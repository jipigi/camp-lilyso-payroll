"""Point d'entrée de l'Interface_Streamlit — `streamlit run app/main.py`.

Spec de référence : ``interface-streamlit`` — tâche 26.1 (Req 3.2, 4.1,
17.1, 17.2, 17.3).
Design de référence : ``design.md`` §Architecture « Navigation
multipage ».

Ce module assemble les cinq pages de rendu de `app/pages_ui/`
(`tableau_de_bord`, `nouvel_employe`, `fiche_employe_detaillee`,
`formulaire_paie`, `historique_et_cumuls`) via `st.Page`/`st.navigation`
(décision n° 6) et applique l'identité visuelle globale
(`st.set_page_config`, Req 3.2). `nouvel_employe` (Req 4.4) a été
ajoutée après livraison — voir `app/pages_ui/nouvel_employe.py`.

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

import streamlit as st

from app.pages_ui import (
    fiche_employe_detaillee,
    formulaire_paie,
    historique_et_cumuls,
    nouvel_employe,
    tableau_de_bord,
)
from app.pages_ui._navigation import configurer_pages

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
)
page_historique = st.Page(
    historique_et_cumuls.render,
    title="Historique et cumuls annuels",
    icon=":material/history:",
    url_path="historique-et-cumuls",
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
)

navigation = st.navigation(
    [
        page_tableau_de_bord,
        page_nouvel_employe,
        page_fiche_employe,
        page_formulaire_paie,
        page_historique,
    ]
)
navigation.run()
