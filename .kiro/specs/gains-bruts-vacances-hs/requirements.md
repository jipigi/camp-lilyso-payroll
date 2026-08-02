# Requirements Document

<!-- Titre métier : Document d'exigences — gains-bruts-vacances-hs. Les en-têtes structurels de niveau supérieur (Requirements Document, Introduction, Glossary, Requirements) et les libellés « Requirement N », « User Story: », « Acceptance Criteria » sont maintenus en anglais pour la conformité au format Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec implémente **l'étape 2** du plan d'implémentation
(`docs/plan-implementation.md`), immédiatement après le socle contractuel
`moteur-paie-contrats` livré en étape 1. Elle définit et impose la
fonction pure `calcul_gains` qui prend en entrée un `PayrollInput`
figé et les paramètres annuels versionnés, et produit en sortie la
décomposition typée `GainsDecomposes` (salaire régulier, heures
supplémentaires, jours fériés manuels, indemnité de vacances, brut
total) accompagnée d'une `CalculationTrace` auditée.

**Périmètre strict** : seuls le calcul du **brut** et sa trace sont
couverts. Aucune retenue (RRQ, RQAP, AE, impôt QC, impôt fédéral) ni
aucune charge patronale (FSS, CNESST, CNT) n'est calculée ici — ces
capacités relèvent des specs 3 à 8 du plan d'implémentation. Aucun
contrat de `moteur-paie-contrats` n'est modifié ni étendu : cette spec
ne fait que **consommer** `PayrollInput`, `ParametresAnnee`,
`GainsDecomposes`, `CalculationTrace` et les exceptions du domaine.

**Contrats consommés sans modification** (déjà figés par
`moteur-paie-contrats`, 55/55 tâches livrées, 605 tests) :

- `models.payroll_input.PayrollInput` — porte 2 `HeuresParSemaine`, un
  `taux_horaire_effectif` strictement positif, un `taux_vacances` ∈
  `{Decimal("0.04"), Decimal("0.06")}`, un `jours_feries_manuels`
  ≥ 0, et refuse déjà par construction les cas hors matrice (province
  ≠ QC, fréquence ≠ aux deux semaines).
- `models.payroll_result.GainsDecomposes` — sept champs :
  `salaire_regulier`, `heures_supplementaires_montant`, `vacances`,
  `jours_feries_manuels`, `brut_total`, `multiplicateur_heures_supp`,
  `seuil_heures_supp_hebdo`, tous en `Decimal`, tous ≥ 0 (les deux
  derniers > 0), immuable après construction.
- `models.trace.CalculationTrace` — signature de trace exigée par la
  règle 02 (source officielle sur liste blanche, année, section,
  paramètres, entrées, sous-totaux nommés, arrondissement, résultat).
- `payroll_engine.parameters_loader.ParametresAnnee` — expose
  `frequence_paie`, `vacances`, `heures_supplementaires` déjà typés.

**Corpus de validation** : les six scénarios QC001–QC006 documentés
dans `docs/scenario-qc0*.md` doivent être reproduits **au cent près**
sur la section `gains` de leurs fixtures de sortie
(`tests/fixtures/outputs/qc0*.json`). Ce corpus fixe la définition
opérationnelle de « conformité » de cette spec.

**Limitation connue du corpus actuel (à lever ultérieurement)** : les
fixtures QC001–QC006 portent une répartition hebdomadaire des heures
qui est une **fabrication 50/50** du total période sur les deux
semaines constituantes. Les valeurs WebRAS et PDOC de référence ont
été calculées sur les **totaux de période**, pas sur des semaines
individuelles. Cette spec calcule donc le `salaire_regulier` et le
`heures_supplementaires_montant` comme des sommes sur les deux
semaines qui sont **mathématiquement équivalentes** à un calcul
direct sur les totaux (multiplication linéaire), mais elle ne prétend
**pas** que la décomposition hebdomadaire des fixtures actuelles est
auditée. Une révision future du corpus est prévue pour saisir des
valeurs WebRAS et PDOC réellement calibrées semaine par semaine
(nouvelles captures officielles nécessaires) — jusqu'à cette
révision, la reproduction au cent près ne porte que sur les totaux
de période.

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire, `float` interdit dans la
  fonction et ses intermédiaires
- Règle 02 — retour `(GainsDecomposes, CalculationTrace)` avec source
  officielle sur la liste blanche de `CalculationTrace`
- Règle 03 — cas hors matrice déjà refusés par `PayrollInput` ; cette
  spec s'appuie sur ce refus et n'introduit pas de garde-fou redondant
  au-delà de la validation d'un `taux_vacances` supporté
- Règle 04 — aucune donnée personnelle réelle dans les tests ou
  exemples ; corpus anonymisé QC001–QC006 uniquement
- Règle 05 — tous les paramètres (`multiplicateur_heures_supp`,
  `seuil_heures_supp_hebdo`, taux de vacances par défaut) proviennent
  exclusivement de `parameters/<AAAA>/quebec.json` ; aucune valeur en
  dur dans le code Python
- Règle 06 — spec → tests (property + golden) → implémentation →
  validation ; tests écrits avant code

**Livrables ratifiés par les requirements** :

- `payroll_engine/gains_bruts.py` — fonction publique `calcul_gains`
- Ajout ou vérification, dans `parameters/2026/quebec.json`, des clés
  `heures_supplementaires.multiplicateur` (chaîne `"1.5"`) et
  `heures_supplementaires.seuil_hebdomadaire_heures` (chaîne `"40"`)

