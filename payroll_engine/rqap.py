"""Calcul de la cotisation RQAP — employé et employeur.

Spec de référence : ``cotisations-sociales-qc`` — tâche 10.1.
Design de référence : ``design.md`` §Components §1 (« Signatures
exactes »), §4 (« `calcul_rqap_employe` »), §5
(« `calcul_rqap_employeur` »), §8 (« Helper d'arrondissement »).

Ce module expose deux fonctions publiques et pures :

- :func:`calcul_rqap_employe` — cotisation au Régime québécois
  d'assurance parentale (RQAP) retenue à l'employé, taux appliqué
  directement au salaire admissible (aucune exemption soustraite),
  plafonnée par le cumul YTD.
- :func:`calcul_rqap_employeur` — cotisation RQAP employeur, calcul
  **indépendant** avec son propre taux et son propre plafond, jamais
  dérivé du montant employé déjà arrondi.

Règles appliquées (Req 1, 4, 5) :

- Règle 01 (``Decimal`` obligatoire) — aucun ``float`` dans ce module ;
  le seul mécanisme d'arrondissement autorisé est ``Decimal.quantize``
  avec ``rounding=ROUND_HALF_UP``.
- Règle 02 (traçabilité des formules) — chaque fonction retourne
  ``tuple[Decimal, CalculationTrace]``, la trace référençant le
  TP-1015.F de l'année fiscale de la paie.
- Règle 05 (paramètres annuels versionnés) — aucun taux ni plafond
  RQAP n'est codé en dur : ces valeurs sont lues exclusivement depuis
  ``parametres_annee.rqap``.

Requirements couverts : 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 4.1,
4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 10.1,
10.3, 10.4, 11.1, 11.2, 11.4, 11.6, 11.7, 11.8, 12.2, 12.4, 12.5.
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
# Dupliqué à l'identique dans `rrq.py` et `assurance_emploi.py` — décision
# de duplication contrôlée (design §Architecture « Helper d'arrondissement
# partagé »), pas un oubli de factorisation.

_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")


def _arrondir(montant: Decimal) -> Decimal:
    """Arrondit `montant` à 2 décimales selon ROUND_HALF_UP (Req 10.1, règle 01).

    Seul mécanisme d'arrondissement autorisé dans ce module : `round()`,
    `math.floor()`, `math.ceil()` et `math.trunc()` sont proscrits — voir
    le test de garde `tests/test_guards.py::TestRqapNoFloat`.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# calcul_rqap_employe (Req 4, design §Components §4)
# ---------------------------------------------------------------------------


