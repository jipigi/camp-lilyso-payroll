# Journal de validation

Registre chronologique des validations effectuées contre les outils officiels (WebRAS, PDOC) et des mises à jour de paramètres. À tenir à jour à chaque intervention significative sur le moteur ou sur les paramètres.

## Format d'entrée

Chaque entrée comprend :

- Date (AAAA-MM-JJ)
- Type : `parametres`, `scenario`, `annuel`, `regression`, `deviation`
- Personne responsable (initiales suffisent)
- Description
- Résultat : `OK`, `ECART`, `EN_COURS`
- Actions prises

---

## 2026

### 2026-01-XX — Cadrage initial du projet

- **Type** : parametres
- **Description** : ouverture du workspace, création des règles de steering, documentation initiale, scénario QC001 amorcé avec résultats WebRAS partiels (RRQ 86,34 $, impôt QC 104,56 $).
- **Résultat** : EN_COURS
- **Actions** : compléter QC001 avec RQAP, AE, impôt fédéral et employeur ; finaliser `parameters/2026/*.json` avec les valeurs officielles du TP-1015.F et T4127 2026.

### 2026-01-XX — Extraction du corpus initial (5 paies réelles + QC001 ré-exécuté)

- **Type** : scenario
- **Description** :
  - Extraction anonymisée de 5 bulletins de paie réels de la paie #1 saison 2026 (déposés dans `intake/`, jamais versionnés).
  - Ré-exécution complète de QC001 dans WebRAS et PDOC pour lever la divergence RRQ initiale.
  - Validation croisée des paramètres 2026 sur 6 exécutions indépendantes.
- **Résultat** : OK
- **Constats clés** :
  - **Fréquence 2026 = 27 périodes** confirmée par WebRAS et PDOC (année à 27 paies bi-hebdomadaires).
  - Exemption RRQ par période = 3 500 ÷ 27 = **129,63 $**.
  - Taux 2026 confirmés au cent près sur 6 scénarios : RRQ 6,30 %, RQAP employé 0,43 %, RQAP employeur 0,602 %, AE employé 1,30 %, AE employeur ×1,4, FSS 1,65 % (à masse salariale 14 861,60 $).
  - **Divergence initiale QC001 résolue** : l'ancienne valeur RRQ 86,34 $ provenait d'une exécution WebRAS en « deux fois par mois » (24 périodes). La ré-exécution en « aux deux semaines / 27 périodes » donne RRQ = 87,36 $, cohérent avec la formule des 5 paies réelles.
  - **PDOC révèle un mécanisme important** : la cotisation supplémentaire au RRQ (1 % × (brut − exemption)) est traitée comme une **déduction du revenu imposable fédéral**, pas un crédit. Impact sur la formule `impot-federal`.
  - **Ni WebRAS ni PDOC** ne proposent de case à cocher « exonération de la retenue d'impôt ». L'exonération signalée sur TP-1015.3 ou TD1 est appliquée en aval par l'employeur, hors calculateurs officiels. Le moteur reflétera ce mécanisme comme un court-circuit avant la formule d'impôt.
- **Actions suivantes** :
  - Créer les scénarios `QC002` à `QC006` (les 5 paies réelles anonymisées) après clarification de l'application concrète de l'exonération dans le corpus réel.
  - Consulter TP-1015.F 2026 et T4127 2026 pour compléter les formules d'impôt et les plafonds annuels (`TO_FILL` restants).
- **Fichiers modifiés** : `docs/scenario-qc001.md`, `parameters/2026/quebec.json`, `parameters/2026/canada.json`, `docs/hypotheses-2026.md`, `docs/journal-validation.md`.

### 2026-01-XX — Corpus complet des scénarios QC001-QC006 (impôts validés)

- **Type** : scenario
- **Description** :
  - Confirmation avec l'employeur du mécanisme d'exonération : ni WebRAS ni PDOC ne proposent de case dédiée. Les employés ayant coché exonération sur TP-1015.3 ou TD1 se voient retenir 0 $ par décision employeur en aval, indépendamment de ce que la formule aurait calculé. Le moteur reflétera ce mécanisme par un court-circuit avant l'invocation de la formule.
  - Ré-exécution WebRAS et PDOC des bruts de EMP001, EMP002, EMP004, EMP005 sans considération d'exonération (valeurs « formule ») pour compléter les golden tests de la formule d'impôt.
  - Création des scénarios `QC002` à `QC006` avec les valeurs pré-exonération (pour tester la formule) et post-exonération (pour tester le court-circuit).
- **Résultat** : OK
- **Points de validation de la formule d'impôt QC** (avant exonération) :
  - QC001 : brut 1 516,32 → 104,56 $ (WebRAS)
  - QC002 : brut 2 861,04 → 329,31 $ (WebRAS)
  - QC003 : brut 2 179,84 → 201,17 $ (WebRAS)
  - QC004 : brut 294,84 → 0,00 $ (WebRAS, sous seuil)
  - QC005 : brut 1 739,92 → 135,55 $ (WebRAS)
  - QC006 : brut 505,44 → 0,00 $ (WebRAS, sous seuil)
