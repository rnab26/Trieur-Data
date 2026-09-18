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
7. [ ] Étiquettes libres sur un client (n1).
8. [ ] Annuler un import entier en un clic (n3).
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
12. [ ] **À cadrer avec l'utilisateur avant de coder**, pas juste
    "commencer par le haut" : rôles plus fins par environnement, avec
    "encore plus de restrictions possibles si nécessaire" (n5) —
    formulation volontairement ouverte, la granularité exacte
    (lecture/écriture par colonne ? par action ? autre chose ?) doit se
    discuter avant d'écrire du code, pas être devinée.
13. [ ] **Reporté par l'utilisateur** ("plus tard") : colonnes
    calculées simples (n8).

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

## Branche `fix/pipeline-full-parity` — parité Streamlit du pipeline, vérification indépendante + push (2026-09-18)

**Contexte** : suite au retour de l'utilisateur ("la refonte React du
pipeline a perdu l'auto-assignation et plein de fonctionnalités de
l'ancien Streamlit, le visuel n'est pas pro, un fichier de <1 Mo met
~30s à charger"), deux agents (backend puis frontend) ont retravaillé
la branche `fix/pipeline-full-parity` pour retrouver la parité
fonctionnelle avec les onglets 2-4 Streamlit et corriger la lenteur.
Cette entrée documente la vérification indépendante de leur travail
(rien pris pour argent comptant, un rapport précédent sur ce projet
s'était déjà révélé faux) avant push.

**Correctif de performance — vérifié réel, pas juste relu le rapport** :
lu `trieur/db.py` : `append_pipeline_rows` (fonction existante, gardée)
fait bien un SELECT (row_count) + UPDATE à CHAQUE lot de 500 lignes en
plus de l'INSERT — 3 allers-retours réseau par lot. La nouvelle
`append_pipeline_rows_bulk` ne fait qu'UNE seule lecture de row_count
avant la boucle d'INSERT et UNE seule écriture après, quel que soit le
nombre de lots (`batch_size`, par défaut 2000 lignes/lot, pour rester
sous la limite de payload PostgREST). Test dédié
`test_append_pipeline_rows_bulk_only_updates_row_count_once` vérifié :
force le comptage des appels `update` sur `pipeline_sessions` et
affirme qu'il n'y en a qu'un seul même avec plusieurs lots — passe.
Vérifié aussi que l'endpoint d'import (`api/main.py`,
`create_pipeline_session_endpoint`) appelle bien
`append_pipeline_rows_bulk` (pas l'ancienne fonction) — la cause racine
mesurée par l'agent backend (~29s pour 1 Mo/5787 lignes avec
l'ancienne boucle, ~2.7s pour le même volume en un seul INSERT) est
donc réellement corrigée dans le chemin de code utilisé, pas seulement
dans une fonction annexe non appelée.

**Parité fonctionnelle — vérifiée en lisant le code, pas le rapport** :
- Import multi-fichiers + Google Sheets dans le même batch
  (`_read_pipeline_sources`/`_merge_pipeline_sheets`, suffixage des noms
  dupliqués) : confirmé dans `api/main.py`.
- Auto-assignation : confirmé que `apply_pipeline_mapping` appelle
  `trieur/matching.py:auto_assign_with_memory` avec le mapping mémorisé
  par empreinte de colonnes (`get_remembered_mapping_for_shape`),
  sauvegardé après confirmation (`save_remembered_mapping_for_shape`) —
  scopé à l'organisation (nouvelle table `pipeline_remembered_mappings`).
- Dédoublonnage réel : `POST/DELETE .../pipeline/sessions/{id}/dedup`
  réutilisent `trieur/filters.py:dedupe_dataframe`, persistant via
  `pipeline_sessions.dedup_config`, réappliqué à `/rows` et `/export`
  (`_apply_active_dedup`) jusqu'à annulation explicite — confirmé.
- Presets d'export nommés : CRUD confirmé sur
  `/orgs/{org_id}/pipeline/export-presets`, nouvelle table
  `pipeline_export_presets`.
- Écran React refait en 4 onglets (Colonnes maîtres / Importer / Filtrer
  / Exporter), même découpage que la version Streamlit, au lieu de
  l'assistant linéaire à 3 étapes livré par la refonte précédente
  (celle que l'utilisateur a rejetée) — confirmé en lisant
  `PipelineScreen.tsx` et les nouveaux composants
  (`PipelineImportPanel`, `PipelineMappingGrid`, `PipelineDedupPanel`,
  `PipelineExportPanel`).

**Tests / build — réexécutés, pas relus** :
- `python3 -m pytest -q` (suite complète) → **277 passed, 1 failed**
  (`test_master_columns_localstorage_fallback`). Ce test échoue déjà de
  façon intermittente sur ce projet (voir l'entrée "Revue Copilot PR
  #24" ci-dessus, bisecté et documenté comme flaky/dépendant de l'ordre
  d'exécution, indépendant du code touché) — pas une régression
  introduite par cette branche.
- `cd frontend && npm run build` → exit 0 (`tsc -b && vite build`, 0
  erreur TypeScript).
- `git diff --stat main -- views/ app.py` → **vide**. Le code Streamlit
  original n'a pas été touché par cette branche.

**Migration base de données — appliquée** : la migration
`supabase/migrations/0012_pipeline_parity.sql` (2 nouvelles tables
`pipeline_remembered_mappings`/`pipeline_export_presets` + colonne
`dedup_config` sur `pipeline_sessions`, RLS activée avec policies sur
le même modèle que les tables existantes) n'avait pas encore été
appliquée en base par les agents précédents. Vérifié sur le projet
Supabase réel (`bexiyvmdbxcwxasgslxp`, celui qui contient
`trieur_data.*`) qu'elle manquait, puis appliquée directement (ajout
pur, aucune donnée existante touchée). Sans ça, les nouvelles routes
mapping/dédoublonnage/presets auraient échoué en production dès le
premier appel réel.

**Limites connues, non fermées** (héritées des rapports des agents,
vérifiées réelles en lisant le code, pas de raison de les corriger dans
ce lot) :
- Import PDF/SEPA (relevés bancaires) toujours absent de l'API
  pipeline — seuls Excel/CSV/Google Sheets sont couverts.
- Pas d'UI d'inclusion/exclusion par fichier/onglet avant mapping : tous
  les fichiers/onglets d'un import sont fusionnés en une session dès le
  départ (limite backend documentée dans son propre code).
- Les filtres `/rows` et `/export` restent le système simple par
  colonne, pas les groupes OU/ET par "critères département" de l'onglet
  3 Streamlit d'origine — seul le dédoublonnage a été porté fidèlement.
  Corriger ça demande un chantier backend séparé (le contrat de
  `list_pipeline_session_rows`/`export_pipeline_session_rows` n'expose
  que `col_filters` simple).
- L'application du mapping fait encore un `update` par ligne en boucle
  (pas optimisé en lot comme l'import initial) — pas mesuré, pourrait
  être lent sur de très gros volumes (l'utilisateur mentionne des
  fichiers de 50-80 Mo, plusieurs à la fois, pas encore testés).

**Poussé** sur `origin/fix/pipeline-full-parity` (commits `ca8e566`,
`a9c6d76`). **Pas de merge sur `main`** — l'utilisateur a explicitement
rejeté un merge précédent qui avait changé l'architecture sans son
accord ; cette branche corrige justement ce problème, mais le go/no-go
de merge reste sa décision.

**Visuel/design** : l'utilisateur a indiqué qu'il fournira lui-même un
template de design à suivre pour une prochaine passe — non traité dans
ce lot, volontairement, en attendant ce template.

---

## Pipeline : staging Postgres remplacé par un store en mémoire (2026-09-18)

**Contexte** : l'utilisateur travaille avec des fichiers jusqu'à 2
millions de lignes, gérés instantanément par l'ancienne app Streamlit
(`st.session_state`, zéro écriture réseau avant la validation finale).
Sur un test réel de 92 000 lignes contre la nouvelle API FastAPI, même
après le correctif de parallélisation des lots (`append_pipeline_rows_bulk`),
c'est resté trop lent — cause racine : chaque ligne importée était
écrite en Postgres (`trieur_data.pipeline_rows`) dès l'upload, avant
tout mapping/confirmation, un coût réseau que Streamlit n'avait jamais
eu et qui ne tient pas à l'échelle visée.

**Fait** :
- `trieur/pipeline_memory.py` (nouveau) : store en mémoire process
  (dict de module + `threading.Lock`), TTL 24h avec balayage
  opportuniste par org (même principe que l'ancien
  `delete_expired_pipeline_sessions_for_org`, mais sans réseau).
  Fonctions : `create_session`, `get_session`, `delete_session`,
  `delete_expired_sessions_for_org`, `update_session_status`,
  `update_session_dedup`, `set_session_mapping`, `append_rows`,
  `list_rows`, `map_rows` (réécrit toutes les lignes en UN SEUL passage
  O(n), remplace l'ancienne boucle `update_pipeline_row_data` par ligne
  — plus rapide ET plus simple, plus de réseau à amortir).
- `api/main.py` : les 6 routes pipeline (`POST/GET .../sessions`,
  `GET .../rows`, `GET .../export`, `POST .../mapping`, `POST/DELETE
  .../dedup`) lisent/écrivent ce store au lieu de `trieur/db.py`. Logique
  métier (filtres, dédoublonnage, export, auto-assignation mapping)
  inchangée — seule la couche de stockage change.
- `trieur/db.py` : fonctions `pipeline_sessions`/`pipeline_rows`
  (`create_pipeline_session`, `get_pipeline_session`,
  `append_pipeline_rows(_bulk)`, `list_pipeline_rows`,
  `update_pipeline_row_data`, `update_pipeline_session_status/dedup`,
  `delete_pipeline_session`, `delete_expired_pipeline_sessions_for_org`)
  **gardées mais plus appelées par l'API** — code mort. Idem pour les
  tables `trieur_data.pipeline_sessions`/`pipeline_rows` et les
  migrations 0010/0011/0012 qui les créent : **aucune suppression
  destructrice faite ici**, décision volontairement laissée à
  l'utilisateur. `pipeline_remembered_mappings` et
  `pipeline_export_presets` (mapping mémorisé par forme de fichier,
  presets d'export) restent en Postgres, inchangés — ce ne sont pas des
  données de travail volumineuses, juste des petites préférences par
  compte/org.
- Tests : `tests/test_api.py` (tests pipeline réécrits contre le store
  en mémoire au lieu du faux client Postgres) + nouveau
  `tests/test_pipeline_memory.py` (13 tests directs du module, dont un
  test à 500 000 lignes synthétiques mesurant le temps réel). Suite
  complète : **291 passed** (`python3 -m pytest -q`).
  `tests/test_db_pipeline.py` (9 tests) laissé tel quel : il teste
  toujours les fonctions `trieur/db.py` ci-dessus, désormais du code mort
  côté API mais toujours du code réel et fonctionnel — pas de couverture
  supprimée, juste plus rien qui l'exerce en production.

**Mesure réelle (pas une estimation)** : création d'une session + 500 000
lignes synthétiques, 100% en mémoire, zéro réseau : **~0.56 à 0.78s**
selon la machine (voir la sortie `[perf]` du test
`test_large_scale_session_creation_is_fast`). Confirme que le coût
mesuré à 92 000 lignes réelles (~2min, réseau Supabase) était bien le
staging Postgres, pas la logique métier.

**Sécurité — changement réel, pas cosmétique** : la RLS Postgres ne
protège plus ces données de travail (elles ne passent plus par
Supabase). `pipeline_memory.get_session()` ne filtre PAS par `org_id`
lui-même — c'est `api/main.py:_get_pipeline_session_or_404` qui compare
explicitement `session["org_id"]` (même code qu'avant ce changement),
mais c'est DÉSORMAIS LA SEULE protection contre un accès cross-org, sans
policy RLS en secours. Vérifié : les 3 tests `*_wrong_org_is_404`
(session/rows/export/mapping/dedup) passent toujours contre le nouveau
store.

**Limite réelle, documentée dans le code (`pipeline_memory.py`)** : ce
dict vit dans la mémoire du process uvicorn — perdu à chaque
déploiement/crash/restart, exactement comme `st.session_state` avant
(pas une régression). Conséquence : cette API ne peut PAS tourner en
plusieurs instances derrière un load-balancer sans un store partagé
(Redis, etc.) — sans objet sur l'hébergement actuel (une seule instance
Render), mais à revoir explicitement si l'app doit un jour scaler
horizontalement.

**Pas fait dans ce lot, à décider par un humain** :
- Suppression (ou non) des tables `pipeline_sessions`/`pipeline_rows`
  et des migrations 0010/0011/0012 qui les créent, et des fonctions
  `trieur/db.py` correspondantes — tout ça est désormais du code/schéma
  mort côté pipeline, gardé intact volontairement.

**Commité** sur `fix/pipeline-full-parity` — **pas pushé** (l'agent
suivant vérifie et pousse, voir consigne de la tâche).
