"""Bulletin_De_Paie — page de consultation en lecture seule d'une paie.

Reproduit visuellement le gabarit officiel
`intake/ressources/../fiches-paie/Bulletin-paie-gabarit.xlsx` (hors
dépôt, règle 04) : identification employé/employeur, période, section
salaire détaillée (heures normales/supplémentaires × taux, indemnités,
brut), déductions fiscales (impôt fédéral/provincial, RRQ, AE, RQAP,
total, NET), cotisations employeur pour information (RRQ, AE, RQAP,
CNESST avec son taux, FSS, total).

Accès exclusivement par navigation contextuelle — jamais de ressaisie
d'``id_paie`` par l'opérateur (décision explicite, discussion
utilisateur) : l'``id_paie`` cible est lu depuis
`st.session_state["bulletin_id_paie_cible"]`, écrit par la page
appelante (Tableau_De_Bord, Fiche_Employe_Detaillee) avant
`st.switch_page`. Si la clé est absente (accès direct par URL ou clic
sur l'élément de navigation latérale), un message explicite invite
l'opérateur à naviguer depuis une fiche employé plutôt que d'afficher
une page vide silencieusement.

Bouton « Corriger cette paie » entre le titre et le contenu (haut de
page) — visible uniquement si la paie est `EMISE` (seul statut que
`payroll_engine.register.remplacer_paie` accepte de remplacer, Req 13.2
du moteur) ; route vers le Formulaire_Paie en mode correction, avec
l'``id_paie`` déjà chargé (jamais de ressaisie).

Couche de rendu (`app/pages_ui/`) : ce module **peut** importer
``streamlit`` (Req 1.1, 1.3 ne s'appliquent qu'à
`app/logique_metier/**`).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par `lire_paie` est enveloppée par `executer_avec_capture` — aucun
`except Exception`/`except BaseException` générique n'est présent dans
ce module (Req 16.1, 16.3).

Règle 02 (traçabilité) : ce module n'invente aucune nouvelle
`CalculationTrace` — le taux CNESST affiché est lu directement depuis
`CalculationTrace.parametres_utilises["taux_total_cnesst"]` déjà
produite par `assembler_paie`. Les deux « taux horaire » affichés
(heures normales, heures supplémentaires) sont des **calculs d'affichage
purs** (montant ÷ heures, division inverse de la multiplication faite
par `payroll_engine.gains_bruts.calcul_gains`), pas une nouvelle règle
fiscale — si le nombre d'heures d'une catégorie est nul, le taux
correspondant est affiché comme absent plutôt que de diviser par zéro.

Champs du gabarit non disponibles dans les modèles du moteur, résolus
par décision explicite (discussion utilisateur) :

- **Informations employeur** (nom, adresse, ville, code postal, numéro
  NQE) — constantes fixes de l'organisation, centralisées dans
  `app/config_employeur.py` plutôt que codées en dur ici.
- **NAS de l'employé** — lu depuis `FicheCoordonnees.nas`
  (`app/logique_metier/annuaire_coordonnees.py`), jamais transmis au
  moteur de calcul (règle 04) ; affiché tel quel s'il existe, sinon
  indication explicite d'absence.
- **Prénom et Nom séparés** — décision explicite : `Employee.
  nom_affichage` reste affiché sur une seule ligne, sous le libellé
  « Nom complet » (pas de séparation Prénom/Nom, contrairement au
  gabarit).
"""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from app.config_employeur import CONFIG_EMPLOYEUR
from app.logique_metier.annuaire_coordonnees import lire_coordonnees
from app.logique_metier.annuaire_employes import lire_employe
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from models.enums import StatutDePaie
from models.payroll_result import MontantAvecTrace, PayrollResult
from payroll_engine.register import chemin_bd_production, lire_paie

#: Clé de `st.session_state` portant l'``id_paie`` de la paie à
#: afficher — écrite par la page appelante avant `st.switch_page`,
#: jamais ressaisie par l'opérateur sur cette page.
CLE_ID_PAIE_CIBLE = "bulletin_id_paie_cible"


