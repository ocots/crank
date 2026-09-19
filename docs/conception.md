# Brainstorm — Orchestration d'agents autonomes

_Document de travail. Projet frère de [idee-brainstorm.md](idee-brainstorm.md), qui en sera
le premier client._
_Créé le 2026-09-18._

---

## 1. Ce que tu veux vraiment

Tu dis « je veux lancer un agent et dire _avance_ ». Sous cette phrase il y a trois
bénéfices très différents, et ils ne se valent pas :

| Bénéfice | Valeur réelle |
| --- | --- |
| **Reprise sans contexte** — ne jamais avoir à re-expliquer où on en est | **énorme, et immédiate** |
| **Travail pendant que tu fais autre chose** | réelle, mais bornée par ton débit de relecture |
| **Parallélisme** (plusieurs agents à la fois) | **surestimée** — elle te noie en PRs |

Le vrai gain est le premier. Un projet solo meurt de la **friction de reprise** : deux
semaines sans y toucher, et il faut une heure pour se remettre dedans. Un système qui
répond « voilà où on en est, voilà la prochaine chose à faire, je la fais » supprime cette
friction. C'est ça qu'il faut optimiser en priorité — pas le débit.

**Corollaire de conception** : si un choix améliore la reprise au détriment du débit,
prends-le.

---

## 2. Le principe central : l'orchestrateur est un script, pas un agent

C'est la décision la plus structurante, et elle va plus loin que ton intuition
(« des scripts pour les parties déterministes »).

**La _sélection_ de la tâche doit être déterministe. Seule l'_exécution_ est un agent.**

Si tu laisses un LLM décider « sur quoi dois-je travailler ? », tu obtiens de la dérive,
des redites, et un comportement non reproductible — impossible à déboguer, impossible à
tester. Si c'est un script qui décide, à partir de l'état objectif (git, issues, PRs, CI),
alors :

- le même état produit **toujours** la même décision → reproductible
- **le sélecteur devient testable** : un état simulé en entrée, une tâche attendue en
  sortie. Des tests unitaires sur l'orchestrateur lui-même.
- tu peux lire et corriger la règle qui t'a déplu, au lieu de retoucher un prompt
- tu peux l'exécuter sans agent, juste pour savoir « qu'est-ce qui se passerait ? »

L'agent, lui, reçoit une tâche **déjà choisie**, avec son critère de complétion, et n'a
qu'un seul travail : la faire.

> **Règle :** tout ce qui peut être décidé par une requête `gh` + une comparaison doit
> l'être. L'agent n'est convoqué que là où il faut du jugement sur du code.

---

## 3. Où vit l'état

**Recommandation : GitHub est la source de vérité de la file de travail.**

| Concept | Support |
| --- | --- |
| tâche | **issue**, avec labels |
| état d'une tâche | labels (`ready`, `in-progress`, `blocked`, `needs-decision`) |
| rôle requis | label (`role:test`, `role:doc`, `role:feature`…) |
| travail en cours | **PR** + worktree |
| décision à prendre | **PR** sur `decisions/` (§7) |
| mémoire de tâche | fichier de suivi dans la branche (§6) |

**Pourquoi pas une file de tâches en fichiers dans le dépôt**, alors que c'est ta
philosophie par ailleurs (et la mienne pour le projet examen) ? Parce qu'ici c'est
**concurrent**. Deux worktrees qui modifient `TASKS.md` entrent en conflit sur chaque
opération. Les issues GitHub sont atomiques, concurrentes, interrogeables via `gh`, et te
donnent une interface de lecture gratuite sur ton téléphone.

L'exception : le **fichier de suivi d'une tâche** vit dans sa branche, donc isolé par
construction. Là, le fichier texte est le bon choix.

---

## 4. L'anatomie d'une tâche — le critère de complétion est tout

**La qualité du système entier tient à un seul champ : `done`.**

Une tâche sans critère vérifiable produit du volume, pas du progrès. C'est le mode
d'échec n°1 des agents autonomes : ils font quelque chose de plausible, s'arrêtent quand
ça « semble fini », et tu découvres trois PRs plus tard qu'ils ont dérivé.

