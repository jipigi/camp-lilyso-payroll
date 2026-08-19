# Requirements Document

<!-- Titre métier : Document d'exigences — bilan-fiscal-employeur. Les en-têtes
structurels de niveau supérieur (Requirements Document, Introduction, Glossary,
Requirements) et les libellés « Requirement N », « User Story: »,
« Acceptance Criteria » sont maintenus en anglais pour la conformité au format
Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Les entreprises québécoises doivent verser aux deux paliers de gouvernement
(Québec et Canada), au plus tard le 15 de chaque mois, la somme des retenues
à la source et des cotisations patronales accumulées. Cette spec ajoute une
nouvelle section **« Bilan fiscal »** au Tableau_De_Bord
(`app/pages_ui/tableau_de_bord.py`), affichée sous la liste des Fiches_Employe
existante, qui agrège — pour une période choisie par l'opérateur (un mois ou
une année civile complète) — les montants déjà calculés et tracés par le
moteur de paie, répartis entre le palier Québec (« QC ») et le palier Canada
(« CA »).

Cette spec **ne modifie ni le moteur de paie (`payroll_engine/`) ni les
modèles (`models/`)** : elle lit exclusivement des `PayrollResult` déjà
persistés dans le Registre_Maitre (`payroll.db`) et n'invente aucun nouveau
calcul fiscal (règle 02 — la traçabilité de chaque montant a déjà été assurée
en amont par le moteur ; cette fonctionnalité ne fait qu'agréger des montants
déjà calculés et tracés).

**Décisions actées pour lever les ambiguïtés identifiées dans la demande** :

1. **Mois/année de rattachement d'une paie** — le mois et l'année utilisés
   pour classer une paie EMISE dans le Selecteur_De_Periode et pour
   l'agréger dans le Bilan_Fiscal sont ceux de `PayPeriod.date_paiement`
   (date de versement effectif du salaire), et non `annee_fiscale` ni
   `date_debut`/`date_fin` de la période. Ce choix reflète la réalité de
   l'obligation de versement : les retenues et cotisations d'une paie sont
   dues au gouvernement en fonction du mois où le salaire est effectivement
   versé à l'employé.
2. **Répartition QC/CA** — fixée par la nature de chaque cotisation, sans
   ambiguïté possible : RRQ, RQAP, FSS, CNESST et CNT sont des cotisations
   provinciales (colonne QC) ; l'assurance-emploi (AE) est fédérale
   (colonne CA). L'impôt sur le revenu retenu comporte une composante
   provinciale (`impot_qc_retenu`, colonne QC) et une composante fédérale
   (`impot_federal_retenu`, colonne CA), affichées sur une seule ligne
   « Impôt sur le revenu retenu » avec un montant dans chacune des deux
   colonnes.
3. **Grand total** — la section ne comporte que les trois colonnes du
   Tableau_Bilan_Fiscal (« Retenues et cotisations », « QC », « CA ») ; le
   « grand total » demandé est donc une ligne « Grand total » dont la
   colonne QC contient la somme du total des retenues QC et du total des
   cotisations QC, et dont la colonne CA contient la somme du total des
   retenues CA et du total des cotisations CA — sans colonne
   supplémentaire. Une **ligne additionnelle** « Grand total combiné
   (QC + CA) » est affichée immédiatement après la ligne « Grand total »
   (jamais comme colonne supplémentaire du tableau) : sa cellule
   QC/CA, fusionnée sur les deux colonnes, affiche la somme du montant QC
   et du montant CA de la ligne « Grand total » — le montant unique à
   verser en tout, tous paliers confondus.
