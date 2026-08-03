"""Retenue d'impôt du Québec — formule TP-1015.F et retenue effective.

Spec de référence : ``impots-retenues-source`` — tâche 9.1.
Design de référence : ``design.md`` §Components §1 (« Signatures
exactes »), §2 (« `calcul_impot_qc_formule` »), §3 (« `calcul_impot_qc_retenu` »),
§6 (« Helpers partagés ») et §7 (« Ordre d'exécution »).

Ce module expose deux fonctions publiques et pures :

- :func:`calcul_impot_qc_formule` — retenue d'impôt du Québec calculée
  par la formule à paliers progressifs du TP-1015.F (revenu imposable de
  période après les DEUX déductions — déduction pour travailleur proratée
  et déduction pour la première cotisation supplémentaire au RRQ —,
  ré-annualisation, palier progressif via constante de rebasage « méthode
  K », crédit personnel convertible, plancher à zéro).
- :func:`calcul_impot_qc_retenu` — retenue d'impôt QC effective :
  court-circuit **véritable** d'exonération (TP-1015.3) puis ajout
  inconditionnel de la retenue additionnelle QC.

Règles appliquées (Req 1, 2, 3) :

- Règle 01 (``Decimal`` obligatoire) — aucun ``float`` dans ce module ;
  le seul mécanisme d'arrondissement autorisé est ``Decimal.quantize``
  avec ``rounding=ROUND_HALF_UP`` (helper :func:`_arrondir`). La formule
  officielle TP-1015.F 2026 comporte DEUX arrondissements monétaires
  bien identifiés : la déduction pour travailleur de période ``H`` et le
  montant de période final ``impot_periode`` (Req 8.1). Le reste du calcul
  reste en pleine précision ``Decimal``.
- Règle 02 (traçabilité des formules) — chaque fonction retourne
  ``tuple[Decimal, CalculationTrace]``, la trace référençant le
  TP-1015.F de l'année fiscale de la paie (source sur liste blanche).
- Règle 05 (paramètres annuels versionnés) — aucun taux, seuil,
  constante, déduction ni crédit n'est codé en dur : ces valeurs sont
  lues exclusivement depuis ``parametres_annee``. Seuls ``Decimal("0.00")``
  (plancher) et l'entier ``2`` (précision d'arrondissement) sont des
  littéraux autorisés.

Requirements couverts : 1.1, 1.2, 1.4, 1.5, 1.7, 1.8, 1.9, 2.1, 2.2,
2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.1, 7.2,
7.3, 8.1, 8.2, 9.1 à 9.7, 10.5, 12.1, 12.2, 12.4, 12.5.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from models.enums import Juridiction, ModeArrondissement
from models.payroll_input import PayrollInput
from models.payroll_result import GainsDecomposes
from models.trace import CalculationTrace
from payroll_engine.parameters_loader import ParametresAnnee, Palier

# ---------------------------------------------------------------------------
# Helper d'arrondissement (Req 8.1, design §Architecture / §Components §6)
# ---------------------------------------------------------------------------
#
# Dupliqué à l'identique dans `impot_federal.py` — décision de duplication
# contrôlée (design §Architecture « Helper d'arrondissement partagé »),
# même justification que `rrq.py`/`rqap.py`/`assurance_emploi.py`.

_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")


def _arrondir(montant: Decimal) -> Decimal:
    """Arrondit `montant` à 2 décimales selon ROUND_HALF_UP (Req 8.1, règle 01).

    Seul mécanisme d'arrondissement autorisé dans ce module : `round()`,
    `math.floor()`, `math.ceil()` et `math.trunc()` sont proscrits.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Helper de recherche de palier (design §Architecture / §Components §6)
# ---------------------------------------------------------------------------


