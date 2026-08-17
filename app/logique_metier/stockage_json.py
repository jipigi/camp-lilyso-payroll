"""Primitives d'E/S JSON génériques — écriture atomique, lecture avec défaut.

Spec de référence : ``interface-streamlit`` — tâche 12.1.
Design de référence : ``design.md`` §Components §1 (`ecrire_atomique`,
`lire_texte_ou_defaut`).

Ce module porte les **deux seules primitives d'E/S** partagées par
`annuaire_employes.py` et `annuaire_coordonnees.py` (tâches 13 et 14) :

- :func:`ecrire_atomique` — patron write-to-temp + rename, garantissant
  qu'aucune écriture partielle du fichier cible n'est jamais visible,
  même en cas d'exception avant la substitution finale (Req 2.6, 20.5) ;
- :func:`lire_texte_ou_defaut` — lecture tolérante à l'absence du
  fichier (cas nominal d'un annuaire jamais encore écrit), sans jamais
  lever d'exception (Req 2.2, 20.7).

Règle 04 (données sensibles) : ces primitives sont génériques et ne
connaissent aucune donnée métier. Les chemins de production réels
(`chemin_annuaire_employes_production()`,
`chemin_annuaire_coordonnees_production()`, définis dans les modules
appelants) résident hors dépôt ; ce module ne fait aucune hypothèse sur
le contenu ou la localisation des fichiers qu'il manipule.

Règle 01 : ces primitives manipulent du texte brut, jamais de montant
monétaire — la règle ``Decimal`` ne s'y applique pas.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from payroll_engine.stockage_distant import telecharger_si_absent, televerser


def ecrire_atomique(chemin: Path, contenu: str) -> None:
    """Écrit ``contenu`` dans ``chemin`` de façon atomique (Req 2.6, 20.5).

    Patron write-to-temp + rename : le contenu complet est d'abord écrit
    dans un fichier temporaire créé dans le **même répertoire** que
    ``chemin`` (garantit que ``os.replace`` reste sur le même système de
    fichiers — condition requise pour l'atomicité POSIX et Windows), puis
    ``os.replace(temp, chemin)`` remplace la cible en une seule opération
    atomique. Si une exception survient avant ``os.replace`` (erreur
    d'écriture disque, permission refusée), le fichier temporaire est
    supprimé et ``chemin`` reste inchangé — aucune écriture partielle
    n'est jamais visible. Le nettoyage est assuré par un bloc
    ``finally`` gardé par un indicateur booléen de succès (jamais par
    une clause ``except`` générique, conformément à la disjonction
    stricte du design §Error Handling) : le ``finally`` s'exécute dans
    tous les cas — succès ou exception — et ne supprime le fichier
    temporaire que si ``os.replace`` n'a jamais été atteint. Toute
    exception traverse naturellement le bloc, sans être interceptée ni
    masquée.

    Crée le répertoire parent (`mkdir(parents=True, exist_ok=True)`) si
    nécessaire — cohérent avec le comportement de `_connexion` de
    `register.py` (Req 15, spec `net-cumuls-registre`).

    Le fichier temporaire est ouvert avec ``newline=""`` en plus de
    ``encoding="utf-8"`` pour désactiver la traduction universelle des
    fins de ligne opérée par défaut par Python en mode texte (tout
    ``\r`` isolé, ``\r\n``, ou ``\n`` serait sinon normalisé à
    l'écriture). Cette désactivation préserve le contenu textuel exact,
    y compris les caractères de fin de ligne isolés, condition
    nécessaire pour un round-trip fidèle sur du contenu JSON qui
    pourrait légitimement contenir n'importe quel caractère Unicode
    (Property 3, design §Correctness Properties 3).
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    descripteur, chemin_temp_str = tempfile.mkstemp(
        dir=str(chemin.parent), suffix=".tmp"
    )
    chemin_temp = Path(chemin_temp_str)
    substitution_effectuee = False
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8", newline="") as f:
            f.write(contenu)
            f.flush()
            os.fsync(f.fileno())
        os.replace(chemin_temp, chemin)
        substitution_effectuee = True
    finally:
        if not substitution_effectuee:
            chemin_temp.unlink(missing_ok=True)

    # Synchronisation best-effort vers un stockage distant persistant
    # (hébergement éphémère, ex. Streamlit Community Cloud) — no-op si
    # aucun bucket n'est configuré (voir `stockage_distant.py`).
    televerser(chemin)


def lire_texte_ou_defaut(chemin: Path, defaut: str) -> str:
    """Lit ``chemin`` en UTF-8, ou retourne ``defaut`` si absent (Req 2.2, 20.7).

    Aucune exception n'est levée si ``chemin`` n'existe pas encore — c'est
    le cas nominal d'un annuaire jamais encore écrit.

    La lecture désactive elle aussi la traduction universelle des fins
    de ligne (``newline=""``), symétriquement à l'écriture dans
    :func:`ecrire_atomique`, afin de préserver le contenu textuel exact
    y compris les caractères de fin de ligne isolés (``\\r``, ``\\n``,
    ``\\r\\n``) — condition nécessaire pour un round-trip fidèle
    (Property 3, design §Correctness Properties 3). Le projet ciblant
    Python >= 3.11 (`pyproject.toml`), le paramètre ``newline`` de
    ``Path.read_text`` (disponible seulement depuis Python 3.13) n'est
    pas utilisé ; ``open()`` est utilisé directement pour rester
    compatible avec toutes les versions supportées.
    """
    telecharger_si_absent(chemin)
    if not chemin.exists():
        return defaut
    with open(chemin, "r", encoding="utf-8", newline="") as f:
        return f.read()
