# Requirements Document

<!-- Titre métier : Document d'exigences — net-cumuls-registre. Les en-têtes
structurels de niveau supérieur (Requirements Document, Introduction, Glossary,
Requirements) et les libellés « Requirement N », « User Story: »,
« Acceptance Criteria » sont maintenus en anglais pour la conformité au format
Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec implémente **l'étape 6** du plan d'implémentation
(`docs/plan-implementation.md`), après `moteur-paie-contrats` (étape 1, socle
contractuel figé), `gains-bruts-vacances-hs` (étape 2, `calcul_gains`),
`cotisations-sociales-qc` (étape 3, RRQ/RQAP/AE employé et employeur),
`impots-retenues-source` (étape 4, impôt QC et fédéral) et
`charges-patronales` (étape 5, FSS/CNESST/CNT et
`assembler_cotisations_employeur`). Elle livre les deux derniers composants du
moteur de calcul avant le bulletin PDF et l'interface :

- **`payroll_engine/net_pay.py`** — l'**orchestrateur bout-en-bout** qui
  invoque, dans l'ordre, toutes les fonctions de calcul déjà livrées par les
  étapes 2 à 5, puis assemble le `PayrollResult` complet (retenues employé,
  cotisations employeur, net, coût employeur, cumuls YTD de fin de paie) ;
- **`payroll_engine/register.py`** — le **registre maître**, une persistance
  SQLite locale qui archive chaque paie de façon append-only, maintient une
  vue dénormalisée des cumuls YTD par employé et par année civile, et
  implémente l'annulation-remplacement (Req 6 de `moteur-paie-contrats`) par
  transaction atomique.

**Périmètre de cette spec** :

- une fonction d'orchestration unique dans `net_pay.py` qui produit un
  `PayrollResult` complet à partir d'un `PayrollInput` et des paramètres
  annuels, en **invoquant** (jamais en recalculant) `calcul_gains`,
  `calcul_rrq_employe`/`calcul_rrq_employeur`,
  `calcul_rqap_employe`/`calcul_rqap_employeur`,
  `calcul_ae_employe`/`calcul_ae_employeur`,
  `calcul_impot_qc_formule`/`calcul_impot_qc_retenu`,
  `calcul_impot_federal_formule`/`calcul_impot_federal_retenu` et
  `charges_patronales.assembler_cotisations_employeur` ;
- le schéma et les opérations du registre SQLite dans `register.py` :
  insertion append-only, lecture, annulation-remplacement, maintien de la vue
  dénormalisée des cumuls YTD ;
- la distinction entre **saison** (métadonnée informative du registre) et
  **année civile** (base exclusive des cumuls fiscaux et des plafonds,
  contrat déjà figé par `CumulsYTD`).

Sont explicitement **hors périmètre** :

- toute formule fiscale (RRQ, RQAP, AE, impôt QC, impôt fédéral, FSS, CNESST,
  CNT) — déjà livrées par les étapes 2 à 5, invoquées ici sans modification ;
- toute modification des modèles figés par `moteur-paie-contrats`
  (`PayrollResult`, `CumulsYTD`, `MontantAvecTrace`, `CalculationTrace`,
  `StatutDePaie`) — cette spec les **consomme**, elle ne les altère pas ;
- la génération du bulletin PDF (étape 7, `bulletin-pdf`) et l'interface
  Streamlit (étape 8, `interface-streamlit`), qui consommeront le registre
  maître livré ici.

**Décisions actées (confirmées par l'utilisateur en phase clarify)** :

1. **Portée de l'orchestrateur** — `net_pay.py` est un orchestrateur complet
   bout-en-bout : il invoque `calcul_gains`, les six fonctions RRQ/RQAP/AE
   employé et employeur, les quatre fonctions d'impôt QC/fédéral et
   `assembler_cotisations_employeur`, puis assemble lui-même le
   `PayrollResult` complet (net, coût employeur, cumuls de fin).
2. **Schéma du registre** — `register.py` (SQLite) expose une table `paies`
   append-only (chaque ligne porte un `PayrollResult` sérialisé en JSON) et
   une table dénormalisée `cumuls_ytd` indexée par `(employe_id,
   annee_civile)`, mise à jour à chaque insertion de paie de statut `EMISE`.
3. **Annulation-remplacement** — assurée par
   `remplacer_paie(ancien_id, nouveau_payroll_result)` : marque la ligne
   ancienne `REMPLACE_PAR` avec son `remplace_par_id`, insère la nouvelle
   version, recalcule `cumuls_ytd` (retrait de la contribution de l'ancienne
   paie, ajout de celle de la nouvelle), le tout dans une seule transaction
   SQLite atomique.
4. **Saison vs année civile** — `CumulsYTD` reste strictement basé sur
   `annee_civile` (contrat déjà figé par `moteur-paie-contrats`,
   `models/cumuls.py`). Le champ **`saison`** est une métadonnée purement
   informative attachée à chaque ligne du registre (ex. « Saison 2026 »), à
   des fins de rapport OBNL ; il n'a **aucun** effet sur les cumuls fiscaux ni
   sur les plafonds annuels, et n'est **pas** un champ du `PayrollResult`
   figé — c'est une colonne propre à la table `paies` du registre,
   fournie par l'appelant au moment de l'insertion.
5. **Résolution de la traçabilité de l'assemblage (règle 02)** — `net_pay.py`
   **n'invente aucune nouvelle `CalculationTrace`**. Le contrat figé
   `PayrollResult` expose `net` et `cout_employeur` comme des `Decimal`
   simples, sans champ de trace dédié (voir `models/payroll_result.py`) :
   ces deux montants sont des **agrégations arithmétiques exactes** de
   composantes déjà tracées (`gains.brut_total`,
   `retenues_employe.total_retenues_employe`,
   `cotisations_employeur.total_cotisations_employeur`), pas de nouveaux
   calculs fiscaux sourcés. `net_pay.py` **assemble** uniquement ; la
   traçabilité de chaque montant individuel reste portée par les
   `CalculationTrace` produites par les fonctions invoquées (règle 02
   toujours respectée, sans duplication ni trace superflue).
6. **Résolution de la dépendance circulaire `cumuls_fin`** — `PayrollResult`
   exige `cumuls_fin` comme champ obligatoire à la construction, mais
   `CumulsYTD.avec_paie` a besoin des montants de la paie courante pour
   produire ce même `cumuls_fin`. `net_pay.py` résout cette circularité en
   calculant d'abord toutes les sections (gains, retenues, cotisations, net,
   coût employeur), puis en invoquant `CumulsYTD.avec_paie` avec un objet
   intermédiaire exposant `employe_id`, `annee_fiscale` et les onze
   catégories monétaires de la paie courante (voir Requirement 6), et enfin
   en construisant le `PayrollResult` final, `cumuls_fin` inclus, en un seul
   appel `PayrollResult(...)`.

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire partout, y compris à la
  persistance SQLite (aucune colonne `REAL`, aucun `float` intermédiaire).
