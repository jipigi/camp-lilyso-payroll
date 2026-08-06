"""Annuaire_Coordonnees — `FicheCoordonnees` et cycle CRUD (Req 20).

Spec de référence : ``interface-streamlit`` — tâche 14.1.
Design de référence : ``design.md`` §Components §3 (`annuaire_coordonnees.py`
— `FicheCoordonnees` et cycle CRUD) ; §Data Models (schéma `FicheCoordonnees`).

Règle 04 (données sensibles) : ``chemin_annuaire_coordonnees_production()``
résout un chemin **hors** du dépôt versionné (même répertoire que
``chemin_bd_production()``, décision n° 2/8 du design) — ce module ne
contient et ne code en dur aucune donnée personnelle réelle. Rappel
explicite : ``FicheCoordonnees`` est délibérément placée sous ``app/``,
**jamais** sous ``models/`` (décision n° 8) — ce modèle porte des données
personnelles réelles en production, à l'opposé du contrat de calcul
(``models.employee.Employee``, qui les interdit via
``reject_sensitive_fields``). ``FicheCoordonnees`` n'a donc délibérément
**aucun** validateur `reject_sensitive_fields`/`reject_float` : ce serait
un contresens vis-à-vis de sa raison d'être.

Règle 01 : aucun champ de ``FicheCoordonnees`` n'est un ``Decimal`` —
absence de montant monétaire (cohérent avec le Glossary de
``requirements.md``) — la règle ne s'applique pas à ce module.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from payroll_engine.register import chemin_bd_production
from app.logique_metier.stockage_json import ecrire_atomique, lire_texte_ou_defaut


class FicheCoordonnees(BaseModel):
    """Coordonnées opérationnelles d'un employé (Req 20) — JAMAIS transmise
    à `assembler_paie`, `PayrollInput`, `Employee` ni à aucune fonction de
    `payroll_engine/` (Req 20.3, Req 18.4). Définie sous `app/`, jamais
    sous `models/` (décision n° 8) : ce modèle porte délibérément des
    données personnelles réelles en production, à l'inverse du contrat de
    calcul qui les interdit (règle 04, `reject_sensitive_fields`).

    Aucun champ n'est un `Decimal` — la règle 01 ne s'applique pas à ce
    modèle (absence de montant monétaire, cohérent avec le Glossary).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    employe_id: str = Field(..., min_length=1)
    nom_complet_reel: str | None = None
    nas: str | None = None
    adresse_residentielle: str | None = None
    courriel: str | None = None
    telephone: str | None = None


def chemin_annuaire_coordonnees_production() -> Path:
    """Chemin de production de l'Annuaire_Coordonnees (Req 20.7, décision n° 2).

    Dérivé de ``chemin_bd_production()`` (résolution `%APPDATA%`/
    `XDG_DATA_HOME`/repli déjà figée par ``payroll_engine.register``) —
    aucune duplication de cette logique.
    """
    return chemin_bd_production().parent / "coordonnees.json"


def lister_coordonnees(
    chemin_coordonnees: Path = chemin_annuaire_coordonnees_production(),
) -> tuple[FicheCoordonnees, ...]:
    """Liste toutes les Fiche_Coordonnees (helper interne à ce module).

    Même patron que `lister_employes` — tuple vide si le fichier n'existe
    pas encore (Req 20.7), aucune exception. Chaque élément du tableau
    JSON brut est ré-encodé individuellement (``json.dumps``) puis
    repassé à ``FicheCoordonnees.model_validate_json`` (décision n° 3).
    """
    brut = lire_texte_ou_defaut(chemin_coordonnees, defaut="[]")
    elements = json.loads(brut)
    return tuple(
        FicheCoordonnees.model_validate_json(json.dumps(element))
        for element in elements
    )


def enregistrer_coordonnees(
    fiche: FicheCoordonnees,
    chemin_coordonnees: Path = chemin_annuaire_coordonnees_production(),
) -> None:
    """Enregistre ``fiche`` — création ou mise à jour par ``employe_id`` (Req 20.1).

    Lit l'annuaire courant (via ``lister_coordonnees``, réutilisation sans
    duplication de la logique de lecture), remplace toute Fiche_Coordonnees
    de même ``employe_id`` par ``fiche`` ou l'ajoute si absente, puis
    réécrit l'annuaire complet de façon atomique (``ecrire_atomique``,
    Req 20.5).
    """
    existantes = {f.employe_id: f for f in lister_coordonnees(chemin_coordonnees)}
    existantes[fiche.employe_id] = fiche
    contenu = "[" + ",".join(f.model_dump_json() for f in existantes.values()) + "]"
    ecrire_atomique(chemin_coordonnees, contenu)


def lire_coordonnees(
    employe_id: str,
    chemin_coordonnees: Path = chemin_annuaire_coordonnees_production(),
) -> FicheCoordonnees | None:
    """Lit une Fiche_Coordonnees unique par ``employe_id`` (Req 20.2).

    Retourne ``None`` si absent de l'annuaire (Req 20.7) — jamais
    ``KeyError``, à la différence de ``lire_employe`` : l'absence de
    coordonnées pour un employé est un cas nominal (fiche pas encore
    saisie), pas une erreur.
    """
    for fiche in lister_coordonnees(chemin_coordonnees):
        if fiche.employe_id == employe_id:
            return fiche
    return None
