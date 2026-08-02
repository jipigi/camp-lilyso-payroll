# Requirements Document

<!-- Titre métier : Document d'exigences — moteur-paie-contrats. Les en-têtes structurels de niveau supérieur (Requirements Document, Glossary, Requirements) et les libellés « Requirement N », « User Story: », « Acceptance Criteria » sont maintenus en anglais pour la conformité au format Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec établit les **contrats de données** du moteur de paie Camp LilySO : les modèles typés (Pydantic v2) qui décrivent une paie de son entrée à sa sortie, le format de trace attaché à chaque calcul fiscal futur, les exceptions du domaine et le chargeur des paramètres fiscaux annuels versionnés.

Elle constitue le socle non modifiable des specs ultérieures énumérées dans `docs/plan-implementation.md` (gains bruts, RRQ, RQAP, AE, impôts, charges patronales, registre, bulletin, interface). Une fois ces contrats acceptés, aucun module de calcul ne pourra les altérer ; il devra les respecter.

**Hors périmètre de cette spec** : aucune formule fiscale n'est implémentée ici. Aucun calcul RRQ, RQAP, AE, impôt QC, impôt fédéral, FSS, CNESST, CNT n'est exécuté. Cette spec définit uniquement les *formes* que ces calculs devront prendre.

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire, `float` interdit dans les modèles et les fonctions
- Règle 02 — chaque calcul fiscal futur retourne `(Decimal, CalculationTrace)` ; la trace doit être conçue dès maintenant pour ce contrat
- Règle 03 — seuls les cas de la matrice Camp LilySO sont acceptés ; tout autre cas lève `UnsupportedPayrollCase`
- Règle 04 — aucune donnée personnelle réelle dans les modèles, exemples ou tests
- Règle 05 — paramètres fiscaux uniquement dans `parameters/<AAAA>/*.json`, jamais codés en dur

**Corpus de référence à couvrir intégralement** : les 6 scénarios `docs/scenario-qc001.md` à `docs/scenario-qc006.md` doivent pouvoir être représentés au cent près, tant en entrée qu'en sortie, à travers les modèles définis ici.

## Glossary

- **Moteur** : le moteur de paie Camp LilySO, considéré comme un système unique dont la frontière est définie par les contrats de cette spec.
- **Modèle_Employee** : structure Pydantic v2 représentant une fiche employé avec uniquement des données non sensibles (règle 04).
- **Modèle_PayPeriod** : structure Pydantic v2 représentant une période de paie aux deux semaines, décomposée en ses semaines constituantes (essentiel pour le calcul futur des heures supplémentaires par semaine, seuil 40 h).
- **Modèle_PayrollInput** : contrat d'entrée complet du moteur, agrégeant employé, période, heures, taux horaire, paramètres TP-1015.3 et TD1, ainsi que les cumuls YTD.
- **Modèle_PayrollResult** : contrat de sortie complet du moteur, incluant gains décomposés, retenues employé, cotisations employeur, net et coût employeur total.
- **CalculationTrace** : trace exhaustive d'un calcul fiscal individuel (source officielle, année, section, paramètres, entrées, sous-totaux nommés, mode d'arrondissement, résultat).
- **Chargeur_De_Paramètres** : composant unique qui lit `parameters/<AAAA>/{quebec,canada}.json`, convertit les chaînes numériques en `Decimal`, refuse toute sentinelle `"TO_FILL"` et retourne un objet typé.
- **UnsupportedPayrollCase** : exception levée à la frontière du Moteur pour tout cas hors de la matrice Camp LilySO (règle 03).
- **MissingParameterError** : exception levée par le Chargeur_De_Paramètres lorsqu'une valeur `"TO_FILL"` est nécessaire à un calcul.
- **Cumul_YTD** : montant accumulé depuis le 1er janvier de l'année civile pour une catégorie donnée (RRQ, RQAP, AE, impôt QC, impôt fédéral, brut, vacances, net).
- **Statut_De_Paie** : état d'une paie parmi `brouillon`, `emise`, `annulee`, `remplace_par` ; supporte l'immuabilité et l'annulation-remplacement.
- **Frequence_De_Paie** : énumération limitée à `aux_deux_semaines` dans le périmètre courant.
- **Juridiction** : énumération à deux valeurs, `quebec` et `canada`.
- **TP-1015.3** : formulaire québécois déclaratif de l'employé fournissant le montant total des crédits, l'exonération de retenue et la retenue additionnelle.
- **TD1** : formulaire fédéral équivalent au TP-1015.3.
- **WebRAS** : calculateur officiel de Revenu Québec, oracle des golden tests QC.
- **PDOC** : calculateur officiel de l'ARC, oracle des golden tests fédéraux.

## Requirements

<!-- Chaque « Requirement N » ci-dessous est une exigence métier rédigée en français. -->

### Requirement 1: Fiche employé sans donnée sensible

**User Story:** En tant que responsable de la paie du Camp LilySO, je veux une fiche employé strictement limitée aux données non sensibles utilisées par le moteur, afin de garantir qu'aucun NAS, compte bancaire ou adresse personnelle ne puisse être introduit dans le dépôt Git (règle 04).

