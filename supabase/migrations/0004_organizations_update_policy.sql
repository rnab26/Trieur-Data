-- =============================================================
-- Corrige un trou de sécurité : la table organizations n'avait qu'une
-- policy SELECT, aucune UPDATE. Un utilisateur connecté normal (pas
-- admin) qui essayait d'enregistrer les colonnes maîtres de son
-- organisation depuis l'onglet "Base de données" échouait donc
-- silencieusement côté RLS (seul l'accès admin direct fonctionnait).
--
-- Décision : seuls les super-admins peuvent modifier les réglages d'une
-- organisation (colonnes maîtres, futur créancier SEPA...) -- réglage
-- partagé par tous les membres, pas à modifier par n'importe qui.
-- À revoir si un membre non-admin a un jour besoin de le faire lui-même.
-- =============================================================

create policy organizations_update_admin_only on trieur_data.organizations
    for update using (trieur_data.is_super_admin())
    with check (trieur_data.is_super_admin());
