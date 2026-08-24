"""Registre maître SQLite — schéma, chemin de production, transactions.

Spec de référence : ``net-cumuls-registre`` — tâches 8.1 et 8.2.
Design de référence : ``design.md`` §Components §3.0 (« Signatures
exactes »), §3.1 (`chemin_bd_production`), §3.2 (« Connexion et
transaction atomique — pattern partagé »), §3.3 (`inserer_paie`), §3.6
(`lire_cumuls_ytd`) ; §Data Models (DDL des tables ``paies`` et
``cumuls_ytd``).

Ce module porte, à terme, le registre maître **append-only** des
paies du Camp LilySO (`inserer_paie`, `lire_paie`,
`lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie` — tâches
8.2 à 8.4). La tâche 8.1 a posé l'**infrastructure** partagée par ces
cinq fonctions :

- le schéma SQL des deux tables (`paies`, `cumuls_ytd`) ;
- :func:`chemin_bd_production` — résolution multiplateforme du chemin
  de production, pure, sans aucune E/S (Req 15.1) ;
- :func:`_creer_schema_si_absent` — création idempotente du schéma
  (`CREATE TABLE IF NOT EXISTS`), appelée en tête de chaque fonction
  publique ;
- :func:`_connexion` — gestionnaire de contexte garantissant
  l'atomicité (`BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`) de toute
  écriture (Req 11.5, 13.6).

La tâche 8.2 ajoute :

- :func:`inserer_paie` — insertion append-only, quel que soit le
  statut, avec contrôle explicite d'unicité de `id_paie` et mise à
  jour conditionnelle de `cumuls_ytd` (Req 11). Bug corrigé après
  livraison (demande explicite de l'utilisateur) : refuse en outre
  toute insertion `EMISE` si une AUTRE ligne `EMISE` existe déjà pour
  la même Paie_Logique `(employe_id, annee_fiscale, numero_periode)` —
  empêche deux paies `EMISE` actives simultanément pour la même
  période (root cause : le flux « Nouvelle paie » de l'interface
  pouvait ré-émettre une période déjà émise sans jamais passer par
  `remplacer_paie`, qui seul invalide correctement l'ancienne ligne) ;
- :func:`lire_cumuls_ytd` (et son helper interne
  :func:`_lire_cumuls_ytd_tx`) — lecture du cumul YTD courant, retourne
  `CumulsYTD.zero(...)` si absent (Req 10.4, 12.4) ;
- :func:`_upsert_cumuls_ytd` — écriture idempotente des onze colonnes
  monétaires de `cumuls_ytd`, chaque `Decimal` converti en `str(...)`
  (Req 10.3) ;
- :class:`_ContributionResultat` — adaptateur interne exposant les
  onze catégories `CumulsYTD` à partir d'un `PayrollResult` complet
  (voir sa docstring pour la justification détaillée).

La tâche 8.3 ajoute :

- :func:`lire_paie` — relecture d'une paie unique par `id_paie`, via
  `PayrollResult.model_validate_json(payload_json)` ; `KeyError`
  explicite si l'identifiant est absent (Req 12.1, 12.2, 12.5) ;
- :func:`lire_historique_paie` — relecture de toutes les versions
  d'une Paie_Logique `(employe_id, annee_fiscale, numero_periode)`,
  triées par `version ASC` ; retourne un tuple vide si aucune version
  n'existe, jamais d'exception (Req 12.3).

La tâche 8.4 ajoute :

- :func:`remplacer_paie` — annulation-remplacement atomique d'une
  paie `EMISE` : marque l'ancienne ligne `REMPLACE_PAR`, insère la
  nouvelle ligne, puis recalcule `cumuls_ytd` (retrait de l'ancienne
  contribution, ajout de la nouvelle si `EMISE`) dans une seule
  transaction (Req 13) ;
- :func:`_inserer_ligne_paie_tx` — helper interne factorisé hors de
  `inserer_paie`, réutilisé par `remplacer_paie` pour l'insertion
  brute de la ligne `paies` ;
- :func:`_soustraire_contribution` — symétrique de `CumulsYTD.avec_paie`,
  retire la contribution d'un `PayrollResult` d'un `CumulsYTD`.

Règles appliquées (Req 9 à 15) :

- Règle 01 (``Decimal`` obligatoire) — aucune colonne SQL n'utilise le
  type flottant natif de SQLite : tout montant monétaire est stocké en
  ``TEXT`` (`payload_json` pour `paies`, onze colonnes `TEXT` pour
  `cumuls_ytd`), jamais en virgule flottante native SQLite (Req 9.2,
  10.2).
- Règle 04 (données sensibles) — :func:`chemin_bd_production` résout
  un chemin **hors** du dépôt versionné (`%APPDATA%\\CampLilySO\\payroll.db`
  ou équivalent multiplateforme), jamais une valeur codée en dur vers
  la racine du dépôt.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from models.cumuls import CumulsYTD
from models.enums import StatutDePaie
from models.payroll_input import PayrollInput
from models.payroll_result import PayrollResult
from payroll_engine.stockage_distant import telecharger_si_absent, televerser

#: Les onze catégories monétaires `_CATEGORIES_MONETAIRES` de
#: `models.cumuls.CumulsYTD`, dans le même ordre — reprises ici pour
#: piloter `_upsert_cumuls_ytd`/`_lire_cumuls_ytd_tx` sans importer un
#: symbole privé d'un autre module (design §Components §3.3, §3.6).
_CATEGORIES_CUMULS: tuple[str, ...] = (
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

__all__ = [
    "annuler_paie",
    "chemin_bd_production",
    "inserer_paie",
    "lire_cumuls_ytd",
    "lire_historique_paie",
    "lire_paie",
    "remplacer_paie",
    "supprimer_paie_brouillon",
]

#: Statuts autorisés pour ``nouveau_resultat`` dans `remplacer_paie` (Req
#: 13.3, design §Components §3.7). Tout autre statut (`ANNULEE`,
#: `REMPLACE_PAR`) est refusé — une paie de remplacement doit être soit
#: immédiatement `EMISE`, soit conservée en `BROUILLON` en attendant
#: confirmation, jamais insérée directement dans un état terminal
#: incohérent avec un remplacement.
_STATUTS_NOUVEAU_RESULTAT_AUTORISES: frozenset[StatutDePaie] = frozenset(
    {StatutDePaie.EMISE, StatutDePaie.BROUILLON}
)


# ---------------------------------------------------------------------------
# _ContributionResultat — pont interne entre un `PayrollResult` complet et
# `CumulsYTD.avec_paie` (design §Components §3.3 : « `resultat` EST un
# PayrollResult complet : `CumulsYTD.avec_paie` lit ses onze catégories
# nativement »).
# ---------------------------------------------------------------------------
#
# Vérification contre `models/payroll_result.py` : `PayrollResult` n'expose
# **pas** les onze catégories `_CATEGORIES_MONETAIRES` comme attributs
# plats de premier niveau — seul `net` l'est. Les dix autres
# (`brut`, `vacances`, `rrq_employe`, `rrq_employeur`, `rqap_employe`,
# `rqap_employeur`, `ae_employe`, `ae_employeur`, `impot_qc_retenu`,
# `impot_federal_retenu`) ne vivent que sous `resultat.gains` /
# `resultat.retenues_employe` / `resultat.cotisations_employeur`. Un appel
# direct `cumul.avec_paie(resultat)` retomberait donc, via
# `getattr(resultat, categorie, valeur_actuelle)`, sur la valeur *actuelle*
# du cumul pour ces dix catégories (aucune agrégation, bug silencieux).
# `_ContributionResultat` reproduit exactement le mapping du design
# §Components §2 (table du Requirement 6 AC2, identique à
# `net_pay._ContributionPaie`) pour satisfaire le duck typing de
# `CumulsYTD.avec_paie` avec un `PayrollResult` complet.
@dataclass(frozen=True)
class _ContributionResultat:
    """Adaptateur interne — expose les onze catégories `CumulsYTD` à
    partir d'un `PayrollResult` complet (mapping design §Components §2/§3.3).

    Interne à `register.py` — non exportée, non exposée hors module.
    """

    employe_id: str
    annee_fiscale: int
    brut: Decimal
    vacances: Decimal
    rrq_employe: Decimal
    rrq_employeur: Decimal
    rqap_employe: Decimal
    rqap_employeur: Decimal
    ae_employe: Decimal
    ae_employeur: Decimal
    impot_qc_retenu: Decimal
    impot_federal_retenu: Decimal
    net: Decimal

    @classmethod
    def depuis(cls, resultat: PayrollResult) -> "_ContributionResultat":
        """Construit la contribution à partir d'un `PayrollResult` complet.

        Mapping exact (design §Components §2, table du Requirement 6
        AC2) : chaque catégorie provient du sous-modèle qui la porte
        réellement sur `PayrollResult` (`gains`, `retenues_employe`,
        `cotisations_employeur`) — jamais recalculée.
        """
        return cls(
            employe_id=resultat.employe_id,
            annee_fiscale=resultat.annee_fiscale,
            brut=resultat.gains.brut_total,
            vacances=resultat.gains.vacances,
            rrq_employe=resultat.retenues_employe.rrq.montant,
            rrq_employeur=resultat.cotisations_employeur.rrq_employeur.montant,
            rqap_employe=resultat.retenues_employe.rqap.montant,
            rqap_employeur=resultat.cotisations_employeur.rqap_employeur.montant,
            ae_employe=resultat.retenues_employe.ae.montant,
            ae_employeur=resultat.cotisations_employeur.ae_employeur.montant,
            impot_qc_retenu=resultat.retenues_employe.impot_qc_retenu.montant,
            impot_federal_retenu=resultat.retenues_employe.impot_federal_retenu.montant,
            net=resultat.net,
        )

# ---------------------------------------------------------------------------
# Schéma SQL — table `paies` (Req 9, design §Data Models)
# ---------------------------------------------------------------------------
#
# Aucune colonne monétaire (`net`, `cout_employeur`, montants de `gains`/
# `retenues_employe`/`cotisations_employeur`) n'utilise le type
# flottant natif de SQLite — la source de vérité exclusive de tout
# montant individuel d'une paie est `payload_json` (Req 9.2, règle
# 01). Les colonnes hors `payload_json` sont des colonnes
# d'indexation, jamais de calcul.
#
# `payload_input_json` (bugfix `heures-periode-et-persistance-brouillon`,
# design §Bug Condition — Bug 2, Req 2.3) — colonne **nullable**, sans
# `NOT NULL`, ajoutée en fin de table par migration additive
# (`ALTER TABLE ... ADD COLUMN`, voir
# :func:`_ajouter_colonne_payload_input_json_si_absente` ci-dessous).
# Elle porte le `PayrollInput` sérialisé
# (`PayrollInput.model_dump_json()`) ayant produit la paie, afin qu'un
# brouillon relu (`lire_paie`) puisse restituer intégralement les
# valeurs saisies par l'utilisateur (heures, notamment) plutôt que de
# les recalculer approximativement depuis `PayrollResult` seul.
#
# Cette colonne est ajoutée par migration **additive**, jamais par
# recréation de table : les lignes déjà présentes avant le déploiement
# du bugfix reçoivent `NULL` pour `payload_input_json` et ne sont
# **jamais** rétro-remplies (règle 06 — immutabilité historique ;
# design §Preservation Requirements, Req 3.4). SQLite ne supporte pas
# `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` : l'idempotence est donc
# assurée explicitement par :func:`_ajouter_colonne_payload_input_json_si_absente`,
# qui vérifie d'abord via `PRAGMA table_info(paies)` que la colonne
# n'existe pas déjà avant d'exécuter l'`ALTER TABLE`, afin qu'un appel
# répété (chaque fonction publique du registre appelle
# `_creer_schema_si_absent`) ne lève jamais `sqlite3.OperationalError:
# duplicate column name`.

_DDL_PAIES = """
CREATE TABLE IF NOT EXISTS paies (
    id_paie             TEXT    PRIMARY KEY,
    employe_id          TEXT    NOT NULL,
    annee_fiscale       INTEGER NOT NULL,
    numero_periode      INTEGER NOT NULL,
    saison              TEXT    NOT NULL,
    version             INTEGER NOT NULL,
    statut              TEXT    NOT NULL,
    remplace_par_id     TEXT,
    date_creation       TEXT    NOT NULL,
    date_emission       TEXT,
    payload_json        TEXT    NOT NULL,
    payload_input_json  TEXT
);
"""

#: Index permettant à `lire_historique_paie` (Req 9.4, Req 12.3) de
#: retrouver et trier efficacement toutes les versions d'une Paie_Logique
#: `(employe_id, annee_fiscale, numero_periode)` sans scan complet de
#: table.
_DDL_INDEX_PAIES_LOGIQUE = """
CREATE INDEX IF NOT EXISTS idx_paies_logique
    ON paies (employe_id, annee_fiscale, numero_periode, version);
