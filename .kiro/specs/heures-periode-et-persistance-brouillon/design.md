# Heures_Periode_Et_Persistance_Brouillon Bugfix Design

<!-- Document de design — heures-periode-et-persistance-brouillon. Les en-têtes structurels de niveau supérieur sont maintenus en anglais pour la conformité au format Kiro. Tout le contenu métier est rédigé en français. -->

## Overview

Ce bugfix corrige deux défauts d'ergonomie et de persistance du Formulaire_Paie, sans toucher à aucune formule fiscale ni à aucun contrat déjà figé du moteur (`models/payroll_input.py`, `models/pay_period.py`, `payroll_engine/gains_bruts.py`, les invariants de `PayrollResult`).

**BUG 1 — Saisie des heures à 4 champs au lieu de 2 totaux.** Le Formulaire_Paie exige que l'opérateur répartisse lui-même ses 2 totaux d'heures (normales, supplémentaires) sur les 2 semaines constituantes de la période avant de les saisir, alors que `calcul_gains` (`payroll_engine/gains_bruts.py`) ne dépend que de la somme des heures sur la période entière — jamais de leur répartition par semaine (vérifié : `sum(s.heures_normales for s in payroll_input.heures_par_semaine)` et l'équivalent pour les heures supplémentaires, aucune lecture individuelle de `heures_par_semaine[0]` ou `[1]`). La correction remplace les 4 champs de saisie par exactement 2 champs (`total_heures_normales`, `total_heures_supplementaires`) dans les deux sections du formulaire concernées, et introduit une fonction pure de répartition interne, déterministe et documentée comme fiscalement neutre, qui reconstruit le tuple `heures_par_semaine` attendu par `PayrollInput` (contrat moteur strictement inchangé).

**BUG 2 — Brouillon non restituable intégralement.** Le registre (`payroll_engine/register.py`) ne persiste que `PayrollResult.model_dump_json()` dans la colonne `payload_json` de la table `paies` ; les données d'entrée (`PayrollInput`) qui ont produit ce résultat ne sont jamais conservées. `valeurs_effectives_depuis_paie` ne peut donc jamais reconstruire les heures saisies, et affiche systématiquement `"0.00"` en forçant une ressaisie complète — même pour un brouillon créé il y a quelques minutes. La correction ajoute une colonne `payload_input_json` à la table `paies`, portant `PayrollInput.model_dump_json()`, écrite par `inserer_paie`/`remplacer_paie` et lue par `lire_paie`/`lire_historique_paie`. Conformément à la règle 06 (immutabilité historique) et à l'exigence 3.4 du bugfix, **aucune migration rétroactive** n'est effectuée : les lignes déjà présentes dans le registre avant le déploiement de cette correction n'ont pas cette colonne renseignée (`NULL`), et toute lecture doit gérer ce cas sans lever d'exception — `valeurs_effectives_depuis_paie` continue alors à afficher `"0.00"` pour les heures, exactement comme avant la correction (comportement inchangé, Req 3.4).

Les deux corrections partagent le même point d'ancrage (le Formulaire_Paie et son cycle saisie → assemblage → enregistrement → reprise) mais sont **indépendantes fonctionnellement** : Bug 1 change l'ergonomie de saisie des heures ; Bug 2 change ce qui est persisté et relu. Aucune des deux ne modifie une formule fiscale, un paramètre annuel (règle 05) ou le contrat `PayrollInput`/`PayrollResult` (règle 01, règle 02).

## Glossary

- **Bug_Condition (C)** : selon le bug considéré — `C_Heures(X)` : toute saisie d'une période de paie aux deux semaines (le formulaire actuel exige toujours 4 champs) ; `C_Brouillon(X)` : toute reprise d'une paie déjà enregistrée dans le registre (le registre actuel ne persiste jamais le `PayrollInput`).
- **Property (P)** : `P_Heures` — le formulaire expose exactement 2 champs d'heures et la répartition interne choisie n'affecte pas le résultat fiscal ; `P_Brouillon` — pour une paie créée après le déploiement de cette correction, `valeurs_effectives_depuis_paie` restitue les 2 totaux d'heures sans ressaisie forcée.
- **Preservation** : comportement du moteur fiscal (`calcul_gains`, `PayrollInput`, `PayrollResult`) inchangé pour toute entrée équivalente ; comportement de lecture inchangé (`"0.00"` + avertissement) pour les paies enregistrées avant le déploiement (Req 3.4).
- **total_heures_normales / total_heures_supplementaires** : les 2 nouveaux champs de saisie du Formulaire_Paie — `Decimal`, un total pour l'ensemble de la période de 2 semaines, remplaçant les 4 champs `heures_normales_1`/`heures_supp_1`/`heures_normales_2`/`heures_supp_2`.
- **repartir_heures_sur_semaines** : nouvelle fonction pure de `app/logique_metier/formulaire_paie.py` qui répartit les 2 totaux saisis sur les 2 `HeuresParSemaine` attendus par `PayrollInput.heures_par_semaine` — répartition arbitraire, déterministe, sans effet sur `calcul_gains`.
- **payload_input_json** : nouvelle colonne `TEXT` nullable de la table `paies`, portant `PayrollInput.model_dump_json()` — `NULL` pour toute ligne insérée avant le déploiement de cette correction, jamais rétro-remplie.
- **Paie_Post_Correction** : une paie dont la ligne `paies` a été insérée par une version du code intégrant cette correction — sa colonne `payload_input_json` est renseignée (non `NULL`).
- **Paie_Pre_Correction** : une paie dont la ligne `paies` existait déjà avant le déploiement de cette correction, ou insérée par un chemin de code qui ne transmettrait pas le `PayrollInput` — sa colonne `payload_input_json` reste `NULL` par absence de rétro-remplissage.

## Bug Details

### Bug Condition

Le bug se manifeste sous deux formes distinctes mais colocalisées dans le même flux (saisie → assemblage → persistance → reprise) du Formulaire_Paie.

**Formal Specification — Bug 1 (saisie des heures) :**

```
FUNCTION isBugCondition_Heures(input)
  INPUT: input de type SaisieFormulairePaie
  OUTPUT: boolean

  // Vrai pour toute saisie d'une période de paie aux deux semaines,
  // puisque le formulaire actuel (avant correction) exige TOUJOURS la
  // décomposition par semaine — aucune saisie de ce type n'y échappe.
  RETURN input.frequence == AUX_DEUX_SEMAINES
END FUNCTION
```

**Formal Specification — Bug 2 (persistance du brouillon) :**

```
FUNCTION isBugCondition_Brouillon(input)
  INPUT: input de type RepriseDeBrouillon
  OUTPUT: boolean

  // Vrai pour toute reprise d'une paie déjà enregistrée dans le
  // registre (BROUILLON ou EMISE), puisque le registre actuel (avant
  // correction) ne persiste jamais le PayrollInput, quel que soit le
  // statut.
  RETURN input.paie_deja_enregistree == true
         AND input.payload_input_json_disponible == false
END FUNCTION
```

### Examples

- **Bug 1** — l'opérateur dispose de 2 totaux hors système (« 70 h normales, 6 h supplémentaires sur la période ») ; le formulaire actuel exige qu'il détermine lui-même quelle part revient à la semaine 1 et quelle part revient à la semaine 2, alors que `calcul_gains` ne fait que sommer les deux semaines avant d'appliquer le taux horaire. Attendu : 2 champs seulement, la répartition interne est un détail d'implémentation invisible pour l'opérateur.
- **Bug 1 (cas dégénéré)** — un opérateur saisit 0 h normales et 0 h supplémentaires (période sans heures travaillées, ex. congé). Attendu : les 2 totaux à `"0.00"` produisent un `PayrollInput.heures_par_semaine` valide (2 `HeuresParSemaine` à zéro), sans erreur.
- **Bug 2** — un brouillon est enregistré avec `total_heures_normales="70.00"` et `total_heures_supplementaires="6.00"` ; l'opérateur revient plus tard poursuivre la saisie. Avant correction : les champs d'heures affichent `"0.00"`, ressaisie forcée. Après correction (paie créée après déploiement) : les champs affichent `"70.00"` et `"6.00"`, aucune ressaisie.
- **Bug 2 (cas de préservation, Req 3.4)** — une paie déjà présente dans le registre avant le déploiement de cette correction (donc sans colonne `payload_input_json` renseignée) est reprise. Attendu : comportement strictement inchangé — `"0.00"` affiché, avertissement affiché, aucune exception levée par la lecture de la colonne absente/`NULL`.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors :**

- `calcul_gains` et tout le reste du moteur fiscal (`payroll_engine/`, `models/`) produisent des résultats identiques pour toute entrée équivalente — aucune formule, aucun paramètre annuel (règle 05) n'est modifié.
- `PayrollInput.heures_par_semaine` reste un tuple de 2 `HeuresParSemaine`, un par `WeekSegment` de la période — le contrat moteur (`models/payroll_input.py`, `models/pay_period.py`) est strictement inchangé (Req 3.2 du bugfix).
- L'Action_Corriger (`remplacer_paie`) continue d'appliquer les mêmes règles de version incrémentée, de confirmation explicite et de recalcul des `cumuls_ytd` (Req 3.3 du bugfix).
- Les six valeurs TP-1015.3/TD1 effectives, les jours fériés manuels, l'année fiscale, le numéro de période et les dates continuent d'être restitués correctement pour le pré-remplissage (Req 3.5 du bugfix) — cette restitution ne dépend pas de la nouvelle colonne `payload_input_json`, elle reste portée par les `CalculationTrace` déjà persistées dans `payload_json` (mécanisme inchangé de `valeurs_effectives_depuis_paie`).
- Pour toute paie enregistrée **avant** le déploiement de cette correction, la reprise de brouillon continue d'afficher `"0.00"` pour les champs d'heures et d'informer l'opérateur qu'ils doivent être ressaisis (Req 3.4 du bugfix — limitation assumée, pas de migration rétroactive, cohérent avec la règle 06).
- Tous les golden tests et property-based tests existants du moteur fiscal continuent de passer sans modification (Req 3.6 du bugfix).

**Scope :**

Toute entrée qui n'implique ni la saisie d'heures par le Formulaire_Paie, ni la lecture/écriture de la table `paies`, est complètement hors du périmètre de ce bugfix. Cela inclut notamment :

- tout calcul fiscal (RRQ, RQAP, AE, impôt QC/fédéral, charges patronales) ;
- la lecture/écriture de la table `cumuls_ytd` ;
- l'annuaire des employés, le tableau de bord, le bulletin PDF ;
- toute paie déjà enregistrée avant le déploiement de cette correction (Req 3.4).

## Hypothesized Root Cause

Root cause déjà confirmée par lecture directe du code (pas une hypothèse à valider par exploration — les deux causes sont structurelles et documentées dans le code source lui-même) :

1. **Bug 1 — Absence de fonction de répartition, saisie 1:1 avec le contrat moteur.** `app/pages_ui/formulaire_paie.py::_section_nouvelle_paie` et `::_section_corriger_paie` exposent directement 4 `st.text_input` (`heures_normales_1`, `heures_supp_1`, `heures_normales_2`, `heures_supp_2`) qui alimentent, sans transformation, les 2 `HeuresParSemaine` de `construire_payroll_input`. Aucune fonction n'existe pour dériver ces 2 `HeuresParSemaine` à partir de 2 totaux — le formulaire a été conçu en miroir exact du contrat moteur plutôt qu'en fonction du flux opérationnel réel de l'opérateur (qui ne dispose que de 2 totaux, cf. bugfix.md §Bug 1).

2. **Bug 2 — `register.py` ne persiste que `PayrollResult`, jamais `PayrollInput`.** Le DDL `_DDL_PAIES` de `payroll_engine/register.py` ne définit que la colonne `payload_json` (portant `resultat.model_dump_json()`) ; aucune colonne n'existe pour le `PayrollInput`. `_inserer_ligne_paie_tx` ne reçoit d'ailleurs même pas le `PayrollInput` en paramètre — seul `resultat: PayrollResult` lui est transmis. La docstring de `valeurs_effectives_depuis_paie` documente elle-même explicitement cette limitation (« les heures normales/supplémentaires saisies par semaine … ne sont pas persistées par `assembler_paie`/`payroll_engine.net_pay` »).

3. **Cause dérivée — `assembler_paie` ne reçoit ni ne retourne le `PayrollInput`.** `payroll_engine/net_pay.py::assembler_paie` consomme un `PayrollInput` en argument mais ne le fait pas transiter jusqu'au `PayrollResult` retourné (ce n'est pas son rôle — le contrat `PayrollResult` reste inchangé, règle absolue de cette correction). Le `PayrollInput` doit donc être conservé **en dehors** de `PayrollResult`, entre l'appel à `assembler_paie` et l'appel à `inserer_paie`/`remplacer_paie` — la seule structure déjà disponible à cet effet côté UI est `st.session_state` (déjà utilisé pour porter `fp_nouvelle_paie_assemblee`/`fp_corriger_paie_reassemblee`).

