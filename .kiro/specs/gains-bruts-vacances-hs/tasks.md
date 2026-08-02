# Implementation Plan: gains-bruts-vacances-hs

<!-- Plan d'implémentation — spec « gains bruts, vacances et heures supplémentaires »
     du moteur de paie Camp LilySO. Les en-têtes structurels (Overview, Tasks, Notes,
     Task Dependency Graph) sont maintenus en anglais pour conformité au format Kiro.
     Le contenu métier est en français. -->

## Overview

Cette spec livre **l'étape 2 du plan d'implémentation** (`docs/plan-implementation.md`) : la fonction pure `calcul_gains` dans `payroll_engine/gains_bruts.py`, seule fonction publique exposée. Elle assemble le brut d'une paie (salaire régulier, heures supplémentaires, indemnité de vacances, jours fériés manuels) à partir d'un `PayrollInput` figé et des paramètres annuels versionnés, et produit un `GainsDecomposes` + une `CalculationTrace` conforme à la règle 02.

**Aucun contrat** du socle `moteur-paie-contrats` (55/55 tâches livrées, 605 tests) n'est modifié : cette spec **consomme** exclusivement `PayrollInput`, `ParametresAnnee`, `GainsDecomposes`, `CalculationTrace`, `Juridiction`, `ModeArrondissement`, `UnsupportedPayrollCase`.

L'ordre suit strictement la règle 06 : **tests avant code**. Les 19 propriétés de correction du design sont regroupées par lots logiques (signature / linéarité / monotonie / identité comptable / transport / trace / défense en profondeur) pour éviter un émiettement en 19 tâches distinctes, tout en garantissant qu'un `grep` sur `Property N` retrouve la traçabilité intégrale.

**Livrables** :

