"""Property tests et tests d'exemple pour `app/logique_metier/dernieres_paies.py`.

Spec de référence : ``interface-streamlit`` — tâche 5.1 (squelette du
fichier et test de la Property 5).
Design de référence : ``design.md`` §Components §4 (`dernieres_paies.py`
— lecture SQL directe, sans fonction privée de `register.py`) et
§Correctness Properties 5, 6, 7 ; décision n° 5.

Ce fichier porte l'ensemble des property tests et tests d'exemple des
lectures/agrégations de paies (`derniere_annee_paie`, `LignePaieResume`,
`lire_resumes_paies`, `filtrer_par_annee`, `regrouper_saison_par_annee`,
`formater_option_annee`). La tâche 5.1 pose le **squelette** : le module
docstring, les imports, et la Property 5 (classe
``TestDerniereAnneePaie``). Les tâches suivantes ont ajouté :

- ``TestLibelleAnneeSaison`` — Property 6 (tâche 5.2) ;
- ``TestFiltrageParAnnee`` — Property 7 (tâche 5.3) ;
- ``TestLireResumesPaies`` — tests d'exemple de `lire_resumes_paies`
  (tâche 5.4, dernière classe de ce fichier).

Les **3 propriétés** couvertes par ce fichier de test au total (design.md
§Correctness Properties) :

5. **Property 5 — Dernière année de paie d'un employé**.
6. **Property 6 — Libellé année/saison du sélecteur**.
7. **Property 7 — Filtrage des paies par année fiscale**.

``TestLireResumesPaies`` (tâche 5.4) n'introduit aucune nouvelle
property numérotée du design — ce sont des **tests d'exemple** ciblés
(Req 4.3, 18.2) : base neuve sans exception, `net` jamais reconverti en
`float` (règle 01), et absence d'appel à une fonction privée de
`payroll_engine.register` (inspection `ast` du code source).

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/dernieres_paies.py`` n'existe **pas encore** à ce
stade (implémentation prévue à la tâche 15.1/15.2). Ce fichier importe
donc localement les symboles du module sous test (au sein de chaque test)
afin que la **collecte** pytest de ce fichier réussisse même tant que le
module cible est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``app.logique_metier.dernieres_paies`` —
c'est le comportement **attendu et correct** (état rouge intentionnel)
tant que la tâche 15 (implémentation) n'a pas été réalisée (checkpoint
de la tâche 11 du plan).

``payroll_engine.register.inserer_paie`` et
``payroll_engine.register.chemin_bd_production`` sont déjà livrés et
figés par la spec ``net-cumuls-registre`` — importés directement ici
(pas d'import différé nécessaire pour ceux-là, à la différence des
symboles de `dernieres_paies.py`).

Règle 01 : les `PayrollResult` générés par
`st_sequence_payroll_results_meme_employe_annee` (`tests/strategies.py`,
tâche 1.1 de `net-cumuls-registre`) portent exclusivement des champs
`Decimal` (jamais de `float`) — ce fichier ne réintroduit aucune
conversion `float`.
Règle 04 : chaque test injecte systématiquement un chemin de base
temporaire (`st_chemin_bd_temporaire`, `tmp_path`) ou `":memory:"` —
jamais le chemin de production (`chemin_bd_production()`) — et
n'utilise que des identifiants fictifs `EMPnnn`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from models.payroll_result import PayrollResult
from payroll_engine.register import inserer_paie
from tests.strategies import (
    st_chemin_bd_temporaire,  # noqa: F401  (fixture pytest, résolue par nom de paramètre)
    st_saison,
    st_sequence_payroll_results_meme_employe_annee,
)

#: Racine du dépôt, pour localiser `app/logique_metier/dernieres_paies.py`
#: à des fins d'inspection `ast` du **code source** (même convention que
#: `tests/app/logique_metier/test_annuaire_employes.py::_REPO_ROOT`).
_REPO_ROOT: Path = Path(__file__).parent.parent.parent.parent

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec les autres fichiers de
# la suite — ``deadline=None``, mêmes suppressions de health check). Le
# nombre d'exemples est piloté par le profil Hypothesis actif (voir
# tests/conftest.py : dev=15 par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


# ---------------------------------------------------------------------------
# Stratégie locale — mélange de groupes de paies pour plusieurs
# employés/années (composition, sans duplication, de
# ``st_sequence_payroll_results_meme_employe_annee``).
# ---------------------------------------------------------------------------


@st.composite
def _st_groupes_paies_multi_employes_annees(
    draw: st.DrawFn,
) -> tuple[tuple[PayrollResult, ...], ...]:
    """0 à 4 groupes de paies, chacun pour un couple `employe_id`/`annee_fiscale`.

    Compose ``st_sequence_payroll_results_meme_employe_annee`` (`tests/
    strategies.py`, réutilisation directe, sans duplication) : chaque
    groupe tiré est un mélange autonome, rattaché à son propre
    `employe_id`/`annee_fiscale`. Les groupes vides (`n = 0` pour ce
    tirage) sont écartés, ainsi que tout groupe dont le couple
    `(employe_id, annee_fiscale)` a déjà été vu — pour garantir que
    chaque groupe conservé possède un `id_paie` distinct de tous les
    autres (évite une collision d'unicité lors des insertions
    successives via `inserer_paie`, Req 11.6). Le résultat est donc un
    ensemble de groupes non vides, deux à deux distincts par couple
    `(employe_id, annee_fiscale)` — exactement le « mélange
    d'employés/années » requis par la Property 5.
    """
    n_groupes = draw(st.integers(min_value=0, max_value=4))
    couples_vus: set[tuple[str, int]] = set()
    groupes: list[tuple[PayrollResult, ...]] = []
    for _ in range(n_groupes):
        groupe = draw(st_sequence_payroll_results_meme_employe_annee(n_max=3))
        if not groupe:
            continue
        couple = (groupe[0].employe_id, groupe[0].annee_fiscale)
        if couple in couples_vus:
            continue
        couples_vus.add(couple)
        groupes.append(groupe)
    return tuple(groupes)


def _st_employe_id_arbitraire() -> st.SearchStrategy[str]:
    """Identifiant employé fictif `EMPnnn` arbitraire (règle 04).

    Utilisé pour interroger `derniere_annee_paie` avec un `employe_id`
    potentiellement absent de tout groupe généré par
    `_st_groupes_paies_multi_employes_annees` — le test vérifie alors le
    cas `None` (Property 5).
    """
    return st.integers(min_value=1, max_value=999).map(lambda n: f"EMP{n:03d}")


# ---------------------------------------------------------------------------
# Property 5 — Dernière année de paie d'un employé
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 5: Dernière année de paie d'un employé
#
# *Pour tout* ensemble de paies insérées pour un mélange d'employés/
# années, `derniere_annee_paie(employe_id, chemin_bd)` retourne le
# maximum des `annee_fiscale` correspondant exactement à `employe_id`,
# ou `None` si aucune paie (y compris base neuve sans table `paies`).
#
# _Requirements: 4.3_
# _Design: §Components §4 ; §Correctness Properties 5 ; décision n° 5_


class TestDerniereAnneePaie:
    """Property 5 — dernière année de paie d'un employé."""

    # Feature: interface-streamlit, Property 5: Dernière année de paie d'un employé
    @pytest.mark.property
    @given(
        groupes=_st_groupes_paies_multi_employes_annees(),
        saison=st_saison(),
        employe_id_arbitraire=_st_employe_id_arbitraire(),
    )
    @settings_large_input
    def test_retourne_le_maximum_des_annees_correspondant_exactement_ou_none(
        self,
        groupes: tuple[tuple[PayrollResult, ...], ...],
        saison: str,
        employe_id_arbitraire: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 5 (Req 4.3).

        Insère chaque `PayrollResult` de chaque groupe de ``groupes`` via
        `inserer_paie` (base neuve — `st_chemin_bd_temporaire` garantit un
        fichier SQLite absent avant la première insertion). Pour chaque
        `employe_id` présent dans au moins un groupe,
        `derniere_annee_paie(employe_id, chemin_bd)` doit retourner
        exactement le maximum des `annee_fiscale` des groupes rattachés à
        cet `employe_id` — jamais une année d'un autre employé. Pour un
        `employe_id` arbitraire absent de tout groupe,
        `derniere_annee_paie` doit retourner `None`.
        """
        from app.logique_metier.dernieres_paies import derniere_annee_paie

        for groupe in groupes:
            for resultat in groupe:
                inserer_paie(resultat, saison, chemin_bd=st_chemin_bd_temporaire)

        annees_par_employe: dict[str, set[int]] = {}
        for groupe in groupes:
            employe_id = groupe[0].employe_id
            annee_fiscale = groupe[0].annee_fiscale
            annees_par_employe.setdefault(employe_id, set()).add(annee_fiscale)

        for employe_id, annees in annees_par_employe.items():
            resultat_obtenu = derniere_annee_paie(
                employe_id, chemin_bd=st_chemin_bd_temporaire
            )
            assert resultat_obtenu == max(annees), (
                f"`derniere_annee_paie({employe_id!r}, ...)` doit retourner "
                f"le maximum des années fiscales rattachées à cet employé "
                f"({max(annees)}), obtenu {resultat_obtenu!r}."
            )

        if employe_id_arbitraire not in annees_par_employe:
            resultat_absent = derniere_annee_paie(
                employe_id_arbitraire, chemin_bd=st_chemin_bd_temporaire
            )
            assert resultat_absent is None, (
                f"`derniere_annee_paie({employe_id_arbitraire!r}, ...)` doit "
                f"retourner `None` en l'absence de toute paie pour cet "
                f"employé, obtenu {resultat_absent!r}."
            )

    # Feature: interface-streamlit, Property 5: Dernière année de paie d'un employé
    def test_exemple_base_memoire_neuve_sans_table_paies_retourne_none(
        self,
    ) -> None:
        """Test d'exemple — base `:memory:` neuve, sans table `paies` (Req 4.3).

        Une base SQLite `":memory:"` fraîchement ouverte n'a encore
        créé aucune table (contrairement à une base fichier déjà
        initialisée par `register.py`) — `derniere_annee_paie` doit
        intercepter explicitement `sqlite3.OperationalError` («no such
        table») et retourner `None`, jamais laisser l'exception se
        propager (décision n° 5).
        """
        from app.logique_metier.dernieres_paies import derniere_annee_paie

        resultat = derniere_annee_paie("EMP001", chemin_bd=":memory:")

        assert resultat is None, (
            "`derniere_annee_paie` sur une base `:memory:` neuve (sans "
            f"table `paies`) doit retourner `None`, obtenu {resultat!r}."
        )


# ---------------------------------------------------------------------------
# Property 6 — Libellé année/saison du sélecteur
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 6: Libellé année/saison du sélecteur
#
# *Pour tout* ensemble de `LignePaieResume` arbitraires,
# `formater_option_annee(annee, regrouper_saison_par_annee(resumes)[annee])`
# produit `"<annee> (<saison>)"` où `<saison>` est celle du résumé de
# `date_creation` maximale pour cette année ; sans résumé pour cette
# année, `formater_option_annee(annee, None)` produit `"<annee>"` seul.
#
# _Requirements: 5.2_
# _Design: §Components §4 ; §Correctness Properties 6_


def _st_date_creation_triable() -> st.SearchStrategy[str]:
    """Chaîne `date_creation` ISO simple, triable lexicographiquement.

    Design §Components §4 : `date_creation` est une chaîne ISO stockée
    telle quelle (aucune conversion `datetime`, décision n° 5). Cette
    stratégie fige l'année/le jour/l'heure de base et ne fait varier que
    les microsecondes (zero-paddées sur 6 chiffres) afin de produire des
    chaînes de longueur constante, strictement comparables
    lexicographiquement — suffisant pour simuler un ordre chronologique
    arbitraire au sein d'un même groupe de résumés, sans dépendre du
    format réel produit par `register.py`.
    """
    return st.integers(min_value=0, max_value=999_999).map(
        lambda n: f"2020-01-01T00:00:00.{n:06d}"
    )


def _st_annee_fiscale_arbitraire() -> st.SearchStrategy[int]:
    """Année fiscale arbitraire, plage volontairement resserrée.

    Une plage resserrée (`2020` à `2035`) augmente la probabilité que
    plusieurs `LignePaieResume` générés partagent la même `annee_fiscale`
    au sein d'un même exemple — indispensable pour exercer le
    regroupement par « `date_creation` maximale » de
    `regrouper_saison_par_annee` (Property 6) plutôt que de systématiquement
    produire des groupes à un seul élément.
    """
    return st.integers(min_value=2020, max_value=2035)


@st.composite
def _st_champs_ligne_paie_resume(draw: st.DrawFn) -> dict[str, object]:
    """Champs arbitraires pour construire une `LignePaieResume` fictive.

    `id_paie`, `numero_periode`, `version`, `statut`, `net` sont des
    valeurs fictives simples — ce test exerce uniquement l'agrégation
    pure (`regrouper_saison_par_annee`/`formater_option_annee`), sans
    passer par `PayrollResult`/`register.py`. `net` reste une chaîne
    (règle 01). `saison` réutilise `st_saison()` (`tests/strategies.py`,
    tâche 5.1) — y compris la chaîne vide, traitée comme « absence de
    saison » par `formater_option_annee` (falsy).
    """
    return {
        "id_paie": f"PAIE-TEST-{draw(st.integers(min_value=0, max_value=999_999))}",
        "numero_periode": draw(st.integers(min_value=1, max_value=27)),
        "version": draw(st.integers(min_value=1, max_value=5)),
        "statut": draw(st.sampled_from(["EN_VIGUEUR", "ANNULEE", "REMPLACE_PAR"])),
        "net": str(draw(st.integers(min_value=0, max_value=100_000))),
        "saison": draw(st_saison()),
        "annee_fiscale": draw(_st_annee_fiscale_arbitraire()),
        "date_creation": draw(_st_date_creation_triable()),
    }


def _st_liste_champs_lignes_paie_resume(
    max_size: int = 8,
) -> st.SearchStrategy[tuple[dict[str, object], ...]]:
    """0 à `max_size` jeux de champs de `LignePaieResume`, sans contrainte
    d'unicité — plusieurs résumés peuvent partager la même `annee_fiscale`
    (voulu, voir `_st_annee_fiscale_arbitraire`).
    """
    return st.lists(
        _st_champs_ligne_paie_resume(), min_size=0, max_size=max_size
    ).map(tuple)


class TestLibelleAnneeSaison:
    """Property 6 — libellé année/saison du sélecteur."""

    # Feature: interface-streamlit, Property 6: Libellé année/saison du sélecteur
    @pytest.mark.property
    @given(
        champs_lignes=_st_liste_champs_lignes_paie_resume(),
        annee_test=_st_annee_fiscale_arbitraire(),
    )
    @settings_large_input
    def test_libelle_formate_selon_saison_du_resume_le_plus_recent_ou_annee_seule(
        self,
        champs_lignes: tuple[dict[str, object], ...],
        annee_test: int,
    ) -> None:
        """Property 6 (Req 5.2).

        Construit un `LignePaieResume` par jeu de champs de
        `champs_lignes`, calcule `regrouper_saison_par_annee(resumes)` et
        compare, pour `annee_test`, la saison retenue à un calcul de
        référence indépendant : la `saison` du résumé de `annee_fiscale
        == annee_test` dont `date_creation` est maximale (ou `None` en
        l'absence de tout résumé pour cette année). Vérifie ensuite que
        `formater_option_annee(annee_test, saison_retenue)` produit
        exactement `f"{annee_test} ({saison})"` lorsque la saison retenue
        est non vide, ou `str(annee_test)` seul sinon (saison absente ou
        chaîne vide — cas falsy, Req 5.2).
        """
        from app.logique_metier.dernieres_paies import (
            LignePaieResume,
            formater_option_annee,
            regrouper_saison_par_annee,
        )

        resumes = tuple(LignePaieResume(**champs) for champs in champs_lignes)

        saisons_par_annee = regrouper_saison_par_annee(resumes)

        resumes_de_lannee_test = [
            resume for resume in resumes if resume.annee_fiscale == annee_test
        ]
        if resumes_de_lannee_test:
            resume_le_plus_recent = max(
                resumes_de_lannee_test, key=lambda resume: resume.date_creation
            )
            saison_attendue: str | None = resume_le_plus_recent.saison
        else:
            saison_attendue = None

        saison_obtenue = saisons_par_annee.get(annee_test)
        assert saison_obtenue == saison_attendue, (
            f"`regrouper_saison_par_annee(...)[{annee_test!r}]` doit "
            f"retourner la saison du résumé de `date_creation` maximale "
            f"pour cette année ({saison_attendue!r}), obtenu "
            f"{saison_obtenue!r}."
        )

        libelle = formater_option_annee(annee_test, saison_obtenue)
        if saison_attendue:
            assert libelle == f"{annee_test} ({saison_attendue})", (
                f"`formater_option_annee({annee_test!r}, {saison_obtenue!r})` "
                f"doit produire "
                f"{f'{annee_test} ({saison_attendue})'!r}, obtenu {libelle!r}."
            )
        else:
            assert libelle == str(annee_test), (
                f"`formater_option_annee({annee_test!r}, {saison_obtenue!r})` "
                f"doit produire {str(annee_test)!r} seul en l'absence de "
                f"saison exploitable, obtenu {libelle!r}."
            )


# ---------------------------------------------------------------------------
# Property 7 — Filtrage des paies par année fiscale
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 7: Filtrage des paies par année fiscale
#
# *Pour tout* ensemble de résumés et *toute* année, `filtrer_par_annee`
# retourne exactement le sous-ensemble correspondant, même ordre
# relatif, sans altération de champ.
#
# _Requirements: 5.3_
# _Design: §Components §4 ; §Correctness Properties 7_


class TestFiltrageParAnnee:
    """Property 7 — filtrage des paies par année fiscale."""

    # Feature: interface-streamlit, Property 7: Filtrage des paies par année fiscale
    @pytest.mark.property
    @given(
        champs_lignes=_st_liste_champs_lignes_paie_resume(),
        annee_test=_st_annee_fiscale_arbitraire(),
    )
    @settings_large_input
    def test_retourne_exactement_le_sous_ensemble_de_lannee_meme_ordre_sans_alteration(
        self,
        champs_lignes: tuple[dict[str, object], ...],
        annee_test: int,
    ) -> None:
        """Property 7 (Req 5.3).

        Construit un `LignePaieResume` par jeu de champs de
        `champs_lignes` (réutilisation directe des helpers de la tâche
        5.2, sans duplication), puis compare
        `filtrer_par_annee(resumes, annee_test)` à une implémentation de
        référence en Python pur —
        `tuple(r for r in resumes if r.annee_fiscale == annee_test)` —
        construite indépendamment sur la même séquence `resumes`. La
        comparaison directe (`==`) sur les tuples de `LignePaieResume`
        (dataclass) vérifie à la fois l'appartenance au sous-ensemble,
        l'ordre relatif préservé (même position relative que dans
        `resumes`) et l'absence d'altération d'aucun champ (égalité
        structurelle complète de chaque élément).
        """
        from app.logique_metier.dernieres_paies import (
            LignePaieResume,
            filtrer_par_annee,
        )

        resumes = tuple(LignePaieResume(**champs) for champs in champs_lignes)

        resultat_obtenu = filtrer_par_annee(resumes, annee_test)

        resultat_attendu = tuple(
            resume for resume in resumes if resume.annee_fiscale == annee_test
        )

        assert resultat_obtenu == resultat_attendu, (
            f"`filtrer_par_annee(resumes, {annee_test!r})` doit retourner "
            f"exactement le sous-ensemble de `resumes` dont "
            f"`annee_fiscale == {annee_test!r}`, dans le même ordre "
            f"relatif et sans altération de champ ; attendu "
            f"{resultat_attendu!r}, obtenu {resultat_obtenu!r}."
        )


# ---------------------------------------------------------------------------
# Tests d'exemple — `lire_resumes_paies` (tâche 5.4)
# ---------------------------------------------------------------------------
#
# Trois tests d'exemple ciblés (aucune nouvelle property numérotée du
# design) :
#
# 1. base `:memory:` neuve, sans table `paies` → tuple vide, sans
#    exception (même discipline que `derniere_annee_paie`, Req 18.2) ;
# 2. `net` de chaque `LignePaieResume` reste une chaîne (`str`), jamais
#    reconvertie en `float` (règle 01) ;
# 3. inspection `ast` du code source confirmant l'absence d'appel à une
#    fonction privée (préfixée `_`) de `payroll_engine.register` dans
#    `dernieres_paies.py` (Req 4.3, 18.2).
#
# _Requirements: 4.3, 18.2_
# _Design: §Components §4 ; décision n° 5_


def _noms_prives_importes_de_register(arbre: ast.Module) -> set[str]:
    """Noms locaux liés à un import direct d'un symbole privé de `register`.

    Couvre le patron ``from payroll_engine.register import
    _creer_schema_si_absent`` (ou avec alias ``as``) — tout appel direct
    à ce nom local (`ast.Name`) doit ensuite être considéré comme un
    appel à une fonction privée de `payroll_engine.register`.
    """
    noms: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.ImportFrom) and noeud.module in (
            "payroll_engine.register",
            "register",
        ):
            for alias in noeud.names:
                nom_local = alias.asname or alias.name
                if alias.name.startswith("_"):
                    noms.add(nom_local)
    return noms


def _alias_modules_register(arbre: ast.Module) -> set[str]:
    """Noms locaux désignant le module `payroll_engine.register` lui-même.

    Couvre ``import payroll_engine.register`` (nom local
    ``payroll_engine``, cas rare), ``import payroll_engine.register as
    register`` et ``from payroll_engine import register`` — tout accès
    ``<alias>._quelque_chose(...)`` doit ensuite être considéré comme un
    appel à une fonction privée de `payroll_engine.register`.
    """
    alias_modules: set[str] = {"register"}
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.name in ("payroll_engine.register", "register"):
                    alias_modules.add(alias.asname or alias.name.split(".")[0])
        if isinstance(noeud, ast.ImportFrom) and noeud.module == "payroll_engine":
            for alias in noeud.names:
                if alias.name == "register":
                    alias_modules.add(alias.asname or alias.name)
    return alias_modules


def _appelle_fonction_privee_de_register(noeud_call: ast.Call, arbre: ast.Module) -> bool:
    """`True` si cet `ast.Call` appelle une fonction privée de `register`.

    Couvre deux formes syntaxiques (voir décision n° 5 du design et Req
    18.2) :

    - appel par attribut : ``register._creer_schema_si_absent(...)`` —
      ``func`` est un ``ast.Attribute`` dont ``attr`` commence par
      ``"_"`` et dont ``value`` est un ``ast.Name`` résolvant à un
      alias du module `payroll_engine.register` ;
    - appel par nom direct après import ciblé :
      ``from payroll_engine.register import _creer_schema_si_absent``
      puis ``_creer_schema_si_absent(...)`` — ``func`` est un
      ``ast.Name`` dont l'``id`` a été importé directement depuis
      `payroll_engine.register` avec un préfixe ``"_"``.
    """
    func = noeud_call.func

    if isinstance(func, ast.Attribute) and func.attr.startswith("_"):
        if isinstance(func.value, ast.Name):
            if func.value.id in _alias_modules_register(arbre):
                return True

    if isinstance(func, ast.Name):
        if func.id in _noms_prives_importes_de_register(arbre):
            return True

    return False


class TestLireResumesPaies:
    """Tests d'exemple de `lire_resumes_paies` (Req 4.3, 18.2)."""

    def test_exemple_base_memoire_neuve_sans_table_paies_retourne_tuple_vide(
        self,
    ) -> None:
        """Test d'exemple — base `:memory:` neuve, sans table `paies` (Req 18.2).

        Même discipline que
        `TestDerniereAnneePaie.test_exemple_base_memoire_neuve_sans_table_
        paies_retourne_none` : une base SQLite `":memory:"` fraîchement
        ouverte n'a encore créé aucune table — `lire_resumes_paies` doit
        intercepter explicitement l'absence de table et retourner un
        tuple vide, jamais laisser une exception se propager (décision
        n° 5).
        """
        from app.logique_metier.dernieres_paies import lire_resumes_paies

        resultat = lire_resumes_paies("EMP001", chemin_bd=":memory:")

        assert resultat == (), (
            "`lire_resumes_paies` sur une base `:memory:` neuve (sans "
            f"table `paies`) doit retourner un tuple vide, obtenu {resultat!r}."
        )

    # Feature: interface-streamlit, Tests d'exemple de `lire_resumes_paies`
    @given(groupe=st_sequence_payroll_results_meme_employe_annee(n_max=1))
    @settings_large_input
    def test_exemple_net_reste_une_chaine_jamais_reconvertie_en_float(
        self,
        groupe: tuple[PayrollResult, ...],
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Test d'exemple — `net` reste une chaîne, jamais un `float`/`Decimal` (règle 01).

        Insère une unique paie réelle via `inserer_paie` (base neuve —
        `st_chemin_bd_temporaire`, réutilisation de
        `st_sequence_payroll_results_meme_employe_annee` avec
        `n_max=1`), puis vérifie explicitement que `resultat[0].net`
        est de type `str` — jamais reconverti en `float` ni reconstruit
        en `Decimal` par `lire_resumes_paies` (design §Data Models
        « `LignePaieResume` » : `net` reste la chaîne `Decimal`
        sérialisée du `payload_json` d'origine). Les tirages où la
        séquence est vide (`n = 0`) sont écartés (`assume`) : ce test
        exerce le cas d'au moins une paie réelle.
        """
        assume(len(groupe) >= 1)

        from app.logique_metier.dernieres_paies import lire_resumes_paies

        resultat_paie = groupe[0]
        inserer_paie(resultat_paie, "Été 2026", chemin_bd=st_chemin_bd_temporaire)

        resultat = lire_resumes_paies(
            resultat_paie.employe_id, chemin_bd=st_chemin_bd_temporaire
        )

        assert len(resultat) == 1, (
            "`lire_resumes_paies` doit retourner exactement un résumé "
            f"après une unique insertion, obtenu {resultat!r}."
        )
        assert isinstance(resultat[0].net, str), (
            "`LignePaieResume.net` doit rester une chaîne (`str`), jamais "
            f"reconverti en `float`/`Decimal` (règle 01) ; type obtenu "
            f"{type(resultat[0].net)!r}."
        )

    def test_dernieres_paies_napelle_aucune_fonction_privee_de_register(
        self,
    ) -> None:
        """`dernieres_paies.py` n'appelle aucune fonction privée de `register.py`.

        Inspection statique (`ast`) du **code source** du fichier — pas
        un import du module — afin que ce test reste collectable et
        significatif avant même que le fichier existe (règle 06). Tant
        que ``app/logique_metier/dernieres_paies.py`` n'existe pas
        (implémentation prévue à la tâche 15.1/15.2), ce test est
        explicitement marqué ``skip`` plutôt que d'échouer de façon
        confuse (``FileNotFoundError``).

        Une fois le fichier créé, `derniere_annee_paie` et
        `lire_resumes_paies` doivent interroger `paies` en SQL direct,
        sans jamais appeler `_creer_schema_si_absent` ni une autre
        fonction privée (préfixée `_`) de `payroll_engine/register.py`
        (Req 4.3, 18.2, décision n° 5 du design).
        """
        chemin_module = _REPO_ROOT / "app" / "logique_metier" / "dernieres_paies.py"

        if not chemin_module.exists():
            pytest.skip(
                "app/logique_metier/dernieres_paies.py n'existe pas "
                "encore — tâche 15.1/15.2"
            )

        arbre = ast.parse(chemin_module.read_text(encoding="utf-8"))

        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Call) and _appelle_fonction_privee_de_register(
                noeud, arbre
            ):
                pytest.fail(
                    "dernieres_paies.py appelle une fonction privée "
                    "(préfixée `_`) de `payroll_engine.register` (Req "
                    "4.3, 18.2) — `derniere_annee_paie`/`lire_resumes_paies` "
                    "doivent interroger `paies` en SQL direct, sans "
                    "jamais appeler `_creer_schema_si_absent` ni aucune "
                    "autre fonction privée de `register.py`."
                )
