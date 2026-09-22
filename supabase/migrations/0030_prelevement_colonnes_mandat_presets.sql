-- =============================================================
-- Jeux de colonnes réutilisables pour le fichier de mandats
-- (Raphaël, 2026-09-22 : "il faut aussi pouvoir enregistrer des jeux
-- de colonnes préalables de façon simple et claire... comme on avait
-- sur Streamlit") -- distinct des "colonnes maîtres" (user_column_sets,
-- domaine Trieur de Data/import) : ceci enregistre un instantané complet
-- de colonnes_mandat (ordre + visibilité), scopé à l'organisation
-- (comme colonnes_mandat lui-même), pour appliquer en un clic une
-- disposition déjà préparée plutôt que de tout refaire à la main.
-- =============================================================

create table trieur_data.prelevement_colonnes_mandat_presets (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    name text not null,
    colonnes jsonb not null,
    created_at timestamptz not null default now(),
    created_by uuid
);

create unique index prelevement_colonnes_mandat_presets_org_name_idx
    on trieur_data.prelevement_colonnes_mandat_presets (org_id, lower(name));

alter table trieur_data.prelevement_colonnes_mandat_presets enable row level security;

create policy prelevement_colonnes_mandat_presets_rw on trieur_data.prelevement_colonnes_mandat_presets
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));
