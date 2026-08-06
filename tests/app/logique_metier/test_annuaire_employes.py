"""Property tests et tests d'exemple pour `app/logique_metier/annuaire_employes.py`.

Spec de référence : ``interface-streamlit`` — tâche 3.1 (squelette du
fichier et test de la Property 1).
Design de référence : ``design.md`` §Components §2 (`annuaire_employes.py`
— cycle CRUD) et §Correctness Properties 1, 2.

Ce fichier porte l'ensemble des property tests et tests d'exemple de
l'Annuaire_Employes (`lister_employes`, `enregistrer_employe`,
`lire_employe`). La tâche 3.1 pose le **squelette** : le module docstring,
les imports, et la Property 1 (classe ``TestRoundTripAnnuaireEmployes``).
Les tâches suivantes ajouteront :

- ``TestLireParId`` — Property 2 (tâche 3.2) ;
- ``TestAucunGardeFouDuplique`` — test d'exemple d'absence de garde-fou
  dupliqué (tâche 3.3).

Les **2 propriétés** couvertes par ce fichier de test au total (design.md
§Correctness Properties) :

1. **Property 1 — Round-trip de l'Annuaire_Employes**.
2. **Property 2 — Lecture par `id` — round-trip et absence**.

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/annuaire_employes.py`` n'existe **pas encore** à ce
stade (implémentation prévue à la tâche 13.1). Ce fichier importe donc
localement les fonctions du module sous test (au sein de chaque test)
afin que la **collecte** pytest de ce fichier réussisse même tant que le
module cible est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``app.logique_metier.annuaire_employes`` —
c'est le comportement **attendu et correct** (état rouge intentionnel)
tant que la tâche 13.1 (implémentation) n'a pas été réalisée (checkpoint
de la tâche 11 du plan).

Règle 01 : les `Employee` générés par `st_employee_valide` (tâche 1.1)
portent exclusivement des champs `Decimal` (jamais de `float`) — ce
fichier ne réintroduit aucune conversion `float`.
Règle 04 : chaque test injecte systématiquement un chemin d'annuaire
temporaire via ``st_chemin_json_temporaire`` (tâche 1.1, ``tmp_path``) —
jamais le chemin de production (`chemin_annuaire_employes_production()`)
— et n'utilise que des identifiants fictifs ``EMPnnn`` (via
``st_employee_valide``).
"""

from __future__ import annotations

from typing import Callable
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from models.employee import Employee
from tests.app.strategies import st_chemin_json_temporaire, st_employee_valide

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


# ---------------------------------------------------------------------------
# Property 1 — Round-trip de l'Annuaire_Employes
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 1: Round-trip de l'Annuaire_Employes
#
# *Pour toute* liste de Fiches_Employe valides avec des `id` distincts,
# écrire chacune via `enregistrer_employe` puis appeler `lister_employes`
# retourne exactement l'ensemble des fiches écrites, triées par `id`
# croissant ; pour l'ensemble vide (aucune écriture), `lister_employes`
# retourne un tuple vide sans lever d'exception.
#
# _Requirements: 2.1, 2.2, 2.3_
# _Design: §Components §2 ; §Correctness Properties 1_


