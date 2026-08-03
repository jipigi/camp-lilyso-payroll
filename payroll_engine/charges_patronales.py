"""Calcul des charges patronales — FSS, CNESST, CNT — et assemblage employeur.

Spec de référence : ``charges-patronales`` — tâche 11.1 (étape 5 du plan
d'implémentation).
Design de référence : ``design.md`` §Components §1 (« Signatures exactes »),
§2 (« `calcul_fss` »), §3 (« `calcul_cnesst` »), §4 (« `calcul_cnt` »),
§5 (« `assembler_cotisations_employeur` »), §6 (« Helper d'arrondissement »),
§7 (« Ordre d'exécution ») et §Error Handling.

Ce module expose trois fonctions pures de calcul et une fonction d'assemblage :

- :func:`calcul_fss` — cotisation au Fonds des services de santé
  (Revenu Québec, TP-1015.F 2026, section 5). Patron proportionnel simple
  ``montant = arrondir(taux_fss × brut_total)`` — sans exemption, sans
  plafond, sans cumul YTD ; la table par masse salariale n'est jamais
  consultée (Req 2).
- :func:`calcul_cnesst` — cotisation à la Commission des normes, de
  l'équité, de la santé et de la sécurité du travail. Patron identique
  ``montant = arrondir(taux_total × brut_total)`` — aucun plafond annuel ;
  le drapeau ``en_attente_classification`` n'affecte pas le calcul de
  période (Req 3).
- :func:`calcul_cnt` — cotisation relative aux normes du travail
  (LE-39.0.2 2026, ligne 35). Patron identique
  ``montant = arrondir(taux_cnt × brut_total)`` — la ``base_admissible``
  est lue pour la trace uniquement, jamais appliquée comme plafond (Req 4).
- :func:`assembler_cotisations_employeur` — assemble
  :class:`~models.payroll_result.CotisationsEmployeur` en **invoquant**
  (sans les recalculer) les fonctions employeur RRQ/RQAP/AE de l'étape 3
  et les trois fonctions ci-dessus, puis somme les six montants (Req 6, 9).

Règles appliquées (Req 1 à 9) :

- Règle 01 (``Decimal`` obligatoire) — aucun ``float`` dans ce module ;
  le seul mécanisme d'arrondissement autorisé est ``Decimal.quantize``
  avec ``rounding=ROUND_HALF_UP`` (helper :func:`_arrondir`).
- Règle 02 (traçabilité des formules) — chaque fonction de calcul retourne
  ``tuple[Decimal, CalculationTrace]`` avec une source officielle sur la
  liste blanche : FSS → ``"TP-1015.F <année>, section 5 — FSS"``,
  CNESST → URL ``www.cnesst.gouv.qc.ca``, CNT → ``"LE-39.0.2 <année>"``.
- Règle 05 (paramètres annuels versionnés) — aucun taux, base ni masse
  n'est codé en dur : ces valeurs sont lues exclusivement depuis
  ``parametres_annee``. Seuls ``Decimal("0.01")`` (précision monétaire) et
  l'entier ``2`` (précision d'arrondissement) sont des littéraux autorisés.

Requirements couverts : 1.1 à 1.8, 2.*, 3.*, 4.*, 5.*, 6.*, 7.1, 7.2, 8.*,
9.1, 9.3, 10.*, 11.1, 11.2, 11.3.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from models.enums import Juridiction, ModeArrondissement
from models.exceptions import MissingParameterError
from models.payroll_input import PayrollInput
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
)
from models.trace import CalculationTrace
from payroll_engine.assurance_emploi import calcul_ae_employeur
from payroll_engine.parameters_loader import ParametresAnnee
from payroll_engine.rqap import calcul_rqap_employeur
from payroll_engine.rrq import calcul_rrq_employeur

# ---------------------------------------------------------------------------
# Helper d'arrondissement (Req 8, design §Architecture / §Components §6)
# ---------------------------------------------------------------------------
#
# Dupliqué à l'identique dans `rrq.py`/`rqap.py`/`assurance_emploi.py`/
# `impot_qc.py`/`impot_federal.py` — décision de duplication contrôlée
# (design §Architecture « Helper d'arrondissement — duplication
# contrôlée »), pas un oubli de factorisation.

_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")


def _arrondir(montant: Decimal) -> Decimal:
    """Arrondit `montant` à 2 décimales selon ROUND_HALF_UP (Req 8, règle 01).

    Seul mécanisme d'arrondissement autorisé dans ce module : `round()`,
    `math.floor()`, `math.ceil()` et `math.trunc()` sont proscrits — voir
    le test de garde `tests/test_guards.py::TestChargesPatronalesNoFloat`.
    Appelé **exactement une fois** par montant théorique dans chacune des
    trois fonctions de calcul, jamais sur `gains.brut_total` (déjà arrondi)
    ni sur le total de l'assemblage.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# calcul_fss (Req 2, Req 5, Req 8, design §Components §2)