```yaml
id: 42
titre: "locate — homographie robuste à la perspective"
role: feature
done: "pytest tests/vision/test_locate.py -q passe, et le test
        test_homography_perspective_30deg existe et passe"
touche: ["exam_core/vision/**", "tests/vision/**"]
bloque_sur: []
budget: "1 session"
```

**Règle d'admission** : une tâche sans `done` exécutable en une commande n'est **pas
`ready`**. Elle retourne à l'orienteur (§5) pour raffinement. C'est un filtre dur, et
c'est lui qui empêche le système de produire du bruit.

Conséquence : **le rôle le plus important n'est pas celui qui code, c'est celui qui écrit
les critères de complétion.**

---

## 5. Les rôles

Un rôle = un prompt + une **liste de chemins autorisés** + un type de critère.

| Rôle | Fait quoi | Peut modifier | Critère typique |
| --- | --- | --- | --- |
| `orienteur` | transforme un objectif en tâches avec critères vérifiables ; propose des décisions (§7) | `decisions/**` uniquement | issues créées, chacune avec un `done` exécutable |
| `feature` | implémente une tâche | `src/**`, `tests/**` | les tests nommés passent |
| `test` | renforce la suite d'un module | **`tests/**` seulement** | score de mutation ≥ seuil (§10) |
| `doc` | docstrings, exemples, README | `docs/**`, docstrings | doc compile, exemples exécutés |
| `reviewer` | relit une PR et commente | **rien — lecture seule** | commentaire posté |
| `refactor` | nettoyage borné | périmètre déclaré | tests **inchangés** et verts |

**La liste de chemins n'est pas une consigne, c'est une vérification.** Le script de
finalisation (§6) rejette une PR dont le diff sort du périmètre du rôle. Sans ça, les
rôles ne sont que du vocabulaire.

Le cas le plus important : **`test` ne peut pas toucher au code de production.** Sinon
l'agent « fait passer le test » en modifiant le code testé, ce qui est exactement
l'inverse du but.

---

## 6. Le cycle d'une tâche — les deux scripts

```text
  avance
    │
    ├─▶ [1] scheduler.py        ← déterministe, testable, sans LLM
    │       lit : git log, gh issue list, gh pr list, statut CI
    │       applique : garde-fous globaux, puis l'échelle de priorité (§9)
    │       sort  : (tâche, rôle)  ou  « rien à faire » + rapport
    │
    ├─▶ [2] setup.sh <task-id>   ← déterministe
    │       git worktree add, branche task/42-locate-homographie
    │       réclame la tâche : label in-progress + assignee (atomique)
    │       crée .task.md (id, done, contexte, journal vide)
    │
    ├─▶ [3] AGENT <rôle>         ← le seul endroit avec du jugement
    │       reçoit : .task.md, le critère `done`, son périmètre
    │       travaille, tient son journal dans .task.md
    │       s'arrête quand `done` passe — ou déclare qu'il est bloqué (§10)
    │
    └─▶ [4] finalize.sh          ← déterministe
            lance : tests, lint, types, la commande `done`
            vérifie : diff ⊆ périmètre du rôle, taille du diff sous le plafond
            ouvre la PR, corps généré depuis .task.md
            retire in-progress, pose needs-human-review
```

**Le fichier de suivi `.task.md` fait double emploi, et c'est voulu :**

- c'est la **mémoire de l'agent** — s'il est interrompu, il reprend en le lisant. C'est le
  mécanisme de reprise au niveau tâche, pendant que le scheduler l'assure au niveau projet.
- c'est le **brouillon de la description de PR** — `finalize.sh` le transforme en corps de
  PR. Tu obtiens gratuitement le contexte de relecture : ce qui a été fait, pourquoi, ce
  dont l'agent n'était pas sûr.

Ce dernier point compte : **ce qui rend une PR relisible en 2 minutes au lieu de 20, c'est
la description**, et tu ne veux pas qu'un agent la rédige après coup depuis le diff.

---

## 7. Les décisions comme PR — bonne idée, à formaliser

