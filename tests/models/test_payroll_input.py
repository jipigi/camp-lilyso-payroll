"""Property tests et tests d'exemple pour ``PayrollInput`` et ``HeuresParSemaine``.

Tâche 9.1 de la spec ``moteur-paie-contrats`` — tests écrits **avant** le
code (règle 06, TDD). Tant que la tâche 9.2 n'a pas créé
``models/payroll_input.py``, la collection pytest de ce fichier échoue
avec ``ModuleNotFoundError``. C'est le comportement attendu : les tests
précèdent l'implémentation.

Portée exacte de la tâche 9.1 (``tasks.md`` §9.1) :

- **Property 1 (partiel PayrollInput) : Immuabilité** — mutation d'un
  champ déclaré lève ``ValidationError`` (``frozen=True``).
  **Validates: Requirements 3.11**
- **Property 3 : Rejet des champs inconnus** — sur ``PayrollInput`` en
  plus d'``Employee``. La construction d'un ``PayrollInput`` avec un
  nom de champ hors contrat (et ne contenant AUCUN motif blacklisté)
  doit lever une ``ValidationError`` (``extra="forbid"``).
  **Validates: Requirements 3.8**
- **Property 5 : Rejet des champs de rémunération et de retenue hors
  matrice** — Hypothesis génère des variantes de casse/accents/
  séparateurs des motifs blacklistés (``commission``, ``bonus``,
  ``boni``, ``allocation_automobile``, ``avantage_imposable``,
  ``cotisation_syndicale``, ``pension_alimentaire``,
  ``saisie_salaire``, …) et vérifie que la construction lève
  ``UnsupportedPayrollCase`` avec un message renvoyant à WebRAS et
  PDOC (Req 11.6). **Validates: Requirements 11.4, 11.5**
- **Property 9 (partiel PayrollInput) : Non-négativité stricte de
  ``jours_feries_manuels``** — une valeur strictement négative lève
  ``ValidationError`` (sans clampage, sans substitution silencieuse
  par zéro, sans conversion en valeur absolue).
  **Validates: Requirements 3.3, 3.6**

Tests d'exemple (``tasks.md`` §9.1) :

- ``taux_vacances = Decimal("0.05")`` lève ``UnsupportedPayrollCase``
  (Req 3.5, 11.3).
- ``pay_period.frequence`` ≠ ``AUX_DEUX_SEMAINES`` reçu en cohérence
  croisée lève ``UnsupportedPayrollCase`` (Req 3.9).
- ``employee.province_travail`` ≠ ``QUEBEC`` reçu en cohérence croisée
  lève ``UnsupportedPayrollCase`` (Req 3.10).
- ``len(heures_par_semaine) != len(pay_period.semaines)`` lève
  ``ValidationError``.
- ``cumuls_debut.employe_id != employee.id`` lève ``ValidationError``.
- ``jours_feries_manuels`` absent est traité comme ``Decimal("0.00")``
  (Req 3.6).

Approche pour les cross-checks (Req 3.9 & 3.10) :

Les validateurs de ``Employee`` et de ``PayPeriod`` refusent déjà les
provinces ≠ QC et les fréquences ≠ ``AUX_DEUX_SEMAINES``. Pour tester
que la cohérence croisée de ``PayrollInput`` détecte AUSSI l'écart
(défense en profondeur, cf. Req 3.9 / 3.10), nous construisons ces
composants via ``Employee.model_construct`` / ``PayPeriod.model_construct``
qui court-circuite les validateurs — puis nous passons l'instance
« invalide » à ``PayrollInput``. Le comportement Pydantic v2 par défaut
(``revalidate_instances="never"``) garantit que le composant n'est PAS
re-validé lors de la construction du ``PayrollInput`` ; c'est donc la
cohérence croisée de ``PayrollInput`` — et rien d'autre — qui détecte
l'écart.

Contexte design (extrait, ``design.md`` §Components 8 et §Data Models 8) :

- ``HeuresParSemaine`` : Pydantic v2, ``frozen=True``, ``extra="forbid"``.
  Champs ``heures_normales`` et ``heures_supplementaires`` ∈ [0, 168].
- ``PayrollInput`` : Pydantic v2, ``frozen=True``, ``extra="forbid"``.
  13 champs (voir liste ``CHAMPS_DECLARES_PAYROLL_INPUT`` ci-dessous).
- Blacklists explicites au niveau du module :
  ``_CHAMPS_REMUNERATION_HORS_MATRICE`` (commission, bonus, boni,
  pourboires, tips, allocation_automobile, car_allowance,
  logement_fourni, avantage_logement, options_achat_actions,
  stock_options, actions, shares, avantage_imposable, ...) et
  ``_CHAMPS_RETENUE_HORS_MATRICE`` (assurance_collective,
  group_insurance, rpa, reer_collectif, group_rrsp,
  cotisation_syndicale, union_dues, pension_alimentaire, alimony,
  saisie_salaire, garnishment).
- ``model_validator(mode="before")`` : rejette les clés hors matrice
  avec ``UnsupportedPayrollCase``.
- ``model_validator(mode="after")`` : cohérence croisée (province,
  fréquence, taux vacances, longueur ``heures_par_semaine``,
  appariement ``cumuls_debut``).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire, ``float`` interdit. Tous les
  montants ci-dessous sont construits à partir de chaînes.
- Règle 03 — périmètre Camp LilySO ; les cas hors matrice lèvent
  ``UnsupportedPayrollCase`` par construction.
- Règle 04 — aucune donnée personnelle réelle. Les identifiants et
  libellés sont fictifs (``EMP001``, ``Monitrice EMP001``, ...).
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie, Juridiction
from models.exceptions import UnsupportedPayrollCase
from models.pay_period import PayPeriod, WeekSegment

# Discipline règle 06 (TDD) : import module-level. Tant que
# ``models/payroll_input.py`` n'existe pas (tâche 9.2 non réalisée), la
# collection pytest de ce fichier échoue avec ``ModuleNotFoundError``.
# C'est exactement l'échec attendu — les tests précèdent l'implémentation.
from models.payroll_input import HeuresParSemaine, PayrollInput  # noqa: E402


# ===========================================================================
# Constantes locales
# ===========================================================================


#: Les 13 champs déclarés par ``PayrollInput`` selon le design §Components 8
#: (contrat porté par le user prompt de la tâche 9.1). Le suffixe
#: ``_effectif`` / ``_effective`` distingue les paramètres qui peuvent
#: différer entre la fiche employé (défaut annuel) et la paie courante
#: (valeur effective utilisée pour ce calcul).
#:
#: Aucune autre clé n'est admise à la construction — cela est vérifié par
#: Property 3 (extra="forbid") et par le test d'exemple
#: ``test_les_13_champs_declares_existent_exactement``.
CHAMPS_DECLARES_PAYROLL_INPUT: tuple[str, ...] = (
    "employee",
    "pay_period",
    "heures_par_semaine",
    "taux_horaire_effectif",
    "taux_vacances",
    "jours_feries_manuels",
    "montant_total_TP1015_3_effectif",
    "exoneration_TP1015_3_effectif",
    "retenue_additionnelle_QC_effective",
    "montant_total_TD1_effectif",
    "exoneration_TD1_effective",
    "retenue_additionnelle_federale_effective",
    "cumuls_debut",
)


#: Motifs de rémunération hors matrice (design §Components 8,
#: Req 11.4). Les valeurs listées ici sont utilisées par Property 5
#: pour générer des variantes de casse / accents / séparateurs qui
#: doivent toutes être refusées.
MOTIFS_REMUNERATION_HORS_MATRICE: tuple[str, ...] = (
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
)


#: Motifs de retenue hors matrice (design §Components 8, Req 11.5).
MOTIFS_RETENUE_HORS_MATRICE: tuple[str, ...] = (
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
)


#: Union des deux blacklists — utilisée par Property 5.
MOTIFS_HORS_MATRICE: tuple[str, ...] = (
    MOTIFS_REMUNERATION_HORS_MATRICE + MOTIFS_RETENUE_HORS_MATRICE
)


#: Motifs sensibles (règle 04). Dupliquée localement pour découpler ce
#: fichier de la structure interne de ``models/_validators.py`` (voir
#: recommandation identique dans ``tests/models/test_employee.py``).
#: Utilisée par Property 3 pour EXCLURE les noms sensibles (isolation
#: vs. Property 4, qui est déjà testée sur ``Employee``).
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


# ===========================================================================
# Utilitaires de normalisation (miroir simplifié de _validators)
# ===========================================================================


def _normaliser(chaine: str) -> str:
    """Retourne une forme comparable (miroir de ``_validators``).

    Applique NFKD → suppression des marques de combinaison → minuscule
    → suppression de tout caractère hors ``[a-z0-9]``. Le résultat sert
    à comparer une clé arbitraire à un motif blacklisté par recherche
    substring — c'est exactement ce que ``reject_sensitive_fields`` et
    la garde ``_rejeter_champs_hors_matrice_et_sensibles`` de
    ``PayrollInput`` font en interne (design §Components 3.2 et §8).
    """
    nfkd = unicodedata.normalize("NFKD", chaine)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sans_accents.lower())


_MOTIFS_HORS_MATRICE_NORMALISES: tuple[str, ...] = tuple(
    _normaliser(m) for m in MOTIFS_HORS_MATRICE if _normaliser(m)
)


_MOTIFS_SENSIBLES_NORMALISES: tuple[str, ...] = tuple(
    _normaliser(m) for m in MOTIFS_SENSIBLES if _normaliser(m)
)


def _contient_motif_hors_matrice(nom: str) -> bool:
    """``True`` si ``nom`` (normalisé) contient un motif hors matrice."""
    forme = _normaliser(nom)
    return any(motif in forme for motif in _MOTIFS_HORS_MATRICE_NORMALISES)


def _contient_motif_sensible(nom: str) -> bool:
    """``True`` si ``nom`` (normalisé) contient un motif sensible."""
    forme = _normaliser(nom)
    return any(motif in forme for motif in _MOTIFS_SENSIBLES_NORMALISES)


def _message_cite_webras_et_pdoc(exc: BaseException) -> bool:
    """``True`` si le message d'exception cite WebRAS ET PDOC (Req 11.6).

    Property 16 (« Contrat des messages d'exception du domaine ») exige
    que tout ``UnsupportedPayrollCase`` levé à la frontière renvoie
    l'utilisateur vers les outils officiels de repli. Comparaison
    insensible à la casse.
    """
    message = str(exc).lower()
    return "webras" in message and "pdoc" in message


# ===========================================================================
# Fabrique locale d'un ``PayrollInput`` valide
# ===========================================================================


# Dates de la période de paie du corpus de tests : 2 semaines contiguës
# couvrant [2026-06-01 ; 2026-06-14]. Choix arbitraire — le contrat ne
# dépend d'aucune date fiscale particulière.
_DATE_DEBUT = date(2026, 6, 1)
_DATE_FIN = date(2026, 6, 14)


def _employee_valide() -> Employee:
    """Construit un ``Employee`` valide anonymisé (règle 04)."""
    return Employee(
        id="EMP001",
        nom_affichage="Monitrice EMP001",
        date_naissance=date(2005, 6, 15),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Monitrice",
        taux_horaire_base=Decimal("15.75"),
        date_embauche=date(2026, 6, 1),
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("18952.00"),
        montant_total_TD1=Decimal("16452.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )


def _pay_period_valide() -> PayPeriod:
    """Construit un ``PayPeriod`` bi-hebdomadaire valide (14 jours)."""
    w0 = WeekSegment(
        date_debut=_DATE_DEBUT,
        date_fin=_DATE_DEBUT + timedelta(days=6),
        heures_normales=Decimal("40.00"),
        heures_supplementaires=Decimal("0.00"),
    )
    w1 = WeekSegment(
        date_debut=_DATE_DEBUT + timedelta(days=7),
        date_fin=_DATE_FIN,
        heures_normales=Decimal("40.00"),
        heures_supplementaires=Decimal("0.00"),
    )
    return PayPeriod(
        numero_periode=12,
        date_debut=_DATE_DEBUT,
        date_fin=_DATE_FIN,
        date_paiement=_DATE_FIN + timedelta(days=3),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=27,
        annee_fiscale=2026,
        semaines=(w0, w1),
    )


def _cumuls_debut_valides(employe_id: str = "EMP001", annee: int = 2026) -> CumulsYTD:
    """``CumulsYTD.zero`` — cumul neutre au début de la première paie."""
    return CumulsYTD.zero(employe_id, annee)


def _heures_par_semaine_valides() -> tuple[HeuresParSemaine, HeuresParSemaine]:
    """Deux ``HeuresParSemaine`` en cohérence avec la période bi-hebdo."""
    return (
        HeuresParSemaine(
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
        ),
        HeuresParSemaine(
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
        ),
    )


def _kwargs_valides_payroll_input(**overrides: Any) -> dict[str, Any]:
    """Kwargs valides par défaut pour ``PayrollInput``, avec surcharges.

    Toutes les valeurs sont fictives (règle 04). Cette fabrique permet
    à chaque test d'isoler la contrainte à vérifier en surchargeant un
    seul champ, sans réécrire l'intégralité du contrat.
    """
    kwargs: dict[str, Any] = {
        "employee": _employee_valide(),
        "pay_period": _pay_period_valide(),
        "heures_par_semaine": _heures_par_semaine_valides(),
        "taux_horaire_effectif": Decimal("15.75"),
        "taux_vacances": Decimal("0.04"),
        "jours_feries_manuels": Decimal("0.00"),
        "montant_total_TP1015_3_effectif": Decimal("18952.00"),
        "exoneration_TP1015_3_effectif": False,
        "retenue_additionnelle_QC_effective": Decimal("0.00"),
        "montant_total_TD1_effectif": Decimal("16452.00"),
        "exoneration_TD1_effective": False,
        "retenue_additionnelle_federale_effective": Decimal("0.00"),
        "cumuls_debut": _cumuls_debut_valides(),
    }
    kwargs.update(overrides)
    return kwargs


# ===========================================================================
# Tests d'exemple — Structure du modèle
# ===========================================================================


class TestPayrollInputChampsDeclares:
    """Vérifie la liste exacte des 13 champs déclarés (design §Components 8)."""

    def test_les_13_champs_declares_existent_exactement(self) -> None:
        """Req 3.1 (agrégation exhaustive), Req 3.8 (``extra="forbid"``)."""
        champs = set(PayrollInput.model_fields.keys())
        attendus = set(CHAMPS_DECLARES_PAYROLL_INPUT)
        manquants = attendus - champs
        assert not manquants, (
            f"PayrollInput doit exposer les champs du design §Components 8. "
            f"Manquants : {manquants!r}."
        )
        superflus = champs - attendus
        assert not superflus, (
            f"PayrollInput expose des champs non prévus par le design : "
            f"{superflus!r}."
        )
        assert len(champs) == 13, f"Attendu 13 champs, reçu {len(champs)}."

    def test_construction_valide_reussit(self) -> None:
        """Sanity — la fabrique locale produit bien un ``PayrollInput`` valide.

        Ce test verrouille la fabrique ``_kwargs_valides_payroll_input`` :
        si une contrainte de ``PayrollInput`` évolue de manière
        incompatible avec ces valeurs anonymisées, ce test échoue AVANT
        les properties, ce qui pointe directement la régression.
        """
        pi = PayrollInput(**_kwargs_valides_payroll_input())
        assert pi.employee.id == "EMP001"
        assert pi.pay_period.frequence is FrequencePaie.AUX_DEUX_SEMAINES
        assert pi.taux_vacances == Decimal("0.04")
        assert pi.jours_feries_manuels == Decimal("0.00")
        assert pi.cumuls_debut.employe_id == "EMP001"


# ===========================================================================
# Test d'exemple — ``jours_feries_manuels`` optionnel avec défaut 0.00
# ===========================================================================


class TestJoursFeriesManuelsOptionnel:
    """Req 3.6 — ``jours_feries_manuels`` absent traité comme ``Decimal("0.00")``."""

    def test_jours_feries_manuels_absent_vaut_zero(self) -> None:
        """Req 3.6 — absence de la clé équivaut à ``Decimal("0.00")``.

        Le contrat exige une VALEUR PAR DÉFAUT explicite (pas ``None``,
        pas un placeholder), afin que les modules de calcul aval
        puissent additionner ce champ à d'autres montants sans branche
        conditionnelle.
        """
        kwargs = _kwargs_valides_payroll_input()
        # On retire la clé pour vérifier le comportement par défaut.
        kwargs.pop("jours_feries_manuels")
        pi = PayrollInput(**kwargs)
        assert pi.jours_feries_manuels == Decimal("0.00")
        # Vérification stricte du type : c'est bien un ``Decimal``,
        # pas un ``int`` 0 coercé (règle 01).
        assert isinstance(pi.jours_feries_manuels, Decimal)

    def test_jours_feries_manuels_zero_explicite_est_accepte(self) -> None:
        """La borne inférieure ``0.00`` est incluse (``ge=Decimal("0")``)."""
        pi = PayrollInput(
            **_kwargs_valides_payroll_input(jours_feries_manuels=Decimal("0.00"))
        )
        assert pi.jours_feries_manuels == Decimal("0.00")

    def test_jours_feries_manuels_positif_est_accepte(self) -> None:
        """Un montant positif est admis (cas nominal d'un jour férié travaillé)."""
        pi = PayrollInput(
            **_kwargs_valides_payroll_input(jours_feries_manuels=Decimal("125.00"))
        )
        assert pi.jours_feries_manuels == Decimal("125.00")


# ===========================================================================
# Tests d'exemple — Refus à la frontière (Req 3.5, 3.9, 3.10, 11.3)
# ===========================================================================


class TestPayrollInputFrontiereHorsMatrice:
    """Refus fail-fast des cas hors matrice (règle 03)."""

    def test_taux_vacances_005_leve_unsupported_payroll_case(self) -> None:
        """Req 3.5, 11.3 — ``taux_vacances = 0.05`` refusé.

        Camp LilySO applique 4 % (nouvelles saisons) ou 6 % (à partir de
        la troisième année). Toute autre valeur est hors matrice.
        """
        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(
                **_kwargs_valides_payroll_input(taux_vacances=Decimal("0.05"))
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
        """Req 3.5, 11.3 — toute valeur ∉ ``{0.04, 0.06}`` refusée."""
        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(
                **_kwargs_valides_payroll_input(taux_vacances=taux_invalide)
            )

    def test_taux_vacances_006_est_accepte(self) -> None:
        """Sanity — la borne haute ``0.06`` de Req 11.3 est admise."""
        pi = PayrollInput(
            **_kwargs_valides_payroll_input(taux_vacances=Decimal("0.06"))
        )
        assert pi.taux_vacances == Decimal("0.06")

    def test_pay_period_frequence_hors_matrice_leve_unsupported_en_coherence_croisee(
        self,
    ) -> None:
        """Req 3.9 — cohérence croisée : ``pay_period.frequence`` ≠
        ``AUX_DEUX_SEMAINES`` DOIT être détectée par ``PayrollInput``.

        ``PayPeriod`` refuse déjà toute fréquence hors matrice à sa
        propre construction. Pour tester que la cohérence croisée de
        ``PayrollInput`` détecte AUSSI l'écart (défense en profondeur,
        design §Composant 8), on construit un ``PayPeriod`` via
        :meth:`PayPeriod.model_construct` qui bypasse les validateurs,
        avec une chaîne libre en guise de ``frequence``. Par défaut
        Pydantic v2 (``revalidate_instances="never"``), l'instance
        n'est PAS re-validée à l'assignation au champ ``pay_period`` de
        ``PayrollInput`` — c'est donc le validateur
        ``_coherence_croisee`` du ``PayrollInput`` qui doit détecter et
        rejeter l'incohérence.
        """
        # ``model_construct`` accepte n'importe quelle valeur pour
        # ``frequence`` (pas de coercition ni de validation). On lui
        # passe une chaîne représentant une fréquence hors matrice
        # (« hebdomadaire »).
        pay_period_invalide = PayPeriod.model_construct(
            numero_periode=12,
            date_debut=_DATE_DEBUT,
            date_fin=_DATE_FIN,
            date_paiement=_DATE_FIN + timedelta(days=3),
            frequence="hebdomadaire",  # type: ignore[arg-type]
            nb_periodes_annuelles=52,
            annee_fiscale=2026,
            semaines=_pay_period_valide().semaines,
        )
        # Sanity : ``model_construct`` n'a effectivement pas rejeté la
        # fréquence hors matrice — le PayPeriod « invalide » existe.
        assert pay_period_invalide.frequence == "hebdomadaire"

        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(
                **_kwargs_valides_payroll_input(pay_period=pay_period_invalide)
            )

    def test_employee_province_non_quebec_leve_unsupported_en_coherence_croisee(
        self,
    ) -> None:
        """Req 3.10 — cohérence croisée : ``employee.province_travail`` ≠
        ``QUEBEC`` DOIT être détectée par ``PayrollInput``.

        Même approche que le test précédent : ``Employee.model_construct``
        court-circuite la validation frontière d'``Employee`` pour
        permettre à ``PayrollInput`` de démontrer sa propre garde de
        cohérence croisée (défense en profondeur, design §Composant 8).
        """
        employee_valide = _employee_valide()
        # Instance dérivée qui bypasse la validation Employee : on peut
        # y injecter ``province_travail=CANADA`` sans être bloqué par
        # ``_refuser_hors_matrice`` d'``Employee``.
        employee_invalide = Employee.model_construct(
            **{**employee_valide.model_dump(), "province_travail": Juridiction.CANADA}
        )
        # Sanity : l'instance dérivée porte bien la province hors matrice.
        assert employee_invalide.province_travail is Juridiction.CANADA

        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(
                **_kwargs_valides_payroll_input(employee=employee_invalide)
            )


# ===========================================================================
# Tests d'exemple — Cohérence croisée non-métier (Req 3.1, 3.7)
# ===========================================================================


class TestPayrollInputCoherenceCroiseeNonMetier:
    """Cohérence croisée d'incohérences de forme (``ValidationError``)."""

    def test_heures_par_semaine_de_longueur_incorrecte_leve_validation_error(
        self,
    ) -> None:
        """``len(heures_par_semaine) != len(pay_period.semaines)`` refusé.

        Cette contrainte garantit que chaque ``WeekSegment`` de la
        période a exactement un ``HeuresParSemaine`` associé — condition
        indispensable au calcul futur des heures supplémentaires par
        semaine (Req 3.7, design §Composant 8).

        Discipline exception : c'est une incohérence de FORME (non un
        cas hors matrice), donc c'est une ``ValidationError`` Pydantic
        qui est levée, pas ``UnsupportedPayrollCase``.
        """
        # Une seule ``HeuresParSemaine`` alors que la période contient
        # 2 ``WeekSegment``.
        une_seule_semaine = (
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
            ),
        )
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(heures_par_semaine=une_seule_semaine)
            )

    def test_heures_par_semaine_de_trois_semaines_leve_validation_error(
        self,
    ) -> None:
        """Trois semaines pour une période à deux ``WeekSegment`` refusé."""
        trois_semaines = (
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
            ),
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
            ),
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
            ),
        )
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(heures_par_semaine=trois_semaines)
            )

    def test_cumuls_debut_employe_id_different_leve_validation_error(self) -> None:
        """``cumuls_debut.employe_id != employee.id`` refusé (Req 3.1).

        Les cumuls YTD sont indexés par employé (Req 7.2). Un
        ``PayrollInput`` dont le cumul de départ appartient à un autre
        employé est incohérent — la garde de cohérence croisée doit le
        rejeter comme une erreur de forme.
        """
        cumuls_autre_employe = CumulsYTD.zero("EMP999", 2026)
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(cumuls_debut=cumuls_autre_employe)
            )

    def test_cumuls_debut_annee_civile_differente_leve_validation_error(self) -> None:
        """``cumuls_debut.annee_civile != pay_period.annee_fiscale`` refusé.

        Les cumuls YTD sont indexés par année civile (Req 7.2). Une
        paie de 2026 ne peut pas partir d'un cumul YTD 2025 — la
        garde de cohérence croisée doit le rejeter.
        """
        cumuls_autre_annee = CumulsYTD.zero("EMP001", 2025)
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(cumuls_debut=cumuls_autre_annee)
            )