- **Points de validation de la formule d'impôt fédéral** (avant exonération) :
  - QC001 : brut 1 516,32 → 86,25 $ (PDOC)
  - QC002 : brut 2 861,04 → 289,05 $ (PDOC)
  - QC003 : brut 2 179,84 → 173,35 $ (PDOC)
  - QC004 : brut 294,84 → 0,00 $ (PDOC, sous seuil)
  - QC005 : brut 1 739,92 → 112,66 $ (PDOC)
  - QC006 : brut 505,44 → 0,00 $ (PDOC, sous seuil)
- **Anomalie détectée** : dans le fichier Excel source, la valeur RQAP employeur pour EMP003 (QC004) est de 1,78 $ alors que la formule `294,84 × 0,602 %` produit 1,7749 $ arrondi à 1,77 $. Écart de 1 ¢. Cause probable : saisie manuelle dans l'Excel. Action : lors de l'implémentation du module `rqap`, ré-exécuter QC004 dans WebRAS et prendre la valeur retournée comme référence.
- **Fichiers créés** : `docs/scenario-qc002.md`, `docs/scenario-qc003.md`, `docs/scenario-qc004.md`, `docs/scenario-qc005.md`, `docs/scenario-qc006.md`.

### 2026-01-XX — Étape 0 : couverture des golden tests

- **Type** : scenario
- **Description** : synthèse de la couverture des tests de référence après extraction du corpus.
- **Couverture par module** :

| Module moteur | Nombre de scénarios | Bruts testés (min/max) |
|---|---|---|
| Gains bruts + vacances + HS | 6 | 294,84 → 2 861,04 |
| RRQ (formule et exemption 129,63 par période) | 6 | 294,84 → 2 861,04 |
| RQAP employé (0,43 %) | 6 | 294,84 → 2 861,04 |
| RQAP employeur (0,602 %) | 6 (anomalie 1 ¢ sur QC004 à investiguer) | 294,84 → 2 861,04 |
| AE employé (1,30 %) | 6 | 294,84 → 2 861,04 |
| AE employeur (× 1,4) | 6 | 294,84 → 2 861,04 |
| FSS (1,65 % pour masse 14 861,60 $) | 6 | 294,84 → 2 861,04 |
| CNESST (provision 1,12 %) | 6 | 294,84 → 2 861,04 |
| Impôt QC (formule, sans exonération) | 6 (dont 2 sous-seuil = 0 $) | 0 $ → 329,31 $ |
| Impôt fédéral (formule, sans exonération) | 6 (dont 2 sous-seuil = 0 $) | 0 $ → 289,05 $ |
| Court-circuit exonération QC | 4 (QC002, QC003, QC005, QC006) | — |
| Court-circuit exonération fédéral | 4 (QC002, QC003, QC005, QC006) | — |

- **Résultat** : OK. Le corpus est suffisamment dense pour engager l'implémentation avec confiance.

---

## Modèle pour prochaines entrées

```
### AAAA-MM-JJ — Titre court

- Type : scenario | parametres | annuel | regression | deviation
- Responsable : XY
- Description : ce qui a été fait, quel scénario, quelle source consultée
- Résultat : OK | ECART | EN_COURS
- Actions : ce qui a été fait ou reste à faire
- Références : URLs, sections du TP-1015.F ou T4127, chemins de fichiers modifiés
```

## Politique de validation

- **Avant la première paie de chaque saison** : re-tourner tous les scénarios de référence avec les paramètres de l'année et documenter le résultat ici.
- **À chaque publication d'un nouveau TP-1015.F ou T4127** : consigner la date de publication, la date de consultation, et les changements pertinents.
- **À chaque écart entre WebRAS/PDOC et le moteur** : consigner l'écart en cents, la cause probable, et le correctif appliqué. Ne jamais fermer un écart sans explication documentée.
- **À chaque ajout d'un cas supporté** : consigner la modification de la matrice de la règle 03 et du document `cas-non-supportes.md`.

### 2026-01-XX — Confirmation officielle de la classification CNESST

- **Type** : parametres
- **Description** : réception de la décision de classification de la CNESST pour Camp LilySO.
- **Résultat** : OK
- **Valeurs confirmées** :
  - Unité de classification : **57020**
  - Taux CNI : **0,90 %**
  - Taux d'unité : **0,22 %**
  - Taux total : **1,12 %**
