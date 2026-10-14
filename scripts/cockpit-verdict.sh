#!/usr/bin/env bash
# Commande du cockpit central (rnab26/Cockpit-General) — installée par brancher.sh.
# Exécute TOUJOURS la dernière version de scripts/verdict.sh (voir cockpit-lanceur.sh).
source "$(dirname "${BASH_SOURCE[0]}")/cockpit-lanceur.sh" || exit 1
cockpit_a_jour || exit 1
exec "$COCKPIT_CACHE/scripts/verdict.sh" "$@"
