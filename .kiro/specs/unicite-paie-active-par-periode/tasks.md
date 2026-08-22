# Implementation Plan

## Overview

Bugfix : invariant « au plus une ligne active par période » (Bug A, `payroll_engine/register.py::inserer_paie`) et libellé de la Colonne_Paies (Bug B, `app/pages_ui/tableau_de_bord.py::_ligne_colonne_paie_html`).

Méthodologie bug condition (observation-first, règle 06) : chaque bug suit l'ordre Exploration (contre-exemples sur le code non corrigé) → Fix → Préservation. Bug A et Bug B sont indépendants entre eux (fichiers, fonctions et tables distincts) et peuvent être exécutés en parallèle après la tâche 1.

## Task Dependency Graph

```
1. Fixtures et helpers de test partagés
   ├─→ 2. [Bug A] Exploration — contre-exemples sur inserer_paie non corrigé
   │      └─→ 3. [Bug A] Fix — invalidation des BROUILLON actifs dans inserer_paie
   │             ├─→ 4. [Bug A] Property-based test — Fix Checking (Property 1)
   │             ├─→ 5. [Bug A] Property-based test — Preservation Checking (Property 3)
   │             └─→ 6. [Bug A] Tests unitaires + garde-fous existants (régression)
   │
   └─→ 7. [Bug B] Exploration — contre-exemples sur _ligne_colonne_paie_html non corrigé
          └─→ 8. [Bug B] Fix — _formater_date_sans_annee + nouveau corps de _ligne_colonne_paie_html
                 ├─→ 9. [Bug B] Property-based test — Fix Checking (Property 2)
                 ├─→ 10. [Bug B] Property-based test — Preservation Checking (Property 4)
                 └─→ 11. [Bug B] Tests unitaires (régression)

12. Intégration et validation finale (dépend de 4, 5, 6, 9, 10, 11)
```

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2, 7] },
    { "wave": 3, "tasks": [3, 8] },
    { "wave": 4, "tasks": [4, 5, 6, 9, 10, 11] },
    { "wave": 5, "tasks": [12] }
  ]
}
``` 

## Tasks

- [x] 1. Fixtures et helpers de test partagés
  - Vérifier que `_payroll_result_valide(*, id_paie, employe_id, annee_fiscale, numero_periode, statut)` (déjà défini dans `tests/payroll_engine/test_register.py`, ligne ~1507) reste réutilisable tel quel pour les nouveaux tests d'exploration/fix/préservation de Bug A — ne pas dupliquer cette factory.
  - Vérifier que `st_ligne_paie_resume_arbitraire()` (déjà défini dans `tests/app/strategies.py`, ligne ~658) couvre bien les statuts `BROUILLON`/`EMISE`, un `numero_periode` (1 à 27) et une `date_paiement` ISO optionnelle — réutiliser cette stratégie pour les tests Bug B plutôt que d'en écrire une nouvelle.
  - Si besoin, ajouter un helper `_lignes_actives(module, employe_id, annee_fiscale, numero_periode, chemin_bd)` dans `tests/payroll_engine/test_register.py` qui appelle `lire_historique_paie` et filtre sur `statut ∈ {BROUILLON, EMISE}` — utilisé par plusieurs tâches suivantes (2, 4, 5, 6) pour éviter la duplication de logique d'assertion.
  - _Requirements: (préparation, ne valide aucun requirement directement)_

- [x] 2. [Bug A] Exploration — contre-exemples sur `inserer_paie` non corrigé
  - Dans `tests/payroll_engine/test_register.py`, ajouter une classe `TestExplorationInvarianceLigneActive` (même patron documenté que `TestExplorationPersistancePayrollInput` déjà présent dans ce fichier — commentaire explicite « NE PAS corriger ces tests ni le code lorsqu'ils échouent »).
  - Test 1 (exemple) : insérer deux `BROUILLON` successifs pour la même Paie_Logique `(EMP001, 2026, 1)` via `inserer_paie`, puis lire `lire_historique_paie` et observer que les DEUX lignes sont actives (`statut ∈ {BROUILLON, EMISE}`) — contre-exemple attendu sur le code non corrigé.
  - Test 2 (exemple) : insérer un `BROUILLON` puis un `EMISE` pour la même Paie_Logique, observer que les deux restent actives simultanément (le `BROUILLON` n'est jamais invalidé).
  - Exécuter ces deux tests sur le code actuel (non corrigé) et confirmer qu'ils échouent bien pour la raison attendue (accumulation, pas une autre erreur) — documente/confirme l'hypothèse de root cause du design.
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 3. [Bug A] Fix — invalidation des `BROUILLON` actifs dans `inserer_paie`
  - Dans `payroll_engine/register.py::inserer_paie`, ajouter le bloc d'invalidation (design §Fix Implementation, Bug A, Changement 1) immédiatement après le garde-fou `EMISE`→`EMISE` existant et avant `_inserer_ligne_paie_tx` — même connexion/curseur `connexion` déjà ouvert par `_connexion(chemin_bd)`.
  - Le bloc doit : sélectionner toutes les lignes `paies` de statut `BROUILLON` pour `(employe_id, annee_fiscale, numero_periode)`, et pour chacune, exécuter `UPDATE paies SET statut = 'remplace_par', remplace_par_id = ?, payload_json = ? WHERE id_paie = ?` avec `payload_json` reconstruit via `PayrollResult.model_validate_json(...).model_copy(update={"statut": REMPLACE_PAR, "remplace_par_id": resultat.id_paie})` — reproduisant exactement le modèle de mutation de l'étape 3a de `remplacer_paie`.
  - Ne jamais muter `payload_input_json` dans ce bloc.
  - Ne modifier ni la signature de `inserer_paie`, ni `_inserer_ligne_paie_tx`, ni `_connexion`, ni `remplacer_paie`, ni aucun fichier de `app/pages_ui/formulaire_paie.py`.
  - Exécuter les tests de la tâche 2 : ils doivent maintenant passer (le fix corrige les contre-exemples).
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 4. [Bug A] Property-based test — Fix Checking (Property 1)
  - PBT task.
  - Dans `tests/payroll_engine/test_register.py`, écrire un test Hypothesis qui génère une séquence d'insertions (`BROUILLON`/`BROUILLON`, `BROUILLON`/`EMISE`, ou plusieurs `BROUILLON` successifs) pour une même Paie_Logique, appelle `inserer_paie` pour chacune dans l'ordre, puis vérifie qu'après chaque insertion il existe au plus une ligne active (`statut ∈ {BROUILLON, EMISE}`) et que toute ligne devenue inactive porte `statut = REMPLACE_PAR` avec `remplace_par_id` égal à l'`id_paie` de l'insertion suivante.
  - Exclure de la génération les séquences qui déclencheraient le garde-fou `EMISE`→`EMISE` existant (deux `EMISE` consécutifs sans `BROUILLON` intermédiaire) — cette combinaison est couverte par la tâche 6, pas par cette property.
  - Référencer explicitement "Feature: unicite-paie-active-par-periode, Property 1: Bug Condition - Invariant au plus une ligne active par période" en commentaire au-dessus du test (convention déjà utilisée dans ce fichier).
  - Exécuter le test via la commande pytest du projet et corriger jusqu'à ce qu'il passe.
  - _Requirements: 2.1, 2.2_

- [x] 5. [Bug A] Property-based test — Preservation Checking (Property 3)
  - PBT task.
  - Dans `tests/payroll_engine/test_register.py`, écrire un test Hypothesis qui génère des insertions où `isBugCondition_InvarianceActive` est fausse (Paie_Logiques toutes distinctes, ou première insertion d'une Paie_Logique sans ligne active préexistante), et vérifie que le comportement (aucune ligne mutée hors la ligne insérée, `cumuls_ytd` identique à un calcul manuel, aucune exception inattendue) est strictement identique à celui du code d'avant ce bugfix.
  - Inclure un cas couvrant explicitement `test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee` sous forme de propriété généralisée (BROUILLON après EMISE actif, sans BROUILLON actif préexistant) — vérifier qu'aucune mutation de la ligne EMISE n'a lieu.
  - Référencer "Feature: unicite-paie-active-par-periode, Property 3: Preservation - Flux et garde-fous existants du registre" en commentaire.
  - Exécuter le test et corriger jusqu'à ce qu'il passe.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 6. [Bug A] Tests unitaires + garde-fous existants (régression)
  - Exécuter `TestRefusDoubleEmisePourMemePeriode` (existant, `tests/payroll_engine/test_register.py`) sans aucune modification — confirmer qu'il passe toujours après le fix de la tâche 3 (Req 3.1).
  - Ajouter un test unitaire d'exemple : insertion d'un `EMISE` alors qu'un `BROUILLON` actif existe déjà pour la même Paie_Logique → vérifier que l'ancien `BROUILLON` passe à `REMPLACE_PAR`, que `remplace_par_id` pointe vers le nouvel `id_paie`, et que `lire_cumuls_ytd` reflète uniquement la contribution du nouvel `EMISE` (jamais celle du `BROUILLON`, Req 3.4).
  - Ajouter un test unitaire d'exemple pour le cas d'auto-réparation : plusieurs `BROUILLON` actifs déjà présents en base (simulant une base ayant accumulé le bug avant correction) puis une nouvelle insertion → toutes les anciennes lignes `BROUILLON` doivent passer à `REMPLACE_PAR`.
  - Exécuter toute la suite `tests/payroll_engine/test_register.py` et confirmer l'absence de régression.
  - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 7. [Bug B] Exploration — contre-exemples sur `_ligne_colonne_paie_html` non corrigé
  - Dans `tests/app/pages_ui/test_tableau_de_bord.py`, ajouter une classe `TestExplorationLibelleColonnePaies` import ant directement `_ligne_colonne_paie_html` depuis `app.pages_ui.tableau_de_bord`.
  - Test 1 (exemple) : construire un `LignePaieResume` `EMISE` avec `date_paiement="2026-07-29"` et `numero_periode=1`, appeler `_ligne_colonne_paie_html`, observer sur le code non corrigé que le texte produit contient l'année (`"2026"`) et ne contient pas `"Paie #1"`.
  - Test 2 (exemple) : construire un `LignePaieResume` `BROUILLON`, observer sur le code non corrigé que le texte produit contient une date (alors qu'un brouillon ne devrait jamais en afficher).
  - Confirmer que ces deux tests échouent sur le code actuel pour la raison attendue (format redondant/incomplet), avant d'implémenter le fix.
  - _Requirements: 1.4, 1.5_

- [x] 8. [Bug B] Fix — `_formater_date_sans_annee` + nouveau corps de `_ligne_colonne_paie_html`
  - Dans `app/pages_ui/tableau_de_bord.py`, ajouter la fonction `_formater_date_sans_annee(valeur_iso: str) -> str` juste après `_formater_date_courte` (design §Fix Implementation, Bug B, Changement 1) — réutilise `_NOMS_MOIS_MINUSCULES`, jamais d'année dans la sortie.
  - Remplacer le corps de `_ligne_colonne_paie_html` par la nouvelle logique (design §Fix Implementation, Bug B, Changement 2) : `"Paie #{numero_periode} - déposée le {date sans année}"` si `EMISE`, `"Paie #{numero_periode} - brouillon"` (sans date) si `BROUILLON` — signature inchangée, construction des `href` inchangée à l'identique (même code, même ordre des conditions statut/`href`).
  - Ne pas modifier `_LIBELLES_STATUT`, `_formater_date_courte`, `_NOMS_MOIS_MINUSCULES` (extension additive uniquement), `paies_pour_colonne`, ni `_contenu_colonne_paies_html`.
  - Exécuter les tests de la tâche 7 : ils doivent maintenant passer.
  - _Requirements: 2.4, 2.5, 2.6_

- [x] 9. [Bug B] Property-based test — Fix Checking (Property 2)
  - PBT task.
  - Dans `tests/app/pages_ui/test_tableau_de_bord.py`, écrire un test Hypothesis utilisant `st_ligne_paie_resume_arbitraire()` (filtré pour garantir `date_paiement` non `None` quand `statut = EMISE`, puisque `_formater_date_sans_annee` exige une date valide pour ce statut) qui vérifie pour chaque `LignePaieResume` généré : le texte du lien ne contient jamais l'année (`str(annee_fiscale)` ni l'année extraite de `date_paiement`), contient toujours `f"Paie #{numero_periode}"`, et respecte le suffixe exact attendu (`" - déposée le {jour} {mois}"` ou `" - brouillon"`) selon le statut.
  - Référencer "Feature: unicite-paie-active-par-periode, Property 2: Bug Condition - Libellé Colonne_Paies sans année" en commentaire.
  - Exécuter le test et corriger jusqu'à ce qu'il passe.
  - _Requirements: 2.4, 2.5, 2.6_

- [x]* 10. [Bug B] Property-based test — Preservation Checking (Property 4)
  - PBT task.
  - Dans `tests/app/pages_ui/test_tableau_de_bord.py`, écrire un test Hypothesis qui génère un `LignePaieResume` arbitraire, calcule le `href` produit par `_ligne_colonne_paie_html` avant et après le fix (en isolant la construction du `href`, indépendante du texte — comparer directement le fragment `href="..."` extrait du HTML retourné) et vérifie qu'il est strictement identique (même URL, même paramètres `employe_id`/`id_paie`, même route selon le statut).
  - Ajouter un second test Hypothesis vérifiant que `paies_pour_colonne` (non modifiée) produit le même tuple filtré/trié avant et après ce bugfix sur un jeu de `LignePaieResume` généré — test de garde plutôt qu'un test de fix, puisque cette fonction n'est pas touchée.
  - Référencer "Feature: unicite-paie-active-par-periode, Property 4: Preservation - Filtrage, tri et navigation de la Colonne_Paies" en commentaire.
  - Exécuter le test et corriger jusqu'à ce qu'il passe.
  - _Requirements: 3.6, 3.7, 3.8_

- [x] 11. [Bug B] Tests unitaires (régression)
  - Ajouter un test unitaire d'exemple : `LignePaieResume` `EMISE` avec `date_paiement="2026-07-29"`, `numero_periode=1` → texte exact `"Paie #1 - déposée le 29 juillet"`.
  - Ajouter un test unitaire d'exemple : `LignePaieResume` `BROUILLON`, `numero_periode=2` → texte exact `"Paie #2 - brouillon"`, aucune date dans le HTML produit.
  - Ajouter un test unitaire pour `_formater_date_sans_annee` seule : `"2026-07-29T00:00:00"` → `"29 juillet"` (jour sans zéro initial, mois en minuscules, aucune année).
  - Exécuter toute la suite `tests/app/pages_ui/test_tableau_de_bord.py` et confirmer l'absence de régression (notamment `TestRenommageColonnePaies` et les tests d'isolation d'erreur existants).
  - _Requirements: 2.4, 2.5, 2.6, 3.6, 3.7, 3.8_

- [x] 12. Intégration et validation finale
  - Exécuter la suite complète du projet (`pytest`) et confirmer qu'aucun test préexistant ne régresse, en particulier `TestRefusDoubleEmisePourMemePeriode`, `TestRemplacerPaie`, et les tests de `app/logique_metier/dernieres_paies.py`/`paies_pour_colonne`.
  - Vérifier manuellement (ou via un test d'intégration léger) le scénario du design §Testing Strategy « Integration Tests » : enregistrer deux `BROUILLON` successifs pour la même période via le flux « Nouvelle paie », puis observer dans le Tableau_De_Bord qu'une seule ligne active apparaît avec le nouveau libellé.
  - Confirmer qu'aucun fichier hors périmètre n'a été modifié : `app/pages_ui/formulaire_paie.py` (`_section_corriger_paie`), `remplacer_paie`, `paies_pour_colonne`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

## Notes

- Bug A et Bug B sont indépendants (fichiers, fonctions et tables distincts) et peuvent être traités en parallèle par deux personnes/sessions différentes après la tâche 1.
- Hors périmètre de ce bugfix (ne pas modifier) : `app/pages_ui/formulaire_paie.py` (`_section_corriger_paie`, `_section_nouvelle_paie`), `remplacer_paie`, `paies_pour_colonne`, `_formater_date_courte`, `_LIBELLES_STATUT`.
- Méthodologie bug condition (règle 06) : chaque test d'exploration DOIT échouer sur le code non corrigé avant l'implémentation du fix — ne jamais corriger un test d'exploration qui échoue, corriger le code.
