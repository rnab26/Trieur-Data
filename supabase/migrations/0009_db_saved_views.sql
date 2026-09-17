-- =============================================================
-- Vues enregistrées, nommées (chantier 5/8, voir PROJECT_LOG.md) :
-- une combinaison recherche + filtres par colonne + colonnes affichées
-- de la Base de données, sauvegardée sous un nom et rappelable en un
-- clic -- même principe que les filtres enregistrés du Trieur de Data
-- (tab3_filtrage_dedup.py), mais liée au COMPTE (comme les colonnes
-- maîtres de 0003), pas à l'organisation : chaque utilisateur garde ses
-- propres vues, quel que soit qui d'autre travaille sur le même
-- environnement.
-- =============================================================

create table trieur_data.db_saved_views (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    name text not null,
    search text not null default '',
    col_filters jsonb not null default '{}'::jsonb,
    visible_cols jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (user_id, org_id, name)
);

create index db_saved_views_user_org_idx on trieur_data.db_saved_views (user_id, org_id);

alter table trieur_data.db_saved_views enable row level security;

-- Contrairement à user_master_column_sets (0003, sans org_id), cette
-- table référence un environnement précis : la ligne doit donc rester
-- soumise à la même règle d'appartenance que le reste du schéma
-- (records, dedup_alerts, chantiers...), pas seulement à l'identité du
-- propriétaire -- sinon un utilisateur retiré d'un environnement garde
-- un accès permanent aux vues qu'il y avait enregistrées, et rien
-- n'empêche de viser un org_id auquel on n'a jamais appartenu.
create policy db_saved_views_own on trieur_data.db_saved_views
    for all using (user_id = auth.uid() and trieur_data.is_org_member(org_id))
    with check (user_id = auth.uid() and trieur_data.is_org_member(org_id));
