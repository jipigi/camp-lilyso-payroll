# Implementation Plan: impots-retenues-source

<!-- Plan d'implémentation — spec « impôt retenu à la source (QC et fédéral) »
     du moteur de paie Camp LilySO. Les en-têtes structurels (Overview, Tasks,
     Notes, Task Dependency Graph) sont maintenus en anglais pour conformité
     au format Kiro. Le contenu métier est en français. -->

## Overview

Cette spec livre **l'étape 4 du plan d'implémentation** (`docs/plan-implementation.md`), immédiatement après `cotisations-sociales-qc` (étape 3, complétée à 100 %) : quatre fonctions pures — `calcul_impot_qc_formule`, `calcul_impot_qc_retenu` (`payroll_engine/impot_qc.py`), `calcul_impot_federal_formule`, `calcul_impot_federal_retenu` (`payroll_engine/impot_federal.py`) — qui calculent les retenues d'impôt à la source Québec (TP-1015.F 2026) et fédérale (T4127 2026), à partir d'un `PayrollInput` figé, du `GainsDecomposes` produit par l'étape 2, et des paramètres annuels versionnés.

**Aucun contrat** des socles `moteur-paie-contrats` et `cotisations-sociales-qc` n'est modifié : cette spec **consomme** exclusivement `PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `Juridiction`, `ModeArrondissement`, `MissingParameterError`, `ParametresAnnee`/`RRQParametres`/`RQAPParametres`/`AEParametres`. Seuls `ImpotQCParametres` et `ImpotFederalParametres` (déjà en `extra="allow"`) sont étendus de façon strictement additive avec un nouveau sous-modèle partagé `Palier`.

**Découverte de conception déterminante** (design.md §Overview) : le mécanisme fédéral officiel T4127 Option 1 exige, pour un résident du Québec, le crédit personnel K1 **et** le crédit K2Q (cotisations RRQ base/AE/RQAP) **et** le crédit K4 (montant canadien pour emploi), suivis de l'abattement du Québec (16,5 %) — un simple crédit personnel K1 seul ne reproduit pas les montants golden (`86,25 $` sur QC001). Ce mécanisme impose deux nouveaux champs de paramètres non anticipés dans les requirements : `plafond_cotisation_base_rrq_annuel` et `taux_abattement_quebec` (section `impot_federal` de `parameters/2026/canada.json`).

L'ordre suit strictement la règle 06 : **tests avant code**, puis **mise à jour bloquante des paramètres officiels 2026** avant que les golden tests ne puissent passer, puis extension du chargeur de paramètres, puis implémentation.

**Livrables** :

