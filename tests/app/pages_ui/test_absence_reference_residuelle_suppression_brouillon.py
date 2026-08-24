"""Test de propriété — absence de référence résiduelle après suppression
d'un brouillon (Formulaire_Paie).

Spec de référence : ``formulaire-paie-suppression-et-ux`` — tâche 7.4.
Design de référence : ``design.md`` §Components et Interfaces #5
(``_dialogue_confirmation_suppression_brouillon``, `formulaire_paie.py`) ;
§Correctness Properties Property 5 (« l'état de session affiché
immédiatement après ne référence plus cet ``id_paie`` dans aucune valeur
pré-remplie du formulaire », ``Validates: Requirements 3.9``).

**Property 5: Absence de référence résiduelle après suppression d'un
brouillon**

For all `id_paie` d'une paie `BROUILLON` supprimée avec succès depuis le
Formulaire_Paie, l'état de session affiché immédiatement après ne
référence plus cet `id_paie` dans aucune valeur pré-remplie du
formulaire.

**Validates: Requirements 3.9**

Exercer `_dialogue_confirmation_suppression_brouillon` nécessite de
contourner le décorateur `st.dialog` — celui-ci exige un contexte
d'exécution Streamlit réel (`ScriptRunContext`) absent en test unitaire
(même limite déjà documentée par les autres tests de ce module, qui
mockent `st` directement plutôt que d'utiliser
`streamlit.testing.v1.AppTest`). `st.dialog` (comme `functools.wraps`)
expose la fonction décorée via l'attribut `__wrapped__` : ce test invoque
donc `_dialogue_confirmation_suppression_brouillon.__wrapped__(id_paie)`
directement — comportement strictement identique au corps de la fonction
telle qu'exécutée par Streamlit lors d'un clic réel, sans jamais passer
par le mécanisme d'ouverture de popup (hors de portée de cette
propriété).

``streamlit`` (importé sous l'alias ``st`` dans ``formulaire_paie.py``)
est mocké via ``unittest.mock.patch("app.pages_ui.formulaire_paie.st")``
— même patron que ``tests/app/pages_ui/test_formulaire_paie.py``.
``st.session_state`` est simulé par un vrai ``dict`` Python contenant
``"fp_nouvelle_id_paie_precharge"`` (la seule clé de pré-remplissage
retirée par la fonction, voir design §Components #5) avant l'appel, afin
de vérifier qu'elle est bien absente après. ``supprimer_paie_brouillon``
(importée directement dans l'espace de noms de ``formulaire_paie.py``
depuis ``payroll_engine.register``) est mockée pour toujours réussir
(``return_value=None``), isolant cette propriété de toute écriture
disque réelle — la suppression physique elle-même est déjà couverte par
la Property 3 (``tests/payroll_engine/test_register.py``).

Règle 04 : les `id_paie` générés par la stratégie Hypothesis ci-dessous
portent exclusivement des identifiants fictifs `EMPnnn`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.pages_ui.formulaire_paie import (
    _dialogue_confirmation_suppression_brouillon,
)

_settings_property = settings(
    max_examples=100, suppress_health_check=[HealthCheck.too_slow]
)


def _bouton_confirmer_seulement(*_args: object, **kwargs: object) -> bool:
    """``st.button(...)`` retourne ``True`` uniquement pour le bouton
    « Supprimer le brouillon » (``key="fp_supprimer_brouillon_confirmer"``),
    ``False`` pour le bouton « Annuler » — sans quoi un unique
    ``st_mock.button.return_value = True`` ferait retourner ``True`` pour
    les deux boutons du dialogue, déclenchant à tort les deux branches
    (`st.rerun()` appelé deux fois)."""
    return kwargs.get("key") == "fp_supprimer_brouillon_confirmer"


def _st_id_paie_brouillon() -> st.SearchStrategy[str]:
    """`id_paie` fictif arbitraire de forme ``PAIE-EMPnnn-<annee>-<v>``
    (règle 04) — seule la forme importe pour cette propriété, jamais son
    interprétation métier (la fonction testée traite `id_paie` comme une
    chaîne opaque transmise à `supprimer_paie_brouillon` puis retirée de
    `st.session_state`)."""
    return st.builds(
        lambda n, annee, v: f"PAIE-EMP{n:03d}-{annee}-{v:03d}",
        st.integers(min_value=1, max_value=999),
        st.integers(min_value=2024, max_value=2028),
        st.integers(min_value=1, max_value=5),
    )


class TestAbsenceReferenceResiduelleApresSuppressionBrouillon:
    """Property 5 — absence de référence résiduelle après suppression
    d'un brouillon (Req 3.9)."""

    # Feature: formulaire-paie-suppression-et-ux, Property 5: Absence de référence résiduelle après suppression d'un brouillon
    @pytest.mark.property
    @given(id_paie=_st_id_paie_brouillon())
    @_settings_property
    def test_session_state_ne_reference_plus_id_paie_supprime(
        self, id_paie: str
    ) -> None:
        """Property 5 (Req 3.9).

        Pour tout `id_paie` d'une paie `BROUILLON` dont la suppression
        réussit (`supprimer_paie_brouillon` ne lève aucune exception),
        `st.session_state` ne contient plus la clé de pré-remplissage
        `"fp_nouvelle_id_paie_precharge"` immédiatement après l'appel à
        `_dialogue_confirmation_suppression_brouillon` — aucune valeur
        pré-remplie du formulaire ne référence donc plus le brouillon
        supprimé."""
        session_state = {
            "fp_nouvelle_id_paie_precharge": id_paie,
            # Clé sans rapport, jamais retirée par cette fonction — sert
            # à vérifier que le retrait est bien ciblé, pas un vidage
            # complet de `st.session_state`.
            "fp_nouvelle_employe_id": "EMP001",
        }

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.supprimer_paie_brouillon",
            return_value=None,
        ) as supprimer_mock:
            st_mock.session_state = session_state
            st_mock.button.side_effect = _bouton_confirmer_seulement
            st_mock.columns.return_value = (
                st_mock.__class__(),
                st_mock.__class__(),
            )

            _dialogue_confirmation_suppression_brouillon.__wrapped__(id_paie)

        supprimer_mock.assert_called_once()
        assert "fp_nouvelle_id_paie_precharge" not in session_state, (
            "aucune valeur pré-remplie du Formulaire_Paie ne doit plus "
            f"référencer l'id_paie supprimé {id_paie!r} (Req 3.9), "
            f"session_state obtenu : {session_state!r}."
        )
        st_mock.rerun.assert_called_once()
        # Clé sans rapport préservée — retrait ciblé, pas un vidage
        # complet de `st.session_state`.
        assert session_state.get("fp_nouvelle_employe_id") == "EMP001"

    def test_exemple_erreur_registre_ne_retire_pas_la_cle_de_prechargement(
        self,
    ) -> None:
        """Cas complémentaire (Req 3.6, 3.7) — si `supprimer_paie_brouillon`
        échoue (`ValueError`/`KeyError`, capturée par
        `executer_avec_capture`), la clé de pré-remplissage n'est jamais
        retirée : l'échec de la suppression physique ne doit jamais
        laisser croire à tort qu'aucune référence résiduelle ne
        subsiste — au contraire, le brouillon existe toujours."""
        id_paie = "PAIE-EMP001-2026-001"
        session_state = {"fp_nouvelle_id_paie_precharge": id_paie}

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.supprimer_paie_brouillon",
            side_effect=ValueError("statut actuel 'emise' != BROUILLON"),
        ):
            st_mock.session_state = session_state
            st_mock.button.side_effect = _bouton_confirmer_seulement
            st_mock.columns.return_value = (
                st_mock.__class__(),
                st_mock.__class__(),
            )

            _dialogue_confirmation_suppression_brouillon.__wrapped__(id_paie)

        st_mock.error.assert_called_once()
        st_mock.rerun.assert_not_called()
        assert session_state.get("fp_nouvelle_id_paie_precharge") == id_paie
