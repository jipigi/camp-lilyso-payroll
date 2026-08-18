"""Property tests et tests d'exemple pour `app/logique_metier/annuaire_coordonnees.py`.

Spec de référence : ``interface-streamlit`` — tâche 4.1 (squelette du
fichier, modèle `FicheCoordonnees` attendu et test de la Property 15).
Design de référence : ``design.md`` §Components §3 (`annuaire_coordonnees.py`
— `FicheCoordonnees` et cycle CRUD), §Data Models (schéma `FicheCoordonnees`)
et §Correctness Properties 15.

Ce fichier porte l'ensemble des property tests et tests d'exemple de
l'Annuaire_Coordonnees (`FicheCoordonnees`, `enregistrer_coordonnees`,
`lire_coordonnees`). La tâche 4.1 pose le **squelette** : le module
docstring, les imports, un test d'exemple verrouillant le schéma minimal
de `FicheCoordonnees` (construction avec `employe_id` seul, tous les
autres champs `None`, `model_config` `frozen=True, extra="forbid"`) et la
Property 15 (classe ``TestRoundTripAnnuaireCoordonnees``). La tâche
suivante ajoutera :

- ``TestSeparationStricte`` — tests d'exemple de séparation stricte du
  contrat de calcul (tâche 4.2).

La **propriété** couverte par ce fichier de test (design.md
§Correctness Properties) :

1. **Property 15 — Round-trip de l'Annuaire_Coordonnees**.

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/annuaire_coordonnees.py`` n'existe **pas encore** à
ce stade (implémentation prévue à la tâche 14.1). Ce fichier importe donc
localement les symboles du module sous test (au sein de chaque test)
afin que la **collecte** pytest de ce fichier réussisse même tant que le
module cible est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``app.logique_metier.annuaire_coordonnees`` —
c'est le comportement **attendu et correct** (état rouge intentionnel)
tant que la tâche 14.1 (implémentation) n'a pas été réalisée (checkpoint
de la tâche 11 du plan). Même discipline que
``tests/app/strategies.py::st_fiche_coordonnees_valide`` (import différé
de ``FicheCoordonnees`` au sein du corps de la stratégie).

Règle 01 : ``FicheCoordonnees`` ne porte aucun champ ``Decimal`` (absence
de montant monétaire, cohérent avec le Glossary de `requirements.md`) —
la règle ne s'applique donc pas à ce fichier.
Règle 04 : chaque test injecte systématiquement un chemin d'annuaire
temporaire via ``st_chemin_json_temporaire`` (tâche 1.1, ``tmp_path``) —
jamais le chemin de production (`chemin_annuaire_coordonnees_production()`)
— et n'utilise que des identifiants fictifs ``EMPnnn`` et des coordonnées
manifestement fictives (via ``st_fiche_coordonnees_valide``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pydantic
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.app.strategies import st_chemin_json_temporaire, st_fiche_coordonnees_valide

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
# Test d'exemple — schéma minimal de `FicheCoordonnees` (Req 20)
# ---------------------------------------------------------------------------
#
# Verrouille le contrat minimal du modèle décrit par le design (§Data
# Models, §Components §3) : seul `employe_id` est obligatoire, tous les
# autres champs sont optionnels (`None` par défaut), et le modèle est
# `frozen=True, extra="forbid"` (cohérent avec le reste du domaine).


class TestFicheCoordonneesSchemaMinimal:
    """Verrouille le schéma minimal de `FicheCoordonnees` (Req 20.1, 20.2)."""

    def test_employe_id_seul_est_valide_avec_tous_les_autres_champs_none(
        self,
    ) -> None:
        from app.logique_metier.annuaire_coordonnees import FicheCoordonnees

        fiche = FicheCoordonnees(employe_id="EMP001")

        assert fiche.employe_id == "EMP001"
        assert fiche.prenom is None
        assert fiche.nom is None
        assert fiche.nas is None
        assert fiche.adresse_residentielle is None
        assert fiche.courriel is None
        assert fiche.telephone is None

    def test_champ_supplementaire_est_rejete(self) -> None:
        from app.logique_metier.annuaire_coordonnees import FicheCoordonnees

        with pytest.raises(pydantic.ValidationError):
            FicheCoordonnees(employe_id="EMP001", champ_inconnu="valeur")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Property 15 — Round-trip de l'Annuaire_Coordonnees
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 15: Round-trip de l'Annuaire_Coordonnees
#
# *Pour toute* liste de Fiche_Coordonnees valides avec des `employe_id`
# distincts, écrire chacune via `enregistrer_coordonnees` puis lire chaque
# `employe_id` via `lire_coordonnees` retourne une fiche égale à celle
# écrite ; pour tout `employe_id` n'appartenant pas à l'ensemble écrit (y
# compris lorsque l'annuaire n'existe pas encore), `lire_coordonnees`
# retourne `None` sans lever d'exception.
#
# _Requirements: 20.1, 20.2, 20.7_
# _Design: §Components §3 ; §Data Models ; §Correctness Properties 15_


class TestRoundTripAnnuaireCoordonnees:
    """Property 15 — round-trip complet de l'Annuaire_Coordonnees."""

    # Feature: interface-streamlit, Property 15: Round-trip de l'Annuaire_Coordonnees
    @pytest.mark.property
    @given(
        fiches=st.lists(
            st_fiche_coordonnees_valide(),
            unique_by=lambda f: f.employe_id,
            max_size=8,
        )
    )
    @settings_large_input
    def test_ecrire_puis_lire_chaque_employe_id_retourne_une_fiche_egale(
        self,
        fiches: list["FicheCoordonnees"],  # noqa: F821
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        from app.logique_metier.annuaire_coordonnees import (
            enregistrer_coordonnees,
            lire_coordonnees,
        )

        chemin_coordonnees = st_chemin_json_temporaire("coordonnees")

        for fiche in fiches:
            enregistrer_coordonnees(fiche, chemin_coordonnees)

        for fiche in fiches:
            resultat = lire_coordonnees(fiche.employe_id, chemin_coordonnees)
            assert resultat == fiche

    # Feature: interface-streamlit, Property 15: Round-trip de l'Annuaire_Coordonnees
    @pytest.mark.property
    @given(employe_id_absent=st.text(min_size=1, max_size=10))
    @settings_large_input
    def test_employe_id_absent_retourne_none_sans_exception(
        self,
        employe_id_absent: str,
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        from app.logique_metier.annuaire_coordonnees import lire_coordonnees

        chemin_coordonnees = st_chemin_json_temporaire("coordonnees")

        resultat = lire_coordonnees(employe_id_absent, chemin_coordonnees)

        assert resultat is None

    # Feature: interface-streamlit, Property 15: Round-trip de l'Annuaire_Coordonnees
    def test_annuaire_inexistant_retourne_none_sans_exception(
        self,
        st_chemin_json_temporaire: Callable[[str], Path],
    ) -> None:
        from app.logique_metier.annuaire_coordonnees import lire_coordonnees

        chemin_coordonnees = st_chemin_json_temporaire("coordonnees")

        resultat = lire_coordonnees("EMP001", chemin_coordonnees)

        assert resultat is None


# ---------------------------------------------------------------------------
# Tests d'exemple — séparation stricte du contrat de calcul (Req 20.3, 18.4)
# ---------------------------------------------------------------------------
#
# Verrouille la séparation stricte entre `FicheCoordonnees` (couche
# `app/logique_metier/`, données personnelles hors calcul) et le contrat de
# calcul du moteur (`Employee`, `PayrollInput`, `PayrollResult`) : ce modèle
# ne doit jamais être ni devenir un de ces types, et le module qui le porte
# ne doit jamais importer les modules de calcul (design §Components §3,
# §Data Models, décision n° 8). Le second test verrouille l'absence
# délibérée de toute validation de format sur `nas` (Req 20.2, Glossary de
# `requirements.md` — `nas` est une donnée d'affichage brute, jamais une
# entrée du moteur de calcul).

import ast

#: Racine du dépôt — trois niveaux au-dessus de
#: ``tests/app/logique_metier/test_annuaire_coordonnees.py`` (``logique_metier/``
#: -> ``app/`` -> ``tests/`` -> racine), plus un niveau supplémentaire pour
#: atteindre la racine du dépôt (même convention que
#: ``tests/app/test_guards.py::_REPO_ROOT``, un niveau plus profond ici).
_REPO_ROOT: Path = Path(__file__).parent.parent.parent.parent

#: Modules de calcul dont l'import est interdit dans
#: ``app/logique_metier/annuaire_coordonnees.py`` — matérialise la
#: séparation stricte entre le contrat de calcul (`Employee`,
#: `PayrollInput`, `PayrollResult`) et `FicheCoordonnees` (Req 20.3).
_MODULES_DE_CALCUL_INTERDITS: tuple[str, ...] = (
    "payroll_engine.net_pay",
    "models.payroll_input",
    "models.payroll_result",
)


class TestSeparationStricte:
    """Séparation stricte du contrat de calcul (Req 20.3, 18.4)."""

    def test_annuaire_coordonnees_naimporte_aucun_module_de_calcul(self) -> None:
        """`annuaire_coordonnees.py` n'importe jamais `Employee`/`PayrollInput`/`PayrollResult`.

        Inspection statique (`ast`) du **code source** du fichier — pas un
        import du module — afin que ce test reste collectable et
        significatif avant même que le fichier existe (règle 06). Tant que
        ``app/logique_metier/annuaire_coordonnees.py`` n'existe pas
        (implémentation prévue à la tâche 14.1), ce test est explicitement
        marqué ``skip`` plutôt que d'échouer de façon confuse.
        """
        chemin_module = _REPO_ROOT / "app" / "logique_metier" / "annuaire_coordonnees.py"

        if not chemin_module.exists():
            pytest.skip(
                "app/logique_metier/annuaire_coordonnees.py n'existe pas "
                "encore — tâche 14.1"
            )

        arbre = ast.parse(chemin_module.read_text(encoding="utf-8"))

        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    assert alias.name not in _MODULES_DE_CALCUL_INTERDITS, (
                        f"annuaire_coordonnees.py importe {alias.name!r} "
                        f"(Req 20.3) — FicheCoordonnees doit rester "
                        f"strictement séparée du contrat de calcul."
                    )
            if isinstance(noeud, ast.ImportFrom):
                assert noeud.module not in _MODULES_DE_CALCUL_INTERDITS, (
                    f"annuaire_coordonnees.py importe depuis "
                    f"{noeud.module!r} (Req 20.3) — FicheCoordonnees doit "
                    f"rester strictement séparée du contrat de calcul."
                )

    def test_nas_accepte_une_chaine_arbitraire_non_formatee(self) -> None:
        """`nas` accepte toute chaîne, sans validation de format (Req 20.2).

        `FicheCoordonnees` est un modèle d'affichage de données
        personnelles (`app/logique_metier/`), jamais une entrée du moteur
        de calcul — aucune validation de format n'est donc appliquée sur
        `nas` (Glossary de `requirements.md`). Donnée manifestement
        fictive (règle 04).
        """
        from app.logique_metier.annuaire_coordonnees import FicheCoordonnees

        fiche = FicheCoordonnees(employe_id="EMP001", nas="123-abc-XYZ-non-formaté")

        assert fiche.nas == "123-abc-XYZ-non-formaté"


# ---------------------------------------------------------------------------
# Migration additive — ancien champ `nom_complet_reel` (bug UI corrigé
# après livraison, scission Prénom/Nom fidèle au gabarit officiel)
# ---------------------------------------------------------------------------


class TestMigrationNomCompletReel:
    """`lister_coordonnees` migre l'ancien champ `nom_complet_reel` (Req 20.1, 20.2).

    Les fiches enregistrées avant la scission Prénom/Nom portent un champ
    unique `nom_complet_reel` dans le fichier JSON — incompatible avec le
    nouveau schéma (`extra="forbid"`). Cette migration additive à la
    lecture (jamais de réécriture du fichier historique) découpe le nom
    complet sur le premier espace.
    """

    def test_ancien_format_nom_complet_reel_est_migre_vers_prenom_et_nom(
        self, st_chemin_json_temporaire: Callable[[str], Path]
    ) -> None:
        import json as json_module

        from app.logique_metier.annuaire_coordonnees import lister_coordonnees
        from app.logique_metier.stockage_json import ecrire_atomique

        chemin_coordonnees = st_chemin_json_temporaire("coordonnees")
        ancien_contenu = json_module.dumps(
            [{"employe_id": "EMP001", "nom_complet_reel": "Lily-Soleil Goydadin"}]
        )
        ecrire_atomique(chemin_coordonnees, ancien_contenu)

        fiches = lister_coordonnees(chemin_coordonnees)

        assert len(fiches) == 1
        assert fiches[0].prenom == "Lily-Soleil"
        assert fiches[0].nom == "Goydadin"

    def test_ancien_format_nom_complet_reel_sans_espace_va_entierement_au_prenom(
        self, st_chemin_json_temporaire: Callable[[str], Path]
    ) -> None:
        import json as json_module

        from app.logique_metier.annuaire_coordonnees import lister_coordonnees
        from app.logique_metier.stockage_json import ecrire_atomique

        chemin_coordonnees = st_chemin_json_temporaire("coordonnees")
        ancien_contenu = json_module.dumps(
            [{"employe_id": "EMP001", "nom_complet_reel": "Madonna"}]
        )
        ecrire_atomique(chemin_coordonnees, ancien_contenu)

        fiches = lister_coordonnees(chemin_coordonnees)

        assert fiches[0].prenom == "Madonna"
        assert fiches[0].nom is None
