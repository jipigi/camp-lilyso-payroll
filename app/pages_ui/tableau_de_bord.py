"""Tableau_De_Bord — page d'accueil de l'Interface_Streamlit (Req 4).

Spec de référence : ``interface-streamlit`` — tâche 22.1.
Design de référence : ``design.md`` §Architecture « Navigation
multipage » ; §Components §2 (`annuaire_employes.py`), §4
(`dernieres_paies.py`).

Ce module porte la fonction unique :func:`render` qui affiche la liste
des Fiches_Employe de l'Annuaire_Employes (Req 4.1, 4.2), un raccourci
par ligne pour ajouter une paie (Req 4.5) ou naviguer vers la
Fiche_Employe_Detaillee (Req 4.6), et un bouton qui route vers la page
dédiée de création d'un nouvel employé (Req 4.4 ;
`app/pages_ui/nouvel_employe.py`).

Couche de rendu (`app/pages_ui/`) : ce module **peut** importer
``streamlit``, à la différence de `app/logique_metier/` (Req 1.1, 1.3).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par `lister_employes` est enveloppée par `executer_avec_capture` —
aucun `except Exception`/`except BaseException` générique n'est
présent dans ce module (Req 16.1, 16.3).

Bug UI corrigé après livraison (Req 4.4, Req 4.5, Req 4.6) :

1. Les boutons « Ajouter une paie » et « Voir la fiche » ne faisaient
   qu'écrire `st.session_state` sans jamais déclencher de navigation —
   corrigé par `st.switch_page` (voir `app/pages_ui/_navigation.py` pour
   la raison technique du registre de pages plutôt qu'un chemin de
   fichier).
2. Le formulaire de création d'employé vivait directement sur cette
   page, ce qui empêchait le nouvel employé d'apparaître dans la liste
   ci-dessus après confirmation (la liste avait déjà été rendue plus
   haut dans le même run de script) et ne correspondait pas au
   Requirement 4 AC4 (écran dédié). Extrait vers
   `app/pages_ui/nouvel_employe.py`, atteint via `st.switch_page`.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.logique_metier.annuaire_employes import lister_employes
from app.logique_metier.dernieres_paies import (
    derniere_paie_creee,
    lire_resumes_paies,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from models.employee import Employee

#: Clés de `st.session_state` transportant la sélection d'employé et
#: d'année vers les pages voisines (Req 4.5, 4.6).
_CLE_EMPLOYE_SELECTIONNE = "employe_id_selectionne"
_CLE_ANNEE_PAIE_DEFAUT = "annee_paie_defaut"

#: Libellés d'affichage des statuts de paie (`StatutDePaie`, valeurs
#: internes en minuscules) — bug UI corrigé après livraison (Req 4.2) :
#: le Tableau_De_Bord affiche désormais le statut et la date pertinente
#: de la dernière paie créée pour chaque employé.
_LIBELLES_STATUT: dict[str, str] = {
    "brouillon": "Brouillon",
    "emise": "Émise",
    "annulee": "Annulée",
    "remplace_par": "Remplacée",
}


def render() -> None:
    """Affiche le Tableau_De_Bord — liste des employés et création (Req 4).

    Liste chaque Fiche_Employe (`id`, `nom_affichage`, dernière année de
    paie ou indication explicite d'absence — Req 4.1, 4.2, 4.3), offre
    un raccourci par ligne pour ajouter une paie ou consulter la Fiche_
    Employe_Detaillee (Req 4.5, 4.6), et un bouton qui route vers la
    page dédiée de création d'un nouvel employé (Req 4.4).
    """
    st.header("Tableau de bord — Employés")

    resultat_employes = executer_avec_capture(lister_employes)
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    _afficher_liste_employes(employes)

    st.divider()
    if st.button("Ajouter un nouvel employé", type="primary"):
        from app.pages_ui._navigation import page_nouvel_employe

        st.switch_page(page_nouvel_employe)


def _afficher_liste_employes(employes: tuple[Employee, ...]) -> None:
    """Affiche une ligne par Fiche_Employe avec ses raccourcis (Req 4.1 à 4.6).

    Bug UI corrigé après livraison (Req 4.2) : chaque ligne affiche
    désormais aussi le statut de la dernière paie créée pour l'employé
    (Brouillon/Émise/Annulée/Remplacée) et la date pertinente — date
    d'émission si Émise/Annulée/Remplacée (`date_emission`), date de
    dernier enregistrement si Brouillon (`date_creation`, seule date
    renseignée dans ce cas).
    """
    if not employes:
        st.info("Aucun employé enregistré dans l'Annuaire_Employes.")
        return

    # En-têtes de colonnes — mêmes proportions que les lignes ci-dessous
    # (Req 4.2), pour que l'opérateur identifie chaque colonne sans
    # deviner son contenu.
    col_entete_id, col_entete_nom, col_entete_derniere_paie, col_entete_actions = (
        st.columns([2, 3, 3, 3])
    )
    with col_entete_id:
        st.markdown("**No. d'employé**")
    with col_entete_nom:
        st.markdown("**Prénom et nom**")
    with col_entete_derniere_paie:
        st.markdown("**Dernière paie**")
    with col_entete_actions:
        st.markdown("**Actions**")

    for employe in employes:
        resultat_resumes = executer_avec_capture(
            lambda employe_id=employe.id: lire_resumes_paies(employe_id)
        )
        if isinstance(resultat_resumes, ErreurDomaineAffichable):
            derniere_paie = None
            erreur_resumes: ErreurDomaineAffichable | None = resultat_resumes
        else:
            derniere_paie = derniere_paie_creee(resultat_resumes)
            erreur_resumes = None

        col_id, col_nom, col_derniere_paie, col_actions = st.columns([2, 3, 3, 3])

        with col_id:
            st.write(employe.id)
        with col_nom:
            st.write(employe.nom_affichage)
        with col_derniere_paie:
            if erreur_resumes is not None:
                st.write(
                    f"{erreur_resumes.type_exception}: {erreur_resumes.message}"
                )
            elif derniere_paie is None:
                st.write("Aucune paie enregistrée")
            else:
                libelle_statut = _LIBELLES_STATUT.get(
                    derniere_paie.statut, derniere_paie.statut
                )
                date_pertinente = (
                    derniere_paie.date_emission
                    if derniere_paie.date_emission
                    else derniere_paie.date_creation
                )
                st.write(f"{libelle_statut} — {date_pertinente}")
        with col_actions:
            if st.button(
                "Ajouter une paie",
                key=f"ajouter_paie_{employe.id}",
                type="primary",
            ):
                st.session_state[_CLE_EMPLOYE_SELECTIONNE] = employe.id
                st.session_state[_CLE_ANNEE_PAIE_DEFAUT] = date.today().year
                # Bug UI corrigé après livraison : les deux boutons ne
                # faisaient qu'écrire `st.session_state` sans jamais
                # déclencher la navigation — `st.switch_page` complète
                # ce raccourci en routant réellement vers la page
                # « Nouvelle paie / correction » (Req 4.5). L'objet
                # `Page` (pas un chemin de fichier) est requis ici car
                # la page est définie par un callable
                # (`app/pages_ui/_navigation.py`).
                from app.pages_ui._navigation import page_formulaire_paie

                st.switch_page(page_formulaire_paie)
            if st.button("Voir la fiche", key=f"voir_fiche_{employe.id}"):
                st.session_state[_CLE_EMPLOYE_SELECTIONNE] = employe.id
                # Idem (Req 4.6) — route vers la Fiche_Employe_Detaillee.
                from app.pages_ui._navigation import page_fiche_employe

                st.switch_page(page_fiche_employe)
