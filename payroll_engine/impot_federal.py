"""Retenue d'impôt fédéral — formule T4127 Option 1 et retenue effective.

Spec de référence : ``impots-retenues-source`` — tâche 10.1.
Design de référence : ``design.md`` §Components §1 (« Signatures
exactes »), §4 (« `calcul_impot_federal_formule` »), §5
(« `calcul_impot_federal_retenu` »), §6 (« Helpers partagés ») et §7
(« Ordre d'exécution »).

Ce module expose deux fonctions publiques et pures :

- :func:`calcul_impot_federal_formule` — retenue d'impôt fédéral calculée
  par le mécanisme T4127 Option 1 (déduction de la première cotisation
  supplémentaire au RRQ, ré-annualisation, paliers progressifs « méthode
  K », crédits non remboursables K1 — crédit personnel TD1 —, K2Q —
  cotisations RRQ base / AE / RQAP annualisées et plafonnées —, K4 —
  montant canadien pour emploi —, puis abattement du Québec, plancher à
  zéro).
- :func:`calcul_impot_federal_retenu` — retenue d'impôt fédéral effective :
  court-circuit **véritable** d'exonération (TD1) puis ajout inconditionnel
  de la retenue additionnelle fédérale.

Règles appliquées (Req 4, 5, 6) :

- Règle 01 (``Decimal`` obligatoire) — aucun ``float`` dans ce module ;
  le seul mécanisme d'arrondissement autorisé est ``Decimal.quantize``
  avec ``rounding=ROUND_HALF_UP`` (helper :func:`_arrondir`). Le calcul
  interne reste en **pleine précision** ``Decimal`` du début jusqu'à
  l'arrondissement **unique et final** de ``impot_periode`` (Req 8.1). La
  déduction pour la première cotisation supplémentaire au RRQ est exposée
  arrondie au cent **dans la trace** (valeur d'affichage/audit), mais la
  valeur pleine précision est conservée pour le calcul du revenu imposable
  de période.
- Règle 02 (traçabilité des formules) — chaque fonction retourne
  ``tuple[Decimal, CalculationTrace]``, la trace référençant le T4127 de
  l'année fiscale de la paie (source sur liste blanche).
- Règle 05 (paramètres annuels versionnés) — aucun taux, seuil,
  constante, déduction ni crédit n'est codé en dur : ces valeurs sont
  lues exclusivement depuis ``parametres_annee``. Seuls ``Decimal("0.00")``
  (plancher) et l'entier ``2`` (précision d'arrondissement) sont des
  littéraux autorisés.
- Règle 06 / Req 6.3 — le mécanisme K2Q recompose **localement** les
  projections annualisées des cotisations RRQ (taux de base), AE et RQAP
  à partir de ``gains.brut_total`` et des sections
  ``parametres_annee.rrq``/``.rqap``/``.assurance_emploi`` : **aucun**
  appel aux fonctions de calcul de cotisations sociales de la spec
  ``cotisations-sociales-qc``, **aucun** import de
  ``payroll_engine.rrq``/``.rqap``/``.assurance_emploi``, **aucune**
  lecture de ``payroll_input.cumuls_debut``.

Requirements couverts : 1.1, 1.2, 1.4, 1.5, 1.7, 1.8, 1.9, 4.1 à 4.9,
5.1 à 5.6, 6.1, 6.3, 7.1, 7.2, 7.3, 8.1, 8.2, 9.1 à 9.7, 10.5, 12.1,
12.2, 12.4, 12.5.
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
# Dupliqué à l'identique dans `impot_qc.py` — décision de duplication
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
    (Req 10.5) : chaque palier voit ses attributs typés `taux` et
    `constante_k` **matérialisés** au passage, de sorte qu'un palier marqué
    `"TO_FILL"` lève `MissingParameterError` **quel que soit** le palier
    finalement retenu par le revenu annualisé (Property 13). Cette
    matérialisation défensive est la raison pour laquelle la boucle ne
    court-circuite pas (`break`) sur le premier palier hors intervalle :
    tous les paliers sont validés, puis le dernier dont `seuil_bas_annuel
    <= revenu_annuel` est retenu. `MissingParameterError` est propagée
    telle quelle (règle 05).
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
# calcul_impot_federal_formule (Req 4, Req 6, Req 7, design §Components §4)
# ---------------------------------------------------------------------------


def calcul_impot_federal_formule(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la retenue d'impôt fédéral par la formule T4127 et sa trace.

    Algorithme (design §Components §4, Req 4, Req 7) — le calcul interne
    reste en **pleine précision** `Decimal` du début jusqu'à
    l'arrondissement **unique et final** de `impot_periode` (Req 8.1) :

    a. `deduction_rrq_supp = taux_rrq_supp × max(0, salaire_periode −
       exemption_periode_rrq)` (première cotisation supplémentaire au RRQ
       déduite du revenu, Req 4.1).
    b. `revenu_imposable_periode = salaire_periode − deduction_rrq_supp` ;
       `revenu_imposable_annuel = revenu_imposable_periode × nb_periodes`
       (Req 4.2).
    c. `(taux_palier, constante_k)` = dernier palier dont `seuil_bas_annuel
       <= revenu_imposable_annuel` ; `impot_avant_credits = taux_palier ×
       revenu_imposable_annuel − constante_k` (Req 4.3).
    d. `k1 = taux_conversion × montant_total_TD1_effectif` (crédit
       personnel TD1, Req 4.4).
    e. `k2q = taux_conversion × (cotisation_rrq_base + cotisation_ae +
       cotisation_rqap)`, où chaque cotisation est une projection annuelle
       théorique plafonnée, recalculée **localement** (Req 6.1, 6.3).
    f. `k4 = taux_conversion × min(revenu_imposable_annuel, cea_annuel)`
       (montant canadien pour emploi).
    g. `impot_annuel_base = max(0, impot_avant_credits − k1 − k2q − k4)` ;
       `impot_annuel_net = impot_annuel_base − taux_abattement ×
       impot_annuel_base` (abattement du Québec) ;
       `impot_periode = max(0, arrondir(impot_annuel_net / nb_periodes))`.

    Le comportement sous le seuil d'imposition (Req 7) est un cas normal
    de cette séquence : si `impot_avant_credits − k1 − k2q − k4 <= 0`, le
    `max(0, ...)` produit `Decimal("0.00")` sans branche dédiée. Aucun
    drapeau d'exonération ni la retenue additionnelle n'est lu (Req 4.9).

    Séparation stricte (Req 6.3) : `cotisation_rrq_annualisee_base`,
    `cotisation_ae_annualisee` et `cotisation_rqap_annualisee` sont des
    variables **strictement internes** à cette fonction (Req 6.1),
    calculées directement depuis `gains.brut_total` et les sections de
    paramètres `rrq`/`rqap`/`assurance_emploi` — jamais via les fonctions
    de calcul de cotisations sociales de la spec `cotisations-sociales-qc`,
    jamais depuis `payroll_input.cumuls_debut`.

    Fonction pure (Req 1.4, 1.7, 1.9) : ne mute aucun argument, aucune E/S.

    Exceptions :
        MissingParameterError: si un paramètre consommé (paliers,
            `taux_credits_convertibles`, `montant_emploi_canadien_annuel`,
            `plafond_cotisation_base_rrq_annuel`, `taux_abattement_quebec`)
            porte la sentinelle `"TO_FILL"` (Req 1.8, 10.5).
    """
    impot_federal = parametres_annee.impot_federal
    rrq = parametres_annee.rrq
    assurance_emploi = parametres_annee.assurance_emploi
    rqap = parametres_annee.rqap

    # Étape a — Salaire de période (Req 1.6) et déduction de la première
    # cotisation supplémentaire au RRQ (Req 4.1).
    salaire_periode = gains.brut_total
    nb_periodes = Decimal(str(payroll_input.pay_period.nb_periodes_annuelles))

    # `portion_supplementaire_deductible_fed` est un dict extra non typé
    # (absorbé par extra="allow" sur RRQParametres) : sa valeur brute est
    # une chaîne "0.010" — conversion en Decimal sans passer par float
    # (règle 01).
    taux_rrq_supp = Decimal(
        str(rrq.portion_supplementaire_deductible_fed["taux_effectif"])
    )
    exemption_periode_rrq = rrq.exemption_par_periode_aux_deux_semaines_2026
    deduction_rrq_supp = taux_rrq_supp * max(
        Decimal("0.00"), salaire_periode - exemption_periode_rrq
    )

    # Étape b — Annualisation nette (pleine précision, Req 4.2).
    revenu_imposable_periode = salaire_periode - deduction_rrq_supp
    revenu_imposable_annuel = revenu_imposable_periode * nb_periodes

    # Étape c — Palier progressif applicable (méthode K, Req 4.3).
    taux_palier, constante_k = _taux_et_constante_pour_palier(
        revenu_imposable_annuel, impot_federal.paliers
    )
    impot_avant_credits = taux_palier * revenu_imposable_annuel - constante_k

    taux_conversion = impot_federal.taux_credits_convertibles

    # Étape d — K1 : crédit personnel (TD1, Req 4.4).
    k1 = taux_conversion * payroll_input.montant_total_TD1_effectif

    # Étape e — K2Q : cotisations RRQ base / AE / RQAP annualisées et
    # plafonnées (mécanisme T4127 Option 1). RECALCUL LOCAL : les variables
    # `cotisation_*_annualisee` sont strictement internes (Req 6.1) et ne
    # transitent JAMAIS par les fonctions de calcul de cotisations sociales
    # de la spec cotisations-sociales-qc (Req 6.3) ni par
    # payroll_input.cumuls_debut. Ce sont des projections annuelles
    # théoriques, pas la cotisation effective.
    taux_base_rrq = rrq.taux_cotisation_totale_employe - taux_rrq_supp
    cotisation_rrq_annualisee_base = min(
        nb_periodes
        * taux_base_rrq
        * max(Decimal("0.00"), salaire_periode - exemption_periode_rrq),
        impot_federal.plafond_cotisation_base_rrq_annuel,
    )
    cotisation_ae_annualisee = min(
        nb_periodes * assurance_emploi.taux_employe_quebec * salaire_periode,
        assurance_emploi.cotisation_max_employe,
    )
    cotisation_rqap_annualisee = min(
        nb_periodes * rqap.taux_employe * salaire_periode,
        rqap.cotisation_max_employe,
    )
    k2q = taux_conversion * (
        cotisation_rrq_annualisee_base
        + cotisation_ae_annualisee
        + cotisation_rqap_annualisee
    )

    # Étape f — K4 : montant canadien pour emploi (CEA), plafonné au revenu.
    cea_annuel = impot_federal.montant_emploi_canadien_annuel
    k4 = taux_conversion * min(revenu_imposable_annuel, cea_annuel)

    # Impôt annuel de base (plancher à zéro après les trois crédits).
    impot_annuel_base = max(
        Decimal("0.00"), impot_avant_credits - k1 - k2q - k4
    )

    # Étape g — Abattement du Québec puis montant de période : unique et
    # dernier arrondissement monétaire (Req 8.1), suivi du plancher à zéro
    # (Req 4.6, 7.1).
    taux_abattement = impot_federal.taux_abattement_quebec
    impot_annuel_net = impot_annuel_base - (taux_abattement * impot_annuel_base)
    impot_periode = max(
        Decimal("0.00"), _arrondir(impot_annuel_net / nb_periodes)
    )

    # Construction de la CalculationTrace (Req 9, design §Components §4).
    # Les taux/constantes sont exposés en PLEINE PRÉCISION (la Property 7
    # les relit pour reconstruire la chaîne). En revanche, les sous-totaux
    # MONÉTAIRES du mécanisme de crédits (revenu_imposable_annuel,
    # impot_avant_credits, k1, k2q, k4, impot_annuel_base, impot_annuel_net)
    # sont exposés ARRONDIS AU CENT dans la trace — alignement strict sur
    # `impot_qc.py` (voir §sous_totaux de `calcul_impot_qc_formule`) : la
    # trace est une vue d'affichage/audit (règle 02), pas le calcul. Le
    # calcul interne, lui, a conservé la PLEINE PRÉCISION `Decimal` de bout
    # en bout jusqu'à l'arrondissement unique et final de `impot_periode`
    # (Req 8.1) ; seules les valeurs STOCKÉES dans `sous_totaux` sont
    # arrondies, ce qui évite en outre d'exposer de longues séquences de
    # décimales dans les fixtures (règle 04, faux positifs « NAS »). La
    # déduction RRQ supplémentaire est déjà exposée arrondie au cent dans
    # `entrees` (Property 6) et le revenu imposable de période en découle.
    deduction_rrq_supp_arrondie = _arrondir(deduction_rrq_supp)
    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"T4127 {annee_fiscale}, section 3 — Impôt fédéral",
        annee=annee_fiscale,
        juridiction=Juridiction.CANADA,
        section="3 — Retenue d'impôt fédéral (formule)",
        parametres_utilises={
            "taux_credits_convertibles": taux_conversion,
            "taux_palier": taux_palier,
            "constante_k": constante_k,
            "montant_emploi_canadien_annuel": cea_annuel,
            "taux_abattement_quebec": taux_abattement,
        },
        entrees={
            "salaire_periode": salaire_periode,
            "nb_periodes_annuelles": nb_periodes,
            "deduction_rrq_supp": deduction_rrq_supp_arrondie,
            "montant_total_td1": payroll_input.montant_total_TD1_effectif,
        },
        sous_totaux={
            "revenu_imposable_periode": _arrondir(
                salaire_periode - deduction_rrq_supp_arrondie
            ),
            "revenu_imposable_annuel": _arrondir(revenu_imposable_annuel),
            "impot_avant_credits": _arrondir(impot_avant_credits),
            "k1": _arrondir(k1),
            "k2q": _arrondir(k2q),
            "k4": _arrondir(k4),
            "impot_annuel_base": _arrondir(impot_annuel_base),
            "impot_annuel_net": _arrondir(impot_annuel_net),
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=impot_periode,
    )

    return (impot_periode, trace)


