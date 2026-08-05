# Requirements Document

<!-- Titre métier : Document d'exigences — impots-retenues-source. Les en-têtes structurels de niveau supérieur (Requirements Document, Introduction, Glossary, Requirements) et les libellés « Requirement N », « User Story: », « Acceptance Criteria » sont maintenus en anglais pour la conformité au format Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec implémente **l'étape 4** du plan d'implémentation
(`docs/plan-implementation.md`), immédiatement après `moteur-paie-contrats`
(étape 1, socle contractuel figé, modèles/exceptions/trace/parameters_loader),
`gains-bruts-vacances-hs` (étape 2, fonction `calcul_gains`) et
`cotisations-sociales-qc` (étape 3, RRQ/RQAP/AE, complétée à 100 %). Elle
définit et impose les quatre fonctions pures de calcul des retenues
d'impôt à la source du Camp LilySO :

- **Impôt du Québec** (TP-1015.F 2026) — calcul de la retenue théorique
  selon la formule officielle (paliers progressifs, crédit personnel
  total du TP-1015.3, déduction pour travailleur), puis calcul de la
  retenue effective après application du court-circuit d'exonération
  TP-1015.3 et ajout de la retenue additionnelle QC ;
- **Impôt fédéral** (T4127 2026) — calcul de la retenue théorique selon
  la formule officielle (paliers progressifs, crédit personnel total du
  TD1, déduction de la portion supplémentaire du RRQ), puis calcul de la
  retenue effective après application du court-circuit d'exonération TD1
  et ajout de la retenue additionnelle fédérale.

Ces deux calculs sont regroupés dans une seule spec parce qu'ils
partagent la même forme structurelle : une formule à paliers progressifs
appliquée à un revenu imposable annualisé, réduite d'un crédit personnel
total porté par un formulaire déclaratif de l'employé (TP-1015.3 pour le
Québec, TD1 pour le fédéral), suivie d'un mécanisme de court-circuit
d'exonération optionnel et de l'ajout d'une retenue additionnelle
volontaire optionnelle. Le Requirement 1 fixe précisément, pour chacune
des quatre fonctions, la formule et la nature exacte de cette parenté et
de ses écarts (déduction pour travailleur propre au Québec ; déduction de
la portion supplémentaire RRQ propre au fédéral).

**Périmètre strict** : seules les quatre fonctions de calcul d'impôt
(formule et retenue effective, pour chacune des deux juridictions) et
leur trace sont couvertes. Sont explicitement **hors périmètre** de
cette spec :

- le RRQ, le RQAP et l'AE (étape 3, `cotisations-sociales-qc`, déjà
  livrée) ;
- le FSS, la CNESST et la CNT (étape 5, `charges-patronales`) ;
- l'assemblage du `PayrollResult` complet, la mise à jour du `CumulsYTD`
  après paie (via `CumulsYTD.avec_paie`) et le registre maître (étape 6,
  `net-cumuls-registre`).

**Contrats consommés sans modification** (déjà figés par
`moteur-paie-contrats`) :

- `models.payroll_input.PayrollInput` — porte notamment
  `montant_total_TP1015_3_effectif`, `exoneration_TP1015_3_effectif`,
  `retenue_additionnelle_QC_effective`, `montant_total_TD1_effectif`,
  `exoneration_TD1_effective`, `retenue_additionnelle_federale_effective`
  (noms de champs exacts confirmés dans `models/payroll_input.py`), ainsi
  que `pay_period.annee_fiscale` et `pay_period.nb_periodes_annuelles`.
- `models.payroll_result.GainsDecomposes` — produit par `calcul_gains`
  (étape 2) ; son champ `brut_total` est la seule source du salaire de
  période consommé par cette spec (même décision de périmètre que
  `cotisations-sociales-qc` Requirement 1 AC6 — cohérence transversale du
  moteur).
- `models.payroll_result.MontantAvecTrace`, `RetenuesEmploye` — les
  quatre montants produits par cette spec alimenteront in fine les
  champs `impot_qc_formule`, `impot_qc_retenu`, `impot_federal_formule`,
  `impot_federal_retenu` de `RetenuesEmploye` (assemblage réalisé par
  l'étape 6, pas par cette spec). Rappel du contrat déjà figé (Req 12.8
  de `moteur-paie-contrats`) : seuls `impot_qc_retenu.montant` et
  `impot_federal_retenu.montant` participent à `total_retenues_employe` ;
  les deux montants `*_formule` sont conservés pour la traçabilité et
  n'entrent jamais dans le total.
- `models.trace.CalculationTrace` — contrat de trace imposé par la
  règle 02.
- `models.exceptions.MissingParameterError`, `UnsupportedPayrollCase`.
- `payroll_engine.parameters_loader.ParametresAnnee`, `ImpotQCParametres`,
  `ImpotFederalParametres` — déjà typés (properties `Decimal` qui lèvent
  `MissingParameterError` sur `"TO_FILL"` ; les structures complexes
  telles que `paliers`, `taux_credits_convertibles`,
  `regles_arrondissement`, `deduction_pour_travailleur_annuelle`,
  `montant_emploi_canadien_annuel` et `deduction_rrq_supplementaire` sont
  actuellement absorbées par `extra="allow"` sur ces deux sous-modèles —
  voir la décision de périmètre « paramètres non encore typés
  finement » ci-dessous).

**Décision de périmètre — champ commun `montant_personnel_base`
inutilisé** : les sous-modèles `ImpotQCParametres` et
`ImpotFederalParametres` exposent chacun une propriété
`montant_personnel_base` (18 952,00 $ pour le Québec, 16 452,00 $ pour le
fédéral en 2026). Cette spec **ne lit ni ne consomme** cette propriété :
le crédit personnel effectivement appliqué par le Moteur_Impots provient
exclusivement de `payroll_input.montant_total_TP1015_3_effectif` (Québec)
et `payroll_input.montant_total_TD1_effectif` (fédéral) — les montants
réellement déclarés par l'employé sur son formulaire TP-1015.3 ou TD1,
qui peuvent différer du montant personnel de base par défaut (crédits
additionnels : montant pour personne à charge, montant pour déficience,
etc.). Pour le corpus QC001–QC006, ces deux valeurs coïncident
numériquement avec les montants personnels de base 2026 (18 952,00 $ et
16 452,00 $ respectivement) parce qu'aucun scénario du corpus ne déclare
de crédit additionnel — mais la spec n'exploite jamais cette coïncidence
comme raccourci de calcul.

