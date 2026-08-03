"""Property tests et tests d'exemple pour `calcul_impot_qc_formule`/`calcul_impot_qc_retenu`.

Spec de référence : ``impots-retenues-source`` — tâche 2.1 (squelette et
tests transversaux).
Design de référence : ``design.md`` §Testing Strategy, §Correctness
Properties 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13 (variantes QC) et
§Components §1, §2, §3.

Ce fichier porte l'ensemble des property tests et tests d'exemple du
module ``payroll_engine/impot_qc.py`` (``calcul_impot_qc_formule``,
``calcul_impot_qc_retenu``). La tâche 2.1 pose le squelette : les
imports, les helpers de génération (combinaison des stratégies de
``tests/strategies.py``) et les tests **transversaux** (classe
``TestSignaturePureteRobustesse``) qui s'appliquent identiquement aux
deux fonctions d'impôt QC. Les tâches 2.2 à 2.3 ajouteront
respectivement :

- ``TestFormuleQc`` — Property 5, 4, 8, 9 (variantes QC), tâche 2.2
  (implémentée) ;
- ``TestRetenueQc`` — Property 10, 11 (variantes QC), tâche 2.3.

Propriétés couvertes par ce fichier au fil de la tâche 2 (design.md
§Testing Strategy « Détail des property tests ») : **Property 1, 2, 3,
4, 5, 8, 9, 10, 11, 12, 13 — variantes QC**. La tâche 2.1 (ce squelette)
couvre les trois propriétés transversales :

1. **Property 1 — Déterminisme (pureté)** : deux appels à
   ``calcul_impot_qc_formule`` (puis ``calcul_impot_qc_retenu``) avec les
   mêmes arguments produisent deux tuples égaux au sens ``==``.
2. **Property 2 — Absence d'exception sur entrée valide** : aucun rejet
   pour tout ``PayrollInput``/``GainsDecomposes``/``ParametresAnnee``
   2026 valides, y compris les cas extrêmes (salaire nul, crédit
   personnel nul ou très élevé via ``st_credit_personnel_eleve``,
   retenue additionnelle nulle ou élevée).
3. **Property 3 — Forme ``Decimal`` du résultat et de la trace** : le
   montant retourné et chaque valeur de
   ``trace.parametres_utilises``/``entrees``/``sous_totaux``/``resultat``
   sont des ``Decimal`` finis, égaux à leur propre
   ``.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)``.

**Limitation héritée du corpus golden** (Introduction des requirements,
design §Testing Strategy) : les six scénarios QC001–QC006 ne portent
aucune retenue additionnelle QC non nulle et ne couvrent que des crédits
personnels proches du montant personnel de base 2026. Le comportement
sous le seuil d'imposition avec crédit personnel très élevé (Property 8)
et l'ajout d'une retenue additionnelle non nulle (Property 10) ne sont
donc couverts que par les property tests de ce fichier, via
``st_credit_personnel_eleve()`` et les helpers de génération locaux.

Discipline règle 06 (TDD — tests avant code) : ``payroll_engine/impot_qc.py``
n'existe **pas encore** à ce stade (il sera implémenté par la tâche 9.1).
À l'image du squelette de ``tests/payroll_engine/test_rrq.py`` (spec
``cotisations-sociales-qc``, tâche 2.1), ce fichier importe
``calcul_impot_qc_formule`` et ``calcul_impot_qc_retenu`` **au niveau
module** : la collecte pytest de ce fichier échoue donc actuellement avec
``ModuleNotFoundError`` sur ``payroll_engine.impot_qc`` — c'est le
comportement **attendu et correct** tant que la tâche 9.1
(implémentation) n'a pas été réalisée.

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from unittest.mock import patch  # noqa: F401  (utilisé par Property 11, tâche 2.3)

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.enums import Juridiction, ModeArrondissement  # noqa: F401  (tâches 2.2/2.3)
from models.exceptions import MissingParameterError  # noqa: F401  (Property 13, tâche 2.x)
from models.payroll_input import PayrollInput
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.impot_qc import calcul_impot_qc_formule, calcul_impot_qc_retenu
from payroll_engine.parameters_loader import load_parameters
from tests.strategies import (
    st_brut_total_avec_zero,
    st_credit_personnel_eleve,
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_impot_avec_to_fill,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_rrq.py)
# ---------------------------------------------------------------------------

# Le nombre d'exemples est piloté par le profil Hypothesis actif
# (voir ``tests/conftest.py`` : dev=15 par défaut, ci=100).
settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@pytest.fixture(scope="module")
def parametres_2026_reels():
    """`ParametresAnnee` réel 2026 Québec pour les tests d'exemple chiffrés.

    Chargé une seule fois par module via `load_parameters(2026,
    Juridiction.QUEBEC)` (règle 05 — aucune valeur fiscale codée en dur ;
    la section `impot_quebec` consommée par `calcul_impot_qc_formule`
    provient exclusivement de `parameters/2026/quebec.json`). Distinct de
    la stratégie Hypothesis `st_parametres_annee_2026_qc_ca()` : les tests
    d'exemple (non paramétrés par `@given`) ont besoin d'une instance
    concrète, pas d'une stratégie.
    """
    return load_parameters(2026, Juridiction.QUEBEC)


# ---------------------------------------------------------------------------
# Helpers internes de génération — combinent les stratégies de
# tests/strategies.py pour produire des entrées couvrant les cas extrêmes
# de Property 2 (salaire nul ou très élevé, crédit personnel nul ou très
# élevé, retenue additionnelle nulle ou élevée), non couverts par le
# corpus golden QC001–QC006.
#
# Note « fixture module-scoped » (tâche 2.1) : les paramètres annuels
# réels 2026 (fusion Québec + Canada) sont fournis par la stratégie
# ``st_parametres_annee_2026_qc_ca()``, dont la fabrique sous-jacente est
# mémorisée au niveau module via ``functools.lru_cache(maxsize=1)`` dans
# ``tests/strategies.py`` : les fichiers ``parameters/2026/*.json`` ne
# sont donc lus qu'une seule fois par processus de test, quel que soit le
# nombre d'exemples Hypothesis générés (équivalent d'une fixture
# module-scoped). ``ParametresAnnee`` étant ``frozen=True``, l'instance
# partagée entre tous les exemples ne peut pas être mutée par un test.
# ---------------------------------------------------------------------------


def _construire_gains_decomposes(brut_total: Decimal) -> GainsDecomposes:
    """``GainsDecomposes`` valide, minimal, pour un ``brut_total`` donné.

    Seul ``brut_total`` importe pour les quatre fonctions d'impôt de
    cette spec (Req 1.6 — lecture exclusive de ``gains.brut_total``) ; les
    autres composantes du brut sont mises à zéro pour ne pas introduire de
    bruit hors du périmètre de cette spec. ``multiplicateur_heures_supp``
    et ``seuil_heures_supp_hebdo`` sont des valeurs de contexte portées
    par contrat (``gt=0``) mais non consommées par le Moteur_Impots — les
    valeurs ``1.5``/``40`` ne sont pas des paramètres fiscaux au sens de la
    règle 05, seulement des valeurs de forme requises par
    ``GainsDecomposes``. Helper dupliqué localement (même convention que
    ``tests/payroll_engine/test_rrq.py`` : duplication triviale préférée à
    un ``conftest`` transversal).
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
    exercer le cas « salaire de période très élevé » exigé par Property 2
    (design §Correctness Properties 2), qui pousse le revenu imposable
    annualisé dans les paliers progressifs supérieurs.
    """
    return st.decimals(
        min_value=Decimal("5000.01"),
        max_value=Decimal("1000000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


def _st_retenue_additionnelle_avec_zero_et_elevee() -> st.SearchStrategy[Decimal]:
    """``Decimal`` de retenue additionnelle, biaisé vers ``0.00`` et vers des valeurs élevées.

    Design (§Correctness Properties 2) : la retenue additionnelle QC/fed
    doit être exercée à ``Decimal("0.00")`` (cas nominal du corpus golden)
    **et** à des montants élevés (jusqu'à ``5000.00 $``) pour couvrir
    l'ajout inconditionnel de la retenue additionnelle (Property 10, tâche
    2.3) sans dépendre du corpus golden — aucune fixture QC001–QC006 ne
    porte de retenue additionnelle non nulle. Règle 01 : ``Decimal``
    exclusivement.
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
def _st_payroll_input_impot(draw: st.DrawFn) -> PayrollInput:
    """``PayrollInput`` couvrant les cas extrêmes propres à l'impôt.

    Part de ``st_payroll_input()`` (héritée sans modification de
    ``cotisations-sociales-qc``, cohérente par construction — Québec, aux
    deux semaines, appariement cumuls/employé/année) puis **remplace**
    sélectivement, sans mutation (``model_copy(update=...)`` — règle 06,
    immuabilité) :

    - ``montant_total_TP1015_3_effectif`` / ``montant_total_TD1_effectif``
      par un crédit personnel très élevé (``st_credit_personnel_eleve()``)
      dans une partie des exemples, pour exercer le comportement sous le
      seuil d'imposition (Property 8 / Requirement 12.5) sans dépendre du
      corpus golden ;
    - ``retenue_additionnelle_QC_effective`` /
      ``retenue_additionnelle_federale_effective`` par une valeur nulle ou
      élevée (``_st_retenue_additionnelle_avec_zero_et_elevee()``).

    Le tirage ``st.one_of(st.none(), ...)`` conserve dans une partie des
    exemples les valeurs déjà produites par ``st_payroll_input()`` (crédit
    proche du montant personnel de base) : les deux régimes (crédit
    « normal » et crédit « très élevé ») sont donc couverts.
    """
    payroll_input = draw(st_payroll_input())

    updates: dict[str, Decimal] = {}

    credit_qc = draw(st.one_of(st.none(), st_credit_personnel_eleve()))
    if credit_qc is not None:
        updates["montant_total_TP1015_3_effectif"] = credit_qc

    credit_fed = draw(st.one_of(st.none(), st_credit_personnel_eleve()))
    if credit_fed is not None:
        updates["montant_total_TD1_effectif"] = credit_fed

    updates["retenue_additionnelle_QC_effective"] = draw(
        _st_retenue_additionnelle_avec_zero_et_elevee()
    )
    updates["retenue_additionnelle_federale_effective"] = draw(
        _st_retenue_additionnelle_avec_zero_et_elevee()
    )

    return payroll_input.model_copy(update=updates)


