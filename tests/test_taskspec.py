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
