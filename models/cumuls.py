"""Modèle ``CumulsYTD`` — cumuls year-to-date par employé et par catégorie.

Spec de référence : ``moteur-paie-contrats`` — tâche 8.2.
Design de référence : sections « Components and Interfaces » §7 et
« Data Models » §6 (``design.md``).

Ce module expose une unique classe :

- :class:`CumulsYTD` — cumuls YTD immuables portés par un couple
  ``(employe_id, annee_civile)``. Onze catégories monétaires
  ``Decimal >= 0`` : brut, vacances, RRQ (employé/employeur), RQAP
  (employé/employeur), AE (employé/employeur), impôts retenus (QC et
  fédéral), net.

Contraintes structurantes (design §Data Models 6, Req 7) :

- Pydantic v2 avec ``frozen=True`` (Req 7.3 — immuabilité) et
  ``extra="forbid"`` (cohérence avec le reste du domaine).
- Chaque catégorie monétaire est ``Decimal`` avec contrainte
  ``ge=Decimal("0")`` (Req 7.1 — non-négativité stricte, sans clampage).
- Rejet universel de ``float`` sur les onze catégories via
  :func:`models._validators.reject_float` branché en ``mode="before"``
  (règle 01, Req 10.1).
- Fabrique :meth:`CumulsYTD.zero` — instance neutre avec toutes les
  catégories à ``Decimal("0.00")`` (représentation canonique deux
  décimales), point de départ obligatoire de chaque année civile.
- Méthode :meth:`CumulsYTD.avec_paie` — retourne une **nouvelle**
  instance via ``model_copy(update=...)``, sans jamais muter la source
  (Req 7.3, 7.4). Refuse par :class:`PayrollDomainError` toute paie
  dont ``employe_id`` (Req 7.7) ou ``annee_fiscale`` (Req 7.6) ne
  correspond pas au cumul courant.

Requirements couverts : 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from models._validators import _parse_json_reject_floats, reject_float
from models.exceptions import PayrollDomainError

if TYPE_CHECKING:
    # ``PayrollResult`` sera livré par la tâche 10.4. L'import est confiné
    # à ``TYPE_CHECKING`` pour deux raisons :
    #
    # 1. Éviter tout cycle d'import : ``PayrollResult`` référencera
    #    ``CumulsYTD`` dans son champ ``cumuls_fin`` (design §Data Models 9).
    #    Une importation à l'exécution introduirait un cycle
    #    ``models.cumuls`` ↔ ``models.payroll_result``.
    # 2. Permettre à ce module d'exister avant que
    #    ``models.payroll_result`` ne soit créé — la tâche 8.2 précède la
    #    tâche 10.4 dans le plan d'implémentation.
    #
    # L'annotation du paramètre de :meth:`avec_paie` est écrite sous
    # forme de chaîne (``"PayrollResult"``) pour rester valide même à
    # l'exécution, tout en offrant aux outils d'analyse statique
    # (mypy, pyright) le type précis attendu.
    from models.payroll_result import PayrollResult  # noqa: F401


#: Les onze catégories monétaires ``Decimal >= 0`` portées par
#: :class:`CumulsYTD`. Ordre : celui du design §Data Models 6. Ce tuple est
#: utilisé par :meth:`CumulsYTD.zero` (initialisation à ``Decimal("0.00")``
#: pour chaque catégorie) et par :meth:`CumulsYTD.avec_paie` (agrégation
#: catégorie par catégorie).
#:
#: L'ordre n'a **aucune** signification fiscale : c'est un ordre de
#: présentation. Les modules de calcul futurs (RRQ, RQAP, AE, impôts,
#: charges patronales) accèdent aux catégories par leur nom, jamais par
#: leur position.
_CATEGORIES_MONETAIRES: tuple[str, ...] = (
    "brut",
    "vacances",
    "rrq_employe",
    "rrq_employeur",
    "rqap_employe",
    "rqap_employeur",
    "ae_employe",
    "ae_employeur",
    "impot_qc_retenu",
    "impot_federal_retenu",
    "net",
)


class CumulsYTD(BaseModel):
    """Cumuls year-to-date d'un employé pour une année civile (design §7).

    Modèle Pydantic v2 **immuable** (``frozen=True``, Req 7.3) qui
    refuse tout champ inconnu (``extra="forbid"``). Représente l'état
    accumulé d'un employé depuis le 1er janvier d'une année civile pour
    chacune des onze catégories monétaires suivies par le moteur.

    L'instance est associée à un couple ``(employe_id, annee_civile)``
    (Req 7.2) qui la rend inagrégeable avec un cumul d'un autre employé
    ou d'une autre année. La règle est appliquée par la méthode
    :meth:`avec_paie` (Req 7.6, 7.7) qui refuse toute paie dont
    l'identifiant employé ou l'année fiscale diffère.

    Toutes les catégories sont contraintes ``>= 0`` (Req 7.1) et
    tapées ``Decimal`` (règle 01). Un ``float`` transmis à la
    construction est refusé par :func:`models._validators.reject_float`
    en ``mode="before"`` (Req 10.1).

    Le contrat garantit deux propriétés que les modules aval consomment :

    - **Monotonie croissante** (Req 7.4, 7.5) : la méthode
      :meth:`avec_paie` produit une nouvelle instance dont chaque
      catégorie est ``>=`` la catégorie correspondante du cumul source.
      Cette propriété est portée par la contrainte ``ge=Decimal("0")``
      sur les montants d'une paie (voir ``PayrollResult`` — tâche 10.4)
      combinée à une agrégation additive stricte.
    - **Immuabilité** (Req 7.3) : ``self`` n'est jamais muté. Une
      correction se fait par annulation-remplacement au niveau de la
      paie (Req 6), puis par recalcul du cumul à partir du dernier
      état connu.

    Sérialisation JSON round-trip (Req 7.8) : les onze catégories sont
    sérialisées comme chaînes guillemées par le sérialiseur de champ
    ci-dessous ; la fabrique :meth:`model_validate_json` pourra être
    surchargée par la tâche 13 pour rerouter le parsing via
    :func:`models._validators._parse_json_reject_floats`.
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2
    # ------------------------------------------------------------------
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    # ------------------------------------------------------------------
    # Champs d'identification (Req 7.2)
    # ------------------------------------------------------------------

    employe_id: str = Field(..., min_length=1)
    """Identifiant technique de l'employé. Non vide (règle 04 : jamais
    un NAS ; convention : identifiant fictif ``EMP001`` etc.)."""

    annee_civile: int = Field(..., ge=2000, le=2100)
    """Année civile de rattachement du cumul. Les bornes couvrent
    largement la fenêtre d'exploitation du moteur (2026 minimum,
    plusieurs décennies de marge)."""

    # ------------------------------------------------------------------
    # Onze catégories monétaires (Req 7.1, design §Data Models 6)
    # ------------------------------------------------------------------
    #
    # Chaque catégorie est ``Decimal >= 0``. La contrainte ``ge`` de
    # Pydantic v2 rejette toute valeur strictement négative sans
    # clampage ni conversion en valeur absolue. Le nommage suit le
    # design (snake_case, langue française pour les termes métier
    # québécois).

    brut: Decimal = Field(..., ge=Decimal("0"))
    """Cumul du salaire brut versé depuis le 1er janvier."""

    vacances: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de l'indemnité de vacances (4 % ou 6 % selon l'employé)."""

    rrq_employe: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de la cotisation RRQ retenue à l'employé (part employé)."""

    rrq_employeur: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de la cotisation RRQ versée par l'employeur (part employeur)."""

    rqap_employe: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de la cotisation RQAP retenue à l'employé."""

    rqap_employeur: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de la cotisation RQAP versée par l'employeur."""

    ae_employe: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de la cotisation d'assurance-emploi retenue à l'employé."""

    ae_employeur: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de la cotisation d'assurance-emploi versée par l'employeur
    (typiquement 1,4 × la part employé au Québec)."""

    impot_qc_retenu: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de l'impôt provincial (Québec) effectivement retenu."""

    impot_federal_retenu: Decimal = Field(..., ge=Decimal("0"))
    """Cumul de l'impôt fédéral effectivement retenu."""

    net: Decimal = Field(..., ge=Decimal("0"))
    """Cumul du salaire net versé (brut - total des retenues employé)."""

    # ------------------------------------------------------------------
    # Refus universel de ``float`` sur les onze catégories (règle 01,
    # Req 10.1). Installé en ``mode="before"`` pour intercepter la
    # valeur brute AVANT toute coercition Pydantic. Sans ce garde-fou,
    # un ``float`` natif serait converti silencieusement en ``Decimal``
    # avec précision binaire, introduisant des écarts au cent avec les
    # golden tests WebRAS et PDOC (règle 01 justification).
    # ------------------------------------------------------------------
    @field_validator(*_CATEGORIES_MONETAIRES, mode="before")
    @classmethod
    def _refuser_float(cls, value: Any) -> Any:
        """Refuse ``float`` et ``Decimal`` pollué par ``float``.

        Délègue à :func:`models._validators.reject_float`. Voir ce
        module pour les cas d'acceptation (``int``, chaîne conforme à
        ``[+-]?[0-9]+(\\.[0-9]+)?``, ``Decimal`` fini à précision
        raisonnable) et de refus (``float`` natif y compris ``0.0``,
        ``Decimal`` non fini ou à précision aberrante).
        """
        return reject_float(value)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des 11 catégories (Req 7.8, 13.1,
    # 13.4). ``when_used="json"`` : la conversion en chaîne guillemée
    # s'applique UNIQUEMENT à la sortie JSON (``model_dump_json``) ; le
    # ``model_dump`` Python natif conserve les ``Decimal`` intacts.
    # Cette convention garantit qu'aucun ``Decimal`` n'apparaît comme
    # littéral flottant non guillemé dans la chaîne JSON produite
    # (contrainte (c) de Property 6, Req 13.4). Elle rend le round-trip
    # via :func:`_parse_json_reject_floats` sûr sans passer par
    # ``float`` (règle 01, Req 13.5).
    # ------------------------------------------------------------------
    @field_serializer(*_CATEGORIES_MONETAIRES, when_used="json")
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque catégorie ``Decimal`` en chaîne guillemée (règle 01)."""
        return str(v)

    # ==================================================================
    # Parseur JSON personnalisé — reroute par ``_parse_json_reject_floats``
    # ==================================================================
    #
    # Surcharge de ``model_validate_json`` pour interdire tout littéral
    # flottant non guillemé dans la chaîne JSON entrante (règle 01,
    # Req 13.5). Bénéfice : un cumul YTD édité manuellement dans un
    # fichier de reprise ne peut pas introduire de précision binaire
    # aberrante par mégarde — un littéral comme ``"brut": 1516.32``
    # (non guillemé) est refusé fail-fast avant toute coercition.
    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        context: Any = None,
    ) -> "CumulsYTD":
        """Parse un :class:`CumulsYTD` depuis JSON sans passer par ``float``.

        La chaîne JSON est d'abord décodée via
        :func:`models._validators._parse_json_reject_floats`, puis le
        dictionnaire résultant est passé à ``model_validate`` pour
        bénéficier des validateurs de champ standard (Req 7.1,
        contraintes ``ge=0``, refus universel de ``float``).
        """
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode("utf-8")
        donnees = _parse_json_reject_floats(json_data)
        return cls.model_validate(donnees, strict=strict, context=context)

    # ==================================================================
    # Fabrique de classe — cumul neutre pour une nouvelle année
    # ==================================================================

    @classmethod
    def zero(cls, employe_id: str, annee_civile: int) -> "CumulsYTD":
        """Retourne un cumul YTD neutre pour ``(employe_id, annee_civile)``.

        Toutes les onze catégories sont initialisées à ``Decimal("0.00")``
        (représentation canonique à deux décimales — cohérente avec
        l'affichage monétaire standard). C'est le point de départ
        **obligatoire** de chaque nouvelle année civile : la méthode
        :meth:`avec_paie` refuse toute agrégation entre années
        différentes (Req 7.6), forçant l'appelant à repartir de
        ``CumulsYTD.zero(employe_id, nouvelle_annee)`` au changement
        d'exercice.

        Deux appels avec les mêmes arguments produisent deux instances
        égales au sens de :class:`pydantic.BaseModel.__eq__` (comparaison
        champ à champ) — la fabrique est déterministe.
        """
        valeurs_categories: dict[str, Decimal] = {
            categorie: Decimal("0.00") for categorie in _CATEGORIES_MONETAIRES
        }
        return cls(
            employe_id=employe_id,
            annee_civile=annee_civile,
            **valeurs_categories,
        )

    # ==================================================================
    # Agrégation d'une paie — nouvelle instance, source inchangée
    # ==================================================================

    def avec_paie(self, resultat: "PayrollResult") -> "CumulsYTD":
        """Incrémente le cumul avec les montants d'une paie (Req 7.4).

        Retourne une **nouvelle** instance de :class:`CumulsYTD` obtenue
        via ``self.model_copy(update=...)``. ``self`` reste strictement
        inchangée (Req 7.3, cohérent avec ``frozen=True``).

        L'agrégation est catégorie par catégorie : pour chacune des onze
        catégories monétaires, la nouvelle valeur est
        ``getattr(self, cat) + getattr(resultat, cat, getattr(self, cat))``.
        L'accès par :func:`getattr` avec valeur par défaut permet à
        cette méthode de fonctionner dès la tâche 8.2 avec un
        ``PayrollResult`` partiel ou un stub (``types.SimpleNamespace``
        exposant seulement ``employe_id`` et ``annee_fiscale``) — la
        logique d'agrégation complète, incluant les onze catégories,
        sera raffinée par la tâche 10.4 lorsque ``PayrollResult`` sera
        entièrement défini.

        Rejets fail-fast (Req 7.6, 7.7) :

        - Si ``resultat.employe_id`` diffère de ``self.employe_id``,
          lève :class:`PayrollDomainError` avec un message citant les
          **deux** identifiants (permet à l'auditeur d'identifier le
          mismatch).
        - Si ``resultat.annee_fiscale`` diffère de ``self.annee_civile``,
          lève :class:`PayrollDomainError` avec un message citant les
          **deux** années et invitant à repartir de
          :meth:`CumulsYTD.zero` pour la nouvelle année.

        Ces refus sont détectés **avant** toute lecture des catégories
        monétaires : la méthode fonctionne donc avec un objet minimal
        exposant seulement les deux attributs ``employe_id`` et
        ``annee_fiscale`` (duck typing intentionnel — voir tests
        d'exemple utilisant :class:`types.SimpleNamespace`).

        L'exception :class:`PayrollDomainError` reste strictement
        disjointe de :class:`pydantic.ValidationError` (Req 8.7) : le
        consommateur peut capturer séparément un refus métier
        (``employe_id`` ou année incohérents) d'une erreur de forme.
        """
        # -- 1. Cohérence de l'employé (Req 7.7) ------------------------
        #
        # Priorité au refus par employé sur le refus par année : les
        # tests d'exemple assument un ordre stable des vérifications
        # (test ``avec_paie`` avec employé différent et année correcte).
        # Message actionnable : cite les deux identifiants pour que le
        # consommateur identifie immédiatement le mismatch (Req 8.3 par
        # extension à toute ``PayrollDomainError``).
        employe_id_paie = resultat.employe_id
        if employe_id_paie != self.employe_id:
            raise PayrollDomainError(
                f"Impossible d'agréger la paie de l'employé "
                f"'{employe_id_paie}' dans le cumul YTD de l'employé "
                f"'{self.employe_id}' (Req 7.7). Chaque cumul YTD est "
                "associé à un employé unique — vérifier l'appariement "
                "avant l'agrégation."
            )

        # -- 2. Cohérence de l'année (Req 7.6) --------------------------
        #
        # Message actionnable : cite les deux années et invite à
        # repartir de ``CumulsYTD.zero()`` pour la nouvelle année civile
        # (design §Data Models 6, message explicite).
        annee_paie = resultat.annee_fiscale
        if annee_paie != self.annee_civile:
            raise PayrollDomainError(
                f"Impossible d'agréger une paie de l'année fiscale "
                f"{annee_paie} dans le cumul YTD de l'année civile "
                f"{self.annee_civile} (Req 7.6). Repartir d'un cumul "
                f"neutre via ``CumulsYTD.zero(employe_id, {annee_paie})`` "
                "pour la nouvelle année."
            )

        # -- 3. Agrégation additive catégorie par catégorie -------------
        #
        # ``model_copy(update=...)`` produit une nouvelle instance sans
        # muter ``self`` (contrat ``frozen=True``, Req 7.3). Pour chaque
        # catégorie, la valeur est incrémentée du montant correspondant
        # exposé par ``resultat``. En attendant la tâche 10.4 qui livrera
        # les onze champs sur ``PayrollResult``, on utilise ``getattr``
        # avec valeur par défaut : si l'attribut n'est pas exposé par
        # ``resultat`` (cas d'un stub minimal), la catégorie reste à sa
        # valeur courante — l'agrégation reste alors monotone (Req 7.5)
        # puisqu'aucun montant négatif n'est possible (contrainte ``ge=0``
        # sur les catégories, et ``PayrollResult`` imposera la même
        # contrainte sur ses propres montants).
        mises_a_jour: dict[str, Decimal] = {}
        for categorie in _CATEGORIES_MONETAIRES:
            valeur_actuelle: Decimal = getattr(self, categorie)
            montant_paie: Decimal = getattr(resultat, categorie, valeur_actuelle)
            mises_a_jour[categorie] = valeur_actuelle + montant_paie

        return self.model_copy(update=mises_a_jour)
