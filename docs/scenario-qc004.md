# Scénario de référence QC004

Paie #1 réelle anonymisée d'un employé du corpus Camp LilySO — brut très faible, **sans exonération**. Utilisé pour valider le comportement « sous-seuil » de la formule d'impôt (impôt QC et fédéral doivent retourner 0 $ même en l'absence d'exonération, parce que le brut annualisé est inférieur au montant personnel de base).

## Contexte

| Élément | Valeur |
|---|---|
| Identifiant | QC004 |
| Nature | Paie réelle anonymisée (EMP003 dans `intake/`) |
| Année fiscale | 2026 |
| Province de travail | Québec |
| Fréquence de paie | Aux deux semaines (27 périodes en 2026) |
| Position dans la saison | Paie 1 |
| Date de paiement | 2026-07-29 |
| Titre d'emploi | Monitrice |
| Taux horaire | 14,00 $ |
| Heures normales / heures supp | 20,25 / 0 |
| **Exonération TP-1015.3 (impôt QC)** | **Non cochée** |
| **Exonération TD1 (impôt fédéral)** | **Non cochée** |

## Décomposition du brut

| Ligne | Montant |
|---|---|
| Salaire régulier (20,25 h × 14) | 283,50 $ |
| Vacances 4 % | 11,34 $ |
| **Salaire brut** | **294,84 $** |

Brut annualisé théorique : 294,84 × 27 = 7 960,68 $. Bien en dessous du montant personnel de base QC (18 952 $) et fédéral (16 452 $). Les deux formules d'impôt retournent 0 sans besoin d'exonération.

## Résultats officiels

### Impôts — valeurs formule (WebRAS et PDOC, sans exonération)

| Ligne | Valeur | Source |
|---|---|---|
| Impôt QC (formule TP-1015.F) | **0,00 $** | WebRAS |
| Impôt fédéral (formule T4127) | **0,00 $** | PDOC |

Note : ce sont bien des valeurs formule (pas de court-circuit). WebRAS et PDOC exécutent leurs formules complètes et retournent 0 $ parce que le brut annualisé n'atteint pas le seuil d'imposition.

### Retenues employé

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ | (294,84 − 129,63) × 6,30 % | **10,41 $** |
| RQAP | 294,84 × 0,43 % | **1,27 $** |
| AE | 294,84 × 1,30 % | **3,83 $** |

### Cotisations employeur

| Cotisation | Formule | Valeur |
|---|---|---|
| RRQ employeur | Identique à employé | 10,41 $ |
| RQAP employeur | 294,84 × 0,602 % | **1,77 $** (formule) — Excel corpus indique 1,78 $ (voir anomalie ci-dessous) |
| AE employeur | 3,83 × 1,4 | 5,36 $ |
| FSS | 294,84 × 1,65 % | 4,86 $ |
| CNESST (1,12 % — unité 57020 confirmée) | 294,84 × 1,12 % | 3,30 $ |

### Consolidation

| Élément | Valeur |
|---|---|
| Total retenues employé | 15,51 $ |
| **Salaire net** | **279,33 $** |
| Coût employeur (incl. CNESST) | 320,53 $ |

## Anomalie à investiguer

L'Excel du corpus indique RQAP employeur = **1,78 $** pour ce brut, alors que la formule `294,84 × 0,602 %` donne 1,7749 $ arrondi à **1,77 $** (arrondi standard « half-up »). Écart de 1 ¢. Trois hypothèses :

- Saisie manuelle erronée dans la source Excel (probable)
- Règle d'arrondissement WebRAS spécifique (peu probable — la même règle produit 9,13 sur QC001 en cohérence avec half-up)
- Ajout d'un plancher minimal quelque part (aucune trace connue dans TP-1015.F)

Action : au moment d'écrire le module `rqap`, faire tourner ce scénario en direct dans WebRAS et prendre la valeur retournée par WebRAS comme référence, pas celle de l'Excel. Consigner le résultat dans `docs/journal-validation.md`.

## Utilisation comme golden test

- **Formule impôt QC « sous seuil »** : `calcul_impot_quebec(brut=294,84, exoneration=False)` doit retourner 0,00 $ — vérifie que la formule ne produit pas un impôt négatif ou une erreur
- **Formule impôt fédéral « sous seuil »** : idem, 0,00 $
- **RRQ, RQAP employé, AE** : au cent près
- **Cas de test crucial** parce qu'il valide que la formule d'impôt retourne bien 0 quand le brut annualisé < montant personnel de base, sans passer par l'exonération
