# Bugfix Requirements Document

## Introduction

Le flux « Nouvelle paie » du Formulaire_Paie (`app/pages_ui/formulaire_paie.py::_section_nouvelle_paie`/`_section_enregistrement`, via `payroll_engine/register.py::inserer_paie`, append-only) et l'affichage de la Colonne_Paies du Tableau_De_Bord (`app/pages_ui/tableau_de_bord.py::_ligne_colonne_paie_html`) présentent deux défauts liés à la même Paie_Logique `(employe_id, annee_fiscale, numero_periode)`, corrigés ensemble car le second défaut (libellé) rend visible dans l'interface la conséquence du premier (accumulation de brouillons) :

- **BUG A — Aucune limite au nombre de lignes BROUILLON actives par période.** `inserer_paie` refuse déjà une seconde ligne `EMISE` pour la même Paie_Logique (garde-fou existant, `TestRefusDoubleEmisePourMemePeriode`, non touché par ce bugfix) mais ne contrôle rien d'autre : chaque nouvel enregistrement `BROUILLON` insère une nouvelle version (append-only) sans jamais invalider les lignes `BROUILLON` précédentes de la même période, et un `BROUILLON` peut aussi être suivi d'une insertion `EMISE` sans que l'ancien `BROUILLON` ne soit invalidé. Résultat : il peut exister un nombre illimité de lignes actives (`BROUILLON` et/ou `EMISE`) simultanément pour une même Paie_Logique, alors que l'invariant attendu du registre est qu'il n'en existe jamais plus d'une.

- **BUG B — Libellé de la Colonne_Paies incorrect et redondant.** `_ligne_colonne_paie_html` affiche actuellement `"{libellé_statut} — {date complète avec année}"` (ex. `"Brouillon — 3 juillet 2026"`, `"Émise — 3 juillet 2026"`). Ce format n'indique jamais le numéro de période et affiche systématiquement l'année, alors que la Colonne_Paies ne montre déjà que les paies de l'année sélectionnée par le Selecteur_De_Periode_Global (`paies_pour_colonne`) — l'année affichée est donc redondante et potentiellement trompeuse.

Ces deux corrections partagent le même périmètre technique : le flux « Nouvelle paie » et son affichage associé dans le Tableau_De_Bord. Le flux « Corriger une paie émise » (`_section_corriger_paie`, `remplacer_paie`) n'est concerné par aucune des deux corrections — sa logique de remplacement `EMISE`→`EMISE` reste inchangée.

## Bug Analysis

### Current Behavior (Defect)

**Bug A — accumulation illimitée de lignes actives par Paie_Logique.**

Fonction bug condition — identifie les insertions affectées par ce défaut :

```pascal
FUNCTION isBugCondition_InvarianceActive(X)
  INPUT: X of type InsertionPaie
    // X représente un appel inserer_paie(nouvelle_ligne, saison, ...)
    // dans le flux "Nouvelle paie", où il existe, immédiatement avant
    // cet appel, une ligne active (statut BROUILLON) pour la même
    // Paie_Logique (employe_id, annee_fiscale, numero_periode) que
    // nouvelle_ligne.
  OUTPUT: boolean

  RETURN existe_ligne_active(X.employe_id, X.annee_fiscale, X.numero_periode)
     AND ligne_active(X.employe_id, X.annee_fiscale, X.numero_periode).statut = BROUILLON
     AND X.nouvelle_ligne.statut ∈ {BROUILLON, EMISE}
END FUNCTION
```

1.1 WHEN une ligne `BROUILLON` active existe déjà pour une Paie_Logique `(employe_id, annee_fiscale, numero_periode)` et qu'une nouvelle ligne `BROUILLON` est insérée pour la même période via `inserer_paie` THEN le système insère la nouvelle ligne sans jamais invalider l'ancienne — les deux lignes `BROUILLON` restent simultanément actives indéfiniment

1.2 WHEN une ligne `BROUILLON` active existe déjà pour une Paie_Logique et qu'une nouvelle ligne `EMISE` est insérée pour la même période via `inserer_paie` THEN le système insère la nouvelle ligne `EMISE` sans invalider l'ancienne ligne `BROUILLON` — la ligne `BROUILLON` reste active en plus de la nouvelle ligne `EMISE`

1.3 WHEN un employé accumule plusieurs enregistrements successifs en `BROUILLON` pour la même période (ex. plusieurs sessions de saisie sans émission) THEN le système laisse croître sans limite le nombre de lignes `BROUILLON` actives pour cette période, sans qu'aucun mécanisme n'invalide les versions précédentes

