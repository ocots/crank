"""CLI `crank`.

    crank next       → que faut-il faire maintenant ? (déterministe, sans effet de bord)
    crank setup N    → worktree + branche + réclamation + .task.md
    crank finalize   → vérifications, puis PR. Refuse si une vérification échoue.
    crank status     → l'ordre de ta session de relecture
    crank init       → installe .crank.toml, decisions/ et les labels
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import briefs, checks, git_ops, naming, state, taskfile
from .config import CONFIG_NAME, Config, load_config
from .models import CLAIM_LABEL, FAILED_LABEL, REVIEW_LABEL, Action, Plan
from .scheduler import plan as compute_plan

LABELS = {
    CLAIM_LABEL: "0e8a16",
    REVIEW_LABEL: "1d76db",
    "blocked": "b60205",
    FAILED_LABEL: "d73a4a",
    "human-only": "5319e7",
    "decision:blocking": "d93f0b",
    "priority:high": "e99695",
    "role:feature": "c2e0c6",
    "role:test": "c5def5",
    "role:doc": "fef2c0",
}


def _root() -> Path:
    try:
        return git_ops.repo_root(Path.cwd())
    except git_ops.GitError:
        raise click.ClickException("pas dans un dépôt git")


def _load() -> tuple[Path, Config]:
    root = _root()
    return root, load_config(root)


def _echo_plan(p: Plan) -> None:
    head = {
        Action.FIX_CI: "🔴 P0 — CI cassée",
        Action.ADDRESS_REVIEW: "💬 P1 — review à traiter",
        Action.WORK_TASK: f"▶  {p.tier.value} — au travail",
        Action.STOP: "⏸  rien à faire",
    }[p.action]
    click.echo(click.style(head, bold=True))
    click.echo(f"   {p.reason}")
    if p.task and p.task.spec:
        click.echo(f"   rôle       : {p.role}")
        click.echo(f"   done       : {p.task.spec.done}")
        if p.task.spec.touche:
            click.echo(f"   périmètre  : {', '.join(p.task.spec.touche)}")
        click.echo()
        click.echo(f"   → crank setup {p.task.number}")
    for note in p.notes:
        click.echo()
        click.echo(click.style(f"   • {note}", fg="yellow"))
    if p.skipped:
        click.echo()
        click.echo("   écartées :")
        for number, why in p.skipped[:10]:
            click.echo(f"     #{number} — {why}")


@click.group()
@click.version_option("0.1.0", prog_name="crank")
def app() -> None:
    """Orchestration d'agents autonomes — la sélection est déterministe."""


@app.command("next")
@click.option("--json", "as_json", is_flag=True, help="sortie machine, pour un agent")
def next_cmd(as_json: bool) -> None:
    """Que faut-il faire maintenant ? Aucun effet de bord."""
    root, config = _load()
    try:
        current = state.collect(root, config)
    except state.StateError as exc:
        raise click.ClickException(str(exc))
    p = compute_plan(current, config)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "action": p.action.value,
                    "tier": p.tier.value,
                    "reason": p.reason,
                    "role": p.role,
                    "task": p.task.number if p.task else None,
                    "done": p.task.spec.done if p.task and p.task.spec else None,
                    "paths": list(p.task.spec.touche) if p.task and p.task.spec else [],
                    "pr": p.pr.number if p.pr else None,
                    "notes": list(p.notes),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _echo_plan(p)
    sys.exit(0 if p.actionable else 1)


