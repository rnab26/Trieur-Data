-- =============================================================
-- Frais de dossier par produit (Raphaël, 2026-09-21) : trouvé en
-- croisant le fichier CRM de référence avec le vrai fichier de remise
-- bancaire du Drive -- 20€ facturés UNE FOIS PAR PRODUIT actif au 1er
-- prélèvement (jamais un montant client indivis). Réglable ici pour ne
-- jamais coder cette valeur en dur.
-- =============================================================

alter table trieur_data.prelevement_rules
    add column frais_setup_eur numeric not null default 20.0 check (frais_setup_eur >= 0);