**Bug B — libellé de la Colonne_Paies redondant et incomplet.**

Fonction bug condition — identifie les résumés affichés affectés par ce défaut (le défaut touche systématiquement tout affichage, quel que soit le statut) :

```pascal
FUNCTION isBugCondition_Libelle(X)
  INPUT: X of type LignePaieResume affichée dans la Colonne_Paies
  OUTPUT: boolean

  // Vrai pour tout résumé affiché : le format actuel omet toujours le
  // numéro de période et affiche toujours l'année, quel que soit
  // resume.statut.
  RETURN X.statut ∈ {BROUILLON, EMISE}
END FUNCTION
```

1.4 WHEN une ligne de la Colonne_Paies correspond à une paie de statut `EMISE` THEN le système affiche le libellé au format `"{libellé_statut} — {date complète avec année}"` (ex. `"Émise — 3 juillet 2026"`), sans indiquer le numéro de période et en incluant l'année alors que la Colonne_Paies n'affiche déjà que les paies de l'année sélectionnée par le Selecteur_De_Periode_Global

1.5 WHEN une ligne de la Colonne_Paies correspond à une paie de statut `BROUILLON` THEN le système affiche le libellé au format `"{libellé_statut} — {date complète avec année}"` (ex. `"Brouillon — 3 juillet 2026"`), sans indiquer le numéro de période et en affichant une date de paiement qui n'a pourtant aucune valeur définitive pour un brouillon

### Expected Behavior (Correct)

**Bug A — propriété de correction (Fix Checking).**

```pascal
// Property: Fix Checking — Invariant "au plus une ligne active par période"
FOR ALL X WHERE isBugCondition_InvarianceActive(X) DO
  ancienne_ligne ← ligne_active(X.employe_id, X.annee_fiscale, X.numero_periode)
  inserer_paie'(X.nouvelle_ligne, X.saison, ...)

  lignes_actives ← lignes_avec_statut_dans(
      X.employe_id, X.annee_fiscale, X.numero_periode, {BROUILLON, EMISE}
  )
  ASSERT nombre(lignes_actives) = 1
     AND lignes_actives[0].id_paie = X.nouvelle_ligne.id_paie

  ancienne_relue ← lire_paie'(ancienne_ligne.id_paie)
  ASSERT ancienne_relue.statut = REMPLACE_PAR
     AND ancienne_relue.remplace_par_id = X.nouvelle_ligne.id_paie
END FOR
```

2.1 WHEN `inserer_paie` insère une nouvelle ligne (`BROUILLON` ou `EMISE`) pour une Paie_Logique où une ligne `BROUILLON` active existe déjà THEN le système SHALL, dans la même transaction atomique que l'insertion, faire passer le statut de cette ancienne ligne `BROUILLON` à `REMPLACE_PAR` et renseigner son `remplace_par_id` avec l'`id_paie` de la nouvelle ligne insérée — en ne mutant que les colonnes `statut`, `remplace_par_id` et `payload_json` de l'ancienne ligne (jamais `payload_input_json`), reproduisant exactement le modèle de mutation déjà utilisé par `remplacer_paie`

2.2 WHEN cette mutation est appliquée THEN le système SHALL garantir qu'il n'existe jamais plus d'une ligne active (statut ∈ {`BROUILLON`, `EMISE`}) simultanément pour une même Paie_Logique `(employe_id, annee_fiscale, numero_periode)`, pour les trois transitions possibles `BROUILLON`→`BROUILLON`, `BROUILLON`→`EMISE` et `EMISE`→`EMISE` (cette dernière restant bloquée par le garde-fou déjà en place, sans aucun changement à ce comportement)

2.3 WHEN cette correction est implémentée THEN le système SHALL la limiter strictement au flux « Nouvelle paie » (`_section_nouvelle_paie`/`_section_enregistrement`, via `inserer_paie`), sans modifier le flux « Corriger une paie émise » (`_section_corriger_paie`, `remplacer_paie`)

**Bug B — propriété de correction (Fix Checking).**

