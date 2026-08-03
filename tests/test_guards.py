"""Tests de garde statique du moteur de paie Camp LilySO.

Spec de référence : ``moteur-paie-contrats`` — section 15 (tâches 15.1
à 15.5).

Ces cinq tests de garde protègent les invariants transversaux du
projet **par introspection** (models et code source) plutôt que par
exécution de calculs fiscaux. Ils sont indépendants des golden tests
(section 14) et ne consomment donc pas le marqueur ``@pytest.mark.golden``.

Cinq classes de tests, chacune couvrant un requirement structurant :

- :class:`TestNoFloatFields` — Req 10.3 (aucun champ ``float`` dans les
  12 modèles du domaine).
- :class:`TestNoHardcodedFiscalValues` — règle 05 (aucune valeur fiscale
  codée en dur dans ``models/`` ou ``payroll_engine/``).
- :class:`TestExceptionHierarchyDisjoint` — Req 8.2, 8.7 (disjonction
  stricte entre exceptions du domaine et :class:`pydantic.ValidationError`).
- :class:`TestExceptionMessageContract` — Req 8.3, 8.6, 11.6 &
  Property 16 (contrat de contenu des messages d'exception).
- :class:`TestNoPersonalDataInFixtures` — règle 04 (aucune donnée
  personnelle réelle dans les fixtures).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit (couvert par
  :class:`TestNoFloatFields`).
- Règle 03 — périmètre Camp LilySO strict, refus fail-fast hors matrice
  (couvert par :class:`TestExceptionMessageContract`).
- Règle 04 — aucune donnée personnelle sensible dans le dépôt (couvert
  par :class:`TestNoPersonalDataInFixtures`).
- Règle 05 — paramètres fiscaux exclusivement dans
  ``parameters/<AAAA>/*.json`` (couvert par
  :class:`TestNoHardcodedFiscalValues`).
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import ast
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import Juridiction
from models.exceptions import (
    MissingParameterError,
    PayrollDomainError,
    UnsupportedPayrollCase,
)
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
    PayrollResult,
    RetenuesEmploye,
)
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import load_parameters


# ===========================================================================
# Constantes et helpers partagés
# ===========================================================================


#: Racine du dépôt — deux niveaux au-dessus de ``tests/test_guards.py``.
_REPO_ROOT: Path = Path(__file__).parent.parent


#: Les 12 modèles du domaine dont le contrat de champs doit être vérifié
#: (Req 10.3). L'ordre suit celui de la spec ``moteur-paie-contrats``
#: section 15.1.
_MODELES_DU_DOMAINE: tuple[type, ...] = (
    Employee,
    WeekSegment,
    PayPeriod,
    HeuresParSemaine,
    CumulsYTD,
    PayrollInput,
    GainsDecomposes,
    MontantAvecTrace,
    RetenuesEmploye,
    CotisationsEmployeur,
    PayrollResult,
    CalculationTrace,
)


def _annotation_contient_float(annotation: Any) -> bool:
    """``True`` si ``annotation`` contient ``float`` à un niveau quelconque.

    Descente récursive dans la structure de types annotée par Pydantic.
    Couvre :

    - ``float`` scalaire ;
    - ``Union[float, ...]`` et son équivalent PEP 604 ``float | X`` ;
    - ``dict[str, float]``, ``list[float]``, ``tuple[float, ...]`` ;
    - ``Optional[float]`` (alias ``Union[float, None]``) ;
    - toute combinaison imbriquée (``dict[str, Union[float, int]]``,
      ``list[dict[str, float]]``, etc.).

    Les sous-modèles (Pydantic ``BaseModel``) rencontrés sont **ignorés** :
    la garde s'applique au contrat de champs de chaque modèle individuel,
    la traversée transitive serait redondante puisque chacun des
    12 modèles du domaine est déjà inclus dans :data:`_MODELES_DU_DOMAINE`.
    """
    if annotation is float:
        return True
    for arg in get_args(annotation):
        if _annotation_contient_float(arg):
            return True
    return False


def _iterer_fichiers_python_domaine() -> list[Path]:
    """Liste les fichiers ``.py`` sous ``models/`` et ``payroll_engine/``.

    Exclut le cache ``__pycache__``. Les tests de garde ne scannent PAS
    ``parameters/<AAAA>/*.json`` : la règle 05 autorise explicitement
    les valeurs fiscales dans ces fichiers versionnés.
    """
    dossiers = (_REPO_ROOT / "models", _REPO_ROOT / "payroll_engine")
    fichiers: list[Path] = []
    for dossier in dossiers:
        for chemin in dossier.rglob("*.py"):
            if "__pycache__" in chemin.parts:
                continue
            fichiers.append(chemin)
    return fichiers


def _iterer_valeurs_json(
    donnees: Any, chemin: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], str]]:
    """Yield ``(chemin_cle, valeur_str)`` pour chaque chaîne dans ``donnees``.

    ``chemin`` est la séquence de clés traversées depuis la racine ; il
    permet aux tests de personnaliser la détection par emplacement
    (ex. ``id_paie`` doit être ignoré pour la garde NAS).

    - Les valeurs non-``str`` (``int``, ``bool``, ``None``) sont ignorées.
    - Les listes sont traversées ; l'index n'est PAS ajouté au chemin
      (les gardes se basent sur le nom de clé, pas sur la position).
    """
    resultats: list[tuple[tuple[str, ...], str]] = []
    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            nouveau_chemin = chemin + (str(cle),) if isinstance(cle, str) else chemin
            resultats.extend(_iterer_valeurs_json(valeur, nouveau_chemin))
    elif isinstance(donnees, list):
        for element in donnees:
            resultats.extend(_iterer_valeurs_json(element, chemin))
    elif isinstance(donnees, str):
        resultats.append((chemin, donnees))
    return resultats


# ===========================================================================
# 15.1 — Aucun champ typé ``float`` dans les 12 modèles du domaine (Req 10.3)
# ===========================================================================


class TestNoFloatFields:
    """Aucune annotation ``float`` dans les 12 modèles du domaine (Req 10.3).

    Cette garde ferme la règle 01 « ``Decimal`` obligatoire » côté
    contrat de forme : quelle que soit la valeur transmise à
    l'exécution, le type annoté ne DOIT jamais laisser transiter un
    ``float`` par mégarde. Introspection via :attr:`BaseModel.model_fields`
    (Pydantic v2) sur chacun des 12 modèles du domaine — la traversée
    de l'arbre de types couvre les alias ``Union``, ``dict[str, ...]``,
    ``list[...]``, ``tuple[..., ...]`` et leurs combinaisons.
    """

    @pytest.mark.parametrize(
        "modele",
        _MODELES_DU_DOMAINE,
        ids=lambda m: m.__name__,
    )
    def test_aucun_champ_annote_float(self, modele: type) -> None:
        """Chaque champ de chaque modèle refuse ``float`` à l'annotation.

        Détection récursive dans l'arbre de types de chaque
        ``FieldInfo.annotation``. Une violation nommée est reportée avec
        le nom du modèle, le nom du champ et l'annotation coupable —
        assez d'information pour corriger la ligne fautive sans
        introspection supplémentaire.
        """
        champs_fautifs: list[tuple[str, Any]] = []
        for nom_champ, info in modele.model_fields.items():
            if _annotation_contient_float(info.annotation):
                champs_fautifs.append((nom_champ, info.annotation))

        assert not champs_fautifs, (
            f"Le modèle {modele.__name__} contient au moins un champ "
            f"annoté avec ``float`` (règle 01, Req 10.3) : "
            f"{champs_fautifs}. Remplacer par ``Decimal`` et rebrancher "
            f"``reject_float`` en ``mode='before'`` si nécessaire."
        )


# ===========================================================================
# 15.2 — Aucune valeur fiscale codée en dur dans ``models/`` ni
#        ``payroll_engine/`` (règle 05)
# ===========================================================================


#: Motifs interdits recherchés ligne à ligne dans les sources Python du
#: domaine. Ces motifs correspondent aux taux et montants publiés par
#: Revenu Québec (TP-1015.F 2026) et l'ARC (T4127 2026) — les avoir en
#: dur dans le code court-circuiterait le chargement versionné imposé
#: par la règle 05.
#:
#: Une occurrence détectée bloque la garde ; la seule localisation
#: autorisée est ``parameters/<AAAA>/*.json`` (non scanné ici).
_MOTIFS_FISCAUX_INTERDITS: tuple[str, ...] = (
    'Decimal("0.063")',    # RRQ — taux cotisation base employé/employeur
    'Decimal("0.0043")',   # RQAP — taux employé
    'Decimal("0.00602")',  # RQAP — taux employeur (spec cotisations-sociales-qc)
    'Decimal("0.0130")',   # AE — taux employé Québec
    'Decimal("0.0165")',   # FSS — taux camp LilySO 2026
    'Decimal("0.0112")',   # CNESST — provision
    'Decimal("1.4")',      # AE — multiplicateur employeur (spec cotisations-sociales-qc)
    'Decimal("129.63")',   # RRQ — exemption par période aux deux semaines (spec cotisations-sociales-qc)
    'Decimal("4479.30")',  # RRQ — cotisation maximale annuelle employé (spec cotisations-sociales-qc)
)


#: Motifs numériques bruts également interdits — montants personnels de
#: base QC et fédéral 2026 (TP-1015.3 et TD1). L'expression régulière
#: matérialise « le nombre 18952 ou 16452, précédé et suivi d'un
#: non-chiffre » : elle capture aussi bien ``"18952"``, ``"18952.00"``,
#: qu'un ``18952`` scalaire, tout en excluant les nombres qui
#: contiendraient accidentellement cette sous-séquence (ex. ``189521``).
_MONTANTS_BRUTS_INTERDITS_REGEX: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)18952(?!\d)"),
    re.compile(r"(?<!\d)16452(?!\d)"),
)


class TestNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``models/`` ni ``payroll_engine/``.

    Vérifie ligne par ligne les fichiers ``.py`` du domaine contre
    :data:`_MOTIFS_FISCAUX_INTERDITS` et
    :data:`_MONTANTS_BRUTS_INTERDITS_REGEX`. La règle 05 impose que
    tout taux, plafond, exemption ou seuil fiscal soit stocké dans
    ``parameters/<AAAA>/*.json`` — jamais en dur.

    Exceptions documentées, **non** flaguées (design §Architecture
    point 3) :

    - ``Decimal("0.04")`` et ``Decimal("0.06")`` : constantes métier des
      taux d'indemnité de vacances (Normes du travail QC), matérialisées
      dans les validateurs de :class:`Employee` et :class:`PayrollInput`
      — hors champ fiscal au sens de la règle 05.
    - ``Decimal("168")`` : borne physique du nombre d'heures hebdomadaires
      (7 jours × 24 h), utilisée comme contrainte ``le`` sur les champs
      d'heures — bornes de forme, pas paramètre fiscal.
    - ``26`` : valeur de repli déterministe pour ``nb_periodes_annuelles``
      lorsque ni le fichier de l'année courante ni celui de l'année
      précédente ne sont disponibles (design §Components 10, task 12.4)
      — repli documenté, pas paramètre fiscal.

    Les motifs listés ci-dessus n'entrent volontairement PAS en collision
    avec ces exceptions : aucune règle spéciale de whitelist n'est
    nécessaire.
    """

    def test_aucune_valeur_fiscale_en_dur(self) -> None:
        """Aucun motif interdit ne DOIT apparaître dans les sources scannées."""
        violations: list[str] = []
        for chemin in _iterer_fichiers_python_domaine():
            # Lecture ligne à ligne pour reporter la ligne exacte —
            # essentiel pour qu'un développeur puisse corriger sans
            # scanner tout le fichier.
            for numero_ligne, ligne in enumerate(
                chemin.read_text(encoding="utf-8").splitlines(), start=1
            ):
                for motif in _MOTIFS_FISCAUX_INTERDITS:
                    if motif in ligne:
                        violations.append(
                            f"{chemin.relative_to(_REPO_ROOT).as_posix()}:"
                            f"{numero_ligne} — {motif!r} : {ligne.strip()}"
                        )
                for regex in _MONTANTS_BRUTS_INTERDITS_REGEX:
                    if regex.search(ligne):
                        violations.append(
                            f"{chemin.relative_to(_REPO_ROOT).as_posix()}:"
                            f"{numero_ligne} — {regex.pattern!r} : "
                            f"{ligne.strip()}"
                        )

        assert not violations, (
            "Valeurs fiscales codées en dur détectées (règle 05). "
            "Déplacer chaque valeur dans ``parameters/<AAAA>/*.json`` "
            "et lire via ``load_parameters``. Occurrences :\n"
            + "\n".join(violations)
        )


# ===========================================================================
# 15.3 — Disjonction stricte des hiérarchies d'exception (Req 8.2, 8.7)
# ===========================================================================


class TestExceptionHierarchyDisjoint:
    """Les exceptions du domaine sont disjointes de ``ValidationError`` (Req 8.7).

    Vérifie par introspection ``issubclass`` que les trois exceptions
    du domaine (:class:`PayrollDomainError`,
    :class:`UnsupportedPayrollCase`, :class:`MissingParameterError`)
    n'héritent pas de :class:`pydantic.ValidationError`, et que
    :class:`UnsupportedPayrollCase` et :class:`MissingParameterError`
    sont mutuellement disjointes (Req 8.2).

    Cette disjonction est fondamentale pour l'architecture d'exception
    (design §Components 2) : un consommateur DOIT pouvoir capturer
    séparément un refus métier (``PayrollDomainError``) d'une erreur de
    forme (``ValidationError``). Sans cette garde, un raffinement
    inopiné dans un futur commit pourrait rompre le contrat sans que
    la CI le détecte.
    """

    def test_unsupported_payroll_case_disjoint_de_validation_error(self) -> None:
        """``UnsupportedPayrollCase`` n'hérite PAS de ``ValidationError`` (Req 8.7)."""
        assert not issubclass(UnsupportedPayrollCase, ValidationError)

    def test_missing_parameter_error_disjoint_de_validation_error(self) -> None:
        """``MissingParameterError`` n'hérite PAS de ``ValidationError`` (Req 8.7)."""
        assert not issubclass(MissingParameterError, ValidationError)

    def test_payroll_domain_error_disjoint_de_validation_error(self) -> None:
        """``PayrollDomainError`` n'hérite PAS de ``ValidationError`` (Req 8.7)."""
        assert not issubclass(PayrollDomainError, ValidationError)

    def test_unsupported_et_missing_mutuellement_disjoints(self) -> None:
        """``UnsupportedPayrollCase`` et ``MissingParameterError`` sont
        mutuellement disjoints (Req 8.2).
        """
        assert not issubclass(UnsupportedPayrollCase, MissingParameterError)
        assert not issubclass(MissingParameterError, UnsupportedPayrollCase)


# ===========================================================================
# 15.4 — Contrat des messages d'exception (Property 16, Req 8.3, 8.6, 11.6)
# ===========================================================================


def _construire_employe_valide(**overrides: Any) -> dict[str, Any]:
    """Construit un dict de champs valides pour :class:`Employee`.

    Utilisé par les tests d'exception qui cherchent à déclencher UN
    validateur précis : les autres champs restent conformes pour que
    l'échec ne provienne pas d'une autre cause.

    Aucune valeur fiscale (18 952, 16 452) n'est utilisée : les
    montants ``montant_total_TP1015_3`` et ``montant_total_TD1`` sont
    fixés à ``Decimal("0.00")`` (valeur neutre acceptable pour la
    validation, l'objet ne sert qu'à déclencher un refus métier).
    """
    base: dict[str, Any] = {
        "id": "EMPGUARD001",
        "nom_affichage": "Employé Test QCGUARD",
        "date_naissance": "2000-01-01",
        "province_travail": Juridiction.QUEBEC,
        "titre_emploi": "Employé synthétique",
        "taux_horaire_base": Decimal("15.00"),
        "date_embauche": "2026-06-15",
        "taux_indemnite_vacances": Decimal("0.04"),
        "exoneration_TP1015_3": False,
        "exoneration_TD1": False,
        "montant_total_TP1015_3": Decimal("0.00"),
        "montant_total_TD1": Decimal("0.00"),
        "retenue_additionnelle_QC": Decimal("0.00"),
        "retenue_additionnelle_federale": Decimal("0.00"),
    }
    base.update(overrides)
    return base


class TestExceptionMessageContract:
    """Contrat de contenu des messages d'exception (Property 16).

    Chaque :class:`UnsupportedPayrollCase` levée par un validateur du
    domaine DOIT contenir le nom du cas refusé (Req 8.3) ET renvoyer
    à WebRAS ou PDOC (Req 11.6). Chaque :class:`MissingParameterError`
    levée par :func:`load_parameters` DOIT porter le chemin JSON,
    l'année, la juridiction et le nom du fichier à mettre à jour
    (Req 8.6, Req 9.5).

    Les tests marqués ``@pytest.mark.property`` génèrent des entrées
    variées par Hypothesis pour couvrir plus large que quelques
    exemples ponctuels ; les cas non paramétrables (par exemple les
    énumérations à valeur unique comme ``FrequencePaie``) restent en
    tests d'exemple simples.
    """

    # ------------------------------------------------------------------
    # UnsupportedPayrollCase — province ≠ QC
    # ------------------------------------------------------------------

    def test_message_province_hors_quebec(self) -> None:
        """Province ``CANADA`` → message contient le cas refusé + WebRAS/PDOC.

        :class:`Juridiction` n'expose que ``QUEBEC`` et ``CANADA`` dans
        le périmètre courant ; ``CANADA`` est le seul déclencheur
        possible du validateur ``province_travail`` par cette voie.
        """
        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            Employee(**_construire_employe_valide(province_travail=Juridiction.CANADA))

        message = str(exc_info.value)
        assert "canada" in message.lower(), (
            "Le message doit mentionner le nom du cas refusé (Req 8.3, "
            f"Property 16). Message reçu : {message!r}"
        )
        assert ("WebRAS" in message) or ("PDOC" in message), (
            "Le message doit renvoyer à WebRAS ou PDOC (Req 11.6, "
            f"Property 16). Message reçu : {message!r}"
        )

    # ------------------------------------------------------------------
    # UnsupportedPayrollCase — fréquence ≠ AUX_DEUX_SEMAINES
    # ------------------------------------------------------------------
    #
    # ``FrequencePaie`` n'expose actuellement que ``AUX_DEUX_SEMAINES``.
    # Le validateur ``_refuser_frequence_hors_matrice_before`` intercepte
    # toute chaîne inconnue avant coercition ; on utilise Hypothesis pour
    # explorer un ensemble de chaînes non listées et vérifier que le
    # contrat de message tient sur toute la surface.

    @pytest.mark.property
    @given(
        frequence_inconnue=st.sampled_from(
            [
                "hebdomadaire",
                "mensuelle",
                "bimensuelle",
                "annuelle",
                "quinzaine",
                "quotidienne",
                "trimestrielle",
            ]
        )
    )
    def test_message_frequence_hors_matrice(self, frequence_inconnue: str) -> None:
        """Toute chaîne de fréquence hors matrice → message + WebRAS/PDOC."""
        from datetime import date

        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            PayPeriod(
                numero_periode=1,
                date_debut=date(2026, 7, 13),
                date_fin=date(2026, 7, 26),
                date_paiement=date(2026, 7, 29),
                frequence=frequence_inconnue,
                nb_periodes_annuelles=26,
                annee_fiscale=2026,
                semaines=(),
            )

        message = str(exc_info.value)
        assert frequence_inconnue in message, (
            "Le message doit citer la fréquence refusée (Req 8.3, "
            f"Property 16). Reçu : {message!r} pour {frequence_inconnue!r}"
        )
        assert ("WebRAS" in message) or ("PDOC" in message), (
            "Le message doit renvoyer à WebRAS ou PDOC (Req 11.6, "
            f"Property 16). Message reçu : {message!r}"
        )

    # ------------------------------------------------------------------
    # UnsupportedPayrollCase — taux vacances ∉ {0.04, 0.06}
    # ------------------------------------------------------------------

    @pytest.mark.property
    @given(
        taux_invalide=st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("0.20"),
            allow_nan=False,
            allow_infinity=False,
            places=4,
        ).filter(lambda d: d not in {Decimal("0.04"), Decimal("0.06")})
    )
    def test_message_taux_vacances_hors_matrice(self, taux_invalide: Decimal) -> None:
        """Taux vacances ∉ ``{0.04, 0.06}`` → message + WebRAS/PDOC."""
        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            Employee(
                **_construire_employe_valide(taux_indemnite_vacances=taux_invalide)
            )

        message = str(exc_info.value)
        # Le validateur cite la valeur du taux dans le message (formatage
        # ``Decimal.__str__``) — on vérifie la présence du nombre pour
        # confirmer que le cas refusé est bien nommé (Req 8.3).
        assert str(taux_invalide) in message or "vacances" in message.lower(), (
            "Le message doit citer le taux refusé ou mentionner "
            "explicitement les vacances (Req 8.3, Property 16). "
            f"Reçu : {message!r} pour {taux_invalide!r}"
        )
        assert ("WebRAS" in message) or ("PDOC" in message), (
            "Le message doit renvoyer à WebRAS ou PDOC (Req 11.6, "
            f"Property 16). Message reçu : {message!r}"
        )

    # ------------------------------------------------------------------
    # MissingParameterError — sentinelle ``TO_FILL`` sur un paramètre
    # effectivement consommé
    # ------------------------------------------------------------------

    def test_message_missing_parameter_error(self) -> None:
        """``MissingParameterError`` cite chemin JSON, année, juridiction, fichier.

        On charge les paramètres réels 2026 QC (dont la section CNT —
        charge annuelle non encore formulée par la spec
        ``charges-patronales`` — reste marquée ``"TO_FILL"`` dans le JSON
        versionné même après le remplissage des plafonds RRQ/RQAP 2026)
        et on déclenche la matérialisation sur un paramètre non renseigné.
        Le message DOIT (Req 8.6, Property 16) inclure :

        - le **chemin JSON** du paramètre (ex. ``cnt.taux``) ;
        - l'**année** courante (``2026``) ;
        - la **juridiction** courante (``quebec``) ;
        - le **fichier** à mettre à jour
          (ex. ``parameters/2026/quebec.json``).
        """
        parametres = load_parameters(2026, Juridiction.QUEBEC)

        with pytest.raises(MissingParameterError) as exc_info:
            # ``taux`` (section ``cnt``) est ``"TO_FILL"`` dans
            # ``parameters/2026/quebec.json`` — l'accès à la propriété
            # déclenche la matérialisation, qui lève l'exception.
            _ = parametres.cnt.taux

        message = str(exc_info.value)

        # Chemin JSON — au minimum le nom du champ ; idéalement
        # préfixé par la section (``cnt.<champ>``).
        assert "taux" in message, (
            "Le message doit contenir le nom du paramètre manquant "
            f"(Req 8.6). Reçu : {message!r}"
        )
        assert "cnt" in message, (
            "Le message doit contenir la section (chemin JSON, Req 8.6). "
            f"Reçu : {message!r}"
        )

        # Année et juridiction.
        assert "2026" in message, (
            "Le message doit contenir l'année (Req 8.6). "
            f"Reçu : {message!r}"
        )
        assert "quebec" in message.lower(), (
            "Le message doit contenir la juridiction (Req 8.6). "
            f"Reçu : {message!r}"
        )

        # Fichier à mettre à jour — nom conventionnel
        # ``parameters/<annee>/<juridiction>.json``.
        assert "quebec.json" in message, (
            "Le message doit contenir le nom du fichier à mettre à jour "
            f"(Req 8.6). Reçu : {message!r}"
        )


# ===========================================================================
# 15.5 — Aucune donnée personnelle dans les fixtures (règle 04)
# ===========================================================================


#: Clés considérées comme sûres pour la garde NAS — leur valeur peut
#: contenir des séquences de chiffres qui ne représentent pas un numéro
#: d'assurance sociale. La liste couvre les identifiants techniques,
#: numéros de période et dates ISO 8601 utilisés dans les fixtures.
_CLES_SANS_NAS: frozenset[str] = frozenset(
    {
        "annee_fiscale",
        "annee_civile",
        "annee",
        "id_paie",
        "numero_periode",
        "nb_periodes_annuelles",
        "version",
        "date_naissance",
        "date_debut",
        "date_fin",
        "date_paiement",
        "date_embauche",
        "date_fin_emploi",
        "date_creation",
        "date_emission",
        "date_publication",
        "date_consultation",
        "id",
        "employe_id",
    }
)


#: Pattern d'un numéro d'assurance sociale (9 chiffres consécutifs). La
#: garde flague toute occurrence dans une valeur non couverte par
#: :data:`_CLES_SANS_NAS`.
_NAS_REGEX: re.Pattern[str] = re.compile(r"\d{9}")


#: Pattern d'un IBAN — 2 lettres majuscules, 2 chiffres, puis au moins
#: 4 caractères alphanumériques (ISO 13616). Suffisant pour attraper
#: les IBAN européens standards. Ne matche pas ``PAIE-EMP001-...`` ni
#: les sources officielles (``TP-1015.F 2026``) car ceux-ci contiennent
#: un séparateur (``-`` ou ``.``) entre les blocs.
_IBAN_REGEX: re.Pattern[str] = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,}\b")


#: Mots-clés d'adresse postale — présence détectée avec des délimiteurs
#: de mot pour éviter les faux positifs (par exemple ``brut`` ne
#: contient pas le mot ``rue``). Insensible à la casse.
_MOTS_CLES_ADRESSE_REGEX: re.Pattern[str] = re.compile(
    r"\b(rue|avenue|boulevard|chemin|route)\b",
    re.IGNORECASE,
)


#: Champs dont la valeur doit correspondre à un motif de nom/titre
#: anonymisé de la liste blanche.
_CHAMPS_NOMS_ANONYMISES: frozenset[str] = frozenset(
    {"nom_affichage", "titre_emploi"}
)


#: Motifs anonymisés autorisés pour :data:`_CHAMPS_NOMS_ANONYMISES`.
#: Correspond à la convention adoptée pour les fixtures QC001–QC006
#: (règle 04) : identifiants techniques ``EMP\w+``, titres bruts, et
#: combinaisons titre + identifiant.
_MOTIFS_NOMS_ANONYMISES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(motif)
    for motif in (
        r"^EMP\w+$",
        r"^Monitrice$",
        r"^Monitrice EMP\w+$",
        r"^Monitrice en chef$",
        r"^Moniteur$",
        r"^Moniteur EMP\w+$",
        r"^Moniteur sauveteur$",
        r"^Assistante$",
        r"^Assistante EMP\w+$",
        r"^Assistante monitrice$",
        r"^Employé Test QC\w+$",
        r"^Employé synthétique$",
    )
)


def _nom_est_anonymise(valeur: str) -> bool:
    """``True`` si ``valeur`` correspond à un motif anonymisé autorisé."""
    return any(motif.match(valeur) for motif in _MOTIFS_NOMS_ANONYMISES)


class TestNoPersonalDataInFixtures:
    """Aucune donnée personnelle réelle dans ``tests/fixtures/**/*.json`` (règle 04).

    Quatre gardes complémentaires appliquées à chaque fichier de
    fixture :

    1. **Pas de NAS** — recherche d'une séquence de 9 chiffres
       consécutifs dans les valeurs de chaîne, hors clés techniques
       (identifiants et dates, cf. :data:`_CLES_SANS_NAS`).
    2. **Pas d'IBAN** — recherche du motif ISO 13616 minimal
       (2 lettres + 2 chiffres + 4+ alphanumériques).
    3. **Pas d'adresse postale** — recherche de mots-clés (``rue``,
       ``avenue``, ``boulevard``, ``chemin``, ``route``) avec
       délimiteurs de mot.
    4. **Nom anonymisé** — les valeurs de ``nom_affichage`` et
       ``titre_emploi`` doivent correspondre à un motif de la liste
       blanche (:data:`_MOTIFS_NOMS_ANONYMISES`).

    Une fixture qui échoue à l'une de ces gardes signale une potentielle
    fuite de donnée personnelle réelle — arrêt immédiat exigé par la
    règle 04.
    """

    def _fixtures(self) -> list[Path]:
        """Liste tous les fichiers ``.json`` sous ``tests/fixtures/``."""
        racine_fixtures = _REPO_ROOT / "tests" / "fixtures"
        return sorted(racine_fixtures.rglob("*.json"))

    def test_fixtures_ne_contiennent_pas_de_nas(self) -> None:
        """Aucune valeur de chaîne ne DOIT contenir 9 chiffres consécutifs.

        Les clés techniques listées dans :data:`_CLES_SANS_NAS` sont
        exemptées : leurs valeurs peuvent légitimement porter des
        séquences numériques (dates ISO, identifiants composés).
        """
        violations: list[str] = []
        for fixture in self._fixtures():
            donnees = json.loads(fixture.read_text(encoding="utf-8"))
            for chemin, valeur in _iterer_valeurs_json(donnees):
                # La dernière clé du chemin identifie le champ direct
                # portant la valeur — c'est celle qu'on autorise.
                cle_directe = chemin[-1] if chemin else ""
                if cle_directe in _CLES_SANS_NAS:
                    continue
                if _NAS_REGEX.search(valeur):
                    violations.append(
                        f"{fixture.relative_to(_REPO_ROOT).as_posix()} — "
                        f"chemin={'.'.join(chemin)} valeur={valeur!r}"
                    )

        assert not violations, (
            "Séquences de 9 chiffres consécutifs détectées dans les "
            "fixtures — potentielle fuite de NAS (règle 04). "
            "Anonymiser ou supprimer :\n" + "\n".join(violations)
        )

    def test_fixtures_ne_contiennent_pas_d_iban(self) -> None:
        """Aucune valeur de chaîne ne DOIT matcher le motif IBAN.

        Le motif ``[A-Z]{2}\\d{2}[A-Z0-9]{4,}`` est strict : les
        identifiants Camp LilySO (``PAIE-EMPTEST001-2026-01``) ne
        matchent pas car ils contiennent des ``-`` séparant les blocs.
        Les sources officielles (``TP-1015.F 2026``) non plus, pour la
        même raison.
        """
        violations: list[str] = []
        for fixture in self._fixtures():
            donnees = json.loads(fixture.read_text(encoding="utf-8"))
            for chemin, valeur in _iterer_valeurs_json(donnees):
                if _IBAN_REGEX.search(valeur):
                    violations.append(
                        f"{fixture.relative_to(_REPO_ROOT).as_posix()} — "
                        f"chemin={'.'.join(chemin)} valeur={valeur!r}"
                    )

        assert not violations, (
            "Motif IBAN détecté dans les fixtures — potentielle fuite "
            "de compte bancaire (règle 04) :\n" + "\n".join(violations)
        )

    def test_fixtures_ne_contiennent_pas_d_adresse(self) -> None:
        """Aucun mot-clé d'adresse postale ne DOIT apparaître dans les fixtures."""
        violations: list[str] = []
        for fixture in self._fixtures():
            donnees = json.loads(fixture.read_text(encoding="utf-8"))
            for chemin, valeur in _iterer_valeurs_json(donnees):
                correspondance = _MOTS_CLES_ADRESSE_REGEX.search(valeur)
                if correspondance:
                    violations.append(
                        f"{fixture.relative_to(_REPO_ROOT).as_posix()} — "
                        f"chemin={'.'.join(chemin)} valeur={valeur!r} "
                        f"(mot-clé : {correspondance.group(0)!r})"
                    )

        assert not violations, (
            "Mot-clé d'adresse postale détecté dans les fixtures "
            "(règle 04) — remplacer par des identifiants anonymisés :\n"
            + "\n".join(violations)
        )

    def test_champs_de_noms_uniquement_anonymises(self) -> None:
        """``nom_affichage`` et ``titre_emploi`` DOIVENT matcher la whitelist.

        Ces deux champs sont les seuls emplacements légitimes pour un
        nom ou un titre affichable dans le contrat d'entrée. La règle 04
        impose que leur valeur soit anonymisée — d'où la vérification
        contre :data:`_MOTIFS_NOMS_ANONYMISES`.
        """
        violations: list[str] = []
        for fixture in self._fixtures():
            donnees = json.loads(fixture.read_text(encoding="utf-8"))
            for chemin, valeur in _iterer_valeurs_json(donnees):
                cle_directe = chemin[-1] if chemin else ""
                if cle_directe not in _CHAMPS_NOMS_ANONYMISES:
                    continue
                if not _nom_est_anonymise(valeur):
                    violations.append(
                        f"{fixture.relative_to(_REPO_ROOT).as_posix()} — "
                        f"chemin={'.'.join(chemin)} valeur={valeur!r}"
                    )

        assert not violations, (
            "Valeur non anonymisée détectée sur un champ de nom/titre "
            "(règle 04). Utiliser un motif de la liste blanche "
            "(EMP<num>, Monitrice, Moniteur EMP<num>, Employé Test "
            "QC<num>, etc.) :\n" + "\n".join(violations)
        )


