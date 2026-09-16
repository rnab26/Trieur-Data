-- =============================================================
-- Trieur de Data — schéma initial (comptes, organisations, imports, dédup, cockpit)
--
-- Modèle : une seule base Postgres, isolation par organisation via RLS.
-- "organization" = espace métier (ex: Leads, Prélèvement). Un utilisateur
-- appartient à une ou plusieurs organisations via `memberships`, avec un
-- rôle. `admin_global` voit tout, quelle que soit l'organisation.
-- =============================================================

-- ---------------------------------------------------------------
-- Organisations
-- ---------------------------------------------------------------
create table public.organizations (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    created_at timestamptz not null default now()
);

comment on table public.organizations is
    'Espace métier isolé (ex: Leads, Prélèvement). Le slug "global" est réservé au cockpit transverse.';

insert into public.organizations (slug, name) values
    ('leads', 'Leads'),
    ('prelevement', 'Prélèvement'),
    ('global', 'Global (transverse)');

-- ---------------------------------------------------------------
-- Profils (miroir léger de auth.users)
-- ---------------------------------------------------------------
create table public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    full_name text,
    is_super_admin boolean not null default false,
    created_at timestamptz not null default now()
);

comment on column public.profiles.is_super_admin is
    'Voit et administre toutes les organisations, y compris le cockpit global.';

-- ---------------------------------------------------------------
-- Appartenance aux organisations
-- ---------------------------------------------------------------
create table public.memberships (
    user_id uuid not null references auth.users (id) on delete cascade,
    org_id uuid not null references public.organizations (id) on delete cascade,
    role text not null default 'member' check (role in ('member', 'org_admin')),
    created_at timestamptz not null default now(),
    primary key (user_id, org_id)
);

-- ---------------------------------------------------------------
-- Fonctions utilitaires RLS
-- ---------------------------------------------------------------
create or replace function public.is_super_admin()
returns boolean
language sql
security definer
stable
set search_path = public
as $$
    select coalesce(
        (select is_super_admin from public.profiles where id = auth.uid()),
        false
    );
$$;

create or replace function public.is_org_member(target_org_id uuid)
returns boolean
language sql
security definer
stable
set search_path = public
as $$
    select public.is_super_admin() or exists (
        select 1 from public.memberships
        where user_id = auth.uid() and org_id = target_org_id
    );
$$;

-- ---------------------------------------------------------------
-- Lots d'import (traçabilité : fichier, source, qui, quand)
-- ---------------------------------------------------------------
create table public.import_batches (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references public.organizations (id),
    source_filename text not null,
    source_sheet text,
    imported_by uuid references auth.users (id),
    imported_at timestamptz not null default now(),
    row_count integer not null default 0,
    notes text
);

create index import_batches_org_id_idx on public.import_batches (org_id);

-- ---------------------------------------------------------------
-- Lignes importées (structure dynamique : colonnes maîtres variables
-- selon l'organisation -> stockées en JSONB plutôt qu'en colonnes figées)
-- ---------------------------------------------------------------
create table public.records (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references public.organizations (id),
    batch_id uuid not null references public.import_batches (id) on delete cascade,
    data jsonb not null,
    iban_normalized text generated always as (
        nullif(upper(regexp_replace(data->>'iban', '\s', '', 'g')), '')
    ) stored,
    created_at timestamptz not null default now()
);

create index records_org_id_idx on public.records (org_id);
create index records_batch_id_idx on public.records (batch_id);
create index records_iban_normalized_idx on public.records (org_id, iban_normalized)
    where iban_normalized is not null;

comment on column public.records.iban_normalized is
    'IBAN normalisé (espaces retirés, majuscules) — clé de rapprochement dédup prélèvement.';

-- ---------------------------------------------------------------
-- Alertes de doublon détectées à l'import (ex: même IBAN, mandat renvoyé
-- sous un nom différent) — jamais de suppression automatique, juste une
-- file de validation manuelle.
-- ---------------------------------------------------------------
create table public.dedup_alerts (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references public.organizations (id),
    record_id uuid not null references public.records (id) on delete cascade,
    matched_record_id uuid not null references public.records (id) on delete cascade,
    match_type text not null default 'iban_exact',
    status text not null default 'pending' check (status in ('pending', 'confirmed_duplicate', 'confirmed_different')),
    created_at timestamptz not null default now(),
    resolved_by uuid references auth.users (id),
    resolved_at timestamptz,
    note text
);

