"""Extraction du bloc ```crank depuis le corps d'une issue.

Format attendu :

    ```crank
    role: feature
    done: pytest tests/vision/test_locate.py -q
    touche:
      - src/exam_core/vision/**
      - tests/vision/**
    bloque_sur: ["0007"]
    budget: 1 session
    ```

Une tâche sans `done` exécutable n'est pas recevable : c'est le filtre qui empêche
le système de produire du bruit (voir §4 du document de conception).
"""

from __future__ import annotations

import re

import yaml

from .models import TaskSpec

_BLOCK = re.compile(r"```crank\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


class SpecError(ValueError):
    pass


def _as_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    raise SpecError(f"champ « {field} » : liste ou chaîne attendue")


def parse_spec(body: str | None) -> TaskSpec:
    """Lève SpecError si le bloc est absent, illisible ou incomplet."""
    if not body:
        raise SpecError("corps d'issue vide : bloc ```crank absent")
    match = _BLOCK.search(body)
    if not match:
        raise SpecError("bloc ```crank absent")
    try:
        raw = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SpecError(f"bloc ```crank illisible : {exc}") from exc
    if not isinstance(raw, dict):
        raise SpecError("bloc ```crank : un dictionnaire est attendu")

    role = str(raw.get("role", "")).strip()
    if not role:
        raise SpecError("champ « role » manquant")

    done = str(raw.get("done", "")).strip()
    if not done:
        raise SpecError("champ « done » manquant — pas de critère vérifiable, pas de tâche")

    return TaskSpec(
        role=role,
        done=done,
        touche=_as_tuple(raw.get("touche"), "touche"),
        bloque_sur=tuple(str(r).strip() for r in _as_tuple(raw.get("bloque_sur"), "bloque_sur")),
        budget=str(raw.get("budget", "")).strip(),
    )


def try_parse_spec(body: str | None) -> tuple[TaskSpec | None, str]:
    try:
        return parse_spec(body), ""
    except SpecError as exc:
        return None, str(exc)
