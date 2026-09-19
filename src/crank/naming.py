"""Conventions de nommage — branches, worktrees, fichiers de suivi.

Regroupées ici pour qu'une branche, son worktree et son suivi portent
toujours le même slug, calculé une seule fois.
"""

from __future__ import annotations

import re


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "tache"


def branch_name(number: int, title: str) -> str:
    return f"task/{number}-{slugify(title)}"


def run_filename(number: int, title: str) -> str:
    return f"{number:04d}-{slugify(title)}.md"


def number_from_branch(branch: str) -> int | None:
    match = re.fullmatch(r"task/(\d+)(?:-.*)?", branch)
    return int(match.group(1)) if match else None
