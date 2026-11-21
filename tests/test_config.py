from __future__ import annotations

from pathlib import Path

import pytest

from crank.config import load_config


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / ".crank.toml").write_text(text, encoding="utf-8")
    return tmp_path


class TestSizeExclude:
    def test_vide_par_defaut(self, tmp_path):
        assert load_config(write(tmp_path, "[crank]\n")).size_exclude == ()

    def test_lue(self, tmp_path):
        config = load_config(write(tmp_path, '[crank]\nsize_exclude = ["uv.lock"]\n'))
        assert config.size_exclude == ("uv.lock",)

    def test_proposee_par_crank_init(self, tmp_path):
        from crank.cli import _DEFAULT_CONFIG

        assert "*.lock" in load_config(write(tmp_path, _DEFAULT_CONFIG)).size_exclude


class TestDeletionWeight:
    def test_un_par_defaut(self, tmp_path):
        assert load_config(write(tmp_path, "[crank]\n")).deletion_weight == 1

    def test_lu(self, tmp_path):
        assert load_config(write(tmp_path, "[crank]\ndeletion_weight = 0.5\n")).deletion_weight == 0.5

    @pytest.mark.parametrize("valeur", ["1.5", "-0.1", '"0.5"', "true"])
    def test_refuse_hors_de_0_1(self, tmp_path, valeur):
        with pytest.raises(ValueError, match="deletion_weight"):
            load_config(write(tmp_path, f"[crank]\ndeletion_weight = {valeur}\n"))


class TestSensitive:
    def test_absente_par_defaut(self, tmp_path):
        rules = load_config(write(tmp_path, "[crank]\n")).sensitive
        assert not rules.declared

    def test_lue(self, tmp_path):
        rules = load_config(
            write(
                tmp_path,
                """
[sensitive]
forbidden_paths = ["*.csv"]
allowed_paths = ["tests/fixtures/**"]
patterns = [{ name = "IBAN", regex = 'FR\\d{2}' }]
""",
            )
        ).sensitive
        assert rules.declared
        assert rules.forbidden_paths == ("*.csv",)
        assert rules.allowed_paths == ("tests/fixtures/**",)
        assert rules.patterns[0].name == "IBAN"

    def test_regex_invalide_refusee_au_chargement(self, tmp_path):
        """Mieux vaut échouer au chargement qu'au moment où la PR doit être protégée."""
        with pytest.raises(ValueError) as exc:
            load_config(write(tmp_path, "[sensitive]\npatterns = [{ name = \"x\", regex = \"(\" }]\n"))
        assert "« x »" in str(exc.value)

    def test_motif_incomplet_refuse(self, tmp_path):
        with pytest.raises(ValueError) as exc:
            load_config(write(tmp_path, "[sensitive]\npatterns = [{ name = \"x\" }]\n"))
        assert "regex" in str(exc.value)

    def test_la_config_de_crank_init_se_charge(self, tmp_path):
        """La section y est proposée commentée : rien n'est déclaré tant qu'on ne la remplit pas."""
        from crank.cli import _DEFAULT_CONFIG

        assert not load_config(write(tmp_path, _DEFAULT_CONFIG)).sensitive.declared
