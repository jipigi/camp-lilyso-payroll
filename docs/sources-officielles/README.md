# Guides fiscaux officiels — référence ultime des calculs (versionnés par année)

Ce dossier archive les **guides gouvernementaux publics** qui servent de
**référence ultime** à tous les calculs fiscaux du moteur. Ils sont
**versionnés dans Git** (documents publics, aucune donnée personnelle — règle 04)
afin de rendre chaque valeur de `parameters/<AAAA>/*.json` reproductible et
auditable (règles 02 et 05). Ils accompagnent le fichier `docs/sources-officielles.md`
(liste blanche des sources autorisées).

## Structure (une année = un sous-dossier)

```
docs/sources-officielles/
├── 2026/
│   ├── tp-1015-f-2026.pdf                       # Revenu Québec — TP-1015.F (impôt QC, RRQ, RQAP, FSS)
│   ├── t4127-2026.pdf                           # ARC — T4127 (impôt fédéral, AE)
│   ├── le-39.0.2-2026.pdf                       # Revenu Québec — LE-39.0.2 (cotisation CNT)
│   ├── cnesst-table-taux-2026.pdf               # CNESST — table des taux par unité
│   └── cnesst-classification-camp-lilyso-2026.pdf  # CNESST — décision de classification (unité 57020)
├── 2027/                                         # à créer l'an prochain
└── README.md
```

Convention de nommage : minuscules, tirets, année sur 4 chiffres
(`tp-1015-f-<AAAA>.pdf`, `t4127-<AAAA>.pdf`, `le-39.0.2-<AAAA>.pdf`,
`cnesst-table-taux-<AAAA>.pdf`, ...).

## Processus de mise à jour annuelle

Chaque année, avant la première paie :

1. Déposer les nouveaux guides dans `docs/sources-officielles/<nouvelle_année>/`.
2. Demander la vérification : comparer aux paramètres de l'année précédente,
   extraire les valeurs à jour (paliers, taux, plafonds, déductions, crédits,
   abattement, taux FSS/CNESST/CNT) et créer `parameters/<nouvelle_année>/{quebec,canada}.json`.
3. Relancer la validation contre WebRAS et PDOC sur le corpus de référence.
4. Consigner les écarts et la validation dans `docs/journal-validation.md`.

Ce cycle est aligné sur la section « Mise à jour annuelle » de la règle 05.

## Règle 04 — ce qui NE va PAS ici

- Aucune capture WebRAS/PDOC **nominative** (par employé) : celles-ci peuvent
  contenir des données personnelles réelles et doivent aller dans
  `tests/fixtures/personal/` (exclu par `.gitignore`), jamais ici.
- Aucun bulletin réel, aucun TD1/TP-1015.3 rempli réel.

Seuls des documents **publics** sont versionnés ici. La décision de
classification CNESST du Camp LilySO est un document d'employeur sans donnée
personnelle d'employé (unité et taux uniquement).

## Guides archivés (2026)

| Fichier | Source | Valide |
|---|---|---|
| `2026/tp-1015-f-2026.pdf` | Revenu Québec — TP-1015.F 2026 (version 2026-01) | `parameters/2026/quebec.json` — impôt QC, RRQ, RQAP, FSS |
| `2026/t4127-2026.pdf` | ARC — T4127 2026 | `parameters/2026/canada.json` — impôt fédéral, AE |
| `2026/le-39.0.2-2026.pdf` | Revenu Québec — LE-39.0.2 (2026-01) | `parameters/2026/quebec.json` — cotisation CNT (taux, max assujetti) |
| `2026/cnesst-table-taux-2026.pdf` | CNESST — table des taux 2026 | `parameters/2026/quebec.json` — taux CNESST (CNI + unité) |
| `2026/cnesst-classification-camp-lilyso-2026.pdf` | CNESST — classification Camp LilySO | `parameters/2026/quebec.json` — unité 57020 |
