# Implementation Plan: interface-streamlit

<!-- Plan d'implémentation — spec « interface Streamlit » du Camp LilySO.
     Les en-têtes structurels (Overview, Tasks, Notes, Task Dependency Graph)
     sont maintenus en anglais pour conformité au format Kiro. Le contenu
     métier est en français. -->

## Overview

Cette spec livre **l'étape 7 du plan d'implémentation** (`docs/plan-implementation.md`), après les six specs qui ont livré et figé l'intégralité du moteur de calcul (`models/`, `payroll_engine/`). Elle ajoute une **interface locale Streamlit** (`app/`) qui **consomme** ce moteur sans le modifier — deux couches strictes :

- **`app/logique_metier/*.py`** (huit modules, aucun import `streamlit`) — `stockage_json.py`, `annuaire_employes.py`, `annuaire_coordonnees.py`, `dernieres_paies.py`, `parametres_fiscaux.py`, `formulaire_paie.py`, `fiche_employe.py`, `erreurs.py` ;
- **`app/pages_ui/*.py` + `app/main.py`** (rendu Streamlit exclusivement) — `tableau_de_bord.py`, `fiche_employe_detaillee.py`, `formulaire_paie.py`, `historique_et_cumuls.py`, et le point d'entrée qui les assemble via `st.navigation`/`st.Page`.

**Aucun fichier existant sous `payroll_engine/` ou `models/` n'est modifié** (Req 18.1) : l'interface invoque exclusivement `assembler_paie`, `inserer_paie`, `lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie`, `chemin_bd_production` et `load_parameters` avec leurs signatures exactes déjà figées (Req 18.3).

**Livrables** :

- `tests/app/strategies.py` (stratégies Hypothesis dédiées)
- `tests/app/logique_metier/test_stockage_json.py`, `test_annuaire_employes.py`, `test_annuaire_coordonnees.py`, `test_dernieres_paies.py`, `test_parametres_fiscaux.py`, `test_formulaire_paie.py`, `test_fiche_employe.py`, `test_erreurs.py`
- `tests/app/test_guards.py` (quatre classes de garde statique)
- `app/logique_metier/*.py` (huit modules listés ci-dessus)
- `app/pages_ui/*.py` (quatre modules de rendu) et `app/main.py`
- `app/assets/logo-camp-lilyso.png` (copie versionnée, source `intake/ressources/`, hors dépôt)
- `.streamlit/config.toml` (thème natif, palette Camp LilySO)

**Cadre de discipline appliqué à chaque tâche** :

