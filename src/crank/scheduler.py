"""Le sélecteur. Fonction pure : (RepoState, Config) -> Plan.

C'est la décision de conception centrale du projet : la *sélection* de la tâche est
déterministe et testable, seule l'*exécution* est confiée à un agent. Le même état
produit toujours le même plan.

Aucune E/S ici. Jamais.
"""

from __future__ import annotations

from fnmatch import fnmatch

from .config import Config
from .models import (
    Action,
    Decision,
    Plan,
    PullRequest,
    RepoState,
    Task,
    Tier,
)

_TIER_ORDER = {Tier.P0: 0, Tier.P1: 1, Tier.P2: 2, Tier.P3: 3, Tier.P4: 4, Tier.P5: 5}


def _normalise(pattern: str) -> str:
    return pattern.rstrip("/")


def paths_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Deux périmètres se recouvrent-ils ? Conservateur : sans périmètre, on suppose oui."""
    if not a or not b:
        return True
    for pa in a:
        for pb in b:
            na, nb = _normalise(pa), _normalise(pb)
            if na == nb or fnmatch(na, nb) or fnmatch(nb, na):
                return True
            base_a = na.split("*", 1)[0].rstrip("/")
            base_b = nb.split("*", 1)[0].rstrip("/")
            if base_a and base_b and (base_a.startswith(base_b) or base_b.startswith(base_a)):
                return True
    return False


def unsettled_decisions(task: Task, state: RepoState) -> tuple[str, ...]:
    if task.spec is None:
        return ()
    pending: list[str] = []
    for ref in task.spec.decision_refs:
        decision = state.decision(ref)
        if decision is None or not decision.settled:
            pending.append(ref)
    return tuple(pending)


def unfinished_tasks(task: Task, state: RepoState) -> tuple[int, ...]:
    """Les tâches dont celle-ci dépend et qui ne sont pas fermées.

    Fermée, quelle que soit la raison (fusion de sa PR, abandon), débloque : comme pour
    les décisions, ce qui bloque, c'est ce qui n'est pas terminé. Une référence vers une
    issue inconnue bloque — mieux vaut une tâche qui attend qu'une tâche qui part sur un
    `main` qui ne contient pas encore ce dont elle a besoin.
    """
    if task.spec is None:
        return ()
    return tuple(n for n in task.spec.task_refs if n not in state.closed_issues)


def waiting_on(state: RepoState) -> dict[int, tuple[int, ...]]:
    """Pour chaque tâche non terminée, les tâches ouvertes qui l'attendent.

    C'est ce qui permet à `crank status` de remonter les PRs qui débloquent d'autres
    tâches (§8.3) : les fusionner en premier libère le plus de travail.
    """
    waiting: dict[int, list[int]] = {}
    for task in state.tasks:
        for number in unfinished_tasks(task, state):
            waiting.setdefault(number, []).append(task.number)
    return {n: tuple(sorted(ts)) for n, ts in sorted(waiting.items())}


def task_blocker(task: Task, state: RepoState, config: Config) -> str:
    """Pourquoi cette tâche n'est-elle pas éligible ? Chaîne vide si elle l'est."""
    if task.claimed:
        return "déjà réclamée"
    if task.human_only:
        return "human-only — à ta charge, jamais confiée à un agent"
    if task.blocked:
        return "étiquetée blocked"
    if task.failed:
        return "échec précédent — retirer le label agent:failed pour la remettre en jeu"
    if task.spec is None:
        return f"spec invalide : {task.spec_error or 'bloc ```crank absent'}"
    if config.role(task.spec.role) is None:
        return f"rôle « {task.spec.role} » inconnu"
    pending = unsettled_decisions(task, state)
    waiting = unfinished_tasks(task, state)
    if pending or waiting:
        parts = []
        if pending:
            parts.append("décision " + ", ".join(pending))
        if waiting:
            parts.append("tâche " + ", ".join(_task_label(n, state) for n in waiting))
        return "bloquée sur " + " ; ".join(parts)
    for other in state.in_progress_tasks:
        other_paths = other.spec.touche if other.spec else ()
        if paths_overlap(task.spec.touche, other_paths):
            return f"périmètre en conflit avec {other.ref} (en cours)"
    return ""


def _task_label(number: int, state: RepoState) -> str:
    if state.task(number) is None:
        return f"#{number} (introuvable)"
    return f"#{number}"


def _sort_key(task: Task, config: Config) -> tuple[int, int, int]:
    tier = config.tier_of(task.spec.role) if task.spec else None
    return (
        _TIER_ORDER.get(tier, 99) if tier else 99,
        0 if task.high_priority else 1,
        task.number,
    )


def _stop_notes(state: RepoState) -> tuple[str, ...]:
    notes: list[str] = []

    pending = [d for d in state.decisions if not d.settled]
    if pending:
        notes.append(
            f"{len(pending)} décision(s) en attente — à traiter EN PREMIER en session : "
            + ", ".join(f"{d.ref} ({d.title})" for d in pending)
        )

    human = [t for t in state.tasks if t.human_only and not t.claimed]
    if human:
        notes.append(
            f"{len(human)} tâche(s) human-only à ta charge : "
            + ", ".join(t.ref for t in human)
        )

    malformed = [t for t in state.tasks if t.spec is None and not t.human_only]
    if malformed:
        notes.append(
            f"{len(malformed)} tâche(s) sans critère « done » vérifiable — "
            "à reformuler avant de pouvoir être prises : "
            + ", ".join(t.ref for t in malformed)
        )

    # La famine ne concerne que les décisions : ce sont elles qui attendent l'humain.
    # Une tâche qui attend une autre tâche attend du travail, pas un arbitrage.
    available = [t for t in state.tasks if not t.human_only and not t.claimed]
    blocked_count = sum(1 for t in available if unsettled_decisions(t, state))
    if available and blocked_count / len(available) > 0.5:
        notes.append(
            "⚠ plus de la moitié des tâches disponibles sont bloquées sur tes décisions "
            "— risque de famine (§7)"
        )
    return tuple(notes)


def plan(state: RepoState, config: Config) -> Plan:
    """Descend l'échelle P0 → P5 et rend la première action possible."""

    # P0 — CI rouge sur main. Passe outre WIP_MAX : rien d'autre ne compte.
    if not state.ci_main_ok:
        return Plan(
            action=Action.FIX_CI,
            tier=Tier.P0,
            reason=f"CI rouge sur {config.main_branch} — réparer avant toute autre chose",
            role="feature",
        )

    # P1 — PR ouverte demandant une action de l'auteur. Ne crée pas de PR : hors WIP.
    awaiting = sorted(
        (pr for pr in state.prs if pr.needs_author_action),
        key=lambda pr: pr.number,
    )
    if awaiting:
        pr = awaiting[0]
        return Plan(
            action=Action.ADDRESS_REVIEW,
            tier=Tier.P1,
            reason=f"PR #{pr.number} : changements demandés — répondre avant d'ouvrir du neuf",
            pr=pr,
        )

    # Garde-fou de débit : ne limite que l'ouverture de NOUVELLES PRs.
    if state.open_wip >= config.wip_max:
        return Plan(
            action=Action.STOP,
            tier=Tier.P5,
            reason=(
                f"plafond atteint : {state.open_wip} PR(s) ouverte(s) pour WIP_MAX="
                f"{config.wip_max}. À toi de jouer — une session vide la file."
            ),
            notes=_stop_notes(state),
        )

    # P2 → P4 — première tâche éligible, dans l'ordre des tiers.
    skipped: list[tuple[int, str]] = []
    candidates: list[Task] = []
    for task in state.tasks:
        why = task_blocker(task, state, config)
        if why:
            skipped.append((task.number, why))
        else:
            candidates.append(task)

    if candidates:
        chosen = min(candidates, key=lambda t: _sort_key(t, config))
        tier = config.tier_of(chosen.spec.role) or Tier.P2
        return Plan(
            action=Action.WORK_TASK,
            tier=tier,
            reason=f"tâche {chosen.ref} — {chosen.title}",
            task=chosen,
            role=chosen.spec.role,
            skipped=tuple(skipped),
        )

    # P5 — rien à faire. Ce n'est pas un échec : c'est un rapport.
    return Plan(
        action=Action.STOP,
        tier=Tier.P5,
        reason="aucune tâche prête",
        notes=_stop_notes(state),
        skipped=tuple(skipped),
    )
