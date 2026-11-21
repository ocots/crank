"""Le scheduler est une fonction pure : on lui donne un état simulé, on vérifie le plan.

C'est tout l'intérêt d'avoir sorti la décision du LLM — ces tests seraient impossibles
autrement.
"""

from __future__ import annotations

from conftest import make_pr, make_state, make_task

from crank.config import Config
from crank.models import (
    CLAIM_LABEL,
    DECISION_ACTEE,
    DECISION_PROPOSEE,
    DECISION_REJETEE,
    Action,
    Decision,
    Tier,
)
from crank.scheduler import paths_overlap, plan, task_blocker, waiting_on


class TestDeterminisme:
    def test_meme_etat_meme_plan(self, config):
        state = make_state(tasks=(make_task(3), make_task(1), make_task(2)))
        assert plan(state, config) == plan(state, config)


class TestEchelleDePriorite:
    def test_p0_ci_rouge_passe_avant_tout(self, config):
        state = make_state(tasks=(make_task(1),), ci_ok=False)
        p = plan(state, config)
        assert p.action is Action.FIX_CI
        assert p.tier is Tier.P0

    def test_p0_ignore_le_plafond_wip(self, config):
        prs = tuple(make_pr(n) for n in range(1, 9))
        p = plan(make_state(prs=prs, ci_ok=False), config)
        assert p.action is Action.FIX_CI

    def test_p1_review_avant_nouvelle_tache(self, config):
        state = make_state(
            tasks=(make_task(1),),
            prs=(make_pr(7, review="CHANGES_REQUESTED"),),
        )
        p = plan(state, config)
        assert p.action is Action.ADDRESS_REVIEW
        assert p.pr.number == 7

    def test_p1_ignore_le_plafond_wip(self):
        config = Config(wip_max=1)
        state = make_state(prs=(make_pr(4, review="CHANGES_REQUESTED"), make_pr(5)))
        assert plan(state, config).action is Action.ADDRESS_REVIEW

    def test_p1_prend_la_plus_ancienne(self, config):
        state = make_state(
            prs=(
                make_pr(9, review="CHANGES_REQUESTED"),
                make_pr(4, review="CHANGES_REQUESTED"),
            )
        )
        assert plan(state, config).pr.number == 4

    def test_feature_avant_test_avant_doc(self, config):
        state = make_state(
            tasks=(
                make_task(1, role="doc", touche=("docs/**",)),
                make_task(2, role="test", touche=("tests/b/**",)),
                make_task(3, role="feature", touche=("src/c/**",)),
            )
        )
        p = plan(state, config)
        assert p.task.number == 3 and p.tier is Tier.P2

    def test_priorite_haute_puis_numero(self, config):
        state = make_state(
            tasks=(
                make_task(1, touche=("src/a/**",)),
                make_task(5, touche=("src/b/**",), labels=("priority:high",)),
            )
        )
        assert plan(state, config).task.number == 5


class TestPlafondDeDebit:
    def test_stop_quand_wip_atteint(self):
        config = Config(wip_max=2)
        state = make_state(tasks=(make_task(1),), prs=(make_pr(1), make_pr(2)))
        p = plan(state, config)
        assert p.action is Action.STOP
        assert "plafond" in p.reason

    def test_les_brouillons_ne_comptent_pas(self):
        config = Config(wip_max=2)
        state = make_state(
            tasks=(make_task(1),), prs=(make_pr(1), make_pr(2, draft=True))
        )
        assert plan(state, config).action is Action.WORK_TASK


