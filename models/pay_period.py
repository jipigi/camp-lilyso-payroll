"""Modèles ``WeekSegment`` et ``PayPeriod`` — période de paie et semaines constituantes.

Spec de référence : ``moteur-paie-contrats`` — tâches 7.2 et 7.3.
Design de référence : section « Components and Interfaces » §6 et
« Data Models » §6 (``design.md``).

Ce module expose deux modèles Pydantic v2 immuables :

- :class:`WeekSegment` — une semaine constituante d'une période de paie.
  Champs : ``date_debut``, ``date_fin``, ``heures_normales``,
  ``heures_supplementaires`` (chaque quantité d'heures ∈ ``[0, 168]`` —
  borne physique, Normes du travail QC). Invariant post-construction :
  ``date_fin >= date_debut``.
- :class:`PayPeriod` — une période de paie décomposée en ses semaines
  constituantes. **Non implémenté par cette tâche 7.2** ; sa mise en
  place complète (validateurs ordonnés, contiguïté, couverture, refus
  hors matrice) est prise en charge par la tâche 7.3.

Requirements couverts par la tâche 7.2 :

- Req 2.3 — Chaque semaine expose ``date_debut``, ``date_fin``,
  ``heures_normales``, ``heures_supplementaires``. ``date_fin >=
  date_debut`` est appliqué par le validateur ``mode="after"``.
- Req 2.8 — Immuabilité après construction (``frozen=True``).
- Req 10.1 — Tous les montants numériques sont ``Decimal``, ``float``
  rejeté à la validation via :func:`models._validators.reject_float`
  branché en ``mode="before"``.

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit ;
- Règle 06 — TDD, tests avant code : ce module est couvert par
  ``tests/models/test_pay_period.py`` (tâche 7.1) écrit **avant** cette
  implémentation.
"""

from __future__ import annotations

from datetime import date, timedelta
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

from models._validators import reject_float
from models.enums import FrequencePaie
from models.exceptions import UnsupportedPayrollCase


class WeekSegment(BaseModel):
    """Une semaine constituante d'une période de paie (design §6).

    Modèle Pydantic v2 immuable (``frozen=True``) qui refuse tout champ
    inconnu (``extra="forbid"``). Les deux quantités d'heures sont bornées
    à l'intervalle ``[0, 168]`` : la borne inférieure exclut toute valeur
    négative (Req 2.3, une durée n'est jamais négative), la borne
    supérieure est une borne physique (168 h = 7 jours × 24 h, Normes du
    travail QC). Toute valeur hors plage est rejetée par Pydantic via
    les contraintes ``ge`` / ``le`` du champ.

    L'invariant croisé ``date_fin >= date_debut`` est appliqué par le
    validateur ``_verifier_ordre_des_dates`` en ``mode="after"``. L'égalité
    est autorisée : une « semaine » réduite à une seule journée est un
    cas dégénéré rare mais admis (par exemple, ajustement de fin d'année
    fiscale).

    ``float`` est refusé à la validation via
    :func:`models._validators.reject_float` branché en ``mode="before"``
    sur les deux champs ``Decimal`` (règle 01, Req 10.1). Un ``float``
    natif serait sinon converti silencieusement en ``Decimal`` par
    Pydantic, ce qui introduirait des erreurs binaires incompatibles avec
    les golden tests WebRAS/PDOC.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    date_debut: date
    date_fin: date
    heures_normales: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("168"),
    )
    heures_supplementaires: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("168"),
    )

    # ------------------------------------------------------------------
    # Rejet transverse de ``float`` (règle 01, Req 10.1)
    # ------------------------------------------------------------------
    #
    # Installé en ``mode="before"`` pour intercepter la valeur brute
    # **avant** que Pydantic n'applique les contraintes ``ge`` / ``le``
    # ou la coercition ``Decimal``. Ce placement est crucial :
    # ``Decimal(0.1) < Decimal("168")`` retournerait ``True`` alors que
    # la valeur d'origine était un ``float`` — sans ce validateur, la
    # fuite passerait inaperçue.
    @field_validator(
        "heures_normales",
        "heures_supplementaires",
        mode="before",
    )
    @classmethod
    def _refuser_float(cls, value: Any) -> Any:
        """Refuse ``float`` et ``Decimal`` pollué par ``float``.

        Voir :func:`models._validators.reject_float` pour le détail des
        cas d'acceptation et de refus (règle 01, Req 10.1).
        """
        return reject_float(value)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des ``Decimal`` (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    #
    # ``when_used="json"`` : la conversion en chaîne guillemée s'applique
    # UNIQUEMENT à la sortie JSON (``model_dump_json``), pas à
    # ``model_dump`` (dict Python) qui conserve les ``Decimal``. Cette
    # discipline garantit que la chaîne JSON produite ne contient jamais
    # de littéral flottant non guillemé (contrainte (c) de Property 6,
    # Req 13.4) — un round-trip via ``_parse_json_reject_floats`` est
    # alors possible sans passer par ``float`` (règle 01).
    @field_serializer(
        "heures_normales",
        "heures_supplementaires",
        when_used="json",
    )
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque champ ``Decimal`` en chaîne guillemée (règle 01)."""
        return str(v)

    # ------------------------------------------------------------------
    # Invariant croisé sur les dates (Req 2.3, design §6)
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _verifier_ordre_des_dates(self) -> "WeekSegment":
        """``date_fin >= date_debut`` — Req 2.3 (design §6).

        L'égalité est autorisée (semaine dégénérée d'une seule journée).
        Une ``date_fin`` strictement antérieure à ``date_debut`` est un
        cas incohérent qui doit être rejeté à la construction pour
        éviter de propager une durée négative dans les modules aval.
        """
        if self.date_fin < self.date_debut:
            raise ValueError(
                "`date_fin` doit être postérieure ou égale à `date_debut` "
                f"(Req 2.3). Reçu : date_debut={self.date_debut.isoformat()}, "
                f"date_fin={self.date_fin.isoformat()}."
            )
        return self


