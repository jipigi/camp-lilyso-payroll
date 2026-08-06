"""Détection des années de paramètres disponibles et fusion QC + Canada.

Spec de référence : ``interface-streamlit`` — tâche 16.1.
Design de référence : ``design.md`` §Components 5.
Règle 05 : aucun taux/plafond/constante fiscale codé en dur dans ce
module — ``charger_parametres_fusionnes`` délègue intégralement à
``payroll_engine.parameters_loader.load_parameters``.

Ce module expose :

- :func:`lister_annees_disponibles` (Req 6.1) : les années pour
  lesquelles ``parameters/<AAAA>/`` existe sur disque avec les deux
  fichiers requis (``quebec.json`` et ``canada.json``).
- :func:`charger_parametres_fusionnes` (Req 6.2, Req 6.4) : charge et
  fusionne les paramètres Québec et Canada d'une année en un unique
  ``ParametresAnnee``, sans intercepter ``FileNotFoundError``.
"""

from __future__ import annotations

from pathlib import Path

from models.enums import Juridiction
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters


def lister_annees_disponibles(chemin_racine: Path | None = None) -> tuple[int, ...]:
    """Années pour lesquelles `parameters/<AAAA>/` existe sur disque (Req 6.1).

    Une année est retenue si son dossier contient à la fois `quebec.json`
    et `canada.json` (les deux fichiers nécessaires à la fusion de
    l'AC2) — un dossier incomplet n'est pas proposé à la sélection.
    Résolution par défaut identique à celle de `load_parameters`
    (`Path(__file__).parent.parent.parent / "parameters"`, cohérente
    avec Req 9.9 de `moteur-paie-contrats`), injectable pour les tests.
    Retourne un tuple trié par année croissante ; tuple vide si le
    dossier racine n'existe pas.
    """
    racine = chemin_racine or (Path(__file__).parent.parent.parent / "parameters")
    if not racine.exists():
        return ()
    annees = []
    for enfant in racine.iterdir():
        if not enfant.is_dir() or not enfant.name.isdigit():
            continue
        if (enfant / "quebec.json").exists() and (enfant / "canada.json").exists():
            annees.append(int(enfant.name))
    return tuple(sorted(annees))


def charger_parametres_fusionnes(
    annee: int, chemin_racine: Path | None = None
) -> ParametresAnnee:
    """Charge et fusionne QUEBEC + CANADA pour ``annee`` (Req 6.2).

    Réutilise **exactement** le patron déjà établi par
    `tests/strategies.py::_charger_parametres_annee_2026_qc_ca` (racine
    Québec enrichie de `assurance_emploi` et `impot_federal` de la racine
    Canada, via `model_copy(update=...)`, sans mutation). Toute
    `FileNotFoundError` levée par `load_parameters` (fichier absent)
    n'est pas interceptée (Req 6.4) — elle remonte telle quelle.
    """
    parametres_qc = load_parameters(annee, Juridiction.QUEBEC, chemin_racine)
    parametres_ca = load_parameters(annee, Juridiction.CANADA, chemin_racine)
    return parametres_qc.model_copy(
        update={
            "assurance_emploi": parametres_ca.assurance_emploi,
            "impot_federal": parametres_ca.impot_federal,
        }
    )
