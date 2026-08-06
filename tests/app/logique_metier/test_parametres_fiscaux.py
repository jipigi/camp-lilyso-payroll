"""Property tests et tests d'exemple de `parametres_fiscaux.py`.

Spec de référence : ``interface-streamlit`` — tâche 6.
Design de référence : ``design.md`` §Components 5 (`app/logique_metier/
parametres_fiscaux.py`), §Correctness Properties 8 et 9.

Discipline TDD (règle 06) : ce fichier est écrit **avant**
``app/logique_metier/parametres_fiscaux.py`` (tâche 16.1). Tant que ce
module n'existe pas, chaque test échoue à l'**exécution** avec
``ModuleNotFoundError`` sur l'import local de ``lister_annees_disponibles``/
``charger_parametres_fusionnes`` — c'est le comportement attendu. L'import
de ces symboles est fait **à l'intérieur de chaque fonction de test** (et
non au niveau module) afin que la collecte pytest de l'ensemble du
répertoire ``tests/app/`` réussisse même tant que le module cible est
absent (convention déjà appliquée dans ``test_dernieres_paies.py``, entre
autres).

Portée de la tâche 6.1 (issue directe de ``tasks.md`` §6.1) :

- **Property 8 : Détection des années de paramètres disponibles** — pour
  toute structure ``parameters/<AAAA>/`` générée (années complètes avec les
  deux fichiers requis, années incomplètes avec un seul des deux, et noms de
  dossiers non numériques), ``lister_annees_disponibles(chemin_racine)``
  retourne exactement l'ensemble trié des années complètes ; tuple vide si
  le dossier racine n'existe pas. **Validates: Requirements 6.1**

Portée de la tâche 6.2 (issue directe de ``tasks.md`` §6.2) :

- **Property 9 : Fusion Parametres_Annuels_Fusionnes Québec + Canada** —
  réutilisation directe de ``tests/strategies.py::st_parametres_annee_2026_qc_ca``
  (fichier à la racine du projet, tâche 1.1 de la spec ``net-cumuls-registre``) :
  pour la paire QC/CA valide de l'année 2026, ``charger_parametres_fusionnes``
  produit un ``ParametresAnnee`` dont ``rrq``/``rqap``/``impot_quebec``
  proviennent exactement de la racine Québec et ``assurance_emploi``/
  ``impot_federal`` exactement de la racine Canada, sans recalcul ni
  altération. **Validates: Requirements 6.2**

Le test d'exemple de propagation de ``FileNotFoundError`` (tâche 6.3) est
ajouté par une tâche ultérieure distincte — volontairement absent de ce
fichier à ce stade pour éviter tout conflit d'édition concurrente.

Règle 04 : aucun chemin de production n'est jamais utilisé — toutes les
structures ``parameters/<AAAA>/`` de ce fichier sont construites sous
``tmp_path``. Le contenu des fichiers ``quebec.json``/``canada.json``
générés ici est un JSON minimal bidon (``"{}"``) : cette tâche ne teste que
la détection de présence de fichiers, jamais leur contenu (le chargement
réel est couvert par ``load_parameters``, déjà testé sous
``tests/payroll_engine/test_parameters_loader.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from models.enums import Juridiction
from payroll_engine.parameters_loader import ParametresAnnee, load_parameters
from tests.strategies import st_parametres_annee_2026_qc_ca

__all__: list[str] = []


# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec le reste de la suite —
# voir tests/conftest.py : dev=15 exemples par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_arborescence = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

#: Bornes d'années utilisées par les stratégies de ce module — plage réaliste
#: et disjointe des dossiers non numériques générés séparément.
_ANNEE_MIN = 2020
_ANNEE_MAX = 2099


def _creer_annee_complete(racine: Path, annee: int) -> None:
    """Crée ``racine/<annee>/`` avec ``quebec.json`` et ``canada.json``.

    Contenu JSON minimal bidon (``"{}"``) — cette tâche ne teste que la
    détection de présence de fichiers, pas leur contenu (règle 04, note de
    tâche 6.1).
    """
    dossier = racine / str(annee)
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "quebec.json").write_text("{}", encoding="utf-8")
    (dossier / "canada.json").write_text("{}", encoding="utf-8")


def _creer_annee_incomplete(racine: Path, annee: int, fichier_present: str) -> None:
    """Crée ``racine/<annee>/`` avec un seul des deux fichiers requis.

    ``fichier_present`` vaut ``"quebec.json"`` ou ``"canada.json"`` —
    l'année ne DOIT PAS être retenue par ``lister_annees_disponibles``.
    """
    dossier = racine / str(annee)
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / fichier_present).write_text("{}", encoding="utf-8")


def _creer_dossier_non_numerique(racine: Path, nom: str) -> None:
    """Crée ``racine/<nom>/`` avec les deux fichiers requis, mais un nom de
    dossier non numérique — DOIT être ignoré par ``lister_annees_disponibles``
    (le nom ne satisfait pas ``str.isdigit()``).
    """
    dossier = racine / nom
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "quebec.json").write_text("{}", encoding="utf-8")
    (dossier / "canada.json").write_text("{}", encoding="utf-8")


@st.composite
def _st_arborescence_parameters(
    draw: st.DrawFn,
) -> tuple[set[int], set[int], set[str]]:
    """Génère trois ensembles disjoints : années complètes, années
    incomplètes, et noms de dossiers non numériques.

    Les années complètes et incomplètes sont tirées d'ensembles disjoints
    de ``_ANNEE_MIN``..``_ANNEE_MAX`` (aucun chevauchement, pour que le
    statut « complet »/« incomplet » de chaque année générée soit sans
    ambiguïté).
    """
    toutes_les_annees = draw(
        st.sets(
            st.integers(min_value=_ANNEE_MIN, max_value=_ANNEE_MAX),
            max_size=12,
        )
    )
    annees_incompletes = draw(
        st.sets(st.sampled_from(sorted(toutes_les_annees)))
        if toutes_les_annees
        else st.just(set())
    )
    annees_completes = toutes_les_annees - annees_incompletes

    # Noms de périphérique réservés par Windows (NUL, CON, PRN, AUX,
    # COM1-9, LPT1-9) : impossibles à créer comme fichier/dossier normal
    # sur ce système de fichiers, indépendamment de la casse. Découvert
    # par Hypothesis (contre-exemple "NUL") — ce n'est pas un
    # comportement à tester ici (aucune implémentation ne pourrait de
    # toute façon créer un tel dossier pour le test), donc exclu de la
    # génération plutôt que traité comme un cas métier.
    _noms_reserves_windows = frozenset(
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )
    noms_non_numeriques = draw(
        st.sets(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Ll", "Lu"), max_codepoint=0x7A
                ),
                min_size=1,
                max_size=8,
            ).filter(
                lambda s: not s.isdigit()
                and s.upper() not in _noms_reserves_windows
            ),
            max_size=5,
        )
    )

    return annees_completes, annees_incompletes, noms_non_numeriques


class TestListerAnneesDisponibles:
    """Property 8 : Détection des années de paramètres disponibles.

    Design (§Components 5, §Correctness Properties 8) : une année est
    retenue si et seulement si son dossier ``parameters/<AAAA>/`` contient
    à la fois ``quebec.json`` et ``canada.json``. Les dossiers dont le nom
    n'est pas entièrement numérique sont ignorés, même s'ils contiennent
    les deux fichiers requis. ``lister_annees_disponibles`` retourne un
    tuple vide (sans exception) si le dossier racine n'existe pas.
    """

    # Feature: interface-streamlit, Property 8: Détection des années de paramètres disponibles
    @pytest.mark.property
    @given(arborescence=_st_arborescence_parameters())
    @settings_arborescence
    def test_property_8_detection_des_annees_disponibles(
        self,
        arborescence: tuple[set[int], set[int], set[str]],
        tmp_path: Path,
    ) -> None:
        """**Validates: Requirements 6.1**

        Construit sous ``tmp_path`` un mélange d'années complètes (les deux
        fichiers présents), d'années incomplètes (un seul fichier présent)
        et de dossiers non numériques (les deux fichiers présents mais nom
        non numérique), puis vérifie que ``lister_annees_disponibles``
        retourne exactement l'ensemble trié des années complètes — ni les
        années incomplètes, ni les dossiers non numériques n'apparaissent.
        """
        import shutil

        from app.logique_metier.parametres_fiscaux import lister_annees_disponibles

        annees_completes, annees_incompletes, noms_non_numeriques = arborescence
        racine = tmp_path / "parameters"

        # ``tmp_path`` est une fixture à portée fonction : Hypothesis exécute
        # de nombreux exemples au sein d'un seul appel de la fonction de
        # test (HealthCheck.function_scoped_fixture est explicitement
        # supprimé ci-dessus), ce qui signifie que ``racine`` est le MÊME
        # répertoire physique pour chaque exemple généré. Sans nettoyage
        # explicite, les dossiers créés par un exemple précédent
        # persisteraient et fausseraient l'assertion de l'exemple courant.
        shutil.rmtree(racine, ignore_errors=True)

        for annee in annees_completes:
            _creer_annee_complete(racine, annee)
        for annee in annees_incompletes:
            _creer_annee_incomplete(racine, annee, fichier_present="quebec.json")
        for nom in noms_non_numeriques:
            _creer_dossier_non_numerique(racine, nom)

        resultat = lister_annees_disponibles(racine)

        assert resultat == tuple(sorted(annees_completes)), (
            "lister_annees_disponibles doit retourner exactement l'ensemble "
            "trié des années dont le dossier contient à la fois quebec.json "
            f"et canada.json. Attendu {tuple(sorted(annees_completes))!r}, "
            f"obtenu {resultat!r} (années incomplètes={annees_incompletes!r}, "
            f"dossiers non numériques={noms_non_numeriques!r})."
        )

    def test_exemple_dossier_racine_inexistant_retourne_tuple_vide(
        self, tmp_path: Path
    ) -> None:
        """Test d'exemple — dossier racine absent → tuple vide, sans
        exception (Req 6.1, cas explicite du design §Components 5).
        """
        from app.logique_metier.parametres_fiscaux import lister_annees_disponibles

        racine_absente = tmp_path / "parameters_jamais_creee"

        resultat = lister_annees_disponibles(racine_absente)

        assert resultat == ()

    def test_exemple_annee_complete_unique_est_detectee(
        self, tmp_path: Path
    ) -> None:
        """Test d'exemple — une unique année complète (2026) est retenue,
        confirmant le cas nominal minimal avant la généralisation par
        Property 8.
        """
        from app.logique_metier.parametres_fiscaux import lister_annees_disponibles

        racine = tmp_path / "parameters"
        _creer_annee_complete(racine, 2026)

        resultat = lister_annees_disponibles(racine)

        assert resultat == (2026,)

    def test_exemple_annee_incomplete_seule_nest_pas_detectee(
        self, tmp_path: Path
    ) -> None:
        """Test d'exemple — une année avec un seul des deux fichiers requis
        (``quebec.json`` sans ``canada.json``) n'est jamais retenue.
        """
        from app.logique_metier.parametres_fiscaux import lister_annees_disponibles

        racine = tmp_path / "parameters"
        _creer_annee_incomplete(racine, 2027, fichier_present="quebec.json")

        resultat = lister_annees_disponibles(racine)

        assert resultat == ()


class TestFusionParametres:
    """Property 9 : Fusion Parametres_Annuels_Fusionnes Québec + Canada.

    Design (§Components 5, §Correctness Properties 9) : pour une paire de
    ``ParametresAnnee`` valides (une Québec, une Canada, même année),
    ``charger_parametres_fusionnes`` produit un ``ParametresAnnee`` dont
    les sections ``rrq``, ``rqap``, ``impot_quebec`` sont identiques à
    celles de la racine Québec, et dont les sections ``assurance_emploi``,
    ``impot_federal`` sont identiques à celles de la racine Canada — sans
    qu'aucune valeur ne soit recalculée ou altérée.

    Réutilisation directe de
    ``tests/strategies.py::st_parametres_annee_2026_qc_ca`` (racine du
    projet, tâche 1.1 de la spec ``net-cumuls-registre`` — aucune
    duplication de génération de ``ParametresAnnee``, note du docstring de
    ``tests/app/strategies.py``). Cette stratégie retourne un
    ``ParametresAnnee`` déjà fusionné : elle sert ici de **référence**
    indépendante à laquelle comparer le résultat de
    ``charger_parametres_fusionnes(2026)``, en plus des deux chargements
    directs (``load_parameters(2026, Juridiction.QUEBEC)`` et
    ``load_parameters(2026, Juridiction.CANADA)``) sur les fichiers réels
    ``parameters/2026/quebec.json`` et ``parameters/2026/canada.json``
    (déjà validés par les six specs précédentes du moteur).
    """

    # Feature: interface-streamlit, Property 9: Fusion Parametres_Annuels_Fusionnes Québec + Canada
    @pytest.mark.property
    @given(parametres_reference=st_parametres_annee_2026_qc_ca())
    @settings_arborescence
    def test_property_9_fusion_quebec_canada(
        self, parametres_reference: ParametresAnnee
    ) -> None:
        """**Validates: Requirements 6.2**

        Charge séparément les racines Québec et Canada réelles de 2026,
        puis vérifie que ``charger_parametres_fusionnes(2026)`` produit un
        ``ParametresAnnee`` dont ``rrq``/``rqap``/``impot_quebec``
        proviennent exactement de la racine Québec, et dont
        ``assurance_emploi``/``impot_federal`` proviennent exactement de
        la racine Canada — sans recalcul ni altération. La référence
        fusionnée fournie par ``st_parametres_annee_2026_qc_ca`` (construite
        indépendamment via ``model_copy``, voir
        ``tests/strategies.py::_charger_parametres_annee_2026_qc_ca``) sert
        de triple vérification supplémentaire sur les mêmes cinq sections.
        """
        from app.logique_metier.parametres_fiscaux import charger_parametres_fusionnes

        parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
        parametres_ca = load_parameters(2026, Juridiction.CANADA)

        resultat = charger_parametres_fusionnes(2026)

        assert resultat.rrq == parametres_qc.rrq == parametres_reference.rrq, (
            "La section rrq doit provenir exactement de la racine Québec, "
            "sans recalcul ni altération."
        )
        assert (
            resultat.rqap == parametres_qc.rqap == parametres_reference.rqap
        ), (
            "La section rqap doit provenir exactement de la racine Québec, "
            "sans recalcul ni altération."
        )
        assert (
            resultat.impot_quebec
            == parametres_qc.impot_quebec
            == parametres_reference.impot_quebec
        ), (
            "La section impot_quebec doit provenir exactement de la racine "
            "Québec, sans recalcul ni altération."
        )
        assert (
            resultat.assurance_emploi
            == parametres_ca.assurance_emploi
            == parametres_reference.assurance_emploi
        ), (
            "La section assurance_emploi doit provenir exactement de la "
            "racine Canada, sans recalcul ni altération."
        )
        assert (
            resultat.impot_federal
            == parametres_ca.impot_federal
            == parametres_reference.impot_federal
        ), (
            "La section impot_federal doit provenir exactement de la "
            "racine Canada, sans recalcul ni altération."
        )


class TestFichierAbsent:
    """Test d'exemple de propagation de ``FileNotFoundError`` (Req 6.4).

    Design (§Components 5) : ``charger_parametres_fusionnes`` délègue
    intégralement à ``load_parameters(annee, Juridiction.QUEBEC,
    chemin_racine)`` puis ``load_parameters(annee, Juridiction.CANADA,
    chemin_racine)``. Si le fichier ``parameters/<annee>/quebec.json`` (ou
    ``canada.json``) n'existe pas sous ``chemin_racine``, ``load_parameters``
    (déjà existant et stable, ``payroll_engine.parameters_loader``) lève
    ``FileNotFoundError`` — cette exception d'origine ne DOIT PAS être
    interceptée par ``charger_parametres_fusionnes`` (règle 03, aucun
    garde-fou supplémentaire qui masquerait l'erreur).
    """

    def test_exemple_annee_inexistante_leve_filenotfounderror_non_interceptee(
        self, tmp_path: Path
    ) -> None:
        """**Validates: Requirements 6.4**

        ``chemin_racine`` (``tmp_path``) est vide — aucun dossier
        ``9999/`` n'y existe. ``charger_parametres_fusionnes(9999,
        chemin_racine=tmp_path)`` doit laisser remonter la
        ``FileNotFoundError`` d'origine levée par ``load_parameters``,
        sans qu'aucune autre exception ne soit substituée.
        """
        from app.logique_metier.parametres_fiscaux import charger_parametres_fusionnes

        annee_inexistante = 9999

        with pytest.raises(FileNotFoundError):
            charger_parametres_fusionnes(annee_inexistante, chemin_racine=tmp_path)
