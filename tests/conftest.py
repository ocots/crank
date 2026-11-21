from __future__ import annotations

import pytest

from crank.config import Config
from crank.models import (
    CLAIM_LABEL,
    DECISION_ACTEE,
    DECISION_PROPOSEE,
    Decision,
    PullRequest,
    RepoState,
    Task,
    TaskSpec,
)


def make_task(
    number: int,
    *,
    role: str = "feature",
    done: str = "pytest -q",
    touche: tuple[str, ...] = ("src/a/**",),
    bloque_sur: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
    assignees: tuple[str, ...] = (),
    title: str = "",
    spec: bool = True,
    spec_error: str = "",
) -> Task:
    return Task(
        number=number,
        title=title or f"tâche {number}",
        labels=frozenset(labels),
        assignees=assignees,
        spec=TaskSpec(role=role, done=done, touche=touche, bloque_sur=bloque_sur)
        if spec
        else None,
        spec_error=spec_error,
    )


def make_pr(
    number: int,
    *,
    draft: bool = False,
    review: str = "",
    branch: str = "",
) -> PullRequest:
    return PullRequest(
        number=number,
        title=f"pr {number}",
        branch=branch or f"task/{number}-x",
        is_draft=draft,
        review_decision=review,
        task_number=number,
    )


def make_state(
    *,
    tasks: tuple[Task, ...] = (),
    prs: tuple[PullRequest, ...] = (),
    decisions: tuple[Decision, ...] = (),
    closed: tuple[int, ...] = (),
    ci_ok: bool = True,
) -> RepoState:
    return RepoState(
        ci_main_ok=ci_ok,
        tasks=tasks,
        prs=prs,
        decisions=decisions,
        closed_issues=frozenset(closed),
    )


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def claimed_label() -> str:
    return CLAIM_LABEL


@pytest.fixture
def actee() -> str:
    return DECISION_ACTEE


@pytest.fixture
def proposee() -> str:
    return DECISION_PROPOSEE
