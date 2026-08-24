"""Fiche_Employe_Detaillee — page de détail d'un employé (Req 5, 11, 20.4).

Spec de référence : ``interface-streamlit`` — tâche 23.1.
Design de référence : ``design.md`` §Components §3 (`annuaire_coordonnees.py`
— `FicheCoordonnees`), §4 (`dernieres_paies.py`), §7 (`fiche_employe.py`
— `mettre_a_jour_donnees_fiscales`).

Ce module porte la fonction unique :func:`render` qui regroupe **quatre
sections visuellement distinctes** sur un seul écran (Req 5.1) :

1. **Informations principales** — champs non sensibles de la
   Fiche_Employe (`Employee`), hors données fiscales TD1/TP-1015.3.
2. **Coordonnées opérationnelles** — `FicheCoordonnees` via
   `lire_coordonnees`/`enregistrer_coordonnees` (Requirement 20).
3. **Formulaire TD1 / TP-1015.3 (à mettre à jour chaque année)** — les 6
   champs fiscaux d'`Employee`, invoque `mettre_a_jour_donnees_fiscales`
   puis `enregistrer_employe` (Req 11.1, 11.2, 11.3) ; toute erreur
   traverse `executer_avec_capture` sans qu'aucune modification
   partielle ne soit jamais persistée dans l'Annuaire_Employes — la
   reconstruction immuable (`mettre_a_jour_donnees_fiscales`) échoue
   *avant* tout appel à `enregistrer_employe`, les deux opérations
   étant enchaînées dans une seule fonction passée à
   `executer_avec_capture` (Req 11.4).
4. **Paies** — liste déroulante des années fiscales formatée par
   `formater_option_annee`/`regrouper_saison_par_annee` (Req 5.2),
   liste des paies de l'année sélectionnée via
   `filtrer_par_annee`/`lire_resumes_paies` (Req 5.3), consultation des
   valeurs TD1/TP-1015.3 effectives d'une paie choisie et des cumuls
   YTD de l'année via `lire_cumuls_ytd` (Req 5.4), bouton d'ajout de
   paie qui pré-remplit l'année civile courante (modifiable, Req 5.5),
   et indication explicite d'absence de paie sans lever d'exception
   (Req 5.6).

Bug UI signalé après démo — bascule consultation/édition par section
(sections 1 à 3, jamais la section 4 « Paies » qui n'a pas de mode
consultation/édition à opposer) : chaque section affiche par défaut
uniquement des libellés et leurs valeurs (aucun widget de saisie), avec
un bouton icône crayon (``:material/edit:``, infobulle « Modifier les
informations de cette section ») aligné à droite du titre de section.
Au clic, la section bascule en mode édition (le formulaire déjà existant
avant cette correction), avec un bouton « Annuler » ajouté à droite du
bouton de mise à jour — l'annulation revient au mode consultation sans
appeler la fonction d'enregistrement, donc sans écrire quoi que ce soit
sur disque. Le mode courant de chaque section est piloté par une clé
``st.session_state`` booléenne dédiée (``_CLE_EDITION_INFORMATIONS``,
``_CLE_EDITION_COORDONNEES``, ``_CLE_EDITION_FISCAL``), initialisée à
``False`` (consultation) et jamais partagée entre sections — modifier
une section n'affecte jamais le mode des deux autres.

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

Bug UI corrigé après livraison (lien depuis le Bulletin_De_Paie) : la
pré-sélection de l'employé accepte désormais aussi
`st.query_params["employe_id"]` (paramètre d'URL, ``?employe_id=EMPnnn``),
en priorité sur `st.session_state["employe_id_selectionne"]` — un lien
HTML brut (``<a href="...">``, ex. sur le libellé « Non renseigné » du
NAS dans `bulletin_paie.py`) ne peut écrire aucun `st.session_state`
avant la navigation, à la différence d'un bouton Streamlit natif
(`st.switch_page`).
"""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from app.logique_metier.annuaire_coordonnees import (
    FicheCoordonnees,
    enregistrer_coordonnees,
    formater_nas,
    libelle_employe,
    lire_coordonnees,
    lister_coordonnees,
)
from app.logique_metier.annuaire_employes import (
    enregistrer_employe,
    lister_employes,
    lister_titres_emploi_suggeres,
)
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
from app.pages_ui._navigation import afficher_lien_retour_tableau_de_bord
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

#: Même clé de `st.session_state` que `app/pages_ui/tableau_de_bord.py`
#: — transporte la sélection d'employé courante entre pages (Req 4.6).
#: Dupliquée ici en constante locale plutôt qu'importée (constante
#: privée de `tableau_de_bord.py`) — même discipline que
#: `historique_et_cumuls.py::_CATEGORIES_CUMULS_AFFICHAGE`.
_CLE_EMPLOYE_SELECTIONNE = "employe_id_selectionne"

