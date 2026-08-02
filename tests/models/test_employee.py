"""Property tests et tests d'exemple du modèle ``Employee`` (``models/employee.py``).

Spec de référence : ``moteur-paie-contrats`` — tâche 6.1.
Design de référence : section « Components and Interfaces » §5 et
« Data Models » §4 (``design.md``).

Discipline TDD (règle 06) : ce module de tests est écrit **avant**
l'implémentation. Tant que la tâche 6.2 n'a pas créé
``models/employee.py``, la collection pytest de ce fichier échoue avec
``ModuleNotFoundError``. C'est le comportement attendu — les tests
précèdent le code.

Portée de la tâche 6.1 (``tasks.md`` §6.1) :

- **Property 1** (partiel ``Employee``) : Immuabilité. Hypothesis génère
  des ``Employee`` valides et vérifie que toute mutation d'un champ lève
  ``ValidationError``. **Validates: Requirements 1.6**.
- **Property 3** : Rejet des champs inconnus (``extra="forbid"``).
  Hypothesis génère des noms de champ hors contrat et vérifie que la
  construction échoue. **Validates: Requirements 1.2**.
- **Property 4** (déclenchement sur ``Employee``) : Rejet des champs
  apparentés à des données sensibles (règle 04). Hypothesis génère des
  variantes de casse/accents/séparateurs des motifs blacklistés ;
  construction d'un ``Employee`` avec la clé injectée lève
  ``ValidationError`` avec référence à la règle 04.
  **Validates: Requirements 1.3**.
- **Property 9** (partiel ``Employee``) : Non-négativité des montants.
  Hypothesis génère des valeurs strictement négatives sur les champs
  ``taux_horaire_base`` (contrainte ``>0``), ``montant_total_TP1015_3``,
  ``montant_total_TD1``, ``retenue_additionnelle_QC``,
  ``retenue_additionnelle_federale`` (contrainte ``>=0``) et vérifie le
  rejet à la validation. **Validates: Requirements 4.11 (par extension),
  3.6**.

Tests d'exemple complémentaires (``tasks.md`` §6.1) :

- ``province_travail != QUEBEC`` lève ``UnsupportedPayrollCase`` avec un
  message mentionnant WebRAS et PDOC (Req 1.5, 11.1, 11.6 ; Property 16
  « Contrat des messages d'exception du domaine »).
- ``taux_indemnite_vacances`` hors ``{0.04, 0.06}`` lève
  ``UnsupportedPayrollCase`` (Req 11.3).
- Les 15 champs déclarés par Req 1.1 existent et les montants monétaires
  sont typés ``Decimal`` (aucun ``float``). Le task 6.1 mentionne « 14
  champs » ; la lecture attentive de Req 1.1 et de ``design.md``
  §Data Models 4 donne en réalité 15 champs (``id``, ``nom_affichage``,
  ``date_naissance``, ``province_travail``, ``titre_emploi``,
  ``taux_horaire_base``, ``date_embauche``, ``date_fin_emploi``,
  ``taux_indemnite_vacances``, ``exoneration_TP1015_3``,
  ``exoneration_TD1``, ``montant_total_TP1015_3``, ``montant_total_TD1``,
  ``retenue_additionnelle_QC``, ``retenue_additionnelle_federale``). Ce
  test vérifie la liste exacte de 15 champs conforme au design.

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire ; les tests eux-mêmes n'utilisent
  ``float`` que pour vérifier son rejet à la frontière.
- Règle 03 — périmètre Camp LilySO ; les cas hors matrice lèvent
  ``UnsupportedPayrollCase`` par construction.
- Règle 04 — aucune donnée personnelle réelle. Les motifs sensibles
  testés sont des **noms de champ** blacklistés, pas des valeurs.
  Les identifiants et noms utilisés dans les fixtures sont fictifs
  (``EMP001``, « Monitrice EMP001 »).
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Any

import pydantic
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# Ces imports viennent de modules déjà implémentés par les tâches 2 et 3.
from models.enums import Juridiction
from models.exceptions import UnsupportedPayrollCase

# Import volontairement au niveau module : tant que ``models/employee.py``
# n'existe pas (tâche 6.2 non réalisée), la collection pytest échoue avec
# ``ModuleNotFoundError``. C'est le comportement attendu par la règle 06 —
# les tests précèdent l'implémentation.
from models.employee import Employee  # noqa: E402


# ===========================================================================
# Utilitaires et constantes partagés par les tests
# ===========================================================================


# Liste des 15 champs déclarés par Req 1.1 et §Data Models 4 du design.
# Ce set-source-de-vérité est utilisé par (a) le test d'exemple qui vérifie
# la présence des 15 champs, (b) la stratégie Hypothesis de Property 3 qui
# doit générer des noms de champ **hors** de cette liste.
CHAMPS_DECLARES_EMPLOYEE: tuple[str, ...] = (
    "id",
    "nom_affichage",
    "date_naissance",
    "province_travail",
    "titre_emploi",
    "taux_horaire_base",
    "date_embauche",
    "date_fin_emploi",
    "taux_indemnite_vacances",
    "exoneration_TP1015_3",
    "exoneration_TD1",
    "montant_total_TP1015_3",
    "montant_total_TD1",
    "retenue_additionnelle_QC",
    "retenue_additionnelle_federale",
)


# Champs monétaires (typés ``Decimal``) parmi les 15 déclarés — vérifiés
# par le test d'exemple ``test_champs_monetaires_sont_typés_decimal``.
CHAMPS_MONETAIRES: tuple[str, ...] = (
    "taux_horaire_base",
    "taux_indemnite_vacances",
    "montant_total_TP1015_3",
    "montant_total_TD1",
    "retenue_additionnelle_QC",
    "retenue_additionnelle_federale",
)


# Champs à contrainte ``>= 0`` (non-négativité stricte au sens ``ge``) —
# utilisés par Property 9 pour la génération des valeurs négatives à
# tester.
CHAMPS_NON_NEGATIFS: tuple[str, ...] = (
    "montant_total_TP1015_3",
    "montant_total_TD1",
    "retenue_additionnelle_QC",
    "retenue_additionnelle_federale",
)


# Liste noire des motifs sensibles (règle 04). Dupliquée depuis
# ``tests/models/test_validators.py`` (recommandation du task 6.1 :
# duplication préférable à l'import pour la lisibilité, et pour découpler
# les tests d'Employee de la structure interne de ``_validators``). Toute
# divergence entre cette liste et celle de ``models/_validators.py`` doit
# être considérée comme un bug d'implémentation à corriger côté validateurs.
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


def _normaliser(chaine: str) -> str:
    """Retourne une forme comparable pour recherche substring (règle 04).

    Miroir volontairement simplifié de
    ``models._validators._normaliser_pour_recherche`` : suppression des
    accents, passage en minuscules, retrait de tout caractère hors
    ``[a-z0-9]``. Utilisé UNIQUEMENT côté tests pour construire les
    stratégies Hypothesis (a) qui génèrent des clés sensibles à coup sûr
    (Property 4) et (b) qui **excluent** toute clé sensible pour tester
    ``extra="forbid"`` isolément (Property 3).
    """
    nfkd = unicodedata.normalize("NFKD", chaine)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sans_accents.lower())


_MOTIFS_NORMALISES: tuple[str, ...] = tuple(
    _normaliser(motif) for motif in MOTIFS_SENSIBLES if _normaliser(motif)
)


def _contient_motif_sensible(nom: str) -> bool:
    """``True`` si la forme normalisée de ``nom`` contient un motif sensible."""
    forme = _normaliser(nom)
    return any(motif in forme for motif in _MOTIFS_NORMALISES)


def _message_mentionne_regle_04(exc: BaseException) -> bool:
    """``True`` si le message d'exception renvoie à la règle 04."""
    message = str(exc)
    normalise = (
        unicodedata.normalize("NFKD", message).encode("ASCII", "ignore").decode().lower()
    )
    return bool(re.search(r"(regle|rule)\s*0*4\b", normalise))


