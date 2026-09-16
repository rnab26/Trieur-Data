-- =============================================================
-- Trieur de Data — schéma initial (comptes, organisations, imports, dédup, cockpit)
--
-- Isolation : ce projet Supabase est partagé avec l'app Jarvis. Toutes les
-- tables vivent dans le schéma dédié `trieur_data` (jamais `public`, qui
-- appartient à Jarvis) — aucune table, fonction ou trigger ne touche à
-- l'existant. Seul `auth.users` est partagé entre les deux apps (users
-- Supabase Auth communs), ce qui est voulu : un même compte peut donner
-- accès aux deux outils.
--
-- Modèle métier : isolation par organisation via RLS. "organization" =
-- espace métier (ex: Leads, Prélèvement). Un utilisateur appartient à une
-- ou plusieurs organisations via `memberships`, avec un rôle. Un profil
-- marqué `is_super_admin` voit tout, quelle que soit l'organisation.
-- =============================================================

create schema if not exists trieur_data;

-- ---------------------------------------------------------------
-- Organisations
-- ---------------------------------------------------------------
create table trieur_data.organizations (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    created_at timestamptz not null default now()
);

comment on table trieur_data.organizations is
    'Espace métier isolé (ex: Leads, Prélèvement). Le slug "global" est réservé au cockpit transverse.';

insert into trieur_data.organizations (slug, name) values
    ('leads', 'Leads'),
    ('prelevement', 'Prélèvement'),
    ('global', 'Global (transverse)');

-- ---------------------------------------------------------------
-- Profils (miroir léger de auth.users, propre à Trieur de Data)
-- ---------------------------------------------------------------
create table trieur_data.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    full_name text,
    is_super_admin boolean not null default false,
    created_at timestamptz not null default now()
);

comment on column trieur_data.profiles.is_super_admin is
    'Voit et administre toutes les organisations, y compris le cockpit global.';

-- ---------------------------------------------------------------
-- Appartenance aux organisations
-- ---------------------------------------------------------------
create table trieur_data.memberships (
    user_id uuid not null references auth.users (id) on delete cascade,
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    role text not null default 'member' check (role in ('member', 'org_admin')),
    created_at timestamptz not null default now(),
    primary key (user_id, org_id)
);

-- ---------------------------------------------------------------
-- Fonctions utilitaires RLS
-- ---------------------------------------------------------------
create or replace function trieur_data.is_super_admin()
returns boolean
language sql
security definer
stable
set search_path = trieur_data
as $$
    select coalesce(
        (select is_super_admin from trieur_data.profiles where id = auth.uid()),
        false
    );
$$;

create or replace function trieur_data.is_org_member(target_org_id uuid)
returns boolean
language sql
security definer
stable
set search_path = trieur_data
as $$
    select trieur_data.is_super_admin() or exists (
        select 1 from trieur_data.memberships
        where user_id = auth.uid() and org_id = target_org_id
    );
$$;

-- ---------------------------------------------------------------
-- Lots d'import (traçabilité : fichier, source, qui, quand)
-- ---------------------------------------------------------------
create table trieur_data.import_batches (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    source_filename text not null,
    source_sheet text,
    imported_by uuid references auth.users (id),
    imported_at timestamptz not null default now(),
    row_count integer not null default 0,
    notes text
);

create index import_batches_org_id_idx on trieur_data.import_batches (org_id);

-- ---------------------------------------------------------------
-- Lignes importées (structure dynamique : colonnes maîtres variables
-- selon l'organisation -> stockées en JSONB plutôt qu'en colonnes figées)
-- ---------------------------------------------------------------
create table trieur_data.records (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    batch_id uuid not null references trieur_data.import_batches (id) on delete cascade,
    data jsonb not null,
    iban_normalized text generated always as (
        nullif(upper(regexp_replace(data->>'iban', '\s', '', 'g')), '')
    ) stored,
    created_at timestamptz not null default now()
);

create index records_org_id_idx on trieur_data.records (org_id);
create index records_batch_id_idx on trieur_data.records (batch_id);
create index records_iban_normalized_idx on trieur_data.records (org_id, iban_normalized)
    where iban_normalized is not null;

comment on column trieur_data.records.iban_normalized is
    'IBAN normalisé (espaces retirés, majuscules) — clé de rapprochement dédup prélèvement.';

-- ---------------------------------------------------------------
-- Alertes de doublon détectées à l'import (ex: même IBAN, mandat renvoyé
-- sous un nom différent) — jamais de suppression automatique, juste une
-- file de validation manuelle.
-- ---------------------------------------------------------------
create table trieur_data.dedup_alerts (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    record_id uuid not null references trieur_data.records (id) on delete cascade,
    matched_record_id uuid not null references trieur_data.records (id) on delete cascade,
    match_type text not null default 'iban_exact',
    status text not null default 'pending' check (status in ('pending', 'confirmed_duplicate', 'confirmed_different')),
    created_at timestamptz not null default now(),
    resolved_by uuid references auth.users (id),
    resolved_at timestamptz,
    note text
);

