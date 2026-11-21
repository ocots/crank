"""Le fichier de suivi d'une tâche — mémoire de l'agent, puis description de PR.

Il vit dans `.crank/runs/`, il est **commité avec la PR et conservé** : un agent qui
intervient plus tard sur le même terrain doit pouvoir lire ce qui a déjà été tenté.
C'est la mémoire longue du projet — celle que ni `git log` ni le diff ne donnent.

Triple emploi, voulu :
  1. mémoire de travail — l'agent peut être interrompu et reprendre ;
  2. description de PR — générée par `crank finalize`, donc la relecture arrive avec
     son contexte, ce qui est le premier levier de vitesse du projet ;
  3. archive — conservée après fusion, consultable par les interventions suivantes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Task
from .naming import run_filename

RUNS_DIR = ".crank/runs"
ARCHIVE_DIR = ".crank/archived"

_TEMPLATE = """# Tâche #{number} — {title}

- **rôle** : `{role}`
- **critère de complétion** : `{done}`
- **périmètre** : {touche}
- **budget** : {budget}

## Plan

<!-- Cases à cocher, établies avant de commencer, corrigées en chemin si besoin. -->

- [ ] …

## Journal

<!-- Tenu au fil de l'eau, jamais reconstitué à la fin. -->

## Bilan

<!-- Ce qui a été fait, ce qui reste ouvert. Devient le corps de la PR. -->

## Points d'incertitude

<!-- Ce dont tu n'es pas sûr, et que le relecteur doit regarder en priorité. -->
"""

_SECTION = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TaskFile:
    path: Path
    text: str

    def section(self, name: str) -> str:
        matches = list(_SECTION.finditer(self.text))
        for i, m in enumerate(matches):
            if m.group(1).strip().lower() == name.strip().lower():
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(self.text)
                body = re.sub(r"<!--.*?-->", "", self.text[start:end], flags=re.DOTALL)
                return body.strip()
        return ""

    def pr_body(self, task: Task) -> str:
        done = task.spec.done if task.spec else ""
        parts = [
            f"Closes #{task.number}",
            "",
            "## Bilan",
            self.section("Bilan") or "_non renseigné_",
            "",
            "## Points d'incertitude",
            self.section("Points d'incertitude") or "_aucun signalé_",
        ]
        plan = self.section("Plan")
        if plan:
            parts += ["", "## Plan", plan]
        parts += [
            "",
            "---",
            f"Critère de complétion vérifié : `{done}`",
            f"Suivi : `{RUNS_DIR}/{self.path.name}`",
            "",
            "_Généré par `crank finalize`._",
        ]
        return "\n".join(parts)


class TaskFileError(RuntimeError):
    pass


def path_for(worktree: Path, task: Task) -> Path:
    """Le suivi de la tâche, retrouvé par son **numéro**.

    Le nom contient le slug du titre, mais une issue se renomme — en particulier quand
    on la découpe parce que son diff dépasse le plafond. Le numéro, lui, ne change pas.
    """
    folder = worktree / RUNS_DIR
    expected = folder / run_filename(task.number, task.title)
    if expected.is_file():
        return expected
    found = sorted(folder.glob(f"{task.number:04d}-*.md")) if folder.is_dir() else []
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise TaskFileError(f"plusieurs suivis pour #{task.number} : {names} — n'en garder qu'un")
    return found[0] if found else expected


def render(task: Task) -> str:
    spec = task.spec
    return _TEMPLATE.format(
        number=task.number,
        title=task.title,
        role=spec.role if spec else "?",
        done=spec.done if spec else "?",
        touche=", ".join(f"`{p}`" for p in spec.touche) if spec and spec.touche else "_non déclaré_",
        budget=(spec.budget if spec and spec.budget else "_non déclaré_"),
    )


def write(worktree: Path, task: Task) -> Path:
    """Crée le suivi s'il n'existe pas. Ne l'écrase jamais : on peut reprendre."""
    path = path_for(worktree, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(render(task), encoding="utf-8")
    return path


def read(worktree: Path, task: Task) -> TaskFile:
    path = path_for(worktree, task)
    if not path.is_file():
        raise TaskFileError(
            f"suivi introuvable : aucun {RUNS_DIR}/{task.number:04d}-*.md"
            " — `crank setup` l'aurait créé"
        )
    return TaskFile(path=path, text=path.read_text(encoding="utf-8"))


def previous_runs(root: Path) -> tuple[Path, ...]:
    """Suivis déjà enregistrés — à consulter avant d'intervenir sur le même terrain."""
    found: list[Path] = []
    for folder in (root / RUNS_DIR, root / ARCHIVE_DIR):
        if folder.is_dir():
            found.extend(sorted(folder.glob("*.md")))
    return tuple(found)
