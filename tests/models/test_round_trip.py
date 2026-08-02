"""Property 6 — Round-trip JSON déterministe pour les 12 modèles du domaine.

Spec de référence : ``moteur-paie-contrats`` — tâche 13.1.
Design de référence : sections « Test Strategy » (Property 6) et
« Architecture » point 6 (``design.md``).

Discipline TDD (règle 06) : ce module de tests est écrit **avant**
l'ajout d'éventuels sérialiseurs ``Decimal → str`` sur les modèles autres
que :class:`models.trace.CalculationTrace` (qui, lui, dispose déjà de
``field_serializer(when_used="json")`` explicites). Les tests peuvent
donc échouer sur certains modèles tant que la tâche 13.2 n'a pas complété
l'implémentation — c'est le comportement attendu par la règle 06.

Portée exacte de la tâche 13.1 (``tasks.md`` §13.1) :

- **Property 6 : Round-trip JSON déterministe** — Hypothesis génère des
  instances valides de :class:`Employee`, :class:`WeekSegment`,
  :class:`PayPeriod`, :class:`HeuresParSemaine`, :class:`CumulsYTD`,
  :class:`PayrollInput`, :class:`GainsDecomposes`,
  :class:`MontantAvecTrace`, :class:`RetenuesEmploye`,
  :class:`CotisationsEmployeur`, :class:`PayrollResult`,
  :class:`CalculationTrace`. Pour chacune, vérifie :

  (a) ``parse(serialize(x)) == x`` — égalité champ à champ après
      round-trip JSON. L'égalité repose sur ``BaseModel.__eq__`` de
      Pydantic v2, qui compare les champs (``Decimal``, ``date``,
      ``datetime``, chaînes, énumérations, sous-modèles) sans
      conversion silencieuse (règle 01).
  (b) Sérialisation déterministe — deux appels successifs à
      ``model_dump_json()`` sur la même instance produisent la même
      chaîne d'octets (ordre des clés stable, ordre des listes /
      sous-totaux nommés préservé).
  (c) La chaîne JSON ne contient **aucun** littéral numérique non
      guillemé avec point décimal ou notation scientifique (test par
      hook ``parse_float`` de :func:`json.loads`). Un ``Decimal`` doit
      être encodé en chaîne guillemée (règle 01, Req 13.5).

  **Validates: Requirements 5.5, 7.8, 13.1, 13.2, 13.3, 13.4**

Approche pour les modèles à invariants croisés (``PayPeriod``,
``PayrollInput``, ``PayrollResult``, ``RetenuesEmploye``,
``CotisationsEmployeur``) : les stratégies Hypothesis locales
construisent l'instance de manière **cohérente par construction** —
c'est-à-dire qu'aucune contrainte ne peut être violée par tirage
aléatoire. Approche cohérente avec celle déjà utilisée dans
``tests/models/test_payroll_result.py`` (fabrique ``_make_result``) et
``tests/models/test_pay_period.py`` (stratégie ``_pay_period_bien_aligne``).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire. Toutes les valeurs monétaires
  sont construites à partir de chaînes.
- Règle 02 — chaque ``CalculationTrace`` utilise une source de la
  liste blanche (``TP-1015.F 2026``).
- Règle 04 — identifiants employé fictifs (``EMP001``, ``EMP002``, …).
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Discipline règle 06 (TDD) : imports au niveau module. Si l'un des 12
# modèles n'est pas encore livré (tâches 2 à 10 non complètes), la
# collection pytest de ce fichier échoue avec ``ModuleNotFoundError`` —
# comportement attendu.
from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import (
    FrequencePaie,
    Juridiction,
    ModeArrondissement,
    StatutDePaie,
)
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
    PayrollResult,
    RetenuesEmploye,
)
from models.trace import CalculationTrace


# ===========================================================================
# Helpers pour la vérification de Property 6
# ===========================================================================


class _FloatLitteralDetecte(Exception):
    """Signal interne levé dès qu'un littéral flottant est rencontré.

    Utilisé uniquement par :func:`_json_contient_flottant_non_guilleme`
    pour interrompre :func:`json.loads` au premier littéral avec point
    décimal — approche cohérente avec le hook ``_reject_json_float`` de
    :mod:`models._validators` mais sans dépendance sur un symbole
    privé (leading underscore).
    """


def _hook_parse_float(_litteral: str) -> None:
    """Hook ``parse_float`` : lève :class:`_FloatLitteralDetecte`.

    :func:`json.loads` appelle ``parse_float`` sur tout jeton numérique
    JSON contenant un point décimal ou une notation scientifique. Un
    entier JSON pur (``27``, ``1``) passe par ``parse_int`` et
    n'atteint pas ce hook — les champs ``int`` (numéro de période,
    année fiscale, version, ...) restent donc acceptés (Req 10.1,
    exception explicite).
    """
    raise _FloatLitteralDetecte()


def _json_contient_flottant_non_guilleme(json_str: str) -> bool:
    """``True`` si la chaîne JSON contient un littéral flottant non guillemé.

    Vérifie la contrainte (c) de Property 6 : la sérialisation d'un
    ``Decimal`` doit produire une chaîne guillemée (``"1516.32"``) et
    jamais un littéral flottant (``1516.32``). :func:`json.loads` est
    utilisé avec ``parse_float=_hook_parse_float`` : dès qu'un jeton
    numérique JSON contenant un point ou un exposant est décodé, le
    hook lève, et cette fonction retourne ``True``.

    Approche préférée à une regex ad hoc : le parseur JSON standard
    connaît la grammaire des chaînes (échappement, Unicode) et évite
    tout faux positif sur des motifs numériques accidentellement
    présents à l'intérieur d'une chaîne (par exemple un nom de
    catégorie qui contiendrait ``1.5``).
    """
    try:
        json.loads(json_str, parse_float=_hook_parse_float)
    except _FloatLitteralDetecte:
        return True
    return False


def _assert_round_trip(instance: Any, cls: type) -> None:
    """Vérifie les trois contraintes de Property 6 sur ``instance``.

    Encapsule le corps de chaque property test pour éviter la
    duplication à travers les 12 modèles testés. L'ordre des
    vérifications est stable :

    1. Détermination de la chaîne JSON sérialisée.
    2. Contrainte (c) — aucun flottant non guillemé (Req 13.4).
       Vérifiée AVANT le round-trip : un flottant non guillemé dans la
       chaîne rendrait le round-trip potentiellement corrompu par
       précision binaire à la relecture (règle 01).
    3. Contrainte (b) — sérialisation déterministe (Req 13.3). Un
       second ``model_dump_json`` doit produire la même chaîne
       d'octets, à l'ordre des clés près.
    4. Contrainte (a) — round-trip fidèle (Req 5.5, Req 7.8, Req 13.2).
       ``cls.model_validate_json(json_str)`` doit reproduire une
       instance strictement égale à ``instance`` au sens de
       ``BaseModel.__eq__``.
    """
    # (1) Sérialisation
    json_str = instance.model_dump_json()

    # (c) Aucun flottant non guillemé — protège la précision Decimal.
    assert not _json_contient_flottant_non_guilleme(json_str), (
        "La sérialisation contient un littéral flottant non guillemé "
        "(Req 13.4). Un `Decimal` doit être encodé en chaîne "
        f"guillemée. Chaîne reçue :\n{json_str}"
    )

    # (b) Sérialisation déterministe.
    json_str_bis = instance.model_dump_json()
    assert json_str == json_str_bis, (
        "La sérialisation n'est pas déterministe (Req 13.3) : deux "
        "appels successifs à `model_dump_json()` sur la même instance "
        f"produisent des chaînes différentes.\nPremier appel :\n"
        f"{json_str}\nSecond appel :\n{json_str_bis}"
    )

    # (a) Round-trip fidèle.
    reconstruit = cls.model_validate_json(json_str)
    assert reconstruit == instance, (
        "Le round-trip JSON ne préserve pas l'égalité champ à champ "
        f"(Req 13.2).\nOriginal :\n{instance!r}\nReconstruit :\n"
        f"{reconstruit!r}"
    )


# ===========================================================================
# Stratégies Hypothesis atomiques réutilisables
# ===========================================================================
#
# Stratégies volontairement bornées et à faible cardinalité pour maintenir
# le temps d'exécution d'Hypothesis raisonnable. Property 6 vise la
# généricité du round-trip sur l'espace des inputs — pas l'exploration
# extrême des bornes numériques (couverte par Property 9).


@st.composite
def _decimal_monetaire(
    draw: st.DrawFn,
    *,
    min_value: Decimal = Decimal("0.00"),
    max_value: Decimal = Decimal("10000.00"),
) -> Decimal:
    """``Decimal`` bornée à deux décimales dans ``[min_value, max_value]``."""
    return draw(
        st.decimals(
            min_value=min_value,
            max_value=max_value,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@st.composite
def _decimal_strict_positif(
    draw: st.DrawFn, *, max_value: Decimal = Decimal("1000.00")
) -> Decimal:
    """``Decimal`` strictement positif, deux décimales."""
    return draw(
        st.decimals(
            min_value=Decimal("0.01"),
            max_value=max_value,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@st.composite
def _decimal_heures(draw: st.DrawFn) -> Decimal:
    """``Decimal`` d'heures dans ``[0, 168]`` (borne physique)."""
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
def _employe_id(draw: st.DrawFn) -> str:
    """Identifiant employé fictif ``EMPnnn`` (règle 04)."""
    n = draw(st.integers(min_value=1, max_value=999))
    return f"EMP{n:03d}"


