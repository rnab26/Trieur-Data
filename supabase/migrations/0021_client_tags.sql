-- =============================================================
-- Étiquettes libres sur un client (chantier Cockpit "Ajouter des
-- étiquettes à un client", ex. "VIP", "à recontacter", "litige") --
-- statut manuel, filtrable dans la liste, comme demandé.
--
-- Table à part (comme db_saved_views, pas une clé de plus dans le jsonb
-- `data` de records) : les étiquettes ne viennent jamais d'un import,
-- se filtrent et se suppriment indépendamment des colonnes de
-- l'environnement, et plusieurs étiquettes par client doivent rester
-- faciles à interroger (une par ligne, pas une chaîne à parser). La
-- table `annotations` du schéma initial (0001) est un texte libre par
-- ligne/lot, pas un ensemble d'étiquettes structurées -- pas réutilisée
-- ici, ce n'est pas le même besoin.
--
-- Dépend de trieur_data.can_write() (migration 0020, "Ajouter un accès
-- en lecture seule") pour la même règle d'écriture que le reste des
-- données clients : un membre lecture seule voit les étiquettes mais ne
-- peut ni en poser ni en retirer.
-- =============================================================

create table trieur_data.record_tags (
    id uuid primary key default gen_random_uuid(),
    org_id uuid not null references trieur_data.organizations (id) on delete cascade,
    record_id uuid not null references trieur_data.records (id) on delete cascade,
    tag text not null,
    created_by uuid references auth.users (id),
    created_at timestamptz not null default now(),
    unique (record_id, tag)
);

create index record_tags_org_idx on trieur_data.record_tags (org_id);
create index record_tags_record_idx on trieur_data.record_tags (record_id);

comment on table trieur_data.record_tags is
    'Étiquettes manuelles libres sur un client (ex: VIP, à recontacter) -- indépendantes des colonnes importées.';

alter table trieur_data.record_tags enable row level security;

create policy record_tags_select on trieur_data.record_tags
    for select using (trieur_data.is_org_member(org_id));
create policy record_tags_insert on trieur_data.record_tags
    for insert with check (trieur_data.can_write(org_id));
create policy record_tags_delete on trieur_data.record_tags
    for delete using (trieur_data.can_write(org_id));