- Règle 02 — traçabilité des formules déjà portée par les fonctions
  invoquées ; `net_pay.py` n'ajoute aucune trace propre (décision n° 5).
- Règle 03 — `net_pay.py` et `register.py` ne réintroduisent aucun garde-fou
  de périmètre (déjà portés par `PayrollInput`) ; toute
  `UnsupportedPayrollCase` ou `MissingParameterError` levée par une fonction
  invoquée est **propagée** sans être interceptée ni remplacée.
- Règle 04 — aucune donnée personnelle réelle dans le dépôt ; la base SQLite
  de production réside hors dépôt (`%APPDATA%\CampLilySO\payroll.db`) ; les
  tests utilisent exclusivement des identifiants fictifs et une base
  temporaire ou en mémoire.
- Règle 05 — aucun taux, plafond ni constante fiscale codé en dur dans
  `net_pay.py` ou `register.py` ; les paramètres transitent exclusivement par
  `ParametresAnnee` injecté par l'appelant.
- Règle 06 — spec → tests (property + golden) → implémentation → validation ;
  tests écrits avant le code.

**Contrats consommés sans modification** (déjà figés par
`moteur-paie-contrats`, `cotisations-sociales-qc`, `impots-retenues-source`
et `charges-patronales`) :

- `models.payroll_input.PayrollInput`, `models.payroll_result.GainsDecomposes`,
  `MontantAvecTrace`, `RetenuesEmploye`, `CotisationsEmployeur`,
  `PayrollResult` — y compris ses trois invariants `model_validator` déjà
  vérifiés à la construction (identités comptables, biconditionnelle statut,
  cohérence `cumuls_fin`).
- `models.cumuls.CumulsYTD`, notamment `CumulsYTD.zero` et `CumulsYTD.avec_paie`.
- `models.trace.CalculationTrace`.
- `models.enums.StatutDePaie`, `models.enums.Juridiction`,
  `models.enums.ModeArrondissement`.
- `models.exceptions.PayrollDomainError`, `UnsupportedPayrollCase`,
  `MissingParameterError`.
- `payroll_engine.parameters_loader.ParametresAnnee`, `load_parameters`.
- `payroll_engine.gains_bruts.calcul_gains`.
- `payroll_engine.rrq.calcul_rrq_employe`, `calcul_rrq_employeur`.
- `payroll_engine.rqap.calcul_rqap_employe`, `calcul_rqap_employeur`.
- `payroll_engine.assurance_emploi.calcul_ae_employe`, `calcul_ae_employeur`.
- `payroll_engine.impot_qc.calcul_impot_qc_formule`, `calcul_impot_qc_retenu`.
- `payroll_engine.impot_federal.calcul_impot_federal_formule`,
  `calcul_impot_federal_retenu`.
- `payroll_engine.charges_patronales.assembler_cotisations_employeur`.

## Glossary

- **Moteur_Net_Cumuls_Registre** : l'ensemble formé par l'orchestrateur
  `net_pay.py` et le registre `register.py`, considéré comme un système
  unique aux fins de ce document.
- **Assemblage_De_Paie** : la fonction publique unique de `net_pay.py` qui
  invoque toutes les fonctions de calcul des étapes 2 à 5 et produit un
  `PayrollResult` complet et valide.
- **Registre_Maitre** : la couche de persistance SQLite locale (`register.py`)
  qui archive les paies et maintient les cumuls YTD dénormalisés.
- **Table_Paies** : la table SQLite append-only qui porte, pour chaque
  version de chaque paie, son `PayrollResult` sérialisé en JSON et ses
  colonnes d'indexation (`id_paie`, `employe_id`, `annee_fiscale`,
  `numero_periode`, `version`, `statut`, `remplace_par_id`, `saison`,
  `date_creation`, `date_emission`).
- **Table_Cumuls_YTD** : la table SQLite dénormalisée, une ligne par couple
  `(employe_id, annee_civile)`, portant les onze catégories monétaires de
  `CumulsYTD` sous forme de chaînes décimales.
