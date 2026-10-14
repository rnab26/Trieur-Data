#!/usr/bin/env bash
# Lanceur du cockpit central — installé par brancher.sh de rnab26/Cockpit-General.
# NE PAS MODIFIER ICI : toute évolution se fait dans Cockpit-General.
#
# Pourquoi (Raphaël, 29 sept. 2026) : « améliorer constamment le cockpit, et que
# les autres cockpits récupèrent ces évolutions en simultané ». Les scripts des
# sessions ne sont donc plus copiés dans le projet : chaque commande
# scripts/cockpit-*.sh et le hook de démarrage prennent la DERNIÈRE version sur
# Cockpit-General (branche main), gardée en cache hors du dépôt (10 min par
# défaut), et retombent sur le dernier cache si GitHub ne répond pas.
#
# Réglages (variables d'environnement, facultatives) : COCKPIT_SOURCE (URL
# brute du dépôt), COCKPIT_CACHE (dossier), COCKPIT_TTL (secondes).
COCKPIT_SOURCE="${COCKPIT_SOURCE:-https://raw.githubusercontent.com/rnab26/Cockpit-General/main}"
COCKPIT_CACHE="${COCKPIT_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/cockpit-general}"
COCKPIT_FICHIERS=(scripts/sql.sh scripts/demander.sh scripts/marche.py scripts/progression.sh scripts/progression_tableau.py scripts/chantier.sh hooks/session-start.sh hooks/prompt-rappel.sh hooks/suivi.sh hooks/autonome.sh scripts/passe.sh scripts/media.sh scripts/chef.sh scripts/verdict.sh scripts/revue-a-toi.sh scripts/renfort.sh scripts/reproduction.sh scripts/greffe.sh modeles/cockpit-pre-push.sh scripts/emplacement.sh scripts/analyser-depot.py scripts/apercu-emplacement.mjs)

# Noms des commandes tels qu'on les tape DANS le projet (affichés par le hook).
export COCKPIT_SQL_CMD="scripts/cockpit-sql.sh" COCKPIT_PROG_CMD="scripts/cockpit-progression.sh" COCKPIT_DEM_CMD="scripts/cockpit-demander.sh" COCKPIT_CHANTIER_CMD="scripts/cockpit-chantier.sh" COCKPIT_MEDIA_CMD="scripts/cockpit-media.sh" COCKPIT_CHEF_CMD="scripts/cockpit-chef.sh" COCKPIT_VERDICT_CMD="scripts/cockpit-verdict.sh" COCKPIT_RENFORT_CMD="scripts/cockpit-renfort.sh" COCKPIT_REPRO_CMD="scripts/cockpit-reproduction.sh" COCKPIT_PRFUS_CMD="scripts/cockpit-pr-a-fusionner.sh" COCKPIT_EMPL_CMD="scripts/cockpit-emplacement.sh"
export COCKPIT_SQL="$COCKPIT_CACHE/scripts/sql.sh"
export COCKPIT_GREFFE_CMD="scripts/cockpit-greffe.sh"

# VOIE 1 — greffe invisible (30 sept. 2026, chantier f31ae3ec) : un dépôt qui
# n'est pas à Raphaël ne reçoit AUCUN fichier du cockpit. Les commandes vivent
# dans $COCKPIT_HOME/bin (posées par brancher.sh --voie invisible, relancé par
# le script d'installation de SON environnement cloud) et le projet se
# reconnaît à son dépôt git : une ligne « owner/repo slug » dans
# $COCKPIT_HOME/greffes. Un projet branché normalement (COCKPIT_PROJET posé par
# son .claude/settings.json) n'est jamais concerné.
COCKPIT_HOME="${COCKPIT_HOME:-$HOME/.cockpit}"
cockpit_depot_de() { # dossier → owner/repo (minuscules), d'après l'adresse de origin
  local url; url=$(git -C "$1" remote get-url origin 2>/dev/null) || return 1
  url="${url%/}"; url="${url%.git}"
  printf '%s\n' "$url" | awk -F'[/:]' 'NF >= 2 { print tolower($(NF-1) "/" $NF) }'
}
cockpit_greffe_slug() { # dossier → slug du projet greffé, ou rien
  local f="$COCKPIT_HOME/greffes" d; [ -f "$f" ] || return 1
  d=$(cockpit_depot_de "$1") && [ -n "$d" ] || return 1
  awk -v d="$d" '$1 == d { print $2; exit }' "$f" | grep .
}
if [ -z "${COCKPIT_PROJET:-}" ] && _cockpit_s=$(cockpit_greffe_slug "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null); then
  export COCKPIT_PROJET="$_cockpit_s" COCKPIT_SANS_TRACE=1
fi
if [ "${COCKPIT_SANS_TRACE:-}" = 1 ]; then
  # Les commandes montrées aux sessions : hors du dépôt, chemin complet.
  for _cockpit_v in COCKPIT_SQL_CMD COCKPIT_PROG_CMD COCKPIT_DEM_CMD COCKPIT_CHANTIER_CMD COCKPIT_MEDIA_CMD COCKPIT_CHEF_CMD COCKPIT_VERDICT_CMD COCKPIT_RENFORT_CMD COCKPIT_REPRO_CMD COCKPIT_PRFUS_CMD COCKPIT_EMPL_CMD COCKPIT_GREFFE_CMD; do
    export "$_cockpit_v=$COCKPIT_HOME/bin/${!_cockpit_v#scripts/}"
  done
fi

cockpit_a_jour() {
  local repere="$COCKPIT_CACHE/.maj" age
  if [ -f "$repere" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$repere" 2>/dev/null || echo 0) ))
    [ "$age" -lt "${COCKPIT_TTL:-600}" ] && return 0
  fi
  local tmp f; tmp=$(mktemp -d)
  # La liste des fichiers vient du cockpit lui-même (modeles/fichiers.txt) :
  # un fichier ajouté au cockpit arrive partout sans retoucher ce lanceur.
  # La liste écrite ci-dessus ne sert que si elle est injoignable.
  local liste=("${COCKPIT_FICHIERS[@]}")
  if curl -fsS --max-time 8 "$COCKPIT_SOURCE/modeles/fichiers.txt" -o "$tmp/.liste" 2>/dev/null && [ -s "$tmp/.liste" ]; then
    mapfile -t liste < <(grep -E '^[a-zA-Z0-9_./-]+$' "$tmp/.liste")
  fi
  for f in "${liste[@]}"; do
    mkdir -p "$tmp/$(dirname "$f")"
    if ! curl -fsS --max-time 8 "$COCKPIT_SOURCE/$f" -o "$tmp/$f"; then
      rm -rf "$tmp"
      if [ -x "$COCKPIT_CACHE/scripts/sql.sh" ]; then
        echo "(cockpit : Cockpit-General injoignable, dernière version en cache utilisée)" >&2; return 0
      fi
      echo "Cockpit : impossible de récupérer $f depuis $COCKPIT_SOURCE, et aucune version en cache." >&2; return 1
    fi
  done
  rm -f "$tmp/.liste"
  chmod +x "$tmp"/scripts/*.sh "$tmp"/hooks/*.sh "$tmp"/modeles/*.sh 2>/dev/null
  # Remplacement d'un bloc : jamais un mélange d'ancienne et de nouvelle version.
  mkdir -p "$COCKPIT_CACHE"; cp -r "$tmp"/. "$COCKPIT_CACHE"/; touch "$repere"; rm -rf "$tmp"
}