@st.composite
def _annee_fiscale(draw: st.DrawFn) -> int:
    """Année civile plausible pour le corpus Camp LilySO."""
    return draw(st.integers(min_value=2024, max_value=2030))


# Fenêtre de dates réaliste pour le Camp LilySO. La borne haute laisse
# 14 jours de marge pour ``date + timedelta(days=13)`` (fin de période
# bi-hebdomadaire) sans dépasser une date valide.
_DATE_MIN = date(2024, 1, 1)
_DATE_MAX = date(2028, 6, 30)


# ===========================================================================
# Stratégie — CalculationTrace
# ===========================================================================


# Sources conformes à la liste blanche (règle 02, design §Components 4).
# On échantillonne pour minimiser la variabilité — la stratégie de
# Property 12 (test_trace.py) couvre l'espace complet.
_SOURCES_OFFICIELLES: tuple[str, ...] = (
    "TP-1015.F 2026",
    "TP-1015.F 2026, section 3.2 — RRQ",
    "TP-1015.G 2026",
    "TP-1015.3 2026",
    "T4127 2026",
    "T4127 2026, section 8",
    "TD1 2026",
    "Guide de l'employeur ARC 2026",
    "https://www.revenuquebec.gouv.qc.ca/documents/tp-1015",
    "https://www.canada.ca/formulaires/td1",
)


