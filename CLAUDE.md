# CLAUDE.md — Trieur de Data

Consignes de travail pour Claude Code sur ce repo. À lire avant toute
intervention.

## Discipline de branche

- Ne jamais travailler directement sur `main`. Toujours rester sur la
  branche du chantier en cours.
- Ne jamais merger une PR ni déployer sans demande explicite de
  l'utilisateur, même si tous les tests passent. Pousser le correctif
  validé sur la branche du chantier et ouvrir/mettre à jour la PR, puis
  attendre l'accord pour merger.
- Si merger soi-même est techniquement bloqué par la configuration de la
  session, le dire clairement plutôt que de chercher un contournement —
  l'utilisateur mergera lui-même via GitHub.
- Cas particulier : CLAUDE.md et PROJECT_LOG.md vivent sur leur propre
  branche (pas la branche de feature en cours). Même règle de
  confirmation explicite avant merge sur `main`.

## Autonomie par défaut

- Corriger un bug évident, relancer un test, pousser un correctif validé
  sans redemander la permission à chaque étape.
- Ne pas attendre de confirmation pour des actions réversibles et locales
  au chantier (lancer les tests, ajuster le code, committer sur la
  branche de travail).

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
  "Notes / À faire" du chantier concerné dans `PROJECT_LOG.md`. Une tâche
  faite est cochée `[x]`, jamais supprimée.
