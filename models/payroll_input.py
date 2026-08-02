"""Modèles ``HeuresParSemaine`` et ``PayrollInput`` — contrat d'entrée du moteur.

Spec de référence : ``moteur-paie-contrats`` — tâche 9.2.
Design de référence : sections « Components and Interfaces » §8 et
« Data Models » §7 (``design.md``).

Ce module expose deux modèles Pydantic v2 immuables et deux blacklists
explicites de motifs hors matrice Camp LilySO :

- :class:`HeuresParSemaine` — quantités d'heures régulières et
  supplémentaires pour **une** semaine constituante. Deux champs
  ``Decimal ∈ [0, 168]`` (borne physique, Normes du travail QC).
- :class:`PayrollInput` — contrat d'entrée complet du moteur.
  Treize champs exactement (Req 3.1), immuable (Req 3.11), avec
  refus fail-fast à la frontière : cas hors matrice → ``UnsupportedPayrollCase``,
  incohérence de forme → ``ValidationError``.
- :data:`_CHAMPS_REMUNERATION_HORS_MATRICE` — motifs de rémunération
  hors périmètre Camp LilySO (Req 11.4).
- :data:`_CHAMPS_RETENUE_HORS_MATRICE` — motifs de retenue hors
  périmètre Camp LilySO (Req 11.5).

Contraintes structurantes (design §Components 8, Req 3 & Req 11) :

- ``frozen=True`` + ``extra="forbid"`` — immuabilité et fermeture stricte
  du contrat (Req 3.8, Req 3.11) ;
- rejet transverse de ``float`` sur tous les champs monétaires typés
  ``Decimal`` (règle 01, Req 10.1) via :func:`models._validators.reject_float`
  branché en ``mode="before"`` ;
- ``model_validator(mode="before")`` :meth:`_rejeter_champs_hors_matrice` —
  refus fail-fast des clés apparentées à un motif hors matrice (Req 11.4,
  11.5) avec :class:`UnsupportedPayrollCase` native. Le message cite
  explicitement WebRAS ET PDOC (Req 11.6, Property 16) ;
- ``model_validator(mode="after")`` :meth:`_coherence_croisee` —
  cohérence croisée des composants agrégés (Req 3.5, 3.7, 3.9, 3.10).
  Les cas hors matrice lèvent :class:`UnsupportedPayrollCase` native ;
  les incohérences de forme lèvent :class:`ValueError` (enveloppée par
  Pydantic en :class:`pydantic.ValidationError`).

Discipline exception (Req 8.7, design §Components 2) :

En Pydantic v2, seuls ``ValueError``, ``AssertionError`` et
``PydanticCustomError`` levés dans un validateur sont enveloppés dans
``ValidationError``. :class:`UnsupportedPayrollCase` dérive de
:class:`Exception` (via :class:`PayrollDomainError`), elle se propage
donc **nativement** au consommateur — préservant la disjonction stricte
entre exceptions du domaine et erreurs de validation Pydantic.

Défense en profondeur (design §Composant 8) :

Les gardes de cohérence croisée sur ``employee.province_travail`` et
``pay_period.frequence`` sont **redondantes** avec les validateurs de
:class:`Employee` et :class:`PayPeriod` en fonctionnement nominal —
puisque ces modèles refusent déjà les cas hors matrice à leur propre
construction. Elles restent cependant nécessaires pour couvrir les cas
d'appelants qui court-circuitent la validation via ``model_construct``
(cf. tests d'exemple ``test_..._en_coherence_croisee``). C'est ce que
la spec appelle « défense en profondeur ».

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit ;
- Règle 03 — périmètre Camp LilySO strict, refus fail-fast hors matrice ;
- Règle 06 — TDD, tests écrits avant ce module
  (``tests/models/test_payroll_input.py``, tâche 9.1).

Requirements couverts : 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10,
3.11, 3.12, 10.1, 11.3, 11.4, 11.5, 11.6, 11.7.
"""

from __future__ import annotations

import re
import unicodedata
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
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction
from models.exceptions import UnsupportedPayrollCase
from models.pay_period import PayPeriod


# ===========================================================================
# Blacklists explicites de motifs hors matrice (design §Composant 8)
# ===========================================================================