class TestEligibilite:
    def test_tache_reclamee_par_label(self, config):
        state = make_state(tasks=(make_task(1, labels=(CLAIM_LABEL,)),))
        assert plan(state, config).action is Action.STOP

    def test_tache_reclamee_par_assignee(self, config):
        state = make_state(tasks=(make_task(1, assignees=("ocots",)),))
        assert plan(state, config).action is Action.STOP

    def test_human_only_jamais_confiee_a_un_agent(self, config):
        state = make_state(tasks=(make_task(1, labels=("human-only",)),))
        p = plan(state, config)
        assert p.action is Action.STOP
        assert any("human-only" in n for n in p.notes)

    def test_sans_critere_done_pas_de_tache(self, config):
        state = make_state(tasks=(make_task(1, spec=False, spec_error="bloc absent"),))
        p = plan(state, config)
        assert p.action is Action.STOP
        assert any("done" in n for n in p.notes)

    def test_role_inconnu_ecarte(self, config):
        state = make_state(tasks=(make_task(1, role="poete"),))
        p = plan(state, config)
        assert p.action is Action.STOP
        assert any("poete" in why for _, why in p.skipped)

    def test_label_blocked(self, config):
        state = make_state(tasks=(make_task(1, labels=("blocked",)),))
        assert plan(state, config).action is Action.STOP


class TestDecisionsBloquantes:
    def test_bloquee_tant_que_la_decision_est_proposee(self, config):
        state = make_state(
            tasks=(make_task(1, bloque_sur=("0007",)),),
            decisions=(Decision("0007", "format", DECISION_PROPOSEE),),
        )
        assert plan(state, config).action is Action.STOP

    def test_debloquee_quand_actee(self, config):
        state = make_state(
            tasks=(make_task(1, bloque_sur=("0007",)),),
            decisions=(Decision("0007", "format", DECISION_ACTEE),),
        )
        assert plan(state, config).action is Action.WORK_TASK

    def test_une_decision_rejetee_debloque_aussi(self, config):
        state = make_state(
            tasks=(make_task(1, bloque_sur=("0007",)),),
            decisions=(Decision("0007", "format", DECISION_REJETEE),),
        )
        assert plan(state, config).action is Action.WORK_TASK

    def test_decision_absente_bloque(self, config):
        state = make_state(tasks=(make_task(1, bloque_sur=("9999",)),))
        assert plan(state, config).action is Action.STOP

    def test_repli_sur_une_tache_non_bloquee(self, config):
        state = make_state(
            tasks=(
                make_task(1, bloque_sur=("0007",), touche=("src/a/**",)),
                make_task(2, role="doc", touche=("docs/**",)),
            ),
            decisions=(Decision("0007", "x", DECISION_PROPOSEE),),
        )
        p = plan(state, config)
        assert p.task.number == 2 and p.tier is Tier.P4

    def test_alerte_famine(self, config):
        state = make_state(
            tasks=(
                make_task(1, bloque_sur=("0007",)),
                make_task(2, bloque_sur=("0007",), touche=("src/b/**",)),
            ),
            decisions=(Decision("0007", "x", DECISION_PROPOSEE),),
        )
        assert any("famine" in n for n in plan(state, config).notes)


