"""Hiérarchie d'exceptions du domaine — moteur de paie Camp LilySO.

Ce module définit les exceptions métier levées par le moteur, strictement
disjointes de la hiérarchie ``pydantic.ValidationError`` (Req 8.7). Un
consommateur peut ainsi capturer séparément :

- un **refus métier** (``PayrollDomainError`` et sous-classes) ;
- une **erreur de forme** (``pydantic.ValidationError``).

Structure imposée par la spec ``moteur-paie-contrats`` §Data Models 2 :

    Exception
    └── PayrollDomainError                (base du domaine, non-Pydantic)
        ├── UnsupportedPayrollCase        (règle 03 — cas hors matrice)
        └── MissingParameterError         (règle 05 — paramètre "TO_FILL")

Contraintes clés (Req 8) :

- Req 8.1 & 8.4 — ``UnsupportedPayrollCase`` et ``MissingParameterError``
  dérivent toutes deux de ``PayrollDomainError``, elle-même dérivée de la
  classe standard ``Exception``.
- Req 8.2 — les deux exceptions restent strictement disjointes : aucune
  n'hérite de l'autre.
- Req 8.3 & 8.6 — le message porté par toute exception du domaine DOIT être
  une chaîne non vide et actionnable. Cette contrainte est appliquée dès le
  constructeur (fail-fast) pour empêcher qu'un ``raise
  UnsupportedPayrollCase("")`` ne masque un cas refusé sans motif exploitable
  par l'auditeur.
- Req 8.7 — aucune classe de ce module n'hérite de
  ``pydantic.ValidationError``.

Conformément à la règle 06 (TDD), les tests sont écrits avant ce module :
voir ``tests/models/test_exceptions.py``.
"""

from __future__ import annotations


class PayrollDomainError(Exception):
    """Base des exceptions métier du moteur de paie Camp LilySO.

    Toute exception levée à la frontière du moteur pour un motif métier
    (cas hors matrice, paramètre manquant) DOIT dériver de cette classe.
    Elle est distincte de ``pydantic.ValidationError`` pour permettre à un
    consommateur (application Streamlit, tests) de capturer séparément un
    refus métier d'une erreur de forme (Req 8.7).

    Le constructeur exige un message non vide et non uniquement composé
    d'espaces (Req 8.3 & 8.6). Un message actionnable est indispensable
    pour la piste d'audit : sans motif exploitable, une exception du
    domaine n'a pas de valeur pour l'auditeur (Revenu Québec, ARC).
    """

    def __init__(self, message: str) -> None:
        # Refus fail-fast des messages absents, vides ou blancs.
        # - ``None`` ou tout non-``str`` : ``TypeError`` (contrat de type).
        # - Chaîne dont ``strip()`` est vide (``""``, ``"   "``, ``"\t\n"``) :
        #   ``ValueError`` (valeur invalide) — un message uniquement composé
        #   d'espaces est sémantiquement vide.
        if not isinstance(message, str):
            raise TypeError(
                "Le message d'une exception du domaine doit être une chaîne "
                "non vide (Req 8.3, 8.6)."
            )
        if not message.strip():
            raise ValueError(
                "Le message d'une exception du domaine ne peut pas être vide "
                "ni composé uniquement d'espaces (Req 8.3, 8.6). Fournir un "
                "motif actionnable citant le cas refusé et, le cas échéant, "
                "l'outil officiel de repli (WebRAS, PDOC)."
            )
        super().__init__(message)


class UnsupportedPayrollCase(PayrollDomainError):
    """Cas de paie hors de la matrice Camp LilySO (règle 03).

    Levée à la frontière du moteur (validateurs de ``Employee``,
    ``PayPeriod``, ``PayrollInput``) lorsqu'une entrée sort du périmètre
    supporté : province autre que Québec, fréquence de paie autre qu'aux
    deux semaines, rémunération non horaire, retenue non supportée,
    avantage imposable non supporté, taux de vacances hors
    ``{0.04, 0.06}``, etc.

    Le message DOIT préciser la nature du cas refusé et renvoyer
    explicitement vers WebRAS (``revenuquebec.ca/webras``) et le
    calculateur PDOC (``canada.ca/pdoc``) — voir Req 8.3.

    NE DOIT PAS être utilisée pour signaler un paramètre manquant ou
    une sentinelle ``"TO_FILL"`` dans un cas par ailleurs supporté :
    dans ce dernier cas, lever ``MissingParameterError`` (Req 8.2).
    """


class MissingParameterError(PayrollDomainError):
    """Paramètre fiscal manquant ou marqué ``"TO_FILL"`` (règle 05).

    Levée par le chargeur ``payroll_engine.parameters_loader.load_parameters``
    (et par les propriétés matérialisant les sections différées de
    ``ParametresAnnee``) lorsqu'une valeur nécessaire à un calcul est
    absente ou porte la sentinelle ``"TO_FILL"``.

    Le message DOIT être actionnable et préciser (Req 8.6) :

    - le chemin JSON du paramètre manquant
      (ex. ``rrq.maximum_gains_admissibles_mga``) ;
    - l'année et la juridiction concernées ;
    - le fichier de paramètres à mettre à jour
      (ex. ``parameters/2026/quebec.json``) ;
    - la source officielle à consulter (TP-1015.F, T4127).

    NE DOIT PAS être utilisée pour signaler un cas hors matrice : dans
    ce dernier cas, lever ``UnsupportedPayrollCase`` (Req 8.2).
    """
