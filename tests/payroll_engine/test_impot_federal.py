"""Property tests et tests d'exemple pour `calcul_impot_federal_formule`/`calcul_impot_federal_retenu`.

Spec de référence : ``impots-retenues-source`` — tâche 3.1 (squelette et
tests transversaux).
Design de référence : ``design.md`` §Testing Strategy, §Correctness
Properties 1, 2, 3 (et 4, 6, 7, 8, 9, 10, 11, 12, 13 pour les tâches
suivantes) et §Components §1, §4, §5.

Ce fichier porte l'ensemble des property tests et tests d'exemple du
module ``payroll_engine/impot_federal.py``
(``calcul_impot_federal_formule``, ``calcul_impot_federal_retenu``). La
tâche 3.1 pose le squelette : les imports, la fixture des paramètres
annuels réels 2026 (Québec + Canada fusionnés), la configuration
Hypothesis partagée et les tests **transversaux** (classe
``TestSignaturePureteRobustesse``) qui s'appliquent identiquement aux
deux fonctions fédérales. Les tâches 3.2 et 3.3 ajouteront
respectivement :

- ``TestAssietteFederale`` — Property 6, Property 4 (variante fédérale)
  (tâche 3.2) ;
- ``TestMecanismeK1K2QK4`` — Property 7, Property 8, Property 9 (variantes
  fédérales) (tâche 3.3) ;
- ``TestRetenueFederale`` — Property 10, Property 11 (variantes fédérales)
  (tâche 3.4).

Propriétés couvertes par **cette** tâche (3.1), voir design.md
§Correctness Properties, chacune appliquée aux deux fonctions fédérales :

1. **Property 1 — Déterminisme (pureté)** : deux appels à
   ``calcul_impot_federal_formule`` (et ``calcul_impot_federal_retenu``)
   avec les mêmes arguments produisent deux tuples égaux au sens ``==``.
2. **Property 2 — Absence d'exception sur entrée valide** : aucun rejet
   pour tout ``PayrollInput``/``GainsDecomposes``/``ParametresAnnee``
   valides, y compris les cas extrêmes (salaire nul, crédit personnel nul
   ou très élevé via ``st_credit_personnel_eleve``, cumul YTD nul ou
   proche du plafond, salaire très élevé, retenue additionnelle nulle ou
   élevée).
3. **Property 3 — Forme ``Decimal`` du résultat et de la trace** : le
   montant retourné et chaque valeur des dictionnaires de trace sont des
   ``Decimal`` finis ; le montant retourné et ``trace.resultat`` sont en
   outre arrondis à deux décimales ``ROUND_HALF_UP``.

**Limitation héritée du corpus golden** (Introduction des requirements,
design §Testing Strategy) : les six scénarios QC001–QC006 sont tous des
paies n° 1 de la saison — cumul YTD de départ nul pour les six catégories
de cotisation, et aucune retenue additionnelle non nulle. Le corpus
golden ne valide donc **jamais** directement les crédits personnels très
élevés (comportement sous le seuil d'imposition, Property 8) ni la
retenue additionnelle non nulle : ces comportements ne sont couverts que
par les property tests de ce fichier, via ``st_credit_personnel_eleve()``
et les stratégies locales de ce module.

Discipline règle 06 (TDD — tests avant code) :
``payroll_engine/impot_federal.py`` n'existe **pas encore** à ce stade.
Comme ``test_rrq.py`` (spec ``cotisations-sociales-qc``, tâche 2.1), ce
fichier importe ``calcul_impot_federal_formule`` et
``calcul_impot_federal_retenu`` **au niveau module** : la collecte pytest
de ce fichier échoue donc actuellement avec ``ModuleNotFoundError`` sur
``payroll_engine.impot_federal`` — c'est le comportement **attendu et
correct** tant que la tâche 10.1 (implémentation) n'a pas été réalisée
(checkpoint de la tâche 8 du plan).

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction, ModeArrondissement
from models.exceptions import MissingParameterError
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.impot_federal import (
    calcul_impot_federal_formule,
    calcul_impot_federal_retenu,
)
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters
from tests.strategies import (
    st_brut_total_avec_zero,
    st_credit_personnel_eleve,
    st_cumuls_ytd_non_nuls,
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_impot_avec_to_fill,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Fixture module-scoped : paramètres 2026 fusionnés Québec + Canada
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parametres_2026_qc_ca() -> ParametresAnnee:
    """Charge une seule fois les paramètres 2026 fusionnés Québec + Canada.

    Cohérent avec ``_charger_parametres_annee_2026_qc_ca`` de
    ``tests/strategies.py`` : la racine Québec (``rrq``, ``rqap``,
    ``impot_quebec``) reçoit la section ``assurance_emploi`` de la racine
    Canada. ``calcul_impot_federal_formule`` a besoin **à la fois** des
    sections ``rrq``/``rqap``/``assurance_emploi`` (mécanisme K2Q, design
    §Components §4) et de la section ``impot_federal`` (paliers, crédits,
    abattement du Québec) — cette dernière provient directement de la
    racine Canada, qui la porte nativement.

    Portée ``module`` : les deux fichiers ne sont lus qu'une seule fois
    par ce fichier de test, quel que soit le nombre de tests (property ou
    exemple) qui consomment cette fixture.
    """
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    return parametres_qc.model_copy(
        update={
            "assurance_emploi": parametres_ca.assurance_emploi,
            "impot_federal": parametres_ca.impot_federal,
        }
    )


# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_rrq.py)
# ---------------------------------------------------------------------------

# Design (§Testing Strategy « Configuration Hypothesis ») : pas de deadline
# (les modèles Pydantic peuvent dépasser 200 ms/exemple sous charge) et
# suppression du health check "too_slow" pour les propriétés à surface
# d'entrée large (composition de plusieurs sous-modèles via
# ``st_payroll_input()``). Le nombre d'exemples est piloté par le profil
# Hypothesis actif (voir ``tests/conftest.py`` : dev=15 par défaut, ci=100).
settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Helpers internes de génération — combinent les stratégies de
# tests/strategies.py pour produire des entrées couvrant les cas extrêmes
# (salaire admissible nul ou très élevé, cumul YTD non nul, crédit
# personnel fédéral très élevé) non couverts par le corpus golden.
# ---------------------------------------------------------------------------


def _construire_gains_decomposes(brut_total: Decimal) -> GainsDecomposes:
    """``GainsDecomposes`` valide, minimal, pour un ``brut_total`` donné.

    Seul ``brut_total`` importe pour les quatre fonctions de cette spec
    (Req 1.6 — lecture exclusive de ``gains.brut_total``) ; les autres
    composantes du brut sont mises à zéro pour ne pas introduire de bruit
    hors du périmètre de cette spec. ``multiplicateur_heures_supp`` et
    ``seuil_heures_supp_hebdo`` sont des valeurs de contexte portées par
    contrat (``gt=0``) mais non consommées par le Moteur_Impots — les
    valeurs ``1.5``/``40`` ne sont pas des paramètres fiscaux au sens de
    la règle 05, seulement des valeurs de forme requises par
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