- Règle 01 — toute saisie numérique convertie en `Decimal` via chaîne, jamais `float` ; `FicheCoordonnees` ne porte aucun champ `Decimal` (absence de montant monétaire)
- Règle 02 — l'interface n'invente aucune nouvelle `CalculationTrace` ; elle affiche exclusivement les traces déjà produites par `assembler_paie`
- Règle 03 — aucun nouveau garde-fou de périmètre dupliqué ; `UnsupportedPayrollCase`/`MissingParameterError` propagées sans interception silencieuse
- Règle 04 — `chemin_annuaire_employes_production()`, `chemin_annuaire_coordonnees_production()` et `chemin_bd_production()` résident hors dépôt ; tests exclusivement sur `tmp_path` ; identifiants fictifs `EMP0XX` ; coordonnées de test manifestement fictives (`"555-0100"`, `"test@example.invalid"`)
- Règle 05 — aucun taux/plafond/constante fiscale codé en dur dans `app/` ; `charger_parametres_fusionnes` délègue intégralement à `load_parameters`
- Règle 06 — sections 1 à 10 (stratégies, property tests des huit modules, tests d'exemple, tests de garde) rédigées et vérifiées **rouges avant** le checkpoint de la section 11, qui précède l'implémentation des sections 12 à 19 ; second checkpoint (section 20) avant le rendu Streamlit (sections 21 à 26) ; validation finale en section 27

**Point de vigilance explicitement corrigé (design §Components 7)** : le pseudocode initial de `mettre_a_jour_donnees_fiscales` utilisait `employee.model_copy(update={...})`, qui **ne ré-exécute pas** les validateurs Pydantic (comportement documenté de Pydantic v2). La tâche 18.2 implémente la version corrigée — reconstruction via le constructeur complet `Employee(**{**employee.model_dump(), <6 champs mis à jour>})` — afin que les gardes de validation d'`Employee` restent actives sur les nouvelles valeurs. La tâche 8.2 écrit le test qui aurait échoué avec `model_copy` et qui valide la correction.

## Tasks

- [x] 1. Préparer les stratégies Hypothesis dédiées à `interface-streamlit`
  - [x] 1.1 Créer `tests/app/strategies.py` avec les stratégies et fixtures nécessaires
    - Ajouter `st_employee_valide()` — délègue aux contraintes déjà connues d'`Employee` (province `Juridiction.QUEBEC` uniquement, `taux_indemnite_vacances` ∈ `{0.04, 0.06}`), identifiants exclusivement `EMPnnn` fictifs (règle 04)
    - Ajouter `st_fiche_coordonnees_valide()` — `employe_id` de forme `EMPnnn`, téléphones/courriels manifestement fictifs (ex. `"555-01XX"`, `"test-XX@example.invalid"`, Req 19.4)
    - Ajouter `st_dates_periode_valide()` — génère `date_debut` puis calcule `date_fin = date_debut + timedelta(days=13)`, satisfaisant par construction la contrainte de contiguïté de `PayPeriod` (pour Properties 10, 11)
    - Ajouter `st_chemin_json_temporaire(tmp_path)` — fournit `tmp_path / f"{prefixe}_{uuid4().hex}.json"` à chaque exemple généré (annuaires JSON, Properties 1, 2, 3, 15)
    - Documenter la réutilisation directe de `tests/strategies.py::st_parametres_annee_2026_qc_ca` (Property 9) — aucune duplication de génération de `ParametresAnnee`
    - Chaque nouvelle stratégie documentée par un docstring citant le design §Testing Strategy « Stratégies Hypothesis réutilisées et nouvelles » et la règle 04
    - _Requirements: 19.1, 19.4_
    - _Design: §Testing Strategy « Stratégies Hypothesis réutilisées et nouvelles »_

- [x] 2. Property tests et tests d'exemple de `stockage_json.py` (`tests/app/logique_metier/test_stockage_json.py`)
  - [x] 2.1 Créer le squelette du fichier et le test de la Property 3
    - Module docstring citant le design §Components 1, la Property 3, et le rappel que ce fichier est écrit **avant** `app/logique_metier/stockage_json.py` (règle 06)
    - Imports : `pytest`, `hypothesis` (`given`, `settings`, `st`), `tmp_path` ; import local de `ecrire_atomique`/`lire_texte_ou_defaut` pour ne pas faire échouer la collecte tant que le module n'existe pas
    - **Property 3 : Écriture atomique des annuaires JSON** — pour tout contenu textuel arbitraire, après `ecrire_atomique(chemin, contenu)`, `chemin.read_text() == contenu` et aucun fichier `*.tmp` résiduel dans le répertoire parent ; test d'exemple complémentaire simulant une exception avant `os.replace` (monkeypatch de `os.replace` levant une exception) — le fichier cible reste dans son état antérieur et aucun `*.tmp` ne subsiste
    - Annotation : `# Feature: interface-streamlit, Property 3: Écriture atomique des annuaires JSON`
    - _Requirements: 2.6, 20.5_
    - _Design: §Components §1 ; §Correctness Properties 3_

  - [x] 2.2 Test d'exemple de `lire_texte_ou_defaut` (classe `TestLireTexteOuDefaut`)
    - Test d'exemple : `chemin` inexistant → retourne `defaut` sans exception (Req 2.2, 20.7)
    - Test d'exemple : `chemin` existant → retourne le contenu exact du fichier
    - _Requirements: 2.2, 20.7_
    - _Design: §Components §1_

- [x] 3. Property tests et tests d'exemple de `annuaire_employes.py` (`tests/app/logique_metier/test_annuaire_employes.py`)
  - [x] 3.1 Créer le squelette du fichier et le test de la Property 1
    - Module docstring citant le design §Components 2, les Properties 1 et 2, écrit avant `app/logique_metier/annuaire_employes.py` (règle 06)
    - Imports : `pytest`, `hypothesis`, `models.employee.Employee`, les stratégies de la tâche 1.1 ; import local de `lister_employes`/`enregistrer_employe`/`lire_employe`
    - **Property 1 : Round-trip de l'Annuaire_Employes** — pour toute liste de `Employee` valides avec `id` distincts, écrire chacune via `enregistrer_employe` puis `lister_employes` retourne exactement l'ensemble écrit, trié par `id` croissant ; pour l'ensemble vide, `lister_employes` retourne un tuple vide sans exception
    - Annotation : `# Feature: interface-streamlit, Property 1: Round-trip de l'Annuaire_Employes`
    - _Requirements: 2.1, 2.2, 2.3_
    - _Design: §Components §2 ; §Correctness Properties 1_

  - [x] 3.2 Test de la Property 2 (classe `TestLireParId`)
    - **Property 2 : Lecture par `id` — round-trip et absence** — pour toute liste écrite et pour tout `id` : si présent, `lire_employe(id)` égale la fiche écrite ; si absent, `lire_employe(id)` lève `KeyError` dont le message cite `id`
    - Annotation : `# Feature: interface-streamlit, Property 2: Lecture par id — round-trip et absence`
    - _Requirements: 2.4, 2.5_
    - _Design: §Components §2 ; §Correctness Properties 2_

  - [x] 3.3 Test d'exemple d'absence de garde-fou dupliqué (classe `TestAucunGardeFouDuplique`)
    - Test d'exemple : `enregistrer_employe` ne valide rien elle-même — un `Employee` déjà construit hors matrice aurait levé `UnsupportedPayrollCase` **à la construction** (`Employee(...)`), jamais à l'enregistrement ; vérifier par inspection (`ast`) l'absence de `raise UnsupportedPayrollCase` dans `annuaire_employes.py`
    - _Requirements: 2.7_
    - _Design: §Components §2_

- [x] 4. Property tests et tests d'exemple de `annuaire_coordonnees.py` (`tests/app/logique_metier/test_annuaire_coordonnees.py`)
  - [x] 4.1 Créer le squelette du fichier, le modèle `FicheCoordonnees` attendu et le test de la Property 15
    - Module docstring citant le design §Components 3, §Data Models, la Property 15, écrit avant `app/logique_metier/annuaire_coordonnees.py` (règle 06)
    - Test d'exemple : `FicheCoordonnees(employe_id="EMP001")` valide avec tous les autres champs `None` ; `model_config` `frozen=True, extra="forbid"` (rejet d'un champ supplémentaire)
    - **Property 15 : Round-trip de l'Annuaire_Coordonnees** — pour toute liste de `FicheCoordonnees` valides avec `employe_id` distincts, écrire via `enregistrer_coordonnees` puis lire chaque `employe_id` via `lire_coordonnees` retourne une fiche égale ; pour tout `employe_id` absent (y compris annuaire inexistant), `lire_coordonnees` retourne `None` sans exception
    - Annotation : `# Feature: interface-streamlit, Property 15: Round-trip de l'Annuaire_Coordonnees`
    - _Requirements: 20.1, 20.2, 20.7_
    - _Design: §Components §3 ; §Data Models ; §Correctness Properties 15_

  - [x] 4.2 Tests d'exemple de séparation stricte du contrat de calcul (classe `TestSeparationStricte`)
    - Test d'exemple : `FicheCoordonnees` n'est jamais une instance `Employee` ni un de ses champs — inspection statique (`ast`) de `app/logique_metier/annuaire_coordonnees.py` confirmant l'absence de tout import de `payroll_engine.net_pay`, `models.payroll_input`, `models.payroll_result` (Req 20.3)
    - Test d'exemple : `nas` accepte une chaîne arbitraire non formatée sans validation de format (Req 20.2, Glossary)
    - _Requirements: 20.3, 18.4_
    - _Design: §Components §3 ; §Data Models_

