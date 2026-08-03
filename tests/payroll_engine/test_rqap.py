"""Property tests et tests d'exemple pour `calcul_rqap_employe`/`calcul_rqap_employeur`.

Spec de référence : ``cotisations-sociales-qc`` — tâche 3.1 (squelette).
Design de référence : ``design.md`` §Testing Strategy, §Correctness
Properties 1, 2, 3, §Components §1, §4, §5.

Ce fichier est actuellement un **squelette** (tâche 3.1 uniquement) : il
porte les imports, la fixture de vérification des paramètres, la
configuration Hypothesis partagée, la stratégie de génération commune
(``_st_contexte_calcul_rqap``) et les trois propriétés transversales
applicables indifféremment aux deux fonctions RQAP (Property 1
« Déterminisme », Property 2 « Absence d'exception sur entrée valide »,
Property 3 « Forme `Decimal` du résultat et de la trace »). Les propriétés
spécifiques à la formule, au plafonnement, à l'indépendance de l'employeur
RQAP (anomalie QC004), à la trace détaillée et à la propagation de
`MissingParameterError` seront ajoutées par les tâches 3.2 à 3.5.

Contrairement à ``tests/payroll_engine/test_gains_bruts.py`` (dont
`payroll_engine/gains_bruts.py` était absent au moment de son écriture,
d'où le choix d'un import local par test pour rester collectable), ce
fichier importe `calcul_rqap_employe` et `calcul_rqap_employeur`
**au niveau module** — cohérent avec la majorité des autres fichiers de
test du dépôt (ex. ``tests/payroll_engine/test_parameters_loader.py``).
`payroll_engine/rqap.py` n'existe pas encore à ce stade (tâche 10.1 non
réalisée) : l'import échoue avec `ModuleNotFoundError`, ce qui est
**attendu et correct** conformément à la règle 06 (tests avant code).
Ce fichier redeviendra collectable et exécutable dès que la tâche 10.1
aura livré `payroll_engine/rqap.py`.

Stratégie de génération commune (design §Testing Strategy) : un
`PayrollInput` valide avec `cumuls_debut` généré — y compris des cumuls
non nuls pour exercer le plafonnement en cours de saison, absent du
corpus golden (Introduction des requirements : toutes les fixtures
QC001–QC006 sont des paies n° 1, cumul YTD nul) —, un `GainsDecomposes`
valide (`brut_total >= 0`, biaisé vers zéro) et le `ParametresAnnee` réel
2026 (fusion Québec + Canada) chargé une seule fois. Cette stratégie
(`_st_contexte_calcul_rqap`) est réutilisée par les tâches 3.2 à 3.5.

Règle 01 : tous les montants manipulés par ces tests sont des `Decimal`
(jamais de `float`), y compris dans les assertions de comparaison.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction, ModeArrondissement
from models.exceptions import MissingParameterError
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.payroll_result import GainsDecomposes
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters
from payroll_engine.rqap import calcul_rqap_employe, calcul_rqap_employeur
from tests.strategies import (  # noqa: F401
    st_brut_total_avec_zero,
    st_cumuls_ytd_non_nuls,
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_avec_to_fill,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Fonctions ciblées par ce fichier (tâche 3.1)
# ---------------------------------------------------------------------------
#
# Regroupées ici pour permettre le paramétrage des tests transversaux sur
# les deux fonctions RQAP (design §Correctness Properties 1, 2, 3 :
# « pour chacune des six fonctions », restreint aux deux fonctions RQAP
# dans ce fichier).
_FONCTIONS_RQAP: tuple = (calcul_rqap_employe, calcul_rqap_employeur)
_NOMS_FONCTIONS_RQAP: tuple[str, ...] = (
    "calcul_rqap_employe",
    "calcul_rqap_employeur",
)


# ---------------------------------------------------------------------------
# Fixture module-scoped : paramètres 2026 Québec + Canada fusionnés
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parametres_2026_qc_ca() -> ParametresAnnee:
    """Charge une seule fois les paramètres 2026 fusionnés Québec + Canada.

    Design (§Testing Strategy « Stratégies Hypothesis ») : reproduit la
    fusion effectuée par ``tests.strategies._charger_parametres_annee_2026_qc_ca``
    (``rrq``/``rqap`` de Québec + ``assurance_emploi`` du Canada sur la
    même racine ``ParametresAnnee``), sans dépendre de cette fonction
    privée. Portée ``module`` : le chargement n'a lieu qu'une seule fois
    pour ce fichier de test.

    Vérification de non-régression (miroir de
    ``tests/payroll_engine/test_gains_bruts.py``, Req 9.6) : les quatre
    paramètres RQAP consommés par ``calcul_rqap_employe`` et
    ``calcul_rqap_employeur`` (design §Components §4, §5) doivent être
    accessibles sans lever ``MissingParameterError`` — si une future
    édition de ``parameters/2026/quebec.json`` introduisait
    accidentellement une sentinelle ``"TO_FILL"`` sur l'un de ces champs,
    toute la suite de tests de ce fichier échouerait immédiatement ici.
    """
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    parametres = parametres_qc.model_copy(
        update={"assurance_emploi": parametres_ca.assurance_emploi}
    )

    assert parametres.rqap.taux_employe.is_finite()
    assert parametres.rqap.taux_employeur.is_finite()
    assert parametres.rqap.cotisation_max_employe.is_finite()
    assert parametres.rqap.cotisation_max_employeur.is_finite()

    return parametres


# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée
# ---------------------------------------------------------------------------

# Design (§Testing Strategy « Configuration Hypothesis ») : pas de deadline
# (les modèles Pydantic composés peuvent dépasser 200 ms/exemple sous
# charge), et suppression du health check "too_slow" — cohérent avec
# ``tests/payroll_engine/test_gains_bruts.py``. Le nombre d'exemples est
# piloté par le profil Hypothesis actif (voir ``tests/conftest.py`` :
# dev=15 par défaut, ci=100).
settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Stratégie de génération commune (design §Testing Strategy)
# ---------------------------------------------------------------------------


def _construire_gains_decomposes(brut_total: Decimal) -> GainsDecomposes:
    """Construit un `GainsDecomposes` valide pour un `brut_total` donné.

    Helper local (non une stratégie Hypothesis) : loge tout le brut dans
    `salaire_regulier` et met les autres composantes à zéro — acceptable
    au niveau du contrat, `GainsDecomposes` n'imposant PAS
    `salaire_regulier + heures_supp + vacances + feries == brut_total`
    (design ``gains-bruts-vacances-hs`` §Data Models 9, confirmé par
    ``tests/models/test_payroll_result.py::_make_gains``). Les deux
    valeurs de contexte heures supplémentaires
    (`multiplicateur_heures_supp`, `seuil_heures_supp_hebdo`) ne sont
    consommées par aucune des six fonctions de cette spec (design
    §Components §1 : seul `gains.brut_total` est lu) — des constantes
    structurelles fixes (`1.5`, `40`) suffisent ici, cohérentes avec les
    valeurs déjà utilisées par `tests/models/test_payroll_result.py`.
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
def _st_contexte_calcul_rqap(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """`(PayrollInput, GainsDecomposes, ParametresAnnee)` valides pour RQAP.

    Design (§Testing Strategy « Stratégies Hypothesis ») : stratégie de
    génération commune à toutes les propriétés de ce fichier.

    - `PayrollInput` : `st_payroll_input()` (Québec, aux deux semaines,
      cohérent par construction) dont `cumuls_debut` est **remplacé**
      par un `CumulsYTD` tiré de `st_cumuls_ytd_non_nuls()` — biaisé vers
      `[0, plafond]` et vers le plafond exact — pour exercer le
      plafonnement en cours de saison (cas non couvert par le corpus
      golden, toutes les fixtures QC001–QC006 étant des paies n° 1,
      cumul YTD nul). `employe_id` et `annee_civile` du cumul tiré sont
      réécrits pour rester appariés à `employee.id` /
      `pay_period.annee_fiscale` (invariant de construction de
      `PayrollInput`, Req 3.1) — `CumulsYTD` étant `frozen=True`, la
      réécriture passe par `model_copy(update=...)`, sans mutation.
    - `GainsDecomposes` : `brut_total` tiré de `st_brut_total_avec_zero()`
      (biaisé vers `Decimal("0.00")`, Property 6), via
      `_construire_gains_decomposes`.
    - `ParametresAnnee` : `st_parametres_annee_2026_qc_ca()` — instance
      réelle 2026 fusionnée Québec + Canada, mémorisée au niveau module
      (règle 05 : aucune valeur fiscale codée en dur).
    """
    payroll_input_base = draw(st_payroll_input())
    cumuls_tires = draw(st_cumuls_ytd_non_nuls())
    cumuls_ajustes: CumulsYTD = cumuls_tires.model_copy(
        update={
            "employe_id": payroll_input_base.employee.id,
            "annee_civile": payroll_input_base.pay_period.annee_fiscale,
        }
    )
    payroll_input = payroll_input_base.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )

    brut_total = draw(st_brut_total_avec_zero())
    gains = _construire_gains_decomposes(brut_total)

    parametres_annee = draw(st_parametres_annee_2026_qc_ca())

    return payroll_input, gains, parametres_annee


