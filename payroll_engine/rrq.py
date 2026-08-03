"""Calcul de la cotisation RRQ — employé et employeur.

Spec de référence : ``cotisations-sociales-qc`` — tâche 9.1.
Design de référence : ``design.md`` §Components §1 (« Signatures
exactes »), §2 (« `calcul_rrq_employe` »), §3 (« `calcul_rrq_employeur` »),
§8 (« Helper d'arrondissement »).

Ce module expose deux fonctions publiques et pures :

- :func:`calcul_rrq_employe` — cotisation au Régime de rentes du Québec
  (RRQ) retenue à l'employé, après exemption par période et
  plafonnement par le cumul YTD.
- :func:`calcul_rrq_employeur` — cotisation RRQ employeur, strictement
  égale à la cotisation employé (délégation structurelle, TP-1015.F ne
  définissant aucune formule employeur distincte).

Règles appliquées (Req 1, 2, 3) :

- Règle 01 (``Decimal`` obligatoire) — aucun ``float`` dans ce module ;
  le seul mécanisme d'arrondissement autorisé est ``Decimal.quantize``
  avec ``rounding=ROUND_HALF_UP``.
- Règle 02 (traçabilité des formules) — chaque fonction retourne
  ``tuple[Decimal, CalculationTrace]``, la trace référençant le
  TP-1015.F de l'année fiscale de la paie.
- Règle 05 (paramètres annuels versionnés) — aucun taux, exemption ni
  plafond RRQ n'est codé en dur : ces valeurs sont lues exclusivement
  depuis ``parametres_annee.rrq``.

Requirements couverts : 1.1, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 2.1,
2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 10.1, 10.3, 10.4,
11.1, 11.2, 11.3, 11.6, 11.7, 11.8, 12.1, 12.4, 12.5.
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
# Dupliqué à l'identique dans `rqap.py` et `assurance_emploi.py` — décision
# de duplication contrôlée (design §Architecture « Helper d'arrondissement
# partagé »), pas un oubli de factorisation.

_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")


def _arrondir(montant: Decimal) -> Decimal:
    """Arrondit `montant` à 2 décimales selon ROUND_HALF_UP (Req 10.1, règle 01).

    Seul mécanisme d'arrondissement autorisé dans ce module : `round()`,
    `math.floor()`, `math.ceil()` et `math.trunc()` sont proscrits — voir
    le test de garde `tests/test_guards.py::TestRrqNoFloat`.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# calcul_rrq_employe (Req 2, design §Components §2)
# ---------------------------------------------------------------------------


