-- =============================================================
-- Correctif fiabilité (revue GitHub Copilot, PR #25, sur la migration
-- 0014 elle-même) : le jeton propriétaire (0014) empêche une requête
-- périmée de libérer le verrou d'une requête plus récente, mais ne
-- protège PAS l'opération entière -- si l'analyse+suppression dépasse
-- la TTL (30s), une 2e requête peut réclamer le verrou pendant que la
-- 1re continue son calcul, et les deux peuvent encore supprimer des
-- choix incompatibles (la 1re avec des données déjà périmées).
--
-- Un vrai verrou tenu pendant toute l'opération demanderait soit une
-- transaction SQL unique couvrant tout le calcul (la logique de
-- dédoublonnage reste en Python, voir migration 0013), soit un
-- heartbeat réseau -- disproportionné pour un outil interne mono-poste.
-- Correctif retenu, proportionné : juste avant la suppression (le point
-- de non-retour), l'appelant revérifie qu'il est TOUJOURS propriétaire
-- du verrou. Si un autre appel l'a repris entretemps (verrou expiré et
-- réclamé), on abandonne sans rien supprimer plutôt que de continuer sur
-- une analyse devenue périmée -- réduit la fenêtre de course de "toute
-- la durée de l'opération" à l'instant entre cette vérification et le
-- DELETE qui suit immédiatement.
-- =============================================================

create or replace function trieur_data.is_pipeline_dedupe_lock_owner(p_session_id uuid, p_owner text)
returns boolean
language sql
security invoker
set search_path = trieur_data
as $$
    select coalesce(
        (select dedupe_lock_owner = p_owner from trieur_data.pipeline_sessions where id = p_session_id),
        false
    );
$$;

grant execute on function trieur_data.is_pipeline_dedupe_lock_owner(uuid, text) to authenticated;
