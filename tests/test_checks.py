from __future__ import annotations

import pytest

from crank.checks import logic_unchanged, path_allowed

BASE = '''
def f(x):
    """Ancienne docstring."""
    return x + 1
'''


class TestPathAllowed:
    @pytest.mark.parametrize(
        "path, patterns, expected",
        [
            ("src/a.py", ("src/**",), True),
            ("src/deep/nested/a.py", ("src/**",), True),
            ("tests/t.py", ("tests/**",), True),
            ("src/a.py", ("tests/**",), False),
            ("README.md", ("README.md",), True),
            ("docs/x/y.md", ("docs/**",), True),
            ("pyproject.toml", ("src/**", "tests/**"), False),
        ],
    )
    def test_correspondances(self, path, patterns, expected):
        assert path_allowed(path, patterns) is expected


class TestLogicUnchanged:
    """Ce qui permet au rôle `doc` de toucher src/** sans pouvoir changer la logique."""

    def test_docstring_modifiee_seule(self):
        new = BASE.replace("Ancienne docstring.", "Nouvelle docstring, bien plus claire.")
        assert logic_unchanged(BASE, new)

    def test_docstring_ajoutee(self):
        old = "def f(x):\n    return x + 1\n"
        new = 'def f(x):\n    """Ajoutée."""\n    return x + 1\n'
        assert logic_unchanged(old, new)

    def test_logique_modifiee_detectee(self):
        assert not logic_unchanged(BASE, BASE.replace("x + 1", "x + 2"))

    def test_ajout_de_fonction_detecte(self):
        assert not logic_unchanged(BASE, BASE + "\ndef g():\n    return 0\n")

    def test_commentaire_seul_ne_compte_pas_comme_logique(self):
        assert logic_unchanged(BASE, BASE.replace("return x + 1", "return x + 1  # noqa"))

    def test_docstring_de_module(self):
        old = '"""Vieux."""\nX = 1\n'
        new = '"""Neuf, plus long."""\nX = 1\n'
        assert logic_unchanged(old, new)

    def test_fonction_reduite_a_sa_docstring(self):
        old = 'def f():\n    """D."""\n'
        assert logic_unchanged(old, old.replace('"""D."""', '"""Autre."""'))

    def test_syntaxe_invalide_refusee(self):
        assert not logic_unchanged(BASE, "def f(:\n")
