"""Stratégies Hypothesis réutilisables pour les property-based tests.

Ce module hébergera les stratégies communes qui seront enrichies progressivement
par les tâches 2 à 14 de la spec ``moteur-paie-contrats``. Il est
volontairement vide (aucune stratégie exportée) tant que les modèles du domaine
n'existent pas — importer ce module ne DOIT pas déclencher d'import des
modèles, afin que la découverte pytest reste possible sans le paquet ``models``.

Stratégies planifiées (design.md, section « Stratégies Hypothesis ») :

- ``decimal_monetary()`` — ``Decimal`` ≥ 0, deux décimales, borné à 100 000 $.
- ``decimal_heures()``    — ``Decimal`` ∈ [0, 168], deux décimales.
- ``date_travail()``      — dates 2020-01-01 → 2030-12-31.
- ``employe_valide()``    — ``Employee`` valide (tâche 6).
- ``week_segment_valide(debut)`` — semaine de 7 jours (tâche 7).
- ``pay_period_valide()`` — ``PayPeriod`` avec 2 semaines contiguës (tâche 7).
- ``cumuls_ytd_valide()`` — ``CumulsYTD`` avec catégories ``decimal_monetary``.
- ``calculation_trace_valide()`` — source tirée de la liste blanche (tâche 5).
- ``payroll_result_valide()`` — identités comptables satisfaites par
  construction (tâche 10).

Règle 01 : chaque stratégie manipulant un montant fiscal DOIT retourner un
``Decimal`` (jamais un ``float``).
"""

from __future__ import annotations

# Aucune stratégie exportée pour l'instant. Les tâches ultérieures ajouteront
# les fonctions listées dans la docstring ci-dessus, avec leurs tests.
__all__: list[str] = []
