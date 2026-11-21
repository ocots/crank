"""Le fichier de suivi doit survivre au renommage de son issue."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import make_task

from crank import taskfile
from crank.taskfile import RUNS_DIR, TaskFileError


class TestRetrouveParNumero:
    def test_cree_puis_relu(self, tmp_path):
        task = make_task(7, title="Locate robuste")
        path = taskfile.write(tmp_path, task)
        assert path.name == "0007-locate-robuste.md"
        assert taskfile.read(tmp_path, task).path == path

    def test_issue_renommee_apres_setup(self, tmp_path):
        """Le cas réel : on découpe une tâche trop grosse, donc on renomme son issue."""
        avant = make_task(1, title="Socle et règlement")
        path = taskfile.write(tmp_path, avant)
        apres = replace(avant, title="Socle seulement")
        assert taskfile.read(tmp_path, apres).path == path

    def test_ecrire_ne_cree_pas_de_doublon_apres_renommage(self, tmp_path):
        avant = make_task(1, title="Ancien titre")
        taskfile.write(tmp_path, avant)
        taskfile.write(tmp_path, replace(avant, title="Nouveau titre"))
        assert len(list((tmp_path / RUNS_DIR).glob("0001-*.md"))) == 1

    def test_pas_de_confusion_entre_numeros(self, tmp_path):
        taskfile.write(tmp_path, make_task(10, title="Dix"))
        with pytest.raises(TaskFileError):
            taskfile.read(tmp_path, make_task(1, title="Un"))

    def test_absent_message_clair(self, tmp_path):
        with pytest.raises(TaskFileError) as exc:
            taskfile.read(tmp_path, make_task(3, title="X"))
        assert "0003-*.md" in str(exc.value) and "crank setup" in str(exc.value)

    def test_plusieurs_suivis_pour_un_numero(self, tmp_path):
        folder = tmp_path / RUNS_DIR
        folder.mkdir(parents=True)
        (folder / "0002-a.md").write_text("x")
        (folder / "0002-b.md").write_text("y")
        with pytest.raises(TaskFileError) as exc:
            taskfile.read(tmp_path, make_task(2, title="c"))
        assert "0002-a.md" in str(exc.value) and "0002-b.md" in str(exc.value)


class TestCorpsDePR:
    def test_le_lien_vers_le_suivi_suit_le_vrai_fichier(self, tmp_path):
        avant = make_task(1, title="Ancien titre")
        taskfile.write(tmp_path, avant)
        apres = replace(avant, title="Nouveau titre")
        body = taskfile.read(tmp_path, apres).pr_body(apres)
        assert f"{RUNS_DIR}/0001-ancien-titre.md" in body
