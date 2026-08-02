"""Validateurs Pydantic v2 transverses — moteur de paie Camp LilySO.

Spec de référence : ``moteur-paie-contrats`` — tâche 4.2.
Design de référence : section « Components and Interfaces » §3 (`design.md`).

Ce module expose trois utilitaires réutilisés par tous les modèles du
domaine :

- :func:`reject_float` — refuse toute valeur ``float`` ou ``Decimal`` dont
  la représentation trahit une origine ``float`` (précision aberrante).
  Utilisé comme ``field_validator("*", mode="before")`` (règle 01) sur
  chaque modèle Pydantic du domaine (voir design §3.1).
- :func:`reject_sensitive_fields` — refuse toute clé dont la forme
  normalisée (casse, accents, séparateurs ``_``/``-``/espace, ponctuation)
  contient un motif blacklisté (`nas`, `iban`, `adresse`, ...). Utilisé
  comme ``model_validator(mode="before")`` sur les modèles qui reçoivent
  des données brutes du monde extérieur (règle 04, voir design §3.2).
- :func:`_parse_json_reject_floats` — wrapper autour de ``json.loads``
  qui refuse tout littéral numérique non guillemé contenant un point
  décimal ou une notation scientifique. Utilisé par les chargeurs de
  paramètres et par ``model_validate_json`` (règle 01 + Req 13.5, voir
  design §3.3).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit ;
- Règle 04 — aucune donnée personnelle sensible dans le contrat de paie ;
- Règle 06 — TDD, tests avant code : ces validateurs sont couverts par
  ``tests/models/test_validators.py`` avant leur implémentation.

Requirements couverts : 1.3, 1.4, 3.2, 9.4, 10.1, 10.2, 10.4, 13.5.
"""

from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal
from typing import Any, NoReturn


# ---------------------------------------------------------------------------
# Liste noire des motifs sensibles (design §Components 3.2)
# ---------------------------------------------------------------------------

#: Liste des motifs bannis (règle 04). La détection est effectuée sur une
#: forme normalisée (voir :func:`_normaliser_pour_recherche`) et fonctionne
#: par recherche substring : toute clé dont la forme normalisée **contient**
#: l'un de ces motifs (également normalisé) est refusée.
#:
#: Exemples de détection positive :
#:
#: - ``"NAS"``, ``"Nas"``, ``"nAs"`` → motif ``"nas"`` ;
#: - ``"N.A.S."`` → motif ``"nas"`` (la ponctuation est éliminée) ;
#: - ``"numero-assurance-sociale"``, ``"NUMERO_ASSURANCE_SOCIALE"``,
#:   ``"numero assurance sociale"`` → motif ``"numero_assurance_sociale"`` ;
#: - ``"téléphone_personnel"`` → motif ``"telephone_personnel"``
#:   (accents éliminés) ;
#: - ``"adresse_domicile"``, ``"iban_conjoint"`` → motifs ``"adresse"`` et
#:   ``"iban"`` détectés en substring.
MOTIFS_SENSIBLES: tuple[str, ...] = (
    "nas",
    "sin",
    "numero_assurance_sociale",
    "social_insurance_number",
    "compte_bancaire",
    "bank_account",
    "iban",
    "transit",
    "institution_bancaire",
    "adresse",
    "address",
    "courriel_personnel",
    "personal_email",
    "telephone_personnel",
    "personal_phone",
    "date_naissance_reelle",
)


# ---------------------------------------------------------------------------
# Utilitaires internes de normalisation
# ---------------------------------------------------------------------------


def _normaliser_pour_recherche(chaine: str) -> str:
    """Retourne une forme canonique de ``chaine`` pour recherche substring.

    La normalisation applique, dans l'ordre :

    1. Décomposition NFKD (sépare chaque lettre accentuée en base + diacritique).
    2. Suppression des marques de combinaison Unicode (les accents décomposés
       disparaissent : ``é`` → ``e``, ``ç`` → ``c``, ``ñ`` → ``n``).
    3. Passage en minuscules.
    4. Suppression de tout caractère hors ``[a-z0-9]`` : les séparateurs
       ``_``, ``-`` et l'espace mentionnés par le design sont ainsi
       éliminés, tout comme la ponctuation (``.``, ``,``) qui pourrait
       masquer un motif blacklisté (ex. ``N.A.S.``).

    Cette forme est utilisée pour comparer la clé fournie par l'appelant à
    chacun des motifs de :data:`MOTIFS_SENSIBLES` (eux-mêmes normalisés).
    """
    nfkd = unicodedata.normalize("NFKD", chaine)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    minuscule = sans_accents.lower()
    return re.sub(r"[^a-z0-9]", "", minuscule)


