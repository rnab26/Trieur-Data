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


def unknown_columns(columns, master_cols) -> list:
    """Colonnes d'un fichier à importer qui n'existent pas encore dans
    les colonnes maîtres de l'environnement -- comparaison insensible à
    la casse (même convention que le dédoublonnage des colonnes maîtres,
    voir views/tab1_colonnes_maitres.py), ordre préservé, jamais de
    doublon dans le résultat. Sert à demander explicitement (plutôt que
    deviner) si ces colonnes doivent être ajoutées à l'environnement, au
    lieu de s'afficher "en plus" sans que personne ait choisi."""
    known_lower = {c.lower() for c in master_cols}
    seen_lower = set()
    result = []
    for c in columns:
        cl = c.lower()
        if cl not in known_lower and cl not in seen_lower:
            seen_lower.add(cl)
            result.append(c)
    return result


def render_unknown_columns_prompt(client, org_id, df_columns, is_admin, key_prefix) -> list:
    """Avant un import, signale les colonnes du fichier que l'environnement
    ne connaît pas encore et propose de les ajouter -- au lieu de les
    laisser s'afficher "en plus" sans que personne ait choisi. Partagé
    entre l'upload direct (Base de données) et le bouton "Enregistrer
    dans la base de données" (Export), pour ne jamais avoir deux
    comportements différents selon le chemin d'import. Réservé aux
    administrateurs (même règle que les réglages de colonnes) : un
    membre simple voit juste un message informatif, l'import continue
    normalement -- aucune donnée n'est jamais perdue, seule
    l'"officialisation" de la colonne dans les réglages est bloquée.
    Renvoie la liste des colonnes que l'appelant doit ajouter (via
    trieur/db.py:add_org_master_columns) avant l'import, vide si rien à
    faire."""
    from trieur.db import get_org_master_columns

    master_cols = get_org_master_columns(client, org_id)
    unknown = unknown_columns(df_columns, master_cols)
    if not unknown:
        return []

    if not is_admin:
        st.info(
            "ℹ️ Ce fichier contient des colonnes non déclarées dans cet "
            "environnement, importées quand même (juste pas encore "
            "officialisées) : " + ", ".join(unknown) + ". Un administrateur "
            "peut les ajouter dans les réglages de l'environnement."
        )
        return []

    st.info(f"ℹ️ Ce fichier a {len(unknown)} colonne(s) que cet environnement ne connaît pas encore.")
    # La cle du widget depend du CONTENU du lot de colonnes inconnues, pas
    # seulement de key_prefix : sinon, une fois qu'un premier lot a ete vu
    # pour cette cle, Streamlit reutilise la selection persistee en
    # session_state pour un lot DIFFERENT (fichier suivant, colonnes
    # differentes) et n'applique plus jamais `default=unknown` -- meme
    # bug de fond que les widgets indexes par position (clear_stale_widgets
    # ci-dessous), ici indexe par contenu plutot que par position.
    widget_key = f"{key_prefix}_add_cols"
    sig_key = f"{widget_key}_sig"
    current_sig = tuple(sorted(unknown))
    if st.session_state.get(sig_key) != current_sig:
        st.session_state.pop(widget_key, None)
        st.session_state[sig_key] = current_sig
    return st.multiselect(
        "Les ajouter aux colonnes de l'environnement ? (sinon elles sont "
        "importées quand même, juste pas déclarées dans les réglages)",
        options=unknown,
        default=unknown,
        key=widget_key,
    )


def clear_stale_widgets(*prefixes: str) -> None:
    """À appeler après toute mutation d'une liste dont les widgets sont
    indexés par POSITION (renommer, réordonner, supprimer un élément) :
    purge les clés `st.session_state` qui commencent par un de ces
    préfixes. Sans ça, l'élément qui glisse à un indice hérite du widget
    (texte tapé, confirmation de suppression en attente...) laissé par
    l'élément qui occupait cet indice avant la mutation -- Streamlit
    ignore `value=` tant que la clé existe déjà en session_state."""
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(prefixes):
            st.session_state.pop(k, None)
