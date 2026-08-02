"""Tests d'exemple pour ``models/exceptions.py``.

Tâche 3.1 de la spec ``moteur-paie-contrats`` — tests **écrits avant** le code
(règle 06, TDD). Tant que la tâche 3.2 n'a pas créé le module
``models/exceptions.py``, ces tests échouent volontairement (l'import échoue
au chargement du fichier), ce qui matérialise la contrainte « pas de code
avant test » exigée par la règle 06.

Portée de la tâche 3.1 (issue directe de ``tasks.md`` §3.1) :

- Vérifier l'existence des trois exceptions du domaine (Req 8.1, 8.4).
- Vérifier la hiérarchie ``PayrollDomainError`` → ``UnsupportedPayrollCase``,
  ``MissingParameterError`` (Req 8.1, 8.4).
- Vérifier la disjonction stricte vis-à-vis de ``pydantic.ValidationError``
  (Req 8.7) : aucune exception du domaine n'est une sous-classe de
  ``pydantic.ValidationError``, afin qu'un ``try/except ValidationError`` ne
  masque jamais un refus métier.
- Vérifier qu'un message vide (chaîne vide, chaîne d'espaces, absence de
  message) n'est pas admis à la construction. La contrainte de non-vacuité
  (Req 8.3 et 8.6) est appliquée dès le constructeur pour un fail-fast :
  aucune exception du domaine ne peut être levée sans motif exploitable par
  l'auditeur.

Aucun autre comportement (contenu détaillé du message, référence WebRAS/PDOC,
chemin JSON du paramètre manquant, etc.) n'est vérifié ici : ces contrats
relèvent respectivement des propriétés 12 (liste blanche des sources) et 16
(contrat des messages), testées par les tâches 5.1 et 15.4.
"""

from __future__ import annotations

import pydantic
import pytest

# Import volontairement au niveau module : tant que ``models/exceptions.py``
# n'existe pas (tâche 3.2 non réalisée), la collection pytest de ce fichier
# échoue avec ``ModuleNotFoundError``. C'est le comportement attendu par la
# règle 06 (TDD) — les tests précèdent l'implémentation.
from models.exceptions import (
    MissingParameterError,
    PayrollDomainError,
    UnsupportedPayrollCase,
)


# ---------------------------------------------------------------------------
# Existence des trois exceptions du domaine
# ---------------------------------------------------------------------------


class TestExistence:
    """Req 8.1, 8.4 — les trois exceptions du domaine sont exposées."""

    def test_payroll_domain_error_derive_de_exception(self) -> None:
        # Base du domaine : dérive de la classe standard Python `Exception`,
        # afin d'être capturable par les gestionnaires génériques d'erreurs
        # tout en restant distincte des erreurs de forme Pydantic.
        assert issubclass(PayrollDomainError, Exception)

    def test_unsupported_payroll_case_est_une_classe(self) -> None:
        assert isinstance(UnsupportedPayrollCase, type)

    def test_missing_parameter_error_est_une_classe(self) -> None:
        assert isinstance(MissingParameterError, type)


# ---------------------------------------------------------------------------
# Hiérarchie du domaine
# ---------------------------------------------------------------------------


class TestHierarchie:
    """Req 8.1, 8.4 — ``UnsupportedPayrollCase`` et ``MissingParameterError``
    dérivent toutes deux de ``PayrollDomainError``.
    """

    def test_unsupported_herite_de_payroll_domain_error(self) -> None:
        assert issubclass(UnsupportedPayrollCase, PayrollDomainError)

    def test_missing_herite_de_payroll_domain_error(self) -> None:
        assert issubclass(MissingParameterError, PayrollDomainError)

    def test_unsupported_et_missing_sont_disjointes(self) -> None:
        # Req 8.2 — les deux exceptions restent strictement disjointes dans
        # leurs déclencheurs ; leurs hiérarchies ne doivent pas non plus se
        # superposer, sinon un ``except MissingParameterError`` capturerait
        # aussi les cas hors matrice (et inversement).
        assert not issubclass(UnsupportedPayrollCase, MissingParameterError)
        assert not issubclass(MissingParameterError, UnsupportedPayrollCase)