- [x] 5. Property tests et tests d'exemple de `dernieres_paies.py` (`tests/app/logique_metier/test_dernieres_paies.py`)
  - [x] 5.1 Créer le squelette du fichier et le test de la Property 5
    - Module docstring citant le design §Components 4, les Properties 5, 6, 7, écrit avant `app/logique_metier/dernieres_paies.py` (règle 06)
    - Imports : `pytest`, `hypothesis`, `payroll_engine.register.inserer_paie`, les stratégies existantes de `tests/strategies.py` (séquences de `PayrollResult`) et de la tâche 1.1 ; import local de `derniere_annee_paie`/`LignePaieResume`/`lire_resumes_paies`/`filtrer_par_annee`/`regrouper_saison_par_annee`/`formater_option_annee`
    - **Property 5 : Dernière année de paie d'un employé** — pour tout ensemble de paies insérées pour un mélange d'employés/années, `derniere_annee_paie(employe_id, chemin_bd)` retourne le maximum des `annee_fiscale` correspondant exactement à `employe_id`, ou `None` si aucune paie (y compris base neuve sans table `paies` — test d'exemple explicite sur `:memory:` neuve)
    - Annotation : `# Feature: interface-streamlit, Property 5: Dernière année de paie d'un employé`
    - _Requirements: 4.3_
    - _Design: §Components §4 ; §Correctness Properties 5 ; décision n° 5_

  - [x] 5.2 Test de la Property 6 (classe `TestLibelleAnneeSaison`)
    - **Property 6 : Libellé année/saison du sélecteur** — pour tout ensemble de `LignePaieResume` arbitraires, `formater_option_annee(annee, regrouper_saison_par_annee(resumes)[annee])` produit `"<annee> (<saison>)"` où `<saison>` est celle du résumé de `date_creation` maximale pour cette année ; sans résumé pour cette année, `formater_option_annee(annee, None)` produit `"<annee>"` seul
    - Annotation : `# Feature: interface-streamlit, Property 6: Libellé année/saison du sélecteur`
    - _Requirements: 5.2_
    - _Design: §Components §4 ; §Correctness Properties 6_

  - [x] 5.3 Test de la Property 7 (classe `TestFiltrageParAnnee`)
    - **Property 7 : Filtrage des paies par année fiscale** — pour tout ensemble de résumés et toute année, `filtrer_par_annee` retourne exactement le sous-ensemble correspondant, même ordre relatif, sans altération de champ
    - Annotation : `# Feature: interface-streamlit, Property 7: Filtrage des paies par année fiscale`
    - _Requirements: 5.3_
    - _Design: §Components §4 ; §Correctness Properties 7_

  - [x] 5.4 Test d'exemple de `lire_resumes_paies` (classe `TestLireResumesPaies`)
    - Test d'exemple : sur une base neuve sans table `paies`, retourne un tuple vide sans exception (même discipline que `derniere_annee_paie`, Req 18.2)
    - Test d'exemple : `net` de chaque `LignePaieResume` reste une chaîne (`str`), jamais reconvertie en `float` (règle 01)
    - Test d'exemple : inspection `ast` confirmant l'absence d'appel à une fonction privée (préfixée `_`) de `payroll_engine.register` dans `dernieres_paies.py` (Req 4.3, 18.2)
    - _Requirements: 4.3, 18.2_
    - _Design: §Components §4 ; décision n° 5_

- [x] 6. Property tests et tests d'exemple de `parametres_fiscaux.py` (`tests/app/logique_metier/test_parametres_fiscaux.py`)
  - [x] 6.1 Créer le squelette du fichier et le test de la Property 8
    - Module docstring citant le design §Components 5, les Properties 8 et 9, écrit avant `app/logique_metier/parametres_fiscaux.py` (règle 06)
    - Imports : `pytest`, `hypothesis`, `tmp_path` ; import local de `lister_annees_disponibles`/`charger_parametres_fusionnes`
    - **Property 8 : Détection des années de paramètres disponibles** — pour toute structure `parameters/<AAAA>/` générée (années complètes avec les deux fichiers, années incomplètes, fichiers non numériques), `lister_annees_disponibles(chemin_racine)` retourne exactement l'ensemble trié des années complètes ; tuple vide si le dossier racine n'existe pas
    - Annotation : `# Feature: interface-streamlit, Property 8: Détection des années de paramètres disponibles`
    - _Requirements: 6.1_
    - _Design: §Components §5 ; §Correctness Properties 8_

  - [x] 6.2 Test de la Property 9 (classe `TestFusionParametres`)
    - **Property 9 : Fusion Parametres_Annuels_Fusionnes Québec + Canada** — réutilisation de `tests/strategies.py::st_parametres_annee_2026_qc_ca` (tâche 1.1) ; pour toute paire QC/CA valide même année, `charger_parametres_fusionnes` produit un `ParametresAnnee` dont `rrq`/`rqap`/`impot_quebec` proviennent exactement de la racine QC et `assurance_emploi`/`impot_federal` exactement de la racine CA, sans recalcul ni altération
    - Annotation : `# Feature: interface-streamlit, Property 9: Fusion Parametres_Annuels_Fusionnes Québec + Canada`
    - _Requirements: 6.2_
    - _Design: §Components §5 ; §Correctness Properties 9_

  - [x] 6.3 Test d'exemple de propagation `FileNotFoundError` (classe `TestFichierAbsent`)
    - Test d'exemple : `charger_parametres_fusionnes(annee_inexistante, chemin_racine)` lève `FileNotFoundError` d'origine, non interceptée (Req 6.4)
    - _Requirements: 6.4_
    - _Design: §Components §5_

- [x] 7. Property tests et tests d'exemple de `formulaire_paie.py` (`tests/app/logique_metier/test_formulaire_paie.py`)
  - [x] 7.1 Créer le squelette du fichier et le test de la Property 4
    - Module docstring citant le design §Components 6, les Properties 4, 10, 11, 13, écrit avant `app/logique_metier/formulaire_paie.py` (règle 06)
    - Imports : `pytest`, `hypothesis`, `models.pay_period.{PayPeriod, WeekSegment}`, `models.payroll_input.{HeuresParSemaine, PayrollInput}`, les stratégies de la tâche 1.1 ; import local de `convertir_numero_en_id`/`deriver_semaines_constituantes`/`construire_payroll_input`/`generer_id_paie`
    - **Property 4 : Conversion du numéro d'employé en `id`** — pour tout entier `1` à `999`, `convertir_numero_en_id(str(n))` retourne exactement `f"EMP{n:03d}"`
    - Test d'exemple : `convertir_numero_en_id("abc")` lève `ValueError` (Req 4.7, pas de garde-fou supplémentaire — règle 03)
    - Annotation : `# Feature: interface-streamlit, Property 4: Conversion du numéro d'employé en id`
    - _Requirements: 4.7_
    - _Design: §Components §6 ; §Correctness Properties 4_

  - [x] 7.2 Test de la Property 10 (classe `TestDerivationSemaines`)
    - **Property 10 : Dérivation mécanique des `WeekSegment`** — pour toute paire de dates telle que `date_fin == date_debut + 13 jours` (via `st_dates_periode_valide`, tâche 1.1), `deriver_semaines_constituantes` produit deux `WeekSegment` couvrant `[date_debut, date_debut+6]` et `[date_debut+7, date_fin]`, satisfaisant par construction les invariants de `PayPeriod`
    - Annotation : `# Feature: interface-streamlit, Property 10: Dérivation mécanique des WeekSegment`
    - _Requirements: 7.3_
    - _Design: §Components §6 ; §Correctness Properties 10_

  - [x] 7.3 Test de la Property 11 (classe `TestConstructionPayrollInput`)
    - **Property 11 : Assemblage du `PayrollInput` depuis le Formulaire_Paie** — pour toute combinaison valide (Fiche_Employe, dates cohérentes, heures, paramètres effectifs), `construire_payroll_input` produit un `PayrollInput` dont chaque champ scalaire égale l'argument fourni, `pay_period.annee_fiscale` égale `annee_fiscale`, et `pay_period.semaines` égale le résultat de `deriver_semaines_constituantes` sur les mêmes dates
    - Annotation : `# Feature: interface-streamlit, Property 11: Assemblage du PayrollInput depuis le Formulaire_Paie`
    - _Requirements: 6.3, 7.7_
    - _Design: §Components §6 ; §Correctness Properties 11_

  - [x] 7.4 Test de la Property 13 (classe `TestGenerationIdPaie`)
    - **Property 13 : Génération déterministe de `id_paie`** — pour tout `employe_id`, `annee_fiscale`, `numero_periode` (`1` à `27`), `version >= 1`, `generer_id_paie(...)` produit exactement `f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:02d}-v{version}"` ; test d'exemple explicite pour la régénération après incrément (`version = version_ciblee + 1`)
    - Annotation : `# Feature: interface-streamlit, Property 13: Génération déterministe de id_paie`
    - _Requirements: 10.1, 13.3_
    - _Design: §Components §6 ; §Correctness Properties 13_

  - [x] 7.5 Tests d'exemple de propagation des erreurs de validation (classe `TestPropagationErreursFormulaire`)
    - Test d'exemple : `deriver_semaines_constituantes`/`construire_payroll_input` avec `date_fin != date_debut + 13 jours` → l'erreur de validation d'origine de `PayPeriod` (contiguïté/couverture) remonte sans interception (Req 7.4)
    - Test d'exemple : `construire_payroll_input` avec des heures hors matrice → `UnsupportedPayrollCase` d'origine remonte sans interception (Req 7.7)
    - Inspection `ast` : absence de tout `try/except` autour des constructions `WeekSegment`/`PayPeriod`/`HeuresParSemaine`/`PayrollInput` dans `formulaire_paie.py`
    - _Requirements: 7.4, 7.7_
    - _Design: §Components §6_

- [x] 8. Property tests et tests d'exemple de `fiche_employe.py` (`tests/app/logique_metier/test_fiche_employe.py`)
  - [x] 8.1 Créer le squelette du fichier et le test de la Property 12
    - Module docstring citant le design §Components 7, les Properties 12 et 14, et la note de correction du point de vigilance (`model_copy` → constructeur complet), écrit avant `app/logique_metier/fiche_employe.py` (règle 06)
    - Imports : `pytest`, `hypothesis`, `models.employee.Employee`, `st_employee_valide` (tâche 1.1) ; import local de `parametres_effectifs_par_defaut`/`mettre_a_jour_donnees_fiscales`
    - **Property 12 : Pré-remplissage identité des paramètres effectifs** — pour toute Fiche_Employe valide, `parametres_effectifs_par_defaut(employee)` retourne un dict dont chacune des 7 clés égale strictement le champ source correspondant, sans muter `employee`
    - Annotation : `# Feature: interface-streamlit, Property 12: Pré-remplissage identité des paramètres effectifs`
    - _Requirements: 8.1_
    - _Design: §Components §7 ; §Correctness Properties 12_

  - [x] 8.2 Test de la Property 14 et test explicite des garde-fous actifs (classe `TestMiseAJourFiscaleImmuable`)
    - **Property 14 : Mise à jour immuable des données fiscales** — pour toute Fiche_Employe valide et toute combinaison valide des 6 nouvelles valeurs fiscales, `mettre_a_jour_donnees_fiscales` produit une nouvelle instance `Employee` dont les 6 champs correspondent exactement aux nouvelles valeurs, tous les autres champs identiques à l'original, et l'original reste inchangé après l'appel
    - **Test explicite du point de vigilance (design §Components 7, correction `model_copy` → constructeur complet)** : construire un `Employee` valide puis appeler `mettre_a_jour_donnees_fiscales` avec une valeur qui violerait un validateur Pydantic actif d'`Employee` (ex. un montant négatif sur un champ contraint `ge=0`) — le test DOIT assertir qu'une erreur de validation est levée ; ce test échouerait silencieusement (aucune erreur) si l'implémentation utilisait `employee.model_copy(update=...)`, car `model_copy` ne ré-exécute pas les validateurs — il ne passe qu'avec le constructeur complet `Employee(**{**employee.model_dump(), ...})`
    - Annotation : `# Feature: interface-streamlit, Property 14: Mise à jour immuable des données fiscales`
    - _Requirements: 11.2_
    - _Design: §Components §7 ; §Correctness Properties 14 ; note de correction post-§Components 7_

  - [x] 8.3 Test d'exemple de propagation sans interception (classe `TestPropagationMiseAJour`)
    - Test d'exemple : `mettre_a_jour_donnees_fiscales` avec une valeur invalide propage `UnsupportedPayrollCase`/erreur de validation d'origine, sans interception, et sans qu'aucune modification partielle ne soit visible sur l'instance retournée (aucune instance partielle n'est jamais créée — l'exception est levée avant tout retour) (Req 11.4)
    - _Requirements: 11.4_
    - _Design: §Components §7_

- [x] 9. Tests d'exemple de `erreurs.py` (`tests/app/logique_metier/test_erreurs.py`)
  - [x] 9.1 Créer le squelette du fichier et les tests de disjonction stricte
    - Module docstring citant le design §Components 8, §Error Handling, écrit avant `app/logique_metier/erreurs.py` (règle 06)
    - Import local de `ErreurDomaineAffichable`/`executer_avec_capture`
    - Test d'exemple : `executer_avec_capture(lambda: (_ for _ in ()).throw(UnsupportedPayrollCase("msg")))` retourne `ErreurDomaineAffichable("UnsupportedPayrollCase", "msg")`
    - Test d'exemple : idem pour `MissingParameterError`, `ValueError`, `KeyError` (message cité intact, non paraphrasé, non tronqué)
    - Test d'exemple : `executer_avec_capture(lambda: (_ for _ in ()).throw(TypeError("msg")))` **laisse `TypeError` se propager** (non interceptée) — assertion `pytest.raises(TypeError)` (Req 16.3)
    - Test d'exemple : `executer_avec_capture(lambda: 42)` retourne `42` inchangé (cas de succès)
    - _Requirements: 16.1, 16.2, 16.3_
    - _Design: §Components §8 ; §Error Handling « Disjonction stricte »_

- [x] 10. Tests de garde statique (`tests/app/test_guards.py`)
  - [x] 10.1 Garde d'absence d'import `streamlit` dans `app/logique_metier/**`
    - `TestLogiqueMetierNaimportePasStreamlit` — parcourt `Path("app/logique_metier").rglob("*.py")` avec `ast.parse`, vérifie l'absence de `ast.Import`/`ast.ImportFrom` référençant `streamlit` (patron exact du design §Error Handling)
    - Ce test échoue tant qu'aucun fichier de `app/logique_metier/` n'existe (collecte vide acceptée, mais le test doit rester vert dès la création des fichiers sans `streamlit`) — comportement attendu avant implémentation (règle 06)
    - _Requirements: 1.1, 1.3_
    - _Design: §Error Handling « Test de garde — absence d'import streamlit »_

  - [x] 10.2 Garde d'absence de `except Exception`/`except BaseException` générique hors `erreurs.py`
    - `TestAucunExceptGenerique` — parcourt tous les fichiers de `app/` sauf `app/logique_metier/erreurs.py`, recherche `ast.ExceptHandler` dont `type` résout à `Exception`/`BaseException` — échoue si trouvé
    - _Requirements: 16.1_
    - _Design: §Error Handling « Test de garde — absence de except Exception »_

  - [x] 10.3 Garde d'absence de référence à `paystub`
    - `TestAucuneReferencePaystub` — recherche textuelle (grep) de `paystub` dans `app/main.py` et `app/pages_ui/**` — échoue si trouvé
    - _Requirements: 17.3_
    - _Design: §Error Handling « Test de garde — absence de référence à paystub »_

  - [x] 10.4 Garde des signatures exactes des six fonctions du moteur invoquées
    - `TestSignaturesExactesMoteur` — via `inspect.signature`, vérifie que chaque site d'appel de `assembler_paie`, `inserer_paie`, `lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie` dans `app/logique_metier/**` et `app/pages_ui/**` n'utilise aucun argument positionnel ou nommé absent de la signature figée (aucun argument supplémentaire) — inspection `ast` des appels (noms d'arguments) comparée à `inspect.signature` des six fonctions importées de `payroll_engine`
    - Ce test échoue tant que les fichiers `app/` correspondants n'existent pas — comportement attendu (règle 06)
    - _Requirements: 18.3_
    - _Design: §Error Handling « Points d'appel couverts »_

- [x] 11. Checkpoint — tests rouges complets avant implémentation
  - Vérifier que `pytest tests/app/logique_metier/` échoue avec `ModuleNotFoundError` sur chacun des huit imports locaux (`stockage_json`, `annuaire_employes`, `annuaire_coordonnees`, `dernieres_paies`, `parametres_fiscaux`, `formulaire_paie`, `fiche_employe`, `erreurs`)
  - Vérifier que les quatre classes de garde de la tâche 10 échouent ou restent vides tant que `app/` n'existe pas
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implémentation de `app/logique_metier/stockage_json.py`
  - [x] 12.1 Créer `ecrire_atomique` et `lire_texte_ou_defaut`
    - Docstring citant Req 2.6, 20.5, règle 04, et pointant vers la spec `interface-streamlit`
    - `ecrire_atomique(chemin, contenu)` — `mkdir(parents=True, exist_ok=True)`, `tempfile.mkstemp(dir=str(chemin.parent), suffix=".tmp")`, écriture + `fsync`, `os.replace(chemin_temp, chemin)`, nettoyage du fichier temporaire (`unlink(missing_ok=True)`) sur toute exception via `except BaseException: ... raise`
    - `lire_texte_ou_defaut(chemin, defaut)` — retourne `defaut` si `not chemin.exists()`, sinon `chemin.read_text(encoding="utf-8")`
    - À ce stade, tous les tests de la tâche 2 doivent passer
    - _Requirements: 2.2, 2.6, 20.5, 20.7_
    - _Design: §Components §1_

- [x] 13. Implémentation de `app/logique_metier/annuaire_employes.py`
  - [x] 13.1 Créer `chemin_annuaire_employes_production`, `lister_employes`, `enregistrer_employe`, `lire_employe`
    - Docstring citant Req 2, règle 04, pointant vers la spec `interface-streamlit`
    - `chemin_annuaire_employes_production() -> Path` — `chemin_bd_production().parent / "employees.json"` (aucune duplication de la résolution `%APPDATA%`, décision n° 2)
    - `lister_employes(chemin_annuaire=chemin_annuaire_employes_production())` — `lire_texte_ou_defaut(..., defaut="[]")`, `json.loads`, ré-encodage individuel (`json.dumps`) puis `Employee.model_validate_json`, tri par `id` (Req 2.1, 2.2)
    - `enregistrer_employe(employe, chemin_annuaire=...)` — dict `{id: Employee}` depuis `lister_employes`, remplacement/ajout par `id`, réécriture complète via `ecrire_atomique` (Req 2.3, 2.6)
    - `lire_employe(id_employe, chemin_annuaire=...)` — parcours de `lister_employes`, `KeyError` explicite citant `id_employe` si absent (Req 2.4, 2.5)
    - Aucun garde-fou de périmètre dupliqué (Req 2.7)
    - À ce stade, tous les tests de la tâche 3 doivent passer
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_
    - _Design: §Components §2 ; §Architecture « Résolution des chemins de production hors dépôt »_

- [x] 14. Implémentation de `app/logique_metier/annuaire_coordonnees.py`
  - [x] 14.1 Créer `FicheCoordonnees`, `chemin_annuaire_coordonnees_production`, `lister_coordonnees`, `enregistrer_coordonnees`, `lire_coordonnees`
    - Docstring citant Req 20, règle 04, pointant vers la spec `interface-streamlit` ; rappel explicite que ce modèle est placé sous `app/`, jamais sous `models/` (décision n° 8)
    - `class FicheCoordonnees(BaseModel)` — `model_config = ConfigDict(frozen=True, extra="forbid")`, champs `employe_id: str = Field(..., min_length=1)`, `nom_complet_reel`, `nas`, `adresse_residentielle`, `courriel`, `telephone` (tous `str | None = None`)
    - `chemin_annuaire_coordonnees_production() -> Path` — `chemin_bd_production().parent / "coordonnees.json"`
    - `lister_coordonnees`/`enregistrer_coordonnees`/`lire_coordonnees` — même patron exact que `annuaire_employes.py` (Req 20.1, 20.2, 20.5, 20.7), `lire_coordonnees` retourne `None` si absent (jamais `KeyError`, à la différence de `lire_employe`)
    - À ce stade, tous les tests de la tâche 4 doivent passer
    - _Requirements: 20.1, 20.2, 20.5, 20.7_
    - _Design: §Components §3 ; §Data Models_

- [x] 15. Implémentation de `app/logique_metier/dernieres_paies.py`
  - [x] 15.1 Créer `derniere_annee_paie` et `LignePaieResume`
    - Docstring citant Req 4.3, 5.3, 18.2, règle 01, pointant vers la spec `interface-streamlit`
    - `derniere_annee_paie(employe_id, chemin_bd=chemin_bd_production())` — `sqlite3.connect`, `SELECT MAX(annee_fiscale) FROM paies WHERE employe_id = ?`, capture explicite de `sqlite3.OperationalError` dont le message contient `"no such table"` → `None` ; toute autre `OperationalError` propagée ; `None` si aucune ligne (Req 4.3, 18.2)
    - `@dataclass(frozen=True) class LignePaieResume` — `id_paie`, `numero_periode`, `version`, `statut`, `net` (`str`), `saison`, `annee_fiscale`, `date_creation`
    - À ce stade, les tests de la tâche 5.1 (Property 5) et 5.4 doivent passer
    - _Requirements: 4.3, 18.2_
    - _Design: §Components §4 ; décision n° 5_

  - [x] 15.2 Créer `lire_resumes_paies`, `filtrer_par_annee`, `regrouper_saison_par_annee`, `formater_option_annee`
    - `lire_resumes_paies(employe_id, chemin_bd=...)` — `SELECT` direct des colonnes documentées de `paies`, extraction de `net` via `PayrollResult.model_validate_json(payload_json).net` converti en `str`, tuple trié par `(annee_fiscale, date_creation)`, tuple vide si table absente (même discipline que 15.1)
    - `filtrer_par_annee(resumes, annee_fiscale)` — filtre pur, ordre relatif préservé (Req 5.3)
    - `regrouper_saison_par_annee(resumes)` — dict `{annee: saison}` de `date_creation` maximale par année (Req 5.2)
    - `formater_option_annee(annee, saison)` — `f"{annee} ({saison})"` ou `str(annee)` (Req 5.2)
    - À ce stade, tous les tests de la tâche 5 doivent passer
    - _Requirements: 5.2, 5.3, 14.3_
    - _Design: §Components §4 ; §Correctness Properties 6, 7_

- [x] 16. Implémentation de `app/logique_metier/parametres_fiscaux.py`
  - [x] 16.1 Créer `lister_annees_disponibles` et `charger_parametres_fusionnes`
    - Docstring citant Req 6, règle 05, pointant vers la spec `interface-streamlit`
    - `lister_annees_disponibles(chemin_racine=None)` — résolution par défaut `Path(__file__).parent.parent.parent / "parameters"`, tuple trié des années dont le dossier contient `quebec.json` **et** `canada.json`, tuple vide si racine absente (Req 6.1)
    - `charger_parametres_fusionnes(annee, chemin_racine=None)` — `load_parameters(annee, Juridiction.QUEBEC, chemin_racine)`, `load_parameters(annee, Juridiction.CANADA, chemin_racine)`, fusion via `parametres_qc.model_copy(update={"assurance_emploi": ..., "impot_federal": ...})` (patron identique à `tests/strategies.py::_charger_parametres_annee_2026_qc_ca`) ; aucune interception de `FileNotFoundError` (Req 6.4)
    - À ce stade, tous les tests de la tâche 6 doivent passer
    - _Requirements: 6.1, 6.2, 6.4_
    - _Design: §Components §5_

- [x] 17. Implémentation de `app/logique_metier/formulaire_paie.py`
  - [x] 17.1 Créer `convertir_numero_en_id` et `deriver_semaines_constituantes`
    - Docstring citant Req 4.7, 7, règle 03, pointant vers la spec `interface-streamlit`
    - `convertir_numero_en_id(numero)` — `f"EMP{int(numero):03d}"`, `int(numero)` propage `ValueError` sans garde-fou supplémentaire (Req 4.7)
    - `deriver_semaines_constituantes(date_debut, date_fin)` — deux `WeekSegment` (`heures_normales`/`heures_supplementaires` provisoires à `Decimal("0")`, remplacées par l'appelant), première semaine `[date_debut, date_debut+6j]`, seconde `[date_debut+7j, date_fin]` (Req 7.3)
    - À ce stade, les tests des tâches 7.1 et 7.2 doivent passer
    - _Requirements: 4.7, 7.3_
    - _Design: §Components §6_

  - [x] 17.2 Créer `construire_payroll_input` et `generer_id_paie`
    - `construire_payroll_input(*, employee, numero_periode, date_debut, date_fin, date_paiement, annee_fiscale, nb_periodes_annuelles, heures_semaine_1, heures_semaine_2, taux_horaire_effectif, taux_vacances, jours_feries_manuels, montant_total_TP1015_3_effectif, exoneration_TP1015_3_effectif, retenue_additionnelle_QC_effective, montant_total_TD1_effectif, exoneration_TD1_effective, retenue_additionnelle_federale_effective, cumuls_debut) -> PayrollInput` — signature figée par mots-clés uniquement, dérive les deux `WeekSegment` réels (avec les heures fournies) via `deriver_semaines_constituantes` puis remplacement des heures, construit `PayPeriod(frequence=FrequencePaie.AUX_DEUX_SEMAINES, ...)` puis `PayrollInput(...)` ; aucune interception des exceptions de validation (Req 7.7)
    - `generer_id_paie(employe_id, annee_fiscale, numero_periode, version)` — `f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:02d}-v{version}"` (Req 10.1, 13.3)
    - À ce stade, tous les tests de la tâche 7 doivent passer
    - _Requirements: 6.3, 7.7, 10.1, 13.3_
    - _Design: §Components §6_

- [x] 18. Implémentation de `app/logique_metier/fiche_employe.py`
  - [x] 18.1 Créer `ParametresEffectifs` (TypedDict) et `parametres_effectifs_par_defaut`
    - Docstring citant Req 8.1, pointant vers la spec `interface-streamlit`
    - `class ParametresEffectifs(TypedDict)` avec les 7 clés exactes du design §Components 7
    - `parametres_effectifs_par_defaut(employee)` — projection pure des 7 champs source, aucune mutation d'`employee`
    - À ce stade, les tests de la tâche 8.1 doivent passer
    - _Requirements: 8.1_
    - _Design: §Components §7_

  - [x] 18.2 Créer `mettre_a_jour_donnees_fiscales` — constructeur complet, PAS `model_copy`
    - **Correction explicite du point de vigilance du design §Components 7** : implémenter avec `Employee(**{**employee.model_dump(), "montant_total_TP1015_3": montant_total_TP1015_3, "exoneration_TP1015_3": exoneration_TP1015_3, "retenue_additionnelle_QC": retenue_additionnelle_QC, "montant_total_TD1": montant_total_TD1, "exoneration_TD1": exoneration_TD1, "retenue_additionnelle_federale": retenue_additionnelle_federale})` — **jamais** `employee.model_copy(update={...})`, car `model_copy` ne ré-exécute pas les validateurs Pydantic et laisserait passer une valeur qui violerait un garde-fou d'`Employee` (Req 11.2, 11.4)
    - `employee.model_dump()` (mode Python, pas JSON) préserve les valeurs `Decimal` natives directement réutilisables par le constructeur `Employee(...)`
    - `employee` (l'original) reste inchangé (`frozen=True`) ; l'instance retournée est nouvelle et intégralement revalidée
    - À ce stade, tous les tests de la tâche 8 doivent passer, y compris le test explicite de la tâche 8.2 qui aurait échoué silencieusement avec `model_copy`
    - _Requirements: 11.2, 11.4_
    - _Design: §Components §7 ; note de correction post-§Components 7_

- [x] 19. Implémentation de `app/logique_metier/erreurs.py`
  - [x] 19.1 Créer `ErreurDomaineAffichable` et `executer_avec_capture`
    - Docstring citant Req 16, règle 03, pointant vers la spec `interface-streamlit`
    - `@dataclass(frozen=True) class ErreurDomaineAffichable` — `type_exception: str`, `message: str`
    - `executer_avec_capture(fonction)` — `try: return fonction()`, `except UnsupportedPayrollCase as exc: return ErreurDomaineAffichable("UnsupportedPayrollCase", str(exc))`, puis `MissingParameterError`, `ValueError`, `KeyError` dans cet ordre exact — **aucun** `except Exception`/`except BaseException` (Req 16.1, 16.3)
    - À ce stade, tous les tests de la tâche 9 doivent passer
    - _Requirements: 16.1, 16.2, 16.3_
    - _Design: §Components §8 ; §Error Handling_

- [x] 20. Checkpoint — logique métier complète, tous les tests non-UI passent
  - Exécuter `pytest tests/app/ --strict-markers -ra` — tous les tests des tâches 2 à 10 doivent passer (property tests, tests d'exemple, tests de garde)
  - Vérifier que les quatre classes de garde de la tâche 10 passent, en particulier l'absence d'import `streamlit` dans les huit fichiers désormais implémentés de `app/logique_metier/`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 21. Assets et configuration visuelle
  - [x] 21.1 Copier le logo du Camp LilySO vers un emplacement versionné
    - Copier `intake/ressources/logo-camp-lilyso.png` (hors dépôt versionné) vers `app/assets/logo-camp-lilyso.png` (emplacement versionné) — fichier non sensible (illustration générique de mouettes), copie explicite requise car `intake/` est hors dépôt (règle 04, Req 3.2)
    - Créer `app/assets/__init__.py` si nécessaire pour la cohérence du package (aucune logique, fichier vide ou docstring seul)
    - _Requirements: 3.2_
    - _Design: §Overview « Livrables » ; §Architecture « Placement dans l'arbre »_

  - [x] 21.2 Créer `.streamlit/config.toml` avec le thème natif
    - Créer `.streamlit/config.toml` avec la section `[theme]` : `primaryColor = "#7aaeea"`, `backgroundColor = "#bad5f4"`, `secondaryBackgroundColor = "#1f2c3b"`, `textColor = "#3d5775"`, `font = "sans serif"` — valeurs exactes du design §Architecture « Thème natif », correspondance documentée avec `intake/ressources/code-couleurs.txt`
    - _Requirements: 3.1_
    - _Design: §Architecture « Thème natif (Req 3.1, décision n° 7) »_

- [x] 22. Implémentation du rendu Streamlit — tableau de bord
  - [x] 22.1 Créer `app/pages_ui/tableau_de_bord.py`
    - Fonction unique `render() -> None` : liste les Fiches_Employe (`lister_employes`, enveloppé par `executer_avec_capture`), affiche pour chacune `id`, `nom_affichage`, année de dernière paie (`derniere_annee_paie`, ou indication explicite d'absence) (Req 4.1, 4.2, 4.3)
    - Bouton d'ajout d'employé déclenchant le formulaire de création de Fiche_Employe (champs de l'AC7, sans NAS/adresse/courriel/téléphone — Req 4.7, 4.8) ; `province_travail` affiché en lecture seule fixé à `Juridiction.QUEBEC` (Req 4.9) ; construction via `Employee.avec_defauts_par_annee(...)` (Req 4.10), affichage des 4 valeurs dérivées ajustables avant `enregistrer_employe` (Req 4.11) ; toute `MissingParameterError`/`UnsupportedPayrollCase` affichée via `executer_avec_capture` (Req 4.12)
    - Raccourci par ligne pour ajouter une paie (année civile courante pré-sélectionnée, modifiable, Req 4.5) et pour naviguer vers la Fiche_Employe_Detaillee (Req 4.6)
    - Application de la palette (boutons `type="primary"`) et confirmation explicite absente ici (aucune action irréversible sur cet écran)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12_
    - _Design: §Architecture « Navigation multipage » ; §Components §2, §4_

- [x] 23. Implémentation du rendu Streamlit — fiche employé détaillée
  - [ ] 23.1 Créer `app/pages_ui/fiche_employe_detaillee.py`
    - Fonction unique `render() -> None` : trois sections visuellement distinctes — informations employé, Fiche_Coordonnees, paies (Req 5.1, 20.4)
    - Section informations employé : affichage des champs `Employee`, formulaire de modification des 6 champs TD1/TP-1015.3 invoquant `mettre_a_jour_donnees_fiscales` puis `enregistrer_employe` (Req 11.1, 11.2, 11.3) ; toute erreur via `executer_avec_capture` sans persistance partielle (Req 11.4)
    - Section coordonnées : affichage/édition de la `FicheCoordonnees` via `lire_coordonnees`/`enregistrer_coordonnees`, visuellement distincte du Formulaire_Paie et du formulaire de création (Req 20.4)
    - Section paies : liste déroulante des années formatée par `formater_option_annee`/`regrouper_saison_par_annee` (Req 5.2), liste des paies de l'année sélectionnée via `filtrer_par_annee`/`lire_resumes_paies` (Req 5.3), affichage des valeurs TD1/TP-1015.3 effectives et des cumuls YTD (`lire_cumuls_ytd`, Req 5.4), bouton d'ajout de paie (Req 5.5), indication explicite d'absence de paie (Req 5.6)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.1, 11.2, 11.3, 11.4, 20.4_
    - _Design: §Components §3, §4, §7_

- [x] 24. Implémentation du rendu Streamlit — formulaire de paie
  - [x] 24.1 Créer `app/pages_ui/formulaire_paie.py`
    - Fonction unique `render() -> None` : sélection de l'année parmi `lister_annees_disponibles()` (Req 6.1), chargement de `charger_parametres_fusionnes` (Req 6.2, 6.4), `numero_periode` bornée par `nb_periodes_annuelles` (Req 7.1), trois dates de période (Req 7.2), heures par semaine dérivées et jours fériés manuels en `Decimal` (Req 7.5, 7.6)
    - Pré-remplissage des 7 paramètres effectifs (`parametres_effectifs_par_defaut`, Req 8.1, 8.2) et de `cumuls_debut` (`lire_cumuls_ytd`, Req 9.1, 9.2, 9.3) — aucune saisie manuelle des onze catégories
    - Bouton d'assemblage invoquant `construire_payroll_input` puis `assembler_paie(...)` via `executer_avec_capture`, `id_paie` généré par `generer_id_paie` avec `version=1` (Req 10.1) ; affichage complet de la Paie_Assemblee avec consultation des `CalculationTrace` (Req 10.2, 10.3) ; toute erreur affichée sans persistance automatique (Req 10.4, 10.5)
    - Choix explicite `BROUILLON`/`EMISE`, `saison` pré-rempli `"Été <annee_fiscale>"` modifiable (Req 12.1, 12.2), confirmation explicite avant `inserer_paie` si `EMISE` (Req 3.3), confirmation de l'`id_paie` inséré (Req 12.3, 12.4), erreur `ValueError` affichée sans masquer l'état de saisie (Req 12.5)
    - Action_Corriger : sélection d'une paie `EMISE`, pré-remplissage du formulaire, réassemblage, `version = version_ciblee + 1`, confirmation explicite avant `remplacer_paie` (Req 3.3, 13.1 à 13.5)
    - Préservation de `st.session_state` sur toute erreur (Req 16.4) — chaque widget lié par `key=`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5, 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5, 16.4, 3.3_
    - _Design: §Components §5, §6, §7, §8 ; §Error Handling « Préservation des valeurs saisies »_

- [x] 25. Implémentation du rendu Streamlit — historique et cumuls
  - [x] 25.1 Créer `app/pages_ui/historique_et_cumuls.py`
    - Fonction unique `render() -> None` : sélection employé/année fiscale/numéro de période, appel `lire_historique_paie(...)` via `executer_avec_capture`, affichage ordonné par `version` croissant (Req 14.1) ; tuple vide indiqué explicitement sans erreur (Req 14.2) ; affichage minimal par version (`id_paie`, `version`, `statut`, `remplace_par_id`, `date_creation`, `date_emission`, `net`) (Req 14.3)
    - Sélection employé/année civile, appel `lire_cumuls_ytd(...)` via `executer_avec_capture`, affichage des onze catégories (Req 15.1) ; absence de ligne affichée à `Decimal("0.00")` sans traitement particulier (Req 15.2)
    - _Requirements: 14.1, 14.2, 14.3, 15.1, 15.2_
    - _Design: §Components §4 ; §Error Handling_

- [x] 26. Implémentation du point d'entrée et wiring de la navigation
  - [x] 26.1 Créer `app/main.py`
    - Imports des quatre modules de `app/pages_ui/` (tâches 22 à 25, toutes doivent déjà exister) et `streamlit`
    - `st.set_page_config(page_title="Camp LilySO — Paie", page_icon="app/assets/logo-camp-lilyso.png")` (Req 3.2, tâche 21.1)
    - Construction des quatre `st.Page(<module>.render, title=..., icon=...)`, `tableau_de_bord` par défaut (`default=True`) (Req 4.1)
    - `st.navigation([...]).run()`
    - Aucune référence à `payroll_engine/paystub.py` (Req 17.1, 17.2, 17.3) — vérifié par le test de garde de la tâche 10.3
    - À ce stade, l'application est complète : tous les tests de `tests/app/` passent, incluant les quatre classes de garde de la tâche 10
    - _Requirements: 3.2, 4.1, 17.1, 17.2, 17.3_
    - _Design: §Architecture « Navigation multipage »_

- [x] 27. Checkpoint final — exécution complète et vérification des garde-fous
  - Exécuter `pytest --strict-markers -ra` sur l'ensemble des tests (`tests/app/**` et l'ensemble des tests existants du moteur) — tous doivent passer, aucune régression sur les six specs antérieures
  - Vérifier que `pytest tests/app/` exécute des tests couvrant les 15 propriétés du design (annotées `# Feature: interface-streamlit, Property N`) via `grep -rn "Property [0-9]" tests/app/`
  - Vérifier que les quatre classes de garde de la tâche 10 passent : absence d'import `streamlit` dans `app/logique_metier/**`, absence de `except Exception`/`except BaseException` générique hors `erreurs.py`, absence de référence à `paystub`, signatures exactes des six fonctions du moteur invoquées
  - Vérifier par grep qu'aucun fichier `*.json`/`*.db` réel n'est commité sous `app/` ou à la racine du dépôt (règle 04)
  - Vérifier la présence de `app/assets/logo-camp-lilyso.png` et de `.streamlit/config.toml` avec les quatre clés `[theme]` exactes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- **Aucune tâche marquée `*`** dans ce plan : la règle 06 du projet impose que les property tests, tests d'exemple et tests de garde soient rédigés **avant** l'implémentation et ne peuvent pas être considérés comme facultatifs — discipline TDD stricte alignée avec les six specs précédentes du moteur, dont `net-cumuls-registre`.
- **Ordre spec → tests → implémentation → validation** respecté au niveau du plan : sections 1 à 10 (stratégies, property tests des huit modules de `app/logique_metier/`, tests d'exemple, tests de garde) précèdent le checkpoint explicite de la section 11, qui précède les sections 12 à 19 (implémentation de `app/logique_metier/**`). Le second checkpoint (section 20) valide que toute la logique métier est fonctionnelle et testée avant d'aborder le rendu Streamlit (sections 21 à 26). La section 27 valide l'exécution complète finale.
- **Correction explicite du point de vigilance `model_copy` → constructeur complet** (design §Components 7) : la tâche 8.2 écrit un test qui aurait échoué silencieusement (aucune erreur levée) si `mettre_a_jour_donnees_fiscales` utilisait `employee.model_copy(update={...})`, car cette méthode Pydantic v2 ne ré-exécute pas les validateurs. La tâche 18.2 implémente la version corrigée via `Employee(**{**employee.model_dump(), <6 champs mis à jour>})`, garantissant que les gardes de validation d'`Employee` restent actives sur les nouvelles valeurs fiscales.
- **Copie du logo hors dépôt vers un emplacement versionné** (tâche 21.1) : `intake/ressources/logo-camp-lilyso.png` réside hors du dépôt versionné (règle 04) ; la copie vers `app/assets/logo-camp-lilyso.png` est un fichier non sensible (illustration générique), traité comme une tâche explicite et vérifiable (présence du fichier), pas comme une opération manuelle.
- **Thème natif plutôt que CSS injecté** (tâche 21.2) : `.streamlit/config.toml` applique la palette Camp LilySO via les clés `[theme]` natives, sans dépendance à `st.markdown(..., unsafe_allow_html=True)`, cohérent avec la décision n° 7 du design.
- **`app/pages_ui/**` et `app/main.py` ne sont couverts par aucune property-based test** (design §Testing Strategy « Hors périmètre du PBT ») : ce sont des tests d'exemple et de garde qui couvrent le rendu ; le contenu métier invoqué par ces pages est déjà entièrement validé par les tâches 2 à 19 et par les tests des six specs antérieures du moteur.
- **`app/main.py` implémenté en dernier** (tâche 26) : il importe les quatre modules de `app/pages_ui/` (tâches 22 à 25), qui doivent donc être implémentés au préalable — aucun code orphelin, le point d'entrée assemble uniquement des composants déjà testés et fonctionnels.
- **Chaque property test est annoté** par `# Feature: interface-streamlit, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/app/` retrouve les 15 propriétés du design.
- **Dépendances de fichiers respectées** : `stockage_json.py` (tâche 12) précède `annuaire_employes.py`/`annuaire_coordonnees.py` (tâches 13, 14, qui le réutilisent) ; `dernieres_paies.py` (tâche 15) précède `tableau_de_bord.py` et `fiche_employe_detaillee.py` (tâches 22, 23, qui l'invoquent pour les résumés de paies et la dernière année).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1", "6.1", "7.1", "8.1", "9.1", "10.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.2", "5.2", "6.2", "7.2", "8.2", "10.2"] },
    { "id": 3, "tasks": ["3.3", "5.3", "6.3", "7.3", "8.3", "10.3"] },
    { "id": 4, "tasks": ["5.4", "7.4", "10.4"] },
    { "id": 5, "tasks": ["7.5"] },
    { "id": 6, "tasks": ["12.1", "16.1", "19.1"] },
    { "id": 7, "tasks": ["13.1", "14.1"] },
    { "id": 8, "tasks": ["15.1"] },
    { "id": 9, "tasks": ["15.2"] },
    { "id": 10, "tasks": ["17.1"] },
    { "id": 11, "tasks": ["17.2", "18.1"] },
    { "id": 12, "tasks": ["18.2"] },
    { "id": 13, "tasks": ["21.1", "21.2"] },
    { "id": 14, "tasks": ["22.1", "23.1", "24.1", "25.1"] },
    { "id": 15, "tasks": ["26.1"] }
  ]
}
```