Ton intuition est juste. Deux précisions qui la rendent opérationnelle.

**Un fichier par décision, pas une table.** `decisions/0007-format-feuille-reponses.md`,
avec un en-tête `statut: proposée | actée | rejetée`. Une table unique (comme le §15 du
document examen) crée des conflits dès que deux décisions sont en vol. C'est le format ADR
classique, et un script régénère l'index.

**Fusionner la PR _est_ la décision.** Pas de vote, pas de commentaire à interpréter :
l'état de la décision est l'état du fichier sur `main`. Déterministe, donc lisible par le
scheduler.

```text
decisions/0007-....md   statut: proposée     →  PR ouverte, label decision:blocking
                        tu fusionnes         →  statut: actée
                        tu fermes            →  statut: rejetée, raison en commentaire
```

Une tâche porte `bloque_sur: [decisions/0007]`. Le scheduler ne la propose pas tant que le
fichier n'est pas `actée` sur `main`. **C'est une arête de dépendance, pas une convention
sociale** — donc vérifiable.

**Le risque à surveiller : la famine.** Si tout est bloqué sur toi, les agents passent
leurs journées à faire de la doc. Deux contre-mesures :

- l'orienteur **groupe** les décisions : une PR avec 5 décisions liées vaut mieux que 5 PRs
- le scheduler **remonte l'alerte** quand la part de tâches bloquées dépasse un seuil —
  c'est une information pour toi, pas un problème pour lui

---

## 8. Le contrôle de débit — c'est ça, « à mon rythme »

Tu valides toutes les PRs. Donc **tu es le goulot d'étranglement**, exactement comme dans
le projet examen où tu es le goulot de la correction. Même médecine :

| Mécanisme | Effet |
| --- | --- |
| **Plafond de PRs ouvertes** (`WIP_MAX`, voir §8.1) | quand il est atteint, le scheduler **s'arrête et te le dit**. Les agents ne peuvent pas te dépasser. |
| **Plafond de taille de diff** (~300 lignes) | au-delà, `finalize.sh` refuse et demande de découper. Une PR relisible, ou pas de PR. |
| **Une tâche = une PR = un objectif** | pas de PR fourre-tout |
| **Budget par tâche** | évite qu'un agent s'acharne trois heures sur une impasse |

**`WIP_MAX` est le vrai bouton « mon rythme ».** Tu es en vacances ? Tu le baisses à 2, les
agents s'arrêtent après deux PRs. Tu as un après-midi ? Tu le montes. C'est un paramètre,
pas une discussion.

Sans ce plafond, un système autonome produit 30 PRs en une nuit et le projet est mort — pas
parce que le code est mauvais, mais parce que tu ne les reliras jamais.

### 8.1 Calibrer `WIP_MAX` : 10 PRs/semaine ne suffit pas à le fixer

Capacité annoncée : **~10 PRs par semaine** (2026-09-18).

C'est un **débit**. Or `WIP_MAX` ne se déduit pas du débit seul, mais de la **latence** —
le temps qu'une PR passe ouverte avant d'être traitée. C'est la loi de Little :

```text
WIP = débit × latence
```

À 10 PRs/semaine (≈ 1,4/jour), selon ta façon de relire :

| Ta cadence de relecture | Latence | `WIP_MAX` |
| --- | --- | --- |
| tous les jours | ~1 j | **2** |
| tous les 2-3 jours | ~2,5 j | **3-4** |
| une fois par semaine, en lot | ~5 j | **7-8** |

**Le paramètre à régler n'est donc pas « combien tu peux relire » mais « à quelle
fréquence tu relis ».** Un plafond trop haut ne te fait pas aller plus vite : il fabrique
une file d'attente, et une PR qui attend 5 jours part en conflit avec les suivantes.

**Cadence réelle (2026-09-18) : une session de 2 h, tous les 3 jours.** Soit ~2,3 sessions
et ~4,7 h de relecture par semaine.

→ **`WIP_MAX = 4`**, dimensionné pour qu'**une session vide entièrement la file**.

