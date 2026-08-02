"""Assemblage du brut d'une paie — salaire régulier, heures supp, vacances.

Spec de référence : ``gains-bruts-vacances-hs`` — tâche 5.1 (squelette).
Design de référence : ``design.md`` §Components §1 (« Signature exacte »),
§Components §2 étape 0 (« Défense en profondeur `taux_vacances` »),
§Components §4 (« Helper d'arrondissement ») et §Error Handling.

Ce module expose la fonction publique unique ``calcul_gains`` qui assemble
le gain brut d'une paie (salaire régulier, heures supplémentaires,
indemnité de vacances, jours fériés manuels) à partir d'un
``PayrollInput`` figé et des paramètres annuels versionnés, et produit un
``GainsDecomposes`` accompagné d'une ``CalculationTrace`` conforme à la
règle 02.

**État** : le module est complet — la constante d'arrondissement
``_PRECISION_MONNAIE``, le helper ``_arrondir``, la défense en
profondeur `taux_vacances` (étape 0) et le chemin nominal complet
(étapes 1 à 5, construction de la trace et du ``GainsDecomposes``, tâche
5.2) sont tous livrés.

Requirements couverts : 1.1, 1.4, 1.6, 2.1-2.5, 3.1-3.8, 4.1-4.5,
5.1-5.8, 6.1-6.5, 7.1-7.6, 8.1-8.8, 9.1, 9.2, 10.3, 10.5, 12.3, 13.1,
13.3, 14.1, 14.2.

Règles appliquées :

- Règle 01 (`Decimal` obligatoire) — aucun `float` dans ce module ; le
  seul mécanisme d'arrondissement autorisé est `Decimal.quantize` avec
  `rounding=ROUND_HALF_UP` (Req 12.3).
- Règle 02 (traçabilité des formules) — la fonction retournera, à la
  tâche 5.2, un tuple `(GainsDecomposes, CalculationTrace)` dont la
  trace référence le `TP-1015.G` de l'année fiscale de la paie.
- Règle 05 (paramètres annuels versionnés) — aucune constante fiscale
  (multiplicateur, seuil hebdomadaire) n'est codée en dur dans ce
  module ; ces valeurs sont lues depuis `parametres_annee` à la tâche
  5.2. La seule matrice de refus métier codée en dur ici est
  l'ensemble fermé des taux de vacances supportés (défense en
  profondeur, voir l'étape 0 de `calcul_gains`), qui n'est pas un
  paramètre fiscal au sens de la règle 05.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from models.enums import Juridiction, ModeArrondissement
from models.exceptions import UnsupportedPayrollCase
from models.payroll_input import PayrollInput
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import ParametresAnnee

# ---------------------------------------------------------------------------
# Helper d'arrondissement (Req 7.1, Req 12.3, design §Components §4)
# ---------------------------------------------------------------------------

#: Précision monétaire imposée par le TP-1015.G : 2 décimales. Ce n'est
#: pas un paramètre fiscal (règle 05 ne l'exige pas dans `parameters/`) —
#: c'est une convention de forme.
_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")


def _arrondir(montant: Decimal) -> Decimal:
    """Arrondit `montant` à 2 décimales selon ROUND_HALF_UP (Req 7.1, règle 01).

    Seul mécanisme d'arrondissement autorisé dans ce module (Req 12.3) :
    `round()`, `math.floor()`, `math.ceil()` et `math.trunc()` sont
    proscrits — voir le test de garde
    `tests/test_guards.py::TestGainsBrutsNoFloat`.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Point d'entrée public (Req 1, design §Components §1)
# ---------------------------------------------------------------------------