"""

# ---------------------------------------------------------------------------
# Schéma SQL — table `cumuls_ytd` (Req 10, design §Data Models)
# ---------------------------------------------------------------------------
#
# Clé primaire composite `(employe_id, annee_civile)` — SQLite en fait
# automatiquement un index unique, ce qui rend `INSERT ... ON
# CONFLICT(employe_id, annee_civile) DO UPDATE SET ...` directement
# utilisable par `_upsert_cumuls_ytd` (tâche 8.2) sans requête de
# contrôle préalable. Onze colonnes `TEXT`, jamais en virgule
# flottante native SQLite (Req 10.2, règle 01) — même ordre que
# `models.cumuls._CATEGORIES_MONETAIRES`.

_DDL_CUMULS_YTD = """
CREATE TABLE IF NOT EXISTS cumuls_ytd (
    employe_id            TEXT NOT NULL,
    annee_civile          INTEGER NOT NULL,
    brut                  TEXT NOT NULL,
    vacances              TEXT NOT NULL,
    rrq_employe           TEXT NOT NULL,
    rrq_employeur         TEXT NOT NULL,
    rqap_employe          TEXT NOT NULL,
    rqap_employeur        TEXT NOT NULL,
    ae_employe            TEXT NOT NULL,
    ae_employeur          TEXT NOT NULL,
    impot_qc_retenu       TEXT NOT NULL,
    impot_federal_retenu  TEXT NOT NULL,
    net                   TEXT NOT NULL,
    PRIMARY KEY (employe_id, annee_civile)
);
"""


# ---------------------------------------------------------------------------
# chemin_bd_production (Req 15.1, design §Components §3.1, décision n° 5)
# ---------------------------------------------------------------------------


def chemin_bd_production() -> Path:
    """Chemin de production `%APPDATA%\\CampLilySO\\payroll.db` (Req 15.1).

    Résolution multiplateforme sans nouvelle dépendance (design
    §Components §3.1, décision n° 5) :

    1. Si ``APPDATA`` est présent dans l'environnement (Windows
       nominal — cible de production du Camp LilySO, règle 04), la
       base résolue est ``Path(os.environ["APPDATA"])``.
    2. Sinon, si ``XDG_DATA_HOME`` est présent (repli Linux/CI
       explicite), la base résolue est
       ``Path(os.environ["XDG_DATA_HOME"])``.
    3. Sinon, dernier repli portable : ``Path.home() / ".local" /
       "share"``.

    Le chemin retourné est toujours ``base / "CampLilySO" /
    "payroll.db"``.

    Fonction **pure** : uniquement des lectures de variables
    d'environnement, aucune écriture disque (aucun répertoire ni
    fichier n'est créé ici). C'est cette pureté qui permet de
    l'utiliser comme valeur par défaut de paramètre (`chemin_bd`) sans
    effet de bord à la définition des cinq fonctions publiques du
    registre (tâches 8.2 à 8.4) — la création effective du répertoire
    parent est différée jusqu'à la première connexion
    (:func:`_connexion`).
    """
    if "APPDATA" in os.environ:
        base = Path(os.environ["APPDATA"])
    elif "XDG_DATA_HOME" in os.environ:
        base = Path(os.environ["XDG_DATA_HOME"])
    else:
        base = Path.home() / ".local" / "share"

    return base / "CampLilySO" / "payroll.db"


# ---------------------------------------------------------------------------
# _creer_schema_si_absent (design §Components §3.2)
# ---------------------------------------------------------------------------


def _creer_schema_si_absent(connexion: sqlite3.Connection) -> None:
    """Crée le schéma (`paies`, `cumuls_ytd`, index) si absent.

    Idempotente — chaque instruction DDL est `CREATE TABLE/INDEX IF NOT
    EXISTS` (design §Components §3.2). Appelée en tête de chaque
    fonction publique du registre (tâches 8.2 à 8.4), car `chemin_bd`
    peut pointer vers un fichier neuf ou une base `:memory:`
    fraîchement ouverte à chaque appel de test.
    """
    connexion.execute(_DDL_PAIES)
    connexion.execute(_DDL_INDEX_PAIES_LOGIQUE)
    connexion.execute(_DDL_CUMULS_YTD)
    _ajouter_colonne_payload_input_json_si_absente(connexion)


# ---------------------------------------------------------------------------
# _ajouter_colonne_payload_input_json_si_absente — migration additive
# (bugfix `heures-periode-et-persistance-brouillon`, design §Bug Condition
# — Bug 2, §Preservation Requirements, Req 2.3, Req 3.4)
# ---------------------------------------------------------------------------


def _ajouter_colonne_payload_input_json_si_absente(
    connexion: sqlite3.Connection,
) -> None:
    """Ajoute `payload_input_json` à `paies` si elle est absente (Req 2.3).

    Migration **additive** : les bases créées avant ce bugfix portent
    une table `paies` sans la colonne `payload_input_json` (DDL
    d'origine, Req 9). Recréer la table (`DROP`/`CREATE`) romprait
    l'immutabilité historique (règle 06) en risquant de perdre ou de
    réécrire des lignes déjà présentes ; cette fonction utilise donc
    exclusivement `ALTER TABLE paies ADD COLUMN payload_input_json
    TEXT`, qui préserve toutes les lignes existantes et leur donne la
    valeur `NULL` pour la nouvelle colonne — **jamais** de
    rétro-remplissage (design §Preservation Requirements, Req 3.4).

    SQLite ne supporte pas la clause `ADD COLUMN IF NOT EXISTS` :
    l'idempotence est donc assurée explicitement ici, via `PRAGMA
    table_info(paies)`, qui liste les colonnes actuelles de la table
    (`ligne[1]` porte le nom de chaque colonne). Si
    `payload_input_json` est déjà présente, aucune instruction n'est
    exécutée — un appel répété (chaque fonction publique du registre
    appelle `_creer_schema_si_absent`, donc cette fonction, à chaque
    connexion) ne lève donc jamais `sqlite3.OperationalError:
    duplicate column name`.

    Appelée exclusivement depuis :func:`_creer_schema_si_absent`, à
    l'intérieur d'une transaction déjà ouverte par :func:`_connexion` —
    ne gère elle-même aucune transaction.
    """
    colonnes = {
        ligne[1]
        for ligne in connexion.execute("PRAGMA table_info(paies)").fetchall()
    }
    if "payload_input_json" not in colonnes:
        connexion.execute(
            "ALTER TABLE paies ADD COLUMN payload_input_json TEXT"
        )


# ---------------------------------------------------------------------------
# _connexion — pattern de transaction atomique partagé (Req 11.5, 13.6,
# design §Components §3.2)
# ---------------------------------------------------------------------------


@contextmanager
def _connexion(chemin_bd: str | Path) -> Iterator[sqlite3.Connection]:
    """Ouvre une connexion SQLite avec transaction explicite (Req 11.5, 13.6).

    `isolation_level=None` désactive l'autocommit implicite de
    `sqlite3` ; la transaction est ouverte explicitement par `BEGIN
    IMMEDIATE` (évite une lecture sale entre le `SELECT` de contrôle et
    l'`UPDATE`/`INSERT` qui suit, cas `remplacer_paie`) et fermée par
    `COMMIT` en sortie normale ou `ROLLBACK` si une exception traverse
    le bloc `with`.

    Le répertoire parent de `chemin_bd` est créé si nécessaire
    (`mkdir(parents=True, exist_ok=True)`) — sauf pour la valeur
    spéciale `":memory:"`, qui n'a aucun répertoire parent à créer
    (base SQLite éphémère en mémoire).
    """
    chemin: str | Path = chemin_bd if chemin_bd == ":memory:" else Path(chemin_bd)
    if isinstance(chemin, Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        # Synchronisation best-effort depuis un stockage distant persistant
        # (hébergement éphémère, ex. Streamlit Community Cloud) — no-op si
        # aucun bucket n'est configuré ou si le fichier existe déjà
        # localement (voir `app/logique_metier/stockage_distant.py`).
        telecharger_si_absent(chemin)

    connexion = sqlite3.connect(str(chemin), isolation_level=None)
    connexion.execute("PRAGMA foreign_keys = ON")
    transaction_reussie = False
    try:
        connexion.execute("BEGIN IMMEDIATE")
        yield connexion
        connexion.execute("COMMIT")
        transaction_reussie = True
    except BaseException:
        connexion.execute("ROLLBACK")
        raise
    finally:
        connexion.close()
        # Téléversement best-effort — uniquement après un `COMMIT` réussi
        # (jamais après un `ROLLBACK`, pour ne pas propager un état
        # transitoire/invalide vers le stockage distant). No-op si aucun
        # bucket n'est configuré. Sur `":memory:"`, `isinstance(chemin,
        # Path)` est déjà `False` : rien à synchroniser pour une base
        # éphémère en mémoire.
        if transaction_reussie and isinstance(chemin, Path):
            televerser(chemin)


# ---------------------------------------------------------------------------
# _upsert_cumuls_ytd — écriture idempotente des onze colonnes (Req 10.3,
# design §Components §3.3)
# ---------------------------------------------------------------------------


def _upsert_cumuls_ytd(connexion: sqlite3.Connection, cumul: CumulsYTD) -> None:
    """Écrit ``cumul`` dans `cumuls_ytd` par upsert (Req 10.3, 11.5).

    Une seule instruction `INSERT ... ON CONFLICT(employe_id,
    annee_civile) DO UPDATE SET ...` (clause SQLite native, rendue
    possible par la clé primaire composite `(employe_id, annee_civile)`
    du DDL — design §Data Models « cumuls_ytd »). Chaque valeur
    `Decimal` des onze catégories monétaires est convertie en
    `str(valeur)` avant écriture — **jamais** `float(valeur)` (règle 01,
    Req 10.3) : SQLite ne reçoit que des chaînes ``TEXT``.

    Appelée exclusivement à l'intérieur d'une transaction déjà ouverte
    par :func:`_connexion` (``inserer_paie``, futures ``remplacer_paie``
    — tâche 8.4) ; ne gère elle-même aucune transaction.
    """
    valeurs_texte: tuple[str, ...] = tuple(
        str(getattr(cumul, categorie)) for categorie in _CATEGORIES_CUMULS
    )
    connexion.execute(
        "INSERT INTO cumuls_ytd ("
        "employe_id, annee_civile, brut, vacances, rrq_employe, "
        "rrq_employeur, rqap_employe, rqap_employeur, ae_employe, "
        "ae_employeur, impot_qc_retenu, impot_federal_retenu, net"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(employe_id, annee_civile) DO UPDATE SET "
        "brut = excluded.brut, "
        "vacances = excluded.vacances, "
        "rrq_employe = excluded.rrq_employe, "
        "rrq_employeur = excluded.rrq_employeur, "
        "rqap_employe = excluded.rqap_employe, "
        "rqap_employeur = excluded.rqap_employeur, "
        "ae_employe = excluded.ae_employe, "
        "ae_employeur = excluded.ae_employeur, "
        "impot_qc_retenu = excluded.impot_qc_retenu, "
        "impot_federal_retenu = excluded.impot_federal_retenu, "
        "net = excluded.net",
        (cumul.employe_id, cumul.annee_civile, *valeurs_texte),
    )


# ---------------------------------------------------------------------------
# _lire_cumuls_ytd_tx — lecture des cumuls dans une transaction déjà
# ouverte (Req 10.4, 12.4, design §Components §3.6)
# ---------------------------------------------------------------------------


def _lire_cumuls_ytd_tx(
    connexion: sqlite3.Connection, employe_id: str, annee_civile: int
) -> CumulsYTD:
    """Lit le cumul YTD courant de ``(employe_id, annee_civile)`` (Req 10.4).

    Retourne `CumulsYTD.zero(employe_id, annee_civile)` si aucune ligne
    n'existe encore pour ce couple — jamais d'exception (Req 10.4).
    Chaque colonne lue est une chaîne `TEXT` (ex. ``"1516.32"``), passée
    directement à `CumulsYTD.model_validate(...)`, qui la convertit en
    `Decimal` via `reject_float` — aucun `float()` n'intervient à aucune
    étape (règle 01, Req 12.5).

    Fonction interne, appelée à l'intérieur d'une transaction déjà
    ouverte par :func:`_connexion` — ne gère elle-même aucune
    transaction. Réutilisée par `inserer_paie` (cette tâche) et, à terme,
    par `lire_cumuls_ytd` (fonction publique, cette tâche) ainsi que par
    `remplacer_paie` (tâche 8.4).
    """
    ligne = connexion.execute(
        "SELECT brut, vacances, rrq_employe, rrq_employeur, rqap_employe, "
        "rqap_employeur, ae_employe, ae_employeur, impot_qc_retenu, "
        "impot_federal_retenu, net FROM cumuls_ytd "
        "WHERE employe_id = ? AND annee_civile = ?",
        (employe_id, annee_civile),
    ).fetchone()

    if ligne is None:
        return CumulsYTD.zero(employe_id, annee_civile)

    donnees: dict[str, str | int] = {
        "employe_id": employe_id,
        "annee_civile": annee_civile,
    }
    for categorie, valeur in zip(_CATEGORIES_CUMULS, ligne, strict=True):
        donnees[categorie] = valeur
    return CumulsYTD.model_validate(donnees)


# ---------------------------------------------------------------------------
# lire_cumuls_ytd — fonction publique de lecture (Req 12.4, 10.4, design
# §Components §3.6)
# ---------------------------------------------------------------------------


def lire_cumuls_ytd(
    employe_id: str,
    annee_civile: int,
    chemin_bd: str | Path = chemin_bd_production(),
) -> CumulsYTD:
    """Lit le cumul YTD courant de ``(employe_id, annee_civile)`` (Req 12.4).

    Ouvre sa propre transaction via :func:`_connexion` (lecture pure —
    `BEGIN IMMEDIATE`/`COMMIT` restent neutres sur une lecture, mais le
    pattern reste identique à toutes les fonctions publiques du
    registre pour la cohérence, design §Components §3.2), crée le
    schéma si absent, puis délègue à :func:`_lire_cumuls_ytd_tx`.

    Retourne `CumulsYTD.zero(employe_id, annee_civile)` si aucune ligne
    n'existe encore — jamais d'exception (Req 10.4).
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)
        return _lire_cumuls_ytd_tx(connexion, employe_id, annee_civile)


# ---------------------------------------------------------------------------
# _inserer_ligne_paie_tx — insertion brute de la ligne `paies` (extrait de
# `inserer_paie`, réutilisé par `remplacer_paie`, design §Components §3.7
# étape 3b)
# ---------------------------------------------------------------------------


def _inserer_ligne_paie_tx(
    connexion: sqlite3.Connection,
    resultat: PayrollResult,
    saison: str,
    payload_input_json: str | None,
) -> None:
    """Insère la ligne `paies` de ``resultat`` (étape 2 de `inserer_paie`).

    Exécute **uniquement** l'`INSERT INTO paies (...)` — ni contrôle
    d'unicité de `id_paie`, ni mise à jour de `cumuls_ytd` (ces deux
    responsabilités restent portées par les appelants : `inserer_paie`
    pour le contrôle d'unicité (Req 11.6) et la mise à jour conditionnelle
    des cumuls (Req 11.3, 11.4) ; `remplacer_paie` pour le recalcul des
    cumuls après retrait de l'ancienne contribution (Req 13.4c)).

    ``payload_input_json`` (bugfix `heures-periode-et-persistance-brouillon`,
    design §Fix Implementation point 3, Req 2.3) porte le
    `PayrollInput.model_dump_json()` ayant produit ``resultat``, ou
    `None` si l'appelant n'en dispose pas — écrit tel quel dans la
    colonne nullable `payload_input_json` (règle 06, aucune
    rétro-inférence).

    Fonction interne, appelée à l'intérieur d'une transaction déjà ouverte
    par :func:`_connexion` — ne gère elle-même aucune transaction.
    """
    connexion.execute(
        "INSERT INTO paies (id_paie, employe_id, annee_fiscale, "
        "numero_periode, saison, version, statut, remplace_par_id, "
        "date_creation, date_emission, payload_json, "
        "payload_input_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            resultat.id_paie,
            resultat.employe_id,
            resultat.annee_fiscale,
            resultat.pay_period.numero_periode,
            saison,
            resultat.version,
            resultat.statut.value,
            resultat.remplace_par_id,
            resultat.date_creation.isoformat(),
            resultat.date_emission.isoformat() if resultat.date_emission else None,
            resultat.model_dump_json(),
            payload_input_json,
        ),
    )


# ---------------------------------------------------------------------------
# inserer_paie — insertion append-only + mise à jour conditionnelle des
# cumuls (Req 11, design §Components §3.3)
# ---------------------------------------------------------------------------


def inserer_paie(
    resultat: PayrollResult,
    saison: str,
    payroll_input: PayrollInput | None = None,
    chemin_bd: str | Path = chemin_bd_production(),
) -> None:
    """Insère ``resultat`` dans le registre maître, append-only (Req 11).

    Dans une seule transaction atomique (:func:`_connexion`, Req 11.5) :

    1. **Contrôle explicite d'unicité** de `resultat.id_paie` — si une
       ligne porte déjà cet identifiant, lève `ValueError` avec un
       message actionnable citant l'identifiant concerné, **avant toute
       écriture** (Req 11.6). Le contrôle porte strictement sur
       `id_paie`, jamais sur l'égalité complète de l'objet — une seconde
       tentative avec un `PayrollResult` distinct mais portant le même
       `id_paie` est refusée de la même façon.
    2. **Insertion append-only** de la ligne dans `paies`, quel que soit
       `resultat.statut` (Req 11.2) — `payload_json` porte
       `resultat.model_dump_json()` sans nouveau schéma de sérialisation
       (décision design n° 4, Req 12.5). Depuis le bugfix
       `heures-periode-et-persistance-brouillon` (Req 2.3, design
       §Correctness Properties Property 2) : si ``payroll_input`` est
       fourni, sa sérialisation (`payroll_input.model_dump_json()`) est
       persistée dans la colonne nullable `payload_input_json` — même
       mécanisme de sérialisation Decimal → chaîne déjà porté par
       `PayrollInput.model_dump_json()`/`model_validate_json()` (règle
       01, aucun nouveau schéma de sérialisation introduit). Si
       ``payroll_input`` est `None` (défaut — préservation, design
       §Correctness Properties Property 4), `payload_input_json` reste
       `NULL` pour cette ligne, comportement identique à avant ce
       bugfix.
    3. **Mise à jour conditionnelle de `cumuls_ytd`** — uniquement si
       `resultat.statut == StatutDePaie.EMISE` (Req 11.3) : lecture du
       cumul courant via `_lire_cumuls_ytd_tx` (retourne
       `CumulsYTD.zero(...)` si absent, Req 10.4), puis agrégation via
       `CumulsYTD.avec_paie(_ContributionResultat.depuis(resultat))`.
       `PayrollResult` n'expose ses onze catégories monétaires que sous
       ses sous-modèles (`gains`, `retenues_employe`,
       `cotisations_employeur`) — seul `net` est un attribut plat ; un
       appel direct `cumul.avec_paie(resultat)` ne agrégerait donc, par
       duck typing (`getattr(resultat, categorie, valeur_actuelle)`),
       que `net`. `_ContributionResultat` (interne à ce module, mapping
       identique à `net_pay._ContributionPaie`) reproduit le mapping
       exact du design §Components §2/§3.3 pour les dix autres
       catégories. Pour tout autre statut, `cumuls_ytd` reste
       **inchangée** (Req 11.4).

    Sortie du bloc `with` : `COMMIT` si aucune exception, `ROLLBACK`
    complet sinon (Req 11.5) — les deux effets (insertion + mise à jour
    des cumuls) sont donc visibles ensemble ou pas du tout.
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)

        # 1. Refus si id_paie déjà présent (Req 11.6) — contrôle
        #    explicite pour un message actionnable, plutôt que de
        #    laisser fuiter `sqlite3.IntegrityError` (contrainte
        #    `PRIMARY KEY` du DDL `paies`).
        ligne_existante = connexion.execute(
            "SELECT 1 FROM paies WHERE id_paie = ?", (resultat.id_paie,)
        ).fetchone()
        if ligne_existante is not None:
            raise ValueError(
                f"id_paie '{resultat.id_paie}' déjà présent — append-only, "
                "aucune ré-insertion (Req 11.6)."
            )

        # 1bis. Bug corrigé (demande explicite de l'utilisateur) — refus
        #       si une AUTRE ligne EMISE existe déjà pour la même
        #       Paie_Logique `(employe_id, annee_fiscale, numero_periode)`
        #       et que `resultat` est lui-même EMISE. Root cause du bug :
        #       `inserer_paie` ne contrôlait auparavant que l'unicité de
        #       `id_paie` (toujours neuf via `prochaine_version`), jamais
        #       l'unicité de la paie EMISE par période — le flux
        #       « Nouvelle paie » (par opposition à « Corriger cette
        #       paie », qui passe par `remplacer_paie` et marque bien
        #       l'ancienne ligne `REMPLACE_PAR`) pouvait ainsi émettre une
        #       seconde fois la même période sans jamais invalider la
        #       première — deux lignes `EMISE` actives simultanément pour
        #       la même Paie_Logique, faussant `lire_paies_emises`/le
        #       Bilan_Fiscal (double comptage). Garde-fou posé ici,
        #       au niveau le plus bas du registre — protège tout
        #       appelant présent ou futur, pas seulement l'interface
        #       Streamlit (défense en profondeur).
        if resultat.statut == StatutDePaie.EMISE:
            autre_emise = connexion.execute(
                "SELECT id_paie FROM paies WHERE employe_id = ? AND "
                "annee_fiscale = ? AND numero_periode = ? AND statut = ?",
                (
                    resultat.employe_id,
                    resultat.annee_fiscale,
                    resultat.pay_period.numero_periode,
                    StatutDePaie.EMISE.value,
                ),
            ).fetchone()
            if autre_emise is not None:
                raise ValueError(
                    f"Une paie EMISE ('{autre_emise[0]}') existe déjà pour "
                    f"employe_id={resultat.employe_id!r}, "
                    f"annee_fiscale={resultat.annee_fiscale}, "
                    f"numero_periode={resultat.pay_period.numero_periode} — "
                    "utilisez remplacer_paie(...) pour corriger une paie "
                    "déjà émise plutôt que d'en insérer une nouvelle."
                )

        # 1ter. Bug corrigé (unicite-paie-active-par-periode) — invalider
        #       toute ligne BROUILLON active de la même Paie_Logique avant
        #       l'insertion, dans la même transaction atomique. Toutes les
        #       lignes BROUILLON actives trouvées sont mutées (pas
        #       seulement la première) : une base ayant déjà accumulé
        #       plusieurs BROUILLON actifs avant ce correctif (conséquence
        #       du bug) doit être auto-réparée dès la prochaine insertion
        #       pour cette Paie_Logique, plutôt que de laisser des lignes
        #       orphelines actives. S'exécute uniquement si le garde-fou
        #       ci-dessus (1bis) n'a pas levé d'exception.
        lignes_brouillon_actives = connexion.execute(
            "SELECT id_paie, payload_json FROM paies WHERE employe_id = ? "
            "AND annee_fiscale = ? AND numero_periode = ? AND statut = ?",
            (
                resultat.employe_id,
                resultat.annee_fiscale,
                resultat.pay_period.numero_periode,
                StatutDePaie.BROUILLON.value,
            ),
        ).fetchall()
        for id_paie_ancien, payload_ancien in lignes_brouillon_actives:
            ancien_resultat = PayrollResult.model_validate_json(payload_ancien)
            payload_ancien_maj = ancien_resultat.model_copy(
                update={
                    "statut": StatutDePaie.REMPLACE_PAR,
                    "remplace_par_id": resultat.id_paie,
                    # Écart documenté vs. modèle de mutation de
                    # `remplacer_paie` (étape 3a) : `date_emission` doit
                    # être renseignée dès que `statut ∈ {EMISE, ANNULEE,
                    # REMPLACE_PAR}` (invariant `PayrollResult`, Req
                    # 6.7). `remplacer_paie` ne mute jamais que des
                    # lignes déjà EMISE (donc déjà pourvues d'une
                    # `date_emission`) — mais une ligne BROUILLON n'en a
                    # jamais eu. `resultat.date_creation` (celle de la
                    # NOUVELLE ligne qui la remplace, déjà disponible,
                    # déterministe) sert de valeur : aucun appel à
                    # `datetime.now()` (pureté, même discipline que le
                    # reste du moteur de paie), et cette date est
                    # cohérente avec l'instant de la transaction qui
                    # invalide ce BROUILLON.
                    "date_emission": resultat.date_creation,
                }
            ).model_dump_json()
            connexion.execute(
                "UPDATE paies SET statut = ?, remplace_par_id = ?, "
                "payload_json = ? WHERE id_paie = ?",
                (
                    StatutDePaie.REMPLACE_PAR.value,
                    resultat.id_paie,
                    payload_ancien_maj,
                    id_paie_ancien,
                ),
            )
        # SEULE mutation autorisée sur une ligne existante (Req 9.3) —
        # jamais `payload_input_json` (colonne non touchée ci-dessus).

        # 2. Insertion append-only (Req 11.2) — quel que soit le statut.
        payload_input_json = (
            payroll_input.model_dump_json() if payroll_input is not None else None
        )
        _inserer_ligne_paie_tx(connexion, resultat, saison, payload_input_json)

        # 3. Mise à jour cumuls_ytd SEULEMENT si EMISE (Req 11.3, 11.4).
        if resultat.statut == StatutDePaie.EMISE:
            cumul_actuel = _lire_cumuls_ytd_tx(
                connexion, resultat.employe_id, resultat.annee_fiscale
            )
            contribution = _ContributionResultat.depuis(resultat)
            nouveau_cumul = cumul_actuel.avec_paie(contribution)
            _upsert_cumuls_ytd(connexion, nouveau_cumul)
        # Sinon : `cumuls_ytd` inchangée (Req 11.4).
    # Sortie du `with` -> COMMIT si aucune exception, ROLLBACK sinon (Req 11.5).


# ---------------------------------------------------------------------------
# lire_paie — relecture d'une paie unique par id_paie (Req 12.1, 12.2, 12.5,
# design §Components §3.4)
# ---------------------------------------------------------------------------


def lire_paie(
    id_paie: str,
    chemin_bd: str | Path = chemin_bd_production(),
) -> tuple[PayrollResult, PayrollInput | None]:
    """Relit la paie identifiée par ``id_paie`` (Req 12.1).

    Ouvre sa propre transaction via :func:`_connexion` (lecture pure,
    même pattern que toutes les fonctions publiques du registre —
    design §Components §3.2), crée le schéma si absent, puis
    sélectionne `payload_json` et `payload_input_json` pour la ligne
    `paies` dont `id_paie` correspond exactement.

    Lève `KeyError` avec un message citant `id_paie` si aucune ligne
    ne correspond (Req 12.2) — jamais de valeur de repli silencieuse.

    La désérialisation passe exclusivement par
    `PayrollResult.model_validate_json(...)`, qui reconstruit chaque
    montant en `Decimal` via Pydantic — aucun `float()` n'intervient à
    aucune étape (règle 01, Req 12.5). Round-trip avec `inserer_paie`
    (`resultat.model_dump_json()` — design §Components §3.3, décision
    n° 4) : aucun nouveau schéma de sérialisation.

    Depuis le bugfix `heures-periode-et-persistance-brouillon` (Req
    2.4, 3.4 ; design §Fix Implementation point 6, §Correctness
    Properties Property 2/Property 4) : retourne désormais un COUPLE
    `(resultat, payroll_input)` — **rupture de signature assumée**,
    tous les appelants existants doivent déstructurer le retour. Le
    second élément est `None` si `payload_input_json` est `NULL` en
    base (`Paie_Pre_Correction`, colonne non renseignée par un
    `inserer_paie`/`remplacer_paie` antérieur à ce bugfix, ou appelant
    n'ayant pas fourni `payroll_input`) — **jamais** d'exception levée
    pour ce cas (préservation, Req 3.4). Si `payload_input_json` est
    renseigné (`Paie_Post_Correction`), `payroll_input` est reconstruit
    via `PayrollInput.model_validate_json(...)` — même discipline
    anti-`float` que pour `PayrollResult` (règle 01, Req 12.5).
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)
        ligne = connexion.execute(
            "SELECT payload_json, payload_input_json FROM paies "
            "WHERE id_paie = ?",
            (id_paie,),
        ).fetchone()
        if ligne is None:
            raise KeyError(f"Aucune paie trouvée pour id_paie={id_paie!r}.")
        payload_json, payload_input_json = ligne
        resultat = PayrollResult.model_validate_json(payload_json)
        payroll_input = (
            PayrollInput.model_validate_json(payload_input_json)
            if payload_input_json is not None
            else None
        )
        return (resultat, payroll_input)


# ---------------------------------------------------------------------------
# lire_historique_paie — relecture de toutes les versions d'une
# Paie_Logique (Req 12.3, design §Components §3.5)
# ---------------------------------------------------------------------------


def lire_historique_paie(
    employe_id: str,
    annee_fiscale: int,
    numero_periode: int,
    chemin_bd: str | Path = chemin_bd_production(),
) -> tuple[tuple[PayrollResult, PayrollInput | None], ...]:
    """Relit toutes les versions de la Paie_Logique identifiée (Req 12.3).

    Une Paie_Logique est identifiée par le triplet `(employe_id,
    annee_fiscale, numero_periode)` — chaque version successive
    (append-only, `remplacer_paie`) porte le même triplet mais un
    `version` croissant. Ouvre sa propre transaction via
    :func:`_connexion`, crée le schéma si absent, puis sélectionne
    `payload_json` et `payload_input_json` pour toutes les lignes
    correspondantes, triées par `version ASC` (ordre chronologique
    d'insertion — exploite `idx_paies_logique`, design §Data Models
    « paies »).

    Retourne un tuple **vide** si aucune version n'existe pour ce
    triplet — jamais d'exception (comportement symétrique de
    `lire_cumuls_ytd`, Req 10.4).

    Chaque élément du tuple est désérialisé via
    `PayrollResult.model_validate_json(...)`, jamais via `float()`
    (règle 01, Req 12.5).

    Depuis le bugfix `heures-periode-et-persistance-brouillon` (Req
    2.4, 3.4 ; design §Fix Implementation point 7, §Correctness
    Properties Property 2/Property 4) : extension symétrique à
    `lire_paie` — retourne désormais un tuple de COUPLES
    `(resultat, payroll_input)`, un couple par version. Pour chaque
    couple, `payroll_input` est `None` si `payload_input_json` est
    `NULL` pour cette version précise (`Paie_Pre_Correction`) — jamais
    d'exception (préservation, Req 3.4) ; sinon reconstruit via
    `PayrollInput.model_validate_json(...)` (règle 01).
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)
        lignes = connexion.execute(
            "SELECT payload_json, payload_input_json FROM paies "
            "WHERE employe_id = ? AND annee_fiscale = ? AND numero_periode = ? "
            "ORDER BY version ASC",
            (employe_id, annee_fiscale, numero_periode),
        ).fetchall()
        resultats: list[tuple[PayrollResult, PayrollInput | None]] = []
        for payload_json, payload_input_json in lignes:
            resultat = PayrollResult.model_validate_json(payload_json)
            payroll_input = (
                PayrollInput.model_validate_json(payload_input_json)
                if payload_input_json is not None
                else None
            )
            resultats.append((resultat, payroll_input))
        return tuple(resultats)


