"""Vérifications exécutées contre un vrai dépôt git temporaire.

Le scheduler se teste sur des états simulés ; ces fonctions-là, non : elles parlent
à git. C'est exactement là que se cachent les bugs qu'un test sur mock ne verrait pas.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from crank.checks import (
    changed_files,
    check_docstrings_only,
    check_scope,
    check_size,
    diff_size,
)
from crank.config import Role
from crank.models import Tier


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "depot"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "test@example.invalid")
    git(r, "config", "user.name", "test")
    (r / "src").mkdir()
    (r / "tests").mkdir()
    (r / "src" / "mod.py").write_text('def f(x):\n    """Vieille."""\n    return x + 1\n')
    (r / "tests" / "test_mod.py").write_text("def test_f():\n    assert True\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "socle")
    git(r, "branch", "base")
    return r


FEATURE = Role("feature", Tier.P2, ("src/**", "tests/**"))
TESTS_ONLY = Role("test", Tier.P3, ("tests/**",))
DOC = Role("doc", Tier.P4, ("docs/**", "src/**"), docstrings_only=True)


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


class TestDiff:
    def test_fichiers_modifies(self, repo):
        (repo / "src" / "mod.py").write_text("def f(x):\n    return x + 2\n")
        commit(repo, "change")
        assert changed_files(repo, "base") == ("src/mod.py",)

    def test_taille_du_diff(self, repo):
        (repo / "src" / "neuf.py").write_text("\n".join(f"x = {i}" for i in range(20)) + "\n")
        commit(repo, "ajout")
        assert diff_size(repo, "base") >= 20

    def test_aucun_changement(self, repo):
        assert changed_files(repo, "base") == ()


class TestPerimetre:
    def test_role_test_hors_perimetre_refuse(self, repo):
        (repo / "src" / "mod.py").write_text("def f(x):\n    return 0\n")
        commit(repo, "triche")
        result = check_scope(repo, "base", TESTS_ONLY)
        assert not result.ok
        assert "src/mod.py" in result.detail

    def test_role_test_dans_son_perimetre_accepte(self, repo):
        (repo / "tests" / "test_mod.py").write_text("def test_f():\n    assert 1 == 1\n")
        commit(repo, "vrais tests")
        assert check_scope(repo, "base", TESTS_ONLY).ok

    def test_role_feature_couvre_src_et_tests(self, repo):
        (repo / "src" / "mod.py").write_text("def f(x):\n    return x + 2\n")
        (repo / "tests" / "test_mod.py").write_text("def test_f():\n    assert 1\n")
        commit(repo, "les deux")
        assert check_scope(repo, "base", FEATURE).ok

    def test_fichier_racine_hors_perimetre(self, repo):
        (repo / "pyproject.toml").write_text("[project]\n")
        commit(repo, "config")
        assert not check_scope(repo, "base", FEATURE).ok


class TestTaille:
    def test_sous_le_plafond(self, repo):
        (repo / "src" / "mod.py").write_text("def f(x):\n    return x + 2\n")
        commit(repo, "petit")
        assert check_size(repo, "base", 300).ok

    def test_au_dessus_du_plafond(self, repo):
        (repo / "src" / "gros.py").write_text("\n".join(f"x{i} = {i}" for i in range(400)) + "\n")
        commit(repo, "gros")
        result = check_size(repo, "base", 300)
        assert not result.ok
        assert "découpe" in result.detail


class TestDocstringsOnly:
    def test_docstring_seule_acceptee(self, repo):
        (repo / "src" / "mod.py").write_text('def f(x):\n    """Neuve et claire."""\n    return x + 1\n')
        commit(repo, "doc")
        assert check_docstrings_only(repo, "base", DOC).ok

    def test_logique_modifiee_refusee(self, repo):
        (repo / "src" / "mod.py").write_text('def f(x):\n    """Vieille."""\n    return x + 99\n')
        commit(repo, "logique déguisée en doc")
        result = check_docstrings_only(repo, "base", DOC)
        assert not result.ok
        assert "src/mod.py" in result.detail

    def test_fichier_python_ajoute_refuse(self, repo):
        (repo / "src" / "neuf.py").write_text("def g():\n    return 1\n")
        commit(repo, "nouveau module")
        assert not check_docstrings_only(repo, "base", DOC).ok

    def test_non_python_ignore(self, repo):
        (repo / "docs").mkdir()
        (repo / "docs" / "guide.md").write_text("# Guide\n")
        commit(repo, "markdown")
        assert check_docstrings_only(repo, "base", DOC).ok

    def test_non_applicable_pour_les_autres_roles(self, repo):
        (repo / "src" / "mod.py").write_text("def f(x):\n    return 0\n")
        commit(repo, "libre")
        assert check_docstrings_only(repo, "base", FEATURE).ok
