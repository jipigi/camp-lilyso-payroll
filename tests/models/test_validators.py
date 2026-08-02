"""Property tests des validateurs transverses (``models/_validators.py``).

Spec de référence : ``moteur-paie-contrats`` — tâche 4.1.
Design de référence : section « Components and Interfaces » §3
(Validateurs transverses réutilisables).

Discipline TDD (règle 06) : ce module est écrit **avant** l'implémentation.
Tant que la tâche 4.2 n'a pas créé ``models/_validators.py``, la collection
pytest de ce fichier échoue avec ``ModuleNotFoundError``. C'est le
comportement attendu — les tests précèdent le code.

Portée de la tâche 4.1 (``tasks.md`` §4.1) :

- **Property 2** : rejet universel de ``float`` dans tout champ ``Decimal``
  (Requirements 10.1, 10.2, 10.4). Hypothesis génère des ``float`` (positifs,
  négatifs, ``NaN``, ``4.0``, ``0.0``) et des ``Decimal`` construits depuis un
  ``float`` avec précision aberrante ; ``reject_float`` DOIT lever une erreur.
  Les entiers Python et les chaînes convertibles restent acceptés.
- **Property 4** : rejet des motifs sensibles (Requirement 1.3).
  Hypothesis génère des variantes de casse, d'accentuation et de séparateurs
  de chaque motif de la liste noire (``nas``, ``sin``, ``iban``, ``adresse``,
  ``courriel_personnel``, ``telephone_personnel``, ...). ``reject_sensitive_fields``
  DOIT refuser la clé avec un message renvoyant à la règle 04.
- **Property JSON** : rejet des littéraux JSON numériques non guillemés
  contenant un point décimal (Requirements 10.1, 13.5). ``_parse_json_reject_floats("1.0")``
  et ``_parse_json_reject_floats("0.0")`` DOIVENT lever, alors que
  ``_parse_json_reject_floats("1")`` et ``_parse_json_reject_floats("40")``
  DOIVENT passer.

Aucun autre validateur n'est testé ici. Les properties 3, 5, 12, 16 et la
sérialisation JSON déterministe sont couvertes par les tâches ultérieures
(6.1, 9.1, 5.1, 13.1, 15.4).

Règles applicables :

- Règle 01 — aucun ``float`` dans le domaine paie. Les tests eux-mêmes
  peuvent construire des ``float`` **uniquement** pour vérifier qu'ils sont
  rejetés à la frontière.
- Règle 04 — aucun donnée personnelle réelle. Les motifs sensibles testés
  sont des **noms de champ** blacklistés, pas des valeurs.
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# Import volontairement au niveau module : tant que ``models/_validators.py``
# n'existe pas (tâche 4.2 non réalisée), la collection pytest échoue avec
# ``ModuleNotFoundError``. C'est le comportement attendu par la règle 06.
from models._validators import (  # noqa: E402
    _parse_json_reject_floats,
    reject_float,
    reject_sensitive_fields,
)


# ---------------------------------------------------------------------------
# Utilitaires communs
# ---------------------------------------------------------------------------


# Liste noire des motifs sensibles (design.md §Components 3.2).
# Cette constante n'importe PAS depuis ``models/_validators`` afin de ne pas
# dépendre de la structure interne du module implémenté par la tâche 4.2 : les
# tests vérifient le **comportement** attendu (rejet), pas le détail interne
# de la constante. Toute divergence entre cette liste et celle de
# l'implémentation doit être considérée comme un bug d'implémentation à
# corriger côté ``_validators``.
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


def _message_mentionne_regle_04(exc: BaseException) -> bool:
    """Retourne ``True`` si le message d'exception renvoie à la règle 04.

    On accepte les variantes ``règle 04``, ``regle 04``, ``rule 04`` (mais
    on exige la présence du numéro ``04`` pour éviter les faux positifs sur
    d'autres règles du dépôt). Comparaison insensible à la casse et aux
    accents.
    """
    message = str(exc)
    normalized = (
        unicodedata.normalize("NFKD", message).encode("ASCII", "ignore").decode().lower()
    )
    # On tolère « règle 04 », « regle 04 » (déjà couvert par la normalisation)
    # ainsi que « rule 04 ». On exige explicitement le nombre ``04``.
    return bool(re.search(r"(regle|rule)\s*0*4\b", normalized))


# ===========================================================================
# Property 2 — Rejet universel de ``float`` dans tout champ ``Decimal``
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 2: Rejet universel de `float` dans
# tout champ `Decimal`. *Pour tout* modèle du domaine et *pour tout* champ
# typé `Decimal`, l'assignation d'une valeur `float` (Python natif, y compris
# `4.0` et `0.0`), d'un `Decimal` construit par `Decimal(float_val)` avec
# précision aberrante, ou d'un littéral JSON numérique non guillemé (avec
# ou sans point décimal) contenant un point décimal, doit lever une erreur
# de validation. Un entier JSON sans point décimal (`27`, `40`) reste accepté.
#
# **Validates: Requirements 10.1, 10.2, 10.4**
# ===========================================================================


class TestRejectFloatExemples:
    """Exemples explicites cités par le task 4.1 pour ``reject_float``.

    Ces exemples verrouillent les cas limites qui ont motivé la propriété
    (``4.0``, ``0.0``, ``NaN``, ``Decimal(1516.32)``). Les propriétés
    Hypothesis qui suivent généralisent sur tout l'espace de ``float``.
    """

    @pytest.mark.parametrize(
        "valeur_float",
        [
            0.0,
            4.0,
            1.0,
            -1.0,
            1516.32,
            -1516.32,
            0.1,
            1e-10,
            1e10,
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
        ids=[
            "zero",
            "quatre",
            "un",
            "moins_un",
            "salaire_qc001",
            "salaire_negatif",
            "un_dixieme_binaire",
            "tres_petit",
            "tres_grand",
            "nan",
            "inf_positif",
            "inf_negatif",
        ],
    )
    def test_float_natif_est_toujours_rejete(self, valeur_float: float) -> None:
        # Requirement 10.2 : refus actif de la classe ``float`` avant toute
        # conversion. Requirement 10.1 : refus même quand la valeur
        # représente un entier exact (``4.0``, ``0.0``).
        with pytest.raises((ValueError, TypeError)):
            reject_float(valeur_float)

    def test_decimal_construit_depuis_float_est_rejete(self) -> None:
        # Requirement 10.4 : ``Decimal(1516.32)`` produit une valeur avec
        # une expansion binaire aberrante (~50 chiffres après la virgule).
        # ``reject_float`` doit détecter cette précision anormale.
        decimal_pollue = Decimal(1516.32)  # noqa: RUF032 (intentionnel : test)
        # Sanity : la construction depuis float produit bien une précision
        # aberrante, sinon la property est mal calibrée.
        assert len(str(decimal_pollue)) > 20
        with pytest.raises((ValueError, TypeError)):
            reject_float(decimal_pollue)

    def test_decimal_de_zero_construit_depuis_float_est_rejete_ou_accepte(self) -> None:
        # ``Decimal(0.0)`` produit ``Decimal('0')`` — pas de précision
        # aberrante. Ce cas est indistinguable de ``Decimal("0")`` et
        # peut légitimement passer. Ce test documente le comportement
        # limite : soit ``reject_float`` détecte l'origine ``float``
        # (rejet), soit il ne voit qu'un ``Decimal('0')`` propre
        # (acceptation). Les deux sont acceptables ici car le
        # requirement 10.4 vise les précisions **aberrantes**.
        try:
            reject_float(Decimal(0.0))
        except (ValueError, TypeError):
            pass  # rejet strict : OK
        # Absence d'erreur : également OK — ``Decimal('0')`` est propre.

    @pytest.mark.parametrize(
        "entier",
        [0, 1, 27, 40, 1516, -1, -1516],
        ids=["zero", "un", "vingt_sept", "quarante", "gros", "moins_un", "gros_negatif"],
    )
    def test_entiers_python_sont_acceptes(self, entier: int) -> None:
        # Requirement 10.1 (exception explicite) : un entier Python (donc
        # sans point décimal) est accepté par le validateur, qui laisse
        # Pydantic effectuer la coercition vers ``Decimal``. ``reject_float``
        # ne DOIT PAS lever pour un ``int``.
        # NB : on n'assertit pas le type de retour car ``reject_float``
        # peut soit retourner ``entier`` tel quel, soit le convertir en
        # ``Decimal(str(entier))``. Les deux comportements sont conformes
        # au design §3.1.
        reject_float(entier)  # ne doit pas lever

    @pytest.mark.parametrize(
        "chaine",
        [
            "0",
            "1",
            "40",
            "1516",
            "0.00",
            "1.00",
            "1516.32",
            "-1516.32",
            "+1.00",
            "0.063",
        ],
        ids=[
            "zero",
            "un",
            "quarante",
            "gros_entier",
            "zero_deux_decimales",
            "un_deux_decimales",
            "montant_qc001",
            "montant_negatif",
            "avec_plus",
            "taux_rrq",
        ],
    )
    def test_chaines_convertibles_sont_acceptees(self, chaine: str) -> None:
        # Requirement 10.2 : les chaînes convertibles directement en
        # ``Decimal`` (via ``Decimal(str)``, sans passage par ``float``)
        # sont acceptées. Design §3.1 précise que la chaîne ne doit pas
        # contenir de notation scientifique ni de caractères hors
        # ``[0-9.\-+]`` : les cas ci-dessus respectent cette contrainte.
        reject_float(chaine)  # ne doit pas lever

    @pytest.mark.parametrize(
        "decimal_propre",
        [
            Decimal("0"),
            Decimal("0.00"),
            Decimal("1.00"),
            Decimal("1516.32"),
            Decimal("-1516.32"),
            Decimal("0.063"),
        ],
    )
    def test_decimal_propres_sont_acceptes(self, decimal_propre: Decimal) -> None:
        # Les ``Decimal`` construits depuis une chaîne (donc sans pollution
        # binaire) DOIVENT être acceptés (design §3.1, Req 10.2).
        reject_float(decimal_propre)  # ne doit pas lever


@pytest.mark.property
class TestRejectFloatProperties:
    """Property 2 (partielle) — généralisation Hypothesis sur ``float`` et ``int``."""

    # Feature: moteur-paie-contrats, Property 2: Rejet universel de `float`
    # dans tout champ `Decimal`.
    @given(
        st.floats(
            allow_nan=True,
            allow_infinity=True,
            allow_subnormal=True,
        )
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.filter_too_much])
    def test_tout_float_est_rejete(self, x: float) -> None:
        """Requirement 10.1, 10.2 — aucune valeur ``float`` (aucune) n'est admise."""
        # Sanity : Hypothesis nous donne bien un ``float`` (même pour ``nan``).
        assert isinstance(x, float)
        with pytest.raises((ValueError, TypeError)):
            reject_float(x)

    # Feature: moteur-paie-contrats, Property 2: Rejet universel de `float`
    # dans tout champ `Decimal` (via Decimal(float_val) avec précision aberrante).
    @given(
        st.floats(
            allow_nan=False,
            allow_infinity=False,
            allow_subnormal=False,
            min_value=-1_000_000.0,
            max_value=1_000_000.0,
        )
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.filter_too_much])
    def test_decimal_construit_depuis_float_avec_precision_aberrante_est_rejete(
        self, x: float
    ) -> None:
        """Requirement 10.4 — ``Decimal(float_val)`` avec précision aberrante."""
        decimal_pollue = Decimal(x)
        # On se restreint aux ``float`` dont la conversion en ``Decimal``
        # produit une chaîne longue (typique d'une expansion binaire). Les
        # ``float`` qui ont une représentation exacte courte (comme ``1.0``
        # → ``Decimal('1')``) ne sont pas distinguables d'un ``Decimal``
        # propre et sont exclus ici. Requirement 10.4 vise précisément ces
        # cas « aberrants ».
        assume(len(str(decimal_pollue)) > 20)
        with pytest.raises((ValueError, TypeError)):
            reject_float(decimal_pollue)

    # Feature: moteur-paie-contrats, Property 2: Rejet universel de `float`
    # dans tout champ `Decimal` (les entiers Python restent acceptés).
    @given(st.integers(min_value=-1_000_000_000, max_value=1_000_000_000))
    @settings(max_examples=200)
    def test_tout_entier_python_est_accepte(self, n: int) -> None:
        """Requirement 10.1 (exception explicite) — un ``int`` sans point décimal."""
        # Ne DOIT PAS lever. Le retour peut être ``n`` ou ``Decimal(str(n))``.
        reject_float(n)

    # Feature: moteur-paie-contrats, Property 2: Rejet universel de `float`
    # dans tout champ `Decimal` (les chaînes convertibles restent acceptées).
    @given(
        st.decimals(
            min_value=Decimal("-100000.00"),
            max_value=Decimal("100000.00"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        )
    )
    @settings(max_examples=200)
    def test_toute_chaine_convertible_est_acceptee(self, d: Decimal) -> None:
        """Requirement 10.2 — chaîne convertible en ``Decimal`` sans passer par ``float``."""
        chaine = str(d)
        # Sanity : pas de notation scientifique, pas de caractères parasites.
        assert re.fullmatch(r"[+-]?[0-9]+(\.[0-9]+)?", chaine), chaine
        reject_float(chaine)  # ne doit pas lever


class TestRejectFloatChainesInvalides:
    """Cas complémentaires du design §3.1 : notation scientifique et
    caractères hors ``[0-9.\\-+]`` sont refusés.

    Ces cas ne sont pas explicitement dans le task 4.1 mais découlent
    directement du design §3.1. On les inclut ici pour verrouiller la
    surface de la fonction, sans multiplier les cas au-delà du strict
    nécessaire.
    """

    @pytest.mark.parametrize(
        "chaine_invalide",
        [
            "1e2",
            "1E2",
            "1.5e-3",
            "1.5E+3",
            "abc",
            "1,00",  # séparateur virgule non supporté
            "12$",
            "NaN",
            "Infinity",
        ],
    )
    def test_chaines_scientifiques_ou_avec_caracteres_hors_alphabet_sont_rejetees(
        self, chaine_invalide: str
    ) -> None:
        with pytest.raises((ValueError, TypeError)):
            reject_float(chaine_invalide)


# ===========================================================================
# Property 4 — Rejet des champs apparentés à des données sensibles (règle 04)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 4: Rejet des champs apparentés à
# des données sensibles (règle 04). *Pour tout* motif de la liste noire des
# données sensibles et *pour toute* variante de casse, d'accentuation et de
# séparateurs (`_`, `-`, espace), l'ajout d'une clé contenant ce motif à la
# construction de `Employee` ou de `PayrollInput` doit lever une erreur de
# validation dont le message renvoie à la règle 04.
#
# **Validates: Requirements 1.3**
# ===========================================================================


# --- Stratégies Hypothesis dédiées à Property 4 -----------------------------

_TABLE_ACCENTS = {
    "a": "àáâãä",
    "e": "éèêë",
    "i": "íìîï",
    "o": "óòôõö",
    "u": "úùûü",
    "c": "ç",
    "n": "ñ",
}


@st.composite
def _casse_variee(draw: st.DrawFn, base: str) -> str:
    """Applique une variation de casse aléatoire caractère à caractère."""
    return "".join(
        draw(st.sampled_from([c.lower(), c.upper()])) if c.isalpha() else c for c in base
    )


@st.composite
def _accents_varies(draw: st.DrawFn, base: str) -> str:
    """Insère aléatoirement des variantes accentuées dans la chaîne.

    L'insensibilité aux accents doit être garantie côté validateur (design
    §3.2 : la liste noire est normalisée « case + accents + séparateurs »).
    """
    resultat: list[str] = []
    for c in base:
        lower = c.lower()
        if lower in _TABLE_ACCENTS and draw(st.booleans()):
            variante = draw(st.sampled_from(list(_TABLE_ACCENTS[lower])))
            resultat.append(variante if c.islower() else variante.upper())
        else:
            resultat.append(c)
    return "".join(resultat)


@st.composite
def _separateurs_varies(draw: st.DrawFn, base: str) -> str:
    """Remplace ``_`` par ``_``, ``-`` ou espace de manière aléatoire."""
    separateur = draw(st.sampled_from(["_", "-", " "]))
    return base.replace("_", separateur)


@st.composite
def _cle_sensible_variee(draw: st.DrawFn) -> str:
    """Génère une clé contenant un motif sensible avec toutes les variations.

    Étapes :
    1. Choisir un motif de la liste noire.
    2. Varier la casse caractère à caractère.
    3. Injecter des accents sur certaines lettres.
    4. Remplacer les ``_`` par ``_``, ``-`` ou espace.
    5. Optionnellement, ajouter un préfixe et un suffixe (recherche
       substring : le motif reste détectable).
    """
    motif = draw(st.sampled_from(MOTIFS_SENSIBLES))
    variee = draw(_casse_variee(motif))
    variee = draw(_accents_varies(variee))
    variee = draw(_separateurs_varies(variee))
    # Bruit optionnel (préfixe / suffixe alphanumériques courts).
    prefixe = draw(st.text(alphabet="abcdef", min_size=0, max_size=3))
    suffixe = draw(st.text(alphabet="xyz0123", min_size=0, max_size=3))
    return f"{prefixe}{variee}{suffixe}"


# --- Tests d'exemple pour Property 4 ---------------------------------------


class TestRejectSensitiveFieldsExemples:
    """Exemples explicites de motifs sensibles refusés à la construction."""

    @pytest.mark.parametrize("motif", MOTIFS_SENSIBLES)
    def test_chaque_motif_de_la_liste_noire_est_rejete(self, motif: str) -> None:
        """Chaque motif exact déclenche le refus (Req 1.3)."""
        with pytest.raises((ValueError, TypeError)) as exc_info:
            reject_sensitive_fields({motif: "valeur_quelconque"})
        assert _message_mentionne_regle_04(exc_info.value), (
            f"Le message d'exception pour le motif '{motif}' doit renvoyer "
            f"explicitement à la règle 04. Reçu : {exc_info.value!s}"
        )

    def test_message_cite_le_nom_de_la_cle_refusee(self) -> None:
        """Le message doit permettre à l'auditeur d'identifier la clé fautive."""
        cle_fautive = "NAS"
        with pytest.raises((ValueError, TypeError)) as exc_info:
            reject_sensitive_fields({cle_fautive: "123-456-789"})
        assert cle_fautive in str(exc_info.value) or cle_fautive.lower() in str(
            exc_info.value
        ).lower(), (
            f"Le message doit citer la clé refusée ('{cle_fautive}'). "
            f"Reçu : {exc_info.value!s}"
        )

    def test_dictionnaire_propre_est_accepte(self) -> None:
        """Un dictionnaire sans motif sensible passe sans erreur."""
        donnees_propres = {
            "id": "EMP001",
            "nom_affichage": "Monitrice EMP001",
            "titre_emploi": "Monitrice",
            "province_travail": "quebec",
        }
        # Ne DOIT PAS lever. Le retour peut être ``donnees_propres`` tel
        # quel ou une version transformée.
        reject_sensitive_fields(donnees_propres)

    def test_dictionnaire_vide_est_accepte(self) -> None:
        """Un dictionnaire vide n'a aucune clé sensible et passe."""
        reject_sensitive_fields({})

    @pytest.mark.parametrize(
        "cle_variante",
        [
            "NAS",
            "Nas",
            "nAs",
            "N.A.S.",  # variante avec ponctuation : la recherche substring
            # reste positive sur "nas".
            "numero-assurance-sociale",
            "numero assurance sociale",
            "NUMERO_ASSURANCE_SOCIALE",
            "compte-bancaire",
            "Compte Bancaire",
            "COURRIEL_PERSONNEL",
            "telephone-personnel",
            "téléphone_personnel",
            "adresse_domicile",  # substring "adresse" présente
            "iban_conjoint",
        ],
    )
    def test_variantes_courantes_sont_rejetees(self, cle_variante: str) -> None:
        """Les variantes typiques de casse / séparateur / accents sont refusées."""
        with pytest.raises((ValueError, TypeError)) as exc_info:
            reject_sensitive_fields({cle_variante: "valeur"})
        assert _message_mentionne_regle_04(exc_info.value), (
            f"Variante '{cle_variante}' : le message doit renvoyer à la "
            f"règle 04. Reçu : {exc_info.value!s}"
        )


# --- Property test Hypothesis pour Property 4 ------------------------------


@pytest.mark.property
class TestRejectSensitiveFieldsProperty:
    """Property 4 (Hypothesis) — variantes de casse/accents/séparateurs."""

    # Feature: moteur-paie-contrats, Property 4: Rejet des champs apparentés
    # à des données sensibles (règle 04).
    @given(cle=_cle_sensible_variee())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.filter_too_much],
    )
    def test_toute_variante_de_motif_sensible_est_rejetee(self, cle: str) -> None:
        """Requirement 1.3 — pour toute variante de motif blacklisté, refus."""
        with pytest.raises((ValueError, TypeError)) as exc_info:
            reject_sensitive_fields({cle: "valeur_arbitraire"})
        assert _message_mentionne_regle_04(exc_info.value), (
            f"Clé '{cle}' : le message d'erreur doit renvoyer à la règle 04. "
            f"Reçu : {exc_info.value!s}"
        )


