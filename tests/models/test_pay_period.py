"""Property tests et tests d'exemple pour ``WeekSegment`` et ``PayPeriod``.

Tâche 7.1 de la spec ``moteur-paie-contrats`` — tests écrits **avant** le
code (règle 06, TDD). Tant que les tâches 7.2 et 7.3 n'ont pas créé
``models/pay_period.py``, la collection pytest de ce fichier échoue avec
``ModuleNotFoundError``. C'est le comportement attendu — les tests
précèdent l'implémentation.

Portée exacte de la tâche 7.1 (``tasks.md`` §7.1) :

- **Property 1 (partiel PayPeriod) : Immuabilité** —
  ``PayPeriod`` et ``WeekSegment`` sont ``frozen=True`` (design §6). Toute
  mutation d'un champ déclaré lève ``ValidationError``.
  **Validates: Requirements 2.8**
- **Property 13 : Contiguïté et couverture des semaines constituantes** —
  Hypothesis génère des ``PayPeriod`` avec 2 ``WeekSegment`` bien alignés
  (acceptés) et mal alignés (refusés).
  **Validates: Requirements 2.4, 2.5**
- **Property 14 : Nombre correct de semaines constituantes** — Hypothesis
  génère des listes de longueur ``n ≠ 2`` et vérifie que l'erreur de
  nombre prévaut sur les vérifications de contiguïté / couverture
  (court-circuit AC4/AC5 du Req 2).
  **Validates: Requirements 2.2**
- **Property 9 (partiel) : Non-négativité et borne supérieure des heures**
  — ``heures_normales`` et ``heures_supplementaires`` ∈ ``[0, 168]``
  (design §6, bornes physiques justifiées par les Normes du travail QC).
  **Validates: Requirements 2.3**
- Test d'exemple : ``frequence != AUX_DEUX_SEMAINES`` lève
  ``UnsupportedPayrollCase`` mentionnant la règle 03 et les outils
  officiels (WebRAS, PDOC).
  Requirements 2.6, 11.2, 11.6.
- Test d'exemple : ``date_fin < date_debut`` sur ``WeekSegment`` lève
  ``ValidationError``.
  Requirements 2.3.
- Test d'exemple : ``nb_periodes_annuelles`` accepté à 26 et à 27, refusé
  à 0 ou négatif (design §6).
  Requirements 2.7 (côté modèle).

Aucune valeur fiscale n'est codée en dur (règle 05) : les heures utilisées
comme sondes (``Decimal("40")`` etc.) sont des sondes de forme et non des
paramètres fiscaux. Aucune donnée personnelle réelle n'est utilisée
(règle 04). Tous les montants et taux manipulés sont des ``Decimal``
construits depuis des chaînes (règle 01).

Contexte design (extrait, ``design.md`` §Components 6 et §Data Models 6) :

- ``WeekSegment`` : Pydantic v2, ``frozen=True``, ``extra="forbid"``.
  Champs ``date_debut: date``, ``date_fin: date``,
  ``heures_normales: Decimal ∈ [0, 168]``,
  ``heures_supplementaires: Decimal ∈ [0, 168]``. Validateur :
  ``date_fin >= date_debut``.
- ``PayPeriod`` : Pydantic v2, ``frozen=True``, ``extra="forbid"``.
  Champs ``numero_periode: int``, ``date_debut: date``, ``date_fin: date``,
  ``date_paiement: date``, ``frequence: FrequencePaie``,
  ``nb_periodes_annuelles: int``, ``annee_fiscale: int``,
  ``semaines: tuple[WeekSegment, ...]``.
  Ordre STRICT des validateurs (Req 2.4 explicite) :

  1. ``_refuser_frequence_hors_matrice`` → ``UnsupportedPayrollCase`` si
     la fréquence n'est pas ``AUX_DEUX_SEMAINES``.
  2. ``_nombre_semaines_correspond_a_frequence`` → ``ValidationError`` si
     ``len(semaines) != 2``.
  3. ``_semaines_contigues_et_couvrantes`` → court-circuité lorsque le
     nombre n'est pas correct (AC4/AC5 du Req 2 : « la vérification NE
     DOIT PAS être évaluée » quand l'AC2 échoue).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

# Discipline règle 06 (TDD) : import module-level. Tant que ``models/pay_period.py``
# n'existe pas (tâches 7.2 et 7.3 non réalisées), la collection pytest de ce
# fichier échoue avec ``ModuleNotFoundError``. C'est exactement l'échec
# attendu — les tests précèdent l'implémentation.
from models.enums import FrequencePaie
from models.exceptions import UnsupportedPayrollCase
from models.pay_period import PayPeriod, WeekSegment


# ---------------------------------------------------------------------------
# Stratégies Hypothesis locales
# ---------------------------------------------------------------------------
#
# Ces stratégies restent LOCALES à ce fichier plutôt que d'être ajoutées à
# ``tests/strategies.py`` : elles portent des invariants spécifiques à
# ``PayPeriod`` (fenêtre de 14 jours contiguë, deux semaines de 7 jours) qui
# ne seront pas nécessairement partagés par les autres modèles du domaine.
# Les stratégies transverses (heures monétaires, dates, cumuls, ...) seront
# consolidées plus tard dans ``tests/strategies.py`` par les tâches
# ultérieures.

# Fenêtre de dates réaliste pour le Camp LilySO : quelques saisons autour de
# l'année cible 2026. La borne supérieure laisse une marge pour
# ``date + timedelta(days=13)`` sans dépasser une date valide.
_DATE_MIN = date(2024, 1, 1)
_DATE_MAX = date(2028, 6, 30)


@st.composite
def _heures_valides(draw: st.DrawFn) -> Decimal:
    """Génère un ``Decimal`` d'heures dans ``[0, 168]`` (design §6)."""
    return draw(
        st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("168"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@st.composite
def _week_segment_valide(
    draw: st.DrawFn, *, date_debut: date | None = None
) -> WeekSegment:
    """Génère un ``WeekSegment`` de 7 jours consécutifs, heures ∈ [0, 168]."""
    if date_debut is None:
        date_debut = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    return WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=draw(_heures_valides()),
        heures_supplementaires=draw(_heures_valides()),
    )


@st.composite
def _pay_period_bien_aligne(draw: st.DrawFn) -> PayPeriod:
    """Génère un ``PayPeriod`` acceptable pour Property 13 :

    - exactement 2 ``WeekSegment`` de 7 jours ;
    - contigus (``w0.date_fin + 1 == w1.date_debut``) ;
    - couvrant exactement ``[date_debut ; date_fin]`` (14 jours au total).
    """
    date_debut = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    w0 = draw(_week_segment_valide(date_debut=date_debut))
    w1 = draw(_week_segment_valide(date_debut=date_debut + timedelta(days=7)))
    return PayPeriod(
        numero_periode=draw(st.integers(min_value=1, max_value=27)),
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=13),
        date_paiement=date_debut + timedelta(days=16),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=draw(st.sampled_from([26, 27])),
        annee_fiscale=draw(st.integers(min_value=2024, max_value=2028)),
        semaines=(w0, w1),
    )


