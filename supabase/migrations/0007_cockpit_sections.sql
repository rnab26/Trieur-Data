-- =============================================================
-- Sections pour les chantiers du Cockpit (point 3 de
-- cockpit-kit/FONCTIONNALITES.md). L'utilisateur veut pouvoir grouper
-- ses chantiers par section dès maintenant, pas seulement quand leur
-- nombre grossira -- décision explicite du 17 sept. 2026, qui prime
-- sur la conditionnalité écrite dans le cahier des charges du kit.
--
-- `theme` reste du texte libre sur `chantiers` (comme sur Jarvis) : la
-- table `sections` ne porte que ce que le texte libre ne sait pas porter
-- -- exister sans chantier, avoir un ordre. Les deux ne sont PAS liés par
-- une clé étrangère stricte (le texte peut légèrement diverger si
-- quelqu'un tape un thème sans passer par le sélecteur) -- exactement le
-- choix déjà documenté sur Jarvis, pour la même raison : une FK ici
-- interdirait de créer un chantier avant d'avoir déclaré sa section, ce
-- qui contredirait "on annonce, on ne bloque pas".
-- =============================================================

alter table trieur_data.chantiers add column theme text;

create table trieur_data.sections (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    nom text not null,
    position integer not null default 0,
    created_at timestamptz not null default now(),
    unique (org_id, nom)
);

create index sections_org_idx on trieur_data.sections (org_id, position);

alter table trieur_data.sections enable row level security;

create policy sections_rw on trieur_data.sections
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));