#### Acceptance Criteria

1. LE Modèle_Employee DOIT exposer les champs suivants et uniquement ceux-ci : identifiant technique, nom d'affichage anonymisable, date de naissance, province de travail, titre d'emploi, taux horaire de base, date d'embauche, date de fin d'emploi optionnelle, taux d'indemnité de vacances applicable, drapeau d'exonération TP-1015.3, drapeau d'exonération TD1, montant total TP-1015.3, montant total TD1, retenue additionnelle QC, retenue additionnelle fédérale.
2. LE Modèle_Employee DOIT rejeter tout champ inconnu à la validation Pydantic (`extra="forbid"`).
3. SI un champ portant un nom apparenté à une donnée sensible (`nas`, `sin`, `numero_assurance_sociale`, `compte_bancaire`, `iban`, `adresse`, `courriel_personnel`, `telephone_personnel`) est fourni à la construction du Modèle_Employee, ALORS LE Modèle_Employee DOIT lever une erreur de validation avec un message renvoyant à la règle 04.
4. LE Modèle_Employee DOIT typer tous les montants monétaires en `decimal.Decimal` et rejeter toute valeur `float` à la validation.
5. LORSQUE la province de travail fournie n'est pas `quebec`, LE Modèle_Employee DOIT lever `UnsupportedPayrollCase` avec un message renvoyant vers WebRAS et PDOC.
6. LE Modèle_Employee DOIT être immuable après construction (Pydantic `frozen=True` ou équivalent).
7. LE Modèle_Employee DOIT exposer une fabrique de classe nommée `Employee.avec_defauts_par_annee(annee_reference: int, **champs)` qui construit un Modèle_Employee immuable. QUAND l'un des champs `montant_total_TP1015_3`, `montant_total_TD1`, `retenue_additionnelle_QC` ou `retenue_additionnelle_federale` n'est pas fourni dans les arguments, LA fabrique DOIT lire la valeur par défaut correspondante depuis `parameters/<annee_reference>/quebec.json` (montant personnel de base QC, retenue additionnelle QC par défaut 0) et `parameters/<annee_reference>/canada.json` (montant personnel de base fédéral, retenue additionnelle fédérale par défaut 0). LA fabrique NE DOIT PAS coder en dur les valeurs 18 952, 16 452 ou 0 — elle DOIT toujours passer par le Chargeur_De_Paramètres.

---

### Requirement 2: Période de paie décomposée en semaines constituantes

**User Story:** En tant que futur module de calcul des heures supplémentaires, je veux que chaque période de paie fournisse la décomposition explicite de ses semaines constituantes, afin d'appliquer le seuil hebdomadaire de 40 heures conformément aux Normes du travail du Québec sans reconstruire cette information à la volée.

#### Acceptance Criteria

1. LE Modèle_PayPeriod DOIT exposer les champs suivants : numéro de période dans l'année civile, date de début, date de fin, date de paiement, fréquence de paie, nombre de périodes annuelles applicables à cette année, année fiscale, et liste ordonnée de semaines constituantes.
2. LE Modèle_PayPeriod DOIT contenir exactement deux semaines constituantes lorsque la fréquence est `aux_deux_semaines`.
3. Chaque semaine constituante DOIT exposer sa date de début, sa date de fin, et le nombre d'heures normales et d'heures supplémentaires imputées à cette semaine.
4. LORSQUE le Modèle_PayPeriod contient exactement le nombre de semaines constituantes exigé par l'AC2 pour la fréquence fournie (soit deux semaines pour `aux_deux_semaines`), LE Modèle_PayPeriod DOIT garantir que la date de fin de chaque semaine constituante est postérieure ou égale à sa date de début, et que les semaines constituantes sont contiguës et non chevauchantes. LES vérifications de contiguïté et de non-chevauchement de cet AC4 NE DOIVENT PAS être évaluées lorsque le nombre de semaines constituantes ne satisfait pas l'AC2 : dans ce cas, l'erreur de validation portée par l'AC2 (nombre de semaines incorrect) DOIT prévaloir.
5. LORSQUE le Modèle_PayPeriod contient exactement le nombre de semaines constituantes exigé par l'AC2, LE Modèle_PayPeriod DOIT garantir que la somme des jours des semaines constituantes couvre exactement l'intervalle `[date_debut ; date_fin]` de la période. LA vérification de couverture exacte de cet AC5 NE DOIT PAS être évaluée lorsque le nombre de semaines constituantes ne satisfait pas l'AC2 : dans ce cas, l'erreur de l'AC2 DOIT prévaloir.
6. LE Modèle_PayPeriod DOIT accepter uniquement la fréquence `aux_deux_semaines` ; SI toute autre fréquence est fournie, ALORS LE Modèle_PayPeriod DOIT lever `UnsupportedPayrollCase` avec un message citant la règle 03.
7. LE Modèle_PayPeriod DOIT recevoir `nb_periodes_annuelles` comme un entier positif à la construction, dont la valeur est fournie par le Chargeur_De_Paramètres depuis `parameters/<annee_fiscale>/quebec.json` (section `frequence_paie`, clé `nb_periodes_annuelles`). La valeur DOIT être identique dans `canada.json` sous la même clé. Ce paramètre DOIT être versionné par année civile : 27 pour 2026 (année à 27 paies bi-hebdomadaires selon le calendrier Camp LilySO), 26 pour 2027 et les années standard. LE Modèle_PayPeriod NE DOIT PAS coder en dur cette valeur et NE DOIT PAS la dériver du calendrier de paye — c'est un paramètre annuel explicite. LORSQU'une nouvelle année fiscale est demandée et qu'aucun fichier de paramètres `parameters/<annee_fiscale>/quebec.json` (ou `canada.json`) n'existe encore pour cette année, LE Chargeur_De_Paramètres DOIT permettre la poursuite de l'opération sans intervention manuelle bloquante en appliquant, dans cet ordre, un mécanisme de repli documenté : (a) réutiliser la valeur `nb_periodes_annuelles` de l'année civile précédente (`<annee_fiscale - 1>`) si le fichier de paramètres correspondant est disponible et expose la clé, sinon (b) appliquer la valeur par défaut documentée `26` pour une année bi-hebdomadaire standard. LA source effective retenue (année du fichier de repli utilisé, ou mention explicite `valeur_par_defaut`) DOIT être exposée dans les métadonnées de l'objet `ParametresAnnee` retourné afin de préserver la traçabilité de la source, conformément à la règle 02.
8. LE Modèle_PayPeriod DOIT être immuable après construction.