def calcul_gains(
    payroll_input: PayrollInput,
    parametres_annee: ParametresAnnee,
) -> tuple[GainsDecomposes, CalculationTrace]:
    """Assemble le brut d'une paie et sa trace (Req 1, règles 01, 02, 05).

    Fonction pure : deux appels avec les mêmes arguments retournent deux
    tuples égaux au sens `==`, sans état interne, sans lecture de
    fichier, sans appel à `datetime.now()` ni à toute autre source de
    non-déterminisme (Req 1.2, Req 14).

    Algorithme complet (design §Components §2, §6) : défense en
    profondeur `taux_vacances` (étape 0), salaire régulier (étape 1),
    heures supplémentaires (étape 2), base vacances (étape 3),
    indemnité de vacances (étape 4), brut total (étape 5), puis
    construction de la `CalculationTrace` et du `GainsDecomposes`.

    Exceptions :
        UnsupportedPayrollCase: si `payroll_input.taux_vacances` sort
            de la matrice fermée des taux de vacances supportés
            (situation qui ne peut théoriquement survenir qu'en cas de
            contournement de la validation via
            `PayrollInput.model_construct`).
    """
    # Étape 0 — Défense en profondeur `taux_vacances` (Req 10.3, Req 13.3,
    # design §Components §2 étape 0). En temps normal cette garde ne se
    # déclenche jamais : le validateur `_coherence_croisee` de
    # `PayrollInput` refuse déjà ce cas à la construction. Elle protège
    # uniquement contre un contournement via `PayrollInput.model_construct`.
    if payroll_input.taux_vacances not in {Decimal("0.04"), Decimal("0.06")}:
        raise UnsupportedPayrollCase(
            f"Taux d'indemnité de vacances {payroll_input.taux_vacances} "
            "non supporté par le Camp LilySO (règle 03, Req 10.3). Seul "
            "un taux figurant dans la matrice Camp LilySO admise par "
            "PayrollInput est accepté. Pour un cas exceptionnel, "
            "utiliser WebRAS (revenuquebec.ca/webras) et PDOC "
            "(canada.ca/pdoc)."
        )

    # Étape 1 — Lecture des paramètres heures supplémentaires (Req 3.2,
    # 9.1) : le multiplicateur et le seuil hebdomadaire ne sont jamais
    # codés en dur — ils sont lus depuis les paramètres annuels injectés.
    mult = parametres_annee.heures_supplementaires.multiplicateur
    seuil = parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures

    # Agrégation des entrées (design §Components §2, §5.3) : totaux de
    # période utilisés à la fois par l'algorithme et par la trace.
    heures_normales_totales = sum(
        (s.heures_normales for s in payroll_input.heures_par_semaine),
        start=Decimal("0"),
    )
    heures_supplementaires_totales = sum(
        (s.heures_supplementaires for s in payroll_input.heures_par_semaine),
        start=Decimal("0"),
    )

    # Étape 1 — Salaire régulier (Req 2, design §Components §2 étape 1).
    sr = _arrondir(
        sum(
            (
                s.heures_normales * payroll_input.taux_horaire_effectif
                for s in payroll_input.heures_par_semaine
            ),
            start=Decimal("0"),
        )
    )

    # Étape 2 — Heures supplémentaires (Req 3, design §Components §2
    # étape 2). Aucun reclassement des heures : le multiplicateur
    # s'applique à toutes les heures déclarées comme supplémentaires,
    # indépendamment du seuil hebdomadaire (Req 4).
    hs = _arrondir(
        sum(
            (
                s.heures_supplementaires
                * payroll_input.taux_horaire_effectif
                * mult
                for s in payroll_input.heures_par_semaine
            ),
            start=Decimal("0"),
        )
    )

    # Étape 3 — Base vacances (Req 5.1, 7.3, design §Components §2
    # étape 3). Somme exacte de trois `Decimal` déjà à 2 décimales — pas
    # de ré-arrondissement.
    base_vac = sr + hs + payroll_input.jours_feries_manuels

    # Étape 4 — Indemnité de vacances (Req 5.2, 5.6, design §Components
    # §2 étape 4). Formule identique pour 4 % et 6 % (Req 13.1).
    iv = _arrondir(base_vac * payroll_input.taux_vacances)

    # Étape 5 — Brut total (Req 6.1, 6.4, design §Components §2 étape
    # 5). Somme exacte de quatre `Decimal` déjà à 2 décimales — pas de
    # ré-arrondissement.
    brut = sr + hs + payroll_input.jours_feries_manuels + iv

    # Vérification interne d'identité comptable (Req 6.4) : protège
    # contre un refactoring futur qui introduirait un arrondissement
    # supplémentaire. Un écart est un bug interne, jamais un cas métier.
    assert brut == sr + hs + payroll_input.jours_feries_manuels + iv

    # Construction de la CalculationTrace (Req 8, design §Components §5).
    trace = CalculationTrace(
        source=(
            f"TP-1015.G {payroll_input.pay_period.annee_fiscale}, section "
            "salaire brut, heures supplémentaires et indemnité de vacances"
        ),
        annee=payroll_input.pay_period.annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="salaire brut, heures supplémentaires et indemnité de vacances",
        parametres_utilises={
            "multiplicateur_heures_supp": mult,
            "taux_vacances": payroll_input.taux_vacances,
        },
        entrees={
            "heures_normales_totales": heures_normales_totales,
            "heures_supplementaires_totales": heures_supplementaires_totales,
            "taux_horaire_effectif": payroll_input.taux_horaire_effectif,
            "jours_feries_manuels": payroll_input.jours_feries_manuels,
        },
        sous_totaux={
            "salaire_regulier": sr,
            "heures_supplementaires_montant": hs,
            "base_vacances": base_vac,
            "vacances": iv,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=brut,
    )

    # Construction du GainsDecomposes (Req 6.3, 6.5, design §Components
    # §3).
    gains = GainsDecomposes(
        salaire_regulier=sr,
        heures_supplementaires_montant=hs,
        vacances=iv,
        jours_feries_manuels=payroll_input.jours_feries_manuels,
        brut_total=brut,
        multiplicateur_heures_supp=mult,
        seuil_heures_supp_hebdo=seuil,
    )

    return (gains, trace)
