# =============================================================
# Petits helpers d'interface partagés entre plusieurs onglets.
# =============================================================

import streamlit as st


def confirm_delete_button(label: str, key: str) -> bool:
    """Bouton de suppression à deux étapes : le premier clic affiche un
    avertissement et un vrai bouton "Oui, supprimer" ; seul ce second clic
    renvoie True. Un clic isolé (mauvaise visée sur mobile, notamment) ne
    supprime donc jamais rien — règle globale : jamais de suppression sans
    confirmation."""
    pending_key = f"_confirm_pending_{key}"

    if not st.session_state.get(pending_key):
        if st.button(label, key=key):
            st.session_state[pending_key] = True
            st.rerun()
        return False

    st.warning("Suppression définitive, impossible à annuler après coup.")
    col_yes, col_cancel = st.columns(2)
    with col_yes:
        confirmed = st.button("✅ Oui, supprimer", key=f"{key}_yes", type="primary")
    with col_cancel:
        if st.button("Annuler", key=f"{key}_cancel"):
            st.session_state[pending_key] = False
            st.rerun()

    if confirmed:
        st.session_state[pending_key] = False
        return True
    return False
