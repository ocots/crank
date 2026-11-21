from __future__ import annotations

import pytest

from crank.naming import branch_name, number_from_branch, run_filename, slugify


class TestSlugify:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Locate — homographie robuste", "locate-homographie-robuste"),
            ("  Espaces  multiples  ", "espaces-multiples"),
            ("Déjà accentué !", "deja-accentue"),
            ("Règlement mensuel", "reglement-mensuel"),
            ("Le cœur de l'été", "le-coeur-de-l-ete"),
            ("Ça marche, Œuvre", "ca-marche-oeuvre"),
            ("", "tache"),
            ("///", "tache"),
        ],
    )
    def test_cas(self, text, expected):
        assert slugify(text) == expected

    def test_tronque_sans_tiret_final(self):
        assert not slugify("a" * 10 + " " + "b" * 60, limit=12).endswith("-")


class TestBranchName:
    def test_format(self):
        assert branch_name(42, "Locate robuste") == "task/42-locate-robuste"


class TestRunFilename:
    def test_numero_sur_quatre_chiffres_pour_trier(self):
        assert run_filename(7, "Locate") == "0007-locate.md"
        assert run_filename(1234, "Locate") == "1234-locate.md"

    def test_tri_lexicographique_suit_le_numero(self):
        noms = sorted(run_filename(n, "x") for n in (2, 10, 1))
        assert noms == ["0001-x.md", "0002-x.md", "0010-x.md"]


class TestNumberFromBranch:
    @pytest.mark.parametrize(
        "branch, expected",
        [
            ("task/42-locate-robuste", 42),
            ("task/7", 7),
            ("main", None),
            ("feature/42-x", None),
            ("task/abc", None),
        ],
    )
    def test_extraction(self, branch, expected):
        assert number_from_branch(branch) == expected