---

### Requirement 3: Contrat d'entrée complet du moteur

**User Story:** En tant que consommateur du moteur de paie, je veux un contrat d'entrée unique et typé qui rassemble tout ce dont le moteur a besoin pour produire une paie, afin d'éviter les paramètres passés par « mille chemins » et de garantir la reproductibilité d'un calcul à partir de ses entrées.

#### Acceptance Criteria

1. LE Modèle_PayrollInput DOIT agréger : un Modèle_Employee, un Modèle_PayPeriod, les heures normales et supplémentaires par semaine constituante, le taux horaire effectif de la période, le taux d'indemnité de vacances applicable, un champ optionnel de montant manuel de jours fériés, les paramètres TP-1015.3 (montant total des crédits, exonération oui/non, retenue additionnelle), les paramètres TD1 (montant total, exonération oui/non, retenue additionnelle), et les cumuls YTD par catégorie.
2. LE Modèle_PayrollInput DOIT typer tous les montants en `decimal.Decimal` et DOIT rejeter activement, à la validation Pydantic v2, toute valeur numérique fournie sous forme `float` (y compris lorsque la valeur `float` est présentée en JSON sans guillemets, par exemple `1516.32`), en levant une erreur de validation explicite. LE Modèle_PayrollInput NE DOIT PAS se contenter de reposer sur le typage `Decimal` : IL DOIT installer un validateur Pydantic dédié qui détecte la classe `float` avant toute conversion et refuse l'entrée.
3. LE Modèle_PayrollInput DOIT garantir que les heures normales et supplémentaires par semaine sont non négatives et bornées supérieurement à 168 heures par semaine, plancher à zéro.
4. LE Modèle_PayrollInput DOIT garantir que le taux horaire effectif est strictement positif.
5. LE Modèle_PayrollInput DOIT garantir que le taux d'indemnité de vacances est un `Decimal` dans l'ensemble `{Decimal("0.04"), Decimal("0.06")}` sans autre valeur admise dans le périmètre courant.
6. LE Modèle_PayrollInput DOIT exposer un champ manuel optionnel de montant de jours fériés en `Decimal`. SI ce champ est absent, ALORS LE Modèle_PayrollInput DOIT le traiter comme `Decimal("0.00")`. SI une valeur strictement négative est fournie pour ce champ (par exemple `Decimal("-1.00")`), ALORS LE Modèle_PayrollInput DOIT lever une erreur de validation Pydantic explicite qui rejette l'entrée, sans clampage, sans substitution silencieuse par zéro et sans conversion en valeur absolue. LA non-négativité de ce champ DOIT être appliquée activement à la validation, indépendamment de son caractère optionnel.
7. LE Modèle_PayrollInput DOIT accepter les cumuls YTD sous forme de structure typée exposant au minimum : cumul brut, cumul vacances, cumul RRQ employé, cumul RQAP employé, cumul AE employé, cumul impôt QC retenu, cumul impôt fédéral retenu, cumul net ; chaque cumul DOIT être un `Decimal` non négatif.
8. LE Modèle_PayrollInput DOIT rejeter tout champ inconnu à la validation (`extra="forbid"`).
9. SI la fréquence de paie du Modèle_PayPeriod contenu n'est pas `aux_deux_semaines`, ALORS LE Modèle_PayrollInput DOIT lever `UnsupportedPayrollCase`.
10. SI la province du Modèle_Employee contenu n'est pas `quebec`, ALORS LE Modèle_PayrollInput DOIT lever `UnsupportedPayrollCase`.
11. LE Modèle_PayrollInput DOIT être immuable après construction.
12. LE Modèle_PayrollInput DOIT pouvoir représenter au cent près les entrées de tous les scénarios `QC001` à `QC006` sans transformation ni perte d'information.

