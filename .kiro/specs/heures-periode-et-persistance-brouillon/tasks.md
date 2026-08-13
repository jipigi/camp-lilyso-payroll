# Implementation Plan: heures-periode-et-persistance-brouillon

<!-- Plan d'implémentation — bugfix « heures-periode-et-persistance-brouillon ».
     Les en-têtes structurels (Overview, Tasks, Notes, Task Dependency Graph)
     sont maintenus en anglais pour conformité au format Kiro. Le contenu
     métier est en français. -->

## Overview

Ce bugfix corrige deux défauts indépendants mais colocalisés du Formulaire_Paie
(`bugfix.md`, `design.md`) :

- **Bug 1** — saisie des heures à 4 champs au lieu de 2 totaux
  (`app/pages_ui/formulaire_paie.py`, nouvelle fonction `repartir_heures_sur_semaines`
  dans `app/logique_metier/formulaire_paie.py`).
- **Bug 2** — brouillon non restituable intégralement, `PayrollInput` jamais persisté
  (`payroll_engine/register.py`, nouvelle colonne nullable `payload_input_json`,
  `app/logique_metier/formulaire_paie.py::valeurs_effectives_depuis_paie`).

Les deux bugs partagent le même point d'ancrage (le cycle saisie → assemblage →
enregistrement → reprise du Formulaire_Paie) mais restent **fonctionnellement
indépendants** : aucune formule fiscale, aucun paramètre annuel (règle 05) ni le
contrat `PayrollInput`/`PayrollResult` (règle 01, règle 02) n'est modifié.

Les 4 propriétés de correction du design (`design.md` §Correctness Properties)
pilotent l'ordre des tâches, suivant la méthodologie bug condition :

- **Property 1 / Property 2 (Bug Condition)** — écrites et exécutées AVANT toute
  correction ; elles doivent ÉCHOUER sur le code non corrigé (confirment que le
  bug existe).
- **Property 3 / Property 4 (Preservation)** — écrites et exécutées AVANT toute
  correction ; elles doivent PASSER sur le code non corrigé (comportement de
  référence à préserver).

La correction (section 5 et 6) n'est implémentée qu'ensuite, puis validée en
ré-exécutant les 4 mêmes tests — aucun nouveau test n'est écrit après la
correction (méthodologie observation-first, `06-workflow-kiro.md`).

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — `Decimal` de bout en bout ; `payload_input_json` est du `TEXT`
  sérialisé via `PayrollInput.model_dump_json()`, jamais `float`
- Règle 02 — aucune nouvelle `CalculationTrace` introduite ; `net_pay.py` n'est
  pas modifié
- Règle 03 — aucun nouveau garde-fou de périmètre ; erreurs de validation
  d'origine propagées sans interception
- Règle 04 — tests exclusivement sur base temporaire (`tmp_path`) ou `:memory:`,
  identifiants fictifs `EMPnnn`
- Règle 05 — aucun paramètre fiscal touché ; `calcul_gains`/`payroll_engine/gains_bruts.py`
  non modifiés
- Règle 06 — sections 1 à 4 (exploration + préservation) rédigées et vérifiées
  **avant** la correction (sections 5 et 6), qui précèdent le checkpoint final
  (section 7)

## Tasks

- [x] 1. Write bug condition exploration test — Bug 1 (saisie des heures à 4 champs)
  - **Property 1: Bug Condition** — Saisie à 2 totaux, répartition fiscalement neutre
  - **IMPORTANT**: Write this property-based test BEFORE implementing the fix
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **GOAL**: Surfacer l'absence de toute fonction de répartition
    (`repartir_heures_sur_semaines`) dans `app/logique_metier/formulaire_paie.py`,
    confirmant que le formulaire actuel exige toujours 4 champs pour toute saisie
    `AUX_DEUX_SEMAINES` (`isBugCondition_Heures(X) = X.frequence == AUX_DEUX_SEMAINES`,
    toujours vrai — design §Bug Condition)
  - Fichier : `tests/app/logique_metier/test_formulaire_paie.py` (nouvelle classe,
    ex. `TestRepartirHeuresSurSemaines`)
  - Test 1 (exemple, cas déterministe) : `from app.logique_metier.formulaire_paie
    import repartir_heures_sur_semaines` échoue par `ImportError`/`AttributeError`
    sur le code non corrigé — scope à ce cas concret (fonction absente, pas une
    propriété générative)
  - Test 2 (property-based, Hypothesis) : pour des totaux
    `total_heures_normales`/`total_heures_supplementaires` générés dans `[0, 168]`
    (bornes `HeuresParSemaine`), l'appel à `repartir_heures_sur_semaines(...)`
    échoue systématiquement sur le code non corrigé
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (`ImportError`/`AttributeError`) — confirme
    que le bug (4 champs obligatoires, aucune répartition interne) existe
  - Document counterexamples found (ex. « `repartir_heures_sur_semaines` n'existe
    pas dans `app.logique_metier.formulaire_paie` »)
  - Mark task complete when tests are written, run, and failure is documented
  - _Requirements: 1.1, 1.2_

