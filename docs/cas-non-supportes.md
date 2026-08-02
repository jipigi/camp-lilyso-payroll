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

## Procédure d'ajout d'un cas supporté

Si un cas listé ici devient nécessaire :

1. Le retirer de ce document et l'ajouter à la matrice de la règle `03-perimetre-camp-lilyso.md`
2. Créer une spec Kiro dédiée
3. Ajouter au moins un scénario `QCxxx` avec référence WebRAS/ARC
4. Exécuter tous les scénarios existants pour vérifier l'absence de régression
5. Documenter la date de l'ajout dans `docs/journal-validation.md`
