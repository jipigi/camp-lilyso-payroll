# Hypothèses de travail — Saison 2026

Ce document consigne les paramètres et hypothèses adoptés pour la saison 2026. Chaque ligne indique la source de vérité et le statut de validation.

**Conventions de statut** :

- `VALIDE_WEBRAS` : valeur reproduite au cent près par WebRAS sur au moins un scénario documenté du corpus (`docs/scenario-qc*.md`).
- `VALIDE_PDOC` : valeur reproduite au cent près par PDOC (Calculateur ARC) sur au moins un scénario documenté.
- `HYPOTHESE` : valeur adoptée par décision projet en attendant confirmation.
- `TO_CONFIRM` : à vérifier dans la source officielle (TP-1015.F 2026, T4127 2026) avant utilisation en production.
- `EN_ATTENTE` : dépend d'un événement externe (ex. décision de classification CNESST).

## 1. Employeur

| Élément | Valeur | Statut |
|---|---|---|
| Raison sociale | Camp LilySO (OBNL) | Interne |
| Province de travail | Québec | Décision projet |
| Fréquence de paie | Aux deux semaines | Décision employeur |
| Nombre de paies par saison | 3 | Décision employeur |
| **Nombre de paies bi-hebdomadaires 2026 (pour annualisation fiscale)** | **27** | **VALIDE_WEBRAS et VALIDE_PDOC** |
| Nombre de paies bi-hebdomadaires années standard | 26 | À réévaluer chaque année |
| Réduction du taux AE employeur | Aucune | OBNL sans régime d'assurance salaire admissible |
| Multiplicateur AE employeur | 1,4 | VALIDE_PDOC (règle standard fédérale) |
| Masse salariale totale annuelle 2026 (utilisée par WebRAS) | 14 861,60 $ | Estimée pour paramétrer WebRAS (impacte le taux FSS) |
| Fréquence de versement des remises | `TO_CONFIRM` selon masse salariale | Revenu Québec / ARC |

## 2. RRQ (Régime de rentes du Québec)

Source : TP-1015.F 2026, section RRQ.

