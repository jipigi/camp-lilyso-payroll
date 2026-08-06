"""Disjonction stricte des erreurs du domaine — `app/logique_metier/erreurs.py`.

Spec de référence : ``interface-streamlit`` — tâche 19.1 (Req 16, règle 03).
Design de référence : ``design.md`` §Components §8 (`erreurs.py` —
`ErreurDomaineAffichable`, `executer_avec_capture`) ; §Error Handling
« Disjonction stricte (Req 16) — mécanisme central ».

Ce module est le **seul** point de capture d'exception de toute la
surface `app/`. Il centralise le patron « appeler une fonction, capturer
distinctement `UnsupportedPayrollCase`, `MissingParameterError`,
`ValueError`, `KeyError`, retourner soit le résultat soit une
`ErreurDomaineAffichable` » (Req 16.1, 16.2). AUCUN `except
Exception`/`except BaseException` générique n'est présent ici ni
ailleurs sous `app/` (Req 16.3, règle 03 — un cas hors matrice lève
toujours une exception explicite plutôt que d'être masqué
silencieusement) : toute exception hors des quatre types listés traverse
`executer_avec_capture` sans être interceptée, remontant jusqu'à
Streamlit qui l'affichera complète plutôt que d'échouer silencieusement.

Ce fichier est explicitement exclu du balayage du test de garde
`TestAucunExceptGenerique` (tâche 10.2, ``tests/app/test_guards.py``)
puisqu'il est le seul autorisé à contenir des ``except`` — mais aucun de
ses gestionnaires n'utilise ``Exception``/``BaseException`` génériques ;
seuls les quatre types nommés explicitement ci-dessous sont capturés.

Aucun import ``streamlit`` (Req 1.1, 1.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from models.exceptions import MissingParameterError, UnsupportedPayrollCase

T = TypeVar("T")


@dataclass(frozen=True)
class ErreurDomaineAffichable:
    """Erreur capturée, prête à afficher sans altération (Req 16.2).

    ``type_exception`` distingue les quatre catégories interceptées
    (`"UnsupportedPayrollCase"`, `"MissingParameterError"`,
    `"ValueError"`, `"KeyError"`) ; ``message`` porte le message
    d'origine **intact**, jamais reformulé ni tronqué.
    """

    type_exception: str
    message: str


def executer_avec_capture(
    fonction: Callable[[], T]
) -> T | ErreurDomaineAffichable:
    """Exécute ``fonction`` en capturant distinctement les 4 types (Req 16.1, 16.2).

    Capture, dans cet ordre, `UnsupportedPayrollCase`, `MissingParameterError`,
    `ValueError`, `KeyError` — chacune retournée comme
    `ErreurDomaineAffichable` avec son message d'origine intact. AUCUN
    `except Exception`/`except BaseException` générique n'est présent :
    toute autre exception traverse cette fonction sans interception
    (Req 16.3), remontant jusqu'à Streamlit qui l'affichera complète
    (type et message) plutôt que d'échouer silencieusement.

    `UnsupportedPayrollCase` et `MissingParameterError` sont capturées
    **avant** `ValueError`/`KeyError` bien qu'aucune des deux n'en hérite
    (elles dérivent de `PayrollDomainError(Exception)`, disjointes de
    `ValueError` — voir `models/exceptions.py`) : l'ordre n'a pas d'effet
    sur la sélection de la branche (types disjoints), mais reflète l'ordre
    de priorité métier du Requirement 16 AC2.
    """
    try:
        return fonction()
    except UnsupportedPayrollCase as exc:
        return ErreurDomaineAffichable("UnsupportedPayrollCase", str(exc))
    except MissingParameterError as exc:
        return ErreurDomaineAffichable("MissingParameterError", str(exc))
    except ValueError as exc:
        return ErreurDomaineAffichable("ValueError", str(exc))
    except KeyError as exc:
        return ErreurDomaineAffichable("KeyError", str(exc))
