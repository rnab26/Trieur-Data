#!/bin/bash
# =============================================================
# SessionStart : charge automatiquement les chantiers Cockpit ouverts
# (Trieur de Data) au démarrage d'une session Claude Code sur ce dépôt,
# pour ne jamais avoir à redemander "regarde le Cockpit".
#
# Silencieux (exit 0 sans rien afficher) si les identifiants Supabase ne
# sont pas configurés dans cet environnement -- ne bloque jamais le
# démarrage d'une session sur un dépôt clone ailleurs.
# =============================================================
set -euo pipefail

if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  exit 0
fi

python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

PROJECT_URL = "https://bexiyvmdbxcwxasgslxp.supabase.co"
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

query = (
    "/rest/v1/chantiers"
    "?select=title,status,priority,updated_at,organizations(name)"
    "&status=in.(a_faire,en_cours,attente_retour)"
    "&order=updated_at.desc"
)
req = urllib.request.Request(
    PROJECT_URL + query,
    headers={
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Accept-Profile": "trieur_data",
    },
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        chantiers = json.load(resp)
except (urllib.error.URLError, TimeoutError, ValueError):
    # Pas de reseau / Supabase indisponible : ne bloque jamais le demarrage.
    raise SystemExit(0)

if not chantiers:
    raise SystemExit(0)

print("## Chantiers ouverts dans le Cockpit (Trieur de Data)\n")
print(
    "Repo trieur-data : le Cockpit (table trieur_data.chantiers) contient "
    f"{len(chantiers)} chantier(s) ouvert(s). Lis le fil de discussion complet "
    "(trieur_data.chantier_messages, via le MCP Supabase) avant d'agir sur l'un "
    "d'eux, et mets a jour son statut/un message quand tu avances ou termines.\n"
)
for c in chantiers:
    org = (c.get("organizations") or {}).get("name", "?")
    print(f"- [{org}] **{c['title']}** — statut `{c['status']}`, priorité {c['priority']} (maj {c['updated_at']})")
PY
