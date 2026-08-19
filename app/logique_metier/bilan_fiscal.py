"""Bilan fiscal employeur — agrégation des retenues et cotisations.

Spec de référence : ``bilan-fiscal-employeur``.
Design de référence : ``design.md`` §Architecture (décisions n° 1, 2, 5) ;
§Components §1 à §5 ; §Correctness Properties 1 à 14.

Ce module est une **pure couche d'agrégation et de lecture** — il ne
touche ni `payroll_engine/` ni `models/`, n'invente aucune nouvelle
`CalculationTrace` ni aucune formule fiscale (règle 02) : il agrège
exclusivement des montants déjà calculés et tracés par le moteur de
paie, lus depuis `PayrollResult.retenues_employe` et
`PayrollResult.cotisations_employeur` déjà persistés dans le Registre_
Maitre (`payroll.db`).

Décision n° 1 (design §Architecture) : nouveau module distinct de
`app/logique_metier/dernieres_paies.py` — celui-ci agrège les paies
d'**un seul employé** (`employe_id` en paramètre), alors que le Bilan_
Fiscal agrège les paies de **tous les employés confondus** pour une
Periode_Fiscale, sans jamais exposer ni filtrer par `employe_id`
(règle 04). Ce module suit néanmoins le même style que
`dernieres_paies.py` (lecture SQL directe via `sqlite3.connect`, jamais
de fonction privée de `payroll_engine.register`, même traduction de
`sqlite3.OperationalError` « no such table » en absence de données —
décision n° 5 de `interface-streamlit`).

Cette tâche (9.1) implémente uniquement le §Components §1 du design —
détermination du Mois_De_Rattachement et construction des options du
Selecteur_De_Periode (Properties 1, 2, 3) :

- :data:`_NOMS_MOIS` — les 12 noms de mois français exacts (Req 2.6) ;
- :class:`PeriodeFiscale` — une Periode_Fiscale (Mois_Fiscal ou
  Annee_Complete) ;
- :class:`OptionPeriode` — une option affichable du Selecteur_De_
  Periode ;
- :func:`mois_annee_rattachement` — extraction pure du Mois_De_
  Rattachement d'une paie (Req 2.2) ;
- :func:`formater_option_annee_complete` /
  :func:`formater_option_mois_fiscal` — formatage des libellés
  (Req 2.5, 2.6) ;
- :func:`construire_options_periode` — construction triée des options
  du Selecteur_De_Periode (Req 2.1, 2.3, 2.4, 2.7).

Les autres fonctions et types du design (présélection par défaut,
filtrage par période, agrégation du Tableau_Bilan_Fiscal, lecture SQL)
sont implémentés par les tâches suivantes (9.2 à 9.5) — ce module reste
volontairement incomplet à ce stade.

Règle 01 : aucune valeur `float` n'est introduite par ce module — les
fonctions de ce fichier ne manipulent que des `int`/`str` (mois/année/
libellés) ; aucun champ monétaire n'est encore agrégé à ce stade.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from models.enums import StatutDePaie
from models.payroll_result import PayrollResult
from payroll_engine.register import chemin_bd_production

_PRECISION_MONNAIE = Decimal("0.01")
"""Précision d'arrondissement monétaire — deux décimales, cohérente avec
`_arrondir` de `payroll_engine/*.py` (RRQ, RQAP, AE, impôts, charges
patronales). Réutilisée telle quelle par :func:`_arrondir_montant`, seul
mécanisme d'arrondissement autorisé par ce module (règle 01)."""


def _arrondir_montant(montant: Decimal) -> Decimal:
    """Arrondit ``montant`` à deux décimales selon `ROUND_HALF_UP`.

    Convention identique à celle des modules `payroll_engine/*.py`
    (`_arrondir` de `rrq.py`, `rqap.py`, `assurance_emploi.py`,
    `impot_qc.py`, `impot_federal.py`, `charges_patronales.py`,
    `gains_bruts.py`) — reprise ici pour l'agrégation du Tableau_Bilan_
    Fiscal (Requirements 6.2-6.4, 8.2-8.7), sans introduire de nouvelle
    formule fiscale (règle 02) : cette fonction ne fait que sommer et
    arrondir des montants déjà calculés et tracés par le moteur de paie.
    """
    return montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)