@app.command()
@click.argument("number", type=int)
def setup(number: int) -> None:
    """Prépare le terrain pour la tâche NUMBER : worktree, branche, réclamation."""
    root, config = _load()
    tasks = state.collect_tasks(root)
    task = next((t for t in tasks if t.number == number), None)
    if task is None:
        raise click.ClickException(f"issue #{number} introuvable ou fermée")
    if task.spec is None:
        raise click.ClickException(
            f"issue #{number} sans critère « done » vérifiable : {task.spec_error}"
        )
    if task.claimed:
        raise click.ClickException(f"issue #{number} déjà réclamée")
    if config.role(task.spec.role) is None:
        raise click.ClickException(f"rôle « {task.spec.role} » inconnu dans {CONFIG_NAME}")

    branch = naming.branch_name(number, task.title)
    path = git_ops.worktree_path(root, config.worktree_root, number, task.title)
    if path.exists():
        raise click.ClickException(f"{path} existe déjà")

    git_ops.create_worktree(root, path, branch, config.main_branch)
    try:
        git_ops.claim_issue(root, number, CLAIM_LABEL)
    except git_ops.GitError as exc:
        git_ops.remove_worktree(root, path)
        raise click.ClickException(f"réclamation impossible, worktree retiré : {exc}")
    taskfile.write(path, task)

    click.echo(click.style(f"✓ worktree prêt pour #{number}", fg="green"))
    click.echo(f"  chemin : {path}")
    click.echo(f"  branche: {branch}")
    click.echo(f"  rôle   : {task.spec.role}")
    click.echo(f"  done   : {task.spec.done}")
    run_path = taskfile.path_for(path, task)
    click.echo(f"  suivi  : {run_path.relative_to(path)}")

    earlier = taskfile.previous_runs(root)
    if earlier:
        click.echo()
        click.echo(f"  {len(earlier)} suivi(s) ant\u00e9rieur(s) dans .crank/ \u2014 lis ceux qui touchent au m\u00eame terrain")

    click.echo()
    click.echo(f"  cd {path}")

    brief = briefs.load(root, task.spec.role)
    if brief:
        click.echo()
        click.echo(click.style("─" * 70, dim=True))
        click.echo(brief.rstrip())


@app.command()
@click.argument("role")
def brief(role: str) -> None:
    """Affiche le brief du rôle ROLE."""
    root = _root()
    text = briefs.load(root, role)
    if not text:
        raise click.ClickException(f"aucun brief pour le rôle « {role} »")
    click.echo(text.rstrip())


@app.command()
@click.option("--dry-run", is_flag=True, help="vérifie sans ouvrir la PR")
@click.option("--draft", is_flag=True, help="ouvre la PR en brouillon (agent bloqué)")
def finalize(dry_run: bool, draft: bool) -> None:
    """Vérifie le travail du worktree courant, puis ouvre la PR."""
    cwd = Path.cwd()
    root = _root()
    config = load_config(root)

    branch = git_ops.current_branch(cwd)
    number = naming.number_from_branch(branch)
    if number is None:
        raise click.ClickException(f"branche « {branch} » : format task/<n>-<slug> attendu")

    task = next((t for t in state.collect_tasks(root) if t.number == number), None)
    if task is None or task.spec is None:
        raise click.ClickException(f"issue #{number} introuvable ou sans spec")
    tf = taskfile.read(cwd, task)
    role = config.role(task.spec.role)
    if role is None:
        raise click.ClickException(f"rôle « {task.spec.role} » inconnu")

    base = f"origin/{config.main_branch}"
    git_ops.run(["git", "fetch", "origin", config.main_branch], cwd, check=False)

    results = [
        checks.check_scope(cwd, base, role),
        checks.check_size(cwd, base, config.max_diff_lines),
        checks.check_docstrings_only(cwd, base, role),
        checks.run_command("critère « done »", task.spec.done, cwd),
    ]
    for name, command in config.checks.items():
        results.append(checks.run_command(name, command, cwd))

    click.echo(click.style("Vérifications", bold=True))
    for r in results:
        click.echo("  " + r.line())

    failed = [r for r in results if not r.ok]
    if failed:
        click.echo()
        raise click.ClickException(
            f"{len(failed)} vérification(s) en échec — aucune PR ouverte. "
            "Corrige, ou déclare-toi bloqué avec --draft."
        )

    if dry_run:
        click.echo()
        click.echo(click.style("✓ tout passe (dry-run, PR non ouverte)", fg="green"))
        return

    if git_ops.is_dirty(cwd):
        raise click.ClickException("modifications non committées — commit d'abord")
    git_ops.run(["git", "push", "-u", "origin", branch], cwd)

    url = git_ops.open_pr(
        cwd,
        title=f"{task.title} (#{number})",
        body=tf.pr_body(task),
        base=config.main_branch,
        draft=draft,
    )
    git_ops.release_issue(root, number, CLAIM_LABEL)
    if not draft:
        git_ops.gh(["pr", "edit", url, "--add-label", REVIEW_LABEL], cwd, check=False)

    click.echo()
    click.echo(click.style(f"✓ PR ouverte : {url}", fg="green"))


