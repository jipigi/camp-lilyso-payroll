"""Rendu Streamlit — Formulaire_Paie (assemblage, enregistrement, correction).

Spec de référence : ``interface-streamlit`` — tâche 24.1 (Req 6, 7, 8, 9,
10, 12, 13, 16.4, 3.3).
Design de référence : ``design.md`` §Components §5, §6, §7, §8 ;
§Error Handling « Préservation des valeurs saisies ».

Ce module porte l'unique fonction publique :func:`render`, exclusivement
du rendu Streamlit — aucune logique métier nouvelle n'est introduite
ici. Tout calcul ou accès aux annuaires/registre est délégué à
``app/logique_metier/**`` ou directement aux six fonctions du moteur
déjà figées (``construire_payroll_input``, ``generer_id_paie``,
``assembler_paie``, ``inserer_paie``, ``remplacer_paie``,
``lire_cumuls_ytd``), chaque appel étant enveloppé par
``executer_avec_capture`` (Req 16.1, 16.2, 16.3).

Flux couvert :

1. **Sélection de l'année et des paramètres** (Req 6) — l'opérateur
   choisit une année parmi ``lister_annees_disponibles()``,
   ``charger_parametres_fusionnes`` fournit le
   Parametres_Annuels_Fusionnes correspondant ; ``FileNotFoundError``
   traverse sans interception (Req 6.4).
2. **Saisie de la période et des heures** (Req 7) — trois dates de
   période (début, fin, paiement), un ``numero_periode`` borné par
   ``nb_periodes_annuelles``, deux jeux d'heures par semaine (dérivées
   mécaniquement par ``construire_payroll_input``/
   ``deriver_semaines_constituantes``) et un montant de jours fériés
   manuels — tous convertis en ``Decimal`` via chaîne (règle 01).
3. **Pré-remplissage** (Req 8, 9) — les 7 paramètres effectifs
   (``parametres_effectifs_par_defaut``) et les cumuls de début
   (``lire_cumuls_ytd``) sont dérivés automatiquement, jamais saisis
   manuellement pour les onze catégories.
4. **Assemblage** (Req 10) — ``construire_payroll_input`` puis
   ``assembler_paie(...)`` via ``executer_avec_capture``, ``id_paie``
   généré par ``generer_id_paie`` avec ``version=1`` ; affichage complet
   de la Paie_Assemblee avec consultation des ``CalculationTrace`` ;
   aucune persistance automatique.
5. **Enregistrement** (Req 12) — choix explicite
   ``BROUILLON``/``EMISE``, ``saison`` pré-rempli ``"Été
   <annee_fiscale>"`` modifiable, confirmation explicite avant
   ``inserer_paie`` si ``EMISE`` (Req 3.3), confirmation de l'``id_paie``
   inséré, ``ValueError`` affichée sans masquer l'état de saisie.
6. **Action_Corriger** (Req 13) — sélection d'une paie ``EMISE`` par son
   ``id_paie``, pré-remplissage du formulaire de correction,
   réassemblage, ``version = version_ciblee + 1``, confirmation
   explicite avant ``remplacer_paie``.

Chaque widget est lié par un ``key=`` explicite : un retour
``ErreurDomaineAffichable`` ne réinitialise aucune valeur de
``st.session_state``, préservant l'état de saisie de l'opérateur
(Req 16.4).

**Simplification documentée de l'Action_Corriger** : la sélection de la
paie cible se fait par saisie directe de son ``id_paie`` (plutôt que par
une liste déroulante alimentée par ``lire_historique_paie`` sur
plusieurs critères croisés) — l'opérateur consulte l'écran « Historique
et cumuls » (tâche 25.1) pour retrouver cet identifiant avant de revenir
ici. Le pré-remplissage du formulaire de correction utilise
``lire_paie`` pour relire la paie ciblée. Ce choix reste fonctionnel et
complet au sens des Req 13.1 à 13.5 (sélection, pré-remplissage,
réassemblage avec version incrémentée, confirmation explicite,
confirmation du résultat), sans introduire de widget de recherche
supplémentaire hors périmètre de cette tâche.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import streamlit as st

from app.logique_metier.annuaire_employes import lister_employes
from app.logique_metier.dernieres_paies import (
    lire_resumes_paies,
    prochaine_version,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.logique_metier.fiche_employe import parametres_effectifs_par_defaut
from app.logique_metier.formulaire_paie import (
    construire_payroll_input,
    generer_id_paie,
    repartir_heures_sur_semaines,
    valeurs_effectives_depuis_paie,
)
from app.logique_metier.parametres_fiscaux import (
    charger_parametres_fusionnes,
    lister_annees_disponibles,
)
from models.enums import StatutDePaie
from models.payroll_input import PayrollInput
from models.payroll_result import PayrollResult
from payroll_engine.net_pay import assembler_paie

#: Bornes du sélecteur de dates de période/paiement — sans
#: `min_value`/`max_value` explicites, `st.date_input` limite la plage
#: par défaut à environ ±10 ans autour d'aujourd'hui, ce qui empêche de
#: saisir une paie de correction pour une période ancienne (bug corrigé
#: ici, pure ergonomie de saisie — aucune règle fiscale associée).
_DATE_PERIODE_MIN = date(date.today().year - 15, 1, 1)
_DATE_PERIODE_MAX = date(date.today().year + 5, 12, 31)
from payroll_engine.register import (
    chemin_bd_production,
    inserer_paie,
    lire_cumuls_ytd,
    lire_paie,
    remplacer_paie,
)


def _decimal_depuis_saisie(valeur: str) -> Decimal:
    """Convertit une chaîne saisie en ``Decimal`` (règle 01).

    Jamais de passage par ``float`` — ``Decimal(str)`` directement.
    ``InvalidOperation`` (chaîne non numérique) est convertie en
    ``ValueError`` pour rester dans les quatre types interceptés par
    ``executer_avec_capture`` (Req 16.1, 16.2).
    """
    try:
        return Decimal(valeur)
    except InvalidOperation as exc:
        raise ValueError(
            f"Valeur '{valeur}' non convertible en montant décimal."
        ) from exc


def _afficher_trace(libelle: str, montant_avec_trace: object, cle: str) -> None:
    """Affiche un ``MontantAvecTrace`` avec sa ``CalculationTrace`` consultable.

    Consultation sans altération ni reformulation (Req 10.3) — chaque
    champ de la trace est affiché tel que produit par ``assembler_paie``.
    """
    st.write(f"{libelle} : {montant_avec_trace.montant}")
    with st.expander(f"Trace — {libelle}", expanded=False):
        trace = montant_avec_trace.trace
        st.write(f"Source : {trace.source}")
        st.write(f"Année : {trace.annee}")
        st.write(f"Juridiction : {trace.juridiction.value}")
        st.write(f"Section : {trace.section}")
        st.write(f"Paramètres utilisés : {dict(trace.parametres_utilises)}")
        st.write(f"Entrées : {dict(trace.entrees)}")
        st.write(f"Sous-totaux : {dict(trace.sous_totaux)}")
        st.write(f"Mode d'arrondissement : {trace.mode_arrondissement.value}")
        st.write(f"Résultat : {trace.resultat}")


def _afficher_paie_assemblee(resultat: PayrollResult) -> None:
    """Affiche la Paie_Assemblee complète (Req 10.2, 10.3).

    Décomposition des gains, sept retenues employé et leur total, six
    cotisations employeur et leur total, ``net``, ``cout_employeur``,
    ``cumuls_fin`` — chaque montant portant une ``CalculationTrace``
    reste consultable via :func:`_afficher_trace`.
    """
    st.subheader("Résultat de l'assemblage")

    st.write("**Gains**")
    st.write(f"Salaire régulier : {resultat.gains.salaire_regulier}")
    st.write(
        "Heures supplémentaires : "
        f"{resultat.gains.heures_supplementaires_montant}"
    )
    st.write(f"Vacances : {resultat.gains.vacances}")
    st.write(f"Jours fériés manuels : {resultat.gains.jours_feries_manuels}")
    st.write(f"Brut total : {resultat.gains.brut_total}")

    st.write("**Retenues employé**")
    _afficher_trace("RRQ (employé)", resultat.retenues_employe.rrq, "rrq_emp")
    _afficher_trace("RQAP (employé)", resultat.retenues_employe.rqap, "rqap_emp")
    _afficher_trace("AE (employé)", resultat.retenues_employe.ae, "ae_emp")
    _afficher_trace(
        "Impôt QC — formule",
        resultat.retenues_employe.impot_qc_formule,
        "iqc_formule",
    )
    _afficher_trace(
        "Impôt QC — retenu",
        resultat.retenues_employe.impot_qc_retenu,
        "iqc_retenu",
    )
    _afficher_trace(
        "Impôt fédéral — formule",
        resultat.retenues_employe.impot_federal_formule,
        "ifed_formule",
    )
    _afficher_trace(
        "Impôt fédéral — retenu",
        resultat.retenues_employe.impot_federal_retenu,
        "ifed_retenu",
    )
    st.write(
        "Total des retenues employé : "
        f"{resultat.retenues_employe.total_retenues_employe}"
    )

    st.write("**Cotisations employeur**")
    _afficher_trace(
        "RRQ (employeur)", resultat.cotisations_employeur.rrq_employeur, "rrq_emplr"
    )
    _afficher_trace(
        "RQAP (employeur)", resultat.cotisations_employeur.rqap_employeur, "rqap_emplr"
    )
    _afficher_trace(
        "AE (employeur)", resultat.cotisations_employeur.ae_employeur, "ae_emplr"
    )
    _afficher_trace("FSS", resultat.cotisations_employeur.fss, "fss")
    _afficher_trace("CNESST", resultat.cotisations_employeur.cnesst, "cnesst")
    st.write(
        "CNESST en attente de classification : "
        f"{resultat.cotisations_employeur.cnesst_en_attente_classification}"
    )
    _afficher_trace("CNT", resultat.cotisations_employeur.cnt, "cnt")
    st.write(
        "Total des cotisations employeur : "
        f"{resultat.cotisations_employeur.total_cotisations_employeur}"
    )

    st.write("**Identités comptables**")
    st.write(f"Net : {resultat.net}")
    st.write(f"Coût employeur : {resultat.cout_employeur}")

    with st.expander("Cumuls annuels après cette paie", expanded=False):
        st.write(f"Brut : {resultat.cumuls_fin.brut}")
        st.write(f"Vacances : {resultat.cumuls_fin.vacances}")
        st.write(f"RRQ employé : {resultat.cumuls_fin.rrq_employe}")
        st.write(f"RRQ employeur : {resultat.cumuls_fin.rrq_employeur}")
        st.write(f"RQAP employé : {resultat.cumuls_fin.rqap_employe}")
        st.write(f"RQAP employeur : {resultat.cumuls_fin.rqap_employeur}")
        st.write(f"AE employé : {resultat.cumuls_fin.ae_employe}")
        st.write(f"AE employeur : {resultat.cumuls_fin.ae_employeur}")
        st.write(f"Impôt QC retenu : {resultat.cumuls_fin.impot_qc_retenu}")
        st.write(f"Impôt fédéral retenu : {resultat.cumuls_fin.impot_federal_retenu}")
        st.write(f"Net : {resultat.cumuls_fin.net}")


def _section_nouvelle_paie(
    employes: tuple, annees_disponibles: tuple[int, ...]
) -> None:
    """Flux complet Formulaire_Paie pour une nouvelle Paie_Logique (Req 6 à 10, 12).

    Bug UI corrigé après livraison — pré-sélection contextuelle
    (Req 4.5 du Tableau_De_Bord, tableau des paies de la Fiche_Employe_
    Detaillee) : si `st.session_state["fp_employe_id_precharge"]` est
    renseigné (écrit par la page appelante avant `st.switch_page`),
    l'employé et l'année sont pré-sélectionnés en conséquence — jamais
    de ressaisie manuelle du numéro d'employé pour ce cas d'usage.

    Pré-remplissage depuis un brouillon existant (`st.session_state[
    "fp_nouvelle_id_paie_precharge"]`, écrit par le tableau des paies
    de la Fiche_Employe_Detaillee) : jours fériés et paramètres
    TP-1015.3/TD1 effectifs sont restaurés depuis la dernière version
    du brouillon ; les heures par semaine restent à `"0.00"` — non
    récupérables depuis une paie déjà assemblée (voir docstring de
    `app/logique_metier/formulaire_paie.py::valeurs_effectives_depuis_paie`,
    décision explicite : l'opérateur doit les ressaisir).
    """
    st.subheader("Nouvelle paie")

    options_employes = [e.id for e in employes]
    employe_id_precharge = st.session_state.get("fp_employe_id_precharge")
    index_employe_precharge = (
        options_employes.index(employe_id_precharge)
        if employe_id_precharge in options_employes
        else 0
    )
    employe_id = st.selectbox(
        "Employé",
        options_employes,
        index=index_employe_precharge,
        key="fp_nouvelle_employe_id",
    )
    employe = next(e for e in employes if e.id == employe_id)

    # ------------------------------------------------------------------
    # Pré-remplissage depuis un brouillon existant, une seule fois par
    # navigation contextuelle (consommé puis retiré de session_state
    # pour ne pas re-déclencher à chaque rerun de widget).
    # ------------------------------------------------------------------
    valeurs_precharge: dict[str, object] | None = None
    id_paie_brouillon_precharge = st.session_state.pop(
        "fp_nouvelle_id_paie_precharge", None
    )
    if id_paie_brouillon_precharge:
        resultat_brouillon = executer_avec_capture(
            lambda: lire_paie(
                id_paie_brouillon_precharge, chemin_bd=chemin_bd_production()
            )
        )
        if isinstance(resultat_brouillon, ErreurDomaineAffichable):
            st.error(
                f"{resultat_brouillon.type_exception}: "
                f"{resultat_brouillon.message}"
            )
        else:
            paie_brouillon, payroll_input_brouillon = resultat_brouillon
            valeurs_precharge = valeurs_effectives_depuis_paie(
                paie_brouillon, payroll_input_brouillon
            )
            # Message générique ici — le détail sur la restitution ou
            # non des heures (Paie_Post_Correction vs Paie_Pre_
            # Correction) est affiché juste avant les 2 champs d'heures
            # concernés, pour éviter un message dupliqué/contradictoire.
            st.info(
                "Formulaire pré-rempli depuis le brouillon "
                f"'{id_paie_brouillon_precharge}'."
            )

    # ------------------------------------------------------------------
    # Req 6 — sélection de l'année des paramètres fiscaux.
    # ------------------------------------------------------------------
    annee_precharge = (
        valeurs_precharge["annee_fiscale"] if valeurs_precharge else None
    )
    index_annee_precharge = (
        list(annees_disponibles).index(annee_precharge)
        if annee_precharge in annees_disponibles
        else 0
    )
    annee_fiscale = st.selectbox(
        "Année des paramètres fiscaux",
        annees_disponibles,
        index=index_annee_precharge,
        key="fp_nouvelle_annee",
    )

    resultat_params = executer_avec_capture(
        lambda: charger_parametres_fusionnes(annee_fiscale)
    )
    if isinstance(resultat_params, ErreurDomaineAffichable):
        st.error(f"{resultat_params.type_exception}: {resultat_params.message}")
        return
    parametres_annee = resultat_params

    nb_periodes_annuelles = (
        parametres_annee.frequence_paie.nb_periodes_annuelles
        if parametres_annee.frequence_paie is not None
        else 27
    )

    # ------------------------------------------------------------------
    # Req 7 — période de paie et heures.
    # ------------------------------------------------------------------
    numero_periode = st.number_input(
        "Numéro de période",
        min_value=1,
        max_value=nb_periodes_annuelles,
        step=1,
        value=(
            int(valeurs_precharge["numero_periode"]) if valeurs_precharge else 1
        ),
        key="fp_nouvelle_numero_periode",
    )
    date_debut = st.date_input(
        "Date de début de la période",
        value=valeurs_precharge["date_debut"] if valeurs_precharge else None,
        min_value=_DATE_PERIODE_MIN,
        max_value=_DATE_PERIODE_MAX,
        key="fp_nouvelle_date_debut",
    )
    date_fin = st.date_input(
        "Date de fin de la période",
        value=valeurs_precharge["date_fin"] if valeurs_precharge else None,
        min_value=_DATE_PERIODE_MIN,
        max_value=_DATE_PERIODE_MAX,
        key="fp_nouvelle_date_fin",
    )
    date_paiement = st.date_input(
        "Date de paiement",
        value=valeurs_precharge["date_paiement"] if valeurs_precharge else None,
        min_value=_DATE_PERIODE_MIN,
        max_value=_DATE_PERIODE_MAX,
        key="fp_nouvelle_date_paiement",
    )

    if valeurs_precharge is not None:
        if (
            "total_heures_normales" in valeurs_precharge
            and "total_heures_supplementaires" in valeurs_precharge
        ):
            # Paie_Post_Correction (design §Glossary) — le PayrollInput
            # d'origine a été persisté (colonne payload_input_json non
            # NULL) : les 2 totaux d'heures sont restitués sans
            # ressaisie (Req 2.4, design §Correctness Properties,
            # Property 2).
            st.info(
                "Heures d'origine restituées depuis le brouillon — "
                "aucune ressaisie nécessaire."
            )
        else:
            # Paie_Pre_Correction (design §Glossary) — le PayrollInput
            # d'origine n'a pas été persisté, les 2 totaux d'heures
            # restent non récupérables (Req 3.4, préservation du
            # comportement antérieur à cette correction).
            st.warning(
                "Heures par semaine non récupérables depuis le brouillon — "
                "veuillez les ressaisir ci-dessous."
            )
    st.write("Heures — période complète (2 semaines)")
    total_heures_normales = st.text_input(
        "Total heures normales (période)",
        value=(
            str(valeurs_precharge.get("total_heures_normales", "0.00"))
            if valeurs_precharge
            else "0.00"
        ),
        key="fp_nouvelle_total_hn",
    )
    total_heures_supplementaires = st.text_input(
        "Total heures supplémentaires (période)",
        value=(
            str(valeurs_precharge.get("total_heures_supplementaires", "0.00"))
            if valeurs_precharge
            else "0.00"
        ),
        key="fp_nouvelle_total_hs",
    )

    jours_feries_manuels = st.text_input(
        "Jours fériés manuels ($)",
        value=(
            str(valeurs_precharge["jours_feries_manuels"])
            if valeurs_precharge
            else "0.00"
        ),
        key="fp_nouvelle_jours_feries",
    )

    # ------------------------------------------------------------------
    # Req 8 — pré-remplissage des 7 paramètres effectifs.
    # ------------------------------------------------------------------
    parametres_effectifs = parametres_effectifs_par_defaut(employe)
    st.write("Paramètres effectifs (pré-remplis depuis la Fiche_Employe, ajustables)")
    taux_horaire_effectif = st.text_input(
        "Taux horaire effectif",
        value=str(parametres_effectifs["taux_horaire_effectif"]),
        key="fp_nouvelle_taux_horaire",
    )
    taux_vacances_options = ["0.04", "0.06"]
    taux_vacances_index = taux_vacances_options.index(
        str(parametres_effectifs["taux_vacances"])
    ) if str(parametres_effectifs["taux_vacances"]) in taux_vacances_options else 0
    taux_vacances = st.selectbox(
        "Taux de vacances",
        taux_vacances_options,
        index=taux_vacances_index,
        key="fp_nouvelle_taux_vacances",
    )
    montant_tp1015_3 = st.text_input(
        "Montant total TP-1015.3 effectif",
        value=str(
            valeurs_precharge["montant_total_TP1015_3_effectif"]
            if valeurs_precharge
            else parametres_effectifs["montant_total_TP1015_3_effectif"]
        ),
        key="fp_nouvelle_montant_tp",
    )
    exoneration_tp1015_3 = st.checkbox(
        "Exonération TP-1015.3",
        value=(
            valeurs_precharge["exoneration_TP1015_3_effectif"]
            if valeurs_precharge
            else parametres_effectifs["exoneration_TP1015_3_effectif"]
        ),
        key="fp_nouvelle_exo_tp",
    )
    retenue_qc = st.text_input(
        "Retenue additionnelle QC effective",
        value=str(
            valeurs_precharge["retenue_additionnelle_QC_effective"]
            if valeurs_precharge
            else parametres_effectifs["retenue_additionnelle_QC_effective"]
        ),
        key="fp_nouvelle_retenue_qc",
    )
    montant_td1 = st.text_input(
        "Montant total TD1 effectif",
        value=str(
            valeurs_precharge["montant_total_TD1_effectif"]
            if valeurs_precharge
            else parametres_effectifs["montant_total_TD1_effectif"]
        ),
        key="fp_nouvelle_montant_td1",
    )
    exoneration_td1 = st.checkbox(
        "Exonération TD1",
        value=(
            valeurs_precharge["exoneration_TD1_effective"]
            if valeurs_precharge
            else parametres_effectifs["exoneration_TD1_effective"]
        ),
        key="fp_nouvelle_exo_td1",
    )
    retenue_federale = st.text_input(
        "Retenue additionnelle fédérale effective",
        value=str(
            valeurs_precharge["retenue_additionnelle_federale_effective"]
            if valeurs_precharge
            else parametres_effectifs["retenue_additionnelle_federale_effective"]
        ),
        key="fp_nouvelle_retenue_fed",
    )

    # ------------------------------------------------------------------
    # Req 9 — pré-remplissage automatique des cumuls_debut.
    # ------------------------------------------------------------------
    resultat_cumuls = executer_avec_capture(
        lambda: lire_cumuls_ytd(
            employe_id, annee_fiscale, chemin_bd=chemin_bd_production()
        )
    )
    if isinstance(resultat_cumuls, ErreurDomaineAffichable):
        st.error(f"{resultat_cumuls.type_exception}: {resultat_cumuls.message}")
        return
    cumuls_debut = resultat_cumuls

    # ------------------------------------------------------------------
    # Req 10 — assemblage de la paie.
    # ------------------------------------------------------------------
    if st.button("Assembler la paie", type="primary", key="fp_nouvelle_assembler"):
        # Conservé par `_assembler()` (nonlocal) pour transmission à
        # `st.session_state["fp_nouvelle_payroll_input_assemble"]" —
        # préparation pour la tâche 6.5 (persistance du PayrollInput via
        # `inserer_paie`), `assembler_paie` ne renvoie que le
        # `PayrollResult` (contrat moteur inchangé, règle 02).
        payroll_input_construit: PayrollInput | None = None

        def _assembler() -> PayrollResult:
            nonlocal payroll_input_construit
            heures_semaine_1, heures_semaine_2 = repartir_heures_sur_semaines(
                total_heures_normales=_decimal_depuis_saisie(total_heures_normales),
                total_heures_supplementaires=_decimal_depuis_saisie(
                    total_heures_supplementaires
                ),
            )
            payroll_input = construire_payroll_input(
                employee=employe,
                numero_periode=int(numero_periode),
                date_debut=date_debut,
                date_fin=date_fin,
                date_paiement=date_paiement,
                annee_fiscale=annee_fiscale,
                nb_periodes_annuelles=nb_periodes_annuelles,
                heures_semaine_1=heures_semaine_1,
                heures_semaine_2=heures_semaine_2,
                taux_horaire_effectif=_decimal_depuis_saisie(taux_horaire_effectif),
                taux_vacances=_decimal_depuis_saisie(taux_vacances),
                jours_feries_manuels=_decimal_depuis_saisie(jours_feries_manuels),
                montant_total_TP1015_3_effectif=_decimal_depuis_saisie(
                    montant_tp1015_3
                ),
                exoneration_TP1015_3_effectif=exoneration_tp1015_3,
                retenue_additionnelle_QC_effective=_decimal_depuis_saisie(
                    retenue_qc
                ),
                montant_total_TD1_effectif=_decimal_depuis_saisie(montant_td1),
                exoneration_TD1_effective=exoneration_td1,
                retenue_additionnelle_federale_effective=_decimal_depuis_saisie(
                    retenue_federale
                ),
                cumuls_debut=cumuls_debut,
            )
            payroll_input_construit = payroll_input
            # Bug UI corrigé après livraison — détermination de la
            # version à utiliser : `remplacer_paie` (moteur) exige que
            # la paie remplacée soit EMISE (Req 13.2 du moteur), donc
            # toute poursuite de saisie d'un brouillon insère une
            # NOUVELLE version via `inserer_paie` (append-only) plutôt
            # que de remplacer l'ancienne ligne — `prochaine_version`
            # détermine ce numéro à partir des paies déjà existantes
            # pour ce `numero_periode` (1 si aucune, sinon max + 1).
            resultat_resumes_existants = executer_avec_capture(
                lambda: lire_resumes_paies(
                    employe_id, chemin_bd=chemin_bd_production()
                )
            )
            resumes_existants = (
                ()
                if isinstance(resultat_resumes_existants, ErreurDomaineAffichable)
                else resultat_resumes_existants
            )
            version = prochaine_version(resumes_existants, int(numero_periode))
            id_paie = generer_id_paie(
                employe_id, annee_fiscale, int(numero_periode), version
            )
            return assembler_paie(
                payroll_input,
                parametres_annee,
                id_paie,
                version,
                StatutDePaie.BROUILLON,
                datetime.now(),
            )

        resultat_assemblage = executer_avec_capture(_assembler)
        if isinstance(resultat_assemblage, ErreurDomaineAffichable):
            st.error(
                f"{resultat_assemblage.type_exception}: {resultat_assemblage.message}"
            )
        else:
            # Req 10.5 — aucune persistance automatique : le résultat est
            # conservé en session pour l'étape d'enregistrement explicite.
            st.session_state["fp_nouvelle_paie_assemblee"] = resultat_assemblage
            # Conservation du PayrollInput assemblé — préparation pour
            # la tâche 6.5 (transmission à `inserer_paie(...,
            # payroll_input=...)`, design §Fix Implementation point 5).
            st.session_state[
                "fp_nouvelle_payroll_input_assemble"
            ] = payroll_input_construit
            st.success("Paie assemblée avec succès.")

    paie_assemblee = st.session_state.get("fp_nouvelle_paie_assemblee")
    if paie_assemblee is not None:
        _afficher_paie_assemblee(paie_assemblee)
        _section_enregistrement(
            paie_assemblee, annee_fiscale, cle_prefixe="fp_nouvelle"
        )


def _section_enregistrement(
    paie_assemblee: PayrollResult, annee_fiscale: int, *, cle_prefixe: str
) -> None:
    """Choix BROUILLON/EMISE, saison, confirmation, ``inserer_paie`` (Req 12, 3.3).

    Depuis le bugfix `heures-periode-et-persistance-brouillon` (Req 2.3,
    2.4, design §Correctness Properties Property 2) : le `PayrollInput`
    assemblé, conservé en session sous
    `f"{cle_prefixe}_payroll_input_assemble"` (tâche 5.2), est transmis
    à `inserer_paie` pour persistance dans `payload_input_json`.
    """
    payroll_input_assemble = st.session_state.get(
        f"{cle_prefixe}_payroll_input_assemble"
    )
    st.write("**Enregistrement**")
    statut_choisi = st.radio(
        "Statut", ["BROUILLON", "EMISE"], key=f"{cle_prefixe}_statut_choisi"
    )
    saison = st.text_input(
        "Saison", value=f"Été {annee_fiscale}", key=f"{cle_prefixe}_saison"
    )

    confirmation = True
    if statut_choisi == "EMISE":
        # Req 3.3 — confirmation explicite avant toute action irréversible.
        confirmation = st.checkbox(
            "Je confirme vouloir émettre cette paie de façon définitive.",
            key=f"{cle_prefixe}_confirmation_emission",
        )

    if st.button(
        "Enregistrer la paie", type="primary", key=f"{cle_prefixe}_enregistrer"
    ):
        if not confirmation:
            st.warning(
                "Confirmation requise avant d'émettre une paie de façon "
                "définitive."
            )
            return

        statut_final = (
            StatutDePaie.EMISE if statut_choisi == "EMISE" else StatutDePaie.BROUILLON
        )
        date_emission = datetime.now() if statut_final == StatutDePaie.EMISE else None

        def _inserer() -> str:
            # Bug UI corrigé après livraison : `id_paie`/`version` sont
            # figés au moment de l'assemblage (bouton « Assembler la
            # paie »), avant tout choix de statut. Si l'opérateur change
            # ensuite le statut (BROUILLON -> EMISE) sans réassembler,
            # `paie_assemblee.id_paie` correspond déjà à une ligne
            # insérée précédemment (ex. le brouillon lui-même) — le
            # registre étant strictement append-only (aucune
            # modification en place, traçabilité), une seconde
            # insertion avec le même `id_paie` est refusée par
            # `inserer_paie` (Req 11.6). Détection automatique : si
            # `id_paie` existe déjà, une nouvelle version est régénérée
            # ici (même mécanisme que `_assembler()` ci-dessus,
            # `prochaine_version`) avant l'insertion, sans action
            # supplémentaire requise de l'opérateur.
            resultat_existant = executer_avec_capture(
                lambda: lire_paie(
                    paie_assemblee.id_paie, chemin_bd=chemin_bd_production()
                )
            )
            if isinstance(resultat_existant, ErreurDomaineAffichable):
                # `KeyError` attendue — `id_paie` n'existe pas encore,
                # aucune régénération nécessaire.
                id_paie_final = paie_assemblee.id_paie
                version_finale = paie_assemblee.version
            else:
                resultat_resumes = executer_avec_capture(
                    lambda: lire_resumes_paies(
                        paie_assemblee.employe_id, chemin_bd=chemin_bd_production()
                    )
                )
                resumes = (
                    ()
                    if isinstance(resultat_resumes, ErreurDomaineAffichable)
                    else resultat_resumes
                )
                version_finale = prochaine_version(
                    resumes, paie_assemblee.pay_period.numero_periode
                )
                id_paie_final = generer_id_paie(
                    paie_assemblee.employe_id,
                    paie_assemblee.annee_fiscale,
                    paie_assemblee.pay_period.numero_periode,
                    version_finale,
                )

            paie_a_inserer = PayrollResult(
                **{
                    **paie_assemblee.model_dump(),
                    "id_paie": id_paie_final,
                    "version": version_finale,
                    "statut": statut_final,
                    "date_emission": date_emission,
                }
            )
            inserer_paie(
                paie_a_inserer,
                saison,
                payroll_input=payroll_input_assemble,
                chemin_bd=chemin_bd_production(),
            )
            return paie_a_inserer.id_paie

        resultat_insertion = executer_avec_capture(_inserer)
        if isinstance(resultat_insertion, ErreurDomaineAffichable):
            # Req 12.5 — ValueError affichée sans masquer l'état de saisie
            # (aucune clé de session_state n'est réinitialisée ici).
            st.error(
                f"{resultat_insertion.type_exception}: {resultat_insertion.message}"
            )
        else:
            # Req 12.4 — confirmation explicite de l'id_paie inséré.
            st.success(
                f"Paie '{resultat_insertion}' enregistrée avec le statut "
                f"{statut_final.value}."
            )


def _section_corriger_paie(employes: tuple, annees_disponibles: tuple[int, ...]) -> None:
    """Action_Corriger — annulation-remplacement d'une paie EMISE (Req 13).

    Simplification documentée (voir docstring de module) : la paie
    cible est identifiée par saisie directe de son ``id_paie`` (recueilli
    au préalable depuis l'écran « Historique et cumuls annuels »), relue via
    ``lire_paie``, puis pré-remplit un formulaire de réassemblage
    identique au flux de nouvelle paie. ``version = version_ciblee + 1``
    (Req 13.3) et confirmation explicite avant ``remplacer_paie``
    (Req 3.3, 13.4).

    Bug UI corrigé après livraison : si `st.session_state[
    "fp_corriger_ancien_id_precharge"]` est renseigné (écrit par
    `bulletin_paie.py` avant `st.switch_page`, bouton « Corriger cette
    paie »), l'``id_paie`` est pré-rempli — jamais de ressaisie
    manuelle dans ce cas.
    """
    st.subheader("Corriger une paie émise")

    ancien_id_precharge = st.session_state.pop(
        "fp_corriger_ancien_id_precharge", ""
    )
    ancien_id = st.text_input(
        "id_paie de la paie EMISE à corriger",
        value=ancien_id_precharge,
        key="fp_corriger_ancien_id",
    )
    if not ancien_id:
        st.info(
            "Saisissez l'id_paie d'une paie EMISE (voir Historique et "
            "cumuls annuels)."
        )
        return

    resultat_ancienne_paie = executer_avec_capture(
        lambda: lire_paie(ancien_id, chemin_bd=chemin_bd_production())
    )
    if isinstance(resultat_ancienne_paie, ErreurDomaineAffichable):
        st.error(
            f"{resultat_ancienne_paie.type_exception}: "
            f"{resultat_ancienne_paie.message}"
        )
        return
    # Le PayrollInput de la paie EMISE ciblée n'est pas utilisé pour
    # pré-remplir les heures dans ce flux (design §Fix Implementation) —
    # les heures du formulaire de correction restent à "0.00" par
    # défaut.
    ancienne_paie, _ = resultat_ancienne_paie

    if ancienne_paie.statut != StatutDePaie.EMISE:
        st.error(
            f"La paie '{ancien_id}' a le statut "
            f"{ancienne_paie.statut.value} — seule une paie EMISE peut "
            "être corrigée (Req 13.1)."
        )
        return

    st.write(
        f"Paie ciblée : employé={ancienne_paie.employe_id} | "
        f"année fiscale={ancienne_paie.annee_fiscale} | "
        f"numéro de période={ancienne_paie.pay_period.numero_periode} | "
        f"version actuelle={ancienne_paie.version}"
    )

    try:
        employe_ciblee = next(
            e for e in employes if e.id == ancienne_paie.employe_id
        )
    except StopIteration:
        st.error(
            f"Employé '{ancienne_paie.employe_id}' absent de l'Annuaire_"
            "Employes — impossible de pré-remplir le formulaire de "
            "correction."
        )
        return

    if ancienne_paie.annee_fiscale not in annees_disponibles:
        st.error(
            f"Aucun paramètre fiscal disponible pour l'année "
            f"{ancienne_paie.annee_fiscale}."
        )
        return

    resultat_params = executer_avec_capture(
        lambda: charger_parametres_fusionnes(ancienne_paie.annee_fiscale)
    )
    if isinstance(resultat_params, ErreurDomaineAffichable):
        st.error(f"{resultat_params.type_exception}: {resultat_params.message}")
        return
    parametres_annee = resultat_params
    nb_periodes_annuelles = (
        parametres_annee.frequence_paie.nb_periodes_annuelles
        if parametres_annee.frequence_paie is not None
        else 27
    )

    # ------------------------------------------------------------------
    # Req 13.2 — pré-remplissage du formulaire depuis la paie ciblée.
    # ------------------------------------------------------------------
    semaines = ancienne_paie.pay_period.semaines
    date_debut = st.date_input(
        "Date de début de la période",
        value=semaines[0].date_debut,
        min_value=_DATE_PERIODE_MIN,
        max_value=_DATE_PERIODE_MAX,
        key="fp_corriger_date_debut",
    )
    date_fin = st.date_input(
        "Date de fin de la période",
        value=semaines[-1].date_fin,
        min_value=_DATE_PERIODE_MIN,
        max_value=_DATE_PERIODE_MAX,
        key="fp_corriger_date_fin",
    )
    date_paiement = st.date_input(
        "Date de paiement",
        value=ancienne_paie.pay_period.date_paiement,
        min_value=_DATE_PERIODE_MIN,
        max_value=_DATE_PERIODE_MAX,
        key="fp_corriger_date_paiement",
    )

    st.write("Heures — période complète (2 semaines)")
    total_heures_normales = st.text_input(
        "Total heures normales (période)", value="0.00", key="fp_corriger_total_hn"
    )
    total_heures_supplementaires = st.text_input(
        "Total heures supplémentaires (période)",
        value="0.00",
        key="fp_corriger_total_hs",
    )
    jours_feries_manuels = st.text_input(
        "Jours fériés manuels ($)", value="0.00", key="fp_corriger_jours_feries"
    )

    taux_horaire_effectif = st.text_input(
        "Taux horaire effectif",
        value=str(employe_ciblee.taux_horaire_base),
        key="fp_corriger_taux_horaire",
    )
    taux_vacances_options = ["0.04", "0.06"]
    taux_vacances_index = taux_vacances_options.index(
        str(employe_ciblee.taux_indemnite_vacances)
    ) if str(employe_ciblee.taux_indemnite_vacances) in taux_vacances_options else 0
    taux_vacances = st.selectbox(
        "Taux de vacances",
        taux_vacances_options,
        index=taux_vacances_index,
        key="fp_corriger_taux_vacances",
    )
    montant_tp1015_3 = st.text_input(
        "Montant total TP-1015.3 effectif",
        value=str(employe_ciblee.montant_total_TP1015_3),
        key="fp_corriger_montant_tp",
    )
    exoneration_tp1015_3 = st.checkbox(
        "Exonération TP-1015.3",
        value=employe_ciblee.exoneration_TP1015_3,
        key="fp_corriger_exo_tp",
    )
    retenue_qc = st.text_input(
        "Retenue additionnelle QC effective",
        value=str(employe_ciblee.retenue_additionnelle_QC),
        key="fp_corriger_retenue_qc",
    )
    montant_td1 = st.text_input(
        "Montant total TD1 effectif",
        value=str(employe_ciblee.montant_total_TD1),
        key="fp_corriger_montant_td1",
    )
    exoneration_td1 = st.checkbox(
        "Exonération TD1",
        value=employe_ciblee.exoneration_TD1,
        key="fp_corriger_exo_td1",
    )
    retenue_federale = st.text_input(
        "Retenue additionnelle fédérale effective",
        value=str(employe_ciblee.retenue_additionnelle_federale),
        key="fp_corriger_retenue_fed",
    )

    resultat_cumuls = executer_avec_capture(
        lambda: lire_cumuls_ytd(
            ancienne_paie.employe_id,
            ancienne_paie.annee_fiscale,
            chemin_bd=chemin_bd_production(),
        )
    )
    if isinstance(resultat_cumuls, ErreurDomaineAffichable):
        st.error(f"{resultat_cumuls.type_exception}: {resultat_cumuls.message}")
        return
    cumuls_debut = resultat_cumuls

    if st.button("Réassembler la paie", type="primary", key="fp_corriger_assembler"):
        # Conservé par `_reassembler()` (nonlocal) pour transmission à
        # `st.session_state["fp_corriger_payroll_input_reassemble"]" —
        # préparation pour la tâche 6.5 (persistance du PayrollInput via
        # `remplacer_paie`), `assembler_paie` ne renvoie que le
        # `PayrollResult` (contrat moteur inchangé, règle 02).
        payroll_input_construit: PayrollInput | None = None

        def _reassembler() -> PayrollResult:
            nonlocal payroll_input_construit
            heures_semaine_1, heures_semaine_2 = repartir_heures_sur_semaines(
                total_heures_normales=_decimal_depuis_saisie(total_heures_normales),
                total_heures_supplementaires=_decimal_depuis_saisie(
                    total_heures_supplementaires
                ),
            )
            payroll_input = construire_payroll_input(
                employee=employe_ciblee,
                numero_periode=ancienne_paie.pay_period.numero_periode,
                date_debut=date_debut,
                date_fin=date_fin,
                date_paiement=date_paiement,
                annee_fiscale=ancienne_paie.annee_fiscale,
                nb_periodes_annuelles=nb_periodes_annuelles,
                heures_semaine_1=heures_semaine_1,
                heures_semaine_2=heures_semaine_2,
                taux_horaire_effectif=_decimal_depuis_saisie(taux_horaire_effectif),
                taux_vacances=_decimal_depuis_saisie(taux_vacances),
                jours_feries_manuels=_decimal_depuis_saisie(jours_feries_manuels),
                montant_total_TP1015_3_effectif=_decimal_depuis_saisie(
                    montant_tp1015_3
                ),
                exoneration_TP1015_3_effectif=exoneration_tp1015_3,
                retenue_additionnelle_QC_effective=_decimal_depuis_saisie(
                    retenue_qc
                ),
                montant_total_TD1_effectif=_decimal_depuis_saisie(montant_td1),
                exoneration_TD1_effective=exoneration_td1,
                retenue_additionnelle_federale_effective=_decimal_depuis_saisie(
                    retenue_federale
                ),
                cumuls_debut=cumuls_debut,
            )
            payroll_input_construit = payroll_input
            # Req 13.3 — version = version_ciblee + 1, id_paie regénéré.
            nouvelle_version = ancienne_paie.version + 1
            id_paie = generer_id_paie(
                ancienne_paie.employe_id,
                ancienne_paie.annee_fiscale,
                ancienne_paie.pay_period.numero_periode,
                nouvelle_version,
            )
            return assembler_paie(
                payroll_input,
                parametres_annee,
                id_paie,
                nouvelle_version,
                StatutDePaie.BROUILLON,
                datetime.now(),
            )

        resultat_reassemblage = executer_avec_capture(_reassembler)
        if isinstance(resultat_reassemblage, ErreurDomaineAffichable):
            st.error(
                f"{resultat_reassemblage.type_exception}: "
                f"{resultat_reassemblage.message}"
            )
        else:
            st.session_state["fp_corriger_paie_reassemblee"] = resultat_reassemblage
            st.session_state["fp_corriger_ancien_id_cible"] = ancien_id
            # Conservation du PayrollInput réassemblé — préparation pour
            # la tâche 6.5 (transmission à `remplacer_paie(...,
            # nouveau_payroll_input=...)`, design §Fix Implementation
            # point 5).
            st.session_state[
                "fp_corriger_payroll_input_reassemble"
            ] = payroll_input_construit
            st.success("Paie réassemblée avec succès.")

    paie_reassemblee = st.session_state.get("fp_corriger_paie_reassemblee")
    if paie_reassemblee is not None:
        _afficher_paie_assemblee(paie_reassemblee)

        st.write("**Correction**")
        statut_choisi = st.radio(
            "Statut de la nouvelle version",
            ["BROUILLON", "EMISE"],
            key="fp_corriger_statut_choisi",
        )
        saison = st.text_input(
            "Saison",
            value=f"Été {ancienne_paie.annee_fiscale}",
            key="fp_corriger_saison",
        )
        # Req 3.3 — confirmation explicite avant remplacer_paie (action
        # irréversible d'annulation-remplacement).
        confirmation = st.checkbox(
            "Je confirme vouloir remplacer définitivement la paie "
            f"'{ancien_id}' par cette nouvelle version.",
            key="fp_corriger_confirmation",
        )

        if st.button(
            "Corriger cette paie", type="primary", key="fp_corriger_remplacer"
        ):
            if not confirmation:
                st.warning(
                    "Confirmation requise avant de remplacer définitivement "
                    "une paie émise."
                )
                return

            statut_final = (
                StatutDePaie.EMISE
                if statut_choisi == "EMISE"
                else StatutDePaie.BROUILLON
            )
            date_emission = (
                datetime.now() if statut_final == StatutDePaie.EMISE else None
            )
            nouveau_resultat = PayrollResult(
                **{
                    **paie_reassemblee.model_dump(),
                    "statut": statut_final,
                    "date_emission": date_emission,
                }
            )

            nouveau_payroll_input = st.session_state.get(
                "fp_corriger_payroll_input_reassemble"
            )

            def _remplacer() -> str:
                remplacer_paie(
                    ancien_id,
                    nouveau_resultat,
                    saison,
                    nouveau_payroll_input=nouveau_payroll_input,
                    chemin_bd=chemin_bd_production(),
                )
                return nouveau_resultat.id_paie

            resultat_remplacement = executer_avec_capture(_remplacer)
            if isinstance(resultat_remplacement, ErreurDomaineAffichable):
                st.error(
                    f"{resultat_remplacement.type_exception}: "
                    f"{resultat_remplacement.message}"
                )
            else:
                # Req 13.4 — confirmation explicite de l'ancien et du
                # nouvel id_paie.
                st.success(
                    f"Paie '{ancien_id}' marquée REMPLACE_PAR — nouvelle "
                    f"paie '{resultat_remplacement}' insérée."
                )


def render() -> None:
    """Rendu de la page « Formulaire de paie » (Req 6 à 10, 12, 13, 16.4).

    Bug UI corrigé après livraison — remplacement de ``st.tabs`` (qui ne
    supporte aucune sélection programmatique d'onglet, limitation
    Streamlit confirmée) par un dispatch de mode piloté par
    ``st.session_state`` : le mode « Nouvelle paie » (assemblage +
    enregistrement, y compris pré-remplissage depuis un brouillon
    existant) reste **toujours le mode par défaut** — décision explicite
    (discussion utilisateur) : aucun bouton de bascule manuelle vers le
    mode « Corriger une paie émise ». Ce dernier n'est activé que
    lorsque la page est atteinte avec une intention de correction
    explicite (clé ``st.session_state["fp_corriger_ancien_id_precharge"]``
    renseignée par `bulletin_paie.py`, bouton « Corriger cette paie »).

    Chaque widget est lié par un ``key=`` explicite — un retour
    ``ErreurDomaineAffichable`` ne réinitialise aucune valeur de
    ``st.session_state`` (Req 16.4).
    """
    st.header("Formulaire de paie")

    resultat_employes = executer_avec_capture(lambda: lister_employes())
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    if not employes:
        st.info("Aucun employé dans l'annuaire. Ajoutez un employé pour commencer.")
        return

    annees_disponibles = lister_annees_disponibles()
    if not annees_disponibles:
        st.error(
            "Aucune année de paramètres fiscaux disponible sous "
            "parameters/<AAAA>/."
        )
        return

    # Mode « Corriger » activé uniquement si une intention explicite de
    # correction a été transmise par la page appelante — jamais par
    # défaut, jamais via une bascule manuelle (décision explicite).
    mode_correction = bool(
        st.session_state.get("fp_corriger_ancien_id_precharge")
    )

    if mode_correction:
        _section_corriger_paie(employes, annees_disponibles)
    else:
        _section_nouvelle_paie(employes, annees_disponibles)