_NOMS_MOIS: dict[int, str] = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}
"""Les 12 noms de mois français, orthographe et casse exactes imposées
par le Requirement 2.6 (première lettre en majuscule, accents inclus)."""


@dataclass(frozen=True)
class PeriodeFiscale:
    """Une Periode_Fiscale — un Mois_Fiscal (`mois` renseigné) ou une
    Annee_Complete (`mois` absent). Requirements 2, 10."""

    annee: int
    mois: int | None = None  # 1-12 ; None => Annee_Complete


@dataclass(frozen=True)
class OptionPeriode:
    """Une option affichable du Selecteur_De_Periode — libellé pré-formaté
    (Requirement 2.5, 2.6) associé à sa `PeriodeFiscale`."""

    libelle: str
    periode: PeriodeFiscale


def mois_annee_rattachement(date_paiement: date) -> tuple[int, int]:
    """Mois_De_Rattachement (`annee`, `mois`) d'une paie (Requirement 2.2).

    Extraction pure de `PayPeriod.date_paiement.year`/`.month` — aucune
    autre source (ni `annee_fiscale`, ni `date_debut`/`date_fin`,
    décision n° 1 des requirements).
    """
    return (date_paiement.year, date_paiement.month)


def formater_option_annee_complete(annee: int) -> str:
    """`"<annee> (année complète)"` (Requirement 2.5)."""
    return f"{annee} (année complète)"


def formater_option_mois_fiscal(annee: int, mois: int) -> str:
    """`"<Nom_du_mois> <annee>"` avec les 12 noms exacts `_NOMS_MOIS`
    (Requirement 2.6)."""
    return f"{_NOMS_MOIS[mois]} {annee}"


def construire_options_periode(
    paies_emises: tuple[PayrollResult, ...]
) -> tuple[OptionPeriode, ...]:
    """Options du Selecteur_De_Periode (Requirements 2.1, 2.3, 2.4, 2.7).

    Pour chaque `PayrollResult` de ``paies_emises``, détermine le
    Mois_De_Rattachement via :func:`mois_annee_rattachement`. Construit
    l'ensemble des années présentes (Annee_Complete) et l'ensemble des
    couples (mois, année) présents (Mois_Fiscal), formate chaque option
    via :func:`formater_option_annee_complete`/
    :func:`formater_option_mois_fiscal`, puis trie par année décroissante,
    Annee_Complete avant les Mois_Fiscal (croissants) de cette même année
    (Requirement 2.7). Retourne un tuple vide si ``paies_emises`` est
    vide.
    """
    annees_presentes: set[int] = set()
    couples_presents: set[tuple[int, int]] = set()
    for paie in paies_emises:
        annee, mois = mois_annee_rattachement(paie.pay_period.date_paiement)
        annees_presentes.add(annee)
        couples_presents.add((annee, mois))

    options = [
        OptionPeriode(
            libelle=formater_option_annee_complete(annee),
            periode=PeriodeFiscale(annee=annee, mois=None),
        )
        for annee in annees_presentes
    ] + [
        OptionPeriode(
            libelle=formater_option_mois_fiscal(annee, mois),
            periode=PeriodeFiscale(annee=annee, mois=mois),
        )
        for annee, mois in couples_presents
    ]

    options.sort(
        key=lambda option: (
            -option.periode.annee,
            option.periode.mois is not None,
            option.periode.mois or 0,
        )
    )
    return tuple(options)


def filtrer_paies_par_periode(
    paies_emises: tuple[PayrollResult, ...], periode: PeriodeFiscale
) -> tuple[PayrollResult, ...]:
    """Sous-ensemble des Paies_Agregees de ``periode`` (Requirements 10.1,
    10.2, 10.3).

    Si ``periode.mois`` est renseigné (Mois_Fiscal) : conserve les
    `PayrollResult` dont `mois_annee_rattachement(...) == (periode.annee,
    periode.mois)`. Si ``periode.mois`` est `None` (Annee_Complete) :
    conserve les `PayrollResult` dont l'année de rattachement égale
    `periode.annee`, tous mois confondus. ``paies_emises`` est supposé déjà
    filtré sur `statut == EMISE` par :func:`lire_paies_emises` — cette
    fonction ne filtre plus jamais par statut (Requirement 10.3 déjà
    assuré en amont par la requête SQL).
    """
    if periode.mois is not None:
        return tuple(
            paie
            for paie in paies_emises
            if mois_annee_rattachement(paie.pay_period.date_paiement)
            == (periode.annee, periode.mois)
        )

    return tuple(
        paie
        for paie in paies_emises
        if mois_annee_rattachement(paie.pay_period.date_paiement)[0]
        == periode.annee
    )