def _taux_horaire_affiche(montant: Decimal, heures: Decimal) -> str:
    """Calcul d'affichage pur : ``montant / heures``, formaté à 2 décimales.

    Division inverse de la multiplication faite par
    `payroll_engine.gains_bruts.calcul_gains` (règle 02 : aucune
    nouvelle règle fiscale, uniquement la reconstruction d'une valeur
    déjà appliquée). Retourne un tiret cadratin si ``heures == 0``
    (aucune division par zéro, aucun taux à afficher pour une
    catégorie d'heures non travaillée).
    """
    if heures == Decimal("0"):
        return "—"
    return str((montant / heures).quantize(Decimal("0.01")))


def _afficher_trace_montant(libelle: str, montant_avec_trace: MontantAvecTrace) -> None:
    """Affiche un montant avec sa trace consultable (règle 02).

    Même patron que `formulaire_paie.py::_afficher_trace` — consultation
    sans altération ni reformulation de la trace produite par
    `assembler_paie`.
    """
    trace = montant_avec_trace.trace
    st.write(f"{libelle} : {montant_avec_trace.montant} $")
    with st.expander(f"Trace — {libelle}", expanded=False):
        st.write(f"Source : {trace.source}")
        st.write(f"Section : {trace.section}")
        st.write(f"Paramètres utilisés : {dict(trace.parametres_utilises)}")


