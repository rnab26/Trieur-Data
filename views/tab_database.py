# =============================================================
# Base de données : mémoire persistante du Trieur de Data, par
# organisation (Leads / Prélèvement) -- liste des clients importés
# (avec recherche), import avec vérification de doublon IBAN contre
# tout l'historique en base, file d'alertes à résoudre à la main.
# Les réglages (colonnes maîtres de l'environnement) sont dans un
# tiroir séparé, discret -- ce n'est pas le contenu principal de cet
# onglet.
#
# Accessible à tout membre connecté de l'organisation (pas réservé aux
# administrateurs -- contrairement au Cockpit, qui lui ne concerne que
# le développement du logiciel).
#
# Vue provisoire : le format définitif (colonnes affichées, filtres)
# sera revu une fois un exemple réel (Excel Prélèvement) reçu -- voir
# le chantier Cockpit correspondant.
# =============================================================

import pandas as pd
import streamlit as st

from trieur.db import (
    LIST_PAGE_SIZE,
    add_org_master_columns,
    count_records,
    delete_record,
    delete_saved_view,
    get_org_master_columns,
    get_profiles_map,
    get_record,
    import_dataframe,
    list_all_records,
    list_dedup_alerts,
    list_records,
    list_saved_views,
    resolve_dedup_alert,
    save_org_master_columns,
    save_saved_view,
    update_record,
)
from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
from views._auth import accessible_organizations, require_login
from views._ui import clear_stale_widgets, confirm_delete_button, render_unknown_columns_prompt


def render():
    try:
        configured = "supabase" in st.secrets
    except Exception:
        configured = False

    if not configured:
        st.info(
            "La Base de données n'est pas encore configurée (clés Supabase "
            "manquantes dans les Secrets Streamlit Cloud). Le Trieur de Data "
            "fonctionne normalement en mode local (onglets Import/Filtrage/Export)."
        )
        return

    ctx = require_login()
    client = ctx["client"]
    user = ctx["user"]
    is_admin = ctx["profile"].get("is_super_admin")

    all_orgs = accessible_organizations(ctx)
    if not all_orgs:
        st.info("Aucun espace accessible. Contacte l'administrateur.")
        return

    org_labels = {o["id"]: o["name"] for o in all_orgs}
    org_id = st.selectbox(
        "Environnement",
        options=list(org_labels.keys()),
        format_func=lambda oid: org_labels[oid],
        key="db_org_select",
    )

    _render_alerts(client, org_id, user)
    _render_client_list(client, org_id, org_labels[org_id], user)
    _render_import(client, org_id, user, is_admin)
    _render_settings(client, org_id, is_admin)


def _render_alerts(client, org_id, user):
    alerts = list_dedup_alerts(client, org_id, status="pending")
    if not alerts:
        return

    st.warning(f"⚠️ {len(alerts)} alerte(s) de doublon IBAN en attente")
    for alert in alerts:
        with st.container(border=True):
            st.write("**Nouvelle ligne :**", alert["record"]["data"])
            st.write("**Déjà en base :**", alert["matched"]["data"])
            st.caption(alert.get("note") or "")
            col_dup, col_ok = st.columns(2)
            with col_dup:
                if st.button("C'est un doublon", key=f"dup_{alert['id']}"):
                    resolve_dedup_alert(client, alert["id"], "confirmed_duplicate", user.id)
                    st.rerun()
            with col_ok:
                if st.button("Ce sont 2 personnes différentes", key=f"ok_{alert['id']}"):
                    resolve_dedup_alert(client, alert["id"], "confirmed_different", user.id)
                    st.rerun()
    st.divider()


def _records_cache_key(org_id):
    return f"db_records_cache_{org_id}"


def invalidate_client_list_cache(org_id):
    """A appeler avant tout st.rerun() qui suit une ecriture (import,
    suppression) sur cet environnement -- sinon le lot mis en cache par
    "Charger plus" (voir plus bas) continue d'afficher un etat perime."""
    st.session_state.pop(_records_cache_key(org_id), None)