def determiner_periode_par_defaut(
    aujourdhui: date, options: tuple[OptionPeriode, ...]
) -> PeriodeFiscale | None:
    """Mois_Fiscal présélectionné à l'ouverture de session (Requirements
    3.1, 3.2, 3.3).

    - Si ``1 <= aujourdhui.day <= 15`` : cible le mois **précédant** le
      mois courant (Requirement 3.1).
    - Sinon (``16 <= aujourdhui.day <= dernier jour du mois``) : cible le
      mois **courant** (Requirement 3.2).
    - Si la `PeriodeFiscale` cible ne correspond à aucun `OptionPeriode`
      de type Mois_Fiscal de ``options``, retourne le Mois_Fiscal le plus
      récent parmi ``options`` (Requirement 3.3).
    - Retourne `None` si ``options`` ne contient aucun Mois_Fiscal (cas
      dégénéré — en pratique jamais atteint tant que le Requirement 4
      masque le Selecteur_De_Periode en l'absence totale de paie EMISE).

    Fonction pure — ne lit jamais `st.session_state` ni l'horloge
    elle-même ; l'appelant (`tableau_de_bord.py`) lui fournit
    ``aujourdhui`` (Requirement 3.5).
    """
    if 1 <= aujourdhui.day <= 15:
        if aujourdhui.month == 1:
            annee_cible, mois_cible = aujourdhui.year - 1, 12
        else:
            annee_cible, mois_cible = aujourdhui.year, aujourdhui.month - 1
    else:
        annee_cible, mois_cible = aujourdhui.year, aujourdhui.month

    periodes_mois_fiscal = tuple(
        option.periode for option in options if option.periode.mois is not None
    )

    periode_cible = PeriodeFiscale(annee=annee_cible, mois=mois_cible)
    if periode_cible in periodes_mois_fiscal:
        return periode_cible

    if not periodes_mois_fiscal:
        return None

    return max(periodes_mois_fiscal, key=lambda periode: (periode.annee, periode.mois))


def resoudre_periode_a_afficher(
    cle_deja_definie: bool,
    valeur_en_session: str | None,
    periode_par_defaut: PeriodeFiscale | None,
    options: tuple[OptionPeriode, ...],
) -> str | None:
    """Libellé de la `PeriodeFiscale` à afficher/présélectionner
    (Requirement 3.4).

    Si ``cle_deja_definie`` est vrai (un choix, automatique ou manuel, a
    déjà été résolu durant cette session) ET que ``valeur_en_session``
    correspond encore à une option de ``options``, la retourne inchangée
    (conserve le choix de l'opérateur, Requirement 3.4). Sinon (première
    résolution de la session, ou option devenue indisponible entre deux
    réaffichages), recalcule et retourne le libellé correspondant à
    ``periode_par_defaut`` (ou `None` si ``periode_par_defaut`` est
    `None`).
    """
    if cle_deja_definie and valeur_en_session is not None and any(
        option.libelle == valeur_en_session for option in options
    ):
        return valeur_en_session

    if periode_par_defaut is None:
        return None

    option_correspondante = next(
        (option for option in options if option.periode == periode_par_defaut),
        None,
    )
    return option_correspondante.libelle if option_correspondante else None


# ---------------------------------------------------------------------------
# Agrégation — LigneBilan, calculer_total, TableauBilanFiscal,
# construire_tableau_bilan_fiscal (Requirements 6, 7, 8, 9, 11.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LigneBilan:
    """Une ligne du Tableau_Bilan_Fiscal dont les deux colonnes sont
    toujours calculables (Requirements 6.2-6.5, 8.2-8.7) — `qc`/`ca` sont
    explicitement `Decimal("0")` (jamais `None`) lorsque la juridiction
    ne s'applique pas ou que les paies sources sont absentes."""

    libelle: str
    qc: Decimal
    ca: Decimal


