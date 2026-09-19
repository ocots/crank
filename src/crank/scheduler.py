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
    for ref in task.spec.bloque_sur:
        decision = state.decision(ref)
        if decision is None or not decision.settled:
            pending.append(ref)
    return tuple(pending)


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
    if pending:
        return "bloquée sur décision " + ", ".join(pending)
    for other in state.in_progress_tasks:
        other_paths = other.spec.touche if other.spec else ()
        if paths_overlap(task.spec.touche, other_paths):
            return f"périmètre en conflit avec {other.ref} (en cours)"
    return ""


def _sort_key(task: Task, config: Config) -> tuple[int, int, int]:
    tier = config.tier_of(task.spec.role) if task.spec else None
    return (
        _TIER_ORDER.get(tier, 99) if tier else 99,
        0 if task.high_priority else 1,
        task.number,
    )


def _stop_notes(state: RepoState, config: Config, skipped: list[tuple[int, str]]) -> tuple[str, ...]:
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

    blocked_count = sum(1 for _, why in skipped if why.startswith("bloquée sur décision"))
    eligible_total = sum(1 for t in state.tasks if not t.human_only and not t.claimed)
    if eligible_total and blocked_count / eligible_total > 0.5:
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
            notes=_stop_notes(state, config, []),
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
        notes=_stop_notes(state, config, skipped),
        skipped=tuple(skipped),
    )