@st.composite
def _dict_decimal_nomme(
    draw: st.DrawFn, *, max_size: int = 3
) -> dict[str, Decimal]:
    """Petit dict ``str → Decimal`` — ordre d'insertion préservé (Req 5.5).

    Les clés sont générées dans un alphabet ASCII pur pour éviter tout
    problème d'encodage lors de la sérialisation JSON (les chaînes non-
    ASCII sont fines mais ajoutent une couche de variabilité qui ne
    fait pas partie de Property 6).
    """
    n = draw(st.integers(min_value=0, max_value=max_size))
    cles = draw(
        st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
                min_size=1,
                max_size=15,
            ),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )
    valeurs = [draw(_decimal_monetaire(max_value=Decimal("100000.00"))) for _ in cles]
    # Construction explicite via un dict littéral : préserve l'ordre
    # d'insertion (Python 3.7+, garantie de langage).
    return {cle: valeur for cle, valeur in zip(cles, valeurs)}


@st.composite
def _calculation_trace_valide(draw: st.DrawFn) -> CalculationTrace:
    """Génère une ``CalculationTrace`` valide (règle 02, Req 5.1)."""
    return CalculationTrace(
        source=draw(st.sampled_from(_SOURCES_OFFICIELLES)),
        annee=draw(st.integers(min_value=2024, max_value=2030)),
        juridiction=draw(st.sampled_from(list(Juridiction))),
        section=draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -",
                min_size=1,
                max_size=30,
            ).map(lambda s: s.strip() or "section")
        ),
        parametres_utilises=draw(_dict_decimal_nomme()),
        entrees=draw(_dict_decimal_nomme()),
        sous_totaux=draw(_dict_decimal_nomme()),
        mode_arrondissement=draw(st.sampled_from(list(ModeArrondissement))),
        precision_arrondissement=draw(st.integers(min_value=0, max_value=10)),
        resultat=draw(_decimal_monetaire(max_value=Decimal("100000.00"))),
    )


# ===========================================================================
# Stratégie — Employee
# ===========================================================================


