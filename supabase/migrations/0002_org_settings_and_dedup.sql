-- =============================================================
-- Environnements personnalisés : colonnes maîtres propres à chaque
-- organisation (au lieu du fichier JSON global partagé par tout le
-- monde) + fonction de vérification de doublon IBAN contre TOUT
-- l'historique en base (pas juste le fichier du jour).
-- =============================================================

alter table trieur_data.organizations
    add column if not exists master_columns jsonb not null default '[]'::jsonb;

update trieur_data.organizations
set master_columns = '["NOM", "PRENOM", "IBAN", "EMAIL", "TELEPHONE", "ADRESSE", "CP", "VILLE", "Source Data"]'::jsonb
where slug = 'prelevement' and master_columns = '[]'::jsonb;

update trieur_data.organizations
set master_columns = '["NOM", "PRENOM", "GENRE/CIVILITE", "VILLE", "CP", "ADRESSE", "TELEPHONE MOBILE", "TELEPHONE FIXE", "EMAIL", "DATE DE NAISSANCE", "Source Data"]'::jsonb
where slug = 'leads' and master_columns = '[]'::jsonb;

-- ---------------------------------------------------------------
-- Vérifie un IBAN contre l'historique complet de l'organisation et
-- retourne les correspondances existantes (jamais de suppression --
-- juste l'information pour décider). Utilisée à l'import ET
-- consultable à la demande.
-- ---------------------------------------------------------------
create or replace function trieur_data.find_iban_matches(p_org_id uuid, p_iban text)
returns table (record_id uuid, batch_id uuid, source_filename text, imported_at timestamptz, data jsonb)
language sql
security invoker
stable
set search_path = trieur_data
as $$
    select r.id, r.batch_id, b.source_filename, b.imported_at, r.data
    from trieur_data.records r
    join trieur_data.import_batches b on b.id = r.batch_id
    where r.org_id = p_org_id
      and r.iban_normalized = upper(regexp_replace(p_iban, '\s', '', 'g'))
    order by b.imported_at;
$$;

grant execute on function trieur_data.find_iban_matches(uuid, text) to authenticated;
