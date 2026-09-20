-- =============================================================
-- Régularisation du dépôt (drift trouvé le 2026-09-20) : appliquée à la
-- base réelle le 2026-09-18 (version `20260918144819`, voir
-- `list_migrations`) par la même session/branche que 0016 -- voir sa
-- note pour le contexte. Contenu copié tel quel.
--
-- Déjà appliquée sur la base de PRODUCTION actuelle -- ne l'exécute pas
-- à la main dessus (le `create table` échouerait, la table existe
-- déjà). Reste une migration normale et rejouable dans la séquence
-- complète (0001 à N) pour initialiser une base neuve.
--
-- Filtres multi-critères pré-enregistrés (onglet 3 Streamlit,
-- views/tab3_filtrage_dedup.py -- trieur/filters.py:apply_filter_groups) --
-- scopés au COMPTE + à l'organisation, même patron que
-- pipeline_export_presets (0016). Remplace saved_filters.json
-- (trieur/persistence.py), qui ne survivait pas à un redeploy et
-- n'était pas partagé entre comptes. Non utilisée par l'API actuelle de
-- `main` -- table inerte tant que personne ne la câble.
--
-- groups = liste de GROUPES (OU entre eux), chaque groupe = liste de
-- CRITÈRES (ET entre eux) -- même forme que trieur/persistence.py
-- (voir _is_valid_filter) : {"column", "kind": "departements"|"valeurs", "values": [...]}.
-- =============================================================

create table trieur_data.pipeline_saved_filters (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    name text not null,
    groups jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (user_id, org_id, name)
);

comment on table trieur_data.pipeline_saved_filters is
    'Filtres multi-critères pré-enregistrés (onglet "Filtrer" du Trieur de Data) -- remplace saved_filters.json, même patron que pipeline_export_presets (par compte + organisation).';

create index pipeline_saved_filters_user_org_idx on trieur_data.pipeline_saved_filters (user_id, org_id);

alter table trieur_data.pipeline_saved_filters enable row level security;

create policy pipeline_saved_filters_own on trieur_data.pipeline_saved_filters
    for all using (user_id = auth.uid() and trieur_data.is_org_member(org_id))
    with check (user_id = auth.uid() and trieur_data.is_org_member(org_id));