- **Paie_Logique** : l'entité conceptuelle identifiée par le triplet
  `(employe_id, annee_fiscale, numero_periode)`, qui peut être portée par
  plusieurs lignes de la Table_Paies au fil des versions (une paie initiale
  `EMISE` puis, après annulation-remplacement, une ligne `REMPLACE_PAR` et
  une nouvelle ligne `EMISE` de version supérieure).
- **Saison** : métadonnée informative (ex. « 2026 ») attachée à chaque ligne
  de la Table_Paies au moment de l'insertion, distincte de l'année civile.
  N'entre dans **aucun** calcul fiscal, cumul ou plafond.
- **Annee_Civile** : `payroll_result.annee_fiscale` (alias
  `cumuls_fin.annee_civile`) — la seule base de rattachement des cumuls
  fiscaux et des plafonds annuels RRQ/RQAP/AE (contrat déjà figé).
- **Chemin_BD** : le chemin du fichier SQLite. En production,
  `%APPDATA%\CampLilySO\payroll.db` (hors dépôt, règle 04). Toute fonction du
  Registre_Maitre DOIT accepter ce chemin en paramètre injectable, avec ce
  chemin de production comme valeur par défaut, pour permettre l'injection
  d'un chemin temporaire ou d'une base en mémoire dans les tests.
- **Categories_CumulsYTD** : les onze catégories monétaires de `CumulsYTD`
  (brut, vacances, rrq_employe, rrq_employeur, rqap_employe,
  rqap_employeur, ae_employe, ae_employeur, impot_qc_retenu,
  impot_federal_retenu, net) — voir le mapping exact depuis `PayrollResult`
  au Requirement 6.
- **PayrollInput**, **GainsDecomposes**, **MontantAvecTrace**,
  **RetenuesEmploye**, **CotisationsEmployeur**, **PayrollResult**,
  **CumulsYTD**, **CalculationTrace**, **StatutDePaie**,
  **UnsupportedPayrollCase**, **MissingParameterError**, **ParametresAnnee** :
  contrats figés par les specs antérieures, consommés sans modification.

## Requirements

### Requirement 1: Point d'entrée unique de l'orchestrateur `net_pay.py`

**User Story:** En tant qu'appelant du moteur (interface future, tests
d'intégration), je veux un point d'entrée unique et typé qui produit un
`PayrollResult` complet à partir d'un `PayrollInput`, afin de ne jamais avoir
à orchestrer manuellement les fonctions de calcul des étapes 2 à 5.

#### Acceptance Criteria

1. LE Moteur_Net_Cumuls_Registre DOIT exposer, dans `payroll_engine/net_pay.py`,
   une fonction publique unique d'Assemblage_De_Paie de signature
   `(payroll_input: PayrollInput, parametres_annee: ParametresAnnee, id_paie: str, version: int, statut: StatutDePaie, date_creation: datetime, date_emission: datetime | None = None, remplace_par_id: str | None = None) -> PayrollResult`.
2. L'Assemblage_De_Paie DOIT être une **fonction pure** : deux appels
   successifs avec les mêmes arguments DOIVENT retourner deux `PayrollResult`
   égaux au sens `==`, sans état interne persistant, sans lecture ni écriture
   de fichier ou de base de données, et sans appel à `datetime.now()` ni à
   toute autre source de non-déterminisme (`id_paie`, `version`, `statut`,
   `date_creation`, `date_emission` et `remplace_par_id` sont fournis par
   l'appelant, jamais générés en interne).
3. L'Assemblage_De_Paie NE DOIT PAS invoquer directement `load_parameters` —
   les paramètres annuels DOIVENT être injectés par l'argument
   `parametres_annee`.
4. L'Assemblage_De_Paie NE DOIT PAS muter `payroll_input` ni
   `parametres_annee` (objets `frozen=True` par contrat).
5. L'Assemblage_De_Paie DOIT être importable sans effet de bord.

---

### Requirement 2: Invocation stricte des fonctions déjà livrées

**User Story:** En tant que responsable de la cohérence du moteur, je veux que
l'orchestrateur invoque exclusivement les fonctions de calcul déjà livrées et
validées par les étapes 2 à 5, afin qu'aucune formule fiscale ne soit
dupliquée ni recalculée de façon incohérente dans `net_pay.py`.

#### Acceptance Criteria

1. L'Assemblage_De_Paie DOIT obtenir `GainsDecomposes` en invoquant
   exclusivement `payroll_engine.gains_bruts.calcul_gains(payroll_input, parametres_annee)`,
   sans en recalculer aucune composante.
2. L'Assemblage_De_Paie DOIT obtenir les trois retenues sociales employé en
   invoquant exclusivement `calcul_rrq_employe`, `calcul_rqap_employe` et
   `calcul_ae_employe`, chacune avec `(payroll_input, gains, parametres_annee)`.
3. L'Assemblage_De_Paie DOIT obtenir les deux retenues d'impôt (formule et
   retenue effective, QC et fédérale) en invoquant exclusivement
   `calcul_impot_qc_formule`, `calcul_impot_qc_retenu`,
   `calcul_impot_federal_formule` et `calcul_impot_federal_retenu`, chacune
   avec `(payroll_input, gains, parametres_annee)`.
4. L'Assemblage_De_Paie DOIT obtenir `CotisationsEmployeur` complet (les six
   cotisations employeur, dont RRQ/RQAP/AE employeur) en invoquant
   exclusivement
   `payroll_engine.charges_patronales.assembler_cotisations_employeur(payroll_input, gains, parametres_annee)`,
   sans invoquer séparément `calcul_rrq_employeur`, `calcul_rqap_employeur`,
   `calcul_ae_employeur`, `calcul_fss`, `calcul_cnesst` ni `calcul_cnt` en
   dehors de cet appel unique.