---

### Requirement 4: Contrat de sortie complet du moteur

**User Story:** En tant que consommateur du moteur de paie, je veux un contrat de sortie unique et typé qui expose la décomposition intégrale d'une paie (gains, retenues, cotisations employeur, net, coût employeur) avec la trace de chaque calcul, afin d'auditer chaque montant sans avoir à réexécuter le moteur.

#### Acceptance Criteria

1. LE Modèle_PayrollResult DOIT exposer les gains décomposés : salaire régulier, heures supplémentaires, vacances, jours fériés manuels, brut total.
2. LE Modèle_PayrollResult DOIT exposer les retenues employé, chacune associée à sa CalculationTrace : RRQ, RQAP, AE, impôt QC, impôt fédéral, ainsi que le total des retenues.
3. LE Modèle_PayrollResult DOIT exposer les cotisations employeur, chacune associée à sa CalculationTrace : RRQ employeur, RQAP employeur, AE employeur, FSS, CNESST (avec drapeau `en_attente_classification`), CNT, ainsi que le total des cotisations employeur.
4. LE Modèle_PayrollResult DOIT exposer le salaire net, calculé comme brut moins total des retenues employé.
5. LE Modèle_PayrollResult DOIT exposer le coût employeur total, calculé comme brut plus total des cotisations employeur.
6. LE Modèle_PayrollResult DOIT exposer les cumuls YTD mis à jour après application de la paie courante.
7. LE Modèle_PayrollResult DOIT exposer le Statut_De_Paie et, LORSQUE le statut est `remplace_par`, la référence à la paie de remplacement.
8. LE Modèle_PayrollResult DOIT typer tous les montants en `decimal.Decimal` et rejeter tout `float` à la validation.
9. LE Modèle_PayrollResult DOIT garantir l'identité comptable `brut = net + total_retenues_employe` au cent près et lever une erreur de validation dans le cas contraire.
10. LE Modèle_PayrollResult DOIT garantir l'identité `cout_employeur = brut + total_cotisations_employeur` au cent près et lever une erreur de validation dans le cas contraire.
11. LE Modèle_PayrollResult DOIT garantir qu'aucune retenue employé et qu'aucune cotisation employeur n'est de valeur négative, et lever une erreur de validation dans le cas contraire.
12. LE Modèle_PayrollResult DOIT être immuable après construction.
13. LE Modèle_PayrollResult DOIT pouvoir représenter au cent près les sorties de tous les scénarios `QC001` à `QC006` sans perte d'information ni arrondissement supplémentaire à la construction.
14. LE Modèle_PayrollResult DOIT exposer, dans sa section des gains, deux champs `Decimal` supplémentaires : `multiplicateur_heures_supp` (typiquement `Decimal("1.5")` pour 2026) et `seuil_heures_supp_hebdo` (typiquement `Decimal("40")` pour 2026). Ces deux champs DOIVENT correspondre aux valeurs chargées depuis `parameters/<annee_fiscale>/quebec.json` (section `heures_supplementaires`) au moment du calcul de la paie. LE Modèle_PayrollResult NE DOIT PAS recalculer ces valeurs — il les reçoit du moteur de calcul. Cette exposition permet au module `bulletin-pdf` et au registre maître d'afficher explicitement le facteur d'heures supplémentaires appliqué, comme le fait déjà le gabarit Excel du corpus (formule `=E21*1.5` dans le bulletin de paie type).

---

### Requirement 5: Trace exhaustive d'un calcul fiscal

**User Story:** En tant qu'auditeur (interne, Revenu Québec ou ARC) qui inspecte une paie trois ans après son émission, je veux disposer pour chaque montant retenu ou versé d'une trace autonome référençant la source officielle, l'année, les paramètres utilisés, les entrées, les sous-totaux et le mode d'arrondissement, afin de reconstruire exactement le calcul sans avoir à réexécuter le moteur.

#### Acceptance Criteria

