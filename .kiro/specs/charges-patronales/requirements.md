# Requirements Document

<!-- Titre métier : Document d'exigences — charges-patronales. Les en-têtes
structurels de niveau supérieur (Requirements Document, Introduction, Glossary,
Requirements) et les libellés « Requirement N », « User Story: »,
« Acceptance Criteria » sont maintenus en anglais pour la conformité au format
Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec implémente **l'étape 5** du plan d'implémentation
(`docs/plan-implementation.md`), après `moteur-paie-contrats` (étape 1, socle
contractuel figé), `gains-bruts-vacances-hs` (étape 2, `calcul_gains`),
`cotisations-sociales-qc` (étape 3, RRQ/RQAP/AE employé et employeur) et
`impots-retenues-source` (étape 4, impôt QC et fédéral). Elle définit et impose
les fonctions pures de calcul des **charges patronales** du Camp LilySO, c'est-à-dire
les cotisations assumées par l'employeur, ainsi que leur **agrégation** dans
l'objet `CotisationsEmployeur` :

- **FSS** — Fonds des services de santé (Revenu Québec) ;
- **CNESST** — cotisation à la Commission des normes, de l'équité, de la santé
  et de la sécurité du travail ;
- **CNT** — cotisation relative aux normes du travail (formulaire LE-39.0.2).

Ces trois charges, combinées aux cotisations employeur RRQ/RQAP/AE déjà livrées
à l'étape 3, alimentent l'agrégat déjà figé
`models.payroll_result.CotisationsEmployeur` (six `MontantAvecTrace` + le
drapeau `cnesst_en_attente_classification` + `total_cotisations_employeur`), et
participent à `cout_employeur` du `PayrollResult`.

**Périmètre de cette spec** :

- les trois fonctions de calcul `calcul_fss`, `calcul_cnesst`, `calcul_cnt`,
  chacune retournant `tuple[Decimal, CalculationTrace]` (règle 02) ;
- une fonction d'**assemblage** produisant `CotisationsEmployeur` complet, qui
  **invoque** (sans les recalculer) les fonctions employeur RRQ/RQAP/AE de
  l'étape 3 et les trois nouvelles fonctions de charges, et calcule
  `total_cotisations_employeur`.

Sont explicitement **hors périmètre** :

- le **recalcul** du RRQ, du RQAP ou de l'AE employeur (étape 3,
  `cotisations-sociales-qc`, déjà livrés) — l'assemblage les invoque uniquement ;
- l'assemblage du `PayrollResult` complet, `net`, le champ `cout_employeur`
  lui-même et les cumuls YTD (étape 6, `net-cumuls-registre`). Cette spec
  **spécifie** la relation `cout_employeur = brut + total_cotisations_employeur`
  (Requirement 9) sans construire le `PayrollResult`.

