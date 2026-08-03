# Atelier — Données sources et extraction des golden tests

Ce document décrit le protocole d'importation, d'extraction et d'anonymisation des fichiers sources (Excel de fiches d'employés, bulletins de paie générés depuis WebRAS et PDOC) afin d'en tirer les scénarios de référence utilisés par la suite de golden tests.

Objectif fondamental : conserver **la valeur d'audit** des calculs officiels tout en **excluant définitivement** toute donnée personnelle réelle du dépôt.

## Principes non négociables

1. Les fichiers sources bruts ne quittent jamais le poste local. Ils ne sont ni commis, ni synchronisés, ni transmis à un service tiers.
2. Seules les **valeurs numériques dépersonnalisées** transitent vers le dépôt versionné, sous forme de scénarios `QCxxx` anonymisés.
3. Un scénario ne mentionne jamais un nom, un NAS, un compte bancaire, une adresse ou toute autre donnée nominative.
4. Chaque scénario indique explicitement sa source (WebRAS, PDOC), la date d'exécution officielle et l'année fiscale.

## Emplacement dans le workspace

```
camp-lilyso-payroll/
├── intake/                              <- entièrement exclu de Git (.gitignore)
│   ├── fiches-employes/                 <- Excel des fiches employés (données réelles)
│   ├── fiches-paie/                     <- Excel des bulletins générés (WebRAS + PDOC)
│   └── captures-officielles/            <- PDF/PNG des sessions WebRAS et PDOC (optionnel)
```

Le dossier `intake/` est créé au besoin et exclu intégralement par `.gitignore`. Aucun fichier n'y est versionné.

## Convention de nommage suggérée

Pour faciliter le repérage sans exposer d'identité, préférer :

```
intake/fiches-paie/2026-P1-employe-A.xlsx
intake/fiches-paie/2026-P1-employe-B.xlsx
intake/fiches-employes/employe-A.xlsx
```

Un mapping local `intake/mapping.txt` (ignoré par Git) peut associer `employe-A` à un vrai nom, à des fins de retrouvage interne. Ce mapping ne quitte jamais le poste.

## Workflow d'extraction

Étape par étape, pour chaque fichier source :

1. **Dépôt**
   L'utilisateur place le fichier dans `intake/`.

2. **Lecture par Kiro**
   Kiro lit le fichier (feuilles Excel, cellules calculées). Aucun contenu nominatif n'est répercuté dans les prompts de conversation ni dans les fichiers du dépôt.

3. **Extraction des paramètres du scénario**
   Sont extraits uniquement :
   - Année fiscale
   - Province de travail (attendue : Québec)
   - Fréquence de paie
   - Âge de l'employé (ou tranche d'âge si nécessaire)
   - TP-1015.3 : montant total, exonération oui/non, retenue additionnelle
   - TD1 : montant total, exonération oui/non, retenue additionnelle
   - Salaire brut de la période, incluant décomposition régulier / heures supp / vacances
   - Heures par semaine (pour valider le module heures supp)
   - Position de la paie dans la saison (paie 1, 2, 3)
   - Cumuls YTD au début de la période, s'ils existent

4. **Extraction des résultats officiels**
   Sont extraits uniquement les montants calculés par WebRAS et PDOC :
   - RRQ employé, RRQ employeur
   - RQAP employé, RQAP employeur
   - AE employé, AE employeur
   - Impôt du Québec retenu
   - Impôt fédéral retenu
   - Salaire net
   - FSS, CNESST (provision), CNT si présents

5. **Attribution d'un identifiant**
   Le scénario reçoit un code séquentiel `QCxxx` selon la date d'ouverture. Aucun lien avec un nom.

6. **Rédaction du scénario anonymisé**
   Création ou mise à jour d'un document `docs/scenario-QCxxx.md` sur le modèle de `docs/scenario-qc001.md`, contenant uniquement les valeurs extraites.

7. **Création du test automatique**
   Le scénario est ajouté à `tests/test_reference_payrolls.py` (ou fichier dédié) comme cas paramétré.

8. **Archivage éventuel**
   Si l'utilisateur souhaite conserver une preuve d'audit visuelle sans données nominatives, une capture caviardée peut être archivée dans `tests/fixtures/personal/QCxxx/` (hors dépôt, exclu par `.gitignore`). Le nom original ne doit pas apparaître.

9. **Nettoyage optionnel**
   Une fois le scénario validé et le test créé, le fichier Excel source peut être :
   - conservé dans `intake/` (aucun impact sur Git)
   - déplacé vers un stockage local hors workspace
   - supprimé si l'utilisateur préfère

## Ce qui ne quitte jamais `intake/`

Sans exception :

- Nom complet réel
- Numéro d'assurance sociale
- Numéro de compte bancaire, transit, institution
- Adresse
- Date de naissance exacte (utiliser l'âge, ou une tranche)
- Signature numérisée
- Toute image ou PDF nominatif non caviardé

## Rôle de Kiro pendant l'extraction

Kiro :

- Peut lire librement les fichiers déposés dans `intake/`
- Doit paraphraser et **anonymiser** avant toute écriture vers `docs/`, `tests/` ou tout autre dossier versionné
- Doit refuser d'écrire un nom, NAS ou détail bancaire dans une réponse de conversation
- Doit signaler à l'utilisateur si un fichier contient un type de donnée que l'application ne supporte pas (voir `docs/cas-non-supportes.md`) — ce cas devient alors une décision : soit étendre la matrice, soit exclure ce scénario de la suite golden

## Point d'entrée pour l'utilisateur

Message type à envoyer à Kiro après avoir déposé les fichiers :

> « Les fichiers sont dans `intake/`. Extrais les scénarios anonymisés et propose-moi les valeurs à vérifier avant de créer les tests. »

Kiro procédera fichier par fichier, présentera un tableau récapitulatif anonymisé pour validation humaine, et ne créera les scénarios `QCxxx` qu'après confirmation.
