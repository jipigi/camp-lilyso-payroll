"""Bulletin_De_Paie — page de consultation en lecture seule d'une paie.

Reproduit visuellement le gabarit officiel
`intake/fiches-paie/Bulletin-paie-gabarit.xlsx` (hors dépôt, règle 04) :
identification employé/employeur, période, section salaire détaillée
(heures normales/supplémentaires x taux, indemnités, brut) et
déductions fiscales (impôt fédéral/provincial, RRQ, AE, RQAP, total)
côte à côte, salaire NET, puis — en toute dernière position, distincte
du reste car destinée à l'information seulement — les cotisations
employeur (RRQ, AE, RQAP, CNESST avec son taux, FSS, CNT, total).

Hiérarchie visuelle à deux niveaux (discussion utilisateur) : les
**sections** de premier niveau (« Identification », « Période »,
« Heures travaillées et salaire », « Cotisation employeur ») portent un
bandeau bleu plein (`_CSS_BULLETIN::.bulletin-section-titre`) ; les
**sous-sections** qu'elles regroupent (« Salarié »/« Employeur »,
« Salaire »/« Indemnités »/« Déductions fiscales ») sont en gras seul,
sans fond de couleur (voir :func:`_sous_titre`).

Bug UI corrigé après livraison (option retenue par l'utilisateur : mise
en page HTML/CSS imprimable plutôt qu'un remplissage du gabarit Excel
converti en PDF côté serveur — évite toute dépendance système
supplémentaire sur Streamlit Community Cloud) : le corps du bulletin
(à partir de la section « Identification ») est désormais rendu comme
**un seul bloc HTML/CSS** (`st.markdown(..., unsafe_allow_html=True)`),
reproduisant fidèlement la disposition à deux colonnes du gabarit
officiel (Salarié/Employeur, Salaire/Cotisations employeur). L'opérateur
imprime cette page (Ctrl+P du navigateur, « Enregistrer en PDF ») pour
produire le document à transmettre à l'employé — aucune génération de
fichier PDF côté serveur n'est introduite par ce changement. Des règles
`@media print` masquent le chrome Streamlit (barre latérale, en-tête,
boutons, encarts d'audit) pour qu'une impression ne contienne que le
bulletin lui-même.

Accès exclusivement par navigation contextuelle — jamais de ressaisie
d'``id_paie`` par l'opérateur (décision explicite, discussion
utilisateur) : l'``id_paie`` cible est lu depuis
`st.session_state["bulletin_id_paie_cible"]`, écrit par la page
appelante (Tableau_De_Bord, Fiche_Employe_Detaillee) avant
`st.switch_page`. Si la clé est absente (accès direct par URL ou clic
sur l'élément de navigation latérale), un message explicite invite
l'opérateur à naviguer depuis une fiche employé plutôt que d'afficher
une page vide silencieusement.

Boutons d'action entre le titre et le contenu (haut de page), tous
masqués à l'impression via un conteneur dédié
(``st.container(key="bulletin_barre_actions")``, voir Règle UI 07 —
`.kiro/steering/07-ui-boutons.md`) :

- « Imprimer » (visuel **primaire**, Règle UI 07 — action principale de
  cette page) — toujours visible, déclenche la commande d'impression du
  navigateur (`window.print()`). Rendu via
  `st.components.v1.html` plutôt que `st.markdown` : le Markdown de
  Streamlit passe son HTML par un assainisseur (DOMPurify) qui retire
  systématiquement les attributs `onclick`, rendant tout bouton HTML
  injecté par `st.markdown` inerte — seul `components.v1.html` (rendu
  dans un `<iframe>` isolé, non assaini) exécute le JavaScript
  nécessaire. `window.parent.print()` cible la fenêtre du navigateur
  contenant l'application (et non l'iframe lui-même, qui n'a pas de
  contenu à imprimer).
- Menu à trois points (`st.popover`, icône ``:material/more_vert:``,
  label vide, aide « Autres actions ») — demande explicite de
  l'utilisateur : regroupe les deux actions secondaires/destructives
  peu fréquentes, plutôt que de les afficher comme deux boutons
  distincts dans la barre. Visible uniquement si la paie est `EMISE`
  (seul statut pour lequel les deux actions qu'il contient sont
  pertinentes) :

  - « Corriger » (icône ``:material/edit:``, visuel **secondaire**,
    Règle UI 07) — visible uniquement si la paie est `EMISE` (seul
    statut que `payroll_engine.register.remplacer_paie` accepte de
    remplacer, Req 13.2 du moteur) ; route vers le Formulaire_Paie en
    mode correction, avec l'``id_paie`` déjà chargé (jamais de
    ressaisie).
  - « Supprimer » (icône ``:material/delete:``, visuel
    **Bouton_Danger** — action destructive irréversible) — ouvre la
    Popup_Confirmation_Paie_Emise (:func:`_dialogue_confirmation_
    suppression_paie`).

Couche de rendu (`app/pages_ui/`) : ce module **peut** importer
``streamlit`` (Req 1.1, 1.3 ne s'appliquent qu'à
`app/logique_metier/**`).

Disjonction stricte (Req 16) : toute exception susceptible d'être levée
par `lire_paie` est enveloppée par `executer_avec_capture` — aucun
`except Exception`/`except BaseException` générique n'est présent dans
ce module (Req 16.1, 16.3).

Règle 02 (traçabilité) : ce module n'invente aucune nouvelle
`CalculationTrace`. Le bulletin imprimable affiche chaque montant déjà
calculé par `assembler_paie`, sans trace détaillée (mise en page fidèle
au gabarit officiel, qui n'expose pas ce niveau de détail) ; la
consultation de chaque `CalculationTrace` reste possible via la section
« Détails des calculs (audit) », masquée à l'impression, qui réutilise
`_afficher_trace_montant` (même patron que `formulaire_paie.py`). Les
deux « taux horaire » affichés (heures normales, heures
supplémentaires) sont des **calculs d'affichage purs** (montant ÷
heures, division inverse de la multiplication faite par
`payroll_engine.gains_bruts.calcul_gains`), pas une nouvelle règle
fiscale — si le nombre d'heures d'une catégorie est nul, le taux
correspondant est affiché comme absent plutôt que de diviser par zéro.

Règle 04 (données sensibles) : chaque champ personnel interpolé dans le
bloc HTML (prénom, nom, NAS, titre d'emploi) est échappé via
`html.escape` avant insertion — défense en profondeur contre une saisie
contenant des caractères HTML spéciaux (``&``, ``<``, ``>``), même si
ces champs proviennent de saisies internes de confiance.

Champs du gabarit non disponibles dans les modèles du moteur, résolus
par décision explicite (discussion utilisateur) :

- **Informations employeur** (nom, adresse, ville, code postal, numéro
  NQE) — constantes fixes de l'organisation, centralisées dans
  `app/config_employeur.py` plutôt que codées en dur ici.
- **Prénom / Nom / NAS de l'employé** — lus depuis
  `FicheCoordonnees.prenom`/`.nom`/`.nas`
  (`app/logique_metier/annuaire_coordonnees.py`), jamais transmis au
  moteur de calcul (règle 04) ; si `FicheCoordonnees` est absente ou que
  `prenom`/`nom` n'y sont pas renseignés, `Employee.nom_affichage` est
  découpé sur le premier espace comme repli (même convention que la
  migration de l'ancien champ `nom_complet_reel`, voir
  `annuaire_coordonnees.py::_migrer_nom_complet_reel_si_present`).
"""

