"""Modèle ``Employee`` — fiche employé strictement non sensible.

Spec de référence : ``moteur-paie-contrats`` — tâche 6.2.
Design de référence : sections « Components and Interfaces » §5 et
« Data Models » §4 (``design.md``).

Ce module implémente **uniquement** le constructeur principal du modèle
:class:`Employee`. La fabrique :meth:`Employee.avec_defauts_par_annee`
(Req 1.7) relève de la tâche 6.3 et sera greffée ultérieurement.

Contrat porté par ce modèle (Req 1.1 & §Data Models 4 du design) :

- 15 champs exhaustifs, aucun de plus (``extra="forbid"``) ;
- ``frozen=True`` — toute mutation post-construction lève
  ``pydantic.ValidationError`` (Req 1.6) ;
- ``str_strip_whitespace=True`` — les identifiants et libellés sont
  normalisés en supprimant les blancs de bord, ce qui préserve la
  contrainte ``min_length=1`` sans faux positifs sur ``"  "`` ;
- rejet transversal de ``float`` sur les 6 champs monétaires typés
  ``Decimal`` (règle 01, Req 1.4, Req 10.1) via
  :func:`models._validators.reject_float` en ``mode="before"`` ;
- rejet fail-fast des clés apparentées à des données sensibles (Req 1.3,
  règle 04) via :func:`models._validators.reject_sensitive_fields` en
  ``model_validator(mode="before")`` ;
- refus fail-fast à la frontière (règle 03) : province ≠ QC et taux de
  vacances ∉ ``{0.04, 0.06}`` lèvent :class:`UnsupportedPayrollCase`
  avec un message qui cite explicitement WebRAS et PDOC (Req 1.5,
  Req 11.1, Req 11.3, Req 11.6, Property 16).

Discipline exception (Req 8.7, design §Components 2) :

Le ``model_validator(mode="after")`` de refus à la frontière lève
directement :class:`UnsupportedPayrollCase`. En Pydantic v2, seuls
``ValueError``, ``AssertionError`` et ``PydanticCustomError`` levés dans
un validateur sont enveloppés dans ``ValidationError`` ; toute autre
exception se propage nativement. Comme :class:`UnsupportedPayrollCase`
dérive de :class:`Exception` (via :class:`PayrollDomainError`), elle
remonte telle quelle au consommateur — condition indispensable pour
préserver la disjonction stricte entre exceptions du domaine et erreurs
de validation Pydantic (Req 8.7).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit ;
- Règle 03 — périmètre Camp LilySO strict, refus fail-fast hors matrice ;
- Règle 04 — aucune donnée personnelle sensible ;
- Règle 06 — TDD ; tests écrits avant ce module
  (``tests/models/test_employee.py``, tâche 6.1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from models._validators import (
    _parse_json_reject_floats,
    reject_float,
    reject_sensitive_fields,
)
from models.enums import Juridiction
from models.exceptions import UnsupportedPayrollCase


#: Ensemble fermé des taux d'indemnité de vacances admis dans le périmètre
#: Camp LilySO (règle 03, Req 11.3). Les Normes du travail QC prévoient 4 %
#: la première et deuxième année de service, 6 % à compter de la troisième
#: année. Toute autre valeur est hors matrice et lève
#: :class:`UnsupportedPayrollCase` à la construction.
#:
#: Ce ``frozenset`` matérialise deux constantes *métier* (pas fiscales au
#: sens de la règle 05) qui figurent explicitement dans la matrice de
#: support ``docs/cas-non-supportes.md`` — elles peuvent donc rester
#: codées dans le validateur, comme le documente le design §Architecture
#: point 3.
_TAUX_VACANCES_SUPPORTES: frozenset[Decimal] = frozenset(
    (Decimal("0.04"), Decimal("0.06"))
)


class Employee(BaseModel):
    """Fiche employé strictement non sensible du Camp LilySO.

    Instance immuable (``frozen=True``) portant les 15 champs déclarés
    par Req 1.1 et validés à la construction. Aucun champ supplémentaire
    n'est admis (``extra="forbid"``, Req 1.2) ; aucune clé apparentée à
    une donnée sensible n'est admise (règle 04, Req 1.3) ; aucun montant
    fourni sous forme de ``float`` n'est admis (règle 01, Req 1.4) ; les
    cas hors matrice Camp LilySO (province ≠ QC, taux de vacances hors
    ``{0.04, 0.06}``) lèvent :class:`UnsupportedPayrollCase` avec un
    message renvoyant à WebRAS et PDOC (règle 03, Req 1.5, Req 11.6).

    La fabrique :meth:`avec_defauts_par_annee` (Req 1.7) sera implémentée
    par la tâche 6.3 et lira les valeurs par défaut via le chargeur de
    paramètres, sans aucune valeur en dur.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    # ---- Identité & rattachement (Req 1.1 AC1) --------------------------

    id: str = Field(..., min_length=1)
    """Identifiant technique interne (ex. ``"EMP001"``). Anonymisable :
    cette clé NE DOIT PAS être un NAS ni une donnée nominative réelle."""

    nom_affichage: str = Field(..., min_length=1)
    """Libellé affichable, potentiellement anonymisé
    (ex. ``"Monitrice EMP001"``). Aucune obligation d'y stocker un nom
    complet réel — c'est même contraire à la règle 04."""

    date_naissance: date
    """Date de naissance fictive/anonymisée dans les tests et les
    exemples (règle 04). Champ requis pour de futurs calculs d'âge liés
    aux exemptions RRQ (âge < 18 / >= 65), non implémentés par cette spec."""

    province_travail: Juridiction
    """Province de travail. Contrainte à :attr:`Juridiction.QUEBEC`
    par le validateur ``_refuser_hors_matrice`` (Req 1.5, Req 11.1)."""

    titre_emploi: str = Field(..., min_length=1)
    """Titre d'emploi de l'employé (ex. ``"Monitrice"``, ``"Cuisinier"``)."""

    # ---- Rémunération de base (Req 1.1 AC1) ------------------------------

    taux_horaire_base: Decimal = Field(..., gt=Decimal("0"))
    """Taux horaire de base en dollars canadiens, strictement positif.
    Un taux nul ou négatif n'a pas de sens économique et lèverait des
    incohérences aval (brut négatif, retenues négatives)."""

    # ---- Emploi (dates de service) --------------------------------------

    date_embauche: date
    """Date d'embauche effective — début de la période de service qui
    déclenche l'application du taux de vacances."""

    date_fin_emploi: date | None = None
    """Date de fin d'emploi le cas échéant ; ``None`` tant que
    l'employé est actif. Le typage ``date | None`` autorise l'absence
    de la clé à la construction (comportement par défaut)."""

    # ---- Vacances (Req 11.3) ---------------------------------------------

    taux_indemnite_vacances: Decimal
    """Taux d'indemnité de vacances applicable, dans
    ``{Decimal("0.04"), Decimal("0.06")}`` (Req 11.3). Toute autre valeur
    est refusée par le validateur ``_refuser_hors_matrice`` avec
    :class:`UnsupportedPayrollCase` (règle 03)."""

    # ---- Statut fiscal TP-1015.3 / TD1 (Req 1.1 AC1) ---------------------

    exoneration_TP1015_3: bool
    """Drapeau d'exonération de retenue provinciale déclaré au
    formulaire TP-1015.3 par l'employé. ``True`` signifie que la
    retenue d'impôt QC est nulle pour la période, quel que soit le
    résultat de la formule."""

    exoneration_TD1: bool
    """Drapeau d'exonération de retenue fédérale déclaré au TD1."""

    montant_total_TP1015_3: Decimal = Field(..., ge=Decimal("0"))
    """Montant total des crédits d'impôt QC déclaré au TP-1015.3
    (montant personnel de base + autres crédits). Non négatif."""

    montant_total_TD1: Decimal = Field(..., ge=Decimal("0"))
    """Montant total des crédits d'impôt fédéral déclaré au TD1. Non négatif."""

    retenue_additionnelle_QC: Decimal = Field(..., ge=Decimal("0"))
    """Retenue additionnelle QC demandée volontairement par l'employé.
    ``Decimal("0.00")`` par défaut ; jamais négative."""

    retenue_additionnelle_federale: Decimal = Field(..., ge=Decimal("0"))
    """Retenue additionnelle fédérale demandée volontairement par
    l'employé. ``Decimal("0.00")`` par défaut ; jamais négative."""

    # =====================================================================
    # Validateurs
    # =====================================================================

    @model_validator(mode="before")
    @classmethod
    def _rejeter_champs_sensibles(cls, data: Any) -> Any:
        """Refus fail-fast des clés apparentées à des données sensibles.

        Délégué à :func:`reject_sensitive_fields` (règle 04, Req 1.3).
        S'exécute **avant** la validation des champs typés, ce qui
        garantit qu'aucune valeur sensible ne transite dans l'instance
        même transitoirement. La ``ValueError`` levée par le validateur
        est enveloppée par Pydantic dans une ``ValidationError`` — le
        message d'origine (qui cite la règle 04) est préservé.
        """
        return reject_sensitive_fields(data)

    @field_validator(
        "taux_horaire_base",
        "taux_indemnite_vacances",
        "montant_total_TP1015_3",
        "montant_total_TD1",
        "retenue_additionnelle_QC",
        "retenue_additionnelle_federale",
        mode="before",
    )
    @classmethod
    def _rejeter_float(cls, value: Any) -> Any:
        """Refus universel de ``float`` sur les champs monétaires.

        Installé uniquement sur les champs typés ``Decimal`` (design
        §3.1) — les champs ``date``, ``bool`` et ``str`` n'ont pas de
        frontière ``float`` à protéger. Délégué à
        :func:`reject_float` (règle 01, Req 1.4, Req 10.1).
        """
        return reject_float(value)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des ``Decimal`` (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    #
    # ``when_used="json"`` cible UNIQUEMENT la sortie JSON — le
    # ``model_dump`` Python natif conserve les ``Decimal`` intacts. La
    # chaîne JSON produite par ``model_dump_json`` encode donc chaque
    # ``Decimal`` en chaîne guillemée (``"1516.32"``), condition
    # indispensable pour la contrainte (c) de Property 6 : aucune valeur
    # ``Decimal`` ne doit apparaître comme littéral flottant non guillemé
    # dans la chaîne JSON (règle 01, Req 13.4). Cette convention permet
    # le round-trip via :func:`_parse_json_reject_floats` sans passer par
    # ``float`` (Req 13.5).
    @field_serializer(
        "taux_horaire_base",
        "taux_indemnite_vacances",
        "montant_total_TP1015_3",
        "montant_total_TD1",
        "retenue_additionnelle_QC",
        "retenue_additionnelle_federale",
        when_used="json",
    )
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque champ ``Decimal`` en chaîne guillemée (règle 01)."""
        return str(v)

    @model_validator(mode="after")
    def _refuser_hors_matrice(self) -> "Employee":
        """Refus fail-fast des cas hors matrice Camp LilySO (règle 03).

        Deux gardes distinctes, dans l'ordre :

        1. Province ≠ Québec (Req 1.5, Req 11.1) — le moteur ne calcule
           que la fiscalité QC. Le message cite WebRAS et PDOC comme
           outils officiels de repli (Req 11.6, Property 16).
        2. Taux d'indemnité de vacances ∉ ``{0.04, 0.06}`` (Req 11.3)
           — le Camp LilySO n'applique que ces deux régimes de vacances.

        Discipline exception : ce validateur est en ``mode="after"`` et
        lève une :class:`UnsupportedPayrollCase` qui n'hérite pas de
        ``ValueError``. Pydantic v2 ne l'enveloppe donc pas dans
        ``ValidationError`` — elle se propage nativement au consommateur
        (Req 8.7, design §Components 2).
        """
        if self.province_travail is not Juridiction.QUEBEC:
            raise UnsupportedPayrollCase(
                f"Province de travail '{self.province_travail}' non supportée "
                "(règle 03) : le Camp LilySO opère au Québec uniquement. "
                "Pour un cas exceptionnel, utiliser WebRAS "
                "(revenuquebec.ca/webras) et PDOC (canada.ca/pdoc)."
            )
        if self.taux_indemnite_vacances not in _TAUX_VACANCES_SUPPORTES:
            raise UnsupportedPayrollCase(
                f"Taux d'indemnité de vacances {self.taux_indemnite_vacances} "
                "non supporté (Req 11.3, règle 03) : le Camp LilySO applique "
                "exclusivement 4 % (Decimal(\"0.04\")) ou 6 % "
                "(Decimal(\"0.06\")) selon l'ancienneté. Pour un cas "
                "exceptionnel, utiliser WebRAS (revenuquebec.ca/webras) "
                "et PDOC (canada.ca/pdoc)."
            )
        return self

    # =====================================================================
    # Parseur JSON personnalisé — reroute par ``_parse_json_reject_floats``
    # =====================================================================
    #
    # Surcharge de ``model_validate_json`` pour interdire tout littéral
    # flottant non guillemé dans la chaîne JSON entrante (règle 01,
    # Req 13.5). Bénéfice : même si un opérateur édite manuellement un
    # document JSON sérialisé, une chaîne comme ``"taux_horaire_base":
    # 25.50`` (littéral non guillemé) est refusée fail-fast avec un
    # message actionnable, avant même que Pydantic ne coerce vers
    # ``Decimal`` via ``float`` (ce qui aurait produit une précision
    # binaire aberrante).
    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        context: Any = None,
    ) -> "Employee":
        """Parse un :class:`Employee` depuis JSON sans passer par ``float``.

        La chaîne JSON est décodée via
        :func:`models._validators._parse_json_reject_floats`, qui refuse
        tout littéral numérique non guillemé contenant un point décimal
        ou une notation scientifique. Le dictionnaire résultant est
        ensuite passé à ``model_validate`` pour bénéficier des
        validateurs de champ standard (règle 04, règle 03, règle 01).
        """
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode("utf-8")
        donnees = _parse_json_reject_floats(json_data)
        return cls.model_validate(donnees, strict=strict, context=context)

    # =====================================================================
    # Fabrique — défauts lus depuis parameters/<annee>/*.json (Req 1.7)
    # =====================================================================

    @classmethod
    def avec_defauts_par_annee(
        cls,
        annee_reference: int,
        chemin_parametres: Path | None = None,
        **champs: Any,
    ) -> "Employee":
        """Construit un :class:`Employee` avec défauts lus depuis
        ``parameters/<annee_reference>/*.json`` (Req 1.7, design §Components 5).

        Cette fabrique est un point d'entrée ergonomique qui **substitue**
        les défauts manquants — elle ne **remplace jamais** les valeurs
        fournies par l'appelant. Un kwarg explicitement passé prévaut
        toujours sur la valeur lue dans le JSON (design §Components 5).

        Champs pour lesquels un défaut est lu via :func:`load_parameters` :

        - ``montant_total_TP1015_3`` — lu depuis
          ``parameters/<annee>/quebec.json`` →
          ``impot_quebec.montant_personnel_base`` (Req 1.7, règle 05).
        - ``montant_total_TD1`` — lu depuis
          ``parameters/<annee>/canada.json`` →
          ``impot_federal.montant_personnel_base``.
        - ``retenue_additionnelle_QC`` — lu depuis la clé
          ``td1015_3.retenue_additionnelle_defaut`` du fichier Québec.
        - ``retenue_additionnelle_federale`` — lu depuis la clé
          ``td1.retenue_additionnelle_defaut`` du fichier Canada.

        Discipline (règle 05, tâche 6.3) :

        - **Aucune valeur en dur** (18 952, 16 452, 0) n'apparaît dans
          le corps de cette méthode. Le montant personnel de base Québec,
          le montant personnel de base fédéral et les valeurs par défaut
          des retenues additionnelles sont **tous** consommés via
          :func:`load_parameters`.
        - Une valeur ``"TO_FILL"`` sur un défaut effectivement consommé
          fait lever :class:`~models.exceptions.MissingParameterError` au
          moment de l'accès à la propriété correspondante du modèle de
          paramètres (Req 8.5, Req 9.5). Ce comportement est délégué au
          chargeur — la fabrique ne l'implémente pas elle-même.

        Import différé (tâche 6.3, tâche 12.5) :

        :func:`load_parameters` réside dans ``payroll_engine`` qui
        importe déjà ``models.enums`` et ``models.exceptions``. Un import
        au niveau module créerait un cycle
        (``models.employee`` → ``payroll_engine.parameters_loader`` →
        ``models._validators`` → …). L'import à l'intérieur du corps de
        la méthode brise ce cycle : le module ``models.employee`` peut
        être importé sans forcer le chargement de ``payroll_engine``.
        L'injection optionnelle de ``chemin_parametres`` permet en outre
        aux tests de contourner le dossier ``parameters/`` réel du projet
        (test B).

        Paramètres :

        - ``annee_reference`` : année civile des paramètres fiscaux à
          lire (transmise telle quelle à :func:`load_parameters`).
        - ``chemin_parametres`` (kwarg-only) : dossier racine ``parameters/``
          à utiliser. ``None`` (défaut) délègue à la résolution
          déterministe de :func:`load_parameters` (Req 9.9). Fournir
          ``tmp_path`` dans les tests pour isoler des fixtures contrôlées.
        - ``**champs`` : tout autre champ d':class:`Employee`. Chaque
          champ présent est utilisé **tel quel** — la fabrique ne
          consulte pas le JSON pour ces champs.

        Retourne :

        - Une instance :class:`Employee` immuable (``frozen=True``)
          validée selon toutes les règles de la classe (Req 1.1–1.6).
        """
        # Import différé — voir docstring §Import différé.
        from payroll_engine.parameters_loader import load_parameters

        # Chargement paresseux par juridiction : n'ouvre le fichier Québec
        # que si un défaut Québec est effectivement requis (idem Canada).
        # Deux tests (D-TP et D-TD) fournissent l'un des deux montants
        # personnels de base en kwarg — les charger les deux serait un
        # surcoût sans valeur, et éviterait aussi la lecture d'un fichier
        # potentiellement absent lorsqu'il n'est pas nécessaire.
        _params_qc: Any = None
        _params_fed: Any = None

        def _get_params_qc() -> Any:
            nonlocal _params_qc
            if _params_qc is None:
                _params_qc = load_parameters(
                    annee_reference, Juridiction.QUEBEC, chemin_parametres
                )
            return _params_qc

        def _get_params_fed() -> Any:
            nonlocal _params_fed
            if _params_fed is None:
                _params_fed = load_parameters(
                    annee_reference, Juridiction.CANADA, chemin_parametres
                )
            return _params_fed

        # ---- Défauts Québec (TP-1015.3) ---------------------------------
        #
        # Chaque défaut n'est consommé QUE si le kwarg correspondant est
        # absent — ainsi la surcharge kwarg prévaut toujours (design
        # §Components 5, test D). L'accès à la propriété du sous-modèle
        # (``.montant_personnel_base`` etc.) lève ``MissingParameterError``
        # de manière transparente si la valeur JSON est ``"TO_FILL"``
        # (test C, règle 05, Req 8.5, Req 9.5).
        if "montant_total_TP1015_3" not in champs:
            champs["montant_total_TP1015_3"] = (
                _get_params_qc().impot_quebec.montant_personnel_base
            )

        if "retenue_additionnelle_QC" not in champs:
            # Clé documentée dans le design §Components 5 :
            # ``td1015_3.retenue_additionnelle_defaut``. Le nom d'attribut
            # côté modèle Pydantic est ``td_1015_3`` (voir
            # :class:`ParametresAnnee`). L'accès à ``retenue_additionnelle_defaut``
            # lève ``MissingParameterError`` si la valeur JSON est
            # ``"TO_FILL"`` ; il lève ``AttributeError`` si la section
            # ``td_1015_3`` est absente du fichier — situation fail-fast
            # attendue par la règle 05 (« aucun paramètre codé en dur »).
            champs["retenue_additionnelle_QC"] = (
                _get_params_qc().td_1015_3.retenue_additionnelle_defaut
            )

        # ---- Défauts fédéraux (TD1) -------------------------------------
        if "montant_total_TD1" not in champs:
            champs["montant_total_TD1"] = (
                _get_params_fed().impot_federal.montant_personnel_base
            )

        if "retenue_additionnelle_federale" not in champs:
            # Idem côté fédéral : clé ``td1.retenue_additionnelle_defaut``.
            champs["retenue_additionnelle_federale"] = (
                _get_params_fed().td1.retenue_additionnelle_defaut
            )

        # ---- Construction déléguée au constructeur classique ------------
        #
        # Toutes les validations Pydantic + les gardes règle 03 (province,
        # taux vacances) et règle 04 (champs sensibles) s'appliquent
        # normalement — la fabrique n'a AUCUN raccourci sur ces vérifications
        # (Req 1.1–1.6, Property 16).
        return cls(**champs)