# ===========================================================================
# Property 1 (partiel PayrollInput) — Immuabilité
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles du
# domaine (composante ``PayrollInput``). *Pour tout* ``PayrollInput``
# valide, la mutation d'un de ses 13 champs déclarés doit lever une
# erreur de validation Pydantic (``frozen=True``).
#
# **Validates: Requirements 3.11**
# ===========================================================================


class TestProperty1ImmuabiliteExemples:
    """Exemples explicites de mutation refusée."""

    def test_mutation_taux_horaire_effectif_leve(self) -> None:
        pi = PayrollInput(**_kwargs_valides_payroll_input())
        with pytest.raises(ValidationError):
            pi.taux_horaire_effectif = Decimal("20.00")  # type: ignore[misc]

    def test_mutation_taux_vacances_leve(self) -> None:
        pi = PayrollInput(**_kwargs_valides_payroll_input())
        with pytest.raises(ValidationError):
            pi.taux_vacances = Decimal("0.06")  # type: ignore[misc]

    def test_mutation_jours_feries_manuels_leve(self) -> None:
        pi = PayrollInput(**_kwargs_valides_payroll_input())
        with pytest.raises(ValidationError):
            pi.jours_feries_manuels = Decimal("50.00")  # type: ignore[misc]

    def test_mutation_cumuls_debut_leve(self) -> None:
        pi = PayrollInput(**_kwargs_valides_payroll_input())
        autre_cumul = CumulsYTD.zero("EMP001", 2026)
        with pytest.raises(ValidationError):
            pi.cumuls_debut = autre_cumul  # type: ignore[misc]


