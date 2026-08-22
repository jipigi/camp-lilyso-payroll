# Implementation Plan: tableau-de-bord-periode-globale

## Overview

Convertit le design en étapes de code incrémentales, chacune validée par
des tests écrits avant l'implémentation (règle 06) : d'abord les
fonctions pures nouvelles/étendues de `app/logique_metier/**` (chacune
accompagnée de ses property tests Hypothesis, tag `Feature:
tableau-de-bord-periode-globale, Property N: <titre>`), puis le câblage
de rendu dans `app/pages_ui/tableau_de_bord.py` et
`app/pages_ui/formulaire_paie.py`. Aucune tâche de déploiement, de
publication ou d'exécution manuelle de l'application n'est incluse
(hors périmètre d'un agent de code).

Les dix Correctness Properties du design sont couvertes une par une, au
plus près de la fonction pure qu'elles valident. Les critères
d'acceptation 1.6, 1.7, 2.1 et 2.2 (câblage architectural ou déjà
couverts par les property tests existants de `bilan-fiscal-employeur`)
sont couverts par des tests unitaires/d'intégration ciblés plutôt que
par de nouvelles propriétés, conformément au design.

## Tasks

- [x] 1. Étendre `app/logique_metier/bilan_fiscal.py` (Décision 1)
  - Ajouter `construire_options_annee(paies_emises, annee_courante)` et
    `determiner_annee_par_defaut(annee_courante)`, sans modifier ni
    supprimer aucune fonction existante du module
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.1 Implémenter `construire_options_annee` et `determiner_annee_par_defaut`
    - Réutiliser `mois_annee_rattachement` et
      `formater_option_annee_complete` déjà existants, sans duplication
    - Garantir qu'`annee_courante` figure toujours exactement une fois
      dans le résultat, trié par année décroissante, sans jamais
      produire d'option `periode.mois` non `None`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x]* 1.2 Écrire le property test de la Property 1
    - **Property 1: Options d'année exactes et sans doublon**
    - **Validates: Requirements 1.1, 1.2, 1.3**
    - Réutiliser `st_payroll_result_arbitraire` (`tests/app/strategies.py`)

  - [x]* 1.3 Écrire le property test de la Property 2
    - **Property 2: Présélection par défaut toujours disponible**
    - **Validates: Requirements 1.4, 1.5**

  - [x]* 1.4 Écrire les tests unitaires des cas limites de `construire_options_annee`
    - Année courante déjà présente parmi les Annee_Avec_Paie_Emise
      (pas de doublon) ; `paies_emises` vide (une seule option de
      repli)
    - _Requirements: 1.2, 1.3_

- [ ] 2. Étendre `app/logique_metier/dernieres_paies.py` (Décision 7)
  - Ajouter `paies_pour_colonne(resumes, annee)`, sans modifier
    `derniere_paie_creee` ni aucune autre fonction existante
  - _Requirements: 5.2, 5.3, 5.4_

  - [x] 2.1 Implémenter `paies_pour_colonne`
    - Filtrer sur `statut ∈ {BROUILLON, EMISE}` et
      `date.fromisoformat(date_paiement).year == annee`, exclure les
      résumés sans `date_paiement`
    - Trier BROUILLON avant EMISE, chaque groupe par date de paiement
      décroissante puis `numero_periode` croissant
    - _Requirements: 5.2, 5.3, 5.4_

  - [x]* 2.2 Écrire le property test de la Property 6
    - **Property 6: Filtrage et ordre exacts de la Colonne_Paies**
    - **Validates: Requirements 5.2, 5.3, 5.4**
    - Nouvelle stratégie Hypothesis pour `LignePaieResume` (statuts,
      dates de paiement, `numero_periode` arbitraires)

  - [x]* 2.3 Écrire le property test de la Property 7
    - **Property 7: Absence de paie jamais confondue avec une erreur de lecture**
    - **Validates: Requirements 5.6**

- [ ] 3. Checkpoint — Ensure all tests pass, ask the user if questions arise.

- [x] 4. Créer `app/logique_metier/tri_employes.py` (Décision 6, nouveau module)
  - `cle_tri_employe`, `normaliser_pour_tri`, `trier_employes_pour_affichage`
  - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.1 Implémenter le module `tri_employes.py`
    - `cle_tri_employe` : concatène `prenom`/`nom` de la
      `FicheCoordonnees` si présente, sinon `Employee.nom_affichage`
    - `normaliser_pour_tri` : décomposition Unicode NFKD, suppression
      des marques de combinaison, `casefold()` (même technique que
      `models._validators._normaliser_pour_recherche`, sans suppression
      de ponctuation/espaces)
    - `trier_employes_pour_affichage` : trie par clé normalisée
      croissante, `Employee.id` croissant en départage
    - _Requirements: 4.1, 4.2, 4.3_

  - [x]* 4.2 Écrire le property test de la Property 5
    - **Property 5: Tri par Prénom Nom, insensible casse/accents, départagé par id**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Réutiliser `st_employee_valide`, `st_fiche_coordonnees_valide`
      (`tests/app/strategies.py`) ; dictionnaire partiel de fiches
      (certains employés sans fiche)

  - [x]* 4.3 Écrire les tests unitaires des cas limites de tri
    - Deux employés avec la même clé normalisée (départage par `id`) ;
      clé avec accents/casse mixte (ex. « Éloïse » vs « eloise »)
    - _Requirements: 4.2, 4.3_

