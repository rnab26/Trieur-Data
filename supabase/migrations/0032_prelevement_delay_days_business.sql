-- Délai minimum avant le 1er prélèvement : passé de 3 jours calendaires
-- à 4 JOURS OUVRÉS (correction du père de Raphaël, 2026-09-24, sur la
-- règle codée le 2026-09-22 : "décaler au-delà si dans les 4 jours il y
-- a un samedi ou un dimanche" -- voir trieur/prelevement.py:
-- add_business_days). Ne change que la valeur par défaut de la colonne
-- pour un futur environnement Prélèvement créé sans réglage explicite ;
-- la valeur déjà enregistrée pour l'environnement existant a été mise à
-- jour séparément (scripts/sql.sh, même jour).
alter table trieur_data.prelevement_rules
    alter column delay_days set default 4;