- Extension de `tests/strategies.py` (`st_credit_personnel_eleve`, `st_parametres_annee_impot_avec_to_fill`)
- `tests/payroll_engine/test_impot_qc.py`, `test_impot_federal.py` (property tests + tests d'exemple, dont Property 11 — court-circuit véritable par mock)
- Extension de `tests/test_golden_outputs.py` (paramétrage des quatre champs d'impôt sur QC001–QC006)
- Extension de `tests/test_guards.py` (10 nouvelles classes de garde statique)
- Extension de `parameters/2026/quebec.json` (section `impot_quebec`) et `parameters/2026/canada.json` (section `impot_federal`) avec les valeurs officielles TP-1015.F 2026 / T4127 2026 122e édition
- Extension de `tests/payroll_engine/test_parameters_loader.py` (nouveau sous-modèle `Palier`, propagation de contexte)
- Extension de `payroll_engine/parameters_loader.py` (`Palier`, `ImpotQCParametres`, `ImpotFederalParametres`, `_propager_contexte`)
- `payroll_engine/impot_qc.py`, `payroll_engine/impot_federal.py` (implémentation, quatre fonctions au total)
- Mise à jour des sous-champs `trace` de `tests/fixtures/outputs/qc002.json`–`qc006.json` (montants inchangés)
- Entrée dans `docs/journal-validation.md` (validation manuelle WebRAS/PDOC, QC001)

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — `Decimal` de bout en bout, aucun `float` dans les modules ni dans leurs tests
- Règle 02 — retour `(Decimal, CalculationTrace)` avec `source` conforme à la liste blanche de `CalculationTrace` (`"TP-1015.F 2026, ..."`, `"T4127 2026, ..."`)
- Règle 03 — aucun nouveau garde-fou `UnsupportedPayrollCase` (délégation totale aux garde-fous de `PayrollInput`/`GainsDecomposes`)
- Règle 04 — corpus anonymisé QC001–QC006 déjà en place, aucune donnée personnelle réintroduite
- Règle 05 — tous les paliers, taux, déductions et abattements lus exclusivement depuis `parametres_annee.impot_quebec`/`.impot_federal`/`.rrq`/`.rqap`/`.assurance_emploi`, jamais codés en dur ; source officielle et date de consultation consignées dans chaque fichier JSON
- Règle 06 — sections 1 à 8 (tests, golden, garde, paramètres, chargeur) rédigées et vérifiées **rouges avant** les sections 9 à 10 (implémentation) ; validation manuelle en section 12

## Tasks

- [x] 1. Préparer les stratégies Hypothesis dédiées à l'impôt
  - [x] 1.1 Étendre `tests/strategies.py` avec les stratégies crédit personnel élevé et paramètres avec `TO_FILL` ciblé côté impôt
    - Ajouter `st_credit_personnel_eleve()` — génère des valeurs de `montant_total_TP1015_3_effectif`/`montant_total_TD1_effectif` biaisées vers des montants très élevés (jusqu'à plusieurs centaines de milliers de dollars, via `st.one_of` incluant des bornes proches du revenu annualisé maximal généré), afin d'exercer le comportement sous le seuil d'imposition (Property 8) et la défense en profondeur du Requirement 12.5 sans dépendre du corpus golden
    - Ajouter `st_parametres_annee_impot_avec_to_fill(champ)` — construit une variante de `ParametresAnnee` où un champ ciblé parmi `impot_quebec.paliers[i].taux`, `impot_quebec.paliers[i].constante_k`, `impot_quebec.taux_credits_convertibles`, `impot_quebec.deduction_pour_travailleur_annuelle`, `impot_federal.paliers[i].taux`, `impot_federal.taux_credits_convertibles`, `impot_federal.montant_emploi_canadien_annuel`, `impot_federal.plafond_cotisation_base_rrq_annuel`, `impot_federal.taux_abattement_quebec` porte la sentinelle `"TO_FILL"`, utilisée par Property 13
    - Réutiliser `st_payroll_input_et_gains()` et `st_parametres_annee_2026_qc_ca()` (héritées de `cotisations-sociales-qc`, sans modification)
    - Documenter chaque nouvelle stratégie par un docstring citant le design §Testing Strategy « Stratégies Hypothesis » et la règle 01
    - _Requirements: 8.1 (P8), 10.5 (P13), 12.5_
    - _Design: §Testing Strategy « Stratégies Hypothesis »_

- [x] 2. Property-based tests et tests d'exemple de `impot_qc.py` (`tests/payroll_engine/test_impot_qc.py`)
  - [x] 2.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteRobustesse`)
    - Module docstring citant le design §Testing Strategy, la liste des propriétés couvertes par ce fichier (Property 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13 — variantes QC), et le rappel que ce fichier est écrit **avant** `payroll_engine/impot_qc.py` (règle 06)
    - Imports : `pytest`, `Decimal`, `hypothesis` (`given`, `settings`), `unittest.mock.patch`, les modèles consommés (`PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `Juridiction`, `ModeArrondissement`, `MissingParameterError`), les stratégies de `tests/strategies.py`
    - Fixture module-scoped pour `st_parametres_annee_2026_qc_ca()`
    - **Property 1 : Déterminisme** — deux appels à `calcul_impot_qc_formule` (puis `calcul_impot_qc_retenu`) avec les mêmes arguments produisent deux tuples égaux au sens `==`
    - **Property 2 : Absence d'exception sur entrée valide** — aucun rejet pour tout `PayrollInput`/`GainsDecomposes`/`ParametresAnnee` 2026 valides, y compris cas extrêmes (salaire nul, crédit personnel nul ou élevé via `st_credit_personnel_eleve`, retenue additionnelle nulle ou élevée)
    - **Property 3 : Forme `Decimal` du résultat et de la trace** — le montant retourné et chaque valeur de `trace.parametres_utilises`/`entrees`/`sous_totaux`/`resultat` sont des `Decimal` finis, égaux à leur propre `.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`
    - Test d'exemple : import de `calcul_impot_qc_formule`, `calcul_impot_qc_retenu` sans effet de bord (aucune E/S, aucun appel réseau, aucune action au moment de l'import)
    - Annotation de chaque test : `# Feature: impots-retenues-source, Property N: <titre>`
    - _Requirements: 1.1, 1.4, 1.6, 1.7, 1.8, 1.9, 2.6, 2.7, 3.4, 3.5_
    - _Design: §Correctness Properties 1, 2, 3 ; §Components §1_

  - [x] 2.2 Tests de la formule QC — assiette, palier, crédit personnel, bornes et seuil d'imposition (classe `TestFormuleQc`)
    - **Property 5 : Formule QC — assiette, palier et crédit personnel** — `revenu_imposable_periode == max(0, brut_total - deduction_pour_travailleur_annuelle/nb_periodes)`, `impot_annuel_base == max(0, taux_palier × revenu_imposable_annuel - constante_k)` (dernier palier dont `seuil_bas_annuel <= revenu_imposable_annuel`), `impot_annuel_net == impot_annuel_base - taux_credits_convertibles × montant_total_TP1015_3_effectif`, `resultat == max(0, arrondir(impot_annuel_net / nb_periodes))` — reconstruction intégrale à partir des seules valeurs de `trace`
    - **Property 4 (variante QC) : Montant jamais strictement négatif** — `calcul_impot_qc_formule(...)[0] >= Decimal("0.00")` pour tout argument valide
    - **Property 8 (variante QC) : Comportement sous le seuil d'imposition** — avec `st_credit_personnel_eleve()`, lorsque le revenu imposable annuel devient inférieur ou égal au crédit personnel effectif, `calcul_impot_qc_formule` retourne `Decimal("0.00")` sans exception, indépendamment de `exoneration_TP1015_3_effectif`
    - **Property 9 (variante QC) : Non-consultation des champs d'exonération/retenue additionnelle** — pour toute paire de `PayrollInput` identiques sauf sur `exoneration_TP1015_3_effectif`/`retenue_additionnelle_QC_effective`, `calcul_impot_qc_formule` retourne des résultats identiques (montant et trace)
    - Test d'exemple : reproduction chiffrée de QC004 — revenu annualisé inférieur au crédit personnel, `exoneration_TP1015_3_effectif = False`, résultat `Decimal("0.00")` par la seule formule (Requirement 7.3)
    - Annotations pour chacune des quatre propriétés
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8, 7.1, 7.2, 7.3, 9.7, 12.4, 12.5_
    - _Design: §Correctness Properties 4, 5, 8, 9 ; §Components §2_

  - [x] 2.3 Tests du court-circuit d'exonération et de la retenue additionnelle QC (classe `TestRetenueQc`)
    - **Property 10 (variante QC) : Court-circuit d'exonération et ajout de la retenue additionnelle** — si `exoneration_TP1015_3_effectif == True`, `calcul_impot_qc_retenu` retourne exactement `payroll_input.retenue_additionnelle_QC_effective` ; si `False`, retourne exactement `calcul_impot_qc_formule(...)[0] + retenue_additionnelle_QC_effective` — dans les deux cas la retenue additionnelle s'ajoute inconditionnellement
    - **Property 11 (variante QC) : Court-circuit véritable** — pour tout `PayrollInput` avec `exoneration_TP1015_3_effectif == True`, un espion (`unittest.mock.patch`) posé sur `calcul_impot_qc_formule` dans le module `impot_qc` n'est **jamais appelé** lors de l'exécution de `calcul_impot_qc_retenu`
    - Test d'exemple : `retenue_additionnelle_QC_effective` strictement positive et exonération active → retenue effective strictement égale à cette retenue additionnelle (Requirement 12.2)
    - Annotations pour chacune des deux propriétés
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 12.2_
    - _Design: §Correctness Properties 10, 11 ; §Components §3_

  - [x] 2.4 Tests de trace des deux fonctions QC (classe `TestTraceQc`)
    - **Property 12 (variante QC) : Contenu minimal et cohérence de la trace** — `trace.source` matche `^TP-1015\.F \d{4}` ; `trace.annee == payroll_input.pay_period.annee_fiscale` ; `trace.juridiction == Juridiction.QUEBEC` ; `trace.section` distingue « formule » de « retenu » ; pour la formule, `entrees` contient au minimum `salaire_periode`/`nb_periodes_annuelles` et `sous_totaux` contient `revenu_imposable_periode` ; pour la retenue, `parametres_utilises` contient `exoneration_active`, `entrees` contient `impot_qc_formule`, `sous_totaux` contient `retenue_effective` ; `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`, `trace.precision_arrondissement == 2`, `trace.resultat` égal au montant retourné
    - Annotation : `# Feature: impots-retenues-source, Property 12: Contenu minimal et cohérence de la trace (QC)`
    - _Requirements: 3.6, 9.1, 9.2, 9.3, 9.4, 9.5_
    - _Design: §Correctness Properties 12 ; §Components §2, §3_

  - [x] 2.5 Test de propagation de `MissingParameterError` pour l'impôt QC (classe `TestMissingParameterImpotQc`)
    - **Property 13 (variante QC)** — pour un `ParametresAnnee` construit via `st_parametres_annee_impot_avec_to_fill` avec un champ `impot_quebec.paliers[i].taux`, `.constante_k`, `.taux_credits_convertibles` ou `.deduction_pour_travailleur_annuelle` marqué `"TO_FILL"`, l'appel à `calcul_impot_qc_formule` (et par délégation `calcul_impot_qc_retenu` lorsque l'exonération est inactive) lève `MissingParameterError` non interceptée
    - Annotation : `# Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt QC)`
    - _Requirements: 1.8, 10.5_
    - _Design: §Correctness Properties 13 ; §Error Handling_