# ---------------------------------------------------------------------------


def calcul_fss(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation FSS de période et sa trace (Req 2, règles 01, 02, 05).

    Algorithme (design §Components §2) — patron proportionnel simple :

    1. Contrôle de section (`fss is None` → `MissingParameterError`, Req 1.8).
    2. `salaire_assujetti = gains.brut_total` (Req 1.5).
    3. `taux_fss = parametres_annee.fss.taux_camp_lilyso_2026` (Req 2.3) ;
       `masse_salariale` lue à titre documentaire pour la trace (Req 5.2).
    4. `montant = arrondir(taux_fss × salaire_assujetti)` (Req 2.1, 2.2).

    Aucune exemption, aucun plafond, aucun cumul. La
    `table_taux_par_masse_salariale` n'est **jamais** consultée (Req 2.7).
    Lorsque `salaire_assujetti == Decimal("0.00")`, `montant ==
    Decimal("0.00")` sans branche dédiée (Req 2.5).

    Fonction pure (Req 1.3, 1.6, 1.7) : ne mute aucun argument, aucune E/S.

    Exceptions :
        MissingParameterError: si la section `fss` est absente (Req 1.8) ou
            si `taux_camp_lilyso_2026` porte la sentinelle `"TO_FILL"`.
    """
    if parametres_annee.fss is None:
        raise MissingParameterError(
            "Section 'fss' absente des paramètres "
            f"({parametres_annee.annee}, {parametres_annee.juridiction}). "
            "Renseigner parameters/<AAAA>/quebec.json, section 'fss'."
        )
    fss = parametres_annee.fss

    # Étape 2 — Salaire assujetti (Req 1.5, seule source).
    salaire_assujetti = gains.brut_total

    # Étape 3 — Paramètres (taux consommé, masse documentaire — Req 5.2).
    taux_fss = fss.taux_camp_lilyso_2026
    masse_salariale = fss.masse_salariale_utilisee_webras_2026

    # Étape 4 — Montant de période, arrondi une seule fois (Req 2.1, 2.2, 8.1).
    montant = _arrondir(taux_fss * salaire_assujetti)

    # Construction de la CalculationTrace (Req 5, design §Components §2).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 5 — FSS",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="5 — Fonds des services de santé (FSS)",
        parametres_utilises={
            "taux_fss": taux_fss,
        },
        entrees={
            "salaire_assujetti": salaire_assujetti,
            "masse_salariale_annuelle": masse_salariale,
        },
        sous_totaux={
            "cotisation_brute": montant,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=montant,
    )

    return (montant, trace)


# ---------------------------------------------------------------------------
# calcul_cnesst (Req 3, Req 5, Req 8, design §Components §3)
# ---------------------------------------------------------------------------


def calcul_cnesst(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation CNESST de période et sa trace (Req 3, règles 01, 02, 05).

    Algorithme (design §Components §3) — patron proportionnel simple :

    1. Contrôle de section (`cnesst is None` → `MissingParameterError`, Req 1.8).
    2. `salaire_assujetti = gains.brut_total` (Req 1.5).
    3. `taux_total = parametres_annee.cnesst.taux_total` (Req 3.3) ;
       `unite` portée dans la trace (`section`, Req 5.3).
    4. `montant = arrondir(taux_total × salaire_assujetti)` (Req 3.1, 3.2).

    Aucun plafond annuel de salaire assujetti (Req 3.7). Le drapeau
    `en_attente_classification` **n'est pas lu ici** (il ne change pas le
    calcul de période, Req 3.8) — il est lu par l'assemblage. Les sous-taux
    `taux_unite`/`taux_cni` ne sont **pas** consommés par le calcul.
    Lorsque `salaire_assujetti == Decimal("0.00")`, `montant ==
    Decimal("0.00")` (Req 3.5).

    Fonction pure (Req 1.3, 1.6, 1.7).

    Exceptions :
        MissingParameterError: si la section `cnesst` est absente (Req 1.8)
            ou si `taux_total` porte la sentinelle `"TO_FILL"`.
    """
    if parametres_annee.cnesst is None:
        raise MissingParameterError(
            "Section 'cnesst' absente des paramètres "
            f"({parametres_annee.annee}, {parametres_annee.juridiction}). "
            "Renseigner parameters/<AAAA>/quebec.json, section 'cnesst'."
        )
    cnesst = parametres_annee.cnesst

    # Étape 2 — Salaire assujetti (Req 1.5, seule source).
    salaire_assujetti = gains.brut_total

    # Étape 3 — Taux total (consommé) et unité (trace, Req 5.3).
    taux_total = cnesst.taux_total
    unite = cnesst.unite

    # Étape 4 — Montant de période, arrondi une seule fois (Req 3.1, 3.2, 8.1).
    montant = _arrondir(taux_total * salaire_assujetti)

    # Construction de la CalculationTrace (Req 5, design §Components §3).
    # La source est une URL officielle concrète sur `www.cnesst.gouv.qc.ca`
    # (page des taux de prime / tarification), admise par la liste blanche
    # `.gouv.qc.ca`. L'unité est portée dans `section` (le contrat
    # `parametres_utilises` est typé `dict[str, Decimal]` et ne peut pas
    # contenir la chaîne d'unité).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=(
            "https://www.cnesst.gouv.qc.ca/fr/demarches-formulaires/"
            "employeurs/assurance-sante-securite-travail/tarification/"
            "taux-prime"
        ),
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section=f"Classification CNESST — unité {unite}",
        parametres_utilises={
            "taux_total_cnesst": taux_total,
        },
        entrees={
            "salaire_assujetti": salaire_assujetti,
        },
        sous_totaux={
            "cotisation_brute": montant,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=montant,
    )

    return (montant, trace)


