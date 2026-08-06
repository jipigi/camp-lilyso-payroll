"""Tests d'exemple pour `app/logique_metier/erreurs.py`.

Spec de référence : ``interface-streamlit`` — tâche 9.1 (squelette du
fichier et tests de disjonction stricte).
Design de référence : ``design.md`` §Components §8 (`erreurs.py` —
`ErreurDomaineAffichable`, `executer_avec_capture`, disjonction stricte
des erreurs, Req 16) et §Error Handling « Disjonction stricte (Req 16) —
mécanisme central ».

Ce fichier porte l'ensemble des tests d'exemple de `erreurs.py`. Il n'y a
pas de property tests pour ce module (la tâche 9 ne comporte qu'une seule
sous-tâche, 9.1, sans suite 9.2/9.3) : le contrat de
`executer_avec_capture` est entièrement verrouillé par des exemples
concrets, un par type intercepté (`UnsupportedPayrollCase`,
`MissingParameterError`, `ValueError`, `KeyError`), un exemple de
non-interception (`TypeError`, Req 16.3) et un exemple de succès (valeur
de retour inchangée).

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/erreurs.py`` n'existe **pas encore** à ce stade
(implémentation prévue à la tâche 19.1). Ce fichier importe donc
localement (au sein de chaque fonction de test, jamais au niveau module)
les symboles du module sous test — `ErreurDomaineAffichable` et
`executer_avec_capture` — afin que la **collecte** pytest de ce fichier
réussisse même tant que le module cible est absent. À l'exécution, chaque
test échoue alors avec ``ModuleNotFoundError`` sur
``app.logique_metier.erreurs`` — c'est le comportement **attendu et
correct** (état rouge intentionnel) tant que la tâche 19.1
(implémentation) n'a pas été réalisée (checkpoint de la tâche 11 du
plan). Même discipline que
``tests/app/logique_metier/test_dernieres_paies.py``.

``models.exceptions.UnsupportedPayrollCase`` et
``models.exceptions.MissingParameterError`` sont déjà livrées et figées
par la spec ``moteur-paie-contrats`` — importées directement ici (pas
d'import différé nécessaire pour celles-là, à la différence des symboles
de `erreurs.py`).

Règle 04 : aucune donnée sensible n'est nécessaire pour ce fichier — les
messages d'exception utilisés dans les exemples sont des chaînes
génériques (`"msg"`, etc.), sans identifiant ni donnée personnelle.
"""

from __future__ import annotations

import pytest

from models.exceptions import MissingParameterError, UnsupportedPayrollCase

# ---------------------------------------------------------------------------
# Tests d'exemple — disjonction stricte des 4 types interceptés (Req 16.1,
# 16.2) et non-interception de tout autre type (Req 16.3).
# ---------------------------------------------------------------------------
#
# _Requirements: 16.1, 16.2, 16.3_
# _Design: §Components §8 ; §Error Handling « Disjonction stricte »_


class TestExecuterAvecCaptureDisjonctionStricte:
    """Disjonction stricte de `executer_avec_capture` (Req 16.1, 16.2, 16.3)."""

    def test_capture_unsupported_payroll_case(self) -> None:
        from app.logique_metier.erreurs import (
            ErreurDomaineAffichable,
            executer_avec_capture,
        )

        def _lever() -> None:
            raise UnsupportedPayrollCase("msg")

        resultat = executer_avec_capture(_lever)

        assert resultat == ErreurDomaineAffichable("UnsupportedPayrollCase", "msg")

    def test_capture_missing_parameter_error(self) -> None:
        from app.logique_metier.erreurs import (
            ErreurDomaineAffichable,
            executer_avec_capture,
        )

        def _lever() -> None:
            raise MissingParameterError("msg")

        resultat = executer_avec_capture(_lever)

        assert resultat == ErreurDomaineAffichable("MissingParameterError", "msg")

    def test_capture_value_error(self) -> None:
        from app.logique_metier.erreurs import (
            ErreurDomaineAffichable,
            executer_avec_capture,
        )

        def _lever() -> None:
            raise ValueError("msg")

        resultat = executer_avec_capture(_lever)

        assert resultat == ErreurDomaineAffichable("ValueError", "msg")

    def test_capture_key_error(self) -> None:
        from app.logique_metier.erreurs import (
            ErreurDomaineAffichable,
            executer_avec_capture,
        )

        def _lever() -> None:
            raise KeyError("msg")

        resultat = executer_avec_capture(_lever)

        # `str(KeyError("msg"))` produit `"'msg'"` (repr de la clé) — le
        # message d'origine est cité intact, non paraphrasé, non tronqué
        # (Req 16.2), quelle que soit sa forme exacte.
        assert resultat == ErreurDomaineAffichable("KeyError", str(KeyError("msg")))

    def test_type_error_nest_pas_interceptee_et_se_propage(self) -> None:
        """Req 16.3 — toute exception hors des 4 types traverse sans interception."""
        from app.logique_metier.erreurs import executer_avec_capture

        def _lever() -> None:
            raise TypeError("msg")

        with pytest.raises(TypeError):
            executer_avec_capture(_lever)

    def test_cas_de_succes_retourne_la_valeur_inchangee(self) -> None:
        from app.logique_metier.erreurs import executer_avec_capture

        resultat = executer_avec_capture(lambda: 42)

        assert resultat == 42