def _message_mentionne_webras_et_pdoc(exc: BaseException) -> bool:
    """``True`` si le message d'exception cite explicitement WebRAS ET PDOC.

    Property 16 (« Contrat des messages d'exception du domaine ») exige que
    tout ``UnsupportedPayrollCase`` levé à la frontière renvoie l'utilisateur
    vers les outils officiels de repli. Comparaison insensible à la casse.
    """
    message = str(exc).lower()
    return "webras" in message and "pdoc" in message


# ---------------------------------------------------------------------------
# Fabrique locale d'un ``Employee`` valide (fixtures anonymisées, règle 04)
# ---------------------------------------------------------------------------


#: Dictionnaire de kwargs d'un ``Employee`` valide dans le périmètre Camp
#: LilySO. Toutes les valeurs sont fictives (règle 04). Les tests peuvent
#: repartir de ce squelette et surcharger un seul champ pour isoler la
#: contrainte à vérifier.
KWARGS_VALIDES_MODELE: dict[str, Any] = {
    "id": "EMP001",
    "nom_affichage": "Monitrice EMP001",
    "date_naissance": date(2005, 6, 15),
    "province_travail": Juridiction.QUEBEC,
    "titre_emploi": "Monitrice",
    "taux_horaire_base": Decimal("15.75"),
    "date_embauche": date(2026, 6, 20),
    "date_fin_emploi": None,
    "taux_indemnite_vacances": Decimal("0.04"),
    "exoneration_TP1015_3": False,
    "exoneration_TD1": False,
    "montant_total_TP1015_3": Decimal("18952.00"),
    "montant_total_TD1": Decimal("16452.00"),
    "retenue_additionnelle_QC": Decimal("0.00"),
    "retenue_additionnelle_federale": Decimal("0.00"),
}