def calculer_total(*cellules: Decimal | None) -> Decimal | None:
    """Somme générique avec propagation de l'indisponibilité (Requirements
    7.1, 7.2, 7.3, 9.1, 9.2, 9.3, 9.4).

    Si ``cellules`` ne contient **aucune** valeur `Decimal` (toutes
    `None`, y compris la séquence vide) : retourne `None` (indicateur
    d'indisponibilité, Requirement 7.3/9.4 — jamais un total calculé).
    Sinon, retourne la somme exacte (arithmétique `Decimal`, sans
    arrondissement additionnel) des cellules non `None`, chaque `None`
    individuel comptant comme zéro dans la somme (Requirement 7.2).

    Fonction unique réutilisée pour les quatre lignes de total du tableau
    (Total des retenues, Total des cotisations, Grand total, Grand total
    combiné) — même sous-fonction générique, appliquée à des jeux de
    cellules différents selon le niveau (design §Correctness Properties,
    Property 10).
    """
    if all(cellule is None for cellule in cellules):
        return None

    return sum(
        (cellule for cellule in cellules if cellule is not None), Decimal("0")
    )


@dataclass(frozen=True)
class TableauBilanFiscal:
    """Structure complète du Tableau_Bilan_Fiscal pour une Periode_Fiscale
    (Requirements 5 à 9). Les quatre familles de totaux
    (`total_retenues_*`, `total_cotisations_*`, `grand_total_*`) sont
    `Decimal | None` — `None` signifie « indicateur d'indisponibilité »
    (Requirement 7.3, 9.4), rendu par la couche d'affichage comme un
    texte explicite plutôt qu'un montant."""

    ligne_rrq: LigneBilan
    ligne_rqap: LigneBilan
    ligne_ae: LigneBilan
    ligne_impot: LigneBilan  # QC=impot_qc_retenu, CA=impot_federal_retenu
    total_retenues_qc: Decimal | None
    total_retenues_ca: Decimal | None

    ligne_rrq_employeur: LigneBilan
    ligne_rqap_employeur: LigneBilan
    ligne_ae_employeur: LigneBilan
    ligne_fss: LigneBilan
    ligne_cnesst: LigneBilan
    ligne_cnt: LigneBilan
    cnesst_en_attente_classification: bool  # Requirement 8.8 — OU logique
    total_cotisations_qc: Decimal | None
    total_cotisations_ca: Decimal | None

    grand_total_qc: Decimal | None
    grand_total_ca: Decimal | None
    grand_total_combine: Decimal | None  # cellule fusionnée QC+CA, Requirement 9.3