def _build_rows(records, master_cols):
    """Aplati les lignes brutes Supabase (data jsonb + fichier d'import)
    en dictionnaires plats -- partagé entre l'affichage paginé et l'export
    complet pour ne jamais avoir deux logiques de mise en forme qui
    divergent."""
    rows = []
    for r in records:
        data = r["data"] or {}
        batch = r.get("import_batches") or {}
        # Colonnes de l'organisation d'abord, dans l'ordre defini dans les
        # reglages -- puis toute colonne presente dans la ligne mais pas
        # (encore) declaree, pour ne jamais masquer de donnee.
        row = {"_id": r["id"]}
        for col in master_cols:
            row[col] = data.get(col)
        for key, value in data.items():
            if key not in master_cols:
                row[key] = value
        row["Fichier source"] = batch.get("source_filename")
        row["Importé le"] = batch.get("imported_at")
        # Historique court (migration 0008) : quand/par qui APRES import --
        # volontairement minimal, pas un journal des valeurs changees.
        # "_modifie_par_id" est l'identifiant brut (uuid), resolu en nom
        # d'affichage a part (voir _resolve_modifier_names) : _build_rows
        # reste une fonction pure, sans appel reseau.
        row["Modifié le"] = r.get("updated_at")
        row["_modifie_par_id"] = r.get("updated_by")
        rows.append(row)
    return rows


def _resolve_modifier_names(client, rows):
    """Remplace la cle brute "_modifie_par_id" (uuid, posee par
    _build_rows) par une colonne d'affichage "Modifié par" -- seul
    endroit qui fait l'appel reseau necessaire (_build_rows reste pur).
    Un identifiant non resolvable (RLS -- voir get_profiles_map) devient
    "quelqu'un" plutot qu'une erreur ou un uuid brut a l'ecran."""
    ids = tuple(r.get("_modifie_par_id") for r in rows)
    profiles = get_profiles_map(client, ids)
    for r in rows:
        uid = r.pop("_modifie_par_id", None)
        if not uid:
            r["Modifié par"] = None
        else:
            profile = profiles.get(uid)
            r["Modifié par"] = (profile or {}).get("full_name") or "quelqu'un"
    return rows


def _filter_by_search(rows, search):
    if not search:
        return rows
    needle = search.lower()
    return [
        r for r in rows
        if needle in " ".join(str(v) for k, v in r.items() if k != "_id" and v).lower()
    ]


def _filter_by_columns(rows, col_filters):
    if not col_filters:
        return rows
    return [
        r for r in rows
        if all(col_filters[c] in str(r.get(c) or "").lower() for c in col_filters)
    ]


def _render_export(client, org_id, org_name, total, search, col_filters, all_cols, visible_cols, master_cols):
    with st.expander("💾 Exporter ces résultats"):
        st.caption(
            "Exporte TOUT l'environnement (pas seulement le lot déjà chargé "
            "à l'écran), avec la même recherche et les mêmes filtres par "
            "colonne qu'en ce moment. Une colonne que tu as explicitement "
            "masquée à l'écran reste masquée ; une colonne pas encore vue "
            "à l'écran (hors du lot chargé) est incluse quand même, pour "
            "ne jamais perdre de donnée en silence."
        )
        sig = (org_id, search, tuple(sorted(col_filters.items())), tuple(visible_cols), total)
        file_base = sanitize_filename(org_name, default="export_base")

        def _export_df():
            # Colonnes explicitement masquees par l'utilisateur (presentes
            # dans le lot affiche mais retirees de "Colonnes affichees") --
            # celles-ci restent hors export. Toute AUTRE colonne, meme
            # jamais vue a l'ecran (hors du lot deja charge), est incluse :
            # sinon un fichier plus ancien avec une colonne non encore
            # decouverte perdrait cette donnee en silence a l'export.
            all_records = list_all_records(client, org_id)
            rows = _resolve_modifier_names(client, _build_rows(all_records, master_cols))
            rows = _filter_by_columns(_filter_by_search(rows, search), col_filters)
            full_cols = []
            for row in rows:
                for c in row.keys():
                    if c != "_id" and c not in full_cols:
                        full_cols.append(c)
            explicitly_hidden = set(all_cols) - set(visible_cols)
            export_cols = [c for c in full_cols if c not in explicitly_hidden] or full_cols
            df = pd.DataFrame(rows) if rows else pd.DataFrame()
            for c in export_cols:
                if c not in df.columns:
                    df[c] = None
            return df[export_cols] if export_cols else df

        def _cached_export_df():
            # Un seul fetch complet partage entre CSV et Excel -- sans ce
            # cache, cliquer les deux boutons relancerait deux fois le
            # meme scan paginé de tout l'environnement.
            cache_key = f"_db_export_df_{org_id}"
            cached = st.session_state.get(cache_key)
            if cached and cached[0] == sig:
                return cached[1]
            df = _export_df()
            st.session_state[cache_key] = (sig, df)
            return df

        col_csv, col_xlsx = st.columns(2)
        with col_csv:
            if st.button("⚙️ Préparer le CSV", key=f"db_export_csv_prep_{org_id}"):
                with st.spinner("Récupération de tout l'environnement..."):
                    st.session_state[f"_db_export_csv_{org_id}"] = (sig, export_csv_safe(_cached_export_df()))
            cached = st.session_state.get(f"_db_export_csv_{org_id}")
            if cached and cached[0] == sig and cached[1]:
                st.download_button(
                    "💾 Télécharger CSV", data=cached[1],
                    file_name=f"{file_base}.csv",
                    mime="text/csv", key=f"db_export_csv_dl_{org_id}",
                )
        with col_xlsx:
            if st.button("⚙️ Préparer l'Excel", key=f"db_export_xlsx_prep_{org_id}"):
                with st.spinner("Récupération de tout l'environnement..."):
                    buf = export_excel_safe(_cached_export_df())
                    st.session_state[f"_db_export_xlsx_{org_id}"] = (sig, buf.getvalue() if buf else None)
            cachedx = st.session_state.get(f"_db_export_xlsx_{org_id}")
            if cachedx and cachedx[0] == sig and cachedx[1]:
                st.download_button(
                    "💾 Télécharger Excel", data=cachedx[1],
                    file_name=f"{file_base}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"db_export_xlsx_dl_{org_id}",
                )


