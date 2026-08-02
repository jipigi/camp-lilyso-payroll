# Règle 01 — Decimal obligatoire

**Statut :** absolue, non négociable
**Portée :** tout le moteur de paie (`payroll_engine/`, `models/`, tests inclus)

## Règle

Tous les calculs monétaires et fiscaux DOIVENT utiliser `decimal.Decimal`. L'utilisation de `float` est interdite dans le domaine paie.

## Justification

Les calculs fiscaux publiés par Revenu Québec (TP-1015.F) et l'ARC (T4127) sont définis en arithmétique décimale exacte, avec des règles d'arrondissement précises. `float` introduit des erreurs binaires qui peuvent produire des écarts au cent avec WebRAS ou le calculateur ARC, ce qui invaliderait les golden tests.

## Application

À faire :

```python
from decimal import Decimal
salaire_brut = Decimal("1516.32")
taux_rrq = Decimal("0.063")
```

À ne pas faire :

```python
salaire_brut = 1516.32              # INTERDIT
taux_rrq = 6.3 / 100                # INTERDIT
montant = Decimal(1516.32)          # INTERDIT (conversion depuis float)
```

## Arrondissement

Toujours utiliser les modes d'arrondissement définis par les guides officiels (`ROUND_HALF_UP`, `ROUND_HALF_EVEN`, etc. selon la formule). L'arrondissement doit être documenté et référencé à la source officielle dans la trace de calcul (voir règle 02).

## Vérification

- Tout PR introduisant `float` dans `payroll_engine/` ou `models/` doit être refusé.
- Les tests doivent comparer avec `Decimal` et une tolérance nulle (`==`) contre les résultats WebRAS/ARC.
- Un test de garde vérifie qu'aucun montant du résultat n'est de type `float`.
