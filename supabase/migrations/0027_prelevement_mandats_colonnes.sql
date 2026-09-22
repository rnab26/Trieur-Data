-- =============================================================
-- Nouvelles colonnes du fichier des mandats (Raphaël/père de Raphaël,
-- 2026-09-22, "ordre des colonnes du fichiers de mandats") -- le
-- bouton "Enregistré dans la base de données" stocke les mêmes lignes
-- que l'aperçu de génération (voir save_prelevement_mandats), donc le
-- schéma suit le nouvel ordre/contenu de colonnes ajouté à
-- api/main.py:_mandat_dict. Toutes nullable/en texte comme le reste de
-- la table (dates stockées en "JJ/MM/AAAA", jamais en `date`, même
-- convention que la migration 0023).
-- =============================================================

alter table trieur_data.prelevement_mandats
    add column prenom text,
    add column frequence_mois integer,
    add column jour_prelevement integer,
    add column prochaine_echeance text,
    add column date_fin text,
    add column statut text,
    add column reference_facture text,
    add column libelle text;
