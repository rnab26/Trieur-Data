# =============================================================
# Filet de sécurité de diagnostic -- affiche automatiquement toute
# erreur réelle (n'importe où dans l'app) directement sur l'écran, avec
# la trace complète, au lieu de laisser un plantage silencieux ou un
# message générique. Sert aussi de repère dans les logs Render (type
# "app", les seuls disponibles sur ce service -- Render ne fournit pas
# de logs de requêtes HTTP ici, vérifié).
# =============================================================

import sys
import traceback

import streamlit as st


def report_exception(context: str, exc: Exception) -> None:
    """Affiche la trace complète sur l'écran (visible par l'utilisateur,
    pas besoin de venir me la copier-coller) ET l'imprime sur stdout
    (visible dans les logs Render). `context` identifie l'endroit du
    plantage (ex: "import Trieur de Data", "upload Base de données")."""
    tb = traceback.format_exc()
    print(f"[ERREUR:{context}] {tb}", file=sys.stderr, flush=True)

    st.error(f"❌ Erreur réelle dans « {context} » -- voici le détail complet :")
    st.exception(exc)
    with st.expander("Trace technique complète (à copier si besoin)", expanded=True):
        st.code(tb, language="python")


def render_upload_diagnostics(uploaded, key: str) -> None:
    """Panneau de diagnostic toujours visible sous un uploader -- utile
    justement quand l'échec se produit AVANT d'atteindre notre code Python
    (le widget d'upload lui-même, côté navigateur) : dans ce cas aucune
    exception ne se déclenche jamais côté serveur, donc report_exception()
    ne suffit pas. Affiche l'URL et les en-têtes que Streamlit voit
    réellement (st.context, API stable depuis 1.x) -- si l'URL vue par le
    serveur ne correspond pas à celle de la barre d'adresse du navigateur,
    ou si un en-tête attendu manque, ça pointe directement vers la cause."""
    log_checkpoint(f"upload_widget:{key}", a_recu_un_fichier=uploaded is not None)

    with st.expander("🔧 Diagnostic (à laisser ouvert si l'upload échoue)", expanded=False):
        st.write("**Fichier reçu par le serveur cette exécution :**", uploaded is not None)
        if uploaded is not None:
            st.write("Nom :", uploaded.name, "-- Taille :", uploaded.size, "octets")
        try:
            st.write("**URL vue par le serveur :**", st.context.url)
            st.write("**En-têtes reçus :**")
            st.json(dict(st.context.headers))
        except Exception as exc:  # ce diagnostic ne doit jamais lui-même planter la page
            st.write("(impossible de lire st.context :", exc, ")")


def log_checkpoint(label: str, **details) -> None:
    """Repère de passage imprimé sur stdout (logs Render), horodaté par
    Render lui-même. Sert à savoir si le code Python est atteint du tout
    (ex: le uploader a-t-il seulement reçu un fichier ?) sans attendre une
    exception -- utile quand le blocage est côté navigateur/réseau, avant
    même d'arriver à notre code."""
    print(f"[CHECKPOINT:{label}] {details}", file=sys.stderr, flush=True)
