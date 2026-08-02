# Scénario de référence QC002

Paie #1 réelle anonymisée d'un employé du corpus Camp LilySO — brut le plus élevé. Utilisé pour valider la formule d'impôt QC et l'impôt fédéral aux niveaux hauts de la courbe, ainsi que le court-circuit d'exonération.

## Contexte

| Élément | Valeur |
|---|---|
| Identifiant | QC002 |
| Nature | Paie réelle anonymisée (EMP001 dans `intake/`) |
| Année fiscale | 2026 |
| Province de travail | Québec |
| Fréquence de paie | Aux deux semaines (27 périodes en 2026) |
| Position dans la saison | Paie 1 (aucun cumul YTD antérieur) |
| Date de paiement | 2026-07-29 |
| Titre d'emploi | Monitrice en chef |
| Taux horaire | 21,00 $ |
| Heures normales / heures supp | 116 / 10 |
| **Exonération TP-1015.3 (impôt QC)** | **Cochée** |
| **Exonération TD1 (impôt fédéral)** | **Cochée** |

## Décomposition du brut

| Ligne | Montant |
|---|---|
| Salaire régulier (116 h × 21 + 10 h × 31,50) | 2 751,00 $ |
| Vacances 4 % | 110,04 $ |
| **Salaire brut** | **2 861,04 $** |

## Résultats officiels

### Impôts — valeurs formule (WebRAS et PDOC pré-exonération)

Ces valeurs sont celles que WebRAS et PDOC produisent pour ce brut sans considération d'exonération. Elles servent de golden test pour les modules `impot-quebec` et `impot-federal`.

| Ligne | Valeur | Source |
|---|---|---|
| Impôt QC (formule TP-1015.F) | **329,31 $** | WebRAS |
| Impôt fédéral (formule T4127) | **289,05 $** | PDOC |

### Impôts — valeurs retenues (post-exonération)

Ces valeurs sont ce que le moteur doit produire quand l'exonération est active, soit un court-circuit à 0.

| Ligne | Valeur | Mécanisme |
|---|---|---|
| Impôt QC retenu | 0,00 $ | Court-circuit exonération TP-1015.3 |
| Impôt fédéral retenu | 0,00 $ | Court-circuit exonération TD1 |

### Retenues employé (indépendantes de l'exonération d'impôt)

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ | (2 861,04 − 129,63) × 6,30 % | **172,08 $** |
| RQAP | 2 861,04 × 0,43 % | **12,30 $** |
| AE | 2 861,04 × 1,30 % | **37,19 $** |

### Cotisations employeur

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ employeur | Identique à employé | 172,08 $ |
| RQAP employeur | 2 861,04 × 0,602 % | 17,22 $ |
| AE employeur | 37,19 × 1,4 | 52,07 $ |
| FSS | 2 861,04 × 1,65 % | 47,21 $ |
| CNESST (1,12 % — unité 57020 confirmée) | 2 861,04 × 1,12 % | 32,04 $ |

### Consolidation

| Élément | Valeur |
|---|---|
| Total retenues employé (avec exonération) | 221,57 $ |
| Total retenues employé (sans exonération) | 839,93 $ |
| **Salaire net (avec exonération)** | **2 639,47 $** |
| Salaire net (sans exonération) | 2 021,11 $ |
| Coût employeur (incl. CNESST) | 3 181,66 $ |

## Utilisation comme golden test

- **Formule impôt QC** : `calcul_impot_quebec(brut=2861,04, exoneration=False)` doit retourner 329,31 $
- **Formule impôt féd.** : `calcul_impot_federal(brut=2861,04, exoneration=False)` doit retourner 289,05 $
- **Court-circuit** : `calcul_impot_quebec(brut=2861,04, exoneration=True)` doit retourner 0,00 $ sans invoquer la formule
- **RRQ, RQAP, AE, FSS, RQAP employeur, AE employeur** : au cent près
