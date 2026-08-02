"""Property tests et tests d'exemple pour ``PayrollResult`` et ses sous-modèles.

Tâche 10.1 de la spec ``moteur-paie-contrats`` — tests écrits **avant** le
code (règle 06, TDD). Tant que la tâche 10.2 / 10.3 / 10.4 n'a pas créé
``models/payroll_result.py``, la collection pytest de ce fichier échoue
avec ``ModuleNotFoundError``. C'est le comportement attendu — les tests
précèdent l'implémentation.

Portée exacte de la tâche 10.1 (``tasks.md`` §10.1) :

- **Property 1 (partiel PayrollResult, GainsDecomposes, MontantAvecTrace,
  RetenuesEmploye, CotisationsEmployeur) : Immuabilité** — toute mutation
  d'un champ déclaré lève ``ValidationError`` (``frozen=True``).
  **Validates: Requirements 4.12, 6.2**
- **Property 7 : Identité brute** — Hypothesis construit des triplets
  ``(brut, retenues, net)`` cohérents (``net + total_retenues ==
  brut_total``) et incohérents ; les cohérents passent, les incohérents
  lèvent ``ValidationError``.
  **Validates: Requirements 4.4, 4.9**
- **Property 8 : Identité coût employeur** — Hypothesis idem sur
  ``cout_employeur == brut + total_cotisations``.
  **Validates: Requirements 4.5, 4.10**
- **Property 9 (partiel PayrollResult) : Non-négativité** des retenues
  et cotisations sur les cinq ``MontantAvecTrace`` de ``RetenuesEmploye``
  ainsi que les six ``MontantAvecTrace`` de ``CotisationsEmployeur``,
  plus les deux totaux.
  **Validates: Requirements 4.11**
- **Property 11 : Biconditionnelle ``statut ⟺ remplace_par_id ⟺
  date_emission``** — parametrize explicitement les 4×2×2 = 16
  combinaisons et vérifie qu'exactement les combinaisons valides passent.
  **Validates: Requirements 6.3, 6.4, 6.5, 6.7**
- Tests d'exemple :
  - ``total_retenues_employe`` incohérent avec la somme des retenues
    effectivement retenues (RRQ + RQAP + AE + impôt QC retenu + impôt
    fédéral retenu) lève ``ValidationError``.
  - ``total_cotisations_employeur`` incohérent avec la somme des six
    cotisations employeur lève ``ValidationError``.
  - ``multiplicateur_heures_supp`` et ``seuil_heures_supp_hebdo`` sont
    reçus du module de calcul (design §Data Models 9, Req 4.14) — jamais
    recalculés par ``GainsDecomposes``.
  - ``cumuls_fin.employe_id != employe_id`` ou ``cumuls_fin.annee_civile
    != annee_fiscale`` lève ``ValidationError``.
  - ``version >= 1`` et ``id_paie`` non vide.

Contexte design (extrait, ``design.md`` §Components 9 et §Data Models 9) :

- ``GainsDecomposes`` : ``frozen``, ``extra="forbid"``. 7 champs :
  ``salaire_regulier``, ``heures_supplementaires_montant``, ``vacances``,
  ``jours_feries_manuels``, ``brut_total`` (tous ``Decimal >= 0``),
  ``multiplicateur_heures_supp`` (``Decimal > 0``),
  ``seuil_heures_supp_hebdo`` (``Decimal > 0``).
- ``MontantAvecTrace`` : ``frozen``, ``extra="forbid"``. Champs
  ``montant: Decimal >= 0`` et ``trace: CalculationTrace``.
- ``RetenuesEmploye`` : ``frozen``, ``extra="forbid"``. 7
  ``MontantAvecTrace`` (RRQ, RQAP, AE, impôt QC formule, impôt QC retenu,
  impôt fédéral formule, impôt fédéral retenu) + ``total_retenues_employe:
  Decimal >= 0``. L'invariant du design impose
  ``total_retenues_employe == rrq.montant + rqap.montant + ae.montant +
  impot_qc_retenu.montant + impot_federal_retenu.montant`` (les
  ``*_formule`` NE comptent PAS dans le total — Req 12.8).
- ``CotisationsEmployeur`` : ``frozen``, ``extra="forbid"``. 6
  ``MontantAvecTrace`` (RRQ employeur, RQAP employeur, AE employeur,
  FSS, CNESST, CNT) + drapeau ``cnesst_en_attente_classification: bool``
  + ``total_cotisations_employeur: Decimal >= 0``. Invariant : total =
  somme des 6.
- ``PayrollResult`` : ``frozen``, ``extra="forbid"``. Champs ``id_paie``,
  ``version >= 1``, ``employe_id``, ``annee_fiscale``, ``pay_period``,
  ``gains``, ``retenues_employe``, ``cotisations_employeur``, ``net``,
  ``cout_employeur``, ``cumuls_fin``, ``statut``, ``remplace_par_id: str
  | None``, ``date_creation: datetime``, ``date_emission: datetime |
  None``. Invariants ``model_validator(mode="after")`` :

  1. Identités comptables (Req 4.9, 4.10).
  2. Biconditionnelle statut ⟺ remplace_par_id (Req 6.3–6.5) + implication
     statut ∈ {EMISE, ANNULEE, REMPLACE_PAR} ⟹ date_emission renseignée
     (Req 6.7).
  3. Cohérence ``cumuls_fin`` : ``employe_id`` et année alignés avec
     ``PayrollResult``.

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit dans les tests.
- Règle 02 — chaque ``CalculationTrace`` construite ici utilise une
  source officielle de la liste blanche (``TP-1015.F 2026``).
- Règle 04 — identifiants employé fictifs (``EMP001``).
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

# Discipline règle 06 (TDD) : import module-level. Tant que
# ``models/payroll_result.py`` n'existe pas (tâches 10.2/10.3/10.4 non
# réalisées), la collection pytest de ce fichier échoue avec
# ``ModuleNotFoundError``. C'est exactement l'échec attendu — les tests
# précèdent l'implémentation.
from models.cumuls import CumulsYTD
from models.enums import FrequencePaie, Juridiction, ModeArrondissement, StatutDePaie
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
    PayrollResult,
    RetenuesEmploye,
)
from models.trace import CalculationTrace


# ===========================================================================
# Fabriques locales de sous-modèles valides
# ===========================================================================
#
# Ces fabriques évitent de dupliquer la construction des sous-modèles
# dans chaque test. Elles sont volontairement locales à ce fichier
# (pas de partage via ``tests/strategies.py``) car elles portent des
# détails d'implémentation propres à ``PayrollResult`` — au premier
# scénario partagé (tâche 14, golden tests QC001–QC006), la
# consolidation sera faite.
#
# Toutes les valeurs par défaut :
#
# - respectent la règle 01 (``Decimal`` construit depuis chaînes) ;
# - respectent la règle 02 (source ``CalculationTrace`` conforme à la
#   liste blanche : ``TP-1015.F 2026``) ;
# - respectent la règle 04 (identifiants employé fictifs).
# ===========================================================================


def _make_trace(resultat: Decimal = Decimal("0.00")) -> CalculationTrace:
    """Fabrique une ``CalculationTrace`` valide minimale.

    La source est ancrée à ``TP-1015.F 2026`` (formulaire officiel de
    la liste blanche du design §Components 4). Le résultat scalaire
    est passé par l'appelant pour permettre d'aligner la trace sur le
    montant du ``MontantAvecTrace`` associé (bonne pratique, sans être
    imposée par le contrat).
    """
    return CalculationTrace(
        source="TP-1015.F 2026",
        annee=2026,
        juridiction=Juridiction.QUEBEC,
        section="Section fixture",
        parametres_utilises={},
        entrees={},
        sous_totaux={},
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=resultat,
    )


def _make_montant(montant: Decimal) -> MontantAvecTrace:
    """Fabrique un ``MontantAvecTrace`` valide (règle 01 + règle 02)."""
    return MontantAvecTrace(montant=montant, trace=_make_trace(montant))


def _make_pay_period() -> PayPeriod:
    """Fabrique une ``PayPeriod`` valide aux deux semaines (2026-06-01 → 2026-06-14).

    Deux ``WeekSegment`` de 7 jours contigus, sans heures pour éviter
    tout couplage avec les valeurs de gains testées ailleurs.
    ``nb_periodes_annuelles=27`` reflète le calendrier Camp LilySO 2026
    (année à 27 paies bi-hebdomadaires — voir Req 2.7).
    """
    debut = date(2026, 6, 1)
    fin = debut + timedelta(days=13)
    semaine_1 = WeekSegment(
        date_debut=debut,
        date_fin=debut + timedelta(days=6),
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )
    semaine_2 = WeekSegment(
        date_debut=debut + timedelta(days=7),
        date_fin=fin,
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )
    return PayPeriod(
        numero_periode=12,
        date_debut=debut,
        date_fin=fin,
        date_paiement=fin + timedelta(days=5),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=27,
        annee_fiscale=2026,
        semaines=(semaine_1, semaine_2),
    )


def _make_gains(
    *,
    brut_total: Decimal = Decimal("1000.00"),
    multiplicateur_heures_supp: Decimal = Decimal("1.5"),
    seuil_heures_supp_hebdo: Decimal = Decimal("40"),
) -> GainsDecomposes:
    """Fabrique un ``GainsDecomposes`` valide.

    Par défaut, tout le brut est logé dans ``salaire_regulier`` — les
    autres composantes sont à zéro. C'est acceptable au niveau du
    contrat : ``GainsDecomposes`` n'impose PAS ``salaire_regulier +
    heures_supp + vacances + feries == brut_total`` (design §Data Models
    9). Cette identité pourra être ajoutée par une spec ultérieure ; la
    tâche 10 n'y touche pas.
    """
    return GainsDecomposes(
        salaire_regulier=brut_total,
        heures_supplementaires_montant=Decimal("0.00"),
        vacances=Decimal("0.00"),
        jours_feries_manuels=Decimal("0.00"),
        brut_total=brut_total,
        multiplicateur_heures_supp=multiplicateur_heures_supp,
        seuil_heures_supp_hebdo=seuil_heures_supp_hebdo,
    )


def _make_retenues(
    *,
    rrq: Decimal = Decimal("0.00"),
    rqap: Decimal = Decimal("0.00"),
    ae: Decimal = Decimal("0.00"),
    impot_qc_retenu: Decimal = Decimal("0.00"),
    impot_federal_retenu: Decimal = Decimal("0.00"),
    impot_qc_formule: Decimal | None = None,
    impot_federal_formule: Decimal | None = None,
    total_retenues_employe: Decimal | None = None,
) -> RetenuesEmploye:
    """Fabrique un ``RetenuesEmploye`` valide.

    Par défaut, ``impot_qc_formule`` et ``impot_federal_formule`` valent
    respectivement ``impot_qc_retenu`` et ``impot_federal_retenu`` (cas
    « pas d'exonération »). ``total_retenues_employe`` est calculé
    automatiquement comme la somme des 5 retenues effectivement retenues
    (RRQ + RQAP + AE + impôt QC retenu + impôt fédéral retenu — les
    ``*_formule`` NE comptent PAS, Req 12.8), sauf si l'appelant force
    une valeur explicite (utile pour tester les incohérences).
    """
    if impot_qc_formule is None:
        impot_qc_formule = impot_qc_retenu
    if impot_federal_formule is None:
        impot_federal_formule = impot_federal_retenu
    if total_retenues_employe is None:
        total_retenues_employe = (
            rrq + rqap + ae + impot_qc_retenu + impot_federal_retenu
        )
    return RetenuesEmploye(
        rrq=_make_montant(rrq),
        rqap=_make_montant(rqap),
        ae=_make_montant(ae),
        impot_qc_formule=_make_montant(impot_qc_formule),
        impot_qc_retenu=_make_montant(impot_qc_retenu),
        impot_federal_formule=_make_montant(impot_federal_formule),
        impot_federal_retenu=_make_montant(impot_federal_retenu),
        total_retenues_employe=total_retenues_employe,
    )


def _make_cotisations(
    *,
    rrq_employeur: Decimal = Decimal("0.00"),
    rqap_employeur: Decimal = Decimal("0.00"),
    ae_employeur: Decimal = Decimal("0.00"),
    fss: Decimal = Decimal("0.00"),
    cnesst: Decimal = Decimal("0.00"),
    cnt: Decimal = Decimal("0.00"),
    cnesst_en_attente_classification: bool = False,
    total_cotisations_employeur: Decimal | None = None,
) -> CotisationsEmployeur:
    """Fabrique un ``CotisationsEmployeur`` valide.

    ``total_cotisations_employeur`` est calculé automatiquement comme la
    somme des 6 cotisations (RRQ_er + RQAP_er + AE_er + FSS + CNESST +
    CNT), sauf si l'appelant force une valeur pour tester une
    incohérence.
    """
    if total_cotisations_employeur is None:
        total_cotisations_employeur = (
            rrq_employeur + rqap_employeur + ae_employeur + fss + cnesst + cnt
        )
    return CotisationsEmployeur(
        rrq_employeur=_make_montant(rrq_employeur),
        rqap_employeur=_make_montant(rqap_employeur),
        ae_employeur=_make_montant(ae_employeur),
        fss=_make_montant(fss),
        cnesst=_make_montant(cnesst),
        cnesst_en_attente_classification=cnesst_en_attente_classification,
        cnt=_make_montant(cnt),
        total_cotisations_employeur=total_cotisations_employeur,
    )


def _make_result(**overrides: Any) -> PayrollResult:
    """Fabrique un ``PayrollResult`` valide, prêt à être surchargé.

    L'objectif est de permettre à chaque test de tester UNE contrainte
    en surchargeant un seul champ, sans réécrire les autres. Toutes
    les identités comptables (Req 4.9, 4.10) et de cohérence
    (``cumuls_fin`` / ``employe_id`` / ``annee_fiscale``) sont
    satisfaites par défaut.

    Convention : ``brut`` (raccourci ``brut_total``) est calculé pour
    couvrir exactement les retenues (net = brut - total_retenues), et le
    coût employeur est calculé pour couvrir exactement les cotisations
    (cout = brut + total_cotisations). L'appelant peut surcharger un
    champ terminal (``net``, ``cout_employeur``, ``gains``,
    ``retenues_employe``, ``cotisations_employeur``) pour introduire
    une incohérence contrôlée.
    """
    brut_total: Decimal = overrides.pop("brut_total_defaut", Decimal("1000.00"))
    gains = overrides.pop("gains", None) or _make_gains(brut_total=brut_total)
    retenues = overrides.pop("retenues_employe", None) or _make_retenues()
    cotisations = overrides.pop("cotisations_employeur", None) or _make_cotisations()

    total_retenues = retenues.total_retenues_employe
    total_cotisations = cotisations.total_cotisations_employeur

    defauts: dict[str, Any] = {
        "id_paie": "PAIE-EMP001-2026-12",
        "version": 1,
        "employe_id": "EMP001",
        "annee_fiscale": 2026,
        "pay_period": _make_pay_period(),
        "gains": gains,
        "retenues_employe": retenues,
        "cotisations_employeur": cotisations,
        "net": gains.brut_total - total_retenues,
        "cout_employeur": gains.brut_total + total_cotisations,
        "cumuls_fin": CumulsYTD.zero("EMP001", 2026),
        "statut": StatutDePaie.BROUILLON,
        "remplace_par_id": None,
        "date_creation": datetime(2026, 6, 19, 12, 0, 0),
        "date_emission": None,
    }
    defauts.update(overrides)
    return PayrollResult(**defauts)


# ---------------------------------------------------------------------------
# Sanity check des fabriques : la fabrique par défaut construit un
# ``PayrollResult`` valide. Un échec ici signalerait un bug dans la
# fabrique (test défaillant) et non dans l'implémentation testée.
# ---------------------------------------------------------------------------


class TestFabriqueParDefautEstValide:
    """Sondes des fabriques utilisées par les autres tests."""

    def test_fabrique_par_defaut_construit_un_payroll_result_valide(self) -> None:
        """La fabrique produit une instance dont toutes les identités passent."""
        resultat = _make_result()
        assert isinstance(resultat, PayrollResult)
        assert resultat.gains.brut_total == Decimal("1000.00")
        assert resultat.net == Decimal("1000.00")
        assert resultat.cout_employeur == Decimal("1000.00")
        assert resultat.retenues_employe.total_retenues_employe == Decimal("0.00")
        assert (
            resultat.cotisations_employeur.total_cotisations_employeur
            == Decimal("0.00")
        )


# ===========================================================================
# Stratégies Hypothesis locales
# ===========================================================================


@st.composite
def _decimal_monetaire(
    draw: st.DrawFn,
    *,
    min_value: Decimal = Decimal("0.00"),
    max_value: Decimal = Decimal("10000.00"),
) -> Decimal:
    """``Decimal`` monétaire ``[min_value, max_value]``, deux décimales.

    Bornes volontairement modestes pour éviter les débordements
    numériques et garder le temps d'exécution d'Hypothesis
    raisonnable. Les tests visent la propriété (identité comptable),
    pas la performance sur les grands montants.
    """
    return draw(
        st.decimals(
            min_value=min_value,
            max_value=max_value,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@st.composite
def _cinq_retenues_avec_somme_bornee(
    draw: st.DrawFn, *, plafond_somme: Decimal
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Génère cinq retenues ``>= 0`` dont la somme est ``<= plafond_somme``.

    Utilisé par les property tests d'identité brute : la somme des
    retenues doit rester ``<= brut_total`` pour permettre à
    ``net = brut_total - total_retenues >= 0`` (Req 4.11).
    """
    if plafond_somme < Decimal("0.00"):
        plafond_somme = Decimal("0.00")
    # Chaque retenue tient dans [0, plafond_somme / 5] pour garantir que
    # la somme des cinq reste sous le plafond, avec une marge suffisante
    # pour que Hypothesis ait matière à varier les distributions.
    borne_individuelle = (plafond_somme / Decimal("5")).quantize(Decimal("0.01"))
    rrq = draw(_decimal_monetaire(max_value=borne_individuelle))
    rqap = draw(_decimal_monetaire(max_value=borne_individuelle))
    ae = draw(_decimal_monetaire(max_value=borne_individuelle))
    impot_qc = draw(_decimal_monetaire(max_value=borne_individuelle))
    impot_fed = draw(_decimal_monetaire(max_value=borne_individuelle))
    return (rrq, rqap, ae, impot_qc, impot_fed)


@st.composite
def _six_cotisations(
    draw: st.DrawFn, *, borne_individuelle: Decimal = Decimal("500.00")
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Génère six cotisations employeur ``>= 0``, chacune dans ``[0, borne]``."""
    return tuple(  # type: ignore[return-value]
        draw(_decimal_monetaire(max_value=borne_individuelle)) for _ in range(6)
    )


# ===========================================================================
# Property 1 — Immuabilité des 5 modèles (Req 4.12, 6.2)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
# domaine. *Pour toute* instance valide de ``GainsDecomposes``,
# ``MontantAvecTrace``, ``RetenuesEmploye``, ``CotisationsEmployeur`` ou
# ``PayrollResult``, toute mutation d'un champ déclaré doit lever
# ``pydantic.ValidationError`` (``frozen=True``).
#
# **Validates: Requirements 4.12, 6.2**
# ===========================================================================


class TestProperty1ImmuabiliteGainsDecomposes:
    """Immuabilité de ``GainsDecomposes`` (design §Data Models 9)."""

    @pytest.mark.parametrize(
        "champ,nouvelle_valeur",
        [
            ("salaire_regulier", Decimal("999.99")),
            ("heures_supplementaires_montant", Decimal("50.00")),
            ("vacances", Decimal("40.00")),
            ("jours_feries_manuels", Decimal("100.00")),
            ("brut_total", Decimal("2000.00")),
            ("multiplicateur_heures_supp", Decimal("2.0")),
            ("seuil_heures_supp_hebdo", Decimal("35")),
        ],
    )
    def test_mutation_leve_validation_error(
        self, champ: str, nouvelle_valeur: Decimal
    ) -> None:
        """Req 4.12 — chaque champ de ``GainsDecomposes`` est immuable."""
        gains = _make_gains()
        with pytest.raises(ValidationError):
            setattr(gains, champ, nouvelle_valeur)


class TestProperty1ImmuabiliteMontantAvecTrace:
    """Immuabilité de ``MontantAvecTrace``."""

    def test_mutation_montant_leve_validation_error(self) -> None:
        """Req 4.12 — mutation de ``montant`` refusée."""
        mat = _make_montant(Decimal("0.00"))
        with pytest.raises(ValidationError):
            mat.montant = Decimal("100.00")  # type: ignore[misc]

    def test_mutation_trace_leve_validation_error(self) -> None:
        """Req 4.12 — mutation de ``trace`` refusée."""
        mat = _make_montant(Decimal("0.00"))
        with pytest.raises(ValidationError):
            mat.trace = _make_trace(Decimal("42.00"))  # type: ignore[misc]


class TestProperty1ImmuabiliteRetenuesEmploye:
    """Immuabilité de ``RetenuesEmploye``."""

    @pytest.mark.parametrize(
        "champ",
        [
            "rrq",
            "rqap",
            "ae",
            "impot_qc_formule",
            "impot_qc_retenu",
            "impot_federal_formule",
            "impot_federal_retenu",
            "total_retenues_employe",
        ],
    )
    def test_mutation_dun_champ_leve_validation_error(self, champ: str) -> None:
        """Req 4.12 — chaque champ de ``RetenuesEmploye`` est immuable."""
        retenues = _make_retenues()
        with pytest.raises(ValidationError):
            if champ == "total_retenues_employe":
                setattr(retenues, champ, Decimal("999.99"))
            else:
                setattr(retenues, champ, _make_montant(Decimal("42.00")))


class TestProperty1ImmuabiliteCotisationsEmployeur:
    """Immuabilité de ``CotisationsEmployeur``."""

    @pytest.mark.parametrize(
        "champ",
        [
            "rrq_employeur",
            "rqap_employeur",
            "ae_employeur",
            "fss",
            "cnesst",
            "cnt",
            "cnesst_en_attente_classification",
            "total_cotisations_employeur",
        ],
    )
    def test_mutation_dun_champ_leve_validation_error(self, champ: str) -> None:
        """Req 4.12 — chaque champ de ``CotisationsEmployeur`` est immuable."""
        cotisations = _make_cotisations()
        with pytest.raises(ValidationError):
            if champ == "cnesst_en_attente_classification":
                setattr(cotisations, champ, True)
            elif champ == "total_cotisations_employeur":
                setattr(cotisations, champ, Decimal("999.99"))
            else:
                setattr(cotisations, champ, _make_montant(Decimal("42.00")))


class TestProperty1ImmuabilitePayrollResult:
    """Immuabilité de ``PayrollResult`` (Req 6.2)."""

    @pytest.mark.parametrize(
        "champ,valeur",
        [
            ("id_paie", "PAIE-AUTRE"),
            ("version", 2),
            ("employe_id", "EMP002"),
            ("annee_fiscale", 2027),
            ("net", Decimal("500.00")),
            ("cout_employeur", Decimal("500.00")),
            ("statut", StatutDePaie.EMISE),
            ("remplace_par_id", "PAIE-AUTRE"),
        ],
    )
    def test_mutation_dun_champ_leve_validation_error(
        self, champ: str, valeur: object
    ) -> None:
        """Req 4.12 / 6.2 — chaque champ de ``PayrollResult`` est immuable."""
        resultat = _make_result()
        with pytest.raises(ValidationError):
            setattr(resultat, champ, valeur)


@pytest.mark.property
class TestProperty1ImmuabilitePropertyPayrollResult:
    """Property 1 (Hypothesis) — mutation universellement refusée."""

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
    # domaine.
    #
    # **Validates: Requirements 4.12, 6.2**
    @given(nouveau_net=_decimal_monetaire(max_value=Decimal("1000.00")))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.filter_too_much])
    def test_mutation_du_net_est_toujours_refusee(self, nouveau_net: Decimal) -> None:
        """Req 4.12 — pour tout ``Decimal`` cible, la mutation de ``net`` est refusée."""
        resultat = _make_result()
        with pytest.raises(ValidationError):
            resultat.net = nouveau_net  # type: ignore[misc]


# ===========================================================================
# Property 7 — Identité brute (Req 4.4, 4.9)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 7: Identité brute
# ``net + total_retenues_employe == brut_total``.
#
# Deux volets :
#
# - **Volet cohérent** : Hypothesis construit des triplets ``(brut,
#   retenues, net)`` où ``net + Σretenues == brut`` — la construction
#   DOIT réussir.
# - **Volet incohérent** : Hypothesis construit des triplets avec un
#   écart ``delta ≠ 0`` — la construction DOIT lever
#   ``ValidationError``.
#
# **Validates: Requirements 4.4, 4.9**
# ===========================================================================


@pytest.mark.property
class TestProperty7IdentiteBrute:
    """Identité comptable ``net + total_retenues == brut`` (Req 4.9)."""

    # Feature: moteur-paie-contrats, Property 7: Identité brute.
    #
    # **Validates: Requirements 4.4, 4.9**
    @given(
        brut=_decimal_monetaire(
            min_value=Decimal("100.00"), max_value=Decimal("5000.00")
        ),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
    def test_triplet_coherent_passe_la_validation(
        self, brut: Decimal, data: st.DataObject
    ) -> None:
        """Req 4.9 — un ``PayrollResult`` cohérent construit sans erreur."""
        (rrq, rqap, ae, impot_qc, impot_fed) = data.draw(
            _cinq_retenues_avec_somme_bornee(plafond_somme=brut)
        )
        total_retenues = rrq + rqap + ae + impot_qc + impot_fed
        net = brut - total_retenues
        # Sanity : la stratégie DOIT garantir ``net >= 0`` (Req 4.11).
        assert net >= Decimal("0.00")

        retenues = _make_retenues(
            rrq=rrq,
            rqap=rqap,
            ae=ae,
            impot_qc_retenu=impot_qc,
            impot_federal_retenu=impot_fed,
        )
        gains = _make_gains(brut_total=brut)
        resultat = _make_result(gains=gains, retenues_employe=retenues, net=net)

        # L'identité tient au cent près.
        assert (
            resultat.net + resultat.retenues_employe.total_retenues_employe
            == resultat.gains.brut_total
        )

    # Feature: moteur-paie-contrats, Property 7: Identité brute.
    #
    # **Validates: Requirements 4.4, 4.9**
    @given(
        brut=_decimal_monetaire(
            min_value=Decimal("100.00"), max_value=Decimal("5000.00")
        ),
        delta=_decimal_monetaire(
            min_value=Decimal("0.01"), max_value=Decimal("500.00")
        ),
        signe_positif=st.booleans(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
    def test_triplet_incoherent_leve_validation_error(
        self,
        brut: Decimal,
        delta: Decimal,
        signe_positif: bool,
        data: st.DataObject,
    ) -> None:
        """Req 4.9 — un ``PayrollResult`` incohérent est refusé."""
        (rrq, rqap, ae, impot_qc, impot_fed) = data.draw(
            _cinq_retenues_avec_somme_bornee(plafond_somme=brut)
        )
        total_retenues = rrq + rqap + ae + impot_qc + impot_fed
        # Ecart contrôlé : net = brut - total_retenues + delta (ou - delta)
        # -> l'identité brute NE tient PAS.
        net_incoherent = brut - total_retenues + (delta if signe_positif else -delta)
        # On exige que ``net_incoherent`` reste >= 0 pour éviter que la
        # ``ValidationError`` soit provoquée par la contrainte ``ge=0`` de
        # ``net`` plutôt que par l'identité comptable qui est l'objet du test.
        assume(net_incoherent >= Decimal("0.00"))
        # Et on écarte les cas rares où le sens choisi annule le delta.
        assume(net_incoherent + total_retenues != brut)

        retenues = _make_retenues(
            rrq=rrq,
            rqap=rqap,
            ae=ae,
            impot_qc_retenu=impot_qc,
            impot_federal_retenu=impot_fed,
        )
        gains = _make_gains(brut_total=brut)
        with pytest.raises(ValidationError):
            _make_result(
                gains=gains, retenues_employe=retenues, net=net_incoherent
            )


# ===========================================================================
# Property 8 — Identité coût employeur (Req 4.5, 4.10)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 8: Identité coût employeur
# ``cout_employeur == brut_total + total_cotisations_employeur``.
#
# **Validates: Requirements 4.5, 4.10**
# ===========================================================================


@pytest.mark.property
class TestProperty8IdentiteCoutEmployeur:
    """Identité comptable ``cout = brut + total_cotisations`` (Req 4.10)."""

    # Feature: moteur-paie-contrats, Property 8: Identité coût employeur.
    #
    # **Validates: Requirements 4.5, 4.10**
    @given(
        brut=_decimal_monetaire(
            min_value=Decimal("100.00"), max_value=Decimal("5000.00")
        ),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
    def test_triplet_coherent_passe_la_validation(
        self, brut: Decimal, data: st.DataObject
    ) -> None:
        """Req 4.10 — un ``PayrollResult`` cohérent construit sans erreur."""
        (rrq_er, rqap_er, ae_er, fss, cnesst, cnt) = data.draw(_six_cotisations())
        cotisations = _make_cotisations(
            rrq_employeur=rrq_er,
            rqap_employeur=rqap_er,
            ae_employeur=ae_er,
            fss=fss,
            cnesst=cnesst,
            cnt=cnt,
        )
        total_cotisations = cotisations.total_cotisations_employeur
        gains = _make_gains(brut_total=brut)
        resultat = _make_result(
            gains=gains,
            cotisations_employeur=cotisations,
            cout_employeur=brut + total_cotisations,
        )

        assert (
            resultat.cout_employeur
            == resultat.gains.brut_total
            + resultat.cotisations_employeur.total_cotisations_employeur
        )

    # Feature: moteur-paie-contrats, Property 8: Identité coût employeur.
    #
    # **Validates: Requirements 4.5, 4.10**
    @given(
        brut=_decimal_monetaire(
            min_value=Decimal("100.00"), max_value=Decimal("5000.00")
        ),
        delta=_decimal_monetaire(
            min_value=Decimal("0.01"), max_value=Decimal("500.00")
        ),
        signe_positif=st.booleans(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
    def test_triplet_incoherent_leve_validation_error(
        self,
        brut: Decimal,
        delta: Decimal,
        signe_positif: bool,
        data: st.DataObject,
    ) -> None:
        """Req 4.10 — un ``PayrollResult`` incohérent est refusé."""
        (rrq_er, rqap_er, ae_er, fss, cnesst, cnt) = data.draw(_six_cotisations())
        cotisations = _make_cotisations(
            rrq_employeur=rrq_er,
            rqap_employeur=rqap_er,
            ae_employeur=ae_er,
            fss=fss,
            cnesst=cnesst,
            cnt=cnt,
        )
        total_cotisations = cotisations.total_cotisations_employeur
        cout_incoherent = (
            brut + total_cotisations + (delta if signe_positif else -delta)
        )
        assume(cout_incoherent >= Decimal("0.00"))
        assume(cout_incoherent != brut + total_cotisations)

        gains = _make_gains(brut_total=brut)
        with pytest.raises(ValidationError):
            _make_result(
                gains=gains,
                cotisations_employeur=cotisations,
                cout_employeur=cout_incoherent,
            )


# ===========================================================================
# Property 9 (partiel PayrollResult) — Non-négativité (Req 4.11)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 9: Non-négativité des retenues
# et cotisations. *Pour tout* montant d'un ``MontantAvecTrace`` d'une
# ``RetenuesEmploye`` ou d'une ``CotisationsEmployeur``, ainsi que pour
# les totaux, une valeur strictement négative doit lever
# ``pydantic.ValidationError`` sans clampage silencieux.
#
# **Validates: Requirements 4.11**
# ===========================================================================


_CATEGORIES_RETENUE: tuple[str, ...] = (
    "rrq",
    "rqap",
    "ae",
    "impot_qc_formule",
    "impot_qc_retenu",
    "impot_federal_formule",
    "impot_federal_retenu",
)

_CATEGORIES_COTISATION: tuple[str, ...] = (
    "rrq_employeur",
    "rqap_employeur",
    "ae_employeur",
    "fss",
    "cnesst",
    "cnt",
)


class TestProperty9NonNegativiteMontantAvecTrace:
    """``MontantAvecTrace.montant`` refuse toute valeur strictement négative."""

    @pytest.mark.parametrize(
        "valeur_negative",
        [Decimal("-0.01"), Decimal("-1.00"), Decimal("-1000.00")],
    )
    def test_montant_negatif_est_refuse_a_la_construction(
        self, valeur_negative: Decimal
    ) -> None:
        """Req 4.11 — refus fail-fast d'un montant < 0."""
        with pytest.raises(ValidationError):
            MontantAvecTrace(
                montant=valeur_negative, trace=_make_trace(valeur_negative)
            )


class TestProperty9NonNegativiteRetenues:
    """Chaque ``MontantAvecTrace`` de ``RetenuesEmploye`` refuse un négatif."""

    @pytest.mark.parametrize("categorie", _CATEGORIES_RETENUE)
    def test_categorie_negative_est_refusee(self, categorie: str) -> None:
        """Req 4.11 — refus fail-fast pour chaque catégorie de retenue."""
        # Construction du ``MontantAvecTrace`` négatif : bloquée dès la
        # sous-construction. On l'attend ici — la propriété se manifeste
        # au premier niveau où le montant négatif est présenté à Pydantic.
        with pytest.raises(ValidationError):
            MontantAvecTrace(
                montant=Decimal("-0.01"), trace=_make_trace(Decimal("-0.01"))
            )

    def test_total_retenues_negatif_est_refuse(self) -> None:
        """Req 4.11 — ``total_retenues_employe`` négatif refusé."""
        # On force un total < 0 en laissant les sous-champs à 0 et en
        # écrasant le total. ``total_retenues_employe`` a ``ge=0`` par
        # design ; la validation Pydantic doit refuser.
        with pytest.raises(ValidationError):
            _make_retenues(total_retenues_employe=Decimal("-0.01"))


class TestProperty9NonNegativiteCotisations:
    """Chaque ``MontantAvecTrace`` de ``CotisationsEmployeur`` refuse un négatif."""

    @pytest.mark.parametrize("categorie", _CATEGORIES_COTISATION)
    def test_categorie_negative_est_refusee(self, categorie: str) -> None:
        """Req 4.11 — refus fail-fast pour chaque catégorie de cotisation."""
        with pytest.raises(ValidationError):
            MontantAvecTrace(
                montant=Decimal("-0.01"), trace=_make_trace(Decimal("-0.01"))
            )

    def test_total_cotisations_negatif_est_refuse(self) -> None:
        """Req 4.11 — ``total_cotisations_employeur`` négatif refusé."""
        with pytest.raises(ValidationError):
            _make_cotisations(total_cotisations_employeur=Decimal("-0.01"))


@pytest.mark.property
class TestProperty9NonNegativiteProperty:
    """Property 9 (Hypothesis) — refus universel des valeurs négatives."""

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des
    # retenues et cotisations.
    #
    # **Validates: Requirements 4.11**
    @given(
        valeur_negative=st.decimals(
            min_value=Decimal("-100000.00"),
            max_value=Decimal("-0.01"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
    def test_montant_avec_trace_negatif_est_refuse(
        self, valeur_negative: Decimal
    ) -> None:
        """Req 4.11 — pour tout ``Decimal`` < 0, ``MontantAvecTrace`` refusé."""
        assert valeur_negative < Decimal("0")
        with pytest.raises(ValidationError):
            MontantAvecTrace(
                montant=valeur_negative, trace=_make_trace(valeur_negative)
            )


# ===========================================================================
# Property 11 — Biconditionnelle statut ⟺ remplace_par_id ⟺ date_emission
# (Req 6.3, 6.4, 6.5, 6.7)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 11: Biconditionnelle statut ⟺
# remplace_par_id ⟺ date_emission. Les 4×2×2 = 16 combinaisons sont
# parametrées explicitement. Chaque combinaison est étiquetée VALID ou
# INVALID selon la synthèse des Req 6.3, 6.4, 6.5, 6.7 (design §Data
# Models 9, méthode ``_statut_et_remplacement_coherents``) :
#
# - ``statut == REMPLACE_PAR`` ⟺ ``remplace_par_id`` renseigné
#   (non-``None`` et non-vide) — Req 6.3, 6.4, 6.5.
# - ``statut ∈ {EMISE, ANNULEE, REMPLACE_PAR}`` ⟹ ``date_emission``
#   renseignée — Req 6.7 (implication unidirectionnelle : rien
#   n'interdit d'avoir une ``date_emission`` en ``BROUILLON``).
#
# **Validates: Requirements 6.3, 6.4, 6.5, 6.7**
# ===========================================================================


#: Date d'émission fictive utilisée par les tests parametrés — postérieure
#: à la ``date_creation`` par défaut de la fabrique.
_DATE_EMISSION_FICTIVE: datetime = datetime(2026, 6, 20, 9, 0, 0)


def _remplace_par_id_pour(statut: StatutDePaie, present: bool) -> str | None:
    """Retourne ``remplace_par_id`` selon la présence souhaitée.

    Convention (design §Data Models 9) : ``present=False`` → ``None``,
    ``present=True`` → une chaîne non vide identifiant la paie
    remplaçante.
    """
    del statut  # inutilisé, présent pour lisibilité de l'appelant
    return "PAIE-REMPLACEMENT-EMP001-2026-13" if present else None


def _date_emission_pour(present: bool) -> datetime | None:
    """Retourne ``date_emission`` selon la présence souhaitée."""
    return _DATE_EMISSION_FICTIVE if present else None


# 16 combinaisons — cf. §Data Models 9 pour l'énoncé de l'invariant.
#
# Colonnes : (statut, R = remplace_par_id présent, D = date_emission
# présente, VALID = attendu accepté par la validation).
_COMBINAISONS_PROPERTY_11: tuple[tuple[StatutDePaie, bool, bool, bool], ...] = (
    # BROUILLON : R doit être absent (Req 6.5). D n'est pas requis (Req 6.7 —
    # implication unidirectionnelle, aucune interdiction en BROUILLON).
    (StatutDePaie.BROUILLON, False, False, True),
    (StatutDePaie.BROUILLON, False, True, True),
    (StatutDePaie.BROUILLON, True, False, False),  # R interdit
    (StatutDePaie.BROUILLON, True, True, False),  # R interdit
    # EMISE : R doit être absent (Req 6.5). D est requis (Req 6.7).
    (StatutDePaie.EMISE, False, False, False),  # D requis
    (StatutDePaie.EMISE, False, True, True),
    (StatutDePaie.EMISE, True, False, False),  # R interdit + D requis
    (StatutDePaie.EMISE, True, True, False),  # R interdit
    # ANNULEE : R doit être absent (Req 6.5). D est requis (Req 6.7).
    (StatutDePaie.ANNULEE, False, False, False),  # D requis
    (StatutDePaie.ANNULEE, False, True, True),
    (StatutDePaie.ANNULEE, True, False, False),  # R interdit + D requis
    (StatutDePaie.ANNULEE, True, True, False),  # R interdit
    # REMPLACE_PAR : R est requis (Req 6.4). D est requis (Req 6.7).
    (StatutDePaie.REMPLACE_PAR, False, False, False),  # R et D requis
    (StatutDePaie.REMPLACE_PAR, False, True, False),  # R requis
    (StatutDePaie.REMPLACE_PAR, True, False, False),  # D requis
    (StatutDePaie.REMPLACE_PAR, True, True, True),
)


@pytest.mark.property
class TestProperty11BiconditionnelleStatutRemplacementEmission:
    """Property 11 — 16 combinaisons paramétrées explicitement.

    L'énumération explicite est préférée à Hypothesis pour ce cas :
    l'espace d'entrée est fini et petit (16 points), et l'énumération
    documente en lecture directe la table de vérité de l'invariant.
    """

    # Feature: moteur-paie-contrats, Property 11: Biconditionnelle statut
    # ⟺ remplace_par_id ⟺ date_emission.
    #
    # **Validates: Requirements 6.3, 6.4, 6.5, 6.7**
    @pytest.mark.parametrize(
        "statut,remplace_par_id_present,date_emission_present,combinaison_valide",
        _COMBINAISONS_PROPERTY_11,
    )
    def test_les_16_combinaisons_respectent_la_biconditionnelle(
        self,
        statut: StatutDePaie,
        remplace_par_id_present: bool,
        date_emission_present: bool,
        combinaison_valide: bool,
    ) -> None:
        """Req 6.3–6.5, 6.7 — exactement 5 combinaisons sur 16 sont valides."""
        remplace_par_id = _remplace_par_id_pour(statut, remplace_par_id_present)
        date_emission = _date_emission_pour(date_emission_present)

        if combinaison_valide:
            resultat = _make_result(
                statut=statut,
                remplace_par_id=remplace_par_id,
                date_emission=date_emission,
            )
            # Sondes de sanity sur l'instance construite.
            assert resultat.statut is statut
            assert resultat.remplace_par_id == remplace_par_id
            assert resultat.date_emission == date_emission
        else:
            with pytest.raises(ValidationError):
                _make_result(
                    statut=statut,
                    remplace_par_id=remplace_par_id,
                    date_emission=date_emission,
                )

    def test_exactement_cinq_combinaisons_sur_seize_sont_valides(self) -> None:
        """Sanity — la table de vérité contient bien 5 acceptations sur 16.

        Ce test ne construit AUCUN modèle : il vérifie que la
        parametrization elle-même est cohérente avec l'analyse du design
        (garde-fou contre un décalage entre la table de vérité et
        l'implémentation, dans les deux sens).
        """
        assert len(_COMBINAISONS_PROPERTY_11) == 16
        cas_valides = [c for c in _COMBINAISONS_PROPERTY_11 if c[3]]
        assert len(cas_valides) == 5

    def test_remplace_par_id_vide_traite_comme_absent(self) -> None:
        """Req 6.3, 6.4 — une chaîne ``""`` équivaut à ``None`` (design §9).

        Ce complément aux 16 combinaisons vérifie explicitement le cas
        ``remplace_par_id=""`` : le design évalue le champ par truthiness
        (``if not self.remplace_par_id``), donc une chaîne vide doit
        satisfaire la biconditionnelle « remplace_par_id absent » —
        combinée à ``statut == REMPLACE_PAR``, la construction doit
        échouer (le remplaçant est effectivement absent).
        """
        with pytest.raises(ValidationError):
            _make_result(
                statut=StatutDePaie.REMPLACE_PAR,
                remplace_par_id="",
                date_emission=_DATE_EMISSION_FICTIVE,
            )


# ===========================================================================
# Tests d'exemple — Cohérence de somme des retenues et cotisations
# ===========================================================================


class TestCoherenceTotalRetenues:
    """``total_retenues_employe`` DOIT égaler la somme des retenues retenues."""

    def test_total_incoherent_par_rapport_a_la_somme_leve_validation_error(
        self,
    ) -> None:
        """Req 4.9 (par extension via ``RetenuesEmploye``).

        La somme des cinq retenues effectivement retenues (RRQ + RQAP +
        AE + impôt QC retenu + impôt fédéral retenu) DOIT correspondre à
        ``total_retenues_employe``. Un écart, même d'un cent, doit lever
        ``ValidationError``.
        """
        with pytest.raises(ValidationError):
            _make_retenues(
                rrq=Decimal("10.00"),
                rqap=Decimal("5.00"),
                ae=Decimal("3.00"),
                impot_qc_retenu=Decimal("20.00"),
                impot_federal_retenu=Decimal("15.00"),
                # Vraie somme = 53.00 ; on force un total incohérent :
                total_retenues_employe=Decimal("52.99"),
            )

    def test_total_correct_passe_la_validation(self) -> None:
        """Cas positif — la somme cohérente construit l'instance."""
        retenues = _make_retenues(
            rrq=Decimal("10.00"),
            rqap=Decimal("5.00"),
            ae=Decimal("3.00"),
            impot_qc_retenu=Decimal("20.00"),
            impot_federal_retenu=Decimal("15.00"),
            # Total = 53.00 — cohérent avec la somme.
        )
        assert retenues.total_retenues_employe == Decimal("53.00")

    def test_impots_formule_ne_comptent_pas_dans_le_total(self) -> None:
        """Req 12.8 — seuls les ``*_retenu`` participent au total.

        Cas typique d'exonération TP-1015.3 : l'impôt QC « formule »
        vaut par exemple ``42.00`` (calculé par la formule officielle)
        mais l'impôt QC « retenu » vaut ``0.00`` (court-circuit par
        l'exonération). Le total ne compte que les valeurs *retenues*,
        pas les valeurs *formule*.
        """
        retenues = _make_retenues(
            rrq=Decimal("10.00"),
            rqap=Decimal("0.00"),
            ae=Decimal("0.00"),
            impot_qc_formule=Decimal("42.00"),  # formule non nulle
            impot_qc_retenu=Decimal("0.00"),  # retenu à zéro (exonération)
            impot_federal_formule=Decimal("100.00"),  # formule non nulle
            impot_federal_retenu=Decimal("0.00"),  # retenu à zéro (exonération)
            # Total attendu = RRQ + RQAP + AE + impôt QC retenu +
            # impôt fédéral retenu = 10 + 0 + 0 + 0 + 0 = 10.00.
        )
        assert retenues.total_retenues_employe == Decimal("10.00")


class TestCoherenceTotalCotisations:
    """``total_cotisations_employeur`` DOIT égaler la somme des 6 cotisations."""

    def test_total_incoherent_par_rapport_a_la_somme_leve_validation_error(
        self,
    ) -> None:
        """Req 4.10 (par extension via ``CotisationsEmployeur``).

        La somme des six cotisations (RRQ employeur + RQAP employeur +
        AE employeur + FSS + CNESST + CNT) DOIT correspondre à
        ``total_cotisations_employeur``. Un écart, même d'un cent, doit
        lever ``ValidationError``.
        """
        with pytest.raises(ValidationError):
            _make_cotisations(
                rrq_employeur=Decimal("10.00"),
                rqap_employeur=Decimal("5.00"),
                ae_employeur=Decimal("3.00"),
                fss=Decimal("15.00"),
                cnesst=Decimal("12.00"),
                cnt=Decimal("1.00"),
                # Vraie somme = 46.00 ; total incohérent :
                total_cotisations_employeur=Decimal("46.01"),
            )

    def test_total_correct_passe_la_validation(self) -> None:
        """Cas positif — la somme cohérente construit l'instance."""
        cotisations = _make_cotisations(
            rrq_employeur=Decimal("10.00"),
            rqap_employeur=Decimal("5.00"),
            ae_employeur=Decimal("3.00"),
            fss=Decimal("15.00"),
            cnesst=Decimal("12.00"),
            cnt=Decimal("1.00"),
            # Total = 46.00.
        )
        assert cotisations.total_cotisations_employeur == Decimal("46.00")


# ===========================================================================
# Test d'exemple — ``multiplicateur_heures_supp`` et
# ``seuil_heures_supp_hebdo`` reçus, jamais recalculés (Req 4.14)
# ===========================================================================


class TestChampsHeuresSuppRecusDuModuleDeCalcul:
    """Req 4.14 — ``GainsDecomposes`` reçoit ces deux champs, ne les recalcule pas.

    ``GainsDecomposes`` ne connaît PAS la logique fiscale : les valeurs
    ``multiplicateur_heures_supp`` et ``seuil_heures_supp_hebdo`` lui
    sont fournies par le module de calcul (qui les a lues depuis
    ``parameters/<annee>/quebec.json`` section ``heures_supplementaires``).
    Cette responsabilité de simple *portage* est vérifiée en montrant
    que :

    - toute valeur ``Decimal > 0`` sur ces deux champs est acceptée
      telle quelle (aucune coercition ni recalcul) ;
    - la valeur exposée après construction est *strictement* celle
      fournie en entrée (fidélité au cent près, cohérente avec la
      règle 01).
    """

    @pytest.mark.parametrize(
        "multiplicateur,seuil",
        [
            (Decimal("1.5"), Decimal("40")),
            # Cas alternatifs (règle 05 — les valeurs viennent des paramètres
            # annuels ; ces triplets alternatifs simulent des paramètres
            # modifiés par une évolution des Normes du travail QC).
            (Decimal("2.0"), Decimal("35")),
            (Decimal("1.25"), Decimal("44")),
            # Précision étendue à quatre décimales, admise (Req 4.14).
            (Decimal("1.5000"), Decimal("40.00")),
        ],
    )
    def test_valeurs_fournies_sont_exposees_a_lidentique(
        self, multiplicateur: Decimal, seuil: Decimal
    ) -> None:
        """Req 4.14 — les deux valeurs sont préservées à l'octet près."""
        gains = _make_gains(
            multiplicateur_heures_supp=multiplicateur,
            seuil_heures_supp_hebdo=seuil,
        )
        # Egalite stricte de valeur (``==`` sur ``Decimal`` respecte
        # la valeur numérique, pas la représentation).
        assert gains.multiplicateur_heures_supp == multiplicateur
        assert gains.seuil_heures_supp_hebdo == seuil

    def test_multiplicateur_zero_ou_negatif_est_refuse(self) -> None:
        """Design §Data Models 9 — ``multiplicateur_heures_supp: gt=0``."""
        with pytest.raises(ValidationError):
            _make_gains(multiplicateur_heures_supp=Decimal("0"))
        with pytest.raises(ValidationError):
            _make_gains(multiplicateur_heures_supp=Decimal("-1.5"))

    def test_seuil_zero_ou_negatif_est_refuse(self) -> None:
        """Design §Data Models 9 — ``seuil_heures_supp_hebdo: gt=0``."""
        with pytest.raises(ValidationError):
            _make_gains(seuil_heures_supp_hebdo=Decimal("0"))
        with pytest.raises(ValidationError):
            _make_gains(seuil_heures_supp_hebdo=Decimal("-40"))


# ===========================================================================
# Tests d'exemple — Cohérence ``cumuls_fin`` avec ``employe_id`` / année
# ===========================================================================


class TestCoherenceCumulsFin:
    """``cumuls_fin`` DOIT correspondre à ``employe_id`` et ``annee_fiscale``."""

    def test_cumuls_fin_avec_employe_id_different_leve_validation_error(
        self,
    ) -> None:
        """Design §Data Models 9 — ``cumuls_fin.employe_id == employe_id``."""
        cumuls_autre_employe = CumulsYTD.zero("EMP999", 2026)
        with pytest.raises(ValidationError):
            _make_result(cumuls_fin=cumuls_autre_employe)

    def test_cumuls_fin_avec_annee_civile_differente_leve_validation_error(
        self,
    ) -> None:
        """Design §Data Models 9 — ``cumuls_fin.annee_civile == annee_fiscale``."""
        cumuls_autre_annee = CumulsYTD.zero("EMP001", 2027)
        with pytest.raises(ValidationError):
            _make_result(cumuls_fin=cumuls_autre_annee)

    def test_cumuls_fin_aligne_passe_la_validation(self) -> None:
        """Cas positif — ``cumuls_fin`` aligné construit l'instance."""
        cumuls_alignes = CumulsYTD.zero("EMP001", 2026)
        resultat = _make_result(cumuls_fin=cumuls_alignes)
        assert resultat.cumuls_fin == cumuls_alignes


# ===========================================================================
# Tests d'exemple — ``version >= 1``, ``id_paie`` non vide
# ===========================================================================


class TestBornesIdEtVersion:
    """``PayrollResult`` refuse ``version < 1`` et ``id_paie`` vide (Req 6.6)."""

    @pytest.mark.parametrize("version_invalide", [0, -1, -100])
    def test_version_strictement_inferieure_a_1_est_refusee(
        self, version_invalide: int
    ) -> None:
        """Req 6.6 — la version numérique commence à 1."""
        with pytest.raises(ValidationError):
            _make_result(version=version_invalide)

    def test_version_egale_a_1_est_acceptee(self) -> None:
        """Cas positif — la version initiale ``1`` construit l'instance."""
        resultat = _make_result(version=1)
        assert resultat.version == 1

    def test_version_superieure_a_1_est_acceptee(self) -> None:
        """Cas positif — les versions ultérieures (annulation-remplacement) passent."""
        resultat = _make_result(version=42)
        assert resultat.version == 42

    def test_id_paie_vide_est_refuse(self) -> None:
        """Design §Data Models 9 — ``id_paie: str = Field(..., min_length=1)``."""
        with pytest.raises(ValidationError):
            _make_result(id_paie="")

    def test_id_paie_non_vide_est_accepte(self) -> None:
        """Cas positif — un ``id_paie`` non vide construit l'instance."""
        resultat = _make_result(id_paie="PAIE-QC001-EMP001-2026-P12")
        assert resultat.id_paie == "PAIE-QC001-EMP001-2026-P12"
