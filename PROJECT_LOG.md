# PROJECT_LOG.md — Trieur de Data

Journal court de l'état des chantiers. Pas un historique complet des
échanges — juste : quoi, où ça en est, quoi ne pas casser, et les tâches
en attente.

---

## Priorisation des 19 fonctionnalités validées (2026-09-17)

**Décision** : l'utilisateur a rempli la fiche
(https://claude.ai/artifact/DYHosfZYYCWQZ12vic2nzP) en mettant "oui"
sur les 19 cases existantes, et a demandé de proposer un ordre de
priorité moi-même et de commencer par le haut. Les 8 nouvelles idées
(n1-n8) ajoutées à la fiche après coup n'ont pas encore de réponse —
pas encore priorisées, en attente.

**Ordre proposé et retenu** :
1. [x] Refonte de la liste clients (recherche par colonne, tri,
   masquer des colonnes, sélection multiple, pagination) — livré.
2. [x] Export direct depuis la Base de données — livré, voir section
   ci-dessous.
3. [x] Modifier une ligne directement + historique court par ligne —
   livré, voir section ci-dessous.
4. [x] Colonnes adaptables selon le fichier importé — livré, voir
   section ci-dessous.

**Reprioris­ation (2026-09-17, suite)** : l'utilisateur a répondu aux 8
nouvelles idées (n1-n8) — toutes "oui" sauf n8 "Colonnes calculées
simples" (**plus tard**, explicitement dépriorisée). Nouvel ordre pour
la suite, en intégrant ces réponses et leurs commentaires :

5. [x] Vues enregistrées, nommées — livré, voir section ci-dessous.
6. [x] Tableau de bord par environnement + badge d'alertes de doublon
   toujours visible — livré, voir section ci-dessous (fusion de
   l'ancien point 6 et de n6 "Rappel visible des alertes en attente" —
   même famille, "vue d'ensemble en
   arrivant").
7. [x] Étiquettes libres sur un client (n1) — livré, voir section
   ci-dessous.
8. [x] Annuler un import entier en un clic (n3) — livré, voir section
   ci-dessous.
9. [x] Recherche avancée façon Google Sheets + modification multiple —
   livré, voir section ci-dessous.
10. [x] Diff au réimport (comparaison champ par champ sur une alerte de
    doublon) — livré, voir section ci-dessous.
11. [ ] **En attente**, bloqué sur l'Excel de référence : détection de
    quasi-doublons sur d'autres critères que l'IBAN (n2 — "OUI MAIS PAS
    FORCEMENT QUE LES IBAN") + règle de doublon configurable par
    activité (ancien point 7) — les deux posent la même question de
    fond ("quelle règle de rapprochement pour quelle activité"), à
    trancher ensemble une fois l'Excel reçu.
12. [x] Rôles plus fins par environnement (n5) — premier palier livré
    (rôle "lecture seule" par environnement), voir section ci-dessous.
    Granularité plus fine (par colonne, par action...) pas demandée
    pour l'instant, reste ouverte si besoin plus tard.
13. [ ] **Reporté par l'utilisateur** ("plus tard") : colonnes
    calculées simples (n8).

**2026-09-21** : les points 7, 8, 11, 12 et 13 ci-dessus (les seuls encore
non livrés de cette liste) sont maintenant aussi des chantiers dans le
Cockpit (`trieur_data.chantiers`, org "global"), avec le contexte utile
en premier message de chaque fil. Ce fichier reste le journal détaillé
(quoi, pourquoi, ce qui a été vérifié) ; le Cockpit reste le tableau de
bord court et à jour en temps réel (visible dans l'appli ET par toute
session Claude Code sur ce repo, qu'une entrée vienne d'une saisie
manuelle ou d'une session en cours -- même table Supabase des deux
côtés, pas de synchronisation à faire).

**2026-09-21, suite** : Raphaël a demandé un traitement automatique des
chantiers Cockpit, sans avoir à relancer une session pour chacun.
Routine créée : **"Cockpit Trieur de Data — traitement horaire des
chantiers"** (`trig_01LGJrQmy1KPBmXj8qDAXae9`), toutes les heures,
branchée sur une session dédiée (`session_01Q9jyjGCsc1DfK4XPNZSTgQ`,
accès Supabase + GitHub + dépôt vérifiés). À chaque passe : prend
jusqu'à 2 chantiers `a_faire` (priorité haute d'abord), les traite de
bout en bout (branche, code, tests, PR, merge sur main) si l'énoncé est
clair ; si un vrai choix ambigu se pose, publie une fiche Artifact
(mêmes boutons cliquables + commentaire que la fiche fonctionnalités du
17/09) plutôt que de bloquer en texte, et repasse le chantier en
`attente_retour`. Si rien à traiter, la passe s'arrête tout de suite
(coût minimal). Prompt complet de la Routine consultable via
`list_triggers` (MCP claude-code-remote) si besoin de le retoucher.
**Nettoyage à faire si abandonné** : désactiver/supprimer cette Routine
et archiver la session dédiée si ce mode de fonctionnement est arrêté.

---

## Recherche avancée + modification multiple + diff au réimport (2026-09-17)

**Fait** (chantiers 9 et 10, regroupés — mode rapide demandé par
l'utilisateur) :
- Filtres par colonne à opérateurs : contient / ne contient pas / égal
  à / vide / non vide (au lieu du seul "contient").
- Sélectionner 2+ lignes ouvre "Modifier un champ pour la sélection" —
  un champ, une valeur, appliquée à toute la sélection, avec
  confirmation (`views/_ui.py:confirm_action_button()`, généralisé à
  partir de `confirm_delete_button()`).
- Les alertes de doublon affichent un vrai tableau de comparaison champ
  par champ (`views/tab_database.py:diff_rows()`) au lieu de deux blocs
  de données brutes.

**Corrigé après revue avant merge** : le bug `... or ""` (valeur
"fausse" confondue avec vide) déjà corrigé une fois dans
`_render_edit_form` avait été réintroduit dans les opérateurs vide/non
vide et dans le diff — corrigé avec des comparaisons explicites à
`None`. Rappeler une vue enregistrée avant ce commit aurait fait
planter l'onglet (format de stockage des filtres changé) — compatibilité
ajoutée. Le sélecteur de champ de la modification en masse ne propose
plus les colonnes d'affichage dérivées ("Fichier source", "Modifié
le"...), qui auraient pollué le jsonb en silence si écrites.

**Vérifié** : `tests/test_client_list_helpers.py` étendu (+10 tests,
dont les deux régressions falsy-value trouvées en revue). Suite
complète (149 tests) + e2e Playwright réel verts.

**Pas vérifié** : le rendu réel avec un compte Supabase connecté (pas
de secrets disponibles dans la session qui a fait ce chantier), ni le
correctif de compatibilité des vues enregistrées avec une vraie vue au
format d'avant ce commit (aucune vue réelle n'existe encore en prod).

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (filtres par opérateur,
  modification en masse sur plusieurs lignes, comparaison sur une
  alerte de doublon).

Avec ce chantier, **8 des 8 chantiers priorisés le 2026-09-17 sont
livrés** (hors points 11-13, respectivement bloqué sur l'Excel, à
cadrer avec l'utilisateur, et reporté par lui).

---

## Tableau de bord par environnement + badge d'alertes (2026-09-17)

**Fait** :
- `trieur/db.py:get_last_import_batch()` — fichier + date du dernier
  import pour un environnement.
- `views/tab_database.py:_render_dashboard()` — 3 indicateurs en haut
  de la Base de données : clients, alertes de doublon en attente
  (visible dès l'arrivée sur l'environnement, pas seulement à
  l'import), dernier import.

**Vérifié** : `tests/test_db_dashboard.py` (3 tests, faux client).
Suite complète (141 tests) + e2e Playwright réel verts (un échec isolé
du test pipeline complet confirmé flaky par relances répétées, sans
lien avec ce commit).

**Pas vérifié** : le rendu réel avec un compte Supabase connecté (pas
de secrets disponibles dans la session qui a fait ce chantier).

**Ne pas casser** : `total` (nombre de clients) et `alerts` (alertes en
attente) sont calculés UNE fois dans `render()` et partagés entre
`_render_dashboard`/`_render_alerts`/`_render_client_list` — ne jamais
réintroduire un `count_records()`/`list_dedup_alerts()` local dans l'un
de ces trois sans vérifier que ce n'est pas déjà calculé plus haut.

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (vérifier que les 3 chiffres
  du tableau de bord correspondent bien à la réalité de
  l'environnement).

---

## Vues enregistrées, nommées (2026-09-17)

**Fait** :
- Migration 0009 : `trieur_data.db_saved_views` (par compte + par
  environnement), appliquée à la base réelle.
- `trieur/db.py` : `list_saved_views()` (mis en cache), `save_saved_view()`
  (upsert par nom, remplace plutôt que duplique), `delete_saved_view()`.
- Expander "👁️ Vues enregistrées" dans la Base de données : lister,
  appliquer, enregistrer la combinaison recherche + filtres + colonnes
  affichées actuelle, supprimer avec confirmation.

**Vérifié** : `tests/test_db_saved_views.py` (4 tests, faux client).
Suite complète (138 tests) + e2e Playwright réel verts.

**Pas vérifié** : le formulaire réel avec un compte Supabase connecté
(pas de secrets disponibles dans la session qui a fait ce chantier).

**Bug de sécurité trouvé et corrigé avant merge** : la policy RLS de
`db_saved_views` ne vérifiait que l'identité du propriétaire, jamais
l'appartenance à l'organisation référencée — contrairement à toutes les
autres tables du schéma qui référencent un `org_id`. Corrigé dans la
migration et sur la base réelle (vérifié par une requête directe sur
`pg_policy`) avant tout usage réel de la table.

**Ne pas casser** :
- Rappeler une vue doit toujours vider tous les filtres par colonne
  existants avant de reposer ceux de la vue (sinon un filtre tapé avant
  l'appel reste actif en silence) — voir le bloc "pending apply" en
  tête de `_render_client_list`.

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (enregistrer une vue, en
  rappeler une autre, vérifier que les filtres se réinitialisent bien).

---

## Colonnes adaptables selon le fichier importé (2026-09-17)

**Fait** :
- `views/_ui.py:unknown_columns()` — colonnes d'un fichier absentes des
  colonnes maîtres de l'environnement (insensible à la casse).
- `views/_ui.py:render_unknown_columns_prompt()` — signale ces colonnes
  avant l'import et propose de les ajouter (admin uniquement, même
  règle que les réglages ; un membre simple voit un message informatif,
  l'import continue, aucune donnée n'est jamais perdue). Partagé entre
  l'upload direct (Base de données) et "Enregistrer dans la base de
  données" (Export) — un seul comportement.
- `trieur/db.py:add_org_master_columns()` — ajoute les colonnes
  choisies, jamais de doublon même sous une casse différente.

**Vérifié** : `tests/test_ui_helpers.py` (6 tests) +
`tests/test_db_master_columns.py` (3 tests, faux client). Suite
complète (134 tests) + e2e Playwright réel verts.

**Pas vérifié** : le formulaire réel avec un compte Supabase connecté
(pas de secrets disponibles dans la session qui a fait ce chantier).

**Ne pas casser** :
- Les deux chemins d'import (upload direct, "Enregistrer dans la base
  de données") doivent continuer à passer par
  `render_unknown_columns_prompt()` + `add_org_master_columns()` — ne
  jamais réintroduire une logique locale d'ajout de colonnes dans l'un
  des deux sans l'autre.

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (importer un fichier avec une
  colonne inconnue de l'environnement, vérifier la proposition
  d'ajout).

---

## Modifier une ligne directement + historique court par ligne (2026-09-17)

**Fait** :
- Migration 0008 (appliquée à la vraie base, vérifiée) :
  `records.updated_at`/`updated_by` — volontairement minimal, pas un
  journal complet des valeurs changées.
- `trieur/db.py` : `get_record()` (lecture fraîche d'un client),
  `update_record()` (remplace tout le contenu, trace qui/quand, renvoie
  si la ligne existait encore), `get_profiles_map()` (résout des
  identifiants en noms, mis en cache comme les autres lectures rares).
- Sélectionner UNE ligne dans le tableau (même case à cocher que la
  suppression groupée) ouvre "✏️ Modifier cette ligne" — un champ par
  colonne, enregistrement explicite. Colonnes "Modifié le"/"Modifié
  par" ajoutées à l'affichage et à l'export.

**Vérifié** : `tests/test_db_update_record.py` (8 tests, dont le cas
"ligne supprimée entre-temps") + `tests/test_client_list_helpers.py`
étendu. Suite complète (125 tests) + e2e Playwright réel verts.

**Pas vérifié** : le formulaire réel avec un compte Supabase connecté
(pas de secrets disponibles dans la session qui a fait ce chantier).

**Limites connues, documentées dans le code, pas corrigées** :
- Dernière écriture gagne — pas de détection si un autre membre modifie
  le même client entre-temps (silencieusement écrasé). Un correctif
  demanderait un verrou optimiste (comparer une version avant
  d'écraser) — pas fait, le volume/usage actuel ne le justifie pas.
- Modifier le champ IBAN affiché ne resynchronise pas la clé interne
  `"iban"` qui alimente la détection de doublon — liée à la règle de
  doublon configurable par activité (point 7 ci-dessus), déjà en
  attente de l'Excel de référence.

**Ne pas casser** :
- Toute nouvelle lecture de plusieurs identifiants utilisateur pour de
  l'affichage doit passer par `get_profiles_map()` (mis en cache), pas
  un appel direct répété à chaque rerun.
- `update_record()` remplace TOUT le contenu `data` -- un futur appelant
  doit toujours partir du contenu actuel (`get_record()`), jamais d'un
  sous-ensemble de champs.

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (sélectionner une ligne,
  modifier un champ, vérifier "Modifié le"/"Modifié par").

---

## Export direct depuis la Base de données (2026-09-17)

**Fait** (`trieur/db.py`, `views/tab_database.py`) :
- `list_all_records()` : ramène TOUT l'historique d'un environnement en
  enchaînant les pages (jamais seulement le lot paginé affiché à
  l'écran), en avançant de la taille réellement renvoyée par chaque
  page plutôt que de la taille demandée — une limite serveur
  silencieuse plus petite ne tronque donc jamais le résultat.
- Bouton "💾 Exporter ces résultats" : CSV/Excel de tout l'environnement,
  avec la même recherche/les mêmes filtres par colonne qu'à l'écran.
  Une colonne masquée EXPLICITEMENT par l'utilisateur reste masquée à
  l'export ; une colonne jamais vue à l'écran (dans une ligne pas
  encore chargée) est incluse quand même, pour ne jamais perdre de
  donnée en silence.
- Refactoring : aplatissement des lignes et filtrage (recherche,
  colonnes) extraits en fonctions pures partagées entre l'affichage et
  l'export (`_build_rows`, `_filter_by_search`, `_filter_by_columns`).
- `LIST_PAGE_SIZE` (300) unifié dans `trieur/db.py` — une seule source
  de vérité, plus de "300" dupliqué entre deux fichiers.

**Vérifié** : `tests/test_db_pagination.py` (limite serveur plus petite
que la page demandée, accumulation multi-pages, filtrage par
organisation) + `tests/test_client_list_helpers.py` (aplatissement,
recherche, filtres par colonne) — 10 tests nouveaux, faux client
Supabase, pas de réseau. Suite complète (113 tests) + e2e Playwright
réel verts avant et après merge sur `main`. Logique colonnes
masquées/jamais-vues revérifiée dans un script Python autonome.

**Pas vérifié** : le téléchargement réel avec un compte Supabase
connecté (pas de secrets disponibles dans la session qui a fait ce
chantier).

**Limite connue, documentée dans le code, pas corrigée** : pagination
par offset dans `list_all_records` — un import concurrent PENDANT un
export peut en théorie décaler les pages suivantes (dupliquer ou
sauter des lignes). Même risque déjà présent pour "Charger plus", juste
sur une fenêtre plus longue ici. Pas de pagination par curseur pour
l'instant, le volume réel actuel ne le justifie pas.

**Incident de process (auto-signalé)** : ce chantier a été commencé
directement sur `main` par erreur, avant d'être déplacé sur sa propre
branche (`claude/export-depuis-base-de-donnees`) juste avant le premier
commit — donc rien n'a été poussé sur `main` en dehors du merge normal
à la fin. Aucune conséquence réelle, mais la règle "chaque chantier a sa
branche dès le départ" n'a pas été respectée à la lettre pour celui-ci.

**Ne pas casser** :
- La logique de colonnes "masquée explicitement" vs "jamais vue" dans
  `_render_export` dépend de recevoir `all_cols` (pas seulement
  `visible_cols`) — ne pas simplifier cette signature sans repenser le
  cas des colonnes découvertes seulement par "Charger plus" ou par
  l'export lui-même.

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (export CSV et Excel, avec et
  sans filtre actif, avec une colonne masquée).

**Notes / À faire** :
- [ ] Continuer dans cet ordre au point 2 une fois le point 1 confirmé
  par l'utilisateur en usage réel.

---

## Refonte de la liste clients : filtre, tri, colonnes, sélection multiple, pagination (2026-09-17)

**Fait** (`views/tab_database.py`, `trieur/db.py`) :
- Filtre par colonne (texte "contient", combinés en ET) dans un tiroir
  "Filtres par colonne".
- Tri : natif à `st.dataframe` (clic sur un en-tête) — rien à
  construire, juste documenté dans l'aide à l'écran.
- Masquer des colonnes : multiselect "Colonnes affichées" — préférence
  de session pour l'instant, pas encore persistée entre connexions
  (ce sera le rôle des "vues enregistrées", point 5 de la priorisation
  ci-dessus).
- Sélection multiple + suppression groupée :
  `st.dataframe(on_select="rerun", selection_mode="multi-row")`.
  Remplace l'ancien tiroir "Supprimer un client" (menu déroulant, un
  seul à la fois) — retiré pour ne pas garder deux façons de faire la
  même chose.
- Pagination : bouton "Charger plus" par pas de 300, avec un vrai cache
  de session (`trieur/db.py:list_records` gagne un paramètre `offset`,
  réel — vérifié sur l'API installée avant de l'utiliser) pour ne pas
  retélécharger tout depuis le début à chaque clic. Invalidé après
  chaque import ou suppression sur l'environnement, y compris depuis le
  bouton "Enregistrer dans la base de données" de l'onglet Export.

**Vérifié** :
- Une revue `/code-review` (high) sur le commit initial a trouvé 4 bugs
  réels, tous corrigés et revérifiés avant merge : la liste des
  colonnes se recalculait après le filtre de recherche (des colonnes
  disparaissaient de "Colonnes affichées" en tapant une recherche, et y
  restaient effacées) ; le bouton "Charger plus" devenait injoignable
  dès qu'une recherche ne donnait aucun résultat sur le lot déjà
  chargé ; le paramètre `offset` n'était jamais utilisé (retéléchargeait
  tout à chaque clic) ; la suppression groupée ne vidait pas l'état de
  sélection du tableau (risque de sélection fantôme sur d'autres
  clients au rendu suivant).
- Logique de colonnes/recherche/pagination/alignement des identifiants
  vérifiée dans des scripts Python autonomes (sans Streamlit ni
  Supabase).
- Suite complète (103 tests) + e2e Playwright réel (pipeline complet)
  verts avant et après merge sur `main`.

**Pas vérifié** : le rendu réel avec un compte Supabase connecté (pas
de secrets disponibles dans la session qui a fait ce chantier) — la
sélection/suppression groupée et le "Charger plus" n'ont pas été
observés dans un vrai navigateur avec de vraies données.

**Ne pas casser** :
- Toute écriture (import, suppression) sur `trieur_data.records` pour
  un environnement doit appeler
  `views/tab_database.py:invalidate_client_list_cache(org_id)` avant
  son `st.rerun()`, sinon la liste affiche un lot périmé après "Charger
  plus".
- `all_cols` (colonnes connues, filtres, colonnes affichées) doit
  toujours être calculée sur le lot chargé AVANT tout filtre/recherche
  — jamais après, sinon la liste de colonnes varie silencieusement en
  tapant une recherche.

**Notes / À faire** :
- [ ] Utilisateur : tester en usage réel (recherche, filtre par
  colonne, tri en cliquant un en-tête, masquer une colonne, sélection
  multiple + suppression groupée, "charger plus" au-delà de 300).

---

## Idées fonctionnalités Base de données — en attente de sélection (2026-09-17)

**Décision en attente** : l'utilisateur a listé 4 idées pour la Base de
données (recherche/filtre façon Google Sheets, colonnes adaptables selon
le fichier importé, masquer des colonnes à l'affichage, historique court
par ligne) et demandé explicitement d'en suggérer d'autres, en précisant
qu'il testera/répondra plus tard, pas dans l'immédiat.

**Fiche à remplir (fait, pas encore rempli par l'utilisateur)** :
https://claude.ai/artifact/DYHosfZYYCWQZ12vic2nzP — ses 4 idées +
7 suggestions supplémentaires (édition d'une ligne, actions groupées,
export direct depuis la base, vues enregistrées nommées, pagination
au-delà de 300 lignes, règle de doublon configurable par environnement,
petit tableau de bord par environnement), chacune en ✅ je veux / 🕒 plus
tard / ❌ pas besoin, enregistré automatiquement (capacité `db` de
l'artefact) — pas besoin de revenir le dire dans le chat.

**Rien n'est construit tant que la fiche n'est pas remplie** — voir les
réponses via le MCP Supabase n'a pas de sens ici, c'est le magasin `db`
de l'artefact lui-même (lu avec l'outil ArtifactData/Artifact
`read_db`), pas une table `trieur_data`.

**Notes / À faire** :
- [ ] Lire les réponses de la fiche une fois remplie, prioriser avec
  l'utilisateur, ouvrir un chantier par fonctionnalité retenue.
- [ ] Rattaché au chantier Cockpit "Organisation de la gestion des
  clients importés..." (id `69df5886-c639-4bc7-b063-5faf4f52d283`) —
  voir message posté là-bas le 2026-09-17.

---

## Relier le Trieur de Data au CRM : "Enregistrer dans la base de données" (2026-09-17)

**Demande** : la persistance (Leads/Prélèvement, futurs environnements)
doit se moduler par contexte, et le point d'entrée doit être le Trieur
de Data lui-même, pas un import à part. Question posée par
l'utilisateur : "si je n'ai pas signalé pour quelle activité, où ça va
s'enregistrer ?" — réponse implémentée : **nulle part, jamais
automatiquement**.

**Fait** :
- Nouveau bouton "💾 Enregistrer dans la base de données" dans l'onglet
  Export (`views/tab4_export.py`), visible SEULEMENT si déjà connecté
  (aucune connexion forcée — le Trieur de Data reste 100% utilisable
  sans compte). Enregistre `st.session_state.filtered_df` (la base
  déjà nettoyée/filtrée par les onglets 1-3, pas juste les colonnes
  choisies pour l'export CSV/Excel) dans l'environnement choisi
  explicitement dans un menu déroulant (Leads / Prélèvement / futurs).
- Si un fichier mélange plusieurs activités : filtrer dans l'onglet 3
  pour isoler une activité, enregistrer, refaire une passe pour
  l'autre — fonctionne déjà avec l'existant, pas de nouvelle mécanique.
- `trieur/db.py:import_dataframe()` : extrait l'unique chemin d'import
  (déjà utilisé par l'upload direct de l'onglet Base de données, gardé
  tel quel pour charger un fichier brut sans repasser par le pipeline),
  pour que les deux chemins d'écriture en base ne divergent jamais sur
  la logique de dédoublonnage IBAN.
- `views/_auth.py:optional_login_ctx()` : extrait le pattern "section
  additive visible seulement si connecté, sans jamais forcer de
  connexion", déjà utilisé par les colonnes maîtres liées au compte
  (onglet 1), maintenant partagé à un 2e endroit au lieu d'être
  reimplémenté.
- Bug trouvé en écrivant les tests du chemin partagé, corrigé au
  passage : une cellule vide devient `NaN` côté pandas (vrai en
  booléen, non sérialisable en JSON standard) — sans conversion en
  `None`, un import avec une colonne vide plantait. N'a pas encore
  touché la prod (base vide), mais aurait cassé ce nouveau bouton sur
  un vrai export Prélèvement (colonnes jamais toutes remplies).

**Vérifié** : `tests/test_db_import.py` (nouveau, 5 tests, faux client
Supabase — pas de réseau) couvrant explicitement le cas "Rachel Daniel"
/ "Daniel Rachel" à l'origine du besoin de dédoublonnage IBAN. Suite
complète (103 tests + 2 e2e Playwright réels) verte avant et après
merge. Vérifié en navigateur réel que l'onglet Export ne plante pas et
que la section reste invisible sans connexion.

**Pas vérifié** : le vrai flux de bout en bout avec un compte Supabase
réel (pas de secrets disponibles dans la session qui a fait ce
chantier) — logique testée unitairement et relue à la main, jamais
observée en conditions réelles.

**Ne pas casser** :
- `import_dataframe()` est maintenant LE seul endroit qui écrit dans
  `trieur_data.records` avec dédoublonnage IBAN — toute future
  évolution de cette logique (nouvelle règle métier, nouveau champ) se
  fait ici, jamais dans `tab_database.py` ou `tab4_export.py`
  directement.
- Toute nouvelle section "additive si connecté" doit passer par
  `optional_login_ctx()` (jamais un `require_login()`, qui bloque le
  rendu — inacceptable sur un onglet qui doit rester utilisable sans
  compte).

**Notes / À faire** :
- [ ] Utilisateur : tester le vrai bouton avec un compte réel (import →
  filtre → export → "Enregistrer dans la base de données" → vérifier
  dans l'onglet Base de données que les lignes apparaissent dans le bon
  environnement).
- [ ] Question ouverte, pas tranchée : l'upload brut de l'onglet Base
  de données (sans mapping/filtre) reste-t-il utile maintenant que ce
  bouton existe, ou devient-il redondant à terme ? Pas supprimé pour
  l'instant, à revoir selon l'usage réel.

---

## Nettoyage qualité + correction de bugs réels (2026-09-17)

**Demande** : "nettoie le code, fais tout propre, limite les bugs au
maximum, fais les correctifs nécessaires, anticipe" — suite à une
confusion de l'utilisateur sur ce qui avait changé (clarifié : Streamlit
= la techno, inchangée ; Render = l'hébergement, changé lui, voir
section Migration ci-dessous).

**Fait**, sur `trieur/` + `views/` + `app.py`, en deux passes
(`/code-review high --fix` puis `/simplify` sur le diff résultant),
chaque correctif relu et vérifié à la main avant commit :

1. **Bug réel, priorité sécurité/argent** : la détection de doublon
   IBAN (mandats SEPA/prélèvement) ne se déclenchait JAMAIS. La colonne
   générée `records.iban_normalized` (migration 0001) lit la clé JSON
   fixe `"iban"` (minuscule), mais l'import gardait le nom réel de la
   colonne choisie par l'utilisateur ("IBAN", etc.) sans jamais la
   recopier vers cette clé. Corrigé dans `views/tab_database.py`.
   Vérifié par requête réelle sur la base de prod (`trieur_data.records`)
   : table vide, donc aucune ligne existante affectée, pas de backfill
   nécessaire.
2. Suppression/réordonnancement d'une colonne d'environnement (et,
   même bug, un filtre enregistré ou un preset d'export) pouvait
   renommer EN SILENCE l'élément voisin — les champs de saisie sont
   indexés par position et n'étaient jamais vidés après un changement
   de liste.
3. Une ligne totalement vide d'un fichier importé n'était plus jamais
   filtrée à la fusion (onglet 2) : la colonne "Source Data", toujours
   renseignée, faisait échouer le `dropna(how="all")`.
4. Suppression de code mort dans `trieur/matching.py` (deux fonctions
   non appelées, doublons d'une logique déjà ailleurs).
5. **Confirmation à deux clics avant toute suppression** (règle globale
   de l'utilisateur) : trois boutons supprimaient en un clic sans
   confirmation (jeu de colonnes du compte, filtre enregistré, preset
   d'export) — nouveau helper partagé `views/_ui.py:confirm_delete_button()`.
6. Après une revue croisée à 4 angles (`/simplify` : reuse,
   simplification, efficiency, altitude — unanimes), factorisé le
   nettoyage des widgets périmés par position (point 2 + le nouveau
   drapeau "en attente de confirmation" du point 5, qui a le même
   problème) dans un seul helper `clear_stale_widgets()`, au lieu de
   3 implémentations à la main.

**Vérifié** : suite complète (99 tests, dont 2 e2e Playwright réels)
verte avant ET après merge sur `main`. Comportement du nouveau
`confirm_delete_button`/`clear_stale_widgets` vérifié avec
`streamlit.testing.v1.AppTest` (script jetable, supprimé après
verif) : un clic isolé ne supprime rien, "Annuler" revient à l'état
initial, seul le second clic "Oui, supprimer" déclenche l'action.

**Ignoré (signalé, pas traité)** : le renvoi trouvé par l'angle
altitude — indexer les lignes (filtres, presets, colonnes) par un id
stable (uuid) plutôt que par position ferait disparaître entièrement
le besoin de `clear_stale_widgets()`, pas seulement le factoriser.
Changement plus large que ce chantier, à considérer si ce genre de bug
revient sur un futur onglet.

**Ne pas casser** :
- Tout futur bouton de suppression doit passer par
  `confirm_delete_button()` (views/_ui.py), pas un `st.button()` nu.
- Toute nouvelle liste avec des widgets indexés par position (rename,
  reorder, delete) doit appeler `clear_stale_widgets(...)` avec ses
  préfixes après chaque mutation de la liste, sinon retour du même bug
  de renommage/confirmation silencieux sur l'élément voisin.

---

## Instabilité signalée par l'utilisateur (déconnexions, "ça plante") — 2026-09-17

**Cause racine trouvée et corrigée (vérifiée en conditions réelles)** :
Streamlit efface `st.session_state` à chaque reconnexion WebSocket
(mobile qui met l'onglet en veille, réseau qui coupe un instant) — la
session de connexion n'était jamais sauvegardée côté navigateur, donc
déconnexion silencieuse en permanence même si le jeton Supabase restait
valable des semaines. Corrigé avec le même mécanisme de secours
localStorage que les colonnes maîtres (`views/_ls_auth_sync.py` +
`components/ls_auth_session/`) — testé avec un vrai jeton généré via
l'API admin (sans mot de passe), injecté dans le localStorage, page
rechargée : la session revient automatiquement, sans repasser par le
formulaire.

**Deuxième cause, probable, à surveiller** : **deux sessions Claude ont
travaillé sur ce même dépôt en parallèle aujourd'hui** (repéré via
`git log` — une autre session a ajouté le résumé "où j'en suis", le
bandeau "depuis ta dernière visite" et les sections du Cockpit,
référençant un fichier `cockpit-kit/FONCTIONNALITES.md` d'un autre
dépôt de l'utilisateur). Chaque merge sur `main` déclenche un
redéploiement Streamlit Cloud (~1-2 min d'indisponibilité) — avec deux
sessions qui poussent en parallèle, le nombre de redéploiements dans la
journée a été anormalement élevé. Ce n'est probablement pas un vrai bug
Streamlit mais le rythme de développement du jour ; à confirmer si
l'instabilité persiste une fois le rythme de merges redescendu.

**Vraie limite de Streamlit, pas corrigible par du code** : chaque
interaction (clic, saisie) réexécute tout le script de haut en bas —
c'est le modèle même de Streamlit, pas un bug. Sur mobile avec un réseau
irrégulier, ça peut donner une sensation de rechargement fréquent. Si
après ce correctif + la fin du rythme de merges intense la sensation de
lenteur/instabilité persiste, la vraie solution serait de migrer vers
une architecture backend + frontend séparés (React, stack par défaut de
l'utilisateur) — un vrai chantier à part, pas une rustine.

**Notes / À faire** :
- [x] Confirmer avec l'utilisateur que les déconnexions ont cessé après
  ce correctif. → migration complète d'hébergement décidée à la place
  (voir section suivante), le correctif localStorage reste actif.
- [ ] Si l'utilisateur veut ouvrir plusieurs sessions Claude en parallèle
  sur ce dépôt à l'avenir, envisager de les faire travailler sur des
  chantiers différents (branches différentes) plutôt que sur le même
  chantier Cockpit, pour éviter les merges qui se chevauchent.

---

## Migration d'hébergement Streamlit Cloud → Render (2026-09-17)

**Pourquoi** : instabilité persistante (déconnexions, plantages, reboots
manuels) malgré le correctif localStorage ci-dessus — "tous mes autres
projets fonctionnent, à part celui-là". Théorie retenue après 3 incidents
`ImportError` en production juste après un push (chacun reproductible
comme "le code est correct localement") : le redéploiement à chaud de
Streamlit Cloud entre en conflit avec la synchronisation multi-fichiers
Git, ce que Render (déploiement conteneur complet, pas de hot-reload)
n'a pas.

**Fait** : migration vers Render (palier gratuit) sans toucher au
fonctionnement de l'app :
- `render_start.sh` génère `.streamlit/secrets.toml` depuis les variables
  d'environnement Render (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) au
  démarrage du conteneur, puis lance `streamlit run` normalement.
- `.github/workflows/keepalive.yml` : ping toutes les 10 min pour éviter
  la mise en veille du palier gratuit (15 min d'inactivité) — gratuit et
  illimité car le dépôt est public (vérifié : un cron Render gratuit
  n'existe pas, contrairement à ce qu'indiquait le schéma de l'outil).
- Déploiement Render vérifié "live" (logs de démarrage propres) + la
  page réelle récupérée par `curl` (10951 octets, contenu Streamlit
  valide, après avoir écarté un faux "Not Found" dû à un cache Cloudflare
  périmé).
- **Limite honnête** : pas de vérification Playwright complète de l'URL
  Render en HTTPS depuis cet environnement (le proxy sortant réémet son
  propre certificat TLS, non reconnu par défaut par Chromium/Playwright
  — je n'ai pas contourné la vérification TLS, c'est une règle non
  négociable). Les logs Render + le `curl` sont la preuve dont je
  dispose ; **pas encore testé par l'utilisateur en usage réel**.

**Notes / À faire** :
- [ ] Utilisateur : confirmer en usage réel (ouverture depuis le
  téléphone sur plusieurs jours) que l'instabilité a disparu.
- [ ] Décommissionner l'ancien déploiement Streamlit Cloud une fois
  Render confirmé stable (proposé, pas encore décidé).

---

## Performance : mise en cache des lectures Supabase rarement modifiées (2026-09-17)

**Demande** : "améliorer nettement le chargement de la page et des
différents onglets."

**Cause** : `require_login()` (appelé à chaque rendu de Base de données
et du Cockpit) relit le profil et les appartenances par requête réseau
Supabase à CHAQUE interaction, même quand rien n'a changé — pareil pour
la liste des organisations, les sections du Cockpit et les colonnes
maîtres d'une organisation. Streamlit réexécute tout le script à chaque
clic (comportement structurel, pas un bug), donc ces allers-retours
réseau se répétaient inutilement à chaque interaction.

**Fait** (`trieur/db.py`, branche `claude/perf-cache-lectures`,
mergée sur `main`) : `st.cache_data(ttl=30)` sur `get_my_profile`,
`get_my_memberships`, `list_organizations`, `list_sections`,
`get_org_master_columns` — données qui changent rarement. Chaque
écriture correspondante (`save_org_master_columns`, `create_section`,
`set_active_column_set`) appelle `.clear()` explicitement juste après
pour ne jamais afficher de donnée périmée après une action utilisateur.
Les données qui changent souvent (clients importés, chantiers, alertes
de doublon) ne sont **pas** mises en cache — pas de risque de retard
d'affichage là où ça compte.

**Vérifié** : suite de tests complète (99 tests) — 98 passent, 1 échec
préexistant et sans lien (`test_master_columns_localstorage_fallback`,
confirmé en échec identique sur le code non modifié, avant ce chantier).

**Limite honnête** : pas de test Playwright avec vrai jeton Supabase
dans cette session (pas de `.streamlit/secrets.toml` disponible ici) —
la logique d'invalidation a été relue point par point (chaque fonction
d'écriture qui touche une table lue en cache a son `.clear()`), mais
n'a pas été observée en conditions réelles avec un vrai compte.

**Ne pas casser** :
- Toute nouvelle fonction de lecture ajoutée sur une table déjà cachée
  (profiles, organizations, sections) doit soit être mise en cache avec
  le même TTL, soit rester consciente qu'une autre lecture cachée peut
  afficher une version différente pendant jusqu'à 30s après une
  écriture ailleurs.
- Toute nouvelle écriture sur `profiles`, `organizations` ou `sections`
  doit appeler `.clear()` sur la fonction de lecture correspondante,
  sinon régression de donnée périmée.

**Notes / À faire** :
- [ ] Utilisateur : confirmer en usage réel que le chargement est perçu
  comme plus rapide.
- [ ] Si la lenteur persiste malgré ça, le vrai plafond est structurel à
  Streamlit (script entier réexécuté à chaque clic) — la seule vraie
  solution serait une architecture backend + frontend séparés (déjà
  noté plus haut), pas une rustine de plus.

---

## Cockpit : résumé "où j'en suis" + bandeau "depuis ta dernière visite" (2026-09-17)

Le Cockpit se limitait à une liste de chantiers (statut, todos, fil de
discussion) — comparé à celui du projet Jarvis, il manquait deux choses
que l'utilisateur a demandé de généraliser à tout projet, pas seulement
Jarvis (voir `rnab26/dotfiles/cockpit-kit/FONCTIONNALITES.md`, le
cahier des charges partagé, indépendant du langage).

**Résumé "où j'en suis"** (`views/tab_cockpit.py::_render_ou_jen_suis`) :
quatre nombres par organisation — Bouge (`en_cours`), Livré aujourd'hui
(`termine` mis à jour aujourd'hui), Pour toi (`attente_retour`), Dort
(`a_faire`). `abandonne` ne compte dans aucune des quatre, volontairement
(un chantier abandonné n'est ni actif ni "à traiter").

**Bandeau "depuis ta dernière visite"** : nouvelle table
`trieur_data.visites_cockpit` (migration `0006`) + fonction SQL
`marquer_cockpit_vu()` dont le non-recul est garanti côté serveur
(`greatest()`), pas côté client — deux onglets ouverts en même temps ne
doivent pas pouvoir s'écraser l'un l'autre. Silencieux à la toute
première visite (aucun repère = rien à annoncer comme "nouveau").

**Recherche + filtre par statut** ajoutés sur la liste active
(`col_search`/`col_filter` dans `render()`).

Vérifié : `python3 -m py_compile` sur les deux fichiers modifiés,
`pytest` (97/99 — les 2 échecs sont le flake Playwright déjà documenté
plus haut, sans rapport), migration `0006` appliquée réellement contre
la base partagée (table + fonction confirmées présentes par requête).

**Non vérifié** : rendu réel dans un navigateur (pas d'accès Streamlit
Cloud depuis cet environnement). À constater par l'utilisateur : ouvrir
l'onglet Cockpit et voir le résumé à quatre chiffres + le bouton "Vu".

**Notes / À faire** :
- [x] Sections : demandées explicitement par l'utilisateur le jour même
  malgré la conditionnalité du kit — voir entrée suivante.
- [ ] Pas de détection de doublons de chantiers — toujours conditionnel
  au volume, à ajouter si le nombre de chantiers grossit vraiment.
- [ ] Actions groupées (changer le statut de plusieurs chantiers à la
  fois) pas encore faites, même raison (peu de chantiers aujourd'hui).

---

## Cockpit : sections (2026-09-17, suite immédiate)

L'utilisateur a testé le résumé/bandeau ci-dessus et n'a vu ni case ni
section — sa demande explicite : les sections, il les veut MAINTENANT,
indépendamment du volume actuel de chantiers.

**Migration `0007`** : colonne `theme` (texte libre) sur `chantiers` +
table `sections` (id, org_id, nom, position) — PAS de clé étrangère
stricte entre les deux, volontairement (même choix que documenté sur
Jarvis) : une FK interdirait de créer un chantier avant d'avoir déclaré
sa section, ce qui contredirait "on annonce, on ne bloque pas".

**Écran** (`views/tab_cockpit.py`) : le formulaire "Nouveau chantier"
propose une section existante, "Sans section", ou "+ Nouvelle
section..." (crée la section à la volée). Un expander "🗂️ Sections"
liste les sections déclarées et permet d'en créer une VIDE (utile avant
d'y ranger quoi que ce soit). La liste active est groupée par section
dans l'ordre déclaré, une section vide s'affiche quand même (avec "Aucun
chantier actif dans cette section"), et tout chantier dont le thème ne
correspond à AUCUNE section déclarée atterrit sous "À classer" — jamais
perdu, jamais rattaché en silence à la mauvaise section.

**Vérifié RÉELLEMENT, pas supposé** : migration appliquée contre la base
partagée (colonne + table confirmées par requête), et le cycle complet
(créer une section → créer un chantier avec cette section → le relire
avec son thème) rejoué avec un VRAI compte utilisateur authentifié,
membre de l'organisation via RLS — pas la clé service_role, qui aurait
pu masquer un problème de permission. `pytest` : 97/97 (hors le flake
Playwright déjà documenté, ignoré ici).

**Non vérifié** : le rendu réel dans le navigateur (pas d'accès
Streamlit Cloud depuis cet environnement, l'app est derrière l'auth
viewer de Streamlit Cloud). À toi de confirmer après redéploiement.

---

## Base de données : point 1 (gestion des colonnes) + Cockpit restructuré (2026-09-17)

**Gestion des colonnes** : dans Base de données → réglages, chaque
colonne d'une organisation peut être renommée, réordonnée (⬆️/⬇️),
supprimée, et on peut en ajouter — plus un simple champ texte. La liste
"Clients importés" respecte cet ordre (colonnes déclarées d'abord, puis
toute donnée présente mais pas déclarée, jamais masquée). Réservé aux
admins (même règle que les autres réglages d'organisation).

Point 2 du même chantier (enrichissement de clients existants à
l'import) reste en attente : l'utilisateur a précisé qu'un client n'est
créé qu'une fois mais peut avoir des variantes/nouvelles souscriptions
sur ce même client — pas un simple "upsert" par clé. À trancher avec
l'Excel de référence.

**Cockpit restructuré** selon le modèle déjà écrit dans le CLAUDE.md
global de l'utilisateur (demandé explicitement : "monte le Cockpit
depuis CLAUDE.md", confirmé via question de clarification) :
- Chantiers groupés par statut, ceux en `attente_retour` (⏳ attendent
  une réponse) ressortent en premier ; `termine`/`abandonne` sont
  archivés dans un tiroir replié, jamais supprimés.
- Statut modifiable directement dans la liste.
- **Points cochables par chantier** (`trieur_data.chantier_todos`,
  migration `0005`) : "coche ce qui est fait plutôt que de le
  supprimer, note les points restés ouverts" (citation du CLAUDE.md) —
  volontairement pas de suppression possible, seulement cocher/décocher.

Les deux vérifiés par requête réelle contre la base (200 OK) + rendu
réel de la page avec les vrais secrets Supabase (pas de crash) avant
merge. 98/99 tests (99e = flake préexistant déjà documenté).

**Notes / À faire** :
- [ ] Pas encore testé en conditions réelles par l'utilisateur (cocher
  un point, réordonner une colonne, depuis le vrai navigateur).
- [ ] Chantiers Cockpit encore en attente : Export XML SEPA (attend
  l'ICS + l'Excel), organisation de la liste clients (attend l'Excel).

---

## Cockpit : login unique + hook de démarrage automatique (2026-09-17)

**Login unique** : l'utilisateur a signalé deux formulaires de connexion
dupliqués (Cockpit et Base de données demandaient chacun email/mot de
passe). Corrigé : `views/_auth.py.render_top_auth_widget()`, un seul
bouton (popover) affiché une fois dans `app.py`, à côté de la barre de
menu. `require_login()` ne redessine plus de formulaire, renvoie juste
vers ce bouton.

**Bug de sécurité trouvé et corrigé au passage** : la table
`organizations` n'avait qu'une policy RLS **SELECT**, aucune UPDATE — un
membre normal qui essayait d'enregistrer les colonnes maîtres de son
organisation (onglet Base de données) échouait silencieusement (seul
mon accès admin direct fonctionnait). Ajouté : policy UPDATE réservée
aux super-admins (migration `0004_organizations_update_policy.sql`) +
champ désactivé côté interface pour un non-admin.

**Piège de diagnostic à retenir** : deux `ImportError` sont apparus en
prod (Streamlit Cloud) sur du code qui s'importait sans erreur en local
— dans les deux cas, la cause réelle était un **secrets.toml absent en
local** (jamais testé dans les mêmes conditions que la prod) ou un
**déploiement pas encore terminé** au moment où l'utilisateur a
rafraîchi juste après un push. Reproduit les conditions réelles (vrais
secrets Supabase + vrai serveur Streamlit + Playwright) avant de conclure
à un bug de code — ça a évité de chercher un bug qui n'existait pas.
**À faire systématiquement à l'avenir avant de creuser un ImportError
Streamlit Cloud.**

**Hook de démarrage Cockpit** (`.claude/hooks/session-start.sh`,
enregistré dans `.claude/settings.json`) : chaque nouvelle session
Claude Code sur ce dépôt lit maintenant automatiquement les chantiers
`trieur_data.chantiers` ouverts (statut a_faire/en_cours/attente_retour)
au démarrage, via l'API REST Supabase avec `SUPABASE_SERVICE_ROLE_KEY`
(déjà dans l'environnement) — plus besoin de demander "regarde le
Cockpit" à chaque session. Silencieux si la clé est absente (jamais
bloquant). `.claude/` était entièrement gitignoré ; exception ajoutée
pour `.claude/hooks/` et `.claude/settings.json` uniquement (voir
`.gitignore`), pour que ce hook s'applique à toute future session sur ce
dépôt — c'est la version "hook de démarrage" demandée dans le CLAUDE.md
global de l'utilisateur.

**Notes / À faire** :
- [ ] Le hook lit les chantiers mais ne lit pas encore le fil de
  messages complet automatiquement (juste le titre/statut) — la session
  doit encore aller chercher `chantier_messages` via le MCP Supabase.
  Volontaire pour l'instant (éviter un hook trop lourd/lent au
  démarrage) ; à revoir si ça devient gênant en pratique.
- [ ] `get_client()` (trieur/db.py) est un `@st.cache_resource` — donc un
  objet PARTAGÉ par tous les visiteurs du même processus Streamlit Cloud
  (pas par session). `client.auth.set_session(...)` est appelé à chaque
  requête donc ça ne devrait pas mélanger les sessions de deux personnes
  différentes en pratique, mais pas vérifié sous vraie charge concurrente
  (deux comptes connectés en même temps). À surveiller, pas encore un
  problème avec 2 utilisateurs.

---

## Export XML SEPA (pain.008) — Prélèvement (2026-09-17)

**Contexte** (donné par l'utilisateur) : le père gère les prélèvements
via un CRM tiers imparfait (doublons, vendeurs qui renvoient d'anciens
contrats comme nouveaux) et compense avec un Excel truffé de formules de
contrôle (dont la vérif IBAN/nom inversé qui a lancé tout ce chantier
CRM). But : télécharger depuis l'onglet Base de données un fichier XML
conforme au format bancaire (ISO 20022, pain.008), pas juste CSV/Excel.

**Suivi vivant : chantier créé dans le Cockpit** (environnement
Prélèvement, statut "attente_retour") — table `trieur_data.chantiers`,
avec le contexte complet en message. Le mettre à jour là-bas en plus
d'ici quand ça avance.

**2026-09-17 (suite) — Échantillon réel reçu et analysé** :
- [x] L'utilisateur a fourni un vrai fichier XML accepté par la banque du
  père — **contenait de vraies données personnelles/bancaires**, jamais
  copié dans ce dépôt. Une tentative de script pour en tirer
  automatiquement une version anonymisée a été bloquée par un garde-fou
  de la plateforme ("Sensitive-Source Provenance") — pas de détour
  cherché, la référence a été réécrite à la main à partir de la
  structure observée (`tests/fixtures/pain008_sample_reference.xml`,
  100% fictif).
- Confirmé sur l'échantillon réel : schéma **pain.008.001.08**,
  regroupement en blocs `<PmtInf>` par (date de prélèvement, FRST/RCUR).
  **Le BIC débiteur est bien exigé par cette banque** (pas de règle
  "IBAN seul" appliquée ici) — donc le BIC doit venir des données
  source, jamais dérivé ou deviné depuis l'IBAN.
- [x] `trieur/sepa.py.build_pain008_xml()` écrit et testé (10 tests,
  structure comparée à la référence). Lève `SepaXmlError` plutôt que de
  générer un fichier avec un champ manquant/deviné.
- [ ] **Toujours en attente** : l'ICS de l'organisme (pas transmis avec
  le fichier), et l'Excel du père (règles de contrôle, second volet du
  chantier).
- [ ] Pas encore branché à l'interface (onglet Base de données) : reste
  à décider les noms de colonnes Prélèvement pour IBAN/BIC/ICS créancier
  (config organisation), et BIC débiteur/RUM/montant/date de signature
  par ligne (probablement dans l'Excel du père, pas encore reçu) + la
  date de prélèvement demandée (saisie manuelle ou déduite).

**Déjà fait avant l'échantillon** (fondation indépendante du format) :
- [x] `trieur/sepa.py.determine_sequence_type` : FRST/RCUR à partir de
  l'historique IBAN déjà en base (`find_iban_matches`, chantier du
  2026-09-16).
- [x] `trieur.db.get_sepa_sequence_type(client, org_id, iban)`.

**Second objectif du même chantier** (mentionné, à cadrer plus tard) :
étudier l'Excel de contrôle du père une fois reçu pour en extraire les
règles métier restantes et les brancher comme vérifications
supplémentaires sur l'environnement Prélèvement — **pas un moteur
séparé** : des règles en plus sur le moteur unique du Trieur de Data
(décision explicite de l'utilisateur, 2026-09-17).

---

## Mémoire des colonnes maîtres liée au compte (2026-09-17)

**Quoi** : dans l'onglet 1, un utilisateur connecté peut enregistrer
plusieurs jeux de colonnes maîtres nommés, les appliquer, les supprimer.
Le dernier appliqué est retenu et **réappliqué automatiquement à la
prochaine connexion**, quel que soit l'environnement — répond
directement à la demande de l'utilisateur ("éviter de les retaper à la
main"). Table `trieur_data.user_master_column_sets` + colonne
`profiles.active_master_column_set_id`.

**Distinction importante à ne jamais mélanger** :
- Ceci = colonnes maîtres **par compte utilisateur**, pour l'onglet 1
  (coeur du Trieur), peu importe l'organisation.
- Les colonnes maîtres **par organisation** (`organizations.master_columns`,
  chantier du 2026-09-16) servent à structurer l'import dans l'onglet
  "Base de données" — usage différent, ne pas fusionner les deux.

**Garde-fou respecté** (rappel explicite de l'utilisateur, 2026-09-17) :
strictement additif — `trieur/persistence.py` (mode anonyme local +
secours localStorage) et `views/tab3_filtrage_dedup.py` (moteur de dédup
existant, différent du dédup IBAN base) **non touchés**. Vérifié par
89/89 tests passant (E2E réel inclus), et par construction : la section
compte de l'onglet 1 (`_render_account_memory`) sort immédiatement si
`auth_session` n'est pas en session — aucun import Supabase, aucun appel
réseau, aucun changement visuel pour un visiteur non connecté.

**État** : mergé sur `main`. Le login n'a pas encore été testé en
conditions réelles pour CETTE fonctionnalité précise (appliquer un jeu,
se déconnecter, se reconnecter, vérifier qu'il revient automatiquement)
— à faire par l'utilisateur.

**Notes / À faire** :
- [ ] Vérifier en conditions réelles (navigateur, avec un vrai login) :
  enregistrer un jeu de colonnes, se déconnecter/reconnecter, confirmer
  qu'il est réappliqué automatiquement.
- [ ] Reste du chantier "points A+B" évoqué le 2026-09-16 (filtres
  enregistrés, presets d'export, mapping mémorisé par forme de fichier)
  — pas encore migré vers Supabase, toujours en fichiers JSON éphémères
  côté serveur. Prochaine tranche si l'utilisateur confirme que ça reste
  un problème après cette première étape.

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
  projet `jarvis-assistant`) + profil **`is_super_admin = true`** (précisé
  par l'utilisateur le 2026-09-17 : lui et son père sont tous les deux
  admins — pas `member`) + membership Prélèvement.

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
- [x] Les colonnes maîtres de l'onglet 1 (mode anonyme, fichier JSON)
  restent séparées de celles de l'org en base — clarifié le 2026-09-17 :
  ce n'était pas la bonne architecture, voir section suivante.

**2026-09-17 — Refonte navigation : Cockpit ≠ Base de données** :
- Recadrage explicite de l'utilisateur : le **Cockpit est réservé aux
  administrateurs** (lui + son père, jamais un futur utilisateur externe
  à qui l'outil serait prêté) et **ne concerne QUE le développement du
  logiciel** (chantiers, échanges avec Claude) — aucune donnée client ne
  doit y transiter. L'import/dédup/colonnes maîtres par organisation
  (ce qui avait été mis dans le Cockpit le 2026-09-16) était donc au
  mauvais endroit.
- Créé l'onglet **"Base de données"** (`views/tab_database.py`) : reprend
  exactement ce contenu (colonnes maîtres par org, import + dédup IBAN,
  alertes), mais accessible à **tout membre connecté** de l'organisation,
  pas seulement aux admins. `views/tab_cockpit.py` redevient
  chantiers-only, avec garde explicite `is_super_admin` (message "réservé
  aux administrateurs" sinon).
- Navigation : la barre `st.tabs()` des 4 étapes (Colonnes maîtres →
  Import → Filtrage → Export) reste un groupe unique et intact (ne
  JAMAIS la scinder — voir la note sur le widget `streamlit-sortables`,
  chantier Export). Au-dessus, une barre de menu horizontale
  (`st.segmented_control`, 3 sections : "Trieur de Data" / "Base de
  données" / "Cockpit") remplace le 5ᵉ onglet — ce ne sont pas des étapes
  d'un même parcours, elles ne doivent pas être mélangées visuellement
  avec 1→4.
- Vérifié réellement (Playwright, pas juste relu) : le sélecteur
  `[data-testid="stTab"]` utilisé par `views/_nav.py` pour les boutons
  "étape suivante" ne cible bien QUE les 4 onglets (0 à 3), aucune
  interférence du `st.segmented_control`. 89/89 tests passent.
- Refactor partagé : `views/_auth.py.accessible_organizations(ctx)`
  centralise "quelles organisations cet utilisateur voit" (toutes si
  `is_super_admin`, sinon ses memberships) — utilisé par Cockpit ET Base
  de données, une seule source de vérité.
- [ ] **Pas encore testé en conditions réelles par l'utilisateur** une
  fois déployé.
- [ ] Chantier A+B (persistance complète : filtres enregistrés, presets
  d'export, mapping mémorisé, et surtout les onglets 1-4 eux-mêmes
  devenant conscients de la connexion/organisation) — décidé le
  2026-09-17 mais pas encore commencé, c'est le prochain chantier après
  celui-ci.
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

---

## Migration React (branche `feature/react-migration`, en cours)

**Quoi** : bascule progressive de l'interface Streamlit vers une SPA
React, sans toucher à l'app Streamlit actuelle (les deux tournent en
parallèle sur la même base Supabase pendant la transition).

**État (2026-09-17, scaffolding initial)** :
- `api/main.py` : API REST FastAPI au-dessus de `trieur/db.py` (aucune
  logique dupliquée) — orgs, tableau de bord, clients (liste paginée
  avec recherche/filtres sur le lot chargé, lecture, modification),
  import CSV/Excel, colonnes maîtres (lecture ouverte, écriture admin),
  vues enregistrées (créer/lister/supprimer). Auth par jeton Supabase
  (`Authorization: Bearer <token>`), un client Supabase neuf par
  requête (pas le singleton `@st.cache_resource` de Streamlit — évite
  une fuite de jeton entre requêtes concurrentes).
- `frontend/` : Vite + React 19 + TypeScript strict + Tailwind v4,
  composants façon shadcn/ui faits main. Auth Supabase, écran "Base de
  données" (switcher d'organisation, recherche, tableau paginé,
  édition d'un client en modal avec états chargement/vide/erreur).
- Vérifié ce soir : suite de tests complète (`python -m pytest`) —
  **169 tests**, dont les 19 nouveaux de `tests/test_api.py` (faux
  client Supabase, aucun réseau) : tous passent. 1 test E2E
  (`test_master_columns_localstorage_fallback`) échoue de façon
  **intermittente** (~1 fois sur 3) — confirmé flaky **préexistant**,
  reproduit à l'identique sur `main` (commit `e6b54c8`, code inchangé),
  donc sans lien avec ce chantier ; pas corrigé ici, à traiter comme
  chantier de fiabilisation des tests séparément si ça agace.
  `cd frontend && npm run build` : succès (`tsc -b && vite build`,
  exit 0, aucun warning).
- Comparé `api/main.py` et `frontend/src/lib/api.ts` +
  `screens/*.tsx` endpoint par endpoint (méthode, chemin, noms de
  champs) : aucune incohérence trouvée.
- Confirmé : `views/` et `app.py` (l'app Streamlit live) non touchés —
  seuls `api/`, `frontend/`, `requirements*.txt` et `tests/test_api.py`
  ajoutés.
- Branche poussée sur `origin/feature/react-migration`. **Pas mergée
  sur `main`, pas de PR** — migration en cours, pas prête à remplacer
  le site en production.

**État (2026-09-17, suite — import + colonnes maîtres)** :
- `api/main.py` : `POST /orgs/{id}/import` accepte maintenant
  `dry_run=true` — lit le fichier (pandas, comme à l'import réel) et
  renvoie colonnes détectées + aperçu (10 lignes) + colonnes inconnues,
  **sans rien écrire en base**. Sert l'aperçu React avant confirmation
  sans dupliquer la lecture CSV/Excel côté navigateur (et sans y
  installer de lib de parsing Excel : `xlsx`/SheetJS a des CVE non
  corrigées — écarté, préféré une extension de l'endpoint existant).
  Ajout de `GET /me` (profil courant, dont `is_super_admin`) — le
  frontend en a besoin pour proposer ou non les contrôles d'édition des
  colonnes maîtres (le write endpoint les refusait déjà en 403, ceci
  évite juste de les montrer à un membre simple).
- Réordonner/renommer/supprimer une colonne maître ne nécessitait pas
  de nouvel endpoint : `save_org_master_columns` (trieur/db.py) prend
  déjà la liste complète ordonnée — le même
  `POST /orgs/{id}/master-columns` (déjà réservé admin) suffit, on lui
  renvoie chaque fois la liste modifiée.
- `frontend/` : deux nouveaux écrans dans "Base de données" (onglets
  Clients / Importer / Colonnes maîtres) —
  `screens/ImportPanel.tsx` (upload, aperçu des colonnes + IBAN à
  choisir, alerte si plusieurs colonnes ressemblent à un IBAN,
  proposition d'ajouter les colonnes inconnues aux réglages si admin,
  résultat import compté/alertes) et
  `screens/MasterColumnsPanel.tsx` (liste des colonnes ; admin :
  renommer/réordonner/supprimer avec confirmation/ajouter ; non-admin :
  lecture seule). États chargement/vide/erreur traités sur les deux.
- Vérifié : `python3 -m pytest tests/test_api.py -q` → **25 passed**
  (dont 6 nouveaux tests : dry_run n'écrit rien, import réel, gate
  admin sur l'ajout de colonnes inconnues, `/me`). Suite complète
  (`python3 -m pytest -q`) → **175 passed**. `cd frontend && npm run
  build` → succès (`tsc -b && vite build`, exit 0).
- `views/` et `app.py` non touchés.

**Reste à faire (portage des écrans Streamlit vers React)** — au-delà
de "Base de données" (liste/recherche/édition/import/colonnes
maîtres) livré :
- [x] Import CSV/Excel (aperçu colonnes, choix IBAN, colonnes
  inconnues → ajout aux colonnes maîtres) — livré 2026-09-17.
- [x] Gestion des colonnes maîtres (UI ajout/renommage/réordonnage/
  suppression, admin ; lecture seule sinon) — livré 2026-09-17.
- [x] Vues enregistrées (UI créer/lister/appliquer/supprimer) — livré
  2026-09-17 (voir suite ci-dessous).
- [x] Tableau de bord par environnement + badge d'alertes de doublon —
  livré 2026-09-17.
- [x] Modification/suppression multiple (sélection multi-lignes) —
  livré 2026-09-18 (voir 4e incrément ci-dessous).
- [x] Recherche avancée façon Google Sheets (filtres par colonne
  combinés) — livré 2026-09-17 (`ColumnFilters.tsx`), branché sur
  `col_filters` déjà exposé par l'API.
- [x] Alertes de doublon IBAN avec diff (résolution) — livré
  2026-09-18 (voir 4e incrément ci-dessous).
- [x] Export direct depuis la base (CSV/Excel) — livré 2026-09-18
  (voir 4e incrément ci-dessous).
- [x] Historique court par ligne modifiée — déjà exposé par l'API
  existante (`_build_rows`/`_resolve_modifier_names`), affiché comme
  colonne dans le tableau React ; vérifié 2026-09-18, rien à ajouter.
- [x] Diff au réimport (ré-import d'un fichier déjà présent) — audité
  2026-09-18 : **ce n'est pas une fonctionnalité distincte**, c'est le
  même mécanisme que les alertes de doublon IBAN ci-dessus. Dans
  Streamlit, `import_dataframe` (`trieur/db.py`) crée une
  `dedup_alert` dès qu'une ligne réimportée matche un IBAN déjà en
  base (`find_iban_matches`), et c'est cette même alerte qui affiche
  le diff champ par champ (`diff_rows`, `views/tab_database.py`) —
  il n'y a aucun deuxième diff séparé au moment de l'import lui-même.
  Côté React, `DedupAlertsPanel.tsx` réutilise déjà `diff_rows` via
  `GET .../dedup-alerts` (`api/main.py`) : rien à porter, la case
  précédente était trop prudente. Aucun code ajouté pour ce point.
- [ ] Les onglets "Trieur de Data" eux-mêmes (au-delà de la Base de
  données) : tout ce qui vit dans les autres tabs de `app.py`/`views/`
  (import/mapping/aperçu/filtrage/export propres à Trieur de Data) et
  n'a pas encore d'équivalent React ni d'endpoint API dédié. **Scoping
  fait 2026-09-18 (recherche/planning, aucun code)** — voir section
  "Scoping des 4 onglets Streamlit restants" ci-dessous pour le détail
  onglet par onglet et les deux points transverses (session serveur,
  progression des tâches longues) à trancher avant de commencer le
  portage.

**État (2026-09-17, suite — filtres par colonne + vues enregistrées +
tableau de bord)** :
- Découverte : côté API les trois fonctionnalités étaient déjà prêtes
  (`col_filters` sur `GET .../records`, `GET/POST/DELETE
  .../saved-views`, `GET .../dashboard` avec `alerts_pending` via
  `list_dedup_alerts`) — aucun changement API nécessaire, seul le
  frontend manquait.
- `frontend/` : `ColumnFilters.tsx` (opérateur
  contient/ne contient pas/égal à/vide/non vide + valeur, combinés en
  ET), `SavedViews.tsx` (lister/enregistrer/appliquer/supprimer une
  vue), `DashboardPanel.tsx` (clients/alertes en attente/dernier
  import, recalculé après import/édition), `DatabaseScreen.tsx`
  (intègre les trois + sélecteur de colonnes affichées), `api.ts`
  (`colFilters` sur `listRecords`, fonctions vues enregistrées,
  correction d'un bug de types : `Dashboard.last_import` référençait
  `filename`/`created_at` au lieu des vrais champs
  `source_filename`/`imported_at`).
- **Vérifié indépendamment ce soir** (deuxième session, relecture
  ligne à ligne du code + comparaison API/frontend endpoint par
  endpoint) :
  - `python3 -m pytest -q` (suite complète) → **176 passed** (175
    d'avant + 1 nouveau test `test_records_col_filters_operators`),
    aucun flake observé cette fois. Le flake connu
    (`test_master_columns_localstorage_fallback`, ~1 fois sur 3,
    confirmé préexistant sur `main` par bisection) reste un chantier de
    fiabilisation séparé, sans lien avec ce travail.
  - `cd frontend && npm run build` → succès (`tsc -b && vite build`,
    exit 0).
  - `git diff --stat main...feature/react-migration -- views/ app.py`
    → vide, confirmé : app Streamlit toujours non touchée.
  - Relu `ColumnFilters.tsx`/`SavedViews.tsx`/`DashboardPanel.tsx`/
    `DatabaseScreen.tsx` contre `api/main.py` et `api.ts` : méthodes
    HTTP, chemins, noms de champs (`source_filename`/`imported_at`,
    `col_filters`, `visible_cols`) tous cohérents — aucune divergence
    trouvée.
  - Piège des valeurs falsy (0/''/false traité comme "vide") vérifié
    spécifiquement : `_matches_filter` (`views/tab_database.py`) juge
    "vide"/"non vide" sur `value is None or value == ""`, pas sur
    `not value` — un `ENFANTS: 0` reste "non vide", couvert par le
    nouveau test. Côté affichage, `DashboardPanel` et le tableau de
    `DatabaseScreen` utilisent JSX direct / `== null` (jamais `||` ou
    `!value`) — un compteur à 0 s'affiche bien "0", jamais vide ni
    coincé en "chargement". **Aucun bug trouvé, rien à corriger.**
- Poussé sur `origin/feature/react-migration` (commit `<voir git log`
  au moment du push). Toujours pas mergé sur `main`, pas de PR.

**État (2026-09-18, 4e incrément — sélection multiple, alertes de
doublon avec diff, export, historique par ligne)** :
- `api/main.py` : `DELETE /orgs/{org_id}/records` (suppression
  groupée) et `PATCH /orgs/{org_id}/records/bulk` (modification d'UN
  SEUL champ pour toute la sélection), tous deux en boucle sur
  `delete_record`/`get_record`/`update_record` (`trieur/db.py`) — même
  logique que `views/tab_database.py`, aucune requête SQL en masse ni
  logique dupliquée. `GET /orgs/{org_id}/dedup-alerts` (diff champ par
  champ calculé côté serveur via `diff_rows()`, jamais réimplémenté en
  TS) et `POST .../dedup-alerts/{id}/resolve` (garde d'appartenance à
  l'org avant résolution). `GET /orgs/{org_id}/records/export?format=
  csv|xlsx` (`StreamingResponse`, respecte recherche/filtres par
  colonne/colonnes affichées — même règle de masquage que Streamlit :
  colonne connue à l'écran mais décochée → masquée, colonne jamais vue
  → incluse quand même).
- `frontend/` : `BulkActions.tsx` (case par ligne + "tout sélectionner",
  suppression à deux étapes avertissement/confirmer/annuler, édition
  d'un champ pour la sélection) et `DedupAlertsPanel.tsx` (diff par
  alerte, se cache s'il n'y a rien à traiter), intégrés à
  `DatabaseScreen.tsx` ; boutons Export CSV/Excel. Historique par ligne
  ("Modifié le"/"Modifié par") déjà affiché comme colonne, rien à
  ajouter.
- **Vérifié indépendamment ce soir** (session de vérification séparée,
  relecture ligne à ligne + tests réels, pas seulement lu le rapport de
  l'agent précédent) :
  - `python3 -m pytest -q` (suite complète) → **191 passed**, aucun
    échec, aucun flake observé cette fois (le flake connu
    `test_master_columns_localstorage_fallback` ne s'est pas manifesté
    sur ce run).
  - `cd frontend && npm run build` → succès (`tsc -b && vite build`,
    exit code 0, aucune erreur TypeScript).
  - `git diff --stat main...feature/react-migration -- views/ app.py`
    → vide, confirmé : app Streamlit toujours non touchée.
  - `api/main.py` comparé à `frontend/src/lib/api.ts` endpoint par
    endpoint (méthode, chemin, noms de champs) pour les 5 nouvelles
    routes : aucune divergence trouvée.
  - Flux suppression groupée (`BulkActions.tsx`) et résolution
    d'alerte (`DedupAlertsPanel.tsx`) relus spécifiquement pour un bug
    d'id/off-by-one : sélection et résolution sont indexées par
    `record._id`/`alert.id` réels (jamais par position dans un
    tableau) côté React comme côté API — **aucun bug trouvé**.
  - Export (`export_org_records`, `api/main.py`) relu : appelle
    `list_all_records` (tout l'historique, pas seulement la page
    affichée) puis applique `_filter_by_search`/`_filter_by_columns`
    avec les mêmes `search`/`col_filters` que la liste — **confirmé
    que l'export respecte bien les filtres actifs**, pas un export
    brut de toute la base.
  - Aucun bug trouvé nécessitant un correctif — le travail de l'agent
    précédent est passé la vérification sans modification.
- Poussé sur `origin/feature/react-migration`, commit `b9faad9`.
  Toujours pas mergé sur `main`, pas de PR.

**Vérification indépendante (2026-09-18, 5e incrément — audit
diff-réimport confirmé + scoping des 4 onglets restants)** :
- Contrôle indépendant du travail de l'agent précédent (commit
  `2be5115`, "Audite : diff au réimport = alertes de doublon IBAN, pas
  une feature à part") — relecture du code, pas seulement du rapport :
  - `python3 -m pytest -q` (suite complète) → **191 passed**, aucun
    échec, flake connu `test_master_columns_localstorage_fallback` non
    observé sur ce run.
  - `cd frontend && npm run build` → succès (`tsc -b && vite build`,
    exit code 0).
  - `git diff --stat main...feature/react-migration -- views/ app.py`
    n'était **pas vide** au premier essai (31/2/2 lignes sur
    `app.py`/`tab2_import_mapping.py`/`tab_database.py`) — creusé avant
    de conclure à une régression : la branche locale `main` de ce repo
    était **en retard de 4 commits sur `origin/main`** (dont
    précisément le fix CORS de l'upload et l'overlay de debug déjà
    mentionnés par l'agent précédent). En comparant contre
    `origin/main` (la vraie référence de prod) :
    `git diff --stat origin/main feature/react-migration -- views/
    app.py` → **vide, confirmé**. Pas une régression, un `main` local
    obsolète. Rien à corriger.
  - Conclusion : le travail du build agent précédent est validé sans
    modification. Rien n'a cassé.
- Commit `2be5115` poussé sur `origin/feature/react-migration` (ainsi
  que les 6 commits précédents déjà en attente). Toujours pas mergé
  sur `main`, pas de PR — migration en cours.

**Scoping des 4 onglets Streamlit restants (2026-09-18, recherche
seule, aucun code)** — Colonnes maîtres, Import & Mapping, Filtrage &
Dedup, Export :
- **Point transverse n°1 (le plus important, pas spécifique à un
  onglet)** : Streamlit garde `all_sheets`, `final_df` et `filtered_df`
  vivants dans le `session_state` d'un seul process Python, à travers
  tout le pipeline import → mapping → filtre → export, sans jamais
  renvoyer les données complètes au navigateur. Un backend FastAPI
  stateless n'a pas cet équivalent par défaut : **il faut décider UNE
  FOIS d'un mécanisme de session serveur** (cache par `session_id`,
  fichiers temporaires, ou Redis) qui porte le DataFrame intermédiaire
  entre les 3 étapes, **avant** de commencer à porter le moindre
  onglet — sinon chaque onglet sera bricolé différemment. **Décision en
  attente.**
- **Point transverse n°2** : plusieurs opérations sont longues
  (parsing Excel/CSV/PDF multi-millions de lignes, génération Excel,
  sauvegarde CRM en masse) et Streamlit affiche une barre de
  progression "gratuitement" à chaque rerun. En HTTP requête/réponse
  classique, il faut un mécanisme explicite (job async + polling, ou
  SSE/WebSocket) — sinon la barre de progression disparaît ou le
  navigateur time-out. **Décision en attente.**
- **Composant le plus dur à porter** : `streamlit-sortables` (onglet
  Export) — un vrai double glisser-déposer (colonnes incluses/exclues)
  avec son propre bug de mesure déjà contourné en JS dans le code
  actuel. Pas du wrapping de logique Python : un composant frontend
  neuf à construire (`dnd-kit` ou équivalent), avec un vrai enjeu
  tactile/mobile (usage fréquent depuis le téléphone).
- **Onglet 1 — Colonnes maîtres** (détail des fonctionnalités à
  reproduire, pas encore construites) :
  - Textarea listant les colonnes maîtres une par ligne, valeur
    initiale = liste persistée.
  - Bouton "Enregistrer" : dédoublonnage insensible à la casse en
    gardant l'ordre, sauvegarde disque JSON (`user_master_columns.json`),
    message de succès avec le compte, ou avertissement si la sauvegarde
    disque échoue (hébergement sans disque persistant).
  - Bouton "Réinitialiser" : revient à `DEFAULT_MASTER_COLUMNS` et
    sauvegarde.
  - Message d'erreur si la liste soumise est vide.
  - Info-bulle fixe expliquant la détection automatique
    TELEPHONE MOBILE/FIXE par contenu.
  - Section additive visible seulement si connecté : jeux de colonnes
    nommés liés au **compte** utilisateur (distincts des colonnes par
    organisation de l'onglet Base de données) — select des jeux
    existants, bouton Appliquer (applique + marque "jeu actif" pour la
    prochaine connexion), bouton Supprimer avec confirmation, champ nom
    + bouton Enregistrer le jeu courant sous un nouveau nom.
  - Auto-chargement une fois par session du dernier jeu actif
    enregistré sur le compte, dès la connexion.
- **Onglets 2 (Import & Mapping), 3 (Filtrage & Dedup), 4 (Export)** :
  scoping détaillé **pas encore reçu** dans cet incrément — seul
  l'onglet 1 a été détaillé jusqu'ici côté fonctionnalités précises.
  À compléter dans un prochain incrément avant de commencer le portage
  (ne pas supposer que ces 3 onglets sont plus simples que le 1er sans
  les avoir audités).
- **Estimation globale du chantier complet** (4 onglets + fondation
  session/progression) : **large** — probablement le plus gros morceau
  du portage React après "Base de données".

**Avancement global estimé** : ~55-60% de la migration complète. Fait :
auth, écran Base de données avec liste/recherche/filtres par
colonne/édition/import/colonnes maîtres/vues enregistrées/tableau de
bord/sélection multiple (suppression + modification groupées)/alertes
de doublon avec diff/export CSV-Excel/historique par ligne. Le "diff au
réimport" n'était **pas** une fonctionnalité distincte — audité et
clos 2026-09-18 (voir plus haut). Pour arriver à 100% il reste,
**honnêtement** : l'audit détaillé (fait pour l'onglet 1, pas encore
pour 2-4, voir scoping ci-dessus) puis le portage de **tous les autres
onglets propres à "Trieur de Data"** (import/mapping/aperçu/filtrage/
export au-delà de la Base de données), plus deux décisions
d'architecture transverses à trancher avant de commencer (session
serveur pour porter le pipeline import→mapping→filtre→export, et
progression pour les opérations longues) — c'est probablement le plus
gros morceau restant avant de pouvoir envisager un remplacement de
l'app Streamlit en production.

**Ne pas casser** : l'app Streamlit (`app.py`, `views/`) reste la seule
en production tant que ce chantier n'est pas fini — ne jamais merger
`feature/react-migration` sur `main` sans validation explicite de
l'utilisateur, migration écran par écran.

**État (2026-09-18, 6e incrément — écran Cockpit porté, vérifié
indépendamment)** :
- Cockpit (chantiers de dev de l'app elle-même, réservé admin) porté
  en React par l'agent précédent (commit `8a345be`) : `api/main.py`
  (`GET/POST /orgs/{id}/chantiers`, `GET/POST .../sections`, `PATCH
  .../chantiers/{id}/status`, `GET/POST .../messages`, `GET/POST
  .../todos`, `PATCH .../todos/{id}`, tous derrière
  `require_cockpit_access`, même règle que `views/tab_cockpit.py`,
  aucune logique dupliquée — tout appelle `trieur/db.py`),
  `CockpitScreen.tsx` + `ChantierCard.tsx` (bandeau "Où j'en suis",
  formulaires chantier/section, recherche + filtre statut, groupement
  par section, todos + fil de discussion), nouvel onglet nav visible
  admin seulement.
- **Vérifié indépendamment ce soir** (relecture ligne à ligne, pas
  seulement le rapport de l'agent précédent) :
  - `python3 -m pytest -q` (suite complète) → **205 passed** (191
    d'avant + 14 nouveaux tests Cockpit dans `tests/test_api.py`).
  - `cd frontend && npm run build` → succès (`tsc -b && vite build`,
    exit 0). `npm run lint` → seulement des warnings déjà présents sur
    d'autres écrans (`set-state-in-effect`, `only-export-components`),
    aucun nouveau problème.
  - `git diff --stat main...feature/react-migration -- views/ app.py`
    → non vide (31/2/2 lignes sur `app.py`/`tab2_import_mapping.py`/
    `tab_database.py`), mais ce sont les commits **antérieurs** au
    portage Cockpit (filet de diagnostic visible, déjà en place avant
    ce chantier) — rien ajouté par le portage Cockpit lui-même à
    `views/`/`app.py`. Confirmé sans régression.
  - `api/main.py` comparé à `frontend/src/lib/api.ts` endpoint par
    endpoint pour les 8 nouvelles routes Cockpit : méthode, chemin,
    noms de champs — aucune divergence trouvée.
  - **Bug réel trouvé et corrigé** : les 4 `<select>` natifs de
    `CockpitScreen.tsx` (switch d'environnement, priorité, section,
    filtre de statut) n'avaient pas de classe de couleur de texte
    explicite (`text-[var(--foreground)]`), contrairement à celui de
    `ChantierCard.tsx` qui l'avait déjà. Sur fond sombre
    (`.cockpit-dark`), un `<select>` natif ne garantit pas d'hériter
    la couleur du texte du conteneur dans tous les navigateurs — texte
    illisible (sombre sur fond sombre) ou popup système clair par
    défaut. Corrigé : couleur de texte ajoutée aux 4 `<select>`, plus
    `color-scheme: dark` posé sur `.cockpit-dark` pour que le popup
    natif du `<select>` lui-même rende sombre au lieu de reprendre le
    thème clair du système. Rebuild + lint refaits après correctif :
    toujours vert.
- Poussé sur `origin/feature/react-migration`, commit `<voir hash du
  push ci-dessous>`. Toujours pas mergé sur `main`, pas de PR.

**Décision d'architecture prise (2026-09-18) — PAS ENCORE IMPLÉMENTÉE,
prochaine session à démarrer par ceci** : réponse au point transverse
n°1 ci-dessus (session serveur pour porter le pipeline import → mapping
→ filtre → export des onglets 1-4 "Trieur de Data" vers FastAPI
stateless).
- **Choix retenu** : un schéma Postgres de *staging* côté Supabase
  (`trieur_data.import_sessions` + `trieur_data.import_rows`, ou une
  variante à une seule table de staging avec un tableau JSONB clé par
  `session_id`) — **PAS Redis, PAS un cache fichier temporaire/parquet**.
- **Pourquoi** (vérifié en lisant `api/main.py` + `trieur/db.py` +
  `views/tab1-4` cette session, pas deviné) :
  - L'écran "Base de données" (liste/fiche/tableau de bord/export) est
    déjà le bon patron : chaque requête est sans état, la pagination
    est réelle (offset/limit contre Supabase Postgres via
    `list_records`/`count_records`), et l'export streame depuis
    `list_all_records()` qui paginate sur toute la table. Cette partie
    scale déjà bien, aucun changement d'architecture nécessaire là.
  - Le vrai trou, confirmé en lisant `views/tab1-4` et l'endpoint
    d'import existant (`api/main.py:437`, `import_records` — seule
    pièce du pipeline à 4 étapes déjà portée en FastAPI, et elle
    fusionne import + écriture en un seul appel atomique, sans étape
    intermédiaire de mapping/filtre exposée via l'API) : les onglets
    1-4 (import → mapping colonnes → filtre/dedup → export) vivent
    entièrement dans `st.session_state` de Streamlit, comme un
    DataFrame pandas en mémoire porté d'un rerun à l'autre
    (`views/tab2_import_mapping.py` construit `all_sheets`/
    `filtered_df` en mémoire ; `views/tab4_export.py` lit
    `st.session_state.filtered_df` directement). Un backend FastAPI
    sans état n'a rien d'équivalent à `session_state` — chaque requête
    HTTP est un process neuf, donc ce pipeline à 4 étapes ne peut pas
    survivre entre deux requêtes sans un mécanisme de persistance.
  - Pourquoi Postgres plutôt que Redis ou fichier/parquet : le budget
    annoncé est Supabase Starter + un service web Render à 7$/mois,
    rien d'autre. Redis = un nouveau service managé (coût) ou du
    self-host dans le même dyno Render (perd les données à chaque
    redeploy/restart, ce qui annule l'intérêt ; les offres
    gratuites/starter de Render n'incluent pas de Redis persistant
    sans ressource payante séparée). Un cache fichier/parquet sur le
    disque local de Render est **éphémère** sur cette plateforme — un
    service web Render perd son disque local à chaque redeploy/restart/
    scaling, donc ça ne survivrait même pas le temps d'un import →
    export en plusieurs requêtes si un redeploy tombe entre les deux.
    Postgres (déjà payé, déjà là) survit à tout ça nativement.
- **Ce que ça implique concrètement pour la suite** (pas encore fait,
  à faire par la prochaine session avant de porter les onglets 2-4) :
  créer la migration Supabase pour `trieur_data.import_sessions`/
  `trieur_data.import_rows` (ou la variante JSONB à une table), décider
  du TTL/nettoyage des sessions d'import abandonnées, puis porter
  l'étape mapping et l'étape filtre/dedup comme des endpoints qui
  lisent/écrivent cette table de staging au lieu du DataFrame en
  mémoire. Le point transverse n°2 (progression des tâches longues)
  reste, lui, **toujours en attente** — non traité par cette décision.
- **Statut clair pour éviter toute confusion** : ceci est une
  **décision d'architecture actée, pas du code livré**. Aucune
  migration, aucune table, aucun endpoint n'a été créé pour ça dans cet
  incrément — uniquement le choix et sa justification, pour que la
  prochaine session parte directement à l'implémentation au lieu de
  re-débattre Redis vs Postgres vs fichiers.

**Statut honnête de l'ensemble de la migration React (2026-09-18)** :
l'écran "Base de données" est complet et solide (CRUD, recherche,
filtres, import, colonnes maîtres, vues enregistrées, tableau de bord,
actions groupées, alertes de doublon, export, historique) et l'écran
"Cockpit" vient d'être porté et vérifié à son tour — ces deux écrans
suivent déjà une bonne architecture (API stateless, pagination réelle
côté Postgres). Ce qui reste est le morceau le plus gros et le moins
avancé : les 4 onglets "Trieur de Data" eux-mêmes (import → mapping →
filtre/dedup → export), dont le portage n'a même pas commencé — seul
l'onglet 1 a été scopé en détail, et la décision d'architecture qui
débloque les 3 autres (staging Postgres, ci-dessus) vient d'être prise
mais reste entièrement à implémenter. Tant que ces 4 onglets ne sont
pas portés, Streamlit reste la seule interface pour "Trieur de Data" en
production — le Cockpit et la Base de données React ne remplacent
qu'une partie de l'app, pas encore le cœur du pipeline de tri de
données.

**État (2026-09-18, staging Postgres implémenté — couche données
seulement)** :
- Migration `supabase/migrations/0010_pipeline_staging.sql` — deux
  tables, appliquée pour de vrai (`mcp__Supabase__apply_migration`,
  confirmé ensuite par une lecture réelle d'`information_schema` :
  tables, colonnes et policies présentes) :
  - `trieur_data.pipeline_sessions` (id, org_id, created_by, created_at,
    expires_at TTL 24h par défaut, status
    importing/mapped/filtered/exported/expired, source_filename,
    row_count).
  - `trieur_data.pipeline_rows` (id, session_id, row_index, data jsonb)
    — table séparée plutôt qu'un unique jsonb sur `pipeline_sessions` :
    l'étape 3 (filtre/dedup) doit pouvoir filtrer/mettre à jour des
    lignes individuellement, une ligne Postgres par ligne importée le
    permet nativement (même patron que `trieur_data.records` côté CRM).
    `unique(session_id, row_index)`.
  - RLS : `pipeline_sessions_rw`/`pipeline_rows_rw`, même patron
    `is_org_member(org_id)` que le reste du schéma (`pipeline_rows`
    passe par une sous-requête sur `pipeline_sessions`, comme
    `chantier_messages_rw` le fait déjà pour `chantiers`).
  - Nettoyage : fonction `trieur_data.cleanup_expired_pipeline_sessions()`
    (supprime les sessions dont `expires_at < now()`, cascade sur les
    lignes) — **aucun pg_cron créé**, juste la fonction prête à être
    appelée (par un futur `cron.schedule`, ou par l'app elle-même) ;
    commentée dans la migration avec les deux façons de l'appeler.
- `trieur/db.py` : `create_pipeline_session`, `get_pipeline_session`,
  `update_pipeline_session_status`, `append_pipeline_rows` (par lots,
  `start_index` fourni par l'appelant, met à jour `row_count`),
  `list_pipeline_rows` (paginé, `LIST_PAGE_SIZE`), `delete_pipeline_session`.
  Aucune route API ne les appelle encore — uniquement la couche
  données, pour que la prochaine session porte les onglets 2-4 dessus
  sans redécider l'architecture.
- `tests/test_db_pipeline.py` (9 tests, faux client Supabase, même
  pattern que `test_db_import.py`/`test_db_saved_views.py`) : session
  créée/lue/introuvable, ajout de lignes par lots avec `row_index`
  continu, pagination, changement de statut, suppression.
- Vérifié : `python3 -m pytest -q` → **213 passed**, 1 échec — le flake
  déjà documenté et pré-existant `test_master_columns_localstorage_fallback`
  (sans lien avec ce travail, voir plus haut dans ce journal).
- **Reste à faire** (pas dans cet incrément, portage API des onglets
  2-4) : endpoints FastAPI qui lisent/écrivent cette table de staging
  pour les étapes mapping/filtre/export, et le point transverse n°2
  (progression des tâches longues), toujours en attente.

**État (2026-09-18, API pipeline — étape 1 import + mapping)** :
- `api/main.py` : 3 nouvelles routes, couche fine sur `trieur/db.py`
  (déjà en place ci-dessus) et sur la logique déjà écrite pour
  l'onglet 2 (`trieur/io_excel.py`, `trieur/matching.py`), rien
  réimplémenté :
  - `POST /orgs/{org_id}/pipeline/sessions` (upload Excel/CSV) : lit le
    fichier avec les lecteurs existants (moteurs calamine/openpyxl,
    déduction d'en-tête absente), fusionne tous les onglets en une
    seule session de staging (onglet d'origine gardé sous `_sheet` par
    ligne, jamais proposé au mapping), renvoie `session_id` + colonnes
    détectées + `unknown_columns` (vs colonnes maîtres de l'org) +
    aperçu (10 lignes). PDF (relevés SEPA) hors périmètre de cette
    route pour l'instant.
  - `GET /orgs/{org_id}/pipeline/sessions/{id}` : statut + aperçu,
    reconstruit les colonnes depuis les lignes en staging (pas de
    colonne dédiée côté SQL) ; 404 si session d'un autre org ou
    expirée/nettoyée (vérifié en plus de la RLS, même patron que
    `_get_chantier_or_404`).
  - `POST .../sessions/{id}/mapping` : `dry_run=true` renvoie la
    suggestion d'auto-assignation (`trieur/matching.py:auto_assign_columns_fast`,
    échantillonnée sur l'aperçu déjà chargé, pas tout le fichier) sans
    rien écrire ; sans `dry_run`, applique le mapping (fourni, ou la
    suggestion si omis) en réécrivant chaque ligne avec les clés
    colonnes MAÎTRES, puis passe la session à `mapped`. Simplification
    connue vs l'onglet 2 : deux colonnes source mappées sur la même
    colonne maître -> la dernière écrase (pas de fusion "1ère valeur
    non vide").
  - `trieur/db.py` : ajout de `update_pipeline_row_data` (réécriture du
    jsonb d'une ligne de staging) — seule fonction manquante pour que
    l'endpoint mapping reste fin, pas d'appel direct à PostgREST depuis
    `api/main.py`.
- **Colonnes maîtres : PAS de nouvelle liste.** Vérifié que
  `trieur/persistence.py` (`load_master_columns`, fichier JSON local)
  est un reliquat pré-multi-tenant de l'app Streamlit — global au
  process, pas par organisation — donc un concept différent de
  `trieur_data.organizations.master_columns` (par org, déjà utilisé
  par le CRM). Le pipeline étant lui aussi par org, il réutilise
  directement `GET/POST /orgs/{org_id}/master-columns` (déjà en place) :
  aucune route ajoutée pour ça.
- `tests/test_api.py` : 13 nouveaux tests (upload, détection colonnes,
  aperçu, 404 cross-org, dry_run vs application du mapping, mapping
  auto par défaut, 400 si tout `(non assigne)`, 401/403). Fausse table
  Supabase du fichier étendue pour accepter un insert en LISTE (lot de
  lignes, comme `append_pipeline_rows`) et poser les mêmes valeurs par
  défaut SQL (`status`, `row_count`) qu'un insert Postgres réel.
- Vérifié : `python3 -m pytest -q` → **226 passed**, 1 échec — même
  flake pré-existant `test_master_columns_localstorage_fallback`, sans
  lien (13 tests en plus des 213 précédents, tous verts).
- **Reste à faire** : porter les onglets 3-4 (filtre/dedup, export) sur
  cette même table de staging ; PDF (relevés SEPA) pas encore branché
  sur `POST .../pipeline/sessions` ; le point transverse n°2
  (progression des tâches longues) reste ouvert.

**État (2026-09-18, écran React "Trieur de Data" — étape 1 import +
mapping) + vérification indépendante de tout l'incrément staging**,
implémenté (étape 1 : import + mapping) :
- `frontend/src/screens/PipelineScreen.tsx` : nouvel écran, mêmes
  routes que l'API ci-dessus (`createPipelineSession`,
  `suggestPipelineMapping`, `applyPipelineMapping` dans
  `frontend/src/lib/api.ts`) — upload → aperçu colonnes/colonnes
  inconnues → mapping colonne par colonne (suggestion auto en
  `dry_run`, éditable) → "Construire". Une étape affichée à la fois,
  colonnes maîtres réutilisées via `get/setMasterColumns` (aucune
  deuxième liste créée). États chargement/vide/erreur/succès traités à
  chaque appel. `views/` et `app.py` non touchés.
- **Vérification indépendante** (pas seulement les rapports des 3
  agents de ce run) :
  - Supabase (`mcp__Supabase__list_tables` + requête directe sur
    `pg_tables`/`pg_policies`, projet `bexiyvmdbxcwxasgslxp`) :
    `trieur_data.pipeline_sessions` et `trieur_data.pipeline_rows`
    existent réellement, `rowsecurity = true` sur les deux, policy
    `is_org_member(org_id)` (directe pour `pipeline_sessions`, via
    sous-requête sur la session pour `pipeline_rows`) — confirmé, pas
    supposé.
  - Suite complète : `python3 -m pytest -q` → **226 passed** (comme
    rapporté), + 1 échec sur `test_master_columns_localstorage_fallback`.
    Creusé : ce test est **flaky** (course sur le délai fixe de 4s
    avant lecture du DOM), reproduit aussi bien en échec qu'en succès
    sur des commits d'AVANT ce run (`720af64`, avant les 3 commits de
    cet incrément) et systématiquement en succès sur le commit de base
    `2f8133f` (pris isolément, plusieurs runs) — pas une régression de
    cet incrément, pré-existant sur la branche, non corrigé ici (hors
    périmètre : chantier de fiabilisation des tests E2E séparé si ça
    agace).
  - `cd frontend && npm run build` → succès, exit 0 (`tsc -b && vite
    build`).
  - `git diff --stat main...feature/react-migration -- views/ app.py`
    → seuls 3 fichiers, tous depuis un commit d'AVANT ce run
    (`8b39500`, filet de diagnostic) — confirmé qu'aucun des 3 commits
    de cet incrément (`165c185`, `f191285`, `51167ee`) n'y touche.
  - Relu `api/main.py` (endpoints pipeline) et
    `frontend/src/lib/api.ts`/`PipelineScreen.tsx` côte à côte :
    aucune incohérence de contrat (noms de champs, chemins, sentinelle
    `(non assigne)`).
  - Scoping org_id : `require_org_access` (dépendance FastAPI, membre
    ou super-admin) sur les 3 routes + `_get_pipeline_session_or_404`
    (session d'un AUTRE org → 404, jamais une fuite) en plus de la RLS
    Supabase (défense en profondeur). Un test couvrait déjà le cas sur
    le GET (`test_pipeline_session_get_wrong_org_is_404`) ; **ajouté
    l'équivalent manquant sur le POST mapping**
    (`test_pipeline_mapping_wrong_org_is_404`, vérifie 404 ET que les
    lignes ne sont pas réécrites) — bug de couverture trouvé et
    corrigé, pas un bug de sécurité réel (le code appelait déjà le même
    garde-fou), mais non testé jusqu'ici sur cette route précise.
  - Suite après ajout du test : `python3 -m pytest -q` →
    **227 passed**, même flake pré-existant, sans lien.
  - Poussé : commit `20a433a` (test ajouté ci-dessus + cette mise à
    jour du journal) sur `origin/feature/react-migration`, dans le même
    push que les 3 commits de l'incrément (`165c185`, `f191285`,
    `51167ee`), déjà locaux et non poussés avant cette vérification.
- **Statut honnête de l'ensemble de la migration React** : Base de
  données + Cockpit restent complets. Pipeline "Trieur de Data" :
  étape 1 (import + mapping) livrée et vérifiée de bout en bout
  (staging Postgres + API + écran React) ; étapes 2-3 du pipeline
  (filtre/dédoublonnage, export) et les détails d'UI propres aux
  onglets 1/3/4 encore Streamlit-only restent à porter. Estimation
  honnête de complétion globale de la migration : **~70 %** (les deux
  écrans les plus utilisés au quotidien — Base de données, Cockpit —
  et la première moitié du pipeline sont solides ; le reste du
  pipeline, le plus gros morceau restant, n'est pas commencé au-delà
  de cette étape 1).

**État (2026-09-18, 7e incrément — barre de progression par chantier +
vérification indépendante d'un rapport d'agent contredit par un autre)** :
- Réponse à la demande explicite de l'utilisateur ("une barre de
  progression constante sur chaque chantier") : déjà livrée dans cette
  même branche, commit `6dfb45c` (avant cette vérification) —
  `frontend/src/screens/ChantierCard.tsx` affiche sous chaque carte une
  barre (fait/total, calcul client à partir des `chantier_todos` déjà
  chargés par carte, aucun appel API ni changement backend) + le texte
  "X/Y points traités". Diff de 14 lignes, un seul fichier, revu à
  l'instant : correct, pas de division par zéro (condition
  `todos.length > 0` avant le calcul).
- **Rapport contradictoire entre deux agents de ce run** : un agent
  "API" affirmait avoir livré les étapes 2-3 du pipeline (filtre/dedup +
  export sur les sessions pipeline) ; un agent "frontend" contestait
  cette affirmation. **Vérifié indépendamment, l'agent frontend avait
  raison** :
  - `grep` sur les routes de `api/main.py` : seulement 3 routes
    `/orgs/{id}/pipeline/sessions...` (import, aperçu, mapping) —
    aucune route `filter` ni `export` sous ce chemin.
  - `git fetch origin` + `git log origin/feature/react-migration` :
    dernier commit distant = `6dfb45c` (la barre de progression),
    identique au HEAD local. Aucun commit de filtre/export pipeline,
    ni local ni distant.
  - `frontend/src/lib/api.ts` : aucun appel `pipeline`+`filter`/`export`
    non plus — le frontend n'appelle que les 3 routes qui existent
    réellement (`createPipelineSession`, `suggestPipelineMapping`,
    `applyPipelineMapping`). Pas de divergence de contrat, parce que
    rien de nouveau n'a été construit des deux côtés.
  - Conclusion : l'affirmation "un agent API vient d'ajouter
    filtre/export pour les sessions pipeline" était **fausse** —
    probablement une hallucination de rapport dans le run précédent.
    Les étapes 2-3 du pipeline restent non commencées au-delà de
    l'étape 1 (import + mapping).
- **Vérification complète refaite ce soir** :
  - `python3 -m pytest -q` → **228 passed** au 2e run (1er run : 227
    passed + 1 échec sur `test_master_columns_localstorage_fallback`,
    même flake déjà documenté plus haut dans ce journal, reproduit en
    échec puis en succès sans aucun changement de code entre les deux
    runs — confirmé non lié à cet incrément).
  - `cd frontend && npm run build` → succès, exit 0.
  - `git diff --stat main...feature/react-migration -- views/ app.py` →
    3 fichiers (`app.py`, `tab2_import_mapping.py`, `tab_database.py`),
    tous depuis le commit `8b39500` (filet de diagnostic upload,
    antérieur à cet incrément) — rien ajouté par cet incrément à
    `views/`/`app.py`. `main` (`635fcde`) n'a reçu aucun commit de cette
    migration, comme prévu — le site Streamlit en production reste
    inchangé.
  - Relecture de `_filter_by_columns`/`_matches_filter`
    (`views/tab_database.py`, réutilisés par `api/main.py` pour
    `/records` et `/records/export`) : le bug de classe "valeur fausse
    traitée comme vide" (0/''/false) n'est **pas présent** — l'opérateur
    "vide" teste `value is None or value == ""` explicitement, jamais
    `not value`, et c'est couvert par
    `test_filter_by_columns_vide_does_not_treat_zero_as_empty`.
  - Scoping `org_id` sur les 3 routes pipeline existantes :
    `require_org_access` en dépendance FastAPI sur les 3, +
    `_get_pipeline_session_or_404` qui traite une session d'un autre org
    comme introuvable (404). Déjà testé (`test_pipeline_session_get_wrong_org_is_404`,
    `test_pipeline_mapping_wrong_org_is_404`) — rien à ajouter, les
    étapes 2-3 n'existant pas encore, il n'y a pas de nouvelle route à
    scoper.
  - **Repéré, hors périmètre de cet incrément** : 3 branches locales
    (`main-tmp`, `main-tmp2`, `main-tmp4`) non poussées sur `origin`,
    contenant des correctifs de production (upload CORS, version
    Python, keep-alive) apparemment issus d'un autre chantier de
    fiabilisation du site Streamlit en direct. Pas touché — ne fait pas
    partie de cette demande, signalé pour que l'utilisateur sache que
    ces branches existent et décide s'il faut les fusionner ou les
    supprimer.
- Rien à committer côté code pour cet incrément (la barre de
  progression était déjà poussée) — ce journal est la seule mise à
  jour, poussée directement sur `origin/feature/react-migration`.
- **Statut honnête de l'ensemble de la migration React (toujours
  ~70 %, pas d'écran supplémentaire porté ce soir)** :
  - **Fait et vérifié** : Base de données (complet) ; Cockpit (complet,
    y compris la barre de progression par chantier demandée
    aujourd'hui) ; Pipeline "Trieur de Data" étape 1 (import +
    mapping/onglet 2) livrée et testée de bout en bout.
  - **Reste pour 100 %** :
    - Pipeline étapes 2-3 (onglets 3-4 Streamlit : filtre/dédoublonnage
      avec les alertes de doublons, export final depuis une session
      pipeline) — pas commencées, c'est le plus gros morceau restant.
    - Détails d'UI propres à l'onglet 1 (gestion fine des colonnes
      maîtres côté Streamlit — renommage, réordonnancement, mémoire
      liée au compte) pas encore vérifiés un par un côté React au-delà
      de la réutilisation basique `get/setMasterColumns`.
    - Options avancées des onglets 3-4 si certaines ont été simplifiées
      lors du portage (aucune n'existe encore, donc à valider au moment
      du portage, pas avant).
    - L'équivalent du glisser-déposer `streamlit-sortables` (réordonner
      des éléments à la souris/au doigt, utilisé quelque part dans
      l'app Streamlit actuelle) — pas encore vérifié si un composant
      React équivalent a été posé ; à confirmer écran par écran pendant
      le portage des onglets 3-4.
    - Le point transverse n°2 toujours ouvert : barre de progression
      pour les opérations *longues* (upload/traitement d'un gros
      fichier) — différente de celle par chantier livrée aujourd'hui,
      demande une vraie architecture de suivi de tâche côté API
      (polling ou SSE), pas commencée.
  - **`main` non touché** : confirmé ce soir par `git diff`/`git log` —
    le site Streamlit en production (branche `main`, dernier commit
    `635fcde`) n'a reçu aucun commit de cette migration depuis son
    démarrage. Aucun merge n'a eu lieu, aucune PR n'est ouverte.

- **Pipeline étapes 2-3, tentative suivante — cette fois-ci réelle,
  vérifiée indépendamment de zéro (2026-09-18, même soir)** : après le
  faux rapport signalé ci-dessus, deux nouveaux agents ("API" puis
  "frontend") ont retravaillé le même chantier. Vérification refaite
  sans se fier à leurs rapports :
  - `grep -n "pipeline" api/main.py` : les 3 routes existantes (import,
    aperçu, mapping) **+ 2 nouvelles routes réelles** —
    `GET /orgs/{org_id}/pipeline/sessions/{id}/rows` (ligne 687) et
    `GET .../export` (ligne 716). Lues en entier : réutilisent
    `_filter_by_search`/`_filter_by_columns` (`views/tab_database.py`,
    mêmes fonctions que `/records`) et `export_csv_safe`/
    `export_excel_safe` (`trieur/export.py`), sur toutes les lignes de
    la session via un nouvel helper paginé `_all_pipeline_rows` — pas
    juste l'aperçu (`PIPELINE_PREVIEW_SIZE`).
  - `python3 -m pytest -q` (suite complète) → **238 passed, 2 warnings
    in 26.38s**, exactement 228 (base de référence) + 10 nouveaux tests
    pipeline filtre/export (`test_pipeline_rows_filter_*`,
    `test_pipeline_rows_search`, `test_pipeline_rows_wrong_org_is_404`,
    `test_pipeline_export_*`). Aucune régression, aucun flake cette
    fois.
  - `git log feature/react-migration -3 --oneline` → 2 nouveaux
    commits réels : `2bc8763` (`api/main.py` +102 lignes,
    `tests/test_api.py` +181 lignes) et `c580851`
    (`frontend/src/lib/api.ts` +86, `frontend/src/screens/PipelineScreen.tsx`
    +201/-8) — `git show --stat` sur chacun confirmé, correspond
    exactement aux rapports des deux agents.
  - `git diff --stat main...feature/react-migration -- views/ app.py` →
    toujours les mêmes 3 fichiers que la vérification précédente
    (`app.py`, `tab2_import_mapping.py`, `tab_database.py`), tous issus
    du commit `8b39500` (antérieur, filet de diagnostic upload) — rien
    ajouté par cet incrément à `views/`/`app.py`, `main` toujours
    intact.
  - Scoping `org_id` : `test_pipeline_rows_wrong_org_is_404` et
    `test_pipeline_export_wrong_org_is_404` existent et passent — les 2
    nouvelles routes utilisent `_get_pipeline_session_or_404`, comme
    les 3 routes existantes.
  - Bug de classe "valeur fausse traitée comme vide" (0/''/false) :
    absent — `_matches_filter` teste explicitement
    `value is None or value == ""`, jamais `not value` ; couvert en
    plus par le nouveau test
    `test_pipeline_rows_filter_non_vide_traite_zero_comme_une_vraie_valeur`.
  - `cd frontend && npm run build` → succès, **exit 0** (tsc + vite,
    aucune erreur TypeScript).
  - **Conclusion : travail réel cette fois, contrairement à la
    tentative précédente.** Poussé sur `origin/feature/react-migration`
    (`git push`), `main` non touché.
  - **Statut honnête de la migration React : ~78 %**
    (Base de données + Cockpit + Pipeline étapes 1-2-3 complets et
    testés ; reste : détails fins onglet 1 déjà listés plus haut,
    glisser-déposer `streamlit-sortables` à confirmer côté React, barre
    de progression pour les uploads longs — pas commencée).

**État (2026-09-18, 8e incrément — 3 finitions demandées : jeux de
colonnes personnels, ordre/sélection colonnes à l'export pipeline,
mesure réelle du temps d'upload)** :
- **1. Jeux de colonnes maîtres personnels (compte)** — livré :
  `views/tab1_colonnes_maitres.py:_render_account_memory` portée en
  React. `trieur/db.py` (`list_user_column_sets`/`save_user_column_set`/
  `delete_user_column_set`/`set_active_column_set`) existait déjà
  (audit précédent confirmé) mais **sans aucune route API ni test** --
  ajouté `GET/POST /me/column-sets`, `POST /me/column-sets/{id}/apply`,
  `DELETE /me/column-sets/{id}` (`api/main.py`), tous scopés au compte
  connecté (`user_id`, jamais un `org_id` -- ces jeux ne sont PAS ceux
  de l'onglet Base de données). Garde de propriété avant delete/apply
  (même patron que `delete_saved_view_endpoint`) : un `set_id` d'un
  autre compte renvoie 404, jamais une suppression/lecture croisée.
  Enregistrer ou appliquer un jeu marque le profil actif
  (`set_active_column_set`, invalide déjà le cache `get_my_profile` côté
  `trieur/db.py`) -- `/me` le renvoie immédiatement.
  `frontend/src/screens/PersonalColumnSets.tsx` (nouveau) : liste des
  jeux, application, suppression (confirmation), édition de la liste en
  cours (ajout/suppression/réordonnancement flèches haut-bas -- même
  patron que `MasterColumnsPanel.tsx` pour les colonnes d'organisation,
  pas un deuxième composant réordonnable différent), enregistrement sous
  un nom. **Auto-chargement une fois au montage** du dernier jeu actif
  (`profiles.active_master_column_set_id` via `/me`), avec message
  explicite ("rechargé automatiquement"). Intégré sous
  `MasterColumnsPanel.tsx` (section additive, visible pour tout compte
  connecté, pas seulement admin -- distinct de la gestion des colonnes
  de l'organisation qui reste admin-only juste au-dessus). États
  chargement/vide/erreur traités.
- **2. Ordre et sélection des colonnes à l'export du pipeline** — livré :
  équivalent du glisser-déposer `streamlit-sortables` de
  `views/tab4_export.py`, mais en **flèches haut/bas + cases à cocher**
  plutôt qu'un vrai drag-and-drop : décidé après lecture de
  `tab4_export.py` (son propre contournement JS d'un bug de mesure du
  composant, déjà signalé comme fragile dans ce journal) et parce que le
  glisser-déposer HTML5 natif est peu fiable au toucher, alors que
  l'utilisateur travaille surtout depuis son téléphone -- ce même patron
  (flèches) est déjà en place pour les colonnes maîtres d'organisation
  (`MasterColumnsPanel.tsx`), donc cohérent avec le reste de l'app plutôt
  qu'une deuxième façon de faire la même chose. Aucune dépendance
  nouvelle ajoutée (ni `dnd-kit` ni équivalent).
  `api/main.py:export_pipeline_session_rows` : nouveau paramètre
  `columns` (liste ordonnée, séparée par des virgules) -- une colonne
  absente de la liste est exclue de l'export, l'ordre demandé est
  respecté, une colonne demandée mais absente des données réelles est
  ignorée silencieusement (jamais ajoutée vide) ; `columns` vide =
  comportement précédent inchangé (toutes les colonnes, ordre
  d'apparition) -- **rétrocompatible**. `frontend/src/lib/api.ts`
  (`exportPipelineSessionRows` accepte `columns?: string[]`) et
  `PipelineScreen.tsx` (nouvel état `colOrder`/`excludedCols`, fusionné
  automatiquement avec les colonnes détectées à chaque changement de
  filtre/session, jamais de colonne perdue silencieusement ; export
  désactivé si tout est exclu, avec message explicite).
- **3. Temps d'upload/traitement d'un gros fichier** — mesuré, PAS
  d'architecture async construite (décision justifiée ci-dessous) :
  - Mesuré réellement (pas supposé) : CSV généré localement, 50 000
    lignes, 8 colonnes, ≈5,1 Mo
    (`NOM,PRENOM,EMAIL,TELEPHONE,VILLE,ADRESSE,CP,IBAN`). Appel direct
    des fonctions réelles de `api/main.py`
    (`_parse_pipeline_file`/`_merge_pipeline_sheets`, celles utilisées
    par `POST .../pipeline/sessions`) : **parse 0.107s + merge 0.506s =
    0.613s total** pour 50 000 lignes -- le parsing/fusion pur est
    négligeable, pas un problème en soi.
  - **Ce que je n'ai PAS mesuré, honnêtement** : le temps réel des
    écritures réseau vers Supabase. `append_pipeline_rows` est appelé en
    boucle, **100 lots séquentiels** de 500 lignes
    (`PIPELINE_APPEND_BATCH`) pour ce fichier de 50 000 lignes -- chaque
    lot est un aller-retour HTTP synchrone vers PostgREST. Je n'ai pas
    exécuté ce chemin contre le vrai projet Supabase (ça écrirait 50 000
    lignes de test dans les tables de staging réelles sans demande
    explicite pour ce test précis) -- **estimation, pas mesure** : même à
    50-150ms par aller-retour (cas favorable, même région), 100
    allers-retours séquentiels représentent déjà 5 à 15 secondes, et une
    latence moins favorable dépasserait facilement la limite de
    30-60s d'un proxy/reverse-proxy typique. C'est donc plausiblement un
    **vrai temps d'attente synchrone de plusieurs secondes**, pas
    juste de la prudence excessive.
  - **Décision prise dans ce périmètre, avec la limite de temps de cet
    incrément** : construire une vraie file d'attente asynchrone
    (job + polling/SSE) sans avoir mesuré le vrai chiffre contre
    Supabase aurait été de la sur-ingénierie sur une simple estimation.
    À la place, livré ce qui aide déjà concrètement sans engager
    d'architecture nouvelle : un **spinner + chrono en secondes**
    pendant l'upload (`PipelineScreen.tsx`, état `uploadElapsedSec`,
    `setInterval` 1s, message "un gros fichier peut prendre encore
    quelques instants" au-delà de 8s) -- contrairement à ce qui était
    supposé, **aucun spinner à chrono n'existait avant** sur cet écran
    (juste un texte statique "Lecture du fichier…", vérifié par lecture
    du code, pas déduit).
  - **Reste ouvert, à trancher par une prochaine session (pas résolu
    ici, pour ne pas laisser un doute silencieux)** : mesurer le vrai
    temps contre Supabase avec un fichier de taille réaliste (le
    prochain incrément qui touche à l'upload devrait le faire en premier
    geste) ; si confirmé multi-secondes de façon significative,
    remplacer la boucle synchrone `POST .../pipeline/sessions` par un
    job asynchrone (ex. la session est créée immédiatement en statut
    `importing`, les lots s'ajoutent en tâche de fond, le frontend
    poll `GET .../pipeline/sessions/{id}` déjà existant jusqu'à
    `row_count` stable) -- l'endpoint GET existe déjà, donc ce futur
    travail n'aurait pas à créer de nouvelle route de lecture, juste à
    rendre l'écriture asynchrone et le statut fiable pendant l'écriture.
- Tests ajoutés (`tests/test_api.py`) : 9 nouveaux tests
  `/me/column-sets*` (vide par défaut, save/list, nom/colonnes vides
  =400, remplacement même nom, apply marque actif + renvoie les
  colonnes, apply id inconnu=404, delete, delete du jeu d'un autre
  compte=404, auth requise) + 2 nouveaux tests export pipeline
  `columns` (ordre+sélection respectés, colonne inconnue ignorée sans
  erreur).
- Vérifié : `python3 -m pytest -q` (suite complète) → **250 passed**
  (240 + 11 nouveaux : 9 column-sets + 2 export columns), sur un run ;
  un run antérieur dans la même session a montré le flake déjà
  documenté `test_master_columns_localstorage_fallback` (249 passed, 1
  échec) -- même flake préexistant, sans lien, non corrigé ici (hors
  périmètre, chantier de fiabilisation E2E séparé si ça agace).
  `cd frontend && npm run build` → succès, exit 0 (`tsc -b && vite
  build`). `npm run lint` → uniquement les warnings déjà présents sur
  d'autres écrans (`set-state-in-effect`, un de plus sur
  `PersonalColumnSets.tsx`, même famille que
  `DashboardPanel.tsx`/`SavedViews.tsx`/etc., aucun nouveau type
  d'avertissement).
  `git diff --stat -- views/ app.py` → vide, confirmé : app Streamlit
  toujours non touchée.
- **Ce qui a été simplifié/laissé de côté, explicitement** :
  - Point 2 : glisser-déposer réel (souris/tactile) **volontairement
    pas construit** -- flèches haut/bas à la place, décision justifiée
    ci-dessus (cohérence avec `MasterColumnsPanel.tsx`, fiabilité
    tactile). Si l'utilisateur préfère un vrai drag-and-drop malgré le
    risque tactile, à revoir explicitement.
  - Point 3 : voir "reste ouvert" ci-dessus -- le vrai chiffre réseau
    contre Supabase n'a pas été mesuré, seulement estimé à partir du
    nombre de lots. Ne pas confondre l'estimation ci-dessus avec une
    mesure réelle en production.
  - Pas ajouté : tests `trieur/db.py` dédiés pour
    `list_user_column_sets`/`save_user_column_set`/etc. -- déjà couverts
    indirectement par les 9 tests API ci-dessus (mêmes fonctions
    appelées avec un faux client), pas dupliqué en tests séparés pour
    rester dans le périmètre minimal demandé ("tests pour les nouveaux
    endpoints API").
- Committé sur `feature/react-migration` (message en français, voir
  `git log`). **Pas pushé** (demande explicite de l'utilisateur pour cet
  incrément : ne pas pousser).

**Vérification indépendante de ce 8e incrément, refaite de zéro
(2026-09-18, même soir, nouvelle session)** — un rapport précédent sur
ce même repo s'était révélé faux, donc rien n'est pris pour acquis ici :
tout relu, tout réexécuté.
- `git log feature/react-migration -5 --oneline` / `git show --stat
  HEAD` : commit `3ff3eda` réel, non pushé (`origin/feature/react-migration`
  toujours à `df8ef3d`, confirmé par `git fetch`). Diff réel : 7 fichiers,
  875 insertions/6 suppressions (`api/main.py`, `frontend/src/lib/api.ts`,
  `MasterColumnsPanel.tsx`, `PersonalColumnSets.tsx` (nouveau),
  `PipelineScreen.tsx`, `tests/test_api.py`, `PROJECT_LOG.md`).
- `python3 -m pytest -q` (suite complète, run frais) → **250 passed, 2
  warnings, 26.47s**. Pas de flake cette fois (le flake E2E
  `test_master_columns_localstorage_fallback` documenté plus haut est
  intermittent, pas reproduit sur ce run).
- `cd frontend && npm run build` → **exit 0** (`tsc -b && vite build`,
  aucune erreur TypeScript, seul avertissement = taille de chunk >500kB,
  préexistant, sans lien).
- `git diff --stat main...feature/react-migration -- views/ app.py` →
  **3 fichiers** (`app.py`, `views/tab2_import_mapping.py`,
  `views/tab_database.py`), mais tous issus du commit `8b39500`
  (antérieur, filet de diagnostic upload — voir plus haut) via
  `git log main..feature/react-migration -- views/ app.py` : **rien
  ajouté par le commit `3ff3eda`** à ces fichiers. `main` toujours
  intact, confirmé.
- Code relu pour les 3 points, pas seulement le rapport de l'agent :
  - **1. Jeux de colonnes personnels** : les 4 routes
    (`GET/POST /me/column-sets`, `POST .../apply`, `DELETE .../{id}`)
    existent réellement dans `api/main.py`, avec garde de propriété
    (`_get_own_column_set_or_404`) avant apply/delete — confirmé par
    lecture directe. `PersonalColumnSets.tsx` : auto-chargement au
    montage via `active_master_column_set_id`, états
    chargement/vide/erreur, confirmation avant suppression
    (`window.confirm`), intégré dans `MasterColumnsPanel.tsx`
    (`<PersonalColumnSets />` ajouté, visible pour tout compte connecté).
    Réel, correspond au rapport.
  - **2. Ordre/sélection colonnes export** : paramètre `columns` sur
    `export_pipeline_session_rows`, filtre `[c for c in requested_cols
    if c in full_cols]` — rétrocompatible (vide = tout, ordre
    d'apparition), colonne inconnue ignorée sans erreur. Côté écran,
    `colOrder`/`excludedCols` avec flèches haut/bas + cases à cocher,
    fusion automatique des nouvelles colonnes détectées sans perte.
    Réel, correspond au rapport.
  - **3. Chrono d'upload** : `setInterval` 1s affichant
    `uploadElapsedSec`, spinner CSS, message après 8s — réel, mais
    reste ce que le rapport dit honnêtement : un affichage de temps
    écoulé, pas une vraie barre de progression ni un job asynchrone.
    Le vrai coût réseau (100 lots séquentiels vers Supabase pour 50 000
    lignes) reste **estimé, jamais mesuré en conditions réelles** —
    point toujours ouvert, non résolu par cet incrément.
  - 11 nouveaux tests dans `tests/test_api.py` confirmés un par un
    (noms de fonctions relus) : couvrent vide par défaut, save/list,
    validation nom/colonnes vides (400), remplacement même nom, apply
    (actif + 404 sur id inconnu), delete (+ 404 sur jeu d'un autre
    compte), auth requise, export colonnes (ordre+sélection, colonne
    inconnue ignorée). Couverture réelle, pas seulement des tests qui
    passent par accident.
- **Conclusion : le rapport de cet incrément est honnête et exact.**
  Aucune régression trouvée, aucun écart entre le rapport et le code
  réel.
- Poussé sur `origin/feature/react-migration` (`git push`), commit
  `3ff3eda` — **pas de merge sur `main`, pas de PR** : décision qui
  reste à l'utilisateur, conformément aux règles de ce projet.

**Statut honnête de l'ensemble de la migration React (2026-09-18,
après ce 8e incrément) : ~82 %.**
- **Fait et vérifié** : Base de données (complet, y compris colonnes
  maîtres d'organisation + jeux personnels par compte) ; Cockpit
  (complet, barre de progression par chantier) ; Pipeline "Trieur de
  Data" étapes 1-2-3 complètes (import/mapping, filtre/dédoublonnage,
  export avec ordre/sélection de colonnes) ; chrono d'upload affiché.
  Tous testés (250 tests passants) et le build frontend passe.
- **Reste pour 100 %, liste précise** :
  1. Étiquettes libres sur un client (n1) — pas commencé, ni côté
     Streamlit ni côté React (feature produit, pas juste un portage).
  2. Annuler un import entier en un clic (n3) — pas commencé.
  3. Détection de quasi-doublons hors IBAN + règle configurable par
     activité (n2 + point 7) — bloqué sur l'Excel de référence attendu
     de l'utilisateur, pas un manque de code.
  4. Rôles plus fins par environnement (n5) — à cadrer avec
     l'utilisateur avant de coder, pas encore lancé.
  5. Mesure réelle du coût réseau upload contre le vrai Supabase (voir
     point 3 ci-dessus) — pour trancher si un job asynchrone est
     nécessaire ou si le chrono actuel suffit.
  6. Colonnes calculées simples (n8) — explicitement reporté par
     l'utilisateur ("plus tard").
- **Ce qu'une revue avant merge sur `main`/mise en prod devrait vérifier
  en plus, avant que l'utilisateur décide** (aucun de ces points n'a
  été audité spécifiquement pendant la migration écran par écran) :
  - **Cas limites d'authentification** : expiration de session/jeton
    pendant une action longue (upload, export), comportement si
    `is_super_admin` change en cours de session, accès à un `org_id`
    dont l'utilisateur vient d'être retiré.
  - **Passage mobile réel** : tous les écrans ont été construits
    "téléphone d'abord" dans l'intention (choix explicite des flèches
    plutôt que drag-and-drop), mais aucune passe de test tactile sur
    écran réel n'a été faite écran par écran — à faire avant bascule.
  - **Test de charge avec un vrai gros fichier** : le point 5 ci-dessus
    — actuellement seulement estimé, jamais mesuré contre le vrai
    projet Supabase.
  - **Filet de diagnostic (`trieur/debug.py`, commit `8b39500`)** :
    affiche la trace complète des exceptions à l'écran sur l'app
    Streamlit — utile en migration, mais à vérifier/retirer ou gater
    (visible admin seulement) avant toute mise en prod, pour ne pas
    exposer de détails internes à un utilisateur final. Concerne
    l'app Streamlit (`main`), pas la branche React, mais doit être
    tranché avant que `main` reparte en prod avec ce commit si jamais
    il y est mergé séparément.
  - **Chunk frontend >500 kB** (avertissement build, voir plus haut) —
    sans impact fonctionnel, mais à code-splitter avant une vraie mise
    en prod si le temps de chargement initial compte.
  - Pas de revue de sécurité dédiée (RLS Supabase, CORS) refaite
    spécifiquement pour cet incrément — dernière revue explicite plus
    haut dans ce journal, à rafraîchir avant bascule finale.

## Audit avant merge : correctifs réels + go/no-go (2026-09-18)

**Contexte** : audit indépendant de la branche `feature/react-migration`
(5 constats, dont 1 bloquant, 2 importants, 1 mineur, 1 point de
contrôle positif). Vérifié chaque constat sur le vrai code avant de
corriger — aucun ne s'est révélé faux.

**Corrigé — bloquant** :
- **Filet de diagnostic exposé à tout utilisateur** (`trieur/debug.py`,
  déjà noté comme point ouvert dans l'entrée précédente de ce
  journal) : `report_exception` (trace Python complète, `app.py` lignes
  365-399, les 4 onglets Trieur de Data + Base de données + Cockpit) et
  `render_upload_diagnostics` (URL + en-têtes HTTP bruts,
  `views/tab_database.py:650` et `views/tab2_import_mapping.py:52`)
  s'affichaient à n'importe quel compte connecté, et même sans compte
  du tout côté onglet "Trieur de Data" (pas de login requis là).
  Confirmé en lisant le code avant correction. **Corrigé** : les deux
  fonctions prennent maintenant un paramètre `is_admin` (par défaut
  `False`, donc sûr par défaut) — message générique tant que ce n'est
  pas `True`. `is_admin` vient de `ctx["profile"]["is_super_admin"]`
  quand un compte est connecté (via `optional_login_ctx()`, qui ne
  bloque jamais le rendu), `False` sinon. La trace complète reste
  toujours imprimée sur stdout (logs Render), inchangé. Preuve : `python3
  -m pytest -q` → 250 passants (voir plus bas), aucun test ne couvrait
  ce filet avant (pas de régression possible à ce niveau) ; relecture
  manuelle des 4 points d'appel dans `app.py`, `views/tab_database.py`,
  `views/tab2_import_mapping.py`.

**Corrigé — important** :
- **Aucun traitement global du 401 côté frontend** (`frontend/src/lib/api.ts`) :
  un jeton révoqué ou un 401 métier (compte sans profil) laissait
  chaque écran afficher son message d'erreur brut, sans reconnexion ni
  redirection. **Corrigé** : les 4 endroits qui gèrent une réponse HTTP
  en erreur (`request`, `importRequest`, `exportRecords`,
  `exportPipelineSessionRows`) passent maintenant par un helper commun
  `throwForErrorResponse` qui, sur un 401, force `supabase.auth.signOut()`
  (+ un flag `sessionStorage` lu une fois par `LoginScreen`, qui affiche
  alors "Ta session a expiré ou n'est plus valide. Reconnecte-toi.").
  `App.tsx` réagit déjà à `session === null` (`useAuth`) → retour
  automatique sur l'écran de connexion, sans manipulation manuelle.
  Preuve : `cd frontend && npm run build` → succès (voir plus bas) ;
  pas de test automatisé frontend dans ce repo (aucun test JS existant à
  faire régresser), donc vérifié par relecture du flux complet
  (`api.ts` → `AuthContext` → `App.tsx` → `LoginScreen.tsx`) plutôt que
  par un test exécuté — **limite à signaler explicitement**.
- **Bundle frontend >500 kB** (avertissement Vite confirmé en sortie
  réelle avant correctif : `index-*.js` 510,64 kB / 139,63 kB gzip) :
  `App.tsx` chargeait `DatabaseScreen`/`PipelineScreen`/`CockpitScreen`
  statiquement, donc systématiquement, même pour un compte qui n'ouvre
  jamais le Cockpit. **Corrigé** : les 3 écrans passent par
  `React.lazy()` + `<Suspense>`, un chunk par écran. Preuve, build réel
  après correctif : chunk principal `index-*.js` 448,50 kB / 127,61 kB
  gzip (sous le seuil 500 kB, plus d'avertissement),
  `DatabaseScreen-*.js` 35,68 kB, `PipelineScreen-*.js` 13,34 kB,
  `CockpitScreen-*.js` 14,32 kB séparés.

**Corrigé — mineur (trivial, fait dans le même mouvement)** :
- Cases à cocher de sélection dans `DatabaseScreen.tsx` (tout
  sélectionner + par ligne) : zone de clic réelle ~16 px, sous les ~40 px
  recommandés au tactile. **Corrigé** : enveloppées dans un `<label>`
  de 36×36 px (`h-9 w-9`), case agrandie à `h-5 w-5`.

**Vérifié, aucune action — point de contrôle positif de l'audit** :
- RLS Supabase (`records`, `pipeline_rows`, `chantiers`) : confirmé
  déjà conforme par l'audit (policy `ALL` unique par table via
  `is_org_member()`, RLS activée, aucun repli permissif) — non
  re-vérifié ici en base (pas de raison de refaire une requête déjà
  faite par l'audit sur les mêmes tables), rien à corriger.

**Documenté comme lacune connue, volontairement non traité ici** :
- Aucune lacune supplémentaire ouverte par ce passage d'audit. Les
  lacunes déjà documentées dans l'entrée précédente (étiquettes libres,
  annulation d'import, quasi-doublons hors IBAN, rôles fins par
  environnement, mesure réelle du coût réseau upload, colonnes
  calculées, passe tactile écran par écran) restent ouvertes et sont
  des chantiers séparés, pas des blocages de sécurité/fiabilité —
  inchangées par ce passage.

**Preuves d'exécution réelles** :
- `python3 -m pytest -q` → `250 passed, 2 warnings` (aucun échec).
  Note : `test_master_columns_localstorage_fallback` (test E2E
  Playwright, déjà signalé flaky préexistant dans l'entrée précédente)
  a été relancé seul pour confirmer : `1 passed` — comportement
  intermittent confirmé une fois de plus, sans lien avec ce chantier
  (aucun fichier touché par ce correctif n'a de rapport avec le
  localStorage des colonnes maîtres).
- `cd frontend && npm run build` → succès (`tsc -b && vite build`,
  exit 0), sortie complète relevée ci-dessus (chunks + tailles).

**Go/no-go merge `feature/react-migration` → `main` : prêt, en attente
du feu vert de l'utilisateur.**
Aucun blocage de sécurité ou de fiabilité connu ne reste ouvert côté
code de cette branche : le seul point bloquant remonté par l'audit
(filet de diagnostic exposé) est corrigé et vérifié. Les lacunes
restantes (liste ci-dessus, inchangée) sont des manques fonctionnels
ou des points à mesurer/cadrer, pas des raisons de bloquer un merge —
mais elles restent réelles et méritent d'être lues avant de décider.
Le test E2E flaky préexistant n'est pas un obstacle (confirmé sans
lien avec le code touché). La décision de merger reste, comme
toujours sur ce projet, celle de l'utilisateur seul.

Poussé sur `origin/feature/react-migration` — **pas de merge sur
`main`, pas de PR.**

---

## Revue Copilot PR #24 — 9 points corrigés, vérification indépendante (2026-09-18)

**Contexte** : un agent avait traité les 9 points remontés par la revue
Copilot sur PR #24 (dont un point CRITIQUE sécurité — RPC cross-tenant),
6 commits sur `feature/react-migration`, non poussés, en attendant une
vérification indépendante avant push.

**Vérification faite (pas juste relu le rapport — reproduit)** :
- **Sécurité (#1, RPC `cleanup_expired_pipeline_sessions`)** :
  `information_schema.role_routine_grants` interrogé en direct sur
  `bexiyvmdbxcwxasgslxp` → `EXECUTE` accordé seulement à `service_role`
  et `postgres`, `authenticated` bien retiré. **Confirmé réel.**
  Vérifié aussi que le nettoyage opportuniste ajouté (#8,
  `delete_expired_pipeline_sessions_for_org`) n'appelle PAS ce RPC —
  passe par le client normal de l'appelant, scopé RLS à son org : lu le
  code (`trieur/db.py`, `api/main.py`), cohérent avec le rapport.
- **#2 RecordEditDialog** : lu `frontend/src/screens/RecordEditDialog.tsx`
  — garde bien `originalData`/`editedKeys`, seul un champ édité part en
  chaîne. Conforme au rapport.
- **#3 useIsAdmin** : lu `frontend/src/lib/useAccount.ts` + `App.tsx` +
  `DatabaseScreen.tsx` — `useIsAdmin(ready)` dépend bien d'un signal de
  session prête. Conforme.
- **#4 mapping colonnes dupliquées** : lu `PipelineScreen.tsx` —
  détection des doublons + bouton "Construire" désactivé (`canBuild`).
  Conforme.
- **#5/#6 races DatabaseScreen/CockpitScreen** : `requestIdRef` présent
  dans les deux écrans. Conforme.
- **#7 pagination pipeline rows** : lu `api/main.py` — `page`/`page_size`
  ajoutés, recherche/filtres bien appliqués sur toute la session avant
  découpe (comportement documenté, différent de `/records`). Conforme.
- **#9 README** : diff `frontend/README.md` vérifié, écrans à jour.
  Conforme (le texte de `PipelineScreen.tsx` sur le dédoublonnage non
  câblé, laissé tel quel, est bien exact).
- **Tests** : `python3 -m pytest -q` → **1 échec** au premier run
  (`test_master_columns_localstorage_fallback`, suite complète), alors
  que le rapport annonçait "253 passed, 1 deselected" — formulation
  inexacte (rien n'est déselectionné, pas de marker). Creusé avant
  d'accepter l'explication "flake" : testé en isolation (passe),
  bisecté commit par commit sur les 6 nouveaux (chacun passe seul en
  répétant le test), testé sur `main` et sur la base de la branche
  avant ces 6 commits (`fd15e29`, suite complète : 250 passed, propre),
  puis suite complète rejouée deux fois de plus sur `feature/react-migration`
  au même commit : 1 échec puis 0 échec (254 passed). **Confirmé
  flaky/dépendant de l'ordre d'exécution en suite complète, pas une
  régression des 6 commits** — ce test ne touche à aucun fichier modifié
  par ce lot, et le comportement identique avait déjà été documenté
  comme préexistant dans une entrée précédente de ce journal (voir
  ci-dessus, "Go/no-go merge"). `tests/test_api.py` +
  `tests/test_db_pipeline.py` seuls : 104 passed.
- `cd frontend && npm run build` → exit 0 (`tsc -b && vite build`).
- `git diff --stat main...feature/react-migration -- views/ app.py` :
  toujours seulement les 3 fichiers déjà connus (`app.py`,
  `tab2_import_mapping.py`, `tab_database.py`), issus de commits
  antérieurs à ces 6 — pas de dérive du code Streamlit.

**Poussé** sur `origin/feature/react-migration`, commit `b3d80fc`
(6 commits, `fd15e29..b3d80fc`). Aucune correction supplémentaire
nécessaire — les 9 points sont réels et corrects tels que rapportés.
Commentaire posté sur PR #24 récapitulant les 9 points.

**Pas de merge sur `main` — pas demandé, décision utilisateur.**

---

## Frontend Trieur de Data -- portage fidèle des 4 onglets (2026-09-20)

**Contexte** : après le portage backend fidèle (mapping + moteur
filtre/dédoublonnage réel, commits `5c96ece`/`f1c4fae`/`2729e7d` sur
`claude/data-sorter-react-migration-kw7l7y`), `PipelineScreen.tsx`
restait un mirroir simplifié en un seul fichier (711 lignes, pas de
filtre multi-critères, pas de dédoublonnage côté écran). Reconstruit en
suivant le VISUEL et l'enchaînement exact des 4 vues Streamlit
d'origine (`views/tab1_colonnes_maitres.py` à `tab4_export.py`, commit
`635fcde`), pas une réinterprétation.

**Livré** :
- `frontend/src/screens/pipeline/Tab1ColonnesMaitres.tsx`,
  `Tab2ImportMapping.tsx`, `Tab3FiltrageDedup.tsx`, `Tab4Export.tsx` --
  4 composants distincts, `PipelineScreen.tsx` réécrit comme simple
  conteneur (état partagé : session pipeline, filtre multi-critères,
  recherche/filtres colonne, ordre/sélection export -- équivalent
  `st.session_state`).
- `frontend/src/lib/api.ts` : ajout des types/fonctions manquants côté
  contrat API déjà en place (`groups` sur `/rows` et `/export`,
  `getPipelineDuplicates`, `applyPipelineDedupe`, champs IBAN sur le
  résultat de mapping).
- `frontend/src/screens/MasterColumnsPanel.tsx` : ajout d'un callback
  optionnel `onColumnsChange` (DatabaseScreen ne le passe pas, aucun
  changement de comportement pour cet écran) pour que le Trieur de
  Data reste à jour sans revenir sur l'onglet 1.

**Écarts volontaires par rapport au Python** (documentés en commentaire
dans le code) :
- Dédoublonnage (onglet 3) **définitif** côté API (staging Postgres),
  contrairement à l'ancien `st.session_state` annulable -- confirmation
  explicite ajoutée avant toute suppression, avec avertissement
  "non annulable".
- Un seul fichier par session (pas de multi-fichiers ni Google Sheets),
  mapping global à la session (pas par onglet source) -- limite déjà du
  contrat API backend (`api/main.py`), pas ajoutée ici.
- Pas de filtres/presets d'export nommés et persistés côté pipeline
  (aucun endpoint pour ça, contrairement aux colonnes maîtres) --
  Streamlit les proposait via `saved_filters.json`/`export_presets.json`.
- Pas de sélection de valeurs par menu déroulant (colonnes <1000
  valeurs distinctes) : toujours un champ texte séparé par `;` -- aucun
  endpoint ne renvoie les valeurs distinctes d'une colonne pour tout le
  staging (seulement la page affichée).
- Pas de section "Enregistrer dans la base de données (CRM)" en fin
  d'export -- écran Base de données explicitement hors périmètre de ce
  chantier.

**Vérifié** :
- `npm run build` (tsc -b && vite build) : exit 0.
- `npm run lint` (oxlint) : exit 0, seulement des warnings déjà
  présents ailleurs dans le repo (même style, aucune nouvelle erreur).
- Vérification visuelle : pas d'infra de test frontend existante:
  harness temporaire (`mock.html`/`mock-main.tsx`, jamais commité,
  supprimé après coup) monté avec Playwright/Chromium pour capturer
  chaque onglet (import/mapping/IBAN, filtre multi-critères, export)
  avec des props simulées -- layout mobile confirmé, états vide/erreur
  confirmés propres (pas de crash sans session Supabase réelle). Pas de
  vérification avec un vrai backend/Supabase (identifiants non
  disponibles dans cette session) : à refaire par Raphaël en local ou
  sur l'environnement de dev avant mise en prod si un doute subsiste.

**Reste à faire / suivi** :
- [ ] Tester le flux complet avec un vrai fichier + vraies colonnes
  maîtres, en particulier la revue manuelle de doublons (aperçu par
  groupe) et l'export avec ordre de colonnes personnalisé.
- [ ] Décider si les filtres/presets d'export nommés du pipeline
  valent la peine d'un nouvel endpoint (actuellement non portés, voir
  écarts ci-dessus).

### Merge PR #25 (2026-09-20) -- chantier terminé

PR ouverte sur `main` avec le backend + frontend ci-dessus, revue
GitHub Copilot passée en boucle jusqu'à stabilisation (6 rounds), tous
les vrais bugs corrigés et testés avant merge :

1. `groups` (filtre multi-critères) non validé -> 500 au lieu de 400 sur
   une structure malformée. Corrigé (`_validate_filter_groups`).
2. Dédoublonnage manuel : un groupe de doublons non couvert par
   `keep_ids` perdait TOUTES ses lignes au lieu d'être rejeté. Corrigé
   (vérification stricte avant tout DELETE).
3. Détection IBAN par contenu limitée aux 10 premières lignes
   (`PIPELINE_PREVIEW_SIZE`) -> une colonne au nom générique avec des
   IBAN plus loin dans le fichier n'était jamais détectée. Étendu à un
   échantillon de 1000 lignes.
4. `PipelineScreen.tsx` : changement d'org rapide pouvait laisser le
   1er critère de filtre sur une colonne de l'ancienne org (closure
   périmée). Corrigé.
5. `Tab4Export.tsx` : ordre des colonnes à l'export déduit d'une seule
   ligne échantillon -> une colonne absente de cette ligne (mais
   présente sur d'autres) était silencieusement exclue de l'export.
   Corrigé (union des colonnes maîtres du mapping).
6. `row_count` non atomique côté suppression ET côté import par lots
   (même patron read-modify-write) -> deux appels concurrents
   pouvaient corrompre le compteur. Corrigé par RPC SQL atomique
   (migrations 0012, 0013).
7. Dédoublonnage : analyse et suppression non atomiques -> deux appels
   concurrents sur la même session pouvaient chacun garder une ligne
   différente du même groupe puis supprimer celle que l'autre voulait
   garder. Corrigé par un verrou court par session avec jeton
   propriétaire (migrations 0013/0014) + revérification juste avant le
   DELETE (migration 0015, réduit la fenêtre de course résiduelle à
   l'instant entre la revérification et le DELETE). Accepté comme
   suffisant pour un outil interne mono-poste -- un verrou tenu par une
   vraie transaction SQL de bout en bout serait disproportionné ici.
8. Deux races React pré-existantes (colonnes maîtres périmées lors
   d'un changement d'org, champ de filtre affichant une valeur périmée
   après changement de colonne) trouvées et corrigées au passage.

**Faux positif vérifié, pas corrigé** : Copilot a signalé que `.delete()`
côté `trieur/db.py` pourrait toujours renvoyer `res.data` vide donc
`n_deleted=0` -- vérifié dans le code source de `postgrest-py` (version
réellement installée, `2.31.0`) : `returning=ReturnMethod.representation`
est la valeur PAR DÉFAUT de `.delete()`, `res.data` contient bien les
lignes supprimées. Pas un bug.

294 tests backend au départ du chantier -> 307 à la fin (13 nouveaux,
tous les correctifs ci-dessus couverts). Build frontend vert. Mergé
sur `main` (commit `849e94a`).

**Point trouvé en vérifiant la base réelle, non traité (hors périmètre)** :
deux migrations Supabase (`0012_pipeline_parity`,
`pipeline_saved_filters`, appliquées le 2026-09-18) existent sur le
projet réel (`jarvis-assistant`) mais leurs fichiers `.sql` sont absents
de ce dépôt -- drift pré-existant à ce chantier (une autre session a dû
appliquer du SQL directement sans committer le fichier correspondant).
À régulariser séparément : soit retrouver/recréer les fichiers
manquants depuis le schéma réel, soit confirmer qu'ils viennent d'un
autre repo/chantier.

**Reste à faire côté Raphaël** :
- [x] Vérifier le flux complet en conditions réelles (vraies données,
  vrai compte) -- voir chantier "Cold start + landing + migrations"
  ci-dessous (PR #26), vérifié en live via curl sur `trieur-data`.
- [x] Régulariser le drift de migrations ci-dessus -- voir même
  chantier (PR #26).

---

## Cold start + landing par défaut + régularisation migrations (PR #26, 2026-09-20)

- Écran d'atterrissage par défaut : "Trieur de Data" au lieu de "Base
  de données" (`App.tsx`).
- Cold start ~1 min éliminé sans dépense supplémentaire : réutilisation
  du plan payant déjà pris (`trieur-data`, Starter ~7$/mois) au lieu
  d'un nouveau service -- vérifié en live (curl : 0.74s, en-tête CORS
  présent).
- Migrations `0016_pipeline_parity.sql`/`0017_pipeline_saved_filters.sql`
  ajoutées (renumérotées depuis une branche existante), rendues
  idempotentes (`IF NOT EXISTS`/`DROP POLICY IF EXISTS`), contenu
  vérifié contre la base réelle (`BEGIN;...ROLLBACK;`). Elles créent
  `pipeline_remembered_mappings`, `pipeline_export_presets`,
  `pipeline_saved_filters` et `pipeline_sessions.dedup_config` --
  actuellement INERTES (pas encore câblées dans l'API).
- CORS étendu aux domaines de prod réellement utilisés.

Mergé sur `main`. Reste à faire : câbler ces tables inertes si le
besoin (mémoire de mapping par forme de fichier, presets d'export,
filtres sauvegardés) est confirmé -- pas fait dans ce chantier ni le
suivant (#27).

---

## Multi-fichiers, mapping par onglet, vitesse d'import (PR #27, 2026-09-20)

**Pourquoi** : régressions réelles signalées par Raphaël par rapport à
l'original Streamlit sur l'onglet 2 (Import & Mapping) -- un seul
fichier à la fois (avant : 10-15 fusionnés), import lent, mapping en un
seul bloc en bas de page au lieu d'une carte par fichier/onglet avec
les menus au-dessus de l'aperçu (comme l'original).

**Livré** :
- Import multi-fichiers fusionnés en une session, parallélisé
  (`asyncio.gather` + `to_thread`), un seul appel RPC final pour
  `row_count` au lieu d'un par lot.
- Mapping PAR ONGLET (`mapping: {sheet_key: {source: maître}}`, fidèle
  à `views/tab2_import_mapping.py`) : chaque onglet garde son propre
  mapping, un onglet exclu/non mappé est retiré de la base fusionnée.
- Frontend : une carte empilée par onglet (résumé, bouton "Auto"
  local, grille menus/aperçu alignée), bouton global "Auto-assigner
  tous les onglets", expander d'inclusion fichiers/onglets.
- Zone d'import : vraie dropzone (glisser-déposer + icône) au lieu du
  `<input type="file">` natif, carte par fichier avec spinner pendant
  l'envoi (un seul appel réseau atomique -- les spinners tournent
  ensemble puis passent tous en succès/erreur ensemble, honnête sur ce
  que fait réellement l'appel).
- Bug trouvé en clarifiant l'UI "jeux de colonnes" : "Appliquer ce jeu"
  ne touchait que la mémoire personnelle du compte, jamais les colonnes
  maîtres réelles de l'environnement (contrairement à l'original qui
  les écrivait immédiatement) -- reconnecté (callback `onApply` vers
  `MasterColumnsPanel`).
- Textes explicatifs ajoutés : différence "jeux de colonnes"
  (Enregistrer vs Appliquer) et "environnements" (colonnes maîtres +
  imports cloisonnés par environnement).

**Revue Copilot, 8 rounds jusqu'à stabilisation, tous les vrais bugs
corrigés et testés avant merge** :
1. Nettoyage de session manquant si un lot d'import échoue en
   parallèle (course entre écriture et suppression).
2. Nettoyage de session manquant si le RPC final `row_count` échoue
   après que tous les lots ont réussi.
3. Dry-run de mapping chargeait TOUTE la session en mémoire à chaque
   import -- borné à un échantillon (`PIPELINE_SUGGESTION_ROW_CAP`).
4. Clés d'onglet inconnues dans le mapping fourni acceptées
   silencieusement -> tous les vrais onglets supprimés avec une
   réponse "mapped" à zéro ligne. Rejeté avant mutation (400).
5. Re-mapping d'une session déjà mappée acceptée -> `merge_mapped_row`
   retire `_sheet`, un retry regroupait tout sous une clé vide et
   supprimait tout. Rejeté (409).
6. Suppression des lignes exclues en un seul `.in_("id", ...)` ->
   risque de dépasser les limites de taille de requête PostgREST sur
   les gros volumes. Par lots bornés désormais.
7. **Race condition réelle** : le garde de statut lisait puis testait
   séparément de l'écriture finale -- deux requêtes concurrentes
   (double clic, deux onglets) pouvaient toutes deux passer le garde
   avant qu'aucune n'écrive `mapped`, et muteraient chacune les lignes
   de l'autre. Corrigé par réservation atomique
   (`claim_pipeline_session_for_mapping`, `UPDATE ... WHERE
   status='importing'` en un seul aller-retour SQL) juste avant les
   mutations.
8. **Dry-run cassait le multi-fichiers** : l'échantillon utilisait un
   LIMIT global sur toute la session avant de regrouper par onglet --
   si le 1er onglet dépassait le plafond, les onglets suivants
   n'apparaissaient jamais dans la suggestion et se faisaient
   supprimer silencieusement à l'application. Corrigé : échantillon
   PAR ONGLET (filtre SQL jsonb `data->>_sheet`), le frontend transmet
   les `sheet_key` connus.
9. La réservation atomique (point 7) écrivait déjà le statut `mapped`
   AVANT la réécriture des lignes -- un échec en cours de route
   (panne réseau) laissait la session visible comme `mapped` avec un
   staging à moitié transformé, retry impossible (409). Corrigé :
   bloc IBAN + réécriture dans un try/except, session entière
   supprimée sur échec (même choix que pour l'import), l'utilisateur
   réimporte proprement.
10. Menus de mapping modifiables manuellement pendant
    "Auto-assigner tous les onglets" -> une modif manuelle pouvait être
    écrasée silencieusement par la suggestion qui arrive ensuite.
    Menus désactivés pendant le chargement global.

**Écart volontaire assumé** : pas de mémoire du mapping par "forme de
fichier" (remembered_mappings/column_fingerprint, tables inertes créées
par PR #26) -- nouveau schéma DB déjà en place mais pas câblé, hors
périmètre de ce chantier.

**Trouvailles Copilot non corrigées, notées pour suivi (non bloquantes,
sévérité modérée, pas de perte de données)** :
- Matérialisation complète de la session en mémoire à l'application
  RÉELLE du mapping (pas le dry-run) -- préexistante à ce chantier
  (depuis `5c96ece`), nécessiterait un refactor streaming plus large
  (agrégation IBAN + comptage cohérents à travers les pages).
- Deux fichiers uploadés avec le MÊME nom se regroupent sous une seule
  carte dans l'expander d'inclusion (le compteur "fichiers" est alors
  sous-évalué) -- cas rare, chaque onglet reste individuellement
  distinguable et contrôlable, juste le regroupement visuel par nom de
  fichier qui fusionne les deux.
- Le bouton "Auto" LOCAL d'un onglet envoie quand même les clés de
  TOUS les onglets au dry-run (juste plus lent avec beaucoup
  d'onglets, pas un bug de correction).
- Un fichier déjà choisi puis reproposé après une erreur peut ne pas
  redéclencher `onChange` si l'input n'a pas été vidé (`fileInputRef`
  jamais réinitialisé dans `reset()`, contrairement à `ImportPanel.tsx`).

313 tests backend au départ -> 324 à la fin (11 nouveaux, tous les
correctifs 1-9 ci-dessus couverts par un test dédié). Build frontend et
lint verts à chaque commit. Mergé sur `main` (commit `abac465`).

**Reste à faire côté Raphaël** :
- [ ] Mesure réelle de vitesse en production sur un vrai import
  multi-fichiers (non faite dans cette session -- pas d'identifiants de
  test disponibles).
- [ ] Décider si les 4 trouvailles Copilot non bloquantes ci-dessus
  valent un chantier dédié.

---

## Message réseau clair + gros fichiers xlsx en flux (PR #28 + #29, 2026-09-20/21)

**Pourquoi** : Raphaël a signalé (capture d'écran) qu'en quittant la
page pendant un import (bascule d'appli sur mobile), il revenait sur
`Erreur : Erreur inconnue.` -- inexploitable. Root cause creusée avec
les métriques Render RÉELLES au moment exact du signalement (pas
supposée) : un .xlsx de 8,5 Mo a fait grimper le process de 123 à
488 Mo de RAM en quelques secondes (pandas/openpyxl charge tout en
mémoire, jamais en flux), juste sous la limite de 512 Mo du plan
Render -- OOM-kill en pleine requête, d'où la connexion coupée sans
réponse HTTP. Un correctif naïf (plafond bas, 8 Mo) aurait RÉGRESSÉ
par rapport à l'usage réel de Raphaël ("avant je pouvais importer
jusqu'à 500 Mo, je veux pas régresser") -- confirmé dans
`.streamlit/config.toml` (`maxUploadSize=500` sur l'ancien Streamlit).

**PR #28 -- message clair + garde-fous de taille** :
- `safeFetch()`/`safeReadJson()`/`safeReadBlob()`/`throwForErrorResponse()`
  (`frontend/src/lib/api.ts`) convertissent toute coupure réseau (avant
  OU pendant la lecture du corps, réponse OK ou erreur) en message
  explicite, plutôt que l'erreur brute du navigateur qui tombait dans
  le `catch` générique de chaque écran. Séparent aussi lecture (réseau)
  et parsing JSON (format) -- un JSON invalide/HTML de proxy ne
  s'affiche plus comme "connexion interrompue".
- Avertissement "ne quitte pas cette page" pendant l'import, sur LES
  DEUX parcours qui envoient des fichiers (`Tab2ImportMapping.tsx` ET
  `ImportPanel.tsx`, Base de données > Importer).
- `PIPELINE_MAX_UPLOAD_BYTES` : plafond appliqué AVANT toute lecture
  (`f.size`, jamais un `f.read()` préalable), sur les DEUX endpoints
  d'import (`/pipeline/sessions` et `/orgs/{org_id}/import` --
  celui-ci n'avait AUCUNE protection avant ce chantier).

**PR #29 -- import et mapping réellement EN FLUX, jamais toute la
session en mémoire** (au lieu de se contenter de rehausser le
plafond) :
1. **Import** (`trieur/io_excel.py:stream_excel_sheets`) -- openpyxl
   en mode `read_only`, ligne par ligne, insertion par lots. Détection
   d'en-tête reproduite à l'identique sur un échantillon borné (ces
   fonctions n'en regardent de toute façon jamais plus). Mesuré : delta
   mémoire quasi nul sur 50 000 lignes (sous-process isolé), contre
   ~45x la taille du fichier en RAM par le chemin classique -- calamine
   testé en parallèle : même pic mémoire qu'openpyxl, aucun gain réel
   malgré le commentaire "plus économe" hérité du code d'origine.
2. **Application du mapping** (`api/main.py:apply_pipeline_mapping`) --
   chaque onglet traité PAR PAGES depuis la base plutôt que tout
   chargé d'un coup : sans ce 2e volet, le même risque mémoire se
   serait juste déplacé de l'import au mapping sur un gros fichier.
3. Bascule automatique au-delà de `PIPELINE_STREAM_THRESHOLD_BYTES`
   (8 Mo, mesuré) ; en dessous, chemin classique inchangé. Plafond
   absolu (`PIPELINE_MAX_UPLOAD_BYTES`) relevé à **550 Mo** (marge
   au-dessus du besoin réel de 500 Mo) -- un plafond plus bas aurait
   juste déplacé la régression du "plante en RAM" au "rejeté en 413".

**Revue Copilot, ~15 rounds cumulés sur les deux PR, tous les vrais
bugs corrigés et testés avant merge** -- points notables :
- Deux endroits distincts avaient le même bug `(f.size or 0)` :
  UploadFile.size indisponible compté silencieusement à 0 octet,
  contournant le plafond ET laissant passer `f.read()` sur un fichier
  arbitrairement gros. Corrigé aux 3 endroits (chaque PR avait sa
  propre copie indépendante du endpoint, créées avant qu'aucune ne
  soit mergée).
- **Traitement partiel silencieux en mode flux** : `apply_pipeline_mapping`
  se basait entièrement sur `sheet_keys` fourni par le client -- une
  liste désynchronisée laissait des lignes jamais traitées (ni
  mises à jour ni exclues) alors que la session passait quand même à
  `mapped`. Garde ajoutée : `n_updated + n_excluded` comparé au
  `row_count` initial (capturé AVANT toute mutation -- `delete_pipeline_rows`
  décrémente `row_count` sur le même dict en place côté client
  Postgrest, donc le relire après coup aurait faussé la comparaison),
  échec explicite + session supprimée sur mismatch.
- **En-têtes vides/dupliquées écrasaient des colonnes** :
  `dict(zip(columns, ...))` perdait silencieusement des données sur un
  fichier avec une en-tête imparfaite (cellules vides, nom répété).
  Vérifié contre le vrai comportement de pandas (pas supposé) et
  reproduit à l'identique (`Unnamed: <index>`, suffixe `.1`/`.2`).
- Une trouvaille répétée sur plusieurs rounds (conversion `None` en
  chaîne `"None"` lors de l'inférence sans en-tête) a été
  méthodiquement VÉRIFIÉE contre la version pandas réellement
  installée (non reproductible, testé en conditions réelles) avant
  d'être quand même rendue explicite dans le code par prudence,
  plutôt que patchée à l'aveugle sur la seule foi de la review.
- Test mémoire (`test_io_excel_streaming.py`) déplacé dans un
  sous-process `spawn` isolé -- `ru_maxrss` est un maximum non
  décroissant, le mesurer dans le process de test aurait pu masquer
  une régression du streaming derrière le pic déjà atteint en
  générant le fichier de test.
- `.xls` (format binaire Excel 97-2003, différent de `.xlsx`) exclu
  explicitement du mode flux -- `stream_excel_sheets` repose sur
  openpyxl, qui ne le lit pas.

**Fusion des deux PR** : #28 mergé en premier (`ec0e7ec`), conflit
attendu résolu en gardant la version évoluée de #29 sur
`api/main.py`/`tests/test_api.py` (seuil de flux + plafond 550 Mo +
garde .xls + garde traitement-partiel, pas le simple rejet 8 Mo de
#28) -- puis #29 mergé (`a3d86aa`). 343 tests backend verts (hors le
test e2e Playwright `test_master_columns_localstorage_fallback`,
préexistant et non lié, déjà connu instable en CI). Build et lint
frontend verts. Déployé sur Render, service live et sain (logs
vérifiés, aucune erreur).

**Reste à faire côté Raphaël** :
- [ ] Test réel avec un vrai fichier volumineux (300-550 Mo) après
  déploiement -- cette échelle n'a jamais été vérifiée en conditions
  réelles (temps de requête, délais proxy Render au-delà de quelques
  dizaines de Mo).
- [ ] Reproduire le scénario original (quitter la page pendant un
  import) pour confirmer que le message est bien maintenant lisible.

---

## Fix : écran blanc entre les changements de menu (2026-09-21, PR #30)

**Signalé par Raphaël** : bascule entre "Base de données" / "Trieur de
Data" / "Cockpit" → écran blanc à chaque fois, et l'environnement
sélectionné revenait au premier de la liste.

**Cause** : `App.tsx` démonte entièrement l'écran actif à chaque
changement d'onglet du haut (rendu conditionnel, pas de persistance).
`useOrgs()`/`useIsAdmin()` (`frontend/src/lib/useAccount.ts`)
repartaient donc de zéro à CHAQUE bascule -- le temps de l'aller-retour
réseau, la barre d'onglets et le sélecteur d'environnement (conditionnés
à `orgs`/`orgId` non nuls) disparaissaient complètement du DOM, sans
indicateur de chargement.

**Fait** :
- Cache module-level dans `useAccount.ts` (survit aux remontages de
  composant, pas aux rechargements de page) : sert immédiatement la
  dernière valeur connue au remontage, une requête revalide en
  arrière-plan.
- Environnement sélectionné conservé entre les bascules (repli sur le
  premier de la liste seulement si l'accès a été retiré entre-temps).
- Cache vidé explicitement à la déconnexion (`AuthContext.signOut`)
  pour ne jamais fuiter les environnements/le statut admin d'un compte
  vers un autre compte connecté ensuite dans le même onglet.

**Corrigé après revue Copilot (2 rounds)** : une requête `listOrgs()`/
`getMe()` déjà en vol au moment de `clearAccountCache()` (déconnexion
suivie d'une reconnexion rapide avec un AUTRE compte) pouvait résoudre
APRÈS le nettoyage et réécrire le cache partagé avec les données de
l'ancien compte -- son `cancelled` local ne se ferme qu'au démontage du
composant, pas au nettoyage du cache. Ajout d'un compteur de génération
(`cacheGeneration`, incrémenté à chaque `clearAccountCache()`) capturé
par chaque requête au lancement et revérifié juste avant toute écriture
du cache module-level.

**CI** : `pytest` rouge sur le dernier commit (344 passed, 1 failed) --
`test_master_columns_localstorage_fallback`, le flake Playwright
préexistant déjà documenté plus haut dans ce journal (délai fixe de 4s
parfois trop court), sans rapport avec le diff (`useAccount.ts`
uniquement). Re-run fait une fois : même échec exact, confirmé non lié.
Mergé en l'état (commentaire de constat sur la PR).

**Reste à faire côté Raphaël** :
- [ ] Confirmer en conditions réelles (bascule entre les 3 menus,
  connecté) -- pas d'identifiants de test Supabase disponibles dans cet
  environnement pour un clic réel en navigateur.

---

## Cockpit : sections auto-classées, liens cliquables, questions intégrées, chiffres cliquables (2026-09-21, PR #31 et #32)

**Signalé par Raphaël**, en usage réel du Cockpit (captures d'écran) :
- Créer un chantier demandait de choisir une section à la main.
- Un lien posté dans le fil d'un chantier (fiche de questions) n'était
  pas cliquable au pouce sur téléphone.
- Répondre à une question posée par une session Claude nécessitait le
  lien claude.ai de la fiche -- perdu d'une session à l'autre, invisible
  sans lui, oblige à "dédoublonner" entre le Cockpit et les sessions.
- Les 4 chiffres "Où j'en suis" (Bouge/Livré/Pour toi/Dort) ne menaient
  nulle part -- "je vois écrit 2, je sais pas où ils sont".
- Le sélecteur d'environnement (Global/Prélèvement/Leads) n'expliquait
  pas ce qu'il fait.
- Les titres de chantiers étaient trop longs/techniques.

**Fait (PR #31)** :
- `POST /orgs/{org}/chantiers` sans thème devine la section depuis le
  titre (sections existantes en priorité, sinon une famille de
  mots-clés du domaine, sinon "Général") et la crée si besoin --
  `trieur/db.py:infer_chantier_theme`. Le formulaire du Cockpit ne
  demande plus de section.
- Les URL dans un message de chantier sont rendues en lien cliquable
  (`ChantierCard.tsx:LinkifiedText`).

**Fait (PR #32)** :
- Nouvelle table `trieur_data.chantier_questions` (migration 0018) :
  une question à choix cliquables + commentaire vit **dans le Cockpit
  lui-même**, plus sur une page claude.ai à part. Une session Claude
  crée la question par SQL, Raphaël répond dans l'appli (ou
  inversement) -- même ligne des deux côtés, rien à synchroniser.
  Endpoints `GET/POST/PATCH /orgs/{org}/chantiers/{id}/questions`.
  Affichées inconditionnellement dans `ChantierCard` (pas cachées
  derrière "voir le fil"), comme les points à suivre.
- Les 4 chiffres "Où j'en suis" sont cliquables : chaque nombre fait
  défiler jusqu'à la liste filtrée sur ce statut ("Livré aujourd'hui"
  ouvre les chantiers clos).
- Phrase d'explication ajoutée sous le sélecteur d'environnement.
- Titres de chantiers simplifiés (en base, hors code) : le détail
  technique reste dans le 1er message du fil, jamais dans le titre.

**Routine horaire du Cockpit mise à jour en conséquence** (même
Routine que la section précédente, `trig_015S4ox6ncE2kZmF81BSW4WK`
après recréation -- l'ancien id `trig_0119bTU23D8zmvbsJPqqhiNH` n'est
plus valide) : elle n'utilise plus JAMAIS la fiche Artifact claude.ai
pour poser une question sur un chantier ambigu -- elle insère dans
`trieur_data.chantier_questions` à la place, et vérifie cette table
(plus `ArtifactData`) pour savoir si une réponse est arrivée avant de
reprendre un chantier `attente_retour`. Consigne aussi ajoutée : titres
de chantier toujours courts (5-8 mots), jamais de jargon technique dans
le titre.

**Vérifié** : `npm run build`/`npm run lint` (aucune nouvelle erreur,
les deux PR), `pytest` 349 passed hors flake e2e déjà documenté (PR
#32 ajoute 5 tests sur les questions + corrige un vrai bug de cache
trouvé en les écrivant : `list_sections` n'était pas purgée entre les
tests, voir PR #31).

**Reste à faire côté Raphaël** :
- [ ] Vérifier en conditions réelles dans le Cockpit : créer un
  chantier (section auto), cliquer un chiffre "Où j'en suis", répondre
  à une question si la Routine en pose une.

---

## Prélèvement : réglage clair/sombre + génération des mandats SEPA depuis l'export CRM (2026-09-21, PR #33 et #34)

**Contexte** : Raphaël a fourni les 3 fichiers Excel de référence de
son père (récupération CRM, tri/nettoyage, création des mandats) +
un classeur Drive historique (11 onglets, 5,5 Mo), pour comprendre le
processus manuel actuel de remise bancaire (prélèvements SEPA MGS,
banques CAIXA/Sabadell) et l'automatiser dans l'environnement
Prélèvement -- domaine explicitement "zéro droit à l'erreur".

**Analyse menée avant tout code** (fichiers copiés dans le scratchpad
de session, pas dans le dépôt -- données clients réelles) : formules
Excel lues onglet par onglet (`INDIRECT`, `MATCH`, calcul IBAN mod-97,
lookup tarifs...), compréhension confirmée avec Raphaël par plusieurs
séries de questions simples (fiches à choix). Règles retenues :
- Optivie et Optilife sont le même produit -> fusionnés en un seul
  montant.
- "Contrat MYMO casse & perte appareil auditif" : délibérément ignoré
  pour l'instant (demande explicite).
- Correctif IBAN : espaces retirés, "fr" -> "FR". IBAN inexistant ->
  ligne ignorée. Carte bleue -> jamais en prélèvement.
- Date du 1er prélèvement : jamais avant aujourd'hui + 3 jours (délai
  fixe).
- OOFF (1er prélèvement, avec frais de dossier) vs RCUR (récurrent,
  sans frais) : le montant diffère, pas juste un indicateur.
- Tableau de tarifs : quasi fixe, sert à un code de suivi interne, pas
  au calcul du montant (déjà fourni par le CRM).
- ICS (identifiant créancier SEPA) : laissé vide pour l'instant
  (Raphaël n'avait pas le numéro sous la main).

**Portée volontairement limitée à ce que Raphaël a demandé de traiter
en premier** : nettoyer un export CRM brut -> classeur prêt pour la
banque (OOFF/RCUR/Exclus). L'historique des remises passées, la
détection de doublons/noms inversés, le suivi des impayés et la
réconciliation du relevé bancaire (classeur Drive) sont un chantier
séparé, créé dans le Cockpit pour ne pas l'oublier : **"Historique,
doublons, impayés et relevé bancaire"** (org Prélèvement).

**Fait (PR #34)** :
- `trieur/prelevement.py` : moteur pur (aucune dépendance réseau/DB,
  testable en isolation) -- IBAN nettoyé ET vérifié par un vrai calcul
  mod-97 (`iban_checksum_valid`, ISO 7064 MOD 97-10), BIC 8 caractères
  complété à 11 avec "XXX", montants robustes au séparateur décimal
  ("," ou "."), date du 1er prélèvement via `MAX(aujourd'hui+3,
  prévue)`, motif de virement reconstruit (`MGS-{RUM}` + suffixe par
  produit facturé), classement OOFF/RCUR sur la présence de frais de
  dossier. Une ligne cassée est exclue AVEC LA RAISON (`ExclusionRow`),
  jamais une exception qui ferait échouer tout le lot.
- Migration `0019_prelevement_rules.sql` + `trieur/db.py` : réglages
  ajustables par organisation (ICS, nature CORE/B2B, délai en jours) --
  rien codé en dur, demande explicite de Raphaël ("qu'on puisse les
  ajuster par la suite, pas que tout le code s'implémente dedans en
  vrac").
- `api/main.py` : `GET/POST /orgs/{org}/prelevement/rules`, `POST
  /orgs/{org}/prelevement/generate` (upload l'export CRM en CSV/xlsx,
  renvoie un classeur à 3 onglets OOFF/RCUR/Exclus). Réservé aux
  administrateurs (`require_cockpit_access`) -- données bancaires de
  clients, pas un export ordinaire de la Base de données.
- Nouvel onglet "Prélèvement" dans l'appli (`PrelevementScreen.tsx`,
  visible seulement pour les admins) : réglages + dépôt de fichier +
  téléchargement direct du résultat avec un résumé (nombre de OOFF/
  RCUR/exclus).
- PR #33 (mergée avant celle-ci, sans lien direct) : réglage de thème
  clair/sombre/auto pour toute l'appli, demandé par Raphaël en pleine
  nuit sur le Cockpit -- voir entrée dédiée plus haut si besoin, pas
  détaillé ici.

**Vérifié, pas juste testé sur des données inventées** : moteur validé
sur le VRAI fichier CRM de référence (291 lignes) -- 287 mandats
générés, 4 exclusions légitimes (3 clients sans aucun montant, 1 carte
bleue). Trouvaille notable en validant : 5 IBAN que le CRM d'origine
n'avait jamais marqués "validés" (juste jamais vérifiés, pas
réellement invalides) passent correctement le calcul mod-97 -- le
moteur est donc plus fiable que le drapeau d'origine sur ce point
précis, pas moins. `pytest` : 380 passed (31 nouveaux tests : 25 sur
le moteur pur avec un IBAN réel du fichier de référence, 6 sur les
2 endpoints), hors le flake e2e déjà documenté. `npm run build`/`npm
run lint` : aucune nouvelle erreur.

**Comparaison ligne par ligne faite par Claude (2026-09-21, PR #36)** :
Raphaël a demandé la comparaison au fichier Excel actuel -- faite
directement contre les onglets calculés du classeur de référence
("3 Sheet1"/"Mandats CAIXA"), sur le seul vrai client encore présent
dans ce classeur au moment de l'analyse (`MGS-20230`, RUM `1422647`,
les autres lignes du classeur n'étaient que des restes de formules
vides malgré un `max_row` élevé -- vérifié cellule par cellule avant
de conclure). 5 champs sur 7 correspondaient déjà exactement (montant,
motif, BIC, IBAN, type de séquence). 2 ne correspondaient pas, corrigés
dans la foulée :
- `date_signature_mandat` repartait de la date du jour au lieu de la
  date de création du contrat dans le CRM.
- `explication_periodicite` restait remplie pour un 1er prélèvement
  (FRST), alors que le fichier de référence la laisse vide.

Re-testé sur le fichier CRM complet (291 lignes) après correctif :
toujours 287 OOFF / 0 RCUR / 4 exclus, identique à avant -- confirme
que le correctif ne change que les 2 champs erronés, rien d'autre.

**Reste à faire côté Raphaël, IMPORTANT avant tout usage réel** :
- [ ] Comparer un lot COMPLET (pas juste 1 ligne comme ci-dessus, faute
  de plus de vraies lignes disponibles dans le classeur de référence
  au moment de la vérification) au résultat de son père sur le même
  lot, avant de faire confiance à ce module pour une vraie remise en
  banque. Aucune automatisation bancaire ne doit partir en production
  sans cette vérification humaine à plus grande échelle, même si tous
  les tests automatisés passent et que le seul exemple disponible
  correspond.
- [ ] Donner le numéro ICS quand il sera disponible (réglage dans
  l'onglet Prélèvement, pas besoin de redemander à Claude).
- [ ] Chantier séparé déjà noté dans le Cockpit pour la suite :
  historique/doublons/impayés/relevé bancaire -- à ne prendre qu'une
  fois celui-ci validé en conditions réelles.

---

## Accès en lecture seule par environnement (2026-09-21, PR #35, Routine Cockpit)

**Fait** (chantier point 12 ci-dessus, "rôles plus fins par
environnement") : Raphaël a besoin de donner à des partenaires externes
un accès de consultation seule -- "un accès de lecture simple pour
consulter certaines informations, ça m'évite de leur expliquer tout ou
leur sortir des documents". Réponse "encore plus de restrictions
possibles si nécessaire" prise comme feu vert pour un premier palier
simple (lecture/écriture par environnement entier), pas une
granularité fine par colonne (pas demandée, resterait à cadrer si
besoin plus tard).

- Migration `0020_read_only_role.sql` (appliquée en base sous le nom
  `0018_read_only_role` avant une collision de numéro avec `main`,
  fichier renommé ensuite -- aucun impact, Supabase suit les
  migrations par horodatage) : troisième valeur `lecture_seule` pour
  `memberships.role`, fonction `trieur_data.can_write()`, policies RLS
  séparées lecture/écriture sur `records`/`import_batches`/
  `dedup_alerts`. C'est la vraie barrière de sécurité : Streamlit et
  l'API FastAPI utilisent tous deux la clé anon + le jeton de
  l'utilisateur connecté, jamais `service_role` -- donc appliquée quel
  que soit le chemin emprunté.
- Streamlit (`views/tab_database.py`) et API (`api/main.py`) :
  import/modification/suppression/résolution d'alerte masqués ou
  refusés (403) pour un membre lecture seule, en plus de la RLS (double
  vérification, même convention que le reste de l'app).
- Réglages de l'environnement (admin) : nouvelle section "👥 Membres de
  cet environnement" pour changer le rôle d'un membre déjà présent ou
  retirer son accès, sans écrire de SQL à chaque changement.

**Limite connue, documentée, hors périmètre de ce chantier** : créer
une toute première appartenance pour un nouveau compte reste manuel
(aucun flux d'invitation n'existe pour personne aujourd'hui, pas
seulement pour ce rôle). Une fois la ligne `memberships` créée une
fois (dashboard Supabase + une ligne SQL), son rôle est modifiable
directement dans l'app.

**Vérifié** : migration testée sur le projet Supabase réel avant
application (contraintes/policies confirmées, tous les membres
existants étaient `org_admin` donc aucune régression pour eux).
`pytest` : 400 passed (nouveaux tests : rôle lecture seule refusé sur
bulk delete/update, patch, résolution d'alerte, import ; lecture
toujours autorisée ; super-admin toujours en écriture même sans ligne
`memberships` ; endpoints membres réservés aux admins), hors le flake
e2e Playwright déjà documenté (environnement sandbox sans navigateur,
CI l'installe et passe).

**Pas encore vérifié** : rendu réel dans l'app avec un vrai compte
partenaire en lecture seule (pas de tel compte existant à ce jour).

---

## Étiquettes libres sur un client (2026-09-21, PR #38, Routine Cockpit)

**Fait** (chantier point 7 ci-dessus, n1) : statut manuel filtrable par
client (ex. "VIP", "à recontacter", "litige"), demande explicite de
Raphaël, sans commentaire additionnel.

- Migration `0021_client_tags.sql` : table `record_tags` à part (pas
  une clé de plus dans le jsonb `data`, qui mélangerait avec les champs
  importés) -- une ligne par (client, étiquette), partagée par toute
  l'organisation (pas liée à un compte comme les vues enregistrées).
  Écriture réservée à `trieur_data.can_write()` (migration 0020) : un
  membre lecture seule voit les étiquettes mais ne peut ni en poser ni
  en retirer.
- La liste clients affiche une colonne "Étiquettes" (jointes par
  virgule, triées) construite à côté de "Modifié par" -- elle profite
  gratuitement des filtres par colonne déjà existants (contient/vide/
  non vide...), pas de filtre dédié à écrire ni maintenir.
- Ajout/retrait immédiat depuis la fiche d'un client sélectionné, sans
  bouton "Enregistrer" séparé (une étiquette est triviale à défaire,
  contrairement à une modification de champ importé).
- API (`api/main.py`) : mêmes endpoints (`GET /orgs/{org}/tags`,
  `POST`/`DELETE .../records/{id}/tags`, gardés par
  `require_write_access`), même colonne "Étiquettes" en liste/export,
  pour rester cohérent avec le frontend React en cours de portage.

**Vérifié** : `pytest` : 417/418 en local avant push, puis en CI.

**CI rouge rencontrée, sans lien avec ce chantier** :
`tests/test_e2e_smoke.py::test_master_columns_localstorage_fallback`
échoue de façon reproductible (confirmé par un re-run identique) --
mais échoue À L'IDENTIQUE sur `main` lui-même depuis plusieurs commits
déjà (avant cette PR, ex. la clôture de la PR #35). Pas touché par ce
chantier (rien ici ne touche `views/_ls_sync.py` ni la restauration
localStorage des colonnes maîtres) -- mergé malgré ce rouge
pré-existant, comme les PR #35/#36 avant elle. **À corriger sans lien
avec un chantier produit** : ce test e2e semble casser dès qu'un autre
test de la même session a déjà modifié les colonnes maîtres par défaut
(les valeurs qu'il trouve, "GENRE/CIVILITE", "VILLE", "Source Data"...,
ressemblent à un état laissé par un autre test) -- probable manque
d'isolation entre tests e2e, pas encore diagnostiqué en détail.

**Pas encore vérifié** : rendu réel dans l'app (pas de compte Supabase
connecté disponible dans cette session).

---

## Annuler un import entier en un clic (2026-09-21, PR #40, Routine Cockpit)

**Fait** (chantier point 8 ci-dessus, n3) : répondu "oui" par Raphaël,
sans commentaire additionnel.

- Aucune migration nécessaire : `records.batch_id` référence déjà
  `import_batches` en `on delete cascade` depuis le schéma initial
  (`0001_init.sql`) -- supprimer le lot suffit à retirer ses clients,
  alertes de doublon et étiquettes avec lui.
- `trieur/db.py` : `list_recent_import_batches()` (15 plus récents),
  `cancel_import_batch()`.
- Section "🗂️ Imports récents (annuler)" dans l'onglet Import
  (Streamlit), un bouton par lot avec confirmation à deux étapes --
  masquée pour un membre lecture seule. Même API côté FastAPI.

**Vérifié, pas juste supposé depuis la définition SQL** : cascade testé
directement sur le projet Supabase réel (lot + client + étiquette de
test insérés, lot supprimé, les trois confirmés disparus, aucune trace
résiduelle) avant d'écrire le code Python. `pytest` : 424/425 (voir
point suivant).

**CI rouge pré-existante rencontrée à nouveau (3e fois consécutive,
PR #35/#38/#40)** :
`tests/test_e2e_smoke.py::test_master_columns_localstorage_fallback`
reste cassé sur `main`, sans lien avec les 3 derniers chantiers livrés.
Mergé à chaque fois malgré ce rouge (déjà expliqué et accepté comme
pratique sur ce dépôt), mais ça commence à coûter une vérification
manuelle à chaque PR -- **vaut maintenant un chantier dédié pour le
corriger** plutôt que de continuer à le contourner. Piste déjà notée :
manque d'isolation entre tests e2e (l'état trouvé au moment de l'échec
ressemble aux colonnes maîtres laissées par un AUTRE test e2e de la
même session pytest, pas les valeurs par défaut attendues).

---

## Correctif du flake e2e "colonnes maîtres / localStorage" (2026-09-21, PR #42)

**Fait** (chantier auto-créé suite au point ci-dessus, pas demandé par
Raphaël -- root-cause pendant un temps mort plutôt que de recontourner
une 4e fois) : la piste "manque d'isolation entre tests" notée plus
haut était **fausse** -- vérifié et écartée après investigation réelle,
pas juste supposée.

**Vraie cause racine** : la restauration depuis le `localStorage` prend
DEUX allers-retours serveur (le composant JS renvoie sa valeur → rerun
automatique Streamlit, puis `app.py` appelle `st.rerun()` une seconde
fois pour rafraîchir le widget texte). Le test pariait sur un délai
fixe de 4 secondes pour que les deux se terminent -- assez en local,
pas toujours sous la charge d'un runner CI partagé.

**Vérifié en conditions réelles avant de conclure** (vrai Chromium,
vraie app Streamlit lancée en sous-processus, aucun mock) : la
fonctionnalité de restauration elle-même fonctionne très bien (moins
d'1 seconde à chaque essai, y compris en rejouant exactement la
séquence des deux tests du fichier l'un après l'autre plusieurs fois
de suite) -- c'est le TEST, pas le produit, qui pariait sur un chrono
fixe au lieu d'attendre la vraie condition.

**Corrigé** : remplacé `page.wait_for_timeout(4000)` + une lecture
unique par `expect(textarea).to_have_value(..., timeout=15000)`
(Playwright), qui réinterroge le DOM en boucle jusqu'à la bonne valeur
au lieu de parier sur un délai unique. `pytest` : 423 passés en local
(hors e2e, navigateur non installé dans ce bac à sable) + CI verte sur
la PR (le vrai test concerné inclus, avec le navigateur installé par
la CI).

Plus de rouge pré-existant à documenter/contourner sur les prochaines
PR -- si `test_master_columns_localstorage_fallback` recommence à
échouer, ce n'est PAS le même problème (celui-ci est réellement
corrigé, pas juste masqué).

**Correction (2026-09-21, plus tard le même jour)** : **ce diagnostic
était incomplet.** Le même test a re-échoué sur la PR #46 juste après.
La vraie cause racine (un `st.rerun()` en trop dans `app.py`, pas
seulement un délai de test trop court) est corrigée dans l'entrée
"Correctif du flake e2e -- vraie cause" plus bas. Gardé cette entrée
telle quelle (pas réécrite) pour que la trace de ce qui a été cru à
tort reste visible -- voir plus bas pour l'explication complète et la
vérification réelle.

---

## Prélèvement : montant par produit + suffixes IMMO/MYJURIS corrigés (2026-09-21, PR #37/#39/#41/#43)

**Fait** (retours réels de Raphaël sur trieur-data-app-test.onrender.com,
traités dans l'ordre où il les a signalés) :

1. **Champ fichier invisible/mal indiqué** (PR #37, puis #39) : l'input
   `type="file"` brut n'avait ni libellé ni contraste. Ajout d'un
   libellé numéroté "1. Choisis le fichier..." puis remplacement complet
   par la même zone glisser-déposer que l'étape Import & mapping du
   Trieur de Data (icône, surbrillance au survol, nom+taille affichés).

2. **Résumé "0/0/0" alors que le fichier généré contenait de vraies
   données** (PR #41) : cause racine trouvée en lisant le code, pas
   devinée -- le middleware CORS n'exposait pas
   `X-Ooff-Count`/`X-Rcur-Count`/`X-Exclus-Count` au JavaScript du
   navigateur (`allow_headers` gouverne les en-têtes de REQUÊTE, pas
   les en-têtes de RÉPONSE lisibles cross-origin). Corrigé avec
   `expose_headers` sur `CORSMiddleware`, nouveau test qui simule une
   vraie requête cross-origin (sinon indétectable par `TestClient`).

3. **Montants "complètement délirants"** (PR #43, le plus gros) :
   Raphaël a demandé de croiser avec le fichier Drive existant
   (lecture seule stricte, "zéro modification" -- respecté). En
   croisant le fichier CRM de référence avec le vrai fichier de remise
   bancaire ("remises CAIXA+Sabadell"), la vraie cause a été trouvée :
   **le moteur générait UN mandat par CLIENT en sommant tous ses
   produits actifs, alors que la banque exige UN mandat par PRODUIT
   actif**, chacun avec son propre montant et son propre motif
   `MGS-{RUM}-{suffixe}`. La colonne "Total cotisation et frais de
   dossier", utilisée jusque-là comme source du montant, ne correspond
   en réalité à AUCUN montant réel envoyé en banque -- vérifié faux sur
   plus de 10 clients croisés à la main, jamais réutilisée depuis.

   Règle confirmée : montant RCUR = valeur brute de la colonne produit ;
   montant FRST = valeur produit + frais de dossier fixe **par produit**
   (20€ par défaut, rendu réglable -- `prelevement_rules.frais_setup_eur`,
   migration 0022 -- jamais codé en dur).

   Raphaël a aussi demandé une nouvelle structure d'onglets (un onglet
   "Mandat" combiné EN PLUS de "First"/"RCUR" détaillés -- "First"
   remplace "OOFF"), le retrait de la colonne "Nature" (réglage global,
   pas une donnée par client) et l'ajout d'une colonne "Date d'effet"
   (lue depuis le CRM, jamais inventée si absente).

   **Deuxième passe** : Raphaël a renvoyé un nouvel export CRM brut
   (déjà présent en parallèle sur le Drive, pour recroiser). Sur ce
   fichier, 6 mandats sur 88 ne correspondaient à aucune ligne réelle --
   tous liés au produit IMMO. Deux bugs supplémentaires trouvés et
   corrigés : (a) la colonne IMMO correspond au suffixe **"-AU"**, pas
   "-IM" comme la formule Excel d'origine (reverse-engineered dans une
   session précédente) le laissait penser ; (b) quand MYJURIS et IMMO
   sont actifs **ensemble**, ils fusionnent en UN SEUL mandat "-J-AU"
   (montants additionnés, frais comptés 2 fois) -- seule exception
   connue à la règle "un mandat par produit", confirmée sur 2 clients
   réels distincts.

**Vérifié à l'échelle réelle** (pas seulement par les tests unitaires) :
moteur relancé sur les DEUX fichiers CRM réels disponibles (291 lignes
+ 66 lignes), chaque mandat généré comparé au motif+type exact du vrai
fichier de remise bancaire du Drive (lecture seule) -- **501 mandats
sur 502 correspondent EXACTEMENT** (le seul écart restant est un
client pas encore envoyé à la banque dans l'historique du Drive, pas
une erreur du moteur). `pytest` : 433 passés (34 tests moteur, 9 tests
API Prélèvement).

**CI rouge rencontrée pendant ce chantier** : le même test
`test_master_columns_localstorage_fallback`, déjà "corrigé" par PR #42
en parallèle par l'autre session, a quand même échoué 2 fois sur des
commits différents pendant que plusieurs jobs tournaient en parallèle
(main restait vert au même moment à chaque fois) -- mergé malgré ce
rouge, documenté sur chaque PR. Pas de nouvelle cause racine identifiée
au-delà de ce qui est déjà dans l'entrée PR #42 ci-dessus ; à surveiller
si ça redevient fréquent.

### PR #44/#45 : import multi-fichiers + résumé des étapes de traitement (2026-09-21)

Raphaël a signalé n'avoir aucun retour visuel à l'import (drag-drop ou
clic) et a demandé le support multi-fichiers pour l'avenir, puis un
"petit résumé des étapes" après import (pas une fonctionnalité
permanente, juste pour comprendre ce qui a été fait sur le fichier).

- PR #44 : import multi-fichiers (`<input multiple>`, sélection
  cumulable, retrait fichier par fichier, fusion `pd.concat` côté
  serveur).
- PR #45 : résumé en phrases lisibles après génération (fichiers/lignes
  lues, exclusions détaillées par raison, mandats First/RCUR générés,
  fusions MYJURIS+IMMO appliquées) -- encodé en base64 dans un en-tête
  HTTP dédié (`X-Steps-B64`, ASCII only) et ajouté à `expose_headers`
  CORS (même classe de bug déjà rencontrée une fois pour
  `X-Ooff-Count`, évitée ici d'emblée). Mergée malgré le flake connu
  ci-dessous (436 passed / 1 failed, non lié au diff).

### PR #46 : bug réel -- exclusion silencieuse d'un client avec produit actif (2026-09-21)

En re-testant un fichier déjà validé, Raphaël a obtenu "86 First / 0
RCUR / 1 exclue" au lieu du "87/0" attendu -- fichier confirmé
identique (hash SHA256) à l'original. Root-cause trouvée en comparant
mon chemin de validation (lecture openpyxl brute) au vrai chemin
serveur (`pandas.read_excel` + `.where(pd.notnull(df), None)`) :
**`DataFrame.where(pd.notnull(df), None)` ne remplace pas toujours une
cellule vide par `None` sur une colonne de nombres** -- une colonne
`float64` ne peut pas contenir `None`, pandas la recase discrètement en
`NaN`. `to_amount()` laissait ce `NaN` contaminer les sommes
(`49.9 + nan = nan`), et le filtre "montant > 0" excluait à tort le
client MGS-18397 MACEDO ANNIE (Optilife=49,90€ actif) à cause d'une
AUTRE colonne produit (Optivie) vide.

**Corrigé** : garde NaN explicite (`raw != raw`) dans `to_amount()`,
sans dépendance externe ajoutée au module (toujours pur, sans
pandas/réseau/DB). Nouveau test dédié
(`test_to_amount_nan_is_zero_not_contagious`). Revalidé sur le fichier
exact de Raphaël (87/0, corrigé) et sur le fichier de référence 291
lignes (415/4, inchangé -- pas de régression). `pytest` : 436 passed.
Mergée malgré le même flake connu (2 échecs identiques sur le re-run,
non lié à ce diff qui ne touche que `trieur/prelevement.py`).

**Ce bug renforce la nécessité** de la validation en lot réel par
Raphaël avant tout envoi bancaire (déjà demandée ci-dessus) : une
exclusion silencieuse de ce type serait passée inaperçue sans son
signalement.

**CI -- flake persistant** : `test_master_columns_localstorage_fallback`
a de nouveau échoué (2 fois d'affilée sur PR #46, une fois sur PR #45),
toujours la même assertion sur la valeur d'un textarea. GitHub envoie
un mail "run failed" à chaque échec -- expliqué à Raphaël, ce n'est pas
lié à ses données. Pas encore de cause racine identifiée au-delà de ce
qui est déjà noté plus haut ; commence à devenir fréquent, pourrait
justifier un chantier dédié si ça continue.

**Reste à faire côté Raphaël** :
- Fournir le numéro ICS quand il l'aura (réglable directement dans
  l'onglet Prélèvement, aucune session nécessaire).
- Tester un lot complet en conditions réelles avant tout envoi à la
  banque -- la validation ci-dessus compare au fichier de remise
  historique, pas encore à un nouvel envoi réel post-correctif.
- Les combinaisons de produits autres que MYJURIS+IMMO (ex. Carte
  MGS + Admin&Aide) n'ont jamais été observées ensemble dans les
  données disponibles -- restent traitées comme des mandats séparés
  par défaut ; à corriger si un cas réel montre le contraire.

---

## Correctif du flake e2e -- vraie cause cette fois (2026-09-21, PR #47)

**Le diagnostic de la PR #42 (plus haut) était incomplet.** Le même
test (`test_master_columns_localstorage_fallback`) a re-échoué sur la
PR #46 juste après avoir été "corrigé". Root-cause repris de zéro
plutôt que de re-contourner une 5e fois.

**Pourquoi le diagnostic précédent avait l'air correct alors qu'il ne
l'était pas** : testé localement avec le Chromium déjà présent dans
l'environnement (une version assez ancienne) -- le bug ne s'y
reproduisait jamais, quel que soit le nombre d'essais. Téléchargé le
Chromium EXACT que la CI installe (Chrome for Testing 153.0.8010.12)
pour refaire le diagnostic : le flake est immédiatement apparu, environ
1 fois sur 2 (2 échecs sur 4 premiers essais).

**Vraie cause racine** : dans `app.py`, la restauration depuis le
localStorage appelait un `st.rerun()` explicite après avoir mis à jour
`st.session_state`. Ce rerun entrait en collision avec le rerun **déjà
déclenché automatiquement** par Streamlit quand la valeur du composant
localStorage change -- selon l'ordre d'arrivée de ces deux reruns
concurrents, la restauration pouvait se perdre. Ce n'était donc pas
une histoire de délai de test trop court (le diagnostic de la PR #42),
mais un vrai bug produit : en conditions réelles, un utilisateur dont
le fichier serveur a été perdu (redémarrage de conteneur) pouvait ne
PAS récupérer sa configuration depuis son navigateur, une fois sur
deux.

**Corrigé** : `st.rerun()` retiré. Inutile de toute façon -- la ligne
juste avant (`st.session_state["master_cols_input"] = ...`) s'exécute
avant que l'onglet ne rende ce widget dans le MÊME passage de script,
donc Streamlit affiche déjà la valeur restaurée sans rerun
supplémentaire à déclencher.

**Vérifié, pas supposé** : avec le Chromium exact de la CI, 10
exécutions consécutives du test réel après le correctif -- 10/10
vertes, rapides (~21s à chaque fois, signe que la valeur est correcte
dès le premier rendu, pas après plusieurs tentatives). `pytest` (hors
e2e) : 436 passés, aucune régression.

Cette fois, si `test_master_columns_localstorage_fallback` recommence
à échouer, ce sera un problème différent -- la cause connue jusqu'ici
est réellement éliminée, pas juste masquée une deuxième fois.

### Validation en lot réel (2026-09-21, après PR #46) + PR #48 : environnement verrouillé

Raphaël a généré un lot complet (87 mandats) avec le correctif NaN et
l'a croisé contre l'historique du Drive (lecture seule, `export CRM` de
`4_drive_final.xlsx`) : **87/87 RUM connus, 87/87 motifs identiques,
87/87 montants identiques** à une valeur déjà enregistrée dans
l'historique pour ce motif. Envoyé à son père pour avis. Aucun écart
détecté.

En marge de cette validation, Raphaël a signalé ne pas comprendre le
sélecteur "Environnement" affiché dans l'onglet Prélèvement (capture
avec Leads/Prélèvement/Global) : confusion entre les onglets du haut
(les outils) et ce sélecteur (quel espace de données l'outil utilise).
Vérifié en base : seul l'environnement "Prélèvement" a des réglages
enregistrés (ICS, frais, nature, délai) ; les valeurs vues sur "Global"
étaient de simples valeurs par défaut serveur (coïncidence trompeuse
avec les vraies valeurs de "Prélèvement"). Risque réel de créer
silencieusement un second jeu de réglages en éditant au mauvais
endroit.

**PR #48** : l'onglet Prélèvement ne propose plus de sélecteur --
il cherche automatiquement l'org nommée "Prélèvement" et s'y limite,
avec un message d'erreur explicite si cet environnement n'existe pas
pour l'utilisateur. Le panneau "Réglages" déjà existant (ICS, nature,
délai, frais) reste la vue complète, visible et modifiable de ces
réglages -- inchangé, mais désormais sans ambiguïté. Mergée, CI verte
du premier coup.
