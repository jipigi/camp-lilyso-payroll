# Règle 06 — Workflow Kiro pour le projet

**Statut :** guide de travail
**Portée :** toute nouvelle fonctionnalité ou modification du moteur

## Principe

Le développement suit strictement l'ordre : **spec → tests → implémentation → validation**. Aucun code du moteur fiscal ne DOIT être écrit avant que la spec correspondante soit rédigée et acceptée.

## Séquence pour chaque nouvelle capacité du moteur

1. **Créer une spec Kiro** avec l'atelier `feature-requirements-first-workflow`
   - Requirements : intention métier, cas supportés, exigences EARS
   - Design : formules officielles, structure de données, arrondissement, trace
   - Tasks : décomposition en étapes testables
2. **Rédiger les tests avant le code**
   - Golden tests contre WebRAS ou le calculateur ARC (résultats attendus au cent près)
   - Property-based tests (Hypothesis) pour les invariants (voir plus bas)
   - Tests de cas d'erreur (cas non supportés → `UnsupportedPayrollCase`)
3. **Implémenter jusqu'à ce que tous les tests passent**
   - Signature typée `(entrées) -> tuple[Decimal, CalculationTrace]`
   - Trace complète référençant la source officielle
4. **Valider contre les outils officiels**
   - Reproduire au moins un scénario dans WebRAS ou le calculateur ARC
   - Archiver les guides officiels dans `docs/sources-officielles/<AAAA>/` ; les captures d'exécution nominatives restent hors dépôt (`tests/fixtures/personal/`)
   - Consigner la validation dans `docs/journal-validation.md`

## Invariants à couvrir en property-based testing

Chaque module de calcul doit inclure au minimum ces propriétés :

- `net = brut - somme(retenues)` (identité comptable)
- Aucune retenue n'est négative
- Aucune retenue employé n'excède le plafond annuel de sa catégorie
- Les cumuls (RRQ, RQAP, AE, impôt) sont monotones croissants au fil des paies
- La somme des paies d'un employé sur la saison = son gain brut total
- `cout_employeur = brut + charges_patronales`
- Un cas hors matrice (règle 03) lève toujours `UnsupportedPayrollCase`

## Hooks Kiro recommandés (à créer plus tard)

- Sur sauvegarde de `payroll_engine/*.py` : exécuter `pytest` avec `-x --ff`
- Sur sauvegarde de `parameters/**/*.json` : valider le schéma et refuser `TO_FILL` en production
- Sur PR : vérifier qu'aucun `float` n'apparaît dans le diff des modules de calcul

## Spec par capacité — liste initiale prévue

1. `moteur-paie-contrats` — modèles, exceptions, trace, chargeur de paramètres
2. `gains-bruts-vacances-hs` — salaire régulier, heures supp par semaine, vacances 4 %
3. `cotisations-sociales-qc` — RRQ, RQAP et AE (employé et employeur), regroupées car formes de formule identiques (taux × gains admissibles plafonnés, cumul YTD)
4. `impots-retenues-source` — impôt QC (TP-1015.F, exonération TP-1015.3) et impôt fédéral (T4127, exonération TD1), regroupées car formes de formule identiques (paliers progressifs, exonération, retenue additionnelle)
5. `charges-patronales` — FSS, CNESST, CNT
6. `net-cumuls-registre` — assemblage, cumuls YTD, registre maître
7. `interface-streamlit` — saisie et affichage (avant le bulletin PDF, à la demande du projet)
8. `bulletin-pdf` — génération du bulletin PDF, intégrée à l'interface livrée à l'étape 7

## Discipline générale

- Ne jamais devancer une spec (« je code déjà un peu pour voir »)
- Ne jamais écrire un test qui ne se réfère pas à une source officielle
- Ne jamais fusionner du code sans que `pytest` passe entièrement
- Ne jamais toucher aux paramètres d'une année passée (immutabilité historique)
