from __future__ import annotations

import pytest

from crank.checks import CheckResult, finalize_gate, logic_unchanged, path_allowed

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
