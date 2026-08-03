"""Property tests et tests d'exemple pour `payroll_engine/charges_patronales.py`.

Spec de référence : ``charges-patronales`` — tâche 2.1 (squelette du fichier
et tests transversaux).
Design de référence : ``design.md`` §Testing Strategy, §Correctness Properties
1 à 13 et §Components §1, §2, §3, §4, §5, §6.

Ce fichier porte l'ensemble des property tests et tests d'exemple des trois
fonctions de calcul du module ``payroll_engine/charges_patronales.py``
(``calcul_fss``, ``calcul_cnesst``, ``calcul_cnt``) ainsi que de la fonction
d'assemblage ``assembler_cotisations_employeur``. La tâche 2.1 pose le
**squelette** : le module docstring, les imports, la stratégie module-scoped
des paramètres annuels réels 2026 (Québec) et les tests **transversaux**
(classe ``TestSignaturePureteRobustesse``) qui s'appliquent identiquement aux
trois fonctions de calcul. Les tâches suivantes ajouteront :

- ``TestFormuleChargesPatronales`` — Property 2, 3, 4 (tâche 2.2) ;
- ``TestMonotonieEtIndependance`` — Property 5, 7, 8 (tâche 2.3) ;
- ``TestTraceChargesPatronales`` — Property 9 (tâche 2.4) ;
- ``TestMissingParameterChargesPatronales`` — Property 13 (tâche 2.5) ;
- ``TestAssemblageCotisationsEmployeur`` — Property 10, 11, 12 et les variantes
  d'assemblage des Properties 1, 6, 13 (tâche 3.1).

Les **13 propriétés** couvertes par ce fichier de test (design.md
§Correctness Properties) :

1. **Property 1 — Déterminisme (pureté)** : deux appels d'une même fonction
   (calcul ou assemblage) avec les mêmes arguments produisent deux résultats
   égaux au sens ``==``. *(cette tâche, pour les trois fonctions de calcul)*
2. **Property 2 — Formule proportionnelle et arrondissement** :
   ``montant == arrondir(taux × gains.brut_total)``.
3. **Property 3 — Non-négativité** : ``montant >= Decimal("0.00")``.
4. **Property 4 — Zéro lorsque le salaire assujetti est nul**.
5. **Property 5 — Monotonie croissante** par rapport au ``brut_total``.
6. **Property 6 — Forme ``Decimal`` du résultat et de la trace** : montant et
   valeurs de trace ``Decimal`` finies, montant arrondi à 2 décimales
   ``ROUND_HALF_UP``. *(cette tâche, pour les trois fonctions de calcul)*
7. **Property 7 — Indépendance** vis-à-vis des champs non pertinents de
   ``payroll_input``.
8. **Property 8 — Insensibilité** aux paramètres non consommés et absence de
   plafond.
9. **Property 9 — Conformité et contenu de la trace**.
10. **Property 10 — Assemblage par invocation** sans recalcul.
11. **Property 11 — Report du drapeau CNESST** sans effet sur le total.
12. **Property 12 — Identité d'agrégation** (somme des six montants).
13. **Property 13 — Propagation de ``MissingParameterError``** sans
    interception.

Discipline règle 06 (TDD — tests avant code) :
``payroll_engine/charges_patronales.py`` n'existe **pas encore** à ce stade.
Contrairement à ``test_rrq.py`` (spec ``cotisations-sociales-qc``) qui importe
son module cible au niveau module, ce fichier **importe localement** les
fonctions sous test (via ``importlib.import_module`` dans un helper appelé au
sein de chaque test) afin que la **collecte** pytest de ce fichier réussisse
même tant que le module cible est absent. À l'exécution, chaque test échoue
alors avec ``ModuleNotFoundError`` sur ``payroll_engine.charges_patronales`` —
c'est le comportement **attendu et correct** (état rouge intentionnel) tant
que la tâche 11.1 (implémentation) n'a pas été réalisée (checkpoint de la
tâche 7 du plan).

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison.
Règle 04 : aucune donnée nominative réelle — corpus et générateurs anonymisés
(``EMPnnn``).
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from types import ModuleType

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.enums import Juridiction, ModeArrondissement  # noqa: F401  (contrats consommés)
from models.exceptions import MissingParameterError  # noqa: F401  (contrats consommés)
from models.payroll_input import PayrollInput
from models.payroll_result import (  # noqa: F401  (contrats consommés)
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
)
from models.trace import CalculationTrace
from tests.strategies import (
    st_brut_total_avec_zero_et_grands,
    st_parametres_annee_2026_qc,
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_avec_to_fill,
    st_parametres_annee_variantes_non_consommees,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_rrq.py).
# Le nombre d'exemples est piloté par le profil Hypothesis actif
# (voir ``tests/conftest.py`` : dev=15 par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

#: Nom qualifié du module sous test (règle 06 — importé localement pour ne pas
#: faire échouer la collecte tant que la tâche 11.1 n'a pas créé le module).
_NOM_MODULE_CIBLE = "payroll_engine.charges_patronales"

#: Les trois fonctions de calcul partageant la même signature et le même patron
#: proportionnel (design §Components §1). Les tests transversaux (Property 1,
#: Property 6) sont paramétrés sur ces trois noms plutôt que dupliqués.
_NOMS_FONCTIONS_CALCUL: tuple[str, ...] = ("calcul_fss", "calcul_cnesst", "calcul_cnt")

#: Ordre exact des paramètres imposé par le design §Components §1 pour les
#: trois fonctions de calcul et pour l'assemblage.
_PARAMETRES_ATTENDUS: tuple[str, ...] = ("payroll_input", "gains", "parametres_annee")


# ---------------------------------------------------------------------------
# Helpers internes — import local du module cible, génération d'entrées,
# vérification de la forme Decimal.
# ---------------------------------------------------------------------------


def _importer_module_charges_patronales() -> ModuleType:
    """Importe ``payroll_engine.charges_patronales`` au moment de l'appel.

    Règle 06 (TDD — tests avant code) : le module cible n'existe pas encore.
    En différant l'import à l'intérieur des tests (plutôt qu'au niveau module),
    la **collecte** pytest de ce fichier reste possible ; seule l'**exécution**
    de chaque test lève ``ModuleNotFoundError`` tant que la tâche 11.1 n'a pas
    créé le module — état rouge attendu et correct.
    """
    return importlib.import_module(_NOM_MODULE_CIBLE)


def _construire_gains_decomposes(brut_total: Decimal) -> GainsDecomposes:
    """``GainsDecomposes`` valide, minimal, pour un ``brut_total`` donné.

    Seul ``brut_total`` importe pour les trois fonctions de charges
    patronales (Req 1.5 — lecture exclusive de ``gains.brut_total`` comme
    Salaire_Assujetti) ; les autres composantes du brut sont mises à zéro
    pour ne pas introduire de bruit hors du périmètre de cette spec.
    ``multiplicateur_heures_supp`` et ``seuil_heures_supp_hebdo`` sont des
    valeurs de contexte portées par contrat (``gt=0``) mais non consommées
    par le Moteur_Charges_Patronales — les valeurs ``1.5`` / ``40`` ne sont
    pas des paramètres fiscaux au sens de la règle 05, seulement des valeurs
    de forme requises par ``GainsDecomposes``.
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
def _st_entrees(draw: st.DrawFn) -> tuple[PayrollInput, GainsDecomposes]:
    """``(PayrollInput, GainsDecomposes)`` couvrant la plage de ``brut_total``.

    Combine ``st_payroll_input()`` (``PayrollInput`` cohérent par
    construction — Québec, aux deux semaines) avec
    ``st_brut_total_avec_zero_et_grands()`` (``Decimal`` ∈ [0, 200000],
    biaisé vers ``0.00`` — Property 4 — et vers de grandes valeurs
    > ``103 000 $`` — Property 8). Le ``brut_total`` tiré est enveloppé dans
    un ``GainsDecomposes`` valide via ``_construire_gains_decomposes``.
    """
    payroll_input = draw(st_payroll_input())
    brut_total = draw(st_brut_total_avec_zero_et_grands())
    gains = _construire_gains_decomposes(brut_total)
    return payroll_input, gains


def _verifier_forme_decimal(montant: Decimal, trace: CalculationTrace) -> None:
    """Vérifie Property 6 (design §Correctness Properties 6) pour un couple
    ``(montant, trace)`` retourné par une des trois fonctions de calcul.

    - Le montant retourné, ``trace.resultat`` et chaque valeur de
      ``trace.parametres_utilises`` / ``entrees`` / ``sous_totaux`` sont des
      ``Decimal`` finis (``isinstance`` + ``is_finite()``).
    - Le montant retourné et ``trace.resultat`` sont en outre égaux à leur
      propre arrondi à deux décimales selon ``ROUND_HALF_UP``.
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
# 2.1 — Signature, pureté et forme Decimal (Property 1, Property 6)
# ---------------------------------------------------------------------------


class TestSignaturePureteRobustesse:
    """Property 1, 6 — déterminisme et forme `Decimal`, plus les tests
    d'exemple de signatures exactes et d'import sans effet de bord.

    Design (§Correctness Properties 1, 6 ; §Components §1 « Signatures
    exactes »). Ces deux propriétés s'appliquent identiquement à
    `calcul_fss`, `calcul_cnesst` et `calcul_cnt` : elles sont donc
    paramétrées sur les trois noms de fonction (`_NOMS_FONCTIONS_CALCUL`)
    plutôt que dupliquées.
    """

    # Feature: charges-patronales, Property 1: Déterminisme (pureté)
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_1_deux_appels_identiques_produisent_des_tuples_egaux(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, et pour chacune des trois fonctions de calcul `f`,
        `f(pi, g, p) == f(pi, g, p)` : deux appels avec les mêmes arguments
        produisent deux tuples `(montant, trace)` égaux au sens `==` sur les
        deux composantes (`Decimal` et `CalculationTrace`).

        **Validates: Requirements 1.3, 10.4**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)

            resultat_1 = fonction(payroll_input, gains, parametres_annee)
            resultat_2 = fonction(payroll_input, gains, parametres_annee)

            assert resultat_1 == resultat_2, (
                f"{nom_fonction} n'est pas déterministe : {resultat_1!r} != "
                f"{resultat_2!r}"
            )
            assert resultat_1[0] == resultat_2[0]
            assert resultat_1[1] == resultat_2[1]

    # Feature: charges-patronales, Property 6: Forme Decimal du résultat et de la trace
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_6_forme_decimal_du_resultat_et_de_la_trace(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, et pour chacune des trois fonctions de calcul, le montant
        retourné et chaque valeur de `trace.parametres_utilises` / `entrees`
        / `sous_totaux` / `resultat` sont des `Decimal` finis ; le montant
        retourné (et `trace.resultat`) sont en outre égaux à leur arrondi à
        deux décimales `ROUND_HALF_UP`.

        **Validates: Requirements 2.6, 3.6, 4.6, 8.3, 10.5**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            montant, trace = fonction(payroll_input, gains, parametres_annee)
            _verifier_forme_decimal(montant, trace)

    def test_exemple_signatures_exactes_des_trois_fonctions_et_de_l_assemblage(
        self,
    ) -> None:
        """Test d'exemple — signatures exactes (Req 1.1, 1.2).

        Les trois fonctions de calcul (`calcul_fss`, `calcul_cnesst`,
        `calcul_cnt`) et la fonction d'assemblage
        (`assembler_cotisations_employeur`) exposent chacune, dans l'ordre,
        les paramètres `(payroll_input, gains, parametres_annee)` sans valeur
        par défaut (design §Components §1). Vérifié par introspection
        `inspect.signature`.
        """
        module = _importer_module_charges_patronales()

        noms_a_verifier = (*_NOMS_FONCTIONS_CALCUL, "assembler_cotisations_employeur")
        for nom_fonction in noms_a_verifier:
            assert hasattr(module, nom_fonction), (
                f"Le module cible doit exposer `{nom_fonction}` (Req 1.1/1.2)."
            )
            fonction = getattr(module, nom_fonction)
            signature = inspect.signature(fonction)

            noms_parametres = tuple(signature.parameters)
            assert noms_parametres == _PARAMETRES_ATTENDUS, (
                f"`{nom_fonction}` doit avoir les paramètres "
                f"{_PARAMETRES_ATTENDUS} dans cet ordre, obtenu {noms_parametres}."
            )
            for parametre in signature.parameters.values():
                assert parametre.default is inspect.Parameter.empty, (
                    f"`{nom_fonction}` ne doit imposer aucune valeur par défaut "
                    f"(paramètre `{parametre.name}`)."
                )
                assert parametre.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.POSITIONAL_ONLY,
                ), (
                    f"`{nom_fonction}` doit exposer des paramètres positionnels "
                    f"(paramètre `{parametre.name}`)."
                )

    def test_exemple_import_charges_patronales_sans_effet_de_bord(self, capsys) -> None:
        """Test d'exemple — l'import du module ne produit aucun effet de bord
        (Req 1.7) : pas d'ouverture de fichier, pas d'appel réseau, pas
        d'écriture sur `stdout` / `stderr` au moment de l'import.

        Design (§Architecture « Contrainte de pureté »). Le module est retiré
        de `sys.modules` avant l'import (s'il y était déjà chargé) afin de
        forcer une exécution fraîche de son corps — c'est à ce moment-là
        qu'un éventuel effet de bord au niveau module se manifesterait. Les
        quatre symboles publics attendus doivent être exposés après l'import.
        """
        sys.modules.pop(_NOM_MODULE_CIBLE, None)

        module = importlib.import_module(_NOM_MODULE_CIBLE)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert _NOM_MODULE_CIBLE in sys.modules
        assert hasattr(module, "calcul_fss")
        assert hasattr(module, "calcul_cnesst")
        assert hasattr(module, "calcul_cnt")
        assert hasattr(module, "assembler_cotisations_employeur")


# ---------------------------------------------------------------------------
# 2.2 — Formule proportionnelle, non-négativité et salaire nul
#       (Property 2, Property 3, Property 4)
# ---------------------------------------------------------------------------

#: Association nom de fonction de calcul -> accès au taux propre à cette
#: fonction dans un ``ParametresAnnee`` (design §Components §2, §3, §4) :
#:
#: - ``calcul_fss``    -> ``parametres_annee.fss.taux_camp_lilyso_2026`` ;
#: - ``calcul_cnesst`` -> ``parametres_annee.cnesst.taux_total`` ;
#: - ``calcul_cnt``    -> ``parametres_annee.cnt.taux``.
#:
#: Chaque taux est lu **exclusivement** depuis ``parametres_annee`` (règle 05 —
#: aucun taux fiscal codé en dur dans les tests) ; il permet de recalculer le
#: montant théorique ``taux × gains.brut_total`` attendu par la Property 2.
_ACCES_TAUX_PAR_FONCTION = {
    "calcul_fss": lambda parametres_annee: parametres_annee.fss.taux_camp_lilyso_2026,
    "calcul_cnesst": lambda parametres_annee: parametres_annee.cnesst.taux_total,
    "calcul_cnt": lambda parametres_annee: parametres_annee.cnt.taux,
}

#: Un demi-cent — borne de l'écart entre le montant retourné (arrondi à deux
#: décimales ``ROUND_HALF_UP``) et le montant théorique ``taux × brut_total``
#: (design §Correctness Properties 2).
_DEMI_CENT: Decimal = Decimal("0.005")


class TestFormuleChargesPatronales:
    """Property 2, 3, 4 — formule proportionnelle et arrondissement,
    non-négativité, et zéro lorsque le salaire assujetti est nul.

    Design (§Correctness Properties 2, 3, 4 ; §Components §2, §3, §4, §6).
    Les trois propriétés s'appliquent identiquement à `calcul_fss`,
    `calcul_cnesst` et `calcul_cnt` (patron proportionnel simple
    `montant = arrondir(taux × brut_total)`, sans exemption, sans plafond) :
    elles sont donc paramétrées sur les trois noms de fonction
    (`_NOMS_FONCTIONS_CALCUL`) plutôt que dupliquées, le taux propre à chaque
    fonction étant lu via `_ACCES_TAUX_PAR_FONCTION` (règle 05).
    """

    # Feature: charges-patronales, Property 2: Formule proportionnelle et arrondissement
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_2_montant_egal_arrondi_du_taux_fois_le_brut(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, et pour chacune des trois fonctions de calcul `f` de taux
        `taux`, `f(pi, g, p)[0] == arrondir(taux × g.brut_total)` où
        `arrondir == quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`.

        En conséquence, l'écart entre le montant retourné et le montant
        théorique `taux × brut_total` est borné par un demi-cent, et aucune
        exemption n'est soustraite (l'égalité stricte à `arrondir(taux ×
        brut_total)` échouerait si une exemption était retranchée).

        **Validates: Requirements 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 8.1, 8.2, 10.3**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            taux = _ACCES_TAUX_PAR_FONCTION[nom_fonction](parametres_annee)

            montant, _trace = fonction(payroll_input, gains, parametres_annee)

            montant_theorique = taux * gains.brut_total
            montant_attendu = montant_theorique.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            assert montant == montant_attendu, (
                f"{nom_fonction} : montant {montant!r} != "
                f"arrondir({taux!r} × {gains.brut_total!r}) = {montant_attendu!r}"
            )
            # L'écart au montant théorique non arrondi est borné par un demi-cent.
            assert abs(montant - montant_theorique) <= _DEMI_CENT, (
                f"{nom_fonction} : écart |{montant!r} - {montant_theorique!r}| "
                f"dépasse un demi-cent ({_DEMI_CENT!r})"
            )

    # Feature: charges-patronales, Property 3: Non-négativité
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_3_montant_jamais_negatif(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `brut_total ≥ 0`, chacune des trois fonctions de calcul
        retourne un montant `≥ Decimal("0.00")` (non-négativité).

        **Validates: Requirements 2.4, 3.4, 4.4, 10.1**
        """
        payroll_input, gains = entrees
        assert gains.brut_total >= Decimal("0.00")  # invariant de la stratégie
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            montant, _trace = fonction(payroll_input, gains, parametres_annee)

            assert montant >= Decimal("0.00"), (
                f"{nom_fonction} a retourné un montant strictement négatif : "
                f"{montant!r}"
            )

    # Feature: charges-patronales, Property 4: Zéro lorsque le salaire assujetti est nul
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_4_salaire_nul_donne_zero_sans_exception(
        self,
        payroll_input: PayrollInput,
        parametres_annee,
    ) -> None:
        """*Pour* `brut_total == Decimal("0.00")`, chacune des trois fonctions
        de calcul retourne `Decimal("0.00")` sans lever d'exception.

        Le `GainsDecomposes` est construit avec un `brut_total` nul (via
        `_construire_gains_decomposes`), indépendamment du `PayrollInput`
        généré : la propriété ne dépend d'aucun autre champ que du salaire
        assujetti nul (Req 1.5).

        **Validates: Requirements 2.5, 3.5, 4.5**
        """
        gains_nuls = _construire_gains_decomposes(Decimal("0.00"))
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            montant, _trace = fonction(payroll_input, gains_nuls, parametres_annee)

            assert montant == Decimal("0.00"), (
                f"{nom_fonction} avec brut_total nul doit retourner "
                f"Decimal(\"0.00\"), obtenu {montant!r}"
            )

