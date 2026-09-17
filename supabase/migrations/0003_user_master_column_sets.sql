-- =============================================================
-- Mémoire des colonnes maîtres liée au COMPTE (pas à l'organisation) :
-- un utilisateur enregistre un ou plusieurs jeux de colonnes maîtres,
-- les sélectionne/applique à volonté, et retrouve le dernier appliqué
-- automatiquement à sa prochaine connexion -- quel que soit
-- l'environnement (Leads, Prélèvement...).
--
-- Purement additif : n'affecte en rien l'onglet 1 en mode anonyme
-- (fichier JSON + secours localStorage, inchangés) ni les colonnes
-- maîtres PAR ORGANISATION ajoutées dans 0002 (usage différent : celles
-- de 0002 structurent l'import dans l'onglet "Base de données").
-- =============================================================

create table trieur_data.user_master_column_sets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    name text not null,
    columns jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, name)
);

create index user_master_column_sets_user_idx on trieur_data.user_master_column_sets (user_id);

alter table trieur_data.profiles
    add column if not exists active_master_column_set_id uuid
        references trieur_data.user_master_column_sets (id) on delete set null;

alter table trieur_data.user_master_column_sets enable row level security;

create policy user_master_column_sets_own on trieur_data.user_master_column_sets
    for all using (user_id = auth.uid())
    with check (user_id = auth.uid());
