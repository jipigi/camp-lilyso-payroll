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

### 2026-08-03 — Validation de `impot_federal.py` contre PDOC (crédit RRQ K2Q) et correction des fixtures QC002/003/005

- **Type** : regression
- **Description** : validation du module `impot_federal.py` contre PDOC (calculateur officiel de l'ARC, référence absolue). PDOC a été ré-exécuté avec l'option « Montant cumulatif annuel », en incluant le crédit fédéral pour la cotisation de base au RRQ (K2Q), sur le brut incluant les vacances 4 %. Les moniteurs du Camp LilySO ont tous 18 ans et plus : ils cotisent au RRQ, donc le calcul fédéral DOIT inclure le crédit K2Q.
- **Résultat** : OK
- **Points de validation de la formule d'impôt fédéral** (avec crédit RRQ K2Q, valeurs PDOC correspondant exactement à `impot_federal.py`) :
  - QC001 : brut 1 516,32 → **86,25 $**
  - QC002 : brut 2 861,04 → **268,06 $**
  - QC003 : brut 2 179,84 → **157,59 $**
  - QC005 : brut 1 739,92 → **110,29 $**
- **Correction des fixtures** : les valeurs `impot_federal_formule` des fixtures QC002/QC003/QC005 (`tests/fixtures/outputs/qc00{2,3,5}.json`) ont été corrigées de 289,05/173,35/112,66 vers **268,06/157,59/110,29**. Les valeurs antérieures provenaient d'un run PDOC réalisé par erreur avec l'option « Exemption au RRQ », qui retire le crédit K2Q. Ces anciennes valeurs étaient incohérentes avec la ligne RRQ effectivement payée dans les mêmes fixtures et avec le mécanisme K2Q officiel décrit au T4127 chapitre 4. Le champ `impot_federal_retenu` reste 0,00 $ pour ces trois scénarios (employés exonérés TD1) — inchangé. QC001 (86,25 $), QC004 et QC006 (0,00 $, sous seuil) étaient déjà corrects — non modifiés.
- **Validation des paramètres officiels 2026** déposés dans `tests/fixtures/official/` (TP-1015.F 2026 et T4127 2026) :
  - Québec : déduction pour travailleur 1 450 $ + taux 0,06, constantes K entières confirmées (0 / 2 717 / 8 151 / 10 465).
  - Fédéral : paliers, constantes K, crédit canadien pour emploi (CEA 1 501 $) et abattement du Québec (0,165) confirmés.
- **Note** : la structure interne complète de la `trace` (clés `entrees`/`sous_totaux`) des `impot_federal_formule` sera réalignée par la tâche 11.1 ; cette entrée ne concerne que la correction du `montant` (et du `resultat` de trace) pour refléter la valeur PDOC validée.
- **Références** : PDOC (option « Montant cumulatif annuel », crédit RRQ K2Q) ; T4127 2026 chapitre 4 (facteur K2Q) ; TP-1015.F 2026 ; `tests/fixtures/official/`.
- **Fichiers modifiés** : `tests/fixtures/outputs/qc002.json`, `tests/fixtures/outputs/qc003.json`, `tests/fixtures/outputs/qc005.json`, `docs/journal-validation.md`.

### 2026-08-03 — Régénération du corpus golden QC001–QC006 (CNT, sources CNESST/CNT, totaux)

- **Type** : scenario
- **Description** : régénération des six fixtures de sortie `tests/fixtures/outputs/qc00{1..6}.json` dans le cadre de la spec `charges-patronales` (tâche 10.1, Req 11.4/11.5). Trois corrections appliquées à la section `cotisations_employeur` de chaque fixture :
  1. **CNT désormais non nulle** : `cnt.montant` passe de `0,00` à `arrondir(0,0006 × brut_total)` (ROUND_HALF_UP, 2 décimales), conformément à la LE-39.0.2 (2026-01), ligne 35 (taux 0,06 %).
  2. **Sources de trace corrigées** (règle 02, Req 5.7) : `cnesst.trace.source` passe de l'attribution erronée `TP-1015.F 2026, section 6 — CNESST` à l'URL officielle CNESST `https://www.cnesst.gouv.qc.ca/fr/demarches-formulaires/employeurs/assurance-sante-securite-travail/tarification/taux-prime` ; `cnt.trace.source` passe de `TP-1015.F 2026, section 7 — CNT` à `LE-39.0.2 2026`. Champs de trace alignés sur le design §Components §2/§3/§4 (sections, `parametres_utilises`, `entrees` avec clé unifiée `salaire_assujetti`).
  3. **Totaux recalculés** : `total_cotisations_employeur` (somme au cent des six montants) et `cout_employeur` (= `brut_total + total`) recalculés pour intégrer la CNT.
- **Résultat** : OK
- **Valeurs de CNT et totaux régénérés** :

| Scénario | brut_total | CNT (0,0006 × brut) | total_cotisations_employeur | cout_employeur |
|---|---|---|---|---|
| QC001 | 1 516,32 | 0,91 | 166,99 | 1 683,31 |
| QC002 | 2 861,04 | 1,72 | 322,34 | 3 183,38 |
| QC003 | 2 179,84 | 1,31 | 243,65 | 2 423,49 |
| QC004 | 294,84 | 0,18 | 25,88 | 320,72 |
| QC005 | 1 739,92 | 1,04 | 192,83 | 1 932,75 |
| QC006 | 505,44 | 0,30 | 50,22 | 555,66 |

- **Validation** :
  - **FSS et CNESST** restent exacts au cent près contre WebRAS : les montants `fss.montant` (`0,0165 × brut`) et `cnesst.montant` (`0,0112 × brut`) sont inchangés par cette régénération (vérifiés par assertion lors de la régénération : `montant == arrondir(taux × brut)`).
  - **CNT** : absente de WebRAS par paie (charge annuelle répartie, décision requirements n° 2), validée par calcul direct `0,0006 × Salaire_Assujetti` de la LE-39.0.2 (2026-01), ligne 35.
  - Round-trip `PayrollResult` : `pytest tests/test_golden_outputs.py::test_golden_output_scenario` (6 scénarios) passe — les invariants comptables (`cout_employeur == brut + total`, `total == somme des six cotisations`) et la liste blanche des sources (`LE-39.0.2 2026`, URL `www.cnesst.gouv.qc.ca`) sont satisfaits.
  - Le golden test `test_charges_patronales_reproduisent_fixture` reste rouge par `ModuleNotFoundError` (module `payroll_engine/charges_patronales.py` livré par la tâche 11.1) — comportement attendu (règle 06, tests avant code).
- **Coordination tâche 11.1** : l'implémentation de `calcul_cnesst` DOIT émettre exactement l'URL `https://www.cnesst.gouv.qc.ca/fr/demarches-formulaires/employeurs/assurance-sante-securite-travail/tarification/taux-prime` comme `trace.source` pour reproduire ces fixtures.
- **Fichiers modifiés** : `tests/fixtures/outputs/qc001.json`–`qc006.json`, `docs/journal-validation.md`.

### 2026-08-03 — Validation manuelle QC001 des charges patronales (checkpoint final `charges-patronales`, tâche 12)

- **Type** : scenario
- **Description** : validation manuelle du scénario de référence QC001 pour les
  trois charges patronales livrées par la spec `charges-patronales` (étape 5),
  charge par charge, après implémentation de `payroll_engine/charges_patronales.py`
  (tâche 11.1). Cette entrée complète l'entrée de régénération du corpus du
  2026-08-03 (« Régénération du corpus golden QC001–QC006 ») en confirmant, au
  cent, que le moteur reproduit les valeurs de la fixture `qc001.json` (Req 11.1
  à 11.3, 11.5).
- **Résultat** : OK
- **Valeurs QC001 reproduites par le moteur** (brut_total = 1 516,32 $) :

| Charge | Formule | Calcul | Montant reproduit | Source de trace |
|---|---|---|---|---|
| FSS | 0,0165 × brut | 0,0165 × 1 516,32 = 25,01928 → ROUND_HALF_UP | **25,02 $** | `TP-1015.F 2026, section 5 — FSS` |
| CNESST | 0,0112 × brut | 0,0112 × 1 516,32 = 16,982784 → ROUND_HALF_UP | **16,98 $** | `https://www.cnesst.gouv.qc.ca/.../taux-prime` (unité 57020) |
| CNT | 0,0006 × brut | 0,0006 × 1 516,32 = 0,909792 → ROUND_HALF_UP | **0,91 $** | `LE-39.0.2 2026` (ligne 35) |
| **total_cotisations_employeur** | somme des six cotisations employeur | RRQ 87,36 + RQAP 9,13 + AE 27,59 + FSS 25,02 + CNESST 16,98 + CNT 0,91 | **166,99 $** | — |

- **Approche de validation** (pas de session WebRAS fabriquée) :
  - **FSS** et **CNESST** : le moteur reproduit **au cent** les montants de la
    fixture `qc001.json`, montants eux-mêmes validés au cent contre WebRAS lors
    des exécutions du corpus (voir entrées « Corpus complet QC001–QC006 » et
    « Confirmation officielle de la classification CNESST », unité 57020 à 1,12 %).
    Une **ré-exécution WebRAS en direct de QC001** (FSS et CNESST) reste une
    **étape manuelle de l'opérateur** à consigner ici lors de la revalidation
    saisonnière ; elle n'a pas été simulée automatiquement.
  - **CNT** : absente de WebRAS par paie (charge annuelle répartie, décision
    requirements n° 2). Validée par **calcul direct** `0,0006 × Salaire_Assujetti`
    d'après la **LE-39.0.2 (2026-01)**, ligne 35 (taux 0,06 %) → 0,91 $, valeur
    reproduite par `calcul_cnt`.
- **Archivage de la source** : le guide **LE-39.0.2 (2026-01)** est référencé dans
  `docs/sources-officielles.md` (section « LE-39.0.2 », ajout à la liste blanche
  `_SOURCES_OFFICIELLES_REGEX` déjà effectué en tâche 8.1) et destiné à
  `docs/sources-officielles/2026/`. **Le dépôt physique du PDF dans ce répertoire
  reste une action manuelle de l'opérateur** (fichier binaire non ajouté par
  l'outillage) — la référence documentaire est en place, la copie PDF est à
  archiver par l'opérateur lors de la validation officielle.
- **Vérification automatisée** : `pytest --strict-markers -ra` → **882 passed,
  1 skipped** (le skip est un corps de test réservé à l'étape 6, sans rapport).
  `test_charges_patronales_reproduisent_fixture` → 6 tests (QC001–QC006) tous au
  cent ; les quatre classes de garde `charges_patronales` passent ; les 13
  propriétés du design (dont l'assemblage 10, 11, 12) sont couvertes.
- **Références** : LE-39.0.2 (2026-01), lignes 29 et 35 ; décision de
  classification CNESST (unité 57020, taux total 1,12 %) ; TP-1015.F 2026,
  section 5 — FSS ; `tests/fixtures/outputs/qc001.json`.
- **Fichiers modifiés** : `docs/cas-non-supportes.md`, `docs/plan-implementation.md`,
  `docs/journal-validation.md`.

### 2026-08-03 — Ré-exécution WebRAS en direct de QC001 (confirmation finale FSS/CNESST)

- **Type** : scenario
- **Description** : ré-exécution manuelle en direct de WebRAS pour le scénario
  QC001 (brut 1 516,32 $, période 1/27), demandée par l'opérateur pour clore
  l'étape manuelle notée dans l'entrée précédente (« Validation manuelle QC001
  des charges patronales »). Résultat WebRAS transmis par l'opérateur.
- **Résultat** : OK — aucun écart.
- **Sortie WebRAS (retenues employé)** :
  - Impôt du Québec sur le revenu brut : **104,56 $**
  - Cotisation au RRQ (6,3 %) : **87,36 $**
  - Deuxième cotisation supplémentaire au RRQ (4 %) : **0,00 $**
  - Cotisation au RQAP (0,43 %) : **6,52 $**
- **Sortie WebRAS (cotisations employeur, période courante)** :
  - Cotisation au RRQ (6,3 %) : **87,36 $**
  - Deuxième cotisation supplémentaire au RRQ (4 %) : **0,00 $**
  - Cotisation au RQAP (0,602 %) : **9,13 $**
  - Cotisation au FSS (1,65 %) : **25,02 $**
- **Comparaison avec le moteur / la fixture `qc001.json`** :

| Poste | WebRAS | Moteur | Écart |
|---|---|---|---|
| Impôt QC (retenu) | 104,56 $ | 104,56 $ | 0 |
| RRQ employé | 87,36 $ | 87,36 $ | 0 |
| RRQ employé (2e cotisation supp.) | 0,00 $ | 0,00 $ (MSGA jamais atteint, hors périmètre) | 0 |
| RQAP employé | 6,52 $ | 6,52 $ | 0 |
| RRQ employeur | 87,36 $ | 87,36 $ | 0 |
| RQAP employeur | 9,13 $ | 9,13 $ | 0 |
| **FSS** | **25,02 $** | **25,02 $** | **0** |
- **Note CNESST** : WebRAS **ne calcule pas la CNESST** (absente de ses sorties,
  employeur comme employé) — correction par rapport à l'hypothèse de travail
  antérieure. La cotisation CNESST (16,98 $ pour QC001) reste donc validée
  exclusivement par calcul direct `0,0112 × Salaire_Assujetti` contre la
  décision de classification officielle (unité 57020, taux total 1,12 %), et
  non par WebRAS. Idem pour la CNT (0,91 $, calcul direct `0,0006 × brut`
  d'après la LE-39.0.2, ligne 35 — WebRAS ne la calcule pas non plus, cotisation
  annuelle hors sorties par paie).
- **Conclusion** : la ré-exécution WebRAS confirme au cent près toutes les
  valeurs qu'elle est en mesure de produire (impôt QC, RRQ employé/employeur,
  RQAP employé/employeur, FSS). Les charges CNESST et CNT, structurellement
  absentes de WebRAS, demeurent validées par calcul direct contre leurs sources
  officielles respectives (décision de classification CNESST ; LE-39.0.2
  (2026-01)). L'étape manuelle de revalidation WebRAS de QC001 est close.
- **Reste à faire (opérateur)** : archivage physique du PDF LE-39.0.2 (2026-01)
  dans `docs/sources-officielles/2026/` — la référence documentaire est déjà en
  place (`docs/sources-officielles.md`), seul le dépôt du fichier binaire reste
  à faire.
- **Fichiers modifiés** : `docs/journal-validation.md`.
