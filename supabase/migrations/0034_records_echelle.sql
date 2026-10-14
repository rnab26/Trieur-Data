-- 0034 : base de données qui tient à l'échelle (centaines de milliers /
-- millions de lignes par environnement). Chantier cockpit 6547bd6a.
--
-- Mesuré sur un schéma jetable de 500 000 lignes fictives (voir PROJECT_LOG.md) :
-- avant, la recherche et les filtres ne regardaient que le lot déjà chargé
-- (300 lignes) et l'export relisait tout par pages à décalage (offset).
--
-- CETTE MIGRATION NE FAIT QU'AJOUTER (index, fonctions) : rien n'est modifié ni
-- supprimé, idempotente. Les index sont créés sans `concurrently` (impossible
-- dans une migration transactionnelle) : sur une table déjà grosse, les créer
-- à la main avec `create index concurrently ...` avant de la rejouer.

create extension if not exists pg_trgm with schema extensions;

-- 1) Liste paginée / export : "les plus récents de CET environnement" sans tri
--    de toute l'organisation. Sert aussi la pagination par curseur
--    (created_at, id) de l'export.
create index if not exists records_org_created_idx
    on trieur_data.records (org_id, created_at desc, id desc);

-- 2) Texte de recherche d'une ligne : valeurs seulement (pas les noms de
--    colonnes), en minuscules -- c'est ce que cherchait déjà
--    views/tab_database.py:_filter_by_search côté Python.
create or replace function trieur_data.record_search_text(p_data jsonb)
returns text
language sql
immutable
parallel safe
as $$
    select lower(coalesce(string_agg(value, ' '), '')) from jsonb_each_text(p_data);
$$;

create index if not exists records_search_trgm_idx
    on trieur_data.records using gin (trieur_data.record_search_text(data) extensions.gin_trgm_ops);

-- 3) Recherche + filtres par colonne + page, calculés par la base.
--    Mêmes règles que trieur/db.py côté Python (contient / ne contient pas /
--    égal à / vide / non vide, insensible à la casse). Colonnes de filtre
--    comprises : toute clé de `data`, "Fichier source", "Importé le",
--    "Modifié le" et "Étiquettes". "Modifié par" (nom résolu depuis les
--    profils) n'existe pas en base : l'appelant doit la filtrer lui-même.
--    Pagination : soit `p_offset`, soit le curseur (p_after_created, p_after_id)
--    -- le curseur reste rapide à n'importe quelle profondeur (export).
--    `p_with_total` : compte les lignes correspondantes, mais JAMAIS au-delà de
--    p_total_cap + 1 (mesuré : compter 500 000 correspondances coûtait ~25 s,
--    alors que la page elle-même se lit en quelques ms). total > p_total_cap
--    veut dire "plus de p_total_cap".
--    security definer (comme is_org_member lui-même) : la politique de lecture
--    des lignes (is_org_member(org_id)) est vérifiée UNE fois en tête, pas une
--    fois par ligne -- mesuré : l'appel par ligne coûtait à lui seul ~16 s pour
--    compter 500 000 lignes. Même droit qu'avant : lire = être membre de
--    l'environnement (ou super-admin).
create or replace function trieur_data.search_records(
    p_org_id uuid,
    p_search text default '',
    p_filters jsonb default '{}'::jsonb,
    p_limit int default 300,
    p_offset int default 0,
    p_after_created timestamptz default null,
    p_after_id uuid default null,
    p_with_total boolean default false,
    p_total_cap int default 10000
)
returns table (
    id uuid,
    data jsonb,
    created_at timestamptz,
    updated_at timestamptz,
    updated_by uuid,
    source_filename text,
    imported_at timestamptz,
    tags text,
    total bigint
)
language plpgsql
stable
security definer
set search_path = trieur_data, extensions
as $fn$
declare
    v_where text := format('r.org_id = %L', p_org_id);
    v_search text := lower(coalesce(trim(p_search), ''));
    v_col text;
    v_spec jsonb;
    v_op text;
    v_val text;
    v_expr text;
    v_clause text;
    v_batch_ids uuid[];
    v_ids uuid[];
    v_cond text;
    v_neg boolean;
    v_tag_ids uuid[];
    v_limit int := greatest(1, least(coalesce(p_limit, 300), 5000));
    v_needs_b boolean := false;
    v_inner_from text;
    v_sql text;
