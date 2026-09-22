-- =============================================================
-- Demandes de modification des règles codées en dur du moteur de
-- prélèvement (Raphaël, 2026-09-22) : les vraies règles de décision
-- (exclusions, FRST/RCUR, liste des produits...) restent du code --
-- mais Raphaël/son père doivent pouvoir écrire "cette règle doit
-- changer, voici comment" directement dans l'écran, sans passer par
-- le chat, pour que Claude Code les traite au message suivant. Pas un
-- moteur qui code lui-même : juste une file d'attente structurée,
-- traitée par une vraie session Claude Code (revue + tests + PR),
-- jamais appliquée automatiquement.
-- =============================================================

create table trieur_data.prelevement_rule_requests (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    titre text not null,
    demande text not null,
    -- en_attente : pas encore traité. en_cours : une session Claude Code
    -- a commencé. valide : le changement est codé, testé et déployé.
    statut text not null default 'en_attente' check (statut in ('en_attente', 'en_cours', 'valide')),
    created_at timestamptz not null default now(),
    created_by uuid,
    updated_at timestamptz not null default now(),
    updated_by uuid
);

create index prelevement_rule_requests_org_idx on trieur_data.prelevement_rule_requests (org_id);

alter table trieur_data.prelevement_rule_requests enable row level security;

create policy prelevement_rule_requests_rw on trieur_data.prelevement_rule_requests
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));
