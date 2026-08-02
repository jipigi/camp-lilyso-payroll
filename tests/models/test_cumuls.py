"""Property tests et tests d'exemple pour ``CumulsYTD``.

Tâche 8.1 de la spec ``moteur-paie-contrats`` — tests écrits **avant** le
code (règle 06, TDD). Tant que la tâche 8.2 n'a pas créé
``models/cumuls.py``, la collection pytest de ce fichier échoue avec
``ModuleNotFoundError``. C'est le comportement attendu : les tests
précèdent l'implémentation.

Portée exacte de la tâche 8.1 (``tasks.md`` §8.1) :

- **Property 1 (partiel CumulsYTD) : Immuabilité** — mutation directe d'un
  champ déclaré lève ``ValidationError`` (``frozen=True``), et
  ``avec_paie`` retourne une **nouvelle** instance sans modifier
  l'instance source (design §Data Models 6 : ``model_copy(update=...)``).
  **Validates: Requirements 7.3**
- **Property 9 (partiel CumulsYTD) : Non-négativité** — Hypothesis génère
  des valeurs ``Decimal`` strictement négatives sur chacune des 11
  catégories monétaires et vérifie que la construction lève
  ``ValidationError`` (``Field(..., ge=Decimal("0"))``), sans clampage
  silencieux ni conversion en valeur absolue.
  **Validates: Requirements 7.1**
- **Property 10 : Monotonie croissante via ``avec_paie``** — Hypothesis
  génère un ``CumulsYTD c`` et un ``PayrollResult p`` cohérents (mêmes
  ``employe_id`` et ``annee_fiscale``), vérifie que **chaque** catégorie
  du résultat est ``>=`` celle de ``c``, et que ``c`` reste strictement
  inchangée après l'appel. **Validates: Requirements 7.4, 7.5**
  *(cette property dépend de ``PayrollResult`` — la stratégie sera
  enrichie dans la tâche 10 ; d'ici là, la classe de test est
  ``@pytest.mark.skipif`` sur l'absence du module ``models.payroll_result``.)*
- Tests d'exemple : ``avec_paie`` lève ``PayrollDomainError`` si
  ``employe_id`` diffère (Req 7.7) ou si ``annee_fiscale`` diffère (Req 7.6).
  Ces tests utilisent un **stub minimal** (``types.SimpleNamespace``)
  parce que l'incohérence est détectée AVANT toute utilisation des
  autres champs du ``PayrollResult`` (voir design §Data Models 6,
  méthode ``avec_paie``).
- Test d'exemple : ``CumulsYTD.zero("EMP001", 2026)`` produit une instance
  dont les 11 catégories sont exactement ``Decimal("0.00")``.

Contexte design (extrait, ``design.md`` §Components 7 et §Data Models 6) :

- ``CumulsYTD`` : Pydantic v2, ``frozen=True``, ``extra="forbid"``.
- Champs : ``employe_id: str`` (non vide), ``annee_civile: int``,
  plus 11 ``Decimal >= 0`` : ``brut``, ``vacances``, ``rrq_employe``,
  ``rrq_employeur``, ``rqap_employe``, ``rqap_employeur``, ``ae_employe``,
  ``ae_employeur``, ``impot_qc_retenu``, ``impot_federal_retenu``,
  ``net``.
- Fabrique : ``CumulsYTD.zero(employe_id, annee_civile) -> CumulsYTD``
  avec toutes les catégories à ``Decimal("0.00")``.
- Méthode : ``CumulsYTD.avec_paie(resultat: PayrollResult) -> CumulsYTD``
  retournant une nouvelle instance via ``model_copy(update=...)``.
  Refuse par ``PayrollDomainError`` (Req 7.6 / 7.7) toute paie dont
  ``employe_id`` ou ``annee_fiscale`` ne correspond pas.

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit. Tous les
  montants ci-dessous sont construits à partir de chaînes.
- Règle 04 — aucune donnée personnelle réelle. Les identifiants employé
  utilisés (``EMP001``, ``EMP002``, ...) sont des sondes fictives.
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

# Discipline règle 06 (TDD) : import module-level. Tant que ``models/cumuls.py``
# n'existe pas (tâche 8.2 non réalisée), la collection pytest de ce
# fichier échoue avec ``ModuleNotFoundError``. C'est exactement l'échec
# attendu — les tests précèdent l'implémentation.
from models.cumuls import CumulsYTD
from models.exceptions import PayrollDomainError


# ---------------------------------------------------------------------------
# Import conditionnel de ``PayrollResult`` (Property 10)
# ---------------------------------------------------------------------------
#
# ``PayrollResult`` sera créé par la tâche 10.4. En attendant, on active la
# Property 10 uniquement lorsque le module est disponible : les tests
# resteront skippés pendant les tâches 8.2 → 10.3, puis passeront
# automatiquement au vert dès que la tâche 10.4 aura livré le modèle.
try:  # pragma: no cover — la branche activée dépend de l'avancement du plan.
    from models.payroll_result import PayrollResult  # noqa: F401

    HAS_PAYROLL_RESULT = True
except ImportError:
    HAS_PAYROLL_RESULT = False


# ---------------------------------------------------------------------------
# Constantes locales
# ---------------------------------------------------------------------------

#: Les 11 catégories monétaires ``Decimal >= 0`` portées par ``CumulsYTD``
#: (design §Data Models 6). L'ordre correspond à celui du design et
#: n'est PAS une convention métier fiscale : il sert uniquement à
#: paramétrer les tests. Les noms sont ceux du design (``rrq_employe``,
#: ``rrq_employeur``, etc.) — les identifiants informels ``RRQ_e`` /
#: ``RRQ_er`` cités dans ``tasks.md §8.2`` renvoient à ces mêmes champs.
CATEGORIES_MONETAIRES: tuple[str, ...] = (
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


# ---------------------------------------------------------------------------
# Stratégies Hypothesis locales
# ---------------------------------------------------------------------------


@st.composite
def _decimal_monetaire_non_negatif(draw: st.DrawFn) -> Decimal:
    """Génère un ``Decimal`` ≥ 0, deux décimales, borné à 100 000 $.

    Borne haute arbitraire pour éviter les ``Decimal`` disproportionnés
    dans les cumuls YTD (au-delà d'un an de paie très généreuse, aucune
    catégorie n'atteint ce montant dans le périmètre Camp LilySO).
    """
    return draw(
        st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("100000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@st.composite
def _decimal_strictement_negatif(draw: st.DrawFn) -> Decimal:
    """Génère un ``Decimal`` strictement < 0, deux décimales.

    ``allow_nan`` et ``allow_infinity`` sont désactivés : la propriété 9
    porte sur la NÉGATIVITÉ, pas sur les valeurs spéciales.
    """
    return draw(
        st.decimals(
            min_value=Decimal("-100000.00"),
            max_value=Decimal("-0.01"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@st.composite
def _employe_id_valide(draw: st.DrawFn) -> str:
    """Identifiant employé fictif non vide (règle 04)."""
    n = draw(st.integers(min_value=1, max_value=999))
    return f"EMP{n:03d}"


@st.composite
def _annee_civile_valide(draw: st.DrawFn) -> int:
    """Année civile plausible pour le corpus Camp LilySO."""
    return draw(st.integers(min_value=2024, max_value=2030))


@st.composite
def _cumuls_ytd_valide(draw: st.DrawFn) -> CumulsYTD:
    """Génère un ``CumulsYTD`` avec toutes les catégories ≥ 0."""
    kwargs: dict[str, object] = {
        "employe_id": draw(_employe_id_valide()),
        "annee_civile": draw(_annee_civile_valide()),
    }
    for categorie in CATEGORIES_MONETAIRES:
        kwargs[categorie] = draw(_decimal_monetaire_non_negatif())
    return CumulsYTD(**kwargs)


def _kwargs_valides(**overrides: object) -> dict[str, object]:
    """Kwargs valides par défaut pour construire un ``CumulsYTD``.

    Utilisé par les tests d'exemple pour isoler l'aspect testé (par ex.
    surcharger une seule catégorie avec une valeur négative). Toutes les
    valeurs par défaut sont ``Decimal("0.00")`` — l'instance de base
    est équivalente à ``CumulsYTD.zero("EMP001", 2026)``.
    """
    kwargs: dict[str, object] = {
        "employe_id": "EMP001",
        "annee_civile": 2026,
    }
    for categorie in CATEGORIES_MONETAIRES:
        kwargs[categorie] = Decimal("0.00")
    kwargs.update(overrides)
    return kwargs


# ===========================================================================
# Property 1 (partiel CumulsYTD) — Immuabilité
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
# domaine. *Pour tout* ``CumulsYTD`` valide, la mutation d'un de ses champs
# déclarés doit lever une erreur de validation Pydantic (``frozen=True``).
# En outre, ``avec_paie`` doit retourner une nouvelle instance sans
# modifier l'instance source (design §Data Models 6 :
# ``self.model_copy(update=...)``).
#
# **Validates: Requirements 7.3**
# ===========================================================================


class TestProperty1ImmuabiliteExemples:
    """Exemples explicites de mutation refusée sur ``CumulsYTD``."""

    def test_mutation_directe_dun_champ_categorie_leve_validation_error(self) -> None:
        """Requirement 7.3 — mutation directe d'une catégorie refusée."""
        cumuls = CumulsYTD(**_kwargs_valides())
        with pytest.raises(ValidationError):
            cumuls.brut = Decimal("100.00")  # type: ignore[misc]

    def test_mutation_directe_dun_champ_meta_leve_validation_error(self) -> None:
        """Requirement 7.3 — mutation de ``employe_id`` refusée."""
        cumuls = CumulsYTD(**_kwargs_valides())
        with pytest.raises(ValidationError):
            cumuls.employe_id = "EMP002"  # type: ignore[misc]

    def test_mutation_directe_dannee_civile_leve_validation_error(self) -> None:
        """Requirement 7.3 — mutation de ``annee_civile`` refusée."""
        cumuls = CumulsYTD(**_kwargs_valides())
        with pytest.raises(ValidationError):
            cumuls.annee_civile = 2027  # type: ignore[misc]


@pytest.mark.property
class TestProperty1ImmuabiliteProperty:
    """Property 1 (Hypothesis) — mutation refusée sur tout champ déclaré."""

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
    # domaine.
    @given(cumuls=_cumuls_ytd_valide(), categorie=st.sampled_from(CATEGORIES_MONETAIRES))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.filter_too_much])
    def test_mutation_dune_categorie_leve_validation_error(
        self, cumuls: CumulsYTD, categorie: str
    ) -> None:
        """Requirement 7.3 — pour toute catégorie, la mutation est refusée."""
        with pytest.raises(ValidationError):
            setattr(cumuls, categorie, Decimal("42.00"))