# ===========================================================================
# 4.1 (spec gains-bruts-vacances-hs) — Absence de ``float`` dans
#     ``payroll_engine/gains_bruts.py`` (Req 12.1, 12.2, 12.3, 12.4, 1.4)
# ===========================================================================
#
# Spec de référence : ``gains-bruts-vacances-hs`` — tâche 4.1. Cette garde
# est écrite AVANT ``payroll_engine/gains_bruts.py`` (tâches 5.1/5.2, non
# réalisées à ce stade) — règle 06 « tests avant code ». Tant que le
# fichier n'existe pas, chaque test de cette classe échoue de façon
# explicite via ``pytest.fail`` (et non par une erreur de collection),
# ce qui est le comportement rouge attendu.


#: Chemin du module cible de cette garde, relatif à la racine du dépôt.
_CHEMIN_GAINS_BRUTS: Path = _REPO_ROOT / "payroll_engine" / "gains_bruts.py"


#: Noms de fonction appelée en forme ``nom(...)`` interdits comme
#: mécanisme d'arrondissement (Req 12.3) — ``round`` retourne un
#: ``float`` ou un ``int`` selon le nombre d'arguments, jamais admissible
#: dans le domaine paie (règle 01).
_APPELS_ARRONDISSEMENT_INTERDITS: frozenset[str] = frozenset({"round"})