@pytest.mark.property
class TestProperty1ImmuabiliteProperty:
    """Property 1 (Hypothesis) — mutation refusée sur tout champ déclaré."""

    # Feature: moteur-paie-contrats, Property 1: Immuabilité des modèles
    # du domaine (composante ``PayrollInput``).
    @given(champ_a_muter=st.sampled_from(CHAMPS_DECLARES_PAYROLL_INPUT))
    @settings(
        max_examples=len(CHAMPS_DECLARES_PAYROLL_INPUT) * 2,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_toute_mutation_dun_champ_leve_validation_error(
        self, champ_a_muter: str
    ) -> None:
        """Req 3.11 — ``frozen=True`` refuse toute mutation post-construction.

        Le type de la nouvelle valeur n'importe pas : c'est l'acte de
        mutation qui est refusé par Pydantic (``type='frozen_instance'``
        ou ``'frozen_field'`` selon la version).
        """
        pi = PayrollInput(**_kwargs_valides_payroll_input())
        with pytest.raises(ValidationError):
            # ``getattr(pi, champ_a_muter)`` : valeur courante — on la
            # réassigne, ce qui est refusé sans dépendre d'une valeur
            # arbitraire.
            setattr(pi, champ_a_muter, getattr(pi, champ_a_muter))


# ===========================================================================
# Property 3 — Rejet des champs inconnus (``extra="forbid"``) (Req 3.8)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 3: Rejet universel des champs
# inconnus (``extra="forbid"``) — composante ``PayrollInput``. *Pour tout*
# nom de champ non déclaré dans le contrat ``PayrollInput``, qui ne
# contient NI motif blacklisté hors matrice (sinon c'est Property 5),
# NI motif sensible (sinon c'est Property 4 sur ``Employee``), la
# construction avec ce champ additionnel doit lever une
# ``ValidationError``.
#
# **Validates: Requirements 3.8**
# ===========================================================================


@st.composite
def _nom_champ_inconnu_non_sensible_non_blacklisté(draw: st.DrawFn) -> str:
    """Génère un nom de champ hors contrat, non sensible, non blacklisté.

    Contraintes essentielles à l'isolation de Property 3 :

    - le nom NE DOIT PAS être un des 13 champs déclarés (sinon la
      construction pourrait réussir et la property serait fausse par
      erreur de setup) ;
    - le nom NE DOIT PAS contenir un motif sensible (règle 04) — sinon
      le rejet vient de ``reject_sensitive_fields`` (Property 4), pas
      d'``extra="forbid"`` ;
    - le nom NE DOIT PAS contenir un motif hors matrice (Req 11.4/11.5)
      — sinon le rejet vient de la garde
      ``_rejeter_champs_hors_matrice_et_sensibles`` en amont
      (Property 5), pas d'``extra="forbid"``.

    Ces trois exclusions matérialisent la stratification des refus par
    le contrat : Property 3 vérifie UNIQUEMENT le comportement
    ``extra="forbid"``.
    """
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
    assume(nom not in CHAMPS_DECLARES_PAYROLL_INPUT)
    assume(not _contient_motif_sensible(nom))
    assume(not _contient_motif_hors_matrice(nom))
    # Au moins un caractère non-``_`` pour éviter ``_``, ``__``, etc.
    assume(any(c != "_" for c in nom))
    return nom


@pytest.mark.property
class TestProperty3ExtraForbidProperty:
    """Property 3 (Hypothesis) — ``extra="forbid"`` sur ``PayrollInput``."""

    # Feature: moteur-paie-contrats, Property 3: Rejet universel des
    # champs inconnus (`extra="forbid"`) — composante ``PayrollInput``.
    @given(nom_inconnu=_nom_champ_inconnu_non_sensible_non_blacklisté())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_tout_champ_inconnu_leve_validation_error(
        self, nom_inconnu: str
    ) -> None:
        """Requirement 3.8 — ``extra="forbid"`` refuse tout champ non déclaré."""
        kwargs_pollues = _kwargs_valides_payroll_input(**{nom_inconnu: "arbitraire"})
        with pytest.raises(ValidationError):
            PayrollInput(**kwargs_pollues)


class TestProperty3ExtraForbidExemples:
    """Cas explicites de champ hors contrat — verrouillent le comportement."""

    @pytest.mark.parametrize(
        "champ_inconnu",
        [
            "champ_inexistant",
            "notes",
            "commentaire_rh",
            "identifiant_dossier",
            "hash_paiement",
            "reference_bancaire_paie",
        ],
    )
    def test_champ_inconnu_documente_est_refuse(self, champ_inconnu: str) -> None:
        """Sanity — la liste des champs du design est effectivement close."""
        assert champ_inconnu not in CHAMPS_DECLARES_PAYROLL_INPUT, (
            f"Le test suppose que '{champ_inconnu}' n'est PAS un champ "
            "déclaré ; si le design est étendu, mettre à jour ce test."
        )
        assert not _contient_motif_sensible(champ_inconnu), (
            f"'{champ_inconnu}' contient un motif sensible ; ce n'est "
            "PAS ce qu'on teste ici (Property 3, isolation vs. Property 4)."
        )
        assert not _contient_motif_hors_matrice(champ_inconnu), (
            f"'{champ_inconnu}' contient un motif hors matrice ; ce "
            "n'est PAS ce qu'on teste ici (Property 3, isolation vs. "
            "Property 5)."
        )
        with pytest.raises(ValidationError):
            PayrollInput(**_kwargs_valides_payroll_input(**{champ_inconnu: "valeur"}))


# ===========================================================================
# Property 5 — Rejet des champs de rémunération et de retenue hors matrice
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 5: Rejet des champs hors matrice
# — composante ``PayrollInput``. *Pour tout* motif blacklisté
# (rémunération : commission, bonus, boni, allocation_automobile,
# avantage_imposable, options_achat_actions, actions, pourboires,
# logement_fourni, … ; retenue : cotisation_syndicale, pension_alimentaire,
# saisie_salaire, assurance_collective, rpa, reer_collectif, …) et *pour
# toute* variante de casse, d'accentuation et de séparateurs, la
# construction d'un ``PayrollInput`` avec cette clé additionnelle DOIT
# lever ``UnsupportedPayrollCase`` avec un message renvoyant explicitement
# à WebRAS et PDOC (Req 11.6, Property 16).
#
# **Validates: Requirements 11.4, 11.5**
# ===========================================================================


# --- Stratégies Hypothesis dédiées aux variantes de motifs hors matrice ---
#
# Miroir simplifié des stratégies de ``test_validators.py`` / ``test_employee.py``
# adapté à Property 5. La normalisation Pydantic (``lower().replace("-",
# "_").replace(" ", "_")``) documentée en design §Composant 8 impose
# quelques variations spécifiques :
#
# - casse (``COMMISSION``, ``Commission``, ``cOmMiSsIoN``) ;
# - séparateurs (``allocation_automobile`` → ``allocation-automobile``
#   → ``allocation automobile``) ;
# - accents optionnels (``pension_alimentaire`` reste ASCII, mais
#   ``régime_pension`` ou ``cotisation_syndicale`` peuvent apparaître
#   avec accents dans les gabarits Excel).

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
        draw(st.sampled_from([c.lower(), c.upper()])) if c.isalpha() else c
        for c in base
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
def _cle_hors_matrice_variee(draw: st.DrawFn) -> str:
    """Génère une clé qui contient un motif hors matrice, avec variantes.

    Étapes :

    1. Choisir un motif blacklisté (rémunération OU retenue).
    2. Varier la casse caractère par caractère.
    3. Injecter des accents sur certaines lettres.
    4. Remplacer ``_`` par ``_``, ``-`` ou espace.

    Aucun préfixe / suffixe n'est ajouté pour Property 5 : les blacklists
    du design §Composant 8 utilisent une normalisation ``lower + replace``
    (voir extrait design), donc la détection porte sur le motif normalisé
    EXACT, pas sur une recherche substring. Les motifs sont testés « en
    dur » — c'est le contrat de refus des CLÉS blacklistées, pas la
    règle 04 (qui, elle, utilise une recherche substring et fait l'objet
    de Property 4 sur ``Employee``).
    """
    motif = draw(st.sampled_from(MOTIFS_HORS_MATRICE))
    variee = draw(_casse_variee(motif))
    variee = draw(_accents_varies(variee))
    variee = draw(_separateurs_varies(variee))
    return variee


@pytest.mark.property
class TestProperty5RejetChampsHorsMatriceProperty:
    """Property 5 (Hypothesis) — refus des motifs blacklistés."""

    # Feature: moteur-paie-contrats, Property 5: Rejet des champs hors
    # matrice (rémunération et retenue) — composante ``PayrollInput``.
    @given(cle_blacklistee=_cle_hors_matrice_variee())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_toute_variante_dun_motif_hors_matrice_leve_unsupported(
        self, cle_blacklistee: str
    ) -> None:
        """Req 11.4, 11.5 — refus + message renvoyant à WebRAS/PDOC (Req 11.6)."""
        # Sanity : la clé générée coïncide bien avec un motif blacklisté.
        assert _contient_motif_hors_matrice(cle_blacklistee), (
            f"La stratégie a généré '{cle_blacklistee}' qui NE contient PAS "
            "de motif blacklisté ; la property test ne serait alors pas "
            "significative."
        )
        # Filtre défensif : si la variante coïncide accidentellement avec
        # un champ déclaré (peu probable vu les motifs), on renonce.
        assume(cle_blacklistee not in CHAMPS_DECLARES_PAYROLL_INPUT)

        kwargs_pollues = _kwargs_valides_payroll_input(**{cle_blacklistee: "valeur"})
        with pytest.raises(UnsupportedPayrollCase) as exc_info:
            PayrollInput(**kwargs_pollues)
        # Property 16 (Req 11.6) — le message renvoie explicitement vers
        # WebRAS ET PDOC.
        assert _message_cite_webras_et_pdoc(exc_info.value), (
            f"Le message d'UnsupportedPayrollCase pour un champ hors matrice "
            f"'{cle_blacklistee}' DOIT renvoyer vers WebRAS ET PDOC (Req 11.6). "
            f"Reçu : {exc_info.value!s}"
        )


class TestProperty5RejetChampsHorsMatriceExemples:
    """Cas explicites — chaque motif de la blacklist est refusé."""

    @pytest.mark.parametrize("motif", MOTIFS_REMUNERATION_HORS_MATRICE)
    def test_motif_remuneration_hors_matrice_leve_unsupported(
        self, motif: str
    ) -> None:
        """Req 11.4 — les motifs de rémunération hors matrice sont refusés."""
        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(**_kwargs_valides_payroll_input(**{motif: "valeur"}))

    @pytest.mark.parametrize("motif", MOTIFS_RETENUE_HORS_MATRICE)
    def test_motif_retenue_hors_matrice_leve_unsupported(self, motif: str) -> None:
        """Req 11.5 — les motifs de retenue hors matrice sont refusés."""
        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(**_kwargs_valides_payroll_input(**{motif: "valeur"}))

    @pytest.mark.parametrize(
        "motif_avec_valeur_decimal",
        [
            "commission",
            "bonus",
            "boni",
            "allocation_automobile",
            "avantage_imposable",
            "cotisation_syndicale",
            "pension_alimentaire",
            "saisie_salaire",
        ],
    )
    def test_motif_hors_matrice_avec_valeur_decimal_leve_unsupported(
        self, motif_avec_valeur_decimal: str
    ) -> None:
        """La valeur associée à la clé n'importe pas — la clé seule suffit.

        Design §Composant 8 : le refus porte sur la CLÉ (nom de champ),
        pas sur la valeur. Un ``Decimal("0.00")`` associé à un champ
        blacklisté reste refusé.
        """
        with pytest.raises(UnsupportedPayrollCase):
            PayrollInput(
                **_kwargs_valides_payroll_input(
                    **{motif_avec_valeur_decimal: Decimal("100.00")}
                )
            )


# ===========================================================================
# Property 9 (partiel PayrollInput) — Non-négativité de ``jours_feries_manuels``
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 9: Non-négativité stricte des
# ``Decimal`` marqués comme tels — composante ``PayrollInput``,
# champ ``jours_feries_manuels``. *Pour toute* valeur ``Decimal``
# strictement négative fournie à ``jours_feries_manuels``, la
# construction DOIT lever ``ValidationError``, SANS clampage
# silencieux, SANS substitution par zéro, SANS conversion en valeur
# absolue (Req 3.6 explicitement).
#
# **Validates: Requirements 3.3, 3.6**
# ===========================================================================


@st.composite
def _decimal_strictement_negatif(draw: st.DrawFn) -> Decimal:
    """Génère un ``Decimal`` strictement < 0, deux décimales."""
    return draw(
        st.decimals(
            min_value=Decimal("-100000.00"),
            max_value=Decimal("-0.01"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@pytest.mark.property
class TestProperty9JoursFeriesManuelsNonNegatifProperty:
    """Property 9 (Hypothesis) — ``jours_feries_manuels < 0`` refusé."""

    # Feature: moteur-paie-contrats, Property 9: Non-négativité des
    # ``Decimal`` marqués comme tels — ``jours_feries_manuels`` du
    # ``PayrollInput``.
    @given(valeur_negative=_decimal_strictement_negatif())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    def test_toute_valeur_strictement_negative_est_refusee(
        self, valeur_negative: Decimal
    ) -> None:
        """Req 3.6 — refus sans clampage, substitution ni valeur absolue.

        Le contrat exige un rejet EXPLICIT : ni ``Decimal("0.00")``
        silencieux, ni ``abs(valeur)``. Une ``ValidationError`` doit
        être levée (contrainte ``ge=Decimal("0")`` du ``Field``).
        """
        assert valeur_negative < Decimal("0")  # sanity Hypothesis
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(jours_feries_manuels=valeur_negative)
            )


class TestProperty9JoursFeriesManuelsExemples:
    """Cas explicites — verrouillent les bornes critiques."""

    @pytest.mark.parametrize(
        "valeur_neg",
        [
            Decimal("-0.01"),
            Decimal("-1.00"),
            Decimal("-50.00"),
            Decimal("-125.00"),
            Decimal("-9999.99"),
        ],
        ids=["moins_1_cent", "moins_1", "moins_50", "moins_125", "gros_negatif"],
    )
    def test_valeur_negative_explicite_est_refusee(self, valeur_neg: Decimal) -> None:
        """Req 3.6 — chaque exemple négatif emblématique est refusé."""
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(jours_feries_manuels=valeur_neg)
            )

    def test_valeur_negative_nest_pas_silencieusement_clamppee(self) -> None:
        """Req 3.6 — ``PayrollInput(jours_feries_manuels=-1)`` NE DOIT PAS
        produire silencieusement un ``PayrollInput`` avec
        ``jours_feries_manuels = Decimal("0.00")`` ou ``Decimal("1.00")``.
        """
        # Sanity négative : si le contrat était brisé (clampage à zéro
        # ou passage en valeur absolue), la ligne suivante réussirait ;
        # elle DOIT lever.
        with pytest.raises(ValidationError):
            PayrollInput(
                **_kwargs_valides_payroll_input(jours_feries_manuels=Decimal("-1.00"))
            )


# ===========================================================================
# Tests d'exemple — ``HeuresParSemaine``
# ===========================================================================
#
# ``HeuresParSemaine`` est un modèle utilitaire consommé par
# ``PayrollInput.heures_par_semaine``. Design §Composant 8 :
# ``frozen=True``, ``extra="forbid"``, deux champs ``Decimal`` bornés
# à ``[0, 168]``. Ces tests d'exemple cadenassent son contrat de forme
# indépendamment de ``PayrollInput``.


class TestHeuresParSemaineExemples:
    """Invariants de ``HeuresParSemaine`` (design §Composant 8)."""

    def test_construction_valide_conserve_les_valeurs(self) -> None:
        hps = HeuresParSemaine(
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("2.50"),
        )
        assert hps.heures_normales == Decimal("40.00")
        assert hps.heures_supplementaires == Decimal("2.50")

    def test_heures_zero_sont_acceptees(self) -> None:
        """La borne inférieure ``0`` est incluse."""
        hps = HeuresParSemaine(
            heures_normales=Decimal("0"),
            heures_supplementaires=Decimal("0"),
        )
        assert hps.heures_normales == Decimal("0")

    def test_heures_normales_negatives_sont_rejetees(self) -> None:
        """Borne inférieure ``ge=Decimal("0")``."""
        with pytest.raises(ValidationError):
            HeuresParSemaine(
                heures_normales=Decimal("-0.01"),
                heures_supplementaires=Decimal("0.00"),
            )

    def test_heures_normales_au_dela_de_168_sont_rejetees(self) -> None:
        """Borne supérieure physique ``le=Decimal("168")``."""
        with pytest.raises(ValidationError):
            HeuresParSemaine(
                heures_normales=Decimal("168.01"),
                heures_supplementaires=Decimal("0.00"),
            )

    def test_heures_supplementaires_negatives_sont_rejetees(self) -> None:
        with pytest.raises(ValidationError):
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("-0.01"),
            )

    def test_heures_supplementaires_au_dela_de_168_sont_rejetees(self) -> None:
        with pytest.raises(ValidationError):
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("168.01"),
            )

    def test_champ_inconnu_est_rejete(self) -> None:
        """``extra="forbid"`` sur ``HeuresParSemaine``."""
        with pytest.raises(ValidationError):
            HeuresParSemaine(
                heures_normales=Decimal("40.00"),
                heures_supplementaires=Decimal("0.00"),
                heures_pause=Decimal("1"),  # type: ignore[call-arg]
            )

    def test_immutabilite(self) -> None:
        """``frozen=True`` sur ``HeuresParSemaine`` (Property 1 exemple)."""
        hps = HeuresParSemaine(
            heures_normales=Decimal("40.00"),
            heures_supplementaires=Decimal("0.00"),
        )
        with pytest.raises(ValidationError):
            hps.heures_normales = Decimal("50.00")  # type: ignore[misc]
