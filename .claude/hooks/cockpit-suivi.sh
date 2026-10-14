#!/usr/bin/env bash
# Suivi des sessions et de leurs tâches en arrière-plan (agents, commandes) par
# le cockpit central (rnab26/Cockpit-General) — installé par brancher.sh.
# Exécute la dernière version de hooks/suivi.sh. Ne fait JAMAIS échouer ni
# ralentir la session : au moindre souci, il se tait.
RACINE="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
source "$RACINE/scripts/cockpit-lanceur.sh" 2>/dev/null || exit 0
cockpit_a_jour 2>/dev/null || exit 0
[ -f "$COCKPIT_CACHE/hooks/suivi.sh" ] || exit 0
exec bash "$COCKPIT_CACHE/hooks/suivi.sh"
