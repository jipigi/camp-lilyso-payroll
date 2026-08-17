"""Synchronisation optionnelle vers un stockage objet S3-compatible (Backblaze B2).

Contexte : le système de fichiers de Streamlit Community Cloud est
**éphémère** — tout fichier écrit localement (`payroll.db`,
`employees.json`, `coordonnees.json`) est perdu au prochain redémarrage
du conteneur (mise en veille après inactivité, redéploiement). Ce module
ajoute une synchronisation *best-effort* vers un bucket S3-compatible
(Backblaze B2, testé ; tout endpoint compatible S3 fonctionnerait) pour
que ces fichiers survivent aux redémarrages du conteneur.

**Strictement opt-in, no-op par défaut** : ce module ne fait rien tant
que la section ``[b2]`` n'est pas présente dans ``st.secrets`` (fichier
``.streamlit/secrets.toml`` en local, jamais commité — voir
``.gitignore`` — ou boîte "Secrets" de Streamlit Community Cloud en
production). En l'absence de cette configuration (cas nominal des
environnements de développement et de test), :func:`telecharger_si_absent`
et :func:`televerser` sont des no-op silencieux — **aucun changement de
comportement** pour l'exécution locale ni pour la suite `pytest`
(règle 04 : tests exclusivement sur `tmp_path`/`:memory:`, jamais de
réseau).

**Avertissement (règle 04)** : si un développeur crée délibérément un
``.streamlit/secrets.toml`` local avec une section ``[b2]`` valide pour
tester cette intégration avant déploiement, toute exécution de `pytest`
dans ce même environnement déclenchera également des tentatives de
synchronisation réelle vers le bucket configuré (les fichiers de test
utilisent des chemins `tmp_path` réels, pas `:memory:`, donc le filtre
`chemin != ":memory:"` ne les exclut pas). Ne jamais laisser un
``[b2]`` configuré localement pendant une session de développement
courante — le retirer (ou renommer temporairement le fichier) avant de
lancer la suite de tests.

**Format attendu de ``st.secrets["b2"]``** :

```toml
[b2]
key_id = "..."
application_key = "..."
bucket = "CampLilySO"
endpoint = "s3.ca-east-006.backblazeb2.com"
```

Chaque fichier synchronisé (``payroll.db``, ``employees.json``,
``coordonnees.json``) est stocké sous son seul nom de fichier
(``chemin.name``) comme clé d'objet S3 — espace de noms plat, un bucket
dédié à cette application (Req règle 04 : aucune donnée personnelle
codée en dur ni committée, uniquement des identifiants d'accès lus
depuis ``st.secrets``).

Toute erreur réseau ou de configuration est capturée et journalisée
(``print``, visible dans les logs Streamlit Cloud) sans jamais lever
d'exception ni interrompre l'opération locale déjà réussie (écriture
disque/SQLite) — la synchronisation distante est un complément
*best-effort*, pas une garantie transactionnelle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Garde-fou pour n'émettre qu'une seule fois par processus le log
#: d'avertissement "section [b2] absente/inaccessible" (voir
#: :func:`_config_b2`) — une liste à un élément plutôt qu'une variable
#: globale simple, pour rester mutable depuis l'intérieur de la fonction
#: sans `global`.
_AVERTISSEMENT_CONFIG_DEJA_EMIS = [False]


def _config_b2() -> dict[str, Any] | None:
    """Retourne la configuration ``[b2]`` de ``st.secrets``, ou ``None``.

    ``None`` si Streamlit n'est pas installé, si aucun
    ``secrets.toml`` n'existe, ou si la section ``[b2]`` est absente —
    dans tous ces cas, ce module reste un no-op complet (voir docstring
    de module).
    """
    try:
        import streamlit as st
    except ImportError:
        # Streamlit non installé (environnement de test/CI sans le groupe
        # optionnel `ui`) — cas nominal silencieux, aucun log.
        return None

    try:
        config = dict(st.secrets["b2"])
    except Exception as exc:
        # Toute autre situation (absence de `secrets.toml`, section
        # `[b2]` absente, `st.secrets` mal formé) est journalisée une
        # seule fois par processus — utile pour diagnostiquer, via les
        # logs Streamlit Cloud, un problème de configuration des
        # Secrets, sans spammer les exécutions locales/tests répétées ni
        # lever d'exception vers l'appelant (comportement no-op
        # préservé).
        if not _AVERTISSEMENT_CONFIG_DEJA_EMIS[0]:
            _AVERTISSEMENT_CONFIG_DEJA_EMIS[0] = True
            print(
                f"[stockage_distant] Section [b2] absente/inaccessible de "
                f"st.secrets — synchronisation distante désactivée pour cette "
                f"session : {exc!r}",
                flush=True,
            )
        return None

    if not _AVERTISSEMENT_CONFIG_DEJA_EMIS[0]:
        _AVERTISSEMENT_CONFIG_DEJA_EMIS[0] = True
        print(
            f"[stockage_distant] Section [b2] trouvée dans st.secrets — "
            f"bucket={config.get('bucket')!r}, endpoint={config.get('endpoint')!r}.",
            flush=True,
        )
    return config


def _client_et_bucket() -> tuple[Any, str] | None:
    """Construit le client ``boto3`` S3-compatible, ou ``None`` si inactif.

    ``boto3`` n'est importé que si une configuration ``[b2]`` valide est
    trouvée — aucune dépendance dure sur ``boto3`` pour les
    environnements où la synchronisation distante n'est jamais activée
    (développement local, tests).
    """
    config = _config_b2()
    if config is None:
        return None
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{config['endpoint']}",
            aws_access_key_id=config["key_id"],
            aws_secret_access_key=config["application_key"],
            # Backblaze B2 (API S3-compatible) exige l'adressage "path"
            # (`endpoint/bucket/clé`) plutôt que le style "virtual-hosted"
            # par défaut de boto3 (`bucket.endpoint/clé`) — sans ce
            # réglage, la connexion est fermée par le serveur avant toute
            # réponse valide (constaté lors des tests de connectivité).
            # `signature_version="s3v4"` est également requis par B2.
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )
        return client, config["bucket"]
    except Exception as exc:
        print(
            f"[stockage_distant] Configuration B2 invalide, ignorée : {exc}",
            flush=True,
        )
        return None


def telecharger_si_absent(chemin: Path) -> None:
    """Télécharge ``chemin`` depuis le bucket s'il est absent localement.

    No-op si ``chemin`` existe déjà localement, si la synchronisation
    n'est pas configurée, ou si aucun objet distant ne porte ce nom
    (cas nominal du tout premier démarrage — le fichier local sera alors
    créé normalement par l'appelant, ex. schéma SQLite/annuaire JSON
    vide).
    """
    if chemin.exists():
        return
    resultat = _client_et_bucket()
    if resultat is None:
        return
    client, bucket = resultat
    chemin.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, chemin.name, str(chemin))
        print(
            f"[stockage_distant] '{chemin.name}' retéléchargé depuis le "
            f"bucket '{bucket}'.",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[stockage_distant] Téléchargement de '{chemin.name}' impossible "
            f"(objet distant absent ou erreur réseau) — poursuite avec un "
            f"fichier local neuf : {exc}",
            flush=True,
        )


def televerser(chemin: Path) -> None:
    """Téléverse ``chemin`` vers le bucket — no-op si non configuré.

    Best-effort : toute erreur est journalisée sans jamais interrompre
    l'appelant (l'écriture locale a déjà réussi avant cet appel).
    """
    resultat = _client_et_bucket()
    if resultat is None:
        return
    client, bucket = resultat
    try:
        client.upload_file(str(chemin), bucket, chemin.name)
        print(
            f"[stockage_distant] '{chemin.name}' téléversé vers le bucket "
            f"'{bucket}'.",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[stockage_distant] Téléversement de '{chemin.name}' échoué "
            f"(l'écriture locale reste valide pour cette session) : {exc}",
            flush=True,
        )
