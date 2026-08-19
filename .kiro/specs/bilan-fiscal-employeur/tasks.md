# Implementation Plan: bilan-fiscal-employeur

<!-- Plan d'implémentation — section « Bilan fiscal » du Tableau_De_Bord.
     Les en-têtes structurels (Overview, Tasks) sont maintenus en anglais
     pour conformité au format Kiro. Le contenu métier est en français. -->

## Overview

Cette spec ajoute une nouvelle section « Bilan fiscal » au Tableau_De_Bord
(`app/pages_ui/tableau_de_bord.py`), sans modifier `payroll_engine/` ni
`models/` — une pure couche d'agrégation et de rendu, cohérente avec le
style de `app/logique_metier/dernieres_paies.py` (décision n° 5,
`interface-streamlit`).

**Livrables** :

- `app/logique_metier/bilan_fiscal.py` (nouveau module — logique pure +
  lecture SQL directe)
- `app/pages_ui/tableau_de_bord.py` (modifié — nouvelle fonction
  `_afficher_bilan_fiscal`, appelée depuis `render()`)
- `tests/app/strategies.py` (extension — `st_payroll_result_arbitraire`,
  `st_periode_fiscale`, `st_cellule_montant_ou_indisponible`)
- `tests/app/logique_metier/test_bilan_fiscal.py` (nouveau — property
  tests, tests d'exemple, test de garde structurel)

**Discipline règle 06 (TDD)** : chaque section de tests (2 à 8) est
rédigée et vérifiée **rouge** (échec par `ModuleNotFoundError` sur
`app.logique_metier.bilan_fiscal`, import local dans chaque test — même
patron que `test_dernieres_paies.py`) avant le checkpoint de la section 9,
qui précède l'implémentation du module (section 10) et du rendu (section
11).

**Cadre normatif appliqué à chaque tâche** :

- Règle 01 — tout montant reste un `Decimal` de la désérialisation à
  l'affichage, jamais converti en `float`
- Règle 02 — aucune nouvelle `CalculationTrace` ni formule fiscale ;
  uniquement de l'agrégation de montants déjà calculés (vérifié par le
  test de garde structurel, tâche 8.1)
- Règle 04 — aucune donnée personnelle affichée ; tests avec identifiants
  fictifs `EMPnnn` uniquement, jamais la base de production
- Décision n° 5 (`interface-streamlit`) — lecture SQL directe,
  `sqlite3.OperationalError` (« no such table ») traduite en absence de
  données, jamais de fonction privée de `payroll_engine.register`

## Tasks