class TestDependancesEntreTaches:
    """`bloque_sur: ["#1"]` : une tâche qui a besoin du code d'une autre attend sa fusion.

    Le recouvrement de périmètres ne suffit pas : il ne protège que tant que l'autre
    tâche est réclamée. Dès sa PR ouverte, elle ne l'est plus, et la suivante partirait
    d'un `main` qui ne contient pas encore ce dont elle a besoin.
    """

    def test_bloquee_tant_que_la_tache_est_ouverte(self, config):
        state = make_state(
            tasks=(
                make_task(1, labels=(CLAIM_LABEL,), touche=("src/a/**",)),
                make_task(2, bloque_sur=("#1",), touche=("src/b/**",)),
            )
        )
        p = plan(state, config)
        assert p.action is Action.STOP
        assert (2, "bloquée sur tâche #1") in p.skipped

    def test_bloquee_meme_quand_sa_pr_est_ouverte(self, config):
        """Le cas qui motive la fonctionnalité : la tâche 1 n'est plus réclamée."""
        state = make_state(
            tasks=(
                make_task(1, touche=("src/a/**",), labels=("blocked",)),
                make_task(2, bloque_sur=("#1",), touche=("src/b/**",)),
            ),
            prs=(make_pr(1),),
        )
        assert plan(state, config).action is Action.STOP

    def test_debloquee_quand_la_tache_est_fermee(self, config):
        state = make_state(
            tasks=(make_task(2, bloque_sur=("#1",)),),
            closed=(1,),
        )
        p = plan(state, config)
        assert p.action is Action.WORK_TASK and p.task.number == 2

    def test_reference_inconnue_bloque(self, config):
        state = make_state(tasks=(make_task(2, bloque_sur=("#99",)),))
        p = plan(state, config)
        assert p.action is Action.STOP
        assert (2, "bloquée sur tâche #99 (introuvable)") in p.skipped

    def test_decision_et_tache_melees(self, config):
        decision = Decision("0007", "format", DECISION_PROPOSEE)
        task = make_task(2, bloque_sur=("0007", "#1"), touche=("src/b/**",))
        state = make_state(tasks=(make_task(1), task), decisions=(decision,))
        assert task_blocker(task, state, config) == "bloquée sur décision 0007 ; tâche #1"

    def test_decision_tranchee_mais_tache_ouverte(self, config):
        state = make_state(
            tasks=(
                make_task(1, labels=(CLAIM_LABEL,), touche=("src/a/**",)),
                make_task(2, bloque_sur=("0007", "#1"), touche=("src/b/**",)),
            ),
            decisions=(Decision("0007", "format", DECISION_ACTEE),),
        )
        assert plan(state, config).action is Action.STOP

    def test_les_deux_levees(self, config):
        state = make_state(
            tasks=(make_task(2, bloque_sur=("0007", "#1")),),
            decisions=(Decision("0007", "format", DECISION_ACTEE),),
            closed=(1,),
        )
        assert plan(state, config).task.number == 2

    def test_la_chaine_avance_maillon_par_maillon(self, config):
        """1 → 2 → 3 : seule la première est éligible."""
        state = make_state(
            tasks=(
                make_task(1, touche=("src/a/**",)),
                make_task(2, bloque_sur=("#1",), touche=("src/b/**",)),
                make_task(3, bloque_sur=("#2",), touche=("src/c/**",)),
            )
        )
        p = plan(state, config)
        assert p.task.number == 1
        assert {n for n, _ in p.skipped} == {2, 3}

    def test_attendre_une_tache_nest_pas_une_famine(self, config):
        """La famine signale ce qui attend l'humain : les décisions, pas le travail."""
        state = make_state(
            tasks=(
                make_task(1, labels=(CLAIM_LABEL,), touche=("src/a/**",)),
                make_task(2, bloque_sur=("#1",), touche=("src/b/**",)),
                make_task(3, bloque_sur=("#1",), touche=("src/c/**",)),
            )
        )
        assert not any("famine" in n for n in plan(state, config).notes)


class TestAttentes:
    def test_qui_attend_qui(self):
        state = make_state(
            tasks=(
                make_task(1),
                make_task(2, bloque_sur=("#1",)),
                make_task(3, bloque_sur=("#1", "#2")),
            )
        )
        assert waiting_on(state) == {1: (2, 3), 2: (3,)}

    def test_une_tache_fermee_nest_plus_attendue(self):
        state = make_state(tasks=(make_task(2, bloque_sur=("#1",)),), closed=(1,))
        assert waiting_on(state) == {}

    def test_les_decisions_ne_comptent_pas(self):
        state = make_state(tasks=(make_task(2, bloque_sur=("0007",)),))
        assert waiting_on(state) == {}