**Décisions actées (confirmées par l'utilisateur en phase requirements)** :

1. **Portée de l'assemblage** — cette spec livre les trois fonctions de calcul
   **et** l'assemblage de `CotisationsEmployeur` (agrégation des six cotisations
   employeur, dont RRQ/RQAP/AE employeur invoqués depuis l'étape 3).
2. **Modélisation de la CNT** — la CNT est calculée **par paie** comme
   `Taux_CNT × Salaire_Assujetti`, où `Taux_CNT = 0,0006` (0,06 %) lu du
   formulaire officiel **LE-39.0.2 (2026-01)**, ligne 35. La CNT est légalement
   une cotisation annuelle (payée avec le sommaire RLZ-1.ST) ; sa répartition
   par paie au taux 0,06 % reproduit exactement la charge annuelle tant que le
   maximum par employé n'est pas atteint (décision n° 4). Les fixtures
   QC001–QC006, qui portaient `cnt = 0,00 $`, **seront régénérées** pour porter
   la CNT calculée (Requirement 11).
3. **FSS — taux unique** — usage du taux unique
   `taux_camp_lilyso_2026 = 0,0165` ; la table
   `table_taux_par_masse_salariale` reste hors périmètre (`TO_FILL`). Le premier
   seuil de changement de taux FSS est à une masse salariale de 1 M$, jamais
   atteinte par le Camp LilySO.
4. **Plafond annuel CNESST et CNT** — aucun plafond annuel n'est appliqué : le
   maximum de salaire assujetti (CNESST comme CNT : 103 000 $ par employé pour
   2026) n'est jamais atteint au Camp LilySO. Traité hors périmètre au même
   titre que la deuxième cotisation supplémentaire RRQ (MSGA) à l'étape 3.
5. **Attribution de source (règle 02)** — les sources incorrectes des fixtures
   sont **corrigées** :
   - FSS → `TP-1015.F <année>, section 5 — FSS` (inchangé, sur liste blanche) ;
   - CNESST → une **URL officielle `www.cnesst.gouv.qc.ca`** (déjà admise par la
     liste blanche `.gouv.qc.ca`) plutôt que `TP-1015.F` ;
   - CNT → **`LE-39.0.2 <année>`** (source réelle du taux). Cette source **n'est
     pas encore sur la liste blanche** de `CalculationTrace` : son ajout est une
     dépendance de contrat (Requirement 5 AC7).
   Les fixtures QC001–QC006 seront régénérées en conséquence.
6. **Nom du module** — `payroll_engine/charges_patronales.py` (convention
   francophone, cohérente avec `impot_qc.py` / `impot_federal.py` /
   `assurance_emploi.py`), au lieu de `employer_contributions.py` du plan. Cette
   déviation sera reflétée dans `docs/plan-implementation.md`.

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire, `float` interdit.
- Règle 02 — chaque fonction retourne `tuple[Decimal, CalculationTrace]` avec
  source officielle sur la liste blanche de `CalculationTrace`.
- Règle 03 — cas hors matrice Camp LilySO → `UnsupportedPayrollCase` (garde-fous
  d'entrée déjà portés par `PayrollInput`, non redoublés ici, Requirement 7).
- Règle 04 — aucune donnée personnelle réelle ; corpus anonymisé QC001–QC006.
- Règle 05 — tous les taux, bases et masses proviennent exclusivement de
  `parameters/<AAAA>/quebec.json` ; aucune valeur en dur dans le code Python.
- Règle 06 — spec → tests (property + golden) → implémentation → validation ;
  tests écrits avant le code.

**Contrats consommés sans modification** (déjà figés par `moteur-paie-contrats`) :

- `models.payroll_input.PayrollInput` — porte notamment
  `pay_period.annee_fiscale`, `pay_period.nb_periodes_annuelles` et
  `cumuls_debut` (lu par les fonctions employeur RRQ/RQAP/AE lors de l'assemblage).
- `models.payroll_result.GainsDecomposes` — produit par `calcul_gains`
  (étape 2) ; son champ `brut_total` est la seule source du salaire assujetti.
- `models.payroll_result.MontantAvecTrace`, `CotisationsEmployeur` — produits
  par cette spec (assemblage).
- `models.trace.CalculationTrace` — contrat de trace (règle 02). Voir
  Requirement 5 AC7 : la liste blanche de sources devra être étendue pour
  admettre `LE-39.0.2`.
- `models.exceptions.MissingParameterError`, `UnsupportedPayrollCase`.
- `payroll_engine.parameters_loader.ParametresAnnee`, `FSSParametres`,
  `CNESSTParametres`, `CNTParametres`.
- `payroll_engine.rrq.calcul_rrq_employeur`,
  `payroll_engine.rqap.calcul_rqap_employeur`,
  `payroll_engine.assurance_emploi.calcul_ae_employeur` — fonctions employeur de
  l'étape 3, invoquées telles quelles par l'assemblage.

## Glossary

- **Moteur_Charges_Patronales** : l'ensemble des trois fonctions de calcul
  (FSS, CNESST, CNT) et de la fonction d'assemblage livrées par cette spec,
  considéré comme un système unique aux fins de ce document.
- **FSS** : Fonds des services de santé — cotisation employeur perçue par
  Revenu Québec, calculée sur le salaire assujetti selon un taux fonction de la
  masse salariale annuelle de l'employeur.
- **CNESST** : cotisation à la Commission des normes, de l'équité, de la santé
  et de la sécurité du travail, calculée sur le salaire assujetti au taux total
  de la classification (unité) attribuée à l'employeur.
- **CNT** : cotisation relative aux normes du travail (formulaire LE-39.0.2),
  perçue par Revenu Québec au taux de 0,06 % de la rémunération assujettie.
- **Salaire_Assujetti** : `gains.brut_total` — la seule source du salaire de
  période consommé par cette spec (même décision de périmètre que
  `cotisations-sociales-qc` et `impots-retenues-source`).
- **Taux_FSS** : `parametres_annee.fss.taux_camp_lilyso_2026` (0,0165 pour
  2026) — taux FSS unique appliqué au Camp LilySO.
- **Masse_Salariale_Annuelle_Employeur** :
  `parametres_annee.fss.masse_salariale_utilisee_webras_2026` (14 861,60 $ pour
  2026) — valeur documentaire portée dans la trace FSS ; justifie le choix du
  Taux_FSS mais n'entre pas dans le calcul du montant de période.
- **Table_Taux_FSS** : `parametres_annee.fss.table_taux_par_masse_salariale`
  (`"TO_FILL"`) — table des taux FSS par tranche de masse salariale. **Hors
  périmètre** (décision n° 3).
- **Taux_Total_CNESST** : `parametres_annee.cnesst.taux_total` (0,0112 pour
  2026 = CNI 0,90 % + unité 0,22 %).
- **Unite_CNESST** : `parametres_annee.cnesst.unite` (« 57020 » pour 2026).
- **En_Attente_Classification_CNESST** :
  `parametres_annee.cnesst.en_attente_classification` (`bool`, `false` pour
  2026). Reporté tel quel dans
  `CotisationsEmployeur.cnesst_en_attente_classification` (Requirement 9).
- **Taux_CNT** : `parametres_annee.cnt.taux` (à renseigner à `0,0006` d'après
  LE-39.0.2 (2026-01), ligne 35 — voir Requirement 12).
- **Base_Admissible_CNT** : `parametres_annee.cnt.base_admissible` — maximum de
  rémunération assujettie par employé (103 000 $ pour 2026, LE-39.0.2 ligne 29).
  **Jamais atteinte** au Camp LilySO (décision n° 4).
- **Nb_Periodes_Annuelles** : `payroll_input.pay_period.nb_periodes_annuelles`
  (27 pour 2026).
- **Mode_Arrondissement** : `ROUND_HALF_UP` à deux décimales, cohérent avec les
  autres modules du moteur et confirmé par WebRAS.
- **CotisationsEmployeur** : agrégat figé (`moteur-paie-contrats`) portant les
  six cotisations employeur (`rrq_employeur`, `rqap_employeur`, `ae_employeur`,
  `fss`, `cnesst`, `cnt`), le drapeau `cnesst_en_attente_classification` et
  `total_cotisations_employeur`.
- **Corpus_Golden** : les six scénarios QC001–QC006 (`tests/fixtures/inputs/` et
  `tests/fixtures/outputs/`).
- **PayrollInput**, **GainsDecomposes**, **CalculationTrace**,
  **MontantAvecTrace**, **ParametresAnnee**, **FSSParametres**,
  **CNESSTParametres**, **CNTParametres**, **UnsupportedPayrollCase**,
  **MissingParameterError** : contrats figés par `moteur-paie-contrats`.

## Requirements

### Requirement 1: Points d'entrée uniques et signatures imposées

**User Story:** En tant qu'orchestrateur du moteur de paie, je veux trois
fonctions publiques et typées, une par charge patronale, plus une fonction
d'assemblage, afin que chaque charge soit calculable indépendamment, testable
en isolation, et que l'agrégat employeur soit produit de façon reproductible et
auditable.

#### Acceptance Criteria

1. LE Moteur_Charges_Patronales DOIT exposer, dans
   `payroll_engine/charges_patronales.py`, trois fonctions publiques
   `calcul_fss`, `calcul_cnesst` et `calcul_cnt`, chacune de signature
   `(payroll_input: PayrollInput, gains: GainsDecomposes, parametres_annee: ParametresAnnee) -> tuple[Decimal, CalculationTrace]`.
2. LE Moteur_Charges_Patronales DOIT exposer, dans le même module, une fonction
   publique d'assemblage de signature
   `(payroll_input: PayrollInput, gains: GainsDecomposes, parametres_annee: ParametresAnnee) -> CotisationsEmployeur`.
3. CHACUNE des fonctions DOIT être une **fonction pure** : deux appels
   successifs avec les mêmes arguments DOIVENT retourner deux résultats égaux au
   sens `==`, sans état interne persistant, sans lecture ou écriture de fichier,
   sans variable de module mutable et sans appel à `datetime.now()` ni à toute
   autre source de non-déterminisme.
4. CHACUNE des fonctions NE DOIT PAS invoquer directement `load_parameters` —
   les paramètres DOIVENT être injectés par l'argument `parametres_annee`.
5. CHACUNE des trois fonctions de calcul DOIT lire le Salaire_Assujetti
   exclusivement depuis `gains.brut_total`, sans en dériver une valeur
   différente et sans lire `payroll_input` pour cette valeur.
6. CHACUNE des fonctions NE DOIT PAS muter `payroll_input`, `gains` ni
   `parametres_annee` (objets `frozen=True` par contrat).
7. CHACUNE des fonctions DOIT être importable sans effet de bord.
8. IF une section de paramètres requise (`parametres_annee.fss`,
   `parametres_annee.cnesst` ou `parametres_annee.cnt`) est absente (`None`),
   THEN LE Moteur_Charges_Patronales DOIT lever `MissingParameterError` avec un
   message actionnable identifiant la section manquante.

---

### Requirement 2: Calcul de la cotisation FSS

**User Story:** En tant que responsable de la paie, je veux que la cotisation
au Fonds des services de santé soit calculée sur le salaire assujetti au taux
FSS applicable au Camp LilySO, afin que la charge FSS soit exacte au cent près
par rapport à WebRAS.

#### Acceptance Criteria

1. LE Moteur_Charges_Patronales DOIT calculer la cotisation FSS de période comme
   `Taux_FSS × Salaire_Assujetti`.
2. LE Moteur_Charges_Patronales DOIT arrondir la cotisation FSS selon le
   Mode_Arrondissement (voir Requirement 8).
3. LE Moteur_Charges_Patronales DOIT lire le Taux_FSS exclusivement depuis
   `parametres_annee.fss.taux_camp_lilyso_2026` (règle 05).
4. LE montant FSS retourné par `calcul_fss` NE DOIT jamais être strictement
   négatif.
5. WHEN le Salaire_Assujetti est égal à `Decimal("0.00")`, THE
   Moteur_Charges_Patronales SHALL retourner `Decimal("0.00")` comme cotisation
   FSS, sans lever d'exception.
6. LE Moteur_Charges_Patronales NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
7. LE Moteur_Charges_Patronales NE DOIT PAS consulter la Table_Taux_FSS ni
   sélectionner un taux en fonction de la Masse_Salariale_Annuelle_Employeur —
   le taux appliqué est exclusivement le Taux_FSS unique (décision n° 3).

---

### Requirement 3: Calcul de la cotisation CNESST

**User Story:** En tant que responsable de la paie, je veux que la cotisation
CNESST soit calculée sur le salaire assujetti au taux total de la classification
confirmée du Camp LilySO, afin que la charge CNESST soit exacte au cent près par
rapport à WebRAS.

#### Acceptance Criteria

1. LE Moteur_Charges_Patronales DOIT calculer la cotisation CNESST de période
   comme `Taux_Total_CNESST × Salaire_Assujetti`.
2. LE Moteur_Charges_Patronales DOIT arrondir la cotisation CNESST selon le
   Mode_Arrondissement (voir Requirement 8).
3. LE Moteur_Charges_Patronales DOIT lire le Taux_Total_CNESST exclusivement
   depuis `parametres_annee.cnesst.taux_total` (règle 05).
4. LE montant CNESST retourné par `calcul_cnesst` NE DOIT jamais être
   strictement négatif.
5. WHEN le Salaire_Assujetti est égal à `Decimal("0.00")`, THE
   Moteur_Charges_Patronales SHALL retourner `Decimal("0.00")` comme cotisation
   CNESST, sans lever d'exception.
6. LE Moteur_Charges_Patronales NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
7. LE Moteur_Charges_Patronales NE DOIT PAS appliquer de plafond annuel de
   salaire assujetti CNESST (maximum 103 000 $ par employé pour 2026, jamais
   atteint — décision n° 4).
8. WHERE `En_Attente_Classification_CNESST` vaut `true`, LE
   Moteur_Charges_Patronales DOIT tout de même produire une cotisation CNESST
   calculée avec le Taux_Total_CNESST disponible (taux provisoire) — le drapeau
   signale un ajustement rétroactif possible mais n'annule pas le calcul.

---

### Requirement 4: Calcul de la cotisation CNT

**User Story:** En tant que responsable de la paie, je veux que la cotisation
relative aux normes du travail soit calculée par paie au taux officiel de la
LE-39.0.2, afin de répartir la charge annuelle CNT du Camp LilySO sur les paies
de façon tracée et sans valeur codée en dur.

#### Acceptance Criteria

1. LE Moteur_Charges_Patronales DOIT calculer la cotisation CNT de période comme
   `Taux_CNT × Salaire_Assujetti`.
2. LE Moteur_Charges_Patronales DOIT arrondir la cotisation CNT selon le
   Mode_Arrondissement (voir Requirement 8).
3. LE Moteur_Charges_Patronales DOIT lire le Taux_CNT exclusivement depuis
   `parametres_annee.cnt.taux` (règle 05), dont la valeur officielle 2026 est
   `0,0006` (LE-39.0.2 (2026-01), ligne 35).
4. LE montant CNT retourné par `calcul_cnt` NE DOIT jamais être strictement
   négatif.
5. WHEN le Salaire_Assujetti est égal à `Decimal("0.00")`, THE
   Moteur_Charges_Patronales SHALL retourner `Decimal("0.00")` comme cotisation
   CNT, sans lever d'exception.
6. LE Moteur_Charges_Patronales NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
7. LE Moteur_Charges_Patronales NE DOIT PAS appliquer de plafond de
   Base_Admissible_CNT (maximum 103 000 $ par employé pour 2026, jamais atteint
   — décision n° 4) ; le paramètre `base_admissible` est renseigné à des fins
   documentaires et de trace, sans être appliqué comme plafond de calcul.

---

### Requirement 5: Traçabilité de chaque charge patronale (règle 02)

**User Story:** En tant que responsable de la conformité, je veux que chaque
charge patronale calculée soit accompagnée d'une trace exhaustive référençant sa
source officielle exacte, afin qu'un montant contesté puisse être reconstruit
trois ans plus tard.

#### Acceptance Criteria

1. CHACUNE des trois fonctions de calcul DOIT retourner une `CalculationTrace`
   conforme au contrat figé (source sur liste blanche, année, juridiction,
   section, `parametres_utilises`, `entrees`, `sous_totaux`,
   `mode_arrondissement`, `precision_arrondissement`, `resultat`).
2. LA trace FSS DOIT porter la source `"TP-1015.F <année>, section 5 — FSS"` et
   exposer, dans `parametres_utilises`, le Taux_FSS, et dans `entrees`, le
   Salaire_Assujetti et la Masse_Salariale_Annuelle_Employeur.
3. LA trace CNESST DOIT porter une source officielle CNESST sur le domaine
   `www.cnesst.gouv.qc.ca` (admise par la liste blanche `.gouv.qc.ca`), exposer
   le Taux_Total_CNESST et l'Unite_CNESST dans `parametres_utilises`, et le
   Salaire_Assujetti dans `entrees`.
4. LA trace CNT DOIT porter la source `"LE-39.0.2 <année>"`, exposer le Taux_CNT
   (et la Base_Admissible_CNT à titre documentaire) dans `parametres_utilises`,
   et le Salaire_Assujetti dans `entrees`.
5. LE champ `resultat` de chaque trace DOIT être égal au montant `Decimal`
   retourné par la fonction correspondante (cohérence trace ↔ montant).
6. LE champ `annee` de chaque trace DOIT être égal à
   `payroll_input.pay_period.annee_fiscale`, `mode_arrondissement` DOIT valoir
   `ROUND_HALF_UP` et `precision_arrondissement` DOIT valoir `2`.
7. LA liste blanche des sources officielles de `models.trace.CalculationTrace`
   DOIT être étendue pour admettre le motif `LE-39.0.2 <année>` avant que la
   trace CNT (AC4) ne soit valide ; cet ajout DOIT être documenté dans
   `docs/sources-officielles.md` (règle 02). L'attribution incorrecte
   `TP-1015.F ... — CNESST` / `TP-1015.F ... — CNT` des fixtures d'origine NE
   DOIT PAS être conservée.

---

### Requirement 6: Assemblage de CotisationsEmployeur

**User Story:** En tant qu'orchestrateur du moteur, je veux une fonction qui
assemble les six cotisations employeur en un objet `CotisationsEmployeur`
cohérent, afin que l'étape 6 dispose d'un agrégat employeur prêt à intégrer au
`PayrollResult`.

#### Acceptance Criteria

1. LA fonction d'assemblage DOIT invoquer `calcul_rrq_employeur`,
   `calcul_rqap_employeur` et `calcul_ae_employeur` (étape 3) pour obtenir les
   trois cotisations sociales employeur, sans les recalculer indépendamment.
2. LA fonction d'assemblage DOIT invoquer `calcul_fss`, `calcul_cnesst` et
   `calcul_cnt` pour obtenir les trois charges patronales.
3. LA fonction d'assemblage DOIT construire un `CotisationsEmployeur` dont les
   champs `rrq_employeur`, `rqap_employeur`, `ae_employeur`, `fss`, `cnesst`,
   `cnt` portent chacun le `MontantAvecTrace` (montant + trace) issu de la
   fonction correspondante.
4. LA fonction d'assemblage DOIT renseigner
   `cnesst_en_attente_classification` avec la valeur
   `En_Attente_Classification_CNESST` lue depuis les paramètres.
5. LA fonction d'assemblage DOIT calculer `total_cotisations_employeur` comme la
   somme, au cent près, des six montants de cotisation ; cette somme DOIT
   satisfaire l'invariant déjà porté par le contrat `CotisationsEmployeur`.
6. LA fonction d'assemblage DOIT être une fonction pure (Requirement 1 AC3) et
   NE DOIT muter aucun de ses arguments.
7. IF une fonction invoquée lève `MissingParameterError`, THEN la fonction
   d'assemblage DOIT propager cette exception sans la masquer.

---

### Requirement 7: Périmètre Camp LilySO (règle 03)

**User Story:** En tant que responsable de la conformité, je veux que le moteur
refuse tout cas hors matrice Camp LilySO plutôt que d'inventer un traitement,
afin de garantir l'exactitude fiscale.

#### Acceptance Criteria

1. LE Moteur_Charges_Patronales DOIT s'appuyer sur les garde-fous d'entrée déjà
   portés par `PayrollInput` (province Québec, fréquence aux deux semaines,
   etc.) et NE DOIT PAS les redoubler.
2. LE Moteur_Charges_Patronales NE DOIT PAS appliquer de plafond annuel de
   salaire assujetti pour la CNESST ni pour la CNT — les rémunérations du Camp
   LilySO restent bien en deçà du maximum de 103 000 $ par employé, cas traité
   hors périmètre au même titre que la deuxième cotisation supplémentaire RRQ
   (MSGA) à l'étape 3 (décision n° 4).
3. WHERE une extension future du périmètre exige un plafond annuel CNESST/CNT ou
   une table FSS par masse salariale, LE Moteur_Charges_Patronales DOIT être
   documenté dans `docs/cas-non-supportes.md` et accompagné d'un golden test
   dédié avant activation (règle 03).

---

### Requirement 8: Arrondissement et précision monétaire (règle 01)

**User Story:** En tant que responsable de la paie, je veux que chaque charge
patronale soit arrondie exactement comme WebRAS, afin de garantir l'égalité au
cent près.

#### Acceptance Criteria

1. LE Moteur_Charges_Patronales DOIT arrondir chaque montant final (FSS, CNESST,
   CNT) au cent avec le mode `ROUND_HALF_UP` et une précision de 2 décimales.
2. LE Moteur_Charges_Patronales DOIT conserver toutes les valeurs intermédiaires
   en `Decimal` pleine précision jusqu'à l'arrondissement final.
3. LE Moteur_Charges_Patronales NE DOIT jamais produire, retourner ou stocker de
   valeur de type `float` (règle 01).
4. LE mode et la précision d'arrondissement appliqués DOIVENT être consignés dans
   la trace de chaque charge (`mode_arrondissement`, `precision_arrondissement`).

---

### Requirement 9: Relation avec cout_employeur

**User Story:** En tant qu'orchestrateur du moteur, je veux que la relation entre
l'agrégat employeur et le coût employeur soit spécifiée sans ambiguïté, afin que
l'étape 6 puisse assembler le `PayrollResult` de façon cohérente.

#### Acceptance Criteria

1. LE `total_cotisations_employeur` produit par l'assemblage (Requirement 6)
   DOIT égaler, au cent près, la somme des six cotisations employeur
   (RRQ employeur + RQAP employeur + AE employeur + FSS + CNESST + CNT).
2. LE `cout_employeur` du `PayrollResult` DOIT égaler, au cent près,
   `gains.brut_total + total_cotisations_employeur` — invariant déjà porté par
   le contrat `PayrollResult`, dont la vérification effective relève de
   l'étape 6.
3. LE drapeau `cnesst_en_attente_classification` NE DOIT PAS modifier le
   `total_cotisations_employeur` : `cnesst.montant` (même provisoire) est
   toujours inclus dans la somme.

---

### Requirement 10: Invariants de correction (property-based testing)

**User Story:** En tant qu'ingénieur qualité, je veux que les propriétés
générales des charges patronales soient vérifiées sur un large éventail
d'entrées, afin de détecter les cas limites que le corpus golden ne couvre pas.

#### Acceptance Criteria

1. FOR ALL Salaire_Assujetti `>= 0`, chacune des trois cotisations (FSS, CNESST,
   CNT) DOIT être `>= 0` (non-négativité).
2. FOR ALL Salaire_Assujetti `>= 0`, chacune des trois cotisations DOIT être
   monotone croissante par rapport au Salaire_Assujetti (à taux fixé).
3. FOR ALL Salaire_Assujetti `>= 0`, chaque cotisation DOIT être égale à
   l'arrondi de `taux × Salaire_Assujetti`, avec un écart au montant théorique
   borné par un demi-cent (propriété d'arrondissement).
4. FOR ALL entrées valides, deux appels successifs de la même fonction avec les
   mêmes arguments DOIVENT produire des résultats égaux (déterminisme).
5. FOR ALL entrées valides, aucun montant retourné (calcul ou assemblage) NE
   DOIT être de type `float` (règle 01).
6. FOR ALL entrées valides, `total_cotisations_employeur` de l'assemblage DOIT
   égaler la somme des six `montant` (identité d'agrégation, Requirement 9 AC1).

---

### Requirement 11: Reproduction et régénération du corpus golden QC001–QC006

**User Story:** En tant que responsable de la validation, je veux que les
fonctions reproduisent au cent près les charges patronales des fixtures, et que
les fixtures soient régénérées là où elles portaient des valeurs ou des sources
incorrectes, afin de garantir la cohérence avec les sources officielles.

#### Acceptance Criteria

1. FOR ALL scénario du Corpus_Golden, `calcul_fss` DOIT reproduire au cent près
   la valeur `cotisations_employeur.fss.montant` de la fixture de sortie.
2. FOR ALL scénario du Corpus_Golden, `calcul_cnesst` DOIT reproduire au cent
   près la valeur `cotisations_employeur.cnesst.montant`, et
   `En_Attente_Classification_CNESST` DOIT égaler
   `cotisations_employeur.cnesst_en_attente_classification`.
3. FOR ALL scénario du Corpus_Golden, `calcul_cnt` DOIT reproduire au cent près
   la valeur `cotisations_employeur.cnt.montant`.
4. LES fixtures QC001–QC006 DOIVENT être régénérées pour porter (a) la CNT
   calculée au taux `0,0006` au lieu de `0,00`, (b) les sources corrigées CNESST
   (`www.cnesst.gouv.qc.ca`) et CNT (`LE-39.0.2`), et (c) les valeurs recalculées
   de `total_cotisations_employeur` et `cout_employeur` qui en découlent.
5. LA régénération des fixtures (AC4) DOIT préserver l'exactitude au cent près
   par rapport à WebRAS pour les charges vérifiables dans WebRAS (FSS, CNESST) ;
   la CNT, absente de WebRAS par paie, DOIT être validée contre le calcul
   `0,0006 × Salaire_Assujetti` de la LE-39.0.2.
6. LES golden tests des AC1 à AC3 NE PEUVENT être déclarés exécutables qu'après
   complétion des paramètres requis (Requirement 12).

---

### Requirement 12: Complétude des paramètres avant exécution des golden tests

**User Story:** En tant que mainteneur, je veux que toute valeur non trouvable
dans les guides archivés soit remplacée par une valeur officielle sourcée avant
l'exécution des golden tests, afin de respecter les règles 02 et 05.

#### Acceptance Criteria

1. AVANT l'exécution des golden tests (Requirement 11), les paramètres
   `parametres_annee.cnt.taux` et `parametres_annee.cnt.base_admissible`
   DOIVENT être renseignés (`taux = "0.0006"`, `base_admissible = "103000.00"`
   d'après LE-39.0.2 (2026-01), lignes 35 et 29), sans sentinelle `"TO_FILL"`.
2. LA section `cnt` de `parameters/2026/quebec.json` DOIT porter sa source
   officielle (`LE-39.0.2 (2026-01)`) et sa date de consultation (règle 05).
3. LE guide LE-39.0.2 (2026-01) archivé dans `docs/sources-officielles/2026/`
   DOIT être référencé dans `docs/sources-officielles.md`, et la liste blanche
   de `CalculationTrace` DOIT admettre `LE-39.0.2` (Requirement 5 AC7).
4. LES paramètres FSS (`taux_camp_lilyso_2026`) et CNESST (`taux_total`,
   `en_attente_classification`), déjà renseignés et validés, NE DOIVENT PAS être
   modifiés par cette spec.
5. IF une valeur requise n'est pas trouvable dans les guides déjà archivés dans
   `docs/sources-officielles/2026/`, THEN une source officielle additionnelle
   DOIT être déposée dans ce répertoire et référencée dans
   `docs/sources-officielles.md` avant que la valeur ne soit utilisée.