#: Forme normalisée des motifs sensibles, pré-calculée une seule fois pour
#: éviter le coût de :func:`_normaliser_pour_recherche` sur chaque clé
#: examinée. L'ordre est préservé pour que le message d'erreur cite le motif
#: **original** (lisible par l'auditeur) plutôt que sa forme normalisée.
_MOTIFS_NORMALISES: tuple[tuple[str, str], ...] = tuple(
    (_normaliser_pour_recherche(motif), motif) for motif in MOTIFS_SENSIBLES
)


#: Regex des chaînes numériques admissibles pour :func:`reject_float`.
#:
#: Le design §3.1 impose que les chaînes convertibles en ``Decimal``
#: n'utilisent ni notation scientifique (``1e2``, ``1E-3``) ni caractère
#: hors ``[0-9.\-+]``. Cette regex est plus restrictive : elle exige un
#: format ``[±]entier[.décimales]``, ce qui exclut aussi ``NaN``,
#: ``Infinity``, le séparateur virgule francophone (``1,00``) et tout
#: caractère parasite (``12$``, ``abc``).
_REGEX_DECIMAL_STR: re.Pattern[str] = re.compile(r"^[+-]?[0-9]+(\.[0-9]+)?$")


#: Longueur au-delà de laquelle un ``Decimal`` est considéré comme ayant
#: une précision « aberrante », symptomatique d'une construction depuis
#: un ``float`` (Req 10.4). Un montant fiscal légitime tient largement
#: sous 20 caractères (ex. ``"1516.32"`` en fait 7, ``"-9999999.999999"``
#: en fait 15). ``Decimal(1516.32)`` produit ``Decimal("1516.319999...")``
#: soit ~54 caractères, ce qui déclenche le refus.
_PRECISION_ABERRANTE_SEUIL: int = 20


# ---------------------------------------------------------------------------
# reject_float — refus universel de ``float`` (règle 01)
# ---------------------------------------------------------------------------


