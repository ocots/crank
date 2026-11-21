from __future__ import annotations

import pytest

from crank.taskspec import SpecError, parse_spec, try_parse_spec

VALID = """
Contexte de la tâche, en prose.

```crank
role: feature
done: pytest tests/vision/test_locate.py -q
touche:
  - src/exam_core/vision/**
  - tests/vision/**
bloque_sur: ["0007"]
budget: 1 session
```
"""


def test_bloc_complet():
    spec = parse_spec(VALID)
    assert spec.role == "feature"
    assert spec.done == "pytest tests/vision/test_locate.py -q"
    assert spec.touche == ("src/exam_core/vision/**", "tests/vision/**")
    assert spec.bloque_sur == ("0007",)
    assert spec.budget == "1 session"


def test_champs_optionnels_absents():
    spec = parse_spec("```crank\nrole: doc\ndone: mkdocs build\n```")
    assert spec.touche == () and spec.bloque_sur == ()


def test_touche_en_chaine_simple():
    spec = parse_spec("```crank\nrole: doc\ndone: x\ntouche: docs/**\n```")
    assert spec.touche == ("docs/**",)


@pytest.mark.parametrize(
    "body, fragment",
    [
        (None, "vide"),
        ("", "vide"),
        ("aucun bloc ici", "absent"),
        ("```crank\ndone: pytest\n```", "role"),
        ("```crank\nrole: feature\n```", "done"),
        ("```crank\nrole: feature\ndone: '   '\n```", "done"),
        ("```crank\n- ceci est une liste\n```", "dictionnaire"),
    ],
)
def test_specs_invalides(body, fragment):
    with pytest.raises(SpecError) as exc:
        parse_spec(body)
    assert fragment in str(exc.value)


def test_le_message_derreur_explique_pourquoi():
    with pytest.raises(SpecError) as exc:
        parse_spec("```crank\nrole: feature\n```")
    assert "pas de critère vérifiable" in str(exc.value)


def test_try_parse_ne_leve_pas():
    spec, error = try_parse_spec("rien")
    assert spec is None and "absent" in error


def test_bloc_insensible_a_la_casse():
    assert parse_spec("```CRANK\nrole: test\ndone: pytest\n```").role == "test"


class TestBloqueSur:
    """`bloque_sur` mêle décisions (`"0007"`) et tâches (`"#12"`)."""

    def test_decisions_et_taches_separees(self):
        spec = parse_spec('```crank\nrole: f\ndone: x\nbloque_sur: ["0007", "#12"]\n```')
        assert spec.bloque_sur == ("0007", "#12")
        assert spec.decision_refs == ("0007",)
        assert spec.task_refs == (12,)

    def test_tache_en_liste_yaml(self):
        spec = parse_spec('```crank\nrole: f\ndone: x\nbloque_sur:\n  - "#3"\n```')
        assert spec.task_refs == (3,)

    def test_reference_de_tache_mal_formee(self):
        with pytest.raises(SpecError) as exc:
            parse_spec('```crank\nrole: f\ndone: x\nbloque_sur: ["#abc"]\n```')
        assert "#<numéro>" in str(exc.value)

    @pytest.mark.parametrize(
        "ligne",
        [
            "bloque_sur: #12",          # la clé devient vide
            "bloque_sur:\n  - #12",     # l'élément devient vide
        ],
    )
    def test_diese_sans_guillemets_explique(self, ligne):
        """Sans guillemets, YAML lit `#12` comme un commentaire : la dépendance
        disparaîtrait sans bruit. Le message doit dire quoi faire."""
        with pytest.raises(SpecError) as exc:
            parse_spec(f"```crank\nrole: f\ndone: x\n{ligne}\n```")
        assert "guillemets" in str(exc.value)

    def test_diese_sans_guillemets_en_liste_entre_crochets(self):
        with pytest.raises(SpecError):
            parse_spec("```crank\nrole: f\ndone: x\nbloque_sur: [#12]\n```")
