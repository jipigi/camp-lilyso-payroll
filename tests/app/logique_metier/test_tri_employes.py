"""Property tests et tests d'exemple pour `app/logique_metier/tri_employes.py`.

Spec de référence : ``tableau-de-bord-periode-globale`` — tâche 4.2.
Design de référence : ``design.md`` §Components et Interfaces §3
(`tri_employes.py`) ; §Correctness Properties, Property 5.

Ce fichier porte le property test de la Property 5 (tri par Prénom Nom,
insensible casse/accents, départagé par id) de
`trier_employes_pour_affichage`.

Règle 04 (données sensibles) : les stratégies réutilisées
(`st_employee_valide`, `st_fiche_coordonnees_valide`,
`tests/app/strategies.py`) ne produisent que des identifiants et
coordonnées fictives (`EMPnnn`, préfixes/domaines réservés aux
exemples) — aucune donnée personnelle réelle.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.logique_metier.annuaire_coordonnees import FicheCoordonnees
from app.logique_metier.tri_employes import (
    cle_tri_employe,
    normaliser_pour_tri,
    trier_employes_pour_affichage,
)
from models.employee import Employee
from models.enums import Juridiction
from tests.app.strategies import st_employee_valide, st_fiche_coordonnees_valide


def _construire_employe(employe_id: str, nom_affichage: str) -> Employee:
    """`Employee` valide minimal pour un test d'exemple (Req 04 — id/nom
    fictifs, jamais de donnée personnelle réelle).

    Tous les champs hors `id`/`nom_affichage` sont fixés à des valeurs
    passe-partout dans le périmètre Camp LilySO (province QC, taux de
    vacances 4 %) — seuls `id` et `nom_affichage` varient d'un appel à
    l'autre, ce qui est le seul degré de liberté nécessaire aux tests de
    cas limites de tri ci-dessous.
    """
    return Employee(
        id=employe_id,
        nom_affichage=nom_affichage,
        date_naissance=date(2000, 1, 1),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Monitrice",
        taux_horaire_base=Decimal("20.00"),
        date_embauche=date(2024, 6, 1),
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("0.00"),
        montant_total_TD1=Decimal("0.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec les autres fichiers de
# la suite — ``deadline=None``, mêmes suppressions de health check). Le
# nombre d'exemples est piloté par le profil Hypothesis actif (voir
# tests/conftest.py : dev=15 par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@st.composite
def _st_employes_uniques(
    draw: st.DrawFn, max_size: int = 8
) -> tuple[Employee, ...]:
    """0 à `max_size` `Employee` valides, uniques par `id`.

    Réutilisation directe de `st_employee_valide` (`tests/app/
    strategies.py`, tâche 1.1 de la spec `interface-streamlit`) —
    ``unique_by=lambda e: e.id`` garantit qu'aucun doublon d'`id` n'est
    produit au sein d'un même tuple, condition nécessaire pour que le
    départage par `Employee.id` de la Property 5 soit exercé sans
    ambiguïté (deux employés strictement identiques par `id` ne
    pourraient pas être distingués par le test de référence).
    """
    return tuple(
        draw(
            st.lists(
                st_employee_valide(),
                min_size=0,
                max_size=max_size,
                unique_by=lambda e: e.id,
            )
        )
    )


@st.composite
def _st_fiches_partielles(
    draw: st.DrawFn, employes: tuple[Employee, ...]
) -> dict[str, FicheCoordonnees]:
    """Dictionnaire `{employe_id: FicheCoordonnees}` ne couvrant qu'un
    sous-ensemble arbitraire de ``employes`` (Property 5 — « certains
    employés sans fiche »).

    Pour chaque `Employee` de ``employes``, un booléen tiré
    indépendamment décide si une `FicheCoordonnees` (`st_fiche_
    coordonnees_valide`, réutilisation directe sans duplication) lui est
    associée — la `FicheCoordonnees.employe_id` générée est **remplacée**
    par l'`id` réel de l'employé (`employe.id`) pour que le dictionnaire
    reste cohérent avec la clé utilisée par `trier_employes_pour_
    affichage` (`fiches.get(employe.id)`), indépendamment de l'`EMPnnn`
    fictif tiré par la stratégie sous-jacente.
    """
    fiches: dict[str, FicheCoordonnees] = {}
    for employe in employes:
        a_une_fiche = draw(st.booleans())
        if a_une_fiche:
            fiche = draw(st_fiche_coordonnees_valide())
            fiches[employe.id] = fiche.model_copy(update={"employe_id": employe.id})
    return fiches


@st.composite
def _st_employes_et_fiches_partielles(
    draw: st.DrawFn,
) -> tuple[tuple[Employee, ...], dict[str, FicheCoordonnees]]:
    """Compose `_st_employes_uniques` et `_st_fiches_partielles` (Property 5)."""
    employes = draw(_st_employes_uniques())
    fiches = draw(_st_fiches_partielles(employes))
    return employes, fiches


# ---------------------------------------------------------------------------
# Property 5 — Tri par Prénom Nom, insensible casse/accents, départagé
# par id
# ---------------------------------------------------------------------------
#
# Feature: tableau-de-bord-periode-globale, Property 5: Tri par Prénom Nom, insensible casse/accents, départagé par id
#
# *Pour tout* tuple d'employés et *tout* dictionnaire partiel de
# `FicheCoordonnees` associées (certains employés sans fiche), le
# résultat de `trier_employes_pour_affichage` est trié par ordre
# croissant de `normaliser_pour_tri(cle_tri_employe(...))`, et pour
# toute paire d'employés dont cette clé normalisée est identique,
# l'ordre relatif suit `Employee.id` croissant.
#
# _Requirements: 4.1, 4.2, 4.3_
# _Design: §Components et Interfaces §3 ; §Correctness Properties 5_


class TestTrierEmployesPourAffichage:
    """Property 5 — tri par Prénom Nom, insensible casse/accents,
    départagé par id."""

    # Feature: tableau-de-bord-periode-globale, Property 5: Tri par Prénom Nom, insensible casse/accents, départagé par id
    @pytest.mark.property
    @given(donnees=_st_employes_et_fiches_partielles())
    @settings_large_input
    def test_trie_par_cle_normalisee_croissante_departage_par_id(
        self,
        donnees: tuple[tuple[Employee, ...], dict[str, FicheCoordonnees]],
    ) -> None:
        """Property 5 (Req 4.1, 4.2, 4.3).

        Compare `trier_employes_pour_affichage(employes, fiches)` à un
        tri de référence indépendant, calculé sur la même clé
        (`normaliser_pour_tri(cle_tri_employe(employe, fiches.get(employe.id)))`,
        `employe.id`) — les deux tris doivent produire exactement la même
        séquence d'employés. Vérifie ensuite explicitement, pour chaque
        paire consécutive du résultat, que la clé normalisée est
        non-décroissante, et que deux employés consécutifs de clé
        normalisée strictement identique apparaissent par `id` croissant.
        """
        employes, fiches = donnees

        resultat = trier_employes_pour_affichage(employes, fiches)

        # Même ensemble d'employés, aucune perte ni duplication.
        assert set(e.id for e in resultat) == set(e.id for e in employes), (
            "`trier_employes_pour_affichage` ne doit ni perdre ni "
            "dupliquer d'employé ; attendu le même ensemble d'`id` que "
            f"l'entrée, obtenu {[e.id for e in resultat]!r} pour une "
            f"entrée {[e.id for e in employes]!r}."
        )
        assert len(resultat) == len(employes), (
            "`trier_employes_pour_affichage` doit retourner un tuple de "
            f"même longueur que l'entrée ; attendu {len(employes)}, "
            f"obtenu {len(resultat)}."
        )

        # Tri de référence indépendant, sur la même clé documentée par le
        # design (§Components et Interfaces §3).
        resultat_attendu = tuple(
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
        assert resultat == resultat_attendu, (
            "`trier_employes_pour_affichage` doit produire exactement le "
            "même ordre qu'un tri de référence par "
            "`(normaliser_pour_tri(cle_tri_employe(...)), employe.id)` "
            f"croissant ; attendu {[e.id for e in resultat_attendu]!r}, "
            f"obtenu {[e.id for e in resultat]!r}."
        )

        # Ordre croissant des clés normalisées, paire par paire.
        cles_normalisees = [
            normaliser_pour_tri(cle_tri_employe(employe, fiches.get(employe.id)))
            for employe in resultat
        ]
        for cle_precedente, cle_suivante in zip(cles_normalisees, cles_normalisees[1:]):
            assert cle_precedente <= cle_suivante, (
                "les clés normalisées consécutives du résultat doivent "
                f"être non-décroissantes ; obtenu {cle_precedente!r} puis "
                f"{cle_suivante!r} dans {cles_normalisees!r}."
            )

        # Départage par `id` croissant entre employés de clé normalisée
        # strictement identique.
        for employe_precedent, employe_suivant in zip(resultat, resultat[1:]):
            cle_precedente = normaliser_pour_tri(
                cle_tri_employe(employe_precedent, fiches.get(employe_precedent.id))
            )
            cle_suivante = normaliser_pour_tri(
                cle_tri_employe(employe_suivant, fiches.get(employe_suivant.id))
            )
            if cle_precedente == cle_suivante:
                assert employe_precedent.id <= employe_suivant.id, (
                    "deux employés de clé normalisée identique doivent "
                    f"être départagés par `Employee.id` croissant ; "
                    f"obtenu {employe_precedent.id!r} avant "
                    f"{employe_suivant.id!r} pour une clé commune "
                    f"{cle_precedente!r}."
                )


# ---------------------------------------------------------------------------
# Tests unitaires des cas limites de tri (tâche 4.3)
# ---------------------------------------------------------------------------
#
# _Requirements: 4.2, 4.3_
#
# Exemples concrets (pas Hypothesis) illustrant les deux cas limites
# explicitement demandés par la tâche : le départage par `id` lorsque la
# clé normalisée est strictement identique, et l'équivalence
# casse/accents de `normaliser_pour_tri` (« Éloïse » vs « eloise »).


class TestCasLimitesTri:
    """Cas limites de tri : départage par `id`, équivalence casse/accents."""

    def test_departage_par_id_croissant_quand_cle_normalisee_identique(self) -> None:
        """Deux employés de même clé de tri normalisée sont départagés
        par `id` croissant (Req 4.2).

        Deux `Employee` sans `FicheCoordonnees` associée, dont le
        `nom_affichage` est exactement identique — la clé normalisée est
        donc rigoureusement la même pour les deux. Seul l'`id` diffère
        (`"EMP002"` vs `"EMP001"`), volontairement fourni ici dans
        l'ordre inverse de l'ordre attendu pour vérifier que le tri ne
        se contente pas de préserver l'ordre d'entrée.
        """
        employe_b = _construire_employe("EMP002", "Camille Tremblay")
        employe_a = _construire_employe("EMP001", "Camille Tremblay")

        resultat = trier_employes_pour_affichage((employe_b, employe_a), {})

        assert [e.id for e in resultat] == ["EMP001", "EMP002"], (
            "deux employés de clé de tri normalisée strictement "
            "identique doivent apparaître par `id` croissant ; obtenu "
            f"{[e.id for e in resultat]!r}."
        )

    def test_accents_et_casse_mixte_sont_equivalents_pour_le_tri(self) -> None:
        """« Éloïse » et « eloise » produisent la même clé normalisée et
        sont donc départagés par `id` (Req 4.3).

        Vérifie d'abord explicitement l'équivalence de
        `normaliser_pour_tri` sur ces deux graphies (accents + casse
        mixte contre minuscules sans accent), puis que
        `trier_employes_pour_affichage` en tient compte : les deux
        employés apparaissent dans l'ordre de leur `id` croissant,
        malgré une graphie de surface différente et un `id` fourni dans
        l'ordre inverse.
        """
        assert normaliser_pour_tri("Éloïse") == normaliser_pour_tri("eloise"), (
            "« Éloïse » et « eloise » doivent produire la même clé "
            "normalisée (accents et casse ignorés) ; obtenu "
            f"{normaliser_pour_tri('Éloïse')!r} et "
            f"{normaliser_pour_tri('eloise')!r}."
        )

        employe_majuscule_accentue = _construire_employe("EMP002", "Éloïse")
        employe_minuscule_sans_accent = _construire_employe("EMP001", "eloise")

        resultat = trier_employes_pour_affichage(
            (employe_majuscule_accentue, employe_minuscule_sans_accent), {}
        )

        assert [e.id for e in resultat] == ["EMP001", "EMP002"], (
            "« Éloïse » et « eloise » étant équivalents pour le tri, "
            "les deux employés doivent être départagés par `id` "
            f"croissant ; obtenu {[e.id for e in resultat]!r}."
        )
