"""Chargeur de paramètres fiscaux versionnés — moteur de paie Camp LilySO.

Spec de référence : ``moteur-paie-contrats`` — tâche 12.2.
Design de référence : ``design.md`` §Components 10 et §Data Models 9.

Ce module expose :

- :data:`SENTINEL_TO_FILL` : la sentinelle ``"TO_FILL"`` utilisée dans les
  fichiers ``parameters/<AAAA>/*.json`` pour indiquer un paramètre non
  encore renseigné (règle 05).
- Les 13 sous-modèles typés des sections de paramètres (Pydantic v2,
  ``frozen=True``, ``extra="allow"``) : :class:`FrequencePaieParametres`,
  :class:`RRQParametres`, :class:`RQAPParametres`, :class:`AEParametres`,
  :class:`ImpotQCParametres`, :class:`ImpotFederalParametres`,
  :class:`TD1015_3Parametres`, :class:`TD1Parametres`,
  :class:`FSSParametres`, :class:`CNESSTParametres`, :class:`CNTParametres`,
  :class:`VacancesParametres`, :class:`HeuresSupplementairesParametres`.
- La racine :class:`ParametresAnnee` qui agrège les sections optionnelles
  selon la juridiction (Québec vs Canada).
- :func:`load_parameters` : point d'entrée unique de lecture des fichiers
  ``parameters/<AAAA>/{quebec,canada}.json``. *Cette fonction est
  actuellement un stub (Task 12.2 implémente seulement les modèles) ; la
  Task 12.3 fournira l'implémentation complète.*

Discipline
----------

- **Règle 01** : aucun ``float`` dans le domaine paie. Les champs
  ``Decimal`` acceptent ``Decimal`` ou une chaîne numérique convertible
  ``Decimal(str)`` — jamais un ``float`` — ou la sentinelle
  ``"TO_FILL"`` qui reste un ``str`` jusqu'à matérialisation.
- **Règle 02** : chaque ``MissingParameterError`` levée à la
  matérialisation cite le chemin JSON du paramètre, l'année, la
  juridiction et le fichier à mettre à jour (voir
  :meth:`_ParametresSectionBase._materialiser`).
- **Règle 05** : aucun taux/plafond/exemption codé en dur ; tous les
  paramètres sont stockés dans les fichiers JSON versionnés par année.
- **Règle 06** : ce module est écrit après ses tests
  (``tests/payroll_engine/test_parameters_loader.py``) — les tests
  d'accès à un ``"TO_FILL"`` restent rouges tant que Task 12.3 n'a pas
  câblé ``load_parameters`` pour propager le contexte aux sections.

Design du chargement différé (Req 9.7, Req 9.11)
------------------------------------------------

Chaque sous-modèle stocke ses valeurs brutes sous des champs suffixés
``_brut`` typés ``Decimal | Literal["TO_FILL"]``. Un ``field_validator``
en ``mode="before"`` convertit les chaînes numériques en ``Decimal``
(via ``Decimal(str)``, jamais via ``float``) et laisse ``"TO_FILL"``
intact.

Chaque valeur brute est exposée via une ``@property`` du nom du champ
JSON (sans suffixe). L'accès à la propriété :

- retourne le ``Decimal`` si la valeur a été renseignée ;
- lève :class:`~models.exceptions.MissingParameterError` avec un message
  actionnable si la valeur est ``"TO_FILL"``.

Ce mécanisme respecte Req 9.5 (« lever ``MissingParameterError`` au
premier accès à un paramètre non renseigné ») **sans** empêcher le
chargement des sections qui contiennent des ``"TO_FILL"`` non consommés
(Req 9.11). Le contexte du message (année, juridiction, fichier) est
propagé de :class:`ParametresAnnee` vers chaque section via des
``PrivateAttr`` positionnés par :meth:`ParametresAnnee._propager_contexte`.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from models._validators import _parse_json_reject_floats, reject_float
from models.enums import Juridiction
from models.exceptions import MissingParameterError


# ---------------------------------------------------------------------------
# Sentinelle et helpers de validation
# ---------------------------------------------------------------------------

#: Sentinelle utilisée dans les fichiers ``parameters/<AAAA>/*.json`` pour
#: marquer un paramètre fiscal encore inconnu (règle 05). Sa présence sur
#: un champ ``Decimal`` fait lever :class:`MissingParameterError` à la
#: **matérialisation** (accès par la propriété du champ), pas au
#: chargement (Req 9.11 : les sections partiellement ``"TO_FILL"`` doivent
#: rester chargeables tant qu'aucun champ manquant n'est consommé).
SENTINEL_TO_FILL: Final[str] = "TO_FILL"


#: Type des champs bruts stockés par les sous-modèles de paramètres.
#: Une valeur est soit un ``Decimal`` (après conversion depuis la chaîne
#: numérique du JSON), soit la sentinelle ``"TO_FILL"`` littérale.
ValeurBrute = Decimal | Literal["TO_FILL"]


def _valider_decimal_ou_to_fill(v: Any) -> Any:
    """Validateur ``mode="before"`` pour les champs :data:`ValeurBrute`.

    Chaîne de responsabilités (ordre important) :

    1. **Sentinelle d'abord.** Si la valeur est la chaîne littérale
       ``"TO_FILL"``, elle est préservée telle quelle. Ce court-circuit
       précède ``reject_float`` car ce dernier applique une regex stricte
       ``^[+-]?[0-9]+(\\.[0-9]+)?$`` sur les chaînes et refuserait
       ``"TO_FILL"``. La matérialisation vers :class:`Decimal` est
       différée à l'accès de la propriété correspondante (Req 9.11).
    2. **Rejet des ``float``.** Toute autre valeur est passée à
       :func:`~models._validators.reject_float` qui refuse les ``float``
       natifs (règle 01) et les ``Decimal`` de précision aberrante
       (typiques d'une construction depuis ``float``, Req 10.4).
    3. **Conversion string → Decimal.** Une chaîne numérique valide (par
       exemple ``"0.063"`` ou ``"3500.00"``) est convertie en
       :class:`Decimal` via ``Decimal(str)`` — la seule forme de
       conversion autorisée par la règle 01. La chaîne passe préalablement
       par la regex de :func:`reject_float`, qui rejette la notation
       scientifique et la virgule francophone.
    4. **Autres types.** ``Decimal``, ``int`` (et ``bool`` par héritage)
       sont retournés tels quels et validés par Pydantic selon le typage
       annoté du champ.

    Ce validateur est appliqué en ``mode="before"`` sur chaque champ
    ``*_brut`` des sous-modèles. Il est délibérément séparé de la
    propriété de matérialisation pour respecter la séparation des
    responsabilités : ce validateur gère la **coercition** (JSON →
    ``Decimal``), la propriété gère la **matérialisation** (fail-fast
    sur ``"TO_FILL"``).
    """
    # Étape 1 — Sentinelle prioritaire. Doit être testée AVANT
    # ``reject_float`` car ce dernier applique une regex qui rejette
    # toute chaîne non-numérique, y compris ``"TO_FILL"``.
    if isinstance(v, str) and v == SENTINEL_TO_FILL:
        return v

    # Étape 2 — Rejet des ``float`` et des chaînes non numériques
    # (règle 01, Req 10.1, 10.4). ``reject_float`` renvoie la valeur
    # inchangée si elle est acceptable (``Decimal`` fini, chaîne
    # décimale, ``int``) et lève ``ValueError`` sinon.
    v = reject_float(v)

    # Étape 3 — Conversion string → ``Decimal``. La regex de
    # ``reject_float`` a déjà validé le format ; la construction
    # ``Decimal(str)`` ne passe donc jamais par ``float``.
    if isinstance(v, str):
        try:
            return Decimal(v)
        except (ValueError, ArithmeticError):
            # Chaîne rejetée par ``Decimal`` malgré la regex : cas très
            # improbable (regex plus permissive que ``Decimal`` sur
            # certains bords). Laisser Pydantic produire le message
            # d'erreur contextualisé sur le champ concerné.
            return v

    return v


# ---------------------------------------------------------------------------
# Base commune aux sous-modèles de paramètres
# ---------------------------------------------------------------------------


class _ParametresSectionBase(BaseModel):
    """Base commune aux 13 sous-modèles de sections de paramètres.

    Configuration Pydantic v2 :

    - ``frozen=True`` : immuabilité après construction (règle 06 —
      « immuabilité historique ») ;
    - ``extra="allow"`` : les fichiers ``parameters/<AAAA>/*.json``
      contiennent régulièrement des clés d'audit (``commentaire``,
      ``statut``, ``statut_taux``, ``statut_plafonds``, ``notes``,
      etc.) qui documentent l'origine et l'état de validation d'une
      valeur. Cette permissivité est acceptable ici car les fichiers
      sont sous notre contrôle (règle 05), contrairement aux modèles
      du domaine (``Employee``, ``PayrollInput``) où ``extra="forbid"``
      reste obligatoire ;
    - ``populate_by_name=True`` : permet de construire une section
      avec le **nom du champ Python** (``taux_cotisation_totale_employe_brut``)
      OU son **alias JSON** (``taux_cotisation_totale_employe``). Cela
      garantit que le round-trip ``model_validate(model_dump()) == m``
      fonctionne dans les deux directions.

    Contexte pour :class:`~models.exceptions.MissingParameterError` :
    quatre :class:`PrivateAttr` portent l'année, la juridiction, le
    chemin du fichier et le nom de la section. Ces attributs sont
    positionnés par :meth:`ParametresAnnee._propager_contexte` après
    la construction de l'agrégat racine. Ils **ne** sont **pas** lus
    depuis le JSON : ce sont des métadonnées d'exécution, pas des
    paramètres fiscaux.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    # -- Contexte pour les messages MissingParameterError -----------------
    #
    # Ces PrivateAttr sont écrits par ParametresAnnee._propager_contexte
    # après la construction du modèle racine. Les valeurs par défaut
    # (``0``, ``""``) permettent de construire une section isolément
    # dans les tests unitaires sans avoir à instancier tout l'agrégat.
    # Sur un modèle ``frozen=True``, Pydantic v2 autorise l'écriture
    # d'un PrivateAttr via ``__setattr__`` (les private attrs sont
    # explicitement exclus du verrou ``frozen``).

    _contexte_annee: int = PrivateAttr(default=0)
    _contexte_juridiction: str = PrivateAttr(default="")
    _contexte_fichier: str = PrivateAttr(default="")
    _contexte_section: str = PrivateAttr(default="")

    def _materialiser(self, nom_champ: str, valeur: ValeurBrute) -> Decimal:
        """Retourne le :class:`Decimal` ou lève :class:`MissingParameterError`.

        Paramètres :

        - ``nom_champ`` : nom du champ dans la section (ex.
          ``"maximum_gains_admissibles_mga"``). Utilisé pour construire
          le chemin JSON dans le message d'erreur (ex.
          ``"rrq.maximum_gains_admissibles_mga"``).
        - ``valeur`` : la valeur brute stockée par le champ ``*_brut``
          correspondant. Soit un ``Decimal`` (déjà converti par le
          field_validator), soit la sentinelle ``"TO_FILL"``.

        Comportement :

        - Si la valeur est un ``Decimal``, elle est retournée telle
          quelle.
        - Si la valeur est ``"TO_FILL"``, :class:`MissingParameterError`
          est levée avec un message qui contient (Req 8.6, Req 9.5,
          Property 16) :

          * le **chemin JSON** complet (``<section>.<champ>``) ;
          * l'**année** et la **juridiction** courantes ;
          * le **fichier de paramètres** à mettre à jour ;
          * la **source officielle** à consulter (TP-1015.F pour QC,
            T4127 pour le fédéral).

        - Tout autre type est un bug de conversion : lever
          :class:`TypeError` pour aider le développeur à diagnostiquer.
        """
        if isinstance(valeur, Decimal):
            return valeur

        if valeur == SENTINEL_TO_FILL:
            chemin_complet = (
                f"{self._contexte_section}.{nom_champ}"
                if self._contexte_section
                else nom_champ
            )
            fichier = (
                self._contexte_fichier
                or f"parameters/{self._contexte_annee}/{self._contexte_juridiction}.json"
            )
            source_officielle = (
                f"TP-1015.F {self._contexte_annee}"
                if self._contexte_juridiction == Juridiction.QUEBEC.value
                else f"T4127 {self._contexte_annee}"
            )
            raise MissingParameterError(
                f"Paramètre '{chemin_complet}' non renseigné (sentinelle "
                f"'TO_FILL') pour l'année {self._contexte_annee}, "
                f"juridiction '{self._contexte_juridiction}'. "
                f"Fichier à mettre à jour : {fichier}. "
                f"Consulter la source officielle {source_officielle} et "
                f"remplacer 'TO_FILL' par la valeur numérique en chaîne "
                f"de caractères (ex. \"0.063\")."
            )

        # Tout autre type est inattendu : le field_validator aurait dû
        # normaliser en Decimal ou en "TO_FILL". Un chemin ici indique
        # un bug de conversion, pas un cas métier — lever TypeError.
        raise TypeError(
            f"Type inattendu pour le paramètre '{nom_champ}' : "
            f"{type(valeur).__name__} (attendu Decimal ou 'TO_FILL'). "
            "Ceci indique un bug de conversion — signaler l'incident."
        )


# ---------------------------------------------------------------------------
# Sous-modèles typés des sections de paramètres
# ---------------------------------------------------------------------------
#
# Chaque sous-modèle applique le patron :
#
# 1. Un champ ``<nom>_brut : ValeurBrute`` avec ``Field(alias="<nom>")`` :
#    Pydantic reçoit la clé JSON telle quelle (``"taux_..."``) et la stocke
#    dans l'attribut Python ``<nom>_brut``. ``populate_by_name=True`` (défini
#    sur la base) autorise également la construction directe via l'attribut
#    Python dans les tests unitaires.
# 2. Un ``field_validator("<nom>_brut", mode="before")`` qui délègue à
#    :func:`_valider_decimal_ou_to_fill` : refus des ``float`` (règle 01)
#    et coercition string → ``Decimal`` sans passer par ``float``.
# 3. Une ``@property <nom>`` qui appelle
#    ``self._materialiser("<nom>", self.<nom>_brut)`` : retourne le
#    :class:`Decimal` ou lève :class:`MissingParameterError` avec un
#    message actionnable (Req 9.5, Property 16).
#
# Les champs non-numériques (``statut``, ``commentaire``, etc.) sont
# absorbés par ``extra="allow"`` et restent accessibles via
# ``model_extra`` — nous ne les typons pas explicitement pour ne pas
# alourdir chaque sous-modèle avec des méta-données d'audit.


class FrequencePaieParametres(_ParametresSectionBase):
    """Nombre de périodes de paie annuelles (Req 2.7, design §Components 10).

    ``nb_periodes_annuelles`` est un :class:`int` (pas un ``Decimal``) : ce
    n'est **pas** un paramètre fiscal au sens de la règle 05 mais un
    élément de calendrier. Il est directement typé sans suffixe ``_brut``
    et sans matérialisation différée.

    ``source_effective`` est une métadonnée d'audit renseignée par le
    chargeur (Task 12.4) selon le mécanisme de repli :

    - ``"annee_courante"`` : lu dans ``parameters/<annee>/*.json`` ;
    - ``"repli_annee_<AAAA>"`` : lu dans le fichier de l'année précédente ;
    - ``"valeur_par_defaut"`` : aucun fichier disponible, valeur ``26``.

    Le défaut ``"annee_courante"`` permet aux tests qui construisent
    directement une section (sans passer par ``load_parameters``) de ne
    pas avoir à fournir ce champ.
    """

    nb_periodes_annuelles: int = Field(..., ge=1, le=53)
    statut: str = ""
    commentaire: str = ""
    source_effective: str = "annee_courante"


class RRQParametres(_ParametresSectionBase):
    """Régime de rentes du Québec — TP-1015.F 2026, section RRQ.

    Contient :

    - les taux de cotisation totale (base + première supplémentaire) employé
      et employeur ;
    - les taux de la deuxième cotisation supplémentaire (RRQ2) — hors
      périmètre Camp LilySO en pratique mais typés pour cohérence ;
    - l'exemption générale annuelle et son équivalent aux deux semaines ;
    - les plafonds annuels : MGA, MSGA, cotisation maximale employé.

    La clé ``portion_supplementaire_deductible_fed`` (dictionnaire imbriqué
    utilisé par le module ``impot-federal``) est absorbée par
    ``extra="allow"`` — nous ne la typons pas ici car elle n'est pas un
    ``Decimal`` scalaire.
    """

    taux_cotisation_totale_employe_brut: ValeurBrute = Field(
        ..., alias="taux_cotisation_totale_employe"
    )
    taux_cotisation_totale_employeur_brut: ValeurBrute = Field(
        ..., alias="taux_cotisation_totale_employeur"
    )
    taux_deuxieme_cotisation_supplementaire_employe_brut: ValeurBrute = Field(
        ..., alias="taux_deuxieme_cotisation_supplementaire_employe"
    )
    taux_deuxieme_cotisation_supplementaire_employeur_brut: ValeurBrute = Field(
        ..., alias="taux_deuxieme_cotisation_supplementaire_employeur"
    )
    exemption_generale_annuelle_brut: ValeurBrute = Field(
        ..., alias="exemption_generale_annuelle"
    )
    exemption_par_periode_aux_deux_semaines_2026_brut: ValeurBrute = Field(
        ..., alias="exemption_par_periode_aux_deux_semaines_2026"
    )
    maximum_gains_admissibles_mga_brut: ValeurBrute = Field(
        ..., alias="maximum_gains_admissibles_mga"
    )
    maximum_supplementaire_gains_admissibles_msga_brut: ValeurBrute = Field(
        ..., alias="maximum_supplementaire_gains_admissibles_msga"
    )
    cotisation_max_annuelle_employe_brut: ValeurBrute = Field(
        ..., alias="cotisation_max_annuelle_employe"
    )

    @field_validator(
        "taux_cotisation_totale_employe_brut",
        "taux_cotisation_totale_employeur_brut",
        "taux_deuxieme_cotisation_supplementaire_employe_brut",
        "taux_deuxieme_cotisation_supplementaire_employeur_brut",
        "exemption_generale_annuelle_brut",
        "exemption_par_periode_aux_deux_semaines_2026_brut",
        "maximum_gains_admissibles_mga_brut",
        "maximum_supplementaire_gains_admissibles_msga_brut",
        "cotisation_max_annuelle_employe_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux_cotisation_totale_employe(self) -> Decimal:
        return self._materialiser(
            "taux_cotisation_totale_employe",
            self.taux_cotisation_totale_employe_brut,
        )

    @property
    def taux_cotisation_totale_employeur(self) -> Decimal:
        return self._materialiser(
            "taux_cotisation_totale_employeur",
            self.taux_cotisation_totale_employeur_brut,
        )

    @property
    def taux_deuxieme_cotisation_supplementaire_employe(self) -> Decimal:
        return self._materialiser(
            "taux_deuxieme_cotisation_supplementaire_employe",
            self.taux_deuxieme_cotisation_supplementaire_employe_brut,
        )

    @property
    def taux_deuxieme_cotisation_supplementaire_employeur(self) -> Decimal:
        return self._materialiser(
            "taux_deuxieme_cotisation_supplementaire_employeur",
            self.taux_deuxieme_cotisation_supplementaire_employeur_brut,
        )

    @property
    def exemption_generale_annuelle(self) -> Decimal:
        return self._materialiser(
            "exemption_generale_annuelle",
            self.exemption_generale_annuelle_brut,
        )

    @property
    def exemption_par_periode_aux_deux_semaines_2026(self) -> Decimal:
        return self._materialiser(
            "exemption_par_periode_aux_deux_semaines_2026",
            self.exemption_par_periode_aux_deux_semaines_2026_brut,
        )

    @property
    def maximum_gains_admissibles_mga(self) -> Decimal:
        return self._materialiser(
            "maximum_gains_admissibles_mga",
            self.maximum_gains_admissibles_mga_brut,
        )

    @property
    def maximum_supplementaire_gains_admissibles_msga(self) -> Decimal:
        return self._materialiser(
            "maximum_supplementaire_gains_admissibles_msga",
            self.maximum_supplementaire_gains_admissibles_msga_brut,
        )

    @property
    def cotisation_max_annuelle_employe(self) -> Decimal:
        return self._materialiser(
            "cotisation_max_annuelle_employe",
            self.cotisation_max_annuelle_employe_brut,
        )


class RQAPParametres(_ParametresSectionBase):
    """Régime québécois d'assurance parentale — TP-1015.F 2026, section RQAP.

    Taux employé et employeur distincts, plafonds annuels de gains et de
    cotisation.
    """

    taux_employe_brut: ValeurBrute = Field(..., alias="taux_employe")
    taux_employeur_brut: ValeurBrute = Field(..., alias="taux_employeur")
    maximum_gains_assurables_brut: ValeurBrute = Field(
        ..., alias="maximum_gains_assurables"
    )
    cotisation_max_employe_brut: ValeurBrute = Field(..., alias="cotisation_max_employe")
    cotisation_max_employeur_brut: ValeurBrute = Field(
        ..., alias="cotisation_max_employeur"
    )

    @field_validator(
        "taux_employe_brut",
        "taux_employeur_brut",
        "maximum_gains_assurables_brut",
        "cotisation_max_employe_brut",
        "cotisation_max_employeur_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux_employe(self) -> Decimal:
        return self._materialiser("taux_employe", self.taux_employe_brut)

    @property
    def taux_employeur(self) -> Decimal:
        return self._materialiser("taux_employeur", self.taux_employeur_brut)

    @property
    def maximum_gains_assurables(self) -> Decimal:
        return self._materialiser(
            "maximum_gains_assurables", self.maximum_gains_assurables_brut
        )

    @property
    def cotisation_max_employe(self) -> Decimal:
        return self._materialiser(
            "cotisation_max_employe", self.cotisation_max_employe_brut
        )

    @property
    def cotisation_max_employeur(self) -> Decimal:
        return self._materialiser(
            "cotisation_max_employeur", self.cotisation_max_employeur_brut
        )


class AEParametres(_ParametresSectionBase):
    """Assurance-emploi — T4127 2026, taux applicable aux résidents du Québec.

    Le multiplicateur employeur standard est ``1.4`` (aucune réduction pour
    Camp LilySO, cf. commentaire du fichier ``canada.json``). ``province_taux``
    et ``reduction_taux_employeur`` sont des chaînes documentaires.
    """

    province_taux: str = ""
    reduction_taux_employeur: str = ""
    taux_employe_quebec_brut: ValeurBrute = Field(..., alias="taux_employe_quebec")
    multiplicateur_employeur_brut: ValeurBrute = Field(
        ..., alias="multiplicateur_employeur"
    )
    maximum_gains_assurables_brut: ValeurBrute = Field(
        ..., alias="maximum_gains_assurables"
    )
    cotisation_max_employe_brut: ValeurBrute = Field(..., alias="cotisation_max_employe")
    cotisation_max_employeur_brut: ValeurBrute = Field(
        ..., alias="cotisation_max_employeur"
    )

    @field_validator(
        "taux_employe_quebec_brut",
        "multiplicateur_employeur_brut",
        "maximum_gains_assurables_brut",
        "cotisation_max_employe_brut",
        "cotisation_max_employeur_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux_employe_quebec(self) -> Decimal:
        return self._materialiser("taux_employe_quebec", self.taux_employe_quebec_brut)

    @property
    def multiplicateur_employeur(self) -> Decimal:
        return self._materialiser(
            "multiplicateur_employeur", self.multiplicateur_employeur_brut
        )

    @property
    def maximum_gains_assurables(self) -> Decimal:
        return self._materialiser(
            "maximum_gains_assurables", self.maximum_gains_assurables_brut
        )

    @property
    def cotisation_max_employe(self) -> Decimal:
        return self._materialiser(
            "cotisation_max_employe", self.cotisation_max_employe_brut
        )

    @property
    def cotisation_max_employeur(self) -> Decimal:
        return self._materialiser(
            "cotisation_max_employeur", self.cotisation_max_employeur_brut
        )



class ImpotQCParametres(_ParametresSectionBase):
    """Impôt du Québec — TP-1015.F 2026, section impôt.

    Le seul champ scalaire ``Decimal`` typé ici est le montant personnel de
    base. Les structures complexes (``paliers``, ``taux_credits_convertibles``,
    ``regles_arrondissement``, ``deduction_pour_travailleur_annuelle``) sont
    absorbées par ``extra="allow"`` : elles seront typées finement dans une
    spec dédiée au module ``impot-quebec`` où elles seront réellement
    consommées.
    """

    montant_personnel_base_brut: ValeurBrute = Field(
        ..., alias="montant_personnel_base"
    )

    @field_validator("montant_personnel_base_brut", mode="before")
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def montant_personnel_base(self) -> Decimal:
        return self._materialiser(
            "montant_personnel_base", self.montant_personnel_base_brut
        )


class ImpotFederalParametres(_ParametresSectionBase):
    """Impôt fédéral — T4127 2026.

    Comme pour ``ImpotQCParametres``, les structures complexes (paliers,
    règles d'arrondissement, déduction RRQ supplémentaire imbriquée) sont
    laissées en ``extra="allow"`` et seront typées par la spec
    ``impot-federal``.
    """

    montant_personnel_base_brut: ValeurBrute = Field(
        ..., alias="montant_personnel_base"
    )
    montant_emploi_canadien_annuel_brut: ValeurBrute = Field(
        default=SENTINEL_TO_FILL, alias="montant_emploi_canadien_annuel"
    )

    @field_validator(
        "montant_personnel_base_brut",
        "montant_emploi_canadien_annuel_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def montant_personnel_base(self) -> Decimal:
        return self._materialiser(
            "montant_personnel_base", self.montant_personnel_base_brut
        )

    @property
    def montant_emploi_canadien_annuel(self) -> Decimal:
        return self._materialiser(
            "montant_emploi_canadien_annuel",
            self.montant_emploi_canadien_annuel_brut,
        )


class TD1015_3Parametres(_ParametresSectionBase):
    """TP-1015.3 — Déclaration pour la retenue d'impôt du Québec.

    Section correspondant au formulaire employé (montant total, retenue
    additionnelle). Le sous-modèle est déclaré ici pour héberger les
    valeurs par défaut annuelles consommées par la fabrique
    :meth:`~models.employee.Employee.avec_defauts_par_annee` (Req 1.7,
    task 12.5).

    Champs scalaires :

    - ``montant_total_defaut_brut`` — placeholder pour un futur défaut
      annuel du montant total TP-1015.3. Peut rester ``"TO_FILL"`` tant
      qu'aucun scénario ne le consomme (Req 9.11).
    - ``retenue_additionnelle_defaut_brut`` — valeur par défaut de la
      retenue additionnelle QC demandée volontairement par l'employé.
      Consommée par la fabrique :meth:`Employee.avec_defauts_par_annee`
      lorsque le kwarg ``retenue_additionnelle_QC`` n'est pas fourni
      (Req 1.7). La règle 05 impose que la valeur ``"0.00"`` soit portée
      par le JSON versionné, pas par le code Python — un ``default=SENTINEL_TO_FILL``
      garantit qu'une omission dans le JSON échoue au premier accès avec
      un :class:`~models.exceptions.MissingParameterError` actionnable.
    """

    montant_total_defaut_brut: ValeurBrute = Field(
        default=SENTINEL_TO_FILL, alias="montant_total_defaut"
    )
    retenue_additionnelle_defaut_brut: ValeurBrute = Field(
        default=SENTINEL_TO_FILL, alias="retenue_additionnelle_defaut"
    )

    @field_validator(
        "montant_total_defaut_brut",
        "retenue_additionnelle_defaut_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def montant_total_defaut(self) -> Decimal:
        return self._materialiser(
            "montant_total_defaut", self.montant_total_defaut_brut
        )

    @property
    def retenue_additionnelle_defaut(self) -> Decimal:
        return self._materialiser(
            "retenue_additionnelle_defaut",
            self.retenue_additionnelle_defaut_brut,
        )


class TD1Parametres(_ParametresSectionBase):
    """TD1 fédéral — paramètres personnels.

    ``montant_base_2026`` correspond au montant personnel de base fédéral.
    ``retenue_additionnelle_defaut`` est la valeur par défaut de la
    retenue additionnelle fédérale demandée volontairement par l'employé.
    Elle est consommée par la fabrique
    :meth:`~models.employee.Employee.avec_defauts_par_annee` lorsque le
    kwarg ``retenue_additionnelle_federale`` n'est pas fourni (Req 1.7,
    task 12.5). Comme pour la clé QC symétrique, la règle 05 impose que
    ``"0.00"`` soit porté par le JSON — un ``default=SENTINEL_TO_FILL``
    garantit qu'une omission dans le JSON échoue au premier accès avec
    un :class:`~models.exceptions.MissingParameterError` actionnable.

    Les drapeaux booléens documentent la prise en charge du moteur
    (exonération / retenue additionnelle) et ne sont ni des taux ni des
    plafonds — ils sont typés directement.
    """

    montant_base_2026_brut: ValeurBrute = Field(..., alias="montant_base_2026")
    retenue_additionnelle_defaut_brut: ValeurBrute = Field(
        default=SENTINEL_TO_FILL, alias="retenue_additionnelle_defaut"
    )
    exoneration_supportee_par_moteur: bool = True
    exoneration_mecanisme: str = ""
    retenue_additionnelle_supportee: bool = True

    @field_validator(
        "montant_base_2026_brut",
        "retenue_additionnelle_defaut_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def montant_base_2026(self) -> Decimal:
        return self._materialiser("montant_base_2026", self.montant_base_2026_brut)

    @property
    def retenue_additionnelle_defaut(self) -> Decimal:
        return self._materialiser(
            "retenue_additionnelle_defaut",
            self.retenue_additionnelle_defaut_brut,
        )


class FSSParametres(_ParametresSectionBase):
    """Fonds des services de santé — TP-1015.F 2026.

    Le taux dépend de la masse salariale annuelle de l'employeur. Pour
    Camp LilySO en 2026, WebRAS applique 1,65 % (voir ``quebec.json``).
    La table complète ``table_taux_par_masse_salariale`` reste absorbée
    par ``extra="allow"`` (structure de type table à typer dans une spec
    ``charges-patronales`` dédiée).
    """

    taux_camp_lilyso_2026_brut: ValeurBrute = Field(
        ..., alias="taux_camp_lilyso_2026"
    )
    masse_salariale_utilisee_webras_2026_brut: ValeurBrute = Field(
        default=SENTINEL_TO_FILL, alias="masse_salariale_utilisee_webras_2026"
    )

    @field_validator(
        "taux_camp_lilyso_2026_brut",
        "masse_salariale_utilisee_webras_2026_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux_camp_lilyso_2026(self) -> Decimal:
        return self._materialiser(
            "taux_camp_lilyso_2026", self.taux_camp_lilyso_2026_brut
        )

    @property
    def masse_salariale_utilisee_webras_2026(self) -> Decimal:
        return self._materialiser(
            "masse_salariale_utilisee_webras_2026",
            self.masse_salariale_utilisee_webras_2026_brut,
        )


class CNESSTParametres(_ParametresSectionBase):
    """CNESST — classification et taux confirmés par l'employeur.

    ``unite`` (numéro à 5 chiffres) est une chaîne. ``en_attente_classification``
    est un drapeau utilisé par le module ``charges-patronales`` pour lever
    un avertissement si la classification n'est pas confirmée.
    """

    unite: str = ""
    en_attente_classification: bool = False
    taux_cni_brut: ValeurBrute = Field(..., alias="taux_cni")
    taux_unite_brut: ValeurBrute = Field(..., alias="taux_unite")
    taux_total_brut: ValeurBrute = Field(..., alias="taux_total")

    @field_validator(
        "taux_cni_brut",
        "taux_unite_brut",
        "taux_total_brut",
        mode="before",
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux_cni(self) -> Decimal:
        return self._materialiser("taux_cni", self.taux_cni_brut)

    @property
    def taux_unite(self) -> Decimal:
        return self._materialiser("taux_unite", self.taux_unite_brut)

    @property
    def taux_total(self) -> Decimal:
        return self._materialiser("taux_total", self.taux_total_brut)


class CNTParametres(_ParametresSectionBase):
    """Cotisation Normes du travail — TP-1015.F 2026, section CNT.

    Charge annuelle (n'apparaît pas paie par paie dans WebRAS). Les deux
    champs sont typiquement ``"TO_FILL"`` tant que la spec
    ``charges-patronales`` n'a pas confirmé leur formulation exacte.
    """

    taux_brut: ValeurBrute = Field(default=SENTINEL_TO_FILL, alias="taux")
    base_admissible_brut: ValeurBrute = Field(
        default=SENTINEL_TO_FILL, alias="base_admissible"
    )

    @field_validator("taux_brut", "base_admissible_brut", mode="before")
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux(self) -> Decimal:
        return self._materialiser("taux", self.taux_brut)

    @property
    def base_admissible(self) -> Decimal:
        return self._materialiser("base_admissible", self.base_admissible_brut)


class VacancesParametres(_ParametresSectionBase):
    """Politique employeur de vacances — non fiscal, valeurs de référence.

    Les deux taux ``0.04`` et ``0.06`` sont dans la matrice Camp LilySO
    (règle 03) et documentés dans le fichier ``quebec.json``. Ils sont
    typés ``Decimal`` pour cohérence avec le reste du domaine, avec
    matérialisation à l'accès pour respecter le patron des sous-modèles.
    """

    taux_defaut_brut: ValeurBrute = Field(..., alias="taux_defaut")
    taux_alternatif_brut: ValeurBrute = Field(..., alias="taux_alternatif")
    mode_versement: str = "chaque_paie"

    @field_validator("taux_defaut_brut", "taux_alternatif_brut", mode="before")
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def taux_defaut(self) -> Decimal:
        return self._materialiser("taux_defaut", self.taux_defaut_brut)

    @property
    def taux_alternatif(self) -> Decimal:
        return self._materialiser("taux_alternatif", self.taux_alternatif_brut)


class HeuresSupplementairesParametres(_ParametresSectionBase):
    """Loi sur les normes du travail — heures supplémentaires.

    Seuil hebdomadaire (40 h au Québec) et multiplicateur (1,5×). Valeurs
    métier issues des Normes du travail QC, typées ``Decimal`` (le seuil
    reste un ``Decimal`` pour la cohérence des calculs, même s'il est
    entier).
    """

    seuil_hebdomadaire_heures_brut: ValeurBrute = Field(
        ..., alias="seuil_hebdomadaire_heures"
    )
    multiplicateur_brut: ValeurBrute = Field(..., alias="multiplicateur")

    @field_validator(
        "seuil_hebdomadaire_heures_brut", "multiplicateur_brut", mode="before"
    )
    @classmethod
    def _valider_brut(cls, v: Any) -> Any:
        return _valider_decimal_ou_to_fill(v)

    @property
    def seuil_hebdomadaire_heures(self) -> Decimal:
        return self._materialiser(
            "seuil_hebdomadaire_heures", self.seuil_hebdomadaire_heures_brut
        )

    @property
    def multiplicateur(self) -> Decimal:
        return self._materialiser("multiplicateur", self.multiplicateur_brut)



# ---------------------------------------------------------------------------
# Racine agrégeant les sections de paramètres d'une année
# ---------------------------------------------------------------------------
#
# Le nom des sections optionnelles doit correspondre à la clé JSON dans
# ``parameters/<AAAA>/*.json``. Cette liste est utilisée par
# :meth:`ParametresAnnee._propager_contexte` pour injecter dans chaque
# sous-modèle l'année, la juridiction et le fichier concernés (nécessaire
# à la construction du message de :class:`MissingParameterError`,
# Property 16).
_SECTIONS_PARAMETRES: Final[tuple[str, ...]] = (
    "frequence_paie",
    "rrq",
    "rqap",
    "impot_quebec",
    "impot_federal",
    "assurance_emploi",
    "td_1015_3",
    "td1",
    "fss",
    "cnesst",
    "cnt",
    "vacances",
    "heures_supplementaires",
)


class ParametresAnnee(BaseModel):
    """Racine agrégeant les paramètres fiscaux d'une année et d'une juridiction.

    Réflète la structure des fichiers ``parameters/<AAAA>/{quebec,canada}.json``.
    Chaque section est optionnelle et absente selon la juridiction :

    - **Québec** : ``frequence_paie``, ``rrq``, ``rqap``, ``impot_quebec``,
      ``fss``, ``cnesst``, ``cnt``, ``vacances``, ``heures_supplementaires``
      (et ``td_1015_3`` en préparation) ;
    - **Canada** : ``frequence_paie``, ``assurance_emploi``,
      ``impot_federal``, ``td1``.

    ``model_config`` :

    - ``frozen=True`` — immuabilité historique (règle 06) ;
    - ``extra="allow"`` — les fichiers portent des méta-données de racine
      (``notes``, ``date_consultation``, ...) qu'on ne veut pas énumérer
      explicitement ;
    - ``populate_by_name=True`` — cohérent avec les sous-modèles.

    Après la validation Pydantic (``model_validator(mode="after")``), la
    méthode :meth:`_propager_contexte` positionne les :class:`PrivateAttr`
    de contexte (``_contexte_annee``, ``_contexte_juridiction``,
    ``_contexte_fichier``, ``_contexte_section``) sur chaque section
    non-``None``. Ces attributs sont indispensables pour que
    :meth:`_ParametresSectionBase._materialiser` construise un message
    :class:`MissingParameterError` actionnable (Property 16, Req 8.6, Req 9.5).

    L'assignation utilise :func:`object.__setattr__` : le patron par défaut
    de Pydantic v2 pour ``PrivateAttr`` supporte l'écriture sur un modèle
    ``frozen=True``, mais ``object.__setattr__`` court-circuite tout hook
    de validation et rend l'intention (« modifier l'état privé, pas un
    champ du modèle ») explicite.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    # ClassVar : liste utilisée par _propager_contexte, exposée pour les
    # tests introspectifs (ne devrait pas être serialisée par Pydantic).
    _NOMS_SECTIONS: ClassVar[tuple[str, ...]] = _SECTIONS_PARAMETRES

    # ---- Champs racine ----------------------------------------------------

    annee: int = Field(..., ge=2000, le=2100)
    juridiction: Juridiction
    source: str
    date_publication: str
    date_consultation: str = ""
    url_consultee: str = ""
    notes: str = ""

    # ---- Sections optionnelles -------------------------------------------
    #
    # Toutes les sections sont ``| None = None`` : la présence d'une section
    # dans un fichier de paramètres dépend de la juridiction (Québec vs
    # Canada). Une section absente ne doit pas empêcher le chargement, et
    # tout accès à une section ``None`` levé par un module de calcul aval
    # sera un ``AttributeError`` explicite (« ``NoneType`` object has no
    # attribute ``...`` »), distinct de :class:`MissingParameterError`.

    frequence_paie: FrequencePaieParametres | None = None
    rrq: RRQParametres | None = None
    rqap: RQAPParametres | None = None
    impot_quebec: ImpotQCParametres | None = None
    impot_federal: ImpotFederalParametres | None = None
    assurance_emploi: AEParametres | None = None
    td_1015_3: TD1015_3Parametres | None = None
    td1: TD1Parametres | None = None
    fss: FSSParametres | None = None
    cnesst: CNESSTParametres | None = None
    cnt: CNTParametres | None = None
    vacances: VacancesParametres | None = None
    heures_supplementaires: HeuresSupplementairesParametres | None = None

    # ---- Propagation du contexte aux sections ----------------------------

    @model_validator(mode="after")
    def _propager_contexte(self) -> "ParametresAnnee":
        """Injecte le contexte (année, juridiction, fichier) dans chaque section.

        Chaque section non-``None`` reçoit :

        - ``_contexte_annee`` : l'année (``int``) ;
        - ``_contexte_juridiction`` : la juridiction (``str``, ex.
          ``"quebec"``, ``"canada"``) ;
        - ``_contexte_fichier`` : le chemin relatif du fichier de paramètres
          (ex. ``"parameters/2026/quebec.json"``) ;
        - ``_contexte_section`` : le nom de la section (ex. ``"rrq"``).

        Ces valeurs alimentent le message de :class:`MissingParameterError`
        levée par :meth:`_ParametresSectionBase._materialiser` (Property 16).

        L'assignation utilise :func:`object.__setattr__` pour ne pas
        déclencher le verrou ``frozen`` des sous-modèles. Sur Pydantic v2,
        les :class:`PrivateAttr` sont préservés à travers cette écriture :
        ``__pydantic_private__`` reste initialisé (défauts positionnés par
        la construction), et l'attribut ainsi écrit est retrouvé par
        ``__getattribute__`` sur l'instance.
        """
        juridiction_str = self.juridiction.value
        fichier = f"parameters/{self.annee}/{juridiction_str}.json"

        for nom_section in self._NOMS_SECTIONS:
            section = getattr(self, nom_section, None)
            if section is None:
                continue
            object.__setattr__(section, "_contexte_annee", self.annee)
            object.__setattr__(section, "_contexte_juridiction", juridiction_str)
            object.__setattr__(section, "_contexte_fichier", fichier)
            object.__setattr__(section, "_contexte_section", nom_section)

        return self


# ---------------------------------------------------------------------------
# Point d'entrée du chargement (implémentation Task 12.3)
# ---------------------------------------------------------------------------


def load_parameters(
    annee: int,
    juridiction: Juridiction,
    chemin_racine: Path | None = None,
) -> ParametresAnnee:
    """Charge les paramètres fiscaux d'une année et d'une juridiction.

    Point d'entrée unique de lecture des fichiers
    ``parameters/<AAAA>/{quebec,canada}.json`` (règle 05, Req 9.1–9.11).

    Séquence exécutée à chaque appel — la fonction est **pure** (aucun
    cache, aucun état module, aucun effet de bord) pour satisfaire
    Req 9.10 / Property 15 :

    1. **Résolution du dossier racine** (Req 9.9). Si ``chemin_racine``
       n'est pas fourni, le défaut est calculé depuis ``__file__`` :
       ``Path(__file__).parent.parent / "parameters"``. Ce mode de
       résolution est **déterministe** et indépendant du répertoire de
       travail courant : deux exécutions dans deux CWD différents lisent
       le même fichier.
    2. **Construction du chemin de fichier**
       ``<chemin_racine>/<annee>/<juridiction.value>.json``. La valeur
       de :class:`Juridiction` (``"quebec"`` ou ``"canada"``) est
       utilisée telle quelle comme nom de fichier — la mise en
       correspondance JSON ↔ code repose sur cette convention (règle 05).
    3. **Vérification d'existence** (Req 9.8). Si le fichier n'existe
       pas, :class:`FileNotFoundError` est levée avec un message qui
       contient l'année, la juridiction et le chemin absolu — assez
       d'information pour que l'utilisateur sache exactement quel
       fichier créer.
    4. **Lecture et parsing JSON** (Req 9.4, 13.5). Le fichier est lu en
       UTF-8 puis parsé via :func:`_parse_json_reject_floats`, qui
       branche ``json.loads(..., parse_float=_reject_json_float)``.
       Tout littéral décimal non guillemé (``0.063`` au lieu de
       ``"0.063"``) fait échouer le chargement fail-fast, avec un
       message actionnable pointant vers le document JSON source.
       Aucun ``float`` n'est jamais construit — même transitoirement
       (règle 01).
    5. **Construction du modèle Pydantic**. ``ParametresAnnee(**donnees)``
       délègue la validation aux 13 sous-modèles. Chaque
       ``field_validator("*_brut", mode="before")`` appelle
       :func:`_valider_decimal_ou_to_fill` : les chaînes numériques
       sont converties en :class:`Decimal` via ``Decimal(str)`` (Req 9.3),
       la sentinelle ``"TO_FILL"`` est préservée telle quelle
       (Req 9.11), et tout ``float`` résiduel est refusé (règle 01,
       Req 10.1). Une chaîne d'alias ``Field(alias=...)`` permet aux
       clés JSON originales (sans suffixe ``_brut``) d'être reconnues.
    6. **Propagation du contexte** — s'exécute automatiquement via le
       ``model_validator(mode="after")`` :meth:`ParametresAnnee._propager_contexte`.
       Chaque sous-modèle reçoit l'année, la juridiction et le chemin
       du fichier pour que la future :class:`MissingParameterError`
       soit **contextualisée** (Property 16, Req 8.6, Req 9.5).

    **Fail-fast différé.** Une valeur ``"TO_FILL"`` sur un champ non
    consommé n'empêche pas le chargement (Req 9.11). L'erreur ne se
    matérialise qu'au **premier accès** à la propriété correspondante
    (``parametres.rrq.maximum_gains_admissibles_mga``, par exemple),
    avec un message renvoyant vers TP-1015.F 2026 (juridiction Québec)
    ou T4127 2026 (juridiction Canada). Ce couplage est piloté par
    :meth:`_ParametresSectionBase._materialiser`.

    Paramètres :

    - ``annee`` : année civile des paramètres (2000 à 2100) ;
    - ``juridiction`` : :class:`Juridiction.QUEBEC` ou :class:`Juridiction.CANADA` ;
    - ``chemin_racine`` : dossier ``parameters/`` à utiliser (utile pour
      les tests). Par défaut, résolu depuis ``__file__`` (Req 9.9).

    Retourne :

    - Une instance :class:`ParametresAnnee` figée (``frozen=True``) et
      contextualisée (les sections portent l'année, la juridiction et le
      chemin du fichier pour les messages d'erreur).

    Lève :

    - :class:`FileNotFoundError` si ``parameters/<annee>/<juridiction>.json``
      n'existe pas (Req 9.8) ;
    - :class:`ValueError` sur littéral JSON non guillemé pour un champ
      numérique (Req 9.4, 13.5, levée par
      :func:`_parse_json_reject_floats`) ;
    - :class:`pydantic.ValidationError` sur incohérence de schéma
      (type incorrect, champ obligatoire manquant, etc.) ;
    - :class:`~models.exceptions.MissingParameterError` **au premier
      accès** à un champ ``"TO_FILL"** — jamais au chargement (Req 9.11).

    Discipline :

    - **Règle 01** : aucun ``float`` intermédiaire. Le hook
      ``parse_float`` de :func:`_parse_json_reject_floats` refuse tout
      littéral flottant JSON avant même la construction du dictionnaire.
    - **Règle 05** : ce chargeur est la **source unique** de lecture des
      paramètres fiscaux. Aucun autre module ne DOIT lire directement
      les fichiers ``parameters/<AAAA>/*.json``.
    - **Req 9.7** : la fonction ne s'exécute qu'à l'appel — l'import du
      module n'a aucun effet de bord (démontré par le test
      ``TestValidationDiffereeALImport``).
    - **Req 9.10** : aucun ``@lru_cache``, aucun état module partagé —
      deux appels identiques retournent deux instances distinctes mais
      ``==``.
    """
    # Étape 1 — Résolution du dossier racine (Req 9.9). Le défaut est
    # calculé depuis le fichier courant, jamais depuis ``os.getcwd()``,
    # pour rester déterministe quel que soit le répertoire de travail.
    if chemin_racine is None:
        chemin_racine = Path(__file__).parent.parent / "parameters"

    # Étape 2 — Construction du chemin de fichier. La convention
    # ``<AAAA>/<juridiction>.json`` est celle imposée par la règle 05
    # (paramètres versionnés par année) et par le design §Components 10.
    chemin_fichier = chemin_racine / str(annee) / f"{juridiction.value}.json"

    # Étape 3 — Vérification d'existence (Req 9.8). Le message inclut
    # l'année, la juridiction et le chemin absolu afin que l'utilisateur
    # puisse localiser précisément le fichier à créer.
    if not chemin_fichier.is_file():
        raise FileNotFoundError(
            f"Fichier de paramètres introuvable pour l'année {annee} et "
            f"la juridiction '{juridiction.value}' : "
            f"'{chemin_fichier}'. Créer le fichier "
            f"'parameters/{annee}/{juridiction.value}.json' à partir "
            f"des valeurs officielles "
            f"({'TP-1015.F' if juridiction == Juridiction.QUEBEC else 'T4127'} "
            f"{annee}). Voir règle 05 "
            "(`.kiro/steering/05-parametres-annuels-versionnes.md`)."
        )

    # Étape 4 — Lecture et parsing JSON (Req 9.4, 13.5). ``read_text`` en
    # UTF-8 est explicite pour éviter les surprises sur Windows où
    # l'encodage par défaut est ``cp1252``. ``_parse_json_reject_floats``
    # refuse tout littéral décimal non guillemé (règle 01).
    contenu_texte = chemin_fichier.read_text(encoding="utf-8")
    donnees_brutes = _parse_json_reject_floats(contenu_texte)

    # Étape 5 & 6 — Construction du modèle et propagation du contexte.
    # Pydantic exécute automatiquement ``_propager_contexte`` en
    # ``model_validator(mode="after")`` après avoir bâti chaque
    # sous-section, injectant l'année, la juridiction et le fichier
    # dans les ``PrivateAttr`` de contexte des sections non-``None``.
    return ParametresAnnee(**donnees_brutes)


# ---------------------------------------------------------------------------
# Mécanisme de repli ``nb_periodes_annuelles`` (Task 12.4, Req 2.7)
# ---------------------------------------------------------------------------


#: Valeur par défaut documentée pour ``nb_periodes_annuelles`` en dernier
#: recours (branche (c) du repli de Req 2.7). Ce n'est **pas** un paramètre
#: fiscal au sens de la règle 05 : c'est une valeur de calendrier
#: correspondant à une année bi-hebdomadaire standard (26 périodes = 52
#: semaines / 2). La règle 05 interdit de coder en dur les taux, plafonds,
#: seuils et exemptions fiscaux — ``26`` ne relève d'aucune de ces
#: catégories et est explicitement autorisé par le design §Components 10
#: et par les notes de ``tasks.md`` §12.4.
_NB_PERIODES_ANNUELLES_REPLI_DEFAUT: Final[int] = 26


def load_nb_periodes_annuelles(
    annee: int,
    juridiction: Juridiction,
    chemin_racine: Path | None = None,
) -> tuple[int, str]:
    """Retourne ``(nb_periodes_annuelles, source_effective)`` avec repli (Req 2.7).

    Ordre du repli (design §Components 10 « Mécanisme de repli
    ``nb_periodes_annuelles`` ») :

    - **(a) Année courante.** Si ``parameters/<annee>/<juridiction>.json``
      existe et contient ``frequence_paie.nb_periodes_annuelles`` sous
      forme d'entier positif, la valeur est lue depuis ce fichier et
      ``source_effective = "annee_courante"``.
    - **(b) Année précédente.** Sinon, si
      ``parameters/<annee - 1>/<juridiction>.json`` existe et contient la
      clé, la valeur est réutilisée et
      ``source_effective = f"repli_annee_{annee - 1}"``.
    - **(c) Valeur par défaut documentée.** Sinon, la valeur ``26`` est
      retournée avec ``source_effective = "valeur_par_defaut"``.

    Cette fonction est **distincte** de :func:`load_parameters` : elle
    NE lève PAS :class:`FileNotFoundError` en cas de fichier absent
    (Req 9.8 s'applique au chargement complet, pas au seul repli de
    ``nb_periodes_annuelles``). Le design §Components 10 énonce
    explicitement que le repli DOIT « permettre la poursuite de
    l'opération sans intervention manuelle bloquante ».

    Paramètres :

    - ``annee`` : année civile pour laquelle on cherche
      ``nb_periodes_annuelles`` ;
    - ``juridiction`` : :class:`Juridiction.QUEBEC` ou
      :class:`Juridiction.CANADA` (la valeur doit être identique dans les
      deux fichiers selon Req 2.7 — le repli ne s'occupe que d'une
      juridiction à la fois) ;
    - ``chemin_racine`` : dossier ``parameters/`` à utiliser (utile pour
      les tests). Par défaut, résolu depuis ``__file__`` (Req 9.9),
      identique à :func:`load_parameters`.

    Retourne :

    - Un tuple ``(nb_periodes_annuelles, source_effective)`` où :

      * ``nb_periodes_annuelles`` est un :class:`int` positif ;
      * ``source_effective`` est une chaîne parmi ``"annee_courante"``,
        ``"repli_annee_<AAAA>"`` et ``"valeur_par_defaut"``.

    La valeur ``source_effective`` est destinée à être exposée dans
    :attr:`FrequencePaieParametres.source_effective` de tout
    :class:`ParametresAnnee` construit à partir de ce repli, afin de
    préserver la traçabilité de la source (règle 02).

    Discipline :

    - **Règle 01** : la lecture JSON passe par
      :func:`_parse_json_reject_floats` (aucun ``float`` intermédiaire).
    - **Règle 02** : la source effective est **toujours** retournée à
      l'appelant, jamais silencieusement remplacée. La branche (c) est
      audit-friendly grâce à la chaîne ``"valeur_par_defaut"``.
    - **Règle 05** : aucun taux/plafond fiscal en dur. La seule valeur
      numérique en dur est ``26``, qui est un élément de calendrier
      (année bi-hebdomadaire standard), pas un paramètre fiscal.
    """
    if chemin_racine is None:
        chemin_racine = Path(__file__).parent.parent / "parameters"

    def _extraire_nb_periodes_annuelles(annee_lecture: int) -> int | None:
        """Extrait ``nb_periodes_annuelles`` d'un fichier de paramètres.

        Retourne ``None`` si :

        - le fichier ``parameters/<annee_lecture>/<juridiction>.json``
          n'existe pas ;
        - le fichier ne contient pas de section ``frequence_paie`` sous
          forme de dictionnaire ;
        - la clé ``nb_periodes_annuelles`` est absente, n'est pas un
          entier, est un booléen, ou est un entier ≤ 0.

        Ces refus silencieux (retour ``None``) sont volontaires : le repli
        (b) doit rester **best-effort**. Un fichier de l'année précédente
        endommagé ne doit PAS bloquer l'opération — la branche (c)
        garantit qu'on retombe toujours sur une valeur exploitable
        (design §Components 10).

        Cette fonction NE valide PAS la structure complète du fichier :
        elle ne consomme que ``frequence_paie.nb_periodes_annuelles``.
        Elle ne lève donc jamais :class:`MissingParameterError` sur un
        ``"TO_FILL"`` d'une autre section (Req 9.11).
        """
        chemin_fichier = chemin_racine / str(annee_lecture) / f"{juridiction.value}.json"
        if not chemin_fichier.is_file():
            return None

        # Utilise ``_parse_json_reject_floats`` pour rester cohérent avec
        # :func:`load_parameters` : un fichier avec un littéral décimal
        # non guillemé serait refusé par ce parseur. Ici on ne lit qu'un
        # entier, donc le hook ``parse_float`` ne s'active pas — mais on
        # profite du fail-fast en cas de JSON malformé.
        contenu = chemin_fichier.read_text(encoding="utf-8")
        donnees = _parse_json_reject_floats(contenu)

        frequence_paie = donnees.get("frequence_paie")
        if not isinstance(frequence_paie, dict):
            return None

        nb = frequence_paie.get("nb_periodes_annuelles")
        # ``isinstance(nb, bool)`` est True lorsque ``nb is True`` ou
        # ``nb is False`` : on refuse explicitement ce cas parce que
        # ``bool`` est sous-classe de ``int`` en Python — sans ce garde,
        # ``True`` serait accepté comme ``1``.
        if isinstance(nb, bool) or not isinstance(nb, int) or nb < 1:
            return None

        return nb

    # Branche (a) — fichier de l'année courante.
    valeur_courante = _extraire_nb_periodes_annuelles(annee)
    if valeur_courante is not None:
        return (valeur_courante, "annee_courante")

    # Branche (b) — fichier de l'année précédente.
    annee_precedente = annee - 1
    valeur_precedente = _extraire_nb_periodes_annuelles(annee_precedente)
    if valeur_precedente is not None:
        return (valeur_precedente, f"repli_annee_{annee_precedente}")

    # Branche (c) — valeur par défaut documentée (design §Components 10).
    return (_NB_PERIODES_ANNUELLES_REPLI_DEFAUT, "valeur_par_defaut")
