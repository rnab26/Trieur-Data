# PROJECT_LOG.md — Trieur de Data

Journal court de l'état des chantiers. Pas un historique complet des
échanges — juste : quoi, où ça en est, quoi ne pas casser, et les tâches
en attente.

---

## CRM / Base de données (Cockpit) — chantier en cours

**Quoi** : base de données persistante (comptes, organisations Leads/
Prélèvement/Global, traçabilité d'import, dédup par IBAN au niveau base
et non plus fichier par fichier, annotations) + Cockpit (onglet 5) où
utilisateur et Claude échangent des chantiers/demandes en continu,
même principe que le cockpit Jarvis.

**Décisions prises (2026-09-16)** :
- Infra : schéma Postgres dédié `trieur_data` appliqué sur le projet
  Supabase existant `jarvis-assistant` (partagé, isolé par schéma + RLS),
  plutôt qu'un projet Supabase séparé — pour rester gratuit (limite de 2
  projets free atteinte, l'utilisateur ne voulant pas mettre un projet en
  pause). Si un jour le partage gêne Jarvis, migration vers un projet 100%
  isolé possible (~25$/mois) — décision à reprendre alors avec
  l'utilisateur (argent).
- `auth.users` Supabase est donc partagé avec Jarvis (voulu : un même
  compte peut ouvrir les deux outils). Toutes les autres tables (profils,
  organisations, imports, dédup, cockpit) vivent uniquement dans
  `trieur_data`, jamais touché aux tables `public.*` de Jarvis.
- **La coque de base du Trieur (onglets 1 à 4) reste utilisable SANS
  compte**, exactement comme avant — demande explicite de l'utilisateur.
  Le login Supabase ne s'applique qu'à l'onglet 5 "Cockpit".
- Schéma SQL : `supabase/migrations/0001_init.sql` (organisations,
  profiles, memberships, import_batches, records (JSONB + IBAN normalisé
  généré), dedup_alerts (jamais de suppression auto, file de validation),
  annotations, chantiers, chantier_messages). RLS activé partout, filtrage
  par organisation.

**État** : migration appliquée sur Supabase (vérifié : 9 tables
`trieur_data.*` créées, RLS actif, rien cassé côté Jarvis — 31 tables
`public.*` intactes, advisors de sécurité ne remontent rien de nouveau).
Code app (`trieur/db.py`, `views/_auth.py`, `views/tab_cockpit.py`) écrit
et intégré. 89/89 tests passent (87 unitaires + 2 E2E Playwright,
vérifiés en conditions réelles avec navigateur headless).

**Bloquant avant mise en service réelle** (actions manuelles, aucun
chemin API disponible pour les faire à la place de l'utilisateur) :
1. [x] Ajouter `trieur_data` aux "Exposed schemas" du projet Supabase
   (Project Settings → API) — fait par l'utilisateur 2026-09-16, vérifié
   par requête REST réelle (passage de "schéma non exposé" à une erreur
   de droits normale, signe que le schéma est bien exposé).
2. [x] Coller les 2 clés Supabase (URL + clé anon, non sensibles) dans les
   Secrets de l'app sur Streamlit Cloud — fait par l'utilisateur.
3. [x] Compte utilisateur (`r.nabet26@gmail.com`, déjà existant côté
   Jarvis, `auth.users` partagé) : profil `trieur_data` créé en
   super-admin + membre `org_admin` des 3 organisations — même mot de
   passe que Jarvis, rien à reconfigurer côté utilisateur. Compte du père :
   en attente de son email (l'utilisateur a dit "pas encore").

**⚠️ Piège rencontré (2026-09-16)** : le Cockpit avait été développé et
testé sur la branche du chantier, jamais mergé sur `main` — donc jamais
déployé (Streamlit Cloud déploie uniquement `main`). L'utilisateur a
d'abord testé en conditions réelles ("fait") avant que le merge n'ait
lieu, ce qui a fait perdre un aller-retour. **Leçon : sur ce projet, un
chantier de code n'est réellement "prêt à tester par l'utilisateur" que
merge sur `main` inclus — ne jamais dire "teste maintenant" avant le
merge.** Mergé sur `main` le 2026-09-16 (branche gardée, non supprimée).

**Régression évitée** : l'import de la librairie `supabase` au niveau
module ralentissait le démarrage de toute l'app (mesuré : a rendu le
test E2E `test_master_columns_localstorage_fallback` flaky, y compris
en dehors de ce chantier — confirmé en reproduisant le même flake sur
`main` sans aucun changement, donc préexistant, pas causé par ce
chantier). Corrigé quand même par prudence : import de `supabase`
repoussé à l'intérieur de `get_client()` (chargé seulement si quelqu'un
ouvre réellement le Cockpit), les onglets 1 à 4 gardent leur poids
d'origine.

