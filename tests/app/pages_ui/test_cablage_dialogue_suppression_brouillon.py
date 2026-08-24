"""Tests unitaires — câblage du dialogue de confirmation de suppression
du brouillon (`app/pages_ui/formulaire_paie.py`).

Spec de référence : ``formulaire-paie-suppression-et-ux`` — tâche 7.5.
Design de référence : ``design.md`` §Components et Interfaces #5
(``_dialogue_confirmation_suppression_brouillon``, `formulaire_paie.py`).

Ce module vérifie le **câblage** de `_dialogue_confirmation_
suppression_brouillon`, complémentaire aux tests de propriété déjà
écrits (tâches 7.3, 7.4) :

1. Le bouton « Annuler » ferme la popup (`st.rerun()`) sans jamais
   invoquer `supprimer_paie_brouillon` (Req 3.5).
2. Une erreur du registre (`ValueError`/`KeyError`, capturée par
   `executer_avec_capture` sous forme d'`ErreurDomaineAffichable`) est
   affichée via `st.error` sans provoquer de `st.rerun()` (Req 3.6,
   3.7) — la popup reste ouverte, l'opérateur voit le message d'erreur.

`_dialogue_confirmation_suppression_brouillon` est décorée par
`@st.dialog(...)` — l'invoquer directement déclenche l'ouverture réelle
d'une popup Streamlit, qui nécessite un contexte de script en cours
d'exécution (`ScriptRunContext`) absent en test unitaire (même limite
déjà documentée par `tests/app/pages_ui/
test_absence_reference_residuelle_suppression_brouillon.py`). Ces tests
invoquent donc `_dialogue_confirmation_suppression_brouillon.
__wrapped__(id_paie)` — l'attribut standard posé par `functools.wraps`
(utilisé par `st.dialog`), qui expose la fonction décorée sans jamais
passer par le mécanisme d'ouverture de popup.

``streamlit`` (importé sous l'alias ``st`` dans `formulaire_paie.py`)
est mocké via `unittest.mock.patch("app.pages_ui.formulaire_paie.st")`
— même patron que les autres tests de ce dossier.
``st.session_state`` est simulé par un vrai `dict` Python.
`supprimer_paie_brouillon` (importée directement dans l'espace de noms
de `formulaire_paie.py` depuis `payroll_engine.register`) est mockée
pour isoler ce câblage de toute écriture disque réelle.

Règle 04 : l'``id_paie`` utilisé ci-dessous (``PAIE-EMP001-2026-001``)
est fictif, aucune donnée personnelle réelle.
"""

from __future__ import annotations

from unittest.mock import patch

from app.pages_ui.formulaire_paie import (
    _dialogue_confirmation_suppression_brouillon,
)

_ID_PAIE_TEST = "PAIE-EMP001-2026-001"


def _bouton_annuler_seulement(*_args: object, **kwargs: object) -> bool:
    """``st.button(...)`` retourne ``True`` uniquement pour le bouton
    « Annuler » (``key="fp_supprimer_brouillon_annuler"``), ``False``
    pour le bouton « Supprimer le brouillon » — sans quoi un unique
    ``st_mock.button.return_value = True`` ferait retourner ``True``
    pour les deux boutons du dialogue, déclenchant à tort les deux
    branches."""
    return kwargs.get("key") == "fp_supprimer_brouillon_annuler"


def _bouton_confirmer_seulement(*_args: object, **kwargs: object) -> bool:
    """Symétrique de `_bouton_annuler_seulement` — seul le bouton
    « Supprimer le brouillon » (``key="fp_supprimer_brouillon_
    confirmer"``) est cliqué."""
    return kwargs.get("key") == "fp_supprimer_brouillon_confirmer"


class TestBoutonAnnulerFermeLaPopupSansSupprimer:
    """Le bouton « Annuler » ferme la popup sans invoquer
    `supprimer_paie_brouillon` (Req 3.5)."""

    def test_annuler_ferme_la_popup_sans_appeler_supprimer_paie_brouillon(
        self,
    ) -> None:
        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.supprimer_paie_brouillon"
        ) as supprimer_mock:
            st_mock.session_state = {
                "fp_nouvelle_id_paie_precharge": _ID_PAIE_TEST
            }
            st_mock.button.side_effect = _bouton_annuler_seulement
            st_mock.columns.return_value = (
                st_mock.__class__(),
                st_mock.__class__(),
            )

            _dialogue_confirmation_suppression_brouillon.__wrapped__(
                _ID_PAIE_TEST
            )

        supprimer_mock.assert_not_called()
        st_mock.rerun.assert_called_once()
        st_mock.error.assert_not_called()
        # « Annuler » ferme la popup sans jamais retirer la clé de
        # pré-remplissage — le brouillon existe toujours, aucune
        # suppression n'a eu lieu.
        assert (
            st_mock.session_state.get("fp_nouvelle_id_paie_precharge")
            == _ID_PAIE_TEST
        )


class TestErreurRegistreAfficheeSansRerun:
    """Une erreur du registre (`ValueError`/`KeyError`) est affichée via
    `st.error` sans provoquer de `st.rerun()` (Req 3.6, 3.7) — la popup
    reste ouverte."""

    def test_value_error_statut_non_brouillon_affichee_sans_rerun(self) -> None:
        """`supprimer_paie_brouillon` lève `ValueError` (statut courant
        refusé, ex. `EMISE`) : `st.error(...)` est appelé, `st.rerun()`
        n'est jamais appelé (Req 3.6)."""
        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.supprimer_paie_brouillon",
            side_effect=ValueError(
                "statut actuel 'emise' != BROUILLON, suppression refusée"
            ),
        ) as supprimer_mock:
            st_mock.session_state = {
                "fp_nouvelle_id_paie_precharge": _ID_PAIE_TEST
            }
            st_mock.button.side_effect = _bouton_confirmer_seulement
            st_mock.columns.return_value = (
                st_mock.__class__(),
                st_mock.__class__(),
            )

            _dialogue_confirmation_suppression_brouillon.__wrapped__(
                _ID_PAIE_TEST
            )

        supprimer_mock.assert_called_once()
        st_mock.error.assert_called_once()
        st_mock.rerun.assert_not_called()
        # La clé de pré-remplissage n'est jamais retirée en cas d'échec
        # (Req 3.9 ne s'applique qu'au succès) : le brouillon existe
        # toujours.
        assert (
            st_mock.session_state.get("fp_nouvelle_id_paie_precharge")
            == _ID_PAIE_TEST
        )

    def test_key_error_id_paie_absent_affichee_sans_rerun(self) -> None:
        """`supprimer_paie_brouillon` lève `KeyError` (`id_paie` absent
        du Registre) : `st.error(...)` est appelé, `st.rerun()` n'est
        jamais appelé (Req 3.7)."""
        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.supprimer_paie_brouillon",
            side_effect=KeyError(f"paie {_ID_PAIE_TEST!r} introuvable"),
        ) as supprimer_mock:
            st_mock.session_state = {
                "fp_nouvelle_id_paie_precharge": _ID_PAIE_TEST
            }
            st_mock.button.side_effect = _bouton_confirmer_seulement
            st_mock.columns.return_value = (
                st_mock.__class__(),
                st_mock.__class__(),
            )

            _dialogue_confirmation_suppression_brouillon.__wrapped__(
                _ID_PAIE_TEST
            )

        supprimer_mock.assert_called_once()
        st_mock.error.assert_called_once()
        st_mock.rerun.assert_not_called()
        assert (
            st_mock.session_state.get("fp_nouvelle_id_paie_precharge")
            == _ID_PAIE_TEST
        )
