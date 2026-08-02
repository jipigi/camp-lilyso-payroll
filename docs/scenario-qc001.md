# Scénario de référence QC001

Scénario **synthétique** (employé fictif de test) exécuté dans WebRAS et PDOC pour valider le corpus complet des formules 2026. Le seul cas du corpus où aucune exonération d'impôt n'est appliquée — donc le seul qui valide les formules d'impôt QC et d'impôt fédéral.

Toutes les valeurs ci-dessous sont issues d'une exécution WebRAS et PDOC datée de la mise en place initiale du projet.

## Contexte

| Élément | Valeur |
|---|---|
| Identifiant | QC001 |
| Nature | Synthétique — employé fictif de test |
| Année fiscale | 2026 |
| Province de travail | Québec |
| Fréquence de paie | Aux deux semaines |
| Nombre de périodes de paie dans l'année | **27** |
| Position dans la saison | Paie 1 (aucun cumul YTD antérieur) |
| Date de paiement de référence | 2026-07-29 |

## Entrées WebRAS

| Champ WebRAS | Valeur |
|---|---|
| Nombre de périodes de paie | Aux deux semaines (27) |
| Période de paie courante | 1 |
| Salaire (brut de la période, vacances incluses) | 1 516,32 $ |
| Masse salariale totale annuelle de l'employeur | 14 861,60 $ |
| Montant personnel de base (crédits d'impôt personnels) | 18 952,00 $ |
| Autres champs | Valeurs par défaut |

## Entrées PDOC (Calculateur ARC)

| Champ PDOC | Valeur |
|---|---|
| Province ou territoire d'emploi | Québec |
| Fréquence des périodes de paie | Aux deux semaines (27 périodes par année) |
| Date à laquelle l'employé est rémunéré | 2026-07-29 |
| Revenu de salaires ou de traitement par période de paie | 1 458,00 $ |
| Paie de vacances | 58,32 $ (soit 4 % × 1 458,00 $) |
| Montant total du formulaire TD1 fédéral | 16 452,00 $ |
| Traitement RRQ | Exemption au RRQ (option PDOC standard pour employé QC cotisant au RRQ) |
| Cumuls annuels AE (gains assurables et cotisations retenues) | 0,00 $ (paie 1) |
| Autres champs | Valeurs par défaut |

**Note importante** : ni WebRAS ni PDOC ne proposent de case à cocher « exonération de la retenue d'impôt ». L'exonération signalée sur les formulaires TP-1015.3 et TD1 est appliquée en aval par l'employeur (impôt retenu = 0 par décision), et n'est pas une entrée des calculateurs officiels. Pour QC001, aucune exonération n'est active — les calculateurs produisent l'impôt selon la formule normale.

## Résultats officiels

### WebRAS — Revenus et impôt QC

| Ligne | Valeur |
|---|---|
| Revenu brut de la période | 1 516,32 $ |
| Revenu imposable (base impôt QC) | 1 448,75 $ |
| **Impôt du Québec sur le revenu brut** | **104,56 $** |

### WebRAS — Retenues employé

| Cotisation | Taux | Montant |
|---|---|---|
| RRQ | 6,30 % | **87,36 $** |
| Deuxième cotisation supplémentaire au RRQ (RRQ2) | 4,00 % | 0,00 $ |
| RQAP | 0,43 % | **6,52 $** |

### WebRAS — Cotisations employeur

| Cotisation | Taux | Montant |
|---|---|---|
| RRQ (employeur) | 6,30 % | 87,36 $ |
| Deuxième cotisation supplémentaire au RRQ (RRQ2 employeur) | 4,00 % | 0,00 $ |
| RQAP (employeur) | 0,602 % | 9,13 $ |
| FSS | 1,65 % | 25,02 $ |

### PDOC — Impôt fédéral et AE

| Ligne | Valeur |
|---|---|
| Revenu imposable pour la période de paie (base impôt fédéral) | 1 502,45 $ |
| **Retenue d'impôt fédéral** | **86,25 $** |
| **Retenues pour l'AE** | **19,71 $** |
| Retenues pour le RRQ (rappel, calculé aussi par PDOC) | 87,36 $ |
| Retenues pour le RRQ2 | 0,00 $ |
| Total des retenues (PDOC, excl. impôt QC) | 193,32 $ |
| Montant net (PDOC, excl. impôt QC) | 1 323,00 $ |

### PDOC — Information supplémentaire

| Ligne | Valeur |
|---|---|
| Retenues des cotisations supplémentaires du RRQ (portion déductible fédéralement) | 13,87 $ |
| Gains ouvrant droit à pension pour la période | 1 516,32 $ |
| Gains assurables pour la période | 1 516,32 $ |

**Interprétation de la cotisation supplémentaire au RRQ** : la portion de 13,87 $ (= 1 % × (brut − exemption)) est incluse dans la cotisation totale RRQ de 87,36 $, mais elle est traitée fédéralement comme une **déduction du revenu imposable** plutôt qu'un crédit d'impôt. C'est pourquoi le revenu imposable fédéral PDOC (1 502,45 $) = brut − 13,87 $. La portion restante (73,49 $) donne droit à un crédit non remboursable fédéral standard. Ce mécanisme devra être reproduit dans le module `impot-federal`.

## Résultats consolidés (calculés)

| Élément | Valeur |
|---|---|
| **Salaire brut** | **1 516,32 $** |
| Salaire régulier (déduit) | 1 458,00 $ |
| Vacances 4 % | 58,32 $ |
| **Total retenues employé** | **304,40 $** |
| - Impôt QC | 104,56 $ |
| - Impôt fédéral | 86,25 $ |
| - RRQ | 87,36 $ |
| - RQAP | 6,52 $ |
| - AE | 19,71 $ |
| **Salaire net** | **1 211,92 $** |
| **Total charges patronales (excl. CNESST, CNT)** | **149,10 $** |
| - RRQ employeur | 87,36 $ |
| - RQAP employeur | 9,13 $ |
| - AE employeur (calculé : 19,71 × 1,4) | 27,59 $ |
| - FSS | 25,02 $ |
| CNESST (1,12 % — unité 57020 confirmée) | 16,98 $ |
| **Coût employeur total** (brut + charges) | **1 683,04 $** (incl. CNESST) |

## Utilisation comme golden test

Ce scénario devient plusieurs tests automatiques :

```python
# tests/test_reference_qc001.py

BRUT_QC001 = Decimal("1516.32")

def test_qc001_rrq_employe():
    resultat, trace = calcul_rrq_employe(
        salaire_periode=BRUT_QC001,
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annee=27,
        cumul_rrq_ytd=Decimal("0.00"),
        parametres=charger_parametres(2026, "quebec").rrq,
    )
    assert resultat == Decimal("87.36")
    assert "TP-1015.F 2026" in trace.source

def test_qc001_rqap_employe():
    resultat, _ = calcul_rqap_employe(BRUT_QC001, parametres_2026_qc().rqap)
    assert resultat == Decimal("6.52")

def test_qc001_ae_employe():
    resultat, _ = calcul_ae_employe(BRUT_QC001, parametres_2026_ca().assurance_emploi)
    assert resultat == Decimal("19.71")

def test_qc001_impot_quebec():
    resultat, _ = calcul_impot_quebec(
        brut_periode=BRUT_QC001,
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annee=27,
        credits_tp1015_3=Decimal("18952.00"),
        exoneration=False,
        retenue_additionnelle=Decimal("0.00"),
        parametres=charger_parametres(2026, "quebec"),
    )
    assert resultat == Decimal("104.56")

def test_qc001_impot_federal():
    resultat, _ = calcul_impot_federal(
        brut_periode=BRUT_QC001,
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annee=27,
        credits_td1=Decimal("16452.00"),
        exoneration=False,
        retenue_additionnelle=Decimal("0.00"),
        parametres=charger_parametres(2026, "canada"),
    )
    assert resultat == Decimal("86.25")
```

## Archivage de la référence

À placer dans `intake/captures-officielles/QC001/` (dossier local, gitignoré) :

- Capture PDF de la session WebRAS avec les entrées et résultats visibles
- Capture PDF de la session PDOC avec les entrées et résultats visibles

## Statut

- [x] Entrées WebRAS et PDOC documentées
- [x] Impôt QC obtenu de WebRAS : 104,56 $
- [x] Impôt fédéral obtenu de PDOC : 86,25 $
- [x] RRQ, RQAP, AE, RRQ employeur, RQAP employeur, FSS validés au cent près
- [x] Formule RRQ (27 périodes, exemption 3 500 / 27 = 129,63) confirmée
- [x] Cotisation supplémentaire au RRQ (1 % pour déduction fédérale) identifiée
- [ ] Fichier de fixture PDF archivé dans `intake/captures-officielles/QC001/`
- [ ] Tests automatiques en place (à créer une fois le moteur implémenté)
