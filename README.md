# crank

Orchestration d'agents autonomes sur un dépôt git.

> **La sélection du travail est déterministe. Seule l'exécution est un agent.**

Si un modèle décide « sur quoi dois-je travailler ? », on obtient de la dérive et un
comportement non reproductible, impossible à déboguer. Ici c'est un script qui décide,
à partir de l'état objectif du dépôt — donc le même état produit toujours le même plan,
et le sélecteur lui-même est couvert par des tests.

L'agent reçoit une tâche **déjà choisie**, avec son critère de complétion, et n'a qu'un
seul travail : la faire.

## Installation

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Requiert `git` et [`gh`](https://cli.github.com/) authentifié.

## Usage

```bash
cd /chemin/vers/ton/depot
crank init            # .crank.toml, decisions/, labels GitHub

crank next            # que faut-il faire maintenant ? (sans effet de bord)
crank setup 42        # worktree + branche + réclamation + .task.md
#   … l'agent travaille dans le worktree …
crank finalize        # vérifications, puis PR — refuse si une vérification échoue

crank status          # l'ordre de ta session de relecture
```

## Définir une tâche

Une issue GitHub, avec un bloc `crank` dans le corps :

~~~markdown
Le recalage échoue quand la feuille est photographiée de biais.

```crank
role: feature
done: pytest tests/vision/test_locate.py -q
touche:
  - src/exam_core/vision/**
  - tests/vision/**
bloque_sur: ["0007"]
budget: 1 session
```
~~~

**Une tâche sans `done` exécutable en une commande n'est pas recevable.** C'est le filtre
qui empêche le système de produire du volume au lieu du progrès — et c'est pour ça que le
rôle le plus important n'est pas celui qui code, mais celui qui écrit les critères.

## L'échelle de priorité

`crank next` descend cette échelle et rend la première action possible :

| | | |
| --- | --- | --- |
| **P0** | CI rouge sur `main` | réparer — rien d'autre ne compte, ignore le plafond |
| **P1** | PR avec changements demandés | répondre avant d'ouvrir du neuf, ignore le plafond |
| **P2** | tâche `feature` prête | le travail normal |
| **P3** | tâche `test` | dette de test ciblée |
| **P4** | tâche `doc` | documentation ciblée |
| **P5** | rien | rapport d'état — décisions en attente, tâches mal formées, `human-only` |

## Les garde-fous

Ce ne sont pas des consignes dans un prompt : ce sont des vérifications qui refusent la PR.

- **`wip_max`** — plafond de PRs ouvertes. Atteint, le scheduler s'arrête et te le dit.
  Dimensionné pour qu'**une session de relecture vide la file**. Il ne limite que
  l'ouverture de *nouvelles* PRs : P0 et P1 passent outre.
- **`max_diff_lines`** — une PR relisible, ou pas de PR.
- **périmètre par rôle** — le diff doit rester dans les chemins déclarés. En particulier,
  le rôle `test` **ne peut pas toucher au code de production** : sans ça, un agent « fait
  passer le test » en modifiant le code testé.
- **`docstrings_only`** — le rôle `doc` peut toucher `src/**`, mais l'AST privé de ses
  docstrings doit rester identique. Vérifié, pas supposé.
- **données sensibles** — chemins et motifs interdits (`[sensitive]`, voir plus bas) :
  refusés même en `--draft`, parce qu'une donnée poussée ne se rattrape pas.
- **critère `done`** — exécuté ; s'il échoue, aucune PR n'est ouverte.
- **conflits de périmètre** — deux tâches aux chemins qui se recouvrent ne partent jamais
  en parallèle.

## Les données sensibles

Copies d'examen, relevés bancaires, listes nominatives : la règle est que les données
vivent **hors du dépôt**. Le `.gitignore` n'est qu'un filet — rien n'empêche un agent de
commiter une fixture « réaliste » copiée d'un vrai fichier, ou un fichier égaré dans un
chemin imprévu. Et un commit poussé ne se rattrape pas.

D'où une vérification **dure** de `crank finalize`, déclarée par dépôt :

```toml
[sensitive]
forbidden_paths = ["data/**", "*.csv", "*.pdf"]   # fichiers interdits dans le diff
allowed_paths   = ["tests/fixtures/**"]           # où les données fictives sont permises
patterns = [                                      # motifs interdits dans les lignes ajoutées
  { name = "IBAN",   regex = '\bFR\d{2}(?:\s?[0-9A-Z]{4}){5}\s?[0-9A-Z]{3}\b' },
  { name = "e-mail", regex = '[\w.+-]+@[\w-]+\.[\w.]+' },
]
```

- Seuls les fichiers **ajoutés ou modifiés** et les lignes **ajoutées** sont examinés :
  une donnée qu'une PR retire, ou qui était déjà là, n'est pas son affaire.
- `allowed_paths` échappe aux deux contrôles, chemins et motifs.
- Le refus désigne le fichier, la ligne et la règle — **jamais la valeur trouvée**, qui
  finirait sinon dans un terminal, un log ou un corps de PR.
- Une regex invalide est refusée au chargement de la configuration, pas au moment où la
  PR devait être protégée.
- Sans section `[sensitive]`, la vérification passe. `crank init` en propose une,
  commentée.

## Les décisions

Un fichier par décision dans `decisions/`, avec un champ `statut`. Une tâche déclare
`bloque_sur: ["0007"]` et reste invisible tant que la décision n'est pas tranchée.

**Fusionner la PR vaut décision** — l'état est celui du fichier sur `main`, donc lisible
par le scheduler comme une vraie arête de dépendance, pas comme une convention sociale.

Un fichier par décision (et non une table) parce que plusieurs décisions peuvent être en
vol simultanément : une table entrerait en conflit à chaque fois.

## `human-only`

Certaines tâches ne passeront jamais par un agent : imprimer et scanner, animer une
répétition, rédiger un contenu, trancher une décision. Le label `human-only` les fait
apparaître dans `crank status` comme échéances à ta charge, sans jamais être proposées
à un agent ni comptées dans le plafond.

Sans ça, on obtient un système qui ronronne pendant que le chemin critique — souvent
physique — n'avance pas.

## Tests

```bash
.venv/bin/python -m pytest
```

Le scheduler étant une fonction pure `(RepoState, Config) -> Plan`, ses tests sont des
états simulés en entrée et des plans attendus en sortie. Aucun dépôt, aucun réseau.