def calcul_rqap_employe(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation RQAP employé et sa trace (Req 4, règles 01, 02, 05).

    Algorithme (design §Components §4) :

    1. `salaire_admissible = gains.brut_total` (Req 1.6 — aucune autre
       source).
    2. `montant_periode = arrondir(taux_employe * salaire_admissible)`
       (Req 4.1, 10.1). Contrairement au RRQ, **aucune** exemption n'est
       soustraite du salaire admissible avant application du taux.
    3. `marge_disponible = max(0, plafond_annuel - cumul_ytd)` (Req 4.2).
    4. `cotisation_effective = min(montant_periode, marge_disponible)`
       (Req 4.3).

    Fonction pure : deux appels avec les mêmes arguments retournent deux
    tuples égaux au sens `==` (Req 1.4). Ne mute aucun argument (Req 1.8).

    Exceptions :
        MissingParameterError: si `taux_employe` ou
            `cotisation_max_employe` de `parametres_annee.rqap` porte la
            sentinelle `"TO_FILL"` (Req 1.9, 12.5).
    """
    # Étape 1 — Salaire admissible (Req 1.6, 4.1).
    salaire_admissible = gains.brut_total

    # Étape 2 — Montant théorique de période, arrondi une seule fois avant
    # comparaison avec la marge disponible (Req 4.1, 10.1, 10.3). Aucune
    # exemption soustraite (contrairement au RRQ, design §Components §4).
    taux_employe = parametres_annee.rqap.taux_employe
    montant_periode = _arrondir(taux_employe * salaire_admissible)

    # Étape 3 — Marge disponible face au plafond annuel (Req 4.2).
    plafond_annuel = parametres_annee.rqap.cotisation_max_employe
    cumul_ytd = payroll_input.cumuls_debut.rqap_employe
    marge_disponible = max(Decimal("0.00"), plafond_annuel - cumul_ytd)

    # Étape 4 — Cotisation effective (Req 4.3).
    cotisation_effective = min(montant_periode, marge_disponible)

    # Construction de la CalculationTrace (Req 11, design §Components §4).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 3.3 — RQAP",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="3.3 — RQAP employé",
        parametres_utilises={
            "taux_employe": taux_employe,
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
# calcul_rqap_employeur (Req 5, design §Components §5)
# ---------------------------------------------------------------------------


def calcul_rqap_employeur(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation RQAP employeur et sa trace (Req 5, règles 01, 02, 05).

    **Calcul indépendant** (design §Components §5, Req 5.1, 5.2) : le
    montant théorique de période employeur est calculé à partir de
    `gains.brut_total` avec son propre taux
    (`parametres_annee.rqap.taux_employeur`) et son propre plafond
    (`parametres_annee.rqap.cotisation_max_employeur`) — jamais dérivé
    du montant retourné par `calcul_rqap_employe` (qui a déjà été
    arrondi).

    Point de vigilance central de cette spec (anomalie QC004, design
    §Components §5) : `montant_periode` se calcule à partir de
    `gains.brut_total` (le salaire admissible brut), **jamais** à partir
    de la cotisation RQAP employé déjà arrondie. C'est cette
    indépendance de calcul qui produit `Decimal("1.77")` pour QC004
    (`294,84 × 0,602 % = 1,7749` → `1,77`), et non `Decimal("1.78")`
    (qui aurait résulté de la dérivation erronée
    `1,27 × 1,4 = 1,778` → `1,78`, méthode que cette spec rejette
    explicitement — voir Requirement 5.2 et la décision de résolution
    de l'anomalie dans l'Introduction des requirements). NE JAMAIS
    remplacer le calcul ci-dessous par un appel à `calcul_rqap_employe`
    suivi d'une multiplication par un multiplicateur employeur.

    Exceptions :
        MissingParameterError: si `taux_employeur` ou
            `cotisation_max_employeur` de `parametres_annee.rqap` porte
            la sentinelle `"TO_FILL"` (Req 1.9, 12.5).
    """
    # Étape 1 — Salaire admissible (Req 1.6, 5.1) — même source brute que
    # `calcul_rqap_employe`, jamais une valeur dérivée de la cotisation
    # employé.
    salaire_admissible = gains.brut_total

    # Étape 2 — Montant théorique de période, calculé INDÉPENDAMMENT à
    # partir du brut (Req 5.1, 5.2, 10.1, 10.3). Voir le point de
    # vigilance QC004 dans la docstring ci-dessus : ne jamais dériver ce
    # montant de `calcul_rqap_employe(...)[0]`.
    taux_employeur = parametres_annee.rqap.taux_employeur
    montant_periode = _arrondir(taux_employeur * salaire_admissible)

    # Étape 3 — Marge disponible face au plafond annuel employeur, distinct
    # du plafond employé (Req 5.3).
    plafond_annuel = parametres_annee.rqap.cotisation_max_employeur
    cumul_ytd = payroll_input.cumuls_debut.rqap_employeur
    marge_disponible = max(Decimal("0.00"), plafond_annuel - cumul_ytd)

    # Étape 4 — Cotisation effective (Req 5.4).
    cotisation_effective = min(montant_periode, marge_disponible)

    # Construction de la CalculationTrace (Req 11, design §Components §5).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 3.3 — RQAP",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="3.3 — RQAP employeur",
        parametres_utilises={
            "taux_employeur": taux_employeur,
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