## Glossary

- **Moteur_Gains** : le module de calcul des gains bruts, considéré
  comme un système unique dont la frontière est définie par la
  signature `calcul_gains(payroll_input, parametres_annee) ->
  tuple[GainsDecomposes, CalculationTrace]`.
- **Fonction_Calcul_Gains** : la fonction publique `calcul_gains`
  livrée dans `payroll_engine/gains_bruts.py`, dont le contrat est
  imposé par cette spec.
- **Salaire_Regulier** : montant des heures normales de la période,
  soit la somme sur les semaines constituantes de
  `heures_normales_semaine × taux_horaire_effectif`.
- **Heures_Supplementaires_Montant** : montant des heures
  supplémentaires de la période, soit la somme sur les semaines
  constituantes de `heures_supplementaires_semaine ×
  taux_horaire_effectif × multiplicateur_heures_supp`.
- **Base_Vacances** : montant sur lequel l'indemnité de vacances est
  calculée, soit `Salaire_Regulier + Heures_Supplementaires_Montant +
  jours_feries_manuels`. Exclut explicitement l'indemnité de vacances
  elle-même.
- **Indemnite_Vacances** : montant de l'indemnité de vacances de la
  période, soit `Base_Vacances × taux_vacances`.
- **Brut_Total** : gain brut total de la période, soit
  `Salaire_Regulier + Heures_Supplementaires_Montant +
  jours_feries_manuels + Indemnite_Vacances`.