- [x] 2. Write bug condition exploration test — Bug 2 (brouillon non restituable)
  - **Property 2: Bug Condition** — Restitution intégrale d'un brouillon post-correction
  - **IMPORTANT**: Write this property-based test BEFORE implementing the fix
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **GOAL**: Surfacer l'absence de persistance du `PayrollInput`
    (`isBugCondition_Brouillon(X) = X.paie_deja_enregistree == true AND
    X.payload_input_json_disponible == false`, toujours vrai sur le code non
    corrigé — design §Bug Condition)
  - Fichier : `tests/payroll_engine/test_register.py` (nouvelle classe, ex.
    `TestExplorationPersistancePayrollInput`) et
    `tests/app/logique_metier/test_formulaire_paie.py` (nouvelle classe, ex.
    `TestExplorationValeursEffectivesHeures`)
  - Test 1 (exemple) : `PRAGMA table_info(paies)` (via `tmp_path`/`":memory:"`,
    jamais la base de production — règle 04) ne contient pas la colonne
    `payload_input_json` après `_creer_schema_si_absent` sur le code non corrigé
  - Test 2 (exemple) : `lire_paie(id_paie)` retourne un `PayrollResult` seul —
    `resultat, payroll_input = lire_paie(id_paie)` échoue par `TypeError`
    (« cannot unpack non-iterable PayrollResult ») sur le code non corrigé
  - Test 3 (property-based, Hypothesis, réutilise `tests/strategies.py::st_payroll_input`/
    générateur de `PayrollResult` existant) : pour tout `PayrollResult` généré,
    `valeurs_effectives_depuis_paie(resultat)` ne contient JAMAIS les clés
    `total_heures_normales`/`total_heures_supplementaires` sur le code non corrigé,
    quelles que soient les heures d'origine
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL/confirment l'absence de restitution —
    `PRAGMA table_info` sans la colonne, `TypeError` à la déstructuration, dict
    sans les clés d'heures
  - Document counterexamples found (ex. « `valeurs_effectives_depuis_paie(resultat)`
    ne restitue jamais les heures, même pour un brouillon inséré à l'instant »)
  - Mark task complete when tests are written, run, and failure is documented
  - _Requirements: 1.3, 1.4_

- [x] 3. Write preservation property test — neutralité fiscale de la répartition interne (Bug 1)
  - **Property 3: Preservation** — Neutralité fiscale de la répartition interne
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: sur le code non corrigé (moteur fiscal inchangé par ce bugfix),
    `calcul_gains(payroll_input, parametres_annee)` ne lit jamais
    `heures_par_semaine[0]`/`[1]` individuellement — vérifié par lecture directe
    de `payroll_engine/gains_bruts.py` (design §Hypothesized Root Cause, point 4)
  - Fichier : `tests/payroll_engine/test_gains_bruts.py` (nouvelle classe, ex.
    `TestNeutraliteRepartitionInterne`) — teste `calcul_gains` directement, module
    non modifié par ce bugfix
  - Write property-based test (Hypothesis) : pour tout couple
    `(total_heures_normales, total_heures_supplementaires)` dans `[0, 168]` et
    pour au moins 2 répartitions internes candidates distinctes des mêmes 2
    totaux sur les 2 `HeuresParSemaine` (ex. « tout sur semaine 1 » et « 50/50 »),
    `calcul_gains` appliqué aux 2 `PayrollInput` résultants (mêmes autres champs,
    `ParametresAnnee` quelconque valide) produit un `GainsDecomposes` strictement
    identique (`salaire_regulier`, `heures_supplementaires_montant`, `vacances`,
    `jours_feries_manuels`, `brut_total`)
  - Verify test passes on UNFIXED code (ce test caractérise le moteur fiscal
    déjà existant, non affecté par ce bugfix — il doit passer aussi bien avant
    qu'après la correction)
  - **EXPECTED OUTCOME**: Test PASSES — confirme la neutralité fiscale déjà
    garantie par le moteur, base de la Property 1 (Fix Checking)
  - Mark task complete when test is written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2_

- [x] 4. Write preservation tests — paies pré-correction, Action_Corriger, non-régression golden (Bug 2)
  - **Property 4: Preservation** — Comportement inchangé pour les paies pré-correction et pour l'Action_Corriger
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: sur le code non corrigé, une ligne `paies` sans `PayrollInput`
    associé (cas normal, puisque `payload_input_json` n'existe même pas encore)
    est relue sans exception, et `valeurs_effectives_depuis_paie` affiche
    `"0.00"` avec l'avertissement existant
  - Fichier : `tests/payroll_engine/test_register.py` (nouvelle classe, ex.
    `TestPreservationPaiesPreCorrection`) et
    `tests/app/logique_metier/test_formulaire_paie.py` (cas d'exemple ajoutés à
    la classe créée en tâche 2)
  - Test 1 (property-based, Hypothesis + `tmp_path`, réutilise
    `st_sequence_payroll_results_meme_employe_annee`/générateurs existants de
    `tests/strategies.py`) : pour tout `PayrollResult` inséré via
    `inserer_paie(resultat, saison, chemin_bd=...)` (signature actuelle, sans
    `PayrollInput`) puis relu, aucune exception n'est levée et
    `valeurs_effectives_depuis_paie(resultat_relu)` ne contient pas les clés
    d'heures — comportement à préserver strictement identique après correction
    pour ce type d'appel (Req 3.4)
  - Test 2 (exemple) : `remplacer_paie` sur une paie `EMISE` existante continue
    de produire une nouvelle version incrémentée (`version + 1`), une
    confirmation explicite reste requise côté UI (déjà couverte par les tests
    existants de `_section_corriger_paie` — ne pas dupliquer, seulement vérifier
    que la signature actuelle `remplacer_paie(ancien_id, nouveau_resultat, saison,
    chemin_bd=...)` fonctionne sans régression), et `cumuls_ytd` est recalculé à
    l'identique (Req 3.3)
  - Test 3 (exemple, non-régression) : référencer explicitement dans le test
    l'exécution de la suite existante `tests/test_golden_outputs.py`/
    `tests/payroll_engine/test_gains_bruts.py` et confirmer qu'aucune de ces
    suites n'est modifiée par ce bugfix (Req 3.5, 3.6)
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASSENT — confirme le comportement de référence
    à préserver après correction (aucune exception sur colonne absente,
    versioning/cumuls inchangés, golden tests intacts)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.3, 3.4, 3.5, 3.6_

- [x] 5. Fix — Bug 1 : remplacer les 4 champs d'heures par 2 totaux + répartition interne

  - [x] 5.1 Implémenter `repartir_heures_sur_semaines` dans `app/logique_metier/formulaire_paie.py`
    - Nouvelle fonction pure à mots-clés :
      `repartir_heures_sur_semaines(*, total_heures_normales: Decimal,
      total_heures_supplementaires: Decimal) -> tuple[HeuresParSemaine, HeuresParSemaine]`
    - Répartition arbitraire déterministe retenue par le design : totalité sur
      `heures_semaine_1`, `heures_semaine_2` à `Decimal("0.00")` pour les deux
      quantités — aucune validation de bornes ajoutée (propagation de
      `pydantic.ValidationError` depuis `HeuresParSemaine`, règle 03)
    - _Bug_Condition: isBugCondition_Heures(X) = X.frequence == AUX_DEUX_SEMAINES (design §Bug Condition — Bug 1)_
    - _Expected_Behavior: repartir_heures_sur_semaines(total_hn, total_hs) retourne un tuple de 2 HeuresParSemaine dont la somme des heures_normales == total_hn et la somme des heures_supplementaires == total_hs (design §Correctness Properties, Property 1)_
    - _Requirements: 2.1, 2.2_

  - [x] 5.2 Remplacer les 4 champs de saisie par 2 champs dans `app/pages_ui/formulaire_paie.py`
    - `_section_nouvelle_paie` : retirer les 4 `st.text_input` (`fp_nouvelle_hn1`,
      `fp_nouvelle_hs1`, `fp_nouvelle_hn2`, `fp_nouvelle_hs2`) et les remplacer
      par 2 `st.text_input` (`fp_nouvelle_total_hn`, `fp_nouvelle_total_hs`),
      pré-remplis depuis `valeurs_precharge.get("total_heures_normales", "0.00")`/
      `.get("total_heures_supplementaires", "0.00")` s'ils sont disponibles
    - `_section_corriger_paie` : même changement avec les clés
      `fp_corriger_total_hn`/`fp_corriger_total_hs`
    - Dans `_assembler()`/`_reassembler()` : appeler
      `repartir_heures_sur_semaines(...)` puis transmettre le résultat inchangé
      à `construire_payroll_input(heures_semaine_1=..., heures_semaine_2=...)`
    - Ajouter l'import de `repartir_heures_sur_semaines` depuis
      `app.logique_metier.formulaire_paie`
    - Conserver le `PayrollInput` assemblé dans `st.session_state` (clés
      `fp_nouvelle_payroll_input_assemble`/`fp_corriger_payroll_input_reassemble`)
      pour transmission à la tâche 6.5
    - _Bug_Condition: isBugCondition_Heures(X) = X.frequence == AUX_DEUX_SEMAINES (design §Bug Condition — Bug 1)_
    - _Expected_Behavior: le formulaire expose exactement 2 champs de saisie d'heures pour la période complète (design §Correctness Properties, Property 1)_
    - _Preservation: calcul_gains produit un résultat fiscal identique quelle que soit la répartition interne choisie (design §Correctness Properties, Property 3)_
    - _Requirements: 2.1, 2.2_

  - [x] 5.3 Vérifier que le test d'exploration Bug 1 passe désormais
    - **Property 1: Expected Behavior** — Saisie à 2 totaux, répartition fiscalement neutre
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Exécuter les tests de la tâche 1 (`test_formulaire_paie.py::TestRepartirHeuresSurSemaines`)
      sur le code corrigé
    - **EXPECTED OUTCOME**: Tests PASSENT — confirme que
      `repartir_heures_sur_semaines` existe et respecte la propriété de somme
    - _Requirements: 2.1, 2.2_

  - [x] 5.4 Vérifier que le test de préservation Property 3 passe toujours
    - **Property 3: Preservation** — Neutralité fiscale de la répartition interne
    - **IMPORTANT**: Re-run the SAME test from task 3 — do NOT write a new test
    - Exécuter le test de la tâche 3 (`test_gains_bruts.py::TestNeutraliteRepartitionInterne`)
      sur le code corrigé
    - **EXPECTED OUTCOME**: Test PASSE toujours — confirme qu'aucune régression
      n'a été introduite dans `payroll_engine/gains_bruts.py` (module non
      modifié par cette tâche)
    - _Requirements: 3.1, 3.2_

- [ ] 6. Fix — Bug 2 : persister et restituer le `PayrollInput` d'un brouillon

  - [x] 6.1 Étendre le schéma SQL de `payroll_engine/register.py` — colonne nullable + migration additive
    - Ajouter `payload_input_json TEXT` (nullable, pas de `NOT NULL`) à `_DDL_PAIES`
    - Ajouter `_ajouter_colonne_payload_input_json_si_absente(connexion)` :
      vérifie via `PRAGMA table_info(paies)` puis exécute `ALTER TABLE paies ADD
      COLUMN payload_input_json TEXT` si absente — idempotent, aucune donnée
      existante modifiée (règle 06 immutabilité historique)
    - Appeler ce helper depuis `_creer_schema_si_absent`
    - _Bug_Condition: isBugCondition_Brouillon(X) = X.paie_deja_enregistree == true AND X.payload_input_json_disponible == false (design §Bug Condition — Bug 2)_
    - _Preservation: les lignes déjà présentes avant le déploiement reçoivent NULL, jamais de rétro-remplissage (design §Preservation Requirements, Req 3.4)_
    - _Requirements: 2.3_

  - [x] 6.2 Persister le `PayrollInput` dans `inserer_paie`/`remplacer_paie`/`_inserer_ligne_paie_tx`
    - `_inserer_ligne_paie_tx` : nouveau paramètre `payload_input_json: str | None`,
      ajouté à l'`INSERT`
    - `inserer_paie` : nouveau paramètre optionnel
      `payroll_input: PayrollInput | None = None` (positionné après `saison`,
      avant `chemin_bd`), sérialisé via `payroll_input.model_dump_json()` si
      fourni, sinon `None`
    - `remplacer_paie` : nouveau paramètre optionnel
      `nouveau_payroll_input: PayrollInput | None = None`, même mécanisme —
      l'ancienne ligne n'est jamais modifiée dans sa colonne `payload_input_json`
      (immutabilité déjà portée par le registre)
    - _Bug_Condition: isBugCondition_Brouillon(X) (design §Bug Condition — Bug 2)_
    - _Expected_Behavior: inserer_paie'/remplacer_paie' persistent PayrollInput dans payload_input_json (design §Correctness Properties, Property 2)_
    - _Preservation: payroll_input=None (défaut) laisse payload_input_json à NULL, aucun appelant existant cassé (design §Correctness Properties, Property 4)_
    - _Requirements: 2.3_

  - [x] 6.3 Étendre `lire_paie`/`lire_historique_paie` pour retourner le `PayrollInput` relu
    - `lire_paie` : retourne désormais `tuple[PayrollResult, PayrollInput | None]`
      — `None` si `payload_input_json` est `NULL`, jamais d'exception ; sinon
      `PayrollInput.model_validate_json(...)` (rupture de signature assumée,
      design §Fix Implementation point 6)
    - `lire_historique_paie` : retourne désormais
      `tuple[tuple[PayrollResult, PayrollInput | None], ...]`, extension symétrique
    - _Bug_Condition: isBugCondition_Brouillon(X) (design §Bug Condition — Bug 2)_
    - _Expected_Behavior: lire_paie'/lire_historique_paie' restituent le PayrollInput persisté sans exception (design §Correctness Properties, Property 2)_
    - _Preservation: payload_input_json NULL (Paie_Pre_Correction) => payroll_input is None, aucune exception (design §Correctness Properties, Property 4)_
    - _Requirements: 2.4, 3.4_

  - [x] 6.4 Étendre `valeurs_effectives_depuis_paie` dans `app/logique_metier/formulaire_paie.py`
    - Nouveau paramètre optionnel `payroll_input_persiste: PayrollInput | None = None`
    - Si fourni : ajouter `total_heures_normales`/`total_heures_supplementaires`
      au dict retourné, calculés par sommation directe de
      `payroll_input_persiste.heures_par_semaine` (inverse de
      `repartir_heures_sur_semaines`)
    - Si `None` : les deux clés restent absentes du dict (comportement Req 3.4
      inchangé)
    - _Bug_Condition: isBugCondition_Brouillon(X) (design §Bug Condition — Bug 2)_
    - _Expected_Behavior: valeurs_effectives_depuis_paie'(resultat, payroll_input_persiste) restitue total_heures_normales == somme(heures_par_semaine[*].heures_normales) et total_heures_supplementaires == somme(heures_par_semaine[*].heures_supplementaires) (design §Correctness Properties, Property 2)_
    - _Preservation: payroll_input_persiste=None (défaut) => dict sans les 2 clés, comportement identique à avant cette correction (design §Correctness Properties, Property 4)_
    - _Requirements: 2.4, 3.4_

  - [x] 6.5 Mettre à jour les appelants dans `app/pages_ui/formulaire_paie.py`
    - `_section_enregistrement` : transmettre `payroll_input_assemble` (lu depuis
      `st.session_state`, conservé à la tâche 5.2) à
      `inserer_paie(..., payroll_input=payroll_input_assemble, ...)`
    - `_section_corriger_paie` (bloc `_remplacer()`) : transmettre
      `st.session_state.get("fp_corriger_payroll_input_reassemble")` à
      `remplacer_paie(..., nouveau_payroll_input=..., ...)`
    - Préchargement de brouillon (`_section_nouvelle_paie`) : déstructurer le
      couple retourné par `lire_paie` (`paie_brouillon, payroll_input_brouillon
      = ...`), transmettre les deux à
      `valeurs_effectives_depuis_paie(paie_brouillon, payroll_input_brouillon)`,
      adapter le message affiché selon la présence ou non des clés d'heures
      dans `valeurs_precharge`
    - Tout autre appelant de `lire_paie` (`_section_corriger_paie`) mis à jour
      pour déstructurer le couple (utiliser `_` si le `PayrollInput` n'est pas
      utilisé à cet endroit)
    - _Bug_Condition: isBugCondition_Brouillon(X) (design §Bug Condition — Bug 2)_
    - _Expected_Behavior: reprise d'un brouillon post-correction affiche les 2 totaux d'heures d'origine, sans ressaisie forcée (design §Correctness Properties, Property 2)_
    - _Preservation: reprise d'un brouillon pré-correction continue d'afficher "0.00" avec avertissement (design §Correctness Properties, Property 4)_
    - _Requirements: 2.4, 3.4_

  - [x] 6.6 Vérifier que le test d'exploration Bug 2 passe désormais
    - **Property 2: Expected Behavior** — Restitution intégrale d'un brouillon post-correction
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Exécuter les tests de la tâche 2 (`test_register.py::TestExplorationPersistancePayrollInput`,
      `test_formulaire_paie.py::TestExplorationValeursEffectivesHeures`) sur le
      code corrigé
    - **EXPECTED OUTCOME**: Tests PASSENT — `payload_input_json` existe,
      `lire_paie` retourne un couple, `valeurs_effectives_depuis_paie` restitue
      les 2 totaux pour une paie post-correction
    - _Requirements: 2.3, 2.4_

  - [x] 6.7 Vérifier que les tests de préservation Property 4 passent toujours
    - **Property 4: Preservation** — Comportement inchangé pour les paies pré-correction et pour l'Action_Corriger
    - **IMPORTANT**: Re-run the SAME tests from task 4 — do NOT write new tests
    - Exécuter les tests de la tâche 4 (`test_register.py::TestPreservationPaiesPreCorrection`
      et cas ajoutés à `test_formulaire_paie.py`) sur le code corrigé
    - **EXPECTED OUTCOME**: Tests PASSENT toujours — aucune exception sur
      `payload_input_json` `NULL`, versioning/cumuls de `remplacer_paie`
      inchangés, golden tests intacts
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.3, 3.4, 3.5, 3.6_

- [x] 7. Checkpoint - Ensure all tests pass
  - Exécuter la suite complète (`pytest`) : tests des tâches 1 à 4 (mêmes tests,
    maintenant sur code corrigé), tests unitaires additionnels de
    `repartir_heures_sur_semaines`/schéma SQL/`valeurs_effectives_depuis_paie`
    (design §Testing Strategy §Unit Tests), et l'intégralité des golden tests /
    property-based tests existants du moteur fiscal
    (`tests/test_golden_outputs.py`, `tests/payroll_engine/*`) sans aucune
    modification (Req 3.6)
  - Vérifier qu'aucun `float` n'apparaît dans le diff des modules touchés
    (règle 01, garde-fou existant)
  - Ensure all tests pass, ask the user if questions arise

## Notes

- **Deux bugs, un seul plan** : Bug 1 (sections 1, 3, 5) et Bug 2 (sections 2, 4, 6)
  sont fonctionnellement indépendants et peuvent être développés en parallèle
  après le checkpoint d'exploration — ils ne partagent aucun fichier de test ni
  aucune fonction implémentée, seulement le module `app/pages_ui/formulaire_paie.py`
  en écriture (tâches 5.2 et 6.5 touchent des sections distinctes de ce fichier).
- **Aucun nouveau test après la correction** : les tâches 5.3/5.4 et 6.6/6.7
  ré-exécutent strictement les mêmes tests écrits aux tâches 1 à 4 — la
  méthodologie observation-first interdit d'écrire un nouveau test de
  validation après coup.
- **Rupture de signature assumée** : `lire_paie` retourne désormais un couple
  `(PayrollResult, PayrollInput | None)` (tâche 6.3) — tous les appelants
  existants (`app/pages_ui/formulaire_paie.py`) sont mis à jour dans la même
  tâche 6.5, pas de compatibilité arrière conservée pour cette fonction
  spécifique (design §Fix Implementation, point 6).
- **Immutabilité historique (règle 06)** : la tâche 6.1 ajoute une colonne
  nullable sans aucune migration rétroactive des lignes déjà présentes — les
  paies pré-correction restent avec `payload_input_json = NULL` pour toujours,
  comportement testé explicitement par la Property 4 (tâche 4, ré-exécutée en
  tâche 6.7).
- **Chaque property test est annoté** par `**Property N: Bug Condition|Preservation**`
  et référence les exigences EARS qu'il valide (`_Requirements: X.Y_`).
- **Tâche 7 — garde-fou de schéma mis à jour (`tests/test_guards.py`)** :
  `TestRegisterSchemaExact::test_schema_paies_exact` (spec antérieure
  `net-cumuls-registre`) comparait `PRAGMA table_info(paies)` à un tuple de
  référence figé à 11 colonnes. La tâche 6.1 ayant intentionnellement ajouté
  la colonne nullable `payload_input_json` en fin de DDL, ce tuple de
  référence (`_COLONNES_ATTENDUES_PAIES`) a été mis à jour pour inclure
  `("payload_input_json", "TEXT")` — décision explicite de l'utilisateur à la
  tâche 7 (mise à jour du garde-fou plutôt qu'exception documentée, puisque
  le garde-fou décrivait un schéma désormais périmé par conception, pas un
  comportement à préserver).
- **Tâche 7 — élargissement constaté de la flakiness Hypothesis/tmp_path déjà
  connue** : en plus des 4 tests initialement identifiés
  (`TestCumulYTDDeNPaies`, `TestRoundTrip`, `TestAbsenceFloat`,
  `TestRefusInsertionDupliquee`), le même mécanisme de collision `id_paie`
  (`hypothesis.errors.FlakyFailure` déclenchant
  `ValueError: id_paie '...' déjà présent`) affecte aussi, de façon
  intermittente, `tests/app/logique_metier/test_dernieres_paies.py::TestDerniereAnneePaie::test_retourne_le_maximum_des_annees_correspondant_exactement_ou_none`
  et `::TestLireResumesPaies::test_exemple_net_reste_une_chaine_jamais_reconvertie_en_float`
  — fichier non touché par ce bugfix, même cause racine préexistante, pas une
  régression introduite par les tâches 1 à 6.
- **Échec accepté à la tâche 6.7 (faux positif d'assertion, pas une régression)** :
  `test_register.py::TestPreservationPaiesPreCorrection::test_exemple_suites_golden_existantes_non_modifiees_par_ce_bugfix`
  échoue sur le code corrigé — l'assertion vérifie l'absence littérale de la
  sous-chaîne `"calcul_gains"` dans le contenu texte de
  `app/logique_metier/formulaire_paie.py`, mais la docstring de
  `repartir_heures_sur_semaines` (tâche 5.1) mentionne
  `payroll_engine.gains_bruts.calcul_gains` à titre purement documentaire
  (justification de la neutralité fiscale de la répartition interne, Property
  1/3) — aucun `import`/appel réel n'a été ajouté (vérifié par grep ciblé sur
  `^import|^from`). Le comportement réel testé (absence de couplage au moteur
  fiscal) reste vrai ; seule l'assertion par sous-chaîne produit un faux
  positif. Laissé tel quel sans modification du test ni du code, sur décision
  explicite de l'utilisateur.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3", "4"] },
    { "id": 2, "tasks": ["5.1"] },
    { "id": 3, "tasks": ["5.2"] },
    { "id": 4, "tasks": ["5.3", "5.4"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["6.2"] },
    { "id": 7, "tasks": ["6.3"] },
    { "id": 8, "tasks": ["6.4"] },
    { "id": 9, "tasks": ["6.5"] },
    { "id": 10, "tasks": ["6.6", "6.7"] },
    { "id": 11, "tasks": ["7"] }
  ]
}
```
