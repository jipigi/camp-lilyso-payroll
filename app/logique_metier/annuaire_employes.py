"""Annuaire_Employes JSON — cycle CRUD complet des Fiches_Employe.

Spec de référence : ``interface-streamlit`` — tâche 13.1.
Design de référence : ``design.md`` §Components §2 (`annuaire_employes.py`
— cycle CRUD) ; §Architecture « Résolution des chemins de production hors
dépôt ».

Ce module porte les **trois fonctions publiques** de l'Annuaire_Employes :

- :func:`lister_employes` — lecture complète, triée par `id` croissant
  (Req 2.1, 2.2) ;
- :func:`enregistrer_employe` — remplacement/ajout par `id`, réécriture
  complète et atomique de l'annuaire (Req 2.3, 2.6) ;
- :func:`lire_employe` — lecture unique par `id`, `KeyError` explicite si
  absent (Req 2.4, 2.5).

ainsi que la fonction pure :func:`chemin_annuaire_employes_production`
qui résout le chemin de production hors dépôt.

Règle 04 (données sensibles) : :func:`chemin_annuaire_employes_production`
**ne duplique pas** la résolution `%APPDATA%` déjà portée par
`payroll_engine.register.chemin_bd_production` (décision de conception
n° 2) — elle en dérive simplement le répertoire parent, en y ajoutant le
nom de fichier `"employees.json"`. Le chemin de production réel réside
donc systématiquement hors dépôt, au même endroit que `payroll.db`. Les
tests (tâche 3) injectent exclusivement des chemins `tmp_path`, jamais ce
chemin de production.

Règle 03 (périmètre Camp LilySO) : ce module ne valide **aucun** champ
d'`Employee` lui-même et ne lève jamais `UnsupportedPayrollCase` — un
`Employee` hors matrice aurait déjà été refusé **à la construction**
(`Employee(...)`, `models/employee.py`). `enregistrer_employe`/
`lire_employe` ne dupliquent jamais cette validation (Req 2.7).

Règle 01 : aucun montant monétaire n'est manipulé ici — les champs
`Decimal` d'`Employee` sont sérialisés/désérialisés exclusivement via
`Employee.model_dump_json()`/`Employee.model_validate_json(...)`, qui
gèrent déjà le rejet de `float` (voir `models/employee.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

from models.employee import Employee
from payroll_engine.register import chemin_bd_production

from app.logique_metier.stockage_json import ecrire_atomique, lire_texte_ou_defaut


def chemin_annuaire_employes_production() -> Path:
    """Chemin de production de l'Annuaire_Employes (Req 2, règle 04).

    Dérivé du répertoire parent de :func:`chemin_bd_production` — aucune
    nouvelle résolution `%APPDATA%`/`XDG_DATA_HOME` n'est introduite ici
    (décision de conception n° 2) : le fichier `"employees.json"` réside
    dans le même répertoire hors dépôt que `payroll.db`.

    Fonction pure — aucune E/S disque, aucune création de répertoire.
    """
    return chemin_bd_production().parent / "employees.json"


def lister_employes(
    chemin_annuaire: Path = chemin_annuaire_employes_production(),
) -> tuple[Employee, ...]:
    """Liste toutes les Fiches_Employe de l'annuaire, triées par `id` (Req 2.1, 2.2).

    Lecture tolérante à l'absence du fichier (`lire_texte_ou_defaut`,
    défaut `"[]"`) — jamais d'exception si l'annuaire n'a encore jamais
    été écrit. Chaque élément de la liste JSON est ré-encodé
    individuellement (`json.dumps`) puis validé via
    `Employee.model_validate_json`, qui applique l'intégralité des
    validateurs Pydantic d'`Employee` (règle 01, règle 03, règle 04) à la
    relecture.
    """
    brut = lire_texte_ou_defaut(chemin_annuaire, defaut="[]")
    elements = json.loads(brut)
    employes = tuple(
        Employee.model_validate_json(json.dumps(element)) for element in elements
    )
    return tuple(sorted(employes, key=lambda e: e.id))


def enregistrer_employe(
    employe: Employee,
    chemin_annuaire: Path = chemin_annuaire_employes_production(),
) -> None:
    """Enregistre ``employe`` dans l'annuaire, par remplacement/ajout (Req 2.3, 2.6).

    Reconstruit le dict `{id: Employee}` de l'état courant (via
    :func:`lister_employes`), remplace ou ajoute l'entrée pour
    `employe.id`, puis réécrit l'annuaire **complet** de façon atomique
    (:func:`ecrire_atomique`, Req 2.6). Aucune validation de périmètre
    n'est effectuée ici (Req 2.7) — `employe` est déjà une instance
    `Employee` valide.
    """
    existants = {e.id: e for e in lister_employes(chemin_annuaire)}
    existants[employe.id] = employe
    contenu = "[" + ",".join(e.model_dump_json() for e in existants.values()) + "]"
    ecrire_atomique(chemin_annuaire, contenu)


def lire_employe(
    id_employe: str,
    chemin_annuaire: Path = chemin_annuaire_employes_production(),
) -> Employee:
    """Lit la Fiche_Employe identifiée par ``id_employe`` (Req 2.4, 2.5).

    Parcourt :func:`lister_employes`. Lève `KeyError` avec un message
    citant explicitement ``id_employe`` si aucune fiche ne correspond —
    jamais de valeur de repli silencieuse.
    """
    for employe in lister_employes(chemin_annuaire):
        if employe.id == id_employe:
            return employe
    raise KeyError(f"Aucune Fiche_Employe trouvée pour id={id_employe!r}.")
