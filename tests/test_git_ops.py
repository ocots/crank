"""PR ouverte ou mise à jour par `finalize` (gh simulé)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crank import git_ops


@pytest.fixture
def gh(monkeypatch):
    """Simule `gh` : `existantes` est la réponse de `pr list`, les appels sont notés."""
    appels: list[list[str]] = []
    etat = {"existantes": []}

    def faux_gh(args, cwd, check=True):
        appels.append(args)
        if args[:2] == ["pr", "list"]:
            return json.dumps(etat["existantes"])
        if args[:2] == ["pr", "create"]:
            return "https://example.invalid/pr/1"
        return ""

    monkeypatch.setattr(git_ops, "gh", faux_gh)
    return appels, etat


def test_cree_quand_aucune_pr(gh):
    appels, _ = gh
    url, creee = git_ops.open_or_update_pr(Path("."), "task/3-x", "T (#3)", "Closes #3", "main")
    assert (url, creee) == ("https://example.invalid/pr/1", True)
    assert appels[-1][:2] == ["pr", "create"]


def test_met_a_jour_la_pr_ouverte(gh):
    appels, etat = gh
    etat["existantes"] = [{"url": "https://example.invalid/pr/9", "state": "OPEN"}]
    url, creee = git_ops.open_or_update_pr(Path("."), "task/3-x", "T (#3)", "Closes #3\n\n## Bilan", "main")
    assert (url, creee) == ("https://example.invalid/pr/9", False)
    edit = appels[-1]
    assert edit[:3] == ["pr", "edit", "https://example.invalid/pr/9"]
    assert edit[edit.index("--body") + 1].startswith("Closes #3")
    assert edit[edit.index("--title") + 1] == "T (#3)"
    assert not any(a[:2] == ["pr", "create"] for a in appels)


def test_pr_fusionnee_refusee(gh):
    _, etat = gh
    etat["existantes"] = [{"url": "https://example.invalid/pr/9", "state": "MERGED"}]
    with pytest.raises(git_ops.GitError, match="merged"):
        git_ops.open_or_update_pr(Path("."), "task/3-x", "T (#3)", "Closes #3", "main")