def _render_edit_form(client, org_id, record_id, master_cols, user):
    """Modifier un client déjà importé, un seul à la fois (sélection
    multiple = suppression groupée seulement, pas d'édition en masse --
    des valeurs différentes par ligne n'ont pas de "nouvelle valeur"
    commune qui aurait un sens). Limites connues, non traitées :
    - Si le champ IBAN visible est modifié ici, la clé interne "iban" qui
      alimente la détection de doublon (voir trieur/db.py:import_dataframe)
      n'est PAS resynchronisée -- laquelle des colonnes de l'environnement
      est "la" colonne IBAN n'est choisie qu'au moment de l'import, pas
      stockée par la suite. Lié à la règle de doublon configurable par
      activité, déjà en attente de l'Excel de référence (voir
      PROJECT_LOG.md).
    - Dernière écriture gagne : aucune détection si un autre membre a
      modifié ce même client entre l'ouverture du formulaire et
      l'enregistrement (voir trieur/db.py:update_record)."""
    # Valeur fraiche (pas le lot mis en cache de session, potentiellement
    # perime) au moment d'OUVRIR le formulaire -- reduit, sans l'eliminer,
    # le risque d'ecraser une modification faite par quelqu'un d'autre
    # entre-temps.
    raw = get_record(client, record_id)
    if raw is None:
        st.warning("Ce client n'existe plus (supprimé entre-temps).")
        return

    with st.expander("✏️ Modifier cette ligne", expanded=False):
        current_data = dict(raw.get("data") or {})
        field_names = list(master_cols) + [k for k in current_data if k not in master_cols]
        new_values = {}
        for field in field_names:
            # Une valeur "fausse" (0, False) est une vraie valeur, pas une
            # case vide -- `... or ""` l'aurait effacee a l'affichage puis
            # a l'enregistrement (voir revue de code).
            existing = current_data.get(field)
            display_value = "" if existing is None else str(existing)
            new_values[field] = st.text_input(
                field, value=display_value,
                key=f"edit_{org_id}_{record_id}_{field}",
            )
        if st.button("💾 Enregistrer les modifications", key=f"edit_save_{org_id}_{record_id}"):
            cleaned = {k: (v.strip() or None) for k, v in new_values.items()}
            if update_record(client, record_id, cleaned, user.id):
                st.success("Client modifié.")
                invalidate_client_list_cache(org_id)
                clear_stale_widgets(f"edit_{org_id}_{record_id}_")
                st.rerun()
            else:
                st.error("Ce client n'existe plus (supprimé entre-temps) : rien n'a été enregistré.")