@st.composite
def _st_entrees_completes(draw: st.DrawFn) -> tuple[PayrollInput, GainsDecomposes]:
    """``(PayrollInput, GainsDecomposes)`` couvrant les cas extrêmes de
    Property 2 : salaire de période nul ou très élevé
    (``st_brut_total_avec_zero`` / ``_st_brut_total_eleve``), crédit
    personnel nul, normal ou très élevé, retenue additionnelle nulle ou
    élevée (``_st_payroll_input_impot``).
    """
    payroll_input = draw(_st_payroll_input_impot())
    brut_total = draw(st.one_of(st_brut_total_avec_zero(), _st_brut_total_eleve()))
    gains = _construire_gains_decomposes(brut_total)
    return payroll_input, gains


def _verifier_property_3_forme_decimal(montant: Decimal, trace: CalculationTrace) -> None:
    """Vérifie Property 3 (design §Correctness Properties 3) pour un
    couple ``(montant, trace)`` retourné par une des fonctions d'impôt QC.

    - Chaque valeur de ``trace.parametres_utilises``/``entrees``/
      ``sous_totaux``, plus ``montant`` et ``trace.resultat`` eux-mêmes,
      est un ``Decimal`` fini (``isinstance`` + ``is_finite()``).
    - ``montant`` et ``trace.resultat`` sont en outre égaux à leur propre
      ``.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)``.
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
# 2.1 — Signature, pureté et robustesse (Property 1, 2, 3)
# ---------------------------------------------------------------------------


class TestSignaturePureteRobustesse:
    """Property 1, 2, 3 — déterminisme, absence d'exception, forme `Decimal`.

    Design (§Correctness Properties 1, 2, 3 ; §Components §1 « Signatures
    exactes »). Ces trois propriétés s'appliquent identiquement à
    `calcul_impot_qc_formule` et `calcul_impot_qc_retenu`, plus un test
    d'exemple vérifiant l'absence d'effet de bord à l'import (Req 1.9).
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
        `ParametresAnnee` valides, `calcul_impot_qc_formule(pi, g, p) ==
        calcul_impot_qc_formule(pi, g, p)` et de même pour
        `calcul_impot_qc_retenu` : deux appels avec les mêmes arguments
        produisent deux tuples égaux au sens `==` sur les deux
        composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.4**
        """
        payroll_input, gains = entrees

        resultat_formule_1 = calcul_impot_qc_formule(payroll_input, gains, parametres_annee)
        resultat_formule_2 = calcul_impot_qc_formule(payroll_input, gains, parametres_annee)
        assert resultat_formule_1 == resultat_formule_2
        assert resultat_formule_1[0] == resultat_formule_2[0]
        assert resultat_formule_1[1] == resultat_formule_2[1]

        resultat_retenu_1 = calcul_impot_qc_retenu(payroll_input, gains, parametres_annee)
        resultat_retenu_2 = calcul_impot_qc_retenu(payroll_input, gains, parametres_annee)
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
        `ParametresAnnee` valides — y compris les cas extrêmes (salaire
        nul, crédit personnel nul ou très élevé, retenue additionnelle
        nulle ou élevée) — `calcul_impot_qc_formule` et
        `calcul_impot_qc_retenu` retournent un tuple sans lever aucune
        exception.

        **Validates: Requirements 1.8, 12.1**
        """
        payroll_input, gains = entrees

        resultat_formule = calcul_impot_qc_formule(payroll_input, gains, parametres_annee)
        resultat_retenu = calcul_impot_qc_retenu(payroll_input, gains, parametres_annee)

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
        sont des `Decimal` finis, égaux à leur propre
        `.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`.

        **Validates: Requirements 2.6, 2.7, 3.4, 3.5**
        """
        payroll_input, gains = entrees

        montant_formule, trace_formule = calcul_impot_qc_formule(
            payroll_input, gains, parametres_annee
        )
        _verifier_property_3_forme_decimal(montant_formule, trace_formule)

        montant_retenu, trace_retenu = calcul_impot_qc_retenu(
            payroll_input, gains, parametres_annee
        )
        _verifier_property_3_forme_decimal(montant_retenu, trace_retenu)

    def test_import_calcul_impot_qc_sans_effet_de_bord(self, capsys) -> None:
        """Test d'exemple — `from payroll_engine.impot_qc import
        calcul_impot_qc_formule, calcul_impot_qc_retenu` ne produit
        **aucun effet de bord** (Req 1.9) : pas d'ouverture de fichier,
        pas d'appel réseau, pas d'écriture sur `stdout` / `stderr`, aucune
        action au moment de l'import.

        Design (§Architecture « Contrainte de pureté »). Le module est
        retiré de `sys.modules` avant l'import (s'il y était déjà chargé
        par un import précédent) afin de forcer une exécution fraîche du
        corps du module — c'est justement à ce moment-là qu'un éventuel
        effet de bord au niveau module se manifesterait.
        """
        nom_module = "payroll_engine.impot_qc"
        sys.modules.pop(nom_module, None)

        module = importlib.import_module(nom_module)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert nom_module in sys.modules
        assert hasattr(module, "calcul_impot_qc_formule")
        assert hasattr(module, "calcul_impot_qc_retenu")


# ---------------------------------------------------------------------------
# 2.2 — Helpers de reconstruction et stratégies dédiées à la formule QC
# ---------------------------------------------------------------------------
#
# Property 5 (« reconstruction intégrale à partir des seules valeurs de
# trace ») exige de rejouer, côté test, exactement la même arithmétique
# `Decimal` que celle décrite au design §Components §2. Les deux helpers
# ci-dessous dupliquent volontairement — à des fins de vérification
# indépendante — l'arrondissement `ROUND_HALF_UP` à deux décimales et la
# recherche de palier (« dernier palier dont `seuil_bas_annuel <=
# revenu_imposable_annuel` »). Règle 01 : `Decimal` exclusivement, aucun
# `float`. Règle 05 : aucun taux/seuil/constante n'est codé en dur ici —
# le taux et la constante du palier proviennent exclusivement de
# `parametres_annee.impot_quebec.paliers`.


