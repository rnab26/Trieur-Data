# API REST (`api/`)

API FastAPI qui expose la logique métier déjà écrite dans `trieur/db.py`
(rien n'est dupliqué : chaque endpoint appelle les mêmes fonctions que
l'app Streamlit). Objectif : permettre une migration progressive de
l'interface vers React sans toucher aux vues Streamlit existantes
(`views/`), qui continuent de tourner en parallèle.

## Lancer en local

```bash
pip install -r requirements.txt   # fastapi, uvicorn, python-multipart y sont
uvicorn api.main:app --reload
```

L'API démarre sur `http://localhost:8000` (doc interactive sur
`/docs`).

## Variables d'environnement / secrets

Même source que l'app Streamlit : un fichier `.streamlit/secrets.toml`
à la racine du dépôt, avec :

```toml
[supabase]
url = "https://xxxx.supabase.co"
anon_key = "eyJ..."
```

Aucun secret n'est codé en dur dans `api/`. En production (Render...),
ce fichier est fourni par le même mécanisme que pour le service
Streamlit -- pas de nouvelle variable à ajouter.

## Authentification

Chaque requête porte le jeton Supabase de l'utilisateur connecté :

```
Authorization: Bearer <access_token>
```

Le jeton est vérifié via `client.auth.get_user(token)` (appel réel à
Supabase Auth, mêmes règles que le formulaire de connexion Streamlit --
voir `views/_auth.py`). Un jeton absent, mal formé ou invalide renvoie
`401`. Un compte connecté mais sans profil Trieur de Data (table
`profiles`) renvoie aussi `401`. Un accès à un environnement (`org_id`)
dont l'utilisateur n'est pas membre (et n'est pas super-admin) renvoie
`403`.

Point d'implémentation important : contrairement à l'app Streamlit
(qui réutilise un seul client Supabase mis en cache par session), l'API
crée un **client Supabase neuf à chaque requête** (voir
`get_supabase_client()` dans `api/main.py`). Réutiliser le singleton
`trieur.db.get_client()` ici aurait fait courir le jeton d'un
utilisateur sur la requête concurrente d'un autre, puisqu'une API
traite plusieurs requêtes en parallèle (contrairement à un rerun
Streamlit, séquentiel). Toute la logique métier (lecture/écriture en
base) continue de passer par `trieur/db.py`, seule la construction du
client change.

## Endpoints

Tous scoppés à `org_id` (sauf `/orgs`) et protégés par le jeton
ci-dessus :

- `GET /orgs` -- environnements accessibles au compte connecté.
- `GET /orgs/{org_id}/dashboard` -- total clients, alertes de doublon
  en attente, dernier import (fichier + date).
- `GET /orgs/{org_id}/records` -- liste paginée (`page`, `page_size`,
  `search`, `col_filters` en JSON). **Limite connue** (déjà présente
  côté Streamlit, pas une régression introduite ici) : `search` et
  `col_filters` filtrent uniquement le lot chargé pour la page
  demandée, pas tout l'historique de l'environnement.
- `GET /orgs/{org_id}/records/{record_id}` -- un client.
- `PATCH /orgs/{org_id}/records/{record_id}` -- remplace entièrement
  le champ `data` du client (`{"data": {...}}`), même règle que
  `trieur.db.update_record` (pas de fusion partielle).
- `POST /orgs/{org_id}/import` -- upload CSV/Excel (`multipart/form-data`,
  champs `file`, `iban_col` optionnel, `add_unknown_columns` optionnel).
- `GET`/`POST /orgs/{org_id}/master-columns` -- colonnes maîtres de
  l'environnement (écriture réservée aux super-admins, comme dans
  Streamlit).
- `GET`/`POST /orgs/{org_id}/saved-views`, `DELETE
  /orgs/{org_id}/saved-views/{view_id}` -- vues enregistrées, liées au
  compte connecté (la suppression vérifie que la vue lui appartient
  avant d'agir).

## Tests

```bash
pytest tests/test_api.py
```

Aucun appel réseau réel : un faux client Supabase (même style que les
autres tests du dépôt, ex. `tests/test_db_saved_views.py`) est injecté
via `app.dependency_overrides`.
