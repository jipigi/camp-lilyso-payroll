# Implementation Plan: formulaire-paie-suppression-et-ux

## Overview

Cette fonctionnalité corrige le format d'affichage du sélecteur d'employé
du Formulaire_Paie, ajoute deux actions destructives contrôlées
(suppression physique d'un `BROUILLON`, annulation d'une paie `EMISE`
sans jamais la supprimer physiquement) et change la présélection par
défaut du `Radio_Statut_Correction` vers `EMISE`. Aucune formule fiscale
n'est modifiée (règles 01/02/03/05 hors périmètre de ce plan — aucun
`Decimal` fiscal nouveau, aucune trace de calcul, aucun paramètre
annuel touché) ; seule la couche de persistance (`payroll_engine/
register.py`) et la couche de rendu (`app/pages_ui/**`,
`app/logique_metier/annuaire_coordonnees.py`) sont concernées. Les
exemples de test utilisent exclusivement des identifiants fictifs
(`EMP001`, `EMP002`, etc.), conformément à la règle 04.

L'implémentation suit l'ordre : (1) formatage partagé du libellé
employé, (2) fonctions de registre `supprimer_paie_brouillon` et
`annuler_paie` avec leurs garde-fous transactionnels, (3) câblage des
boutons/popups de confirmation dans le Formulaire_Paie et le
Bulletin_De_Paie, (4) présélection du statut EMISE. Chaque étape
s'appuie sur le patron transactionnel déjà en place (`_connexion`,
`_lire_cumuls_ytd_tx`, `_soustraire_contribution`, `_upsert_cumuls_ytd`)
utilisé par `inserer_paie`/`remplacer_paie`, sans nouvelle dépendance.

## Tasks

- [x] 1. Extraire et partager le formatage du libellé employé
  - [x] 1.1 Implémenter `libelle_employe` dans `annuaire_coordonnees.py`
    - Fonction pure publique `libelle_employe(employe_id, coordonnees_par_employe_id)`, extraite de l'actuelle closure `_libelle_employe` de `fiche_employe_detaillee.py`, sans changement de comportement
    - Respecte l'ordre de repli : aucune fiche → `employe_id` ; prénom/nom absents → `employe_id` ; prénom/nom sans courriel → `"Prénom Nom"` ; cas complet → `"Prénom Nom (courriel)"`
    - Aucune E/S, aucun import `streamlit` dans ce module
    - _Requirements: 2.1, 2.3, 1.1, 1.2, 1.3_

  - [x]* 1.2 Écrire le test de propriété pour `libelle_employe`
    - **Property 1: Règles de repli exhaustives de `libelle_employe`**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

  - [x]* 1.3 Écrire les tests unitaires des quatre cas de repli de `libelle_employe`
    - Cas : aucune fiche, fiche sans prénom/nom, prénom/nom sans courriel, cas complet
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.4 Faire réutiliser `libelle_employe` par `fiche_employe_detaillee.py`
    - Retirer la closure locale `_libelle_employe` de `render()` ; le `format_func` du `st.selectbox("Employé", ...)` appelle désormais `libelle_employe(...)` importée d'`annuaire_coordonnees.py`
    - Comportement d'affichage strictement identique (aucune régression visuelle)
    - _Requirements: 2.2_