4. **Cause dérivée — aucune contrainte fiscale ne justifie la saisie par semaine.** Vérifié directement dans `payroll_engine/gains_bruts.py::calcul_gains` : `heures_normales_totales` et `heures_supplementaires_totales` sont calculés par `sum(s.X for s in payroll_input.heures_par_semaine)`, et tous les montants (`sr`, `hs`) sont eux-mêmes des sommes sur `payroll_input.heures_par_semaine` — aucune lecture indexée (`[0]`, `[1]`) n'apparaît dans le module. La répartition par semaine choisie par `repartir_heures_sur_semaines` (Bug 1) est donc démontrée fiscalement neutre par lecture du code, pas seulement par hypothèse.

## Correctness Properties

Property 1: Bug Condition — Saisie à 2 totaux, répartition fiscalement neutre

_For any_ saisie du Formulaire_Paie d'une période de paie aux deux semaines (bug condition Bug 1 vérifiée — le formulaire actuel exige toujours 4 champs), le formulaire corrigé SHALL exposer exactement 2 champs de saisie d'heures (`total_heures_normales`, `total_heures_supplementaires`) ; `repartir_heures_sur_semaines(total_heures_normales, total_heures_supplementaires)` SHALL retourner un tuple de 2 `HeuresParSemaine` dont la somme des `heures_normales` égale `total_heures_normales` et dont la somme des `heures_supplementaires` égale `total_heures_supplementaires` ; et pour tout `PayrollInput` construit à partir de ce tuple, `calcul_gains` SHALL produire un `GainsDecomposes` identique à celui produit par n'importe quelle autre répartition interne des 2 mêmes totaux sur les 2 semaines.

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition — Restitution intégrale d'un brouillon post-correction

