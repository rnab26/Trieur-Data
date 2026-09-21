-- =============================================================
-- Règles de génération des mandats de prélèvement (Raphaël,
-- 2026-09-21) : issu de l'analyse du classeur Excel de référence du
-- père de Raphaël (3 fichiers + le classeur Drive historique).
-- Réglages qui doivent pouvoir être ajustés sans toucher au code
-- (ICS, nature CORE/B2B, délai minimum avant le 1er prélèvement) --
-- une ligne par organisation, comme org_settings/dedup_config.
-- =============================================================

create table trieur_data.prelevement_rules (
    org_id uuid primary key references trieur_data.organizations (id) on delete cascade,
    ics text,
    nature text not null default 'CORE' check (nature in ('CORE', 'B2B')),
    delay_days integer not null default 3 check (delay_days >= 0),
    updated_at timestamptz not null default now(),
    updated_by uuid
);

alter table trieur_data.prelevement_rules enable row level security;

create policy prelevement_rules_rw on trieur_data.prelevement_rules
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));
