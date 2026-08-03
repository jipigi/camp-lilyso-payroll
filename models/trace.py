"""Modèle ``CalculationTrace`` — trace exhaustive d'un calcul fiscal.

Spec de référence : ``moteur-paie-contrats`` — tâche 5.2.
Design de référence : sections « Components and Interfaces » §4 et
« Data Models » §3 (``design.md``).

Cette classe fixe le contrat de trace exigé par la **règle 02**
(``.kiro/steering/02-tracabilite-formules.md``) et par le Requirement 5 :
chaque fonction de calcul fiscal future du moteur retournera
``tuple[Decimal, CalculationTrace]`` où la trace documente la source
officielle, l'année, la section, les paramètres utilisés, les entrées,
les sous-totaux nommés, le mode et la précision d'arrondissement, et le
résultat final. Toute paie doit pouvoir être auditée trois ans après son
émission à partir de sa seule trace, sans réexécuter le moteur.

Contraintes structurantes :

- Pydantic v2 avec ``frozen=True`` (immuabilité, Req 5.4) et
  ``extra="forbid"`` (rejet des champs inconnus, cohérent avec le reste du
  domaine).
- ``str_strip_whitespace=True`` sur les champs chaînes (``source``,
  ``section``) : les blancs de bordure sont supprimés avant toute
  validation, ce qui rend la comparaison à la liste blanche déterministe.
- Liste blanche stricte des sources officielles (Req 5.2, règle 02) :
  formulaires ``TP-1015.F``, ``TP-1015.G``, ``TP-1015.3``, ``T4127``,
  ``TD1``, ``Guide de l'employeur ARC``, ``LE-39.0.2`` (cotisation CNT,
  ajouté par la spec ``charges-patronales``, extension additive), ou URL
  sur ``.gouv.qc.ca`` / ``.canada.ca``. Toute autre source est refusée
  avec un message renvoyant explicitement à la règle 02.
- Rejet universel de ``float`` sur tous les champs ``Decimal`` (règle 01,
  Req 5.3) via ``field_validator(..., mode="before")`` délégué à
  :func:`models._validators.reject_float`. Pour les champs ``dict[str,
  Decimal]``, la validation itère sur les valeurs.
- Sérialisation JSON déterministe : chaque ``Decimal`` est encodé en
  **chaîne guillemée** via ``field_serializer`` (prépare Property 6 du
  design — round-trip JSON déterministe).
- ``model_validate_json`` est **surchargé** pour rerouter le parsing par
  :func:`models._validators._parse_json_reject_floats`, qui refuse tout
  littéral flottant non guillemé (règle 01 + Req 13.5).
- ``__str__`` produit une représentation textuelle ordonnée (Req 5.6) :
  source, année, section, paramètres, entrées, sous-totaux, arrondissement
  (mode + précision), résultat.

Requirements couverts : 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 5.8.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from models._validators import _parse_json_reject_floats, reject_float
from models.enums import Juridiction, ModeArrondissement

# ---------------------------------------------------------------------------
# Liste blanche des sources officielles (design §Components 4, Req 5.2)
# ---------------------------------------------------------------------------
#
# L'ordre est celui du design ; il n'a pas d'impact fonctionnel (chaque
# regex est testée indépendamment) mais facilite la traçabilité entre le
# document et le code.

_SOURCES_OFFICIELLES_REGEX: tuple[str, ...] = (
    r"^TP-1015\.F \d{4}(, section .+)?$",
    r"^TP-1015\.G \d{4}(, section .+)?$",
    r"^TP-1015\.3 \d{4}(, section .+)?$",
    r"^T4127 \d{4}(, section .+)?$",
    r"^TD1 \d{4}(, section .+)?$",
    r"^Guide de l'employeur ARC \d{4}(, section .+)?$",
    # NOUVEAU (spec ``charges-patronales``, tâche 8.1) — cotisation CNT.
    # Formulaire LE-39.0.2 « Déclaration pour la cotisation des normes du
    # travail » (Revenu Québec). Extension STRICTEMENT ADDITIVE : aucun
    # motif existant n'est retiré ni modifié (Req 5.7, Req 12.3, règle 02).
    r"^LE-39\.0\.2 \d{4}(, .+)?$",
    r"^https?://[a-z0-9\-\.]+\.gouv\.qc\.ca/.+$",
    r"^https?://[a-z0-9\-\.]+\.canada\.ca/.+$",
)

#: Motifs pré-compilés une seule fois pour éviter le coût de compilation
#: à chaque validation. Le module est chargé une fois ; les regex sont
#: recompilées à chaque import mais pas à chaque construction d'instance.
_SOURCES_OFFICIELLES_MATCHERS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(motif) for motif in _SOURCES_OFFICIELLES_REGEX
)


def _source_est_officielle(source: str) -> bool:
    """``True`` si ``source`` matche l'une des regex de la liste blanche."""
    return any(matcher.match(source) for matcher in _SOURCES_OFFICIELLES_MATCHERS)


