"""Property tests et tests d'exemple pour `calcul_ae_employe`/`calcul_ae_employeur`.

Spec de référence : ``cotisations-sociales-qc`` — tâche 4.1 (squelette).
Design de référence : ``design.md`` §Testing Strategy (« Stratégies
Hypothesis »), §Correctness Properties 1, 2, 3 et §Components §1, §6, §7.

Ce fichier est actuellement un **squelette** (tâche 4.1 uniquement) : il
porte les imports, la fixture de paramètres fusionnés Québec/Canada, la
configuration Hypothesis partagée et la classe transversale
``TestSignaturePureteRobustesse`` (Property 1, 2, 3, appliquées à
``calcul_ae_employe`` **et** ``calcul_ae_employeur``). Les classes
suivantes (formule proportionnelle et plafonnement, dérivation employeur,
trace, propagation de `MissingParameterError`) sont ajoutées par les
tâches 4.2 à 4.5.

Conformément à la règle 06 (TDD — tests avant code), ce squelette précède
l'implémentation de ``payroll_engine/assurance_emploi.py`` : le module
n'existe pas encore à ce stade. Contrairement à ``test_gains_bruts.py``
(qui importe son module cible localement à l'intérieur de chaque test
pour rester collectable même sans le module), les autres fichiers de
cette spec (``test_rrq.py``, ``test_rqap.py``) suivent le même patron —
ce fichier fait de même : ``payroll_engine.assurance_emploi`` est importé
**localement** à l'intérieur de chaque test qui en a besoin. Seuls ces
tests précis échouent avec ``ModuleNotFoundError`` (au moment de
l'exécution, pas de la collection) tant que le module n'existe pas.

Trois propriétés couvertes par ce fichier (design §Correctness
Properties), chacune appliquée aux deux fonctions AE :

1. Déterminisme (pureté) — Property 1.
2. Absence d'exception sur entrée valide — Property 2.
3. Forme ``Decimal`` du résultat et de la trace — Property 3.

**Limitation héritée du corpus golden** (Introduction des requirements,
design §Testing Strategy) : les six scénarios QC001–QC006 sont tous des
paies n° 1 de la saison (``cumul_ytd`` de départ nul pour les six
catégories de cotisation). Le corpus golden ne valide donc pas
directement le plafonnement en cours de saison (cumul non nul, proche ou
égal au plafond annuel) — ce comportement est couvert exclusivement par
les property tests de ce fichier, via ``st_cumuls_ytd_non_nuls()``.

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
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters
from tests.strategies import (  # noqa: F401
    st_brut_total_avec_zero,
    st_cumuls_ytd_non_nuls,
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_avec_to_fill,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Fixture module-scoped : paramètres 2026 fusionnés Québec + Canada
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parametres_2026_qc_ca() -> ParametresAnnee:
    """Charge une seule fois les paramètres 2026 fusionnés Québec + Canada.

    Cohérent avec ``_charger_parametres_annee_2026_qc_ca`` de
    ``tests/strategies.py`` (mémorisation ``lru_cache`` équivalente, ici
    au niveau de la fixture pytest plutôt que du module de stratégies) :
    la section ``assurance_emploi`` provient de
    ``parameters/2026/canada.json``, tandis que ``rrq``/``rqap`` restent
    ceux de ``parameters/2026/quebec.json``. Cette fixture matérialise
    une **vérification de non-régression** (à l'image de
    ``parametres_2026_qc`` dans ``test_gains_bruts.py``) : le
    multiplicateur employeur AE (design §Overview « Décisions
    structurantes retenues » point 5) doit rester ``1.4`` — si une future
    édition de ``canada.json`` modifiait accidentellement cette valeur,
    toute la suite de tests de ce fichier échouerait immédiatement ici.

    Portée ``module`` : les deux fichiers ne sont lus qu'une seule fois
    par ce fichier de test, quel que soit le nombre de tests (property ou
    exemple) qui consomment cette fixture.
    """
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    parametres = parametres_qc.model_copy(
        update={"assurance_emploi": parametres_ca.assurance_emploi}
    )

    # Non-régression — design §Overview, décision structurante 5.
    assert parametres.assurance_emploi.multiplicateur_employeur == Decimal("1.4")

    return parametres


# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée
# ---------------------------------------------------------------------------

# Design (§Testing Strategy « Configuration Hypothesis »* repris de
# ``gains-bruts-vacances-hs``) : pas de deadline (les modèles Pydantic
# peuvent dépasser 200 ms/exemple sous charge), et suppression du health
# check "too_slow" pour les propriétés à surface d'entrée large (composition
# de plusieurs sous-modèles via ``st_payroll_input()``). Le nombre
# d'exemples est piloté par le profil Hypothesis actif (voir
# ``tests/conftest.py`` : dev=15 par défaut, ci=100).
settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Helpers internes — construction d'un `GainsDecomposes` valide
# ---------------------------------------------------------------------------
#
# `calcul_ae_employe`/`calcul_ae_employeur` ne consomment que
# `gains.brut_total` (design §Components §6, §7 ; décision de périmètre
# « salaire admissible unique » de l'Introduction des requirements). Les
# autres composantes de `GainsDecomposes` ne sont pas lues par ces deux
# fonctions ; elles sont néanmoins requises par le contrat du modèle
# (règle 01 — `Decimal` partout, `GainsDecomposes` n'impose pas
# `salaire_regulier + heures_supp + vacances + feries == brut_total`,
# voir `models/payroll_result.py`). On loge donc tout le brut dans
# `salaire_regulier`, à l'image de `_make_gains` dans
# `tests/models/test_payroll_result.py`.


def _construire_gains(brut_total: Decimal) -> GainsDecomposes:
    """Construit un `GainsDecomposes` valide pour un `brut_total` donné.

    Seul `brut_total` varie dans les tests de ce fichier ; les autres
    composantes sont fixées à des valeurs neutres (`Decimal("0.00")`
    pour les montants, valeurs de contexte heures supplémentaires
    standard `1.5`/`40` — non consommées par les fonctions AE mais
    requises par le contrat du modèle).
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
def _st_gains_decomposes(
    draw: st.DrawFn, *, brut_total_strategy: st.SearchStrategy[Decimal]
) -> GainsDecomposes:
    """`GainsDecomposes` valide dont `brut_total` provient de `brut_total_strategy`."""
    brut_total = draw(brut_total_strategy)
    return _construire_gains(brut_total)