@st.composite
def _pay_period_kwargs_mal_aligne(draw: st.DrawFn) -> dict[str, Any]:
    """Génère les kwargs d'un ``PayPeriod`` dont l'alignement est brisé.

    Chaque ``WeekSegment`` est INDIVIDUELLEMENT valide (``date_fin >=
    date_debut``, heures ∈ ``[0, 168]``). C'est la contiguïté ou la
    couverture au niveau du ``PayPeriod`` qui échoue, ce qui doit
    déclencher un refus (Property 13, Req 2.4 & 2.5).

    Quatre types de désalignement sont générés uniformément :

    - ``"gap"`` : trou d'un jour entre ``w0.date_fin`` et ``w1.date_debut``.
    - ``"overlap"`` : ``w0.date_fin == w1.date_debut`` (chevauchement d'un jour).
    - ``"not_start"`` : ``w0.date_debut != pay_period.date_debut``.
    - ``"not_end"`` : ``w1.date_fin != pay_period.date_fin``.
    """
    date_debut = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_fin = date_debut + timedelta(days=13)
    kind = draw(st.sampled_from(["gap", "overlap", "not_start", "not_end"]))
    heures_n = Decimal("40.00")
    heures_s = Decimal("0.00")

    if kind == "gap":
        # w0 : [j0, j5] (6 jours), w1 : [j7, j13] (7 jours) → j6 non couvert.
        w0 = WeekSegment(
            date_debut=date_debut,
            date_fin=date_debut + timedelta(days=5),
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
        w1 = WeekSegment(
            date_debut=date_debut + timedelta(days=7),
            date_fin=date_fin,
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
    elif kind == "overlap":
        # w0 : [j0, j7] (8 jours), w1 : [j7, j13] → j7 couvert deux fois.
        w0 = WeekSegment(
            date_debut=date_debut,
            date_fin=date_debut + timedelta(days=7),
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
        w1 = WeekSegment(
            date_debut=date_debut + timedelta(days=7),
            date_fin=date_fin,
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
    elif kind == "not_start":
        # w0 commence 1 jour après ``pay_period.date_debut`` → j0 non couvert.
        w0 = WeekSegment(
            date_debut=date_debut + timedelta(days=1),
            date_fin=date_debut + timedelta(days=7),
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
        w1 = WeekSegment(
            date_debut=date_debut + timedelta(days=8),
            date_fin=date_fin,
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
    else:  # kind == "not_end"
        # w1 se termine 1 jour avant ``pay_period.date_fin`` → j13 non couvert.
        w0 = WeekSegment(
            date_debut=date_debut,
            date_fin=date_debut + timedelta(days=6),
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )
        w1 = WeekSegment(
            date_debut=date_debut + timedelta(days=7),
            date_fin=date_fin - timedelta(days=1),
            heures_normales=heures_n,
            heures_supplementaires=heures_s,
        )

    return {
        "numero_periode": 1,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "date_paiement": date_fin + timedelta(days=3),
        "frequence": FrequencePaie.AUX_DEUX_SEMAINES,
        "nb_periodes_annuelles": 26,
        "annee_fiscale": 2026,
        "semaines": (w0, w1),
        "_kind": kind,  # pour diagnostic Hypothesis ; retiré avant la construction
    }


def _week_segment_arbitraire(index: int, base: date) -> WeekSegment:
    """Fabrique un ``WeekSegment`` valide, décalé de ``index`` semaines.

    Utilisé par la stratégie de Property 14 pour générer une liste de
    ``n`` segments individuellement valides mais dont le NOMBRE ne
    correspond pas à la fréquence (``n != 2`` pour ``AUX_DEUX_SEMAINES``).
    """
    return WeekSegment(
        date_debut=base + timedelta(days=index * 7),
        date_fin=base + timedelta(days=index * 7 + 6),
        heures_normales=Decimal("40.00"),
        heures_supplementaires=Decimal("0.00"),
    )


@st.composite
def _liste_semaines_taille_incorrecte(
    draw: st.DrawFn,
) -> tuple[WeekSegment, ...]:
    """Génère une liste de segments valides dont la longueur ``n ∈
    {0, 1, 3, 4, 5, 6}`` — c'est-à-dire toujours différente de 2.

    Chaque segment est individuellement valide : la seule erreur possible
    au niveau du ``PayPeriod`` est le nombre de segments (Property 14).
    """
    n = draw(st.sampled_from([0, 1, 3, 4, 5, 6]))
    base = date(2026, 1, 5)  # un lundi — sans effet fonctionnel ici
    return tuple(_week_segment_arbitraire(i, base) for i in range(n))


# ---------------------------------------------------------------------------
# Motifs textuels pour l'inspection des messages d'exception
# ---------------------------------------------------------------------------

# Pour Property 14 : le message d'erreur doit porter sur le NOMBRE de
# semaines, PAS sur la contiguïté ni la couverture (court-circuit AC4/AC5
# du Req 2). Ces motifs identifient une éventuelle fuite de la vérification
# de contiguïté / couverture. Comparaison insensible à la casse.
_KEYWORDS_CONTIGUITE = re.compile(
    r"(contigu|chevauch|couvr|couvert|overlap|adjacent|gap)",
    re.IGNORECASE,
)


def _normaliser_message(message: str) -> str:
    """Retourne le message en minuscules et sans accents (comparaison robuste)."""
    return (
        unicodedata.normalize("NFKD", message)
        .encode("ASCII", "ignore")
        .decode("ASCII")
        .lower()
    )


def _mentionne_regle_03(message: str) -> bool:
    """Vrai si le message renvoie explicitement à la règle 03."""
    normalized = _normaliser_message(message)
    return bool(re.search(r"(regle|rule)\s*0*3\b", normalized))


def _mentionne_outils_officiels(message: str) -> bool:
    """Vrai si le message cite WebRAS ou PDOC (Req 11.6)."""
    normalized = _normaliser_message(message)
    return ("webras" in normalized) or ("pdoc" in normalized)


def _semaines_valides_pour_pay_period() -> tuple[WeekSegment, WeekSegment]:
    """Deux ``WeekSegment`` contigus couvrant ``[2026-06-01 ; 2026-06-14]``.

    Utilisé par plusieurs tests d'exemple qui veulent isoler un aspect
    autre que la contiguïté / couverture.
    """
    return (
        WeekSegment(
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 7),
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
        ),
        WeekSegment(
            date_debut=date(2026, 6, 8),
            date_fin=date(2026, 6, 14),
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
        ),
    )


# ===========================================================================
# Tests d'exemple — ``WeekSegment``
# ===========================================================================
#
# Ces tests d'exemple cadenassent les invariants de forme du ``WeekSegment``
# indépendamment de Hypothesis : ils fournissent des repères explicites,
# lisibles et parfaitement déterministes, complémentaires des property tests
# ci-dessous.


class TestWeekSegmentExemples:
    """Invariants d'entrée du ``WeekSegment`` (design §6, Req 2.3)."""

    def test_construction_valide_conserve_les_valeurs(self) -> None:
        """Un ``WeekSegment`` bien formé expose ses champs sans transformation."""
        w = WeekSegment(
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 7),
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("2.50"),
        )
        assert w.date_debut == date(2026, 6, 1)
        assert w.date_fin == date(2026, 6, 7)
        assert w.heures_normales == Decimal("40.00")
        assert w.heures_supplementaires == Decimal("2.50")

    def test_date_fin_egale_a_date_debut_est_acceptee(self) -> None:
        """``date_fin >= date_debut`` autorise l'égalité stricte (design §6)."""
        w = WeekSegment(
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 1),
            heures_normales=Decimal("0"),
            heures_supplementaires=Decimal("0"),
        )
        assert w.date_debut == w.date_fin

    def test_date_fin_anterieure_a_date_debut_leve_validation_error(self) -> None:
        """Req 2.3 — ``date_fin < date_debut`` DOIT lever ``ValidationError``."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 8),
                date_fin=date(2026, 6, 1),  # antérieure : invariant violé
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
            )

    @pytest.mark.parametrize(
        "heures_neg",
        [Decimal("-0.01"), Decimal("-1"), Decimal("-40.00"), Decimal("-168.00")],
        ids=["moins_1_cent", "moins_1", "moins_40", "moins_168"],
    )
    def test_heures_normales_negatives_sont_rejetees(
        self, heures_neg: Decimal
    ) -> None:
        """Design §6 — ``heures_normales`` borné inférieurement à 0."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=heures_neg,
                heures_supplementaires=Decimal("0.00"),
            )

    @pytest.mark.parametrize(
        "heures_hors",
        [Decimal("168.01"), Decimal("200.00"), Decimal("500.00"), Decimal("9999.99")],
        ids=["borne_plus_un_cent", "200", "500", "gros"],
    )
    def test_heures_normales_au_dela_de_168_sont_rejetees(
        self, heures_hors: Decimal
    ) -> None:
        """Design §6 — ``heures_normales`` borné supérieurement à 168."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=heures_hors,
                heures_supplementaires=Decimal("0.00"),
            )

    def test_heures_supplementaires_negatives_sont_rejetees(self) -> None:
        """Design §6 — ``heures_supplementaires`` borné inférieurement à 0."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("-0.01"),
            )

    def test_heures_supplementaires_au_dela_de_168_sont_rejetees(self) -> None:
        """Design §6 — ``heures_supplementaires`` borné supérieurement à 168."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("168.01"),
            )

    def test_champ_inconnu_est_rejete(self) -> None:
        """Design §6 — ``extra="forbid"``."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
                heures_pause=Decimal("1"),  # type: ignore[call-arg]
            )


