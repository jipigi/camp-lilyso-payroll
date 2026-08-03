# Implementation Plan: cotisations-sociales-qc

<!-- Plan d'implémentation — spec « cotisations sociales RRQ, RQAP, AE » du
     moteur de paie Camp LilySO. Les en-têtes structurels (Overview, Tasks,
     Notes, Task Dependency Graph) sont maintenus en anglais pour
     conformité au format Kiro. Le contenu métier est en français. -->

## Overview

Cette spec livre **l'étape 3 du plan d'implémentation** (`docs/plan-implementation.md`) : six fonctions pures — `calcul_rrq_employe`, `calcul_rrq_employeur` (`payroll_engine/rrq.py`), `calcul_rqap_employe`, `calcul_rqap_employeur` (`payroll_engine/rqap.py`), `calcul_ae_employe`, `calcul_ae_employeur` (`payroll_engine/assurance_emploi.py`) — qui calculent les trois cotisations sociales à taux fixe plafonné du Camp LilySO, à partir d'un `PayrollInput` figé, du `GainsDecomposes` produit par l'étape 2 (`calcul_gains`), et des paramètres annuels versionnés.

**Aucun contrat** des socles `moteur-paie-contrats` (605 tests) et `gains-bruts-vacances-hs` (649 tests) n'est modifié : cette spec **consomme** exclusivement `PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `CumulsYTD`, `Juridiction`, `ModeArrondissement`, `MissingParameterError`, `ParametresAnnee`/`RRQParametres`/`RQAPParametres`/`AEParametres`.

L'ordre suit strictement la règle 06 : **tests avant code**. Les 18 propriétés de correction du design sont regroupées en sous-tâches transversales (déterminisme/robustesse/forme, bornes/plafonnement, formules par cotisation, trace, cas d'erreur) pour éviter un émiettement en 18 tâches distinctes, tout en garantissant qu'un `grep` sur `Property N` retrouve la traçabilité intégrale.

**Livrables** :