# ---------------------------------------------------------------------------
# _soustraire_contribution — symétrique de `CumulsYTD.avec_paie` (design
# §Components §3.7 étape 3c)
# ---------------------------------------------------------------------------


def _soustraire_contribution(cumul: CumulsYTD, resultat: PayrollResult) -> CumulsYTD:
    """Retire la contribution de ``resultat`` de ``cumul`` (Req 13.4c, 13.5).

    Retourne une **nouvelle** instance de :class:`CumulsYTD` via
    ``model_copy(update=...)`` — ``cumul`` reste inchangé (même contrat
    d'immuabilité que `CumulsYTD.avec_paie`). Pour chacune des onze
    catégories monétaires, la nouvelle valeur est
    ``getattr(cumul, cat) - getattr(_ContributionResultat.depuis(resultat), cat)``
    — symétrique exacte de l'addition portée par `CumulsYTD.avec_paie`.

    Comme pour `inserer_paie`, le passage par `_ContributionResultat`
    (plutôt qu'un accès direct aux attributs de ``resultat``) est
    nécessaire : `PayrollResult` n'expose ses onze catégories monétaires
    que sous ses sous-modèles (`gains`, `retenues_employe`,
    `cotisations_employeur`) — seul `net` est un attribut plat.

    Fonction interne, appelée exclusivement par `remplacer_paie` à
    l'intérieur d'une transaction déjà ouverte par :func:`_connexion` —
    ne gère elle-même aucune transaction.
    """
    contribution = _ContributionResultat.depuis(resultat)
    mises_a_jour: dict[str, Decimal] = {
        categorie: getattr(cumul, categorie) - getattr(contribution, categorie)
        for categorie in _CATEGORIES_CUMULS
    }
    return cumul.model_copy(update=mises_a_jour)


