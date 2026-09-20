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
- **Trieur de Data** (`src/screens/PipelineScreen.tsx`, 4 onglets dans
  `src/screens/pipeline/`) : mirroir fidèle des 4 onglets Streamlit
  d'origine (`views/tab1_colonnes_maitres.py` à `tab4_export.py`), sur
  le staging temporaire (24h) du pipeline plutôt que sur la base
  permanente :
  - `Tab1ColonnesMaitres.tsx` -- réutilise `MasterColumnsPanel`
    (colonnes maîtres de l'environnement + jeux personnels liés au
    compte, cf `PersonalColumnSets.tsx`) : une seule notion de
    "colonnes maîtres" pour tout le Trieur de Data, jamais une
    deuxième liste.
  - `Tab2ImportMapping.tsx` -- import d'UN fichier Excel/CSV/PDF (pas
    de multi-fichiers ni Google Sheets, limite du contrat API actuel),
    aperçu, auto-assignation + mapping manuel, construction de la
    base, avertissement IBAN (checksum mod 97) après construction.
  - `Tab3FiltrageDedup.tsx` -- filtre multi-critères (groupes OU /
    critères ET, y compris département par code postal), plus
    recherche libre/filtres par colonne (ajout gardé de l'existant),
    analyse des doublons par colonne (revue groupe par groupe avec
    aperçu réel, ou règle globale au-delà de 50 groupes), suppression
    avec confirmation explicite -- **définitive** côté API
    (contrairement à Streamlit, voir docstring
    `api/main.py:apply_pipeline_dedupe`).
  - `Tab4Export.tsx` -- ordre/sélection des colonnes à l'export
    (flèches, pas de glisser-déposer tactile), nom de fichier
    personnalisable, export CSV/Excel (avec le même seuil Excel
    ~1,05M lignes que Streamlit).

  Écarts volontaires documentés en commentaire dans le code : pas de
  filtres/presets d'export *nommés et persistés* côté pipeline (aucun
  endpoint pour ça dans le contrat API actuel, à la différence des
  colonnes maîtres), pas de section "Enregistrer dans la base de
  données" (hors périmètre, écran Base de données exclu de ce
  chantier).
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
