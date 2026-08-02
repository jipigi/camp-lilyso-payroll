"""Moteur de calcul de paie Camp LilySO.

Chaque sous-module implémente une capacité fiscale et retourne un tuple
`(montant, CalculationTrace)` conformément à la règle de steering 02.

Aucun module ne DOIT contenir de valeur numérique de taux, plafond ou
exemption : tous les paramètres proviennent de `parameters/<AAAA>/*.json`.

Voir `docs/plan-implementation.md` pour la séquence de développement.
"""