def _render_saved_views(client, org_id, user, search, all_cols, visible_cols):
    """Enregistrer/rappeler une combinaison recherche + filtres par
    colonne + colonnes affichées, sous un nom -- même principe que les
    filtres enregistrés du Trieur de Data (onglet Filtrage), liée au
    compte (chaque utilisateur garde ses propres vues)."""
    views = list_saved_views(client, user.id, org_id)

    with st.expander("👁️ Vues enregistrées", expanded=False):
        if views:
            st.markdown("**Vues enregistrées :**")
        for v in views:
            c_name, c_apply, c_del = st.columns([4, 1.3, 1.3])
            with c_name:
                st.write(v["name"])
            with c_apply:
                if st.button("Appliquer", key=f"dbview_apply_{v['id']}", use_container_width=True):
                    st.session_state[f"_apply_db_view_{org_id}"] = {
                        "search": v.get("search") or "",
                        "col_filters": v.get("col_filters") or {},
                        "visible_cols": v.get("visible_cols") or [],
                    }
                    st.rerun()
            with c_del:
                if confirm_delete_button("Supprimer", key=f"dbview_del_{v['id']}"):
                    delete_saved_view(client, v["id"])
                    st.success(f"Vue « {v['name']} » supprimée.")
                    st.rerun()

        st.divider()
        st.caption("Enregistre la recherche, les filtres par colonne et les colonnes affichées actuels.")
        new_name = st.text_input("Nom de la vue", key=f"dbview_new_name_{org_id}")
        if st.button("💾 Enregistrer la vue actuelle", key=f"dbview_save_{org_id}"):
            name = new_name.strip()
            if not name:
                st.error("Donne un nom à cette vue.")
            else:
                # Valeurs brutes des filtres par colonne (pas la version en
                # minuscules utilisee pour filtrer) : sinon la case affiche
                # une version en minuscules apres avoir rappele la vue,
                # meme si le filtre fonctionne toujours (comparaison
                # insensible a la casse cote _filter_by_columns).
                raw_col_filters = {
                    c: st.session_state.get(f"colfilter_{org_id}_{c}", "").strip()
                    for c in all_cols
                    if st.session_state.get(f"colfilter_{org_id}_{c}", "").strip()
                }
                save_saved_view(client, user.id, org_id, name, search, raw_col_filters, list(visible_cols))
                st.success(f"Vue « {name} » enregistrée.")
                st.rerun()


