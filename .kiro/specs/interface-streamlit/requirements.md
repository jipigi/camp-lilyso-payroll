# Requirements Document

<!-- Titre métier : Document d'exigences — interface-streamlit. Les en-têtes
structurels de niveau supérieur (Requirements Document, Introduction, Glossary,
Requirements) et les libellés « Requirement N », « User Story: »,
« Acceptance Criteria » sont maintenus en anglais pour la conformité au format
Kiro. Tout le contenu métier est rédigé en français. -->

## Introduction

Cette spec implémente **l'étape 7** du plan d'implémentation
(`docs/plan-implementation.md`), après `moteur-paie-contrats` (étape 1),
`gains-bruts-vacances-hs` (étape 2), `cotisations-sociales-qc` (étape 3),
`impots-retenues-source` (étape 4), `charges-patronales` (étape 5) et
`net-cumuls-registre` (étape 6, qui a livré `payroll_engine/net_pay.py` et
`payroll_engine/register.py`). Elle est livrée **avant** `bulletin-pdf`
(étape 8), inversion actée explicitement par le projet le 2026-08-05 (voir
note dans `docs/plan-implementation.md`) pour permettre la saisie et la
consultation du registre dès cette étape.

Cette spec livre une **interface locale Streamlit** (`app/`) qui consomme le
moteur de paie déjà entièrement livré et testé, sans le modifier :

- un **tableau de bord** listant les employés comme point d'entrée de
  l'application, à partir d'un nouvel **annuaire employés** local, propre
  à l'interface (l'application n'a jusqu'ici aucune notion d'employé
  persistée : `register.py` ne fait qu'indexer des paies par `employe_id`
  en texte libre) ;
- une **fiche employé détaillée**, organisée par sections (informations
  employé, coordonnées, paies), qui regroupe la gestion de la Fiche_Employe
  et de ses paies sur un seul écran ;
- une **identité visuelle** reprenant les couleurs et le logo du Camp
  LilySO, et le respect de normes d'utilisabilité reconnues (heuristiques
  Nielsen Norman Group) sur l'ensemble de l'interface ;
- la possibilité de **modifier les données fiscales TD1/TP-1015.3** d'une
  Fiche_Employe existante, sans devoir attendre la saisie d'une nouvelle
  paie ;
- une saisie **simplifiée** de la période de paie : trois dates saisies
  une seule fois (début, fin, paiement) pour la période entière, plutôt
  que semaine par semaine ;
- saisie des heures par semaine constituante (heures normales et
  supplémentaires), jours fériés manuels, avec pré-remplissage des
  paramètres TP-1015.3/TD1/taux horaire depuis la fiche employé et des
  cumuls de début de paie depuis le registre maître ;
- assemblage de la paie via `payroll_engine.net_pay.assembler_paie` et
  affichage complet du résultat (gains, retenues, cotisations employeur,
  net, coût employeur, trace) ;
- enregistrement de la paie dans le registre maître via
  `payroll_engine.register.inserer_paie`, en `BROUILLON` ou en `EMISE` ;
- correction d'une paie déjà émise par annulation-remplacement via
  `payroll_engine.register.remplacer_paie` ;
- consultation du registre maître : historique d'une Paie_Logique
  (`lire_historique_paie`) et cumuls YTD d'un employé
  (`lire_cumuls_ytd`) ;
- gestion explicite, fail-fast, des cas d'erreur du domaine
  (`UnsupportedPayrollCase`, `MissingParameterError`) et des refus du
  registre (`ValueError`, `KeyError`), sans jamais les masquer (règle 03).

**Hors périmètre explicite de cette spec** :

- toute génération de bulletin PDF — reportée à l'étape 8 (`bulletin-pdf`),
  qui ajoutera un bouton de génération PDF à l'interface livrée ici ;
- tout export CSV/JSON de la paie assemblée. Le plan d'implémentation
  mentionnait initialement un export CSV/JSON comme livrable temporaire ;
  cette spec **s'en écarte explicitement** (décision confirmée par
  l'utilisateur en phase clarify, 2026-08-06) car l'interface elle-même
  permet déjà la consultation complète d'une paie assemblée, insérée, ou de
  l'historique/cumuls — un export à plat n'apporte pas de valeur
  supplémentaire à ce stade. `docs/plan-implementation.md` sera mis à jour
  pour refléter cette déviation ;
- toute modification de `payroll_engine/` ou `models/` — cette spec ajoute
  une couche `app/` qui **consomme** le moteur existant sans le modifier ;
- toute formule fiscale, tout calcul de paie propre à l'interface — tous
  les calculs restent exclusivement portés par `assembler_paie` ;
- l'authentification, le contrôle d'accès ou le déploiement réseau —
  l'interface est un outil **local**, exécuté sur le poste de
  l'utilisateur (`streamlit run app/main.py`), sans exposition réseau
  prévue par cette spec.