- Extension de `tests/strategies.py` (4 nouvelles stratégies Hypothesis : `st_cumuls_ytd_non_nuls`, `st_brut_total_avec_zero`, `st_parametres_annee_2026_qc_ca`, `st_parametres_annee_avec_to_fill`)
- `tests/payroll_engine/test_rrq.py`, `test_rqap.py`, `test_assurance_emploi.py` (property tests + tests d'exemple)
- Extension de `tests/test_golden_outputs.py` (paramétrage `test_cotisations_sociales_reproduisent_fixture` sur QC001–QC006, y compris l'assertion `Decimal("1.77")` de QC004)
- Extension de `tests/test_guards.py` (9 nouvelles classes de garde statique + 1 classe transversale)
- Extension documentaire de `docs/cas-non-supportes.md` (note RRQ2, Requirement 8.3)
- `payroll_engine/rrq.py`, `payroll_engine/rqap.py`, `payroll_engine/assurance_emploi.py` (implémentation, six fonctions au total)

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — `Decimal` de bout en bout, aucun `float` dans les modules ni dans leurs tests
- Règle 02 — retour `(Decimal, CalculationTrace)` avec `source` conforme à la liste blanche de `CalculationTrace` (TP-1015.F pour RRQ/RQAP, T4127 pour AE)
- Règle 03 — aucun nouveau garde-fou `UnsupportedPayrollCase` (délégation totale aux garde-fous de `PayrollInput`/`GainsDecomposes`) ; RRQ2 documentée comme hors périmètre sans code
- Règle 04 — corpus anonymisé QC001–QC006 déjà en place, aucune donnée personnelle réintroduite
- Règle 05 — tous les taux, exemptions et plafonds lus exclusivement depuis `parametres_annee.rrq`/`rqap`/`assurance_emploi`, jamais codés en dur
- Règle 06 — sections 1 à 5 (tests, garde, documentation) rédigées **avant** la section 6 (implémentation) ; les tests sont rouges à l'écriture, verts après implémentation

## Tasks

- [x] 1. Préparer les stratégies Hypothesis dédiées cotisations sociales
  - [x] 1.1 Étendre `tests/strategies.py` avec les stratégies cumuls YTD et paramètres canadiens
    - Ajouter `st_cumuls_ytd_non_nuls()` — génère un `CumulsYTD` où au moins une des six catégories (`rrq_employe`, `rrq_employeur`, `rqap_employe`, `rqap_employeur`, `ae_employe`, `ae_employeur`) est strictement positive, avec un biais explicite vers `[0, plafond]` et vers `plafond` exactement (via `st.one_of` incluant `st.just(plafond)`), afin d'exercer le plafonnement en cours de saison non couvert par le corpus golden (Introduction des requirements, design §Testing Strategy)
    - Ajouter `st_brut_total_avec_zero()` — `Decimal` dans `[Decimal("0.00"), Decimal("5000.00")]`, deux décimales, biaisé vers `Decimal("0.00")` via `st.one_of(st.just(Decimal("0.00")), st.decimals(...))` (Property 6)
    - Ajouter `st_parametres_annee_2026_qc_ca()` — retourne le `ParametresAnnee` réel 2026 chargé une seule fois via `load_parameters(2026, Juridiction.QUEBEC)`, mémorisé au niveau module (`functools.lru_cache(maxsize=1)`, cohérent avec `_charger_parametres_annee_2026_qc` déjà existant), réutilisable par les trois modules de test de cette spec
    - Ajouter `st_parametres_annee_avec_to_fill(champ)` — construit une variante de `ParametresAnnee` où un champ ciblé parmi ceux consommés par les Requirements 12.1 à 12.3 (`taux_cotisation_totale_employe`, `exemption_par_periode_aux_deux_semaines_2026`, `cotisation_max_annuelle_employe`, `taux_employe`/`taux_employeur` RQAP, `cotisation_max_employe`/`cotisation_max_employeur` RQAP, `taux_employe_quebec`, `multiplicateur_employeur`, `cotisation_max_employe`/`cotisation_max_employeur` AE) porte la sentinelle `"TO_FILL"`, utilisée par Property 17
    - Documenter chaque stratégie par un docstring citant le design §Testing Strategy « Stratégies Hypothesis » et la règle 01
    - _Requirements: 2.6, 4.4, 5.5, 6.4, 12.5_
    - _Design: §Testing Strategy « Stratégies Hypothesis »_

- [x] 2. Property-based tests et tests d'exemple de `rrq.py` (`tests/payroll_engine/test_rrq.py`)
  - [x] 2.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteRobustesse`)
    - Module docstring citant le design §Testing Strategy, la liste des propriétés couvertes par ce fichier, la limitation « corpus golden = paie n°1, cumul YTD nul » héritée de l'Introduction des requirements
    - Imports : `pytest`, `Decimal`, `hypothesis` (`given`, `settings`), les modèles consommés (`PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `Juridiction`, `ModeArrondissement`), les stratégies de `tests/strategies.py`
    - Fixture module-scoped pour `st_parametres_annee_2026_qc_ca()`
    - **Property 1 : Déterminisme** — deux appels à `calcul_rrq_employe` avec les mêmes arguments produisent deux tuples égaux au sens `==`
    - **Property 2 : Absence d'exception sur entrée valide** — aucun rejet pour tout `PayrollInput`/`GainsDecomposes`/`ParametresAnnee` valides, y compris cas extrêmes (salaire nul, cumul YTD nul ou proche du plafond via `st_cumuls_ytd_non_nuls`, salaire très élevé)
    - **Property 3 : Forme `Decimal` du résultat et de la trace** — le montant retourné et chaque valeur de `trace.parametres_utilises`/`entrees`/`sous_totaux`/`resultat` sont des `Decimal` finis, arrondis à 2 décimales `ROUND_HALF_UP`
    - Test d'exemple : import de `calcul_rrq_employe`, `calcul_rrq_employeur` sans effet de bord (aucune E/S, aucun appel réseau)
    - Annotation de chaque test : `# Feature: cotisations-sociales-qc, Property N: <titre>`
    - _Requirements: 1.4, 1.9, 1.10, 2.7, 3.4_
    - _Design: §Correctness Properties 1, 2, 3 ; §Components §1_

  - [x] 2.2 Tests de la formule de l'assiette cotisable et du plafonnement RRQ employé (classe `TestFormuleEtPlafonnementRrqEmploye`)
    - **Property 7 : Formule de l'assiette cotisable RRQ** — `montant_periode == arrondir(taux_cotisation_totale_employe × max(Decimal("0.00"), brut_total − exemption_par_periode))`
    - **Property 4 (variante RRQ employé) : Bornes générales** — `Decimal("0.00") <= cotisation <= montant_periode` et `cumul_ytd_rrq_employe + cotisation <= plafond_annuel_rrq_employe`
    - **Property 5 (variante RRQ employé) : Plancher à zéro quand cumul ≥ plafond** — utilise `st_cumuls_ytd_non_nuls()` biaisé vers le plafond exact
    - **Property 6 (variante RRQ employé) : Zéro sur salaire nul** — utilise `st_brut_total_avec_zero()`
    - Test d'exemple : `Salaire_Admissible ≤ Exemption_Par_Periode_RRQ` → cotisation `Decimal("0.00")` sans exception
    - Annotations `# Feature: cotisations-sociales-qc, Property N: <titre>` pour chacune des quatre propriétés
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 14.1, 14.2, 14.4_
    - _Design: §Correctness Properties 4, 5, 6, 7 ; §Components §2_

  - [x] 2.3 Tests d'égalité structurelle RRQ employeur = RRQ employé (classe `TestEgaliteRrqEmployeur`)
    - **Property 9 : Égalité structurelle** — `calcul_rrq_employeur(pi, g, p) == calcul_rrq_employe(pi, g, p)` (égalité stricte sur le montant, aucun plafond/cumul/taux distinct côté employeur)
    - Test d'exemple vérifiant explicitement qu'aucun champ `cotisation_max_annuelle_employeur` n'est supposé exister sur `RRQParametres` (absence d'`AttributeError` masqué, cohérence Req 3.2)
    - Annotation : `# Feature: cotisations-sociales-qc, Property 9: Égalité structurelle RRQ employeur = RRQ employé`
    - _Requirements: 3.1, 3.2, 3.4_
    - _Design: §Correctness Properties 9 ; §Components §3_

  - [x] 2.4 Tests de trace RRQ employé et employeur (classe `TestTraceRrq`)
    - **Property 13 (variante RRQ) : Conformité `source`/`annee`/`juridiction`/`section`** — `source` matche `^TP-1015\.F \d{4}, section 3\.2`, `juridiction == Juridiction.QUEBEC`, `section` distingue employé/employeur
    - **Property 14 (variante RRQ) : Contenu minimal de la trace** — `parametres_utilises` contient au moins `taux_cotisation_totale_employe` (ou `_employeur`) et une exemption ; `entrees` contient `salaire_periode`, `nb_periodes_annuelles`, `cumul_ytd` ; `sous_totaux` contient `exemption_periode`, `assiette_cotisable`
    - **Property 15 (variante RRQ) : Cohérence `resultat`/mode/précision** — `mode_arrondissement == ROUND_HALF_UP`, `precision_arrondissement == 2`, `resultat == cotisation_effective`
    - **Property 16 (variante RRQ) : Auto-suffisance** — `trace.sous_totaux["assiette_cotisable"] == max(Decimal("0.00"), trace.entrees["salaire_periode"] − trace.sous_totaux["exemption_periode"])` recalculable sans consulter `payroll_input`/`parametres_annee`
    - Annotations pour chacune des quatre propriétés
    - _Requirements: 11.1, 11.2, 11.3, 11.6, 11.7, 11.8_
    - _Design: §Correctness Properties 13, 14, 15, 16 ; §Components §2, §3_

  - [x] 2.5 Test de propagation de `MissingParameterError` pour RRQ (classe `TestMissingParameterRrq`)
    - **Property 17 (variante RRQ)** — pour un `ParametresAnnee` avec `taux_cotisation_totale_employe`, `exemption_par_periode_aux_deux_semaines_2026` ou `cotisation_max_annuelle_employe` marqué `"TO_FILL"` (via `st_parametres_annee_avec_to_fill`), l'appel à `calcul_rrq_employe` (ou `calcul_rrq_employeur` par délégation) lève `MissingParameterError` non interceptée
    - Annotation : `# Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RRQ)`
    - _Requirements: 1.9, 12.5_
    - _Design: §Correctness Properties 17 ; §Error Handling_