# Alphabet ASCII lisible pour les identifiants et libellés. Aucun
# caractère blanchi par ``str_strip_whitespace=True`` pour ne pas
# invalider ``min_length=1`` accidentellement.
_ALPHABET_TEXTE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@st.composite
def _employee_valide(
    draw: st.DrawFn, *, employe_id: str | None = None
) -> Employee:
    """Génère un ``Employee`` valide dans le périmètre Camp LilySO.

    Contraintes appliquées par construction (Req 1.1, 1.5, Req 11.1,
    Req 11.3) :

    - ``province_travail = QUEBEC`` (règle 03) ;
    - ``taux_indemnite_vacances ∈ {0.04, 0.06}`` (Req 11.3) ;
    - ``taux_horaire_base > 0`` ;
    - montants ``>= 0``.
    """
    identifiant = employe_id if employe_id is not None else draw(_employe_id())
    date_naissance = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_embauche = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_fin_emploi = draw(
        st.one_of(
            st.none(),
            st.dates(min_value=date_embauche, max_value=_DATE_MAX),
        )
    )
    return Employee(
        id=identifiant,
        nom_affichage=draw(
            st.text(alphabet=_ALPHABET_TEXTE, min_size=1, max_size=25)
        ),
        date_naissance=date_naissance,
        province_travail=Juridiction.QUEBEC,
        titre_emploi=draw(
            st.text(alphabet=_ALPHABET_TEXTE, min_size=1, max_size=25)
        ),
        taux_horaire_base=draw(_decimal_strict_positif(max_value=Decimal("100.00"))),
        date_embauche=date_embauche,
        date_fin_emploi=date_fin_emploi,
        taux_indemnite_vacances=draw(
            st.sampled_from([Decimal("0.04"), Decimal("0.06")])
        ),
        exoneration_TP1015_3=draw(st.booleans()),
        exoneration_TD1=draw(st.booleans()),
        montant_total_TP1015_3=draw(_decimal_monetaire(max_value=Decimal("50000.00"))),
        montant_total_TD1=draw(_decimal_monetaire(max_value=Decimal("50000.00"))),
        retenue_additionnelle_QC=draw(_decimal_monetaire(max_value=Decimal("500.00"))),
        retenue_additionnelle_federale=draw(
            _decimal_monetaire(max_value=Decimal("500.00"))
        ),
    )


# ===========================================================================
# Stratégie — WeekSegment
# ===========================================================================


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
        heures_normales=draw(_decimal_heures()),
        heures_supplementaires=draw(_decimal_heures()),
    )


# ===========================================================================
# Stratégie — PayPeriod
# ===========================================================================


@st.composite
def _pay_period_valide(
    draw: st.DrawFn,
    *,
    annee_fiscale: int | None = None,
    date_debut: date | None = None,
) -> PayPeriod:
    """Génère un ``PayPeriod`` bi-hebdomadaire cohérent par construction.

    Les invariants suivants sont satisfaits par construction (Req 2.2,
    2.4, 2.5, 11.2) :

    - Fréquence ``AUX_DEUX_SEMAINES`` (règle 03) ;
    - Deux ``WeekSegment`` de 7 jours contigus, couvrant exactement
      ``[date_debut ; date_debut + 13 jours]`` ;
    - ``nb_periodes_annuelles`` échantillonné dans ``{26, 27}``.
    """
    if date_debut is None:
        date_debut = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_fin = date_debut + timedelta(days=13)
    annee = (
        annee_fiscale
        if annee_fiscale is not None
        else draw(st.integers(min_value=2024, max_value=2030))
    )
    w0 = draw(_week_segment_valide(date_debut=date_debut))
    w1 = draw(_week_segment_valide(date_debut=date_debut + timedelta(days=7)))
    return PayPeriod(
        numero_periode=draw(st.integers(min_value=1, max_value=27)),
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_fin + timedelta(days=draw(st.integers(min_value=1, max_value=10))),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=draw(st.sampled_from([26, 27])),
        annee_fiscale=annee,
        semaines=(w0, w1),
    )


# ===========================================================================
# Stratégie — HeuresParSemaine
# ===========================================================================


@st.composite
def _heures_par_semaine_valide(draw: st.DrawFn) -> HeuresParSemaine:
    """Génère un ``HeuresParSemaine`` avec heures ∈ [0, 168]."""
    return HeuresParSemaine(
        heures_normales=draw(_decimal_heures()),
        heures_supplementaires=draw(_decimal_heures()),
    )


# ===========================================================================
# Stratégie — CumulsYTD
# ===========================================================================


_CATEGORIES_CUMULS: tuple[str, ...] = (
    "brut",
    "vacances",
    "rrq_employe",
    "rrq_employeur",
    "rqap_employe",
    "rqap_employeur",
    "ae_employe",
    "ae_employeur",
    "impot_qc_retenu",
    "impot_federal_retenu",
    "net",
)


