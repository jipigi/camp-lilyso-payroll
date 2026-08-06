"""Tests de garde statique de l'interface Streamlit (`app/`).

Spec de référence : ``interface-streamlit`` — section 10 (tâches 10.1
à 10.4).

Ces quatre classes de tests protègent par introspection statique
(``ast``, inspection textuelle, ``inspect.signature``) les invariants
structurels de séparation entre la couche logique métier
(``app/logique_metier/**``, aucun rendu) et la couche de rendu
(``app/main.py``, ``app/pages_ui/**``) :

- :class:`TestLogiqueMetierNaimportePasStreamlit` — Req 1.1, 1.3 (aucun
  import ``streamlit`` dans ``app/logique_metier/**``).
- :class:`TestAucunExceptGenerique` — Req 16.1 (aucun ``except
  Exception``/``except BaseException`` générique hors ``erreurs.py``).
- :class:`TestAucuneReferencePaystub` — Req 17.3 (aucune référence
  textuelle à ``paystub``).
- :class:`TestSignaturesExactesMoteur` — Req 18.3 (signatures exactes
  des six fonctions du moteur invoquées, aucun argument surnuméraire).

Patron exact repris du design ``interface-streamlit`` §Error Handling
« Test de garde — absence d'import streamlit » et sections suivantes.

Comportement attendu avant implémentation (règle 06) : pour les trois
premières classes (:class:`TestLogiqueMetierNaimportePasStreamlit`,
:class:`TestAucunExceptGenerique`, :class:`TestAucuneReferencePaystub`),
tant qu'aucun fichier de ``app/`` n'existe, ``Path.rglob("*.py")``
retourne un itérable vide — la collecte est vide mais le test reste
**vert** (aucune violation trouvée puisqu'aucun fichier n'est
parcouru). Ces trois gardes restent vertes dès leur création et après
l'implémentation des sections 12 à 26, tant que les invariants qu'elles
protègent sont respectés.

:class:`TestSignaturesExactesMoteur` est un cas particulier inverse :
une collecte vide (aucun site d'appel trouvé) ne peut prouver le
respect des signatures figées du moteur — ce test échoue donc
**explicitement et intentionnellement** tant qu'aucun site d'appel
réel n'existe sous ``app/logique_metier/`` ni ``app/pages_ui/``,
c'est-à-dire avant l'implémentation des sections 12 à 19 et 22 à 26.
Il ne devient vert qu'une fois les premiers appels réels aux six
fonctions du moteur introduits, avec des arguments conformes à leurs
signatures figées.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from payroll_engine.net_pay import assembler_paie
from payroll_engine.register import (
    inserer_paie,
    lire_cumuls_ytd,
    lire_historique_paie,
    lire_paie,
    remplacer_paie,
)

#: Racine du dépôt — deux niveaux au-dessus de ``tests/app/test_guards.py``
#: (``tests/app/`` -> ``tests/`` -> racine). Chemin robuste, indépendant du
#: répertoire d'exécution de ``pytest`` (même convention que
#: ``tests/test_guards.py::_REPO_ROOT``).
_REPO_ROOT: Path = Path(__file__).parent.parent.parent


class TestLogiqueMetierNaimportePasStreamlit:
    """Aucun import ``streamlit`` dans ``app/logique_metier/**`` (Req 1.1, 1.3).

    Parcourt tous les fichiers ``.py`` sous ``app/logique_metier/`` par
    ``ast.parse`` et vérifie l'absence de tout ``ast.Import``/
    ``ast.ImportFrom`` référençant ``streamlit`` — patron exact du
    design §Error Handling « Test de garde — absence d'import
    streamlit ». Cette garde matérialise la séparation stricte entre
    la couche logique métier (testable sans ``streamlit.testing.v1``)
    et la couche de rendu (design §Architecture, décision n° 1).

    Tant qu'aucun fichier n'existe sous ``app/logique_metier/``,
    ``rglob("*.py")`` retourne un itérable vide : la collecte est
    vide et le test reste vert (règle 06) — comportement attendu
    avant l'implémentation des sections 12 à 19.
    """

    def test_logique_metier_naimporte_pas_streamlit(self) -> None:
        """Aucun ``import streamlit``/``from streamlit import ...``."""
        for fichier in (_REPO_ROOT / "app" / "logique_metier").rglob("*.py"):
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.Import):
                    assert not any(
                        alias.name == "streamlit" for alias in noeud.names
                    ), (
                        f"{fichier.relative_to(_REPO_ROOT).as_posix()} "
                        f"importe streamlit (Req 1.1, 1.3) — ce module "
                        f"doit rester exclusivement de la logique métier."
                    )
                if isinstance(noeud, ast.ImportFrom):
                    assert noeud.module != "streamlit", (
                        f"{fichier.relative_to(_REPO_ROOT).as_posix()} "
                        f"importe depuis streamlit (Req 1.1, 1.3) — ce "
                        f"module doit rester exclusivement de la logique "
                        f"métier."
                    )

class TestAucunExceptGenerique:
    """Aucun ``except Exception``/``except BaseException`` générique hors
    ``app/logique_metier/erreurs.py`` (Req 16.1).

    Parcourt tous les fichiers ``.py`` sous ``app/`` — à l'exception
    explicite d'``app/logique_metier/erreurs.py`` — par ``ast.parse`` et
    recherche tout ``ast.ExceptHandler`` dont le ``type`` résout à
    ``Exception`` ou ``BaseException`` — patron exact du design
    §Error Handling « Test de garde — absence de except Exception ».
    Un ``except:`` nu (``type=None``) est également considéré comme
    une violation : il est encore plus permissif qu'``except
    Exception`` et contreviendrait à l'esprit de la disjonction
    stricte (design §Error Handling « Disjonction stricte »),
    ``executer_avec_capture`` (dans ``erreurs.py``, seul fichier
    exclu) étant le seul point de capture autorisé de toute la
    surface ``app/``.

    Tant qu'aucun fichier n'existe sous ``app/`` (hormis l'exclusion),
    ``rglob("*.py")`` retourne un itérable vide : la collecte est
    vide et le test reste vert (règle 06) — comportement attendu
    avant l'implémentation des sections 12 à 26.
    """

    #: Chemin relatif (POSIX) du seul fichier autorisé à contenir des
    #: ``except`` explicites sur les quatre types métier
    #: (``UnsupportedPayrollCase``, ``MissingParameterError``,
    #: ``ValueError``, ``KeyError``) — jamais ``Exception``/
    #: ``BaseException`` génériques, mais exclu par précaution du
    #: balayage de cette garde (design §Components 8).
    _FICHIER_EXCLU: str = "app/logique_metier/erreurs.py"

    def test_aucun_except_generique_hors_erreurs(self) -> None:
        """Aucun ``except Exception``/``except BaseException``/``except:`` nu."""
        for fichier in (_REPO_ROOT / "app").rglob("*.py"):
            chemin_relatif = fichier.relative_to(_REPO_ROOT).as_posix()
            if chemin_relatif == self._FICHIER_EXCLU:
                continue

            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.ExceptHandler):
                    continue

                type_handler = noeud.type
                est_generique = type_handler is None or (
                    isinstance(type_handler, ast.Name)
                    and type_handler.id in ("Exception", "BaseException")
                )
                assert not est_generique, (
                    f"{chemin_relatif} contient un bloc "
                    f"except générique (Exception/BaseException/nu) "
                    f"(Req 16.1) — seul app/logique_metier/erreurs.py "
                    f"peut centraliser la capture d'exceptions."
                )


class TestAucuneReferencePaystub:
    """Aucune référence textuelle à ``paystub`` dans ``app/main.py`` et
    ``app/pages_ui/**`` (Req 17.3).

    Recherche textuelle (``grep``) de la sous-chaîne ``paystub`` dans le
    contenu de ``app/main.py`` (si le fichier existe) et de tous les
    fichiers ``.py`` sous ``app/pages_ui/`` (si le dossier existe) —
    patron exact du design §Error Handling « Test de garde — absence de
    référence à payroll_engine/paystub.py ». Cette garde matérialise
    l'absence de dépendance de l'interface vers un module
    ``payroll_engine/paystub.py`` qui n'existe pas dans le moteur
    (design, Req 17.3) : l'interface doit s'appuyer exclusivement sur
    les six fonctions du moteur explicitement listées.

    Recherche insensible à la casse (``str.lower()``) par précaution :
    une référence ``Paystub`` ou ``PAYSTUB`` (ex. nom de classe,
    commentaire) constituerait la même violation qu'une occurrence
    ``paystub`` en minuscules strictes.

    Tant qu'``app/main.py`` n'existe pas et qu'``app/pages_ui/``
    n'existe pas, aucun fichier n'est lu : la recherche ne trouve
    aucune occurrence et le test reste vert (règle 06) — comportement
    attendu avant l'implémentation des sections 22 à 26.
    """

    def test_aucune_reference_paystub(self) -> None:
        """Aucune occurrence de ``paystub`` (insensible à la casse)."""
        fichiers: list[Path] = []

        main_py = _REPO_ROOT / "app" / "main.py"
        if main_py.is_file():
            fichiers.append(main_py)

        pages_ui = _REPO_ROOT / "app" / "pages_ui"
        if pages_ui.is_dir():
            fichiers.extend(pages_ui.rglob("*.py"))

        for fichier in fichiers:
            contenu = fichier.read_text(encoding="utf-8")
            assert "paystub" not in contenu.lower(), (
                f"{fichier.relative_to(_REPO_ROOT).as_posix()} contient "
                f"une référence à 'paystub' (Req 17.3) — l'interface ne "
                f"doit dépendre que des six fonctions du moteur "
                f"explicitement listées."
            )


class TestSignaturesExactesMoteur:
    """Signatures exactes des six fonctions du moteur invoquées (Req 18.3).

    Importe les six fonctions figées du moteur —
    :func:`payroll_engine.net_pay.assembler_paie` et les cinq fonctions
    de :mod:`payroll_engine.register` (:func:`inserer_paie`,
    :func:`lire_paie`, :func:`lire_historique_paie`,
    :func:`lire_cumuls_ytd`, :func:`remplacer_paie`) — et obtient leurs
    signatures réelles via ``inspect.signature``. Parcourt ensuite tous
    les fichiers ``.py`` sous ``app/logique_metier/`` **et**
    ``app/pages_ui/`` par ``ast.parse``, repère chaque ``ast.Call`` dont
    la fonction appelée correspond par nom à l'une des six cibles (appel
    direct ``ast.Name`` ou qualifié ``ast.Attribute``, ex.
    ``register.lire_paie(...)``), et vérifie que les arguments
    positionnels et nommés utilisés à ce site d'appel restent un
    sous-ensemble valide des paramètres de la signature figée — patron
    exact du design §Error Handling « Points d'appel couverts ».

    **Comportement rouge intentionnel, à la différence des trois gardes
    précédentes (règle 06)** : si aucun site d'appel n'est trouvé — ce
    qui est nécessairement le cas tant qu'aucun fichier n'existe sous
    ``app/logique_metier/`` ni ``app/pages_ui/`` — le test échoue
    explicitement avec un message actionnable, plutôt que de passer
    silencieusement par défaut. Une collecte vide ne peut prouver le
    respect des signatures figées ; ce test ne devient significatif
    qu'après l'implémentation des sections 12 à 19 (couche logique
    métier) et 22 à 26 (couche de rendu), qui introduisent les premiers
    sites d'appel réels aux six fonctions du moteur.
    """

    def test_appels_respectent_signatures_figees(self) -> None:
        """Aucun site d'appel n'utilise d'argument absent de la signature."""
        fonctions_moteur = {
            "assembler_paie": assembler_paie,
            "inserer_paie": inserer_paie,
            "lire_paie": lire_paie,
            "lire_historique_paie": lire_historique_paie,
            "lire_cumuls_ytd": lire_cumuls_ytd,
            "remplacer_paie": remplacer_paie,
        }
        signatures = {
            nom: inspect.signature(fonction)
            for nom, fonction in fonctions_moteur.items()
        }

        dossiers = (
            _REPO_ROOT / "app" / "logique_metier",
            _REPO_ROOT / "app" / "pages_ui",
        )

        fichiers: list[Path] = []
        for dossier in dossiers:
            if dossier.is_dir():
                fichiers.extend(dossier.rglob("*.py"))

        nombre_sites_appel = 0

        for fichier in fichiers:
            chemin_relatif = fichier.relative_to(_REPO_ROOT).as_posix()
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue

                if isinstance(noeud.func, ast.Name):
                    nom_fonction = noeud.func.id
                elif isinstance(noeud.func, ast.Attribute):
                    nom_fonction = noeud.func.attr
                else:
                    continue

                if nom_fonction not in signatures:
                    continue

                nombre_sites_appel += 1
                signature = signatures[nom_fonction]
                parametres = list(signature.parameters.keys())

                assert len(noeud.args) <= len(parametres), (
                    f"{chemin_relatif} appelle {nom_fonction}(...) avec "
                    f"{len(noeud.args)} arguments positionnels, mais la "
                    f"signature figée {signature} n'en déclare que "
                    f"{len(parametres)} (Req 18.3) — aucun argument "
                    f"surnuméraire n'est autorisé."
                )

                for mot_cle in noeud.keywords:
                    if mot_cle.arg is None:
                        # Dépaquetage **kwargs — non vérifiable statiquement.
                        continue
                    assert mot_cle.arg in parametres, (
                        f"{chemin_relatif} appelle {nom_fonction}(...) avec "
                        f"l'argument nommé '{mot_cle.arg}' absent de la "
                        f"signature figée {signature} (Req 18.3) — aucun "
                        f"argument surnuméraire n'est autorisé."
                    )

        assert nombre_sites_appel > 0, (
            "Aucun site d'appel trouvé pour les fonctions du moteur "
            "(assembler_paie, inserer_paie, lire_paie, "
            "lire_historique_paie, lire_cumuls_ytd, remplacer_paie) sous "
            "app/logique_metier/ et app/pages_ui/ — ce test deviendra "
            "significatif une fois les tâches 12 à 19 et 22 à 26 "
            "implémentées."
        )
