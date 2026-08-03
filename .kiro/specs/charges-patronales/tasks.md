# Implementation Plan: charges-patronales

<!-- Plan d'implémentation — spec « charges patronales (FSS, CNESST, CNT) » du
     moteur de paie Camp LilySO. Les en-têtes structurels (Overview, Tasks,
     Notes, Task Dependency Graph) sont maintenus en anglais pour conformité au
     format Kiro. Le contenu métier est en français. -->

## Overview

Cette spec livre **l'étape 5 du plan d'implémentation** (`docs/plan-implementation.md`), après `impots-retenues-source` (étape 4) : un module unique `payroll_engine/charges_patronales.py` exposant **trois fonctions pures de calcul** — `calcul_fss`, `calcul_cnesst`, `calcul_cnt`, chacune de signature `(payroll_input, gains, parametres_annee) -> tuple[Decimal, CalculationTrace]` — et une **fonction d'assemblage** `assembler_cotisations_employeur(payroll_input, gains, parametres_annee) -> CotisationsEmployeur` qui **invoque** (sans les recalculer) les fonctions employeur RRQ/RQAP/AE de l'étape 3 et les trois nouvelles fonctions de charges.

**Aucun contrat n'est redéfini.** Cette spec **consomme** exclusivement `PayrollInput`, `GainsDecomposes`, `MontantAvecTrace`, `CotisationsEmployeur`, `CalculationTrace`, `Juridiction`, `ModeArrondissement`, `MissingParameterError`, `ParametresAnnee`/`FSSParametres`/`CNESSTParametres`/`CNTParametres`, plus `calcul_rrq_employeur`/`calcul_rqap_employeur`/`calcul_ae_employeur`. **Seule** modification de contrat figé : l'extension **strictement additive** de la liste blanche `_SOURCES_OFFICIELLES_REGEX` de `models/trace.py` pour admettre le motif `LE-39.0.2 <année>` (Req 5.7).

**Découverte de recherche déterminante** (design.md §Overview) : les trois charges suivent le même patron proportionnel simple `montant = arrondir(taux × brut_total)`, sans exemption, sans plafond, sans cumul YTD. Deux corrections de données sont requises avant que les golden tests ne passent : (a) renseigner la section `cnt` de `parameters/2026/quebec.json` (`taux = "0.0006"`, `base_admissible = "103000.00"`, LE-39.0.2 (2026-01)) — Req 12.1/12.2 ; (b) corriger les sous-libellés CNESST **inversés** (`taux_unite = "0.0090"`, `taux_cni = "0.0022"`) sans toucher `taux_total = "0.0112"` — Req 5.7. Les fixtures QC001–QC006, qui portaient `cnt = 0,00` et des sources incorrectes, sont **régénérées** (Req 11.4).

L'ordre suit strictement la règle 06 : **tests avant code**, puis extension additive de la liste blanche `trace.py` et mise à jour bloquante des paramètres officiels 2026, puis régénération des fixtures, puis implémentation, puis validation manuelle.

**Livrables** :