def _render_client_list(client, org_id, org_name, user):
    total = count_records(client, org_id)
    st.markdown(f"##### Clients importés ({total})")

    if total == 0:
        st.caption("Aucun client importé pour l'instant dans cet environnement.")
        st.divider()
        return

    # Lot charge, mis en cache de session pour que "Charger plus" ne
    # retelecharge pas depuis le debut a chaque clic (offset sur le lot
    # deja charge -- voir trieur/db.py:list_records). Invalide par tout
    # import ou toute suppression sur cet environnement.
    cache_key = _records_cache_key(org_id)
    if cache_key not in st.session_state:
        st.session_state[cache_key] = list_records(client, org_id, limit=LIST_PAGE_SIZE)
    records = st.session_state[cache_key]

    # Application d'une vue enregistree : positionner AVANT les widgets
    # (recherche, filtres par colonne, colonnes affichees) concernes --
    # meme logique que le "pending filter"/"pending preset" des onglets
    # Filtrage et Export. Les filtres par colonne visent des cles
    # position-par-NOM (colfilter_{org_id}_{col}) : en poser une pour une
    # colonne qui n'existe plus dans ce lot est sans effet, pas une
    # erreur.
    pending_view = st.session_state.pop(f"_apply_db_view_{org_id}", None)
    if pending_view is not None:
        st.session_state[f"search_{org_id}"] = pending_view.get("search") or ""
        # Vide TOUS les filtres par colonne actuels avant de reposer ceux
        # de la vue -- sinon un filtre tape avant de rappeler une vue qui
        # ne le mentionne pas continue de s'appliquer apres, et le
        # resultat affiche ne correspond plus a ce qui a ete enregistre.
        clear_stale_widgets(f"colfilter_{org_id}_")
        for col, val in (pending_view.get("col_filters") or {}).items():
            st.session_state[f"colfilter_{org_id}_{col}"] = val
        st.session_state[f"db_visible_cols_{org_id}"] = list(pending_view.get("visible_cols") or [])

    search = st.text_input("🔎 Rechercher (nom, IBAN, email...)", key=f"search_{org_id}")
    master_cols = get_org_master_columns(client, org_id)

    all_rows = _resolve_modifier_names(client, _build_rows(records, master_cols))

    # Colonnes connues sur ce lot charge -- calculees AVANT la recherche
    # texte et les filtres, pour que la liste de colonnes (et donc la
    # selection "colonnes affichees") ne varie jamais silencieusement en
    # tapant dans la recherche.
    all_cols = []
    for row in all_rows:
        for c in row.keys():
            if c != "_id" and c not in all_cols:
                all_cols.append(c)

    rows = _filter_by_search(all_rows, search)

    with st.expander("🔎 Filtres par colonne"):
        st.caption("Chaque filtre garde les lignes qui CONTIENNENT le texte tapé (insensible à la casse). Combinés entre eux.")
        col_filters = {}
        filt_cols = st.columns(2)
        for i, col in enumerate(all_cols):
            with filt_cols[i % 2]:
                val = st.text_input(col, key=f"colfilter_{org_id}_{col}", placeholder="contient...")
                if val.strip():
                    col_filters[col] = val.strip().lower()

    rows = _filter_by_columns(rows, col_filters)

    # Colonnes affichees : preference de session par defaut, mais peut
    # etre rappelee/enregistree via une vue nommee (voir
    # _render_saved_views plus bas). Sanitize d'abord une selection
    # perimee (colonne qui n'existe plus dans ce lot) pour ne jamais
    # faire planter le multiselect.
    visible_key = f"db_visible_cols_{org_id}"
    if visible_key in st.session_state:
        st.session_state[visible_key] = [c for c in st.session_state[visible_key] if c in all_cols]
    visible_cols = st.multiselect(
        "Colonnes affichées",
        options=all_cols,
        default=all_cols,
        key=visible_key,
    )
    if not visible_cols:
        st.warning("⚠️ Aucune colonne sélectionnée : toutes affichées par défaut.")
        visible_cols = all_cols

    _render_saved_views(client, org_id, user, search, all_cols, visible_cols)

    if not rows:
        st.caption("Aucun résultat pour cette recherche/ces filtres.")
    else:
        df = pd.DataFrame(rows)
        row_ids = list(df["_id"])
        st.caption(
            f"{len(rows)} résultat(s) affiché(s) sur {len(records)} chargé(s) "
            f"({total} au total dans l'environnement). Clique un en-tête de "
            "colonne pour trier ; coche des lignes pour les supprimer ensemble."
        )
        selection_key = f"db_table_select_{org_id}"
        event = st.dataframe(
            df[visible_cols],
            use_container_width=True,
            height=300,
            hide_index=True,
            key=selection_key,
            on_select="rerun",
            selection_mode="multi-row",
        )
        selected_rows = (getattr(event, "selection", None) or {}).get("rows", [])

        if selected_rows:
            selected_ids = [row_ids[i] for i in selected_rows]
            st.write(f"**{len(selected_ids)} ligne(s) sélectionnée(s).**")
            if confirm_delete_button(f"🗑️ Supprimer la sélection ({len(selected_ids)})", key=f"bulk_delete_{org_id}"):
                for rid in selected_ids:
                    delete_record(client, rid)
                st.success(f"{len(selected_ids)} client(s) supprimé(s).")
                invalidate_client_list_cache(org_id)
                # `selection_key` lui-meme : les positions selectionnees
                # (ex: [7,8,9]) ne correspondent plus a rien apres la
                # suppression -- sans ce nettoyage, IndexError au prochain
                # rendu (row_ids plus court) ou pire, une selection
                # fantome sur d'autres clients (voir clear_stale_widgets).
                clear_stale_widgets(selection_key, f"_confirm_pending_bulk_delete_{org_id}")
                st.rerun()

            if len(selected_ids) == 1:
                _render_edit_form(client, org_id, selected_ids[0], master_cols, user)

    if len(records) < total:
        remaining = total - len(records)
        if st.button(f"⬇️ Charger {min(LIST_PAGE_SIZE, remaining)} client(s) de plus (sur {remaining} restants)", key=f"loadmore_{org_id}"):
            more = list_records(client, org_id, limit=LIST_PAGE_SIZE, offset=len(records))
            st.session_state[cache_key] = records + more
            st.rerun()

    _render_export(client, org_id, org_name, total, search, col_filters, all_cols, visible_cols, master_cols)

    st.divider()


