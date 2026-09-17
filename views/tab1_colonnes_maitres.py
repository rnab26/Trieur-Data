"""Onglet 1 : gestion des colonnes maitres (ajout/suppression/reinitialisation)."""
import traceback

import streamlit as st

from trieur.matching import DEFAULT_MASTER_COLUMNS
from trieur.persistence import save_master_columns
from views._ui import confirm_delete_button


def _render_account_memory():
    """Section ADDITIVE, visible seulement si deja connecte (aucun login
    force ici -- l'onglet reste 100% utilisable sans compte, inchange).
    Permet de retrouver un jeu de colonnes maitres nomme, lie au compte,
    quel que soit l'environnement -- distinct des colonnes par
    organisation (onglet Base de donnees)."""
    if "auth_session" not in st.session_state:
        return

    try:
        configured = "supabase" in st.secrets
    except Exception:
        configured = False
    if not configured:
        return

    from trieur.db import (
        get_client,
        get_my_profile,
        list_user_column_sets,
        save_user_column_set,
        delete_user_column_set,
        set_active_column_set,
    )

    client = get_client()
    session = st.session_state["auth_session"]
    client.auth.set_session(session.access_token, session.refresh_token)
    user = session.user
    profile = get_my_profile(client, user.id)
    if not profile:
        return

    # Applique UNE FOIS par session le dernier jeu actif enregistre sur le
    # compte, exactement comme le secours localStorage (app.py) le fait deja
    # pour le cas "fichier serveur reinitialise" -- meme principe, source en plus.
    if not st.session_state.get("_user_cols_autoloaded") and profile.get("active_master_column_set_id"):
        active_id = profile["active_master_column_set_id"]
        matches = [s for s in list_user_column_sets(client, user.id) if s["id"] == active_id]
        st.session_state["_user_cols_autoloaded"] = True
        if matches and matches[0]["columns"]:
            st.session_state.master_columns = matches[0]["columns"]
            st.session_state["master_cols_input"] = "\n".join(matches[0]["columns"])
            save_master_columns(matches[0]["columns"])
            st.rerun()

    with st.expander(f"🔗 Mémoire liée à ton compte ({user.email})"):
        sets = list_user_column_sets(client, user.id)

        if sets:
            labels = {s["id"]: s["name"] for s in sets}
            chosen_id = st.selectbox(
                "Jeux de colonnes enregistrés",
                options=list(labels.keys()),
                format_func=lambda sid: labels[sid],
                key="user_col_set_select",
            )
            col_apply, col_delete = st.columns([1, 1])
            with col_apply:
                if st.button("✅ Appliquer ce jeu", key="apply_user_col_set"):
                    chosen = next(s for s in sets if s["id"] == chosen_id)
                    st.session_state.master_columns = chosen["columns"]
                    st.session_state["master_cols_input"] = "\n".join(chosen["columns"])
                    save_master_columns(chosen["columns"])
                    set_active_column_set(client, user.id, chosen_id)
                    st.success(f"Jeu « {chosen['name']} » appliqué et retenu pour ta prochaine connexion.")
                    st.rerun()
            with col_delete:
                if confirm_delete_button("🗑️ Supprimer ce jeu", key="delete_user_col_set"):
                    delete_user_column_set(client, chosen_id)
                    st.success("Jeu de colonnes supprimé.")
                    st.rerun()
        else:
            st.caption("Aucun jeu de colonnes enregistré sur ton compte pour l'instant.")

        new_name = st.text_input("Nom du nouveau jeu", key="new_user_col_set_name")
        if st.button("💾 Enregistrer les colonnes actuelles sous ce nom", key="save_user_col_set"):
            current_cols = [c for c in st.session_state.master_columns if c]
            if not new_name.strip():
                st.error("Donne un nom à ce jeu de colonnes.")
            elif not current_cols:
                st.error("Aucune colonne à enregistrer.")
            else:
                saved = save_user_column_set(client, user.id, new_name.strip(), current_cols)
                set_active_column_set(client, user.id, saved["id"])
                st.success(f"Jeu « {new_name.strip()} » enregistré sur ton compte.")
                st.rerun()


def render():
    try:
        st.subheader("Gerer vos colonnes maitres")
        st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne. "
                 "La liste est **conservee** apres rechargement de la page.")
        cols_text = st.text_area(
            "Colonnes maitres",
            value="\n".join(st.session_state.master_columns),
            height=250,
            key="master_cols_input"
        )

        col_save, col_reset = st.columns([1, 1])
        with col_save:
            if st.button("💾 Enregistrer la liste des colonnes maitres", type="primary"):
                new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
                # dedoublonnage en gardant l'ordre
                seen = set()
                deduped = []
                for c in new_list:
                    key = c.lower()
                    if key not in seen:
                        seen.add(key)
                        deduped.append(c)
                if deduped:
                    st.session_state.master_columns = deduped
                    ok = save_master_columns(deduped)
                    if ok:
                        st.success(f"{len(deduped)} colonnes maitres enregistrees et conservees.")
                    else:
                        st.warning(f"{len(deduped)} colonnes prises en compte pour la session "
                                   "(sauvegarde disque indisponible sur cet hebergement).")
                else:
                    st.error("❌ Veuillez entrer au moins une colonne maître.")

        with col_reset:
            if st.button("↩️ Reinitialiser (liste par defaut)"):
                st.session_state.master_columns = DEFAULT_MASTER_COLUMNS.copy()
                save_master_columns(DEFAULT_MASTER_COLUMNS.copy())
                st.success("Liste reinitialisee aux colonnes par defaut.")
                st.rerun()

        st.caption("ℹ️ Astuce : les colonnes **TELEPHONE MOBILE** et **TELEPHONE FIXE** "
                   "sont detectees automatiquement d'apres le contenu (prefixes 06/07 = mobile, "
                   "01-05/08/09 = fixe), meme si l'en-tete est absente ou trompeuse.")

        _render_account_memory()

    except Exception:
        st.error("\u274c Une erreur est survenue dans cet onglet. Copie-colle le detail ci-dessous pour diagnostic.")
        st.code(traceback.format_exc(), language="text")