5. L'Assemblage_De_Paie NE DOIT recalculer, dupliquer ni approximer aucune
   formule fiscale (RRQ, RQAP, AE, impôt QC, impôt fédéral, FSS, CNESST, CNT)
   par une logique propre à `net_pay.py`.
6. SI une fonction invoquée lève `MissingParameterError` ou
   `UnsupportedPayrollCase`, ALORS l'Assemblage_De_Paie DOIT propager cette
   exception sans l'intercepter, la masquer ni la reconvertir.

---

### Requirement 3: Assemblage des retenues employé (`RetenuesEmploye`)

**User Story:** En tant qu'orchestrateur du moteur, je veux assembler les sept
montants de retenue employé (RRQ, RQAP, AE, impôt QC formule/retenu, impôt
fédéral formule/retenu) en un `RetenuesEmploye` cohérent, afin que le
`PayrollResult` porte une décomposition complète et tracée des retenues.

#### Acceptance Criteria

1. L'Assemblage_De_Paie DOIT construire un `RetenuesEmploye` dont les champs
   `rrq`, `rqap`, `ae`, `impot_qc_formule`, `impot_qc_retenu`,
   `impot_federal_formule` et `impot_federal_retenu` portent chacun le
   `MontantAvecTrace` (montant + trace) issu de la fonction correspondante
   (Requirement 2).
2. L'Assemblage_De_Paie DOIT calculer `total_retenues_employe` comme la somme,
   au cent près, des cinq retenues **effectivement retenues** (RRQ + RQAP +
   AE + impôt QC retenu + impôt fédéral retenu), à l'exclusion des deux
   montants `*_formule`, conformément à l'invariant déjà porté par le contrat
   `RetenuesEmploye`.
3. L'Assemblage_De_Paie NE DOIT PAS recalculer `total_retenues_employe`
   autrement qu'en additionnant les cinq montants effectivement retenus.

---

### Requirement 4: Assemblage des cotisations employeur (`CotisationsEmployeur`)

**User Story:** En tant qu'orchestrateur du moteur, je veux obtenir l'agrégat
`CotisationsEmployeur` déjà produit par l'étape 5, afin que le
`PayrollResult` porte le coût employeur complet sans dépendance dupliquée.

#### Acceptance Criteria

1. L'Assemblage_De_Paie DOIT utiliser directement, comme champ
   `cotisations_employeur` du `PayrollResult`, l'objet `CotisationsEmployeur`
   retourné par `assembler_cotisations_employeur` (Requirement 2 AC4), sans
   en modifier aucun champ.
2. L'Assemblage_De_Paie NE DOIT PAS reconstruire ni cloner
   `CotisationsEmployeur` par assignation champ à champ.

---

### Requirement 5: Identités comptables — net et coût employeur

**User Story:** En tant que responsable de la paie, je veux que le salaire net
et le coût employeur soient calculés par simple arithmétique exacte à partir
des composantes déjà tracées, afin que les deux identités comptables du
contrat `PayrollResult` soient toujours satisfaites par construction.

#### Acceptance Criteria

1. L'Assemblage_De_Paie DOIT calculer `net` comme
   `gains.brut_total - retenues_employe.total_retenues_employe`, sans
   arrondissement supplémentaire (les deux opérandes sont déjà arrondis au
   cent par les fonctions invoquées).
2. L'Assemblage_De_Paie DOIT calculer `cout_employeur` comme
   `gains.brut_total + cotisations_employeur.total_cotisations_employeur`,
   sans arrondissement supplémentaire.
3. LE `net` et LE `cout_employeur` ainsi calculés DOIVENT satisfaire,
   sans écart, les deux invariants `model_validator` déjà portés par
   `PayrollResult` (identité brute Req 4.9, identité coût employeur Req 4.10
   de `moteur-paie-contrats`) — la construction du `PayrollResult` final
   (Requirement 7) DOIT réussir sans lever `ValidationError` pour ce motif
   sur toute entrée valide.
4. L'Assemblage_De_Paie NE DOIT introduire aucun `float` intermédiaire dans
   ce calcul (règle 01).

---

### Requirement 6: Calcul de `cumuls_fin` — mapping vers les onze catégories

**User Story:** En tant qu'orchestrateur du moteur, je veux calculer les
cumuls YTD de fin de paie à partir des cumuls de début et des montants de la
paie courante, afin que le `PayrollResult` porte un `cumuls_fin` cohérent et
monotone, sans dépendance circulaire avec sa propre construction.

#### Acceptance Criteria

