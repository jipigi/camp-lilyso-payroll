# Règle 03 — Périmètre Camp LilySO

**Statut :** absolue
**Portée :** conception, implémentation, tests, interface

## Règle

L'application couvre EXCLUSIVEMENT les cas de paie du Camp LilySO. Tout cas hors périmètre DOIT lever `UnsupportedPayrollCase` avec un message clair pointant vers WebRAS ou le calculateur ARC.

## Cas supportés (matrice explicite)

| Dimension | Valeurs supportées |
|---|---|
| Province de travail | Québec uniquement |
| Type d'emploi | Salarié saisonnier à durée déterminée |
| Rémunération | Horaire (heures régulières + heures supplémentaires) |
| Vacances | 4 % versées à chaque paie (extensible à 6 %) |
| Fréquence de paie | Aux deux semaines |
| Régime de retraite | RRQ (pas RPC) |
| RQAP | Oui |
| Assurance-emploi | Taux Québec, multiplicateur employeur 1,4 |
| Impôt QC | TP-1015.3 avec montant total + exonération optionnelle |
| Impôt fédéral | TD1 avec montant total + exonération optionnelle |
| Jours fériés | Champ manuel (pas de calcul automatique dans MVP) |

## Cas explicitement NON supportés

Tout ce qui n'est pas dans la matrice ci-dessus, notamment :

- autres provinces ou territoires
- travailleurs autonomes, consultants, entrepreneurs
- rémunération à commission, au rendement, ou avec bonis complexes
- pourboires
- allocations automobiles, logement fourni, avantages imposables
- régimes de retraite complémentaires, REER collectifs
- assurance collective, assurance salaire
- cotisations syndicales
- pension alimentaire, saisies de salaire
- actions, options d'achat
- fréquences de paie autres qu'aux deux semaines (hebdo, mensuelle, etc.)

## Principe fail-fast

Face à un cas inconnu :

- NE JAMAIS inventer un traitement fiscal
- NE JAMAIS produire un résultat approximatif
- NE JAMAIS ignorer silencieusement une entrée non reconnue
- TOUJOURS lever une exception explicite avec message actionnable

Exemple :

```python
raise UnsupportedPayrollCase(
    "Fréquence de paie 'hebdomadaire' non supportée. "
    "Le Camp LilySO fonctionne aux deux semaines uniquement. "
    "Pour un cas exceptionnel, utiliser WebRAS et le calculateur ARC."
)
```

## Extension du périmètre

L'ajout d'un cas supporté DOIT :

1. être documenté dans `docs/cas-non-supportes.md` (déplacement vers cas supportés)
2. être accompagné d'au moins un golden test WebRAS/ARC
3. être testé contre tous les scénarios de référence existants pour éviter les régressions