# ---------------------------------------------------------------------------
# 2.3 — Monotonie, indépendance vis-à-vis de `payroll_input` et insensibilité
#       aux paramètres non consommés (Property 5, Property 7, Property 8)
# ---------------------------------------------------------------------------

#: Seuil de la ``base_admissible`` CNT / plafond annuel CNESST documenté
#: (``103 000 $``, design §Overview « valeurs officielles »). Au-delà de ce
#: seuil, aucune des trois fonctions ne plafonne : le montant reste égal à
#: ``arrondir(taux × brut_total)`` (Property 8, absence de plafond). Lu ici
#: comme repère de test uniquement (la valeur fiscale reste portée par
#: ``parametres_annee.cnt.base_admissible`` — règle 05).
_SEUIL_SANS_PLAFOND: Decimal = Decimal("103000.00")


@st.composite
def _st_deux_payroll_inputs_meme_annee(
    draw: st.DrawFn,
) -> tuple[PayrollInput, PayrollInput]:
    """Deux ``PayrollInput`` identiques sur l'année fiscale, différant ailleurs.

    Property 7 (design §Correctness Properties 7) exige deux ``PayrollInput``
    ``pi1``, ``pi2`` **identiques sur ``pay_period.annee_fiscale``** mais
    différant sur des champs **non liés au salaire assujetti**. La stratégie
    tire un premier ``PayrollInput`` cohérent (``st_payroll_input()``), puis
    construit une variante via ``model_copy(update=...)`` qui conserve
    ``employee`` et ``pay_period`` (donc la même ``annee_fiscale``) et le même
    ``(employe_id, annee_civile)`` sur ``cumuls_debut`` — préservant les
    invariants structurels de ``PayrollInput`` — tout en variant :

    - les onze catégories monétaires de ``cumuls_debut`` (cumuls d'ouverture) ;
    - les montants et drapeaux TP-1015.3 (``montant_total_TP1015_3_effectif``,
      ``exoneration_TP1015_3_effectif``, ``retenue_additionnelle_QC_effective``) ;
    - les montants et drapeaux TD1 (``montant_total_TD1_effectif``,
      ``exoneration_TD1_effective``, ``retenue_additionnelle_federale_effective``).

    Aucun de ces champs n'alimente le Salaire_Assujetti (lu exclusivement
    depuis ``gains.brut_total`` — Req 1.5) : les trois fonctions de charges
    patronales doivent donc produire le même montant pour ``pi1`` et ``pi2``.

    Immuabilité (règle 06) : ``pi1`` n'est jamais muté ; ``pi2`` est une
    nouvelle instance obtenue par ``model_copy``. Règle 01 : toutes les
    valeurs tirées sont des ``Decimal`` (jamais un ``float``).
    """
    pi1 = draw(st_payroll_input())

    def _montant_test() -> Decimal:
        return draw(
            st.decimals(
                min_value=Decimal("0.00"),
                max_value=Decimal("100000.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        )

    # cumuls_debut variant : mêmes (employe_id, annee_civile), catégories
    # monétaires distinctes (préserve les invariants croisés de PayrollInput).
    cumuls_variante = pi1.cumuls_debut.model_copy(
        update={
            "brut": _montant_test(),
            "vacances": _montant_test(),
            "rrq_employe": _montant_test(),
            "rrq_employeur": _montant_test(),
            "rqap_employe": _montant_test(),
            "rqap_employeur": _montant_test(),
            "ae_employe": _montant_test(),
            "ae_employeur": _montant_test(),
            "impot_qc_retenu": _montant_test(),
            "impot_federal_retenu": _montant_test(),
            "net": _montant_test(),
        }
    )

    pi2 = pi1.model_copy(
        update={
            "montant_total_TP1015_3_effectif": _montant_test(),
            "exoneration_TP1015_3_effectif": draw(st.booleans()),
            "retenue_additionnelle_QC_effective": draw(
                st.decimals(
                    min_value=Decimal("0.00"),
                    max_value=Decimal("2000.00"),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                )
            ),
            "montant_total_TD1_effectif": _montant_test(),
            "exoneration_TD1_effective": draw(st.booleans()),
            "retenue_additionnelle_federale_effective": draw(
                st.decimals(
                    min_value=Decimal("0.00"),
                    max_value=Decimal("2000.00"),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                )
            ),
            "cumuls_debut": cumuls_variante,
        }
    )
    return pi1, pi2


class TestMonotonieEtIndependance:
    """Property 5, 7, 8 — monotonie croissante par rapport au salaire
    assujetti, indépendance vis-à-vis des champs non pertinents de
    `payroll_input`, et insensibilité aux paramètres non consommés (avec
    absence de plafond).

    Design (§Correctness Properties 5, 7, 8 ; §Components §2, §3, §4 ;
    §Error Handling « Hors périmètre »). Les trois propriétés s'appliquent
    identiquement à `calcul_fss`, `calcul_cnesst` et `calcul_cnt` (patron
    proportionnel simple `montant = arrondir(taux × brut_total)`, sans
    exemption, sans plafond, sans lecture de champ de `payroll_input` autre
    que `pay_period.annee_fiscale` pour la trace) : elles sont donc
    paramétrées sur les trois noms de fonction (`_NOMS_FONCTIONS_CALCUL`)
    plutôt que dupliquées.
    """

    # Feature: charges-patronales, Property 5: Monotonie croissante par rapport au salaire assujetti
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        brut_a=st_brut_total_avec_zero_et_grands(),
        brut_b=st_brut_total_avec_zero_et_grands(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_5_monotonie_croissante_par_rapport_au_brut(
        self,
        payroll_input: PayrollInput,
        brut_a: Decimal,
        brut_b: Decimal,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `ParametresAnnee` valides et deux
        `GainsDecomposes` `g1`, `g2` tels que `g1.brut_total ≤ g2.brut_total`,
        chacune des trois fonctions de calcul (à taux fixé) produit
        `montant(g1) ≤ montant(g2)`.

        Les deux `brut_total` tirés sont ordonnés (`brut_bas ≤ brut_haut`)
        puis enveloppés dans deux `GainsDecomposes` valides via
        `_construire_gains_decomposes` ; seul le `brut_total` diffère entre
        `g1` et `g2`. Le taux étant lu depuis le même `parametres_annee`
        (taux fixé, règle 05), le montant est une fonction croissante du
        `brut_total`.

        **Validates: Requirements 10.2**
        """
        brut_bas, brut_haut = sorted((brut_a, brut_b))
        assert brut_bas <= brut_haut  # invariant du tri

        g1 = _construire_gains_decomposes(brut_bas)
        g2 = _construire_gains_decomposes(brut_haut)
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            montant_bas, _t1 = fonction(payroll_input, g1, parametres_annee)
            montant_haut, _t2 = fonction(payroll_input, g2, parametres_annee)

            assert montant_bas <= montant_haut, (
                f"{nom_fonction} n'est pas monotone croissante : "
                f"montant({brut_bas!r})={montant_bas!r} > "
                f"montant({brut_haut!r})={montant_haut!r}"
            )

    # Feature: charges-patronales, Property 7: Indépendance vis-à-vis des champs non pertinents de `payroll_input`
    @pytest.mark.property
    @given(
        payroll_inputs=_st_deux_payroll_inputs_meme_annee(),
        brut_total=st_brut_total_avec_zero_et_grands(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_7_independance_vis_a_vis_des_champs_non_pertinents(
        self,
        payroll_inputs: tuple[PayrollInput, PayrollInput],
        brut_total: Decimal,
        parametres_annee,
    ) -> None:
        """*Pour tout* `GainsDecomposes` et `ParametresAnnee` valides, et deux
        `PayrollInput` `pi1`, `pi2` identiques sur `pay_period.annee_fiscale`
        mais différant sur des champs non liés au salaire assujetti
        (`cumuls_debut`, montants TP-1015.3/TD1), chacune des trois fonctions
        de calcul produit le même montant : le Salaire_Assujetti est lu
        exclusivement depuis `gains.brut_total` (Req 1.5).

        `pi1` et `pi2` partagent le même `pay_period` (donc la même
        `annee_fiscale`) et le même `GainsDecomposes` (même `brut_total`) ;
        seuls les champs non pertinents diffèrent. Les montants retournés
        doivent être égaux au sens `==`.

        **Validates: Requirements 1.5**
        """
        pi1, pi2 = payroll_inputs
        # Précondition de la propriété : même année fiscale.
        assert (
            pi1.pay_period.annee_fiscale == pi2.pay_period.annee_fiscale
        )
        gains = _construire_gains_decomposes(brut_total)
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            montant_1, _t1 = fonction(pi1, gains, parametres_annee)
            montant_2, _t2 = fonction(pi2, gains, parametres_annee)

            assert montant_1 == montant_2, (
                f"{nom_fonction} dépend d'un champ non pertinent de "
                f"payroll_input : montant(pi1)={montant_1!r} != "
                f"montant(pi2)={montant_2!r} (même brut_total {brut_total!r})"
            )

    # Feature: charges-patronales, Property 8: Insensibilité aux paramètres non consommés et absence de plafond
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_base=st_parametres_annee_2026_qc(),
        parametres_variante=st_parametres_annee_variantes_non_consommees(),
    )
    @settings_large_input
    def test_property_8_insensibilite_aux_parametres_non_consommes_et_absence_de_plafond(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_base,
        parametres_variante,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` (y compris
        `brut_total` très élevé, au-delà de `103 000 $`) et deux
        `ParametresAnnee` différant **uniquement** sur des champs non
        consommés par le calcul de période, les montants sont identiques :

        - **FSS** — indépendant de `fss.masse_salariale_utilisee_webras_2026`
          et de `fss.table_taux_par_masse_salariale` (jamais consultée) ;
        - **CNESST** — indépendant de `cnesst.en_attente_classification` et
          des sous-taux `cnesst.taux_unite` / `cnesst.taux_cni` ;
        - **CNT** — indépendant de `cnt.base_admissible` (jamais appliquée
          comme plafond).

        De plus, à `brut_total` élevé (> `103 000 $`), chaque montant reste
        égal à `arrondir(taux × brut_total)` sans aucun plafonnement.

        `parametres_variante` (via `st_parametres_annee_variantes_non_consommees()`)
        ne diffère de `parametres_base` (`st_parametres_annee_2026_qc()`) que
        sur les champs non consommés ; les taux consommés
        (`fss.taux_camp_lilyso_2026`, `cnesst.taux_total`, `cnt.taux`) sont
        identiques. Le montant calculé avec la variante doit donc égaler
        celui calculé avec les paramètres de base, lui-même égal à
        `arrondir(taux × brut_total)`.

        **Validates: Requirements 2.7, 3.7, 3.8, 4.7, 7.2**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        for nom_fonction in _NOMS_FONCTIONS_CALCUL:
            fonction = getattr(module, nom_fonction)
            # Le taux consommé est identique entre base et variante (règle 05).
            taux = _ACCES_TAUX_PAR_FONCTION[nom_fonction](parametres_base)

            montant_base, _tb = fonction(payroll_input, gains, parametres_base)
            montant_variante, _tv = fonction(
                payroll_input, gains, parametres_variante
            )

            # Insensibilité : varier les champs non consommés ne change rien.
            assert montant_base == montant_variante, (
                f"{nom_fonction} dépend d'un paramètre non consommé : "
                f"montant(base)={montant_base!r} != "
                f"montant(variante)={montant_variante!r}"
            )

            # Absence de plafond : le montant reste arrondir(taux × brut_total)
            # même au-delà de la base admissible de 103 000 $.
            montant_attendu = (taux * gains.brut_total).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            assert montant_base == montant_attendu, (
                f"{nom_fonction} : montant {montant_base!r} != "
                f"arrondir({taux!r} × {gains.brut_total!r}) = "
                f"{montant_attendu!r} (plafonnement inattendu ?)"
            )
            if gains.brut_total > _SEUIL_SANS_PLAFOND:
                # Vérification explicite de l'absence de plafond au-delà du
                # seuil documenté (103 000 $) : le montant continue de croître.
                assert montant_base == montant_attendu, (
                    f"{nom_fonction} : plafonnement détecté au-delà de "
                    f"{_SEUIL_SANS_PLAFOND!r} pour brut_total "
                    f"{gains.brut_total!r}"
                )

# ---------------------------------------------------------------------------
# 2.4 — Conformité et contenu de la trace (Property 9)
# ---------------------------------------------------------------------------

#: Motif exact de la source FSS (design §Components §2) : le millésime est un
#: entier à quatre chiffres injecté depuis ``pay_period.annee_fiscale``. La
#: comparaison est faite avec ``re.fullmatch`` pour interdire tout préfixe ou
#: suffixe parasite. Le tiret cadratin « — » est le même caractère U+2014 que
#: celui produit par la fonction (design §Application des règles steering).
_MOTIF_SOURCE_FSS: re.Pattern[str] = re.compile(r"^TP-1015\.F \d{4}, section 5 — FSS$")

#: Fragment de domaine officiel attendu dans la source CNESST (design
#: §Components §3, « Note sur la source CNESST ») : une URL concrète sur
#: ``www.cnesst.gouv.qc.ca``. La liste blanche de ``CalculationTrace`` valide
#: déjà la forme complète de l'URL ; la Property 9 vérifie ici uniquement que
#: le domaine officiel figure dans la source.
_DOMAINE_CNESST: str = "www.cnesst.gouv.qc.ca"

#: Unité CNESST attendue dans le champ texte ``section`` (design §Components
#: §3, Req 5.3). Le contrat ``parametres_utilises`` étant typé
#: ``dict[str, Decimal]``, l'unité (chaîne) est exposée dans ``section``.
_UNITE_CNESST: str = "57020"


class TestTraceChargesPatronales:
    """Property 9 — conformité et contenu de la trace des trois fonctions de
    calcul.

    Design (§Correctness Properties 9 ; §Components §2, §3, §4). La partie
    **commune** de la propriété (trace `CalculationTrace` valide, cohérence
    `trace.resultat == montant`, `annee`, `mode_arrondissement`,
    `precision_arrondissement`, `juridiction`) est identique aux trois
    fonctions et vérifiée par le helper `_verifier_trace_commune`. La partie
    **spécifique** (motif de `source`, contenu de `section`,
    `parametres_utilises`, `entrees`) diffère d'une fonction à l'autre (les
    trois traces ne portent pas les mêmes clés ni les mêmes sources
    officielles) : elle est donc testée par trois méthodes distinctes
    (`calcul_fss`, `calcul_cnesst`, `calcul_cnt`).

    Règle 05 : les taux et la `base_admissible` attendus dans la trace sont
    lus depuis `parametres_annee` (jamais codés en dur dans les assertions).
    Règle 01 : toutes les valeurs comparées sont des `Decimal`.
    """

    @staticmethod
    def _verifier_trace_commune(
        trace: CalculationTrace,
        montant: Decimal,
        payroll_input: PayrollInput,
    ) -> None:
        """Vérifie la partie commune de Property 9 (design §Correctness
        Properties 9) pour un couple `(montant, trace)` retourné par l'une des
        trois fonctions de calcul.

        - `trace` est bien une `CalculationTrace` (valide par construction
          Pydantic — sinon la fonction aurait levé `ValidationError`) ;
        - `trace.resultat == montant` (cohérence trace ↔ montant, Req 5.5) ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` (Req 5.1) ;
        - `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`
          et `trace.precision_arrondissement == 2` (Req 5.5, 8.4) ;
        - `trace.juridiction == Juridiction.QUEBEC` (Req 5.1).
        """
        assert isinstance(trace, CalculationTrace), (
            f"La trace retournée n'est pas une CalculationTrace : {trace!r}"
        )
        assert trace.resultat == montant, (
            f"trace.resultat {trace.resultat!r} != montant retourné {montant!r}"
        )
        assert trace.annee == payroll_input.pay_period.annee_fiscale, (
            f"trace.annee {trace.annee!r} != "
            f"pay_period.annee_fiscale {payroll_input.pay_period.annee_fiscale!r}"
        )
        assert trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP, (
            f"trace.mode_arrondissement {trace.mode_arrondissement!r} != "
            f"ROUND_HALF_UP"
        )
        assert trace.precision_arrondissement == 2, (
            f"trace.precision_arrondissement {trace.precision_arrondissement!r} "
            f"!= 2"
        )
        assert trace.juridiction == Juridiction.QUEBEC, (
            f"trace.juridiction {trace.juridiction!r} != Juridiction.QUEBEC"
        )

    # Feature: charges-patronales, Property 9: Conformité et contenu de la trace
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_9_trace_fss_conforme_et_complete(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la trace de `calcul_fss` satisfait la partie commune de
        Property 9 et, en propre (design §Components §2) :

        - `trace.source` matche `^TP-1015\\.F \\d{4}, section 5 — FSS$` ;
        - `trace.parametres_utilises` contient le taux FSS
          (`fss.taux_camp_lilyso_2026`, règle 05) ;
        - `trace.entrees` contient `salaire_assujetti` (== `gains.brut_total`)
          et `masse_salariale_annuelle`
          (== `fss.masse_salariale_utilisee_webras_2026`).

        **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.4**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        montant, trace = module.calcul_fss(payroll_input, gains, parametres_annee)

        self._verifier_trace_commune(trace, montant, payroll_input)

        assert _MOTIF_SOURCE_FSS.fullmatch(trace.source), (
            f"trace.source FSS {trace.source!r} ne matche pas "
            f"{_MOTIF_SOURCE_FSS.pattern!r}"
        )

        # Le taux FSS consommé (règle 05) figure dans parametres_utilises.
        taux_fss = parametres_annee.fss.taux_camp_lilyso_2026
        assert taux_fss in trace.parametres_utilises.values(), (
            f"Le taux FSS {taux_fss!r} n'apparaît pas dans "
            f"parametres_utilises {trace.parametres_utilises!r}"
        )

        # entrees : salaire_assujetti (== brut_total) et masse_salariale_annuelle.
        assert "salaire_assujetti" in trace.entrees, (
            f"trace.entrees FSS doit contenir 'salaire_assujetti', "
            f"obtenu {trace.entrees!r}"
        )
        assert trace.entrees["salaire_assujetti"] == gains.brut_total, (
            f"trace.entrees['salaire_assujetti'] "
            f"{trace.entrees['salaire_assujetti']!r} != brut_total "
            f"{gains.brut_total!r}"
        )
        assert "masse_salariale_annuelle" in trace.entrees, (
            f"trace.entrees FSS doit contenir 'masse_salariale_annuelle', "
            f"obtenu {trace.entrees!r}"
        )
        assert (
            trace.entrees["masse_salariale_annuelle"]
            == parametres_annee.fss.masse_salariale_utilisee_webras_2026
        ), (
            f"trace.entrees['masse_salariale_annuelle'] "
            f"{trace.entrees['masse_salariale_annuelle']!r} != "
            f"fss.masse_salariale_utilisee_webras_2026 "
            f"{parametres_annee.fss.masse_salariale_utilisee_webras_2026!r}"
        )

    # Feature: charges-patronales, Property 9: Conformité et contenu de la trace
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_9_trace_cnesst_conforme_et_complete(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la trace de `calcul_cnesst` satisfait la partie commune de
        Property 9 et, en propre (design §Components §3) :

        - `trace.source` matche une URL sur `www.cnesst.gouv.qc.ca` ;
        - `trace.parametres_utilises` contient le taux total
          (`cnesst.taux_total`, règle 05) ;
        - `trace.section` contient l'unité `57020` (le contrat
          `parametres_utilises` étant typé `dict[str, Decimal]`, l'unité —
          une chaîne — est exposée dans le champ texte `section`) ;
        - `trace.entrees` contient `salaire_assujetti` (== `gains.brut_total`).

        **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.4**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        montant, trace = module.calcul_cnesst(payroll_input, gains, parametres_annee)

        self._verifier_trace_commune(trace, montant, payroll_input)

        assert _DOMAINE_CNESST in trace.source, (
            f"trace.source CNESST {trace.source!r} ne contient pas le domaine "
            f"officiel {_DOMAINE_CNESST!r}"
        )

        # Le taux total CNESST consommé (règle 05) figure dans parametres_utilises.
        taux_total = parametres_annee.cnesst.taux_total
        assert taux_total in trace.parametres_utilises.values(), (
            f"Le taux total CNESST {taux_total!r} n'apparaît pas dans "
            f"parametres_utilises {trace.parametres_utilises!r}"
        )

        # L'unité 57020 est exposée dans le champ texte section (Req 5.3).
        assert _UNITE_CNESST in trace.section, (
            f"trace.section CNESST {trace.section!r} ne contient pas l'unité "
            f"{_UNITE_CNESST!r}"
        )

        # entrees : salaire_assujetti (== brut_total).
        assert "salaire_assujetti" in trace.entrees, (
            f"trace.entrees CNESST doit contenir 'salaire_assujetti', "
            f"obtenu {trace.entrees!r}"
        )
        assert trace.entrees["salaire_assujetti"] == gains.brut_total, (
            f"trace.entrees['salaire_assujetti'] "
            f"{trace.entrees['salaire_assujetti']!r} != brut_total "
            f"{gains.brut_total!r}"
        )

    # Feature: charges-patronales, Property 9: Conformité et contenu de la trace
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_9_trace_cnt_conforme_et_complete(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        valides, la trace de `calcul_cnt` satisfait la partie commune de
        Property 9 et, en propre (design §Components §4) :

        - `trace.source == f"LE-39.0.2 {annee_fiscale}"` ;
        - `trace.parametres_utilises` contient le taux CNT (`cnt.taux`) et la
          `base_admissible` (`cnt.base_admissible`, documentaire — règle 05) ;
        - `trace.entrees` contient `salaire_assujetti` (== `gains.brut_total`).

        **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.4**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        montant, trace = module.calcul_cnt(payroll_input, gains, parametres_annee)

        self._verifier_trace_commune(trace, montant, payroll_input)

        source_attendue = f"LE-39.0.2 {payroll_input.pay_period.annee_fiscale}"
        assert trace.source == source_attendue, (
            f"trace.source CNT {trace.source!r} != {source_attendue!r}"
        )

        # Le taux CNT et la base_admissible consommés (règle 05) figurent dans
        # parametres_utilises.
        taux_cnt = parametres_annee.cnt.taux
        base_admissible = parametres_annee.cnt.base_admissible
        valeurs_parametres = trace.parametres_utilises.values()
        assert taux_cnt in valeurs_parametres, (
            f"Le taux CNT {taux_cnt!r} n'apparaît pas dans "
            f"parametres_utilises {trace.parametres_utilises!r}"
        )
        assert base_admissible in valeurs_parametres, (
            f"La base_admissible CNT {base_admissible!r} n'apparaît pas dans "
            f"parametres_utilises {trace.parametres_utilises!r}"
        )

        # entrees : salaire_assujetti (== brut_total).
        assert "salaire_assujetti" in trace.entrees, (
            f"trace.entrees CNT doit contenir 'salaire_assujetti', "
            f"obtenu {trace.entrees!r}"
        )
        assert trace.entrees["salaire_assujetti"] == gains.brut_total, (
            f"trace.entrees['salaire_assujetti'] "
            f"{trace.entrees['salaire_assujetti']!r} != brut_total "
            f"{gains.brut_total!r}"
        )


# ---------------------------------------------------------------------------
# 2.5 — Propagation de `MissingParameterError` sans interception (Property 13)
# ---------------------------------------------------------------------------

#: Association nom de fonction de calcul -> chemin ``"<section>.<champ>"`` du
#: champ **consommé** par cette fonction (design §Components §2, §3, §4). Passé
#: à ``st_parametres_annee_avec_to_fill(champ)`` pour produire un
#: ``ParametresAnnee`` où ce champ porte la sentinelle ``"TO_FILL"`` :
#:
#: - ``calcul_fss``    -> ``fss.taux_camp_lilyso_2026`` ;
#: - ``calcul_cnesst`` -> ``cnesst.taux_total`` ;
#: - ``calcul_cnt``    -> ``cnt.taux``.
_CHAMP_TO_FILL_PAR_FONCTION: dict[str, str] = {
    "calcul_fss": "fss.taux_camp_lilyso_2026",
    "calcul_cnesst": "cnesst.taux_total",
    "calcul_cnt": "cnt.taux",
}

#: Association nom de fonction de calcul -> nom de la **section requise** dont
#: l'absence (``None``) doit être détectée en tête de fonction (Req 1.8,
#: design §Components §1 « Garde-fou de section manquante », §Error Handling
#: « Distinction section absente vs valeur absente »).
_SECTION_REQUISE_PAR_FONCTION: dict[str, str] = {
    "calcul_fss": "fss",
    "calcul_cnesst": "cnesst",
    "calcul_cnt": "cnt",
}


@st.composite
def _st_fonction_et_parametres_to_fill(
    draw: st.DrawFn,
) -> tuple[str, object]:
    """``(nom_fonction, parametres_annee)`` où le champ consommé porte ``"TO_FILL"``.

    Tire l'un des trois noms de fonction de calcul puis, via
    ``st_parametres_annee_avec_to_fill(champ)`` (``champ`` étant le chemin
    ``"<section>.<champ>"`` du champ **consommé** par cette fonction —
    ``_CHAMP_TO_FILL_PAR_FONCTION``), un ``ParametresAnnee`` réel 2026 dont ce
    seul champ porte la sentinelle ``"TO_FILL"``. L'accès à la propriété
    matérialisée correspondante (``.taux_camp_lilyso_2026`` / ``.taux_total``
    / ``.taux``) lève ``MissingParameterError`` (design §Error Handling
    « Valeur absente »), ce que Property 13 vérifie.

    Règle 06 (immuabilité) : ``st_parametres_annee_avec_to_fill`` recopie la
    section ciblée puis la racine via ``model_copy`` — l'instance mémorisée
    des paramètres réels n'est jamais mutée.
    """
    nom_fonction = draw(st.sampled_from(tuple(_CHAMP_TO_FILL_PAR_FONCTION)))
    champ = _CHAMP_TO_FILL_PAR_FONCTION[nom_fonction]
    parametres_annee = draw(st_parametres_annee_avec_to_fill(champ))
    return nom_fonction, parametres_annee


class TestMissingParameterChargesPatronales:
    """Property 13 — propagation de `MissingParameterError` sans interception,
    et test d'exemple de la section requise `None`.

    Design (§Correctness Properties 13 ; §Error Handling « Matrice des
    exceptions », « Distinction section absente vs valeur absente »). Deux
    mécanismes distincts mènent à la même exception, tous deux couverts ici :

    - **valeur absente** (`"TO_FILL"`) sur un champ consommé — l'accès à la
      propriété matérialisée du sous-modèle lève `MissingParameterError`, que
      la fonction de calcul **propage** sans l'intercepter (Property 13,
      partie property) ;
    - **section absente** (`None`) — la fonction de calcul **lève**
      explicitement `MissingParameterError` en tête, avec un message
      actionnable identifiant la section manquante (Req 1.8, partie exemple).

    Dans les deux cas, l'exception observée doit être exactement
    `MissingParameterError` (jamais une autre exception, ni une exception
    masquée par un `except` trop large).
    """

    # Feature: charges-patronales, Property 13: Propagation de MissingParameterError
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        fonction_et_parametres=_st_fonction_et_parametres_to_fill(),
    )
    @settings_large_input
    def test_property_13_champ_consomme_to_fill_leve_missing_parameter_error(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        fonction_et_parametres: tuple[str, object],
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et pour tout
        `ParametresAnnee` où le champ **consommé** par l'une des trois
        fonctions de calcul (`fss.taux_camp_lilyso_2026`, `cnesst.taux_total`,
        `cnt.taux`) porte la sentinelle `"TO_FILL"`, l'appel à la fonction
        concernée lève `MissingParameterError` (jamais une autre exception, ni
        une exception masquée).

        La fonction de calcul ne redouble pas le contrôle : l'exception est
        **propagée** telle quelle depuis la propriété matérialisée du
        sous-modèle (design §Error Handling « Valeur absente »).

        **Validates: Requirements 1.8, 6.7**
        """
        payroll_input, gains = entrees
        nom_fonction, parametres_annee = fonction_et_parametres
        module = _importer_module_charges_patronales()

        fonction = getattr(module, nom_fonction)

        with pytest.raises(MissingParameterError):
            fonction(payroll_input, gains, parametres_annee)

    # Feature: charges-patronales, Property 13: Propagation de MissingParameterError
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_exemple_section_requise_none_leve_missing_parameter_error(
        self,
        payroll_input: PayrollInput,
        parametres_annee,
    ) -> None:
        """Test d'exemple — section requise `None` -> `MissingParameterError`
        avec message actionnable identifiant la section manquante (Req 1.8).

        Pour chacune des trois fonctions de calcul, on construit une variante
        du `ParametresAnnee` réel 2026 où **sa** section requise
        (`fss` / `cnesst` / `cnt`) est mise à `None` via `model_copy`
        (règle 06 — immuabilité : l'instance de base n'est jamais mutée).
        L'appel doit lever `MissingParameterError` (jamais une autre
        exception) et le message doit identifier la section manquante
        (design §Components §1 « Garde-fou de section manquante », §Error
        Handling « Distinction section absente vs valeur absente »).

        Le garde-fou de section s'exécutant en tête de fonction, l'exception
        est levée indépendamment des valeurs de `payroll_input` et de
        `gains` ; un `GainsDecomposes` minimal non nul suffit.
        """
        module = _importer_module_charges_patronales()
        gains = _construire_gains_decomposes(Decimal("1000.00"))

        for nom_fonction, nom_section in _SECTION_REQUISE_PAR_FONCTION.items():
            parametres_sans_section = parametres_annee.model_copy(
                update={nom_section: None}
            )
            fonction = getattr(module, nom_fonction)

            with pytest.raises(MissingParameterError) as exc_info:
                fonction(payroll_input, gains, parametres_sans_section)

            message = str(exc_info.value)
            assert nom_section in message, (
                f"{nom_fonction} avec la section '{nom_section}' absente doit "
                f"lever une MissingParameterError dont le message identifie la "
                f"section manquante ; message obtenu : {message!r}"
            )


# ---------------------------------------------------------------------------
# 3.1 — Assemblage `assembler_cotisations_employeur`
#       (Property 10, 11, 12 + variantes d'assemblage des Property 1, 6, 13)
# ---------------------------------------------------------------------------
#
# L'assemblage **invoque** (sans les recalculer) les trois fonctions employeur
# de l'étape 3 — ``calcul_rrq_employeur`` (``payroll_engine.rrq``),
# ``calcul_rqap_employeur`` (``payroll_engine.rqap``) et ``calcul_ae_employeur``
# (``payroll_engine.assurance_emploi``) — puis les trois fonctions de charges
# patronales de cette spec (``calcul_fss``, ``calcul_cnesst``, ``calcul_cnt``).
#
# ``calcul_ae_employeur`` lit ``parametres_annee.assurance_emploi`` (section du
# fichier ``canada.json``), tandis que RRQ/RQAP lisent ``rrq``/``rqap`` et les
# trois charges lisent ``fss``/``cnesst``/``cnt`` (fichier ``quebec.json``).
# Les tests d'assemblage utilisent donc ``st_parametres_annee_2026_qc_ca()``
# (fusion Québec + Canada : ``rrq``, ``rqap``, ``fss``, ``cnesst``, ``cnt`` de
# la racine Québec enrichis de ``assurance_emploi`` de la racine Canada), et
# **non** ``st_parametres_annee_2026_qc()`` (Québec seul, sans
# ``assurance_emploi`` — patron identique à
# ``tests/test_golden_outputs.py::test_charges_patronales_reproduisent_fixture``
# et à ``tests/strategies.py::_charger_parametres_annee_2026_qc_ca``).

#: Noms des six champs ``MontantAvecTrace`` de ``CotisationsEmployeur``, dans
#: l'ordre du contrat figé (design §Data Models 9). Property 12 (identité
#: d'agrégation) somme les ``montant`` de ces six champs ; Property 6
#: (assemblage) vérifie leur forme ``Decimal``.
_CHAMPS_COTISATIONS_EMPLOYEUR: tuple[str, ...] = (
    "rrq_employeur",
    "rqap_employeur",
    "ae_employeur",
    "fss",
    "cnesst",
    "cnt",
)

#: Chemins ``"<section>.<champ>"`` de champs **consommés** par l'une des six
#: fonctions invoquées par l'assemblage (trois employeur de l'étape 3 + trois
#: charges de cette spec). Passés à ``st_parametres_annee_avec_to_fill(champ)``,
#: ils produisent un ``ParametresAnnee`` où ce seul champ porte ``"TO_FILL"`` :
#: la fonction invoquée qui le consomme lève alors ``MissingParameterError``,
#: que l'assemblage doit **propager** sans l'intercepter (Property 13). Les
#: chemins couvrent aussi bien une charge patronale (``fss``/``cnesst``/``cnt``)
#: qu'une cotisation employeur invoquée (``rrq``/``rqap``/``assurance_emploi``),
#: pour démontrer la propagation quelle que soit la fonction source.
_CHAMPS_TO_FILL_ASSEMBLAGE: tuple[str, ...] = (
    "fss.taux_camp_lilyso_2026",
    "cnesst.taux_total",
    "cnt.taux",
    "rrq.taux_cotisation_totale_employe",
    "rqap.taux_employeur",
    "assurance_emploi.multiplicateur_employeur",
)


def _fonctions_sources_par_champ(module_charges: ModuleType) -> dict:
    """Association champ de ``CotisationsEmployeur`` -> fonction source.

    Property 10 (assemblage par invocation) vérifie que chaque
    ``MontantAvecTrace`` de ``CotisationsEmployeur`` provient **exactement**
    de l'appel à la fonction dédiée. Cette table associe chacun des six champs
    à la fonction qui le produit :

    - ``rrq_employeur`` -> ``payroll_engine.rrq.calcul_rrq_employeur`` ;
    - ``rqap_employeur`` -> ``payroll_engine.rqap.calcul_rqap_employeur`` ;
    - ``ae_employeur`` -> ``payroll_engine.assurance_emploi.calcul_ae_employeur`` ;
    - ``fss`` -> ``calcul_fss`` (module de charges) ;
    - ``cnesst`` -> ``calcul_cnesst`` (module de charges) ;
    - ``cnt`` -> ``calcul_cnt`` (module de charges).

    Les trois fonctions employeur de l'étape 3 existent déjà : elles sont
    importées **localement** (au moment de l'appel) pour rester cohérent avec
    la discipline règle 06 du fichier (le module de charges, lui, n'existe pas
    encore et est fourni par ``module_charges``).
    """
    from payroll_engine.assurance_emploi import calcul_ae_employeur
    from payroll_engine.rqap import calcul_rqap_employeur
    from payroll_engine.rrq import calcul_rrq_employeur

    return {
        "rrq_employeur": calcul_rrq_employeur,
        "rqap_employeur": calcul_rqap_employeur,
        "ae_employeur": calcul_ae_employeur,
        "fss": module_charges.calcul_fss,
        "cnesst": module_charges.calcul_cnesst,
        "cnt": module_charges.calcul_cnt,
    }


@st.composite
def _st_parametres_assemblage_to_fill(draw: st.DrawFn) -> object:
    """``ParametresAnnee`` (fusion QC/CA) dont un champ consommé porte ``"TO_FILL"``.

    Tire l'un des chemins de ``_CHAMPS_TO_FILL_ASSEMBLAGE`` (champ consommé par
    l'une des six fonctions invoquées par l'assemblage) puis, via
    ``st_parametres_annee_avec_to_fill(champ)``, un ``ParametresAnnee`` réel
    2026 (fusion Québec + Canada) dont ce seul champ porte la sentinelle
    ``"TO_FILL"``. L'accès à la propriété matérialisée correspondante lève
    ``MissingParameterError`` lorsque la fonction qui la consomme est invoquée
    par l'assemblage — ce que Property 13 (assemblage) vérifie.

    Règle 06 (immuabilité) : ``st_parametres_annee_avec_to_fill`` recopie la
    section ciblée puis la racine via ``model_copy`` — l'instance mémorisée des
    paramètres réels n'est jamais mutée.
    """
    champ = draw(st.sampled_from(_CHAMPS_TO_FILL_ASSEMBLAGE))
    return draw(st_parametres_annee_avec_to_fill(champ))


class TestAssemblageCotisationsEmployeur:
    """Property 10, 11, 12 + variantes d'assemblage des Property 1, 6, 13.

    Design (§Correctness Properties 1, 6, 10, 11, 12, 13 ; §Components §5).
    ``assembler_cotisations_employeur`` produit un ``CotisationsEmployeur`` en
    **invoquant** (jamais en recalculant) les six fonctions employeur :

    - Property 10 — chaque ``MontantAvecTrace`` provient exactement de l'appel
      à la fonction dédiée (montant **et** trace) ;
    - Property 11 — le drapeau ``cnesst_en_attente_classification`` est reporté
      depuis les paramètres et n'a aucun effet sur le total ;
    - Property 12 — le ``total_cotisations_employeur`` égale, au cent près, la
      somme des six montants employeur ;
    - Property 1 (assemblage) — déterminisme (deux appels égaux au sens ``==``) ;
    - Property 6 (assemblage) — forme ``Decimal`` du total et des six montants ;
    - Property 13 (assemblage) — propagation de ``MissingParameterError`` sans
      interception.

    Règle 05 : les taux et drapeaux attendus sont lus depuis ``parametres_annee``
    (jamais codés en dur). Règle 01 : toutes les valeurs comparées sont des
    ``Decimal`` (ou le ``bool`` du drapeau CNESST).
    """

    # Feature: charges-patronales, Property 10: Assemblage par invocation sans recalcul
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_10_assemblage_par_invocation_sans_recalcul(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        (fusion QC/CA) valides, l'objet `CotisationsEmployeur` produit par
        `assembler_cotisations_employeur` satisfait champ par champ :

        - `cot.rrq_employeur.montant == calcul_rrq_employeur(pi, g, p)[0]` ;
        - `cot.rqap_employeur.montant == calcul_rqap_employeur(pi, g, p)[0]` ;
        - `cot.ae_employeur.montant == calcul_ae_employeur(pi, g, p)[0]` ;
        - `cot.fss.montant == calcul_fss(pi, g, p)[0]` ;
        - `cot.cnesst.montant == calcul_cnesst(pi, g, p)[0]` ;
        - `cot.cnt.montant == calcul_cnt(pi, g, p)[0]`.

        De plus, chaque champ est un `MontantAvecTrace` dont la `trace` est
        **exactement** celle retournée par la fonction correspondante
        (`getattr(cot, champ).trace == f(pi, g, p)[1]`) : l'assemblage
        n'invente ni ne recalcule aucune trace (design §Components §5).

        **Validates: Requirements 1.3, 6.1, 6.2, 6.3, 9.1**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        cot = module.assembler_cotisations_employeur(
            payroll_input, gains, parametres_annee
        )
        fonctions_sources = _fonctions_sources_par_champ(module)

        for nom_champ in _CHAMPS_COTISATIONS_EMPLOYEUR:
            fonction = fonctions_sources[nom_champ]
            montant_attendu, trace_attendue = fonction(
                payroll_input, gains, parametres_annee
            )

            champ = getattr(cot, nom_champ)
            assert isinstance(champ, MontantAvecTrace), (
                f"cot.{nom_champ} doit être un MontantAvecTrace, obtenu "
                f"{champ!r}"
            )
            assert champ.montant == montant_attendu, (
                f"cot.{nom_champ}.montant {champ.montant!r} != "
                f"montant retourné par la fonction source {montant_attendu!r} "
                f"(recalcul détecté ?)"
            )
            assert champ.trace == trace_attendue, (
                f"cot.{nom_champ}.trace ne provient pas de la fonction "
                f"correspondante"
            )

    # Feature: charges-patronales, Property 11: Report du drapeau CNESST sans effet sur le total
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_base=st_parametres_annee_2026_qc_ca(),
        variante_qc=st_parametres_annee_variantes_non_consommees(),
    )
    @settings_large_input
    def test_property_11_report_du_drapeau_cnesst_sans_effet_sur_le_total(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_base,
        variante_qc,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` valides :

        - **Report** — `cot.cnesst_en_attente_classification` égale
          `parametres_annee.cnesst.en_attente_classification` (le drapeau est
          reporté tel quel depuis les paramètres, jamais recalculé — Req 6.4,
          9.3) ;
        - **Sans effet sur le total** — `total_cotisations_employeur` est
          identique que le drapeau vaille `True` ou `False` (Req 9.3).

        Le second point est vérifié en comparant l'assemblage sur
        `parametres_base` (fusion QC/CA réelle, drapeau `False` pour 2026) et
        sur une variante (`st_parametres_annee_variantes_non_consommees()`) qui
        **diffère uniquement** sur des champs non consommés — dont le drapeau
        `cnesst.en_attente_classification`, tiré aléatoirement `True`/`False`.
        La variante est enrichie de la section `assurance_emploi` (et
        `impot_federal`) de `parametres_base` pour que `calcul_ae_employeur`
        invoqué par l'assemblage dispose de sa section (la variante, issue de
        `st_parametres_annee_2026_qc()`, est Québec seul). Les taux consommés
        (`fss.taux_camp_lilyso_2026`, `cnesst.taux_total`, `cnt.taux`, RRQ,
        RQAP, AE) étant identiques entre base et variante, les deux totaux
        doivent être égaux au sens `==` : varier le drapeau (et les autres
        champs non consommés) ne change pas le total.

        **Validates: Requirements 6.4, 9.3, 10.4, 10.6**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        # La variante (Québec seul) reçoit la section assurance_emploi de la
        # base fusionnée pour que l'assemblage puisse invoquer calcul_ae_employeur
        # (règle 06 — model_copy, aucune mutation de l'instance de base).
        variante = variante_qc.model_copy(
            update={
                "assurance_emploi": parametres_base.assurance_emploi,
                "impot_federal": parametres_base.impot_federal,
            }
        )

        cot_base = module.assembler_cotisations_employeur(
            payroll_input, gains, parametres_base
        )
        cot_variante = module.assembler_cotisations_employeur(
            payroll_input, gains, variante
        )

        # Report fidèle du drapeau depuis les paramètres.
        assert (
            cot_base.cnesst_en_attente_classification
            == parametres_base.cnesst.en_attente_classification
        ), (
            f"cot_base.cnesst_en_attente_classification "
            f"{cot_base.cnesst_en_attente_classification!r} != "
            f"parametres.cnesst.en_attente_classification "
            f"{parametres_base.cnesst.en_attente_classification!r}"
        )
        assert (
            cot_variante.cnesst_en_attente_classification
            == variante.cnesst.en_attente_classification
        ), (
            f"cot_variante.cnesst_en_attente_classification "
            f"{cot_variante.cnesst_en_attente_classification!r} != "
            f"variante.cnesst.en_attente_classification "
            f"{variante.cnesst.en_attente_classification!r}"
        )

        # Le drapeau (et les autres champs non consommés) n'affecte pas le total.
        assert (
            cot_base.total_cotisations_employeur
            == cot_variante.total_cotisations_employeur
        ), (
            f"total_cotisations_employeur dépend d'un champ non consommé "
            f"(drapeau CNESST ?) : base "
            f"{cot_base.total_cotisations_employeur!r} != variante "
            f"{cot_variante.total_cotisations_employeur!r}"
        )

    # Feature: charges-patronales, Property 12: Identité d'agrégation
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_12_identite_d_agregation(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        (fusion QC/CA) valides, `cot.total_cotisations_employeur` égale, au
        cent près, la somme des six montants employeur (`rrq_employeur +
        rqap_employeur + ae_employeur + fss + cnesst + cnt`).

        Chaque montant étant déjà arrondi à deux décimales, leur somme est
        exacte au cent : l'égalité est vérifiée au sens `==` (tolérance nulle,
        règle 01), cohérente avec l'invariant `model_validator` déjà porté par
        le contrat `CotisationsEmployeur`.

        **Validates: Requirements 6.5, 9.1, 10.6**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        cot = module.assembler_cotisations_employeur(
            payroll_input, gains, parametres_annee
        )

        somme_des_six = sum(
            (getattr(cot, nom_champ).montant for nom_champ in _CHAMPS_COTISATIONS_EMPLOYEUR),
            start=Decimal("0.00"),
        )

        assert cot.total_cotisations_employeur == somme_des_six, (
            f"total_cotisations_employeur {cot.total_cotisations_employeur!r} "
            f"!= somme des six montants employeur {somme_des_six!r}"
        )

    # Feature: charges-patronales, Property 1: Déterminisme (pureté)
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_1_assemblage_deux_appels_identiques_produisent_des_cotisations_egales(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        (fusion QC/CA) valides, deux appels de
        `assembler_cotisations_employeur` avec les mêmes arguments produisent
        deux `CotisationsEmployeur` égaux au sens `==` (déterminisme, pureté).

        **Validates: Requirements 1.3, 6.6, 10.4**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        cot_1 = module.assembler_cotisations_employeur(
            payroll_input, gains, parametres_annee
        )
        cot_2 = module.assembler_cotisations_employeur(
            payroll_input, gains, parametres_annee
        )

        assert cot_1 == cot_2, (
            f"assembler_cotisations_employeur n'est pas déterministe : "
            f"{cot_1!r} != {cot_2!r}"
        )

    # Feature: charges-patronales, Property 6: Forme Decimal du résultat et de la trace
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings_large_input
    def test_property_6_assemblage_forme_decimal_du_total_et_des_six_montants(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput`, `GainsDecomposes` et `ParametresAnnee`
        (fusion QC/CA) valides, `total_cotisations_employeur` est un `Decimal`
        fini à deux décimales (égal à son arrondi `ROUND_HALF_UP`), et chacun
        des six `montant` des champs employeur est un `Decimal` fini.

        **Validates: Requirements 6.5, 10.5**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        cot = module.assembler_cotisations_employeur(
            payroll_input, gains, parametres_annee
        )

        total = cot.total_cotisations_employeur
        assert isinstance(total, Decimal), (
            f"total_cotisations_employeur n'est pas un Decimal : {total!r}"
        )
        assert total.is_finite(), (
            f"total_cotisations_employeur n'est pas fini : {total!r}"
        )
        assert total == total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), (
            f"total_cotisations_employeur {total!r} n'est pas à deux décimales "
            f"ROUND_HALF_UP"
        )

        for nom_champ in _CHAMPS_COTISATIONS_EMPLOYEUR:
            montant = getattr(cot, nom_champ).montant
            assert isinstance(montant, Decimal), (
                f"cot.{nom_champ}.montant n'est pas un Decimal : {montant!r}"
            )
            assert montant.is_finite(), (
                f"cot.{nom_champ}.montant n'est pas fini : {montant!r}"
            )

    # Feature: charges-patronales, Property 13: Propagation de MissingParameterError
    @pytest.mark.property
    @given(
        entrees=_st_entrees(),
        parametres_annee=_st_parametres_assemblage_to_fill(),
    )
    @settings_large_input
    def test_property_13_assemblage_propage_missing_parameter_error(
        self,
        entrees: tuple[PayrollInput, GainsDecomposes],
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` et `GainsDecomposes` valides, et pour tout
        `ParametresAnnee` (fusion QC/CA) où un champ **consommé** par l'une des
        six fonctions invoquées par l'assemblage (`fss.taux_camp_lilyso_2026`,
        `cnesst.taux_total`, `cnt.taux`, `rrq.taux_cotisation_totale_employe`,
        `rqap.taux_employeur`, `assurance_emploi.multiplicateur_employeur`)
        porte la sentinelle `"TO_FILL"`, l'appel à
        `assembler_cotisations_employeur` lève `MissingParameterError` : la
        fonction invoquée qui consomme ce champ lève l'exception, et
        l'assemblage la **propage** sans l'intercepter (jamais une autre
        exception, ni une exception masquée).

        **Validates: Requirements 6.7, 10.4**
        """
        payroll_input, gains = entrees
        module = _importer_module_charges_patronales()

        with pytest.raises(MissingParameterError):
            module.assembler_cotisations_employeur(
                payroll_input, gains, parametres_annee
            )