#: Motifs de **rémunération** hors matrice Camp LilySO (Req 11.4).
#:
#: Toute clé du dict d'entrée dont la forme normalisée
#: (voir :func:`_normaliser_pour_recherche`) **contient** l'un de ces
#: motifs (également normalisé) déclenche :class:`UnsupportedPayrollCase`
#: par :meth:`PayrollInput._rejeter_champs_hors_matrice`.
#:
#: Périmètre exclu par cette blacklist : commissions, bonis, pourboires,
#: allocations automobiles, avantages logement/imposables, options
#: d'achat d'actions. Ces catégories relèvent de calculs fiscaux
#: spécifiques hors du périmètre du Camp LilySO (règle 03) — elles
#: nécessiteraient WebRAS et PDOC pour un traitement correct.
_CHAMPS_REMUNERATION_HORS_MATRICE: frozenset[str] = frozenset(
    {
        "commission",
        "bonus",
        "boni",
        "pourboires",
        "tips",
        "allocation_automobile",
        "car_allowance",
        "logement_fourni",
        "avantage_logement",
        "avantage_imposable",
        "options_achat_actions",
        "stock_options",
        "actions",
        "shares",
    }
)


#: Motifs de **retenue** hors matrice Camp LilySO (Req 11.5).
#:
#: Même mécanisme de détection que
#: :data:`_CHAMPS_REMUNERATION_HORS_MATRICE`. Périmètre exclu : assurance
#: collective, régimes de retraite complémentaires (RPA, REER collectif),
#: cotisations syndicales, pensions alimentaires, saisies de salaire.
#: Ces retenues relèvent de règles contractuelles ou judiciaires que le
#: Camp LilySO ne prend pas en charge (règle 03).
_CHAMPS_RETENUE_HORS_MATRICE: frozenset[str] = frozenset(
    {
        "assurance_collective",
        "group_insurance",
        "rpa",
        "reer_collectif",
        "group_rrsp",
        "cotisation_syndicale",
        "union_dues",
        "pension_alimentaire",
        "alimony",
        "saisie_salaire",
        "garnishment",
    }
)


# ===========================================================================
# Utilitaires internes de normalisation
# ===========================================================================


def _normaliser_pour_recherche(chaine: str) -> str:
    """Retourne une forme canonique de ``chaine`` pour recherche substring.

    La normalisation applique, dans l'ordre :

    1. Décomposition NFKD — sépare chaque lettre accentuée en base +
       diacritique.
    2. Suppression des marques de combinaison Unicode — les accents
       décomposés disparaissent (``é`` → ``e``, ``ç`` → ``c``).
    3. Passage en minuscules.
    4. Suppression de tout caractère hors ``[a-z0-9]`` — les séparateurs
       ``_``, ``-`` et l'espace mentionnés par le design sont ainsi
       éliminés, tout comme la ponctuation qui pourrait masquer un motif
       blacklisté.

    Approche cohérente avec celle de :func:`models._validators._normaliser_pour_recherche`
    et avec l'utilitaire ``_normaliser`` utilisé par
    ``tests/models/test_payroll_input.py`` (règle 06 — TDD, tests avant
    code). Elle garantit la couverture de toutes les variantes générées
    par Hypothesis (casse, accents, séparateurs) pour Property 5.
    """
    nfkd = unicodedata.normalize("NFKD", chaine)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    minuscule = sans_accents.lower()
    return re.sub(r"[^a-z0-9]", "", minuscule)


#: Forme normalisée des motifs hors matrice, pré-calculée une seule fois
#: pour éviter le coût de :func:`_normaliser_pour_recherche` sur chaque
#: clé examinée. L'ordre insertion n'est pas signifiant (recherche par
#: appartenance), mais la valeur **originale** du motif est conservée
#: pour que le message d'erreur cite le motif lisible par l'auditeur.
_MOTIFS_HORS_MATRICE_NORMALISES: tuple[tuple[str, str], ...] = tuple(
    (_normaliser_pour_recherche(motif), motif)
    for motif in sorted(_CHAMPS_REMUNERATION_HORS_MATRICE | _CHAMPS_RETENUE_HORS_MATRICE)
    if _normaliser_pour_recherche(motif)
)


#: Ensemble fermé des taux d'indemnité de vacances admis dans le
#: périmètre Camp LilySO (règle 03, Req 3.5, Req 11.3). Les Normes du
#: travail QC prévoient 4 % (1re et 2e année de service) et 6 %
#: (à compter de la 3e année). Toute autre valeur passée à
#: ``PayrollInput.taux_vacances`` est refusée par
#: :meth:`PayrollInput._coherence_croisee` avec
#: :class:`UnsupportedPayrollCase`. Miroir du ``frozenset`` équivalent
#: sur :class:`Employee` — nécessaire ici pour porter le contrat au
#: niveau du ``PayrollInput`` (défense en profondeur).
_TAUX_VACANCES_SUPPORTES: frozenset[Decimal] = frozenset(
    (Decimal("0.04"), Decimal("0.06"))
)


