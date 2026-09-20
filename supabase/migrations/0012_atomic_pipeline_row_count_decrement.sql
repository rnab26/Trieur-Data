-- =============================================================
-- Correctif fiabilité (revue GitHub Copilot, PR #25) :
-- trieur/db.py:delete_pipeline_rows mettait à jour
-- pipeline_sessions.row_count par un READ (get_pipeline_session) puis un
-- WRITE (update .eq("id", ...)) séparés, calculé côté Python
-- ("ancien - n"). Deux suppressions concurrentes sur la même session
-- (ex: deux onglets ouverts, ou deux requêtes de dédoublonnage envoyées
-- coup sur coup) peuvent lire le même ancien compteur avant que l'autre
-- n'ait écrit sa mise à jour, et chacune écrit "ancien - n" : le
-- compteur final reste au-dessus du nombre réel de lignes restantes
-- (perdu, pas juste temporairement faux) -- UI/réponses API incohérentes
-- avec trieur_data.pipeline_rows, la source de vérité réelle.
--
-- Correctif : un UPDATE ... SET row_count = row_count - delta fait dans
-- la MÊME requête SQL (via ce RPC), donc atomique côté Postgres --
-- aucune fenêtre entre lecture et écriture où une autre transaction peut
-- s'intercaler. `greatest(0, ...)` : un compteur ne descend jamais sous
-- 0 même si l'appelant se trompe de delta (garde déjà présente côté
-- Python avant ce correctif, reprise ici pour ne pas la perdre).
--
-- `security invoker` (pas definer) : le RPC ne fait rien que l'appelant
-- ne pourrait déjà faire par un UPDATE direct sur sa ligne
-- pipeline_sessions -- reste soumis à la policy RLS existante
-- (pipeline_sessions_rw, is_org_member), même principe que
-- find_iban_matches (migration 0002).
-- =============================================================

create or replace function trieur_data.adjust_pipeline_row_count(p_session_id uuid, p_delta integer)
returns integer
language sql
security invoker
set search_path = trieur_data
as $$
    update trieur_data.pipeline_sessions
    set row_count = greatest(0, row_count + p_delta)
    where id = p_session_id
    returning row_count;
$$;

grant execute on function trieur_data.adjust_pipeline_row_count(uuid, integer) to authenticated;
