"""Property tests, tests d'exemple et fixtures pour `calcul_gains`.

Spec de référence : ``gains-bruts-vacances-hs`` — tâche 1.2 (squelette).
Design de référence : ``design.md`` §Testing Strategy (« Approche duale »,
« Organisation des fichiers de test », « Configuration Hypothesis »,
« Stratégies Hypothesis ») et §Architecture « Point de vérification
`parameters/2026/quebec.json` » (Req 9.6).

Ce fichier est actuellement un **squelette** (tâche 1.2 uniquement) : il
porte les imports, la fixture de vérification des paramètres et la
configuration Hypothesis partagée. Les classes de property tests
elles-mêmes sont ajoutées par les tâches 2.1 à 2.12, chacune couvrant une
ou plusieurs des propriétés listées ci-dessous. Conformément à la règle 06
(TDD — tests avant code), ce squelette précède l'implémentation de
``payroll_engine/gains_bruts.py`` (tâche 5.1/5.2) ; il n'importe donc PAS
encore ce module au niveau fichier, afin de ne pas casser la collection
pytest tant qu'il n'existe pas. Chaque tâche 2.x important effectivement
``calcul_gains`` le fera dans son propre contexte, une fois le module créé.

19 propriétés couvertes par ce fichier (design §Correctness Properties),
groupées en 12 classes de test (une par sous-tâche 2.1 à 2.12) :

1.  Linéarité du salaire régulier — ``TestLineariteSalaireRegulier`` (2.2)
2.  Linéarité du montant des heures supplémentaires — ``TestLineariteHeuresSupp`` (2.3)
3.  Identité comptable du brut total — ``TestIdentiteComptableBrut`` (2.6)
4.  Monotonie du brut vs heures normales — ``TestMonotonieHeuresNormales`` (2.4)
5.  Monotonie du brut vs heures supplémentaires — ``TestMonotonieHeuresSupp`` (2.5)
6.  Forme des composantes monétaires — ``TestFormeComposantes`` (2.7)
7.  Transport strict de ``jours_feries_manuels`` — ``TestTransportStrict`` (2.8)
8.  Transport strict du multiplicateur et du seuil — ``TestTransportStrict`` (2.8)
9.  Déterminisme (idempotence de l'appel) — ``TestSignaturePureteDeterminisme`` (2.1)
10. Absence d'exception sur ``PayrollInput`` valide — ``TestSignaturePureteDeterminisme`` (2.1)
11. Forme du tuple retourné — ``TestSignaturePureteDeterminisme`` (2.1)
12. Conformité de ``trace.source`` à la liste blanche — ``TestTraceSourceMetadonnees`` (2.9)
13. Contenu de ``trace.entrees`` — ``TestTraceContenu`` (2.10)
14. Contenu et ordre de ``trace.sous_totaux`` — ``TestTraceContenu`` (2.10)
15. Contenu de ``trace.parametres_utilises`` — ``TestTraceContenu`` (2.10)
16. Cohérence des métadonnées d'arrondissement dans la trace — ``TestTraceSourceMetadonnees`` (2.9)
17. Auto-suffisance de la trace (identité comptable interne) — ``TestTraceAutoSuffisante`` (2.11)
18. Extensibilité au taux 6 % — ``TestExtensibiliteEtDefense`` (2.12)
19. Refus d'un ``taux_vacances`` hors matrice (défense en profondeur) — ``TestExtensibiliteEtDefense`` (2.12)

**Limitation du corpus golden** (héritée de l'Introduction des
requirements et rappelée ici pour toute propriété qui s'appuierait sur des
exemples calibrés semaine par semaine) : les fixtures QC001–QC006 portent
une décomposition hebdomadaire **fabriquée 50/50** du total de période sur
les deux semaines constituantes. Les valeurs WebRAS et PDOC de référence
ont été calculées sur les **totaux de période**, pas sur des semaines
individuelles. Les property tests de ce fichier ne s'appuient donc jamais
sur une décomposition hebdomadaire réputée auditée — seule la linéarité de
la formule (Property 1, Property 2) garantit l'équivalence totaux de
période / somme des semaines. Voir ``docs/hypotheses-2026.md`` §9 pour le
détail de cette limitation.

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison.
"""

from __future__ import annotations

import re
import sys
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.enums import Juridiction, ModeArrondissement
from models.exceptions import UnsupportedPayrollCase
from models.payroll_input import HeuresParSemaine
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters
from tests.strategies import (  # noqa: F401
    st_heures_par_semaine,
    st_jours_feries_manuels,
    st_parametres_annee_2026_qc,
    st_payroll_input,
    st_taux_horaire,
    st_taux_vacances,
)

# ---------------------------------------------------------------------------
# Fixture session-scoped : paramètres 2026 Québec + vérification Req 9.6
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def parametres_2026_qc() -> ParametresAnnee:
    """Charge une seule fois ``load_parameters(2026, Juridiction.QUEBEC)``.

    Design (§Architecture « Point de vérification
    `parameters/2026/quebec.json` », Req 9.6) : le fichier
    ``parameters/2026/quebec.json`` contient déjà les deux clés
    nécessaires à ``calcul_gains`` dans sa section
    ``heures_supplementaires``. Cette fixture matérialise la **vérification
    de non-régression** exigée par la tâche 1.2 — si une future édition du
    fichier modifiait accidentellement le multiplicateur légal (1,5) ou le
    seuil hebdomadaire (40 h), toute la suite de tests de cette spec
    échouerait immédiatement ici, avant même d'exercer ``calcul_gains``.

    Portée ``session`` : le fichier n'est lu qu'une seule fois par
    exécution de la suite, quel que soit le nombre de tests (property ou
    exemple) qui consomment cette fixture — cohérent avec la mémorisation
    ``lru_cache`` de ``st_parametres_annee_2026_qc()`` dans
    ``tests/strategies.py`` (tâche 1.1).
    """
    parametres = load_parameters(2026, Juridiction.QUEBEC)

    # Req 9.6 — non-régression des deux clés critiques consommées par
    # calcul_gains. Ces valeurs viennent exclusivement du fichier JSON
    # versionné (règle 05) ; elles ne sont jamais codées en dur ailleurs.
    assert parametres.heures_supplementaires.multiplicateur == Decimal("1.5")
    assert parametres.heures_supplementaires.seuil_hebdomadaire_heures == Decimal("40")

    return parametres


# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée
# ---------------------------------------------------------------------------

# Design (§Testing Strategy « Configuration Hypothesis ») : 100 itérations
# minimum (défaut Hypothesis), pas de deadline (les modèles Pydantic
# peuvent dépasser 200 ms/exemple sous charge), et suppression du health
# check "too_slow" pour les propriétés à surface d'entrée large (composition
# de plusieurs sous-modèles via ``st_payroll_input()``). Réutilisable en
# ``@settings_large_input`` sur chaque test property de ce fichier.
settings_large_input = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# 2.1 — Signature, pureté et déterminisme (Property 9, 10, 11)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) : ``payroll_engine/gains_bruts.py`` n'existe
# pas encore (tâches 5.1/5.2 non réalisées à ce stade). Contrairement aux
# autres fichiers de test du dépôt qui importent le module cible au niveau
# module (acceptant que toute la collection du fichier échoue avec
# ``ModuleNotFoundError`` tant que le module n'existe pas), ce fichier a
# été conçu par la tâche 1.2 pour rester **collectable** même en l'absence
# de ``gains_bruts.py`` — voir le docstring de module ci-dessus. L'import
# de ``calcul_gains`` est donc fait **localement**, à l'intérieur de
# chaque test qui en a besoin : seuls ces tests précis échouent
# (``ModuleNotFoundError`` levée au moment de l'exécution du test, pas de
# la collection), le reste de la suite pytest du dépôt n'est pas affecté.