#: Clés de `st.session_state` pilotant le mode consultation/édition de
#: chaque section (bug UI signalé après démo) — préfixées par
#: `employe.id` pour qu'un changement d'employé sélectionné réinitialise
#: naturellement chaque section en mode consultation (nouvelle clé,
#: absente de `st.session_state`, donc `False` par défaut via
#: `.get(..., False)`), plutôt que de conserver le mode édition d'un
#: employé précédemment sélectionné.
_CLE_EDITION_INFORMATIONS = "fed_edition_informations_{employe_id}"
_CLE_EDITION_COORDONNEES = "fed_edition_coordonnees_{employe_id}"
_CLE_EDITION_FISCAL = "fed_edition_fiscal_{employe_id}"

#: Clé de `st.session_state` portant l'identifiant d'ancre HTML vers
#: lequel défiler au prochain rendu (bug UI signalé après démo — après
#: un enregistrement ou une annulation, l'opérateur se retrouvait
#: ramené en haut de page, la section concernée n'étant plus visible,
#: en particulier la première). Posée juste avant chaque `st.rerun()`
#: qui suit une annulation ou un enregistrement réussi ; consommée une
#: seule fois en fin de :func:`render`, une fois toutes les ancres
#: (posées par :func:`_afficher_entete_section`) déjà rendues sur la
#: page.
_CLE_SCROLL_CIBLE = "fed_scroll_cible"

#: CSS scoped du tableau HTML sémantique des Paies (bug UI signalé après
#: démo — remplacement d'un faux tableau construit avec des `<div>`/
#: `st.columns` par un véritable élément `<table>`, structure sémantique
#: correcte pour une liste de données tabulaires). Même teinte bleu
#: foncé/police blanche que `tableau_de_bord.py::_CSS_LISTE_EMPLOYES`/
#: `_CSS_BILAN_FISCAL`, dupliquée ici (constante privée d'un autre
#: module de rendu), pour une cohérence visuelle entre les tableaux de
#: l'application.
_CSS_TABLEAU_PAIES = """
<style>
.paies-conteneur {
    margin: 8px 0 16px 0;
    font-family: "Segoe UI", Arial, sans-serif;
}
table.paies-tableau {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}
table.paies-tableau th,
table.paies-tableau td {
    padding: 6px 10px;
    text-align: left;
}
table.paies-tableau thead th {
    background: #2c5f8a;
    color: #ffffff;
    font-weight: 700;
}
a.paies-lien-action {
    color: #2c5f8a;
    text-decoration: underline;
    font-weight: 600;
}
/* Bug UI signalé après démo (2, puis 3) : force le bouton « Ajouter
   une paie »
   (`st.container(key="fed_conteneur_bouton_ajouter_paie_<employe_id>")`)
   à s'aligner sur le bord droit réel de sa colonne — même patron que
   `tableau_de_bord.py::tdb_conteneur_bouton_ajouter_employe`, y compris
   le correctif nécessaire sur l'enfant `element-container` (largeur à
   100 % par défaut, neutralisant `justify-content: flex-end` tant
   qu'elle n'est pas réduite à `fit-content`). Le sélecteur cible tout
   conteneur dont la clé commence par ce préfixe (un par employé), via
   `[class*=...]` plutôt qu'une classe exacte.
*/
div[class*="st-key-fed_conteneur_bouton_ajouter_paie_"] {
    display: flex;
    justify-content: flex-end;
}
div[class*="st-key-fed_conteneur_bouton_ajouter_paie_"] > div[data-testid="element-container"] {
    width: fit-content;
}
</style>
"""


def _planifier_defilement_vers(cle_edition: str) -> None:
    """Planifie le défilement automatique vers l'ancre de la section
    ``cle_edition`` (même valeur que l'``id`` HTML posé par
    :func:`_afficher_entete_section`) — à appeler juste avant chaque
    `st.rerun()` suivant une annulation ou un enregistrement réussi.
    """
    st.session_state[_CLE_SCROLL_CIBLE] = cle_edition


def _defiler_vers_cible_en_attente() -> None:
    """Exécute le défilement planifié par :func:`_planifier_defilement_vers`,
    s'il y en a un — à appeler une seule fois, en toute fin de
    :func:`render`, une fois les trois sections (et leurs ancres HTML)
    déjà rendues sur la page. Consomme la clé (`.pop`) pour ne défiler
    qu'une seule fois par rerun.

    `components.html` (plutôt que `st.markdown`) : même raison que le
    bouton « Imprimer » de `bulletin_paie.py` — le Markdown de Streamlit
    assainit le HTML injecté, mais un simple `<script>` sans attribut
    `onclick` y survivrait ; `components.html` est utilisé ici par
    cohérence avec ce précédent, et parce que `window.parent.document`
    (l'application, hors de l'``<iframe>`` isolé du composant) est la
    cible réelle du défilement.
    """
    cible = st.session_state.pop(_CLE_SCROLL_CIBLE, None)
    if not cible:
        return
    components.html(
        f"""
        <script>
            var cible = window.parent.document.getElementById("{cible}");
            if (cible) {{
                cible.scrollIntoView({{behavior: "smooth", block: "start"}});
            }}
        </script>
        """,
        height=0,
    )


