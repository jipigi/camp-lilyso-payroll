"""Tests d'exemple et property test du chargeur de paramètres versionnés.

Spec de référence : ``moteur-paie-contrats`` — tâche 12.1.
Design de référence : ``design.md`` §Components 10 et §Data Models 9
(``payroll_engine/parameters_loader.py``).

Discipline TDD (règle 06) : ce module est écrit **avant** l'implémentation.
Tant que la tâche 12.2 / 12.3 n'a pas créé ``payroll_engine/parameters_loader.py``,
la collection pytest de ce fichier échoue avec ``ModuleNotFoundError``. C'est
le comportement attendu — les tests précèdent le code.

Portée de la tâche 12.1 (issue directe de ``tasks.md`` §12.1) :

- **Property 15** : déterminisme de ``load_parameters``. Hypothesis génère
  un fichier de paramètres temporaire (via ``tmp_path``) et vérifie que deux
  appels successifs retournent des instances ``ParametresAnnee`` égales au
  sens ``==`` (aucun cache, aucun état global). **Validates: Requirements 9.10**
- Tests d'exemple couvrant les Requirements 8.2, 8.5, 8.6, 9.1–9.11, 13.5 :
  * chargement nominal de ``parameters/2026/quebec.json`` (Req 9.1, 9.2, 9.11) ;
  * accès à un champ ``"TO_FILL"`` → ``MissingParameterError`` avec chemin JSON
    identifié et référence au fichier de paramètres (Req 8.5, 8.6, 9.5, 9.11) ;
  * fichier absent → ``FileNotFoundError`` avec année et juridiction dans le
    message (Req 9.8) ;
  * littéral JSON non guillemé sur un champ ``Decimal`` → erreur de validation
    (Req 9.4, 13.5) ;
  * paramètre optionnel ``chemin_racine`` accepté (Req 9.9) ;
  * ``Decimal`` chargés strictement égaux à ``Decimal(str_value)`` sans passage
    par ``float`` (Req 9.3, 9.4) ;
  * validation NON déclenchée à l'import du module (Req 9.7) ;
  * disjonction stricte ``MissingParameterError`` / ``UnsupportedPayrollCase``
    (Req 8.2).

Règles applicables :

- Règle 01 — aucun ``float`` dans le domaine paie. Les tests eux-mêmes ne
  construisent des ``float`` que pour vérifier leur rejet à la frontière
  (littéral JSON non guillemé).
- Règle 04 — aucune donnée personnelle réelle. Les fichiers temporaires
  générés par Hypothesis ne contiennent que des paramètres fiscaux publics.
- Règle 05 — les paramètres fiscaux ne sont lus que via ``load_parameters``,
  jamais codés en dur dans les modules Python.
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import importlib
import json
from decimal import Decimal
from pathlib import Path

import pydantic
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.enums import Juridiction
from models.exceptions import MissingParameterError, UnsupportedPayrollCase

# Import volontairement au niveau module : tant que
# ``payroll_engine/parameters_loader.py`` n'existe pas (tâches 12.2 / 12.3 non
# réalisées), la collection pytest de ce fichier échoue avec
# ``ModuleNotFoundError``. C'est le comportement attendu par la règle 06.
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters  # noqa: E402


# ---------------------------------------------------------------------------
# Constantes et helpers de test
# ---------------------------------------------------------------------------


# Chemin vers le dossier ``parameters/`` de production (état actuel du dépôt),
# utilisé par les tests qui vérifient le comportement contre les fichiers
# réels ``parameters/2026/{quebec,canada}.json`` — Req 9.11.
PARAMETERS_DIR_PRODUCTION: Path = Path(__file__).resolve().parents[2] / "parameters"


def _minimal_quebec_json(annee: int, nb_periodes: int, source: str) -> dict:
    """Retourne un dictionnaire JSON minimal valide pour la juridiction Québec.

    Ce squelette expose les champs racine exigés par le design
    (``annee``, ``juridiction``, ``source``, ``date_publication``,
    ``url_consultee``) et une section ``frequence_paie`` complète. Il ne
    contient aucun ``TO_FILL`` afin que ``load_parameters`` réussisse
    intégralement (Property 15 — déterminisme).

    Toutes les valeurs numériques monétaires sont exprimées en **chaînes**
    (jamais en littéraux JSON non guillemés), pour respecter la règle 01
    et le Req 13.5.
    """

    return {
        "annee": annee,
        "juridiction": "quebec",
        "source": source,
        "date_publication": "TO_FILL",
        "date_consultation": "TO_FILL",
        "url_consultee": "TO_FILL",
        "notes": "Fichier de test généré par Hypothesis (Property 15).",
        "frequence_paie": {
            "commentaire": "Fixture de test.",
            "nb_periodes_annuelles": nb_periodes,
            "statut": "TEST",
        },
    }


# ---------------------------------------------------------------------------
# Chargement nominal (Req 9.1, 9.2, 9.11)
# ---------------------------------------------------------------------------


class TestChargementNominal:
    """Req 9.1, 9.2, 9.11 — ``load_parameters(2026, Juridiction.QUEBEC)``
    charge le fichier ``parameters/2026/quebec.json`` sans erreur, dès lors
    que l'appelant se limite aux sections dépourvues de ``"TO_FILL"``.

    La contrainte Req 9.11 accepte que le fichier actuel contienne des
    ``"TO_FILL"`` sur des champs non consommés par les scénarios QC001–QC006 :
    le chargement doit néanmoins réussir, et la ``MissingParameterError`` ne
    doit se déclencher qu'à l'accès effectif d'un champ ``"TO_FILL"``.
    """

    def test_quebec_2026_charge_sans_erreur(self) -> None:
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        assert isinstance(parametres, ParametresAnnee)
        assert parametres.annee == 2026
        assert parametres.juridiction == Juridiction.QUEBEC

    def test_canada_2026_charge_sans_erreur(self) -> None:
        parametres = load_parameters(2026, Juridiction.CANADA)
        assert isinstance(parametres, ParametresAnnee)
        assert parametres.annee == 2026
        assert parametres.juridiction == Juridiction.CANADA

    def test_section_frequence_paie_est_accessible(self) -> None:
        # ``frequence_paie`` ne contient aucun ``"TO_FILL"`` dans le fichier
        # actuel : la section DOIT être entièrement lisible sans exception.
        # La valeur 27 est celle documentée dans ``parameters/2026/quebec.json``
        # (année à 27 paies bi-hebdomadaires — Req 2.7).
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        assert parametres.frequence_paie.nb_periodes_annuelles == 27


# ---------------------------------------------------------------------------
# Fichier absent (Req 9.8)
# ---------------------------------------------------------------------------


class TestFichierAbsent:
    """Req 9.8 — l'absence du fichier ``parameters/<annee>/<juridiction>.json``
    DOIT lever ``FileNotFoundError`` avec un message identifiant explicitement
    l'année et la juridiction demandées, pour guider l'utilisateur vers la
    création du fichier annuel manquant (règle 05).
    """

    def test_annee_absente_leve_file_not_found(self, tmp_path: Path) -> None:
        # ``tmp_path`` est vide : aucun sous-dossier ``2099/`` n'existe.
        with pytest.raises(FileNotFoundError) as exc_info:
            load_parameters(2099, Juridiction.QUEBEC, chemin_racine=tmp_path)

        message = str(exc_info.value)
        # Le message DOIT contenir l'année et la juridiction (Req 9.8).
        assert "2099" in message
        assert "quebec" in message.lower()

    def test_juridiction_absente_leve_file_not_found(self, tmp_path: Path) -> None:
        # Créer un dossier d'année, mais sans le fichier canada.json attendu.
        (tmp_path / "2099").mkdir()
        with pytest.raises(FileNotFoundError) as exc_info:
            load_parameters(2099, Juridiction.CANADA, chemin_racine=tmp_path)

        message = str(exc_info.value)
        assert "2099" in message
        assert "canada" in message.lower()


# ---------------------------------------------------------------------------
# Accès à une valeur ``"TO_FILL"`` (Req 8.5, 8.6, 9.5, 9.11)
# ---------------------------------------------------------------------------


class TestValeurToFill:
    """Req 8.5, 8.6, 9.5, 9.11 — l'accès à un champ ``Decimal`` marqué
    ``"TO_FILL"`` DOIT lever ``MissingParameterError`` avec un message
    contenant :

    - le chemin JSON du paramètre manquant (ex. ``rrq.maximum_gains_admissibles_mga``) ;
    - l'année et la juridiction ;
    - le fichier de paramètres à mettre à jour ;
    - une référence à la source officielle (TP-1015.F ou T4127).

    Vérification issue de Property 16 (contrat des messages) — testée plus
    complètement par la tâche 15.4. Ici, on couvre le déclenchement de
    l'exception et la présence du chemin JSON dans le message.
    """

    def test_acces_rrq_mga_leve_missing_parameter_error(self) -> None:
        # ``rrq.maximum_gains_admissibles_mga`` est ``"TO_FILL"`` dans le
        # fichier actuel (2026/quebec.json), et est explicitement cité par la
        # tâche 12.1 comme exemple de chemin à identifier.
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        with pytest.raises(MissingParameterError) as exc_info:
            _ = parametres.rrq.maximum_gains_admissibles_mga

        message = str(exc_info.value)
        # Le chemin JSON doit apparaître dans le message (Req 9.5).
        assert "rrq" in message.lower()
        assert "maximum_gains_admissibles_mga" in message

    def test_message_missing_parameter_error_identifie_le_fichier(self) -> None:
        # Req 8.6 — le message DOIT indiquer le fichier de paramètres à
        # mettre à jour et l'année / la juridiction concernées.
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        with pytest.raises(MissingParameterError) as exc_info:
            _ = parametres.rrq.maximum_gains_admissibles_mga

        message = str(exc_info.value)
        assert "2026" in message
        assert "quebec" in message.lower()
        # Le message doit mentionner le fichier de paramètres.
        assert "parameters" in message.lower() or "quebec.json" in message.lower()


# ---------------------------------------------------------------------------
# Rejet d'un littéral JSON non guillemé sur un champ ``Decimal`` (Req 9.4, 13.5)
# ---------------------------------------------------------------------------


class TestRejetLitteralJsonFloat:
    """Req 9.4, 13.5 — un fichier de paramètres contenant un littéral
    numérique **non guillemé** (ex. ``"taux_rrq": 0.063``) DOIT être rejeté
    par le chargeur avec une erreur de validation, sans coercition silencieuse
    ni traitement partiel du document.

    L'implémentation utilise ``json.loads(..., parse_float=_reject_json_float)``
    (design §Components 3.3), ce qui garantit un rejet fail-fast dès la
    première occurrence d'un littéral décimal non guillemé.
    """

    def test_litteral_non_guilleme_est_rejete(self, tmp_path: Path) -> None:
        # Construire un fichier avec un littéral décimal non guillemé sur
        # ``frequence_paie.commentaire`` — non, mieux : injecter un décimal
        # non guillemé directement dans le JSON. On écrit la chaîne à la main
        # pour contourner ``json.dumps`` qui guillemet les Decimals implicitement.
        annee_dir = tmp_path / "2026"
        annee_dir.mkdir()
        contenu_json_non_conforme = (
            '{\n'
            '  "annee": 2026,\n'
            '  "juridiction": "quebec",\n'
            '  "source": "Revenu Québec — TP-1015.F 2026",\n'
            '  "date_publication": "TEST",\n'
            '  "url_consultee": "TEST",\n'
            '  "frequence_paie": {\n'
            '    "nb_periodes_annuelles": 27,\n'
            '    "statut": "TEST"\n'
            '  },\n'
            '  "rrq": {\n'
            '    "taux_cotisation_totale_employe": 0.063,\n'
            '    "taux_cotisation_totale_employeur": "0.063",\n'
            '    "exemption_generale_annuelle": "3500.00"\n'
            '  }\n'
            '}\n'
        )
        (annee_dir / "quebec.json").write_text(contenu_json_non_conforme, encoding="utf-8")

        # Le rejet peut se manifester sous plusieurs formes suivant la couche
        # qui l'attrape en premier (parseur JSON, validateur Pydantic). On
        # accepte donc n'importe laquelle de : ``pydantic.ValidationError``,
        # ``ValueError``, ``TypeError``. La contrainte forte est que le
        # chargement échoue — jamais qu'il accepte silencieusement le float.
        with pytest.raises((pydantic.ValidationError, ValueError, TypeError)):
            load_parameters(2026, Juridiction.QUEBEC, chemin_racine=tmp_path)

    def test_litteral_entier_sans_point_decimal_reste_accepte(
        self, tmp_path: Path
    ) -> None:
        # Req 10.1 — un entier JSON sans point décimal (ex. ``27``) DOIT rester
        # accepté. C'est le cas de ``frequence_paie.nb_periodes_annuelles`` qui
        # est un ``int`` (et non un ``Decimal``). Ce test contre-exemple
        # cadenasse la surface positive du parseur.
        annee_dir = tmp_path / "2030"
        annee_dir.mkdir()
        contenu = _minimal_quebec_json(2030, 26, "Revenu Québec — TP-1015.F 2030")
        (annee_dir / "quebec.json").write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        parametres = load_parameters(2030, Juridiction.QUEBEC, chemin_racine=tmp_path)
        assert parametres.frequence_paie.nb_periodes_annuelles == 26


# ---------------------------------------------------------------------------
# Paramètre optionnel ``chemin_racine`` (Req 9.9)
# ---------------------------------------------------------------------------


class TestCheminRacineOptionnel:
    """Req 9.9 — ``load_parameters`` accepte un paramètre optionnel
    ``chemin_racine`` permettant d'injecter un dossier de test. Par défaut,
    il utilise le dossier ``parameters/`` de la racine du projet.
    """

    def test_chemin_racine_par_defaut_pointe_vers_parameters(self) -> None:
        # Sans argument ``chemin_racine``, le loader DOIT trouver le dossier
        # ``parameters/`` de production. Ce test échoue si le résolveur pointe
        # ailleurs (ex. ``.``, un chemin absolu erroné).
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        assert parametres.annee == 2026

    def test_chemin_racine_injecte_pointant_vers_dossier_de_test(
        self, tmp_path: Path
    ) -> None:
        annee_dir = tmp_path / "2030"
        annee_dir.mkdir()
        contenu = _minimal_quebec_json(2030, 26, "Revenu Québec — TP-1015.F 2030")
        (annee_dir / "quebec.json").write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Le chargeur DOIT lire le fichier depuis ``chemin_racine`` (et NON
        # depuis le dossier ``parameters/`` de production).
        parametres = load_parameters(2030, Juridiction.QUEBEC, chemin_racine=tmp_path)
        assert parametres.annee == 2030
        assert parametres.frequence_paie.nb_periodes_annuelles == 26

    def test_chemin_racine_pointe_dans_le_bon_repertoire(self, tmp_path: Path) -> None:
        # Contre-exemple : le même appel avec un ``chemin_racine`` vide DOIT
        # échouer, prouvant que ``chemin_racine`` gouverne effectivement la
        # résolution de fichier.
        with pytest.raises(FileNotFoundError):
            load_parameters(2030, Juridiction.QUEBEC, chemin_racine=tmp_path)


# ---------------------------------------------------------------------------
# Conversion ``Decimal`` sans passage par ``float`` (Req 9.3, 9.4)
# ---------------------------------------------------------------------------


class TestConversionDecimalPure:
    """Req 9.3, 9.4 — les chaînes numériques des fichiers de paramètres
    DOIVENT être converties en ``Decimal`` via ``Decimal(str)`` uniquement,
    sans passer par ``float``. La différence est observable : ``Decimal(0.063)``
    (via float) porte des artefacts binaires (« 0,063000000000000000444... »),
    alors que ``Decimal("0.063")`` porte exactement « 0,063 ».
    """

    def test_taux_rrq_est_decimal_str_pas_decimal_float(self) -> None:
        # ``rrq.taux_cotisation_totale_employe`` = "0.063" dans le fichier
        # actuel. Après chargement, la valeur DOIT être strictement égale à
        # ``Decimal("0.063")``, ce qui prouve qu'elle n'est PAS passée par
        # ``float``.
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        valeur = parametres.rrq.taux_cotisation_totale_employe

        assert valeur == Decimal("0.063")
        # Contre-exemple : la valeur ne doit PAS être égale à ``Decimal(0.063)``
        # (construit depuis un float, avec précision aberrante).
        assert valeur != Decimal(0.063)  # noqa: PLR2004
        # La représentation string ne DOIT PAS porter d'artefacts binaires.
        assert str(valeur) == "0.063"

    def test_exemption_generale_annuelle_est_decimal_str(self) -> None:
        # ``rrq.exemption_generale_annuelle`` = "3500.00" dans le fichier actuel.
        parametres = load_parameters(2026, Juridiction.QUEBEC)
        valeur = parametres.rrq.exemption_generale_annuelle

        assert valeur == Decimal("3500.00")
        # La précision de la chaîne source est préservée : deux décimales.
        assert str(valeur) == "3500.00"


# ---------------------------------------------------------------------------
# Validation NON déclenchée à l'import du module (Req 9.7)
# ---------------------------------------------------------------------------


class TestValidationDiffereeALImport:
    """Req 9.7 — la validation du schéma DOIT être déclenchée uniquement par
    l'exécution effective de ``load_parameters``, jamais de manière proactive
    à l'import du module de chargement, ni au moment de l'initialisation d'une
    constante de module.

    Cette contrainte est déjà démontrée par le simple fait que l'import
    ``from payroll_engine.parameters_loader import ...`` en tête de ce fichier
    n'a levé aucune exception (les fichiers actuels ``parameters/2026/*.json``
    contiennent des ``"TO_FILL"`` mais l'import ne les consomme pas). Ce test
    l'énonce explicitement en re-important le module via ``importlib.reload``.
    """

    def test_import_du_module_ne_leve_pas_dexception(self) -> None:
        # Le seul fait que ce fichier de test soit chargé (import au niveau
        # module en tête) démontre déjà que l'import n'échoue pas malgré la
        # présence de ``"TO_FILL"`` dans ``parameters/2026/*.json``.
        import payroll_engine.parameters_loader as loader_module

        # Réimport explicite : re-execute le module top-level et vérifie
        # qu'aucune validation proactive n'est déclenchée.
        rechargé = importlib.reload(loader_module)

        # ``load_parameters`` doit toujours être exposé après reload.
        assert callable(rechargé.load_parameters)
        assert rechargé.ParametresAnnee is not None

    def test_import_ne_declenche_pas_missing_parameter_error(self) -> None:
        # Vérification négative explicite : le reload NE DOIT PAS lever
        # ``MissingParameterError`` (ni ``pydantic.ValidationError``), même
        # si les fichiers ``parameters/2026/*.json`` contiennent des
        # ``"TO_FILL"``.
        import payroll_engine.parameters_loader as loader_module

        # Si l'import déclenchait la validation, ``importlib.reload`` lèverait.
        try:
            importlib.reload(loader_module)
        except (MissingParameterError, pydantic.ValidationError) as exc:
            pytest.fail(
                f"L'import du module a déclenché une validation proactive "
                f"({type(exc).__name__}), ce qui viole Req 9.7 : {exc}"
            )


# ---------------------------------------------------------------------------
# Disjonction des exceptions du domaine (Req 8.2)
# ---------------------------------------------------------------------------


class TestDisjonctionExceptions:
    """Req 8.2 — ``MissingParameterError`` et ``UnsupportedPayrollCase``
    DOIVENT rester strictement disjointes. Aucune n'est une sous-classe de
    l'autre, et un ``try/except`` sur l'une ne DOIT jamais capturer l'autre.

    Cette propriété est déjà couverte par ``tests/models/test_exceptions.py``
    (tâche 3.1), mais elle est réitérée ici car explicitement demandée par la
    tâche 12.1 (elle garantit qu'un paramètre ``"TO_FILL"`` levé par le loader
    ne peut jamais être confondu avec un cas hors matrice).
    """

    def test_missing_pas_sous_classe_de_unsupported(self) -> None:
        assert not issubclass(MissingParameterError, UnsupportedPayrollCase)

    def test_unsupported_pas_sous_classe_de_missing(self) -> None:
        assert not issubclass(UnsupportedPayrollCase, MissingParameterError)


# ---------------------------------------------------------------------------
# Property 15 : Déterminisme de load_parameters (Req 9.10)
# ---------------------------------------------------------------------------


# Feature: moteur-paie-contrats, Property 15: Déterminisme de load_parameters
@pytest.mark.property
@given(
    annee=st.integers(min_value=2020, max_value=2099),
    nb_periodes=st.integers(min_value=1, max_value=53),
    source=st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        min_size=1,
        max_size=80,
    ),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_property_15_load_parameters_est_deterministe(
    annee: int,
    nb_periodes: int,
    source: str,
    tmp_path: Path,
) -> None:
    """Property 15 : *Pour tout* triplet ``(annee, juridiction, chemin_racine)``
    pointant vers un fichier de paramètres valide, deux appels successifs à
    ``load_parameters(annee, juridiction, chemin_racine)`` DOIVENT retourner
    deux instances ``ParametresAnnee`` égales au sens ``==``.

    **Validates: Requirements 9.10**

    Aucun état global n'est mis en cache entre les appels. Le chargeur DOIT
    être une fonction pure : deux appels identiques produisent deux objets
    égaux champ à champ.

    Hypothesis fait varier :

    - ``annee`` (entier dans [2020, 2099]) — teste plusieurs sous-dossiers ;
    - ``nb_periodes_annuelles`` (entier dans [1, 53]) — teste plusieurs valeurs
      dans ``frequence_paie`` ;
    - ``source`` (chaîne ASCII imprimable non vide) — teste plusieurs valeurs
      métadonnées à la racine.

    L'invariant testé est indépendant de la structure exacte du contenu :
    seule compte la relation « deux appels identiques → objets ``==`` ».
    """

    # Isoler chaque itération Hypothesis dans un sous-dossier dédié pour
    # éviter les collisions entre exécutions successives dans le même
    # ``tmp_path`` (function-scoped mais réutilisé par Hypothesis).
    iter_root = tmp_path / f"annee_{annee}_np_{nb_periodes}"
    iter_root.mkdir(exist_ok=True)
    annee_dir = iter_root / str(annee)
    annee_dir.mkdir(exist_ok=True)

    contenu = _minimal_quebec_json(annee, nb_periodes, source)
    (annee_dir / "quebec.json").write_text(
        json.dumps(contenu, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Deux appels successifs identiques : le second NE DOIT PAS bénéficier
    # d'un cache ni voir un état différent.
    parametres_1 = load_parameters(annee, Juridiction.QUEBEC, chemin_racine=iter_root)
    parametres_2 = load_parameters(annee, Juridiction.QUEBEC, chemin_racine=iter_root)

    # Égalité au sens ``==`` (champ à champ, garantie par Pydantic v2 pour
    # les modèles ``frozen=True``).
    assert parametres_1 == parametres_2
    # Ce sont deux instances distinctes (pas d'aliasing via un cache global).
    assert parametres_1 is not parametres_2


# ---------------------------------------------------------------------------
# Mécanisme de repli ``nb_periodes_annuelles`` (Task 12.4, Req 2.7)
# ---------------------------------------------------------------------------


# Import local du helper au niveau module ne serait pas atteint tant que
# ``load_nb_periodes_annuelles`` n'existe pas (tâche 12.4 non réalisée).
# Une fois le helper implémenté, l'import fonctionne — la discipline TDD
# de la règle 06 impose d'importer directement pour que la collection
# pytest révèle immédiatement toute régression de nom d'API.
from payroll_engine.parameters_loader import load_nb_periodes_annuelles  # noqa: E402


class TestReplNbPeriodesAnnuellesBrancheA:
    """Req 2.7, branche (a) — ``parameters/<annee>/<juridiction>.json`` existe
    et contient ``frequence_paie.nb_periodes_annuelles``. Le repli DOIT lire
    la valeur depuis le fichier de l'année courante et exposer
    ``source_effective = "annee_courante"``.
    """

    def test_annee_courante_lit_depuis_le_fichier_correspondant(
        self, tmp_path: Path
    ) -> None:
        # Créer parameters/2026/quebec.json avec nb_periodes_annuelles=27
        # (année à 27 paies, cas Camp LilySO 2026).
        annee_dir = tmp_path / "2026"
        annee_dir.mkdir()
        contenu = _minimal_quebec_json(2026, 27, "Revenu Québec — TP-1015.F 2026")
        (annee_dir / "quebec.json").write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        valeur, source_effective = load_nb_periodes_annuelles(
            2026, Juridiction.QUEBEC, chemin_racine=tmp_path
        )

        assert valeur == 27
        assert source_effective == "annee_courante"

    def test_annee_courante_meme_si_annee_precedente_existe(
        self, tmp_path: Path
    ) -> None:
        # Contre-exemple : si (a) ET (b) existent, la branche (a) DOIT
        # gagner. Ici l'année courante 2027 porte 26, l'année précédente
        # 2026 porte 27 — le repli DOIT retenir 26 avec "annee_courante"
        # et jamais 27 avec "repli_annee_2026".
        annee_courante_dir = tmp_path / "2027"
        annee_courante_dir.mkdir()
        contenu_2027 = _minimal_quebec_json(2027, 26, "Revenu Québec — TP-1015.F 2027")
        (annee_courante_dir / "quebec.json").write_text(
            json.dumps(contenu_2027, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        annee_precedente_dir = tmp_path / "2026"
        annee_precedente_dir.mkdir()
        contenu_2026 = _minimal_quebec_json(2026, 27, "Revenu Québec — TP-1015.F 2026")
        (annee_precedente_dir / "quebec.json").write_text(
            json.dumps(contenu_2026, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        valeur, source_effective = load_nb_periodes_annuelles(
            2027, Juridiction.QUEBEC, chemin_racine=tmp_path
        )

        assert valeur == 26
        assert source_effective == "annee_courante"


class TestReplNbPeriodesAnnuellesBrancheB:
    """Req 2.7, branche (b) — ``parameters/<annee>/<juridiction>.json`` est
    absent, mais ``parameters/<annee - 1>/<juridiction>.json`` existe et
    contient ``frequence_paie.nb_periodes_annuelles``. Le repli DOIT lire
    la valeur depuis le fichier de l'année précédente et exposer
    ``source_effective = "repli_annee_<AAAA>"``.
    """

    def test_annee_precedente_utilisee_si_annee_courante_absente(
        self, tmp_path: Path
    ) -> None:
        # Créer uniquement parameters/2026/quebec.json (année précédente),
        # PAS parameters/2027/*. Requête pour 2027 → repli vers 2026.
        annee_precedente_dir = tmp_path / "2026"
        annee_precedente_dir.mkdir()
        contenu = _minimal_quebec_json(2026, 27, "Revenu Québec — TP-1015.F 2026")
        (annee_precedente_dir / "quebec.json").write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        valeur, source_effective = load_nb_periodes_annuelles(
            2027, Juridiction.QUEBEC, chemin_racine=tmp_path
        )

        assert valeur == 27
        assert source_effective == "repli_annee_2026"

    def test_repli_ne_saute_pas_deux_annees(self, tmp_path: Path) -> None:
        # Contre-exemple : le repli s'arrête à l'année précédente. Si
        # 2028 est demandée et que seule 2026 est disponible (2027
        # manquante), le repli NE DOIT PAS remonter jusqu'à 2026 — il
        # DOIT tomber sur la valeur par défaut (branche (c)).
        annee_2026_dir = tmp_path / "2026"
        annee_2026_dir.mkdir()
        contenu = _minimal_quebec_json(2026, 27, "Revenu Québec — TP-1015.F 2026")
        (annee_2026_dir / "quebec.json").write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        valeur, source_effective = load_nb_periodes_annuelles(
            2028, Juridiction.QUEBEC, chemin_racine=tmp_path
        )

        # Design §Components 10 documente uniquement (a) → (b) → (c). Il
        # n'y a PAS de saut à ``annee - 2``.
        assert valeur == 26  # valeur par défaut documentée
        assert source_effective == "valeur_par_defaut"


class TestReplNbPeriodesAnnuellesBrancheC:
    """Req 2.7, branche (c) — aucun fichier disponible pour l'année courante
    ni pour l'année précédente. Le repli DOIT retourner la valeur par
    défaut ``26`` avec ``source_effective = "valeur_par_defaut"``.
    """

    def test_valeur_par_defaut_quand_aucun_fichier_disponible(
        self, tmp_path: Path
    ) -> None:
        # ``tmp_path`` est vide : ni parameters/2099/ ni parameters/2098/
        # n'existent.
        valeur, source_effective = load_nb_periodes_annuelles(
            2099, Juridiction.QUEBEC, chemin_racine=tmp_path
        )

        # 26 est la valeur par défaut documentée pour une année
        # bi-hebdomadaire standard (design §Components 10).
        assert valeur == 26
        assert source_effective == "valeur_par_defaut"

    def test_valeur_par_defaut_meme_avec_dossiers_annee_vides(
        self, tmp_path: Path
    ) -> None:
        # Cas limite : les sous-dossiers d'année existent mais aucun
        # fichier JSON n'y est présent. Le repli DOIT malgré tout
        # atteindre la branche (c) sans lever d'exception.
        (tmp_path / "2099").mkdir()
        (tmp_path / "2098").mkdir()

        valeur, source_effective = load_nb_periodes_annuelles(
            2099, Juridiction.QUEBEC, chemin_racine=tmp_path
        )

        assert valeur == 26
        assert source_effective == "valeur_par_defaut"