- [ ] 5. Checkpoint — Ensure all tests pass, ask the user if questions arise.

- [x] 6. Étendre `app/logique_metier/formulaire_paie.py` (Décision 8, fonctions pures)
  - Ajouter `valider_date_paiement_pour_emission` et
    `message_erreur_date_paiement`, sans modifier les fonctions
    existantes du module
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 6.1 Implémenter `valider_date_paiement_pour_emission` et `message_erreur_date_paiement`
    - `valider_date_paiement_pour_emission` : message non `None` si et
      seulement si `date_paiement` absente ou strictement antérieure à
      `date_fin`
    - `message_erreur_date_paiement` : retourne `message_precedent`
      inchangé si `statut_choisi == "BROUILLON"` ; recalcule sinon
      (`statut_choisi == "EMISE"`), sans jamais tenir compte de
      `message_precedent` dans ce second cas
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x]* 6.2 Écrire le property test de la Property 9
    - **Property 9: Validation de la date de paiement à l'émission**
    - **Validates: Requirements 6.1, 6.3**
    - Nouvelle stratégie Hypothesis pour des paires `date_fin`/
      `date_paiement` arbitraires (`date_paiement` incluant `None`)

  - [x]* 6.3 Écrire le property test de la Property 10
    - **Property 10: Non-application et non-effacement du message en BROUILLON**
    - **Validates: Requirements 6.2, 6.4**

- [ ] 7. Checkpoint — Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Restructurer `app/pages_ui/tableau_de_bord.py` (Décisions 2, 3, 4, 5, 9)
  - Sélecteur global résolu une seule fois, retrait de la colonne « No.
    d'employé », tri par Prénom Nom, Colonne_Paies enrichie
  - _Requirements: 1.6, 1.7, 2.1, 2.2, 2.3, 3.1, 3.2, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 8.1 Renommer la clé de session et implémenter `_resoudre_annee_selectionnee`
    - Renommer `_CLE_PERIODE_LIBELLE` en `_CLE_ANNEE_SELECTIONNEE_LIBELLE`
      (`"tdb_annee_selectionnee_libelle"`)
    - Implémenter `_resoudre_annee_selectionnee() -> tuple[tuple[PayrollResult, ...] | None, int]`
      (Décision 2, 4) : affiche le `st.selectbox` (options
      `construire_options_annee`/`determiner_annee_par_defaut`) ou le
      message d'erreur de repli à l'emplacement du sélecteur
    - Retirer l'early-return « Aucune paie émise » de
      `_afficher_bilan_fiscal` (Décision 3)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.2_

  - [x] 8.2 Mettre à jour `render()` et `_afficher_bilan_fiscal`
    - `render()` appelle `_resoudre_annee_selectionnee()` une seule
      fois, en haut de la fonction, avant le rendu de la section
      « Employés » (Req 1.7)
    - `_afficher_bilan_fiscal(paies_emises, periode_selectionnee)` ne
      construit plus son propre sélecteur ; n'est pas rendue si
      `paies_emises is None` (Décision 4)
    - Envelopper « filtrage + construction + génération HTML » dans un
      seul `executer_avec_capture(lambda: ...)` (Décision 5) ; afficher
      `st.error(...)` à la place du tableau en cas d'échec, sans
      interrompre le reste de `render()`
    - _Requirements: 1.7, 2.1, 2.2, 2.3_

  - [x] 8.3 Mettre à jour `_afficher_liste_employes` (tri, colonnes, isolation d'erreur)
    - Signature étendue : `_afficher_liste_employes(employes, *, annee_selectionnee: int)`
    - Retirer `<th>No. d'employé</th>` et la cellule `<td>{employe.id}</td>`
      correspondante (Décision 9), sans modifier l'ordre/le contenu des
      autres colonnes
    - Appeler `lire_coordonnees` par employé pour construire le
      dictionnaire de `FicheCoordonnees`, puis
      `trier_employes_pour_affichage` avant de construire les lignes
    - Renommer l'en-tête « Dernière paie » en « Paies » ; construire la
      Colonne_Paies via `paies_pour_colonne(resumes, annee_selectionnee)`
      (une ligne par paie, séparateur `<br>`, texte d'absence explicite
      si vide, texte d'erreur isolé à la ligne de l'employé concerné en
      cas d'échec de `lire_resumes_paies`)
    - Extraire la construction du bloc `<table>` dans une fonction pure
      dédiée (même patron que `_construire_html_bilan_fiscal`) prenant
      en paramètres les employés déjà triés et le contenu HTML déjà
      résolu de chaque Colonne_Paies, pour rester testable par
      Hypothesis sans dépendance à `streamlit`/aux lectures disque
    - _Requirements: 3.1, 3.2, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x]* 8.4 Écrire le property test de la Property 3
    - **Property 3: Colonne « No. d'employé » absente, colonnes restantes inchangées**
    - **Validates: Requirements 3.1**
    - Créer `tests/app/pages_ui/__init__.py` et
      `tests/app/pages_ui/test_tableau_de_bord.py`

  - [x]* 8.5 Écrire le property test de la Property 4
    - **Property 4: Identifiant employé jamais affiché comme texte visible**
    - **Validates: Requirements 3.2**
    - Inclure des identifiants avec caractères spéciaux d'URL

  - [x]* 8.6 Écrire le property test de la Property 8
    - **Property 8: Isolation des erreurs de lecture par employé**
    - **Validates: Requirements 5.5**
    - Simuler par mock un sous-ensemble arbitraire d'employés dont
      `lire_resumes_paies` échoue

  - [x]* 8.7 Écrire le test unitaire du renommage de colonne
    - Vérifie que l'en-tête affiché est « Paies » (et non « Dernière
      paie »), un seul exemple (Requirement 5.1, non universel)
    - _Requirements: 5.1_

  - [x]* 8.8 Écrire le test unitaire du cas `paies_emises = ()` avec repli
    - Vérifie qu'avec l'Option_Annee_Courante_De_Repli sélectionnée,
      aucune ligne/aucun total du Tableau_Bilan_Fiscal n'affiche
      l'indicateur d'indisponibilité
    - _Requirements: 2.2_

  - [x]* 8.9 Écrire le test unitaire d'isolation d'erreur du Tableau_Bilan_Fiscal
    - Simule une exception lors de la construction/génération HTML du
      tableau ; vérifie que la section Employés reste rendue
    - _Requirements: 2.3_