| Paramètre | Valeur | Statut |
|---|---|---|
| Taux de cotisation totale employé (base + première suppl.) | **6,30 %** | **VALIDE_WEBRAS** |
| Taux de cotisation totale employeur | **6,30 %** | **VALIDE_WEBRAS** |
| Taux deuxième cotisation supplémentaire (RRQ2) — employé et employeur | **4,00 %** | **VALIDE_WEBRAS** (aucun cas Camp LilySO ne l'atteint) |
| Exemption générale annuelle | **3 500,00 $** | **VALIDE_WEBRAS** |
| Exemption par période (aux 2 semaines / 27 périodes 2026) | **129,63 $** ( = 3 500 ÷ 27 ) | **VALIDE_WEBRAS** (6 vérifications indépendantes) |
| Portion « cotisation supplémentaire » déductible fédéralement | **1,00 %** × (brut − exemption) | **VALIDE_PDOC** |
| Maximum des gains admissibles (MGA) | `TO_CONFIRM` | TP-1015.F 2026 |
| Maximum supplémentaire des gains admissibles (MSGA) | `TO_CONFIRM` | TP-1015.F 2026 |
| Cotisation maximale annuelle employé (base) | `TO_CONFIRM` | TP-1015.F 2026 |

**Note** : la deuxième cotisation supplémentaire (RRQ2, 4 %) ne s'applique qu'aux gains entre MGA et MSGA. Aucun scénario Camp LilySO ne s'en approche.

## 3. RQAP (Régime québécois d'assurance parentale)

Source : TP-1015.F 2026, section RQAP.

| Paramètre | Valeur | Statut |
|---|---|---|
| Taux employé | **0,43 %** | **VALIDE_WEBRAS** |
| Taux employeur | **0,602 %** | **VALIDE_WEBRAS** |
| Maximum des gains assurables | `TO_CONFIRM` | TP-1015.F 2026 |
| Cotisation maximale employé | `TO_CONFIRM` (WebRAS avait mentionné 442,90 $ initialement) | TP-1015.F 2026 |

## 4. Assurance-emploi (AE) — Québec

Source : T4127 2026.

| Paramètre | Valeur | Statut |
|---|---|---|
| Taux employé (résidents QC) | **1,30 %** | **VALIDE_PDOC** |
| Multiplicateur employeur | **1,4** | **VALIDE_PDOC** |
| Maximum des gains assurables | `TO_CONFIRM` | T4127 2026 |
| Cotisation maximale employé | `TO_CONFIRM` | T4127 2026 |

## 5. Impôt du Québec

Source : TP-1015.F 2026.

| Paramètre | Valeur | Statut |
|---|---|---|
| Montant personnel de base (2026, cas courant) | **18 952,00 $** | À vérifier au TP-1015.F 2026 |
| Formule de retenue | Formules officielles TP-1015.F | À implémenter selon guide |
| Exonération de la retenue (option employeur, hors WebRAS) | Supportée par le moteur | Court-circuit en amont |
| Retenue additionnelle demandée par l'employé | Supportée | TP-1015.3 |
| Golden values disponibles | QC001 : brut 1 516,32 $ → impôt QC 104,56 $ | **VALIDE_WEBRAS** |
| Déduction annuelle qui réduit le brut vers le revenu imposable | ~1 825 $ annuel (à confirmer, probablement déduction pour travailleur) | `TO_CONFIRM` |
| Revenu imposable QC pour QC001 | 1 448,75 $ ( = 1 516,32 − 67,57 ) | **VALIDE_WEBRAS** |
| Retenue additionnelle plafonnée à 0 $ si insuffisance de brut (QC+fédéral combinés) | Lorsque la somme des retenues additionnelles volontaires QC + fédérale dépasse l'espace disponible sur le brut après cotisations obligatoires (RRQ, RQAP, AE) et impôt de base des deux juridictions, les DEUX retenues additionnelles sont mises à 0 $ (jamais de réduction partielle, jamais de priorité QC/fédéral) | **HYPOTHESE** — décision opérationnelle Camp LilySO, non prescrite par TP-1015.F ni T4127/T4001 de l'ARC — voir `docs/journal-validation.md` pour la recherche effectuée |

**Note sur l'exonération** : ni WebRAS ni PDOC ne proposent de case « exonération de la retenue d'impôt ». Sur les formulaires TP-1015.3 (QC) et TD1 (fédéral), l'employé peut cocher qu'il souhaite être exonéré. Dans ce cas, l'employeur décide de retenir 0 $ d'impôt sans invoquer WebRAS/PDOC pour l'impôt. Le moteur reflète ce mécanisme comme un **court-circuit** : `exoneration_qc = True → impot_qc = 0`, indépendamment du brut.

## 6. Impôt fédéral

Source : T4127 2026.

| Paramètre | Valeur | Statut |
|---|---|---|
| Montant personnel de base fédéral (2026, cas courant) | **16 452,00 $** | À vérifier au T4127 2026 |
| Formule de retenue | Formules officielles T4127 | À implémenter selon guide |
| Exonération de la retenue (option employeur, hors PDOC) | Supportée par le moteur | Court-circuit en amont |
| Retenue additionnelle demandée par l'employé | Supportée | TD1 |
| Golden values disponibles | QC001 : brut 1 516,32 $ → impôt féd. 86,25 $ | **VALIDE_PDOC** |
| Portion RRQ déduite avant calcul impôt féd. | 1 % × (brut − exemption RRQ pp) | **VALIDE_PDOC** |
| Revenu imposable fédéral pour QC001 | 1 502,45 $ ( = 1 516,32 − 13,87 ) | **VALIDE_PDOC** |
| Retenue additionnelle plafonnée à 0 $ si insuffisance de brut (QC+fédéral combinés) | Lorsque la somme des retenues additionnelles volontaires QC + fédérale dépasse l'espace disponible sur le brut après cotisations obligatoires (RRQ, RQAP, AE) et impôt de base des deux juridictions, les DEUX retenues additionnelles sont mises à 0 $ (jamais de réduction partielle, jamais de priorité QC/fédéral) | **HYPOTHESE** — décision opérationnelle Camp LilySO, non prescrite par TP-1015.F ni T4127/T4001 de l'ARC — voir `docs/journal-validation.md` pour la recherche effectuée |

## 7. Charges patronales autres

### FSS (Fonds des services de santé)

| Paramètre | Valeur | Statut |
|---|---|---|
| Taux applicable à Camp LilySO 2026 (masse salariale 14 861,60 $) | **1,65 %** | **VALIDE_WEBRAS** |
| Table complète des taux par tranche de masse salariale | `TO_CONFIRM` | Table FSS annuelle |

### CNESST — Camp de jour

| Paramètre | Valeur | Statut |
|---|---|---|
| Unité de classification | 57020 | **VALIDE_OFFICIEL** (décision CNESST reçue) |
| Taux CNI (net) | 0,90 % | **VALIDE_OFFICIEL** |
| Taux d'unité | 0,22 % | **VALIDE_OFFICIEL** |
| **Taux total** | **1,12 %** | **VALIDE_OFFICIEL** |
| Drapeau `en_attente_classification` du modèle | `false` pour Camp LilySO 2026 | Modèle conservé pour d'autres employeurs éventuels ou années futures |

### CNT (Cotisation relative aux normes du travail)

| Paramètre | Valeur | Statut |
|---|---|---|
| Taux | `TO_CONFIRM` | Guide CNT annuel |
| Traitement | Charge patronale annuelle, hors bulletin employé | Règle 03 |

## 8. Vacances

| Paramètre | Valeur | Notes |
|---|---|---|
| Taux d'indemnité pour tous les employés du camp | 4 % | Politique employeur |
| Mode de versement | À chaque paie | Politique employeur |
| Support d'un taux de 6 % | Prévu comme option | Extensibilité |

## 9. Heures supplémentaires

| Paramètre | Valeur | Source |
|---|---|---|
| Seuil hebdomadaire | 40 heures par semaine | Normes du travail QC |
| Multiplicateur | 1,5 × taux horaire | Normes du travail QC |
| Base de calcul | Par semaine, jamais par période de paie | Règle métier explicite |

### Responsabilité de la classification normal / supplémentaire

Décision de conception (2026-08) : la classification des heures entre `heures_normales` et `heures_supplementaires` **relève de la saisie utilisateur**, pas du moteur.

- L'utilisateur (ou le fichier d'import) fournit directement `heures_normales` et `heures_supplementaires` **par semaine constituante**, en tenant compte du seuil de 40 h et des règles internes du camp (congés, jours fériés, gardes de nuit, etc.).
- Le moteur ne vérifie **pas** que `heures_normales ≤ 40` pour une semaine donnée. Cette contrainte n'est pas encodée dans `WeekSegment` ni dans `HeuresParSemaine`.
- Les valeurs `seuil_heures_supp_hebdo` (40) et `multiplicateur_heures_supp` (1,5) restent stockées dans `parameters/2026/quebec.json` et sont *transportées* dans `PayrollResult.gains` (Req 4.14) uniquement à des fins d'affichage sur le bulletin — pas de validation.