@st.composite
def _cumuls_ytd_valide(
    draw: st.DrawFn,
    *,
    employe_id: str | None = None,
    annee_civile: int | None = None,
) -> CumulsYTD:
    """Génère un ``CumulsYTD`` avec les 11 catégories ``Decimal >= 0``."""
    kwargs: dict[str, Any] = {
        "employe_id": employe_id if employe_id is not None else draw(_employe_id()),
        "annee_civile": (
            annee_civile if annee_civile is not None else draw(_annee_fiscale())
        ),
    }
    for categorie in _CATEGORIES_CUMULS:
        kwargs[categorie] = draw(_decimal_monetaire(max_value=Decimal("50000.00")))
    return CumulsYTD(**kwargs)


# ===========================================================================
# Stratégie — PayrollInput
# ===========================================================================


@st.composite
def _payroll_input_valide(draw: st.DrawFn) -> PayrollInput:
    """Génère un ``PayrollInput`` cohérent par construction (Req 3).

    Contraintes croisées satisfaites par construction :

    - ``employee.province_travail == QUEBEC`` (Req 3.10) ;
    - ``pay_period.frequence == AUX_DEUX_SEMAINES`` (Req 3.9) ;
    - ``taux_vacances ∈ {0.04, 0.06}`` (Req 3.5) ;
    - ``len(heures_par_semaine) == len(pay_period.semaines) == 2`` (Req 3.7) ;
    - ``cumuls_debut.employe_id == employee.id`` (Req 3.1) ;
    - ``cumuls_debut.annee_civile == pay_period.annee_fiscale`` (Req 3.1).
    """
    identifiant = draw(_employe_id())
    annee = draw(_annee_fiscale())
    employe = draw(_employee_valide(employe_id=identifiant))
    periode = draw(_pay_period_valide(annee_fiscale=annee))
    heures = (
        draw(_heures_par_semaine_valide()),
        draw(_heures_par_semaine_valide()),
    )
    cumuls = draw(_cumuls_ytd_valide(employe_id=identifiant, annee_civile=annee))
    return PayrollInput(
        employee=employe,
        pay_period=periode,
        heures_par_semaine=heures,
        taux_horaire_effectif=draw(
            _decimal_strict_positif(max_value=Decimal("100.00"))
        ),
        taux_vacances=draw(
            st.sampled_from([Decimal("0.04"), Decimal("0.06")])
        ),
        jours_feries_manuels=draw(_decimal_monetaire(max_value=Decimal("500.00"))),
        montant_total_TP1015_3_effectif=draw(
            _decimal_monetaire(max_value=Decimal("50000.00"))
        ),
        exoneration_TP1015_3_effectif=draw(st.booleans()),
        retenue_additionnelle_QC_effective=draw(
            _decimal_monetaire(max_value=Decimal("500.00"))
        ),
        montant_total_TD1_effectif=draw(
            _decimal_monetaire(max_value=Decimal("50000.00"))
        ),
        exoneration_TD1_effective=draw(st.booleans()),
        retenue_additionnelle_federale_effective=draw(
            _decimal_monetaire(max_value=Decimal("500.00"))
        ),
        cumuls_debut=cumuls,
    )


# ===========================================================================
# Stratégie — GainsDecomposes
# ===========================================================================


@st.composite
def _gains_decomposes_valide(
    draw: st.DrawFn, *, brut_total: Decimal | None = None
) -> GainsDecomposes:
    """Génère un ``GainsDecomposes`` valide.

    ``GainsDecomposes`` n'impose pas ``salaire_regulier +
    heures_supplementaires_montant + vacances + jours_feries_manuels ==
    brut_total`` (design §Data Models 9). On peut donc tirer chaque
    composante indépendamment sans casser l'invariant du modèle.
    """
    if brut_total is None:
        brut_total = draw(_decimal_monetaire(max_value=Decimal("20000.00")))
    return GainsDecomposes(
        salaire_regulier=draw(_decimal_monetaire(max_value=Decimal("20000.00"))),
        heures_supplementaires_montant=draw(
            _decimal_monetaire(max_value=Decimal("5000.00"))
        ),
        vacances=draw(_decimal_monetaire(max_value=Decimal("2000.00"))),
        jours_feries_manuels=draw(_decimal_monetaire(max_value=Decimal("1000.00"))),
        brut_total=brut_total,
        multiplicateur_heures_supp=draw(
            _decimal_strict_positif(max_value=Decimal("3.00"))
        ),
        seuil_heures_supp_hebdo=draw(
            _decimal_strict_positif(max_value=Decimal("100.00"))
        ),
    )


# ===========================================================================
# Stratégie — MontantAvecTrace
# ===========================================================================


