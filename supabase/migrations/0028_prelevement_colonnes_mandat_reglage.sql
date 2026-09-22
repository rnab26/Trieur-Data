-- =============================================================
-- Ordre/visibilité des colonnes du fichier de mandats, réglable sur le
-- site sans repasser par Claude (demande du père de Raphaël,
-- 2026-09-22, "ORDRE DES COLONNES + MODIFICATIONS" : "que ca reste
-- figé jusqu'au prochaines modification manuelle sur le site
-- directement sans passer par claude"). Une ligne par organisation,
-- même table que les autres réglages Prélèvement.
--
-- Liste ordonnée de {"cle": "<clé du dict _mandat_dict>", "visible":
-- bool} -- NULL/absent = comportement par défaut inchangé (l'ordre
-- fixe codé dans _mandat_dict, toutes les colonnes visibles).
-- =============================================================

alter table trieur_data.prelevement_rules
    add column colonnes_mandat jsonb;