1. L'Assemblage_De_Paie DOIT calculer `cumuls_fin` en invoquant
   `payroll_input.cumuls_debut.avec_paie(contribution_paie)`, où
   `contribution_paie` est un objet exposant au minimum `employe_id`,
   `annee_fiscale` et les onze Categories_CumulsYTD de la paie courante,
   construit et disponible **avant** l'assemblage final du `PayrollResult`
   (résolution de la dépendance circulaire, décision n° 6 de l'Introduction).
2. L'Assemblage_De_Paie DOIT dériver chacune des onze Categories_CumulsYTD de
   `contribution_paie` exactement comme suit, sans aucune autre source :
   - `brut` = `gains.brut_total` ;
   - `vacances` = `gains.vacances` ;
   - `rrq_employe` = `retenues_employe.rrq.montant` ;
   - `rrq_employeur` = `cotisations_employeur.rrq_employeur.montant` ;
   - `rqap_employe` = `retenues_employe.rqap.montant` ;
   - `rqap_employeur` = `cotisations_employeur.rqap_employeur.montant` ;
   - `ae_employe` = `retenues_employe.ae.montant` ;
   - `ae_employeur` = `cotisations_employeur.ae_employeur.montant` ;
   - `impot_qc_retenu` = `retenues_employe.impot_qc_retenu.montant` ;
   - `impot_federal_retenu` = `retenues_employe.impot_federal_retenu.montant` ;
   - `net` = `net` (Requirement 5 AC1).
3. `contribution_paie.employe_id` DOIT égaler `payroll_input.employee.id` et
   `contribution_paie.annee_fiscale` DOIT égaler
   `payroll_input.pay_period.annee_fiscale`.
4. SI `payroll_input.cumuls_debut.annee_civile` diffère de
   `payroll_input.pay_period.annee_fiscale`, ALORS l'Assemblage_De_Paie DOIT
   laisser `CumulsYTD.avec_paie` lever `PayrollDomainError` sans
   l'intercepter (comportement déjà porté par le contrat `CumulsYTD`, Req 7.6
   de `moteur-paie-contrats`).
5. LE `cumuls_fin` résultant DOIT satisfaire, pour chacune des onze
   catégories, `cumuls_fin.<categorie> >= cumuls_debut.<categorie>`
   (monotonie croissante, propriété déjà portée par `CumulsYTD.avec_paie`).

---

### Requirement 7: Construction complète et cohérente du `PayrollResult`

**User Story:** En tant qu'orchestrateur du moteur, je veux assembler en une
seule construction finale un `PayrollResult` complet incluant son cycle de
vie, afin que la sortie de `net_pay.py` soit directement persistable par le
registre maître sans étape de complétion supplémentaire.

#### Acceptance Criteria

1. L'Assemblage_De_Paie DOIT construire un unique `PayrollResult` portant :
   `id_paie`, `version`, `employe_id` (= `payroll_input.employee.id`),
   `annee_fiscale` (= `payroll_input.pay_period.annee_fiscale`),
   `pay_period` (= `payroll_input.pay_period`), `gains`, `retenues_employe`,
   `cotisations_employeur`, `net`, `cout_employeur`, `cumuls_fin`, `statut`,
   `remplace_par_id`, `date_creation`, `date_emission` — tous fournis ou
   calculés conformément aux Requirements 1 à 6.
2. `id_paie`, `version`, `statut`, `date_creation`, `date_emission` et
   `remplace_par_id` DOIVENT être ceux reçus en argument par
   l'Assemblage_De_Paie, sans modification ni valeur par défaut divergente.
3. LA construction du `PayrollResult` final DOIT réussir sans lever
   `ValidationError` pour toute combinaison d'arguments par ailleurs valide
   (Requirements 1 à 6 satisfaits) — en particulier les trois invariants déjà
   portés par le contrat (identités comptables, biconditionnelle statut, et
   cohérence `cumuls_fin`) sont satisfaits par construction.
4. L'Assemblage_De_Paie NE DOIT PAS construire le `PayrollResult` via
   `model_construct` ni contourner ses validateurs.

---

### Requirement 8: Traçabilité de l'assemblage (règle 02)

**User Story:** En tant que responsable de la conformité, je veux que la
décision de ne pas produire de trace propre à `net_pay.py` soit explicite et
vérifiable, afin que la règle 02 reste respectée sans duplication ni trace
superflue sur des agrégations purement arithmétiques.

#### Acceptance Criteria

