# Bugfix Requirements Document

## Introduction

Le Formulaire_Paie (saisie, assemblage et enregistrement d'une paie du Camp LilySO) présente deux défauts liés au même flux de saisie et de persistance d'une paie, corrigés ensemble car ils touchent la même étape (saisie des heures) et le même mécanisme (reprise d'un brouillon) :

- **BUG 1 — Saisie des heures non adaptée à la réalité opérationnelle.** Le Formulaire_Paie exige la saisie des heures normales et supplémentaires séparément pour chacune des 2 semaines constituantes de la période (4 champs), alors que l'opérateur ne dispose déjà, hors système, que de 2 totaux pour l'ensemble de la période de 2 semaines (c'est l'opérateur qui détermine déjà la répartition légale heures normales/supplémentaires par semaine). Le moteur de calcul du brut (`payroll_engine/gains_bruts.py::calcul_gains`) ne dépend que de la somme des heures sur la période, jamais de leur répartition par semaine — la contrainte de saisie à 4 champs n'a donc aucune justification fiscale.

- **BUG 2 — Un brouillon de paie n'est pas restituable intégralement pour poursuite de saisie.** Le registre (`payroll_engine/register.py`, table `paies`) ne persiste que le `PayrollResult` (résultat assemblé), jamais les données d'entrée (`PayrollInput`) qui ont produit ce résultat. Lorsqu'un brouillon est repris pour poursuite de saisie, `app/logique_metier/formulaire_paie.py::valeurs_effectives_depuis_paie` ne peut pas reconstruire les heures saisies (aucune trace ne les porte explicitement) : l'opérateur retrouve systématiquement "0.00" et doit ressaisir entièrement les heures, ce qui contredit le principe même d'un brouillon.

Ces deux corrections partagent le même point d'ancrage : le contrat `PayrollInput` (et son assemblage dans `app/logique_metier/formulaire_paie.py`) reste inchangé au sens du moteur fiscal — seules l'ergonomie de saisie et la persistance des données d'entrée sont corrigées. Aucune formule, aucun paramètre fiscal (seuil hebdomadaire, multiplicateur d'heures supplémentaires — règle 05) n'est modifié.

## Bug Analysis

### Current Behavior (Defect)

**Bug 1 — 4 champs d'heures au lieu de 2 totaux.**

Fonction bug condition — identifie les saisies affectées par ce défaut :

```pascal
FUNCTION isBugCondition_Heures(X)
  INPUT: X of type SaisieFormulairePaie
  OUTPUT: boolean

  // Vrai pour toute saisie d'une période de paie aux deux semaines,
  // puisque le formulaire actuel exige TOUJOURS la décomposition par
  // semaine (aucune saisie de ce type n'y échappe).
  RETURN X.frequence = AUX_DEUX_SEMAINES
END FUNCTION
```

1.1 WHEN l'opérateur saisit les heures d'une période de paie de 2 semaines THEN le système exige 4 champs distincts (`heures_normales_1`, `heures_supp_1`, `heures_normales_2`, `heures_supp_2`) alors que l'opérateur ne dispose déjà, hors système, que de 2 totaux pour l'ensemble de la période

1.2 WHEN l'opérateur assemble la paie à partir de ces 4 champs THEN le système oblige l'opérateur à répartir lui-même ses 2 totaux sur les 2 semaines constituantes avant de les saisir, sans que cette répartition n'ait le moindre effet sur le calcul du brut (`calcul_gains` n'additionne que les totaux d'heures sur la période, sans reclassement par seuil hebdomadaire)

**Bug 2 — brouillon non restituable intégralement.**

Fonction bug condition — identifie les reprises de brouillon affectées par ce défaut :

```pascal
FUNCTION isBugCondition_Brouillon(X)
  INPUT: X of type RepriseDeBrouillon
  OUTPUT: boolean

  // Vrai pour toute reprise d'un brouillon (ou d'une paie émise) déjà
  // enregistré dans le registre, puisque le registre actuel ne
  // persiste jamais le PayrollInput, quel que soit le statut.
  RETURN X.paie_deja_enregistree = true
END FUNCTION
```

1.3 WHEN une paie (`BROUILLON` ou `EMISE`) est enregistrée dans le registre (table `paies`) THEN le système persiste uniquement `PayrollResult.model_dump_json()` dans `payload_json`, sans les données d'entrée (`PayrollInput`) ayant produit ce résultat

1.4 WHEN un brouillon est repris pour poursuite de saisie via `valeurs_effectives_depuis_paie` THEN le système affiche "0.00" pour les champs d'heures et force l'opérateur à ressaisir entièrement les heures, car elles ne sont reconstructibles depuis aucune `CalculationTrace` du `PayrollResult` déjà assemblé

### Expected Behavior (Correct)

**Bug 1 — propriété de correction (Fix Checking).**

```pascal
// Property: Fix Checking — Saisie à 2 totaux
FOR ALL X WHERE isBugCondition_Heures(X) DO
  formulaire ← rendre_formulaire_paie'(X)
  ASSERT nombre_champs_heures(formulaire) = 2
     AND champs_heures(formulaire) = {total_heures_normales, total_heures_supplementaires}

  payroll_input ← construire_payroll_input'(total_heures_normales, total_heures_supplementaires)
  ASSERT payroll_input.heures_par_semaine EST tuple de 2 HeuresParSemaine  // contrat moteur inchangé
     AND somme(payroll_input.heures_par_semaine[*].heures_normales) = total_heures_normales
     AND somme(payroll_input.heures_par_semaine[*].heures_supplementaires) = total_heures_supplementaires

  (gains, trace) ← calcul_gains(payroll_input, parametres_annee)
  ASSERT gains = calcul_gains(payroll_input_repartition_equivalente_arbitraire, parametres_annee).gains
    // la répartition interne choisie n'affecte pas le résultat fiscal
END FOR
```

2.1 WHEN l'opérateur saisit les heures d'une période de paie de 2 semaines THEN le système SHALL exposer exactement 2 champs de saisie (un total d'heures normales, un total d'heures supplémentaires) pour l'ensemble de la période, sans exiger de décomposition par semaine

2.2 WHEN l'opérateur assemble la paie à partir de ces 2 totaux THEN le système SHALL construire un `PayrollInput.heures_par_semaine` (tuple de 2 `HeuresParSemaine`, un par `WeekSegment` existant — contrat moteur inchangé) via une répartition interne des 2 totaux dont le choix est arbitraire, sans modifier le calcul du brut ni le résultat fiscal produit (`calcul_gains` ne dépend que de la somme des heures sur la période, jamais de leur répartition par semaine)

**Bug 2 — propriété de correction (Fix Checking).**

```pascal
// Property: Fix Checking — Restitution intégrale d'un brouillon
FOR ALL X WHERE isBugCondition_Brouillon(X) AND X.paie_creee_apres_deploiement = true DO
  id_paie ← inserer_paie'(paie_originale, saison)
  paie_relue ← lire_paie'(id_paie)
  valeurs ← valeurs_effectives_depuis_paie'(paie_relue)

  ASSERT valeurs CONTIENT tous les champs du Formulaire_Paie
     AND valeurs.total_heures_normales = paie_originale.payroll_input.total_heures_normales
     AND valeurs.total_heures_supplementaires = paie_originale.payroll_input.total_heures_supplementaires
     AND aucun champ ne vaut une valeur par défaut de repli ("0.00") non saisie par l'opérateur
END FOR
```

2.3 WHEN une paie (`BROUILLON` ou `EMISE`) est enregistrée dans le registre APRÈS le déploiement de cette correction THEN le système SHALL persister les données d'entrée exactes (`PayrollInput`, ou toute information équivalente permettant de reconstruire fidèlement le formulaire de saisie) avec le reste des informations de la paie (table `paies`)

2.4 WHEN un brouillon créé APRÈS le déploiement de cette correction est repris pour poursuite de saisie THEN le système SHALL restituer intégralement tous les champs du Formulaire_Paie, y compris les 2 totaux d'heures (heures normales, heures supplémentaires), sans aucune perte ni ressaisie forcée

### Unchanged Behavior (Regression Prevention)

Propriété de préservation, exprimée pour les deux bugs (F = comportement avant correction, F' = comportement après correction) :

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition_Heures(X) AND NOT isBugCondition_Brouillon(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

3.1 WHEN le calcul du brut (`calcul_gains`) reçoit un `PayrollInput.heures_par_semaine` dont la somme des heures normales et des heures supplémentaires sur les 2 semaines est identique à celle qui aurait été produite avant cette correction THEN le système SHALL CONTINUE TO produire un `GainsDecomposes` strictement identique (`salaire_regulier`, `heures_supplementaires_montant`, `vacances`, `jours_feries_manuels`, `brut_total`), quelle que soit la répartition interne choisie entre les 2 `WeekSegment`

3.2 WHEN `construire_payroll_input` assemble un `PayrollInput` THEN le système SHALL CONTINUE TO produire `heures_par_semaine` comme un tuple de 2 `HeuresParSemaine` (un par `WeekSegment` de la période), sans aucun changement du modèle de données du moteur (`models/payroll_input.py`, `models/pay_period.py` inchangés)

3.3 WHEN une paie `EMISE` existante est corrigée via l'Action_Corriger (`remplacer_paie`) THEN le système SHALL CONTINUE TO appliquer les mêmes règles de version incrémentée, de confirmation explicite et de recalcul des `cumuls_ytd` qu'avant cette correction

3.4 WHEN une paie déjà présente dans le registre AVANT le déploiement de cette correction est reprise pour poursuite de saisie THEN le système SHALL CONTINUE TO afficher les champs d'heures à "0.00" et informer l'opérateur qu'ils doivent être ressaisis — limitation assumée et documentée comme décision opérationnelle du projet (pas de migration rétroactive des données historiques, cohérent avec la règle 06)

3.5 WHEN les six valeurs TP-1015.3/TD1 effectives, les jours fériés manuels, l'année fiscale, le numéro de période et les dates d'une paie (brouillon ou émise, quel que soit son statut) sont reconstruits pour pré-remplissage THEN le système SHALL CONTINUE TO les restituer correctement, comme c'était déjà le cas avant cette correction

3.6 WHEN toute fonction du moteur fiscal (`payroll_engine/`, `models/`) est appelée avec des entrées non affectées par ces corrections THEN le système SHALL CONTINUE TO produire des résultats identiques à ceux produits avant cette correction — aucune régression sur les golden tests et les property-based tests existants (identité comptable, non-négativité, plafonds, monotonie des cumuls)