- [x] 1. Préparer les stratégies Hypothesis dédiées à `bilan-fiscal-employeur`
  - [x] 1.1 Étendre `tests/app/strategies.py`
    - Ajouter `st_payroll_result_arbitraire(*, statut=None, date_paiement=None)`
      — variante généralisée de `_st_payroll_result_pour_registre`
      (`tests/strategies.py`), acceptant un `statut: StatutDePaie |
      SearchStrategy[StatutDePaie] | None` et une `date_paiement: date |
      SearchStrategy[date] | None` arbitraires en plus des champs déjà
      randomisés (montants de `RetenuesEmploye`/`CotisationsEmployeur`,
      `cnesst_en_attente_classification`) ; documenter la réutilisation
      directe des helpers internes existants (`_st_montant_registre`,
      `_st_decimal_monetaire`), sans duplication
    - Ajouter `st_periode_fiscale()` — génère une `PeriodeFiscale`
      arbitraire (`mois=None` pour Annee_Complete, ou `mois` ∈ `[1, 12]`
      pour Mois_Fiscal), important localement le type cible (le module
      n'existe pas encore, règle 06)
    - Ajouter `st_cellule_montant_ou_indisponible()` —
      `st.one_of(st.none(), _st_decimal_monetaire())`, pour la Property 10
      testée en isolation
    - Chaque nouvelle stratégie documentée par un docstring citant le
      design §Testing Strategy « Stratégies Hypothesis nécessaires »
    - _Requirements: 2.2, 3.1, 7.1_
    - _Design: §Testing Strategy « Stratégies Hypothesis nécessaires »_

- [x] 2. Property tests — Mois_De_Rattachement et options du Selecteur_De_Periode
  - [x] 2.1 Créer le squelette de `tests/app/logique_metier/test_bilan_fiscal.py` et le test de la Property 1
    - Module docstring citant le design §Components §1, les Properties 1
      à 14, écrit avant `app/logique_metier/bilan_fiscal.py` (règle 06) ;
      import local de chaque symbole du module sous test au sein de
      chaque test (collecte pytest réussie malgré l'absence du module)
    - **Property 1 : Détermination du Mois_De_Rattachement et exactitude
      des options générées** — pour tout ensemble de `PayrollResult`
      `EMISE` (`date_paiement` arbitraires), l'ensemble des
      `OptionPeriode` produit par `construire_options_periode` correspond
      exactement à l'ensemble des années et couples (mois, année) présents
      dans `date_paiement`
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 1: Détermination du Mois_De_Rattachement et exactitude des options générées`
    - _Requirements: 2.2, 2.3, 2.4_
    - _Design: §Components §1 ; §Correctness Properties 1_

  - [x] 2.2 Test de la Property 2 (classe `TestFormatageLibelles`)
    - **Property 2 : Formatage des libellés d'options** — pour toute
      année et tout mois (1 à 12), `formater_option_annee_complete` et
      `formater_option_mois_fiscal` produisent exactement les libellés
      imposés, avec les 12 noms de mois français exacts (orthographe et
      casse, y compris Février/Août/Décembre accentués)
    - Test d'exemple complémentaire `test_exemple_douze_mois_formates_avec_orthographe_exacte`
      vérifiant littéralement les 12 libellés
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 2: Formatage des libellés d'options`
    - _Requirements: 2.5, 2.6_
    - _Design: §Components §1 ; §Correctness Properties 2_

  - [x] 2.3 Test de la Property 3 (classe `TestOrdreOptions`)
    - **Property 3 : Ordre des options du Selecteur_De_Periode** — pour
      tout ensemble arbitraire d'années et de couples (mois, année), les
      options sont ordonnées par année décroissante, Annee_Complete avant
      les Mois_Fiscal (croissants) de chaque année
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 3: Ordre des options du Selecteur_De_Periode`
    - _Requirements: 2.7_
    - _Design: §Components §1 ; §Correctness Properties 3_

- [x] 3. Property tests — présélection par défaut et persistance du choix manuel
  - [x] 3.1 Test de la Property 4 (classe `TestPeriodeParDefaut`)
    - **Property 4 : Présélection par défaut de la période** — pour toute
      date arbitraire et tout ensemble d'options disponibles, vérifie les
      trois branches (`jour <= 15` → mois précédent ; `jour >= 16` → mois
      courant ; mois cible absent des options → Mois_Fiscal le plus
      récent disponible)
    - Tests d'exemple complémentaires `test_exemple_frontiere_jour_15_cible_mois_precedent`
      et `test_exemple_frontiere_jour_16_cible_mois_courant`
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 4: Présélection par défaut de la période`
    - _Requirements: 3.1, 3.2, 3.3_
    - _Design: §Components §2 ; §Correctness Properties 4_

  - [x] 3.2 Test de la Property 5 (classe `TestPersistanceChoixManuel`)
    - **Property 5 : Persistance du choix manuel de l'opérateur** — pour
      toute séquence d'appels à `resoudre_periode_a_afficher` simulant
      plusieurs réaffichages, une fois un libellé résolu et toujours
      disponible, il n'est jamais remplacé par un nouveau calcul de
      présélection, même si `periode_par_defaut` change entre deux appels
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 5: Persistance du choix manuel de l'opérateur`
    - _Requirements: 3.4_
    - _Design: §Components §2 ; §Correctness Properties 5_

- [x] 4. Property test — absence totale de Paie_Agregee
  - [x] 4.1 Test de la Property 6 (classe `TestAbsenceTotalePaieAgregee`)
    - **Property 6 : Détection de l'absence totale de Paie_Agregee** —
      pour tout ensemble de paies sans aucun statut `EMISE`, la lecture
      retourne un tuple vide ; pour tout tuple vide en entrée de
      `construire_options_periode`, le résultat est un tuple vide
      d'options — même comportement quelle que soit la cause (aucun
      employé, aucune paie, uniquement des statuts non-`EMISE`)
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 6: Détection de l'absence totale de Paie_Agregee`
    - _Requirements: 1.2, 4.1_
    - _Design: §Components §5 ; §Correctness Properties 6_

- [x] 5. Property tests — agrégation des lignes du Tableau_Bilan_Fiscal
  - [x] 5.1 Test de la Property 7 (classe `TestRepartitionQcCaSensUnique`)
    - **Property 7 : Répartition QC/CA à sens unique des lignes
      mono-juridictionnelles** — pour tout ensemble arbitraire de
      `PayrollResult`, chacune des neuf lignes mono-juridictionnelles a sa
      colonne de juridiction attribuée égale à la somme exacte des
      montants sources correspondants, arrondie à deux décimales, et
      l'autre colonne explicitement à zéro — y compris pour un ensemble
      vide
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 7: Répartition QC/CA à sens unique des lignes mono-juridictionnelles`
    - _Requirements: 6.2, 6.3, 6.4, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_
    - _Design: §Components §4 ; §Correctness Properties 7_

  - [x] 5.2 Test de la Property 8 (classe `TestLigneImpotExclusionFormule`)
    - **Property 8 : Ligne Impôt et exclusion des montants formule** —
      pour tout ensemble arbitraire de `PayrollResult` (y compris des cas
      d'exonération où `*_formule` diffère de `*_retenu`), la ligne Impôt
      utilise exclusivement `impot_qc_retenu`/`impot_federal_retenu` ;
      `impot_qc_formule`/`impot_federal_formule` n'influencent jamais
      aucune somme du tableau
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 8: Ligne Impôt et exclusion des montants formule`
    - _Requirements: 6.5, 6.6_
    - _Design: §Components §4 ; §Correctness Properties 8_

  - [x] 5.3 Test de la Property 9 (classe `TestAgregationDrapeauCnesst`)
    - **Property 9 : Agrégation du drapeau CNESST en attente de
      classification** — pour tout ensemble arbitraire de `PayrollResult`
      avec drapeau `cnesst_en_attente_classification` arbitraire, le
      drapeau agrégé égale le OU logique sur l'ensemble (faux pour
      l'ensemble vide)
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 9: Agrégation du drapeau CNESST en attente de classification`
    - _Requirements: 8.8_
    - _Design: §Components §4 ; §Correctness Properties 9_

- [x] 6. Property test — calcul générique des totaux
  - [x] 6.1 Test de la Property 10 (classe `TestCalculerTotal`)
    - **Property 10 : Calcul générique des lignes de total avec
      propagation de l'indisponibilité** — pour toute séquence arbitraire
      de cellules `Decimal | None`, `calculer_total` retourne `None` si
      toutes sont `None`, sinon la somme exacte des valeurs non `None`
      (chaque `None` individuel comptant comme zéro)
    - Test isolé, sans passer par le pipeline complet (utilise
      `st_cellule_montant_ou_indisponible` de la tâche 1.1)
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 10: Calcul générique des lignes de total avec propagation de l'indisponibilité`
    - _Requirements: 7.1, 7.2, 7.3, 9.1, 9.2, 9.3, 9.4_
    - _Design: §Components §4 ; §Correctness Properties 10_

- [x] 7. Property tests — filtrage par période et lecture SQL
  - [x] 7.1 Test de la Property 11 (classe `TestFiltrageParPeriode`)
    - **Property 11 : Filtrage exact des Paies_Agregees par
      Periode_Fiscale** — pour tout ensemble arbitraire de `PayrollResult`
      `EMISE` et toute `PeriodeFiscale`, `filtrer_paies_par_periode`
      retourne exactement le sous-ensemble correspondant (Mois_Fiscal ou
      Annee_Complete), y compris le tuple vide
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 11: Filtrage exact des Paies_Agregees par Periode_Fiscale`
    - _Requirements: 10.1, 10.2_
    - _Design: §Components §3 ; §Correctness Properties 11_

  - [x] 7.2 Test de la Property 12 (classe `TestLirePaiesEmises`, intégration légère SQLite)
    - **Property 12 : La lecture SQL n'agrège que les paies de statut
      EMISE** — pour tout mélange arbitraire de statuts insérés dans une
      base SQLite temporaire (`st_chemin_bd_temporaire`, `inserer_paie`),
      `lire_paies_emises` retourne exactement l'ensemble des `PayrollResult`
      de statut `EMISE`, y compris tuple vide et base neuve sans table
      `paies` (test d'exemple `test_exemple_base_memoire_neuve_sans_table_paies_retourne_tuple_vide`)
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 12: La lecture SQL n'agrège que les paies de statut EMISE`
    - _Requirements: 10.3_
    - _Design: §Components §5 ; §Correctness Properties 12 ; décision n° 5_

  - [x] 7.3 Test de la Property 13 (classe `TestPreservationDecimal`)
    - **Property 13 : Préservation stricte du type Decimal de bout en
      bout** — pour tout ensemble arbitraire de `PayrollResult` insérés
      dans une base SQLite temporaire, chaque cellule numérique non `None`
      produite par le pipeline complet (lecture → filtrage → agrégation)
      est de type `decimal.Decimal` exactement
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 13: Préservation stricte du type Decimal de bout en bout`
    - _Requirements: 11.2_
    - _Design: §Components §5 ; §Correctness Properties 13_

  - [x] 7.4 Test de la Property 14 (classe `TestEchecDeserialisation`)
    - **Property 14 : Interruption de l'agrégation sur échec de
      désérialisation** — pour toute base SQLite temporaire contenant une
      ligne `EMISE` de `payload_json` invalide, `lire_paies_emises` lève
      une exception (`json.JSONDecodeError` ou `pydantic.ValidationError`)
      plutôt que de retourner un résultat partiel
    - Tests d'exemple complémentaires pour les deux sous-cas explicites :
      `test_exemple_payload_json_syntaxiquement_invalide_leve_json_decode_error`
      et `test_exemple_payload_json_valide_mais_non_conforme_leve_validation_error`
    - Test d'exemple `test_exemple_executer_avec_capture_transforme_echec_deserialisation_en_erreur_affichable`
      vérifiant la propagation jusqu'à `executer_avec_capture` sans
      capture locale intermédiaire
    - Annotation : `# Feature: bilan-fiscal-employeur, Property 14: Interruption de l'agrégation sur échec de désérialisation`
    - _Requirements: 11.3_
    - _Design: §Components §5 ; §Correctness Properties 14 ; §Error Handling_

- [x] 8. Test de garde structurel et checkpoint rouge
  - [x] 8.1 Test de garde structurel (classe `TestAucunImportInterditPayrollEngine`)
    - Inspection `ast` de `app/logique_metier/bilan_fiscal.py` confirmant
      qu'aucune fonction de `payroll_engine/` autre que
      `chemin_bd_production` n'est importée (règle 02, Requirement 11.1),
      même patron que l'inspection existante de `dernieres_paies.py`
    - _Requirements: 11.1_
    - _Design: §Testing Strategy « Test de garde structurel »_

  - [x] 8.2 Checkpoint — confirmer l'état rouge de toute la suite
    - Exécuter `pytest tests/app/logique_metier/test_bilan_fiscal.py` et
      confirmer que chaque test échoue par `ModuleNotFoundError` (ou
      erreur d'import équivalente) sur `app.logique_metier.bilan_fiscal` —
      jamais une erreur d'assertion ou une erreur de syntaxe du fichier de
      test lui-même
    - _Requirements: (aucun — discipline règle 06)_
    - _Design: (aucun — discipline de processus)_

- [x] 9. Implémenter `app/logique_metier/bilan_fiscal.py`
  - [x] 9.1 Types de données et fonctions de formatage/options
    - Implémenter `PeriodeFiscale`, `OptionPeriode`,
      `mois_annee_rattachement`, `formater_option_annee_complete`,
      `formater_option_mois_fiscal`, `construire_options_periode`
      (Properties 1, 2, 3)
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_
    - _Design: §Components §1_

  - [x] 9.2 Présélection par défaut et persistance du choix manuel
    - Implémenter `determiner_periode_par_defaut`,
      `resoudre_periode_a_afficher` (Properties 4, 5)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
    - _Design: §Components §2_

  - [x] 9.3 Filtrage par Periode_Fiscale
    - Implémenter `filtrer_paies_par_periode` (Property 11)
    - _Requirements: 10.1, 10.2, 10.3_
    - _Design: §Components §3_

  - [x] 9.4 Agrégation — `LigneBilan`, `calculer_total`, `TableauBilanFiscal`, `construire_tableau_bilan_fiscal`
    - Implémenter les structures de données et
      `construire_tableau_bilan_fiscal` (Properties 6, 7, 8, 9, 10)
    - _Requirements: 1.2, 4.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 9.1, 9.2, 9.3, 9.4, 11.1_
    - _Design: §Components §4_

  - [x] 9.5 Lecture SQL directe — `lire_paies_emises`
    - Implémenter `lire_paies_emises`, avec traduction de
      `sqlite3.OperationalError` (« no such table ») en tuple vide et
      propagation intacte des échecs de désérialisation (Properties 12,
      13, 14)
    - _Requirements: 10.3, 11.1, 11.2, 11.3_
    - _Design: §Components §5 ; décision n° 5_

  - [x] 9.6 Checkpoint — confirmer l'état vert de la suite de tests du module
    - Exécuter `pytest tests/app/logique_metier/test_bilan_fiscal.py` et
      confirmer que tous les tests (property, exemple, garde structurel)
      passent
    - _Requirements: (aucun — discipline règle 06)_
    - _Design: (aucun — discipline de processus)_

- [x] 10. Intégrer le rendu dans `app/pages_ui/tableau_de_bord.py`
  - [x] 10.1 Ajouter `_afficher_bilan_fiscal` et le CSS scoped `bilan-fiscal-*`
    - Ajouter le bloc CSS (classes `bilan-fiscal-*`, même convention que
      `bulletin_paie.py::_CSS_BULLETIN`) et la fonction `_afficher_bilan_fiscal`
      — orchestre `lire_paies_emises`/`construire_tableau_bilan_fiscal` via
      `executer_avec_capture`, message d'absence (Requirement 4.1),
      `st.selectbox` en haut à droite lié à
      `st.session_state["bilan_fiscal_periode_libelle"]`, rendu HTML/CSS du
      Tableau_Bilan_Fiscal (en-têtes de section fusionnées, cellule
      « Grand total combiné » fusionnée)
    - _Requirements: 1.1, 2.1, 5.1, 5.2, 6.1, 8.1, 9.2, 9.3_
    - _Design: §Architecture décisions 3, 4 ; §Components « `_afficher_bilan_fiscal` »_

  - [x] 10.2 Appeler `_afficher_bilan_fiscal` depuis `render()`
    - Insérer l'appel entre `_afficher_liste_employes(employes)` et le
      `st.divider()` précédant le bouton « Ajouter un nouvel employé »,
      avec son propre `st.divider()`
    - _Requirements: 1.1, 1.2_
    - _Design: §Architecture décision n° 4_

- [x] 11. Validation finale
  - [x] 11.1 Exécuter la suite complète et le profil Hypothesis `ci`
    - `HYPOTHESIS_PROFILE=ci pytest tests/app/logique_metier/test_bilan_fiscal.py tests/app/test_guards.py`
      — confirmer 100+ itérations par propriété et absence de régression
      sur les tests de garde existants (aucun import `streamlit` sous
      `app/logique_metier/`)
    - _Requirements: (validation transverse de toutes les properties 1 à 14)_
    - _Design: §Testing Strategy_

  - [x] ~~11.2 Vérification manuelle de non-régression du Tableau_De_Bord~~
    - **Retirée à la demande de l'utilisateur** — validation visuelle
      effectuée manuellement par l'utilisateur lui-même plutôt que par
      l'agent.

## Notes

- **Aucune tâche marquée `*`** : la règle 06 du projet impose que les property tests, tests d'exemple et tests de garde soient rédigés **avant** l'implémentation — discipline TDD stricte alignée avec les specs précédentes (`interface-streamlit`, `net-cumuls-registre`).
- **Ordre spec → tests → implémentation → validation** : sections 1 à 8 (stratégies, property tests, test de garde) précèdent le checkpoint rouge de la tâche 8.2, qui précède l'implémentation du module (section 9) et son propre checkpoint vert (tâche 9.6), avant l'intégration au rendu (section 10) et la validation finale (section 11).
- **Nouveau module plutôt qu'extension de `dernieres_paies.py`** (design §Architecture décision n° 1) : le Bilan_Fiscal agrège tous les employés confondus, une portée incompatible avec la portée par-employé de `dernieres_paies.py` — `app/logique_metier/bilan_fiscal.py` est un fichier neuf, dans le même style (décision n° 5).
- **Aucune modification de `payroll_engine/` ni `models/`** : toutes les tâches sont scopées à `app/logique_metier/bilan_fiscal.py`, `app/pages_ui/tableau_de_bord.py`, et à leurs tests — cohérent avec le hors périmètre explicite des requirements.
- **Chaque property test est annoté** par `# Feature: bilan-fiscal-employeur, Property N: <titre>` et référence les exigences EARS qu'il valide (`Requirements X.Y`). Un `grep -rn "Property [0-9]" tests/app/logique_metier/test_bilan_fiscal.py` retrouve les 14 propriétés du design.
- **`app/pages_ui/tableau_de_bord.py::_afficher_bilan_fiscal` n'est couvert par aucune property-based test** (cohérent avec `design.md` §Testing Strategy et la pratique déjà établie pour `app/pages_ui/**`) : validation par lecture de code, le contenu métier sous-jacent étant déjà entièrement validé par les tâches 2 à 9. La vérification visuelle manuelle (anciennement tâche 11.2) a été retirée du plan à la demande de l'utilisateur, qui l'effectue lui-même.
- **Dépendance de fichier respectée** : `app/logique_metier/bilan_fiscal.py` (tâche 9) précède son intégration dans `app/pages_ui/tableau_de_bord.py` (tâche 10), qui l'invoque exclusivement via `executer_avec_capture`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "4.1", "6.1", "7.2"] },
    { "id": 2, "tasks": ["2.2", "3.1", "5.1", "7.1", "7.3"] },
    { "id": 3, "tasks": ["2.3", "3.2", "5.2", "7.4"] },
    { "id": 4, "tasks": ["5.3"] },
    { "id": 5, "tasks": ["8.1"] },
    { "id": 6, "tasks": ["8.2"] },
    { "id": 7, "tasks": ["9.1"] },
    { "id": 8, "tasks": ["9.2", "9.3"] },
    { "id": 9, "tasks": ["9.4"] },
    { "id": 10, "tasks": ["9.5"] },
    { "id": 11, "tasks": ["9.6"] },
    { "id": 12, "tasks": ["10.1"] },
    { "id": 13, "tasks": ["10.2"] },
    { "id": 14, "tasks": ["11.1"] }
  ]
}
```
