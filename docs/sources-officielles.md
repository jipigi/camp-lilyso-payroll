# Sources officielles

Registre exhaustif des documents et outils gouvernementaux utilisés comme référence normative pour ce projet. Toute formule implémentée dans `payroll_engine/` DOIT tracer son origine vers l'une de ces sources.

**Convention** : ce document liste les sources autorisées. Le contenu réel (valeurs, dates de publication, URLs stables) sera confirmé lors de la consultation de chaque document et consigné dans les fichiers de paramètres `parameters/<AAAA>/*.json` sous les champs `source`, `date_publication` et `url_consultee`.

## Revenu Québec

### TP-1015.F — Formules pour le calcul des retenues à la source et des cotisations

**Rôle** : source primaire pour tous les calculs québécois (impôt QC, RRQ, RQAP, FSS, CNT).

**Portée dans le projet** :

- Formules de retenue de l'impôt du Québec
- Formules RRQ (cotisation de base et supplémentaire)
- Formules RQAP
- Paramètres du Fonds des services de santé (FSS)
- Cotisation relative aux normes du travail

**Point d'accès** : à consulter directement sur `revenuquebec.ca`, section « Formulaires et publications », rechercher `TP-1015.F <ANNÉE>`.

### TP-1015.G — Guide de l'employeur

**Rôle** : guide narratif accompagnant les formules, utile pour comprendre les cas limites et les règles d'application.

**Portée dans le projet** :

- Traitement des périodes de paie partielles
- Traitement des cumuls
- Règles d'arrondissement narrées

### TP-1015.3 — Déclaration pour la retenue d'impôt (Québec)

**Rôle** : formulaire rempli par l'employé, source des paramètres personnels utilisés par le moteur.

**Portée dans le projet** :

- Montant total des crédits demandés
- Case d'exonération de la retenue d'impôt du Québec
- Retenue additionnelle demandée

### WebRAS

**Rôle** : calculateur officiel en ligne de Revenu Québec, utilisé comme oracle de référence pour les golden tests.

**Portée dans le projet** :

- Génération de résultats de référence pour chaque scénario `QCxxx`
- Validation continue du moteur (comparaison au cent près)
- Archivage des captures d'écran ou PDF de chaque exécution dans `tests/fixtures/official/`

**Entrées WebRAS pertinentes** :

- Nombre de périodes de paie dans l'année (attention : 27 en 2026, 26 en année standard)
- Période de paie courante (1, 2, ou 3 pour le camp)
- Salaire brut de la période (vacances incluses)
- Masse salariale totale annuelle de l'employeur (impacte le taux FSS)
- Montant personnel de base du TP-1015.3
- Autres champs laissés à leur valeur par défaut pour les cas Camp LilySO

**Limites de WebRAS pour ce projet** :

- **Pas de case « exonération de la retenue d'impôt »** : cette option des formulaires TP-1015.3 et TD1 est appliquée en aval par l'employeur, hors WebRAS. Le moteur devra implémenter l'exonération comme un court-circuit en amont du calcul d'impôt.

## Agence du revenu du Canada (ARC)

### T4127 — Formules pour le calcul informatisé des retenues sur la paie

**Rôle** : source primaire pour tous les calculs fédéraux, expressément conçue pour les développeurs de logiciels de paie.

**Portée dans le projet** :

- Formules de retenue de l'impôt fédéral
- Formules d'assurance-emploi (taux Québec)
- Règles d'annualisation
- Traitement des paramètres TD1
- Règles d'arrondissement fédérales

### TD1 fédéral

**Rôle** : formulaire rempli par l'employé, source des paramètres personnels fédéraux.

**Portée dans le projet** :

- Montant total des crédits demandés
- Case d'exonération de la retenue d'impôt fédéral
- Retenue additionnelle demandée

### PDOC — Calculateur en direct des retenues sur la paie (ARC)

**Rôle** : calculateur officiel en ligne de l'ARC, utilisé comme oracle de référence complémentaire à WebRAS.

**Portée dans le projet** :

- Validation croisée de l'impôt fédéral et de l'AE
- Génération de résultats de référence pour chaque scénario
- Archivage des captures dans `tests/fixtures/official/`

**Entrées PDOC pertinentes** :

- Province ou territoire d'emploi (Québec)
- Fréquence des périodes de paie avec nombre de périodes annuelles (aux 2 semaines / 27 pour 2026)
- Date à laquelle l'employé est rémunéré
- Revenu de salaires ou de traitement par période de paie (base salaire, sans vacances)
- Paie de vacances (champ distinct)
- Montant total du formulaire TD1 fédéral
- Traitement RRQ (« Exemption au RRQ » indique le régime QC standard)
- Cumuls annuels AE (gains assurables + cotisations déjà retenues) — pour respecter le plafond en fin d'année

**Sorties PDOC pertinentes** :

- Retenue d'impôt fédéral, retenue d'impôt provincial (= 0 pour QC, calculé par WebRAS)
- Retenues pour RRQ (base + supplémentaire agrégés) et RRQ2 (séparément)
- Retenue pour AE
- **Autres montants > Retenues des cotisations supplémentaires du RRQ** : portion 1 % du RRQ traitée comme déduction fédérale. À utiliser pour reproduire la formule `impot-federal`.

**Limites de PDOC pour ce projet** :

- **Pas de case « exonération de la retenue d'impôt »** : même mécanisme que WebRAS. L'exonération TD1 est appliquée en aval, non prise en charge par le calculateur.

## CNESST

**Rôle** : source pour la classification et le taux de cotisation applicable.

**Portée dans le projet** :

- Décision de classification (unité, taux CNI, taux d'unité)
- Traitement en tant que charge patronale (jamais retenue employé)

**Statut actuel** : la demande d'inscription du Camp LilySO a été transmise ; hypothèse de travail unité 57020 à 1,12 %, à confirmer.

## Normes du travail du Québec (CNESST — mandat CNT)

**Rôle** : source pour la cotisation relative aux normes du travail.

**Portée dans le projet** :

- Taux de la cotisation annuelle
- Base d'application (rémunérations assujetties)

## Protocole d'archivage des sources

Pour chaque source consultée :

1. Noter la date exacte de consultation
2. Sauvegarder une copie PDF locale (hors dépôt Git si le document est nominatif)
3. Consigner l'URL exacte dans le champ `url_consultee` du fichier de paramètres correspondant
4. Ne jamais reproduire textuellement de larges extraits dans le dépôt — se limiter à des références de section

## Sources interdites

- Blogs, forums, sites tiers (Wagepoint, Nethris, ADP, etc.)
- Anciens exemples internet
- Documents non datés
- Documents non attribués à une administration fiscale officielle