def _afficher_entete_section(titre: str, cle_edition: str) -> bool:
    """En-tête de section avec bouton icône crayon aligné à droite (bug
    UI signalé après démo) — titre à gauche, bouton crayon
    (``:material/edit:``, infobulle « Modifier les informations de
    cette section ») à droite, sur la même ligne. Au clic, bascule
    ``st.session_state[cle_edition]`` à ``True`` (mode édition) et
    déclenche un `st.rerun()` immédiat.

    Pose une ancre HTML invisible (``id=cle_edition``) juste avant le
    titre — cible de :func:`_defiler_vers_cible_en_attente` (bug UI
    signalé après démo, défilement automatique après enregistrement/
    annulation).

    Retourne l'état courant du mode édition (``st.session_state.get(
    cle_edition, False)``), lu **avant** tout clic éventuel sur ce même
    rerun — l'appelant s'en sert pour décider quelle branche
    (consultation ou édition) afficher sous cet en-tête.
    """
    st.markdown(f'<div id="{cle_edition}"></div>', unsafe_allow_html=True)
    col_titre, col_bouton = st.columns([5, 1])
    with col_titre:
        st.subheader(titre)
    with col_bouton:
        if st.button(
            "",
            icon=":material/edit:",
            help="Modifier les informations de cette section",
            key=f"{cle_edition}_bouton_crayon",
        ):
            st.session_state[cle_edition] = True
            st.rerun()
    return st.session_state.get(cle_edition, False)

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

#: Libellés d'affichage des onze catégories de `CumulsYTD` (bug UI
#: signalé après démo — le nom brut des attributs Python, ex.
#: ``"rrq_employe"``, n'est pas assez clair pour l'opérateur) — un
#: libellé complet par catégorie, dérivé de la docstring de chaque champ
#: (`models/cumuls.py::CumulsYTD`).
_LIBELLES_CUMULS_AFFICHAGE: dict[str, str] = {
    "brut": "Salaire brut",
    "vacances": "Indemnité de vacances",
    "rrq_employe": "RRQ — part employé",
    "rrq_employeur": "RRQ — part employeur",
    "rqap_employe": "RQAP — part employé",
    "rqap_employeur": "RQAP — part employeur",
    "ae_employe": "Assurance-emploi — part employé",
    "ae_employeur": "Assurance-emploi — part employeur",
    "impot_qc_retenu": "Impôt provincial (Québec) retenu",
    "impot_federal_retenu": "Impôt fédéral retenu",
    "net": "Salaire net",
}


def render() -> None:
    """Rendu de la Fiche_Employe_Detaillee (Req 5.1) — trois sections.

    Sélectionne d'abord l'employé courant (pré-rempli depuis
    `st.session_state["employe_id_selectionne"]` si l'opérateur vient du
    Tableau_De_Bord), puis affiche les trois sections dans l'ordre :
    informations employé, coordonnées, paies.
    """
    afficher_lien_retour_tableau_de_bord()
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
    # Bug UI signalé après démo : un lien HTML externe (ex. depuis le
    # Bulletin_De_Paie, sur le libellé « Non renseigné » d'une donnée
    # manquante) ne peut pas écrire `st.session_state` avant la
    # navigation — contrairement à `st.switch_page`, qui reste réservé
    # aux boutons Streamlit natifs. `st.query_params["employe_id"]`
    # (paramètre d'URL) est donc lu en priorité, avant le repli habituel
    # sur `st.session_state` alimenté par les boutons de navigation
    # internes (Tableau_De_Bord, etc.).
    employe_id_defaut = st.query_params.get(
        "employe_id", st.session_state.get(_CLE_EMPLOYE_SELECTIONNE)
    )
    index_defaut = (
        options_employes.index(employe_id_defaut)
        if employe_id_defaut in options_employes
        else 0
    )
    # Bug UI signalé après démo : le sélecteur affichait l'identifiant
    # brut (`EMPnnn`) plutôt qu'un libellé humainement lisible —
    # `lister_coordonnees()` (lecture groupée, une seule fois, plutôt
    # que Req N appels `lire_coordonnees` répétés dans le `format_func`)
    # fournit Prénom/Nom/Courriel de chaque `FicheCoordonnees` existante ;
    # un employé sans coordonnées saisies affiche uniquement son id.
    resultat_coordonnees_toutes = executer_avec_capture(lambda: lister_coordonnees())
    coordonnees_par_employe_id: dict[str, FicheCoordonnees] = (
        {}
        if isinstance(resultat_coordonnees_toutes, ErreurDomaineAffichable)
        else {f.employe_id: f for f in resultat_coordonnees_toutes}
    )

    # Bug UI signalé après démo, formatage désormais partagé (Req 2.2) :
    # `libelle_employe` (extraite dans `annuaire_coordonnees.py`) remplace
    # l'ancienne closure locale `_libelle_employe` — comportement
    # d'affichage strictement identique.
    employe_id = st.selectbox(
        "Employé",
        options_employes,
        index=index_defaut,
        format_func=lambda eid: libelle_employe(eid, coordonnees_par_employe_id),
        key="fed_employe_id",
    )
    employe = next(e for e in employes if e.id == employe_id)

    # Ordre de section renommé/réordonné (bug UI signalé après démo) :
    # 1. Informations principales ; 2. Coordonnées opérationnelles ;
    # 3. Formulaire TD1 / TP-1015.3 (à mettre à jour chaque année) ;
    # 4. Paies (inchangée, toujours en dernier).
    _section_informations_principales(employe)

    st.divider()
    _section_coordonnees(employe.id)

    st.divider()
    _section_fiscal(employe)

    st.divider()
    _section_paies(employe_id)

    # Exécuté une seule fois, en toute fin de page, une fois les trois
    # ancres HTML (une par section, posées par `_afficher_entete_section`)
    # déjà rendues — voir `_planifier_defilement_vers` (bug UI signalé
    # après démo : après un enregistrement/une annulation, l'opérateur se
    # retrouvait ramené en haut de page, la section concernée disparue
    # de la vue, en particulier la première).
    _defiler_vers_cible_en_attente()