# ---------------------------------------------------------------------------
# Valeurs valides connues de ``FrequencePaie`` — pré-calcul pour ``mode="before"``
# ---------------------------------------------------------------------------
#
# Ce ``frozenset`` matérialise l'ensemble des chaînes que Pydantic peut
# coercer en :class:`FrequencePaie` sans lever d'erreur. Il est pré-calculé
# au chargement du module pour éviter le coût d'un ``{f.value for f in
# FrequencePaie}`` à chaque construction de :class:`PayPeriod`. Toute chaîne
# hors de cet ensemble est refusée par ``_refuser_frequence_hors_matrice_before``
# avec :class:`UnsupportedPayrollCase` avant que Pydantic n'appelle
# ``FrequencePaie(...)``.
_FREQUENCES_CONNUES: frozenset[str] = frozenset(f.value for f in FrequencePaie)


class PayPeriod(BaseModel):
    """Période de paie décomposée en ses semaines constituantes (design §6).

    Modèle Pydantic v2 immuable (``frozen=True``) qui refuse tout champ
    inconnu (``extra="forbid"``). Représente une fenêtre de paie bornée
    par ``date_debut`` et ``date_fin`` et décomposée en ``semaines`` —
    exactement deux ``WeekSegment`` pour la fréquence
    ``AUX_DEUX_SEMAINES``, seule fréquence supportée par le Camp LilySO
    (règle 03, Req 11.2).

    ``nb_periodes_annuelles`` est fourni **à la construction** par
    l'appelant (typiquement lu depuis ``parameters/<AAAA>/quebec.json``
    par ``load_parameters``). Le modèle ne dépend PAS de
    ``load_parameters`` (design §Composant 6.2 / AC7 du Req 2) : la
    séparation évite un cycle d'imports et rend le modèle testable en
    isolation.

    Ordre STRICT des validateurs (design §6, AC4/AC5 du Req 2) :

    1. :meth:`_refuser_frequence_hors_matrice_before` — ``field_validator``
       en ``mode="before"`` sur ``frequence`` : intercepte toute chaîne
       non reconnue **avant** la coercition ``FrequencePaie(...)`` et
       lève :class:`UnsupportedPayrollCase` avec un message citant la
       règle 03 et les outils officiels de repli (WebRAS et PDOC,
       Req 11.6). Sans ce garde-fou, Pydantic lèverait une
       ``ValidationError`` de coercition d'énumération, faisant perdre
       le contrat de refus métier attendu (Req 8.7).
    2. :meth:`_refuser_frequence_hors_matrice` — ``model_validator`` en
       ``mode="after"``, défense en profondeur : si un jour
       :class:`FrequencePaie` s'enrichit d'autres valeurs (« hebdomadaire »,
       « mensuelle »), cette garde continue à rejeter les cas hors
       matrice sans dépendre du seul mécanisme de coercition.
    3. :meth:`_nombre_semaines_correspond_a_frequence` —
       ``model_validator`` en ``mode="after"`` : exige exactement 2
       ``WeekSegment`` pour ``AUX_DEUX_SEMAINES`` (Req 2 AC2).
    4. :meth:`_semaines_contigues_et_couvrantes` — ``model_validator``
       en ``mode="after"`` : vérifie la contiguïté et la couverture
       exacte. **Court-circuité** si ``len(semaines) != 2`` (Req 2
       AC4/AC5 : « la vérification NE DOIT PAS être évaluée lorsque
       le nombre de semaines constituantes ne satisfait pas l'AC2 »).

    En Pydantic v2, les ``model_validator(mode="after")`` sont exécutés
    dans l'ordre de déclaration dans la classe. L'ordre 2 → 3 → 4
    ci-dessus est donc matérialisé par l'ordre des définitions plus bas.

    Discipline exception : les validateurs qui rejettent un cas hors
    matrice lèvent :class:`UnsupportedPayrollCase` (dérivé de
    :class:`Exception` via :class:`PayrollDomainError`). Pydantic v2
    n'enveloppe pas cette exception dans ``ValidationError`` — elle
    remonte telle quelle au consommateur (Req 8.7, design §Components 2).
    Les validateurs qui rejettent une incohérence de forme (nombre de
    semaines incorrect, contiguïté brisée, couverture incomplète) lèvent
    :class:`ValueError`, qui est enveloppée dans une ``ValidationError``
    Pydantic.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    # ------------------------------------------------------------------
    # Champs (design §6)
    # ------------------------------------------------------------------

    numero_periode: int = Field(..., ge=1, le=27)
    """Numéro séquentiel de la période dans l'année fiscale, ``[1, 27]``.
    La borne supérieure inclut le cas d'une année à 27 paies bi-hebdomadaires
    (rare, arrive typiquement une fois par décennie — 2026 par exemple).
    """

    date_debut: date
    """Date inclusive de début de la période de paie."""

    date_fin: date
    """Date inclusive de fin de la période de paie. Contigüité avec les
    semaines constituantes contrôlée par
    :meth:`_semaines_contigues_et_couvrantes`."""

    date_paiement: date
    """Date de versement effectif du salaire (typiquement quelques jours
    après ``date_fin``). Aucun invariant temporel n'est imposé au niveau
    du modèle ; la cohérence de calendrier reste sous la responsabilité
    de l'appelant."""

    frequence: FrequencePaie
    """Fréquence de paie. Seule :attr:`FrequencePaie.AUX_DEUX_SEMAINES`
    est admise (règle 03, Req 11.2). Toute autre valeur — y compris
    fournie sous forme de chaîne — est refusée par
    :meth:`_refuser_frequence_hors_matrice_before` avec
    :class:`UnsupportedPayrollCase`."""

    nb_periodes_annuelles: int = Field(..., ge=1, le=53)
    """Nombre de périodes de paie sur l'année fiscale, ``[1, 53]``.
    Valeurs typiques Camp LilySO : ``26`` (année standard) ou ``27``
    (année à 27 paies bi-hebdomadaires, comme 2026). La borne supérieure
    couvre les cas dégénérés hebdomadaires (52 ou 53 paies) que le
    contrat ne supporte pas fonctionnellement mais autorise à la
    construction — le refus hors matrice est porté par
    :meth:`_refuser_frequence_hors_matrice`. Fourni par l'appelant
    (typiquement ``load_parameters``), le modèle ne le calcule pas."""

    annee_fiscale: int = Field(..., ge=2000, le=2100)
    """Année fiscale de rattachement de la période."""

    semaines: tuple[WeekSegment, ...]
    """Semaines constituantes de la période. Exactement deux pour
    ``AUX_DEUX_SEMAINES`` (Req 2 AC2). L'ordre est significatif :
    ``semaines[0]`` couvre la première semaine, ``semaines[-1]`` la
    dernière. La contiguïté (``semaines[i+1].date_debut ==
    semaines[i].date_fin + 1 jour``) et la couverture exacte
    (``semaines[0].date_debut == date_debut`` et
    ``semaines[-1].date_fin == date_fin``) sont vérifiées par
    :meth:`_semaines_contigues_et_couvrantes`."""

    # =====================================================================
    # Validateurs
    # =====================================================================

    # ------------------------------------------------------------------
    # 1. Refus hors matrice AVANT coercition d'énumération
    # ------------------------------------------------------------------
    #
    # ``FrequencePaie`` n'expose actuellement qu'une seule valeur
    # (``AUX_DEUX_SEMAINES``, règle 03). Si l'appelant passe une chaîne
    # non reconnue (« hebdomadaire », « mensuelle », ...), Pydantic tenterait
    # de la coercer en ``FrequencePaie`` et lèverait une ``ValidationError``
    # de coercition — perdant ainsi le contrat métier « cas hors matrice →
    # ``UnsupportedPayrollCase`` » (Req 11.2, Property 16). Ce validateur
    # ``mode="before"`` intercepte ces chaînes AVANT que Pydantic n'appelle
    # ``FrequencePaie(...)`` et lève l'exception métier attendue.
    @field_validator("frequence", mode="before")
    @classmethod
    def _refuser_frequence_hors_matrice_before(cls, value: Any) -> Any:
        """Intercepte les chaînes hors matrice avant coercition d'énumération.

        Cas d'acceptation :

        - :class:`FrequencePaie` déjà construite → transmis tel quel ;
        - chaîne dont la valeur correspond à un ``FrequencePaie.value``
          (actuellement le seul cas est ``"aux_deux_semaines"``) →
          transmis tel quel (Pydantic coercera ensuite en enum) ;
        - autre type (``None``, ``int``, ...) → transmis tel quel,
          Pydantic gérera le rejet de forme via ``ValidationError``.

        Cas de refus :

        - chaîne inconnue → :class:`UnsupportedPayrollCase` avec message
          citant la règle 03 et les outils officiels (WebRAS, PDOC).
        """
        if isinstance(value, FrequencePaie):
            return value
        if isinstance(value, str) and value not in _FREQUENCES_CONNUES:
            raise UnsupportedPayrollCase(
                f"Fréquence de paie '{value}' non supportée (règle 03). "
                "Le Camp LilySO fonctionne aux deux semaines uniquement. "
                "Pour un cas exceptionnel, utiliser WebRAS "
                "(revenuquebec.ca/webras) et PDOC (canada.ca/pdoc)."
            )
        return value

    # ------------------------------------------------------------------
    # 2. Refus hors matrice APRÈS coercition — défense en profondeur
    # ------------------------------------------------------------------
    #
    # Redondant tant que ``FrequencePaie`` n'a qu'une seule valeur, mais
    # indispensable pour maintenir le contrat si l'énumération devait
    # s'enrichir (ex. ajout futur de ``HEBDOMADAIRE`` dans une version
    # spéculative — cette garde continuerait à rejeter la fréquence hors
    # matrice au niveau du ``PayPeriod`` sans nécessiter de modification).
    @model_validator(mode="after")
    def _refuser_frequence_hors_matrice(self) -> "PayPeriod":
        """Rejette toute fréquence différente de ``AUX_DEUX_SEMAINES``.

        Discipline exception : lève :class:`UnsupportedPayrollCase`
        (dérivée de :class:`Exception`), non enveloppée par Pydantic v2
        (Req 8.7, design §Components 2).
        """
        if self.frequence is not FrequencePaie.AUX_DEUX_SEMAINES:
            raise UnsupportedPayrollCase(
                f"Fréquence de paie '{self.frequence}' non supportée "
                "(règle 03). Le Camp LilySO fonctionne aux deux semaines "
                "uniquement. Pour un cas exceptionnel, utiliser WebRAS "
                "(revenuquebec.ca/webras) et PDOC (canada.ca/pdoc)."
            )
        return self

    # ------------------------------------------------------------------
    # 3. Nombre correct de semaines constituantes (Req 2 AC2)
    # ------------------------------------------------------------------
    #
    # Doit être déclaré AVANT ``_semaines_contigues_et_couvrantes`` : en
    # Pydantic v2, les ``model_validator(mode="after")`` sont exécutés
    # dans l'ordre de déclaration. Une erreur de nombre doit prévaloir
    # sur une erreur de contiguïté / couverture (AC4/AC5 du Req 2 :
    # « la vérification NE DOIT PAS être évaluée lorsque le nombre de
    # semaines constituantes ne satisfait pas l'AC2 »). Le message NE
    # DOIT PAS mentionner la contiguïté ni la couverture (Property 14).
    @model_validator(mode="after")
    def _nombre_semaines_correspond_a_frequence(self) -> "PayPeriod":
        """Exige exactement 2 semaines pour ``AUX_DEUX_SEMAINES``.

        Discipline message : la formulation porte STRICTEMENT sur le
        nombre de semaines, jamais sur la contiguïté ni la couverture,
        pour garantir le court-circuit AC4/AC5 vérifié par Property 14.
        """
        if (
            self.frequence is FrequencePaie.AUX_DEUX_SEMAINES
            and len(self.semaines) != 2
        ):
            raise ValueError(
                "PayPeriod aux_deux_semaines doit contenir exactement 2 "
                f"semaines constituantes, reçu {len(self.semaines)} (Req 2 AC2)."
            )
        return self

    # ------------------------------------------------------------------
    # 4. Contiguïté et couverture exacte (Req 2 AC4, AC5)
    # ------------------------------------------------------------------
    #
    # Court-circuité si ``len(semaines) != 2`` : la validation précédente
    # a déjà signalé l'erreur de nombre, et le contrat AC4/AC5 exige
    # explicitement que ces invariants ne soient PAS évalués dans ce cas
    # (Req 2). Ce court-circuit interne est indispensable pour Property 14 :
    # sans lui, une ``ValidationError`` Pydantic accumulerait les erreurs
    # des deux validateurs, faisant fuiter les mots-clés ``contigu`` /
    # ``couvr`` / ``chevauch`` dans le message pour des cas ``n != 2``.
    @model_validator(mode="after")
    def _semaines_contigues_et_couvrantes(self) -> "PayPeriod":
        """Vérifie la contiguïté et la couverture exacte des semaines.

        Applicable uniquement quand ``len(semaines) == 2`` (fréquence
        ``AUX_DEUX_SEMAINES``). Les trois invariants sont :

        - couverture du début : ``semaines[0].date_debut ==
          self.date_debut`` (Req 2 AC5) ;
        - couverture de la fin : ``semaines[-1].date_fin ==
          self.date_fin`` (Req 2 AC5) ;
        - contiguïté / non-chevauchement : ``semaines[1].date_debut ==
          semaines[0].date_fin + 1 jour`` (Req 2 AC4).

        Toute violation lève :class:`ValueError` (enveloppée par Pydantic
        en :class:`pydantic.ValidationError`) avec un message citant la
        nature de l'écart (contiguïté ou couverture).
        """
        # Court-circuit AC4/AC5 : si le nombre n'est pas correct, la
        # validation précédente a déjà rejeté la construction ; ce
        # validateur NE DOIT PAS ajouter d'erreur de contiguïté /
        # couverture (Property 14).
        if len(self.semaines) != 2:
            return self

        premiere, derniere = self.semaines

        if premiere.date_debut != self.date_debut:
            raise ValueError(
                "La première semaine constituante doit débuter à "
                f"``date_debut`` de la période (Req 2 AC5 — couverture). "
                f"Reçu : semaines[0].date_debut="
                f"{premiere.date_debut.isoformat()}, "
                f"date_debut={self.date_debut.isoformat()}."
            )
        if derniere.date_fin != self.date_fin:
            raise ValueError(
                "La dernière semaine constituante doit se terminer à "
                f"``date_fin`` de la période (Req 2 AC5 — couverture). "
                f"Reçu : semaines[-1].date_fin={derniere.date_fin.isoformat()}, "
                f"date_fin={self.date_fin.isoformat()}."
            )
        if derniere.date_debut != premiere.date_fin + timedelta(days=1):
            raise ValueError(
                "Les semaines constituantes doivent être contiguës et "
                "non chevauchantes (Req 2 AC4). "
                f"Reçu : semaines[0].date_fin={premiere.date_fin.isoformat()}, "
                f"semaines[1].date_debut={derniere.date_debut.isoformat()} "
                "(attendu : semaines[0].date_fin + 1 jour)."
            )
        return self