# ===========================================================================
# Property 1 (partiel PayPeriod, WeekSegment) — Immuabilité
# ===========================================================================
# Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
# domaine (partiel — ``PayPeriod`` et ``WeekSegment``). Pour toute
# instance valide, la mutation d'un champ déclaré doit lever une erreur
# de validation Pydantic (``frozen=True``).
#
# **Validates: Requirements 2.8**


@pytest.mark.property
class TestProperty1Immuabilite:
    """Property 1 (partiel) — ``PayPeriod`` et ``WeekSegment`` sont ``frozen``."""

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
    # domaine (composante ``PayPeriod``).
    @given(pp=_pay_period_bien_aligne())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_mutation_de_pay_period_leve_validation_error(
        self, pp: PayPeriod
    ) -> None:
        """Req 2.8 — ``PayPeriod`` immuable après construction."""
        with pytest.raises(ValidationError):
            pp.numero_periode = 99  # type: ignore[misc]

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
    # domaine (composante ``PayPeriod`` — mutation de la tuple ``semaines``).
    @given(pp=_pay_period_bien_aligne())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_mutation_du_champ_semaines_leve_validation_error(
        self, pp: PayPeriod
    ) -> None:
        """Req 2.8 — même le champ agrégé ``semaines`` reste immuable."""
        with pytest.raises(ValidationError):
            pp.semaines = ()  # type: ignore[misc]

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
    # domaine (composante ``WeekSegment``).
    @given(w=_week_segment_valide())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_mutation_de_week_segment_leve_validation_error(
        self, w: WeekSegment
    ) -> None:
        """Req 2.8 — ``WeekSegment`` immuable après construction."""
        with pytest.raises(ValidationError):
            w.heures_normales = Decimal("999.99")  # type: ignore[misc]


