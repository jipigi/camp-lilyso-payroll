"""Suite de tests du moteur de paie Camp LilySO.

Trois catégories :

- Golden tests : reproduction au cent près des résultats WebRAS et PDOC pour
  chaque scénario `QCxxx` documenté sous `docs/scenario-*.md`.
- Property-based tests (Hypothesis) : invariants du domaine (identité comptable,
  monotonie des cumuls, respect des plafonds, refus des cas hors matrice).
- Tests d'erreur : chaque cas non supporté doit lever `UnsupportedPayrollCase`
  avec un message actionnable.
"""