# ---------------------------------------------------------------------------
# 3.1 — Signature, pureté et robustesse (Property 1, 2, 3)
# ---------------------------------------------------------------------------


class TestSignaturePureteRobustesse:
    """Property 1, 2, 3 — déterminisme, absence d'exception, forme `Decimal`.

    Design (§Correctness Properties 1, 2, 3 ; §Components §1 « Signature
    exacte »). Les trois propriétés sont appliquées indifféremment à
    `calcul_rqap_employe` et `calcul_rqap_employeur` via
    `pytest.mark.parametrize`, plus un test d'exemple vérifiant
    l'absence d'effet de bord à l'import (Req 1.10).
    """

    # Feature: cotisations-sociales-qc, Property 1: Déterminisme (pureté)
    @pytest.mark.property
    @pytest.mark.parametrize(
        "fonction", _FONCTIONS_RQAP, ids=_NOMS_FONCTIONS_RQAP
    )
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_1_deux_appels_identiques_produisent_des_tuples_egaux(
        self,
        fonction,
        contexte,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, `f(pi, g, p) == f(pi, g, p)` — deux appels avec les mêmes
        arguments produisent deux tuples égaux au sens `==` sur les deux
        composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.4**

        Aucun état interne persistant, aucune source de non-déterminisme
        (règle 06 « fonction pure ») : `payroll_input`, `gains` et
        `parametres_annee` sont tous immuables (`frozen=True`) — deux
        appels successifs avec les mêmes arguments doivent produire deux
        résultats structurellement identiques.
        """
        payroll_input, gains, parametres_annee = contexte

        resultat_1 = fonction(payroll_input, gains, parametres_annee)
        resultat_2 = fonction(payroll_input, gains, parametres_annee)

        assert resultat_1 == resultat_2
        assert resultat_1[0] == resultat_2[0]
        assert resultat_1[1] == resultat_2[1]

    # Feature: cotisations-sociales-qc, Property 2: Absence d'exception sur entrée valide
    @pytest.mark.property
    @pytest.mark.parametrize(
        "fonction", _FONCTIONS_RQAP, ids=_NOMS_FONCTIONS_RQAP
    )
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_2_aucune_exception_sur_entree_valide(
        self,
        fonction,
        contexte,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides (paramètres 2026 entièrement renseignés), `f(pi, g, p)`
        retourne un tuple sans lever aucune exception — y compris pour
        les cas extrêmes générés : salaire admissible nul ou très élevé
        (`st_brut_total_avec_zero`), cumul YTD nul ou proche du plafond
        (`st_cumuls_ytd_non_nuls`, via `_st_contexte_calcul_rqap`).

        **Validates: Requirements 1.9, 14.1**
        """
        payroll_input, gains, parametres_annee = contexte

        resultat = fonction(payroll_input, gains, parametres_annee)

        assert resultat is not None

    # Feature: cotisations-sociales-qc, Property 3: Forme Decimal du résultat et de la trace
    @pytest.mark.property
    @pytest.mark.parametrize(
        "fonction", _FONCTIONS_RQAP, ids=_NOMS_FONCTIONS_RQAP
    )
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_3_forme_decimal_du_resultat_et_de_la_trace(
        self,
        fonction,
        contexte,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant retourné et chaque valeur contenue dans
        `trace.parametres_utilises`, `trace.entrees`, `trace.sous_totaux`
        et `trace.resultat` satisfont :

        - `isinstance(v, Decimal)` — aucun `float` produit ;
        - `v.is_finite()` — pas de `NaN` ni d'infini ;
        - le montant retourné et `trace.resultat` sont arrondis à deux
          décimales selon `ROUND_HALF_UP`.

        **Validates: Requirements 4.5, 5.6**
        """
        payroll_input, gains, parametres_annee = contexte

        montant, trace = fonction(payroll_input, gains, parametres_annee)

        assert isinstance(montant, Decimal)
        assert montant.is_finite()
        assert montant == montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        for valeurs in (
            trace.parametres_utilises,
            trace.entrees,
            trace.sous_totaux,
        ):
            for v in valeurs.values():
                assert isinstance(v, Decimal)
                assert v.is_finite()

        assert isinstance(trace.resultat, Decimal)
        assert trace.resultat.is_finite()
        assert trace.resultat == trace.resultat.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def test_import_calcul_rqap_sans_effet_de_bord(self, capsys) -> None:
        """Test d'exemple — l'import de `payroll_engine.rqap` ne produit
        **aucun effet de bord** (Req 1.10) : pas d'ouverture de fichier,
        pas d'appel réseau, pas d'écriture sur `stdout` / `stderr`.

        Design (§Architecture « Contrainte de pureté »). Le module est
        retiré de `sys.modules` avant l'import (s'il y était déjà chargé,
        par exemple via l'import de tête de ce fichier) afin de forcer
        une exécution fraîche du corps du module — c'est justement au
        moment de cette exécution que d'éventuels effets de bord au
        niveau module (ouverture de fichier, `print`, connexion réseau,
        appel à `load_parameters`) se manifesteraient.

        Ce test échoue avec `ModuleNotFoundError` tant que
        `payroll_engine/rqap.py` n'existe pas (tâche 10.1) — attendu et
        correct conformément à la règle 06 (tests avant code).
        """
        import importlib
        import sys

        nom_module = "payroll_engine.rqap"
        sys.modules.pop(nom_module, None)

        importlib.import_module(nom_module)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert nom_module in sys.modules


# ---------------------------------------------------------------------------
# 3.2 — Formule proportionnelle et plafonnement RQAP employé
# (Property 4, 5, 6, 8 — variantes RQAP employé)
# ---------------------------------------------------------------------------


@st.composite
def _st_contexte_rqap_employe_cumul_au_plafond_ou_au_dela(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """Contexte RQAP dont `cumuls_debut.rqap_employe` >= plafond annuel.

    Design (§Correctness Properties 5) : « si `cumul_ytd_correspondant >=
    plafond_annuel_correspondant`, alors la fonction retourne
    `Decimal("0.00")` [...] quel que soit le `Salaire_Admissible` de la
    période ». Part de `_st_contexte_calcul_rqap()` (mêmes bornes de
    `brut_total`, mêmes paramètres 2026 réels) puis **remplace**
    `cumuls_debut.rqap_employe` par `plafond + surplus` — `surplus`
    biaisé vers `Decimal("0.00")` pour couvrir à la fois le cas limite
    « cumul exactement au plafond » et le cas « cumul au-delà du
    plafond » (`CumulsYTD.rqap_employe` n'impose qu'une borne inférieure
    `ge=0`, aucune borne supérieure — un cumul au-delà du plafond annuel
    reste un état représentable, par exemple après une correction
    manuelle en cours de saison). `CumulsYTD`/`PayrollInput` étant
    `frozen=True`, le remplacement passe par `model_copy(update=...)`,
    sans mutation (règle 06).
    """
    payroll_input, gains, parametres_annee = draw(_st_contexte_calcul_rqap())
    plafond = parametres_annee.rqap.cotisation_max_employe
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
        update={"rqap_employe": plafond + surplus}
    )
    payroll_input_ajuste = payroll_input.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )
    return payroll_input_ajuste, gains, parametres_annee


@st.composite
def _st_contexte_calcul_rqap_avec_brut_nul(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """Contexte RQAP dont `gains.brut_total` est fixé à `Decimal("0.00")`.

    Design (§Correctness Properties 6) : « *for any* `PayrollInput`,
    `GainsDecomposes` avec `brut_total == Decimal("0.00")` et
    `ParametresAnnee` valides [...] retourne `Decimal("0.00")` sans lever
    d'exception ». Réutilise `_st_contexte_calcul_rqap()` pour
    `payroll_input` (y compris un `cumuls_debut.rqap_employe`
    potentiellement non nul, quel qu'il soit — la propriété doit tenir
    « quel que soit le `Salaire_Admissible` », donc indépendamment de
    l'état du cumul) et `parametres_annee`, mais reconstruit `gains`
    avec `brut_total = Decimal("0.00")` via `_construire_gains_decomposes`.
    """
    payroll_input, _gains_non_utilises, parametres_annee = draw(
        _st_contexte_calcul_rqap()
    )
    gains = _construire_gains_decomposes(Decimal("0.00"))
    return payroll_input, gains, parametres_annee


class TestFormuleEtPlafonnementRqapEmploye:
    """Property 4, 5, 6, 8 (variantes RQAP employé) — formule proportionnelle
    sans exemption, bornes générales, plancher à zéro au plafond, zéro sur
    salaire nul.

    Design (§Correctness Properties 4, 5, 6, 8 ; §Components §4). Cette
    classe couvre exclusivement `calcul_rqap_employe` — les variantes
    employeur équivalentes (y compris l'anomalie QC004) sont ajoutées par
    la tâche 3.3 (`TestIndependanceEtPlafonnementRqapEmployeur`).
    """

    # Feature: cotisations-sociales-qc, Property 8: Formule proportionnelle sans exemption (RQAP employé)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_8_formule_proportionnelle_sans_exemption(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant théorique de période de `calcul_rqap_employe`
        (`trace.sous_totaux["cotisation_brute"]`) est égal à
        `arrondir(taux_employe × brut_total)` — **aucune** exemption
        n'est soustraite du `Salaire_Admissible` avant application du
        taux, contrairement à la formule RRQ (Property 7).

        **Validates: Requirements 4.1**
        """
        payroll_input, gains, parametres_annee = contexte

        _, trace = calcul_rqap_employe(payroll_input, gains, parametres_annee)

        montant_periode_attendu = (
            parametres_annee.rqap.taux_employe * gains.brut_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert trace.sous_totaux["cotisation_brute"] == montant_periode_attendu

    # Feature: cotisations-sociales-qc, Property 4: Bornes générales (RQAP employé)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_4_bornes_generales(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la cotisation RQAP employé effective satisfait
        `Decimal("0.00") <= cotisation <= montant_periode` (montant
        théorique de période, `trace.sous_totaux["cotisation_brute"]`) et
        `Cumul_YTD_RQAP_Employe + cotisation <=
        Plafond_Annuel_RQAP_Employe`.

        **Validates: Requirements 4.2, 4.3, 4.6, 14.4**
        """
        payroll_input, gains, parametres_annee = contexte

        cotisation, trace = calcul_rqap_employe(
            payroll_input, gains, parametres_annee
        )
        montant_periode = trace.sous_totaux["cotisation_brute"]
        cumul_ytd = payroll_input.cumuls_debut.rqap_employe
        plafond_annuel = parametres_annee.rqap.cotisation_max_employe

        assert Decimal("0.00") <= cotisation <= montant_periode
        assert cumul_ytd + cotisation <= plafond_annuel

    # Feature: cotisations-sociales-qc, Property 5: Plancher à zéro quand cumul >= plafond (RQAP employé)
    @pytest.mark.property
    @given(contexte=_st_contexte_rqap_employe_cumul_au_plafond_ou_au_dela())
    @settings_large_input
    def test_property_5_plancher_zero_quand_cumul_au_plafond_ou_au_dela(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput` dont `Cumul_YTD_RQAP_Employe >=
        Plafond_Annuel_RQAP_Employe`, `calcul_rqap_employe` retourne
        `Decimal("0.00")` sans lever d'exception, quel que soit le
        `Salaire_Admissible` de la période (`brut_total` généré par
        `st_brut_total_avec_zero()` via `_st_contexte_calcul_rqap`).

        **Validates: Requirements 4.4**
        """
        payroll_input, gains, parametres_annee = contexte
        assert (
            payroll_input.cumuls_debut.rqap_employe
            >= parametres_annee.rqap.cotisation_max_employe
        )

        cotisation, _ = calcul_rqap_employe(payroll_input, gains, parametres_annee)

        assert cotisation == Decimal("0.00")

    # Feature: cotisations-sociales-qc, Property 6: Zéro sur salaire nul (RQAP employé)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap_avec_brut_nul())
    @settings_large_input
    def test_property_6_zero_sur_salaire_nul(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput` et `ParametresAnnee` valides, et
        `GainsDecomposes` avec `brut_total == Decimal("0.00")`,
        `calcul_rqap_employe` retourne `Decimal("0.00")` sans lever
        d'exception — indépendamment de l'état de
        `cumuls_debut.rqap_employe`.

        **Validates: Requirements 14.1**
        """
        payroll_input, gains, parametres_annee = contexte
        assert gains.brut_total == Decimal("0.00")

        cotisation, _ = calcul_rqap_employe(payroll_input, gains, parametres_annee)

        assert cotisation == Decimal("0.00")


# ---------------------------------------------------------------------------
# 3.3 — Indépendance et plafonnement RQAP employeur, anomalie QC004
# (Property 4, 5, 8, 10 — variantes RQAP employeur ; Property 18)
# ---------------------------------------------------------------------------


@st.composite
def _st_contexte_rqap_employeur_cumul_au_plafond_ou_au_dela(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """Contexte RQAP dont `cumuls_debut.rqap_employeur` >= plafond annuel.

    Design (§Correctness Properties 5) — variante employeur du gabarit
    déjà utilisé par
    `_st_contexte_rqap_employe_cumul_au_plafond_ou_au_dela` (tâche 3.2) :
    part de `_st_contexte_calcul_rqap()` puis **remplace**
    `cumuls_debut.rqap_employeur` par `plafond + surplus`, `surplus`
    biaisé vers `Decimal("0.00")` pour couvrir à la fois le cas limite
    « cumul exactement au plafond » et le cas « cumul au-delà du
    plafond ». Le plafond employeur (`cotisation_max_employeur`) est
    lu depuis le `ParametresAnnee` réel 2026 tiré par
    `_st_contexte_calcul_rqap()` — jamais codé en dur (règle 05).
    `CumulsYTD`/`PayrollInput` étant `frozen=True`, le remplacement passe
    par `model_copy(update=...)`, sans mutation (règle 06).
    """
    payroll_input, gains, parametres_annee = draw(_st_contexte_calcul_rqap())
    plafond = parametres_annee.rqap.cotisation_max_employeur
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
        update={"rqap_employeur": plafond + surplus}
    )
    payroll_input_ajuste = payroll_input.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )
    return payroll_input_ajuste, gains, parametres_annee


@st.composite
def _st_contexte_rqap_employeur_sans_plafonnement(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """Contexte RQAP dont `cumuls_debut.rqap_employeur` est fixé à zéro.

    Isole la comparaison de Property 10 (formule indépendante sur le
    brut *vs* formule dérivée explicitement rejetée
    `arrondir(Decimal("1.4") × cotisation_employe)`) de tout effet du
    plafonnement en cours de saison. Avec `brut_total <=
    Decimal("5000.00")` (borne de `st_brut_total_avec_zero`, via
    `_st_contexte_calcul_rqap`) et `taux_employeur ==
    Decimal("0.00602")` (paramètres 2026 réels), le montant théorique de
    période employeur ne dépasse jamais `Decimal("30.10")` — largement
    sous le plafond annuel employeur (`Decimal("620.06")` en 2026) : le
    plafonnement ne peut donc jamais s'engager côté employeur dans ce
    contexte, quel que soit `cumuls_debut.rqap_employeur` d'origine, une
    fois celui-ci remplacé par zéro. Cela permet de comparer directement
    les valeurs *effectives* retournées (`[0]` du tuple) sans ambiguïté
    liée au plafonnement, conformément à la formulation du design
    (§Correctness Properties 10) : `calcul_rqap_employeur(pi, g, p)[0]`
    *vs* `arrondir(Decimal("1.4") × calcul_rqap_employe(pi, g, p)[0])`.
    `CumulsYTD`/`PayrollInput` étant `frozen=True`, le remplacement passe
    par `model_copy(update=...)`, sans mutation (règle 06).
    """
    payroll_input, gains, parametres_annee = draw(_st_contexte_calcul_rqap())
    cumuls_ajustes = payroll_input.cumuls_debut.model_copy(
        update={"rqap_employeur": Decimal("0.00")}
    )
    payroll_input_ajuste = payroll_input.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )
    return payroll_input_ajuste, gains, parametres_annee


def _payroll_input_deterministe_qc004() -> PayrollInput:
    """`PayrollInput` déterministe reproduisant le contexte du scénario
    QC004 (Property 18) : cumuls YTD nuls, année civile 2026.

    Test d'exemple, pas un test Hypothesis (design §Correctness
    Properties 18) : cette instance est fixe et anonymisée (règle 04 —
    identifiant fictif `EMP004`, aucune donnée nominative réelle),
    construite selon le même patron que
    `tests/payroll_engine/test_rrq.py::_payroll_input_deterministe_pour_exemple`.
    Aucun `float` (règle 01) : tous les montants et taux sont construits
    depuis des `Decimal`.
    """
    date_debut = date(2026, 6, 1)
    date_fin = date(2026, 6, 14)

    employee = Employee(
        id="EMP004",
        nom_affichage="Employe Test EMP004",
        date_naissance=date(1990, 3, 20),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Directrice",
        taux_horaire_base=Decimal("22.00"),
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
    cumuls_debut = CumulsYTD.zero(employe_id="EMP004", annee_civile=2026)
    return PayrollInput(
        employee=employee,
        pay_period=pay_period,
        heures_par_semaine=heures_par_semaine,
        taux_horaire_effectif=Decimal("22.00"),
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


def _construire_contexte_qc004() -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """`(PayrollInput, GainsDecomposes, ParametresAnnee)` du scénario QC004.

    `brut_total = Decimal("294.84")` (Requirement 5.8, Property 18),
    cumuls YTD nuls, paramètres 2026 Québec réels chargés via
    `load_parameters` (règle 05 — aucune valeur fiscale codée en dur).
    Réutilisé à la fois comme cas concret explicite de Property 10
    (`@example`) et comme fixture du test d'exemple dédié de
    Property 18.
    """
    payroll_input = _payroll_input_deterministe_qc004()
    gains = _construire_gains_decomposes(Decimal("294.84"))
    parametres_annee = load_parameters(2026, Juridiction.QUEBEC)
    return payroll_input, gains, parametres_annee


class TestIndependanceEtPlafonnementRqapEmployeur:
    """Property 4, 5, 8, 10 (variantes RQAP employeur) et Property 18
    (reproduction chiffrée de l'anomalie QC004).

    Design (§Correctness Properties 4, 5, 8, 10, 18 ; §Components §5).
    **Point de vigilance central de cette spec** : `calcul_rqap_employeur`
    calcule un montant théorique de période à partir de `gains.brut_total`
    (le salaire admissible brut), **jamais** à partir du montant
    `calcul_rqap_employe` déjà arrondi — contrairement à
    `calcul_ae_employeur` (tâche 4.3), qui se dérive à l'inverse du
    montant employé effectif. C'est cette indépendance de calcul qui
    résout l'anomalie QC004 : `Decimal("1.77")`
    (`294,84 × 0,602 % = 1,7749` → `1,77`) et non `Decimal("1.78")`
    (qui aurait résulté de la dérivation erronée `1,27 × 1,4 = 1,778` →
    `1,78`, méthode que cette spec rejette explicitement).
    """

    # Feature: cotisations-sociales-qc, Property 8: Formule proportionnelle sans exemption (RQAP employeur)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_8_formule_proportionnelle_sans_exemption_employeur(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant théorique de période de
        `calcul_rqap_employeur` (`trace.sous_totaux["cotisation_brute"]`)
        est égal à `arrondir(taux_employeur × brut_total)` — **aucune**
        exemption n'est soustraite du `Salaire_Admissible` avant
        application du taux.

        **Validates: Requirements 5.1**
        """
        payroll_input, gains, parametres_annee = contexte

        _, trace = calcul_rqap_employeur(payroll_input, gains, parametres_annee)

        montant_periode_attendu = (
            parametres_annee.rqap.taux_employeur * gains.brut_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert trace.sous_totaux["cotisation_brute"] == montant_periode_attendu

    # Feature: cotisations-sociales-qc, Property 4: Bornes générales (RQAP employeur)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_4_bornes_generales_employeur(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la cotisation RQAP employeur effective satisfait
        `Decimal("0.00") <= cotisation <= montant_periode` (montant
        théorique de période, `trace.sous_totaux["cotisation_brute"]`) et
        `Cumul_YTD_RQAP_Employeur + cotisation <=
        Plafond_Annuel_RQAP_Employeur`.

        **Validates: Requirements 5.3, 5.4, 5.7, 14.4**
        """
        payroll_input, gains, parametres_annee = contexte

        cotisation, trace = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )
        montant_periode = trace.sous_totaux["cotisation_brute"]
        cumul_ytd = payroll_input.cumuls_debut.rqap_employeur
        plafond_annuel = parametres_annee.rqap.cotisation_max_employeur

        assert Decimal("0.00") <= cotisation <= montant_periode
        assert cumul_ytd + cotisation <= plafond_annuel

    # Feature: cotisations-sociales-qc, Property 5: Plancher à zéro quand cumul >= plafond (RQAP employeur)
    @pytest.mark.property
    @given(contexte=_st_contexte_rqap_employeur_cumul_au_plafond_ou_au_dela())
    @settings_large_input
    def test_property_5_plancher_zero_quand_cumul_au_plafond_ou_au_dela_employeur(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput` dont `Cumul_YTD_RQAP_Employeur >=
        Plafond_Annuel_RQAP_Employeur`, `calcul_rqap_employeur` retourne
        `Decimal("0.00")` sans lever d'exception, quel que soit le
        `Salaire_Admissible` de la période.

        **Validates: Requirements 5.5**
        """
        payroll_input, gains, parametres_annee = contexte
        assert (
            payroll_input.cumuls_debut.rqap_employeur
            >= parametres_annee.rqap.cotisation_max_employeur
        )

        cotisation, _ = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )

        assert cotisation == Decimal("0.00")

    # Feature: cotisations-sociales-qc, Property 10: Indépendance de la cotisation RQAP employeur
    @pytest.mark.property
    @example(contexte=_construire_contexte_qc004())
    @given(contexte=_st_contexte_rqap_employeur_sans_plafonnement())
    @settings_large_input
    def test_property_10_independance_de_la_cotisation_rqap_employeur(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant théorique de période de
        `calcul_rqap_employeur` est calculé à partir de `brut_total` (le
        salaire admissible brut) et **non** à partir du montant
        `calcul_rqap_employe` déjà arrondi :
        `montant_periode_rqap_employeur ==
        arrondir(taux_employeur × brut_total)`, indépendamment de la
        valeur de `calcul_rqap_employe(pi, g, p)[0]`.

        Rejette explicitement la formule dérivée
        `arrondir(Decimal("1.4") × cotisation_employe)` : lorsque cette
        formule diverge de la formule indépendante (double arrondissement
        en cascade — voir l'anomalie QC004, forcée par `@example` avec
        `brut_total = Decimal("294.84")`), la valeur retournée par
        `calcul_rqap_employeur` suit la formule indépendante, jamais la
        formule dérivée. Le contexte
        `_st_contexte_rqap_employeur_sans_plafonnement()` garantit
        qu'aucun plafonnement ne peut brouiller cette comparaison directe
        sur les valeurs effectives retournées.

        **Validates: Requirements 5.1, 5.2**
        """
        payroll_input, gains, parametres_annee = contexte

        cotisation_employeur, trace_employeur = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )
        cotisation_employe, _ = calcul_rqap_employe(
            payroll_input, gains, parametres_annee
        )

        montant_periode_independant_attendu = (
            parametres_annee.rqap.taux_employeur * gains.brut_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert (
            trace_employeur.sous_totaux["cotisation_brute"]
            == montant_periode_independant_attendu
        )
        # Aucun plafonnement engagé dans ce contexte (voir docstring de
        # `_st_contexte_rqap_employeur_sans_plafonnement`) : la valeur
        # effective retournée est donc égale au montant théorique.
        assert cotisation_employeur == montant_periode_independant_attendu

        montant_periode_derive_rejete = (
            Decimal("1.4") * cotisation_employe
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if montant_periode_derive_rejete != montant_periode_independant_attendu:
            assert cotisation_employeur != montant_periode_derive_rejete

    # Feature: cotisations-sociales-qc, Property 18: Reproduction chiffrée de la résolution de l'anomalie QC004
    def test_property_18_reproduction_chiffree_de_lanomalie_qc004(self) -> None:
        """Test d'exemple (pas un test Hypothesis, design §Correctness
        Properties 18) — pour le scénario QC004 du Corpus_Golden
        (`brut_total = Decimal("294.84")`, cumuls YTD nuls, paramètres
        2026), `calcul_rqap_employeur` retourne exactement
        `Decimal("1.77")` — et non `Decimal("1.78")` — confirmant que le
        calcul indépendant sur le brut (`294,84 × 0,602 % = 1,7749` →
        `1,77`) prévaut sur la dérivation erronée à partir du montant
        employé déjà arrondi (`1,27 × 1,4 = 1,778` → `1,78`).

        **Validates: Requirements 5.8, 13.3**
        """
        payroll_input, gains, parametres_annee = _construire_contexte_qc004()

        cotisation_employeur, trace_employeur = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )

        assert cotisation_employeur == Decimal("1.77")
        assert cotisation_employeur != Decimal("1.78")
        assert trace_employeur.sous_totaux["cotisation_brute"] == Decimal("1.77")


# ---------------------------------------------------------------------------
# 3.4 — Trace RQAP employé et employeur (Property 13, 14, 15, 16)
# ---------------------------------------------------------------------------


class TestTraceRqap:
    """Property 13, 14, 15, 16 — conformité, contenu minimal, cohérence et
    auto-suffisance de la `CalculationTrace` RQAP (employé et employeur).

    Design (§Correctness Properties 13, 14, 15, 16 ; §Components §4, §5).
    Mêmes gabarits que `tests/payroll_engine/test_rrq.py::TestTraceRrq`
    (tâche 2.4), adaptés au contenu de trace RQAP : contrairement au RRQ,
    `parametres_utilises` porte le **taux effectivement appliqué**
    (`taux_employe` ou `taux_employeur`, sans exemption associée) et
    `sous_totaux` ne porte qu'une seule clé, `cotisation_brute` — aucune
    `assiette_cotisable` distincte du salaire admissible, puisque le RQAP
    ne soustrait aucune exemption (Property 8, tâche 3.2). Les quatre
    propriétés s'appliquent aux deux fonctions `calcul_rqap_employe` et
    `calcul_rqap_employeur` — seule Property 13 (via `section`) distingue
    explicitement les deux côtés. Les vérifications de contenu
    (Property 14) portent sur des **inclusions** (« contient au moins »)
    plutôt que sur une égalité stricte d'ensemble de clés, conformément à
    la formulation du design.
    """

    # Feature: cotisations-sociales-qc, Property 13: Conformité de trace.source, trace.annee, trace.juridiction et trace.section (RQAP)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_13_conformite_source_annee_juridiction_section(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces retournées par
        `calcul_rqap_employe` et `calcul_rqap_employeur` satisfont
        simultanément :

        - `trace.source` matche `^TP-1015\\.F \\d{4}, section 3\\.3` ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` ;
        - `trace.juridiction == Juridiction.QUEBEC` ;
        - `trace.section` est une chaîne non vide qui distingue
          explicitement le côté employé du côté employeur (la section
          employeur contient `"employeur"`, la section employé ne le
          contient pas).

        **Validates: Requirements 11.1, 11.2**
        """
        payroll_input, gains, parametres_annee = contexte
        pattern_source = re.compile(r"^TP-1015\.F \d{4}, section 3\.3")

        _montant_employe, trace_employe = calcul_rqap_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )

        for trace in (trace_employe, trace_employeur):
            assert pattern_source.match(trace.source) is not None
            assert trace.annee == payroll_input.pay_period.annee_fiscale
            assert trace.juridiction == Juridiction.QUEBEC
            assert trace.section != ""

        assert "employeur" in trace_employeur.section
        assert "employeur" not in trace_employe.section

    # Feature: cotisations-sociales-qc, Property 14: Contenu minimal exact de la trace par fonction (RQAP)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_14_contenu_minimal_de_la_trace(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de `calcul_rqap_employe` et
        `calcul_rqap_employeur` contiennent au moins :

        - dans `parametres_utilises` : le taux effectivement appliqué
          propre au côté concerné (`taux_employe` ou `taux_employeur`) ;
        - dans `entrees` : `salaire_periode` ;
        - dans `sous_totaux` : `cotisation_brute`.

        **Validates: Requirements 11.4**
        """
        payroll_input, gains, parametres_annee = contexte

        _montant_employe, trace_employe = calcul_rqap_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )

        assert "taux_employe" in trace_employe.parametres_utilises
        assert "taux_employeur" in trace_employeur.parametres_utilises

        for trace in (trace_employe, trace_employeur):
            assert "salaire_periode" in trace.entrees
            assert "cotisation_brute" in trace.sous_totaux

    # Feature: cotisations-sociales-qc, Property 15: Cohérence resultat/mode/précision (RQAP)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_15_coherence_resultat_mode_precision(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de `calcul_rqap_employe` et
        `calcul_rqap_employeur` satisfont
        `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`,
        `trace.precision_arrondissement == 2`, et `trace.resultat` est
        égal au montant retourné par la fonction (premier élément du
        tuple).

        **Validates: Requirements 10.4, 11.6**
        """
        payroll_input, gains, parametres_annee = contexte

        montant_employe, trace_employe = calcul_rqap_employe(
            payroll_input, gains, parametres_annee
        )
        montant_employeur, trace_employeur = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )

        for montant, trace in (
            (montant_employe, trace_employe),
            (montant_employeur, trace_employeur),
        ):
            assert trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
            assert trace.precision_arrondissement == 2
            assert trace.resultat == montant

    # Feature: cotisations-sociales-qc, Property 16: Auto-suffisance de la trace (RQAP)
    @pytest.mark.property
    @given(contexte=_st_contexte_calcul_rqap())
    @settings_large_input
    def test_property_16_auto_suffisance_de_la_trace(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, un tiers peut recalculer
        `trace.sous_totaux["cotisation_brute"]` (et donc `trace.resultat`
        avant plafonnement) à partir des seuls contenus de
        `trace.parametres_utilises` et `trace.entrees` — sans consulter
        `payroll_input` ni `parametres_annee` — via :

            trace.sous_totaux["cotisation_brute"] == arrondir(
                trace.parametres_utilises["taux_employe"]
                * trace.entrees["salaire_periode"]
            )

        (ou `taux_employeur` côté employeur). Contrairement au RRQ
        (Property 16, tâche 2.4), aucune exemption n'entre dans ce
        recalcul — le RQAP ne soustrait aucune exemption du salaire
        admissible (Property 8, tâche 3.2).

        **Validates: Requirements 11.8**
        """
        payroll_input, gains, parametres_annee = contexte

        _montant_employe, trace_employe = calcul_rqap_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_rqap_employeur(
            payroll_input, gains, parametres_annee
        )

        assert trace_employe.sous_totaux["cotisation_brute"] == (
            trace_employe.parametres_utilises["taux_employe"]
            * trace_employe.entrees["salaire_periode"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert trace_employeur.sous_totaux["cotisation_brute"] == (
            trace_employeur.parametres_utilises["taux_employeur"]
            * trace_employeur.entrees["salaire_periode"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# ---------------------------------------------------------------------------
# 3.5 — Propagation de MissingParameterError (Property 17)
# ---------------------------------------------------------------------------


class TestMissingParameterRqap:
    """Property 17 (variante RQAP) — propagation de `MissingParameterError`
    sans interception.

    Design (§Correctness Properties 17 ; §Error Handling « Matrice des
    exceptions »). Contrairement au RRQ (`TestMissingParameterRrq`,
    tâche 2.5), où `calcul_rrq_employeur` délègue strictement à
    `calcul_rrq_employe` (Property 9) — ce qui rend les quatre champs
    testables sur les deux fonctions indifféremment —, le RQAP employeur
    est un **calcul indépendant** (Property 10, tâche 3.3) :
    `calcul_rqap_employeur` ne lit jamais `rqap.taux_employe` ni
    `rqap.cotisation_max_employe`, et réciproquement
    `calcul_rqap_employe` ne lit jamais `rqap.taux_employeur` ni
    `rqap.cotisation_max_employeur` (design §Components §4, §5). Chaque
    champ marqué `"TO_FILL"` (via `st_parametres_annee_avec_to_fill`)
    n'est donc testé que sur la fonction qui le consomme réellement :

    - `rqap.taux_employe`, `rqap.cotisation_max_employe` ->
      `calcul_rqap_employe` uniquement ;
    - `rqap.taux_employeur`, `rqap.cotisation_max_employeur` ->
      `calcul_rqap_employeur` uniquement.
    """

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RQAP)
    @pytest.mark.property
    @given(
        contexte=_st_contexte_calcul_rqap(),
        parametres_annee=st_parametres_annee_avec_to_fill("rqap.taux_employe"),
    )
    @settings_large_input
    def test_property_17_to_fill_taux_employe(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `rqap.taux_employe` porte la sentinelle
        `"TO_FILL"`, `calcul_rqap_employe` lève `MissingParameterError`,
        non interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains, _parametres_non_utilises = contexte

        with pytest.raises(MissingParameterError):
            calcul_rqap_employe(payroll_input, gains, parametres_annee)

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RQAP)
    @pytest.mark.property
    @given(
        contexte=_st_contexte_calcul_rqap(),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "rqap.cotisation_max_employe"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_cotisation_max_employe(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `rqap.cotisation_max_employe` porte la
        sentinelle `"TO_FILL"`, `calcul_rqap_employe` lève
        `MissingParameterError`, non interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains, _parametres_non_utilises = contexte

        with pytest.raises(MissingParameterError):
            calcul_rqap_employe(payroll_input, gains, parametres_annee)

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RQAP)
    @pytest.mark.property
    @given(
        contexte=_st_contexte_calcul_rqap(),
        parametres_annee=st_parametres_annee_avec_to_fill("rqap.taux_employeur"),
    )
    @settings_large_input
    def test_property_17_to_fill_taux_employeur(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `rqap.taux_employeur` porte la sentinelle
        `"TO_FILL"`, `calcul_rqap_employeur` lève
        `MissingParameterError`, non interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains, _parametres_non_utilises = contexte

        with pytest.raises(MissingParameterError):
            calcul_rqap_employeur(payroll_input, gains, parametres_annee)

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RQAP)
    @pytest.mark.property
    @given(
        contexte=_st_contexte_calcul_rqap(),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "rqap.cotisation_max_employeur"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_cotisation_max_employeur(
        self,
        contexte: tuple[PayrollInput, GainsDecomposes, ParametresAnnee],
        parametres_annee: ParametresAnnee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `rqap.cotisation_max_employeur` porte la
        sentinelle `"TO_FILL"`, `calcul_rqap_employeur` lève
        `MissingParameterError`, non interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        payroll_input, gains, _parametres_non_utilises = contexte

        with pytest.raises(MissingParameterError):
            calcul_rqap_employeur(payroll_input, gains, parametres_annee)