- [x] 3. Property-based tests et tests d'exemple de `rqap.py` (`tests/payroll_engine/test_rqap.py`)
  - [x] 3.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteRobustesse`)
    - Même structure que la tâche 2.1, appliquée à `calcul_rqap_employe` et `calcul_rqap_employeur`
    - **Property 1, 2, 3** (déterminisme, absence d'exception, forme `Decimal`) appliquées aux deux fonctions RQAP
    - Annotations correspondantes
    - _Requirements: 1.4, 1.9, 1.10, 4.5, 5.6_
    - _Design: §Correctness Properties 1, 2, 3 ; §Components §1_

  - [x] 3.2 Tests de la formule proportionnelle et du plafonnement RQAP employé (classe `TestFormuleEtPlafonnementRqapEmploye`)
    - **Property 8 (variante RQAP employé) : Formule proportionnelle sans exemption** — `montant_periode == arrondir(taux_employe × brut_total)`, aucune exemption soustraite (contrairement au RRQ)
    - **Property 4 (variante RQAP employé) : Bornes générales**
    - **Property 5 (variante RQAP employé) : Plancher à zéro quand cumul ≥ plafond**
    - **Property 6 (variante RQAP employé) : Zéro sur salaire nul**
    - Annotations pour chacune des quatre propriétés
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 14.1, 14.4_
    - _Design: §Correctness Properties 4, 5, 6, 8 ; §Components §4_

  - [x] 3.3 Tests d'indépendance et de plafonnement RQAP employeur, y compris l'anomalie QC004 (classe `TestIndependanceEtPlafonnementRqapEmployeur`)
    - **Property 10 : Indépendance de la cotisation RQAP employeur** — `montant_periode_rqap_employeur == arrondir(taux_employeur × brut_total)`, indépendamment de `calcul_rqap_employe(pi, g, p)[0]` (rejette explicitement `arrondir(Decimal("1.4") × cotisation_employe)` comme formule)
    - **Property 8 (variante RQAP employeur)**, **Property 4 (variante RQAP employeur)**, **Property 5 (variante RQAP employeur)** — mêmes gabarits que 3.2 appliqués à l'employeur
    - **Property 18 : Reproduction chiffrée de l'anomalie QC004** — pour `brut_total = Decimal("294.84")`, cumuls YTD nuls, paramètres 2026, `calcul_rqap_employeur` retourne exactement `Decimal("1.77")` (test d'exemple, pas un test Hypothesis — valeurs fixes du scénario QC004)
    - Annotations pour chacune des propriétés, en particulier `# Feature: cotisations-sociales-qc, Property 18: Reproduction chiffrée de la résolution de l'anomalie QC004`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 5.8, 13.3_
    - _Design: §Correctness Properties 4, 5, 8, 10, 18 ; §Components §5_

  - [x] 3.4 Tests de trace RQAP employé et employeur (classe `TestTraceRqap`)
    - **Property 13, 14, 15, 16 (variantes RQAP)** — mêmes gabarits que la tâche 2.4, adaptés au contenu de trace RQAP (`parametres_utilises` = taux effectif, `sous_totaux` = `cotisation_brute`)
    - Annotations pour chacune des quatre propriétés
    - _Requirements: 11.1, 11.2, 11.4, 11.6, 11.7, 11.8_
    - _Design: §Correctness Properties 13, 14, 15, 16 ; §Components §4, §5_

  - [x] 3.5 Test de propagation de `MissingParameterError` pour RQAP (classe `TestMissingParameterRqap`)
    - **Property 17 (variante RQAP)** — champs `taux_employe`, `taux_employeur`, `cotisation_max_employe`, `cotisation_max_employeur` de `parametres_annee.rqap`
    - Annotation : `# Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (RQAP)`
    - _Requirements: 1.9, 12.5_
    - _Design: §Correctness Properties 17 ; §Error Handling_

