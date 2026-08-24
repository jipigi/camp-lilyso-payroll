# Requirements Document

## Introduction

Cette fonctionnalité corrige une incohérence d'affichage du sélecteur d'employé du Formulaire_Paie et ajoute deux actions destructives contrôlées : la suppression physique d'un brouillon de paie non émis, et l'annulation d'une paie déjà émise (sans jamais la supprimer physiquement, conformément à l'immutabilité historique du registre). Seule la présélection par défaut du Radio_Statut_Correction (flux « Corriger une paie émise ») change, passant à « EMISE » ; les options du radio bouton BROUILLON/EMISE existant du Formulaire_Paie, sa présence, ainsi que le Radio_Statut_Nouvelle_Paie du flux « Nouvelle paie », restent hors périmètre de cette spec et inchangés (décision actée avec l'utilisateur).

Portée technique : `app/pages_ui/formulaire_paie.py`, `app/pages_ui/bulletin_paie.py`, `app/pages_ui/fiche_employe_detaillee.py`, `app/logique_metier/annuaire_coordonnees.py`, `payroll_engine/register.py`. Périmètre Camp LilySO uniquement (règle 03) ; aucune donnée personnelle réelle dans les exemples ci-dessous (règle 04, identifiants fictifs `EMP001`, `EMP002`).

## Glossary

- **Formulaire_Paie** : `app/pages_ui/formulaire_paie.py`, écran de saisie/assemblage/enregistrement d'une paie (flux « Nouvelle paie » et « Corriger une paie émise »).
- **Bulletin_De_Paie** : `app/pages_ui/bulletin_paie.py`, écran de consultation en lecture seule d'une paie déjà enregistrée.
- **Fiche_Employe_Detaillee** : `app/pages_ui/fiche_employe_detaillee.py`, écran de détail d'un employé.
- **Registre** : `payroll_engine/register.py`, module de persistance SQLite du registre maître des paies.
- **Paie_Brouillon** : une paie de statut `StatutDePaie.BROUILLON`.
- **Paie_Emise** : une paie de statut `StatutDePaie.EMISE`.
- **Paie_Annulee** : une paie de statut `StatutDePaie.ANNULEE`.
- **Fiche_Coordonnees** : `app.logique_metier.annuaire_coordonnees.FicheCoordonnees`, portant notamment `prenom`, `nom`, `courriel`.
- **Libelle_Employe** : le texte d'affichage d'un employé dans un sélecteur, produit selon les règles de repli du Requirement 1.
- **Selecteur_Employe_Formulaire** : le `st.selectbox("Employé", ...)` de la section « Nouvelle paie » du Formulaire_Paie (`_section_nouvelle_paie`).
- **Radio_Statut_Correction** : le `st.radio("Statut de la nouvelle version", ["BROUILLON", "EMISE"], key="fp_corriger_statut_choisi")` de la section « Corriger une paie émise » du Formulaire_Paie (`_section_corriger_paie`).
- **Radio_Statut_Nouvelle_Paie** : le `st.radio("Statut", ["BROUILLON", "EMISE"], key=f"{cle_prefixe}_statut_choisi")` de `_section_enregistrement`, tel qu'invoqué depuis la section « Nouvelle paie » du Formulaire_Paie (`_section_nouvelle_paie`, `cle_prefixe="fp_nouvelle"`).
- **Bouton_Danger** : visuel de bouton à fond rouge et police blanche, réservé exclusivement aux deux boutons destructifs de cette spec (« Supprimer le brouillon », « Supprimer la paie »).
- **Popup_Confirmation_Brouillon** : la fenêtre modale de confirmation affichée par le Formulaire_Paie avant toute suppression physique d'une Paie_Brouillon.
- **Popup_Confirmation_Paie_Emise** : la fenêtre modale de confirmation affichée par le Bulletin_De_Paie avant toute annulation d'une Paie_Emise.
- **`supprimer_paie_brouillon`** : nouvelle fonction publique du Registre — suppression physique d'une ligne `BROUILLON`.
- **`annuler_paie`** : nouvelle fonction publique du Registre — annulation (mutation de statut vers `ANNULEE`) d'une ligne `EMISE`, avec décrément des cumuls YTD.
- **Cumuls_YTD** : `payroll_engine.register.lire_cumuls_ytd`/`cumuls_ytd`, les onze catégories monétaires cumulées par employé et année civile.

## Requirements

### Requirement 1: Format d'affichage cohérent de l'employé dans le Formulaire_Paie

**User Story:** En tant qu'opérateur de paie, je veux voir le nom et le courriel de l'employé dans la liste déroulante de sélection du Formulaire_Paie, afin de retrouver rapidement le bon employé sans devoir mémoriser son identifiant technique.

#### Acceptance Criteria

1. WHEN le Selecteur_Employe_Formulaire affiche une option pour un employé dont une Fiche_Coordonnees existe avec `prenom`, `nom` et `courriel` tous renseignés, THE Formulaire_Paie SHALL afficher cette option sous la forme exacte `"{prenom} {nom} ({courriel})"`.
2. WHEN le Selecteur_Employe_Formulaire affiche une option pour un employé dont une Fiche_Coordonnees existe avec `prenom` et `nom` renseignés mais `courriel` absent ou vide, THE Formulaire_Paie SHALL afficher cette option sous la forme exacte `"{prenom} {nom}"`, sans parenthèses.
3. IF aucune Fiche_Coordonnees n'existe pour un employé, OR IF la Fiche_Coordonnees existe mais que `prenom` et `nom` sont tous deux absents ou vides, THEN THE Formulaire_Paie SHALL afficher l'identifiant technique de cet employé comme option du Selecteur_Employe_Formulaire.
4. THE Formulaire_Paie SHALL produire, pour un même employé et les mêmes Fiche_Coordonnees, un Libelle_Employe strictement identique à celui affiché par la Fiche_Employe_Detaillee pour ce même employé.
5. THE Formulaire_Paie SHALL lire l'ensemble des Fiche_Coordonnees nécessaires à la construction du Selecteur_Employe_Formulaire par un seul appel groupé, sans effectuer un appel de lecture distinct par option affichée.

### Requirement 2: Fonction de formatage partagée

**User Story:** En tant que développeur de l'application, je veux une seule fonction de formatage du Libelle_Employe partagée entre écrans, afin d'éviter la duplication de cette logique et de garantir que toute future correction s'applique uniformément.

#### Acceptance Criteria

1. THE Registre_Logique_Metier SHALL exposer une fonction publique unique de construction du Libelle_Employe, réutilisée à la fois par le Formulaire_Paie et par la Fiche_Employe_Detaillee.
2. WHEN la Fiche_Employe_Detaillee construit le Libelle_Employe d'un employé, THE Fiche_Employe_Detaillee SHALL invoquer cette même fonction publique plutôt qu'une logique de formatage locale dupliquée.
3. THE fonction publique de construction du Libelle_Employe SHALL être une fonction pure, sans accès disque ni import du module d'affichage, prenant en paramètre l'ensemble des Fiche_Coordonnees déjà lues par l'appelant.

### Requirement 3: Suppression physique d'une paie brouillon depuis le Formulaire_Paie

**User Story:** En tant qu'opérateur de paie, je veux pouvoir supprimer un brouillon de paie que je ne souhaite plus conserver, afin de garder le registre des paies propre sans devoir passer par une manipulation technique de la base de données.

#### Acceptance Criteria

1. WHILE la paie chargée dans le Formulaire_Paie est une Paie_Brouillon, THE Formulaire_Paie SHALL afficher un bouton « Supprimer le brouillon » au style Bouton_Danger, positionné à droite du bouton « Assembler la paie ».
2. IF la paie chargée dans le Formulaire_Paie n'est pas une Paie_Brouillon, THEN THE Formulaire_Paie SHALL ne jamais afficher le bouton « Supprimer le brouillon ».
3. WHEN l'opérateur actionne le bouton « Supprimer le brouillon », THE Formulaire_Paie SHALL afficher la Popup_Confirmation_Brouillon portant le titre exact « Supprimer le brouillon ? », le texte exact « Vous perdrez les dates et les heures saisies dans ce brouillon de paie. », un bouton « Supprimer le brouillon » au style Bouton_Danger et un bouton « Annuler » au style secondaire par défaut.
4. WHEN l'opérateur actionne le bouton « Supprimer le brouillon » de la Popup_Confirmation_Brouillon, THE Registre SHALL supprimer physiquement de la table des paies la ligne correspondant à cette Paie_Brouillon.
5. WHEN l'opérateur actionne le bouton « Annuler » de la Popup_Confirmation_Brouillon, THE Formulaire_Paie SHALL fermer la Popup_Confirmation_Brouillon sans invoquer `supprimer_paie_brouillon`.
6. IF `supprimer_paie_brouillon` est invoquée avec l'identifiant d'une paie dont le statut n'est pas `BROUILLON`, THEN THE Registre SHALL refuser l'opération sans modifier la table des paies et SHALL signaler explicitement le statut courant refusé.
7. IF `supprimer_paie_brouillon` est invoquée avec un identifiant de paie absent du Registre, THEN THE Registre SHALL signaler explicitement l'absence de cette paie sans modifier la table des paies.
8. THE Registre SHALL laisser les Cumuls_YTD strictement inchangés après toute suppression réussie d'une Paie_Brouillon.
9. WHEN la suppression d'une Paie_Brouillon réussit, THE Formulaire_Paie SHALL réafficher un formulaire de nouvelle paie sans aucune donnée pré-remplie provenant du brouillon supprimé.

### Requirement 4: Annulation d'une paie émise depuis le Bulletin_De_Paie

**User Story:** En tant qu'opérateur de paie, je veux pouvoir annuler une paie déjà émise par erreur, afin de corriger le registre sans laisser une paie erronée compter dans les cumuls annuels de l'employé.

#### Acceptance Criteria

1. WHILE la paie affichée dans le Bulletin_De_Paie est une Paie_Emise, THE Bulletin_De_Paie SHALL afficher un bouton « Supprimer la paie » au style Bouton_Danger, positionné à gauche du bouton « Corriger cette paie ».
2. IF la paie affichée dans le Bulletin_De_Paie n'est pas une Paie_Emise, THEN THE Bulletin_De_Paie SHALL ne jamais afficher le bouton « Supprimer la paie ».
3. WHEN l'opérateur actionne le bouton « Supprimer la paie », THE Bulletin_De_Paie SHALL afficher la Popup_Confirmation_Paie_Emise portant le titre exact « Supprimer la paie de {Prénom Nom} ? », le texte exact « Cette paie est marquée comme émise, si vous la supprimez, vous perdrez le calcul du salaire et des cotisations. », un bouton « Supprimer la paie de {Prénom Nom} » au style Bouton_Danger et un bouton « Annuler » au style secondaire par défaut, où `{Prénom Nom}` est le prénom et le nom affichés de l'employé de cette paie.
4. WHEN l'opérateur actionne le bouton « Supprimer la paie de {Prénom Nom} » de la Popup_Confirmation_Paie_Emise, THE Registre SHALL faire transiter le statut de cette Paie_Emise vers `ANNULEE` sans jamais supprimer physiquement la ligne correspondante de la table des paies.
5. WHEN l'opérateur actionne le bouton « Annuler » de la Popup_Confirmation_Paie_Emise, THE Bulletin_De_Paie SHALL fermer la Popup_Confirmation_Paie_Emise sans invoquer `annuler_paie`.
6. WHEN `annuler_paie` fait transiter avec succès une Paie_Emise vers `ANNULEE`, THE Registre SHALL décrémenter chacune des onze catégories monétaires des Cumuls_YTD de l'employé et de l'année civile concernés, exactement de la contribution de cette paie.
7. IF la transition de statut vers `ANNULEE` réussit mais que le décrément des Cumuls_YTD échoue, THEN THE Registre SHALL annuler la transition de statut de sorte que la ligne concernée conserve son statut `EMISE` d'origine, de façon à ce que la transition de statut et le décrément des Cumuls_YTD soient toujours visibles ensemble ou jamais du tout.
8. IF `annuler_paie` est invoquée avec l'identifiant d'une paie dont le statut n'est pas `EMISE`, THEN THE Registre SHALL refuser l'opération sans modifier la table des paies ni les Cumuls_YTD, et SHALL signaler explicitement le statut courant refusé.
9. IF `annuler_paie` est invoquée avec un identifiant de paie absent du Registre, THEN THE Registre SHALL signaler explicitement l'absence de cette paie sans modifier la table des paies ni les Cumuls_YTD.
10. WHEN l'annulation d'une Paie_Emise réussit, THE Bulletin_De_Paie SHALL réafficher la même paie avec son statut `ANNULEE`, sans afficher ni le bouton « Corriger cette paie » ni le bouton « Supprimer la paie » pour cette paie.

### Requirement 5: Visuel des boutons destructifs

**User Story:** En tant qu'opérateur de paie, je veux distinguer visuellement au premier coup d'œil les actions destructives des autres actions de l'écran, afin d'éviter un clic accidentel sur une action irréversible.

#### Acceptance Criteria

1. THE Formulaire_Paie SHALL afficher le bouton « Supprimer le brouillon » et le bouton « Supprimer le brouillon » de la Popup_Confirmation_Brouillon avec un fond rouge et une police blanche.
2. THE Bulletin_De_Paie SHALL afficher le bouton « Supprimer la paie » et le bouton « Supprimer la paie de {Prénom Nom} » de la Popup_Confirmation_Paie_Emise avec un fond rouge et une police blanche.
3. THE Formulaire_Paie SHALL afficher le bouton « Annuler » de la Popup_Confirmation_Brouillon avec le style secondaire par défaut de Streamlit, sans fond rouge — la police du style secondaire par défaut de Streamlit, y compris si elle est blanche, reste admise.
4. THE Bulletin_De_Paie SHALL afficher le bouton « Annuler » de la Popup_Confirmation_Paie_Emise avec le style secondaire par défaut de Streamlit, sans fond rouge — la police du style secondaire par défaut de Streamlit, y compris si elle est blanche, reste admise.
5. WHERE le style Bouton_Danger est appliqué à un bouton natif Streamlit du Formulaire_Paie ou du Bulletin_De_Paie, THE module concerné SHALL documenter explicitement cet écart au style primaire/secondaire natif de l'application dans un commentaire du fichier source.

### Requirement 6: Présélection du statut lors de la correction d'une paie émise

**User Story:** En tant qu'opérateur de paie, je veux que le statut proposé par défaut lors de la correction d'une paie déjà émise soit « EMISE », afin de ne pas devoir sélectionner manuellement cette option à chaque correction alors que c'est le résultat attendu dans l'immense majorité des cas.

#### Acceptance Criteria

1. WHEN le Formulaire_Paie affiche le Radio_Statut_Correction dans le flux « Corriger une paie émise », THE Formulaire_Paie SHALL présélectionner l'option « EMISE ».
2. THE Formulaire_Paie SHALL continuer à présélectionner l'option « BROUILLON » sur le Radio_Statut_Nouvelle_Paie du flux « Nouvelle paie », sans changement de ce comportement existant.
