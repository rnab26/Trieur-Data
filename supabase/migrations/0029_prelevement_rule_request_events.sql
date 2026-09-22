-- =============================================================
-- Journal d'activité en direct sur une demande de modification de
-- règle Prélèvement (Raphaël, 2026-09-22) -- une session Claude Code
-- y écrit de courts messages pendant qu'elle travaille dessus ("je
-- regarde le code existant", "PR créée, CI en cours", "déployé"...),
-- pour que le fil soit visible sur le site en quasi direct, plutôt
-- que découvert après coup dans le journal PROJECT_LOG.md. Même
-- principe que prelevement_rule_request_questions (migration 0026) :
-- table à part, cascade sur la demande, RLS via son org_id.
-- =============================================================

create table trieur_data.prelevement_rule_request_events (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null references trieur_data.prelevement_rule_requests (id) on delete cascade,
    message text not null,
    created_at timestamptz not null default now()
);

create index prelevement_rule_request_events_request_idx
    on trieur_data.prelevement_rule_request_events (request_id, created_at);

alter table trieur_data.prelevement_rule_request_events enable row level security;

create policy prelevement_rule_request_events_rw on trieur_data.prelevement_rule_request_events
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