class TestConflitsDePerimetre:
    def test_perimetre_en_conflit_avec_une_tache_en_cours(self, config):
        state = make_state(
            tasks=(
                make_task(1, labels=(CLAIM_LABEL,), touche=("src/vision/**",)),
                make_task(2, touche=("src/vision/locate.py",)),
            )
        )
        p = plan(state, config)
        assert p.action is Action.STOP
        assert any("conflit" in why for _, why in p.skipped)

    def test_perimetres_disjoints_passent(self, config):
        state = make_state(
            tasks=(
                make_task(1, labels=(CLAIM_LABEL,), touche=("src/vision/**",)),
                make_task(2, touche=("src/grading/**",)),
            )
        )
        assert plan(state, config).task.number == 2

    def test_perimetre_absent_suppose_le_conflit(self, config):
        state = make_state(
            tasks=(
                make_task(1, labels=(CLAIM_LABEL,), touche=()),
                make_task(2, touche=("src/grading/**",)),
            )
        )
        assert plan(state, config).action is Action.STOP


class TestPrFusionneeIssueOuverte:
    """Le `Closes #N` perdu : PR fusionnée, issue restée ouverte."""

    def etat(self):
        return make_state(
            tasks=(make_task(36), make_task(37, bloque_sur=("#36",), touche=("src/b/**",))),
            merged_open=((36, 39),),
        )

    def test_la_dependante_est_debloquee(self, config):
        state = self.etat()
        assert task_blocker(state.task(37), state, config) == ""

    def test_la_tache_n_est_pas_proposee(self, config):
        state = self.etat()
        assert task_blocker(state.task(36), state, config) == "PR #39 fusionnée, issue restée ouverte — la fermer"
        assert plan(state, config).task.number == 37

    def test_une_note_le_signale(self, config):
        notes = plan(self.etat(), config).notes
        assert any("issue #36 restée ouverte alors que sa PR #39 est fusionnée" in n and "gh issue close 36" in n
                   for n in notes)


class TestPathsOverlap:
    def test_identiques(self):
        assert paths_overlap(("src/a/**",), ("src/a/**",))

    def test_imbriques(self):
        assert paths_overlap(("src/**",), ("src/vision/locate.py",))

    def test_disjoints(self):
        assert not paths_overlap(("src/vision/**",), ("docs/**",))

    def test_vide_est_conservateur(self):
        assert paths_overlap((), ("docs/**",))

    def test_fichiers_de_suivi_jamais_en_conflit(self):
        assert not paths_overlap(("src/a.py", ".crank/runs/**"), ("src/b.py", ".crank/runs/**"))
        assert not paths_overlap((".crank/runs/**",), ("src/**",))

    def test_vrai_conflit_a_cote_du_suivi(self):
        assert paths_overlap(("src/a.py", ".crank/runs/**"), ("src/**", ".crank/runs/**"))


class TestRapportDArret:
    def test_rien_a_faire_reste_informatif(self, config):
        p = plan(make_state(), config)
        assert p.action is Action.STOP
        assert p.reason == "aucune tâche prête"

    def test_decisions_en_attente_signalees_en_premier(self, config):
        state = make_state(decisions=(Decision("0007", "format", DECISION_PROPOSEE),))
        assert "EN PREMIER" in plan(state, config).notes[0]


class TestTaskBlocker:
    def test_tache_eligible_na_pas_de_blocage(self, config):
        assert task_blocker(make_task(1), make_state(), config) == ""


class TestEchec:
    """Un échec n'est jamais retenté tout seul — leçon de ocourses/agents."""

    def test_tache_en_echec_ecartee(self, config):
        state = make_state(tasks=(make_task(1, labels=("agent:failed",)),))
        p = plan(state, config)
        assert p.action is Action.STOP
        assert any("agent:failed" in why for _, why in p.skipped)

    def test_retirer_le_label_la_remet_en_jeu(self, config):
        state = make_state(tasks=(make_task(1),))
        assert plan(state, config).action is Action.WORK_TASK

    def test_repli_sur_une_autre_tache(self, config):
        state = make_state(
            tasks=(
                make_task(1, labels=("agent:failed",), touche=("src/a/**",)),
                make_task(2, touche=("src/b/**",)),
            )
        )
        assert plan(state, config).task.number == 2