- [x] 4. Property-based tests et tests d'exemple de `assurance_emploi.py` (`tests/payroll_engine/test_assurance_emploi.py`)
  - [x] 4.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteRobustesse`)
    - Même structure que la tâche 2.1, appliquée à `calcul_ae_employe` et `calcul_ae_employeur`
    - **Property 1, 2, 3** appliquées aux deux fonctions AE
    - Annotations correspondantes
    - _Requirements: 1.4, 1.9, 1.10, 6.5, 7.4_
    - _Design: §Correctness Properties 1, 2, 3 ; §Components §1_

  - [x] 4.2 Tests de la formule proportionnelle et du plafonnement AE employé (classe `TestFormuleEtPlafonnementAeEmploye`)
    - **Property 8 (variante AE employé) : Formule proportionnelle sans exemption** — `montant_periode == arrondir(taux_employe_quebec × brut_total)`
    - **Property 4, 5, 6 (variantes AE employé)**
    - Annotations pour chacune des quatre propriétés
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6, 14.1, 14.4_
    - _Design: §Correctness Properties 4, 5, 6, 8 ; §Components §6_

  - [x] 4.3 Tests de dérivation et de plafonnement AE employeur (classe `TestDerivationEtPlafonnementAeEmployeur`)
    - **Property 11 : Dérivation depuis la cotisation AE employé plafonnée** — `montant_periode_ae_employeur == arrondir(multiplicateur_employeur × cotisation_ae_employe_effective)` où `cotisation_ae_employe_effective` est exactement `calcul_ae_employe(pi, g, p)[0]` (après plafonnement employé) — rejette explicitement `arrondir(taux_employe_quebec × multiplicateur_employeur × brut_total)` comme formule
    - **Property 4 (variante AE employeur) : Bornes** — `cumul_ytd_ae_employeur + cotisation <= plafond_annuel_ae_employeur` (défense en profondeur, Requirement 7 AC3)
    - Test d'exemple : cas où `cotisation_ae_employe_effective` est déjà plafonnée (cumul employé proche du plafond) — vérifie que l'employeur se dérive bien du montant *post-plafonnement*, pas du brut
    - Annotations pour chacune des propriétés
    - _Requirements: 7.1, 7.2, 7.3, 7.5_
    - _Design: §Correctness Properties 4, 11 ; §Components §7_

  - [x] 4.4 Tests de trace AE employé et employeur (classe `TestTraceAe`)
    - **Property 13, 14, 15, 16 (variantes AE)** — `juridiction == Juridiction.CANADA`, `source` matche `^T4127 \d{4}, section 4`, `parametres_utilises` employeur contient `multiplicateur_employeur`, `entrees` employeur contient `ae_employe`, `sous_totaux` employeur contient le produit avant arrondissement final
    - Annotations pour chacune des quatre propriétés
    - _Requirements: 11.1, 11.2, 11.5, 11.6, 11.7, 11.8_
    - _Design: §Correctness Properties 13, 14, 15, 16 ; §Components §6, §7_

  - [x] 4.5 Test de propagation de `MissingParameterError` pour AE (classe `TestMissingParameterAe`)
    - **Property 17 (variante AE)** — champs `taux_employe_quebec`, `multiplicateur_employeur`, `cotisation_max_employe`, `cotisation_max_employeur` de `parametres_annee.assurance_emploi`
    - Annotation : `# Feature: cotisations-sociales-qc, Property 17: Propagation de MissingParameterError (AE)`
    - _Requirements: 1.9, 12.5_
    - _Design: §Correctness Properties 17 ; §Error Handling_

