# CLAUDE.md — Trieur de Data

Consignes de travail pour Claude Code sur ce repo. À lire avant toute
intervention.

## Discipline de branche (code applicatif)

- Ne jamais travailler directement sur `main` pour du code applicatif.
  Toujours rester sur la branche du chantier en cours.
- Ne jamais merger une PR de code ni déployer sans demande explicite de
  l'utilisateur POUR CE CHANGEMENT PRÉCIS, même si tous les tests
  passent. Pousser le correctif validé sur la branche du chantier et
  ouvrir/mettre à jour la PR, puis attendre l'accord pour merger.
- Si merger soi-même est techniquement bloqué par la configuration de la
  session, le dire clairement plutôt que de chercher un contournement —
  l'utilisateur mergera lui-même via GitHub.

## Exception : fichiers de doc/suivi (CLAUDE.md, PROJECT_LOG.md)

- Ces deux fichiers sont créés, modifiés et poussés **directement sur
  `main`**, sans demander confirmation à chaque fois — l'utilisateur ne
  veut pas valider ça manuellement dans GitHub.
- Si `git push` vers `main` est bloqué par une contrainte de session,
  utiliser l'API GitHub (`create_or_update_file` ou équivalent) pour
  écrire directement sur `main` à la place.
- Cette exception ne s'applique qu'à ces deux fichiers de suivi — jamais
  au code applicatif.

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
  "Notes / À faire" du chantier concerné dans `PROJECT_LOG.md`, poussée
  directement sur `main`. Une tâche faite est cochée `[x]`, jamais
  supprimée.
