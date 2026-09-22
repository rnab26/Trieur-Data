#!/usr/bin/env bash
# Exécute du SQL sur le projet Supabase sans validation manuelle de Raphaël.
#
# Pourquoi ce script existe : l'outil MCP Supabase (execute_sql) impose un pop-up à
# chaque appel, imposé par le serveur MCP et impossible à désactiver -- aucun réglage
# de permissions ne le lève, quel que soit le mode d'accès de la session. Raphaël
# travaille depuis son téléphone et ne veut plus cliquer. Ce script passe par l'API
# HTTPS et la fonction public.exec_sql, donc par Bash : aucune validation.
#
# Ce projet partage le MÊME projet Supabase que Jarvis-assistant
# (bexiyvmdbxcwxasgslxp) -- exec_sql y existe déjà (créée par la migration 0010 de
# Jarvis-assistant), pas besoin d'une nouvelle migration ici. Script identique à
# celui de Jarvis-assistant et melissa-nabet, copié le 22 sept. 2026.
#
# Usage :
#   scripts/sql.sh "select id, nom from clients limit 5;"
#   echo "update clients set statut='actif' where id='...';" | scripts/sql.sh
#   scripts/sql.sh < requete.sql
#
# Prérequis : la variable d'environnement SUPABASE_SERVICE_ROLE_KEY, définie dans
# l'environnement cloud Claude Code. Jamais dans le dépôt.
#
# RAPPEL : cette clé donne un accès total à la base. On demande à Raphaël avant
# tout drop, delete massif ou truncate.

set -euo pipefail

URL="${SUPABASE_URL:-https://bexiyvmdbxcwxasgslxp.supabase.co}"

# Deux façons d'être authentifié, et le script s'accommode des deux :
#
# 1. En-tête posé par le proxy (le bon mode). La clé est enregistrée en « API
#    credential » sur l'environnement cloud, avec l'en-tête `apikey` et un
#    préfixe vide. Le proxy d'Anthropic l'ajoute à la requête APRÈS qu'elle a
#    quitté la machine : la clé n'existe nulle part dans la session, donc aucune
#    session ne peut la lire ni la faire fuiter. Rien à faire ici.
#
# 2. Clé en variable d'environnement (mode historique). On pose les en-têtes
#    nous-mêmes. La clé est alors lisible par toute session de l'environnement.
#
# Supabase exige l'en-tête `apikey`. `Authorization` seul renvoie 401, `apikey`
# seul suffit. D'où le préfixe vide côté proxy.
entetes=(-H "Content-Type: application/json")
if [ -n "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  entetes+=(-H "apikey: $SUPABASE_SERVICE_ROLE_KEY"
            -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY")
fi

# La requête vient du premier argument, sinon de l'entrée standard.
if [ $# -gt 0 ]; then
  requete="$1"
else
  requete="$(cat)"
fi

if [ -z "${requete//[[:space:]]/}" ]; then
  echo "Erreur : aucune requête fournie." >&2
  exit 2
fi

# public.exec_sql (Jarvis-assistant, migration 0010) enveloppe la requête
# dans `select ... from (%s) as t` pour renvoyer les lignes d'un SELECT.
# Un `;` final rend cet enrobage syntaxiquement invalide -- la fonction
# tombe alors dans son repli `EXECUTE` brut, qui exécute bien le SELECT
# mais n'en récupère jamais le résultat (rows toujours null, silencieux,
# sans erreur). Bug réel rencontré en usage (2026-09-22) : un simple
# `select 1;` renvoyait "exécuté sans résultat" au lieu de la ligne.
# Retirer le(s) `;` final(aux) avant l'envoi rend le chemin "lignes
# renvoyées" à nouveau utilisable pour un SELECT unique en fin de requête.
requete="$(printf '%s' "$requete" | sed -E 's/[[:space:];]+$//')"

# jq construit le JSON, pour que guillemets, apostrophes et sauts de ligne de la requête
# soient échappés correctement.
corps="$(jq -n --arg q "$requete" '{query: $q}')"

reponse="$(curl -sS --max-time 60 -X POST "$URL/rest/v1/rpc/exec_sql" \
  "${entetes[@]}" -d "$corps")"

# Réponse inattendue (erreur PostgREST, HTML d'un proxy...) : on la montre telle quelle.
if ! echo "$reponse" | jq -e 'type == "object" and has("ok")' >/dev/null 2>&1; then
  echo "Réponse inattendue de Supabase :" >&2
  echo "$reponse" >&2
  if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
    cat >&2 <<'FIN'

Aucune clé dans l'environnement, et la requête n'a pas abouti : l'« API
credential » de l'environnement cloud n'est probablement pas en place, ou son
en-tête n'est pas nommé « apikey » avec un préfixe vide. À vérifier dans
claude.ai > Code > environnement > API credentials. En attendant, repasser par
l'outil MCP Supabase (avec le pop-up) et le signaler à Raphaël.
FIN
  fi
  exit 1
fi

echo "$reponse" | jq .

# Code de sortie non nul si le SQL a échoué, pour que l'échec ne passe pas inaperçu.
if [ "$(echo "$reponse" | jq -r '.ok')" != "true" ]; then
  exit 1
fi