from __future__ import annotations

import base64
import html
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from app.config_employeur import CONFIG_EMPLOYEUR
from app.logique_metier.annuaire_coordonnees import lire_coordonnees
from app.logique_metier.annuaire_employes import lire_employe
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from app.pages_ui._navigation import afficher_lien_retour_tableau_de_bord
from models.enums import StatutDePaie
from models.payroll_result import MontantAvecTrace, PayrollResult
from payroll_engine.register import annuler_paie, chemin_bd_production, lire_paie

#: Clé de `st.session_state` portant l'``id_paie`` de la paie à
#: afficher — écrite par la page appelante avant `st.switch_page`,
#: jamais ressaisie par l'opérateur sur cette page.
CLE_ID_PAIE_CIBLE = "bulletin_id_paie_cible"

#: Chemin du logo de l'organisation, déjà versionné et utilisé comme
#: icône de page (`app/main.py::st.set_page_config`) — réutilisé ici
#: tel quel, jamais dupliqué depuis `intake/` (zone d'atterrissage hors
#: dépôt, règle 04).
_CHEMIN_LOGO = Path(__file__).resolve().parent.parent / "assets" / "logo-camp-lilyso.png"


def _logo_en_data_uri() -> str | None:
    """Encode le logo en data URI base64 pour l'en-tête du bulletin.

    Un ``<img src="app/assets/...">`` ne fonctionnerait pas dans le
    bloc HTML injecté par `st.markdown` (chemin de fichier local, pas
    une URL servie) — l'encodage en data URI intègre l'image
    directement dans le HTML, fonctionnel aussi bien à l'écran qu'à
    l'impression. Retourne ``None`` si le fichier est absent (aucune
    exception : l'en-tête s'affiche alors sans logo plutôt que de
    faire échouer tout le rendu du bulletin).
    """
    if not _CHEMIN_LOGO.exists():
        return None
    contenu = _CHEMIN_LOGO.read_bytes()
    encode = base64.b64encode(contenu).decode("ascii")
    return f"data:image/png;base64,{encode}"

