"""Calcul de la cotisation AE (assurance-emploi) — employé et employeur.

Spec de référence : ``cotisations-sociales-qc`` — tâche 11.1.
Design de référence : ``design.md`` §Components §1 (« Signatures
exactes »), §6 (« `calcul_ae_employe` »), §7 (« `calcul_ae_employeur` »),
§8 (« Helper d'arrondissement »).

Ce module expose deux fonctions publiques et pures :

- :func:`calcul_ae_employe` — cotisation d'assurance-emploi (taux
  Québec) retenue à l'employé, taux appliqué directement au salaire
  admissible (aucune exemption soustraite), plafonnée par le cumul YTD.
- :func:`calcul_ae_employeur` — cotisation AE employeur, **dérivée** du
  montant AE employé effectivement retenu (post-plafonnement) via le
  multiplicateur employeur (1,4) — le T4127 ne définit aucun taux
  employeur AE indépendant.

Règles appliquées (Req 1, 6, 7) :

- Règle 01 (``Decimal`` obligatoire) — aucun ``float`` dans ce module ;
  le seul mécanisme d'arrondissement autorisé est ``Decimal.quantize``
  avec ``rounding=ROUND_HALF_UP``.
- Règle 02 (traçabilité des formules) — chaque fonction retourne
  ``tuple[Decimal, CalculationTrace]``, la trace référençant le T4127
  de l'année fiscale de la paie.
- Règle 05 (paramètres annuels versionnés) — aucun taux, multiplicateur
  ni plafond AE n'est codé en dur : ces valeurs sont lues exclusivement
  depuis ``parametres_annee.assurance_emploi``.

Requirements couverts : 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 6.1,
6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 10.1, 10.2, 10.3, 10.4,
11.1, 11.2, 11.5, 11.6, 11.7, 11.8, 12.3, 12.4, 12.5.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from models.enums import Juridiction, ModeArrondissement
from models.payroll_input import PayrollInput
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import ParametresAnnee

# ---------------------------------------------------------------------------
# Helper d'arrondissement (Req 10.1, design §Components §8)
# ---------------------------------------------------------------------------
#
# Dupliqué à l'identique dans `rrq.py` et `rqap.py` — décision de
# duplication contrôlée (design §Architecture « Helper d'arrondissement
# partagé »), pas un oubli de factorisation.

_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")


def _arrondir(montant: Decimal) -> Decimal:
    """Arrondit `montant` à 2 décimales selon ROUND_HALF_UP (Req 10.1, règle 01).

    Seul mécanisme d'arrondissement autorisé dans ce module : `round()`,
    `math.floor()`, `math.ceil()` et `math.trunc()` sont proscrits — voir
    le test de garde `tests/test_guards.py::TestAssuranceEmploiNoFloat`.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# calcul_ae_employe (Req 6, design §Components §6)
# ---------------------------------------------------------------------------


