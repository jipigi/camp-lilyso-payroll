"""Dérivation de dates, assemblage `PayrollInput`, génération d'`id_paie`.

Spec de référence : ``interface-streamlit`` — tâches 17.1 (`convertir_
numero_en_id`, `deriver_semaines_constituantes`) et 17.2
(`construire_payroll_input`, `generer_id_paie`). Design de référence :
``design.md`` §Components §6 (`formulaire_paie.py` — dérivation de
dates, assemblage, génération d'identifiants), Req 4.7, 6.3, 7, 10.1,
13.3.

Règle 03 (périmètre Camp LilySO) : ces fonctions ne dupliquent aucun
garde-fou de périmètre déjà porté par `models/` — elles se contentent
d'une conversion de forme (`convertir_numero_en_id`), d'une
décomposition mécanique de dates (`deriver_semaines_constituantes`),
d'un assemblage direct de modèles déjà validés
(`construire_payroll_input`) et d'un formatage de chaîne
(`generer_id_paie`). Toute erreur de validation d'origine
(`ValueError`, `UnsupportedPayrollCase`, erreurs de validation de
`WeekSegment`/`PayPeriod`/`PayrollInput`) remonte sans interception,
sans message personnalisé (Req 7.7).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import FrequencePaie
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput


def convertir_numero_en_id(numero: str) -> str:
    """Convertit un numéro d'employé saisi en `id` `EMPnnn` (Req 4.7).

    ``"1"`` → ``"EMP001"``, ``"23"`` → ``"EMP023"``. Fonction pure : zero-
    padding sur 3 chiffres, préfixe `EMP` fixe. `int(numero)` lève
    `ValueError` si `numero` n'est pas un entier — propagée telle quelle,
    pas de garde-fou supplémentaire (règle 03 — pas de nouveau garde-fou
    de périmètre, ce n'est pas un cas hors matrice mais une erreur de
    saisie de forme).
    """
    return f"EMP{int(numero):03d}"


def deriver_semaines_constituantes(
    date_debut: date, date_fin: date
) -> tuple[WeekSegment, WeekSegment]:
    """Dérive les deux `WeekSegment` requis par `PayPeriod` (Req 7.3).

    Première semaine : `[date_debut, date_debut + 6 jours]`. Seconde
    semaine : `[date_debut + 7 jours, date_fin]`. Arithmétique de dates
    pure — aucun calcul fiscal, aucune heure n'est fixée ici (les heures
    sont fournies séparément par l'appelant, voir
    `construire_payroll_input`). Si `date_fin != date_debut + 13 jours`,
    les `WeekSegment`/`PayPeriod` résultants échoueront à la validation
    de contiguïté/couverture déjà portée par `PayPeriod`
    (`_semaines_contigues_et_couvrantes`) — cette fonction ne duplique
    pas ce contrôle, elle se contente de la décomposition mécanique
    (Req 7.4 : l'erreur de validation résultante est celle de `PayPeriod`,
    propagée sans interception par l'appelant).
    """
    premiere = WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )
    seconde = WeekSegment(
        date_debut=date_debut + timedelta(days=7),
        date_fin=date_fin,
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )
    return (premiere, seconde)


def construire_payroll_input(
    *,
    employee: Employee,
    numero_periode: int,
    date_debut: date,
    date_fin: date,
    date_paiement: date,
    annee_fiscale: int,
    nb_periodes_annuelles: int,
    heures_semaine_1: HeuresParSemaine,
    heures_semaine_2: HeuresParSemaine,
    taux_horaire_effectif: Decimal,
    taux_vacances: Decimal,
    jours_feries_manuels: Decimal,
    montant_total_TP1015_3_effectif: Decimal,
    exoneration_TP1015_3_effectif: bool,
    retenue_additionnelle_QC_effective: Decimal,
    montant_total_TD1_effectif: Decimal,
    exoneration_TD1_effective: bool,
    retenue_additionnelle_federale_effective: Decimal,
    cumuls_debut: CumulsYTD,
) -> PayrollInput:
    """Assemble un `PayrollInput` depuis le Formulaire_Paie (Req 6.3, 7.7).

    Signature figée par mots-clés uniquement (aucun argument
    positionnel) : dérive les deux `WeekSegment` de la période via
    `deriver_semaines_constituantes`, construit le `PayPeriod`
    correspondant (`frequence=FrequencePaie.AUX_DEUX_SEMAINES`, seule
    valeur supportée — règle 03) puis le `PayrollInput` complet.

    Aucune interception des exceptions de validation : toute erreur
    levée par `PayPeriod`/`PayrollInput`/`HeuresParSemaine` (contiguïté
    des dates, cas hors matrice via `UnsupportedPayrollCase`, etc.)
    remonte telle quelle à l'appelant (Req 7.7).
    """
    semaine_1, semaine_2 = deriver_semaines_constituantes(date_debut, date_fin)
    pay_period = PayPeriod(
        numero_periode=numero_periode,
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_paiement,
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=nb_periodes_annuelles,
        annee_fiscale=annee_fiscale,
        semaines=(semaine_1, semaine_2),
    )
    return PayrollInput(
        employee=employee,
        pay_period=pay_period,
        heures_par_semaine=(heures_semaine_1, heures_semaine_2),
        taux_horaire_effectif=taux_horaire_effectif,
        taux_vacances=taux_vacances,
        jours_feries_manuels=jours_feries_manuels,
        montant_total_TP1015_3_effectif=montant_total_TP1015_3_effectif,
        exoneration_TP1015_3_effectif=exoneration_TP1015_3_effectif,
        retenue_additionnelle_QC_effective=retenue_additionnelle_QC_effective,
        montant_total_TD1_effectif=montant_total_TD1_effectif,
        exoneration_TD1_effective=exoneration_TD1_effective,
        retenue_additionnelle_federale_effective=(
            retenue_additionnelle_federale_effective
        ),
        cumuls_debut=cumuls_debut,
    )


def generer_id_paie(
    employe_id: str, annee_fiscale: int, numero_periode: int, version: int
) -> str:
    """Génère l'identifiant déterministe d'une paie (Req 10.1, 13.3).

    Format exact : ``f"PAIE-{employe_id}-{annee_fiscale}-
    {numero_periode:02d}-v{version}"``. Fonction pure de formatage,
    sans validation supplémentaire (règle 03).
    """
    return f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:02d}-v{version}"


def valeurs_effectives_depuis_paie(resultat: "PayrollResult") -> dict[str, object]:
    """Reconstruit les valeurs saisies du Formulaire_Paie depuis un
    `PayrollResult` déjà assemblé — bug UI corrigé après livraison
    (pré-remplissage du formulaire pour poursuivre l'édition d'un
    brouillon, ou pour corriger une paie émise).

    **Limitation documentée (décision explicite, discussion
    utilisateur)** : les heures normales/supplémentaires saisies par
    semaine (`PayrollInput.heures_par_semaine`) ne sont **pas**
    persistées par `assembler_paie`/`payroll_engine.net_pay` — seul le
    montant en dollars agrégé (`gains.salaire_regulier`, `gains.
    heures_supplementaires_montant`) est conservé dans `PayrollResult`.
    `PayrollResult.pay_period.semaines` porte les `WeekSegment` avec des
    heures à `Decimal("0")` (dérivées mécaniquement par
    `deriver_semaines_constituantes`, jamais renseignées par le
    moteur) — reconstruire les heures par déduction (montant ÷ taux
    horaire) serait trompeur : impossible de connaître la répartition
    exacte semaine 1/semaine 2 ni la part normale/supplémentaire si le
    seuil hebdomadaire a été dépassé. Cette fonction ne tente donc
    **aucune** reconstruction des heures — les clés `heures_normales_1`,
    `heures_supplementaires_1`, `heures_normales_2`,
    `heures_supplementaires_2` sont volontairement absentes du dict
    retourné ; l'appelant (`app/pages_ui/formulaire_paie.py`) doit
    laisser ces champs à `"0.00"` et informer l'opérateur qu'ils
    doivent être ressaisis.

    Cette fonction ne fait qu'une **projection pure** (lecture directe
    de champs déjà persistés ou de traces déjà produites, règle 02 :
    aucune nouvelle `CalculationTrace`) — les six valeurs TP-1015.3/TD1
    effectives sont reconstituées depuis les `CalculationTrace.entrees`
    des retenues employé (même patron que
    `fiche_employe_detaillee.py::_afficher_valeurs_fiscales_effectives`).

    Retourne un dict directement utilisable pour pré-remplir les
    widgets `st.text_input`/`st.date_input`/`st.checkbox` du
    Formulaire_Paie.
    """
    semaines = resultat.pay_period.semaines
    retenues = resultat.retenues_employe

    exoneration_tp1015_3 = bool(
        int(retenues.impot_qc_retenu.trace.parametres_utilises["exoneration_active"])
    )
    exoneration_td1 = bool(
        int(
            retenues.impot_federal_retenu.trace.parametres_utilises[
                "exoneration_active"
            ]
        )
    )

    return {
        "numero_periode": resultat.pay_period.numero_periode,
        "date_debut": semaines[0].date_debut,
        "date_fin": semaines[-1].date_fin,
        "date_paiement": resultat.pay_period.date_paiement,
        "annee_fiscale": resultat.annee_fiscale,
        "jours_feries_manuels": resultat.gains.jours_feries_manuels,
        "montant_total_TP1015_3_effectif": (
            retenues.impot_qc_formule.trace.entrees["montant_total_tp1015_3"]
        ),
        "exoneration_TP1015_3_effectif": exoneration_tp1015_3,
        "retenue_additionnelle_QC_effective": (
            retenues.impot_qc_retenu.trace.entrees["retenue_additionnelle_qc"]
        ),
        "montant_total_TD1_effectif": (
            retenues.impot_federal_formule.trace.entrees["montant_total_td1"]
        ),
        "exoneration_TD1_effective": exoneration_td1,
        "retenue_additionnelle_federale_effective": (
            retenues.impot_federal_retenu.trace.entrees[
                "retenue_additionnelle_federale"
            ]
        ),
    }
