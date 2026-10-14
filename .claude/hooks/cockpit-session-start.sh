#!/usr/bin/env bash
# Hook de démarrage du cockpit central (rnab26/Cockpit-General) — installé par
# brancher.sh. Exécute la dernière version de hooks/session-start.sh. Ne fait
# JAMAIS échouer le démarrage d'une session.
RACINE="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if ! source "$RACINE/scripts/cockpit-lanceur.sh" 2>/dev/null || ! cockpit_a_jour 2>/tmp/cockpit-maj.err; then
  jq -n --arg c "Cockpit non chargé : les scripts du cockpit central sont injoignables ($(tr '\n' ' ' </tmp/cockpit-maj.err 2>/dev/null)). Signale-le à Raphaël, n'invente pas l'état du projet." \
    '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $c}}'
  exit 0
fi
exec bash "$COCKPIT_CACHE/hooks/session-start.sh"
