# Implementation Plan: net-cumuls-registre

<!-- Plan d'implémentation — spec « net, cumuls YTD et registre maître » du
     moteur de paie Camp LilySO. Les en-têtes structurels (Overview, Tasks,
     Notes, Task Dependency Graph) sont maintenus en anglais pour conformité au
     format Kiro. Le contenu métier est en français. -->

## Overview

Cette spec livre **l'étape 6 du plan d'implémentation** (`docs/plan-implementation.md`), après `moteur-paie-contrats` (étape 1), `gains-bruts-vacances-hs` (étape 2), `cotisations-sociales-qc` (étape 3), `impots-retenues-source` (étape 4) et `charges-patronales` (étape 5) : deux fichiers distincts —

- **`payroll_engine/net_pay.py`** — une fonction pure unique `assembler_paie` qui invoque, dans l'ordre, les neuf fonctions de calcul déjà livrées par les étapes 2 à 5, résout la dépendance circulaire de `cumuls_fin` via l'objet privé `_ContributionPaie`, puis construit le `PayrollResult` complet en un seul appel ;
- **`payroll_engine/register.py`** — le registre maître SQLite, append-only, avec cumuls YTD dénormalisés (table `cumuls_ytd`) et annulation-remplacement atomique (`remplacer_paie`).

**Aucun contrat n'est redéfini et aucune formule fiscale n'est implémentée** : `net_pay.py` invoque exclusivement `calcul_gains`, `calcul_rrq_employe`, `calcul_rqap_employe`, `calcul_ae_employe`, `calcul_impot_qc_formule`/`calcul_impot_qc_retenu`, `calcul_impot_federal_formule`/`calcul_impot_federal_retenu` et `assembler_cotisations_employeur` ; `register.py` réutilise `PayrollResult.model_dump_json()`/`model_validate_json()` sans nouveau schéma de sérialisation et `CumulsYTD.avec_paie`/`CumulsYTD.zero` sans modification. Aucune nouvelle dépendance externe (`os`/`pathlib`/`sqlite3`/`contextlib` de la bibliothèque standard uniquement, décision design n° 5).

**Livrables** :

