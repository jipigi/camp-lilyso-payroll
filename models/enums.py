"""Énumérations fermées du domaine de paie Camp LilySO.

Spec de référence : ``moteur-paie-contrats`` — tâche 2.2.
Design de référence : section « Data Models » §1 (``design.md``).

Toutes les énumérations sont des :class:`enum.StrEnum` (Python 3.11+), donc :

- immuables ;
- comparables directement à des ``str`` littérales ;
- sérialisables telles quelles en JSON (`json.dumps(Juridiction.QUEBEC) == '"quebec"'`).

Aucune valeur hors matrice Camp LilySO n'est exposée (règle 03). Une tentative
de construction avec une chaîne inconnue lève un ``ValueError`` standard, qui
sera converti en :class:`models.exceptions.UnsupportedPayrollCase` par les
modèles Pydantic qui consomment ces énumérations (voir design §2 et §6).

Requirements couverts (voir ``.kiro/specs/moteur-paie-contrats/requirements.md``) :

- Req 5.1 — ``CalculationTrace.mode_arrondissement`` ∈ :class:`ModeArrondissement`,
  ``CalculationTrace.juridiction`` ∈ :class:`Juridiction`.
- Req 6.1 — ``PayrollResult.statut`` ∈ :class:`StatutDePaie`.
- Req 9.1 — ``load_parameters(annee, juridiction)`` avec :class:`Juridiction`
  à deux valeurs exactement (``quebec`` et ``canada``).
- Req 11.1 / 11.2 — périmètre Camp LilySO : Québec uniquement,
  fréquence aux deux semaines uniquement.
"""

from __future__ import annotations

from enum import StrEnum


class Juridiction(StrEnum):
    """Juridictions fiscales supportées par le moteur.

    Deux valeurs exactement dans le périmètre courant (règle 03) :
    ``QUEBEC`` pour les retenues provinciales (TP-1015.F) et ``CANADA``
    pour les retenues fédérales (T4127).
    """

    QUEBEC = "quebec"
    CANADA = "canada"


class FrequencePaie(StrEnum):
    """Fréquences de paie supportées par le moteur.

    Le Camp LilYSO fonctionne exclusivement aux deux semaines (règle 03,
    Req 2 AC6, Req 11 AC2). Toute autre fréquence est hors matrice et lèvera
    :class:`models.exceptions.UnsupportedPayrollCase` au niveau des modèles
    consommateurs (``PayPeriod``, ``PayrollInput``).
    """

    AUX_DEUX_SEMAINES = "aux_deux_semaines"


class StatutDePaie(StrEnum):
    """États d'une paie dans le cycle immuabilité / annulation-remplacement.

    - ``BROUILLON`` : paie calculée mais non émise, encore modifiable ;
    - ``EMISE`` : paie officiellement émise, immuable ;
    - ``ANNULEE`` : paie précédemment émise, annulée sans remplacement ;
    - ``REMPLACE_PAR`` : paie précédemment émise, remplacée par une nouvelle version
      (référencée par ``PayrollResult.remplace_par_id``).
    """

    BROUILLON = "brouillon"
    EMISE = "emise"
    ANNULEE = "annulee"
    REMPLACE_PAR = "remplace_par"


class ModeArrondissement(StrEnum):
    """Modes d'arrondissement autorisés par les guides officiels.

    Les valeurs correspondent strictement aux constantes du module standard
    :mod:`decimal` (``decimal.ROUND_HALF_UP``, etc.). Elles sont donc
    utilisables directement comme argument ``rounding`` de
    :meth:`decimal.Decimal.quantize` (Req 5.1, règle 01).
    """

    ROUND_HALF_UP = "ROUND_HALF_UP"
    ROUND_HALF_EVEN = "ROUND_HALF_EVEN"
    ROUND_DOWN = "ROUND_DOWN"
    ROUND_UP = "ROUND_UP"