@st.composite
def _montant_avec_trace_valide(
    draw: st.DrawFn, *, montant: Decimal | None = None
) -> MontantAvecTrace:
    """Génère un ``MontantAvecTrace`` avec une trace conforme (règle 02)."""
    m = (
        montant
        if montant is not None
        else draw(_decimal_monetaire(max_value=Decimal("5000.00")))
    )
    return MontantAvecTrace(montant=m, trace=draw(_calculation_trace_valide()))


# ===========================================================================
# Stratégie — RetenuesEmploye
# ===========================================================================


@st.composite
def _retenues_employe_valide(draw: st.DrawFn) -> RetenuesEmploye:
    """Génère un ``RetenuesEmploye`` avec l'invariant de somme satisfait.

    Invariant (Req 12.8) : ``total_retenues_employe == rrq + rqap + ae
    + impot_qc_retenu + impot_federal_retenu`` — les deux montants
    ``*_formule`` NE comptent PAS dans le total.
    """
    rrq_m = draw(_decimal_monetaire(max_value=Decimal("500.00")))
    rqap_m = draw(_decimal_monetaire(max_value=Decimal("100.00")))
    ae_m = draw(_decimal_monetaire(max_value=Decimal("200.00")))
    impot_qc_retenu_m = draw(_decimal_monetaire(max_value=Decimal("1000.00")))
    impot_federal_retenu_m = draw(_decimal_monetaire(max_value=Decimal("1000.00")))
    # Les ``*_formule`` sont indépendants de la somme (Req 12.8) et
    # peuvent être n'importe quel Decimal >= 0.
    impot_qc_formule_m = draw(_decimal_monetaire(max_value=Decimal("1000.00")))
    impot_federal_formule_m = draw(_decimal_monetaire(max_value=Decimal("1000.00")))
    total = rrq_m + rqap_m + ae_m + impot_qc_retenu_m + impot_federal_retenu_m
    return RetenuesEmploye(
        rrq=draw(_montant_avec_trace_valide(montant=rrq_m)),
        rqap=draw(_montant_avec_trace_valide(montant=rqap_m)),
        ae=draw(_montant_avec_trace_valide(montant=ae_m)),
        impot_qc_formule=draw(_montant_avec_trace_valide(montant=impot_qc_formule_m)),
        impot_qc_retenu=draw(_montant_avec_trace_valide(montant=impot_qc_retenu_m)),
        impot_federal_formule=draw(
            _montant_avec_trace_valide(montant=impot_federal_formule_m)
        ),
        impot_federal_retenu=draw(
            _montant_avec_trace_valide(montant=impot_federal_retenu_m)
        ),
        total_retenues_employe=total,
    )


# ===========================================================================
# Stratégie — CotisationsEmployeur
# ===========================================================================


@st.composite
def _cotisations_employeur_valide(draw: st.DrawFn) -> CotisationsEmployeur:
    """Génère un ``CotisationsEmployeur`` avec invariant de somme satisfait.

    Invariant (design §Data Models 9) : ``total_cotisations_employeur
    == rrq_employeur + rqap_employeur + ae_employeur + fss + cnesst + cnt``.
    """
    rrq_er = draw(_decimal_monetaire(max_value=Decimal("500.00")))
    rqap_er = draw(_decimal_monetaire(max_value=Decimal("100.00")))
    ae_er = draw(_decimal_monetaire(max_value=Decimal("300.00")))
    fss = draw(_decimal_monetaire(max_value=Decimal("200.00")))
    cnesst = draw(_decimal_monetaire(max_value=Decimal("200.00")))
    cnt = draw(_decimal_monetaire(max_value=Decimal("50.00")))
    total = rrq_er + rqap_er + ae_er + fss + cnesst + cnt
    return CotisationsEmployeur(
        rrq_employeur=draw(_montant_avec_trace_valide(montant=rrq_er)),
        rqap_employeur=draw(_montant_avec_trace_valide(montant=rqap_er)),
        ae_employeur=draw(_montant_avec_trace_valide(montant=ae_er)),
        fss=draw(_montant_avec_trace_valide(montant=fss)),
        cnesst=draw(_montant_avec_trace_valide(montant=cnesst)),
        cnesst_en_attente_classification=draw(st.booleans()),
        cnt=draw(_montant_avec_trace_valide(montant=cnt)),
        total_cotisations_employeur=total,
    )


# ===========================================================================
# Stratégie — PayrollResult
# ===========================================================================


