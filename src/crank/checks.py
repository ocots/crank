"""Vérifications de finalisation — déterministes, opposables, sans jugement.

Ce sont elles qui rendent les rôles réels plutôt qu'indicatifs : une PR dont le diff
sort du périmètre de son rôle est refusée, pas signalée.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from .config import Role, SensitiveRules


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        return f"{'✓' if self.ok else '✗'} {self.name}" + (f" — {self.detail}" if self.detail else "")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def changed_files(cwd: Path, base: str) -> tuple[str, ...]:
    out = _git(["diff", "--name-only", f"{base}...HEAD"], cwd)
    return tuple(line for line in out.splitlines() if line.strip())


def diff_size(cwd: Path, base: str) -> int:
    out = _git(["diff", "--numstat", f"{base}...HEAD"], cwd)
    total = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            for n in parts[:2]:
                if n.isdigit():
                    total += int(n)
    return total


def path_allowed(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if fnmatch(path, pattern):
            return True
        # `src/**` doit aussi couvrir `src/a/b.py`
        if pattern.endswith("/**") and path.startswith(pattern[:-2]):
            return True
    return False


def check_scope(cwd: Path, base: str, role: Role) -> CheckResult:
    if not role.paths:
        return CheckResult(f"périmètre ({role.name})", True, "aucune restriction déclarée")
    outside = [p for p in changed_files(cwd, base) if not path_allowed(p, role.paths)]
    if outside:
        return CheckResult(
            f"périmètre ({role.name})",
            False,
            "hors périmètre : " + ", ".join(outside[:5]) + ("…" if len(outside) > 5 else ""),
        )
    return CheckResult(f"périmètre ({role.name})", True)


def check_size(cwd: Path, base: str, max_lines: int) -> CheckResult:
    size = diff_size(cwd, base)
    ok = size <= max_lines
    return CheckResult(
        "taille du diff",
        ok,
        f"{size} lignes (plafond {max_lines})"
        + ("" if ok else " — découpe la tâche, une PR relisible ou pas de PR"),
    )


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def logic_unchanged(old_source: str, new_source: str) -> bool:
    """Les deux sources sont-elles identiques une fois les docstrings retirées ?

    Permet au rôle `doc` de toucher `src/**` sans pouvoir modifier la logique.
    """
    try:
        old = _strip_docstrings(ast.parse(old_source))
        new = _strip_docstrings(ast.parse(new_source))
    except SyntaxError:
        return False
    return ast.dump(old, include_attributes=False) == ast.dump(new, include_attributes=False)


def check_docstrings_only(cwd: Path, base: str, role: Role) -> CheckResult:
    if not role.docstrings_only:
        return CheckResult("docstrings seules", True, "non applicable")
    offenders: list[str] = []
    for path in changed_files(cwd, base):
        if not path.endswith(".py"):
            continue
        try:
            old = _git(["show", f"{base}:{path}"], cwd)
        except subprocess.CalledProcessError:
            offenders.append(f"{path} (fichier ajouté)")
            continue
        new_path = cwd / path
        if not new_path.is_file():
            offenders.append(f"{path} (supprimé)")
            continue
        if not logic_unchanged(old, new_path.read_text(encoding="utf-8")):
            offenders.append(path)
    if offenders:
        return CheckResult(
            "docstrings seules",
            False,
            "logique modifiée dans : " + ", ".join(offenders[:5]),
        )
    return CheckResult("docstrings seules", True)


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(diff: str) -> list[tuple[str, int, str]]:
    """Les lignes AJOUTÉES d'un `git diff -U0`, avec leur fichier et leur numéro.

    Seules les lignes ajoutées comptent : une donnée qu'on retire ou qui était déjà là
    n'est pas l'affaire de cette PR.
    """
    lines: list[tuple[str, int, str]] = []
    path: str | None = None
    lineno = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = target[2:] if target.startswith("b/") else None  # /dev/null : supprimé
        elif raw.startswith("@@"):
            match = _HUNK.match(raw)
            lineno = int(match.group(1)) if match else 0
        elif raw.startswith("+") and path is not None:
            lines.append((path, lineno, raw[1:]))
            lineno += 1
    return lines


def scan_sensitive(
    files: tuple[str, ...], lines: list[tuple[str, int, str]], rules: SensitiveRules
) -> list[str]:
    """Ce qui enfreint les règles, désigné par fichier, ligne et règle.

    **Jamais la valeur trouvée** : le rapport finit dans un terminal, un log, parfois un
    corps de PR — le recopier y ferait fuir exactement ce qu'on cherche à retenir.
    """
    offenders: list[str] = []
    for path in files:
        forbidden = path_allowed(path, rules.forbidden_paths)
        if forbidden and not path_allowed(path, rules.allowed_paths):
            offenders.append(f"{path} (chemin interdit)")
    compiled = [(p.name, re.compile(p.regex)) for p in rules.patterns]
    for path, lineno, text in lines:
        if path_allowed(path, rules.allowed_paths):
            continue
        for name, regex in compiled:
            if regex.search(text):
                offenders.append(f"{path}:{lineno} ({name})")
    return offenders


def check_sensitive(cwd: Path, base: str, rules: SensitiveRules) -> CheckResult:
    if not rules.declared:
        return CheckResult("données sensibles", True, "aucune règle déclarée")
    quiet = ["-c", "core.quotePath=false"]  # chemins accentués en clair, pas en octal
    names = _git([*quiet, "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"], cwd)
    files = tuple(line for line in names.splitlines() if line.strip())
    diff = _git([*quiet, "diff", "-U0", "--no-color", "--no-ext-diff", f"{base}...HEAD"], cwd)
    offenders = scan_sensitive(files, added_lines(diff), rules)
    if offenders:
        return CheckResult(
            "données sensibles",
            False,
            ", ".join(offenders[:5]) + ("…" if len(offenders) > 5 else ""),
        )
    return CheckResult("données sensibles", True)


def diff_hygiene(
    cwd: Path, base: str, role: Role, max_lines: int, rules: SensitiveRules
) -> list[CheckResult]:
    """Les vérifications que rien ne contourne, pas même `--draft`.

    Un brouillon reste une PR : ni un diff hors périmètre, ni une donnée sensible n'y
    ont leur place. Une donnée poussée ne se rattrape pas.
    """
    return [
        check_scope(cwd, base, role),
        check_size(cwd, base, max_lines),
        check_docstrings_only(cwd, base, role),
        check_sensitive(cwd, base, rules),
    ]


def run_command(name: str, command: str, cwd: Path) -> CheckResult:
    proc = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True)
    if proc.returncode == 0:
        return CheckResult(name, True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
    return CheckResult(name, False, "\n    " + "\n    ".join(tail))


def finalize_gate(
    hard: list[CheckResult], soft: list[CheckResult], draft: bool
) -> tuple[bool, bool]:
    """Décide si `finalize` doit refuser — extrait pour être testable sans parler à
    git ni à `gh`, ce que le reste de `finalize` doit faire.

    Retourne `(bloque, critere_manquant)`. L'hygiène du diff (`hard` : périmètre,
    taille, docstrings, données sensibles) bloque toujours. Le critère `done` et les vérifications
    personnalisées (`soft`) ne bloquent qu'en dehors de `--draft` — sans ça, `--draft`
    ne pourrait jamais montrer un travail précisément incomplet, ce qui est son but.
    """
    failed_soft = any(not r.ok for r in soft)
    bloque = any(not r.ok for r in hard) or (failed_soft and not draft)
    return bloque, failed_soft