# ===========================================================================
# Property JSON — Rejet des littéraux JSON non guillemés avec point décimal
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 2 (composante JSON) : le parseur
# `_parse_json_reject_floats` DOIT rejeter tout littéral numérique JSON non
# guillemé contenant un point décimal (même `1.0`, `0.0`), et accepter les
# entiers JSON sans point décimal (`1`, `40`) ainsi que les chaînes guillemées.
#
# **Validates: Requirements 10.1, 13.5**
# ===========================================================================


class TestParseJsonRejectFloatsExemples:
    """Exemples explicites cités par le task 4.1."""

    @pytest.mark.parametrize(
        "json_flottant",
        ["1.0", "0.0", "-1.0", "1516.32", "-1516.32", "0.063", "1.5e2", "1.0e0"],
    )
    def test_litteral_avec_point_decimal_est_rejete(
        self, json_flottant: str
    ) -> None:
        """Requirement 10.1, 13.5 — refus immédiat, fail-fast."""
        with pytest.raises((ValueError, TypeError)):
            _parse_json_reject_floats(json_flottant)

    @pytest.mark.parametrize(
        "json_entier",
        ["0", "1", "27", "40", "1516", "-1", "-1516"],
    )
    def test_litteral_entier_est_accepte(self, json_entier: str) -> None:
        """Requirement 10.1 (exception explicite) — un entier JSON passe."""
        resultat = _parse_json_reject_floats(json_entier)
        # ``resultat`` peut être ``int`` (comportement natif ``json.loads``)
        # ou déjà ``Decimal`` (si le wrapper coerce en aval). Les deux sont
        # conformes au design §3.3.
        assert resultat == int(json_entier)

    @pytest.mark.parametrize(
        "json_chaine",
        ['"1.00"', '"40"', '"1516.32"', '"0.063"'],
    )
    def test_chaine_guillemee_est_acceptee(self, json_chaine: str) -> None:
        """Requirement 13.5 — une valeur guillemée passe sans erreur.

        C'est le format cible pour représenter un ``Decimal`` en JSON
        (voir design §Round-trip JSON déterministe).
        """
        resultat = _parse_json_reject_floats(json_chaine)
        assert isinstance(resultat, str)
        # La chaîne originale (entre guillemets JSON) donne bien la
        # valeur numérique littérale une fois parsée.
        assert resultat == json.loads(json_chaine)

    def test_objet_json_avec_flottant_est_rejete_globalement(self) -> None:
        """Requirement 13.5 — rejet global, non partiel, du document."""
        # Fail-fast : la présence d'UN littéral flottant suffit à faire
        # échouer TOUT le document en cours d'analyse.
        document = '{"taux_rrq": 0.063, "annee": 2026}'
        with pytest.raises((ValueError, TypeError)):
            _parse_json_reject_floats(document)

    def test_objet_json_avec_seulement_entiers_et_chaines_est_accepte(self) -> None:
        """Requirement 13.5 — pas de faux positif sur un JSON propre."""
        document = '{"taux_rrq": "0.063", "annee": 2026, "nb_periodes": 27}'
        resultat = _parse_json_reject_floats(document)
        assert resultat == {"taux_rrq": "0.063", "annee": 2026, "nb_periodes": 27}


