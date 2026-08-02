"""Stratégies Hypothesis réutilisables pour les property-based tests.

Historique : ce module a été créé (vide) par la spec ``moteur-paie-contrats``.
Les tâches 2 à 14 de cette spec ont finalement implémenté leurs stratégies
Hypothesis localement dans chaque fichier de test (``tests/models/*.py``),
laissant ce module inutilisé. La spec ``gains-bruts-vacances-hs`` (tâche 1.1)
est la première à le peupler réellement, avec les stratégies dédiées au
calcul des gains bruts, décrites ci-dessous.

Stratégies dédiées « gains bruts, vacances et heures supplémentaires »
(design.md §Testing Strategy « Stratégies Hypothesis », spec
``gains-bruts-vacances-hs``, tâche 1.1) :

- ``st_taux_horaire()``            — ``Decimal`` ∈ [10.00, 50.00], 2 décimales.
- ``st_heures_par_semaine()``      — ``Decimal`` ∈ [0, 60], 2 décimales.
- ``st_taux_vacances()``           — ``Decimal`` ∈ {0.04, 0.06}.
- ``st_jours_feries_manuels()``    — ``Decimal`` ∈ [0.00, 500.00], biaisé vers 0.
- ``st_payroll_input()``           — ``PayrollInput`` cohérent par construction
  (Québec, aux deux semaines, 2 semaines constituantes, appariement
  cumuls/employé/année).
- ``st_parametres_annee_2026_qc()`` — ``ParametresAnnee`` réel 2026 Québec,
  chargé une seule fois via ``load_parameters`` et mémorisé au niveau module.

Règle 01 : chaque stratégie manipulant un montant fiscal ou une durée
d'heures DOIT retourner un ``Decimal`` (jamais un ``float``).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from hypothesis import strategies as st

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters

__all__ = [
    "st_taux_horaire",
    "st_heures_par_semaine",
    "st_taux_vacances",
    "st_jours_feries_manuels",
    "st_payroll_input",
    "st_parametres_annee_2026_qc",
]


# ===========================================================================
# Bornes et générateurs internes partagés (non exportés)
# ===========================================================================
#
# Fenêtre de dates réaliste pour le Camp LilySO. La borne haute laisse
# 14 jours de marge pour ``date_debut + timedelta(days=13)`` (fin de
# période bi-hebdomadaire) sans dépasser une date valide.
_DATE_MIN = date(2024, 1, 1)
_DATE_MAX = date(2028, 6, 30)

#: Bornes réutilisées pour les montants monétaires « génériques » du
#: contrat (crédits TP-1015.3 / TD1, retenues additionnelles) qui ne
#: font pas partie des cinq stratégies dédiées demandées par la tâche
#: 1.1, mais que ``st_payroll_input()`` doit tout de même peupler pour
#: produire un ``PayrollInput`` valide (règle 01 : ``Decimal`` partout).
_MAX_CREDIT = Decimal("50000.00")
_MAX_RETENUE_ADDITIONNELLE = Decimal("500.00")


@st.composite
def _st_employe_id(draw: st.DrawFn) -> str:
    """Identifiant employé fictif ``EMPnnn`` (règle 04 — jamais de NAS réel)."""
    n = draw(st.integers(min_value=1, max_value=999))
    return f"EMP{n:03d}"


@st.composite
def _st_annee_fiscale(draw: st.DrawFn) -> int:
    """Année civile plausible pour le corpus Camp LilySO (2024–2030)."""
    return draw(st.integers(min_value=2024, max_value=2030))


@st.composite
def _st_decimal_monetaire(
    draw: st.DrawFn, *, max_value: Decimal
) -> Decimal:
    """``Decimal`` ∈ [0.00, max_value], deux décimales (règle 01)."""
    return draw(
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=max_value,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


def _st_week_segment(*, date_debut: date) -> WeekSegment:
    """Semaine de 7 jours consécutifs pour un ``PayPeriod``.

    Les champs ``heures_normales`` / ``heures_supplementaires`` de
    ``WeekSegment`` ne sont **pas** consommés par ``calcul_gains``
    (design gains-bruts-vacances-hs §Components — voir la note de
    ``models.payroll_input`` sur la distinction ``WeekSegment`` /
    ``HeuresParSemaine``) : ils sont fixés à ``Decimal("0")`` pour ne
    pas introduire de bruit hors du périmètre de cette spec. Les heures
    effectivement utilisées par le calcul proviennent de
    ``PayrollInput.heures_par_semaine`` (voir ``st_heures_par_semaine``).

    Fonction déterministe (pas une stratégie Hypothesis) : ``date_debut``
    est toujours fourni par l'appelant, il n'y a donc rien à tirer au
    hasard ici.
    """
    return WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )


@st.composite
def _st_pay_period_deux_semaines(
    draw: st.DrawFn, *, annee_fiscale: int
) -> PayPeriod:
    """``PayPeriod`` aux deux semaines, deux ``WeekSegment`` contigus.

    Fréquence fixée à ``FrequencePaie.AUX_DEUX_SEMAINES`` — seule
    fréquence supportée par le Camp LilySO (règle 03).
    """
    date_debut = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_fin = date_debut + timedelta(days=13)
    semaine_0 = _st_week_segment(date_debut=date_debut)
    semaine_1 = _st_week_segment(date_debut=date_debut + timedelta(days=7))
    return PayPeriod(
        numero_periode=draw(st.integers(min_value=1, max_value=27)),
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_fin
        + timedelta(days=draw(st.integers(min_value=1, max_value=10))),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=draw(st.sampled_from([26, 27])),
        annee_fiscale=annee_fiscale,
        semaines=(semaine_0, semaine_1),
    )


@st.composite
def _st_employee_qc(draw: st.DrawFn, *, employe_id: str) -> Employee:
    """``Employee`` valide dans le périmètre Camp LilySO (règle 03, règle 04).

    ``province_travail`` fixée à ``Juridiction.QUEBEC``. Aucune donnée
    nominative réelle (``nom_affichage`` fictif basé sur l'identifiant).
    """
    date_embauche = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    return Employee(
        id=employe_id,
        nom_affichage=f"Employe Test {employe_id}",
        date_naissance=draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX)),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Moniteur",
        taux_horaire_base=draw(
            st.decimals(
                min_value=Decimal("10.00"),
                max_value=Decimal("50.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        date_embauche=date_embauche,
        date_fin_emploi=None,
        taux_indemnite_vacances=draw(
            st.sampled_from([Decimal("0.04"), Decimal("0.06")])
        ),
        exoneration_TP1015_3=draw(st.booleans()),
        exoneration_TD1=draw(st.booleans()),
        montant_total_TP1015_3=draw(_st_decimal_monetaire(max_value=_MAX_CREDIT)),
        montant_total_TD1=draw(_st_decimal_monetaire(max_value=_MAX_CREDIT)),
        retenue_additionnelle_QC=draw(
            _st_decimal_monetaire(max_value=_MAX_RETENUE_ADDITIONNELLE)
        ),
        retenue_additionnelle_federale=draw(
            _st_decimal_monetaire(max_value=_MAX_RETENUE_ADDITIONNELLE)
        ),
    )


# ===========================================================================
# Stratégies dédiées gains bruts (design.md §Testing Strategy)
# ===========================================================================


def st_taux_horaire() -> st.SearchStrategy[Decimal]:
    """Taux horaire effectif plausible pour le Camp LilySO.

    Design (§Testing Strategy « Stratégies Hypothesis ») : ``Decimal``
    dans ``[Decimal("10.00"), Decimal("50.00")]``, deux décimales,
    ``allow_nan=False``, ``allow_infinity=False`` — plage réaliste des
    taux horaires versés au Camp LilySO. Alimente
    ``PayrollInput.taux_horaire_effectif`` (règle 01 : ``Decimal``
    exclusivement, jamais ``float``).
    """
    return st.decimals(
        min_value=Decimal("10.00"),
        max_value=Decimal("50.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


def st_heures_par_semaine() -> st.SearchStrategy[Decimal]:
    """Quantité d'heures (normales OU supplémentaires) pour une semaine.

    Design (§Testing Strategy « Stratégies Hypothesis ») : ``Decimal``
    dans ``[0, 60]``, deux décimales — autorise ``0`` (Req 2.4, 3.6,
    4.4), les valeurs fractionnaires (Req 4.5) et les dépassements du
    seuil hebdomadaire de 40 h (Req 3.1). Cette stratégie est tirée deux
    fois par semaine constituante (une pour ``heures_normales``, une
    pour ``heures_supplementaires``) pour peupler
    ``HeuresParSemaine`` — voir ``st_payroll_input``. Règle 01 :
    ``Decimal`` exclusivement (``allow_nan=False``,
    ``allow_infinity=False``).
    """
    return st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("60"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


def st_taux_vacances() -> st.SearchStrategy[Decimal]:
    """Taux d'indemnité de vacances supporté par le Camp LilySO (règle 03).

    Design (§Testing Strategy « Stratégies Hypothesis ») : ensemble fermé
    ``st.sampled_from([Decimal("0.04"), Decimal("0.06")])`` — seules
    valeurs admises par ``PayrollInput.taux_vacances`` (Req 3.5,
    Req 11.3). Utilisée notamment par Property 18 (extensibilité au
    taux 6 %). Property 19 (défense en profondeur) génère à l'inverse
    des valeurs HORS de cet ensemble via une stratégie locale dédiée du
    fichier de test — cette stratégie-ci ne couvre volontairement que
    le cas nominal.
    """
    return st.sampled_from([Decimal("0.04"), Decimal("0.06")])


def st_jours_feries_manuels() -> st.SearchStrategy[Decimal]:
    """Montant des jours fériés inscrits manuellement, biaisé vers 0.

    Design (§Testing Strategy « Stratégies Hypothesis ») : ``Decimal``
    dans ``[Decimal("0.00"), Decimal("500.00")]``, deux décimales, avec
    un poids fort sur le cas nominal ``Decimal("0.00")`` (absence de
    jour férié travaillé) via
    ``st.one_of(st.just(Decimal("0.00")), st.decimals(...))``. Alimente
    ``PayrollInput.jours_feries_manuels`` (``ge=0`` — règle 01 :
    ``Decimal`` exclusivement, jamais négatif).
    """
    return st.one_of(
        st.just(Decimal("0.00")),
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("500.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def st_payroll_input(draw: st.DrawFn) -> PayrollInput:
    """``PayrollInput`` cohérent par construction pour gains-bruts-vacances-hs.

    Design (§Testing Strategy « Stratégies Hypothesis ») : compose
    ``st_taux_horaire``, ``st_heures_par_semaine``, ``st_taux_vacances``,
    ``st_jours_feries_manuels`` avec des stratégies internes pour
    ``Employee``, ``PayPeriod`` (deux ``WeekSegment`` contigus) et
    ``CumulsYTD.zero(...)``, en garantissant par construction :

    - ``cumuls_debut.employe_id == employee.id`` ;
    - ``cumuls_debut.annee_civile == pay_period.annee_fiscale`` ;
    - ``employee.province_travail == Juridiction.QUEBEC`` (règle 03) ;
    - ``pay_period.frequence == FrequencePaie.AUX_DEUX_SEMAINES`` (règle 03) ;
    - ``len(heures_par_semaine) == 2`` (une entrée par semaine constituante
      de la période, Req 3.7).

    Règle 01 : tous les montants sont des ``Decimal`` (aucun ``float``).
    """
    employe_id = draw(_st_employe_id())
    annee_fiscale = draw(_st_annee_fiscale())
    employee = draw(_st_employee_qc(employe_id=employe_id))
    pay_period = draw(_st_pay_period_deux_semaines(annee_fiscale=annee_fiscale))
    heures_par_semaine = (
        HeuresParSemaine(
            heures_normales=draw(st_heures_par_semaine()),
            heures_supplementaires=draw(st_heures_par_semaine()),
        ),
        HeuresParSemaine(
            heures_normales=draw(st_heures_par_semaine()),
            heures_supplementaires=draw(st_heures_par_semaine()),
        ),
    )
    cumuls_debut = CumulsYTD.zero(employe_id=employe_id, annee_civile=annee_fiscale)
    return PayrollInput(
        employee=employee,
        pay_period=pay_period,
        heures_par_semaine=heures_par_semaine,
        taux_horaire_effectif=draw(st_taux_horaire()),
        taux_vacances=draw(st_taux_vacances()),
        jours_feries_manuels=draw(st_jours_feries_manuels()),
        montant_total_TP1015_3_effectif=draw(
            _st_decimal_monetaire(max_value=_MAX_CREDIT)
        ),
        exoneration_TP1015_3_effectif=draw(st.booleans()),
        retenue_additionnelle_QC_effective=draw(
            _st_decimal_monetaire(max_value=_MAX_RETENUE_ADDITIONNELLE)
        ),
        montant_total_TD1_effectif=draw(
            _st_decimal_monetaire(max_value=_MAX_CREDIT)
        ),
        exoneration_TD1_effective=draw(st.booleans()),
        retenue_additionnelle_federale_effective=draw(
            _st_decimal_monetaire(max_value=_MAX_RETENUE_ADDITIONNELLE)
        ),
        cumuls_debut=cumuls_debut,
    )


# ===========================================================================
# Paramètres annuels réels — mémorisation module-scoped
# ===========================================================================


@lru_cache(maxsize=1)
def _charger_parametres_annee_2026_qc() -> ParametresAnnee:
    """Charge ``load_parameters(2026, Juridiction.QUEBEC)`` une seule fois.

    ``functools.lru_cache(maxsize=1)`` mémorise le résultat au niveau
    module : le fichier ``parameters/2026/quebec.json`` n'est lu qu'une
    seule fois par processus de test, quel que soit le nombre d'exemples
    Hypothesis générés (design §Testing Strategy « Stratégies
    Hypothesis »). ``ParametresAnnee`` est ``frozen=True`` (immuable) —
    l'instance partagée entre tous les exemples ne peut donc pas être
    mutée par un test, ce qui rend le partage thread-safe.
    """
    return load_parameters(2026, Juridiction.QUEBEC)


def st_parametres_annee_2026_qc() -> st.SearchStrategy[ParametresAnnee]:
    """``ParametresAnnee`` réel 2026 Québec, chargé une seule fois.

    Design (§Testing Strategy « Stratégies Hypothesis ») : retourne
    toujours la même instance ``ParametresAnnee`` mémorisée au niveau
    module via ``load_parameters(2026, Juridiction.QUEBEC)`` (règle 05 —
    aucun taux, seuil ou multiplicateur fiscal codé en dur dans les
    tests ; la valeur provient exclusivement de
    ``parameters/2026/quebec.json``).
    """
    return st.just(_charger_parametres_annee_2026_qc())
