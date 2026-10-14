#!/usr/bin/env bash
# Rappel à chaque message du cockpit central (rnab26/Cockpit-General) — installé par
# brancher.sh. Exécute la dernière version de hooks/prompt-rappel.sh. Ne fait
# JAMAIS échouer le démarrage d'une session.
RACINE="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if ! source "$RACINE/scripts/cockpit-lanceur.sh" 2>/dev/null || ! cockpit_a_jour 2>/tmp/cockpit-maj.err; then
  jq -n --arg c "Cockpit injoignable : pense quand même à signaler ce travail à Raphaël." \
    '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $c}}'
  exit 0
fi
exec bash "$COCKPIT_CACHE/hooks/prompt-rappel.sh"