**Décision de périmètre — paramètres non encore typés finement** : à la
date de rédaction de cette spec, `parameters/2026/quebec.json` (section
`impot_quebec`) et `parameters/2026/canada.json` (section
`impot_federal`) portent encore la sentinelle `"TO_FILL"` sur les
champs `paliers`, `taux_credits_convertibles`, `regles_arrondissement`
(Québec et fédéral), `deduction_pour_travailleur_annuelle` (Québec) et
`montant_emploi_canadien_annuel` (fédéral). Le Requirement 12 impose que
ces paramètres soient intégralement renseignés (valeurs numériques
publiées par Revenu Québec et l'ARC pour l'année 2026) **avant** que la
phase de tâches ne puisse déclarer les golden tests du Requirement 11
exécutables — cohérent avec la règle 05 (« aucun taux fiscal codé en dur
») et avec le critère de sortie de l'étape 0 du plan d'implémentation.
Cette spec ne fige pas la structure JSON exacte de `paliers` : ce détail
relève de la phase de conception (design), qui devra également décider
si `ImpotQCParametres` et `ImpotFederalParametres` doivent être étendus
avec des sous-modèles typés dédiés (par analogie avec `RRQParametres`,
`RQAPParametres`, `AEParametres` de l'étape 3) plutôt que de rester en
`extra="allow"`.

**Décision de conception — signature des fonctions** : les quatre
fonctions de cette spec suivent le même patron que les six fonctions de
`cotisations-sociales-qc` : chaque fonction reçoit le `PayrollInput`
complet, le `GainsDecomposes` produit par l'étape 2 et le
`ParametresAnnee`, et retourne `tuple[Decimal, CalculationTrace]`
conformément à la règle 02. Les deux fonctions « retenue effective »
(`calcul_impot_qc_retenu`, `calcul_impot_federal_retenu`) délèguent
structurellement à leur fonction « formule » homologue par un appel
interne direct, selon le même patron de délégation structurelle déjà
appliqué par `calcul_rrq_employeur` (délégation stricte) et
`calcul_ae_employeur` (délégation avec transformation) dans
`cotisations-sociales-qc`. Voir Requirement 1 pour le détail exact par
fonction.

**Décision de conception — noms de modules** : cette spec livre
`payroll_engine/impot_qc.py` et `payroll_engine/impot_federal.py`. Ces
noms diffèrent des noms `quebec_tax.py` / `federal_tax.py` mentionnés
dans `docs/plan-implementation.md` (étape 4) : les noms `impot_qc.py` /
`impot_federal.py` sont préférés pour rester cohérents avec les champs
déjà figés de `RetenuesEmploye` (`impot_qc_formule`, `impot_qc_retenu`,
`impot_federal_formule`, `impot_federal_retenu`) et avec les sections
déjà nommées `impot_quebec` / `impot_federal` de `ParametresAnnee`. Cette
déviation mineure du plan sera reflétée dans `docs/plan-implementation.md`
à l'issue de la revue de cette spec — même type de déviation documentée
et acceptée que celle déjà actée pour `assurance_emploi.py` (au lieu de
`ei.py`) dans `cotisations-sociales-qc`.

**Décision de conception — mécanisme d'exonération, un court-circuit
distinct de l'exemption des cotisations sociales** : l'exonération
TP-1015.3 (respectivement TD1) est un mécanisme **strictement local** à
la retenue d'impôt : `exoneration_TP1015_3_effectif = True` force
`impot_qc_retenu` à `Decimal("0.00")` **avant** ajout de la retenue
additionnelle éventuelle — voir Requirement 3 — mais ne modifie en rien
le calcul du RRQ, du RQAP ou de l'AE (déjà livrés par
`cotisations-sociales-qc`, qui ne lisent aucun des deux champs
d'exonération). Ce principe, déjà énoncé dans
`docs/plan-implementation.md` (« Séparation stricte... l'exonération
d'impôt ≠ exemption des cotisations sociales »), est formalisé par le
Requirement 6 de cette spec.

**Décision de résolution — cas « sous le seuil d'imposition » sans
exonération (QC004, QC006)** : les scénarios QC004 et QC006 du
Corpus_Golden n'ont **aucune** exonération active pour QC004
(`exoneration_TP1015_3_effectif = False`, `exoneration_TD1_effective =
False`) et une exonération active pour QC006, mais les deux scénarios
produisent `impot_qc_formule == Decimal("0.00")` et `impot_federal_formule
== Decimal("0.00")` **par la formule elle-même**, parce que le brut
annualisé (`brut_total × nb_periodes_annuelles`) reste inférieur au
crédit personnel effectif. Cette spec traite ce cas comme un
comportement **normal et attendu** de la formule à paliers progressifs
(revenu imposable annualisé net de crédit personnel négatif ou nul →
impôt nul), et non comme un cas d'erreur ni comme une variante du
court-circuit d'exonération — voir Requirement 7. QC004 est le seul
scénario du Corpus_Golden qui valide ce comportement **indépendamment**
du mécanisme d'exonération (les deux champs d'exonération y sont à
`False`).

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire, `float` interdit.
- Règle 02 — chaque fonction retourne `tuple[Decimal, CalculationTrace]`
  avec source officielle sur la liste blanche de `CalculationTrace`
  (`"TP-1015.F 2026, ..."` et `"T4127 2026, ..."`).
- Règle 03 — cas hors matrice déjà refusés par `PayrollInput` ; cette
  spec ne redouble pas ces garde-fous (voir Requirement 13).
- Règle 04 — aucune donnée personnelle réelle ; corpus anonymisé
  QC001–QC006 uniquement.
- Règle 05 — tous les taux, paliers, constantes et montants proviennent
  exclusivement de `parameters/<AAAA>/quebec.json` et
  `parameters/<AAAA>/canada.json` ; aucune valeur en dur dans le code
  Python.
- Règle 06 — spec → tests (property + golden) → implémentation →
  validation ; tests écrits avant code.

**Corpus de validation** : les six scénarios QC001–QC006 documentés dans
`docs/scenario-qc0*.md` et `docs/journal-validation.md` doivent
reproduire **au cent près** les quatre champs `impot_qc_formule`,
`impot_qc_retenu`, `impot_federal_formule`, `impot_federal_retenu` de
leurs fixtures de sortie (`tests/fixtures/outputs/qc0*.json`, déjà
renseignées pour ces quatre champs, y compris leurs sous-traces). QC001
est le seul scénario sans aucune exonération active où la formule produit
un impôt strictement positif pour les deux juridictions ; QC002, QC003 et
QC005 valident la formule à des niveaux de revenu croissants **et** le
court-circuit d'exonération ; QC004 et QC006 valident le comportement
« sous le seuil d'imposition ». Aucun scénario du corpus ne porte de
retenue additionnelle QC ou fédérale non nulle (`retenue_additionnelle_QC_effective`
et `retenue_additionnelle_federale_effective` valent `Decimal("0.00")`
dans les six fixtures d'entrée) — ce comportement reste néanmoins
spécifié par cette spec (Requirement 3, Requirement 5) et devra être
couvert par des tests de propriété plutôt que par le corpus golden.

## Glossary

- **Moteur_Impots** : l'ensemble des quatre fonctions de calcul livrées
  par cette spec, considéré comme un système unique aux fins de ce
  document.
- **Salaire_Periode** : `GainsDecomposes.brut_total` — la seule source du
  salaire de période consommé par cette spec (même décision de périmètre
  que `cotisations-sociales-qc`).
- **TP-1015.F** : formulaire/guide de retenues à la source publié par
  Revenu Québec, source de la formule de retenue d'impôt du Québec.
- **T4127** : guide de calcul des retenues sur la paie publié par l'ARC,
  source de la formule de retenue d'impôt fédéral (méthode dite
  « Option 1 »).
- **TP-1015.3** : formulaire de déclaration pour la retenue d'impôt du
  Québec rempli par l'employé, source du crédit personnel total QC, du
  drapeau d'exonération et de la retenue additionnelle QC.
- **TD1** : formulaire de déclaration des crédits d'impôt personnels
  fédéral rempli par l'employé, source du crédit personnel total
  fédéral, du drapeau d'exonération et de la retenue additionnelle
  fédérale.
- **Credit_Personnel_QC_Effectif** :
  `payroll_input.montant_total_TP1015_3_effectif` — montant total des
  crédits personnels QC effectivement déclarés par l'employé pour cette
  paie (voir décision de périmètre de l'Introduction : distinct de
  `parametres_annee.impot_quebec.montant_personnel_base`).
- **Credit_Personnel_Federal_Effectif** :
  `payroll_input.montant_total_TD1_effectif` — équivalent fédéral de
  `Credit_Personnel_QC_Effectif`.
- **Exoneration_QC_Active** : `payroll_input.exoneration_TP1015_3_effectif`
  (`bool`). Lorsque `True`, force `impot_qc_retenu` (avant ajout de la
  retenue additionnelle) à `Decimal("0.00")`, sans invoquer la formule à
  paliers progressifs pour ce montant (Requirement 3).
- **Exoneration_Federale_Active** :
  `payroll_input.exoneration_TD1_effective` (`bool`) — équivalent
  fédéral de `Exoneration_QC_Active` (Requirement 5).
- **Retenue_Additionnelle_QC_Effective** :
  `payroll_input.retenue_additionnelle_QC_effective` — montant
  volontaire supplémentaire ajouté à `impot_qc_retenu` **après**
  application du court-circuit d'exonération (Requirement 3).
- **Retenue_Additionnelle_Federale_Effective** :
  `payroll_input.retenue_additionnelle_federale_effective` — équivalent
  fédéral de `Retenue_Additionnelle_QC_Effective` (Requirement 5).
- **Nb_Periodes_Annuelles** : `payroll_input.pay_period.nb_periodes_annuelles`
  — nombre de périodes de paie annuelles utilisé pour annualiser le
  Salaire_Periode avant application des paliers progressifs (27 pour
  2026, cohérent avec `cotisations-sociales-qc` Requirement 13 AC6 — la
  valeur DOIT provenir de `payroll_input`, jamais d'une constante codée
  en dur).
- **Deduction_Pour_Travailleur** : montant annuel soustrait du revenu
  imposable QC avant application des paliers progressifs, lu depuis
  `parametres_annee.impot_quebec.deduction_pour_travailleur_annuelle`
  (actuellement `"TO_FILL"` — voir décision de périmètre de
  l'Introduction, à renseigner par la phase de tâches).
- **Deduction_RRQ_Supplementaire_Federale** : portion de la cotisation
  RRQ traitée fédéralement comme une déduction du revenu (et non comme
  un crédit), égale à `taux_effectif × max(Decimal("0.00"), Salaire_Periode
  − Exemption_Par_Periode_RRQ)`, où `taux_effectif` est lu depuis
  `parametres_annee.rrq.portion_supplementaire_deductible_fed.taux_effectif`
  (déjà renseigné à `"0.010"` dans `parameters/2026/quebec.json`) et
  `Exemption_Par_Periode_RRQ` depuis
  `parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026`
  (même champ que celui consommé par `calcul_rrq_employe`, spec
  `cotisations-sociales-qc`). Confirmée par PDOC sur QC001 : `13,87 $ =
  1,00 % × (1 516,32 $ − 129,63 $)`, revenu imposable fédéral résultant
  `1 502,45 $ = 1 516,32 $ − 13,87 $`.
- **Revenu_Imposable_QC_Periode** : le revenu de période effectivement
  soumis aux paliers progressifs QC, après application de la
  Deduction_Pour_Travailleur (proratée par période) ; confirmé par
  WebRAS sur QC001 : `1 448,75 $ = 1 516,32 $ − 67,57 $`.
- **Revenu_Imposable_Federal_Periode** : le revenu de période
  effectivement soumis aux paliers progressifs fédéraux, après
  déduction de la Deduction_RRQ_Supplementaire_Federale ; confirmé par
  PDOC sur QC001 : `1 502,45 $ = 1 516,32 $ − 13,87 $`.
- **Mode_Arrondissement_Impots** : `ROUND_HALF_UP` à deux décimales,
  cohérent avec le TP-1015.F et le T4127 2026 et avec
  `cotisations-sociales-qc`.
- **Corpus_Golden** : les six scénarios QC001–QC006 documentés dans
  `docs/scenario-qc0*.md`, matérialisés dans `tests/fixtures/inputs/` et
  `tests/fixtures/outputs/`.
- **PayrollInput**, **GainsDecomposes**, **CalculationTrace**,
  **RetenuesEmploye**, **MontantAvecTrace**, **ParametresAnnee**,
  **ImpotQCParametres**, **ImpotFederalParametres**,
  **UnsupportedPayrollCase**, **MissingParameterError** : contrats figés
  par `moteur-paie-contrats`, consommés sans modification par cette
  spec.

## Requirements

<!-- Chaque « Requirement N » ci-dessous est une exigence métier rédigée en français. -->

### Requirement 1: Points d'entrée uniques et signatures imposées

**User Story:** En tant qu'orchestrateur du moteur de paie, je veux
quatre fonctions publiques et typées, une par juridiction et par étape
(formule / retenue effective), afin que le calcul de chaque retenue
d'impôt soit reproductible indépendamment, testable en isolation, et
retourne systématiquement une trace auditable.

#### Acceptance Criteria

1. LE Moteur_Impots DOIT exposer, dans `payroll_engine/impot_qc.py`,
   deux fonctions publiques `calcul_impot_qc_formule`, de signature
   `(payroll_input: PayrollInput, gains: GainsDecomposes, parametres_annee: ParametresAnnee) -> tuple[Decimal, CalculationTrace]`,
   et `calcul_impot_qc_retenu`, de signature
   `(payroll_input: PayrollInput, gains: GainsDecomposes, parametres_annee: ParametresAnnee, additionnelle_permise: bool) -> tuple[Decimal, CalculationTrace]`
   (voir Requirement 14 pour le rôle exact du 4e paramètre
   `additionnelle_permise`, introduit par cette même spec en révision).
2. LE Moteur_Impots DOIT exposer, dans `payroll_engine/impot_federal.py`,
   deux fonctions publiques `calcul_impot_federal_formule`, de même
   signature à 3 paramètres que `calcul_impot_qc_formule` (AC1), et
   `calcul_impot_federal_retenu`, de même signature à 4 paramètres que
   `calcul_impot_qc_retenu` (AC1, Requirement 14).
3. `calcul_impot_qc_retenu` DOIT invoquer `calcul_impot_qc_formule` en
   interne (même module, appel direct) avec les mêmes arguments
   `payroll_input`, `gains`, `parametres_annee` — délégation
   structurelle garantissant qu'aucune divergence de calcul ne puisse
   apparaître entre les deux fonctions au fil d'un refactoring futur.
   `calcul_impot_federal_retenu` DOIT appliquer la même discipline vis-à-vis
   de `calcul_impot_federal_formule`.
4. CHACUNE des quatre fonctions DOIT être une **fonction pure** : deux
   appels successifs avec les mêmes arguments DOIVENT retourner deux
   tuples égaux au sens `==`, sans état interne persistant, sans lecture
   ou écriture de fichier, sans variable de module mutable et sans appel
   à `datetime.now()` ni à toute autre source de non-déterminisme.
5. CHACUNE des quatre fonctions NE DOIT PAS invoquer directement
   `load_parameters` — les paramètres DOIVENT être injectés par
   l'argument `parametres_annee`.
6. CHACUNE des quatre fonctions DOIT lire le Salaire_Periode
   exclusivement depuis `gains.brut_total`, sans en dériver une valeur
   différente et sans lire `payroll_input` pour cette valeur.
7. CHACUNE des quatre fonctions NE DOIT PAS muter `payroll_input`,
   `gains` ni `parametres_annee` — ces objets sont `frozen=True` par
   contrat et cette spec ne retourne jamais d'objet mis à jour.
8. CHACUNE des quatre fonctions NE DOIT PAS lever d'exception non
   documentée. LES seules exceptions autorisées sont
   `MissingParameterError` (règle 05, Requirement 12) et
   `pydantic.ValidationError` propagée par une construction interne de
   `CalculationTrace` invalide (cas de bug interne, pas un cas métier
   attendu).
9. CHACUNE des quatre fonctions DOIT être importable sans effet de bord
   (aucune action au moment de l'import).

---

### Requirement 2: Calcul de la formule d'impôt du Québec

**User Story:** En tant que responsable de la paie, je veux que la
formule de retenue d'impôt du Québec applique les paliers progressifs
officiels au revenu de période, net de la déduction pour travailleur et
du crédit personnel total déclaré sur le TP-1015.3, afin que le montant
théorique produit soit exact au cent près, indépendamment de toute
décision ultérieure d'exonération.

#### Acceptance Criteria

1. LE Moteur_Impots DOIT annualiser le Salaire_Periode net de la
   Deduction_Pour_Travailleur proratée par période, en tenant compte du
   Nb_Periodes_Annuelles, pour obtenir un revenu imposable annuel de
   référence.
2. LE Moteur_Impots DOIT appliquer les paliers progressifs QC (taux et
   seuils lus depuis `parametres_annee.impot_quebec`) au revenu imposable
   annuel de référence pour obtenir un impôt annuel de base.
3. LE Moteur_Impots DOIT réduire l'impôt annuel de base d'un crédit
   calculé à partir du Credit_Personnel_QC_Effectif (`payroll_input.montant_total_TP1015_3_effectif`),
   selon le mécanisme de crédit personnel officiel du TP-1015.F.
4. LE Moteur_Impots DOIT convertir l'impôt annuel net résultant en un
   montant de période en le divisant par le Nb_Periodes_Annuelles, puis
   arrondir selon le Mode_Arrondissement_Impots (voir Requirement 8).
5. LORSQUE l'impôt annuel net résultant de l'AC3 est négatif ou nul, LE
   Moteur_Impots DOIT retourner `Decimal("0.00")` comme montant théorique
   de la formule QC, sans lever d'exception — ce cas se produit
   notamment lorsque le revenu annualisé (Salaire_Periode ×
   Nb_Periodes_Annuelles) est inférieur au Credit_Personnel_QC_Effectif
   (voir Requirement 7).
6. LE Moteur_Impots NE DOIT introduire aucun `float` intermédiaire dans
   ce calcul (règle 01).
7. LE montant retourné par `calcul_impot_qc_formule` NE DOIT jamais être
   strictement négatif.
8. `calcul_impot_qc_formule` NE DOIT PAS consulter
   `payroll_input.exoneration_TP1015_3_effectif` ni
   `payroll_input.retenue_additionnelle_QC_effective` — ces deux champs
   sont exclusivement consommés par `calcul_impot_qc_retenu`
   (Requirement 3), jamais par la formule elle-même.

---

### Requirement 3: Calcul de la retenue d'impôt du Québec effectivement retenue

**User Story:** En tant que responsable de la paie, je veux que la
retenue d'impôt du Québec effectivement appliquée sur la paie soit nulle
lorsque l'employé a coché l'exonération sur son TP-1015.3, et augmentée
de toute retenue additionnelle volontaire dans tous les cas, afin que le
bulletin de paie reflète fidèlement le choix déclaré par l'employé.

#### Acceptance Criteria

1. LE Moteur_Impots DOIT calculer un montant de base égal à
   `Decimal("0.00")` LORSQUE `payroll_input.exoneration_TP1015_3_effectif
   == True`, et égal au montant retourné par `calcul_impot_qc_formule`
   (invoqué avec les mêmes arguments) LORSQUE
   `payroll_input.exoneration_TP1015_3_effectif == False`.
2. LE Moteur_Impots DOIT retourner comme retenue d'impôt QC effective la
   somme du montant de base de l'AC1 et de
   `payroll_input.retenue_additionnelle_QC_effective` — l'ajout de la
   retenue additionnelle NE DOIT PAS être court-circuité par
   l'exonération.
3. LE Moteur_Impots NE DOIT PAS invoquer la formule à paliers progressifs
   QC pour produire le montant de base LORSQUE l'exonération est active
   (court-circuit véritable, pas simple remplacement du résultat par
   zéro après calcul).
4. LA retenue d'impôt QC effective retournée NE DOIT jamais être
   strictement négative.
5. LE Moteur_Impots NE DOIT introduire aucun `float` intermédiaire dans
   ce calcul (règle 01).
6. LA CalculationTrace retournée par `calcul_impot_qc_retenu` DOIT
   exposer, dans `entrees`, le montant retourné par
   `calcul_impot_qc_formule` sous la clé `impot_qc_formule`, que
   l'exonération soit active ou non — permettant à un auditeur de
   reconstruire manuellement ce qu'aurait été la retenue sans
   exonération.

---

### Requirement 4: Calcul de la formule d'impôt fédéral

**User Story:** En tant que responsable de la paie, je veux que la
formule de retenue d'impôt fédéral applique les paliers progressifs
officiels au revenu de période, net de la déduction de la portion
supplémentaire du RRQ et du crédit personnel total déclaré sur le TD1,
afin que le montant théorique produit soit exact au cent près,
indépendamment de toute décision ultérieure d'exonération.

#### Acceptance Criteria

1. LE Moteur_Impots DOIT calculer la Deduction_RRQ_Supplementaire_Federale
   et la soustraire du Salaire_Periode avant annualisation, selon le
   mécanisme confirmé par PDOC (voir Glossary).
2. LE Moteur_Impots DOIT annualiser le Salaire_Periode net de la
   Deduction_RRQ_Supplementaire_Federale, en tenant compte du
   Nb_Periodes_Annuelles, pour obtenir un revenu imposable annuel de
   référence.
3. LE Moteur_Impots DOIT appliquer les paliers progressifs fédéraux
   (taux et seuils lus depuis `parametres_annee.impot_federal`) au
   revenu imposable annuel de référence pour obtenir un impôt annuel de
   base.
4. LE Moteur_Impots DOIT réduire l'impôt annuel de base d'un crédit
   calculé à partir du Credit_Personnel_Federal_Effectif
   (`payroll_input.montant_total_TD1_effectif`), selon le mécanisme de
   crédit personnel officiel du T4127.
5. LE Moteur_Impots DOIT convertir l'impôt annuel net résultant en un
   montant de période en le divisant par le Nb_Periodes_Annuelles, puis
   arrondir selon le Mode_Arrondissement_Impots (voir Requirement 8).
6. LORSQUE l'impôt annuel net résultant de l'AC4 est négatif ou nul, LE
   Moteur_Impots DOIT retourner `Decimal("0.00")` comme montant théorique
   de la formule fédérale, sans lever d'exception — ce cas se produit
   notamment lorsque le revenu annualisé net de la
   Deduction_RRQ_Supplementaire_Federale est inférieur au
   Credit_Personnel_Federal_Effectif (voir Requirement 7).
7. LE Moteur_Impots NE DOIT introduire aucun `float` intermédiaire dans
   ce calcul (règle 01).
8. LE montant retourné par `calcul_impot_federal_formule` NE DOIT jamais
   être strictement négatif.
9. `calcul_impot_federal_formule` NE DOIT PAS consulter
   `payroll_input.exoneration_TD1_effective` ni
   `payroll_input.retenue_additionnelle_federale_effective` — ces deux
   champs sont exclusivement consommés par `calcul_impot_federal_retenu`
   (Requirement 5), jamais par la formule elle-même.

---

### Requirement 5: Calcul de la retenue d'impôt fédéral effectivement retenue

**User Story:** En tant que responsable de la paie, je veux que la
retenue d'impôt fédéral effectivement appliquée sur la paie soit nulle
lorsque l'employé a coché l'exonération sur son TD1, et augmentée de
toute retenue additionnelle volontaire dans tous les cas, afin que le
bulletin de paie reflète fidèlement le choix déclaré par l'employé.

#### Acceptance Criteria

1. LE Moteur_Impots DOIT calculer un montant de base égal à
   `Decimal("0.00")` LORSQUE `payroll_input.exoneration_TD1_effective ==
   True`, et égal au montant retourné par `calcul_impot_federal_formule`
   (invoqué avec les mêmes arguments) LORSQUE
   `payroll_input.exoneration_TD1_effective == False`.
2. LE Moteur_Impots DOIT retourner comme retenue d'impôt fédéral
   effective la somme du montant de base de l'AC1 et de
   `payroll_input.retenue_additionnelle_federale_effective` — l'ajout de
   la retenue additionnelle NE DOIT PAS être court-circuité par
   l'exonération.
3. LE Moteur_Impots NE DOIT PAS invoquer la formule à paliers progressifs
   fédérale pour produire le montant de base LORSQUE l'exonération est
   active (court-circuit véritable, pas simple remplacement du résultat
   par zéro après calcul).
4. LA retenue d'impôt fédéral effective retournée NE DOIT jamais être
   strictement négative.
5. LE Moteur_Impots NE DOIT introduire aucun `float` intermédiaire dans
   ce calcul (règle 01).
6. LA CalculationTrace retournée par `calcul_impot_federal_retenu` DOIT
   exposer, dans `entrees`, le montant retourné par
   `calcul_impot_federal_formule` sous la clé `impot_federal_formule`,
   que l'exonération soit active ou non.

---

### Requirement 6: Séparation stricte entre exonération d'impôt et cotisations sociales

**User Story:** En tant que responsable de la conformité fiscale, je
veux que l'exonération de la retenue d'impôt (QC ou fédérale) n'ait
aucune incidence sur le calcul du RRQ, du RQAP ou de l'AE, afin de ne
jamais confondre un choix personnel relatif à l'impôt sur le revenu avec
une obligation de cotisation sociale distincte.

#### Acceptance Criteria

1. AUCUNE des quatre fonctions de cette spec NE DOIT lire ni retourner
   de valeur affectant `RetenuesEmploye.rrq`, `RetenuesEmploye.rqap` ni
   `RetenuesEmploye.ae` — ces trois champs sont exclusivement produits
   par les fonctions de la spec `cotisations-sociales-qc`.
2. LE fait que `payroll_input.exoneration_TP1015_3_effectif` ou
   `payroll_input.exoneration_TD1_effective` soit `True` NE DOIT
   entraîner AUCUNE modification du comportement des fonctions
   `calcul_rrq_employe`, `calcul_rrq_employeur`, `calcul_rqap_employe`,
   `calcul_rqap_employeur`, `calcul_ae_employe`, `calcul_ae_employeur` —
   propriété déjà garantie par construction (ces six fonctions ne lisent
   aucun des deux champs d'exonération), vérifiée ici comme propriété
   transversale entre les deux specs.
3. LA Deduction_RRQ_Supplementaire_Federale (Requirement 4 AC1) DOIT être
   calculée par `calcul_impot_federal_formule` **indépendamment** de tout
   appel aux fonctions RRQ de `cotisations-sociales-qc` — cette spec ne
   dépend d'aucune fonction du module `payroll_engine/rrq.py`, elle
   recalcule la portion pertinente directement à partir de
   `gains.brut_total` et de `parametres_annee.rrq`.

---

### Requirement 7: Comportement sous le seuil d'imposition

**User Story:** En tant que responsable de la conformité fiscale, je
veux que la formule d'impôt (QC et fédérale) retourne un montant nul,
sans lever d'exception, lorsque le revenu annualisé de l'employé est
inférieur au crédit personnel effectivement déclaré, indépendamment de
toute exonération, afin de refléter fidèlement le comportement des
calculateurs officiels WebRAS et PDOC sur les bas revenus.

#### Acceptance Criteria

1. LORSQUE le revenu imposable annuel de référence (Requirement 2 AC1
   pour le QC, Requirement 4 AC2 pour le fédéral) est inférieur ou égal
   au crédit personnel effectif correspondant, LA fonction formule
   correspondante DOIT retourner `Decimal("0.00")`, sans lever
   d'exception, indépendamment de la valeur des deux champs
   d'exonération.
2. CE comportement DOIT être distingué, dans la CalculationTrace
   retournée, du court-circuit d'exonération du Requirement 3 / 5 : la
   trace produite par la fonction formule (`calcul_impot_qc_formule` ou
   `calcul_impot_federal_formule`) DOIT documenter le calcul complet
   ayant mené au résultat nul (revenu imposable annuel, crédit
   personnel), et non un simple drapeau d'exonération.
3. LE scénario QC004 du Corpus_Golden (aucune exonération active,
   `exoneration_TP1015_3_effectif = False`,
   `exoneration_TD1_effective = False`) DOIT produire
   `impot_qc_formule == Decimal("0.00")` ET `impot_federal_formule ==
   Decimal("0.00")` par ce seul mécanisme.

---

### Requirement 8: Arrondissement à deux décimales sur chaque montant

**User Story:** En tant que responsable de la conformité fiscale, je
veux que chaque montant d'impôt soit arrondi à deux décimales selon le
mode utilisé par WebRAS et PDOC, afin que la reconstruction manuelle des
lignes du bulletin de paie produise exactement les mêmes montants que le
moteur.

#### Acceptance Criteria

1. LE Moteur_Impots DOIT appliquer le mode d'arrondissement
   `decimal.ROUND_HALF_UP` avec une précision de deux décimales au
   montant de période final calculé par `calcul_impot_qc_formule` et
   `calcul_impot_federal_formule` (Requirement 2 AC4, Requirement 4
   AC5).
2. LE Moteur_Impots NE DOIT PAS ré-arrondir le résultat de
   `calcul_impot_qc_formule` / `calcul_impot_federal_formule` (déjà
   arrondi à deux décimales) lors de la construction de la retenue
   effective par `calcul_impot_qc_retenu` / `calcul_impot_federal_retenu`
   — la somme d'un montant déjà arrondi et de la retenue additionnelle
   (elle-même contrainte à deux décimales par le contrat `PayrollInput`)
   reste naturellement à deux décimales sans arrondissement
   supplémentaire.
3. LE mode et la précision d'arrondissement effectivement appliqués
   DOIVENT être exposés dans chaque `CalculationTrace` retournée (voir
   Requirement 9 AC5).

---

### Requirement 9: Trace exhaustive de chaque calcul d'impôt

**User Story:** En tant qu'auditeur (interne, Revenu Québec ou ARC) qui
inspecte une paie plusieurs années après son émission, je veux que la
trace de chaque calcul d'impôt référence la source officielle, liste les
paramètres utilisés, les entrées, les sous-totaux intermédiaires nommés
et le mode d'arrondissement, afin de reconstruire le montant exact sans
réexécuter le moteur.

#### Acceptance Criteria

1. `calcul_impot_qc_formule` et `calcul_impot_qc_retenu` DOIVENT
   retourner une `CalculationTrace` dont le champ `source` est conforme
   à la liste blanche des sources officielles de `CalculationTrace` et
   commence par `"TP-1015.F 2026"`. `calcul_impot_federal_formule` et
   `calcul_impot_federal_retenu` DOIVENT produire une `source`
   commençant par `"T4127 2026"`.
2. LA CalculationTrace retournée par CHACUNE des quatre fonctions DOIT
   porter `annee = payroll_input.pay_period.annee_fiscale`, la
   `juridiction` correcte (`Juridiction.QUEBEC` pour les deux fonctions
   QC, `Juridiction.CANADA` pour les deux fonctions fédérales), et une
   chaîne `section` non vide qui distingue explicitement la formule de
   la retenue effective.
3. LA CalculationTrace de `calcul_impot_qc_formule` DOIT exposer, dans
   `entrees`, au minimum `salaire_periode` et `nb_periodes_annuelles` ;
   dans `sous_totaux`, au minimum le revenu imposable de période
   (`revenu_imposable_periode`, voir Glossary
   Revenu_Imposable_QC_Periode). LA CalculationTrace de
   `calcul_impot_federal_formule` DOIT exposer, dans `entrees`, au
   minimum `salaire_periode`, `nb_periodes_annuelles` et
   `deduction_rrq_supp` ; dans `sous_totaux`, au minimum le revenu
   imposable de période (`revenu_imposable_periode`, voir Glossary
   Revenu_Imposable_Federal_Periode).
4. LA CalculationTrace de `calcul_impot_qc_retenu` et de
   `calcul_impot_federal_retenu` DOIT exposer, dans `parametres_utilises`,
   au minimum un indicateur de l'état d'exonération effectivement
   appliqué (`exoneration_active`) ; dans `entrees`, au minimum le
   montant formule correspondant (Requirement 3 AC6, Requirement 5 AC6) ;
   dans `sous_totaux`, au minimum la retenue effective
   (`retenue_effective`).
5. CHAQUE CalculationTrace DOIT porter `mode_arrondissement =
   ModeArrondissement.ROUND_HALF_UP`, `precision_arrondissement = 2` et
   `resultat` égal au montant retourné par la fonction.
6. LES trois dictionnaires `parametres_utilises`, `entrees` et
   `sous_totaux` de chaque trace DOIVENT contenir uniquement des valeurs
   `Decimal` ; aucun `float` NE DOIT y apparaître (règle 01).
7. CHAQUE CalculationTrace produite DOIT être suffisante pour permettre
   à un tiers de recalculer manuellement le montant retourné à partir de
   ses seuls contenus, sans consulter ni le `PayrollInput` d'origine ni
   les fichiers `parameters/<AAAA>/*.json`.

---

### Requirement 10: Consommation stricte des paramètres annuels versionnés

**User Story:** En tant que responsable de la mise à jour annuelle des
paramètres fiscaux, je veux que le module de retenues d'impôt lise 100 %
de ses paliers, seuils, constantes et déductions depuis
`parameters/<AAAA>/quebec.json` et `parameters/<AAAA>/canada.json` sans
exception, afin qu'une révision annuelle des barèmes ne nécessite jamais
de retoucher du code Python (règle 05).

#### Acceptance Criteria

1. LE Moteur_Impots DOIT lire, pour la formule QC, l'ensemble des
   paliers progressifs, la déduction pour travailleur annuelle et toute
   constante de conversion nécessaire depuis
   `parametres_annee.impot_quebec` — sans jamais coder en dur un seuil,
   un taux ou une constante représentant un palier d'imposition QC 2026.
2. LE Moteur_Impots DOIT lire, pour la formule fédérale, l'ensemble des
   paliers progressifs et toute constante de conversion nécessaire
   depuis `parametres_annee.impot_federal` — sans jamais coder en dur un
   seuil, un taux ou une constante représentant un palier d'imposition
   fédéral 2026.
3. LE Moteur_Impots DOIT lire le taux effectif de la
   Deduction_RRQ_Supplementaire_Federale depuis
   `parametres_annee.rrq.portion_supplementaire_deductible_fed.taux_effectif`
   et l'exemption par période RRQ depuis
   `parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026` —
   sans jamais coder en dur `Decimal("0.010")` ni `Decimal("129.63")`.
4. LE Moteur_Impots NE DOIT contenir aucune constante numérique
   représentant un palier, un seuil, un taux, une constante d'ajustement
   ou un montant personnel de base fiscal dans son propre code
   (règle 05) — aucune exception, même pour une valeur qui semble stable
   d'une année à l'autre ET même à titre temporaire pendant le
   développement (règle 05 étant absolue et non négociable, aucune
   période de migration ni de placeholder codé en dur n'est tolérée,
   contrairement à ce qui pourrait être admis sur un projet sans cette
   contrainte). LES seules constantes numériques autorisées dans le code
   de cette spec sont l'entier `2` (précision d'arrondissement) et
   `Decimal("0.00")` utilisé comme plancher ou valeur neutre. Si un
   paramètre requis n'est pas encore renseigné dans
   `parameters/<AAAA>/*.json`, LE Moteur_Impots DOIT laisser
   `MissingParameterError` se propager (voir AC5) plutôt que de
   recourir à une valeur par défaut codée en dur.
5. SI un champ consommé par l'AC1, l'AC2 ou l'AC3 est marqué `"TO_FILL"`
   dans le fichier de paramètres, ALORS l'accès à la propriété
   correspondante DOIT lever `MissingParameterError` ; LE Moteur_Impots
   NE DOIT PAS intercepter cette exception ni la convertir en une autre.
6. LES fichiers `parameters/2026/quebec.json` et
   `parameters/2026/canada.json` DOIVENT être mis à jour, préalablement à
   l'implémentation, pour renseigner intégralement tous les champs
   consommés par l'AC1 et l'AC2 (paliers progressifs, déduction pour
   travailleur, montant de l'emploi canadien le cas échéant) avec les
   valeurs publiées par Revenu Québec (TP-1015.F 2026) et l'ARC
   (T4127 2026) — vérification effective réalisée par la phase de
   tâches, préalable obligatoire aux golden tests du Requirement 11.

---

### Requirement 11: Corpus golden — reproduction au cent près

**User Story:** En tant que responsable de la conformité fiscale, je veux
que les quatre montants d'impôt calculés par cette spec reproduisent au
cent près les valeurs validées par WebRAS et PDOC pour les six scénarios
de référence, afin d'avoir une garantie empirique que le moteur produit
des montants corrects avant toute mise en production.

#### Acceptance Criteria

1. POUR CHAQUE scénario du Corpus_Golden (QC001 à QC006),
   `calcul_impot_qc_formule` appliqué au `PayrollInput` et au
   `GainsDecomposes` du scénario DOIT retourner exactement le montant
   `impot_qc_formule.montant` de la fixture de sortie correspondante
   (`tests/fixtures/outputs/qc0*.json`).
2. POUR CHAQUE scénario du Corpus_Golden, `calcul_impot_qc_retenu` DOIT
   retourner exactement le montant `impot_qc_retenu.montant` de la
   fixture.
3. POUR CHAQUE scénario du Corpus_Golden, `calcul_impot_federal_formule`
   DOIT retourner exactement le montant `impot_federal_formule.montant`
   de la fixture.
4. POUR CHAQUE scénario du Corpus_Golden, `calcul_impot_federal_retenu`
   DOIT retourner exactement le montant `impot_federal_retenu.montant`
   de la fixture.
5. POUR CHAQUE `CalculationTrace` retournée sur le Corpus_Golden, le
   champ `resultat` DOIT être égal au montant retourné par la fonction
   correspondante (cohérence trace/montant).
6. LE scénario QC001 DOIT en particulier confirmer `impot_qc_formule ==
   Decimal("104.56")` et `impot_federal_formule == Decimal("86.25")`
   (seul scénario du corpus sans aucune exonération active où les deux
   formules produisent un impôt strictement positif).
7. LES scénarios QC004 et QC006 DOIVENT confirmer
   `impot_qc_formule == Decimal("0.00")` ET `impot_federal_formule ==
   Decimal("0.00")` (comportement sous le seuil d'imposition,
   Requirement 7).

---

### Requirement 12: Cas d'erreur et bornes de validité

**User Story:** En tant que responsable de la robustesse du moteur, je
veux que les cas limites (salaire de période nul, crédit personnel très
élevé, retenue additionnelle non nulle) soient traités de façon
prévisible et testée, afin qu'aucun montant négatif ni aucune exception
inattendue ne puisse survenir en production.

#### Acceptance Criteria

1. LORSQUE `Salaire_Periode = Decimal("0.00")` (paie à brut nul, cas
   théorique), CHACUNE des quatre fonctions DOIT retourner
   `Decimal("0.00")` sans lever d'exception (en l'absence de retenue
   additionnelle non nulle).
2. LORSQUE `payroll_input.retenue_additionnelle_QC_effective` (ou son
   équivalent fédéral) est strictement positive et que l'exonération
   correspondante est active, LA retenue effective retournée par
   `calcul_impot_qc_retenu` (ou `calcul_impot_federal_retenu`) DOIT être
   strictement égale à cette retenue additionnelle, sans lever
   d'exception.
3. ÉTANT DONNÉ que `PayrollInput` impose déjà `ge=Decimal("0")` sur
   `montant_total_TP1015_3_effectif`, `retenue_additionnelle_QC_effective`,
   `montant_total_TD1_effectif` et
   `retenue_additionnelle_federale_effective` (contrat
   `moteur-paie-contrats`), CHACUNE des quatre fonctions DOIT pouvoir
   supposer que ces quatre valeurs reçues en entrée sont toujours non
   négatives, sans re-valider cette contrainte.
4. AUCUNE des quatre fonctions NE DOIT jamais retourner un montant
   strictement négatif, quelles que soient les valeurs valides (au sens
   du contrat `PayrollInput`/`GainsDecomposes`) de ses arguments.
5. LORSQUE `Credit_Personnel_QC_Effectif` (ou son équivalent fédéral) est
   très élevé au point que le revenu imposable annuel de référence
   devienne fortement négatif, LA fonction formule correspondante DOIT
   néanmoins retourner `Decimal("0.00")` sans lever d'exception ni
   produire un résultat négatif (défense en profondeur au-delà du cas
   nominal du Requirement 7).

---

### Requirement 13: Délégation aux garde-fous existants pour les cas hors matrice

**User Story:** En tant que responsable de la robustesse du moteur, je
veux que le module de retenues d'impôt s'appuie sur les refus déjà
portés par `PayrollInput` plutôt que de les redoubler, afin de maintenir
un seul point de vérité pour la définition de la matrice Camp LilySO
(règle 03).

#### Acceptance Criteria

1. LE Moteur_Impots DOIT compter sur le fait qu'un `PayrollInput`
   construit avec succès garantit par construction : province Québec,
   fréquence aux deux semaines, montants TP-1015.3/TD1 non négatifs,
   drapeaux d'exonération booléens valides — sans re-tester ces
   invariants.
2. LE Moteur_Impots DOIT compter sur le fait qu'un `GainsDecomposes`
   construit avec succès garantit par construction que `brut_total ≥ 0`
   — sans re-tester cet invariant.
3. LE Moteur_Impots NE DOIT PAS introduire de nouveau garde-fou
   `UnsupportedPayrollCase` ni de nouvelle validation défensive
   supplémentaire au-delà de ceux déjà couverts par `PayrollInput` et
   `GainsDecomposes` — aucun cas hors matrice n'est identifié pour les
   quatre fonctions de retenue d'impôt dans le périmètre Camp LilySO.
   LE Moteur_Impots DOIT traiter toute entrée reçue via un
   `PayrollInput` et un `GainsDecomposes` construits avec succès comme
   intrinsèquement valide pour ses propres besoins, sans réintroduire de
   contrôle de forme redondant (seule `MissingParameterError`,
   couverte par le Requirement 10, reste une exception légitime hors du
   chemin nominal).

---

### Requirement 14: Plafonnement combiné des retenues additionnelles selon l'espace disponible

**User Story:** En tant que responsable de la conformité fiscale, je
veux que les deux retenues additionnelles volontaires (QC et fédérale)
soient mises à 0 $ ensemble — jamais réduites partiellement, jamais
départagées par une priorité entre juridictions — lorsque leur somme
dépasse l'espace réellement disponible sur le brut de la paie, afin
d'éviter qu'une paie produise un net négatif ou une situation
incohérente que ni PDOC ni WebRAS ne savent traiter.

**Contexte et décision de périmètre** : cette règle est une **décision
opérationnelle du projet Camp LilySO**, actée avec l'employeur après
une recherche documentaire dont le résultat est infructueux —
consignée dans `docs/journal-validation.md` (entrée « Recherche
documentaire sur le plafonnement combiné des retenues additionnelles »).
Ni le TP-1015.F 2026 (Revenu Québec) ni le T4127 2026/T4001 (ARC) ne
prescrivent de traitement pour ce cas ; PDOC refuse de calculer le cas
testé manuellement par l'employeur (brut 100 $, retenues additionnelles
75 $ QC + 75 $ fédéral), et WebRAS ne valide rien de plus. Cette règle
**ne doit jamais être présentée comme une règle fiscale officielle**
dans le code, les traces de calcul, ni la documentation destinée à un
tiers ou un auditeur — voir Requirement 9 (aucune nouvelle source de
trace officielle n'est inventée par ce mécanisme).

#### Acceptance Criteria

1. `calcul_impot_qc_retenu` et `calcul_impot_federal_retenu` DOIVENT
   chacune accepter un 4e paramètre positionnel obligatoire
   `additionnelle_permise: bool`, sans valeur par défaut, en plus des
   trois paramètres existants (`payroll_input`, `gains`,
   `parametres_annee`) — signature complète :
   `(payroll_input: PayrollInput, gains: GainsDecomposes, parametres_annee: ParametresAnnee, additionnelle_permise: bool) -> tuple[Decimal, CalculationTrace]`.
   `calcul_impot_qc_formule` et `calcul_impot_federal_formule` NE SONT
   PAS modifiées par ce Requirement et conservent leur signature à 3
   paramètres (Requirement 1).
2. LORSQUE `additionnelle_permise == False`, LE Moteur_Impots DOIT
   forcer la retenue additionnelle correspondante
   (`payroll_input.retenue_additionnelle_QC_effective` pour
   `calcul_impot_qc_retenu`, `payroll_input.retenue_additionnelle_federale_effective`
   pour `calcul_impot_federal_retenu`) à `Decimal("0.00")` dans le
   calcul de la retenue effective retournée — le montant de base
   (post-exonération, résultat du court-circuit d'exonération existant
   du Requirement 3 / Requirement 5) DOIT rester inchangé et continuer
   à suivre son propre court-circuit d'exonération existant,
   indépendamment de `additionnelle_permise`.
3. LORSQUE `additionnelle_permise == True` (cas normal, majoritaire),
   LE Moteur_Impots DOIT produire un comportement **strictement
   identique** à celui déjà spécifié par le Requirement 3 (QC) et le
   Requirement 5 (fédéral) avant l'introduction de ce Requirement —
   rétrocompatibilité totale du chemin nominal.
4. LE calcul de la valeur booléenne `additionnelle_permise` NE
   RELÈVE PAS de `payroll_engine/impot_qc.py` ni de
   `payroll_engine/impot_federal.py` : ces deux modules n'ont pas la
   vue transversale nécessaire (aucun accès aux montants RRQ, RQAP, AE,
   ni à l'impôt de base de l'autre juridiction). CE calcul DOIT être
   effectué exclusivement par l'orchestrateur
   `payroll_engine/net_pay.py::assembler_paie` (spec
   `net-cumuls-registre`), seul composant disposant de cette vue
   complète, qui le transmet en 4e argument aux deux fonctions de
   retenue.
5. LE mécanisme de plafonnement introduit par ce Requirement NE DOIT
   PAS inventer de nouvelle source de `CalculationTrace` officielle :
   `trace.source` de `calcul_impot_qc_retenu` DOIT continuer à commencer
   par `"TP-1015.F 2026"` et celui de `calcul_impot_federal_retenu` par
   `"T4127 2026"`, exactement comme avant ce Requirement (Requirement 9)
   — ce mécanisme modifie une entrée du calcul déjà tracé, il n'invente
   pas une source distincte.
6. LA `CalculationTrace` retournée par `calcul_impot_qc_retenu` et
   `calcul_impot_federal_retenu` DOIT exposer, dans
   `parametres_utilises`, un nouveau champ `additionnelle_permise` égal
   à `Decimal("1")` si `additionnelle_permise == True`, ou
   `Decimal("0")` si `additionnelle_permise == False` (même convention
   que le champ existant `exoneration_active`).
7. LA `CalculationTrace` retournée par `calcul_impot_qc_retenu` et
   `calcul_impot_federal_retenu` DOIT continuer à exposer, dans
   `entrees`, la retenue additionnelle **originale demandée** (avant
   tout plafonnement — `payroll_input.retenue_additionnelle_QC_effective`
   ou son équivalent fédéral, inchangée), ET DOIT exposer, dans
   `sous_totaux`, un nouveau sous-total `retenue_additionnelle_appliquee`
   distinct — égal à la retenue additionnelle originale lorsque
   `additionnelle_permise == True`, et égal à `Decimal("0.00")` lorsque
   `additionnelle_permise == False` — de sorte qu'un tiers auditeur
   puisse voir qu'une retenue additionnelle a été demandée puis refusée,
   et non simplement observer un montant nul sans explication
   (auto-suffisance de la trace, cohérent avec le Requirement 9.7).
8. CE Requirement NE MODIFIE PAS le comportement de
   `calcul_impot_qc_formule` ni de `calcul_impot_federal_formule`
   (Requirement 2, Requirement 4) : le montant théorique de la formule
   demeure calculé identiquement, sans lecture d'`additionnelle_permise`
   (paramètre qu'elles ne reçoivent pas).