class TestRoundTripAnnuaireEmployes:
    """Property 1 — round-trip complet de l'Annuaire_Employes."""

    # Feature: interface-streamlit, Property 1: Round-trip de l'Annuaire_Employes
    @pytest.mark.property
    @given(
        employes=st.lists(
            st_employee_valide(), unique_by=lambda e: e.id, max_size=8
        )
    )
    @settings_large_input
    def test_ecrire_puis_lister_retourne_exactement_lensemble_ecrit_trie_par_id(
        self,
        employes: list[Employee],
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        from app.logique_metier.annuaire_employes import (
            enregistrer_employe,
            lister_employes,
        )

        chemin_annuaire = st_chemin_json_temporaire("employees")

        for employe in employes:
            enregistrer_employe(employe, chemin_annuaire)

        resultat = lister_employes(chemin_annuaire)

        assert resultat == tuple(sorted(employes, key=lambda e: e.id))

    # Feature: interface-streamlit, Property 1: Round-trip de l'Annuaire_Employes
    def test_annuaire_vide_retourne_tuple_vide_sans_exception(
        self,
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        from app.logique_metier.annuaire_employes import lister_employes

        chemin_annuaire = st_chemin_json_temporaire("employees")

        resultat = lister_employes(chemin_annuaire)

        assert resultat == ()


# ---------------------------------------------------------------------------
# Property 2 — Lecture par `id` — round-trip et absence
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 2: Lecture par id — round-trip et absence
#
# *Pour toute* liste de Fiches_Employe écrite via `enregistrer_employe` et
# *pour tout* `id` : si cet `id` est présent dans la liste écrite,
# `lire_employe(id)` retourne exactement la fiche écrite pour cet `id` ;
# si cet `id` est absent, `lire_employe(id)` lève `KeyError` dont le
# message cite l'`id` recherché.
#
# _Requirements: 2.4, 2.5_
# _Design: §Components §2 ; §Correctness Properties 2_


class TestLireParId:
    """Property 2 — lecture unique par `id` : round-trip et absence."""

    # Feature: interface-streamlit, Property 2: Lecture par id — round-trip et absence
    @pytest.mark.property
    @given(
        employes=st.lists(
            st_employee_valide(), unique_by=lambda e: e.id, min_size=1, max_size=8
        ),
        index_cible=st.integers(min_value=0, max_value=7),
    )
    @settings_large_input
    def test_id_present_lire_employe_retourne_la_fiche_ecrite(
        self,
        employes: list[Employee],
        index_cible: int,
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        from app.logique_metier.annuaire_employes import (
            enregistrer_employe,
            lire_employe,
        )

        chemin_annuaire = st_chemin_json_temporaire("employees")

        for employe in employes:
            enregistrer_employe(employe, chemin_annuaire)

        cible = employes[index_cible % len(employes)]

        resultat = lire_employe(cible.id, chemin_annuaire)

        assert resultat == cible

    # Feature: interface-streamlit, Property 2: Lecture par id — round-trip et absence
    @pytest.mark.property
    @given(
        employes=st.lists(st_employee_valide(), unique_by=lambda e: e.id, max_size=8),
        id_absent=st.builds(lambda n: f"EMP{n:03d}", st.integers(min_value=1, max_value=999)),
    )
    @settings_large_input
    def test_id_absent_lire_employe_leve_keyerror_citant_lid(
        self,
        employes: list[Employee],
        id_absent: str,
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        assume(id_absent not in {e.id for e in employes})

        from app.logique_metier.annuaire_employes import (
            enregistrer_employe,
            lire_employe,
        )

        chemin_annuaire = st_chemin_json_temporaire("employees")

        for employe in employes:
            enregistrer_employe(employe, chemin_annuaire)

        with pytest.raises(KeyError) as exc_info:
            lire_employe(id_absent, chemin_annuaire)

        assert id_absent in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test d'exemple — absence de garde-fou dupliqué
# ---------------------------------------------------------------------------
#
# `enregistrer_employe` ne valide rien elle-même — un `Employee` déjà
# construit hors matrice aurait levé `UnsupportedPayrollCase` **à la
# construction** (`Employee(...)`), jamais à l'enregistrement. Vérifié par
# inspection statique (`ast`) : absence de tout `raise UnsupportedPayrollCase`
# dans `annuaire_employes.py` (règle 03 — aucun garde-fou de périmètre
# dupliqué hors du moteur/des modèles).
#
# _Requirements: 2.7_
# _Design: §Components §2_

import ast

#: Racine du dépôt — trois niveaux au-dessus de
#: ``tests/app/logique_metier/test_annuaire_employes.py`` (``logique_metier/``
#: -> ``app/`` -> ``tests/`` -> racine), plus un niveau supplémentaire pour
#: atteindre la racine du dépôt (même convention que
#: ``tests/app/logique_metier/test_annuaire_coordonnees.py::_REPO_ROOT``).
_REPO_ROOT: Path = Path(__file__).parent.parent.parent.parent


def _leve_unsupported_payroll_case(noeud_raise: ast.Raise) -> bool:
    """`True` si ce `ast.Raise` lève `UnsupportedPayrollCase` (par nom).

    Couvre les deux formes syntaxiques possibles :

    - levée avec appel : ``raise UnsupportedPayrollCase("...")`` — le nœud
      d'exception est un ``ast.Call`` dont ``func`` est un ``ast.Name``
      d'id ``"UnsupportedPayrollCase"`` ;
    - levée sans parenthèses (réexception d'une variable/exception déjà
      construite) : ``raise UnsupportedPayrollCase`` seul — le nœud
      d'exception est directement un ``ast.Name`` d'id
      ``"UnsupportedPayrollCase"``.
    """
    exc = noeud_raise.exc

    if exc is None:
        return False

    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
        return exc.func.id == "UnsupportedPayrollCase"

    if isinstance(exc, ast.Name):
        return exc.id == "UnsupportedPayrollCase"

    return False


class TestAucunGardeFouDuplique:
    """Absence de garde-fou de périmètre dupliqué dans `annuaire_employes.py` (Req 2.7)."""

    def test_annuaire_employes_ne_leve_jamais_unsupportedpayrollcase(self) -> None:
        """`annuaire_employes.py` ne contient aucun `raise UnsupportedPayrollCase`.

        Inspection statique (`ast`) du **code source** du fichier — pas un
        import du module — afin que ce test reste collectable et
        significatif avant même que le fichier existe (règle 06). Tant que
        ``app/logique_metier/annuaire_employes.py`` n'existe pas
        (implémentation prévue à la tâche 13.1), ce test est explicitement
        marqué ``skip`` plutôt que d'échouer de façon confuse
        (``FileNotFoundError``).

        Une fois le fichier créé (tâche 13.1), la validation de périmètre
        (matrice Camp LilySO, règle 03) reste exclusivement à la charge de
        la construction de `Employee` (`models/employee.py`) — jamais
        dupliquée dans la couche d'enregistrement/lecture de l'annuaire.
        """
        chemin_module = _REPO_ROOT / "app" / "logique_metier" / "annuaire_employes.py"

        if not chemin_module.exists():
            pytest.skip(
                "app/logique_metier/annuaire_employes.py n'existe pas "
                "encore — tâche 13.1"
            )

        arbre = ast.parse(chemin_module.read_text(encoding="utf-8"))

        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Raise) and _leve_unsupported_payroll_case(noeud):
                pytest.fail(
                    "annuaire_employes.py lève UnsupportedPayrollCase "
                    "(Req 2.7) — enregistrer_employe/lire_employe ne "
                    "doivent jamais dupliquer la validation de périmètre "
                    "déjà effectuée à la construction de Employee."
                )
