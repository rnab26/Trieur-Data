#!/usr/bin/env bash
# Mode autonome du cockpit central (rnab26/Cockpit-General) — installé par
# brancher.sh. Exécute la dernière version de hooks/autonome.sh (hook Stop). Au
# moindre souci il se tait : la session s'arrête normalement.
RACINE="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
source "$RACINE/scripts/cockpit-lanceur.sh" 2>/dev/null || exit 0
cockpit_a_jour 2>/dev/null || exit 0
[ -f "$COCKPIT_CACHE/hooks/autonome.sh" ] || exit 0
exec bash "$COCKPIT_CACHE/hooks/autonome.sh"
