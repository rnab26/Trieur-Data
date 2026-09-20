-- =============================================================
-- Régularisation du dépôt (drift trouvé le 2026-09-20) : cette migration
-- a été appliquée à la base réelle le 2026-09-18 (version
-- `20260918111901`, voir `list_migrations`) par une session travaillant
-- sur la branche `fix/pipeline-full-parity` -- jamais mergée sur `main`,
-- son fichier n'existait donc pas ici alors que le schéma, lui, était
-- déjà en place. Contenu copié tel quel depuis cette branche (aucune
-- ligne changée) pour que `main` reflète enfin le schéma réel.
--
-- Déjà appliquée sur la base de PRODUCTION actuelle -- ne l'exécute pas
-- à la main dessus (les `create table` échoueraient, les objets
-- existent déjà). Reste une migration normale et rejouable dans la
-- séquence complète (0001 à N) pour initialiser une base neuve (reset
-- local, nouveau projet Supabase).
--
-- Crée trois éléments non utilisés par l'API actuelle de `main` (le
-- portage fidèle du 2026-09-20 a documenté leur absence comme un écart
-- volontaire) : ils restent en base, inertes, tant que personne ne les
-- câble côté API/frontend.
--
-- 1) Mémoire du mapping PAR FORME DE FICHIER (trieur/matching.py:
--    column_fingerprint/auto_assign_with_memory), scopée à l'ORGANISATION
--    (pas au compte) : plusieurs membres d'un même environnement
--    réimportent souvent le même type de fichier, et doivent tous
--    profiter du mapping déjà confirmé par un collègue -- même principe
--    que master_columns (par org, pas par utilisateur). Remplace le
--    fichier JSON local `remembered_mappings.json` (trieur/persistence.py),
--    qui ne survit pas à un redeploy et n'est pas partagé entre comptes.
--
-- 2) Presets d'export nommés (ordre + sélection des colonnes, onglet 4),
--    scopés au COMPTE + à l'organisation -- même patron que
--    db_saved_views (0009) : une préférence d'affichage personnelle, pas
--    une donnée métier partagée.
--
-- 3) Dédoublonnage actif sur une session de pipeline (onglet 3) : doit
--    "persister et se réappliquer à chaque rerun jusqu'à annulation
--    explicite" (voir tab3_filtrage_dedup.py) -- stocké directement sur
--    la session, pas une table séparée (un seul dédoublonnage actif par
--    session à la fois).
-- =============================================================

create table trieur_data.pipeline_remembered_mappings (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    fingerprint text not null,
    mapping jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    unique (org_id, fingerprint)
);

comment on table trieur_data.pipeline_remembered_mappings is
    'Mapping colonnes source -> colonnes maîtres CONFIRMÉ, mémorisé par empreinte de forme de fichier (trieur/matching.py:column_fingerprint) -- rejoué automatiquement au prochain import de même forme (trieur/matching.py:auto_assign_with_memory), remplace remembered_mappings.json.';

create index pipeline_remembered_mappings_org_idx on trieur_data.pipeline_remembered_mappings (org_id);

alter table trieur_data.pipeline_remembered_mappings enable row level security;

create policy pipeline_remembered_mappings_rw on trieur_data.pipeline_remembered_mappings
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));


create table trieur_data.pipeline_export_presets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    name text not null,
    included jsonb not null default '[]'::jsonb,
    excluded jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (user_id, org_id, name)
);

comment on table trieur_data.pipeline_export_presets is
    'Presets d''export nommés (ordre + sélection des colonnes, onglet 4 Trieur de Data) -- remplace export_presets.json, même patron que db_saved_views (par compte + organisation).';

create index pipeline_export_presets_user_org_idx on trieur_data.pipeline_export_presets (user_id, org_id);

alter table trieur_data.pipeline_export_presets enable row level security;

create policy pipeline_export_presets_own on trieur_data.pipeline_export_presets
    for all using (user_id = auth.uid() and trieur_data.is_org_member(org_id))
    with check (user_id = auth.uid() and trieur_data.is_org_member(org_id));


alter table trieur_data.pipeline_sessions
    add column dedup_config jsonb;

comment on column trieur_data.pipeline_sessions.dedup_config is
    'Colonne créée par la branche fix/pipeline-full-parity pour un dédoublonnage actif réappliqué à chaque lecture ({"column": ..., "keep": "first"|"complete"}, voir tab3_filtrage_dedup.py) -- INERTE sur main : aucun code de api/main.py ne la lit ni ne l''écrit aujourd''hui (main supprime les doublons directement, voir POST .../dedupe). À câbler ou à abandonner selon ce qui est décidé.';
