# Plan d'implémentation

Séquence de développement du moteur de paie Camp LilySO. Chaque étape correspond à une spec Kiro dédiée, à créer une seule à la fois selon la règle `06-workflow-kiro.md`.

## Étape 0 — Cadrage et paramètres (en cours)

**Livrables** :

- [x] Steering rules (règles 01 à 06)
- [x] Documentation initiale : hypothèses 2026, sources, cas non supportés, plan, journal
- [x] Corpus de golden tests QC001 à QC006 documenté (6 scénarios avec valeurs WebRAS et PDOC au cent près)
- [x] Ateliers données sources : protocole `intake/` + `docs/atelier-donnees-sources.md`
- [x] Paramètres 2026 partiellement validés dans `parameters/2026/*.json` :
  - Taux RRQ 6,3 %, RRQ2 4 %, exemption 3 500 / 27 = 129,63 $
  - Taux RQAP employé 0,43 %, employeur 0,602 %
  - Taux AE employé 1,30 %, multiplicateur employeur 1,4
  - Taux FSS 1,65 % (Camp LilySO 2026, masse 14 861,60 $)
  - Nombre de périodes de paie 2026 = 27
  - Montants personnels de base QC (18 952 $) et fédéral (16 452 $)
- [ ] **Consultation directe du TP-1015.F 2026 et du T4127 2026** pour compléter :
  - Plafonds annuels RRQ (MGA, MSGA), plafond RQAP, plafond AE
  - Paliers et constantes de la formule d'impôt QC (avec déduction pour travailleur)
  - Paliers et constantes de la formule d'impôt fédéral (avec montant d'emploi canadien)
  - Règles d'arrondissement officielles
- [ ] Environnement Python (uv ou venv), `pyproject.toml` déjà en place, installer `pytest`, `hypothesis`
- [ ] Investigation de l'anomalie RQAP employeur EMP003 (Excel 1,78 vs formule 1,77) par ré-exécution WebRAS

**Critère de sortie** : tous les `TO_FILL` liés à la couverture des scénarios QC001-QC006 sont remplis dans les fichiers de paramètres, et l'environnement Python peut exécuter un test bidon.

## Étape 1 — Spec `moteur-paie-contrats`

**Objectif** : établir les modèles de données, exceptions, format de trace, et chargeur de paramètres.

**Livrables** :

- `models/employee.py` : dataclass `Employee` (données non-sensibles)
- `models/pay_period.py` : dataclass `PayPeriod` avec semaines constituantes
- `models/payroll_input.py` : contrat d'entrée typé du moteur
- `models/payroll_result.py` : contrat de sortie typé (gains, retenues, employeur, net, coût employeur)
- `models/trace.py` : `CalculationTrace` avec source, année, paramètres, sous-totaux
- `models/exceptions.py` : `UnsupportedPayrollCase`, `MissingParameterError`
- `payroll_engine/parameters_loader.py` : chargeur JSON → objets typés
- Tests : validation des contrats, refus de `float`, refus de `TO_FILL`, refus de cas hors matrice

**Critère de sortie** : les contrats sont figés, testés, et servent de socle non modifiable aux étapes suivantes.

## Étape 2 — Spec `gains-bruts-vacances-hs`

**Objectif** : calculer le salaire brut à partir des heures.

**Livrables** :

- `payroll_engine/gross_pay.py`
- `payroll_engine/overtime.py` (calcul par semaine, seuil 40 h)
- `payroll_engine/vacation.py` (4 % ou 6 %)
- Décomposition explicite : régulier / heures supplémentaires / vacances / brut total

**Tests** :

- Golden test : 36 h, 40 h, 41 h par semaine
- Property test : `brut = regulier + hs + vacances`
- Cas d'erreur : heures négatives, taux nul, semaine à 168 h

## Étape 3 — Spec `rrq`

**Objectif** : reproduire la formule RRQ du TP-1015.F 2026 au cent près.

**Livrables** :

- `payroll_engine/rrq.py`
- Support de l'exemption générale annuelle (répartition selon la fréquence de paie)
- Support du plafond annuel (arrêt de la cotisation)
- Support des cumuls YTD

**Tests** :

- Golden test QC001 : cotisation employé = 86,34 $ sur 1 516,32 $
- Property test : cotisation ≤ plafond annuel, monotonie du cumul
- Cas d'erreur : gains inférieurs à l'exemption prorata → cotisation nulle

## Étape 4 — Spec `rqap`

**Objectif** : reproduire la formule RQAP du TP-1015.F 2026.

**Livrables** :

- `payroll_engine/rqap.py`
- Cotisation employé et employeur
- Plafond annuel