# Triplets ``(statut, remplace_par_id, date_emission)`` valides selon la
# biconditionnelle Property 11 (Req 6.3–6.5, 6.7). Ils sont énumérés
# explicitement pour garantir qu'Hypothesis n'invente pas un cas
# invalide qui casserait la stratégie.
_TRIPLETS_STATUT_VALIDES: tuple[
    tuple[StatutDePaie, str | None, datetime | None], ...
] = (
    # BROUILLON : ni ``remplace_par_id`` ni ``date_emission`` requis.
    (StatutDePaie.BROUILLON, None, None),
    (StatutDePaie.BROUILLON, None, datetime(2026, 6, 20, 10, 0, 0)),
    # EMISE : ``date_emission`` requise, ``remplace_par_id`` interdit.
    (StatutDePaie.EMISE, None, datetime(2026, 6, 20, 10, 0, 0)),
    # ANNULEE : ``date_emission`` requise, ``remplace_par_id`` interdit.
    (StatutDePaie.ANNULEE, None, datetime(2026, 6, 21, 11, 0, 0)),
    # REMPLACE_PAR : ``remplace_par_id`` non vide ET ``date_emission`` requises.
    (
        StatutDePaie.REMPLACE_PAR,
        "PAIE-EMP001-2026-13",
        datetime(2026, 7, 5, 12, 0, 0),
    ),
)


@st.composite
def _payroll_result_valide(draw: st.DrawFn) -> PayrollResult:
    """Génère un ``PayrollResult`` cohérent par construction.

    Toutes les identités et biconditionnelles sont satisfaites par
    construction (Req 4.6, 4.9, 4.10, 6.3–6.5, 6.7) :

    - ``net + total_retenues_employe == gains.brut_total`` (Req 4.9) ;
    - ``cout_employeur == gains.brut_total + total_cotisations_employeur``
      (Req 4.10) ;
    - ``cumuls_fin.employe_id == employe_id`` (Req 4.6) ;
    - ``cumuls_fin.annee_civile == annee_fiscale`` (Req 4.6) ;
    - biconditionnelle statut ⟺ remplace_par_id ⟺ date_emission
      (Req 6.3–6.5, 6.7) via :data:`_TRIPLETS_STATUT_VALIDES`.

    On construit d'abord les retenues et cotisations, puis on choisit
    ``brut_total`` de sorte que ``net = brut_total - total_retenues``
    soit ``>= 0`` (contrainte ``Field(..., ge=0)`` sur ``net``).
    """
    identifiant = draw(_employe_id())
    annee = draw(_annee_fiscale())

    retenues = draw(_retenues_employe_valide())
    cotisations = draw(_cotisations_employeur_valide())

    # ``brut_total`` doit couvrir toutes les retenues employé (sinon
    # ``net = brut - total_retenues < 0``, refusé par ``ge=0``). On
    # ajoute une marge non-négative tirée aléatoirement.
    marge_net = draw(_decimal_monetaire(max_value=Decimal("5000.00")))
    brut_total = retenues.total_retenues_employe + marge_net
    gains = draw(_gains_decomposes_valide(brut_total=brut_total))

    net = brut_total - retenues.total_retenues_employe
    cout_employeur = brut_total + cotisations.total_cotisations_employeur

    statut, remplace_par_id, date_emission = draw(
        st.sampled_from(_TRIPLETS_STATUT_VALIDES)
    )

    return PayrollResult(
        id_paie=f"PAIE-{identifiant}-{annee}-{draw(st.integers(min_value=1, max_value=27))}",
        version=draw(st.integers(min_value=1, max_value=5)),
        employe_id=identifiant,
        annee_fiscale=annee,
        pay_period=draw(_pay_period_valide(annee_fiscale=annee)),
        gains=gains,
        retenues_employe=retenues,
        cotisations_employeur=cotisations,
        net=net,
        cout_employeur=cout_employeur,
        cumuls_fin=draw(_cumuls_ytd_valide(employe_id=identifiant, annee_civile=annee)),
        statut=statut,
        remplace_par_id=remplace_par_id,
        date_creation=datetime(2026, 6, 19, 12, 0, 0),
        date_emission=date_emission,
    )


# ===========================================================================
# Property 6 — Round-trip JSON déterministe pour les 12 modèles du domaine
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 6: Round-trip JSON déterministe
# pour tous les modèles du domaine.
#
# **Validates: Requirements 5.5, 7.8, 13.1, 13.2, 13.3, 13.4**
#
# Un test PBT distinct par modèle — approche cohérente avec la structure
# de ``tasks.md §13.1`` qui énumère explicitement les 12 modèles et
# facilite l'identification du modèle défaillant dans le rapport pytest.
# ===========================================================================