begin
    if not trieur_data.is_org_member(p_org_id) then
        return;  -- pas membre : aucune ligne, exactement comme la RLS
    end if;

    if v_search <> '' then
        -- le fichier d'origine fait partie du texte cherché (comme avant)
        select coalesce(array_agg(b.id), '{}') into v_batch_ids
        from import_batches b
        where b.org_id = p_org_id and position(v_search in lower(coalesce(b.source_filename, ''))) > 0;
        select coalesce(array_agg(distinct t.record_id), '{}') into v_tag_ids
        from record_tags t
        where t.org_id = p_org_id and position(v_search in lower(t.tag)) > 0;
        v_where := v_where || format(
            ' and (record_search_text(r.data) like %L or r.batch_id = any(%L::uuid[]) or r.id = any(%L::uuid[]))',
            '%' || replace(replace(replace(v_search, '\', '\\'), '%', '\%'), '_', '\_') || '%',
            v_batch_ids, v_tag_ids
        );
    end if;

    for v_col, v_spec in select * from jsonb_each(coalesce(p_filters, '{}'::jsonb)) loop
        v_op := coalesce(v_spec->>'op', 'contient');
        v_val := lower(coalesce(v_spec->>'value', ''));
        if v_col = 'Fichier source' then
            -- peu de fichiers d'import : on retrouve d'abord les fichiers qui
            -- correspondent, puis les lignes par batch_id (index) -- sans joindre
            -- les centaines de milliers de lignes (mesuré : 7 à 15 s avec jointure)
            v_neg := v_op in ('ne contient pas', 'non vide');
            v_cond := case
                when v_op in ('vide', 'non vide') then 'coalesce(b.source_filename, '''') = '''''
                when v_op = 'égal à' then format('lower(coalesce(b.source_filename, '''')) = %L', v_val)
                else format('position(%L in lower(coalesce(b.source_filename, ''''))) > 0', v_val) end;
            execute format('select coalesce(array_agg(b.id), ''{}'') from import_batches b where b.org_id = %L and %s',
                           p_org_id, v_cond) into v_ids;
            v_where := v_where || case when v_neg
                then format(' and not (r.batch_id = any(%L::uuid[]))', v_ids)
                else format(' and r.batch_id = any(%L::uuid[])', v_ids) end;
            continue;
        end if;
        if v_col = 'Étiquettes' then
            -- jointure des étiquettes comme dans l'écran : "a, b"
            v_expr := '(select string_agg(t.tag, '', '' order by t.tag) from record_tags t where t.record_id = r.id)';
        elsif v_col = 'Importé le' then
            v_expr := 'b.imported_at::text';
            v_needs_b := true;
        elsif v_col = 'Modifié le' then
            v_expr := 'r.updated_at::text';
        else
            v_expr := format('r.data->>%L', v_col);
        end if;

        if v_op = 'vide' then
            v_clause := format('coalesce(%s, '''') = ''''', v_expr);
        elsif v_op = 'non vide' then
            v_clause := format('coalesce(%s, '''') <> ''''', v_expr);
        elsif v_op = 'égal à' then
            v_clause := format('lower(coalesce(%s, '''')) = %L', v_expr, v_val);
            -- même condition nécessaire que "contient" (égal => contenu) : index de recherche
            if v_expr like 'r.data->>%' and v_val <> '' then
                v_clause := v_clause || format(
                    ' and record_search_text(r.data) like %L',
                    '%' || replace(replace(replace(v_val, '\', '\\'), '%', '\%'), '_', '\_') || '%'
                );
            end if;
        elsif v_op = 'ne contient pas' then
            v_clause := format('position(%L in lower(coalesce(%s, ''''))) = 0', v_val, v_expr);
        else  -- contient
            v_clause := format('position(%L in lower(coalesce(%s, ''''))) > 0', v_val, v_expr);
            -- condition nécessaire (valeur d'une clé de data => présente dans le
            -- texte de la ligne) : laisse la base utiliser l'index de recherche
            if v_expr like 'r.data->>%' and v_val <> '' then
                v_clause := v_clause || format(
                    ' and record_search_text(r.data) like %L',
                    '%' || replace(replace(replace(v_val, '\', '\\'), '%', '\%'), '_', '\_') || '%'
                );
            end if;
        end if;
        v_where := v_where || ' and (' || v_clause || ')';
    end loop;

    if p_after_id is not null and p_after_created is not null then
        v_where := v_where || format(' and (r.created_at, r.id) < (%L::timestamptz, %L::uuid)', p_after_created, p_after_id);
        p_offset := 0;
    end if;

    -- Page choisie D'ABORD (tri + limite sur les seules colonnes de `records`,
    -- index org_id/created_at/id), détails (fichier d'origine, étiquettes)
    -- ajoutés ensuite aux seules lignes de la page : un décalage profond ne
    -- joint plus toutes les lignes sautées.
    v_inner_from := 'records r' || case when v_needs_b
        then ' left join import_batches b on b.id = r.batch_id' else '' end;
    v_sql := 'select i.id, i.data, i.created_at, i.updated_at, i.updated_by, b2.source_filename, b2.imported_at, '
        || '(select string_agg(t.tag, '', '' order by t.tag) from record_tags t where t.record_id = i.id), '
        || case when p_with_total
                then format('(select count(*) from (select 1 from %s where %s limit %s) c)',
                       v_inner_from, v_where, greatest(coalesce(p_total_cap, 10000), 1) + 1)
                else 'null::bigint' end
        || ' from (select r.id, r.data, r.created_at, r.updated_at, r.updated_by, r.batch_id from ' || v_inner_from
        || ' where ' || v_where
        || format(' order by r.created_at desc, r.id desc limit %s offset %s', v_limit, greatest(coalesce(p_offset, 0), 0))
        || ') i left join import_batches b2 on b2.id = i.batch_id order by i.created_at desc, i.id desc';
    return query execute v_sql;
end;
$fn$;

revoke all on function trieur_data.search_records(uuid, text, jsonb, int, int, timestamptz, uuid, boolean, int) from public;
grant execute on function trieur_data.search_records(uuid, text, jsonb, int, int, timestamptz, uuid, boolean, int) to authenticated;

-- 4) Nombre de lignes d'un environnement (écran "Total", pagination) : même
--    vérification d'appartenance, comptage sans politique par ligne.
create or replace function trieur_data.count_org_records(p_org_id uuid)
returns bigint
language plpgsql
stable
security definer
set search_path = trieur_data, extensions
as $fn$
begin
    if not trieur_data.is_org_member(p_org_id) then
        return 0;
    end if;
    return (select count(*) from trieur_data.records where org_id = p_org_id);
end;
$fn$;

revoke all on function trieur_data.count_org_records(uuid) from public;
grant execute on function trieur_data.count_org_records(uuid) to authenticated;