#: Attributs de méthode/fonction appelée en forme ``mod.attr(...)``
#: interdits comme mécanisme d'arrondissement (Req 12.3) — couvre
#: ``math.floor``, ``math.ceil``, ``math.trunc`` quel que soit l'alias
#: d'import du module ``math``.
_ATTRIBUTS_ARRONDISSEMENT_INTERDITS: frozenset[str] = frozenset(
    {"floor", "ceil", "trunc"}
)


def _parser_module_gains_bruts() -> ast.Module:
    """Parse ``payroll_engine/gains_bruts.py`` en arbre AST.

    Échoue explicitement (``pytest.fail``) si le fichier n'existe pas
    encore — état attendu avant les tâches 5.1/5.2 de la spec
    ``gains-bruts-vacances-hs`` (règle 06, TDD : ce test de garde est
    rouge par absence de module, pas par erreur de collection).
    """
    if not _CHEMIN_GAINS_BRUTS.exists():
        pytest.fail(
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "n'existe pas encore. Ce test de garde précède "
            "l'implémentation (tâches 5.1/5.2 de la spec "
            "gains-bruts-vacances-hs, règle 06) et DOIT rester rouge "
            "jusqu'à la création du module."
        )
    source = _CHEMIN_GAINS_BRUTS.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(_CHEMIN_GAINS_BRUTS))


def _trouver_fonction(arbre: ast.Module, nom: str) -> ast.FunctionDef | None:
    """Retourne la première ``def <nom>(...)`` de niveau module dans ``arbre``."""
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return noeud
    return None


class TestGainsBrutsNoFloat:
    """Aucun ``float`` dans ``payroll_engine/gains_bruts.py`` (Req 12.1–12.4).

    Ferme la règle 01 (« ``Decimal`` obligatoire ») côté module de
    calcul des gains bruts, par introspection statique de l'AST — sans
    dépendre d'une exécution ni d'un import du module (Req 1.6 :
    aucun effet de bord au moment de l'import).

    Quatre gardes complémentaires :

    1. Aucune littérale flottante dans le code source (Req 12.1).
    2. Aucun appel ``Decimal(<non-str>)`` — défend contre ``Decimal(1.5)``
       et ``Decimal(x)`` où ``x`` n'est pas une chaîne littérale
       (Req 12.2).
    3. Aucun appel ``round(...)``, ``math.floor(...)``, ``math.ceil(...)``
       ou ``math.trunc(...)`` — seul ``Decimal.quantize`` est autorisé
       pour arrondir (Req 12.3).
    4. La signature de ``calcul_gains`` retourne l'annotation exacte
       ``tuple[GainsDecomposes, CalculationTrace]`` et n'accepte aucun
       paramètre par défaut (Req 1.4, Req 12.4).
    """

    def test_aucune_litterale_flottante(self) -> None:
        """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 12.1)."""
        arbre = _parser_module_gains_bruts()
        violations = [
            f"ligne {noeud.lineno} — {noeud.value!r}"
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Constant) and isinstance(noeud.value, float)
        ]

        assert not violations, (
            "Littérale flottante détectée dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(règle 01, Req 12.1). Remplacer par un ``Decimal(\"...\")`` "
            "ou une valeur lue depuis ``parametres_annee``. "
            "Occurrences :\n" + "\n".join(violations)
        )

    def test_aucun_appel_decimal_depuis_non_str(self) -> None:
        """Aucun ``Decimal(<non-str>)`` — seule ``Decimal(\"...\")`` est admise (Req 12.2)."""
        arbre = _parser_module_gains_bruts()
        violations: list[str] = []
        for noeud in ast.walk(arbre):
            if not (
                isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Name)
                and noeud.func.id == "Decimal"
            ):
                continue
            for argument in noeud.args:
                est_litterale_str = isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                )
                if not est_litterale_str:
                    violations.append(
                        f"ligne {noeud.lineno} — Decimal({ast.unparse(argument)})"
                    )

        assert not violations, (
            "Appel ``Decimal(<non-str>)`` détecté dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(règle 01, Req 12.2). Seule ``Decimal(\"...\")`` (littérale "
            "chaîne) ou une valeur déjà ``Decimal`` transportée depuis "
            "``parametres_annee``/``payroll_input`` est admise. "
            "Occurrences :\n" + "\n".join(violations)
        )

    def test_aucune_fonction_arrondissement_interdite(self) -> None:
        """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc`` (Req 12.3).

        Seul ``Decimal.quantize`` est autorisé pour arrondir — détection
        par nom d'appel direct (``round(...)``) et par attribut de
        méthode (``<alias>.floor(...)``, ``<alias>.ceil(...)``,
        ``<alias>.trunc(...)``), robuste à l'alias d'import du module
        ``math``.
        """
        arbre = _parser_module_gains_bruts()
        violations: list[str] = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            fonction = noeud.func
            if isinstance(fonction, ast.Name) and fonction.id in (
                _APPELS_ARRONDISSEMENT_INTERDITS
            ):
                violations.append(f"ligne {noeud.lineno} — {fonction.id}(...)")
            elif (
                isinstance(fonction, ast.Attribute)
                and fonction.attr in _ATTRIBUTS_ARRONDISSEMENT_INTERDITS
            ):
                violations.append(
                    f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                )

        assert not violations, (
            "Appel d'arrondissement interdit détecté dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(règle 01, Req 12.3). Seul ``Decimal.quantize(Decimal(\"0.01\"), "
            "rounding=ROUND_HALF_UP)`` est autorisé pour arrondir. "
            "Occurrences :\n" + "\n".join(violations)
        )

    def test_signature_calcul_gains_retourne_tuple_gains_trace(self) -> None:
        """``calcul_gains`` annote son retour ``tuple[GainsDecomposes, CalculationTrace]`` (Req 1.4, 12.4)."""
        arbre = _parser_module_gains_bruts()
        fonction = _trouver_fonction(arbre, "calcul_gains")

        assert fonction is not None, (
            "Aucune fonction ``calcul_gains`` trouvée au niveau module "
            f"dans {_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 1.1)."
        )
        assert fonction.returns is not None, (
            "``calcul_gains`` ne porte aucune annotation de retour "
            "(Req 1.4, 12.4). Attendu : "
            "``tuple[GainsDecomposes, CalculationTrace]``."
        )

        annotation_retour = ast.unparse(fonction.returns)
        assert annotation_retour == "tuple[GainsDecomposes, CalculationTrace]", (
            "L'annotation de retour de ``calcul_gains`` doit être exactement "
            "``tuple[GainsDecomposes, CalculationTrace]`` (Req 1.4, 12.4). "
            f"Reçu : {annotation_retour!r}"
        )

    def test_signature_calcul_gains_sans_parametre_par_defaut(self) -> None:
        """``calcul_gains`` n'accepte aucun paramètre par défaut (Req 1.4)."""
        arbre = _parser_module_gains_bruts()
        fonction = _trouver_fonction(arbre, "calcul_gains")

        assert fonction is not None, (
            "Aucune fonction ``calcul_gains`` trouvée au niveau module "
            f"dans {_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 1.1)."
        )

        arguments = fonction.args
        defauts_presents = bool(
            arguments.defaults
            or any(defaut is not None for defaut in arguments.kw_defaults)
        )
        assert not defauts_presents, (
            "``calcul_gains`` ne doit accepter aucun paramètre par défaut "
            "(Req 1.4) — chaque appel doit fournir explicitement "
            "``payroll_input`` et ``parametres_annee``, sans état "
            "implicite hérité d'une valeur par défaut."
        )


# ===========================================================================
# 4.2 (spec gains-bruts-vacances-hs) — Absence de valeurs fiscales en dur
#     dans ``payroll_engine/gains_bruts.py`` (Req 5.7, 9.4)
# ===========================================================================
#
# Spec de référence : ``gains-bruts-vacances-hs`` — tâche 4.2. Même
# discipline que la tâche 4.1 (règle 06, TDD) : ce test de garde est
# écrit AVANT ``payroll_engine/gains_bruts.py`` (tâches 5.1/5.2, non
# réalisées à ce stade). Tant que le fichier n'existe pas, chaque test
# de cette classe échoue explicitement via ``pytest.fail`` (et non par
# une erreur de collection), ce qui est le comportement rouge attendu.


#: Motifs interdits recherchés ligne à ligne — le multiplicateur des
#: heures supplémentaires (1,5) et le seuil hebdomadaire (40 h) DOIVENT
#: provenir exclusivement de ``parametres_annee.heures_supplementaires``
#: (règle 05, Req 9.4). Les avoir en dur court-circuiterait le
#: chargement versionné imposé par la règle 05.
_MOTIFS_HS_INTERDITS: tuple[str, ...] = (
    'Decimal("1.5")',
    'Decimal("1.50")',
    'Decimal("40")',
    'Decimal("40.00")',
    'Decimal("40.0")',
)


#: Littéraux ``Decimal("...")`` explicitement autorisés dans
#: ``payroll_engine/gains_bruts.py`` : neutre additif (Req 9.4) et
#: précision d'arrondissement ``_PRECISION_MONNAIE`` imposée par
#: TP-1015.G — pas un paramètre fiscal.
_DECIMAL_NEUTRES_AUTORISES: tuple[str, ...] = (
    'Decimal("0")',
    'Decimal("0.00")',
    'Decimal("0.01")',
)


#: Littéraux ``Decimal("...")`` du taux de vacances, admis
#: **uniquement** sur l'unique ligne de défense en profondeur qui
#: construit l'ensemble des taux supportés (Req 10.3, cohérent avec
#: l'exception ``Employee`` documentée dans
#: :class:`TestNoHardcodedFiscalValues`).
_DECIMAL_VACANCES_AUTORISES: tuple[str, ...] = (
    'Decimal("0.04")',
    'Decimal("0.06")',
)


#: Reconnaît tout littéral ``Decimal("...")`` (contenu quelconque entre
#: guillemets) — utilisé pour neutraliser ces occurrences avant la
#: recherche de constantes numériques nues, afin qu'un nombre légitime
#: à l'intérieur d'une chaîne ``Decimal`` autorisée ne soit pas
#: re-détecté comme une constante déguisée.
_DECIMAL_LITTERAL_REGEX: re.Pattern[str] = re.compile(r'Decimal\("[^"]*"\)')


#: Constantes numériques nues (hors ``Decimal("...")``) dont la
#: présence signale une valeur fiscale déguisée en littéral ``float``
#: ou ``int`` — recherchées avec des délimiteurs excluant les chiffres,
#: points et caractères alphanumériques adjacents pour éviter les faux
#: positifs (ex. ``2026`` ne doit pas matcher ``40`` ; un identifiant
#: ``_40`` ne doit pas matcher non plus).
_CONSTANTES_NUES_INTERDITES_REGEX: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![\w.])1\.5(?![\w])"),
    re.compile(r"(?<![\w.])40(?:\.0+)?(?![\w])"),
    re.compile(r"(?<![\w.])0\.04(?![\w])"),
    re.compile(r"(?<![\w.])0\.06(?![\w])"),
)


def _lire_lignes_gains_bruts() -> list[str]:
    """Retourne les lignes de ``payroll_engine/gains_bruts.py``.

    Échoue explicitement (``pytest.fail``) si le fichier n'existe pas
    encore — même état rouge attendu que
    :func:`_parser_module_gains_bruts` avant les tâches 5.1/5.2 de la
    spec ``gains-bruts-vacances-hs`` (règle 06).
    """
    if not _CHEMIN_GAINS_BRUTS.exists():
        pytest.fail(
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "n'existe pas encore. Ce test de garde précède "
            "l'implémentation (tâches 5.1/5.2 de la spec "
            "gains-bruts-vacances-hs, règle 06) et DOIT rester rouge "
            "jusqu'à la création du module."
        )
    return _CHEMIN_GAINS_BRUTS.read_text(encoding="utf-8").splitlines()


class TestGainsBrutsNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``payroll_engine/gains_bruts.py``.

    Ferme la règle 05 côté module de calcul des gains bruts : le
    multiplicateur des heures supplémentaires (1,5) et le seuil
    hebdomadaire (40 h) DOIVENT provenir exclusivement de
    ``parametres_annee.heures_supplementaires`` (Req 9.4). Trois gardes
    complémentaires, par lecture ligne à ligne du fichier source :

    1. Absence stricte des motifs ``Decimal("1.5")``, ``Decimal("1.50")``,
       ``Decimal("40")``, ``Decimal("40.00")``, ``Decimal("40.0")``.
    2. Confinement de ``Decimal("0.04")``/``Decimal("0.06")`` à l'unique
       ligne de défense en profondeur (Req 10.3), deux occurrences
       maximum sur cette ligne — la même exception que celle documentée
       pour ``Employee`` dans :class:`TestNoHardcodedFiscalValues`.
    3. Absence de constantes numériques déguisées (``1.5``, ``40``,
       ``0.04``, ``0.06`` en littéral ``float``/``int`` nu, hors chaîne
       ``Decimal("...")``).

    Les littéraux ``Decimal("0")``, ``Decimal("0.00")`` (neutre additif)
    et ``Decimal("0.01")`` (précision ``_PRECISION_MONNAIE``, imposée
    par TP-1015.G) sont explicitement autorisés partout dans le module
    — ce ne sont pas des paramètres fiscaux au sens de la règle 05.
    """

    def test_aucun_motif_multiplicateur_ou_seuil_hs_en_dur(self) -> None:
        """``1.5``/``40`` DOIVENT provenir de ``parametres_annee`` (Req 9.4)."""
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(_lire_lignes_gains_bruts(), start=1):
            for motif in _MOTIFS_HS_INTERDITS:
                if motif in ligne:
                    violations.append(
                        f"ligne {numero_ligne} — {motif!r} : {ligne.strip()}"
                    )

        assert not violations, (
            "Valeur fiscale du multiplicateur/seuil heures supplémentaires "
            "codée en dur (règle 05, Req 9.4). Ces valeurs DOIVENT être "
            "lues via ``parametres_annee.heures_supplementaires``. "
            "Occurrences :\n" + "\n".join(violations)
        )

    def test_whitelist_vacances_limitee_a_une_ligne_deux_occurrences(self) -> None:
        """``Decimal("0.04")``/``Decimal("0.06")`` confinés à l'unique ligne
        de défense en profondeur, deux occurrences maximum (Req 10.3).
        """
        lignes_avec_motif_vacances = [
            (numero, ligne)
            for numero, ligne in enumerate(_lire_lignes_gains_bruts(), start=1)
            if any(motif in ligne for motif in _DECIMAL_VACANCES_AUTORISES)
        ]

        assert len(lignes_avec_motif_vacances) <= 1, (
            "``Decimal(\"0.04\")``/``Decimal(\"0.06\")`` ne DOIVENT "
            "apparaître que sur l'unique ligne de défense en profondeur "
            "qui construit l'ensemble des taux de vacances supportés "
            "(Req 10.3, exception cohérente avec ``Employee`` dans "
            "``TestNoHardcodedFiscalValues``). Lignes trouvées :\n"
            + "\n".join(
                f"ligne {numero} — {ligne.strip()}"
                for numero, ligne in lignes_avec_motif_vacances
            )
        )

        if lignes_avec_motif_vacances:
            numero, ligne = lignes_avec_motif_vacances[0]
            occurrences = sum(
                ligne.count(motif) for motif in _DECIMAL_VACANCES_AUTORISES
            )
            assert occurrences <= 2, (
                f"La ligne {numero} contient plus de deux occurrences de "
                "``Decimal(\"0.04\")``/``Decimal(\"0.06\")`` (Req 10.3) : "
                f"{ligne.strip()!r}"
            )

    def test_aucune_constante_numerique_deguisee(self) -> None:
        """Aucun littéral nu ``1.5``/``40``/``0.04``/``0.06`` hors ``Decimal("...")`` (Req 9.4)."""
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(_lire_lignes_gains_bruts(), start=1):
            # Neutraliser tout littéral ``Decimal("...")`` avant la
            # recherche de constantes nues, pour qu'un nombre légitime
            # à l'intérieur d'une chaîne ``Decimal`` autorisée (ou d'un
            # motif interdit déjà reporté par l'autre garde) ne soit pas
            # re-détecté ici.
            ligne_sans_decimal = _DECIMAL_LITTERAL_REGEX.sub("", ligne)
            for regex in _CONSTANTES_NUES_INTERDITES_REGEX:
                if regex.search(ligne_sans_decimal):
                    violations.append(
                        f"ligne {numero_ligne} — {regex.pattern!r} : "
                        f"{ligne.strip()}"
                    )

        assert not violations, (
            "Constante numérique déguisée détectée (règle 05, Req 9.4). "
            "Toute valeur fiscale du multiplicateur/seuil heures "
            "supplémentaires doit provenir de "
            "``parametres_annee.heures_supplementaires`` et être "
            "transportée sous forme de ``Decimal`` déjà matérialisé — "
            "jamais un littéral ``float``/``int`` nu. "
            "Occurrences :\n" + "\n".join(violations)
        )


# ===========================================================================
# 4.3 (spec gains-bruts-vacances-hs) — Non-appel de ``load_parameters`` et
#     absence de sources de non-déterminisme dans
#     ``payroll_engine/gains_bruts.py`` (Req 1.3, 1.6, 14.1, 14.2, 14.3)
# ===========================================================================
#
# Spec de référence : ``gains-bruts-vacances-hs`` — tâche 4.3. Même
# discipline que les tâches 4.1/4.2 (règle 06, TDD) : ce test de garde est
# écrit AVANT ``payroll_engine/gains_bruts.py`` (tâches 5.1/5.2, non
# réalisées à ce stade). Tant que le fichier n'existe pas, chaque test de
# cette classe échoue explicitement via ``pytest.fail`` (et non par une
# erreur de collection), ce qui est le comportement rouge attendu.


#: Seuls ces noms peuvent être importés depuis
#: ``payroll_engine.parameters_loader`` dans ``gains_bruts.py`` — le
#: **type** ``ParametresAnnee`` est autorisé (annotation de paramètre),
#: mais jamais la fonction ``load_parameters`` elle-même : la fonction de
#: calcul reçoit ``parametres_annee`` déjà matérialisé par l'appelant
#: (Req 1.3, 1.6).
_NOMS_AUTORISES_DEPUIS_PARAMETERS_LOADER: frozenset[str] = frozenset(
    {"ParametresAnnee"}
)


#: Attributs d'appel de méthode signalant une ouverture ou une lecture de
#: fichier — ``Path(...).read_text()``/``read_bytes()`` (Req 1.3, 1.6).
_ATTRIBUTS_OUVERTURE_FICHIER_INTERDITS: frozenset[str] = frozenset(
    {"read_text", "read_bytes"}
)


#: Attributs d'appel signalant une désérialisation JSON directe —
#: ``json.load(...)``/``json.loads(...)`` (Req 1.3, 1.6). Le nom de base
#: de l'appel (``json`` quel que soit l'alias) est vérifié séparément pour
#: éviter tout faux positif sur une méthode ``.load``/``.loads`` non liée
#: à ``json``.
_ATTRIBUTS_JSON_INTERDITS: frozenset[str] = frozenset({"load", "loads"})


#: Attributs d'appel ``datetime.now()``/``datetime.today()`` — sources de
#: non-déterminisme proscrites (Req 14.1). Le nom de base de l'appel doit
#: contenir ``datetime`` pour éviter tout faux positif sur une méthode
#: homonyme d'un autre objet.
_ATTRIBUTS_DATETIME_NON_DETERMINISTES: frozenset[str] = frozenset({"now", "today"})


#: Noms de variables/appels de niveau module signalant un état mutable
#: partagé entre appels — proscrit par la contrainte de pureté (Req 14.3).
_APPELS_CONSTRUCTEURS_MUTABLES_INTERDITS: frozenset[str] = frozenset(
    {"dict", "list", "set"}
)


class TestGainsBrutsNoLoadParametersCall:
    """``payroll_engine/gains_bruts.py`` n'appelle jamais ``load_parameters``
    et ne recourt à aucune source de non-déterminisme (Req 1.3, 1.6, 14.1,
    14.2, 14.3).

    Ferme la contrainte de pureté du module de calcul des gains bruts
    (design §Architecture « Contrainte de pureté ») : la fonction reçoit
    ``parametres_annee`` déjà matérialisé par l'appelant (Req 1.3) et ne
    doit produire aucun effet de bord ni dépendre d'un état externe
    variable (Req 1.6, 14.1, 14.2). Cinq gardes complémentaires, par
    introspection AST et lecture ligne à ligne du fichier source :

    1. Absence stricte du token ``load_parameters`` (import ou appel).
    2. Tout import depuis ``payroll_engine.parameters_loader`` ne cible
       que le type ``ParametresAnnee``.
    3. Absence d'ouverture de fichier (``open(...)``,
       ``Path(...).read_text()``/``read_bytes()``,
       ``json.load(...)``/``json.loads(...)``).
    4. Absence d'appel à ``datetime.now()``/``datetime.today()``,
       ``random.*`` ou ``os.environ`` — sources de non-déterminisme
       proscrites (Req 14.1, 14.2).
    5. Absence de variable de module mutable (``_cache = {}``,
       ``logging.getLogger(...)`` au niveau module, etc.) — Req 14.3.
    """

    def test_aucun_token_load_parameters(self) -> None:
        """Grep : aucune occurrence du token ``load_parameters`` (Req 1.3, 1.6)."""
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(_lire_lignes_gains_bruts(), start=1):
            if "load_parameters" in ligne:
                violations.append(f"ligne {numero_ligne} — {ligne.strip()}")

        assert not violations, (
            "Occurrence du token ``load_parameters`` détectée dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 1.3, 1.6). La fonction de calcul DOIT recevoir "
            "``parametres_annee`` déjà matérialisé par l'appelant — "
            "jamais charger elle-même les paramètres. Occurrences :\n"
            + "\n".join(violations)
        )

    def test_import_parameters_loader_type_seulement(self) -> None:
        """Seul le type ``ParametresAnnee`` est importable depuis
        ``payroll_engine.parameters_loader`` (Req 1.3, 1.6).
        """
        arbre = _parser_module_gains_bruts()
        violations: list[str] = []
        for noeud in ast.walk(arbre):
            if not (
                isinstance(noeud, ast.ImportFrom)
                and noeud.module == "payroll_engine.parameters_loader"
            ):
                continue
            for alias in noeud.names:
                if alias.name not in _NOMS_AUTORISES_DEPUIS_PARAMETERS_LOADER:
                    violations.append(
                        f"ligne {noeud.lineno} — from {noeud.module} "
                        f"import {alias.name}"
                    )

        assert not violations, (
            "Import non autorisé depuis "
            "``payroll_engine.parameters_loader`` détecté (Req 1.3, 1.6). "
            "Seul le type ``ParametresAnnee`` (annotation de paramètre) "
            "est admis — jamais ``load_parameters``. Occurrences :\n"
            + "\n".join(violations)
        )

    def test_aucune_ouverture_fichier(self) -> None:
        """Aucun ``open(...)``, ``Path(...).read_text()``/``read_bytes()``,
        ``json.load(...)``/``json.loads(...)`` (Req 1.3, 1.6).

        La fonction reçoit ``parametres_annee`` déjà matérialisé — aucune
        lecture de fichier ne doit avoir lieu dans ce module.
        """
        arbre = _parser_module_gains_bruts()
        violations: list[str] = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            fonction = noeud.func
            if isinstance(fonction, ast.Name) and fonction.id == "open":
                violations.append(f"ligne {noeud.lineno} — open(...)")
            elif isinstance(fonction, ast.Attribute):
                if fonction.attr in _ATTRIBUTS_OUVERTURE_FICHIER_INTERDITS:
                    violations.append(
                        f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                    )
                elif fonction.attr in _ATTRIBUTS_JSON_INTERDITS:
                    base = ast.unparse(fonction.value)
                    if "json" in base.lower():
                        violations.append(
                            f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                        )

        assert not violations, (
            "Ouverture ou désérialisation de fichier détectée dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 1.3, 1.6). La fonction reçoit ``parametres_annee`` "
            "déjà matérialisé par l'appelant — aucune lecture de fichier "
            "ne doit avoir lieu ici. Occurrences :\n" + "\n".join(violations)
        )

    def test_aucune_source_non_determinisme(self) -> None:
        """Aucun ``datetime.now()``/``datetime.today()``, ``random.*``,
        ``os.environ`` (Req 14.1, 14.2).
        """
        arbre = _parser_module_gains_bruts()
        violations: list[str] = []
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute):
                fonction = noeud.func
                if fonction.attr in _ATTRIBUTS_DATETIME_NON_DETERMINISTES:
                    base = ast.unparse(fonction.value)
                    if "datetime" in base.lower():
                        violations.append(
                            f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                        )
            if isinstance(noeud, ast.Attribute):
                base = ast.unparse(noeud.value)
                premier_segment = base.split(".")[0]
                if premier_segment == "random":
                    violations.append(f"ligne {noeud.lineno} — {ast.unparse(noeud)}")
                if noeud.attr == "environ" and base == "os":
                    violations.append(f"ligne {noeud.lineno} — os.environ")

        assert not violations, (
            "Source de non-déterminisme détectée dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 14.1, 14.2). ``datetime.now()``/``datetime.today()``, "
            "``random.*`` et ``os.environ`` sont proscrits — toute donnée "
            "variable doit provenir explicitement des paramètres reçus. "
            "Occurrences :\n" + "\n".join(violations)
        )

    def test_aucune_variable_module_mutable(self) -> None:
        """Aucune variable de module mutable (``_cache = {}``,
        ``logging.getLogger(...)`` au niveau module, etc.) (Req 14.3).
        """
        arbre = _parser_module_gains_bruts()
        violations: list[str] = []
        for noeud in arbre.body:
            if not isinstance(noeud, ast.Assign):
                continue
            valeur = noeud.value
            noms_cibles = [
                cible.id for cible in noeud.targets if isinstance(cible, ast.Name)
            ]
            if not noms_cibles:
                continue

            est_litterale_mutable = isinstance(valeur, (ast.Dict, ast.List, ast.Set))
            est_appel_mutable = False
            if isinstance(valeur, ast.Call):
                appelee = valeur.func
                if (
                    isinstance(appelee, ast.Name)
                    and appelee.id in _APPELS_CONSTRUCTEURS_MUTABLES_INTERDITS
                ):
                    est_appel_mutable = True
                elif (
                    isinstance(appelee, ast.Attribute)
                    and appelee.attr == "getLogger"
                ):
                    est_appel_mutable = True

            if est_litterale_mutable or est_appel_mutable:
                violations.append(
                    f"ligne {noeud.lineno} — {', '.join(noms_cibles)} = "
                    f"{ast.unparse(valeur)}"
                )

        assert not violations, (
            "Variable de module mutable détectée dans "
            f"{_CHEMIN_GAINS_BRUTS.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 14.3). Un module de calcul pur ne doit exposer aucun "
            "état mutable partagé entre appels (cache, logger, etc.) au "
            "niveau module. Occurrences :\n" + "\n".join(violations)
        )


# ===========================================================================
# 7.1 (spec cotisations-sociales-qc) — Absence de ``float`` dans
#     ``payroll_engine/rrq.py``, ``rqap.py`` et ``assurance_emploi.py``
#     (Req 2.7, 3.4, 4.5, 5.6, 6.5, 7.4)
# ===========================================================================
#
# Spec de référence : ``cotisations-sociales-qc`` — tâche 7.1. Même
# discipline que :class:`TestGainsBrutsNoFloat` (règle 06, TDD) : ces
# tests de garde sont écrits AVANT ``payroll_engine/rrq.py``,
# ``rqap.py`` et ``assurance_emploi.py`` (tâches 9.1/10.1/11.1, non
# réalisées à ce stade). Tant que ces fichiers n'existent pas, chaque
# test échoue explicitement via ``pytest.fail`` (et non par une erreur
# de collection), ce qui est le comportement rouge attendu.


#: Chemins des trois modules cibles de cette spec, relatifs à la racine
#: du dépôt.
_CHEMIN_RRQ: Path = _REPO_ROOT / "payroll_engine" / "rrq.py"
_CHEMIN_RQAP: Path = _REPO_ROOT / "payroll_engine" / "rqap.py"
_CHEMIN_ASSURANCE_EMPLOI: Path = _REPO_ROOT / "payroll_engine" / "assurance_emploi.py"


def _parser_module_cotisation(chemin: Path) -> ast.Module:
    """Parse un des trois modules de cotisations sociales en arbre AST.

    Échoue explicitement (``pytest.fail``) si le fichier n'existe pas
    encore — état attendu avant les tâches 9.1/10.1/11.1 de la spec
    ``cotisations-sociales-qc`` (règle 06, TDD : ce test de garde est
    rouge par absence de module, pas par erreur de collection).
    """
    if not chemin.exists():
        pytest.fail(
            f"{chemin.relative_to(_REPO_ROOT).as_posix()} n'existe pas "
            "encore. Ce test de garde précède l'implémentation (tâches "
            "9.1/10.1/11.1 de la spec cotisations-sociales-qc, règle 06) "
            "et DOIT rester rouge jusqu'à la création du module."
        )
    source = chemin.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(chemin))


def _verifier_aucune_litterale_flottante(chemin: Path) -> None:
    """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 12.1)."""
    arbre = _parser_module_cotisation(chemin)
    violations = [
        f"ligne {noeud.lineno} — {noeud.value!r}"
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, float)
    ]

    assert not violations, (
        "Littérale flottante détectée dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (règle 01). "
        "Remplacer par un ``Decimal(\"...\")`` ou une valeur lue depuis "
        "``parametres_annee``. Occurrences :\n" + "\n".join(violations)
    )


def _verifier_aucun_appel_decimal_depuis_non_str(chemin: Path) -> None:
    """Aucun ``Decimal(<non-str>)`` — ``Decimal(\"...\")`` ou ``Decimal(str(...))`` admis.

    Exception au motif strict : un appel ``Decimal(str(<expr>))`` (le
    seul argument étant lui-même un appel ``str(...)``) n'est PAS une
    violation. Ce motif est explicitement mandaté par le design
    (§Components §2, table de trace de ``calcul_rrq_employe``) pour
    convertir un entier (ex.
    ``payroll_input.pay_period.nb_periodes_annuelles``) en ``Decimal``
    sans passer par ``Decimal(int)`` (risque de heurter une éventuelle
    validation de format) ni par ``float``. Tout autre argument non
    littéral-chaîne (``Decimal(1.5)``, ``Decimal(some_variable)``,
    ``Decimal(x + y)``, etc.) reste signalé.
    """
    arbre = _parser_module_cotisation(chemin)
    violations: list[str] = []
    for noeud in ast.walk(arbre):
        if not (
            isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "Decimal"
        ):
            continue
        for argument in noeud.args:
            est_litterale_str = isinstance(argument, ast.Constant) and isinstance(
                argument.value, str
            )
            est_conversion_str = (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id == "str"
            )
            if not (est_litterale_str or est_conversion_str):
                violations.append(
                    f"ligne {noeud.lineno} — Decimal({ast.unparse(argument)})"
                )

    assert not violations, (
        "Appel ``Decimal(<non-str>)`` détecté dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (règle 01). Seule "
        "``Decimal(\"...\")`` (littérale chaîne) ou ``Decimal(str(...))`` "
        "(conversion entier-vers-Decimal via chaîne, design §Components "
        "§2) ou une valeur déjà ``Decimal`` transportée depuis "
        "``parametres_annee``/``payroll_input``/``gains`` est admise. "
        "Occurrences :\n" + "\n".join(violations)
    )


def _verifier_aucune_fonction_arrondissement_interdite(chemin: Path) -> None:
    """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc``.

    Seul ``Decimal.quantize`` est autorisé pour arrondir — détection par
    nom d'appel direct (``round(...)``) et par attribut de méthode
    (``<alias>.floor(...)``, ``<alias>.ceil(...)``, ``<alias>.trunc(...)``),
    robuste à l'alias d'import du module ``math``.
    """
    arbre = _parser_module_cotisation(chemin)
    violations: list[str] = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        fonction = noeud.func
        if isinstance(fonction, ast.Name) and fonction.id in (
            _APPELS_ARRONDISSEMENT_INTERDITS
        ):
            violations.append(f"ligne {noeud.lineno} — {fonction.id}(...)")
        elif (
            isinstance(fonction, ast.Attribute)
            and fonction.attr in _ATTRIBUTS_ARRONDISSEMENT_INTERDITS
        ):
            violations.append(f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)")

    assert not violations, (
        "Appel d'arrondissement interdit détecté dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (règle 01). Seul "
        "``Decimal.quantize(Decimal(\"0.01\"), rounding=ROUND_HALF_UP)`` "
        "est autorisé pour arrondir. Occurrences :\n" + "\n".join(violations)
    )


def _verifier_signatures_retournent_tuple_decimal_trace(
    chemin: Path, noms_fonctions: tuple[str, ...]
) -> None:
    """Chaque signature publique retourne ``tuple[Decimal, CalculationTrace]``
    sans paramètre par défaut.
    """
    arbre = _parser_module_cotisation(chemin)
    for nom in noms_fonctions:
        fonction = _trouver_fonction(arbre, nom)

        assert fonction is not None, (
            f"Aucune fonction ``{nom}`` trouvée au niveau module dans "
            f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 1.1)."
        )
        assert fonction.returns is not None, (
            f"``{nom}`` ne porte aucune annotation de retour (Req 1.4). "
            "Attendu : ``tuple[Decimal, CalculationTrace]``."
        )

        annotation_retour = ast.unparse(fonction.returns)
        assert annotation_retour == "tuple[Decimal, CalculationTrace]", (
            f"L'annotation de retour de ``{nom}`` doit être exactement "
            "``tuple[Decimal, CalculationTrace]`` (Req 1.4). "
            f"Reçu : {annotation_retour!r}"
        )

        arguments = fonction.args
        defauts_presents = bool(
            arguments.defaults
            or any(defaut is not None for defaut in arguments.kw_defaults)
        )
        assert not defauts_presents, (
            f"``{nom}`` ne doit accepter aucun paramètre par défaut "
            "(Req 1.4) — chaque appel doit fournir explicitement "
            "``payroll_input``, ``gains`` et ``parametres_annee``, sans "
            "état implicite hérité d'une valeur par défaut."
        )


class TestRrqNoFloat:
    """Aucun ``float`` dans ``payroll_engine/rrq.py`` (Req 2.7, 3.4).

    Ferme la règle 01 (« ``Decimal`` obligatoire ») côté module RRQ, par
    introspection statique de l'AST — sans dépendre d'une exécution ni
    d'un import du module. Motif identique à
    :class:`TestGainsBrutsNoFloat` (design §Testing Strategy « Détail
    des tests de garde »).

    Quatre gardes complémentaires :

    1. Aucune littérale flottante dans le code source.
    2. Aucun appel ``Decimal(<non-str>)``.
    3. Aucun appel ``round(...)``, ``math.floor(...)``, ``math.ceil(...)``
       ou ``math.trunc(...)``.
    4. Les signatures de ``calcul_rrq_employe`` et ``calcul_rrq_employeur``
       retournent l'annotation exacte ``tuple[Decimal, CalculationTrace]``
       et n'acceptent aucun paramètre par défaut.
    """

    def test_aucune_litterale_flottante(self) -> None:
        """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 2.7)."""
        _verifier_aucune_litterale_flottante(_CHEMIN_RRQ)

    def test_aucun_appel_decimal_depuis_non_str(self) -> None:
        """Aucun ``Decimal(<non-str>)`` — seule ``Decimal(\"...\")`` est admise (Req 2.7)."""
        _verifier_aucun_appel_decimal_depuis_non_str(_CHEMIN_RRQ)

    def test_aucune_fonction_arrondissement_interdite(self) -> None:
        """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc`` (Req 2.7)."""
        _verifier_aucune_fonction_arrondissement_interdite(_CHEMIN_RRQ)

    def test_signatures_retournent_tuple_decimal_trace(self) -> None:
        """``calcul_rrq_employe``/``calcul_rrq_employeur`` annotent leur retour
        ``tuple[Decimal, CalculationTrace]`` sans paramètre par défaut (Req 3.4).
        """
        _verifier_signatures_retournent_tuple_decimal_trace(
            _CHEMIN_RRQ, ("calcul_rrq_employe", "calcul_rrq_employeur")
        )


class TestRqapNoFloat:
    """Aucun ``float`` dans ``payroll_engine/rqap.py`` (Req 4.5, 5.6).

    Ferme la règle 01 côté module RQAP, par introspection statique de
    l'AST. Motif identique à :class:`TestGainsBrutsNoFloat` (design
    §Testing Strategy « Détail des tests de garde »).

    Quatre gardes complémentaires :

    1. Aucune littérale flottante dans le code source.
    2. Aucun appel ``Decimal(<non-str>)``.
    3. Aucun appel ``round(...)``, ``math.floor(...)``, ``math.ceil(...)``
       ou ``math.trunc(...)``.
    4. Les signatures de ``calcul_rqap_employe`` et
       ``calcul_rqap_employeur`` retournent l'annotation exacte
       ``tuple[Decimal, CalculationTrace]`` et n'acceptent aucun
       paramètre par défaut.
    """

    def test_aucune_litterale_flottante(self) -> None:
        """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 4.5)."""
        _verifier_aucune_litterale_flottante(_CHEMIN_RQAP)

    def test_aucun_appel_decimal_depuis_non_str(self) -> None:
        """Aucun ``Decimal(<non-str>)`` — seule ``Decimal(\"...\")`` est admise (Req 4.5)."""
        _verifier_aucun_appel_decimal_depuis_non_str(_CHEMIN_RQAP)

    def test_aucune_fonction_arrondissement_interdite(self) -> None:
        """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc`` (Req 4.5)."""
        _verifier_aucune_fonction_arrondissement_interdite(_CHEMIN_RQAP)

    def test_signatures_retournent_tuple_decimal_trace(self) -> None:
        """``calcul_rqap_employe``/``calcul_rqap_employeur`` annotent leur retour
        ``tuple[Decimal, CalculationTrace]`` sans paramètre par défaut (Req 5.6).
        """
        _verifier_signatures_retournent_tuple_decimal_trace(
            _CHEMIN_RQAP, ("calcul_rqap_employe", "calcul_rqap_employeur")
        )


class TestAssuranceEmploiNoFloat:
    """Aucun ``float`` dans ``payroll_engine/assurance_emploi.py``
    (Req 6.5, 7.4).

    Ferme la règle 01 côté module AE, par introspection statique de
    l'AST. Motif identique à :class:`TestGainsBrutsNoFloat` (design
    §Testing Strategy « Détail des tests de garde »).

    Quatre gardes complémentaires :

    1. Aucune littérale flottante dans le code source.
    2. Aucun appel ``Decimal(<non-str>)``.
    3. Aucun appel ``round(...)``, ``math.floor(...)``, ``math.ceil(...)``
       ou ``math.trunc(...)``.
    4. Les signatures de ``calcul_ae_employe`` et ``calcul_ae_employeur``
       retournent l'annotation exacte ``tuple[Decimal, CalculationTrace]``
       et n'acceptent aucun paramètre par défaut.
    """

    def test_aucune_litterale_flottante(self) -> None:
        """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 6.5)."""
        _verifier_aucune_litterale_flottante(_CHEMIN_ASSURANCE_EMPLOI)

    def test_aucun_appel_decimal_depuis_non_str(self) -> None:
        """Aucun ``Decimal(<non-str>)`` — seule ``Decimal(\"...\")`` est admise (Req 6.5)."""
        _verifier_aucun_appel_decimal_depuis_non_str(_CHEMIN_ASSURANCE_EMPLOI)

    def test_aucune_fonction_arrondissement_interdite(self) -> None:
        """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc`` (Req 6.5)."""
        _verifier_aucune_fonction_arrondissement_interdite(_CHEMIN_ASSURANCE_EMPLOI)

    def test_signatures_retournent_tuple_decimal_trace(self) -> None:
        """``calcul_ae_employe``/``calcul_ae_employeur`` annotent leur retour
        ``tuple[Decimal, CalculationTrace]`` sans paramètre par défaut (Req 7.4).
        """
        _verifier_signatures_retournent_tuple_decimal_trace(
            _CHEMIN_ASSURANCE_EMPLOI, ("calcul_ae_employe", "calcul_ae_employeur")
        )


# ===========================================================================
# 7.2 (spec cotisations-sociales-qc) — Absence de valeurs fiscales en dur
#     dans ``payroll_engine/rrq.py``, ``rqap.py``, ``assurance_emploi.py``
#     (Req 12.4)
# ===========================================================================
#
# Spec de référence : ``cotisations-sociales-qc`` — tâche 7.2. Même
# discipline que :class:`TestGainsBrutsNoHardcodedFiscalValues` (règle 06,
# TDD) : ces tests de garde sont écrits AVANT ``payroll_engine/rrq.py``,
# ``rqap.py`` et ``assurance_emploi.py`` (tâches 9.1/10.1/11.1, non
# réalisées à ce stade). Tant que ces fichiers n'existent pas, chaque test
# échoue explicitement via ``pytest.fail`` — même comportement rouge que
# :class:`TestRrqNoFloat` et consorts, via :func:`_parser_module_cotisation`.


#: Seule constante ``Decimal`` autorisée dans les trois modules de
#: cotisations sociales : le plancher/valeur neutre (Req 12.4, design
#: §Testing Strategy « Détail des tests de garde »). Tout autre littéral
#: ``Decimal("...")`` doit provenir de ``parametres_annee.rrq``/``rqap``/
#: ``assurance_emploi`` — jamais codé en dur.
#: Littéraux ``Decimal("...")`` explicitement autorisés : plancher/valeur
#: neutre (``"0.00"``) et précision d'arrondissement ``_PRECISION_MONNAIE``
#: (``"0.01"``, design §Architecture « Helper d'arrondissement partagé »).
#: Motif identique à ``_DECIMAL_NEUTRES_AUTORISES`` de
#: :class:`TestGainsBrutsNoHardcodedFiscalValues`, qui établit déjà que
#: ``"0.01"`` (littéral de précision) est légitimement admis à côté de
#: ``"0.00"`` dans ce même fichier.
_DECIMAUX_AUTORISES: tuple[str, ...] = ("0.00", "0.01")

#: Seul littéral entier nu autorisé : la précision d'arrondissement
#: (``precision_arrondissement=2``, design §Components §8/§10). Tout
#: autre littéral entier signale une valeur fiscale ou de paramétrage
#: déguisée.
_ENTIER_PRECISION_AUTORISE: int = 2


def _verifier_aucune_constante_fiscale_en_dur(chemin: Path) -> None:
    """Aucune constante ``Decimal`` ni ``int`` en dur hors plancher/précision.

    Parcourt l'arbre AST du module et signale :

    - tout appel ``Decimal("...")`` dont le contenu de la chaîne ne
      figure pas dans :data:`_DECIMAUX_AUTORISES` (``"0.00"``
      plancher/valeur neutre, ``"0.01"`` précision d'arrondissement —
      Req 12.4) ;
    - tout littéral entier nu (``ast.Constant`` de type ``int``, hors
      ``bool``) différent de ``2`` (précision d'arrondissement, Req 12.4).

    Motif identique à :class:`TestGainsBrutsNoHardcodedFiscalValues`
    (design §Testing Strategy « Détail des tests de garde »), simplifié
    ici : aucun des trois modules de cette spec ne porte de défense en
    profondeur nécessitant une liste blanche supplémentaire (contrairement
    à ``gains_bruts.py`` et son whitelist de taux de vacances).
    """
    arbre = _parser_module_cotisation(chemin)
    violations: list[str] = []

    for noeud in ast.walk(arbre):
        if (
            isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "Decimal"
        ):
            for argument in noeud.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    if argument.value not in _DECIMAUX_AUTORISES:
                        violations.append(
                            f"ligne {noeud.lineno} — Decimal({argument.value!r})"
                        )
        elif (
            isinstance(noeud, ast.Constant)
            and isinstance(noeud.value, int)
            and not isinstance(noeud.value, bool)
            and noeud.value != _ENTIER_PRECISION_AUTORISE
        ):
            violations.append(f"ligne {noeud.lineno} — {noeud.value!r} (int nu)")

    assert not violations, (
        "Constante fiscale codée en dur détectée dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (règle 05, Req 12.4). "
        "Seuls ``Decimal(\"0.00\")`` (plancher/valeur neutre), "
        "``Decimal(\"0.01\")`` (précision d'arrondissement) et l'entier "
        "``2`` (précision d'arrondissement) sont autorisés en dur — tout "
        "autre taux, plafond ou exemption DOIT être lu depuis "
        "``parametres_annee``. Occurrences :\n" + "\n".join(violations)
    )


def _verifier_aucun_motif_fiscal_partage_en_dur(chemin: Path) -> None:
    """Aucun motif fiscal partagé du domaine en dur, en défense complémentaire.

    Réutilise :data:`_MOTIFS_FISCAUX_INTERDITS` et
    :data:`_MONTANTS_BRUTS_INTERDITS_REGEX` (partagés avec
    :class:`TestNoHardcodedFiscalValues`), étendus pour couvrir les taux
    RRQ/RQAP/AE 2026 propres à cette spec (Req 12.4).
    """
    if not chemin.exists():
        pytest.fail(
            f"{chemin.relative_to(_REPO_ROOT).as_posix()} n'existe pas "
            "encore. Ce test de garde précède l'implémentation (tâches "
            "9.1/10.1/11.1 de la spec cotisations-sociales-qc, règle 06) "
            "et DOIT rester rouge jusqu'à la création du module."
        )

    violations: list[str] = []
    for numero_ligne, ligne in enumerate(
        chemin.read_text(encoding="utf-8").splitlines(), start=1
    ):
        for motif in _MOTIFS_FISCAUX_INTERDITS:
            if motif in ligne:
                violations.append(
                    f"ligne {numero_ligne} — {motif!r} : {ligne.strip()}"
                )
        for regex in _MONTANTS_BRUTS_INTERDITS_REGEX:
            if regex.search(ligne):
                violations.append(
                    f"ligne {numero_ligne} — {regex.pattern!r} : {ligne.strip()}"
                )

    assert not violations, (
        "Valeur fiscale codée en dur détectée (motif partagé, règle 05, "
        f"Req 12.4) dans {chemin.relative_to(_REPO_ROOT).as_posix()}. "
        "Déplacer chaque valeur dans ``parameters/2026/quebec.json`` ou "
        "``canada.json`` et lire via ``parametres_annee``. Occurrences :\n"
        + "\n".join(violations)
    )


class TestRrqNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``payroll_engine/rrq.py`` (Req 12.4).

    Ferme la règle 05 côté module RRQ, par deux gardes complémentaires :

    1. Introspection AST (:func:`_verifier_aucune_constante_fiscale_en_dur`) :
       aucune constante ``Decimal`` autre que ``Decimal("0.00")``
       (plancher/valeur neutre) ou ``Decimal("0.01")`` (précision
       d'arrondissement, ``_PRECISION_MONNAIE``) et aucun littéral
       entier nu autre que ``2`` (précision d'arrondissement).
    2. Lecture ligne à ligne contre les motifs fiscaux partagés du
       domaine, étendus pour couvrir les taux RRQ 2026 (``0.063``,
       ``129.63``, ``4479.30``).

    Motif identique à :class:`TestGainsBrutsNoHardcodedFiscalValues`
    (design §Testing Strategy « Détail des tests de garde »), simplifié
    car ``rrq.py`` ne porte aucune défense en profondeur nécessitant une
    liste blanche supplémentaire.
    """

    def test_aucune_constante_fiscale_en_dur(self) -> None:
        """Seuls ``Decimal("0.00")``, ``Decimal("0.01")`` et l'entier ``2`` sont autorisés (Req 12.4)."""
        _verifier_aucune_constante_fiscale_en_dur(_CHEMIN_RRQ)

    def test_aucun_motif_fiscal_partage_en_dur(self) -> None:
        """Aucun motif fiscal partagé du domaine détecté (Req 12.4)."""
        _verifier_aucun_motif_fiscal_partage_en_dur(_CHEMIN_RRQ)


class TestRqapNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``payroll_engine/rqap.py`` (Req 12.4).

    Ferme la règle 05 côté module RQAP, par les deux mêmes gardes
    complémentaires que :class:`TestRrqNoHardcodedFiscalValues`, motifs
    fiscaux partagés étendus pour couvrir les taux RQAP 2026
    (``0.0043`` employé, ``0.00602`` employeur).
    """

    def test_aucune_constante_fiscale_en_dur(self) -> None:
        """Seuls ``Decimal("0.00")``, ``Decimal("0.01")`` et l'entier ``2`` sont autorisés (Req 12.4)."""
        _verifier_aucune_constante_fiscale_en_dur(_CHEMIN_RQAP)

    def test_aucun_motif_fiscal_partage_en_dur(self) -> None:
        """Aucun motif fiscal partagé du domaine détecté (Req 12.4)."""
        _verifier_aucun_motif_fiscal_partage_en_dur(_CHEMIN_RQAP)


class TestAssuranceEmploiNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``payroll_engine/assurance_emploi.py``
    (Req 12.4).

    Ferme la règle 05 côté module AE, par les deux mêmes gardes
    complémentaires que :class:`TestRrqNoHardcodedFiscalValues`, motifs
    fiscaux partagés étendus pour couvrir les taux AE 2026 (``0.0130``
    employé, ``1.4`` multiplicateur employeur).
    """

    def test_aucune_constante_fiscale_en_dur(self) -> None:
        """Seuls ``Decimal("0.00")``, ``Decimal("0.01")`` et l'entier ``2`` sont autorisés (Req 12.4)."""
        _verifier_aucune_constante_fiscale_en_dur(_CHEMIN_ASSURANCE_EMPLOI)

    def test_aucun_motif_fiscal_partage_en_dur(self) -> None:
        """Aucun motif fiscal partagé du domaine détecté (Req 12.4)."""
        _verifier_aucun_motif_fiscal_partage_en_dur(_CHEMIN_ASSURANCE_EMPLOI)


# ===========================================================================
# 7.3 (spec cotisations-sociales-qc) — Absence d'appel à
#     ``load_parameters`` et de toute source de non-déterminisme dans
#     ``payroll_engine/rrq.py``, ``rqap.py``, ``assurance_emploi.py``
#     (Req 1.5)
# ===========================================================================
#
# Spec de référence : ``cotisations-sociales-qc`` — tâche 7.3. Même
# discipline que :class:`TestGainsBrutsNoLoadParametersCall` (règle 06,
# TDD) : ces tests de garde sont écrits AVANT ``payroll_engine/rrq.py``,
# ``rqap.py`` et ``assurance_emploi.py`` (tâches 9.1/10.1/11.1, non
# réalisées à ce stade). Tant que ces fichiers n'existent pas, chaque test
# échoue explicitement via ``pytest.fail`` — même comportement rouge que
# :class:`TestRrqNoFloat` et consorts, via :func:`_parser_module_cotisation`
# et :func:`_lire_lignes_cotisation`.


def _lire_lignes_cotisation(chemin: Path) -> list[str]:
    """Retourne les lignes d'un des trois modules de cotisations sociales.

    Échoue explicitement (``pytest.fail``) si le fichier n'existe pas
    encore — même état rouge attendu que :func:`_parser_module_cotisation`
    avant les tâches 9.1/10.1/11.1 de la spec ``cotisations-sociales-qc``
    (règle 06).
    """
    if not chemin.exists():
        pytest.fail(
            f"{chemin.relative_to(_REPO_ROOT).as_posix()} n'existe pas "
            "encore. Ce test de garde précède l'implémentation (tâches "
            "9.1/10.1/11.1 de la spec cotisations-sociales-qc, règle 06) "
            "et DOIT rester rouge jusqu'à la création du module."
        )
    return chemin.read_text(encoding="utf-8").splitlines()


def _verifier_aucun_token_load_parameters(chemin: Path) -> None:
    """Grep : aucune occurrence du token ``load_parameters`` (Req 1.5)."""
    violations: list[str] = []
    for numero_ligne, ligne in enumerate(_lire_lignes_cotisation(chemin), start=1):
        if "load_parameters" in ligne:
            violations.append(f"ligne {numero_ligne} — {ligne.strip()}")

    assert not violations, (
        "Occurrence du token ``load_parameters`` détectée dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 1.5). La "
        "fonction de calcul DOIT recevoir ``parametres_annee`` déjà "
        "matérialisé par l'appelant — jamais charger elle-même les "
        "paramètres. Occurrences :\n" + "\n".join(violations)
    )


def _verifier_aucune_ouverture_fichier_cotisation(chemin: Path) -> None:
    """Aucun ``open(...)``, ``Path(...).read_text()``/``read_bytes()``,
    ``json.load(...)``/``json.loads(...)`` (Req 1.5).

    La fonction reçoit ``parametres_annee`` déjà matérialisé — aucune
    lecture de fichier ne doit avoir lieu dans ces modules.
    """
    arbre = _parser_module_cotisation(chemin)
    violations: list[str] = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        fonction = noeud.func
        if isinstance(fonction, ast.Name) and fonction.id == "open":
            violations.append(f"ligne {noeud.lineno} — open(...)")
        elif isinstance(fonction, ast.Attribute):
            if fonction.attr in _ATTRIBUTS_OUVERTURE_FICHIER_INTERDITS:
                violations.append(
                    f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                )
            elif fonction.attr in _ATTRIBUTS_JSON_INTERDITS:
                base = ast.unparse(fonction.value)
                if "json" in base.lower():
                    violations.append(
                        f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                    )

    assert not violations, (
        "Ouverture ou désérialisation de fichier détectée dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 1.5). La "
        "fonction reçoit ``parametres_annee`` déjà matérialisé par "
        "l'appelant — aucune lecture de fichier ne doit avoir lieu ici. "
        "Occurrences :\n" + "\n".join(violations)
    )


def _verifier_aucune_source_non_determinisme_cotisation(chemin: Path) -> None:
    """Aucun ``datetime.now()``/``datetime.today()``, ``random.*``,
    ``os.environ`` (Req 1.5).
    """
    arbre = _parser_module_cotisation(chemin)
    violations: list[str] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute):
            fonction = noeud.func
            if fonction.attr in _ATTRIBUTS_DATETIME_NON_DETERMINISTES:
                base = ast.unparse(fonction.value)
                if "datetime" in base.lower():
                    violations.append(
                        f"ligne {noeud.lineno} — {ast.unparse(fonction)}(...)"
                    )
        if isinstance(noeud, ast.Attribute):
            base = ast.unparse(noeud.value)
            premier_segment = base.split(".")[0]
            if premier_segment == "random":
                violations.append(f"ligne {noeud.lineno} — {ast.unparse(noeud)}")
            if noeud.attr == "environ" and base == "os":
                violations.append(f"ligne {noeud.lineno} — os.environ")

    assert not violations, (
        "Source de non-déterminisme détectée dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 1.5). "
        "``datetime.now()``/``datetime.today()``, ``random.*`` et "
        "``os.environ`` sont proscrits — toute donnée variable doit "
        "provenir explicitement des paramètres reçus. Occurrences :\n"
        + "\n".join(violations)
    )


def _verifier_aucune_variable_module_mutable_cotisation(chemin: Path) -> None:
    """Aucune variable de module mutable (``_cache = {}``,
    ``logging.getLogger(...)`` au niveau module, etc.) (Req 1.5).
    """
    arbre = _parser_module_cotisation(chemin)
    violations: list[str] = []
    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        valeur = noeud.value
        noms_cibles = [
            cible.id for cible in noeud.targets if isinstance(cible, ast.Name)
        ]
        if not noms_cibles:
            continue

        est_litterale_mutable = isinstance(valeur, (ast.Dict, ast.List, ast.Set))
        est_appel_mutable = False
        if isinstance(valeur, ast.Call):
            appelee = valeur.func
            if (
                isinstance(appelee, ast.Name)
                and appelee.id in _APPELS_CONSTRUCTEURS_MUTABLES_INTERDITS
            ):
                est_appel_mutable = True
            elif isinstance(appelee, ast.Attribute) and appelee.attr == "getLogger":
                est_appel_mutable = True

        if est_litterale_mutable or est_appel_mutable:
            violations.append(
                f"ligne {noeud.lineno} — {', '.join(noms_cibles)} = "
                f"{ast.unparse(valeur)}"
            )

    assert not violations, (
        "Variable de module mutable détectée dans "
        f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 1.5). Un "
        "module de calcul pur ne doit exposer aucun état mutable "
        "partagé entre appels (cache, logger, etc.) au niveau module. "
        "Occurrences :\n" + "\n".join(violations)
    )


class TestRrqNoLoadParametersCall:
    """``payroll_engine/rrq.py`` n'appelle jamais ``load_parameters`` et ne
    recourt à aucune source de non-déterminisme (Req 1.5).

    Ferme la contrainte de pureté du module RRQ (design §Architecture
    « Contrainte de pureté » ; design §Testing Strategy « Détail des
    tests de garde »), motif identique à
    :class:`TestGainsBrutsNoLoadParametersCall`. Quatre gardes
    complémentaires, par introspection AST et lecture ligne à ligne du
    fichier source :

    1. Absence stricte du token ``load_parameters`` (import ou appel).
    2. Absence d'ouverture de fichier (``open(...)``,
       ``Path(...).read_text()``/``read_bytes()``,
       ``json.load(...)``/``json.loads(...)``).
    3. Absence d'appel à ``datetime.now()``/``datetime.today()``,
       ``random.*`` ou ``os.environ`` — sources de non-déterminisme
       proscrites.
    4. Absence de variable de module mutable.
    """

    def test_aucun_token_load_parameters(self) -> None:
        """Grep : aucune occurrence du token ``load_parameters`` (Req 1.5)."""
        _verifier_aucun_token_load_parameters(_CHEMIN_RRQ)

    def test_aucune_ouverture_fichier(self) -> None:
        """Aucun ``open(...)``/``read_text()``/``json.load(...)`` (Req 1.5)."""
        _verifier_aucune_ouverture_fichier_cotisation(_CHEMIN_RRQ)

    def test_aucune_source_non_determinisme(self) -> None:
        """Aucun ``datetime.now()``, ``random.*``, ``os.environ`` (Req 1.5)."""
        _verifier_aucune_source_non_determinisme_cotisation(_CHEMIN_RRQ)

    def test_aucune_variable_module_mutable(self) -> None:
        """Aucune variable de module mutable (Req 1.5)."""
        _verifier_aucune_variable_module_mutable_cotisation(_CHEMIN_RRQ)


class TestRqapNoLoadParametersCall:
    """``payroll_engine/rqap.py`` n'appelle jamais ``load_parameters`` et ne
    recourt à aucune source de non-déterminisme (Req 1.5).

    Ferme la contrainte de pureté du module RQAP, motif identique à
    :class:`TestRrqNoLoadParametersCall`. Quatre gardes complémentaires
    identiques, appliquées à ``payroll_engine/rqap.py``.
    """

    def test_aucun_token_load_parameters(self) -> None:
        """Grep : aucune occurrence du token ``load_parameters`` (Req 1.5)."""
        _verifier_aucun_token_load_parameters(_CHEMIN_RQAP)

    def test_aucune_ouverture_fichier(self) -> None:
        """Aucun ``open(...)``/``read_text()``/``json.load(...)`` (Req 1.5)."""
        _verifier_aucune_ouverture_fichier_cotisation(_CHEMIN_RQAP)

    def test_aucune_source_non_determinisme(self) -> None:
        """Aucun ``datetime.now()``, ``random.*``, ``os.environ`` (Req 1.5)."""
        _verifier_aucune_source_non_determinisme_cotisation(_CHEMIN_RQAP)

    def test_aucune_variable_module_mutable(self) -> None:
        """Aucune variable de module mutable (Req 1.5)."""
        _verifier_aucune_variable_module_mutable_cotisation(_CHEMIN_RQAP)


class TestAssuranceEmploiNoLoadParametersCall:
    """``payroll_engine/assurance_emploi.py`` n'appelle jamais
    ``load_parameters`` et ne recourt à aucune source de non-déterminisme
    (Req 1.5).

    Ferme la contrainte de pureté du module AE, motif identique à
    :class:`TestRrqNoLoadParametersCall`. Quatre gardes complémentaires
    identiques, appliquées à ``payroll_engine/assurance_emploi.py``.
    """

    def test_aucun_token_load_parameters(self) -> None:
        """Grep : aucune occurrence du token ``load_parameters`` (Req 1.5)."""
        _verifier_aucun_token_load_parameters(_CHEMIN_ASSURANCE_EMPLOI)

    def test_aucune_ouverture_fichier(self) -> None:
        """Aucun ``open(...)``/``read_text()``/``json.load(...)`` (Req 1.5)."""
        _verifier_aucune_ouverture_fichier_cotisation(_CHEMIN_ASSURANCE_EMPLOI)

    def test_aucune_source_non_determinisme(self) -> None:
        """Aucun ``datetime.now()``, ``random.*``, ``os.environ`` (Req 1.5)."""
        _verifier_aucune_source_non_determinisme_cotisation(_CHEMIN_ASSURANCE_EMPLOI)

    def test_aucune_variable_module_mutable(self) -> None:
        """Aucune variable de module mutable (Req 1.5)."""
        _verifier_aucune_variable_module_mutable_cotisation(_CHEMIN_ASSURANCE_EMPLOI)


# ===========================================================================
# 7.4 — Aucun nouveau garde-fou ``UnsupportedPayrollCase`` (Req 8.1, 8.2, 9.3)
# ===========================================================================


#: Les trois modules cibles de cette spec, regroupés pour la classe de
#: garde transversale ci-dessous.
_MODULES_COTISATIONS_SOCIALES: tuple[Path, ...] = (
    _CHEMIN_RRQ,
    _CHEMIN_RQAP,
    _CHEMIN_ASSURANCE_EMPLOI,
)


class TestCotisationsSocialesNoUnsupportedPayrollCase:
    """Aucun nouveau garde-fou ``UnsupportedPayrollCase`` dans les trois
    modules de cotisations sociales (Req 8.1, 8.2, 9.3).

    Cette spec **délègue intégralement** aux garde-fous déjà en place
    dans ``models/payroll_input.py`` et ``models/payroll_result.py``
    (validateurs de la spec ``moteur-paie-contrats``) : la province de
    travail, la fréquence de paie et le taux de vacances sont déjà
    validés en amont, avant que ``PayrollInput``/``GainsDecomposes`` ne
    parviennent aux fonctions de calcul RRQ/RQAP/AE. Aucune des six
    fonctions livrées par cette spec ne DOIT donc importer ni lever
    ``UnsupportedPayrollCase`` (design §Error Handling « Aucun nouveau
    garde-fou »).

    Contrairement aux classes de garde des tâches 7.1 à 7.3 (une classe
    par module), cette classe est **transversale** : un seul test
    paramétré couvre les trois modules, motif cohérent avec le
    caractère strictement identique de la garde sur les trois fichiers.
    """

    @pytest.mark.parametrize(
        "chemin",
        _MODULES_COTISATIONS_SOCIALES,
        ids=lambda c: c.name,
    )
    def test_aucun_token_unsupported_payroll_case(self, chemin: Path) -> None:
        """Grep : aucune occurrence du token ``UnsupportedPayrollCase``
        (Req 8.1, 8.2, 9.3).
        """
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(
            _lire_lignes_cotisation(chemin), start=1
        ):
            if "UnsupportedPayrollCase" in ligne:
                violations.append(f"ligne {numero_ligne} — {ligne.strip()}")

        assert not violations, (
            "Occurrence du token ``UnsupportedPayrollCase`` détectée dans "
            f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 8.1, 8.2, "
            "9.3). Cette spec délègue intégralement aux garde-fous "
            "existants de ``PayrollInput``/``GainsDecomposes`` — aucun "
            "nouveau garde-fou ne doit être introduit ici. Occurrences :\n"
            + "\n".join(violations)
        )


# ===========================================================================
# 5.1 (spec impots-retenues-source) — Absence de ``float`` dans
#     ``payroll_engine/impot_qc.py`` et ``payroll_engine/impot_federal.py``
#     (Req 2.6, 3.5, 4.7, 5.5)
# ===========================================================================
#
# Spec de référence : ``impots-retenues-source`` — tâche 5.1. Même
# discipline TDD (règle 06) que :class:`TestRrqNoFloat` et consorts : ces
# tests de garde sont écrits AVANT ``payroll_engine/impot_qc.py`` et
# ``payroll_engine/impot_federal.py`` (tâches d'implémentation non encore
# réalisées). Tant que ces fichiers n'existent pas, chaque test échoue
# explicitement via :func:`_parser_module_cotisation` (``pytest.fail`` —
# et non par une erreur de collection), ce qui est le comportement rouge
# attendu.
#
# Les quatre helpers partagés réutilisés ci-dessous
# (:func:`_verifier_aucune_litterale_flottante`,
# :func:`_verifier_aucun_appel_decimal_depuis_non_str`,
# :func:`_verifier_aucune_fonction_arrondissement_interdite`,
# :func:`_verifier_signatures_retournent_tuple_decimal_trace`) sont
# strictement génériques (introspection AST paramétrée par un chemin) et
# s'appliquent tels quels aux modules d'impôt. En particulier,
# :func:`_verifier_aucun_appel_decimal_depuis_non_str` admet déjà
# ``Decimal(str(...))`` — motif requis par les modules d'impôt pour
# convertir ``nb_periodes_annuelles`` (entier) en ``Decimal`` sans passer
# par ``float`` ni ``Decimal(int)``.


#: Chemins des deux modules cibles de cette spec, relatifs à la racine du
#: dépôt.
_CHEMIN_IMPOT_QC: Path = _REPO_ROOT / "payroll_engine" / "impot_qc.py"
_CHEMIN_IMPOT_FEDERAL: Path = _REPO_ROOT / "payroll_engine" / "impot_federal.py"


class TestImpotQCNoFloat:
    """Aucun ``float`` dans ``payroll_engine/impot_qc.py`` (Req 2.6, 3.5).

    Ferme la règle 01 (« ``Decimal`` obligatoire ») côté module impôt QC,
    par introspection statique de l'AST — sans dépendre d'une exécution ni
    d'un import du module. Motif identique à :class:`TestRrqNoFloat`
    (design §Testing Strategy « Détail des tests de garde »).

    Quatre gardes complémentaires :

    1. Aucune littérale flottante dans le code source.
    2. Aucun appel ``Decimal(<non-str>)`` — ``Decimal("...")`` et
       ``Decimal(str(...))`` (conversion ``nb_periodes_annuelles``) admis.
    3. Aucun appel ``round(...)``, ``math.floor(...)``, ``math.ceil(...)``
       ou ``math.trunc(...)``.
    4. Les signatures de ``calcul_impot_qc_formule`` et
       ``calcul_impot_qc_retenu`` retournent l'annotation exacte
       ``tuple[Decimal, CalculationTrace]`` et n'acceptent aucun
       paramètre par défaut.
    """

    def test_aucune_litterale_flottante(self) -> None:
        """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 2.6)."""
        _verifier_aucune_litterale_flottante(_CHEMIN_IMPOT_QC)

    def test_aucun_appel_decimal_depuis_non_str(self) -> None:
        """Aucun ``Decimal(<non-str>)`` — ``Decimal("...")``/``Decimal(str(...))`` admis (Req 2.6)."""
        _verifier_aucun_appel_decimal_depuis_non_str(_CHEMIN_IMPOT_QC)

    def test_aucune_fonction_arrondissement_interdite(self) -> None:
        """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc`` (Req 2.6)."""
        _verifier_aucune_fonction_arrondissement_interdite(_CHEMIN_IMPOT_QC)

    def test_signatures_retournent_tuple_decimal_trace(self) -> None:
        """``calcul_impot_qc_formule``/``calcul_impot_qc_retenu`` annotent leur
        retour ``tuple[Decimal, CalculationTrace]`` sans paramètre par défaut (Req 3.5).
        """
        _verifier_signatures_retournent_tuple_decimal_trace(
            _CHEMIN_IMPOT_QC,
            ("calcul_impot_qc_formule", "calcul_impot_qc_retenu"),
        )


class TestImpotFederalNoFloat:
    """Aucun ``float`` dans ``payroll_engine/impot_federal.py`` (Req 4.7, 5.5).

    Ferme la règle 01 côté module impôt fédéral, par introspection
    statique de l'AST. Motif identique à :class:`TestRrqNoFloat` (design
    §Testing Strategy « Détail des tests de garde »).

    Quatre gardes complémentaires :

    1. Aucune littérale flottante dans le code source.
    2. Aucun appel ``Decimal(<non-str>)`` — ``Decimal("...")`` et
       ``Decimal(str(...))`` (conversion ``nb_periodes_annuelles``) admis.
    3. Aucun appel ``round(...)``, ``math.floor(...)``, ``math.ceil(...)``
       ou ``math.trunc(...)``.
    4. Les signatures de ``calcul_impot_federal_formule`` et
       ``calcul_impot_federal_retenu`` retournent l'annotation exacte
       ``tuple[Decimal, CalculationTrace]`` et n'acceptent aucun
       paramètre par défaut.
    """

    def test_aucune_litterale_flottante(self) -> None:
        """Aucun ``ast.Constant`` de type ``float`` dans le module (Req 4.7)."""
        _verifier_aucune_litterale_flottante(_CHEMIN_IMPOT_FEDERAL)

    def test_aucun_appel_decimal_depuis_non_str(self) -> None:
        """Aucun ``Decimal(<non-str>)`` — ``Decimal("...")``/``Decimal(str(...))`` admis (Req 4.7)."""
        _verifier_aucun_appel_decimal_depuis_non_str(_CHEMIN_IMPOT_FEDERAL)

    def test_aucune_fonction_arrondissement_interdite(self) -> None:
        """Aucun ``round``/``math.floor``/``math.ceil``/``math.trunc`` (Req 4.7)."""
        _verifier_aucune_fonction_arrondissement_interdite(_CHEMIN_IMPOT_FEDERAL)

    def test_signatures_retournent_tuple_decimal_trace(self) -> None:
        """``calcul_impot_federal_formule``/``calcul_impot_federal_retenu`` annotent
        leur retour ``tuple[Decimal, CalculationTrace]`` sans paramètre par défaut (Req 5.5).
        """
        _verifier_signatures_retournent_tuple_decimal_trace(
            _CHEMIN_IMPOT_FEDERAL,
            ("calcul_impot_federal_formule", "calcul_impot_federal_retenu"),
        )


# ===========================================================================
# 5.2 (spec impots-retenues-source) — Aucune valeur fiscale codée en dur
#      dans ``impot_qc.py`` ni ``impot_federal.py`` (règle 05, Req 10.4)
# ===========================================================================
#
# Ces deux classes réutilisent telles quelles les gardes partagées de la
# spec ``cotisations-sociales-qc`` (tâche 7.2) :
#
# - :func:`_verifier_aucune_constante_fiscale_en_dur` (AST) — garde
#   *primaire*, **value-agnostic** : interdit tout littéral
#   ``Decimal("...")`` autre que ``Decimal("0.00")`` (plancher/valeur
#   neutre) et ``Decimal("0.01")`` (précision d'arrondissement), ainsi que
#   tout littéral entier nu autre que ``2`` (précision). Comme elle ne
#   dépend d'aucune valeur numérique connue, elle enforce pleinement le
#   Req 10.4 (aucun taux/palier/crédit/déduction/abattement en dur) sans
#   avoir besoin de connaître les valeurs officielles 2026.
# - :func:`_verifier_aucun_motif_fiscal_partage_en_dur` — garde
#   *complémentaire* (défense en profondeur) contre les motifs fiscaux
#   partagés déjà listés dans :data:`_MOTIFS_FISCAUX_INTERDITS`.
#
# NOTE (extension future de ``_MOTIFS_FISCAUX_INTERDITS``) : la tâche 5.2
# prévoit d'étendre optionnellement les motifs partagés pour couvrir les
# paliers, crédits convertibles, déduction pour travailleur et abattement
# du Québec 2026. Ces valeurs ne sont toutefois confirmées qu'en tâche 6
# (remplissage de ``parameters/2026/quebec.json`` et ``canada.json`` depuis
# le TP-1015.F 2026 / T4127 2026). Ajouter dès maintenant des littéraux
# 2026 *non confirmés* serait contre-productif (motifs erronés). La garde
# AST value-agnostic ci-dessus étant déjà suffisante pour le Req 10.4,
# aucun littéral spéculatif n'est ajouté ici ; ``_MOTIFS_FISCAUX_INTERDITS``
# pourra être étendu une fois la tâche 6 close et les valeurs officielles
# établies.


class TestImpotQCNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``payroll_engine/impot_qc.py`` (Req 10.4).

    Ferme la règle 05 côté module impôt QC, par les deux mêmes gardes
    complémentaires que :class:`TestRrqNoHardcodedFiscalValues` :

    1. Introspection AST (:func:`_verifier_aucune_constante_fiscale_en_dur`) :
       aucune constante ``Decimal`` autre que ``Decimal("0.00")``
       (plancher/valeur neutre) ou ``Decimal("0.01")`` (précision
       d'arrondissement) et aucun littéral entier nu autre que ``2``
       (précision d'arrondissement). Garde *value-agnostic* : tout palier,
       taux, crédit convertible, déduction pour travailleur ou abattement
       DOIT être lu depuis ``parametres_annee.impot_quebec`` — jamais codé
       en dur.
    2. Lecture ligne à ligne contre les motifs fiscaux partagés du domaine
       (:func:`_verifier_aucun_motif_fiscal_partage_en_dur`), en défense
       complémentaire.
    """

    def test_aucune_constante_fiscale_en_dur(self) -> None:
        """Seuls ``Decimal("0.00")``, ``Decimal("0.01")`` et l'entier ``2`` sont autorisés (Req 10.4)."""
        _verifier_aucune_constante_fiscale_en_dur(_CHEMIN_IMPOT_QC)

    def test_aucun_motif_fiscal_partage_en_dur(self) -> None:
        """Aucun motif fiscal partagé du domaine détecté (Req 10.4)."""
        _verifier_aucun_motif_fiscal_partage_en_dur(_CHEMIN_IMPOT_QC)


class TestImpotFederalNoHardcodedFiscalValues:
    """Aucune valeur fiscale en dur dans ``payroll_engine/impot_federal.py``
    (Req 10.4).

    Ferme la règle 05 côté module impôt fédéral, par les deux mêmes gardes
    complémentaires que :class:`TestRrqNoHardcodedFiscalValues`. La garde
    AST *value-agnostic* interdit tout palier, taux, crédit convertible,
    montant canadien pour emploi, plafond de cotisation de base RRQ ou
    abattement du Québec codé en dur ; ces valeurs DOIVENT provenir de
    ``parametres_annee.impot_federal`` (et des sections ``rrq``/``rqap``/
    ``assurance_emploi`` pour le crédit K2Q).
    """

    def test_aucune_constante_fiscale_en_dur(self) -> None:
        """Seuls ``Decimal("0.00")``, ``Decimal("0.01")`` et l'entier ``2`` sont autorisés (Req 10.4)."""
        _verifier_aucune_constante_fiscale_en_dur(_CHEMIN_IMPOT_FEDERAL)

    def test_aucun_motif_fiscal_partage_en_dur(self) -> None:
        """Aucun motif fiscal partagé du domaine détecté (Req 10.4)."""
        _verifier_aucun_motif_fiscal_partage_en_dur(_CHEMIN_IMPOT_FEDERAL)


# ===========================================================================
# 5.3 (spec impots-retenues-source) — Contrainte de pureté : aucun appel à
#      ``load_parameters`` ni source de non-déterminisme dans ``impot_qc.py``
#      et ``impot_federal.py`` (Req 1.5)
# ===========================================================================
#
# Ces deux classes réutilisent telles quelles les quatre gardes partagées de
# la spec ``cotisations-sociales-qc`` (tâche 7.3), motif identique à
# :class:`TestRrqNoLoadParametersCall` (design §Testing Strategy « Détail des
# tests de garde ») :
#
# - :func:`_verifier_aucun_token_load_parameters` — grep du token
#   ``load_parameters`` (ni import, ni appel).
# - :func:`_verifier_aucune_ouverture_fichier_cotisation` — absence
#   d'ouverture de fichier (``open(...)``, ``json.load(...)``/``json.loads``,
#   ``Path(...).read_text()``/``read_bytes()``).
# - :func:`_verifier_aucune_source_non_determinisme_cotisation` — absence de
#   ``datetime.now()``/``datetime.today()``, ``random.*``, ``os.environ``.
# - :func:`_verifier_aucune_variable_module_mutable_cotisation` — absence de
#   variable de module mutable.
#
# La contrainte de pureté impose que ``impot_qc.py`` et ``impot_federal.py``
# reçoivent leurs paramètres en argument (``parametres_annee``) et ne les
# chargent jamais eux-mêmes : le chargement reste la responsabilité exclusive
# de l'orchestrateur (design §Architecture « Contrainte de pureté »).


class TestImpotQCNoLoadParametersCall:
    """``payroll_engine/impot_qc.py`` n'appelle jamais ``load_parameters`` et
    ne recourt à aucune source de non-déterminisme (Req 1.5).

    Ferme la contrainte de pureté du module impôt QC (design §Architecture
    « Contrainte de pureté » ; design §Testing Strategy « Détail des tests de
    garde »), motif identique à :class:`TestRrqNoLoadParametersCall`. Quatre
    gardes complémentaires, par introspection AST et lecture ligne à ligne du
    fichier source :

    1. Absence stricte du token ``load_parameters`` (import ou appel).
    2. Absence d'ouverture de fichier (``open(...)``,
       ``Path(...).read_text()``/``read_bytes()``,
       ``json.load(...)``/``json.loads(...)``).
    3. Absence d'appel à ``datetime.now()``/``datetime.today()``,
       ``random.*`` ou ``os.environ`` — sources de non-déterminisme
       proscrites.
    4. Absence de variable de module mutable.
    """

    def test_aucun_token_load_parameters(self) -> None:
        """Grep : aucune occurrence du token ``load_parameters`` (Req 1.5)."""
        _verifier_aucun_token_load_parameters(_CHEMIN_IMPOT_QC)

    def test_aucune_ouverture_fichier(self) -> None:
        """Aucun ``open(...)``/``read_text()``/``json.load(...)`` (Req 1.5)."""
        _verifier_aucune_ouverture_fichier_cotisation(_CHEMIN_IMPOT_QC)

    def test_aucune_source_non_determinisme(self) -> None:
        """Aucun ``datetime.now()``, ``random.*``, ``os.environ`` (Req 1.5)."""
        _verifier_aucune_source_non_determinisme_cotisation(_CHEMIN_IMPOT_QC)

    def test_aucune_variable_module_mutable(self) -> None:
        """Aucune variable de module mutable (Req 1.5)."""
        _verifier_aucune_variable_module_mutable_cotisation(_CHEMIN_IMPOT_QC)


class TestImpotFederalNoLoadParametersCall:
    """``payroll_engine/impot_federal.py`` n'appelle jamais ``load_parameters``
    et ne recourt à aucune source de non-déterminisme (Req 1.5).

    Ferme la contrainte de pureté du module impôt fédéral, motif identique à
    :class:`TestRrqNoLoadParametersCall`. Quatre gardes complémentaires
    identiques, appliquées à ``payroll_engine/impot_federal.py``.
    """

    def test_aucun_token_load_parameters(self) -> None:
        """Grep : aucune occurrence du token ``load_parameters`` (Req 1.5)."""
        _verifier_aucun_token_load_parameters(_CHEMIN_IMPOT_FEDERAL)

    def test_aucune_ouverture_fichier(self) -> None:
        """Aucun ``open(...)``/``read_text()``/``json.load(...)`` (Req 1.5)."""
        _verifier_aucune_ouverture_fichier_cotisation(_CHEMIN_IMPOT_FEDERAL)

    def test_aucune_source_non_determinisme(self) -> None:
        """Aucun ``datetime.now()``, ``random.*``, ``os.environ`` (Req 1.5)."""
        _verifier_aucune_source_non_determinisme_cotisation(_CHEMIN_IMPOT_FEDERAL)

    def test_aucune_variable_module_mutable(self) -> None:
        """Aucune variable de module mutable (Req 1.5)."""
        _verifier_aucune_variable_module_mutable_cotisation(_CHEMIN_IMPOT_FEDERAL)


# ===========================================================================
# 5.4 (spec impots-retenues-source) — Indépendance de ``impot_federal.py``
#      vis-à-vis des fonctions de cotisations sociales (Req 6.3)
# ===========================================================================
#
# Le mécanisme K2Q de ``calcul_impot_federal_formule`` recompose LOCALEMENT
# les projections annualisées des cotisations RRQ (taux de base), AE et RQAP
# à partir de ``gains.brut_total``, ``nb_periodes_annuelles`` et des sections
# de paramètres ``parametres_annee.rrq``/``.rqap``/``.assurance_emploi``. Il
# ne DOIT jamais appeler les fonctions réelles ``calcul_rrq_employe``,
# ``calcul_rqap_employe`` ou ``calcul_ae_employe`` de la spec
# ``cotisations-sociales-qc``, ni importer les modules qui les hébergent
# (design §Error Handling « Ce que les quatre fonctions NE font PAS » ;
# §Séparation exonération / cotisations sociales).
#
# NUANCE IMPORTANTE : la LECTURE des sections de paramètres
# (``parametres_annee.rrq``/``.rqap``/``.assurance_emploi`` — simple accès
# d'attribut sur l'objet paramètres) reste AUTORISÉE et ne DOIT pas être
# signalée. Seuls sont proscrits :
#   - les tokens de fonction ``calcul_rrq_employe``/``calcul_rqap_employe``/
#     ``calcul_ae_employe`` (appel ou import) ;
#   - les imports des modules ``payroll_engine.rrq``/``payroll_engine.rqap``/
#     ``payroll_engine.assurance_emploi``.
# La garde matche donc sur ces noms de fonction précis et sur les
# statements d'import, JAMAIS sur les sous-chaînes génériques
# ``rrq``/``rqap``/``assurance_emploi``.


#: Noms de fonction des cotisations sociales interdits dans
#: ``impot_federal.py`` — appel ou import (Req 6.3).
_FONCTIONS_COTISATION_INTERDITES: tuple[str, ...] = (
    "calcul_rrq_employe",
    "calcul_rqap_employe",
    "calcul_ae_employe",
)

#: Modules de cotisations sociales dont l'import est interdit dans
#: ``impot_federal.py`` (Req 6.3).
_MODULES_COTISATION_INTERDITS: tuple[str, ...] = (
    "payroll_engine.rrq",
    "payroll_engine.rqap",
    "payroll_engine.assurance_emploi",
)


def _ligne_importe_module(ligne: str, module: str) -> bool:
    """Vrai si ``ligne`` importe ``module`` (``from <module> import ...`` ou
    ``import <module>``), tolérant les espaces multiples et un alias ``as``.

    Ne matche que des statements d'import — un simple accès d'attribut
    ``parametres_annee.rrq`` ne contient pas le préfixe ``payroll_engine.``
    et n'est donc jamais capté.
    """
    ligne_nettoyee = ligne.strip()
    return (
        ligne_nettoyee.startswith(f"from {module} import")
        or ligne_nettoyee.startswith(f"from {module}.")
        or ligne_nettoyee == f"import {module}"
        or ligne_nettoyee.startswith(f"import {module} ")
        or ligne_nettoyee.startswith(f"import {module} as ")
        or ligne_nettoyee.startswith(f"import {module}.")
    )


class TestImpotFederalNoRrqRqapAeFunctionCalls:
    """``payroll_engine/impot_federal.py`` n'appelle jamais — et n'importe
    jamais — les fonctions de cotisations sociales (Req 6.3).

    Le crédit K2Q est recomposé localement depuis
    ``parametres_annee.rrq``/``.rqap``/``.assurance_emploi`` ; les fonctions
    réelles ``calcul_rrq_employe``/``calcul_rqap_employe``/``calcul_ae_employe``
    de la spec ``cotisations-sociales-qc`` ne DOIVENT jamais être invoquées,
    et leurs modules d'accueil ne DOIVENT jamais être importés (design
    §Testing Strategy « Détail des tests de garde » ; §Error Handling « Ce que
    les quatre fonctions NE font PAS »).

    La LECTURE des sections de paramètres reste autorisée : la garde ne
    matche que les noms de fonction précis et les statements d'import, jamais
    les sous-chaînes ``rrq``/``rqap``/``assurance_emploi`` en général.

    Réutilise le helper de lecture ligne à ligne :func:`_lire_lignes_cotisation`
    (même état rouge « module inexistant » attendu avant la tâche 9.x, règle 06).
    """

    def test_aucun_appel_fonction_cotisation(self) -> None:
        """Grep : aucun token ``calcul_rrq_employe``/``calcul_rqap_employe``/
        ``calcul_ae_employe`` dans le module (Req 6.3)."""
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(
            _lire_lignes_cotisation(_CHEMIN_IMPOT_FEDERAL), start=1
        ):
            for fonction in _FONCTIONS_COTISATION_INTERDITES:
                if fonction in ligne:
                    violations.append(
                        f"ligne {numero_ligne} — {fonction} : {ligne.strip()}"
                    )

        assert not violations, (
            "Appel/import d'une fonction de cotisations sociales détecté dans "
            f"{_CHEMIN_IMPOT_FEDERAL.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 6.3). Le crédit K2Q DOIT être recomposé localement depuis "
            "``parametres_annee.rrq``/``.rqap``/``.assurance_emploi`` — jamais "
            "via ``calcul_rrq_employe``/``calcul_rqap_employe``/"
            "``calcul_ae_employe``. Occurrences :\n" + "\n".join(violations)
        )

    def test_aucun_import_module_cotisation(self) -> None:
        """Grep : aucun import de ``payroll_engine.rrq``/``.rqap``/
        ``.assurance_emploi`` (Req 6.3)."""
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(
            _lire_lignes_cotisation(_CHEMIN_IMPOT_FEDERAL), start=1
        ):
            for module in _MODULES_COTISATION_INTERDITS:
                if _ligne_importe_module(ligne, module):
                    violations.append(
                        f"ligne {numero_ligne} — {module} : {ligne.strip()}"
                    )

        assert not violations, (
            "Import d'un module de cotisations sociales détecté dans "
            f"{_CHEMIN_IMPOT_FEDERAL.relative_to(_REPO_ROOT).as_posix()} "
            "(Req 6.3). ``impot_federal.py`` ne DOIT importer ni "
            "``payroll_engine.rrq``, ni ``payroll_engine.rqap``, ni "
            "``payroll_engine.assurance_emploi`` : le mécanisme K2Q est "
            "indépendant de ces modules. Occurrences :\n" + "\n".join(violations)
        )


# ===========================================================================
# 5.5 (spec impots-retenues-source) — Aucun nouveau garde-fou
#      ``UnsupportedPayrollCase`` dans ``impot_qc.py`` ni ``impot_federal.py``
#      (Req 13.1, 13.2, 13.3)
# ===========================================================================
#
# Miroir strict de :class:`TestCotisationsSocialesNoUnsupportedPayrollCase`
# (spec ``cotisations-sociales-qc`` tâche 7.4) appliqué aux deux modules
# d'impôt. Cette spec **délègue intégralement** aux garde-fous déjà en place
# dans ``models/payroll_input.py`` et ``models/payroll_result.py``
# (validateurs de la spec ``moteur-paie-contrats``) : province de travail,
# fréquence de paie et taux de vacances sont validés en amont, avant que
# ``PayrollInput``/``GainsDecomposes`` ne parviennent aux quatre fonctions
# de calcul d'impôt. Aucune de ces fonctions ne DOIT donc importer ni lever
# ``UnsupportedPayrollCase`` (design §Error Handling « Aucun nouveau
# garde-fou », Req 13.1, 13.2, 13.3).


#: Les deux modules cibles de cette spec, regroupés pour la classe de garde
#: transversale ci-dessous.
_MODULES_IMPOT: tuple[Path, ...] = (
    _CHEMIN_IMPOT_QC,
    _CHEMIN_IMPOT_FEDERAL,
)


class TestImpotNoUnsupportedPayrollCase:
    """Aucun nouveau garde-fou ``UnsupportedPayrollCase`` dans les deux
    modules d'impôt (Req 13.1, 13.2, 13.3).

    Cette spec **délègue intégralement** aux garde-fous déjà portés à la
    construction par ``PayrollInput``/``GainsDecomposes`` (validateurs de la
    spec ``moteur-paie-contrats``) : la province de travail, la fréquence de
    paie et le taux de vacances sont déjà validés en amont, avant que ces
    modèles ne parviennent aux fonctions ``calcul_impot_qc_formule``/
    ``calcul_impot_qc_retenu``/``calcul_impot_federal_formule``/
    ``calcul_impot_federal_retenu``. Aucune de ces quatre fonctions ne DOIT
    donc importer ni lever ``UnsupportedPayrollCase`` (design §Error Handling
    « Aucun nouveau garde-fou »).

    Contrairement aux classes de garde des tâches 5.1 à 5.4 (une classe par
    module, ou spécifique à ``impot_federal.py``), cette classe est
    **transversale** : un seul test paramétré couvre les deux modules, motif
    cohérent avec le caractère strictement identique de la garde sur les deux
    fichiers — miroir de
    :class:`TestCotisationsSocialesNoUnsupportedPayrollCase`.

    Réutilise le helper de lecture ligne à ligne
    :func:`_lire_lignes_cotisation` (même état rouge « module inexistant »
    attendu avant la tâche 9.x, règle 06).
    """

    @pytest.mark.parametrize(
        "chemin",
        _MODULES_IMPOT,
        ids=lambda c: c.name,
    )
    def test_aucun_token_unsupported_payroll_case(self, chemin: Path) -> None:
        """Grep : aucune occurrence du token ``UnsupportedPayrollCase``
        (Req 13.1, 13.2, 13.3).
        """
        violations: list[str] = []
        for numero_ligne, ligne in enumerate(
            _lire_lignes_cotisation(chemin), start=1
        ):
            if "UnsupportedPayrollCase" in ligne:
                violations.append(f"ligne {numero_ligne} — {ligne.strip()}")

        assert not violations, (
            "Occurrence du token ``UnsupportedPayrollCase`` détectée dans "
            f"{chemin.relative_to(_REPO_ROOT).as_posix()} (Req 13.1, 13.2, "
            "13.3). Cette spec délègue intégralement aux garde-fous "
            "existants de ``PayrollInput``/``GainsDecomposes`` — aucun "
            "nouveau garde-fou ne doit être introduit ici. Occurrences :\n"
            + "\n".join(violations)
        )
