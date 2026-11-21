"""Opérations git et gh à effet de bord. Déterministes, jamais décidées par un agent."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .naming import slugify


class GitError(RuntimeError):
    pass


def run(args: list[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise GitError(f"{' '.join(args[:4])} : {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def repo_root(start: Path) -> Path:
    out = run(["git", "rev-parse", "--show-toplevel"], start)
    return Path(out)


def current_branch(cwd: Path) -> str:
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)


def is_dirty(cwd: Path) -> bool:
    return bool(run(["git", "status", "--porcelain"], cwd))


def worktree_path(root: Path, worktree_root: str, number: int, title: str) -> Path:
    base = (root / worktree_root).resolve()
    return base / f"{root.name}-task-{number}-{slugify(title, 24)}"


def create_worktree(root: Path, path: Path, branch: str, base_branch: str) -> None:
    run(["git", "fetch", "origin", base_branch], root, check=False)
    start = f"origin/{base_branch}"
    if not run(["git", "rev-parse", "--verify", "--quiet", start], root, check=False):
        start = base_branch
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "-b", branch, str(path), start], root)


def remove_worktree(root: Path, path: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(path)], root, check=False)


def gh(args: list[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise GitError(f"gh {' '.join(args[:3])} : {proc.stderr.strip()}")
    return proc.stdout.strip()


def claim_issue(cwd: Path, number: int, label: str) -> None:
    gh(["issue", "edit", str(number), "--add-label", label, "--add-assignee", "@me"], cwd)


def release_issue(cwd: Path, number: int, label: str) -> None:
    gh(["issue", "edit", str(number), "--remove-label", label], cwd, check=False)


def mark_failed(cwd: Path, number: int, claim_label: str, failed_label: str, reason: str) -> None:
    """Libère la réclamation ET pose la marque d'échec. Jamais l'un sans l'autre."""
    gh(["issue", "comment", str(number), "--body", f"Échec de l'agent : {reason}"], cwd, check=False)
    gh(
        ["issue", "edit", str(number), "--remove-label", claim_label, "--add-label", failed_label],
        cwd,
        check=False,
    )


def ensure_labels(cwd: Path, labels: dict[str, str]) -> None:
    for name, color in labels.items():
        gh(["label", "create", name, "--color", color, "--force"], cwd, check=False)


def open_pr(cwd: Path, title: str, body: str, base: str, draft: bool = False) -> str:
    args = ["pr", "create", "--title", title, "--body", body, "--base", base]
    if draft:
        args.append("--draft")
    return gh(args, cwd)
