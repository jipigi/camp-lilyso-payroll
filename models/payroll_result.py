"""Modèles de sortie du moteur de paie — ``GainsDecomposes``, ``MontantAvecTrace``.

Spec de référence : ``moteur-paie-contrats`` — tâches 10.2, 10.3, 10.4.
Design de référence : sections « Components and Interfaces » §9 et
« Data Models » §9 (``design.md``).

Ce module expose la hiérarchie de sortie du moteur. La tâche 10.2 met en
place les deux modèles atomiques :

- :class:`GainsDecomposes` — décomposition du brut d'une paie en cinq
  composantes (``salaire_regulier``, ``heures_supplementaires_montant``,
  ``vacances``, ``jours_feries_manuels``, ``brut_total``) plus deux
  paramètres portés depuis les paramètres annuels
  (``multiplicateur_heures_supp``, ``seuil_heures_supp_hebdo`` —
  Req 4 AC14, règle 05).
- :class:`MontantAvecTrace` — couple ``(montant, trace)`` servant à
  chaque cotisation ou retenue individuelle, où la trace est une
  :class:`models.trace.CalculationTrace` attestant la source officielle,
  les paramètres et les entrées du calcul (règle 02).

La tâche 10.3 ajoute deux nouveaux modèles agrégés :

- :class:`RetenuesEmploye` — sept :class:`MontantAvecTrace` (RRQ, RQAP,
  AE, impôt QC formule, impôt QC retenu, impôt fédéral formule, impôt
  fédéral retenu) plus ``total_retenues_employe: Decimal >= 0``. Un
  invariant ``model_validator(mode="after")`` impose l'égalité stricte
  entre le total et la somme des cinq retenues *effectivement retenues*
  (Req 12.8 : les ``*_formule`` NE comptent PAS dans le total).
- :class:`CotisationsEmployeur` — six :class:`MontantAvecTrace` (RRQ
  employeur, RQAP employeur, AE employeur, FSS, CNESST, CNT) plus le
  drapeau ``cnesst_en_attente_classification: bool`` et
  ``total_cotisations_employeur: Decimal >= 0``. Un invariant
  ``model_validator(mode="after")`` impose l'égalité stricte entre le
  total et la somme des six cotisations (le drapeau n'affecte pas la
  somme).

La classe :class:`PayrollResult` reste **stubbée** ci-dessous pour
permettre la collection pytest de ``tests/models/test_payroll_result.py``
(qui importe les cinq symboles en tête) sans échouer avec
``ModuleNotFoundError``. Ce stub sera **remplacé** par son
implémentation complète à la tâche 10.4. Toute utilisation du stub avec
des arguments lèvera ``TypeError`` — c'est volontaire, cela signale au
test qu'il dépend d'une tâche à venir (règle 06 — TDD, tests avant
code).

Requirements couverts par les tâches 10.2 et 10.3 :

- Req 4.1 — Structure ``GainsDecomposes`` avec les cinq composantes du
  brut plus les deux valeurs de contexte heures supplémentaires.
- Req 4.14 — ``multiplicateur_heures_supp`` et ``seuil_heures_supp_hebdo``
  sont *portés* dans ``GainsDecomposes`` (jamais recalculés) ; le module
  de calcul lit les valeurs depuis ``parameters/<AAAA>/quebec.json``
  section ``heures_supplementaires`` et les passe à cette classe telles
  quelles.
- Req 5.8 — ``MontantAvecTrace`` fixe le contrat ``(Decimal, CalculationTrace)``
  utilisé par chaque cotisation individuelle et par le tuple de retour
  des fonctions de calcul fiscal (règle 02).
- Req 4.2 — Structure ``RetenuesEmploye`` avec les sept retenues
  individuelles et le total agrégé.
- Req 4.3 — Structure ``CotisationsEmployeur`` avec les six cotisations
  individuelles, le drapeau ``cnesst_en_attente_classification`` et le
  total agrégé.
- Req 10.1 — Tous les montants ``Decimal`` refusent ``float`` via
  :func:`models._validators.reject_float` en ``mode="before"``.
- Req 12.8 — Les montants ``impot_qc_formule`` et ``impot_federal_formule``
  ne sont PAS additionnés au total des retenues employé (portés pour la
  traçabilité de la formule avant application d'une exonération
  TP-1015.3 / TD1).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit ;
- Règle 02 — chaque ``MontantAvecTrace`` porte une trace conforme à la
  liste blanche (validation portée par :class:`models.trace.CalculationTrace`) ;
- Règle 06 — TDD, tests avant code : ce module est couvert par
  ``tests/models/test_payroll_result.py`` (tâche 10.1) écrit **avant**
  cette implémentation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from models._validators import _parse_json_reject_floats, reject_float
from models.cumuls import CumulsYTD
from models.enums import StatutDePaie
from models.pay_period import PayPeriod
from models.trace import CalculationTrace


# ---------------------------------------------------------------------------
# GainsDecomposes — décomposition du brut (Req 4.1, 4.14)
# ---------------------------------------------------------------------------


class GainsDecomposes(BaseModel):
    """Décomposition du brut d'une paie (design §Data Models 9).

    Sept champs, tous ``Decimal``, tous refusant ``float`` en entrée
    (règle 01). Cinq d'entre eux (``salaire_regulier``,
    ``heures_supplementaires_montant``, ``vacances``,
    ``jours_feries_manuels``, ``brut_total``) constituent les
    composantes du gain brut de la paie et sont contraints ``>= 0``. Les
    deux derniers (``multiplicateur_heures_supp``,
    ``seuil_heures_supp_hebdo``) sont des *valeurs de contexte* portées
    depuis les paramètres annuels (règle 05) et contraints ``> 0`` —
    Req 4.14 impose qu'ils soient *reçus* du module de calcul, jamais
    recalculés par cette classe.

    Le contrat n'impose PAS ``salaire_regulier + heures_supp + vacances
    + jours_feries_manuels == brut_total`` : cette identité, si elle
    devient nécessaire, sera portée par une spec ultérieure du plan
    (``gains-bruts-vacances-hs``). La tâche 10.2 se limite au contrat
    de forme (types, bornes, immuabilité, refus de ``float``).
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2 — cohérente avec les autres modèles du
    # domaine (design §9) :
    # - ``frozen=True`` : immuabilité stricte après construction (Req 4.12,
    #   couvert par Property 1) ;
    # - ``extra="forbid"`` : rejet fail-fast des champs non déclarés
    #   (design §9, coherent avec ``Employee``, ``PayPeriod``, etc.).
    # ------------------------------------------------------------------
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Cinq composantes du brut — chacune ``>= 0`` (Req 4.11, Property 9).
    # L'ordre déclaré correspond à celui du design §Data Models 9 et à
    # celui affiché sur le bulletin de paie (spec ``bulletin-pdf``).
    salaire_regulier: Decimal = Field(..., ge=Decimal("0"))
    heures_supplementaires_montant: Decimal = Field(..., ge=Decimal("0"))
    vacances: Decimal = Field(..., ge=Decimal("0"))
    jours_feries_manuels: Decimal = Field(..., ge=Decimal("0"))
    brut_total: Decimal = Field(..., ge=Decimal("0"))

    # Deux valeurs de contexte heures supplémentaires — Req 4.14, règle 05.
    # ``gt=0`` (strictement positif) : un multiplicateur ou un seuil
    # nul ou négatif n'a aucun sens fiscal et signalerait un bug amont
    # (paramètres corrompus ou mauvais aiguillage). Refus fail-fast.
    multiplicateur_heures_supp: Decimal = Field(..., gt=Decimal("0"))
    seuil_heures_supp_hebdo: Decimal = Field(..., gt=Decimal("0"))

    # ------------------------------------------------------------------
    # Refus universel de ``float`` (règle 01, Req 10.1).
    #
    # Le validateur ``mode="before"`` s'applique **avant** la coercition
    # Pydantic, ce qui empêche la conversion silencieuse d'un ``float``
    # en ``Decimal``. Il est appliqué à tous les champs ``Decimal`` du
    # modèle via l'astuce ``"*"`` — Pydantic v2 exécute alors le
    # validateur sur chaque champ déclaré (les champs non-``Decimal``,
    # si présents, seraient également filtrés mais ce modèle n'en a
    # pas). ``reject_float`` accepte : ``int``, ``str`` conforme au
    # format décimal, ``Decimal`` fini à précision raisonnable ; il
    # refuse : ``float``, ``Decimal`` non fini ou à précision aberrante.
    # ------------------------------------------------------------------
    @field_validator("*", mode="before")
    @classmethod
    def _rejeter_float(cls, v: Any) -> Any:
        """Délègue à :func:`reject_float` (règle 01, Req 10.1)."""
        return reject_float(v)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des 7 ``Decimal`` (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    #
    # ``when_used="json"`` cible UNIQUEMENT la sortie JSON —
    # ``model_dump`` (dict Python) conserve les ``Decimal``. Chaque
    # champ ``Decimal`` (les cinq composantes du brut + les deux
    # valeurs de contexte heures supplémentaires) est encodé en chaîne
    # guillemée dans la chaîne JSON produite, condition (c) de
    # Property 6 : aucun littéral flottant non guillemé (Req 13.4).
    @field_serializer(
        "salaire_regulier",
        "heures_supplementaires_montant",
        "vacances",
        "jours_feries_manuels",
        "brut_total",
        "multiplicateur_heures_supp",
        "seuil_heures_supp_hebdo",
        when_used="json",
    )
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque champ ``Decimal`` en chaîne guillemée (règle 01)."""
        return str(v)


# ---------------------------------------------------------------------------
# MontantAvecTrace — couple ``(Decimal, CalculationTrace)`` (Req 5.8)
# ---------------------------------------------------------------------------


class MontantAvecTrace(BaseModel):
    """Couple ``(montant, trace)`` d'un calcul fiscal (design §Data Models 9).

    Structure atomique utilisée par :class:`RetenuesEmploye` et
    :class:`CotisationsEmployeur` pour chaque cotisation ou retenue
    individuelle. Le contrat fixé ici correspond exactement au tuple
    de retour ``(Decimal, CalculationTrace)`` exigé par la règle 02 pour
    toute fonction de calcul fiscal — reformulé en objet plutôt qu'en
    tuple pour bénéficier de la validation Pydantic et de l'immuabilité.

    - ``montant : Decimal >= 0`` — le résultat monétaire du calcul (une
      retenue ou cotisation, y compris ``0.00`` en cas d'exonération).
    - ``trace : CalculationTrace`` — la trace exhaustive du calcul, dont
      la source officielle est validée par :class:`CalculationTrace`
      (règle 02).

    Note : ``MontantAvecTrace`` n'impose PAS que ``trace.resultat ==
    montant``. Cette contrainte de cohérence, si elle devient nécessaire,
    sera portée par une spec ultérieure. La tâche 10.2 se limite au
    contrat de forme (types, non-négativité, immuabilité, refus de
    ``float``).
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2 — cohérente avec ``GainsDecomposes`` et
    # les autres modèles du domaine.
    # ------------------------------------------------------------------
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Montant scalaire ``>= 0`` (Req 4.11, Property 9). Un montant
    # négatif signalerait une erreur amont dans le module de calcul —
    # rejet fail-fast plutôt que clampage silencieux.
    montant: Decimal = Field(..., ge=Decimal("0"))

    # La trace elle-même est un modèle Pydantic frozen (voir
    # ``models/trace.py``). Sa validation (liste blanche des sources,
    # refus de ``float`` sur ses champs ``Decimal``, etc.) est portée
    # par ``CalculationTrace`` — ce champ hérite de tous ces contrôles
    # transitivement.
    trace: CalculationTrace

    # ------------------------------------------------------------------
    # Refus universel de ``float`` sur les champs ``Decimal`` (règle 01,
    # Req 10.1). Ici, seul ``montant`` est ``Decimal`` ; ``trace`` est un
    # sous-modèle. Le sélecteur ``"montant"`` cible explicitement le
    # champ scalaire — ``reject_float`` traverse toute valeur non-Decimal
    # (dict, sous-modèle, etc.) sans lever d'erreur, mais on préfère la
    # sélection explicite pour éviter toute confusion à l'inspection.
    # ------------------------------------------------------------------
    @field_validator("montant", mode="before")
    @classmethod
    def _rejeter_float_montant(cls, v: Any) -> Any:
        """Délègue à :func:`reject_float` (règle 01, Req 10.1)."""
        return reject_float(v)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe du ``montant`` (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    #
    # Seul ``montant`` est ``Decimal`` — ``trace`` est un sous-modèle
    # (:class:`CalculationTrace`) qui porte ses propres sérialiseurs
    # transitivement. ``when_used="json"`` : conversion en chaîne
    # guillemée uniquement à la sortie JSON.
    @field_serializer("montant", when_used="json")
    def _serialiser_montant(self, v: Decimal) -> str:
        """Encode ``montant`` en chaîne guillemée (règle 01, Req 13.4)."""
        return str(v)


# ---------------------------------------------------------------------------
# RetenuesEmploye — 7 MontantAvecTrace + total (Req 4.2, 12.8)
# ---------------------------------------------------------------------------


class RetenuesEmploye(BaseModel):
    """Agrégat des retenues employé d'une paie (design §Data Models 9).

    Sept :class:`MontantAvecTrace` couvrant :

    - **RRQ** (``rrq``) : cotisation employé au Régime de rentes du
      Québec (source ``TP-1015.F`` — spec ultérieure ``rrq``) ;
    - **RQAP** (``rqap``) : cotisation employé au Régime québécois
      d'assurance parentale ;
    - **AE** (``ae``) : cotisation employé à l'assurance-emploi (taux
      Québec, spec ultérieure ``assurance-emploi``) ;
    - **Impôt QC formule** (``impot_qc_formule``) : retenue **calculée
      par la formule TP-1015.F** avant tout court-circuit d'exonération
      TP-1015.3 (Req 12.8) ;
    - **Impôt QC retenu** (``impot_qc_retenu``) : retenue **effectivement
      appliquée** sur la paie après application éventuelle du montant
      total TP-1015.3. Différe de ``impot_qc_formule`` uniquement en cas
      d'exonération ;
    - **Impôt fédéral formule** (``impot_federal_formule``) : retenue
      **calculée par la formule T4127** avant tout court-circuit
      d'exonération TD1 (Req 12.8) ;
    - **Impôt fédéral retenu** (``impot_federal_retenu``) : retenue
      **effectivement appliquée** après application éventuelle du
      montant total TD1.

    Plus le champ ``total_retenues_employe: Decimal >= 0`` qui doit
    égaler **strictement** la somme des cinq retenues *effectivement
    retenues* : ``rrq + rqap + ae + impot_qc_retenu +
    impot_federal_retenu``. Les deux montants ``*_formule`` NE comptent
    PAS dans le total (Req 12.8, test
    ``test_impots_formule_ne_comptent_pas_dans_le_total``) — ils sont
    stockés pour la traçabilité (permettent de reconstruire ce qui aurait
    été retenu sans exonération) mais ne sont jamais additionnés au net.

    Invariant `model_validator(mode="after")` : toute incohérence entre
    ``total_retenues_employe`` et la somme des cinq retenues retenues
    lève ``ValueError`` (encapsulée en ``ValidationError`` par Pydantic).
    L'égalité est comparée au cent près (``Decimal.__eq__``, tolérance
    nulle — règle 01).
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2 — cohérente avec les autres modèles.
    # ------------------------------------------------------------------
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Sept ``MontantAvecTrace``. Ordre déclaré = ordre du design
    # §Data Models 9 et du bulletin de paie (spec ``bulletin-pdf``).
    rrq: MontantAvecTrace
    rqap: MontantAvecTrace
    ae: MontantAvecTrace
    impot_qc_formule: MontantAvecTrace
    impot_qc_retenu: MontantAvecTrace
    impot_federal_formule: MontantAvecTrace
    impot_federal_retenu: MontantAvecTrace

    # Total scalaire ``>= 0`` — vérifié par l'invariant ci-dessous.
    total_retenues_employe: Decimal = Field(..., ge=Decimal("0"))

    # ------------------------------------------------------------------
    # Refus de ``float`` sur le total scalaire (règle 01, Req 10.1).
    # Les sept ``MontantAvecTrace`` portent leur propre garde
    # ``reject_float`` sur ``montant`` (transitivement).
    # ------------------------------------------------------------------
    @field_validator("total_retenues_employe", mode="before")
    @classmethod
    def _rejeter_float_total(cls, v: Any) -> Any:
        """Délègue à :func:`reject_float` (règle 01, Req 10.1)."""
        return reject_float(v)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe du total scalaire (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    #
    # Les sept ``MontantAvecTrace`` portent leur propre sérialiseur
    # transitivement (``montant`` en chaîne guillemée). Seul le champ
    # scalaire ``total_retenues_employe`` doit être encodé ici.
    @field_serializer("total_retenues_employe", when_used="json")
    def _serialiser_total(self, v: Decimal) -> str:
        """Encode ``total_retenues_employe`` en chaîne guillemée (règle 01)."""
        return str(v)

    # ------------------------------------------------------------------
    # Invariant de cohérence de somme (Req 12.8).
    #
    # ``total_retenues_employe`` DOIT égaler la somme des cinq retenues
    # *effectivement retenues*. Les deux montants ``*_formule`` (impôt
    # QC formule, impôt fédéral formule) NE comptent PAS — ils sont
    # portés pour la traçabilité mais absents du net (test
    # ``test_impots_formule_ne_comptent_pas_dans_le_total``).
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _verifier_coherence_total(self) -> "RetenuesEmploye":
        """Req 12.8 — total = RRQ + RQAP + AE + impôt QC retenu + impôt fédéral retenu."""
        somme_attendue = (
            self.rrq.montant
            + self.rqap.montant
            + self.ae.montant
            + self.impot_qc_retenu.montant
            + self.impot_federal_retenu.montant
        )
        if self.total_retenues_employe != somme_attendue:
            raise ValueError(
                "Incohérence de somme dans `RetenuesEmploye` (Req 12.8) : "
                f"`total_retenues_employe` = {self.total_retenues_employe} "
                f"mais la somme des cinq retenues effectivement retenues "
                f"(RRQ + RQAP + AE + impôt QC retenu + impôt fédéral "
                f"retenu) vaut {somme_attendue}. Les montants "
                "`impot_qc_formule` et `impot_federal_formule` NE "
                "comptent PAS dans le total (Req 12.8) : ils sont stockés "
                "pour la traçabilité de la formule avant application "
                "éventuelle d'une exonération TP-1015.3 / TD1."
            )
        return self


# ---------------------------------------------------------------------------
# CotisationsEmployeur — 6 MontantAvecTrace + drapeau + total (Req 4.3)
# ---------------------------------------------------------------------------


class CotisationsEmployeur(BaseModel):
    """Agrégat des cotisations employeur d'une paie (design §Data Models 9).

    Six :class:`MontantAvecTrace` couvrant :

    - **RRQ employeur** (``rrq_employeur``) : cotisation patronale au
      Régime de rentes du Québec (généralement égale à la cotisation
      employé — spec ultérieure ``rrq``) ;
    - **RQAP employeur** (``rqap_employeur``) : cotisation patronale au
      Régime québécois d'assurance parentale ;
    - **AE employeur** (``ae_employeur``) : cotisation patronale à
      l'assurance-emploi (multiplicateur 1,4 × AE employé pour le
      Québec — spec ultérieure ``assurance-emploi``) ;
    - **FSS** (``fss``) : Fonds des services de santé (spec ultérieure
      ``charges-patronales``) ;
    - **CNESST** (``cnesst``) : cotisation à la Commission des normes,
      de l'équité, de la santé et de la sécurité du travail. Le taux
      dépend de la classification d'entreprise assignée par la CNESST,
      qui peut être **en attente** au moment de la première paie de
      l'année (voir ``cnesst_en_attente_classification``) ;
    - **CNT** (``cnt``) : cotisation à la Commission des normes du
      travail.

    Plus deux champs additionnels :

    - ``cnesst_en_attente_classification: bool`` — drapeau opérationnel
      indiquant que le taux CNESST utilisé est provisoire (typiquement
      le taux moyen du secteur), à ajuster rétroactivement lorsque la
      classification définitive est reçue. La valeur du drapeau
      n'affecte PAS l'invariant de somme : ``cnesst.montant`` est
      toujours inclus dans le total (design §Data Models 9).
    - ``total_cotisations_employeur: Decimal >= 0`` — doit égaler
      **strictement** la somme des six cotisations.

    Invariant ``model_validator(mode="after")`` : toute incohérence entre
    ``total_cotisations_employeur`` et la somme des six cotisations lève
    ``ValueError`` (encapsulée en ``ValidationError`` par Pydantic).
    L'égalité est comparée au cent près (règle 01, tolérance nulle).
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2 — cohérente avec les autres modèles.
    # ------------------------------------------------------------------
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Six ``MontantAvecTrace`` — ordre du design §Data Models 9.
    rrq_employeur: MontantAvecTrace
    rqap_employeur: MontantAvecTrace
    ae_employeur: MontantAvecTrace
    fss: MontantAvecTrace
    cnesst: MontantAvecTrace

    # Drapeau opérationnel — placé entre ``cnesst`` (auquel il se
    # rapporte sémantiquement) et ``cnt`` (design §Data Models 9). Ce
    # positionnement facilite la lecture : la classification est un
    # attribut du calcul CNESST.
    cnesst_en_attente_classification: bool

    cnt: MontantAvecTrace

    # Total scalaire ``>= 0`` — vérifié par l'invariant ci-dessous.
    total_cotisations_employeur: Decimal = Field(..., ge=Decimal("0"))

    # ------------------------------------------------------------------
    # Refus de ``float`` sur le total scalaire (règle 01, Req 10.1).
    # Les six ``MontantAvecTrace`` portent leur propre garde
    # ``reject_float`` sur ``montant`` (transitivement).
    # ------------------------------------------------------------------
    @field_validator("total_cotisations_employeur", mode="before")
    @classmethod
    def _rejeter_float_total(cls, v: Any) -> Any:
        """Délègue à :func:`reject_float` (règle 01, Req 10.1)."""
        return reject_float(v)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe du total scalaire (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    #
    # Les six ``MontantAvecTrace`` portent leur propre sérialiseur
    # transitivement. Seul le champ scalaire
    # ``total_cotisations_employeur`` doit être encodé ici.
    @field_serializer("total_cotisations_employeur", when_used="json")
    def _serialiser_total(self, v: Decimal) -> str:
        """Encode ``total_cotisations_employeur`` en chaîne guillemée (règle 01)."""
        return str(v)

    # ------------------------------------------------------------------
    # Invariant de cohérence de somme (design §Data Models 9).
    #
    # ``total_cotisations_employeur`` DOIT égaler la somme des six
    # cotisations. Le drapeau ``cnesst_en_attente_classification`` n'a
    # AUCUN effet sur la somme — ``cnesst.montant`` (même provisoire)
    # participe toujours au total.
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _verifier_coherence_total(self) -> "CotisationsEmployeur":
        """Total = RRQ_er + RQAP_er + AE_er + FSS + CNESST + CNT (design §9)."""
        somme_attendue = (
            self.rrq_employeur.montant
            + self.rqap_employeur.montant
            + self.ae_employeur.montant
            + self.fss.montant
            + self.cnesst.montant
            + self.cnt.montant
        )
        if self.total_cotisations_employeur != somme_attendue:
            raise ValueError(
                "Incohérence de somme dans `CotisationsEmployeur` : "
                f"`total_cotisations_employeur` = "
                f"{self.total_cotisations_employeur} mais la somme des "
                f"six cotisations (RRQ employeur + RQAP employeur + AE "
                f"employeur + FSS + CNESST + CNT) vaut {somme_attendue}. "
                "Le drapeau `cnesst_en_attente_classification` n'a aucun "
                "effet sur cette somme : `cnesst.montant` (même "
                "provisoire) est toujours inclus dans le total."
            )
        return self


# ---------------------------------------------------------------------------
# PayrollResult — contrat de sortie complet du moteur (Req 4.4-4.13, 6.1-6.7)
# ---------------------------------------------------------------------------


class PayrollResult(BaseModel):
    """Résultat d'une paie du moteur Camp LilySO (design §Data Models 9).

    Modèle Pydantic v2 **immuable** (``frozen=True``, Req 4.12, 6.2) qui
    refuse tout champ inconnu (``extra="forbid"``). Représente une paie
    calculée dans son entièreté : identification, période, gains
    décomposés, retenues employé, cotisations employeur, net, coût
    employeur, cumuls YTD de fin de paie, et cycle de vie
    (``statut`` / ``remplace_par_id`` / ``date_emission``).

    Trois invariants de cohérence, portés par des
    ``model_validator(mode="after")`` exécutés dans l'ordre de
    déclaration :

    1. **Identités comptables** (Req 4.9, 4.10) :

       - ``net + retenues_employe.total_retenues_employe ==
         gains.brut_total`` (identité brute) ;
       - ``cout_employeur == gains.brut_total +
         cotisations_employeur.total_cotisations_employeur`` (identité
         coût employeur).

       Écart au cent près refusé (comparaison ``==`` sur ``Decimal``,
       tolérance nulle — règle 01).

    2. **Biconditionnelle statut ⟺ remplace_par_id ⟺ date_emission**
       (Req 6.3, 6.4, 6.5, 6.7) :

       - ``statut == REMPLACE_PAR`` ⟺ ``remplace_par_id`` renseigné
         (non-``None`` et non-vide) — les statuts ``BROUILLON``,
         ``EMISE`` et ``ANNULEE`` interdisent la présence de
         ``remplace_par_id`` ;
       - ``statut ∈ {EMISE, ANNULEE, REMPLACE_PAR}`` ⟹ ``date_emission``
         renseignée (implication unidirectionnelle : rien n'interdit
         d'avoir une ``date_emission`` en ``BROUILLON``).

       La chaîne ``""`` équivaut à ``None`` pour l'évaluation (truthiness
       via ``if not self.remplace_par_id``), cohérent avec le test
       ``test_remplace_par_id_vide_traite_comme_absent``.

    3. **Cohérence ``cumuls_fin``** (Req 4.6) :

       - ``cumuls_fin.employe_id == self.employe_id`` ;
       - ``cumuls_fin.annee_civile == self.annee_fiscale``.

       Un cumul rattaché à un autre employé ou à une autre année est
       refusé — garantit qu'aucun cumul étranger ne peut être
       « attaché » à une paie par erreur.

    Discipline exception : toutes les incohérences sont levées comme
    ``ValueError`` par les validateurs, encapsulées automatiquement en
    :class:`pydantic.ValidationError` par Pydantic v2 (Req 8.7 — refus
    de forme, disjoint de :class:`PayrollDomainError`).

    Requirements couverts : 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11,
    4.12, 4.13, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7.
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2 — cohérente avec les autres modèles.
    # ------------------------------------------------------------------
    model_config = ConfigDict(frozen=True, extra="forbid")

    # ------------------------------------------------------------------
    # Identification (Req 6.1, 6.6)
    # ------------------------------------------------------------------

    id_paie: str = Field(..., min_length=1)
    """Identifiant unique de la paie. Non vide (design §Data Models 9).
    Convention Camp LilySO : ``PAIE-<employe>-<annee>-<numero_periode>``.
    """

    version: int = Field(..., ge=1)
    """Numéro de version de la paie. Débute à 1, incrémenté à chaque
    annulation-remplacement (Req 6.6). Une version < 1 est refusée."""

    employe_id: str = Field(..., min_length=1)
    """Identifiant technique de l'employé — cohérent avec
    ``cumuls_fin.employe_id`` (Req 4.6, vérifié par
    :meth:`_cumuls_fin_coherents`)."""

    annee_fiscale: int = Field(..., ge=2000, le=2100)
    """Année fiscale de rattachement — cohérente avec
    ``pay_period.annee_fiscale`` (contrat amont) et
    ``cumuls_fin.annee_civile`` (Req 4.6)."""

    # ------------------------------------------------------------------
    # Sections composites (Req 4.4, 4.7, 4.8)
    # ------------------------------------------------------------------

    pay_period: PayPeriod
    """Période de paie décomposée en ses semaines constituantes."""

    gains: GainsDecomposes
    """Décomposition du brut (Req 4.1, 4.4)."""

    retenues_employe: RetenuesEmploye
    """Sept retenues employé + total (Req 4.2, 4.7)."""

    cotisations_employeur: CotisationsEmployeur
    """Six cotisations employeur + drapeau CNESST + total (Req 4.3, 4.8)."""

    # ------------------------------------------------------------------
    # Agrégats scalaires (Req 4.9, 4.10, 4.11)
    # ------------------------------------------------------------------

    net: Decimal = Field(..., ge=Decimal("0"))
    """Salaire net versé à l'employé. Contrainte ``>= 0`` (Req 4.11).
    Identité comptable (Req 4.9) : ``net + total_retenues_employe ==
    gains.brut_total``, vérifiée par :meth:`_identites_comptables`."""

    cout_employeur: Decimal = Field(..., ge=Decimal("0"))
    """Coût total employeur (brut + charges patronales). Contrainte
    ``>= 0`` (Req 4.11). Identité comptable (Req 4.10) :
    ``cout_employeur == gains.brut_total +
    total_cotisations_employeur``, vérifiée par
    :meth:`_identites_comptables`."""

    cumuls_fin: CumulsYTD
    """Cumuls YTD après application de cette paie (Req 4.13). Doit être
    rattaché au même employé et à la même année (Req 4.6, vérifié par
    :meth:`_cumuls_fin_coherents`)."""

    # ------------------------------------------------------------------
    # Cycle de vie (Req 6.1, 6.3-6.5, 6.7)
    # ------------------------------------------------------------------

    statut: StatutDePaie
    """État de la paie dans le cycle immuabilité / annulation-remplacement
    (Req 6.1). Voir :class:`StatutDePaie` pour la sémantique des quatre
    valeurs."""

    remplace_par_id: str | None = None
    """Identifiant de la paie remplaçante lorsque ``statut ==
    REMPLACE_PAR`` (Req 6.3, 6.4). ``None`` ou chaîne vide interdits
    en ``REMPLACE_PAR`` ; obligatoirement absents pour les autres
    statuts (Req 6.5). La chaîne ``""`` est traitée comme ``None`` via
    truthiness (test
    ``test_remplace_par_id_vide_traite_comme_absent``)."""

    date_creation: datetime
    """Date de création (première insertion) de la paie. Toujours
    renseignée, y compris en ``BROUILLON``."""

    date_emission: datetime | None = None
    """Date d'émission officielle de la paie. Requise dès que ``statut
    ∈ {EMISE, ANNULEE, REMPLACE_PAR}`` (Req 6.7). Optionnelle en
    ``BROUILLON`` (implication unidirectionnelle)."""

    # ------------------------------------------------------------------
    # Refus universel de ``float`` sur les champs ``Decimal`` scalaires
    # (règle 01, Req 10.1). Les sous-modèles (``gains``,
    # ``retenues_employe``, ``cotisations_employeur``, ``cumuls_fin``,
    # ``pay_period``) portent leurs propres gardes ``reject_float``
    # transitivement.
    # ------------------------------------------------------------------
    @field_validator("net", "cout_employeur", mode="before")
    @classmethod
    def _rejeter_float(cls, v: Any) -> Any:
        """Délègue à :func:`reject_float` (règle 01, Req 10.1)."""
        return reject_float(v)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des 2 ``Decimal`` scalaires
    # (Req 13.1, 13.4). Les sous-modèles composites (``gains``,
    # ``retenues_employe``, ``cotisations_employeur``, ``cumuls_fin``,
    # ``pay_period``) portent leurs propres sérialiseurs transitivement.
    #
    # ``when_used="json"`` : la conversion en chaîne guillemée s'applique
    # UNIQUEMENT à la sortie JSON. Cette convention est indispensable
    # pour la contrainte (c) de Property 6 : aucun ``Decimal`` ne doit
    # apparaître comme littéral flottant non guillemé dans la chaîne
    # JSON produite (règle 01, Req 13.4).
    # ------------------------------------------------------------------
    @field_serializer("net", "cout_employeur", when_used="json")
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque champ ``Decimal`` scalaire en chaîne guillemée (règle 01)."""
        return str(v)

    # ==================================================================
    # Parseur JSON personnalisé — reroute par ``_parse_json_reject_floats``
    # ==================================================================
    #
    # Surcharge de ``model_validate_json`` pour interdire tout littéral
    # flottant non guillemé dans la chaîne JSON entrante (règle 01,
    # Req 13.5). Point d'entrée typique : un ``PayrollResult`` sérialisé
    # sur disque (ex. fixture ``tests/fixtures/outputs/qc0XX.json``,
    # spec ``moteur-paie-contrats`` tâche 14.2) est refusé fail-fast si
    # un littéral non guillemé y a été introduit — la précision fiscale
    # est préservée bout à bout, même après édition manuelle.
    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        context: Any = None,
    ) -> "PayrollResult":
        """Parse un :class:`PayrollResult` depuis JSON sans passer par ``float``.

        La chaîne JSON est décodée via
        :func:`models._validators._parse_json_reject_floats`, qui refuse
        tout littéral numérique non guillemé contenant un point décimal
        ou une notation scientifique. Le dictionnaire résultant est
        ensuite passé à ``model_validate`` pour bénéficier des
        validateurs de champ standard et des trois invariants
        d'identité/biconditionnelle/cohérence des cumuls
        (Req 4.9, 4.10, 6.3–6.5, 6.7, 4.6).
        """
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode("utf-8")
        donnees = _parse_json_reject_floats(json_data)
        return cls.model_validate(donnees, strict=strict, context=context)

    # ==================================================================
    # Invariants de cohérence (ordre significatif — Pydantic v2 exécute
    # les ``model_validator(mode="after")`` dans l'ordre de déclaration).
    # ==================================================================

    # ------------------------------------------------------------------
    # 1. Identités comptables (Req 4.9, 4.10)
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _identites_comptables(self) -> "PayrollResult":
        """Req 4.9, 4.10 — identités brute et coût employeur."""
        # Identité brute (Req 4.9) : net + total_retenues == brut.
        somme_brute = self.net + self.retenues_employe.total_retenues_employe
        if somme_brute != self.gains.brut_total:
            raise ValueError(
                "Identité brute rompue (Req 4.9) : "
                f"net ({self.net}) + total_retenues_employe "
                f"({self.retenues_employe.total_retenues_employe}) "
                f"= {somme_brute} ≠ brut_total ({self.gains.brut_total})."
            )
        # Identité coût employeur (Req 4.10) : cout = brut + total_cotisations.
        cout_attendu = (
            self.gains.brut_total
            + self.cotisations_employeur.total_cotisations_employeur
        )
        if self.cout_employeur != cout_attendu:
            raise ValueError(
                "Identité coût employeur rompue (Req 4.10) : "
                f"cout_employeur ({self.cout_employeur}) ≠ brut_total "
                f"({self.gains.brut_total}) + total_cotisations_employeur "
                f"({self.cotisations_employeur.total_cotisations_employeur}) "
                f"= {cout_attendu}."
            )
        return self

    # ------------------------------------------------------------------
    # 2. Biconditionnelle statut ⟺ remplace_par_id ⟺ date_emission
    #    (Req 6.3, 6.4, 6.5, 6.7)
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _statut_et_remplacement_coherents(self) -> "PayrollResult":
        """Req 6.3-6.5, 6.7 — biconditionnelle statut / remplace_par_id / date_emission.

        Table de vérité (voir ``_COMBINAISONS_PROPERTY_11`` dans
        ``tests/models/test_payroll_result.py``) :

        - ``REMPLACE_PAR`` ⟺ ``remplace_par_id`` renseigné (non-``None``
          et non-vide, évaluation par truthiness) ;
        - Autres statuts (``BROUILLON``, ``EMISE``, ``ANNULEE``) :
          ``remplace_par_id`` interdit ;
        - ``EMISE``, ``ANNULEE``, ``REMPLACE_PAR`` : ``date_emission``
          requise (implication unidirectionnelle, aucune contrainte en
          ``BROUILLON``).
        """
        # Biconditionnelle statut ⟺ remplace_par_id (Req 6.3, 6.4, 6.5).
        # ``if not self.remplace_par_id`` : truthiness — traite ``""``
        # comme ``None`` (test
        # ``test_remplace_par_id_vide_traite_comme_absent``).
        remplace_par_id_present = bool(self.remplace_par_id)
        if self.statut is StatutDePaie.REMPLACE_PAR:
            if not remplace_par_id_present:
                raise ValueError(
                    "statut=REMPLACE_PAR exige remplace_par_id non vide "
                    "(Req 6.3, 6.4)."
                )
        else:
            if remplace_par_id_present:
                raise ValueError(
                    f"remplace_par_id ne doit pas être renseigné quand "
                    f"statut={self.statut.value} (Req 6.5). "
                    "Seul le statut REMPLACE_PAR autorise ce champ."
                )
        # Implication statut ∈ {EMISE, ANNULEE, REMPLACE_PAR} ⟹
        # date_emission renseignée (Req 6.7).
        if self.statut in (
            StatutDePaie.EMISE,
            StatutDePaie.ANNULEE,
            StatutDePaie.REMPLACE_PAR,
        ):
            if self.date_emission is None:
                raise ValueError(
                    f"date_emission doit être renseignée quand "
                    f"statut={self.statut.value} (Req 6.7)."
                )
        return self

    # ------------------------------------------------------------------
    # 3. Cohérence ``cumuls_fin`` (Req 4.6)
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _cumuls_fin_coherents(self) -> "PayrollResult":
        """Req 4.6 — ``cumuls_fin`` rattaché au bon employé et à la bonne année."""
        if self.cumuls_fin.employe_id != self.employe_id:
            raise ValueError(
                f"cumuls_fin.employe_id ({self.cumuls_fin.employe_id!r}) "
                f"doit correspondre à employe_id ({self.employe_id!r}) "
                "(Req 4.6)."
            )
        if self.cumuls_fin.annee_civile != self.annee_fiscale:
            raise ValueError(
                f"cumuls_fin.annee_civile ({self.cumuls_fin.annee_civile}) "
                f"doit correspondre à annee_fiscale ({self.annee_fiscale}) "
                "(Req 4.6)."
            )
        return self