- Extension de `tests/strategies.py` (`st_brut_total_avec_zero_et_grands`, `st_parametres_annee_2026_qc` en fixture, `st_parametres_annee_variantes_non_consommees`, `st_parametres_annee_avec_to_fill`)
- `tests/payroll_engine/test_charges_patronales.py` (13 propriétés + tests d'exemple, calculs et assemblage)
- Extension de `tests/models/test_trace.py` (acceptation de `LE-39.0.2 2026` par la liste blanche)
- Extension de `tests/test_golden_outputs.py` (paramétrage `fss`/`cnesst`/`cnt` + `total_cotisations_employeur` sur QC001–QC006)
- Extension de `tests/test_guards.py` (quatre nouvelles classes de garde statique)
- Extension additive de `models/trace.py` (`_SOURCES_OFFICIELLES_REGEX` + motif `LE-39.0.2 <année>`) et de `docs/sources-officielles.md`
- Mise à jour de `parameters/2026/quebec.json` (section `cnt` renseignée, sous-libellés CNESST corrigés)
- Régénération de `tests/fixtures/outputs/qc001.json`–`qc006.json` (CNT non nulle, sources corrigées, totaux recalculés)
- `payroll_engine/charges_patronales.py` (implémentation, trois fonctions + assemblage)
- Extension de `docs/cas-non-supportes.md` (plafonds annuels CNESST/CNT et table FSS hors périmètre), `docs/plan-implementation.md` (déviation de nom de module) et `docs/journal-validation.md` (validation manuelle WebRAS, QC001)

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — `Decimal` de bout en bout, aucun `float` dans le module ni dans ses tests
- Règle 02 — retour `(Decimal, CalculationTrace)` avec `source` conforme à la liste blanche (FSS `"TP-1015.F <année>, section 5 — FSS"`, CNESST URL `www.cnesst.gouv.qc.ca`, CNT `"LE-39.0.2 <année>"`)
- Règle 03 — aucun nouveau garde-fou `UnsupportedPayrollCase` (délégation totale à `PayrollInput`/`GainsDecomposes`) ; plafonds annuels et table FSS documentés hors périmètre
- Règle 04 — corpus anonymisé QC001–QC006 uniquement, aucune donnée personnelle réintroduite
- Règle 05 — tous les taux (FSS/CNESST/CNT) lus exclusivement depuis `parametres_annee`, jamais codés en dur ; source officielle et date de consultation consignées dans le JSON
- Règle 06 — sections 1 à 6 (stratégies, property tests, test de trace, golden, garde) rédigées et vérifiées **rouges avant** les sections 8 à 11 (contrat, paramètres, fixtures, implémentation) ; validation manuelle en section 12

## Tasks

- [x] 1. Préparer les stratégies Hypothesis dédiées aux charges patronales
  - [x] 1.1 Étendre `tests/strategies.py` avec les stratégies de `brut_total`, de `ParametresAnnee` 2026 et de leurs variantes
    - Ajouter `st_brut_total_avec_zero_et_grands()` — génère un `GainsDecomposes` valide dont `brut_total` est un `Decimal` dans `[Decimal("0.00"), Decimal("200000.00")]` avec `places=2`, biaisé vers `Decimal("0.00")` (Property 4) et vers de grandes valeurs supérieures à `103 000 $` (Property 8, absence de plafond), via `st.one_of(st.just(Decimal("0.00")), st.decimals(...))`
    - Ajouter une fixture module-scoped `st_parametres_annee_2026_qc()` retournant le `ParametresAnnee` réel 2026 (sections `fss`/`cnesst`/`cnt` renseignées) chargé **une seule fois** — réutilisée par toutes les propriétés
    - Ajouter `st_parametres_annee_variantes_non_consommees()` — variantes de `ParametresAnnee` différant **uniquement** sur les champs non consommés par le calcul de période (`fss.masse_salariale_utilisee_webras_2026`, `fss.table_taux_par_masse_salariale`, `cnt.base_admissible`, `cnesst.en_attente_classification`, sous-taux CNESST `taux_unite`/`taux_cni`), pour Property 8 et Property 11
    - Ajouter `st_parametres_annee_avec_to_fill(champ)` — construit une variante où un champ consommé porte la sentinelle `"TO_FILL"` (par exemple `cnt.taux`, `cnesst.taux_total`, `fss.taux_camp_lilyso_2026`) ou une section requise `None`, pour Property 13
    - Réutiliser `st_payroll_input_et_gains()` (héritée des étapes précédentes, sans modification) pour la génération d'un `PayrollInput` valide ; documenter chaque nouvelle stratégie par un docstring citant le design §Testing Strategy « Stratégies Hypothesis » et la règle 01
    - _Requirements: 10.1 (P3), 2.5/3.5/4.5 (P4), 2.7/3.7/4.7/7.2 (P8), 6.4/9.3 (P11), 1.8/6.7 (P13)_
    - _Design: §Testing Strategy « Stratégies Hypothesis »_

- [x] 2. Property-based tests et tests d'exemple des trois fonctions de calcul (`tests/payroll_engine/test_charges_patronales.py`)
  - [x] 2.1 Créer le squelette du fichier et les tests transversaux (classe `TestSignaturePureteRobustesse`)
    - Module docstring citant le design §Testing Strategy, la liste des 13 propriétés couvertes, et le rappel que ce fichier est écrit **avant** `payroll_engine/charges_patronales.py` (règle 06)
    - Imports : `pytest`, `Decimal`, `ROUND_HALF_UP`, `hypothesis` (`given`, `settings`), les modèles consommés (`PayrollInput`, `GainsDecomposes`, `CalculationTrace`, `MontantAvecTrace`, `CotisationsEmployeur`, `Juridiction`, `ModeArrondissement`, `MissingParameterError`), les stratégies de `tests/strategies.py` ; import local des fonctions sous test pour ne pas faire échouer la collecte tant que le module n'existe pas
    - Fixture module-scoped `st_parametres_annee_2026_qc()`
    - **Property 1 : Déterminisme (pureté)** — pour chacune des trois fonctions de calcul, deux appels avec les mêmes arguments produisent deux tuples `(montant, trace)` égaux au sens `==`
    - **Property 6 : Forme `Decimal` du résultat et de la trace** — pour chacune des trois fonctions, le montant retourné et chaque valeur de `trace.parametres_utilises`/`entrees`/`sous_totaux`/`resultat` sont des `Decimal` finis, le montant retourné étant égal à `.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`
    - Test d'exemple : signatures exactes des trois fonctions et de l'assemblage (Req 1.1, 1.2) ; import de `charges_patronales` sans effet de bord (aucune E/S, aucun appel réseau au moment de l'import — Req 1.7)
    - Annotation de chaque test : `# Feature: charges-patronales, Property N: <titre>`
    - _Requirements: 1.1, 1.2, 1.3, 1.7, 2.6, 3.6, 4.6, 8.3, 10.5_
    - _Design: §Correctness Properties 1, 6 ; §Components §1_

  - [x] 2.2 Tests de la formule proportionnelle, de la non-négativité et du salaire nul (classe `TestFormuleChargesPatronales`)
    - **Property 2 : Formule proportionnelle et arrondissement** — paramétrée sur les trois fonctions, `montant == arrondir(taux × gains.brut_total)` où `taux` est le taux propre à la fonction (`fss.taux_camp_lilyso_2026`, `cnesst.taux_total`, `cnt.taux`), `arrondir == quantize(Decimal("0.01"), ROUND_HALF_UP)` ; l'écart au montant théorique est borné par un demi-cent ; aucune exemption n'est soustraite
    - **Property 3 : Non-négativité** — pour tout `brut_total ≥ 0`, chacune des trois fonctions retourne `montant ≥ Decimal("0.00")`
    - **Property 4 : Zéro lorsque le salaire assujetti est nul** — pour `brut_total == Decimal("0.00")`, chacune des trois fonctions retourne `Decimal("0.00")` sans lever d'exception
    - Annotations pour chacune des trois propriétés
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.4, 3.5, 4.1, 4.2, 4.4, 4.5, 8.1, 8.2, 10.1, 10.3_
    - _Design: §Correctness Properties 2, 3, 4 ; §Components §2, §3, §4, §6_

  - [x] 2.3 Tests de monotonie, d'indépendance et d'insensibilité aux paramètres non consommés (classe `TestMonotonieEtIndependance`)
    - **Property 5 : Monotonie croissante** — pour deux `GainsDecomposes` `g1`, `g2` tels que `g1.brut_total ≤ g2.brut_total`, chacune des trois fonctions produit `montant(g1) ≤ montant(g2)` (à taux fixé)
    - **Property 7 : Indépendance vis-à-vis des champs non pertinents de `payroll_input`** — pour deux `PayrollInput` identiques sur `pay_period.annee_fiscale` mais différant sur des champs non liés au salaire assujetti (`cumuls_debut`, montants TP-1015.3/TD1), chacune des trois fonctions produit le même montant (le Salaire_Assujetti est lu exclusivement depuis `gains.brut_total`)
    - **Property 8 : Insensibilité aux paramètres non consommés et absence de plafond** — via `st_parametres_annee_variantes_non_consommees()`, le montant FSS ne dépend ni de `masse_salariale_utilisee_webras_2026` ni de `table_taux_par_masse_salariale` ; le montant CNESST ne dépend ni de `en_attente_classification` ni des sous-taux `taux_unite`/`taux_cni` ; le montant CNT ne dépend pas de `base_admissible` ; à `brut_total` élevé (> `103 000 $`), chaque montant reste `arrondir(taux × brut_total)` sans plafonnement
    - Annotations pour chacune des trois propriétés
    - _Requirements: 1.5, 2.7, 3.7, 3.8, 4.7, 7.2, 10.2_
    - _Design: §Correctness Properties 5, 7, 8 ; §Components §2, §3, §4 ; §Error Handling « Hors périmètre »_

  - [x] 2.4 Tests de conformité et de contenu de la trace (classe `TestTraceChargesPatronales`)
    - **Property 9 : Conformité et contenu de la trace** — pour chacune des trois fonctions : `trace` est une `CalculationTrace` valide, `trace.resultat == montant` retourné, `trace.annee == payroll_input.pay_period.annee_fiscale`, `trace.mode_arrondissement == ModeArrondissement.ROUND_HALF_UP`, `trace.precision_arrondissement == 2`, `trace.juridiction == Juridiction.QUEBEC`
    - FSS : `trace.source` matche `^TP-1015\.F \d{4}, section 5 — FSS$` ; `parametres_utilises` contient le taux FSS ; `entrees` contient `salaire_assujetti` et `masse_salariale_annuelle`
    - CNESST : `trace.source` matche une URL `www.cnesst.gouv.qc.ca` ; `parametres_utilises` contient le taux total ; `section` contient l'unité `57020` ; `entrees` contient `salaire_assujetti`
    - CNT : `trace.source == "LE-39.0.2 <année>"` ; `parametres_utilises` contient le taux CNT et `base_admissible` ; `entrees` contient `salaire_assujetti`
    - Annotation : `# Feature: charges-patronales, Property 9: Conformité et contenu de la trace`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.4_
    - _Design: §Correctness Properties 9 ; §Components §2, §3, §4_

  - [x] 2.5 Test de propagation de `MissingParameterError` (classe `TestMissingParameterChargesPatronales`)
    - **Property 13 : Propagation de `MissingParameterError` sans interception** — via `st_parametres_annee_avec_to_fill(champ)`, pour un `ParametresAnnee` où un champ consommé (`cnt.taux`, `cnesst.taux_total`, `fss.taux_camp_lilyso_2026`) porte `"TO_FILL"`, l'appel à la fonction concernée lève `MissingParameterError` (jamais une autre exception, ni une exception masquée)
    - Test d'exemple : section requise `None` (`parametres_annee.fss`/`.cnesst`/`.cnt`) → `MissingParameterError` avec message actionnable identifiant la section manquante (Req 1.8)
    - Annotation : `# Feature: charges-patronales, Property 13: Propagation de MissingParameterError`
    - _Requirements: 1.8, 6.7_
    - _Design: §Correctness Properties 13 ; §Error Handling_

- [x] 3. Property-based tests de l'assemblage `assembler_cotisations_employeur` (`tests/payroll_engine/test_charges_patronales.py`)
  - [x] 3.1 Ajouter la classe `TestAssemblageCotisationsEmployeur`
    - **Property 10 : Assemblage par invocation sans recalcul** — l'objet `CotisationsEmployeur` produit satisfait champ par champ : `cot.rrq_employeur.montant == calcul_rrq_employeur(pi, g, p)[0]`, `cot.rqap_employeur.montant == calcul_rqap_employeur(pi, g, p)[0]`, `cot.ae_employeur.montant == calcul_ae_employeur(pi, g, p)[0]`, `cot.fss.montant == calcul_fss(pi, g, p)[0]`, `cot.cnesst.montant == calcul_cnesst(pi, g, p)[0]`, `cot.cnt.montant == calcul_cnt(pi, g, p)[0]` ; chaque champ est un `MontantAvecTrace` dont la `trace` provient de la fonction correspondante
    - **Property 11 : Report du drapeau CNESST sans effet sur le total** — `cot.cnesst_en_attente_classification == parametres_annee.cnesst.en_attente_classification`, et `total_cotisations_employeur` est identique que le drapeau vaille `true` ou `false` (via `st_parametres_annee_variantes_non_consommees()`)
    - **Property 12 : Identité d'agrégation** — `cot.total_cotisations_employeur` égale, au cent près, la somme des six montants employeur (`rrq_employeur + rqap_employeur + ae_employeur + fss + cnesst + cnt`)
    - **Property 1 (assemblage) : Déterminisme** — deux appels de `assembler_cotisations_employeur` avec les mêmes arguments produisent deux `CotisationsEmployeur` égaux au sens `==`
    - **Property 6 (assemblage) : Forme `Decimal`** — `total_cotisations_employeur` est un `Decimal` fini à 2 décimales ; chaque `montant` des six champs est un `Decimal`
    - **Property 13 (assemblage) : Propagation** — si une fonction invoquée lève `MissingParameterError`, l'assemblage la propage sans l'intercepter
    - Annotations pour chaque propriété
    - _Requirements: 1.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 9.1, 9.3, 10.4, 10.6_
    - _Design: §Correctness Properties 1, 6, 10, 11, 12, 13 ; §Components §5_

- [x] 4. Test d'extension de la liste blanche de `CalculationTrace` (`tests/models/test_trace.py`)
  - [x] 4.1 Ajouter la classe `TestListeBlancheLE39`
    - Test d'exemple : `CalculationTrace(source="LE-39.0.2 2026", ...)` construit sans erreur après extension de la liste blanche (Req 5.7, 12.3)
    - Test d'exemple de non-régression : une source `"TP-1015.F 2026, section 5 — FSS"` et une URL `www.cnesst.gouv.qc.ca/...` restent acceptées ; une source non officielle (`"blog interne"`) reste rejetée
    - Ce test échoue tant que la tâche 8.1 n'a pas étendu `_SOURCES_OFFICIELLES_REGEX` — comportement attendu (règle 06)
    - _Requirements: 5.7, 12.3_
    - _Design: §Data Models « Extension de la liste blanche `CalculationTrace` »_

- [x] 5. Golden test de reproduction du corpus QC001–QC006 (`tests/test_golden_outputs.py`)
  - [x] 5.1 Ajouter `test_charges_patronales_reproduisent_fixture`
    - Nouveau test paramétré `@pytest.mark.golden @pytest.mark.parametrize("scenario_id", ["QC001", ..., "QC006"])`, import local de `calcul_fss`/`calcul_cnesst`/`calcul_cnt`/`assembler_cotisations_employeur` pour ne pas faire échouer la collecte tant que le module n'existe pas
    - Chargement `PayrollInput` (fixture d'entrée), `GainsDecomposes` (reconstruit depuis la section `gains` de la fixture de sortie), `ParametresAnnee` réel 2026 (Québec)
    - Assertions d'égalité stricte : `calcul_fss(...)[0] == Decimal(sortie["cotisations_employeur"]["fss"]["montant"])`, idem `cnesst` et `cnt` ; `cot.cnesst_en_attente_classification == sortie["cotisations_employeur"]["cnesst_en_attente_classification"]` ; `cot.total_cotisations_employeur == Decimal(sortie["cotisations_employeur"]["total_cotisations_employeur"])`
    - Assertion `trace_fss.resultat == fss` (cohérence trace/montant, Req 5.5)
    - Docstring citant la limitation « ce test nécessite les paramètres `cnt` 2026 renseignés et les fixtures régénérées — voir tâches 9 et 10 » (Req 11.6)
    - _Requirements: 11.1, 11.2, 11.3, 11.5, 11.6_
    - _Design: §Testing Strategy « Détail des golden tests »_

- [x] 6. Tests de garde statique du nouveau module (`tests/test_guards.py`)
  - [x] 6.1 Ajouter les quatre classes de garde pour `charges_patronales.py`
    - `TestChargesPatronalesNoFloat` — parser le module avec `ast.parse`, vérifier l'absence de `ast.Constant(value=float(...))`, l'absence d'appel `Decimal(<non-str>)`, l'absence d'appel `round`/`math.floor`/`math.ceil`/`math.trunc` (Req 2.6, 3.6, 4.6, 8.3)
    - `TestChargesPatronalesNoHardcodedFiscalValues` — lecture ligne par ligne, absence de toute constante `Decimal` autre que `Decimal("0.00")` (valeur neutre) et l'entier `2` (précision d'arrondissement) — cohérent avec `TestRrqNoHardcodedFiscalValues` (Req 2.3, 3.3, 4.3, règle 05)
    - `TestChargesPatronalesNoLoadParametersCall` — grep du fichier source pour vérifier l'absence du token `load_parameters` (ni import, ni appel), l'absence de `open(`/`json.load`/`Path(...).read_text()`, l'absence de `datetime.now()`/`random.`/`os.environ` (Req 1.4)
    - `TestChargesPatronalesNoUnsupportedPayrollCase` — grep du token `UnsupportedPayrollCase` absent du module (aucun nouveau garde-fou, Req 7.1)
    - Ces classes échouent tant que `payroll_engine/charges_patronales.py` n'existe pas — comportement attendu (règle 06)
    - _Requirements: 1.4, 2.3, 2.6, 3.3, 3.6, 4.3, 4.6, 7.1, 8.3_
    - _Design: §Testing Strategy « Détail des tests de garde »_

- [x] 7. Checkpoint — tests rouges complets avant modification des contrats et implémentation
  - Vérifier que `pytest tests/payroll_engine/test_charges_patronales.py` échoue avec `ModuleNotFoundError` sur l'import `payroll_engine.charges_patronales`
  - Vérifier que `pytest tests/test_golden_outputs.py::test_charges_patronales_reproduisent_fixture` échoue également (module absent et/ou paramètres `cnt` en `"TO_FILL"`)
  - Vérifier que les quatre classes de garde de la tâche 6 échouent (module inexistant)
  - Vérifier que la classe `TestListeBlancheLE39` de la tâche 4 échoue (liste blanche non encore étendue)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Extension additive de la liste blanche `CalculationTrace` et documentation des sources
  - [x] 8.1 Étendre `models/trace.py` et `docs/sources-officielles.md`
    - Ajouter à `_SOURCES_OFFICIELLES_REGEX` le motif `r"^LE-39\.0\.2 \d{4}(, .+)?$"` — extension **strictement additive**, aucun motif existant retiré ni modifié (Req 5.7)
    - Documenter dans `docs/sources-officielles.md` l'ajout de `LE-39.0.2` à la liste blanche, avec la référence au guide LE-39.0.2 (2026-01) archivé dans `docs/sources-officielles/2026/` (règle 02, Req 12.3)
    - À ce stade, la classe `TestListeBlancheLE39` (tâche 4) doit passer
    - _Requirements: 5.7, 12.3_
    - _Design: §Data Models « Extension de la liste blanche `CalculationTrace` »_

- [x] 9. Mise à jour bloquante des paramètres officiels 2026 (`parameters/2026/quebec.json`)
  - [x] 9.1 Renseigner la section `cnt` et corriger les sous-libellés de la section `cnesst`
    - Section `cnt` : remplacer les sentinelles `"TO_FILL"` par `taux = "0.0006"` et `base_admissible = "103000.00"` d'après LE-39.0.2 (2026-01), lignes 35 et 29 ; ajouter `source = "LE-39.0.2 (2026-01)"`, `date_consultation` (date effective), un `commentaire` citant les décisions requirements n° 2 et n° 4, et `statut = "VALIDE_LE_39_0_2_2026"` (Req 12.1, 12.2)
    - Section `cnesst` : corriger les sous-libellés **inversés** — `taux_unite = "0.0090"` et `taux_cni = "0.0022"` (la décision de classification énonce « taux de l'unité = 0,90 », « prime/CNI = 0,22 ») ; **ne pas toucher** `taux_total = "0.0112"` ni `en_attente_classification` ni `unite` ; mettre à jour le `commentaire` pour documenter la correction (Req 5.7)
    - Confirmer qu'aucun autre paramètre déjà validé n'est modifié : `fss.taux_camp_lilyso_2026 = "0.0165"` inchangé, `cnesst.taux_total = "0.0112"` inchangé (Req 12.4)
    - Facultatif (test d'exemple non bloquant) : vérifier l'invariant `taux_unite + taux_cni == taux_total`
    - _Requirements: 12.1, 12.2, 12.4_
    - _Design: §Data Models « Édition des paramètres `parameters/2026/quebec.json` » ; règle 05_

- [x] 10. Régénération du corpus golden QC001–QC006 (`tests/fixtures/outputs/qc001.json`–`qc006.json`)
  - [x] 10.1 Régénérer les six fixtures de sortie pour la CNT, les sources et les totaux recalculés
    - Pour chaque scénario, remplacer `cotisations_employeur.cnt.montant` (`0,00`) par `arrondir(0,0006 × brut_total)` calculé depuis le `brut_total` de la fixture (Req 11.4a)
    - Corriger les sources de trace : `cotisations_employeur.cnesst.trace.source` → URL `www.cnesst.gouv.qc.ca` ; `cotisations_employeur.cnt.trace.source` → `LE-39.0.2 2026` ; supprimer toute attribution `TP-1015.F ... — CNESST/CNT` d'origine (Req 11.4b, 5.7)
    - Recalculer `cotisations_employeur.total_cotisations_employeur` et `cout_employeur` pour intégrer la CNT désormais non nulle (Req 11.4c)
    - Consigner la régénération dans `docs/journal-validation.md` : FSS et CNESST restent exacts au cent contre WebRAS ; la CNT, absente de WebRAS par paie, est validée contre `0,0006 × Salaire_Assujetti` de la LE-39.0.2 (Req 11.5)
    - _Requirements: 11.4, 11.5_
    - _Design: §Testing Strategy « Régénération du corpus golden QC001–QC006 »_

- [x] 11. Implémentation de `payroll_engine/charges_patronales.py`
  - [x] 11.1 Créer le module avec `_arrondir`, les trois fonctions de calcul et l'assemblage
    - Docstring citant Req 1 à 9, les règles 01, 02, 05, et pointant vers la spec `charges-patronales`
    - Constante privée `_PRECISION_MONNAIE: Final[Decimal] = Decimal("0.01")`, helper `_arrondir` (patron identique à `rrq.py`/`impot_qc.py`) — appelé **exactement une fois** par montant théorique, jamais sur `gains.brut_total` ni sur le total de l'assemblage
    - Contrôle de section en tête de chaque fonction de calcul : `if parametres_annee.<section> is None: raise MissingParameterError(...)` avec message actionnable (Req 1.8)
    - `calcul_fss` : `montant = _arrondir(fss.taux_camp_lilyso_2026 × gains.brut_total)` ; ne consulte **jamais** `table_taux_par_masse_salariale` ; `masse_salariale_utilisee_webras_2026` portée dans `entrees` à titre documentaire ; trace avec les champs exacts du design §Components §2 (`source = f"TP-1015.F {annee}, section 5 — FSS"`, `section`, `parametres_utilises`, `entrees`, `sous_totaux`, `mode_arrondissement`, `precision_arrondissement=2`, `resultat`)
    - `calcul_cnesst` : `montant = _arrondir(cnesst.taux_total × gains.brut_total)` ; ne lit pas `en_attente_classification` ni les sous-taux ; aucun plafond annuel ; trace avec `source` = URL officielle `www.cnesst.gouv.qc.ca` (concrète, à figer depuis le guide archivé), `section = f"Classification CNESST — unité {unite}"` (Req 5.3)
    - `calcul_cnt` : `montant = _arrondir(cnt.taux × gains.brut_total)` ; `base_admissible` lue **uniquement** pour la trace (`parametres_utilises`), jamais appliquée comme plafond ; trace avec `source = f"LE-39.0.2 {annee}"` (Req 4.7, 5.4)
    - `assembler_cotisations_employeur` : **invocation stricte** de `calcul_rrq_employeur`/`calcul_rqap_employeur`/`calcul_ae_employeur` (étape 3) puis `calcul_fss`/`calcul_cnesst`/`calcul_cnt` ; lecture du drapeau `cnesst.en_attente_classification` ; `total = somme des six montants` (déjà arrondis, somme exacte au cent, aucun ré-arrondissement) ; construction de `CotisationsEmployeur` avec six `MontantAvecTrace`, le drapeau et le total ; propage `MissingParameterError` sans interception (Req 6)
    - À ce stade, **tous** les tests des tâches 2, 3, 5, 6 doivent passer, y compris les assertions golden QC001–QC006 de la tâche 5
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 8.1, 8.2, 8.3, 8.4, 9.1, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.1, 11.2, 11.3_
    - _Design: §Components §1, §2, §3, §4, §5, §6, §7 ; §Error Handling_

- [x] 12. Checkpoint final — exécution complète, vérification des compteurs et validation manuelle
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (property + golden + garde + exemple) — tous doivent passer
  - Vérifier que `pytest tests/payroll_engine/test_charges_patronales.py` exécute des tests couvrant les 13 propriétés du design (annotées `# Feature: charges-patronales, Property N`), y compris les propriétés d'assemblage 10, 11, 12
  - Vérifier que `pytest tests/test_golden_outputs.py::test_charges_patronales_reproduisent_fixture` exécute exactement 6 tests (un par scénario QC001–QC006) et tous passent au cent près (`fss`, `cnesst`, `cnt`, `total_cotisations_employeur`)
  - Vérifier que les quatre classes de garde de la tâche 6 passent
  - Vérifier par grep que `payroll_engine/charges_patronales.py` ne contient aucun `float`, aucune valeur fiscale codée en dur hors `Decimal("0.00")`/`2`, ni `load_parameters`, `open(`, `datetime.now`, `random.`, `UnsupportedPayrollCase`
  - Reproduire manuellement le scénario QC001 dans WebRAS (FSS et CNESST), confirmer les montants au cent, confirmer la CNT par calcul direct `0,0006 × Salaire_Assujetti`, archiver le guide LE-39.0.2 (2026-01) dans `docs/sources-officielles/2026/` et consigner la validation (date, résultat) dans `docs/journal-validation.md`
  - Étendre `docs/cas-non-supportes.md` (plafonds annuels CNESST/CNT 103 000 $ et table FSS par masse salariale hors périmètre, Req 7.3) et `docs/plan-implementation.md` (déviation de nom de module `charges_patronales.py`, décision requirements n° 6)
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, golden tests et tests de garde soient rédigés **avant** l'implémentation et ne peuvent pas être considérés comme facultatifs — discipline TDD stricte alignée avec `moteur-paie-contrats`, `cotisations-sociales-qc` et `impots-retenues-source`.
- **Ordre spec → tests → implémentation → validation** respecté au niveau du plan : sections 1 à 6 (stratégies, property tests des calculs et de l'assemblage, test de liste blanche, golden test, tests de garde) précèdent le checkpoint explicite de la section 7, qui précède les sections 8 (extension additive de la liste blanche), 9 (mise à jour bloquante des paramètres), 10 (régénération des fixtures) et 11 (implémentation). La section 12 valide manuellement contre WebRAS.
- **Les sections 9 et 10 sont bloquantes critiques** : sans la section `cnt` renseignée (`taux = "0.0006"`, `base_admissible = "103000.00"`) et les fixtures régénérées (CNT non nulle, sources corrigées, totaux recalculés), les golden tests de la section 5 échouent — soit avec `MissingParameterError` (paramètres en `"TO_FILL"`), soit sur des valeurs `cnt = 0,00` obsolètes — même après implémentation complète de la section 11.
- **Correction de traçabilité CNESST (règle 02)** : la tâche 9.1 corrige les sous-libellés **inversés** `taux_unite`/`taux_cni` sans toucher `taux_total = "0.0112"` (seule valeur consommée par le calcul). Cette correction est une exigence de traçabilité, pas de calcul — le montant CNESST reste inchangé.
- **Extension de contrat strictement additive** : la seule modification d'un contrat figé est l'ajout du motif `LE-39.0.2 <année>` à `_SOURCES_OFFICIELLES_REGEX` (tâche 8.1) ; aucun motif existant n'est retiré, la source CNESST réutilise le motif URL `.gouv.qc.ca` déjà présent.
- **Chaque property test est annoté** par `# Feature: charges-patronales, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/payroll_engine/test_charges_patronales.py` retrouve les 13 propriétés du design (dont les propriétés 10, 11, 12 spécifiques à l'assemblage).
- **Assemblage par invocation, jamais par recalcul** : la tâche 3.1 (Property 10) teste que chaque montant employeur provient de l'appel à la fonction dédiée ; la tâche 11.1 implémente `assembler_cotisations_employeur` en **invoquant** RRQ/RQAP/AE de l'étape 3 sans réécrire leurs formules (Req 6.1, décision requirements n° 1).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1", "5.1", "6.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3"] },
    { "id": 4, "tasks": ["2.4"] },
    { "id": 5, "tasks": ["2.5"] },
    { "id": 6, "tasks": ["3.1"] },
    { "id": 7, "tasks": ["8.1", "9.1"] },
    { "id": 8, "tasks": ["10.1"] },
    { "id": 9, "tasks": ["11.1"] }
  ]
}
```