- [x] 3. Property-based tests et tests d'exemple de `impot_federal.py` (`tests/payroll_engine/test_impot_federal.py`)
  - [x] 3.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteRobustesse`)
    - Même structure que la tâche 2.1, appliquée à `calcul_impot_federal_formule` et `calcul_impot_federal_retenu`
    - **Property 1, 2, 3** (déterminisme, absence d'exception, forme `Decimal`) appliquées aux deux fonctions fédérales
    - Annotations correspondantes
    - _Requirements: 1.2, 1.4, 1.6, 1.7, 1.8, 1.9, 4.7, 4.8, 5.4, 5.5_
    - _Design: §Correctness Properties 1, 2, 3 ; §Components §1_

  - [x] 3.2 Tests de la Deduction_RRQ_Supplementaire_Federale et de l'assiette fédérale (classe `TestAssietteFederale`)
    - **Property 6 : Deduction_RRQ_Supplementaire_Federale et assiette** — `deduction_rrq_supp == taux_effectif_rrq_supp × max(0, brut_total - exemption_par_periode_rrq)` et `revenu_imposable_periode == brut_total - deduction_rrq_supp`, exposés tels quels dans `trace.entrees`/`trace.sous_totaux`
    - **Property 4 (variante fédérale) : Montant jamais strictement négatif** — `calcul_impot_federal_formule(...)[0] >= Decimal("0.00")` pour tout argument valide
    - Test d'exemple : reproduction chiffrée de la Deduction_RRQ_Supplementaire_Federale sur QC001 (`13,87 $ = 1,00 % × (1 516,32 $ − 129,63 $)`, confirmée PDOC — voir Glossary requirements)
    - Annotations pour chacune des deux propriétés
    - _Requirements: 4.1, 4.2, 4.7, 4.8, 9.3, 12.4_
    - _Design: §Correctness Properties 4, 6 ; §Components §4_

  - [x] 3.3 Tests du mécanisme K1 + K2Q + K4, de l'abattement du Québec et du seuil d'imposition (classe `TestMecanismeK1K2QK4`)
    - **Property 7 : Mécanisme K1 + K2Q + K4 et abattement du Québec** — `impot_annuel_base == max(0, taux_palier × revenu_imposable_annuel - constante_k - k1 - k2q - k4)`, où `k1 == taux_credits_convertibles × montant_total_TD1_effectif`, `k4 == taux_credits_convertibles × min(revenu_imposable_annuel, montant_emploi_canadien_annuel)`, et `k2q` calculé exclusivement à partir de `gains.brut_total`, `nb_periodes_annuelles` et des sections `parametres_annee.rrq`/`.rqap`/`.assurance_emploi` (jamais via `payroll_input.cumuls_debut` ni un appel à `calcul_rrq_employe`/`calcul_rqap_employe`/`calcul_ae_employe`) ; `impot_annuel_net == impot_annuel_base - taux_abattement_quebec × impot_annuel_base`
    - **Property 8 (variante fédérale) : Comportement sous le seuil d'imposition** — avec `st_credit_personnel_eleve()` appliqué à `montant_total_TD1_effectif`, `calcul_impot_federal_formule` retourne `Decimal("0.00")` sans exception, indépendamment de `exoneration_TD1_effective`
    - **Property 9 (variante fédérale) : Non-consultation des champs d'exonération/retenue additionnelle** — pour toute paire de `PayrollInput` identiques sauf sur `exoneration_TD1_effective`/`retenue_additionnelle_federale_effective`, `calcul_impot_federal_formule` retourne des résultats identiques
    - Test d'exemple : reproduction chiffrée de K1/K2Q/K4 sur QC001 conforme à la vérification numérique du design §Overview (`K1 ≈ 2 303,28 $`, `K2Q ≈ 377,08 $`, `K4 ≈ 210,14 $`, `T ≈ 86,25 $` après abattement)
    - Test d'exemple : reproduction chiffrée de QC004/QC006 — `impot_federal_formule == Decimal("0.00")` (Requirement 7.3, 11.7)
    - Annotations pour chacune des trois propriétés
    - _Requirements: 4.3, 4.4, 4.6, 4.9, 6.3, 7.1, 7.2, 7.3, 9.7, 12.5_
    - _Design: §Correctness Properties 7, 8, 9 ; §Components §4_

  - [x] 3.4 Tests du court-circuit d'exonération et de la retenue additionnelle fédérale (classe `TestRetenueFederale`)
    - **Property 10 (variante fédérale) : Court-circuit d'exonération et ajout de la retenue additionnelle** — même gabarit que la tâche 2.3, substituant `exoneration_TD1_effective`, `retenue_additionnelle_federale_effective`, `calcul_impot_federal_formule`
    - **Property 11 (variante fédérale) : Court-circuit véritable** — espion posé sur `calcul_impot_federal_formule` dans le module `impot_federal`, jamais appelé lorsque `exoneration_TD1_effective == True`
    - Test d'exemple : `retenue_additionnelle_federale_effective` strictement positive et exonération active → retenue effective strictement égale à cette retenue additionnelle
    - Annotations pour chacune des deux propriétés
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 12.2_
    - _Design: §Correctness Properties 10, 11 ; §Components §5_

  - [x] 3.5 Tests de trace des deux fonctions fédérales (classe `TestTraceFederale`)
    - **Property 12 (variante fédérale)** — même gabarit que la tâche 2.4 : `trace.source` matche `^T4127 \d{4}`, `trace.juridiction == Juridiction.CANADA`, `entrees` de la formule contient au minimum `salaire_periode`/`nb_periodes_annuelles`/`deduction_rrq_supp`, `sous_totaux` contient `revenu_imposable_periode`
    - Annotation : `# Feature: impots-retenues-source, Property 12: Contenu minimal et cohérence de la trace (fédéral)`
    - _Requirements: 5.6, 9.1, 9.2, 9.3, 9.4, 9.5_
    - _Design: §Correctness Properties 12 ; §Components §4, §5_

  - [x] 3.6 Test de propagation de `MissingParameterError` pour l'impôt fédéral (classe `TestMissingParameterImpotFederal`)
    - **Property 13 (variante fédérale)** — champs `impot_federal.paliers[i].taux`, `.taux_credits_convertibles`, `.montant_emploi_canadien_annuel`, `.plafond_cotisation_base_rrq_annuel`, `.taux_abattement_quebec` marqués `"TO_FILL"` via `st_parametres_annee_impot_avec_to_fill`
    - Annotation : `# Feature: impots-retenues-source, Property 13: Propagation de MissingParameterError (impôt fédéral)`
    - _Requirements: 1.8, 10.5_
    - _Design: §Correctness Properties 13 ; §Error Handling_

