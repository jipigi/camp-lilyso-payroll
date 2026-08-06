"""Nouvel_Employe — page dédiée de création d'une Fiche_Employe (Req 4.4,
4.7 à 4.12).

Spec de référence : ``interface-streamlit`` — tâche 22.1 (module
d'origine), corrigé après livraison en page dédiée distincte du
Tableau_De_Bord.

Bug UI corrigé après livraison : le formulaire de création vivait à
l'origine directement sur le Tableau_De_Bord (`tableau_de_bord.py`),
sous la liste des employés. Deux problèmes en résultaient :

1. Après confirmation (« Confirmer et enregistrer »), l'employé créé
   n'apparaissait pas dans la liste affichée juste au-dessus — la liste
   avait déjà été lue (`lister_employes()`) et rendue **avant**
   l'écriture de l'annuaire, sur le même run du script.
2. Le Requirement 4 AC4 demande explicitement que l'ajout d'un employé
   déclenche un **écran dédié**, avec retour au Tableau_De_Bord après
   confirmation — pas un formulaire toujours visible sur la page
   d'accueil.

Cette page résout les deux : elle est atteinte exclusivement par
`st.switch_page` depuis le Tableau_De_Bord (bouton « Ajouter un nouvel
employé »), et route explicitement vers le Tableau_De_Bord
(`st.switch_page`) après un enregistrement réussi — le nouveau `render()`
du Tableau_De_Bord relit alors `lister_employes()` à neuf, la nouvelle
fiche y apparaît immédiatement.

Couche de rendu (`app/pages_ui/`) : ce module **peut** importer
``streamlit`` (Req 1.1, 1.3 ne s'appliquent qu'à
`app/logique_metier/**`).

Règle 03 (périmètre Camp LilySO) : ``province_travail`` n'est jamais
saisi librement — affiché en lecture seule, fixé à
`Juridiction.QUEBEC` (Req 4.9).

Règle 04 (données sensibles) : ce formulaire n'expose aucun champ
NAS/adresse/courriel/téléphone (Req 4.8) — ces champs relèvent
exclusivement de la `FicheCoordonnees`
(`app/logique_metier/annuaire_coordonnees.py`), gérée depuis la
Fiche_Employe_Detaillee (Requirement 20), jamais depuis ce formulaire.

Règle 01 (Decimal obligatoire) : chaque montant est saisi comme texte
puis converti en `Decimal` via chaîne, jamais via `float` (Req 4.7).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par `Employee.avec_defauts_par_annee` est enveloppée par
`executer_avec_capture` — aucun `except Exception`/`except
BaseException` générique n'est présent dans ce module (Req 4.12, 16.1,
16.3).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

from app.logique_metier.annuaire_employes import enregistrer_employe
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.logique_metier.formulaire_paie import convertir_numero_en_id
from app.logique_metier.parametres_fiscaux import lister_annees_disponibles
from models.employee import Employee
from models.enums import Juridiction

#: Bornes du sélecteur de date pour `date_naissance` (Req 4.7) — sans
#: `min_value`/`max_value` explicites, `st.date_input` limite la plage
#: par défaut à environ ±10 ans autour d'aujourd'hui, ce qui empêche de
#: saisir la date de naissance réelle d'un moniteur (bug UI corrigé
#: après livraison, pure ergonomie de saisie — aucune règle fiscale
#: associée).
_DATE_NAISSANCE_MIN = date(date.today().year - 100, 1, 1)
_DATE_NAISSANCE_MAX = date.today()

#: Bornes du sélecteur de date pour `date_embauche`/`date_fin_emploi`
#: (Req 4.7) — même correction, plage large couvrant les embauches
#: passées et une marge future raisonnable.
_DATE_EMPLOI_MIN = date(date.today().year - 50, 1, 1)
_DATE_EMPLOI_MAX = date(date.today().year + 5, 12, 31)

#: Taux d'indemnité de vacances admis dans le périmètre Camp LilySO
#: (règle 03, Req 4.7) — mêmes deux valeurs que celles admises par
#: `Employee._refuser_hors_matrice` (`models/employee.py`).
_TAUX_VACANCES_OPTIONS: tuple[str, ...] = ("0.04", "0.06")

#: Clé de `st.session_state` portant l'`Employee` construit par
#: `avec_defauts_par_annee` en attente d'ajustement des 4 valeurs
#: fiscales dérivées, avant l'Action_Enregistrer définitive (Req 4.11).
_CLE_EMPLOYE_EN_ATTENTE = "nouvel_employe_en_attente"


def render() -> None:
    """Rendu de la page « Nouvel employé » (Req 4.4, 4.7 à 4.12).

    Formulaire de création, puis écran d'ajustement des 4 valeurs
    fiscales dérivées (Req 4.11) avant confirmation définitive. Après
    confirmation réussie, route vers le Tableau_De_Bord (Req 4.4).
    """
    st.header("Ajouter un nouvel employé")

    if _CLE_EMPLOYE_EN_ATTENTE in st.session_state:
        _afficher_ajustement_et_confirmation()
        return

    _afficher_formulaire_creation()


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
            "Date de naissance",
            min_value=_DATE_NAISSANCE_MIN,
            max_value=_DATE_NAISSANCE_MAX,
            key="creation_date_naissance",
        )
        titre_emploi = st.text_input("Titre d'emploi", key="creation_titre_emploi")
        taux_horaire_base = st.text_input(
            "Taux horaire de base ($)", key="creation_taux_horaire_base"
        )
        date_embauche = st.date_input(
            "Date d'embauche",
            min_value=_DATE_EMPLOI_MIN,
            max_value=_DATE_EMPLOI_MAX,
            key="creation_date_embauche",
        )
        date_fin_emploi = st.date_input(
            "Date de fin d'emploi (optionnel)",
            value=None,
            min_value=_DATE_EMPLOI_MIN,
            max_value=_DATE_EMPLOI_MAX,
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
            st.rerun()

    col_annuler, _ = st.columns(2)
    with col_annuler:
        if st.button("Annuler et retourner au tableau de bord"):
            from app.pages_ui._navigation import page_tableau_de_bord

            st.switch_page(page_tableau_de_bord)


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
        st.rerun()
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

    # Bug UI corrigé après livraison (Req 4.4) : retour explicite au
    # Tableau_De_Bord après confirmation — sa fonction `render()` relit
    # `lister_employes()` à neuf sur ce nouveau run, la fiche créée y
    # apparaît donc immédiatement (l'ancien comportement affichait ce
    # message sur la même page sans jamais relire la liste déjà rendue
    # plus haut dans le même run de script).
    from app.pages_ui._navigation import page_tableau_de_bord

    st.switch_page(page_tableau_de_bord)
