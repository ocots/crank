"""Configuration lue depuis `.crank.toml` à la racine du dépôt cible."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .models import Tier

CONFIG_NAME = ".crank.toml"


@dataclass(frozen=True)
class Role:
    name: str
    tier: Tier
    paths: tuple[str, ...]
    docstrings_only: bool = False
    brief: str = ""


@dataclass(frozen=True)
class SensitivePattern:
    name: str
    regex: str


@dataclass(frozen=True)
class SensitiveRules:
    """Ce qui ne doit jamais entrer dans le dépôt : données personnelles, secrets.

    `allowed_paths` désigne les zones où les données fictives sont permises (fixtures de
    test) : elles échappent aux deux contrôles, chemins et motifs.
    """

    forbidden_paths: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    patterns: tuple[SensitivePattern, ...] = ()

    @property
    def declared(self) -> bool:
        return bool(self.forbidden_paths or self.patterns)


DEFAULT_ROLES: dict[str, Role] = {
    "feature": Role("feature", Tier.P2, ("src/**", "tests/**")),
    "test": Role("test", Tier.P3, ("tests/**",)),
    "doc": Role(
        "doc",
        Tier.P4,
        ("docs/**", "README.md", "examples/**", "src/**"),
        docstrings_only=True,
    ),
}


@dataclass(frozen=True)
class Config:
    wip_max: int = 4
    max_diff_lines: int = 300
    size_exclude: tuple[str, ...] = ()
    deletion_weight: float = 1.0
    main_branch: str = "main"
    decisions_dir: str = "decisions"
    worktree_root: str = ".."
    roles: dict[str, Role] = field(default_factory=lambda: dict(DEFAULT_ROLES))
    checks: dict[str, str] = field(default_factory=dict)
    sensitive: SensitiveRules = field(default_factory=SensitiveRules)

    def role(self, name: str) -> Role | None:
        return self.roles.get(name)

    def tier_of(self, role_name: str) -> Tier | None:
        role = self.roles.get(role_name)
        return role.tier if role else None


def _weight(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 1:
        raise ValueError(f"deletion_weight : un nombre entre 0 et 1 attendu, pas « {raw} »")
    return float(raw)


def _parse_roles(raw: dict) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            continue
        tier_raw = str(body.get("tier", "P2"))
        try:
            tier = Tier(tier_raw)
        except ValueError as exc:
            raise ValueError(f"rôle « {name} » : tier « {tier_raw} » inconnu") from exc
        roles[name] = Role(
            name=name,
            tier=tier,
            paths=tuple(body.get("paths", ())),
            docstrings_only=bool(body.get("docstrings_only", False)),
            brief=str(body.get("brief", "")),
        )
    return roles


def _parse_sensitive(raw: dict) -> SensitiveRules:
    patterns: list[SensitivePattern] = []
    for i, body in enumerate(raw.get("patterns", ())):
        if not isinstance(body, dict) or not body.get("name") or not body.get("regex"):
            raise ValueError(f"[sensitive] motif n°{i + 1} : `name` et `regex` attendus")
        name, regex = str(body["name"]), str(body["regex"])
        try:
            re.compile(regex)
        except re.error as exc:
            raise ValueError(f"[sensitive] motif « {name} » : regex invalide ({exc})") from exc
        patterns.append(SensitivePattern(name, regex))
    return SensitiveRules(
        forbidden_paths=tuple(raw.get("forbidden_paths", ())),
        allowed_paths=tuple(raw.get("allowed_paths", ())),
        patterns=tuple(patterns),
    )


def load_config(root: Path) -> Config:
    path = root / CONFIG_NAME
    if not path.is_file():
        return Config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    section = raw.get("crank", {})
    roles = _parse_roles(raw.get("roles", {})) or dict(DEFAULT_ROLES)
    return Config(
        wip_max=int(section.get("wip_max", 4)),
        max_diff_lines=int(section.get("max_diff_lines", 300)),
        size_exclude=tuple(section.get("size_exclude", ())),
        deletion_weight=_weight(section.get("deletion_weight", 1)),
        main_branch=str(section.get("main_branch", "main")),
        decisions_dir=str(section.get("decisions_dir", "decisions")),
        worktree_root=str(section.get("worktree_root", "..")),
        roles=roles,
        checks=dict(raw.get("checks", {})),
        sensitive=_parse_sensitive(raw.get("sensitive", {})),
    )
