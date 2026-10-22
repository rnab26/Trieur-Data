# CLAUDE.md — Trieur de Data

<!-- cockpit-premier-geste:début -->
## Cockpit — PREMIER GESTE de la session (si aucun bloc « Cockpit » n'est dans ton contexte)

Une session ouverte sur plusieurs dépôts démarre dans `/home/user` : aucun hook ne tourne, donc le cockpit ne te voit pas et Raphaël ne voit pas ta session. Avant toute autre action, lance UNE fois :

`bash /home/user/Cockpit-General/scripts/connecter.sh --projet trieur-data`

(si `/home/user/Cockpit-General` manque : `git clone -q --depth 1 https://github.com/rnab26/Cockpit-General /home/user/Cockpit-General` d'abord). Il affiche l'état du projet et rend ta session visible dans « Ça avance » ; un petit processus refait son signe de vie tant qu'elle est ouverte. Plusieurs projets dans la session : prends celui du sujet de Raphaël. Si un bloc « Cockpit » est déjà dans ton contexte, ne fais rien.
<!-- cockpit-premier-geste:fin -->

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
- **Depuis le 2026-10-14, le projet est branché sur le cockpit central**
  (projet « Trieur de Data », bloc « Cockpit » en bas de ce fichier, app
  https://rnab26.github.io/Cockpit-General/). Les chantiers (à faire, en
  cours, à vérifier) y vivent : réserve-les, signale ta progression et pose
  tes questions avec les commandes `scripts/cockpit-*.sh`. `PROJECT_LOG.md`
  reste le journal technique (décisions, leçons, détail de ce qui a été
  fait). Ne pas confondre avec le « Cockpit » intégré à l'appli du Trieur
  (écran Cockpit, tables `chantiers` et `prelevement_rule_requests`) : ses
  3 chantiers ouverts ont été repris dans le cockpit central et son tableau
  n'est plus mis à jour ; les demandes de règles du père de Raphaël y
  restent, inchangées.

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


## Cockpit (rnab26/Cockpit-General)

Ce projet est suivi dans le cockpit central (projet `trieur-data`, app
https://rnab26.github.io/Cockpit-General/, base Supabase centrale, schéma `cockpit`).
Le hook `.claude/hooks/cockpit-session-start.sh` injecte l'état au démarrage :
chantiers ouverts par section, questions en attente, réponses humaines,
demandes des utilisateurs, progression des autres sessions.

- **RÉPONSES À RAPHAËL : simples, courtes, nettes, précises** (29 sept. : « je
  veux des réponses simples, courtes, nettes et précises ; pas de pavé »).
  Quelques lignes : la réponse d'abord, puis ce qu'il doit faire s'il y a
  quelque chose. Pas de détail technique sauf s'il le demande.
- **« COMMENT VÉRIFIER » = UNE observation évidente** (29 sept. : « je ne sais
  pas si le résultat est le bon, il faudrait comparer, compter »). Écris ce
  qu'il doit VOIR, reconnaissable d'un coup d'œil (« le bouton est vert »),
  jamais « compte / compare ». Ce qui demande de juger, vérifie-le toi-même et
  donne la preuve. S'il touche « Je ne sais pas : vérifie pour moi », c'est à
  toi de juger ce qu'il a collé : `scripts/cockpit-verdict.sh --chantier <id>
  --bon "…"` ou `--pas-bon "…"` (la session chef du projet lance un agent pour ça).
- **UNE RÉPONSE DE RAPHAËL N'EST JAMAIS PERDUE** (29 sept. : « je réponds, mais
  je ne sais pas si c'est pris en compte »). Sur un chantier que tu tiens, elle
  t'arrive en direct : suis-la tout de suite (un message ou une étape). Sur un
  chantier que personne ne tient, la session chef du projet la confie à un agent
  (« Claude reprend ta réponse » dans le fil) : ne la reprends pas en doublon.
- **UN MESSAGE DE RAPHAËL DANS UN FIL = UNE RÉPONSE COURTE DE CLAUDE DANS CE
  FIL, AVANT DE CONTINUER** (29 sept. : « je pose des questions du type "je n'ai
  pas compris ta demande" et je n'ai pas de retour […] comme une discussion
  WhatsApp »). Une étape ne compte PAS : il faut un message écrit, la réponse
  d'abord, 400 caractères au plus :
  `scripts/cockpit-progression.sh --chantier <id> --point "…"` (fil du projet :
  sans `--chantier`). Son écran affiche « réponse en attente » jusque-là. Sur un
  fil que personne ne tient, la session chef confie la réponse à un agent
  (« Répondre : … ») : ne réponds pas en doublon.
- **UN SUJET = UN FIL, LA SESSION ET LE COCKPIT SONT DEUX PORTES ÉGALES** (29
  sept. : « on discute de plusieurs points et tu y réponds en essayant de tout
  condenser […] je zappe certaines choses » ; « on peut utiliser peu importe
  soit le cockpit soit la session Claude »). Un message qui aborde plusieurs
  sujets : rattache CHACUN à son chantier (`scripts/cockpit-chantier.sh
  --ouvrir` : il reprend, regroupe ou crée), réponds normalement dans la
  session ET écris la réponse de chaque sujet dans son fil
  (`scripts/cockpit-progression.sh --chantier <id> --point "…"`). Ses mots y
  sont recopiés tout seuls (hook de suivi) ; ta réponse, c'est toi. Le hook
  d'arrêt refuse UNE fois l'arrêt si un chantier ouvert ou repris pendant le
  tour n'a pas sa réponse dans son fil. Il demande de mettre de côté, reporter
  ou abandonner : `scripts/cockpit-chantier.sh --de-cote <id> [--jusqu-au
  AAAA-MM-JJ]` ou `--abandonner <id>` (mêmes gestes que les boutons du fil).
- **UN AUTRE SUJET ÉCRIT DANS UN FIL (« il faudrait aussi X ») → C'EST TOI
  QUI CRÉES LE CHANTIER** (30 sept. : « plutôt que de quitter ce chat et de
  créer un nouveau chantier manuellement […] que la session Claude comprenne
  qu'il faut créer le chantier et l'attribuer là où c'est nécessaire ») :
  `scripts/cockpit-chantier.sh --ouvrir "<titre>" --demande "<ses mots>"
  --depuis <id du fil | projet> --reponse "<ta réponse, 400 car.>"`. Créé
  « Prêt à lancer » (non réservé), rangé (Correctifs, sinon la section du
  fil, ou `--section`), ou ajouté au chantier vivant qui existe déjà ; ta
  réponse arrive dans son fil avec un bouton vers le nouveau. Ne le code pas
  dans la foulée sauf s'il le demande.
- **TES QUESTIONS RESTENT À JOUR** (29 sept. : « je ne veux pas répondre à
  des choses déjà faites, déjà répondues ou en cours »). Dès que tu avances sur
  un chantier où tu as une question ouverte : `scripts/cockpit-demander.sh
  --confirmer <id>` si elle compte encore, `--retirer <id> "pourquoi"` sinon.
  Le hook te le rappelle ; l'app marque « Claude a avancé depuis ». Pareil
  pour un chantier « à vérifier / à cadrer / bloqué » (0022) : `--confirmer
  <id du chantier>`, et `--debloquer <id> "pourquoi"` quand il ne l'est plus.
- **RÈGLE DE CLARTÉ — tout ce que Raphaël lit dans le cockpit** (questions,
  constats à faire, « comment vérifier », titres, messages du fil) : le plus
  simple possible, pour quelqu'un qui ne code pas. On doit comprendre **le
  sujet**, **ce qu'il y a à faire**, et pouvoir **répondre d'un toucher**. Une
  question = une phrase (140 car.) + un pourquoi en mots de tous les jours +
  2 à 4 réponses toutes prêtes, chacune disant ce qui se passe si on la
  choisit. Pas de jargon, pas d'identifiant, pas de chiffres techniques : le
  détail va dans le fil. Les scripts refusent ce qui dépasse (Raphaël, 29 sept. :
  « dans 80 % des cas je ne comprends pas, donc je ne peux pas répondre »).
  **Écrire pour un jeune de 15 ans** (Raphaël, 6 oct. : « du jargon, du
  charabia, toujours les mêmes phrases ») : des mots de tous les jours, une idée
  par phrase, un verbe d'action au début de chaque étape, et jamais la même
  formule recopiée d'une carte à l'autre. Pas : « Fusionne la PR, la CI est
  verte, le hook est propagé ». Mais : « Touche « Merge pull request » : le
  changement part en ligne. » `scripts/clarte.py` refuse les mots de
  développeur (endpoint, hook, migration, commit, branche, script, déployer…)
  dans les questions, étapes, « comment vérifier », résumés et réponses ; le nom
  exact d'un bouton va entre « », le détail technique dans le fil.
- **Chaque demande de travail de Raphaël → un chantier, AVANT de coder** :
  `scripts/cockpit-chantier.sh --ouvrir "<titre court>" --demande "<ses mots>" --section "<rubrique>"`.
  Il reprend (ou rouvre) le chantier existant au lieu d'en créer un doublon.
  **C'est TOI qui tranches, jamais Raphaël** (ses mots, 29 sept. 2026 :
  « personne mieux que Claude sait si c'est un doublon […] ce n'est pas à moi
  de trier, catégoriser à chaque fois ») : sur « ambigu », lis les extraits
  affichés et relance avec `--id <le bon>` ou `--nouveau`, sans lui demander.
  Range toujours dans une section (`--section`, créée si elle n'existe pas ;
  après coup : `--ranger <id> --section "…"`). Un petit correctif visuel, de
  mise en page ou d'ergonomie va dans **« Correctifs »** : sans `--section`, il
  y est rangé tout seul à la création (règle `cockpit.est_correctif`, même pour
  l'app et le module embarqué) ; un faux tri se corrige par `--ranger`. Si deux chantiers existants
  sont en fait le même sujet, **suggère** la fusion :
  `--suggerer-fusion <id à absorber> --dans <id qui reste> --pourquoi "…"` —
  il l'accepte d'un toucher dans l'app. Un rappel le redit à chaque message
  (hook `cockpit-prompt-rappel.sh`).
- **Tes agents et tes commandes longues sont suivis tout seuls** (hook
  `cockpit-suivi.sh` : Raphaël voit dans le cockpit chaque session, ses agents,
  depuis quand ils tournent). Ce qui ne se devine pas, c'est leur avancement :
  **dans la consigne de CHAQUE agent que tu lances**, écris-lui d'appeler
  `scripts/cockpit-progression.sh --agent "<la description exacte que tu lui
  as donnée>" --chantier <id> --etape "…" --pct N --eta 10m` à chaque étape,
  et `--agent "…" --termine "…"` à la fin. Donne des descriptions d'agents
  lisibles par Raphaël (le sujet, pas la technique).
- **UN CHEF PAR PROJET** (29 sept. : « je ne veux pas gérer sur une seule
  session plein de projets en même temps […] ça doit se faire dans la session
  concernant le projet en question, sinon ça mélange tous les contextes »).
  La session où Raphaël écrit devient chef de CE projet (`trieur-data`), et de lui
  seul : `scripts/cockpit-chef.sh` lui donne les chantiers, réponses et
  vérifications de ce projet, qu'elle confie à des agents ; les autres projets
  ont leur chef dans leur propre session, n'y touche jamais d'ici. Quand elle
  le devient, la consigne dit de créer (ou déplacer) SON réveil horaire, puis
  de le noter : `scripts/cockpit-chef.sh --reveil <trig_…> --distante <session_…>`.
  `--etat` : qui dirige ; `--max <n>` : agents en parallèle pour ce projet.
- **RENFORTS** (0024) : Raphaël les demande d'un bouton du cockpit (« Lancer
  des renforts ») : une session cloud par SECTION en attente. La passe de la
  chef te dit d'ouvrir chaque demande (`create_session`, titre « Renfort ·
  <projet> · <section> — ne pas toucher », tags `cockpit-renfort`), de la
  noter (`scripts/cockpit-renfort.sh --session <id> <session_…>`, ou
  `--erreur`), et d'archiver les renforts finis (`archive_session`, accord
  de Raphaël donné d'avance, puis `--archive <id>`). Tu es TOI-MÊME un renfort
  (consigne « [cockpit-renfort] ») : `scripts/cockpit-renfort.sh --suivant
  <id>` te donne tes chantiers (ta section seulement, un agent chacun), puis
  ATTENDS ou FINI ; tu ne prends rien d'autre et tu ne dis rien à Raphaël ici.
