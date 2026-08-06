"""Dernières paies et résumés — lecture SQL directe du registre maître.

Spec de référence : ``interface-streamlit`` — tâche 15.1.
Design de référence : ``design.md`` §Components §4 (`dernieres_paies.py`
— lecture SQL directe, sans fonction privée de `register.py`) ;
§Correctness Properties 5, 6, 7 ; décision n° 5 ; règle 01.

Ce module porte :

- :func:`derniere_annee_paie` — maximum de `annee_fiscale` pour un
  `employe_id` donné, `None` si aucune paie ou base neuve sans table
  `paies` (Req 4.3, 18.2) (tâche 15.1) ;
- :class:`LignePaieResume` — dataclass immuable portant un résumé
  minimal d'une paie pour l'affichage (Req 5.3, 18.2) (tâche 15.1) ;
- :func:`lire_resumes_paies` — lecture SQL directe de tous les résumés
  de paie d'un employé (Req 5.2, 5.3, 18.2) (tâche 15.2) ;
- :func:`filtrer_par_annee` — filtre pur par `annee_fiscale` (Req 5.3)
  (tâche 15.2) ;
- :func:`regrouper_saison_par_annee` — saison la plus récente par
  année fiscale (Req 5.2) (tâche 15.2) ;
- :func:`formater_option_annee` — libellé d'option du sélecteur
  d'année (Req 5.2) (tâche 15.2).

Décision n° 5 (design) : ce module interroge la table `paies` en SQL
direct via `sqlite3.connect`, sans jamais appeler de fonction privée
(préfixée `_`) de `payroll_engine.register` — notamment pas
`_creer_schema_si_absent`. Sur une base neuve (fichier absent ou
`":memory:"`), la table `paies` n'existe pas encore : `sqlite3` lève
alors `sqlite3.OperationalError` avec un message contenant
`"no such table"`. Cette exception est interceptée explicitement et
traduite en `None` — jamais laissée se propager. Toute autre
`OperationalError` (ex. base corrompue, verrou) est repropagée sans
interception (Req 4.3, 18.2).

Règle 01 : `LignePaieResume.net` reste une chaîne (`str`) — la
représentation `Decimal` sérialisée d'origine du `payload_json`, jamais
reconvertie en `float`.

Règle 04 (données sensibles) : `chemin_bd` par défaut
(`chemin_bd_production()`) résout un chemin hors dépôt ; les tests
(tâche 5) injectent exclusivement des chemins temporaires ou
`":memory:"`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from models.payroll_result import PayrollResult
from payroll_engine.register import chemin_bd_production


def derniere_annee_paie(
    employe_id: str,
    chemin_bd: str | Path = chemin_bd_production(),
) -> int | None:
    """Dernière année fiscale de paie de ``employe_id`` (Req 4.3, 18.2).

    Interroge `paies` en SQL direct (`SELECT MAX(annee_fiscale) ...`).
    Sur une base neuve sans table `paies`, `sqlite3.OperationalError`
    (message contenant `"no such table"`) est interceptée explicitement
    et traduite en `None` — toute autre `OperationalError` est
    repropagée sans interception (décision n° 5). Retourne également
    `None` si aucune paie n'existe pour ``employe_id``.
    """
    try:
        connexion = sqlite3.connect(str(chemin_bd))
        try:
            ligne = connexion.execute(
                "SELECT MAX(annee_fiscale) FROM paies WHERE employe_id = ?",
                (employe_id,),
            ).fetchone()
        finally:
            connexion.close()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise
    if ligne is None or ligne[0] is None:
        return None
    return int(ligne[0])


@dataclass(frozen=True)
class LignePaieResume:
    """Résumé minimal d'une paie pour l'affichage (Req 5.3, 18.2)."""

    id_paie: str
    numero_periode: int
    version: int
    statut: str
    net: str  # Decimal sérialisé en chaîne — jamais reconverti en float
    saison: str
    annee_fiscale: int
    date_creation: str
    date_emission: str | None = None
    """Date d'émission officielle (Req 6.7 de `PayrollResult` — requise
    dès que `statut` ∈ {EMISE, ANNULEE, REMPLACE_PAR}) ; `None` en
    `BROUILLON`. Ajouté après livraison pour le Tableau_De_Bord (statut
    et date de la dernière paie créée d'un employé)."""
    date_paiement: str | None = None
    """Date de paiement de la période (`PayrollResult.pay_period.
    date_paiement`), ajoutée après livraison pour le tableau des paies
    de la Fiche_Employe_Detaillee. `None` seulement si absente du
    `payload_json` (ne devrait jamais arriver — `PayPeriod.date_paiement`
    est un champ requis — mais un défaut défensif évite une régression
    si le schéma évoluait)."""


def lire_resumes_paies(
    employe_id: str,
    chemin_bd: str | Path = chemin_bd_production(),
) -> tuple[LignePaieResume, ...]:
    """Résumés de toutes les paies de ``employe_id`` (Req 5.2, 5.3, 18.2).

    Interroge `paies` en SQL direct (`SELECT` des colonnes documentées),
    sans jamais appeler de fonction privée de `register.py` (décision
    n° 5). Sur une base neuve sans table `paies`,
    `sqlite3.OperationalError` (message contenant `"no such table"`) est
    interceptée explicitement et traduite en tuple vide — toute autre
    `OperationalError` est repropagée sans interception (même discipline
    que `derniere_annee_paie`, tâche 15.1).

    `net` est extrait de `PayrollResult.model_validate_json(payload_json)
    .net`, converti en `str` — jamais reconverti en `float` (règle 01).
    Le résultat est trié par `(annee_fiscale, date_creation)`.
    """
    try:
        connexion = sqlite3.connect(str(chemin_bd))
        try:
            lignes = connexion.execute(
                "SELECT id_paie, numero_periode, saison, version, statut, "
                "annee_fiscale, date_creation, date_emission, payload_json "
                "FROM paies WHERE employe_id = ?",
                (employe_id,),
            ).fetchall()
        finally:
            connexion.close()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return ()
        raise

    resumes = []
    for (
        id_paie,
        numero_periode,
        saison,
        version,
        statut,
        annee_fiscale,
        date_creation,
        date_emission,
        payload_json,
    ) in lignes:
        resultat = PayrollResult.model_validate_json(payload_json)
        resumes.append(
            LignePaieResume(
                id_paie=id_paie,
                numero_periode=numero_periode,
                version=version,
                statut=statut,
                net=str(resultat.net),
                saison=saison,
                annee_fiscale=annee_fiscale,
                date_creation=date_creation,
                date_emission=date_emission,
                date_paiement=resultat.pay_period.date_paiement.isoformat(),
            )
        )
    return tuple(sorted(resumes, key=lambda r: (r.annee_fiscale, r.date_creation)))


def filtrer_par_annee(
    resumes: tuple[LignePaieResume, ...], annee_fiscale: int
) -> tuple[LignePaieResume, ...]:
    """Sous-ensemble de ``resumes`` de ``annee_fiscale`` (Req 5.3).

    Filtre pur : même ordre relatif que ``resumes``, sans altération
    d'aucun champ.
    """
    return tuple(r for r in resumes if r.annee_fiscale == annee_fiscale)


def regrouper_saison_par_annee(
    resumes: tuple[LignePaieResume, ...]
) -> dict[int, str | None]:
    """Saison la plus récente par `annee_fiscale` (Req 5.2).

    Pour chaque `annee_fiscale` présente dans ``resumes``, retient la
    `saison` du résumé de `date_creation` maximale.
    """
    par_annee: dict[int, LignePaieResume] = {}
    for resume in resumes:
        actuel = par_annee.get(resume.annee_fiscale)
        if actuel is None or resume.date_creation > actuel.date_creation:
            par_annee[resume.annee_fiscale] = resume
    return {annee: resume.saison for annee, resume in par_annee.items()}


def formater_option_annee(annee: int, saison: str | None) -> str:
    """Libellé d'option du sélecteur d'année (Req 5.2).

    Produit `"<annee> (<saison>)"` si ``saison`` est non vide, sinon
    `"<annee>"` seul.
    """
    return f"{annee} ({saison})" if saison else str(annee)


def numeros_periode_disponibles(
    resumes: tuple[LignePaieResume, ...]
) -> tuple[int, ...]:
    """Numéros de période distincts présents dans ``resumes``, triés croissant.

    Filtre pur, sans accès disque — destiné à alimenter une liste
    déroulante de numéros de période déjà utilisés par un employé pour
    une année donnée (typiquement après un appel à :func:`filtrer_par_annee`),
    plutôt qu'un `st.number_input` libre acceptant n'importe quelle valeur
    entre 1 et 27. Ergonomie de saisie pure — aucune règle fiscale
    associée, aucune donnée inventée : uniquement les numéros de période
    pour lesquels ``resumes`` contient effectivement au moins une paie.
    """
    return tuple(sorted({r.numero_periode for r in resumes}))


def derniere_paie_creee(
    resumes: tuple[LignePaieResume, ...]
) -> LignePaieResume | None:
    """Résumé de la paie la plus récemment créée (`date_creation` maximale).

    Filtre pur, sans accès disque — destiné au Tableau_De_Bord (Req 4.2)
    pour afficher le statut et la date pertinente (`date_emission` si
    `EMISE`/`ANNULEE`/`REMPLACE_PAR`, `date_creation` sinon —
    `BROUILLON`) de la dernière paie créée d'un employé, en complément
    de :func:`derniere_annee_paie` (qui ne renvoie que l'année).
    `None` si ``resumes`` est vide (aucune paie enregistrée).
    """
    if not resumes:
        return None
    return max(resumes, key=lambda r: r.date_creation)


def annees_disponibles(resumes: tuple[LignePaieResume, ...]) -> tuple[int, ...]:
    """Années fiscales distinctes présentes dans ``resumes``, triées croissant.

    Filtre pur, sans accès disque — destiné à alimenter une liste
    déroulante des années pour lesquelles un employé a au moins une paie
    (écran « Historique et cumuls »), plutôt qu'un `st.number_input`
    libre acceptant n'importe quelle année entre 2000 et 2100. Même
    discipline que :func:`numeros_periode_disponibles`.
    """
    return tuple(sorted({r.annee_fiscale for r in resumes}))


def prochaine_version(
    resumes: tuple[LignePaieResume, ...], numero_periode: int
) -> int:
    """Version suivante à utiliser pour insérer une nouvelle Paie_Logique
    de ``numero_periode`` (bug UI corrigé après livraison).

    Filtre pur, sans accès disque — évite la collision d'``id_paie``
    lorsqu'un opérateur poursuit la saisie d'un `BROUILLON` plusieurs
    fois avant de l'émettre : `payroll_engine.register.remplacer_paie`
    exige que la paie remplacée soit `EMISE` (Req 13.2 du moteur), donc
    toute poursuite de saisie d'un `BROUILLON` insère une **nouvelle
    version** via `inserer_paie` (append-only) plutôt que de remplacer
    l'ancienne ligne — cette fonction détermine le numéro de version à
    utiliser pour cette nouvelle insertion.

    Retourne `max(versions) + 1` pour les résumés dont `numero_periode`
    correspond, ou `1` si aucun résumé ne correspond (première
    insertion pour ce numéro de période).
    """
    versions = tuple(
        r.version for r in resumes if r.numero_periode == numero_periode
    )
    return max(versions, default=0) + 1


def dernieres_versions_par_periode(
    resumes: tuple[LignePaieResume, ...]
) -> tuple[LignePaieResume, ...]:
    """Ne conserve que la version la plus récente de chaque `numero_periode`.

    Filtre pur, sans accès disque — décision opérationnelle du Camp
    LilySO (discussion utilisateur, pas une règle du moteur) : le
    tableau des paies de la Fiche_Employe_Detaillee n'affiche que la
    version la plus récente de chaque `numero_periode`, jamais les
    versions intermédiaires devenues obsolètes.

    Contexte : `payroll_engine.register.remplacer_paie` exige que la
    paie remplacée soit `EMISE` (Req 13.2 du moteur) — il n'existe donc
    aucun mécanisme de remplacement pour un `BROUILLON`. Poursuivre la
    saisie d'un brouillon insère par conséquent une **nouvelle version**
    via `inserer_paie` (append-only) plutôt que de remplacer l'ancienne
    ligne ; le brouillon précédent demeure dans le registre (jamais
    supprimé) mais ce filtre l'exclut de l'affichage.

    Pour chaque `numero_periode` présent dans ``resumes``, retient le
    résumé de `version` maximale. Résultat trié par `numero_periode`
    croissant (contrairement à :func:`lire_resumes_paies`, trié par
    `date_creation`) — ordre attendu pour un tableau de paies par
    période.
    """
    par_periode: dict[int, LignePaieResume] = {}
    for resume in resumes:
        actuel = par_periode.get(resume.numero_periode)
        if actuel is None or resume.version > actuel.version:
            par_periode[resume.numero_periode] = resume
    return tuple(
        par_periode[numero_periode]
        for numero_periode in sorted(par_periode.keys())
    )