def _arrondir_2(montant: Decimal) -> Decimal:
    """Arrondi monétaire `ROUND_HALF_UP` à deux décimales (design §Components §2).

    Réplique indépendante du helper privé `_arrondir` de
    `payroll_engine/impot_qc.py` (design §Architecture « Helper
    d'arrondissement partagé »), pour vérifier Property 5 sans importer
    l'implémentation.
    """
    return montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _taux_et_constante_pour_palier(
    revenu_annuel: Decimal, paliers
) -> tuple[Decimal, Decimal]:
    """(taux, constante_k) du dernier palier dont `seuil_bas_annuel <= revenu_annuel`.

    Réplique indépendante du helper privé
    `_taux_et_constante_pour_palier` de `payroll_engine/impot_qc.py`
    (design §Architecture « Helper de recherche de palier »). `paliers`
    est supposé trié par `seuil_bas_annuel` croissant (invariant
    documenté du fichier JSON, design §Architecture). Lecture exclusive
    des paliers typés de `parametres_annee.impot_quebec.paliers`
    (règle 05).
    """
    palier_applicable = paliers[0]
    for palier in paliers:
        if palier.seuil_bas_annuel <= revenu_annuel:
            palier_applicable = palier
        else:
            break
    return (palier_applicable.taux, palier_applicable.constante_k)


@st.composite
def _st_entrees_credit_qc_eleve(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes]:
    """`(PayrollInput, GainsDecomposes)` à crédit personnel QC très élevé.

    Force `montant_total_TP1015_3_effectif` à une valeur issue de
    `st_credit_personnel_eleve()` (≥ 100 000 $, jusqu'à 1 000 000 $) et
    borne le `brut_total` à `[0, 5000]` (`st_brut_total_avec_zero`) afin
    que le revenu imposable annualisé (≈ `brut × nb_periodes`) reste
    largement en deçà du crédit dans la grande majorité des exemples :
    condition du comportement sous le seuil d'imposition (Property 8,
    design §Correctness Properties 8). Aucune mutation en place —
    `model_copy(update=...)` (règle 06, immuabilité).
    """
    payroll_input = draw(st_payroll_input())
    credit = draw(st_credit_personnel_eleve())
    payroll_input = payroll_input.model_copy(
        update={"montant_total_TP1015_3_effectif": credit}
    )
    brut_total = draw(st_brut_total_avec_zero())
    gains = _construire_gains_decomposes(brut_total)
    return payroll_input, gains


