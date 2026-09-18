# Trieur de Data — frontend React (migration en cours)

Nouvelle interface React, en parallèle de l'app Streamlit existante
(`app.py`), branchée sur la même base Supabase via l'API REST FastAPI
(`api/main.py`). Les deux interfaces peuvent tourner en même temps.

Stack : Vite + React + TypeScript + Tailwind CSS + composants shadcn/ui
(faits main dans `src/components/ui/`, pas encore générés via la CLI
`shadcn`).

## Écrans livrés

- **Connexion** (`src/screens/LoginScreen.tsx`) : email + mot de passe,
  via Supabase Auth (même schéma que `views/_auth.py`).
- **Base de données** (`src/screens/DatabaseScreen.tsx`) : sélecteur
  d'environnement (organisation), tableau de bord (compteurs, dernier
  import), alertes de doublon, recherche, filtres par colonne façon
  Google Sheets, tableau paginé des clients ("Charger plus"), colonnes
  affichées personnalisables, vues enregistrées, import CSV/Excel,
  colonnes maîtres, modification d'un client (`RecordEditDialog.tsx`),
  modification/suppression en masse (`BulkActions.tsx`), export CSV/Excel.
- **Trieur de Data** (`src/screens/PipelineScreen.tsx`) : import
  CSV/Excel en staging temporaire (24h), suggestion + mapping des
  colonnes vers les colonnes maîtres, puis recherche/filtres/export sur
  les lignes mappées -- mirroir simplifié des onglets 1-4 Streamlit.
  Le dédoublonnage/import définitif (écriture dans la base permanente)
  n'est pas encore porté ici.
- **Cockpit** (`src/screens/CockpitScreen.tsx`, réservé aux
  administrateurs) : suivi des chantiers du logiciel lui-même (créer,
  organiser par section, changer de statut, rechercher/filtrer,
  messages et sous-tâches par chantier).

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

- Trieur de Data (pipeline) : pas de dédoublonnage ni d'écriture finale
  dans la base permanente (`trieur_data.records`) -- reste en staging
  temporaire, jamais confirmé/importé définitivement depuis cet écran.
- Pas de test end-to-end navigateur (Chromium headless ne valide pas le
  certificat TLS émis par le proxy de cet environnement pour un hôte
  externe — limite de l'environnement, pas du code). Vérifié à la place :
  build Vite + compilation TypeScript strict, les deux au vert.
