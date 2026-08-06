"""Rendu Streamlit — historique d'une Paie_Logique et cumuls YTD.

Spec de référence : ``interface-streamlit`` — tâche 25.1 (Req 14, 15).
Design de référence : ``design.md`` §Components §4 ; §Error Handling
« Disjonction stricte », « Points d'appel couverts ».

Ce module porte l'unique fonction publique :func:`render`, exclusivement
du rendu Streamlit — aucune logique métier nouvelle n'est introduite
ici, seuls des relais directs vers des fonctions déjà entièrement
testées par les specs antérieures du moteur (`lire_historique_paie`,
`lire_cumuls_ytd`, §Testing Strategy « Hors périmètre du PBT »).

Deux sections indépendantes :

- **Historique d'une Paie_Logique** — sélection `employe_id`,
  `annee_fiscale`, `numero_periode`, invocation de
  `lire_historique_paie(...)` via `executer_avec_capture`, affichage
  ordonné par `version` croissant (Req 14.1 ; l'ordre `ASC` est déjà
  garanti par `payroll_engine.register.lire_historique_paie`, aucun tri
  supplémentaire n'est effectué ici) ; tuple vide indiqué explicitement
  sans erreur (Req 14.2) ; affichage minimal par version — `id_paie`,
  `version`, `statut`, `remplace_par_id`, `date_creation`,
  `date_emission`, `net` (Req 14.3).
- **Cumuls YTD d'un employé** — sélection `employe_id`, `annee_civile`,
  invocation de `lire_cumuls_ytd(...)` via `executer_avec_capture`,
  affichage des onze catégories monétaires du `CumulsYTD` retourné
  (Req 15.1) ; absence de ligne déjà traduite par `lire_cumuls_ytd` en
  `CumulsYTD.zero(...)` — affichée telle quelle, sans traitement
  particulier ni exception dans cette fonction (Req 15.2).

Toute exception traverse exclusivement `executer_avec_capture`
(`app/logique_metier/erreurs.py`) — aucun `except Exception`/`except
BaseException` ici (Req 16.1, 16.3, vérifié par
`TestAucunExceptGenerique`).

Les deux appels au registre utilisent la signature exacte déjà figée
de `lire_historique_paie(employe_id, annee_fiscale, numero_periode,
chemin_bd)` et `lire_cumuls_ytd(employe_id, annee_civile, chemin_bd)`
(Req 18.3, vérifié par `TestSignaturesExactesMoteur`) — aucun argument
positionnel ou nommé supplémentaire.
"""

from __future__ import annotations

import streamlit as st

from app.logique_metier.annuaire_employes import lister_employes
from app.logique_metier.dernieres_paies import (
    annees_disponibles,
    filtrer_par_annee,
    lire_resumes_paies,
    numeros_periode_disponibles,
)
from app.logique_metier.erreurs import ErreurDomaineAffichable, executer_avec_capture
from models.cumuls import CumulsYTD
from payroll_engine.register import chemin_bd_production, lire_cumuls_ytd, lire_historique_paie

