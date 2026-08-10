"""Navigation entre onglets natifs st.tabs() depuis le code Python.

Streamlit ne permet pas de piloter quel onglet de st.tabs() est actif
depuis le serveur -- st.tabs() est un choix purement client. On simule
donc un clic sur l'onglet cible : pas de rerun serveur, juste un clic JS
sur le bon element [data-baseweb="tab"] apres un court delai (le temps que
le rerun declenche par le bouton lui-meme se termine et que le DOM soit stable).
"""
import streamlit.components.v1 as components


def goto_native_tab(index):
    """Bascule sur l'onglet natif d'index `index` (0 = premier onglet).

    Selecteur verifie sur Streamlit 1.61 : les onglets natifs de st.tabs()
    portent role="tab" et data-testid="stTab" (PAS data-baseweb="tab", qui
    ne matche plus rien sur cette version)."""
    components.html(
        f"""<script>
        setTimeout(function () {{
            var tabs = window.parent.document.querySelectorAll('[data-testid="stTab"]');
            if (tabs.length > {index}) {{ tabs[{index}].click(); }}
        }}, 80);
        </script>""",
        height=0,
    )
