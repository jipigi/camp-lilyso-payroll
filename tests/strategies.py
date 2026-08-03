"""Stratégies Hypothesis réutilisables pour les property-based tests.

Historique : ce module a été créé (vide) par la spec ``moteur-paie-contrats``.
Les tâches 2 à 14 de cette spec ont finalement implémenté leurs stratégies
Hypothesis localement dans chaque fichier de test (``tests/models/*.py``),
laissant ce module inutilisé. La spec ``gains-bruts-vacances-hs`` (tâche 1.1)
est la première à le peupler réellement, avec les stratégies dédiées au
calcul des gains bruts, décrites ci-dessous. La spec ``cotisations-sociales-qc``
(tâche 1.1) étend ce module avec quatre stratégies supplémentaires dédiées
aux cumuls YTD plafonnés et aux paramètres RRQ/RQAP/AE.

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

Stratégies dédiées « cotisations sociales RRQ, RQAP, AE »
(design.md §Testing Strategy « Stratégies Hypothesis », spec
``cotisations-sociales-qc``, tâche 1.1) :

- ``st_cumuls_ytd_non_nuls()``        — ``CumulsYTD`` où au moins une des six
  catégories de cotisation est strictement positive, biaisé vers ``[0, plafond]``
  et vers le plafond exact (exerce le plafonnement en cours de saison).
- ``st_brut_total_avec_zero()``       — ``Decimal`` ∈ [0.00, 5000.00], biaisé vers 0.
- ``st_parametres_annee_2026_qc_ca()`` — ``ParametresAnnee`` réel 2026 fusionné
  Québec + Canada (RRQ, RQAP, AE tous accessibles depuis le même objet),
  chargé une seule fois et mémorisé au niveau module.
- ``st_parametres_annee_avec_to_fill(champ)`` — variante du ``ParametresAnnee``
  ci-dessus où un champ ciblé porte la sentinelle ``"TO_FILL"`` (Property 17).

Stratégies dédiées « impôt retenu à la source QC et fédéral »
(design.md §Testing Strategy « Stratégies Hypothesis », spec
``impots-retenues-source``, tâche 1.1) :

- ``st_credit_personnel_eleve()``   — ``Decimal`` biaisé vers des montants
  très élevés (plusieurs centaines de milliers de dollars, jusqu'à des
  bornes dépassant le revenu annualisé maximal généré par
  ``st_payroll_input``), pour ``montant_total_TP1015_3_effectif`` /
  ``montant_total_TD1_effectif`` — exerce le comportement sous le seuil
  d'imposition (Property 8) et la défense en profondeur du Requirement
  12.5 sans dépendre du corpus golden.
- ``st_parametres_annee_impot_avec_to_fill(champ)`` — variante du
  ``ParametresAnnee`` réel 2026 (fusion QC + CA, incluant la section
  ``impot_federal``) où un champ ciblé côté impôt — scalaire
  (``impot_quebec.taux_credits_convertibles``, …) ou imbriqué dans un
  palier (``impot_quebec.paliers[i].taux``, …) — porte la sentinelle
  ``"TO_FILL"`` (Property 13).

Note d'ordonnancement (règle 06) : ``st_parametres_annee_impot_avec_to_fill``
cible des champs typés (sous-modèle ``Palier`` et attributs ``*_brut`` des
sections ``impot_quebec`` / ``impot_federal``) qui ne deviennent des
propriétés matérialisées qu'à partir de la tâche 7.2. Cette stratégie est
donc écrite **avant** le code qu'elle exercera (tests avant implémentation) :
son corps s'exécute paresseusement (à l'appel, jamais à l'import), de sorte
que l'import de ce module reste sûr. Son invocation effective peut lever
``AttributeError`` tant que la tâche 7.2 n'a pas matérialisé les champs
typés — comportement attendu et correct au titre de la règle 06.

Stratégies dédiées « charges patronales FSS, CNESST, CNT »
(design.md §Testing Strategy « Stratégies Hypothesis », spec
``charges-patronales``, tâche 1.1) :

- ``st_brut_total_avec_zero_et_grands()`` — ``Decimal`` ∈ [0.00, 200000.00],
  deux décimales, biaisé vers ``Decimal("0.00")`` (Property 4) **et** vers de
  grandes valeurs supérieures à ``103 000 $`` (Property 8, absence de
  plafond). Destiné à alimenter ``GainsDecomposes.brut_total`` dans les tests
  des trois fonctions de charges.
- ``st_parametres_annee_variantes_non_consommees()`` — variantes du
  ``ParametresAnnee`` réel 2026 Québec différant **uniquement** sur les
  champs non consommés par le calcul de période (``fss.masse_salariale_``
  ``utilisee_webras_2026``, ``fss.table_taux_par_masse_salariale``,
  ``cnt.base_admissible``, ``cnesst.en_attente_classification`` et les
  sous-taux CNESST ``taux_unite`` / ``taux_cni``), pour Property 8
  (insensibilité + absence de plafond) et Property 11 (report du drapeau
  CNESST sans effet sur le total).

Les stratégies ``st_parametres_annee_2026_qc()`` (``ParametresAnnee`` réel
2026 Québec, sections ``fss`` / ``cnesst`` / ``cnt`` renseignées) et
``st_parametres_annee_avec_to_fill(champ)`` (variante où un champ consommé
porte ``"TO_FILL"``), toutes deux déjà présentes ci-dessus, sont
**réutilisées telles quelles** par la spec ``charges-patronales`` : la
première fournit le socle de paramètres commun à toutes les propriétés, la
seconde couvre la Property 13 pour ``fss.taux_camp_lilyso_2026``,
``cnesst.taux_total`` et ``cnt.taux``.

Règle 01 : chaque stratégie manipulant un montant fiscal ou une durée
d'heures DOIT retourner un ``Decimal`` (jamais un ``float``).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from hypothesis import strategies as st

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from payroll_engine.parameters_loader import (
    SENTINEL_TO_FILL,
    ParametresAnnee,
    load_parameters,
)

__all__ = [
    "st_taux_horaire",
    "st_heures_par_semaine",
    "st_taux_vacances",
    "st_jours_feries_manuels",
    "st_payroll_input",
    "st_parametres_annee_2026_qc",
    "st_cumuls_ytd_non_nuls",
    "st_brut_total_avec_zero",
    "st_parametres_annee_2026_qc_ca",
    "st_parametres_annee_avec_to_fill",
    "st_credit_personnel_eleve",
    "st_parametres_annee_impot_avec_to_fill",
    "st_brut_total_avec_zero_et_grands",
    "st_parametres_annee_variantes_non_consommees",
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


# ===========================================================================
# Paramètres annuels réels fusionnés Québec + Canada — mémorisation
# module-scoped (spec cotisations-sociales-qc, tâche 1.1)
# ===========================================================================


@lru_cache(maxsize=1)
def _charger_parametres_annee_2026_qc_ca() -> ParametresAnnee:
    """Charge et fusionne ``load_parameters(2026, QUEBEC | CANADA)`` une seule fois.

    Les six fonctions de la spec ``cotisations-sociales-qc`` (RRQ, RQAP —
    sections du fichier ``quebec.json`` — et AE — section du fichier
    ``canada.json``) consomment un unique argument ``parametres_annee``
    (design §Components §1 : ``ParametresAnnee``). Pour permettre à
    ``calcul_ae_employe``/``calcul_ae_employeur`` d'accéder à
    ``parametres_annee.assurance_emploi`` tout en gardant
    ``parametres_annee.rrq``/``.rqap`` disponibles pour les deux autres
    modules, cette fabrique fusionne les deux instances réelles chargées
    séparément : la racine Québec (``rrq``, ``rqap``) reçoit la section
    ``assurance_emploi`` de la racine Canada, via
    ``model_copy(update=...)`` (aucune mutation — règle 06, immuabilité).

    ``functools.lru_cache(maxsize=1)`` mémorise le résultat au niveau
    module, cohérent avec ``_charger_parametres_annee_2026_qc`` déjà
    existant (design §Testing Strategy « Stratégies Hypothesis ») : les
    fichiers ``parameters/2026/{quebec,canada}.json`` ne sont lus qu'une
    seule fois par processus de test. ``ParametresAnnee`` est
    ``frozen=True`` — l'instance partagée ne peut pas être mutée par un
    test, ce qui rend le partage thread-safe.
    """
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    return parametres_qc.model_copy(
        update={
            "assurance_emploi": parametres_ca.assurance_emploi,
            "impot_federal": parametres_ca.impot_federal,
        }
    )


def st_parametres_annee_2026_qc_ca() -> st.SearchStrategy[ParametresAnnee]:
    """``ParametresAnnee`` réel 2026, fusion Québec (RRQ, RQAP) + Canada (AE).

    Design (§Testing Strategy « Stratégies Hypothesis ») : retourne
    toujours la même instance mémorisée au niveau module via
    ``load_parameters(2026, Juridiction.QUEBEC)`` fusionné avec
    ``load_parameters(2026, Juridiction.CANADA)`` (règle 05 — aucun taux,
    seuil ou multiplicateur fiscal codé en dur dans les tests ; les
    valeurs proviennent exclusivement de ``parameters/2026/quebec.json``
    et ``parameters/2026/canada.json``). Réutilisable par les trois
    fichiers de tests de la spec ``cotisations-sociales-qc``
    (``test_rrq.py``, ``test_rqap.py``, ``test_assurance_emploi.py``).
    """
    return st.just(_charger_parametres_annee_2026_qc_ca())


# ===========================================================================
# Stratégies dédiées cotisations sociales RRQ, RQAP, AE
# (design.md §Testing Strategy « Stratégies Hypothesis »,
#  spec cotisations-sociales-qc, tâche 1.1)
# ===========================================================================

#: Association catégorie ``CumulsYTD`` -> chemin ``(section, champ)`` du
#: plafond annuel correspondant dans ``ParametresAnnee`` (design
#: §Correctness Properties 4, 5 ; §Components §2 à §7). La RRQ employeur
#: n'a pas de plafond distinct dans ``parameters/2026/quebec.json``
#: (``calcul_rrq_employeur`` délègue strictement à ``calcul_rrq_employe``,
#: §Components §3) : elle réutilise le même plafond que la RRQ employé,
#: ce qui reste un biais de génération raisonnable pour exercer le
#: plafonnement en cours de saison sans jamais coder ce montant en dur
#: dans ``payroll_engine/`` (règle 05 — seul ce module de test lit la
#: valeur, via l'objet ``ParametresAnnee`` réel).
_CATEGORIES_COTISATION_VERS_PLAFOND: tuple[tuple[str, str, str], ...] = (
    ("rrq_employe", "rrq", "cotisation_max_annuelle_employe"),
    ("rrq_employeur", "rrq", "cotisation_max_annuelle_employe"),
    ("rqap_employe", "rqap", "cotisation_max_employe"),
    ("rqap_employeur", "rqap", "cotisation_max_employeur"),
    ("ae_employe", "assurance_emploi", "cotisation_max_employe"),
    ("ae_employeur", "assurance_emploi", "cotisation_max_employeur"),
)


def _st_montant_ytd_biaise_plafond(plafond: Decimal) -> st.SearchStrategy[Decimal]:
    """``Decimal`` dans ``[0, plafond]``, biaisé vers ``plafond`` exactement.

    Helper interne de ``st_cumuls_ytd_non_nuls`` : ``st.one_of`` incluant
    ``st.just(plafond)`` (design §Testing Strategy « Stratégies
    Hypothesis ») garantit qu'Hypothesis explore régulièrement le cas
    limite où le cumul YTD atteint exactement le plafond annuel — cas
    non couvert par le corpus golden (Introduction des requirements,
    toutes les fixtures QC001–QC006 étant des paies n° 1, cumul nul).
    """
    return st.one_of(
        st.just(plafond),
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=plafond,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def st_cumuls_ytd_non_nuls(draw: st.DrawFn) -> CumulsYTD:
    """``CumulsYTD`` où au moins une des six catégories de cotisation est > 0.

    Design (§Testing Strategy « Stratégies Hypothesis ») : génère les six
    catégories ``rrq_employe``, ``rrq_employeur``, ``rqap_employe``,
    ``rqap_employeur``, ``ae_employe``, ``ae_employeur`` avec un biais
    explicite vers ``[0, plafond]`` et vers ``plafond`` exactement (voir
    ``_st_montant_ytd_biaise_plafond``), où chaque ``plafond`` est lu
    depuis le ``ParametresAnnee`` réel 2026 fusionné
    (``st_parametres_annee_2026_qc_ca``) — jamais codé en dur (règle 05).
    Si le tirage produit six zéros (cas improbable mais possible), une
    catégorie choisie au hasard est forcée à son plafond pour garantir
    l'invariant « au moins une catégorie strictement positive » promis
    par le nom de cette stratégie.

    Cette stratégie exerce le plafonnement en cours de saison (Property
    4, Property 5) qui n'est **pas** couvert par le corpus golden
    QC001–QC006 (Introduction des requirements : toutes les fixtures
    sont des paies n° 1, cumul YTD nul).

    Les catégories non fiscales (``brut``, ``vacances``,
    ``impot_qc_retenu``, ``impot_federal_retenu``, ``net``) sont
    générées avec des bornes larges mais indépendantes du plafonnement
    testé — règle 01 : ``Decimal`` exclusivement pour les onze
    catégories de ``CumulsYTD``.
    """
    parametres = _charger_parametres_annee_2026_qc_ca()

    valeurs_cotisation: dict[str, Decimal] = {}
    for categorie, nom_section, nom_champ in _CATEGORIES_COTISATION_VERS_PLAFOND:
        section = getattr(parametres, nom_section)
        plafond = getattr(section, nom_champ)
        valeurs_cotisation[categorie] = draw(_st_montant_ytd_biaise_plafond(plafond))

    if all(valeur == Decimal("0.00") for valeur in valeurs_cotisation.values()):
        categorie_forcee, nom_section, nom_champ = draw(
            st.sampled_from(_CATEGORIES_COTISATION_VERS_PLAFOND)
        )
        section = getattr(parametres, nom_section)
        valeurs_cotisation[categorie_forcee] = getattr(section, nom_champ)

    return CumulsYTD(
        employe_id=draw(_st_employe_id()),
        annee_civile=draw(_st_annee_fiscale()),
        brut=draw(_st_decimal_monetaire(max_value=Decimal("50000.00"))),
        vacances=draw(_st_decimal_monetaire(max_value=Decimal("3000.00"))),
        impot_qc_retenu=draw(_st_decimal_monetaire(max_value=Decimal("10000.00"))),
        impot_federal_retenu=draw(
            _st_decimal_monetaire(max_value=Decimal("10000.00"))
        ),
        net=draw(_st_decimal_monetaire(max_value=Decimal("50000.00"))),
        **valeurs_cotisation,
    )


def st_brut_total_avec_zero() -> st.SearchStrategy[Decimal]:
    """``Decimal`` dans ``[0.00, 5000.00]``, biaisé vers ``Decimal("0.00")``.

    Design (§Testing Strategy « Stratégies Hypothesis », Property 6) :
    ``st.one_of(st.just(Decimal("0.00")), st.decimals(...))`` — poids
    fort sur le cas limite « salaire admissible nul », qui doit produire
    ``Decimal("0.00")`` sans exception pour chacune des six fonctions de
    cotisation (Property 6). Alimente ``GainsDecomposes.brut_total``
    dans les tests de cette spec (règle 01 : ``Decimal`` exclusivement).
    """
    return st.one_of(
        st.just(Decimal("0.00")),
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("5000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


def st_parametres_annee_avec_to_fill(champ: str) -> st.SearchStrategy[ParametresAnnee]:
    """``ParametresAnnee`` réel 2026 (fusion QC/CA) avec un champ à ``"TO_FILL"``.

    Design (§Testing Strategy « Stratégies Hypothesis », Property 17) :
    construit une variante du ``ParametresAnnee`` réel retourné par
    ``st_parametres_annee_2026_qc_ca()`` où un champ ciblé porte la
    sentinelle ``SENTINEL_TO_FILL`` (``"TO_FILL"``), pour vérifier que
    l'accès à la propriété correspondante lève ``MissingParameterError``
    sans être interceptée (Requirements 1.9, 12.5).

    ``champ`` : chemin ``"<section>.<nom_du_champ>"`` désignant l'un des
    champs consommés par les Requirements 12.1 à 12.3, par exemple :

    - ``"rrq.taux_cotisation_totale_employe"``,
      ``"rrq.exemption_par_periode_aux_deux_semaines_2026"``,
      ``"rrq.cotisation_max_annuelle_employe"`` ;
    - ``"rqap.taux_employe"``, ``"rqap.taux_employeur"``,
      ``"rqap.cotisation_max_employe"``, ``"rqap.cotisation_max_employeur"`` ;
    - ``"assurance_emploi.taux_employe_quebec"``,
      ``"assurance_emploi.multiplicateur_employeur"``,
      ``"assurance_emploi.cotisation_max_employe"``,
      ``"assurance_emploi.cotisation_max_employeur"``.

    Le chemin ``"<section>.<champ>"`` désambiguïse les noms de champs
    partagés entre sections (``cotisation_max_employe``/``_employeur``
    existent à la fois sur ``RQAPParametres`` et ``AEParametres``).

    Seuls la section ciblée puis la racine sont recopiées via
    ``model_copy(update=...)`` (aucune mutation de l'instance mémorisée
    par ``st_parametres_annee_2026_qc_ca`` — règle 06, immuabilité) :
    le champ brut ``"<champ>_brut"`` est celui réellement stocké par les
    sous-modèles de ``payroll_engine.parameters_loader`` (voir
    ``_ParametresSectionBase`` — chaque champ public est une propriété
    qui matérialise ``"<champ>_brut"``, alias JSON identique au nom
    public).
    """
    nom_section, nom_champ = champ.split(".", maxsplit=1)
    parametres_base = _charger_parametres_annee_2026_qc_ca()
    section_base = getattr(parametres_base, nom_section)
    section_modifiee = section_base.model_copy(
        update={f"{nom_champ}_brut": SENTINEL_TO_FILL}
    )
    parametres_modifies = parametres_base.model_copy(
        update={nom_section: section_modifiee}
    )
    return st.just(parametres_modifies)


# ===========================================================================
# Stratégies dédiées impôt retenu à la source QC et fédéral
# (design.md §Testing Strategy « Stratégies Hypothesis »,
#  spec impots-retenues-source, tâche 1.1)
# ===========================================================================

#: Bornes de génération (NON fiscales — règle 05) du crédit personnel
#: « élevé ». Ces valeurs ne sont ni un taux, ni un seuil, ni un plafond
#: officiel : ce sont de simples bornes de génération choisies pour
#: dépasser largement le revenu imposable annualisé maximal que
#: ``st_payroll_input`` peut produire (taux horaire ≤ 50 $, heures ≤ 60 h
#: par semaine, ≤ 27 périodes ⇒ revenu annualisé de l'ordre de quelques
#: centaines de milliers de dollars). En générant un crédit personnel
#: pouvant atteindre ``1 000 000,00 $``, on garantit qu'Hypothesis
#: explore régulièrement le cas où le crédit effectif dépasse le revenu
#: imposable annualisé — condition du comportement sous le seuil
#: d'imposition (Property 8) et de la défense en profondeur du
#: Requirement 12.5.
_CREDIT_PERSONNEL_ELEVE_MIN = Decimal("100000.00")
_CREDIT_PERSONNEL_ELEVE_MAX = Decimal("1000000.00")

#: Chemin d'un champ imbriqué dans un palier :
#: ``"<section>.paliers[<index>].<champ>"`` (ex. ``impot_quebec.paliers[2].taux``).
#: Le second cas de figure — un champ scalaire de section
#: (``"<section>.<champ>"``) — est traité par ``str.split`` de repli.
_PALIER_CHAMP_RE = re.compile(
    r"^(?P<section>[^.]+)\.paliers\[(?P<index>\d+)\]\.(?P<champ>[^.]+)$"
)


def st_credit_personnel_eleve() -> st.SearchStrategy[Decimal]:
    """``Decimal`` biaisé vers des crédits personnels très élevés.

    Design (§Testing Strategy « Stratégies Hypothesis ») : génère des
    valeurs destinées à ``montant_total_TP1015_3_effectif`` /
    ``montant_total_TD1_effectif`` biaisées vers des montants très élevés
    (jusqu'à plusieurs centaines de milliers de dollars), pour exercer le
    comportement sous le seuil d'imposition (Property 8) et la défense en
    profondeur du Requirement 12.5 sans dépendre du corpus golden — ce
    dernier ne couvrant que des crédits proches du montant personnel de
    base 2026.

    L'usage de ``st.one_of`` inclut explicitement les deux bornes exactes
    (``500 000,00 $`` et ``1 000 000,00 $``, voir
    ``_CREDIT_PERSONNEL_ELEVE_MAX``) afin qu'Hypothesis échantillonne
    régulièrement des crédits proches ou au-delà du revenu imposable
    annualisé maximal généré par ``st_payroll_input`` — c'est-à-dire des
    crédits qui garantissent une retenue nulle par la seule formule,
    indépendamment de l'exonération (Property 8 / Requirement 12.5).

    Règle 01 : retourne exclusivement des ``Decimal`` à deux décimales
    (``allow_nan=False``, ``allow_infinity=False``) — jamais un ``float``.
    Règle 05 : les bornes sont de simples bornes de génération, ce ne sont
    ni des taux, ni des seuils, ni des plafonds fiscaux officiels.
    """
    return st.one_of(
        st.just(_CREDIT_PERSONNEL_ELEVE_MAX),
        st.just(Decimal("500000.00")),
        st.decimals(
            min_value=_CREDIT_PERSONNEL_ELEVE_MIN,
            max_value=_CREDIT_PERSONNEL_ELEVE_MAX,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@lru_cache(maxsize=1)
def _charger_parametres_annee_2026_impot() -> ParametresAnnee:
    """Charge un ``ParametresAnnee`` 2026 fusionné incluant ``impot_federal``.

    Point de départ : l'instance mémorisée par
    ``_charger_parametres_annee_2026_qc_ca`` (racine Québec — ``rrq``,
    ``rqap``, ``impot_quebec`` — enrichie de la section
    ``assurance_emploi`` du fichier Canada). Cette fabrique y ajoute en
    plus la section ``impot_federal`` chargée depuis
    ``parameters/2026/canada.json`` via ``model_copy(update=...)`` (aucune
    mutation — règle 06, immuabilité), de sorte que l'objet résultant
    porte **à la fois** ``impot_quebec`` et ``impot_federal`` : c'est le
    socle commun requis par les variantes QC **et** fédérale de la
    Property 13.

    ``functools.lru_cache(maxsize=1)`` mémorise le résultat au niveau
    module (cohérent avec les autres fabriques de ce module) : les
    fichiers ``parameters/2026/{quebec,canada}.json`` ne sont relus qu'une
    seule fois par processus de test. ``ParametresAnnee`` est
    ``frozen=True`` — l'instance partagée ne peut pas être mutée par un
    test, ce qui rend le partage thread-safe.
    """
    parametres_qc_ca = _charger_parametres_annee_2026_qc_ca()
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    return parametres_qc_ca.model_copy(
        update={"impot_federal": parametres_ca.impot_federal}
    )


def st_parametres_annee_impot_avec_to_fill(
    champ: str,
) -> st.SearchStrategy[ParametresAnnee]:
    """``ParametresAnnee`` réel 2026 (fusion QC/CA) avec un champ impôt à ``"TO_FILL"``.

    Design (§Testing Strategy « Stratégies Hypothesis », Property 13) :
    construit une variante du ``ParametresAnnee`` réel retourné par
    ``_charger_parametres_annee_2026_impot()`` (qui porte à la fois
    ``impot_quebec`` et ``impot_federal``) où un champ ciblé côté impôt
    porte la sentinelle ``SENTINEL_TO_FILL`` (``"TO_FILL"``), pour
    vérifier que l'accès à la propriété correspondante lève
    ``MissingParameterError`` non interceptée (Requirements 1.8, 10.5).

    ``champ`` accepte deux formes :

    - **champ scalaire de section** — ``"<section>.<champ>"``, par
      exemple ``"impot_quebec.taux_credits_convertibles"``,
      ``"impot_quebec.deduction_pour_travailleur_annuelle"``,
      ``"impot_federal.taux_credits_convertibles"``,
      ``"impot_federal.montant_emploi_canadien_annuel"``,
      ``"impot_federal.plafond_cotisation_base_rrq_annuel"``,
      ``"impot_federal.taux_abattement_quebec"`` ;
    - **champ imbriqué dans un palier** —
      ``"<section>.paliers[<index>].<champ>"``, par exemple
      ``"impot_quebec.paliers[0].taux"``,
      ``"impot_quebec.paliers[1].constante_k"``,
      ``"impot_federal.paliers[0].taux"``.

    Mécanisme (identique à ``st_parametres_annee_avec_to_fill`` pour le
    cas scalaire) : le champ réellement stocké par les sous-modèles de
    ``payroll_engine.parameters_loader`` est ``"<champ>_brut"`` (chaque
    propriété publique matérialise son ``"<champ>_brut"``). Pour un champ
    de palier, le ``Palier`` ciblé est recopié via
    ``model_copy(update={f"{champ}_brut": SENTINEL_TO_FILL})``, la liste
    ``paliers`` reconstruite, puis la section et enfin la racine recopiées
    — aucune mutation de l'instance mémorisée (règle 06, immuabilité).

    Ordonnancement (règle 06 — tests avant code) : les propriétés typées
    ``Palier.taux`` / ``.constante_k`` / ``.seuil_bas_annuel`` et les
    attributs ``*_brut`` des sections impôt ne sont matérialisés qu'à
    partir de la tâche 7.2. Cette stratégie est écrite en amont, contre la
    structure cible décrite dans le design (§Data Models « Nouveau
    sous-modèle partagé Palier », « Extension de ImpotQCParametres /
    ImpotFederalParametres »). Son corps ne s'exécute qu'à l'appel (jamais
    à l'import) : l'import de ce module reste donc sûr, et l'invocation de
    cette stratégie peut légitimement lever ``AttributeError`` tant que la
    tâche 7.2 n'a pas typé les paliers — comportement attendu.

    Règle 01 : la sentinelle ``"TO_FILL"`` reste une chaîne ; aucune
    valeur monétaire ``float`` n'est introduite.
    """
    parametres_base = _charger_parametres_annee_2026_impot()

    match_palier = _PALIER_CHAMP_RE.match(champ)
    if match_palier is not None:
        nom_section = match_palier.group("section")
        index = int(match_palier.group("index"))
        nom_champ = match_palier.group("champ")
        section_base = getattr(parametres_base, nom_section)
        paliers = list(section_base.paliers)
        palier_cible = paliers[index]
        palier_modifie = palier_cible.model_copy(
            update={f"{nom_champ}_brut": SENTINEL_TO_FILL}
        )
        paliers[index] = palier_modifie
        section_modifiee = section_base.model_copy(
            update={"paliers": tuple(paliers)}
        )
    else:
        nom_section, nom_champ = champ.split(".", maxsplit=1)
        section_base = getattr(parametres_base, nom_section)
        section_modifiee = section_base.model_copy(
            update={f"{nom_champ}_brut": SENTINEL_TO_FILL}
        )

    parametres_modifies = parametres_base.model_copy(
        update={nom_section: section_modifiee}
    )
    return st.just(parametres_modifies)


# ===========================================================================
# Stratégies dédiées charges patronales FSS, CNESST, CNT
# (design.md §Testing Strategy « Stratégies Hypothesis »,
#  spec charges-patronales, tâche 1.1)
# ===========================================================================

#: Borne haute de ``brut_total`` pour les property tests des charges
#: patronales. Choisie très au-dessus de la base admissible CNT/CNESST de
#: ``103 000 $`` afin qu'Hypothesis exerce régulièrement l'absence de
#: plafond (Property 8) : au-delà de ce seuil, chaque montant doit rester
#: ``arrondir(taux × brut_total)`` sans plafonnement. Règle 05 : ce n'est ni
#: un taux, ni un seuil, ni un plafond fiscal officiel — c'est une simple
#: borne de génération de test.
_BRUT_TOTAL_CHARGES_MAX = Decimal("200000.00")

#: Seuil « grande valeur » (> base admissible ``103 000 $``) au-delà duquel
#: on veut biaiser une partie des tirages, pour couvrir l'absence de plafond
#: (Property 8). Borne de génération de test uniquement (règle 05).
_BRUT_TOTAL_CHARGES_GRAND_MIN = Decimal("103000.01")


def st_brut_total_avec_zero_et_grands() -> st.SearchStrategy[Decimal]:
    """``Decimal`` ∈ [0.00, 200000.00], biaisé vers 0 et vers de grandes valeurs.

    Design (§Testing Strategy « Stratégies Hypothesis », spec
    ``charges-patronales``) : ``st.one_of(st.just(Decimal("0.00")),
    st.decimals(...))`` sur ``[Decimal("0.00"), Decimal("200000.00")]``
    avec ``places=2``, doublement biaisé :

    - vers ``Decimal("0.00")`` exactement (branche ``st.just``), cas limite
      « salaire assujetti nul » qui doit produire ``Decimal("0.00")`` sans
      exception pour chacune des trois fonctions de charges (Property 4) ;
    - vers de grandes valeurs strictement supérieures à la base admissible
      de ``103 000 $`` (branche dédiée ``[103000.01, 200000.00]``), pour
      exercer l'absence de plafond annuel : au-delà du seuil, chaque montant
      doit rester ``arrondir(taux × brut_total)`` sans plafonnement
      (Property 8).

    La troisième branche couvre uniformément toute la plage ``[0, 200000]``
    afin de ne pas laisser de trou entre les deux biais.

    Alimente ``GainsDecomposes.brut_total`` dans les tests de la spec
    ``charges-patronales`` (le test compose un ``GainsDecomposes`` valide
    autour de cette valeur). Règle 01 : ``Decimal`` exclusivement
    (``allow_nan=False``, ``allow_infinity=False``), jamais un ``float``.
    """
    return st.one_of(
        st.just(Decimal("0.00")),
        st.decimals(
            min_value=_BRUT_TOTAL_CHARGES_GRAND_MIN,
            max_value=_BRUT_TOTAL_CHARGES_MAX,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=_BRUT_TOTAL_CHARGES_MAX,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def st_parametres_annee_variantes_non_consommees(
    draw: st.DrawFn,
) -> ParametresAnnee:
    """``ParametresAnnee`` 2026 Québec variant sur les seuls champs non consommés.

    Design (§Testing Strategy « Stratégies Hypothesis », spec
    ``charges-patronales``) : produit une variante du ``ParametresAnnee``
    réel 2026 Québec (``st_parametres_annee_2026_qc()``) qui diffère
    **exclusivement** sur les champs que le calcul de période n'utilise
    jamais, en laissant intacts les seuls champs consommés par les formules
    (``fss.taux_camp_lilyso_2026``, ``cnesst.taux_total``, ``cnt.taux``).
    Champs non consommés variés :

    - ``fss.masse_salariale_utilisee_webras_2026`` (documentaire) ;
    - ``fss.table_taux_par_masse_salariale`` (table hors périmètre, absorbée
      par ``extra="allow"``) ;
    - ``cnt.base_admissible`` (portée dans la trace, jamais appliquée comme
      plafond — Property 8) ;
    - ``cnesst.en_attente_classification`` (drapeau reporté sans effet sur le
      total — Property 11) ;
    - ``cnesst.taux_unite`` / ``cnesst.taux_cni`` (sous-taux documentaires,
      seul ``taux_total`` est consommé).

    Sert à démontrer, sur une plage de variantes, que le montant FSS ne
    dépend ni de la masse salariale documentaire ni de la table, que le
    montant CNESST ne dépend ni du drapeau ni des sous-taux, et que le
    montant CNT ne dépend pas de la base admissible (Property 8), et que le
    total des cotisations employeur est identique que le drapeau CNESST
    vaille ``True`` ou ``False`` (Property 11).

    Immuabilité (règle 06) : l'instance mémorisée par
    ``st_parametres_annee_2026_qc()`` n'est **jamais** mutée. Chaque section
    modifiée est reconstruite via ``model_validate`` sur son ``model_dump``
    (les champs consommés y sont recopiés à l'identique, les champs non
    consommés remplacés par les valeurs tirées), puis la racine est recopiée
    via ``model_copy(update=...)``. La reconstruction par ``model_dump`` /
    ``model_validate`` n'accède à aucune propriété matérialisée : les
    éventuels champs ``"TO_FILL"`` non consommés restent des chaînes et ne
    lèvent pas ``MissingParameterError`` à la génération.

    Règle 01 : tous les montants tirés sont des ``Decimal`` (jamais un
    ``float``). Règle 05 : les valeurs variées sont de simples valeurs de
    génération de test — aucune ne redéfinit un paramètre fiscal consommé.
    """
    base = _charger_parametres_annee_2026_qc()

    # --- Champs FSS non consommés ---
    nouvelle_masse = draw(
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("5000000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    nouvelle_table = draw(
        st.sampled_from([SENTINEL_TO_FILL, "table_variante_A", "table_variante_B"])
    )
    section_fss = type(base.fss).model_validate(
        {
            **base.fss.model_dump(by_alias=True),
            "masse_salariale_utilisee_webras_2026": nouvelle_masse,
            "table_taux_par_masse_salariale": nouvelle_table,
        }
    )

    # --- Champs CNESST non consommés (drapeau + sous-taux) ---
    nouveau_drapeau = draw(st.booleans())
    nouveau_taux_unite = draw(
        st.decimals(
            min_value=Decimal("0.0000"),
            max_value=Decimal("0.0500"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    nouveau_taux_cni = draw(
        st.decimals(
            min_value=Decimal("0.0000"),
            max_value=Decimal("0.0500"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    section_cnesst = type(base.cnesst).model_validate(
        {
            **base.cnesst.model_dump(by_alias=True),
            "en_attente_classification": nouveau_drapeau,
            "taux_unite": nouveau_taux_unite,
            "taux_cni": nouveau_taux_cni,
        }
    )

    # --- Champ CNT non consommé (base admissible, jamais un plafond) ---
    nouvelle_base_admissible = draw(
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("500000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    section_cnt = type(base.cnt).model_validate(
        {
            **base.cnt.model_dump(by_alias=True),
            "base_admissible": nouvelle_base_admissible,
        }
    )

    return base.model_copy(
        update={"fss": section_fss, "cnesst": section_cnesst, "cnt": section_cnt}
    )