def _st_brut_total_eleve() -> st.SearchStrategy[Decimal]:
    """``Decimal`` élevé (``]5000.00, 1000000.00]``), deux décimales.

    Complète ``st_brut_total_avec_zero()`` (bornée à ``5000.00``) pour
    exercer le cas « salaire très élevé » exigé par Property 2 (design
    §Correctness Properties 2), notamment le franchissement des paliers
    progressifs supérieurs et le plafonnement des cotisations annualisées
    du mécanisme K2Q. La borne haute n'est pas un paramètre fiscal (règle
    05) mais une simple borne de génération.
    """
    return st.decimals(
        min_value=Decimal("5000.01"),
        max_value=Decimal("1000000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


@st.composite
def _st_payroll_input_avec_cumuls_non_nuls(draw: st.DrawFn) -> PayrollInput:
    """``PayrollInput`` dont ``cumuls_debut`` peut être non nul.

    Combine ``st_payroll_input()`` (cumuls neutres par construction) avec
    ``st_cumuls_ytd_non_nuls()`` (au moins une catégorie strictement
    positive, biaisée vers le plafond annuel exact — design §Testing
    Strategy). L'appariement ``(employe_id, annee_civile)`` exigé par le
    contrat ``PayrollInput`` est préservé en recopiant les deux
    identifiants du ``PayrollInput`` de base sur le ``CumulsYTD`` généré,
    via ``model_copy(update=...)`` (aucune mutation — règle 06,
    immuabilité).

    Bien que les quatre fonctions de cette spec ne lisent **pas**
    ``cumuls_debut`` (le mécanisme K2Q est une projection annuelle
    théorique, design §Components §4), faire varier ce champ élargit la
    surface d'entrée testée par Property 1/2/3 sans coût.
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


@st.composite
def _st_entrees_completes(draw: st.DrawFn) -> tuple[PayrollInput, GainsDecomposes]:
    """``(PayrollInput, GainsDecomposes)`` couvrant les cas extrêmes de
    Property 2 : cumul YTD nul ou proche du plafond
    (``_st_payroll_input_avec_cumuls_non_nuls``), salaire admissible nul
    ou très élevé (``st_brut_total_avec_zero`` / ``_st_brut_total_eleve``)
    et crédit personnel fédéral occasionnellement très élevé
    (``st_credit_personnel_eleve`` réaffecté à
    ``montant_total_TD1_effectif``).

    Le biais vers un crédit personnel fédéral très élevé exerce le
    comportement sous le seuil d'imposition (design §Correctness
    Properties 2 : « crédit personnel nul ou très élevé ») dès la classe
    transversale, sans attendre la Property 8 dédiée (tâche 3.3). La
    réaffectation passe par ``model_copy(update=...)`` (immuabilité —
    ``PayrollInput`` est ``frozen=True``).
    """
    payroll_input = draw(_st_payroll_input_avec_cumuls_non_nuls())
    if draw(st.booleans()):
        credit_eleve = draw(st_credit_personnel_eleve())
        payroll_input = payroll_input.model_copy(
            update={"montant_total_TD1_effectif": credit_eleve}
        )
    brut_total = draw(st.one_of(st_brut_total_avec_zero(), _st_brut_total_eleve()))
    gains = _construire_gains_decomposes(brut_total)
    return payroll_input, gains


def _verifier_property_3_forme_decimal(
    montant: Decimal, trace: CalculationTrace
) -> None:
    """Vérifie Property 3 (design §Correctness Properties 3) pour un
    couple ``(montant, trace)`` retourné par une des fonctions fédérales.

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
    assert trace.resultat == trace.resultat.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


# ---------------------------------------------------------------------------
# 3.1 — Signature, pureté et robustesse (Property 1, 2, 3)
# ---------------------------------------------------------------------------


class TestSignaturePureteRobustesse:
    """Property 1, 2, 3 — déterminisme, absence d'exception, forme `Decimal`.

    Design (§Correctness Properties 1, 2, 3 ; §Components §1 « Signatures
    exactes »). Ces trois propriétés s'appliquent identiquement à
    `calcul_impot_federal_formule` et `calcul_impot_federal_retenu`, plus
    un test d'exemple vérifiant l'absence d'effet de bord à l'import
    (Req 1.9).
    """

    # Feature: impots-retenues-source, Property 1: Déterminisme (pureté)
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
        `ParametresAnnee` valides, `calcul_impot_federal_formule(pi, g, p)
        == calcul_impot_federal_formule(pi, g, p)` et de même pour
        `calcul_impot_federal_retenu` : deux appels avec les mêmes
        arguments produisent deux tuples égaux au sens `==` sur les deux
        composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.4**
        """
        payroll_input, gains = entrees

        resultat_formule_1 = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )
        resultat_formule_2 = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )
        assert resultat_formule_1 == resultat_formule_2
        assert resultat_formule_1[0] == resultat_formule_2[0]
        assert resultat_formule_1[1] == resultat_formule_2[1]

        resultat_retenu_1 = calcul_impot_federal_retenu(
            payroll_input, gains, parametres_annee
        )
        resultat_retenu_2 = calcul_impot_federal_retenu(
            payroll_input, gains, parametres_annee
        )
        assert resultat_retenu_1 == resultat_retenu_2
        assert resultat_retenu_1[0] == resultat_retenu_2[0]
        assert resultat_retenu_1[1] == resultat_retenu_2[1]

    # Feature: impots-retenues-source, Property 2: Absence d'exception sur entrée valide
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
        `ParametresAnnee` valides (2026 entièrement renseignés) — y
        compris les cas extrêmes (salaire nul, crédit personnel fédéral
        nul ou très élevé, cumul YTD nul ou proche du plafond, salaire
        très élevé) — `calcul_impot_federal_formule` et
        `calcul_impot_federal_retenu` retournent un tuple sans lever
        aucune exception.

        **Validates: Requirements 1.8, 12.1**
        """
        payroll_input, gains = entrees

        resultat_formule = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )
        resultat_retenu = calcul_impot_federal_retenu(
            payroll_input, gains, parametres_annee
        )

        assert resultat_formule is not None
        assert resultat_retenu is not None

    # Feature: impots-retenues-source, Property 3: Forme Decimal du résultat et de la trace
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

        **Validates: Requirements 4.8, 5.4, 5.5**
        """
        payroll_input, gains = entrees

        montant_formule, trace_formule = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )
        _verifier_property_3_forme_decimal(montant_formule, trace_formule)

        montant_retenu, trace_retenu = calcul_impot_federal_retenu(
            payroll_input, gains, parametres_annee
        )
        _verifier_property_3_forme_decimal(montant_retenu, trace_retenu)

    def test_import_calcul_impot_federal_sans_effet_de_bord(self, capsys) -> None:
        """Test d'exemple — `from payroll_engine.impot_federal import
        calcul_impot_federal_formule, calcul_impot_federal_retenu` ne
        produit **aucun effet de bord** (Req 1.9) : pas d'ouverture de
        fichier, pas d'appel réseau, pas d'écriture sur `stdout` /
        `stderr`.

        Design (§Architecture « Contrainte de pureté »). Le module est
        retiré de `sys.modules` avant l'import (s'il y était déjà chargé
        par un import précédent) afin de forcer une exécution fraîche du
        corps du module — c'est justement à ce moment-là qu'un éventuel
        effet de bord au niveau module se manifesterait.
        """
        import importlib

        nom_module = "payroll_engine.impot_federal"
        sys.modules.pop(nom_module, None)

        module = importlib.import_module(nom_module)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert nom_module in sys.modules
        assert hasattr(module, "calcul_impot_federal_formule")
        assert hasattr(module, "calcul_impot_federal_retenu")


# ---------------------------------------------------------------------------
# Helper d'exemple — PayrollInput déterministe reproduisant le scénario
# QC001 (paie n° 1, 27 périodes, brut 1 516,32 $, TD1 16 452,00 $, aucune
# exonération). Mirroir de `_payroll_input_deterministe_pour_exemple` de
# `tests/payroll_engine/test_rrq.py` — instance fixe, anonymisée (règle
# 04), sans aucun `float` (règle 01). Le brut n'est pas dérivé des heures :
# il est porté directement par le `GainsDecomposes` (Req 1.6), les heures
# de forme sont donc mises à zéro.
# ---------------------------------------------------------------------------


def _payroll_input_qc001_pour_exemple() -> PayrollInput:
    """`PayrollInput` déterministe reproduisant les données de QC001.

    Seuls les champs consommés par `calcul_impot_federal_formule` pour la
    Deduction_RRQ_Supplementaire_Federale et l'assiette portent les
    valeurs de QC001 (`nb_periodes_annuelles=27`,
    `montant_total_TD1_effectif=16452.00`, `exoneration_TD1_effective`
    False) ; le brut lui-même est fourni par le `GainsDecomposes` (Req
    1.6). Aucune donnée personnelle réelle (règle 04) : identifiant et
    intitulé sont synthétiques.
    """
    date_debut = date(2026, 7, 13)
    date_fin = date(2026, 7, 26)

    employee = Employee(
        id="EMPTEST001",
        nom_affichage="Employe Test QC001",
        date_naissance=date(2005, 6, 15),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Employe synthetique",
        taux_horaire_base=Decimal("18.00"),
        date_embauche=date_debut,
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("18952.00"),
        montant_total_TD1=Decimal("16452.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )
    semaine_0 = WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=Decimal("40.5"),
        heures_supplementaires=Decimal("0.00"),
    )
    semaine_1 = WeekSegment(
        date_debut=date_debut + timedelta(days=7),
        date_fin=date_fin,
        heures_normales=Decimal("40.5"),
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
            heures_normales=Decimal("40.5"), heures_supplementaires=Decimal("0.00")
        ),
        HeuresParSemaine(
            heures_normales=Decimal("40.5"), heures_supplementaires=Decimal("0.00")
        ),
    )
    cumuls_debut = CumulsYTD.zero(employe_id="EMPTEST001", annee_civile=2026)
    return PayrollInput(
        employee=employee,
        pay_period=pay_period,
        heures_par_semaine=heures_par_semaine,
        taux_horaire_effectif=Decimal("18.00"),
        taux_vacances=Decimal("0.04"),
        jours_feries_manuels=Decimal("0.00"),
        montant_total_TP1015_3_effectif=Decimal("18952.00"),
        exoneration_TP1015_3_effectif=False,
        retenue_additionnelle_QC_effective=Decimal("0.00"),
        montant_total_TD1_effectif=Decimal("16452.00"),
        exoneration_TD1_effective=False,
        retenue_additionnelle_federale_effective=Decimal("0.00"),
        cumuls_debut=cumuls_debut,
    )


def _deduction_rrq_supp_attendue(
    brut_total: Decimal, parametres_annee: ParametresAnnee
) -> Decimal:
    """Reconstruit la Deduction_RRQ_Supplementaire_Federale attendue
    (design §Components §4, étape a ; Glossary requirements).

    Le taux effectif et l'exemption par période sont lus **exclusivement**
    depuis `parametres_annee.rrq` (règle 05, Req 12.4) — jamais codés en
    dur — puis la déduction théorique
    `taux × max(Decimal("0.00"), brut − exemption)` est arrondie à deux
    décimales `ROUND_HALF_UP` (Mode_Arrondissement_Impots), telle qu'elle
    est exposée dans `trace.entrees["deduction_rrq_supp"]`. `Decimal(str(...))`
    protège contre tout `float` résiduel (règle 01) sur la valeur brute lue
    dans la clé imbriquée `portion_supplementaire_deductible_fed`.
    """
    taux_rrq_supp = Decimal(
        str(parametres_annee.rrq.portion_supplementaire_deductible_fed["taux_effectif"])
    )
    exemption_periode_rrq = (
        parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
    )
    deduction_theorique = taux_rrq_supp * max(
        Decimal("0.00"), brut_total - exemption_periode_rrq
    )
    return deduction_theorique.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 3.2 — Deduction_RRQ_Supplementaire_Federale et assiette (Property 6,
#       Property 4 variante fédérale)
# ---------------------------------------------------------------------------


class TestAssietteFederale:
    """Property 6 et Property 4 (variante fédérale) — Deduction_RRQ_Supplementaire_Federale,
    assiette imposable de période et plancher à zéro.

    Design (§Correctness Properties 4, 6 ; §Components §4). La classe
    couvre :

    - **Property 6** — `calcul_impot_federal_formule` calcule
      `deduction_rrq_supp == taux_effectif_rrq_supp × max(0, brut_total −
      exemption_par_periode_rrq)` et `revenu_imposable_periode ==
      brut_total − deduction_rrq_supp`, exposés tels quels dans
      `trace.entrees`/`trace.sous_totaux` ;
    - **Property 4 (variante fédérale)** — le montant retourné par
      `calcul_impot_federal_formule` est toujours `>= Decimal("0.00")`.

    Plus un test d'exemple reproduisant la Deduction_RRQ_Supplementaire_Federale
    de QC001 (`13,87 $ = 1,00 % × (1 516,32 $ − 129,63 $)`, confirmée
    PDOC — Glossary requirements).
    """

    # Feature: impots-retenues-source, Property 6: Deduction_RRQ_Supplementaire_Federale et assiette
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_6_deduction_rrq_supp_et_assiette(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, `calcul_impot_federal_formule` expose
        dans sa trace une Deduction_RRQ_Supplementaire_Federale égale à
        `taux_effectif_rrq_supp × max(Decimal("0.00"), brut_total −
        exemption_par_periode_rrq)` (arrondie à deux décimales) et un
        revenu imposable de période égal à `brut_total −
        deduction_rrq_supp` (calculé à partir de la valeur exposée dans
        `trace.entrees`).

        Le taux effectif et l'exemption sont reconstruits **uniquement**
        depuis `parametres_annee.rrq` (règle 05) : aucun `Decimal("0.010")`
        ni `Decimal("129.63")` codé en dur (Req 12.4).

        **Validates: Requirements 4.1, 4.2, 9.3**
        """
        payroll_input, gains = entrees

        _montant, trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )

        deduction_attendue = _deduction_rrq_supp_attendue(
            gains.brut_total, parametres_annee
        )
        assert trace.entrees["deduction_rrq_supp"] == deduction_attendue
        assert trace.sous_totaux["revenu_imposable_periode"] == (
            gains.brut_total - trace.entrees["deduction_rrq_supp"]
        )

    # Feature: impots-retenues-source, Property 4: Montant jamais strictement négatif (fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_4_montant_jamais_strictement_negatif(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, `calcul_impot_federal_formule(...)[0]
        >= Decimal("0.00")` — le montant théorique de période n'est
        jamais strictement négatif (plancher à zéro du design §Components
        §4, étapes f et impot_periode).

        **Validates: Requirements 4.7, 4.8, 9.7**
        """
        payroll_input, gains = entrees

        montant, _trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )

        assert montant >= Decimal("0.00")

    def test_exemple_deduction_rrq_supp_qc001(
        self, parametres_2026_qc_ca: ParametresAnnee
    ) -> None:
        """Test d'exemple — reproduction chiffrée de la
        Deduction_RRQ_Supplementaire_Federale sur QC001.

        Scénario QC001 (`tests/fixtures/inputs/qc001.json`) : brut de
        période `1 516,32 $`, 27 périodes annuelles. Le taux effectif
        (`1,00 %`) et l'exemption par période (`129,63 $`) sont lus depuis
        `parametres_2026_qc_ca.rrq` (règle 05) : leur produit reproduit la
        valeur confirmée par PDOC `13,87 $ = 1,00 % × (1 516,32 $ −
        129,63 $)`, et l'assiette imposable de période vaut alors
        `1 502,45 $ = 1 516,32 $ − 13,87 $` (Glossary
        Revenu_Imposable_Federal_Periode).

        **Validates: Requirements 4.1, 4.2, 9.3, 12.4**
        """
        payroll_input = _payroll_input_qc001_pour_exemple()
        gains = _construire_gains_decomposes(Decimal("1516.32"))

        # La déduction et l'assiette dérivent uniquement des paramètres
        # (taux, exemption) et du brut — jamais de constantes fiscales
        # codées en dur (Req 12.4).
        deduction_attendue = _deduction_rrq_supp_attendue(
            Decimal("1516.32"), parametres_2026_qc_ca
        )
        assert deduction_attendue == Decimal("13.87")

        _montant, trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_2026_qc_ca
        )

        assert trace.entrees["deduction_rrq_supp"] == Decimal("13.87")
        assert trace.sous_totaux["revenu_imposable_periode"] == Decimal("1502.45")


# ---------------------------------------------------------------------------
# 3.3 — Fixture, helpers et stratégies dédiés au mécanisme K1 + K2Q + K4
# ---------------------------------------------------------------------------
#
# Property 7 exige de rejouer, côté test, exactement l'arithmétique
# `Decimal` du mécanisme K2Q décrit au design §Components §4 (recalcul
# annualisé local des cotisations RRQ base / AE / RQAP, plafonné aux
# maximums annuels). Le helper `_k2q_attendu` duplique volontairement —
# à des fins de vérification indépendante — cette arithmétique, en lisant
# **tous** les taux, exemptions et plafonds depuis `parametres_annee`
# (règle 05 : aucun taux/plafond fiscal codé en dur). Point de vigilance
# central du design §Components §4 : ce recalcul part de `gains.brut_total`
# et des sections `parametres_annee.rrq`/`.rqap`/`.assurance_emploi`
# (+ `impot_federal.plafond_cotisation_base_rrq_annuel`), **jamais** de
# `payroll_input.cumuls_debut` ni d'un appel à `calcul_rrq_employe`/
# `calcul_rqap_employe`/`calcul_ae_employe` (Req 6.3).


@pytest.fixture(scope="module")
def parametres_2026_qc_ca_federal(
    parametres_2026_qc_ca: ParametresAnnee,
) -> ParametresAnnee:
    """`ParametresAnnee` 2026 fusionné portant **aussi** la section `impot_federal`.

    La fixture `parametres_2026_qc_ca` a une racine Québec (`rrq`, `rqap`,
    `impot_quebec`) enrichie de la section `assurance_emploi` de la racine
    Canada, mais son champ `impot_federal` reste `None` (le fichier
    `parameters/2026/quebec.json` ne porte pas cette section). Or
    `calcul_impot_federal_formule` a besoin des paliers, du taux de
    conversion des crédits, du montant canadien pour emploi, du plafond de
    cotisation de base RRQ et du taux d'abattement du Québec — tous portés
    par `parameters/2026/canada.json`. Cette fixture ajoute donc la section
    `impot_federal` chargée depuis la racine Canada via
    `model_copy(update=...)` (aucune mutation — règle 06, immuabilité),
    en miroir de `_charger_parametres_annee_2026_impot` de
    `tests/strategies.py`. Réservée aux tests d'exemple chiffrés (non
    paramétrés par `@given`), qui ont besoin d'une instance concrète
    portant l'ensemble des sections consommées par la formule fédérale.
    """
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    return parametres_2026_qc_ca.model_copy(
        update={"impot_federal": parametres_ca.impot_federal}
    )


#: Configuration Hypothesis pour Property 7 et Property 8 — surface
#: d'entrée large combinant crédits personnels, déductions annualisées
#: et paliers progressifs. Deadline désactivée et health check "too_slow"
#: supprimé, comme `settings_large_input`. Le nombre d'exemples est piloté
#: par le profil Hypothesis actif (voir ``tests/conftest.py`` : dev=15 par
#: défaut, ci=100).
settings_seuil = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def _arrondir_2(montant: Decimal) -> Decimal:
    """Arrondi monétaire `ROUND_HALF_UP` à deux décimales (design §Components §4).

    Réplique indépendante du helper privé `_arrondir` de
    `payroll_engine/impot_federal.py` (design §Architecture « Helper
    d'arrondissement partagé »), pour vérifier Property 7 sans importer
    l'implémentation. Miroir de `_arrondir_2` de `test_impot_qc.py`. Le
    calcul interne du module reste en pleine précision `Decimal` du début
    jusqu'à l'arrondissement UNIQUE et final de `impot_periode` (Req 8.1) ;
    les sous-totaux monétaires de la trace, eux, sont exposés arrondis au
    cent (valeur d'affichage/audit — alignement sur `impot_qc.py`), d'où
    la comparaison des sous-totaux à `_arrondir_2(valeur_reconstruite)`.
    """
    return montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _k2q_attendu(
    brut_total: Decimal,
    nb_periodes: Decimal,
    taux_conversion: Decimal,
    parametres_annee: ParametresAnnee,
) -> Decimal:
    """Reconstruit `k2q` (crédit fédéral T4127 pour cotisations RRQ base /
    AE / RQAP) attendu, design §Components §4 étape e.

    `k2q == taux_conversion × (cotisation_rrq_base + cotisation_ae +
    cotisation_rqap)`, où chaque cotisation est une **projection annuelle
    théorique plafonnée** calculée directement depuis `brut_total`,
    `nb_periodes` et les sections `parametres_annee.rrq`/`.rqap`/
    `.assurance_emploi` (+ `impot_federal.plafond_cotisation_base_rrq_annuel`) :

    - `cotisation_rrq_base = min(nb_periodes × taux_base_rrq × max(0,
      brut_total − exemption_periode_rrq), plafond_cotisation_base_rrq_annuel)`,
      avec `taux_base_rrq = taux_cotisation_totale_employe −
      taux_effectif_rrq_supp` ;
    - `cotisation_ae = min(nb_periodes × taux_employe_quebec × brut_total,
      cotisation_max_employe_ae)` ;
    - `cotisation_rqap = min(nb_periodes × taux_employe_rqap × brut_total,
      cotisation_max_employe_rqap)`.

    Tous les taux, exemptions et plafonds sont lus **exclusivement** depuis
    `parametres_annee` (règle 05, Req 12.4) — jamais codés en dur.
    `Decimal(str(...))` protège contre tout `float` résiduel (règle 01) sur
    la valeur brute lue dans la clé imbriquée
    `portion_supplementaire_deductible_fed`. Aucune consultation de
    `payroll_input.cumuls_debut`, aucun appel aux fonctions de
    `cotisations-sociales-qc` (Req 6.3) : reconstruction strictement locale.
    """
    taux_rrq_supp = Decimal(
        str(parametres_annee.rrq.portion_supplementaire_deductible_fed["taux_effectif"])
    )
    exemption_periode_rrq = (
        parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
    )
    taux_base_rrq = parametres_annee.rrq.taux_cotisation_totale_employe - taux_rrq_supp

    cotisation_rrq_base = min(
        nb_periodes
        * taux_base_rrq
        * max(Decimal("0.00"), brut_total - exemption_periode_rrq),
        parametres_annee.impot_federal.plafond_cotisation_base_rrq_annuel,
    )
    cotisation_ae = min(
        nb_periodes * parametres_annee.assurance_emploi.taux_employe_quebec * brut_total,
        parametres_annee.assurance_emploi.cotisation_max_employe,
    )
    cotisation_rqap = min(
        nb_periodes * parametres_annee.rqap.taux_employe * brut_total,
        parametres_annee.rqap.cotisation_max_employe,
    )
    return taux_conversion * (cotisation_rrq_base + cotisation_ae + cotisation_rqap)


def _st_retenue_additionnelle_federale() -> st.SearchStrategy[Decimal]:
    """`Decimal` de retenue additionnelle fédérale, biaisé vers `0.00` et vers des valeurs élevées.

    Utilisée par la paire de Property 9 (variante fédérale) pour faire
    varier `retenue_additionnelle_federale_effective` entre les deux
    membres de la paire. Ce champ n'est **pas** consulté par
    `calcul_impot_federal_formule` (Req 4.9) : le faire varier vérifie
    précisément cette non-consultation. Règle 01 : `Decimal` exclusivement.
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


@st.composite
def _st_entrees_credit_fed_eleve(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes]:
    """`(PayrollInput, GainsDecomposes)` à crédit personnel fédéral très élevé.

    Force `montant_total_TD1_effectif` à une valeur issue de
    `st_credit_personnel_eleve()` (≥ 100 000 $, jusqu'à 1 000 000 $) et
    borne le `brut_total` à `[0, 5000]` (`st_brut_total_avec_zero`) afin que
    le revenu imposable annualisé (≈ `brut × nb_periodes`) reste dans la
    grande majorité des exemples inférieur ou égal au crédit : condition du
    comportement sous le seuil d'imposition (Property 8, design §Correctness
    Properties 8). Aucune mutation en place — `model_copy(update=...)`
    (règle 06, immuabilité).
    """
    payroll_input = draw(st_payroll_input())
    credit = draw(st_credit_personnel_eleve())
    payroll_input = payroll_input.model_copy(
        update={"montant_total_TD1_effectif": credit}
    )
    brut_total = draw(st_brut_total_avec_zero())
    gains = _construire_gains_decomposes(brut_total)
    return payroll_input, gains


@st.composite
def _st_paire_input_exoneration_retenue_fed(
    draw: st.DrawFn,
) -> tuple[PayrollInput, PayrollInput, GainsDecomposes]:
    """Paire `(base, variante)` identique **sauf** sur les deux champs
    fédéraux `exoneration_TD1_effective` / `retenue_additionnelle_federale_effective`,
    plus le `GainsDecomposes` partagé.

    Design (§Correctness Properties 9, variante fédérale) : la variante
    inverse le drapeau d'exonération fédérale (`exoneration_TD1_effective`)
    et remplace la retenue additionnelle fédérale
    (`retenue_additionnelle_federale_effective`) par une valeur tirée
    indépendamment — tous les autres champs (dont `montant_total_TD1_effectif`,
    seul champ de crédit consommé par la formule fédérale) restent
    strictement identiques. `model_copy(update=...)` garantit l'absence de
    mutation (règle 06).
    """
    payroll_input, gains = draw(_st_entrees_completes())
    variante = payroll_input.model_copy(
        update={
            "exoneration_TD1_effective": (
                not payroll_input.exoneration_TD1_effective
            ),
            "retenue_additionnelle_federale_effective": draw(
                _st_retenue_additionnelle_federale()
            ),
        }
    )
    return payroll_input, variante, gains


# ---------------------------------------------------------------------------
# 3.3 — Mécanisme K1 + K2Q + K4, abattement du Québec et seuil d'imposition
#       (Property 7, Property 8, Property 9 — variantes fédérales)
# ---------------------------------------------------------------------------


class TestMecanismeK1K2QK4:
    """Property 7, 8, 9 (variantes fédérales) — mécanisme complet du T4127.

    Design (§Overview « Découverte de recherche déterminante » ;
    §Correctness Properties 7, 8, 9 ; §Components §4). La classe couvre :

    - **Property 7** — `calcul_impot_federal_formule` reconstruit
      `impot_annuel_base == max(0, taux_palier × revenu_imposable_annuel −
      constante_k − k1 − k2q − k4)`, avec `k1`/`k4` dérivés du taux de
      conversion des crédits et `k2q` recalculé localement (RRQ base / AE /
      RQAP annualisés et plafonnés), puis `impot_annuel_net ==
      impot_annuel_base − taux_abattement_quebec × impot_annuel_base` ;
    - **Property 8 (variante fédérale)** — sous un crédit personnel fédéral
      très élevé, la formule retourne `Decimal("0.00")`, indépendamment de
      `exoneration_TD1_effective` ;
    - **Property 9 (variante fédérale)** — la formule ignore totalement
      `exoneration_TD1_effective` et `retenue_additionnelle_federale_effective`.

    Plus trois tests d'exemple : reproduction chiffrée du mécanisme complet
    sur QC001 (`86,25 $`, impossible à reproduire sans K2Q + K4 + abattement,
    design §Overview) et retenue fédérale par la seule formule à `0,00 $`
    sur QC004 et QC006 (Req 7.3, 11.7).
    """

    # Feature: impots-retenues-source, Property 7: Formule fédérale — mécanisme K1 + K2Q + K4 et abattement du Québec
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_seuil
    def test_property_7_mecanisme_k1_k2q_k4_et_abattement(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, le résultat de
        `calcul_impot_federal_formule` est reconstructible à partir des
        seules valeurs de sa trace et des paramètres annuels (design
        §Components §4) :

        - `impot_avant_credits == taux_palier × revenu_imposable_annuel −
          constante_k` ;
        - `k1 == taux_credits_convertibles × montant_total_TD1_effectif` ;
        - `k4 == taux_credits_convertibles × min(revenu_imposable_annuel,
          montant_emploi_canadien_annuel)` ;
        - `k2q` recalculé exclusivement depuis `gains.brut_total`,
          `nb_periodes_annuelles` et `parametres_annee.rrq`/`.rqap`/
          `.assurance_emploi` (+ `impot_federal.plafond_cotisation_base_rrq_annuel`),
          **jamais** via `payroll_input.cumuls_debut` ni un appel à
          `calcul_rrq_employe`/`calcul_rqap_employe`/`calcul_ae_employe` ;
        - `impot_annuel_base == max(0, impot_avant_credits − k1 − k2q −
          k4)` ;
        - `impot_annuel_net == impot_annuel_base − taux_abattement_quebec ×
          impot_annuel_base`.

        Patron de reconstruction (miroir de Property 5 QC,
        `test_impot_qc.py::TestFormuleQc`) : la chaîne K1 + K2Q + K4 +
        abattement est recomposée **en pleine précision** `Decimal` à
        partir des seules ENTRÉES (`trace.entrees`) et PARAMÈTRES
        (`trace.parametres_utilises` et `parametres_annee`), jamais des
        sous-totaux (exposés arrondis au cent — Property 3). Le calcul
        interne du module reste en pleine précision jusqu'à
        l'arrondissement UNIQUE et final de `impot_periode` (Req 8.1) ;
        seuls les sous-totaux STOCKÉS dans la trace sont arrondis
        (alignement sur `impot_qc.py`). Deux niveaux de comparaison :

        - le **montant final** retourné (et `trace.resultat`) est comparé
          par égalité stricte `Decimal` (`==`, tolérance nulle — règle 01)
          à la reconstruction pleine précision suivie de l'arrondissement
          final unique ;
        - chaque **sous-total** monétaire de la trace
          (`revenu_imposable_annuel`, `impot_avant_credits`, `k1`, `k2q`,
          `k4`, `impot_annuel_base`, `impot_annuel_net`) est comparé à
          `_arrondir_2(valeur_reconstruite_pleine_precision)` (égalité au
          cent), et NON à la valeur pleine précision.

        Le mécanisme est vérifié dans sa forme : `k1` dérive du taux de
        conversion et du `montant_total_td1`, `k4` du taux de conversion et
        de `min(revenu, CEA)`, `k2q` recalculé exclusivement depuis
        `gains.brut_total`, `nb_periodes_annuelles` et
        `parametres_annee.rrq`/`.rqap`/`.assurance_emploi`
        (+ `impot_federal.plafond_cotisation_base_rrq_annuel`) — **jamais**
        via `payroll_input.cumuls_debut` ni un appel à
        `calcul_rrq_employe`/`calcul_rqap_employe`/`calcul_ae_employe`, et
        l'abattement au taux `0,165`. Le taux de palier, la constante, le
        taux de conversion, le montant canadien pour emploi et le taux
        d'abattement sont lus dans `trace.parametres_utilises` ; aucun taux
        ni seuil n'est codé en dur (règle 05, Req 12.4).

        **Validates: Requirements 4.3, 4.4, 6.3, 9.7**
        """
        payroll_input, gains = entrees

        montant, trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )

        # --- Valeurs lues exclusivement dans les entrées / paramètres de
        #     la trace (jamais dans les sous-totaux arrondis) ---
        salaire_periode = trace.entrees["salaire_periode"]
        nb_periodes = trace.entrees["nb_periodes_annuelles"]
        montant_total_td1 = trace.entrees["montant_total_td1"]
        taux_palier = trace.parametres_utilises["taux_palier"]
        constante_k = trace.parametres_utilises["constante_k"]
        taux_conversion = trace.parametres_utilises["taux_credits_convertibles"]
        cea_annuel = trace.parametres_utilises["montant_emploi_canadien_annuel"]
        taux_abattement = trace.parametres_utilises["taux_abattement_quebec"]

        # --- Assiette annualisée reconstruite en PLEINE PRÉCISION à partir
        #     des paramètres RRQ (taux effectif et exemption par période),
        #     jamais de la déduction arrondie exposée dans `trace.entrees`
        #     (design §Components §4, étapes a/b). ---
        taux_rrq_supp = Decimal(
            str(
                parametres_annee.rrq.portion_supplementaire_deductible_fed[
                    "taux_effectif"
                ]
            )
        )
        exemption_periode_rrq = (
            parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
        )
        deduction_rrq_supp = taux_rrq_supp * max(
            Decimal("0.00"), salaire_periode - exemption_periode_rrq
        )
        revenu_imposable_periode = salaire_periode - deduction_rrq_supp
        revenu_imposable_annuel = revenu_imposable_periode * nb_periodes

        # --- Impôt annuel avant crédits (paliers progressifs, pleine précision) ---
        impot_avant_credits = taux_palier * revenu_imposable_annuel - constante_k

        # --- K1 : crédit personnel (TD1) ---
        k1 = taux_conversion * montant_total_td1

        # --- K4 : montant canadien pour emploi (CEA), plafonné au revenu ---
        k4 = taux_conversion * min(revenu_imposable_annuel, cea_annuel)

        # --- K2Q : cotisations RRQ base / AE / RQAP annualisées et
        #     plafonnées, recalculées localement (jamais via cumuls_debut
        #     ni les fonctions cotisations — Req 6.3) ---
        k2q = _k2q_attendu(
            gains.brut_total, nb_periodes, taux_conversion, parametres_annee
        )

        # --- Impôt annuel de base (plancher à zéro après les trois crédits) ---
        impot_annuel_base = max(
            Decimal("0.00"), impot_avant_credits - k1 - k2q - k4
        )

        # --- Abattement du Québec (taux 0,165) ---
        impot_annuel_net = impot_annuel_base - taux_abattement * impot_annuel_base

        # --- Montant de période : arrondissement UNIQUE et final, puis
        #     plancher à zéro ; comparé au montant retourné par égalité
        #     stricte (règle 01, tolérance nulle). ---
        resultat_reconstruit = max(
            Decimal("0.00"), _arrondir_2(impot_annuel_net / nb_periodes)
        )
        assert resultat_reconstruit == montant
        assert resultat_reconstruit == trace.resultat

        # --- Sous-totaux de la trace : comparés à l'arrondi au cent de la
        #     reconstruction pleine précision (valeurs d'affichage/audit,
        #     alignement sur `impot_qc.py`), PAS à la pleine précision. ---
        assert trace.sous_totaux["revenu_imposable_annuel"] == _arrondir_2(
            revenu_imposable_annuel
        )
        assert trace.sous_totaux["impot_avant_credits"] == _arrondir_2(
            impot_avant_credits
        )
        assert trace.sous_totaux["k1"] == _arrondir_2(k1)
        assert trace.sous_totaux["k2q"] == _arrondir_2(k2q)
        assert trace.sous_totaux["k4"] == _arrondir_2(k4)
        assert trace.sous_totaux["impot_annuel_base"] == _arrondir_2(
            impot_annuel_base
        )
        assert trace.sous_totaux["impot_annuel_net"] == _arrondir_2(
            impot_annuel_net
        )

    # Feature: impots-retenues-source, Property 8: Comportement sous le seuil d'imposition (fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_credit_fed_eleve(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_seuil
    def test_property_8_comportement_sous_le_seuil_d_imposition(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` dont le crédit personnel fédéral
        (`montant_total_TD1_effectif`) est très élevé, lorsque le revenu
        imposable annuel devient inférieur ou égal à ce crédit,
        `calcul_impot_federal_formule` retourne `Decimal("0.00")` sans lever
        d'exception — indépendamment de la valeur de `exoneration_TD1_effective`
        (la formule n'inspecte jamais ce drapeau, design §Components §4,
        Req 4.9).

        Justification du plancher (design §Correctness Properties 8) : quand
        `credit >= revenu_imposable_annuel`, `k1 = taux_credits_convertibles ×
        credit >= taux_credits_convertibles × revenu_imposable_annuel >=
        impot_avant_credits` ; comme `k2q >= 0` et `k4 >= 0`, le
        `max(0, impot_avant_credits − k1 − k2q − k4)` final produit
        `Decimal("0.00")`, propagé jusqu'au montant de période.

        **Validates: Requirements 4.6, 7.1, 12.5**
        """
        payroll_input, gains = entrees

        montant, trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )

        revenu_imposable_annuel = trace.sous_totaux["revenu_imposable_annuel"]
        credit_effectif = payroll_input.montant_total_TD1_effectif
        if revenu_imposable_annuel <= credit_effectif:
            assert montant == Decimal("0.00")

        # Indépendance vis-à-vis de l'exonération : la formule ignore ce
        # drapeau (Req 4.9), les deux valeurs donnent donc le même montant.
        for exoneration in (True, False):
            payroll_input_exo = payroll_input.model_copy(
                update={"exoneration_TD1_effective": exoneration}
            )
            montant_exo, _trace_exo = calcul_impot_federal_formule(
                payroll_input_exo, gains, parametres_annee
            )
            assert montant_exo == montant

    # Feature: impots-retenues-source, Property 9: Non-consultation des champs d'exonération/retenue additionnelle (fédéral)
    @pytest.mark.property
    @given(
        paire=_st_paire_input_exoneration_retenue_fed(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_9_non_consultation_exoneration_retenue_additionnelle(
        self,
        paire: tuple[PayrollInput, PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour toute* paire de `PayrollInput` identiques sauf sur
        `exoneration_TD1_effective` / `retenue_additionnelle_federale_effective`,
        `calcul_impot_federal_formule` retourne des résultats **identiques**
        — montant **et** trace (design §Correctness Properties 9, Req 4.9).
        La fonction formule n'inspecte aucun de ces deux champs.

        **Validates: Requirements 4.9**
        """
        payroll_input_base, payroll_input_variante, gains = paire

        resultat_base = calcul_impot_federal_formule(
            payroll_input_base, gains, parametres_annee
        )
        resultat_variante = calcul_impot_federal_formule(
            payroll_input_variante, gains, parametres_annee
        )

        assert resultat_base == resultat_variante
        assert resultat_base[0] == resultat_variante[0]
        assert resultat_base[1] == resultat_variante[1]

    def test_exemple_k1_k2q_k4_qc001(
        self,
        parametres_2026_qc_ca_federal: ParametresAnnee,
        fixtures_outputs_dir,
    ) -> None:
        """Test d'exemple — reproduction chiffrée du mécanisme complet sur QC001.

        Scénario QC001 (`tests/fixtures/outputs/qc001.json`) : brut de
        période `1 516,32 $`, 27 périodes, TD1 `16 452,00 $`, aucune
        exonération. Le design §Overview « Découverte de recherche
        déterminante » démontre que seul le mécanisme complet K1 + K2Q + K4
        suivi de l'abattement du Québec reproduit la valeur golden
        `86,25 $` (`K1 ≈ 2 303,28 $`, `K2Q ≈ 377,08 $`, `K4 ≈ 210,14 $`) —
        un K1 seul produirait ~104 $ ou ~88 $, jamais `86,25 $`.

        La valeur attendue est **lue directement dans la fixture de sortie**
        (`impot_federal_formule.montant`) plutôt que codée en dur, puis
        confrontée au montant et à `trace.resultat` retournés par la
        formule. Les paramètres 2026 sont réels (`load_parameters` via la
        fixture `parametres_2026_qc_ca_federal`, règle 05).

        **Validates: Requirements 4.3, 4.4, 9.7**
        """
        payroll_input = _payroll_input_qc001_pour_exemple()
        gains = _construire_gains_decomposes(Decimal("1516.32"))

        sortie = json.loads(
            (fixtures_outputs_dir / "qc001.json").read_text(encoding="utf-8")
        )
        montant_attendu = Decimal(
            sortie["retenues_employe"]["impot_federal_formule"]["montant"]
        )
        assert montant_attendu == Decimal("86.25")

        montant, trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_2026_qc_ca_federal
        )

        assert montant == montant_attendu
        assert trace.resultat == montant_attendu

    @pytest.mark.parametrize("scenario", ["qc004", "qc006"])
    def test_exemple_federal_formule_nulle(
        self,
        scenario: str,
        fixtures_inputs_dir,
        fixtures_outputs_dir,
        parametres_2026_qc_ca_federal: ParametresAnnee,
    ) -> None:
        """Test d'exemple — retenue fédérale par la seule formule à `0,00 $`
        sur QC004 et QC006 (Requirement 7.3, 11.7).

        QC004 (revenu annualisé sous le crédit personnel fédéral,
        `exoneration_TD1_effective == False`) et QC006 (exonération TD1
        active, formule néanmoins nulle) produisent tous deux
        `impot_federal_formule == Decimal("0.00")` (design §Overview, valeurs
        golden `0,00 $`). Comme `calcul_impot_federal_formule` ignore
        l'exonération (Req 4.9), le résultat nul provient dans les deux cas
        de la seule formule (comportement sous le seuil d'imposition), pas
        d'un court-circuit.

        Le `PayrollInput` est chargé depuis la fixture d'entrée réelle et le
        `GainsDecomposes` reconstruit depuis la section `gains` de la fixture
        de sortie ; la valeur attendue est lue dans
        `impot_federal_formule.montant` de la fixture de sortie. Paramètres
        2026 réels (`load_parameters` via `parametres_2026_qc_ca_federal`,
        règle 05).

        **Validates: Requirements 7.2, 7.3**
        """
        texte_entree = (fixtures_inputs_dir / f"{scenario}.json").read_text(
            encoding="utf-8"
        )
        payroll_input = PayrollInput.model_validate_json(texte_entree)

        sortie = json.loads(
            (fixtures_outputs_dir / f"{scenario}.json").read_text(encoding="utf-8")
        )
        gains = GainsDecomposes.model_validate(sortie["gains"])
        montant_attendu = Decimal(
            sortie["retenues_employe"]["impot_federal_formule"]["montant"]
        )
        assert montant_attendu == Decimal("0.00")

        montant, trace = calcul_impot_federal_formule(
            payroll_input, gains, parametres_2026_qc_ca_federal
        )

        assert montant == Decimal("0.00")
        assert trace.resultat == Decimal("0.00")