#: CSS partagé du bulletin imprimable — injecté une seule fois en tête
#: du bloc HTML (voir :func:`_construire_html_bulletin`). Les règles
#: `@media print` ciblent les attributs `data-testid` stables exposés
#: par Streamlit pour son propre chrome (en-tête, barre latérale,
#: barre d'outils) ainsi que les widgets natifs de cette page
#: (bouton de correction, expanders d'audit) — masqués uniquement à
#: l'impression, toujours visibles à l'écran.
_CSS_BULLETIN = """
<style>
@media print {
    [data-testid="stHeader"], [data-testid="stSidebar"],
    [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stButton"], [data-testid="stExpander"],
    [data-testid="stCaptionContainer"], [data-testid="stPageLink"],
    .bulletin-hors-impression,
    .st-key-bulletin_barre_actions {
        display: none !important;
    }
    .bulletin-conteneur { border: none !important; }
    /* Le fond de couleur de l'application (thème Streamlit,
       `.streamlit/config.toml::backgroundColor`) consommerait de
       l'encre sans apporter d'information au bulletin imprimé — forcé
       en blanc uniquement à l'impression, jamais à l'écran. */
    html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"],
    [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
        background: #ffffff !important;
    }
    /* Marges verticales resserrées à l'impression uniquement (écran
       inchangé) — objectif demandé par l'utilisateur : faire tenir le
       salaire NET sur la première page plutôt qu'en haut d'une
       deuxième page, sans réduire l'écran à l'usage quotidien. */
    .bulletin-conteneur { margin: 0 auto !important; padding: 10px 30px !important; }
    .bulletin-entete { margin-bottom: 10px !important; padding-bottom: 6px !important; }
    .bulletin-section-titre { margin: 8px 0 5px 0 !important; padding: 4px 12px !important; }
    table.bulletin-lignes td { padding: 1px 4px !important; }
    .bulletin-net { margin-top: 10px !important; padding: 8px 18px !important; }
    .bulletin-sous-titre-espace { margin-top: 8px !important; }
    .bulletin-section-titre-fin { margin-top: 20px !important; }
}
.bulletin-conteneur {
    max-width: 880px;
    margin: 8px auto 24px auto;
    padding: 28px 36px;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    background: #ffffff;
    font-family: "Segoe UI", Arial, sans-serif;
    color: #1a1a1a;
}
.bulletin-entete {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 3px solid #2c5f8a;
}
.bulletin-entete img {
    width: 50px;
    height: auto;
}
.bulletin-titre-principal {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #2c5f8a;
}
.bulletin-section-titre {
    background: #2c5f8a;
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
    padding: 6px 12px;
    margin: 18px 0 8px 0;
    border-radius: 4px;
}
/* Espacement additionnel avant la section « Cotisation employeur »,
   qui suit directement l'encadré du salaire NET — sans cette marge,
   la section de fin de bulletin (information secondaire) semblait
   accolée au NET (résultat le plus important pour l'employé). */
.bulletin-section-titre-fin { margin-top: 32px; }
.bulletin-deux-colonnes {
    display: flex;
    flex-wrap: wrap;
    gap: 32px;
}
.bulletin-colonne { flex: 1; min-width: 260px; }
.bulletin-sous-titre {
    display: block;
    margin: 0 0 4px 0;
}
.bulletin-sous-titre-espace { margin-top: 14px; }
table.bulletin-lignes { width: 100%; border-collapse: collapse; font-size: 13.5px; }
table.bulletin-lignes td { padding: 3px 4px; vertical-align: top; }
table.bulletin-lignes td.libelle { color: #333333; }
table.bulletin-lignes td.valeur {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
a.bulletin-lien-fiche-employe {
    color: #2c5f8a;
    text-decoration: underline;
}
@media print {
    /* Un lien de complétion de donnée n'a aucun sens sur un document
       imprimé — affiché comme le texte "Non renseigné" brut, sans
       soulignement ni couleur de lien, à l'impression uniquement. */
    a.bulletin-lien-fiche-employe {
        color: inherit;
        text-decoration: none;
    }
}
table.bulletin-lignes tr.bulletin-total td {
    border-top: 1px solid #999999;
    font-weight: 700;
    padding-top: 6px;
}
table.bulletin-lignes tr.bulletin-total-fort td {
    font-weight: 700;
    font-size: 15px;
    color: #2c5f8a;
}
/* Variante neutre du total fort — « Total des déductions » n'est pas
   le résultat final visé par l'employé (contrairement au salaire BRUT
   ou au total des cotisations employeur) ; le bleu de mise en
   emphase serait trompeur ici (discussion utilisateur). */
table.bulletin-lignes tr.bulletin-total-fort-neutre td {
    font-weight: 700;
    font-size: 15px;
    color: #1a1a1a;
}
.bulletin-net {
    margin-top: 18px;
    padding: 12px 18px;
    background: #eaf3ea;
    border: 1px solid #a7d0a7;
    border-radius: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 17px;
    font-weight: 700;
    color: #1e6b1e;
}
</style>
"""


#: Bouton « Imprimer » — HTML/JS autonome rendu via
#: `st.components.v1.html` (voir docstring de module : `st.markdown`
#: assainit et retire tout `onclick`). Visuel primaire (Règle UI 07)
#: répliqué en CSS plutôt que réutilisé depuis le thème Streamlit — un
#: bouton HTML natif dans un `<iframe>` n'a pas accès aux classes
#: générées par Streamlit (`stBaseButton-primary`). `window.parent`
#: cible la fenêtre de l'application (celle qui porte le bulletin),
#: pas l'``<iframe>`` isolé du composant lui-même (qui n'a aucun
#: contenu à imprimer).
_BOUTON_IMPRIMER_HTML = """
<button
    onclick="window.parent.print();"
    style="
        width: 100%;
        height: 38px;
        background-color: #1f2c3b;
        color: #FFFFFF;
        border: 1px solid #1f2c3b;
        border-radius: 8px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 14px;
        font-weight: 400;
        cursor: pointer;
    "
    onmouseover="this.style.opacity=0.85;"
    onmouseout="this.style.opacity=1;"
>Imprimer</button>
"""


