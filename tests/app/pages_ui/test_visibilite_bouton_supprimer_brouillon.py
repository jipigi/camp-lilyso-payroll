"""Test de propriété — visibilité conditionnelle du bouton « Supprimer le
brouillon » (Formulaire_Paie).

Spec de référence : ``formulaire-paie-suppression-et-ux`` — tâche 7.3.
Design de référence : ``design.md`` §Components et Interfaces #5
(bouton « Supprimer le brouillon », `_section_nouvelle_paie`) ;
§Correctness Properties Property 2 (« le bouton est affiché si et
seulement si le statut de la paie chargée est BROUILLON »,
``Validates: Requirements 3.1, 3.2``).

**Property 2: Visibilité conditionnelle du bouton « Supprimer le
brouillon »**

For all `PayrollResult` chargés dans le Formulaire_Paie, le bouton
« Supprimer le brouillon » est affiché si et seulement si le statut de
la paie chargée est `BROUILLON`.

**Validates: Requirements 3.1, 3.2**

Exercer directement `_section_nouvelle_paie` de bout en bout pour cette
propriété nécessiterait de mocker l'intégralité de la chaîne de widgets
Streamlit (`st.selectbox`, `st.date_input`, `st.text_input`, `st.columns`,
...) — un harnais disproportionné pour vérifier une seule expression
booléenne, et qui reste couplé à des détails d'implémentation sans
rapport avec cette propriété (mêmes limites déjà documentées par
``tests/app/pages_ui/test_formulaire_paie.py``, qui mocke `st`
directement plutôt que d'utiliser `streamlit.testing.v1.AppTest`).

La condition d'affichage du bouton a donc été extraite en une fonction
pure et testable, `_afficher_bouton_supprimer_brouillon(
id_paie_brouillon_precharge, paie_brouillon)` — comportement strictement
identique à l'expression en ligne précédemment inlinée dans
`_section_nouvelle_paie` (aucune régression de comportement, voir
tâches 7.1/7.2 déjà complétées). Ce test de propriété exerce cette
fonction pour toute combinaison de statut de paie et de présence/absence
de l'`id_paie` de pré-remplissage, et couvre en complément les deux tests
d'exemple triviaux (`id_paie_brouillon_precharge` absent,
`paie_brouillon` absent — cas défensif).

Règle 04 : les `PayrollResult` générés par `st_payroll_result_arbitraire`
portent exclusivement des identifiants fictifs `EMPnnn`.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.pages_ui.formulaire_paie import _afficher_bouton_supprimer_brouillon
from models.enums import StatutDePaie
from models.payroll_result import PayrollResult
from tests.app.strategies import st_payroll_result_arbitraire

_settings_property = settings(
    max_examples=100, suppress_health_check=[HealthCheck.too_slow]
)


class TestVisibiliteBoutonSupprimerBrouillon:
    """Property 2 — visibilité conditionnelle du bouton « Supprimer le
    brouillon »."""

    # Feature: formulaire-paie-suppression-et-ux, Property 2: Visibilité conditionnelle du bouton « Supprimer le brouillon »
    @pytest.mark.property
    @given(
        paie_brouillon=st_payroll_result_arbitraire(
            statut=st.sampled_from(list(StatutDePaie))
        )
    )
    @_settings_property
    def test_bouton_affiche_si_et_seulement_si_statut_brouillon(
        self, paie_brouillon: PayrollResult
    ) -> None:
        """Property 2 (Req 3.1, 3.2).

        Pour tout `PayrollResult` chargé dans le Formulaire_Paie (avec un
        `id_paie_brouillon_precharge` toujours renseigné, cas normal du
        pré-remplissage — voir `_section_nouvelle_paie`), le bouton
        « Supprimer le brouillon » est affiché si et seulement si le
        statut de cette paie est `BROUILLON`."""
        affiche = _afficher_bouton_supprimer_brouillon(
            paie_brouillon.id_paie, paie_brouillon
        )

        assert affiche == (paie_brouillon.statut == StatutDePaie.BROUILLON)

    def test_exemple_id_paie_brouillon_precharge_absent_naffiche_jamais_le_bouton(
        self,
    ) -> None:
        """Cas défensif — aucun `id_paie` de brouillon transmis (flux
        normal de nouvelle paie, sans pré-remplissage) : le bouton n'est
        jamais affiché, même si un `paie_brouillon` était par erreur
        renseigné (Req 3.2)."""
        assert (
            _afficher_bouton_supprimer_brouillon(None, None) is False
        )
        assert _afficher_bouton_supprimer_brouillon("", None) is False

    def test_exemple_paie_brouillon_absente_naffiche_jamais_le_bouton(self) -> None:
        """Cas défensif — la relecture de la paie a échoué
        (`ErreurDomaineAffichable`, `paie_brouillon` resté `None`) alors
        qu'un `id_paie_brouillon_precharge` était bien transmis : le
        bouton n'est jamais affiché (Req 3.2)."""
        assert (
            _afficher_bouton_supprimer_brouillon("PAIE-EMP001-2026-001-v1", None)
            is False
        )
