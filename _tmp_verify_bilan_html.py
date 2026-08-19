"""Script temporaire — invoque directement le pipeline de rendu du Bilan
Fiscal (mêmes fonctions que `_afficher_bilan_fiscal`) contre la base de
test isolée, pour confirmer par du code (et non par une capture d'écran)
que le HTML produit contient les libellés attendus.

Règle 04 : mêmes gardes que `_tmp_seed_bilan_fiscal.py` (APPDATA isolé).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_RACINE = str(Path(__file__).resolve().parent)
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

_MARQUEUR_REPERTOIRE_TEST = "_tmp_test_appdata_bilan_fiscal"
_appdata = os.environ.get("APPDATA", "")
if _MARQUEUR_REPERTOIRE_TEST not in _appdata:
    raise SystemExit(
        f"Garde de sécurité (règle 04) : APPDATA doit contenir "
        f"'{_MARQUEUR_REPERTOIRE_TEST}'. Valeur actuelle : {_appdata!r}."
    )

from app.logique_metier.bilan_fiscal import (
    construire_options_periode,
    construire_tableau_bilan_fiscal,
    filtrer_paies_par_periode,
    lire_paies_emises,
)
from app.pages_ui.tableau_de_bord import _construire_html_bilan_fiscal

paies = lire_paies_emises()
print(f"Paies EMISE lues : {len(paies)}")

options = construire_options_periode(paies)
print(f"Options de période générées : {[o.libelle for o in options]}")

# Utilise la première option (année complète la plus récente en principe).
periode = options[0].periode
paies_filtrees = filtrer_paies_par_periode(paies, periode)
tableau = construire_tableau_bilan_fiscal(paies_filtrees)
html = _construire_html_bilan_fiscal(tableau)

attendus = [
    "Retenues et cotisations",
    ">QC<",
    ">CA<",
    "Retenues sur le salaire de l'employé",
    "Cotisations patronales",
    "Grand total combiné (QC + CA)",
]
print("\n--- Vérification des libellés attendus dans le HTML généré ---")
for libelle in attendus:
    present = libelle in html
    print(f"{'OK ' if present else 'MANQUANT'} : {libelle!r}")

print(f"\nDrapeau CNESST agrégé attendu (au moins une paie en attente) : {tableau.cnesst_en_attente_classification}")