1. L'Assemblage_De_Paie NE DOIT PAS construire de nouvelle
   `CalculationTrace` pour `net` ni pour `cout_employeur` (décision n° 5 de
   l'Introduction) — ces deux champs restent des `Decimal` simples,
   conformément au contrat `PayrollResult` déjà figé.
2. CHAQUE montant individuel exposé par `retenues_employe` et
   `cotisations_employeur` DOIT continuer à porter la `CalculationTrace`
   produite par la fonction qui l'a calculé (Requirements 3 et 4) — aucune
   trace n'est perdue, remplacée ni régénérée par l'Assemblage_De_Paie.
3. L'Assemblage_De_Paie NE DOIT PAS modifier le contenu d'une
   `CalculationTrace` reçue d'une fonction invoquée.

---

### Requirement 9: Schéma de la table `paies` du registre maître

**User Story:** En tant que responsable de la paie, je veux que chaque version
de chaque paie soit archivée de façon append-only dans une table SQLite
dédiée, afin de disposer d'une piste d'audit complète et immuable.

#### Acceptance Criteria

1. LE Registre_Maitre DOIT exposer une Table_Paies dont la clé primaire est
   `id_paie` (texte, unique), et qui porte au minimum les colonnes :
   `employe_id`, `annee_fiscale`, `numero_periode`, `saison`, `version`,
   `statut`, `remplace_par_id` (nullable), `date_creation`, `date_emission`
   (nullable), et `payload_json` (le `PayrollResult` complet sérialisé via
   `model_dump_json`).
2. TOUTE colonne monétaire dérivable du `payload_json` NE DOIT PAS être
   dupliquée sous forme numérique `REAL` dans la Table_Paies — la source de
   vérité des montants d'une paie individuelle reste exclusivement
   `payload_json` (règle 01, absence de `float`).
3. LA Table_Paies NE DOIT PAS autoriser la suppression d'une ligne
   (append-only) ; la seule mise à jour permise sur une ligne existante est
   la transition de cycle de vie décrite au Requirement 13 (passage de
   `statut='emise'` à `statut='remplace_par'` avec renseignement de
   `remplace_par_id`) — toute autre modification d'une ligne existante est
   interdite.
4. LA Table_Paies DOIT permettre de retrouver, pour une Paie_Logique donnée
   (`employe_id`, `annee_fiscale`, `numero_periode`), l'ensemble de ses
   versions ordonnées par `version` croissant.
5. LE champ `saison` DOIT être une chaîne fournie par l'appelant à
   l'insertion (Requirement 11), sans validation fiscale, sans effet sur
   `cumuls_ytd` (Requirement 14).

---

### Requirement 10: Schéma dénormalisé de la table `cumuls_ytd`

**User Story:** En tant que module de calcul futur (bulletin PDF, interface),
je veux consulter directement les cumuls YTD d'un employé pour une année
civile sans reconstruire l'historique complet de ses paies, afin d'obtenir une
réponse immédiate et cohérente.

#### Acceptance Criteria

1. LE Registre_Maitre DOIT exposer une Table_Cumuls_YTD dont la clé primaire
   composite est `(employe_id, annee_civile)`.
2. LA Table_Cumuls_YTD DOIT porter les onze Categories_CumulsYTD, chacune
   stockée comme chaîne décimale (colonne `TEXT`), jamais comme `REAL` ni
   `float` (règle 01).
3. POUR TOUT couple `(employe_id, annee_civile)` présent dans la
   Table_Cumuls_YTD, la ligne correspondante DOIT être reconstructible en un
   `CumulsYTD` valide via `CumulsYTD.model_validate(...)` sans passer par
   `float`.
4. L'ABSENCE d'une ligne pour un couple `(employe_id, annee_civile)` donné
   DOIT être interprétée par le Registre_Maitre comme équivalente à
   `CumulsYTD.zero(employe_id, annee_civile)`, sans lever d'exception à la
   lecture.

---

### Requirement 11: Insertion d'une paie et mise à jour des cumuls

**User Story:** En tant que responsable de la paie, je veux qu'insérer une
paie émise mette à jour atomiquement à la fois l'historique et les cumuls
dénormalisés, afin que les deux tables restent toujours cohérentes entre
elles.

#### Acceptance Criteria

1. LE Registre_Maitre DOIT exposer une fonction publique
   `inserer_paie(resultat: PayrollResult, saison: str, chemin_bd: ... = <chemin de production par défaut>) -> None`.
2. `inserer_paie` DOIT toujours insérer une nouvelle ligne dans la
   Table_Paies portant `resultat` sérialisé et `saison` fourni, quel que soit
   `resultat.statut`.
3. QUAND `resultat.statut` vaut `StatutDePaie.EMISE`, `inserer_paie` DOIT
   mettre à jour la Table_Cumuls_YTD pour `(resultat.employe_id,
   resultat.annee_fiscale)` en appliquant la contribution des onze
   Categories_CumulsYTD de `resultat` (mapping du Requirement 6 AC2) au
   cumul dénormalisé existant (ou à `CumulsYTD.zero` si absent), par simple
   addition catégorie par catégorie.
4. QUAND `resultat.statut` est différent de `StatutDePaie.EMISE`
   (`BROUILLON`, `ANNULEE`, `REMPLACE_PAR`), `inserer_paie` NE DOIT PAS
   modifier la Table_Cumuls_YTD.
5. L'insertion de la ligne dans la Table_Paies et, le cas échéant, la mise à
   jour de la Table_Cumuls_YTD DOIVENT s'exécuter dans une seule transaction
   SQLite atomique : soit les deux effets sont appliqués, soit aucun.
6. SI `resultat.id_paie` existe déjà dans la Table_Paies, ALORS
   `inserer_paie` DOIT refuser l'insertion (contrainte d'unicité de clé
   primaire) sans corrompre l'état existant.

---

### Requirement 12: Lecture du registre maître

**User Story:** En tant que futur module consommateur (bulletin PDF,
interface Streamlit), je veux lire une paie, l'historique d'une paie logique
ou les cumuls d'un employé, afin d'afficher ou d'exporter ces informations
sans dépendre de la structure interne du registre.

#### Acceptance Criteria

1. LE Registre_Maitre DOIT exposer `lire_paie(id_paie: str, ...) -> PayrollResult`
   qui retourne le `PayrollResult` désérialisé depuis `payload_json` pour la
   ligne dont la clé primaire est `id_paie`.
2. SI `id_paie` n'existe pas dans la Table_Paies, ALORS `lire_paie` DOIT
   lever une exception explicite (par exemple `KeyError` ou équivalent
   documenté) identifiant `id_paie` recherché.
3. LE Registre_Maitre DOIT exposer
   `lire_historique_paie(employe_id: str, annee_fiscale: int, numero_periode: int, ...) -> tuple[PayrollResult, ...]`
   qui retourne toutes les versions d'une Paie_Logique donnée, ordonnées par
   `version` croissant.
4. LE Registre_Maitre DOIT exposer
   `lire_cumuls_ytd(employe_id: str, annee_civile: int, ...) -> CumulsYTD`
   qui retourne le cumul dénormalisé correspondant, ou
   `CumulsYTD.zero(employe_id, annee_civile)` si aucune ligne n'existe
   (Requirement 10 AC4).
5. TOUTE fonction de lecture DOIT désérialiser les montants exclusivement via
   `Decimal` (jamais via `float`), y compris lors du parsing de
   `payload_json` (règle 01).
6. TOUTE fonction de lecture DOIT accepter un `chemin_bd` injectable, avec le
   chemin de production par défaut (cohérent avec Requirement 15).

---

### Requirement 13: Annulation-remplacement (`remplacer_paie`)

