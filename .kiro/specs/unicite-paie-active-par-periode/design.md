# Unicité Paie Active Par Période — Bugfix Design

## Overview

Ce bugfix corrige deux défauts partageant le même périmètre technique (flux « Nouvelle paie » et son affichage dans le Tableau_De_Bord) :

- **Bug A** : `payroll_engine/register.py::inserer_paie` n'invalide jamais les lignes `BROUILLON` actives précédentes d'une même Paie_Logique `(employe_id, annee_fiscale, numero_periode)` — seul le doublon `EMISE`→`EMISE` est déjà refusé (garde-fou existant, non touché). Résultat : accumulation illimitée de lignes actives (`BROUILLON` et/ou `EMISE`) pour une même période.
- **Bug B** : `app/pages_ui/tableau_de_bord.py::_ligne_colonne_paie_html` affiche un libellé redondant (année systématiquement affichée, alors que la Colonne_Paies ne montre déjà que l'année sélectionnée) et incomplet (numéro de période jamais affiché).

**Stratégie de correction :**

- Bug A : ajouter, dans la même transaction atomique que l'insertion (`inserer_paie`), une étape qui détecte les lignes `BROUILLON` actives de la même Paie_Logique et les fait passer au statut `REMPLACE_PAR` — en reproduisant exactement le modèle de mutation déjà utilisé par `remplacer_paie` (mêmes colonnes mutées : `statut`, `remplace_par_id`, `payload_json`). Le garde-fou `EMISE`→`EMISE` existant (`ValueError`) reste inchangé et s'exécute avant cette nouvelle étape. Le flux « Corriger une paie émise » (`_section_corriger_paie`, `remplacer_paie`) reste hors périmètre.
- Bug B : remplacer le format du libellé par `"Paie #{numero_periode} - déposée le {date sans année}"` (EMISE) / `"Paie #{numero_periode} - brouillon"` (BROUILLON, jamais de date), via une nouvelle fonction de formatage de date sans année, cohérente en style avec `_formater_date_courte`/`_NOMS_MOIS_MINUSCULES`. Le filtrage, le tri et les `href` de `paies_pour_colonne` restent inchangés — seul le texte affiché change.

## Glossary

- **Bug_Condition (C)** : la condition qui déclenche chacun des deux défauts — voir `## Bug Details` pour les deux spécifications formelles (`isBugCondition_InvarianceActive`, `isBugCondition_Libelle`).
- **Property (P)** : le comportement correct attendu une fois la condition de bug levée — voir `## Correctness Properties`.
- **Preservation** : les comportements existants (flux « Corriger une paie émise », garde-fou `EMISE`→`EMISE`, filtrage/tri/`href` de `paies_pour_colonne`) qui doivent rester strictement inchangés par ce bugfix.
- **Paie_Logique** : le triplet `(employe_id, annee_fiscale, numero_periode)` qui identifie une même « case » de paie à travers ses versions successives (append-only).
- **Ligne active** : une ligne de la table `paies` dont `statut ∈ {BROUILLON, EMISE}` — par opposition à `ANNULEE`/`REMPLACE_PAR`, qui sont des états terminaux.
- **`inserer_paie`** : fonction de `payroll_engine/register.py` qui insère une nouvelle ligne `paies` (append-only), utilisée exclusivement par le flux « Nouvelle paie » (`_section_nouvelle_paie`/`_section_enregistrement` de `app/pages_ui/formulaire_paie.py`).
- **`remplacer_paie`** : fonction de `payroll_engine/register.py`, utilisée exclusivement par le flux « Corriger une paie émise » (`_section_corriger_paie`) — hors périmètre de ce bugfix, sert de modèle de référence pour la mutation de l'ancienne ligne.
- **`_connexion`** : gestionnaire de contexte de `payroll_engine/register.py` garantissant l'atomicité (`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`) de toute écriture — déjà utilisé par `inserer_paie` ; aucune nouvelle connexion n'est ouverte par ce bugfix.
- **`_ligne_colonne_paie_html`** : fonction de `app/pages_ui/tableau_de_bord.py` qui génère le libellé HTML cliquable d'une ligne de la Colonne_Paies du Tableau_De_Bord.
- **`paies_pour_colonne`** : fonction de `app/logique_metier/dernieres_paies.py` qui filtre/trie les `LignePaieResume` affichés dans la Colonne_Paies — non modifiée par ce bugfix.

## Bug Details

### Bug A — Absence d'invariant d'unicité active par période

**Formal Specification:**

```
FUNCTION isBugCondition_InvarianceActive(X)
  INPUT: X of type InsertionPaie
    // X représente un appel inserer_paie(nouvelle_ligne, saison, ...)
    // du flux "Nouvelle paie", où il existe, immédiatement avant cet
    // appel, une ligne active de statut BROUILLON pour la même
    // Paie_Logique (employe_id, annee_fiscale, numero_periode) que
    // nouvelle_ligne.
  OUTPUT: boolean

  RETURN existe_ligne_active(X.employe_id, X.annee_fiscale, X.numero_periode)
     AND ligne_active(X.employe_id, X.annee_fiscale, X.numero_periode).statut = BROUILLON
     AND X.nouvelle_ligne.statut IN {BROUILLON, EMISE}
END FUNCTION
```

### Examples

- Un employé enregistre un `BROUILLON` pour la période 1, puis rouvre le Formulaire_Paie et enregistre un second `BROUILLON` pour la même période 1 sans passer par le pré-remplissage de brouillon existant → **attendu** : l'ancien `BROUILLON` passe à `REMPLACE_PAR` ; **actuel (bug)** : les deux `BROUILLON` restent actifs indéfiniment.
- Un employé a un `BROUILLON` actif pour la période 2, puis assemble et enregistre directement en `EMISE` pour la même période 2 → **attendu** : l'ancien `BROUILLON` passe à `REMPLACE_PAR`, référencé par le nouvel `id_paie` `EMISE` ; **actuel (bug)** : le `BROUILLON` reste actif en plus du nouvel `EMISE`.
- Plusieurs sessions de saisie successives sans jamais émettre → **attendu** : à tout instant, au plus une ligne active pour cette période ; **actuel (bug)** : croissance sans limite du nombre de `BROUILLON` actifs.
- Cas limite déjà couvert (inchangé) : une ligne `EMISE` active existe déjà et une seconde insertion `EMISE` est tentée pour la même période → garde-fou existant lève `ValueError`, avant toute logique de ce bugfix.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Le garde-fou `EMISE`→`EMISE` existant (`ValueError`, `TestRefusDoubleEmisePourMemePeriode`) continue de s'appliquer, sans aucune modification de comportement ni de message.
- L'insertion d'un `BROUILLON` alors qu'une ligne `EMISE` active existe déjà (et qu'aucun `BROUILLON` actif n'existe) reste autorisée sans invalider la ligne `EMISE` (`test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee`).
- L'insertion de la première ligne d'une Paie_Logique n'ayant encore aucune ligne active reste une insertion simple, sans mutation d'aucune autre ligne.
- Le flux « Corriger une paie émise » (`_section_corriger_paie`, `remplacer_paie`) — aucune modification de signature ni de comportement.
- `cumuls_ytd` reste inchangée par la mutation d'un `BROUILLON` vers `REMPLACE_PAR` (un `BROUILLON` ne contribue jamais aux cumuls).
- Le filtrage (`paies_pour_colonne`), le tri, et les `href` de navigation de la Colonne_Paies — seul le texte du libellé change (Bug B).
- Le format complet avec année (`_formater_date_courte`) reste utilisé ailleurs dans ce fichier (ex. Bilan_Fiscal) — non modifié, seule une nouvelle fonction est ajoutée pour la Colonne_Paies.

**Scope:**
Toute insertion qui n'implique pas une ligne `BROUILLON` active préexistante pour la même Paie_Logique (Bug A), et tout affichage de la Colonne_Paies en dehors du texte du libellé lui-même (Bug B), sont hors du périmètre affecté par ce fix.

## Hypothesized Root Cause

1. **Bug A — étape manquante dans `inserer_paie`** : la fonction contrôle déjà l'unicité de `id_paie` (Req 11.6) et refuse le doublon `EMISE`→`EMISE` (garde-fou déjà en place), mais ne recherche jamais de ligne `BROUILLON` active de la même Paie_Logique avant d'insérer — contrairement à `remplacer_paie`, qui mute explicitement l'ancienne ligne (étape 3a) avant d'insérer la nouvelle (étape 3b). Le flux « Nouvelle paie » n'appelle jamais `remplacer_paie` (réservé au flux « Corriger une paie émise »), donc aucune mutation de l'ancienne ligne n'a jamais lieu pour ce flux.
2. **Bug A — append-only sans invalidation** : le modèle append-only du registre est correct par conception (immutabilité historique, règle 06 du projet) mais suppose qu'une étape d'invalidation de l'ancienne ligne accompagne systématiquement toute nouvelle version active — cette étape existe pour `remplacer_paie`, jamais pour `inserer_paie`.
3. **Bug B — format de libellé jamais revu depuis l'ajout du statut/date** : `_ligne_colonne_paie_html` a été écrit avant que le besoin d'afficher le numéro de période soit identifié, et réutilise `_formater_date_courte` (avec année) par défaut plutôt qu'un format dédié à un contexte où l'année est déjà filtrée en amont par le Selecteur_De_Periode_Global.
4. **Bug B — absence de fonction de formatage sans année** : aucune fonction existante de `tableau_de_bord.py` ne produit une date sans année ; `_formater_date_courte`/`_NOMS_MOIS_MINUSCULES` sont la seule référence de style disponible, mais incluent toujours l'année.

## Correctness Properties

Property 1: Bug Condition - Invariant "au plus une ligne active par période"

_For any_ insertion `X` via `inserer_paie` où `isBugCondition_InvarianceActive(X)` est vraie (une ligne `BROUILLON` active existe déjà pour la même Paie_Logique `(employe_id, annee_fiscale, numero_periode)`), la fonction corrigée SHALL, dans la même transaction atomique que l'insertion de la nouvelle ligne, faire passer le statut de cette ancienne ligne `BROUILLON` à `REMPLACE_PAR` et renseigner son `remplace_par_id` avec l'`id_paie` de la nouvelle ligne (en ne mutant que `statut`, `remplace_par_id` et `payload_json`, jamais `payload_input_json`), de sorte qu'il n'existe plus, après l'insertion, qu'une seule ligne active (`statut ∈ {BROUILLON, EMISE}`) pour cette Paie_Logique.

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition - Libellé Colonne_Paies sans année

_For any_ `LignePaieResume` `X` affiché dans la Colonne_Paies (`isBugCondition_Libelle(X)`, vraie pour tout statut `BROUILLON`/`EMISE`), la fonction corrigée `_ligne_colonne_paie_html` SHALL produire un libellé qui n'affiche jamais l'année, affiche toujours le `numero_periode`, et vaut exactement `"Paie #{numero_periode} - déposée le {date sans année}"` si `X.statut = EMISE`, ou exactement `"Paie #{numero_periode} - brouillon"` (sans aucune date) si `X.statut = BROUILLON`.

**Validates: Requirements 2.4, 2.5, 2.6**

Property 3: Preservation - Flux et garde-fous existants du registre

_For any_ insertion `X` via `inserer_paie` où `isBugCondition_InvarianceActive(X)` est fausse (aucune ligne `BROUILLON` active de la même Paie_Logique, ou insertion via un flux hors périmètre), la fonction corrigée SHALL produire exactement le même résultat que la fonction d'origine : le garde-fou `EMISE`→`EMISE` continue de lever `ValueError`, l'insertion d'un `BROUILLON` après un `EMISE` actif reste autorisée sans mutation, la première insertion d'une Paie_Logique reste une insertion simple, `cumuls_ytd` reste inchangée pour toute mutation `BROUILLON`→`REMPLACE_PAR`, et `remplacer_paie`/`_section_corriger_paie` restent inchangés à l'identique.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

Property 4: Preservation - Filtrage, tri et navigation de la Colonne_Paies

_For any_ `LignePaieResume` `X` où `isBugCondition_Libelle(X)` est fausse (aucun cas — le format actuel affecte systématiquement tout affichage), le filtrage par statut/année (`paies_pour_colonne`), l'ordre de tri (BROUILLON avant EMISE, puis date de paiement décroissante, puis numéro de période croissant) et les `href` de navigation générés par `_ligne_colonne_paie_html` SHALL rester strictement identiques à ceux produits avant cette correction — seul le texte affiché du libellé change.

**Validates: Requirements 3.6, 3.7, 3.8**

## Fix Implementation

### Bug A — `payroll_engine/register.py::inserer_paie`

**Changement 1 — nouvelle étape d'invalidation, dans la transaction existante.**

Insérée **après** le garde-fou `EMISE`→`EMISE` existant (étape « 1bis » du code actuel) et **avant** l'insertion de la nouvelle ligne (étape 2, `_inserer_ligne_paie_tx`) — même connexion/curseur `connexion` déjà ouvert par `_connexion(chemin_bd)`, aucune nouvelle transaction :

```python
# 1ter. Bug corrigé (unicite-paie-active-par-periode) — invalider
# toute ligne BROUILLON active de la même Paie_Logique avant
# l'insertion, dans la même transaction atomique. Toutes les lignes
# BROUILLON actives trouvées sont mutées (pas seulement la première) :
# une base ayant déjà accumulé plusieurs BROUILLON actifs avant ce
# correctif (conséquence du bug) doit être auto-réparée dès la
# prochaine insertion pour cette Paie_Logique, plutôt que de laisser
# des lignes orphelines actives.
lignes_brouillon_actives = connexion.execute(
    "SELECT id_paie, payload_json FROM paies WHERE employe_id = ? "
    "AND annee_fiscale = ? AND numero_periode = ? AND statut = ?",
    (
        resultat.employe_id,
        resultat.annee_fiscale,
        resultat.pay_period.numero_periode,
        StatutDePaie.BROUILLON.value,
    ),
).fetchall()
for id_paie_ancien, payload_ancien in lignes_brouillon_actives:
    ancien_resultat = PayrollResult.model_validate_json(payload_ancien)
    payload_ancien_maj = ancien_resultat.model_copy(
        update={
            "statut": StatutDePaie.REMPLACE_PAR,
            "remplace_par_id": resultat.id_paie,
        }
    ).model_dump_json()
    connexion.execute(
        "UPDATE paies SET statut = ?, remplace_par_id = ?, "
        "payload_json = ? WHERE id_paie = ?",
        (
            StatutDePaie.REMPLACE_PAR.value,
            resultat.id_paie,
            payload_ancien_maj,
            id_paie_ancien,
        ),
    )
```

Ce bloc reproduit **exactement** le modèle de mutation de l'étape 3a de `remplacer_paie` : `model_copy(update={"statut": ..., "remplace_par_id": ...})` puis `UPDATE ... SET statut = ?, remplace_par_id = ?, payload_json = ? WHERE id_paie = ?` — mêmes trois colonnes mutées, jamais `payload_input_json` (immutabilité de cette colonne, règle 06).

**Changement 2 — ordre des opérations dans `inserer_paie` (aucune modification de signature) :**

1. Contrôle d'unicité de `id_paie` (existant, inchangé).
2. Garde-fou `EMISE`→`EMISE` (existant, inchangé) — lève `ValueError` **avant toute écriture** si applicable.
3. **Nouveau** : invalidation des lignes `BROUILLON` actives de la même Paie_Logique (Changement 1) — s'exécute uniquement si l'étape 2 n'a pas levé d'exception.
4. Insertion append-only de la nouvelle ligne (existant, `_inserer_ligne_paie_tx`, inchangé).
5. Mise à jour conditionnelle de `cumuls_ytd` si `EMISE` (existant, inchangé).
6. Sortie du bloc `with _connexion(...)` — `COMMIT` unique couvrant les étapes 3, 4 et 5, ou `ROLLBACK` intégral si une exception traverse l'une d'elles.

**Aucun nouveau paramètre, aucune nouvelle fonction publique.** `_inserer_ligne_paie_tx`, `_connexion`, `_creer_schema_si_absent` restent inchangées. Le nouveau bloc est un ajout inline dans `inserer_paie`, cohérent avec la taille et le style du garde-fou `EMISE`→`EMISE` déjà présent dans la même fonction (pas de nouvelle fonction interne nécessaire — bloc court, non réutilisé ailleurs).

**Fichiers explicitement non modifiés (hors périmètre) :** `app/pages_ui/formulaire_paie.py` (`_section_corriger_paie`, `_section_nouvelle_paie`), `remplacer_paie`.

### Bug B — `app/pages_ui/tableau_de_bord.py::_ligne_colonne_paie_html`

**Changement 1 — nouvelle fonction de formatage sans année**, ajoutée à côté de `_formater_date_courte` (même fichier, même style) :

```python
def _formater_date_sans_annee(valeur_iso: str) -> str:
    """Formate une date/heure ISO en date courte française SANS année
    (bug corrigé — Colonne_Paies, Req 2.4, 2.6) : ``"<jour> <mois>"``,
    ex. ``"29 juillet"`` (jour sans zéro initial, mois en minuscules —
    même convention que :func:`_formater_date_courte`). L'année est
    volontairement omise : la Colonne_Paies n'affiche déjà que les
    paies de l'année sélectionnée par le Selecteur_De_Periode_Global
    (``paies_pour_colonne``) — l'afficher serait redondant.
    """
    valeur_date = datetime.fromisoformat(valeur_iso).date()
    return f"{valeur_date.day} {_NOMS_MOIS_MINUSCULES[valeur_date.month]}"
```

Réutilise `_NOMS_MOIS_MINUSCULES` (déjà défini dans ce fichier) — aucune nouvelle table de noms de mois.

**Changement 2 — nouveau corps de `_ligne_colonne_paie_html`** (signature inchangée : `(employe_id: str, resume: LignePaieResume) -> str`) :

```python
def _ligne_colonne_paie_html(employe_id: str, resume: LignePaieResume) -> str:
    """Génère une ligne cliquable de la Colonne_Paies pour ``resume``
    (Req 2.4, 2.5, 2.6) : numéro de période et statut, sous forme de
    lien — même navigation qu'avant cette correction (Formulaire_Paie
    en mode correction si BROUILLON, Bulletin_De_Paie si EMISE). Ne
    modifie jamais le filtrage (`paies_pour_colonne`), le tri, ni les
    `href` — seul le texte affiché change.
    """
    if resume.statut == StatutDePaie.EMISE.value:
        date_affichee = _formater_date_sans_annee(resume.date_paiement)
        texte = f"Paie #{resume.numero_periode} - déposée le {date_affichee}"
    else:  # BROUILLON — jamais de date (Req 2.5)
        texte = f"Paie #{resume.numero_periode} - brouillon"

    if resume.statut == StatutDePaie.BROUILLON.value:
        href = (
            "/formulaire-paie"
            f"?employe_id={quote(employe_id)}"
            f"&id_paie={quote(resume.id_paie)}"
        )
    else:
        href = f"/bulletin-paie?id_paie={quote(resume.id_paie)}"
    return _lien_action_employe(href=href, texte=texte)
```

**Changements explicitement exclus :** `_LIBELLES_STATUT` reste défini (utilisé ailleurs dans le fichier pour d'autres affichages de statut) mais n'est plus référencé par `_ligne_colonne_paie_html` ; `_formater_date_courte` reste inchangée et continue d'être utilisée par les autres sections du fichier ; `paies_pour_colonne`, `_contenu_colonne_paies_html`, la construction des `href` et la logique de tri restent inchangées.

## Testing Strategy

### Validation Approach

Deux phases : d'abord surfacer des contre-exemples démontrant chaque bug sur le code non corrigé (confirme/réfute l'analyse de root cause), puis vérifier que le fix corrige le comportement pour les entrées affectées tout en préservant le reste.

### Exploratory Bug Condition Checking

**Goal**: Surfacer des contre-exemples AVANT d'implémenter le fix, pour confirmer ou réfuter les hypothèses de root cause ci-dessus.

**Test Plan**: Sur le code non corrigé, insérer une séquence `BROUILLON` → `BROUILLON` puis `BROUILLON` → `EMISE` pour la même Paie_Logique via `inserer_paie`, et observer le nombre de lignes actives résultantes ainsi que le libellé produit par `_ligne_colonne_paie_html`.

**Test Cases**:
1. **Double BROUILLON même période** : insérer deux `BROUILLON` successifs pour `(EMP001, 2026, 1)` → sur le code non corrigé, `lire_historique_paie` doit révéler deux lignes actives (`BROUILLON`, `BROUILLON`), ce qui est le contre-exemple attendu.
2. **BROUILLON puis EMISE même période** : insérer un `BROUILLON` puis un `EMISE` pour la même période → sur le code non corrigé, les deux lignes doivent rester actives (`BROUILLON` actif ET `EMISE` actif simultanément).
3. **Libellé EMISE avec année** : construire un `LignePaieResume` `EMISE` avec une `date_paiement` connue → sur le code non corrigé, `_ligne_colonne_paie_html` doit produire un texte contenant l'année et le préfixe `"Émise — "`, jamais `"Paie #"`.
4. **Libellé BROUILLON avec date** : construire un `LignePaieResume` `BROUILLON` → sur le code non corrigé, le texte produit contient une date (alors qu'un brouillon ne devrait jamais en afficher une).

**Expected Counterexamples**:
- Plus d'une ligne active simultanément pour une même Paie_Logique après plusieurs insertions successives via `inserer_paie` (confirme Bug A).
- Libellé contenant l'année et omettant le numéro de période, quel que soit le statut (confirme Bug B).

### Fix Checking

**Goal**: Vérifier que pour toute entrée où la condition de bug est vraie, la fonction corrigée produit le comportement attendu (Property 1, Property 2).

**Pseudocode:**
```
FOR ALL X WHERE isBugCondition_InvarianceActive(X) DO
  ancienne_ligne := ligne_active(X.employe_id, X.annee_fiscale, X.numero_periode)
  inserer_paie'(X.nouvelle_ligne, X.saison, ...)

  lignes_actives := lignes_avec_statut_dans(
      X.employe_id, X.annee_fiscale, X.numero_periode, {BROUILLON, EMISE}
  )
  ASSERT nombre(lignes_actives) = 1 AND lignes_actives[0].id_paie = X.nouvelle_ligne.id_paie

  ancienne_relue := lire_paie'(ancienne_ligne.id_paie)
  ASSERT ancienne_relue.statut = REMPLACE_PAR
     AND ancienne_relue.remplace_par_id = X.nouvelle_ligne.id_paie
END FOR

FOR ALL X WHERE isBugCondition_Libelle(X) DO
  libelle := _ligne_colonne_paie_html'(X.employe_id, X.resume)
  ASSERT NOT contient_annee(libelle)
  IF X.resume.statut = EMISE THEN
    ASSERT libelle_texte(libelle) = "Paie #" + X.resume.numero_periode + " - déposée le " + formater_date_sans_annee(X.resume.date_paiement)
  END IF
  IF X.resume.statut = BROUILLON THEN
    ASSERT libelle_texte(libelle) = "Paie #" + X.resume.numero_periode + " - brouillon" AND NOT contient_date(libelle)
  END IF
END FOR
```

### Preservation Checking

**Goal**: Vérifier que pour toute entrée où la condition de bug est fausse, la fonction corrigée produit le même résultat que la fonction d'origine (Property 3, Property 4).

**Pseudocode:**
```
FOR ALL X WHERE NOT isBugCondition_InvarianceActive(X) DO
  ASSERT inserer_paie(X) = inserer_paie'(X)
  // incluant : ValueError levée dans les mêmes cas (EMISE->EMISE),
  // aucune mutation d'aucune autre ligne, cumuls_ytd identiques
END FOR

FOR ALL X WHERE NOT isBugCondition_Libelle(X) DO
  ASSERT paies_pour_colonne(X) = paies_pour_colonne'(X)  // inchangé, non touché
  ASSERT href(_ligne_colonne_paie_html(X)) = href(_ligne_colonne_paie_html'(X))
END FOR
```

**Testing Approach**: Property-based testing est recommandé pour la préservation car il génère automatiquement de nombreuses séquences d'insertions et de nombreux `LignePaieResume`, incluant des combinaisons de statuts/périodes non anticipées manuellement.

**Test Plan**: Observer le comportement sur le code NON corrigé pour le garde-fou `EMISE`→`EMISE`, l'insertion `BROUILLON` après `EMISE`, et le tri/filtrage de `paies_pour_colonne`, puis écrire des tests capturant ce comportement pour garantir qu'il persiste après le fix.

**Test Cases**:
1. **Garde-fou EMISE→EMISE préservé** : `TestRefusDoubleEmisePourMemePeriode` (existant) doit continuer à passer sans modification après le fix.
2. **BROUILLON après EMISE préservé** : `test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee` (existant) doit continuer à passer sans modification.
3. **Première insertion d'une Paie_Logique** : observer qu'une insertion simple (aucune ligne active préexistante) ne mute aucune autre ligne, avant et après le fix.
4. **Tri et filtrage Colonne_Paies inchangés** : observer l'ordre et le sous-ensemble retourné par `paies_pour_colonne` sur un jeu de `LignePaieResume` varié, avant et après le fix (le fix ne touche pas cette fonction).
5. **`href` inchangés** : observer les `href` générés par `_ligne_colonne_paie_html` pour un `BROUILLON` et un `EMISE`, avant et après le fix — seul le texte doit différer.

### Unit Tests

- `inserer_paie` : insertion d'un `BROUILLON` alors qu'un `BROUILLON` actif existe déjà pour la même Paie_Logique → l'ancien passe à `REMPLACE_PAR`, `remplace_par_id` pointe vers le nouveau, une seule ligne active après.
- `inserer_paie` : insertion d'un `EMISE` alors qu'un `BROUILLON` actif existe déjà pour la même Paie_Logique → même résultat que ci-dessus, et `cumuls_ytd` reflète uniquement la contribution du nouvel `EMISE`.
- `inserer_paie` : cas avec plusieurs `BROUILLON` actifs préexistants (auto-réparation) → toutes les anciennes lignes passent à `REMPLACE_PAR`, une seule ligne active après.
- `_ligne_colonne_paie_html` : cas `EMISE` avec une date connue → texte exact `"Paie #{n} - déposée le {jour} {mois}"`, sans année.
- `_ligne_colonne_paie_html` : cas `BROUILLON` → texte exact `"Paie #{n} - brouillon"`, aucune date.
- `_formater_date_sans_annee` : jour sans zéro initial, mois en minuscules, jamais d'année dans la chaîne produite.

### Property-Based Tests

- Property 1 (Fix Checking, Bug A) : pour toute séquence Hypothesis d'insertions `BROUILLON`/`EMISE` sur la même Paie_Logique respectant le garde-fou `EMISE`→`EMISE`, après chaque insertion il existe au plus une ligne active, et toute ligne devenue inactive porte `statut = REMPLACE_PAR` avec `remplace_par_id` correct.
- Property 2 (Fix Checking, Bug B) : pour tout `LignePaieResume` généré aléatoirement (statut, numéro de période, date de paiement arbitraires), le libellé produit ne contient jamais l'année et respecte le format exact attendu selon le statut.
- Property 3 (Preservation, Bug A) : pour toute séquence d'insertions ne déclenchant jamais `isBugCondition_InvarianceActive` (ex. Paie_Logiques toutes distinctes, ou statuts alternant sans jamais avoir de `BROUILLON` actif préexistant), le résultat (lignes insérées, exceptions levées, `cumuls_ytd`) est strictement identique à celui produit par la fonction d'origine.
- Property 4 (Preservation, Bug B) : pour tout jeu de `LignePaieResume` généré aléatoirement, `paies_pour_colonne` et les `href` produits par `_ligne_colonne_paie_html` restent identiques avant/après le fix.

### Integration Tests

- Flux complet « Nouvelle paie » : enregistrer un `BROUILLON`, rouvrir le Formulaire_Paie, enregistrer un second `BROUILLON` pour la même période sans pré-remplissage explicite → vérifier via le Tableau_De_Bord que la Colonne_Paies n'affiche plus qu'une seule ligne active pour cette période, avec le nouveau libellé.
- Flux complet « Nouvelle paie » suivi d'une émission : `BROUILLON` puis `EMISE` pour la même période → Bilan_Fiscal ne compte la contribution qu'une seule fois (`cumuls_ytd` correct).
- Flux « Corriger une paie émise » inchangé : exécuter une correction complète (`remplacer_paie`) après ce bugfix et vérifier qu'aucune régression n'apparaît (mêmes assertions que les tests existants du flux de correction).
- Tableau_De_Bord : vérifier que la Colonne_Paies affiche `"Paie #1 - déposée le 29 juillet"` pour une paie `EMISE` réelle et `"Paie #2 - brouillon"` pour un brouillon réel, dans le contexte d'une année sélectionnée par le Selecteur_De_Periode_Global.
