"""Configuration partagée de la suite de tests du moteur de paie Camp LilySO.

Ce module :

- documente les marqueurs pytest utilisés dans le projet (aussi déclarés dans
  ``[tool.pytest.ini_options]`` de ``pyproject.toml``, source unique de vérité
  côté configuration) ;
- expose des fixtures de chemins vers les corpus de scénarios ``QC001``–``QC006``
  (Requirement 12 de la spec ``moteur-paie-contrats``) ;
- prépare l'accueil des stratégies Hypothesis définies dans
  ``tests/strategies.py`` (importables sans effets de bord).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire : aucun test ne DOIT introduire de ``float``
  pour représenter un montant ou un taux fiscal.
- Règle 02 — Traçabilité : chaque test golden compare au cent près contre une
  fixture officielle documentée dans ``docs/scenario-qc0XX.md``.
- Règle 03 — Périmètre : les tests marqués ``unsupported`` vérifient qu'un cas
  hors matrice lève ``UnsupportedPayrollCase``.
- Règle 04 — Données sensibles : aucune donnée nominative réelle ne DOIT
  apparaître dans les fixtures (voir garde ``tests/test_guards.py`` future).
- Règle 06 — Workflow : tests avant code, sans exception.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest
from hypothesis import HealthCheck, settings


# ---------------------------------------------------------------------------
# Profils Hypothesis (vitesse des runs property-based).
# ---------------------------------------------------------------------------
#
# Runs locaux rapides par défaut (profil dev, 15 exemples) ; validation
# complète via HYPOTHESIS_PROFILE=ci (>=100, conforme design
# §Testing Strategy « minimum 100 itérations par propriété »).
#
# conftest.py est importé par pytest AVANT la collecte des tests, donc le
# profil est chargé avant l'évaluation des objets ``settings(...)`` définis
# au niveau module dans ``tests/payroll_engine/*.py``. Ces objets omettent
# volontairement ``max_examples`` : ils héritent alors du ``max_examples``
# du profil actif (dev=15, ci=100).

_SUPPRESS_HEALTH_CHECK: Final = [
    HealthCheck.too_slow,
    HealthCheck.filter_too_much,
    HealthCheck.function_scoped_fixture,
]

settings.register_profile(
    "dev",
    max_examples=15,
    deadline=None,
    suppress_health_check=_SUPPRESS_HEALTH_CHECK,
)

settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,
    suppress_health_check=_SUPPRESS_HEALTH_CHECK,
)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


# ---------------------------------------------------------------------------
# Chemins vers les fixtures (partagés par tous les tests golden et de garde).
# ---------------------------------------------------------------------------

TESTS_DIR: Final[Path] = Path(__file__).parent
FIXTURES_DIR: Final[Path] = TESTS_DIR / "fixtures"
FIXTURES_INPUTS_DIR: Final[Path] = FIXTURES_DIR / "inputs"
FIXTURES_OUTPUTS_DIR: Final[Path] = FIXTURES_DIR / "outputs"
# Guides fiscaux officiels (TP-1015.F, T4127, LE-39.0.2, tables CNESST) —
# référence de validation, versionnés par année sous docs/sources-officielles/.
SOURCES_OFFICIELLES_DIR: Final[Path] = TESTS_DIR.parent / "docs" / "sources-officielles"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Racine des fixtures de test."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def fixtures_inputs_dir() -> Path:
    """Fixtures d'entrée ``PayrollInput`` (JSON) pour ``QC001``–``QC006``."""
    return FIXTURES_INPUTS_DIR


@pytest.fixture(scope="session")
def fixtures_outputs_dir() -> Path:
    """Fixtures de sortie ``PayrollResult`` (JSON) pour ``QC001``–``QC006``."""
    return FIXTURES_OUTPUTS_DIR


@pytest.fixture(scope="session")
def sources_officielles_dir() -> Path:
    """Guides fiscaux officiels versionnés (docs/sources-officielles/<AAAA>/)."""
    return SOURCES_OFFICIELLES_DIR
