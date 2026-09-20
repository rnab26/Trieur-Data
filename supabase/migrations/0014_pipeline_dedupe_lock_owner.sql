-- =============================================================
-- Correctif fiabilité (revue GitHub Copilot, PR #25, sur la migration
-- 0013 elle-même) : le verrou de dédoublonnage n'avait pas de
-- propriétaire. Si une requête dépasse la TTL (30s), une 2e requête peut
-- réclamer le verrou expiré ; quand la 1re requête atteint son `finally`,
-- elle appelait unlock SANS CONDITION et libérait donc le verrou de la
-- 2e requête -- une 3e requête pouvait alors s'exécuter en même temps
-- que la 2e, exactement la course que la migration 0013 était censée
-- empêcher.
--
-- Correctif : chaque appel génère un jeton (uuid côté Python, voir
-- api/main.py) posé comme propriétaire au moment du claim ;
-- unlock_pipeline_dedupe ne libère le verrou QUE si le jeton fourni
-- correspond toujours au propriétaire actuel -- une requête qui a
-- dépassé sa TTL et perdu la propriété du verrou ne peut plus libérer
-- celui de quelqu'un d'autre.
-- =============================================================

alter table trieur_data.pipeline_sessions
    add column dedupe_lock_owner text;

create or replace function trieur_data.try_lock_pipeline_dedupe(p_session_id uuid, p_owner text, p_ttl_seconds integer default 30)
returns boolean
language sql
security invoker
set search_path = trieur_data
as $$
    with claimed as (
        update trieur_data.pipeline_sessions
        set dedupe_lock_at = now(),
            dedupe_lock_owner = p_owner
        where id = p_session_id
          and (dedupe_lock_at is null or dedupe_lock_at < now() - make_interval(secs => p_ttl_seconds))
        returning true
    )
    select coalesce((select true from claimed), false);
$$;

create or replace function trieur_data.unlock_pipeline_dedupe(p_session_id uuid, p_owner text)
returns void
language sql
security invoker
set search_path = trieur_data
as $$
    update trieur_data.pipeline_sessions
    set dedupe_lock_at = null,
        dedupe_lock_owner = null
    where id = p_session_id
      and dedupe_lock_owner = p_owner;
$$;

grant execute on function trieur_data.try_lock_pipeline_dedupe(uuid, text, integer) to authenticated;
grant execute on function trieur_data.unlock_pipeline_dedupe(uuid, text) to authenticated;

-- Les anciennes signatures (sans p_owner, migration 0013) ne sont plus
-- appelées par le code -- supprimées pour ne pas laisser deux RPC
-- valides avec un comportement différent sous le même nom de fonction.
drop function if exists trieur_data.try_lock_pipeline_dedupe(uuid, integer);
drop function if exists trieur_data.unlock_pipeline_dedupe(uuid);