create index dedup_alerts_org_status_idx on trieur_data.dedup_alerts (org_id, status);

-- ---------------------------------------------------------------
-- Annotations libres (sur un lot d'import ou une ligne précise)
-- ---------------------------------------------------------------
create table trieur_data.annotations (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    target_type text not null check (target_type in ('batch', 'record')),
    target_id uuid not null,
    author uuid references auth.users (id),
    body text not null,
    created_at timestamptz not null default now()
);

create index annotations_org_target_idx on trieur_data.annotations (org_id, target_type, target_id);

-- ---------------------------------------------------------------
-- Cockpit : chantiers (par organisation, ou "global" pour transverse)
-- ---------------------------------------------------------------
create table trieur_data.chantiers (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id),
    title text not null,
    status text not null default 'a_faire' check (status in ('a_faire', 'en_cours', 'attente_retour', 'termine', 'abandonne')),
    priority text not null default 'normale' check (priority in ('basse', 'normale', 'haute')),
    created_by uuid references auth.users (id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index chantiers_org_status_idx on trieur_data.chantiers (org_id, status);

-- Fil de discussion par chantier (messages utilisateur <-> Claude)
create table trieur_data.chantier_messages (
    id uuid primary key default gen_random_uuid(),
    chantier_id uuid not null references trieur_data.chantiers (id) on delete cascade,
    author_type text not null check (author_type in ('user', 'claude')),
    author uuid references auth.users (id),
    body text not null,
    created_at timestamptz not null default now()
);

create index chantier_messages_chantier_idx on trieur_data.chantier_messages (chantier_id, created_at);

create or replace function trieur_data.touch_chantier_updated_at()
returns trigger
language plpgsql
set search_path = trieur_data
as $$
begin
    update trieur_data.chantiers set updated_at = now() where id = new.chantier_id;
    return new;
end;
$$;

create trigger chantier_messages_touch_parent
    after insert on trieur_data.chantier_messages
    for each row execute function trieur_data.touch_chantier_updated_at();

-- ---------------------------------------------------------------
-- RLS : activation + politiques (filtrage serveur par organisation)
-- ---------------------------------------------------------------
alter table trieur_data.organizations enable row level security;
alter table trieur_data.profiles enable row level security;
alter table trieur_data.memberships enable row level security;
alter table trieur_data.import_batches enable row level security;
alter table trieur_data.records enable row level security;
alter table trieur_data.dedup_alerts enable row level security;
alter table trieur_data.annotations enable row level security;
alter table trieur_data.chantiers enable row level security;
alter table trieur_data.chantier_messages enable row level security;

create policy organizations_select on trieur_data.organizations
    for select using (trieur_data.is_org_member(id));

create policy profiles_select_self_or_admin on trieur_data.profiles
    for select using (id = auth.uid() or trieur_data.is_super_admin());

create policy profiles_update_self on trieur_data.profiles
    for update using (id = auth.uid());

create policy memberships_select on trieur_data.memberships
    for select using (user_id = auth.uid() or trieur_data.is_super_admin());

create policy import_batches_rw on trieur_data.import_batches
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));

create policy records_rw on trieur_data.records
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));

create policy dedup_alerts_rw on trieur_data.dedup_alerts
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));

create policy annotations_rw on trieur_data.annotations
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));

create policy chantiers_rw on trieur_data.chantiers
    for all using (trieur_data.is_org_member(org_id))
    with check (trieur_data.is_org_member(org_id));

create policy chantier_messages_rw on trieur_data.chantier_messages
    for all using (
        trieur_data.is_org_member((select org_id from trieur_data.chantiers where id = chantier_id))
    )
    with check (
        trieur_data.is_org_member((select org_id from trieur_data.chantiers where id = chantier_id))
    );

-- ---------------------------------------------------------------
-- Auto-création du profil à l'inscription (nom de trigger préfixé pour
-- ne jamais entrer en collision avec un futur trigger ajouté par Jarvis
-- sur la même table auth.users partagée)
-- ---------------------------------------------------------------
create or replace function trieur_data.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = trieur_data
as $$
begin
    insert into trieur_data.profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name')
    on conflict (id) do nothing;
    return new;
end;
$$;

create trigger trieur_data_on_auth_user_created
    after insert on auth.users
    for each row execute function trieur_data.handle_new_user();

-- ---------------------------------------------------------------
-- Exposition API : le schéma doit être ajouté à "Exposed schemas" dans
-- Project Settings > API pour être accessible via l'API REST/PostgREST
-- (fait automatiquement par la migration suivante côté configuration).
-- ---------------------------------------------------------------
grant usage on schema trieur_data to anon, authenticated, service_role;
grant all on all tables in schema trieur_data to authenticated, service_role;
grant all on all sequences in schema trieur_data to authenticated, service_role;
alter default privileges in schema trieur_data grant all on tables to authenticated, service_role;
alter default privileges in schema trieur_data grant all on sequences to authenticated, service_role;