_For any_ paie (`BROUILLON` ou `EMISE`) enregistrée dans le registre APRÈS le déploiement de cette correction (bug condition Bug 2 vérifiée — reprise d'une paie déjà enregistrée), `inserer_paie`/`remplacer_paie` SHALL persister le `PayrollInput` (colonne `payload_input_json`, non `NULL`) ayant produit cette paie, et `valeurs_effectives_depuis_paie` appliqué au résultat de `lire_paie`/`lire_historique_paie` SHALL restituer `total_heures_normales` et `total_heures_supplementaires` strictement égaux à ceux saisis à l'origine, sans valeur de repli `"0.00"` non saisie par l'opérateur.

**Validates: Requirements 2.3, 2.4**

Property 3: Preservation — Neutralité fiscale de la répartition interne

_For any_ `PayrollInput.heures_par_semaine` dont la somme des heures normales et supplémentaires sur les 2 semaines est identique à celle qui aurait été produite avant cette correction, `calcul_gains` SHALL CONTINUE TO produire un `GainsDecomposes` strictement identique (`salaire_regulier`, `heures_supplementaires_montant`, `vacances`, `jours_feries_manuels`, `brut_total`), quelle que soit la répartition interne choisie entre les 2 `WeekSegment` ; et `construire_payroll_input` SHALL CONTINUE TO produire `heures_par_semaine` comme un tuple de 2 `HeuresParSemaine`, sans aucun changement des modèles `models/payroll_input.py`/`models/pay_period.py`.

**Validates: Requirements 3.1, 3.2**

Property 4: Preservation — Comportement inchangé pour les paies pré-correction et pour l'Action_Corriger

_For any_ paie déjà présente dans le registre AVANT le déploiement de cette correction (colonne `payload_input_json` absente/`NULL`), `valeurs_effectives_depuis_paie` SHALL CONTINUE TO afficher les champs d'heures à `"0.00"` avec l'avertissement de ressaisie, sans lever d'exception liée à l'absence de la colonne ; et pour toute paie `EMISE` corrigée via `remplacer_paie`, le système SHALL CONTINUE TO appliquer les mêmes règles de version incrémentée, de confirmation explicite et de recalcul des `cumuls_ytd` qu'avant cette correction.

**Validates: Requirements 3.3, 3.4**

## Fix Implementation

### Changes Required

**File**: `app/pages_ui/formulaire_paie.py`

**Fonctions**: `_section_nouvelle_paie`, `_section_corriger_paie`

**Specific Changes**:

1. **Remplacement des 4 champs par 2 champs** : dans `_section_nouvelle_paie`, retirer les 4 `st.text_input` (`fp_nouvelle_hn1`, `fp_nouvelle_hs1`, `fp_nouvelle_hn2`, `fp_nouvelle_hs2`) et les remplacer par 2 `st.text_input` :
   ```python
   st.write("Heures — période complète (2 semaines)")
   total_heures_normales = st.text_input(
       "Total heures normales (période)", value="0.00",
       key="fp_nouvelle_total_hn",
   )
   total_heures_supplementaires = st.text_input(
       "Total heures supplémentaires (période)", value="0.00",
       key="fp_nouvelle_total_hs",
   )
   ```
   Même changement dans `_section_corriger_paie` avec les clés `fp_corriger_total_hn`/`fp_corriger_total_hs`.

2. **Appel à `repartir_heures_sur_semaines`** : dans le bloc `_assembler()`/`_reassembler()`, remplacer la construction directe des 2 `HeuresParSemaine` depuis 4 valeurs saisies par un appel à la nouvelle fonction :
   ```python
   heures_semaine_1, heures_semaine_2 = repartir_heures_sur_semaines(
       total_heures_normales=_decimal_depuis_saisie(total_heures_normales),
       total_heures_supplementaires=_decimal_depuis_saisie(total_heures_supplementaires),
   )
   ```
   puis transmission inchangée à `construire_payroll_input(heures_semaine_1=..., heures_semaine_2=..., ...)`.

3. **Import** : ajouter `repartir_heures_sur_semaines` à l'import existant depuis `app.logique_metier.formulaire_paie`.

4. **Pré-remplissage depuis un brouillon** (`_section_nouvelle_paie`, bloc `valeurs_precharge`) : les 2 nouveaux champs sont pré-remplis depuis `valeurs_precharge["total_heures_normales"]`/`["total_heures_supplementaires"]` s'ils sont présents dans le dict retourné par `valeurs_effectives_depuis_paie` (Paie_Post_Correction), sinon la valeur par défaut `"0.00"` est conservée avec l'avertissement existant (Paie_Pre_Correction, Req 3.4) — le message d'avertissement existant (« Heures par semaine non récupérables … ») est reformulé pour ne s'afficher que dans ce second cas (voir point 5 du fichier `app/logique_metier/formulaire_paie.py` ci-dessous).

5. **Conservation du `PayrollInput` assemblé en session** : dans `_assembler()`/`_reassembler()`, stocker également le `PayrollInput` construit (pas seulement le `PayrollResult`) dans `st.session_state`, sous une clé dédiée (`fp_nouvelle_payroll_input_assemble` / `fp_corriger_payroll_input_reassemble`) — nécessaire pour que `_section_enregistrement`/l'appel à `remplacer_paie` puisse le transmettre à `inserer_paie`/`remplacer_paie` (voir §4 ci-dessous).

---

**File**: `app/logique_metier/formulaire_paie.py`

**Fonction nouvelle**: `repartir_heures_sur_semaines`

**Specific Changes**:

1. **Nouvelle fonction pure** :
   ```python
   def repartir_heures_sur_semaines(
       *,
       total_heures_normales: Decimal,
       total_heures_supplementaires: Decimal,
   ) -> tuple[HeuresParSemaine, HeuresParSemaine]:
       """Répartit 2 totaux d'heures sur les 2 `HeuresParSemaine` du
       contrat moteur (`PayrollInput.heures_par_semaine`) — bug UI
       corrigé (Req 2.1, 2.2 du bugfix).

       **Règle de répartition, explicite et arbitraire** : la totalité
       des heures normales et supplémentaires est portée par la
       PREMIÈRE semaine (`heures_semaine_1`) ; la seconde semaine
       (`heures_semaine_2`) reçoit toujours `Decimal("0.00")` pour les
       deux quantités. Ce choix est un détail d'implémentation SANS
       AUCUN effet sur le résultat fiscal (Property 1, Property 3) :
       `payroll_engine.gains_bruts.calcul_gains` ne lit jamais
       `heures_par_semaine[0]`/`[1]` individuellement — il calcule
       exclusivement `sum(s.heures_normales for s in
       payroll_input.heures_par_semaine)` et l'équivalent pour les
       heures supplémentaires (vérifié par lecture directe de
       `gains_bruts.py`, confirmé par Property 1 en property-based
       testing). Toute autre règle de répartition déterministe
       (50/50, tout sur la semaine 2, etc.) satisferait également
       Property 1 — celle-ci a été retenue pour sa simplicité et sa
       lisibilité.

       Fonction pure : deux appels avec les mêmes arguments produisent
       deux tuples égaux au sens `==`. Aucune validation de bornes
       n'est effectuée ici — `HeuresParSemaine` applique déjà ses
       propres contraintes (`[0, 168]`, règle 01) ; toute valeur hors
       plage lève `pydantic.ValidationError` depuis la construction du
       modèle, propagée sans interception (règle 03 — pas de nouveau
       garde-fou).
       """
       semaine_1 = HeuresParSemaine(
           heures_normales=total_heures_normales,
           heures_supplementaires=total_heures_supplementaires,
       )
       semaine_2 = HeuresParSemaine(
           heures_normales=Decimal("0.00"),
           heures_supplementaires=Decimal("0.00"),
       )
       return (semaine_1, semaine_2)
   ```

2. **Modification de `valeurs_effectives_depuis_paie`** : ajouter la restitution des 2 totaux d'heures, conditionnée à la disponibilité du `PayrollInput` persisté (nouveau paramètre) :
   ```python
   def valeurs_effectives_depuis_paie(
       resultat: "PayrollResult",
       payroll_input_persiste: "PayrollInput | None" = None,
   ) -> dict[str, object]:
       """... (docstring existante conservée, complétée) ...

       Depuis cette correction (Req 2.3, 2.4 du bugfix) : si
       ``payroll_input_persiste`` est fourni (Paie_Post_Correction —
       `payload_input_json` non `NULL` relu par `register.py`), les
       clés `total_heures_normales` et `total_heures_supplementaires`
       sont ajoutées au dict retourné, calculées par sommation directe
       de `payroll_input_persiste.heures_par_semaine` (inverse exact de
       `repartir_heures_sur_semaines` — la somme est invariante par
       rapport à la répartition choisie, Property 1). Si
       ``payroll_input_persiste`` est `None` (Paie_Pre_Correction —
       colonne absente/`NULL`, comportement de préservation Req 3.4),
       ces deux clés sont **absentes** du dict retourné — l'appelant
       (`app/pages_ui/formulaire_paie.py`) doit alors laisser les 2
       champs de saisie à `"0.00"` et afficher l'avertissement de
       ressaisie existant, exactement comme avant cette correction.
       """
       # ... corps existant inchangé ...
       resultat_dict: dict[str, object] = { ... }  # dict existant, inchangé
       if payroll_input_persiste is not None:
           resultat_dict["total_heures_normales"] = sum(
               (s.heures_normales for s in payroll_input_persiste.heures_par_semaine),
               start=Decimal("0"),
           )
           resultat_dict["total_heures_supplementaires"] = sum(
               (s.heures_supplementaires for s in payroll_input_persiste.heures_par_semaine),
               start=Decimal("0"),
           )
       return resultat_dict
   ```
   Le paramètre `payroll_input_persiste` est optionnel avec défaut `None` pour ne casser aucun appelant existant (préservation, Property 4). Les deux appelants de `formulaire_paie.py` (préchargement de brouillon dans `_section_nouvelle_paie`) sont mis à jour pour transmettre le `PayrollInput` relu (voir §5 ci-dessous — `lire_paie` renvoie désormais un couple).

---

**File**: `payroll_engine/register.py`

**Fonctions**: schéma SQL, `inserer_paie`, `_inserer_ligne_paie_tx`, `remplacer_paie`, `lire_paie`, `lire_historique_paie`

**Specific Changes**:

1. **Extension du DDL `paies`** — nouvelle colonne nullable, rétrocompatible (`ALTER TABLE` non nécessaire pour les bases neuves car le DDL `CREATE TABLE IF NOT EXISTS` est déjà idempotent ; pour les bases existantes créées avant cette correction, la colonne doit être ajoutée par migration additive séparée — voir point 6) :
   ```python
   _DDL_PAIES = """
   CREATE TABLE IF NOT EXISTS paies (
       id_paie             TEXT    PRIMARY KEY,
       employe_id          TEXT    NOT NULL,
       annee_fiscale       INTEGER NOT NULL,
       numero_periode      INTEGER NOT NULL,
       saison              TEXT    NOT NULL,
       version             INTEGER NOT NULL,
       statut              TEXT    NOT NULL,
       remplace_par_id     TEXT,
       date_creation       TEXT    NOT NULL,
       date_emission       TEXT,
       payload_json        TEXT    NOT NULL,
       payload_input_json  TEXT
   );
   """
   ```
   `payload_input_json` est **nullable** (pas de `NOT NULL`) — c'est précisément ce qui permet aux lignes pré-correction de rester valides sans rétro-remplissage (Req 3.4, règle 06 immutabilité historique). Aucun changement à `_DDL_INDEX_PAIES_LOGIQUE`.

2. **Migration additive pour bases existantes** — `_creer_schema_si_absent` (appelée en tête de chaque fonction publique) doit gérer le cas d'une base créée par une version antérieure du code, où la table `paies` existe déjà mais sans la colonne `payload_input_json` :
   ```python
   def _creer_schema_si_absent(connexion: sqlite3.Connection) -> None:
       connexion.execute(_DDL_PAIES)
       connexion.execute(_DDL_INDEX_PAIES_LOGIQUE)
       connexion.execute(_DDL_CUMULS_YTD)
       _ajouter_colonne_payload_input_json_si_absente(connexion)


   def _ajouter_colonne_payload_input_json_si_absente(
       connexion: sqlite3.Connection,
   ) -> None:
       """Ajoute `payload_input_json` par migration additive (Req 2.3,
       rétrocompatibilité). `CREATE TABLE IF NOT EXISTS` ne modifie
       jamais le schéma d'une table déjà existante — sur une base créée
       par une version antérieure du code, la table `paies` existe déjà
       SANS cette colonne. `ALTER TABLE ... ADD COLUMN` est idempotent
       ici par vérification explicite via `PRAGMA table_info` (SQLite
       ne supporte pas `ADD COLUMN IF NOT EXISTS`) — aucune donnée
       existante n'est modifiée ni supprimée (règle 06, Req 3.4) : les
       lignes déjà présentes reçoivent `NULL` pour la nouvelle colonne,
       jamais une valeur de repli inventée.
       """
       colonnes = {
           ligne[1]
           for ligne in connexion.execute("PRAGMA table_info(paies)").fetchall()
       }
       if "payload_input_json" not in colonnes:
           connexion.execute(
               "ALTER TABLE paies ADD COLUMN payload_input_json TEXT"
           )
   ```

3. **`_inserer_ligne_paie_tx`** — nouveau paramètre `payload_input_json: str | None`, transmis à l'`INSERT` :
   ```python
   def _inserer_ligne_paie_tx(
       connexion: sqlite3.Connection,
       resultat: PayrollResult,
       saison: str,
       payload_input_json: str | None,
   ) -> None:
       connexion.execute(
           "INSERT INTO paies (id_paie, employe_id, annee_fiscale, "
           "numero_periode, saison, version, statut, remplace_par_id, "
           "date_creation, date_emission, payload_json, "
           "payload_input_json) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (
               resultat.id_paie,
               resultat.employe_id,
               resultat.annee_fiscale,
               resultat.pay_period.numero_periode,
               saison,
               resultat.version,
               resultat.statut.value,
               resultat.remplace_par_id,
               resultat.date_creation.isoformat(),
               resultat.date_emission.isoformat() if resultat.date_emission else None,
               resultat.model_dump_json(),
               payload_input_json,
           ),
       )
   ```

4. **`inserer_paie`** — nouveau paramètre optionnel `payroll_input: PayrollInput | None = None`, transmis à `_inserer_ligne_paie_tx` après sérialisation :
   ```python
   def inserer_paie(
       resultat: PayrollResult,
       saison: str,
       payroll_input: PayrollInput | None = None,
       chemin_bd: str | Path = chemin_bd_production(),
   ) -> None:
       """... (docstring existante conservée, complétée) ...

       Depuis cette correction (Req 2.3 du bugfix) : si
       ``payroll_input`` est fourni, sa sérialisation
       (`payroll_input.model_dump_json()`) est persistée dans la
       nouvelle colonne `payload_input_json` — même mécanisme de
       sérialisation Decimal → chaîne guillemée déjà porté par
       `PayrollInput.model_dump_json()`/`model_validate_json()` (règle
       01, aucun nouveau schéma de sérialisation introduit). Si
       ``payroll_input`` est `None` (appelant qui ne le fournit pas —
       aucun appelant actuel de ce module ne devrait être dans ce cas
       après la mise à jour de `app/pages_ui/formulaire_paie.py`, mais
       le paramètre reste optionnel pour ne pas casser un appelant
       existant, préservation Property 4), `payload_input_json` reste
       `NULL` pour cette ligne — comportement identique à une
       Paie_Pre_Correction.
       """
       with _connexion(chemin_bd) as connexion:
           _creer_schema_si_absent(connexion)
           ligne_existante = connexion.execute(
               "SELECT 1 FROM paies WHERE id_paie = ?", (resultat.id_paie,)
           ).fetchone()
           if ligne_existante is not None:
               raise ValueError(
                   f"id_paie '{resultat.id_paie}' déjà présent — append-only, "
                   "aucune ré-insertion (Req 11.6)."
               )
           payload_input_json = (
               payroll_input.model_dump_json() if payroll_input is not None else None
           )
           _inserer_ligne_paie_tx(connexion, resultat, saison, payload_input_json)
           if resultat.statut == StatutDePaie.EMISE:
               cumul_actuel = _lire_cumuls_ytd_tx(
                   connexion, resultat.employe_id, resultat.annee_fiscale
               )
               contribution = _ContributionResultat.depuis(resultat)
               nouveau_cumul = cumul_actuel.avec_paie(contribution)
               _upsert_cumuls_ytd(connexion, nouveau_cumul)
   ```
   Signature : `payroll_input` est placé **avant** `chemin_bd` (paramètre déjà positionné en dernier par convention du module) et **après** `saison`, avec un défaut `None` pour rester compatible avec tout appel positionnel existant qui s'arrêterait à `saison`.

5. **`remplacer_paie`** — même extension : nouveau paramètre optionnel `nouveau_payroll_input: PayrollInput | None = None`, transmis lors de l'insertion de la nouvelle ligne (l'ancienne ligne n'est jamais modifiée dans sa colonne `payload_input_json` — seuls `statut`/`remplace_par_id` sont mutés, conformément à l'invariant d'immutabilité déjà porté par le registre) :
   ```python
   def remplacer_paie(
       ancien_id: str,
       nouveau_resultat: PayrollResult,
       saison: str,
       nouveau_payroll_input: PayrollInput | None = None,
       chemin_bd: str | Path = chemin_bd_production(),
   ) -> None:
       ...
       payload_input_json = (
           nouveau_payroll_input.model_dump_json()
           if nouveau_payroll_input is not None
           else None
       )
       _inserer_ligne_paie_tx(connexion, nouveau_resultat, saison, payload_input_json)
       ...
   ```

6. **`lire_paie`** — retourne désormais un couple `(PayrollResult, PayrollInput | None)` — **décision de rupture de signature assumée**, seul moyen pour l'appelant UI de recevoir le `PayrollInput` persisté sans introduire une seconde fonction de lecture redondante :
   ```python
   def lire_paie(
       id_paie: str,
       chemin_bd: str | Path = chemin_bd_production(),
   ) -> tuple[PayrollResult, PayrollInput | None]:
       """... (docstring existante conservée, complétée) ...

       Depuis cette correction (Req 2.4, 3.4 du bugfix) : retourne
       désormais un COUPLE `(resultat, payroll_input)`. `payroll_input`
       est `None` si `payload_input_json` est `NULL` en base (Paie_Pre_
       Correction, colonne absente/non renseignée) — JAMAIS d'exception
       levée pour ce cas (Req 3.4). Si `payload_input_json` est
       renseigné (Paie_Post_Correction), `payroll_input` est reconstruit
       via `PayrollInput.model_validate_json(...)` — même discipline
       anti-`float` que pour `PayrollResult` (règle 01, Req 12.5 du
       registre).
       """
       with _connexion(chemin_bd) as connexion:
           _creer_schema_si_absent(connexion)
           ligne = connexion.execute(
               "SELECT payload_json, payload_input_json FROM paies "
               "WHERE id_paie = ?",
               (id_paie,),
           ).fetchone()
           if ligne is None:
               raise KeyError(f"Aucune paie trouvée pour id_paie={id_paie!r}.")
           payload_json, payload_input_json = ligne
           resultat = PayrollResult.model_validate_json(payload_json)
           payroll_input = (
               PayrollInput.model_validate_json(payload_input_json)
               if payload_input_json is not None
               else None
           )
           return (resultat, payroll_input)
   ```
   **Impact de rupture** : tous les appelants existants de `lire_paie` (`app/pages_ui/formulaire_paie.py::_section_nouvelle_paie`, `::_section_corriger_paie`, ainsi que tout autre module — vérifié : `app/logique_metier/dernieres_paies.py` n'appelle pas `lire_paie`, il fait sa propre lecture SQL directe) doivent être mis à jour pour déstructurer le couple retourné. C'est un changement de forme localisé et volontaire, pas une régression — chaque appelant actuel n'utilisait déjà le retour que comme un `PayrollResult` unique ; la mise à jour consiste à ajouter `, payroll_input_relu = ` (ou `_` si non utilisé) à chaque site d'appel.

7. **`lire_historique_paie`** — extension symétrique, retourne un tuple de couples :
   ```python
   def lire_historique_paie(
       employe_id: str,
       annee_fiscale: int,
       numero_periode: int,
       chemin_bd: str | Path = chemin_bd_production(),
   ) -> tuple[tuple[PayrollResult, PayrollInput | None], ...]:
       """... (docstring existante conservée, complétée) ..."""
       with _connexion(chemin_bd) as connexion:
           _creer_schema_si_absent(connexion)
           lignes = connexion.execute(
               "SELECT payload_json, payload_input_json FROM paies "
               "WHERE employe_id = ? AND annee_fiscale = ? AND numero_periode = ? "
               "ORDER BY version ASC",
               (employe_id, annee_fiscale, numero_periode),
           ).fetchall()
           resultats = []
           for payload_json, payload_input_json in lignes:
               resultat = PayrollResult.model_validate_json(payload_json)
               payroll_input = (
                   PayrollInput.model_validate_json(payload_input_json)
                   if payload_input_json is not None
                   else None
               )
               resultats.append((resultat, payroll_input))
           return tuple(resultats)
   ```
   Aucun appelant actuel de `lire_historique_paie` n'a été identifié dans `app/` (grep : seul `register.py`/tests) — impact de rupture nul en pratique, extension purement additive pour cette fonction.

---

**File**: `payroll_engine/net_pay.py`

**Aucun changement.** `assembler_paie` continue de recevoir un `PayrollInput` en argument et de retourner un `PayrollResult` seul — le contrat de cette fonction n'est PAS étendu (règle 02 : aucune nouvelle trace, et le design décide délibérément de garder l'orchestrateur fiscal totalement étranger à la question de persistance). C'est l'**appelant** (`app/pages_ui/formulaire_paie.py`) qui conserve le `PayrollInput` déjà en sa possession (il vient de le construire lui-même via `construire_payroll_input`) pour le transmettre séparément à `inserer_paie`/`remplacer_paie`.

---

**File**: `app/pages_ui/formulaire_paie.py` (suite — flux d'enregistrement)

**Fonctions**: `_section_enregistrement`, `_section_corriger_paie` (bloc de remplacement), préchargement de brouillon

**Specific Changes**:

8. **`_section_enregistrement`** — transmission du `PayrollInput` conservé en session à `inserer_paie` :
   ```python
   def _section_enregistrement(
       paie_assemblee: PayrollResult,
       payroll_input_assemble: PayrollInput,
       annee_fiscale: int,
       *,
       cle_prefixe: str,
   ) -> None:
       ...
       def _inserer() -> str:
           inserer_paie(
               paie_a_inserer,
               saison,
               payroll_input=payroll_input_assemble,
               chemin_bd=chemin_bd_production(),
           )
           return paie_a_inserer.id_paie
       ...
   ```
   Le paramètre `payroll_input_assemble` est lu depuis `st.session_state["fp_nouvelle_payroll_input_assemble"]` (ou `fp_corriger_payroll_input_reassemble`) par l'appelant de `_section_enregistrement`.

9. **`_section_corriger_paie`** — le bloc `_remplacer()` transmet de même le `PayrollInput` conservé :
   ```python
   def _remplacer() -> str:
       remplacer_paie(
           ancien_id,
           nouveau_resultat,
           saison,
           nouveau_payroll_input=st.session_state.get(
               "fp_corriger_payroll_input_reassemble"
           ),
           chemin_bd=chemin_bd_production(),
       )
       return nouveau_resultat.id_paie
   ```

10. **Préchargement de brouillon** (`_section_nouvelle_paie`) — mise à jour de l'appel à `lire_paie` (déstructuration du couple) et transmission du `PayrollInput` relu à `valeurs_effectives_depuis_paie` :
    ```python
    resultat_brouillon = executer_avec_capture(
        lambda: lire_paie(
            id_paie_brouillon_precharge, chemin_bd=chemin_bd_production()
        )
    )
    if isinstance(resultat_brouillon, ErreurDomaineAffichable):
        st.error(...)
    else:
        paie_brouillon, payroll_input_brouillon = resultat_brouillon
        valeurs_precharge = valeurs_effectives_depuis_paie(
            paie_brouillon, payroll_input_brouillon
        )
        if "total_heures_normales" in valeurs_precharge:
            st.info(
                "Formulaire pré-rempli depuis le brouillon "
                f"'{id_paie_brouillon_precharge}', y compris les heures."
            )
        else:
            st.info(
                "Formulaire pré-rempli depuis le brouillon "
                f"'{id_paie_brouillon_precharge}' — les heures doivent "
                "être ressaisies (brouillon créé avant la mise à jour "
                "permettant leur restitution)."
            )
    ```
    Les 2 nouveaux champs de saisie (point 1 ci-dessus) utilisent `valeurs_precharge.get("total_heures_normales", "0.00")` / `.get("total_heures_supplementaires", "0.00")` comme valeur par défaut, au lieu du littéral fixe `"0.00"` — cohérent avec le pré-remplissage déjà appliqué aux autres champs du formulaire.

## Testing Strategy

### Validation Approach

Approche duale, cohérente avec `net-cumuls-registre` : d'abord des tests exploratoires sur le code AVANT correction pour confirmer la root cause (déjà confirmée par lecture directe — cette étape sert de non-régression documentaire plutôt que de découverte), puis des tests de correction (Fix Checking) et de préservation (Preservation Checking) sur le code APRÈS correction.

### Exploratory Bug Condition Checking

**Goal**: Documenter, par un test qui échoue sur le code non corrigé, l'absence de fonction de répartition (Bug 1) et l'absence de colonne de persistance du `PayrollInput` (Bug 2) — confirme la root cause déjà établie par lecture de code.

**Test Plan**: Écrire un test qui importe `repartir_heures_sur_semaines` depuis `app.logique_metier.formulaire_paie` (échoue par `ImportError`/`AttributeError` avant correction) et un test qui insère une paie puis vérifie l'absence de la colonne `payload_input_json` via `PRAGMA table_info` (échoue par assertion avant correction).

**Test Cases**:
1. **Absence de fonction de répartition** : `from app.logique_metier.formulaire_paie import repartir_heures_sur_semaines` échoue avant correction.
2. **Absence de colonne** : `PRAGMA table_info(paies)` ne contient pas `payload_input_json` avant correction.
3. **`lire_paie` retourne un `PayrollResult` seul** : avant correction, `lire_paie(id_paie)` ne peut pas être déstructuré en couple — échoue par `TypeError` (« cannot unpack non-iterable PayrollResult »).
4. **`valeurs_effectives_depuis_paie` ne restitue jamais les heures** : avant correction, le dict retourné ne contient jamais `total_heures_normales`/`total_heures_supplementaires`, quel que soit l'argument.

**Expected Counterexamples**:
- Les 4 tests ci-dessus échouent systématiquement avant correction — confirment que les 2 bugs sont bien structurels et non intermittents.

### Fix Checking

**Goal**: Vérifier que pour toute entrée où la bug condition est vraie, le code corrigé produit le comportement attendu.

**Pseudocode:**
```
FOR ALL X WHERE isBugCondition_Heures(X) DO
  formulaire ← rendre_formulaire_paie'(X)
  ASSERT nombre_champs_heures(formulaire) == 2
  hn1_hs1, hn2_hs2 ← repartir_heures_sur_semaines(X.total_hn, X.total_hs)
  ASSERT somme_normales(hn1_hs1, hn2_hs2) == X.total_hn
     AND somme_supplementaires(hn1_hs1, hn2_hs2) == X.total_hs
END FOR

FOR ALL X WHERE isBugCondition_Brouillon(X) AND X.paie_creee_apres_deploiement DO
  inserer_paie'(resultat, saison, payroll_input=X.payroll_input)
  resultat_relu, payroll_input_relu ← lire_paie'(resultat.id_paie)
  valeurs ← valeurs_effectives_depuis_paie'(resultat_relu, payroll_input_relu)
  ASSERT valeurs["total_heures_normales"] == X.payroll_input.total_heures_normales
     AND valeurs["total_heures_supplementaires"] == X.payroll_input.total_heures_supplementaires
END FOR
```

### Preservation Checking

**Goal**: Vérifier que pour toute entrée où la bug condition ne tient pas (ou pour les paies pré-correction), le code corrigé produit le même résultat qu'avant.

**Pseudocode:**
```
FOR ALL payroll_input WHERE NOT isBugCondition_Heures(payroll_input) DO
  ASSERT calcul_gains(payroll_input, params) == calcul_gains_original(payroll_input, params)
END FOR

FOR ALL X WHERE isBugCondition_Brouillon(X) AND NOT X.paie_creee_apres_deploiement DO
  resultat_relu, payroll_input_relu ← lire_paie'(X.id_paie)   // colonne NULL
  ASSERT payroll_input_relu IS None
  valeurs ← valeurs_effectives_depuis_paie'(resultat_relu, payroll_input_relu)
  ASSERT "total_heures_normales" NOT IN valeurs
     AND "total_heures_supplementaires" NOT IN valeurs
END FOR
```

**Testing Approach**: Property-based testing (Hypothesis) est recommandé pour Property 1 et Property 3 (neutralité fiscale de la répartition) — génère de nombreuses répartitions internes candidates et vérifie que `calcul_gains` produit le même résultat pour toutes, catchant tout couplage caché entre répartition et calcul qu'un test manuel pourrait manquer.

**Test Plan**: Observer d'abord le comportement du code NON corrigé (4 champs, aucune colonne `payload_input_json`) pour établir la référence, puis écrire les tests de correction et de préservation sur le code corrigé.

**Test Cases**:
1. **Répartition arbitraire et neutralité fiscale** : pour des totaux Hypothesis-générés, `calcul_gains` appliqué à `repartir_heures_sur_semaines(...)` produit le même `GainsDecomposes` que pour toute autre répartition respectant les mêmes 2 totaux (Property 1, Property 3).
2. **Round-trip complet** : insertion puis relecture d'une paie avec `PayrollInput`, vérification que `valeurs_effectives_depuis_paie` restitue exactement les 2 totaux d'origine (Property 2).
3. **Préservation des paies pré-correction** : une ligne insérée directement en SQL sans colonne `payload_input_json` (simulant une base pré-existante) est relue sans exception, `payroll_input_relu is None`, et `valeurs_effectives_depuis_paie` ne contient pas les clés d'heures (Property 4).
4. **Migration additive idempotente** : appeler `_creer_schema_si_absent` deux fois sur la même connexion ne lève pas d'erreur (`ALTER TABLE` non ré-exécuté grâce à la vérification `PRAGMA table_info`).

### Unit Tests

- `repartir_heures_sur_semaines` : cas nominal, cas `0.00`/`0.00`, cas valeurs à la borne `168` (rejeté par `HeuresParSemaine`, propagé sans interception).
- Schéma SQL : `PRAGMA table_info(paies)` contient `payload_input_json` comme colonne nullable (`notnull == 0`) après `_creer_schema_si_absent`, aussi bien sur une base neuve que sur une base migrée depuis l'ancien schéma (créée manuellement avec l'ancien DDL puis migrée).
- `inserer_paie`/`remplacer_paie` avec `payroll_input=None` explicite : `payload_input_json` reste `NULL` (compatibilité arrière du paramètre optionnel).
- `lire_paie`/`lire_historique_paie` sur une ligne avec `payload_input_json` `NULL` : retourne `payroll_input is None`, aucune exception.
- `valeurs_effectives_depuis_paie(resultat, None)` : dict retourné ne contient pas les 2 clés d'heures (comportement Req 3.4 explicitement testé).
- `valeurs_effectives_depuis_paie(resultat, payroll_input)` : dict retourné contient les 2 clés d'heures, valeurs égales aux sommes de `payroll_input.heures_par_semaine`.

### Property-Based Tests

- **Property 1 / Property 3** (Hypothesis) : génère `total_heures_normales`, `total_heures_supplementaires` dans `[0, 168]` (bornes `HeuresParSemaine`) et des `PayrollInput`/`ParametresAnnee` valides quelconques ; vérifie que `calcul_gains` appliqué à `repartir_heures_sur_semaines(...)` égale `calcul_gains` appliqué à une répartition alternative générée (ex. 50/50, ou toute-sur-semaine-2) pour les mêmes 2 totaux.
- **Property 2** (Hypothesis + base temporaire `tmp_path`) : génère des `PayrollInput`/`PayrollResult` valides, insère via `inserer_paie(..., payroll_input=...)`, relit via `lire_paie`, vérifie l'égalité stricte des 2 totaux restitués par `valeurs_effectives_depuis_paie` avec ceux du `PayrollInput` d'origine.
- **Property 4** (Hypothesis + base temporaire) : génère des lignes insérées avec `payload_input_json` `NULL` (simulant l'état pré-correction) et vérifie l'absence d'exception et l'absence des clés d'heures dans `valeurs_effectives_depuis_paie`.

### Integration Tests

- Flux complet Formulaire_Paie : saisie de 2 totaux → assemblage → enregistrement en `BROUILLON` → reprise du même brouillon → vérification que les 2 champs de saisie affichent les 2 totaux d'origine (test au niveau `app/logique_metier/formulaire_paie.py`, sans dépendance à Streamlit — la logique de rendu Streamlit elle-même n'est pas testée automatiquement, cohérent avec le reste du projet).
- Flux Action_Corriger inchangé : une paie `EMISE` corrigée via `remplacer_paie` avec un nouveau `PayrollInput` continue de produire une nouvelle version incrémentée, avec `cumuls_ytd` recalculés à l'identique du comportement pré-correction (aucune régression sur `net-cumuls-registre`).
- Test de non-régression golden : les 6 scénarios QC001–QC006 assemblés puis insérés via `inserer_paie(..., payroll_input=payroll_input_fixture)` puis relus via `lire_paie` reproduisent toujours `net`/`cout_employeur`/`cumuls_fin` au cent près (aucune modification de `payload_json`, seule l'ajout de `payload_input_json` est en jeu).