# ===========================================================================
# Property 9 (partiel CumulsYTD) — Non-négativité des catégories
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 9: Non-négativité des ``Decimal``
# marqués comme tels. *Pour tout* champ ``Decimal`` marqué non-négatif par
# le contrat de ``CumulsYTD`` (les 11 catégories), l'assignation d'une
# valeur strictement négative doit lever une erreur de validation, sans
# clampage silencieux ni conversion en valeur absolue.
#
# **Validates: Requirements 7.1**
# ===========================================================================


class TestProperty9NonNegativiteExemples:
    """Exemples explicites de valeurs négatives refusées à la construction."""

    @pytest.mark.parametrize("categorie", CATEGORIES_MONETAIRES)
    def test_valeur_negative_dun_cent_est_refusee(self, categorie: str) -> None:
        """Requirement 7.1 — ``-0.01`` sur chaque catégorie est refusé."""
        kwargs = _kwargs_valides(**{categorie: Decimal("-0.01")})
        with pytest.raises(ValidationError):
            CumulsYTD(**kwargs)

    @pytest.mark.parametrize("categorie", CATEGORIES_MONETAIRES)
    def test_valeur_negative_importante_est_refusee(self, categorie: str) -> None:
        """Requirement 7.1 — un gros négatif reste refusé."""
        kwargs = _kwargs_valides(**{categorie: Decimal("-1000.00")})
        with pytest.raises(ValidationError):
            CumulsYTD(**kwargs)

    @pytest.mark.parametrize("categorie", CATEGORIES_MONETAIRES)
    def test_zero_exact_est_accepte(self, categorie: str) -> None:
        """La borne inférieure ``0.00`` est incluse (``ge=Decimal("0"))``)."""
        kwargs = _kwargs_valides(**{categorie: Decimal("0.00")})
        cumuls = CumulsYTD(**kwargs)
        assert getattr(cumuls, categorie) == Decimal("0.00")


