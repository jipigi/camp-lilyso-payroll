# Règle 04 — Données sensibles

**Statut :** absolue, non négociable
**Portée :** dépôt Git, GitHub, prompts Kiro, tests, documentation

## Règle

Aucune donnée personnelle réelle d'employé, de conjoint ou de personne à charge ne DOIT jamais apparaître dans :

- le dépôt Git (fichiers versionnés OU historique)
- GitHub ou toute autre plateforme distante
- les prompts envoyés à Kiro
- les tests automatisés
- la documentation
- les logs de développement

## Données interdites dans le dépôt

- Numéro d'assurance sociale (NAS) réel
- Numéro de compte bancaire, transit, institution
- Adresse personnelle complète
- Date de naissance réelle si combinée à un nom
- Nom complet réel d'un salarié
- Photocopies ou scans de TD1 réels
- Photocopies ou scans de TP-1015.3 réels
- Bulletins de paie réels
- Toute pièce justificative gouvernementale nominative

## Convention pour les tests et exemples

Utiliser des identifiants fictifs et anonymisés :

```python
EMPLOYE_TEST_QC001 = Employee(
    id="EMP001",
    nom_affichage="Employé Test QC001",
    date_naissance=date(2005, 6, 15),   # fictive
    nas=None,                            # jamais stocké dans les tests
)
```

Nommer les scénarios de référence par code (ex. `QC001`, `QC002`) plutôt que par personne.

## Base de données locale

La base SQLite contenant les vraies données des salariés du camp DOIT :

- résider hors du dossier versionné (ex. `%APPDATA%\CampLilySO\payroll.db`)
- être exclue explicitement par `.gitignore` même si elle apparaît dans le dossier
- être sauvegardée par l'utilisateur en dehors du contrôle de version
- ne jamais être copiée dans les fixtures de test

## Vérification

- `.gitignore` exclut `*.db`, `data/`, `.env`, `secrets/`, `personal/`
- Un test de garde vérifie qu'aucun fichier `*.db` n'est présent dans l'arbre versionné
- Avant tout commit, revue manuelle : les diffs ne contiennent aucune donnée nominative réelle

## En cas de fuite accidentelle

Si des données réelles sont commises par erreur :

1. Arrêter immédiatement toute action sur le dépôt
2. Ne PAS pousser vers GitHub
3. Réécrire l'historique local (`git filter-repo` ou équivalent)
4. Si déjà poussé : rotation des données concernées (nouveau compte bancaire, etc.) et notification aux personnes affectées