C'est le bon réglage parce qu'il préserve une propriété qui vaut plus que le débit :
**après chaque session, la file est vide et les agents repartent d'un `main` propre.**
Pas de branche qui traîne, pas de conflit accumulé, pas de PR qui pourrit. Un plafond plus
haut grignoterait quelques PRs de plus au prix de branches obsolètes — mauvais échange.

Raffinement possible plus tard (pas en v1) : le scheduler **mesure** la latence réelle sur
`gh pr list --state merged` et ajuste tout seul.

### 8.2 Le vrai levier : le temps de relecture par PR

La contrainte n'est pas le nombre de PRs, c'est **le budget de 120 minutes par session**.
Ce qui donne une arithmétique très directe :

| Temps moyen par PR | PRs/session | PRs/semaine |
| --- | --- | --- |
| 25 min | ~5 | ~11 |
| 15 min | ~8 | ~19 |
| 10 min | ~12 | ~28 |

**Diviser par deux le temps de relecture d'une PR double la vitesse du projet.** Aucun
réglage côté agents n'a ce pouvoir-là. C'est donc **là** qu'il faut mettre l'effort :

- **plafond de taille** (~300 lignes) et une PR = un objectif
- **description générée depuis `.task.md`** (§6) : ce qui a été fait, pourquoi, ce dont
  l'agent n'était pas sûr. Relire un diff sans contexte coûte trois fois plus cher.
- **le rôle `reviewer` passe avant toi** et laisse ses commentaires : tu arrives sur une PR
  déjà dégrossie
- **règle dure : `finalize.sh` ne présente jamais une PR qui n'est pas déjà verte et dans
  son périmètre.** Tes 120 minutes ne doivent jamais servir à découvrir un test cassé.

### 8.3 Le déroulé d'une session — l'ordre compte

Pas chronologique. Par effet de levier décroissant :

```text
 1. décisions bloquantes        ~10 min   ← EN PREMIER, toujours
 2. PRs qui débloquent d'autres tâches
 3. le reste, des plus petites aux plus grosses
 4. s'il reste du temps : relire le rapport d'état, arbitrer le cap
```

**Le point 1 est non négociable.** Répondre à une décision coûte 5 minutes et débloque
3 jours de travail d'agents. Si tu commences par le code et que la session déborde, les
agents restent bloqués 3 jours de plus — c'est le pire usage possible de ton temps.

### 8.4 Ce que les agents ne peuvent pas faire

Ton budget de 2 h tous les 3 jours est un budget de **relecture**, pas le budget total du
projet. Une catégorie de tâches ne passera jamais par un agent :

- **S2** : imprimer, faire remplir, scanner (§11 du document examen)
- **la répétition générale du 29 octobre**
- rédiger le contenu du sujet et le barème
- les décisions

→ Prévoir un label **`human-only`** : le scheduler les **affiche** dans le rapport comme
échéances à ta charge, mais ne les propose **jamais** à un agent et ne les compte pas dans
`WIP_MAX`. Sans ça, tu auras un système qui tourne parfaitement pendant que le chemin
critique — qui est physique — n'avance pas.

### 8.5 Ce que ça donne en sessions

| Échéance | Sessions restantes | Budget |
| --- | --- | --- |
| Répétition générale (29 oct) | **~14 sessions** | ~60 PRs |
| Examen (23 nov) | ~22 sessions | ~95 PRs |

M0 + M1 ≈ 30 PRs ≈ **7 sessions**. Il en reste 14 avant le 29 octobre : **la marge est de
2×**, comme estimé. Confortable, à condition de ne pas élargir le périmètre.

### 8.6 La conclusion qui doit guider la conception

**Ta capacité de relecture n'est pas le facteur limitant** (§8.5 : 2× de marge). Le facteur
limitant est la **qualité par PR** — est-ce que le système produit des PRs qui méritent
d'être fusionnées, et qui se relisent vite ?

Donc : ne dépense aucun effort à optimiser le débit des agents. Dépense-le sur les critères
de complétion (§4), le périmètre vérifié (§5), le score de mutation (§10) et la qualité des
descriptions de PR (§8.2). Et garde la marge pour ce qu'elle est — une **provision pour les
mauvaises surprises**, pas une autorisation d'élargir le périmètre.