- [x] 2. Reformater le sélecteur d'employé du Formulaire_Paie
  - [x] 2.1 Mettre à jour `_section_nouvelle_paie` (`formulaire_paie.py`)
    - Ajouter un seul appel groupé à `lister_coordonnees()` (via `executer_avec_capture`) construisant `coordonnees_par_employe_id`, jamais un appel par option affichée
    - `format_func` du `st.selectbox("Employé", ...)` appelle `libelle_employe(eid, coordonnees_par_employe_id)`
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [x]* 2.2 Écrire le test unitaire de cohérence du libellé entre écrans
    - Vérifie que, pour un même `employe_id` et les mêmes `FicheCoordonnees`, le libellé affiché par le Selecteur_Employe_Formulaire est strictement identique à celui de la Fiche_Employe_Detaillee
    - _Requirements: 1.4_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implémenter `supprimer_paie_brouillon` dans le Registre
  - [x] 4.1 Ajouter `supprimer_paie_brouillon` à `payroll_engine/register.py`
    - Transaction atomique (`_connexion`) : lecture + contrôle du statut (`KeyError` si `id_paie` absent, `ValueError` explicite citant le statut courant si ≠ `BROUILLON`), puis `DELETE FROM paies WHERE id_paie = ?`
    - Aucune mise à jour de `cumuls_ytd` (un `BROUILLON` n'y contribue jamais)
    - Ajouter `"supprimer_paie_brouillon"` à `__all__`
    - _Requirements: 3.4, 3.6, 3.7, 3.8_

  - [x]* 4.2 Écrire le test de propriété pour la suppression physique et la préservation des cumuls
    - **Property 3: Suppression physique d'une paie `BROUILLON` et préservation des Cumuls_YTD**
    - **Validates: Requirements 3.4, 3.8**

  - [x]* 4.3 Écrire le test de propriété pour le garde-fou de `supprimer_paie_brouillon`
    - **Property 4: Garde-fou de `supprimer_paie_brouillon`**
    - **Validates: Requirements 3.6, 3.7**

  - [x]* 4.4 Écrire les tests unitaires d'exemple pour `supprimer_paie_brouillon`
    - `KeyError` si `id_paie` inconnu ; `ValueError` pour chacun des trois autres statuts (`EMISE`, `ANNULEE`, `REMPLACE_PAR`)
    - _Requirements: 3.6, 3.7_

- [x] 5. Implémenter `annuler_paie` dans le Registre
  - [x] 5.1 Ajouter `annuler_paie` à `payroll_engine/register.py`
    - Transaction atomique (`_connexion`) : lecture + contrôle du statut (`KeyError`/`ValueError` symétriques à `supprimer_paie_brouillon`), mutation `statut → ANNULEE` via `model_copy` (même patron que l'étape 3a de `remplacer_paie`, `date_emission` inchangée), puis décrément de `cumuls_ytd` via `_lire_cumuls_ytd_tx` + `_soustraire_contribution` + `_upsert_cumuls_ytd`
    - Jamais de `DELETE` ; `ROLLBACK` intégral si une étape échoue (statut et cumuls visibles ensemble ou jamais du tout)
    - Ajouter `"annuler_paie"` à `__all__`
    - _Requirements: 4.4, 4.6, 4.7, 4.8, 4.9_

  - [x]* 5.2 Écrire le test de propriété pour la transition vers `ANNULEE` sans suppression physique
    - **Property 8: Annulation transite vers `ANNULEE` sans jamais supprimer physiquement la ligne**
    - **Validates: Requirements 4.4**

  - [x]* 5.3 Écrire le test de propriété pour le décrément exact des Cumuls_YTD
    - **Property 9: Décrément exact des Cumuls_YTD lors de l'annulation**
    - **Validates: Requirements 4.6**

  - [x]* 5.4 Écrire le test de propriété pour le garde-fou de `annuler_paie`
    - **Property 10: Garde-fou de `annuler_paie`**
    - **Validates: Requirements 4.8, 4.9**

  - [x]* 5.5 Écrire les tests unitaires d'exemple pour `annuler_paie`
    - Annulation réussie relit `statut == ANNULEE` et `date_emission` inchangée ; `KeyError` si `id_paie` inconnu ; `ValueError` pour chacun des trois autres statuts ; atomicité du rollback si le décrément échoue
    - _Requirements: 4.4, 4.7, 4.8, 4.9_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Bouton et popup de suppression du brouillon (Formulaire_Paie)
  - [x] 7.1 Ajouter le bouton « Supprimer le brouillon » et le style `_CSS_BOUTON_DANGER`
    - Constante privée `_CSS_BOUTON_DANGER` (fond `#b3261e`, police blanche) ciblant les clés `st-key-fp_supprimer_brouillon*`, avec commentaire documentant explicitement l'écart à la Règle UI 07 (troisième couleur de bouton, hors binaire primaire/secondaire, réservée exclusivement à cette action destructive)
    - Bouton affiché uniquement si la paie chargée dans `_section_nouvelle_paie` est une `Paie_Brouillon` (`id_paie_brouillon_precharge` renseigné ET statut relu `BROUILLON`), positionné à droite du bouton « Assembler la paie » via `st.columns`
    - _Requirements: 3.1, 3.2, 5.1, 5.5_

  - [x] 7.2 Implémenter `_dialogue_confirmation_suppression_brouillon` (`st.dialog`)
    - Titre exact « Supprimer le brouillon ? », texte exact « Vous perdrez les dates et les heures saisies dans ce brouillon de paie. »
    - Bouton « Supprimer le brouillon » (style `Bouton_Danger`) invoquant `supprimer_paie_brouillon` via `executer_avec_capture`, affichage d'erreur via `st.error` en cas d'échec, sinon nettoyage de la clé de pré-remplissage du brouillon et `st.rerun()`
    - Bouton « Annuler » (style secondaire par défaut) fermant la popup sans invoquer `supprimer_paie_brouillon`
    - _Requirements: 3.3, 3.4, 3.5, 3.9_

  - [x]* 7.3 Écrire le test de propriété pour la visibilité conditionnelle du bouton « Supprimer le brouillon »
    - **Property 2: Visibilité conditionnelle du bouton « Supprimer le brouillon »**
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 7.4 Écrire le test de propriété pour l'absence de référence résiduelle après suppression
    - **Property 5: Absence de référence résiduelle après suppression d'un brouillon**
    - **Validates: Requirements 3.9**

  - [x]* 7.5 Écrire les tests unitaires de câblage du dialogue de suppression du brouillon
    - Le bouton « Annuler » ferme la popup sans appeler `supprimer_paie_brouillon` ; une erreur du registre (`ValueError`/`KeyError`) est affichée via `st.error` sans provoquer de `st.rerun()`
    - _Requirements: 3.5, 3.6, 3.7_

- [x] 8. Bouton et popup de suppression de paie émise (Bulletin_De_Paie)
  - [x] 8.1 Ajouter le bouton « Supprimer la paie » et le style `_CSS_BOUTON_DANGER`
    - Constante privée `_CSS_BOUTON_DANGER` dupliquée dans `bulletin_paie.py` (même discipline de duplication de petites constantes que `_LIBELLES_STATUT`), ciblant `st-key-bulletin_supprimer*`, avec commentaire documentant l'écart à la Règle UI 07
    - Barre d'actions étendue à trois colonnes ; bouton affiché à gauche de « Corriger cette paie » uniquement si `paie.statut == StatutDePaie.EMISE`
    - _Requirements: 4.1, 4.2, 5.2, 5.5_

  - [x] 8.2 Implémenter `_dialogue_confirmation_suppression_paie` (`st.dialog`)
    - Titre dynamique exact « Supprimer la paie de {Prénom Nom} ? », texte exact « Cette paie est marquée comme émise, si vous la supprimez, vous perdrez le calcul du salaire et des cotisations. »
    - Bouton « Supprimer la paie de {Prénom Nom} » (style `Bouton_Danger`) invoquant `annuler_paie` via `executer_avec_capture`, affichage d'erreur via `st.error` en cas d'échec, sinon `st.rerun()`
    - Bouton « Annuler » (style secondaire par défaut) fermant la popup sans invoquer `annuler_paie`
    - Après annulation réussie, la paie relue affiche son statut `ANNULEE` sans bouton « Corriger cette paie » ni « Supprimer la paie »
    - _Requirements: 4.3, 4.4, 4.5, 4.10_

  - [x]* 8.3 Écrire le test de propriété pour la visibilité conditionnelle du bouton « Supprimer la paie »
    - **Property 6: Visibilité conditionnelle du bouton « Supprimer la paie »**
    - **Validates: Requirements 4.1, 4.2, 4.10**

  - [x]* 8.4 Écrire le test de propriété pour le titre et le texte dynamiques de la popup
    - **Property 7: Construction dynamique du titre et du texte de la Popup_Confirmation_Paie_Emise**
    - **Validates: Requirements 4.3**

  - [x]* 8.5 Écrire les tests unitaires de câblage du dialogue de suppression de paie émise
    - Le bouton « Annuler » ferme la popup sans appeler `annuler_paie` ; une erreur du registre est affichée via `st.error` sans provoquer de `st.rerun()`
    - _Requirements: 4.5, 4.8, 4.9_

- [x] 9. Présélection du statut EMISE pour la correction d'une paie émise
  - [x] 9.1 Modifier la présélection du `Radio_Statut_Correction` (`formulaire_paie.py`)
    - `st.radio("Statut de la nouvelle version", ["BROUILLON", "EMISE"], index=1, key="fp_corriger_statut_choisi")` dans `_section_corriger_paie`
    - Ne pas modifier `Radio_Statut_Nouvelle_Paie` (`_section_enregistrement`, `cle_prefixe="fp_nouvelle"`), qui reste présélectionné sur `BROUILLON`
    - _Requirements: 6.1, 6.2_

  - [x]* 9.2 Écrire les tests unitaires de présélection des radios de statut
    - Le `Radio_Statut_Correction` du flux « Corriger une paie émise » est présélectionné sur `EMISE` ; le `Radio_Statut_Nouvelle_Paie` du flux « Nouvelle paie » reste présélectionné sur `BROUILLON`
    - _Requirements: 6.1, 6.2_

- [x] 10. Checkpoint final - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Les tâches marquées `*` sont optionnelles et peuvent être ignorées pour un MVP plus rapide, mais restent recommandées pour couvrir les propriétés universelles du design.
- Chaque tâche référence les sous-exigences granulaires du document `requirements.md` pour la traçabilité.
- Les checkpoints valident l'ensemble des tests (unitaires + propriétés) avant de poursuivre.
- Les tests de propriété (Hypothesis, ≥100 itérations, profil CI existant) valident les invariants universels du design ; les tests unitaires valident des exemples concrets et des cas d'erreur.
- Aucune donnée personnelle réelle n'est utilisée dans les tests (règle 04) — identifiants fictifs `EMP001`/`EMP002` uniquement.
- Aucune formule fiscale, aucun paramètre annuel versionné et aucun `Decimal` de calcul de retenue n'est introduit par ce plan (règles 01, 02, 03, 05 non concernées) ; seule l'arithmétique déjà existante de `_soustraire_contribution`/`CumulsYTD` (déjà en `Decimal`) est réutilisée pour `annuler_paie`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "2.1", "4.2", "5.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "4.3", "7.1", "8.1"] },
    { "id": 3, "tasks": ["4.4", "7.2", "8.2"] },
    { "id": 4, "tasks": ["5.2", "7.3", "8.3", "9.1"] },
    { "id": 5, "tasks": ["5.3", "7.4", "8.4"] },
    { "id": 6, "tasks": ["5.4", "7.5", "8.5"] },
    { "id": 7, "tasks": ["5.5", "9.2"] }
  ]
}
```
