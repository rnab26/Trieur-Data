-- =============================================================
-- Le Cockpit se limitait à une liste de chantiers, sans réponse aux deux
-- questions qui comptent le plus (voir cockpit-kit/FONCTIONNALITES.md,
-- points 1 et 2 -- le cahier des charges partagé avec les autres projets) :
--   - "où j'en suis" -- un résumé plutôt que de tout relire ;
--   - "qu'est-ce qui a changé depuis mon dernier passage".
--
-- Le résumé (point 1) se calcule à la volée depuis `chantiers.status`,
-- rien à stocker. Le repère de dernière visite (point 2), lui, doit
-- vivre en base : sans ça, se reconnecter depuis un autre appareil
-- réannoncerait tout ce qui a déjà été vu -- même piège que documenté
-- sur Jarvis (chantier ae0f3a7b, "le repère suit le compte, pas l'écran").
-- =============================================================

create table trieur_data.visites_cockpit (
    user_id uuid primary key references auth.users (id) on delete cascade,
    vu_le timestamptz not null default now()
);

alter table trieur_data.visites_cockpit enable row level security;

create policy visites_cockpit_rw on trieur_data.visites_cockpit
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());

-- Le repère ne recule JAMAIS, quel que soit l'ordre d'arrivée de deux
-- écrans ouverts en même temps -- c'est la fonction qui le garantit,
-- pas l'appelant (même raison que sur Jarvis : le dernier `upsert` reçu
-- ne doit pas effacer un passage plus récent déjà enregistré).
create or replace function trieur_data.marquer_cockpit_vu()
returns timestamptz
language plpgsql
security definer
set search_path = trieur_data, public
as $$
declare
    v_nouveau timestamptz;
begin
    insert into trieur_data.visites_cockpit (user_id, vu_le)
    values (auth.uid(), now())
    on conflict (user_id) do update
        set vu_le = greatest(trieur_data.visites_cockpit.vu_le, excluded.vu_le)
    returning vu_le into v_nouveau;

    return v_nouveau;
end;
$$;

revoke all on function trieur_data.marquer_cockpit_vu() from public;
grant execute on function trieur_data.marquer_cockpit_vu() to authenticated;
