"""Property tests et tests d'exemple pour `calcul_rrq_employe`/`calcul_rrq_employeur`.

Spec de référence : ``cotisations-sociales-qc`` — tâche 2.1 (squelette et
tests transversaux).
Design de référence : ``design.md`` §Testing Strategy, §Correctness
Properties 1, 2, 3, 4, 5, 6, 7, 9, 13, 14, 15, 16, 17 et §Components §1,
§2, §3.

Ce fichier porte l'ensemble des property tests et tests d'exemple du
module ``payroll_engine/rrq.py`` (``calcul_rrq_employe``,
``calcul_rrq_employeur``). La tâche 2.1 pose le squelette : les imports,
la fixture des paramètres annuels réels 2026 (Québec + Canada fusionnés)
et les tests **transversaux** (classe ``TestSignaturePureteRobustesse``)
qui s'appliquent identiquement aux deux fonctions RRQ. Les tâches 2.2 à
2.5 ajouteront respectivement :

- ``TestFormuleEtPlafonnementRrqEmploye`` — Property 4, 5, 6, 7 (tâche 2.2) ;
- ``TestEgaliteRrqEmployeur`` — Property 9 (tâche 2.3) ;
- ``TestTraceRrq`` — Property 13, 14, 15, 16 (tâche 2.4) ;
- ``TestMissingParameterRrq`` — Property 17 (tâche 2.5).

Propriétés couvertes par **cette** tâche (2.1), voir design.md
§Correctness Properties :

1. **Property 1 — Déterminisme (pureté)** : deux appels à
   ``calcul_rrq_employe`` (et ``calcul_rrq_employeur``) avec les mêmes
   arguments produisent deux tuples égaux au sens ``==``.
2. **Property 2 — Absence d'exception sur entrée valide** : aucun rejet
   pour tout ``PayrollInput``/``GainsDecomposes``/``ParametresAnnee``
   valides, y compris les cas extrêmes (salaire admissible nul, cumul
   YTD nul ou proche du plafond, salaire très élevé).
3. **Property 3 — Forme ``Decimal`` du résultat et de la trace** : le
   montant retourné et chaque valeur des dictionnaires de trace sont des
   ``Decimal`` finis ; le montant retourné et ``trace.resultat`` sont en
   outre arrondis à deux décimales ``ROUND_HALF_UP``.

**Limitation héritée du corpus golden** (Introduction des requirements,
design §Testing Strategy) : les six scénarios QC001–QC006 sont tous des
paies n° 1 de la saison — cumul YTD de départ nul pour les six
catégories de cotisation. Le corpus golden ne valide donc **jamais**
directement le plafonnement en cours de saison (cumul YTD non nul) : ce
comportement n'est couvert que par les property tests de ce fichier,
via la stratégie ``st_cumuls_ytd_non_nuls()`` (biaisée vers le plafond
annuel exact).

Discipline règle 06 (TDD — tests avant code) : ``payroll_engine/rrq.py``
n'existe **pas encore** à ce stade. Contrairement au squelette de
``test_gains_bruts.py`` (spec ``gains-bruts-vacances-hs``, tâche 1.2) qui
retardait l'import du module cible à l'intérieur de chaque test pour
rester collectable, ce fichier importe ``calcul_rrq_employe`` et
``calcul_rrq_employeur`` **au niveau module** : la collecte pytest de ce
fichier échoue donc actuellement avec ``ModuleNotFoundError`` sur
``payroll_engine.rrq`` — c'est le comportement **attendu et correct**
tant que la tâche 9.1 (implémentation) n'a pas été réalisée (checkpoint
de la tâche 5 du plan).

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison.
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction, ModeArrondissement
from models.exceptions import MissingParameterError
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_result import GainsDecomposes
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters
from payroll_engine.rrq import calcul_rrq_employe, calcul_rrq_employeur
from tests.strategies import (
    st_brut_total_avec_zero,
    st_cumuls_ytd_non_nuls,
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_avec_to_fill,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_gains_bruts.py)
# ---------------------------------------------------------------------------

# Le nombre d'exemples est piloté par le profil Hypothesis actif
# (voir ``tests/conftest.py`` : dev=15 par défaut, ci=100).
settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Helpers internes de génération — combinent les stratégies de
# tests/strategies.py pour produire des entrées couvrant le plafonnement
# en cours de saison (cumul YTD non nul) et les cas extrêmes de salaire
# admissible (nul ou très élevé), non couverts par le corpus golden.
# ---------------------------------------------------------------------------


@st.composite
def _st_payroll_input_avec_cumuls_non_nuls(draw: st.DrawFn) -> PayrollInput:
    """``PayrollInput`` dont ``cumuls_debut`` peut être non nul.

    Combine ``st_payroll_input()`` (cumuls neutres par construction) avec
    ``st_cumuls_ytd_non_nuls()`` (au moins une catégorie strictement
    positive, biaisée vers le plafond annuel exact — design §Testing
    Strategy). L'appariement ``(employe_id, annee_civile)`` exigé par le
    contrat ``PayrollInput`` (règle du modèle amont) est préservé en
    recopiant les deux identifiants du ``PayrollInput`` de base sur le
    ``CumulsYTD`` généré, via ``model_copy(update=...)`` (aucune mutation
    — règle 06, immuabilité).
    """
    payroll_input = draw(st_payroll_input())
    cumuls_generes = draw(st_cumuls_ytd_non_nuls())
    cumuls_ajustes = cumuls_generes.model_copy(
        update={
            "employe_id": payroll_input.employee.id,
            "annee_civile": payroll_input.pay_period.annee_fiscale,
        }
    )
    return payroll_input.model_copy(update={"cumuls_debut": cumuls_ajustes})


def _st_brut_total_eleve() -> st.SearchStrategy[Decimal]:
    """``Decimal`` élevé (``]5000.00, 1000000.00]``), deux décimales.

    Complète ``st_brut_total_avec_zero()`` (bornée à ``5000.00``) pour
    exercer le cas « salaire admissible très élevé » exigé par Property 2
    (design §Correctness Properties 2), notamment le plafonnement complet
    de la cotisation RRQ employé une fois le MGA atteint.
    """
    return st.decimals(
        min_value=Decimal("5000.01"),
        max_value=Decimal("1000000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


def _construire_gains_decomposes(brut_total: Decimal) -> GainsDecomposes:
    """``GainsDecomposes`` valide, minimal, pour un ``brut_total`` donné.

    Seul ``brut_total`` importe pour les six fonctions de cotisations
    sociales (Req 1.6 — lecture exclusive de ``gains.brut_total``) ; les
    autres composantes du brut sont mises à zéro pour ne pas introduire
    de bruit hors du périmètre de cette spec. ``multiplicateur_heures_supp``
    et ``seuil_heures_supp_hebdo`` sont des valeurs de contexte portées
    par contrat (``gt=0``) mais non consommées par le Moteur_Cotisations
    — les valeurs ``1.5``/``40`` ne sont pas des paramètres fiscaux au
    sens de la règle 05, seulement des valeurs de forme requises par
    ``GainsDecomposes``.
    """
    return GainsDecomposes(
        salaire_regulier=brut_total,
        heures_supplementaires_montant=Decimal("0.00"),
        vacances=Decimal("0.00"),
        jours_feries_manuels=Decimal("0.00"),
        brut_total=brut_total,
        multiplicateur_heures_supp=Decimal("1.5"),
        seuil_heures_supp_hebdo=Decimal("40"),
    )


@st.composite
def _st_entrees_completes(draw: st.DrawFn) -> tuple[PayrollInput, GainsDecomposes]:
    """``(PayrollInput, GainsDecomposes)`` couvrant les cas extrêmes de
    Property 2 : cumul YTD nul ou proche du plafond
    (``_st_payroll_input_avec_cumuls_non_nuls``), salaire admissible nul
    ou très élevé (``st_brut_total_avec_zero`` / ``_st_brut_total_eleve``).
    """
    payroll_input = draw(_st_payroll_input_avec_cumuls_non_nuls())
    brut_total = draw(st.one_of(st_brut_total_avec_zero(), _st_brut_total_eleve()))
    gains = _construire_gains_decomposes(brut_total)
    return payroll_input, gains


def _verifier_property_3_forme_decimal(montant: Decimal, trace: CalculationTrace) -> None:
    """Vérifie Property 3 (design §Correctness Properties 3) pour un
    couple ``(montant, trace)`` retourné par une des six fonctions.

    - Chaque valeur de ``trace.parametres_utilises``/``entrees``/
      ``sous_totaux``, plus ``montant`` et ``trace.resultat`` eux-mêmes,
      est un ``Decimal`` fini (``isinstance`` + ``is_finite()``).
    - ``montant`` et ``trace.resultat`` sont en outre arrondis à deux
      décimales selon ``ROUND_HALF_UP``.
    """
    valeurs_a_verifier: list[Decimal] = [montant, trace.resultat]
    valeurs_a_verifier.extend(trace.parametres_utilises.values())
    valeurs_a_verifier.extend(trace.entrees.values())
    valeurs_a_verifier.extend(trace.sous_totaux.values())

    for valeur in valeurs_a_verifier:
        assert isinstance(valeur, Decimal), f"Valeur non-Decimal détectée : {valeur!r}"
        assert valeur.is_finite(), f"Valeur Decimal non finie détectée : {valeur!r}"

    assert montant == montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert trace.resultat == trace.resultat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 2.1 — Signature, pureté et robustesse (Property 1, 2, 3)
# ---------------------------------------------------------------------------


class TestSignaturePureteRobustesse:
    """Property 1, 2, 3 — déterminisme, absence d'exception, forme `Decimal`.

    Design (§Correctness Properties 1, 2, 3 ; §Components §1 « Signatures
    exactes »). Ces trois propriétés s'appliquent identiquement à
    `calcul_rrq_employe` et `calcul_rrq_employeur`, plus un test
    d'exemple vérifiant l'absence d'effet de bord à l'import (Req 1.10).
    """

    # Feature: cotisations-sociales-qc, Property 1: Déterminisme (pureté)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_1_deux_appels_identiques_produisent_des_tuples_egaux(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, `calcul_rrq_employe(pi, g, p) ==
        calcul_rrq_employe(pi, g, p)` et de même pour
        `calcul_rrq_employeur` : deux appels avec les mêmes arguments
        produisent deux tuples égaux au sens `==` sur les deux
        composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.4**
        """
        payroll_input, gains = entrees

        resultat_employe_1 = calcul_rrq_employe(payroll_input, gains, parametres_annee)
        resultat_employe_2 = calcul_rrq_employe(payroll_input, gains, parametres_annee)
        assert resultat_employe_1 == resultat_employe_2
        assert resultat_employe_1[0] == resultat_employe_2[0]
        assert resultat_employe_1[1] == resultat_employe_2[1]

        resultat_employeur_1 = calcul_rrq_employeur(payroll_input, gains, parametres_annee)
        resultat_employeur_2 = calcul_rrq_employeur(payroll_input, gains, parametres_annee)
        assert resultat_employeur_1 == resultat_employeur_2
        assert resultat_employeur_1[0] == resultat_employeur_2[0]
        assert resultat_employeur_1[1] == resultat_employeur_2[1]

    # Feature: cotisations-sociales-qc, Property 2: Absence d'exception sur entrée valide
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_2_aucune_exception_sur_entree_valide(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides — y compris les cas extrêmes (salaire
        admissible nul, cumul YTD nul ou proche du plafond, salaire très
        élevé) — `calcul_rrq_employe` et `calcul_rrq_employeur`
        retournent un tuple sans lever aucune exception.

        **Validates: Requirements 1.9, 14.1**
        """
        payroll_input, gains = entrees

        resultat_employe = calcul_rrq_employe(payroll_input, gains, parametres_annee)
        resultat_employeur = calcul_rrq_employeur(payroll_input, gains, parametres_annee)

        assert resultat_employe is not None
        assert resultat_employeur is not None

    # Feature: cotisations-sociales-qc, Property 3: Forme Decimal du résultat et de la trace
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_3_forme_decimal_du_resultat_et_de_la_trace(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, le montant retourné et chaque valeur
        de `trace.parametres_utilises`/`entrees`/`sous_totaux`/`resultat`
        sont des `Decimal` finis ; le montant retourné et `trace.resultat`
        sont en outre arrondis à deux décimales `ROUND_HALF_UP`.

        **Validates: Requirements 2.7, 3.4, 11.7**
        """
        payroll_input, gains = entrees

        montant_employe, trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )
        _verifier_property_3_forme_decimal(montant_employe, trace_employe)

        montant_employeur, trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )
        _verifier_property_3_forme_decimal(montant_employeur, trace_employeur)

    def test_import_calcul_rrq_sans_effet_de_bord(self, capsys) -> None:
        """Test d'exemple — `from payroll_engine.rrq import
        calcul_rrq_employe, calcul_rrq_employeur` ne produit **aucun
        effet de bord** (Req 1.10) : pas d'ouverture de fichier, pas
        d'appel réseau, pas d'écriture sur `stdout` / `stderr`.

        Design (§Architecture « Contrainte de pureté »). Le module est
        retiré de `sys.modules` avant l'import (s'il y était déjà chargé
        par un import précédent) afin de forcer une exécution fraîche du
        corps du module — c'est justement à ce moment-là qu'un éventuel
        effet de bord au niveau module se manifesterait.
        """
        import importlib

        nom_module = "payroll_engine.rrq"
        sys.modules.pop(nom_module, None)

        module = importlib.import_module(nom_module)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert nom_module in sys.modules
        assert hasattr(module, "calcul_rrq_employe")
        assert hasattr(module, "calcul_rrq_employeur")