**Tests** :

- Golden test QC001 (à compléter)
- Property test : plafonds respectés, cumul monotone

## Étape 5 — Spec `assurance-emploi`

**Objectif** : reproduire la formule AE du T4127 2026 (taux Québec).

**Livrables** :

- `payroll_engine/ei.py`
- Cotisation employé (taux QC)
- Cotisation employeur (× 1,4)
- Plafond annuel

**Tests** :

- Golden test QC001 (à compléter via PDOC)
- Property test : `employeur = 1.4 * employe` (au cent près)

## Étape 6 — Spec `impot-quebec`

**Objectif** : reproduire la retenue d'impôt du Québec selon TP-1015.F 2026.

**Livrables** :

- `payroll_engine/quebec_tax.py`
- Support de la fréquence de paie théorique (26 périodes annuelles ou selon la formule officielle)
- Support de l'exonération TP-1015.3
- Support de la retenue additionnelle
- Séparation stricte : exonération d'impôt ≠ exemption des cotisations sociales

**Tests** :

- Golden test QC001 : impôt QC = 104,56 $
- Cas d'exonération : impôt QC = 0 $, RRQ/RQAP/AE inchangés
- Retenue additionnelle : ajout au cent près

## Étape 7 — Spec `impot-federal`

**Objectif** : reproduire la retenue d'impôt fédéral selon T4127 2026.

**Livrables** :

- `payroll_engine/federal_tax.py`
- Support de la fréquence de paie théorique
- Support de l'exonération TD1
- Support de la retenue additionnelle

**Tests** :

- Golden test QC001 (à compléter via PDOC)
- Cas d'exonération

## Étape 8 — Spec `charges-patronales`

**Objectif** : calculer les charges assumées par l'employeur (hors bulletin employé).

**Livrables** :

- `payroll_engine/employer_contributions.py`
- FSS (selon taux annuel)
- CNESST (taux configurable, provision si en attente de classification)
- CNT (cotisation normes du travail)
- RRQ / RQAP / AE employeur (déjà calculés dans les modules précédents, ici agrégés)

**Tests** :

- Property test : `cout_employeur = brut + total_charges_patronales`
- Comportement CNESST en attente : flag `EN_ATTENTE_CLASSIFICATION` dans la trace

## Étape 9 — Spec `net-cumuls-registre`

**Objectif** : assembler un `PayrollResult` complet et maintenir le registre maître.

**Livrables** :

- `payroll_engine/net_pay.py`
- `payroll_engine/register.py` (persistance SQLite)
- Cumuls YTD par employé et par catégorie
- Distinction saison / année civile

**Tests** :

- Property test : identité comptable brut = net + retenues
- Property test : cumul YTD n paies = somme des paies 1..n
- Test d'annulation-remplacement (immutabilité, versionnement)

## Étape 10 — Spec `bulletin-pdf`

**Objectif** : générer un bulletin PDF conforme aux exigences du guide TP-1015.G.

**Livrables** :

- `payroll_engine/paystub.py` (reportlab, weasyprint ou équivalent)
- Bulletin employé (sans charges patronales)
- Registre maître (avec charges patronales)

**Tests** :

- Snapshot PDF (comparaison structure)
- Présence des champs obligatoires

## Étape 11 — Spec `interface-streamlit`

**Objectif** : interface locale pour saisir une paie et générer les livrables.

**Livrables** :

- `app/main.py` (Streamlit)
- Sélection employé → saisie heures → génération paie et PDF
- Consultation du registre maître

**Tests** :

- Tests d'intégration : parcours saisie → PDF sans erreur
- Aucun test UI automatisé au niveau des composants (hors périmètre MVP)

## Étape 12 — Validation croisée continue

**Objectif** : politique de validation permanente.

**Livrables** :

- Procédure : chaque saison, revalider au moins un scénario par employé via WebRAS + PDOC
- Journal de validation à jour dans `docs/journal-validation.md`
- Mise à jour annuelle des paramètres `parameters/<AAAA>/`

## Ordre de priorité si le temps manque

Si la première saison arrive avant la complétion de toutes les étapes :

1. Étapes 0 à 3 (contrats + gains + RRQ) sont nécessaires
2. Étapes 4 à 7 (RQAP, AE, impôts) sont nécessaires
3. Étape 8 (charges patronales) est nécessaire pour la comptabilité
4. Étape 9 (registre) est nécessaire pour les cumuls
5. Étape 10 (PDF) et Étape 11 (Streamlit) peuvent temporairement être remplacés par un export CSV et une saisie via un notebook Jupyter

L'objectif reste **exactitude avant automatisation**.