4. **Montants de traçabilité pré-exonération exclus, retenue effective
   toujours incluse** — `RetenuesEmploye.impot_qc_formule` et
   `RetenuesEmploye.impot_federal_formule` (portés uniquement pour la
   traçabilité de la formule avant exonération TP-1015.3/TD1 — voir
   `models/payroll_result.py`) ne sont **jamais** additionnés à aucun
   montant affiché par le Bilan_Fiscal. Ceci **ne retire aucun montant
   réellement retenu** sur le salaire d'un employé : le Bilan_Fiscal
   utilise exclusivement `impot_qc_retenu` et `impot_federal_retenu`
   (Requirement 6, Acceptance Criterion 5), qui représentent la retenue
   **effectivement appliquée** sur chaque paie. Pour un employé **non
   exonéré**, `impot_qc_retenu`/`impot_federal_retenu` sont égaux à
   `impot_qc_formule`/`impot_federal_formule` (aucune exonération ne
   réduit la retenue) et sont donc **pleinement inclus** dans le total —
   la retenue d'un employé non exonéré n'est jamais omise du
   Bilan_Fiscal. Seul un employé bénéficiant d'une exonération
   TP-1015.3/TD1 voit sa retenue effective (`*_retenu`) inférieure à la
   formule (`*_formule`) ; c'est cette retenue effective, réduite par
   l'exonération, qui est seule sommée — cohérent avec l'invariant déjà
   imposé par le moteur sur `total_retenues_employe`.
5. **Absence totale de paie émise** — une liste d'Fiches_Employe vide dans
   l'Annuaire_Employes implique nécessairement l'absence de toute paie de
   statut EMISE ; ces deux constats (Requirement 1 et Requirement 4)
   déclenchent donc le **même** comportement d'affichage (message
   d'absence, ni Selecteur_De_Periode ni Tableau_Bilan_Fiscal) plutôt que
   deux comportements distincts.

**Hors périmètre explicite de cette spec** :

- toute génération de document de versement officiel (formulaire
  gouvernemental de remise) ;
- toute soumission électronique aux gouvernements du Québec ou du Canada ;
- toute modification de `payroll_engine/` ou `models/` — cette spec ajoute
  une lecture d'agrégation dans `app/`, sans toucher au moteur ;
- tout nouveau calcul fiscal — tous les montants affichés proviennent
  exclusivement de `PayrollResult.retenues_employe` et
  `PayrollResult.cotisations_employeur` déjà persistés.

**Cadre normatif appliqué** :

- Règle 01 — tout montant agrégé par le Bilan_Fiscal reste un `Decimal`
  depuis sa lecture (`PayrollResult.model_validate_json`) jusqu'à son
  affichage ; aucune conversion en `float` n'est introduite à aucune étape
  de l'agrégation ou de l'affichage.
- Règle 02 — le Bilan_Fiscal n'invente aucune nouvelle `CalculationTrace`
  ni aucune nouvelle formule fiscale ; il agrège exclusivement des montants
  déjà calculés et tracés par le moteur.
- Règle 04 — aucune donnée personnelle réelle d'employé n'apparaît dans les
  tests ou exemples de cette spec ; le Bilan_Fiscal n'affiche que des
  montants agrégés, jamais de détail nominatif par employé.
- Règle 05 — le Bilan_Fiscal ne code en dur aucun taux, plafond ni règle de
  répartition provinciale/fédérale au-delà de la nature fixe de chaque
  cotisation (RRQ/RQAP/FSS/CNESST/CNT provinciaux, AE et impôt fédéral
  fédéraux) déjà déterminée par la structure de `RetenuesEmploye` et
  `CotisationsEmployeur`.

**Contrats consommés sans modification** (déjà figés par les specs
antérieures) :

- `models.payroll_result.PayrollResult`, `RetenuesEmploye`,
  `CotisationsEmployeur`, `MontantAvecTrace`.
- `models.enums.StatutDePaie` (seule la valeur `EMISE` est considérée).
- `models.pay_period.PayPeriod` (champ `date_paiement`).
- `payroll_engine.register.chemin_bd_production`.
- `app.logique_metier.dernieres_paies` (module de référence pour le style
  de lecture SQL directe — cette spec étend ce module ou en crée un
  nouveau dans le même style, sans jamais appeler de fonction privée de
  `payroll_engine.register`, décision n° 5 déjà actée par
  `interface-streamlit`).

## Glossary

- **Bilan_Fiscal** : la nouvelle section du Tableau_De_Bord introduite par
  cette spec, affichée sous la liste des Fiches_Employe existante, qui
  présente le Selecteur_De_Periode et le Tableau_Bilan_Fiscal.
- **Selecteur_De_Periode** : la liste déroulante, positionnée en haut à
  droite de la section Bilan_Fiscal, qui permet à l'opérateur de choisir
  une Periode_Fiscale parmi les Annee_Complete et les Mois_Fiscal
  effectivement disponibles.
