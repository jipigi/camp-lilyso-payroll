"""Tests d'exemple des énumérations fermées du domaine (``models/enums.py``).

Spec de référence : ``moteur-paie-contrats`` — tâche 2.1.
Requirements couverts (voir ``.kiro/specs/moteur-paie-contrats/requirements.md``) :

- Requirement 5.1 — ``CalculationTrace.mode_arrondissement`` ∈ ``ModeArrondissement``
  (``ROUND_HALF_UP``, ``ROUND_HALF_EVEN``, ``ROUND_DOWN``, ``ROUND_UP``) et
  ``CalculationTrace.juridiction`` ∈ ``Juridiction``.
- Requirement 6.1 — ``PayrollResult.statut`` ∈ ``StatutDePaie``
  (``brouillon``, ``emise``, ``annulee``, ``remplace_par``).
- Requirement 9.1 — ``load_parameters(annee, juridiction)`` avec ``Juridiction``
  à deux valeurs exactement : ``quebec`` et ``canada``.

Le task 2.1 vérifie également ``FrequencePaie`` (implicitement lié aux
requirements 2.6, 3.9 et 11.2 : périmètre Camp LilySO restreint à la fréquence
``aux_deux_semaines``).

Discipline TDD (règle 06) : ce module de tests est écrit **avant** l'existence
de ``models/enums.py``. Les tests DOIVENT échouer à la collection (``ImportError``)
tant que la tâche 2.2 n'a pas fourni l'implémentation.
"""

from __future__ import annotations

from enum import StrEnum

import pytest


# ---------------------------------------------------------------------------
# ``Juridiction`` — deux valeurs exactement (Requirement 9.1)
# ---------------------------------------------------------------------------


class TestJuridiction:
    """``Juridiction`` expose exactement ``quebec`` et ``canada``."""

    def test_valeur_quebec_est_la_chaine_quebec(self) -> None:
        from models.enums import Juridiction

        assert Juridiction.QUEBEC == "quebec"
        assert Juridiction.QUEBEC.value == "quebec"

    def test_valeur_canada_est_la_chaine_canada(self) -> None:
        from models.enums import Juridiction

        assert Juridiction.CANADA == "canada"
        assert Juridiction.CANADA.value == "canada"

    def test_juridiction_est_une_str_enum(self) -> None:
        """Sérialisable telle quelle en JSON (voir §Data Models du design)."""
        from models.enums import Juridiction

        assert issubclass(Juridiction, StrEnum)
        # Comportement ``StrEnum`` : la valeur est une ``str`` à part entière.
        assert isinstance(Juridiction.QUEBEC, str)

    def test_expose_exactement_deux_membres(self) -> None:
        from models.enums import Juridiction

        assert {membre.value for membre in Juridiction} == {"quebec", "canada"}
        assert len(list(Juridiction)) == 2

    def test_toute_autre_valeur_leve_value_error(self) -> None:
        from models.enums import Juridiction

        with pytest.raises(ValueError):
            Juridiction("ontario")
        with pytest.raises(ValueError):
            Juridiction("QUEBEC")  # les valeurs sont en minuscules


# ---------------------------------------------------------------------------
# ``FrequencePaie`` — une seule valeur dans le périmètre courant
# ---------------------------------------------------------------------------


class TestFrequencePaie:
    """``FrequencePaie`` limitée à ``aux_deux_semaines`` (règle 03, Req 2.6)."""

    def test_valeur_aux_deux_semaines(self) -> None:
        from models.enums import FrequencePaie

        assert FrequencePaie.AUX_DEUX_SEMAINES == "aux_deux_semaines"
        assert FrequencePaie.AUX_DEUX_SEMAINES.value == "aux_deux_semaines"

    def test_est_une_str_enum(self) -> None:
        from models.enums import FrequencePaie

        assert issubclass(FrequencePaie, StrEnum)
        assert isinstance(FrequencePaie.AUX_DEUX_SEMAINES, str)

    def test_expose_exactement_un_membre(self) -> None:
        from models.enums import FrequencePaie

        assert {membre.value for membre in FrequencePaie} == {"aux_deux_semaines"}
        assert len(list(FrequencePaie)) == 1

    def test_hebdomadaire_leve_value_error(self) -> None:
        """La fréquence hebdomadaire est hors matrice Camp LilySO (règle 03)."""
        from models.enums import FrequencePaie

        with pytest.raises(ValueError):
            FrequencePaie("hebdomadaire")

    @pytest.mark.parametrize(
        "valeur_hors_matrice",
        ["mensuelle", "bimensuelle", "aux_2_semaines", "AUX_DEUX_SEMAINES", ""],
    )
    def test_toute_autre_valeur_leve_value_error(
        self, valeur_hors_matrice: str
    ) -> None:
        from models.enums import FrequencePaie

        with pytest.raises(ValueError):
            FrequencePaie(valeur_hors_matrice)


