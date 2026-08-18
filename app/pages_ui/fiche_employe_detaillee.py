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
    annees_disponibles,
    dernieres_versions_par_periode,
    filtrer_par_annee,
    formater_option_annee,
    lire_resumes_paies,
    regrouper_saison_par_annee,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.logique_metier.fiche_employe import (
    mettre_a_jour_donnees_fiscales,
    mettre_a_jour_informations_principales,
)
from app.pages_ui import bulletin_paie
from models.employee import Employee
from models.enums import StatutDePaie
from payroll_engine.register import chemin_bd_production, lire_cumuls_ytd

#: Libellés d'affichage des statuts de paie — même dict que
#: `app/pages_ui/tableau_de_bord.py::_LIBELLES_STATUT`, dupliqué ici
#: (constante privée d'un autre module de rendu).
_LIBELLES_STATUT: dict[str, str] = {
    "brouillon": "Brouillon",
    "emise": "Émise",
    "annulee": "Annulée",
    "remplace_par": "Remplacée",
}

#: Taux d'indemnité de vacances admis dans le périmètre Camp LilySO
#: (règle 03) — mêmes deux valeurs que
#: `app/pages_ui/tableau_de_bord.py::_TAUX_VACANCES_OPTIONS`, dupliquées
#: ici (constante privée d'un autre module de rendu).
_TAUX_VACANCES_OPTIONS: tuple[str, ...] = ("0.04", "0.06")

