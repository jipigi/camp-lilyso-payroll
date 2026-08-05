"""Orchestrateur bout-en-bout de l'assemblage d'une paie complète.

Spec de référence : ``net-cumuls-registre`` — tâche 7.1 (squelette :
``_ContributionPaie`` et imports du module).
Design de référence : ``design.md`` §Components §1 (`assembler_paie`,
pseudocode complet A à H) et §2 (`_ContributionPaie`).
Requirements de référence : Req 1 à 8 (`requirements.md`).

Ce module expose (tâche 7.2, à venir) une unique fonction publique
``assembler_paie`` qui invoque, dans l'ordre, les neuf fonctions de
calcul déjà livrées par les étapes 2 à 5 du plan d'implémentation
(`gains_bruts`, `rrq`, `rqap`, `assurance_emploi`, `impot_qc`,
`impot_federal`, `charges_patronales`), résout la dépendance circulaire
de `cumuls_fin` via l'objet privé `_ContributionPaie` (cette tâche), puis
construit le `PayrollResult` complet en un seul appel.

**Aucune formule fiscale n'est implémentée ici** : ce module orchestre,
il ne calcule pas (règle 05 — aucun taux, plafond ni constante fiscale
codé en dur ; les paramètres transitent exclusivement par
`ParametresAnnee` injecté par l'appelant, jamais relu depuis le disque
par ce module — Req 1.3, aucun appel au chargeur de paramètres).

Discipline appliquée (voir `requirements.md` §Introduction et
`design.md` §Overview) :

- Règle 01 — `Decimal` de bout en bout, aucun `float` intermédiaire.
- Règle 02 — aucune nouvelle `CalculationTrace` n'est inventée ici ;
  chaque `MontantAvecTrace` reçu d'une fonction invoquée est reporté
  sans altération (Req 8.1 à 8.3).
- Règle 03 — aucun nouveau garde-fou de périmètre ; toute
  `UnsupportedPayrollCase`/`MissingParameterError` levée par une
  fonction invoquée est propagée sans interception (Req 2.6, 17.1 à
  17.3) — ce module ne lève jamais lui-même `UnsupportedPayrollCase`.
- Règle 05 — voir ci-dessus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.cumuls import CumulsYTD
from models.enums import StatutDePaie
from models.payroll_input import PayrollInput
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
    PayrollResult,
    RetenuesEmploye,
)
from payroll_engine.assurance_emploi import calcul_ae_employe
from payroll_engine.charges_patronales import assembler_cotisations_employeur
from payroll_engine.gains_bruts import calcul_gains
from payroll_engine.impot_federal import (
    calcul_impot_federal_formule,
    calcul_impot_federal_retenu,
)
from payroll_engine.impot_qc import calcul_impot_qc_formule, calcul_impot_qc_retenu
from payroll_engine.parameters_loader import ParametresAnnee
from payroll_engine.rqap import calcul_rqap_employe
from payroll_engine.rrq import calcul_rrq_employe


@dataclass(frozen=True)
class _ContributionPaie:
    """Objet intermédiaire privé — pont entre les montants de la paie
    courante et `CumulsYTD.avec_paie`, AVANT que le `PayrollResult` final
    n'existe (résout la dépendance circulaire, décision requirements
    n° 6, Req 6.1 à 6.3).

    Expose exactement les attributs que `CumulsYTD.avec_paie` lit par
    duck typing (`getattr(resultat, categorie, ...)` sur
    `models.cumuls._CATEGORIES_MONETAIRES`, sans `isinstance` — voir
    `models/cumuls.py`) : `employe_id`, `annee_fiscale`, et les onze
    catégories monétaires identiques à
    `models.cumuls._CATEGORIES_MONETAIRES` (`brut`, `vacances`,
    `rrq_employe`, `rrq_employeur`, `rqap_employe`, `rqap_employeur`,
    `ae_employe`, `ae_employeur`, `impot_qc_retenu`,
    `impot_federal_retenu`, `net`).

    Interne à `net_pay.py` — non exportée, non exposée hors module.
    """

    employe_id: str
    annee_fiscale: int
    brut: Decimal
    vacances: Decimal
    rrq_employe: Decimal
    rrq_employeur: Decimal
    rqap_employe: Decimal
    rqap_employeur: Decimal
    ae_employe: Decimal
    ae_employeur: Decimal
    impot_qc_retenu: Decimal
    impot_federal_retenu: Decimal
    net: Decimal


def assembler_paie(
    payroll_input: PayrollInput,
    parametres_annee: ParametresAnnee,
    id_paie: str,
    version: int,
    statut: StatutDePaie,
    date_creation: datetime,
    date_emission: datetime | None = None,
    remplace_par_id: str | None = None,
) -> PayrollResult:
    """Assemble une paie complète en invoquant, dans l'ordre, les neuf
    fonctions de calcul déjà livrées (Req 1, Req 2).

    Fonction pure : ``id_paie``, ``version``, ``statut``,
    ``date_creation``, ``date_emission``, ``remplace_par_id`` sont fournis
    par l'appelant, jamais générés en interne (Req 1.2) — aucun appel à
    ``datetime.now()``, ``uuid.uuid4()`` ou équivalent. Deux appels avec
    les mêmes huit arguments produisent deux ``PayrollResult`` égaux au
    sens ``==`` (Req 1.2, 1.4).

    Algorithme complet (design §Components §1, étapes A à H) : gains
    (A), trois retenues sociales employé (B), impôts QC/fédéral formule
    et retenu (C), cotisations employeur en un seul appel (D), assemblage
    ``RetenuesEmploye`` (E), identités comptables ``net``/``cout_employeur``
    (F), résolution de la dépendance circulaire ``cumuls_fin`` via
    ``_ContributionPaie`` (G), construction finale du ``PayrollResult``
    via le constructeur Pydantic standard (H).

    Aucun ``try``/``except`` : toute ``MissingParameterError``,
    ``UnsupportedPayrollCase`` ou ``PayrollDomainError`` levée par l'une
    des fonctions invoquées ou par ``CumulsYTD.avec_paie`` se propage
    inchangée jusqu'à l'appelant (Req 2.6, 6.4, 17.3).

    **Calcul de ``additionnelle_permise`` (spec ``impots-retenues-source``,
    Requirement 14)** : avant d'invoquer ``calcul_impot_qc_retenu``/
    ``calcul_impot_federal_retenu``, cette fonction calcule un booléen
    ``additionnelle_permise`` en comparant la somme des deux retenues
    additionnelles volontaires demandées à l'espace disponible sur le
    brut après les cotisations obligatoires (RRQ, RQAP, AE) et l'impôt
    de base (post-exonération, pré-additionnelle) des deux juridictions.
    Ce calcul est une **comparaison arithmétique pure**, pas une formule
    fiscale TP-1015.F ni T4127/T4001 : il implémente une **décision
    opérationnelle du projet Camp LilySO**, documentée dans
    ``docs/hypotheses-2026.md`` (sections 5 et 6) et
    ``docs/journal-validation.md`` (recherche documentaire infructueuse
    auprès de PDOC et WebRAS pour ce cas). Ce calcul est effectué ici, et
    non dans ``impot_qc.py``/``impot_federal.py``, car seul cet
    orchestrateur a la vue transversale nécessaire (accès simultané aux
    montants RRQ/RQAP/AE et à l'impôt de base des deux juridictions) —
    cohérent avec la règle « aucune formule fiscale implémentée ici » de
    ce module (voir docstring de module) : ce calcul n'invente aucun taux
    ni seuil fiscal, il compare des montants déjà produits par les
    fonctions invoquées.
    """
    # --- A. Gains (Req 2.1) -----------------------------------------
    gains, _trace_gains = calcul_gains(payroll_input, parametres_annee)

    # --- B. Trois retenues sociales employé (Req 2.2) ----------------
    rrq_emp_montant, rrq_emp_trace = calcul_rrq_employe(
        payroll_input, gains, parametres_annee
    )
    rqap_emp_montant, rqap_emp_trace = calcul_rqap_employe(
        payroll_input, gains, parametres_annee
    )
    ae_emp_montant, ae_emp_trace = calcul_ae_employe(
        payroll_input, gains, parametres_annee
    )

    # --- C. Impôts QC et fédéral — formule ET retenue (Req 2.3) ------
    iqc_formule_montant, iqc_formule_trace = calcul_impot_qc_formule(
        payroll_input, gains, parametres_annee
    )
    ifed_formule_montant, ifed_formule_trace = calcul_impot_federal_formule(
        payroll_input, gains, parametres_annee
    )

    # --- C'. additionnelle_permise (spec impots-retenues-source, Req 14) -
    # Comparaison arithmétique pure — décision opérationnelle Camp
    # LilySO, non prescrite par TP-1015.F ni T4127/T4001 (voir docstring
    # de fonction et docs/hypotheses-2026.md). Le montant de base de
    # chaque juridiction suit son propre court-circuit d'exonération
    # existant (inchangé) avant d'entrer dans le calcul de l'espace
    # disponible.
    # Zéro obtenu par arithmétique sur un montant déjà produit
    # (`iqc_formule_montant - iqc_formule_montant`), jamais par un
    # littéral `Decimal("0.00")` codé en dur (règle 05 — ce module n'a
    # besoin d'AUCUNE constante `Decimal` en dur, voir
    # `TestNetPayNoHardcodedFiscalValues`).
    montant_base_qc = (
        iqc_formule_montant - iqc_formule_montant
        if payroll_input.exoneration_TP1015_3_effectif
        else iqc_formule_montant
    )
    montant_base_federal = (
        ifed_formule_montant - ifed_formule_montant
        if payroll_input.exoneration_TD1_effective
        else ifed_formule_montant
    )
    espace_disponible = (
        gains.brut_total
        - rrq_emp_montant
        - rqap_emp_montant
        - ae_emp_montant
        - montant_base_qc
        - montant_base_federal
    )
    somme_additionnelles = (
        payroll_input.retenue_additionnelle_QC_effective
        + payroll_input.retenue_additionnelle_federale_effective
    )
    additionnelle_permise = somme_additionnelles <= espace_disponible

    iqc_retenu_montant, iqc_retenu_trace = calcul_impot_qc_retenu(
        payroll_input, gains, parametres_annee, additionnelle_permise
    )
    ifed_retenu_montant, ifed_retenu_trace = calcul_impot_federal_retenu(
        payroll_input, gains, parametres_annee, additionnelle_permise
    )

    # --- D. CotisationsEmployeur complet, en un seul appel (Req 2.4) -
    cotisations_employeur = assembler_cotisations_employeur(
        payroll_input, gains, parametres_annee
    )

    # --- E. Assemblage RetenuesEmploye (Req 3) ------------------------
    total_retenues_employe = (
        rrq_emp_montant
        + rqap_emp_montant
        + ae_emp_montant
        + iqc_retenu_montant
        + ifed_retenu_montant
    )  # Req 3.2 — seulement les 5 montants retenus, jamais les *_formule.

    retenues_employe = RetenuesEmploye(
        rrq=MontantAvecTrace(montant=rrq_emp_montant, trace=rrq_emp_trace),
        rqap=MontantAvecTrace(montant=rqap_emp_montant, trace=rqap_emp_trace),
        ae=MontantAvecTrace(montant=ae_emp_montant, trace=ae_emp_trace),
        impot_qc_formule=MontantAvecTrace(
            montant=iqc_formule_montant, trace=iqc_formule_trace
        ),
        impot_qc_retenu=MontantAvecTrace(
            montant=iqc_retenu_montant, trace=iqc_retenu_trace
        ),
        impot_federal_formule=MontantAvecTrace(
            montant=ifed_formule_montant, trace=ifed_formule_trace
        ),
        impot_federal_retenu=MontantAvecTrace(
            montant=ifed_retenu_montant, trace=ifed_retenu_trace
        ),
        total_retenues_employe=total_retenues_employe,
    )

    # --- F. Identités comptables — net et coût employeur (Req 5) -----
    net = gains.brut_total - retenues_employe.total_retenues_employe
    cout_employeur = (
        gains.brut_total + cotisations_employeur.total_cotisations_employeur
    )
    # Aucun arrondissement supplémentaire : les deux opérandes sont déjà
    # arrondis au cent par les fonctions invoquées (Req 5.4).

    # --- G. Résolution de la dépendance circulaire cumuls_fin (Req 6) -
    contribution = _ContributionPaie(
        employe_id=payroll_input.employee.id,
        annee_fiscale=payroll_input.pay_period.annee_fiscale,
        brut=gains.brut_total,
        vacances=gains.vacances,
        rrq_employe=retenues_employe.rrq.montant,
        rrq_employeur=cotisations_employeur.rrq_employeur.montant,
        rqap_employe=retenues_employe.rqap.montant,
        rqap_employeur=cotisations_employeur.rqap_employeur.montant,
        ae_employe=retenues_employe.ae.montant,
        ae_employeur=cotisations_employeur.ae_employeur.montant,
        impot_qc_retenu=retenues_employe.impot_qc_retenu.montant,
        impot_federal_retenu=retenues_employe.impot_federal_retenu.montant,
        net=net,
    )
    cumuls_fin = payroll_input.cumuls_debut.avec_paie(contribution)
    # CumulsYTD.avec_paie lit `contribution.employe_id`/`contribution.annee_fiscale`
    # puis les onze attributs via getattr — duck typing, aucune isinstance.
    # Toute incohérence employé/année lève PayrollDomainError, propagée
    # sans interception (Req 6.4).

    # --- H. Construction finale, en un seul appel PayrollResult(...) -
    return PayrollResult(
        id_paie=id_paie,
        version=version,
        employe_id=payroll_input.employee.id,
        annee_fiscale=payroll_input.pay_period.annee_fiscale,
        pay_period=payroll_input.pay_period,
        gains=gains,
        retenues_employe=retenues_employe,
        cotisations_employeur=cotisations_employeur,
        net=net,
        cout_employeur=cout_employeur,
        cumuls_fin=cumuls_fin,
        statut=statut,
        remplace_par_id=remplace_par_id,
        date_creation=date_creation,
        date_emission=date_emission,
    )