**User Story:** En tant que responsable de la paie, je veux corriger une paie
émise par annulation-remplacement plutôt que par modification directe, afin
de préserver la piste d'audit complète exigée par les Normes du travail et par
Revenu Québec.

#### Acceptance Criteria

1. LE Registre_Maitre DOIT exposer une fonction publique
   `remplacer_paie(ancien_id: str, nouveau_resultat: PayrollResult, saison: str, ...) -> None`.
2. `remplacer_paie` DOIT lire la ligne existante `ancien_id` ; SI cette ligne
   n'existe pas ou si son `statut` n'est pas `StatutDePaie.EMISE`, ALORS
   `remplacer_paie` DOIT refuser l'opération avec une exception explicite,
   sans modifier la Table_Paies ni la Table_Cumuls_YTD.
3. SI `nouveau_resultat.statut` n'est pas `StatutDePaie.REMPLACE_PAR`... — la
   ligne **ancienne** est celle marquée `REMPLACE_PAR` par `remplacer_paie`
   lui-même (AC4) ; `nouveau_resultat` DOIT porter un statut parmi
   `{StatutDePaie.EMISE, StatutDePaie.BROUILLON}` et `remplacer_paie` DOIT
   refuser toute autre valeur de `nouveau_resultat.statut` avec une
   exception explicite.
4. `remplacer_paie` DOIT, dans une seule transaction SQLite atomique :
   a. Mettre à jour la ligne `ancien_id` : `statut` passe à
      `StatutDePaie.REMPLACE_PAR` et `remplace_par_id` prend la valeur
      `nouveau_resultat.id_paie` — cette mise à jour est la seule mutation
      autorisée par le Requirement 9 AC3 ;
   b. Insérer une nouvelle ligne pour `nouveau_resultat` (même mécanisme que
      `inserer_paie`, Requirement 11) ;
   c. Recalculer la Table_Cumuls_YTD pour `(employe_id, annee_civile)`
      concerné en retirant la contribution de l'ancienne version (lue depuis
      `payload_json` avant sa mise à jour, mapping du Requirement 6 AC2) et
      en ajoutant celle de `nouveau_resultat`, catégorie par catégorie
      (`valeur_actuelle - contribution_ancienne + contribution_nouvelle`).
5. SI l'ancienne ligne avait `statut = StatutDePaie.EMISE` et que
   `nouveau_resultat.statut` vaut `StatutDePaie.BROUILLON`, ALORS l'étape 4c
   DOIT uniquement retirer la contribution de l'ancienne version (aucun ajout
   tant que la nouvelle version n'est pas elle-même émise).
6. TOUTE erreur survenant pendant l'une des trois étapes de l'AC4 DOIT
   annuler l'intégralité de la transaction (aucune mutation partielle
   visible), la Table_Paies et la Table_Cumuls_YTD restant dans leur état
   antérieur à l'appel.
7. `remplacer_paie` NE DOIT JAMAIS supprimer ni réécrire les champs
   monétaires substantiels de la ligne `ancien_id` (gains, retenues,
   cotisations, net, coût employeur) — seuls `statut` et `remplace_par_id`
   changent dans le `payload_json` mis à jour de cette ligne.

---

### Requirement 14: Distinction saison / année civile

**User Story:** En tant que responsable administratif du Camp LilySO, je veux
que le concept de saison (usage OBNL, rapports internes) reste totalement
séparé de l'année civile qui gouverne les cumuls fiscaux, afin qu'aucune
confusion entre les deux ne puisse jamais fausser un plafond RRQ, RQAP ou AE.

#### Acceptance Criteria

1. LE Registre_Maitre DOIT traiter `saison` comme une chaîne opaque, fournie
   par l'appelant à `inserer_paie` et `remplacer_paie`, sans validation de
   format imposée par cette spec.
2. LE Registre_Maitre NE DOIT JAMAIS utiliser `saison` comme clé de
   regroupement, de filtrage ou de calcul pour la Table_Cumuls_YTD — cette
   dernière reste exclusivement indexée par `(employe_id, annee_civile)`
   (Requirement 10 AC1).
3. L'Assemblage_De_Paie (`net_pay.py`) NE DOIT recevoir ni consommer aucun
   paramètre `saison` — cette métadonnée n'existe qu'au niveau du
   Registre_Maitre, jamais dans le calcul du `PayrollResult`.
4. QUAND deux paies de la même Paie_Logique portent des valeurs `saison`
   différentes entre l'ancienne et la nouvelle version (Requirement 13),
   `remplacer_paie` DOIT accepter cette différence sans erreur — `saison`
   n'entre dans aucun invariant de cohérence entre versions.

---

### Requirement 15: Emplacement, configuration et sécurité de la base (règle 04)

**User Story:** En tant que responsable de la conformité, je veux que la base
SQLite de production ne puisse jamais se retrouver dans le dépôt Git, et que
les tests n'utilisent jamais de données personnelles réelles, afin de
respecter strictement la règle 04.

#### Acceptance Criteria

1. TOUTE fonction publique du Registre_Maitre (`inserer_paie`, `lire_paie`,
   `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie`) DOIT accepter
   un paramètre `chemin_bd` optionnel ; SA valeur par défaut DOIT être le
   chemin de production `%APPDATA%\CampLilySO\payroll.db` (ou équivalent
   multiplateforme documenté), jamais un chemin situé sous le dépôt versionné.
2. LE Registre_Maitre DOIT permettre l'injection d'un `chemin_bd` de test
   (fichier temporaire ou base SQLite en mémoire `:memory:`), afin que la
   suite de tests ne crée jamais de fichier `*.db` dans l'arbre versionné.