@app.command()
@click.argument("number", type=int)
@click.argument("reason")
def fail(number: int, reason: str) -> None:
    """Déclare la tâche NUMBER en échec, avec sa RAISON.

    Libère la réclamation **et** pose `agent:failed`. Un échec n'est jamais retenté
    tout seul : retirer le label remet la tâche en jeu. Ne jamais laisser une issue
    réclamée sans `finalize` ni `fail`.
    """
    root = _root()
    git_ops.mark_failed(root, number, CLAIM_LABEL, FAILED_LABEL, reason)
    click.echo(click.style(f"✓ #{number} marquée en échec, réclamation libérée", fg="yellow"))
    click.echo(f"  raison : {reason}")
    click.echo(f"  retirer le label « {FAILED_LABEL} » la remettra en jeu")


@app.command()
def status() -> None:
    """L'ordre de ta session de relecture — décisions d'abord, toujours."""
    root, config = _load()
    try:
        current = state.collect(root, config)
    except state.StateError as exc:
        raise click.ClickException(str(exc))

    pending = [d for d in current.decisions if not d.settled]
    click.echo(click.style("Session de relecture — dans cet ordre", bold=True))
    click.echo()
    click.echo(click.style("1. Décisions bloquantes (~10 min, débloquent 3 jours)", bold=True))
    if pending:
        for d in pending:
            click.echo(f"   • {d.ref} — {d.title}  [{d.path}]")
    else:
        click.echo("   (aucune)")

    click.echo()
    click.echo(click.style("2. PRs à relire", bold=True))
    if current.prs:
        for pr in sorted(current.prs, key=lambda p: (p.is_draft, p.number)):
            mark = " (brouillon)" if pr.is_draft else ""
            flag = " ⟵ changements demandés" if pr.needs_author_action else ""
            click.echo(f"   • #{pr.number} {pr.title}{mark}{flag}")
    else:
        click.echo("   (aucune)")

    human = [t for t in current.tasks if t.human_only]
    if human:
        click.echo()
        click.echo(click.style("3. À ta charge — aucun agent ne peut le faire", bold=True))
        for t in human:
            click.echo(f"   • {t.ref} {t.title}")

    click.echo()
    click.echo(
        f"WIP : {current.open_wip}/{config.wip_max}"
        f" · tâches ouvertes : {len(current.tasks)}"
        f" · CI {config.main_branch} : {'verte' if current.ci_main_ok else 'ROUGE'}"
    )


@app.command()
@click.option("--labels/--no-labels", default=True, help="créer les labels GitHub")
def init(labels: bool) -> None:
    """Installe la configuration dans le dépôt courant."""
    root = _root()
    config_path = root / CONFIG_NAME
    if config_path.exists():
        click.echo(f"= {CONFIG_NAME} existe déjà")
    else:
        config_path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
        click.echo(f"+ {CONFIG_NAME}")

    decisions = root / "decisions"
    decisions.mkdir(exist_ok=True)
    template = decisions / "0000-modele.md"
    if not template.exists():
        template.write_text(_DECISION_TEMPLATE, encoding="utf-8")
        click.echo("+ decisions/0000-modele.md")

    config = load_config(root)
    for path in briefs.install(root, sorted(config.roles)):
        click.echo(f"+ {path}")
    if skill_path := briefs.install_skill(root):
        click.echo(f"+ {skill_path}")

    if labels:
        try:
            git_ops.ensure_labels(root, LABELS)
            click.echo(f"+ {len(LABELS)} labels GitHub")
        except git_ops.GitError as exc:
            click.echo(click.style(f"! labels non créés : {exc}", fg="yellow"))

    click.echo()
    click.echo("Prochaine étape : créer une issue avec un bloc ```crank, puis `crank next`.")


_DEFAULT_CONFIG = """# Configuration crank — voir `crank --help`

[crank]
wip_max = 4              # dimensionné pour qu'UNE session vide la file
max_diff_lines = 300     # une PR relisible, ou pas de PR
main_branch = "main"

[checks]
# Commandes lancées par `crank finalize`, en plus du critère « done » de la tâche.
# tests = "pytest -q"
# lint  = "ruff check ."

[roles.feature]
tier = "P2"
paths = ["src/**", "tests/**"]

[roles.test]
tier = "P3"
paths = ["tests/**"]      # ne peut PAS toucher au code de production

[roles.doc]
tier = "P4"
paths = ["docs/**", "README.md", "examples/**", "src/**"]
docstrings_only = true    # dans src/**, seules les docstrings peuvent changer
"""

_DECISION_TEMPLATE = """# Modèle de décision

statut: proposée

## Contexte

Ce qui rend ce choix nécessaire.

## Options

1. …
2. …

## Décision

À remplir. **Fusionner la PR vaut décision** : passer `statut` à `actée`.

## Conséquences

Ce que ça engage, et ce que ça ferme.
"""
