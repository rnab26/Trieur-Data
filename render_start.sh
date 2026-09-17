#!/bin/bash
# =============================================================
# Démarrage sur Render : Streamlit lit ses secrets depuis
# .streamlit/secrets.toml, un fichier -- pas des variables
# d'environnement. Ce script génère ce fichier à partir des variables
# d'environnement définies dans Render (SUPABASE_URL, SUPABASE_ANON_KEY)
# au démarrage du conteneur, puis lance l'app normalement. Rien d'autre
# ne change côté application.
# =============================================================
set -euo pipefail

mkdir -p .streamlit
cat > .streamlit/secrets.toml <<EOF
[supabase]
url = "${SUPABASE_URL}"
anon_key = "${SUPABASE_ANON_KEY}"
EOF

exec streamlit run app.py --server.port "${PORT}" --server.address 0.0.0.0 --server.headless true