# ===========================================================================
# Property 9 (partiel) — Non-négativité et borne supérieure des heures
# ===========================================================================
# Feature: moteur-paie-contrats, Property 9: Non-négativité des ``Decimal``
# marqués comme tels (partiel — ``heures_normales`` et
# ``heures_supplementaires`` du ``WeekSegment``). L'ensemble accepté est
# ``[0, 168]`` (design §6). Toute valeur strictement négative ou strictement
# supérieure à 168 doit être rejetée, sans clampage ni conversion en valeur
# absolue.
#
# **Validates: Requirements 2.3**


@pytest.mark.property
class TestProperty9HeuresDansPlageAcceptee:
    """Property 9 (partiel) — bornes physiques des heures dans ``WeekSegment``."""

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des `Decimal`
    # (heures dans [0, 168] acceptées).
    @given(
        heures_normales=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("168"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        heures_supp=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("168"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_heures_dans_0_168_sont_acceptees(
        self,
        heures_normales: Decimal,
        heures_supp: Decimal,
    ) -> None:
        """Req 2.3 (design §6) — l'ensemble ``[0, 168]`` est accepté."""
        w = WeekSegment(
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 7),
            heures_normales=heures_normales,
            heures_supplementaires=heures_supp,
        )
        # Post-condition : les valeurs sont restituées inchangées.
        assert Decimal("0") <= w.heures_normales <= Decimal("168")
        assert Decimal("0") <= w.heures_supplementaires <= Decimal("168")

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des `Decimal`
    # (heures strictement négatives refusées).
    @given(
        heures_neg=st.decimals(
            min_value=Decimal("-10000"),
            max_value=Decimal("-0.01"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_heures_normales_strictement_negatives_sont_rejetees(
        self, heures_neg: Decimal
    ) -> None:
        """Req 2.3 (design §6) — refus sans clampage ni valeur absolue."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=heures_neg,
                heures_supplementaires=Decimal("0.00"),
            )

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des `Decimal`
    # (heures strictement supérieures à 168 refusées — borne physique).
    @given(
        heures_hors=st.decimals(
            min_value=Decimal("168.01"),
            max_value=Decimal("100000"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_heures_normales_au_dela_de_168_sont_rejetees(
        self, heures_hors: Decimal
    ) -> None:
        """Req 2.3 (design §6) — 168 h par semaine calendaire est la borne."""
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=heures_hors,
                heures_supplementaires=Decimal("0.00"),
            )

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des `Decimal`
    # (heures supplémentaires — même bornes que les heures normales).
    @given(
        heures_neg=st.decimals(
            min_value=Decimal("-10000"),
            max_value=Decimal("-0.01"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_heures_supplementaires_strictement_negatives_sont_rejetees(
        self, heures_neg: Decimal
    ) -> None:
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=Decimal("40.00"),
                heures_supplementaires=heures_neg,
            )

    @given(
        heures_hors=st.decimals(
            min_value=Decimal("168.01"),
            max_value=Decimal("100000"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_heures_supplementaires_au_dela_de_168_sont_rejetees(
        self, heures_hors: Decimal
    ) -> None:
        with pytest.raises(ValidationError):
            WeekSegment(
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 7),
                heures_normales=Decimal("40.00"),
                heures_supplementaires=heures_hors,
            )


# ===========================================================================
# Property 13 — Contiguïté et couverture des semaines constituantes
# ===========================================================================
# Feature: moteur-paie-contrats, Property 13: Contiguïté et couverture des
# semaines constituantes. Pour tout ``PayPeriod`` construit avec exactement
# le nombre de semaines exigé par sa fréquence (deux pour
# ``aux_deux_semaines``), la construction est acceptée si et seulement si :
#
# - ``semaines[0].date_debut == pay_period.date_debut``
# - ``semaines[-1].date_fin == pay_period.date_fin``
# - pour tout ``i``, ``semaines[i+1].date_debut == semaines[i].date_fin + 1
#   jour``
#
# **Validates: Requirements 2.4, 2.5**


@pytest.mark.property
class TestProperty13ContiguiteEtCouverture:
    """Property 13 — bien aligné accepté, mal aligné refusé."""

    # Feature: moteur-paie-contrats, Property 13: Contiguïté et couverture
    # des semaines constituantes (branche « acceptée »).
    @given(pp=_pay_period_bien_aligne())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_pay_period_bien_aligne_est_accepte(self, pp: PayPeriod) -> None:
        """Req 2.4, 2.5 — contiguïté et couverture satisfaites → accepté."""
        # Post-conditions structurelles : la stratégie génère bien un
        # PayPeriod aligné, et la construction n'a pas rejeté l'entrée.
        assert isinstance(pp, PayPeriod)
        w0, w1 = pp.semaines
        assert w0.date_debut == pp.date_debut
        assert w1.date_fin == pp.date_fin
        assert w1.date_debut == w0.date_fin + timedelta(days=1)

    # Feature: moteur-paie-contrats, Property 13: Contiguïté et couverture
    # des semaines constituantes (branche « refusée »).
    @given(kwargs=_pay_period_kwargs_mal_aligne())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_pay_period_mal_aligne_est_refuse(
        self, kwargs: dict[str, Any]
    ) -> None:
        """Req 2.4, 2.5 — un désalignement DOIT être détecté à la construction."""
        # ``_kind`` est un indicateur de diagnostic Hypothesis ; il ne fait
        # pas partie du contrat ``PayPeriod``.
        kind = kwargs.pop("_kind")
        with pytest.raises(ValidationError):
            PayPeriod(**kwargs)
        # ``kind`` est repris dans la sortie Hypothesis en cas d'échec pour
        # accélérer le diagnostic — le contract ``ValidationError`` reste
        # le seul comportement observable exigé par Property 13.
        assert kind in {"gap", "overlap", "not_start", "not_end"}


# ===========================================================================
# Property 14 — Nombre correct de semaines constituantes
# ===========================================================================
# Feature: moteur-paie-contrats, Property 14: Nombre correct de semaines
# constituantes. Pour tout ``PayPeriod`` avec
# ``frequence == AUX_DEUX_SEMAINES`` et toute liste ``semaines`` de
# longueur ``n != 2``, la construction DOIT lever une erreur de validation
# **avant** que les invariants de la Property 13 (contiguïté / couverture)
# ne soient évalués (AC4 et AC5 du Req 2 exigent explicitement ce
# court-circuit : « la vérification NE DOIT PAS être évaluée » quand
# l'AC2 échoue).
#
# **Validates: Requirements 2.2**


@pytest.mark.property
class TestProperty14NombreCorrectDeSemaines:
    """Property 14 — l'erreur de nombre prévaut sur celle de contiguïté."""

    # Feature: moteur-paie-contrats, Property 14: Nombre correct de semaines
    # constituantes.
    @given(semaines=_liste_semaines_taille_incorrecte())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_liste_de_taille_incorrecte_est_refusee_sans_erreur_de_contiguite(
        self, semaines: tuple[WeekSegment, ...]
    ) -> None:
        """Req 2.2, AC4/AC5 — court-circuit : le nombre prévaut."""
        # Sanity — la stratégie exclut explicitement ``n == 2``.
        assert len(semaines) != 2

        # Bornes du ``PayPeriod`` réalistes : 14 jours (« aux deux semaines »).
        # Ainsi, si le validateur de contiguïté / couverture n'était PAS
        # court-circuité, il produirait forcément une erreur (la longueur
        # cumulée des ``semaines`` ne correspond pas à 14 jours quand
        # ``n != 2``). Le test vérifie donc précisément que l'implémentation
        # ne laisse PAS fuiter cette erreur — c'est la substance de l'AC4/AC5.
        kwargs: dict[str, Any] = {
            "numero_periode": 1,
            "date_debut": date(2026, 1, 5),
            "date_fin": date(2026, 1, 18),  # 14 jours inclusifs
            "date_paiement": date(2026, 1, 21),
            "frequence": FrequencePaie.AUX_DEUX_SEMAINES,
            "nb_periodes_annuelles": 26,
            "annee_fiscale": 2026,
            "semaines": semaines,
        }
        with pytest.raises(ValidationError) as exc_info:
            PayPeriod(**kwargs)

        # Contrat de Property 14 : le message d'erreur ne DOIT PAS mentionner
        # la contiguïté ni la couverture, car ces validateurs sont
        # court-circuités quand le nombre de semaines est incorrect (Req 2
        # AC4 et AC5). La présence d'un tel mot-clé signalerait une
        # violation du court-circuit.
        message = str(exc_info.value)
        assert not _KEYWORDS_CONTIGUITE.search(message), (
            f"Property 14 violée : l'erreur DOIT porter sur le nombre de "
            f"semaines (n={len(semaines)}), pas sur la contiguïté ni la "
            f"couverture. Message reçu : {message!r}."
        )

    def test_liste_vide_est_refusee_sans_erreur_de_contiguite(self) -> None:
        """Cas limite explicite ``n == 0``, hors Hypothesis."""
        kwargs: dict[str, Any] = {
            "numero_periode": 1,
            "date_debut": date(2026, 1, 5),
            "date_fin": date(2026, 1, 18),
            "date_paiement": date(2026, 1, 21),
            "frequence": FrequencePaie.AUX_DEUX_SEMAINES,
            "nb_periodes_annuelles": 26,
            "annee_fiscale": 2026,
            "semaines": (),
        }
        with pytest.raises(ValidationError) as exc_info:
            PayPeriod(**kwargs)
        assert not _KEYWORDS_CONTIGUITE.search(str(exc_info.value))

    @pytest.mark.parametrize("n", [1, 3, 4, 5])
    def test_liste_de_taille_n_est_refusee_sans_erreur_de_contiguite(
        self, n: int
    ) -> None:
        """Cas d'exemple parametrizés pour ``n ∈ {1, 3, 4, 5}``.

        Ces cas explicites documentent le comportement pour les longueurs
        les plus susceptibles d'être générées à la main ou par erreur
        (une seule semaine oubliée, trois semaines par accident, ...).
        """
        base = date(2026, 1, 5)
        semaines = tuple(_week_segment_arbitraire(i, base) for i in range(n))
        kwargs: dict[str, Any] = {
            "numero_periode": 1,
            "date_debut": date(2026, 1, 5),
            "date_fin": date(2026, 1, 18),
            "date_paiement": date(2026, 1, 21),
            "frequence": FrequencePaie.AUX_DEUX_SEMAINES,
            "nb_periodes_annuelles": 26,
            "annee_fiscale": 2026,
            "semaines": semaines,
        }
        with pytest.raises(ValidationError) as exc_info:
            PayPeriod(**kwargs)
        message = str(exc_info.value)
        assert not _KEYWORDS_CONTIGUITE.search(message), (
            f"n={n} : le message doit porter sur le NOMBRE, pas sur la "
            f"contiguïté. Reçu : {message!r}."
        )


# ===========================================================================
# Tests d'exemple — ``PayPeriod`` fréquence hors matrice
# ===========================================================================


class TestPayPeriodFrequenceHorsMatrice:
    """Req 2.6, 11.2, 11.6 — fréquence hors matrice → ``UnsupportedPayrollCase``.

    L'énumération ``FrequencePaie`` n'expose actuellement qu'une seule
    valeur (``AUX_DEUX_SEMAINES``, règle 03 — périmètre Camp LilySO). Ce
    test vérifie qu'une chaîne brute non reconnue passée en construction
    (« hebdomadaire », « mensuelle », ...) déclenche bien
    ``UnsupportedPayrollCase`` avec un message citant la règle 03 ET les
    outils officiels (WebRAS ou PDOC), et non un ``ValidationError`` de
    coercition d'énumération (design §Components 1).
    """

    @pytest.mark.unsupported
    @pytest.mark.parametrize(
        "frequence_hors_matrice",
        ["hebdomadaire", "mensuelle", "bimensuelle", "annuel", "semi_mensuelle"],
    )
    def test_frequence_hors_matrice_leve_unsupported_payroll_case(
        self, frequence_hors_matrice: str
    ) -> None:
        semaines = _semaines_valides_pour_pay_period()
        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            PayPeriod(
                numero_periode=1,
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 14),
                date_paiement=date(2026, 6, 17),
                frequence=frequence_hors_matrice,  # type: ignore[arg-type]
                nb_periodes_annuelles=26,
                annee_fiscale=2026,
                semaines=semaines,
            )

        message = str(exc_info.value)
        # Le constructeur d'exception refuse un message vide (Req 8.3, 8.6).
        assert message.strip() != ""

        # Req 2.6 — le message DOIT citer la règle 03.
        assert _mentionne_regle_03(message), (
            f"Le message d'``UnsupportedPayrollCase`` doit citer la règle 03 "
            f"(fréquence hors matrice). Reçu : {message!r}."
        )
        # Req 11.6 — le message DOIT rediriger vers un outil officiel
        # (WebRAS ou PDOC).
        assert _mentionne_outils_officiels(message), (
            f"Le message d'``UnsupportedPayrollCase`` doit citer WebRAS ou "
            f"PDOC (Req 11.6). Reçu : {message!r}."
        )


# ===========================================================================
# Tests d'exemple — ``PayPeriod.nb_periodes_annuelles``
# ===========================================================================


class TestPayPeriodNbPeriodesAnnuelles:
    """Design §6 — ``nb_periodes_annuelles: int >= 1``.

    Valeurs typiques Camp LilySO : ``27`` pour 2026 (année à 27 paies
    bi-hebdomadaires) et ``26`` pour 2027 et les années standard.
    """

    def test_valeur_27_est_acceptee_pour_2026(self) -> None:
        """Année 2026 — 27 paies bi-hebdomadaires selon le calendrier."""
        semaines = _semaines_valides_pour_pay_period()
        pp = PayPeriod(
            numero_periode=1,
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 14),
            date_paiement=date(2026, 6, 17),
            frequence=FrequencePaie.AUX_DEUX_SEMAINES,
            nb_periodes_annuelles=27,
            annee_fiscale=2026,
            semaines=semaines,
        )
        assert pp.nb_periodes_annuelles == 27

    def test_valeur_26_est_acceptee_pour_annee_standard(self) -> None:
        """Année standard — 26 paies bi-hebdomadaires."""
        semaines = _semaines_valides_pour_pay_period()
        pp = PayPeriod(
            numero_periode=1,
            date_debut=date(2026, 6, 1),
            date_fin=date(2026, 6, 14),
            date_paiement=date(2026, 6, 17),
            frequence=FrequencePaie.AUX_DEUX_SEMAINES,
            nb_periodes_annuelles=26,
            annee_fiscale=2027,
            semaines=semaines,
        )
        assert pp.nb_periodes_annuelles == 26

    @pytest.mark.parametrize(
        "nb_invalide",
        [0, -1, -26, -27, -100],
        ids=["zero", "moins_un", "moins_26", "moins_27", "moins_100"],
    )
    def test_valeur_zero_ou_negative_est_rejetee(self, nb_invalide: int) -> None:
        """Design §6 — ``nb_periodes_annuelles >= 1`` (entier positif)."""
        semaines = _semaines_valides_pour_pay_period()
        with pytest.raises(ValidationError):
            PayPeriod(
                numero_periode=1,
                date_debut=date(2026, 6, 1),
                date_fin=date(2026, 6, 14),
                date_paiement=date(2026, 6, 17),
                frequence=FrequencePaie.AUX_DEUX_SEMAINES,
                nb_periodes_annuelles=nb_invalide,
                annee_fiscale=2026,
                semaines=semaines,
            )