---

## 9. L'échelle de repli — « il y a toujours quelque chose à faire »

C'est ce qui fait que « avance » marche **toujours**. Le scheduler descend l'échelle
jusqu'à trouver du travail prêt :

```text
P0  CI rouge sur main                    → réparer. Rien d'autre ne compte.
P1  PR ouverte avec une review à traiter → répondre avant d'ouvrir du neuf
P2  tâche `feature` prête et non bloquée → le travail normal
P3  dette de test ciblée                 → module au score de mutation le plus bas
P4  doc manquante ciblée                 → API publique sans docstring, exemple absent
P5  rien                                 → rapport d'état + l'orienteur propose
                                            des tâches ou des décisions
```

P0 et P1 avant P2 : **ne jamais ouvrir un nouveau chantier quand l'existant est cassé ou
en attente.** C'est la règle qui empêche l'accumulation.

**Attention au lest.** P3 et P4 sont le « travail de remplissage » qui rend le système
toujours occupé — et c'est précisément là que la dérive s'installe. Antidote : ils doivent
être **ciblés et bornés**, générés par un script qui mesure (« le module `vision` est à
52 % de score de mutation, cible 80 % »), jamais formulés comme « améliorer les tests ».
Un lest sans critère est un générateur de bruit.

---

## 10. Modes de défaillance, et leurs antidotes

À traiter dès la conception — ce sont eux qui décident si le système est utilisable.

| Défaillance | Pourquoi ça arrive | Antidote |
| --- | --- | --- |
| **Tests en trompe-l'œil** | la couverture est une cible facile à truquer : `assert True`, tests qui n'assertent rien | **score de mutation**, pas couverture (`mutmut`, `cosmic-ray`). Un test qui ne tue aucun mutant ne vaut rien. Et `test` ne peut pas toucher `src/**` (§5). |
| **Volume au lieu de progrès** | tâches floues | `done` exécutable obligatoire (§4) |
| **Dérive** | l'agent fait du plausible mais hors sujet | périmètre de chemins **vérifié** par `finalize.sh` |
| **Doublons / collisions** | deux agents sur la même tâche | réclamation atomique (label + assignee) avant tout travail ; le scheduler ignore ce qui est réclamé |
| **Échec masqué** | l'agent n'arrive pas à satisfaire `done` et « fait au mieux » | **sortie de secours explicite** : il pose `needs-decision`, écrit dans `.task.md` ce qu'il a tenté et pourquoi il bloque, ouvre une PR en _draft_ ou détruit le worktree, et s'arrête. **Ne jamais simuler la réussite.** |
| **Famine de décisions** | tout bloqué sur toi | groupement + alerte (§7) |
| **Coût** | boucles autonomes | budget par tâche, `WIP_MAX` |

La ligne la plus importante du tableau est la première. **La couverture de code est une
cible de Goodhart** : dès qu'un agent est évalué dessus, elle monte sans que la qualité
suive. Le score de mutation résiste beaucoup mieux, et c'est exactement le « critère
objectif » que tu cherches.

---

## 11. Le MVP — construit le 2026-09-18

**État : fait.** Code dans `/Users/ocots/Dev/avance`, 74 tests verts, rien de commité
(à toi de le faire après relecture).

Ce qui est en place : `scheduler.plan()` pur et testé (échelle P0→P5, plafond de débit,
décisions bloquantes, conflits de périmètre), les commandes `next` / `setup` / `finalize` /
`status` / `init` / `brief`, les trois rôles avec périmètres **vérifiés** (dont le contrôle
AST qui empêche le rôle `doc` de modifier autre chose que des docstrings), le mécanisme
`decisions/`, le label `human-only`, et une skill `/avance` pour Claude Code.

Ce qui **n'est pas** fait, délibérément : l'orienteur automatique (§13), le rôle
`reviewer`, l'intégration du score de mutation, les budgets de coût. À ajouter par la
friction, pas par anticipation.