- [ ] 9. Checkpoint — Ensure all tests pass, ask the user if questions arise.

- [x] 10. Modifier `app/pages_ui/formulaire_paie.py` (Décision 8, câblage)
  - Validation bloquante de la date de paiement à l'émission, lue
    depuis les widgets vifs
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 10.1 Ajouter les paramètres `date_fin`/`date_paiement` à `_section_enregistrement`
    - Nouvelle signature :
      `_section_enregistrement(paie_assemblee, annee_fiscale, *, date_fin: date, date_paiement: date | None, cle_prefixe: str)`
    - Appelle `message_erreur_date_paiement` à chaque rendu ; bloque
      avant `_inserer()` (aucune tentative d'insertion) si
      `statut_choisi == "EMISE"` et que le message retourné n'est pas
      `None`, en affichant ce message via `st.error(...)`
    - Met à jour le site d'appel dans `_section_nouvelle_paie` pour
      transmettre les valeurs vives des widgets `date_fin`/
      `date_paiement`, jamais celles de `paie_assemblee.pay_period`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x]* 10.2 Écrire les tests unitaires du câblage de validation
    - Vérifie que la validation utilise les valeurs vives des widgets
      (et non `paie_assemblee.pay_period.date_paiement`, obsolète après
      modification des widgets sans ré-assemblage) ; vérifie le blocage
      effectif de l'insertion ; vérifie la non-application en
      BROUILLON
    - Créer `tests/app/pages_ui/test_formulaire_paie.py`
    - _Requirements: 6.1, 6.2, 6.4_

- [ ] 11. Checkpoint final — Ensure all tests pass, ask the user if questions arise.

## Notes

- Les tâches marquées `*` sont optionnelles et peuvent être omises pour
  un MVP plus rapide.
- Chaque tâche référence les critères d'acceptation granulaires
  correspondants (`_Requirements: X.Y_`).
- Les property tests utilisent Hypothesis (≥100 itérations en profil CI,
  cf. `tests/conftest.py`) et réutilisent les stratégies existantes de
  `tests/app/strategies.py` (`st_payroll_result_arbitraire`,
  `st_employee_valide`, `st_fiche_coordonnees_valide`) ; les nouvelles
  stratégies nécessaires (`LignePaieResume`, dates du Formulaire_Paie)
  sont ajoutées à ce même fichier au fil des tâches 2.2 et 6.2.
- Aucune tâche de déploiement, de publication ou d'exécution manuelle
  de l'application (`streamlit run ...`) n'est incluse — hors périmètre
  d'un agent de code.
- Aucun nouveau modèle Pydantic ni nouvelle table SQL n'est introduit ;
  toutes les tâches ci-dessus étendent des modules existants ou créent
  un unique nouveau module pur (`tri_employes.py`).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "4.1", "6.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.2", "2.3", "4.2", "4.3", "6.2", "6.3", "8.1", "10.1"] },
    { "id": 2, "tasks": ["8.2"] },
    { "id": 3, "tasks": ["8.3"] },
    { "id": 4, "tasks": ["8.4", "8.5", "8.6", "8.7", "8.8", "8.9", "10.2"] }
  ]
}
```
