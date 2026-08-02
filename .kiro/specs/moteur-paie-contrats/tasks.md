# Implementation Plan: moteur-paie-contrats

<!-- Plan d'implémentation — spec fondation du moteur de paie Camp LilySO.
     Les en-têtes structurels (Overview, Tasks, Notes, Task Dependency Graph) sont maintenus en anglais
     pour conformité au format Kiro. Le contenu métier est en français. -->

## Overview

Cette spec établit le **socle contractuel** du moteur de paie Camp LilySO : modèles Pydantic v2, hiérarchie d'exceptions, format de trace, chargeur de paramètres versionnés. Elle n'implémente **aucune formule fiscale** — celles-ci relèvent des specs 2 à 8 du plan (`docs/plan-implementation.md`).

L'ordre des tâches suit strictement la règle 06 : **tests avant code**. Pour chaque composant, les tests (property-based avec Hypothesis + tests d'exemple + golden tests pour le corpus QC001–QC006) sont rédigés avant l'implémentation. Les 16 propriétés de correction du design deviennent chacune un test Hypothesis unique tagué `# Feature: moteur-paie-contrats, Property N: ...`.

**Livrables** :

- `models/enums.py`, `models/exceptions.py`, `models/_validators.py`
- `models/trace.py`, `models/employee.py`, `models/pay_period.py`, `models/cumuls.py`
- `models/payroll_input.py`, `models/payroll_result.py`
- `payroll_engine/parameters_loader.py`
- Tests sous `tests/` : property tests, tests d'exemple, golden tests, tests de garde
- Fixtures anonymisées sous `tests/fixtures/inputs/` et `tests/fixtures/outputs/`

**Cadre de discipline** :

- Règle 01 — `Decimal` obligatoire, aucun `float` dans le domaine
- Règle 02 — chaque calcul fiscal futur devra retourner `(Decimal, CalculationTrace)` : la trace est conçue ici
- Règle 03 — refus fail-fast à la frontière des cas hors matrice
- Règle 04 — aucune donnée personnelle réelle dans les fixtures ni dans le code
- Règle 05 — aucun taux/plafond/seuil en dur dans le Python, tout dans `parameters/<AAAA>/*.json`

## Tasks

