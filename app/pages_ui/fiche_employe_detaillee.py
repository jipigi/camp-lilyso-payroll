"""Fiche_Employe_Detaillee — page de détail d'un employé (Req 5, 11, 20.4).

Spec de référence : ``interface-streamlit`` — tâche 23.1.
Design de référence : ``design.md`` §Components §3 (`annuaire_coordonnees.py`
— `FicheCoordonnees`), §4 (`dernieres_paies.py`), §7 (`fiche_employe.py`
— `mettre_a_jour_donnees_fiscales`).

Ce module porte la fonction unique :func:`render` qui regroupe **trois
sections visuellement distinctes** sur un seul écran (Req 5.1) :

1. **Informations employé** — affichage des champs non sensibles de la
   Fiche_Employe (`Employee`) et formulaire de modification des 6
   champs TD1/TP-1015.3, qui invoque `mettre_a_jour_donnees_fiscales`
   puis `enregistrer_employe` (Req 11.1, 11.2, 11.3) ; toute erreur
   traverse `executer_avec_capture` sans qu'aucune modification
   partielle ne soit jamais persistée dans l'Annuaire_Employes — la
   reconstruction immuable (`mettre_a_jour_donnees_fiscales`) échoue
   *avant* tout appel à `enregistrer_employe`, les deux opérations
   étant enchaînées dans une seule fonction passée à
   `executer_avec_capture` (Req 11.4).
2. **Coordonnées opérationnelles** — affichage/édition de la
   `FicheCoordonnees` via `lire_coordonnees`/`enregistrer_coordonnees`
   (Requirement 20). Cette section reste **visuellement et
   fonctionnellement distincte** du Formulaire_Paie et du formulaire de
   création de Fiche_Employe (Req 20.4) : elle porte son propre
   `st.subheader`, son propre `st.form` à clés dédiées, et n'invoque
   jamais `assembler_paie`/`Employee.avec_defauts_par_annee`.
3. **Paies** — liste déroulante des années fiscales formatée par
   `formater_option_annee`/`regrouper_saison_par_annee` (Req 5.2),
   liste des paies de l'année sélectionnée via
   `filtrer_par_annee`/`lire_resumes_paies` (Req 5.3), consultation des
   valeurs TD1/TP-1015.3 effectives d'une paie choisie et des cumuls
   YTD de l'année via `lire_cumuls_ytd` (Req 5.4), bouton d'ajout de
   paie qui pré-remplit l'année civile courante (modifiable, Req 5.5),
   et indication explicite d'absence de paie sans lever d'exception
   (Req 5.6).

Couche de rendu (`app/pages_ui/`) : ce module **peut** importer
``streamlit``, à la différence de `app/logique_metier/` (Req 1.1, 1.3).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par les fonctions de `app/logique_metier/**` ou du moteur est enveloppée
par `executer_avec_capture` — aucun `except Exception`/`except
BaseException` générique n'est présent dans ce module (Req 16.1, 16.3).

Valeurs TD1/TP-1015.3 effectives d'une paie (Req 5.4) : ces six valeurs
ne sont pas des champs directs de `PayrollResult` — elles sont
reconstituées à partir des `CalculationTrace` déjà produites par
`assembler_paie` (règle 02 : aucune nouvelle trace n'est inventée ici,
uniquement une lecture des traces existantes) :

- `montant_total_TP1015_3_effectif` ←
  `retenues_employe.impot_qc_formule.trace.entrees["montant_total_tp1015_3"]`
  (toujours calculée, même en cas d'exonération — seule
  `impot_qc_retenu` court-circuite la formule) ;
- `exoneration_TP1015_3_effectif` ←
  `retenues_employe.impot_qc_retenu.trace.parametres_utilises["exoneration_active"]`
  (encodée `Decimal("0")`/`Decimal("1")`, reconvertie en `bool`) ;
- `retenue_additionnelle_QC_effective` ←
  `retenues_employe.impot_qc_retenu.trace.entrees["retenue_additionnelle_qc"]` ;
- les trois valeurs fédérales symétriques proviennent de
  `impot_federal_formule`/`impot_federal_retenu` selon le même patron.

Navigation multipage (Req 5.5) : l'assemblage final de la navigation
entre pages est réalisé par `app/main.py` (tâche 26.1, hors périmètre
de cette tâche) — ce module se contente de préparer l'état partagé via
`st.session_state` (mêmes clés que `app/pages_ui/tableau_de_bord.py` :
`employe_id_selectionne`, `annee_paie_defaut`), sans résoudre lui-même
la navigation complète.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

from app.logique_metier.annuaire_coordonnees import (
    FicheCoordonnees,
    enregistrer_coordonnees,
    lire_coordonnees,
)
from app.logique_metier.annuaire_employes import enregistrer_employe, lister_employes
from app.logique_metier.dernieres_paies import (
    LignePaieResume,
    filtrer_par_annee,
    formater_option_annee,
    lire_resumes_paies,
    regrouper_saison_par_annee,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.logique_metier.fiche_employe import mettre_a_jour_donnees_fiscales
from models.employee import Employee
from payroll_engine.register import chemin_bd_production, lire_cumuls_ytd, lire_paie

#: Mêmes clés de `st.session_state` que `app/pages_ui/tableau_de_bord.py`
#: — transportent la sélection d'employé/année courante entre pages
#: (Req 4.5, 4.6, 5.5). Dupliquées ici en constantes locales plutôt
#: qu'importées (ce sont des constantes privées de
#: `tableau_de_bord.py`) — même discipline que
#: `historique_et_cumuls.py::_CATEGORIES_CUMULS_AFFICHAGE`.
_CLE_EMPLOYE_SELECTIONNE = "employe_id_selectionne"
_CLE_ANNEE_PAIE_DEFAUT = "annee_paie_defaut"

#: Les onze catégories monétaires de `CumulsYTD`, dans l'ordre du design
#: §Data Models 6 — même liste que
#: `historique_et_cumuls.py::_CATEGORIES_CUMULS_AFFICHAGE` (Req 5.4,
#: Req 15.1).
_CATEGORIES_CUMULS_AFFICHAGE: tuple[str, ...] = (
    "brut",
    "vacances",
    "rrq_employe",
    "rrq_employeur",
    "rqap_employe",
    "rqap_employeur",
    "ae_employe",
    "ae_employeur",
    "impot_qc_retenu",
    "impot_federal_retenu",
    "net",
)


def render() -> None:
    """Rendu de la Fiche_Employe_Detaillee (Req 5.1) — trois sections.

    Sélectionne d'abord l'employé courant (pré-rempli depuis
    `st.session_state["employe_id_selectionne"]` si l'opérateur vient du
    Tableau_De_Bord), puis affiche les trois sections dans l'ordre :
    informations employé, coordonnées, paies.
    """
    st.header("Fiche employé détaillée")

    resultat_employes = executer_avec_capture(lambda: lister_employes())
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    if not employes:
        st.info("Aucun employé dans l'Annuaire_Employes.")
        return

    options_employes = [e.id for e in employes]
    employe_id_defaut = st.session_state.get(_CLE_EMPLOYE_SELECTIONNE)
    index_defaut = (
        options_employes.index(employe_id_defaut)
        if employe_id_defaut in options_employes
        else 0
    )
    employe_id = st.selectbox(
        "Employé",
        options_employes,
        index=index_defaut,
        key="fed_employe_id",
    )
    employe = next(e for e in employes if e.id == employe_id)

    _section_informations_employe(employe)

    st.divider()
    _section_coordonnees(employe_id)

    st.divider()
    _section_paies(employe_id)


def _section_informations_employe(employe: Employee) -> None:
    """Section (a) — champs `Employee` et modification fiscale (Req 5.1, 11)."""
    st.subheader("Informations employé")

    st.write(f"id : {employe.id}")
    st.write(f"Nom affiché : {employe.nom_affichage}")
    st.write(f"Date de naissance : {employe.date_naissance}")
    st.write(f"Province de travail : {employe.province_travail.value}")
    st.write(f"Titre d'emploi : {employe.titre_emploi}")
    st.write(f"Taux horaire de base : {employe.taux_horaire_base}")
    st.write(f"Date d'embauche : {employe.date_embauche}")
    st.write(
        "Date de fin d'emploi : "
        f"{employe.date_fin_emploi if employe.date_fin_emploi else 'Aucune'}"
    )
    st.write(f"Taux d'indemnité de vacances : {employe.taux_indemnite_vacances}")

    st.write("**Modification des données fiscales TD1/TP-1015.3**")
    with st.form(f"fed_formulaire_fiscal_{employe.id}"):
        montant_tp1015_3 = st.text_input(
            "Montant total TP-1015.3 ($)",
            value=str(employe.montant_total_TP1015_3),
            key=f"fed_montant_tp1015_3_{employe.id}",
        )
        exoneration_tp1015_3 = st.checkbox(
            "Exonération TP-1015.3",
            value=employe.exoneration_TP1015_3,
            key=f"fed_exoneration_tp1015_3_{employe.id}",
        )
        retenue_qc = st.text_input(
            "Retenue additionnelle QC ($)",
            value=str(employe.retenue_additionnelle_QC),
            key=f"fed_retenue_qc_{employe.id}",
        )
        montant_td1 = st.text_input(
            "Montant total TD1 ($)",
            value=str(employe.montant_total_TD1),
            key=f"fed_montant_td1_{employe.id}",
        )
        exoneration_td1 = st.checkbox(
            "Exonération TD1",
            value=employe.exoneration_TD1,
            key=f"fed_exoneration_td1_{employe.id}",
        )
        retenue_federale = st.text_input(
            "Retenue additionnelle fédérale ($)",
            value=str(employe.retenue_additionnelle_federale),
            key=f"fed_retenue_federale_{employe.id}",
        )
        soumis = st.form_submit_button(
            "Mettre à jour les données fiscales", type="primary"
        )

    if not soumis:
        return

    def _mettre_a_jour_et_enregistrer() -> Employee:
        # Req 11.4 — `mettre_a_jour_donnees_fiscales` lève avant tout
        # retour si une valeur est invalide : `enregistrer_employe`
        # n'est alors jamais atteinte, aucune modification partielle
        # n'est jamais persistée dans l'Annuaire_Employes.
        nouvel_employe = mettre_a_jour_donnees_fiscales(
            employe,
            montant_total_TP1015_3=Decimal(montant_tp1015_3),
            exoneration_TP1015_3=exoneration_tp1015_3,
            retenue_additionnelle_QC=Decimal(retenue_qc),
            montant_total_TD1=Decimal(montant_td1),
            exoneration_TD1=exoneration_td1,
            retenue_additionnelle_federale=Decimal(retenue_federale),
        )
        enregistrer_employe(nouvel_employe)
        return nouvel_employe

    try:
        resultat = executer_avec_capture(_mettre_a_jour_et_enregistrer)
    except InvalidOperation:
        st.error(
            "ValueError: chaque valeur fiscale doit être un nombre "
            "décimal valide (ex. \"18.50\")."
        )
        return

    if isinstance(resultat, ErreurDomaineAffichable):
        st.error(f"{resultat.type_exception}: {resultat.message}")
        return

    st.success(f"Données fiscales de {resultat.id} mises à jour.")


def _section_coordonnees(employe_id: str) -> None:
    """Section (b) — `FicheCoordonnees`, distincte du Formulaire_Paie (Req 20.4)."""
    st.subheader("Coordonnées opérationnelles")

    resultat_coordonnees = executer_avec_capture(
        lambda: lire_coordonnees(employe_id)
    )
    if isinstance(resultat_coordonnees, ErreurDomaineAffichable):
        st.error(
            f"{resultat_coordonnees.type_exception}: "
            f"{resultat_coordonnees.message}"
        )
        return
    fiche_existante: FicheCoordonnees | None = resultat_coordonnees

    with st.form(f"fed_formulaire_coordonnees_{employe_id}"):
        nom_complet_reel = st.text_input(
            "Nom complet réel",
            value=(fiche_existante.nom_complet_reel or "") if fiche_existante else "",
            key=f"fed_coord_nom_complet_{employe_id}",
        )
        nas = st.text_input(
            "NAS",
            value=(fiche_existante.nas or "") if fiche_existante else "",
            key=f"fed_coord_nas_{employe_id}",
        )
        adresse_residentielle = st.text_input(
            "Adresse résidentielle",
            value=(
                (fiche_existante.adresse_residentielle or "")
                if fiche_existante
                else ""
            ),
            key=f"fed_coord_adresse_{employe_id}",
        )
        courriel = st.text_input(
            "Courriel",
            value=(fiche_existante.courriel or "") if fiche_existante else "",
            key=f"fed_coord_courriel_{employe_id}",
        )
        telephone = st.text_input(
            "Téléphone",
            value=(fiche_existante.telephone or "") if fiche_existante else "",
            key=f"fed_coord_telephone_{employe_id}",
        )
        soumis = st.form_submit_button("Enregistrer les coordonnées", type="primary")

    if not soumis:
        return

    def _construire_et_enregistrer() -> FicheCoordonnees:
        fiche = FicheCoordonnees(
            employe_id=employe_id,
            nom_complet_reel=nom_complet_reel or None,
            nas=nas or None,
            adresse_residentielle=adresse_residentielle or None,
            courriel=courriel or None,
            telephone=telephone or None,
        )
        enregistrer_coordonnees(fiche)
        return fiche

    resultat_enregistrement = executer_avec_capture(_construire_et_enregistrer)
    if isinstance(resultat_enregistrement, ErreurDomaineAffichable):
        st.error(
            f"{resultat_enregistrement.type_exception}: "
            f"{resultat_enregistrement.message}"
        )
        return

    st.success(f"Coordonnées de {employe_id} enregistrées.")


def _section_paies(employe_id: str) -> None:
    """Section (c) — années, paies, valeurs fiscales effectives, cumuls YTD (Req 5.2 à 5.6)."""
    st.subheader("Paies")

    resultat_resumes = executer_avec_capture(lambda: lire_resumes_paies(employe_id))
    if isinstance(resultat_resumes, ErreurDomaineAffichable):
        st.error(f"{resultat_resumes.type_exception}: {resultat_resumes.message}")
        return
    resumes: tuple[LignePaieResume, ...] = resultat_resumes

    if not resumes:
        # Req 5.6 — absence de paie indiquée explicitement, sans exception.
        st.info("Aucune paie enregistrée pour cet employé.")
    else:
        saisons_par_annee = regrouper_saison_par_annee(resumes)
        annees = sorted(saisons_par_annee.keys())
        options_annees = [
            formater_option_annee(annee, saisons_par_annee.get(annee))
            for annee in annees
        ]
        index_annee = st.selectbox(
            "Année fiscale",
            options=range(len(annees)),
            format_func=lambda i: options_annees[i],
            key=f"fed_annee_{employe_id}",
        )
        annee_selectionnee = annees[index_annee]

        paies_annee = filtrer_par_annee(resumes, annee_selectionnee)
        st.write(f"Paies de l'année {annee_selectionnee} :")
        for resume in paies_annee:
            st.write(
                f"numero_periode={resume.numero_periode} | "
                f"id_paie={resume.id_paie} | "
                f"version={resume.version} | "
                f"statut={resume.statut} | "
                f"net={resume.net} | "
                f"date_creation={resume.date_creation}"
            )

        # Req 5.4 — valeurs TD1/TP-1015.3 effectives d'une paie choisie.
        if paies_annee:
            options_paies = [r.id_paie for r in paies_annee]
            id_paie_detail = st.selectbox(
                "Paie pour le détail fiscal effectif",
                options_paies,
                key=f"fed_paie_detail_{employe_id}",
            )
            _afficher_valeurs_fiscales_effectives(id_paie_detail)

        # Req 5.4 — cumuls YTD de l'année sélectionnée.
        resultat_cumuls = executer_avec_capture(
            lambda: lire_cumuls_ytd(
                employe_id, annee_selectionnee, chemin_bd=chemin_bd_production()
            )
        )
        if isinstance(resultat_cumuls, ErreurDomaineAffichable):
            st.error(f"{resultat_cumuls.type_exception}: {resultat_cumuls.message}")
        else:
            cumuls = resultat_cumuls
            st.write(f"**Cumuls YTD {annee_selectionnee}**")
            for categorie in _CATEGORIES_CUMULS_AFFICHAGE:
                st.write(f"{categorie} = {getattr(cumuls, categorie)}")

    # Req 5.5 — bouton d'ajout d'une nouvelle paie, année civile courante
    # pré-remplie (ou celle déjà en attente depuis le Tableau_De_Bord),
    # modifiable avant de poursuivre vers le Formulaire_Paie.
    st.write("**Ajouter une nouvelle paie**")
    annee_defaut = st.session_state.get(_CLE_ANNEE_PAIE_DEFAUT, date.today().year)
    annee_nouvelle_paie = st.number_input(
        "Année fiscale de la nouvelle paie",
        min_value=2000,
        max_value=2100,
        value=int(annee_defaut),
        step=1,
        key=f"fed_annee_nouvelle_paie_{employe_id}",
    )
    if st.button("Ajouter une paie", type="primary", key=f"fed_ajouter_paie_{employe_id}"):
        st.session_state[_CLE_EMPLOYE_SELECTIONNE] = employe_id
        st.session_state[_CLE_ANNEE_PAIE_DEFAUT] = int(annee_nouvelle_paie)
        st.info(
            "Rendez-vous sur la page « Formulaire de paie » pour "
            f"poursuivre l'ajout d'une paie {int(annee_nouvelle_paie)} "
            f"pour {employe_id}."
        )


def _afficher_valeurs_fiscales_effectives(id_paie: str) -> None:
    """Affiche les 6 valeurs TD1/TP-1015.3 effectives d'une paie (Req 5.4).

    Reconstitue ces six valeurs à partir des `CalculationTrace` déjà
    produites par `assembler_paie` (règle 02 — aucune nouvelle trace
    n'est inventée ici), en relisant la paie via `lire_paie` (une des
    six fonctions figées du moteur, Req 18.3).
    """
    resultat_paie = executer_avec_capture(
        lambda: lire_paie(id_paie, chemin_bd=chemin_bd_production())
    )
    if isinstance(resultat_paie, ErreurDomaineAffichable):
        st.error(f"{resultat_paie.type_exception}: {resultat_paie.message}")
        return

    paie = resultat_paie
    retenues = paie.retenues_employe

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

    st.write(f"**Valeurs TD1/TP-1015.3 effectives — {id_paie}**")
    st.write(
        "Montant total TP-1015.3 effectif : "
        f"{retenues.impot_qc_formule.trace.entrees['montant_total_tp1015_3']}"
    )
    st.write(f"Exonération TP-1015.3 effective : {exoneration_tp1015_3}")
    st.write(
        "Retenue additionnelle QC effective : "
        f"{retenues.impot_qc_retenu.trace.entrees['retenue_additionnelle_qc']}"
    )
    st.write(
        "Montant total TD1 effectif : "
        f"{retenues.impot_federal_formule.trace.entrees['montant_total_td1']}"
    )
    st.write(f"Exonération TD1 effective : {exoneration_td1}")
    st.write(
        "Retenue additionnelle fédérale effective : "
        f"{retenues.impot_federal_retenu.trace.entrees['retenue_additionnelle_federale']}"
    )