3. UN test de garde DOIT vérifier qu'aucun fichier correspondant au motif
   `*.db`, `*.sqlite` ou `*.sqlite3` n'est présent dans l'arbre versionné
   après exécution complète de la suite de tests du Registre_Maitre.
4. TOUT identifiant `employe_id` utilisé dans les tests, fixtures ou exemples
   du Registre_Maitre DOIT être fictif (convention `EMP0XX`), conformément
   au corpus golden QC001–QC006 déjà en usage dans le dépôt.
5. LE Registre_Maitre NE DOIT stocker, dans `payload_json` ou ailleurs, aucun
   champ apparenté à une donnée sensible au sens de la règle 04 (NAS, compte
   bancaire, adresse, courriel ou téléphone personnel) — garantie déjà
   transitivement assurée par le refus de tels champs au niveau d'`Employee`
   (`moteur-paie-contrats`), non redoublée ici.

---

### Requirement 16: Invariants comptables et propriétés testables (property-based testing)

**User Story:** En tant qu'ingénieur qualité, je veux que les invariants
comptables et de cohérence du registre soient vérifiés sur un large éventail
d'entrées générées, afin de détecter tout cas limite que le corpus golden ne
couvre pas.

#### Acceptance Criteria

1. POUR TOUTE entrée valide assemblée par l'Assemblage_De_Paie, l'identité
   comptable `gains.brut_total == net + retenues_employe.total_retenues_employe`
   DOIT être vérifiée (identité déjà portée par le contrat `PayrollResult`,
   re-vérifiée ici au niveau de l'orchestration).
2. POUR TOUTE entrée valide assemblée par l'Assemblage_De_Paie, l'identité
   `cout_employeur == gains.brut_total + cotisations_employeur.total_cotisations_employeur`
   DOIT être vérifiée.
3. POUR TOUTE séquence ordonnée de *n* paies `EMISE` d'un même employé pour
   une même année civile, insérées une à une via `inserer_paie` dans cet
   ordre, le cumul `Table_Cumuls_YTD` résultant DOIT égaler, catégorie par
   catégorie, la somme des contributions (mapping du Requirement 6 AC2) des
   *n* paies (propriété « cumul YTD de *n* paies = somme des paies 1..*n* »).
4. POUR TOUTE paie `EMISE` remplacée par `remplacer_paie` (Requirement 13),
   le cumul `Table_Cumuls_YTD` résultant DOIT être **identique** à celui
   qui aurait été obtenu si seule la nouvelle version avait été insérée
   depuis le début à la place de l'ancienne (propriété d'idempotence de
   substitution).
5. POUR TOUTE paie assemblée puis relue via `lire_paie` après
   `inserer_paie`, LE `PayrollResult` relu DOIT être strictement égal (`==`)
   au `PayrollResult` original assemblé (round-trip sans perte,
   règle 01 — aucun `float` introduit par la sérialisation ou la lecture).
6. POUR TOUTE ligne existante de la Table_Paies, aucune fonction du
   Registre_Maitre autre que `remplacer_paie` (et uniquement selon
   Requirement 13 AC4a) NE DOIT modifier `payload_json`, `statut` ou
   `remplace_par_id` d'une ligne déjà insérée (propriété d'immutabilité).
7. POUR TOUTE entrée valide, deux appels successifs de l'Assemblage_De_Paie
   avec les mêmes arguments DOIVENT produire des `PayrollResult` égaux
   (déterminisme, Requirement 1 AC2).
8. POUR TOUTE entrée valide, aucun montant assemblé, sérialisé ou lu par le
   Moteur_Net_Cumuls_Registre NE DOIT être de type `float` (règle 01).

---

### Requirement 17: Périmètre Camp LilySO et propagation des exceptions (règle 03)

**User Story:** En tant que responsable de la conformité, je veux que
l'orchestrateur et le registre ne réinventent aucun garde-fou de périmètre et
propagent fidèlement les refus déjà portés par les couches amont, afin
d'éviter toute divergence entre les points de contrôle du moteur.

#### Acceptance Criteria

1. LE Moteur_Net_Cumuls_Registre DOIT s'appuyer exclusivement sur les
   garde-fous de périmètre déjà portés par `PayrollInput` (province Québec,
   fréquence aux deux semaines, taux de vacances supporté, etc.) et par les
   fonctions de calcul invoquées, et NE DOIT PAS les redoubler.
2. LE Moteur_Net_Cumuls_Registre NE DOIT lever une nouvelle
   `UnsupportedPayrollCase` que si un cas hors matrice strictement propre à
   l'orchestration ou à la persistance apparaît (par exemple, un
   `nouveau_resultat.statut` non permis au Requirement 13 AC3) — un tel cas
   nouveau DOIT être documenté dans `docs/cas-non-supportes.md` avant
   activation, conformément à la règle 03.
3. SI une fonction invoquée par l'Assemblage_De_Paie (Requirement 2) lève
   `MissingParameterError` ou `UnsupportedPayrollCase`, ALORS cette
   exception DOIT être visible au consommateur exactement comme levée,
   sans encapsulation dans une autre exception ni conversion en valeur de
   retour.
4. LE Registre_Maitre DOIT reproduire au cent près, pour chacun des six
   scénarios `QC001` à `QC006` assemblés via l'Assemblage_De_Paie puis
   insérés via `inserer_paie`, les valeurs `net`, `cout_employeur` et
   `cumuls_fin` déjà validées par le corpus golden existant
   (`tests/fixtures/outputs/qc0XX.json`).
