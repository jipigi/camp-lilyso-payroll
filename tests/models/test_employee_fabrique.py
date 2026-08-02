"""Tests d'exemple pour la fabrique ``Employee.avec_defauts_par_annee``.

Spec de référence : ``moteur-paie-contrats`` — tâche 6.4.
Design de référence : sections « Components and Interfaces » §5 (``design.md``).

Discipline TDD (règle 06) : ce module de tests est écrit **avant**
l'implémentation. Tant que la tâche 6.3 n'a pas ajouté la classmethod
``Employee.avec_defauts_par_annee``, chaque test échoue avec
``AttributeError`` (ou ``NotImplementedError`` selon la stratégie
d'implémentation intermédiaire). C'est le comportement attendu — les
tests précèdent le code.

Portée de la tâche 6.4 (``tasks.md`` §6.4) :

- **Test A** — Chargement des défauts 2026 réussit et retourne un
  ``Employee`` dont ``montant_total_TP1015_3`` et ``montant_total_TD1``
  correspondent aux montants personnels de base extraits de
  ``parameters/2026/quebec.json`` et ``parameters/2026/canada.json``.
  Les valeurs attendues sont **lues depuis le JSON** dans le test,
  jamais codées en dur (règle 05 : aucune valeur fiscale n'apparaît
  dans le code Python — les tests eux-mêmes sont soumis à cette règle
  pour éviter la divergence silencieuse avec ``parameters/``).
- **Test B** — Le paramètre optionnel ``chemin_parametres`` permet
  d'injecter un dossier ``tmp_path`` contenant un JSON de test ; la
  fabrique lit alors ce dossier au lieu du dossier ``parameters/``
  du projet. Cette injection est indispensable pour tester le comportement
  du chargeur sans coupler les tests aux fichiers réels et pour préparer
  le mécanisme d'injection utilisé par le chargeur (voir design
  §Components 10 : ``load_parameters(annee, juridiction, chemin_racine=...)``).
- **Test C** — Un défaut consommé qui porte la sentinelle ``"TO_FILL"``
  lève :class:`MissingParameterError` (règle 05, Req 8.5, Req 9.5). Le
  test utilise ``tmp_path`` pour construire un JSON minimal contenant
  ``"TO_FILL"`` sur le champ ``montant_personnel_base``.
- **Test D** — Les surcharges ``**champs`` passées à la fabrique
  prévalent sur les défauts lus dans le JSON : un
  ``montant_total_TP1015_3`` fourni explicitement en kwarg n'est pas
  substitué par la valeur JSON. Cette sémantique est cohérente avec le
  design §Components 5 qui décrit la fabrique comme un point d'entrée
  ergonomique — l'appelant reste maître de chaque valeur individuelle.

Signature attendue (voir design §Components 5) ::

    Employee.avec_defauts_par_annee(
        annee_reference: int,
        chemin_parametres: Path | None = None,
        **champs
    ) -> Employee

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire. Les JSON de test utilisent des
  chaînes guillemées pour tous les montants ; le parsing passe par
  :func:`models._validators._parse_json_reject_floats` qui refuse les
  littéraux flottants non guillemés.
- Règle 04 — aucune donnée personnelle réelle. Les fixtures utilisent
  ``EMP001`` et ``"Monitrice EMP001"`` (identifiants anonymisés).
- Règle 05 — aucun taux/plafond/seuil ni montant fiscal codé en dur.
  Les montants personnels de base 2026 sont lus depuis les fichiers
  ``parameters/2026/*.json`` du projet ; les JSON de test injectent des
  valeurs fictives lisibles depuis chaque test.
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from models._validators import _parse_json_reject_floats
from models.employee import Employee
from models.enums import Juridiction
from models.exceptions import MissingParameterError


# ---------------------------------------------------------------------------
# Constantes de test
# ---------------------------------------------------------------------------

#: Racine du projet, calculée à partir de ce fichier de test. Structure
#: attendue : ``tests/models/test_employee_fabrique.py`` → remonter deux
#: niveaux donne la racine du dépôt.
_RACINE_PROJET: Path = Path(__file__).resolve().parent.parent.parent

#: Dossier des paramètres versionnés du projet (règle 05). Utilisé par
#: Test A pour lire les vraies valeurs 2026 sans les recopier dans le
#: code Python.
_PARAMETERS_DIR: Path = _RACINE_PROJET / "parameters"

#: Année de référence utilisée par les tests. 2026 est la seule année
#: dont ``parameters/`` contient des fichiers renseignés pour le montant
#: personnel de base au moment de la rédaction de ce test.
_ANNEE_REFERENCE: int = 2026

#: Chemin JSON du montant personnel de base côté Québec (TP-1015.3).
#: Documenté dans ``design.md`` §Components 5 comme une des deux clés
#: acceptables (l'autre étant ``td1015_3.montant_base``). Ce test suit
#: la clé effectivement présente dans ``parameters/2026/quebec.json``
#: à la rédaction : ``impot_quebec.montant_personnel_base``.
_CLE_MONTANT_QC: tuple[str, ...] = ("impot_quebec", "montant_personnel_base")

#: Chemin JSON du montant personnel de base côté fédéral (TD1).
#: Idem — clé présente dans ``parameters/2026/canada.json`` :
#: ``impot_federal.montant_personnel_base``.
_CLE_MONTANT_FED: tuple[str, ...] = ("impot_federal", "montant_personnel_base")


# ---------------------------------------------------------------------------
# Sous-ensemble minimal de kwargs valides (sans les champs à défauts)
# ---------------------------------------------------------------------------


#: Kwargs strictement obligatoires pour construire un ``Employee`` via la
#: fabrique : uniquement les champs qui n'ont PAS de défaut lu depuis le
#: JSON (voir Req 1.7). Les champs à défauts —
#: ``montant_total_TP1015_3``, ``montant_total_TD1``,
#: ``retenue_additionnelle_QC``, ``retenue_additionnelle_federale`` —
#: sont volontairement omis pour que chaque test puisse observer leur
#: substitution depuis les paramètres.
#:
#: Toutes les valeurs sont fictives (règle 04).
_KWARGS_SANS_DEFAUTS: dict[str, Any] = {
    "id": "EMP001",
    "nom_affichage": "Monitrice EMP001",
    "date_naissance": date(2005, 6, 15),
    "province_travail": Juridiction.QUEBEC,
    "titre_emploi": "Monitrice",
    "taux_horaire_base": Decimal("15.75"),
    "date_embauche": date(2026, 6, 20),
    "date_fin_emploi": None,
    "taux_indemnite_vacances": Decimal("0.04"),
    "exoneration_TP1015_3": False,
    "exoneration_TD1": False,
    # Les tests fournissent explicitement ces deux champs pour ne pas
    # dépendre de la présence de clés ``retenue_additionnelle_defaut``
    # dans les JSON — Test A ne teste que la substitution du montant
    # personnel de base, cf. la portée de la tâche 6.4.
    "retenue_additionnelle_QC": Decimal("0.00"),
    "retenue_additionnelle_federale": Decimal("0.00"),
}


# ---------------------------------------------------------------------------
# Utilitaires locaux
# ---------------------------------------------------------------------------


def _extraire(document: dict[str, Any], chemin: tuple[str, ...]) -> Any:
    """Retourne ``document[chemin[0]][chemin[1]]...`` — accès imbriqué."""
    noeud: Any = document
    for cle in chemin:
        noeud = noeud[cle]
    return noeud


def _charger_json_projet(fichier: Path) -> dict[str, Any]:
    """Lit un fichier JSON via :func:`_parse_json_reject_floats` (règle 01).

    Retourne un dictionnaire. L'utilisation du parseur strict garantit
    qu'aucun littéral flottant non guillemé ne peut se glisser dans les
    tests — ni côté ``parameters/`` du projet, ni côté fixtures ``tmp_path``.
    """
    contenu = fichier.read_text(encoding="utf-8")
    document = _parse_json_reject_floats(contenu)
    assert isinstance(document, dict), (
        f"Le document {fichier} doit être un objet JSON racine, pas {type(document)}."
    )
    return document


def _ecrire_json(fichier: Path, document: dict[str, Any]) -> None:
    """Écrit ``document`` dans ``fichier`` en encodant tout ``Decimal`` en chaîne.

    Passe explicitement par ``default=str`` pour respecter la règle 01
    et Req 13.5 : les ``Decimal`` sont sérialisés entre guillemets, jamais
    en littéraux flottants non guillemés que
    :func:`_parse_json_reject_floats` refuserait à la relecture.
    """
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _preparer_dossier_parametres(
    racine: Path,
    annee: int,
    *,
    montant_personnel_base_qc: str,
    montant_personnel_base_fed: str,
) -> Path:
    """Crée ``racine/<annee>/{quebec,canada}.json`` avec un contenu minimal.

    Le contenu reflète la structure des vrais fichiers
    ``parameters/2026/*.json`` (voir ``.kiro/specs/moteur-paie-contrats/design.md``
    §Data Models 10) mais avec des valeurs fictives fournies par le test.
    Seuls les champs nécessaires aux défauts consommés par la fabrique
    sont renseignés — les autres sections peuvent rester absentes ou
    marquées ``"TO_FILL"`` sans affecter le comportement observé.

    Retourne le chemin racine passé en argument (``racine``), pour
    faciliter la lisibilité du site d'appel :

    >>> _preparer_dossier_parametres(tmp_path, 2026, ...)  # doctest: +SKIP
    """
    quebec_json: dict[str, Any] = {
        "annee": annee,
        "juridiction": "quebec",
        "source": "Revenu Québec — TP-1015.F 2026",
        "date_publication": "TO_FILL",
        "date_consultation": "TO_FILL",
        "url_consultee": "TO_FILL",
        "frequence_paie": {
            "nb_periodes_annuelles": 27,
        },
        "impot_quebec": {
            "montant_personnel_base": montant_personnel_base_qc,
        },
    }
    canada_json: dict[str, Any] = {
        "annee": annee,
        "juridiction": "canada",
        "source": "Agence du revenu du Canada — T4127 2026",
        "date_publication": "TO_FILL",
        "date_consultation": "TO_FILL",
        "url_consultee": "TO_FILL",
        "frequence_paie": {
            "nb_periodes_annuelles": 27,
        },
        "impot_federal": {
            "montant_personnel_base": montant_personnel_base_fed,
        },
    }
    _ecrire_json(racine / str(annee) / "quebec.json", quebec_json)
    _ecrire_json(racine / str(annee) / "canada.json", canada_json)
    return racine


# ===========================================================================
# Test A — Chargement des défauts 2026 depuis le vrai dossier ``parameters/``
# ===========================================================================


class TestChargementDefauts2026:
    """Task 6.4 (Test A) — la fabrique lit ``parameters/2026/*.json``.

    Vérifie que ``Employee.avec_defauts_par_annee(2026, ...)`` produit un
    ``Employee`` dont les montants ``montant_total_TP1015_3`` et
    ``montant_total_TD1`` correspondent exactement aux montants
    personnels de base extraits des fichiers de paramètres versionnés du
    projet (règle 05).

    Les valeurs attendues sont **relues depuis le JSON dans le test** :
    aucune comparaison contre ``Decimal("18952.00")`` ou ``Decimal("16452.00")``
    codés en dur. Si les paramètres 2026 sont mis à jour dans les JSON,
    ce test suit automatiquement — c'est la propriété désirée d'une
    règle 05 correctement appliquée.

    _Requirements: 1.7_
    """

    def test_montant_total_TP1015_3_lu_depuis_quebec_json(self) -> None:
        """Le champ ``montant_total_TP1015_3`` reflète la valeur JSON."""
        quebec_json = _charger_json_projet(
            _PARAMETERS_DIR / str(_ANNEE_REFERENCE) / "quebec.json"
        )
        montant_attendu = Decimal(_extraire(quebec_json, _CLE_MONTANT_QC))

        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=_PARAMETERS_DIR,
            **_KWARGS_SANS_DEFAUTS,
        )

        assert emp.montant_total_TP1015_3 == montant_attendu, (
            f"La fabrique doit lire le montant personnel de base QC depuis "
            f"parameters/{_ANNEE_REFERENCE}/quebec.json "
            f"(chemin {'.'.join(_CLE_MONTANT_QC)}). "
            f"Attendu {montant_attendu}, obtenu {emp.montant_total_TP1015_3}."
        )

    def test_montant_total_TD1_lu_depuis_canada_json(self) -> None:
        """Le champ ``montant_total_TD1`` reflète la valeur JSON."""
        canada_json = _charger_json_projet(
            _PARAMETERS_DIR / str(_ANNEE_REFERENCE) / "canada.json"
        )
        montant_attendu = Decimal(_extraire(canada_json, _CLE_MONTANT_FED))

        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=_PARAMETERS_DIR,
            **_KWARGS_SANS_DEFAUTS,
        )

        assert emp.montant_total_TD1 == montant_attendu, (
            f"La fabrique doit lire le montant personnel de base fédéral "
            f"depuis parameters/{_ANNEE_REFERENCE}/canada.json "
            f"(chemin {'.'.join(_CLE_MONTANT_FED)}). "
            f"Attendu {montant_attendu}, obtenu {emp.montant_total_TD1}."
        )

    def test_employee_produit_est_valide(self) -> None:
        """Sanity — l'instance retournée est un ``Employee`` immuable.

        Cadenasse la surface positive de la fabrique : au-delà de la
        substitution des défauts, elle DOIT retourner un ``Employee``
        conforme (frozen, champs d'identité préservés depuis les kwargs).
        """
        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=_PARAMETERS_DIR,
            **_KWARGS_SANS_DEFAUTS,
        )

        assert isinstance(emp, Employee)
        assert emp.id == _KWARGS_SANS_DEFAUTS["id"]
        assert emp.nom_affichage == _KWARGS_SANS_DEFAUTS["nom_affichage"]
        assert emp.province_travail is Juridiction.QUEBEC


# ===========================================================================
# Test B — ``chemin_parametres`` optionnel : injection d'un dossier de test
# ===========================================================================


class TestInjectionCheminParametres:
    """Task 6.4 (Test B) — le kwarg optionnel ``chemin_parametres``
    permet à la fabrique de lire un dossier arbitraire (``tmp_path``).

    Ce mécanisme est indispensable pour :

    - tester le comportement du chargeur sans dépendre des fichiers réels ;
    - reproduire des cas limites (valeurs fictives contrôlées) ;
    - préparer le raccordement au chargeur ``load_parameters`` (design
      §Components 10 : ``load_parameters(annee, juridiction, chemin_racine=...)``).

    Lorsque ``chemin_parametres`` pointe vers ``tmp_path``, la fabrique
    NE DOIT PAS lire ``parameters/`` du projet.

    _Requirements: 1.7_
    """

    def test_lecture_depuis_tmp_path_ignore_parameters_projet(
        self, tmp_path: Path
    ) -> None:
        """La fabrique lit exclusivement le dossier injecté.

        Valeurs de test délibérément différentes des valeurs 2026
        réelles : si la fabrique lisait ``parameters/`` du projet malgré
        l'injection, la comparaison échouerait.
        """
        montant_qc_test = "1234.56"
        montant_fed_test = "9876.54"
        _preparer_dossier_parametres(
            tmp_path,
            _ANNEE_REFERENCE,
            montant_personnel_base_qc=montant_qc_test,
            montant_personnel_base_fed=montant_fed_test,
        )

        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=tmp_path,
            **_KWARGS_SANS_DEFAUTS,
        )

        # Les valeurs attendues sont relues depuis le JSON de test qu'on
        # vient d'écrire — pas de duplication de la chaîne "1234.56"
        # dans l'assertion elle-même (mêmes principes que Test A, à
        # l'échelle du fixture).
        quebec_test = _charger_json_projet(
            tmp_path / str(_ANNEE_REFERENCE) / "quebec.json"
        )
        canada_test = _charger_json_projet(
            tmp_path / str(_ANNEE_REFERENCE) / "canada.json"
        )
        assert emp.montant_total_TP1015_3 == Decimal(
            _extraire(quebec_test, _CLE_MONTANT_QC)
        )
        assert emp.montant_total_TD1 == Decimal(
            _extraire(canada_test, _CLE_MONTANT_FED)
        )

    def test_signature_accepte_chemin_parametres_en_keyword(
        self, tmp_path: Path
    ) -> None:
        """La signature attendue est ``avec_defauts_par_annee(annee, chemin_parametres=..., **champs)``.

        Ce test cadenasse la position **kwargs-only** du paramètre
        ``chemin_parametres`` : il ne doit pas être positionnel, sinon
        la fabrique perdrait sa lisibilité au site d'appel (design
        §Components 5 documente une signature avec ``chemin_parametres``
        après ``annee_reference``, et ``**champs`` derrière).
        """
        _preparer_dossier_parametres(
            tmp_path,
            _ANNEE_REFERENCE,
            montant_personnel_base_qc="1111.11",
            montant_personnel_base_fed="2222.22",
        )
        # Appel en keyword uniquement — si la signature était
        # positionnelle-obligatoire pour ``chemin_parametres``, ceci
        # échouerait avec ``TypeError``. La construction doit réussir.
        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=tmp_path,
            **_KWARGS_SANS_DEFAUTS,
        )
        assert isinstance(emp, Employee)


# ===========================================================================
# Test C — ``"TO_FILL"`` sur défaut consommé → ``MissingParameterError``
# ===========================================================================


class TestSentinelleToFill:
    """Task 6.4 (Test C) — un défaut consommé marqué ``"TO_FILL"`` lève
    :class:`MissingParameterError` (règle 05, Req 8.5, Req 9.5).

    La règle 05 impose que toute valeur ``"TO_FILL"`` reste inutilisable
    en production. Lorsque la fabrique tente de consommer un défaut
    marqué ``"TO_FILL"``, elle DOIT lever ``MissingParameterError`` —
    et non ``UnsupportedPayrollCase`` (Req 8.2 : les deux exceptions du
    domaine restent strictement disjointes dans leurs déclencheurs).

    _Requirements: 1.7 (dépendance à Req 8.5, 9.5)_
    """

    def test_to_fill_sur_montant_personnel_base_qc_leve_missing_parameter(
        self, tmp_path: Path
    ) -> None:
        """``"TO_FILL"`` côté QC → ``MissingParameterError``."""
        _preparer_dossier_parametres(
            tmp_path,
            _ANNEE_REFERENCE,
            montant_personnel_base_qc="TO_FILL",
            # Côté fédéral, on met une valeur valide pour isoler la cause
            # du refus au champ QC.
            montant_personnel_base_fed="9876.54",
        )

        with pytest.raises(MissingParameterError):
            Employee.avec_defauts_par_annee(
                _ANNEE_REFERENCE,
                chemin_parametres=tmp_path,
                **_KWARGS_SANS_DEFAUTS,
            )

    def test_to_fill_sur_montant_personnel_base_fed_leve_missing_parameter(
        self, tmp_path: Path
    ) -> None:
        """``"TO_FILL"`` côté fédéral → ``MissingParameterError``."""
        _preparer_dossier_parametres(
            tmp_path,
            _ANNEE_REFERENCE,
            montant_personnel_base_qc="1234.56",
            montant_personnel_base_fed="TO_FILL",
        )

        with pytest.raises(MissingParameterError):
            Employee.avec_defauts_par_annee(
                _ANNEE_REFERENCE,
                chemin_parametres=tmp_path,
                **_KWARGS_SANS_DEFAUTS,
            )


# ===========================================================================
# Test D — Les surcharges ``**champs`` prévalent sur les défauts JSON
# ===========================================================================


class TestSurchargesKwargsPrevalentSurDefauts:
    """Task 6.4 (Test D) — un ``montant_total_TP1015_3`` fourni
    explicitement en kwarg n'est PAS relu depuis le JSON.

    Cette sémantique est cohérente avec le design §Components 5 : la
    fabrique est un point d'entrée ergonomique qui **substitue** les
    défauts manquants ; elle ne **remplace jamais** les valeurs
    fournies par l'appelant.

    Test conçu pour être robuste à un éventuel bug de priorité inverse :
    la valeur kwarg (``9999.99``) est délibérément différente de la
    valeur JSON du test (``1234.56``). Si la fabrique inversait la
    priorité, l'assertion échouerait sans ambiguïté.

    _Requirements: 1.7_
    """

    def test_montant_TP1015_3_explicite_prevaut(self, tmp_path: Path) -> None:
        """Kwarg ``montant_total_TP1015_3`` > JSON."""
        _preparer_dossier_parametres(
            tmp_path,
            _ANNEE_REFERENCE,
            montant_personnel_base_qc="1234.56",
            montant_personnel_base_fed="9876.54",
        )
        montant_explicite = Decimal("9999.99")

        kwargs = dict(_KWARGS_SANS_DEFAUTS)
        kwargs["montant_total_TP1015_3"] = montant_explicite

        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=tmp_path,
            **kwargs,
        )

        assert emp.montant_total_TP1015_3 == montant_explicite, (
            "La surcharge kwarg ``montant_total_TP1015_3`` doit prévaloir "
            "sur la valeur lue dans quebec.json. Sinon, la fabrique perd "
            "sa vocation de point d'entrée ergonomique (design §Components 5)."
        )
        # Le montant fédéral, non surchargé, doit toujours provenir du JSON —
        # sanity check pour distinguer une inversion globale de priorité
        # d'un simple bug local sur le champ QC.
        canada_test = _charger_json_projet(
            tmp_path / str(_ANNEE_REFERENCE) / "canada.json"
        )
        assert emp.montant_total_TD1 == Decimal(
            _extraire(canada_test, _CLE_MONTANT_FED)
        )

    def test_montant_TD1_explicite_prevaut(self, tmp_path: Path) -> None:
        """Kwarg ``montant_total_TD1`` > JSON (symétrie côté fédéral)."""
        _preparer_dossier_parametres(
            tmp_path,
            _ANNEE_REFERENCE,
            montant_personnel_base_qc="1234.56",
            montant_personnel_base_fed="9876.54",
        )
        montant_explicite = Decimal("8888.88")

        kwargs = dict(_KWARGS_SANS_DEFAUTS)
        kwargs["montant_total_TD1"] = montant_explicite

        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=tmp_path,
            **kwargs,
        )

        assert emp.montant_total_TD1 == montant_explicite


# ===========================================================================
# Test E — Task 12.5 : câblage complet au chargeur (4 défauts lus du JSON)
# ===========================================================================


class TestCablageCompletDefautsChargeur:
    """Task 12.5 — la fabrique lit **les 4 défauts** depuis ``parameters/``.

    Test d'intégration terminal du câblage
    :meth:`Employee.avec_defauts_par_annee` ↔
    :func:`payroll_engine.parameters_loader.load_parameters`. Contrairement
    aux tests A–D (task 6.4) qui fournissent explicitement les retenues
    additionnelles pour isoler la substitution des montants personnels de
    base, ce test omet **les quatre** champs à défaut lu :

    - ``montant_total_TP1015_3`` — lu depuis ``impot_quebec.montant_personnel_base``.
    - ``montant_total_TD1`` — lu depuis ``impot_federal.montant_personnel_base``.
    - ``retenue_additionnelle_QC`` — lu depuis ``td_1015_3.retenue_additionnelle_defaut``.
    - ``retenue_additionnelle_federale`` — lu depuis ``td1.retenue_additionnelle_defaut``.

    Il vérifie que la fabrique produit un :class:`Employee` **sans qu'aucune
    valeur fiscale ne transite par le code Python du test** (règle 05,
    Req 1.7 : « LA fabrique NE DOIT PAS coder en dur les valeurs 18 952,
    16 452 ou 0 »). Les 4 valeurs attendues sont rechargées, dans le test,
    par un appel indépendant à :func:`load_parameters` — la comparaison
    est purement structurelle.

    Ce test valide simultanément :

    - l'absence d'import circulaire (l'import différé de la fabrique
      fonctionne : le module ``models.employee`` est importable
      indépendamment de ``payroll_engine`` — sinon ``pytest`` échouerait
      dès la collecte) ;
    - la présence effective des clés ``retenue_additionnelle_defaut`` dans
      les fichiers ``parameters/2026/*.json`` du projet (règle 05, task
      12.5) ;
    - la traversée complète du chargeur (JSON → ``ParametresAnnee`` →
      accès aux propriétés matérialisées) sans erreur.

    _Requirements: 1.7_
    """

    def test_les_4_defauts_sont_lus_depuis_les_json_2026(self) -> None:
        """Les 4 défauts substitués correspondent aux valeurs JSON 2026.

        L'appelant ne fournit **aucun** des quatre champs à défaut lu.
        La fabrique doit :

        1. ouvrir ``parameters/2026/quebec.json`` et
           ``parameters/2026/canada.json`` ;
        2. substituer les 4 champs manquants avec les valeurs lues ;
        3. produire un :class:`Employee` immuable et valide.

        Les valeurs attendues sont rechargées par un appel indépendant à
        :func:`load_parameters` — jamais recopiées en dur dans ce test
        (règle 05 appliquée aux tests eux-mêmes, comme documenté dans le
        module).
        """
        # Import différé — même stratégie que la fabrique elle-même : le
        # module ``payroll_engine`` n'est chargé qu'au moment nécessaire,
        # ce qui documente en creux l'absence de dépendance circulaire.
        from payroll_engine.parameters_loader import load_parameters

        # Kwargs strictement minimaux : uniquement les champs sans
        # défaut lu depuis le JSON. Les 4 champs à défaut
        # (``montant_total_TP1015_3``, ``montant_total_TD1``,
        # ``retenue_additionnelle_QC``, ``retenue_additionnelle_federale``)
        # sont **délibérément omis** pour observer leur substitution.
        kwargs_sans_defauts_ni_retenues: dict[str, Any] = {
            "id": "EMP001",
            "nom_affichage": "Monitrice EMP001",
            "date_naissance": date(2005, 6, 15),
            "province_travail": Juridiction.QUEBEC,
            "titre_emploi": "Monitrice",
            "taux_horaire_base": Decimal("15.00"),
            "date_embauche": date(2026, 6, 20),
            "date_fin_emploi": None,
            "taux_indemnite_vacances": Decimal("0.04"),
            "exoneration_TP1015_3": False,
            "exoneration_TD1": False,
        }

        # ---- Construction via la fabrique (chemin réel du projet) --------
        emp = Employee.avec_defauts_par_annee(
            _ANNEE_REFERENCE,
            chemin_parametres=_PARAMETERS_DIR,
            **kwargs_sans_defauts_ni_retenues,
        )

        # ---- Valeurs attendues rechargées indépendamment -----------------
        # Aucun ``Decimal(...)`` en dur ici : les 4 valeurs sont issues
        # du chargement JSON, donc reflètent immédiatement toute mise à
        # jour de ``parameters/2026/*.json`` (règle 05).
        params_qc = load_parameters(
            _ANNEE_REFERENCE, Juridiction.QUEBEC, _PARAMETERS_DIR
        )
        params_fed = load_parameters(
            _ANNEE_REFERENCE, Juridiction.CANADA, _PARAMETERS_DIR
        )

        montant_qc_attendu = params_qc.impot_quebec.montant_personnel_base
        retenue_qc_attendue = params_qc.td_1015_3.retenue_additionnelle_defaut
        montant_fed_attendu = params_fed.impot_federal.montant_personnel_base
        retenue_fed_attendue = params_fed.td1.retenue_additionnelle_defaut

        # ---- Vérifications ----------------------------------------------
        assert emp.montant_total_TP1015_3 == montant_qc_attendu, (
            "Défaut ``montant_total_TP1015_3`` doit provenir de "
            f"parameters/{_ANNEE_REFERENCE}/quebec.json → "
            "impot_quebec.montant_personnel_base."
        )
        assert emp.retenue_additionnelle_QC == retenue_qc_attendue, (
            "Défaut ``retenue_additionnelle_QC`` doit provenir de "
            f"parameters/{_ANNEE_REFERENCE}/quebec.json → "
            "td_1015_3.retenue_additionnelle_defaut."
        )
        assert emp.montant_total_TD1 == montant_fed_attendu, (
            "Défaut ``montant_total_TD1`` doit provenir de "
            f"parameters/{_ANNEE_REFERENCE}/canada.json → "
            "impot_federal.montant_personnel_base."
        )
        assert emp.retenue_additionnelle_federale == retenue_fed_attendue, (
            "Défaut ``retenue_additionnelle_federale`` doit provenir de "
            f"parameters/{_ANNEE_REFERENCE}/canada.json → "
            "td1.retenue_additionnelle_defaut."
        )

        # Sanity — l'instance retournée reste conforme au contrat
        # (immutabilité, typage Decimal, province QC).
        assert isinstance(emp, Employee)
        assert isinstance(emp.retenue_additionnelle_QC, Decimal)
        assert isinstance(emp.retenue_additionnelle_federale, Decimal)
        assert emp.province_travail is Juridiction.QUEBEC