# ---------------------------------------------------------------------------
# ``StatutDePaie`` — quatre valeurs exactement (Requirement 6.1)
# ---------------------------------------------------------------------------


class TestStatutDePaie:
    """``StatutDePaie`` supporte l'immuabilité et l'annulation-remplacement."""

    def test_valeurs_individuelles(self) -> None:
        from models.enums import StatutDePaie

        assert StatutDePaie.BROUILLON == "brouillon"
        assert StatutDePaie.EMISE == "emise"
        assert StatutDePaie.ANNULEE == "annulee"
        assert StatutDePaie.REMPLACE_PAR == "remplace_par"

    def test_est_une_str_enum(self) -> None:
        from models.enums import StatutDePaie

        assert issubclass(StatutDePaie, StrEnum)
        assert isinstance(StatutDePaie.BROUILLON, str)

    def test_expose_exactement_quatre_membres(self) -> None:
        from models.enums import StatutDePaie

        valeurs_attendues = {"brouillon", "emise", "annulee", "remplace_par"}
        assert {membre.value for membre in StatutDePaie} == valeurs_attendues
        assert len(list(StatutDePaie)) == 4

    def test_toute_autre_valeur_leve_value_error(self) -> None:
        from models.enums import StatutDePaie

        with pytest.raises(ValueError):
            StatutDePaie("archive")
        with pytest.raises(ValueError):
            StatutDePaie("BROUILLON")


# ---------------------------------------------------------------------------
# ``ModeArrondissement`` — quatre modes exactement (Requirement 5.1)
# ---------------------------------------------------------------------------


class TestModeArrondissement:
    """Miroir strict des modes ``decimal`` cités par TP-1015.F et T4127."""

    def test_valeurs_individuelles(self) -> None:
        from models.enums import ModeArrondissement

        assert ModeArrondissement.ROUND_HALF_UP == "ROUND_HALF_UP"
        assert ModeArrondissement.ROUND_HALF_EVEN == "ROUND_HALF_EVEN"
        assert ModeArrondissement.ROUND_DOWN == "ROUND_DOWN"
        assert ModeArrondissement.ROUND_UP == "ROUND_UP"

    def test_est_une_str_enum(self) -> None:
        from models.enums import ModeArrondissement

        assert issubclass(ModeArrondissement, StrEnum)
        assert isinstance(ModeArrondissement.ROUND_HALF_UP, str)

    def test_expose_exactement_quatre_membres(self) -> None:
        from models.enums import ModeArrondissement

        valeurs_attendues = {
            "ROUND_HALF_UP",
            "ROUND_HALF_EVEN",
            "ROUND_DOWN",
            "ROUND_UP",
        }
        assert {membre.value for membre in ModeArrondissement} == valeurs_attendues
        assert len(list(ModeArrondissement)) == 4

    def test_toute_autre_valeur_leve_value_error(self) -> None:
        from models.enums import ModeArrondissement

        with pytest.raises(ValueError):
            ModeArrondissement("ROUND_CEILING")
        with pytest.raises(ValueError):
            ModeArrondissement("round_half_up")  # les valeurs sont en majuscules

    def test_valeurs_correspondent_aux_constantes_decimal(self) -> None:
        """Les chaînes DOIVENT correspondre aux constantes du module ``decimal``.

        Cela garantit qu'un ``ModeArrondissement`` est utilisable directement
        comme argument ``rounding`` de ``Decimal.quantize`` (voir Req 5.1).
        """
        import decimal

        from models.enums import ModeArrondissement

        assert ModeArrondissement.ROUND_HALF_UP.value == decimal.ROUND_HALF_UP
        assert ModeArrondissement.ROUND_HALF_EVEN.value == decimal.ROUND_HALF_EVEN
        assert ModeArrondissement.ROUND_DOWN.value == decimal.ROUND_DOWN
        assert ModeArrondissement.ROUND_UP.value == decimal.ROUND_UP
