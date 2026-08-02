# Camp LilySO — Moteur de paie interne

Application interne de paie du Camp LilySO (OBNL, camp de jour saisonnier au Québec). Reproduit localement les calculs officiels de Revenu Québec (WebRAS / TP-1015.F) et de l'Agence du revenu du Canada (calculateur PDOC / T4127) pour un très petit nombre de salariés horaires saisonniers.

## Objectif

Éliminer la double saisie manuelle actuelle entre WebRAS et le calculateur ARC. L'application ne remplace pas les outils officiels — elle les reproduit au cent près pour un périmètre volontairement étroit, tout en conservant WebRAS et PDOC comme oracles de validation.

## Périmètre volontairement étroit

- **Province** : Québec uniquement
- **Employés** : ~5 salariés saisonniers horaires par saison
- **Paies** : ~3 par saison, aux deux semaines
- **Rémunération** : horaire (régulier + heures supp), vacances 4 % versées à chaque paie
- **Régimes** : RRQ, RQAP, AE (taux QC), impôt QC, impôt fédéral
- **Charges patronales** : RRQ, RQAP, AE (× 1,4), FSS, CNESST (provision), CNT

Tout ce qui sort de ce périmètre lève une exception `UnsupportedPayrollCase` et renvoie l'utilisateur vers WebRAS ou PDOC. Détails complets : [`docs/cas-non-supportes.md`](docs/cas-non-supportes.md).

## Principes de conception

1. **Exactitude avant automatisation** — mieux vaut refuser un cas que produire un chiffre approximatif.
2. **`Decimal` partout, jamais `float`** — voir règle de steering `01`.
3. **Traçabilité par formule** — chaque calcul renvoie `(montant, CalculationTrace)` avec source officielle, année, paramètres, sous-totaux. Règle `02`.
4. **Paramètres fiscaux versionnés par année** — aucun taux codé en dur. Règle `05`.
5. **Golden tests contre WebRAS et PDOC** — chaque scénario `QCxxx` est reproduit au cent près.
6. **Property-based testing** — invariants du domaine testés avec Hypothesis.
7. **Aucune donnée personnelle réelle dans le dépôt** — règle `04`.

## Structure

```
camp-lilyso-payroll/
├── .kiro/steering/          règles permanentes de projet (01 à 06)
├── docs/                    hypothèses, sources, cas non supportés, scénarios, plan
├── parameters/2026/         paramètres fiscaux versionnés par année (JSON → Decimal)
├── payroll_engine/          modules de calcul (à venir, spec par spec)
├── models/                  contrats de données (à venir, spec 01)
├── tests/                   golden + property + tests d'erreur
├── app/                     interface Streamlit locale (à venir)
├── pyproject.toml
└── README.md
```

## Documentation clé

- [Hypothèses 2026](docs/hypotheses-2026.md) — valeurs de départ, à confirmer contre TP-1015.F et T4127
- [Sources officielles](docs/sources-officielles.md) — références autorisées uniquement
- [Cas non supportés](docs/cas-non-supportes.md) — matrice explicite de rejet
- [Scénario QC001](docs/scenario-qc001.md) — golden test primaire
- [Plan d'implémentation](docs/plan-implementation.md) — séquence des specs à créer
- [Journal de validation](docs/journal-validation.md) — historique des vérifications
- [Atelier données sources](docs/atelier-donnees-sources.md) — protocole d'importation des Excel WebRAS/PDOC et d'anonymisation vers les scénarios `QCxxx`

## État actuel

**Étape 0 — cadrage et paramètres** (en cours) :

- [x] Steering et documentation initiale
- [ ] Consultation directe du TP-1015.F 2026 et du T4127 2026
- [ ] Complétion des `TO_FILL` dans `parameters/2026/*.json`
- [ ] Complétion des résultats attendus pour QC001 (RQAP, AE, impôt fédéral, employeur)
- [ ] Environnement Python (Python 3.11+, `uv` ou `venv`)

La prochaine étape sera la première spec Kiro : **`moteur-paie-contrats`** (modèles, exceptions, trace, chargeur de paramètres).

## Environnement de développement

Prérequis : Python 3.11 ou supérieur.

Installation locale (exemple avec `venv`) :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Lancer les tests :

```powershell
pytest
```

## Sécurité et confidentialité

Ce dépôt n'accepte **aucune** donnée personnelle réelle (NAS, banque, adresse, nom complet, bulletins réels). La base SQLite contenant les fiches salariés réelles réside hors du dépôt, dans un dossier utilisateur. Voir règle de steering `04`.

## Licence

Usage interne Camp LilySO. Aucune diffusion externe.