- **Limite d'usage et mode autonome** : la reprise de la tâche en cours quand
  une limite se lève est native (`autoContinueAtUsageLimit`, posé par
  brancher.sh). Si le projet est en « mode autonome » (allumé par Raphaël
  jusqu'à une heure), le hook `cockpit-autonome.sh` te donne à la fin de ta
  tâche le chantier LIBRE suivant, déjà réservé : suis ses règles (aucune
  dépense, aucune suppression, aucun envoi ; une décision de Raphaël → une
  question dans le cockpit, puis passe au suivant).
- **Réserver avant de toucher** : `scripts/cockpit-sql.sh "select reserver_chantier('<id>', '<ta branche>', 120)"`
  (false = une autre session l'a). Libérer : `liberer_chantier(id, branche)`.
- **Progression en direct, à chaque étape et en terminant** :
  `scripts/cockpit-progression.sh --chantier "<titre ou id>" --etape "…" --pct 40 --eta 25m`,
  les étapes de mise en ligne au fil de l'eau : `--jalon pousse --detail <commit>`,
  `--jalon ci-ok`, `--jalon en-ligne --detail <adresse vérifiée>` (ou
  `--jalon pas-en-ligne --detail <raison>`), puis `--termine "…" --verifier "1. … 2. … 3. Tu dois voir …"` (le chantier
  passe « à vérifier » ; `--verifier` est obligatoire : où aller, quoi faire,
  ce que Raphaël doit voir, sans jargon, avec le LIEN EXACT https://… à ouvrir
  dans l'étape 1 ; rien à ouvrir : `--sans-lien "pourquoi"`) ou `--echec "…"`.
  Le même tableau s'affiche dans la session : c'est le visuel de progression.
- **LES CHANTIERS SE FERMENT D'APRÈS GITHUB, DANS TOUS LES PROJETS** (13 oct. : « mes
  chantiers ne sont pas à jour […] ça doit être général, tous les projets actifs et
  futurs »). Un chantier que plus personne ne tient et dont le travail est fusionné dans
  `main` passe « à vérifier » tout seul (« Livré, d'après GitHub », preuve dans son fil ;
  lu à l'ouverture d'une session et aux messages, 20 min au plus). Donc : (1) signale
  chaque envoi, `scripts/cockpit-progression.sh --jalon pousse --detail <commit>` est la
  preuve la plus sûre ; (2) avant de t'arrêter, `--termine`, ou `scripts/cockpit-chantier.sh
  --de-cote <id>` / `--abandonner <id>`, sur chaque chantier que tu tiens ; (3) au rappel
  « SANS TRACE depuis longtemps », réponds pour CHACUN (terminé / étape / de côté) ; (4) ce
  que Raphaël te dit EN SESSION d'un chantier livré (« ça marche », « ça ne marche pas »),
  écris-le dans son fil (`--point`) : tu ne certifies jamais. Un chantier passé « livré » à
  tort : « Ça ne marche pas » le renvoie en correction. Réglages (par projet et général) :
  écran « Chantiers et GitHub ».
- **« Où ça en est ? »** (Raphaël le demande d'un bouton ; le hook te le met
  sous les yeux) : réponds TOUT DE SUITE dans le fil, 3 lignes au plus (fait /
  reste / ce qui bloque) : `scripts/cockpit-progression.sh --chantier <id> --point "…"`.
  Son écran passe alors à « Réponse arrivée ».
- **Une question à un humain** : `scripts/cockpit-demander.sh --chantier … --question … --pourquoi … --option "libellé|aide|recommande"`
  (`--action` pour quelque chose qu'il doit faire). Jamais dans un artefact.
  **Bloqué en attendant Raphaël (un fichier, une photo, une décision) = tu POSES la
  question (ou l'action) avant de t'arrêter, jamais seulement dans ta réponse** : sinon le
  chantier reste « à lancer » sans qu'il sache que c'est lui qu'on attend (FacePro, 6 oct.).
- **UNE ACTION MANUELLE = LIEN EXACT + ÉTAPES NUMÉROTÉES + TEXTE PRÊT À
  COLLER** (Raphaël, 30 sept. : « à chaque fois il faut que j'aille chercher
  et ce n'est pas assez précis ; des liens précis, des démarches précises pour
  faire simplement des copier-coller, et un visuel si ça peut aider »). Vaut
  pour TOUT geste demandé à Raphaël, quel que soit le chantier, dans le
  cockpit ET dans la conversation de la session : (1) l'adresse EXACTE de la
  page où agir (réglages, formulaire : jamais la page d'accueil du service,
  jamais « va dans les paramètres ») ; (2) un geste par étape, numérotée, avec
  le nom exact du bouton ou du champ ; (3) chaque chose à taper, prête à coller
  (nom de variable, valeur, commande, texte) ; (4) une capture de la page quand
  ça aide à s'y retrouver. Dans le cockpit :
  `scripts/cockpit-demander.sh --action --chantier <id> --question "…" --pourquoi "…"
  --lien "https://…|Ouvrir …" --etape "Dans « Name », colle le nom ci-dessous"
  --etape "Touche « Add secret »" --copier "Nom du secret|RUNPOD_API_KEY" --image capture.png`
  (le script REFUSE une action sans lien ni étape ; `--sans-lien "pourquoi"`
  si aucune page n'existe, geste sur le téléphone par exemple). Un secret ne
  se colle JAMAIS dans le cockpit (refusé) : dis où le trouver et où le coller.
  Avant de demander, vérifie que le geste est vraiment impossible pour toi
  (API, CLI, script) : ne le demande qu'en dernier recours.
- **Une PR à fusionner = une carte, posée par le script** (Raphaël, 30 sept. 2026 :
  « aucune notification pour savoir quand merger »). Dès que tu ouvres une PR
  que la plateforme ne te laisse pas fusionner, lance IMMÉDIATEMENT
  `scripts/cockpit-pr-a-fusionner.sh <n>` : une carte « À toi » avec le lien de
  la PR et les 2 gestes (Merge, Confirm), sans doublon (clé = numéro), retirée
  seule quand la PR est fusionnée (`--fermee`). Ne pose jamais cette action à la main.
  **La carte n'arrive que si la PR est propre** (30 sept., chantier 6ef35b6e) :
  juste AVANT d'ouvrir la PR, `git fetch origin && git merge origin/main` dans ta
  branche (garde les deux côtés), relance les tests rapides. Le script répond
  « PAS PRÊTE : … » (conflit, CI en cours ou en échec) au lieu de poser la carte :
  la chef envoie un agent qui règle le conflit, puis la carte arrive. Une migration :
  son numéro vient de `scripts/prochaine-migration.sh`, au moment d'écrire le fichier.
- **Montre, ne décris pas** (Raphaël, 29 sept. 2026 : « montre-moi des images
  pour que je comprenne mieux, ou ce que je suis censé voir ») : une question
  ou une vérification qui porte sur quelque chose de VISIBLE (un écran, un
  rendu, un avant/après) → joins une capture. `--image capture.png` sur
  `scripts/cockpit-demander.sh` (sous la question) et sur
  `scripts/cockpit-progression.sh --termine … --verifier …` (« Ce que tu dois
  voir », sous les étapes) ; dans le fil :
  `scripts/cockpit-media.sh --envoyer --chantier <id> --texte "…" --image capture.png`.
  png, jpg, webp, gif, mp4, webm ; 4 au plus, 10 Mo chacune ; capture faite
  avec l'outil du projet (Playwright sur le site, capture de l'app…), et
  REGARDE-la avant de l'envoyer (Read sur l'image).
- **Photos, vidéos, fichiers de Raphaël** (joints à ses réponses dans l'app, 📎 dans le hook) : `scripts/cockpit-media.sh --message <id>` ou `--chantier <id>` les télécharge ; REGARDE-les (Read sur l'image) avant de répondre.
- **Demande d'un utilisateur du site : rejoue-la d'abord** (D-05) : le module
  embarqué joint à chaque demande et correction la page, l'appareil, la
  version servie, ses 20 dernières actions et les erreurs JavaScript.
  `scripts/cockpit-reproduction.sh --chantier <id>` l'affiche ; ouvre la page,
  refais les étapes, constate le problème AVANT de corriger (et rejoue après). Sans adresse à
  rouvrir, l'app propose « Copier le test synthétique » (le scénario écrit).
- **Le cycle** est une colonne `etat` : à trier → à cadrer → libre → en cours →
  à vérifier → validé (+ bloqué, reporté). **Seul un humain pose « validé »**
  (bouton « Ça fonctionne, je certifie » ; « Corriger » complète la demande sur
  la même ligne et rend le chantier). Plus aucun marqueur entre crochets.
- **Écrire dans le fil** : `insert into messages (projet_id, chantier_id, auteur, auteur_type, kind, corps)`
  (`kind` info / blocage). Avant de t'arrêter, écris où tu en es.
- **Ces commandes sont des lanceurs** (`scripts/cockpit-lanceur.sh`) : elles
  exécutent toujours la dernière version publiée sur Cockpit-General, sans
  réinstallation. Ne les modifie pas ici ; une évolution se fait dans
  Cockpit-General et arrive dans tous les projets branchés en 10 minutes.
- `scripts/cockpit-sql.sh` vise le schéma `cockpit` sans préfixe, une instruction par appel ;
  demande à Raphaël avant tout drop / delete massif / truncate.
**Consommation, règle GÉNÉRALE (Raphaël, 30 sept. 2026, migration 0034)** : « ne jamais atteindre la limite des modèles ». Les consignes de `chef.sh` / `renfort.sh` donnent le modèle de chaque agent (paramètre `model` de l'outil Agent) : `haiku` pour Revoir À toi, Point, Vérifier ; `sonnet` pour Répondre/Réponse et coder un chantier ; jamais `opus` sauf mention explicite de Raphaël. `create_session` (renforts, relais) : `model: "claude-sonnet-5-5"`. Frein : 2 agents par défaut (`chefs.max_agents`) ; si `get_session` → `rate_limit_info.status` n'est pas `allowed`, au plus 1 agent et aucune revue. Un élément de « À toi » confirmé ne revient pas avant 24 h (`a_toi_a_revoir`). **Bascule automatique (30 sept. 2026, migration 0037, chantier 29fac2e1)** : le NOMBRE d'agents ne pose pas problème, seuls les modèles : l'usage ne freine plus les agents, il descend les MODÈLES. `chef.sh --usage <status> --fenetre <rateLimitType> --reset <resetsAt>` (depuis `get_session` → `external_metadata.rate_limit_info`, qui n'a AUCUN pourcentage : seulement status, type de fenêtre, resetsAt) pose un palier 0 à 3 (`bascule_usage`, règle `palier_cible`, **migration 0045**, chantier a1a67b3d : « Haiku n'est pas assez puissant : dernière option ; plein gaz jusqu'à 50 %, puis répartir jusqu'à la fin de la fenêtre ») : 0 plein gaz (modèles et effort réglés), 1 effort d'un cran plus bas, 2 effort bas + modèle d'un cran plus léger sans passer sous Sonnet, 3 Haiku seulement (si autorisé) quand la limite est atteinte. Rythme = part écoulée de la fenêtre (5 h ou 7 j) + statut : avertissement tôt = palier 2, après le seuil = 1, dans les 10 % finaux = 0 (le crédit va être remis à zéro). Réglages par projet : `chefs.bascule_seuil_pct` (50) et `bascule_haiku` (oui), écran « Modèles et effort ». Monte tout de suite, redescend après 30 min de calme, expire à resetsAt ou après 3 h ; une session en pause `rate_limit` vaut palier 3. `modeles_effectifs` (une règle) est lue par `chef.sh` et `renfort.sh`. Interrupteur `chef.sh --bascule on|off` ou bouton de l'app. Le frein « 1 agent » reste un geste manuel seulement. `verifier-base` §32.
**Déploiement par lot (Raphaël, 5 oct. 2026, chantier 719e60e1)** : « ça consomme trop, le moindre correctif demande un redéploiement ». Accumule les correctifs d’une même vague dans UNE PR / UNE fusion, jamais une PR ou un redéploiement par correctif. Une fonction Supabase se déploie UNE fois en fin de lot (`deployer-fonction.sh`, qui ne renvoie rien si elle est inchangée ; `--force` sinon). Les pushes qui ne touchent ni `app/` ni `embed/` ne déclenchent plus Pages. Ne déclenche jamais un déploiement Render/Supabase/Pages à la main « pour voir ».


<!-- fin du bloc cockpit : brancher.sh remplace tout ce qui précède jusqu'au titre -->
