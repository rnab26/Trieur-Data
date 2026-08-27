# CLAUDE.md — Trieur de Data

Consignes de travail pour Claude Code sur ce repo. À lire avant toute
intervention.

## Exécution autonome

- "Demande explicite" veut dire que l'utilisateur a confirmé une tâche
  (ou une liste de tâches) UNE FOIS dans la discussion. À partir de là,
  tout s'exécute de bout en bout sans redemander à chaque étape :
  commit, push, **merge sur `main`**, déploiement si c'est le but de la
  tâche. Ne jamais renvoyer la balle à l'utilisateur pour une action
  d'exécution (cliquer dans GitHub, un dashboard, etc.) — c'est à faire
  soi-même.
- Si un outil ou une contrainte technique bloque une action normalement
  autorisée (ex. `git push` refusé), chercher un autre chemin qui aboutit
  au même résultat (API GitHub, autre méthode) plutôt que de reporter la
  décision sur l'utilisateur.
- Rendre compte APRÈS coup, pas avant, sauf pour une vraie décision
  ambiguë que seul l'utilisateur peut trancher (choix de design non
  précisé, arbitrage produit...).
- Si quelque chose casse suite à une action faite en autonomie, revenir
  en arrière dès que l'utilisateur le signale — pas besoin d'une
  validation préalable pour ça non plus.

## Discipline de branche (code applicatif)

- Chaque chantier de code a sa propre branche. Ne jamais déborder sur la
  branche d'un autre chantier en cours.
- Merger/déployer du code reste conditionné à une tâche confirmée (voir
  "Exécution autonome" ci-dessus) — mais l'exécution complète, merge sur
  `main` inclus, est toujours faite directement, sans repasser par
  l'utilisateur.

## Fichiers de doc/suivi (CLAUDE.md, PROJECT_LOG.md)

- Ces deux fichiers se mettent à jour sur `main` sans même demander de
  confirmation à chaque fois : c'est une mise à jour de routine, pas une
  vraie décision.
- Si `git push` vers `main` est bloqué par une contrainte de session,
  utiliser l'API GitHub (`create_or_update_file` ou équivalent) pour
  écrire directement sur `main` à la place.

## Rigueur technique

- Ne jamais deviner une API externe : vérifier la vraie documentation ou
  le code source avant d'écrire du code qui en dépend.
- Ne jamais simuler ou supposer un résultat : un correctif n'est validé
  qu'après un vrai test qui passe — pas une relecture de code, pas une
  supposition.
- En cas de régression ou de bug signalé, remonter à la cause racine
  (bisection si besoin) plutôt que de patcher le symptôme.

## Pendant les temps d'attente

- Utiliser les temps morts (CI, build...) pour chercher d'autres
  améliorations possibles plutôt que d'attendre passivement.

## Honnêteté

- Dire clairement quand une approche plafonne ou ne fonctionne pas,
  plutôt que d'enjoliver ou de minimiser.
- Signaler immédiatement tout identifiant/secret qui transite en clair
  (logs, code, message) pour rotation.
- Rappeler de réduire ou couper les ressources externes coûteuses (GPU,
  instances cloud...) une fois une configuration validée.

## Communication

- Toujours rendre compte en français, de façon concise et directe.

## Suivi du travail

- Voir `PROJECT_LOG.md` pour l'état des chantiers en cours sur ce repo.
- Chaque nouvelle idée/demande/tâche à ne pas oublier va dans la section
  "Notes / À faire" du chantier concerné dans `PROJECT_LOG.md`, poussée
  directement sur `main`. Une tâche faite est cochée `[x]`, jamais
  supprimée.
