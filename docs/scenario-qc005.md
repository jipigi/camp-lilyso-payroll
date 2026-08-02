# Scénario de référence QC005

Paie #1 réelle anonymisée d'un employé du corpus Camp LilySO — brut intermédiaire. Utilisé pour valider la formule d'impôt QC/fédéral au niveau intermédiaire de la courbe et le court-circuit d'exonération.

## Contexte

| Élément | Valeur |
|---|---|
| Identifiant | QC005 |
| Nature | Paie réelle anonymisée (EMP004 dans `intake/`) |
| Année fiscale | 2026 |
| Province de travail | Québec |
| Fréquence de paie | Aux deux semaines (27 périodes en 2026) |
| Position dans la saison | Paie 1 |
| Date de paiement | 2026-07-29 |
| Titre d'emploi | Monitrice |
| Taux horaire | 14,00 $ |
| Heures normales / heures supp | 112 / 5 |
| **Exonération TP-1015.3 (impôt QC)** | **Cochée** |
| **Exonération TD1 (impôt fédéral)** | **Cochée** |

## Décomposition du brut

| Ligne | Montant |
|---|---|
| Salaire régulier (112 h × 14 + 5 h × 21) | 1 673,00 $ |
| Vacances 4 % | 66,92 $ |
| **Salaire brut** | **1 739,92 $** |

## Résultats officiels

### Impôts — valeurs formule (WebRAS et PDOC pré-exonération)

| Ligne | Valeur | Source |
|---|---|---|
| Impôt QC (formule TP-1015.F) | **135,55 $** | WebRAS |
| Impôt fédéral (formule T4127) | **112,66 $** | PDOC |

### Impôts — valeurs retenues (post-exonération)

| Ligne | Valeur | Mécanisme |
|---|---|---|
| Impôt QC retenu | 0,00 $ | Court-circuit exonération TP-1015.3 |
| Impôt fédéral retenu | 0,00 $ | Court-circuit exonération TD1 |

### Retenues employé (indépendantes de l'exonération d'impôt)

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ | (1 739,92 − 129,63) × 6,30 % | **101,45 $** |
| RQAP | 1 739,92 × 0,43 % | **7,48 $** |
| AE | 1 739,92 × 1,30 % | **22,62 $** |

### Cotisations employeur

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ employeur | Identique à employé | 101,45 $ |
| RQAP employeur | 1 739,92 × 0,602 % | 10,47 $ |
| AE employeur | 22,62 × 1,4 | 31,67 $ |
| FSS | 1 739,92 × 1,65 % | 28,71 $ |
| CNESST (1,12 % — unité 57020 confirmée) | 1 739,92 × 1,12 % | 19,49 $ |

### Consolidation

| Élément | Valeur |
|---|---|
| Total retenues employé (avec exonération) | 131,55 $ |
| Total retenues employé (sans exonération) | 379,76 $ |
| **Salaire net (avec exonération)** | **1 608,37 $** |
| Salaire net (sans exonération) | 1 360,16 $ |
| Coût employeur (incl. CNESST) | 1 931,71 $ |

## Utilisation comme golden test

- **Formule impôt QC** : `calcul_impot_quebec(brut=1739,92, exoneration=False)` doit retourner 135,55 $
- **Formule impôt féd.** : `calcul_impot_federal(brut=1739,92, exoneration=False)` doit retourner 112,66 $
- **Court-circuit** : exonération = True doit retourner 0,00 $ sans invoquer la formule
- **RRQ, RQAP, AE, FSS, cotisations employeur** : au cent près
