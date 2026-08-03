# Cas non supportés

Ce document formalise, comme un contrat, les situations que l'application refuse de traiter. Toute entrée correspondant à un cas listé ci-dessous DOIT provoquer une exception `UnsupportedPayrollCase` avec un message actionnable renvoyant l'utilisateur vers WebRAS ou le calculateur ARC.

Voir également la règle de steering `03-perimetre-camp-lilyso.md`.

## Matrice de décision

| Dimension | Supporté | Non supporté |
|---|---|---|
| Province de travail | Québec | Ontario, Alberta, Nouveau-Brunswick, TNL, IPÉ, N.-É., Manitoba, Saskatchewan, C.-B., Yukon, TNO, Nunavut |
| Type d'emploi | Salarié saisonnier à durée déterminée | Travailleur autonome, consultant, entrepreneur, sous-traitant |
| Mode de rémunération | Horaire | Salaire annuel, commission, rendement, tarif journalier, forfait |
| Bonis | Aucun dans MVP | Bonis discrétionnaires, bonis contractuels, prime de performance |
| Vacances | 4 % (ou 6 % en option) versées à chaque paie | Vacances accumulées puis payées en fin de saison, banque de vacances complexe |
| Fréquence de paie | Aux deux semaines | Hebdomadaire, semi-mensuelle, mensuelle, 22 périodes, 27 périodes |
| Régime de retraite | RRQ | RPC (autres provinces), régime privé, REER collectif, fonds de pension |
| Assurance-emploi | Taux Québec, multiplicateur employeur 1,4 | Taux hors-Québec, réduction du taux employeur (aucune ne s'applique) |
| Jours fériés | Champ manuel dans MVP | Calcul automatique selon formule légale (hors périmètre v1) |
| Impôt QC | TP-1015.3 montant total + exonération + retenue additionnelle | Lignes spécialisées non couvertes par le formulaire de base |
| Impôt fédéral | TD1 montant total + exonération + retenue additionnelle | Feuilles TD1X, réductions d'impôt spécifiques |

## Types de rémunération non supportés

- Pourboires (déclarés ou attribués)
- Allocation automobile
- Utilisation personnelle d'un véhicule fourni
- Logement fourni par l'employeur
- Repas fournis par l'employeur (autres qu'exemptés)
- Assurance vie employeur au-delà des exemptions
- Options d'achat d'actions
- Rémunération en actions
- Actions accréditives ou primes d'actions
- Prêts consentis par l'employeur
- Frais de déplacement au-delà des exemptions

## Retenues et prélèvements non supportés

- Assurance collective (santé, dentaire, vie, invalidité)
- Régime privé de pension agréé (RPA)
- REER collectif ou individuel prélevé sur la paie
- Régime enregistré d'épargne-retraite collectif volontaire (RVER)
- Cotisations syndicales
- Cotisations à une association professionnelle
- Pension alimentaire (paiement par l'employeur au tribunal)
- Saisies de salaire
- Prêts remboursés à l'employeur
- Dons de charité via la paie

## Situations administratives non supportées

- Employé multi-employeurs avec exemption RRQ répartie
- Employé transféré d'une province à une autre en cours d'année
- Employé non-résident du Canada
- Résident réputé
- Employé en congé parental (RQAP administré directement)
- Employé en cessation d'emploi requérant un relevé d'emploi (v1 : à faire manuellement via l'ARC)
- Rétroactivité d'un ajustement salarial couvrant plusieurs paies
- Paie de départ, indemnité de cessation d'emploi
- Prestations d'invalidité
- Prestations de la CNESST versées via l'employeur

## Sorties administratives non supportées dans le MVP

- Génération électronique des Relevés 1
- Génération électronique des T4
- Génération électronique des relevés d'emploi (RE)
- Dépôt direct bancaire automatisé (fichier CPA 005)
- Transmission automatique aux administrations fiscales
- APIs gouvernementales (WebRAS-API, TED, XML)

## Comportement de l'application face à un cas non supporté

1. Détecter le cas à la frontière (validation des entrées)
2. Lever `UnsupportedPayrollCase` avec un message spécifique et actionnable
3. Suggérer l'outil de repli approprié (WebRAS ou calculateur ARC)
4. Journaliser le refus dans `docs/journal-validation.md` si le cas est récurrent

Exemple de message :

```
UnsupportedPayrollCase:
Rémunération à commission non supportée par l'application Camp LilySO.
Utiliser WebRAS (revenuquebec.ca/webras) et le calculateur PDOC (canada.ca/pdoc)
pour cette paie exceptionnelle, puis reporter manuellement au registre.
```

## RRQ2 — Deuxième cotisation supplémentaire au RRQ (hors périmètre)

La **deuxième cotisation supplémentaire au RRQ** (« RRQ2 »), soit un taux de
4 % appliqué aux gains admissibles compris entre le Maximum des gains
admissibles (MGA) et le Maximum supplémentaire des gains admissibles
(MSGA), est **hors périmètre** de l'application Camp LilySO. Aucune
fonction du moteur de cotisations sociales (`payroll_engine/rrq.py`) ne
calcule, n'expose ni ne lit les champs
`taux_deuxieme_cotisation_supplementaire_employe` et
`taux_deuxieme_cotisation_supplementaire_employeur` de `RRQParametres` —
ces champs restent réservés à une spec future si le périmètre Camp
LilySO devait un jour couvrir des salaires atteignant le MGA.

**Pourquoi aucun garde-fou `UnsupportedPayrollCase` supplémentaire n'est
nécessaire pour ce cas précis** : le `Plafond_Annuel_RRQ_Employe`
(`cotisation_max_annuelle_employe = 4 479,30 $`) correspond exactement au
seuil où l'Assiette_Cotisable_RRQ atteint le MGA
(`74 600 $ − 3 500 $ = 71 100 $`, et `71 100 $ × 6,30 % = 4 479,30 $`). La
cotisation RRQ employé cesse donc naturellement de croître à ce seuil,
plafonnée par le cumul annuel déjà en place (voir la fonction
`calcul_rrq_employe`) : un salarié du Camp LilySO n'atteint jamais, en
pratique, la portion de gains située au-delà du MGA où la RRQ2
s'appliquerait.

Ce comportement est documentaire uniquement — aucun test automatisé n'est
associé à cette note (revue manuelle, conformément à la règle 06).

## Procédure d'ajout d'un cas supporté

Si un cas listé ici devient nécessaire :

1. Le retirer de ce document et l'ajouter à la matrice de la règle `03-perimetre-camp-lilyso.md`
2. Créer une spec Kiro dédiée
3. Ajouter au moins un scénario `QCxxx` avec référence WebRAS/ARC
4. Exécuter tous les scénarios existants pour vérifier l'absence de régression
5. Documenter la date de l'ajout dans `docs/journal-validation.md`