- [x] 1. Préparer l'environnement de test et les dépendances de développement
  - Ajouter `hypothesis>=6.100` et `pytest-cov>=5.0` aux dépendances dev de `pyproject.toml` (déjà présent, vérifier)
  - Créer `tests/conftest.py` avec les marqueurs pytest (`golden`, `property`, `unsupported`) et un `pytest.ini_options` de couverture minimale
  - Créer `tests/strategies.py` (vide pour l'instant, sera enrichi progressivement) qui hébergera les stratégies Hypothesis réutilisables
  - Créer les sous-dossiers `tests/models/`, `tests/payroll_engine/`, `tests/fixtures/inputs/`, `tests/fixtures/outputs/` avec chacun un `__init__.py` ou `.gitkeep`
  - _Requirements: 12.1–12.9 (préparer l'accueil des scénarios QC001–QC006)_

- [x] 2. Énumérations fermées du domaine (`models/enums.py`)
  - [x] 2.1 Écrire les tests d'exemple pour les énumérations
    - Vérifier `Juridiction.QUEBEC == "quebec"`, `Juridiction.CANADA == "canada"`, pas d'autre valeur
    - Vérifier `FrequencePaie.AUX_DEUX_SEMAINES == "aux_deux_semaines"` et que `FrequencePaie("hebdomadaire")` lève `ValueError`
    - Vérifier `StatutDePaie` expose exactement `{brouillon, emise, annulee, remplace_par}`
    - Vérifier `ModeArrondissement` expose exactement `{ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN, ROUND_UP}`
    - _Requirements: 5.1, 6.1, 9.1_

  - [x] 2.2 Implémenter les énumérations en `enum.StrEnum` (Python 3.11+)
    - `Juridiction`, `FrequencePaie`, `StatutDePaie`, `ModeArrondissement`
    - Aucune autre valeur exposée dans le périmètre courant
    - _Requirements: 5.1, 6.1, 9.1, 11.1, 11.2_

- [x] 3. Hiérarchie d'exceptions du domaine (`models/exceptions.py`)
  - [x] 3.1 Écrire les tests d'exemple des exceptions
    - Vérifier que `PayrollDomainError`, `UnsupportedPayrollCase`, `MissingParameterError` existent
    - Vérifier la hiérarchie : `UnsupportedPayrollCase` et `MissingParameterError` héritent de `PayrollDomainError`
    - Vérifier `assert not issubclass(UnsupportedPayrollCase, pydantic.ValidationError)` et idem pour `MissingParameterError`
    - Vérifier qu'un message vide n'est pas admis (contrainte de non-vacuité vérifiée à la construction)
    - _Requirements: 8.1, 8.4, 8.7_

  - [x] 3.2 Implémenter la hiérarchie `PayrollDomainError` → `UnsupportedPayrollCase`, `MissingParameterError`
    - Aucune classe ne dérive de `pydantic.ValidationError`
    - Constructeur avec message non vide obligatoire
    - _Requirements: 8.1, 8.4, 8.7_

- [x] 4. Validateurs Pydantic transverses (`models/_validators.py`)
  - [x] 4.1 Écrire les property tests des validateurs
    - **Property 2 : Rejet universel de `float` dans tout champ `Decimal`** — Hypothesis génère des `float` (positifs, négatifs, NaN, `4.0`, `0.0`, `Decimal(float_val)` avec précision aberrante) et vérifie que `reject_float` lève une erreur ; les entiers Python et les chaînes convertibles restent acceptés. **Validates: Requirements 10.1, 10.2, 10.4**
    - **Property 4 : Rejet des motifs sensibles** — Hypothesis génère des variantes de casse/accents/séparateurs de chaque motif blacklisté et vérifie que `reject_sensitive_fields` refuse la clé avec un message renvoyant à la règle 04. **Validates: Requirements 1.3**
    - Property de rejet JSON non guillemé — `_parse_json_reject_floats("1.0")` et `_parse_json_reject_floats("0.0")` lèvent, `_parse_json_reject_floats("1")` et `"40"` passent. **Validates: Requirements 10.1, 13.5**
    - _Requirements: 1.3, 1.4, 3.2, 4.8, 5.3, 10.1, 10.2, 10.4, 13.5_

  - [x] 4.2 Implémenter `reject_float`, `reject_sensitive_fields`, `_parse_json_reject_floats`
    - `reject_float` en `mode="before"` : refuse `float`, refuse `Decimal` construit depuis `float` (précision aberrante), refuse notation scientifique et caractères hors `[0-9.\-+]`
    - `reject_sensitive_fields` en `model_validator(mode="before")` : liste noire de motifs (normalisée case + accents + `_/-/ `), recherche substring, message renvoyant à la règle 04
    - `_parse_json_reject_floats` : wrapper `json.loads(..., parse_float=_reject_json_float)` qui refuse tout littéral numérique non guillemé avec point décimal
    - _Requirements: 1.3, 1.4, 3.2, 9.4, 10.1, 10.2, 10.4, 13.5_

- [x] 5. Modèle `CalculationTrace` (`models/trace.py`)
  - [x] 5.1 Écrire les property tests et tests d'exemple de `CalculationTrace`
    - **Property 12 : Liste blanche des sources officielles** — Hypothesis génère des chaînes conformes aux regex autorisées (TP-1015.F/G/3, T4127, TD1, guide ARC, `.gouv.qc.ca`, `.canada.ca`) et vérifie que la construction réussit ; génère des chaînes non conformes et vérifie que la construction échoue avec un message renvoyant à la règle 02. **Validates: Requirements 5.2, 12.9**
    - Test d'exemple : construction sans `source`, `annee`, `mode_arrondissement` ou `resultat` lève `ValidationError` (Req 5.7)
    - Test d'exemple : `__str__` liste, dans l'ordre, source, année, section, paramètres, entrées, sous-totaux, arrondissement, résultat (Req 5.6)
    - Test d'exemple : l'ordre d'insertion des `sous_totaux` est préservé après round-trip
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 5.8, 12.9_

  - [x] 5.2 Implémenter `CalculationTrace`
    - Modèle Pydantic v2, `frozen=True`, `extra="forbid"`
    - Validateur de source avec liste blanche regex (TP-1015.F/G/3, T4127, TD1, guide ARC, URLs officielles)
    - `field_validator` en `mode="before"` sur tous les champs `Decimal` (délégué à `reject_float`)
    - Méthode `__str__` produisant une représentation textuelle ordonnée
    - Sérialiseur `Decimal → str` via `field_serializer` (pour préparer Property 6)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 5.8_

- [x] 6. Modèle `Employee` (`models/employee.py`)
  - [x] 6.1 Écrire les property tests et tests d'exemple de `Employee`
    - **Property 1 (partiel Employee) : Immuabilité** — Hypothesis génère des `Employee` valides et vérifie que toute mutation d'un champ lève `ValidationError`. **Validates: Requirements 1.6**
    - **Property 3 : Rejet des champs inconnus** — Hypothesis génère des noms de champ hors contrat et vérifie que la construction échoue. **Validates: Requirements 1.2**
    - **Property 4 (déclenchement sur Employee)** — reuse de la stratégie de motifs sensibles ; construction d'un `Employee` avec la clé injectée lève `ValidationError` avec référence à la règle 04. **Validates: Requirements 1.3**
    - **Property 9 (partiel Employee) : Non-négativité** — montants `>= 0` sur `taux_horaire_base > 0`, `montant_total_TP1015_3 >= 0`, etc. **Validates: Requirements 4.11 (par extension), 3.6**
    - Tests d'exemple : `province_travail != QUEBEC` lève `UnsupportedPayrollCase` avec message mentionnant WebRAS et PDOC (Req 1.5, 11.1, 11.6, 16 messages)
    - Test d'exemple : `taux_indemnite_vacances` hors `{0.04, 0.06}` lève `UnsupportedPayrollCase` (Req 11.3)
    - Test d'exemple : les 14 champs déclarés existent et sont typés `Decimal` (pas de `float`) pour les montants
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 10.1, 11.1, 11.3, 11.6_

  - [x] 6.2 Implémenter `Employee` (constructeur principal, sans la fabrique)
    - Pydantic v2, `frozen=True`, `extra="forbid"`, `str_strip_whitespace=True`
    - Les 14 champs exigés par Req 1.1 (id, nom_affichage, date_naissance, province_travail, titre_emploi, taux_horaire_base, date_embauche, date_fin_emploi optionnelle, taux_indemnite_vacances, exoneration_TP1015_3, exoneration_TD1, montant_total_TP1015_3, montant_total_TD1, retenue_additionnelle_QC, retenue_additionnelle_federale)
    - `model_validator(mode="before")` déléguant à `reject_sensitive_fields`
    - `model_validator(mode="after")` refusant province ≠ QC et taux vacances ∉ {0.04, 0.06} en levant `UnsupportedPayrollCase`
    - Rejet transverse `float` via `reject_float` en `mode="before"` sur les champs `Decimal`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 10.1, 11.1, 11.3, 11.6_

  - [x] 6.3 Implémenter la fabrique `Employee.avec_defauts_par_annee(annee_reference, **champs)`
    - Aucune valeur en dur (18 952, 16 452, 0) dans le corps
    - Lit les valeurs par défaut via `load_parameters` (dépendance à la tâche 12) — utiliser un import différé ou une injection paramétrique du chemin
    - `retenue_additionnelle_QC` et `retenue_additionnelle_federale` par défaut à `Decimal("0.00")` **également lus via `load_parameters`**, jamais codés
    - _Requirements: 1.7_

  - [x] 6.4 Écrire les tests d'exemple pour la fabrique `avec_defauts_par_annee`
    - Chargement des défauts 2026 réussit et retourne un `Employee` avec les montants attendus (comparaison contre le JSON, pas contre des valeurs en dur dans le test)
    - Une valeur `"TO_FILL"` sur un défaut consommé lève `MissingParameterError`
    - Le paramètre optionnel `chemin_parametres` permet d'injecter un dossier de test
    - _Requirements: 1.7_

- [x] 7. Modèles `WeekSegment` et `PayPeriod` (`models/pay_period.py`)
  - [x] 7.1 Écrire les property tests et tests d'exemple de `WeekSegment` et `PayPeriod`
    - **Property 1 (partiel PayPeriod) : Immuabilité**. **Validates: Requirements 2.8**
    - **Property 13 : Contiguïté et couverture des semaines constituantes** — Hypothesis génère des `PayPeriod` avec 2 `WeekSegment` bien alignés (acceptés) et mal alignés (refusés). **Validates: Requirements 2.4, 2.5**
    - **Property 14 : Nombre correct de semaines** — Hypothesis génère des listes de longueur `n ≠ 2` et vérifie que l'erreur de nombre prévaut sur les vérifications de contiguïté/couverture. **Validates: Requirements 2.2**
    - **Property 9 (partiel) : Non-négativité des heures** — `heures_normales`, `heures_supplementaires` ∈ [0, 168]
    - Test d'exemple : `frequence != AUX_DEUX_SEMAINES` lève `UnsupportedPayrollCase` mentionnant règle 03 et outils officiels (Req 2.6, 11.2, 11.6)
    - Test d'exemple : `date_fin < date_debut` sur `WeekSegment` lève `ValidationError`
    - Test d'exemple : `nb_periodes_annuelles` accepté à 26 et à 27, refusé à 0 ou négatif
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 10.1, 11.2, 11.6_

  - [x] 7.2 Implémenter `WeekSegment`
    - Pydantic v2, `frozen=True`, `extra="forbid"`
    - Champs : `date_debut`, `date_fin`, `heures_normales`, `heures_supplementaires` (bornés à `[0, 168]`)
    - `model_validator(mode="after")` : `date_fin >= date_debut`
    - _Requirements: 2.3, 2.8, 10.1_

  - [x] 7.3 Implémenter `PayPeriod`
    - Pydantic v2, `frozen=True`, `extra="forbid"`
    - Champs : `numero_periode`, `date_debut`, `date_fin`, `date_paiement`, `frequence`, `nb_periodes_annuelles`, `annee_fiscale`, `semaines: tuple[WeekSegment, ...]`
    - Ordre strict des validateurs `model_validator(mode="after")` :
      1. `_refuser_frequence_hors_matrice` → `UnsupportedPayrollCase` si ≠ `AUX_DEUX_SEMAINES`
      2. `_nombre_semaines_correspond_a_frequence` → `ValidationError` si `len(semaines) != 2` pour `AUX_DEUX_SEMAINES`
      3. `_semaines_contigues_et_couvrantes` → court-circuité si le nombre n'est pas 2 (respecte AC4/AC5 du Req 2)
    - Ne dépend PAS de `load_parameters` : `nb_periodes_annuelles` est fourni par l'appelant (Req 2.7 côté modèle ; le repli est côté loader)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 11.2, 11.6_

- [x] 8. Modèle `CumulsYTD` (`models/cumuls.py`)
  - [x] 8.1 Écrire les property tests et tests d'exemple de `CumulsYTD`
    - **Property 1 (partiel CumulsYTD) : Immuabilité** — mutation directe lève, et `avec_paie` ne modifie pas l'instance source. **Validates: Requirements 7.3**
    - **Property 9 (partiel CumulsYTD) : Non-négativité** — Hypothesis génère des valeurs négatives et vérifie le rejet. **Validates: Requirements 7.1**
    - **Property 10 : Monotonie croissante via `avec_paie`** — Hypothesis génère un `CumulsYTD c` et un `PayrollResult p` avec `employe_id` et `annee_fiscale` cohérents, vérifie que chaque catégorie du résultat est `>=` celle de `c`, et que `c` reste inchangée. **Validates: Requirements 7.4, 7.5** *(cette property dépend de PayrollResult — la stratégie sera enrichie dans la tâche 10)*
    - Tests d'exemple : `avec_paie` lève `PayrollDomainError` si `employe_id` différent (Req 7.7) ou `annee_fiscale` différente (Req 7.6)
    - Test d'exemple : `CumulsYTD.zero("EMP001", 2026)` produit une instance avec toutes les catégories à `Decimal("0.00")`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 8.2 Implémenter `CumulsYTD`
    - Pydantic v2, `frozen=True`, `extra="forbid"`
    - Champs : `employe_id`, `annee_civile`, plus 11 catégories `Decimal >= 0` (brut, vacances, RRQ_e, RRQ_er, RQAP_e, RQAP_er, AE_e, AE_er, impôt_qc, impôt_fed, net)
    - Fabrique de classe `zero(employe_id, annee_civile)`
    - Méthode `avec_paie(resultat: PayrollResult) -> CumulsYTD` retournant une nouvelle instance via `model_copy(update=...)`, refusant les incohérences avec `PayrollDomainError`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

- [x] 9. Modèle `PayrollInput` (`models/payroll_input.py`)
  - [x] 9.1 Écrire les property tests et tests d'exemple de `PayrollInput`
    - **Property 1 (partiel PayrollInput) : Immuabilité**. **Validates: Requirements 3.11**
    - **Property 3 : Rejet des champs inconnus** — sur `PayrollInput` en plus d'`Employee`. **Validates: Requirements 3.8**
    - **Property 5 : Rejet des champs hors matrice** — Hypothesis génère des variantes des motifs blacklistés (commission, bonus, allocation_automobile, cotisation_syndicale, …) et vérifie que la construction lève `UnsupportedPayrollCase` avec référence WebRAS/PDOC. **Validates: Requirements 11.4, 11.5**
    - **Property 9 (partiel PayrollInput)** : `jours_feries_manuels` négatif → `ValidationError` sans clampage (Req 3.6). **Validates: Requirements 3.3, 3.6**
    - Test d'exemple : `taux_vacances = 0.05` lève `UnsupportedPayrollCase` (Req 3.5, 11.3)
    - Test d'exemple : `pay_period.frequence != AUX_DEUX_SEMAINES` reçu en cohérence croisée lève `UnsupportedPayrollCase` (Req 3.9)
    - Test d'exemple : `employee.province_travail != QUEBEC` reçu en cohérence croisée lève `UnsupportedPayrollCase` (Req 3.10)
    - Test d'exemple : `len(heures_par_semaine) != len(pay_period.semaines)` lève `ValidationError`
    - Test d'exemple : `cumuls_debut.employe_id != employee.id` lève `ValidationError`
    - Test d'exemple : `jours_feries_manuels` absent est traité comme `Decimal("0.00")` (Req 3.6)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x] 9.2 Implémenter `HeuresParSemaine` et `PayrollInput`
    - `HeuresParSemaine` : `frozen`, `extra="forbid"`, heures ∈ [0, 168]
    - `PayrollInput` : `frozen`, `extra="forbid"`
    - Blacklists explicites `_CHAMPS_REMUNERATION_HORS_MATRICE` et `_CHAMPS_RETENUE_HORS_MATRICE` en constantes de module
    - `model_validator(mode="before")` : rejette les clés hors matrice avec `UnsupportedPayrollCase`
    - `model_validator(mode="after")` : cohérence croisée (province, fréquence, taux vacances, longueur `heures_par_semaine`, appariement `cumuls_debut`)
    - Rejet transverse `float` via `reject_float`
    - _Requirements: 3.1–3.12, 11.3, 11.4, 11.5, 11.6, 11.7_

- [x] 10. Modèles de sortie `GainsDecomposes`, `MontantAvecTrace`, `RetenuesEmploye`, `CotisationsEmployeur`, `PayrollResult` (`models/payroll_result.py`)
  - [x] 10.1 Écrire les property tests et tests d'exemple de `PayrollResult` et sous-modèles
    - **Property 1 (partiel PayrollResult, GainsDecomposes, MontantAvecTrace, RetenuesEmploye, CotisationsEmployeur) : Immuabilité**. **Validates: Requirements 4.12, 6.2**
    - **Property 7 : Identité brute** — Hypothesis construit des `(brut, retenues, net)` cohérents et incohérents ; les cohérents passent, les incohérents lèvent `ValidationError`. **Validates: Requirements 4.4, 4.9**
    - **Property 8 : Identité coût employeur** — Hypothesis idem sur `cout_employeur == brut + total_cotisations`. **Validates: Requirements 4.5, 4.10**
    - **Property 9 (partiel PayrollResult) : Non-négativité** des retenues et cotisations. **Validates: Requirements 4.11**
    - **Property 11 : Biconditionnelle `statut ⟺ remplace_par_id ⟺ date_emission`** — Hypothesis génère les 4×2×2 combinaisons et vérifie qu'exactement les combinaisons valides passent. **Validates: Requirements 6.3, 6.4, 6.5, 6.7**
    - Tests d'exemple : `total_retenues_employe` incohérent avec la somme des retenues effectivement retenues lève `ValidationError`
    - Tests d'exemple : `total_cotisations_employeur` incohérent avec la somme des cotisations lève `ValidationError`
    - Tests d'exemple : `multiplicateur_heures_supp` et `seuil_heures_supp_hebdo` reçus depuis le module de calcul, jamais recalculés (Req 4.14)
    - Test d'exemple : `cumuls_fin.employe_id != employe_id` ou `cumuls_fin.annee_civile != annee_fiscale` lève `ValidationError`
    - Test d'exemple : `version >= 1`, `id_paie` non vide
    - _Requirements: 4.1–4.14, 6.1–6.7, 10.1_

  - [x] 10.2 Implémenter `GainsDecomposes` et `MontantAvecTrace`
    - Tous `frozen`, `extra="forbid"`
    - `GainsDecomposes` : 7 champs (salaire_regulier, heures_supplementaires_montant, vacances, jours_feries_manuels, brut_total, multiplicateur_heures_supp, seuil_heures_supp_hebdo)
    - `MontantAvecTrace` : `montant: Decimal >= 0`, `trace: CalculationTrace`
    - _Requirements: 4.1, 4.14, 5.8_

  - [x] 10.3 Implémenter `RetenuesEmploye` et `CotisationsEmployeur`
    - `RetenuesEmploye` : 7 `MontantAvecTrace` (RRQ, RQAP, AE, impôt QC formule, impôt QC retenu, impôt fédéral formule, impôt fédéral retenu) + `total_retenues_employe` avec vérification de somme
    - `CotisationsEmployeur` : 6 `MontantAvecTrace` (RRQ_er, RQAP_er, AE_er, FSS, CNESST, CNT) + drapeau `cnesst_en_attente_classification` + `total_cotisations_employeur` avec vérification de somme
    - _Requirements: 4.2, 4.3, 12.8_

  - [x] 10.4 Implémenter `PayrollResult`
    - `frozen`, `extra="forbid"`
    - Champs : `id_paie`, `version >= 1`, `employe_id`, `annee_fiscale`, `pay_period`, `gains`, `retenues_employe`, `cotisations_employeur`, `net`, `cout_employeur`, `cumuls_fin`, `statut`, `remplace_par_id`, `date_creation`, `date_emission`
    - `model_validator(mode="after")` :
      1. Identités comptables (Req 4.9, 4.10)
      2. Biconditionnelles statut/remplace_par_id/date_emission (Req 6.3–6.5, 6.7)
      3. Cohérence `cumuls_fin` (employe_id, annee)
    - _Requirements: 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 6.1–6.7_

- [x] 11. Checkpoint intermédiaire
  - Exécuter `pytest -m "property or unsupported" -x` sur tous les modèles créés jusqu'ici
  - Vérifier qu'aucun `float` n'apparaît dans les annotations des modèles via introspection
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Chargeur de paramètres (`payroll_engine/parameters_loader.py`)
  - [x] 12.1 Écrire les tests d'exemple et property test du chargeur
    - **Property 15 : Déterminisme de `load_parameters`** — Hypothesis génère un fichier de paramètres temporaire (via `tmp_path`) et vérifie que deux appels successifs retournent des instances `==`. **Validates: Requirements 9.10**
    - Tests d'exemple : `load_parameters(2026, Juridiction.QUEBEC)` charge `parameters/2026/quebec.json` sans erreur pour les sections sans `TO_FILL`
    - Test d'exemple : accès à un champ marqué `"TO_FILL"` lève `MissingParameterError` avec un chemin JSON identifié (ex. `rrq.maximum_gains_admissibles_mga`) et référence au fichier à mettre à jour (Req 8.5, 8.6, 9.5, 9.11)
    - Test d'exemple : fichier absent → `FileNotFoundError` avec année et juridiction dans le message (Req 9.8)
    - Test d'exemple : JSON contenant un littéral non guillemé (ex. `"taux_rrq": 0.063`) sur un champ `Decimal` → `ValidationError` (Req 9.4, 13.5)
    - Test d'exemple : `chemin_racine` optionnel accepté, pointant vers un dossier de test (Req 9.9)
    - Test d'exemple : deux `Decimal` chargés sont strictement égaux à ceux produits par `Decimal(str_value)` (aucune conversion via `float`) (Req 9.3, 9.4)
    - Test d'exemple : la validation n'est PAS déclenchée à l'import du module (Req 9.7)
    - Test d'exemple : `MissingParameterError` n'est PAS une sous-classe de `UnsupportedPayrollCase` et vice versa (Req 8.2)
    - _Requirements: 8.2, 8.5, 8.6, 9.1–9.11, 13.5_

  - [x] 12.2 Implémenter `ParametresAnnee` et ses sous-modèles typés
    - Pydantic v2, `frozen`, `extra="allow"` au niveau des sous-modèles de paramètres (accepte les clés d'audit `commentaire`, `statut`, etc.)
    - Sous-modèles : `FrequencePaieParametres`, `RRQParametres`, `RQAPParametres`, `AEParametres`, `ImpotQCParametres`, `ImpotFederalParametres`, `TD1015_3Parametres`, `TD1Parametres`, `FSSParametres`, `CNESSTParametres`, `CNTParametres`, `VacancesParametres`, `HeuresSupplementairesParametres`
    - Racine `ParametresAnnee` : `annee`, `juridiction`, `source`, `date_publication`, `url_consultee`, sections optionnelles selon juridiction
    - Sections marquées entièrement `"TO_FILL"` : chargement différé via propriété qui matérialise à l'accès
    - _Requirements: 9.6_

  - [x] 12.3 Implémenter `load_parameters(annee, juridiction, chemin_racine=None) -> ParametresAnnee`
    - Utilise `_parse_json_reject_floats` (aucun `float` intermédiaire)
    - Convertit chaque chaîne numérique en `Decimal(str)`
    - Fail-fast sur `"TO_FILL"` au premier accès à la section consommée, avec message renvoyant à TP-1015.F 2026 ou T4127 2026
    - Aucun cache ni état global (déterministe)
    - `chemin_racine` par défaut : `Path(__file__).parent.parent / "parameters"`
    - `FileNotFoundError` si le fichier attendu n'existe pas
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 9.8, 9.9, 9.10, 9.11_

  - [x] 12.4 Implémenter le mécanisme de repli `nb_periodes_annuelles`
    - Ordre : (a) fichier de l'année courante → (b) fichier de l'année précédente → (c) valeur par défaut `26`
    - Métadonnée `source_effective` exposée sur `frequence_paie` (`"annee_courante"`, `"repli_annee_<AAAA>"`, `"valeur_par_defaut"`)
    - **Aucune valeur en dur** autre que `26` (documenté comme repli, pas comme paramètre fiscal)
    - Tests d'exemple : les 3 branches du repli sont couvertes (utiliser un `tmp_path` avec fichiers factices)
    - _Requirements: 2.7_

  - [x] 12.5 Câbler la fabrique `Employee.avec_defauts_par_annee` au chargeur
    - Supprimer l'éventuel import circulaire (import différé à l'intérieur de la fabrique)
    - Test d'exemple : la fabrique lit effectivement `parameters/2026/quebec.json` et `parameters/2026/canada.json`, pas de valeur en dur
    - _Requirements: 1.7_

- [x] 13. Round-trip JSON déterministe pour tous les modèles du domaine
  - [x] 13.1 Écrire le property test de round-trip (`tests/models/test_round_trip.py`)
    - **Property 6 : Round-trip JSON déterministe** — Hypothesis génère des instances valides de `Employee`, `WeekSegment`, `PayPeriod`, `HeuresParSemaine`, `CumulsYTD`, `PayrollInput`, `GainsDecomposes`, `MontantAvecTrace`, `RetenuesEmploye`, `CotisationsEmployeur`, `PayrollResult`, `CalculationTrace`. Pour chacune, vérifie : (a) `parse(serialize(x)) == x` champ à champ, (b) sérialisation déterministe (deux appels produisent la même chaîne, à l'ordre des clés près), (c) la chaîne ne contient aucun littéral numérique non guillemé pour un champ typé `Decimal` (test regex). **Validates: Requirements 5.5, 7.8, 13.1, 13.2, 13.3, 13.4**
    - _Requirements: 5.5, 7.8, 13.1, 13.2, 13.3, 13.4_

  - [x] 13.2 Ajouter/vérifier les `field_serializer` et sérialiseurs JSON dans chaque modèle
    - Sérialiseur `Decimal → str` sur chaque champ `Decimal` de chaque modèle du domaine
    - `model_validate_json` sur les modèles de haut niveau reroute vers `_parse_json_reject_floats`
    - Ordre stable des `sous_totaux` de `CalculationTrace` (dict ordonné Python 3.7+)
    - _Requirements: 13.1, 13.3, 13.4_

- [x] 14. Golden tests des scénarios QC001 à QC006
  - [x] 14.1 Créer les fixtures d'entrée anonymisées pour QC001 à QC006 (`tests/fixtures/inputs/qc0XX.json`)
    - Chaque fixture est un JSON conforme au contrat `PayrollInput`, avec identifiants fictifs (`EMP001`, `Monitrice EMP001`, ...) et dates fictives
    - **Aucun NAS, compte bancaire, adresse ou nom réel** (règle 04)
    - Valeurs d'entrée conformes à Req 12.1–12.6 (brut, heures, taux, exonérations)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 14.2 Créer les fixtures de sortie anonymisées pour QC001 à QC006 (`tests/fixtures/outputs/qc0XX.json`)
    - Chaque fixture est un JSON conforme au contrat `PayrollResult`, valeurs WebRAS/PDOC issues des `docs/scenario-qc0XX.md`
    - Distinction stricte `impot_qc_formule` / `impot_qc_retenu` (Req 12.8) — idem fédéral
    - `CalculationTrace` de chaque montant avec source officielle (TP-1015.F 2026 ou T4127 2026)
    - _Requirements: 12.7, 12.8, 12.9_

  - [x] 14.3 Écrire les golden tests d'entrée (`tests/test_golden_inputs.py`)
    - Pour chaque QC00X : charger la fixture, construire un `PayrollInput`, sérialiser en JSON, comparer à la fixture (round-trip fidèle)
    - Marqué `@pytest.mark.golden`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 14.4 Écrire les golden tests de sortie (`tests/test_golden_outputs.py`)
    - Pour chaque QC00X : charger la fixture, construire un `PayrollResult`, vérifier que toutes les identités comptables passent, sérialiser en JSON, comparer à la fixture au cent près
    - Marqué `@pytest.mark.golden`
    - _Requirements: 12.7, 12.8, 12.9_

- [x] 15. Tests de garde statique (`tests/test_guards.py`)
  - [x] 15.1 Test de garde : aucun champ typé `float` dans les modèles
    - Introspection sur `Model.model_fields` de chacun des 12 modèles du domaine (`Employee`, `WeekSegment`, `PayPeriod`, `HeuresParSemaine`, `CumulsYTD`, `PayrollInput`, `GainsDecomposes`, `MontantAvecTrace`, `RetenuesEmploye`, `CotisationsEmployeur`, `PayrollResult`, `CalculationTrace`)
    - Assertion : aucune annotation `float`, aucun `Union[float, ...]`, aucun `float` dans un `dict[str, ...]`
    - _Requirements: 10.3_

  - [x] 15.2 Test de garde : aucune valeur fiscale en dur dans `models/` ni `payroll_engine/`
    - Grep des motifs `Decimal("0.063")`, `Decimal("0.0043")`, `Decimal("0.0130")`, `"18952"`, `"16452"`, `Decimal("0.0165")` (FSS), `Decimal("0.0112")` (CNESST provision)
    - Seul emplacement autorisé : `parameters/<AAAA>/*.json`
    - Exceptions documentées : `Decimal("0.04")` et `Decimal("0.06")` dans le validateur de taux vacances (convention métier, pas paramètre fiscal), `Decimal("168")` dans les bornes d'heures (borne physique), `26` dans le repli `nb_periodes_annuelles` (repli documenté)
    - _Requirements: 5 (règle steering), 9.3_

  - [x] 15.3 Test de garde : disjonction des hiérarchies d'exception
    - `assert not issubclass(UnsupportedPayrollCase, pydantic.ValidationError)`
    - `assert not issubclass(MissingParameterError, pydantic.ValidationError)`
    - `assert not issubclass(UnsupportedPayrollCase, MissingParameterError)` et vice versa (Req 8.2)
    - _Requirements: 8.2, 8.7_

  - [x] 15.4 Test de garde : contrat des messages d'exception
    - **Property 16 : Contrat des messages d'exception du domaine** — chaque `UnsupportedPayrollCase` levée par les validateurs contient le nom du cas refusé et mentionne "WebRAS" ou "PDOC" ; chaque `MissingParameterError` levée par le loader contient le chemin JSON, l'année, la juridiction, le fichier. **Validates: Requirements 8.3, 8.6, 11.6**
    - _Requirements: 8.3, 8.6, 11.6_

  - [x] 15.5 Test de garde : absence de données personnelles dans les fixtures
    - Grep sur `tests/fixtures/**/*.json` contre : NAS à 9 chiffres, patterns d'IBAN, adresses postales, noms complets non anonymisés
    - _Requirements: règle 04_

- [x] 16. Checkpoint final
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (property + golden + garde + unit)
  - Vérifier que `pytest -m property` exécute au moins 16 tests (un par propriété du design)
  - Vérifier que `pytest -m golden` exécute au moins 12 tests (6 entrées + 6 sorties)
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, golden tests et tests de garde soient rédigés **avant** l'implémentation et ne peuvent être considérés comme facultatifs. La discipline TDD stricte est un livrable de la spec, pas une option.
- **Ordre spec → tests → implémentation → validation** respecté à chaque tâche parente : les sous-tâches de test précèdent les sous-tâches d'implémentation.
- **Chaque property test est référencé au numéro de la propriété du design** (`Property N`) et au numéro des exigences EARS qu'il valide (`Requirements X.Y`).
- **Aucune formule fiscale** n'est implémentée : cette spec établit uniquement les contrats. Les modules RRQ, RQAP, AE, impôts et charges patronales relèvent des specs 2 à 8 du plan.
- **Aucun paramètre fiscal en dur** dans le code Python : la seule valeur autorisée est `26` (repli documenté de `nb_periodes_annuelles`, ce n'est pas un paramètre fiscal au sens de la règle 05).
- **Fixtures anonymisées obligatoires** : les scénarios QC001–QC006 utilisent des identifiants fictifs, jamais de données personnelles réelles (règle 04).
- **Validation croisée avec les outils officiels** (WebRAS, PDOC) est menée à part par l'opérateur du camp et consignée dans `docs/journal-validation.md` : cette étape n'est pas une tâche de code et n'apparaît donc pas dans ce plan.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2"] },
    { "id": 5, "tasks": ["5.1", "6.1", "7.1"] },
    { "id": 6, "tasks": ["5.2", "6.2", "7.2"] },
    { "id": 7, "tasks": ["7.3", "6.4"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["9.1", "10.1"] },
    { "id": 11, "tasks": ["9.2", "10.2"] },
    { "id": 12, "tasks": ["10.3"] },
    { "id": 13, "tasks": ["10.4"] },
    { "id": 14, "tasks": ["12.1"] },
    { "id": 15, "tasks": ["12.2"] },
    { "id": 16, "tasks": ["12.3", "12.4"] },
    { "id": 17, "tasks": ["6.3", "12.5"] },
    { "id": 18, "tasks": ["13.1"] },
    { "id": 19, "tasks": ["13.2"] },
    { "id": 20, "tasks": ["14.1", "14.2"] },
    { "id": 21, "tasks": ["14.3", "14.4"] },
    { "id": 22, "tasks": ["15.1", "15.2", "15.3", "15.4", "15.5"] }
  ]
}
```