Justification : l'application des règles des Normes du travail dépend de circonstances (fériés, temps partiel choisi, régime particulier, entente écrite) que le moteur n'a pas à interpréter. La règle 03 (fail-fast hors matrice) s'applique aux dimensions structurelles (province, fréquence, type de rémunération) ; la classification horaire fine reste une responsabilité de l'utilisateur qui prépare la paie.

Conséquence pratique : les scénarios `QC001`–`QC006` reprennent la répartition normale/supp saisie par le camp dans son Excel de gestion. Le moteur les traite comme des faits, calcule le brut à partir de cette répartition et compare aux golden values WebRAS/PDOC obtenues sur ce même brut.

## 10. Cumuls et scission par année

| Élément | Règle |
|---|---|
| Année de cumul fiscal | Année civile (1er janvier — 31 décembre) |
| Réinitialisation des plafonds RRQ/RQAP/AE | 1er janvier de chaque année |
| Concept « saison » | Champ additionnel pour rapports OBNL, distinct de l'année fiscale |

## 11. Corrections et annulations

Décision de conception :

- Une paie produite est **immuable**
- Une correction se fait par **annulation-remplacement** (paie de contrepassation + nouvelle paie)
- Toute paie porte un `statut` : `brouillon`, `emise`, `annulee`, `remplace_par`
- Le registre maître conserve l'historique complet des versions