**Notes / À faire** :
- [ ] `tests/test_e2e_smoke.py::test_master_columns_localstorage_fallback`
  est flaky de façon préexistante (délai fixe de 4s parfois trop court,
  indépendamment de ce chantier) — reproduit ~1 fois sur 4 sur `main`
  avant tout changement lié au Cockpit. À fiabiliser un jour (attendre une
  condition réelle plutôt qu'un délai fixe) mais hors périmètre de ce
  chantier.
- [x] Login Cockpit vérifié en conditions réelles par l'utilisateur
  (navigateur mobile, 2026-09-16) : connexion avec `r.nabet26@gmail.com`
  OK, sélecteur d'environnement (Leads/Prélèvement/Global) fonctionnel,
  état vide correct. **Chaîne complète validée de bout en bout.**
- [ ] Quand l'utilisateur donne l'email du père : créer son compte
  (Admin API Supabase, `SUPABASE_SERVICE_ROLE_KEY` déjà valide pour le
  projet `jarvis-assistant`) + profil + membership Prélèvement (role
  `member`, pas admin).

**2026-09-16 (suite) — Environnements personnalisés (Prélèvement)** :
- Décision posée avec l'utilisateur : **un seul Cockpit**, chantiers
  attribués par organisation via `org_id` (pas un cockpit par activité —
  éviterait une source de vérité dupliquée).
- Migration `0002_org_settings_and_dedup.sql` : colonne
  `organizations.master_columns` (jsonb, propre à chaque environnement,
  remplace le fichier JSON global partagé pour ce qui passe par le
  Cockpit) + fonction SQL `find_iban_matches` (historique complet, pas
  juste le fichier du jour).
- Cockpit → nouvel onglet "Import & Dédup base" par environnement :
  édition des colonnes maîtres de l'org, import CSV/Excel avec
  vérification IBAN contre tout l'historique en base, file d'alertes de
  doublon à résoudre à la main (jamais de suppression auto). Répond
  directement au cas d'origine (Rachel Daniel / Daniel Rachel, même IBAN,
  1 mois d'écart).
- ⚠️ Piège évité : `st.dataframe(..., width="stretch")` aurait reproduit
  le crash de production déjà documenté dans
  `tests/test_e2e_smoke.py` (incompatible avec Streamlit 1.61.1) —
  utilisé `use_container_width=True` à la place.
- 89/89 tests passent. Mergé sur `main`.
- [ ] **Pas encore testé en conditions réelles par l'utilisateur** (import
  d'un vrai fichier Prélèvement, vérifier qu'une alerte de doublon
  apparaît bien) — à faire avant de considérer ce chantier terminé.
- [ ] Les colonnes maîtres de l'onglet 1 (mode anonyme, fichier JSON)
  restent complètement séparées de celles de l'org en base (Cockpit) —
  décision volontaire pour ne pas toucher à la coque de base, mais à
  clarifier avec l'utilisateur si ça crée de la confusion à l'usage.