def render() -> None:
    """Rendu du Bulletin_De_Paie — consultation en lecture seule.

    Bouton « Corriger cette paie » entre le titre et le contenu (haut de
    page, visible uniquement si la paie est `EMISE`), puis reproduction
    du gabarit officiel : identification, période, salaire, déductions
    fiscales, cotisations employeur.
    """
    id_paie = st.session_state.get(CLE_ID_PAIE_CIBLE)
    if not id_paie:
        st.header("Bulletin de paie")
        st.info(
            "Aucune paie sélectionnée. Naviguez depuis le Tableau de "
            "bord ou la Fiche employé pour consulter un bulletin de "
            "paie."
        )
        return

    resultat_paie = executer_avec_capture(
        lambda: lire_paie(id_paie, chemin_bd=chemin_bd_production())
    )
    if isinstance(resultat_paie, ErreurDomaineAffichable):
        st.header("Bulletin de paie")
        st.error(f"{resultat_paie.type_exception}: {resultat_paie.message}")
        return
    paie: PayrollResult = resultat_paie

    resultat_employe = executer_avec_capture(
        lambda: lire_employe(paie.employe_id)
    )
    if isinstance(resultat_employe, ErreurDomaineAffichable):
        st.header("Bulletin de paie")
        st.error(f"{resultat_employe.type_exception}: {resultat_employe.message}")
        return
    employe = resultat_employe

    resultat_coordonnees = executer_avec_capture(
        lambda: lire_coordonnees(paie.employe_id)
    )
    nas_affiche = "Non renseigné"
    if not isinstance(resultat_coordonnees, ErreurDomaineAffichable):
        if resultat_coordonnees is not None and resultat_coordonnees.nas:
            nas_affiche = resultat_coordonnees.nas

    # ------------------------------------------------------------------
    # Titre + bouton d'action en haut à droite (entre le titre et le
    # contenu — Req explicite de l'utilisateur).
    # ------------------------------------------------------------------
    col_titre, col_action = st.columns([3, 1])
    with col_titre:
        st.header("Bulletin de paie")
    with col_action:
        if paie.statut == StatutDePaie.EMISE:
            if st.button("Corriger cette paie", type="primary"):
                st.session_state["fp_corriger_ancien_id_precharge"] = id_paie
                from app.pages_ui._navigation import page_formulaire_paie

                st.switch_page(page_formulaire_paie)

    st.divider()

    # ------------------------------------------------------------------
    # Identification — Salarié / Employeur.
    # ------------------------------------------------------------------
    st.subheader("Identification")
    col_salarie, col_employeur = st.columns(2)
    with col_salarie:
        st.write("**Salarié**")
        st.write(f"Nom complet : {employe.nom_affichage}")
        st.write(f"NAS : {nas_affiche}")
        st.write(f"Date d'embauche : {employe.date_embauche}")
        st.write(f"Emploi : {employe.titre_emploi}")
    with col_employeur:
        st.write("**Employeur**")
        st.write(f"Nom : {CONFIG_EMPLOYEUR.nom}")
        st.write(f"Adresse : {CONFIG_EMPLOYEUR.adresse}")
        st.write(f"Ville : {CONFIG_EMPLOYEUR.ville}")
        st.write(f"Code postal : {CONFIG_EMPLOYEUR.code_postal}")
        st.write(f"Numéro NQE : {CONFIG_EMPLOYEUR.numero_nqe}")

    st.divider()

    # ------------------------------------------------------------------
    # Période.
    # ------------------------------------------------------------------
    st.subheader("Période")
    semaines = paie.pay_period.semaines
    st.write(
        f"Période correspondant au paiement : du "
        f"{semaines[0].date_debut} au {semaines[-1].date_fin}"
    )
    st.write(f"Date de paiement : {paie.pay_period.date_paiement}")

    st.divider()

    # ------------------------------------------------------------------
    # Heures travaillées et salaire.
    # ------------------------------------------------------------------
    st.subheader("Heures travaillées et salaire")

    heures_normales_totales = sum(
        (s.heures_normales for s in semaines), start=Decimal("0")
    )
    heures_supp_totales = sum(
        (s.heures_supplementaires for s in semaines), start=Decimal("0")
    )

    col_salaire, col_cotisations = st.columns(2)
    with col_salaire:
        st.write("**Salaire**")
        st.write(
            f"Heures normales : {heures_normales_totales} h "
            f"× {_taux_horaire_affiche(paie.gains.salaire_regulier, heures_normales_totales)} $/h"
        )
        st.write(
            f"Heures supplémentaires : {heures_supp_totales} h "
            f"× {_taux_horaire_affiche(paie.gains.heures_supplementaires_montant, heures_supp_totales)} $/h"
        )
        st.write(f"Total salaire : {paie.gains.salaire_regulier + paie.gains.heures_supplementaires_montant} $")
        st.write("**Indemnités**")
        st.write(f"Jours fériés : {paie.gains.jours_feries_manuels} $")
        st.write(f"Congés annuels (vacances) : {paie.gains.vacances} $")
        st.write(
            "Total indemnités : "
            f"{paie.gains.jours_feries_manuels + paie.gains.vacances} $"
        )
        st.write(f"**Salaire BRUT (salaire + indemnités) : {paie.gains.brut_total} $**")

    with col_cotisations:
        st.write("**Cotisation employeur (pour information seulement)**")
        cot = paie.cotisations_employeur
        _afficher_trace_montant("Régime des rentes du Québec (RRQ)", cot.rrq_employeur)
        _afficher_trace_montant("Assurance-emploi (AE)", cot.ae_employeur)
        _afficher_trace_montant(
            "Régime québécois d'assurance parentale (RQAP)", cot.rqap_employeur
        )
        taux_cnesst = cot.cnesst.trace.parametres_utilises.get("taux_total_cnesst")
        libelle_cnesst = "Cotisation CNESST"
        if taux_cnesst is not None:
            libelle_cnesst += f" (taux {taux_cnesst})"
        if cot.cnesst_en_attente_classification:
            libelle_cnesst += " — classification en attente"
        _afficher_trace_montant(libelle_cnesst, cot.cnesst)
        _afficher_trace_montant("Fonds des services de santé (FSS)", cot.fss)
        _afficher_trace_montant(
            "Cotisation relative aux normes du travail (CNT)", cot.cnt
        )
        st.write(f"**Total cotisations employeur : {cot.total_cotisations_employeur} $**")

    st.divider()

    # ------------------------------------------------------------------
    # Déductions fiscales.
    # ------------------------------------------------------------------
    st.subheader("Déductions fiscales")
    ret = paie.retenues_employe
    _afficher_trace_montant("Impôt fédéral", ret.impot_federal_retenu)
    _afficher_trace_montant("Impôt provincial", ret.impot_qc_retenu)
    _afficher_trace_montant("Régime des rentes du Québec (RRQ)", ret.rrq)
    _afficher_trace_montant("Assurance-emploi (AE)", ret.ae)
    _afficher_trace_montant(
        "Régime québécois d'assurance parentale (RQAP)", ret.rqap
    )
    st.write(f"**Total des déductions : {ret.total_retenues_employe} $**")
    st.write(f"## Salaire NET (salaire brut - déductions) : {paie.net} $")

    st.divider()

    # ------------------------------------------------------------------
    # Statut / métadonnées de la paie (hors gabarit, utile à l'audit).
    # ------------------------------------------------------------------
    st.caption(
        f"id_paie={paie.id_paie} | version={paie.version} | "
        f"statut={paie.statut.value} | date de création={paie.date_creation} | "
        f"date d'émission={paie.date_emission if paie.date_emission else 'Non émise'}"
    )