#: Bornes des sélecteurs de date — mêmes valeurs que
#: `app/pages_ui/tableau_de_bord.py` (bug UI corrigé après livraison,
#: cf. docstring de ce module dans `tableau_de_bord.py`).
_DATE_NAISSANCE_MIN = date(date.today().year - 100, 1, 1)
_DATE_NAISSANCE_MAX = date.today()
_DATE_EMPLOI_MIN = date(date.today().year - 50, 1, 1)
_DATE_EMPLOI_MAX = date(date.today().year + 5, 12, 31)

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
    """Section (a) — champs `Employee`, modification des informations
    principales et modification fiscale (Req 5.1, 11).

    Bug UI corrigé après livraison : la fiche détaillée n'affichait ces
    champs qu'en lecture seule — aucun moyen de corriger un nom affiché,
    une date de naissance, un titre d'emploi, un taux horaire de base,
    une date d'embauche/fin d'emploi ou un taux d'indemnité de vacances
    après la création de l'employé. Le formulaire ci-dessous couvre
    exactement les mêmes 7 champs que le formulaire de création
    (`tableau_de_bord.py::_afficher_formulaire_creation`, Req 4.7),
    hormis `province_travail` (fixée à `Juridiction.QUEBEC`, non
    éditable — règle 03).
    """
    st.subheader("Informations employé")

    st.write(f"id : {employe.id}")
    st.write(f"Province de travail : {employe.province_travail.value} (fixe)")

    st.write("**Modification des informations principales**")
    with st.form(f"fed_formulaire_informations_{employe.id}"):
        nom_affichage = st.text_input(
            "Nom affiché",
            value=employe.nom_affichage,
            key=f"fed_nom_affichage_{employe.id}",
        )
        date_naissance = st.date_input(
            "Date de naissance",
            value=employe.date_naissance,
            min_value=_DATE_NAISSANCE_MIN,
            max_value=_DATE_NAISSANCE_MAX,
            key=f"fed_date_naissance_{employe.id}",
        )
        titre_emploi = st.text_input(
            "Titre d'emploi",
            value=employe.titre_emploi,
            key=f"fed_titre_emploi_{employe.id}",
        )
        taux_horaire_base = st.text_input(
            "Taux horaire de base ($)",
            value=str(employe.taux_horaire_base),
            key=f"fed_taux_horaire_base_{employe.id}",
        )
        date_embauche = st.date_input(
            "Date d'embauche",
            value=employe.date_embauche,
            min_value=_DATE_EMPLOI_MIN,
            max_value=_DATE_EMPLOI_MAX,
            key=f"fed_date_embauche_{employe.id}",
        )
        date_fin_emploi = st.date_input(
            "Date de fin d'emploi (optionnel)",
            value=employe.date_fin_emploi,
            min_value=_DATE_EMPLOI_MIN,
            max_value=_DATE_EMPLOI_MAX,
            key=f"fed_date_fin_emploi_{employe.id}",
        )
        index_taux_vacances = _TAUX_VACANCES_OPTIONS.index(
            str(employe.taux_indemnite_vacances)
        ) if str(employe.taux_indemnite_vacances) in _TAUX_VACANCES_OPTIONS else 0
        taux_indemnite_vacances = st.selectbox(
            "Taux d'indemnité de vacances",
            _TAUX_VACANCES_OPTIONS,
            index=index_taux_vacances,
            key=f"fed_taux_indemnite_vacances_{employe.id}",
        )
        soumis_informations = st.form_submit_button(
            "Mettre à jour les informations principales", type="primary"
        )

    if soumis_informations:

        def _mettre_a_jour_informations_et_enregistrer() -> Employee:
            # Même discipline que la section fiscale ci-dessous (Req
            # 11.4) : les deux opérations sont enchaînées dans une seule
            # fonction passée à `executer_avec_capture` — si la
            # reconstruction immuable échoue, `enregistrer_employe`
            # n'est jamais atteinte, aucune modification partielle n'est
            # jamais persistée.
            nouvel_employe = mettre_a_jour_informations_principales(
                employe,
                nom_affichage=nom_affichage,
                date_naissance=date_naissance,
                titre_emploi=titre_emploi,
                taux_horaire_base=Decimal(taux_horaire_base),
                date_embauche=date_embauche,
                date_fin_emploi=date_fin_emploi,
                taux_indemnite_vacances=Decimal(taux_indemnite_vacances),
            )
            enregistrer_employe(nouvel_employe)
            return nouvel_employe

        try:
            resultat_informations = executer_avec_capture(
                _mettre_a_jour_informations_et_enregistrer
            )
        except InvalidOperation:
            st.error(
                "ValueError: le taux horaire de base doit être un nombre "
                "décimal valide (ex. \"18.50\")."
            )
        else:
            if isinstance(resultat_informations, ErreurDomaineAffichable):
                st.error(
                    f"{resultat_informations.type_exception}: "
                    f"{resultat_informations.message}"
                )
            else:
                st.success(
                    f"Informations principales de {resultat_informations.id} "
                    "mises à jour."
                )
                st.rerun()

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
        prenom = st.text_input(
            "Prénom",
            value=(fiche_existante.prenom or "") if fiche_existante else "",
            key=f"fed_coord_prenom_{employe_id}",
        )
        nom = st.text_input(
            "Nom",
            value=(fiche_existante.nom or "") if fiche_existante else "",
            key=f"fed_coord_nom_{employe_id}",
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
            prenom=prenom or None,
            nom=nom or None,
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
    """Section (c) — années, tableau des paies, cumuls annuels (Req 5.2 à 5.6).

    Bug UI corrigé après livraison (demande explicite de l'utilisateur) :

    1. La liste déroulante des paies est remplacée par un vrai tableau
       (colonnes : Numéro de période | Id de la paie | Version | Statut
       | Salaire net | Date de création | Date de paiement | Actions).
    2. Seule la version la plus récente de chaque `numero_periode` est
       affichée (:func:`dernieres_versions_par_periode`) — les versions
       intermédiaires d'un brouillon poursuivi plusieurs fois restent
       dans le registre mais n'apparaissent plus ici.
    3. La liste déroulante d'année reste, valeur par défaut = année la
       plus récente disponible (dernier élément de la liste triée).
    4. Colonne Actions : bouton « Modifier » (route vers le
       Formulaire_Paie, pré-rempli, pour un `BROUILLON`) ou « Voir le
       bulletin » (route vers le Bulletin_De_Paie, pour toute autre
       statut — `EMISE`/`ANNULEE`/`REMPLACE_PAR`).
    """
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
        annees = annees_disponibles(resumes)
        saisons_par_annee = regrouper_saison_par_annee(resumes)
        options_annees = [
            formater_option_annee(annee, saisons_par_annee.get(annee))
            for annee in annees
        ]
        # Valeur par défaut = année la plus récente (dernier élément,
        # `annees_disponibles` retourne un tuple trié croissant).
        index_annee = st.selectbox(
            "Année fiscale",
            options=range(len(annees)),
            format_func=lambda i: options_annees[i],
            index=len(annees) - 1,
            key=f"fed_annee_{employe_id}",
        )
        annee_selectionnee = annees[index_annee]

        paies_annee = dernieres_versions_par_periode(
            filtrer_par_annee(resumes, annee_selectionnee)
        )
        st.write(f"Paies de l'année {annee_selectionnee} :")
        _afficher_tableau_paies(employe_id, paies_annee)

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
            st.write(f"**Cumuls annuels {annee_selectionnee}**")
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
        st.session_state["fp_employe_id_precharge"] = employe_id
        # Bug UI corrigé après livraison : ce bouton ne faisait
        # qu'écrire `st.session_state` sans jamais naviguer — corrigé
        # par `st.switch_page` (même patron que `tableau_de_bord.py`).
        from app.pages_ui._navigation import page_formulaire_paie

        st.switch_page(page_formulaire_paie)


def _afficher_tableau_paies(
    employe_id: str, paies_annee: tuple[LignePaieResume, ...]
) -> None:
    """Tableau des paies de l'année sélectionnée avec colonne Actions
    (bug UI corrigé après livraison, demande explicite de l'utilisateur).

    Colonnes : Numéro de période | Id de la paie | Version | Statut |
    Salaire net | Date de création | Date de paiement | Actions.
    """
    if not paies_annee:
        st.info("Aucune paie pour l'année sélectionnée.")
        return

    proportions = [1, 2, 1, 1, 1, 2, 2, 2]
    entetes = st.columns(proportions)
    for col, libelle in zip(
        entetes,
        [
            "Numéro de période",
            "Id de la paie",
            "Version",
            "Statut",
            "Salaire net",
            "Date de création",
            "Date de paiement",
            "Actions",
        ],
    ):
        with col:
            st.markdown(f"**{libelle}**")

    for resume in paies_annee:
        (
            col_periode,
            col_id,
            col_version,
            col_statut,
            col_net,
            col_creation,
            col_paiement,
            col_actions,
        ) = st.columns(proportions)

        with col_periode:
            st.write(resume.numero_periode)
        with col_id:
            st.write(resume.id_paie)
        with col_version:
            st.write(resume.version)
        with col_statut:
            st.write(_LIBELLES_STATUT.get(resume.statut, resume.statut))
        with col_net:
            st.write(f"{resume.net} $")
        with col_creation:
            st.write(resume.date_creation)
        with col_paiement:
            st.write(resume.date_paiement if resume.date_paiement else "—")
        with col_actions:
            if resume.statut == StatutDePaie.BROUILLON.value:
                if st.button(
                    "Modifier",
                    key=f"fed_modifier_{employe_id}_{resume.id_paie}",
                ):
                    st.session_state["fp_employe_id_precharge"] = employe_id
                    st.session_state["fp_nouvelle_id_paie_precharge"] = (
                        resume.id_paie
                    )
                    from app.pages_ui._navigation import page_formulaire_paie

                    st.switch_page(page_formulaire_paie)
            else:
                if st.button(
                    "Voir le bulletin",
                    key=f"fed_bulletin_{employe_id}_{resume.id_paie}",
                ):
                    st.session_state[bulletin_paie.CLE_ID_PAIE_CIBLE] = (
                        resume.id_paie
                    )
                    from app.pages_ui._navigation import page_bulletin_paie

                    st.switch_page(page_bulletin_paie)