# ===========================================================================
# HeuresParSemaine — quantités d'heures pour une semaine constituante
# ===========================================================================


class HeuresParSemaine(BaseModel):
    """Heures régulières et supplémentaires pour une semaine (design §8).

    Modèle Pydantic v2 immuable (``frozen=True``) qui refuse tout champ
    inconnu (``extra="forbid"``). Utilisé par
    :class:`PayrollInput.heures_par_semaine` — chaque élément du tuple
    documente les heures effectuées pour une semaine constituante de la
    période.

    Les deux quantités sont bornées à ``[0, 168]`` : la borne inférieure
    exclut toute valeur négative (une durée n'est jamais négative), la
    borne supérieure est une borne physique (168 h = 7 jours × 24 h,
    Normes du travail QC). Toute valeur hors plage est rejetée par
    Pydantic via les contraintes ``ge`` / ``le`` du champ.

    ``float`` est refusé à la validation via
    :func:`models._validators.reject_float` branché en ``mode="before"``
    sur les deux champs ``Decimal`` (règle 01, Req 10.1). Un ``float``
    natif serait sinon converti silencieusement en ``Decimal`` par
    Pydantic, ce qui introduirait des erreurs binaires incompatibles
    avec les golden tests WebRAS/PDOC.

    Note : ce modèle est **distinct** de :class:`models.pay_period.WeekSegment`.
    ``WeekSegment`` porte aussi les dates de la semaine (structure fixe
    de la période) ; ``HeuresParSemaine`` porte uniquement les heures
    effectivement réalisées (paramètre de la paie courante). La
    correspondance 1-à-1 entre les deux collections est vérifiée par
    :meth:`PayrollInput._coherence_croisee`.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    heures_normales: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("168"),
    )
    """Heures régulières effectuées cette semaine, ``[0, 168]``."""

    heures_supplementaires: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("168"),
    )
    """Heures supplémentaires effectuées cette semaine, ``[0, 168]``.
    Note : le taux de majoration et le seuil hebdomadaire déclenchant
    l'application des heures supplémentaires sont portés par les
    paramètres annuels (``parameters/<AAAA>/quebec.json``), pas par ce
    modèle — la valeur ici est déjà la quantité d'heures qualifiée
    comme supplémentaire par le module de calcul aval."""

    @field_validator(
        "heures_normales",
        "heures_supplementaires",
        mode="before",
    )
    @classmethod
    def _refuser_float(cls, value: Any) -> Any:
        """Refuse ``float`` et ``Decimal`` pollué par ``float`` (règle 01).

        Installé en ``mode="before"`` pour intercepter la valeur brute
        AVANT que Pydantic n'applique les contraintes ``ge`` / ``le``
        ou la coercition ``Decimal``. Voir
        :func:`models._validators.reject_float` pour le détail des cas
        d'acceptation et de refus.
        """
        return reject_float(value)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des ``Decimal`` (Req 13.1, 13.4)
    # ------------------------------------------------------------------
    @field_serializer(
        "heures_normales",
        "heures_supplementaires",
        when_used="json",
    )
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque champ ``Decimal`` en chaîne guillemée (règle 01).

        ``when_used="json"`` : la conversion cible UNIQUEMENT la sortie
        JSON ; ``model_dump`` (dict Python) conserve les ``Decimal``.
        Cette convention garantit qu'aucun ``Decimal`` n'apparaît comme
        littéral flottant non guillemé dans la chaîne JSON produite
        (contrainte (c) de Property 6, Req 13.4).
        """
        return str(v)


# ===========================================================================
# PayrollInput — contrat d'entrée complet du moteur
# ===========================================================================