### Ce qu'il fallait construire

Tout le reste est du confort. Ce noyau suffit à rendre « avance » utile :

1. **`scheduler.py`** — lit `gh`, applique l'échelle P0–P5 et les garde-fous, sort une
   tâche. Avec ses tests unitaires sur des états simulés.
2. **`setup.sh` / `finalize.sh`** — worktree, réclamation, `.task.md`, puis vérifs + PR.
3. **Trois rôles seulement** : `feature`, `test`, `doc`. Les autres viendront de la
   friction réelle.
4. **`decisions/`** avec le mécanisme de blocage.
5. **`WIP_MAX = 2`.**

Pas d'orienteur automatique au début : **c'est toi qui écris les premières tâches**, avec
leurs `done`. Tu verras vite lesquelles étaient mal formulées — et c'est cette expérience
qui te dira comment écrire le prompt de l'orienteur. L'automatiser avant d'avoir ce retour,
c'est le construire à l'aveugle.

**Sur le harnais** : Claude Code fournit déjà les briques — définitions de sous-agents avec
restriction d'outils (`.claude/agents/*.md`), skills et commandes slash pour `/avance`,
hooks dans `settings.json` pour les vérifications automatiques, et l'outil `Agent` sait
travailler en worktree isolé. Le travail est dans la **conception du sélecteur et des
critères**, pas dans la plomberie.

---

## 12. ⚠ La tension avec le 23 novembre

À dire franchement, parce que c'est le risque principal.

Tu as **9,5 semaines** et une échéance dure, avec un jalon décisif au **29 octobre**
(document examen, §12). Construire un système d'orchestration d'agents est un projet
en soi — la version complète que tu décris, c'est plusieurs semaines.

**Le piège classique** : passer trois semaines à construire l'outil qui construira l'outil,
et arriver au 29 octobre sans feuille de réponses imprimable.

**Ce que je propose :**

- **le MVP du §11, une fois, en deux jours, cette semaine** — pas plus
- **son premier et unique client est le projet examen.** C'est le test : s'il ne sait pas
  faire avancer un projet réel avec une échéance réelle, il ne sert à rien.
- **il grandit par la friction, jamais par anticipation.** Tu ajoutes un rôle le jour où
  son absence te coûte quelque chose de mesurable — pas parce qu'il figure dans ce document.
- **règle d'arrêt explicite** : si au 8 octobre le MVP n'est pas en service, tu l'abandonnes
  pour cette saison et tu codes le projet examen à la main. Poser la date maintenant.

C'est exactement le principe du projet examen appliqué à lui-même : **peu de
fonctionnalités, mais robustes, et toujours quelque chose qui marche.**

---

## 13. Questions ouvertes

1. **Un dépôt ou deux ?** L'orchestration est-elle un outil générique (dépôt séparé,
   réutilisable sur `control-toolbox`) ou du gréement propre au projet examen
   (`.claude/` dans le dépôt) ? → Je pencherais pour **dans le dépôt examen d'abord**,
   extraction plus tard si ça marche. Extraire trop tôt fige de mauvaises abstractions.
2. **Les agents tournent-ils sans surveillance** (la nuit, via `/loop` ou une routine
   planifiée) ou uniquement quand tu lances `avance` ? Le sans-surveillance change le
   profil de risque : `WIP_MAX` et les budgets deviennent critiques, plus des garde-fous.
3. **Quel niveau de confiance sur les commits ?** Les agents poussent-ils sur leur branche
   sans que tu regardes, ou veux-tu un survol avant la PR ?
4. ~~Capacité et fréquence de relecture ?~~ **Répondu : une session de 2 h tous les 3
   jours, ~10 PRs/semaine** → `WIP_MAX = 4`, et le vrai levier est le temps de relecture
   par PR (§8.1 à §8.6).
5. **Que fait le système quand un test devient rouge sur `main` à cause d'une PR
   fusionnée ?** Revert automatique, ou tâche P0 et on répare ? (Je propose P0 : le revert
   automatique surprend plus qu'il n'aide sur un projet solo.)