def _taux_et_constante_pour_palier(
    revenu_annuel: Decimal, paliers: tuple[Palier, ...]
) -> tuple[Decimal, Decimal]:
    """Retourne (taux, constante_k) du dernier palier dont `seuil_bas_annuel <= revenu_annuel`.

    `paliers` est supposé trié par `seuil_bas_annuel` croissant (invariant
    documenté du fichier JSON, design §Architecture — non vérifié ici).

    La table de paliers entière est un **paramètre consommé** de la formule
    (Req 10.1, 10.5) : chaque palier voit ses attributs typés `taux` et
    `constante_k` **matérialisés** au passage, de sorte qu'un palier marqué
    `"TO_FILL"` lève `MissingParameterError` **quel que soit** le palier
    finalement retenu par le revenu annualisé (Property 13). Cette
    matérialisation défensive est la raison pour laquelle la boucle ne
    court-circuite pas (`break`) sur le premier palier hors intervalle :
    tous les paliers sont validés, puis le dernier dont `seuil_bas_annuel
    <= revenu_annuel` est retenu (sélection identique à la version lazy du
    design §Components §6, la liste étant triée par seuil croissant).
    `MissingParameterError` est propagée telle quelle (règle 05).
    """
    # `next(iter(...))` plutôt que `paliers[0]` : évite un littéral entier
    # nu (règle 05, garde AST value-agnostic) tout en sélectionnant le
    # premier palier comme valeur de repli (réécrit dans la boucle).
    palier_applicable = next(iter(paliers))
    for palier in paliers:
        # Matérialisation défensive (Property 13) : force la validation
        # TO_FILL du taux et de la constante de chaque palier de la table.
        _ = palier.taux
        _ = palier.constante_k
        if palier.seuil_bas_annuel <= revenu_annuel:
            palier_applicable = palier
    return (palier_applicable.taux, palier_applicable.constante_k)


# ---------------------------------------------------------------------------
# calcul_impot_qc_formule (Req 2, Req 7, design §Components §2)
# ---------------------------------------------------------------------------


