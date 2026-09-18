-- =============================================================
-- Staging Postgres pour le pipeline "Trieur de Data" (import -> mapping
-- colonnes -> filtre/dedup -> export), onglets 1-4 encore à porter vers
-- FastAPI (voir PROJECT_LOG.md, "Migration React" -- décision
-- d'architecture du 2026-09-18) : un backend FastAPI stateless n'a pas
-- d'équivalent à `st.session_state`, qui portait jusqu'ici le DataFrame
-- intermédiaire d'une étape à l'autre. Choix retenu : Postgres (déjà payé,
-- déjà là), pas Redis (nouveau coût, ou éphémère si self-hébergé sur le
-- même dyno Render) ni fichier/parquet local (le disque de Render ne
-- survit pas à un redeploy).
--
-- Deux tables plutôt qu'un unique jsonb (comme `db_saved_views`) : une
-- ligne Postgres est limitée à ~1 Go via TOAST, ce qui n'est PAS le vrai
-- problème pour "quelques centaines de milliers de lignes" (un tableau
-- jsonb tiendrait largement en taille) -- le vrai problème est que
-- l'étape 3 (filtre/dedup) doit pouvoir FILTRER et METTRE À JOUR des
-- lignes individuellement (ex: retirer une ligne, corriger une valeur
-- après mapping) sans réécrire tout le tableau à chaque fois. Une table
-- `pipeline_rows` avec une ligne Postgres par ligne importée permet ça
-- nativement (update/delete par ligne, filtre SQL), exactement comme
-- `trieur_data.records` le fait déjà côté CRM -- même patron, pas
-- réinventé.
-- =============================================================

-- ---------------------------------------------------------------
-- Une session de pipeline = un import en cours de traitement, tant qu'il
-- n'a pas été validé (bouton "Enregistrer dans la base de données", qui
-- écrit dans `trieur_data.records`, hors staging) ou exporté. Scratch
-- data : TTL courte (24h par défaut), jamais une donnée permanente.
-- ---------------------------------------------------------------
create table trieur_data.pipeline_sessions (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    created_by uuid references auth.users (id),
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '24 hours'),
    status text not null default 'importing'
        check (status in ('importing', 'mapped', 'filtered', 'exported', 'expired')),
    source_filename text,
    row_count integer not null default 0
);

comment on table trieur_data.pipeline_sessions is
    'Session de travail scratch pour le pipeline import->mapping->filtre->export (onglets 1-4 Trieur de Data). TTL via expires_at -- voir trieur_data.cleanup_expired_pipeline_sessions().';
comment on column trieur_data.pipeline_sessions.expires_at is
    'Session abandonnée au-delà de cette date -- éligible au nettoyage (cleanup_expired_pipeline_sessions), jamais lue comme active passé ce délai.';
comment on column trieur_data.pipeline_sessions.status is
    'importing: lignes en cours d''upload/lecture. mapped: colonnes mappées. filtered: filtre/dedup appliqué, prêt pour export. exported: export terminé (session gardée jusqu''à expiration pour permettre de revenir en arrière). expired: marquée par le nettoyage avant suppression effective, valeur transitoire.';

create index pipeline_sessions_org_idx on trieur_data.pipeline_sessions (org_id);
create index pipeline_sessions_expires_at_idx on trieur_data.pipeline_sessions (expires_at);

-- ---------------------------------------------------------------
-- Lignes importées, une ligne Postgres par ligne du fichier -- permet le
-- filtre/dedup (étape 3) et l'édition ligne à ligne sans réécrire tout le
-- lot, contrairement à un unique tableau jsonb sur `pipeline_sessions`.
-- Structure dynamique (colonnes variables selon le fichier importé),
-- donc jsonb comme `trieur_data.records.data` -- même convention.
-- ---------------------------------------------------------------
create table trieur_data.pipeline_rows (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references trieur_data.pipeline_sessions (id) on delete cascade,
    row_index integer not null,
    data jsonb not null,
    unique (session_id, row_index)
);

comment on column trieur_data.pipeline_rows.row_index is
    'Position dans le fichier importé d''origine (0-based) -- ordre d''affichage stable, indépendant de l''ordre d''insertion Postgres.';

create index pipeline_rows_session_idx on trieur_data.pipeline_rows (session_id);

-- ---------------------------------------------------------------
-- RLS : même patron d'appartenance que le reste du schéma
-- (is_org_member(org_id)). `pipeline_rows` n'a pas de org_id propre (pour
-- ne pas dupliquer une valeur déjà portée par la session, même principe
-- que records/dedup_alerts vs leur org_id direct -- mais ici la ligne
-- n'a pas besoin de son propre org_id puisqu'elle n'existe jamais sans
-- session parente) : la policy passe par une sous-requête sur
-- pipeline_sessions, même mécanique que chantier_messages_rw (0001).
-- ---------------------------------------------------------------
alter table trieur_data.pipeline_sessions enable row level security;
alter table trieur_data.pipeline_rows enable row level security;

create policy pipeline_sessions_rw on trieur_data.pipeline_sessions
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));

create policy pipeline_rows_rw on trieur_data.pipeline_rows
    for all using (
        trieur_data.is_org_member(
            (select org_id from trieur_data.pipeline_sessions where id = session_id)
        )
    )
    with check (
        trieur_data.is_org_member(
            (select org_id from trieur_data.pipeline_sessions where id = session_id)
        )
    );

-- ---------------------------------------------------------------
-- Nettoyage des sessions abandonnées (point transverse encore ouvert :
-- PROJECT_LOG.md note que le TTL/nettoyage restait à décider). Fonction
-- SQL prête à être appelée -- PAS de pg_cron installé ici, volontairement
-- (pas de tâche planifiée créée dans cette migration). Deux façons de
-- l'utiliser plus tard, à choisir sans re-migration :
--   - pg_cron, si l'extension est activée sur ce projet Supabase :
--       select cron.schedule(
--           'trieur_data_cleanup_pipeline_sessions', '0 * * * *',
--           $$ select trieur_data.cleanup_expired_pipeline_sessions(); $$
--       );
--   - ou un appel depuis l'app elle-même (ex: au démarrage d'une nouvelle
--     session de pipeline, ou une route API dédiée appelée par un
--     scheduler externe type Render Cron Job) :
--       client.postgrest.schema("trieur_data").rpc(
--           "cleanup_expired_pipeline_sessions", {}
--       ).execute()
-- `security definer` : le nettoyage doit pouvoir supprimer les sessions
-- de TOUTES les organisations en un seul appel, pas seulement celles de
-- l'appelant -- comme marquer_cockpit_vu (0006), pas une action
-- utilisateur normale soumise à la RLS habituelle.
-- ---------------------------------------------------------------
create or replace function trieur_data.cleanup_expired_pipeline_sessions()
returns integer
language plpgsql
security definer
set search_path = trieur_data
as $$
declare
    v_deleted integer;
begin
    delete from trieur_data.pipeline_sessions
    where expires_at < now();

    get diagnostics v_deleted = row_count;
    return v_deleted;
end;
$$;

revoke all on function trieur_data.cleanup_expired_pipeline_sessions() from public;
grant execute on function trieur_data.cleanup_expired_pipeline_sessions() to authenticated, service_role;
