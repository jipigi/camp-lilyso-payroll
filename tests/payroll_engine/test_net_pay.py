"""Property tests et tests d'exemple pour `payroll_engine/net_pay.py`.

Spec de référence : ``net-cumuls-registre`` — tâche 2.1 (squelette du
fichier et tests transversaux).
Design de référence : ``design.md`` §Testing Strategy, §Correctness
Properties 1 à 7 et §Components §1 (`assembler_paie`), §2
(`_ContributionPaie`).

Ce fichier porte l'ensemble des property tests et tests d'exemple de la
fonction d'orchestration unique ``payroll_engine/net_pay.py::assembler_paie``.
La tâche 2.1 pose le **squelette** : le module docstring, les imports, et
les tests **transversaux** (classe ``TestSignaturePureteDeterminisme``)
qui couvrent la signature exacte, l'absence d'effet de bord à l'import et
la Property 1 (déterminisme et non-mutation). Les tâches suivantes
ajouteront :

- ``TestIdentitesComptables`` — Property 2, 3 (tâche 2.2) ;
- ``TestInvocationStricte`` — Property 4 (tâche 2.3) ;
- ``TestCumulsFin`` — Property 5 (tâche 2.4) ;
- ``TestConstructionFinale`` — Property 6 (tâche 2.5) ;
- ``TestPropagationExceptions`` — Property 7 (tâche 2.6).

Les **7 propriétés** couvertes par ce fichier de test au total (design.md
§Correctness Properties) :

1. **Property 1 — Déterminisme et non-mutation** : deux appels successifs
   d'``assembler_paie`` avec les mêmes arguments produisent deux
   `PayrollResult` égaux au sens `==` ; `payroll_input`/`parametres_annee`
   restent inchangés après l'appel. *(cette tâche)*
2. **Property 2 — Identité brute** : `gains.brut_total == net +
   retenues_employe.total_retenues_employe`.
3. **Property 3 — Identité coût employeur** : `cout_employeur ==
   gains.brut_total + cotisations_employeur.total_cotisations_employeur`.
4. **Property 4 — Invocation stricte sans recalcul** : chaque section du
   `PayrollResult` provient d'un appel direct et inchangé à la fonction
   déjà livrée correspondante.
5. **Property 5 — Cohérence et monotonie de `cumuls_fin`**.
6. **Property 6 — Construction finale fidèle et sans erreur**.
7. **Property 7 — Propagation sans interception des exceptions du
   domaine**.

Discipline règle 06 (TDD — tests avant code) :
``payroll_engine/net_pay.py`` n'existe **pas encore** à ce stade. Comme
``test_charges_patronales.py`` (spec ``charges-patronales``), ce fichier
**importe localement** la fonction sous test (via un helper
``_importer_module_net_pay`` appelé au sein de chaque test) afin que la
**collecte** pytest de ce fichier réussisse même tant que le module cible
est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``payroll_engine.net_pay`` — c'est le
comportement **attendu et correct** (état rouge intentionnel) tant que la
tâche 7.2 (implémentation) n'a pas été réalisée (checkpoint de la tâche 6
du plan).

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison.
Règle 04 : aucune donnée nominative réelle — corpus et générateurs
anonymisés (``EMPnnn``, via ``st_payroll_input()``).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import string
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction, StatutDePaie
from models.exceptions import (  # noqa: F401  (contrats consommés)
    MissingParameterError,
    PayrollDomainError,
)
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.payroll_result import (  # noqa: F401  (contrats consommés)
    CotisationsEmployeur,
    GainsDecomposes,
    PayrollResult,
)
from payroll_engine.assurance_emploi import calcul_ae_employe
from payroll_engine.charges_patronales import assembler_cotisations_employeur
from payroll_engine.gains_bruts import calcul_gains
from payroll_engine.impot_federal import (
    calcul_impot_federal_formule,
    calcul_impot_federal_retenu,
)
from payroll_engine.impot_qc import calcul_impot_qc_formule, calcul_impot_qc_retenu
from payroll_engine.parameters_loader import load_parameters
from payroll_engine.rqap import calcul_rqap_employe
from payroll_engine.rrq import calcul_rrq_employe
from tests.strategies import (
    st_parametres_annee_2026_qc_ca,
    st_parametres_annee_avec_to_fill,
    st_payroll_input,
)

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_charges_patronales.py
# et test_rrq.py). Le nombre d'exemples est piloté par le profil Hypothesis
# actif (voir ``tests/conftest.py`` : dev=15 par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

#: Nom qualifié du module sous test (règle 06 — importé localement pour ne
#: pas faire échouer la collecte tant que la tâche 7.2 n'a pas créé le
#: module).
_NOM_MODULE_CIBLE = "payroll_engine.net_pay"

#: Racine du dépôt — deux niveaux au-dessus de ``tests/payroll_engine/``.
_REPO_ROOT: Path = Path(__file__).parent.parent.parent

#: Chemin du fichier source du module cible, pour l'inspection statique
#: légère de la tâche 2.5 (Req 7.4 — absence de ``model_construct``).
_CHEMIN_NET_PAY: Path = _REPO_ROOT / "payroll_engine" / "net_pay.py"

#: Ordre exact des huit paramètres imposé par Requirement 1 AC1 et par le
#: design §Components §1 (« Signature figée exactement telle qu'énoncée »).
_PARAMETRES_ATTENDUS: tuple[str, ...] = (
    "payroll_input",
    "parametres_annee",
    "id_paie",
    "version",
    "statut",
    "date_creation",
    "date_emission",
    "remplace_par_id",
)

#: Les deux derniers paramètres, et eux seuls, portent une valeur par
#: défaut ``None`` (Req 1.1 — « aucun défaut ajouté au-delà de
#: `date_emission`/`remplace_par_id` »).
_PARAMETRES_AVEC_DEFAUT_NONE: frozenset[str] = frozenset(
    {"date_emission", "remplace_par_id"}
)

#: Les 5 combinaisons *valides* (au sens de la biconditionnelle
#: `statut ⟺ remplace_par_id ⟺ date_emission` déjà portée par le contrat
#: `PayrollResult` — voir ``models/payroll_result.py``
#: `_statut_et_remplacement_coherents` et
#: ``tests/models/test_payroll_result.py`` `_COMBINAISONS_PROPERTY_11`) de
#: `(statut, date_emission_requise, remplace_par_id_requis)`. Utilisée par
#: `_st_arguments_cycle_de_vie_valides` pour ne générer, pour la Property 1,
#: que des arguments de cycle de vie qui permettront à la construction
#: finale du `PayrollResult` de réussir (Req 1.1, 1.2, 1.4).
_COMBINAISONS_CYCLE_DE_VIE_VALIDES: tuple[tuple[StatutDePaie, bool, bool], ...] = (
    (StatutDePaie.BROUILLON, False, False),
    (StatutDePaie.BROUILLON, True, False),
    (StatutDePaie.EMISE, True, False),
    (StatutDePaie.ANNULEE, True, False),
    (StatutDePaie.REMPLACE_PAR, True, True),
)


# ---------------------------------------------------------------------------
# Helpers internes — import local du module cible, génération d'arguments
# de cycle de vie valides.
# ---------------------------------------------------------------------------


def _importer_module_net_pay() -> ModuleType:
    """Importe ``payroll_engine.net_pay`` au moment de l'appel.

    Règle 06 (TDD — tests avant code) : le module cible n'existe pas
    encore. En différant l'import à l'intérieur des tests (plutôt qu'au
    niveau module), la **collecte** pytest de ce fichier reste possible ;
    seule l'**exécution** de chaque test lève ``ModuleNotFoundError`` tant
    que la tâche 7.2 n'a pas créé le module — état rouge attendu et
    correct.
    """
    return importlib.import_module(_NOM_MODULE_CIBLE)


def _st_identifiant(prefixe: str) -> st.SearchStrategy[str]:
    """Chaîne non vide plausible pour ``id_paie`` / ``remplace_par_id``.

    Alphabet restreint (lettres ASCII, chiffres, tiret) pour éviter tout
    caractère de contrôle qui compliquerait le diagnostic d'un test en
    échec ; ``prefixe`` documente l'usage au sein de la valeur générée
    (règle 04 — identifiants fictifs, jamais une donnée nominative).
    """
    alphabet = string.ascii_letters + string.digits + "-"
    return st.text(alphabet=alphabet, min_size=1, max_size=20).map(
        lambda s: f"{prefixe}-{s}"
    )


def _st_datetime_plausible() -> st.SearchStrategy[datetime]:
    """``datetime`` naïf plausible pour ``date_creation`` / ``date_emission``.

    Bornée à une fenêtre large mais raisonnable (2020-2035) — aucune
    signification fiscale, seulement des valeurs de forme requises par le
    contrat ``PayrollResult`` (règle 05 : pas une valeur de paramètre
    fiscal, donc aucune contrainte de provenance ``ParametresAnnee``).
    """
    return st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2035, 12, 31, 23, 59, 59),
    )


@st.composite
def _st_arguments_cycle_de_vie_valides(
    draw: st.DrawFn,
) -> tuple[str, int, StatutDePaie, datetime, datetime | None, str | None]:
    """``(id_paie, version, statut, date_creation, date_emission, remplace_par_id)``
    mutuellement cohérents (design §Correctness Properties 1 : « arguments
    de cycle de vie ... valides »).

    Tire une des cinq combinaisons valides de
    :data:`_COMBINAISONS_CYCLE_DE_VIE_VALIDES` (biconditionnelle statut ⟺
    remplace_par_id ⟺ date_emission déjà portée par le contrat
    ``PayrollResult``) puis complète chaque champ requis par cette
    combinaison. Cela garantit que la construction finale du
    ``PayrollResult`` par ``assembler_paie`` (étape H, design §Components
    §1) ne lève jamais ``ValidationError`` pour ce motif — la Property 1
    ne teste que le déterminisme, pas la matrice de rejet (couverte par la
    Property 6 à la tâche 2.5).
    """
    id_paie = draw(_st_identifiant("PAIE"))
    version = draw(st.integers(min_value=1, max_value=50))
    date_creation = draw(_st_datetime_plausible())
    statut, date_emission_requise, remplace_par_id_requis = draw(
        st.sampled_from(_COMBINAISONS_CYCLE_DE_VIE_VALIDES)
    )
    date_emission = draw(_st_datetime_plausible()) if date_emission_requise else None
    remplace_par_id = (
        draw(_st_identifiant("PAIE")) if remplace_par_id_requis else None
    )
    return id_paie, version, statut, date_creation, date_emission, remplace_par_id


# ---------------------------------------------------------------------------
# 2.1 — Signature, absence d'effet de bord à l'import, déterminisme et
#       non-mutation (Property 1)
# ---------------------------------------------------------------------------


class TestSignaturePureteDeterminisme:
    """Property 1 — déterminisme et non-mutation, plus les tests d'exemple
    de signature exacte et d'import sans effet de bord.

    Design (§Correctness Properties 1 ; §Components §1 « Signature figée
    exactement telle qu'énoncée »).
    """

    def test_exemple_signature_exacte_de_assembler_paie(self) -> None:
        """Test d'exemple — signature exacte (Req 1.1).

        ``assembler_paie`` expose, dans l'ordre, les huit paramètres
        ``(payroll_input, parametres_annee, id_paie, version, statut,
        date_creation, date_emission, remplace_par_id)`` (design
        §Components §1). Seuls ``date_emission`` et ``remplace_par_id``
        portent une valeur par défaut, et cette valeur par défaut est
        ``None`` pour les deux. Vérifié par introspection
        ``inspect.signature``.
        """
        module = _importer_module_net_pay()

        assert hasattr(module, "assembler_paie"), (
            "Le module cible doit exposer `assembler_paie` (Req 1.1)."
        )
        fonction = module.assembler_paie
        signature = inspect.signature(fonction)

        noms_parametres = tuple(signature.parameters)
        assert noms_parametres == _PARAMETRES_ATTENDUS, (
            f"`assembler_paie` doit avoir les paramètres "
            f"{_PARAMETRES_ATTENDUS} dans cet ordre, obtenu {noms_parametres}."
        )

        for nom, parametre in signature.parameters.items():
            assert parametre.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.POSITIONAL_ONLY,
            ), f"`assembler_paie` doit exposer un paramètre positionnel `{nom}`."

            if nom in _PARAMETRES_AVEC_DEFAUT_NONE:
                assert parametre.default is None, (
                    f"`{nom}` doit porter la valeur par défaut `None` "
                    f"(Req 1.1), obtenu {parametre.default!r}."
                )
            else:
                assert parametre.default is inspect.Parameter.empty, (
                    f"`{nom}` ne doit imposer aucune valeur par défaut "
                    f"(Req 1.1), obtenu {parametre.default!r}."
                )

    def test_exemple_import_net_pay_sans_effet_de_bord(self, capsys: Any) -> None:
        """Test d'exemple — l'import du module ne produit aucun effet de
        bord (Req 1.5) : pas d'ouverture de fichier, pas d'appel réseau,
        pas d'écriture sur ``stdout`` / ``stderr`` au moment de l'import.

        Le module est retiré de ``sys.modules`` avant l'import (s'il y
        était déjà chargé) afin de forcer une exécution fraîche de son
        corps — c'est à ce moment-là qu'un éventuel effet de bord au
        niveau module se manifesterait.
        """
        sys.modules.pop(_NOM_MODULE_CIBLE, None)

        module = importlib.import_module(_NOM_MODULE_CIBLE)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert _NOM_MODULE_CIBLE in sys.modules
        assert hasattr(module, "assembler_paie")

    # Feature: net-cumuls-registre, Property 1: Déterminisme et non-mutation
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_1_deux_appels_identiques_produisent_des_resultats_egaux(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput`, `ParametresAnnee` et arguments de
        cycle de vie mutuellement cohérents et valides, deux appels
        successifs à `assembler_paie` avec les mêmes arguments produisent
        deux `PayrollResult` égaux au sens `==`, et `payroll_input` /
        `parametres_annee` restent inchangés après l'appel (comparaison
        `==` avant/après) — aucun état interne persistant, aucune mutation
        des objets `frozen=True` reçus en argument.

        **Validates: Requirements 1.2, 1.4, 16.7**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        payroll_input_avant = payroll_input.model_copy(deep=True)
        parametres_annee_avant = parametres_annee.model_copy(deep=True)

        resultat_1 = module.assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            version,
            statut,
            date_creation,
            date_emission,
            remplace_par_id,
        )
        resultat_2 = module.assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            version,
            statut,
            date_creation,
            date_emission,
            remplace_par_id,
        )

        assert resultat_1 == resultat_2, (
            "`assembler_paie` n'est pas déterministe : deux appels avec "
            f"les mêmes arguments ont produit {resultat_1!r} != {resultat_2!r}."
        )
        assert payroll_input == payroll_input_avant, (
            "`assembler_paie` a muté `payroll_input` (Req 1.4)."
        )
        assert parametres_annee == parametres_annee_avant, (
            "`assembler_paie` a muté `parametres_annee` (Req 1.4)."
        )


# ---------------------------------------------------------------------------
# 2.2 — Identités comptables (Property 2, 3)
# ---------------------------------------------------------------------------


class TestIdentitesComptables:
    """Property 2 (identité brute) et Property 3 (identité coût employeur).

    Design (§Correctness Properties 2, 3 ; §Components §1 étapes E, F).

    Note : `PayrollResult` porte déjà, via son propre
    ``model_validator(mode="after")``, les deux invariants
    ``gains.brut_total == net + retenues_employe.total_retenues_employe``
    et ``cout_employeur == gains.brut_total +
    cotisations_employeur.total_cotisations_employeur`` (Req 4.9, 4.10 de
    ``moteur-paie-contrats``) : si `assembler_paie` calculait `net` ou
    `cout_employeur` de façon incohérente, la construction du
    `PayrollResult` échouerait elle-même avec `ValidationError` avant même
    que ces tests ne puissent asserter quoi que ce soit. Ces tests
    confirment donc (a) que la construction réussit bel et bien pour tout
    `PayrollInput`/`ParametresAnnee` valides — ce qui *implique*
    l'identité — et (b) qu'aucun arrondissement supplémentaire n'a été
    appliqué au-delà de celui déjà porté par les fonctions invoquées : les
    deux opérandes de chaque identité restent des `Decimal` exacts (jamais
    de `float` intermédiaire, règle 01), et l'égalité tient sans aucune
    tolérance (`==` strict sur `Decimal`).
    """

    # Feature: net-cumuls-registre, Property 2: Identité brute
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_2_identite_brute(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput` et `ParametresAnnee` valides, le
        `PayrollResult` produit par `assembler_paie` satisfait
        `gains.brut_total == net + retenues_employe.total_retenues_employe`,
        sans aucun écart (comparaison `==` sur `Decimal`, tolérance nulle
        — règle 01) et sans qu'aucun des deux opérandes ne soit un
        `float`.

        **Validates: Requirements 5.1, 5.3, 5.4, 16.1**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        resultat = module.assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            version,
            statut,
            date_creation,
            date_emission,
            remplace_par_id,
        )

        assert isinstance(resultat.gains.brut_total, Decimal), (
            "`gains.brut_total` doit être un `Decimal`, jamais un `float` "
            f"(règle 01), obtenu {type(resultat.gains.brut_total)!r}."
        )
        assert isinstance(resultat.net, Decimal), (
            "`net` doit être un `Decimal`, jamais un `float` (règle 01), "
            f"obtenu {type(resultat.net)!r}."
        )
        assert isinstance(
            resultat.retenues_employe.total_retenues_employe, Decimal
        ), (
            "`retenues_employe.total_retenues_employe` doit être un "
            f"`Decimal`, obtenu "
            f"{type(resultat.retenues_employe.total_retenues_employe)!r}."
        )

        assert resultat.gains.brut_total == (
            resultat.net + resultat.retenues_employe.total_retenues_employe
        ), (
            "Identité brute violée (Req 5.1, 5.3) : "
            f"gains.brut_total = {resultat.gains.brut_total} != "
            f"net + total_retenues_employe = "
            f"{resultat.net + resultat.retenues_employe.total_retenues_employe}."
        )

    # Feature: net-cumuls-registre, Property 3: Identité coût employeur
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_3_identite_cout_employeur(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput` et `ParametresAnnee` valides, le
        `PayrollResult` produit par `assembler_paie` satisfait
        `cout_employeur == gains.brut_total +
        cotisations_employeur.total_cotisations_employeur`, sans aucun
        écart (comparaison `==` sur `Decimal`, tolérance nulle — règle 01)
        et sans qu'aucun des deux opérandes ne soit un `float`.

        **Validates: Requirements 5.2, 5.3, 5.4, 16.2**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        resultat = module.assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            version,
            statut,
            date_creation,
            date_emission,
            remplace_par_id,
        )

        assert isinstance(resultat.gains.brut_total, Decimal), (
            "`gains.brut_total` doit être un `Decimal`, jamais un `float` "
            f"(règle 01), obtenu {type(resultat.gains.brut_total)!r}."
        )
        assert isinstance(resultat.cout_employeur, Decimal), (
            "`cout_employeur` doit être un `Decimal`, jamais un `float` "
            f"(règle 01), obtenu {type(resultat.cout_employeur)!r}."
        )
        assert isinstance(
            resultat.cotisations_employeur.total_cotisations_employeur, Decimal
        ), (
            "`cotisations_employeur.total_cotisations_employeur` doit "
            f"être un `Decimal`, obtenu "
            f"{type(resultat.cotisations_employeur.total_cotisations_employeur)!r}."
        )

        assert resultat.cout_employeur == (
            resultat.gains.brut_total
            + resultat.cotisations_employeur.total_cotisations_employeur
        ), (
            "Identité coût employeur violée (Req 5.2, 5.3) : "
            f"cout_employeur = {resultat.cout_employeur} != "
            f"gains.brut_total + total_cotisations_employeur = "
            f"{resultat.gains.brut_total + resultat.cotisations_employeur.total_cotisations_employeur}."
        )

class TestPlafonnementCombineNetPay:
    """Test dédié — révision Requirement 14 (spec `impots-retenues-source`).

    Vérifie que le cas « brut=0 + retenue additionnelle non nulle » (le
    bug bloquant Property 1/Property 2 découvert précédemment — la
    retenue additionnelle s'ajoutait inconditionnellement au montant de
    base, ce qui pouvait faire dépasser `total_retenues_employe` au-delà
    de `gains.brut_total` et produire un `net` négatif, rejeté par le
    contrat `PayrollResult` avec `ValidationError`) produit désormais un
    `net >= 0` valide, sans exception, grâce au plafonnement combiné des
    retenues additionnelles calculé par `assembler_paie` (Requirement 14,
    décision opérationnelle Camp LilySO — voir `docs/hypotheses-2026.md`).
    """

    def test_brut_nul_avec_retenue_additionnelle_produit_net_valide(self) -> None:
        """Brut nul + retenues additionnelles QC et fédérale strictement
        positives → `assembler_paie` retourne un `PayrollResult` valide
        avec `net == Decimal("0.00")`, sans lever `ValidationError`.

        Avant la révision Requirement 14, la retenue additionnelle
        s'ajoutait inconditionnellement au montant de base (nul, car
        brut nul) : `total_retenues_employe` aurait alors été égal à la
        somme des deux retenues additionnelles (strictement positive),
        dépassant `gains.brut_total = Decimal("0.00")` et produisant un
        `net` négatif — rejeté par le contrat `PayrollResult`
        (`net: Decimal = Field(..., ge=Decimal("0"))`). Avec le
        plafonnement combiné, `espace_disponible = 0 - 0 - 0 - 0 - 0 - 0
        = Decimal("0.00")` et la somme des retenues additionnelles
        (`150,00 $`) excède cet espace : `additionnelle_permise` vaut
        `False`, les deux retenues additionnelles sont mises à 0 $, et
        `net == Decimal("0.00")`.

        `PayrollInput`/`ParametresAnnee` déterministes (même patron que
        `_payroll_input_deterministe_pour_exemple` de
        `tests/payroll_engine/test_rrq.py`), sans exonération (le cas le
        plus exigeant : le montant de base suit la formule, pas le
        court-circuit d'exonération à zéro trivial) et un taux horaire
        nul pour produire un brut nul (`heures_normales`/`heures_supplementaires`
        non nulles combinées à un taux nul, règle 03 — aucun champ
        d'heures négatif ni de contrainte de forme violée).
        """
        module = _importer_module_net_pay()

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
            montant_total_TP1015_3=Decimal("18952.00"),
            montant_total_TD1=Decimal("16452.00"),
            retenue_additionnelle_QC=Decimal("75.00"),
            retenue_additionnelle_federale=Decimal("75.00"),
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
                heures_normales=Decimal("0.00"),
                heures_supplementaires=Decimal("0.00"),
            ),
            HeuresParSemaine(
                heures_normales=Decimal("0.00"),
                heures_supplementaires=Decimal("0.00"),
            ),
        )
        cumuls_debut = CumulsYTD.zero(employe_id="EMP001", annee_civile=2026)
        payroll_input = PayrollInput(
            employee=employee,
            pay_period=pay_period,
            heures_par_semaine=heures_par_semaine,
            taux_horaire_effectif=Decimal("15.75"),
            taux_vacances=Decimal("0.04"),
            jours_feries_manuels=Decimal("0.00"),
            montant_total_TP1015_3_effectif=Decimal("18952.00"),
            exoneration_TP1015_3_effectif=False,
            retenue_additionnelle_QC_effective=Decimal("75.00"),
            montant_total_TD1_effectif=Decimal("16452.00"),
            exoneration_TD1_effective=False,
            retenue_additionnelle_federale_effective=Decimal("75.00"),
            cumuls_debut=cumuls_debut,
        )
        parametres_annee = load_parameters(2026, Juridiction.QUEBEC).model_copy(
            update={
                "assurance_emploi": load_parameters(
                    2026, Juridiction.CANADA
                ).assurance_emploi,
                "impot_federal": load_parameters(2026, Juridiction.CANADA).impot_federal,
            }
        )

        # Ne doit PAS lever ValidationError (bug corrigé par Req 14).
        resultat = module.assembler_paie(
            payroll_input,
            parametres_annee,
            "PAIE-TEST-PLAFONNEMENT-001",
            1,
            StatutDePaie.EMISE,
            datetime(2026, 7, 29),
            datetime(2026, 7, 29),
            None,
        )

        assert resultat.net >= Decimal("0.00"), (
            "`net` doit être >= 0 même avec brut nul et retenues "
            f"additionnelles combinées excédant l'espace disponible : "
            f"net = {resultat.net!r}."
        )
        assert resultat.net == Decimal("0.00"), (
            "Avec brut nul, `net` doit être exactement 0,00 $ : "
            f"{resultat.net!r}."
        )
        # Confirmation explicite : les deux retenues additionnelles ont
        # bien été plafonnées à 0 (additionnelle_permise=False).
        assert resultat.retenues_employe.impot_qc_retenu.montant == (
            resultat.retenues_employe.impot_qc_formule.montant
        )
        assert resultat.retenues_employe.impot_federal_retenu.montant == (
            resultat.retenues_employe.impot_federal_formule.montant
        )


# ---------------------------------------------------------------------------
# 2.3 — Invocation stricte sans recalcul (Property 4)
# ---------------------------------------------------------------------------


class TestInvocationStricte:
    """Property 4 — invocation stricte sans recalcul.

    Design (§Correctness Properties 4 ; §Components §1, pseudocode
    d'ordonnancement étapes A à D). Chaque section du `PayrollResult`
    produit par `assembler_paie` doit provenir d'un appel **direct et
    inchangé** à la fonction déjà livrée correspondante — jamais d'un
    recalcul interne à `net_pay.py`. Ce test appelle indépendamment les
    neuf fonctions déjà livrées (`calcul_gains`, `calcul_rrq_employe`,
    `calcul_rqap_employe`, `calcul_ae_employe`,
    `calcul_impot_qc_formule`/`calcul_impot_qc_retenu`,
    `calcul_impot_federal_formule`/`calcul_impot_federal_retenu`,
    `assembler_cotisations_employeur`) avec le même `(payroll_input,
    gains, parametres_annee)` que celui reçu par `assembler_paie`, et
    compare le résultat à la section correspondante du `PayrollResult`.

    Les neuf fonctions étant elles-mêmes pures (chacune testée
    indépendamment par sa propre spec), les appeler une seconde fois ici
    avec des arguments identiques produit nécessairement les mêmes
    valeurs — un écart ne peut provenir que d'un recalcul ou d'une
    substitution d'arguments à l'intérieur de `assembler_paie`.
    """

    # Feature: net-cumuls-registre, Property 4: Invocation stricte sans recalcul
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_4_invocation_stricte_sans_recalcul(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput` et `ParametresAnnee` valides, le
        `PayrollResult` (`pr`) produit par `assembler_paie` satisfait :
        `pr.gains == calcul_gains(pi, pa)[0]` ; pour chacune des trois
        retenues sociales employé (`rrq`, `rqap`, `ae`),
        `pr.retenues_employe.<categorie>.montant == calcul_<categorie>_employe(pi, gains, pa)[0]` ;
        pour les quatre montants d'impôt (`impot_qc_formule`,
        `impot_qc_retenu`, `impot_federal_formule`,
        `impot_federal_retenu`), même égalité symétrique avec la fonction
        déjà livrée correspondante ; et
        `pr.cotisations_employeur == assembler_cotisations_employeur(pi, gains, pa)`.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.1, 4.1, 4.2**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        pr = module.assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            version,
            statut,
            date_creation,
            date_emission,
            remplace_par_id,
        )

        # --- A. Gains (Req 2.1) ---------------------------------------
        gains_attendus, _trace_gains = calcul_gains(payroll_input, parametres_annee)
        assert pr.gains == gains_attendus, (
            "`pr.gains` doit être strictement égal au résultat d'un "
            f"appel direct à `calcul_gains` (Req 2.1) : {pr.gains!r} != "
            f"{gains_attendus!r}."
        )

        # --- B. Trois retenues sociales employé (Req 2.2) --------------
        rrq_attendu, _ = calcul_rrq_employe(
            payroll_input, gains_attendus, parametres_annee
        )
        assert pr.retenues_employe.rrq.montant == rrq_attendu, (
            "`pr.retenues_employe.rrq.montant` doit provenir d'un appel "
            f"direct à `calcul_rrq_employe` (Req 2.2) : "
            f"{pr.retenues_employe.rrq.montant!r} != {rrq_attendu!r}."
        )

        rqap_attendu, _ = calcul_rqap_employe(
            payroll_input, gains_attendus, parametres_annee
        )
        assert pr.retenues_employe.rqap.montant == rqap_attendu, (
            "`pr.retenues_employe.rqap.montant` doit provenir d'un appel "
            f"direct à `calcul_rqap_employe` (Req 2.2) : "
            f"{pr.retenues_employe.rqap.montant!r} != {rqap_attendu!r}."
        )

        ae_attendu, _ = calcul_ae_employe(
            payroll_input, gains_attendus, parametres_annee
        )
        assert pr.retenues_employe.ae.montant == ae_attendu, (
            "`pr.retenues_employe.ae.montant` doit provenir d'un appel "
            f"direct à `calcul_ae_employe` (Req 2.2) : "
            f"{pr.retenues_employe.ae.montant!r} != {ae_attendu!r}."
        )

        # --- C. Impôts QC et fédéral — formule ET retenue (Req 2.3) ----
        iqc_formule_attendu, _ = calcul_impot_qc_formule(
            payroll_input, gains_attendus, parametres_annee
        )
        assert (
            pr.retenues_employe.impot_qc_formule.montant == iqc_formule_attendu
        ), (
            "`pr.retenues_employe.impot_qc_formule.montant` doit "
            f"provenir d'un appel direct à `calcul_impot_qc_formule` "
            f"(Req 2.3) : {pr.retenues_employe.impot_qc_formule.montant!r} "
            f"!= {iqc_formule_attendu!r}."
        )

        ifed_formule_attendu, _ = calcul_impot_federal_formule(
            payroll_input, gains_attendus, parametres_annee
        )
        assert (
            pr.retenues_employe.impot_federal_formule.montant
            == ifed_formule_attendu
        ), (
            "`pr.retenues_employe.impot_federal_formule.montant` doit "
            f"provenir d'un appel direct à `calcul_impot_federal_formule` "
            f"(Req 2.3) : "
            f"{pr.retenues_employe.impot_federal_formule.montant!r} != "
            f"{ifed_formule_attendu!r}."
        )

        # --- C'. additionnelle_permise (spec impots-retenues-source,
        # Req 14) — reproduit le même calcul que net_pay.py pour
        # construire la valeur "attendue" des retenues effectives.
        montant_base_qc_attendu = (
            Decimal("0.00")
            if payroll_input.exoneration_TP1015_3_effectif
            else iqc_formule_attendu
        )
        montant_base_federal_attendu = (
            Decimal("0.00")
            if payroll_input.exoneration_TD1_effective
            else ifed_formule_attendu
        )
        espace_disponible_attendu = (
            gains_attendus.brut_total
            - rrq_attendu
            - rqap_attendu
            - ae_attendu
            - montant_base_qc_attendu
            - montant_base_federal_attendu
        )
        somme_additionnelles_attendue = (
            payroll_input.retenue_additionnelle_QC_effective
            + payroll_input.retenue_additionnelle_federale_effective
        )
        additionnelle_permise_attendue = (
            somme_additionnelles_attendue <= espace_disponible_attendu
        )

        iqc_retenu_attendu, _ = calcul_impot_qc_retenu(
            payroll_input,
            gains_attendus,
            parametres_annee,
            additionnelle_permise_attendue,
        )
        assert pr.retenues_employe.impot_qc_retenu.montant == iqc_retenu_attendu, (
            "`pr.retenues_employe.impot_qc_retenu.montant` doit provenir "
            f"d'un appel direct à `calcul_impot_qc_retenu` (Req 2.3) : "
            f"{pr.retenues_employe.impot_qc_retenu.montant!r} != "
            f"{iqc_retenu_attendu!r}."
        )

        ifed_retenu_attendu, _ = calcul_impot_federal_retenu(
            payroll_input,
            gains_attendus,
            parametres_annee,
            additionnelle_permise_attendue,
        )
        assert (
            pr.retenues_employe.impot_federal_retenu.montant
            == ifed_retenu_attendu
        ), (
            "`pr.retenues_employe.impot_federal_retenu.montant` doit "
            f"provenir d'un appel direct à `calcul_impot_federal_retenu` "
            f"(Req 2.3) : "
            f"{pr.retenues_employe.impot_federal_retenu.montant!r} != "
            f"{ifed_retenu_attendu!r}."
        )

        # --- D. CotisationsEmployeur complet, en un seul appel (Req 2.4)
        cotisations_attendues = assembler_cotisations_employeur(
            payroll_input, gains_attendus, parametres_annee
        )
        assert pr.cotisations_employeur == cotisations_attendues, (
            "`pr.cotisations_employeur` doit être strictement égal au "
            f"résultat d'un appel direct à "
            f"`assembler_cotisations_employeur` (Req 2.4) : "
            f"{pr.cotisations_employeur!r} != {cotisations_attendues!r}."
        )


# ---------------------------------------------------------------------------
# 2.4 — Cohérence et monotonie de `cumuls_fin` (Property 5)
# ---------------------------------------------------------------------------


#: Mapping exact des onze catégories `_ContributionPaie` (design
#: §Components §2, Requirement 6 AC2) vers l'expression permettant de
#: retrouver le montant correspondant à partir du `PayrollResult` (`pr`)
#: retourné par `assembler_paie`. Chaque valeur est une fonction
#: `PayrollResult -> Decimal` plutôt qu'une chaîne d'attribut, pour
#: refléter fidèlement l'étape G du pseudocode (§Components §1) — en
#: particulier `net` n'est pas une catégorie de `pr.gains`/`pr.retenues_employe`
#: mais bien `pr.net` lui-même (calculé à l'étape F).
_MAPPING_CONTRIBUTION_DEPUIS_RESULTAT: dict[str, Any] = {
    "brut": lambda pr: pr.gains.brut_total,
    "vacances": lambda pr: pr.gains.vacances,
    "rrq_employe": lambda pr: pr.retenues_employe.rrq.montant,
    "rrq_employeur": lambda pr: pr.cotisations_employeur.rrq_employeur.montant,
    "rqap_employe": lambda pr: pr.retenues_employe.rqap.montant,
    "rqap_employeur": lambda pr: pr.cotisations_employeur.rqap_employeur.montant,
    "ae_employe": lambda pr: pr.retenues_employe.ae.montant,
    "ae_employeur": lambda pr: pr.cotisations_employeur.ae_employeur.montant,
    "impot_qc_retenu": lambda pr: pr.retenues_employe.impot_qc_retenu.montant,
    "impot_federal_retenu": lambda pr: pr.retenues_employe.impot_federal_retenu.montant,
    "net": lambda pr: pr.net,
}


class TestCumulsFin:
    """Property 5 — cohérence et monotonie de `cumuls_fin`.

    Design (§Correctness Properties 5 ; §Components §2 — objet
    intermédiaire privé `_ContributionPaie`, résolution de la
    dépendance circulaire entre le `PayrollResult` en cours de
    construction et `CumulsYTD.avec_paie`).

    `st_payroll_input()` garantit déjà par construction (voir son
    docstring, ``tests/strategies.py``) que
    ``cumuls_debut.annee_civile == pay_period.annee_fiscale`` — la
    Property 5 n'a donc besoin d'aucun filtrage supplémentaire pour le
    cas nominal. Le test d'exemple ci-dessous couvre spécifiquement le
    cas *hors* de cette garantie (Req 6.4).
    """

    # Feature: net-cumuls-registre, Property 5: Cohérence et monotonie de cumuls_fin
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_5_coherence_et_monotonie_de_cumuls_fin(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput` valide tel que
        `cumuls_debut.annee_civile == pay_period.annee_fiscale`
        (garanti par `st_payroll_input()`), le `cumuls_fin` du
        `PayrollResult` produit par `assembler_paie` satisfait, pour
        chacune des onze catégories : `cumuls_fin.<categorie> ==
        cumuls_debut.<categorie> + contribution.<categorie>` (mapping
        exact du Requirement 6 AC2) et `cumuls_fin.<categorie> >=
        cumuls_debut.<categorie>` (monotonie croissante).

        **Validates: Requirements 6.1, 6.2, 6.3, 6.5**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        cumuls_debut = payroll_input.cumuls_debut

        resultat = module.assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            version,
            statut,
            date_creation,
            date_emission,
            remplace_par_id,
        )

        assert resultat.cumuls_fin.employe_id == payroll_input.employee.id, (
            "`cumuls_fin.employe_id` doit correspondre à `employee.id` "
            f"(Req 6.3) : {resultat.cumuls_fin.employe_id!r} != "
            f"{payroll_input.employee.id!r}."
        )
        assert (
            resultat.cumuls_fin.annee_civile
            == payroll_input.pay_period.annee_fiscale
        ), (
            "`cumuls_fin.annee_civile` doit correspondre à "
            f"`pay_period.annee_fiscale` (Req 6.3) : "
            f"{resultat.cumuls_fin.annee_civile!r} != "
            f"{payroll_input.pay_period.annee_fiscale!r}."
        )

        for categorie, extraire_contribution in (
            _MAPPING_CONTRIBUTION_DEPUIS_RESULTAT.items()
        ):
            valeur_debut: Decimal = getattr(cumuls_debut, categorie)
            valeur_fin: Decimal = getattr(resultat.cumuls_fin, categorie)
            contribution_attendue: Decimal = extraire_contribution(resultat)

            assert isinstance(valeur_fin, Decimal), (
                f"`cumuls_fin.{categorie}` doit être un `Decimal`, jamais "
                f"un `float` (règle 01), obtenu {type(valeur_fin)!r}."
            )

            assert valeur_fin == valeur_debut + contribution_attendue, (
                f"Cohérence de `cumuls_fin.{categorie}` violée (Req 6.2) : "
                f"{valeur_fin} != cumuls_debut.{categorie} "
                f"({valeur_debut}) + contribution.{categorie} "
                f"({contribution_attendue})."
            )

            assert valeur_fin >= valeur_debut, (
                f"Monotonie violée pour `cumuls_fin.{categorie}` (Req 6.5) : "
                f"{valeur_fin} < cumuls_debut.{categorie} ({valeur_debut})."
            )

    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
    )
    @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow], max_examples=10)
    def test_exemple_cumuls_debut_annee_civile_differente_leve_payroll_domain_error(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
    ) -> None:
        """Test d'exemple — `cumuls_debut.annee_civile !=
        pay_period.annee_fiscale` -> `PayrollDomainError` levée par
        `CumulsYTD.avec_paie`, propagée sans interception (Req 6.4).

        Un `PayrollInput` valide ne peut normalement pas porter un tel
        mismatch : le `model_validator(mode="after")` de `PayrollInput`
        (`_coherence_croisee`, étape 6) le rejette déjà à la
        construction avec `ValidationError` (voir
        ``tests/models/test_payroll_input.py``
        ``test_cumuls_debut_annee_civile_differente_leve_validation_error``).
        Ce test contourne donc cette garde amont via
        ``model_copy(update=...)`` — qui, en Pydantic v2, ne redéclenche
        **aucun** validateur (ni ``field_validator``, ni
        ``model_validator``) — afin de vérifier isolément le
        comportement propre de `assembler_paie` / `CumulsYTD.avec_paie`
        à l'étape G (design §Components §2) : l'étape G ne doit
        *elle-même* rien intercepter, et c'est `CumulsYTD.avec_paie` qui
        lève nativement `PayrollDomainError`. `employe_id` reste
        cohérent (seule l'année diffère) pour isoler précisément le
        contrôle Req 7.6 (année) du contrôle Req 7.7 (employé).
        """
        module = _importer_module_net_pay()

        cumuls_debut_annee_differente = CumulsYTD.zero(
            employe_id=payroll_input.employee.id,
            annee_civile=payroll_input.pay_period.annee_fiscale + 1,
        )
        payroll_input_incoherent = payroll_input.model_copy(
            update={"cumuls_debut": cumuls_debut_annee_differente}
        )

        with pytest.raises(PayrollDomainError):
            module.assembler_paie(
                payroll_input_incoherent,
                parametres_annee,
                "PAIE-EXEMPLE-001",
                1,
                StatutDePaie.EMISE,
                datetime(2026, 6, 15),
                datetime(2026, 6, 15),
                None,
            )


# ---------------------------------------------------------------------------
# 2.5 — Construction finale fidèle et sans erreur (Property 6)
# ---------------------------------------------------------------------------


class TestConstructionFinale:
    """Property 6 — construction finale fidèle et sans erreur.

    Design (§Correctness Properties 6 ; §Components §1 étape H).

    Pour tout `PayrollInput`, `ParametresAnnee` et arguments de cycle de
    vie mutuellement cohérents (`_st_arguments_cycle_de_vie_valides`),
    `assembler_paie` retourne un `PayrollResult` sans lever
    `ValidationError`, et les six champs de cycle de vie du résultat
    (`id_paie`, `version`, `statut`, `date_creation`, `date_emission`,
    `remplace_par_id`) sont strictement identiques aux arguments fournis
    à l'appel — l'étape H (design §Components §1) construit
    `PayrollResult` en un seul appel via le constructeur Pydantic
    standard, sans jamais passer par `model_construct` (Req 7.4).
    """

    # Feature: net-cumuls-registre, Property 6: Construction finale fidèle et sans erreur
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_6_construction_finale_fidele_et_sans_erreur(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput`, `ParametresAnnee` et arguments de
        cycle de vie mutuellement cohérents, `assembler_paie` retourne un
        `PayrollResult` sans lever `ValidationError`, et `id_paie`,
        `version`, `statut`, `date_creation`, `date_emission`,
        `remplace_par_id` du résultat sont strictement identiques aux
        arguments fournis.

        **Validates: Requirements 7.2, 7.3**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        try:
            resultat = module.assembler_paie(
                payroll_input,
                parametres_annee,
                id_paie,
                version,
                statut,
                date_creation,
                date_emission,
                remplace_par_id,
            )
        except ValidationError as exc:  # pragma: no cover - échec attendu à documenter
            pytest.fail(
                "`assembler_paie` a levé `ValidationError` pour des "
                "arguments de cycle de vie mutuellement cohérents "
                f"(Req 7.2) : {exc!r}."
            )

        assert resultat.id_paie == id_paie, (
            "`resultat.id_paie` doit être strictement identique à "
            f"l'argument fourni (Req 7.3) : {resultat.id_paie!r} != "
            f"{id_paie!r}."
        )
        assert resultat.version == version, (
            "`resultat.version` doit être strictement identique à "
            f"l'argument fourni (Req 7.3) : {resultat.version!r} != "
            f"{version!r}."
        )
        assert resultat.statut == statut, (
            "`resultat.statut` doit être strictement identique à "
            f"l'argument fourni (Req 7.3) : {resultat.statut!r} != "
            f"{statut!r}."
        )
        assert resultat.date_creation == date_creation, (
            "`resultat.date_creation` doit être strictement identique à "
            f"l'argument fourni (Req 7.3) : {resultat.date_creation!r} != "
            f"{date_creation!r}."
        )
        assert resultat.date_emission == date_emission, (
            "`resultat.date_emission` doit être strictement identique à "
            f"l'argument fourni (Req 7.3) : {resultat.date_emission!r} != "
            f"{date_emission!r}."
        )
        assert resultat.remplace_par_id == remplace_par_id, (
            "`resultat.remplace_par_id` doit être strictement identique "
            f"à l'argument fourni (Req 7.3) : "
            f"{resultat.remplace_par_id!r} != {remplace_par_id!r}."
        )

    def test_exemple_construction_finale_sans_model_construct(self) -> None:
        """Test d'exemple — inspection statique légère : `net_pay.py` ne
        construit jamais `PayrollResult` via `model_construct` (Req 7.4).

        L'étape H (design §Components §1) impose le constructeur
        Pydantic standard (`PayrollResult(...)`), qui seul déclenche les
        trois `model_validator(mode="after")` du contrat (identités,
        biconditionnelle de cycle de vie, cohérence `cumuls_fin`).
        `model_construct` contournerait silencieusement ces validations.

        Règle 06 (TDD — tests avant code) : tant que
        `payroll_engine/net_pay.py` n'existe pas encore (tâche 7.2), ce
        test échoue explicitement via `pytest.fail` — état rouge attendu,
        et non une erreur de collection.
        """
        if not _CHEMIN_NET_PAY.exists():
            pytest.fail(
                f"{_CHEMIN_NET_PAY.relative_to(_REPO_ROOT).as_posix()} "
                "n'existe pas encore. Ce test de garde précède "
                "l'implémentation (tâche 7.2 de la spec "
                "net-cumuls-registre, règle 06) et DOIT rester rouge "
                "jusqu'à la création du module."
            )

        source = _CHEMIN_NET_PAY.read_text(encoding="utf-8")

        assert "model_construct" not in source, (
            "`payroll_engine/net_pay.py` ne doit jamais utiliser "
            "`model_construct` pour construire `PayrollResult` (Req "
            "7.4) — seul le constructeur Pydantic standard "
            "(`PayrollResult(...)`) est autorisé, afin que les "
            "`model_validator(mode=\"after\")` du contrat s'exécutent "
            "systématiquement."
        )


# ---------------------------------------------------------------------------
# 2.6 — Propagation sans interception des exceptions (Property 7)
# ---------------------------------------------------------------------------


#: Chemins ``"<section>.<champ>"`` de champs **consommés directement** par
#: l'une des neuf fonctions invoquées par `assembler_paie` (design
#: §Components §1, étapes A à D) — un par fonction ou groupe de fonctions
#: partageant la même section, à l'exclusion de `calcul_gains` (dont les
#: deux champs `heures_supplementaires.*` sont couverts par sa propre spec
#: `gains-bruts-vacances-hs`, Property 17) :
#:
#: - ``"rrq.taux_cotisation_totale_employe"`` -> `calcul_rrq_employe` ;
#: - ``"rqap.taux_employe"`` -> `calcul_rqap_employe` ;
#: - ``"assurance_emploi.taux_employe_quebec"`` -> `calcul_ae_employe` ;
#: - ``"impot_quebec.taux_credits_convertibles"`` -> `calcul_impot_qc_formule`
#:   (invoquée directement par `assembler_paie`, indépendamment de
#:   `exoneration_TP1015_3_effectif` — étape C, design §Components §1) ;
#: - ``"impot_federal.taux_credits_convertibles"`` ->
#:   `calcul_impot_federal_formule` (même raisonnement, étape C) ;
#: - ``"fss.taux_camp_lilyso_2026"``, ``"cnesst.taux_total"``,
#:   ``"cnt.taux"`` -> trois des six fonctions invoquées par
#:   `assembler_cotisations_employeur` (étape D).
#:
#: Passés à ``st_parametres_annee_avec_to_fill(champ)``, chacun produit un
#: ``ParametresAnnee`` réel 2026 où ce seul champ porte la sentinelle
#: ``"TO_FILL"`` : la fonction qui le consomme lève alors
#: ``MissingParameterError``, que `assembler_paie` doit **propager** sans
#: l'intercepter (Property 7).
_CHAMPS_TO_FILL_NET_PAY: tuple[str, ...] = (
    "rrq.taux_cotisation_totale_employe",
    "rqap.taux_employe",
    "assurance_emploi.taux_employe_quebec",
    "impot_quebec.taux_credits_convertibles",
    "impot_federal.taux_credits_convertibles",
    "fss.taux_camp_lilyso_2026",
    "cnesst.taux_total",
    "cnt.taux",
)


@st.composite
def _st_parametres_annee_net_pay_avec_to_fill(draw: st.DrawFn) -> Any:
    """``ParametresAnnee`` (fusion QC/CA) dont un champ consommé par l'une des
    neuf fonctions invoquées par `assembler_paie` porte ``"TO_FILL"``.

    Tire l'un des chemins de :data:`_CHAMPS_TO_FILL_NET_PAY` puis, via
    ``st_parametres_annee_avec_to_fill(champ)``, un ``ParametresAnnee`` réel
    2026 (fusion Québec + Canada) dont ce seul champ porte la sentinelle
    ``SENTINEL_TO_FILL``. L'accès à la propriété matérialisée
    correspondante lève ``MissingParameterError`` lorsque la fonction qui la
    consomme est invoquée par `assembler_paie` — ce que Property 7 vérifie.

    Règle 06 (immuabilité) : ``st_parametres_annee_avec_to_fill`` recopie la
    section ciblée puis la racine via ``model_copy`` — l'instance mémorisée
    des paramètres réels n'est jamais mutée.
    """
    champ = draw(st.sampled_from(_CHAMPS_TO_FILL_NET_PAY))
    return draw(st_parametres_annee_avec_to_fill(champ))


class TestPropagationExceptions:
    """Property 7 — propagation sans interception des exceptions du domaine.

    Design (§Correctness Properties 7 ; §Error Handling « Matrice des
    exceptions »). Pour tout `ParametresAnnee` où un champ consommé par
    l'une des neuf fonctions invoquées par `assembler_paie` porte
    ``"TO_FILL"`` ou une section requise est `None`, `assembler_paie` doit
    laisser passer exactement la `MissingParameterError`/
    `UnsupportedPayrollCase` levée par la fonction concernée — jamais
    interceptée, masquée ni reconvertie en une autre exception. Le cas
    `PayrollDomainError` (`cumuls_debut.annee_civile !=
    pay_period.annee_fiscale`, levée par `CumulsYTD.avec_paie` à l'étape G)
    fait également partie de cette propriété selon la matrice du design
    (§Error Handling), en complément du test d'exemple déjà couvert par
    `TestCumulsFin` (tâche 2.4, Req 6.4).
    """

    # Feature: net-cumuls-registre, Property 7: Propagation sans interception
    @pytest.mark.property
    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=_st_parametres_annee_net_pay_avec_to_fill(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings_large_input
    def test_property_7_champ_to_fill_leve_missing_parameter_error_non_interceptee(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """*Pour tout* `PayrollInput` valide et `ParametresAnnee` où un champ
        consommé par l'une des neuf fonctions invoquées porte `"TO_FILL"`
        (:data:`_CHAMPS_TO_FILL_NET_PAY`), `assembler_paie` lève exactement
        `MissingParameterError` — jamais interceptée, masquée ni reconvertie
        en une autre exception (ni `ValueError`, ni `TypeError`, ni
        `AttributeError`).

        **Validates: Requirements 2.6, 17.3**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        with pytest.raises(MissingParameterError):
            module.assembler_paie(
                payroll_input,
                parametres_annee,
                id_paie,
                version,
                statut,
                date_creation,
                date_emission,
                remplace_par_id,
            )

    @given(
        payroll_input=st_payroll_input(),
        parametres_annee=st_parametres_annee_2026_qc_ca(),
        arguments_cycle_de_vie=_st_arguments_cycle_de_vie_valides(),
    )
    @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow], max_examples=10)
    def test_exemple_section_fss_absente_leve_missing_parameter_error_non_interceptee(
        self,
        payroll_input: PayrollInput,
        parametres_annee: Any,
        arguments_cycle_de_vie: tuple[
            str, int, StatutDePaie, datetime, datetime | None, str | None
        ],
    ) -> None:
        """Test d'exemple — section requise `None` (`fss`) -> `assembler_paie`
        propage `MissingParameterError` sans l'intercepter.

        `assembler_cotisations_employeur` (étape D, design §Components §1)
        invoque `calcul_fss`, qui lève `MissingParameterError` en tête de
        fonction lorsque `parametres_annee.fss is None` (garde-fou de
        section, cf. ``payroll_engine/charges_patronales.py``). `net_pay.py`
        ne doit rien intercepter autour de cet appel.

        **Validates: Requirements 2.6, 17.3**
        """
        id_paie, version, statut, date_creation, date_emission, remplace_par_id = (
            arguments_cycle_de_vie
        )
        module = _importer_module_net_pay()

        parametres_sans_fss = parametres_annee.model_copy(update={"fss": None})

        with pytest.raises(MissingParameterError) as exc_info:
            module.assembler_paie(
                payroll_input,
                parametres_sans_fss,
                id_paie,
                version,
                statut,
                date_creation,
                date_emission,
                remplace_par_id,
            )

        assert "fss" in str(exc_info.value), (
            "Le message de `MissingParameterError` doit identifier la "
            f"section manquante 'fss' ; message obtenu : {exc_info.value!r}."
        )

    def test_exemple_cumuls_debut_annee_civile_differente_leve_payroll_domain_error_propagee(
        self,
    ) -> None:
        """Test d'exemple — `PayrollDomainError` (mismatch `annee_civile`)
        appartient elle aussi à Property 7 (design §Error Handling « Matrice
        des exceptions » : « Propagée + Property 7 »), en complément du test
        d'exemple déjà écrit par `TestCumulsFin` (tâche 2.4, Req 6.4).

        Un couple minimal `(PayrollInput, ParametresAnnee)` valide est
        d'abord obtenu via un exemple fixe des stratégies existantes, puis
        `cumuls_debut` est remplacé par un `CumulsYTD.zero` d'une année
        civile différente via ``model_copy`` (qui, en Pydantic v2, ne
        redéclenche aucun validateur) — afin d'isoler le comportement propre
        de `assembler_paie`/`CumulsYTD.avec_paie` à l'étape G, indépendamment
        de la garde amont de `PayrollInput._coherence_croisee`.

        **Validates: Requirements 6.4, 2.6, 17.3**
        """
        module = _importer_module_net_pay()

        @given(
            payroll_input=st_payroll_input(),
            parametres_annee=st_parametres_annee_2026_qc_ca(),
        )
        @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow], max_examples=5)
        def _verifier(payroll_input: PayrollInput, parametres_annee: Any) -> None:
            cumuls_debut_annee_differente = CumulsYTD.zero(
                employe_id=payroll_input.employee.id,
                annee_civile=payroll_input.pay_period.annee_fiscale + 1,
            )
            payroll_input_incoherent = payroll_input.model_copy(
                update={"cumuls_debut": cumuls_debut_annee_differente}
            )

            with pytest.raises(PayrollDomainError):
                module.assembler_paie(
                    payroll_input_incoherent,
                    parametres_annee,
                    "PAIE-EXEMPLE-PROPAGATION-001",
                    1,
                    StatutDePaie.EMISE,
                    datetime(2026, 6, 15),
                    datetime(2026, 6, 15),
                    None,
                )

        _verifier()

    def test_exemple_absence_de_try_except_dans_net_pay(self) -> None:
        """Test d'exemple — inspection statique légère : `net_pay.py` ne
        contient **aucun** bloc `try`/`except` (Req 2.6, 17.3).

        `assembler_paie` invoque les neuf fonctions déjà livrées (design
        §Components §1, étapes A à D) sans jamais les envelopper d'un
        `try`/`except` : toute exception levée par l'une d'elles
        (`MissingParameterError`, `UnsupportedPayrollCase`) ou par
        `CumulsYTD.avec_paie` (`PayrollDomainError`, étape G) doit se
        propager telle quelle jusqu'à l'appelant. Un simple parcours
        `ast.walk` du module recherchant un nœud `ast.Try` suffit : ce
        module ne contient aucune fonction pour laquelle un `try`/`except`
        serait légitime (contrairement à `register.py`, qui utilise
        `try`/`except`/`finally` autour de la gestion transactionnelle
        SQLite — hors périmètre de ce test).

        Règle 06 (TDD — tests avant code) : tant que
        `payroll_engine/net_pay.py` n'existe pas encore (tâche 7.2), ce
        test échoue explicitement via `pytest.fail` — état rouge attendu,
        et non une erreur de collection.
        """
        if not _CHEMIN_NET_PAY.exists():
            pytest.fail(
                f"{_CHEMIN_NET_PAY.relative_to(_REPO_ROOT).as_posix()} "
                "n'existe pas encore. Ce test de garde précède "
                "l'implémentation (tâche 7.2 de la spec "
                "net-cumuls-registre, règle 06) et DOIT rester rouge "
                "jusqu'à la création du module."
            )

        source = _CHEMIN_NET_PAY.read_text(encoding="utf-8")
        arbre = ast.parse(source, filename=str(_CHEMIN_NET_PAY))

        noeuds_try = [noeud for noeud in ast.walk(arbre) if isinstance(noeud, ast.Try)]

        assert not noeuds_try, (
            "`payroll_engine/net_pay.py` ne doit contenir aucun bloc "
            "`try`/`except` (Req 2.6, 17.3) : toute exception levée par "
            "l'une des neuf fonctions invoquées doit se propager sans être "
            f"interceptée. {len(noeuds_try)} bloc(s) `try` trouvé(s) à la "
            f"ligne {noeuds_try[0].lineno if noeuds_try else '?'}."
        )
