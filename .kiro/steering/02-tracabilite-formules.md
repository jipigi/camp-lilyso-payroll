# Règle 02 — Traçabilité des formules

**Statut :** absolue
**Portée :** toutes les fonctions de calcul de `payroll_engine/`

## Règle

Chaque fonction de calcul fiscal ou monétaire retourne un tuple `(montant, trace)` où `trace` est un objet `CalculationTrace` documentant :

- **source** : référence officielle exacte (ex. `"TP-1015.F 2026, section 3.2 — RRQ"`)
- **année** : année d'application des paramètres
- **paramètres utilisés** : taux, plafonds, exemptions employés
- **entrées** : valeurs reçues par la fonction
- **sous-totaux** : étapes intermédiaires nommées
- **arrondissement** : mode et précision appliqués
- **résultat** : montant final

## Justification

Toute retenue ou charge patronale calculée par l'application doit pouvoir être auditée en un clic. Si Revenu Québec ou l'ARC conteste un montant dans trois ans, la trace doit permettre de reconstruire le calcul exact à partir des règles officielles de l'année concernée.

## Application

Signature type d'une fonction de calcul :

```python
from decimal import Decimal
from models.trace import CalculationTrace

def calcul_rrq_employe(
    salaire_periode: Decimal,
    frequence_paie: FrequencePaie,
    cumul_rrq_ytd: Decimal,
    parametres: ParametresRRQ,
) -> tuple[Decimal, CalculationTrace]:
    ...
```

## Interdiction

Une fonction de calcul ne DOIT PAS :

- retourner un montant sans trace
- inventer une référence officielle (« estimation », « approximation »)
- utiliser une source non-officielle (blogs, forums, exemples internet)

## Sources officielles autorisées

Uniquement :

- Revenu Québec — TP-1015.F, TP-1015.G, TP-1015.3
- ARC — T4127, TD1, guide de l'employeur
- Sites officiels `.gouv.qc.ca` et `.canada.ca`

Toute autre source doit être documentée dans `docs/sources-officielles.md` et justifiée.