- [ ] Brancher la détection de doublons par IBAN normalisé (déjà en base,
  colonne générée `records.iban_normalized`) sur le flux d'import
  existant (onglet 2) : à chaque construction de base, vérifier contre
  l'historique complet en base, pas juste le fichier du jour — alerte,
  jamais de suppression automatique.
- [ ] Migrer progressivement l'historique d'import (actuellement en
  session Streamlit uniquement, perdu à la fermeture) vers
  `trieur_data.import_batches` / `records`.
- [ ] Décider avec l'utilisateur du contenu précis de l'onglet "colonnes
  maîtres" par organisation (custom Leads vs Prélèvement) une fois le
  socle DB en service — pas encore cadré.

---

## Import & Mapping (onglet 2)

**Quoi** : import Excel/CSV/PDF SEPA/Google Sheets, auto-assignation vers
les colonnes maîtres, mémoire du mapping par forme de fichier (empreinte
des noms de colonnes), nettoyage + vérification checksum IBAN (mod 97).

**État** : fonctionnel et testé.

**Ne pas casser** :
- Détection téléphone/IBAN par CONTENU (pas seulement par nom de
  colonne) — permet de reconnaître une colonne mal nommée.
- Désambiguïsation des noms de fichiers identiques dans un même import.
- Le mapping mémorisé doit toujours avertir si une colonne référencée
  n'existe plus dans les colonnes maîtres actuelles.
- Le composant `views/_ls_sync.py` renvoie `None` tant qu'il n'a pas
  reçu la réponse JS (comportement normal des composants Streamlit à
  double sens) — ne pas le remplacer par un mécanisme qui suppose une
  réponse synchrone.

**Notes / À faire** :
- [x] Idée reportée par l'utilisateur : vraie base de données persistante
  (ex. Supabase) avec comptes utilisateurs + compte maître voyant tout,
  et une sélection du "type de base"/métier avant import (prospection
  téléphonique vs IBAN, etc. — la structure de la base doit s'adapter).
  Gros chantier, à cadrer avant de commencer. → Cadré et démarré
  2026-09-16, voir nouveau chantier "CRM / Base de données (Cockpit)"
  ci-dessous.
- [x] Signalé par l'utilisateur (2026-09-06) : ses colonnes maîtres se
  réinitialisent au démarrage d'un tri. Cause : `user_master_columns.json`
  est stocké côté serveur et remis à zéro à chaque redémarrage du
  conteneur Streamlit Cloud (voir chantier Infra). Corrigé : composant
  statique léger (`components/ls_master_columns/`, `views/_ls_sync.py`)
  qui duplique les colonnes maîtres dans le `localStorage` du navigateur
  et les restaure automatiquement si le fichier serveur revient aux
  valeurs par défaut — aucune action de l'utilisateur requise. Verrouillé
  par un test E2E (`test_master_columns_localstorage_fallback`).

---

## Filtrage & Dédoublonnage (onglet 3)

**Quoi** : filtre multi-critères (groupes combinés en OU, critères d'un
même groupe combinés en ET), dédup par groupe de doublons avec choix de
la ligne à garder (au-delà de 50 groupes, bascule automatique sur une
règle globale première/plus complète), filtres enregistrés (fichier
serveur + code texte copier/coller portable).

**État** : fonctionnel, testé (unitaire + E2E).

**Ne pas casser** :
- Un groupe de filtre incomplet (valeurs pas encore choisies) ne doit
  jamais filtrer le résultat à zéro.
- Avertir si un filtre enregistré référence une colonne qui n'existe
  plus.
- Les lignes SANS valeur sur la colonne de dédup ne doivent jamais être
  traitées comme doublons entre elles (bug déjà corrigé une fois).

**Notes / À faire** :
- [ ] Revoir si le "groupe OU" est vraiment utilisé au quotidien ;
  simplifier l'interface (ne garder que l'ET) si non.
- [ ] Dédup floue (nom + CP proches) : idée mise de côté volontairement
  (risque de faux positifs / perte de données réelles) — ne pas
  implémenter sans validation explicite des seuils avec l'utilisateur.

---