def reject_float(value: Any) -> Any:
    """Refuse ``float`` et ``Decimal`` pollué par ``float`` (règle 01).

    Ce validateur est installé en ``mode="before"`` sur tous les champs
    ``Decimal`` des modèles du domaine (voir design §3.1). Il examine la
    valeur brute **avant** toute coercition Pydantic pour empêcher la
    conversion silencieuse d'un ``float`` en ``Decimal``, qui produirait
    des erreurs binaires incompatibles avec les golden tests WebRAS/PDOC
    (règle 01 justification).

    Règles d'acceptation :

    - ``int`` → accepté tel quel (couvre l'exception explicite de Req 10.1 :
      les entiers Python n'ont pas de représentation ``float``).
    - ``str`` matchant ``^[+-]?[0-9]+(\\.[0-9]+)?$`` → accepté ; toute
      autre chaîne (notation scientifique, virgule, ``NaN``, ``Infinity``,
      caractères hors ``[0-9.\\-+]``) est refusée.
    - ``Decimal`` fini avec ``len(str(value)) <= 20`` → accepté ; un
      ``Decimal`` non fini (``NaN``, ``Infinity``) ou dont la représentation
      dépasse le seuil de précision aberrante est refusé (Req 10.4).

    Règles de refus :

    - ``float`` (Python natif, y compris ``4.0``, ``0.0``, ``nan``,
      ``inf``) → :class:`ValueError` (Req 10.1, 10.2).
    - ``Decimal`` non fini ou à précision aberrante → :class:`ValueError`
      (Req 10.4).
    - ``str`` non conforme à la regex → :class:`ValueError`.

    Les valeurs d'autres types (``None``, ``date``, ``bool`` sous-classe
    d'``int``, etc.) sont laissées passer : la responsabilité de leur
    rejet incombe à Pydantic en aval, sur la base du typage annoté du
    champ. Ce validateur cible **uniquement** la frontière ``float`` ↔
    ``Decimal``.
    """
    # 1. Refus fail-fast d'un ``float`` natif. Placé en tête car
    #    ``isinstance(x, float)`` doit prévaloir sur toute autre logique :
    #    même ``4.0`` ou ``0.0`` (entiers représentables exactement) sont
    #    interdits par Req 10.1.
    if isinstance(value, float):
        raise ValueError(
            f"Valeur `float` refusée (règle 01) : {value!r}. Le domaine "
            "paie exige `decimal.Decimal`. Passer par `Decimal(str(...))` "
            "ou une chaîne littérale (ex. `Decimal(\"1516.32\")`)."
        )

    # 2. Cas ``Decimal`` : refus si non fini ou précision aberrante.
    #    Note : ``Decimal(0.0)`` produit ``Decimal('0')`` — indistinguable
    #    de ``Decimal('0')`` et donc accepté. Req 10.4 vise les précisions
    #    **aberrantes**, ce cas limite est documenté par le test
    #    ``test_decimal_de_zero_construit_depuis_float_est_rejete_ou_accepte``.
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            raise ValueError(
                f"`Decimal` non fini refusé (règle 01) : {value!r}. "
                "Le domaine paie n'admet ni NaN ni Infinity."
            )
        if len(str(value)) > _PRECISION_ABERRANTE_SEUIL:
            raise ValueError(
                f"`Decimal` à précision aberrante refusé (règle 01) : "
                f"{value!r} ({len(str(value))} caractères). "
                "Cette signature est typique d'une construction "
                "`Decimal(float_val)`. Utiliser `Decimal(str(...))` ou "
                "une chaîne littérale pour préserver l'exactitude fiscale."
            )
        return value

    # 3. Cas ``str`` : la chaîne doit être directement convertible en
    #    ``Decimal`` sans passer par ``float`` (design §3.1). Notation
    #    scientifique et caractères hors ``[0-9.\-+]`` sont refusés.
    if isinstance(value, str):
        if not _REGEX_DECIMAL_STR.match(value):
            raise ValueError(
                f"Chaîne non convertible en `Decimal` refusée (règle 01) : "
                f"{value!r}. Format attendu : `[+-]?chiffres[.chiffres]`, "
                "sans notation scientifique ni séparateur autre que le "
                "point décimal. `NaN`, `Infinity` et le séparateur virgule "
                "sont interdits."
            )
        return value

    # 4. ``int`` (et ``bool`` par héritage) : accepté tel quel. Un entier
    #    Python ne peut pas avoir été construit depuis un ``float`` avec
    #    précision aberrante — c'est un type distinct sans partie décimale.
    if isinstance(value, int):
        return value

    # 5. Autres types (``None``, ``date``, dict, ...) : laissés passer.
    #    Pydantic les rejettera sur la base du typage du champ. Notre
    #    responsabilité s'arrête à la frontière ``float`` ↔ ``Decimal``.
    return value


# ---------------------------------------------------------------------------
# reject_sensitive_fields — refus des motifs blacklistés (règle 04)
# ---------------------------------------------------------------------------