@st.composite
def _st_paire_input_exoneration_retenue_qc(
    draw: st.DrawFn,
) -> tuple[PayrollInput, PayrollInput, GainsDecomposes]:
    """Paire `(base, variante)` identique **sauf** sur les quatre champs
    d'exonération / retenue additionnelle, plus le `GainsDecomposes` partagé.

    Design (§Correctness Properties 9) : la variante inverse les deux
    drapeaux d'exonération (`exoneration_TP1015_3_effectif`,
    `exoneration_TD1_effective`) et remplace les deux retenues
    additionnelles (`retenue_additionnelle_QC_effective`,
    `retenue_additionnelle_federale_effective`) par des valeurs tirées
    indépendamment — tous les autres champs (dont
    `montant_total_TP1015_3_effectif`, seul champ de crédit consommé par
    la formule QC) restent strictement identiques. `model_copy(update=...)`
    garantit l'absence de mutation (règle 06).
    """
    payroll_input, gains = draw(_st_entrees_completes())
    variante = payroll_input.model_copy(
        update={
            "exoneration_TP1015_3_effectif": (
                not payroll_input.exoneration_TP1015_3_effectif
            ),
            "exoneration_TD1_effective": (
                not payroll_input.exoneration_TD1_effective
            ),
            "retenue_additionnelle_QC_effective": draw(
                _st_retenue_additionnelle_avec_zero_et_elevee()
            ),
            "retenue_additionnelle_federale_effective": draw(
                _st_retenue_additionnelle_avec_zero_et_elevee()
            ),
        }
    )
    return payroll_input, variante, gains


#: Configuration Hypothesis pour le comportement sous le seuil
#: d'imposition (Property 7 et Property 8 — surface d'entrée large
#: combinant crédits personnels très élevés et revenus variés).
#: Le nombre d'exemples est désormais piloté par le profil Hypothesis
#: actif (voir ``tests/conftest.py`` : dev=15 par défaut, ci=100).
settings_seuil = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# 2.2 — Formule QC : assiette, palier, crédit personnel, bornes, seuil
# ---------------------------------------------------------------------------