- [x] 5. Checkpoint — tests rouges complets avant implémentation
  - Vérifier que `pytest tests/payroll_engine/test_rrq.py tests/payroll_engine/test_rqap.py tests/payroll_engine/test_assurance_emploi.py` échoue avec `ModuleNotFoundError` sur les trois imports (`payroll_engine.rrq`, `payroll_engine.rqap`, `payroll_engine.assurance_emploi`), confirmant que tous les tests sont écrits avant tout code
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Golden test de reproduction du corpus QC001–QC006
  - [x] 6.1 Étendre `tests/test_golden_outputs.py` avec `test_cotisations_sociales_reproduisent_fixture`
    - Nouveau test paramétré `@pytest.mark.golden @pytest.mark.parametrize("scenario_id", ["QC001", ..., "QC006"])`, suivant le patron de `test_calcul_gains_reproduit_fixture` (import local des six fonctions pour ne pas faire échouer la collecte tant que le module n'existe pas)
    - Chargement `PayrollInput` (fixture d'entrée), `GainsDecomposes` (reconstruit depuis la section `gains` de la fixture de sortie), `ParametresAnnee` réel 2026
    - Appel des six fonctions ; assertions d'égalité stricte sur `retenues_employe.{rrq,rqap,ae}.montant` et `cotisations_employeur.{rrq_employeur,rqap_employeur,ae_employeur}.montant`
    - Assertion `trace.resultat == montant` pour au moins `rrq_employe` (cohérence trace/montant, Req 13.5)
    - Assertion dédiée QC004 : `rqap_employeur == Decimal("1.77")` (Req 5.8, 13.3, Property 18)
    - Assertion dédiée QC001 : `rrq_employe == Decimal("87.36")` (Req 13.6, valeur corrigée 27 périodes)
    - Docstring citant la limitation « corpus golden = paie n°1, cumul YTD nul » (Introduction des requirements, design §Testing Strategy)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_
    - _Design: §Testing Strategy « Détail des golden tests », « Limitation héritée du corpus golden »_

- [x] 7. Tests de garde statique des trois nouveaux modules (`tests/test_guards.py`)
  - [x] 7.1 Ajouter les classes `TestRrqNoFloat`, `TestRqapNoFloat`, `TestAssuranceEmploiNoFloat`
    - Parser chacun des trois modules avec `ast.parse` (motif identique à `TestGainsBrutsNoFloat`)
    - Vérifier l'absence de `ast.Constant(value=float(...))`, l'absence d'appel `Decimal(<non-str>)`, l'absence d'appel `round`/`math.floor`/`math.ceil`/`math.trunc`
    - Vérifier que chaque signature publique retourne `tuple[Decimal, CalculationTrace]` sans paramètre par défaut
    - _Requirements: 2.7, 3.4, 4.5, 5.6, 6.5, 7.4_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 7.2 Ajouter les classes `TestRrqNoHardcodedFiscalValues`, `TestRqapNoHardcodedFiscalValues`, `TestAssuranceEmploiNoHardcodedFiscalValues`
    - Lecture ligne par ligne de chaque module ; vérifier l'absence de toute constante `Decimal` autre que `Decimal("0.00")` (plancher/valeur neutre) et l'entier `2` (précision d'arrondissement) — cohérent avec `TestGainsBrutsNoHardcodedFiscalValues`
    - Étendre les motifs interdits partagés (`_MOTIFS_FISCAUX_INTERDITS`) si nécessaire pour couvrir les taux RRQ/RQAP/AE 2026 (`0.063`, `0.0043`, `0.00602`, `0.0130`, `1.4`, `129.63`, `4479.30`, etc.) déjà en partie couverts par la liste existante
    - _Requirements: 12.4_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 7.3 Ajouter les classes `TestRrqNoLoadParametersCall`, `TestRqapNoLoadParametersCall`, `TestAssuranceEmploiNoLoadParametersCall`
    - Grep du fichier source pour vérifier l'absence du token `load_parameters` (ni import, ni appel), l'absence d'ouverture de fichier (`open(`, `json.load`, `Path(...).read_text()`), l'absence de `datetime.now()`, `random.*`, `os.environ`, l'absence de variable de module mutable
    - _Requirements: 1.5_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 7.4 Ajouter la classe transversale `TestCotisationsSocialesNoUnsupportedPayrollCase`
    - Grep des trois modules (`rrq.py`, `rqap.py`, `assurance_emploi.py`) pour vérifier l'absence du token `UnsupportedPayrollCase` — aucun nouveau garde-fou introduit par cette spec (Requirement 9.3)
    - _Requirements: 8.1, 8.2, 9.3_
    - _Design: §Error Handling « Aucun nouveau garde-fou »_

- [x] 8. Documentation de la RRQ2 hors périmètre (Requirement 8)
  - [x] 8.1 Étendre `docs/cas-non-supportes.md`
    - Ajouter une note documentaire expliquant que la RRQ2 (deuxième cotisation supplémentaire au RRQ, taux 4 % entre le MGA et le MSGA) est hors périmètre de cette spec et en pratique jamais atteinte par le Camp LilySO : `Plafond_Annuel_RRQ_Employe` (`4 479,30 $`) correspond exactement au seuil où l'Assiette_Cotisable_RRQ atteint le MGA (`71 100 $`), donc la cotisation RRQ employé cesse naturellement de croître à ce seuil sans garde-fou supplémentaire
    - Préciser qu'aucun code de cette spec ne lit `taux_deuxieme_cotisation_supplementaire_employe`/`_employeur` de `RRQParametres`
    - Revue manuelle uniquement — aucun test automatisé associé à cette sous-tâche
    - _Requirements: 8.3, 8.4_
    - _Design: §Error Handling « RRQ2 — hors périmètre »_

- [x] 9. Implémentation de `payroll_engine/rrq.py`
  - [x] 9.1 Créer le module avec `_arrondir`, `calcul_rrq_employe` et `calcul_rrq_employeur`
    - Docstring citant Req 1, 2, 3, règles 01, 02, 05, et pointant vers la spec `cotisations-sociales-qc`
    - Constante privée `_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")` et helper `_arrondir` (patron identique à `gains_bruts.py`)
    - `calcul_rrq_employe` : lecture `salaire_admissible = gains.brut_total`, `exemption_periode = parametres_annee.rrq.exemption_par_periode_aux_deux_semaines_2026`, `assiette_cotisable = max(Decimal("0.00"), salaire_admissible - exemption_periode)`, `montant_periode = _arrondir(parametres_annee.rrq.taux_cotisation_totale_employe * assiette_cotisable)`, `marge_disponible = max(Decimal("0.00"), parametres_annee.rrq.cotisation_max_annuelle_employe - payroll_input.cumuls_debut.rrq_employe)`, `cotisation_effective = min(montant_periode, marge_disponible)`
    - Construction de la `CalculationTrace` avec les 9 champs exacts spécifiés par le design §Components §2 (`source`, `annee`, `juridiction=Juridiction.QUEBEC`, `section="3.2 — RRQ"`, `parametres_utilises`, `entrees` avec `nb_periodes_annuelles` converti via `Decimal(str(...))`, `sous_totaux`, `mode_arrondissement`, `precision_arrondissement=2`, `resultat`)
    - `calcul_rrq_employeur` : délégation stricte par appel interne à `calcul_rrq_employe(payroll_input, gains, parametres_annee)`, trace reformulée avec `section="3.2 — RRQ employeur"` et `parametres_utilises` sur `taux_cotisation_totale_employeur`
    - Retour `(cotisation_effective, trace)` — tuple à deux éléments
    - À ce stade, tous les tests de la tâche 2 doivent passer
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 10.1, 10.3, 10.4, 11.1, 11.2, 11.3, 11.6, 11.7, 11.8, 12.1, 12.4, 12.5_
    - _Design: §Components §1, §2, §3, §8_

- [x] 10. Implémentation de `payroll_engine/rqap.py`
  - [x] 10.1 Créer le module avec `_arrondir`, `calcul_rqap_employe` et `calcul_rqap_employeur`
    - Docstring citant Req 4, 5, règles 01, 02, 05
    - `calcul_rqap_employe` : `montant_periode = _arrondir(parametres_annee.rqap.taux_employe * gains.brut_total)` (aucune exemption soustraite), `marge_disponible = max(Decimal("0.00"), parametres_annee.rqap.cotisation_max_employe - payroll_input.cumuls_debut.rqap_employe)`, `cotisation_effective = min(montant_periode, marge_disponible)`
    - `calcul_rqap_employeur` : **calcul indépendant** — `montant_periode = _arrondir(parametres_annee.rqap.taux_employeur * gains.brut_total)`, jamais dérivé de `calcul_rqap_employe(...)[0]` ; `marge_disponible` sur `cotisation_max_employeur` et `cumuls_debut.rqap_employeur`
    - Construction des deux `CalculationTrace` (`section="3.3 — RQAP employé"` / `"3.3 — RQAP employeur"`, `parametres_utilises` = taux effectif, `sous_totaux={"cotisation_brute": montant_periode}`)
    - Commentaire de code citant explicitement le point de vigilance de l'anomalie QC004 (§Components §5 du design) : `montant_periode` se calcule à partir de `gains.brut_total`, jamais à partir du montant employé déjà arrondi
    - À ce stade, tous les tests de la tâche 3 doivent passer, y compris `rqap_employeur == Decimal("1.77")` pour QC004
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 10.1, 10.3, 10.4, 11.1, 11.2, 11.4, 11.6, 11.7, 11.8, 12.2, 12.4, 12.5_
    - _Design: §Components §1, §4, §5, §8_

- [x] 11. Implémentation de `payroll_engine/assurance_emploi.py`
  - [x] 11.1 Créer le module avec `_arrondir`, `calcul_ae_employe` et `calcul_ae_employeur`
    - Docstring citant Req 6, 7, règles 01, 02, 05
    - `calcul_ae_employe` : `montant_periode = _arrondir(parametres_annee.assurance_emploi.taux_employe_quebec * gains.brut_total)`, `marge_disponible` sur `cotisation_max_employe` et `cumuls_debut.ae_employe`, `cotisation_effective = min(montant_periode, marge_disponible)`
    - `calcul_ae_employeur` : **dérivation** — appel interne `cotisation_ae_employe_effective, _ = calcul_ae_employe(payroll_input, gains, parametres_annee)`, `montant_periode = _arrondir(parametres_annee.assurance_emploi.multiplicateur_employeur * cotisation_ae_employe_effective)`, `marge_disponible` sur `cotisation_max_employeur` et `cumuls_debut.ae_employeur`, `cotisation_effective = min(montant_periode, marge_disponible)`
    - Construction des deux `CalculationTrace` (`juridiction=Juridiction.CANADA`, `source` T4127, `section="4 — AE employé (taux Québec)"` / `"4 — AE employeur (multiplicateur 1.4)"`) — pour l'employeur, `sous_totaux["cotisation_employeur"]` porte le produit **avant** arrondissement final (reproduisant la fixture `"27.594"` avant `resultat="27.59"`)
    - Commentaire de code citant le contraste explicite avec `calcul_rqap_employeur` (dérivation vs indépendance)
    - À ce stade, tous les tests de la tâche 4 doivent passer
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 10.1, 10.2, 10.3, 10.4, 11.1, 11.2, 11.5, 11.6, 11.7, 11.8, 12.3, 12.4, 12.5_
    - _Design: §Components §1, §6, §7, §8_

- [x] 12. Checkpoint final — exécution complète et vérification des compteurs
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (property + golden + garde + exemple) — tous doivent passer
  - Vérifier que `pytest tests/payroll_engine/test_rrq.py tests/payroll_engine/test_rqap.py tests/payroll_engine/test_assurance_emploi.py -m property` exécute au moins 15 tests distincts couvrant les 18 propriétés du design (avec variantes par cotisation)
  - Vérifier que `pytest tests/test_golden_outputs.py::test_cotisations_sociales_reproduisent_fixture` exécute exactement 6 tests (un par scénario QC001–QC006) et tous passent au cent près, y compris `rqap_employeur == Decimal("1.77")` sur QC004
  - Vérifier que les neuf classes de garde par module (`TestRrqNoFloat`, `TestRqapNoFloat`, `TestAssuranceEmploiNoFloat`, `TestRrqNoHardcodedFiscalValues`, `TestRqapNoHardcodedFiscalValues`, `TestAssuranceEmploiNoHardcodedFiscalValues`, `TestRrqNoLoadParametersCall`, `TestRqapNoLoadParametersCall`, `TestAssuranceEmploiNoLoadParametersCall`) et la classe transversale `TestCotisationsSocialesNoUnsupportedPayrollCase` passent
  - Vérifier par grep que `payroll_engine/rrq.py`, `rqap.py`, `assurance_emploi.py` ne contiennent aucun `float`, aucune valeur fiscale codée en dur hors `Decimal("0.00")`/`2`, ni `load_parameters`, `open(`, `datetime.now`, `random.`, `UnsupportedPayrollCase`
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, golden tests et tests de garde soient rédigés **avant** l'implémentation et ne peuvent pas être considérés comme facultatifs — discipline TDD stricte alignée avec `moteur-paie-contrats` et `gains-bruts-vacances-hs`.
- **Ordre spec → tests → implémentation → validation** respecté au niveau du plan : sections 1 à 8 (préparation, property tests, golden test, tests de garde, documentation RRQ2) précèdent les sections 9 à 11 (implémentation). À l'issue de la section 8, **tous** les tests sont écrits et rouges (checkpoint explicite en section 5). Les sections 9 à 11 font basculer l'ensemble au vert module par module.
- **Chaque property test est annoté** par `# Feature: cotisations-sociales-qc, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/payroll_engine/test_rrq.py tests/payroll_engine/test_rqap.py tests/payroll_engine/test_assurance_emploi.py` retrouve les 18 propriétés du design (certaines déclinées en plusieurs variantes par cotisation).
- **Groupement des 18 propriétés en sous-tâches transversales** : signature/pureté/robustesse (P1+P2+P3, dupliqué par module car appliqué à des fonctions différentes), formules et plafonnement par cotisation (P4+P5+P6+P7/P8, une sous-tâche par paire employé/employeur), mécanismes de parenté spécifiques (P9 égalité RRQ, P10 indépendance RQAP, P11 dérivation AE), trace (P13+P14+P15+P16, dupliqué par module), erreurs de paramètres (P17, dupliqué par module), anomalie QC004 (P18, test d'exemple dédié).
- **RQAP employeur vs AE employeur — distinction testée explicitement** : la tâche 3.3 teste l'indépendance du calcul RQAP employeur (jamais dérivé du montant employé) tandis que la tâche 4.3 teste la dérivation du calcul AE employeur (toujours dérivé du montant employé post-plafonnement) — ces deux mécanismes opposés sont le cœur de la résolution de l'anomalie QC004 et sont chacun couverts par un test qui échouerait si l'implémentation appliquait le mécanisme de l'autre cotisation par erreur.
- **RRQ2 non implémentée** : la tâche 8 documente uniquement pourquoi aucun garde-fou supplémentaire n'est nécessaire pour ce cas dans le périmètre Camp LilySO (Requirement 8) — aucune fonction ni test de cette spec ne calcule ou n'expose un montant RRQ2.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "4.2"] },
    { "id": 3, "tasks": ["2.4", "2.5", "3.3", "4.3"] },
    { "id": 4, "tasks": ["3.4", "3.5", "4.4", "4.5"] },
    { "id": 5, "tasks": ["6.1", "7.1", "7.2", "7.3", "7.4", "8.1"] },
    { "id": 6, "tasks": ["9.1"] },
    { "id": 7, "tasks": ["10.1"] },
    { "id": 8, "tasks": ["11.1"] }
  ]
}
```
