"""Collecte de l'état réel : `gh`, `git`, et les fichiers de décision.

Tout ce qui touche au monde extérieur est ici, pour que `scheduler.plan` reste pur.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import Config
from .models import (
    Decision,
    DECISION_PROPOSEE,
    PullRequest,
    RepoState,
    Task,
)
from .taskspec import try_parse_spec

_BRANCH_TASK = re.compile(r"task/(\d+)")
_CLOSES = re.compile(r"(?:closes|fixes|resolves)\s+#(\d+)", re.IGNORECASE)
_STATUT = re.compile(r"^statut\s*:\s*(.+?)\s*$", re.MULTILINE)
_TITRE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class StateError(RuntimeError):
    pass


def _run_json(args: list[str], cwd: Path) -> list | dict:
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=60
        ).stdout
    except FileNotFoundError as exc:
        raise StateError("`gh` introuvable — installe GitHub CLI et authentifie-toi") from exc
    except subprocess.CalledProcessError as exc:
        raise StateError(f"{' '.join(args[:3])} a échoué : {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise StateError(f"{' '.join(args[:3])} : délai dépassé") from exc
    return json.loads(out or "[]")


def _labels(raw: dict) -> frozenset[str]:
    return frozenset(lbl["name"] for lbl in raw.get("labels", []) if "name" in lbl)


def collect_tasks(root: Path) -> tuple[Task, ...]:
    raw = _run_json(
        [
            "gh", "issue", "list", "--state", "open", "--limit", "200",
            "--json", "number,title,labels,assignees,body",
        ],
        root,
    )
    tasks: list[Task] = []
    for item in raw:
        spec, error = try_parse_spec(item.get("body"))
        tasks.append(
            Task(
                number=item["number"],
                title=item.get("title", ""),
                labels=_labels(item),
                assignees=tuple(a.get("login", "") for a in item.get("assignees", [])),
                spec=spec,
                spec_error=error,
            )
        )
    return tuple(sorted(tasks, key=lambda t: t.number))


def collect_prs(root: Path) -> tuple[PullRequest, ...]:
    raw = _run_json(
        [
            "gh", "pr", "list", "--state", "open", "--limit", "100",
            "--json", "number,title,labels,isDraft,reviewDecision,headRefName,body",
        ],
        root,
    )
    prs: list[PullRequest] = []
    for item in raw:
        branch = item.get("headRefName", "")
        task_number: int | None = None
        if m := _BRANCH_TASK.search(branch):
            task_number = int(m.group(1))
        elif m := _CLOSES.search(item.get("body") or ""):
            task_number = int(m.group(1))
        prs.append(
            PullRequest(
                number=item["number"],
                title=item.get("title", ""),
                branch=branch,
                labels=_labels(item),
                is_draft=bool(item.get("isDraft", False)),
                review_decision=item.get("reviewDecision") or "",
                task_number=task_number,
            )
        )
    return tuple(sorted(prs, key=lambda p: p.number))


def collect_ci(root: Path, branch: str) -> bool:
    """True si la dernière exécution CI sur `branch` n'est pas en échec.

    Un dépôt sans CI n'est pas considéré comme cassé.
    """
    try:
        raw = _run_json(
            [
                "gh", "run", "list", "--branch", branch, "--limit", "1",
                "--json", "conclusion,status",
            ],
            root,
        )
    except StateError:
        return True
    if not raw:
        return True
    last = raw[0]
    if last.get("status") != "completed":
        return True
    return last.get("conclusion") in ("success", "skipped", "neutral", None)


def collect_decisions(root: Path, config: Config) -> tuple[Decision, ...]:
    folder = root / config.decisions_dir
    if not folder.is_dir():
        return ()
    decisions: list[Decision] = []
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        status_match = _STATUT.search(text)
        title_match = _TITRE.search(text)
        ref = path.stem.split("-", 1)[0]
        decisions.append(
            Decision(
                ref=ref,
                title=title_match.group(1) if title_match else path.stem,
                status=status_match.group(1).strip() if status_match else DECISION_PROPOSEE,
                path=str(path.relative_to(root)),
            )
        )
    return tuple(decisions)


def collect_closed_issues(root: Path, numbers: set[int]) -> frozenset[int]:
    """Parmi `numbers`, les issues fermées.

    On n'interroge que les issues référencées par un `bloque_sur` et absentes des
    issues ouvertes — en pratique une ou deux, pas tout l'historique du dépôt. Une
    issue que `gh` ne trouve pas n'est pas fermée : elle reste bloquante.
    """
    closed: set[int] = set()
    for number in sorted(numbers):
        try:
            raw = _run_json(["gh", "issue", "view", str(number), "--json", "state"], root)
        except StateError:
            continue
        if isinstance(raw, dict) and raw.get("state") == "CLOSED":
            closed.add(number)
    return frozenset(closed)


def collect_merged_open(root: Path, open_numbers: set[int]) -> tuple[tuple[int, int], ...]:
    """Les PR fusionnées de branches `task/<n>-…` dont l'issue `n` est encore ouverte."""
    raw = _run_json(
        ["gh", "pr", "list", "--state", "merged", "--limit", "100", "--json", "number,headRefName"], root
    )
    found: dict[int, int] = {}
    for item in raw:
        if (m := _BRANCH_TASK.search(item.get("headRefName", ""))) and int(m.group(1)) in open_numbers:
            found.setdefault(int(m.group(1)), item["number"])
    return tuple(sorted(found.items()))


def collect(root: Path, config: Config) -> RepoState:
    tasks = collect_tasks(root)
    open_numbers = {t.number for t in tasks}
    referenced = {n for t in tasks if t.spec for n in t.spec.task_refs}
    return RepoState(
        ci_main_ok=collect_ci(root, config.main_branch),
        tasks=tasks,
        prs=collect_prs(root),
        decisions=collect_decisions(root, config),
        closed_issues=collect_closed_issues(root, referenced - open_numbers),
        merged_open=collect_merged_open(root, open_numbers),
    )
