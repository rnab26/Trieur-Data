-- =============================================================
-- Réglages Prélèvement éditables directement dans l'écran, sans passer
-- par du code (Raphaël, 2026-09-22) : frais de dossier PAR PRODUIT
-- (remplace le seul champ global frais_setup_eur dans l'écran -- gardé
-- en base comme valeur de repli/seed) et libellés de périodicité.
--
-- Ce qui reste volontairement hors de ces réglages (chantier "code",
-- pas "réglage") : la liste des produits eux-mêmes (couplée à la
-- fusion spéciale MYJURIS+IMMO et au nom exact des colonnes de l'export
-- CRM) et les règles de décision (exclusions, FRST/RCUR).
-- =============================================================

alter table trieur_data.prelevement_rules
    add column frais_par_produit jsonb not null default '{}'::jsonb,
    add column periodicites jsonb not null default '{}'::jsonb;
