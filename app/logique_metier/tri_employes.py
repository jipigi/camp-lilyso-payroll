"""Tri d'affichage des employés du Tableau_De_Bord — module mono-responsabilité.

Spec de référence : ``tableau-de-bord-periode-globale`` — tâche 4.1.
Design de référence : ``design.md`` §Architecture décision n° 6 ;
§Components et Interfaces §3 (`tri_employes.py`) ; §Correctness
Properties, Property 5.

Ce module porte le tri par Prénom Nom du tableau des employés
(Requirement 4) :

- :func:`cle_tri_employe` — clé de tri brute d'une ligne, combinant un
  `Employee` et sa `FicheCoordonnees | None` (Req 4.1, 4.2) ;
- :func:`normaliser_pour_tri` — forme canonique insensible à la casse
  et aux accents (Req 4.3) ;
- :func:`trier_employes_pour_affichage` — ordre final du tableau
  (Req 4.1-4.3).

Décision n° 6 (design) : plutôt que de coupler `annuaire_employes.py`
(qui ne connaît aujourd'hui que `Employee`) à `FicheCoordonnees`, ou
d'alourdir `annuaire_coordonnees.py` (dédié au cycle CRUD des
coordonnées), cette fonctionnalité introduit ce nouveau module dédié à
une seule responsabilité — le tri d'affichage — cohérent avec le
découpage déjà en place (`bilan_fiscal.py`, `dernieres_paies.py`,
`erreurs.py` sont chacun mono-responsabilité). Ce module importe
`Employee` et `FicheCoordonnees` (import autorisé, sens unique) mais
n'est importé par aucun des deux modules CRUD en retour.

Règle 04 (données sensibles) : aucun exemple de ce module ne porte de
donnée personnelle réelle — tout identifiant illustratif suit la
convention `EMP001`/« Employé Test QC001 ».
"""

from __future__ import annotations

import unicodedata

from app.logique_metier.annuaire_coordonnees import FicheCoordonnees
from models.employee import Employee


def cle_tri_employe(
    employe: Employee, fiche: FicheCoordonnees | None
) -> str:
    """Clé de tri brute d'une ligne du tableau des employés (Req 4.1, 4.2).

    Si ``fiche`` n'est pas `None` : `f"{fiche.prenom or ''} {fiche.nom or
    ''}"`. Sinon : `employe.nom_affichage`. Fonction pure — aucune
    normalisation appliquée ici (voir `normaliser_pour_tri`).
    """
    if fiche is not None:
        return f"{fiche.prenom or ''} {fiche.nom or ''}"
    return employe.nom_affichage


def normaliser_pour_tri(chaine: str) -> str:
    """Forme canonique insensible à la casse et aux accents (Req 4.3).

    Décomposition Unicode NFKD, suppression des marques de combinaison
    (accents, cédille), puis `casefold()` — même technique que
    `models._validators._normaliser_pour_recherche`, sans la
    suppression de la ponctuation/espaces (celle-ci doit rester
    significative pour l'ordre alphabétique d'un nom complet).
    """
    nfkd = unicodedata.normalize("NFKD", chaine)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sans_accents.casefold()


def trier_employes_pour_affichage(
    employes: tuple[Employee, ...],
    fiches: dict[str, FicheCoordonnees],
) -> tuple[Employee, ...]:
    """Ordre d'affichage du tableau des employés (Req 4.1-4.3).

    Trie ``employes`` par `normaliser_pour_tri(cle_tri_employe(employe,
    fiches.get(employe.id)))` croissant, `employe.id` croissant comme
    critère de départage. Fonction pure — ``fiches`` est un dict déjà
    construit par l'appelant (un appel `lire_coordonnees` par employé,
    dans `tableau_de_bord.py`), jamais lu depuis le disque ici.
    """
    return tuple(
        sorted(
            employes,
            key=lambda employe: (
                normaliser_pour_tri(
                    cle_tri_employe(employe, fiches.get(employe.id))
                ),
                employe.id,
            ),
        )
    )
