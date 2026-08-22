# Design Document

## Overview

Cette fonctionnalité modifie trois surfaces déjà existantes :

1. `app/pages_ui/tableau_de_bord.py` — le Selecteur_De_Periode, jusqu'ici
   propre à la section « Bilan fiscal » et offrant des options
   Mois_Fiscal + Annee_Complete, devient un **sélecteur global** (années
   uniquement) positionné au niveau du titre de page, piloté par un
   `st.session_state` unique et consommé par les deux sections
   (« Employés » et « Bilan fiscal »).
2. La section « Employés » de cette même page reçoit trois ajustements
   ciblés : retrait de la colonne « No. d'employé », tri des lignes par
   Prénom Nom (via `FicheCoordonnees`), renommage de la colonne
   « Dernière paie » en « Paies » avec un contenu enrichi (toutes les
   Paie_Brouillon/Paie_Emise de l'année sélectionnée, pas seulement la
   dernière).
3. `app/pages_ui/formulaire_paie.py::_section_enregistrement` reçoit une
   validation bloquante de la date de paiement au moment de l'émission
   (statut choisi `EMISE`).

Aucun nouveau modèle Pydantic, aucune nouvelle table SQL, aucune
nouvelle route. L'essentiel du travail est : (a) deux nouvelles
fonctions pures dans `bilan_fiscal.py` (extension, pas duplication),
(b) une nouvelle fonction pure dans `dernieres_paies.py`, (c) un nouveau
petit module de tri pur `app/logique_metier/tri_employes.py`, (d) deux
nouvelles fonctions pures dans `app/logique_metier/formulaire_paie.py`,
et (e) la réorganisation du rendu de `tableau_de_bord.py` autour d'un
état partagé.

## Architecture

### Décision 1 — Extension de `bilan_fiscal.py`, jamais de duplication

Le module `bilan_fiscal.py` gagne deux fonctions nouvelles et **aucune
fonction existante n'est supprimée ni modifiée** :

- `construire_options_annee(paies_emises, annee_courante)` — remplace,
  côté appelant (`tableau_de_bord.py`), l'usage de
  `construire_options_periode` : ne produit que des options
  Annee_Complete (`OptionPeriode.periode.mois` toujours `None`), et
  garantit que `annee_courante` y figure toujours (réelle si
  Annee_Avec_Paie_Emise, sinon Option_Annee_Courante_De_Repli).
- `determiner_annee_par_defaut(annee_courante)` — remplace, côté
  appelant, l'usage de `determiner_periode_par_defaut` : la présélection
  par défaut n'a plus besoin de logique de « jour du mois » (spécifique
  aux Mois_Fiscal, Requirements 3.1-3.3 de la spec
  `bilan-fiscal-employeur`) — elle est triviale, l'année courante étant
  par construction toujours une option valide.