def calcul_ae_employe(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation AE employé et sa trace (Req 6, règles 01, 02, 05).

    Algorithme (design §Components §6) :

    1. `salaire_admissible = gains.brut_total` (Req 1.6 — aucune autre
       source).
    2. `montant_periode = arrondir(taux_employe_quebec *
       salaire_admissible)` (Req 6.1, 10.1). Aucune exemption n'est
       soustraite du salaire admissible avant application du taux.
    3. `marge_disponible = max(0, plafond_annuel - cumul_ytd)` (Req 6.2).
    4. `cotisation_effective = min(montant_periode, marge_disponible)`
       (Req 6.3).

    Fonction pure : deux appels avec les mêmes arguments retournent deux
    tuples égaux au sens `==` (Req 1.4). Ne mute aucun argument (Req 1.8).

    Exceptions :
        MissingParameterError: si `taux_employe_quebec` ou
            `cotisation_max_employe` de
            `parametres_annee.assurance_emploi` porte la sentinelle
            `"TO_FILL"` (Req 1.9, 12.5).
    """
    # Étape 1 — Salaire admissible (Req 1.6, 6.1).
    salaire_admissible = gains.brut_total

    # Étape 2 — Montant théorique de période, arrondi une seule fois avant
    # comparaison avec la marge disponible (Req 6.1, 10.1, 10.3). Aucune
    # exemption soustraite (comme le RQAP, contrairement au RRQ).
    taux_employe_quebec = parametres_annee.assurance_emploi.taux_employe_quebec
    montant_periode = _arrondir(taux_employe_quebec * salaire_admissible)

    # Étape 3 — Marge disponible face au plafond annuel employé (Req 6.2).
    plafond_annuel = parametres_annee.assurance_emploi.cotisation_max_employe
    cumul_ytd = payroll_input.cumuls_debut.ae_employe
    marge_disponible = max(Decimal("0.00"), plafond_annuel - cumul_ytd)

    # Étape 4 — Cotisation effective (Req 6.3).
    cotisation_effective = min(montant_periode, marge_disponible)

    # Construction de la CalculationTrace (Req 11, design §Components §6).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"T4127 {annee_fiscale}, section 4 — Assurance-emploi",
        annee=annee_fiscale,
        juridiction=Juridiction.CANADA,
        section="4 — AE employé (taux Québec)",
        parametres_utilises={
            "taux_employe_quebec": taux_employe_quebec,
        },
        entrees={
            "salaire_periode": salaire_admissible,
        },
        sous_totaux={
            "cotisation_brute": montant_periode,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=cotisation_effective,
    )

    return (cotisation_effective, trace)


# ---------------------------------------------------------------------------
# calcul_ae_employeur (Req 7, design §Components §7)
# ---------------------------------------------------------------------------


def calcul_ae_employeur(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation AE employeur et sa trace (Req 7, règles 01, 02, 05).

    **Dérivation depuis le montant employé effectif** (design
    §Components §7, Req 7.1, 7.2) — à l'opposé exact de la décision
    retenue pour `calcul_rqap_employeur` (calcul indépendant sur le
    brut, voir `rqap.py`) : le T4127 ne définit aucun taux employeur AE
    indépendant, seulement un multiplicateur (`multiplicateur_employeur`,
    1,4) appliqué à la retenue employé *effectivement* retenue (c'est-à-
    dire **après** plafonnement employé, Requirement 6) — jamais un
    calcul indépendant `taux_employe_quebec * multiplicateur_employeur *
    brut_total`. `calcul_ae_employeur` **invoque** `calcul_ae_employe`
    en interne — même stratégie de délégation structurelle que
    `calcul_rrq_employeur` (`rrq.py`), mais appliquée à un multiplicateur
    plutôt qu'à une simple égalité.

    Exceptions :
        MissingParameterError: si `taux_employe_quebec` ou
            `cotisation_max_employe` (propagés par l'appel interne à
            `calcul_ae_employe`), ou si `multiplicateur_employeur` ou
            `cotisation_max_employeur` de
            `parametres_annee.assurance_emploi` portent la sentinelle
            `"TO_FILL"` (Req 1.9, 12.5).
    """
    # Étape 1 — Cotisation AE employé effective (post-plafonnement),
    # obtenue par appel interne (Req 7.1, 7.2) — NE JAMAIS recalculer
    # indépendamment `taux_employe_quebec * multiplicateur * brut_total`.
    cotisation_ae_employe_effective, _trace_employe = calcul_ae_employe(
        payroll_input, gains, parametres_annee
    )

    # Étape 2 — Montant théorique de période, dérivé du montant employé
    # effectif via le multiplicateur employeur (Req 7.1, 10.2).
    multiplicateur = parametres_annee.assurance_emploi.multiplicateur_employeur
    produit_avant_arrondi = multiplicateur * cotisation_ae_employe_effective
    montant_periode = _arrondir(produit_avant_arrondi)

    # Étape 3 — Marge disponible face au plafond annuel employeur, en
    # défense en profondeur (Req 7.3).
    plafond_annuel = parametres_annee.assurance_emploi.cotisation_max_employeur
    cumul_ytd = payroll_input.cumuls_debut.ae_employeur
    marge_disponible = max(Decimal("0.00"), plafond_annuel - cumul_ytd)

    # Étape 4 — Cotisation effective (Req 7.3).
    cotisation_effective = min(montant_periode, marge_disponible)

    # Construction de la CalculationTrace (Req 11, design §Components §7).
    # `sous_totaux["cotisation_employeur"]` porte le produit AVANT
    # arrondissement final (ex. "27.594"), tandis que `resultat` porte la
    # valeur arrondie finale ("27.59") — reproduction fidèle de la
    # fixture QC001, distincte du patron `rrq.py`/`rqap.py` où
    # `sous_totaux` porte des valeurs déjà arrondies.
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"T4127 {annee_fiscale}, section 4 — Assurance-emploi",
        annee=annee_fiscale,
        juridiction=Juridiction.CANADA,
        section="4 — AE employeur (multiplicateur 1.4)",
        parametres_utilises={
            "multiplicateur_employeur": multiplicateur,
        },
        entrees={
            "ae_employe": cotisation_ae_employe_effective,
        },
        sous_totaux={
            "cotisation_employeur": produit_avant_arrondi,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=cotisation_effective,
    )

    return (cotisation_effective, trace)