class TestSignaturePureteDeterminisme:
    """Property 9, 10, 11 — signature, pureté et déterminisme de `calcul_gains`.

    Design (§Correctness Properties 9, 10, 11 ; §Components §1 « Signature
    exacte »). Trois propriétés Hypothesis plus un test d'exemple
    vérifiant l'absence d'effet de bord à l'import (Req 1.6).
    """

    # Feature: gains-bruts-vacances-hs, Property 9: Déterminisme (idempotence de l'appel)
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_9_deux_appels_identiques_produisent_des_tuples_egaux(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee` valide,
        `calcul_gains(pi, p) == calcul_gains(pi, p)` : deux appels avec les
        mêmes arguments produisent deux tuples égaux au sens `==` sur les
        deux composantes (`GainsDecomposes` et `CalculationTrace`).

        **Validates: Requirements 1.2, 14.1, 14.2**

        Aucun état interne persistant, aucune source de non-déterminisme
        (règle 06 « fonction pure ») : deux appels successifs avec le même
        `PayrollInput` (immuable, `frozen=True`) et le même `ParametresAnnee`
        (immuable, mémorisé par `st_parametres_annee_2026_qc`) doivent
        produire deux résultats structurellement identiques.
        """
        from payroll_engine.gains_bruts import calcul_gains

        resultat_1 = calcul_gains(payroll_input, parametres_annee)
        resultat_2 = calcul_gains(payroll_input, parametres_annee)

        assert resultat_1 == resultat_2
        assert resultat_1[0] == resultat_2[0]
        assert resultat_1[1] == resultat_2[1]

    # Feature: gains-bruts-vacances-hs, Property 10: Absence d'exception sur PayrollInput valide
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_10_aucune_exception_sur_payroll_input_valide(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide (construit via le constructeur
        normal, pas `model_construct`) et tout `ParametresAnnee` valide,
        `calcul_gains(pi, p)` retourne un tuple sans lever aucune exception.

        **Validates: Requirements 1.5, 4.3, 10.4**

        `st_payroll_input()` (tâche 1.1) couvre par construction les cas
        extrêmes du corpus : heures très élevées (`> 40` h/semaine, jusqu'à
        `60`), brut très faible (heures à `0`), taux de vacances à `6 %`
        (`Decimal("0.06")`) et heures fractionnaires (deux décimales). Un
        échec de ce test par exception non attendue signale un défaut de
        robustesse de `calcul_gains` sur l'espace complet des entrées
        valides, pas une erreur de construction (`PayrollInput` lui-même
        refuse déjà tout cas hors matrice — règle 03).
        """
        from payroll_engine.gains_bruts import calcul_gains

        resultat = calcul_gains(payroll_input, parametres_annee)

        assert resultat is not None

    # Feature: gains-bruts-vacances-hs, Property 11: Forme du tuple retourné
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_11_forme_du_tuple_retourne(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee` valide,
        `calcul_gains(pi, p)` retourne un `tuple` de longueur exactement 2,
        avec `result[0]: GainsDecomposes` et `result[1]: CalculationTrace`.

        **Validates: Requirements 1.4**
        """
        from payroll_engine.gains_bruts import calcul_gains

        resultat = calcul_gains(payroll_input, parametres_annee)

        assert isinstance(resultat, tuple)
        assert len(resultat) == 2
        assert isinstance(resultat[0], GainsDecomposes)
        assert isinstance(resultat[1], CalculationTrace)

    def test_import_calcul_gains_sans_effet_de_bord(self, capsys) -> None:
        """Test d'exemple — `from payroll_engine.gains_bruts import
        calcul_gains` ne produit **aucun effet de bord** (Req 1.6) : pas
        d'ouverture de fichier, pas d'appel réseau, pas d'écriture sur
        `stdout` / `stderr`.

        Design (§Architecture « Contrainte de pureté »). Le module retiré
        de `sys.modules` avant l'import (s'il y était déjà, par exemple
        parce qu'un test précédent de cette classe l'a importé
        localement) afin de forcer une exécution fraîche du corps du
        module — c'est justement au moment de cette exécution que
        d'éventuels effets de bord au niveau module (ouverture de
        fichier, `print`, connexion réseau) se manifesteraient.

        Vérification en deux temps :

        1. Capture `capsys` — silence complet sur `stdout` et `stderr`
           pendant l'import.
        2. Inspection de `sys.modules` — le module est bien chargé après
           l'import (preuve que l'absence de sortie n'est pas due à un
           échec silencieux, mais à un import réussi et silencieux).
        """
        import importlib

        nom_module = "payroll_engine.gains_bruts"
        sys.modules.pop(nom_module, None)

        importlib.import_module(nom_module)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert nom_module in sys.modules


# ---------------------------------------------------------------------------
# 2.2 — Linéarité du salaire régulier (Property 1)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


class TestLineariteSalaireRegulier:
    """Property 1 — linéarité du salaire régulier.

    Design (§Correctness Properties 1 ; §Components §2 étape 1). Le test
    recalcule le résultat attendu par une **formule alternative**
    (multiplication directe du taux horaire par le total agrégé des
    heures normales des deux semaines constituantes) et compare au cent
    près à `gains.salaire_regulier`. La formule alternative inverse
    l'ordre somme/multiplication par rapport à l'algorithme attendu (qui
    somme les produits par semaine avant d'arrondir une seule fois) :
    l'égalité au cent près exploite la linéarité de la multiplication
    `Decimal` (Req 2.1, note « granularité » du design et des
    requirements).
    """

    # Feature: gains-bruts-vacances-hs, Property 1: Linéarité du salaire régulier
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_1_salaire_regulier_egal_formule_alternative_sur_total_agrege(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, `gains.salaire_regulier` est égal, au cent près
        (comparaison `==` sur `Decimal`, tolérance nulle — règle 01), au
        produit du taux horaire effectif par la somme agrégée des heures
        normales des deux semaines constituantes, arrondi selon
        `ROUND_HALF_UP` à deux décimales.

        **Validates: Requirements 2.1, 2.2, 2.4, 2.5, 4.1, 4.2, 4.4, 4.5**

        Formule alternative (multiplication directe sur le total agrégé,
        Req 2.1 note « granularité ») :

            heures_normales_totales = Σ semaine.heures_normales
            attendu = quantize(
                heures_normales_totales × taux_horaire_effectif,
                Decimal("0.01"),
                ROUND_HALF_UP,
            )

        Cette formule alternative n'utilise ni le
        `Multiplicateur_Heures_Supp` (Req 2.2 — il ne s'applique jamais
        aux heures normales) ni `heures_supplementaires` : seule
        `heures_normales` entre dans le total agrégé, ce qui couvre
        implicitement les cas de bord Req 2.4 (somme nulle → résultat
        `Decimal("0.00")`) et Req 4.4/4.5 (heures nulles ou
        fractionnaires, aucun traitement spécial) exercés par
        `st_payroll_input()` / `st_heures_par_semaine()`. Règle 01 :
        aucun `float` n'intervient dans le calcul de la valeur attendue.
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, _trace = calcul_gains(payroll_input, parametres_annee)

        heures_normales_totales = sum(
            (s.heures_normales for s in payroll_input.heures_par_semaine),
            start=Decimal("0"),
        )
        attendu = (
            heures_normales_totales * payroll_input.taux_horaire_effectif
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert gains.salaire_regulier == attendu


# ---------------------------------------------------------------------------
# 2.3 — Linéarité du montant des heures supplémentaires (Property 2)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1/2.2 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


@st.composite
def _st_paire_heures_normales_excedentaires(
    draw: st.DrawFn,
) -> tuple[object, object]:
    """Génère une paire `(payroll_input, payroll_input_modifie)` qui ne
    diffère que par `heures_par_semaine[0].heures_normales`, poussée
    strictement au-delà du seuil hebdomadaire légal de 40 h.

    Utilisé par la Property 2 (sous-vérification « absence de
    reclassement », Req 3.5, Req 4.2, Req 4.3) : la valeur de
    `heures_supplementaires_montant` ne doit dépendre en rien de
    `heures_normales`, même lorsque cette dernière dépasse 40 h sur la
    semaine. `heures_par_semaine` étant un tuple de modèles Pydantic
    `frozen=True`, la modification passe par `model_copy(update=...)`
    (sur `HeuresParSemaine` puis sur `PayrollInput`) plutôt que par une
    mutation directe.
    """
    payroll_input = draw(st_payroll_input())
    heures_normales_excedentaire = draw(
        st.decimals(
            min_value=Decimal("40.01"),
            max_value=Decimal("168"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    semaine_0 = payroll_input.heures_par_semaine[0]
    semaine_0_modifiee = semaine_0.model_copy(
        update={"heures_normales": heures_normales_excedentaire}
    )
    payroll_input_modifie = payroll_input.model_copy(
        update={
            "heures_par_semaine": (
                semaine_0_modifiee,
                *payroll_input.heures_par_semaine[1:],
            )
        }
    )
    return payroll_input, payroll_input_modifie


class TestLineariteHeuresSupp:
    """Property 2 — linéarité du montant des heures supplémentaires.

    Design (§Correctness Properties 2 ; §Components §2 étape 2). Le test
    principal recalcule le résultat attendu par une **formule
    alternative** (taux horaire × multiplicateur × total agrégé des
    heures supplémentaires des deux semaines constituantes) et compare
    au cent près à `gains.heures_supplementaires_montant`, exploitant la
    linéarité de la multiplication `Decimal` (Req 3.1, note
    « granularité » du design et des requirements).

    Un second test vérifie explicitement l'**absence de reclassement**
    (Req 3.5, Req 4.2, Req 4.3) : le montant HS ne varie pas lorsque
    `heures_normales` dépasse le seuil hebdomadaire de 40 h sur une
    semaine — la formule ne référence jamais `heures_normales`.
    """

    # Feature: gains-bruts-vacances-hs, Property 2: Linéarité du montant des heures supplémentaires
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_2_montant_hs_egal_formule_alternative_sur_total_agrege(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, `gains.heures_supplementaires_montant` est égal, au cent
        près (comparaison `==` sur `Decimal`, tolérance nulle —
        règle 01), au produit du taux horaire effectif par le
        multiplicateur légal par la somme agrégée des heures
        supplémentaires des deux semaines constituantes, arrondi selon
        `ROUND_HALF_UP` à deux décimales.

        **Validates: Requirements 3.1, 3.2, 3.6, 3.7, 3.8, 4.1**

        Formule alternative (multiplication directe sur le total agrégé,
        Req 3.1 note « granularité ») :

            heures_supplementaires_totales = Σ semaine.heures_supplementaires
            mult = parametres_annee.heures_supplementaires.multiplicateur
            attendu = quantize(
                heures_supplementaires_totales × taux_horaire_effectif × mult,
                Decimal("0.01"),
                ROUND_HALF_UP,
            )

        Cette formule alternative n'utilise ni `heures_normales` (Req 3.5
        — pas de reclassement, voir aussi le test dédié ci-dessous) ni
        le seuil hebdomadaire (Req 3.4 — transporté pour affichage
        uniquement, jamais consommé par le calcul). Elle couvre
        implicitement le cas de bord Req 3.6 (somme nulle → résultat
        `Decimal("0.00")`). Règle 01 : aucun `float` n'intervient dans le
        calcul de la valeur attendue.
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, _trace = calcul_gains(payroll_input, parametres_annee)

        heures_supplementaires_totales = sum(
            (s.heures_supplementaires for s in payroll_input.heures_par_semaine),
            start=Decimal("0"),
        )
        mult = parametres_annee.heures_supplementaires.multiplicateur
        attendu = (
            heures_supplementaires_totales
            * payroll_input.taux_horaire_effectif
            * mult
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert gains.heures_supplementaires_montant == attendu

    # Feature: gains-bruts-vacances-hs, Property 2: Linéarité du montant des heures supplémentaires
    @pytest.mark.property
    @given(
        paire=_st_paire_heures_normales_excedentaires(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_2_absence_de_reclassement_heures_normales_excedentaires(
        self,
        paire,
        parametres_annee,
    ) -> None:
        """*Pour tout* couple `(pi, pi_modifie)` qui ne diffère que par
        `heures_par_semaine[0].heures_normales` poussée strictement
        au-delà de 40 h, `heures_supplementaires_montant` reste
        **identique** entre les deux appels : le moteur ne reclasse
        jamais une portion de `heures_normales` excédentaire en heures
        supplémentaires (Req 3.5, Req 4.2, Req 4.3).

        **Validates: Requirements 3.5, 4.2, 4.3**

        La formule de l'étape 2 (design §Components §2) ne référence à
        aucun moment `heures_normales` : ce test rend cette absence de
        dépendance observable, indépendamment de la formule alternative
        du test précédent.
        """
        from payroll_engine.gains_bruts import calcul_gains

        payroll_input, payroll_input_modifie = paire

        gains_base, _trace_base = calcul_gains(payroll_input, parametres_annee)
        gains_modifie, _trace_modifiee = calcul_gains(
            payroll_input_modifie, parametres_annee
        )

        assert (
            gains_modifie.heures_supplementaires_montant
            == gains_base.heures_supplementaires_montant
        )


# ---------------------------------------------------------------------------
# 2.4 — Monotonie du brut vs heures normales (Property 4)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1/2.2/2.3 : l'import
# de `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


@st.composite
def _st_paire_heures_normales_avec_delta(
    draw: st.DrawFn,
    delta_strategy: st.SearchStrategy[Decimal],
) -> tuple[object, object, Decimal]:
    """Génère un triplet `(pi_a, pi_b, delta)` où `pi_b` ne diffère de
    `pi_a` que par l'ajout de `delta` sur
    `heures_par_semaine[0].heures_normales`.

    Utilisé par la Property 4 (monotonie du brut vs heures normales,
    design §Correctness Properties 4 ; §Components §2 étape 1). `delta`
    est tiré depuis `delta_strategy` — strictement positif pour le test
    de monotonie proprement dit, ou fixé à `Decimal("0")` pour le test
    d'égalité stricte (conséquence de la linéarité). `heures_par_semaine`
    étant un tuple de modèles Pydantic `frozen=True`, la modification
    passe par `model_copy(update=...)` (sur `HeuresParSemaine` puis sur
    `PayrollInput`), à l'image de `_st_paire_heures_normales_excedentaires`
    (tâche 2.3).

    La borne supérieure du `delta` (`Decimal("50")`, imposée par
    l'appelant) est choisie pour garantir
    `heures_normales(pi_a) + delta <= Decimal("168")` compte tenu de la
    borne haute `Decimal("60")` de `st_heures_par_semaine()` (contrat
    `HeuresParSemaine.heures_normales`, `le=Decimal("168")`).
    """
    pi_a = draw(st_payroll_input())
    delta = draw(delta_strategy)
    semaine_0 = pi_a.heures_par_semaine[0]
    semaine_0_modifiee = semaine_0.model_copy(
        update={"heures_normales": semaine_0.heures_normales + delta}
    )
    pi_b = pi_a.model_copy(
        update={
            "heures_par_semaine": (
                semaine_0_modifiee,
                *pi_a.heures_par_semaine[1:],
            )
        }
    )
    return pi_a, pi_b, delta


class TestMonotonieHeuresNormales:
    """Property 4 — monotonie du brut vs heures normales.

    Design (§Correctness Properties 4 ; §Components §2 étape 1). Pour
    deux `PayrollInput` identiques sauf que la somme des
    `heures_normales` de `pi_b` est strictement supérieure à celle de
    `pi_a` (à taux horaire, taux vacances et jours fériés égaux),
    `calcul_gains(pi_b, ...).gains.brut_total >=
    calcul_gains(pi_a, ...).gains.brut_total`. Une augmentation des
    heures normales ne peut jamais diminuer le brut (conséquence de la
    linéarité du salaire régulier — Property 1 — et de la
    non-négativité du taux horaire).

    Un second test vérifie que l'égalité **stricte** tient lorsque le
    `delta` est `Decimal("0")` — conséquence directe de la linéarité :
    `pi_a` et `pi_b` sont alors structurellement identiques et
    produisent le même brut au sens `==`.
    """

    # Feature: gains-bruts-vacances-hs, Property 4: Monotonie du brut vs heures normales
    @pytest.mark.property
    @given(
        triplet=_st_paire_heures_normales_avec_delta(
            delta_strategy=st.decimals(
                min_value=Decimal("0.01"),
                max_value=Decimal("50"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_4_brut_total_croissant_ou_egal_quand_heures_normales_augmentent(
        self,
        triplet,
        parametres_annee,
    ) -> None:
        """*Pour tout* couple `(pi_a, pi_b)` qui ne diffère que par
        `heures_par_semaine[0].heures_normales` de `pi_b` strictement
        supérieure à celle de `pi_a`,
        `calcul_gains(pi_b).gains.brut_total >=
        calcul_gains(pi_a).gains.brut_total`.

        **Validates: Requirements 2.1, 4.1**

        La comparaison est faite sur `Decimal` (règle 01, tolérance
        nulle sur l'opérateur `>=`). Le taux horaire, le taux de
        vacances, les jours fériés manuels et la seconde semaine
        constituante restent strictement identiques entre `pi_a` et
        `pi_b` — seule la variable étudiée (heures normales de la
        première semaine) change.
        """
        from payroll_engine.gains_bruts import calcul_gains

        pi_a, pi_b, _delta = triplet

        gains_a, _trace_a = calcul_gains(pi_a, parametres_annee)
        gains_b, _trace_b = calcul_gains(pi_b, parametres_annee)

        assert gains_b.brut_total >= gains_a.brut_total

    # Feature: gains-bruts-vacances-hs, Property 4: Monotonie du brut vs heures normales
    @pytest.mark.property
    @given(
        triplet=_st_paire_heures_normales_avec_delta(
            delta_strategy=st.just(Decimal("0"))
        ),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_4_egalite_stricte_du_brut_total_quand_delta_nul(
        self,
        triplet,
        parametres_annee,
    ) -> None:
        """*Pour tout* couple `(pi_a, pi_b)` construit avec un `delta`
        égal à `Decimal("0")` sur `heures_par_semaine[0].heures_normales`,
        `calcul_gains(pi_b).gains.brut_total ==
        calcul_gains(pi_a).gains.brut_total` (égalité stricte, pas
        seulement `>=`).

        **Validates: Requirements 2.1, 4.1**

        Conséquence directe de la linéarité (Property 1) : un `delta`
        nul laisse `pi_b` structurellement identique à `pi_a`
        (`heures_normales + Decimal("0") == heures_normales`), donc les
        deux appels à `calcul_gains` doivent produire le même
        `brut_total` au sens `==` sur `Decimal` (règle 01).
        """
        from payroll_engine.gains_bruts import calcul_gains

        pi_a, pi_b, delta = triplet
        assert delta == Decimal("0")

        gains_a, _trace_a = calcul_gains(pi_a, parametres_annee)
        gains_b, _trace_b = calcul_gains(pi_b, parametres_annee)

        assert gains_b.brut_total == gains_a.brut_total


# ---------------------------------------------------------------------------
# 2.5 — Monotonie du brut vs heures supplémentaires (Property 5)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1/2.2/2.3/2.4 :
# l'import de `calcul_gains` reste local à chaque test,
# `payroll_engine/gains_bruts.py` n'existant pas encore (tâches 5.1/5.2).


@st.composite
def _st_paire_heures_supplementaires_avec_delta(
    draw: st.DrawFn,
    delta_strategy: st.SearchStrategy[Decimal],
) -> tuple[object, object, Decimal]:
    """Génère un triplet `(pi_a, pi_b, delta)` où `pi_b` ne diffère de
    `pi_a` que par l'ajout de `delta` sur
    `heures_par_semaine[0].heures_supplementaires`.

    Utilisé par la Property 5 (monotonie du brut vs heures
    supplémentaires, design §Correctness Properties 5 ;
    §Components §2 étape 2) — même invariant que la Property 4
    (tâche 2.4), sur `heures_supplementaires` cette fois, à taux
    horaire, taux vacances, jours fériés et multiplicateur égaux entre
    `pi_a` et `pi_b`. `delta` est tiré depuis `delta_strategy` —
    strictement positif pour le test de monotonie proprement dit, ou
    fixé à `Decimal("0")` pour le test d'égalité stricte (conséquence
    de la linéarité — Property 2). `heures_par_semaine` étant un tuple
    de modèles Pydantic `frozen=True`, la modification passe par
    `model_copy(update=...)` (sur `HeuresParSemaine` puis sur
    `PayrollInput`), à l'image de `_st_paire_heures_normales_avec_delta`
    (tâche 2.4).

    La borne supérieure du `delta` (`Decimal("50")`, imposée par
    l'appelant) est choisie pour garantir
    `heures_supplementaires(pi_a) + delta <= Decimal("168")` compte
    tenu de la borne haute `Decimal("60")` de `st_heures_par_semaine()`
    (contrat `HeuresParSemaine.heures_supplementaires`,
    `le=Decimal("168")`).
    """
    pi_a = draw(st_payroll_input())
    delta = draw(delta_strategy)
    semaine_0 = pi_a.heures_par_semaine[0]
    semaine_0_modifiee = semaine_0.model_copy(
        update={"heures_supplementaires": semaine_0.heures_supplementaires + delta}
    )
    pi_b = pi_a.model_copy(
        update={
            "heures_par_semaine": (
                semaine_0_modifiee,
                *pi_a.heures_par_semaine[1:],
            )
        }
    )
    return pi_a, pi_b, delta


class TestMonotonieHeuresSupp:
    """Property 5 — monotonie du brut vs heures supplémentaires.

    Design (§Correctness Properties 5 ; §Components §2 étape 2). Pour
    deux `PayrollInput` identiques sauf que la somme des
    `heures_supplementaires` de `pi_b` est strictement supérieure à
    celle de `pi_a` (à taux horaire, taux vacances, jours fériés et
    multiplicateur égaux),
    `calcul_gains(pi_b, ...).gains.brut_total >=
    calcul_gains(pi_a, ...).gains.brut_total`. Une augmentation des
    heures supplémentaires ne peut jamais diminuer le brut (conséquence
    de la linéarité du montant des heures supplémentaires — Property 2
    — et de la positivité du multiplicateur). Cette augmentation se
    propage aussi à l'indemnité de vacances via la `Base_Vacances`
    (design §Components §2 étape 3-4), ce qui ne fait que renforcer la
    monotonie (l'indemnité de vacances est elle-même non-décroissante
    en la `Base_Vacances`, à taux de vacances constant et non négatif).

    Un second test vérifie que l'égalité **stricte** tient lorsque le
    `delta` est `Decimal("0")` — conséquence directe de la linéarité :
    `pi_a` et `pi_b` sont alors structurellement identiques et
    produisent le même brut au sens `==`.
    """

    # Feature: gains-bruts-vacances-hs, Property 5: Monotonie du brut vs heures supplémentaires
    @pytest.mark.property
    @given(
        triplet=_st_paire_heures_supplementaires_avec_delta(
            delta_strategy=st.decimals(
                min_value=Decimal("0.01"),
                max_value=Decimal("50"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_5_brut_total_croissant_ou_egal_quand_heures_supplementaires_augmentent(
        self,
        triplet,
        parametres_annee,
    ) -> None:
        """*Pour tout* couple `(pi_a, pi_b)` qui ne diffère que par
        `heures_par_semaine[0].heures_supplementaires` de `pi_b`
        strictement supérieure à celle de `pi_a`,
        `calcul_gains(pi_b).gains.brut_total >=
        calcul_gains(pi_a).gains.brut_total`.

        **Validates: Requirements 3.1, 4.1**

        La comparaison est faite sur `Decimal` (règle 01, tolérance
        nulle sur l'opérateur `>=`). Le taux horaire, le taux de
        vacances, les jours fériés manuels, le multiplicateur légal
        (dérivé de `parametres_annee`, identique pour les deux appels)
        et la seconde semaine constituante restent strictement
        identiques entre `pi_a` et `pi_b` — seule la variable étudiée
        (heures supplémentaires de la première semaine) change.

        Note (design §Correctness Properties 5) : la borne inférieure
        formelle liée à l'indemnité de vacances qui s'ajoute au montant
        HS via la `Base_Vacances` (`delta × taux × multiplicateur ×
        (1 + taux_vacances)`, à une marge de rounding près) n'est pas
        assertée directement ici pour éviter tout faux positif lié au
        double arrondissement en cascade (arrondi de
        `heures_supplementaires_montant`, puis arrondi de
        `vacances` calculé sur une `Base_Vacances` qui inclut ce
        premier montant déjà arrondi). La monotonie au sens `>=` est la
        propriété assertée — elle est la conséquence directe et exacte
        de la linéarité (Property 2) et de la non-décroissance de
        l'arrondissement `ROUND_HALF_UP` et de la multiplication par un
        taux de vacances non négatif.
        """
        from payroll_engine.gains_bruts import calcul_gains

        pi_a, pi_b, _delta = triplet

        gains_a, _trace_a = calcul_gains(pi_a, parametres_annee)
        gains_b, _trace_b = calcul_gains(pi_b, parametres_annee)

        assert gains_b.brut_total >= gains_a.brut_total

    # Feature: gains-bruts-vacances-hs, Property 5: Monotonie du brut vs heures supplémentaires
    @pytest.mark.property
    @given(
        triplet=_st_paire_heures_supplementaires_avec_delta(
            delta_strategy=st.just(Decimal("0"))
        ),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_5_egalite_stricte_du_brut_total_quand_delta_nul(
        self,
        triplet,
        parametres_annee,
    ) -> None:
        """*Pour tout* couple `(pi_a, pi_b)` construit avec un `delta`
        égal à `Decimal("0")` sur
        `heures_par_semaine[0].heures_supplementaires`,
        `calcul_gains(pi_b).gains.brut_total ==
        calcul_gains(pi_a).gains.brut_total` (égalité stricte, pas
        seulement `>=`).

        **Validates: Requirements 3.1, 4.1**

        Conséquence directe de la linéarité (Property 2) : un `delta`
        nul laisse `pi_b` structurellement identique à `pi_a`
        (`heures_supplementaires + Decimal("0") ==
        heures_supplementaires`), donc les deux appels à
        `calcul_gains` doivent produire le même `brut_total` au sens
        `==` sur `Decimal` (règle 01).
        """
        from payroll_engine.gains_bruts import calcul_gains

        pi_a, pi_b, delta = triplet
        assert delta == Decimal("0")

        gains_a, _trace_a = calcul_gains(pi_a, parametres_annee)
        gains_b, _trace_b = calcul_gains(pi_b, parametres_annee)

        assert gains_b.brut_total == gains_a.brut_total


# ---------------------------------------------------------------------------
# 2.6 — Identité comptable du brut total (Property 3)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1-2.5 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


class TestIdentiteComptableBrut:
    """Property 3 — identité comptable du brut total.

    Design (§Correctness Properties 3 ; §Components §2 étape 5,
    §Components §3). Pour tout `PayrollInput` valide et tout
    `ParametresAnnee` valide, le brut total retourné par `calcul_gains`
    est exactement égal à la somme des quatre composantes qui le
    constituent : `salaire_regulier`, `heures_supplementaires_montant`,
    `jours_feries_manuels` et `vacances`.

    Comparaison stricte `==` sur `Decimal` — tolérance nulle (règle 01).
    L'identité tient **après** arrondissement à 2 décimales sur chaque
    composante : la somme exacte de quatre `Decimal` déjà quantifiés à
    2 décimales a naturellement au plus 2 décimales (Req 6.4), donc
    aucun ré-arrondissement supplémentaire n'est nécessaire ni permis
    sur `brut_total` lui-même.
    """

    # Feature: gains-bruts-vacances-hs, Property 3: Identité comptable du brut total
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_3_brut_total_egal_a_la_somme_des_quatre_composantes(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide,
        `gains.brut_total == gains.salaire_regulier +
        gains.heures_supplementaires_montant +
        gains.jours_feries_manuels + gains.vacances`.

        **Validates: Requirements 6.1, 6.4, 6.5**

        Comparaison `==` sur `Decimal` (règle 01, tolérance nulle) :
        aucune approximation n'est tolérée entre le brut total et la
        somme de ses composantes, quel que soit le nombre de décimales
        intermédiaires produites par les étapes de calcul en amont
        (chaque composante étant déjà quantifiée à 2 décimales avant
        cette sommation — Req 6.4).
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, _trace = calcul_gains(payroll_input, parametres_annee)

        assert gains.brut_total == (
            gains.salaire_regulier
            + gains.heures_supplementaires_montant
            + gains.jours_feries_manuels
            + gains.vacances
        )


# ---------------------------------------------------------------------------
# 2.7 — Forme des composantes monétaires (Property 6)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1-2.6 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


class TestFormeComposantes:
    """Property 6 — forme des composantes monétaires.

    Design (§Correctness Properties 6 ; §Components §4). Pour chaque
    composante monétaire `v` de `GainsDecomposes`
    (`salaire_regulier`, `heures_supplementaires_montant`, `vacances`,
    `jours_feries_manuels`, `brut_total`), quatre conditions doivent
    tenir simultanément :

    - `isinstance(v, Decimal)` (règle 01 — aucun `float`) ;
    - `v == v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`
      (arrondi à 2 décimales, mode `ROUND_HALF_UP` — TP-1015.G) ;
    - `v >= Decimal("0")` (non-négativité, contrat `GainsDecomposes`) ;
    - `v.is_finite()` (ni `NaN` ni infini).

    Un second test étend la vérification de type `Decimal` et de
    finitude aux valeurs des trois dictionnaires de la trace
    (`trace.parametres_utilises`, `trace.entrees`,
    `trace.sous_totaux`) — sans les contraintes de quantification à 2
    décimales ni de non-négativité, ces dictionnaires contenant aussi
    des heures et des taux qui ne sont pas des montants monétaires
    (design §Correctness Properties 6).
    """

    # Feature: gains-bruts-vacances-hs, Property 6: Forme des composantes monétaires
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_6_composantes_gains_decomposes_sont_des_montants_valides(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, chacune des cinq composantes monétaires de
        `GainsDecomposes` (`salaire_regulier`,
        `heures_supplementaires_montant`, `vacances`,
        `jours_feries_manuels`, `brut_total`) est un `Decimal` fini,
        non négatif, déjà arrondi à 2 décimales selon `ROUND_HALF_UP`.

        **Validates: Requirements 2.3, 2.5, 3.7, 3.8, 5.6, 6.1, 6.5**
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, _trace = calcul_gains(payroll_input, parametres_annee)

        composantes = (
            gains.salaire_regulier,
            gains.heures_supplementaires_montant,
            gains.vacances,
            gains.jours_feries_manuels,
            gains.brut_total,
        )

        for v in composantes:
            assert isinstance(v, Decimal)
            assert v == v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            assert v >= Decimal("0")
            assert v.is_finite()

    # Feature: gains-bruts-vacances-hs, Property 6: Forme des composantes monétaires
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_6_valeurs_des_dictionnaires_de_trace_sont_des_decimal_finis(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, chaque valeur des trois dictionnaires
        `trace.parametres_utilises`, `trace.entrees` et
        `trace.sous_totaux` est un `Decimal` fini.

        **Validates: Requirements 7.1, 7.2, 8.7, 12.5**

        Contrairement aux cinq composantes de `GainsDecomposes`
        vérifiées par le test précédent, ces dictionnaires contiennent
        aussi des heures et des taux (ex. `taux_horaire_effectif`,
        `heures_normales_totales`, `multiplicateur_heures_supp`) qui ne
        sont pas des montants monétaires : la contrainte de
        quantification à 2 décimales et de non-négativité ne leur est
        donc pas appliquée ici (design §Correctness Properties 6).
        """
        from payroll_engine.gains_bruts import calcul_gains

        _gains, trace = calcul_gains(payroll_input, parametres_annee)

        for valeur in (
            *trace.parametres_utilises.values(),
            *trace.entrees.values(),
            *trace.sous_totaux.values(),
        ):
            assert isinstance(valeur, Decimal)
            assert valeur.is_finite()


# ---------------------------------------------------------------------------
# 2.8 — Transport strict (Property 7, 8)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1-2.7 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


class TestTransportStrict:
    """Property 7, 8 — transport strict de `jours_feries_manuels`, du
    multiplicateur et du seuil des heures supplémentaires.

    Design (§Correctness Properties 7, 8 ; §Components §3, §Components
    §5.2). Trois valeurs traversent `calcul_gains` sans aucune
    transformation ni ré-arrondissement : `jours_feries_manuels` (recopié
    depuis `payroll_input` vers `gains`), `multiplicateur_heures_supp` et
    `seuil_heures_supp_hebdo` (recopiés depuis
    `parametres_annee.heures_supplementaires` vers `gains`). Les trois
    comparaisons sont des égalités strictes `Decimal.__eq__` (règle 01,
    tolérance nulle) — aucune tolérance d'arrondi n'est admise puisqu'il
    ne s'agit pas d'un calcul mais d'un simple transport de valeur.
    """

    # Feature: gains-bruts-vacances-hs, Property 7: Transport strict de jours_feries_manuels
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_7_jours_feries_manuels_transporte_sans_transformation(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, `gains.jours_feries_manuels == payroll_input.jours_feries_manuels`.

        **Validates: Requirements 3.3, 3.4, 6.2, 9.1, 9.2**

        Comparaison `==` sur `Decimal` (règle 01, tolérance nulle) : la
        valeur saisie manuellement dans `payroll_input` est recopiée
        telle quelle dans `gains`, sans aucun ré-arrondissement ni
        aucune autre transformation (design §Components §3).
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, _trace = calcul_gains(payroll_input, parametres_annee)

        assert gains.jours_feries_manuels == payroll_input.jours_feries_manuels

    # Feature: gains-bruts-vacances-hs, Property 8: Transport strict du multiplicateur et du seuil
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_8_multiplicateur_et_seuil_transportes_sans_transformation(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide,
        `gains.multiplicateur_heures_supp ==
        parametres_annee.heures_supplementaires.multiplicateur` et
        `gains.seuil_heures_supp_hebdo ==
        parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures`.

        **Validates: Requirements 7.4, 7.6, 9.1, 9.2**

        Comparaisons `==` sur `Decimal` (règle 01, tolérance nulle) : les
        deux valeurs sont lues exclusivement dans
        `parametres_annee.heures_supplementaires` (règle 05 — aucune
        valeur fiscale codée en dur) et recopiées telles quelles dans
        `gains`, pour affichage sur le bulletin de paie (design
        §Components §5.2), sans jamais être ré-arrondies ni transformées.
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, _trace = calcul_gains(payroll_input, parametres_annee)

        assert (
            gains.multiplicateur_heures_supp
            == parametres_annee.heures_supplementaires.multiplicateur
        )
        assert (
            gains.seuil_heures_supp_hebdo
            == parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures
        )


# ---------------------------------------------------------------------------
# 2.9 — Trace : source et métadonnées d'arrondissement (Property 12, 16)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1-2.8 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


class TestTraceSourceMetadonnees:
    """Property 12, 16 — conformité de `trace.source` à la liste blanche et
    cohérence des métadonnées d'arrondissement dans la trace.

    Design (§Correctness Properties 12, 16 ; §Components §5.1, §5.5). La
    première propriété vérifie que la `CalculationTrace` retournée par
    `calcul_gains` référence bien `TP-1015.G` (règle 02, liste blanche de
    `models.trace.CalculationTrace`) avec l'année correcte encodée à la
    fois dans la chaîne `source` et dans le champ `annee`. La seconde
    propriété vérifie que les métadonnées d'arrondissement de la trace
    reflètent exactement le mode et la précision réellement appliqués par
    `calcul_gains` (`ROUND_HALF_UP`, 2 décimales — règle 01), et que
    `trace.resultat` est bien le brut total retourné.
    """

    # Feature: gains-bruts-vacances-hs, Property 12: Conformité de trace.source à la liste blanche
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_12_trace_source_conforme_a_la_liste_blanche_tp_1015_g(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, la trace retournée par `calcul_gains` satisfait
        simultanément :

        - `trace.source` matche `^TP-1015\\.G \\d{4}(, section .+)?$` ;
        - l'année encodée dans `trace.source` est égale à
          `payroll_input.pay_period.annee_fiscale` ;
        - `trace.annee == payroll_input.pay_period.annee_fiscale` ;
        - `trace.juridiction == Juridiction.QUEBEC` ;
        - `trace.section` est une chaîne non vide.

        **Validates: Requirements 7.5, 8.1, 8.2, 8.6, 11.8**

        Design (§Correctness Properties 12) : la source doit référencer
        `TP-1015.G` (guide de retenue, section « salaire brut, heures
        supplémentaires et indemnité de vacances ») — pas `TP-1015.F`
        (retenues d'impôt) ni aucune autre entrée de la liste blanche de
        `CalculationTrace` (règle 02). L'année encodée dans la chaîne
        `source` doit correspondre exactement à celle de la période de
        paie, pas une année codée en dur.
        """
        from payroll_engine.gains_bruts import calcul_gains

        _gains, trace = calcul_gains(payroll_input, parametres_annee)

        pattern = re.compile(r"^TP-1015\.G (\d{4})(, section .+)?$")
        correspondance = pattern.match(trace.source)
        assert correspondance is not None

        annee_encodee = int(correspondance.group(1))
        assert annee_encodee == payroll_input.pay_period.annee_fiscale
        assert trace.annee == payroll_input.pay_period.annee_fiscale
        assert trace.juridiction == Juridiction.QUEBEC
        assert trace.section != ""

    # Feature: gains-bruts-vacances-hs, Property 16: Cohérence des métadonnées d'arrondissement dans la trace
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_16_metadonnees_arrondissement_coherentes_avec_le_resultat(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide,
        `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`,
        `trace.precision_arrondissement == 2` et
        `trace.resultat == gains.brut_total`.

        **Validates: Requirements 7.5, 8.1, 8.2, 8.6, 11.8**

        Design (§Correctness Properties 16) : les métadonnées
        d'arrondissement exposées dans la trace ne sont pas de simples
        constantes déclaratives — elles doivent refléter exactement le
        mode et la précision réellement appliqués par `_arrondir`
        (`ROUND_HALF_UP`, `Decimal("0.01")` — règle 01), et
        `trace.resultat` doit être identique, au sens `==` sur `Decimal`
        (tolérance nulle), au `brut_total` effectivement retourné dans
        `GainsDecomposes`.
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, trace = calcul_gains(payroll_input, parametres_annee)

        assert trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP
        assert trace.precision_arrondissement == 2
        assert trace.resultat == gains.brut_total


# ---------------------------------------------------------------------------
# 2.10 — Trace : entrées, sous-totaux, paramètres utilisés (Property 13, 14, 15)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1-2.9 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2).


class TestTraceContenu:
    """Property 13, 14, 15 — contenu de `trace.entrees`, contenu et ordre de
    `trace.sous_totaux`, contenu de `trace.parametres_utilises`.

    Design (§Correctness Properties 13, 14, 15 ; §Components §5.2, §5.3,
    §5.4). Trois propriétés distinctes couvrant les trois dictionnaires de
    la `CalculationTrace` retournée par `calcul_gains` :

    - `trace.entrees` — exactement quatre clés, les agrégations d'entrée
      consommées par le calcul (Req 8.4) ;
    - `trace.sous_totaux` — exactement quatre clés, **dans un ordre
      précis** (Req 8.5), reflétant les étapes intermédiaires du calcul ;
    - `trace.parametres_utilises` — exactement deux clés, les paramètres
      fiscaux effectivement consommés (Req 8.3) — le seuil hebdomadaire
      des heures supplémentaires n'y figure PAS puisqu'il est transporté
      exclusivement via `GainsDecomposes.seuil_heures_supp_hebdo`
      (Property 8, tâche 2.8), jamais consommé par la formule de
      `calcul_gains` elle-même.
    """

    # Feature: gains-bruts-vacances-hs, Property 13: Contenu de trace.entrees
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_13_trace_entrees_contient_les_quatre_cles_attendues(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, `trace.entrees` contient exactement les quatre clés
        `{heures_normales_totales, heures_supplementaires_totales,
        taux_horaire_effectif, jours_feries_manuels}`, chacune associée à
        la valeur agrégée correspondante.

        **Validates: Requirements 5.1, 5.5, 5.8, 8.4**

        Les deux totaux (`heures_normales_totales`,
        `heures_supplementaires_totales`) sont recalculés ici par le même
        agrégat que celui utilisé par les Property 1 et 2 (tâches 2.2,
        2.3) : la somme sur les deux semaines constituantes de
        `payroll_input.heures_par_semaine`. `taux_horaire_effectif` et
        `jours_feries_manuels` sont recopiés tels quels depuis
        `payroll_input` (aucun calcul).
        """
        from payroll_engine.gains_bruts import calcul_gains

        _gains, trace = calcul_gains(payroll_input, parametres_annee)

        heures_normales_totales = sum(
            (s.heures_normales for s in payroll_input.heures_par_semaine),
            start=Decimal("0"),
        )
        heures_supplementaires_totales = sum(
            (s.heures_supplementaires for s in payroll_input.heures_par_semaine),
            start=Decimal("0"),
        )

        assert set(trace.entrees.keys()) == {
            "heures_normales_totales",
            "heures_supplementaires_totales",
            "taux_horaire_effectif",
            "jours_feries_manuels",
        }
        assert trace.entrees["heures_normales_totales"] == heures_normales_totales
        assert (
            trace.entrees["heures_supplementaires_totales"]
            == heures_supplementaires_totales
        )
        assert (
            trace.entrees["taux_horaire_effectif"]
            == payroll_input.taux_horaire_effectif
        )
        assert (
            trace.entrees["jours_feries_manuels"]
            == payroll_input.jours_feries_manuels
        )

    # Feature: gains-bruts-vacances-hs, Property 14: Contenu et ordre de trace.sous_totaux
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_14_trace_sous_totaux_ordre_exact_et_valeurs_coherentes(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide,
        `list(trace.sous_totaux.keys()) == ["salaire_regulier",
        "heures_supplementaires_montant", "base_vacances", "vacances"]`
        (ordre exact, pas seulement même ensemble de clés), et les
        valeurs associées sont cohérentes avec les composantes de
        `gains` et avec `base_vacances = salaire_regulier +
        heures_supplementaires_montant + jours_feries_manuels`.

        **Validates: Requirements 5.5, 7.3, 8.5**

        L'ordre exact est vérifié par comparaison de listes (`==` sur
        `list`, pas `set`) : `sous_totaux` documente les étapes
        intermédiaires du calcul dans l'ordre où elles sont produites
        (design §Components §2 étapes 1, 2, 3, 4).
        """
        from payroll_engine.gains_bruts import calcul_gains

        gains, trace = calcul_gains(payroll_input, parametres_annee)

        assert list(trace.sous_totaux.keys()) == [
            "salaire_regulier",
            "heures_supplementaires_montant",
            "base_vacances",
            "vacances",
        ]
        assert trace.sous_totaux["salaire_regulier"] == gains.salaire_regulier
        assert (
            trace.sous_totaux["heures_supplementaires_montant"]
            == gains.heures_supplementaires_montant
        )
        assert trace.sous_totaux["vacances"] == gains.vacances
        assert trace.sous_totaux["base_vacances"] == (
            gains.salaire_regulier
            + gains.heures_supplementaires_montant
            + gains.jours_feries_manuels
        )

    # Feature: gains-bruts-vacances-hs, Property 15: Contenu de trace.parametres_utilises
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_15_trace_parametres_utilises_contient_exactement_deux_cles(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide,
        `set(trace.parametres_utilises.keys()) ==
        {"multiplicateur_heures_supp", "taux_vacances"}`, avec des
        valeurs égales respectivement à
        `parametres_annee.heures_supplementaires.multiplicateur` et
        `payroll_input.taux_vacances`. La clé `seuil_heures_supp_hebdo`
        n'y figure PAS.

        **Validates: Requirements 8.3, 13.2**

        Design (§Correctness Properties 15) : le seuil hebdomadaire des
        heures supplémentaires n'est jamais consommé par la formule de
        `calcul_gains` (aucun test de dépassement, aucun reclassement —
        Property 2, tâche 2.3) ; il est transporté uniquement pour
        affichage via `GainsDecomposes.seuil_heures_supp_hebdo`
        (Property 8, tâche 2.8). Sa présence dans
        `trace.parametres_utilises` signalerait à tort qu'il participe
        au calcul du montant.
        """
        from payroll_engine.gains_bruts import calcul_gains

        _gains, trace = calcul_gains(payroll_input, parametres_annee)

        assert set(trace.parametres_utilises.keys()) == {
            "multiplicateur_heures_supp",
            "taux_vacances",
        }
        assert (
            trace.parametres_utilises["multiplicateur_heures_supp"]
            == parametres_annee.heures_supplementaires.multiplicateur
        )
        assert (
            trace.parametres_utilises["taux_vacances"]
            == payroll_input.taux_vacances
        )
        assert "seuil_heures_supp_hebdo" not in trace.parametres_utilises


class TestTraceAutoSuffisante:
    """Property 17 — auto-suffisance de la trace (identité comptable interne).

    Design (§Correctness Properties 17). Un tiers qui n'a accès qu'aux
    contenus de `trace` (sans jamais consulter `gains` ni
    `payroll_input`) doit pouvoir reconstruire le brut total par simple
    relecture des trois dictionnaires `trace.entrees`,
    `trace.sous_totaux` et `trace.parametres_utilises` — c'est l'exigence
    d'audit « en un clic » de la règle 02. Trois identités enchaînées
    sont vérifiées, chacune ne référençant que des clés de `trace` (et
    l'helper local `_arrondir`, seul mécanisme d'arrondissement autorisé
    — règle 01) :

    1. `trace.resultat` == somme des quatre sous-totaux/entrée
       constituant le brut ;
    2. `trace.sous_totaux["vacances"]` == `base_vacances` arrondi ×
       `taux_vacances`, tous deux lus dans la trace ;
    3. `trace.sous_totaux["base_vacances"]` == somme des trois
       composantes antérieures, toutes lues dans la trace.
    """

    # Feature: gains-bruts-vacances-hs, Property 17: Auto-suffisance de la trace
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_17_trace_auto_suffisante_permet_de_recalculer_le_brut(
        self,
        payroll_input,
        parametres_annee,
    ) -> None:
        """*Pour tout* `PayrollInput` valide et tout `ParametresAnnee`
        valide, un tiers peut recalculer le brut à partir des seuls
        contenus de `trace` — sans jamais consulter `gains` ni
        `payroll_input` — via les trois identités suivantes :

            trace.resultat == (
                trace.sous_totaux["salaire_regulier"]
                + trace.sous_totaux["heures_supplementaires_montant"]
                + trace.entrees["jours_feries_manuels"]
                + trace.sous_totaux["vacances"]
            )

            trace.sous_totaux["vacances"] == arrondir(
                trace.sous_totaux["base_vacances"]
                * trace.parametres_utilises["taux_vacances"]
            )

            trace.sous_totaux["base_vacances"] == (
                trace.sous_totaux["salaire_regulier"]
                + trace.sous_totaux["heures_supplementaires_montant"]
                + trace.entrees["jours_feries_manuels"]
            )

        **Validates: Requirements 8.8**

        `arrondir` désigne ici `Decimal.quantize(Decimal("0.01"),
        rounding=ROUND_HALF_UP)` (règle 01) — le même mode et la même
        précision que `trace.mode_arrondissement` /
        `trace.precision_arrondissement` (Property 16, tâche 2.9).
        Toutes les comparaisons sont des égalités strictes sur
        `Decimal` (tolérance nulle).
        """
        from payroll_engine.gains_bruts import calcul_gains

        _gains, trace = calcul_gains(payroll_input, parametres_annee)

        assert trace.resultat == (
            trace.sous_totaux["salaire_regulier"]
            + trace.sous_totaux["heures_supplementaires_montant"]
            + trace.entrees["jours_feries_manuels"]
            + trace.sous_totaux["vacances"]
        )

        assert trace.sous_totaux["vacances"] == (
            trace.sous_totaux["base_vacances"]
            * trace.parametres_utilises["taux_vacances"]
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        assert trace.sous_totaux["base_vacances"] == (
            trace.sous_totaux["salaire_regulier"]
            + trace.sous_totaux["heures_supplementaires_montant"]
            + trace.entrees["jours_feries_manuels"]
        )


# ---------------------------------------------------------------------------
# 2.12 — Extensibilité 6 % et défense en profondeur (Property 18, 19)
# ---------------------------------------------------------------------------
#
# Discipline règle 06 (TDD) inchangée par rapport à 2.1-2.11 : l'import de
# `calcul_gains` reste local à chaque test, `payroll_engine/gains_bruts.py`
# n'existant pas encore (tâches 5.1/5.2). Cette classe clôt la liste des
# 12 sous-tâches (2.1 à 2.12) couvrant les 19 propriétés du design.


def _payroll_input_valide_pour_exemple() -> object:
    """Construit un `PayrollInput` valide et déterministe (test d'exemple).

    Contrairement aux tests `@given` de cette classe (qui tirent leur
    `PayrollInput` de base via `st_payroll_input()`), le test d'exemple
    de la Property 19 n'a besoin que d'une seule instance fixe,
    déterministe et anonymisée (règle 04) — à l'image de
    `_employee_valide()` / `_pay_period_valide()` de
    `tests/models/test_payroll_input.py`. Aucun `float` (règle 01) :
    tous les montants et taux sont construits depuis des `Decimal`.
    """
    from datetime import date, timedelta

    from models.cumuls import CumulsYTD
    from models.employee import Employee
    from models.enums import FrequencePaie
    from models.pay_period import PayPeriod, WeekSegment
    from models.payroll_input import PayrollInput

    date_debut = date(2026, 6, 1)
    date_fin = date(2026, 6, 14)

    employee = Employee(
        id="EMP001",
        nom_affichage="Monitrice EMP001",
        date_naissance=date(2005, 6, 15),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Monitrice",
        taux_horaire_base=Decimal("15.75"),
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
        heures_normales=Decimal("40.00"),
        heures_supplementaires=Decimal("0.00"),
    )
    semaine_1 = WeekSegment(
        date_debut=date_debut + timedelta(days=7),
        date_fin=date_fin,
        heures_normales=Decimal("40.00"),
        heures_supplementaires=Decimal("0.00"),
    )
    pay_period = PayPeriod(
        numero_periode=12,
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
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
        ),
        HeuresParSemaine(
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
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
        montant_total_TP1015_3_effectif=Decimal("18952.00"),
        exoneration_TP1015_3_effectif=False,
        retenue_additionnelle_QC_effective=Decimal("0.00"),
        montant_total_TD1_effectif=Decimal("16452.00"),
        exoneration_TD1_effective=False,
        retenue_additionnelle_federale_effective=Decimal("0.00"),
        cumuls_debut=cumuls_debut,
    )


@st.composite
def _st_paire_pi_04_pi_06(draw: st.DrawFn) -> tuple[object, object]:
    """Génère une paire `(pi_04, pi_06)` identiques sauf sur `taux_vacances`.

    Utilisé par la Property 18 (extensibilité au taux 6 %, design
    §Correctness Properties 18 ; §Components §2 étape 0). Un
    `PayrollInput` de base est tiré via `st_payroll_input()` (qui tire
    déjà `taux_vacances` dans `{0.04, 0.06}`), puis `pi_04` et `pi_06`
    sont produits par `model_copy(update={"taux_vacances": ...})` — à
    l'image du patron `model_copy` utilisé par
    `_st_paire_heures_normales_excedentaires` (tâche 2.3) et
    `_st_paire_heures_normales_avec_delta` (tâche 2.4) — afin que
    **tous les autres champs** (heures, taux horaire, jours fériés,
    employé, période) restent strictement identiques entre les deux
    instances.
    """
    pi_base = draw(st_payroll_input())
    pi_04 = pi_base.model_copy(update={"taux_vacances": Decimal("0.04")})
    pi_06 = pi_base.model_copy(update={"taux_vacances": Decimal("0.06")})
    return pi_04, pi_06


class TestExtensibiliteEtDefense:
    """Property 18, 19 — extensibilité au taux 6 % et défense en profondeur.

    Design (§Correctness Properties 18, 19 ; §Components §2 étape 0 ;
    §Error Handling « Défense en profondeur `taux_vacances` »). La
    Property 18 vérifie que la formule d'indemnité de vacances est
    strictement identique pour les deux taux supportés (aucun
    branchement conditionnel : `iv = arrondir(base_vacances × taux)`
    quel que soit `taux ∈ {0.04, 0.06}`). La Property 19 vérifie que le
    seul garde-fou de matrice introduit par cette spec — la défense en
    profondeur sur `taux_vacances` — se déclenche pour toute valeur hors
    de cet ensemble fermé, même lorsque la validation normale de
    `PayrollInput` est contournée via `model_construct` (design
    §Components 8 « Défense en profondeur »).
    """

    # Feature: gains-bruts-vacances-hs, Property 18: Extensibilité au taux 6 %
    @pytest.mark.property
    @given(
        paire=_st_paire_pi_04_pi_06(),
        parametres_annee=st_parametres_annee_2026_qc(),
    )
    @settings_large_input
    def test_property_18_vacances_006_egal_base_vacances_004_fois_006_arrondi(
        self,
        paire,
        parametres_annee,
    ) -> None:
        """*Pour tout* couple `(pi_04, pi_06)` identique sauf sur
        `taux_vacances` (`0.04` pour `pi_04`, `0.06` pour `pi_06`),
        `calcul_gains(pi_06).gains.vacances == arrondir(
        calcul_gains(pi_04).trace.sous_totaux["base_vacances"] ×
        Decimal("0.06"))`.

        **Validates: Requirements 13.1**

        `base_vacances` n'est pas un champ direct de `GainsDecomposes`
        (tâche 2.10) — il est lu dans
        `trace_04.sous_totaux["base_vacances"]`. Puisque `pi_04` et
        `pi_06` ne diffèrent que par `taux_vacances`, `base_vacances`
        est identique pour les deux appels (aucune des étapes 1 à 3 de
        l'algorithme — salaire régulier, heures supplémentaires, base
        vacances — ne dépend de `taux_vacances`) : ce test l'utilise
        indifféremment depuis `trace_04`. La comparaison est une
        égalité stricte sur `Decimal` (règle 01, tolérance nulle) — la
        formule d'arrondissement (`quantize(Decimal("0.01"),
        ROUND_HALF_UP)`) est appliquée exactement une fois, comme le
        ferait `calcul_gains` lui-même, ce qui matérialise l'absence de
        branchement conditionnel entre les deux taux.
        """
        from payroll_engine.gains_bruts import calcul_gains

        pi_04, pi_06 = paire

        gains_04, trace_04 = calcul_gains(pi_04, parametres_annee)
        gains_06, _trace_06 = calcul_gains(pi_06, parametres_annee)

        base_vacances_04 = trace_04.sous_totaux["base_vacances"]
        attendu = (base_vacances_04 * Decimal("0.06")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        assert gains_06.vacances == attendu

    # Feature: gains-bruts-vacances-hs, Property 19: Défense en profondeur taux_vacances
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc(),
        taux_invalide=st.decimals(
            min_value=Decimal("-1000"),
            max_value=Decimal("1000"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        ).filter(lambda t: t not in (Decimal("0.04"), Decimal("0.06"))),
    )
    @settings_large_input
    def test_property_19_taux_vacances_hors_matrice_leve_unsupported(
        self,
        payroll_input,
        parametres_annee,
        taux_invalide,
    ) -> None:
        """*Pour tout* `Decimal` `taux ∉ {Decimal("0.04"), Decimal("0.06")}`
        généré par Hypothesis, et tout `PayrollInput` fabriqué via
        `PayrollInput.model_construct(taux_vacances=taux, ...)`
        (contournement de la validation normale),
        `calcul_gains(pi, parametres_annee)` lève
        `UnsupportedPayrollCase`.

        **Validates: Requirements 10.3, 10.5, 13.3**

        `payroll_input` (valide, tiré normalement via
        `st_payroll_input()`) fournit tous les champs autres que
        `taux_vacances` ; `PayrollInput.model_construct(**{**
        payroll_input.__dict__, "taux_vacances": taux_invalide})`
        court-circuite `_coherence_croisee` (le validateur qui refuse
        déjà `taux_vacances` hors matrice à la construction normale) —
        c'est exactement le patron employé par
        `tests/models/test_payroll_input.py` (ex.
        `test_employee_province_non_quebec_leve_unsupported_en_coherence_croisee`)
        pour démontrer une défense en profondeur indépendante de la
        validation frontière. C'est donc le garde-fou **interne à
        `calcul_gains`** (design §Components §2 étape 0, §Error
        Handling) qui doit détecter et refuser la valeur, puisque
        `PayrollInput.model_construct` ne revalide rien.
        """
        from payroll_engine.gains_bruts import calcul_gains
        from models.payroll_input import PayrollInput

        pi_invalide = PayrollInput.model_construct(
            **{**payroll_input.__dict__, "taux_vacances": taux_invalide}
        )

        with pytest.raises(UnsupportedPayrollCase):
            calcul_gains(pi_invalide, parametres_annee)

    # Feature: gains-bruts-vacances-hs, Property 19: Défense en profondeur taux_vacances
    def test_message_taux_vacances_hors_matrice_cite_la_valeur_et_webras_pdoc(
        self,
        parametres_2026_qc,
    ) -> None:
        """Test d'exemple — le message d'exception de la défense en
        profondeur `taux_vacances` contient la valeur refusée
        (`str(taux)`) et mentionne WebRAS/PDOC (insensible à la casse).

        **Validates: Requirements 10.3, 10.5, 13.3**

        Cohérent avec la Property 16 de `moteur-paie-contrats` (Req
        11.6) et avec le patron déjà appliqué par
        `tests/test_guards.py::TestExceptionMessageContract` : le
        message doit permettre à l'auditeur d'identifier à la fois la
        valeur refusée et l'outil officiel de repli, sans avoir à lire
        le code source de `calcul_gains`.
        """
        from payroll_engine.gains_bruts import calcul_gains
        from models.payroll_input import PayrollInput

        payroll_input = _payroll_input_valide_pour_exemple()
        taux_refuse = Decimal("0.05")
        pi_invalide = PayrollInput.model_construct(
            **{**payroll_input.__dict__, "taux_vacances": taux_refuse}
        )

        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            calcul_gains(pi_invalide, parametres_2026_qc)

        message = str(exc_info.value)
        assert str(taux_refuse) in message, (
            "Le message doit citer la valeur refusée (Req 10.5, "
            f"Property 19). Message reçu : {message!r}"
        )
        message_minuscule = message.lower()
        assert ("webras" in message_minuscule) or ("pdoc" in message_minuscule), (
            "Le message doit renvoyer à WebRAS ou PDOC (Req 13.3, "
            f"Property 19, cohérent avec Property 16 de "
            f"moteur-paie-contrats). Message reçu : {message!r}"
        )
