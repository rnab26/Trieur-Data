-- =============================================================
-- Accès en lecture seule par environnement (chantier Cockpit "Ajouter
-- un accès en lecture seule", reprise de PROJECT_LOG.md point 12 / n5).
--
-- Demande de l'utilisateur : donner à des partenaires externes un accès
-- de consultation seule sur un environnement, sans qu'ils puissent
-- importer/modifier/supprimer des clients ni résoudre les alertes de
-- doublon. Formulation volontairement ouverte au départ ("encore plus
-- de restrictions possibles si nécessaire") -- ceci est le premier
-- palier (lecture/écriture par ENVIRONNEMENT), pas une restriction fine
-- par colonne : rien n'empêche d'affiner plus tard si besoin.
--
-- `memberships.role` acceptait déjà 'member'/'org_admin' (migration
-- 0001) mais aucune policy ni code ne distinguait lecture et écriture --
-- tout membre pouvait tout faire sur son organisation. Ajoute une
-- troisième valeur 'lecture_seule' et une fonction `can_write()` que les
-- policies RLS des tables de données clients utilisent pour bloquer les
-- écritures (insert/update/delete) de ce rôle, tout en gardant la
-- lecture inchangée (is_org_member reste utilisé tel quel côté select).
--
-- `org_admin` reste un rôle inerte (aucune permission propre) comme
-- avant cette migration -- pas dans le périmètre de ce chantier (voir
-- PROJECT_LOG.md point 12, encore ouvert pour la suite).
-- =============================================================

alter table trieur_data.memberships
    drop constraint memberships_role_check,
    add constraint memberships_role_check
        check (role in ('member', 'org_admin', 'lecture_seule'));

create or replace function trieur_data.can_write(target_org_id uuid)
returns boolean
language sql
security definer
stable
set search_path = trieur_data
as $$
    select trieur_data.is_super_admin() or exists (
        select 1 from trieur_data.memberships
        where user_id = auth.uid()
          and org_id = target_org_id
          and role in ('member', 'org_admin')
    );
$$;

comment on function trieur_data.can_write(uuid) is
    'Membre avec droit d''écriture sur cet environnement (tout rôle sauf lecture_seule), ou super-admin.';

-- ---------------------------------------------------------------
-- import_batches, records, dedup_alerts : remplace la policy unique
-- "for all" (is_org_member) par une lecture inchangée pour tout membre
-- + une écriture réservée à can_write(). Un membre 'lecture_seule' garde
-- donc EXACTEMENT le même accès en lecture qu'avant cette migration.
-- ---------------------------------------------------------------
drop policy import_batches_rw on trieur_data.import_batches;
create policy import_batches_select on trieur_data.import_batches
    for select using (trieur_data.is_org_member(org_id));
create policy import_batches_insert on trieur_data.import_batches
    for insert with check (trieur_data.can_write(org_id));
create policy import_batches_update on trieur_data.import_batches
    for update using (trieur_data.can_write(org_id)) with check (trieur_data.can_write(org_id));
create policy import_batches_delete on trieur_data.import_batches
    for delete using (trieur_data.can_write(org_id));

drop policy records_rw on trieur_data.records;
create policy records_select on trieur_data.records
    for select using (trieur_data.is_org_member(org_id));
create policy records_insert on trieur_data.records
    for insert with check (trieur_data.can_write(org_id));
create policy records_update on trieur_data.records
    for update using (trieur_data.can_write(org_id)) with check (trieur_data.can_write(org_id));
create policy records_delete on trieur_data.records
    for delete using (trieur_data.can_write(org_id));

drop policy dedup_alerts_rw on trieur_data.dedup_alerts;
create policy dedup_alerts_select on trieur_data.dedup_alerts
    for select using (trieur_data.is_org_member(org_id));
create policy dedup_alerts_insert on trieur_data.dedup_alerts
    for insert with check (trieur_data.can_write(org_id));
create policy dedup_alerts_update on trieur_data.dedup_alerts
    for update using (trieur_data.can_write(org_id)) with check (trieur_data.can_write(org_id));
create policy dedup_alerts_delete on trieur_data.dedup_alerts
    for delete using (trieur_data.can_write(org_id));

-- ---------------------------------------------------------------
-- Gestion des rôles par un administrateur (Réglages de l'environnement,
-- même gate que les colonnes maîtres -- is_super_admin uniquement,
-- comme partout ailleurs dans l'app). Seuls update/delete sont ouverts :
-- créer une toute première appartenance pour un nouveau compte reste un
-- geste manuel hors app (aucun flux d'invitation n'existe pour PERSONNE
-- aujourd'hui, pas seulement pour ce rôle -- hors périmètre de ce
-- chantier). `memberships_select` (migration 0001) couvre déjà la
-- lecture : un super-admin y voit toutes les lignes sans changement.
-- ---------------------------------------------------------------
create policy memberships_update_admin on trieur_data.memberships
    for update using (trieur_data.is_super_admin()) with check (trieur_data.is_super_admin());
create policy memberships_delete_admin on trieur_data.memberships
    for delete using (trieur_data.is_super_admin());
