# =============================================================
# Cockpit : réservé aux administrateurs. Sert UNIQUEMENT au
# développement du logiciel (chantiers, demandes, fil de discussion
# avec Claude) -- rien à voir avec les données clients / l'historique
# d'import, qui vivent dans l'onglet "Base de données".
#
# Structure calquée sur le CLAUDE.md global de l'utilisateur (section
# "Mémoire et continuité entre sessions") : les chantiers en attente
# d'une réponse de l'utilisateur ressortent en premier, les terminés
# sont archivés (jamais supprimés) et repliés par défaut, et chaque
# chantier porte des points cochables ("coche ce qui est fait plutôt
# que de le supprimer, note les points restés ouverts") en plus du fil
# de discussion libre.
# =============================================================

from datetime import datetime, timezone

import streamlit as st

from trieur.db import (
    add_chantier_message,
    add_chantier_todo,
    create_chantier,
    create_section,
    get_derniere_visite_cockpit,
    list_chantier_messages,
    list_chantier_todos,
    list_chantiers,
    list_sections,
    marquer_cockpit_vu,
    set_chantier_todo_done,
    update_chantier_status,
)
from views._auth import accessible_organizations, require_login

SANS_SECTION = "— Sans section —"
NOUVELLE_SECTION = "+ Nouvelle section..."

STATUT_LABELS = {
    "a_faire": "📋 À faire",
    "en_cours": "🔧 En cours",
    "attente_retour": "⏳ Attente de ta réponse",
    "termine": "✅ Terminé",
    "abandonne": "⛔ Abandonné",
}

# Ordre d'affichage : ce qui a besoin de toi d'abord, ce qui est clos en dernier.
STATUT_ORDER = ["attente_retour", "en_cours", "a_faire", "termine", "abandonne"]
STATUT_ACTIFS = ["attente_retour", "en_cours", "a_faire"]
STATUT_ARCHIVES = ["termine", "abandonne"]