def _st_brut_total_eleve() -> st.SearchStrategy[Decimal]:
    """`Decimal` couvrant le cas « salaire admissible très élevé » (Property 2).

    Étend `st_brut_total_avec_zero()` (biaisée vers `Decimal("0.00")`,
    plage `[0.00, 5000.00]`) avec une branche `[5000.01, 50000.00]` pour
    exercer explicitement le cas extrême « salaire très élevé » requis
    par Property 2 (design §Correctness Properties 2). `50000.00`
    dépasse largement le maximum des gains admissibles RRQ 2026
    (`74 600 $` annuel, soit ~`2 869 $`/période aux deux semaines) sans
    avoir besoin de coder cette valeur en dur dans les tests (règle 05 —
    seule une borne de génération, pas un paramètre fiscal).
    """
    return st.one_of(
        st_brut_total_avec_zero(),
        st.decimals(
            min_value=Decimal("5000.01"),
            max_value=Decimal("50000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def _st_payroll_input_avec_cumuls_non_nuls(draw: st.DrawFn) -> PayrollInput:
    """`PayrollInput` valide dont `cumuls_debut` est réaffecté par
    `st_cumuls_ytd_non_nuls()` (au moins une catégorie de cotisation
    strictement positive, biaisée vers le plafond annuel exact).

    `st_cumuls_ytd_non_nuls()` génère un `CumulsYTD` avec son propre
    `employe_id`/`annee_civile` aléatoires — non appariés à un
    `PayrollInput` donné. Ce composite réaffecte ces deux champs
    d'identification pour satisfaire l'invariant de construction de
    `PayrollInput` (`cumuls_debut.employe_id == employee.id`,
    `cumuls_debut.annee_civile == pay_period.annee_fiscale` — voir
    `models/payroll_input.py`), sans toucher aux six catégories de
    cotisation (design §Testing Strategy, Property 2/4/5).
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


def _verifier_forme_decimal(montant: Decimal, trace: CalculationTrace) -> None:
    """Vérifie Property 3 sur un couple `(montant, trace)` retourné.

    - `montant` et `trace.resultat` sont des `Decimal` finis, arrondis à
      deux décimales `ROUND_HALF_UP` ;
    - chaque valeur de `trace.parametres_utilises`, `trace.entrees`,
      `trace.sous_totaux` est un `Decimal` fini (règle 01 — aucun
      `float`, `v.is_finite()`).
    """
    precision = Decimal("0.01")

    assert isinstance(montant, Decimal)
    assert montant.is_finite()
    assert montant == montant.quantize(precision, rounding=ROUND_HALF_UP)

    assert isinstance(trace.resultat, Decimal)
    assert trace.resultat.is_finite()
    assert trace.resultat == trace.resultat.quantize(precision, rounding=ROUND_HALF_UP)

    for dictionnaire in (
        trace.parametres_utilises,
        trace.entrees,
        trace.sous_totaux,
    ):
        for valeur in dictionnaire.values():
            assert isinstance(valeur, Decimal)
            assert valeur.is_finite()


# ---------------------------------------------------------------------------
# 4.1 — Signature, pureté et robustesse (Property 1, 2, 3)
# ---------------------------------------------------------------------------


class TestSignaturePureteRobustesse:
    """Property 1, 2, 3 — signature, pureté et robustesse de
    `calcul_ae_employe` et `calcul_ae_employeur`.

    Design (§Correctness Properties 1, 2, 3 ; §Components §1 « Signature
    exacte », §6, §7). Trois propriétés Hypothesis, chacune dupliquée
    pour les deux fonctions AE, plus un test d'exemple vérifiant
    l'absence d'effet de bord à l'import (Req 1.10).
    """

    # -- Property 1 : Déterminisme -----------------------------------

    # Feature: cotisations-sociales-qc, Property 1: Déterminisme (calcul_ae_employe)
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        gains=_st_gains_decomposes(brut_total_strategy=st_brut_total_avec_zero()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_1_calcul_ae_employe_deux_appels_identiques(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, `calcul_ae_employe(pi, g, p) == calcul_ae_employe(pi, g, p)` :
        deux appels avec les mêmes arguments produisent deux tuples égaux au
        sens `==` sur les deux composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.4**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        resultat_1 = calcul_ae_employe(payroll_input, gains, parametres_annee)
        resultat_2 = calcul_ae_employe(payroll_input, gains, parametres_annee)

        assert resultat_1 == resultat_2
        assert resultat_1[0] == resultat_2[0]
        assert resultat_1[1] == resultat_2[1]

    # Feature: cotisations-sociales-qc, Property 1: Déterminisme (calcul_ae_employeur)
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        gains=_st_gains_decomposes(brut_total_strategy=st_brut_total_avec_zero()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_1_calcul_ae_employeur_deux_appels_identiques(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, `calcul_ae_employeur(pi, g, p) == calcul_ae_employeur(pi, g, p)` :
        deux appels avec les mêmes arguments produisent deux tuples égaux au
        sens `==` sur les deux composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.4**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employeur

        resultat_1 = calcul_ae_employeur(payroll_input, gains, parametres_annee)
        resultat_2 = calcul_ae_employeur(payroll_input, gains, parametres_annee)

        assert resultat_1 == resultat_2
        assert resultat_1[0] == resultat_2[0]
        assert resultat_1[1] == resultat_2[1]

    # -- Property 2 : Absence d'exception sur entrée valide ----------

    # Feature: cotisations-sociales-qc, Property 2: Absence d'exception sur entrée valide (calcul_ae_employe)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_2_calcul_ae_employe_aucune_exception_sur_entree_valide(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides (paramètres 2026 entièrement renseignés), `calcul_ae_employe`
        retourne un tuple sans lever aucune exception — y compris pour les cas
        extrêmes générés (salaire admissible nul, cumul YTD nul ou proche du
        plafond via `st_cumuls_ytd_non_nuls`, salaire très élevé via
        `_st_brut_total_eleve`).

        **Validates: Requirements 1.9, 14.1**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        resultat = calcul_ae_employe(payroll_input, gains, parametres_annee)

        assert resultat is not None

    # Feature: cotisations-sociales-qc, Property 2: Absence d'exception sur entrée valide (calcul_ae_employeur)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_2_calcul_ae_employeur_aucune_exception_sur_entree_valide(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides (paramètres 2026 entièrement renseignés), `calcul_ae_employeur`
        retourne un tuple sans lever aucune exception — y compris pour les cas
        extrêmes générés (salaire admissible nul, cumul YTD nul ou proche du
        plafond via `st_cumuls_ytd_non_nuls`, salaire très élevé via
        `_st_brut_total_eleve`).

        **Validates: Requirements 1.9, 14.1**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employeur

        resultat = calcul_ae_employeur(payroll_input, gains, parametres_annee)

        assert resultat is not None

    # -- Property 3 : Forme `Decimal` du résultat et de la trace -----

    # Feature: cotisations-sociales-qc, Property 3: Forme Decimal du résultat et de la trace (calcul_ae_employe)
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        gains=_st_gains_decomposes(brut_total_strategy=st_brut_total_avec_zero()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_3_calcul_ae_employe_forme_decimal_du_resultat_et_de_la_trace(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant retourné par `calcul_ae_employe` et chaque valeur
        contenue dans `trace.parametres_utilises`/`entrees`/`sous_totaux`/
        `resultat` sont des `Decimal` finis, arrondis à deux décimales
        `ROUND_HALF_UP` pour le montant et `trace.resultat`.

        **Validates: Requirements 6.5, 7.4**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        montant, trace = calcul_ae_employe(payroll_input, gains, parametres_annee)

        _verifier_forme_decimal(montant, trace)

    # Feature: cotisations-sociales-qc, Property 3: Forme Decimal du résultat et de la trace (calcul_ae_employeur)
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        gains=_st_gains_decomposes(brut_total_strategy=st_brut_total_avec_zero()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_3_calcul_ae_employeur_forme_decimal_du_resultat_et_de_la_trace(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant retourné par `calcul_ae_employeur` et chaque valeur
        contenue dans `trace.parametres_utilises`/`entrees`/`sous_totaux`/
        `resultat` sont des `Decimal` finis, arrondis à deux décimales
        `ROUND_HALF_UP` pour le montant et `trace.resultat`.

        **Validates: Requirements 6.5, 7.4**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employeur

        montant, trace = calcul_ae_employeur(payroll_input, gains, parametres_annee)

        _verifier_forme_decimal(montant, trace)

    # -- Test d'exemple : import sans effet de bord -------------------

    def test_import_calcul_ae_employe_et_employeur_sans_effet_de_bord(
        self, capsys
    ) -> None:
        """Test d'exemple — `from payroll_engine.assurance_emploi import
        calcul_ae_employe, calcul_ae_employeur` ne produit **aucun effet de
        bord** (Req 1.10) : pas d'ouverture de fichier, pas d'appel réseau,
        pas d'écriture sur `stdout` / `stderr`.

        Design (§Architecture « Contrainte de pureté »). Le module est
        retiré de `sys.modules` avant l'import (s'il y était déjà) afin de
        forcer une exécution fraîche du corps du module — c'est justement à
        ce moment que d'éventuels effets de bord au niveau module
        (ouverture de fichier, `print`, connexion réseau) se
        manifesteraient.
        """
        import importlib

        nom_module = "payroll_engine.assurance_emploi"
        sys.modules.pop(nom_module, None)

        module = importlib.import_module(nom_module)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert nom_module in sys.modules
        assert hasattr(module, "calcul_ae_employe")
        assert hasattr(module, "calcul_ae_employeur")


# ---------------------------------------------------------------------------
# 4.2 — Formule proportionnelle et plafonnement AE employé
# (Property 4, 5, 6, 8 — variantes AE employé)
# ---------------------------------------------------------------------------


@st.composite
def _st_contexte_cumul_ae_employe_au_plafond(
    draw: st.DrawFn,
) -> tuple[PayrollInput, ParametresAnnee]:
    """`(PayrollInput, ParametresAnnee)` où `cumuls_debut.ae_employe` est
    supérieur ou égal au plafond annuel AE employé.

    Design (§Correctness Properties 5 : « Plancher à zéro lorsque le
    cumul atteint ou dépasse le plafond »). `parametres_annee` est tiré
    de `st_parametres_annee_2026_qc_ca()` (instance réelle 2026, unique
    valeur possible via `st.just`) pour connaître le plafond
    (`assurance_emploi.cotisation_max_employe`) sans jamais le coder en
    dur (règle 05). Le tirage biaise explicitement vers le plafond
    *exact* (`st.just(plafond)`) tout en couvrant aussi le cas
    « strictement au-delà » (`]plafond, plafond + 1000.00]`), les deux
    cas devant produire une cotisation nulle d'après Property 5. Seule
    la catégorie `ae_employe` de `cumuls_debut` est réaffectée — les
    cinq autres catégories restent celles générées par défaut par
    `st_payroll_input()` (neutres), afin de ne tester que le
    plafonnement AE employé isolément.
    """
    parametres_annee = draw(st_parametres_annee_2026_qc_ca())
    plafond = parametres_annee.assurance_emploi.cotisation_max_employe

    payroll_input_base = draw(st_payroll_input())
    cumul_ae_employe = draw(
        st.one_of(
            st.just(plafond),
            st.decimals(
                min_value=plafond,
                max_value=plafond + Decimal("1000.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    cumuls_ajustes = payroll_input_base.cumuls_debut.model_copy(
        update={"ae_employe": cumul_ae_employe}
    )
    payroll_input = payroll_input_base.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )

    return payroll_input, parametres_annee


class TestFormuleEtPlafonnementAeEmploye:
    """Property 4, 5, 6, 8 (variantes AE employé) — formule proportionnelle
    sans exemption et plafonnement de `calcul_ae_employe`.

    Design (§Correctness Properties 4, 5, 6, 8 ; §Components §6). La
    trace de `calcul_ae_employe` expose dans `sous_totaux["cotisation_brute"]`
    le montant théorique de période *avant* plafonnement (voir §Components
    §6, table de trace) — c'est cette valeur qui permet de vérifier
    Property 8 et la borne supérieure de Property 4 indépendamment du
    fait que le montant retourné (`cotisation_effective`) puisse avoir
    été plafonné par le cumul YTD.
    """

    # -- Property 8 : Formule proportionnelle sans exemption ---------

    # Feature: cotisations-sociales-qc, Property 8: Formule proportionnelle sans exemption (AE employé)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_8_montant_periode_egal_taux_fois_brut_total(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant théorique de période de `calcul_ae_employe`
        (`trace.sous_totaux["cotisation_brute"]`) est égal à
        `arrondir(taux_employe_quebec × brut_total)` — aucune exemption
        n'est soustraite du `Salaire_Admissible` avant application du
        taux, contrairement au RRQ.

        **Validates: Requirements 6.1**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        _, trace = calcul_ae_employe(payroll_input, gains, parametres_annee)

        taux_employe_quebec = parametres_annee.assurance_emploi.taux_employe_quebec
        montant_periode_attendu = (taux_employe_quebec * gains.brut_total).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        assert trace.sous_totaux["cotisation_brute"] == montant_periode_attendu

    # -- Property 4 : Bornes générales --------------------------------

    # Feature: cotisations-sociales-qc, Property 4: Bornes générales (AE employé)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_4_bornes_generales_de_la_cotisation_ae_employe(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la cotisation AE employé effective retournée satisfait
        `Decimal("0.00") <= cotisation <= montant_periode` (le montant
        théorique de période, lu dans `trace.sous_totaux["cotisation_brute"]`)
        et `cumul_ytd_ae_employe + cotisation <= plafond_annuel_ae_employe`.

        **Validates: Requirements 6.2, 6.3, 6.6, 14.4**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        montant, trace = calcul_ae_employe(payroll_input, gains, parametres_annee)

        montant_periode = trace.sous_totaux["cotisation_brute"]
        plafond_annuel = parametres_annee.assurance_emploi.cotisation_max_employe
        cumul_ytd = payroll_input.cumuls_debut.ae_employe

        assert Decimal("0.00") <= montant <= montant_periode
        assert cumul_ytd + montant <= plafond_annuel

    # -- Property 5 : Plancher à zéro quand cumul >= plafond ----------

    # Feature: cotisations-sociales-qc, Property 5: Plancher à zéro quand cumul >= plafond (AE employé)
    @pytest.mark.property
    @given(
        contexte=_st_contexte_cumul_ae_employe_au_plafond(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
    )
    @settings_large_input
    def test_property_5_plancher_a_zero_quand_cumul_atteint_ou_depasse_le_plafond(
        self,
        contexte,
        gains,
    ) -> None:
        """*Pour tout* `PayrollInput` dont `cumuls_debut.ae_employe >=
        plafond_annuel_ae_employe`, `GainsDecomposes` et `ParametresAnnee`
        valides, `calcul_ae_employe` retourne `Decimal("0.00")` sans lever
        d'exception, quel que soit le `Salaire_Admissible` de la période
        (y compris un salaire admissible très élevé, via
        `_st_brut_total_eleve`).

        **Validates: Requirements 6.4**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        payroll_input, parametres_annee = contexte

        montant, _ = calcul_ae_employe(payroll_input, gains, parametres_annee)

        assert montant == Decimal("0.00")

    # -- Property 6 : Zéro sur salaire admissible nul ------------------

    # Feature: cotisations-sociales-qc, Property 6: Zéro sur salaire nul (AE employé)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=st.just(Decimal("0.00"))),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_6_zero_sur_salaire_admissible_nul(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` (y compris cumul YTD non nul ou
        proche du plafond) et `ParametresAnnee` valides, si
        `gains.brut_total == Decimal("0.00")`, alors `calcul_ae_employe`
        retourne `Decimal("0.00")` sans lever d'exception.

        **Validates: Requirements 14.1**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employe

        montant, _ = calcul_ae_employe(payroll_input, gains, parametres_annee)

        assert montant == Decimal("0.00")


# ---------------------------------------------------------------------------
# 4.3 — Dérivation et plafonnement AE employeur
# (Property 11, Property 4 variante employeur)
# ---------------------------------------------------------------------------


@st.composite
def _st_contexte_ae_employeur_independance(
    draw: st.DrawFn,
) -> tuple[PayrollInput, PayrollInput, GainsDecomposes, ParametresAnnee]:
    """Deux `PayrollInput` identiques sauf `cumuls_debut.ae_employe`.

    Design (§Correctness Properties 11) : « le montant théorique de
    période de `calcul_ae_employeur` est égal à
    `arrondir(multiplicateur_employeur × cotisation_ae_employe_effective)`
    [...] **jamais** `arrondir(taux_employe_quebec × multiplicateur_employeur
    × brut_total)` ». Contrairement à `_st_contexte_rqap_employeur_independance`
    de ``test_rqap.py`` (qui exploite l'indépendance vis-à-vis du cumul
    employé pour *rejeter* toute dérivation), cette stratégie exploite la
    même variation de `cumuls_debut.ae_employe` pour l'usage **inverse** :
    l'AE employeur DOIT suivre `cotisation_ae_employe_effective` (post-
    plafonnement) lorsque celle-ci varie entre les deux contextes — c'est
    la formule sur le brut qui serait rejetée si elle restait constante
    alors que la cotisation employé effective change.

    Le tirage de la seconde valeur de `ae_employe` est biaisé vers
    `Decimal("0.00")` et vers le plafond employé exact
    (`st.one_of` incluant `st.just(plafond_employe)`) afin de maximiser
    les cas où `calcul_ae_employe` produit deux cotisations effectives
    *différentes* entre les deux contextes (l'une non plafonnée, l'autre
    plafonnée à zéro) — c'est précisément dans ce cas que la formule
    rejetée (calcul indépendant sur le brut, insensible au cumul employé)
    diverge de la formule correcte (dérivation depuis le montant employé
    effectif), rendant le test capable de détecter une régression vers le
    calcul indépendant. `CumulsYTD`/`PayrollInput` étant `frozen=True`,
    la construction du second contexte passe par `model_copy(update=...)`,
    sans mutation (règle 06).
    """
    payroll_input_a = draw(_st_payroll_input_avec_cumuls_non_nuls())
    gains = draw(_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()))
    parametres_annee = draw(st_parametres_annee_2026_qc_ca())

    plafond_employe = parametres_annee.assurance_emploi.cotisation_max_employe
    cumul_employe_b = draw(
        st.one_of(
            st.just(Decimal("0.00")),
            st.just(plafond_employe),
            st.decimals(
                min_value=Decimal("0.00"),
                max_value=plafond_employe,
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    cumuls_b = payroll_input_a.cumuls_debut.model_copy(
        update={"ae_employe": cumul_employe_b}
    )
    payroll_input_b = payroll_input_a.model_copy(update={"cumuls_debut": cumuls_b})

    return payroll_input_a, payroll_input_b, gains, parametres_annee


@st.composite
def _st_contexte_cumul_ae_employeur_au_plafond(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes, ParametresAnnee]:
    """`(PayrollInput, GainsDecomposes, ParametresAnnee)` où
    `cumuls_debut.ae_employeur` est supérieur ou égal au plafond annuel
    AE employeur.

    Design (§Correctness Properties 4, variante AE employeur — défense
    en profondeur, Requirement 7 AC3). Même gabarit que
    `_st_contexte_cumul_ae_employe_au_plafond` (tâche 4.2), appliqué à la
    catégorie `ae_employeur` et au plafond `cotisation_max_employeur` —
    distinct du plafond employé (Requirement 7). `parametres_annee` est
    tiré de `st_parametres_annee_2026_qc_ca()` (instance réelle 2026)
    pour connaître le plafond sans jamais le coder en dur (règle 05).
    """
    parametres_annee = draw(st_parametres_annee_2026_qc_ca())
    plafond = parametres_annee.assurance_emploi.cotisation_max_employeur

    payroll_input_base = draw(st_payroll_input())
    cumul_ae_employeur = draw(
        st.one_of(
            st.just(plafond),
            st.decimals(
                min_value=plafond,
                max_value=plafond + Decimal("1000.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    cumuls_ajustes = payroll_input_base.cumuls_debut.model_copy(
        update={"ae_employeur": cumul_ae_employeur}
    )
    payroll_input = payroll_input_base.model_copy(
        update={"cumuls_debut": cumuls_ajustes}
    )

    return payroll_input, parametres_annee


def _payroll_input_deterministe_pour_exemple_ae(
    *, cumul_ae_employe: Decimal, cumul_ae_employeur: Decimal
) -> PayrollInput:
    """`PayrollInput` valide et déterministe (test d'exemple, Property 11).

    Instance fixe, déterministe et anonymisée (règle 04), à l'image de
    `_payroll_input_deterministe_pour_exemple` de
    ``tests/payroll_engine/test_rrq.py``. Aucun `float` (règle 01) :
    tous les montants et taux sont construits depuis des `Decimal`. Les
    deux cumuls AE (employé et employeur) sont paramétrables afin de
    construire le scénario de plafonnement employé du test d'exemple de
    cette tâche.
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
    cumuls_debut = CumulsYTD.zero(employe_id="EMP001", annee_civile=2026).model_copy(
        update={
            "ae_employe": cumul_ae_employe,
            "ae_employeur": cumul_ae_employeur,
        }
    )
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


class TestDerivationEtPlafonnementAeEmployeur:
    """Property 11, Property 4 (variante AE employeur) — dérivation depuis
    la cotisation AE employé plafonnée et bornes de la cotisation AE
    employeur.

    Design (§Correctness Properties 4, 11 ; §Components §7). Le point de
    vigilance central de cette classe (design §Components §7, décision
    structurante 5) est l'**inverse** de celui de
    `TestIndependanceEtPlafonnementRqapEmployeur` (``test_rqap.py``,
    tâche 3.3) : `calcul_ae_employeur` DOIT se dériver du montant AE
    employé **effectif** (post-plafonnement), et non d'un calcul
    indépendant sur `gains.brut_total` — c'est l'inverse exact de la
    décision retenue pour le RQAP employeur.
    """

    # -- Property 11 : Dérivation depuis la cotisation AE employé plafonnée --

    # Feature: cotisations-sociales-qc, Property 11: Dérivation de la cotisation AE employeur depuis la cotisation AE employé plafonnée
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_11_montant_periode_derive_de_la_cotisation_employe_effective(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, le montant théorique de période de `calcul_ae_employeur`
        est égal à `arrondir(multiplicateur_employeur ×
        cotisation_ae_employe_effective)`, où `cotisation_ae_employe_effective`
        est exactement `calcul_ae_employe(pi, g, p)[0]` (c'est-à-dire
        **après** plafonnement employé) — et non
        `arrondir(taux_employe_quebec × multiplicateur_employeur ×
        brut_total)` (calcul indépendant sur le brut, explicitement
        rejeté).

        **Validates: Requirements 7.1, 7.2**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        cotisation_ae_employe_effective, _ = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        _, trace_employeur = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        multiplicateur = parametres_annee.assurance_emploi.multiplicateur_employeur
        montant_periode_attendu_derive = (
            multiplicateur * cotisation_ae_employe_effective
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        montant_periode_calcul_independant_rejete = (
            parametres_annee.assurance_emploi.taux_employe_quebec
            * multiplicateur
            * gains.brut_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        montant_periode_observe = (
            multiplicateur * trace_employeur.entrees["ae_employe"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert trace_employeur.entrees["ae_employe"] == cotisation_ae_employe_effective
        assert montant_periode_observe == montant_periode_attendu_derive

        # Rejet explicite de la formule indépendante sur le brut : dès
        # que la cotisation employé effective a été plafonnée (diffère
        # de `taux_employe_quebec * brut_total`), les deux formules
        # divergent — la formule correcte utilise la valeur effective.
        if (
            montant_periode_attendu_derive
            != montant_periode_calcul_independant_rejete
        ):
            assert (
                montant_periode_observe != montant_periode_calcul_independant_rejete
            )

    # Feature: cotisations-sociales-qc, Property 11: Dérivation de la cotisation AE employeur (sensibilité au plafonnement employé)
    @pytest.mark.property
    @given(contexte=_st_contexte_ae_employeur_independance())
    @settings_large_input
    def test_property_11_montant_periode_employeur_suit_le_plafonnement_employe(
        self,
        contexte: tuple[PayrollInput, PayrollInput, GainsDecomposes, ParametresAnnee],
    ) -> None:
        """*Pour tout* couple de `PayrollInput` identiques sauf
        `cumuls_debut.ae_employe`, si `calcul_ae_employe` retourne deux
        cotisations effectives *différentes* entre les deux contextes
        (l'une plafonnée, l'autre non), alors `calcul_ae_employeur`
        retourne également deux montants théoriques de période
        *différents* — preuve que l'employeur se dérive bien du montant
        employé post-plafonnement et non d'un calcul indépendant sur
        `gains.brut_total` (qui, lui, resterait strictement identique
        entre les deux contextes puisque `gains` et `brut_total` ne
        changent pas).

        **Validates: Requirements 7.1, 7.2**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        payroll_input_a, payroll_input_b, gains, parametres_annee = contexte

        cotisation_employe_a, _ = calcul_ae_employe(
            payroll_input_a, gains, parametres_annee
        )
        cotisation_employe_b, _ = calcul_ae_employe(
            payroll_input_b, gains, parametres_annee
        )

        _, trace_employeur_a = calcul_ae_employeur(
            payroll_input_a, gains, parametres_annee
        )
        _, trace_employeur_b = calcul_ae_employeur(
            payroll_input_b, gains, parametres_annee
        )

        multiplicateur = parametres_annee.assurance_emploi.multiplicateur_employeur
        montant_periode_a = (multiplicateur * cotisation_employe_a).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        montant_periode_b = (multiplicateur * cotisation_employe_b).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        montant_periode_observe_a = (
            multiplicateur * trace_employeur_a.entrees["ae_employe"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        montant_periode_observe_b = (
            multiplicateur * trace_employeur_b.entrees["ae_employe"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert montant_periode_observe_a == montant_periode_a
        assert montant_periode_observe_b == montant_periode_b

        # Si le plafonnement employé a effectivement produit deux
        # cotisations différentes, l'employeur DOIT suivre — rejet de la
        # formule indépendante sur le brut qui, elle, resterait constante.
        if cotisation_employe_a != cotisation_employe_b:
            assert montant_periode_observe_a != montant_periode_observe_b

    # -- Property 4 (variante AE employeur) : Bornes -------------------

    # Feature: cotisations-sociales-qc, Property 4: Bornes générales (AE employeur, défense en profondeur)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_4_bornes_generales_de_la_cotisation_ae_employeur(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la cotisation AE employeur effective satisfait
        `cumul_ytd_ae_employeur + cotisation <=
        plafond_annuel_ae_employeur` (défense en profondeur, Requirement
        7 AC3), ainsi que `Decimal("0.00") <= cotisation <=
        montant_periode` (montant théorique de période, dérivé de la
        cotisation employé effective).

        **Validates: Requirements 7.3, 7.5**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        cotisation_ae_employe_effective, _ = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        montant, trace = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        multiplicateur = parametres_annee.assurance_emploi.multiplicateur_employeur
        montant_periode = (
            multiplicateur * cotisation_ae_employe_effective
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        cumul_ytd = payroll_input.cumuls_debut.ae_employeur
        plafond_annuel = parametres_annee.assurance_emploi.cotisation_max_employeur

        assert Decimal("0.00") <= montant <= montant_periode
        assert cumul_ytd + montant <= plafond_annuel

    # Feature: cotisations-sociales-qc, Property 4: Plancher à zéro quand cumul employeur >= plafond (AE employeur, défense en profondeur)
    @pytest.mark.property
    @given(
        contexte=_st_contexte_cumul_ae_employeur_au_plafond(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
    )
    @settings_large_input
    def test_property_4_plancher_zero_quand_cumul_employeur_au_plafond_ou_au_dela(
        self,
        contexte,
        gains,
    ) -> None:
        """*Pour tout* `PayrollInput` dont `cumuls_debut.ae_employeur >=
        plafond_annuel_ae_employeur`, `calcul_ae_employeur` retourne
        `Decimal("0.00")` sans lever d'exception, quel que soit le
        `Salaire_Admissible` de la période — défense en profondeur du
        plafonnement employeur (Requirement 7 AC3), indépendamment du
        fait que la cotisation AE employé (Requirement 6) reste, elle,
        potentiellement non nulle.

        **Validates: Requirements 7.3, 7.5**
        """
        from payroll_engine.assurance_emploi import calcul_ae_employeur

        payroll_input, parametres_annee = contexte
        assert (
            payroll_input.cumuls_debut.ae_employeur
            >= parametres_annee.assurance_emploi.cotisation_max_employeur
        )

        montant, _ = calcul_ae_employeur(payroll_input, gains, parametres_annee)

        assert montant == Decimal("0.00")

    # -- Test d'exemple : dérivation post-plafonnement employé ----------

    def test_exemple_employeur_derive_du_montant_employe_post_plafonnement(
        self,
    ) -> None:
        """Test d'exemple — cas où `cotisation_ae_employe_effective` est
        déjà plafonnée (cumul employé à une marge résiduelle de 1,00 $ du
        plafond annuel) : vérifie que l'employeur se dérive bien du
        montant *post-plafonnement* (`Decimal("1.00")` × multiplicateur),
        et non d'un calcul indépendant sur le brut (qui produirait un
        montant théorique bien plus élevé, sans lien avec le
        plafonnement employé).

        Design (§Components §7, point de vigilance central). Le
        `brut_total` choisi (`Decimal("1000.00")`) garantit que le
        montant théorique employé non plafonné
        (`taux_employe_quebec × brut_total`) dépasse largement la marge
        disponible résiduelle de `Decimal("1.00")`, forçant le
        plafonnement employé à s'appliquer : `cotisation_ae_employe_effective
        == Decimal("1.00")`, strictement inférieure à
        `taux_employe_quebec × brut_total`. Aucun `float` (règle 01).

        **Validates: Requirements 7.1, 7.2**
        """
        parametres_annee = load_parameters(2026, Juridiction.CANADA)
        taux_employe_quebec = parametres_annee.assurance_emploi.taux_employe_quebec
        multiplicateur = parametres_annee.assurance_emploi.multiplicateur_employeur
        plafond_employe = parametres_annee.assurance_emploi.cotisation_max_employe

        marge_residuelle = Decimal("1.00")
        cumul_ae_employe = plafond_employe - marge_residuelle
        brut_total = Decimal("1000.00")

        # Confirme que le brut choisi produirait, sans plafonnement, un
        # montant théorique strictement supérieur à la marge résiduelle
        # — condition nécessaire pour que le plafonnement employé
        # s'applique effectivement dans ce scénario.
        montant_periode_employe_sans_plafond = (
            taux_employe_quebec * brut_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert montant_periode_employe_sans_plafond > marge_residuelle

        payroll_input = _payroll_input_deterministe_pour_exemple_ae(
            cumul_ae_employe=cumul_ae_employe,
            cumul_ae_employeur=Decimal("0.00"),
        )
        gains = _construire_gains(brut_total)

        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        cotisation_ae_employe_effective, _ = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        assert cotisation_ae_employe_effective == marge_residuelle
        assert cotisation_ae_employe_effective < montant_periode_employe_sans_plafond

        montant_employeur, trace_employeur = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        montant_employeur_attendu_derive = (
            multiplicateur * cotisation_ae_employe_effective
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Formule rejetée : calcul indépendant sur le brut, insensible
        # au plafonnement employé.
        montant_employeur_calcul_independant_rejete = (
            taux_employe_quebec * multiplicateur * brut_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert montant_employeur == montant_employeur_attendu_derive
        assert trace_employeur.entrees["ae_employe"] == cotisation_ae_employe_effective
        assert montant_employeur != montant_employeur_calcul_independant_rejete


# ---------------------------------------------------------------------------
# 4.4 — Trace AE employé et employeur (Property 13, 14, 15, 16)
# ---------------------------------------------------------------------------


class TestTraceAe:
    """Property 13, 14, 15, 16 — conformité, contenu minimal, cohérence et
    auto-suffisance de la `CalculationTrace` AE (employé et employeur).

    Design (§Correctness Properties 13, 14, 15, 16 ; §Components §6, §7).
    Les quatre propriétés s'appliquent aux deux fonctions
    `calcul_ae_employe` et `calcul_ae_employeur` — seule Property 13 (via
    `section`) distingue explicitement les deux côtés. Contrairement à
    RRQ (§Components §2, §3) et à RQAP (§Components §4, §5), la
    juridiction de la trace AE est `Juridiction.CANADA` (source T4127,
    et non TP-1015.F) et `sous_totaux["cotisation_employeur"]` porte le
    produit `multiplicateur_employeur × ae_employe` **avant**
    arrondissement final (design §Components §7 : reproduction fidèle de
    la fixture `"27.594"` avant `resultat="27.59"`) — c'est le point de
    vigilance central de Property 16 (variante AE employeur) : l'égalité
    d'auto-suffisance ne doit **pas** ré-arrondir cette valeur
    intermédiaire.
    """

    # Feature: cotisations-sociales-qc, Property 13: Conformité de trace.source, trace.annee, trace.juridiction et trace.section (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_13_conformite_source_annee_juridiction_section(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces retournées par
        `calcul_ae_employe` et `calcul_ae_employeur` satisfont
        simultanément :

        - `trace.source` matche `^T4127 \\d{4}, section 4` ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` ;
        - `trace.juridiction == Juridiction.CANADA` ;
        - `trace.section` est une chaîne non vide qui distingue
          explicitement le côté employé du côté employeur (la section
          employeur contient `"employeur"`, la section employé ne le
          contient pas).

        **Validates: Requirements 11.1, 11.2**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        pattern_source = re.compile(r"^T4127 \d{4}, section 4")

        _montant_employe, trace_employe = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        for trace in (trace_employe, trace_employeur):
            assert pattern_source.match(trace.source) is not None
            assert trace.annee == payroll_input.pay_period.annee_fiscale
            assert trace.juridiction == Juridiction.CANADA
            assert trace.section != ""

        assert "employeur" in trace_employeur.section
        assert "employeur" not in trace_employe.section

    # Feature: cotisations-sociales-qc, Property 14: Contenu minimal exact de la trace par fonction (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_14_contenu_minimal_de_la_trace(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de `calcul_ae_employe` et
        `calcul_ae_employeur` contiennent au moins :

        - `calcul_ae_employe` : `taux_employe_quebec` dans
          `parametres_utilises` ; `salaire_periode` dans `entrees` ;
          `cotisation_brute` dans `sous_totaux` ;
        - `calcul_ae_employeur` : `multiplicateur_employeur` dans
          `parametres_utilises` ; `ae_employe` dans `entrees` ; le
          produit avant arrondissement final (`cotisation_employeur`)
          dans `sous_totaux`.

        **Validates: Requirements 11.5**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        _montant_employe, trace_employe = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        assert "taux_employe_quebec" in trace_employe.parametres_utilises
        assert "salaire_periode" in trace_employe.entrees
        assert "cotisation_brute" in trace_employe.sous_totaux

        assert "multiplicateur_employeur" in trace_employeur.parametres_utilises
        assert "ae_employe" in trace_employeur.entrees
        assert "cotisation_employeur" in trace_employeur.sous_totaux

    # Feature: cotisations-sociales-qc, Property 15: Cohérence resultat/mode/précision (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_15_coherence_resultat_mode_precision(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, les traces de `calcul_ae_employe` et
        `calcul_ae_employeur` satisfont
        `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`,
        `trace.precision_arrondissement == 2`, et `trace.resultat` est
        égal au montant retourné par la fonction (premier élément du
        tuple) — y compris pour `calcul_ae_employeur`, où `resultat`
        porte la valeur **arrondie** finale, distincte de
        `sous_totaux["cotisation_employeur"]` (produit avant
        arrondissement final).

        **Validates: Requirements 10.4, 11.6**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        montant_employe, trace_employe = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        montant_employeur, trace_employeur = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        for montant, trace in (
            (montant_employe, trace_employe),
            (montant_employeur, trace_employeur),
        ):
            assert trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
            assert trace.precision_arrondissement == 2
            assert trace.resultat == montant

    # Feature: cotisations-sociales-qc, Property 16: Auto-suffisance de la trace (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_16_auto_suffisance_de_la_trace(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, un tiers peut recalculer les
        sous-totaux de trace à partir des seuls contenus de
        `trace.parametres_utilises` et `trace.entrees` — sans consulter
        `payroll_input`, `gains` ni `parametres_annee` :

        - pour `calcul_ae_employe` :
          `trace.sous_totaux["cotisation_brute"] == arrondir(
          trace.parametres_utilises["taux_employe_quebec"] ×
          trace.entrees["salaire_periode"])` ;
        - pour `calcul_ae_employeur` :
          `trace.sous_totaux["cotisation_employeur"] ==
          trace.parametres_utilises["multiplicateur_employeur"] ×
          trace.entrees["ae_employe"]` — produit **sans**
          arrondissement, conformément au design (§Components §7 :
          `sous_totaux` documente l'étape intermédiaire à précision
          complète, `resultat` documente la valeur finale arrondie).

        **Validates: Requirements 11.8**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        _montant_employe, trace_employe = calcul_ae_employe(
            payroll_input, gains, parametres_annee
        )
        _montant_employeur, trace_employeur = calcul_ae_employeur(
            payroll_input, gains, parametres_annee
        )

        taux_employe_quebec = trace_employe.parametres_utilises["taux_employe_quebec"]
        salaire_periode = trace_employe.entrees["salaire_periode"]
        assert trace_employe.sous_totaux["cotisation_brute"] == (
            taux_employe_quebec * salaire_periode
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        multiplicateur = trace_employeur.parametres_utilises["multiplicateur_employeur"]
        ae_employe = trace_employeur.entrees["ae_employe"]
        assert trace_employeur.sous_totaux["cotisation_employeur"] == (
            multiplicateur * ae_employe
        )


# ---------------------------------------------------------------------------
# 4.5 — Propagation de MissingParameterError (AE) (Property 17)
# ---------------------------------------------------------------------------


class TestMissingParameterAe:
    """Property 17 (variante AE) — propagation de `MissingParameterError`
    sans interception.

    Design (§Correctness Properties 17 ; §Error Handling « Matrice des
    exceptions »). Pour chacun des quatre champs de `AEParametres`
    consommés par `calcul_ae_employe`/`calcul_ae_employeur`
    (`taux_employe_quebec`, `multiplicateur_employeur`,
    `cotisation_max_employe`, `cotisation_max_employeur`), marquer ce
    champ `"TO_FILL"` dans le `ParametresAnnee` (via
    `st_parametres_annee_avec_to_fill`) DOIT faire lever
    `MissingParameterError` à l'appel — non interceptée ni masquée par
    une autre exception — pour toute fonction qui lit effectivement ce
    champ.

    Contrairement à RRQ (§Components §2, §3, délégation stricte de
    `calcul_rrq_employeur` vers `calcul_rrq_employe` pour les **trois**
    champs) et à RQAP (§Components §4, §5, deux fonctions strictement
    indépendantes), la dérivation AE employeur (§Components §7, décision
    structurante 5 : `calcul_ae_employeur` appelle *internement*
    `calcul_ae_employe`, cf. `TestDerivationEtPlafonnementAeEmployeur`)
    produit une matrice de propagation **asymétrique** selon le champ :

    - `taux_employe_quebec` et `cotisation_max_employe` sont lus par
      `calcul_ae_employe` (formule et plafonnement employé,
      §Components §6) — via l'appel interne, `calcul_ae_employeur` lève
      donc **également** `MissingParameterError` pour ces deux champs.
    - `multiplicateur_employeur` et `cotisation_max_employeur` ne sont
      lus que par `calcul_ae_employeur` lui-même (dérivation et
      plafonnement employeur, §Components §7) — `calcul_ae_employe`,
      lui, n'y accède jamais et **ne lève rien** pour ces deux champs.
    """

    # -- Champs lus par calcul_ae_employe (et donc propagés à l'employeur) --

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "assurance_emploi.taux_employe_quebec"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_taux_employe_quebec(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `assurance_emploi.taux_employe_quebec`
        porte la sentinelle `"TO_FILL"`, `calcul_ae_employe` **et**
        `calcul_ae_employeur` (par délégation interne, §Components §7)
        lèvent `MissingParameterError`, non interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        with pytest.raises(MissingParameterError):
            calcul_ae_employe(payroll_input, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_ae_employeur(payroll_input, gains, parametres_annee)

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "assurance_emploi.cotisation_max_employe"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_cotisation_max_employe(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `assurance_emploi.cotisation_max_employe`
        porte la sentinelle `"TO_FILL"`, `calcul_ae_employe` **et**
        `calcul_ae_employeur` (par délégation interne — le plafonnement
        employé est exercé à l'intérieur de l'appel employeur,
        §Components §7) lèvent `MissingParameterError`, non
        interceptée.

        **Validates: Requirements 1.9, 12.5**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        with pytest.raises(MissingParameterError):
            calcul_ae_employe(payroll_input, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_ae_employeur(payroll_input, gains, parametres_annee)

    # -- Champs lus exclusivement par calcul_ae_employeur --------------

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "assurance_emploi.multiplicateur_employeur"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_multiplicateur_employeur(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont
        `assurance_emploi.multiplicateur_employeur` porte la sentinelle
        `"TO_FILL"`, `calcul_ae_employeur` lève `MissingParameterError`,
        non interceptée — tandis que `calcul_ae_employe` (qui ne lit
        jamais ce champ, §Components §6) retourne un résultat normal,
        sans lever aucune exception.

        **Validates: Requirements 1.9, 12.5**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        with pytest.raises(MissingParameterError):
            calcul_ae_employeur(payroll_input, gains, parametres_annee)

        resultat_employe = calcul_ae_employe(payroll_input, gains, parametres_annee)
        assert resultat_employe is not None

    # Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (AE)
    @pytest.mark.property
    @given(
        payroll_input=_st_payroll_input_avec_cumuls_non_nuls(),
        gains=_st_gains_decomposes(brut_total_strategy=_st_brut_total_eleve()),
        parametres_annee=st_parametres_annee_avec_to_fill(
            "assurance_emploi.cotisation_max_employeur"
        ),
    )
    @settings_large_input
    def test_property_17_to_fill_cotisation_max_employeur(
        self,
        payroll_input,
        gains,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont
        `assurance_emploi.cotisation_max_employeur` porte la sentinelle
        `"TO_FILL"`, `calcul_ae_employeur` lève `MissingParameterError`,
        non interceptée — tandis que `calcul_ae_employe` (qui ne lit
        jamais le plafond employeur, §Components §6) retourne un
        résultat normal, sans lever aucune exception.

        **Validates: Requirements 1.9, 12.5**
        """
        from payroll_engine.assurance_emploi import (
            calcul_ae_employe,
            calcul_ae_employeur,
        )

        with pytest.raises(MissingParameterError):
            calcul_ae_employeur(payroll_input, gains, parametres_annee)

        resultat_employe = calcul_ae_employe(payroll_input, gains, parametres_annee)
        assert resultat_employe is not None