- **Impact** : les hypothèses initiales sont validées telles quelles. Aucun recalcul n'est nécessaire, tous les scénarios QC001-QC006 conservent leurs valeurs CNESST déjà calculées à 1,12 %.
- **Fichiers modifiés** : `parameters/2026/quebec.json` (section `cnesst` : statut `VALIDE_OFFICIEL`, drapeau `en_attente_classification: false`), `docs/hypotheses-2026.md` (tableau CNESST), scénarios QC001 à QC006 (libellé « provision, hypothèse » → « unité 57020 confirmée »).
- **Note pour le modèle** : le drapeau `en_attente_classification` reste dans le contrat de données (spec `moteur-paie-contrats`, Requirement 4) pour permettre de représenter d'autres employeurs ou années où la classification serait encore en attente. Pour Camp LilySO 2026, il vaudra `false`.

### 2026-01-XX — Remplissage des plafonds RRQ, RQAP et AE 2026 (TP-1015.F, canada.ca)

- **Type** : parametres
- **Description** : consultation directe du TP-1015.F (2026-01) et du T4127(F) Rév. 26 (26/06), complétée par la page canada.ca « Avis important concernant le maximum de la rémunération assurable pour 2026 » (ARC/ESDC) pour le plafond AE applicable aux résidents du Québec. Remplissage des sentinelles `TO_FILL` correspondantes dans `parameters/2026/quebec.json` et `parameters/2026/canada.json`. Ce travail débloque la spec `rrq` (étape 3 du plan d'implémentation).
- **Résultat** : OK
- **Valeurs renseignées** :
  - `quebec.json.rrq` : `maximum_gains_admissibles_mga` = 74 600,00 $, `maximum_supplementaire_gains_admissibles_msga` = 85 000,00 $, `cotisation_max_annuelle_employe` = 4 479,30 $ (base + première cotisation supplémentaire combinées), `statut_plafonds` → `VALIDE_TP1015F_2026`. Ajout documentaire (`extra="allow"`, non typé) de `deuxieme_cotisation_supplementaire_maximale_employe`/`employeur` = 416,00 $ pour référence future de la spec `rrq`.
  - `quebec.json.rqap` : `maximum_gains_assurables` = 103 000,00 $, `cotisation_max_employe` = 442,90 $, `cotisation_max_employeur` = 620,06 $, `statut_plafonds` → `VALIDE_TP1015F_2026`.
  - `quebec.json` (racine) : `date_publication` = "2026-01" (date de révision imprimée sur le TP-1015.F). `date_consultation` et `url_consultee` restent `TO_FILL` — aucune date de consultation ni URL n'a été fabriquée, seule la date de révision du document papier est vérifiable ici.
  - `canada.json.assurance_emploi` : `maximum_gains_assurables` = 68 900,00 $, `cotisation_max_employe` = 895,70 $ (68 900 × 1,30 %), `cotisation_max_employeur` = 1 253,98 $ (895,70 × 1,4), `statut_plafonds` → `VALIDE_CANADA_CA_2026` (distinct de `VALIDE_PDOC` : provenance = page canada.ca, pas une exécution PDOC). URL source consignée dans le nouveau champ `commentaire_source_plafonds`.
- **Hors périmètre de cette entrée** (restent `TO_FILL`, formulés par des specs futures) : table FSS par masse salariale, section `cnt`, paliers `impot_quebec`/`impot_federal`, sections `td_1015_3`/`td1` liées aux montants annuels non encore consommés.
- **Tests ajustés** : les tests `tests/test_guards.py::TestExceptionMessageContract::test_message_missing_parameter_error` et `tests/payroll_engine/test_parameters_loader.py::TestValeurToFill` ciblaient `rrq.maximum_gains_admissibles_mga` comme exemple de paramètre `TO_FILL`. Ce champ étant désormais renseigné, la cible a été redirigée vers `cnt.taux` (section CNT, charge patronale annuelle, toujours `TO_FILL`, exposée par une propriété typée `_materialiser`-backed dans `payroll_engine/parameters_loader.py::CNTParametres`, hors périmètre des specs `rrq`/`rqap`/`assurance-emploi`). Le test `test_acces_rrq_mga_leve_missing_parameter_error` a été renommé `test_acces_cnt_taux_leve_missing_parameter_error`.
- **Vérification** : `pytest tests/` → 649 passed, 1 skipped (aucune régression). Aucun `float` introduit ; tous les montants restent des chaînes JSON converties en `Decimal` au chargement.
- **Références** : TP-1015.F (2026-01), p.7 « Cotisations au RRQ » et « Cotisations au RQAP » ; T4127(F) Rév. 26 (26/06) ; https://www.canada.ca/fr/emploi-developpement-social/programmes/assurance-emploi/ae-liste/assurance-emploi-employeurs/reduction-taux-cotisation/maximum-remuneration-assurable-2026.html
- **Fichiers modifiés** : `parameters/2026/quebec.json`, `parameters/2026/canada.json`, `tests/test_guards.py`, `tests/payroll_engine/test_parameters_loader.py`, `docs/journal-validation.md`.