#: Les onze catégories monétaires de `CumulsYTD`, dans l'ordre du design
#: §Data Models 6 (repris de `models/cumuls.py::_CATEGORIES_MONETAIRES`,
#: dupliqué ici en local pour l'affichage seulement — ce module ne
#: réimporte pas le tuple privé du module `models.cumuls`).
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
    """Rendu de la page « Historique et cumuls » (Req 14, 15).

    Deux sections indépendantes, chacune protégée par
    `executer_avec_capture` — une erreur dans une section n'empêche pas
    l'affichage de l'autre.
    """
    st.header("Historique des paies et cumuls annuels")

    resultat_employes = executer_avec_capture(lambda: lister_employes())
    if isinstance(resultat_employes, ErreurDomaineAffichable):
        st.error(f"{resultat_employes.type_exception}: {resultat_employes.message}")
        return
    employes = resultat_employes

    if not employes:
        st.info("Aucun employé dans l'annuaire.")
        return

    options_employes = [e.id for e in employes]

    # ------------------------------------------------------------------
    # Section 1 — Historique d'une Paie_Logique (Req 14)
    # ------------------------------------------------------------------
    st.subheader("Historique d'une paie")

    employe_id_historique = st.selectbox(
        "Employé", options_employes, key="historique_employe_id"
    )

    # Bug UI corrigé après livraison (Req 14) : l'année fiscale et le
    # numéro de période étaient saisis via des `st.number_input` libres
    # (n'importe quelle valeur entre 2000/2100 ou 1/27), sans lien avec
    # les paies réellement existantes pour l'employé sélectionné. Les
    # deux sélecteurs sont désormais des listes déroulantes alimentées
    # par `lire_resumes_paies` — uniquement les années/numéros de
    # période pour lesquels cet employé a au moins une paie.
    resultat_resumes_historique = executer_avec_capture(
        lambda: lire_resumes_paies(
            employe_id_historique, chemin_bd=chemin_bd_production()
        )
    )
    if isinstance(resultat_resumes_historique, ErreurDomaineAffichable):
        st.error(
            f"{resultat_resumes_historique.type_exception}: "
            f"{resultat_resumes_historique.message}"
        )
        return
    resumes_historique = resultat_resumes_historique

    annees_historique = annees_disponibles(resumes_historique)
    if not annees_historique:
        st.info(f"Aucune paie enregistrée pour {employe_id_historique}.")
        return

    annee_fiscale = st.selectbox(
        "Année fiscale", annees_historique, key="historique_annee_fiscale"
    )

    numeros_periode_historique = numeros_periode_disponibles(
        filtrer_par_annee(resumes_historique, int(annee_fiscale))
    )
    if not numeros_periode_historique:
        st.info(
            f"Aucune paie enregistrée pour {employe_id_historique} en "
            f"{int(annee_fiscale)}."
        )
        return

    numero_periode = st.selectbox(
        "Numéro de période",
        numeros_periode_historique,
        key="historique_numero_periode",
    )

    if st.button("Consulter l'historique", type="primary"):
        resultat_historique = executer_avec_capture(
            lambda: lire_historique_paie(
                employe_id_historique,
                int(annee_fiscale),
                int(numero_periode),
                chemin_bd=chemin_bd_production(),
            )
        )
        if isinstance(resultat_historique, ErreurDomaineAffichable):
            st.error(
                f"{resultat_historique.type_exception}: {resultat_historique.message}"
            )
        elif not resultat_historique:
            # Req 14.2 — tuple vide indiqué explicitement, sans erreur.
            st.info(
                "Aucune paie trouvée pour cette paie "
                f"(employé={employe_id_historique}, "
                f"année fiscale={int(annee_fiscale)}, "
                f"numéro de période={int(numero_periode)})."
            )
        else:
            # Déjà ordonné par `version` croissant par
            # `lire_historique_paie` (ORDER BY version ASC) — aucun
            # tri supplémentaire ici (Req 14.1).
            for version_paie in resultat_historique:
                st.write(
                    f"id_paie={version_paie.id_paie} | "
                    f"version={version_paie.version} | "
                    f"statut={version_paie.statut.value} | "
                    f"remplace_par_id={version_paie.remplace_par_id} | "
                    f"date_creation={version_paie.date_creation} | "
                    f"date_emission={version_paie.date_emission} | "
                    f"net={version_paie.net}"
                )

    st.divider()

    # ------------------------------------------------------------------
    # Section 2 — Cumuls YTD d'un employé (Req 15)
    # ------------------------------------------------------------------
    st.subheader("Cumuls annuels d'un employé")

    employe_id_cumuls = st.selectbox(
        "Employé", options_employes, key="cumuls_employe_id"
    )

    # Même correction que ci-dessus (Req 15) : l'année civile est
    # désormais une liste déroulante alimentée par les paies réellement
    # existantes de l'employé sélectionné, plutôt qu'un `st.number_input`
    # libre. `annee_fiscale` (utilisée par `lire_resumes_paies`) et
    # `annee_civile` (utilisée par `lire_cumuls_ytd`) désignent la même
    # notion d'année dans ce contexte (Req 15.1) — aucune conversion
    # additionnelle n'est nécessaire.
    resultat_resumes_cumuls = executer_avec_capture(
        lambda: lire_resumes_paies(employe_id_cumuls, chemin_bd=chemin_bd_production())
    )
    if isinstance(resultat_resumes_cumuls, ErreurDomaineAffichable):
        st.error(
            f"{resultat_resumes_cumuls.type_exception}: "
            f"{resultat_resumes_cumuls.message}"
        )
        return
    resumes_cumuls = resultat_resumes_cumuls

    annees_cumuls = annees_disponibles(resumes_cumuls)
    if not annees_cumuls:
        st.info(f"Aucune paie enregistrée pour {employe_id_cumuls}.")
        return

    annee_civile = st.selectbox(
        "Année civile", annees_cumuls, key="cumuls_annee_civile"
    )

    if st.button("Consulter les cumuls", type="primary"):
        resultat_cumuls = executer_avec_capture(
            lambda: lire_cumuls_ytd(
                employe_id_cumuls,
                int(annee_civile),
                chemin_bd=chemin_bd_production(),
            )
        )
        if isinstance(resultat_cumuls, ErreurDomaineAffichable):
            st.error(f"{resultat_cumuls.type_exception}: {resultat_cumuls.message}")
        else:
            # Req 15.2 — absence de ligne déjà traduite par
            # `lire_cumuls_ytd` en `CumulsYTD.zero(...)`, affichée telle
            # quelle, sans traitement particulier ici.
            cumuls: CumulsYTD = resultat_cumuls
            for categorie in _CATEGORIES_CUMULS_AFFICHAGE:
                st.write(f"{categorie} = {getattr(cumuls, categorie)}")