#: Visuel "Bouton_Danger" (fond rouge, police blanche) — troisième couleur
#: de bouton, hors du binaire primaire/secondaire natif de la Règle UI 07
#: (`.kiro/steering/07-ui-boutons.md`). Contrairement au bouton
#: « Imprimer » (`_BOUTON_IMPRIMER_HTML`, JS pur sans retour Python), le
#: bouton « Supprimer la paie » DOIT rester un `st.button` natif — son
#: clic déclenche une annulation côté serveur (`annuler_paie`), impossible
#: à exprimer via `components.v1.html` (aucun canal de retour vers le
#: code Python). Le CSS ci-dessous cible donc la classe `st-key-<key>`
#: que Streamlit attribue automatiquement au conteneur d'un widget natif
#: portant un `key=` explicite — même technique de ciblage que
#: `fiche_employe_detaillee.py::_CSS_TABLEAU_PAIES` (utilisée là pour
#: l'alignement, ici pour la couleur), jamais une modification de
#: `.streamlit/config.toml` (qui ne pilote que primaire/secondaire).
#: Écart documenté à la Règle UI 07 : la couleur n'est pas codée en dur
#: sur un `st.button` natif *sans* `key=` scoping — elle est appliquée
#: exclusivement aux deux boutons destructifs « Supprimer la paie »
#: (`bulletin_supprimer_ouvrir`) / « Supprimer la paie de {Prénom Nom} »
#: (`bulletin_supprimer_confirmer`) de cette page, via leurs clés
#: explicites, jamais globalement. Constante dupliquée dans
#: `formulaire_paie.py` (même discipline de duplication de petites
#: constantes qu'entre `tableau_de_bord.py::_LIBELLES_STATUT` et
#: `fiche_employe_detaillee.py::_LIBELLES_STATUT`) — la portée de chaque
#: copie est limitée aux clés de son propre module (ici
#: `bulletin_supprimer*`, jamais `fp_supprimer_brouillon*`).
_CSS_BOUTON_DANGER = """
<style>
div[class*="st-key-bulletin_supprimer"] button {
    background-color: #b3261e;
    color: #FFFFFF;
    border: 1px solid #b3261e;
}
div[class*="st-key-bulletin_supprimer"] button:hover {
    background-color: #8c1d17;
    border-color: #8c1d17;
    color: #FFFFFF;
}
</style>
"""


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

    Réservé à la section « Détails des calculs (audit) », masquée à
    l'impression (voir docstring de module) — même patron que
    `formulaire_paie.py::_afficher_trace`, consultation sans altération
    ni reformulation de la trace produite par `assembler_paie`.
    """
    trace = montant_avec_trace.trace
    st.write(f"{libelle} : {montant_avec_trace.montant} $")
    with st.expander(f"Trace — {libelle}", expanded=False):
        st.write(f"Source : {trace.source}")
        st.write(f"Section : {trace.section}")
        st.write(f"Paramètres utilisés : {dict(trace.parametres_utilises)}")


def _retirer_indentation(bloc_html: str) -> str:
    """Supprime l'indentation de chaque ligne de ``bloc_html`` (bug UI).

    Le Markdown de Streamlit interprète toute ligne indentée de 4
    espaces ou plus comme un bloc de code littéral (règle CommonMark),
    ce qui empêchait le rendu HTML même avec `unsafe_allow_html=True`.
    Purement une transformation de mise en forme du texte — aucun
    contenu n'est modifié, seul l'espacement de bord de ligne est
    retiré.
    """
    return "\n".join(ligne.lstrip() for ligne in bloc_html.splitlines())


def _diviser_nom_affichage(nom_affichage: str) -> tuple[str, str]:
    """Découpe ``nom_affichage`` en ``(prenom, nom)`` — repli d'affichage seul.

    Utilisé uniquement lorsque `FicheCoordonnees.prenom`/`.nom` ne sont
    pas renseignés (fiche absente, ou champs vides) — même convention
    que la migration de l'ancien champ `nom_complet_reel`
    (`annuaire_coordonnees.py::_migrer_nom_complet_reel_si_present`) :
    découpe sur le premier espace, tout le libellé au prénom si aucun
    espace n'est présent.
    """
    parties = nom_affichage.split(" ", 1)
    return (parties[0], parties[1] if len(parties) > 1 else "")


def _ligne(libelle: str, valeur: str, *, css_ligne: str = "") -> str:
    """Génère une ligne ``<tr>`` libellé/valeur du bulletin imprimable.

    ``libelle`` est déjà échappé par l'appelant si nécessaire (les
    libellés de ce module sont tous des littéraux fixes, jamais des
    données personnelles) ; ``valeur`` doit être pré-échappée par
    l'appelant si elle porte une donnée personnelle en texte libre
    (voir `html.escape` dans :func:`_construire_html_bulletin`).
    """
    classe = f' class="{css_ligne}"' if css_ligne else ""
    return (
        f"<tr{classe}><td class='libelle'>{libelle}</td>"
        f"<td class='valeur'>{valeur}</td></tr>"
    )


def _sous_titre(texte: str, *, marge_haut: bool = False) -> str:
    """Titre de **sous-section** du bulletin — gras seul, sans bandeau.

    Distinct des titres de **section** (bandeau bleu plein,
    `_CSS_BULLETIN::.bulletin-section-titre`) — convention clarifiée
    avec l'utilisateur (discussion) : les sections de premier niveau
    (« Identification », « Période », « Heures travaillées et
    salaire », « Cotisation employeur ») portent le bandeau bleu ; les
    sous-sections qu'elles regroupent (« Salarié »/« Employeur »,
    « Salaire »/« Indemnités »/« Déductions fiscales ») sont en gras
    seul, sans fond de couleur, pour marquer une hiérarchie visuelle
    claire entre les deux niveaux. Toujours rendu en `display: block`
    (classe `.bulletin-sous-titre`, plutôt que le `display: inline`
    par défaut de `<strong>`) avec une marge basse minime — un
    `<strong>` inline laissait un espace visuellement trop important
    avant le tableau suivant (bug UI signalé pour « Salaire » et
    « Déductions fiscales »). L'espacement additionnel de
    ``marge_haut`` (classe `.bulletin-sous-titre-espace`, cumulée) sert
    à séparer deux sous-sections empilées dans une même colonne (ex.
    « Indemnités » sous « Salaire ») et se resserre à l'impression
    (voir `_CSS_BULLETIN::@media print`, marges verticales réduites
    afin que le salaire NET tienne sur la première page imprimée).
    """
    classes = "bulletin-sous-titre" + (" bulletin-sous-titre-espace" if marge_haut else "")
    return f'<strong class="{classes}">{texte}</strong>'


def _lien_fiche_employe(employe_id: str, texte_affiche: str) -> str:
    """Lien HTML vers la Fiche_Employe_Detaillee de ``employe_id`` (bug UI
    signalé après démo) — utilisé sur le libellé « Non renseigné » d'une
    donnée manquante (ex. NAS), pour permettre à l'opérateur de la
    compléter sans devoir chercher manuellement l'employé concerné.

    Navigation par URL réelle (``href``), pas `st.switch_page` (réservé
    aux boutons Streamlit natifs, impossible à déclencher depuis un bloc
    HTML injecté par `st.markdown` — le Markdown de Streamlit retire
    `onclick`, mais laisse `href` intact). La page cible
    (`fiche_employe_detaillee.py`) lit `employe_id` depuis
    `st.query_params` en repli de `st.session_state` (voir sa docstring
    de module) pour pré-sélectionner l'employé visé. ``employe_id`` est
    un identifiant technique interne (`EMPnnn`), jamais une donnée
    personnelle — encodé via `urllib.parse.quote` par précaution, aucun
    `html.escape` supplémentaire nécessaire sur ``texte_affiche``
    (l'appelant fournit toujours le littéral fixe « Non renseigné »,
    jamais une donnée personnelle saisie librement).
    """
    # `target="_self"` — comportement par défaut demandé (jamais un
    # nouvel onglet, sauf indication explicite) : sans cet attribut,
    # Streamlit ouvre tout lien HTML injecté par `st.markdown` dans un
    # nouvel onglet.
    return (
        f'<a class="bulletin-lien-fiche-employe" '
        f'href="/fiche-employe?employe_id={quote(employe_id)}" target="_self">'
        f"{texte_affiche}</a>"
    )


def _construire_html_bulletin(
    *,
    employe,
    prenom_affiche: str,
    nom_affiche: str,
    nas_affiche: str,
    nas_manquant: bool,
    paie: PayrollResult,
    heures_normales_totales: Decimal | None,
    heures_supp_totales: Decimal | None,
) -> str:
    """Construit le bloc HTML complet du bulletin imprimable (règle 04).

    Chaque champ personnel en texte libre (prénom, nom, NAS, titre
    d'emploi) est échappé via `html.escape` avant interpolation —
    défense en profondeur contre une saisie contenant des caractères
    HTML spéciaux. Les montants (`Decimal`) et dates ne nécessitent
    aucun échappement (aucun caractère HTML spécial possible).

    ``nas_manquant`` (bug UI signalé après démo) : si vrai, le libellé
    « Non renseigné » du NAS devient un lien cliquable vers la
    Fiche_Employe_Detaillee de cet employé (:func:`_lien_fiche_employe`),
    pour permettre de compléter cette donnée directement depuis le
    bulletin plutôt que de devoir chercher l'employé manuellement.
    """
    semaines = paie.pay_period.semaines
    gains = paie.gains
    ret = paie.retenues_employe
    cot = paie.cotisations_employeur

    # ------------------------------------------------------------------
    # Bloc « Salaire » — heures, taux, indemnités, brut (design fidèle
    # au gabarit, à l'exception du libellé dupliqué "Total salaire" du
    # gabarit officiel — visiblement une coquille du modèle Excel —
    # corrigé ici en "Total indemnités" pour la deuxième occurrence,
    # cohérence déjà présente dans la version précédente de ce module.
    # ------------------------------------------------------------------
    if heures_normales_totales is None:
        lignes_salaire = (
            _ligne("Heures normales — montant", f"{gains.salaire_regulier} $")
            + _ligne(
                "Heures supplémentaires — montant",
                f"{gains.heures_supplementaires_montant} $",
            )
        )
    else:
        taux_normal = _taux_horaire_affiche(
            gains.salaire_regulier, heures_normales_totales
        )
        taux_supp = _taux_horaire_affiche(
            gains.heures_supplementaires_montant, heures_supp_totales
        )
        lignes_salaire = (
            _ligne("Heures normales", f"{heures_normales_totales} h")
            + _ligne("Taux horaire", f"{taux_normal} $/h")
            + _ligne(
                "Heures supplémentaires", f"{heures_supp_totales} h"
            )
            + _ligne("Taux horaire", f"{taux_supp} $/h")
        )

    total_salaire = gains.salaire_regulier + gains.heures_supplementaires_montant
    total_indemnites = gains.jours_feries_manuels + gains.vacances

    # Colonne de gauche de la section « Heures travaillées et salaire » —
    # sous-sections « Salaire » puis « Indemnités » l'une sous l'autre
    # (emplacement conservé, discussion utilisateur).
    html_colonne_salaire = f"""
        {_sous_titre("Salaire")}
        <table class="bulletin-lignes">
            {lignes_salaire}
            {_ligne("Total salaire", f"{total_salaire} $", css_ligne="bulletin-total")}
        </table>
        {_sous_titre("Indemnités", marge_haut=True)}
        <table class="bulletin-lignes">
            {_ligne("Jours fériés", f"{gains.jours_feries_manuels} $")}
            {_ligne("Congés annuels", f"{gains.vacances} $")}
            {_ligne("Total indemnités", f"{total_indemnites} $", css_ligne="bulletin-total")}
            {_ligne(
                "Salaire BRUT (salaire + indemnités)",
                f"{gains.brut_total} $",
                css_ligne="bulletin-total-fort",
            )}
        </table>
    """

    # Colonne de droite de la section « Heures travaillées et salaire » —
    # sous-section « Déductions fiscales » (remplace l'ancienne
    # sous-section « Cotisation employeur », déplacée en section de fin
    # de bulletin — discussion utilisateur).
    html_colonne_deductions = f"""
        {_sous_titre("Déductions fiscales")}
        <table class="bulletin-lignes">
            {_ligne("Impôt fédéral", f"{ret.impot_federal_retenu.montant} $")}
            {_ligne("Impôt provincial", f"{ret.impot_qc_retenu.montant} $")}
            {_ligne("Régime des rentes du Québec (RRQ)", f"{ret.rrq.montant} $")}
            {_ligne("Assurance-emploi (AE)", f"{ret.ae.montant} $")}
            {_ligne(
                "Régime québécois d'assurance parentale (RQAP)",
                f"{ret.rqap.montant} $",
            )}
            {_ligne(
                "Total des déductions",
                f"{ret.total_retenues_employe} $",
                css_ligne="bulletin-total-fort-neutre",
            )}
        </table>
    """

    # ------------------------------------------------------------------
    # Section « Cotisation employeur (pour information seulement) » —
    # promue de sous-section à section de premier niveau, déplacée en
    # toute dernière position du bulletin, après l'encadré du salaire
    # NET (discussion utilisateur : information secondaire pour
    # l'employé, ne doit pas concurrencer visuellement le NET).
    # ------------------------------------------------------------------
    taux_cnesst = cot.cnesst.trace.parametres_utilises.get("taux_total_cnesst")
    libelle_cnesst = "Cotisation CNESST"
    if taux_cnesst is not None:
        libelle_cnesst += f" (taux {taux_cnesst})"
    if cot.cnesst_en_attente_classification:
        libelle_cnesst += " — classification en attente"

    html_section_cotisations = f"""
        <div class="bulletin-section-titre bulletin-section-titre-fin">
            Cotisation employeur (pour information seulement)
        </div>
        <table class="bulletin-lignes">
            {_ligne("Régime des rentes du Québec (RRQ)", f"{cot.rrq_employeur.montant} $")}
            {_ligne("Assurance-emploi (AE)", f"{cot.ae_employeur.montant} $")}
            {_ligne(
                "Régime québécois d'assurance parentale (RQAP)",
                f"{cot.rqap_employeur.montant} $",
            )}
            {_ligne(html.escape(libelle_cnesst), f"{cot.cnesst.montant} $")}
            {_ligne("Fonds des services de santé (FSS)", f"{cot.fss.montant} $")}
            {_ligne(
                "Cotisation relative aux normes du travail (CNT)",
                f"{cot.cnt.montant} $",
            )}
            {_ligne(
                "Total cotisations employeur",
                f"{cot.total_cotisations_employeur} $",
                css_ligne="bulletin-total-fort",
            )}
        </table>
    """

    prenom_html = html.escape(prenom_affiche)
    nom_html = html.escape(nom_affiche)
    nas_html = (
        _lien_fiche_employe(employe.id, html.escape(nas_affiche))
        if nas_manquant
        else html.escape(nas_affiche)
    )
    titre_emploi_html = html.escape(employe.titre_emploi)

    logo_data_uri = _logo_en_data_uri()
    logo_html = (
        f'<img src="{logo_data_uri}" alt="Camp LilySO">'
        if logo_data_uri is not None
        else ""
    )

    return f"""
    {_CSS_BULLETIN}
    <div class="bulletin-conteneur">
        <div class="bulletin-entete">
            {logo_html}
            <div class="bulletin-titre-principal">Bulletin de paie</div>
        </div>

        <div class="bulletin-section-titre">Identification</div>
        <div class="bulletin-deux-colonnes">
            <div class="bulletin-colonne">
                {_sous_titre("Salarié")}
                <table class="bulletin-lignes">
                    {_ligne("Prénom", prenom_html)}
                    {_ligne("Nom", nom_html)}
                    {_ligne("NAS", nas_html)}
                    {_ligne("Date d'embauche", str(employe.date_embauche))}
                    {_ligne("Emploi", titre_emploi_html)}
                </table>
            </div>
            <div class="bulletin-colonne">
                {_sous_titre("Employeur")}
                <table class="bulletin-lignes">
                    {_ligne("Nom", html.escape(CONFIG_EMPLOYEUR.nom))}
                    {_ligne("Adresse", html.escape(CONFIG_EMPLOYEUR.adresse))}
                    {_ligne("Ville", html.escape(CONFIG_EMPLOYEUR.ville))}
                    {_ligne("Code postal", html.escape(CONFIG_EMPLOYEUR.code_postal))}
                    {_ligne("Numéro NQE", html.escape(CONFIG_EMPLOYEUR.numero_nqe))}
                </table>
            </div>
        </div>

        <div class="bulletin-section-titre">Période</div>
        <table class="bulletin-lignes">
            {_ligne(
                "Période correspondant au paiement",
                f"du {semaines[0].date_debut} au {semaines[-1].date_fin}",
            )}
            {_ligne("Date de paiement", str(paie.pay_period.date_paiement))}
        </table>

        <div class="bulletin-section-titre">Heures travaillées et salaire</div>
        <div class="bulletin-deux-colonnes">
            <div class="bulletin-colonne">{html_colonne_salaire.strip()}</div>
            <div class="bulletin-colonne">{html_colonne_deductions.strip()}</div>
        </div>

        <div class="bulletin-net">
            <span>Salaire NET (salaire brut - déductions)</span>
            <span>{paie.net} $</span>
        </div>

        {html_section_cotisations}
    </div>
    """


@st.dialog("Confirmer la suppression")
def _dialogue_confirmation_suppression_paie(
    id_paie: str, prenom_affiche: str, nom_affiche: str
) -> None:
    """Popup de confirmation avant `annuler_paie` (destructif — Req 4.3 à
    4.5, 4.10).

    Le titre du widget `st.dialog` lui-même reste statique (« Confirmer
    la suppression ») — le titre *exact* exigé par le Req 4.3
    (« Supprimer la paie de {Prénom Nom} ? ») est le premier `st.write`
    rendu dans le corps de la popup, construit dynamiquement à partir de
    `prenom_affiche`/`nom_affiche` (voir Property 7 du design). Après une
    annulation réussie (`st.rerun()`), la paie relue affiche son nouveau
    statut `ANNULEE` — les boutons « Corriger cette paie » et « Supprimer
    la paie » disparaissent naturellement (Req 4.10), visibles uniquement
    si `paie.statut == StatutDePaie.EMISE` (voir `render()`).
    """
    nom_complet = f"{prenom_affiche} {nom_affiche}".strip()
    st.write(f"Supprimer la paie de {nom_complet} ?")
    st.write(
        "Cette paie est marquée comme émise, si vous la supprimez, vous "
        "perdrez le calcul du salaire et des cotisations."
    )
    col_confirmer, col_annuler = st.columns(2)
    with col_confirmer:
        st.markdown(_CSS_BOUTON_DANGER, unsafe_allow_html=True)
        if st.button(
            f"Supprimer la paie de {nom_complet}",
            key="bulletin_supprimer_confirmer",
        ):
            resultat = executer_avec_capture(
                lambda: annuler_paie(id_paie, chemin_bd=chemin_bd_production())
            )
            if isinstance(resultat, ErreurDomaineAffichable):
                st.error(f"{resultat.type_exception}: {resultat.message}")
            else:
                st.rerun()
    with col_annuler:
        if st.button("Annuler", key="bulletin_supprimer_annuler"):
            st.rerun()


def render() -> None:
    """Rendu du Bulletin_De_Paie — consultation en lecture seule.

    Bouton « Corriger cette paie » entre le titre et le contenu (haut de
    page, visible uniquement si la paie est `EMISE`), puis bulletin
    imprimable (HTML/CSS, un seul bloc `st.markdown`) reproduisant le
    gabarit officiel, suivi d'une section d'audit (traces de calcul)
    masquée à l'impression.
    """
    # Bug UI signalé après démo : en plus de `st.session_state` (écrit
    # par un bouton Streamlit natif avant `st.switch_page`), l'``id_paie``
    # cible est désormais aussi accepté via `st.query_params["id_paie"]`
    # — nécessaire pour les liens HTML de la colonne « Actions » des
    # tableaux Employés/Paies (`tableau_de_bord.py`,
    # `fiche_employe_detaillee.py`, désormais de vrais éléments `<table>`
    # sémantiques, Req demande explicite de l'utilisateur), qui ne
    # peuvent écrire aucun `st.session_state` avant la navigation — même
    # mécanisme déjà en place pour `employe_id` sur
    # `fiche_employe_detaillee.py`.
    # Bug UI signalé après démo (demande explicite de l'utilisateur) :
    # lien de retour vers le Tableau_De_Bord au-dessus du titre de page
    # — masqué à l'impression au même titre que le reste du chrome
    # Streamlit (voir `_CSS_BULLETIN::@media print`, sélecteur
    # `[data-testid="stPageLink"]`).
    afficher_lien_retour_tableau_de_bord()

    id_paie = st.session_state.get(CLE_ID_PAIE_CIBLE) or st.query_params.get(
        "id_paie"
    )
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
    # `lire_paie` retourne désormais un couple (PayrollResult,
    # PayrollInput | None) — le PayrollInput persisté (bugfix
    # `heures-periode-et-persistance-brouillon`) est la SEULE source des
    # heures réellement saisies : `PayrollResult.pay_period.semaines`
    # (`WeekSegment.heures_normales`/`heures_supplementaires`) est
    # toujours à `Decimal("0")` par construction
    # (`deriver_semaines_constituantes`, `app/logique_metier/
    # formulaire_paie.py`) — jamais renseigné par le moteur. Si
    # `payroll_input` est `None` (paie enregistrée avant ce bugfix,
    # colonne `payload_input_json` non renseignée), les heures restent
    # non récupérables — comportement de préservation assumé.
    paie, payroll_input = resultat_paie
    paie: PayrollResult = paie

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
    fiche_coordonnees = (
        None
        if isinstance(resultat_coordonnees, ErreurDomaineAffichable)
        else resultat_coordonnees
    )
    nas_manquant = fiche_coordonnees is None or not fiche_coordonnees.nas
    nas_affiche = (
        fiche_coordonnees.nas
        if fiche_coordonnees is not None and fiche_coordonnees.nas
        else "Non renseigné"
    )
    if (
        fiche_coordonnees is not None
        and fiche_coordonnees.prenom
        and fiche_coordonnees.nom
    ):
        prenom_affiche = fiche_coordonnees.prenom
        nom_affiche = fiche_coordonnees.nom
    else:
        prenom_affiche, nom_affiche = _diviser_nom_affichage(employe.nom_affichage)

    # ------------------------------------------------------------------
    # Titre + barre d'actions en haut à droite (entre le titre et le
    # contenu — Req explicite de l'utilisateur). Toute la barre est
    # masquée à l'impression via la clé de conteneur
    # `bulletin_barre_actions` (voir `_CSS_BULLETIN`,
    # `.st-key-bulletin_barre_actions`).
    #
    # Règle UI 07 (`.kiro/steering/07-ui-boutons.md`) : « Imprimer »
    # (action principale de cette page) porte le visuel **primaire** ;
    # « Corriger cette paie » (action secondaire, peu fréquente) porte
    # le visuel **secondaire**. Avant ce changement, les deux boutons
    # de l'application confondaient « bouton `type=\"primary\"` » et
    # « action principale de la page » — cette page est la première à
    # distinguer explicitement les deux visuels sur un même écran.
    # ------------------------------------------------------------------
    # Bug UI corrigé après livraison : le titre de page est rendu en
    # HTML natif (classe `bulletin-hors-impression`, masquable via
    # `_CSS_BULLETIN`) plutôt que via `st.header` — le bulletin
    # imprimable ci-dessous porte déjà son propre titre
    # (`bulletin-titre-principal`), rendre les deux à l'impression
    # aurait dupliqué le titre.
    col_titre, col_actions = st.columns([3, 2])
    with col_titre:
        st.markdown(
            '<h2 class="bulletin-hors-impression">Bulletin de paie</h2>',
            unsafe_allow_html=True,
        )
    with col_actions, st.container(key="bulletin_barre_actions"):
        # Demande explicite de l'utilisateur : le bouton « Imprimer »
        # (action principale de cette page, visuel primaire — Règle UI
        # 07) reste seul visible en permanence ; les deux actions
        # « Corriger » et « Supprimer » (secondaire/destructive,
        # visibles uniquement si `EMISE`) sont désormais regroupées
        # dans un menu à trois points (`st.popover`, icône
        # `:material/more_vert:`, label vide) plutôt que deux boutons
        # distincts dans la barre — réduit l'encombrement visuel pour
        # deux actions peu fréquentes, cohérent avec le bouton icône
        # crayon déjà utilisé par `fiche_employe_detaillee.py::
        # _afficher_entete_section` pour un besoin similaire (action
        # secondaire discrète). Le menu lui-même n'est affiché que si
        # au moins une des deux actions est pertinente pour cette
        # paie — actuellement les deux partagent la même condition de
        # visibilité (`EMISE` uniquement), donc le menu entier est
        # masqué pour toute autre statut plutôt que de l'afficher vide.
        col_action_imprimer, col_action_menu = st.columns([4, 1])
        with col_action_menu:
            if paie.statut == StatutDePaie.EMISE:
                with st.popover(
                    "",
                    icon=":material/more_vert:",
                    help="Autres actions",
                    key="bulletin_menu_actions",
                ):
                    if st.button(
                        "Corriger",
                        icon=":material/edit:",
                        type="secondary",
                        key="bulletin_corriger_ouvrir",
                        use_container_width=True,
                    ):
                        st.session_state["fp_corriger_ancien_id_precharge"] = id_paie
                        from app.pages_ui._navigation import page_formulaire_paie

                        st.switch_page(page_formulaire_paie)
                    st.markdown(_CSS_BOUTON_DANGER, unsafe_allow_html=True)
                    if st.button(
                        "Supprimer",
                        icon=":material/delete:",
                        key="bulletin_supprimer_ouvrir",
                        use_container_width=True,
                    ):
                        _dialogue_confirmation_suppression_paie(
                            id_paie, prenom_affiche, nom_affiche
                        )
        with col_action_imprimer:
            # `components.v1.html` (et non `st.markdown`) — voir
            # docstring de module : seul ce mécanisme laisse passer
            # l'attribut `onclick` nécessaire à `window.parent.print()`.
            components.html(_BOUTON_IMPRIMER_HTML, height=48)

    # ------------------------------------------------------------------
    # Heures travaillées — source unique : le PayrollInput persisté.
    # ------------------------------------------------------------------
    if payroll_input is not None:
        heures_normales_totales = sum(
            (s.heures_normales for s in payroll_input.heures_par_semaine),
            start=Decimal("0"),
        )
        heures_supp_totales = sum(
            (s.heures_supplementaires for s in payroll_input.heures_par_semaine),
            start=Decimal("0"),
        )
    else:
        heures_normales_totales = None
        heures_supp_totales = None
        st.warning(
            "Heures non récupérables pour cette paie (enregistrée avant "
            "l'ajout de la persistance des heures saisies)."
        )

    # ------------------------------------------------------------------
    # Bulletin imprimable — un seul bloc HTML/CSS.
    #
    # Bug UI corrigé après livraison : le Markdown de Streamlit interprète
    # toute ligne indentée de 4 espaces ou plus comme un bloc de code
    # littéral (règle CommonMark), *avant* même que `unsafe_allow_html`
    # n'entre en jeu — l'imbrication des f-strings dans
    # `_construire_html_bulletin` produit naturellement des lignes très
    # indentées, ce qui affichait le HTML brut au lieu de le faire rendre
    # par le navigateur. `_retirer_indentation` neutralise ce piège en
    # supprimant l'indentation de chaque ligne avant l'appel à
    # `st.markdown` — le CSS (`_CSS_BULLETIN`) ne dépend d'aucune
    # indentation significative, cette opération est donc sans risque.
    # ------------------------------------------------------------------
    st.markdown(
        _retirer_indentation(
            _construire_html_bulletin(
                employe=employe,
                prenom_affiche=prenom_affiche,
                nom_affiche=nom_affiche,
                nas_affiche=nas_affiche,
                nas_manquant=nas_manquant,
                paie=paie,
                heures_normales_totales=heures_normales_totales,
                heures_supp_totales=heures_supp_totales,
            )
        ),
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Détails des calculs (audit) — traces consultables (règle 02),
    # masquées à l'impression (`data-testid="stExpander"`).
    # ------------------------------------------------------------------
    with st.expander("Détails des calculs (audit)", expanded=False):
        st.write("**Retenues employé**")
        _afficher_trace_montant("Impôt fédéral", paie.retenues_employe.impot_federal_retenu)
        _afficher_trace_montant("Impôt provincial", paie.retenues_employe.impot_qc_retenu)
        _afficher_trace_montant("RRQ (employé)", paie.retenues_employe.rrq)
        _afficher_trace_montant("AE (employé)", paie.retenues_employe.ae)
        _afficher_trace_montant("RQAP (employé)", paie.retenues_employe.rqap)
        st.write("**Cotisations employeur**")
        _afficher_trace_montant("RRQ (employeur)", paie.cotisations_employeur.rrq_employeur)
        _afficher_trace_montant("AE (employeur)", paie.cotisations_employeur.ae_employeur)
        _afficher_trace_montant("RQAP (employeur)", paie.cotisations_employeur.rqap_employeur)
        _afficher_trace_montant("CNESST", paie.cotisations_employeur.cnesst)
        _afficher_trace_montant("FSS", paie.cotisations_employeur.fss)
        _afficher_trace_montant("CNT", paie.cotisations_employeur.cnt)

    # ------------------------------------------------------------------
    # Statut / métadonnées de la paie (hors gabarit, utile à l'audit) —
    # masqué à l'impression (`data-testid="stCaptionContainer"`).
    # ------------------------------------------------------------------
    st.caption(
        f"id_paie={paie.id_paie} | version={paie.version} | "
        f"statut={paie.statut.value} | date de création={paie.date_creation} | "
        f"date d'émission={paie.date_emission if paie.date_emission else 'Non émise'}"
    )
