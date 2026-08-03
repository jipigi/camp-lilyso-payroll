# Guides fiscaux officiels — référence ultime des calculs (versionnés par année)

Ce dossier archive les **guides gouvernementaux publics** qui servent de
**référence ultime** à tous les calculs fiscaux du moteur. Ils sont
**versionnés dans Git** (documents publics, aucune donnée personnelle — règle 04)
afin de rendre chaque valeur de `parameters/<AAAA>/*.json` reproductible et
auditable (règles 02 et 05).

## Structure (une année = un sous-dossier)

```
tests/fixtures/official/
├── 2026/
│   ├── tp-1015-f-2026.pdf     # Revenu Québec — TP-1015.F 2026
│   └── t4127-2026.pdf         # ARC — T4127 2026
├── 2027/                       # à créer l'an prochain
│   ├── tp-1015-f-2027.pdf
│   └── t4127-2027.pdf
└── README.md
```

Convention de nommage : `tp-1015-f-<AAAA>.pdf`, `t4127-<AAAA>.pdf` (minuscules,
tirets, année sur 4 chiffres).

## Processus de mise à jour annuelle

Chaque année, avant la première paie :

1. Déposer les nouveaux guides dans `tests/fixtures/official/<nouvelle_année>/`.
2. Demander la vérification : comparer aux paramètres de l'année précédente,
   extraire les valeurs à jour (paliers, taux, plafonds, déductions, crédits,
   abattement) et créer `parameters/<nouvelle_année>/{quebec,canada}.json`.
3. Relancer la validation contre WebRAS et PDOC sur le corpus de référence.
4. Consigner les écarts et la validation dans `docs/journal-validation.md`.

Ce cycle est aligné sur la section « Mise à jour annuelle » de la règle 05.

## Règle 04 — ce qui NE va PAS ici

- Aucune capture WebRAS/PDOC **nominative** (par employé) : celles-ci peuvent
  contenir des données personnelles réelles et doivent aller dans
  `tests/fixtures/personal/` (exclu par `.gitignore`), jamais dans `official/`.
- Aucun bulletin réel, aucun TD1/TP-1015.3 rempli réel.

Seuls les documents **publics** (guides gouvernementaux) sont versionnés ici.

## Guides archivés

| Année | Fichier | Source | Valide |
|---|---|---|---|
| 2026 | `2026/tp-1015-f-2026.pdf` | Revenu Québec — TP-1015.F 2026 (version 2026-01) | `parameters/2026/quebec.json` (impôt QC, RRQ, RQAP, FSS, CNT) |
| 2026 | `2026/t4127-2026.pdf` | ARC — T4127 2026 | `parameters/2026/canada.json` (impôt fédéral, AE) |