def _kwargs_valides(**overrides: Any) -> dict[str, Any]:
    """Retourne des kwargs valides pour ``Employee``, avec surcharges optionnelles."""
    kwargs = dict(KWARGS_VALIDES_MODELE)
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# Stratégies Hypothesis dédiées à ``Employee``
# ---------------------------------------------------------------------------


# Alphabet ASCII lisible pour les identifiants et libellés ; ne contient
# aucun caractère blanchi par ``str_strip_whitespace=True``, ce qui évite
# d'invalider ``min_length=1`` par accident.
_ALPHABET_TEXTE = st.characters(
    min_codepoint=0x41,  # 'A'
    max_codepoint=0x7A,  # 'z'
    whitelist_categories=("Lu", "Ll", "Nd"),
)


_DATE_MIN = date(1950, 1, 1)
_DATE_MAX = date(2035, 12, 31)


@st.composite
def _decimal_monetaire_positif(draw: st.DrawFn) -> Decimal:
    """``Decimal`` > 0 à deux décimales, borné à 500 $/h."""
    d = draw(
        st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("500.00"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        )
    )
    return d


@st.composite
def _decimal_monetaire_non_negatif(draw: st.DrawFn) -> Decimal:
    """``Decimal`` >= 0 à deux décimales, borné à 100 000 $."""
    d = draw(
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("100000.00"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        )
    )
    return d


@st.composite
def _employee_kwargs_valides(draw: st.DrawFn) -> dict[str, Any]:
    """Génère un ``dict`` de kwargs qui construit toujours un ``Employee`` valide.

    Contraintes appliquées par construction (voir Req 1.1, 1.5, 1.6,
    Req 11.1, Req 11.3 et §Data Models 4 du design) :

    - ``province_travail = QUEBEC`` (règle 03) ;
    - ``taux_indemnite_vacances ∈ {0.04, 0.06}`` (Req 11.3) ;
    - ``taux_horaire_base > 0`` ;
    - montants ``>= 0`` ;
    - identifiants et libellés non vides après strip
      (``str_strip_whitespace=True``).
    """
    id_ = draw(st.text(alphabet=_ALPHABET_TEXTE, min_size=1, max_size=20))
    nom_affichage = draw(st.text(alphabet=_ALPHABET_TEXTE, min_size=1, max_size=40))
    titre_emploi = draw(st.text(alphabet=_ALPHABET_TEXTE, min_size=1, max_size=40))
    date_naissance = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_embauche = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    # ``date_fin_emploi`` : soit ``None``, soit une date >= ``date_embauche``.
    fin = draw(
        st.one_of(
            st.none(),
            st.dates(min_value=date_embauche, max_value=_DATE_MAX),
        )
    )
    return {
        "id": id_,
        "nom_affichage": nom_affichage,
        "date_naissance": date_naissance,
        "province_travail": Juridiction.QUEBEC,
        "titre_emploi": titre_emploi,
        "taux_horaire_base": draw(_decimal_monetaire_positif()),
        "date_embauche": date_embauche,
        "date_fin_emploi": fin,
        "taux_indemnite_vacances": draw(
            st.sampled_from([Decimal("0.04"), Decimal("0.06")])
        ),
        "exoneration_TP1015_3": draw(st.booleans()),
        "exoneration_TD1": draw(st.booleans()),
        "montant_total_TP1015_3": draw(_decimal_monetaire_non_negatif()),
        "montant_total_TD1": draw(_decimal_monetaire_non_negatif()),
        "retenue_additionnelle_QC": draw(_decimal_monetaire_non_negatif()),
        "retenue_additionnelle_federale": draw(_decimal_monetaire_non_negatif()),
    }


