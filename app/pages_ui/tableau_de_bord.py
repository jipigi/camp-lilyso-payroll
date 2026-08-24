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

Bug UI signalé après démo (demande explicite de l'utilisateur) : le
tableau des employés (:func:`_afficher_liste_employes`) était un faux
tableau construit avec `st.columns`/`<div>` — remplacé par un véritable
élément HTML `<table>` sémantique. Les actions par ligne (« Ajouter une
paie », « Voir la fiche », lien de la dernière paie), auparavant des
`st.button` déclenchant `st.switch_page`, sont désormais des liens
`<a href="...">` naviguant par paramètres d'URL (`st.query_params`) —
un widget Streamlit natif ne pouvant pas être imbriqué dans un
`<table>` HTML injecté par `st.markdown`.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote

import streamlit as st

from app.logique_metier.annuaire_employes import lister_employes
from app.logique_metier.bilan_fiscal import (
    PeriodeFiscale,
    TableauBilanFiscal,
    construire_options_annee,
    construire_tableau_bilan_fiscal,
    determiner_annee_par_defaut,
    filtrer_paies_par_periode,
    lire_annees_avec_paie_active,
    lire_paies_emises,
    resoudre_periode_a_afficher,
)
from app.logique_metier.dernieres_paies import (
    LignePaieResume,
    lire_resumes_paies,
    paies_pour_colonne,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from models.employee import Employee
from models.enums import StatutDePaie
from models.payroll_result import PayrollResult

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

#: Clé de `st.session_state` portant le libellé de l'Annee_Complete
#: actuellement affichée/présélectionnée dans le Selecteur_De_Periode_
#: Global — persiste le choix manuel de l'opérateur pour la durée de la
#: session (spec ``tableau-de-bord-periode-globale``, design.md
#: Décision 2). Ce sélecteur pilote désormais à la fois la section
#: « Employés » et la section « Bilan fiscal » (auparavant local à cette
#: seconde section uniquement, sous l'ancienne clé
#: ``bilan_fiscal_periode_libelle``). Cette clé est aussi le ``key=`` du
#: `st.selectbox` de :func:`_resoudre_annee_selectionnee` — Streamlit
#: lie alors directement la sélection de l'opérateur à cette entrée de
#: `st.session_state`, sans qu'aucune écriture manuelle ne survienne
#: après l'instanciation du widget pour cette même clé (interdit par
#: Streamlit).
_CLE_ANNEE_SELECTIONNEE_LIBELLE = "tdb_annee_selectionnee_libelle"

#: CSS scoped du Bilan_Fiscal — même convention que
#: `bulletin_paie.py::_CSS_BULLETIN` (classes préfixées, ici
#: `bilan-fiscal-`, pour ne jamais entrer en collision avec les classes
#: `bulletin-*`). Fournit : une ligne d'en-tête de colonnes
#: (`.bilan-fiscal-entete`), un bandeau de section fusionné sur trois
#: colonnes (`.bilan-fiscal-section-entete` — Requirements 6.1, 8.1),
#: des lignes de total (`.bilan-fiscal-total`, `.bilan-fiscal-grand-
#: total`), une ligne à cellule QC/CA fusionnée
#: (`.bilan-fiscal-combine` — Requirement 9.3), un indicateur textuel (2026_01
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

#: CSS scoped du tableau HTML sémantique des employés (bug UI signalé
#: après démo — remplacement d'un faux tableau construit avec des
#: `<div>`/`st.columns` par un véritable élément `<table>`, structure
#: sémantique correcte pour une liste de données tabulaires). Bug UI
#: signalé après démo (2) : reprend désormais exactement le même patron
#: visuel que le Tableau_Bilan_Fiscal (`_CSS_BILAN_FISCAL`) — même
#: conteneur (`.employes-conteneur`), même absence de bordure par
#: cellule (les bordures par cellule du premier essai rendaient un
#: visuel incorrect), même en-tête bleu foncé/police blanche en gras.
_CSS_LISTE_EMPLOYES = """
<style>
.employes-conteneur {
    margin: 8px 0 16px 0;
    font-family: "Segoe UI", Arial, sans-serif;
}
table.employes-tableau {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}
table.employes-tableau th,
table.employes-tableau td {
    padding: 6px 10px;
    text-align: left;
}
table.employes-tableau thead th {
    background: #2c5f8a;
    color: #ffffff;
    font-weight: 700;
}
a.employes-lien-action {
    color: #2c5f8a;
    text-decoration: underline;
    font-weight: 600;
}
a.employes-lien-nom {
    color: inherit;
    text-decoration: underline;
    font-weight: 600;
}
/* Bouton secondaire HTML (bug UI signalé après démo, demande explicite
   de l'utilisateur — colonne Actions du tableau des employés) : un
   `st.button` natif ne peut pas être imbriqué dans un `<table>` HTML
   injecté par `st.markdown` (même limitation que les liens d'action
   ci-dessus) — ce lien réplique donc en CSS inline le visuel
   **secondaire** du thème centralisé (`.streamlit/config.toml`, Règle
   UI 07 — cas « hors widgets natifs Streamlit », même précédent que
   `bulletin_paie.py::_BOUTON_IMPRIMER_HTML`) : fond clair, bordure
   neutre, aucune couleur primaire (`#1f2c3b`) reproduite ici.
*/
a.employes-bouton-secondaire {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 0.5rem;
    background: #ffffff;
    color: inherit;
    text-decoration: none;
    font-weight: 400;
    white-space: nowrap;
}
a.employes-bouton-secondaire:hover {
    border-color: #2c5f8a;
    color: #2c5f8a;
}
/* Bug UI signalé après démo (2, puis 3) : force le bouton « Ajouter un
   nouvel employé » (`st.container(key="tdb_conteneur_bouton_ajouter_
   employe")`) à s'aligner sur le bord droit réel de sa colonne — donc
   sur le bord droit du tableau des employés ci-dessous, les deux
   partageant la même largeur de page. `display: flex` + `justify-
   content: flex-end` sur le conteneur ne suffisaient pas seuls : son
   enfant direct (`element-container`, injecté par Streamlit) reçoit une
   largeur à 100 % par défaut, ce qui neutralisait le `flex-end` (rien à
   décaler, l'enfant occupait déjà toute la largeur) — largeur forcée à
   `fit-content` sur cet enfant pour que le bouton ne prenne que sa
   propre largeur, seule condition sous laquelle `flex-end` peut
   effectivement le repousser à droite. */
div.st-key-tdb_conteneur_bouton_ajouter_employe {
    display: flex;
    justify-content: flex-end;
}
div.st-key-tdb_conteneur_bouton_ajouter_employe > div[data-testid="element-container"] {
    width: fit-content;
}
</style>
"""

#: Noms de mois français en minuscules (bug UI signalé après démo —
#: format court de date sans heure, ex. « 3 juillet 2026 ») — mêmes 12
#: noms que `bilan_fiscal.py::_NOMS_MOIS`, dupliqués ici en minuscules
#: (constante privée d'un autre module, orthographe différente requise
#: par cet affichage).
_NOMS_MOIS_MINUSCULES: dict[int, str] = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}


def _formater_date_courte(valeur_iso: str) -> str:
    """Formate une date/heure ISO (`date_creation`/`date_emission`,
    chaînes produites par `datetime.isoformat()`) en date courte
    française sans heure (bug UI signalé après démo — l'heure est
    superflue pour ce contexte) : ``"<jour> <mois> <année>"``, ex.
    ``"3 juillet 2026"`` (jour sans zéro initial, mois en minuscules).
    """
    valeur_date = datetime.fromisoformat(valeur_iso).date()
    return (
        f"{valeur_date.day} {_NOMS_MOIS_MINUSCULES[valeur_date.month]} "
        f"{valeur_date.year}"
    )


def _formater_date_sans_annee(valeur_iso: str) -> str:
    """Formate une date/heure ISO en date courte française SANS année
    (bug corrigé — Colonne_Paies, Req 2.4, 2.6) : ``"<jour> <mois>"``,
    ex. ``"29 juillet"`` (jour sans zéro initial, mois en minuscules —
    même convention que :func:`_formater_date_courte`). L'année est
    volontairement omise : la Colonne_Paies n'affiche déjà que les
    paies de l'année sélectionnée par le Selecteur_De_Periode_Global
    (``paies_pour_colonne``) — l'afficher serait redondant.
    """
    valeur_date = datetime.fromisoformat(valeur_iso).date()
    return f"{valeur_date.day} {_NOMS_MOIS_MINUSCULES[valeur_date.month]}"


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

    # Bug UI signalé après démo (4) — la ligne « Grand total » (colonnes
    # QC/CA séparées) avait été retirée à tort (demande précédente de
    # l'utilisateur, ensuite corrigée) : réintégrée, sous « Total des
    # cotisations » — montants à verser à chaque palier de gouvernement
    # (somme du Total des retenues et du Total des cotisations, par
    # juridiction).
    ligne_grand_total = _ligne_total_html(
        "Grand total",
        tableau.grand_total_qc,
        tableau.grand_total_ca,
        css_ligne="bilan-fiscal-grand-total",
    )

    # Cellule QC/CA fusionnée sur les deux colonnes (Requirement 9.3) —
    # jamais une colonne supplémentaire du Tableau_Bilan_Fiscal
    # (Requirement 5.1, inchangé : exactement trois colonnes). Renommée
    # « Grand total combiné des charges (QC + CA) » (précision : ce
    # total ne porte que les retenues/cotisations, pas les salaires
    # nets, désormais distingués par les deux lignes suivantes).
    ligne_grand_total_combine = (
        '<tr class="bilan-fiscal-combine">'
        "<td>Grand total combiné des charges (QC + CA)</td>"
        f'<td colspan="2" class="bilan-fiscal-combine-valeur">'
        f"{_montant_bilan_ou_indisponible(tableau.grand_total_combine)}</td></tr>"
    )

    # Bug UI signalé après démo (2) — « Total salaires nets » et « Masse
    # salariale totale », toutes deux en cellule fusionnée QC+CA (même
    # raison que ci-dessus), à la suite du Grand total combiné des
    # charges.
    ligne_total_salaires_nets = (
        '<tr class="bilan-fiscal-combine"><td>Total salaires nets</td>'
        f'<td colspan="2" class="bilan-fiscal-combine-valeur">'
        f"{_montant_bilan_ou_indisponible(tableau.total_salaires_nets)}</td></tr>"
    )
    ligne_masse_salariale_totale = (
        '<tr class="bilan-fiscal-combine"><td>Masse salariale totale</td>'
        f'<td colspan="2" class="bilan-fiscal-combine-valeur">'
        f"{_montant_bilan_ou_indisponible(tableau.masse_salariale_totale)}</td></tr>"
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
                    <td colspan="3">Retenues sur les salaires</td>
                </tr>
                {lignes_retenues}
                <tr class="bilan-fiscal-section-entete">
                    <td colspan="3">Cotisations patronales</td>
                </tr>
                {lignes_cotisations}
                {ligne_grand_total}
                {ligne_grand_total_combine}
                {ligne_total_salaires_nets}
                {ligne_masse_salariale_totale}
            </tbody>
        </table>
    </div>
    """


def _resoudre_annee_selectionnee() -> tuple[tuple[PayrollResult, ...] | None, int]:
    """Résout le Selecteur_De_Periode_Global (spec
    ``tableau-de-bord-periode-globale``, design.md Décision 2, 4).

    Lit `lire_paies_emises` via `executer_avec_capture`. En cas de
    succès : construit les options via `construire_options_annee`
    (Requirements 1.1-1.3), la valeur par défaut via
    `determiner_annee_par_defaut`, résout le libellé à afficher via
    `resoudre_periode_a_afficher` (persistance du choix manuel de
    l'opérateur pour la durée de la session, même mécanisme que
    l'ancien sélecteur local — Requirement 1.4, 1.5), affiche le
    `st.selectbox` correspondant, puis retourne
    ``(paies_emises, annee_selectionnee)`` où ``annee_selectionnee`` est
    l'entier extrait de la `PeriodeFiscale` associée au libellé choisi.

    En cas d'échec (`ErreurDomaineAffichable`) : affiche le message
    d'erreur à l'emplacement du sélecteur, sans jamais interrompre le
    reste du rendu de la page (Décision 4), et retourne
    ``(None, date.today().year)`` — `None` signale à l'appelant de ne
    pas rendre la section Bilan fiscal.

    Placement visuel (demande explicite de l'utilisateur) : le
    sélecteur est affiché sur la même ligne que le titre de page
    « Tableau de bord », aligné à droite — pour que l'opérateur
    comprenne immédiatement que cette sélection pilote tout le contenu
    de la page, plutôt qu'une ligne séparée sans lien visuel évident
    avec le titre.
    """
    col_titre, col_selecteur = st.columns([3, 2], vertical_alignment="center")
    with col_titre:
        st.title("Tableau de bord")

    resultat_paies = executer_avec_capture(lire_paies_emises)
    if isinstance(resultat_paies, ErreurDomaineAffichable):
        with col_selecteur:
            st.error(f"{resultat_paies.type_exception}: {resultat_paies.message}")
        return None, date.today().year
    paies_emises = resultat_paies

    # Bug UI corrigé après livraison (demande explicite de l'utilisateur) :
    # `paies_emises` (statut EMISE uniquement) ne suffit pas à dériver
    # toutes les années sélectionnables — une année n'ayant qu'une paie
    # BROUILLON doit rester sélectionnable (la Colonne_Paies l'affiche).
    # Échec non bloquant : en cas d'erreur, le sélecteur reste
    # fonctionnel avec les seules années EMISE/année courante (aucune
    # interruption du reste du rendu, même discipline que le reste de
    # cette fonction).
    resultat_annees_actives = executer_avec_capture(lire_annees_avec_paie_active)
    annees_avec_brouillon = (
        ()
        if isinstance(resultat_annees_actives, ErreurDomaineAffichable)
        else resultat_annees_actives
    )

    annee_courante = date.today().year
    options = construire_options_annee(
        paies_emises, annee_courante, annees_avec_brouillon
    )
    periode_par_defaut = determiner_annee_par_defaut(annee_courante)

    cle_deja_definie = _CLE_ANNEE_SELECTIONNEE_LIBELLE in st.session_state
    valeur_en_session = st.session_state.get(_CLE_ANNEE_SELECTIONNEE_LIBELLE)
    libelle_resolu = resoudre_periode_a_afficher(
        cle_deja_definie, valeur_en_session, periode_par_defaut, options
    )
    if libelle_resolu is None:
        # Cas dégénéré, jamais atteint en pratique — `options` contient
        # toujours au moins l'Option_Annee_Courante_De_Repli.
        libelle_resolu = options[0].libelle

    # Initialise/actualise `st.session_state` AVANT l'instanciation du
    # `st.selectbox` ci-dessous — jamais après (interdit par Streamlit
    # pour un widget lié par `key=`).
    st.session_state[_CLE_ANNEE_SELECTIONNEE_LIBELLE] = libelle_resolu

    with col_selecteur:
        libelle_selectionne = st.selectbox(
            "Année",
            options=[option.libelle for option in options],
            key=_CLE_ANNEE_SELECTIONNEE_LIBELLE,
            label_visibility="collapsed",
        )

    periode_selectionnee = next(
        option.periode for option in options if option.libelle == libelle_selectionne
    )
    return paies_emises, periode_selectionnee.annee


def _afficher_bilan_fiscal(
    paies_emises: tuple[PayrollResult, ...],
    periode_selectionnee: PeriodeFiscale,
) -> None:
    """Section « Bilan fiscal » du Tableau_De_Bord (Requirement 1.1, 2.1-2.3).

    Ne construit plus son propre sélecteur (spec
    ``tableau-de-bord-periode-globale``, design.md Décision 2) —
    ``paies_emises`` et ``periode_selectionnee`` sont déjà résolus par
    :func:`_resoudre_annee_selectionnee`, appelée une seule fois par
    `render()` (Requirement 1.7). N'est pas rendue par l'appelant quand
    la lecture de `lire_paies_emises` a échoué (`paies_emises is None`,
    Décision 4) — cette fonction suppose donc toujours un tuple valide.

    Plus d'early-return sur ``paies_emises`` vide (Décision 3) : le
    Tableau_Bilan_Fiscal est toujours affiché, même intégralement à
    zéro (Requirement 2.2).

    `filtrer_paies_par_periode`, `construire_tableau_bilan_fiscal` et la
    génération du HTML sont enveloppées dans un seul
    `executer_avec_capture(lambda: ...)` (Décision 5, Requirement 2.3) —
    bien que ces fonctions soient pures et totales aujourd'hui, ce seul
    point de capture protège contre une régression future sans jamais
    interrompre le reste de `render()` (la section « Employés » est déjà
    rendue avant l'appel à cette fonction).
    """
    st.header("Bilan fiscal")

    resultat_html = executer_avec_capture(
        lambda: _sans_indentation(
            _construire_html_bilan_fiscal(
                construire_tableau_bilan_fiscal(
                    filtrer_paies_par_periode(paies_emises, periode_selectionnee)
                )
            )
        )
    )
    if isinstance(resultat_html, ErreurDomaineAffichable):
        st.error(f"{resultat_html.type_exception}: {resultat_html.message}")
        return

    st.markdown(_CSS_BILAN_FISCAL + resultat_html, unsafe_allow_html=True)


def render() -> None:
    """Affiche le Tableau_De_Bord — liste des employés et création (Req 4).

    Liste chaque Fiche_Employe (`id`, `nom_affichage`, dernière année de
    paie ou indication explicite d'absence — Req 4.1, 4.2, 4.3), offre
    un raccourci par ligne pour ajouter une paie ou consulter la Fiche_
    Employe_Detaillee (Req 4.5, 4.6), et un bouton qui route vers la
    page dédiée de création d'un nouvel employé (Req 4.4).
    """
    # Selecteur_De_Periode_Global résolu une seule fois, en haut de
    # `render()` (affiche aussi le titre de page « Tableau de bord »,
    # sur la même ligne que le sélecteur — voir docstring de
    # `_resoudre_annee_selectionnee`), avant le rendu de la section
    # « Employés » (spec ``tableau-de-bord-periode-globale``,
    # design.md Décision 2, Requirement 1.7). `paies_emises` vaut
    # `None` si `lire_paies_emises` a échoué (Décision 4) — signale de
    # ne pas rendre la section Bilan fiscal plus bas.
    paies_emises, annee_selectionnee = _resoudre_annee_selectionnee()

    # Bug UI signalé après démo (demande explicite de l'utilisateur) :
    # le bouton « Ajouter un nouvel employé » est désormais aligné à
    # droite du titre de section « Employés », sur la même ligne — même
    # patron `st.columns` que l'alignement du sélecteur de période du
    # Bilan_Fiscal (`_afficher_bilan_fiscal`).
    col_titre_employes, col_bouton_ajouter_employe = st.columns(
        [3, 2], vertical_alignment="center"
    )
    with col_titre_employes:
        st.header("Employés et paies")
    with col_bouton_ajouter_employe:
        # Bug UI signalé après démo (2) : `st.button` occupe par défaut
        # uniquement la largeur de son texte, aligné à gauche de sa
        # colonne — insuffisant pour atteindre le bord droit réel de la
        # page/du tableau ci-dessous. `st.container(key=...)` expose une
        # classe CSS stable (`.st-key-<key>`, même mécanisme que
        # `bulletin_paie.py::bulletin_barre_actions`) ciblée par
        # `_CSS_LISTE_EMPLOYES` pour forcer l'alignement à droite
        # (`display: flex; justify-content: flex-end`).
        with st.container(key="tdb_conteneur_bouton_ajouter_employe"):
            if st.button("Ajouter un nouvel employé", type="primary"):
                from app.pages_ui._navigation import page_nouvel_employe

                st.switch_page(page_nouvel_employe)

    resultat_employes = executer_avec_capture(lister_employes)
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    # TODO(tâche 8.3) : `_afficher_liste_employes` n'accepte pas encore
    # le paramètre `annee_selectionnee` — cette signature sera étendue
    # à la tâche 8.3 (tri par Prénom Nom, retrait de la colonne « No.
    # d'employé », Colonne_Paies enrichie). Câblage anticipé ici pour
    # que `annee_selectionnee` soit déjà transmis dès que la tâche 8.3
    # complète la signature.
    _afficher_liste_employes(employes, annee_selectionnee=annee_selectionnee)

    st.divider()
    if paies_emises is not None:
        periode_selectionnee = PeriodeFiscale(annee=annee_selectionnee, mois=None)
        _afficher_bilan_fiscal(paies_emises, periode_selectionnee)


def _lien_action_employe(*, href: str, texte: str) -> str:
    """Lien HTML d'action de la colonne Actions du tableau des employés
    (bug UI signalé après démo — remplacement des `st.button` par des
    liens `<a>`, nécessaire pour qu'une ligne de tableau reste un `<tr>`
    sémantique plutôt qu'un `st.columns` — un widget Streamlit natif ne
    peut pas être imbriqué dans un `<table>` HTML injecté par
    `st.markdown`).

    Navigation par URL réelle (``href``), même patron que
    `bulletin_paie.py::_lien_fiche_employe` — jamais `st.switch_page`
    (réservé aux boutons Streamlit natifs, inatteignable depuis un bloc
    HTML injecté). Les pages cibles lisent leurs identifiants
    pré-remplis depuis `st.query_params`.
    """
    # `target="_self"` — comportement par défaut demandé (jamais un
    # nouvel onglet, sauf indication explicite) : sans cet attribut,
    # Streamlit ouvre tout lien HTML injecté par `st.markdown` dans un
    # nouvel onglet.
    return (
        f'<a class="employes-lien-action" href="{href}" target="_self">'
        f"{html.escape(texte)}</a>"
    )


def _texte_absence_paie(annee_selectionnee: int) -> str:
    """Texte d'absence explicite de la Colonne_Paies (Req 5.4, 5.6).

    Utilisé aussi bien quand ``paies_pour_colonne`` retourne un tuple
    vide (lecture réussie, aucune paie pour l'année sélectionnée) que
    lorsque l'employé n'a aucune paie du tout — même texte dans les
    deux cas (Requirement 5.4 : peu importe que l'employé possède ou
    non d'autres paies hors de l'année sélectionnée).
    """
    return f"Aucune paie pour {annee_selectionnee}"


def _ligne_colonne_paie_html(employe_id: str, resume: LignePaieResume) -> str:
    """Génère une ligne cliquable de la Colonne_Paies pour ``resume``
    (Req 2.4, 2.5, 2.6) : numéro de période et statut, sous forme de
    lien — même navigation qu'avant cette correction (Formulaire_Paie
    en mode correction si BROUILLON, Bulletin_De_Paie si EMISE). Ne
    modifie jamais le filtrage (`paies_pour_colonne`), le tri, ni les
    `href` — seul le texte affiché change (bug corrigé — le libellé
    précédent affichait systématiquement l'année, redondante avec le
    Selecteur_De_Periode_Global, et omettait le numéro de période).
    """
    if resume.statut == StatutDePaie.EMISE.value:
        date_affichee = _formater_date_sans_annee(resume.date_paiement)
        texte = f"Paie #{resume.numero_periode} - déposée le {date_affichee}"
    else:  # BROUILLON — jamais de date (Req 2.5)
        texte = f"Paie #{resume.numero_periode} - brouillon"

    if resume.statut == StatutDePaie.BROUILLON.value:
        href = (
            "/formulaire-paie"
            f"?employe_id={quote(employe_id)}"
            f"&id_paie={quote(resume.id_paie)}"
        )
    else:
        href = f"/bulletin-paie?id_paie={quote(resume.id_paie)}"
    return _lien_action_employe(href=href, texte=texte)


def _contenu_colonne_paies_html(
    employe_id: str,
    resultat_resumes: tuple[LignePaieResume, ...] | ErreurDomaineAffichable,
    *,
    annee_selectionnee: int,
) -> str:
    """Contenu HTML complet de la Colonne_Paies pour un employé (Req 5.2
    à 5.6).

    Isolation d'erreur (Req 5.5) : si ``resultat_resumes`` est une
    `ErreurDomaineAffichable` (lecture de `lire_resumes_paies` échouée
    pour cet employé), retourne le texte d'erreur — sans affecter les
    autres lignes du tableau (chaque appel est indépendant). Sinon
    (lecture réussie), retourne une ligne par paie de
    `paies_pour_colonne(resultat_resumes, annee_selectionnee)`, séparées
    par `<br>`, ou le texte d'absence explicite (:func:`_texte_absence_paie`)
    si ce filtrage ne retourne aucune paie — jamais le texte d'erreur
    dans ce dernier cas (Req 5.6).
    """
    if isinstance(resultat_resumes, ErreurDomaineAffichable):
        return html.escape(
            f"{resultat_resumes.type_exception}: {resultat_resumes.message}"
        )

    lignes_paies = paies_pour_colonne(resultat_resumes, annee_selectionnee)
    if not lignes_paies:
        return html.escape(_texte_absence_paie(annee_selectionnee))

    return "<br>".join(
        _ligne_colonne_paie_html(employe_id, resume) for resume in lignes_paies
    )


def _construire_html_liste_employes(
    employes_tries: tuple[Employee, ...],
    contenu_colonne_paies_par_employe: dict[str, str],
) -> str:
    """Construit le bloc HTML complet du tableau des employés (Req 3, 4,
    5) — fonction pure, même patron que `_construire_html_bilan_fiscal` :
    ne dépend ni de `streamlit` ni d'aucune lecture disque, reçoit les
    employés déjà triés (`trier_employes_pour_affichage`) et le contenu
    HTML déjà résolu de la Colonne_Paies de chacun
    (:func:`_contenu_colonne_paies_html`), testable par Hypothesis.

    Colonne « No. d'employé » entièrement retirée (Req 3.1) : ni
    `<th>`, ni `<td>` par ligne. `employe.id` continue d'alimenter les
    attributs `href` des liens de la ligne (colonne « Prénom et nom »,
    colonne « Actions »), jamais affiché comme texte visible (Req 3.2).
    """
    lignes_html = []
    for employe in employes_tries:
        # Bug UI signalé après démo (demande explicite de l'utilisateur) :
        # « Voir la fiche » est retiré de la colonne Actions — le nom de
        # l'employé (colonne « Prénom et nom ») porte désormais ce même
        # lien. Seule l'action « Ajouter une paie » reste dans la
        # colonne Actions, sous forme de bouton **secondaire** (Règle UI
        # 07 — action fréquente mais jamais l'action principale
        # attendue de cet écran, contrairement à un futur bouton
        # primaire dédié) plutôt que de lien souligné.
        lien_nom = (
            f'<a class="employes-lien-nom" '
            f'href="/fiche-employe?employe_id={quote(employe.id)}" '
            f'target="_self">'
            f"{html.escape(employe.nom_affichage)}</a>"
        )
        cellule_actions = (
            f'<a class="employes-bouton-secondaire" '
            f'href="/formulaire-paie?employe_id={quote(employe.id)}" '
            f'target="_self">'
            "Ajouter une paie</a>"
        )
        contenu_paies = contenu_colonne_paies_par_employe[employe.id]

        lignes_html.append(
            "<tr>"
            f"<td>{lien_nom}</td>"
            f"<td>{contenu_paies}</td>"
            f"<td>{cellule_actions}</td>"
            "</tr>"
        )

    return f"""
    <div class="employes-conteneur">
        <table class="employes-tableau">
            <thead>
                <tr>
                    <th>Prénom et nom</th>
                    <th>Paies</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {"".join(lignes_html)}
            </tbody>
        </table>
    </div>
    """


def _afficher_liste_employes(
    employes: tuple[Employee, ...], *, annee_selectionnee: int
) -> None:
    """Affiche une ligne par Fiche_Employe avec ses raccourcis (Req 3, 4, 5).

    Tri par `employe.id` croissant (demande explicite de l'utilisateur —
    revient sur le tri par Prénom Nom introduit précédemment) — tri pur,
    sans lecture de `FicheCoordonnees`.

    Colonne_Paies (Req 5) : réutilise le même appel `lire_resumes_paies`
    déjà effectué historiquement par cette fonction (aucun appel SQL
    supplémentaire), enveloppé par `executer_avec_capture` — une
    éventuelle `ErreurDomaineAffichable` est isolée à la ligne de
    l'employé concerné (Req 5.5), sans affecter les autres lignes.

    Bug UI signalé après démo — véritable élément HTML `<table>`
    sémantique (même patron que le Tableau_Bilan_Fiscal), construit par
    la fonction pure :func:`_construire_html_liste_employes` (Req 3, 4,
    5 — testable par Hypothesis sans dépendance à `streamlit`/aux
    lectures disque). Les actions par ligne sont des liens `<a>`
    naviguant par paramètres d'URL (`st.query_params`), un widget
    Streamlit natif ne pouvant pas être imbriqué dans un `<table>` HTML
    injecté par `st.markdown`.
    """
    if not employes:
        st.info("Aucun employé enregistré dans l'Annuaire_Employes.")
        return

    st.markdown(_CSS_LISTE_EMPLOYES, unsafe_allow_html=True)

    employes_tries = tuple(sorted(employes, key=lambda employe: employe.id))

    contenu_colonne_paies_par_employe: dict[str, str] = {}
    for employe in employes_tries:
        resultat_resumes = executer_avec_capture(
            lambda employe_id=employe.id: lire_resumes_paies(employe_id)
        )
        contenu_colonne_paies_par_employe[employe.id] = _contenu_colonne_paies_html(
            employe.id, resultat_resumes, annee_selectionnee=annee_selectionnee
        )

    tableau_html = _construire_html_liste_employes(
        employes_tries, contenu_colonne_paies_par_employe
    )
    st.markdown(_sans_indentation(tableau_html), unsafe_allow_html=True)
