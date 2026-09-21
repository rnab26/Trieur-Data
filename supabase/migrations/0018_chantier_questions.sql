-- =============================================================
-- Raphaël (2026-09-21) : la "fiche de questions" (choix cliquables +
-- commentaire) que la Routine du Cockpit publie sur un chantier ambigu
-- vivait jusqu'ici sur une page claude.ai à part (Artifact) -- perdue
-- au fil des sessions, invisible depuis le Cockpit tant qu'on n'a pas
-- le lien sous la main. Ici, une question posée sur un chantier vit
-- DANS le Cockpit lui-même (même schéma Supabase que `chantiers`) :
-- une session Claude et l'appli lisent/écrivent la même ligne, donc
-- répondre d'un côté répond automatiquement de l'autre -- pas de
-- dédoublonnage à faire entre les deux environnements.
-- =============================================================

create table trieur_data.chantier_questions (
    id uuid primary key default gen_random_uuid(),
    chantier_id uuid not null references trieur_data.chantiers (id) on delete cascade,
    question text not null,
    -- Options cliquables proposées pour CETTE question (adaptées à son
    -- contenu, pas un jeu figé oui/plus_tard/non) -- tableau de texte
    -- libre, affiché comme des boutons côté CockpitScreen.
    options jsonb not null default '[]'::jsonb,
    answer text,
    comment text,
    created_at timestamptz not null default now(),
    answered_at timestamptz
);

create index chantier_questions_chantier_idx on trieur_data.chantier_questions (chantier_id, created_at);

alter table trieur_data.chantier_questions enable row level security;

create policy chantier_questions_rw on trieur_data.chantier_questions
    for all using (
        trieur_data.is_org_member((select org_id from trieur_data.chantiers where id = chantier_id))
    )
    with check (
        trieur_data.is_org_member((select org_id from trieur_data.chantiers where id = chantier_id))
    );