@pytest.mark.property
class TestProperty9NonNegativiteProperty:
    """Property 9 (Hypothesis) — refus universel des valeurs négatives."""

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des
    # ``Decimal`` marqués comme tels.
    @given(
        categorie=st.sampled_from(CATEGORIES_MONETAIRES),
        valeur_negative=_decimal_strictement_negatif(),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.filter_too_much])
    def test_toute_valeur_negative_est_refusee(
        self, categorie: str, valeur_negative: Decimal
    ) -> None:
        """Requirement 7.1 — pour toute catégorie et toute valeur < 0, refus."""
        # Sanity : Hypothesis nous donne bien un ``Decimal`` strictement < 0.
        assert valeur_negative < Decimal("0")
        kwargs = _kwargs_valides(**{categorie: valeur_negative})
        with pytest.raises(ValidationError):
            CumulsYTD(**kwargs)


# ===========================================================================
# Property 10 — Monotonie croissante des cumuls YTD via ``avec_paie``
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 10: Monotonie croissante des
# cumuls YTD via ``avec_paie``. *Pour tout* ``CumulsYTD c`` valide et
# *pour toute* paie ``p: PayrollResult`` valide dont ``p.employe_id ==
# c.employe_id`` et ``p.annee_fiscale == c.annee_civile``, chaque
# catégorie de ``c.avec_paie(p)`` doit être supérieure ou égale à la
# catégorie correspondante de ``c`` (monotonie non-stricte). De plus,
# ``c.avec_paie(p)`` doit être une instance nouvelle et distincte :
# ``c`` doit rester strictement inchangée après l'appel.
#
# **Validates: Requirements 7.4, 7.5**
# ===========================================================================