# ---------------------------------------------------------------------------
# 3.4 — Court-circuit d'exonération et retenue additionnelle fédérale
#       (Property 10, Property 11 — variantes fédérales)
# ---------------------------------------------------------------------------
#
# Property 10 vérifie le contrat de **valeur** de `calcul_impot_federal_retenu`
# (design §Components §5) : sous exonération TD1 active, la retenue effective
# se réduit à la seule `retenue_additionnelle_federale_effective` (le montant
# de base est court-circuité à `Decimal("0.00")`) ; sinon, la retenue vaut
# `calcul_impot_federal_formule(...)[0] + retenue_additionnelle_federale_effective`.
# Dans les deux cas la retenue additionnelle s'ajoute inconditionnellement
# (Req 5.2).
#
# Property 11 vérifie le contrat **structurel** : le court-circuit est
# **véritable** (Req 5.3) — sous exonération active, la fonction formule
# n'est jamais invoquée, pas même pour construire la trace. Un espion
# (`unittest.mock.patch`) posé sur `calcul_impot_federal_formule` dans le
# **namespace du module** `payroll_engine.impot_federal` (là où
# `calcul_impot_federal_retenu` résout le nom) doit rester non appelé.
#
# Règle 01 : `Decimal` exclusivement dans les assertions. Règle 05 : aucun
# taux/seuil n'est codé en dur ici — les montants proviennent de la formule
# et des champs `payroll_input`.


