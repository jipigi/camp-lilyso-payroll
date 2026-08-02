# Règle 05 — Paramètres fiscaux annuels versionnés

**Statut :** absolue
**Portée :** `payroll_engine/`, `parameters/`

## Règle

Aucun taux, plafond, seuil, exemption ou crédit fiscal ne DOIT être codé en dur dans les fonctions Python. Tous les paramètres fiscaux DOIVENT être stockés dans des fichiers JSON versionnés par année sous `parameters/<AAAA>/`.

## Structure

```
parameters/
├── 2026/
│   ├── quebec.json     # TP-1015.F 2026 : RRQ, RQAP, impôt QC, FSS, CNT
│   └── canada.json     # T4127 2026 : AE, impôt fédéral, TD1
└── 2027/
    ├── quebec.json
    └── canada.json
```

## Contenu type d'un fichier de paramètres

```json
{
  "annee": 2026,
  "source": "Revenu Québec — TP-1015.F 2026",
  "date_publication": "AAAA-MM-JJ",
  "url_consultee": "https://www.revenuquebec.ca/...",
  "rrq": {
    "taux_base_employe": "0.0630",
    "taux_base_employeur": "0.0630",
    "exemption_generale_annuelle": "3500.00",
    "maximum_gains_admissibles": "TO_FILL",
    "cotisation_max_employe": "TO_FILL"
  },
  "rqap": {
    "taux_employe": "TO_FILL",
    "taux_employeur": "TO_FILL",
    "maximum_gains_assurables": "TO_FILL",
    "cotisation_max_employe": "442.90"
  }
}
```

## Conventions

- Tous les montants et taux sont des chaînes JSON, parsées en `Decimal` au chargement
- Chaque section inclut sa source et l'année
- Les valeurs inconnues portent la sentinelle `"TO_FILL"` et lèvent une erreur explicite si utilisées
- Aucun paramètre ne doit apparaître à deux endroits (source unique de vérité)

## Chargement

Un chargeur unique `parameters.loader.load_parameters(year, jurisdiction)` :

- lit le fichier JSON correspondant
- convertit toutes les chaînes numériques en `Decimal`
- refuse toute valeur `"TO_FILL"` avec un message actionnable
- retourne un objet typé (dataclass ou Pydantic)

## Mise à jour annuelle

Chaque année, avant la première paie :

1. Consulter les nouveaux TP-1015.F et T4127 sur les sites officiels
2. Créer `parameters/<nouvelle_annee>/quebec.json` et `canada.json`
3. Documenter la source et la date de consultation dans chaque fichier
4. Faire tourner tous les scénarios de référence avec les nouveaux paramètres
5. Consigner les résultats dans `docs/journal-validation.md`

## Interdiction

À NE JAMAIS faire :

```python
# INTERDIT — paramètres codés en dur
TAUX_RRQ = Decimal("0.063")
EXEMPTION_RRQ = Decimal("3500.00")

def calcul_rrq(salaire):
    return salaire * TAUX_RRQ
```

À faire :

```python
def calcul_rrq(salaire, parametres: ParametresRRQ):
    return salaire * parametres.taux_base_employe
```
