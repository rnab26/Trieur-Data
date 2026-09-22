-- =============================================================
-- Mandats de prélèvement enregistrés (Raphaël, 2026-09-22) : bouton
-- "Enregistré dans la base de données" après génération d'un lot --
-- demandé en anticipation, avant que la vue de consultation dédiée
-- (chantier séparé, Cockpit) existe. Un lot généré = un batch_id
-- commun à toutes ses lignes, pour pouvoir les regrouper/distinguer
-- plus tard sans avoir à deviner "quelles lignes venaient ensemble".
--
-- Dates stockées en texte (format "JJ/MM/AAAA", tel que généré par
-- trieur/prelevement.py:generate_mandats) plutôt qu'en `date` --
-- décision volontairement minimale pour ce premier chantier ; à
-- revoir si la future vue de consultation a besoin de trier/filtrer
-- par date réelle.
-- =============================================================

create table trieur_data.prelevement_mandats (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    batch_id uuid not null,
    reference_client text,
    nom text,
    rum text,
    type_sequence text,
    motif text,
    montant_eur numeric,
    devise text,
    iban text,
    bic text,
    adresse text,
    ville text,
    code_postal text,
    pays text,
    email text,
    telephone text,
    date_signature_mandat text,
    date_premiere_echeance text,
    date_effet text,
    periodicite text,
    explication_periodicite text,
    ics text,
    created_at timestamptz not null default now(),
    created_by uuid
);

create index prelevement_mandats_org_batch_idx
    on trieur_data.prelevement_mandats (org_id, batch_id);

alter table trieur_data.prelevement_mandats enable row level security;

create policy prelevement_mandats_rw on trieur_data.prelevement_mandats
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));
