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
- **critère `done`** — exécuté ; s'il échoue, aucune PR n'est ouverte.
- **conflits de périmètre** — deux tâches aux chemins qui se recouvrent ne partent jamais
  en parallèle.
- **dépendances** — une tâche qui attend une autre (`bloque_sur: ["#12"]`) ne part pas
  avant sa fusion.

## Les décisions

Un fichier par décision dans `decisions/`, avec un champ `statut`. Une tâche déclare
`bloque_sur: ["0007"]` et reste invisible tant que la décision n'est pas tranchée.

**Fusionner la PR vaut décision** — l'état est celui du fichier sur `main`, donc lisible
par le scheduler comme une vraie arête de dépendance, pas comme une convention sociale.

Un fichier par décision (et non une table) parce que plusieurs décisions peuvent être en
vol simultanément : une table entrerait en conflit à chaque fois.

## Les dépendances entre tâches

Une tâche qui a besoin du **code** d'une autre l'attend avec `bloque_sur: ["#12"]`, à
côté des décisions :

```crank
bloque_sur: ["0007", "#12"]
```

Elle reste invisible tant que l'issue 12 est ouverte. La PR de la tâche 12 contient
`Closes #12` : **la fusionner ferme l'issue et débloque la suite**. Une issue fermée
sans fusion débloque aussi — ce qui bloque, c'est ce qui n'est pas terminé. Une
référence vers une issue inconnue bloque, et `crank next` le dit.

Le recouvrement de périmètres ne suffit pas pour ça : il ne protège que tant que l'autre
tâche est réclamée. Dès sa PR ouverte, elle ne l'est plus, et la suivante partirait d'un
`main` qui ne contient pas encore ce dont elle a besoin.

`crank status` remonte en tête les PRs qui débloquent d'autres tâches (« ⟵ débloque
#13 ») : les relire d'abord libère le plus de travail.

**Les guillemets sont obligatoires** autour de `"#12"` : sans eux, YAML lit `#12` comme un
commentaire. Le bloc est alors refusé, avec un message qui le dit.

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