@pytest.mark.property
class TestParseJsonRejectFloatsProperty:
    """Property JSON (Hypothesis) — généralisation sur floats et ints."""

    # Feature: moteur-paie-contrats, Property 2 (composante JSON) : rejet des
    # littéraux JSON non guillemés contenant un point décimal.
    @given(
        st.floats(
            allow_nan=False,
            allow_infinity=False,
            allow_subnormal=False,
            min_value=-1_000_000.0,
            max_value=1_000_000.0,
        )
    )
    @settings(max_examples=200)
    def test_tout_litteral_float_json_est_rejete(self, x: float) -> None:
        """Requirement 10.1, 13.5 — pour tout float, la sérialisation JSON
        (non guillemée) est rejetée par le parseur.
        """
        # ``repr(x)`` produit un littéral JSON équivalent (ex. ``0.1``,
        # ``1516.32``). On s'assure qu'il contient bien un point décimal —
        # sinon ce serait un entier JSON et il serait accepté (voir test
        # suivant).
        json_litteral = repr(x)
        assume("." in json_litteral or "e" in json_litteral or "E" in json_litteral)
        with pytest.raises((ValueError, TypeError)):
            _parse_json_reject_floats(json_litteral)

    # Feature: moteur-paie-contrats, Property 2 (composante JSON) : les
    # entiers JSON sans point décimal restent acceptés.
    @given(st.integers(min_value=-1_000_000_000, max_value=1_000_000_000))
    @settings(max_examples=200)
    def test_tout_litteral_entier_json_est_accepte(self, n: int) -> None:
        """Requirement 10.1 (exception explicite) — ``str(int)`` passe toujours."""
        resultat = _parse_json_reject_floats(str(n))
        assert resultat == n