- Extension de `tests/strategies.py` (séquences de `PayrollResult`, statuts de remplacement, `saison`, `chemin_bd` temporaire)
- `tests/payroll_engine/test_net_pay.py` (Properties 1 à 7 + tests d'exemple)
- `tests/payroll_engine/test_register.py` (Properties 8 à 14 + tests d'exemple)
- Extension de `tests/test_golden_outputs.py` (assemblage + insertion des 6 scénarios QC001–QC006)
- Extension de `tests/test_guards.py` (sept nouvelles classes de garde statique)
- `payroll_engine/net_pay.py` (`_ContributionPaie`, `assembler_paie`)
- `payroll_engine/register.py` (schéma SQL, `chemin_bd_production`, `_connexion`, cinq fonctions publiques)

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — `Decimal` de bout en bout ; `payload_json` et `cumuls_ytd.*` exclusivement en `TEXT`, jamais `REAL`/`float`
- Règle 02 — `net_pay.py` n'invente aucune nouvelle `CalculationTrace` ; chaque `MontantAvecTrace` reçu est reporté sans altération
- Règle 03 — aucun nouveau garde-fou de périmètre ; `MissingParameterError`/`UnsupportedPayrollCase` propagées sans interception
- Règle 04 — `chemin_bd` de production hors dépôt ; tests exclusivement sur base temporaire ou `:memory:` ; identifiants fictifs `EMP0XX` ; garde « aucun `*.db` dans l'arbre versionné »
- Règle 05 — aucun taux/plafond/constante fiscale codé en dur ; `parametres_annee` injecté tel quel, jamais relu depuis le disque par `net_pay.py`
- Règle 06 — sections 1 à 5 (stratégies, property tests des deux modules, golden, garde) rédigées et vérifiées **rouges avant** le checkpoint de la section 6, qui précède l'implémentation des sections 7 et 8 ; validation finale en section 9

## Tasks

- [x] 1. Préparer les stratégies Hypothesis dédiées au registre
  - [x] 1.1 Étendre `tests/strategies.py` avec les séquences de `PayrollResult`, statuts, saison et chemins temporaires
    - Ajouter `st_sequence_payroll_results_meme_employe_annee(n_max=5)` — génère une séquence de 0 à `n_max` `PayrollResult` `EMISE` valides, tous rattachés au même `employe_id`/`annee_fiscale`, `id_paie` distincts (pour Property 8)
    - Ajouter `st_statut_nouveau_resultat_autorise()` — `st.sampled_from([StatutDePaie.EMISE, StatutDePaie.BROUILLON])` (pour Property 9)
    - Ajouter `st_statut_nouveau_resultat_refuse()` — `st.sampled_from([StatutDePaie.ANNULEE, StatutDePaie.REMPLACE_PAR])` (pour le test d'exemple de refus, Req 13.3)
    - Ajouter `st_saison()` — `st.text(min_size=0, max_size=30)` (pour Property 13)
    - Ajouter la fixture `st_chemin_bd_temporaire(tmp_path)` — fournit `tmp_path / f"test_{uuid4().hex}.db"` à chaque exemple généré, garantissant une base neuve par exemple Hypothesis (Properties 8/9/10/14)
    - Documenter `st_payroll_input_qc001_a_qc006_ou_genere()` comme réutilisation pure des stratégies existantes (aucune nouvelle génération de `PayrollInput`)
    - Chaque nouvelle stratégie documentée par un docstring citant le design §Testing Strategy « Stratégies Hypothesis » et la règle 01
    - _Requirements: 16.3 (P8), 13.3/16.4 (P9), 14.1/14.2 (P13), 15.2_
    - _Design: §Testing Strategy « Stratégies Hypothesis »_

- [x] 2. Property tests et tests d'exemple de `net_pay.py` (`tests/payroll_engine/test_net_pay.py`)
  - [x] 2.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteDeterminisme`)
    - Module docstring citant le design §Testing Strategy, les 7 propriétés couvertes, et le rappel que ce fichier est écrit **avant** `payroll_engine/net_pay.py` (règle 06)
    - Imports : `pytest`, `hypothesis` (`given`, `settings`), les modèles consommés (`PayrollInput`, `PayrollResult`, `GainsDecomposes`, `CumulsYTD`, `StatutDePaie`, `PayrollDomainError`, `MissingParameterError`), les stratégies existantes (`st_payroll_input_et_gains()` ou équivalent) ; import local de `assembler_paie` pour ne pas faire échouer la collecte tant que le module n'existe pas
    - Test d'exemple : signature exacte de `assembler_paie` via `inspect.signature` (ordre des huit paramètres, valeurs par défaut de `date_emission`/`remplace_par_id`) (Req 1.1)
    - Test d'exemple : import de `net_pay` sans effet de bord (aucune E/S, aucun appel réseau au moment de l'import) (Req 1.5)
    - **Property 1 : Déterminisme et non-mutation** — deux appels successifs avec les mêmes arguments produisent deux `PayrollResult` égaux au sens `==` ; `payroll_input`/`parametres_annee` restent `==` à eux-mêmes avant/après l'appel
    - Annotation : `# Feature: net-cumuls-registre, Property 1: Déterminisme et non-mutation`
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 16.7_
    - _Design: §Correctness Properties 1 ; §Components §1_

  - [x] 2.2 Tests des identités comptables (classe `TestIdentitesComptables`)
    - **Property 2 : Identité brute** — `gains.brut_total == net + retenues_employe.total_retenues_employe`
    - **Property 3 : Identité coût employeur** — `cout_employeur == gains.brut_total + cotisations_employeur.total_cotisations_employeur`
    - Vérifier l'absence d'arrondissement supplémentaire (les deux opérandes sont déjà arrondis au cent par les fonctions invoquées) et l'absence de tout `float` intermédiaire
    - Annotations pour chacune des deux propriétés
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 16.1, 16.2_
    - _Design: §Correctness Properties 2, 3 ; §Components §1 étapes E, F_

  - [x] 2.3 Test d'invocation stricte sans recalcul (classe `TestInvocationStricte`)
    - **Property 4 : Invocation stricte sans recalcul** — `pr.gains == calcul_gains(pi, pa)`, `pr.retenues_employe.rrq.montant == calcul_rrq_employe(pi, gains, pa)[0]` (et symétriquement pour `rqap`/`ae`/`impot_qc_formule`/`impot_qc_retenu`/`impot_federal_formule`/`impot_federal_retenu`), et `pr.cotisations_employeur == assembler_cotisations_employeur(pi, gains, pa)`
    - Vérifier qu'aucune des neuf fonctions n'est appelée deux fois avec des arguments différents (chaque section provient d'un appel direct et inchangé)
    - Annotation : `# Feature: net-cumuls-registre, Property 4: Invocation stricte sans recalcul`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 4.1, 4.2_
    - _Design: §Correctness Properties 4 ; §Components §1 (pseudocode d'ordonnancement)_

  - [x] 2.4 Tests de `cumuls_fin` (classe `TestCumulsFin`)
    - **Property 5 : Cohérence et monotonie de `cumuls_fin`** — pour tout `PayrollInput` valide tel que `cumuls_debut.annee_civile == pay_period.annee_fiscale`, `cumuls_fin.<categorie> == cumuls_debut.<categorie> + contribution.<categorie>` pour chacune des onze catégories (mapping exact du Requirement 6 AC2), et `cumuls_fin.<categorie> >= cumuls_debut.<categorie>`
    - Test d'exemple : `payroll_input.cumuls_debut.annee_civile != pay_period.annee_fiscale` → `PayrollDomainError` levée par `CumulsYTD.avec_paie`, propagée sans interception (Req 6.4)
    - Annotation : `# Feature: net-cumuls-registre, Property 5: Cohérence et monotonie de cumuls_fin`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
    - _Design: §Correctness Properties 5 ; §Components §2 (`_ContributionPaie`)_

  - [x] 2.5 Test de construction finale fidèle (classe `TestConstructionFinale`)
    - **Property 6 : Construction finale fidèle et sans erreur** — pour des arguments de cycle de vie mutuellement cohérents, `assembler_paie` retourne un `PayrollResult` sans lever `ValidationError`, et `id_paie`, `version`, `statut`, `date_creation`, `date_emission`, `remplace_par_id` du résultat sont strictement identiques aux arguments fournis
    - Vérifier que la construction utilise le constructeur Pydantic standard (jamais `model_construct`) — test d'exemple ou inspection statique légère (Req 7.4)
    - Annotation : `# Feature: net-cumuls-registre, Property 6: Construction finale fidèle et sans erreur`
    - _Requirements: 7.2, 7.3, 7.4_
    - _Design: §Correctness Properties 6 ; §Components §1 étape H_

  - [x] 2.6 Test de propagation sans interception des exceptions (classe `TestPropagationExceptions`)
    - **Property 7 : Propagation sans interception** — pour un `ParametresAnnee` où un champ consommé par une des neuf fonctions invoquées porte `"TO_FILL"` ou une section requise est `None`, `assembler_paie` lève exactement la `MissingParameterError`/`UnsupportedPayrollCase` d'origine, jamais interceptée, masquée ni reconvertie
    - Vérifier l'absence de tout `try/except` autour des appels aux neuf fonctions (inspection `ast` légère ou test de comportement)
    - Annotation : `# Feature: net-cumuls-registre, Property 7: Propagation sans interception`
    - _Requirements: 2.6, 6.4, 17.3_
    - _Design: §Correctness Properties 7 ; §Error Handling_

- [x] 3. Property tests et tests d'exemple de `register.py` (`tests/payroll_engine/test_register.py`)
  - [x] 3.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignatureEtChemin`)
    - Module docstring citant le design §Testing Strategy, les 7 propriétés couvertes (8 à 14), et le rappel écrit avant `payroll_engine/register.py` (règle 06)
    - Imports : `pytest`, `hypothesis`, `sqlite3`, les modèles consommés (`PayrollResult`, `CumulsYTD`, `StatutDePaie`), les stratégies de la tâche 1.1 ; import local des cinq fonctions du registre pour ne pas faire échouer la collecte
    - Test d'exemple : signature exacte de `inserer_paie`, `lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie` via `inspect.signature` (Req 11.1, 12.1, 12.3, 12.4, 13.1)
    - Test d'exemple : `chemin_bd_production()` retourne un chemin sous `CampLilySO/payroll.db`, jamais sous la racine du dépôt, avec `monkeypatch.setenv("APPDATA", str(tmp_path))` (Req 15.1)
    - Test d'exemple : chaque fonction publique accepte `":memory:"` comme `chemin_bd` sans erreur (Req 15.2)
    - _Requirements: 11.1, 12.1, 12.3, 12.4, 13.1, 15.1, 15.2_
    - _Design: §Components §3.0, §3.1 ; §Testing Strategy « Tests d'exemple ciblés »_

  - [x] 3.2 Test du cumul YTD de *n* paies (classe `TestCumulYTDDeNPaies`)
    - **Property 8 : Cumul YTD de *n* paies = somme des contributions** — pour une séquence ordonnée de *n* ≥ 0 `PayrollResult` `EMISE` d'un même employé/année, insérés un à un via `inserer_paie` (base neuve), `lire_cumuls_ytd` après les *n* insertions égale, catégorie par catégorie, la somme des contributions ; le cas *n* = 0 retourne `CumulsYTD.zero(employe_id, annee_civile)`
    - Utiliser `st_sequence_payroll_results_meme_employe_annee` et `st_chemin_bd_temporaire` (tâche 1.1)
    - Annotation : `# Feature: net-cumuls-registre, Property 8: Cumul YTD de n paies`
    - _Requirements: 10.4, 11.3, 16.3_
    - _Design: §Correctness Properties 8 ; §Components §3.3_

  - [x] 3.3 Tests d'idempotence de `remplacer_paie` (classe `TestRemplacerPaie`)
    - **Property 9 : Idempotence de substitution** — le `CumulsYTD` obtenu après `inserer_paie(ancien)` puis `remplacer_paie(ancien.id_paie, nouveau, ...)` est identique au `CumulsYTD` obtenu en insérant directement `nouveau` seul depuis une base neuve
    - Test d'exemple : `ancien_id` absent → `KeyError` citant l'identifiant recherché (Req 13.2)
    - Test d'exemple : `ancien_id` présent mais `statut != EMISE` → `ValueError`, aucune mutation de `paies`/`cumuls_ytd` (Req 13.2)
    - Test d'exemple : `nouveau_resultat.statut` hors `{EMISE, BROUILLON}` (via `st_statut_nouveau_resultat_refuse`) → `ValueError`, aucune mutation (Req 13.3)
    - Test d'exemple : ancien `EMISE` remplacé par un nouveau `BROUILLON` → l'étape 4c retire uniquement la contribution ancienne, sans ajout (Req 13.5)
    - Annotation : `# Feature: net-cumuls-registre, Property 9: Idempotence de substitution`
    - _Requirements: 13.2, 13.3, 13.4, 13.5, 16.4_
    - _Design: §Correctness Properties 9 ; §Components §3.7 ; §Error Handling_

  - [x] 3.4 Test de round-trip de sérialisation (classe `TestRoundTrip`)
    - **Property 10 : Round-trip sans perte** — `lire_paie(id_paie, chemin_bd)` après `inserer_paie(resultat, saison, chemin_bd)` retourne un `PayrollResult` strictement égal (`==`) à `resultat`
    - Test d'exemple : `lire_paie` sur `id_paie` absent lève `KeyError` citant l'identifiant recherché (Req 12.2)
    - Annotation : `# Feature: net-cumuls-registre, Property 10: Round-trip de sérialisation`
    - _Requirements: 12.1, 12.2, 12.5, 16.5_
    - _Design: §Correctness Properties 10 ; §Components §3.4_

  - [x] 3.5 Test d'immutabilité des lignes déjà insérées (classe `TestImmutabiliteLignes`)
    - **Property 11 : Immutabilité** — aucune fonction autre que `remplacer_paie` ne modifie `payload_json`/`statut`/`remplace_par_id` d'une ligne déjà insérée ; `remplacer_paie` ne modifie de la ligne `ancien_id` que `statut` et `remplace_par_id` — tous les champs monétaires substantiels du `payload_json` (gains, retenues, cotisations, net, coût employeur) restent identiques
    - Annotation : `# Feature: net-cumuls-registre, Property 11: Immutabilité des lignes déjà insérées`
    - _Requirements: 9.3, 13.7, 16.6_
    - _Design: §Correctness Properties 11 ; §Components §3.7 ; §Data Models_

  - [x] 3.6 Test d'absence de `float` (classe `TestAbsenceFloat`)
    - **Property 12 : Absence de `float`** — pour `inserer_paie`, `lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie`, aucune valeur monétaire assemblée, sérialisée (`payload_json`, colonnes `cumuls_ytd`) ou relue n'est de type `float`
    - Introspection directe des lignes SQLite (`sqlite3.connect(...).execute("SELECT ...")`) pour vérifier le type Python de chaque colonne monétaire lue
    - Annotation : `# Feature: net-cumuls-registre, Property 12: Absence de float`
    - _Requirements: 9.2, 10.2, 10.3, 16.8_
    - _Design: §Correctness Properties 12 ; §Data Models_

  - [x] 3.7 Test d'invariance par rapport à `saison` (classe `TestInvarianceSaison`)
    - **Property 13 : Invariance de `cumuls_ytd` par rapport à `saison`** — deux exécutions identiques de `inserer_paie` différant uniquement par `saison` produisent le même `CumulsYTD` ; `remplacer_paie` accepte sans erreur des `saison` différentes entre ancienne et nouvelle version
    - Utiliser `st_saison()` (tâche 1.1)
    - Annotation : `# Feature: net-cumuls-registre, Property 13: Invariance par rapport à saison`
    - _Requirements: 14.1, 14.2, 14.4_
    - _Design: §Correctness Properties 13_

  - [x] 3.8 Test de refus d'insertion dupliquée (classe `TestRefusInsertionDupliquee`)
    - **Property 14 : Refus d'insertion dupliquée sans corruption** — une seconde tentative `inserer_paie` avec le même `id_paie` lève une exception explicite, et l'état de `paies`/`cumuls_ytd` après la tentative refusée reste identique à l'état juste avant
    - Annotation : `# Feature: net-cumuls-registre, Property 14: Refus d'insertion dupliquée`
    - _Requirements: 11.6_
    - _Design: §Correctness Properties 14 ; §Error Handling_

- [x] 4. Golden test bout en bout (`tests/test_golden_outputs.py`)
  - [x] 4.1 Ajouter `test_assemblage_et_registre_reproduisent_fixture`
    - Nouveau test paramétré `@pytest.mark.golden @pytest.mark.parametrize("scenario_id", ["QC001", ..., "QC006"])`, import local de `assembler_paie`/`inserer_paie`/`lire_paie`/`lire_cumuls_ytd` pour ne pas faire échouer la collecte tant que les modules n'existent pas
    - Charger `PayrollInput` (fixture d'entrée), `ParametresAnnee` réel 2026, la fixture de sortie attendue (`net`, `cout_employeur`, `cumuls_fin`) ; utiliser `tmp_path / "payroll.db"` (jamais la base de production)
    - Assembler via `assembler_paie(...)`, asserter `resultat.net == Decimal(sortie["net"])` et `resultat.cout_employeur == Decimal(sortie["cout_employeur"])`
    - Insérer via `inserer_paie(resultat, saison="Saison 2026 (test)", chemin_bd=chemin_bd)`, relire via `lire_paie` et asserter l'égalité stricte round-trip (`relu == resultat`)
    - Relire les cumuls via `lire_cumuls_ytd` et asserter l'égalité au cent près pour chacune des onze catégories de `sortie["cumuls_fin"]`
    - _Requirements: 17.4_
    - _Design: §Testing Strategy « Détail des golden tests »_

- [x] 5. Tests de garde statique (`tests/test_guards.py`)
  - [x] 5.1 Ajouter les quatre classes de garde pour `net_pay.py`
    - `TestNetPayNoFloat` — parser `net_pay.py` avec `ast.parse`, vérifier l'absence de `ast.Constant(value=float(...))`, d'appel `Decimal(<non-str>)`, l'absence de `round`/`math.floor`/`math.ceil`/`math.trunc` (Req 16.8)
    - `TestNetPayNoHardcodedFiscalValues` — lecture ligne par ligne, absence de toute constante `Decimal` autre que celles strictement nécessaires à la construction de `_ContributionPaie` (aucune valeur fiscale codée en dur — tous les montants proviennent d'appels) (règle 05)
    - `TestNetPayNoLoadParametersCall` — grep du token `load_parameters` absent de `net_pay.py` (ni import, ni appel) (Req 1.3)
    - `TestNetPayNoOwnUnsupportedPayrollCase` — grep : `raise UnsupportedPayrollCase` absent de `net_pay.py` (seule la propagation par transitivité d'appel est admise) (Req 17.1, 17.2)
    - Ces classes échouent tant que `payroll_engine/net_pay.py` n'existe pas — comportement attendu (règle 06)
    - _Requirements: 1.3, 16.8, 17.1, 17.2_
    - _Design: §Testing Strategy « Détail des tests de garde »_

  - [x] 5.2 Ajouter les trois classes de garde pour `register.py`
    - `TestRegisterNoFloat` — parser `register.py` avec `ast` ; vérifier l'absence de colonne SQL déclarée `REAL` dans le DDL (recherche textuelle sur `CREATE TABLE`) ; vérifier l'absence de `float(...)` appliqué à une valeur destinée à une colonne monétaire (Req 10.2, 10.3, 16.8)
    - `TestRegisterNoDbFileInRepo` — fixture `autouse` session-scoped (ou hook `pytest_sessionfinish`) qui effectue un `glob` récursif de la racine du dépôt (hors `.git/`) pour `*.db`, `*.sqlite`, `*.sqlite3` — échoue si un seul résultat est trouvé (Req 15.3, règle 04)
    - `TestRegisterSchemaExact` — `PRAGMA table_info(paies)` / `PRAGMA table_info(cumuls_ytd)` sur une base `:memory:` fraîchement créée ; compare les noms de colonnes et types au DDL de conception (Req 9.1, 10.1)
    - Ces classes échouent tant que `payroll_engine/register.py` n'existe pas — comportement attendu (règle 06)
    - _Requirements: 9.1, 9.2, 10.1, 10.2, 10.3, 15.3, 16.8_
    - _Design: §Testing Strategy « Détail des tests de garde »_

- [x] 6. Checkpoint — tests rouges complets avant implémentation
  - Vérifier que `pytest tests/payroll_engine/test_net_pay.py` échoue avec `ModuleNotFoundError` sur l'import `payroll_engine.net_pay`
  - Vérifier que `pytest tests/payroll_engine/test_register.py` échoue avec `ModuleNotFoundError` sur l'import `payroll_engine.register`
  - Vérifier que `pytest tests/test_golden_outputs.py::test_assemblage_et_registre_reproduisent_fixture` échoue également (modules absents)
  - Vérifier que les sept classes de garde des tâches 5.1 et 5.2 échouent (modules inexistants)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implémentation de `payroll_engine/net_pay.py`
  - [x] 7.1 Créer `_ContributionPaie` et les imports du module
    - Docstring citant Req 1 à 8, les règles 01, 02, 03, 05, et pointant vers la spec `net-cumuls-registre`
    - `@dataclass(frozen=True) class _ContributionPaie` exposant exactement `employe_id`, `annee_fiscale`, et les onze catégories monétaires identiques à `models.cumuls._CATEGORIES_MONETAIRES` (`brut`, `vacances`, `rrq_employe`, `rrq_employeur`, `rqap_employe`, `rqap_employeur`, `ae_employe`, `ae_employeur`, `impot_qc_retenu`, `impot_federal_retenu`, `net`) — non exportée, non exposée hors module
    - Imports exacts des neuf fonctions déjà livrées et des modèles consommés, sans import de `load_parameters` (Req 1.3)
    - _Requirements: 6.1, 6.2, 6.3_
    - _Design: §Components §2 (`_ContributionPaie`)_

  - [x] 7.2 Implémenter `assembler_paie` (étapes A à H)
    - Signature figée exactement telle qu'énoncée (Req 1.1) : `(payroll_input, parametres_annee, id_paie, version, statut, date_creation, date_emission=None, remplace_par_id=None) -> PayrollResult`
    - Étape A : `gains = calcul_gains(payroll_input, parametres_annee)` (Req 2.1)
    - Étape B : `calcul_rrq_employe`, `calcul_rqap_employe`, `calcul_ae_employe` (Req 2.2)
    - Étape C : `calcul_impot_qc_formule`/`calcul_impot_federal_formule`, puis calcul de `additionnelle_permise` (spec `impots-retenues-source`, Requirement 14 — comparaison arithmétique pure, décision opérationnelle Camp LilySO documentée dans `docs/hypotheses-2026.md`, PAS une formule fiscale TP-1015.F/T4127 : `espace_disponible = brut_total - rrq_emp - rqap_emp - ae_emp - montant_base_qc - montant_base_federal` où `montant_base_qc`/`montant_base_federal` sont `Decimal("0.00")` si exonération active sinon le montant `*_formule` ; `additionnelle_permise = (retenue_additionnelle_QC_effective + retenue_additionnelle_federale_effective) <= espace_disponible`), puis `calcul_impot_qc_retenu`/`calcul_impot_federal_retenu` invoquées avec `additionnelle_permise` en 4e argument (Req 2.3)
    - Étape D : `cotisations_employeur = assembler_cotisations_employeur(payroll_input, gains, parametres_annee)` en un seul appel, sans invocation séparée des fonctions employeur individuelles (Req 2.4)
    - Étape E : construire `RetenuesEmploye` avec `total_retenues_employe` = somme des cinq montants effectivement retenus, à l'exclusion des `*_formule` (Req 3.1, 3.2, 3.3)
    - Étape F : `net = gains.brut_total - retenues_employe.total_retenues_employe` ; `cout_employeur = gains.brut_total + cotisations_employeur.total_cotisations_employeur`, sans arrondissement supplémentaire (Req 5.1, 5.2, 5.4)
    - Étape G : construire `_ContributionPaie` selon le mapping exact des onze catégories, puis `cumuls_fin = payroll_input.cumuls_debut.avec_paie(contribution)` par duck typing (Req 6.1 à 6.5)
    - Étape H : `return PayrollResult(...)` en un seul appel via le constructeur Pydantic standard (jamais `model_construct`), tous les champs de cycle de vie strictement égaux aux arguments reçus (Req 7.1 à 7.4)
    - Aucun `try/except` autour des neuf appels — propagation intégrale de `MissingParameterError`/`UnsupportedPayrollCase` (Req 2.6, 17.3) ; aucune nouvelle `CalculationTrace` créée pour `net`/`cout_employeur` (Req 8.1 à 8.3)
    - À ce stade, tous les tests de la tâche 2 doivent passer
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 17.1, 17.2, 17.3_
    - _Design: §Components §1 (pseudocode complet A à H)_

- [x] 8. Implémentation de `payroll_engine/register.py`
  - [x] 8.1 Créer le schéma SQL, `chemin_bd_production` et le gestionnaire de connexion transactionnelle
    - Docstring citant Req 9 à 15, les règles 01, 04, et pointant vers la spec `net-cumuls-registre`
    - DDL `CREATE TABLE IF NOT EXISTS paies (...)` avec `id_paie TEXT PRIMARY KEY`, `employe_id`, `annee_fiscale`, `numero_periode`, `saison`, `version`, `statut`, `remplace_par_id` (nullable), `date_creation`, `date_emission` (nullable), `payload_json` — aucune colonne `REAL` — et son index `idx_paies_logique` (Req 9.1, 9.2, 9.4)
    - DDL `CREATE TABLE IF NOT EXISTS cumuls_ytd (...)` avec clé primaire composite `(employe_id, annee_civile)` et onze colonnes `TEXT` (Req 10.1, 10.2)
    - `chemin_bd_production() -> Path` — résolution `APPDATA` → `XDG_DATA_HOME` → `~/.local/share`, pure, aucune E/S (Req 15.1)
    - `_creer_schema_si_absent(connexion)` — idempotente, exécute les deux DDL `IF NOT EXISTS`
    - `_connexion(chemin_bd)` — gestionnaire de contexte `sqlite3.connect(..., isolation_level=None)`, `BEGIN IMMEDIATE`/`COMMIT` en sortie normale, `ROLLBACK` sur toute exception, création du répertoire parent si nécessaire (Req 11.5, 13.6)
    - _Requirements: 9.1, 9.2, 9.4, 10.1, 10.2, 15.1, 15.2_
    - _Design: §Components §3.0, §3.1, §3.2 ; §Data Models (DDL `paies`, `cumuls_ytd`)_

  - [x] 8.2 Implémenter `inserer_paie` et les helpers d'agrégation des cumuls
    - `_upsert_cumuls_ytd(connexion, cumul)` — `INSERT ... ON CONFLICT(employe_id, annee_civile) DO UPDATE SET ...`, chaque valeur `Decimal` convertie en `str(valeur)`, jamais `float(valeur)` (Req 10.3)
    - `inserer_paie(resultat, saison, chemin_bd=chemin_bd_production())` : contrôle explicite d'unicité de `id_paie` avant toute écriture (`ValueError` actionnable, Req 11.6) ; insertion append-only quel que soit `resultat.statut` (Req 11.2) ; si `resultat.statut == StatutDePaie.EMISE`, mise à jour de `cumuls_ytd` via `CumulsYTD.avec_paie(resultat)` (lecture via `CumulsYTD.zero` si absent) (Req 11.3) ; sinon aucune modification de `cumuls_ytd` (Req 11.4) ; les deux effets dans une seule transaction (`_connexion`) (Req 11.5)
    - À ce stade, les tests de la tâche 3.2 (Property 8) et 3.8 (Property 14) doivent passer
    - _Requirements: 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
    - _Design: §Components §3.3_

  - [x] 8.3 Implémenter `lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd`
    - `lire_paie(id_paie, chemin_bd=chemin_bd_production())` — `SELECT payload_json ... WHERE id_paie = ?` puis `PayrollResult.model_validate_json(...)` ; `KeyError` explicite si absent (Req 12.1, 12.2, 12.5)
    - `lire_historique_paie(employe_id, annee_fiscale, numero_periode, chemin_bd=...)` — `SELECT ... ORDER BY version ASC`, retourne un tuple (éventuellement vide) de `PayrollResult` désérialisés (Req 12.3)
    - `_lire_cumuls_ytd_tx(connexion, employe_id, annee_civile)` et `lire_cumuls_ytd(employe_id, annee_civile, chemin_bd=...)` — retourne `CumulsYTD.zero(...)` si absent, sinon `CumulsYTD.model_validate({...})` depuis les onze colonnes `TEXT` (Req 12.4, 10.4)
    - Toute désérialisation exclusivement via `Decimal`/Pydantic, jamais via `float` (Req 12.5)
    - À ce stade, les tests de la tâche 3.4 (Property 10) doivent passer
    - _Requirements: 10.4, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_
    - _Design: §Components §3.4, §3.5, §3.6_

  - [x] 8.4 Implémenter `remplacer_paie`
    - Lecture + contrôle de l'ancienne ligne : `KeyError` si `ancien_id` absent (Req 13.2) ; `ValueError` si `statut != EMISE` (Req 13.2)
    - Contrôle du statut du nouveau résultat : `ValueError` si `nouveau_resultat.statut` hors `{EMISE, BROUILLON}` (Req 13.3)
    - Dans une seule transaction : (a) `UPDATE paies SET statut='remplace_par', remplace_par_id=?, payload_json=?` sur `ancien_id` via `model_copy` (Req 13.4a, 9.3, 13.7) ; (b) insertion de `nouveau_resultat` via le même mécanisme que `inserer_paie` (Req 13.4b) ; (c) recalcul de `cumuls_ytd` : retrait de la contribution ancienne puis ajout de la nouvelle si `nouveau_resultat.statut == EMISE`, retrait seul si `BROUILLON` (Req 13.4c, 13.5)
    - `_soustraire_contribution(cumul, resultat)` — nouvelle `CumulsYTD` via `model_copy`, catégorie par catégorie
    - `ROLLBACK` intégral sur toute exception pendant les trois étapes (Req 13.6)
    - À ce stade, tous les tests des tâches 3.1, 3.3, 3.5, 3.6, 3.7 et le golden test de la tâche 4 doivent passer
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 14.1, 14.2, 14.4_
    - _Design: §Components §3.7_

- [x] 9. Checkpoint final — exécution complète, vérification des compteurs et validation manuelle
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (property + golden + garde + exemple) — tous doivent passer
  - Vérifier que `pytest tests/payroll_engine/test_net_pay.py` exécute des tests couvrant les 7 propriétés du design (annotées `# Feature: net-cumuls-registre, Property N`)
  - Vérifier que `pytest tests/payroll_engine/test_register.py` exécute des tests couvrant les 7 propriétés du design (Properties 8 à 14)
  - Vérifier que `pytest tests/test_golden_outputs.py::test_assemblage_et_registre_reproduisent_fixture` exécute exactement 6 tests (un par scénario QC001–QC006) et tous passent au cent près (`net`, `cout_employeur`, `cumuls_fin`)
  - Vérifier que les sept classes de garde des tâches 5.1 et 5.2 passent, notamment l'absence de tout fichier `*.db`/`*.sqlite`/`*.sqlite3` résiduel dans l'arbre versionné
  - Vérifier par grep que `net_pay.py` ne contient aucun `float`, aucune valeur fiscale codée en dur, ni `load_parameters`, `datetime.now`, `UnsupportedPayrollCase` propre ; que `register.py` ne déclare aucune colonne `REAL` et n'utilise `float()` sur aucune valeur monétaire
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, golden tests et tests de garde soient rédigés **avant** l'implémentation et ne peuvent pas être considérés comme facultatifs — discipline TDD stricte alignée avec `moteur-paie-contrats`, `cotisations-sociales-qc`, `impots-retenues-source` et `charges-patronales`.
- **Ordre spec → tests → implémentation → validation** respecté au niveau du plan : sections 1 à 5 (stratégies, property tests de `net_pay.py` et `register.py`, golden, garde) précèdent le checkpoint explicite de la section 6, qui précède les sections 7 (implémentation `net_pay.py`) et 8 (implémentation `register.py`). La section 9 valide l'exécution complète et les garde-fous.
- **`net_pay.py` orchestre, `register.py` persiste** : la tâche 7.2 implémente `assembler_paie` comme pure fonction d'agrégation (aucune formule fiscale, aucune E/S) ; la tâche 8 implémente le seul module d'E/S du moteur, agnostique de la façon dont un `PayrollResult` a été produit (décision design n° 3).
- **Résolution de la dépendance circulaire `cumuls_fin`** : la tâche 7.1 crée `_ContributionPaie`, l'objet privé qui satisfait par duck typing le contrat déjà figé de `CumulsYTD.avec_paie`, sans aucune modification de `models/cumuls.py` (décision design n° 2, Req 6).
- **Chaque property test est annoté** par `# Feature: net-cumuls-registre, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/payroll_engine/test_net_pay.py tests/payroll_engine/test_register.py` retrouve les 14 propriétés du design.
- **Distinction saison/année civile préservée dans les tests** : la tâche 3.7 (Property 13) vérifie explicitement que `saison` n'entre dans aucun calcul de `cumuls_ytd`, conformément au Requirement 14.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "4.1", "5.1"] },
    { "id": 1, "tasks": ["2.2", "3.1", "5.2"] },
    { "id": 2, "tasks": ["2.3", "3.2"] },
    { "id": 3, "tasks": ["2.4", "3.3"] },
    { "id": 4, "tasks": ["2.5", "3.4"] },
    { "id": 5, "tasks": ["2.6", "3.5"] },
    { "id": 6, "tasks": ["3.6"] },
    { "id": 7, "tasks": ["3.7"] },
    { "id": 8, "tasks": ["3.8"] },
    { "id": 9, "tasks": ["7.1", "8.1"] },
    { "id": 10, "tasks": ["7.2", "8.2"] },
    { "id": 11, "tasks": ["8.3"] },
    { "id": 12, "tasks": ["8.4"] }
  ]
}
```