# ===========================================================================
# Tests d'exemple — Structure du modèle (Req 1.1)
# ===========================================================================


class TestEmployeeChampsDeclares:
    """Vérifie la liste exacte des 15 champs déclarés par Req 1.1.

    Le task 6.1 parle de « 14 champs » ; la lecture attentive de Req 1.1
    et de ``design.md`` §Data Models 4 donne en réalité 15 champs. Ce test
    ancre la vérité contractuelle telle qu'écrite dans la spec.
    """

    def test_les_15_champs_declares_existent_exactement(self) -> None:
        """Req 1.1, Req 1.2 (``extra="forbid"`` implique liste close)."""
        champs = set(Employee.model_fields.keys())
        attendus = set(CHAMPS_DECLARES_EMPLOYEE)
        # Aucun champ manquant.
        manquants = attendus - champs
        assert not manquants, (
            f"Employee doit exposer les champs Req 1.1. Manquants : {manquants!r}."
        )
        # Aucun champ supplémentaire non-documenté.
        superflus = champs - attendus
        assert not superflus, (
            f"Employee expose des champs non prévus par Req 1.1 : {superflus!r}."
        )
        # Sanity : le compte est bien 15 (spec Req 1.1 exhaustive).
        assert len(champs) == 15, f"Attendu 15 champs, reçu {len(champs)}."

    @pytest.mark.parametrize("nom_champ", CHAMPS_MONETAIRES)
    def test_champs_monetaires_sont_typés_decimal(self, nom_champ: str) -> None:
        """Req 1.4, Req 10.1 — aucun montant monétaire n'est typé ``float``."""
        info = Employee.model_fields[nom_champ]
        annotation = info.annotation
        # L'annotation doit être exactement ``Decimal``, jamais ``float`` ni
        # ``Union[..., float, ...]``. On teste par identité de type et par
        # exclusion explicite de ``float`` dans le graphe d'annotation.
        assert annotation is Decimal, (
            f"Champ '{nom_champ}' : annotation attendue `Decimal`, reçue "
            f"{annotation!r} (règle 01, Req 1.4)."
        )
        # Double-verrou : le nom "float" ne DOIT apparaître nulle part
        # dans la repr de l'annotation.
        assert "float" not in repr(annotation).lower(), (
            f"Champ '{nom_champ}' : le type '{annotation!r}' contient 'float' "
            f"(règle 01 violée)."
        )

    def test_construction_valide_reussit(self) -> None:
        """Sanity — les kwargs modèles produisent bien un ``Employee`` valide.

        Ce test verrouille la fabrique locale ``KWARGS_VALIDES_MODELE`` :
        si un jour Employee introduit une nouvelle contrainte incompatible
        avec ces valeurs anonymisées, ce test échouera **avant** les
        properties, ce qui pointera directement la régression.
        """
        emp = Employee(**KWARGS_VALIDES_MODELE)
        assert emp.id == "EMP001"
        assert emp.province_travail is Juridiction.QUEBEC
        assert emp.taux_indemnite_vacances == Decimal("0.04")


# ===========================================================================
# Tests d'exemple — Refus à la frontière (Req 1.5, 11.1, 11.3, 11.6)
# ===========================================================================