1. LE Modèle CalculationTrace DOIT exposer les champs : `source` (chaîne officielle exacte, par exemple `"TP-1015.F 2026, section 3.2 — RRQ"`), `annee` (entier), `juridiction` (`quebec` ou `canada`), `section` (référence à la section du document officiel), `parametres_utilises` (dictionnaire de `Decimal` nommés), `entrees` (dictionnaire de `Decimal` nommés), `sous_totaux` (dictionnaire ordonné de `Decimal` nommés représentant les étapes intermédiaires), `mode_arrondissement` (chaîne parmi `ROUND_HALF_UP`, `ROUND_HALF_EVEN`, `ROUND_DOWN`, `ROUND_UP`), `precision_arrondissement` (nombre de décimales, entier non négatif), `resultat` (`Decimal`).
2. LE Modèle CalculationTrace DOIT rejeter toute source hors de la liste blanche des documents officiels autorisés par la règle 02 (TP-1015.F, TP-1015.G, TP-1015.3, T4127, TD1, guide de l'employeur ARC, sites `.gouv.qc.ca`, `.canada.ca`) et lever une erreur de validation avec un message actionnable dans le cas contraire.
3. LE Modèle CalculationTrace DOIT typer tous les champs numériques en `decimal.Decimal` et rejeter tout `float` à la validation.
4. LE Modèle CalculationTrace DOIT être immuable après construction.
5. LE Modèle CalculationTrace DOIT être sérialisable en JSON de manière déterministe et round-trip : `parse(serialize(t)) == t` au cent près et à l'ordre des sous-totaux près.
6. LE Modèle CalculationTrace DOIT exposer une méthode de représentation textuelle humainement lisible qui liste, dans l'ordre : source, année, section, paramètres, entrées, sous-totaux nommés, arrondissement, résultat.
7. QUAND une CalculationTrace est construite sans champ `source`, sans `annee`, sans `mode_arrondissement` ou sans `resultat`, LE Modèle CalculationTrace DOIT lever une erreur de validation.
8. LE Modèle CalculationTrace DOIT servir de type de retour à toute fonction de calcul fiscal future du moteur, conformément à la signature `(entrées) -> tuple[Decimal, CalculationTrace]` définie par la règle 02.

---

### Requirement 6: Immuabilité et annulation-remplacement des paies

**User Story:** En tant que responsable de la paie, je veux qu'une paie émise soit strictement immuable et que toute correction se fasse par annulation-remplacement, afin de préserver la piste d'audit exigée par les Normes du travail et par Revenu Québec, sans jamais réécrire une valeur historique.

#### Acceptance Criteria

1. LE Modèle_PayrollResult DOIT exposer un champ `statut` prenant l'une des valeurs de l'énumération `Statut_De_Paie` : `brouillon`, `emise`, `annulee`, `remplace_par`.
2. LE Modèle_PayrollResult DOIT être immuable après construction, indépendamment de la valeur du statut.
3. LE Modèle_PayrollResult DOIT exposer un champ optionnel `remplace_par_id` qui n'est renseigné que lorsque le statut est `remplace_par`.
4. SI le statut est `remplace_par` et que `remplace_par_id` est absent ou vide, ALORS LE Modèle_PayrollResult DOIT lever une erreur de validation.
5. SI le statut est différent de `remplace_par` et que `remplace_par_id` est renseigné, ALORS LE Modèle_PayrollResult DOIT lever une erreur de validation.
6. LE Modèle_PayrollResult DOIT exposer un identifiant technique unique de paie et un numéro de version entier commençant à 1, incrémenté à chaque annulation-remplacement portant sur la même paie logique.
7. LE Modèle_PayrollResult DOIT exposer la date de création et la date d'émission ; SI le statut est `emise`, `annulee` ou `remplace_par`, ALORS la date d'émission DOIT être renseignée.

---

### Requirement 7: Cumuls YTD par employé et par catégorie

**User Story:** En tant que futur module de calcul des retenues, je veux disposer, pour chaque paie, des cumuls YTD (year-to-date) par employé et par catégorie, afin de respecter les plafonds annuels RRQ, RQAP et AE, et d'assurer la monotonie croissante des cumuls saison après saison.

#### Acceptance Criteria

1. LE Modèle_Cumuls_YTD DOIT exposer, pour chaque catégorie, un `Decimal` non négatif : brut, vacances, RRQ employé, RRQ employeur, RQAP employé, RQAP employeur, AE employé, AE employeur, impôt QC retenu, impôt fédéral retenu, net.
2. LE Modèle_Cumuls_YTD DOIT être associé à un employé (identifiant) et à une année civile (entier), et interdire l'agrégation de cumuls appartenant à deux employés ou à deux années différentes.
3. LE Modèle_Cumuls_YTD DOIT être immuable après construction.
4. LE Modèle_Cumuls_YTD DOIT exposer une méthode `avec_paie(resultat: PayrollResult) -> Cumuls_YTD` qui produit une nouvelle instance dans laquelle chaque catégorie est incrémentée du montant correspondant de la paie fournie, sans modifier l'instance d'origine.
5. QUAND la méthode `avec_paie` est appelée, LE Modèle_Cumuls_YTD résultant DOIT garantir que chaque catégorie est supérieure ou égale à la catégorie correspondante de l'instance d'origine (monotonie croissante).
6. SI l'année civile du `PayrollResult` fourni à `avec_paie` diffère de l'année civile du Modèle_Cumuls_YTD, ALORS le Modèle_Cumuls_YTD DOIT lever une erreur explicite invitant à repartir de zéro pour la nouvelle année.
7. SI l'identifiant employé du `PayrollResult` fourni à `avec_paie` diffère de celui du Modèle_Cumuls_YTD, ALORS le Modèle_Cumuls_YTD DOIT lever une erreur explicite.
8. LE Modèle_Cumuls_YTD DOIT pouvoir être sérialisé en JSON et parsé de manière round-trip au cent près.

---

### Requirement 8: Exceptions du domaine

**User Story:** En tant que consommateur du moteur, je veux des exceptions dédiées et informatives pour les cas hors périmètre et pour les paramètres manquants, afin de distinguer clairement un refus métier d'une erreur technique et de rediriger l'utilisateur vers l'outil officiel approprié.

#### Acceptance Criteria

1. LE Moteur DOIT exposer une exception nommée `UnsupportedPayrollCase` dérivant d'une exception dédiée du domaine (par exemple `PayrollDomainError`), distincte des exceptions standard Python.
2. LORSQU'une entrée relève d'un cas hors matrice (règle 03) — province autre que Québec, fréquence de paie autre qu'aux deux semaines, type de rémunération non horaire, retenue non supportée, avantage imposable non supporté —, LE Moteur DOIT lever `UnsupportedPayrollCase` avec un message précisant le cas refusé et renvoyant explicitement vers WebRAS (`revenuquebec.ca/webras`) et le calculateur PDOC (`canada.ca/pdoc`). `UnsupportedPayrollCase` NE DOIT PAS être utilisée pour signaler un paramètre manquant ou une sentinelle `"TO_FILL"` dans un cas par ailleurs supporté (Québec, aux deux semaines, horaire) : DANS ce dernier cas, c'est `MissingParameterError` qui DOIT être levée conformément à l'AC5. LES deux exceptions DOIVENT rester strictement disjointes dans leurs déclencheurs — un cas métier hors matrice pour `UnsupportedPayrollCase`, une donnée de paramétrage manquante ou sentinelle pour `MissingParameterError` — et NE DOIVENT jamais se substituer l'une à l'autre.
3. LE message porté par `UnsupportedPayrollCase` DOIT être une chaîne non vide et DOIT contenir : la nature du cas refusé, l'outil officiel de repli suggéré.
4. LE Moteur DOIT exposer une exception nommée `MissingParameterError` dérivant de la même exception dédiée du domaine.
5. LORSQUE la fonction `load_parameters` est en cours d'exécution et qu'un paramètre annuel indispensable à un calcul est manquant ou porte la sentinelle `"TO_FILL"`, LE Chargeur_De_Paramètres DOIT lever `MissingParameterError` immédiatement pendant le chargement du fichier — et non plus tard au moment du calcul — avec un message précisant : le nom du paramètre, l'année, la juridiction et le fichier de paramètres concerné. LA levée de `MissingParameterError` DOIT se produire au plus tôt (fail-fast) durant l'exécution de `load_parameters`, sans jamais différer la détection à l'appel d'un module de calcul aval.
6. LE message porté par `MissingParameterError` DOIT être une chaîne non vide et actionnable (indiquant explicitement le fichier à mettre à jour).
7. LES exceptions du domaine DOIVENT être capturables séparément des exceptions Pydantic de validation ; QUAND une exception du domaine est levée, elle NE DOIT PAS être une sous-classe de `pydantic.ValidationError`.

---

### Requirement 9: Chargeur de paramètres versionnés

**User Story:** En tant que module de calcul fiscal, je veux un point d'entrée unique pour obtenir les paramètres fiscaux d'une année et d'une juridiction, afin de garantir que tous les modules lisent la même source de vérité et que la substitution annuelle se fasse en un seul endroit.

#### Acceptance Criteria

1. LE Chargeur_De_Paramètres DOIT exposer une fonction publique `load_parameters(annee: int, juridiction: Juridiction) -> ParametresAnnee` où `Juridiction` est une énumération à deux valeurs `quebec` et `canada`.
2. LE Chargeur_De_Paramètres DOIT lire, pour `juridiction=quebec`, le fichier `parameters/<annee>/quebec.json` et, pour `juridiction=canada`, le fichier `parameters/<annee>/canada.json`.
3. LE Chargeur_De_Paramètres DOIT convertir toute chaîne représentant un nombre (taux, plafond, seuil, exemption, crédit, cotisation maximale) en `decimal.Decimal`.
4. LE Chargeur_De_Paramètres NE DOIT JAMAIS convertir une valeur numérique via un `float` intermédiaire.
5. SI une valeur nécessaire est absente ou vaut `"TO_FILL"`, ALORS LE Chargeur_De_Paramètres DOIT lever `MissingParameterError` en identifiant le chemin d'accès à la valeur dans le fichier JSON (par exemple `rrq.maximum_gains_admissibles_mga`).
6. LE Chargeur_De_Paramètres DOIT retourner un objet typé (Pydantic v2 ou équivalent) dont la structure reflète les sections métier du fichier (frequence_paie, RRQ, RQAP, AE, impôt QC, impôt fédéral, TD1, FSS, CNESST, CNT, vacances, heures_supplementaires) et DOIT exposer, au niveau racine, les champs `annee`, `juridiction`, `source`, `date_publication`, `url_consultee`.
7. LORSQUE la fonction `load_parameters` est appelée et que la structure du fichier JSON chargé ne correspond pas au schéma attendu, LE Chargeur_De_Paramètres DOIT lever une erreur de validation avec la liste des champs manquants ou invalides. LA validation du schéma DOIT être déclenchée uniquement par l'exécution effective de `load_parameters` (fait générateur), et NON de manière proactive à l'import du module de chargement, ni au moment de l'initialisation d'une constante de module.
8. SI le fichier `parameters/<annee>/<juridiction>.json` est absent, ALORS LE Chargeur_De_Paramètres DOIT lever `FileNotFoundError` avec un message identifiant l'année et la juridiction demandées.
9. LE Chargeur_De_Paramètres DOIT accepter en paramètre optionnel un chemin racine (répertoire `parameters/`) pour permettre l'injection d'un dossier de test, avec pour défaut le dossier `parameters/` de la racine du projet.
10. LE Chargeur_De_Paramètres DOIT être déterministe : deux appels successifs avec les mêmes arguments et le même fichier JSON DOIVENT retourner deux objets égaux au sens des valeurs (`==`).
11. LE Chargeur_De_Paramètres DOIT être capable de charger avec succès `parameters/2026/quebec.json` et `parameters/2026/canada.json` dès lors que toutes les valeurs `"TO_FILL"` ont été renseignées ; DANS L'ÉTAT ACTUEL de ces fichiers, la tentative de lire un champ marqué `"TO_FILL"` DOIT lever `MissingParameterError` avec un message renvoyant à la consultation du TP-1015.F 2026 ou du T4127 2026.

---

### Requirement 10: Interdiction transversale de `float` dans les contrats

**User Story:** En tant que responsable de la qualité fiscale du moteur, je veux qu'aucun `float` ne puisse se glisser dans un modèle du domaine, afin d'éliminer par construction toute source d'écart binaire avec WebRAS et PDOC (règle 01).

#### Acceptance Criteria

1. LE Modèle_Employee, LE Modèle_PayPeriod, LE Modèle_PayrollInput, LE Modèle_PayrollResult, LE Modèle_Cumuls_YTD ET LE Modèle CalculationTrace DOIVENT rejeter tout champ numérique fourni sous forme `float` à la validation. QUAND une valeur numérique JSON non-guillemée est rencontrée dans un champ typé `Decimal`, LE parseur DOIT la rejeter dès qu'elle contient un point décimal, MÊME lorsqu'elle représente un entier exact (par exemple `1.0`, `0.0`, `40.0`, `4.0`) : seule une chaîne guillemée (`"1.00"`, `"40"`) ou un entier JSON sans point décimal (`1`, `40`) est acceptable pour un champ `Decimal`.
2. LES modèles DOIVENT accepter les entrées UNIQUEMENT sous forme de `Decimal` ou de chaîne de caractères convertible en `Decimal` sans passage par `float`, et DOIVENT rejeter explicitement toute entrée de type `float` à la validation. L'acceptation silencieuse d'une valeur `float` (même exprimable exactement comme `4.0` ou `0.0`) N'EST PAS admise : LE validateur Pydantic DOIT installer une garde active qui identifie la classe `float` avant toute conversion et refuse la valeur avec une erreur de validation actionnable.
3. UN test de garde au niveau du module DOIT vérifier qu'aucun champ typé `float` n'apparaît dans la définition des modèles.
4. QUAND un `Decimal` construit à partir d'un `float` (`Decimal(1516.32)`) est soumis à un modèle, LE modèle DOIT refuser la valeur ou détecter la précision aberrante et lever une erreur de validation.

---

### Requirement 11: Refus à la frontière des cas hors matrice

**User Story:** En tant que responsable de la conformité fiscale, je veux que toute entrée hors matrice Camp LilySO soit refusée à la frontière du moteur avec un message clair, afin de garantir le principe fail-fast de la règle 03 et d'empêcher toute production silencieuse d'un résultat approximatif.

#### Acceptance Criteria

1. LORSQUE la province de travail fournie via le Modèle_Employee ou le Modèle_PayrollInput est différente de `quebec`, LE Moteur DOIT lever `UnsupportedPayrollCase`.
2. LORSQUE la fréquence de paie fournie via le Modèle_PayPeriod ou le Modèle_PayrollInput est différente de `aux_deux_semaines`, LE Moteur DOIT lever `UnsupportedPayrollCase`.
3. LORSQUE le taux d'indemnité de vacances fourni est différent de `Decimal("0.04")` et de `Decimal("0.06")`, LE Moteur DOIT lever `UnsupportedPayrollCase`.
4. LORSQU'un champ dénotant un type de rémunération hors matrice est présent (`commission`, `bonus`, `pourboires`, `allocation_automobile`, `logement_fourni`, `options_achat_actions`), LE Moteur DOIT lever `UnsupportedPayrollCase`.
5. LORSQU'un champ dénotant une retenue hors matrice est présent (`assurance_collective`, `rpa`, `reer_collectif`, `cotisation_syndicale`, `pension_alimentaire`, `saisie_salaire`), LE Moteur DOIT lever `UnsupportedPayrollCase`.
6. LE message de chaque `UnsupportedPayrollCase` levée à la frontière DOIT nommer le cas refusé et suggérer WebRAS ou PDOC comme outil de repli.
7. LE refus des cas hors matrice DOIT se produire à la frontière PAR CONSTRUCTION, via la validation Pydantic du Modèle_Employee, du Modèle_PayPeriod et du Modèle_PayrollInput : dès qu'un de ces modèles est instancié avec une entrée hors matrice, `UnsupportedPayrollCase` DOIT être levée avant toute logique de calcul. LE Moteur N'A PAS À installer, dans les modules de calcul aval, de garde-fou runtime redondant contre les cas hors matrice ; SI la validation frontière n'a pas été atteinte (par exemple à cause d'un contournement système ou d'une négligence de programmation en amont), LE Moteur DOIT autoriser la poursuite des calculs, ET IL RELÈVE de la responsabilité des développeurs de garantir par la conception que le flux passe toujours par la validation frontière avant d'appeler un module de calcul.

---

### Requirement 12: Fidélité de représentation des 6 scénarios de référence

**User Story:** En tant que validateur du moteur, je veux que les contrats définis ici représentent au cent près l'ensemble des entrées et des sorties des scénarios `QC001` à `QC006`, afin de garantir que les modules de calcul futurs pourront être testés en golden tests sans transformation intermédiaire.

#### Acceptance Criteria

1. LE Modèle_PayrollInput DOIT pouvoir représenter les entrées de `QC001` (brut 1 516,32 $ synthétique, sans exonération) et retrouver au cent près, à la sérialisation, la valeur du brut décomposée en salaire régulier 1 458,00 $ et vacances 4 % 58,32 $.
2. LE Modèle_PayrollInput DOIT pouvoir représenter les entrées de `QC002` (brut 2 861,04 $, 116 h régulières + 10 h supp à 21,00 $, exonérations QC et fédérale actives).
3. LE Modèle_PayrollInput DOIT pouvoir représenter les entrées de `QC003` (brut 2 179,84 $, 116 h + 10 h à 16,00 $, exonérations actives).
4. LE Modèle_PayrollInput DOIT pouvoir représenter les entrées de `QC004` (brut 294,84 $, 20,25 h à 14,00 $, sans exonération).
5. LE Modèle_PayrollInput DOIT pouvoir représenter les entrées de `QC005` (brut 1 739,92 $, 112 h + 5 h supp à 14,00 $, exonérations actives).
6. LE Modèle_PayrollInput DOIT pouvoir représenter les entrées de `QC006` (brut 505,44 $, 40,5 h à 12,00 $, exonérations actives).
7. LE Modèle_PayrollResult DOIT pouvoir représenter les sorties officielles WebRAS et PDOC de chacun des scénarios `QC001` à `QC006` au cent près, incluant les retenues employé (RRQ, RQAP, AE, impôt QC formule, impôt fédéral formule, impôt QC retenu, impôt fédéral retenu), les cotisations employeur (RRQ, RQAP, AE ×1,4, FSS 1,65 %, CNESST provision 1,12 %) et le net.
8. LE Modèle_PayrollResult DOIT préserver, pour les scénarios comportant une exonération, la distinction entre la « valeur formule » (calculée par la formule officielle) et la « valeur retenue » (0 $ après court-circuit d'exonération), sous forme de deux champs distincts pour l'impôt QC et pour l'impôt fédéral.
9. LE Modèle CalculationTrace DOIT pouvoir enregistrer, pour chaque montant fiscal des 6 scénarios, une trace référençant la section correspondante du TP-1015.F 2026 ou du T4127 2026.

---

### Requirement 13: Sérialisation déterministe et round-trip des contrats

**User Story:** En tant que futur module de persistance (registre maître SQLite) et de génération de bulletin PDF, je veux que chaque modèle du domaine soit sérialisable en JSON de manière déterministe et parsable sans perte, afin d'archiver les paies et de garantir qu'une paie rechargée est strictement égale à la paie d'origine.

#### Acceptance Criteria

1. LE Modèle_Employee, LE Modèle_PayPeriod, LE Modèle_PayrollInput, LE Modèle_PayrollResult, LE Modèle_Cumuls_YTD ET LE Modèle CalculationTrace DOIVENT exposer une méthode de sérialisation JSON produisant une chaîne où tout `Decimal` est sérialisé en chaîne (jamais en `float`), conservant la précision exacte.
2. POUR TOUTE instance valide de chacun de ces modèles, la propriété round-trip DOIT tenir : `parse(serialize(instance)) == instance`, au sens d'une égalité champ à champ sur `Decimal`, `date`, chaînes et énumérations.
3. LA sérialisation DOIT être déterministe : deux sérialisations d'une même instance produisent la même chaîne d'octets à l'ordre des clés près, en préservant l'ordre des listes et des sous-totaux nommés.
4. LA sérialisation NE DOIT PAS silencieusement convertir un `Decimal` en `float` sous prétexte de compatibilité JSON.
5. QUAND une chaîne JSON contient une valeur numérique sans guillemets (par exemple `1516.32`, `1.0` ou `0.0`) dans un champ typé `Decimal`, LE parseur DOIT arrêter l'analyse immédiatement dès la première occurrence rencontrée (fail-fast, sans tentative de récupération, sans coercition silencieuse, sans traitement partiel), rejeter la totalité du document en cours d'analyse, et lever une erreur de validation invitant à envelopper la valeur dans une chaîne, afin d'éviter la corruption par précision binaire lors de la relecture.