def render():
    try:
        configured = "supabase" in st.secrets
    except Exception:
        configured = False

    if not configured:
        st.info(
            "Le Cockpit n'est pas encore configuré (clés Supabase manquantes "
            "dans les Secrets Streamlit Cloud). Le reste de l'app fonctionne "
            "normalement."
        )
        return

    ctx = require_login()

    if not ctx["profile"].get("is_super_admin"):
        st.warning("Le Cockpit est réservé aux administrateurs.")
        return

    client = ctx["client"]
    user = ctx["user"]

    all_orgs = accessible_organizations(ctx)
    if not all_orgs:
        st.info("Aucun espace accessible.")
        return

    org_labels = {o["id"]: o["name"] for o in all_orgs}
    org_id = st.selectbox(
        "Environnement du chantier",
        options=list(org_labels.keys()),
        format_func=lambda oid: org_labels[oid],
        key="cockpit_org_select",
    )

    chantiers = list_chantiers(client, org_id)
    sections = list_sections(client, org_id)

    derniere_visite = get_derniere_visite_cockpit(client, user.id)
    _render_bandeau_depuis_derniere_visite(client, chantiers, derniere_visite)
    _render_ou_jen_suis(chantiers)

    noms_sections = [s["nom"] for s in sections]

    with st.expander("➕ Nouveau chantier"):
        with st.form("new_chantier_form", clear_on_submit=True):
            title = st.text_input("Titre du chantier / de la demande")
            priority = st.select_slider("Priorité", options=["basse", "normale", "haute"], value="normale")
            section_choisie = st.selectbox(
                "Section", options=[SANS_SECTION] + noms_sections + [NOUVELLE_SECTION],
            )
            nouvelle_section_nom = ""
            if section_choisie == NOUVELLE_SECTION:
                nouvelle_section_nom = st.text_input("Nom de la nouvelle section")
            submit_new = st.form_submit_button("Créer", type="primary")
        if submit_new and title.strip():
            if section_choisie == NOUVELLE_SECTION and nouvelle_section_nom.strip():
                create_section(client, org_id, nouvelle_section_nom.strip())
                theme = nouvelle_section_nom.strip()
            elif section_choisie == SANS_SECTION:
                theme = None
            else:
                theme = section_choisie
            create_chantier(client, org_id, title.strip(), priority, user.id, theme=theme)
            st.rerun()

    with st.expander("🗂️ Sections"):
        if sections:
            for s in sections:
                st.caption(f"• {s['nom']}")
        else:
            st.caption("Aucune section déclarée pour l'instant.")
        with st.form("new_section_form", clear_on_submit=True):
            nom_section = st.text_input("Nouvelle section", placeholder="Ex. Export, Imports, Interface...")
            submit_section = st.form_submit_button("Créer la section")
        if submit_section and nom_section.strip():
            create_section(client, org_id, nom_section.strip())
            st.rerun()

    if not chantiers and not sections:
        st.caption("Aucun chantier pour cet environnement pour l'instant.")
        return

    col_search, col_filter = st.columns([2, 1])
    with col_search:
        recherche = st.text_input(
            "Chercher un chantier", key="cockpit_recherche", placeholder="Chercher un chantier...",
            label_visibility="collapsed",
        )
    with col_filter:
        filtre_statut = st.selectbox(
            "Filtrer par statut",
            options=["tous"] + STATUT_ACTIFS,
            format_func=lambda s: "Tous les statuts actifs" if s == "tous" else STATUT_LABELS[s],
            key="cockpit_filtre_statut",
            label_visibility="collapsed",
        )

    def _correspond(ch):
        if recherche and recherche.strip().lower() not in ch["title"].lower():
            return False
        if filtre_statut != "tous" and ch["status"] != filtre_statut:
            return False
        return True

    by_status = {s: [] for s in STATUT_ORDER}
    for ch in chantiers:
        by_status.setdefault(ch["status"], []).append(ch)

    actifs = [ch for s in STATUT_ACTIFS for ch in by_status.get(s, [])]
    actifs_visibles = [ch for ch in actifs if _correspond(ch)]

    if not actifs_visibles:
        if actifs:
            st.caption("Aucun chantier actif ne correspond à cette recherche/ce filtre.")
        elif not sections:
            st.caption("Aucun chantier actif — tout est terminé ou abandonné.")

    # Groupés par section déclarée, dans l'ordre choisi, puis les chantiers
    # dont le thème ne correspond à AUCUNE section déclarée (dictée à la
    # voix ou tapée avant qu'une section existe) sous "À classer" -- jamais
    # perdus, jamais rattachés en silence à la mauvaise section.
    par_theme: dict[str | None, list[dict]] = {}
    for ch in actifs_visibles:
        par_theme.setdefault(ch.get("theme"), []).append(ch)

    for section in sections:
        chantiers_section = par_theme.pop(section["nom"], [])
        if not chantiers_section and (recherche or filtre_statut != "tous"):
            continue  # une section vide sous un filtre actif n'a rien à montrer
        st.markdown(f"#### {section['nom']}")
        if not chantiers_section:
            st.caption("Aucun chantier actif dans cette section.")
        for ch in chantiers_section:
            _render_chantier(client, ch, user)

    a_classer = par_theme.pop(None, []) + [
        ch for theme, chs in par_theme.items() for ch in chs
    ]
    if a_classer:
        if sections:
            st.markdown("#### À classer")
        for ch in a_classer:
            _render_chantier(client, ch, user)

    archives = [ch for s in STATUT_ARCHIVES for ch in by_status.get(s, [])]
    if archives:
        with st.expander(f"📦 Chantiers clos ({len(archives)})"):
            for ch in archives:
                _render_chantier(client, ch, user, compact=True)


def _parse_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _render_ou_jen_suis(chantiers: list[dict]) -> None:
    """Le résumé "où j'en suis" (cockpit-kit/FONCTIONNALITES.md, point 1) :
    quatre nombres, jamais cinq -- un chantier "abandonne" (l'équivalent
    d'un [REPORTÉ]/[BLOQUÉ] sur Jarvis) ne compte dans AUCUNE des colonnes,
    plutôt que de forcer une case qui mentirait sur son vrai état."""
    if not chantiers:
        return

    aujourdhui = datetime.now(timezone.utc).date()
    bouge = sum(1 for c in chantiers if c["status"] == "en_cours")
    livre = sum(
        1 for c in chantiers
        if c["status"] == "termine" and (d := _parse_dt(c["updated_at"])) and d.date() == aujourdhui
    )
    pour_toi = sum(1 for c in chantiers if c["status"] == "attente_retour")
    dort = sum(1 for c in chantiers if c["status"] == "a_faire")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Bouge", bouge)
    col2.metric("Livré aujourd'hui", livre)
    col3.metric("Pour toi", pour_toi)
    col4.metric("Dort", dort)


