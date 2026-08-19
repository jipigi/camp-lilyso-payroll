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
from decimal import Decimal

import streamlit as st

from app.logique_metier.annuaire_employes import lister_employes
from app.logique_metier.bilan_fiscal import (
    TableauBilanFiscal,
    construire_options_periode,
    construire_tableau_bilan_fiscal,
    determiner_periode_par_defaut,
    filtrer_paies_par_periode,
    lire_paies_emises,
    resoudre_periode_a_afficher,
)
from app.logique_metier.dernieres_paies import (
    derniere_paie_creee,
    lire_resumes_paies,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.pages_ui import bulletin_paie
from models.employee import Employee
from models.enums import StatutDePaie

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

#: Clé de `st.session_state` portant le libellé de la Periode_Fiscale
#: actuellement affichée/présélectionnée dans le Selecteur_De_Periode du
#: Bilan_Fiscal — persiste le choix manuel de l'opérateur pour la durée
#: de la session (Requirement 3.4 ; ``bilan-fiscal-employeur``
#: design.md §Components §2). Cette clé est aussi le ``key=`` du
#: `st.selectbox` de :func:`_afficher_bilan_fiscal` — Streamlit lie
#: alors directement la sélection de l'opérateur à cette entrée de
#: `st.session_state`, sans qu'aucune écriture manuelle ne survienne
#: après l'instanciation du widget pour cette même clé (interdit par
#: Streamlit).
_CLE_PERIODE_LIBELLE = "bilan_fiscal_periode_libelle"

#: CSS scoped du Bilan_Fiscal — même convention que
#: `bulletin_paie.py::_CSS_BULLETIN` (classes préfixées, ici
#: `bilan-fiscal-`, pour ne jamais entrer en collision avec les classes
#: `bulletin-*`). Fournit : une ligne d'en-tête de colonnes
#: (`.bilan-fiscal-entete`), un bandeau de section fusionné sur trois
#: colonnes (`.bilan-fiscal-section-entete` — Requirements 6.1, 8.1),
#: des lignes de total (`.bilan-fiscal-total`, `.bilan-fiscal-grand-
#: total`), une ligne à cellule QC/CA fusionnée
#: (`.bilan-fiscal-combine` — Requirement 9.3), un indicateur textuel
#: d'indisponibilité (`.bilan-fiscal-indisponible` — Requirement 7.3,
#: 9.4) et une puce visible de classification CNESST en attente
#: (`.bilan-fiscal-badge-attente` — Requirement 8.8).
_CSS_BILAN_FISCAL = """
<style>
.bilan-fiscal-conteneur {
    margin: 8px 0 16px 0;
    font-family: "Segoe UI", Arial, sans-serif;
}
table.bilan-fiscal-tableau {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}
table.bilan-fiscal-tableau th,
table.bilan-fiscal-tableau td {
    padding: 6px 10px;
    text-align: left;
}
table.bilan-fiscal-tableau th:not(:first-child),
table.bilan-fiscal-tableau td:not(:first-child) {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
tr.bilan-fiscal-entete th {
    background: #2c5f8a;
    color: #ffffff;
    font-weight: 700;
}
tr.bilan-fiscal-section-entete td {
    font-weight: 700;
    padding-top: 14px;
    text-align: left;
}
tr.bilan-fiscal-total td {
    border-top: 1px solid #999999;
    font-weight: 700;
}
tr.bilan-fiscal-grand-total td {
    border-top: 2px solid #2c5f8a;
    font-weight: 700;
    font-size: 15px;
    color: #2c5f8a;
}
tr.bilan-fiscal-combine td {
    font-weight: 700;
    font-size: 15px;
    background: #eaf3ea;
    border: 1px solid #a7d0a7;
}
tr.bilan-fiscal-combine td.bilan-fiscal-combine-valeur {
    text-align: right;
}
.bilan-fiscal-indisponible {
    font-style: italic;
    color: #999999;
}
.bilan-fiscal-badge-attente {
    display: inline-block;
    margin-left: 8px;
    padding: 1px 8px;
    font-size: 11px;
    font-weight: 600;
    color: #8a5a00;
    background: #fff3cd;
    border: 1px solid #d9a300;
    border-radius: 10px;
    white-space: nowrap;
}
.bilan-fiscal-non-applicable {
    color: #999999;
}
</style>
"""

#: CSS scoped des en-têtes de colonnes du tableau des employés (bug UI
#: signalé après démo) — fond bleu foncé, police blanche, même teinte
#: que `_CSS_BILAN_FISCAL::tr.bilan-fiscal-entete` pour une cohérence
#: visuelle entre les deux tableaux de cette page.
_CSS_LISTE_EMPLOYES = """
<style>
.employes-entete-cellule {
    background: #2c5f8a;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 10px;
    border-radius: 4px;
}
</style>
"""


def _sans_indentation(bloc_html: str) -> str:
    """Supprime l'indentation de chaque ligne de ``bloc_html`` (bug UI).

    Même patron que `bulletin_paie.py::_retirer_indentation` — le
    Markdown de Streamlit interprète toute ligne indentée de 4 espaces
    ou plus comme un bloc de code littéral (règle CommonMark), ce qui
    empêcherait le rendu HTML même avec `unsafe_allow_html=True`.
    Purement une transformation de mise en forme du texte.
    """
    return "\n".join(ligne.lstrip() for ligne in bloc_html.splitlines())


def _montant_bilan(valeur: Decimal) -> str:
    """Formate un montant `Decimal` toujours calculable (`LigneBilan.qc`/
    `.ca`) — deux décimales, même convention `f"{montant} $"` que
    `bulletin_paie.py`. Aucune conversion `float` (règle 01) : ``valeur``
    reste un `Decimal` jusqu'à cette interpolation finale en chaîne."""
    return f"{valeur} $"


def _montant_bilan_ou_indisponible(valeur: Decimal | None) -> str:
    """Formate un montant de total potentiellement indisponible
    (`Decimal | None` — Requirement 7.3, 9.4) : ``None`` devient un
    indicateur textuel explicite plutôt qu'un montant calculé."""
    if valeur is None:
        return '<span class="bilan-fiscal-indisponible">Indisponible</span>'
    return _montant_bilan(valeur)


def _montant_ou_tiret(valeur: Decimal, *, applicable: bool) -> str:
    """Formate la cellule d'une ligne mono-juridictionnelle (bug UI
    signalé après démo) : la colonne dont la juridiction ne s'applique
    jamais (ex. la colonne Canada pour le RRQ) affiche un tiret plutôt
    que ``0,00 $`` — un montant à zéro suggérerait à tort qu'un calcul
    a eu lieu pour cette juridiction, alors qu'elle ne s'applique
    structurellement jamais à cette ligne."""
    if not applicable:
        return '<span class="bilan-fiscal-non-applicable">—</span>'
    return _montant_bilan(valeur)


def _ligne_bilan_html(
    libelle: str,
    qc: Decimal,
    ca: Decimal,
    *,
    qc_applicable: bool = True,
    ca_applicable: bool = True,
) -> str:
    """Génère une ligne ``<tr>`` de détail (RRQ, RQAP, AE, etc.) — les
    deux colonnes de `LigneBilan` sont toujours calculables (jamais
    `None`), donc jamais d'indicateur d'indisponibilité sur ces lignes.
    ``qc_applicable``/``ca_applicable`` distinguent la colonne réellement
    attribuée (montant affiché) de celle qui ne s'applique jamais à
    cette juridiction (tiret affiché, voir :func:`_montant_ou_tiret`)."""
    return (
        f"<tr><td>{libelle}</td>"
        f"<td>{_montant_ou_tiret(qc, applicable=qc_applicable)}</td>"
        f"<td>{_montant_ou_tiret(ca, applicable=ca_applicable)}</td></tr>"
    )


def _ligne_total_html(
    libelle: str, qc: Decimal | None, ca: Decimal | None, *, css_ligne: str
) -> str:
    """Génère une ligne ``<tr>`` de total (« Total des retenues », « Total
    des cotisations », « Grand total ») — colonnes `Decimal | None`,
    l'indisponibilité éventuelle de l'une ou l'autre étant affichée
    indépendamment (Requirement 7.3, 9.4)."""
    return (
        f'<tr class="{css_ligne}"><td>{libelle}</td>'
        f"<td>{_montant_bilan_ou_indisponible(qc)}</td>"
        f"<td>{_montant_bilan_ou_indisponible(ca)}</td></tr>"
    )


def _construire_html_bilan_fiscal(tableau: TableauBilanFiscal) -> str:
    """Construit le bloc HTML du Tableau_Bilan_Fiscal (Requirements 5 à
    9). Aucune donnée interpolée ici n'est une donnée personnelle
    (uniquement des montants agrégés et des libellés fixes) — aucun
    `html.escape` n'est nécessaire (design.md §Architecture décision
    n° 3), à la différence de `bulletin_paie.py`.
    """
    lignes_retenues = "".join(
        [
            _ligne_bilan_html(
                tableau.ligne_rrq.libelle,
                tableau.ligne_rrq.qc,
                tableau.ligne_rrq.ca,
                ca_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_rqap.libelle,
                tableau.ligne_rqap.qc,
                tableau.ligne_rqap.ca,
                ca_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_ae.libelle,
                tableau.ligne_ae.qc,
                tableau.ligne_ae.ca,
                qc_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_impot.libelle,
                tableau.ligne_impot.qc,
                tableau.ligne_impot.ca,
            ),
            _ligne_total_html(
                "Total des retenues",
                tableau.total_retenues_qc,
                tableau.total_retenues_ca,
                css_ligne="bilan-fiscal-total",
            ),
        ]
    )

    # Indication visible adjacente à la ligne CNESST si au moins une
    # Paie_Agregee repose sur une classification en attente (Requirement
    # 8.8) — jamais de donnée personnelle, uniquement un libellé fixe.
    libelle_cnesst = tableau.ligne_cnesst.libelle
    if tableau.cnesst_en_attente_classification:
        libelle_cnesst += (
            ' <span class="bilan-fiscal-badge-attente">'
            "Classification en attente</span>"
        )

    lignes_cotisations = "".join(
        [
            _ligne_bilan_html(
                tableau.ligne_rrq_employeur.libelle,
                tableau.ligne_rrq_employeur.qc,
                tableau.ligne_rrq_employeur.ca,
                ca_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_rqap_employeur.libelle,
                tableau.ligne_rqap_employeur.qc,
                tableau.ligne_rqap_employeur.ca,
                ca_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_ae_employeur.libelle,
                tableau.ligne_ae_employeur.qc,
                tableau.ligne_ae_employeur.ca,
                qc_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_fss.libelle,
                tableau.ligne_fss.qc,
                tableau.ligne_fss.ca,
                ca_applicable=False,
            ),
            _ligne_bilan_html(
                libelle_cnesst,
                tableau.ligne_cnesst.qc,
                tableau.ligne_cnesst.ca,
                ca_applicable=False,
            ),
            _ligne_bilan_html(
                tableau.ligne_cnt.libelle,
                tableau.ligne_cnt.qc,
                tableau.ligne_cnt.ca,
                ca_applicable=False,
            ),
            _ligne_total_html(
                "Total des cotisations",
                tableau.total_cotisations_qc,
                tableau.total_cotisations_ca,
                css_ligne="bilan-fiscal-total",
            ),
        ]
    )

    ligne_grand_total = _ligne_total_html(
        "Grand total",
        tableau.grand_total_qc,
        tableau.grand_total_ca,
        css_ligne="bilan-fiscal-grand-total",
    )

    # Cellule QC/CA fusionnée sur les deux colonnes (Requirement 9.3) —
    # jamais une colonne supplémentaire du Tableau_Bilan_Fiscal
    # (Requirement 5.1, inchangé : exactement trois colonnes).
    ligne_grand_total_combine = (
        '<tr class="bilan-fiscal-combine"><td>Grand total combiné (QC + CA)</td>'
        f'<td colspan="2" class="bilan-fiscal-combine-valeur">'
        f"{_montant_bilan_ou_indisponible(tableau.grand_total_combine)}</td></tr>"
    )

    return f"""
    <div class="bilan-fiscal-conteneur">
        <table class="bilan-fiscal-tableau">
            <thead>
                <tr class="bilan-fiscal-entete">
                    <th>Retenues et cotisations</th><th>Québec</th><th>Canada</th>
                </tr>
            </thead>
            <tbody>
                <tr class="bilan-fiscal-section-entete">
                    <td colspan="3">Retenues sur le salaire de l'employé</td>
                </tr>
                {lignes_retenues}
                <tr class="bilan-fiscal-section-entete">
                    <td colspan="3">Cotisations patronales</td>
                </tr>
                {lignes_cotisations}
                {ligne_grand_total}
                {ligne_grand_total_combine}
            </tbody>
        </table>
    </div>
    """


def _afficher_bilan_fiscal() -> None:
    """Section « Bilan fiscal » du Tableau_De_Bord (Requirement 1.1).

    Orchestre `lire_paies_emises` (via `executer_avec_capture`),
    `construire_options_periode`, `resoudre_periode_a_afficher`/
    `determiner_periode_par_defaut`, un `st.selectbox` positionné en
    haut à droite (Requirement 2.1), `filtrer_paies_par_periode`, et
    `construire_tableau_bilan_fiscal`. Affiche le message d'absence
    (Requirement 4.1) si `lire_paies_emises` retourne un tuple vide,
    sans Selecteur_De_Periode ni Tableau_Bilan_Fiscal dans ce cas.

    Seul `lire_paies_emises` est enveloppé par `executer_avec_capture` —
    `construire_options_periode`, `filtrer_paies_par_periode` et
    `construire_tableau_bilan_fiscal` sont des fonctions pures totales
    sur tout tuple d'entrée (design.md §Architecture décision n° 2),
    elles ne lèvent jamais d'exception.
    """
    resultat_paies = executer_avec_capture(lire_paies_emises)
    if isinstance(resultat_paies, ErreurDomaineAffichable):
        st.header("Bilan fiscal")
        st.error(f"{resultat_paies.type_exception}: {resultat_paies.message}")
        return
    paies_emises = resultat_paies

    if not paies_emises:
        st.header("Bilan fiscal")
        st.info("Aucune paie émise n'a été trouvée.")
        return

    options = construire_options_periode(paies_emises)
    periode_par_defaut = determiner_periode_par_defaut(date.today(), options)

    cle_deja_definie = _CLE_PERIODE_LIBELLE in st.session_state
    valeur_en_session = st.session_state.get(_CLE_PERIODE_LIBELLE)
    libelle_resolu = resoudre_periode_a_afficher(
        cle_deja_definie, valeur_en_session, periode_par_defaut, options
    )
    if libelle_resolu is None:
        # Cas dégénéré (design.md §Components §2) — en pratique jamais
        # atteint tant qu'au moins une paie EMISE existe (`options` non
        # vide à ce stade), mais couvert défensivement.
        libelle_resolu = options[0].libelle

    # Initialise/actualise `st.session_state` AVANT l'instanciation du
    # `st.selectbox` ci-dessous — jamais après (interdit par Streamlit
    # pour un widget lié par `key=`). Le `st.selectbox` met ensuite
    # lui-même à jour cette même clé lors d'une sélection manuelle de
    # l'opérateur, ce qui assure la persistance du choix (Requirement
    # 3.4) sans écriture manuelle additionnelle après sa création.
    st.session_state[_CLE_PERIODE_LIBELLE] = libelle_resolu

    # Titre à gauche, sélecteur de période à droite, sur la même ligne
    # (bug UI signalé après démo) — même patron `st.columns` que
    # l'alignement des en-têtes du tableau des employés.
    col_titre, col_selecteur = st.columns([3, 2], vertical_alignment="center")
    with col_titre:
        st.header("Bilan fiscal")
    with col_selecteur:
        libelle_selectionne = st.selectbox(
            "Période",
            options=[option.libelle for option in options],
            key=_CLE_PERIODE_LIBELLE,
            label_visibility="collapsed",
        )

    periode_selectionnee = next(
        option.periode for option in options if option.libelle == libelle_selectionne
    )
    paies_periode = filtrer_paies_par_periode(paies_emises, periode_selectionnee)
    tableau = construire_tableau_bilan_fiscal(paies_periode)

    st.markdown(
        _CSS_BILAN_FISCAL + _sans_indentation(_construire_html_bilan_fiscal(tableau)),
        unsafe_allow_html=True,
    )


def render() -> None:
    """Affiche le Tableau_De_Bord — liste des employés et création (Req 4).

    Liste chaque Fiche_Employe (`id`, `nom_affichage`, dernière année de
    paie ou indication explicite d'absence — Req 4.1, 4.2, 4.3), offre
    un raccourci par ligne pour ajouter une paie ou consulter la Fiche_
    Employe_Detaillee (Req 4.5, 4.6), et un bouton qui route vers la
    page dédiée de création d'un nouvel employé (Req 4.4).
    """
    st.title("Tableau de bord")
    st.header("Employés")

    resultat_employes = executer_avec_capture(lister_employes)
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    _afficher_liste_employes(employes)

    if st.button("Ajouter un nouvel employé", type="primary"):
        from app.pages_ui._navigation import page_nouvel_employe

        st.switch_page(page_nouvel_employe)

    st.divider()
    _afficher_bilan_fiscal()


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
    # deviner son contenu. Fond bleu foncé / police blanche (bug UI
    # signalé après démo) — même teinte que les en-têtes du Tableau_
    # Bilan_Fiscal (`_CSS_BILAN_FISCAL::tr.bilan-fiscal-entete`).
    st.markdown(_CSS_LISTE_EMPLOYES, unsafe_allow_html=True)
    col_entete_id, col_entete_nom, col_entete_derniere_paie, col_entete_actions = (
        st.columns([2, 3, 3, 3])
    )
    with col_entete_id:
        st.markdown(
            '<div class="employes-entete-cellule">No. d\'employé</div>',
            unsafe_allow_html=True,
        )
    with col_entete_nom:
        st.markdown(
            '<div class="employes-entete-cellule">Prénom et nom</div>',
            unsafe_allow_html=True,
        )
    with col_entete_derniere_paie:
        st.markdown(
            '<div class="employes-entete-cellule">Dernière paie</div>',
            unsafe_allow_html=True,
        )
    with col_entete_actions:
        st.markdown(
            '<div class="employes-entete-cellule">Actions</div>',
            unsafe_allow_html=True,
        )

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
                # Bug UI corrigé après livraison (Req demande explicite
                # de l'utilisateur) : le libellé de la dernière paie est
                # désormais un lien cliquable — route vers le
                # Formulaire_Paie (mode correction pré-rempli) si
                # BROUILLON, vers le Bulletin_De_Paie si EMISE/ANNULEE/
                # REMPLACE_PAR.
                if st.button(
                    f"{libelle_statut} — {date_pertinente}",
                    key=f"derniere_paie_{employe.id}",
                ):
                    if derniere_paie.statut == StatutDePaie.BROUILLON.value:
                        st.session_state["fp_employe_id_precharge"] = employe.id
                        st.session_state["fp_nouvelle_id_paie_precharge"] = (
                            derniere_paie.id_paie
                        )
                        from app.pages_ui._navigation import page_formulaire_paie

                        st.switch_page(page_formulaire_paie)
                    else:
                        st.session_state[bulletin_paie.CLE_ID_PAIE_CIBLE] = (
                            derniere_paie.id_paie
                        )
                        from app.pages_ui._navigation import page_bulletin_paie

                        st.switch_page(page_bulletin_paie)
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
                #
                # Bug UI corrigé après livraison (2) : `formulaire_paie.py`
                # ne lit jamais `_CLE_EMPLOYE_SELECTIONNE` pour
                # pré-sélectionner l'employé dans la liste déroulante —
                # il lit exclusivement `fp_employe_id_precharge` (même
                # clé que le lien « Dernière paie » ci-dessus et que le
                # bouton « Ajouter une paie » de la Fiche_Employe_
                # Detaillee). Sans cette clé, la liste déroulante
                # revenait toujours au premier employé de l'Annuaire.
                st.session_state["fp_employe_id_precharge"] = employe.id
                from app.pages_ui._navigation import page_formulaire_paie

                st.switch_page(page_formulaire_paie)
            if st.button("Voir la fiche", key=f"voir_fiche_{employe.id}"):
                st.session_state[_CLE_EMPLOYE_SELECTIONNE] = employe.id
                # Idem (Req 4.6) — route vers la Fiche_Employe_Detaillee.
                from app.pages_ui._navigation import page_fiche_employe

                st.switch_page(page_fiche_employe)