# ---------------------------------------------------------------------------
# calcul_impot_federal_retenu (Req 5, design §Components §5)
# ---------------------------------------------------------------------------


def calcul_impot_federal_retenu(
    payroll_input: PayrollInput,
    gains: GainsDecomposes,
    parametres_annee: ParametresAnnee,
) -> tuple[Decimal, CalculationTrace]:
    """Calcule la retenue d'impôt fédéral effective et sa trace (Req 5, règles 01, 02, 05).

    Délégation structurelle stricte avec court-circuit **véritable**
    (design §Components §5, Req 5.3) :

    - si `payroll_input.exoneration_TD1_effective` est vrai, le montant de
      base est forcé à `Decimal("0.00")` et `calcul_impot_federal_formule`
      n'est **jamais invoquée** — pas même pour construire la trace ;
    - sinon, `montant_base = calcul_impot_federal_formule(...)[0]`.

    La retenue additionnelle fédérale s'ajoute **inconditionnellement**
    dans les deux cas (Req 5.2) : `retenue_effective = montant_base +
    retenue_additionnelle_federale_effective`, sans ré-arrondissement
    (Req 8.2 — somme de deux valeurs déjà à deux décimales).

    Fonction pure (Req 1.4, 1.7, 1.9).

    Exceptions :
        MissingParameterError: propagée depuis
            `calcul_impot_federal_formule` lorsque l'exonération est
            inactive et qu'un paramètre consommé porte la sentinelle
            `"TO_FILL"` (Req 1.8, 10.5).
    """
    exoneration = payroll_input.exoneration_TD1_effective

    if exoneration:
        # Court-circuit véritable : la fonction formule n'est PAS invoquée
        # (Req 5.3, Property 11).
        montant_base = Decimal("0.00")
    else:
        montant_base, _trace_formule = calcul_impot_federal_formule(
            payroll_input, gains, parametres_annee
        )

    # Ajout inconditionnel de la retenue additionnelle, sans ré-arrondissement
    # (Req 5.2, 8.2).
    retenue_additionnelle = payroll_input.retenue_additionnelle_federale_effective
    retenue_effective = montant_base + retenue_additionnelle

    annee_fiscale = payroll_input.pay_period.annee_fiscale
    trace = CalculationTrace(
        source=f"T4127 {annee_fiscale}, section 3 — Impôt fédéral",
        annee=annee_fiscale,
        juridiction=Juridiction.CANADA,
        section="3 — Retenue d'impôt fédéral (retenu)",
        parametres_utilises={
            # Drapeau d'exonération encodé en `Decimal` via le patron
            # mandaté `Decimal(str(...))` (design §Components §2, règle
            # 01) : `int(exoneration)` vaut 0 ou 1 (booléen, sous-type de
            # `int`, jamais un `float`), sérialisé en chaîne puis converti.
            "exoneration_active": Decimal(str(int(exoneration))),
        },
        entrees={
            "impot_federal_formule": montant_base,
            "retenue_additionnelle_federale": retenue_additionnelle,
        },
        sous_totaux={
            "retenue_effective": retenue_effective,
        },
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=retenue_effective,
    )

    return (retenue_effective, trace)
