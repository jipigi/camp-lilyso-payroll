# Requirements Document

<!-- Titre métier : Document d'exigences — cotisations-sociales-qc. Les en-têtes structurels de niveau supérieur (Requirements Document, Introduction, Glossary, Requirements) et les libellés « Requirement N », « User Story: », « Acceptance Criteria » sont maintenus en anglais pour la conformité au format Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec implémente **l'étape 3** du plan d'implémentation
(`docs/plan-implementation.md`), immédiatement après `moteur-paie-contrats`
(étape 1, socle contractuel figé, 605 tests) et `gains-bruts-vacances-hs`
(étape 2, fonction `calcul_gains`, 649 tests). Elle définit et impose les
six fonctions pures de calcul des trois cotisations sociales à taux fixe
plafonné du Camp LilySO :

- **RRQ** (Régime de rentes du Québec) — cotisation employé et employeur,
  avec exemption générale annuelle répartie par période et plafond annuel
  (assiette bornée par le MGA via le plafond de cotisation) ;
- **RQAP** (Régime québécois d'assurance parentale) — cotisation employé
  et employeur, taux et plafonds distincts pour chaque partie ;
- **AE** (Assurance-emploi, taux Québec) — cotisation employé et
  cotisation employeur dérivée par un multiplicateur (1,4), chacune
  plafonnée annuellement.

Ces trois cotisations sont regroupées dans une seule spec parce qu'elles
partagent la même forme structurelle : un taux appliqué à un salaire
admissible, borné par un plafond annuel consommé via un cumul YTD reçu en
entrée. Le Requirement 1 fixe précisément, pour chacune des six fonctions,
la formule et la nature exacte de cette parenté et de ses écarts (RRQ
employeur ne recalcule rien ; RQAP employeur a son propre taux et son
propre plafond ; AE employeur est dérivée du montant employé effectif).

**Périmètre strict** : seules les six cotisations RRQ/RQAP/AE (employé et
employeur) et leur trace sont couvertes. Sont explicitement **hors
périmètre** de cette spec :

- l'impôt du Québec et l'impôt fédéral (étape 4, `impots-retenues-source`) ;
- le FSS, la CNESST et la CNT (étape 5, `charges-patronales`) ;
- l'assemblage du `PayrollResult` complet, la mise à jour du `CumulsYTD`
  après paie (via `CumulsYTD.avec_paie`) et le registre maître (étape 6,
  `net-cumuls-registre`) ;
- la **deuxième cotisation supplémentaire au RRQ** (« RRQ2 », taux 4 %
  entre le MGA et le MSGA) — voir Requirement 8.

**Contrats consommés sans modification** (déjà figés par
`moteur-paie-contrats`) :

- `models.payroll_input.PayrollInput` — porte notamment `cumuls_debut:
  CumulsYTD`, dont les six catégories `rrq_employe`, `rrq_employeur`,
  `rqap_employe`, `rqap_employeur`, `ae_employe`, `ae_employeur` sont
  consommées par cette spec comme cumul de début de période.
- `models.payroll_result.GainsDecomposes` — produit par `calcul_gains`
  (étape 2) ; son champ `brut_total` est la seule source du salaire
  admissible consommé par cette spec (voir Requirement 1, décision de
  périmètre).
- `models.payroll_result.MontantAvecTrace`, `RetenuesEmploye`,
  `CotisationsEmployeur` — les six montants produits par cette spec
  alimenteront in fine les champs `rrq`, `rqap`, `ae`, `rrq_employeur`,
  `rqap_employeur`, `ae_employeur` de ces agrégats (assemblage réalisé par
  l'étape 6, pas par cette spec).
- `models.trace.CalculationTrace` — contrat de trace imposé par la
  règle 02.
- `models.exceptions.UnsupportedPayrollCase`, `MissingParameterError`.
- `payroll_engine.parameters_loader.ParametresAnnee`, `RRQParametres`,
  `RQAPParametres`, `AEParametres` — déjà typés et matérialisés (properties
  qui lèvent `MissingParameterError` sur `"TO_FILL"`).

**Décision de périmètre — salaire admissible unique** : compte tenu de la
matrice Camp LilySO (règle 03 : rémunération strictement horaire, heures
supplémentaires, indemnité de vacances et jours fériés manuels — aucune
commission, boni, pourboire ni avantage imposable), le salaire admissible
au sens du RRQ (« gains ouvrant droit à pension »), le salaire assurable
au sens du RQAP et le salaire assurable au sens de l'AE sont **tous les
trois égaux à `GainsDecomposes.brut_total`**. Aucune exclusion de gains
n'est appliquée par cette spec. Cette équivalence est directement
confirmée par les entrées PDOC du scénario QC001
(`docs/scenario-qc001.md`, table « PDOC — Information supplémentaire ») :
« Gains ouvrant droit à pension pour la période » et « Gains assurables
pour la période » valent tous deux 1 516,32 $, soit le brut total exact.

**Décision de conception — signature des fonctions** : les six fonctions
de cette spec suivent le même patron que `calcul_gains` (étape 2) plutôt
que la signature illustrative à arguments scalaires esquissée dans
`docs/scenario-qc001.md` (rédigée avant que les contrats `PayrollInput` /
`ParametresAnnee` ne soient figés). Chaque fonction reçoit le
`PayrollInput` complet (pour `cumuls_debut`), le `GainsDecomposes` produit
par l'étape 2 (pour `brut_total`) et le `ParametresAnnee` (pour la section
fiscale pertinente), et retourne `tuple[Decimal, CalculationTrace]`
conformément à la règle 02. Voir Requirement 1 pour le détail exact par
fonction.

**Décision de conception — noms de modules** : cette spec livre
`payroll_engine/rrq.py`, `payroll_engine/rqap.py` et
`payroll_engine/assurance_emploi.py`. Ce dernier nom diffère du nom
`ei.py` mentionné dans `docs/plan-implementation.md` (étape 3) : le nom
`assurance_emploi.py` est préféré pour rester cohérent avec le champ
`ae` / la classe `AEParametres` déjà utilisés partout ailleurs dans le
contrat (`RetenuesEmploye.ae`, `CotisationsEmployeur.ae_employeur`,
`CumulsYTD.ae_employe`). Cette déviation mineure du plan sera reflétée
dans `docs/plan-implementation.md` à l'issue de la revue de cette spec.

**Décision de résolution — anomalie QC004 (RQAP employeur, 1,77 $ vs
1,78 $)** : cette spec retient **1,77 $** comme valeur de référence pour
le scénario QC004 (déjà la valeur présente dans
`tests/fixtures/outputs/qc004.json`), obtenue par calcul **indépendant**
du taux employeur RQAP sur le salaire admissible brut
(`294,84 × 0,602 % = 1,7749 $` → `1,77 $` après arrondissement
`ROUND_HALF_UP`). La valeur de 1,78 $ présente dans l'Excel source du
corpus s'explique très probablement par un calcul erroné dérivant le
montant employeur du montant employé **déjà arrondi**
(`1,27 $ × 1,4 = 1,778 $` → `1,78 $`), une méthode incorrecte au regard du
TP-1015.F : le RQAP employeur a son propre taux et se calcule
indépendamment du montant employé, contrairement à l'AE employeur qui,
lui, se dérive bel et bien du montant employé (voir Requirement 5 et
Requirement 7 pour la distinction explicite entre ces deux mécanismes).
Cette décision sera consignée dans `docs/journal-validation.md` à
l'issue de l'implémentation, avec ré-exécution WebRAS si une divergence
apparaît lors des tests golden.

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire, `float` interdit.
- Règle 02 — chaque fonction retourne `tuple[Decimal, CalculationTrace]`
  avec source officielle sur la liste blanche de `CalculationTrace`.
- Règle 03 — cas hors matrice déjà refusés par `PayrollInput` ; cette
  spec ne redouble pas ces garde-fous (voir Requirement 9) mais introduit
  un refus spécifique pour le cas RRQ2 hors périmètre (Requirement 8).
- Règle 04 — aucune donnée personnelle réelle ; corpus anonymisé
  QC001–QC006 uniquement.
- Règle 05 — tous les taux, exemptions et plafonds proviennent
  exclusivement de `parameters/<AAAA>/quebec.json` et
  `parameters/<AAAA>/canada.json` ; aucune valeur en dur dans le code
  Python.
- Règle 06 — spec → tests (property + golden) → implémentation →
  validation ; tests écrits avant code.

**Corpus de validation** : les six scénarios QC001–QC006 documentés dans
`docs/scenario-qc0*.md` et `docs/journal-validation.md` doivent être
reproduits **au cent près** sur les sections `rrq`, `rqap`, `ae`,
`rrq_employeur`, `rqap_employeur`, `ae_employeur` de leurs fixtures de
sortie (`tests/fixtures/outputs/qc0*.json`, déjà renseignées pour ces six
champs). Tous les scénarios du corpus sont des paies n° 1 de la saison
(`cumul_ytd` de départ nul pour les six catégories) — le corpus actuel ne
valide donc pas directement le comportement de plafonnement en cours de
saison (cumul non nul) ; ce comportement est néanmoins spécifié par cette
spec (Requirement 2 à 7) et couvert par des tests de propriété plutôt que
par le corpus golden.

## Glossary

- **Moteur_Cotisations** : l'ensemble des six fonctions de calcul livrées
  par cette spec, considéré comme un système unique aux fins de ce
  document.
- **Salaire_Admissible** : base de calcul commune aux trois cotisations,
  égale à `GainsDecomposes.brut_total` (voir décision de périmètre
  ci-dessus). Utilisé indifféremment pour désigner le « salaire
  admissible » (RRQ), le « salaire assurable » (RQAP) et le « salaire
  assurable » (AE) — ces trois notions désignent la même valeur dans le
  périmètre Camp LilySO.
- **RRQ** : Régime de rentes du Québec.
- **RQAP** : Régime québécois d'assurance parentale.
- **AE** : Assurance-emploi, taux applicable aux résidents du Québec.
- **Exemption_Par_Periode_RRQ** : montant soustrait du Salaire_Admissible
  avant application du taux RRQ, lu directement depuis
  `parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026` (une
  valeur déjà pré-calculée et versionnée par année dans le fichier de
  paramètres — le Moteur_Cotisations ne la recalcule **jamais** par
  division de `exemption_generale_annuelle` par le nombre de périodes,
  ce qui éviterait de devoir spécifier une règle d'arrondissement
  supplémentaire pour cette division).
- **Assiette_Cotisable_RRQ** : `max(Decimal("0.00"), Salaire_Admissible −
  Exemption_Par_Periode_RRQ)`.
- **Cumul_YTD_RRQ_Employe**, **Cumul_YTD_RRQ_Employeur**,
  **Cumul_YTD_RQAP_Employe**, **Cumul_YTD_RQAP_Employeur**,
  **Cumul_YTD_AE_Employe**, **Cumul_YTD_AE_Employeur** : les six champs
  correspondants de `payroll_input.cumuls_debut` (`CumulsYTD`), lus en
  entrée par le Moteur_Cotisations. Cette spec **consomme** ces valeurs
  sans jamais les muter ni retourner de `CumulsYTD` mis à jour — cette
  responsabilité relève de l'étape 6 (`net-cumuls-registre`).
- **Plafond_Annuel_RRQ_Employe** : `parametres_annee.rrq.
  cotisation_max_annuelle_employe`. Aucun plafond distinct n'existe pour
  l'employeur RRQ (voir Requirement 3).
- **Plafond_Annuel_RQAP_Employe** / **Plafond_Annuel_RQAP_Employeur** :
  `parametres_annee.rqap.cotisation_max_employe` /
  `cotisation_max_employeur`.
- **Plafond_Annuel_AE_Employe** / **Plafond_Annuel_AE_Employeur** :
  `parametres_annee.assurance_emploi.cotisation_max_employe` /
  `cotisation_max_employeur`.
- **RRQ2** / **Deuxieme_Cotisation_Supplementaire** : la deuxième
  cotisation supplémentaire au RRQ (taux 4 % sur les gains admissibles
  entre le MGA et le MSGA). Explicitement **hors périmètre** de cette
  spec (Requirement 8).
- **Mode_Arrondissement_Cotisations** : `ROUND_HALF_UP` à deux décimales,
  cohérent avec le TP-1015.F et le T4127 2026.
- **Corpus_Golden** : les six scénarios QC001–QC006 documentés dans
  `docs/scenario-qc0*.md`, matérialisés dans `tests/fixtures/inputs/` et
  `tests/fixtures/outputs/`.
- **TP-1015.F** : formulaire/guide de retenues à la source publié par
  Revenu Québec, source des formules RRQ et RQAP.
- **T4127** : guide de calcul des retenues sur la paie publié par l'ARC,
  source de la formule AE (taux Québec).
- **PayrollInput**, **GainsDecomposes**, **CalculationTrace**,
  **CumulsYTD**, **ParametresAnnee**, **RRQParametres**,
  **RQAPParametres**, **AEParametres**, **UnsupportedPayrollCase**,
  **MissingParameterError** : contrats figés par `moteur-paie-contrats`,
  consommés sans modification par cette spec.

## Requirements

<!-- Chaque « Requirement N » ci-dessous est une exigence métier rédigée en français. -->

### Requirement 1: Points d'entrée uniques et signatures imposées

**User Story:** En tant qu'orchestrateur du moteur de paie, je veux six
fonctions publiques et typées, une par cotisation et par partie
(employé/employeur), afin que le calcul de chaque cotisation sociale soit
reproductible indépendamment, testable en isolation, et retourne
systématiquement une trace auditable.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT exposer, dans `payroll_engine/rrq.py`, deux
   fonctions publiques `calcul_rrq_employe` et `calcul_rrq_employeur`,
   chacune de signature
   `(payroll_input: PayrollInput, gains: GainsDecomposes, parametres_annee: ParametresAnnee) -> tuple[Decimal, CalculationTrace]`.
2. LE Moteur_Cotisations DOIT exposer, dans `payroll_engine/rqap.py`, deux
   fonctions publiques `calcul_rqap_employe` et `calcul_rqap_employeur`,
   de même signature que l'AC1.
3. LE Moteur_Cotisations DOIT exposer, dans
   `payroll_engine/assurance_emploi.py`, deux fonctions publiques
   `calcul_ae_employe` et `calcul_ae_employeur`, de même signature que
   l'AC1.
4. CHACUNE des six fonctions DOIT être une **fonction pure** : deux
   appels successifs avec les mêmes arguments DOIVENT retourner deux
   tuples égaux au sens `==`, sans état interne persistant, sans lecture
   ou écriture de fichier, sans variable de module mutable et sans appel
   à `datetime.now()` ni à toute autre source de non-déterminisme.
5. CHACUNE des six fonctions NE DOIT PAS invoquer directement
   `load_parameters` — les paramètres DOIVENT être injectés par
   l'argument `parametres_annee`.
6. CHACUNE des six fonctions DOIT lire le Salaire_Admissible
   exclusivement depuis `gains.brut_total`, sans en dériver une valeur
   différente et sans lire `payroll_input` pour cette valeur (voir la
   décision de périmètre de l'Introduction).
7. CHACUNE des six fonctions DOIT lire le cumul YTD pertinent
   exclusivement depuis le champ correspondant de
   `payroll_input.cumuls_debut` (`CumulsYTD`), listé dans le Glossary.
8. CHACUNE des six fonctions NE DOIT PAS muter `payroll_input`,
   `gains`, `parametres_annee` ni `payroll_input.cumuls_debut` — ces
   objets sont `frozen=True` par contrat et cette spec ne retourne
   jamais de `CumulsYTD` mis à jour.
9. CHACUNE des six fonctions NE DOIT PAS lever d'exception non
   documentée. LES seules exceptions autorisées sont
   `MissingParameterError` (règle 05, Requirement 6) et
   `pydantic.ValidationError` propagée par une construction interne de
   `CalculationTrace` invalide (cas de bug interne, pas un cas métier
   attendu).
10. CHACUNE des six fonctions DOIT être importable sans effet de bord
    (aucune action au moment de l'import).

---

### Requirement 2: Calcul de la cotisation RRQ employé

**User Story:** En tant que responsable de la paie, je veux que la
cotisation RRQ employé applique l'exemption par période puis le taux en
vigueur, plafonnée par le cumul déjà retenu sur l'année, afin que le
montant retenu soit exact au cent près et jamais supérieur au maximum
annuel légal.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT calculer l'Assiette_Cotisable_RRQ comme
   `max(Decimal("0.00"), Salaire_Admissible − Exemption_Par_Periode_RRQ)`.
2. LE Moteur_Cotisations DOIT calculer un montant théorique de période
   `montant_periode = taux_cotisation_totale_employe × Assiette_Cotisable_RRQ`,
   arrondi selon le Mode_Arrondissement_Cotisations (voir Requirement 9).
3. LE Moteur_Cotisations DOIT calculer la marge disponible
   `marge_disponible = max(Decimal("0.00"), Plafond_Annuel_RRQ_Employe −
   Cumul_YTD_RRQ_Employe)`.
4. LE Moteur_Cotisations DOIT retourner comme cotisation RRQ employé
   effective `min(montant_periode, marge_disponible)`.
5. LORSQUE `Salaire_Admissible ≤ Exemption_Par_Periode_RRQ`, LE
   Moteur_Cotisations DOIT retourner une cotisation RRQ employé égale à
   `Decimal("0.00")` sans lever d'exception.
6. LORSQUE `Cumul_YTD_RRQ_Employe ≥ Plafond_Annuel_RRQ_Employe`, LE
   Moteur_Cotisations DOIT retourner une cotisation RRQ employé égale à
   `Decimal("0.00")` sans lever d'exception, quel que soit le
   Salaire_Admissible de la période.
7. LE Moteur_Cotisations NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
8. LA cotisation RRQ employé retournée DOIT toujours satisfaire
   `Decimal("0.00") ≤ cotisation ≤ montant_periode` et
   `Cumul_YTD_RRQ_Employe + cotisation ≤ Plafond_Annuel_RRQ_Employe`.

---

### Requirement 3: Calcul de la cotisation RRQ employeur

**User Story:** En tant que responsable de la paie, je veux que la
cotisation RRQ employeur soit strictement égale à la cotisation
effectivement retenue à l'employé pour la même période, conformément au
TP-1015.F qui ne prévoit aucune formule distincte pour l'employeur, afin
que les deux montants restent cohérents sans jamais diverger.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT calculer la cotisation RRQ employeur comme
   strictement égale au montant retourné par `calcul_rrq_employe` invoqué
   avec les mêmes arguments `payroll_input`, `gains`, `parametres_annee`.
2. LE Moteur_Cotisations NE DOIT PAS appliquer de plafond, de cumul ou de
   taux distinct pour l'employeur RRQ — il n'existe aucun champ
   `cotisation_max_annuelle_employeur` dans `RRQParametres` et cette
   fonction NE DOIT PAS en supposer l'existence.
3. LA CalculationTrace retournée par `calcul_rrq_employeur` DOIT citer
   explicitement, dans son champ `section`, que la cotisation employeur
   est égale à la cotisation employé (absence de formule distincte), en
   cohérence avec le TP-1015.F 2026, section 3.2.
4. LE Moteur_Cotisations NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).

---

### Requirement 4: Calcul de la cotisation RQAP employé

**User Story:** En tant que responsable de la paie, je veux que la
cotisation RQAP employé applique le taux employé au salaire admissible
sans exemption, plafonnée par le cumul déjà retenu sur l'année, afin que
le montant retenu soit exact au cent près.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT calculer un montant théorique de période
   `montant_periode = taux_employe × Salaire_Admissible` (RQAP), arrondi
   selon le Mode_Arrondissement_Cotisations. Contrairement au RRQ, AUCUNE
   exemption n'est soustraite du Salaire_Admissible avant application du
   taux.
2. LE Moteur_Cotisations DOIT calculer la marge disponible
   `marge_disponible = max(Decimal("0.00"), Plafond_Annuel_RQAP_Employe −
   Cumul_YTD_RQAP_Employe)`.
3. LE Moteur_Cotisations DOIT retourner comme cotisation RQAP employé
   effective `min(montant_periode, marge_disponible)`.
4. LORSQUE `Cumul_YTD_RQAP_Employe ≥ Plafond_Annuel_RQAP_Employe`, LE
   Moteur_Cotisations DOIT retourner une cotisation RQAP employé égale à
   `Decimal("0.00")` sans lever d'exception.
5. LE Moteur_Cotisations NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
6. LA cotisation RQAP employé retournée DOIT toujours satisfaire
   `Decimal("0.00") ≤ cotisation ≤ montant_periode` et
   `Cumul_YTD_RQAP_Employe + cotisation ≤ Plafond_Annuel_RQAP_Employe`.

---

### Requirement 5: Calcul de la cotisation RQAP employeur

**User Story:** En tant que responsable de la paie, je veux que la
cotisation RQAP employeur soit calculée **indépendamment** de la
cotisation employé, avec son propre taux appliqué directement au salaire
admissible, afin de reproduire fidèlement la formule officielle du
TP-1015.F et d'éviter l'erreur d'arrondissement en cascade identifiée
dans l'anomalie du scénario QC004.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT calculer un montant théorique de période
   `montant_periode = taux_employeur × Salaire_Admissible` (RQAP), arrondi
   selon le Mode_Arrondissement_Cotisations, où `Salaire_Admissible` est
   la même valeur brute que celle utilisée par `calcul_rqap_employe`
   (Req 4 AC1) — **jamais** une valeur dérivée de la cotisation employé
   déjà arrondie.
2. LE Moteur_Cotisations NE DOIT PAS calculer la cotisation RQAP
   employeur comme `1.4 × cotisation_rqap_employe` ni par toute autre
   dérivation à partir du montant employé — cette méthode est
   explicitement rejetée par cette spec car elle produit un résultat
   incorrect (voir la décision de résolution de l'anomalie QC004 dans
   l'Introduction).
3. LE Moteur_Cotisations DOIT calculer la marge disponible
   `marge_disponible = max(Decimal("0.00"),
   Plafond_Annuel_RQAP_Employeur − Cumul_YTD_RQAP_Employeur)`.
4. LE Moteur_Cotisations DOIT retourner comme cotisation RQAP employeur
   effective `min(montant_periode, marge_disponible)`.
5. LORSQUE `Cumul_YTD_RQAP_Employeur ≥ Plafond_Annuel_RQAP_Employeur`, LE
   Moteur_Cotisations DOIT retourner une cotisation RQAP employeur égale
   à `Decimal("0.00")` sans lever d'exception.
6. LE Moteur_Cotisations NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul, y compris de façon temporaire ou pour une étape de
   calcul intermédiaire quelconque (règle 01, absolue et non
   négociable) : tous les opérandes et résultats intermédiaires
   DOIVENT rester des `Decimal` du premier au dernier opérateur
   arithmétique.
7. LA cotisation RQAP employeur retournée DOIT toujours satisfaire
   `Decimal("0.00") ≤ cotisation ≤ montant_periode` et
   `Cumul_YTD_RQAP_Employeur + cotisation ≤ Plafond_Annuel_RQAP_Employeur`.
8. LE scénario QC004 du Corpus_Golden DOIT produire une cotisation RQAP
   employeur de `Decimal("1.77")`, conformément à la décision de
   résolution de l'anomalie documentée dans l'Introduction.

---

### Requirement 6: Calcul de la cotisation AE employé

**User Story:** En tant que responsable de la paie, je veux que la
cotisation AE employé applique le taux Québec au salaire admissible,
plafonnée par le cumul déjà retenu sur l'année, afin que le montant
retenu soit exact au cent près.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT calculer un montant théorique de période
   `montant_periode = taux_employe_quebec × Salaire_Admissible` (AE),
   arrondi selon le Mode_Arrondissement_Cotisations. AUCUNE exemption
   n'est soustraite du Salaire_Admissible avant application du taux.
2. LE Moteur_Cotisations DOIT calculer la marge disponible
   `marge_disponible = max(Decimal("0.00"), Plafond_Annuel_AE_Employe −
   Cumul_YTD_AE_Employe)`.
3. LE Moteur_Cotisations DOIT retourner comme cotisation AE employé
   effective `min(montant_periode, marge_disponible)`.
4. LORSQUE `Cumul_YTD_AE_Employe ≥ Plafond_Annuel_AE_Employe`, LE
   Moteur_Cotisations DOIT retourner une cotisation AE employé égale à
   `Decimal("0.00")` sans lever d'exception.
5. LE Moteur_Cotisations NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
6. LA cotisation AE employé retournée DOIT toujours satisfaire
   `Decimal("0.00") ≤ cotisation ≤ montant_periode` et
   `Cumul_YTD_AE_Employe + cotisation ≤ Plafond_Annuel_AE_Employe`.

---

### Requirement 7: Calcul de la cotisation AE employeur

**User Story:** En tant que responsable de la paie, je veux que la
cotisation AE employeur soit dérivée par un multiplicateur de la
cotisation AE employé **effectivement retenue** pour la même période,
conformément au T4127 qui ne prévoit pas de taux employeur distinct mais
un multiplicateur appliqué à la retenue employé, afin que les deux
montants restent proportionnels après plafonnement.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT calculer la cotisation AE employeur comme
   `arrondir(multiplicateur_employeur × cotisation_ae_employe_effective)`,
   où `cotisation_ae_employe_effective` est le montant retourné par
   `calcul_ae_employe` invoqué avec les mêmes arguments `payroll_input`,
   `gains`, `parametres_annee` (c'est-à-dire **après** plafonnement
   employé — Requirement 6), arrondi selon le
   Mode_Arrondissement_Cotisations.
2. LE Moteur_Cotisations NE DOIT PAS calculer la cotisation AE employeur
   comme `taux_employe_quebec × multiplicateur_employeur ×
   Salaire_Admissible` (calcul indépendant sur le brut) — contrairement
   au RQAP employeur (Requirement 5), le T4127 ne définit **aucun taux
   employeur distinct** pour l'AE ; le paramètre disponible est
   uniquement le multiplicateur appliqué à la retenue employé.
3. LE Moteur_Cotisations DOIT, en défense en profondeur, calculer la
   marge disponible `marge_disponible = max(Decimal("0.00"),
   Plafond_Annuel_AE_Employeur − Cumul_YTD_AE_Employeur)` et retourner
   comme cotisation AE employeur effective
   `min(arrondir(multiplicateur_employeur ×
   cotisation_ae_employe_effective), marge_disponible)`.
4. LE Moteur_Cotisations NE DOIT introduire aucun `float` intermédiaire
   dans ce calcul (règle 01).
5. LA cotisation AE employeur retournée DOIT toujours satisfaire
   `Cumul_YTD_AE_Employeur + cotisation ≤ Plafond_Annuel_AE_Employeur`.

---

### Requirement 8: Deuxième cotisation supplémentaire au RRQ (RRQ2) — hors périmètre

**User Story:** En tant que responsable de la robustesse du moteur, je
veux que la deuxième cotisation supplémentaire au RRQ (RRQ2) soit
explicitement exclue du périmètre calculé par cette spec plutôt
qu'approximée ou ignorée silencieusement, afin de respecter la règle 03
sans introduire de code mort ni de risque fiscal non documenté.

#### Acceptance Criteria

1. LE Moteur_Cotisations NE DOIT PAS calculer ni exposer de montant
   correspondant à la RRQ2, quelle que soit la valeur du
   Salaire_Admissible.
2. LE Moteur_Cotisations NE DOIT PAS lire les champs
   `taux_deuxieme_cotisation_supplementaire_employe` ni
   `taux_deuxieme_cotisation_supplementaire_employeur` de
   `RRQParametres` — ces champs restent réservés à une spec future si le
   périmètre Camp LilySO devait un jour couvrir des salaires atteignant
   le MGA.
3. `docs/cas-non-supportes.md` DOIT documenter que la RRQ2 est hors
   périmètre du Camp LilySO en pratique : le Plafond_Annuel_RRQ_Employe
   (`cotisation_max_annuelle_employe = 4479.30 $`) correspond exactement
   au seuil où l'Assiette_Cotisable_RRQ atteint le MGA
   (`74 600 $ − 3 500 $ = 71 100 $`, et `71 100 × 6,30 % = 4 479,30 $`) ;
   la cotisation RRQ employé effective (Requirement 2) cesse donc
   naturellement de croître exactement à ce seuil, sans qu'aucun garde-fou
   `UnsupportedPayrollCase` supplémentaire ne soit nécessaire pour ce
   cas précis.
4. Cette spec NE modifie NI n'étend `docs/cas-non-supportes.md` au-delà
   de l'ajout documentaire de l'AC3 — l'ajout d'un véritable support de
   la RRQ2 exigerait une spec dédiée, conformément à la règle 03
   (« Extension du périmètre »).

---

### Requirement 9: Délégation aux garde-fous existants pour les cas hors matrice

**User Story:** En tant que responsable de la robustesse du moteur, je
veux que le module de cotisations sociales s'appuie sur les refus déjà
portés par `PayrollInput` plutôt que de les redoubler, afin de maintenir
un seul point de vérité pour la définition de la matrice Camp LilySO
(règle 03).

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT compter sur le fait qu'un `PayrollInput`
   construit avec succès garantit par construction : province Québec,
   fréquence aux deux semaines, taux de vacances ∈ `{0.04, 0.06}` — sans
   re-tester ces invariants.
2. LE Moteur_Cotisations DOIT compter sur le fait qu'un
   `GainsDecomposes` construit avec succès garantit par construction que
   `brut_total ≥ 0` — sans re-tester cet invariant.
3. LE Moteur_Cotisations NE DOIT PAS introduire de nouveau garde-fou
   `UnsupportedPayrollCase` au-delà de celui déjà couvert par
   Requirement 8 — aucun autre cas hors matrice n'est identifié pour les
   trois cotisations RRQ/RQAP/AE dans le périmètre Camp LilySO.

---

### Requirement 10: Arrondissement à deux décimales sur chaque montant

**User Story:** En tant que responsable de la conformité fiscale, je
veux que chaque montant de cotisation soit arrondi à deux décimales selon
le mode utilisé par WebRAS et PDOC, afin que la reconstruction manuelle
des lignes du bulletin de paie produise exactement les mêmes montants
que le moteur.

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT appliquer le mode d'arrondissement
   `decimal.ROUND_HALF_UP` avec une précision de deux décimales à chaque
   montant théorique de période (`montant_periode`) calculé par les
   Requirements 2, 4, 5, 6, 7, avant toute comparaison avec une marge
   disponible.
2. LE Moteur_Cotisations DOIT appliquer l'arrondissement `ROUND_HALF_UP`
   à deux décimales au produit `multiplicateur_employeur ×
   cotisation_ae_employe_effective` du Requirement 7, après la
   multiplication.
3. LE Moteur_Cotisations NE DOIT PAS ré-arrondir une valeur déjà
   arrondie à deux décimales reçue en entrée (`Cumul_YTD_*`,
   `Salaire_Admissible`, `Exemption_Par_Periode_RRQ`).
4. LE mode et la précision d'arrondissement effectivement appliqués
   DOIVENT être exposés dans chaque `CalculationTrace` retournée (voir
   Requirement 11 AC6).

---

### Requirement 11: Trace exhaustive de chaque calcul de cotisation

**User Story:** En tant qu'auditeur (interne, Revenu Québec ou ARC) qui
inspecte une paie plusieurs années après son émission, je veux que la
trace de chaque cotisation référence la source officielle, liste les
paramètres utilisés, les entrées, les sous-totaux intermédiaires nommés
et le mode d'arrondissement, afin de reconstruire le montant exact sans
réexécuter le moteur.

#### Acceptance Criteria

1. CHACUNE des six fonctions DOIT retourner une `CalculationTrace` dont
   le champ `source` est conforme à la liste blanche des sources
   officielles de `CalculationTrace` (règle 02) : `"TP-1015.F 2026,
   section 3.2 — RRQ"` (ou variante employeur) pour `calcul_rrq_employe`
   et `calcul_rrq_employeur` ; `"TP-1015.F 2026, section 3.3 — RQAP"`
   (ou variante employeur) pour `calcul_rqap_employe` et
   `calcul_rqap_employeur` ; `"T4127 2026, section 4 — Assurance-emploi"`
   pour `calcul_ae_employe` et `calcul_ae_employeur`.
2. LA CalculationTrace retournée DOIT porter `annee =
   payroll_input.pay_period.annee_fiscale`, la `juridiction` correcte
   (`Juridiction.QUEBEC` pour RRQ et RQAP, `Juridiction.CANADA` pour
   AE), et une chaîne `section` non vide qui distingue explicitement le
   côté employé du côté employeur.
3. LA CalculationTrace de `calcul_rrq_employe` DOIT exposer, dans
   `parametres_utilises`, au minimum `taux_cotisation_totale_employe` et
   `exemption_generale_annuelle` (ou l'exemption par période
   effectivement utilisée) ; dans `entrees`, au minimum
   `salaire_periode`, `nb_periodes_annuelles` et `cumul_ytd` ; dans
   `sous_totaux`, au minimum `exemption_periode` et
   `assiette_cotisable`.
4. LA CalculationTrace de `calcul_rqap_employe` et
   `calcul_rqap_employeur` DOIT exposer, dans `parametres_utilises`, le
   taux effectivement appliqué (`taux_employe` ou `taux_employeur`) ;
   dans `entrees`, au minimum `salaire_periode` ; dans `sous_totaux`, au
   minimum `cotisation_brute` (le montant théorique avant plafonnement).
5. LA CalculationTrace de `calcul_ae_employe` DOIT exposer, dans
   `parametres_utilises`, `taux_employe_quebec` ; dans `entrees`, au
   minimum `salaire_periode` ; dans `sous_totaux`, au minimum
   `cotisation_brute`. LA CalculationTrace de `calcul_ae_employeur` DOIT
   exposer, dans `parametres_utilises`, `multiplicateur_employeur` ;
   dans `entrees`, au minimum `ae_employe` (le montant employé effectif
   consommé) ; dans `sous_totaux`, au minimum le produit avant
   arrondissement final.
6. CHAQUE CalculationTrace DOIT porter `mode_arrondissement =
   ModeArrondissement.ROUND_HALF_UP`, `precision_arrondissement = 2` et
   `resultat` égal au montant retourné par la fonction.
7. LES trois dictionnaires `parametres_utilises`, `entrees` et
   `sous_totaux` de chaque trace DOIVENT contenir uniquement des valeurs
   `Decimal` ; aucun `float` NE DOIT y apparaître (règle 01).
8. CHAQUE CalculationTrace produite DOIT être suffisante pour permettre
   à un tiers de recalculer manuellement le montant retourné à partir de
   ses seuls contenus, sans consulter ni le `PayrollInput` d'origine ni
   les fichiers `parameters/<AAAA>/*.json`.

---

### Requirement 12: Consommation stricte des paramètres annuels versionnés

**User Story:** En tant que responsable de la mise à jour annuelle des
paramètres fiscaux, je veux que le module de cotisations sociales lise
100 % de ses taux, exemptions et plafonds depuis
`parameters/<AAAA>/quebec.json` et `parameters/<AAAA>/canada.json` sans
exception, afin qu'une révision annuelle des taux ne nécessite jamais de
retoucher du code Python (règle 05).

#### Acceptance Criteria

1. LE Moteur_Cotisations DOIT lire, pour le RRQ, les champs
   `taux_cotisation_totale_employe`, `exemption_par_periode_aux_deux_semaines_2026`
   et `cotisation_max_annuelle_employe` de
   `parametres_annee.rrq` — sans jamais coder en dur `Decimal("0.063")`,
   `Decimal("129.63")` ni `Decimal("4479.30")`.
2. LE Moteur_Cotisations DOIT lire, pour le RQAP, les champs
   `taux_employe`, `taux_employeur`, `cotisation_max_employe` et
   `cotisation_max_employeur` de `parametres_annee.rqap`.
3. LE Moteur_Cotisations DOIT lire, pour l'AE, les champs
   `taux_employe_quebec`, `multiplicateur_employeur`,
   `cotisation_max_employe` et `cotisation_max_employeur` de
   `parametres_annee.assurance_emploi`.
4. LE Moteur_Cotisations NE DOIT contenir aucune constante numérique
   représentant un taux, une exemption ou un plafond fiscal dans son
   propre code (règle 05), ceci incluant explicitement les taux
   employé/employeur des trois cotisations, l'exemption RRQ (annuelle
   ou par période), le multiplicateur employeur AE et les six plafonds
   annuels — aucune exception, même pour une valeur qui semble stable
   d'une année à l'autre. LES seules constantes numériques autorisées
   dans le code de cette spec sont l'entier `2` (précision
   d'arrondissement, imposée par le TP-1015.F et le T4127) et
   `Decimal("0.00")` utilisé comme plancher ou valeur neutre.
5. SI un champ consommé par l'AC1, l'AC2 ou l'AC3 est marqué `"TO_FILL"`
   dans le fichier de paramètres, ALORS l'accès à la propriété
   correspondante DOIT lever `MissingParameterError` (comportement déjà
   porté par `RRQParametres`, `RQAPParametres`, `AEParametres` —
   `moteur-paie-contrats` Req 9.5) ; LE Moteur_Cotisations NE DOIT PAS
   intercepter cette exception ni la convertir en une autre.
6. LES fichiers `parameters/2026/quebec.json` et
   `parameters/2026/canada.json` DOIVENT déjà contenir, à la date de
   rédaction de cette spec, toutes les valeurs consommées par les AC1 à
   AC3 sous forme de chaînes numériques renseignées (aucun `"TO_FILL"`
   sur ces champs précis) — vérification effective réalisée par la phase
   de design et de tâches.

---

### Requirement 13: Corpus golden — reproduction au cent près

**User Story:** En tant que responsable de la conformité fiscale, je veux
que les six cotisations calculées par cette spec reproduisent au cent
près les valeurs validées par WebRAS et PDOC pour les six scénarios de
référence, afin d'avoir une garantie empirique que le moteur produit des
montants corrects avant toute mise en production.

#### Acceptance Criteria

1. POUR CHAQUE scénario du Corpus_Golden (QC001 à QC006), `calcul_rrq_employe`
   appliqué au `PayrollInput` et au `GainsDecomposes` du scénario DOIT
   retourner exactement le montant `rrq.montant` de la fixture de sortie
   correspondante (`tests/fixtures/outputs/qc0*.json`).
2. POUR CHAQUE scénario du Corpus_Golden, `calcul_rrq_employeur` DOIT
   retourner exactement le montant `rrq_employeur.montant` de la fixture.
3. POUR CHAQUE scénario du Corpus_Golden, `calcul_rqap_employe` et
   `calcul_rqap_employeur` DOIVENT retourner exactement les montants
   `rqap.montant` et `rqap_employeur.montant` de la fixture — y compris
   `Decimal("1.77")` pour `rqap_employeur` sur le scénario QC004
   (Requirement 5 AC8).
4. POUR CHAQUE scénario du Corpus_Golden, `calcul_ae_employe` et
   `calcul_ae_employeur` DOIVENT retourner exactement les montants
   `ae.montant` et `ae_employeur.montant` de la fixture.
5. POUR CHAQUE `CalculationTrace` retournée sur le Corpus_Golden, le
   champ `resultat` DOIT être égal au montant retourné par la fonction
   correspondante (cohérence trace/montant).
6. LE scénario QC001 DOIT en particulier confirmer `rrq.montant ==
   Decimal("87.36")` (valeur corrigée après ré-exécution WebRAS en 27
   périodes — voir `docs/journal-validation.md` ; la valeur historique
   de 86,34 $, issue d'une exécution erronée à 24 périodes, N'EST PAS
   une valeur de référence valide pour cette spec).

---

### Requirement 14: Cas d'erreur et bornes de validité

**User Story:** En tant que responsable de la robustesse du moteur, je
veux que les cas limites (salaire admissible nul, cumul déjà au plafond,
salaire admissible négatif théorique) soient traités de façon prévisible
et testée, afin qu'aucune retenue négative ni aucune exception inattendue
ne puisse survenir en production.

#### Acceptance Criteria

1. LORSQUE `Salaire_Admissible = Decimal("0.00")` (paie à brut nul,
   cas théorique), CHACUNE des six fonctions DOIT retourner
   `Decimal("0.00")` sans lever d'exception.
2. LORSQUE le cumul YTD pertinent (`Cumul_YTD_RRQ_Employe`,
   `Cumul_YTD_RQAP_Employe`, `Cumul_YTD_RQAP_Employeur`,
   `Cumul_YTD_AE_Employe` ou `Cumul_YTD_AE_Employeur`) est exactement
   égal à son plafond annuel correspondant, LA fonction concernée DOIT
   retourner `Decimal("0.00")` pour cette cotisation, sans lever
   d'exception.
3. ÉTANT DONNÉ que `CumulsYTD` impose déjà `ge=Decimal("0")` sur chacune
   de ses six catégories pertinentes (contrat `moteur-paie-contrats`),
   CHACUNE des six fonctions DOIT pouvoir supposer que les cumuls YTD
   reçus en entrée sont toujours non négatifs, sans re-valider cette
   contrainte.
4. AUCUNE des six fonctions NE DOIT jamais retourner un montant
   strictement négatif, quelles que soient les valeurs valides (au sens
   du contrat `PayrollInput`/`GainsDecomposes`/`CumulsYTD`) de ses
   arguments.
5. AUCUNE des six fonctions NE DOIT jamais retourner un montant qui,
   ajouté au cumul YTD correspondant, dépasse le plafond annuel
   correspondant (propriété d'invariant vérifiée par test de propriété,
   voir Requirement 2 AC8, Requirement 4 AC6, Requirement 5 AC7,
   Requirement 6 AC6, Requirement 7 AC5).