def construire_tableau_bilan_fiscal(
    paies_periode: tuple[PayrollResult, ...]
) -> TableauBilanFiscal:
    """Construit le `TableauBilanFiscal` complet (Requirements 5 à 9, 11.1).

    Chaque `LigneBilan` mono-juridictionnelle est obtenue par sommation
    directe du champ `MontantAvecTrace.montant` correspondant sur
    ``paies_periode``, arrondie à deux décimales (`_arrondir_montant`) —
    RRQ, RQAP, AE, RRQ employeur, RQAP employeur, AE employeur, FSS,
    CNESST, CNT alimentent chacun **une seule** colonne, l'autre étant
    explicitement `Decimal("0.00")` (Requirements 6.2-6.4, 8.2-8.7). La
    ligne Impôt alimente les deux colonnes à partir de deux champs
    distincts (`impot_qc_retenu`, `impot_federal_retenu`), sans jamais
    inclure `impot_qc_formule`/`impot_federal_formule` (Requirements 6.5,
    6.6). `cnesst_en_attente_classification` est le OU logique de ce
    drapeau sur l'ensemble de ``paies_periode`` (Requirement 8.8).
    ``paies_periode`` vide produit un tableau où chaque `LigneBilan` vaut
    `Decimal("0.00")` dans ses deux colonnes (Requirements 6.1, 8.1 — cas
    « aucune Paie_Agregee »). Les quatre totaux sont calculés via
    :func:`calculer_total` en cascade (`total_retenues` →
    `total_cotisations` → `grand_total` → `grand_total_combine`).
    """
    zero = Decimal("0.00")

    somme_rrq = _arrondir_montant(
        sum((p.retenues_employe.rrq.montant for p in paies_periode), Decimal("0"))
    )
    somme_rqap = _arrondir_montant(
        sum((p.retenues_employe.rqap.montant for p in paies_periode), Decimal("0"))
    )
    somme_ae = _arrondir_montant(
        sum((p.retenues_employe.ae.montant for p in paies_periode), Decimal("0"))
    )
    somme_impot_qc = _arrondir_montant(
        sum(
            (p.retenues_employe.impot_qc_retenu.montant for p in paies_periode),
            Decimal("0"),
        )
    )
    somme_impot_ca = _arrondir_montant(
        sum(
            (
                p.retenues_employe.impot_federal_retenu.montant
                for p in paies_periode
            ),
            Decimal("0"),
        )
    )

    somme_rrq_employeur = _arrondir_montant(
        sum(
            (p.cotisations_employeur.rrq_employeur.montant for p in paies_periode),
            Decimal("0"),
        )
    )
    somme_rqap_employeur = _arrondir_montant(
        sum(
            (p.cotisations_employeur.rqap_employeur.montant for p in paies_periode),
            Decimal("0"),
        )
    )
    somme_ae_employeur = _arrondir_montant(
        sum(
            (p.cotisations_employeur.ae_employeur.montant for p in paies_periode),
            Decimal("0"),
        )
    )
    somme_fss = _arrondir_montant(
        sum((p.cotisations_employeur.fss.montant for p in paies_periode), Decimal("0"))
    )
    somme_cnesst = _arrondir_montant(
        sum(
            (p.cotisations_employeur.cnesst.montant for p in paies_periode),
            Decimal("0"),
        )
    )
    somme_cnt = _arrondir_montant(
        sum((p.cotisations_employeur.cnt.montant for p in paies_periode), Decimal("0"))
    )

    cnesst_en_attente_classification = any(
        p.cotisations_employeur.cnesst_en_attente_classification
        for p in paies_periode
    )

    ligne_rrq = LigneBilan(libelle="RRQ", qc=somme_rrq, ca=zero)
    ligne_rqap = LigneBilan(libelle="RQAP", qc=somme_rqap, ca=zero)
    ligne_ae = LigneBilan(libelle="AE", qc=zero, ca=somme_ae)
    ligne_impot = LigneBilan(
        libelle="Impôt sur le revenu retenu", qc=somme_impot_qc, ca=somme_impot_ca
    )

    total_retenues_qc = calculer_total(
        ligne_rrq.qc, ligne_rqap.qc, ligne_ae.qc, ligne_impot.qc
    )
    total_retenues_ca = calculer_total(
        ligne_rrq.ca, ligne_rqap.ca, ligne_ae.ca, ligne_impot.ca
    )

    ligne_rrq_employeur = LigneBilan(
        libelle="RRQ employeur", qc=somme_rrq_employeur, ca=zero
    )
    ligne_rqap_employeur = LigneBilan(
        libelle="RQAP employeur", qc=somme_rqap_employeur, ca=zero
    )
    ligne_ae_employeur = LigneBilan(
        libelle="AE employeur", qc=zero, ca=somme_ae_employeur
    )
    ligne_fss = LigneBilan(libelle="FSS", qc=somme_fss, ca=zero)
    ligne_cnesst = LigneBilan(libelle="CNESST", qc=somme_cnesst, ca=zero)
    ligne_cnt = LigneBilan(libelle="CNT", qc=somme_cnt, ca=zero)

    total_cotisations_qc = calculer_total(
        ligne_rrq_employeur.qc,
        ligne_rqap_employeur.qc,
        ligne_ae_employeur.qc,
        ligne_fss.qc,
        ligne_cnesst.qc,
        ligne_cnt.qc,
    )
    total_cotisations_ca = calculer_total(
        ligne_rrq_employeur.ca,
        ligne_rqap_employeur.ca,
        ligne_ae_employeur.ca,
        ligne_fss.ca,
        ligne_cnesst.ca,
        ligne_cnt.ca,
    )

    grand_total_qc = calculer_total(total_retenues_qc, total_cotisations_qc)
    grand_total_ca = calculer_total(total_retenues_ca, total_cotisations_ca)
    grand_total_combine = calculer_total(grand_total_qc, grand_total_ca)

    return TableauBilanFiscal(
        ligne_rrq=ligne_rrq,
        ligne_rqap=ligne_rqap,
        ligne_ae=ligne_ae,
        ligne_impot=ligne_impot,
        total_retenues_qc=total_retenues_qc,
        total_retenues_ca=total_retenues_ca,
        ligne_rrq_employeur=ligne_rrq_employeur,
        ligne_rqap_employeur=ligne_rqap_employeur,
        ligne_ae_employeur=ligne_ae_employeur,
        ligne_fss=ligne_fss,
        ligne_cnesst=ligne_cnesst,
        ligne_cnt=ligne_cnt,
        cnesst_en_attente_classification=cnesst_en_attente_classification,
        total_cotisations_qc=total_cotisations_qc,
        total_cotisations_ca=total_cotisations_ca,
        grand_total_qc=grand_total_qc,
        grand_total_ca=grand_total_ca,
        grand_total_combine=grand_total_combine,
    )