## Export (onglet 4)

**Quoi** : ordre/sélection des colonnes par glisser-déposer
(`streamlit-sortables`), presets d'export nommés, export CSV/Excel.

**État** : fonctionnel.

**Ne pas casser** :
- ⚠️ **CRITIQUE** : le widget de glisser-déposer ne calcule sa hauteur
  correctement QUE si les 4 onglets sont rendus via `st.tabs()` natif
  (qui garde tous les onglets montés dans le DOM, juste masqués). Une
  barre d'onglets "maison" (rendu conditionnel) a déjà cassé ce widget
  une fois (invisible, iframe à hauteur 0) — régression réelle survenue
  en prod, corrigée. `tests/test_e2e_smoke.py` verrouille maintenant ce
  point (hauteur d'iframe non nulle) : ne jamais le retirer/affaiblir
  sans re-vérifier ce widget à la main.

**Notes / À faire** : (rien en attente)

---

## Design / Navigation

**Quoi** : logo (`assets/logo.png`, favicon + en-tête), titre "Trieur de
Data", boutons "étape suivante" entre onglets (clic JS côté client sur
l'onglet natif via `views/_nav.py` — piloter `st.tabs()` depuis le code
Python est impossible techniquement).

**État** : thème "épuré façon Apple" (validé). Le thème "Feutré élégant"
a été essayé (fond gris-bleu, titres serif) puis rejeté par l'utilisateur
(contraste texte/couleurs pas apprécié) — ne pas le réintroduire sans
validation explicite (montrer une maquette/artifact avant d'intégrer).

**Ne pas casser** :
- Le sélecteur `[data-testid="stTab"]` utilisé par `views/_nav.py` pour
  cliquer l'onglet natif — fragile aux montées de version Streamlit
  (l'ancien sélecteur `data-baseweb="tab"` ne fonctionnait déjà plus sur
  Streamlit 1.61). Revalider ce sélecteur si Streamlit est mis à jour.
- `st.tabs()` natif doit rester en place (voir chantier Export).

**Notes / À faire** :
- [ ] Rien en attente côté design pour l'instant après le rejet de
  "Feutré élégant" — attendre une nouvelle demande avant de proposer une
  autre piste.

---

## Infra / Tests / CI

**Quoi** : CI GitHub Actions (`pytest` + Playwright E2E), déploiement
Streamlit Cloud (auto sur push vers `main`).

**État** : 88 tests (unitaires + 1 E2E complet couvrant tout le
pipeline). La CI a connu une panne côté plateforme GitHub Actions
(résolue depuis, sans lien avec le code du repo).

**Ne pas casser** :
- Le workflow CI doit lancer `python -m pytest` (pas `pytest` seul), sinon
  `trieur/` n'est pas importable (déjà cassé une fois pour cette raison).
- Les fichiers de config (`user_master_columns.json`, `saved_filters.json`,
  `export_presets.json`, `remembered_mappings.json`) sont stockés côté
  serveur, `.gitignore`és — PAS persistants à travers un redémarrage de
  conteneur Streamlit Cloud. Ce n'est pas une vraie base de données.

**Notes / À faire** :
- [ ] Intégrer dans la suite automatique permanente les scénarios
  vérifiés à la main lors des dernières fonctionnalités (dédup par
  groupe, filtres multi-critères, sauvegarde texte des filtres) pour
  qu'une future modif ne les casse pas silencieusement.

---

## Doc / Suivi (CLAUDE.md, PROJECT_LOG.md)

**Quoi** : ce fichier et `CLAUDE.md`, poussés directement sur `main`
(exception explicite à la regle de branche — voir `CLAUDE.md`).

**État** : mis en place. Politique d'exécution autonome précisée le
2026-08-10 : une tâche confirmée une fois s'exécute de bout en bout
(commit/push/merge/déploiement inclus) sans redemander à chaque étape —
voir `CLAUDE.md` section "Exécution autonome".

**Notes / À faire** : (rien en attente)
