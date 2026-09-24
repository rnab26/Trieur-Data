-- Résumé en langage simple (pas de jargon informatique) d'une demande de
-- règle Prélèvement, affiché à la place du texte de la demande une fois
-- la règle certifiée (Raphaël, 2026-09-24 : "un résumé simple et clair,
-- facile à comprendre, si on veut comprendre quel est le but de cette
-- règle"). Nullable : rien à migrer de force, une carte certifiée sans
-- résumé retombe sur le titre seul (voir PrelevementRuleRequests.tsx).
alter table trieur_data.prelevement_rule_requests
    add column if not exists resume text;