def reject_sensitive_fields(data: Any) -> Any:
    """Refuse toute clé apparentée à une donnée sensible (règle 04).

    Installé comme ``model_validator(mode="before")`` sur les modèles qui
    reçoivent un ``dict`` brut (kwargs, ``model_validate``, parsing JSON).
    Chaque clé est normalisée via :func:`_normaliser_pour_recherche` puis
    comparée par recherche substring à chacun des motifs de
    :data:`MOTIFS_SENSIBLES` (également normalisés).

    En cas de détection, lève :class:`ValueError` (convertie en
    :class:`pydantic.ValidationError` par Pydantic quand ce validateur est
    utilisé dans un modèle) avec un message :

    - qui cite explicitement la clé refusée (indispensable pour permettre
      à l'auteur du contrat d'identifier la source du problème sans lire
      la trace complète) ;
    - qui mentionne le motif blacklisté détecté (permet de comprendre
      *pourquoi* la clé est refusée) ;
    - qui renvoie explicitement à la **règle 04** (référence au steering
      qui justifie l'interdiction).

    Si ``data`` n'est pas un ``dict`` (ex. instance Pydantic déjà
    construite, autre type), la valeur est retournée telle quelle : la
    protection ne s'applique qu'à la frontière ``dict`` → modèle.

    Les valeurs associées aux clés ne sont **jamais** inspectées ni
    conservées : la fonction ne journalise aucune donnée sensible.
    """
    if not isinstance(data, dict):
        return data

    for cle in data:
        # Une clé non-``str`` est laissée à Pydantic (qui la refusera lors
        # de la validation des noms de champ). Nous ne cherchons de motif
        # sensible que sur les chaînes.
        if not isinstance(cle, str):
            continue

        cle_normalisee = _normaliser_pour_recherche(cle)
        if not cle_normalisee:
            # Clé vide ou uniquement composée de séparateurs : rien à
            # comparer, on laisse Pydantic gérer.
            continue

        for motif_normalise, motif_original in _MOTIFS_NORMALISES:
            if motif_normalise and motif_normalise in cle_normalisee:
                raise ValueError(
                    f"Champ sensible refusé (règle 04) : la clé '{cle}' "
                    f"contient le motif blacklisté '{motif_original}'. "
                    "Aucune donnée personnelle sensible (NAS, compte "
                    "bancaire, IBAN, adresse, courriel personnel, "
                    "téléphone personnel, date de naissance réelle, "
                    "etc.) ne DOIT apparaître dans le contrat de paie "
                    "du Camp LilySO ni dans le dépôt Git. Voir règle 04 "
                    "(`.kiro/steering/04-donnees-sensibles.md`)."
                )

    return data


# ---------------------------------------------------------------------------
# _parse_json_reject_floats — refus des littéraux JSON flottants
# ---------------------------------------------------------------------------


def _reject_json_float(litteral: str) -> NoReturn:
    """Refuse tout littéral numérique JSON non guillemé transmis par
    ``json.loads`` via son crochet ``parse_float``.

    ``json.loads`` appelle ``parse_float`` sur tout jeton numérique
    contenant un point décimal (``1.0``, ``0.063``) ou une notation
    scientifique (``1e2``, ``1.5E-3``). Un entier JSON sans point ni
    exposant (``27``, ``40``) passe par ``parse_int`` et n'atteint pas
    cette fonction — il est donc accepté (Req 10.1, exception explicite).

    Un ``Decimal`` doit être encodé en JSON sous forme de **chaîne
    guillemée** (règle 01, Req 13.5) pour préserver son exactitude au
    travers d'un round-trip. Ce hook lève :class:`ValueError` sitôt qu'un
    littéral non guillemé avec point ou exposant est rencontré, avec un
    message actionnable qui indique la correction attendue.
    """
    raise ValueError(
        f"Littéral JSON flottant refusé (règle 01, Req 13.5) : {litteral!r}. "
        "Un montant ou un taux doit être encodé sous forme de chaîne "
        "guillemée (ex. `\"0.063\"` au lieu de `0.063`) pour être converti "
        "en `decimal.Decimal` sans passer par `float`. Corriger le "
        "document JSON à la source."
    )


def _parse_json_reject_floats(source: str) -> Any:
    """Parse une chaîne JSON en refusant tout littéral flottant non guillemé.

    Wrapper strict autour de :func:`json.loads` : ``parse_float`` est
    branché sur :func:`_reject_json_float`, qui lève dès qu'un jeton
    numérique JSON contient un point décimal ou une notation scientifique
    (``0.063``, ``1e-3``, ``1.5E+2``). Le rejet est **global** : la
    présence d'un seul littéral flottant fait échouer le document entier
    (fail-fast, cohérent avec la règle 01).

    Restent acceptés sans intervention (comportement natif de
    :func:`json.loads`) :

    - les entiers JSON (``0``, ``27``, ``-1516``) → ``int`` (Req 10.1) ;
    - les chaînes JSON (``"1516.32"``, ``"0.063"``) → ``str``. Ce format
      est celui exigé par Req 13.5 pour encoder un ``Decimal`` ;
    - les booléens, ``null``, listes et objets, à condition qu'aucune de
      leurs valeurs numériques ne soit un flottant non guillemé.

    Utilisé par :

    - ``payroll_engine.parameters_loader.load_parameters`` pour lire les
      fichiers ``parameters/<AAAA>/*.json`` (Req 9.4) ;
    - les méthodes ``model_validate_json`` des modèles du domaine (via un
      ``model_validator(mode="before")``) — Req 13.5.
    """
    return json.loads(source, parse_float=_reject_json_float)
