"""Conventions de nommage — branches, worktrees, fichiers de suivi.

Regroupées ici pour qu'une branche, son worktree et son suivi portent
toujours le même slug, calculé une seule fois.
"""

from __future__ import annotations

import re
import unicodedata

# NFKD ne décompose pas les ligatures : on les écrit en toutes lettres d'abord.
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss"})


def slugify(text: str, limit: int = 40) -> str:
    """« Règlement du cœur » → `reglement-du-coeur` : les accents sont translittérés,
    pas remplacés par des tirets."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_LIGATURES))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return slug[:limit].rstrip("-") or "tache"


def branch_name(number: int, title: str) -> str:
    return f"task/{number}-{slugify(title)}"


def run_filename(number: int, title: str) -> str:
    return f"{number:04d}-{slugify(title)}.md"


def number_from_branch(branch: str) -> int | None:
    match = re.fullmatch(r"task/(\d+)(?:-.*)?", branch)
    return int(match.group(1)) if match else None