def _render_bandeau_depuis_derniere_visite(client, chantiers: list[dict], derniere_visite: str | None) -> None:
    """cockpit-kit/FONCTIONNALITES.md, point 2. Silencieux à la toute
    première visite (aucun repère = rien à comparer, présenter tout
    l'historique comme "nouveau" serait faux) -- même règle que sur
    Jarvis. Le bouton "Vu" appelle marquer_cockpit_vu(), dont le
    non-recul est garanti côté SQL (greatest()), pas ici."""
    if derniere_visite is None:
        if st.button("👋 Marquer le cockpit comme vu", key="cockpit_premiere_visite"):
            marquer_cockpit_vu(client)
            st.rerun()
        return

    seuil = _parse_dt(derniere_visite)
    livres = [c for c in chantiers if c["status"] == "termine" and (d := _parse_dt(c["updated_at"])) and d > seuil]
    nouveaux = [c for c in chantiers if (d := _parse_dt(c["created_at"])) and d > seuil]

    if not livres and not nouveaux:
        return

    with st.container(border=True):
        col_texte, col_bouton = st.columns([4, 1])
        with col_texte:
            morceaux = []
            if livres:
                morceaux.append(f"**{len(livres)}** livré{'s' if len(livres) > 1 else ''}")
            if nouveaux:
                morceaux.append(f"**{len(nouveaux)}** nouveau{'x' if len(nouveaux) > 1 else ''}")
            st.markdown("Depuis ton dernier passage : " + ", ".join(morceaux))
            for ch in livres[:5]:
                st.caption(f"✓ {ch['title']}")
        with col_bouton:
            if st.button("Vu", key="cockpit_marquer_vu"):
                marquer_cockpit_vu(client)
                st.rerun()


def _render_chantier(client, ch, user, compact=False):
    with st.container(border=True):
        col_title, col_status = st.columns([3, 1])
        with col_title:
            st.markdown(f"**{ch['title']}**")
            st.caption(f"Priorité {ch['priority']} · mis à jour {ch['updated_at']}")
        with col_status:
            new_status = st.selectbox(
                "Statut",
                options=STATUT_ORDER,
                index=STATUT_ORDER.index(ch["status"]),
                format_func=lambda s: STATUT_LABELS[s],
                key=f"status_{ch['id']}",
                label_visibility="collapsed",
            )
            if new_status != ch["status"]:
                update_chantier_status(client, ch["id"], new_status)
                st.rerun()

        _render_todos(client, ch["id"])

        with st.expander("Fil de discussion", expanded=not compact and ch["status"] == "attente_retour"):
            messages = list_chantier_messages(client, ch["id"])
            for msg in messages:
                author = "🧑 Toi" if msg["author_type"] == "user" else "🤖 Claude"
                st.markdown(f"**{author}** · {msg['created_at']}")
                st.write(msg["body"])
                st.divider()

            reply = st.text_area("Ajouter un message", key=f"reply_{ch['id']}")
            if st.button("Envoyer", key=f"send_{ch['id']}"):
                if reply.strip():
                    add_chantier_message(client, ch["id"], reply.strip(), user.id)
                    st.rerun()


def _render_todos(client, chantier_id):
    """Points cochables : jamais supprimés une fois faits, juste cochés
    (voir CLAUDE.md -- "coche ce qui est fait plutôt que de le supprimer")."""
    todos = list_chantier_todos(client, chantier_id)
    if todos:
        for todo in todos:
            checked = st.checkbox(
                todo["body"], value=todo["done"], key=f"todo_{todo['id']}"
            )
            if checked != todo["done"]:
                set_chantier_todo_done(client, todo["id"], checked)
                st.rerun()

    new_todo = st.text_input(
        "Ajouter un point à suivre", key=f"newtodo_{chantier_id}", label_visibility="collapsed",
        placeholder="Ajouter un point à suivre pour ce chantier...",
    )
    if st.button("➕", key=f"addtodo_{chantier_id}"):
        if new_todo.strip():
            add_chantier_todo(client, chantier_id, new_todo.strip())
            st.rerun()