# ---------------------------------------------------------------------------
# Lecture SQL directe — seul point d'E/S (Requirements 10.3, 11.1, 11.2,
# 11.3 ; tâche 9.5)
# ---------------------------------------------------------------------------


def lire_paies_emises(
    chemin_bd: str | Path = chemin_bd_production(),
) -> tuple[PayrollResult, ...]:
    """Toutes les paies de statut `EMISE` du Registre_Maitre (Requirements
    10.3, 11.1, 11.2, 11.3).

    Interroge `paies` en SQL direct (`SELECT payload_json FROM paies
    WHERE statut = ?`, paramètre `StatutDePaie.EMISE.value`), sans jamais
    appeler de fonction privée — ni même publique autre que
    `chemin_bd_production` — de `payroll_engine.register` (décision n° 5,
    Requirement 11.1). Sur une base neuve sans table `paies`,
    `sqlite3.OperationalError` (message contenant `"no such table"`) est
    interceptée explicitement et traduite en tuple vide — toute autre
    `OperationalError` est repropagée sans interception (même discipline
    que `dernieres_paies.derniere_annee_paie`/`lire_resumes_paies`).

    Chaque `payload_json` est décodé via
    `PayrollResult.model_validate_json` — aucune interception locale de
    `pydantic.ValidationError`/`json.JSONDecodeError` : ces deux
    exceptions (sous-classes de `ValueError`) se propagent intactes
    jusqu'à l'appelant (Requirement 11.3 — interrompt l'agrégation de la
    Periode_Fiscale concernée plutôt que de silencieusement ignorer la
    paie corrompue ou produire un résultat partiel).

    Règle 01 : chaque montant reste un `Decimal` depuis la désérialisation
    Pydantic jusqu'au retour de cette fonction — aucune conversion
    `float` à aucune étape (Requirement 11.2).

    **Requête SQL — pourquoi pas de filtrage additionnel par date en
    SQL** : `date_paiement` est un champ imbriqué dans `payload_json`
    (au sein de `pay_period`), pas une colonne SQL indexable — la requête
    ne peut filtrer que sur `statut`. Le filtrage par Periode_Fiscale
    (Mois_De_Rattachement) est fait en mémoire, après désérialisation
    complète, par :func:`filtrer_paies_par_periode` — le volume de paies
    `EMISE` du Camp LilySO (quelques employés saisonniers, ≤27
    paies/an/employé) rend ce coût négligeable.
    """
    try:
        connexion = sqlite3.connect(str(chemin_bd))
        try:
            lignes = connexion.execute(
                "SELECT payload_json FROM paies WHERE statut = ?",
                (StatutDePaie.EMISE.value,),
            ).fetchall()
        finally:
            connexion.close()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return ()
        raise

    return tuple(
        PayrollResult.model_validate_json(payload_json)
        for (payload_json,) in lignes
    )