```pascal
// Property: Fix Checking — Libellé Colonne_Paies sans année
FOR ALL X WHERE isBugCondition_Libelle(X) DO
  libelle ← _ligne_colonne_paie_html'(X.employe_id, X.resume)

  ASSERT NOT contient_annee(libelle)

  IF X.resume.statut = EMISE THEN
    ASSERT libelle_texte(libelle) =
        "Paie #" + X.resume.numero_periode + " - déposée le " +
        formater_date_sans_annee(X.resume.date_paiement)
  END IF

  IF X.resume.statut = BROUILLON THEN
    ASSERT libelle_texte(libelle) =
        "Paie #" + X.resume.numero_periode + " - brouillon"
       AND NOT contient_date(libelle)
  END IF
END FOR
```

2.4 WHEN une ligne de la Colonne_Paies correspond à une paie de statut `EMISE` THEN le système SHALL afficher le libellé au format `"Paie #{numero_periode} - déposée le {date sans année}"` (ex. `"Paie #1 - déposée le 29 juillet"`), en utilisant un format de date sans année (jour sans zéro initial, mois en minuscules, cohérent avec le style français déjà utilisé par `_formater_date_courte`/`_NOMS_MOIS_MINUSCULES`)

2.5 WHEN une ligne de la Colonne_Paies correspond à une paie de statut `BROUILLON` THEN le système SHALL afficher le libellé au format `"Paie #{numero_periode} - brouillon"`, sans jamais afficher de date

2.6 WHEN un libellé de la Colonne_Paies est généré, quel que soit le statut (`BROUILLON` ou `EMISE`) THEN le système SHALL ne jamais afficher l'année, la Colonne_Paies n'affichant déjà que les paies de l'année sélectionnée par le Selecteur_De_Periode_Global (`paies_pour_colonne`)

### Unchanged Behavior (Regression Prevention)

Propriété de préservation, exprimée pour les deux bugs (F = comportement avant correction, F' = comportement après correction) :

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition_InvarianceActive(X) AND NOT isBugCondition_Libelle(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

3.1 WHEN `inserer_paie` insère une ligne `EMISE` pour une Paie_Logique où une AUTRE ligne `EMISE` existe déjà pour la même période THEN le système SHALL CONTINUE TO lever `ValueError` et refuser l'insertion, exactement comme avant cette correction (garde-fou `EMISE`→`EMISE` existant, `TestRefusDoubleEmisePourMemePeriode`, non modifié)

3.2 WHEN `inserer_paie` insère une ligne `BROUILLON` pour une Paie_Logique où une ligne `EMISE` active existe déjà (et où aucune ligne `BROUILLON` active n'existe) THEN le système SHALL CONTINUE TO autoriser l'insertion sans invalider la ligne `EMISE` existante, comportement inchangé (cas couvert par `test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee`, non affecté par ce bugfix)

3.3 WHEN `inserer_paie` insère la première ligne (`BROUILLON` ou `EMISE`) d'une Paie_Logique n'ayant encore aucune ligne active THEN le système SHALL CONTINUE TO l'insérer normalement, sans mutation d'aucune autre ligne du registre

3.4 WHEN une ancienne ligne `BROUILLON` est mutée vers `REMPLACE_PAR` par cette correction THEN le système SHALL CONTINUE TO laisser `cumuls_ytd` inchangée pour cette mutation, une ligne `BROUILLON` ne contribuant jamais aux cumuls (Req 11.3/11.4 déjà en place dans le registre)

3.5 WHEN le flux « Corriger une paie émise » (`_section_corriger_paie`, `remplacer_paie`) est utilisé THEN le système SHALL CONTINUE TO appliquer sa propre logique de remplacement `EMISE`→`EMISE` existante (Req 13 du registre), sans aucune modification de comportement ni de signature

3.6 WHEN une paie de statut `ANNULEE` ou `REMPLACE_PAR` existe dans le registre THEN le système SHALL CONTINUE TO ne jamais l'afficher dans la Colonne_Paies, ce filtrage (`paies_pour_colonne`) restant inchangé

3.7 WHEN le filtrage par année de la Colonne_Paies (`paies_pour_colonne`) est appliqué THEN le système SHALL CONTINUE TO n'afficher que les paies dont la date de paiement appartient à l'année sélectionnée par le Selecteur_De_Periode_Global, sans aucun changement de ce filtrage ni de l'ordre de tri (BROUILLON avant EMISE, puis date de paiement décroissante, puis numéro de période croissant)

3.8 WHEN la navigation associée à chaque ligne de la Colonne_Paies est générée (lien vers Formulaire_Paie si `BROUILLON`, vers Bulletin_De_Paie si `EMISE`) THEN le système SHALL CONTINUE TO produire les mêmes `href` qu'avant cette correction — seul le texte affiché du libellé change