def _section_informations_principales(employe: Employee) -> None:
    """Section 1 — « Informations principales » (Req 5.1, 11).

    Bug UI signalé après démo — mode consultation par défaut (libellés
    et valeurs seuls, aucun widget de saisie), bascule vers le
    formulaire d'édition (inchangé, hormis l'ajout du bouton « Annuler »)
    via le bouton crayon de :func:`_afficher_entete_section`.
    """
    cle_edition = _CLE_EDITION_INFORMATIONS.format(employe_id=employe.id)
    en_edition = _afficher_entete_section("Informations principales", cle_edition)

    # Prénom/Nom proviennent de la `FicheCoordonnees` (bug UI signalé
    # après démo antérieur — voir Coordonnées opérationnelles) — lus ici
    # dans les deux modes (consultation et édition).
    resultat_coordonnees_pour_nom = executer_avec_capture(
        lambda: lire_coordonnees(employe.id)
    )
    fiche_coordonnees_existante: FicheCoordonnees | None = (
        None
        if isinstance(resultat_coordonnees_pour_nom, ErreurDomaineAffichable)
        else resultat_coordonnees_pour_nom
    )

    if not en_edition:
        # Bug UI signalé après démo — affichage en deux colonnes en
        # bureau (`st.columns` reflue automatiquement en une seule
        # colonne empilée sur mobile/écran étroit, comportement natif
        # Streamlit) : colonne de gauche = identité (id, Prénom, Nom,
        # Date de naissance, Titre d'emploi) ; colonne de droite =
        # emploi/rémunération (Taux horaire de base, Date d'embauche,
        # Date de fin d'emploi, Taux d'indemnité de vacances, Province
        # de travail).
        col_identite, col_emploi = st.columns(2)
        with col_identite:
            st.write(f"**id** : {employe.id}")
            st.write(
                "**Prénom** : "
                f"{(fiche_coordonnees_existante.prenom or '—') if fiche_coordonnees_existante else '—'}"
            )
            st.write(
                "**Nom** : "
                f"{(fiche_coordonnees_existante.nom or '—') if fiche_coordonnees_existante else '—'}"
            )
            st.write(f"**Date de naissance** : {employe.date_naissance}")
            st.write(f"**Titre d'emploi** : {employe.titre_emploi}")
        with col_emploi:
            st.write(f"**Taux horaire de base** : {employe.taux_horaire_base} $")
            st.write(f"**Date d'embauche** : {employe.date_embauche}")
            st.write(
                "**Date de fin d'emploi** : "
                f"{employe.date_fin_emploi if employe.date_fin_emploi else '—'}"
            )
            st.write(
                "**Taux d'indemnité de vacances** : "
                f"{employe.taux_indemnite_vacances}"
            )
            st.write(
                f"**Province de travail** : {employe.province_travail.value} (fixe)"
            )
        return

    with st.form(f"fed_formulaire_informations_{employe.id}"):
        prenom = st.text_input(
            "Prénom",
            value=(
                (fiche_coordonnees_existante.prenom or "")
                if fiche_coordonnees_existante
                else ""
            ),
            key=f"fed_prenom_{employe.id}",
        )
        nom = st.text_input(
            "Nom",
            value=(
                (fiche_coordonnees_existante.nom or "")
                if fiche_coordonnees_existante
                else ""
            ),
            key=f"fed_nom_{employe.id}",
        )
        date_naissance = st.date_input(
            "Date de naissance",
            value=employe.date_naissance,
            min_value=_DATE_NAISSANCE_MIN,
            max_value=_DATE_NAISSANCE_MAX,
            key=f"fed_date_naissance_{employe.id}",
        )
        # Bug UI signalé après démo : même autosuggestion que
        # `nouvel_employe.py` (5 titres de base + titres déjà saisis
        # dans l'Annuaire_Employes) — la valeur actuelle de l'employé
        # est pré-sélectionnée si elle figure parmi les suggestions,
        # sinon conservée comme option additionnelle en tête de liste
        # (`accept_new_options=True` permet la saisie libre, mais
        # `st.selectbox` exige que la valeur `index=`-née figure dans
        # `options` — un titre inédit ne serait sinon jamais
        # pré-affiché).
        titres_suggeres = lister_titres_emploi_suggeres()
        if employe.titre_emploi not in titres_suggeres:
            titres_suggeres = (employe.titre_emploi,) + titres_suggeres
        titre_emploi = st.selectbox(
            "Titre d'emploi",
            options=titres_suggeres,
            index=titres_suggeres.index(employe.titre_emploi),
            accept_new_options=True,
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
        col_soumettre, col_annuler = st.columns(2)
        with col_soumettre:
            soumis_informations = st.form_submit_button(
                "Mettre à jour les informations principales", type="primary"
            )
        with col_annuler:
            # Bug UI signalé après démo — retour au mode consultation
            # sans appeler `enregistrer_employe`/`enregistrer_coordonnees`,
            # donc sans écrire quoi que ce soit sur disque.
            annuler_informations = st.form_submit_button("Annuler")

    if annuler_informations:
        st.session_state[cle_edition] = False
        _planifier_defilement_vers(cle_edition)
        st.rerun()

    if soumis_informations:

        def _mettre_a_jour_informations_et_enregistrer() -> Employee:
            # Même discipline que la section fiscale (Req 11.4) : les
            # deux opérations sont enchaînées dans une seule fonction
            # passée à `executer_avec_capture` — si la reconstruction
            # immuable échoue, `enregistrer_employe` n'est jamais
            # atteinte, aucune modification partielle n'est jamais
            # persistée.
            nouvel_employe = mettre_a_jour_informations_principales(
                employe,
                nom_affichage=f"{prenom} {nom}".strip(),
                date_naissance=date_naissance,
                titre_emploi=titre_emploi,
                taux_horaire_base=Decimal(taux_horaire_base),
                date_embauche=date_embauche,
                date_fin_emploi=date_fin_emploi,
                taux_indemnite_vacances=Decimal(taux_indemnite_vacances),
            )
            enregistrer_employe(nouvel_employe)
            # Prénom/Nom sont captés ici — enregistrés dans la
            # `FicheCoordonnees`, jamais transmis à `Employee` lui-même
            # (règle 04), uniquement une fois l'`Employee` déjà persisté
            # avec succès. Les autres champs de coordonnées (NAS,
            # adresse, courriel, téléphone) sont préservés tels quels
            # (`fiche_coordonnees_existante`).
            enregistrer_coordonnees(
                FicheCoordonnees(
                    employe_id=employe.id,
                    prenom=prenom or None,
                    nom=nom or None,
                    nas=(
                        fiche_coordonnees_existante.nas
                        if fiche_coordonnees_existante
                        else None
                    ),
                    adresse_residentielle=(
                        fiche_coordonnees_existante.adresse_residentielle
                        if fiche_coordonnees_existante
                        else None
                    ),
                    courriel=(
                        fiche_coordonnees_existante.courriel
                        if fiche_coordonnees_existante
                        else None
                    ),
                    telephone=(
                        fiche_coordonnees_existante.telephone
                        if fiche_coordonnees_existante
                        else None
                    ),
                )
            )
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
                st.session_state[cle_edition] = False
                st.success(
                    f"Informations principales de {resultat_informations.id} "
                    "mises à jour."
                )
                _planifier_defilement_vers(cle_edition)
                st.rerun()


def _section_fiscal(employe: Employee) -> None:
    """Section 3 — « Formulaire TD1 / TP-1015.3 (à mettre à jour chaque
    année) » (Req 11).

    Bug UI signalé après démo — mode consultation par défaut, bascule
    vers le formulaire d'édition (inchangé, hormis l'ajout du bouton
    « Annuler ») via le bouton crayon de :func:`_afficher_entete_section`.
    """
    cle_edition = _CLE_EDITION_FISCAL.format(employe_id=employe.id)
    en_edition = _afficher_entete_section(
        "À partir du TP-1015.3 et TD1 fourni par l'employé",
        cle_edition,
    )

    if not en_edition:
        st.write(f"**Montant total TP-1015.3** : {employe.montant_total_TP1015_3} $")
        st.write(
            "**Exonération TP-1015.3** : "
            f"{'Oui' if employe.exoneration_TP1015_3 else 'Non'}"
        )
        st.write(
            "**Retenue additionnelle QC** : "
            f"{employe.retenue_additionnelle_QC} $"
        )
        st.write(f"**Montant total TD1** : {employe.montant_total_TD1} $")
        st.write(
            "**Exonération TD1** : "
            f"{'Oui' if employe.exoneration_TD1 else 'Non'}"
        )
        st.write(
            "**Retenue additionnelle fédérale** : "
            f"{employe.retenue_additionnelle_federale} $"
        )
        return

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
        col_soumettre, col_annuler = st.columns(2)
        with col_soumettre:
            soumis = st.form_submit_button(
                "Mettre à jour les données fiscales", type="primary"
            )
        with col_annuler:
            annuler_fiscal = st.form_submit_button("Annuler")

    if annuler_fiscal:
        st.session_state[cle_edition] = False
        _planifier_defilement_vers(cle_edition)
        st.rerun()

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

    st.session_state[cle_edition] = False
    st.success(f"Données fiscales de {resultat.id} mises à jour.")
    _planifier_defilement_vers(cle_edition)
    st.rerun()


def _section_coordonnees(employe_id: str) -> None:
    """Section 2 — « Coordonnées opérationnelles », distincte du
    Formulaire_Paie (Req 20.4).

    Prénom/Nom ne sont pas exposés ici — ils ne vivent qu'à un seul
    endroit, dans la section « Informations principales »
    (:func:`_section_informations_principales`), qui les enregistre
    déjà dans cette même `FicheCoordonnees`. Cette section ne porte donc
    que NAS/adresse/courriel/téléphone.

    Bug UI signalé après démo — mode consultation par défaut, bascule
    vers le formulaire d'édition (inchangé, hormis l'ajout du bouton
    « Annuler ») via le bouton crayon de :func:`_afficher_entete_section`.
    """
    cle_edition = _CLE_EDITION_COORDONNEES.format(employe_id=employe_id)
    en_edition = _afficher_entete_section("Coordonnées opérationnelles", cle_edition)

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

    if not en_edition:
        st.write(
            "**NAS** : "
            f"{(fiche_existante.nas or '—') if fiche_existante else '—'}"
        )
        st.write(
            "**Adresse résidentielle** : "
            f"{(fiche_existante.adresse_residentielle or '—') if fiche_existante else '—'}"
        )
        st.write(
            "**Courriel** : "
            f"{(fiche_existante.courriel or '—') if fiche_existante else '—'}"
        )
        st.write(
            "**Téléphone** : "
            f"{(fiche_existante.telephone or '—') if fiche_existante else '—'}"
        )
        return

    with st.form(f"fed_formulaire_coordonnees_{employe_id}"):
        # `on_change` est interdit par Streamlit sur un widget à
        # l'intérieur d'un `st.form` — le NAS reste donc dans ce
        # formulaire, mise en forme (gabarit ``999 999 999``,
        # `formater_nas`) appliquée uniquement à la soumission.
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
        col_soumettre, col_annuler = st.columns(2)
        with col_soumettre:
            soumis = st.form_submit_button(
                "Enregistrer les coordonnées", type="primary"
            )
        with col_annuler:
            annuler_coordonnees = st.form_submit_button("Annuler")

    if annuler_coordonnees:
        st.session_state[cle_edition] = False
        _planifier_defilement_vers(cle_edition)
        st.rerun()

    if not soumis:
        return

    def _construire_et_enregistrer() -> FicheCoordonnees:
        # Prénom/Nom ne sont plus saisis dans cette section (voir
        # docstring de fonction) — préservés tels quels depuis
        # `fiche_existante` plutôt qu'écrasés à `None`, puisque ce
        # formulaire ne les expose plus.
        fiche = FicheCoordonnees(
            employe_id=employe_id,
            prenom=fiche_existante.prenom if fiche_existante else None,
            nom=fiche_existante.nom if fiche_existante else None,
            nas=formater_nas(nas) or None,
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

    st.session_state[cle_edition] = False
    st.success(f"Coordonnées de {employe_id} enregistrées.")
    _planifier_defilement_vers(cle_edition)
    st.rerun()


def _sous_titre_paies(texte: str) -> str:
    """Sous-titre HTML de la section Paies (« Paies de l'année <annee> »,
    « Cumuls annuels <annee> ») — bug UI signalé après démo (3) : taille
    de police portée à ``1.2rem`` (plus grande que le texte courant de
    `st.write`, mais sans atteindre celle d'un `st.subheader`), gras
    conservé. `html.escape` par précaution même si ``texte`` ne contient
    ici que des libellés fixes et une année (`int`), jamais une donnée
    personnelle."""
    return (
        '<p style="font-size: 1.2rem; font-weight: 700; margin: 0;">'
        f"{html.escape(texte)}</p>"
    )


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

    Bug UI signalé après démo (2) — repositionnement du bouton
    « Ajouter une paie » : le champ séparé « Année fiscale de la
    nouvelle paie » est retiré ; le bouton se trouve désormais à droite
    du titre « Paies de l'année <annee> » (sans les deux-points, même
    visuel que « Cumuls annuels <annee> » juste en dessous — les deux
    sont des sous-titres de même niveau, rendus par
    :func:`_sous_titre_paies`, police 1.2rem — bug UI signalé après
    démo (3)) ; l'année fiscale transmise à la nouvelle paie est
    désormais toujours celle du filtre d'affichage
    (``annee_selectionnee``, liste déroulante « Année fiscale » qui
    pilote toute la section), jamais une saisie séparée.
    """
    st.subheader("Paies")

    resultat_resumes = executer_avec_capture(lambda: lire_resumes_paies(employe_id))
    if isinstance(resultat_resumes, ErreurDomaineAffichable):
        st.error(f"{resultat_resumes.type_exception}: {resultat_resumes.message}")
        return
    resumes: tuple[LignePaieResume, ...] = resultat_resumes

    annees = annees_disponibles(resumes) if resumes else ()
    saisons_par_annee = regrouper_saison_par_annee(resumes) if resumes else {}
    options_annees = [
        formater_option_annee(annee, saisons_par_annee.get(annee))
        for annee in annees
    ]

    if resumes:
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
    else:
        annee_selectionnee = date.today().year

    if not resumes:
        # Req 5.6 — absence de paie indiquée explicitement, sans exception.
        st.info("Aucune paie enregistrée pour cet employé.")
        # Le bouton « Ajouter une paie » reste accessible même sans
        # aucune paie existante — voir le bloc titre + bouton ci-dessous
        # (l'année par défaut est alors l'année civile courante).

    # Bug UI signalé après démo (2) — titre à gauche, bouton « Ajouter
    # une paie » à droite, aligné sur le bord droit de la page (même
    # patron `st.container(key=...)` que `tableau_de_bord.py::
    # tdb_conteneur_bouton_ajouter_employe`).
    col_titre_paies, col_bouton_ajouter = st.columns(
        [3, 2], vertical_alignment="center"
    )
    with col_titre_paies:
        st.markdown(
            _sous_titre_paies(f"Paies de l'année {annee_selectionnee}"),
            unsafe_allow_html=True,
        )
    with col_bouton_ajouter:
        with st.container(key=f"fed_conteneur_bouton_ajouter_paie_{employe_id}"):
            if st.button(
                "Ajouter une paie",
                type="primary",
                key=f"fed_ajouter_paie_{employe_id}",
            ):
                st.session_state["fp_employe_id_precharge"] = employe_id
                # Bug UI signalé après démo (2) : l'année fiscale
                # transmise est toujours celle actuellement sélectionnée
                # dans le filtre d'affichage de cette section
                # (``annee_selectionnee``) — plus de champ séparé.
                # Transmission par `st.query_params` (le lien HTML du
                # bouton — voir CSS ci-dessus — ne peut écrire aucun
                # `st.session_state` avant la navigation), lu en repli
                # par `formulaire_paie.py::_section_nouvelle_paie`.
                st.query_params["annee_fiscale"] = str(annee_selectionnee)
                from app.pages_ui._navigation import page_formulaire_paie

                st.switch_page(page_formulaire_paie)

    if not resumes:
        return

    paies_annee = dernieres_versions_par_periode(
        filtrer_par_annee(resumes, annee_selectionnee)
    )
    _afficher_tableau_paies(employe_id, paies_annee)

    # Req 5.4 — cumuls YTD de l'année sélectionnée.
    resultat_cumuls = executer_avec_capture(
        lambda: lire_cumuls_ytd(
            employe_id, annee_selectionnee, chemin_bd=chemin_bd_production()
        )
    )
    if isinstance(resultat_cumuls, ErreurDomaineAffichable):
        st.error(f"{resultat_cumuls.type_exception}: {resultat_cumuls.message}")
        return

    cumuls = resultat_cumuls
    st.markdown(
        _sous_titre_paies(f"Cumuls annuels {annee_selectionnee}"),
        unsafe_allow_html=True,
    )
    # Bug UI signalé après démo (2) — même visuel deux colonnes que la
    # section « Informations principales »
    # (:func:`_section_informations_principales`) : libellés complets
    # (`_LIBELLES_CUMULS_AFFICHAGE`, ex. « RRQ — part employé ») plutôt
    # que le nom brut des attributs Python (ex. ``"rrq_employe"``),
    # chaque valeur affichée en dollars (même convention `f"{montant} $"`
    # que le reste de l'application). `st.columns` reflue
    # automatiquement en une seule colonne empilée sur mobile/écran
    # étroit (comportement natif Streamlit) — les onze catégories sont
    # réparties pour moitié dans chaque colonne, dans leur ordre
    # d'origine (`_CATEGORIES_CUMULS_AFFICHAGE`).
    moitie = (len(_CATEGORIES_CUMULS_AFFICHAGE) + 1) // 2
    col_cumuls_gauche, col_cumuls_droite = st.columns(2)
    with col_cumuls_gauche:
        for categorie in _CATEGORIES_CUMULS_AFFICHAGE[:moitie]:
            st.write(
                f"**{_LIBELLES_CUMULS_AFFICHAGE[categorie]}** : "
                f"{getattr(cumuls, categorie)} $"
            )
    with col_cumuls_droite:
        for categorie in _CATEGORIES_CUMULS_AFFICHAGE[moitie:]:
            st.write(
                f"**{_LIBELLES_CUMULS_AFFICHAGE[categorie]}** : "
                f"{getattr(cumuls, categorie)} $"
            )


def _sans_indentation(bloc_html: str) -> str:
    """Supprime l'indentation de chaque ligne de ``bloc_html`` — même
    patron que `tableau_de_bord.py::_sans_indentation`/
    `bulletin_paie.py::_retirer_indentation` (Markdown de Streamlit :
    toute ligne indentée de 4 espaces ou plus est traitée comme un bloc
    de code littéral, règle CommonMark, ce qui empêcherait le rendu HTML
    même avec `unsafe_allow_html=True`)."""
    return "\n".join(ligne.lstrip() for ligne in bloc_html.splitlines())


def _lien_action_paie(*, href: str, texte: str) -> str:
    """Lien HTML d'action de la colonne Actions du tableau des Paies
    (bug UI signalé après démo — remplacement d'un `st.button` par un
    lien `<a>`, nécessaire pour qu'une ligne de tableau reste un `<tr>`
    sémantique plutôt qu'un `st.columns` — un widget Streamlit natif ne
    peut pas être imbriqué dans un `<table>` HTML injecté par
    `st.markdown`).

    Navigation par URL réelle (``href``), même patron que
    `bulletin_paie.py::_lien_fiche_employe` — jamais `st.switch_page`
    (réservé aux boutons Streamlit natifs, inatteignable depuis un bloc
    HTML injecté). Les pages cibles (`formulaire_paie.py`,
    `bulletin_paie.py`) lisent leurs identifiants pré-remplis depuis
    `st.query_params`, en repli de `st.session_state`.
    """
    # `target="_self"` — comportement par défaut demandé (jamais un
    # nouvel onglet, sauf indication explicite) : sans cet attribut,
    # Streamlit ouvre tout lien HTML injecté par `st.markdown` dans un
    # nouvel onglet.
    return (
        f'<a class="paies-lien-action" href="{href}" target="_self">'
        f"{html.escape(texte)}</a>"
    )


def _afficher_tableau_paies(
    employe_id: str, paies_annee: tuple[LignePaieResume, ...]
) -> None:
    """Tableau des paies de l'année sélectionnée avec colonne Actions
    (bug UI corrigé après livraison, demande explicite de l'utilisateur).

    Colonnes : Numéro de période | Id de la paie | Version | Statut |
    Salaire net | Date de création | Date de paiement | Actions.

    Bug UI signalé après démo — remplacement d'un faux tableau construit
    avec `st.columns`/`<div>` par un véritable élément HTML `<table>`
    (structure sémantique correcte pour une liste de données), même
    patron que le Tableau_Bilan_Fiscal/tableau des employés de
    `tableau_de_bord.py` (bug UI signalé après démo (3) — mêmes bordures
    par cellule absentes, même conteneur `.paies-conteneur` sans bordure
    de table, ligne d'en-tête bleu foncé/police blanche en gras via
    `_CSS_TABLEAU_PAIES::table.paies-tableau thead th`). Aucune donnée
    personnelle n'est interpolée dans ce tableau (uniquement des
    identifiants techniques et des montants), ``html.escape`` reste
    appliqué par précaution sur chaque cellule textuelle (défense en
    profondeur, même discipline que `bulletin_paie.py`).
    """
    if not paies_annee:
        st.info("Aucune paie pour l'année sélectionnée.")
        return

    lignes_html = []
    for resume in paies_annee:
        if resume.statut == StatutDePaie.BROUILLON.value:
            cellule_actions = _lien_action_paie(
                href=(
                    "/formulaire-paie"
                    f"?employe_id={quote(employe_id)}"
                    f"&id_paie={quote(resume.id_paie)}"
                ),
                texte="Modifier",
            )
        else:
            cellule_actions = _lien_action_paie(
                href=f"/bulletin-paie?id_paie={quote(resume.id_paie)}",
                texte="Voir le bulletin",
            )
        lignes_html.append(
            "<tr>"
            f"<td>{resume.numero_periode}</td>"
            f"<td>{html.escape(resume.id_paie)}</td>"
            f"<td>{resume.version}</td>"
            f"<td>{html.escape(_LIBELLES_STATUT.get(resume.statut, resume.statut))}</td>"
            f"<td>{resume.net} $</td>"
            f"<td>{resume.date_creation}</td>"
            f"<td>{resume.date_paiement if resume.date_paiement else '—'}</td>"
            f"<td>{cellule_actions}</td>"
            "</tr>"
        )

    tableau_html = f"""
    <div class="paies-conteneur">
        <table class="paies-tableau">
            <thead>
                <tr>
                    <th>Numéro de période</th>
                    <th>Id de la paie</th>
                    <th>Version</th>
                    <th>Statut</th>
                    <th>Salaire net</th>
                    <th>Date de création</th>
                    <th>Date de paiement</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {"".join(lignes_html)}
            </tbody>
        </table>
    </div>
    """
    # Bug UI signalé après démo — même teinte bleu foncé/police blanche
    # que le tableau des employés et le Bilan_Fiscal du Tableau_De_Bord
    # (`_CSS_TABLEAU_PAIES`).
    st.markdown(
        _CSS_TABLEAU_PAIES + _sans_indentation(tableau_html),
        unsafe_allow_html=True,
    )



