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

Règle 04 (données sensibles) : ce formulaire capte désormais le NAS dès
la création (bug UI signalé après démo — le NAS est une donnée
obligatoire pour la production des relevés fiscaux de fin d'année, sans
quoi il n'apparaît jamais sur le Bulletin_De_Paie). Le NAS n'est jamais
transmis à `Employee`/`avec_defauts_par_annee` (ce modèle interdit
toute donnée personnelle réelle, `reject_sensitive_fields`) — il est
conservé en attente (`st.session_state`) durant l'étape d'ajustement,
puis enregistré séparément dans la `FicheCoordonnees`
(`app/logique_metier/annuaire_coordonnees.py`) au moment de la
confirmation définitive, une fois l'`Employee` lui-même déjà persisté.
Les autres champs de coordonnées (adresse, courriel, téléphone) restent
saisis exclusivement depuis la Fiche_Employe_Detaillee (Requirement
20), où ils peuvent être ajoutés ou corrigés après la création.

Règle 01 (Decimal obligatoire) : chaque montant est saisi comme texte
puis converti en `Decimal` via chaîne, jamais via `float` (Req 4.7).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par `Employee.avec_defauts_par_annee` est enveloppée par
`executer_avec_capture` — aucun `except Exception`/`except
BaseException` générique n'est présent dans ce module (Req 4.12, 16.1,
16.3).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import streamlit as st

