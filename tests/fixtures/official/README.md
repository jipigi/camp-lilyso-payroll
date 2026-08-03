# Guides fiscaux officiels (référence de validation des paramètres)

Ce dossier archive les guides officiels utilisés pour **valider les valeurs**
des fichiers `parameters/<AAAA>/*.json` (règle 05 : source unique de vérité).

## Fichiers attendus

| Fichier | Source | Valide |
|---|---|---|
| `tp-1015-f-2026.pdf` | Revenu Québec — TP-1015.F 2026 | `parameters/2026/quebec.json` (section `impot_quebec`) : paliers, `taux_credits_convertibles`, `deduction_pour_travailleur_annuelle`, `montant_personnel_base` |
| `t4127-2026.pdf` | ARC — T4127 122e édition (en vigueur 2026-01-01) | `parameters/2026/canada.json` (section `impot_federal`) : paliers + constantes K (Table 8.1), CEA (Table 8.2), plafond RRQ de base (Table 8.4), abattement du Québec (Table 8.2) |

## Points à confirmer en priorité

- **`deduction_pour_travailleur_annuelle`** (quebec.json) : actuellement
  `1448.50 $`, valeur *calibrée* dans la plage `[1448.32 ; 1448.67]` qui
  reproduit WebRAS au cent sur QC001/QC002/QC003/QC005. À confronter au plafond
  officiel « déduction pour un travailleur » 2026 du TP-1015.F.
- Paliers QC et fédéraux, constantes K, CEA (1 501 $), plafond RRQ de base
  (3 768,30 $), abattement (16,5 %).

## Règle 04 — données sensibles

Ces guides sont des documents publics : aucune donnée personnelle. Rien à
caviarder. (Les captures de calcul nominatives, elles, ne doivent jamais être
committées — voir règle 04.)

## Traçabilité

Toute validation faite à partir de ces guides est consignée dans
`docs/journal-validation.md`.
