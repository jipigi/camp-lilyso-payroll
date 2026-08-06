"""Configuration statique de l'employeur — Camp LilySO (Req bulletin de paie).

Ce module porte les informations d'identification de l'employeur qui
figurent sur le Bulletin_De_Paie (`app/pages_ui/bulletin_paie.py`) :
nom, adresse, ville, code postal, numéro NQE (numéro d'identification
d'employeur au registraire des entreprises du Québec).

Ces informations ne sont **saisies nulle part dans l'application** —
elles sont fixes pour l'organisation et ne varient jamais d'un
employé ou d'une paie à l'autre. Décision explicite (discussion avec
l'utilisateur) : plutôt que de les coder en dur directement dans la
page de rendu, elles sont centralisées dans ce module dédié, séparé de
`app/logique_metier/**` (ce module ne fait aucun calcul, aucune E/S —
il n'a donc pas besoin de vivre sous `logique_metier/`, mais reste
importable depuis `app/pages_ui/**` sans dépendance à `streamlit`).

Règle 04 (données sensibles) : ces informations sont des coordonnées
publiques de l'organisation (adresse commerciale, numéro
d'immatriculation), pas des données personnelles d'un individu — leur
présence dans le dépôt versionné ne contrevient pas à la règle 04.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigEmployeur:
    """Informations d'identification de l'employeur affichées sur le
    Bulletin_De_Paie."""

    nom: str
    adresse: str
    ville: str
    code_postal: str
    numero_nqe: str


#: Instance unique — Camp LilySO. Valeurs reprises du gabarit
#: `intake/fiches-paie/Bulletin-paie-gabarit.xlsx` (hors dépôt, règle 04
#: — mais ces valeurs elles-mêmes ne sont pas des données personnelles).
CONFIG_EMPLOYEUR = ConfigEmployeur(
    nom="Camp LilySO",
    adresse="18 rue des sentiers",
    ville="Fossambault-sur-le-Lac (QC)",
    code_postal="G3N 1Z7",
    numero_nqe="1182320557",
)