class TestFormuleQc:
    """Property 5, 4, 8, 9 (variantes QC) — formule d'impôt du Québec.

    Design (§Correctness Properties 4, 5, 8, 9 ; §Components §2). Ces
    propriétés portent sur `calcul_impot_qc_formule` : reconstruction
    intégrale de la formule à partir de la trace (Property 5), plancher à
    zéro (Property 4), comportement sous le seuil d'imposition
    (Property 8) et indépendance totale vis-à-vis des champs d'exonération
    et de retenue additionnelle (Property 9). Un test d'exemple reproduit
    le scénario chiffré QC004 (revenu annualisé sous le crédit personnel).
    """

    # Feature: impots-retenues-source, Property 5: Formule QC — assiette, palier et crédit personnel
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_5_reconstruction_integrale_depuis_la_trace(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et
        `ParametresAnnee` valides, le résultat de `calcul_impot_qc_formule`
        est **intégralement reconstructible** à partir des seules valeurs
        de sa trace (auto-suffisance, design §Components §2). La
        reconstruction recompose la chaîne à partir des entrées et des
        paramètres de la trace (et non des sous-totaux, exposés arrondis
        au cent — Property 3). La formule officielle TP-1015.F 2026
        comporte DEUX arrondissements monétaires : la déduction pour
        travailleur de période `H` et le montant final `impot_periode`
        (Req 8.1) :

        - `deduction_travailleur_periode == arrondir(min(
          taux_deduction_pour_travailleur × salaire_periode,
          deduction_pour_travailleur_annuelle / nb_periodes))` — formule
          officielle `H = arrondir(min(0,06 × D ; 1 450 $ ÷ P))`,
          arrondie au cent (comportement WebRAS) ;
        - `revenu_imposable_periode == max(0, salaire_periode -
          deduction_travailleur_periode -
          taux_rrq_supp × max(0, salaire_periode - exemption_rrq_periode))`
          — DEUX déductions distinctes : déduction pour travailleur
          **et** déduction pour la première cotisation supplémentaire
          au RRQ ;
        - `revenu_imposable_annuel == revenu_imposable_periode ×
          nb_periodes` ;
        - `(taux_palier, constante_k)` correspond au dernier palier de
          `parametres_annee.impot_quebec.paliers` dont `seuil_bas_annuel
          <= revenu_imposable_annuel` ;
        - `impot_annuel_base == max(0, taux_palier ×
          revenu_imposable_annuel - constante_k)` ;
        - `impot_annuel_net == impot_annuel_base -
          taux_credits_convertibles × montant_total_tp1015_3` ;
        - `resultat == max(0, arrondir(impot_annuel_net / nb_periodes))`
          `== montant`.

        Chaque étape est comparée par égalité stricte `Decimal` (`==`,
        tolérance nulle — règle 01) à la valeur homonyme exposée dans
        `trace.sous_totaux`, puis le montant retourné est confronté à la
        reconstruction finale.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 9.7**
        """
        payroll_input, gains = entrees

        montant, trace = calcul_impot_qc_formule(
            payroll_input, gains, parametres_annee
        )

        # --- Valeurs lues exclusivement dans la trace ---
        salaire_periode = trace.entrees["salaire_periode"]
        nb_periodes = trace.entrees["nb_periodes_annuelles"]
        montant_tp1015_3 = trace.entrees["montant_total_tp1015_3"]
        deduction_annuelle = trace.parametres_utilises[
            "deduction_pour_travailleur_annuelle"
        ]
        taux_deduction_pour_travailleur = trace.parametres_utilises[
            "taux_deduction_pour_travailleur"
        ]
        taux_conversion = trace.parametres_utilises["taux_credits_convertibles"]
        taux_palier_trace = trace.parametres_utilises["taux_palier"]
        constante_k_trace = trace.parametres_utilises["constante_k"]
        taux_rrq_supp = trace.parametres_utilises["taux_rrq_supp"]
        exemption_rrq_periode = trace.parametres_utilises["exemption_rrq_periode"]

        # --- Assiette : DEUX déductions distinctes, reconstruite à
        #     partir des seules entrées et paramètres de la trace
        #     (design §Components §2). La déduction pour travailleur
        #     suit la formule officielle TP-1015.F 2026
        #     `H = arrondir(min(taux × D ; plafond ÷ P))`, arrondie au
        #     cent (comportement WebRAS). La déduction RRQ supplémentaire
        #     et le reste du calcul restent en pleine précision jusqu'à
        #     l'arrondissement FINAL de `impot_periode` (Req 8.1). ---
        deduction_travailleur_periode = _arrondir_2(
            min(
                taux_deduction_pour_travailleur * salaire_periode,
                deduction_annuelle / nb_periodes,
            )
        )
        deduction_rrq_supp_periode = taux_rrq_supp * max(
            Decimal("0.00"), salaire_periode - exemption_rrq_periode
        )
        revenu_imposable_periode = max(
            Decimal("0.00"),
            salaire_periode
            - deduction_travailleur_periode
            - deduction_rrq_supp_periode,
        )
        revenu_imposable_annuel = revenu_imposable_periode * nb_periodes

        # --- Palier applicable : cohérence trace <-> paramètres réels ---
        taux_attendu, constante_attendue = _taux_et_constante_pour_palier(
            revenu_imposable_annuel, parametres_annee.impot_quebec.paliers
        )
        assert taux_palier_trace == taux_attendu
        assert constante_k_trace == constante_attendue

        # --- Impôt annuel de base (plancher à zéro) ---
        impot_annuel_base = max(
            Decimal("0.00"),
            taux_palier_trace * revenu_imposable_annuel - constante_k_trace,
        )

        # --- Crédit personnel convertible et impôt annuel net ---
        credit_personnel_annuel = taux_conversion * montant_tp1015_3
        impot_annuel_net = impot_annuel_base - credit_personnel_annuel

        # --- Montant de période : arrondi UNIQUE final puis plancher à zéro ---
        resultat_reconstruit = max(
            Decimal("0.00"), _arrondir_2(impot_annuel_net / nb_periodes)
        )
        assert resultat_reconstruit == montant
        assert resultat_reconstruit == trace.resultat

    # Feature: impots-retenues-source, Property 4: Montant jamais strictement négatif (QC)
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
        `ParametresAnnee` valides, `calcul_impot_qc_formule(...)[0] >=
        Decimal("0.00")` : le montant de retenue par la formule n'est
        jamais strictement négatif, quel que soit le crédit personnel (nul
        ou très élevé), grâce au plancher `max(Decimal("0.00"), ...)`
        appliqué à l'impôt de période (design §Components §2).

        **Validates: Requirements 2.7, 12.4**
        """
        payroll_input, gains = entrees

        montant, _trace = calcul_impot_qc_formule(
            payroll_input, gains, parametres_annee
        )

        assert montant >= Decimal("0.00")

    # Feature: impots-retenues-source, Property 8: Comportement sous le seuil d'imposition (QC)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_credit_qc_eleve(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_seuil
    def test_property_8_comportement_sous_le_seuil_d_imposition(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` dont le crédit personnel effectif
        (`montant_total_TP1015_3_effectif`) est très élevé, lorsque le
        revenu imposable annuel devient inférieur ou égal à ce crédit,
        `calcul_impot_qc_formule` retourne `Decimal("0.00")` sans lever
        d'exception — indépendamment de la valeur de
        `exoneration_TP1015_3_effectif` (la formule n'inspecte jamais ce
        drapeau, design §Components §2, Requirement 2.8).

        Justification du plancher (design §Correctness Properties 8) : si
        `credit >= revenu_imposable_annuel`, alors
        `credit_personnel_annuel = taux × credit >= taux ×
        revenu_imposable_annuel >= impot_annuel_base`, donc
        `impot_annuel_net <= 0` et le `max(0, ...)` final produit
        `Decimal("0.00")`.

        **Validates: Requirements 2.5, 7.1, 12.5**
        """
        payroll_input, gains = entrees

        montant, trace = calcul_impot_qc_formule(
            payroll_input, gains, parametres_annee
        )

        revenu_imposable_annuel = trace.sous_totaux["revenu_imposable_annuel"]
        credit_effectif = payroll_input.montant_total_TP1015_3_effectif
        if revenu_imposable_annuel <= credit_effectif:
            assert montant == Decimal("0.00")

        # Indépendance vis-à-vis de l'exonération : la formule ignore ce
        # drapeau (Req 2.8), les deux valeurs de l'exonération donnent donc
        # exactement le même montant.
        for exoneration in (True, False):
            payroll_input_exo = payroll_input.model_copy(
                update={"exoneration_TP1015_3_effectif": exoneration}
            )
            montant_exo, _trace_exo = calcul_impot_qc_formule(
                payroll_input_exo, gains, parametres_annee
            )
            assert montant_exo == montant

    # Feature: impots-retenues-source, Property 9: Non-consultation des champs d'exonération/retenue additionnelle (QC)
    @pytest.mark.property
    @given(
        paire=_st_paire_input_exoneration_retenue_qc(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_9_non_consultation_exoneration_retenue_additionnelle(
        self,
        paire: tuple[PayrollInput, PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour toute* paire de `PayrollInput` identiques sauf sur
        `exoneration_TP1015_3_effectif` / `exoneration_TD1_effective` /
        `retenue_additionnelle_QC_effective` /
        `retenue_additionnelle_federale_effective`,
        `calcul_impot_qc_formule` retourne des résultats **identiques** —
        montant **et** trace (design §Correctness Properties 9,
        Requirement 2.8). La fonction formule n'inspecte aucun de ces
        quatre champs.

        **Validates: Requirements 2.8**
        """
        payroll_input_base, payroll_input_variante, gains = paire

        resultat_base = calcul_impot_qc_formule(
            payroll_input_base, gains, parametres_annee
        )
        resultat_variante = calcul_impot_qc_formule(
            payroll_input_variante, gains, parametres_annee
        )

        assert resultat_base == resultat_variante
        assert resultat_base[0] == resultat_variante[0]
        assert resultat_base[1] == resultat_variante[1]

    def test_exemple_qc004_revenu_sous_le_credit_personnel(
        self,
        fixtures_inputs_dir,
        fixtures_outputs_dir,
        parametres_2026_reels,
    ) -> None:
        """Test d'exemple — reproduction chiffrée de QC004 (Requirement 7.3).

        Le scénario QC004 (moniteur à temps très partiel : `brut_total =
        294,84 $`, 27 périodes) produit un revenu annualisé
        (`≈ 7 960,68 $`) largement inférieur au crédit personnel QC
        (`montant_total_TP1015_3_effectif = 18 952,00 $`).
        `exoneration_TP1015_3_effectif` vaut `False` : la retenue nulle
        est donc obtenue **par la seule formule** (comportement sous le
        seuil d'imposition), et non par un court-circuit d'exonération.

        Le `PayrollInput` est chargé depuis la fixture d'entrée réelle et
        le `GainsDecomposes` reconstruit depuis la section `gains` de la
        fixture de sortie ; les paramètres 2026 sont les paramètres réels
        (`load_parameters`, règle 05 — aucune valeur fiscale codée en
        dur).

        Validates: Requirements 7.1, 7.2, 7.3
        """
        texte_entree = (fixtures_inputs_dir / "qc004.json").read_text(
            encoding="utf-8"
        )
        payroll_input = PayrollInput.model_validate_json(texte_entree)

        sortie = json.loads(
            (fixtures_outputs_dir / "qc004.json").read_text(encoding="utf-8")
        )
        gains = GainsDecomposes.model_validate(sortie["gains"])

        assert payroll_input.exoneration_TP1015_3_effectif is False

        montant, trace = calcul_impot_qc_formule(
            payroll_input, gains, parametres_2026_reels
        )

        assert montant == Decimal("0.00")
        assert trace.resultat == Decimal("0.00")


# ---------------------------------------------------------------------------
# 2.3 — Court-circuit d'exonération et retenue additionnelle QC
# ---------------------------------------------------------------------------
#
# Property 10 et Property 11 (variantes QC) portent sur
# `calcul_impot_qc_retenu` (design §Correctness Properties 10, 11 ;
# §Components §3) :
#
# - Property 10 vérifie le contrat de valeur : sous exonération active, la
#   retenue effective est exactement `retenue_additionnelle_QC_effective` ;
#   sous exonération inactive, elle vaut exactement
#   `calcul_impot_qc_formule(...)[0] + retenue_additionnelle_QC_effective`.
#   Dans les deux cas la retenue additionnelle s'ajoute inconditionnellement
#   (le court-circuit ne concerne que le montant de base, jamais la retenue
#   additionnelle — Req 3.2).
# - Property 11 vérifie le contrat structurel : le court-circuit est
#   **véritable** (Req 3.3) — sous exonération active, la fonction formule
#   n'est jamais invoquée, pas même pour construire la trace. Un espion
#   (`unittest.mock.patch`) posé sur `calcul_impot_qc_formule` dans le
#   **namespace du module** `payroll_engine.impot_qc` (là où
#   `calcul_impot_qc_retenu` résout le nom) doit rester non appelé.
#
# Règle 01 : `Decimal` exclusivement dans les assertions. Règle 05 : aucun
# taux/seuil n'est codé en dur ici — les montants proviennent de la formule
# et des champs `payroll_input`.


@st.composite
def _st_entrees_exoneration_qc_active(
    draw: st.DrawFn,
) -> tuple[PayrollInput, GainsDecomposes]:
    """`(PayrollInput, GainsDecomposes)` avec `exoneration_TP1015_3_effectif == True`.

    Part de `_st_entrees_completes()` (qui couvre déjà salaire nul ou
    élevé, crédit personnel nul/normal/élevé et retenue additionnelle
    nulle ou élevée) puis force le drapeau d'exonération QC à `True` sans
    mutation en place (`model_copy(update=...)` — règle 06, immuabilité).
    Utilisée par Property 11 (court-circuit véritable), qui exige un
    `PayrollInput` sous exonération active pour vérifier que la fonction
    formule n'est jamais invoquée.
    """
    payroll_input, gains = draw(_st_entrees_completes())
    payroll_input = payroll_input.model_copy(
        update={"exoneration_TP1015_3_effectif": True}
    )
    return payroll_input, gains


class TestRetenueQc:
    """Property 10, 11 (variantes QC) — retenue d'impôt QC effective.

    Design (§Correctness Properties 10, 11 ; §Components §3). Ces deux
    propriétés portent sur `calcul_impot_qc_retenu` : court-circuit
    d'exonération et ajout inconditionnel de la retenue additionnelle
    (Property 10, contrat de valeur), et court-circuit **véritable**
    vérifié par espion sur la fonction formule (Property 11, contrat
    structurel). Un test d'exemple confirme le cas « exonération active +
    retenue additionnelle strictement positive » (Requirement 12.2).
    """

    # Feature: impots-retenues-source, Property 10: Court-circuit d'exonération et ajout de la retenue additionnelle (QC)
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

        - si `exoneration_TP1015_3_effectif == True`, `calcul_impot_qc_retenu`
          retourne **exactement** `retenue_additionnelle_QC_effective`
          (le montant de base est court-circuité à `Decimal("0.00")`) ;
        - si `exoneration_TP1015_3_effectif == False`, `calcul_impot_qc_retenu`
          retourne **exactement** `calcul_impot_qc_formule(...)[0] +
          retenue_additionnelle_QC_effective`.

        Dans les deux cas la retenue additionnelle s'ajoute
        inconditionnellement (design §Correctness Properties 10,
        Req 3.2). L'entrée générée est déclinée en deux variantes ne
        différant que par le drapeau d'exonération (`model_copy` — aucune
        mutation), toutes deux comparées par égalité stricte `Decimal`
        (tolérance nulle, règle 01).

        **Validates: Requirements 3.1, 3.2, 12.2**
        """
        payroll_input, gains = entrees

        # --- Exonération active : montant de base court-circuité à zéro ---
        payroll_input_exo = payroll_input.model_copy(
            update={"exoneration_TP1015_3_effectif": True}
        )
        montant_exo, _trace_exo = calcul_impot_qc_retenu(
            payroll_input_exo, gains, parametres_annee
        )
        assert (
            montant_exo == payroll_input_exo.retenue_additionnelle_QC_effective
        )

        # --- Exonération inactive : formule + retenue additionnelle ---
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TP1015_3_effectif": False}
        )
        montant_formule, _trace_formule = calcul_impot_qc_formule(
            payroll_input_non_exo, gains, parametres_annee
        )
        montant_retenu, _trace_retenu = calcul_impot_qc_retenu(
            payroll_input_non_exo, gains, parametres_annee
        )
        assert (
            montant_retenu
            == montant_formule
            + payroll_input_non_exo.retenue_additionnelle_QC_effective
        )

    # Feature: impots-retenues-source, Property 11: Court-circuit véritable (formule non invoquée sous exonération) (QC)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_exoneration_qc_active(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_11_court_circuit_veritable_formule_non_invoquee(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` tel que
        `exoneration_TP1015_3_effectif == True`, un espion posé sur
        `calcul_impot_qc_formule` dans le **namespace du module**
        `payroll_engine.impot_qc` (là où `calcul_impot_qc_retenu` résout
        le nom) n'est **jamais appelé** lors de l'exécution de
        `calcul_impot_qc_retenu` — le court-circuit est véritable, pas un
        simple remplacement du résultat par zéro après calcul (design
        §Correctness Properties 11, Req 3.3).

        Le patch cible bien `payroll_engine.impot_qc.calcul_impot_qc_formule`
        (le nom tel que la fonction retenue le résout via ses globals de
        module) et non le nom réimporté dans ce module de test.

        **Validates: Requirements 3.3**
        """
        payroll_input, gains = entrees
        assert payroll_input.exoneration_TP1015_3_effectif is True

        with patch(
            "payroll_engine.impot_qc.calcul_impot_qc_formule"
        ) as espion_formule:
            montant, _trace = calcul_impot_qc_retenu(
                payroll_input, gains, parametres_annee
            )

        espion_formule.assert_not_called()
        # Cohérence : sous exonération active, la retenue effective se
        # réduit à la seule retenue additionnelle (montant de base nul).
        assert montant == payroll_input.retenue_additionnelle_QC_effective

    def test_exemple_exoneration_active_retenue_additionnelle_positive(
        self,
        fixtures_inputs_dir,
        fixtures_outputs_dir,
        parametres_2026_reels,
    ) -> None:
        """Test d'exemple — exonération QC active + retenue additionnelle
        strictement positive (Requirement 12.2).

        Le `PayrollInput` de QC001 est chargé depuis la fixture d'entrée
        réelle puis décliné (`model_copy` — aucune mutation) pour activer
        l'exonération TP-1015.3 et porter une retenue additionnelle QC
        strictement positive (`25,00 $`). Aucune fixture du corpus
        QC001–QC006 ne combine exonération active et retenue additionnelle
        non nulle (Introduction des requirements) : ce cas n'est donc
        couvert que par ce test d'exemple et par Property 10.

        La retenue effective attendue est **strictement égale** à la
        retenue additionnelle (le montant de base est court-circuité à
        `Decimal("0.00")`), et la trace expose `retenue_effective ==
        montant`. Les paramètres 2026 sont les paramètres réels
        (`load_parameters`, règle 05).

        Validates: Requirements 3.1, 3.2, 12.2
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
                "exoneration_TP1015_3_effectif": True,
                "retenue_additionnelle_QC_effective": retenue_additionnelle,
            }
        )
        assert payroll_input.exoneration_TP1015_3_effectif is True
        assert payroll_input.retenue_additionnelle_QC_effective > Decimal("0.00")

        montant, trace = calcul_impot_qc_retenu(
            payroll_input, gains, parametres_2026_reels
        )

        assert montant == retenue_additionnelle
        assert trace.resultat == retenue_additionnelle


