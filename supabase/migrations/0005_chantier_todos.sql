-- =============================================================
-- Applique au Cockpit le modèle de mémoire décrit dans le CLAUDE.md
-- global de l'utilisateur ("Mémoire et continuité entre sessions") :
-- "Journal : coche ce qui est fait plutôt que de le supprimer. Note
-- les points restés ouverts."
--
-- Jusqu'ici un chantier n'avait qu'un statut global + un fil de
-- messages en texte libre -- pas de points cochables individuellement.
-- Ajoute une liste de tâches (todos) par chantier, chacune cochée
-- indépendamment, jamais supprimée quand elle est faite (juste cochée).
-- =============================================================

create table trieur_data.chantier_todos (
    id uuid primary key default gen_random_uuid(),
    chantier_id uuid not null references trieur_data.chantiers (id) on delete cascade,
    body text not null,
    done boolean not null default false,
    position integer not null default 0,
    created_at timestamptz not null default now(),
    done_at timestamptz
);

create index chantier_todos_chantier_idx on trieur_data.chantier_todos (chantier_id, position);

alter table trieur_data.chantier_todos enable row level security;

create policy chantier_todos_rw on trieur_data.chantier_todos
    for all using (
        trieur_data.is_org_member((select org_id from trieur_data.chantiers where id = chantier_id))
    )
    with check (
        trieur_data.is_org_member((select org_id from trieur_data.chantiers where id = chantier_id))
    );
