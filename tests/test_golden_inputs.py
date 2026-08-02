"""Golden tests d'entrée — round-trip fidèle des scénarios QC001 à QC006.

Spec de référence : ``moteur-paie-contrats`` — tâche 14.3.
Design de référence : sections « Test Strategy » — golden tests d'entrée —
et « Data Models » §8 (``PayrollInput``) dans ``design.md``.

Portée exacte de la tâche 14.3 (``tasks.md`` §14.3) :

  Pour chaque QC00X : charger la fixture ``tests/fixtures/inputs/qc00X.json``,
  construire un :class:`models.payroll_input.PayrollInput` via
  :meth:`PayrollInput.model_validate_json`, sérialiser en JSON via
  :meth:`PayrollInput.model_dump_json`, comparer à la fixture (round-trip
  fidèle au niveau du ``dict`` reconstruit par ``json.loads``).

  Marqué ``@pytest.mark.golden``.
  **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6**

Ce que le test vérifie exactement :

- **Chargement fidèle** — ``model_validate_json`` accepte la fixture sans
  levée d'exception : la fixture est syntaxiquement valide et respecte
  l'intégralité des invariants du contrat (province Québec, fréquence
  aux deux semaines, taux vacances ∈ ``{0.04, 0.06}``, absence de champ
  sensible, absence de champ hors matrice, correspondance
  ``heures_par_semaine`` / ``pay_period.semaines``, appariement
  ``cumuls_debut``). L'exécution du validateur est effective à cette
  étape (Req 3, Req 11, règle 03, règle 04).

- **Aucun ``float`` dans la fixture** — la surcharge de
  ``model_validate_json`` reroute par ``_parse_json_reject_floats`` qui
  refuse tout littéral numérique non guillemé contenant un point
  décimal ou une notation scientifique. Une fixture erronément produite
  avec ``"taux": 0.04`` (non guillemé) serait rejetée fail-fast
  (règle 01, Req 10.1, Req 13.5).

- **Round-trip conservatif** — le ``dict`` reconstruit à partir de
  ``model_dump_json`` est **strictement égal** au ``dict`` de la
  fixture originale. L'ordre des clés d'un ``dict`` Python n'entre
  pas dans la relation d'égalité, en revanche l'ordre des éléments
  d'une ``list`` (``semaines``, ``heures_par_semaine``) est signifiant
  et doit être préservé (design §Data Models 4 et 8).

Pourquoi ``dict`` et non ``bytes`` : la comparaison au niveau des
octets JSON dépendrait de l'ordre d'émission des clés par Pydantic,
qui n'est pas garanti stable entre versions. La comparaison de
``dict`` (via ``==``) est structurelle et immunisée à ces variations,
tout en restant sensible aux valeurs et à l'ordre des listes — ce qui
correspond exactement à la notion de « fidélité » attendue par le
contrat (Req 13.1, Req 13.3).

Corpus couvert (docs/scenario-qc0XX.md) :

- QC001 — moniteur temps plein, 81 h régulières (Req 12.1) ;
- QC002 — moniteur avec heures supplémentaires (Req 12.2) ;
- QC003 — cuisinier avec impôts non nuls (Req 12.3) ;
- QC004 — directrice au plafond RRQ / RQAP (Req 12.4) ;
- QC005 — moniteur < 18 ans avec exonération RRQ (Req 12.5) ;
- QC006 — assistante temps partiel avec exonérations TP-1015.3 et TD1
  (Req 12.6).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire. Le round-trip transite par des
  chaînes de caractères ; aucun ``float`` n'est produit ni consommé.
- Règle 03 — périmètre Camp LilySO strict. Toute fixture doit rester
  dans la matrice supportée ; le validateur refuse fail-fast toute
  variante hors matrice.
- Règle 04 — identifiants et noms fictifs uniquement (``EMPTEST001``,
  ``EMP002``, …). Le contenu des fixtures est vérifié par la garde
  ``tests/test_guards.py`` (tâche 15.5).
- Règle 06 — TDD, ce module de tests reflète le contrat de tâche 14.3
  et la fixture existante avant toute évolution du modèle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.payroll_input import PayrollInput


#: Identifiants des scénarios de référence du corpus Camp LilySO
#: (Req 12.1 à 12.6). L'ordre est stable et documenté dans
#: ``docs/scenario-qc0XX.md`` ; il conditionne la lisibilité des rapports
#: pytest lorsque plusieurs scénarios régressent simultanément.
SCENARIOS_GOLDEN_INPUTS: tuple[str, ...] = (
    "qc001",
    "qc002",
    "qc003",
    "qc004",
    "qc005",
    "qc006",
)


@pytest.mark.golden
@pytest.mark.parametrize("scenario_id", SCENARIOS_GOLDEN_INPUTS)
def test_payroll_input_round_trip_fidele(
    scenario_id: str,
    fixtures_inputs_dir: Path,
) -> None:
    """Chaque fixture QC00X survit à un round-trip ``PayrollInput`` sans perte.

    Étapes :

    1. Charger le texte JSON de ``tests/fixtures/inputs/{scenario_id}.json``
       et le ``dict`` de référence par un ``json.loads`` direct (bypass
       du modèle, valeur attendue « nue »).
    2. Construire l'instance ``PayrollInput`` via
       :meth:`PayrollInput.model_validate_json` — cette étape déclenche
       aussi le refus fail-fast de tout ``float`` non guillemé
       (``_parse_json_reject_floats``) et l'ensemble des invariants du
       modèle (province Québec, fréquence aux deux semaines, taux
       vacances autorisés, absence de champ hors matrice, cohérence
       croisée).
    3. Ré-émettre le JSON via :meth:`PayrollInput.model_dump_json` puis
       reconstruire un ``dict`` par ``json.loads``.
    4. Comparer les deux ``dict`` par égalité stricte : structure et
       valeurs identiques, ordre des listes préservé, ordre des clés
       de ``dict`` non signifiant.

    L'échec du test signale l'un de ces trois défauts :

    - la fixture contient un motif refusé (hors matrice, float non
      guillemé, champ sensible) — un correctif de la fixture est requis ;
    - le modèle a perdu ou ajouté un champ pendant le round-trip
      (défaut de sérialiseur ``field_serializer`` ou champ défauté non
      émis) — un correctif du modèle est requis ;
    - le contrat du scénario a évolué (nouveau champ, changement
      d'ordre des semaines) — la fixture doit être régénérée en
      synchronisation avec ``docs/scenario-qc0XX.md``.

    Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
    """
    chemin_fixture = fixtures_inputs_dir / f"{scenario_id}.json"
    texte_json_original = chemin_fixture.read_text(encoding="utf-8")

    # (1) ``dict`` de référence directement issu de la fixture,
    #     sans passer par le modèle. Sert de « golden value ».
    dict_original = json.loads(texte_json_original)

    # (2) Construction du modèle : exerce le round-trip d'entrée
    #     ET l'ensemble des validateurs du contrat.
    entree = PayrollInput.model_validate_json(texte_json_original)

    # (3) Re-sérialisation via l'API publique du modèle.
    texte_json_reserialise = entree.model_dump_json()
    dict_reserialise = json.loads(texte_json_reserialise)

    # (4) Comparaison structurelle stricte. Le ``dict`` Python compare
    #     ses valeurs sans tenir compte de l'ordre des clés, mais
    #     l'ordre des listes (semaines, heures_par_semaine) reste
    #     signifiant — ce qui correspond exactement à la notion de
    #     fidélité attendue.
    assert dict_reserialise == dict_original, (
        f"Round-trip infidèle pour {scenario_id.upper()} : le JSON "
        f"reconstruit après model_dump_json diverge de la fixture "
        f"originale. Un correctif de la fixture, du modèle ou de son "
        f"sérialiseur est nécessaire — voir docs/scenario-"
        f"{scenario_id}.md pour le contrat de référence."
    )
