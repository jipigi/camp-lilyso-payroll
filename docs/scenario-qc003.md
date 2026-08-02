# Scénario de référence QC003

Paie #1 réelle anonymisée d'un employé du corpus Camp LilySO — brut haut-intermédiaire. Utilisé pour valider la formule d'impôt QC/fédéral à ce niveau et le court-circuit d'exonération.

## Contexte

| Élément | Valeur |
|---|---|
| Identifiant | QC003 |
| Nature | Paie réelle anonymisée (EMP002 dans `intake/`) |
| Année fiscale | 2026 |
| Province de travail | Québec |
| Fréquence de paie | Aux deux semaines (27 périodes en 2026) |
| Position dans la saison | Paie 1 |
| Date de paiement | 2026-07-29 |
| Titre d'emploi | Moniteur sauveteur |
| Taux horaire | 16,00 $ |
| Heures normales / heures supp | 116 / 10 |
| **Exonération TP-1015.3 (impôt QC)** | **Cochée** |
| **Exonération TD1 (impôt fédéral)** | **Cochée** |

## Décomposition du brut

| Ligne | Montant |
|---|---|
| Salaire régulier (116 h × 16 + 10 h × 24) | 2 096,00 $ |
| Vacances 4 % | 83,84 $ |
| **Salaire brut** | **2 179,84 $** |

## Résultats officiels

### Impôts — valeurs formule (WebRAS et PDOC pré-exonération)

| Ligne | Valeur | Source |
|---|---|---|
| Impôt QC (formule TP-1015.F) | **201,17 $** | WebRAS |
| Impôt fédéral (formule T4127) | **173,35 $** | PDOC |

### Impôts — valeurs retenues (post-exonération)

| Ligne | Valeur | Mécanisme |
|---|---|---|
| Impôt QC retenu | 0,00 $ | Court-circuit exonération TP-1015.3 |
| Impôt fédéral retenu | 0,00 $ | Court-circuit exonération TD1 |

### Retenues employé (indépendantes de l'exonération d'impôt)

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ | (2 179,84 − 129,63) × 6,30 % | **129,16 $** |
| RQAP | 2 179,84 × 0,43 % | **9,37 $** |
| AE | 2 179,84 × 1,30 % | **28,34 $** |

### Cotisations employeur

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ employeur | Identique à employé | 129,16 $ |
| RQAP employeur | 2 179,84 × 0,602 % | 13,12 $ |
| AE employeur | 28,34 × 1,4 | 39,68 $ |
| FSS | 2 179,84 × 1,65 % | 35,97 $ |
| CNESST (1,12 % — unité 57020 confirmée) | 2 179,84 × 1,12 % | 24,41 $ |

### Consolidation

| Élément | Valeur |
|---|---|
| Total retenues employé (avec exonération) | 166,87 $ |
| Total retenues employé (sans exonération) | 541,39 $ |
| **Salaire net (avec exonération)** | **2 012,97 $** |
| Salaire net (sans exonération) | 1 638,45 $ |
| Coût employeur (incl. CNESST) | 2 422,34 $ |

## Utilisation comme golden test

- **Formule impôt QC** : `calcul_impot_quebec(brut=2179,84, exoneration=False)` doit retourner 201,17 $
- **Formule impôt féd.** : `calcul_impot_federal(brut=2179,84, exoneration=False)` doit retourner 173,35 $
- **Court-circuit** : exonération = True doit retourner 0,00 $ sans invoquer la formule
- **RRQ, RQAP, AE, FSS, cotisations employeur** : au cent près
