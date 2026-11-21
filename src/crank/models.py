"""Modèles purs. Aucune E/S, aucune dépendance à git, gh ou au disque."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

CLAIM_LABEL = "in-progress"
BLOCKED_LABEL = "blocked"
HUMAN_ONLY_LABEL = "human-only"
FAILED_LABEL = "agent:failed"
REVIEW_LABEL = "needs-human-review"
TASK_LABEL = "task"
PRIORITY_LABEL = "priority:high"
ROLE_PREFIX = "role:"

DECISION_ACTEE = "actée"
DECISION_PROPOSEE = "proposée"
DECISION_REJETEE = "rejetée"

_TASK_REF = re.compile(r"^#(\d+)$")


def task_ref_number(ref: str) -> int | None:
    """`"#12"` → 12 ; toute autre référence (une décision) → None."""
    match = _TASK_REF.match(ref)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class TaskSpec:
    """Le bloc ```crank d'une issue. `done` est le champ qui décide de tout."""

    role: str
    done: str
    touche: tuple[str, ...] = ()
    bloque_sur: tuple[str, ...] = ()
    budget: str = ""

    @property
    def decision_refs(self) -> tuple[str, ...]:
        return tuple(r for r in self.bloque_sur if task_ref_number(r) is None)

    @property
    def task_refs(self) -> tuple[int, ...]:
        """Les tâches (issues) dont celle-ci dépend : `bloque_sur: ["#12"]`."""
        return tuple(n for r in self.bloque_sur if (n := task_ref_number(r)) is not None)


@dataclass(frozen=True)
class Task:
    number: int
    title: str
    labels: frozenset[str] = frozenset()
    assignees: tuple[str, ...] = ()
    spec: TaskSpec | None = None
    spec_error: str = ""

    @property
    def claimed(self) -> bool:
        return CLAIM_LABEL in self.labels or bool(self.assignees)

    @property
    def human_only(self) -> bool:
        return HUMAN_ONLY_LABEL in self.labels

    @property
    def blocked(self) -> bool:
        return BLOCKED_LABEL in self.labels

    @property
    def failed(self) -> bool:
        """Un échec n'est jamais retenté tout seul : retirer le label remet en jeu."""
        return FAILED_LABEL in self.labels

    @property
    def high_priority(self) -> bool:
        return PRIORITY_LABEL in self.labels

    @property
    def role(self) -> str:
        if self.spec is not None:
            return self.spec.role
        for label in self.labels:
            if label.startswith(ROLE_PREFIX):
                return label[len(ROLE_PREFIX) :]
        return ""

    @property
    def ref(self) -> str:
        return f"#{self.number}"


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    branch: str
    labels: frozenset[str] = frozenset()
    is_draft: bool = False
    review_decision: str = ""
    task_number: int | None = None

    @property
    def needs_author_action(self) -> bool:
        """Le relecteur a demandé des changements : à traiter avant d'ouvrir du neuf."""
        return self.review_decision == "CHANGES_REQUESTED"

    @property
    def counts_against_wip(self) -> bool:
        return not self.is_draft


@dataclass(frozen=True)
class Decision:
    ref: str
    title: str
    status: str
    path: str = ""

    @property
    def settled(self) -> bool:
        return self.status in (DECISION_ACTEE, DECISION_REJETEE)


@dataclass(frozen=True)
class RepoState:
    ci_main_ok: bool = True
    tasks: tuple[Task, ...] = ()
    prs: tuple[PullRequest, ...] = ()
    decisions: tuple[Decision, ...] = ()
    # Issues fermées parmi celles que référence un `bloque_sur`. Une issue ouverte est
    # dans `tasks` ; une issue ni ouverte ni fermée est inconnue, et bloque.
    closed_issues: frozenset[int] = frozenset()

    def decision(self, ref: str) -> Decision | None:
        for d in self.decisions:
            if d.ref == ref:
                return d
        return None

    def task(self, number: int) -> Task | None:
        for t in self.tasks:
            if t.number == number:
                return t
        return None

    @property
    def open_wip(self) -> int:
        return sum(1 for pr in self.prs if pr.counts_against_wip)

    @property
    def in_progress_tasks(self) -> tuple[Task, ...]:
        return tuple(t for t in self.tasks if t.claimed)


class Action(str, Enum):
    FIX_CI = "fix-ci"
    ADDRESS_REVIEW = "address-review"
    WORK_TASK = "work-task"
    STOP = "stop"


class Tier(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"


@dataclass(frozen=True)
class Plan:
    """Ce que le scheduler décide. Entièrement déterminé par (RepoState, Config)."""

    action: Action
    tier: Tier
    reason: str
    task: Task | None = None
    pr: PullRequest | None = None
    role: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    skipped: tuple[tuple[int, str], ...] = field(default_factory=tuple)

    @property
    def actionable(self) -> bool:
        return self.action is not Action.STOP