from app.logique_metier.annuaire_coordonnees import (
    FicheCoordonnees,
    enregistrer_coordonnees,
    formater_nas,
)
from app.logique_metier.annuaire_employes import (
    enregistrer_employe,
    lister_employes,
    lister_titres_emploi_suggeres,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.logique_metier.formulaire_paie import convertir_numero_en_id
from app.logique_metier.parametres_fiscaux import (
    charger_parametres_fusionnes,
    lister_annees_disponibles,
)
from app.pages_ui._navigation import afficher_lien_retour_tableau_de_bord
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

#: Clé de `st.session_state` portant le NAS saisi au formulaire de
#: création, en attente le temps de l'étape d'ajustement — jamais
#: transmis à `Employee` (règle 04), enregistré séparément dans la
#: `FicheCoordonnees` au moment de la confirmation définitive.
_CLE_NAS_EN_ATTENTE = "nouvel_employe_nas_en_attente"

#: Clés de `st.session_state` portant respectivement le prénom et le nom
#: saisis au formulaire de création — bug UI signalé après démo (le
#: formulaire ne captait qu'un « Nom affiché » unique, jamais scindé en
#: Prénom/Nom pour la `FicheCoordonnees`). Comme `_CLE_NAS_EN_ATTENTE`,
#: en attente le temps de l'étape d'ajustement.
_CLE_PRENOM_EN_ATTENTE = "nouvel_employe_prenom_en_attente"
_CLE_NOM_EN_ATTENTE = "nouvel_employe_nom_en_attente"

#: Motif de l'``id`` d'une Fiche_Employe (``convertir_numero_en_id`` —
#: ``EMPnnn``, ``nnn`` un entier non nécessairement borné à 3 chiffres si
#: un numéro saisi manuellement dépasse 999). Réutilisé par
#: :func:`_prochain_numero_employe_disponible` pour extraire la partie
#: numérique de chaque ``id`` existant, sans dupliquer le format déjà
#: figé par `formulaire_paie.convertir_numero_en_id`.
_MOTIF_ID_EMPLOYE = re.compile(r"^EMP(\d+)$")


def _prochain_numero_employe_disponible() -> int:
    """Numéro d'employé le plus grand de l'Annuaire_Employes, +1 (bug UI
    signalé après démo — valeur par défaut du champ « Numéro d'employé »,
    pour éviter à l'opérateur de devoir vérifier manuellement le dernier
    numéro utilisé). Retourne ``1`` si l'annuaire est vide ou si aucun
    ``id`` existant ne correspond au motif ``EMPnnn`` attendu.
    """
    numeros = [
        int(correspondance.group(1))
        for employe in lister_employes()
        if (correspondance := _MOTIF_ID_EMPLOYE.match(employe.id)) is not None
    ]
    return max(numeros, default=0) + 1


def _lundi_semaine_du_1er_juillet(annee: int) -> date:
    """Lundi de la semaine contenant le 1er juillet de ``annee`` (bug UI
    signalé après démo — valeur par défaut de « Date d'embauche »,
    cohérente avec le calendrier saisonnier du Camp LilySO). Calcul pur
    de calendrier : `date.weekday()` retourne 0 pour lundi, donc reculer
    de ``date(annee, 7, 1).weekday()`` jours ramène toujours au lundi de
    la même semaine ISO, que le 1er juillet tombe un lundi (0 jour de
    recul) ou un dimanche (6 jours de recul).
    """
    premier_juillet = date(annee, 7, 1)
    return premier_juillet - timedelta(days=premier_juillet.weekday())


def _vendredi_fin_sixieme_semaine(date_embauche: date) -> date:
    """Vendredi de la 6e semaine suivant ``date_embauche`` (bug UI signalé
    après démo — valeur par défaut de « Date de fin d'emploi »). La
    « 6e semaine passée la date d'embauche » est comptée à partir du
    lundi de la semaine de ``date_embauche`` elle-même (semaine 1) —
    ``date_embauche`` est déjà un lundi lorsque cette fonction est
    appelée avec la valeur par défaut de :func:`_lundi_semaine_du_1er_
    juillet`, le vendredi de la 6e semaine tombe alors exactement 5
    semaines et 4 jours plus tard.
    """
    lundi_semaine_embauche = date_embauche - timedelta(days=date_embauche.weekday())
    return lundi_semaine_embauche + timedelta(weeks=5, days=4)


def render() -> None:
    """Rendu de la page « Nouvel employé » (Req 4.4, 4.7 à 4.12).

    Formulaire de création, puis écran d'ajustement des 4 valeurs
    fiscales dérivées (Req 4.11) avant confirmation définitive. Après
    confirmation réussie, route vers le Tableau_De_Bord (Req 4.4).
    """
    afficher_lien_retour_tableau_de_bord()
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

    numero_par_defaut = str(_prochain_numero_employe_disponible())
    date_embauche_par_defaut = _lundi_semaine_du_1er_juillet(date.today().year)
    date_fin_emploi_par_defaut = _vendredi_fin_sixieme_semaine(
        date_embauche_par_defaut
    )

    # Bug UI signalé après démo : le sélecteur d'année des paramètres
    # fiscaux est déplacé **avant** (hors de) le formulaire — un widget
    # à l'intérieur d'un `st.form` ne déclenche aucun nouveau run avant
    # la soumission, ce qui empêcherait les plafonds d'exonération
    # affichés ci-dessous de refléter l'année réellement choisie tant
    # que le formulaire n'est pas soumis. Un widget hors formulaire
    # déclenche un rerun immédiat au changement, comme partout ailleurs
    # dans l'application (ex. `formulaire_paie.py`).
    annee_reference = st.selectbox(
        "Année des paramètres fiscaux",
        annees_disponibles,
        key="creation_annee_reference",
    )
    resultat_params = executer_avec_capture(
        lambda: charger_parametres_fusionnes(annee_reference)
    )
    if isinstance(resultat_params, ErreurDomaineAffichable):
        st.error(f"{resultat_params.type_exception}: {resultat_params.message}")
        return
    parametres_annee = resultat_params

    with st.form("formulaire_nouvel_employe"):
        numero = st.text_input(
            "Numéro d'employé",
            value=numero_par_defaut,
            key="creation_numero",
            disabled=True,
        )
        prenom = st.text_input("Prénom", key="creation_prenom")
        nom = st.text_input("Nom", key="creation_nom")
        # `on_change` est interdit par Streamlit sur un widget à
        # l'intérieur d'un `st.form` (seul `st.form_submit_button` peut
        # en porter un) — le NAS reste donc dans le formulaire, mise en
        # forme selon le gabarit ``999 999 999`` (:func:`formater_nas`)
        # appliquée uniquement à la soumission, plutôt qu'en direct
        # pendant la saisie (bug UI signalé après démo).
        nas = st.text_input(
            "NAS (optionnel — peut aussi être saisi plus tard depuis la "
            "Fiche employé)",
            key="creation_nas",
        )
        date_naissance = st.date_input(
            "Date de naissance",
            value=None,
            min_value=_DATE_NAISSANCE_MIN,
            max_value=_DATE_NAISSANCE_MAX,
            key="creation_date_naissance",
        )
        # Bug UI signalé après démo : autosuggestion du titre d'emploi
        # (5 titres de base du Camp LilySO, puis tout autre titre déjà
        # saisi dans l'Annuaire_Employes) — `accept_new_options=True`
        # laisse le champ saisissable librement, les suggestions ne
        # sont qu'un raccourci au focus, jamais une restriction des
        # valeurs admissibles (aucune contrainte de périmètre associée
        # à ce champ, contrairement à `province_travail`/`taux_
        # indemnite_vacances`, règle 03).
        titre_emploi = st.selectbox(
            "Titre d'emploi",
            options=lister_titres_emploi_suggeres(),
            index=None,
            accept_new_options=True,
            placeholder="Choisir une suggestion ou saisir un nouveau titre",
            key="creation_titre_emploi",
        )
        taux_horaire_base = st.text_input(
            "Taux horaire de base ($)", key="creation_taux_horaire_base"
        )
        date_embauche = st.date_input(
            "Date d'embauche",
            value=date_embauche_par_defaut,
            min_value=_DATE_EMPLOI_MIN,
            max_value=_DATE_EMPLOI_MAX,
            key="creation_date_embauche",
        )
        date_fin_emploi = st.date_input(
            "Date de fin d'emploi (optionnel)",
            value=date_fin_emploi_par_defaut,
            min_value=_DATE_EMPLOI_MIN,
            max_value=_DATE_EMPLOI_MAX,
            key="creation_date_fin_emploi",
        )
        taux_indemnite_vacances = st.selectbox(
            "Taux d'indemnité de vacances",
            _TAUX_VACANCES_OPTIONS,
            key="creation_taux_indemnite_vacances",
        )
        # Bug UI signalé après démo : titre de section + explication du
        # seuil réel d'admissibilité sous chaque case, plutôt que deux
        # cases nues sans contexte — les deux plafonds (« montant
        # personnel de base ») proviennent des paramètres fiscaux
        # fusionnés de l'année sélectionnée ci-dessus (règle 05, aucune
        # valeur codée en dur : `parametres_annee.impot_quebec`/
        # `.impot_federal.montant_personnel_base`).
        st.markdown("**Exonération d'impôt**")
        # Bug UI signalé après démo : conseil en italique, resserré
        # contre sa case à cocher — `st.container(gap=None)` retire
        # l'espacement vertical par défaut entre les deux widgets
        # regroupés (autrement identique à un espacement entre deux
        # groupes case/conseil distincts).
        with st.container(gap=None):
            exoneration_TP1015_3 = st.checkbox(
                "Exonération TP-1015.3", value=False, key="creation_exoneration_qc"
            )
            st.caption(
                "*Cocher si le revenu annuel prévu provenant de tous "
                "les emplois est inférieur à "
                f"{parametres_annee.impot_quebec.montant_personnel_base} $.*"
            )
        with st.container(gap=None):
            exoneration_TD1 = st.checkbox(
                "Exonération TD1", value=False, key="creation_exoneration_federale"
            )
            st.caption(
                "*Cocher si le revenu annuel prévu provenant de tous "
                "les emplois est inférieur à "
                f"{parametres_annee.impot_federal.montant_personnel_base} $.*"
            )
        st.write(f"Province de travail : {Juridiction.QUEBEC.value} (fixe)")

        soumis = st.form_submit_button("Créer la fiche", type="primary")

    if soumis:
        # `date_naissance` n'a plus de valeur par défaut (bug UI signalé
        # après démo) — `st.date_input(value=None, ...)` retourne `None`
        # tant que l'opérateur n'a pas explicitement choisi une date.
        # `Employee.date_naissance` est un champ requis (`date`, jamais
        # optionnel) : ce garde-fou évite de laisser Pydantic produire
        # un message de validation générique pour ce cas précis.
        if date_naissance is None:
            st.error(
                "ValueError: la date de naissance est requise pour créer "
                "une fiche employé."
            )
        else:
            _construire_et_afficher_employe(
                numero=numero,
                nas=nas,
                prenom=prenom,
                nom=nom,
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
    nas: str,
    prenom: str,
    nom: str,
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
    """Construit l'`Employee` via la fabrique, place le résultat en attente d'ajustement (Req 4.10, 4.11, 4.12).

    Le formulaire capte désormais Prénom/Nom séparément (bug UI signalé
    après démo, remplace l'ancien champ unique « Nom affiché ») — leur
    concaténation (``f"{prenom} {nom}"``) alimente `Employee.
    nom_affichage`, cohérent avec la convention déjà en place
    (`bulletin_paie._diviser_nom_affichage` suppose déjà cette forme en
    repli). Prénom, Nom et NAS sont en outre conservés en attente
    séparément (``_CLE_PRENOM_EN_ATTENTE``, ``_CLE_NOM_EN_ATTENTE``,
    ``_CLE_NAS_EN_ATTENTE``) — jamais transmis à `Employee` (règle 04) —
    pour être enregistrés dans la `FicheCoordonnees` correspondante au
    moment de la confirmation définitive
    (:func:`_afficher_ajustement_et_confirmation`).
    """

    def _construire() -> Employee:
        id_employe = convertir_numero_en_id(numero)
        return Employee.avec_defauts_par_annee(
            annee_reference,
            id=id_employe,
            nom_affichage=f"{prenom} {nom}".strip(),
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
    st.session_state[_CLE_PRENOM_EN_ATTENTE] = prenom
    st.session_state[_CLE_NOM_EN_ATTENTE] = nom
    # Mise en forme du NAS (gabarit ``999 999 999``) appliquée ici, à la
    # soumission — `on_change` (mise en forme en direct) est interdit
    # par Streamlit pour un widget à l'intérieur d'un `st.form`.
    st.session_state[_CLE_NAS_EN_ATTENTE] = formater_nas(nas)


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
        st.session_state.pop(_CLE_PRENOM_EN_ATTENTE, None)
        st.session_state.pop(_CLE_NOM_EN_ATTENTE, None)
        st.session_state.pop(_CLE_NAS_EN_ATTENTE, None)
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

    # Enregistrement de la `FicheCoordonnees` (Prénom/Nom/NAS captés au
    # formulaire de création, bug UI signalé après démo) — uniquement
    # après le succès de l'enregistrement de l'`Employee` lui-même, et
    # uniquement si au moins un des trois champs a été renseigné (évite
    # de créer une Fiche_Coordonnees entièrement vide qui masquerait le
    # cas nominal « coordonnées pas encore saisies », Req 20.7).
    prenom_en_attente = st.session_state.get(_CLE_PRENOM_EN_ATTENTE, "")
    nom_en_attente = st.session_state.get(_CLE_NOM_EN_ATTENTE, "")
    nas_en_attente = st.session_state.get(_CLE_NAS_EN_ATTENTE, "")
    if prenom_en_attente or nom_en_attente or nas_en_attente:
        resultat_coordonnees = executer_avec_capture(
            lambda: enregistrer_coordonnees(
                FicheCoordonnees(
                    employe_id=employe_final.id,
                    prenom=prenom_en_attente or None,
                    nom=nom_en_attente or None,
                    nas=nas_en_attente or None,
                )
            )
        )
        if isinstance(resultat_coordonnees, ErreurDomaineAffichable):
            st.error(
                f"{resultat_coordonnees.type_exception}: "
                f"{resultat_coordonnees.message}"
            )
            return

    del st.session_state[_CLE_EMPLOYE_EN_ATTENTE]
    st.session_state.pop(_CLE_PRENOM_EN_ATTENTE, None)
    st.session_state.pop(_CLE_NOM_EN_ATTENTE, None)
    st.session_state.pop(_CLE_NAS_EN_ATTENTE, None)
    st.success(f"Employé {employe_final.id} créé et enregistré.")

    # Bug UI corrigé après livraison (Req 4.4) : retour explicite au
    # Tableau_De_Bord après confirmation — sa fonction `render()` relit
    # `lister_employes()` à neuf sur ce nouveau run, la fiche créée y
    # apparaît donc immédiatement (l'ancien comportement affichait ce
    # message sur la même page sans jamais relire la liste déjà rendue
    # plus haut dans le même run de script).
    from app.pages_ui._navigation import page_tableau_de_bord

    st.switch_page(page_tableau_de_bord)
