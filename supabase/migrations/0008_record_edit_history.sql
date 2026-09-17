-- =============================================================
-- Historique court par ligne (chantier 3/8, voir PROJECT_LOG.md) :
-- permettre de modifier un client déjà importé, et savoir quand/par qui
-- -- volontairement minimal ("courte, pas un journal de bord énorme,
-- mais qu'on ait les informations", demande explicite de l'utilisateur).
-- La date/fichier d'import restent sur import_batches (déjà en place,
-- migration 0001) ; ces deux colonnes couvrent uniquement la MODIFICATION
-- après import, absente jusqu'ici (aucune fonctionnalité d'édition).
-- =============================================================

alter table trieur_data.records
    add column updated_at timestamptz,
    add column updated_by uuid references auth.users (id);

comment on column trieur_data.records.updated_at is
    'Dernière modification APRÈS import (null si jamais modifié depuis son import).';
comment on column trieur_data.records.updated_by is
    'Qui a fait la dernière modification -- null si jamais modifié.';