class CalculationTrace(BaseModel):
    """Trace exhaustive d'un calcul fiscal (Req 5, règle 02).

    Cette classe est le **type de retour de trace** de toutes les fonctions
    de calcul fiscal du moteur (Req 5.8). Sa signature est fixée par la
    spec ``moteur-paie-contrats`` et ne pourra pas être modifiée par les
    specs ultérieures des modules de calcul (RRQ, RQAP, AE, impôt QC,
    impôt fédéral, charges patronales).

    Champs (Req 5.1) :

    - ``source`` : référence officielle exacte, validée contre la liste
      blanche (Req 5.2, règle 02).
    - ``annee`` : année d'application des paramètres, dans
      ``[2000, 2100]``.
    - ``juridiction`` : ``quebec`` ou ``canada``.
    - ``section`` : sous-section du document officiel (chaîne non vide).
    - ``parametres_utilises`` : dictionnaire ``str → Decimal`` des taux,
      plafonds, exemptions consommés par le calcul. Ordre d'insertion
      préservé (Python 3.7+, Req 5.5).
    - ``entrees`` : dictionnaire ``str → Decimal`` des valeurs d'entrée
      reçues par la fonction de calcul.
    - ``sous_totaux`` : dictionnaire ``str → Decimal`` des étapes
      intermédiaires nommées, dans l'ordre d'exécution (Req 5.5).
    - ``mode_arrondissement`` : mode ``decimal`` appliqué (miroir strict
      des constantes ``decimal.ROUND_*``).
    - ``precision_arrondissement`` : nombre de décimales conservées, dans
      ``[0, 10]``.
    - ``resultat`` : montant final en ``Decimal``.
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2
    # ------------------------------------------------------------------
    #
    # - ``frozen=True`` : immuabilité stricte après construction (Req 5.4).
    # - ``extra="forbid"`` : rejet des champs inconnus. Cohérent avec le
    #   reste du domaine et empêche l'accumulation silencieuse de champs
    #   non spécifiés.
    # - ``str_strip_whitespace=True`` : les blancs de bordure sont
    #   supprimés avant validation. Cela rend la comparaison à la liste
    #   blanche déterministe et évite qu'un espace fantôme fasse échouer
    #   une source légitime.
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    # Ordre déclaré ci-dessous = ordre exposé par ``__str__`` (Req 5.6),
    # complété par juridiction et precision_arrondissement (métadonnées
    # exposées mais non listées dans l'ordre imposé par la spec).
    source: str = Field(..., min_length=1)
    annee: int = Field(..., ge=2000, le=2100)
    juridiction: Juridiction
    section: str = Field(..., min_length=1)
    parametres_utilises: dict[str, Decimal] = Field(default_factory=dict)
    entrees: dict[str, Decimal] = Field(default_factory=dict)
    sous_totaux: dict[str, Decimal] = Field(default_factory=dict)
    mode_arrondissement: ModeArrondissement
    precision_arrondissement: int = Field(..., ge=0, le=10)
    resultat: Decimal

    # ------------------------------------------------------------------
    # Ordre des sections de la représentation textuelle (Req 5.6).
    #
    # Défini comme ClassVar pour rester introspectable, tout en étant
    # exclu du contrat Pydantic (aucun impact sur la validation ni sur
    # la sérialisation). Utilisé par ``__str__``.
    # ------------------------------------------------------------------
    _ORDRE_STR: ClassVar[tuple[str, ...]] = (
        "source",
        "annee",
        "section",
        "parametres_utilises",
        "entrees",
        "sous_totaux",
        "mode_arrondissement",
        "precision_arrondissement",
        "resultat",
    )

    # ------------------------------------------------------------------
    # Validation de la source contre la liste blanche (Req 5.2, règle 02)
    # ------------------------------------------------------------------
    @field_validator("source")
    @classmethod
    def _valider_source_officielle(cls, v: str) -> str:
        """Refuse toute source hors liste blanche.

        La comparaison se fait sur la valeur **après** stripping (config
        ``str_strip_whitespace=True``), donc les blancs de bordure ne
        peuvent pas masquer un motif non conforme. Le message d'erreur
        renvoie explicitement à la règle 02 pour permettre à l'auditeur
        de comprendre pourquoi la source est refusée.
        """
        if _source_est_officielle(v):
            return v
        raise ValueError(
            f"Source non officielle refusée (règle 02) : {v!r}. "
            "Les seules sources autorisées sont TP-1015.F, TP-1015.G, "
            "TP-1015.3, T4127, TD1, le guide de l'employeur ARC, LE-39.0.2, "
            "ou une URL sur `.gouv.qc.ca` / `.canada.ca`. "
            "Voir `.kiro/steering/02-tracabilite-formules.md` (règle 02) "
            "pour la liste complète des documents officiels admissibles."
        )

    # ------------------------------------------------------------------
    # Refus universel de ``float`` sur les champs ``Decimal`` (règle 01,
    # Req 5.3). Le validateur s'applique en ``mode="before"`` à tous les
    # champs porteurs de ``Decimal`` : ``resultat`` (scalaire) et les
    # trois dictionnaires ``dict[str, Decimal]``. Pour les dicts, on
    # itère sur les valeurs et on applique ``reject_float`` à chacune ;
    # les clés (typées ``str``) ne sont pas touchées.
    # ------------------------------------------------------------------
    @field_validator(
        "parametres_utilises",
        "entrees",
        "sous_totaux",
        "resultat",
        mode="before",
    )
    @classmethod
    def _rejeter_float(cls, v: Any) -> Any:
        """Délègue à ``reject_float`` valeur par valeur (règle 01, Req 5.3).

        - Pour un ``dict`` (les champs ``parametres_utilises``, ``entrees``,
          ``sous_totaux``), on parcourt les valeurs et on applique
          ``reject_float`` à chacune. Les clés (chaînes) ne sont pas
          modifiées.
        - Pour un scalaire (le champ ``resultat``), on applique directement
          ``reject_float``.
        - Les autres types (``None``, ``list``, etc.) sont laissés à
          Pydantic, qui les rejettera sur la base du typage annoté.

        ``reject_float`` accepte : ``int``, ``str`` conforme au format
        décimal, ``Decimal`` fini à précision raisonnable. Il refuse :
        tout ``float``, ``Decimal`` non fini ou à précision aberrante,
        chaîne en notation scientifique ou avec des caractères parasites.
        """
        if isinstance(v, dict):
            return {cle: reject_float(valeur) for cle, valeur in v.items()}
        return reject_float(v)

    # ------------------------------------------------------------------
    # Sérialiseurs Decimal → str (prépare Property 6 — round-trip JSON)
    # ------------------------------------------------------------------
    #
    # ``when_used="json"`` : la conversion en chaîne guillemée s'applique
    # uniquement à la sortie JSON (``model_dump_json``), pas à
    # ``model_dump`` (dict Python) qui conserve les ``Decimal``.
    # Bénéfice : le JSON ne contient jamais de littéral flottant non
    # guillemé, ce qui permet le round-trip via
    # ``_parse_json_reject_floats`` (règle 01, Req 13.5).
    @field_serializer(
        "parametres_utilises",
        "entrees",
        "sous_totaux",
        when_used="json",
    )
    def _serialiser_dict_decimal(self, v: dict[str, Decimal]) -> dict[str, str]:
        """Encode chaque valeur du dict comme chaîne, en préservant l'ordre.

        La compréhension de dictionnaire Python préserve l'ordre
        d'insertion (3.7+) : les clés apparaîtront dans le JSON dans le
        même ordre que dans l'instance, ce qui garantit la
        reproductibilité du round-trip (Req 5.5).
        """
        return {cle: str(valeur) for cle, valeur in v.items()}

    @field_serializer("resultat", when_used="json")
    def _serialiser_resultat(self, v: Decimal) -> str:
        """Encode le résultat scalaire comme chaîne guillemée en JSON."""
        return str(v)

    # ------------------------------------------------------------------
    # Parseur JSON personnalisé : reroute par ``_parse_json_reject_floats``
    # ------------------------------------------------------------------
    #
    # Surcharge de ``model_validate_json`` pour interdire tout littéral
    # flottant non guillemé dans la chaîne JSON entrante (règle 01,
    # Req 13.5). Cela garantit que le round-trip JSON de la trace ne
    # peut jamais introduire un ``float`` par mégarde, même si un
    # opérateur modifie manuellement un fichier de trace sérialisé.
    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        context: Any = None,
    ) -> "CalculationTrace":
        """Parse une trace depuis une chaîne JSON, sans passer par ``float``.

        La chaîne JSON est d'abord décodée via
        :func:`models._validators._parse_json_reject_floats`, qui refuse
        tout littéral numérique non guillemé contenant un point décimal
        (ex. ``0.063``, ``1.5``) ou une notation scientifique. Le
        dictionnaire résultant est ensuite passé à ``model_validate``
        pour bénéficier des validateurs de champ standard.
        """
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode("utf-8")
        donnees = _parse_json_reject_floats(json_data)
        return cls.model_validate(donnees, strict=strict, context=context)

    # ------------------------------------------------------------------
    # Représentation textuelle ordonnée (Req 5.6)
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        """Représentation humainement lisible de la trace (Req 5.6).

        Liste, dans l'ordre imposé par la spec : source, année, section,
        paramètres, entrées, sous-totaux, arrondissement (mode +
        précision), résultat. La juridiction est également exposée pour
        permettre à l'auditeur d'identifier immédiatement le régime
        applicable ; elle n'a pas de position imposée dans l'ordre.

        Les dictionnaires (``parametres_utilises``, ``entrees``,
        ``sous_totaux``) sont rendus dans leur ordre d'insertion. Les
        montants sont affichés via ``str(Decimal)`` afin d'éviter toute
        représentation ``float`` accidentelle dans la sortie textuelle.
        """
        # Chaque dict est rendu clé par clé pour préserver l'ordre
        # d'insertion et exposer les montants sans coercition
        # ``float`` (règle 01). ``dict.__repr__`` sur un ``Decimal``
        # produit ``Decimal('...')`` — plus verbeux mais explicite ;
        # on préfère ici un rendu ``clé=valeur`` compact.
        def _rendu_dict(nom: str, d: dict[str, Decimal]) -> str:
            if not d:
                return f"  {nom}: {{}}"
            paires = ", ".join(f"{cle}={valeur}" for cle, valeur in d.items())
            return f"  {nom}: {{{paires}}}"

        lignes = [
            "CalculationTrace:",
            f"  source: {self.source}",
            f"  annee: {self.annee}",
            f"  juridiction: {self.juridiction.value}",
            f"  section: {self.section}",
            _rendu_dict("parametres_utilises", self.parametres_utilises),
            _rendu_dict("entrees", self.entrees),
            _rendu_dict("sous_totaux", self.sous_totaux),
            f"  mode_arrondissement: {self.mode_arrondissement.value}",
            f"  precision_arrondissement: {self.precision_arrondissement}",
            f"  resultat: {self.resultat}",
        ]
        return "\n".join(lignes)