# ---------------------------------------------------------------------------
# 2.2 — Formule de l'assiette cotisable et plafonnement RRQ employé
# (Property 4, 5, 6, 7 — variantes RRQ employé)
# ---------------------------------------------------------------------------


@st.composite
def _st_entrees_rrq_employe_cumul_au_plafond_ou_au_dela(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """`(PayrollInput, GainsDecomposes, ParametresAnnee)` dont
    `cumuls_debut.rrq_employe` >= plafond annuel RRQ employé.

    Design (§Correctness Properties 5) : « si `cumul_ytd_correspondant >=
    plafond_annuel_correspondant`, alors la fonction retourne
    `Decimal("0.00")` [...] quel que soit le `Salaire_Admissible` de la
    période ». Part de `_st_entrees_completes()` (mêmes bornes de
    `brut_total`, cas extrêmes inclus) puis **remplace**
    `cumuls_debut.rrq_employe` par `plafond + surplus` — `surplus`
    biaisé vers `Decimal("0.00")` pour couvrir à la fois le cas limite
    « cumul exactement au plafond » et le cas « cumul au-delà du
    plafond ». `CumulsYTD`/`PayrollInput` étant `frozen=True`, le
    remplacement passe par `model_copy(update=...)`, sans mutation
    (règle 06). Le plafond est lu depuis le `ParametresAnnee` réel 2026
    mémorisé (`st_parametres_annee_2026_qc_ca`), jamais codé en dur
    (règle 05). `ParametresAnnee` est retourné avec le tuple pour que
    le test appelant n'ait pas besoin de le recharger séparément.
    """
    payroll_input, gains = draw(_st_entrees_completes())
    parametres_annee = draw(st_parametres_annee_2026_qc_ca())
    plafond = parametres_annee.rrq.cotisation_max_annuelle_employe
    surplus = draw(
        st.one_of(
            st.just(Decimal("0.00")),
            st.decimals(
                min_value=Decimal("0.00"),
                max_value=Decimal("500.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    cumuls_ajustes = payroll_input.cumuls_debut.model_copy(
        update={"rrq_employe": plafond + surplus}
    )
    payroll_input_ajuste = payroll_input.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )
    return payroll_input_ajuste, gains, parametres_annee


@st.composite
def _st_entrees_rrq_employe_avec_brut_nul(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes]:
    """`(PayrollInput, GainsDecomposes)` dont `gains.brut_total ==
    Decimal("0.00")`.

    Design (§Correctness Properties 6) : « *for any* `PayrollInput`,
    `GainsDecomposes` avec `brut_total == Decimal("0.00")` [...] retourne
    `Decimal("0.00")` sans lever d'exception ». Réutilise
    `_st_entrees_completes()` pour `payroll_input` (y compris un
    `cumuls_debut.rrq_employe` potentiellement non nul, quel qu'il soit —
    la propriété doit tenir « quel que soit le `Salaire_Admissible` »,
    donc indépendamment de l'état du cumul), mais reconstruit `gains`
    avec `brut_total = Decimal("0.00")` via `_construire_gains_decomposes`.
    """
    payroll_input, _gains_non_utilises = draw(_st_entrees_completes())
    gains = _construire_gains_decomposes(Decimal("0.00"))
    return payroll_input, gains


def _payroll_input_deterministe_pour_exemple() -> PayrollInput:
    """`PayrollInput` valide et déterministe (test d'exemple, Property 7).

    Contrairement aux tests `@given` de cette classe (qui tirent leur
    `PayrollInput` via `_st_entrees_completes()`), le test d'exemple de
    la formule RRQ n'a besoin que d'une seule instance fixe,
    déterministe et anonymisée (règle 04) — à l'image de
    `_payroll_input_valide_pour_exemple` de
    `tests/payroll_engine/test_gains_bruts.py`. Aucun `float` (règle
    01) : tous les montants et taux sont construits depuis des
    `Decimal`.
    """
    date_debut = date(2026, 6, 1)
    date_fin = date(2026, 6, 14)

    employee = Employee(
        id="EMP001",
        nom_affichage="Employe Test EMP001",
        date_naissance=date(2005, 6, 15),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Moniteur",
        taux_horaire_base=Decimal("15.75"),
        date_embauche=date_debut,
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("0.00"),
        montant_total_TD1=Decimal("0.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )
    semaine_0 = WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=Decimal("0.00"),
        heures_supplementaires=Decimal("0.00"),
    )
    semaine_1 = WeekSegment(
        date_debut=date_debut + timedelta(days=7),
        date_fin=date_fin,
        heures_normales=Decimal("0.00"),
        heures_supplementaires=Decimal("0.00"),
    )
    pay_period = PayPeriod(
        numero_periode=1,
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_fin + timedelta(days=3),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=27,
        annee_fiscale=2026,
        semaines=(semaine_0, semaine_1),
    )
    heures_par_semaine = (
        HeuresParSemaine(
            heures_normales=Decimal("0.00"), heures_supplementaires=Decimal("0.00")
        ),
        HeuresParSemaine(
            heures_normales=Decimal("0.00"), heures_supplementaires=Decimal("0.00")
        ),
    )
    cumuls_debut = CumulsYTD.zero(employe_id="EMP001", annee_civile=2026)
    return PayrollInput(
        employee=employee,
        pay_period=pay_period,
        heures_par_semaine=heures_par_semaine,
        taux_horaire_effectif=Decimal("15.75"),
        taux_vacances=Decimal("0.04"),
        jours_feries_manuels=Decimal("0.00"),
        montant_total_TP1015_3_effectif=Decimal("0.00"),
        exoneration_TP1015_3_effectif=False,
        retenue_additionnelle_QC_effective=Decimal("0.00"),
        montant_total_TD1_effectif=Decimal("0.00"),
        exoneration_TD1_effective=False,
        retenue_additionnelle_federale_effective=Decimal("0.00"),
        cumuls_debut=cumuls_debut,
    )


class TestFormuleEtPlafonnementRrqEmploye:
    """Property 4, 5, 6, 7 (variantes RRQ employé) — formule de l'assiette
    cotisable, bornes générales, plancher à zéro au plafond, zéro sur
    salaire nul.

    Design (§Correctness Properties 4, 5, 6, 7 ; §Components §2). Cette
    classe couvre exclusivement `calcul_rrq_employe` — l'égalité
    structurelle avec `calcul_rrq_employeur` est couverte par la tâche
    2.3 (`TestEgaliteRrqEmployeur`, Property 9).
    """

    # Feature: cotisations-sociales-qc, Property 7: Formule de l'assiette cotisable RRQ
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_7_formule_assiette_cotisable_rrq(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, le montant théorique de période de
        `calcul_rrq_employe` est égal à `arrondir(taux_cotisation_totale_employe
        × max(Decimal("0.00"), brut_total − exemption_par_periode))` —
        l'exemption est toujours soustraite avant application du taux et
        l'assiette ne devient jamais négative. La cotisation effective
        retournée est alors exactement `min(montant_periode,
        marge_disponible)`, `marge_disponible` étant recalculée à partir
        des mêmes entrées (`payroll_input`, `parametres_annee`) — cette
        égalité relie directement la formule théorique au résultat
        observable de la fonction.

        **Validates: Requirements 2.1, 2.2**
        """
        payroll_input, gains = entrees

        cotisation, trace = calcul_rrq_employe(payroll_input, gains, parametres_annee)

        exemption_periode = (
            parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
        )
        assiette_cotisable_attendue = max(
            Decimal("0.00"), gains.brut_total - exemption_periode
        )
        montant_periode_attendu = (
            parametres_annee.rrq.taux_cotisation_totale_employe
            * assiette_cotisable_attendue
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert trace.sous_totaux["exemption_periode"] == exemption_periode
        assert trace.sous_totaux["assiette_cotisable"] == assiette_cotisable_attendue
        assert assiette_cotisable_attendue >= Decimal("0.00")

        plafond_annuel = parametres_annee.rrq.cotisation_max_annuelle_employe
        cumul_ytd = payroll_input.cumuls_debut.rrq_employe
        marge_disponible = max(Decimal("0.00"), plafond_annuel - cumul_ytd)

        assert cotisation == min(montant_periode_attendu, marge_disponible)

    # Feature: cotisations-sociales-qc, Property 4: Bornes générales (RRQ employé)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_4_bornes_generales_rrq_employe(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, la cotisation RRQ employé effective
        satisfait `Decimal("0.00") <= cotisation <= montant_periode`
        (montant théorique de période, recalculé depuis
        `trace.sous_totaux["assiette_cotisable"]` et
        `taux_cotisation_totale_employe`) et `Cumul_YTD_RRQ_Employe +
        cotisation <= Plafond_Annuel_RRQ_Employe`.

        **Validates: Requirements 2.3, 2.8, 14.4**
        """
        payroll_input, gains = entrees

        cotisation, trace = calcul_rrq_employe(payroll_input, gains, parametres_annee)

        montant_periode = (
            parametres_annee.rrq.taux_cotisation_totale_employe
            * trace.sous_totaux["assiette_cotisable"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cumul_ytd = payroll_input.cumuls_debut.rrq_employe
        plafond_annuel = parametres_annee.rrq.cotisation_max_annuelle_employe

        assert Decimal("0.00") <= cotisation <= montant_periode
        assert cumul_ytd + cotisation <= plafond_annuel

    # Feature: cotisations-sociales-qc, Property 5: Plancher à zéro quand cumul >= plafond (RRQ employé)
    @pytest.mark.property
    @given(entrees=_st_entrees_rrq_employe_cumul_au_plafond_ou_au_dela())
    @settings_large_input
    def test_property_5_plancher_zero_quand_cumul_au_plafond_ou_au_dela_rrq_employe(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput` dont `Cumul_YTD_RRQ_Employe >=
        Plafond_Annuel_RRQ_Employe`, `calcul_rrq_employe` retourne
        `Decimal("0.00")` sans lever d'exception, quel que soit le
        `Salaire_Admissible` de la période.

        **Validates: Requirements 2.6**
        """
        payroll_input, gains, parametres_annee = entrees
        assert (
            payroll_input.cumuls_debut.rrq_employe
            >= parametres_annee.rrq.cotisation_max_annuelle_employe
        )

        cotisation, _ = calcul_rrq_employe(payroll_input, gains, parametres_annee)

        assert cotisation == Decimal("0.00")

    # Feature: cotisations-sociales-qc, Property 6: Zéro sur salaire nul (RRQ employé)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_rrq_employe_avec_brut_nul(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_6_zero_sur_salaire_nul_rrq_employe(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `ParametresAnnee` valides, et
        `GainsDecomposes` avec `brut_total == Decimal("0.00")`,
        `calcul_rrq_employe` retourne `Decimal("0.00")` sans lever
        d'exception — indépendamment de l'état de
        `cumuls_debut.rrq_employe`.

        **Validates: Requirements 2.5**
        """
        payroll_input, gains = entrees
        assert gains.brut_total == Decimal("0.00")

        cotisation, _ = calcul_rrq_employe(payroll_input, gains, parametres_annee)

        assert cotisation == Decimal("0.00")

    def test_exemple_salaire_admissible_sous_exemption_produit_cotisation_nulle(
        self,
    ) -> None:
        """Test d'exemple — `Salaire_Admissible <= Exemption_Par_Periode_RRQ`
        produit une cotisation `Decimal("0.00")` sans exception (Req
        2.4). Utilise `Salaire_Admissible ==
        Exemption_Par_Periode_RRQ` exactement (cas limite) : l'assiette
        cotisable est alors nulle par construction (`max(0, 0)`).
        """
        parametres_annee = load_parameters(2026, Juridiction.QUEBEC)
        exemption_periode = (
            parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
        )
        payroll_input = _payroll_input_deterministe_pour_exemple()
        gains = _construire_gains_decomposes(exemption_periode)

        cotisation, trace = calcul_rrq_employe(payroll_input, gains, parametres_annee)

        assert cotisation == Decimal("0.00")
        assert trace.sous_totaux["assiette_cotisable"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# 2.3 — Égalité structurelle RRQ employeur = RRQ employé (Property 9)
# ---------------------------------------------------------------------------


class TestEgaliteRrqEmployeur:
    """Property 9 — égalité structurelle RRQ employeur = RRQ employé.

    Design (§Correctness Properties 9 ; §Components §3). `RRQParametres`
    ne définit aucun champ `cotisation_max_annuelle_employeur` (règle
    05, requirement 3.2) : `calcul_rrq_employeur` NE DOIT appliquer
    aucun plafond, cumul ni taux distinct côté employeur — la
    délégation à `calcul_rrq_employe` est **structurelle**, pas
    seulement numériquement égale par coïncidence des taux 2026.
    """

    # Feature: cotisations-sociales-qc, Property 9: Égalité structurelle RRQ employeur = RRQ employé
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_9_egalite_structurelle_rrq_employeur_egale_rrq_employe(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides — y compris les cas extrêmes de cumul
        YTD non nul (proche ou au-delà du plafond RRQ employé) et de
        salaire admissible (nul ou très élevé) —
        `calcul_rrq_employeur(pi, g, p)[0] ==
        calcul_rrq_employe(pi, g, p)[0]` : égalité stricte sur le
        montant retourné, aucun plafond, cumul ni taux distinct
        n'existant côté employeur (Req 3.1, 3.2).

        **Validates: Requirements 3.1, 3.2**
        """
        payroll_input, gains = entrees

        montant_employe, _trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )
        montant_employeur, _trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )

        assert montant_employeur == montant_employe

    def test_exemple_rrq_parametres_ne_possede_pas_cotisation_max_annuelle_employeur(
        self,
    ) -> None:
        """Test d'exemple — `RRQParametres` (paramètres réels 2026) ne
        possède **aucun** champ `cotisation_max_annuelle_employeur`
        (Req 3.2). `calcul_rrq_employeur` ne DOIT donc jamais tenter de
        lire un tel champ — sa délégation stricte à
        `calcul_rrq_employe` (aucun plafond, cumul ni taux distinct
        côté employeur) le rend structurellement impossible d'y
        accéder, ce que ce test vérifie explicitement : l'absence du
        champ ne provoque aucune `AttributeError` masquée puisque
        `calcul_rrq_employeur` retourne un résultat valide malgré cette
        absence.
        """
        parametres_annee = load_parameters(2026, Juridiction.QUEBEC)

        assert not hasattr(parametres_annee.rrq, "cotisation_max_annuelle_employeur")

        payroll_input = _payroll_input_deterministe_pour_exemple()
        gains = _construire_gains_decomposes(Decimal("1000.00"))

        montant_employeur, trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )
        montant_employe, _trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )

        assert montant_employeur == montant_employe
        assert montant_employeur is not None
        assert trace_employeur is not None


# ---------------------------------------------------------------------------
# 2.4 — Trace RRQ employé et employeur (Property 13, 14, 15, 16)
# ---------------------------------------------------------------------------


class TestTraceRrq:
    """Property 13, 14, 15, 16 — conformité, contenu minimal, cohérence et
    auto-suffisance de la `CalculationTrace` RRQ (employé et employeur).

    Design (§Correctness Properties 13, 14, 15, 16 ; §Components §2, §3).
    Les quatre propriétés s'appliquent aux deux fonctions
    `calcul_rrq_employe` et `calcul_rrq_employeur` — seule Property 13
    (via `section`) distingue explicitement les deux côtés. Les
    vérifications de contenu (Property 14) portent sur des **inclusions**
    (« contient au moins ») plutôt que sur une égalité stricte
    d'ensemble de clés, conformément à la formulation du design
    (« la trace [...] contient dans `parametres_utilises` au moins
    [...] »), afin de ne pas sur-contraindre le nommage exact des clés
    additionnelles éventuelles.
    """

    # Feature: cotisations-sociales-qc, Property 13: Conformité de trace.source, trace.annee, trace.juridiction et trace.section (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_13_conformite_source_annee_juridiction_section(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces retournées par
        `calcul_rrq_employe` et `calcul_rrq_employeur` satisfont
        simultanément :

        - `trace.source` matche `^TP-1015\\.F \\d{4}, section 3\\.2` ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` ;
        - `trace.juridiction == Juridiction.QUEBEC` ;
        - `trace.section` est une chaîne non vide qui distingue
          explicitement le côté employé du côté employeur (la section
          employeur contient `"employeur"`, la section employé ne le
          contient pas).

        **Validates: Requirements 11.1, 11.2**
        """
        payroll_input, gains = entrees
        pattern_source = re.compile(r"^TP-1015\.F \d{4}, section 3\.2")

        _montant_employe, trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )

        for trace in (trace_employe, trace_employeur):
            assert pattern_source.match(trace.source) is not None
            assert trace.annee == payroll_input.pay_period.annee_fiscale
            assert trace.juridiction == Juridiction.QUEBEC
            assert trace.section != ""

        assert "employeur" in trace_employeur.section
        assert "employeur" not in trace_employe.section

    # Feature: cotisations-sociales-qc, Property 14: Contenu minimal exact de la trace par fonction (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_14_contenu_minimal_de_la_trace(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de `calcul_rrq_employe` et
        `calcul_rrq_employeur` contiennent au moins :

        - dans `parametres_utilises` : le taux de cotisation totale
          propre au côté concerné (`taux_cotisation_totale_employe` ou
          `taux_cotisation_totale_employeur`) et une exemption
          (une clé dont le nom contient `"exemption"`) ;
        - dans `entrees` : `salaire_periode`, `nb_periodes_annuelles`,
          `cumul_ytd` ;
        - dans `sous_totaux` : `exemption_periode`, `assiette_cotisable`.

        **Validates: Requirements 11.3**
        """
        payroll_input, gains = entrees

        _montant_employe, trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )

        assert "taux_cotisation_totale_employe" in trace_employe.parametres_utilises
        assert any(
            "exemption" in cle for cle in trace_employe.parametres_utilises
        )
        assert (
            "taux_cotisation_totale_employeur"
            in trace_employeur.parametres_utilises
        )
        assert any(
            "exemption" in cle for cle in trace_employeur.parametres_utilises
        )

        for trace in (trace_employe, trace_employeur):
            assert "salaire_periode" in trace.entrees
            assert "nb_periodes_annuelles" in trace.entrees
            assert "cumul_ytd" in trace.entrees
            assert "exemption_periode" in trace.sous_totaux
            assert "assiette_cotisable" in trace.sous_totaux

    # Feature: cotisations-sociales-qc, Property 15: Cohérence resultat/mode/précision (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_15_coherence_resultat_mode_precision(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de `calcul_rrq_employe` et
        `calcul_rrq_employeur` satisfont
        `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`,
        `trace.precision_arrondissement == 2`, et `trace.resultat` est
        égal au montant retourné par la fonction (premier élément du
        tuple).

        **Validates: Requirements 10.4, 11.6**
        """
        payroll_input, gains = entrees

        montant_employe, trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )
        montant_employeur, trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )

        for montant, trace in (
            (montant_employe, trace_employe),
            (montant_employeur, trace_employeur),
        ):
            assert trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
            assert trace.precision_arrondissement == 2
            assert trace.resultat == montant

    # Feature: cotisations-sociales-qc, Property 16: Auto-suffisance de la trace (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_16_auto_suffisance_de_la_trace(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, un tiers peut recalculer
        `trace.sous_totaux["assiette_cotisable"]` à partir des seuls
        contenus de `trace.entrees` et `trace.sous_totaux` — sans
        consulter `payroll_input` ni `parametres_annee` — via :

            trace.sous_totaux["assiette_cotisable"] == max(
                Decimal("0.00"),
                trace.entrees["salaire_periode"]
                - trace.sous_totaux["exemption_periode"],
            )

        Vérifié pour `calcul_rrq_employe` et `calcul_rrq_employeur`.

        **Validates: Requirements 11.8**
        """
        payroll_input, gains = entrees

        _montant_employe, trace_employe = calcul_rrq_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_rrq_employeur(
            payroll_input, gains, parametres_annee
        )

        for trace in (trace_employe, trace_employeur):
            assert trace.sous_totaux["assiette_cotisable"] == max(
                Decimal("0.00"),
                trace.entrees["salaire_periode"]
                - trace.sous_totaux["exemption_periode"],
            )


# ---------------------------------------------------------------------------
# 2.5 — Propagation de MissingParameterError (Property 17)
# ---------------------------------------------------------------------------


class TestMissingParameterRrq:
    """Property 17 (variante RRQ) — propagation de `MissingParameterError`
    sans interception.

    Design (§Correctness Properties 17 ; §Error Handling « Matrice des
    exceptions »). Pour chacun des trois champs de `RRQParametres`
    consommés par `calcul_rrq_employe` (et, par délégation stricte,
    `calcul_rrq_employeur` — Property 9) —
    `taux_cotisation_totale_employe`,
    `exemption_par_periode_aux_deux_semaines_2026`,
    `cotisation_max_annuelle_employe` — marquer ce champ `"TO_FILL"`
    dans le `ParametresAnnee` (via `st_parametres_annee_avec_to_fill`)
    DOIT faire lever `MissingParameterError` à l'appel, non interceptée
    ni masquée par une autre exception.
    """

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "rrq.taux_cotisation_totale_employe"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_taux_cotisation_totale_employe(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `rrq.taux_cotisation_totale_employe`
        porte la sentinelle `"TO_FILL"`, `calcul_rrq_employe` **et**
        `calcul_rrq_employeur` lèvent `MissingParameterError`, non
        interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains = entrees

        with pytest.raises(MissingParameterError):
            calcul_rrq_employe(payroll_input, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_rrq_employeur(payroll_input, gains, parametres_annee)

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "rrq.exemption_par_periode_aux_deux_semaines_2026"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_exemption_par_periode(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont
        `rrq.exemption_par_periode_aux_deux_semaines_2026` porte la
        sentinelle `"TO_FILL"`, `calcul_rrq_employe` **et**
        `calcul_rrq_employeur` lèvent `MissingParameterError`, non
        interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains = entrees

        with pytest.raises(MissingParameterError):
            calcul_rrq_employe(payroll_input, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_rrq_employeur(payroll_input, gains, parametres_annee)

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RRQ)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "rrq.cotisation_max_annuelle_employe"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_cotisation_max_annuelle_employe(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `rrq.cotisation_max_annuelle_employe`
        porte la sentinelle `"TO_FILL"`, `calcul_rrq_employe` **et**
        `calcul_rrq_employeur` lèvent `MissingParameterError`, non
        interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains = entrees

        with pytest.raises(MissingParameterError):
            calcul_rrq_employe(payroll_input, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_rrq_employeur(payroll_input, gains, parametres_annee)