@st.composite
def _st_entrees_exoneration_td1_active(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes]:
    """`(PayrollInput, GainsDecomposes)` avec `exoneration_TD1_effective == True`.

    Part de `_st_entrees_completes()` (qui couvre déjà salaire nul ou
    élevé, crédit personnel fédéral nul/normal/élevé et cumul YTD nul ou
    proche du plafond) puis force le drapeau d'exonération fédérale à
    `True` sans mutation en place (`model_copy(update=...)` — règle 06,
    immuabilité). Utilisée par Property 11 (court-circuit véritable), qui
    exige un `PayrollInput` sous exonération active pour vérifier que la
    fonction formule n'est jamais invoquée.

    La retenue additionnelle fédérale est en outre tirée
    (`_st_retenue_additionnelle_federale()`) entre valeurs nulle et
    élevée, afin que Property 11 vérifie aussi l'ajout inconditionnel de
    cette retenue sous exonération active.
    """
    payroll_input, gains = draw(_st_entrees_completes())
    payroll_input = payroll_input.model_copy(
        update={
            "exoneration_TD1_effective": True,
            "retenue_additionnelle_federale_effective": draw(
                _st_retenue_additionnelle_federale()
            ),
        }
    )
    return payroll_input, gains


class TestRetenueFederale:
    """Property 10, 11 (variantes fédérales) — retenue d'impôt fédéral effective.

    Design (§Correctness Properties 10, 11 ; §Components §5). Ces deux
    propriétés portent sur `calcul_impot_federal_retenu` : court-circuit
    d'exonération et ajout inconditionnel de la retenue additionnelle
    (Property 10, contrat de valeur), et court-circuit **véritable**
    vérifié par espion sur la fonction formule (Property 11, contrat
    structurel). Un test d'exemple confirme le cas « exonération active +
    retenue additionnelle strictement positive » (Requirement 12.2).
    """

    # Feature: impots-retenues-source, Property 10: Court-circuit d'exonération et ajout de la retenue additionnelle (fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_10_court_circuit_et_ajout_retenue_additionnelle(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides :

        - si `exoneration_TD1_effective == True`, `calcul_impot_federal_retenu`
          retourne **exactement** `retenue_additionnelle_federale_effective`
          (le montant de base est court-circuité à `Decimal("0.00")`) ;
        - si `exoneration_TD1_effective == False`, `calcul_impot_federal_retenu`
          retourne **exactement** `calcul_impot_federal_formule(...)[0] +
          retenue_additionnelle_federale_effective`.

        Dans les deux cas la retenue additionnelle s'ajoute
        inconditionnellement (design §Correctness Properties 10,
        Req 5.2). L'entrée générée est déclinée en deux variantes ne
        différant que par le drapeau d'exonération (`model_copy` — aucune
        mutation), toutes deux comparées par égalité stricte `Decimal`
        (tolérance nulle, règle 01).

        **Validates: Requirements 5.1, 5.2, 12.2**
        """
        payroll_input, gains = entrees

        # --- Exonération active : montant de base court-circuité à zéro ---
        payroll_input_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": True}
        )
        montant_exo, _trace_exo = calcul_impot_federal_retenu(
            payroll_input_exo, gains, parametres_annee
        )
        assert (
            montant_exo
            == payroll_input_exo.retenue_additionnelle_federale_effective
        )

        # --- Exonération inactive : formule + retenue additionnelle ---
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": False}
        )
        montant_formule, _trace_formule = calcul_impot_federal_formule(
            payroll_input_non_exo, gains, parametres_annee
        )
        montant_retenu, _trace_retenu = calcul_impot_federal_retenu(
            payroll_input_non_exo, gains, parametres_annee
        )
        assert (
            montant_retenu
            == montant_formule
            + payroll_input_non_exo.retenue_additionnelle_federale_effective
        )

    # Feature: impots-retenues-source, Property 11: Court-circuit véritable (formule non invoquée sous exonération) (fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_exoneration_td1_active(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_11_court_circuit_veritable_formule_non_invoquee(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` tel que
        `exoneration_TD1_effective == True`, un espion posé sur
        `calcul_impot_federal_formule` dans le **namespace du module**
        `payroll_engine.impot_federal` (là où `calcul_impot_federal_retenu`
        résout le nom) n'est **jamais appelé** lors de l'exécution de
        `calcul_impot_federal_retenu` — le court-circuit est véritable, pas
        un simple remplacement du résultat par zéro après calcul (design
        §Correctness Properties 11, Req 5.3).

        Le patch cible bien
        `payroll_engine.impot_federal.calcul_impot_federal_formule` (le nom
        tel que la fonction retenue le résout via ses globals de module) et
        non le nom réimporté dans ce module de test.

        **Validates: Requirements 5.3**
        """
        payroll_input, gains = entrees
        assert payroll_input.exoneration_TD1_effective is True

        with patch(
            "payroll_engine.impot_federal.calcul_impot_federal_formule"
        ) as espion_formule:
            montant, _trace = calcul_impot_federal_retenu(
                payroll_input, gains, parametres_annee
            )

        espion_formule.assert_not_called()
        # Cohérence : sous exonération active, la retenue effective se
        # réduit à la seule retenue additionnelle (montant de base nul).
        assert (
            montant == payroll_input.retenue_additionnelle_federale_effective
        )

    def test_exemple_exoneration_active_retenue_additionnelle_positive(
        self,
        fixtures_inputs_dir,
        fixtures_outputs_dir,
        parametres_2026_qc_ca_federal: ParametresAnnee,
    ) -> None:
        """Test d'exemple — exonération TD1 active + retenue additionnelle
        fédérale strictement positive (Requirement 12.2).

        Le `PayrollInput` de QC001 est chargé depuis la fixture d'entrée
        réelle puis décliné (`model_copy` — aucune mutation) pour activer
        l'exonération TD1 et porter une retenue additionnelle fédérale
        strictement positive (`25,00 $`). Aucune fixture du corpus
        QC001–QC006 ne combine exonération active et retenue additionnelle
        non nulle (Introduction des requirements) : ce cas n'est donc
        couvert que par ce test d'exemple et par Property 10.

        La retenue effective attendue est **strictement égale** à la
        retenue additionnelle (le montant de base est court-circuité à
        `Decimal("0.00")`), et la trace expose `retenue_effective ==
        montant`. Les paramètres 2026 sont les paramètres réels
        (`load_parameters` via `parametres_2026_qc_ca_federal`, règle 05).

        **Validates: Requirements 5.1, 5.2, 12.2**
        """
        texte_entree = (fixtures_inputs_dir / "qc001.json").read_text(
            encoding="utf-8"
        )
        payroll_input = PayrollInput.model_validate_json(texte_entree)

        sortie = json.loads(
            (fixtures_outputs_dir / "qc001.json").read_text(encoding="utf-8")
        )
        gains = GainsDecomposes.model_validate(sortie["gains"])

        retenue_additionnelle = Decimal("25.00")
        payroll_input = payroll_input.model_copy(
            update={
                "exoneration_TD1_effective": True,
                "retenue_additionnelle_federale_effective": retenue_additionnelle,
            }
        )
        assert payroll_input.exoneration_TD1_effective is True
        assert (
            payroll_input.retenue_additionnelle_federale_effective
            > Decimal("0.00")
        )

        montant, trace = calcul_impot_federal_retenu(
            payroll_input, gains, parametres_2026_qc_ca_federal
        )

        assert montant == retenue_additionnelle
        assert trace.resultat == retenue_additionnelle