create index dedup_alerts_org_status_idx on public.dedup_alerts (org_id, status);

-- ---------------------------------------------------------------
-- Annotations libres (sur un lot d'import ou une ligne précise)
-- ---------------------------------------------------------------
create table public.annotations (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references public.organizations (id),
    target_type text not null check (target_type in ('batch', 'record')),
    target_id uuid not null,
    author uuid references auth.users (id),
    body text not null,
    created_at timestamptz not null default now()
);

create index annotations_org_target_idx on public.annotations (org_id, target_type, target_id);

-- ---------------------------------------------------------------
-- Cockpit : chantiers (par organisation, ou "global" pour transverse)
-- ---------------------------------------------------------------
create table public.chantiers (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references public.organizations (id),
    title text not null,
    status text not null default 'a_faire' check (status in ('a_faire', 'en_cours', 'attente_retour', 'termine', 'abandonne')),
    priority text not null default 'normale' check (priority in ('basse', 'normale', 'haute')),
    created_by uuid references auth.users (id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index chantiers_org_status_idx on public.chantiers (org_id, status);

-- Fil de discussion par chantier (messages utilisateur <-> Claude)
create table public.chantier_messages (
    id uuid primary key default gen_random_uuid(),
    chantier_id uuid not null references public.chantiers (id) on delete cascade,
    author_type text not null check (author_type in ('user', 'claude')),
    author uuid references auth.users (id),
    body text not null,
    created_at timestamptz not null default now()
);

create index chantier_messages_chantier_idx on public.chantier_messages (chantier_id, created_at);

create or replace function public.touch_chantier_updated_at()
returns trigger
language plpgsql
as $$
begin
    update public.chantiers set updated_at = now() where id = new.chantier_id;
    return new;
end;
$$;

create trigger chantier_messages_touch_parent
    after insert on public.chantier_messages
    for each row execute function public.touch_chantier_updated_at();

-- ---------------------------------------------------------------
-- RLS : activation + politiques (filtrage serveur par organisation)
-- ---------------------------------------------------------------
alter table public.organizations enable row level security;
alter table public.profiles enable row level security;
alter table public.memberships enable row level security;
alter table public.import_batches enable row level security;
alter table public.records enable row level security;
alter table public.dedup_alerts enable row level security;
alter table public.annotations enable row level security;
alter table public.chantiers enable row level security;
alter table public.chantier_messages enable row level security;

create policy organizations_select on public.organizations
    for select using (public.is_org_member(id));

create policy profiles_select_self_or_admin on public.profiles
    for select using (id = auth.uid() or public.is_super_admin());

create policy profiles_update_self on public.profiles
    for update using (id = auth.uid());

create policy memberships_select on public.memberships
    for select using (user_id = auth.uid() or public.is_super_admin());

create policy import_batches_rw on public.import_batches
    for all using (public.is_org_member(org_id))
    with check (public.is_org_member(org_id));

create policy records_rw on public.records
    for all using (public.is_org_member(org_id))
    with check (public.is_org_member(org_id));

create policy dedup_alerts_rw on public.dedup_alerts
    for all using (public.is_org_member(org_id))
    with check (public.is_org_member(org_id));

create policy annotations_rw on public.annotations
    for all using (public.is_org_member(org_id))
    with check (public.is_org_member(org_id));

create policy chantiers_rw on public.chantiers
    for all using (public.is_org_member(org_id))
    with check (public.is_org_member(org_id));

create policy chantier_messages_rw on public.chantier_messages
    for all using (
        public.is_org_member((select org_id from public.chantiers where id = chantier_id))
    )
    with check (
        public.is_org_member((select org_id from public.chantiers where id = chantier_id))
    );

-- ---------------------------------------------------------------
-- Auto-création du profil à l'inscription
-- ---------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name');
    return new;
end;
$$;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();