- **Composante_De_Brut** : l'une des cinq valeurs monétaires
  élémentaires produites par la fonction : `salaire_regulier`,
  `heures_supplementaires_montant`, `jours_feries_manuels`
  (recopié depuis l'entrée), `vacances`, `brut_total`.
- **Multiplicateur_Heures_Supp** : coefficient de majoration des
  heures supplémentaires, valeur `Decimal("1.5")` en 2026, lue depuis
  `parameters/<AAAA>/quebec.json` section `heures_supplementaires`.
- **Seuil_Heures_Supp_Hebdo** : seuil hebdomadaire de déclenchement
  des heures supplémentaires, valeur `Decimal("40")` en 2026, lue
  depuis `parameters/<AAAA>/quebec.json`. **Valeur transportée pour
  affichage uniquement** — le Moteur_Gains ne l'utilise **pas** pour
  reclasser les heures.
- **Mode_Arrondissement_Gains** : mode d'arrondissement appliqué à
  chaque Composante_De_Brut, soit `ROUND_HALF_UP` avec précision de 2
  décimales, cohérent avec le TP-1015.G 2026.
- **Corpus_Golden** : ensemble des six scénarios QC001, QC002, QC003,
  QC004, QC005, QC006 documentés dans `docs/scenario-qc0*.md` et
  matérialisés dans `tests/fixtures/inputs/` et
  `tests/fixtures/outputs/`, section `gains`.
- **TP-1015.G** : guide de l'employeur publié par Revenu Québec ;
  contient les règles d'assemblage du salaire brut, y compris le
  traitement de l'indemnité de vacances et l'arrondissement monétaire
  au cent.
- **Loi_Normes_Travail_QC** : Loi sur les normes du travail du Québec,
  source des règles « heures supplémentaires × 1,5 au-delà de 40 h par
  semaine » et « indemnité de vacances 4 % ou 6 % ».
- **PayrollInput** : contrat d'entrée figé par `moteur-paie-contrats`
  (Req 3 de cette spec). Cette spec **ne le modifie pas**.
- **GainsDecomposes** : sous-modèle de sortie figé par
  `moteur-paie-contrats` (Req 4 AC1 et AC14 de cette spec). Cette spec
  **ne le modifie pas** et se contente de construire une instance
  valide.
- **CalculationTrace** : contrat de trace figé par
  `moteur-paie-contrats` (Req 5 de cette spec). Cette spec **ne le
  modifie pas** et se contente de construire une instance valide dont
  la `source` figure dans la liste blanche.
- **ParametresAnnee** : objet retourné par `load_parameters(annee,
  juridiction)`, figé par `moteur-paie-contrats` (Req 9 de cette
  spec). Cette spec **ne le modifie pas**.
- **UnsupportedPayrollCase** : exception du domaine définie par
  `moteur-paie-contrats` (Req 8), levée à la frontière pour tout cas
  hors matrice Camp LilySO (règle 03).

## Requirements

<!-- Chaque « Requirement N » ci-dessous est une exigence métier rédigée en français. -->

### Requirement 1: Point d'entrée unique et signature imposée

**User Story:** En tant qu'orchestrateur du moteur de paie, je veux
un point d'entrée public unique et typé pour calculer le brut d'une
paie, afin de garantir que toutes les paies d'un même employeur
passent par la même formule d'assemblage, avec la même trace, et sans
paramètre implicite hérité d'un état global.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT exposer une fonction publique nommée
   `calcul_gains` dans le module `payroll_engine.gains_bruts`, dont la
   signature exacte est
   `calcul_gains(payroll_input: PayrollInput, parametres_annee: ParametresAnnee) -> tuple[GainsDecomposes, CalculationTrace]`.
2. LA Fonction_Calcul_Gains DOIT être une **fonction pure** au sens
   suivant : deux appels successifs avec le même `PayrollInput` et le
   même `ParametresAnnee` DOIVENT retourner deux tuples égaux au sens
   `==` (aussi bien sur `GainsDecomposes` que sur `CalculationTrace`),
   sans état interne persistant, sans lecture ou écriture de fichier,
   sans variable de module mutable et sans appel à `datetime.now()` ou
   à toute autre source de non-déterminisme.
3. LA Fonction_Calcul_Gains NE DOIT PAS invoquer directement
   `load_parameters` — les paramètres DOIVENT être injectés par le
   second argument `parametres_annee`. Cette contrainte garantit que
   la fonction reste testable en isolation avec des paramètres
   fabriqués.
4. LA Fonction_Calcul_Gains DOIT retourner un tuple à exactement deux
   éléments : le premier de type `GainsDecomposes`, le second de type
   `CalculationTrace`.
5. LA Fonction_Calcul_Gains NE DOIT PAS lever d'exception non
   documentée. LES seules exceptions autorisées sont :
   `UnsupportedPayrollCase` (règle 03, voir Requirement 10),
   `MissingParameterError` (règle 05, voir Requirement 9) et
   `pydantic.ValidationError` propagée par la construction du
   `GainsDecomposes` ou de la `CalculationTrace` retournés.
6. LA Fonction_Calcul_Gains DOIT être importable via
   `from payroll_engine.gains_bruts import calcul_gains` sans effet de
   bord (aucune action au moment de l'import : pas de lecture de
   fichier, pas d'ouverture de connexion, pas d'appel réseau).

---

### Requirement 2: Calcul du salaire régulier sur la période

**User Story:** En tant que responsable de la paie, je veux que le
salaire régulier soit calculé à partir des heures normales saisies
dans `PayrollInput`, afin que le montant final soit reconstructible
au cent près à partir des seules données d'entrée du contrat, sans
recours à une donnée externe.

**Note sur la granularité** : le calcul agrège les deux semaines
constituantes de `payroll_input.heures_par_semaine`. La formule est
linéaire, donc mathématiquement équivalente à un calcul direct sur
les totaux (`heures_normales_totales × taux_horaire_effectif`). La
décomposition hebdomadaire n'est **pas** validée au cent près par le
corpus actuel (voir la limitation connue documentée dans
l'Introduction).

#### Acceptance Criteria

1. LE Moteur_Gains DOIT calculer le Salaire_Regulier comme la somme,
   sur les deux semaines constituantes de
   `payroll_input.heures_par_semaine`, du produit
   `HeuresParSemaine.heures_normales ×
   PayrollInput.taux_horaire_effectif`. Cette formulation est
   équivalente à `heures_normales_totales × taux_horaire_effectif`
   par linéarité de la multiplication `Decimal` ; les deux
   expressions produisent le même résultat au cent près.
2. LE Moteur_Gains NE DOIT PAS multiplier les heures normales par le
   Multiplicateur_Heures_Supp — le multiplicateur s'applique
   exclusivement aux heures supplémentaires (voir Requirement 3).
3. LE Moteur_Gains DOIT typer le Salaire_Regulier en `decimal.Decimal`
   et l'arrondir à deux décimales selon le Mode_Arrondissement_Gains
   avant de le placer dans `GainsDecomposes.salaire_regulier` (voir
   Requirement 7).
4. LORSQUE la somme des `heures_normales` sur les deux semaines vaut
   `Decimal("0")`, LE Moteur_Gains DOIT produire un Salaire_Regulier
   égal à `Decimal("0.00")` sans lever d'exception.
5. LE Moteur_Gains NE DOIT introduire aucun `float` intermédiaire dans
   le calcul du Salaire_Regulier (règle 01) ; tous les opérandes et
   résultats intermédiaires DOIVENT être des `Decimal`.

---

### Requirement 3: Calcul du montant des heures supplémentaires sur la période

**User Story:** En tant que responsable de la paie, je veux que le
montant des heures supplémentaires soit calculé à partir des heures
supp saisies dans `PayrollInput` et majoré par le multiplicateur
fiscal courant, afin que le bulletin puisse afficher la formule
appliquée (par exemple `10 h × 21,00 $ × 1,5 = 315,00 $`) et que le
montant soit conforme aux Normes du travail du Québec.

**Note sur la granularité** : le calcul agrège les deux semaines
constituantes de `payroll_input.heures_par_semaine`. Comme pour le
salaire régulier, la formule est linéaire et donc équivalente à un
calcul direct sur les totaux. La décomposition hebdomadaire des
heures supplémentaires n'est pas validée par le corpus actuel — voir
la limitation connue documentée dans l'Introduction.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT calculer le Heures_Supplementaires_Montant
   comme la somme, sur les deux semaines constituantes de
   `payroll_input.heures_par_semaine`, du produit
   `HeuresParSemaine.heures_supplementaires ×
   PayrollInput.taux_horaire_effectif × Multiplicateur_Heures_Supp`.
   Cette formulation est équivalente à
   `heures_supplementaires_totales × taux_horaire_effectif ×
   Multiplicateur_Heures_Supp` par linéarité.
2. LE Moteur_Gains DOIT lire le Multiplicateur_Heures_Supp depuis
   `parametres_annee.heures_supplementaires.multiplicateur` et ne
   JAMAIS le coder en dur dans le code Python (règle 05).
3. LE Moteur_Gains DOIT propager le Multiplicateur_Heures_Supp lu
   dans `GainsDecomposes.multiplicateur_heures_supp` sans
   transformation (Req 4 AC14 de `moteur-paie-contrats`).
4. LE Moteur_Gains DOIT propager la valeur
   `parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures`
   dans `GainsDecomposes.seuil_heures_supp_hebdo` sans transformation
   (Req 4 AC14 de `moteur-paie-contrats`).
5. LE Moteur_Gains NE DOIT PAS utiliser le Seuil_Heures_Supp_Hebdo
   pour reclasser les heures. LE Moteur_Gains DOIT accepter tel quel
   le découpage `heures_normales / heures_supplementaires` fourni par
   `payroll_input.heures_par_semaine`, y compris lorsque
   `heures_normales > seuil_hebdomadaire_heures` sur une semaine ou
   lorsque `heures_supplementaires > 0` sans que `heures_normales`
   n'atteigne le seuil (décision de conception documentée dans
   `docs/hypotheses-2026.md` §9).
6. LORSQUE la somme des `heures_supplementaires` sur les deux
   semaines vaut `Decimal("0")`, LE Moteur_Gains DOIT produire un
   Heures_Supplementaires_Montant égal à `Decimal("0.00")` sans
   lever d'exception.
7. LE Moteur_Gains DOIT typer le Heures_Supplementaires_Montant en
   `decimal.Decimal` et l'arrondir à deux décimales selon le
   Mode_Arrondissement_Gains avant de le placer dans
   `GainsDecomposes.heures_supplementaires_montant` (voir Requirement 7).
8. LE Moteur_Gains NE DOIT introduire aucun `float` intermédiaire
   dans le calcul du Heures_Supplementaires_Montant (règle 01).

---

### Requirement 4: Consommation stricte des heures fournies par l'utilisateur

**User Story:** En tant que responsable de la paie qui prépare les
heures dans un tableur externe, je veux que le moteur accepte tel
quel mon découpage `heures_normales / heures_supplementaires` par
semaine, afin que ma classification manuelle (basée sur les
Normes du travail, sur les fériés, sur les gardes de nuit et sur les
règles internes du camp) soit préservée sans être réinterprétée.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT traiter `HeuresParSemaine.heures_normales` et
   `HeuresParSemaine.heures_supplementaires` comme des **faits
   d'entrée**, jamais comme des données à recalculer.
2. LE Moteur_Gains NE DOIT PAS reclasser une portion de
   `heures_normales` en `heures_supplementaires` ni l'inverse, quelle
   que soit la valeur de `heures_normales` par rapport au
   Seuil_Heures_Supp_Hebdo.
3. LE Moteur_Gains NE DOIT PAS déclencher d'avertissement, de log,
   ni d'exception lorsque `heures_normales > seuil_hebdomadaire_heures`
   sur une semaine donnée. LE respect ou non de la Loi_Normes_Travail_QC
   pour la classification incombe à l'utilisateur ou à un module de
   pré-traitement extérieur à cette spec.
4. LE Moteur_Gains DOIT accepter la valeur `Decimal("0")` pour
   `heures_normales` et pour `heures_supplementaires` sans traitement
   spécial : un produit `0 × taux × multiplicateur = 0` reste un
   `Decimal` valide.
5. LE Moteur_Gains DOIT accepter des heures fractionnaires (par
   exemple `Decimal("20.25")`, `Decimal("40.5")`) comme le montrent
   QC004 et QC006 du Corpus_Golden.

---

### Requirement 5: Calcul de l'indemnité de vacances

**User Story:** En tant que responsable de la paie du Camp LilySO,
je veux que l'indemnité de vacances soit calculée selon la Loi sur
les normes du travail du Québec à partir du gain admissible de la
période, afin que le montant versé à chaque paie soit reproductible
au cent près et conforme au taux applicable de l'employé.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT calculer la Base_Vacances comme la somme
   ordonnée `Salaire_Regulier + Heures_Supplementaires_Montant +
   PayrollInput.jours_feries_manuels`, où chaque terme est un
   `Decimal` déjà arrondi selon le Mode_Arrondissement_Gains.
2. LE Moteur_Gains DOIT calculer l'Indemnite_Vacances comme
   `Base_Vacances × PayrollInput.taux_vacances`.
3. LE Moteur_Gains NE DOIT PAS inclure l'Indemnite_Vacances elle-même
   dans la Base_Vacances (pas de vacances sur vacances).
4. LE Moteur_Gains DOIT accepter `PayrollInput.taux_vacances` dans
   l'ensemble `{Decimal("0.04"), Decimal("0.06")}` et **uniquement**
   ces deux valeurs, cet ensemble étant déjà garanti par contrat de
   `PayrollInput` (Req 3.5 de `moteur-paie-contrats`).
5. LORSQUE `PayrollInput.jours_feries_manuels` vaut `Decimal("0.00")`
   (valeur par défaut du contrat `PayrollInput`), LE Moteur_Gains DOIT
   calculer la Base_Vacances comme `Salaire_Regulier +
   Heures_Supplementaires_Montant` uniquement.
6. LE Moteur_Gains DOIT typer l'Indemnite_Vacances en `decimal.Decimal`
   et l'arrondir à deux décimales selon le Mode_Arrondissement_Gains
   avant de la placer dans `GainsDecomposes.vacances` (voir Requirement 7).
7. LE Moteur_Gains NE DOIT PAS coder en dur les taux `Decimal("0.04")`
   ou `Decimal("0.06")` dans son propre code (règle 05) — la valeur
   effective provient de `PayrollInput.taux_vacances`, et la matrice
   des taux supportés est portée par `PayrollInput` et par
   `parametres_annee.vacances`.
8. LE Moteur_Gains DOIT documenter dans la CalculationTrace le taux
   de vacances effectivement appliqué et la Base_Vacances utilisée
   (voir Requirement 8).

---

### Requirement 6: Assemblage et exposition du brut total

**User Story:** En tant que consommateur du `PayrollResult`, je veux
que le brut total soit la somme exacte de ses quatre composantes et
que chacune reste inspectable individuellement, afin de garantir
l'identité comptable en aval et d'afficher chaque ligne sur le
bulletin de paie.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT calculer le Brut_Total comme
   `Salaire_Regulier + Heures_Supplementaires_Montant +
   PayrollInput.jours_feries_manuels + Indemnite_Vacances`, chaque
   terme étant lu après arrondissement à deux décimales.
2. LE Moteur_Gains DOIT recopier `PayrollInput.jours_feries_manuels`
   dans `GainsDecomposes.jours_feries_manuels` sans transformation ni
   recalcul.
3. LE Moteur_Gains DOIT produire un `GainsDecomposes` dont les sept
   champs `Decimal` sont peuplés : `salaire_regulier`,
   `heures_supplementaires_montant`, `vacances`,
   `jours_feries_manuels`, `brut_total`, `multiplicateur_heures_supp`,
   `seuil_heures_supp_hebdo`.
4. LE Moteur_Gains DOIT garantir l'identité
   `brut_total == salaire_regulier + heures_supplementaires_montant +
   jours_feries_manuels + vacances` au cent près (comparaison `==` sur
   `Decimal`, tolérance nulle — règle 01), après application de
   l'arrondissement à deux décimales sur chaque composante et sur le
   brut lui-même. SI cette identité est violée après arrondissement,
   ALORS LE Moteur_Gains DOIT lever une erreur explicite plutôt que
   de retourner un `GainsDecomposes` incohérent.
5. LE `GainsDecomposes` retourné DOIT satisfaire toutes les
   contraintes de son propre contrat (Req 4 AC1 et AC14 de
   `moteur-paie-contrats`) : cinq composantes ≥ 0, deux valeurs de
   contexte > 0, refus de `float`, immuabilité.
6. LE Moteur_Gains NE DOIT PAS ajouter, retirer ou renommer un champ
   de `GainsDecomposes`. Toute évolution du contrat de sortie exige
   une modification de la spec `moteur-paie-contrats`, pas une
   modification de cette spec.

---

### Requirement 7: Arrondissement à deux décimales sur chaque composante

**User Story:** En tant que responsable de la conformité fiscale, je
veux que chaque composante monétaire soit arrondie à deux décimales
selon le mode utilisé par WebRAS et par le guide de l'employeur,
afin que la reconstruction manuelle des lignes du bulletin de paie
produise exactement les mêmes montants que le moteur.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT appliquer le mode d'arrondissement
   `decimal.ROUND_HALF_UP` avec une précision de deux décimales à
   chacune des quatre composantes suivantes, dans cet ordre exact :
   Salaire_Regulier, Heures_Supplementaires_Montant,
   Indemnite_Vacances, Brut_Total.
2. LE Moteur_Gains DOIT appliquer l'arrondissement **une fois** par
   composante, et **après** l'agrégation des semaines pour
   `Salaire_Regulier` et pour `Heures_Supplementaires_Montant` (pas
   d'arrondissement intermédiaire par semaine avant sommation).
3. LE Moteur_Gains DOIT calculer l'Indemnite_Vacances à partir d'une
   Base_Vacances construite avec les composantes déjà arrondies
   (Salaire_Regulier, Heures_Supplementaires_Montant,
   jours_feries_manuels), et arrondir le produit final une seule fois.
4. LE Moteur_Gains DOIT recopier `payroll_input.jours_feries_manuels`
   sans le ré-arrondir, ce champ étant déjà normalisé à deux décimales
   par le contrat de `PayrollInput` (Req 3.6 de
   `moteur-paie-contrats`, valeur par défaut `Decimal("0.00")`).
5. LE mode et la précision d'arrondissement effectivement appliqués
   DOIVENT être exposés dans la CalculationTrace (voir Requirement 8
   AC5).
6. LE Moteur_Gains DOIT préserver le Multiplicateur_Heures_Supp et
   le Seuil_Heures_Supp_Hebdo transportés dans `GainsDecomposes`
   **sans** les ré-arrondir : ces valeurs sont des paramètres, pas
   des composantes monétaires.

---

### Requirement 8: Trace exhaustive du calcul des gains

**User Story:** En tant qu'auditeur (interne, Revenu Québec ou
Normes du travail) qui inspecte une paie plusieurs années après son
émission, je veux que la trace des gains référence la source
officielle, liste les paramètres utilisés, les entrées, les
sous-totaux intermédiaires nommés et le mode d'arrondissement,
afin de reconstruire le brut exact sans réexécuter le moteur.

#### Acceptance Criteria

1. LA Fonction_Calcul_Gains DOIT retourner une `CalculationTrace`
   dont le champ `source` est une chaîne conforme à la liste blanche
   des sources officielles portée par `CalculationTrace` (Req 5 AC2
   de `moteur-paie-contrats`, règle 02) et fait référence au TP-1015.G
   de l'année fiscale de la paie.
2. LA CalculationTrace retournée DOIT porter `annee =
   payroll_input.pay_period.annee_fiscale`, `juridiction =
   Juridiction.QUEBEC` et une chaîne `section` non vide identifiant
   la portion du TP-1015.G référencée (par exemple `"salaire brut,
   heures supplémentaires et indemnité de vacances"`).
3. LA CalculationTrace retournée DOIT exposer, dans
   `parametres_utilises`, au minimum les deux clés suivantes issues
   de `parametres_annee.heures_supplementaires` et de
   `payroll_input.taux_vacances` : `multiplicateur_heures_supp`
   (typiquement `Decimal("1.5")`) et `taux_vacances` (typiquement
   `Decimal("0.04")` ou `Decimal("0.06")`).
4. LA CalculationTrace retournée DOIT exposer, dans `entrees`, au
   minimum les clés suivantes agrégées sur les deux semaines :
   `heures_normales_totales`, `heures_supplementaires_totales`,
   `taux_horaire_effectif`, `jours_feries_manuels`.
5. LA CalculationTrace retournée DOIT exposer, dans `sous_totaux` et
   dans cet ordre : `salaire_regulier`,
   `heures_supplementaires_montant`, `base_vacances`, `vacances`.
6. LA CalculationTrace retournée DOIT porter
   `mode_arrondissement = ModeArrondissement.ROUND_HALF_UP`,
   `precision_arrondissement = 2` et `resultat = Brut_Total`.
7. LES trois dictionnaires `parametres_utilises`, `entrees` et
   `sous_totaux` DOIVENT contenir uniquement des valeurs `Decimal` ;
   aucun `float` NE DOIT y apparaître (règle 01).
8. LA CalculationTrace produite DOIT être suffisante pour permettre
   à un tiers de recalculer manuellement le Brut_Total à partir de
   ses seuls contenus (source, paramètres, entrées, sous-totaux,
   arrondissement) sans consulter ni le `PayrollInput` d'origine ni
   `parameters/<AAAA>/quebec.json`.

---

### Requirement 9: Consommation stricte des paramètres annuels versionnés

**User Story:** En tant que responsable de la mise à jour annuelle
des paramètres fiscaux, je veux que le module de gains bruts lise
100 % de ses coefficients depuis `parameters/<AAAA>/quebec.json`
sans exception, afin qu'une correction du multiplicateur d'heures
supplémentaires ou du seuil hebdomadaire ne nécessite jamais de
retoucher du code Python (règle 05).

#### Acceptance Criteria

1. LE Moteur_Gains DOIT lire le Multiplicateur_Heures_Supp depuis
   `parametres_annee.heures_supplementaires.multiplicateur`.
2. LE Moteur_Gains DOIT lire le Seuil_Heures_Supp_Hebdo depuis
   `parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures`.
3. LE Moteur_Gains NE DOIT PAS lire les taux de vacances (0,04 ou
   0,06) depuis `parametres_annee.vacances` — le taux effectivement
   appliqué provient de `PayrollInput.taux_vacances`, seul champ qui
   fait foi pour cette paie. LES valeurs de
   `parametres_annee.vacances.taux_defaut` et
   `parametres_annee.vacances.taux_alternatif` restent lues par la
   fabrique `Employee.avec_defauts_par_annee` (spec
   `moteur-paie-contrats`, Req 1 AC7), pas par cette fonction.
4. LE Moteur_Gains NE DOIT contenir aucune constante numérique
   représentant un multiplicateur, un seuil, un taux de vacances ou
   un plafond fiscal (règle 05). LES seules constantes numériques
   autorisées dans son code sont l'entier `2` (précision
   d'arrondissement, imposée par le TP-1015.G) et les valeurs `0`
   utilisées comme neutre additif pour la somme initiale.
5. SI `parametres_annee.heures_supplementaires.multiplicateur` ou
   `parametres_annee.heures_supplementaires.seuil_hebdomadaire_heures`
   est absent ou marqué `"TO_FILL"`, ALORS `load_parameters` DOIT
   avoir levé `MissingParameterError` **avant** l'appel à
   `calcul_gains` (Req 9 AC5 de `moteur-paie-contrats`) ; LE
   Moteur_Gains reçoit donc toujours un `ParametresAnnee` dont ces
   deux valeurs sont des `Decimal` valides et n'a pas à re-tester
   `"TO_FILL"`.
6. LE fichier `parameters/2026/quebec.json` DOIT contenir, dans sa
   section `heures_supplementaires`, les deux clés `multiplicateur`
   avec la valeur chaîne `"1.5"` et `seuil_hebdomadaire_heures` avec
   la valeur chaîne `"40"`. LA vérification effective de la présence
   de ces clés est un livrable de la phase de design et de tâches.

---

### Requirement 10: Cas hors matrice — délégation aux garde-fous existants

**User Story:** En tant que responsable de la robustesse du moteur,
je veux que le module de gains bruts s'appuie sur les refus déjà
portés par `PayrollInput` plutôt que de les redoubler, afin de
maintenir un seul point de vérité pour la définition de la matrice
Camp LilySO (règle 03).

#### Acceptance Criteria

1. LE Moteur_Gains DOIT compter sur le fait qu'un `PayrollInput`
   construit avec succès garantit par construction : province QC,
   fréquence aux deux semaines, taux de vacances ∈ `{0.04, 0.06}`,
   correspondance 1-à-1 entre `heures_par_semaine` et
   `pay_period.semaines`, appariement `cumuls_debut` ↔ `employee` ↔
   `pay_period` (Req 3 et Req 11 de `moteur-paie-contrats`).
2. LE Moteur_Gains NE DOIT PAS re-tester la province de travail, la
   fréquence de paie ni la longueur de `heures_par_semaine` — ces
   invariants sont déjà portés par `PayrollInput` et leur duplication
   introduirait un point de divergence.
3. QUAND `payroll_input.taux_vacances` n'appartient pas à
   `{Decimal("0.04"), Decimal("0.06")}` (situation qui ne peut
   théoriquement survenir qu'en cas de contournement de la
   validation via `PayrollInput.model_construct`), LE Moteur_Gains
   DOIT lever `UnsupportedPayrollCase` avec un message renvoyant à
   la règle 03 et citant WebRAS. Cette garde de défense en profondeur
   est le seul garde-fou de matrice que cette spec introduit.
4. LE Moteur_Gains NE DOIT PAS lever `UnsupportedPayrollCase` pour un
   `PayrollInput` dont toutes les valeurs sont conformes à la matrice
   Camp LilySO, y compris les cas extrêmes du Corpus_Golden (brut
   très faible QC006, heures fractionnaires QC004, heures
   supplémentaires importantes QC002).
5. LE Moteur_Gains NE DOIT PAS transformer une exception
   `UnsupportedPayrollCase` levée par un composant interne en une
   autre classe d'exception. LA disjonction stricte entre exceptions
   du domaine et erreurs de validation Pydantic (Req 8 AC7 de
   `moteur-paie-contrats`) DOIT être préservée.

---

### Requirement 11: Reproduction au cent près du corpus QC001 à QC006

**User Story:** En tant que garant de l'exactitude fiscale du moteur,
je veux que le module de gains bruts reproduise à l'unité de cent
près la section `gains` de chacune des six fixtures de sortie
QC001–QC006, afin d'attester que la formule d'assemblage est
compatible avec les 6 scénarios de référence documentés.

#### Acceptance Criteria

1. POUR le scénario QC001 (brut synthétique 1 516,32 $ documenté dans
   `docs/scenario-qc001.md`), LE Moteur_Gains DOIT produire un
   `GainsDecomposes` dont `brut_total == Decimal("1516.32")`,
   `vacances == Decimal("58.32")` et
   `salaire_regulier + heures_supplementaires_montant ==
   Decimal("1458.00")`.
2. POUR le scénario QC002 (brut 2 861,04 $ documenté dans
   `docs/scenario-qc002.md`, taux 21 $/h, 116 h normales et 10 h
   supp), LE Moteur_Gains DOIT produire un `GainsDecomposes` dont
   `salaire_regulier == Decimal("2436.00")`,
   `heures_supplementaires_montant == Decimal("315.00")`,
   `vacances == Decimal("110.04")` et `brut_total ==
   Decimal("2861.04")`.
3. POUR le scénario QC003 (brut 2 179,84 $ documenté dans
   `docs/scenario-qc003.md`, taux 16 $/h, 116 h normales et 10 h
   supp), LE Moteur_Gains DOIT produire un `GainsDecomposes` dont
   `salaire_regulier == Decimal("1856.00")`,
   `heures_supplementaires_montant == Decimal("240.00")`,
   `vacances == Decimal("83.84")` et `brut_total ==
   Decimal("2179.84")`.
4. POUR le scénario QC004 (brut 294,84 $ documenté dans
   `docs/scenario-qc004.md`, taux 14 $/h, 20,25 h normales et 0 h
   supp), LE Moteur_Gains DOIT produire un `GainsDecomposes` dont
   `salaire_regulier == Decimal("283.50")`,
   `heures_supplementaires_montant == Decimal("0.00")`,
   `vacances == Decimal("11.34")` et `brut_total ==
   Decimal("294.84")`.
5. POUR le scénario QC005 (brut 1 739,92 $ documenté dans
   `docs/scenario-qc005.md`, taux 14 $/h, 112 h normales et 5 h supp),
   LE Moteur_Gains DOIT produire un `GainsDecomposes` dont
   `salaire_regulier == Decimal("1568.00")`,
   `heures_supplementaires_montant == Decimal("105.00")`,
   `vacances == Decimal("66.92")` et `brut_total ==
   Decimal("1739.92")`.
6. POUR le scénario QC006 (brut 505,44 $ documenté dans
   `docs/scenario-qc006.md`, taux 12 $/h, 40,5 h normales et 0 h
   supp), LE Moteur_Gains DOIT produire un `GainsDecomposes` dont
   `salaire_regulier == Decimal("486.00")`,
   `heures_supplementaires_montant == Decimal("0.00")`,
   `vacances == Decimal("19.44")` et `brut_total ==
   Decimal("505.44")`.
7. POUR chacun des six scénarios QC001 à QC006, LE `GainsDecomposes`
   produit par LE Moteur_Gains DOIT être **égal au sens `==`** au
   `GainsDecomposes` reconstruit depuis la section `gains` de la
   fixture de sortie correspondante
   (`tests/fixtures/outputs/qc00X.json`), champ par champ, sans
   tolérance.
8. POUR chacun des six scénarios QC001 à QC006, LA CalculationTrace
   retournée par LE Moteur_Gains DOIT porter `resultat` égal au
   `brut_total` du `GainsDecomposes` correspondant.

---

### Requirement 12: Interdiction transversale de `float` dans le module

**User Story:** En tant que responsable de la qualité fiscale du
moteur, je veux qu'aucun `float` ne puisse se glisser dans le code
du module de gains bruts, afin d'éliminer par construction toute
source d'écart binaire avec le corpus (règle 01).

#### Acceptance Criteria

1. LE Moteur_Gains NE DOIT contenir dans son code aucune
   littérale flottante (par exemple `0.04`, `1.5`, `40.0`, `0.0`).
2. LE Moteur_Gains NE DOIT construire aucun `Decimal` à partir d'une
   valeur `float` (par exemple `Decimal(1.5)` est interdit ; seule
   `Decimal("1.5")` est permise, ou la valeur reçue depuis
   `parametres_annee` qui est déjà un `Decimal`).
3. LE Moteur_Gains NE DOIT invoquer aucune fonction de la bibliothèque
   standard qui retourne un `float` (`round`, `math.floor`,
   `math.ceil`, `math.trunc` sur un argument non-`Decimal`,
   `statistics.mean`, etc.). LES arrondissements DOIVENT être
   effectués via la méthode `Decimal.quantize(Decimal("0.01"),
   rounding=ROUND_HALF_UP)`.
4. TOUS les sous-totaux intermédiaires du calcul DOIVENT être typés
   `Decimal` dans les annotations de type de la fonction (variables
   locales et retour), sans ambiguïté `float | Decimal`.
5. LES `Decimal` peuplant `CalculationTrace.parametres_utilises`,
   `CalculationTrace.entrees` et `CalculationTrace.sous_totaux`
   DOIVENT être ceux effectivement manipulés par la fonction, sans
   passage intermédiaire par `float` ni par `str(float(...))`.

---

### Requirement 13: Extensibilité au taux de vacances 6 %

**User Story:** En tant que responsable RH du camp, je veux que le
moteur applique correctement le taux 6 % pour les employés cumulant
trois années de service, afin qu'aucun changement de code ne soit
nécessaire au moment où le premier employé franchira ce seuil.

#### Acceptance Criteria

1. LE Moteur_Gains DOIT produire un résultat correct pour
   `PayrollInput.taux_vacances == Decimal("0.06")` en appliquant la
   même formule que pour `Decimal("0.04")` (voir Requirement 5), sans
   branchement conditionnel spécifique.
2. LE Moteur_Gains DOIT documenter dans la CalculationTrace
   (`parametres_utilises.taux_vacances`) le taux effectif utilisé
   pour la paie, qu'il vaille 4 % ou 6 %.
3. LE Moteur_Gains DOIT lever `UnsupportedPayrollCase` pour tout
   `PayrollInput.taux_vacances` hors de l'ensemble `{Decimal("0.04"),
   Decimal("0.06")}` (défense en profondeur, voir Requirement 10 AC3),
   couvrant ainsi par avance un éventuel taux futur non ratifié par
   `moteur-paie-contrats`.

---

### Requirement 14: Déterminisme et absence d'effet de bord

**User Story:** En tant qu'auteur des tests de propriétés, je veux
que la fonction `calcul_gains` soit strictement déterministe et sans
effet de bord observable, afin que les propriétés Hypothesis puissent
être exécutées des centaines de fois sans dérive et sans coût
d'infrastructure.

#### Acceptance Criteria

1. LA Fonction_Calcul_Gains DOIT être déterministe : POUR toute paire
   `(payroll_input, parametres_annee)` fournie deux fois de suite,
   LES deux tuples retournés DOIVENT être égaux au sens `==` sur les
   deux composantes (`GainsDecomposes` et `CalculationTrace`).
2. LA Fonction_Calcul_Gains NE DOIT PAS muter ses arguments : LES
   objets `payroll_input` et `parametres_annee` DOIVENT être
   sémantiquement égaux à leurs états d'origine après l'appel. LES
   modèles étant `frozen=True`, cette contrainte est déjà garantie
   structurellement — l'AC est cité ici pour interdire toute tentative
   de contournement (par exemple via `object.__setattr__`).
3. LA Fonction_Calcul_Gains NE DOIT PAS effectuer d'entrée-sortie
   (lecture ou écriture de fichier, appel réseau, écriture sur
   `stdout` ou `stderr`, appel à un logger configuré au niveau
   global). LES seuls flux autorisés sont ceux qui sont exposés par
   son type de retour.
4. LA Fonction_Calcul_Gains DOIT être exécutable en isolation : POUR
   toute paire `(payroll_input, parametres_annee)` construite en
   mémoire (sans lecture de disque), LA fonction DOIT retourner un
   résultat sans dépendance implicite sur un fichier ou une variable
   d'environnement.
5. LA Fonction_Calcul_Gains DOIT être compatible avec l'exécution
   simultanée par plusieurs threads sur des paires
   `(payroll_input, parametres_annee)` indépendantes, sans besoin de
   synchronisation externe (conséquence de l'absence d'état mutable
   partagé).