# ---------------------------------------------------------------------------
# 3.5 — Trace des deux fonctions fédérales (Property 12, variante fédérale)
# ---------------------------------------------------------------------------
#
# Property 12 (variante fédérale) porte simultanément sur les deux
# fonctions fédérales (`calcul_impot_federal_formule` et
# `calcul_impot_federal_retenu`, design §Correctness Properties 12 ;
# §Components §4, §5). Elle vérifie le contenu minimal et la cohérence de
# la trace : source sur liste blanche T4127, année et juridiction
# attendues, section distinguant « formule » de « retenu », clés minimales
# de `entrees` / `parametres_utilises` / `sous_totaux`, et invariants
# d'arrondissement / résultat (`ModeArrondissement.ROUND_HALF_UP`,
# précision `2`, `resultat == montant`). Règle 01 : toutes les
# comparaisons de montants portent sur des `Decimal` (tolérance nulle).

#: Expression régulière du préfixe de source fédéral exigé par Property 12
#: (design §Correctness Properties 12 ; §Components §4 : `source =
#: f"T4127 {annee_fiscale}, section 3 — Impôt fédéral"`) : ``"T4127 "``
#: suivi d'un millésime à quatre chiffres. Compilée une fois au niveau
#: module.
_MOTIF_SOURCE_FEDERAL = re.compile(r"^T4127 \d{4}")