# ---------------------------------------------------------------------------
# 2.4 — Trace des deux fonctions QC (Property 12, variante QC)
# ---------------------------------------------------------------------------
#
# Property 12 (variante QC) porte simultanément sur les deux fonctions QC
# (`calcul_impot_qc_formule` et `calcul_impot_qc_retenu`, design
# §Correctness Properties 12 ; §Components §2, §3). Elle vérifie le
# contenu minimal et la cohérence de la trace : source sur liste blanche
# TP-1015.F, année et juridiction attendues, section distinguant
# « formule » de « retenu », clés minimales de `entrees` /
# `parametres_utilises` / `sous_totaux`, et invariants d'arrondissement /
# résultat (`ModeArrondissement.ROUND_HALF_UP`, précision `2`, `resultat
# == montant`). Règle 01 : toutes les comparaisons de montants portent sur
# des `Decimal` (tolérance nulle).

#: Expression régulière du préfixe de source QC exigé par Property 12
#: (design §Correctness Properties 12) : ``"TP-1015.F "`` suivi d'un
#: millésime à quatre chiffres. Compilée une fois au niveau module.
_MOTIF_SOURCE_QC = re.compile(r"^TP-1015\.F \d{4}")


class TestTraceQc:
    """Property 12 (variante QC) — contenu minimal et cohérence de la trace.

    Design (§Correctness Properties 12 ; §Components §2, §3). Cette
    propriété couvre **les deux** fonctions QC dans un même test : la trace
    de `calcul_impot_qc_formule` (source TP-1015.F, section « formule »,
    `entrees` minimales `salaire_periode`/`nb_periodes_annuelles`,
    `sous_totaux` minimal `revenu_imposable_periode`) et celle de
    `calcul_impot_qc_retenu` (section « retenu », `parametres_utilises`
    minimal `exoneration_active`, `entrees` minimal `impot_qc_formule`,
    `sous_totaux` minimal `retenue_effective`). Les invariants communs
    (source sur liste blanche, `annee`, `juridiction`, arrondissement,
    `resultat == montant`) sont vérifiés pour les deux traces.
    """

    # Feature: impots-retenues-source, Property 12: Contenu minimal et cohérence de la trace (QC)
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
        `ParametresAnnee` valides, les traces de `calcul_impot_qc_formule`
        et `calcul_impot_qc_retenu` satisfont le contenu minimal et la
        cohérence exigés par Property 12 (design §Correctness
        Properties 12 ; §Components §2, §3) :

        Invariants communs aux deux traces :

        - `trace.source` matche `^TP-1015\\.F \\d{4}` (liste blanche
          TP-1015.F, préfixée d'un millésime à quatre chiffres) ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` ;
        - `trace.juridiction == Juridiction.QUEBEC` ;
        - `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`,
          `trace.precision_arrondissement == 2` ;
        - `trace.resultat` égal au montant retourné.

        Spécifique à la formule (design §Components §2) :

        - `trace.section` contient « formule » (et pas « retenu ») ;
        - `trace.entrees` contient au minimum `salaire_periode` et
          `nb_periodes_annuelles` ;
        - `trace.sous_totaux` contient au minimum
          `revenu_imposable_periode`.

        Spécifique à la retenue (design §Components §3) :

        - `trace.section` contient « retenu » ;
        - `trace.parametres_utilises` contient `exoneration_active` ;
        - `trace.entrees` contient `impot_qc_formule` ;
        - `trace.sous_totaux` contient `retenue_effective`.

        **Validates: Requirements 3.6, 9.1, 9.2, 9.3, 9.4, 9.5**
        """
        payroll_input, gains = entrees
        annee_attendue = payroll_input.pay_period.annee_fiscale

        # --- Trace de calcul_impot_qc_formule (design §Components §2) ---
        montant_formule, trace_formule = calcul_impot_qc_formule(
            payroll_input, gains, parametres_annee
        )

        assert _MOTIF_SOURCE_QC.match(trace_formule.source) is not None
        assert trace_formule.annee == annee_attendue
        assert trace_formule.juridiction == Juridiction.QUEBEC
        assert "formule" in trace_formule.section
        assert "retenu" not in trace_formule.section
        assert "salaire_periode" in trace_formule.entrees
        assert "nb_periodes_annuelles" in trace_formule.entrees
        assert "revenu_imposable_periode" in trace_formule.sous_totaux
        assert trace_formule.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
        assert trace_formule.precision_arrondissement == 2
        assert trace_formule.resultat == montant_formule

        # --- Trace de calcul_impot_qc_retenu (design §Components §3) ---
        montant_retenu, trace_retenu = calcul_impot_qc_retenu(
            payroll_input, gains, parametres_annee
        )

        assert _MOTIF_SOURCE_QC.match(trace_retenu.source) is not None
        assert trace_retenu.annee == annee_attendue
        assert trace_retenu.juridiction == Juridiction.QUEBEC
        assert "retenu" in trace_retenu.section
        assert "exoneration_active" in trace_retenu.parametres_utilises
        assert "impot_qc_formule" in trace_retenu.entrees
        assert "retenue_effective" in trace_retenu.sous_totaux
        assert trace_retenu.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
        assert trace_retenu.precision_arrondissement == 2
        assert trace_retenu.resultat == montant_retenu


# ---------------------------------------------------------------------------
# 2.5 — Propagation de MissingParameterError (Property 13, variante QC)
# ---------------------------------------------------------------------------
#
# Property 13 (variante QC) porte sur les deux fonctions QC
# (`calcul_impot_qc_formule` et, par délégation structurelle stricte,
# `calcul_impot_qc_retenu` lorsque l'exonération est inactive — design
# §Components §3, Req 3.3). Pour chacun des champs de la section
# `impot_quebec` consommés par la formule QC (design §Components §2 —
# `paliers[i].taux`, `paliers[i].constante_k`, `taux_credits_convertibles`,
# `deduction_pour_travailleur_annuelle`), marquer ce champ `"TO_FILL"`
# dans le `ParametresAnnee` (via `st_parametres_annee_impot_avec_to_fill`)
# DOIT faire lever `MissingParameterError` à l'appel, non interceptée ni
# masquée par une autre exception (design §Error Handling « Matrice des
# exceptions », Requirements 1.8, 10.5).
#
# Délégation (Req 3.3) : `calcul_impot_qc_retenu` n'invoque
# `calcul_impot_qc_formule` — et ne lit donc les paramètres de la section
# `impot_quebec` — que lorsque `exoneration_TP1015_3_effectif == False`.
# Sous exonération active, le court-circuit véritable ne touche jamais les
# paramètres et ne lèverait pas `MissingParameterError` (le montant de
# base est forcé à `Decimal("0.00")`). Les tests ci-dessous forcent donc
# `exoneration_TP1015_3_effectif = False` (`model_copy(update=...)` —
# règle 06, immuabilité) avant d'exercer la délégation sur
# `calcul_impot_qc_retenu`.
#
# Ordonnancement (règle 06 — tests avant code) : la stratégie
# `st_parametres_annee_impot_avec_to_fill` cible les propriétés typées
# `Palier.taux` / `.constante_k` et les attributs `*_brut` de la section
# `impot_quebec`, qui ne sont matérialisés qu'à partir de la tâche 7.2 ;
# `payroll_engine/impot_qc.py` n'existe qu'à partir de la tâche 9.1. La
# collecte pytest de ce fichier échoue donc actuellement avec
# `ModuleNotFoundError` sur `payroll_engine.impot_qc` (import au niveau
# module) — état rouge attendu et correct à ce stade.
#
# Règle 01 : aucune valeur monétaire `float` n'est manipulée ; la
# sentinelle `"TO_FILL"` reste une chaîne portée par la stratégie.


class TestMissingParameterImpotQc:
    """Property 13 (variante QC) — propagation de `MissingParameterError`
    sans interception.

    Design (§Correctness Properties 13 ; §Error Handling « Matrice des
    exceptions »). Pour chacun des champs de la section `impot_quebec`
    consommés par `calcul_impot_qc_formule` (et, par délégation stricte,
    par `calcul_impot_qc_retenu` lorsque l'exonération est inactive —
    Req 3.3) — `paliers[0].taux`, `paliers[0].constante_k`,
    `taux_credits_convertibles`, `deduction_pour_travailleur_annuelle` —
    marquer ce champ `"TO_FILL"` dans le `ParametresAnnee` (via
    `st_parametres_annee_impot_avec_to_fill`) DOIT faire lever
    `MissingParameterError` à l'appel, non interceptée ni masquée par une
    autre exception (Requirements 1.8, 10.5).
    """

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt QC)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_quebec.paliers[0].taux"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_palier_taux(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `impot_quebec.paliers[0].taux` porte la
        sentinelle `"TO_FILL"`, `calcul_impot_qc_formule` lève
        `MissingParameterError` non interceptée. Sous exonération inactive
        (`exoneration_TP1015_3_effectif = False`),
        `calcul_impot_qc_retenu` propage la même exception par délégation
        structurelle (Req 3.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TP1015_3_effectif": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt QC)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_quebec.paliers[0].constante_k"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_palier_constante_k(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `impot_quebec.paliers[0].constante_k` porte
        la sentinelle `"TO_FILL"`, `calcul_impot_qc_formule` lève
        `MissingParameterError` non interceptée, et `calcul_impot_qc_retenu`
        la propage par délégation lorsque l'exonération est inactive
        (Req 3.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TP1015_3_effectif": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt QC)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_quebec.taux_credits_convertibles"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_taux_credits_convertibles(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont `impot_quebec.taux_credits_convertibles`
        porte la sentinelle `"TO_FILL"`, `calcul_impot_qc_formule` lève
        `MissingParameterError` non interceptée, et `calcul_impot_qc_retenu`
        la propage par délégation lorsque l'exonération est inactive
        (Req 3.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TP1015_3_effectif": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_retenu(payroll_input_non_exo, gains, parametres_annee)

    # Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt QC)
    @pytest.mark.property
    @given(
        entrees=_st_entrees_completes(),
        parametres_annee=st_parametres_annee_impot_avec_to_fill(
            "impot_quebec.deduction_pour_travailleur_annuelle"
        ),
    )
    @settings_large_input
    def test_property_13_to_fill_deduction_pour_travailleur_annuelle(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et
        `ParametresAnnee` dont
        `impot_quebec.deduction_pour_travailleur_annuelle` porte la
        sentinelle `"TO_FILL"`, `calcul_impot_qc_formule` lève
        `MissingParameterError` non interceptée, et `calcul_impot_qc_retenu`
        la propage par délégation lorsque l'exonération est inactive
        (Req 3.3).

        **Validates: Requirements 1.8, 10.5**
        """
        payroll_input, gains = entrees
        payroll_input_non_exo = payroll_input.model_copy(
            update={"exoneration_TP1015_3_effectif": False}
        )

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_formule(payroll_input_non_exo, gains, parametres_annee)

        with pytest.raises(MissingParameterError):
            calcul_impot_qc_retenu(payroll_input_non_exo, gains, parametres_annee)