def _render_import(client, org_id, user, is_admin):
    st.markdown("##### Importer un fichier dans la base (avec vérification IBAN)")
    st.caption(
        "Chaque ligne est comparée à TOUT l'historique déjà en base pour cet "
        "environnement (pas juste ce fichier) — un même IBAN déjà vu, même "
        "sous un autre nom, déclenche une alerte au lieu d'être importé en "
        "double silencieusement."
    )

    uploaded = st.file_uploader("Fichier CSV ou Excel", type=["csv", "xlsx"], key=f"upload_{org_id}")
    if uploaded is None:
        return

    try:
        df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
    except Exception as exc:
        st.error(f"Impossible de lire le fichier : {exc}")
        return

    st.dataframe(df.head(10), use_container_width=True)
    iban_col = st.selectbox(
        "Quelle colonne contient l'IBAN ?",
        options=["(aucune)"] + list(df.columns),
        key=f"iban_col_{org_id}",
    )

    cols_to_add = render_unknown_columns_prompt(client, org_id, df.columns, is_admin, key_prefix=f"import_{org_id}")

    if st.button("Vérifier et importer", type="primary", key=f"import_{org_id}"):
        if cols_to_add:
            add_org_master_columns(client, org_id, cols_to_add)
        progress = st.progress(0.0)
        n_imported, n_alerts = import_dataframe(
            client, org_id, uploaded.name, user.id, df,
            iban_col=iban_col if iban_col != "(aucune)" else None,
            on_progress=lambda done, total: progress.progress(done / max(total, 1)),
        )
        st.success(f"{n_imported} lignes importées, {n_alerts} alerte(s) de doublon IBAN créée(s).")
        invalidate_client_list_cache(org_id)
        st.rerun()


def _render_settings(client, org_id, is_admin):
    with st.expander("⚙️ Réglages de l'environnement (colonnes)"):
        cols = list(get_org_master_columns(client, org_id))

        if not is_admin:
            st.caption("Colonnes de cet environnement, modifiables par un administrateur uniquement.")
            for c in cols:
                st.write(f"• {c}")
            return

        st.caption(
            "Crée, renomme, réordonne ou supprime les colonnes de cet "
            "environnement. Les clients déjà importés ne sont pas modifiés — "
            "seuls l'affichage et le prochain import s'adaptent."
        )

        for i, col_name in enumerate(cols):
            c_name, c_up, c_down, c_del = st.columns([6, 1, 1, 1])
            with c_name:
                new_name = st.text_input(
                    "Nom", value=col_name, key=f"colname_{org_id}_{i}", label_visibility="collapsed"
                )
                if new_name.strip() and new_name.strip() != col_name:
                    cols[i] = new_name.strip()
                    save_org_master_columns(client, org_id, cols)
                    st.rerun()
            with c_up:
                if i > 0 and st.button("⬆️", key=f"up_{org_id}_{i}"):
                    cols[i - 1], cols[i] = cols[i], cols[i - 1]
                    save_org_master_columns(client, org_id, cols)
                    clear_stale_widgets(f"colname_{org_id}_")
                    st.rerun()
            with c_down:
                if i < len(cols) - 1 and st.button("⬇️", key=f"down_{org_id}_{i}"):
                    cols[i + 1], cols[i] = cols[i], cols[i + 1]
                    save_org_master_columns(client, org_id, cols)
                    clear_stale_widgets(f"colname_{org_id}_")
                    st.rerun()
            with c_del:
                if st.button("🗑️", key=f"del_{org_id}_{i}"):
                    cols.pop(i)
                    save_org_master_columns(client, org_id, cols)
                    clear_stale_widgets(f"colname_{org_id}_")
                    st.rerun()

        st.divider()
        new_col = st.text_input("Nouvelle colonne", key=f"newcol_{org_id}")
        if st.button("➕ Ajouter une colonne", key=f"addcol_{org_id}"):
            name = new_col.strip()
            if not name:
                st.error("Donne un nom à la nouvelle colonne.")
            elif name in cols:
                st.error("Cette colonne existe déjà.")
            else:
                cols.append(name)
                save_org_master_columns(client, org_id, cols)
                st.rerun()