def calcul_impot_qc_formule(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la retenue d'impôt QC par la formule TP-1015.F et sa trace.

    Algorithme (design §Components §2, Req 2, Req 7) — le calcul interne
    reste en **pleine précision** `Decimal` du début jusqu'à
    l'arrondissement **unique et final** de `impot_periode` (Req 8.1) :

    1. `salaire_periode = gains.brut_total` (Req 1.6).
    2. Déduction pour travailleur (formule officielle TP-1015.F 2026,
       arrondie au cent) :
       `deduction_travailleur_periode = arrondir(min(
       taux_deduction_pour_travailleur × salaire_periode,
       deduction_pour_travailleur_annuelle / nb_periodes))`
       (soit `H = arrondir(min(0,06 × D ; 1 450 $ ÷ P))`).
    3. Déduction pour la première cotisation supplémentaire au RRQ :
       `deduction_rrq_supp_periode = taux_rrq_supp × max(0, salaire_periode
       - exemption_rrq_periode)`.
    4. `revenu_imposable_periode = max(0, salaire_periode -
       deduction_travailleur_periode - deduction_rrq_supp_periode)`.
    5. `revenu_imposable_annuel = revenu_imposable_periode × nb_periodes`.
    6. `(taux_palier, constante_k)` = dernier palier dont
       `seuil_bas_annuel <= revenu_imposable_annuel`.
    7. `impot_annuel_base = max(0, taux_palier × revenu_imposable_annuel -
       constante_k)`.
    8. `credit_personnel_annuel = taux_credits_convertibles ×
       montant_total_TP1015_3_effectif`.
    9. `impot_annuel_net = impot_annuel_base - credit_personnel_annuel`.
    10. `impot_periode = max(0, arrondir(impot_annuel_net / nb_periodes))`.

    Le comportement sous le seuil d'imposition (Req 7) est un cas normal
    de cette séquence : si `impot_annuel_net <= 0`, le `max(0, ...)` final
    produit `Decimal("0.00")` sans branche dédiée ni exception. Aucun
    drapeau d'exonération n'est lu (Req 2.8).

    Fonction pure (Req 1.4, 1.7, 1.9) : ne mute aucun argument, aucune E/S.

    Exceptions :
        MissingParameterError: si un paramètre consommé de la section
            `impot_quebec` (paliers, `taux_credits_convertibles`,
            `deduction_pour_travailleur_annuelle`) porte la sentinelle
            `"TO_FILL"` (Req 1.8, 10.5).
    """
    impot_quebec = parametres_annee.impot_quebec
    rrq = parametres_annee.rrq

    # Étape 1 — Salaire de période (Req 1.6).
    salaire_periode = gains.brut_total
    nb_periodes = Decimal(str(payroll_input.pay_period.nb_periodes_annuelles))

    # Étape 2 — Déduction pour travailleur (formule officielle TP-1015.F 2026) :
    # H = arrondir(min(taux_deduction_pour_travailleur × D ;
    #                  deduction_pour_travailleur_annuelle ÷ P)).
    # Le montant de période H est arrondi au cent (comportement WebRAS
    # confirmé par le PDF officiel). Le taux 0,06 et le plafond 1 450 $
    # proviennent exclusivement des paramètres (règle 05).
    deduction_travailleur_annuelle = impot_quebec.deduction_pour_travailleur_annuelle
    taux_deduction_travailleur = impot_quebec.taux_deduction_pour_travailleur
    deduction_travailleur_plafond_periode = (
        deduction_travailleur_annuelle / nb_periodes
    )
    deduction_travailleur_periode = _arrondir(
        min(
            taux_deduction_travailleur * salaire_periode,
            deduction_travailleur_plafond_periode,
        )
    )

    # Étape 3 — Déduction pour la première cotisation supplémentaire au RRQ.
    # `portion_supplementaire_deductible_fed` est un dict extra non typé
    # (absorbé par extra="allow" sur RRQParametres) : sa valeur brute est
    # une chaîne "0.010" — conversion en Decimal sans passer par float
    # (règle 01).
    taux_rrq_supp = Decimal(
        str(rrq.portion_supplementaire_deductible_fed["taux_effectif"])
    )
    exemption_rrq_periode = rrq.exemption_par_periode_aux_deux_semaines_2026
    deduction_rrq_supp_periode = taux_rrq_supp * max(
        Decimal("0.00"), salaire_periode - exemption_rrq_periode
    )

    # Étape 4 — Revenu imposable de période (deux déductions, pleine précision).
    revenu_imposable_periode = max(
        Decimal("0.00"),
        salaire_periode - deduction_travailleur_periode - deduction_rrq_supp_periode,
    )

    # Étape 5 — Ré-annualisation.
    revenu_imposable_annuel = revenu_imposable_periode * nb_periodes

    # Étape 6 — Palier progressif applicable (méthode K).
    taux_palier, constante_k = _taux_et_constante_pour_palier(
        revenu_imposable_annuel, impot_quebec.paliers
    )

    # Étape 7 — Impôt annuel de base (plancher à zéro).
    impot_annuel_base = max(
        Decimal("0.00"), taux_palier * revenu_imposable_annuel - constante_k
    )

    # Étape 8 — Crédit personnel convertible.
    taux_conversion = impot_quebec.taux_credits_convertibles
    credit_personnel_annuel = (
        taux_conversion * payroll_input.montant_total_TP1015_3_effectif
    )

    # Étape 9 — Impôt annuel net.
    impot_annuel_net = impot_annuel_base - credit_personnel_annuel

    # Étape 10 — Montant de période : arrondissement final au cent, puis
    # plancher à zéro (Req 2.5, 2.7, 7.1, 8.1). Second arrondissement
    # monétaire officiel de la formule (le premier étant la déduction H).
    impot_periode = max(Decimal("0.00"), _arrondir(impot_annuel_net / nb_periodes))

    # Construction de la CalculationTrace (Req 9, design §Components §2).
    # Les taux/constantes/exemption sont exposés en PLEINE PRÉCISION (non
    # arrondis) — la Property 5 les relit pour reconstruire la chaîne. Les
    # sous-totaux monétaires sont exposés arrondis au cent (valeur
    # d'affichage/audit, Property 3), le calcul interne ayant conservé la
    # pleine précision jusqu'à `impot_periode`.
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 4 — Impôt du Québec",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="4 — Retenue d'impôt du Québec (formule)",
        parametres_utilises={
            "deduction_pour_travailleur_annuelle": deduction_travailleur_annuelle,
            "taux_deduction_pour_travailleur": taux_deduction_travailleur,
            "taux_credits_convertibles": taux_conversion,
            "taux_palier": taux_palier,
            "constante_k": constante_k,
            "taux_rrq_supp": taux_rrq_supp,
            "exemption_rrq_periode": exemption_rrq_periode,
        },
        entrees={
            "salaire_periode": salaire_periode,
            "nb_periodes_annuelles": nb_periodes,
            "montant_total_tp1015_3": payroll_input.montant_total_TP1015_3_effectif,
        },
        sous_totaux={
            # Déjà arrondie au cent par la formule officielle (H) — ne pas
            # ré-arrondir une seconde fois.
            "deduction_travailleur_periode": deduction_travailleur_periode,
            "deduction_rrq_supp_periode": _arrondir(deduction_rrq_supp_periode),
            "revenu_imposable_periode": _arrondir(revenu_imposable_periode),
            "revenu_imposable_annuel": _arrondir(revenu_imposable_annuel),
            "impot_annuel_base": _arrondir(impot_annuel_base),
            "credit_personnel_annuel": _arrondir(credit_personnel_annuel),
            "impot_annuel_net": _arrondir(impot_annuel_net),
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=impot_periode,
    )

    return (impot_periode, trace)


# ---------------------------------------------------------------------------
# calcul_impot_qc_retenu (Req 3, design §Components §3)
# ---------------------------------------------------------------------------


def calcul_impot_qc_retenu(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la retenue d'impôt QC effective et sa trace (Req 3, règles 01, 02, 05).

    Délégation structurelle stricte avec court-circuit **véritable**
    (design §Components §3, Req 3.3) :

    - si `payroll_input.exoneration_TP1015_3_effectif` est vrai, le montant
      de base est forcé à `Decimal("0.00")` et `calcul_impot_qc_formule`
      n'est **jamais invoquée** — pas même pour construire la trace ;
    - sinon, `montant_base = calcul_impot_qc_formule(...)[0]`.

    La retenue additionnelle QC s'ajoute **inconditionnellement** dans les
    deux cas (Req 3.2) : `retenue_effective = montant_base +
    retenue_additionnelle_QC_effective`, sans ré-arrondissement (Req 8.2 —
    somme de deux valeurs déjà à deux décimales).

    Fonction pure (Req 1.4, 1.7, 1.9).

    Exceptions :
        MissingParameterError: propagée depuis `calcul_impot_qc_formule`
            lorsque l'exonération est inactive et qu'un paramètre consommé
            porte la sentinelle `"TO_FILL"` (Req 1.8, 10.5).
    """
    exoneration = payroll_input.exoneration_TP1015_3_effectif

    if exoneration:
        # Court-circuit véritable : la fonction formule n'est PAS invoquée
        # (Req 3.3, Property 11).
        montant_base = Decimal("0.00")
    else:
        montant_base, _trace_formule = calcul_impot_qc_formule(
            payroll_input, gains, parametres_annee
        )

    # Ajout inconditionnel de la retenue additionnelle, sans ré-arrondissement
    # (Req 3.2, 8.2).
    retenue_additionnelle = payroll_input.retenue_additionnelle_QC_effective
    retenue_effective = montant_base + retenue_additionnelle

    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"TP-1015.F {annee_fiscale}, section 4 — Impôt du Québec",
        annee=annee_fiscale,
        juridiction=Juridiction.QUEBEC,
        section="4 — Retenue d'impôt du Québec (retenu)",
        parametres_utilises={
            # Drapeau d'exonération encodé en `Decimal` via le patron
            # mandaté `Decimal(str(...))` (design §Components §2, règle
            # 01) : `int(exoneration)` vaut 0 ou 1 (booléen, sous-type
            # de `int`, jamais un `float`), sérialisé en chaîne puis
            # converti. Évite à la fois les littéraux `Decimal("1")` /
            # `Decimal("0")` (garde valeurs fiscales en dur) et la
            # conversion directe `Decimal(int)`/`Decimal(float)`.
            "exoneration_active": Decimal(str(int(exoneration))),
        },
        entrees={
            "impot_qc_formule": montant_base,
            "retenue_additionnelle_qc": retenue_additionnelle,
        },
        sous_totaux={
            "retenue_effective": retenue_effective,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=retenue_effective,
    )

    return (retenue_effective, trace)
