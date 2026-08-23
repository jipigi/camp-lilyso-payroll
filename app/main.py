"""Point d'entrée de l'Interface_Streamlit — `streamlit run app/main.py`.

Spec de référence : ``interface-streamlit`` — tâche 26.1 (Req 3.2, 4.1,
17.1, 17.2, 17.3).
Design de référence : ``design.md`` §Architecture « Navigation
multipage ».

Ce module assemble les six pages de rendu de `app/pages_ui/`
(`tableau_de_bord`, `nouvel_employe`, `fiche_employe_detaillee`,
`formulaire_paie`, `historique_et_cumuls`, `bulletin_paie`) via
`st.Page`/`st.navigation` (décision n° 6) et applique l'identité
visuelle globale (`st.set_page_config`, Req 3.2). `nouvel_employe`
(Req 4.4) et `bulletin_paie` (consultation d'une paie émise) ont été
ajoutées après livraison — voir `app/pages_ui/nouvel_employe.py` et
`app/pages_ui/bulletin_paie.py`.

Aucune logique métier n'est introduite ici : ce module se contente de
déclarer la structure de navigation et de démarrer son exécution
(`navigation.run()`). Il ne dépend d'aucun module de génération de
bulletin absent du moteur figé (Req 17.1, 17.2, 17.3) — seules les six
fonctions déjà figées (`assembler_paie`, `inserer_paie`, `lire_paie`,
`lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie`) sont
invoquées, exclusivement depuis `app/logique_metier/**` et
`app/pages_ui/**`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garantit que la racine du dépôt (contenant `app/`, `models/`,
# `payroll_engine/`) est résolvable comme package top-level, quelle que
# soit la façon dont Streamlit invoque ce script (`streamlit run
# app/main.py` n'ajoute pas nécessairement la racine du dépôt à
# `sys.path`, contrairement à `python -m streamlit run ...` depuis la
# racine) — nécessaire notamment sur Streamlit Community Cloud, où le
# projet n'est plus installé comme package Python depuis la désactivation
# du mode package de Poetry (`package-mode = false`, pyproject.toml).
_RACINE_DEPOT = str(Path(__file__).resolve().parent.parent)
if _RACINE_DEPOT not in sys.path:
    sys.path.insert(0, _RACINE_DEPOT)

import streamlit as st  # noqa: E402

from app.pages_ui import (  # noqa: E402
    bulletin_paie,
    fiche_employe_detaillee,
    formulaire_paie,
    historique_et_cumuls,
    nouvel_employe,
    tableau_de_bord,
)
from app.pages_ui._navigation import configurer_pages  # noqa: E402

st.set_page_config(
    page_title="Camp LilySO — Paie",
    page_icon="app/assets/logo-camp-lilyso.png",
)

page_tableau_de_bord = st.Page(
    tableau_de_bord.render,
    title="Tableau de bord",
    icon=":material/dashboard:",
    url_path="tableau-de-bord",
    default=True,
)
page_nouvel_employe = st.Page(
    nouvel_employe.render,
    title="Nouvel employé",
    icon=":material/person_add:",
    url_path="nouvel-employe",
    # Demande explicite de l'utilisateur : retirée du menu de
    # navigation (seuls le Tableau de bord et la Fiche employé y
    # restent) — la page demeure accessible via le bouton « Ajouter un
    # nouvel employé » du Tableau_De_Bord (`st.switch_page`).
    visibility="hidden",
)
page_fiche_employe = st.Page(
    fiche_employe_detaillee.render,
    title="Fiche employé",
    icon=":material/person:",
    url_path="fiche-employe",
)
page_formulaire_paie = st.Page(
    formulaire_paie.render,
    title="Nouvelle paie / correction",
    icon=":material/receipt_long:",
    url_path="formulaire-paie",
    # Demande explicite de l'utilisateur — accessible via les liens
    # « Ajouter une paie »/« Modifier » des Colonnes_Paies (Tableau_De_
    # Bord, Fiche_Employe_Detaillee), jamais depuis le menu.
    visibility="hidden",
)
page_historique = st.Page(
    historique_et_cumuls.render,
    title="Historique et cumuls annuels",
    icon=":material/history:",
    url_path="historique-et-cumuls",
    # Demande explicite de l'utilisateur — accessible via un lien
    # depuis la Fiche_Employe_Detaillee, jamais depuis le menu.
    visibility="hidden",
)
page_bulletin_paie = st.Page(
    bulletin_paie.render,
    title="Bulletin de paie",
    icon=":material/description:",
    url_path="bulletin-paie",
    # Demande explicite de l'utilisateur — accessible via les liens de
    # paies déjà émises (Tableau_De_Bord, Fiche_Employe_Detaillee),
    # jamais depuis le menu.
    visibility="hidden",
)


# Enregistrement des objets `st.Page` avant `navigation.run()` — permet
# aux modules de rendu (ex. `tableau_de_bord.py`) d'invoquer
# `st.switch_page` avec l'objet `Page` d'origine plutôt qu'un chemin de
# fichier (nécessaire lorsque la page est définie par un callable, voir
# `app/pages_ui/_navigation.py`).
configurer_pages(
    tableau_de_bord=page_tableau_de_bord,
    nouvel_employe=page_nouvel_employe,
    fiche_employe=page_fiche_employe,
    formulaire_paie=page_formulaire_paie,
    historique=page_historique,
    bulletin_paie=page_bulletin_paie,
)

navigation = st.navigation(
    [
        page_tableau_de_bord,
        page_nouvel_employe,
        page_fiche_employe,
        page_formulaire_paie,
        page_historique,
        page_bulletin_paie,
    ]
)
navigation.run()
