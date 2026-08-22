# Requirements Document

## Introduction

Cette fonctionnalité étend le Selecteur_De_Periode existant du Tableau_De_Bord (jusqu'ici limité à la section « Bilan fiscal ») pour qu'il pilote également la section « Employés », tout en simplifiant ses options à des années complètes uniquement (retrait des options de mois fiscal). Elle inclut aussi trois ajustements ciblés de la section Employés (retrait de la colonne « No. d'employé », tri par prénom/nom, renommage et enrichissement de la colonne « Paies ») et l'ajout d'une validation explicite de la date de paiement au moment de l'émission d'une paie dans le Formulaire_Paie.

Portée technique : `app/pages_ui/tableau_de_bord.py`, `app/logique_metier/bilan_fiscal.py`, `app/pages_ui/formulaire_paie.py`, `app/logique_metier/annuaire_coordonnees.py`, `app/logique_metier/dernieres_paies.py`. Périmètre Camp LilySO uniquement (règle 03) ; aucune donnée personnelle réelle dans les exemples ci-dessous (règle 04, identifiants fictifs `EMP001`, `EMP002`).

## Glossary

- **Tableau_De_Bord** : page d'accueil de l'Interface_Streamlit (`app/pages_ui/tableau_de_bord.py::render`), affichant les sections « Employés » et « Bilan fiscal ».
- **Selecteur_De_Periode_Global** : la liste déroulante unique, positionnée en haut de la page au même niveau visuel que le titre « Tableau de bord », alignée à droite, qui pilote à la fois la section Employés et la section Bilan fiscal. Remplace l'ancien sélecteur de période propre à la section Bilan fiscal.
- **Annee_Complete** : une `PeriodeFiscale` dont `mois` est `None` — seul type de période désormais offert par le Selecteur_De_Periode_Global (les options de type Mois_Fiscal sont retirées).
- **Annee_Avec_Paie_Emise** : une année pour laquelle il existe au moins une Paie_Emise (statut `EMISE`) dont la date de paiement (`PayPeriod.date_paiement`) tombe dans cette année.
- **Option_Annee_Courante_De_Repli** : l'option `"{année courante} (année complète)"`, ajoutée au Selecteur_De_Periode_Global uniquement lorsque l'année courante n'est pas déjà une Annee_Avec_Paie_Emise.
- **Paie_Brouillon** : une paie de statut `BROUILLON` (`StatutDePaie.BROUILLON`).
- **Paie_Emise** : une paie de statut `EMISE` (`StatutDePaie.EMISE`).
- **Colonne_Paies** : la colonne du tableau des employés (anciennement « Dernière paie », renommée « Paies ») affichant, pour un employé, l'ensemble de ses Paie_Brouillon et Paie_Emise dont la date de paiement tombe dans l'année sélectionnée par le Selecteur_De_Periode_Global.
- **Fiche_Coordonnees** : `app.logique_metier.annuaire_coordonnees.FicheCoordonnees`, portant notamment `prenom` et `nom`, lue via `lire_coordonnees(employe_id)`.
- **Formulaire_Paie** : `app/pages_ui/formulaire_paie.py`, écran de saisie et d'émission d'une paie.
- **Bouton_Emission** : le bouton « Enregistrer la paie » du Formulaire_Paie lorsqu'il est actionné avec le statut choisi `EMISE` (`app/pages_ui/formulaire_paie.py::_section_enregistrement`).

## Requirements

### Requirement 1: Simplification du Selecteur_De_Periode_Global à des années uniquement

**User Story:** En tant qu'opérateur de paie, je veux que le sélecteur de période du Tableau de bord n'offre que des années complètes, afin de ne plus avoir à choisir entre une vue par mois et une vue annuelle qui n'est plus nécessaire à mon usage.

#### Acceptance Criteria

1. THE Tableau_De_Bord SHALL construire les options du Selecteur_De_Periode_Global exclusivement à partir des Annee_Avec_Paie_Emise, triées par année décroissante, sans jamais inclure d'option de type Mois_Fiscal.
2. WHEN l'année courante n'est pas une Annee_Avec_Paie_Emise, THE Tableau_De_Bord SHALL ajouter l'Option_Annee_Courante_De_Repli aux options du Selecteur_De_Periode_Global, positionnée selon le même ordre décroissant par année que les options des Annee_Avec_Paie_Emise existantes.
3. WHEN l'année courante est une Annee_Avec_Paie_Emise, THE Tableau_De_Bord SHALL exclure l'Option_Annee_Courante_De_Repli des options du Selecteur_De_Periode_Global.
4. IF l'année courante figure parmi les options du Selecteur_De_Periode_Global, THEN THE Tableau_De_Bord SHALL présélectionner l'année courante comme valeur par défaut du Selecteur_De_Periode_Global.
5. IF l'année courante ne figure pas parmi les options du Selecteur_De_Periode_Global, THEN THE Tableau_De_Bord SHALL présélectionner l'Option_Annee_Courante_De_Repli comme valeur par défaut du Selecteur_De_Periode_Global.
6. THE Tableau_De_Bord SHALL afficher le Selecteur_De_Periode_Global au même niveau visuel que le titre « Tableau de bord », aligné à droite de la page.
7. THE Tableau_De_Bord SHALL utiliser la sélection courante du Selecteur_De_Periode_Global pour piloter à la fois la section Employés et la section Bilan fiscal.

### Requirement 2: Comportement de la section Bilan fiscal avec le sélecteur simplifié

**User Story:** En tant qu'opérateur de paie, je veux que la section Bilan fiscal continue de refléter fidèlement l'année sélectionnée même si le sélecteur n'offre plus de vue par mois, afin de conserver une vision annuelle cohérente des charges et retenues.

#### Acceptance Criteria

1. WHEN une Annee_Avec_Paie_Emise est sélectionnée dans le Selecteur_De_Periode_Global, THE Tableau_De_Bord SHALL afficher dans la section Bilan fiscal le Tableau_Bilan_Fiscal agrégé à partir des Paie_Emise dont la date de paiement tombe dans l'année sélectionnée.
2. WHEN l'Option_Annee_Courante_De_Repli est sélectionnée dans le Selecteur_De_Periode_Global, THE Tableau_De_Bord SHALL afficher dans la section Bilan fiscal le Tableau_Bilan_Fiscal produit par `construire_tableau_bilan_fiscal` pour un tuple de paies vide, dans lequel chaque ligne et chaque total du Tableau_Bilan_Fiscal affichent explicitement la valeur zéro, sans qu'aucune ligne ni aucun total n'affiche l'indicateur d'indisponibilité pour ce cas.
3. IF la construction ou l'affichage du Tableau_Bilan_Fiscal échoue pour l'année sélectionnée, THEN THE Tableau_De_Bord SHALL afficher dans la section Bilan fiscal un message d'erreur ou un indicateur d'indisponibilité explicite, à la place du Tableau_Bilan_Fiscal, sans interrompre l'affichage du reste de la page.

### Requirement 3: Retrait de la colonne « No. d'employé »

**User Story:** En tant qu'opérateur de paie, je veux que le tableau des employés du Tableau de bord n'affiche plus le numéro d'employé, afin de réduire l'encombrement visuel d'une colonne peu utile au quotidien.

#### Acceptance Criteria

1. THE Tableau_De_Bord SHALL afficher le tableau des employés sans la colonne « No. d'employé », c'est-à-dire en retirant complètement la structure de cette colonne du DOM rendu (ni l'en-tête `<th>No. d'employé</th>`, ni la cellule de données `<td>{employe.id}</td>` pour chacune des lignes, ni aucun élément vide ou de remplacement à la place de cette colonne), sans modifier l'ordre ni le contenu des autres colonnes du tableau.
2. IF le champ `employe.id` est utilisé en interne dans le rendu du tableau des employés (par exemple comme valeur d'un attribut `href` d'un lien), THEN THE Tableau_De_Bord SHALL ne jamais afficher `employe.id` comme texte visible dans le tableau des employés.

### Requirement 4: Tri des employés par Prénom Nom

**User Story:** En tant qu'opérateur de paie, je veux que les employés soient listés par ordre alphabétique de prénom et nom, afin de retrouver rapidement un employé dans une liste qui grandit avec les saisons.

#### Acceptance Criteria

1. IF une Fiche_Coordonnees existe pour un employé, THEN THE Tableau_De_Bord SHALL utiliser comme clé de tri de la ligne de cet employé la concaténation du `prenom`, d'un espace unique, puis du `nom`, issus de sa Fiche_Coordonnees.
2. IF aucune Fiche_Coordonnees n'existe pour un employé, THEN THE Tableau_De_Bord SHALL utiliser `Employee.nom_affichage` comme clé de tri de la ligne de cet employé.
3. THE Tableau_De_Bord SHALL trier l'ensemble des lignes du tableau selon l'ordre croissant de leur clé de tri, en ignorant la casse (majuscules/minuscules) et les signes diacritiques (accents, cédille), et en utilisant `Employee.id` par ordre croissant comme critère de départage lorsque deux lignes ont une clé de tri identique.

### Requirement 5: Renommage et contenu de la colonne « Paies »

**User Story:** En tant qu'opérateur de paie, je veux voir en un coup d'œil toutes les paies brouillon et émises de l'année sélectionnée pour chaque employé, afin de savoir rapidement qui a une paie en attente d'émission ou déjà émise pour cette année.

#### Acceptance Criteria

1. THE Tableau_De_Bord SHALL afficher la colonne anciennement nommée « Dernière paie » sous le nom « Paies ».
2. WHEN l'employé a au moins une Paie_Brouillon ou une Paie_Emise dont la date de paiement tombe dans l'année sélectionnée par le Selecteur_De_Periode_Global, THE Tableau_De_Bord SHALL afficher dans la Colonne_Paies de cet employé une ligne par paie correspondante, chaque ligne indiquant explicitement si la paie est une Paie_Brouillon ou une Paie_Emise ainsi que sa date de paiement, les lignes étant séparées par un retour à la ligne HTML (`<br>`).
3. THE Tableau_De_Bord SHALL ordonner les lignes de la Colonne_Paies en plaçant d'abord toutes les Paie_Brouillon de l'année sélectionnée, triées par date de paiement décroissante puis, en cas d'égalité de date de paiement entre deux Paie_Brouillon, par `LignePaieResume.numero_periode` croissant, puis toutes les Paie_Emise de l'année sélectionnée, triées selon la même règle (date de paiement décroissante puis `LignePaieResume.numero_periode` croissant en cas d'égalité de date de paiement entre deux Paie_Emise).
4. IF l'employé n'a aucune Paie_Brouillon ni Paie_Emise dont la date de paiement tombe dans l'année sélectionnée (que l'employé possède ou non d'autres paies dont la date de paiement tombe hors de l'année sélectionnée), THEN THE Tableau_De_Bord SHALL afficher dans la Colonne_Paies de cet employé un texte indiquant explicitement l'absence de paie pour l'année sélectionnée, sans jamais afficher les paies dont la date de paiement tombe hors de l'année sélectionnée.
5. IF la lecture des paies d'un employé échoue, THEN THE Tableau_De_Bord SHALL afficher dans la Colonne_Paies de cet employé un texte indiquant l'erreur rencontrée lors de cette lecture, sans empêcher l'affichage des lignes des autres employés du tableau.
6. WHERE la lecture des paies d'un employé pour l'année sélectionnée réussit ET ne retourne aucune Paie_Brouillon ni Paie_Emise pour cette année, THE Tableau_De_Bord SHALL toujours afficher le texte d'absence de paie du critère 4 pour cet employé, sans jamais afficher à la place le texte d'erreur du critère 5.

### Requirement 6: Validation de la date de paiement à l'émission d'une paie

**User Story:** En tant qu'opérateur de paie, je veux être bloqué avec un message clair si j'essaie d'émettre une paie sans date de paiement valide, afin de ne jamais me retrouver avec une erreur d'assemblage tardive et peu explicite au moment de l'émission.

#### Acceptance Criteria

1. WHEN l'opérateur actionne le Bouton_Emission avec le statut choisi `EMISE` ET que la date de paiement saisie dans le Formulaire_Paie est absente ou strictement antérieure à la date de fin de la période saisie (`date_fin`), THE Formulaire_Paie SHALL bloquer immédiatement toute poursuite du traitement d'émission et afficher un message d'erreur indiquant que la date de paiement doit être renseignée avant l'émission.
2. WHILE le statut choisi est `EMISE`, THE Formulaire_Paie SHALL exécuter la validation de la date de paiement avant toute tentative d'insertion de la paie.
3. WHEN l'opérateur actionne le Bouton_Emission avec le statut choisi `EMISE` ET que la date de paiement saisie est présente et non strictement antérieure à la date de fin de la période saisie (`date_fin`), THE Formulaire_Paie SHALL poursuivre le traitement d'émission sans afficher le message d'erreur de validation de la date de paiement.
4. WHILE le statut choisi est `BROUILLON`, THE Formulaire_Paie SHALL ne pas appliquer la validation de la date de paiement propre à l'émission décrite par ce Requirement, sans pour autant effacer un message d'erreur de validation de la date de paiement déjà affiché avant que l'opérateur ne change le statut choisi de `EMISE` à `BROUILLON`.