class TestEmployeeFrontiereHorsMatrice:
    """Refus fail-fast des cas hors matrice Camp LilySO (règle 03)."""

    def test_province_non_quebec_leve_unsupported_payroll_case(self) -> None:
        """Req 1.5, Req 11.1 — province ``CANADA`` refusée.

        Le message DOIT mentionner WebRAS ET PDOC (Req 11.6, Property 16
        « Contrat des messages d'exception du domaine »).
        """
        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            Employee(**_kwargs_valides(province_travail=Juridiction.CANADA))
        assert _message_mentionne_webras_et_pdoc(exc_info.value), (
            "Le message d'UnsupportedPayrollCase pour une province ≠ QC doit "
            "renvoyer explicitement vers WebRAS ET PDOC (Req 11.6). "
            f"Reçu : {exc_info.value!s}"
        )

    @pytest.mark.parametrize(
        "taux_invalide",
        [
            Decimal("0.00"),
            Decimal("0.03"),
            Decimal("0.05"),
            Decimal("0.07"),
            Decimal("0.10"),
            Decimal("1.00"),
        ],
        ids=[
            "zero",
            "trois_pourcent",
            "cinq_pourcent",
            "sept_pourcent",
            "dix_pourcent",
            "cent_pourcent",
        ],
    )
    def test_taux_vacances_hors_ensemble_leve_unsupported(
        self, taux_invalide: Decimal
    ) -> None:
        """Req 11.3 — taux de vacances ∉ ``{0.04, 0.06}`` refusé.

        Camp LilySO applique 4 % aux nouvelles saisons et 6 % à partir de
        la troisième année de service. Toute autre valeur est hors matrice.
        """
        with pytest.raises(UnsupportedPayrollCase):
            Employee(**_kwargs_valides(taux_indemnite_vacances=taux_invalide))

    def test_taux_vacances_004_est_accepte(self) -> None:
        """Sanity — la borne basse ``0.04`` de Req 11.3 est admise."""
        emp = Employee(
            **_kwargs_valides(taux_indemnite_vacances=Decimal("0.04"))
        )
        assert emp.taux_indemnite_vacances == Decimal("0.04")

    def test_taux_vacances_006_est_accepte(self) -> None:
        """Sanity — la borne haute ``0.06`` de Req 11.3 est admise."""
        emp = Employee(
            **_kwargs_valides(taux_indemnite_vacances=Decimal("0.06"))
        )
        assert emp.taux_indemnite_vacances == Decimal("0.06")


# ===========================================================================
# Property 1 (partielle Employee) — Immuabilité (Req 1.6)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
# domaine. *Pour tout* Employee valide, la mutation d'un champ déclaré
# doit lever une erreur de validation Pydantic (frozen=True).
#
# **Validates: Requirements 1.6**
# ===========================================================================


@pytest.mark.property
class TestEmployeeImmuabiliteProperty:
    """Property 1 (Hypothesis) — ``frozen=True`` sur ``Employee``."""

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
    # domaine — instance Employee, mutation d'un champ arbitraire refusée.
    @given(
        kwargs=_employee_kwargs_valides(),
        champ_a_muter=st.sampled_from(CHAMPS_DECLARES_EMPLOYEE),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_toute_mutation_dun_champ_leve_validation_error(
        self, kwargs: dict[str, Any], champ_a_muter: str
    ) -> None:
        """Requirement 1.6 — ``frozen=True`` sur tout champ, sans exception."""
        emp = Employee(**kwargs)
        # Pydantic v2 lève ``ValidationError`` (avec ``type='frozen_instance'``
        # ou ``'frozen_field'``) sur toute assignation d'attribut post-
        # construction lorsque ``frozen=True``. Le type exact de la nouvelle
        # valeur n'importe pas : c'est l'acte de mutation qui est refusé.
        with pytest.raises(pydantic.ValidationError):
            setattr(emp, champ_a_muter, getattr(emp, champ_a_muter))


class TestEmployeeImmuabiliteExemples:
    """Cas explicites de mutation refusée — verrouillent les champs critiques."""

    def test_mutation_id_leve(self) -> None:
        emp = Employee(**KWARGS_VALIDES_MODELE)
        with pytest.raises(pydantic.ValidationError):
            emp.id = "EMP002"  # type: ignore[misc]

    def test_mutation_taux_horaire_base_leve(self) -> None:
        emp = Employee(**KWARGS_VALIDES_MODELE)
        with pytest.raises(pydantic.ValidationError):
            emp.taux_horaire_base = Decimal("20.00")  # type: ignore[misc]

    def test_mutation_montant_total_TP1015_3_leve(self) -> None:
        emp = Employee(**KWARGS_VALIDES_MODELE)
        with pytest.raises(pydantic.ValidationError):
            emp.montant_total_TP1015_3 = Decimal("999.99")  # type: ignore[misc]


# ===========================================================================
# Property 3 — Rejet des champs inconnus (``extra="forbid"``) (Req 1.2)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 3: Rejet universel des champs
# inconnus (`extra="forbid"`). *Pour tout* nom de champ non déclaré dans
# le contrat Employee (et ne contenant AUCUN motif sensible — sinon
# c'est Property 4 qui déclenche), la construction avec ce champ
# additionnel doit lever une erreur de validation.
#
# **Validates: Requirements 1.2**
# ===========================================================================


@st.composite
def _nom_champ_inconnu_non_sensible(draw: st.DrawFn) -> str:
    """Génère un nom de champ hors contrat qui NE contient AUCUN motif sensible.

    Cette contrainte est essentielle pour isoler Property 3 : si le nom
    généré contenait un motif blacklisté (Property 4), le rejet
    proviendrait de ``reject_sensitive_fields`` en amont plutôt que de
    ``extra="forbid"``. Les deux propriétés doivent pouvoir échouer
    indépendamment pour permettre le diagnostic.
    """
    # Alphabet sûr : minuscules + chiffres uniquement. Suffisant pour
    # explorer un large espace tout en gardant l'espace lisible.
    nom = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=(),
                whitelist_characters="abcdefghijklmnopqrstuvwxyz0123456789_",
            ),
            min_size=1,
            max_size=25,
        )
    )
    # Exclusion (a) : ne pas générer un champ déjà déclaré (sinon la
    # construction réussit et la property est fausse par erreur de setup).
    assume(nom not in CHAMPS_DECLARES_EMPLOYEE)
    # Exclusion (b) : ne pas générer un champ sensible (isolation vs. P4).
    assume(not _contient_motif_sensible(nom))
    # Exclusion (c) : garder la lisibilité — au moins un caractère non-``_``
    # pour éviter les cas dégénérés ``_``, ``__``, etc. qui restent valides
    # mais peu informatifs.
    assume(any(c != "_" for c in nom))
    return nom


