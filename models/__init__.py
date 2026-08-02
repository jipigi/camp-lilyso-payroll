"""Contrats de données du moteur de paie Camp LilySO.

Contient les dataclasses/Pydantic pour :

- `Employee` : fiche employé (données non sensibles seulement)
- `PayPeriod` : période de paie avec ses semaines constituantes
- `PayrollInput` : contrat d'entrée du moteur
- `PayrollResult` : contrat de sortie du moteur
- `CalculationTrace` : trace exhaustive d'un calcul fiscal
- Exceptions du domaine : `UnsupportedPayrollCase`, `MissingParameterError`

Ces contrats sont figés par la spec `moteur-paie-contrats` et servent
de socle immuable aux modules de calcul.
"""