- Extension de `tests/strategies.py` (6 nouvelles stratégies Hypothesis)
- `tests/payroll_engine/test_gains_bruts.py` (property tests + tests d'exemple, ~500 lignes)
- Extension de `tests/test_golden_outputs.py` (paramétrage `test_calcul_gains_reproduit_fixture` sur QC001–QC006)
- Extension de `tests/test_guards.py` (3 nouvelles classes de garde statique)
- `payroll_engine/gains_bruts.py` (fonction `calcul_gains` + helper `_arrondir` + constante `_PRECISION_MONNAIE`, ~50 lignes de code)

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — `Decimal` de bout en bout, aucun `float` dans le module ni dans son test
- Règle 02 — retour `(GainsDecomposes, CalculationTrace)` avec `source` conforme à la liste blanche de `CalculationTrace` (TP-1015.G)
- Règle 03 — défense en profondeur unique sur `taux_vacances` hors `{0.04, 0.06}` ; tous les autres cas hors matrice sont déjà refusés par `PayrollInput`
- Règle 04 — corpus anonymisé QC001–QC006 déjà en place, aucune donnée personnelle réintroduite
- Règle 05 — `multiplicateur` (1,5) et `seuil_hebdomadaire_heures` (40) lus exclusivement depuis `parameters/2026/quebec.json` via `ParametresAnnee`
- Règle 06 — sections 1 à 4 (tests, garde) rédigées **avant** la section 5 (implémentation) ; les tests sont rouges à l'écriture, verts après implémentation

## Tasks

- [x] 1. Préparer les stratégies Hypothesis et le squelette de test
  - [x] 1.1 Étendre `tests/strategies.py` avec les stratégies dédiées gains bruts
    - Ajouter `st_taux_horaire()` — `st.decimals(min_value=Decimal("10.00"), max_value=Decimal("50.00"), places=2, allow_nan=False, allow_infinity=False)` pour rester dans la plage réaliste Camp LilySO
    - Ajouter `st_heures_par_semaine()` — `st.decimals(min_value=Decimal("0"), max_value=Decimal("60"), places=2, allow_nan=False, allow_infinity=False)` (autorise `0`, fractionnaires, dépassements du seuil de 40 h par semaine)
    - Ajouter `st_taux_vacances()` — `st.sampled_from([Decimal("0.04"), Decimal("0.06")])`
    - Ajouter `st_jours_feries_manuels()` — `st.one_of(st.just(Decimal("0.00")), st.decimals(min_value=Decimal("0.00"), max_value=Decimal("500.00"), places=2, ...))` biaisé vers `Decimal("0.00")` (cas nominal)
    - Ajouter `st_payroll_input()` — compose les stratégies ci-dessus avec les stratégies existantes (`Employee`, `PayPeriod` avec deux `WeekSegment` contigus, `CumulsYTD.zero(...)`) en garantissant l'appariement `cumuls_debut.employe_id == employee.id`, `annee_civile == pay_period.annee_fiscale`, `province_travail == QUEBEC`, `frequence == AUX_DEUX_SEMAINES`, `len(heures_par_semaine) == 2`
    - Ajouter `st_parametres_annee_2026_qc()` — retourne le `ParametresAnnee` réel chargé une seule fois via `load_parameters(2026, Juridiction.QUEBEC)` mémorisé au niveau module (immutable, thread-safe, cohérent avec la note du design §Testing Strategy « stratégies Hypothesis »)
    - Documenter chaque stratégie par un docstring citant le design §Testing Strategy et la règle 01
    - _Requirements: 1.1, 2.1, 3.1, 4.5, 5.4, 6.1, 9.1, 9.2_
    - _Design: §Testing Strategy « Stratégies Hypothesis »_

  - [x] 1.2 Créer le squelette de `tests/payroll_engine/test_gains_bruts.py`
    - Module docstring citant le design §Testing Strategy, la liste des 19 propriétés couvertes, la limitation « totaux de période uniquement » du corpus (héritée de l'Introduction des requirements)
    - Imports : `pytest`, `Decimal`, `ROUND_HALF_UP`, `hypothesis` (`given`, `settings`, `HealthCheck`), les modèles consommés (`PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `Juridiction`, `ModeArrondissement`, `UnsupportedPayrollCase`), les stratégies de `tests/strategies.py`
    - Fixture session-scoped `parametres_2026_qc` qui charge une seule fois `load_parameters(2026, Juridiction.QUEBEC)` et **vérifie la non-régression** de la section `heures_supplementaires` : `assert parametres.heures_supplementaires.multiplicateur == Decimal("1.5")` et `assert parametres.heures_supplementaires.seuil_hebdomadaire_heures == Decimal("40")` (Req 9.6, design §Architecture « Point de vérification »)
    - Configuration Hypothesis partagée : `@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])` réutilisable sur les propriétés à surface d'entrée large
    - _Requirements: 9.6_
    - _Design: §Testing Strategy « Organisation des fichiers de test », §Architecture « Point de vérification `parameters/2026/quebec.json` »_

- [x] 2. Property-based tests de `calcul_gains` (`tests/payroll_engine/test_gains_bruts.py`)
  - [x] 2.1 Tests signature, pureté et déterminisme (classe `TestSignaturePureteDeterminisme`)
    - **Property 9 : Déterminisme (idempotence de l'appel)** — deux appels avec les mêmes arguments produisent deux tuples égaux au sens `==` sur les deux composantes
    - **Property 10 : Absence d'exception sur `PayrollInput` valide** — aucun rejet pour tout `PayrollInput` construit par le constructeur normal (y compris cas extrêmes : heures > 40/semaine, brut faible, taux 6 %, heures fractionnaires)
    - **Property 11 : Forme du tuple retourné** — `isinstance(result, tuple)`, `len(result) == 2`, `isinstance(result[0], GainsDecomposes)`, `isinstance(result[1], CalculationTrace)`
    - Test d'exemple : `from payroll_engine.gains_bruts import calcul_gains` **sans effet de bord** — pas d'ouverture de fichier, pas d'appel réseau (Req 1.6). Vérification par capture `capsys` (silence complet) et par `sys.modules` inspection
    - Annotation obligatoire de chaque test : `# Feature: gains-bruts-vacances-hs, Property N: <titre>`
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 4.3, 10.4, 14.1, 14.2, 14.5_
    - _Design: §Correctness Properties 9, 10, 11 ; §Components §1 « Signature exacte »_

  - [x] 2.2 Test linéarité du salaire régulier (classe `TestLineariteSalaireRegulier`)
    - **Property 1 : Linéarité du salaire régulier** — `gains.salaire_regulier == arrondir(taux_horaire_effectif × Σ heures_normales_semaine)` où `arrondir = quantize(Decimal("0.01"), ROUND_HALF_UP)`
    - Le test recalcule le résultat attendu par une formule alternative (multiplication directe sur le total agrégé) et compare au cent près, exploitant la linéarité de `Decimal` (voir Req 2.1 et note du design §Components §2 étape 1)
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 1: Linéarité du salaire régulier`
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 4.1, 4.2, 4.4, 4.5_
    - _Design: §Correctness Properties 1 ; §Components §2 étape 1_

  - [x] 2.3 Test linéarité du montant des heures supplémentaires (classe `TestLineariteHeuresSupp`)
    - **Property 2 : Linéarité du montant des heures supplémentaires** — `gains.heures_supplementaires_montant == arrondir(taux_horaire_effectif × multiplicateur × Σ heures_supplementaires_semaine)`
    - Le test recalcule par formule alternative sur le total agrégé (linéarité `Decimal`)
    - Vérifie explicitement l'absence de reclassement : si `heures_normales > 40` sur une semaine, le montant HS n'inclut PAS la portion excédentaire (Req 3.5, Req 4.2, Req 4.3)
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 2: Linéarité du montant des heures supplémentaires`
    - _Requirements: 3.1, 3.2, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3_
    - _Design: §Correctness Properties 2 ; §Components §2 étape 2_

  - [x] 2.4 Test monotonie du brut vs heures normales (classe `TestMonotonieHeuresNormales`)
    - **Property 4 : Monotonie du brut vs heures normales** — pour deux `PayrollInput` identiques sauf que `Σ heures_normales(pi_b) > Σ heures_normales(pi_a)`, `calcul_gains(pi_b).gains.brut_total >= calcul_gains(pi_a).gains.brut_total`
    - La stratégie génère un `PayrollInput` de base puis produit `pi_b` par ajout d'un `Decimal` strictement positif sur `heures_par_semaine[0].heures_normales`
    - Vérifie aussi que l'égalité stricte tient lorsque le delta est `Decimal("0")` (conséquence de la linéarité)
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 4: Monotonie du brut vs heures normales`
    - _Requirements: 2.1, 4.1_
    - _Design: §Correctness Properties 4 ; §Components §2 étape 1_

  - [x] 2.5 Test monotonie du brut vs heures supplémentaires (classe `TestMonotonieHeuresSupp`)
    - **Property 5 : Monotonie du brut vs heures supplémentaires** — même invariant que Property 4, sur `heures_supplementaires` cette fois, à multiplicateur constant
    - Vérifie que le brut croît au moins de `delta × taux × multiplicateur × taux_vacances_neutre` (borne inférieure formelle liée à l'indemnité de vacances qui s'ajoute au montant HS via la Base_Vacances)
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 5: Monotonie du brut vs heures supplémentaires`
    - _Requirements: 3.1, 4.1_
    - _Design: §Correctness Properties 5 ; §Components §2 étape 2_

  - [x] 2.6 Test identité comptable du brut total (classe `TestIdentiteComptableBrut`)
    - **Property 3 : Identité comptable du brut total** — `gains.brut_total == gains.salaire_regulier + gains.heures_supplementaires_montant + gains.jours_feries_manuels + gains.vacances`
    - Comparaison stricte `==` sur `Decimal` — tolérance nulle (règle 01)
    - L'identité doit tenir **après** arrondissement à 2 décimales sur chaque composante (Req 6.4 : la somme exacte de quatre `Decimal` à 2 décimales a naturellement au plus 2 décimales)
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 3: Identité comptable du brut total`
    - _Requirements: 6.1, 6.4, 6.5_
    - _Design: §Correctness Properties 3 ; §Components §2 étape 5, §Components §3_

  - [x] 2.7 Test forme monétaire des composantes (classe `TestFormeComposantes`)
    - **Property 6 : Forme des composantes monétaires** — pour chaque composante `v ∈ {salaire_regulier, heures_supplementaires_montant, vacances, jours_feries_manuels, brut_total}` :
      - `isinstance(v, Decimal)` (aucun `float`)
      - `v == v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` (arrondi 2 décimales, bon mode)
      - `v >= Decimal("0")` (non-négativité, contrat `GainsDecomposes`)
      - `v.is_finite()` (ni `NaN` ni infini)
    - Étend aux valeurs de `trace.parametres_utilises`, `trace.entrees`, `trace.sous_totaux` (uniquement contrainte de type `Decimal` et `is_finite()` pour ces dernières — les heures/taux ne sont pas des montants monétaires, cf. design §Correctness Properties 6)
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 6: Forme des composantes monétaires`
    - _Requirements: 2.3, 2.5, 3.7, 3.8, 5.6, 7.1, 7.2, 8.7, 12.5_
    - _Design: §Correctness Properties 6 ; §Components §4_

  - [x] 2.8 Tests de transport strict (classe `TestTransportStrict`)
    - **Property 7 : Transport strict de `jours_feries_manuels`** — `gains.jours_feries_manuels == payroll_input.jours_feries_manuels` (égalité `Decimal.__eq__`, aucun ré-arrondissement, aucune transformation)
    - **Property 8 : Transport strict du multiplicateur et du seuil** — `gains.multiplicateur_heures_supp == parametres_annee.heures_supplementaires.multiplicateur` et `gains.seuil_heures_supp_hebdo == parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures` (égalités strictes, sans ré-arrondissement)
    - Annotations : `# Feature: gains-bruts-vacances-hs, Property 7: Transport strict de jours_feries_manuels` et `# Feature: gains-bruts-vacances-hs, Property 8: Transport strict du multiplicateur et du seuil`
    - _Requirements: 3.3, 3.4, 6.2, 7.4, 7.6, 9.1, 9.2_
    - _Design: §Correctness Properties 7, 8 ; §Components §3, §Components §5.2_

  - [x] 2.9 Tests trace : source et métadonnées d'arrondissement (classe `TestTraceSourceMetadonnees`)
    - **Property 12 : Conformité de `trace.source` à la liste blanche** — `trace.source` matche `^TP-1015\.G \d{4}(, section .+)?$`, l'année encodée `== payroll_input.pay_period.annee_fiscale`, `trace.annee == payroll_input.pay_period.annee_fiscale`, `trace.juridiction == Juridiction.QUEBEC`, `trace.section` non vide
    - **Property 16 : Cohérence des métadonnées d'arrondissement dans la trace** — `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`, `trace.precision_arrondissement == 2`, `trace.resultat == gains.brut_total`
    - Annotations : `# Feature: gains-bruts-vacances-hs, Property 12: Conformité de trace.source à la liste blanche` et `# Feature: gains-bruts-vacances-hs, Property 16: Cohérence des métadonnées d'arrondissement dans la trace`
    - _Requirements: 7.5, 8.1, 8.2, 8.6, 11.8_
    - _Design: §Correctness Properties 12, 16 ; §Components §5.1, §5.5_

  - [x] 2.10 Tests trace : entrées, sous-totaux, paramètres utilisés (classe `TestTraceContenu`)
    - **Property 13 : Contenu de `trace.entrees`** — quatre clés exactes `{heures_normales_totales, heures_supplementaires_totales, taux_horaire_effectif, jours_feries_manuels}` avec valeurs égales aux agrégations correspondantes
    - **Property 14 : Contenu et ordre de `trace.sous_totaux`** — `list(trace.sous_totaux.keys()) == ["salaire_regulier", "heures_supplementaires_montant", "base_vacances", "vacances"]` (ordre exact) ; valeurs cohérentes avec les composantes de `gains` et avec `base_vacances = sr + hs + jours_feries_manuels`
    - **Property 15 : Contenu de `trace.parametres_utilises`** — `set(trace.parametres_utilises.keys()) == {"multiplicateur_heures_supp", "taux_vacances"}` avec valeurs correspondantes ; le `seuil_heures_supp_hebdo` n'y figure PAS (transporté dans `GainsDecomposes` uniquement)
    - Annotations : `# Feature: gains-bruts-vacances-hs, Property 13: Contenu de trace.entrees`, `# Feature: gains-bruts-vacances-hs, Property 14: Contenu et ordre de trace.sous_totaux`, `# Feature: gains-bruts-vacances-hs, Property 15: Contenu de trace.parametres_utilises`
    - _Requirements: 5.1, 5.5, 5.8, 7.3, 8.3, 8.4, 8.5, 13.2_
    - _Design: §Correctness Properties 13, 14, 15 ; §Components §5.2, §5.3, §5.4_

  - [x] 2.11 Test trace : auto-suffisance (classe `TestTraceAutoSuffisante`)
    - **Property 17 : Auto-suffisance de la trace (identité comptable interne)** — un tiers peut recalculer le brut à partir des seuls contenus de la trace :
      - `trace.resultat == trace.sous_totaux["salaire_regulier"] + trace.sous_totaux["heures_supplementaires_montant"] + trace.entrees["jours_feries_manuels"] + trace.sous_totaux["vacances"]`
      - `trace.sous_totaux["vacances"] == arrondir(trace.sous_totaux["base_vacances"] × trace.parametres_utilises["taux_vacances"])`
      - `trace.sous_totaux["base_vacances"] == trace.sous_totaux["salaire_regulier"] + trace.sous_totaux["heures_supplementaires_montant"] + trace.entrees["jours_feries_manuels"]`
    - Annotation : `# Feature: gains-bruts-vacances-hs, Property 17: Auto-suffisance de la trace`
    - _Requirements: 8.8_
    - _Design: §Correctness Properties 17_

  - [x] 2.12 Tests extensibilité 6 % et défense en profondeur (classe `TestExtensibiliteEtDefense`)
    - **Property 18 : Extensibilité au taux 6 %** — pour `pi_04` et `pi_06` identiques sauf sur `taux_vacances`, `calcul_gains(pi_06).gains.vacances == arrondir(calcul_gains(pi_04).gains.base_vacances × Decimal("0.06"))`. La formule est identique pour les deux taux (aucun branchement conditionnel)
    - **Property 19 : Refus d'un `taux_vacances` hors matrice (défense en profondeur)** — pour tout `Decimal taux ∉ {Decimal("0.04"), Decimal("0.06")}` généré par Hypothesis, un `PayrollInput` fabriqué via `PayrollInput.model_construct(taux_vacances=taux, ...)` (contournement de la validation) déclenche `UnsupportedPayrollCase`
    - Test d'exemple pour Property 19 : le message d'exception contient la valeur refusée (`str(taux)`) et mentionne « WebRAS » ou « webras » et « PDOC » ou « pdoc » (cohérent avec la Property 16 de `moteur-paie-contrats`, Req 11.6)
    - Annotations : `# Feature: gains-bruts-vacances-hs, Property 18: Extensibilité au taux 6 %` et `# Feature: gains-bruts-vacances-hs, Property 19: Défense en profondeur taux_vacances`
    - _Requirements: 10.3, 10.5, 13.1, 13.3_
    - _Design: §Correctness Properties 18, 19 ; §Components §2 étape 0 ; §Error Handling « Défense en profondeur taux_vacances »_

- [x] 3. Golden test de reproduction du corpus QC001–QC006
  - [x] 3.1 Étendre `tests/test_golden_outputs.py` avec `test_calcul_gains_reproduit_fixture`
    - Nouveau test paramétré `@pytest.mark.golden @pytest.mark.parametrize("scenario_id", ["QC001", "QC002", "QC003", "QC004", "QC005", "QC006"])`
    - Chargement fixture d'entrée depuis `tests/fixtures/inputs/qc00X.json` → `PayrollInput.model_validate_json(...)`
    - Chargement paramètres `load_parameters(2026, Juridiction.QUEBEC)`
    - Chargement fixture de sortie `tests/fixtures/outputs/qc00X.json` → extraction de la section `gains` → construction d'un `GainsDecomposes(**fixture["gains"])`
    - Appel `gains_effectifs, trace = calcul_gains(payroll_input, parametres)`
    - Assertion 1 : `gains_effectifs == gains_attendus` (égalité stricte `Decimal`, tolérance nulle sur les 7 champs)
    - Assertion 2 : `trace.resultat == gains_attendus.brut_total` (Req 11.8, cohérence trace/gains)
    - Assertion 3 : `trace.source` matche `^TP-1015\.G 2026(, section .+)?$` (Req 11.7)
    - Commentaire dans le test citant explicitement la limitation « totaux de période uniquement, décomposition hebdomadaire 50/50 fabriquée » héritée de l'Introduction des requirements et de `docs/hypotheses-2026.md` §9
    - Le test consomme les fixtures existantes livrées par `moteur-paie-contrats` (tâches 14.1, 14.2) — aucune nouvelle fixture n'est créée
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_
    - _Design: §Testing Strategy « Détail des golden tests », « Limitation du corpus golden »_

- [x] 4. Tests de garde statique de `payroll_engine/gains_bruts.py` (`tests/test_guards.py`)
  - [x] 4.1 Ajouter la classe `TestGainsBrutsNoFloat` — absence de `float` dans le module
    - Parser `payroll_engine/gains_bruts.py` avec `ast.parse` et parcourir l'AST
    - Vérifier l'absence de `ast.Constant(value=float(...))` (littéraux flottants)
    - Vérifier l'absence d'appel `Decimal(<non-str>)` : rejeter tout `ast.Call(func=ast.Name(id="Decimal"), args=[non-Constant-str])` (défend contre `Decimal(1.5)`, `Decimal(x)` où `x` est ambigu)
    - Vérifier l'absence d'appel `round(...)`, `math.floor(...)`, `math.ceil(...)`, `math.trunc(...)` — la seule opération d'arrondissement autorisée est `Decimal.quantize` (Req 12.3)
    - Vérifier que la signature de `calcul_gains` retourne bien `tuple[GainsDecomposes, CalculationTrace]` (annotation) et n'accepte aucun paramètre par défaut (Req 1.4)
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
    - _Design: §Testing Strategy « Détail des tests de garde », §Components §4_

  - [x] 4.2 Ajouter la classe `TestGainsBrutsNoHardcodedFiscalValues` — absence de valeurs fiscales en dur
    - Lecture ligne par ligne de `payroll_engine/gains_bruts.py`
    - Vérifier l'absence stricte des motifs `Decimal("1.5")`, `Decimal("1.50")`, `Decimal("40")`, `Decimal("40.00")`, `Decimal("40.0")` — ces valeurs viennent exclusivement de `parametres_annee.heures_supplementaires` (Req 9.4)
    - Autoriser les littéraux `Decimal("0")`, `Decimal("0.00")` (neutre additif, Req 9.4), `Decimal("0.01")` (précision d'arrondissement `_PRECISION_MONNAIE`, imposée par TP-1015.G — pas un paramètre fiscal), et `Decimal("0.04")` + `Decimal("0.06")` **uniquement dans le contexte de la défense en profondeur** (whitelist par ligne : deux occurrences maximum, sur la ligne qui construit l'ensemble `{Decimal("0.04"), Decimal("0.06")}`, Req 10.3, cohérent avec l'exception `Employee` documentée dans `TestNoHardcodedFiscalValues` de `moteur-paie-contrats`)
    - Vérifier l'absence de constantes numériques déguisées : pas de `1.5`, `40`, `0.04`, `0.06` en float ou entier hors des contextes autorisés
    - _Requirements: 5.7, 9.4_
    - _Design: §Testing Strategy « Détail des tests de garde », §Architecture « Absence de nouvelle dépendance »_

  - [x] 4.3 Ajouter la classe `TestGainsBrutsNoLoadParametersCall` — non-appel de `load_parameters`
    - Grep du fichier source `payroll_engine/gains_bruts.py` pour vérifier qu'il ne contient pas le token `load_parameters` (ni en import, ni en appel)
    - Vérifier l'absence de `from payroll_engine.parameters_loader import load_parameters` — seul l'import du **type** `ParametresAnnee` est autorisé
    - Vérifier l'absence d'ouverture de fichier : pas d'appel `open(...)`, `Path(...).read_text()`, `json.load(...)`, `json.loads(...)` — la fonction reçoit `parametres_annee` déjà matérialisé (Req 1.3, 1.6)
    - Vérifier l'absence d'appel à `datetime.now()`, `datetime.today()`, `random.*`, `os.environ` — sources de non-déterminisme proscrites (Req 14.1, 14.2)
    - Vérifier l'absence de variable de module mutable (pas de `_cache = {}`, pas de `logging.getLogger(...)` au niveau module)
    - _Requirements: 1.3, 1.6, 14.1, 14.2, 14.3_
    - _Design: §Testing Strategy « Détail des tests de garde », §Architecture « Contrainte de pureté »_

- [x] 5. Implémentation de `payroll_engine/gains_bruts.py`
  - [x] 5.1 Créer le squelette du module + helper d'arrondissement + défense en profondeur
    - Créer `payroll_engine/gains_bruts.py` avec docstring citant Req 1, règles 01, 02, 05, et pointant vers la spec `gains-bruts-vacances-hs`
    - Imports : `from decimal import Decimal, ROUND_HALF_UP`, `from typing import Final`, les modèles consommés (`Juridiction`, `ModeArrondissement`, `UnsupportedPayrollCase`, `PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `ParametresAnnee`)
    - Définir la constante privée `_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")` (2 décimales, imposé par TP-1015.G, cf. design §Components §4)
    - Implémenter `_arrondir(montant: Decimal) -> Decimal` qui retourne `montant.quantize(_PRECISION_MONNAIE, rounding=ROUND_HALF_UP)` — seul mécanisme d'arrondissement autorisé (Req 12.3)
    - Ébaucher la signature publique `def calcul_gains(payroll_input: PayrollInput, parametres_annee: ParametresAnnee) -> tuple[GainsDecomposes, CalculationTrace]:` avec docstring référençant Req 1, règles 01, 02, 05
    - Implémenter l'**étape 0** (défense en profondeur `taux_vacances`) : `if payroll_input.taux_vacances not in {Decimal("0.04"), Decimal("0.06")}: raise UnsupportedPayrollCase(...)` avec message citant la valeur refusée et renvoyant à WebRAS + PDOC (cohérent avec Property 16 de `moteur-paie-contrats`, Req 11.6)
    - À ce stade, `calcul_gains` peut lever la défense en profondeur mais retourne encore `NotImplemented` ou `raise NotImplementedError` sur le chemin nominal — les tests de linéarité restent rouges, les tests de défense en profondeur passent
    - _Requirements: 1.1, 1.4, 1.6, 10.3, 10.5, 12.3, 13.3_
    - _Design: §Components §1, §Components §2 étape 0, §Components §4, §Error Handling_

  - [x] 5.2 Implémenter l'algorithme complet, la trace et la construction du résultat
    - **Étape 1 (Salaire régulier, Req 2)** : `sr = _arrondir(sum((s.heures_normales * payroll_input.taux_horaire_effectif for s in payroll_input.heures_par_semaine), start=Decimal("0")))`
    - **Étape 2 (Heures supp, Req 3)** : lecture `mult = parametres_annee.heures_supplementaires.multiplicateur` puis `hs = _arrondir(sum((s.heures_supplementaires * payroll_input.taux_horaire_effectif * mult for s in payroll_input.heures_par_semaine), start=Decimal("0")))`
    - **Étape 3 (Base vacances, Req 5.1, 7.3)** : `base_vac = sr + hs + payroll_input.jours_feries_manuels` (pas d'arrondissement — somme exacte de trois `Decimal` à 2 décimales)
    - **Étape 4 (Indemnité vacances, Req 5.2, 5.6)** : `iv = _arrondir(base_vac * payroll_input.taux_vacances)`
    - **Étape 5 (Brut total, Req 6.1, 6.4)** : `brut = sr + hs + payroll_input.jours_feries_manuels + iv` (pas d'arrondissement — somme exacte à 2 décimales)
    - **Vérification interne d'identité comptable (Req 6.4)** : `assert brut == sr + hs + payroll_input.jours_feries_manuels + iv` (bug de refactoring, jamais un cas métier)
    - **Construction de la `CalculationTrace`** avec les 9 champs conformément à design §Components §5 :
      - `source = f"TP-1015.G {payroll_input.pay_period.annee_fiscale}, section salaire brut, heures supplémentaires et indemnité de vacances"` (Req 8.1)
      - `annee = payroll_input.pay_period.annee_fiscale` (Req 8.2)
      - `juridiction = Juridiction.QUEBEC` (Req 8.2)
      - `section = "salaire brut, heures supplémentaires et indemnité de vacances"` (Req 8.2)
      - `parametres_utilises = {"multiplicateur_heures_supp": mult, "taux_vacances": payroll_input.taux_vacances}` (Req 8.3)
      - `entrees` avec les 4 clés `heures_normales_totales`, `heures_supplementaires_totales`, `taux_horaire_effectif`, `jours_feries_manuels` (Req 8.4) — sommes explicites via `sum(..., start=Decimal("0"))`
      - `sous_totaux` avec les 4 clés dans l'ordre `salaire_regulier`, `heures_supplementaires_montant`, `base_vacances`, `vacances` (Req 8.5)
      - `mode_arrondissement = ModeArrondissement.ROUND_HALF_UP` (Req 8.6)
      - `precision_arrondissement = 2` (Req 8.6)
      - `resultat = brut` (Req 8.6)
    - **Construction du `GainsDecomposes`** (Req 6.3, 6.5) avec les 7 champs peuplés dans l'ordre : `salaire_regulier=sr`, `heures_supplementaires_montant=hs`, `vacances=iv`, `jours_feries_manuels=payroll_input.jours_feries_manuels` (recopie, Req 6.2), `brut_total=brut`, `multiplicateur_heures_supp=mult` (transport, Req 3.3, 7.6), `seuil_heures_supp_hebdo=parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures` (transport, Req 3.4, 7.6)
    - **Retour** `return (gains, trace)` — tuple à exactement deux éléments (Req 1.4)
    - À ce stade, **tous** les property tests, tests d'exemple, golden tests et tests de garde doivent passer
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.5, 5.6, 5.8, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 9.1, 9.2, 13.1, 14.1, 14.2_
    - _Design: §Components §2 étapes 1–5, §Components §3, §Components §5, §Components §6_

- [x] 6. Checkpoint final — exécution complète et vérification des compteurs
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (property + golden + garde + unit) — tous doivent passer
  - Vérifier que `pytest tests/payroll_engine/test_gains_bruts.py -m property` exécute au moins 12 tests distincts (un par sous-tâche 2.1 à 2.12, couvrant les 19 propriétés du design)
  - Vérifier que `pytest tests/test_golden_outputs.py::test_calcul_gains_reproduit_fixture` exécute exactement 6 tests (un par scénario QC001–QC006) et tous passent au cent près
  - Vérifier que les trois classes de garde `TestGainsBrutsNoFloat`, `TestGainsBrutsNoHardcodedFiscalValues`, `TestGainsBrutsNoLoadParametersCall` passent
  - Vérifier par grep que `payroll_engine/gains_bruts.py` ne contient aucun `float`, ni `1.5`, `40`, `0.04`, `0.06` hors défense en profondeur, ni `load_parameters`, `open(`, `datetime.now`, `random.` (cohérence avec les gardes 4.1 à 4.3)
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, golden tests et tests de garde soient rédigés **avant** l'implémentation et ne peuvent pas être considérés comme facultatifs. La discipline TDD stricte est un livrable de la spec, pas une option (convention alignée avec `moteur-paie-contrats`).
- **Ordre spec → tests → implémentation → validation** respecté au niveau du plan : sections 1 à 4 (préparation, property tests, golden test, tests de garde) précèdent la section 5 (implémentation). À l'issue de la section 4, **tous** les tests sont écrits et rouges (à l'exception de la défense en profondeur qui devient verte après 5.1). L'implémentation en 5.2 fait basculer l'ensemble au vert.
- **Chaque property test est annoté** par `# Feature: gains-bruts-vacances-hs, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/payroll_engine/test_gains_bruts.py` retrouve les 19 propriétés du design.
- **Groupement des 19 propriétés en 12 sous-tâches** : signature/pureté/déterminisme (P9+P10+P11), linéarité SR (P1), linéarité HS (P2), monotonie HN (P4), monotonie HS (P5), identité comptable (P3), forme composantes (P6), transport (P7+P8), trace source/métadonnées (P12+P16), trace contenu (P13+P14+P15), trace auto-suffisance (P17), extensibilité + défense (P18+P19). Ce regroupement suit la table du design §Testing Strategy.
- **Aucune formule fiscale nouvelle** : cette spec assemble le brut à partir de règles déjà publiées (TP-1015.G, Loi sur les normes du travail du Québec). Les retenues (RRQ, RQAP, AE, impôt QC, impôt fédéral) et les charges patronales (FSS, CNESST, CNT) relèvent des specs 3 à 8 du plan d'implémentation.
- **Aucun paramètre fiscal en dur** dans `payroll_engine/gains_bruts.py` : le `multiplicateur` (1,5) et le `seuil_hebdomadaire_heures` (40) viennent exclusivement de `parametres_annee.heures_supplementaires`, chargé par `load_parameters` **avant** l'appel à `calcul_gains`. Les seules constantes littérales autorisées dans le module sont `Decimal("0")` (neutre additif), `Decimal("0.01")` (précision d'arrondissement `_PRECISION_MONNAIE`), et l'ensemble `{Decimal("0.04"), Decimal("0.06")}` uniquement dans la défense en profondeur (matrice de refus métier, pas paramètre fiscal, cohérent avec l'exception `Employee` documentée dans `moteur-paie-contrats`).
- **Fixtures anonymisées** : cette spec **ne crée aucune fixture** — elle consomme les fixtures QC001–QC006 déjà livrées par `moteur-paie-contrats` (tâches 14.1, 14.2). La règle 04 est déjà respectée par ces fixtures existantes.
- **Limitation golden documentée** : les fixtures portent une décomposition hebdomadaire 50/50 fabriquée ; la reproduction au cent près est valide sur les **totaux de période** grâce à la linéarité de la formule (voir Introduction des requirements et `docs/hypotheses-2026.md` §9). Une révision future du corpus (captures WebRAS/PDOC calibrées semaine par semaine) permettra d'étendre la garantie à la granularité semaine — hors périmètre de cette spec.
- **Validation croisée avec les outils officiels** (WebRAS, PDOC) est menée à part par l'opérateur du camp et consignée dans `docs/journal-validation.md` : cette étape n'est pas une tâche de code et n'apparaît donc pas dans ce plan.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "4.1", "4.2", "4.3"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "2.9", "2.10", "2.11", "2.12", "3.1"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] }
  ]
}
```
