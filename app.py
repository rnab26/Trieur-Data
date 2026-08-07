# =============================================================
# Trieur de Data
# VERSION 5.1 :
#   [DEDUP] Suppression reelle des doublons (onglet Filtrage & Dedup), avec
#       choix de la ligne a garder (premiere importee, ou la plus complete).
#   [IBAN] Verification du checksum (mod 97) apres construction de la base :
#       signale les IBAN a la forme correcte mais au checksum invalide
#       (saisie ou OCR PDF), sans rien supprimer automatiquement.
#   [EXPORT] Presets d'export nommes (ordre + selection des colonnes),
#       persistance dans export_presets.json, meme logique que les filtres
#       pre-enregistres.
#   [MEMOIRE MAPPING] Le mapping confirme au moment de "Construire la base"
#       est memorise par FORME de fichier (empreinte des noms de colonnes,
#       independante de l'ordre/casse) dans remembered_mappings.json, et
#       reapplique automatiquement au prochain fichier de meme structure
#       (utile en re-import mobile repete).
#
# Version 5.0  (GROS FICHIERS : plusieurs millions de lignes sans lenteur)
#
#   [CSV] Import direct de fichiers CSV (bien plus rapide/leger que le .xlsx) :
#         separateur et encodage auto-detectes, deduction d'en-tete comme pour
#         Excel. C'est la voie recommandee pour les tres gros volumes.
#   [FILTRE] Onglet Filtrage fluide meme sur des millions de lignes :
#         - plus de recopie de toute la base a chaque clic (grosse lenteur)
#         - filtre par departement (CP) VECTORISE (plus de boucle Python/ligne)
#         - au-dela de 1000 valeurs distinctes, filtre par TEXTE au lieu d'un
#           menu geant qui fige le navigateur
#         - comptage des doublons uniquement a la demande (bouton)
#   [BUILD] Construction plus legere : colonnes a faible cardinalite (Source
#         Data, ville, civilite) stockees en "category" (Source Data : ~29 Mo
#         -> ~1 Mo par million de lignes), moins de copies au pic memoire.
#   [EXPORT] Genere le fichier UNIQUEMENT au clic (avant, le CSV ET l'Excel
#         etaient regeneres a chaque affichage de l'onglet -> l'Excel de
#         plusieurs millions de lignes prenait des minutes pour rien). Excel
#         desactive au-dela de sa limite (~1,05 M lignes/onglet) ; CSV conseille.
#
# Version 4.7 (repart du visuel v4.3, plus 3 corrections) :
#   [DEFILEMENT] Les menus des colonnes maitres ne se TASSENT plus quand un
#       fichier/onglet a beaucoup de colonnes : chaque colonne a une largeur
#       fixe et TOUT le tableau (menus + apercu) defile horizontalement d'un
#       seul bloc, comme on fait defiler les colonnes d'un fichier importe.
#       Les valeurs passent a la ligne au lieu d'etre tronquees.
#   [TEL] Detection telephone mobile/fixe par le SENS du nom de la colonne
#       maitre, et non par un libelle fige : renommer "TELEPHONE MOBILE" en
#       "phone mobile" (ou "portable", "GSM"...) — et "TELEPHONE FIXE" en
#       "phone fixe" — n'empeche plus la detection ni le routage par contenu.
#   [FIX] Plus de crash Cloud si un en-tete de colonne est un nombre
#       (str() sur le libelle du menu).
#   [SOURCE] La colonne source affiche le VRAI nom du classeur Google (lu
#       dans l'en-tete du telechargement) au lieu de "Google Sheets".
#
# Version 4.3 :
#   [7 - tableau aligne] Le mapping et l'apercu ne forment plus qu'UN SEUL
#       tableau : la ligne de menus (colonnes maitres) et les lignes de donnees
#       partagent la meme grille de colonnes -> memes largeurs, alignement
#       parfait, comme des cellules empilees. La ligne des menus a un fond
#       bleute pour la distinguer ; les cellules de donnees sont compactes.
#
# Version 4.2 :
#   [7 - retour visuel] Presentation compacte facon tableau (rangee de menus +
#       apercu), en remplacement de la grille "menu + apercu par colonne" v4.0.
#   [ALERTE] Seuil volume a 600 000 lignes ; texte corrige (2,7 Go de RAM).
#
# Version 4.1 (PERFORMANCE gros fichiers) :
#   [PERF] Lecture Excel/Google Sheets avec le moteur "calamine" (~3x plus
#          rapide et plus econome qu'openpyxl), avec repli automatique.
#   [MEM]  Moins de copies memoire a l'import (suppression des .copy()
#          inutiles) + liberation des DataFrames intermediaires apres la
#          construction de la base.
#   [ALERTE] Avertissement quand le volume total est eleve : sur
#          l'hebergement gratuit (1 Go RAM), un tres gros fichier peut
#          ralentir ou faire redemarrer l'app.
#
# Version 4.0 :
#   [7] Menus de mapping ALIGNES au-dessus de chaque colonne + texte lisible.
#   [10] Design epure facon Apple (CSS global sobre).
#
# Versions precedentes :
#   [5] Filtres PRE-ENREGISTRES (onglet Filtrage) : nommer / appliquer /
#       renommer / supprimer, persistance dans saved_filters.json.
#   [4] Google Sheets ACCELERE : classeur entier en UNE requete (export xlsx),
#       repli CSV si echec. + bouton "Vider le cache" (garde la base).
#
# [REORG] Le code est reparti en modules (aucun changement de comportement) :
#           trieur/matching.py     -> normalisation, detection telephone,
#                                      deduction d'en-tetes, auto-assignation
#           trieur/filters.py      -> code postal / departements
#           trieur/io_excel.py     -> lecture Excel / Google Sheets
#           trieur/io_pdf.py       -> lecture PDF (SEPA)
#           trieur/export.py       -> export CSV / Excel + nom de fichier
#           trieur/persistence.py  -> colonnes maitres + filtres + presets export
#                                      + mapping memorise par forme de fichier
#           views/tab1_colonnes_maitres.py -> onglet 1 (colonnes maitres)
#           views/tab2_import_mapping.py   -> onglet 2 (import + mapping)
#           views/tab3_filtrage_dedup.py   -> onglet 3 (filtrage + dedup)
#           views/tab4_export.py           -> onglet 4 (export)
#         app.py ne contient plus que la config de page, le CSS global,
#         l'initialisation de session_state, et l'assemblage des 4 onglets.
#
# Historique fonctionnel (inchange) :
#   [1] Detection telephone MOBILE / FIXE par le CONTENU (prefixes FR)
#   [2] Deduction des noms de colonnes quand la ligne d'en-tete est ABSENTE
#   [3] Exclusion de fichiers / onglets a l'import
#   [6] Colonnes maitres PERSISTANTES (survivent au rechargement)
#   [8] Limite d'upload portee a 500 Mo (voir .streamlit/config.toml)
#   [9] Nom du fichier final personnalisable avant export (CSV / Excel)
#   [PERF 1.1] Detection telephone echantillonnee (cout constant)
#   [PERF 1.2] Fin des rechargements inutiles (cache par signature)
# =============================================================