@pytest.mark.property
class TestProperty6RoundTripJson:
    """Property 6 (Hypothesis) — round-trip JSON déterministe.

    Un test par modèle du domaine. Le corps de chaque test est réduit à
    l'appel :func:`_assert_round_trip`, qui encapsule les trois
    contraintes (a), (b), (c) — voir la docstring de ce helper pour le
    détail des vérifications.
    """

    # -----------------------------------------------------------------
    # 1. CalculationTrace (Req 5.5)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``CalculationTrace``).
    @given(instance=_calculation_trace_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_calculation_trace(self, instance: CalculationTrace) -> None:
        """Req 5.5 — round-trip JSON déterministe pour ``CalculationTrace``."""
        _assert_round_trip(instance, CalculationTrace)

    # -----------------------------------------------------------------
    # 2. Employee (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``Employee``).
    @given(instance=_employee_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_employee(self, instance: Employee) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``Employee``."""
        _assert_round_trip(instance, Employee)

    # -----------------------------------------------------------------
    # 3. WeekSegment (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``WeekSegment``).
    @given(instance=_week_segment_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_week_segment(self, instance: WeekSegment) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``WeekSegment``."""
        _assert_round_trip(instance, WeekSegment)

    # -----------------------------------------------------------------
    # 4. PayPeriod (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``PayPeriod``).
    @given(instance=_pay_period_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_pay_period(self, instance: PayPeriod) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``PayPeriod``."""
        _assert_round_trip(instance, PayPeriod)

    # -----------------------------------------------------------------
    # 5. HeuresParSemaine (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``HeuresParSemaine``).
    @given(instance=_heures_par_semaine_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_heures_par_semaine(
        self, instance: HeuresParSemaine
    ) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``HeuresParSemaine``."""
        _assert_round_trip(instance, HeuresParSemaine)

    # -----------------------------------------------------------------
    # 6. CumulsYTD (Req 7.8, 13.1–13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``CumulsYTD``).
    @given(instance=_cumuls_ytd_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_cumuls_ytd(self, instance: CumulsYTD) -> None:
        """Req 7.8 + 13.1–13.4 — round-trip JSON déterministe pour ``CumulsYTD``."""
        _assert_round_trip(instance, CumulsYTD)

    # -----------------------------------------------------------------
    # 7. PayrollInput (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``PayrollInput``).
    @given(instance=_payroll_input_valide())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_payroll_input(self, instance: PayrollInput) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``PayrollInput``."""
        _assert_round_trip(instance, PayrollInput)

    # -----------------------------------------------------------------
    # 8. GainsDecomposes (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``GainsDecomposes``).
    @given(instance=_gains_decomposes_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_gains_decomposes(self, instance: GainsDecomposes) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``GainsDecomposes``."""
        _assert_round_trip(instance, GainsDecomposes)

    # -----------------------------------------------------------------
    # 9. MontantAvecTrace (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``MontantAvecTrace``).
    @given(instance=_montant_avec_trace_valide())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_montant_avec_trace(
        self, instance: MontantAvecTrace
    ) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``MontantAvecTrace``."""
        _assert_round_trip(instance, MontantAvecTrace)

    # -----------------------------------------------------------------
    # 10. RetenuesEmploye (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``RetenuesEmploye``).
    @given(instance=_retenues_employe_valide())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_retenues_employe(self, instance: RetenuesEmploye) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``RetenuesEmploye``."""
        _assert_round_trip(instance, RetenuesEmploye)

    # -----------------------------------------------------------------
    # 11. CotisationsEmployeur (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``CotisationsEmployeur``).
    @given(instance=_cotisations_employeur_valide())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_cotisations_employeur(
        self, instance: CotisationsEmployeur
    ) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``CotisationsEmployeur``."""
        _assert_round_trip(instance, CotisationsEmployeur)

    # -----------------------------------------------------------------
    # 12. PayrollResult (Req 13.1, 13.2, 13.3, 13.4)
    # -----------------------------------------------------------------
    # Feature: moteur-paie-contrats, Property 6: Round-trip JSON
    # déterministe (composante ``PayrollResult``). Nombre d'exemples
    # réduit — ``PayrollResult`` est le modèle le plus lourd à générer
    # (dépend de tous les autres) ; 50 itérations suffisent à couvrir
    # la propriété sans allonger le temps d'exécution de la suite.
    @given(instance=_payroll_result_valide())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_round_trip_payroll_result(self, instance: PayrollResult) -> None:
        """Req 13.1–13.4 — round-trip JSON déterministe pour ``PayrollResult``."""
        _assert_round_trip(instance, PayrollResult)
