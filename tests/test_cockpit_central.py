"""Garde-fous du bouton « Demandes » du cockpit central dans le menu du Trieur (14 oct. 2026).

Ce dépôt n'a pas de test JavaScript : on lit les sources. Ce que ça protège :
- le bouton n'apparaît que pour un administrateur (même règle que l'onglet Cockpit) ;
- la balise est bien celle du cockpit (adresse, mode « bouton », identifiant du bouton visé) ;
- une seule porte : rien d'autre que le composant ne pose la balise, donc une seule règle d'accès ;
- le menu défile au lieu d'élargir la page sur téléphone (494 px mesurés sur 390 avant le correctif).

Le parcours réel (personne de connecté, compte normal, administrateur sur ordinateur et sur
téléphone, déconnexion avec le panneau ouvert) a été joué dans Chromium le 14 oct. 2026 : voir
PROJECT_LOG.md. Si ce test devient rouge, relire ce paragraphe avant de le « corriger ».
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _lire(relatif: str) -> str:
    return (SRC / relatif).read_text(encoding="utf-8")


def test_bouton_reserve_aux_administrateurs():
    app = _lire("App.tsx")
    assert re.search(r"\{\s*isAdmin\s*&&\s*<CockpitCentral\s*/>\s*\}", app), (
        "CockpitCentral doit être rendu seulement pour un administrateur (isAdmin), comme l'onglet Cockpit"
    )
    assert app.count("<CockpitCentral") == 1


def test_balise_du_cockpit():
    lib = _lire("lib/cockpitCentral.ts")
    assert "https://rnab26.github.io/Cockpit-General/embed/cockpit-embed.js" in lib
    assert "'data-mode', 'bouton'" in lib
    identifiant = re.search(r"COCKPIT_LIEN_ID\s*=\s*'([a-z0-9-]+)'", lib)
    assert identifiant, "identifiant du bouton du menu introuvable"
    # Le module vise le bouton par cet identifiant : le composant doit porter le même.
    assert "id={COCKPIT_LIEN_ID}" in _lire("components/CockpitCentral.tsx")
    assert "`#${COCKPIT_LIEN_ID}`" in lib
    cle = re.search(r"COCKPIT_CLE\s*=\s*'([^']*)'", lib)
    assert cle and len(cle.group(1)) >= 16 and "__" not in cle.group(1), "clé du projet absente ou restée à remplir"


def test_une_seule_porte():
    for fichier in SRC.rglob("*.ts*"):
        if fichier.name in ("cockpitCentral.ts", "CockpitCentral.tsx"):
            continue
        texte = fichier.read_text(encoding="utf-8")
        assert "poserBalise" not in texte and "cockpit-embed.js" not in texte, (
            f"{fichier.name} pose la balise du cockpit : seul CockpitCentral.tsx doit le faire"
        )


def test_le_composant_retire_ce_quil_a_pose():
    composant = _lire("components/CockpitCentral.tsx")
    assert "poserBalise(" in composant and "retirerBalise(" in composant


def test_menu_defile_au_lieu_de_deborder():
    app = _lire("App.tsx")
    assert "overflow-x-auto" in app and "whitespace-nowrap" in app and "shrink-0" in app
