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

## Requêtes SQL : `scripts/sql.sh`, jamais l'outil MCP, jamais demandé à Raphaël

**N'utilise pas `mcp__Supabase__execute_sql`, et ne demande jamais à Raphaël
d'exécuter une requête à ta place.** Cet outil impose un pop-up à chaque
appel, imposé par le serveur MCP lui-même — aucun réglage de permissions ne
peut le lever, même en accès complet. Raphaël travaille depuis son
téléphone.

```bash
scripts/sql.sh "select id, nom from clients limit 5;"
```

Passe par l'API HTTPS de Supabase (`rest/v1/rpc/exec_sql`), donc par Bash :
aucune validation. Ajouté le 22 sept. 2026 — ce dépôt partage le MÊME projet
Supabase que Jarvis-assistant (`bexiyvmdbxcwxasgslxp`), `exec_sql` y existe
déjà (créée par une migration de Jarvis-assistant), rien à recréer ici.
Script identique à celui de Jarvis-assistant et melissa-nabet. Testé contre
la vraie base (succès et cas d'erreur) avant d'être committé.

Accès total à la base (DDL et suppressions comprises) : toujours demander à
Raphaël avant un `DROP`, un `DELETE` massif ou un `TRUNCATE`.

## Demandes de règles Prélèvement : statut `a_verifier`, jamais `valide` directement

Depuis le 2026-09-22 (retour du père de Raphaël : "il faut un vrai système
question/réponse, bouton validé par l'admin fonctionnel sinon bouton à
corriger, sinon ça fait des doublons") : une session Claude Code qui vient
de coder, tester et **déployer** (vérifié `live` sur les deux services
Render) une demande de `prelevement_rule_requests` passe son statut à
**`a_verifier`**, jamais directement à `valide`. `valide` n'est posé que par
un humain (bouton "✅ Ça fonctionne, je valide" dans l'écran) — jamais par
une session Claude Code elle-même.

Si le père de Raphaël clique "✏️ Corriger" sur une règle `a_verifier` : la
demande repasse à `en_cours` et sa `demande` est complétée avec le texte de
correction (même ligne, même id) — **ne jamais créer une nouvelle
`prelevement_rule_request` pour corriger une règle déjà existante**, sauf
si c'est un sujet réellement distinct.

## Décisions en attente (fiches à remplir)

- **Fonctionnalités Base de données** (2026-09-17) :
  https://claude.ai/artifact/DYHosfZYYCWQZ12vic2nzP — l'utilisateur
  sélectionne les fonctionnalités qu'il veut (✅/🕒/❌), enregistré
  automatiquement dans l'artefact lui-même (capacité `db`). Lire les
  réponses avec l'outil Artifact/ArtifactData (`read_db`), pas dans
  Supabase. Voir `PROJECT_LOG.md` pour le détail.
