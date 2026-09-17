# Trieur de Data — frontend React (migration en cours)

Nouvelle interface React, en parallèle de l'app Streamlit existante
(`app.py`), branchée sur la même base Supabase via l'API REST FastAPI
(`api/main.py`). Les deux interfaces peuvent tourner en même temps.

Stack : Vite + React + TypeScript + Tailwind CSS + composants shadcn/ui
(faits main dans `src/components/ui/`, pas encore générés via la CLI
`shadcn`).

## Écran livré

- **Connexion** (`src/screens/LoginScreen.tsx`) : email + mot de passe,
  via Supabase Auth (même schéma que `views/_auth.py`).
- **Base de données** (`src/screens/DatabaseScreen.tsx`) : sélecteur
  d'environnement (organisation), recherche, tableau paginé des clients
  ("Charger plus"), modification d'un client (`RecordEditDialog.tsx`).
  Écran prioritaire de cette itération : fonctionnel, pas encore poli.

## Lancer en local

```bash
cd frontend
npm install
npm run dev
```

Ouvre `http://localhost:5173`.

## Variables d'environnement

Copie `.env.example` en `.env` (jamais commité) et renseigne :

- `VITE_SUPABASE_URL` — URL du projet Supabase (`st.secrets["supabase"]["url"]`
  côté Streamlit).
- `VITE_SUPABASE_ANON_KEY` — clé anonyme Supabase (`st.secrets["supabase"]["anon_key"]`).
- `VITE_API_URL` — URL de l'API FastAPI (`http://localhost:8000` en local ;
  voir `api/main.py` pour la lancer avec `uvicorn api.main:app --reload`).

Aucun secret en dur dans le code : tout passe par `import.meta.env`.

## Build

```bash
npm run build
```

Lance `tsc -b` (vérification TypeScript stricte) puis `vite build`.

## Ce qui n'est pas encore fait

- Pas de dashboard (compteurs, alertes de doublon), pas d'import
  CSV/Excel, pas de filtres par colonne façon Google Sheets, pas de vues
  enregistrées, pas d'édition/suppression en masse, pas d'export — tout
  ça existe côté Streamlit (`views/tab_database.py`) et reste à porter.
- Pas de test end-to-end navigateur (Chromium headless ne valide pas le
  certificat TLS émis par le proxy de cet environnement pour un hôte
  externe — limite de l'environnement, pas du code). Vérifié à la place :
  build Vite + compilation TypeScript strict, les deux au vert.
