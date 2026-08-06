"""Tableau_De_Bord — page d'accueil de l'Interface_Streamlit (Req 4).

Spec de référence : ``interface-streamlit`` — tâche 22.1.
Design de référence : ``design.md`` §Architecture « Navigation
multipage » ; §Components §2 (`annuaire_employes.py`), §4
(`dernieres_paies.py`).

Ce module porte la fonction unique :func:`render` qui affiche la liste
des Fiches_Employe de l'Annuaire_Employes (Req 4.1, 4.2), un raccourci
par ligne pour ajouter une paie (Req 4.5) ou naviguer vers la
Fiche_Employe_Detaillee (Req 4.6), et le formulaire de création d'un
nouvel employé (Req 4.7 à 4.12).

Couche de rendu (`app/pages_ui/`) : ce module **peut** importer
``streamlit``, à la différence de `app/logique_metier/` (Req 1.1, 1.3).

Règle 03 (périmètre Camp LilySO) : ``province_travail`` n'est jamais
saisi librement — affiché en lecture seule, fixé à
`Juridiction.QUEBEC` (Req 4.9).

Règle 04 (données sensibles) : le formulaire de création n'expose
aucun champ NAS/adresse/courriel/téléphone (Req 4.8) — ces champs
relèvent exclusivement de la `FicheCoordonnees`
(`app/logique_metier/annuaire_coordonnees.py`), gérée depuis la Fiche_
Employe_Detaillee (Requirement 20), jamais depuis ce formulaire.

Règle 01 (Decimal obligatoire) : `taux_horaire_base` est saisi comme
texte puis converti en `Decimal` via chaîne, jamais via `float`
(Req 4.7).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par `lister_employes` ou par `Employee.avec_defauts_par_annee` est
enveloppée par `executer_avec_capture` — aucun `except Exception`/
`except BaseException` générique n'est présent dans ce module
(Req 4.12, 16.1, 16.3).

Navigation multipage (Req 4.5, 4.6) : l'assemblage final de la
navigation entre pages est réalisé par `app/main.py` (tâche 26.1, hors
périmètre de cette tâche). Ce module se contente de préparer l'état
partagé nécessaire via `st.session_state` (`employe_id_selectionne`,
`annee_paie_defaut`) — aucune résolution de navigation complète n'est
tentée ici.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

from app.logique_metier.annuaire_employes import (
    enregistrer_employe,
    lister_employes,
)
from app.logique_metier.dernieres_paies import derniere_annee_paie
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.logique_metier.formulaire_paie import convertir_numero_en_id
from app.logique_metier.parametres_fiscaux import lister_annees_disponibles
from models.employee import Employee
from models.enums import Juridiction

#: Taux d'indemnité de vacances admis dans le périmètre Camp LilySO
#: (règle 03, Req 4.7) — mêmes deux valeurs que celles admises par
#: `Employee._refuser_hors_matrice` (`models/employee.py`).
_TAUX_VACANCES_OPTIONS: tuple[str, ...] = ("0.04", "0.06")

#: Clés de `st.session_state` transportant la sélection d'employé et
#: d'année vers les pages voisines (Req 4.5, 4.6). L'assemblage complet
#: de la navigation (`st.switch_page`/`st.Page`) relève de la tâche
#: 26.1 (`app/main.py`) — non résolu ici.
_CLE_EMPLOYE_SELECTIONNE = "employe_id_selectionne"
_CLE_ANNEE_PAIE_DEFAUT = "annee_paie_defaut"

#: Clé de `st.session_state` portant l'`Employee` construit par
#: `avec_defauts_par_annee` en attente d'ajustement des 4 valeurs
#: fiscales dérivées, avant l'Action_Enregistrer définitive (Req 4.11).
_CLE_EMPLOYE_EN_ATTENTE = "nouvel_employe_en_attente"


def render() -> None:
    """Affiche le Tableau_De_Bord — liste des employés et création (Req 4).

    Liste chaque Fiche_Employe (`id`, `nom_affichage`, dernière année de
    paie ou indication explicite d'absence — Req 4.1, 4.2, 4.3), offre
    un raccourci par ligne pour ajouter une paie ou consulter la Fiche_
    Employe_Detaillee (Req 4.5, 4.6), et le formulaire de création d'un
    nouvel employé (Req 4.7 à 4.12).
    """
    st.header("Tableau de bord — Employés")

    resultat_employes = executer_avec_capture(lister_employes)
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    _afficher_liste_employes(employes)

    st.divider()
    st.subheader("Ajouter un nouvel employé")
    _afficher_formulaire_creation()


def _afficher_liste_employes(employes: tuple[Employee, ...]) -> None:
    """Affiche une ligne par Fiche_Employe avec ses raccourcis (Req 4.1 à 4.6)."""
    if not employes:
        st.info("Aucun employé enregistré dans l'Annuaire_Employes.")
        return

    for employe in employes:
        annee_derniere = derniere_annee_paie(employe.id)
        col_id, col_nom, col_annee, col_actions = st.columns([2, 3, 2, 3])

        with col_id:
            st.write(employe.id)
        with col_nom:
            st.write(employe.nom_affichage)
        with col_annee:
            st.write(
                str(annee_derniere)
                if annee_derniere is not None
                else "Aucune paie enregistrée"
            )
        with col_actions:
            if st.button(
                "Ajouter une paie",
                key=f"ajouter_paie_{employe.id}",
                type="primary",
            ):
                st.session_state[_CLE_EMPLOYE_SELECTIONNE] = employe.id
                st.session_state[_CLE_ANNEE_PAIE_DEFAUT] = date.today().year
            if st.button("Voir la fiche", key=f"voir_fiche_{employe.id}"):
                st.session_state[_CLE_EMPLOYE_SELECTIONNE] = employe.id


def _afficher_formulaire_creation() -> None:
    """Formulaire de création de Fiche_Employe (Req 4.7 à 4.12)."""
    annees_disponibles = lister_annees_disponibles()
    if not annees_disponibles:
        st.warning(
            "Aucune année de paramètres fiscaux disponible sous "
            "parameters/ — impossible de créer un nouvel employé."
        )
        return

    with st.form("formulaire_nouvel_employe"):
        numero = st.text_input("Numéro d'employé", key="creation_numero")
        nom_affichage = st.text_input(
            "Nom affiché", key="creation_nom_affichage"
        )
        date_naissance = st.date_input(
            "Date de naissance", key="creation_date_naissance"
        )
        titre_emploi = st.text_input("Titre d'emploi", key="creation_titre_emploi")
        taux_horaire_base = st.text_input(
            "Taux horaire de base ($)", key="creation_taux_horaire_base"
        )
        date_embauche = st.date_input(
            "Date d'embauche", key="creation_date_embauche"
        )
        date_fin_emploi = st.date_input(
            "Date de fin d'emploi (optionnel)",
            value=None,
            key="creation_date_fin_emploi",
        )
        taux_indemnite_vacances = st.selectbox(
            "Taux d'indemnité de vacances",
            _TAUX_VACANCES_OPTIONS,
            key="creation_taux_indemnite_vacances",
        )
        exoneration_TP1015_3 = st.checkbox(
            "Exonération TP-1015.3", value=False, key="creation_exoneration_qc"
        )
        exoneration_TD1 = st.checkbox(
            "Exonération TD1", value=False, key="creation_exoneration_federale"
        )
        st.write(f"Province de travail : {Juridiction.QUEBEC.value} (fixe)")

        annee_reference = st.selectbox(
            "Année des paramètres fiscaux",
            annees_disponibles,
            key="creation_annee_reference",
        )

        soumis = st.form_submit_button("Créer la fiche", type="primary")

    if soumis:
        _construire_et_afficher_employe(
            numero=numero,
            nom_affichage=nom_affichage,
            date_naissance=date_naissance,
            titre_emploi=titre_emploi,
            taux_horaire_base=taux_horaire_base,
            date_embauche=date_embauche,
            date_fin_emploi=date_fin_emploi,
            taux_indemnite_vacances=taux_indemnite_vacances,
            exoneration_TP1015_3=exoneration_TP1015_3,
            exoneration_TD1=exoneration_TD1,
            annee_reference=annee_reference,
        )

    if _CLE_EMPLOYE_EN_ATTENTE in st.session_state:
        _afficher_ajustement_et_confirmation()


def _construire_et_afficher_employe(
    *,
    numero: str,
    nom_affichage: str,
    date_naissance: date,
    titre_emploi: str,
    taux_horaire_base: str,
    date_embauche: date,
    date_fin_emploi: date | None,
    taux_indemnite_vacances: str,
    exoneration_TP1015_3: bool,
    exoneration_TD1: bool,
    annee_reference: int,
) -> None:
    """Construit l'`Employee` via la fabrique, place le résultat en attente d'ajustement (Req 4.10, 4.11, 4.12)."""

    def _construire() -> Employee:
        id_employe = convertir_numero_en_id(numero)
        return Employee.avec_defauts_par_annee(
            annee_reference,
            id=id_employe,
            nom_affichage=nom_affichage,
            date_naissance=date_naissance,
            province_travail=Juridiction.QUEBEC,
            titre_emploi=titre_emploi,
            taux_horaire_base=Decimal(taux_horaire_base),
            date_embauche=date_embauche,
            date_fin_emploi=date_fin_emploi,
            taux_indemnite_vacances=Decimal(taux_indemnite_vacances),
            exoneration_TP1015_3=exoneration_TP1015_3,
            exoneration_TD1=exoneration_TD1,
        )

    try:
        resultat = executer_avec_capture(_construire)
    except InvalidOperation:
        st.error(
            "ValueError: le taux horaire de base doit être un nombre "
            "décimal valide (ex. \"18.50\")."
        )
        return

    if isinstance(resultat, ErreurDomaineAffichable):
        st.error(f"{resultat.type_exception}: {resultat.message}")
        return

    st.session_state[_CLE_EMPLOYE_EN_ATTENTE] = resultat


def _afficher_ajustement_et_confirmation() -> None:
    """Affiche les 4 valeurs fiscales dérivées, ajustables avant enregistrement (Req 4.11)."""
    nouvel_employe: Employee = st.session_state[_CLE_EMPLOYE_EN_ATTENTE]

    st.write(
        f"Fiche prête pour {nouvel_employe.id} — "
        f"{nouvel_employe.nom_affichage}. Ajustez si nécessaire les "
        f"valeurs fiscales dérivées avant l'enregistrement définitif :"
    )

    montant_tp1015_3 = st.text_input(
        "Montant total TP-1015.3 ($)",
        value=str(nouvel_employe.montant_total_TP1015_3),
        key="ajustement_montant_tp1015_3",
    )
    montant_td1 = st.text_input(
        "Montant total TD1 ($)",
        value=str(nouvel_employe.montant_total_TD1),
        key="ajustement_montant_td1",
    )
    retenue_qc = st.text_input(
        "Retenue additionnelle QC ($)",
        value=str(nouvel_employe.retenue_additionnelle_QC),
        key="ajustement_retenue_qc",
    )
    retenue_federale = st.text_input(
        "Retenue additionnelle fédérale ($)",
        value=str(nouvel_employe.retenue_additionnelle_federale),
        key="ajustement_retenue_federale",
    )

    col_confirmer, col_annuler = st.columns(2)
    with col_confirmer:
        confirmer = st.button(
            "Confirmer et enregistrer",
            key="confirmer_enregistrement_employe",
            type="primary",
        )
    with col_annuler:
        annuler = st.button("Annuler", key="annuler_creation_employe")

    if annuler:
        del st.session_state[_CLE_EMPLOYE_EN_ATTENTE]
        return

    if not confirmer:
        return

    try:
        employe_final = Employee(
            **{
                **nouvel_employe.model_dump(),
                "montant_total_TP1015_3": Decimal(montant_tp1015_3),
                "montant_total_TD1": Decimal(montant_td1),
                "retenue_additionnelle_QC": Decimal(retenue_qc),
                "retenue_additionnelle_federale": Decimal(retenue_federale),
            }
        )
    except InvalidOperation:
        st.error(
            "ValueError: chaque valeur fiscale ajustée doit être un "
            "nombre décimal valide."
        )
        return

    resultat_enregistrement = executer_avec_capture(
        lambda: enregistrer_employe(employe_final)
    )
    if isinstance(resultat_enregistrement, ErreurDomaineAffichable):
        st.error(
            f"{resultat_enregistrement.type_exception}: "
            f"{resultat_enregistrement.message}"
        )
        return

    del st.session_state[_CLE_EMPLOYE_EN_ATTENTE]
    st.success(f"Employé {employe_final.id} créé et enregistré.")