class TestTraceFederale:
    """Property 12 (variante fédérale) — contenu minimal et cohérence de la trace.

    Design (§Correctness Properties 12 ; §Components §4, §5). Cette
    propriété couvre **les deux** fonctions fédérales dans un même test :
    la trace de `calcul_impot_federal_formule` (source T4127, section
    « formule », `entrees` minimales
    `salaire_periode`/`nb_periodes_annuelles`/`deduction_rrq_supp`,
    `sous_totaux` minimal `revenu_imposable_periode`) et celle de
    `calcul_impot_federal_retenu` (section « retenu »,
    `parametres_utilises` minimal `exoneration_active`, `entrees` minimal
    `impot_federal_formule`, `sous_totaux` minimal `retenue_effective`).
    Les invariants communs (source sur liste blanche, `annee`,
    `juridiction`, arrondissement, `resultat == montant`) sont vérifiés
    pour les deux traces.
    """

    # Feature: impots-retenues-source, Property 12: Contenu minimal et cohérence de la trace (fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_12_contenu_minimal_et_coherence_de_la_trace(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de
        `calcul_impot_federal_formule` et `calcul_impot_federal_retenu`
        satisfont le contenu minimal et la cohérence exigés par
        Property 12 (design §Correctness Properties 12 ; §Components
        §4, §5) :

        Invariants communs aux deux traces :

        - `trace.source` matche `^T4127 \\d{4}` (liste blanche T4127,
          préfixée d'un millésime à quatre chiffres) ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` ;
        - `trace.juridiction == Juridiction.CANADA` ;
        - `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`,
          `trace.precision_arrondissement == 2` ;
        - `trace.resultat` égal au montant retourné.

        Spécifique à la formule (design §Components §4) :

        - `trace.section` contient « formule » (et pas « retenu ») ;
        - `trace.entrees` contient au minimum `salaire_periode`,
          `nb_periodes_annuelles` et `deduction_rrq_supp` ;
        - `trace.sous_totaux` contient au minimum
          `revenu_imposable_periode`.

        Spécifique à la retenue (design §Components §5) :

        - `trace.section` contient « retenu » ;
        - `trace.parametres_utilises` contient `exoneration_active` ;
        - `trace.entrees` contient `impot_federal_formule` ;
        - `trace.sous_totaux` contient `retenue_effective`.

        **Validates: Requirements 5.6, 9.1, 9.2, 9.3, 9.4, 9.5**
        """
        payroll_input, gains = entrees
        annee_attendue = payroll_input.pay_period.annee_fiscale

        # --- Trace de calcul_impot_federal_formule (design §Components §4) ---
        montant_formule, trace_formule = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )

        assert _MOTIF_SOURCE_FEDERAL.match(trace_formule.source) is not None
        assert trace_formule.annee == annee_attendue
        assert trace_formule.juridiction == Juridiction.CANADA
        assert "formule" in trace_formule.section
        assert "retenu" not in trace_formule.section
        assert "salaire_periode" in trace_formule.entrees
        assert "nb_periodes_annuelles" in trace_formule.entrees
        assert "deduction_rrq_supp" in trace_formule.entrees
        assert "revenu_imposable_periode" in trace_formule.sous_totaux
        assert trace_formule.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
        assert trace_formule.precision_arrondissement == 2
        assert trace_formule.resultat == montant_formule

        # --- Trace de calcul_impot_federal_retenu (design §Components §5) ---
        montant_retenu, trace_retenu = calcul_impot_federal_retenu(
            payroll_input, gains, parametres_annee
        )

        assert _MOTIF_SOURCE_FEDERAL.match(trace_retenu.source) is not None
        assert trace_retenu.annee == annee_attendue
        assert trace_retenu.juridiction == Juridiction.CANADA
        assert "retenu" in trace_retenu.section
        assert "exoneration_active" in trace_retenu.parametres_utilises
        assert "impot_federal_formule" in trace_retenu.entrees
        assert "retenue_effective" in trace_retenu.sous_totaux
        assert trace_retenu.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
        assert trace_retenu.precision_arrondissement == 2
        assert trace_retenu.resultat == montant_retenu


# ---------------------------------------------------------------------------
# 3.6 — Propagation de MissingParameterError (Property 13, variante fédérale)
# ---------------------------------------------------------------------------
#
# Property 13 (variante fédérale) porte sur les deux fonctions fédérales
# (`calcul_impot_federal_formule` et, par délégation structurelle stricte,
# `calcul_impot_federal_retenu` lorsque l'exonération est inactive —
# design §Components §5, Req 5.3). Pour chacun des champs de la section
# `impot_federal` consommés par la formule fédérale (design §Correctness
# Properties 13 — `paliers[i].taux`, `taux_credits_convertibles`,
# `montant_emploi_canadien_annuel`, `plafond_cotisation_base_rrq_annuel`,
# `taux_abattement_quebec`), marquer ce champ `"TO_FILL"` dans le
# `ParametresAnnee` (via `st_parametres_annee_impot_avec_to_fill`) DOIT
# faire lever `MissingParameterError` à l'appel, non interceptée ni
# masquée par une autre exception (design §Error Handling « Matrice des
# exceptions », Requirements 1.8, 10.5).
#
# Délégation (Req 5.3) : `calcul_impot_federal_retenu` n'invoque
# `calcul_impot_federal_formule` — et ne lit donc les paramètres de la
# section `impot_federal` — que lorsque `exoneration_TD1_effective ==
# False`. Sous exonération active, le court-circuit véritable ne touche
# jamais les paramètres et ne lèverait pas `MissingParameterError` (le
# montant de base est forcé à `Decimal("0.00")`). Les tests ci-dessous
# forcent donc `exoneration_TD1_effective = False` (`model_copy(update=
# ...)` — règle 06, immuabilité) avant d'exercer la délégation sur
# `calcul_impot_federal_retenu`.
#
# Ordonnancement (règle 06 — tests avant code) : la stratégie
# `st_parametres_annee_impot_avec_to_fill` cible les propriétés typées
# `Palier.taux` et les attributs `*_brut` de la section `impot_federal`,
# qui ne sont matérialisés qu'à partir de la tâche 7.2 ;
# `payroll_engine/impot_federal.py` n'existe qu'à partir de la tâche 10.1.
# La collecte pytest de ce fichier échoue donc actuellement avec
# `ModuleNotFoundError` sur `payroll_engine.impot_federal` (import au
# niveau module) — état rouge attendu et correct à ce stade.
#
# Règle 01 : aucune valeur monétaire `float` n'est manipulée ; la
# sentinelle `"TO_FILL"` reste une chaîne portée par la stratégie.


class TestMissingParameterImpotFederal:
    """Property 13 (variante fédérale) — propagation de
    `MissingParameterError` sans interception.

    Design (§Correctness Properties 13 ; §Error Handling « Matrice des
    exceptions »). Pour chacun des champs de la section `impot_federal`
    consommés par `calcul_impot_federal_formule` (et, par délégation
    stricte, par `calcul_impot_federal_retenu` lorsque l'exonération est
    inactive — Req 5.3) — `paliers[0].taux`, `taux_credits_convertibles`,
    `montant_emploi_canadien_annuel`, `plafond_cotisation_base_rrq_annuel`,
    `taux_abattement_quebec` — marquer ce champ `"TO_FILL"` dans le
    `ParametresAnnee` (via `st_parametres_annee_impot_avec_to_fill`) DOIT
    faire lever `MissingParameterError` à l'appel, non interceptée ni
    masquée par une autre exception (Requirements 1.8, 10.5).
    """

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_federal.paliers[0].taux"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_palier_taux(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `impot_federal.paliers[0].taux` porte la
        sentinelle `"TO_FILL"`, `calcul_impot_federal_formule` lève
        `MissingParameterError` non interceptée. Sous exonération inactive
        (`exoneration_TD1_effective = False`),
        `calcul_impot_federal_retenu` propage la même exception par
        délégation structurelle (Req 5.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_federal.taux_credits_convertibles"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_taux_credits_convertibles(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `impot_federal.taux_credits_convertibles`
        porte la sentinelle `"TO_FILL"`, `calcul_impot_federal_formule`
        lève `MissingParameterError` non interceptée, et
        `calcul_impot_federal_retenu` la propage par délégation lorsque
        l'exonération est inactive (Req 5.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_federal.montant_emploi_canadien_annuel"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_montant_emploi_canadien_annuel(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont
        `impot_federal.montant_emploi_canadien_annuel` porte la sentinelle
        `"TO_FILL"`, `calcul_impot_federal_formule` lève
        `MissingParameterError` non interceptée, et
        `calcul_impot_federal_retenu` la propage par délégation lorsque
        l'exonération est inactive (Req 5.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_federal.plafond_cotisation_base_rrq_annuel"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_plafond_cotisation_base_rrq_annuel(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont
        `impot_federal.plafond_cotisation_base_rrq_annuel` porte la
        sentinelle `"TO_FILL"`, `calcul_impot_federal_formule` lève
        `MissingParameterError` non interceptée, et
        `calcul_impot_federal_retenu` la propage par délégation lorsque
        l'exonération est inactive (Req 5.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt fédéral)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_federal.taux_abattement_quebec"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_taux_abattement_quebec(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `impot_federal.taux_abattement_quebec`
        porte la sentinelle `"TO_FILL"`, `calcul_impot_federal_formule`
        lève `MissingParameterError` non interceptée, et
        `calcul_impot_federal_retenu` la propage par délégation lorsque
        l'exonération est inactive (Req 5.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TD1_effective": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_federal_retenu(payroll_input_non_exo, gains, parametres_annee)