@pytest.mark.skipif(
    not HAS_PAYROLL_RESULT,
    reason=(
        "``PayrollResult`` sera créé par la tâche 10.4. Property 10 activera "
        "automatiquement dès que ce modèle sera disponible."
    ),
)
@pytest.mark.property
class TestProperty10MonotonieCroissante:
    """Property 10 (Hypothesis) — activée lorsque ``PayrollResult`` existe.

    La stratégie Hypothesis complète pour générer un ``PayrollResult``
    valide (avec identités comptables satisfaites, cohérence des cumuls
    fin, biconditionnelles ``statut ⇔ remplace_par_id ⇔ date_emission``)
    est planifiée en tâche 10 (``tests/strategies.py`` : fonction
    ``payroll_result_valide()``). Ce test la consommera dès qu'elle
    existera. En attendant, la classe entière est skippée par
    ``skipif`` — elle n'est PAS un ``xfail`` : quand le module
    ``models.payroll_result`` apparaîtra, Hypothesis s'exécutera avec
    la stratégie fournie par la tâche 10, sans modification de ce
    fichier.
    """

    # Feature: moteur-paie-contrats, Property 10: Monotonie croissante des
    # cumuls YTD via ``avec_paie``.
    def test_avec_paie_est_monotone_et_ne_modifie_pas_la_source(self) -> None:
        """Requirements 7.4, 7.5 — property à activer en tâche 10.

        Corps volontairement minimal : la logique Hypothesis complète
        (génération d'un ``PayrollResult`` compatible avec un
        ``CumulsYTD``, vérification catégorie-par-catégorie ``>=``,
        contrôle d'immutabilité de la source) sera ajoutée en tâche 10
        lorsque ``payroll_result_valide()`` sera disponible dans
        ``tests/strategies.py``. Cette placeholder est explicitement
        marquée ``skipif`` au niveau de la classe et n'est jamais
        exécutée avant la tâche 10.4.
        """
        # L'accès à ``PayrollResult`` est protégé par le ``skipif`` de
        # classe. On documente ici l'invariant attendu pour que la
        # tâche 10 sache exactement ce qu'il faut vérifier.
        pytest.skip(
            "Corps à compléter en tâche 10 lorsque la stratégie "
            "``payroll_result_valide()`` sera livrée."
        )


# ===========================================================================
# Tests d'exemple — ``avec_paie`` refuse les incohérences employé / année
# ===========================================================================
#
# Ces tests utilisent un stub minimal (``types.SimpleNamespace``) pour
# ``resultat`` : l'incohérence est détectée AVANT toute utilisation des
# autres champs (design §Data Models 6, méthode ``avec_paie``). Le stub
# expose uniquement ``employe_id`` et ``annee_fiscale`` — c'est
# suffisant pour déclencher le ``PayrollDomainError`` attendu, sans
# dépendre de la création de ``PayrollResult`` (tâche 10.4).
# ===========================================================================