# ---------------------------------------------------------------------------
# Disjonction stricte vis-à-vis de ``pydantic.ValidationError`` (Req 8.7)
# ---------------------------------------------------------------------------


class TestDisjonctionPydantic:
    """Req 8.7 — aucune exception du domaine n'est une sous-classe de
    ``pydantic.ValidationError``. Un consommateur (application Streamlit,
    tests) peut donc capturer séparément un refus métier
    (``PayrollDomainError``) d'une erreur de forme
    (``pydantic.ValidationError``).
    """

    def test_payroll_domain_error_pas_pydantic_validation_error(self) -> None:
        assert not issubclass(PayrollDomainError, pydantic.ValidationError)

    def test_unsupported_pas_pydantic_validation_error(self) -> None:
        assert not issubclass(UnsupportedPayrollCase, pydantic.ValidationError)

    def test_missing_pas_pydantic_validation_error(self) -> None:
        assert not issubclass(MissingParameterError, pydantic.ValidationError)


# ---------------------------------------------------------------------------
# Non-vacuité du message vérifiée à la construction (tasks.md §3.1)
# ---------------------------------------------------------------------------


class TestMessageNonVideALaConstruction:
    """Task 3.1 & Req 8.3, 8.6 — le message des exceptions du domaine DOIT
    être une chaîne non vide, et cette contrainte est appliquée dès le
    constructeur (fail-fast). Un consommateur ne peut pas lever une
    exception du domaine sans motif exploitable par l'auditeur.

    Convention retenue :

    - Chaîne vide ``""`` → ``ValueError`` (type correct, valeur invalide).
    - Chaîne d'espaces uniquement (ex. ``"   "``, ``"\\t\\n"``) → ``ValueError``
      (un message purement blanc est sémantiquement vide).
    - Aucun argument → ``TypeError`` (paramètre positionnel requis) ou
      ``ValueError`` (validation métier) : les deux sont acceptables ici,
      l'important est que la construction échoue.
    """

    @pytest.mark.parametrize(
        "exc_class",
        [PayrollDomainError, UnsupportedPayrollCase, MissingParameterError],
    )
    def test_rejette_message_chaine_vide(
        self, exc_class: type[PayrollDomainError]
    ) -> None:
        with pytest.raises(ValueError):
            exc_class("")

    @pytest.mark.parametrize(
        "exc_class",
        [PayrollDomainError, UnsupportedPayrollCase, MissingParameterError],
    )
    @pytest.mark.parametrize("message_blanc", ["   ", "\t", "\n", " \t\n "])
    def test_rejette_message_uniquement_espaces(
        self,
        exc_class: type[PayrollDomainError],
        message_blanc: str,
    ) -> None:
        with pytest.raises(ValueError):
            exc_class(message_blanc)

    @pytest.mark.parametrize(
        "exc_class",
        [PayrollDomainError, UnsupportedPayrollCase, MissingParameterError],
    )
    def test_rejette_absence_de_message(
        self, exc_class: type[PayrollDomainError]
    ) -> None:
        # Sans argument, la construction doit échouer, soit parce que le
        # constructeur exige explicitement un paramètre (``TypeError``), soit
        # parce qu'un ``__init__`` métier détecte l'absence de motif
        # (``ValueError``). Les deux comportements respectent la contrainte
        # de non-vacuité.
        with pytest.raises((TypeError, ValueError)):
            exc_class()  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "exc_class",
        [PayrollDomainError, UnsupportedPayrollCase, MissingParameterError],
    )
    def test_accepte_message_valide(
        self, exc_class: type[PayrollDomainError]
    ) -> None:
        # Contre-exemple : un message actionnable est accepté et exposé via
        # ``str(exc)``. Ce test cadenasse la surface positive du constructeur
        # (garantit qu'on n'a pas rendu la classe totalement inutilisable en
        # renforçant la non-vacuité).
        message = "Cas refusé : dimension X. Utiliser WebRAS/PDOC."
        exc = exc_class(message)
        assert str(exc) == message