# ---------------------------------------------------------------------------
# calcul_cnt (Req 4, Req 5, Req 8, design §Components §4)
# ---------------------------------------------------------------------------


def calcul_cnt(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation CNT de période et sa trace (Req 4, règles 01, 02, 05).

    Algorithme (design §Components §4) — patron proportionnel simple :

    1. Contrôle de section (`cnt is None` → `MissingParameterError`, Req 1.8).
    2. `salaire_assujetti = gains.brut_total` (Req 1.5).
    3. `taux_cnt = parametres_annee.cnt.taux` (Req 4.3) ; `base_admissible`
       lue **uniquement** pour la trace (Req 4.7, 5.4).
    4. `montant = arrondir(taux_cnt × salaire_assujetti)` (Req 4.1, 4.2).

    Aucun plafond appliqué : `base_admissible` n'est jamais comparée au
    salaire (Req 4.7). Lorsque `salaire_assujetti == Decimal("0.00")`,
    `montant == Decimal("0.00")` (Req 4.5).

    Fonction pure (Req 1.3, 1.6, 1.7).

    Exceptions :
        MissingParameterError: si la section `cnt` est absente (Req 1.8) ou
            si `taux` ou `base_admissible` portent la sentinelle `"TO_FILL"`.
    """
    if parametres_annee.cnt is None:
        raise MissingParameterError(
            "Section 'cnt' absente des paramètres "
            f"({parametres_annee.annee}, {parametres_annee.juridiction}). "
            "Renseigner parameters/<AAAA>/quebec.json, section 'cnt'."
        )
    cnt = parametres_annee.cnt

    # Étape 2 — Salaire assujetti (Req 1.5, seule source).
    salaire_assujetti = gains.brut_total

    # Étape 3 — Taux (consommé) et base admissible (trace documentaire,
    # Req 4.7, 5.4 — jamais appliquée comme plafond).
    taux_cnt = cnt.taux
    base_admissible = cnt.base_admissible

    # Étape 4 — Montant de période, arrondi une seule fois (Req 4.1, 4.2, 8.1).
    montant = _arrondir(taux_cnt * salaire_assujetti)

    # Construction de la CalculationTrace (Req 5, design §Components §4).
    # Source `LE-39.0.2 <année>` — motif ajouté à la liste blanche (tâche 8.1).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"LE-39.0.2 {annee_fiscale}",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="Normes du travail — cotisation (ligne 35)",
        parametres_utilises={
            "taux_cnt": taux_cnt,
            "base_admissible": base_admissible,
        },
        entrees={
            "salaire_assujetti": salaire_assujetti,
        },
        sous_totaux={
            "cotisation_brute": montant,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=montant,
    )

    return (montant, trace)


# ---------------------------------------------------------------------------
# assembler_cotisations_employeur (Req 6, Req 9, design §Components §5)
# ---------------------------------------------------------------------------


def assembler_cotisations_employeur(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> CotisationsEmployeur:
    """Assemble `CotisationsEmployeur` par invocation, jamais par recalcul (Req 6, 9).

    Invocation stricte (design §Components §5, Req 6.1, 6.2) — dans l'ordre
    RRQ_er → RQAP_er → AE_er → FSS → CNESST → CNT :

    1. `calcul_rrq_employeur`, `calcul_rqap_employeur`, `calcul_ae_employeur`
       (étape 3) fournissent les trois cotisations sociales employeur ;
    2. `calcul_fss`, `calcul_cnesst`, `calcul_cnt` (cette spec) fournissent
       les trois charges patronales ;
    3. le drapeau `cnesst.en_attente_classification` est **lu** (jamais
       recalculé) et reporté dans `cnesst_en_attente_classification`
       (Req 6.4, 9.3) ;
    4. `total = somme des six montants` — chaque montant étant déjà arrondi
       à 2 décimales, la somme est exacte au cent, aucun ré-arrondissement
       (Req 6.5, 9.1) ;
    5. construction de `CotisationsEmployeur` (six `MontantAvecTrace` + le
       drapeau + le total).

    Fonction pure (Req 6.6) : ne mute aucun argument. `MissingParameterError`
    levée par une fonction invoquée est propagée sans interception (Req 6.7).
    """
    # --- Trois cotisations sociales employeur (étape 3, invoquées telles quelles).
    rrq_er_montant, rrq_er_trace = calcul_rrq_employeur(
        payroll_input, gains, parametres_annee
    )
    rqap_er_montant, rqap_er_trace = calcul_rqap_employeur(
        payroll_input, gains, parametres_annee
    )
    ae_er_montant, ae_er_trace = calcul_ae_employeur(
        payroll_input, gains, parametres_annee
    )

    # --- Trois charges patronales (cette spec).
    fss_montant, fss_trace = calcul_fss(payroll_input, gains, parametres_annee)
    cnesst_montant, cnesst_trace = calcul_cnesst(
        payroll_input, gains, parametres_annee
    )
    cnt_montant, cnt_trace = calcul_cnt(payroll_input, gains, parametres_annee)

    # --- Drapeau CNESST (lu, jamais recalculé — Req 6.4, 9.3).
    en_attente = parametres_annee.cnesst.en_attente_classification

    # --- Somme exacte au cent (chaque montant déjà arrondi — Req 6.5, 9.1).
    total = (
        rrq_er_montant
        + rqap_er_montant
        + ae_er_montant
        + fss_montant
        + cnesst_montant
        + cnt_montant
    )

    return CotisationsEmployeur(
        rrq_employeur=MontantAvecTrace(montant=rrq_er_montant, trace=rrq_er_trace),
        rqap_employeur=MontantAvecTrace(montant=rqap_er_montant, trace=rqap_er_trace),
        ae_employeur=MontantAvecTrace(montant=ae_er_montant, trace=ae_er_trace),
        fss=MontantAvecTrace(montant=fss_montant, trace=fss_trace),
        cnesst=MontantAvecTrace(montant=cnesst_montant, trace=cnesst_trace),
        cnesst_en_attente_classification=en_attente,
        cnt=MontantAvecTrace(montant=cnt_montant, trace=cnt_trace),
        total_cotisations_employeur=total,
    )