import streamlit as st

from trieur.persistence import (
    load_export_presets,
    load_master_columns,
    load_remembered_mappings,
    load_saved_filters,
)

import views.tab1_colonnes_maitres as view_tab1
import views.tab2_import_mapping as view_tab2
import views.tab3_filtrage_dedup as view_tab3
import views.tab4_export as view_tab4

LOGO_PATH = "assets/logo.png"

st.set_page_config(page_title="Trieur de Data", page_icon=LOGO_PATH, layout="wide")

APP_VERSION = "5.1"

# -------------------------------------------------------------
# [13] DESIGN "FEUTRE ELEGANT" (CSS global, purement cosmetique)
# Palette + typographie choisies parmi 3 pistes proposees et validees par
# l'utilisateur (fond gris-bleu doux, cartes flottantes a ombre legere,
# titres en serif, accent bleu petrole). N'affecte aucun comportement ;
# se contente d'affiner l'apparence.
# -------------------------------------------------------------
st.markdown(
    """
    <style>
      :root {
          --bg: #F1F3F5;
          --card: #FFFFFF;
          --ink: #1D2229;
          --muted: #667080;
          --border: #DCE2E7;
          --accent: #1F6F8B;
          --accent-soft: #E4EEF2;
          --danger: #A6433F;
          --font-display: Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
          --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      }

      html, body, [class*="css"], .stApp {
          background: var(--bg);
          color: var(--ink);
          font-family: var(--font-body);
          -webkit-font-smoothing: antialiased;
      }

      /* Titres : serif, pour une touche plus feutree/editoriale */
      h1, h2, h3 {
          font-family: var(--font-display);
          letter-spacing: -0.005em;
          font-weight: 600;
          color: var(--ink);
      }
      .block-container { padding-top: 2.2rem; max-width: 1300px; }
      p, span, div, label { color: var(--ink); }
      [data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }

      /* Boutons : coins arrondis, transition douce */
      .stButton > button, .stDownloadButton > button {
          background: var(--card);
          border-radius: 10px;
          border: 1px solid var(--border);
          padding: 0.45rem 1.0rem;
          font-weight: 500;
          color: var(--ink);
          transition: all 0.15s ease;
      }
      .stButton > button:hover, .stDownloadButton > button:hover {
          border-color: var(--accent);
          color: var(--accent);
      }
      /* Bouton principal : bleu petrole plein, ombre douce */
      .stButton > button[kind="primary"] {
          background: var(--accent);
          color: #fff;
          border: none;
          box-shadow: 0 4px 12px -4px rgba(31,111,139,0.45);
      }
      .stButton > button[kind="primary"]:hover {
          background: #1a5f78;
          color: #fff;
      }

      /* Champs et menus : coins arrondis, fond carte */
      .stSelectbox div[data-baseweb="select"] > div,
      .stTextInput input, .stTextArea textarea {
          border-radius: 10px;
          background: var(--card);
          border-color: var(--border);
          color: var(--ink);
      }

      /* Onglets : plus d'air, soulignement accent */
      .stTabs [data-baseweb="tab-list"] { gap: 0.4rem; border-bottom-color: var(--border); }
      .stTabs [data-baseweb="tab"] {
          border-radius: 10px 10px 0 0;
          padding: 0.4rem 1rem;
          color: var(--muted);
      }
      .stTabs [aria-selected="true"] { color: var(--accent) !important; }
      .stTabs [data-baseweb="tab-highlight"] { background-color: var(--accent) !important; }

      /* Tableaux, cartes, expanders : coins arrondis, ombre douce plutot
         qu'une simple bordure -- l'effet "carte flottante" de la direction
         retenue. */
      [data-testid="stDataFrame"] {
          border-radius: 12px;
          border: 1px solid var(--border);
          box-shadow: 0 6px 20px -12px rgba(20,40,55,0.18);
      }
      [data-testid="stExpander"] {
          border-radius: 12px;
          border: 1px solid var(--border);
          background: var(--card);
          box-shadow: 0 6px 20px -14px rgba(20,40,55,0.14);
      }
      div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[style*="border"]) {
          box-shadow: 0 6px 20px -14px rgba(20,40,55,0.14);
      }

      /* [7] Libelles de menus : affiches en ENTIER, jamais tronques, meme sur
         des colonnes etroites (utile pour la rangee de mapping). */
      .stSelectbox label, .stSelectbox label p {
          white-space: normal !important;
          overflow-wrap: anywhere;
          word-break: break-word;
          line-height: 1.15;
      }

      /* [7] TABLEAU DE MAPPING : menus + apercu = un seul tableau aligne.
         Cible le conteneur st.container(key="maptbl-N") -> classe st-key-maptbl-N. */

      /* [DEFILEMENT] Quand un fichier/onglet a beaucoup de colonnes, les menus
         des colonnes maitres ne se TASSENT plus : chaque colonne garde une
         largeur fixe et TOUT le tableau (menus + apercu) defile horizontalement
         d'un seul bloc -> les menus restent alignes au-dessus de leur colonne,
         exactement comme on fait defiler les colonnes d'un fichier importe. */
      [class*="st-key-maptbl-"] {
          overflow-x: auto;
      }
      [class*="st-key-maptbl-"] [data-testid="stHorizontalBlock"] {
          flex-wrap: nowrap !important;     /* pas de retour a la ligne */
          width: max-content;
          min-width: 100%;
          gap: 0.25rem !important;          /* colonnes serrees */
      }
      [class*="st-key-maptbl-"] [data-testid="stColumn"] {
          flex: 0 0 160px !important;       /* largeur fixe -> jamais tasse */
          width: 160px !important;
          min-width: 160px !important;
      }
      [class*="st-key-maptbl-"] [data-testid="stVerticalBlock"] {
          gap: 0.15rem !important;          /* lignes serrees (compact) */
      }
      /* Ligne des menus : fond accent-soft + bordure accent = distinction
         "colonne maitre" (repris de la palette feutre elegant). */
      [class*="st-key-maptbl-"] .stSelectbox div[data-baseweb="select"] > div {
          background: var(--accent-soft);
          border: 1px solid var(--accent);
          border-radius: 8px;
          min-height: 34px;
      }
      /* Cellules de donnees : aspect tableau compact. La largeur des colonnes
         etant fixe, les valeurs passent A LA LIGNE au lieu d'etre tronquees. */
      [class*="st-key-maptbl-"] .mapcell {
          font-size: 0.8rem;
          padding: 3px 6px;
          border-bottom: 1px solid var(--border);
          white-space: normal;
          overflow-wrap: anywhere;
          word-break: break-word;
          color: var(--muted);
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# -------------------------------------------------------------
# INITIALISATION SESSION
# -------------------------------------------------------------
if "master_columns" not in st.session_state:
    st.session_state.master_columns = load_master_columns()
if "all_sheets" not in st.session_state:
    st.session_state.all_sheets = {}
if "sheet_mappings" not in st.session_state:
    st.session_state.sheet_mappings = {}
if "final_df" not in st.session_state:
    st.session_state.final_df = None
if "filtered_df" not in st.session_state:
    st.session_state.filtered_df = None
if "export_mode" not in st.session_state:
    st.session_state.export_mode = "fusionné"
if "export_name_base" not in st.session_state:
    st.session_state.export_name_base = ""
if "auto_assign_triggered" not in st.session_state:
    st.session_state.auto_assign_triggered = {}
# [3] Onglets exclus par l'utilisateur (cles "fichier :: onglet")
if "excluded_sheets" not in st.session_state:
    st.session_state.excluded_sheets = set()
# [2] Onglets dont l'en-tete a ete deduite (pour prevenir l'utilisateur)
if "inferred_header_sheets" not in st.session_state:
    st.session_state.inferred_header_sheets = []
# [5] Filtres pre-enregistres (charges depuis saved_filters.json)
if "saved_filters" not in st.session_state:
    st.session_state.saved_filters = load_saved_filters()
# [11] Presets d'export (ordre/selection des colonnes, charges depuis export_presets.json)
if "export_presets" not in st.session_state:
    st.session_state.export_presets = load_export_presets()
# [12] Mapping memorise par forme de fichier (charges depuis remembered_mappings.json)
if "remembered_mappings" not in st.session_state:
    st.session_state.remembered_mappings = load_remembered_mappings()


col_logo, col_title = st.columns([1, 8])
with col_logo:
    st.image(LOGO_PATH, width=72)
with col_title:
    st.title("Trieur de Data")
st.caption(f"Import Excel ou Google Sheets → mapping colonnes → aperçu → filtrage → export · v{APP_VERSION}")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage & Dedup", "4. Export"])

with tab1:
    view_tab1.render()

with tab2:
    view_tab2.render()

with tab3:
    view_tab3.render()

with tab4:
    view_tab4.render()