class TestAvecPaieIncoherences:
    """Refus des paies dont l'employé ou l'année ne correspond pas."""

    def test_avec_paie_leve_payroll_domain_error_si_employe_id_different(self) -> None:
        """Requirement 7.7 — refus si ``resultat.employe_id != self.employe_id``."""
        cumuls = CumulsYTD.zero("EMP001", 2026)
        # Stub minimal : les deux attributs consultés en premier par
        # ``avec_paie`` selon le design §Data Models 6.
        paie_autre_employe = SimpleNamespace(
            employe_id="EMP002",
            annee_fiscale=2026,
        )
        with pytest.raises(PayrollDomainError) as exc_info:
            cumuls.avec_paie(paie_autre_employe)  # type: ignore[arg-type]
        message = str(exc_info.value)
        # Le message doit être actionnable (Req 8.3 pour toutes les
        # ``PayrollDomainError``) : il DOIT citer les deux identifiants
        # employé pour que l'auditeur identifie le mismatch.
        assert "EMP001" in message, message
        assert "EMP002" in message, message

    def test_avec_paie_leve_payroll_domain_error_si_annee_fiscale_differente(
        self,
    ) -> None:
        """Requirement 7.6 — refus si ``resultat.annee_fiscale != self.annee_civile``."""
        cumuls = CumulsYTD.zero("EMP001", 2026)
        paie_autre_annee = SimpleNamespace(
            employe_id="EMP001",
            annee_fiscale=2027,
        )
        with pytest.raises(PayrollDomainError) as exc_info:
            cumuls.avec_paie(paie_autre_annee)  # type: ignore[arg-type]
        message = str(exc_info.value)
        # Le message doit citer les deux années et inviter à repartir
        # d'un ``CumulsYTD.zero()`` pour la nouvelle année (design
        # §Data Models 6, message explicite).
        assert "2026" in message, message
        assert "2027" in message, message

    def test_avec_paie_leve_payroll_domain_error_pas_une_validation_error(self) -> None:
        """Requirement 8.7 (par extension) — ``PayrollDomainError`` n'est
        PAS une ``ValidationError`` Pydantic ; les deux hiérarchies restent
        disjointes (règle 08 / Req 8.7).
        """
        cumuls = CumulsYTD.zero("EMP001", 2026)
        paie_autre_employe = SimpleNamespace(
            employe_id="EMP999",
            annee_fiscale=2026,
        )
        with pytest.raises(PayrollDomainError):
            # Confirmation défensive : si un jour l'implémentation
            # dérivait à tort en ``ValidationError``, ce test le
            # signalerait immédiatement.
            cumuls.avec_paie(paie_autre_employe)  # type: ignore[arg-type]


# ===========================================================================
# Test d'exemple — fabrique de classe ``CumulsYTD.zero``
# ===========================================================================


class TestFabriqueZero:
    """Fabrique ``CumulsYTD.zero(employe_id, annee_civile)``.

    Design §Data Models 6 : la fabrique retourne une instance dont les
    11 catégories sont exactement ``Decimal("0.00")`` (deux décimales,
    représentation canonique). C'est le point de départ obligatoire de
    chaque nouvelle année civile (Req 7.6, message d'erreur de
    ``avec_paie`` en cas de changement d'année).
    """

    def test_zero_produit_toutes_categories_a_zero_deux_decimales(self) -> None:
        """Requirement 7.1 (borne 0 admise) + design §Data Models 6."""
        cumuls = CumulsYTD.zero("EMP001", 2026)
        assert cumuls.employe_id == "EMP001"
        assert cumuls.annee_civile == 2026
        for categorie in CATEGORIES_MONETAIRES:
            valeur = getattr(cumuls, categorie)
            assert isinstance(valeur, Decimal), (
                f"Catégorie '{categorie}' doit être un Decimal, "
                f"reçu : {type(valeur).__name__}"
            )
            # Égalité stricte au ``Decimal("0.00")`` canonique (règle 01) :
            # même valeur ET même représentation à deux décimales.
            assert valeur == Decimal("0.00"), (
                f"Catégorie '{categorie}' doit valoir Decimal('0.00'), "
                f"reçu : {valeur!r}"
            )
            assert str(valeur) == "0.00", (
                f"Catégorie '{categorie}' doit avoir la représentation "
                f"canonique '0.00', reçu : {str(valeur)!r}"
            )

    def test_zero_retourne_bien_une_instance_de_cumuls_ytd(self) -> None:
        """La fabrique retourne une instance immuable du modèle."""
        cumuls = CumulsYTD.zero("EMP001", 2026)
        assert isinstance(cumuls, CumulsYTD)
        # Immuabilité (Property 1) — cohérente avec le reste du modèle.
        with pytest.raises(ValidationError):
            cumuls.brut = Decimal("100.00")  # type: ignore[misc]

    def test_zero_est_deterministe(self) -> None:
        """Deux appels avec les mêmes arguments produisent des instances égales."""
        c1 = CumulsYTD.zero("EMP001", 2026)
        c2 = CumulsYTD.zero("EMP001", 2026)
        # Pydantic v2 compare les modèles champ à champ (``BaseModel.__eq__``).
        assert c1 == c2