# ---------------------------------------------------------------------------
# remplacer_paie — annulation-remplacement atomique (Req 13, design
# §Components §3.7)
# ---------------------------------------------------------------------------


def remplacer_paie(
    ancien_id: str,
    nouveau_resultat: PayrollResult,
    saison: str,
    nouveau_payroll_input: PayrollInput | None = None,
    chemin_bd: str | Path = chemin_bd_production(),
) -> None:
    """Remplace la paie ``ancien_id`` par ``nouveau_resultat`` (Req 13).

    Depuis le bugfix `heures-periode-et-persistance-brouillon` (Req
    2.3, design §Correctness Properties Property 2) : si
    ``nouveau_payroll_input`` est fourni, sa sérialisation
    (`nouveau_payroll_input.model_dump_json()`) est persistée dans la
    colonne `payload_input_json` de la **nouvelle** ligne insérée à
    l'étape 3b uniquement. L'ancienne ligne (``ancien_id``) n'est
    **jamais** modifiée dans sa colonne `payload_input_json` — seuls
    `statut`/`remplace_par_id`/`payload_json` sont mutés à l'étape 3a
    (immutabilité déjà portée par le registre, règle 06). Si
    ``nouveau_payroll_input`` est `None` (défaut — préservation, design
    §Correctness Properties Property 4), `payload_input_json` reste
    `NULL` pour la nouvelle ligne, comportement identique à avant ce
    bugfix.

    Dans une seule transaction atomique (:func:`_connexion`, Req 13.6) :

    1. **Lecture + contrôle de l'ancienne ligne** (Req 13.2) — si
       `ancien_id` est absent de `paies`, lève `KeyError` citant
       l'identifiant recherché. Si la ligne existe mais que son
       `statut` n'est pas `EMISE`, lève `ValueError` citant le statut
       courant — seule une paie `EMISE` peut être remplacée.
    2. **Contrôle du statut du nouveau résultat** (Req 13.3) — si
       `nouveau_resultat.statut` n'est pas dans
       `{EMISE, BROUILLON}`, lève `ValueError` citant le statut refusé.
       Ce contrôle a lieu **avant toute écriture**, comme celui de
       l'étape 1 — aucune mutation de `paies`/`cumuls_ytd` en cas de
       refus (Req 13.2, 13.3).
    3. **Trois mutations dans la même transaction** :

       a. `UPDATE paies SET statut = 'remplace_par', remplace_par_id =
          ?, payload_json = ?` sur la ligne `ancien_id` — via
          `model_copy` de l'ancien `PayrollResult` désérialisé, avec
          uniquement `statut` et `remplace_par_id` modifiés (Req
          13.4a, 9.3, 13.7). C'est la **seule** mutation autorisée sur
          une ligne déjà insérée dans tout le registre.
       b. Insertion de `nouveau_resultat` via
          :func:`_inserer_ligne_paie_tx` — même mécanisme que
          `inserer_paie` (Req 13.4b). Aucune mise à jour de
          `cumuls_ytd` à cette étape : le recalcul complet a lieu à
          l'étape 3c.
       c. Recalcul de `cumuls_ytd` (Req 13.4c, 13.5) : lecture du
          cumul courant via `_lire_cumuls_ytd_tx`, retrait de la
          contribution de l'ancien résultat via
          :func:`_soustraire_contribution`, puis — si
          `nouveau_resultat.statut == EMISE` — ajout de la
          contribution du nouveau résultat via `CumulsYTD.avec_paie` ;
          si `nouveau_resultat.statut == BROUILLON`, le cumul reste au
          seul retrait de l'ancienne contribution (Req 13.5), aucun
          ajout n'étant applicable à un `BROUILLON`.

    Sortie du bloc `with` : `COMMIT` si les trois étapes ont réussi,
    `ROLLBACK` intégral si une exception traverse l'une d'elles (Req
    13.6) — les trois mutations sont donc visibles ensemble ou pas du
    tout.
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)

        # 1. Lecture + contrôle de l'ancienne ligne (Req 13.2).
        ancienne_ligne = connexion.execute(
            "SELECT statut, payload_json FROM paies WHERE id_paie = ?",
            (ancien_id,),
        ).fetchone()
        if ancienne_ligne is None:
            raise KeyError(f"Aucune paie trouvée pour ancien_id={ancien_id!r}.")
        ancien_statut, ancien_payload = ancienne_ligne
        if ancien_statut != StatutDePaie.EMISE.value:
            raise ValueError(
                f"Impossible de remplacer la paie '{ancien_id}' : statut "
                f"actuel '{ancien_statut}' \u2260 EMISE (Req 13.2)."
            )
        ancien_resultat = PayrollResult.model_validate_json(ancien_payload)

        # 2. Contrôle du statut du nouveau résultat (Req 13.3).
        if nouveau_resultat.statut not in _STATUTS_NOUVEAU_RESULTAT_AUTORISES:
            raise ValueError(
                f"statut '{nouveau_resultat.statut.value}' non autorisé pour "
                "un remplacement (Req 13.3) \u2014 attendu EMISE ou BROUILLON."
            )

        # --- À partir d'ici, trois mutations dans UNE seule transaction ---

        # 3a. Marquer l'ancienne ligne REMPLACE_PAR (Req 13.4a, Req 9.3).
        payload_ancien_maj = ancien_resultat.model_copy(
            update={
                "statut": StatutDePaie.REMPLACE_PAR,
                "remplace_par_id": nouveau_resultat.id_paie,
            }
        ).model_dump_json()
        connexion.execute(
            "UPDATE paies SET statut = ?, remplace_par_id = ?, payload_json = ? "
            "WHERE id_paie = ?",
            (
                StatutDePaie.REMPLACE_PAR.value,
                nouveau_resultat.id_paie,
                payload_ancien_maj,
                ancien_id,
            ),
        )
        # SEULE mutation autorisée sur une ligne existante (Req 9.3, 13.7).

        # 3b. Insertion de la nouvelle ligne (même mécanisme que
        #     inserer_paie, Req 13.4b) — pas de mise à jour cumuls à
        #     cette étape (recalculée à 3c). `payload_input_json` ne
        #     concerne QUE cette nouvelle ligne — l'UPDATE de l'étape
        #     3a ci-dessus ne mentionne pas cette colonne, elle reste
        #     donc inchangée pour l'ancienne ligne (règle 06).
        payload_input_json = (
            nouveau_payroll_input.model_dump_json()
            if nouveau_payroll_input is not None
            else None
        )
        _inserer_ligne_paie_tx(
            connexion, nouveau_resultat, saison, payload_input_json
        )

        # 3c. Recalcul cumuls_ytd : retrait ancien + ajout nouveau (Req
        #     13.4c, 13.5).
        cumul_actuel = _lire_cumuls_ytd_tx(
            connexion, ancien_resultat.employe_id, ancien_resultat.annee_fiscale
        )
        cumul_sans_ancien = _soustraire_contribution(cumul_actuel, ancien_resultat)

        if nouveau_resultat.statut == StatutDePaie.EMISE:
            cumul_final = cumul_sans_ancien.avec_paie(
                _ContributionResultat.depuis(nouveau_resultat)
            )
        else:  # BROUILLON (Req 13.5)
            cumul_final = cumul_sans_ancien

        _upsert_cumuls_ytd(connexion, cumul_final)
    # Sortie du `with` -> COMMIT si les 3 étapes ont réussi, ROLLBACK
    # intégral sinon (Req 13.6).


def supprimer_paie_brouillon(
    id_paie: str,
    chemin_bd: str | Path = chemin_bd_production(),
) -> None:
    """Supprime physiquement la ligne ``paies`` identifiée par ``id_paie``.

    Réservée aux lignes de statut ``BROUILLON`` — jamais utilisée pour une
    ligne ``EMISE``/``ANNULEE``/``REMPLACE_PAR``. Un ``BROUILLON`` ne
    contribue jamais à ``cumuls_ytd`` (Req 3.8, cf. Req 11.4 de la spec
    ``net-cumuls-registre``) : aucune mise à jour de ``cumuls_ytd`` n'est
    donc nécessaire ici.

    Dans une seule transaction atomique (:func:`_connexion`) :

    1. **Lecture + contrôle** — si ``id_paie`` est absent de ``paies``,
       lève ``KeyError`` citant l'identifiant recherché (Req 3.7). Si la
       ligne existe mais que son ``statut`` n'est pas ``BROUILLON``, lève
       ``ValueError`` citant le statut courant — seule une paie
       ``BROUILLON`` peut être supprimée physiquement (Req 3.6).
    2. **Suppression** — ``DELETE FROM paies WHERE id_paie = ?`` (Req
       3.4).

    Sortie du bloc ``with`` : ``COMMIT`` si aucune exception, ``ROLLBACK``
    sinon — les deux étapes sont donc visibles ensemble ou pas du tout.

    **Écart documenté avec la règle 06 (immutabilité historique)** : cette
    fonction est la seule du registre à retirer une ligne plutôt que de la
    muter ou d'en ajouter une nouvelle (append-only). Cet écart est
    délibéré et limité aux lignes ``BROUILLON`` uniquement — un brouillon
    n'est, par définition, jamais une « paie émise » au sens de la règle
    06 (aucune valeur auditable n'a jamais été communiquée à l'employé) ;
    l'immutabilité historique protège les paies ``EMISE``/``ANNULEE``/
    ``REMPLACE_PAR``, jamais les brouillons.
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)

        ligne = connexion.execute(
            "SELECT statut FROM paies WHERE id_paie = ?", (id_paie,)
        ).fetchone()
        if ligne is None:
            raise KeyError(f"Aucune paie trouvée pour id_paie={id_paie!r}.")
        (statut_actuel,) = ligne
        if statut_actuel != StatutDePaie.BROUILLON.value:
            raise ValueError(
                f"Impossible de supprimer physiquement la paie '{id_paie}' : "
                f"statut actuel '{statut_actuel}' \u2260 BROUILLON — utilisez "
                "annuler_paie(...) pour une paie déjà EMISE."
            )

        connexion.execute("DELETE FROM paies WHERE id_paie = ?", (id_paie,))
    # Sortie du `with` -> COMMIT si aucune exception, ROLLBACK sinon.


