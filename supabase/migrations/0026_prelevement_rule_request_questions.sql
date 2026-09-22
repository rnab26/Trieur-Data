-- =============================================================
-- Questions à choix cliquables posées par une session Claude Code sur
-- une demande de modification de règle Prélèvement (Raphaël,
-- 2026-09-22) -- même principe que chantier_questions (migration
-- 0018) côté Cockpit : quand une règle demandée n'est pas claire,
-- Claude pose la question ICI plutôt que dans le chat, avec des
-- options cliquables + une réponse libre toujours possible ; la
-- réponse vit dans la même table, lue par la session suivante.
-- =============================================================

create table trieur_data.prelevement_rule_request_questions (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null references trieur_data.prelevement_rule_requests (id) on delete cascade,
    question text not null,
    options jsonb not null default '[]'::jsonb,
    answer text,
    comment text,
    created_at timestamptz not null default now(),
    answered_at timestamptz
);

create index prelevement_rule_request_questions_request_idx
    on trieur_data.prelevement_rule_request_questions (request_id, created_at);

alter table trieur_data.prelevement_rule_request_questions enable row level security;

create policy prelevement_rule_request_questions_rw on trieur_data.prelevement_rule_request_questions
    for all using (
        trieur_data.is_org_member(
            (select org_id from trieur_data.prelevement_rule_requests where id = request_id)
        )
    )
    with check (
        trieur_data.is_org_member(
            (select org_id from trieur_data.prelevement_rule_requests where id = request_id)
        )
    );
