-- =============================================================
-- Nouveau statut "a_verifier" sur les demandes de règles (Raphaël,
-- 2026-09-22) : jusqu'ici une session Claude Code passait directement
-- une demande codée à "valide", sans jamais que Raphaël/son père ne
-- confirment que la règle fonctionne réellement une fois en
-- production. Résultat signalé : quand une règle codée ne correspond
-- pas à ce qui était attendu, une NOUVELLE demande était recréée
-- (doublon) plutôt que de corriger la même demande.
--
-- Nouveau cycle : en_attente -> en_cours -> a_verifier (codé et
-- déployé, en attente de la validation fonctionnelle de l'admin) ->
-- valide (confirmé par un humain) OU retour à en_cours (bouton
-- "à corriger", même demande, jamais une nouvelle ligne).
-- =============================================================

alter table trieur_data.prelevement_rule_requests
    drop constraint prelevement_rule_requests_statut_check;

alter table trieur_data.prelevement_rule_requests
    add constraint prelevement_rule_requests_statut_check
    check (statut in ('en_attente', 'en_cours', 'a_verifier', 'valide'));