# ---------------------------------------------------------------------------
# annuler_paie — annulation d'une paie ÉMISE, jamais de DELETE (Req 4,
# design §Components §4)
# ---------------------------------------------------------------------------


def annuler_paie(
    id_paie: str,
    chemin_bd: str | Path = chemin_bd_production(),
) -> None:
    """Annule la paie ÉMISE identifiée par ``id_paie`` — jamais de ``DELETE``.

    Réservée aux lignes de statut ``EMISE`` — jamais utilisée pour une
    ligne ``BROUILLON`` (voir :func:`supprimer_paie_brouillon`) ni pour
    une ligne déjà ``ANNULEE``/``REMPLACE_PAR``. Contrairement à
    :func:`remplacer_paie`, aucune nouvelle ligne n'est insérée —
    l'ancienne ligne est uniquement mutée, jamais remplacée par une
    version successeure (``remplace_par_id`` reste ``None``).

    Dans une seule transaction atomique (:func:`_connexion`) :

    1. **Lecture + contrôle** — si ``id_paie`` est absent de ``paies``,
       lève ``KeyError`` citant l'identifiant recherché (Req 4.9). Si la
       ligne existe mais que son ``statut`` n'est pas ``EMISE``, lève
       ``ValueError`` citant le statut courant — seule une paie
       ``EMISE`` peut être annulée (Req 4.8).
    2. **Mutation du statut** (Req 4.4) — ``UPDATE paies SET statut =
       'annulee', payload_json = ? WHERE id_paie = ?``, via
       ``model_copy(update={"statut": StatutDePaie.ANNULEE})`` de
       l'ancien ``PayrollResult`` désérialisé — même patron exact que
       l'étape 3a de :func:`remplacer_paie` (``date_emission`` reste
       inchangée : déjà renseignée puisque la ligne était ``EMISE``).
    3. **Décrément de ``cumuls_ytd``** (Req 4.6) — lecture du cumul
       courant via :func:`_lire_cumuls_ytd_tx`, puis retrait de la
       contribution de cette paie via :func:`_soustraire_contribution`
       (même mécanisme que l'étape 3c de :func:`remplacer_paie`), puis
       :func:`_upsert_cumuls_ytd`.

    Sortie du bloc ``with`` : ``COMMIT`` si les trois étapes réussissent,
    ``ROLLBACK`` intégral sinon (Req 4.7) — le statut et les cumuls sont
    donc visibles ensemble ou jamais du tout.

    **Limitation documentée** (symétrique à une limitation déjà existante
    de :func:`remplacer_paie`) : si des paies de périodes postérieures
    pour le même employé et la même année civile ont déjà été émises
    après ``id_paie``, leurs propres ``cumuls_fin`` (snapshots figés dans
    leur ``payload_json`` respectif) ne sont **jamais** recalculés par
    cette fonction — seul le total courant de la table ``cumuls_ytd`` est
    ajusté. Décision actée explicitement avec l'utilisateur : aucune
    condition bloquante liée à l'existence de paies postérieures n'est
    ajoutée par cette spec.

    **Aucun `DELETE`** : à la différence de :func:`supprimer_paie_brouillon`,
    cette fonction respecte l'immutabilité historique (règle 06) — une
    paie ``EMISE`` a déjà été communiquée à l'employé et ne doit jamais
    disparaître physiquement du registre.
    """
    with _connexion(chemin_bd) as connexion:
        _creer_schema_si_absent(connexion)

        ligne = connexion.execute(
            "SELECT statut, payload_json FROM paies WHERE id_paie = ?",
            (id_paie,),
        ).fetchone()
        if ligne is None:
            raise KeyError(f"Aucune paie trouvée pour id_paie={id_paie!r}.")
        statut_actuel, payload_actuel = ligne
        if statut_actuel != StatutDePaie.EMISE.value:
            raise ValueError(
                f"Impossible d'annuler la paie '{id_paie}' : statut actuel "
                f"'{statut_actuel}' \u2260 EMISE."
            )
        ancien_resultat = PayrollResult.model_validate_json(payload_actuel)

        payload_maj = ancien_resultat.model_copy(
            update={"statut": StatutDePaie.ANNULEE}
        ).model_dump_json()
        connexion.execute(
            "UPDATE paies SET statut = ?, payload_json = ? WHERE id_paie = ?",
            (StatutDePaie.ANNULEE.value, payload_maj, id_paie),
        )

        cumul_actuel = _lire_cumuls_ytd_tx(
            connexion, ancien_resultat.employe_id, ancien_resultat.annee_fiscale
        )
        cumul_final = _soustraire_contribution(cumul_actuel, ancien_resultat)
        _upsert_cumuls_ytd(connexion, cumul_final)
    # Sortie du `with` -> COMMIT si les 3 étapes réussissent, ROLLBACK sinon
    # (Req 4.7).
