"""Onglet 1 : gestion des colonnes maitres (ajout/suppression/reinitialisation)."""
import traceback

import streamlit as st

from trieur.matching import DEFAULT_MASTER_COLUMNS
from trieur.persistence import save_master_columns


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

    except Exception:
        st.error("\u274c Une erreur est survenue dans cet onglet. Copie-colle le detail ci-dessous pour diagnostic.")
        st.code(traceback.format_exc(), language="text")
