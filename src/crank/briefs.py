"""Briefs de rôle : le « comment travailler » donné à l'agent.

Les *limites* d'un rôle ne sont pas ici — elles sont dans `checks.py`, vérifiées et
opposables. Un brief qui se contenterait d'énoncer des règles serait du vœu pieux.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

ROLES_DIR = ".crank/roles"


def packaged(role: str) -> str | None:
    try:
        return (
            resources.files("crank.templates.roles")
            .joinpath(f"{role}.md")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return None


def load(root: Path, role: str) -> str:
    """Le brief du dépôt s'il existe, sinon celui du paquet, sinon rien."""
    local = root / ROLES_DIR / f"{role}.md"
    if local.is_file():
        return local.read_text(encoding="utf-8")
    return packaged(role) or ""


def install(root: Path, roles: list[str]) -> list[str]:
    target = root / ROLES_DIR
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for role in roles:
        content = packaged(role)
        path = target / f"{role}.md"
        if content and not path.exists():
            path.write_text(content, encoding="utf-8")
            written.append(str(path.relative_to(root)))
    return written


def install_skill(root: Path) -> str | None:
    try:
        content = (
            resources.files("crank.templates").joinpath("SKILL.md").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    target = root / ".claude" / "skills" / "crank" / "SKILL.md"
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target.relative_to(root))