Les fonctions déjà existantes sont **réutilisées sans modification** :
`resoudre_periode_a_afficher` (générique sur tout `OptionPeriode`/
`PeriodeFiscale`, ne dépend d'aucune logique Mois_Fiscal),
`filtrer_paies_par_periode` (gère déjà le cas `periode.mois is None`),
`construire_tableau_bilan_fiscal`, `lire_paies_emises`,
`mois_annee_rattachement`, `formater_option_annee_complete`.

**Sort du support Mois_Fiscal existant** : `PeriodeFiscale.mois`,
`construire_options_periode`, `determiner_periode_par_defaut`,
`formater_option_mois_fiscal` restent dans le module, inchangés — ils
ne sont simplement **plus jamais appelés** par `tableau_de_bord.py`
après cette fonctionnalité. Ce choix (extension inerte plutôt que
suppression) évite de casser la suite de tests déjà existante et
volumineuse de la spec `bilan-fiscal-employeur` (`tests/app/
logique_metier/test_bilan_fiscal.py`), qui exerce spécifiquement ces
fonctions Mois_Fiscal — les supprimer sortirait du périmètre de cette
fonctionnalité (qui porte sur le comportement du Tableau_De_Bord, pas
sur une refonte de `bilan_fiscal.py`). Une tâche de nettoyage future
pourra retirer ce code mort une fois confirmé qu'aucun autre appelant
n'en dépend.

### Décision 2 — Sélecteur global en `st.session_state`, résolu une seule fois

`render()` résout la Periode_Fiscale sélectionnée **une seule fois**,
en haut de la fonction, avant le rendu de la section « Employés » :

```
paies_emises = executer_avec_capture(lire_paies_emises)
# ... gestion d'erreur (Décision 4) ...
options = construire_options_annee(paies_emises, date.today().year)
periode_par_defaut = determiner_annee_par_defaut(date.today().year)
libelle_resolu = resoudre_periode_a_afficher(...)
st.session_state[_CLE_ANNEE_SELECTIONNEE_LIBELLE] = libelle_resolu
# st.selectbox(..., key=_CLE_ANNEE_SELECTIONNEE_LIBELLE) — rendu au
# niveau du titre de page (Requirement 1.6)
periode_selectionnee = next(o.periode for o in options if o.libelle == libelle_choisi)
```

`periode_selectionnee.annee` (un simple `int`, puisque `mois` est
toujours `None` pour ces options) est ensuite transmis **explicitement
en paramètre** à `_afficher_liste_employes(employes, annee_selectionnee=...)`
et à `_afficher_bilan_fiscal(paies_emises, periode_selectionnee=...)` —
ni l'une ni l'autre ne relit `st.session_state` elle-même. Ce choix
garde ces deux fonctions de rendu testables indépendamment de l'état
Streamlit global et élimine toute ambiguïté sur « qui a résolu la
période en premier ».

La clé de session est renommée `_CLE_ANNEE_SELECTIONNEE_LIBELLE`
(`"tdb_annee_selectionnee_libelle"`) — l'ancienne clé
`bilan_fiscal_periode_libelle`, propre à la section Bilan fiscal, est
retirée puisque le sélecteur n'est plus local à cette section
(Requirement 1.7).

### Décision 3 — Retrait de l'early-return « Aucune paie émise »

Le code actuel de `_afficher_bilan_fiscal` retourne tôt avec
`st.info("Aucune paie émise n'a été trouvée.")` quand `lire_paies_emises`
retourne un tuple vide, sans jamais afficher de sélecteur ni de
Tableau_Bilan_Fiscal. Ce comportement est **incompatible avec le
Requirement 2.2** : même en l'absence totale de Paie_Emise, l'Option_
Annee_Courante_De_Repli doit permettre d'afficher un Tableau_Bilan_Fiscal
intégralement à zéro (jamais l'indicateur d'indisponibilité pour ce
cas). Puisque `construire_options_annee` garantit **toujours** au moins
une option (l'année courante, réelle ou de repli), ce early-return
disparaît : le sélecteur et le Tableau_Bilan_Fiscal sont désormais
**toujours** rendus, quel que soit le contenu de `paies_emises`.

### Décision 4 — Erreur de lecture globale (`lire_paies_emises`)

Si `executer_avec_capture(lire_paies_emises)` retourne une
`ErreurDomaineAffichable`, le sélecteur global ne peut pas être
construit à partir de vraies données. Décision : afficher le message
d'erreur **à l'emplacement du sélecteur** (à droite du titre), tout en
laissant le reste de la page fonctionner avec une valeur de repli
purement locale (`annee_selectionnee = date.today().year`, sans aucune
option affichée) :

- la section « Employés » filtre la Colonne_Paies sur l'année courante
  (comportement dégradé mais jamais bloquant) ;
- la section « Bilan fiscal » n'est pas rendue (aucune donnée fiable —
  message d'erreur déjà visible en haut de page, pas de duplication du
  message).

Ce choix garde une seule source de vérité pour l'erreur (affichée une
fois, au même endroit que le sélecteur qu'elle remplace) sans jamais
interrompre le rendu de la page (cohérent avec la discipline de
disjonction stricte déjà en place ailleurs sur cette page).

### Décision 5 — Isolation de la construction du Tableau_Bilan_Fiscal (Requirement 2.3)

`filtrer_paies_par_periode` et `construire_tableau_bilan_fiscal` sont
des fonctions pures totales (jamais d'exception, cf. docstrings de
`bilan_fiscal.py`) — le seul risque réaliste couvert par le Requirement
2.3 est une régression future dans ces fonctions ou dans la
construction du HTML. Décision : envelopper l'ensemble « filtrage +
construction + génération HTML » de `_afficher_bilan_fiscal` dans un
seul `executer_avec_capture(lambda: ...)`, retournant le HTML complet
prêt à injecter ; toute `ErreurDomaineAffichable` retournée est
affichée via `st.error(...)` à la place du tableau, sans empêcher le
reste de `render()` de s'exécuter (la section « Employés », déjà rendue
plus haut, n'est de toute façon jamais affectée).

### Décision 6 — Nouveau module `app/logique_metier/tri_employes.py`

Le tri par Prénom Nom nécessite de combiner un `Employee` (`id`,
`nom_affichage`) et une `FicheCoordonnees | None` (`prenom`, `nom`).
Plutôt que de coupler `annuaire_employes.py` (qui ne connaît aujourd'hui
que `Employee`) à `FicheCoordonnees`, ou d'alourdir
`annuaire_coordonnees.py` (dédié au cycle CRUD des coordonnées), cette
fonctionnalité introduit un nouveau module **dédié à une seule
responsabilité** — le tri d'affichage — cohérent avec le découpage déjà
en place (`bilan_fiscal.py`, `dernieres_paies.py`, `erreurs.py` sont
chacun mono-responsabilité). Ce module importe `Employee` et
`FicheCoordonnees` (import autorisé, sens unique) mais n'est importé par
aucun des deux modules CRUD en retour.

### Décision 7 — Extension de `dernieres_paies.py` avec `paies_pour_colonne`

La Colonne_Paies réutilise **le même appel** `lire_resumes_paies(employe_id)`
déjà effectué par `_afficher_liste_employes` (aucun appel SQL
supplémentaire) — seule une nouvelle fonction pure de filtrage/tri,
`paies_pour_colonne(resumes, annee)`, est ajoutée à `dernieres_paies.py`
pour transformer les résumés déjà lus en la liste ordonnée attendue par
le Requirement 5. `derniere_paie_creee` (utilisée par l'ancienne
colonne « Dernière paie ») n'est plus appelée par `tableau_de_bord.py`
mais reste dans le module, inchangée (même logique d'extension inerte
que la Décision 1 — elle n'a aucune raison d'être supprimée, rien
n'indique qu'elle soit sans autre appelant potentiel).

### Décision 8 — Validation de la date de paiement lue depuis les widgets vifs, jamais depuis `paie_assemblee`

`_section_enregistrement` reçoit aujourd'hui `paie_assemblee`, un
`PayrollResult` **figé** au moment du dernier clic sur « Assembler la
paie ». Entre ce clic et le clic sur « Enregistrer la paie », l'opérateur
peut modifier les widgets `date_fin`/`date_paiement` de
`_section_nouvelle_paie` sans ré-assembler — `paie_assemblee.pay_period.
date_paiement` serait alors une valeur **obsolète**. Décision :
`_section_enregistrement` reçoit deux nouveaux paramètres explicites,
`date_fin: date` et `date_paiement: date | None`, correspondant aux
valeurs **vives** des widgets au moment du rendu courant — jamais lues
depuis `paie_assemblee`. Cela nécessite de propager ces deux valeurs
depuis `_section_nouvelle_paie` (où elles existent déjà comme variables
locales) jusqu'à l'appel de `_section_enregistrement`.

Portée volontairement limitée à `_section_enregistrement`/« Nouvelle
paie » (Glossary : le Bouton_Emission est explicitement celui de cette
fonction) — le flux « Corriger une paie émise » (`_section_corriger_paie`,
bouton distinct « Corriger cette paie ») n'est pas dans le périmètre de
ce Requirement 6.

### Décision 9 — Retrait de la colonne « No. d'employé »

Simple retrait du `<th>No. d'employé</th>` et du `<td>{employe.id}</td>`
correspondant dans le gabarit HTML de `_afficher_liste_employes` —
aucune fonction pure nouvelle nécessaire. `employe.id` continue
d'alimenter les attributs `href` des liens de la ligne (navigation),
jamais affiché comme texte visible (Requirement 3.2, déjà garanti :
aucun `href` n'est un contenu textuel rendu par le navigateur).

### Décision 10 — Aucun nouveau bouton (Règle UI 07)

Cette fonctionnalité ne introduit aucun nouveau `st.button`/
`st.form_submit_button`. Le Bouton_Emission (« Enregistrer la paie »,
déjà `type="primary"`) est réutilisé tel quel ; seule sa logique
interne gagne une vérification bloquante supplémentaire. La Règle 07
n'est donc pas impactée.

## Components and Interfaces

### 1. `app/logique_metier/bilan_fiscal.py` (extension)

```python
def construire_options_annee(
    paies_emises: tuple[PayrollResult, ...],
    annee_courante: int,
) -> tuple[OptionPeriode, ...]:
    """Options Annee_Complete du Selecteur_De_Periode_Global (Req 1.1-1.3).

    Détermine l'ensemble des années de rattachement (`mois_annee_
    rattachement(...)[0]`) présentes dans ``paies_emises``, y ajoute
    ``annee_courante`` si absente (Option_Annee_Courante_De_Repli),
    formate chaque année via `formater_option_annee_complete`, puis
    trie par année décroissante. Jamais d'option de type Mois_Fiscal
    (``periode.mois`` toujours `None`). ``annee_courante`` figure
    toujours exactement une fois dans le résultat (Req 1.2, 1.3 —
    jamais de doublon si elle est déjà une Annee_Avec_Paie_Emise).
    """


def determiner_annee_par_defaut(annee_courante: int) -> PeriodeFiscale:
    """Annee_Complete présélectionnée par défaut (Req 1.4, 1.5).

    Toujours ``PeriodeFiscale(annee=annee_courante, mois=None)`` —
    triviale par construction : `construire_options_annee` garantit que
    cette période correspond toujours à une option (réelle ou de
    repli), il n'existe donc aucune branche de repli supplémentaire à
    gérer ici (contrairement à `determiner_periode_par_defaut`, dont la
    logique de « jour du mois » ne s'applique qu'aux Mois_Fiscal).
    """
```

Fonctions réutilisées sans modification : `resoudre_periode_a_afficher`,
`filtrer_paies_par_periode`, `construire_tableau_bilan_fiscal`,
`lire_paies_emises`, `mois_annee_rattachement`,
`formater_option_annee_complete`.

### 2. `app/logique_metier/dernieres_paies.py` (extension)

```python
def paies_pour_colonne(
    resumes: tuple[LignePaieResume, ...],
    annee: int,
) -> tuple[LignePaieResume, ...]:
    """Sous-ensemble ordonné pour la Colonne_Paies (Req 5.2, 5.3, 5.4).

    Filtre ``resumes`` sur ``statut ∈ {BROUILLON, EMISE}`` (valeurs
    `StatutDePaie.BROUILLON.value`/`StatutDePaie.EMISE.value`) ET
    ``date.fromisoformat(date_paiement).year == annee`` (un résumé sans
    ``date_paiement`` — cas défensif jamais atteint en pratique, voir
    docstring de `LignePaieResume` — est exclu du résultat plutôt que de
    lever une exception). Trie le résultat en plaçant d'abord tous les
    résumés `BROUILLON` puis tous les `EMISE` ; à l'intérieur de chaque
    groupe, tri par date de paiement décroissante puis
    `numero_periode` croissant en cas d'égalité. Fonction pure, sans
    accès disque.
    """
```

### 3. `app/logique_metier/tri_employes.py` (nouveau module)

```python
def cle_tri_employe(
    employe: Employee, fiche: FicheCoordonnees | None
) -> str:
    """Clé de tri brute d'une ligne du tableau des employés (Req 4.1, 4.2).

    Si ``fiche`` n'est pas `None` : `f"{fiche.prenom or ''} {fiche.nom or
    ''}"`. Sinon : `employe.nom_affichage`. Fonction pure — aucune
    normalisation appliquée ici (voir `normaliser_pour_tri`).
    """


def normaliser_pour_tri(chaine: str) -> str:
    """Forme canonique insensible à la casse et aux accents (Req 4.3).

    Décomposition Unicode NFKD, suppression des marques de combinaison
    (accents, cédille), puis `casefold()` — même technique que
    `models._validators._normaliser_pour_recherche`, sans la
    suppression de la ponctuation/espaces (celle-ci doit rester
    significative pour l'ordre alphabétique d'un nom complet).
    """


def trier_employes_pour_affichage(
    employes: tuple[Employee, ...],
    fiches: dict[str, FicheCoordonnees],
) -> tuple[Employee, ...]:
    """Ordre d'affichage du tableau des employés (Req 4.1-4.3).

    Trie ``employes`` par `normaliser_pour_tri(cle_tri_employe(employe,
    fiches.get(employe.id)))` croissant, `employe.id` croissant comme
    critère de départage. Fonction pure — ``fiches`` est un dict déjà
    construit par l'appelant (un appel `lire_coordonnees` par employé,
    dans `tableau_de_bord.py`), jamais lu depuis le disque ici.
    """
```

### 4. `app/logique_metier/formulaire_paie.py` (extension)

```python
def valider_date_paiement_pour_emission(
    date_paiement: date | None, date_fin: date
) -> str | None:
    """Message de blocage, ou `None` si la date de paiement est valide
    pour une émission (Req 6.1, 6.3).

    Retourne un message d'erreur explicite si ``date_paiement`` est
    `None` ou strictement antérieure à ``date_fin`` ; retourne `None`
    dans tous les autres cas (date présente et `>= date_fin`). Fonction
    pure, aucun accès disque, aucune exception levée.
    """


def message_erreur_date_paiement(
    statut_choisi: str,
    date_paiement: date | None,
    date_fin: date,
    message_precedent: str | None,
) -> str | None:
    """Orchestration pure du message affiché par `_section_enregistrement`
    (Req 6.2, 6.4).

    Si ``statut_choisi != "EMISE"`` (BROUILLON) : retourne
    ``message_precedent`` **inchangé**, sans jamais appeler
    `valider_date_paiement_pour_emission` — la validation propre à
    l'émission ne s'applique pas, et un message déjà affiché n'est
    jamais effacé (Req 6.4). Si ``statut_choisi == "EMISE"`` : retourne
    `valider_date_paiement_pour_emission(date_paiement, date_fin)`,
    recalculé à chaque appel, sans jamais tenir compte de
    ``message_precedent`` (Req 6.2 — la validation est réévaluée avant
    toute tentative d'insertion).
    """
```

### 5. `app/pages_ui/tableau_de_bord.py` (restructuration)

```python
def render() -> None:
    """Résout la Periode_Fiscale globale une seule fois (haut de
    fonction), l'affiche au niveau du titre (Req 1.6), puis délègue aux
    deux sections avec cette valeur déjà résolue en paramètre explicite
    (Req 1.7, Décision 2)."""


def _resoudre_annee_selectionnee() -> tuple[
    tuple[PayrollResult, ...] | None, int
]:
    """Lecture + résolution du sélecteur global (Décision 2, 4).

    Retourne ``(paies_emises, annee_selectionnee)`` en cas de succès de
    `lire_paies_emises`, ou ``(None, date.today().year)`` si la lecture
    échoue — `None` signale à l'appelant de ne pas rendre la section
    Bilan fiscal (Décision 4). Affiche elle-même le `st.selectbox` (ou
    le message d'erreur de repli) au niveau du titre de page.
    """


def _afficher_liste_employes(
    employes: tuple[Employee, ...], *, annee_selectionnee: int
) -> None:
    """Tri par Prénom Nom (Req 4), retrait de « No. d'employé » (Req 3),
    Colonne_Paies enrichie (Req 5) — signature étendue d'un paramètre
    ``annee_selectionnee`` obligatoire (mot-clé)."""


def _afficher_bilan_fiscal(
    paies_emises: tuple[PayrollResult, ...],
    periode_selectionnee: PeriodeFiscale,
) -> None:
    """Ne construit plus son propre sélecteur (Décision 2) — reçoit la
    période déjà résolue ; ne fait plus d'early-return sur tuple vide
    (Décision 3) ; isole la construction du tableau (Décision 5)."""
```

### 6. `app/pages_ui/formulaire_paie.py` (modification ciblée)

```python
def _section_enregistrement(
    paie_assemblee: PayrollResult,
    annee_fiscale: int,
    *,
    date_fin: date,
    date_paiement: date | None,
    cle_prefixe: str,
) -> None:
    """Deux nouveaux paramètres mot-clé obligatoires (Décision 8).
    Calcule/affiche/persiste le message de validation à chaque rendu
    (Req 6.2, 6.4) ; bloque avant `_inserer()` si `statut_choisi ==
    "EMISE"` et que le message n'est pas `None` (Req 6.1, 6.3)."""
```

Site d'appel modifié dans `_section_nouvelle_paie` :
`_section_enregistrement(paie_assemblee, annee_fiscale, date_fin=date_fin, date_paiement=date_paiement, cle_prefixe="fp_nouvelle")`.

## Data Models

Aucun nouveau modèle Pydantic. Réutilisation stricte de :

- `PeriodeFiscale`, `OptionPeriode`, `TableauBilanFiscal`, `LigneBilan`
  (`bilan_fiscal.py`) — `PeriodeFiscale.mois` reste défini dans le
  modèle (compatibilité, Décision 1) mais n'est plus jamais construit à
  une valeur non-`None` par le nouveau code appelant de
  `tableau_de_bord.py`.
- `LignePaieResume` (`dernieres_paies.py`) — champ `date_paiement: str |
  None` déjà présent, réutilisé par `paies_pour_colonne` via
  `date.fromisoformat(...)`.
- `FicheCoordonnees` (`annuaire_coordonnees.py`) — champs `prenom`,
  `nom` déjà présents, aucune modification.
- `Employee` (`models/employee.py`) — champs `id`, `nom_affichage` déjà
  présents, aucune modification.

## Error Handling

| Point de lecture | Mécanisme | Comportement en cas d'échec |
|---|---|---|
| `lire_paies_emises` (sélecteur global) | `executer_avec_capture` | Message d'erreur affiché à l'emplacement du sélecteur ; reste de la page rendu avec repli sur l'année courante (Décision 4) |
| `lister_employes` | `executer_avec_capture` (inchangé) | Message d'erreur, page interrompue (comportement déjà existant, hors périmètre de cette fonctionnalité) |
| `lire_resumes_paies` par employé | `executer_avec_capture` (inchangé, réutilisé pour la Colonne_Paies) | Texte d'erreur dans la cellule Colonne_Paies de cet employé uniquement (Req 5.5) ; les autres lignes ne sont pas affectées |
| Construction + rendu HTML du Tableau_Bilan_Fiscal | `executer_avec_capture` (nouveau point d'enveloppe, Décision 5) | Message d'erreur à la place du tableau (Req 2.3), reste de la page inchangé |
| `lire_coordonnees` par employé (tri) | Aucun — appel direct | Aucun Requirement ne spécifie de comportement de repli explicite pour cet appel ; une exception de lecture (cas hors périmètre, fichier corrompu) se propage sans interception, cohérent avec la règle 03 (fail-fast sur un état inattendu plutôt que masquer silencieusement) |
| Validation de la date de paiement à l'émission | Pure (`valider_date_paiement_pour_emission`), pas d'exception | Message bloquant `st.error(...)`, aucune tentative d'insertion (Req 6.1) |

## Correctness Properties

*Une propriété est une caractéristique ou un comportement qui doit
demeurer vrai pour toutes les exécutions valides d'un système —
essentiellement, un énoncé formel de ce que le système doit faire. Les
propriétés font le pont entre les spécifications lisibles par un humain
et des garanties de correction vérifiables par une machine.*

### Property 1: Options d'année exactes et sans doublon

*Pour tout* tuple de `PayrollResult` `EMISE` et *toute* année courante,
l'ensemble des années produites par `construire_options_annee` est
exactement l'union des années de rattachement présentes dans les paies
et de l'année courante, chacune apparaissant exactement une fois,
triées par année décroissante, et aucune option ne porte de
`periode.mois` non `None`.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 2: Présélection par défaut toujours disponible

*Pour toute* année courante et *tout* tuple de `PayrollResult` `EMISE`,
`determiner_annee_par_defaut(annee_courante)` retourne
`PeriodeFiscale(annee=annee_courante, mois=None)`, et cette période
correspond toujours à une option de
`construire_options_annee(paies_emises, annee_courante)`.

**Validates: Requirements 1.4, 1.5**

### Property 3: Colonne « No. d'employé » absente, colonnes restantes inchangées

*Pour tout* tuple non vide d'employés (identifiants et noms
arbitraires), le HTML produit par le rendu du tableau des employés ne
contient jamais `<th>No. d'employé</th>` ni de cellule `<td>{employe.id}</td>`
répétée par ligne, et l'ensemble ordonné des autres en-têtes de colonnes
(« Prénom et nom », « Paies », « Actions ») reste inchangé.

**Validates: Requirements 3.1**

### Property 4: Identifiant employé jamais affiché comme texte visible

*Pour tout* employé (identifiant arbitraire, y compris des valeurs
contenant des caractères spéciaux d'URL), le texte visible du tableau
rendu (contenu hors des balises et des attributs HTML) ne contient
jamais `employe.id`, alors que ce même identifiant continue d'apparaître
dans au moins un attribut `href`.

**Validates: Requirements 3.2**

### Property 5: Tri par Prénom Nom, insensible casse/accents, départagé par id

*Pour tout* tuple d'employés et *tout* dictionnaire partiel de
`FicheCoordonnees` associées (certains employés sans fiche), le résultat
de `trier_employes_pour_affichage` est trié par ordre croissant de
`normaliser_pour_tri(cle_tri_employe(...))`, et pour toute paire
d'employés dont cette clé normalisée est identique, l'ordre relatif
suit `Employee.id` croissant.

**Validates: Requirements 4.1, 4.2, 4.3**

### Property 6: Filtrage et ordre exacts de la Colonne_Paies

*Pour tout* tuple de `LignePaieResume` (statuts, dates de paiement et
numéros de période arbitraires) et *toute* année, le résultat de
`paies_pour_colonne(resumes, annee)` contient exactement les résumés de
statut `BROUILLON`/`EMISE` dont l'année de `date_paiement` correspond
(aucun résumé d'une autre année, aucun résumé d'un autre statut), tous
les `BROUILLON` précédant tous les `EMISE`, chaque groupe étant trié par
date de paiement décroissante puis `numero_periode` croissant en cas
d'égalité.

**Validates: Requirements 5.2, 5.3, 5.4**

### Property 7: Absence de paie jamais confondue avec une erreur de lecture

*Pour tout* tuple de `LignePaieResume` (y compris vide) et *toute*
année, si la lecture réussit (le résultat est un tuple, jamais une
`ErreurDomaineAffichable`), le texte rendu de la Colonne_Paies pour cet
employé n'est jamais le texte d'erreur — y compris quand
`paies_pour_colonne(resumes, annee)` est vide.

**Validates: Requirements 5.6**

### Property 8: Isolation des erreurs de lecture par employé

*Pour tout* tuple d'employés et *tout* sous-ensemble arbitraire d'entre
eux dont la lecture des résumés de paie échoue (simulée par mock), les
employés dont la lecture réussit affichent toujours leur contenu normal
de Colonne_Paies, indépendamment des échecs des autres lignes.

**Validates: Requirements 5.5**

### Property 9: Validation de la date de paiement à l'émission

*Pour toute* `date_fin` et *toute* `date_paiement` (y compris absente),
`valider_date_paiement_pour_emission(date_paiement, date_fin)` retourne
un message non `None` si et seulement si `date_paiement` est absente ou
strictement antérieure à `date_fin`.

**Validates: Requirements 6.1, 6.3**

### Property 10: Non-application et non-effacement du message en BROUILLON

*Pour tout* `message_precedent` (y compris absent) et *toute*
combinaison arbitraire de `date_paiement`/`date_fin`, si
`statut_choisi` vaut `"BROUILLON"`, `message_erreur_date_paiement`
retourne exactement `message_precedent`, inchangé ; si `statut_choisi`
vaut `"EMISE"`, elle retourne exactement
`valider_date_paiement_pour_emission(date_paiement, date_fin)`,
indépendamment de `message_precedent`.

**Validates: Requirements 6.2, 6.4**

## Testing Strategy

**Tests unitaires** (exemples spécifiques, cohérents avec le patron déjà
établi par `tests/app/logique_metier/test_bilan_fiscal.py`) :

- Renommage du libellé de colonne (« Paies » plutôt que « Dernière
  paie ») — Requirement 5.1, non universel, un seul exemple suffit.
- Isolation d'erreur de construction du Tableau_Bilan_Fiscal (Req 2.3) —
  simulation d'une exception, vérification que la section Employés
  reste rendue.
- Cas `paies_emises = ()` combiné à l'Option_Annee_Courante_De_Repli
  (Req 2.2) — vérifie qu'aucune ligne/aucun total n'affiche
  l'indicateur d'indisponibilité.

**Tests property-based** (Hypothesis, ≥100 itérations, réutilisation des
stratégies existantes de `tests/app/strategies.py` — notamment
`st_payroll_result_arbitraire`, `st_employee_valide`,
`st_fiche_coordonnees_valide` — et de nouvelles stratégies dédiées pour
`LignePaieResume` et les dates du Formulaire_Paie). Chaque property test
référence la propriété correspondante ci-dessus via le tag
`Feature: tableau-de-bord-periode-globale, Property N: <titre>`.

Les dix propriétés listées dans la section « Correctness Properties »
ci-dessus couvrent l'ensemble des critères d'acceptation classés
« testable comme propriété » lors du pré-travail d'analyse. Les
critères 1.6, 1.7, 2.1 et 2.2 (comportement de câblage architectural ou
déjà couvert par les property tests existants de la spec
`bilan-fiscal-employeur`) ne font l'objet d'aucune nouvelle propriété,
pour éviter toute redondance.