- [x] 4. Golden test de reproduction du corpus QC001–QC006
  - [x] 4.1 Étendre `tests/test_golden_outputs.py` avec `test_impots_reproduisent_fixture`
    - Nouveau test paramétré `@pytest.mark.golden @pytest.mark.parametrize("scenario_id", ["QC001", ..., "QC006"])`, import local des quatre fonctions (`calcul_impot_qc_formule`, `calcul_impot_qc_retenu`, `calcul_impot_federal_formule`, `calcul_impot_federal_retenu`) pour ne pas faire échouer la collecte tant que les modules n'existent pas
    - Chargement `PayrollInput` (fixture d'entrée), `GainsDecomposes` (reconstruit depuis la section `gains` de la fixture de sortie), `ParametresAnnee` réel 2026 (Québec et Canada)
    - Assertions d'égalité stricte sur les quatre champs `retenues_employe.{impot_qc_formule,impot_qc_retenu,impot_federal_formule,impot_federal_retenu}.montant`
    - Assertion `trace.resultat == montant` pour au moins `impot_qc_formule` (cohérence trace/montant, Requirement 11.5)
    - Assertion dédiée QC001 : `impot_qc_formule == Decimal("104.56")` ET `impot_federal_formule == Decimal("86.25")` (Requirement 11.6)
    - Assertion dédiée QC004 et QC006 : `impot_qc_formule == Decimal("0.00")` ET `impot_federal_formule == Decimal("0.00")` (Requirement 11.7)
    - Docstring citant le comportement sous le seuil d'imposition (Requirement 7) et la limitation « ce test nécessite les paramètres 2026 intégralement renseignés — voir tâche 6 »
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_
    - _Design: §Testing Strategy « Détail des golden tests »_

- [x] 5. Tests de garde statique des deux nouveaux modules (`tests/test_guards.py`)
  - [x] 5.1 Ajouter les classes `TestImpotQCNoFloat`, `TestImpotFederalNoFloat`
    - Parser chacun des deux modules avec `ast.parse` (motif identique à `TestRrqNoFloat`)
    - Vérifier l'absence de `ast.Constant(value=float(...))`, l'absence d'appel `Decimal(<non-str>)`, l'absence d'appel `round`/`math.floor`/`math.ceil`/`math.trunc`
    - Vérifier que chaque signature publique retourne `tuple[Decimal, CalculationTrace]` sans paramètre par défaut
    - _Requirements: 2.6, 3.5, 4.7, 5.5_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 5.2 Ajouter les classes `TestImpotQCNoHardcodedFiscalValues`, `TestImpotFederalNoHardcodedFiscalValues`
    - Lecture ligne par ligne de chaque module ; vérifier l'absence de toute constante `Decimal` autre que `Decimal("0.00")` (plancher/valeur neutre) et l'entier `2` (précision d'arrondissement) — cohérent avec `TestRrqNoHardcodedFiscalValues`
    - Étendre les motifs interdits partagés (`_MOTIFS_FISCAUX_INTERDITS`) pour couvrir les paliers, crédits convertibles, déduction pour travailleur et abattement du Québec 2026 une fois ces valeurs connues (tâche 6)
    - _Requirements: 10.4_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 5.3 Ajouter les classes `TestImpotQCNoLoadParametersCall`, `TestImpotFederalNoLoadParametersCall`
    - Grep du fichier source pour vérifier l'absence du token `load_parameters` (ni import, ni appel), l'absence d'ouverture de fichier (`open(`, `json.load`, `Path(...).read_text()`), l'absence de `datetime.now()`, `random.*`, `os.environ`, l'absence de variable de module mutable
    - _Requirements: 1.5_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 5.4 Ajouter la classe `TestImpotFederalNoRrqRqapAeFunctionCalls`
    - Grep de `impot_federal.py` pour vérifier l'absence des tokens `calcul_rrq_employe`, `calcul_rqap_employe`, `calcul_ae_employe` (les sections de paramètres `parametres_annee.rrq`/`.rqap`/`.assurance_emploi` restent lisibles, seul l'appel de fonction est prohibé)
    - Vérifier également l'absence d'import des modules `payroll_engine.rrq`, `payroll_engine.rqap`, `payroll_engine.assurance_emploi`
    - _Requirements: 6.3_
    - _Design: §Testing Strategy « Détail des tests de garde » ; §Error Handling « Ce que les quatre fonctions NE font PAS »_

  - [x] 5.5 Ajouter la classe transversale `TestImpotNoUnsupportedPayrollCase`
    - Grep des deux modules (`impot_qc.py`, `impot_federal.py`) pour vérifier l'absence du token `UnsupportedPayrollCase` — aucun nouveau garde-fou introduit par cette spec (Requirement 13.3)
    - _Requirements: 13.1, 13.2, 13.3_
    - _Design: §Error Handling « Aucun nouveau garde-fou »_

- [x] 6. Mise à jour bloquante des paramètres officiels 2026 (Requirement 10.6)
  - [x] 6.1 Rechercher et renseigner `parameters/2026/quebec.json`, section `impot_quebec`
    - Consulter le TP-1015.F 2026 (Revenu Québec, `revenuquebec.ca/fr/entreprises/retenues-a-la-source-et-cotisations-de-lemployeur/trousse-employeur/principaux-changements-pour-2026-trousse-employeur` et `revenuquebec.ca/.../tp-1015-f-v/`)
    - Renseigner `paliers` (4 tranches confirmées pour 2026, seuils indexés inchangés en taux) : `[0 ; 54345,00]` à 14 %, `]54345,00 ; 108680,00]` à 19 %, `]108680,00 ; 132245,00]` à 24 %, `]132245,00 ; ∞]` à 25,75 % — calculer et vérifier `constante_k` pour chaque palier selon la méthode K du design (`constante_k[i] = constante_k[i-1] + seuil_bas[i] × (taux[i] − taux[i-1])`, `constante_k[0] = 0`), en confirmant chaque valeur contre le TP-1015.F 2026 officiel (ne pas se fier uniquement au calcul dérivé — vérifier l'arrondissement officiel de chaque constante)
    - Renseigner `taux_credits_convertibles` (taux du premier palier, `0.14` pour 2026, à confirmer contre le TP-1015.F)
    - Renseigner `deduction_pour_travailleur_annuelle` — consulter la section « Déduction pour un travailleur » du TP-1015.F 2026 ; la valeur doit reproduire `67,57 $` de déduction par période sur QC001 (`67,57 × 27 ≈ 1 824,39 $` annuel, valeur exacte à confirmer contre le guide officiel, pas seulement dérivée de QC001)
    - Renseigner `regles_arrondissement` (texte documentaire, ex. `"ROUND_HALF_UP à 2 décimales, TP-1015.F 2026 section 4"`)
    - Retirer `statut: "TO_FILL_FORMULE"`, ajouter `statut: "VALIDE_TP1015F_2026"` une fois tous les champs renseignés
    - Renseigner les champs racine `date_consultation` et `url_consultee` (actuellement `"TO_FILL"`) avec la date effective de consultation et l'URL exacte de la page consultée
    - _Requirements: 10.1, 10.6_
    - _Design: §Data Models « Extension de ImpotQCParametres » ; règle 05_

  - [x] 6.2 Rechercher et renseigner `parameters/2026/canada.json`, section `impot_federal`
    - Consulter le T4127, 122e édition, en vigueur le 1er janvier 2026 (`canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan/`)
    - Renseigner `paliers` (5 tranches fédérales 2026) : `[0 ; 58523,00]` à 14 %, `]58523,00 ; 117045,00]` à 20,5 %, `]117045,00 ; 181440,00]` à 26 %, `]181440,00 ; 258482,00]` à 29 %, `]258482,00 ; ∞]` à 33 % — calculer et vérifier `constante_k` pour chaque palier selon la même méthode K, en confirmant chaque valeur contre la Table 8.1 du T4127 2026 officiel (ne pas se fier uniquement au calcul dérivé)
    - Renseigner `taux_credits_convertibles` (`0.14`, taux du premier palier fédéral 2026, à confirmer)
    - Renseigner `montant_emploi_canadien_annuel` (montant canadien pour emploi, CEA 2026 — `1 501,00 $` d'après la Table 8.2 du T4127 2026, à confirmer contre le guide officiel plutôt que la seule vérification numérique du design)
    - Renseigner `plafond_cotisation_base_rrq_annuel` (**nouveau champ**, T4127 Table 8.4 ligne QPP — plafond annuel de la cotisation RRQ *au taux de base seul*, distinct de `parametres_annee.rrq.cotisation_max_annuelle_employe` qui porte le taux total incluant la portion supplémentaire ; le taux de base seul et le MGA/exemption 2026 déjà présents dans `quebec.json` permettent de calculer une valeur candidate à vérifier contre le T4127)
    - Renseigner `taux_abattement_quebec` (**nouveau champ**, `0.165` — abattement du Québec, T4127 Table 8.2 ligne QC, valeur stable historiquement mais à confirmer contre l'édition 2026)
    - Renseigner `regles_arrondissement` (texte documentaire)
    - Retirer `statut: "TO_FILL_FORMULE"`, ajouter `statut: "VALIDE_T4127_2026"` une fois tous les champs renseignés
    - Renseigner les champs racine `date_publication`, `date_consultation` et `url_consultee` (actuellement `"TO_FILL"`)
    - _Requirements: 10.2, 10.3, 10.6_
    - _Design: §Data Models « Extension de ImpotFederalParametres » ; règle 05_

  - [x] 6.3 Vérifier la cohérence croisée des deux fichiers de paramètres mis à jour
    - Confirmer que `montant_personnel_base` (déjà présent, non consommé par cette spec) reste inchangé dans les deux fichiers (18 952,00 $ QC, 16 452,00 $ fédéral)
    - Confirmer qu'aucun champ existant consommé par `cotisations-sociales-qc` (`rrq`, `rqap`, `assurance_emploi`) n'a été modifié par cette tâche — extension strictement additive
    - Documenter dans le champ `commentaire` de chaque section la référence exacte de la source (numéro d'édition, date d'entrée en vigueur)
    - _Requirements: 10.6_
    - _Design: §Overview « Application explicite des 6 règles steering », règle 05_

- [x] 7. Extension du chargeur de paramètres (`payroll_engine/parameters_loader.py`)
  - [x] 7.1 Écrire les tests d'exemple du nouveau sous-modèle `Palier` et de l'extension des sections impôt (`tests/payroll_engine/test_parameters_loader.py`)
    - Ajouter les classes `TestPalierMaterialisation`, `TestPropagationContextePalier`, `TestExtensionImpotQCParametres`, `TestExtensionImpotFederalParametres`, suivant le patron déjà en place (`TestValeurToFill`, `TestChargementNominal`)
    - Test d'exemple : un `Palier` construit avec `seuil_bas_annuel`, `taux`, `constante_k` valides matérialise chaque propriété en `Decimal` (pas de `float` intermédiaire)
    - Test d'exemple : un `Palier` dont un champ porte `"TO_FILL"` lève `MissingParameterError` avec un chemin JSON actionnable de la forme `"impot_quebec.paliers[<index>].<champ>"` (propagation de contexte, Requirement 10.5)
    - Test d'exemple : `ParametresAnnee._propager_contexte` injecte correctement `_contexte_annee`/`_contexte_juridiction`/`_contexte_fichier`/`_contexte_section` sur chaque `Palier` imbriqué de `impot_quebec.paliers` et `impot_federal.paliers`, sans régresser la propagation des 13 sections existantes (test de non-régression citant explicitement les sections déjà couvertes par `moteur-paie-contrats` tâche 12.2)
    - Test d'exemple : `ImpotQCParametres.paliers` et `ImpotFederalParametres.paliers` acceptent une liste de plusieurs `Palier` triés par `seuil_bas_annuel` croissant, sans validation d'ordre imposée par le code (invariant documenté, pas vérifié — voir design §Architecture)
    - Test d'exemple : `ImpotFederalParametres.plafond_cotisation_base_rrq_annuel` et `.taux_abattement_quebec` (nouveaux champs) matérialisent correctement en `Decimal` depuis `parameters/2026/canada.json` mis à jour par la tâche 6
    - Ces tests échouent avec `AttributeError`/`ImportError` tant que la tâche 7.2 n'a pas étendu `parameters_loader.py` — comportement attendu (règle 06)
    - _Requirements: 10.1, 10.2, 10.3, 10.5_
    - _Design: §Data Models « Nouveau sous-modèle partagé Palier », « Extension de ParametresAnnee._propager_contexte »_

  - [x] 7.2 Implémenter `Palier` et étendre `ImpotQCParametres`, `ImpotFederalParametres`, `_propager_contexte`
    - Ajouter la classe `Palier(_ParametresSectionBase)` avec `seuil_bas_annuel_brut`/`taux_brut`/`constante_k_brut` (alias `seuil_bas_annuel`/`taux`/`constante_k`), validateur `_valider_brut` réutilisant `_valider_decimal_ou_to_fill`, et les trois propriétés matérialisées `seuil_bas_annuel`, `taux`, `constante_k` (voir design §Data Models, signature exacte)
    - Étendre `ImpotQCParametres` avec `paliers: tuple[Palier, ...]`, `taux_credits_convertibles` (matérialisé `Decimal`), `deduction_pour_travailleur_annuelle` (déjà présent, matérialisé), `regles_arrondissement: str` — extension strictement additive, `montant_personnel_base` inchangé
    - Étendre `ImpotFederalParametres` avec `paliers: tuple[Palier, ...]`, `taux_credits_convertibles`, `montant_emploi_canadien_annuel` (déjà présent, matérialisé), `plafond_cotisation_base_rrq_annuel` (**nouveau**, matérialisé), `taux_abattement_quebec` (**nouveau**, matérialisé), `regles_arrondissement: str`
    - Étendre `ParametresAnnee._propager_contexte` avec le bloc additif propagant le contexte à chaque `Palier` d'une section portant un attribut `paliers` non vide, en construisant `_contexte_section = f"{nom_section}.paliers[{index}]"` — aucune modification du comportement existant pour les 13 sections déjà en place
    - À ce stade, tous les tests de la tâche 7.1 doivent passer
    - _Requirements: 10.1, 10.2, 10.3, 10.5_
    - _Design: §Data Models (intégral)_

- [x] 8. Checkpoint — tests rouges complets avant implémentation des fonctions d'impôt
  - Vérifier que `pytest tests/payroll_engine/test_impot_qc.py tests/payroll_engine/test_impot_federal.py` échoue avec `ModuleNotFoundError` sur les imports `payroll_engine.impot_qc`/`payroll_engine.impot_federal`
  - Vérifier que `pytest tests/test_golden_outputs.py::test_impots_reproduisent_fixture` échoue également avec `ModuleNotFoundError` pour la même raison
  - Vérifier que les nouvelles classes de garde de la tâche 5 échouent (fichiers `impot_qc.py`/`impot_federal.py` inexistants)
  - Vérifier que `pytest tests/payroll_engine/test_parameters_loader.py` passe entièrement (la tâche 7 doit déjà être verte à ce stade)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implémentation de `payroll_engine/impot_qc.py`
  - [x] 9.1 Créer le module avec `_arrondir`, `_taux_et_constante_pour_palier`, `calcul_impot_qc_formule` et `calcul_impot_qc_retenu`
    - Docstring citant Req 1, 2, 3, règles 01, 02, 05, et pointant vers la spec `impots-retenues-source`
    - Constante privée `_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")`, helper `_arrondir` (patron identique à `rrq.py`)
    - Helper privé `_taux_et_constante_pour_palier(revenu_annuel, paliers)` — recherche du dernier palier dont `seuil_bas_annuel <= revenu_annuel` (voir design §Architecture, signature exacte)
    - `calcul_impot_qc_formule` : séquence exacte du design §Components §2 — déduction pour travailleur proratée par période, annualisation, recherche de palier, impôt annuel de base, crédit personnel (`taux_credits_convertibles × montant_total_TP1015_3_effectif`), impôt annuel net, conversion en montant de période avec plancher à zéro et arrondissement unique ; ne consulte jamais `exoneration_TP1015_3_effectif` ni `retenue_additionnelle_QC_effective` (Req 2.8)
    - Construction de la `CalculationTrace` avec les champs exacts spécifiés par le design §Components §2 (`source`, `annee`, `juridiction=Juridiction.QUEBEC`, `section="4 — Retenue d'impôt du Québec (formule)"`, `parametres_utilises`, `entrees`, `sous_totaux`, `mode_arrondissement`, `precision_arrondissement=2`, `resultat`)
    - `calcul_impot_qc_retenu` : court-circuit véritable — `calcul_impot_qc_formule` n'est invoquée que lorsque `exoneration_TP1015_3_effectif == False` ; retenue effective = montant de base + `retenue_additionnelle_QC_effective` ; trace avec `section="4 — Retenue d'impôt du Québec (retenu)"`, `parametres_utilises={"exoneration_active": ...}`, `entrees={"impot_qc_formule": ...}`, `sous_totaux={"retenue_effective": ...}`
    - À ce stade, tous les tests de la tâche 2 doivent passer, y compris les assertions golden QC001/QC004/QC006 de la tâche 4
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.1, 10.4, 10.5, 11.1, 11.2, 11.5, 11.6, 11.7, 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3_
    - _Design: §Components §1, §2, §3, §6, §7_

- [x] 10. Implémentation de `payroll_engine/impot_federal.py`
  - [x] 10.1 Créer le module avec `_arrondir`, `_taux_et_constante_pour_palier`, `calcul_impot_federal_formule` et `calcul_impot_federal_retenu`
    - Docstring citant Req 4, 5, 6, règles 01, 02, 05, et le mécanisme K1+K2Q+K4+abattement confirmé par le design §Overview
    - `calcul_impot_federal_formule` : séquence exacte du design §Components §4 — Deduction_RRQ_Supplementaire_Federale, annualisation nette, recherche de palier, impôt avant crédits, K1 (crédit personnel TD1), K2Q (cotisations RRQ base/AE/RQAP recalculées **localement** depuis `gains.brut_total` et `parametres_annee.rrq`/`.rqap`/`.assurance_emploi`, **jamais** via `calcul_rrq_employe`/`calcul_rqap_employe`/`calcul_ae_employe`), K4 (montant canadien pour emploi plafonné), impôt annuel de base avec plancher à zéro, abattement du Québec, conversion en montant de période avec arrondissement unique ; ne consulte jamais `exoneration_TD1_effective` ni `retenue_additionnelle_federale_effective` (Req 4.9)
    - Commentaire de code citant explicitement le point de vigilance du design (§Components §4) : `cotisation_rrq_annualisee_base`, `cotisation_ae_annualisee`, `cotisation_rqap_annualisee` sont des variables strictement internes, jamais retournées ni exposées comme `RetenuesEmploye.rrq`/`.rqap`/`.ae` (Req 6.1)
    - Construction de la `CalculationTrace` avec les champs exacts du design §Components §4 (`juridiction=Juridiction.CANADA`, `section="3 — Retenue d'impôt fédéral (formule)"`, `entrees` incluant `deduction_rrq_supp`, `sous_totaux` incluant `k1`, `k2q`, `k4`, `impot_avant_credits`, `impot_annuel_base`, `impot_annuel_net`)
    - `calcul_impot_federal_retenu` : symétrique à `calcul_impot_qc_retenu` (tâche 9.1), substituant `exoneration_TD1_effective`, `retenue_additionnelle_federale_effective`, `calcul_impot_federal_formule`, `section="3 — Retenue d'impôt fédéral (retenu)"`
    - À ce stade, tous les tests de la tâche 3 doivent passer, y compris les assertions golden QC001/QC004/QC006 de la tâche 4
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.2, 10.3, 10.4, 10.5, 11.1, 11.3, 11.4, 11.5, 11.6, 11.7, 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3_
    - _Design: §Components §1, §4, §5, §6, §7_

- [x] 11. Alignement des sous-champs `trace` des fixtures golden (Requirement 11, note de conception design §Components §2)
  - [x] 11.1 Mettre à jour `tests/fixtures/outputs/qc002.json` à `qc006.json`
    - Aligner les sous-champs `trace` de `impot_qc_formule`, `impot_qc_retenu`, `impot_federal_formule`, `impot_federal_retenu` sur la structure uniforme fixée par le design (§Components §2, §3, §4, §5) — `entrees`/`sous_totaux`/`parametres_utilises` avec les clés exactes désormais produites par `impot_qc.py`/`impot_federal.py`
    - **Les montants (`montant`, `resultat`) restent strictement inchangés** — seule la structure interne de `trace` est réalignée, changement non contractuel
    - Revalider chaque fixture modifiée contre `test_impots_reproduisent_fixture` (tâche 4) immédiatement après modification
    - _Requirements: 11.1, 11.2, 11.3, 11.4_
    - _Design: §Components §2 « Note de conception — divergence avec les traces déjà présentes »_

- [x] 12. Checkpoint final — exécution complète, vérification des compteurs et validation manuelle
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (property + golden + garde + exemple) — tous doivent passer
  - Vérifier que `pytest tests/payroll_engine/test_impot_qc.py tests/payroll_engine/test_impot_federal.py -m property` exécute au moins 20 tests distincts couvrant les 13 propriétés du design (avec variantes QC/fédéral)
  - Vérifier que `pytest tests/test_golden_outputs.py::test_impots_reproduisent_fixture` exécute exactement 6 tests (un par scénario QC001–QC006) et tous passent au cent près, y compris `impot_qc_formule == Decimal("104.56")` / `impot_federal_formule == Decimal("86.25")` sur QC001 et `Decimal("0.00")`/`Decimal("0.00")` sur QC004/QC006
    - Vérifier que les dix classes de garde de la tâche 5 passent
  - Vérifier par grep que `payroll_engine/impot_qc.py`, `impot_federal.py` ne contiennent aucun `float`, aucune valeur fiscale codée en dur hors `Decimal("0.00")`/`2`, ni `load_parameters`, `open(`, `datetime.now`, `random.`, `UnsupportedPayrollCase`, ni d'appel à `calcul_rrq_employe`/`calcul_rqap_employe`/`calcul_ae_employe` (`impot_federal.py`)
  - Reproduire manuellement le scénario QC001 dans WebRAS (impôt QC) et PDOC (impôt fédéral), confirmer `104,56 $` et `86,25 $`, archiver la capture dans `tests/fixtures/official/` et consigner la validation (date, résultat, capture) dans `docs/journal-validation.md`
  - Mettre à jour `docs/plan-implementation.md` pour consigner la déviation de noms de module déjà actée dans les requirements (`impot_qc.py`/`impot_federal.py` au lieu de `quebec_tax.py`/`federal_tax.py`)
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, golden tests et tests de garde soient rédigés **avant** l'implémentation et ne peuvent pas être considérés comme facultatifs — discipline TDD stricte alignée avec `moteur-paie-contrats` et `cotisations-sociales-qc`.
- **Ordre spec → tests → implémentation → validation** respecté au niveau du plan : sections 1 à 5 (préparation, property tests QC/fédéral, golden test, tests de garde) précèdent la section 6 (mise à jour bloquante des paramètres officiels), qui précède la section 7 (extension du chargeur, avec ses propres tests écrits avant son implémentation), qui précède le checkpoint explicite de la section 8. Les sections 9 à 10 font basculer l'ensemble au vert module par module ; la section 11 aligne les fixtures ; la section 12 valide manuellement contre WebRAS/PDOC.
- **La section 6 est une tâche bloquante critique** : sans les valeurs officielles TP-1015.F 2026 / T4127 2026 renseignées dans `parameters/2026/quebec.json` et `canada.json`, les golden tests de la section 4 échouent avec `MissingParameterError` (et non un échec de logique) même après implémentation complète des sections 9-10. Cette tâche exige une recherche documentaire active (paliers progressifs, montant canadien pour emploi, plafond de cotisation RRQ de base, abattement du Québec) et la citation de la source officielle exacte (édition, date d'entrée en vigueur, URL) dans chaque fichier JSON, conformément à la règle 05.
- **Découverte de conception à ne pas régresser** : le mécanisme fédéral exige K1 (crédit personnel TD1) **+** K2Q (crédit pour cotisations RRQ base/AE/RQAP) **+** K4 (montant canadien pour emploi), suivi de l'abattement du Québec — un K1 seul ne reproduit pas `86,25 $` sur QC001. Les tâches 3.3 et 10.1 testent et implémentent explicitement ce mécanisme complet, pas une simplification à K1 seul.
- **Chaque property test est annoté** par `# Feature: impots-retenues-source, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/payroll_engine/test_impot_qc.py tests/payroll_engine/test_impot_federal.py` retrouve les 13 propriétés du design (certaines déclinées en variantes QC/fédéral).
- **Séparation stricte exonération / cotisations sociales testée explicitement** : la tâche 5.4 vérifie par garde statique qu'`impot_federal.py` n'appelle jamais les fonctions de `cotisations-sociales-qc`, et la tâche 3.3 teste que le recalcul local K2Q ne dépend jamais de `payroll_input.cumuls_debut` — ces deux mécanismes opposés (recalcul local vs délégation interdite) sont le cœur de la séparation imposée par le Requirement 6.
- **Court-circuit véritable testé par mock, pas par PBT strict** : Property 11 (tâches 2.3, 3.4) utilise `unittest.mock.patch` plutôt qu'une propriété universellement quantifiable — comportement structurel critique (Requirement 3.3, 5.3) qui ne se prête pas naturellement à une formulation « pour tout X » au même titre que les autres propriétés.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2"] },
    { "id": 3, "tasks": ["2.3", "3.3"] },
    { "id": 4, "tasks": ["2.4", "2.5", "3.4", "3.5", "3.6"] },
    { "id": 5, "tasks": ["4.1", "5.1", "5.2", "5.3", "5.4", "5.5"] },
    { "id": 6, "tasks": ["6.1", "6.2"] },
    { "id": 7, "tasks": ["6.3"] },
    { "id": 8, "tasks": ["7.1"] },
    { "id": 9, "tasks": ["7.2"] },
    { "id": 10, "tasks": ["9.1"] },
    { "id": 11, "tasks": ["10.1"] },
    { "id": 12, "tasks": ["11.1"] }
  ]
}
```