@pytest.mark.property
class TestEmployeeExtraForbidProperty:
    """Property 3 (Hypothesis) — ``extra="forbid"`` sur ``Employee``."""

    # Feature: moteur-paie-contrats, Property 3: Rejet universel des champs
    # inconnus (`extra="forbid"`).
    @given(
        kwargs=_employee_kwargs_valides(),
        nom_inconnu=_nom_champ_inconnu_non_sensible(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_tout_champ_inconnu_leve_validation_error(
        self, kwargs: dict[str, Any], nom_inconnu: str
    ) -> None:
        """Requirement 1.2 — ``extra="forbid"`` refuse tout champ non déclaré."""
        kwargs_pollues = dict(kwargs)
        kwargs_pollues[nom_inconnu] = "valeur_arbitraire"
        with pytest.raises(pydantic.ValidationError):
            Employee(**kwargs_pollues)


class TestEmployeeExtraForbidExemples:
    """Cas explicites de champ hors contrat — verrouillent le comportement."""

    @pytest.mark.parametrize(
        "champ_inconnu",
        [
            "champ_inexistant",
            "salaire_annuel",  # non déclaré : c'est un champ dérivé
            "poste",  # doublon linguistique de titre_emploi mais nom distinct
            "notes",
            "commentaire_rh",
            "identifiant_dossier",
        ],
    )
    def test_champ_inconnu_documente_est_refuse(self, champ_inconnu: str) -> None:
        """Sanity — la liste des champs Req 1.1 est effectivement close."""
        # Ces noms sont volontairement plausibles mais non déclarés — ils
        # matérialisent la tentation « et si on ajoutait ce champ juste
        # pour ce cas ? » que ``extra="forbid"`` interdit.
        assert champ_inconnu not in CHAMPS_DECLARES_EMPLOYEE, (
            f"Le test suppose que '{champ_inconnu}' n'est PAS un champ "
            "déclaré ; si Req 1.1 est étendu, mettre à jour ce test."
        )
        assert not _contient_motif_sensible(champ_inconnu), (
            f"Le test suppose que '{champ_inconnu}' ne contient PAS de "
            "motif sensible (sinon on testerait Property 4)."
        )
        kwargs_pollues = _kwargs_valides(**{champ_inconnu: "valeur"})
        with pytest.raises(pydantic.ValidationError):
            Employee(**kwargs_pollues)


# ===========================================================================
# Property 4 — Rejet des champs apparentés à des données sensibles (Req 1.3)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 4: Rejet des champs apparentés
# à des données sensibles (règle 04) — déclenchement sur Employee.
# *Pour tout* motif de la liste noire et *pour toute* variante de casse,
# d'accentuation et de séparateurs, la construction d'un Employee avec
# cette clé additionnelle doit lever une erreur de validation dont le
# message renvoie à la règle 04.
#
# **Validates: Requirements 1.3**
# ===========================================================================


# --- Stratégies Hypothesis dédiées à Property 4 (miroir de test_validators) --

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
    return "".join(
        draw(st.sampled_from([c.lower(), c.upper()])) if c.isalpha() else c for c in base
    )


@st.composite
def _accents_varies(draw: st.DrawFn, base: str) -> str:
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
    separateur = draw(st.sampled_from(["_", "-", " "]))
    return base.replace("_", separateur)


@st.composite
def _cle_sensible_variee(draw: st.DrawFn) -> str:
    """Génère une clé contenant un motif sensible avec variations complètes.

    Étapes :

    1. Choisir un motif blacklisté.
    2. Varier la casse caractère par caractère.
    3. Injecter des accents sur certaines lettres.
    4. Remplacer ``_`` par ``_``, ``-`` ou espace.
    5. Ajouter éventuellement un préfixe et un suffixe (la détection est
       une recherche substring : le motif reste détectable).
    """
    motif = draw(st.sampled_from(MOTIFS_SENSIBLES))
    variee = draw(_casse_variee(motif))
    variee = draw(_accents_varies(variee))
    variee = draw(_separateurs_varies(variee))
    prefixe = draw(st.text(alphabet="abcdef", min_size=0, max_size=3))
    suffixe = draw(st.text(alphabet="xyz0123", min_size=0, max_size=3))
    return f"{prefixe}{variee}{suffixe}"


@pytest.mark.property
class TestEmployeeChampsSensiblesProperty:
    """Property 4 (Hypothesis) — refus des motifs sensibles sur ``Employee``."""

    # Feature: moteur-paie-contrats, Property 4: Rejet des champs apparentés
    # à des données sensibles (règle 04) — déclenchement sur Employee.
    @given(
        kwargs=_employee_kwargs_valides(),
        cle_sensible=_cle_sensible_variee(),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_toute_variante_dun_motif_sensible_est_refusee(
        self, kwargs: dict[str, Any], cle_sensible: str
    ) -> None:
        """Requirement 1.3 — refus + message renvoyant à la règle 04."""
        # Filtre défensif : si la variante générée coïncide accidentellement
        # avec un champ déclaré (improbable vu les motifs blacklistés, mais
        # possible pour ``date_naissance_reelle`` → ``date_naissance`` ?),
        # on renonce à l'exemple courant. Ceci n'affecte pas la couverture
        # de la propriété — Hypothesis en produira suffisamment d'autres.
        assume(cle_sensible not in CHAMPS_DECLARES_EMPLOYEE)
        kwargs_pollues = dict(kwargs)
        kwargs_pollues[cle_sensible] = "valeur_arbitraire"
        with pytest.raises(pydantic.ValidationError) as exc_info:
            Employee(**kwargs_pollues)
        # Le message ``ValidationError`` de Pydantic v2 inclut la chaîne
        # levée par le model_validator sous-jacent (``ValueError`` de
        # ``reject_sensitive_fields``). On vérifie que la référence à la
        # règle 04 est bien préservée à travers le wrapping Pydantic.
        assert _message_mentionne_regle_04(exc_info.value), (
            f"Clé sensible '{cle_sensible}' : le message doit renvoyer à "
            f"la règle 04 (règle steering). Reçu : {exc_info.value!s}"
        )


class TestEmployeeChampsSensiblesExemples:
    """Cas explicites de motif sensible refusé à la construction d'Employee."""

    @pytest.mark.parametrize(
        "cle_sensible",
        [
            "nas",
            "NAS",
            "sin",
            "numero_assurance_sociale",
            "numero-assurance-sociale",
            "compte_bancaire",
            "iban",
            "adresse_domicile",
            "courriel_personnel",
            "telephone_personnel",
            "téléphone_personnel",
        ],
    )
    def test_motif_sensible_courant_est_refuse(self, cle_sensible: str) -> None:
        """Requirement 1.3 — motifs typiques de la règle 04."""
        kwargs_pollues = _kwargs_valides(**{cle_sensible: "valeur"})
        with pytest.raises(pydantic.ValidationError) as exc_info:
            Employee(**kwargs_pollues)
        assert _message_mentionne_regle_04(exc_info.value), (
            f"Motif '{cle_sensible}' : message attendu renvoyant à la "
            f"règle 04. Reçu : {exc_info.value!s}"
        )


# ===========================================================================
# Property 9 (partielle Employee) — Non-négativité (Req 3.6, 4.11 par extension)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 9: Non-négativité des `Decimal`
# marqués comme tels — champs monétaires d'Employee. *Pour toute* valeur
# strictement négative sur `taux_horaire_base` (contrainte `> 0`),
# `montant_total_TP1015_3`, `montant_total_TD1`, `retenue_additionnelle_QC`,
# `retenue_additionnelle_federale` (contraintes `>= 0`), la construction
# doit lever une erreur de validation, sans clampage silencieux.
#
# **Validates: Requirements 4.11 (par extension), 3.6**
# ===========================================================================


@st.composite
def _decimal_strictement_negatif(draw: st.DrawFn) -> Decimal:
    """``Decimal`` strictement < 0, deux décimales."""
    return draw(
        st.decimals(
            min_value=Decimal("-100000.00"),
            max_value=Decimal("-0.01"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        )
    )


@pytest.mark.property
class TestEmployeeNonNegativiteProperty:
    """Property 9 (Hypothesis) — refus des valeurs négatives sur les montants."""

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des `Decimal`
    # marqués comme tels — Employee, champs `>= 0`.
    @given(
        kwargs=_employee_kwargs_valides(),
        champ_non_negatif=st.sampled_from(CHAMPS_NON_NEGATIFS),
        valeur_negative=_decimal_strictement_negatif(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_toute_valeur_negative_sur_un_montant_ge_zero_leve(
        self,
        kwargs: dict[str, Any],
        champ_non_negatif: str,
        valeur_negative: Decimal,
    ) -> None:
        """Requirement 4.11 (par extension) — refus sans clampage."""
        kwargs_pollues = dict(kwargs)
        kwargs_pollues[champ_non_negatif] = valeur_negative
        with pytest.raises(pydantic.ValidationError):
            Employee(**kwargs_pollues)

    # Feature: moteur-paie-contrats, Property 9: Non-négativité — cas
    # `taux_horaire_base` (contrainte `> 0` : refus strict à 0 et en négatif).
    @given(
        kwargs=_employee_kwargs_valides(),
        taux_non_positif=st.one_of(
            st.just(Decimal("0.00")),
            _decimal_strictement_negatif(),
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_taux_horaire_non_positif_leve(
        self, kwargs: dict[str, Any], taux_non_positif: Decimal
    ) -> None:
        """Design §Data Models 4 — ``taux_horaire_base: Decimal = Field(..., gt=0)``."""
        kwargs_pollues = dict(kwargs)
        kwargs_pollues["taux_horaire_base"] = taux_non_positif
        with pytest.raises(pydantic.ValidationError):
            Employee(**kwargs_pollues)


class TestEmployeeNonNegativiteExemples:
    """Cas explicites de valeur négative — verrouillent les bornes de Req 3.6/4.11."""

    @pytest.mark.parametrize("champ", CHAMPS_NON_NEGATIFS)
    def test_moins_un_cent_est_refuse_sur_les_montants_non_negatifs(
        self, champ: str
    ) -> None:
        """Requirement 4.11 — la borne à ``0`` est stricte, ``-0.01`` refusé."""
        kwargs = _kwargs_valides(**{champ: Decimal("-0.01")})
        with pytest.raises(pydantic.ValidationError):
            Employee(**kwargs)

    @pytest.mark.parametrize("champ", CHAMPS_NON_NEGATIFS)
    def test_zero_est_accepte_sur_les_montants_non_negatifs(self, champ: str) -> None:
        """Sanity — la borne inférieure ``Decimal("0.00")`` reste incluse."""
        kwargs = _kwargs_valides(**{champ: Decimal("0.00")})
        emp = Employee(**kwargs)
        assert getattr(emp, champ) == Decimal("0.00")

    def test_taux_horaire_zero_est_refuse(self) -> None:
        """Design §Data Models 4 — ``taux_horaire_base > 0`` (strict)."""
        with pytest.raises(pydantic.ValidationError):
            Employee(**_kwargs_valides(taux_horaire_base=Decimal("0.00")))

    def test_taux_horaire_negatif_est_refuse(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            Employee(**_kwargs_valides(taux_horaire_base=Decimal("-15.00")))