**Décisions actées (confirmées par l'utilisateur en phase clarify)** :

1. **Annuaire employés propre à l'interface** — cette spec introduit un
   nouvel **Annuaire_Employes**, persisté dans un fichier **JSON local**
   distinct du registre SQLite (`payroll.db`), résidant lui aussi hors du
   dépôt versionné (règle 04). L'annuaire porte des fiches `Employee`
   (modèle déjà figé par `moteur-paie-contrats`) sérialisées via
   `model_dump_json()`/`model_validate_json()` — aucun nouveau schéma de
   sérialisation. `payroll_engine/register.py` n'est pas modifié.
2. **Statuts de paie supportés par l'interface** — l'opérateur peut
   enregistrer une paie assemblée en `StatutDePaie.BROUILLON` (modifiable,
   sans effet sur `cumuls_ytd`) ou en `StatutDePaie.EMISE` (immuable, met à
   jour `cumuls_ytd`). Le choix du statut à l'insertion est un contrôle
   explicite de l'interface, jamais une valeur par défaut implicite.
3. **Saisie simplifiée des dates de période** (révision du 2026-08-06,
   remplace la décision initiale de saisie manuelle des deux
   `WeekSegment`) — l'opérateur saisit une seule fois trois dates pour la
   période de paie dans son ensemble (date de début, date de fin, date de
   paiement) ; `numero_periode` et `annee_fiscale` restent saisis via des
   listes déroulantes bornées. L'interface **dérive mécaniquement** les
   deux `WeekSegment` requis par `PayPeriod` à partir de la date de début
   et de la date de fin saisies (arithmétique de dates pure, pas de calcul
   fiscal — voir Requirement 7 « Saisie de la période de paie et des
   heures »). Les heures normales et supplémentaires restent saisies par
   semaine constituante (aucun changement sur ce point).
4. **Pré-remplissage, jamais d'automatisme silencieux** — `taux_horaire_effectif`,
   `montant_total_TP1015_3_effectif`, `exoneration_TP1015_3_effectif`,
   `retenue_additionnelle_QC_effective`, `montant_total_TD1_effectif`,
   `exoneration_TD1_effective`, `retenue_additionnelle_federale_effective`
   sont **pré-remplis** depuis la fiche `Employee` sélectionnée
   (`taux_horaire_base`, `montant_total_TP1015_3`, `exoneration_TP1015_3`,
   `retenue_additionnelle_QC`, `montant_total_TD1`, `exoneration_TD1`,
   `retenue_additionnelle_federale`), mais **restent modifiables** par
   l'opérateur pour la paie courante avant assemblage.
5. **Annulation-remplacement incluse** — l'interface expose une action de
   correction d'une paie déjà `EMISE`, qui invoque
   `payroll_engine.register.remplacer_paie`. Cette action n'est **pas**
   reportée à une itération future.
6. **Sélection de l'année des paramètres fiscaux** — l'opérateur choisit
   l'année d'application des paramètres fiscaux parmi les années pour
   lesquelles `parameters/<AAAA>/` existe sur disque ; l'interface charge
   alors `load_parameters(annee, Juridiction.QUEBEC)` et
   `load_parameters(annee, Juridiction.CANADA)` et les fusionne en un seul
   `ParametresAnnee` (même patron de fusion que
   `tests/strategies.py::_charger_parametres_annee_2026_qc_ca` : la racine
   Québec reçoit les sections `assurance_emploi` et `impot_federal` de la
   racine Canada, via `model_copy(update=...)`, sans mutation).
   `annee_fiscale` de la période de paie est fixée à cette même année.
7. **Pré-remplissage de `cumuls_debut`** — l'interface appelle
   automatiquement `lire_cumuls_ytd(employe_id, annee_civile)` pour
   pré-remplir `PayrollInput.cumuls_debut`, plutôt que de laisser
   l'opérateur saisir manuellement les onze catégories monétaires
   cumulées.
8. **`saison` pré-rempli, modifiable** — le champ `saison` transmis à
   `inserer_paie`/`remplacer_paie` est un champ texte libre pré-rempli par
   convention `"Été <annee_fiscale>"`, que l'opérateur peut modifier avant
   l'insertion.
9. **Génération automatique de `id_paie`** — l'interface génère
   `id_paie` selon la convention déterministe
   `PAIE-<employe_id>-<annee_fiscale>-<numero_periode zero-paddé sur 2
   chiffres>-v<version>` (ex. `PAIE-EMP001-2026-03-v1`). L'opérateur ne
   saisit jamais `id_paie` manuellement.
10. **Aucun export CSV/JSON** — voir « Hors périmètre explicite » ci-dessus.
11. **Jours fériés manuels saisis en dollars, sans conversion
    heures→dollars** (confirmé par l'utilisateur le 2026-08-06) — le champ
    `PayrollInput.jours_feries_manuels` continue d'être saisi directement
    en dollars par l'opérateur (comportement déjà porté par le contrat).
    Aucune conversion heures→dollars n'est introduite dans cette spec :
    aucune formule officielle sourcée (CNT) n'a été validée pour cette
    conversion à ce stade, et le Camp LilySO ne l'utilise pas dans la
    saison courante.
12. **Identité visuelle et normes d'utilisabilité** — l'interface reprend
    la palette de couleurs et le logo du Camp LilySO (source :
    `intake/ressources/code-couleurs.txt` et
    `intake/ressources/logo-camp-lilyso.png`, consultés le 2026-08-06) et
    applique les heuristiques d'utilisabilité Nielsen Norman Group
    pertinentes pour une interface de saisie de données métier locale
    (Requirement 3). Le logo, résidant dans `intake/` (hors dépôt
    versionné, règle 04), DOIT être copié vers un emplacement versionné de
    `app/` (ex. `app/assets/logo-camp-lilyso.png`) — cette copie n'est pas
    une donnée personnelle sensible (illustration générique de mouettes),
    et sera traduite en tâche explicite lors de la phase tasks.
13. **Point d'entrée restructuré en tableau de bord** — le point d'entrée
    de l'interface devient un tableau de bord listant tous les employés
    (Requirement 4), plutôt qu'un écran de sélection générique. La gestion
    complète d'un employé (informations, coordonnées, paies) est regroupée
    sur une fiche employé détaillée unique (Requirement 5).
14. **Édition des données fiscales TD1/TP-1015.3 après création** — une
    Fiche_Employe existante peut voir ses six champs TD1/TP-1015.3 mis à
    jour depuis sa fiche détaillée (Requirement 11), sans effet
    rétroactif sur les paies déjà assemblées ou insérées.

**Alignement du formulaire de création de Fiche_Employe sur le fichier
source RH** : la structure du formulaire de création de Fiche_Employe
(Requirement 4, déclenché depuis le tableau de bord) a été alignée sur la
structure de champs du fichier source
`intake/fiches-employes/Fiches employés.xlsx` (une feuille par employé),
consulté localement le 2026-08-06 — uniquement pour ses noms de champs,
jamais pour une valeur réelle qu'il contient (règle 04). Les champs NAS,
adresse résidentielle, courriel et numéro de téléphone présents dans ce
fichier source sont explicitement exclus du formulaire : ils n'existent
pas dans le modèle `Employee` et l'Annuaire_Employes ne DOIT jamais
tenter de les collecter ni de les persister (règle 04).

**Fiche_Coordonnees — besoin opérationnel exprimé explicitement par
l'utilisateur (2026-08-06)** : l'exclusion du NAS, de l'adresse
résidentielle, du courriel et du numéro de téléphone du formulaire de
création de Fiche_Employe (ci-dessus) ne signifie pas que ces
coordonnées n'ont aucune valeur opérationnelle pour le camp — elles
restent nécessaires pour contacter réellement un employé. Cette spec
introduit donc, en réponse à ce besoin, une **Fiche_Coordonnees**
strictement séparée du contrat `Employee` : un nouvel annuaire
purement informationnel (Annuaire_Coordonnees, Requirement 20), lié à
une Fiche_Employe par `id` uniquement, jamais lu ni écrit par
`payroll_engine/` ni par aucun calcul, et jamais transmis à
`assembler_paie`, `PayrollInput` ou `Employee`. Ce principe de
séparation stricte entre (a) le contrat `Employee` du moteur de paie —
déjà figé par `moteur-paie-contrats`, qui interdit explicitement ces
champs via la garde `reject_sensitive_fields` (règle 04) — et (b) une
donnée opérationnelle propre à l'interface est la seule façon de
satisfaire à la fois le besoin de contact réel et la règle 04
appliquée au contrat de calcul.

**Cadre normatif appliqué** :

- Règle 01 — `decimal.Decimal` obligatoire partout où l'interface manipule
  un montant ou une quantité d'heures ; tout champ de saisie numérique
  DOIT être converti en `Decimal` via une chaîne de caractères, jamais via
  `float` (ni par un composant Streamlit natif de type `st.number_input`
  configuré en flottant).
- Règle 02 — l'interface n'invente aucune nouvelle `CalculationTrace` ;
  elle affiche exclusivement les traces déjà produites par les fonctions
  de calcul invoquées via `assembler_paie`.
- Règle 03 — périmètre Camp LilySO strict ; l'interface ne réintroduit
  aucun garde-fou de périmètre (déjà porté par `PayrollInput`/`Employee`/
  `PayPeriod`) et ne masque, n'intercepte silencieusement, ni ne
  reconvertit jamais `UnsupportedPayrollCase` ni `MissingParameterError` —
  ces exceptions DOIVENT être affichées à l'opérateur avec leur message
  d'origine intact.
- Règle 04 — aucune donnée personnelle réelle dans le dépôt, les tests ou
  la documentation ; l'Annuaire_Employes et le registre `payroll.db`
  résident tous deux hors du dépôt versionné (`%APPDATA%\CampLilySO\`) ;
  tous les exemples et fixtures de test utilisent exclusivement des
  identifiants fictifs (`EMP001`, `EMP002`, ...).
- Règle 05 — aucun taux, plafond ni constante fiscale codé en dur dans
  `app/` ; les paramètres transitent exclusivement par le `ParametresAnnee`
  chargé via `load_parameters`.
- Règle 06 — spec → tests (property + intégration) → implémentation →
  validation ; tests écrits avant le code ; la logique métier de `app/`
  DOIT être séparée du rendu Streamlit pour rester testable sans dépendre
  d'un environnement de rendu.

**Contrats consommés sans modification** (déjà figés par les six specs
antérieures) :

- `models.employee.Employee`, `models.pay_period.PayPeriod`,
  `models.pay_period.WeekSegment`, `models.payroll_input.PayrollInput`,
  `models.payroll_input.HeuresParSemaine`, `models.payroll_result.PayrollResult`,
  `models.cumuls.CumulsYTD`, `models.trace.CalculationTrace`,
  `models.enums.StatutDePaie`, `models.enums.Juridiction`,
  `models.enums.FrequencePaie`.
- `models.exceptions.PayrollDomainError`, `UnsupportedPayrollCase`,
  `MissingParameterError`.
- `payroll_engine.parameters_loader.ParametresAnnee`, `load_parameters`.
- `payroll_engine.net_pay.assembler_paie`.
- `payroll_engine.register.inserer_paie`, `lire_paie`,
  `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie`,
  `chemin_bd_production`.

## Glossary

- **Interface_Streamlit** : l'application locale livrée par cette spec
  (`app/`), exécutée via `streamlit run app/main.py`, qui consomme le
  moteur de paie et le registre maître sans les modifier.
- **Tableau_De_Bord** : l'écran d'entrée de l'Interface_Streamlit
  (Requirement 4), qui liste toutes les Fiches_Employe de
  l'Annuaire_Employes avec un résumé de leur situation (numéro, nom,
  dernière année fiscale de paie), et permet d'ajouter un employé ou une
  paie sans naviguer ailleurs au préalable.
- **Fiche_Employe_Detaillee** : l'écran unique (Requirement 5) qui
  regroupe, pour un employé sélectionné depuis le Tableau_De_Bord, trois
  sections distinctes : les informations non sensibles de l'employé, la
  Fiche_Coordonnees, et les paies de l'employé (consultation et ajout).
- **Logique_Metier_App** : l'ensemble des fonctions Python de `app/`
  responsables de la construction des objets du domaine (`Employee`,
  `PayPeriod`, `PayrollInput`), de l'invocation d'`assembler_paie` et des
  fonctions du registre, et de la traduction des exceptions en messages
  affichables — strictement séparée du code de rendu Streamlit (règle 06),
  pour rester testable par des tests unitaires ou property-based sans
  dépendre de `streamlit.testing.v1.AppTest`.
- **Annuaire_Employes** : le nouvel annuaire local introduit par cette
  spec, qui persiste des fiches `Employee` dans un fichier JSON résidant
  hors du dépôt versionné (chemin par défaut analogue à
  `chemin_bd_production()`, ex. `%APPDATA%\CampLilySO\employees.json`),
  injectable pour les tests.
- **Chemin_Annuaire** : le chemin du fichier JSON de l'Annuaire_Employes.
  Toute fonction de l'Annuaire_Employes DOIT accepter ce chemin en
  paramètre injectable, avec un chemin de production par défaut hors
  dépôt.
- **Fiche_Employe** : une entrée de l'Annuaire_Employes, une instance
  `Employee` complète et valide (déjà figée par `moteur-paie-contrats`).
- **Annuaire_Coordonnees** : le nouvel annuaire local introduit par cette
  spec (Requirement 20), purement informationnel, distinct de
  l'Annuaire_Employes et du registre `payroll.db`, qui persiste des
  Fiche_Coordonnees dans un fichier JSON résidant lui aussi hors du dépôt
  versionné (chemin par défaut analogue à `chemin_bd_production()`, ex.
  `%APPDATA%\CampLilySO\coordonnees.json`), injectable pour les tests.
  L'Annuaire_Coordonnees n'est jamais lu ni écrit par `payroll_engine/` ni
  par aucun calcul.
- **Fiche_Coordonnees** : une entrée de l'Annuaire_Coordonnees, contenant
  exclusivement les champs suivants : `employe_id` (clé de liaison vers
  une Fiche_Employe existante), `nom_complet_reel` (optionnel, texte
  libre), `nas` (optionnel, texte libre, jamais validé au format pour ne
  pas suggérer une obligation de le renseigner), `adresse_residentielle`
  (optionnel, texte libre), `courriel` (optionnel, texte libre),
  `telephone` (optionnel, texte libre). Aucun de ces champs n'est un
  `Decimal` ni consommé par un calcul — la règle 01 ne s'applique pas à
  la Fiche_Coordonnees (absence de montant monétaire). Une
  Fiche_Coordonnees n'est jamais une instance `Employee` ni un champ d'un
  `Employee` : elle ne transite jamais par le contrat de calcul.
- **Chemin_Coordonnees** : le chemin du fichier JSON de
  l'Annuaire_Coordonnees. Toute fonction de l'Annuaire_Coordonnees DOIT
  accepter ce chemin en paramètre injectable, avec un chemin de
  production par défaut hors dépôt.
- **Numéro d'employé** : la valeur saisie par l'opérateur au formulaire de
  création de Fiche_Employe (Requirement 4) pour désigner un employé (ex.
  `"1"`, `"23"`), transformée en `Employee.id` selon une convention
  zero-paddée sur 3 chiffres préfixée `EMP` (ex. `"1"` → `"EMP001"`,
  `"23"` → `"EMP023"`), cohérente avec les identifiants fictifs déjà
  utilisés partout ailleurs dans le projet (règle 04).
- **Formulaire_Paie** : l'ensemble des champs saisis ou pré-remplis par
  l'opérateur dans l'Interface_Streamlit pour construire un
  `PayrollInput` : période de paie (dates, `numero_periode`,
  `annee_fiscale`), heures par semaine, jours fériés manuels, taux
  horaire effectif, taux de vacances effectif, paramètres TP-1015.3/TD1
  effectifs.
- **Parametres_Annuels_Fusionnes** : le `ParametresAnnee` unique obtenu en
  fusionnant `load_parameters(annee, Juridiction.QUEBEC)` et
  `load_parameters(annee, Juridiction.CANADA)` pour l'année sélectionnée
  par l'opérateur, selon le patron de fusion déjà utilisé par
  `tests/strategies.py`.
- **Paie_Assemblee** : le `PayrollResult` produit par un appel à
  `assembler_paie`, affiché intégralement par l'Interface_Streamlit avant
  toute décision d'enregistrement.
- **Action_Enregistrer** : l'action déclenchée par l'opérateur qui invoque
  `inserer_paie(resultat, saison, chemin_bd)` avec le statut choisi
  (`BROUILLON` ou `EMISE`).
- **Action_Corriger** : l'action déclenchée par l'opérateur qui invoque
  `remplacer_paie(ancien_id, nouveau_resultat, saison, chemin_bd)` pour
  une Paie_Logique déjà `EMISE`.
- **Employee**, **PayPeriod**, **WeekSegment**, **HeuresParSemaine**,
  **PayrollInput**, **PayrollResult**, **CumulsYTD**, **CalculationTrace**,
  **StatutDePaie**, **ParametresAnnee**, **UnsupportedPayrollCase**,
  **MissingParameterError** : contrats figés par les specs antérieures,
  consommés sans modification.

## Requirements

### Requirement 1: Séparation logique métier / rendu (testabilité)

**User Story:** En tant que développeur du projet, je veux que la logique
métier de l'interface soit isolée du code de rendu Streamlit, afin de
pouvoir la tester unitairement et par property-based testing sans dépendre
d'un environnement de rendu.

#### Acceptance Criteria

1. LA Logique_Metier_App DOIT résider dans des fonctions Python pures ou
   quasi-pures (dépendances explicites en paramètres, pas de lecture
   implicite de `st.session_state` à l'intérieur de ces fonctions) situées
   hors de tout bloc de rendu Streamlit (`st.write`, `st.button`,
   `st.form`, etc.).
2. CHAQUE fonction de la Logique_Metier_App qui construit un objet du
   domaine (`Employee`, `PayPeriod`, `HeuresParSemaine`, `PayrollInput`) ou
   invoque `assembler_paie`, `inserer_paie`, `remplacer_paie`, `lire_paie`,
   `lire_historique_paie` ou `lire_cumuls_ytd` DOIT être appelable et
   testable indépendamment du module `app/main.py`.
3. LA Logique_Metier_App NE DOIT PAS importer le module `streamlit` pour
   son fonctionnement (aucun appel à une fonction `st.*` en dehors du
   module de rendu).

---

### Requirement 2: Annuaire employés — persistance et lecture

**User Story:** En tant qu'opérateur de paie, je veux consulter et créer des
fiches employé dans un annuaire local, afin de sélectionner un employé sans
ressaisir sa fiche complète à chaque paie.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT exposer une fonction de la Logique_Metier_App
   qui liste toutes les Fiches_Employe de l'Annuaire_Employes, triées par
   `id` croissant, à partir d'un Chemin_Annuaire injectable dont la valeur
   par défaut réside hors du dépôt versionné.
2. QUAND l'Annuaire_Employes n'existe pas encore au Chemin_Annuaire
   fourni, LA fonction de listage DOIT retourner un tuple vide, sans lever
   d'exception.
3. L'Interface_Streamlit DOIT exposer une fonction de la Logique_Metier_App
   qui enregistre une Fiche_Employe (création ou mise à jour par `id`) dans
   l'Annuaire_Employes, en réutilisant `Employee.model_dump_json()` pour la
   sérialisation — sans introduire de nouveau schéma de sérialisation.
4. L'Interface_Streamlit DOIT exposer une fonction de la Logique_Metier_App
   qui lit une Fiche_Employe unique par `id` depuis l'Annuaire_Employes, en
   réutilisant `Employee.model_validate_json()` pour la désérialisation.
5. SI l'`id` recherché est absent de l'Annuaire_Employes, ALORS la fonction
   de lecture unique DOIT lever une exception explicite (`KeyError` ou
   équivalent documenté) citant l'`id` recherché.
6. TOUTE écriture dans l'Annuaire_Employes DOIT être atomique : soit la
   fiche complète est persistée, soit le fichier reste inchangé (aucune
   écriture partielle visible en cas d'interruption).
7. L'Annuaire_Employes NE DOIT PAS dupliquer les garde-fous de périmètre
   déjà portés par le modèle `Employee` (province, taux de vacances) —
   toute tentative de création d'une Fiche_Employe hors matrice continue de
   lever `UnsupportedPayrollCase` depuis la construction `Employee(...)`
   elle-même, propagée sans interception par l'Annuaire_Employes.

---

### Requirement 3: Identité visuelle et normes d'utilisabilité

**User Story:** En tant que responsable du camp, je veux que l'interface
reprenne l'identité visuelle du site camplilyso.com et respecte les bonnes
pratiques d'utilisabilité reconnues, afin que l'outil soit cohérent avec la
marque et facile à utiliser pour l'opérateur.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT appliquer, de façon cohérente sur l'ensemble
   des écrans, la palette de couleurs du Camp LilySO (source :
   `intake/ressources/code-couleurs.txt`, consultée le 2026-08-06) : fond
   clair `#bad5f4` avec texte `#3d5775`, fond foncé `#1f2c3b` avec texte
   `#ffffff`, boutons d'action à fond `#7aaeea` avec texte `#3d5775` en
   gras.
2. L'Interface_Streamlit DOIT afficher, dans son en-tête sur chaque écran,
   le logo du Camp LilySO copié vers un emplacement versionné de `app/`
   (ex. `app/assets/logo-camp-lilyso.png`) — le fichier source résidant à
   `intake/ressources/logo-camp-lilyso.png` n'étant pas accessible en
   production (règle 04, `intake/` hors dépôt versionné). Cette copie
   n'est pas une donnée personnelle sensible (illustration générique de
   mouettes au-dessus de l'eau).
3. POUR CHAQUE action irréversible ou difficile à annuler
   (Action_Enregistrer en statut `EMISE`, Action_Corriger),
   L'Interface_Streamlit DOIT présenter une confirmation explicite à
   l'opérateur avant exécution (heuristique NN/g « contrôle et liberté de
   l'utilisateur »).
4. POUR CHAQUE champ de saisie correspondant à un ensemble fermé de
   valeurs déjà porté par un contrat existant (`taux_indemnite_vacances`,
   `StatutDePaie`, année des Parametres_Annuels_Fusionnes, etc.),
   L'Interface_Streamlit DOIT utiliser un contrôle de sélection (liste
   déroulante, case à cocher) plutôt qu'un champ de saisie libre
   (heuristique NN/g « reconnaissance plutôt que rappel »).
5. L'affichage d'une erreur (Requirement 16) DOIT rester visuellement
   distinct du reste de l'interface (ex. couleur ou icône dédiée), sans
   dépendre uniquement de la couleur pour transmettre l'information
   (accessibilité).

Note : cette identité visuelle s'inspire du ton estival du site
camplilyso.com (consulté le 2026-08-06, rendu général uniquement, aucune
valeur pixel-perfect extraite, aucune donnée personnelle concernée) et
applique, lorsqu'applicable à une interface de saisie de données métier
locale, les heuristiques d'utilisabilité Nielsen Norman Group suivantes :
visibilité de l'état du système, contrôle et liberté de l'utilisateur,
cohérence et standards, prévention des erreurs, reconnaissance plutôt que
rappel, aide au diagnostic et à la récupération des erreurs (satisfaite par
le Requirement 16), esthétique et design minimaliste. Les heuristiques non
applicables au périmètre MVP (recherche en texte libre à grande échelle,
raccourcis clavier avancés) ne sont pas retenues.

---

### Requirement 4: Tableau de bord des employés

**User Story:** En tant qu'opérateur de paie, je veux voir d'emblée la
liste de tous les employés avec un résumé de leur situation, afin de
choisir rapidement sur qui agir ou en ajouter un nouveau.

#### Acceptance Criteria

1. LE point d'entrée de l'Interface_Streamlit DOIT être un Tableau_De_Bord
   affichant la liste des Fiches_Employe de l'Annuaire_Employes
   (Requirement 2 AC1), triée par `id` croissant.
2. POUR CHAQUE Fiche_Employe listée, LE Tableau_De_Bord DOIT afficher au
   minimum : le numéro d'employé (`id`), le nom (`nom_affichage`), et
   l'année fiscale de la dernière paie générée pour cet employé (toutes
   années confondues, dérivée du registre maître selon l'AC3), ou une
   indication explicite d'absence de paie si aucune n'existe encore.
3. LA Logique_Metier_App DOIT exposer une fonction en lecture seule qui
   détermine, pour un `employe_id` donné, l'année fiscale de la paie la
   plus récente présente dans le registre maître (`chemin_bd`), en
   interrogeant directement et exclusivement les colonnes déjà
   documentées du schéma `paies` (`employe_id`, `annee_fiscale`) — sans
   dupliquer aucune règle de calcul, sans passer par une fonction privée
   de `payroll_engine/register.py` (dont le nom commence par `_`), et sans
   jamais modifier `payroll_engine/register.py` (Requirement 18). Cette
   fonction retourne une valeur absente explicite (ex. `None`) si aucune
   paie n'existe pour cet employé, sans lever d'exception.
4. DEPUIS le Tableau_De_Bord, L'Interface_Streamlit DOIT permettre
   d'ajouter un nouvel employé, ce qui déclenche le formulaire de création
   de Fiche_Employe (AC7 à AC12 ci-dessous).
5. DEPUIS chaque ligne du Tableau_De_Bord, L'Interface_Streamlit DOIT
   offrir un raccourci direct pour ajouter une nouvelle paie pour cet
   employé, en pré-sélectionnant l'année fiscale courante (année civile
   en cours au moment de l'utilisation) par défaut, modifiable par
   l'opérateur avant de poursuivre vers le Formulaire_Paie.
6. DEPUIS chaque ligne du Tableau_De_Bord, L'Interface_Streamlit DOIT
   permettre de naviguer vers la Fiche_Employe_Detaillee de cet employé
   (Requirement 5).
7. LE formulaire de création de Fiche_Employe DOIT collecter exactement
   les champs suivants : un numéro d'employé (converti en `id` selon la
   convention du Glossary, ex. saisie `"1"` → `"EMP001"`),
   `nom_affichage`, `date_naissance`, `titre_emploi`,
   `taux_horaire_base`, `date_embauche`, `date_fin_emploi` (optionnel),
   `taux_indemnite_vacances` (liste déroulante fermée limitée à
   `{Decimal("0.04"), Decimal("0.06")}`), `exoneration_TP1015_3` et
   `exoneration_TD1` (cases à cocher, pré-remplies à `False`).
8. LE formulaire de création de Fiche_Employe NE DOIT PAS exposer de champ
   de saisie pour un numéro d'assurance sociale, une adresse
   résidentielle, une adresse courriel ou un numéro de téléphone (règle
   04) — l'Annuaire_Employes NE DOIT jamais tenter de collecter ni de
   persister ces champs, y compris lorsqu'ils sont présents dans un
   fichier source externe de l'organisation.
9. DANS le formulaire de création de Fiche_Employe, `province_travail`
   DOIT être fixé à `Juridiction.QUEBEC` sans champ de saisie libre —
   affiché uniquement à titre informatif en lecture seule (règle 03).
10. QUAND l'opérateur soumet le formulaire de création de Fiche_Employe
    avec une année sélectionnée (Requirement 6), La Logique_Metier_App
    DOIT construire la Fiche_Employe via
    `Employee.avec_defauts_par_annee(annee_reference=<année sélectionnée>,
    id=..., nom_affichage=..., date_naissance=..., province_travail=
    Juridiction.QUEBEC, titre_emploi=..., taux_horaire_base=...,
    date_embauche=..., date_fin_emploi=..., taux_indemnite_vacances=...,
    exoneration_TP1015_3=..., exoneration_TD1=...)`, laissant cette
    fabrique dériver `montant_total_TP1015_3`, `montant_total_TD1`,
    `retenue_additionnelle_QC` et `retenue_additionnelle_federale` depuis
    les paramètres de l'année sélectionnée, sans ressaisie manuelle de ces
    quatre champs à la création.
11. APRÈS la construction via `Employee.avec_defauts_par_annee`,
    L'Interface_Streamlit DOIT afficher les quatre valeurs fiscales
    dérivées (`montant_total_TP1015_3`, `montant_total_TD1`,
    `retenue_additionnelle_QC`, `retenue_additionnelle_federale`) et
    permettre à l'opérateur de les ajuster avant l'Action_Enregistrer
    définitive dans l'Annuaire_Employes (Requirement 2 AC3).
12. IF la construction de l'`Employee` via `avec_defauts_par_annee` lève
    `MissingParameterError` ou `UnsupportedPayrollCase`, THEN
    L'Interface_Streamlit DOIT afficher le message d'origine de
    l'exception à l'opérateur sans l'intercepter silencieusement.

---

### Requirement 5: Fiche employé détaillée

**User Story:** En tant qu'opérateur de paie, je veux consulter toutes les
informations d'un employé sur un seul écran organisé par section, afin de
gérer sa fiche et ses paies sans naviguer entre plusieurs écrans
déconnectés.

#### Acceptance Criteria

1. LA Fiche_Employe_Detaillee DOIT présenter au moins trois sections
   visuellement distinctes : (a) informations non sensibles de l'employé
   (les champs du modèle `Employee`, hors coordonnées), (b) coordonnées
   opérationnelles (Fiche_Coordonnees, Requirement 20), (c) paies de
   l'employé.
2. LA section « paies de l'employé » DOIT permettre de sélectionner une
   année fiscale au moyen d'une liste déroulante dont chaque option
   affiche l'année suivie de la saison entre parenthèses lorsqu'au moins
   une paie existe pour cette année (ex. `"2026 (Été 2026)"`), la saison
   affichée étant celle de la paie la plus récente de cette année pour cet
   employé ; si aucune saison n'est disponible (aucune paie), l'année
   seule est affichée.
3. QUAND une année est sélectionnée dans cette liste déroulante,
   L'Interface_Streamlit DOIT afficher la liste des paies de cet employé
   pour cette année (toutes périodes confondues), au minimum
   `numero_periode`, `id_paie`, `version`, `statut`, `net`,
   `date_creation` — en s'appuyant sur les fonctions déjà prévues
   (`lire_historique_paie` par période, Requirement 14, ou la nouvelle
   fonction de lecture de l'AC3 du Requirement 4 si une itération par
   période s'avère nécessaire, sans dupliquer de logique de calcul).
4. EN PLUS de la liste des paies de l'année sélectionnée, cette section
   DOIT permettre de consulter, si elles existent pour au moins une paie
   de cette année, les valeurs TD1 et TP-1015.3 effectives utilisées
   (`montant_total_TP1015_3_effectif`, `exoneration_TP1015_3_effectif`,
   `retenue_additionnelle_QC_effective`, `montant_total_TD1_effectif`,
   `exoneration_TD1_effective`, `retenue_additionnelle_federale_effective`)
   ainsi que les cumuls YTD calculés pour cette année
   (`lire_cumuls_ytd(employe_id, annee_civile, chemin_bd)`, onze
   catégories déjà couvertes par le Requirement 15).
5. LA section « paies de l'employé » DOIT exposer un bouton pour ajouter
   une nouvelle paie, qui demande explicitement l'année fiscale
   (pré-remplie à l'année civile courante, modifiable) avant de
   poursuivre vers le Formulaire_Paie — cohérent avec le raccourci déjà
   offert par le Tableau_De_Bord (Requirement 4 AC5).
6. QUAND aucune paie n'existe encore pour l'employé sélectionné (toutes
   années confondues), la section « paies de l'employé » DOIT l'indiquer
   explicitement sans lever d'exception, tout en conservant le bouton
   d'ajout d'une nouvelle paie.

---

### Requirement 6: Sélection de l'année des paramètres fiscaux

**User Story:** En tant qu'opérateur de paie, je veux choisir l'année
d'application des paramètres fiscaux, afin que la paie soit calculée avec
les bons taux et plafonds officiels.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT présenter à l'opérateur une liste des années
   pour lesquelles un dossier `parameters/<AAAA>/` existe sur disque, et
   n'en admettre la sélection que parmi ces années.
2. QUAND l'opérateur sélectionne une année, L'Interface_Streamlit DOIT
   charger `load_parameters(annee, Juridiction.QUEBEC)` et
   `load_parameters(annee, Juridiction.CANADA)` puis les fusionner en un
   unique Parametres_Annuels_Fusionnes, sans dupliquer ni recalculer aucune
   valeur portée par ces deux appels.
3. `annee_fiscale` du `PayPeriod` construit par le Formulaire_Paie DOIT
   égaler l'année sélectionnée à cette étape.
4. IF le fichier `parameters/<annee>/quebec.json` ou
   `parameters/<annee>/canada.json` est absent au moment du chargement,
   THEN L'Interface_Streamlit DOIT afficher le message d'origine de
   l'exception `FileNotFoundError` levée par `load_parameters`, sans
   l'intercepter silencieusement.

---

### Requirement 7: Saisie de la période de paie et des heures

**User Story:** En tant qu'opérateur de paie, je veux saisir les dates de la
période de paie et les heures travaillées par semaine, afin de construire
l'entrée complète du moteur de calcul.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT permettre à l'opérateur de sélectionner
   `numero_periode` (borné à `[1, nb_periodes_annuelles]` du
   Parametres_Annuels_Fusionnes sélectionné) au moyen d'une liste
   déroulante.
2. L'Interface_Streamlit DOIT permettre à l'opérateur de saisir, pour la
   période de paie dans son ensemble (et non plus semaine par semaine),
   une date de début, une date de fin et une date de paiement — trois
   champs de date distincts, saisis une seule fois.
3. QUAND l'opérateur soumet le Formulaire_Paie, La Logique_Metier_App DOIT
   dériver automatiquement les deux `WeekSegment` requis par `PayPeriod` à
   partir de la date de début et de la date de fin saisies (première
   semaine : date de début à date de début + 6 jours ; seconde semaine :
   date de début + 7 jours à date de fin), sans qu'aucun champ de date
   supplémentaire ne soit demandé à l'opérateur pour cette dérivation.
   Cette dérivation est une décomposition purement mécanique de dates déjà
   saisies (arithmétique de dates), PAS un calcul fiscal ou métier — elle
   ne contrevient donc pas à la règle 03 (aucun calcul automatique de
   règle fiscale, ex. jours fériés).
4. IF la date de fin saisie ne correspond pas exactement à
   `date_debut + 13 jours` (contrainte déjà portée par `PayPeriod`/la
   contiguïté des deux `WeekSegment` dérivés), THEN L'Interface_Streamlit
   DOIT afficher le message d'origine de l'erreur de validation à
   l'opérateur sans l'intercepter silencieusement, cohérent avec l'AC7 sur
   `UnsupportedPayrollCase`/erreur de validation de forme.
5. L'Interface_Streamlit DOIT permettre à l'opérateur de saisir, pour
   chacune des deux semaines constituantes dérivées par l'AC3, une
   quantité d'heures normales et une quantité d'heures supplémentaires,
   chacune convertie en `Decimal` à partir d'une chaîne de caractères
   saisie (règle 01).
6. L'Interface_Streamlit DOIT permettre à l'opérateur de saisir un montant
   de jours fériés manuels, converti en `Decimal` à partir d'une chaîne de
   caractères saisie, avec `Decimal("0.00")` comme valeur pré-remplie.
7. QUAND l'opérateur soumet le Formulaire_Paie, La Logique_Metier_App DOIT
   construire un `HeuresParSemaine` par semaine dérivée par l'AC3, dans le
   même ordre, puis un `PayPeriod` à partir des deux `WeekSegment` et un
   `PayrollInput` à partir de l'ensemble — en laissant tous les
   garde-fous déjà portés par ces modèles (`moteur-paie-contrats`)
   s'appliquer sans duplication. IF cette construction lève
   `UnsupportedPayrollCase` ou une erreur de validation de forme, THEN
   L'Interface_Streamlit DOIT afficher le message d'origine à l'opérateur
   sans l'intercepter silencieusement ni poursuivre l'assemblage de la
   paie.

Note (décision du 2026-08-06) : la saisie des jours fériés manuels
(AC6) reste en dollars (comportement déjà porté par
`PayrollInput.jours_feries_manuels`), sans conversion heures→dollars —
aucune formule officielle sourcée (CNT) n'a été validée pour cette
conversion à ce stade, et le Camp LilySO ne l'utilise pas dans la saison
courante.

---

### Requirement 8: Pré-remplissage des paramètres effectifs de la paie

**User Story:** En tant qu'opérateur de paie, je veux que les paramètres de
rémunération et de retenue de la fiche employé soient pré-remplis pour la
paie courante, afin de ne pas les ressaisir tout en pouvant les corriger en
cas de changement ponctuel.

#### Acceptance Criteria

1. QUAND un employé est sélectionné (Requirement 4 ou 5),
   L'Interface_Streamlit DOIT pré-remplir `taux_horaire_effectif` avec
   `employee.taux_horaire_base`, `taux_vacances` avec
   `employee.taux_indemnite_vacances`, `montant_total_TP1015_3_effectif`
   avec `employee.montant_total_TP1015_3`,
   `exoneration_TP1015_3_effectif` avec `employee.exoneration_TP1015_3`,
   `retenue_additionnelle_QC_effective` avec
   `employee.retenue_additionnelle_QC`, `montant_total_TD1_effectif` avec
   `employee.montant_total_TD1`, `exoneration_TD1_effective` avec
   `employee.exoneration_TD1`, et
   `retenue_additionnelle_federale_effective` avec
   `employee.retenue_additionnelle_federale`.
2. L'Interface_Streamlit DOIT permettre à l'opérateur de modifier chacune
   des sept valeurs pré-remplies par l'AC1 avant l'assemblage de la paie,
   sans que cette modification n'altère la Fiche_Employe dans
   l'Annuaire_Employes.
3. TOUTE valeur monétaire pré-remplie ou modifiée par cet écran DOIT être
   représentée et transmise à `PayrollInput` comme `Decimal`, jamais comme
   `float` (règle 01).

---

### Requirement 9: Pré-remplissage des cumuls de début de paie

**User Story:** En tant qu'opérateur de paie, je veux que les cumuls YTD de
l'employé soient automatiquement récupérés, afin que la paie reflète l'état
réel des cumuls sans ressaisie manuelle.

#### Acceptance Criteria

1. QUAND un employé et une année fiscale sont déterminés (Requirements 4/5
   et 6), La Logique_Metier_App DOIT invoquer
   `lire_cumuls_ytd(employe_id, annee_fiscale, chemin_bd)` pour obtenir la
   valeur de `PayrollInput.cumuls_debut`.
2. L'Interface_Streamlit NE DOIT PAS permettre à l'opérateur de saisir
   manuellement les onze catégories monétaires de `cumuls_debut` — cette
   valeur est exclusivement dérivée de l'AC1.
3. LE `chemin_bd` utilisé par cet appel DOIT être le même chemin de
   registre maître que celui utilisé par les Requirements 13, 14 et 15 de
   cette spec (cohérence d'un seul registre par session).

---

### Requirement 10: Assemblage de la paie

**User Story:** En tant qu'opérateur de paie, je veux déclencher le calcul
complet d'une paie et en voir le détail avant de l'enregistrer, afin de
vérifier son exactitude.

#### Acceptance Criteria

1. QUAND l'opérateur déclenche l'assemblage, La Logique_Metier_App DOIT
   invoquer `assembler_paie(payroll_input, parametres_annee, id_paie,
   version, statut, date_creation, date_emission, remplace_par_id)` avec
   les valeurs issues des Requirements 6 à 9, `id_paie` généré selon la
   convention `PAIE-<employe_id>-<annee_fiscale>-<numero_periode zero-paddé
   sur 2 chiffres>-v<version>`, et `version = 1` pour toute nouvelle
   Paie_Logique (hors Action_Corriger, Requirement 13).
2. APRÈS un appel réussi à `assembler_paie`, L'Interface_Streamlit DOIT
   afficher la Paie_Assemblee complète : la décomposition des gains
   (`salaire_regulier`, `heures_supplementaires_montant`, `vacances`,
   `jours_feries_manuels`, `brut_total`), les sept retenues employé
   (`rrq`, `rqap`, `ae`, `impot_qc_formule`, `impot_qc_retenu`,
   `impot_federal_formule`, `impot_federal_retenu`) et leur total, les six
   cotisations employeur (`rrq_employeur`, `rqap_employeur`,
   `ae_employeur`, `fss`, `cnesst`, `cnt`) et leur total, `net`,
   `cout_employeur`, et `cumuls_fin`.
3. POUR CHAQUE montant individuel affiché par l'AC2 qui porte une
   `CalculationTrace` (chaque `MontantAvecTrace`), L'Interface_Streamlit
   DOIT permettre à l'opérateur de consulter cette trace (source, année,
   paramètres utilisés, entrées, sous-totaux, arrondissement, résultat)
   sans l'altérer ni la reformuler.
4. IF l'appel à `assembler_paie` lève `UnsupportedPayrollCase` ou
   `MissingParameterError`, THEN L'Interface_Streamlit DOIT afficher le
   message d'origine de l'exception à l'opérateur, sans l'intercepter par
   un bloc `except Exception` générique ni poursuivre l'affichage d'une
   Paie_Assemblee partielle.
5. L'Interface_Streamlit NE DOIT PAS enregistrer automatiquement la
   Paie_Assemblee dans le registre maître — l'Action_Enregistrer
   (Requirement 12) reste une étape distincte et explicite déclenchée par
   l'opérateur.

---

### Requirement 11: Modification des données fiscales TD1/TP-1015.3 d'une fiche employé

**User Story:** En tant qu'opérateur de paie, je veux mettre à jour les
montants TD1 et TP-1015.3 d'un employé déjà existant, afin de refléter un
changement de situation fiscale déclaré par l'employé sans devoir le faire
à chaque paie.

#### Acceptance Criteria

1. DEPUIS la Fiche_Employe_Detaillee (section informations employé,
   Requirement 5 AC1), L'Interface_Streamlit DOIT permettre de modifier
   `montant_total_TP1015_3`, `exoneration_TP1015_3`,
   `retenue_additionnelle_QC`, `montant_total_TD1`, `exoneration_TD1`,
   `retenue_additionnelle_federale` de la Fiche_Employe sélectionnée.
2. QUAND l'opérateur soumet cette modification, La Logique_Metier_App
   DOIT reconstruire une nouvelle instance `Employee` (immuable) avec les
   six valeurs mises à jour et tous les autres champs inchangés, puis
   l'enregistrer dans l'Annuaire_Employes via la fonction de mise à jour
   par `id` déjà prévue (Requirement 2 AC3).
3. CETTE modification NE DOIT PAS altérer rétroactivement une paie déjà
   assemblée ou insérée dans le registre maître — seules les paies
   futures verront les nouvelles valeurs pré-remplies (cohérent avec le
   Requirement 8, qui lit la Fiche_Employe au moment de la sélection de
   l'employé, pas au moment de sa création).
4. IF la reconstruction de l'`Employee` mis à jour lève
   `UnsupportedPayrollCase` ou une erreur de validation, THEN
   L'Interface_Streamlit DOIT afficher le message d'origine à l'opérateur
   sans l'intercepter silencieusement, et NE DOIT PAS persister la
   modification partielle dans l'Annuaire_Employes.

---

### Requirement 12: Enregistrement d'une paie (brouillon ou émise)

**User Story:** En tant qu'opérateur de paie, je veux choisir explicitement
d'enregistrer une paie assemblée en brouillon ou de l'émettre, afin de
distinguer une paie encore modifiable d'une paie définitive.

#### Acceptance Criteria

1. APRÈS l'affichage réussi d'une Paie_Assemblee (Requirement 10),
   L'Interface_Streamlit DOIT permettre à l'opérateur de choisir
   explicitement entre `StatutDePaie.BROUILLON` et `StatutDePaie.EMISE`
   avant de déclencher l'Action_Enregistrer.
2. L'Interface_Streamlit DOIT pré-remplir le champ `saison` transmis à
   `inserer_paie` avec la valeur `"Été <annee_fiscale>"`, modifiable par
   l'opérateur avant l'Action_Enregistrer.
3. QUAND l'opérateur déclenche l'Action_Enregistrer, La Logique_Metier_App
   DOIT invoquer `inserer_paie(resultat, saison, chemin_bd)` avec le statut
   choisi à l'AC1 et le `resultat` affiché au Requirement 10.
4. APRÈS un appel réussi à `inserer_paie`, L'Interface_Streamlit DOIT
   confirmer explicitement à l'opérateur l'identifiant `id_paie` inséré et
   le statut appliqué.
5. IF l'appel à `inserer_paie` lève `ValueError` (identifiant déjà présent),
   THEN L'Interface_Streamlit DOIT afficher le message d'origine de
   l'exception à l'opérateur sans l'intercepter silencieusement et sans
   modifier l'état de la Session_De_Saisie de façon à masquer l'échec.

---

### Requirement 13: Correction d'une paie émise (annulation-remplacement)

**User Story:** En tant qu'opérateur de paie, je veux corriger une paie déjà
émise sans la modifier directement, afin de préserver la piste d'audit
append-only du registre maître.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT permettre à l'opérateur de sélectionner une
   Paie_Logique déjà `EMISE` (via l'historique du Requirement 14) comme
   cible de l'Action_Corriger.
2. QUAND une paie cible est sélectionnée pour correction,
   L'Interface_Streamlit DOIT pré-remplir un nouveau Formulaire_Paie à
   partir des valeurs de la paie ciblée, modifiables par l'opérateur avant
   réassemblage.
3. QUAND l'opérateur déclenche l'Action_Corriger après réassemblage
   (Requirement 10), La Logique_Metier_App DOIT construire le nouveau
   `PayrollResult` avec `version = <version de la paie ciblée> + 1` et un
   `id_paie` regénéré selon la convention du Requirement 10 AC1 (incluant
   ce nouveau numéro de version), puis invoquer
   `remplacer_paie(ancien_id, nouveau_resultat, saison, chemin_bd)`.
4. APRÈS un appel réussi à `remplacer_paie`, L'Interface_Streamlit DOIT
   confirmer explicitement à l'opérateur l'ancien `id_paie` marqué
   `REMPLACE_PAR` et le nouvel `id_paie` inséré.
5. IF l'appel à `remplacer_paie` lève `KeyError` (paie ciblée absente) ou
   `ValueError` (statut de l'ancienne ou de la nouvelle paie non autorisé
   pour un remplacement), THEN L'Interface_Streamlit DOIT afficher le
   message d'origine de l'exception à l'opérateur sans l'intercepter
   silencieusement.

---

### Requirement 14: Consultation de l'historique d'une paie

**User Story:** En tant qu'opérateur de paie, je veux consulter toutes les
versions d'une Paie_Logique, afin de comprendre l'historique complet des
corrections apportées.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT permettre à l'opérateur de sélectionner un
   employé, une année fiscale et un numéro de période, puis d'invoquer
   `lire_historique_paie(employe_id, annee_fiscale, numero_periode,
   chemin_bd)` pour afficher toutes les versions correspondantes, ordonnées
   par `version` croissant.
2. QUAND `lire_historique_paie` retourne un tuple vide,
   L'Interface_Streamlit DOIT l'indiquer explicitement à l'opérateur
   (absence de paie pour cette Paie_Logique), sans lever d'exception ni
   afficher un état d'erreur.
3. POUR CHAQUE version affichée par l'AC1, L'Interface_Streamlit DOIT
   afficher au minimum `id_paie`, `version`, `statut`, `remplace_par_id`
   (le cas échéant), `date_creation`, `date_emission` (le cas échéant) et
   `net`.

---

### Requirement 15: Consultation des cumuls YTD d'un employé

**User Story:** En tant qu'opérateur de paie, je veux consulter les cumuls
YTD d'un employé pour une année civile donnée, afin de vérifier son état
cumulatif sans reconstruire l'historique complet de ses paies.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT permettre à l'opérateur de sélectionner un
   employé et une année civile, puis d'invoquer
   `lire_cumuls_ytd(employe_id, annee_civile, chemin_bd)` pour afficher les
   onze catégories monétaires du `CumulsYTD` retourné.
2. QUAND aucune ligne n'existe pour le couple `(employe_id, annee_civile)`
   sélectionné, L'Interface_Streamlit DOIT afficher les onze catégories à
   `Decimal("0.00")` (comportement déjà porté par `lire_cumuls_ytd`, sans
   traitement particulier ni exception dans l'interface).

---

### Requirement 16: Gestion des erreurs — disjonction stricte

**User Story:** En tant que responsable de la conformité, je veux que toute
erreur métier ou de registre reste visible et non altérée par l'interface,
afin de préserver le principe fail-fast de la règle 03 jusqu'à l'opérateur.

#### Acceptance Criteria

1. L'Interface_Streamlit NE DOIT JAMAIS intercepter `UnsupportedPayrollCase`,
   `MissingParameterError`, `ValueError` ou `KeyError` par un bloc `except
   Exception` ou `except BaseException` générique qui masquerait le type ou
   le message d'origine.
2. POUR CHAQUE point d'appel au moteur ou au registre identifié par les
   Requirements 4 à 15 (construction de modèles, `assembler_paie`,
   `inserer_paie`, `remplacer_paie`, `lire_paie`, `lire_historique_paie`,
   `lire_cumuls_ytd`), L'Interface_Streamlit DOIT capturer distinctement au
   moins les types `UnsupportedPayrollCase`, `MissingParameterError`,
   `ValueError` et `KeyError`, et afficher pour chacun un message qui
   inclut le message d'origine de l'exception sans le paraphraser ni le
   tronquer.
3. UNE exception non prévue par l'AC2 (ni interceptée, ni du domaine) NE
   DOIT PAS être masquée par l'Interface_Streamlit — son affichage complet
   (type et message) reste préférable à une interruption silencieuse de
   l'application.
4. L'affichage d'une erreur par cette Interface_Streamlit NE DOIT PAS
   entraîner la perte des valeurs déjà saisies par l'opérateur dans le
   Formulaire_Paie en cours.

---

### Requirement 17: Absence de génération PDF (hors scope)

**User Story:** En tant que responsable du projet, je veux que l'interface
livrée à cette étape ne tente pas de générer de bulletin PDF, afin de
respecter l'inversion des étapes 7 et 8 actée pour ce projet.

#### Acceptance Criteria

1. L'Interface_Streamlit NE DOIT PAS générer, ni proposer de générer, un
   bulletin PDF pour une Paie_Assemblee ou une paie déjà enregistrée.
2. WHERE l'Interface_Streamlit affiche une Paie_Assemblee ou une paie
   déjà enregistrée (Requirements 10, 14), L'Interface_Streamlit PEUT
   indiquer que la génération du bulletin PDF sera disponible dans une
   itération future (`bulletin-pdf`, étape 8), sans qu'un contrôle
   fonctionnel de génération PDF ne soit présent dans cette version.
3. `app/main.py` NE DOIT PAS importer ni référencer un module
   `payroll_engine/paystub.py`, qui n'existe pas encore à cette étape.

---

### Requirement 18: Non-modification du moteur de paie

**User Story:** En tant que responsable de la cohérence du projet, je veux
que l'interface consomme le moteur existant sans le modifier, afin de
préserver l'intégrité des contrats déjà figés et testés par les six specs
antérieures.

#### Acceptance Criteria

1. CETTE spec NE DOIT PAS modifier un fichier existant sous
   `payroll_engine/` ou `models/`.
2. TOUTE nouvelle fonction requise par l'Interface_Streamlit qui n'est pas
   déjà exposée par `payroll_engine/` ou `models/` (notamment
   l'Annuaire_Employes, Requirement 2, la fonction de dernière année de
   paie du Requirement 4 AC3, et l'Annuaire_Coordonnees, Requirement 20)
   DOIT être implémentée exclusivement sous `app/`.
3. L'Interface_Streamlit DOIT invoquer `assembler_paie`, `inserer_paie`,
   `lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd` et
   `remplacer_paie` avec leurs signatures exactes déjà figées — aucun
   argument positionnel ni nommé supplémentaire, aucune substitution par
   une réimplémentation locale.
4. L'Annuaire_Coordonnees et son contenu (toute Fiche_Coordonnees) NE
   DOIVENT jamais être lus par `payroll_engine/` ni par `models/`, ni être
   passés en argument à une fonction de ces deux packages — y compris
   indirectement via un objet construit à partir d'une Fiche_Coordonnees.

---

### Requirement 19: Données sensibles et exécution locale

**User Story:** En tant que responsable de la conformité, je veux que
l'interface et ses tests ne traitent jamais de données personnelles réelles,
afin de respecter la règle 04 sur toute la durée du projet.

#### Acceptance Criteria

1. TOUT exemple, fixture de test ou capture d'écran documentée pour cette
   spec DOIT utiliser exclusivement des identifiants fictifs (`EMP0XX`) et
   des libellés anonymisés, jamais un nom complet réel ni un NAS.
2. LE Chemin_Annuaire par défaut et le `chemin_bd` par défaut utilisés par
   l'Interface_Streamlit en production DOIVENT résider hors du dépôt
   versionné (cohérent avec `chemin_bd_production`).
3. LES tests de l'Interface_Streamlit et de la Logique_Metier_App DOIVENT
   utiliser exclusivement un Chemin_Annuaire et un `chemin_bd` temporaires
   ou en mémoire, injectés explicitement — jamais le chemin de production
   par défaut.
4. MÊME si l'Annuaire_Coordonnees (Requirement 20) est explicitement
   destiné à contenir des coordonnées réelles en production (NAS, adresse
   résidentielle, courriel, téléphone), AUCUNE valeur réelle de ces champs
   ne DOIT jamais apparaître dans les tests, les fixtures, la
   documentation ou tout exemple versionné de cette spec — seules des
   valeurs manifestement fictives (ex. numéro de téléphone `"555-0100"`,
   courriel `"test@example.invalid"`) sont utilisées à ces fins.

---

### Requirement 20: Fiche de coordonnées opérationnelles (hors contrat de calcul)

**User Story:** En tant qu'opérateur de paie, je veux conserver les
coordonnées réelles d'un employé (NAS, adresse, courriel, téléphone) pour
un usage opérationnel de contact, sans que ces données ne transitent
jamais par le moteur de calcul ni par aucun fichier versionné.

#### Acceptance Criteria

1. L'Interface_Streamlit DOIT exposer une fonction de la
   Logique_Metier_App qui enregistre une Fiche_Coordonnees (création ou
   mise à jour par `employe_id`) dans l'Annuaire_Coordonnees, à un
   Chemin_Coordonnees injectable dont la valeur par défaut réside hors du
   dépôt versionné.
2. L'Interface_Streamlit DOIT exposer une fonction de la
   Logique_Metier_App qui lit une Fiche_Coordonnees par `employe_id`,
   retournant une valeur vide/None explicite (pas d'exception) si aucune
   coordonnée n'a été saisie pour cet employé.
3. LA Fiche_Coordonnees NE DOIT JAMAIS être transmise à `assembler_paie`,
   `PayrollInput`, `Employee`, ni à aucune fonction de `payroll_engine/`
   — aucun champ de coordonnées ne doit apparaître dans un
   `CalculationTrace` ni dans le `payload_json` du registre maître
   (`register.py`).
4. LA Fiche_Employe_Detaillee (Requirement 5 AC1) DOIT afficher la
   Fiche_Coordonnees de l'employé courant dans sa section dédiée, mais
   cette section DOIT rester visuellement et fonctionnellement distincte
   du Formulaire_Paie et du formulaire de création de Fiche_Employe.
5. TOUTE écriture dans l'Annuaire_Coordonnees DOIT être atomique, selon le
   même patron que l'Annuaire_Employes (Requirement 2 AC6).
6. LE Chemin_Coordonnees par défaut en production DOIT résider hors du
   dépôt versionné, au même titre que le Chemin_Annuaire et le
   `chemin_bd` de production (règle 04) ; les tests DOIVENT utiliser
   exclusivement un Chemin_Coordonnees temporaire injecté explicitement,
   jamais le chemin de production par défaut, ni de valeur réelle (règle
   04, tous les exemples de test utilisent des identifiants fictifs et
   des coordonnées manifestement fictives, ex. `"555-0100"`,
   `"test@example.invalid"`).
7. SI l'Annuaire_Coordonnees n'existe pas encore au Chemin_Coordonnees
   fourni, ALORS la fonction de lecture DOIT se comporter comme si aucune
   Fiche_Coordonnees n'existait pour aucun employé, sans lever
   d'exception.