def calcul_rrq_employe(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation RRQ employé et sa trace (Req 2, règles 01, 02, 05).

    Algorithme (design §Components §2) :

    1. `salaire_admissible = gains.brut_total` (Req 1.6 — aucune autre
       source).
    2. `exemption_periode` lue depuis
       `parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026`
       (jamais recalculée par division de l'exemption générale annuelle).
    3. `assiette_cotisable = max(0, salaire_admissible - exemption_periode)`
       (Req 2.1).
    4. `montant_periode = arrondir(taux_cotisation_totale_employe *
       assiette_cotisable)` (Req 2.2, 10.1).
    5. `marge_disponible = max(0, plafond_annuel - cumul_ytd)` (Req 2.3).
    6. `cotisation_effective = min(montant_periode, marge_disponible)`
       (Req 2.4).

    Fonction pure : deux appels avec les mêmes arguments retournent deux
    tuples égaux au sens `==` (Req 1.4). Ne mute aucun argument (Req 1.8).

    Exceptions :
        MissingParameterError: si un des trois paramètres RRQ consommés
            (`taux_cotisation_totale_employe`,
            `exemption_par_periode_aux_deux_semaines_2026`,
            `cotisation_max_annuelle_employe`) porte la sentinelle
            `"TO_FILL"` (Req 1.9, 12.5).
    """
    # Étape 1 — Salaire admissible (Req 1.6, 2.1).
    salaire_admissible = gains.brut_total

    # Étape 2 — Exemption par période (Req 2.1, règle 05). Lue directement
    # depuis les paramètres, jamais recalculée à partir de l'exemption
    # générale annuelle (voir Glossary « Exemption_Par_Periode_RRQ »).
    exemption_periode = (
        parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
    )

    # Étape 3 — Assiette cotisable (Req 2.1).
    assiette_cotisable = max(Decimal("0.00"), salaire_admissible - exemption_periode)

    # Étape 4 — Montant théorique de période, arrondi une seule fois avant
    # comparaison avec la marge disponible (Req 2.2, 10.1, 10.3).
    taux_employe = parametres_annee.rrq.taux_cotisation_totale_employe
    montant_periode = _arrondir(taux_employe * assiette_cotisable)

    # Étape 5 — Marge disponible face au plafond annuel (Req 2.3).
    plafond_annuel = parametres_annee.rrq.cotisation_max_annuelle_employe
    cumul_ytd = payroll_input.cumuls_debut.rrq_employe
    marge_disponible = max(Decimal("0.00"), plafond_annuel - cumul_ytd)

    # Étape 6 — Cotisation effective (Req 2.4).
    cotisation_effective = min(montant_periode, marge_disponible)

    # Construction de la CalculationTrace (Req 11, design §Components §2).
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 3.2 — RRQ",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="3.2 — RRQ",
        parametres_utilises={
            "taux_cotisation_totale_employe": taux_employe,
            "exemption_generale_annuelle": parametres_annee.rrq.exemption_generale_annuelle,
        },
        entrees={
            "salaire_periode": salaire_admissible,
            "nb_periodes_annuelles": Decimal(
                str(payroll_input.pay_period.nb_periodes_annuelles)
            ),
            "cumul_ytd": cumul_ytd,
        },
        sous_totaux={
            "exemption_periode": exemption_periode,
            "assiette_cotisable": assiette_cotisable,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=cotisation_effective,
    )

    return (cotisation_effective, trace)


# ---------------------------------------------------------------------------
# calcul_rrq_employeur (Req 3, design §Components §3)
# ---------------------------------------------------------------------------


def calcul_rrq_employeur(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la cotisation RRQ employeur et sa trace (Req 3, règles 01, 02, 05).

    Délégation structurelle stricte (design §Components §3) : le montant
    employeur est **invoqué** depuis `calcul_rrq_employe`, jamais
    recalculé indépendamment — aucun plafond, cumul ni taux distinct
    n'existe côté employeur pour le RRQ (`RRQParametres` ne définit
    aucun champ `cotisation_max_annuelle_employeur`). Cette invocation
    interne garantit que `rrq_employeur == rrq_employe` est une
    propriété structurelle du code, pas seulement une propriété testée
    (Req 3.1, 3.2).
    """
    cotisation_employe_effective, _trace_employe = calcul_rrq_employe(
        payroll_input, gains, parametres_annee
    )
    cotisation_effective = cotisation_employe_effective

    # Reconstruction des sous-totaux nécessaires à la trace employeur
    # (mêmes valeurs que côté employé, design §Components §3 : « Le champ
    # `entrees` inclut en outre `assiette_cotisable` [...] »).
    salaire_admissible = gains.brut_total
    exemption_periode = (
        parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026
    )
    assiette_cotisable = max(Decimal("0.00"), salaire_admissible - exemption_periode)
    taux_employeur = parametres_annee.rrq.taux_cotisation_totale_employeur
    cumul_ytd = payroll_input.cumuls_debut.rrq_employe

    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 3.2 — RRQ",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="3.2 — RRQ employeur",
        parametres_utilises={
            "taux_cotisation_totale_employeur": taux_employeur,
            "exemption_generale_annuelle": parametres_annee.rrq.exemption_generale_annuelle,
        },
        entrees={
            "salaire_periode": salaire_admissible,
            "nb_periodes_annuelles": Decimal(
                str(payroll_input.pay_period.nb_periodes_annuelles)
            ),
            "cumul_ytd": cumul_ytd,
        },
        sous_totaux={
            "exemption_periode": exemption_periode,
            "assiette_cotisable": assiette_cotisable,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=cotisation_effective,
    )

    return (cotisation_effective, trace)
