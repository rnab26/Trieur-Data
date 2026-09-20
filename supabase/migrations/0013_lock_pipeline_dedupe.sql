-- =============================================================
-- Correctif fiabilité (revue GitHub Copilot, PR #25, trouvaille "Rendre
-- l'analyse et la suppression atomiques") :
-- POST .../pipeline/sessions/{id}/dedupe lit toutes les lignes filtrées,
-- calcule les groupes de doublons et le id à garder par groupe EN PYTHON,
-- puis supprime -- plusieurs allers-retours HTTP, jamais une seule
-- transaction SQL. Deux appels concurrents sur la MÊME session (deux
-- onglets ouverts, un double-clic réseau lent) peuvent chacun analyser le
-- même groupe, retenir une ligne différente comme "à garder", puis
-- supprimer chacun la ligne que l'autre voulait garder : le groupe entier
-- disparaît alors qu'aucune requête individuelle n'était incorrecte.
--
-- La logique de dédoublonnage (repose sur trieur/filters.py, portée
-- fidèlement depuis le Python d'origine) reste côté application -- la
-- réécrire en SQL pour une vraie transaction atomique bout en bout serait
-- disproportionné pour un outil interne mono-poste. Correctif retenu :
-- un verrou applicatif court (claim/release) scopé à la session, posé par
-- un UPDATE ... WHERE atomique (donc sans fenêtre de course possible
-- quel que soit le pooling de connexions Postgres/PgBouncer, contrairement
-- à un pg_advisory_lock qui suppose une connexion persistante). Un
-- deuxième appel de dédoublonnage sur la même session pendant qu'un
-- premier est en cours reçoit un 409 explicite au lieu de risquer une
-- suppression incohérente. TTL courte (30s, largement au-dessus du temps
-- d'exécution réel de l'endpoint) : une requête qui crash sans libérer le
-- verrou ne bloque pas la session indéfiniment.
-- =============================================================

alter table trieur_data.pipeline_sessions
    add column dedupe_lock_at timestamptz;

create or replace function trieur_data.try_lock_pipeline_dedupe(p_session_id uuid, p_ttl_seconds integer default 30)
returns boolean
language sql
security invoker
set search_path = trieur_data
as $$
    with claimed as (
        update trieur_data.pipeline_sessions
        set dedupe_lock_at = now()
        where id = p_session_id
          and (dedupe_lock_at is null or dedupe_lock_at < now() - make_interval(secs => p_ttl_seconds))
        returning true
    )
    select coalesce((select true from claimed), false);
$$;

create or replace function trieur_data.unlock_pipeline_dedupe(p_session_id uuid)
returns void
language sql
security invoker
set search_path = trieur_data
as $$
    update trieur_data.pipeline_sessions
    set dedupe_lock_at = null
    where id = p_session_id;
$$;

grant execute on function trieur_data.try_lock_pipeline_dedupe(uuid, integer) to authenticated;
grant execute on function trieur_data.unlock_pipeline_dedupe(uuid) to authenticated;
