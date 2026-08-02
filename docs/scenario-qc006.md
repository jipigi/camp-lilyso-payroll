# Scénario de référence QC006

Paie #1 réelle anonymisée d'un employé du corpus Camp LilySO — brut faible, avec exonération. Utilisé pour valider deux comportements simultanés : (1) la formule d'impôt retourne 0 $ pour un brut annualisé sous le seuil, et (2) le court-circuit d'exonération.

## Contexte

| Élément | Valeur |
|---|---|
| Identifiant | QC006 |
| Nature | Paie réelle anonymisée (EMP005 dans `intake/`) |
| Année fiscale | 2026 |
| Province de travail | Québec |
| Fréquence de paie | Aux deux semaines (27 périodes en 2026) |
| Position dans la saison | Paie 1 |
| Date de paiement | 2026-07-29 |
| Titre d'emploi | Assistante monitrice |
| Taux horaire | 12,00 $ |
| Heures normales / heures supp | 40,5 / 0 |
| **Exonération TP-1015.3 (impôt QC)** | **Cochée** |
| **Exonération TD1 (impôt fédéral)** | **Cochée** |

## Décomposition du brut

| Ligne | Montant |
|---|---|
| Salaire régulier (40,5 h × 12) | 486,00 $ |
| Vacances 4 % | 19,44 $ |
| **Salaire brut** | **505,44 $** |

Brut annualisé théorique : 505,44 × 27 = 13 646,88 $. Sous le montant personnel de base QC (18 952 $) et fédéral (16 452 $). Les formules d'impôt retournent 0 $ même sans exonération.

## Résultats officiels

### Impôts — valeurs formule (WebRAS et PDOC pré-exonération)

| Ligne | Valeur | Source |
|---|---|---|
| Impôt QC (formule TP-1015.F, sans exonération) | **0,00 $** | WebRAS |
| Impôt fédéral (formule T4127, sans exonération) | **0,00 $** | PDOC |

Note : contrairement à QC002/QC003/QC005 où les formules produiraient un impôt positif, ici WebRAS et PDOC exécutent leur formule complète et retournent 0 $ à cause du brut annualisé sous seuil. C'est un deuxième point de validation « sous-seuil » indépendant de QC004.

### Impôts — valeurs retenues (post-exonération)

| Ligne | Valeur |
|---|---|
| Impôt QC retenu | 0,00 $ |
| Impôt fédéral retenu | 0,00 $ |

Pour QC006, les valeurs formule et les valeurs retenues coïncident à 0. Le court-circuit d'exonération produit le même résultat que la formule.

### Retenues employé

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ | (505,44 − 129,63) × 6,30 % | **23,68 $** |
| RQAP | 505,44 × 0,43 % | **2,17 $** |
| AE | 505,44 × 1,30 % | **6,57 $** |

### Cotisations employeur

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ employeur | Identique à employé | 23,68 $ |
| RQAP employeur | 505,44 × 0,602 % | 3,04 $ |
| AE employeur | 6,57 × 1,4 | 9,20 $ |
| FSS | 505,44 × 1,65 % | 8,34 $ |
| CNESST (1,12 % — unité 57020 confirmée) | 505,44 × 1,12 % | 5,66 $ |

### Consolidation

| Élément | Valeur |
|---|---|
| Total retenues employé | 32,42 $ |
| **Salaire net** | **473,02 $** |
| Coût employeur (incl. CNESST) | 555,36 $ |

## Utilisation comme golden test

- **Formule impôt QC « sous seuil »** : `calcul_impot_quebec(brut=505,44, exoneration=False)` doit retourner 0,00 $
- **Formule impôt fédéral « sous seuil »** : `calcul_impot_federal(brut=505,44, exoneration=False)` doit retourner 0,00 $
- **Court-circuit d'exonération** : exonération = True doit également retourner 0,00 $ sans invoquer la formule (invariant : les deux chemins produisent le même résultat)
- **RRQ, RQAP, AE, FSS, cotisations employeur** : au cent près
