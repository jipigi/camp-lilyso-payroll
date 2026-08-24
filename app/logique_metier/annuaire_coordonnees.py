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

from app.logique_metier.stockage_json import ecrire_atomique, lire_texte_ou_defaut
from payroll_engine.register import chemin_bd_production


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
    prenom: str | None = None
    nom: str | None = None
    nas: str | None = None
    adresse_residentielle: str | None = None
    courriel: str | None = None
    telephone: str | None = None


def formater_nas(valeur: str) -> str:
    """Formate un NAS saisi selon le gabarit ``999 999 999`` (bug UI
    signalé après démo — mise en forme visible dans le champ de saisie).

    Retire tout caractère non numérique de ``valeur``, tronque à 9
    chiffres (longueur d'un NAS canadien), puis regroupe par blocs de 3
    séparés par une espace — y compris un dernier bloc partiel si moins
    de 9 chiffres ont été saisis (ex. ``"12345"`` → ``"123 45"``),
    puisque cette fonction est destinée à être rappelée à chaque
    caractère saisi (`on_change`), pas seulement sur une valeur complète.

    Fonction pure de formatage d'affichage — ne valide ni la longueur ni
    la conformité du NAS (aucune règle de validité du NAS, ex. algorithme
    de Luhn, n'est implémentée par cette spec ni ailleurs dans le
    projet) ; aucun import ``streamlit`` (règle 04, cohérent avec le
    reste de ce module).
    """
    chiffres = "".join(caractere for caractere in valeur if caractere.isdigit())[:9]
    blocs = [chiffres[i : i + 3] for i in range(0, len(chiffres), 3)]
    return " ".join(blocs)


def chemin_annuaire_coordonnees_production() -> Path:
    """Chemin de production de l'Annuaire_Coordonnees (Req 20.7, décision n° 2).

    Dérivé de ``chemin_bd_production()`` (résolution `%APPDATA%`/
    `XDG_DATA_HOME`/repli déjà figée par ``payroll_engine.register``) —
    aucune duplication de cette logique.
    """
    return chemin_bd_production().parent / "coordonnees.json"


def _migrer_nom_complet_reel_si_present(element: dict) -> dict:
    """Migre l'ancien champ ``nom_complet_reel`` vers ``prenom``/``nom``.

    Bug UI corrigé après livraison (Req affichage du Bulletin_De_Paie —
    scission Prénom/Nom, fidèle au gabarit officiel) : les fiches
    enregistrées avant ce changement portent un champ unique
    ``nom_complet_reel`` (ex. ``"Lily-Soleil Goydadin"``), incompatible
    avec le nouveau schéma (``prenom``, ``nom`` distincts,
    ``extra="forbid"``). Migration additive à la lecture, jamais à
    l'écriture du fichier existant (règle 06 — immutabilité historique,
    même principe que la colonne ``payload_input_json`` de
    ``payroll_engine/register.py``) : découpe naïve sur le premier
    espace (``"Prénom Reste-du-nom"``) — un nom complet sans espace est
    entièrement affecté à ``prenom``, ``nom`` restant ``None``, plutôt
    que de deviner une séparation incorrecte.
    """
    if "nom_complet_reel" not in element:
        return element
    element = dict(element)
    nom_complet = element.pop("nom_complet_reel")
    if nom_complet and "prenom" not in element and "nom" not in element:
        parties = nom_complet.split(" ", 1)
        element["prenom"] = parties[0]
        element["nom"] = parties[1] if len(parties) > 1 else None
    return element


def lister_coordonnees(
    chemin_coordonnees: Path = chemin_annuaire_coordonnees_production(),
) -> tuple[FicheCoordonnees, ...]:
    """Liste toutes les Fiche_Coordonnees (helper interne à ce module).

    Même patron que `lister_employes` — tuple vide si le fichier n'existe
    pas encore (Req 20.7), aucune exception. Chaque élément du tableau
    JSON brut est d'abord migré (:func:`_migrer_nom_complet_reel_si_present`)
    puis ré-encodé individuellement (``json.dumps``) et repassé à
    ``FicheCoordonnees.model_validate_json`` (décision n° 3).
    """
    brut = lire_texte_ou_defaut(chemin_coordonnees, defaut="[]")
    elements = json.loads(brut)
    return tuple(
        FicheCoordonnees.model_validate_json(
            json.dumps(_migrer_nom_complet_reel_si_present(element))
        )
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


def libelle_employe(
    employe_id: str,
    coordonnees_par_employe_id: dict[str, FicheCoordonnees],
) -> str:
    """Formate le libellé d'affichage d'un employé — ``"Prénom Nom (courriel)"``.

    Extraite de l'ancienne closure ``_libelle_employe`` de
    ``fiche_employe_detaillee.py`` (Req 2.1, 2.2), désormais publique et
    partagée avec le Formulaire_Paie (Req 1.4) — comportement strictement
    identique, seule la duplication est éliminée.

    Repli explicite, dans l'ordre :

    1. Aucune ``FicheCoordonnees`` pour ``employe_id`` → retourne
       ``employe_id`` tel quel (identifiant technique brut).
    2. ``FicheCoordonnees`` présente mais ``prenom``/``nom`` tous deux
       absents ou vides une fois assemblés → retourne ``employe_id``.
    3. ``prenom``/``nom`` disponibles, ``courriel`` absent → retourne
       ``"Prénom Nom"`` (sans parenthèses).
    4. ``prenom``/``nom`` et ``courriel`` disponibles → retourne
       ``"Prénom Nom (courriel)"``.

    Fonction pure — aucune E/S, aucun import ``streamlit`` (cohérent avec
    le reste de ce module, Req 2.3). ``coordonnees_par_employe_id`` est
    fourni par l'appelant (résultat d'un seul appel groupé à
    ``lister_coordonnees()``, jamais un appel ``lire_coordonnees`` par
    option de sélecteur — même optimisation que le code existant de
    ``fiche_employe_detaillee.py``, Req 1.5).
    """
    fiche = coordonnees_par_employe_id.get(employe_id)
    if fiche is None:
        return employe_id
    nom_complet = " ".join(
        partie for partie in (fiche.prenom, fiche.nom) if partie
    ).strip()
    if not nom_complet:
        return employe_id
    if fiche.courriel:
        return f"{nom_complet} ({fiche.courriel})"
    return nom_complet