class PayrollInput(BaseModel):
    """Contrat d'entrée complet du moteur de paie Camp LilySO (design §8).

    Modèle Pydantic v2 **immuable** (``frozen=True``, Req 3.11) qui
    refuse tout champ inconnu (``extra="forbid"``, Req 3.8). Agrège
    treize champs exactement (Req 3.1) : la fiche employé, la période
    de paie décomposée en semaines, les paramètres effectifs de la paie
    courante (heures, taux horaire, taux vacances, jours fériés,
    paramètres TP-1015.3 et TD1 « effectifs »), et le cumul YTD de
    début de paie.

    Le suffixe ``_effectif`` / ``_effective`` sur les paramètres
    TP-1015.3 et TD1 distingue les valeurs **appliquées à cette paie**
    des valeurs par défaut portées par la fiche employé. Cette
    distinction permet de traiter en cours d'année une mise à jour de
    formulaire (TP-1015.3 ou TD1) sans muter la fiche employé.

    Un ``PayrollInput`` construit avec succès garantit **par
    construction** (design §Architecture point 4) :

    - province de travail = Québec (Req 3.10, Req 11.1) ;
    - fréquence de paie = aux deux semaines (Req 3.9, Req 11.2) ;
    - taux de vacances ∈ ``{0.04, 0.06}`` (Req 3.5, Req 11.3) ;
    - absence de champ hors matrice (Req 11.4, 11.5) ;
    - correspondance 1-à-1 entre ``heures_par_semaine`` et les semaines
      de la période (Req 3.7) ;
    - appariement ``cumuls_debut`` / ``employee`` / ``pay_period``
      (Req 3.1) ;
    - tous les montants en ``Decimal`` (règle 01, Req 10.1).

    Les modules de calcul aval (specs 2 à 9) reçoivent donc une entrée
    déjà propre, sans avoir à réinstaller ces garde-fous.
    """

    # ------------------------------------------------------------------
    # Configuration Pydantic v2
    # ------------------------------------------------------------------
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    # ------------------------------------------------------------------
    # Composants agrégés (Req 3.1)
    # ------------------------------------------------------------------

    employee: Employee
    """Fiche employé, déjà validée à sa propre construction (règle 04,
    règle 03). La cohérence croisée avec les autres champs est
    contrôlée par :meth:`_coherence_croisee`."""

    pay_period: PayPeriod
    """Période de paie décomposée en ses semaines constituantes, déjà
    validée à sa propre construction (contiguïté, couverture,
    fréquence)."""

    heures_par_semaine: tuple[HeuresParSemaine, ...]
    """Heures effectuées par semaine, dans le **même ordre** que
    ``pay_period.semaines``. La longueur doit correspondre exactement
    au nombre de :class:`WeekSegment` de la période (Req 3.7) — invariant
    vérifié par :meth:`_coherence_croisee`."""

    # ------------------------------------------------------------------
    # Paramètres de rémunération effectifs à la paie (Req 3.2)
    # ------------------------------------------------------------------

    taux_horaire_effectif: Decimal = Field(..., gt=Decimal("0"))
    """Taux horaire effectivement appliqué à cette paie, strictement
    positif. Peut différer de ``employee.taux_horaire_base`` en cas
    d'ajustement en cours d'année (augmentation, promotion). Un taux
    nul ou négatif n'a pas de sens économique et est refusé par la
    contrainte ``gt=0``."""

    taux_vacances: Decimal
    """Taux d'indemnité de vacances effectivement appliqué. Doit
    appartenir à ``{Decimal("0.04"), Decimal("0.06")}`` — invariant
    porté par :meth:`_coherence_croisee` (Req 3.5, Req 11.3). Pas de
    contrainte ``Field`` sur ce champ : la valeur ``Decimal("0.00")``
    doit être refusée comme cas hors matrice (via
    :class:`UnsupportedPayrollCase`), pas comme violation de
    contrainte (:class:`pydantic.ValidationError`)."""

    jours_feries_manuels: Decimal = Field(
        default=Decimal("0.00"),
        ge=Decimal("0"),
    )
    """Montant total des jours fériés travaillés inscrits manuellement
    par l'opérateur (Req 3.6). Absent → ``Decimal("0.00")`` par défaut.
    Le contrat impose une valeur par défaut explicite (pas ``None``,
    pas un placeholder) afin que les modules aval puissent additionner
    ce champ à d'autres montants sans branche conditionnelle. Refuse
    toute valeur strictement négative (``ge=Decimal("0")``, sans
    clampage silencieux)."""

    # ------------------------------------------------------------------
    # Paramètres TP-1015.3 effectifs à la paie (Req 3.2)
    # ------------------------------------------------------------------

    montant_total_TP1015_3_effectif: Decimal = Field(..., ge=Decimal("0"))
    """Montant total des crédits QC (TP-1015.3) effectivement appliqué
    à cette paie. Non négatif."""

    exoneration_TP1015_3_effectif: bool
    """Drapeau d'exonération de retenue QC effectivement appliqué à
    cette paie. ``True`` → retenue QC forcée à 0 pour cette paie."""

    retenue_additionnelle_QC_effective: Decimal = Field(..., ge=Decimal("0"))
    """Retenue additionnelle QC volontaire effectivement appliquée.
    Non négative."""

    # ------------------------------------------------------------------
    # Paramètres TD1 effectifs à la paie (Req 3.2)
    # ------------------------------------------------------------------

    montant_total_TD1_effectif: Decimal = Field(..., ge=Decimal("0"))
    """Montant total des crédits fédéraux (TD1) effectivement appliqué
    à cette paie. Non négatif."""

    exoneration_TD1_effective: bool
    """Drapeau d'exonération de retenue fédérale effectivement
    appliqué à cette paie."""

    retenue_additionnelle_federale_effective: Decimal = Field(..., ge=Decimal("0"))
    """Retenue additionnelle fédérale volontaire effectivement
    appliquée. Non négative."""

    # ------------------------------------------------------------------
    # Cumul YTD au début de la paie (Req 3.1)
    # ------------------------------------------------------------------

    cumuls_debut: CumulsYTD
    """Cumul YTD au début de la paie, servant de point de départ à
    l'agrégation. L'appariement ``(employe_id, annee_civile)`` avec
    :attr:`employee.id` / :attr:`pay_period.annee_fiscale` est vérifié
    par :meth:`_coherence_croisee`."""

    # =====================================================================
    # Validateurs
    # =====================================================================

    # ------------------------------------------------------------------
    # 1. Rejet des motifs hors matrice sur les CLÉS du dict d'entrée
    # ------------------------------------------------------------------
    #
    # Installé en ``mode="before"`` pour intercepter les clés du dict
    # brut AVANT que Pydantic ne compare aux champs déclarés et ne
    # déclenche ``extra="forbid"``. Cet ordre est fondamental : un
    # champ hors matrice DOIT lever ``UnsupportedPayrollCase`` (Req
    # 11.4, 11.5) et non une ``ValidationError`` générique — c'est ce
    # qui matérialise la disjonction entre cas refusé pour raison
    # métier (hors matrice, règle 03) et cas refusé pour raison de
    # forme (champ inconnu, Req 3.8).
    #
    # Discipline exception : ``UnsupportedPayrollCase`` dérive de
    # :class:`Exception` (via :class:`PayrollDomainError`) et n'est
    # PAS enveloppée par Pydantic — elle remonte nativement au
    # consommateur (Req 8.7, design §Components 2). C'est le même
    # patron que celui utilisé par ``Employee._refuser_hors_matrice``
    # et ``PayPeriod._refuser_frequence_hors_matrice_before``.
    @model_validator(mode="before")
    @classmethod
    def _rejeter_champs_hors_matrice(cls, data: Any) -> Any:
        """Refuse fail-fast toute clé apparentée à un motif hors matrice.

        Chaque clé du ``dict`` d'entrée est normalisée via
        :func:`_normaliser_pour_recherche` (NFKD → strip diacritiques →
        lower → suppression des caractères hors ``[a-z0-9]``) puis
        comparée par **recherche substring** à chacun des motifs de
        :data:`_CHAMPS_REMUNERATION_HORS_MATRICE` et
        :data:`_CHAMPS_RETENUE_HORS_MATRICE` (également normalisés).

        La recherche substring couvre toutes les variantes générées par
        Hypothesis dans Property 5 (casse, accents, séparateurs) ainsi
        que les préfixes/suffixes courants (``commission_2026``,
        ``allocation_automobile_special``) : la simple présence du
        motif dans la clé suffit à déclencher le refus.

        En cas de détection, lève :class:`UnsupportedPayrollCase` (non
        enveloppée par Pydantic, Req 8.7) avec un message qui :

        - cite explicitement la clé refusée (permet à l'auteur du
          contrat d'identifier la source du problème) ;
        - cite le motif blacklisté détecté (permet de comprendre
          **pourquoi** la clé est refusée) ;
        - cite explicitement WebRAS ET PDOC (Req 11.6, Property 16) —
          direction l'auditeur vers les outils officiels de repli.

        Si ``data`` n'est pas un ``dict`` (ex. instance déjà
        construite passée à ``model_validate``), la valeur est
        retournée telle quelle : la protection ne s'applique qu'à la
        frontière ``dict`` → modèle. Les valeurs associées aux clés ne
        sont **jamais** inspectées ni conservées — c'est la clé seule
        qui déclenche le refus (design §Composant 8).
        """
        if not isinstance(data, dict):
            return data

        for cle in data:
            # Une clé non-``str`` est laissée à Pydantic (elle sera
            # refusée par ``extra="forbid"`` ou par la coercition de
            # nom de champ). Nous ne cherchons de motif hors matrice
            # que sur les chaînes.
            if not isinstance(cle, str):
                continue

            cle_normalisee = _normaliser_pour_recherche(cle)
            if not cle_normalisee:
                # Clé vide ou uniquement composée de séparateurs : rien
                # à comparer, Pydantic gérera le rejet via extra="forbid".
                continue

            for motif_normalise, motif_original in _MOTIFS_HORS_MATRICE_NORMALISES:
                if motif_normalise and motif_normalise in cle_normalisee:
                    raise UnsupportedPayrollCase(
                        f"Champ '{cle}' non supporté par le Camp LilySO "
                        f"(règle 03, Req 11.4/11.5) : la clé contient le "
                        f"motif hors matrice '{motif_original}'. Le Camp "
                        "LilySO ne traite ni commissions, bonis, pourboires, "
                        "allocations non salariales, avantages imposables, "
                        "options d'achat d'actions, ni les retenues "
                        "facultatives (assurance collective, RPA/REER "
                        "collectif, cotisations syndicales, pension "
                        "alimentaire, saisie de salaire). Pour un cas "
                        "exceptionnel, utiliser WebRAS "
                        "(revenuquebec.ca/webras) et PDOC "
                        "(canada.ca/pdoc)."
                    )

        return data

    # ------------------------------------------------------------------
    # 2. Refus universel de ``float`` sur les 7 champs ``Decimal``
    # ------------------------------------------------------------------
    #
    # Installé sur chaque champ ``Decimal`` du modèle (règle 01, Req
    # 10.1). Placé en ``mode="before"`` pour intercepter la valeur
    # brute AVANT que Pydantic n'applique les contraintes ``gt`` /
    # ``ge`` ou la coercition ``Decimal`` — ce placement est crucial :
    # sans lui, un ``float`` natif serait converti silencieusement en
    # ``Decimal`` avec précision binaire, introduisant des écarts au
    # cent avec les golden tests WebRAS/PDOC.
    @field_validator(
        "taux_horaire_effectif",
        "taux_vacances",
        "jours_feries_manuels",
        "montant_total_TP1015_3_effectif",
        "retenue_additionnelle_QC_effective",
        "montant_total_TD1_effectif",
        "retenue_additionnelle_federale_effective",
        mode="before",
    )
    @classmethod
    def _refuser_float(cls, value: Any) -> Any:
        """Refuse ``float`` et ``Decimal`` pollué par ``float`` (règle 01).

        Délégué à :func:`models._validators.reject_float`. Voir ce
        module pour les cas d'acceptation (``int``, chaîne conforme à
        ``[+-]?[0-9]+(\\.[0-9]+)?``, ``Decimal`` fini à précision
        raisonnable) et de refus (``float`` natif y compris ``0.0``,
        ``Decimal`` non fini ou à précision aberrante).
        """
        return reject_float(value)

    # ------------------------------------------------------------------
    # Sérialisation JSON déterministe des 7 ``Decimal`` scalaires
    # (Req 13.1, 13.4). Les sous-modèles (``employee``, ``pay_period``,
    # ``heures_par_semaine``, ``cumuls_debut``) portent leurs propres
    # sérialiseurs transitivement.
    #
    # ``when_used="json"`` : la conversion en chaîne guillemée s'applique
    # UNIQUEMENT à la sortie JSON — ``model_dump`` (dict Python)
    # conserve les ``Decimal``. Bénéfice : aucun ``Decimal`` n'apparaît
    # comme littéral flottant non guillemé dans la chaîne JSON
    # produite, ce qui permet le round-trip via
    # :func:`_parse_json_reject_floats` sans passer par ``float``
    # (règle 01, Req 13.5).
    # ------------------------------------------------------------------
    @field_serializer(
        "taux_horaire_effectif",
        "taux_vacances",
        "jours_feries_manuels",
        "montant_total_TP1015_3_effectif",
        "retenue_additionnelle_QC_effective",
        "montant_total_TD1_effectif",
        "retenue_additionnelle_federale_effective",
        when_used="json",
    )
    def _serialiser_decimal(self, v: Decimal) -> str:
        """Encode chaque champ ``Decimal`` scalaire en chaîne guillemée (règle 01)."""
        return str(v)

    # ------------------------------------------------------------------
    # Parseur JSON personnalisé — reroute par ``_parse_json_reject_floats``
    # ------------------------------------------------------------------
    #
    # Surcharge de ``model_validate_json`` pour interdire tout littéral
    # flottant non guillemé dans la chaîne JSON entrante (règle 01,
    # Req 13.5). Point d'entrée typique du moteur : un ``PayrollInput``
    # sérialisé sur disque (ex. fixture ``tests/fixtures/inputs/qc0XX.json``,
    # spec ``moteur-paie-contrats`` tâche 14.1) est ainsi refusé
    # fail-fast si un littéral non guillemé y a été introduit — la
    # précision fiscale est préservée bout à bout.
    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        context: Any = None,
    ) -> "PayrollInput":
        """Parse un :class:`PayrollInput` depuis JSON sans passer par ``float``.

        La chaîne JSON est décodée via
        :func:`models._validators._parse_json_reject_floats`, qui refuse
        tout littéral numérique non guillemé contenant un point décimal
        ou une notation scientifique. Le dictionnaire résultant est
        ensuite passé à ``model_validate`` pour bénéficier des
        validateurs de champ standard (règle 03, règle 04, règle 01).
        """
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode("utf-8")
        donnees = _parse_json_reject_floats(json_data)
        return cls.model_validate(donnees, strict=strict, context=context)

    # ------------------------------------------------------------------
    # 3. Cohérence croisée des composants agrégés
    # ------------------------------------------------------------------
    #
    # Six invariants dans un ordre déterministe. Les trois premiers
    # correspondent à des cas hors matrice (règle 03) et lèvent
    # ``UnsupportedPayrollCase`` (non enveloppée). Les trois derniers
    # correspondent à des incohérences de forme et lèvent
    # ``ValueError`` (enveloppée en ``ValidationError`` par Pydantic).
    #
    # Cet ordre matérialise la disjonction stricte entre exceptions
    # métier et erreurs de validation (Req 8.7, design §Components 2)
    # et fournit un ordre de priorité stable des vérifications pour
    # les tests d'exemple qui ciblent chaque cas individuellement.
    @model_validator(mode="after")
    def _coherence_croisee(self) -> "PayrollInput":
        """Vérifie la cohérence croisée des composants agrégés.

        Ordre des vérifications (fail-fast à la première violation) :

        1. **Province de travail = Québec** (Req 3.10, Req 11.1) —
           défense en profondeur. Nominalement, ``Employee`` refuse
           déjà les provinces ≠ QC. Cette garde protège les appelants
           qui court-circuitent via ``Employee.model_construct``.
           Lève :class:`UnsupportedPayrollCase`.
        2. **Fréquence de paie = aux deux semaines** (Req 3.9,
           Req 11.2) — défense en profondeur, même logique que 1.
           Lève :class:`UnsupportedPayrollCase`.
        3. **Taux de vacances ∈ ``{0.04, 0.06}``** (Req 3.5, Req 11.3).
           Le contrat ne pouvant pas être exprimé par une simple
           contrainte ``Field``, il est porté ici. Lève
           :class:`UnsupportedPayrollCase`.
        4. **Longueur ``heures_par_semaine`` = longueur ``pay_period.semaines``**
           (Req 3.7) — chaque semaine de la période doit avoir
           exactement une entrée d'heures. Lève :class:`ValueError`.
        5. **``cumuls_debut.employe_id == employee.id``** (Req 3.1) —
           le cumul de départ doit appartenir au bon employé. Lève
           :class:`ValueError`.
        6. **``cumuls_debut.annee_civile == pay_period.annee_fiscale``**
           (Req 3.1) — le cumul de départ doit correspondre à l'année
           de la paie. Lève :class:`ValueError`.

        Les messages des :class:`UnsupportedPayrollCase` citent
        explicitement WebRAS ET PDOC (Req 11.6, Property 16).
        """
        # -- 1. Province (Req 3.10) ------------------------------------
        #
        # Utilisation de ``is not`` : compare l'identité de l'enum ;
        # tolère à la fois une valeur ``Juridiction.QUEBEC`` correcte
        # et rejette toute autre valeur (autre membre de l'enum, chaîne
        # brute injectée via ``model_construct``, etc.).
        if self.employee.province_travail is not Juridiction.QUEBEC:
            raise UnsupportedPayrollCase(
                f"Province de travail '{self.employee.province_travail}' non "
                "supportée (règle 03, Req 3.10, Req 11.1) : le Camp LilySO "
                "opère au Québec uniquement. Pour un cas exceptionnel, "
                "utiliser WebRAS (revenuquebec.ca/webras) et PDOC "
                "(canada.ca/pdoc)."
            )

        # -- 2. Fréquence de paie (Req 3.9) ----------------------------
        #
        # Même patron que la province. ``is not`` couvre le cas nominal
        # (autre membre de l'enum, si l'énumération s'enrichissait un
        # jour) ET le cas dégénéré d'une chaîne brute injectée via
        # ``PayPeriod.model_construct`` (chaîne libre ≠ enum, donc
        # ``is not`` retourne True).
        if self.pay_period.frequence is not FrequencePaie.AUX_DEUX_SEMAINES:
            raise UnsupportedPayrollCase(
                f"Fréquence de paie '{self.pay_period.frequence}' non "
                "supportée (règle 03, Req 3.9, Req 11.2) : le Camp LilySO "
                "fonctionne aux deux semaines uniquement. Pour un cas "
                "exceptionnel, utiliser WebRAS (revenuquebec.ca/webras) "
                "et PDOC (canada.ca/pdoc)."
            )

        # -- 3. Taux de vacances (Req 3.5, Req 11.3) -------------------
        if self.taux_vacances not in _TAUX_VACANCES_SUPPORTES:
            raise UnsupportedPayrollCase(
                f"Taux d'indemnité de vacances {self.taux_vacances} "
                "non supporté (règle 03, Req 3.5, Req 11.3) : le Camp "
                "LilySO applique exclusivement 4 % (Decimal(\"0.04\")) ou "
                "6 % (Decimal(\"0.06\")) selon l'ancienneté. Pour un cas "
                "exceptionnel, utiliser WebRAS (revenuquebec.ca/webras) "
                "et PDOC (canada.ca/pdoc)."
            )

        # -- 4. Longueur heures_par_semaine (Req 3.7) ------------------
        #
        # ValueError → wrapped en ValidationError par Pydantic. C'est
        # une incohérence de FORME (pas un cas hors matrice) : le
        # contrat ``PayrollInput`` exige une correspondance 1-à-1
        # entre les semaines de la période et les entrées d'heures.
        if len(self.heures_par_semaine) != len(self.pay_period.semaines):
            raise ValueError(
                f"Le nombre d'entrées `heures_par_semaine` "
                f"({len(self.heures_par_semaine)}) doit correspondre "
                f"au nombre de semaines constituantes de la période "
                f"({len(self.pay_period.semaines)}) — Req 3.7. Chaque "
                "semaine de `pay_period.semaines` doit avoir exactement "
                "une entrée `HeuresParSemaine` associée, dans le même "
                "ordre."
            )

        # -- 5. Appariement cumuls_debut / employee (Req 3.1) ----------
        #
        # ValueError → wrapped en ValidationError. Les cumuls YTD sont
        # indexés par employé (Req 7.2) — mélanger deux employés dans
        # un même ``PayrollInput`` est incohérent.
        if self.cumuls_debut.employe_id != self.employee.id:
            raise ValueError(
                f"`cumuls_debut.employe_id` "
                f"('{self.cumuls_debut.employe_id}') doit correspondre à "
                f"`employee.id` ('{self.employee.id}') — Req 3.1. Le cumul "
                "YTD de départ doit appartenir au même employé que la "
                "fiche employé de cette paie."
            )

        # -- 6. Appariement cumuls_debut / pay_period (Req 3.1) --------
        #
        # ValueError → wrapped en ValidationError. Les cumuls YTD sont
        # indexés par année civile (Req 7.2) — une paie de 2026 ne peut
        # pas partir d'un cumul YTD 2025. La correction se fait par
        # repartir de ``CumulsYTD.zero(employe_id, nouvelle_annee)``.
        if self.cumuls_debut.annee_civile != self.pay_period.annee_fiscale:
            raise ValueError(
                f"`cumuls_debut.annee_civile` ({self.cumuls_debut.annee_civile}) "
                f"doit correspondre à `pay_period.annee_fiscale` "
                f"({self.pay_period.annee_fiscale}) — Req 3.1. Repartir "
                f"d'un cumul neutre via `CumulsYTD.zero(employe_id, "
                f"{self.pay_period.annee_fiscale})` pour la nouvelle "
                "année."
            )

        return self
