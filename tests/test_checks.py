from __future__ import annotations

import pytest

from crank.checks import (
    CheckResult,
    added_lines,
    finalize_gate,
    logic_unchanged,
    path_allowed,
    scan_sensitive,
)
from crank.config import SensitivePattern, SensitiveRules

OK = CheckResult("x", True)
KO = CheckResult("x", False, "raison")

BASE = '''
def f(x):
    """Ancienne docstring."""
    return x + 1
'''


class TestPathAllowed:
    @pytest.mark.parametrize(
        "path, patterns, expected",
        [
            ("src/a.py", ("src/**",), True),
            ("src/deep/nested/a.py", ("src/**",), True),
            ("tests/t.py", ("tests/**",), True),
            ("src/a.py", ("tests/**",), False),
            ("README.md", ("README.md",), True),
            ("docs/x/y.md", ("docs/**",), True),
            ("pyproject.toml", ("src/**", "tests/**"), False),
        ],
    )
    def test_correspondances(self, path, patterns, expected):
        assert path_allowed(path, patterns) is expected


class TestLogicUnchanged:
    """Ce qui permet au rôle `doc` de toucher src/** sans pouvoir changer la logique."""

    def test_docstring_modifiee_seule(self):
        new = BASE.replace("Ancienne docstring.", "Nouvelle docstring, bien plus claire.")
        assert logic_unchanged(BASE, new)

    def test_docstring_ajoutee(self):
        old = "def f(x):\n    return x + 1\n"
        new = 'def f(x):\n    """Ajoutée."""\n    return x + 1\n'
        assert logic_unchanged(old, new)

    def test_logique_modifiee_detectee(self):
        assert not logic_unchanged(BASE, BASE.replace("x + 1", "x + 2"))

    def test_ajout_de_fonction_detecte(self):
        assert not logic_unchanged(BASE, BASE + "\ndef g():\n    return 0\n")

    def test_commentaire_seul_ne_compte_pas_comme_logique(self):
        assert logic_unchanged(BASE, BASE.replace("return x + 1", "return x + 1  # noqa"))

    def test_docstring_de_module(self):
        old = '"""Vieux."""\nX = 1\n'
        new = '"""Neuf, plus long."""\nX = 1\n'
        assert logic_unchanged(old, new)

    def test_fonction_reduite_a_sa_docstring(self):
        old = 'def f():\n    """D."""\n'
        assert logic_unchanged(old, old.replace('"""D."""', '"""Autre."""'))

    def test_syntaxe_invalide_refusee(self):
        assert not logic_unchanged(BASE, "def f(:\n")


class TestFinalizeGate:
    """`--draft` doit pouvoir montrer un travail précisément incomplet — sans ça,
    l'option promise par le message d'erreur de `finalize` n'a aucun effet."""

    def test_tout_passe(self):
        assert finalize_gate([OK], [OK], draft=False) == (False, False)

    def test_hygiene_du_diff_bloque_meme_en_draft(self):
        """Un périmètre ou une taille hors limite n'est jamais négociable."""
        assert finalize_gate([KO], [OK], draft=True) == (True, False)

    def test_critere_manquant_bloque_hors_draft(self):
        assert finalize_gate([OK], [KO], draft=False) == (True, True)

    def test_critere_manquant_nempeche_pas_le_brouillon(self):
        assert finalize_gate([OK], [KO], draft=True) == (False, True)

    def test_les_deux_en_echec_bloquent_meme_en_draft(self):
        assert finalize_gate([KO], [KO], draft=True) == (True, True)


# Un IBAN de démonstration, au format français — fictif.
IBAN = "FR76 3000 6000 0112 3456 7890 189"
IBAN_RULE = SensitivePattern("IBAN", r"\bFR\d{2}(?:\s?[0-9A-Z]{4}){5}\s?[0-9A-Z]{3}\b")
RULES = SensitiveRules(
    forbidden_paths=("*.csv", "data/**"),
    allowed_paths=("tests/fixtures/**",),
    patterns=(IBAN_RULE,),
)

DIFF = """diff --git a/src/a.py b/src/a.py
index 1..2 100644
--- a/src/a.py
+++ b/src/a.py
@@ -3,0 +4,2 @@ def f():
+x = 1
+y = 2
@@ -10 +12 @@
-ancien = 0
+nouveau = 0
diff --git a/src/vieux.py b/src/vieux.py
deleted file mode 100644
--- a/src/vieux.py
+++ /dev/null
@@ -1 +0,0 @@
-supprime = 1
"""


class TestAddedLines:
    def test_fichier_et_numeros_de_ligne(self):
        assert added_lines(DIFF) == [
            ("src/a.py", 4, "x = 1"),
            ("src/a.py", 5, "y = 2"),
            ("src/a.py", 12, "nouveau = 0"),
        ]

    def test_lignes_supprimees_ignorees(self):
        assert all("supprime" not in text for _, _, text in added_lines(DIFF))

    def test_diff_vide(self):
        assert added_lines("") == []


class TestScanSensitive:
    """Une donnée poussée ne se rattrape pas : c'est une vérification, pas une consigne."""

    def test_chemin_interdit(self):
        assert scan_sensitive(("releve.csv",), [], RULES) == ["releve.csv (chemin interdit)"]

    def test_chemin_interdit_en_profondeur(self):
        assert scan_sensitive(("data/2026/x.txt",), [], RULES) == ["data/2026/x.txt (chemin interdit)"]

    def test_exception_pour_les_fixtures(self):
        assert scan_sensitive(("tests/fixtures/releve.csv",), [], RULES) == []

    def test_motif_dans_une_ligne_ajoutee(self):
        found = scan_sensitive((), [("src/a.py", 7, f"iban = '{IBAN}'")], RULES)
        assert found == ["src/a.py:7 (IBAN)"]

    def test_la_valeur_nest_jamais_recopiee(self):
        found = scan_sensitive((), [("src/a.py", 7, f"iban = '{IBAN}'")], RULES)
        assert all(IBAN not in f and "3000" not in f for f in found)

    def test_motif_permis_dans_les_fixtures(self):
        assert scan_sensitive((), [("tests/fixtures/f.py", 1, IBAN)], RULES) == []

    def test_aucune_regle(self):
        assert scan_sensitive(("x.csv",), [("a.py", 1, IBAN)], SensitiveRules()) == []

    def test_ligne_anodine(self):
        assert scan_sensitive(("src/a.py",), [("src/a.py", 1, "total = 3")], RULES) == []