- **Periode_Fiscale** : la valeur sélectionnée dans le Selecteur_De_Periode
  — soit une Annee_Complete, soit un Mois_Fiscal.
- **Annee_Complete** : une option du Selecteur_De_Periode représentant une
  année civile entière (ex. « 2026 (année complète) »), présente
  uniquement si le Registre_Maitre contient au moins une paie EMISE dont
  l'année de rattachement correspond à cette année.
- **Mois_Fiscal** : une option du Selecteur_De_Periode représentant un mois
  civil d'une année donnée (ex. « Juillet 2026 »), présente uniquement si
  le Registre_Maitre contient au moins une paie EMISE dont le mois et
  l'année de rattachement correspondent à ce mois.
- **Mois_De_Rattachement** (et **année de rattachement**) : le mois et
  l'année de `PayPeriod.date_paiement` d'une paie — la valeur utilisée
  pour classer cette paie dans le Selecteur_De_Periode et pour déterminer
  si elle appartient à la Periode_Fiscale sélectionnée (décision n° 1 de
  l'Introduction).
- **Tableau_Bilan_Fiscal** : le tableau à trois colonnes (« Retenues et
  cotisations », « QC », « CA ») affiché dans le Bilan_Fiscal pour la
  Periode_Fiscale sélectionnée.
- **Paies_Agregees** : l'ensemble des paies de statut `StatutDePaie.EMISE`
  du Registre_Maitre dont le Mois_De_Rattachement (et l'année de
  rattachement) correspond à la Periode_Fiscale sélectionnée — jamais les
  paies `BROUILLON`, `ANNULEE`, ni les versions `REMPLACE_PAR`.
- **Registre_Maitre** : la base SQLite (`payroll.db`, atteinte via
  `chemin_bd_production()`) déjà utilisée par le reste de l'application
  pour persister les `PayrollResult`.
- **PayrollResult**, **RetenuesEmploye**, **CotisationsEmployeur**,
  **StatutDePaie** : contrats figés par `moteur-paie-contrats`, consommés
  sans modification.

## Requirements

### Requirement 1: Emplacement de la section Bilan fiscal

**User Story:** En tant qu'opérateur de paie, je veux voir un bilan fiscal
directement dans le tableau de bord, afin de connaître rapidement les
montants à verser aux gouvernements sans naviguer vers un autre écran.

#### Acceptance Criteria

1. THE Tableau_De_Bord SHALL afficher une section nommée « Bilan fiscal »
   immédiatement sous la liste des Fiches_Employe existante, que cette
   liste soit vide ou non.
2. IF la liste des Fiches_Employe de l'Annuaire_Employes est vide, THEN
   THE Bilan_Fiscal SHALL appliquer le comportement défini par le
   Requirement 4 (absence de paie émise) — une liste d'employés vide
   impliquant nécessairement l'absence de toute paie de statut EMISE.

---

### Requirement 2: Alimentation dynamique du Selecteur_De_Periode

**User Story:** En tant qu'opérateur de paie, je veux choisir un mois ou une
année complète parmi les périodes pour lesquelles des paies ont réellement
été émises, afin de ne jamais consulter un bilan pour une période inventée
ou sans données.

#### Acceptance Criteria

1. IF le Registre_Maitre contient au moins une paie de statut EMISE, THEN
   THE Bilan_Fiscal SHALL déterminer le Mois_De_Rattachement et l'année
   de rattachement de chaque paie EMISE (Acceptance Criterion 2) et
   afficher un Selecteur_De_Periode positionné en haut à droite de la
   section.
2. THE Selecteur_De_Periode SHALL déterminer le Mois_De_Rattachement et
   l'année de rattachement de chaque paie à partir du mois et de l'année
   de `PayPeriod.date_paiement` de cette paie.
3. THE Selecteur_De_Periode SHALL lister exclusivement les Annee_Complete
   pour lesquelles le Registre_Maitre contient au moins une paie de statut
   EMISE dont l'année de rattachement correspond à cette année.
4. THE Selecteur_De_Periode SHALL lister exclusivement les Mois_Fiscal
   pour lesquels le Registre_Maitre contient au moins une paie de statut
   EMISE dont le mois et l'année de rattachement correspondent à ce mois.
5. THE Selecteur_De_Periode SHALL présenter chaque Annee_Complete sous la
   forme « <AAAA> (année complète) » (ex. « 2026 (année complète) »).
6. THE Selecteur_De_Periode SHALL présenter chaque Mois_Fiscal sous la
   forme « <Nom_du_mois> <AAAA> », où <Nom_du_mois> est l'un des douze
   noms suivants, avec cette orthographe et cette casse exactes (première
   lettre en majuscule) : Janvier, Février, Mars, Avril, Mai, Juin,
   Juillet, Août, Septembre, Octobre, Novembre, Décembre (ex.
   « Juillet 2026 »).
7. THE Selecteur_De_Periode SHALL ordonner ses options par année de
   rattachement décroissante puis, pour chaque année, présenter l'option
   Annee_Complete avant les options Mois_Fiscal de cette année, ces
   dernières ordonnées par mois croissant.

---

### Requirement 3: Sélection par défaut à l'ouverture

**User Story:** En tant qu'opérateur de paie, je veux que le bilan fiscal
s'ouvre déjà sur la période la plus pertinente selon la date du jour, afin
de ne pas devoir chercher manuellement le mois à verser à chaque
consultation.

#### Acceptance Criteria

1. WHEN le Bilan_Fiscal s'affiche pour la première fois depuis
   l'ouverture de la session ET la date courante est comprise entre le
   1er et le 15 du mois courant inclusivement, THE Selecteur_De_Periode
   SHALL présélectionner le Mois_Fiscal correspondant au mois précédant
   le mois courant.
2. WHEN le Bilan_Fiscal s'affiche pour la première fois depuis
   l'ouverture de la session ET la date courante est comprise entre le
   16 et le dernier jour du mois courant inclusivement, THE
   Selecteur_De_Periode SHALL présélectionner le Mois_Fiscal
   correspondant au mois courant.
3. IF le Mois_Fiscal déterminé par l'Acceptance Criterion 1 ou 2
   ci-dessus ne correspond à aucune option du Selecteur_De_Periode au
   moment de l'affichage, THEN THE Selecteur_De_Periode SHALL
   présélectionner le Mois_Fiscal le plus récent parmi ses options
   disponibles à ce moment.
4. IF l'opérateur a sélectionné manuellement, durant la session en
   cours, un Mois_Fiscal différent de celui présélectionné par les
   critères 1, 2 ou 3, THEN THE Selecteur_De_Periode SHALL conserver ce
   choix manuel lors de tout réaffichage subséquent du Bilan_Fiscal au
   cours de cette même session, sans réappliquer la présélection
   automatique.
5. THE Bilan_Fiscal SHALL déterminer la date courante utilisée aux
   critères 1 et 2 à partir de l'horloge du poste de travail au moment
   de l'affichage initial de la session.

---

### Requirement 4: Absence de paie émise dans le système

**User Story:** En tant qu'opérateur de paie, je veux être informé
clairement si aucune paie n'a encore été émise, afin de comprendre pourquoi
aucun bilan fiscal ne s'affiche plutôt que de croire l'écran défectueux.

#### Acceptance Criteria

1. IF le Registre_Maitre ne contient aucune paie de statut EMISE, THEN THE
   Bilan_Fiscal SHALL afficher, chaque fois que la section Bilan_Fiscal est
   affichée ou rafraîchie, un message indiquant l'absence de paie émise à
   la place du Selecteur_De_Periode et du Tableau_Bilan_Fiscal, sans
   afficher ni l'un ni l'autre.

---

### Requirement 5: Colonnes du Tableau_Bilan_Fiscal

**User Story:** En tant qu'opérateur de paie, je veux voir les montants
répartis entre le palier Québec et le palier Canada, afin de savoir combien
verser à chaque gouvernement.

#### Acceptance Criteria

1. THE Tableau_Bilan_Fiscal SHALL comporter exactement trois colonnes,
   dans cet ordre : « Retenues et cotisations », « QC », « CA », sans
   colonne additionnelle (notamment aucune colonne d'index ou de numéro
   de ligne générée automatiquement par le composant d'affichage).
2. WHERE le Tableau_Bilan_Fiscal est affiché (voir Requirement 4 pour le
   cas d'absence totale de paie EMISE, où ni le Tableau_Bilan_Fiscal ni
   sa ligne d'en-tête ne sont affichés), THE Tableau_Bilan_Fiscal SHALL
   afficher une ligne d'en-tête visible portant littéralement les trois
   libellés « Retenues et cotisations », « QC » et « CA », dans l'ordre
   défini par l'Acceptance Criterion 1 — jamais un sous-ensemble de ces
   libellés.

---

### Requirement 6: Retenues sur le salaire de l'employé

**User Story:** En tant qu'opérateur de paie, je veux voir le détail des
retenues sur le salaire des employés pour la période choisie, réparties
entre QC et CA, afin de vérifier les montants avant de les verser.

#### Acceptance Criteria

1. THE Tableau_Bilan_Fiscal SHALL afficher une ligne d'en-tête fusionnée
   sur les trois colonnes portant le libellé « Retenues sur le salaire de
   l'employé », immédiatement suivie, dans cet ordre, des quatre lignes
   décrites par les Acceptance Criteria 2 à 5 ci-dessous, y compris
   lorsque la période sélectionnée ne contient aucune Paie_Agregee (dans
   ce cas, chacune des quatre lignes affiche zéro dans ses deux colonnes
   QC et CA).
2. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « RRQ » dont la
   colonne QC contient la somme des `RetenuesEmploye.rrq.montant` de
   toutes les Paies_Agregees de la période sélectionnée, arrondie à deux
   décimales, et dont la colonne CA affiche explicitement la valeur
   zéro, y compris lorsque cette somme est nulle.
3. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « RQAP » dont la
   colonne QC contient la somme des `RetenuesEmploye.rqap.montant` de
   toutes les Paies_Agregees de la période sélectionnée, arrondie à deux
   décimales, et dont la colonne CA affiche explicitement la valeur
   zéro, y compris lorsque cette somme est nulle.
4. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « AE » dont la
   colonne QC affiche explicitement la valeur zéro et dont la colonne CA
   contient la somme des `RetenuesEmploye.ae.montant` de toutes les
   Paies_Agregees de la période sélectionnée, arrondie à deux décimales,
   y compris lorsque cette somme est nulle.
5. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « Impôt sur le revenu
   retenu » dont la colonne QC contient la somme des
   `RetenuesEmploye.impot_qc_retenu.montant` des Paies_Agregees et dont la
   colonne CA contient la somme des
   `RetenuesEmploye.impot_federal_retenu.montant` des Paies_Agregees.
6. THE Tableau_Bilan_Fiscal SHALL exclure `RetenuesEmploye.
   impot_qc_formule` et `RetenuesEmploye.impot_federal_formule` de
   chacune des sommes affichées aux Acceptance Criteria 2 à 5, ces deux
   champs ne devant contribuer à aucun total du bloc « Retenues sur le
   salaire de l'employé ».

---

### Requirement 7: Total des retenues

**User Story:** En tant qu'opérateur de paie, je veux voir le total des
retenues employé par palier, afin de connaître le sous-total avant d'y
ajouter les cotisations patronales.

#### Acceptance Criteria

1. THE Tableau_Bilan_Fiscal SHALL afficher, immédiatement après les
   quatre lignes du Requirement 6 (Acceptance Criteria 2 à 5) et avant
   toute ligne de cotisations patronales, une ligne « Total des
   retenues » dont la colonne QC contient la somme exacte (sans
   arrondissement additionnel) des colonnes QC de ces quatre lignes, et
   dont la colonne CA contient la somme exacte (sans arrondissement
   additionnel) des colonnes CA de ces mêmes quatre lignes, chaque
   colonne étant affichée avec exactement deux décimales.
2. IF au moins une des quatre lignes du Requirement 6 (Acceptance
   Criteria 2 à 5) n'a pas de valeur calculée disponible pour la
   colonne QC ou pour la colonne CA, THEN THE Tableau_Bilan_Fiscal
   SHALL considérer cette valeur comme nulle (zéro) dans la somme de la
   colonne concernée de la ligne « Total des retenues », sans
   interrompre l'affichage des autres lignes du tableau.
3. IF les quatre lignes du Requirement 6 (Acceptance Criteria 2 à 5)
   n'ont aucune valeur calculée disponible, THEN THE Tableau_Bilan_Fiscal
   SHALL ne pas afficher la ligne « Total des retenues » pour la
   colonne concernée et SHALL afficher à sa place une indication
   explicite d'indisponibilité, sans interrompre l'affichage des
   autres lignes du tableau.

---

### Requirement 8: Cotisations patronales

**User Story:** En tant qu'opérateur de paie, je veux voir le détail des
cotisations patronales pour la période choisie, réparties entre QC et CA,
afin de vérifier les montants avant de les verser.

#### Acceptance Criteria

1. THE Tableau_Bilan_Fiscal SHALL afficher une ligne d'en-tête fusionnée
   sur les trois colonnes portant le libellé « Cotisations patronales »,
   immédiatement suivie des six lignes décrites par les Acceptance
   Criteria 2 à 7 ci-dessous.
2. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « RRQ employeur »
   dont la colonne QC contient la somme des
   `CotisationsEmployeur.rrq_employeur.montant` des Paies_Agregees et dont
   la colonne CA contient zéro.
3. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « RQAP employeur »
   dont la colonne QC contient la somme des
   `CotisationsEmployeur.rqap_employeur.montant` des Paies_Agregees et
   dont la colonne CA contient zéro.
4. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « AE employeur » dont
   la colonne QC contient zéro et dont la colonne CA contient la somme
   des `CotisationsEmployeur.ae_employeur.montant` des Paies_Agregees.
5. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « FSS » dont la
   colonne QC contient la somme des `CotisationsEmployeur.fss.montant`
   des Paies_Agregees et dont la colonne CA contient zéro.
6. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « CNESST » dont la
   colonne QC contient la somme des `CotisationsEmployeur.cnesst.montant`
   des Paies_Agregees et dont la colonne CA contient zéro.
7. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « CNT » dont la
   colonne QC contient la somme des `CotisationsEmployeur.cnt.montant`
   des Paies_Agregees et dont la colonne CA contient zéro.
8. IF au moins une des Paies_Agregees de la période affichée a
   `CotisationsEmployeur.cnesst_en_attente_classification` à `true`,
   THEN THE Tableau_Bilan_Fiscal SHALL afficher, adjacent à la ligne
   « CNESST », une indication visible signalant que le montant CNESST
   de cette ligne repose sur une classification en attente et peut être
   sujet à révision.

---

### Requirement 9: Total des cotisations et grand total

**User Story:** En tant qu'opérateur de paie, je veux voir le total des
cotisations patronales, le grand total par palier et le grand total
combiné, afin de connaître le montant exact à transmettre à chaque
gouvernement ainsi que le montant total tous paliers confondus.

#### Acceptance Criteria

1. THE Tableau_Bilan_Fiscal SHALL afficher une ligne « Total des
   cotisations », positionnée immédiatement après les six lignes du
   Requirement 8 (Acceptance Criteria 2 à 7), dont la colonne QC
   contient la somme exacte (arithmétique décimale, sans arrondissement
   additionnel) des colonnes QC de ces six lignes et dont la colonne CA
   contient la somme exacte des colonnes CA de ces mêmes six lignes, les
   deux montants étant affichés avec exactement deux décimales dans le
   même format monétaire que les autres lignes du tableau.
2. THE Tableau_Bilan_Fiscal SHALL afficher, immédiatement après la ligne
   « Total des cotisations », une ligne « Grand total » dont la colonne
   QC contient la somme exacte (arithmétique décimale, sans
   arrondissement additionnel) de la colonne QC de la ligne « Total des
   retenues » (Requirement 7) et de la colonne QC de la ligne « Total
   des cotisations » (Acceptance Criterion 1 ci-dessus), et dont la
   colonne CA contient la somme exacte de la colonne CA de ces deux
   mêmes lignes, les deux montants étant affichés avec exactement deux
   décimales dans le même format monétaire que les autres lignes du
   tableau.
3. THE Tableau_Bilan_Fiscal SHALL afficher, comme dernière ligne du
   tableau et immédiatement après la ligne « Grand total », une ligne
   « Grand total combiné (QC + CA) » dont la cellule QC/CA — fusionnée
   sur les colonnes QC et CA — contient la somme exacte (arithmétique
   décimale, sans arrondissement additionnel) du montant QC et du
   montant CA de la ligne « Grand total » (Acceptance Criterion 2
   ci-dessus), affichée avec exactement deux décimales dans le même
   format monétaire que les autres lignes du tableau — jamais une
   colonne supplémentaire du Tableau_Bilan_Fiscal (Requirement 5,
   Acceptance Criterion 1, demeure inchangé : exactement trois
   colonnes).
4. IF une ou plusieurs des valeurs sources requises pour le calcul de la
   ligne « Total des cotisations », de la ligne « Grand total » (la
   ligne « Total des retenues » du Requirement 7 et la ligne « Total des
   cotisations ») ou de la ligne « Grand total combiné (QC + CA) » sont
   absentes ou invalides, THEN THE Tableau_Bilan_Fiscal SHALL afficher, à
   la place du montant numérique concerné, un indicateur d'erreur
   signalant l'impossibilité de calcul pour la ligne affectée, plutôt
   qu'un montant calculé.

---

### Requirement 10: Portée de l'agrégation par période

**User Story:** En tant qu'opérateur de paie, je veux que le bilan fiscal
n'agrège que les paies officiellement émises de la période choisie, afin de
ne jamais verser un montant basé sur une paie provisoire, annulée ou
remplacée.

#### Acceptance Criteria

1. WHERE la Periode_Fiscale sélectionnée dans le Selecteur_De_Periode
   correspond à un mois unique (un Mois_De_Rattachement et une année de
   rattachement), THE Bilan_Fiscal SHALL agréger exclusivement les paies de
   statut EMISE dont le Mois_De_Rattachement et l'année de rattachement
   correspondent à cette Periode_Fiscale, y compris lorsque aucune paie
   EMISE ne correspond, auquel cas le Bilan_Fiscal affiche un total agrégé
   de zéro pour chaque montant.
2. WHERE la Periode_Fiscale sélectionnée est une Annee_Complete, THE
   Bilan_Fiscal SHALL agréger toutes les paies de statut EMISE dont l'année
   de rattachement correspond à cette Annee_Complete, tous mois confondus,
   y compris lorsque aucune paie EMISE ne correspond, auquel cas le
   Bilan_Fiscal affiche un total agrégé de zéro pour chaque montant.
3. THE Bilan_Fiscal SHALL exclure des Paies_Agregees toute paie de statut
   `BROUILLON`, `ANNULEE` ou `REMPLACE_PAR`.
4. WHEN l'opérateur modifie la sélection dans le Selecteur_De_Periode vers
   une nouvelle Periode_Fiscale, THE Bilan_Fiscal SHALL recalculer et
   afficher l'agrégation correspondant à cette nouvelle Periode_Fiscale
   sans nécessiter d'action supplémentaire de l'opérateur.

---

### Requirement 11: Source des montants agrégés

**User Story:** En tant que développeur du projet, je veux que le bilan
fiscal réutilise exclusivement les montants déjà calculés et tracés par le
moteur de paie, afin de ne jamais dupliquer ni réinventer une règle
fiscale dans la couche d'affichage.

#### Acceptance Criteria

1. THE Bilan_Fiscal SHALL obtenir chaque montant affiché exclusivement par
   sommation directe des valeurs des champs `PayrollResult.retenues_employe`
   et `PayrollResult.cotisations_employeur` des Paies_Agregees, sans
   appliquer aucune formule fiscale, arrondi ou transformation
   supplémentaire.
2. THE Bilan_Fiscal SHALL conserver chaque montant agrégé sous forme de
   `Decimal` depuis sa désérialisation via
   `PayrollResult.model_validate_json` jusqu'à son affichage, sans jamais le
   convertir en `float` à aucune étape intermédiaire de lecture, de
   sommation ou d'affichage.
3. IF la désérialisation du `payload_json` persisté d'une paie des
   Paies_Agregees échoue (JSON invalide ou non conforme au schéma
   `PayrollResult`), THEN THE Bilan_Fiscal SHALL interrompre l'agrégation
   de la Periode_Fiscale concernée et afficher un message indiquant
   l'échec de lecture d'une paie, sans afficher de Tableau_Bilan_Fiscal
   pour cette période.
