"""Golden tests de sortie ``PayrollResult`` — corpus QC001 à QC006.

Spec de référence : ``moteur-paie-contrats`` — tâche 14.4.
Fixtures : ``tests/fixtures/outputs/qc00X.json`` (tâche 14.2), issues
des scénarios officiels documentés dans ``docs/scenario-qc0XX.md`` et
validés au cent près contre WebRAS / PDOC.

Pour chaque scénario du corpus, ce module :

1. **Charge la fixture** sous forme de texte JSON depuis
   ``fixtures_outputs_dir`` (fixture session-scoped exposée par
   ``tests/conftest.py``) ;
2. **Reconstruit un** :class:`~models.payroll_result.PayrollResult`
   via :meth:`PayrollResult.model_validate_json` — ce point d'entrée
   déclenche à la fois le refus fail-fast des littéraux flottants non
   guillemés (règle 01, Req 13.5) *et* les trois invariants
   ``model_validator(mode="after")`` : identités comptables (Req 4.9,
   4.10), biconditionnelle statut / remplace_par_id / date_emission
   (Req 6.3–6.5, 6.7) et cohérence de ``cumuls_fin`` (Req 4.6), plus
   transitivement les invariants de somme portés par
   :class:`~models.payroll_result.RetenuesEmploye` (Req 12.8) et
   :class:`~models.payroll_result.CotisationsEmployeur` ;
3. **Vérifie explicitement** — en plus de la validation implicite du
   modèle — les cinq identités attendues par la tâche 14.4 :

   - ``net + total_retenues_employe == gains.brut_total`` (Req 4.9) ;
   - ``cout_employeur == gains.brut_total +
     total_cotisations_employeur`` (Req 4.10) ;
   - somme des cinq retenues effectivement retenues (RRQ + RQAP + AE
     + impôt QC retenu + impôt fédéral retenu) ``==
     total_retenues_employe`` — les deux montants ``*_formule`` NE
     comptent PAS dans le total (Req 12.8) ;
   - somme des six cotisations (RRQ_er + RQAP_er + AE_er + FSS +
     CNESST + CNT) ``== total_cotisations_employeur`` ;
   - ``cumuls_fin.employe_id == employe_id`` et
     ``cumuls_fin.annee_civile == annee_fiscale`` (Req 4.6) ;

4. **Sérialise** le modèle reconstruit en JSON via
   :meth:`PayrollResult.model_dump_json` puis **compare** le dict
   résultant à la fixture originale au cent près (les deux dicts
   sont produits par :func:`json.loads`, ce qui rend la comparaison
   indépendante de l'ordre d'insertion des clés et normalise la
   représentation Python — les ``Decimal`` restent des chaînes
   guillemées de part et d'autre, garantissant l'égalité exacte
   sans tolérance flottante, règle 01).

Les six scénarios sont regroupés par un ``pytest.mark.parametrize``
étiqueté ``qc001``–``qc006`` pour un rapport de test lisible.

Marqueur ``@pytest.mark.golden`` : configuré dans
``pyproject.toml`` (section ``[tool.pytest.ini_options]``).

Requirements couverts : 12.7, 12.8, 12.9.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from models.enums import Juridiction
from models.payroll_input import PayrollInput
from models.payroll_result import GainsDecomposes, PayrollResult
from payroll_engine.parameters_loader import load_parameters


# ---------------------------------------------------------------------------
# Corpus de scénarios (Req 12.1–12.6, tâche 14.2).
#
# Les fixtures ``qc001.json``–``qc006.json`` sont produites par la tâche 14.2
# à partir des captures WebRAS / PDOC anonymisées documentées dans
# ``docs/scenario-qc0XX.md``. Elles couvrent le corpus de reference
# validation-cent-pres du moteur (voir ``docs/journal-validation.md``).
# ---------------------------------------------------------------------------

SCENARIOS: Final[tuple[str, ...]] = (
    "qc001",
    "qc002",
    "qc003",
    "qc004",
    "qc005",
    "qc006",
)


@pytest.mark.golden
@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_golden_output_scenario(
    scenario_id: str,
    fixtures_outputs_dir: Path,
) -> None:
    """Golden test — fixture ``qc00X.json`` → ``PayrollResult`` → JSON.

    Charge la fixture, reconstruit un :class:`PayrollResult` (ce qui
    déclenche toutes les validations d'identité comptable et
    d'invariant de somme), vérifie explicitement les cinq assertions
    exigées par la tâche 14.4, puis sérialise et compare la sortie à
    la fixture d'entrée au cent près.

    Validates: Requirements 12.7, 12.8, 12.9
    """
    # ------------------------------------------------------------------
    # 1. Chargement de la fixture — deux vues : texte brut (pour
    #    ``model_validate_json``) et dict normalisé (pour la comparaison
    #    finale). Le dict est produit par ``json.loads`` standard, donc
    #    tous les ``Decimal`` y sont représentés comme des chaînes
    #    guillemées (règle 01, Req 13.4), ce qui donne une équivalence
    #    exacte sans arithmétique flottante.
    # ------------------------------------------------------------------
    fixture_path = fixtures_outputs_dir / f"{scenario_id}.json"
    assert fixture_path.exists(), (
        f"Fixture manquante : {fixture_path}. "
        f"La tâche 14.2 doit produire les fixtures QC001–QC006 avant "
        f"l'exécution des golden tests de sortie (tâche 14.4)."
    )
    json_text = fixture_path.read_text(encoding="utf-8")
    fixture_dict = json.loads(json_text)

    # ------------------------------------------------------------------
    # 2. Reconstruction — ``model_validate_json`` reroute par
    #    ``_parse_json_reject_floats`` (règle 01, Req 13.5) puis
    #    exécute les trois ``model_validator(mode="after")`` de
    #    ``PayrollResult`` (identités comptables Req 4.9/4.10,
    #    biconditionnelle statut Req 6.3–6.5/6.7, cohérence
    #    ``cumuls_fin`` Req 4.6). Les invariants de somme des
    #    sous-modèles ``RetenuesEmploye`` (Req 12.8) et
    #    ``CotisationsEmployeur`` sont eux aussi vérifiés
    #    transitivement. Toute violation lève ``ValidationError`` avant
    #    de retourner ici.
    # ------------------------------------------------------------------
    resultat = PayrollResult.model_validate_json(json_text)

    # ------------------------------------------------------------------
    # 3. Assertions explicites (Req 12.7, 12.8) — redondantes avec les
    #    validateurs du modèle, mais exigées par la tâche 14.4 pour
    #    documenter noir sur blanc, dans le corps du test golden, les
    #    identités attendues par le corpus. Une régression future qui
    #    affaiblirait un validateur du modèle serait immédiatement
    #    signalée ici.
    # ------------------------------------------------------------------

    # (a) Identité brute (Req 4.9) — comparaison stricte de ``Decimal``,
    #     tolérance nulle (règle 01).
    total_retenues = resultat.retenues_employe.total_retenues_employe
    assert resultat.net + total_retenues == resultat.gains.brut_total, (
        f"[{scenario_id}] Identité brute rompue (Req 4.9) : "
        f"net ({resultat.net}) + total_retenues_employe "
        f"({total_retenues}) ≠ brut_total "
        f"({resultat.gains.brut_total})."
    )

    # (b) Identité coût employeur (Req 4.10).
    total_cotisations = (
        resultat.cotisations_employeur.total_cotisations_employeur
    )
    cout_attendu = resultat.gains.brut_total + total_cotisations
    assert resultat.cout_employeur == cout_attendu, (
        f"[{scenario_id}] Identité coût employeur rompue (Req 4.10) : "
        f"cout_employeur ({resultat.cout_employeur}) ≠ brut_total "
        f"({resultat.gains.brut_total}) + total_cotisations_employeur "
        f"({total_cotisations}) = {cout_attendu}."
    )

    # (c) Somme des cinq retenues *effectivement retenues* (Req 12.8) —
    #     les deux montants ``*_formule`` (impôt QC formule, impôt
    #     fédéral formule) NE comptent PAS dans le total. Ils sont
    #     stockés pour la traçabilité de la formule avant application
    #     éventuelle d'une exonération TP-1015.3 / TD1.
    retenues = resultat.retenues_employe
    somme_retenues = (
        retenues.rrq.montant
        + retenues.rqap.montant
        + retenues.ae.montant
        + retenues.impot_qc_retenu.montant
        + retenues.impot_federal_retenu.montant
    )
    assert somme_retenues == retenues.total_retenues_employe, (
        f"[{scenario_id}] Somme des cinq retenues effectivement retenues "
        f"(RRQ + RQAP + AE + impôt QC retenu + impôt fédéral retenu = "
        f"{somme_retenues}) ≠ total_retenues_employe "
        f"({retenues.total_retenues_employe}). Les montants "
        f"`impot_qc_formule` et `impot_federal_formule` NE comptent PAS "
        f"dans le total (Req 12.8)."
    )

    # (d) Somme des six cotisations employeur. Le drapeau
    #     ``cnesst_en_attente_classification`` n'a AUCUN effet sur la
    #     somme : ``cnesst.montant`` (même provisoire) est toujours
    #     inclus dans le total.
    cotisations = resultat.cotisations_employeur
    somme_cotisations = (
        cotisations.rrq_employeur.montant
        + cotisations.rqap_employeur.montant
        + cotisations.ae_employeur.montant
        + cotisations.fss.montant
        + cotisations.cnesst.montant
        + cotisations.cnt.montant
    )
    assert somme_cotisations == cotisations.total_cotisations_employeur, (
        f"[{scenario_id}] Somme des six cotisations employeur "
        f"(RRQ_er + RQAP_er + AE_er + FSS + CNESST + CNT = "
        f"{somme_cotisations}) ≠ total_cotisations_employeur "
        f"({cotisations.total_cotisations_employeur})."
    )

    # (e) Cohérence ``cumuls_fin`` (Req 4.6) — même employé, même année.
    assert resultat.cumuls_fin.employe_id == resultat.employe_id, (
        f"[{scenario_id}] cumuls_fin.employe_id "
        f"({resultat.cumuls_fin.employe_id!r}) ≠ employe_id "
        f"({resultat.employe_id!r}) (Req 4.6)."
    )
    assert resultat.cumuls_fin.annee_civile == resultat.annee_fiscale, (
        f"[{scenario_id}] cumuls_fin.annee_civile "
        f"({resultat.cumuls_fin.annee_civile}) ≠ annee_fiscale "
        f"({resultat.annee_fiscale}) (Req 4.6)."
    )

    # ------------------------------------------------------------------
    # 4. Sérialisation + comparaison au cent près (Req 12.7, 12.9).
    #
    # ``model_dump_json`` respecte les ``field_serializer(when_used="json")``
    # de chaque sous-modèle : chaque ``Decimal`` sort comme chaîne
    # guillemée (règle 01, Req 13.4). Le round-trip texte → modèle →
    # texte doit produire un dict strictement égal à la fixture
    # originale — c'est la définition opérationnelle de « au cent près »
    # pour ce corpus. Toute divergence signale soit un sérialiseur
    # manquant, soit une perte de précision, soit une écriture non
    # canonique dans la fixture.
    #
    # La comparaison se fait sur les *dicts* (``json.loads(...)``) et
    # non sur les chaînes brutes : l'ordre des clés dans le JSON produit
    # par Pydantic suit l'ordre de déclaration des champs, qui peut
    # différer de l'ordre d'écriture de la fixture. Seule l'égalité
    # sémantique compte pour un golden test.
    # ------------------------------------------------------------------
    json_serialise = resultat.model_dump_json()
    dict_serialise = json.loads(json_serialise)

    assert dict_serialise == fixture_dict, (
        f"[{scenario_id}] Round-trip fixture → PayrollResult → JSON "
        f"non fidèle. La fixture originale et la sortie sérialisée "
        f"divergent, ce qui rompt la contrainte de comparaison au cent "
        f"près (Req 12.7). Vérifier : (1) qu'aucun ``field_serializer`` "
        f"n'a été omis sur un ``Decimal`` (règle 01, Req 13.4), (2) que "
        f"la fixture ne contient pas de champ superflu ou manquant "
        f"vis-à-vis du contrat ``PayrollResult``, (3) que les valeurs "
        f"``Decimal`` sont écrites comme des chaînes guillemées dans la "
        f"fixture (règle 01)."
    )


# ---------------------------------------------------------------------------
# Golden test — section `gains` du corpus QC001–QC006 (spec
# gains-bruts-vacances-hs, tâche 3.1).
#
# ``calcul_gains`` n'existe pas encore à ce stade de la règle 06 (« tests
# avant code ») : le module ``payroll_engine.gains_bruts`` sera livré par
# les tâches 5.1/5.2. L'import est donc effectué **localement**, à
# l'intérieur du test, afin qu'un ``ModuleNotFoundError`` sur cette seule
# fonction ne fasse pas échouer la collecte de tout ce fichier (les golden
# tests ci-dessus, portant sur des modules déjà livrés, doivent continuer à
# passer).
# ---------------------------------------------------------------------------

SCENARIOS_GAINS: Final[tuple[str, ...]] = (
    "QC001",
    "QC002",
    "QC003",
    "QC004",
    "QC005",
    "QC006",
)


@pytest.mark.golden
@pytest.mark.parametrize("scenario_id", SCENARIOS_GAINS)
def test_calcul_gains_reproduit_fixture(
    scenario_id: str,
    fixtures_inputs_dir: Path,
    fixtures_outputs_dir: Path,
) -> None:
    """Reproduit la section ``gains`` de la fixture au cent près.

    **Limitation connue du corpus** (héritée de l'Introduction des
    requirements de la spec ``gains-bruts-vacances-hs`` et de
    ``docs/hypotheses-2026.md`` §9) : les fixtures ``qc00X.json``
    portent une décomposition hebdomadaire des heures qui est une
    **fabrication 50/50** du total de période sur les deux semaines
    constituantes — les valeurs WebRAS/PDOC de référence ont été
    calculées sur les **totaux de période**, pas semaine par semaine.
    La reproduction au cent près validée ici ne porte donc que sur les
    totaux de période ; elle reste correcte car la formule de
    ``calcul_gains`` est linéaire (``Σ heures_semaine × taux ==
    heures_totales × taux``), indépendamment du découpage fabriqué.

    Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7,
    11.8
    """
    # Import local — voir le commentaire de section ci-dessus : le
    # module n'existe pas encore (tâches 5.1/5.2), l'échec attendu à ce
    # stade est un ``ModuleNotFoundError`` propre, pas un crash de
    # collecte pour le reste du fichier.
    from payroll_engine.gains_bruts import calcul_gains

    scenario_fichier = scenario_id.lower()

    # ------------------------------------------------------------------
    # 1. Chargement de la fixture d'entrée → ``PayrollInput``.
    # ------------------------------------------------------------------
    fixture_input_path = fixtures_inputs_dir / f"{scenario_fichier}.json"
    assert fixture_input_path.exists(), (
        f"Fixture d'entrée manquante : {fixture_input_path}. Les tâches "
        f"14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    payroll_input = PayrollInput.model_validate_json(
        fixture_input_path.read_text(encoding="utf-8")
    )

    # ------------------------------------------------------------------
    # 2. Chargement des paramètres annuels versionnés (règle 05).
    # ------------------------------------------------------------------
    parametres = load_parameters(2026, Juridiction.QUEBEC)

    # ------------------------------------------------------------------
    # 3. Chargement de la fixture de sortie → section ``gains`` →
    #    ``GainsDecomposes`` attendu.
    # ------------------------------------------------------------------
    fixture_output_path = fixtures_outputs_dir / f"{scenario_fichier}.json"
    assert fixture_output_path.exists(), (
        f"Fixture de sortie manquante : {fixture_output_path}. Les "
        f"tâches 14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    fixture_output = json.loads(
        fixture_output_path.read_text(encoding="utf-8")
    )
    gains_attendus = GainsDecomposes(**fixture_output["gains"])

    # ------------------------------------------------------------------
    # 4. Appel du moteur de gains bruts.
    # ------------------------------------------------------------------
    gains_effectifs, trace = calcul_gains(payroll_input, parametres)

    # ------------------------------------------------------------------
    # 5. Assertions golden (Req 11.1–11.8).
    # ------------------------------------------------------------------

    # (a) Égalité stricte des sept champs ``Decimal`` — tolérance nulle
    #     (règle 01). ``GainsDecomposes`` est ``frozen=True`` et
    #     implémente l'égalité structurelle Pydantic v2 : ``==`` compare
    #     bien les sept champs un à un.
    assert gains_effectifs == gains_attendus, (
        f"[{scenario_id}] La section gains calculée diverge de la "
        f"fixture au cent près (Req 11.1–11.5) : "
        f"{gains_effectifs!r} != {gains_attendus!r}."
    )

    # (b) Cohérence trace/gains (Req 11.8).
    assert trace.resultat == gains_attendus.brut_total, (
        f"[{scenario_id}] trace.resultat ({trace.resultat}) != "
        f"gains.brut_total ({gains_attendus.brut_total}) (Req 11.8)."
    )

    # (c) Conformité de ``trace.source`` à la liste blanche TP-1015.G
    #     2026 (Req 11.7).
    assert re.match(r"^TP-1015\.G 2026(, section .+)?$", trace.source), (
        f"[{scenario_id}] trace.source ({trace.source!r}) ne matche pas "
        f"^TP-1015\\.G 2026(, section .+)?$ (Req 11.7)."
    )


# ---------------------------------------------------------------------------
# Golden test — cotisations sociales RRQ, RQAP, AE (spec
# cotisations-sociales-qc, tâche 6.1).
#
# ``payroll_engine.rrq``, ``payroll_engine.rqap`` et
# ``payroll_engine.assurance_emploi`` n'existent pas encore à ce stade de
# la règle 06 (« tests avant code » — livrés par les tâches 9.1/10.1/11.1).
# L'import des six fonctions est donc effectué **localement**, à
# l'intérieur du test, afin qu'un ``ModuleNotFoundError`` sur ces trois
# modules ne fasse pas échouer la collecte de tout ce fichier (les golden
# tests ci-dessus, portant sur des modules déjà livrés, doivent continuer à
# passer) — même patron que ``test_calcul_gains_reproduit_fixture``.
# ---------------------------------------------------------------------------

SCENARIOS_COTISATIONS: Final[tuple[str, ...]] = (
    "QC001",
    "QC002",
    "QC003",
    "QC004",
    "QC005",
    "QC006",
)


@pytest.mark.golden
@pytest.mark.parametrize("scenario_id", SCENARIOS_COTISATIONS)
def test_cotisations_sociales_reproduisent_fixture(
    scenario_id: str,
    fixtures_inputs_dir: Path,
    fixtures_outputs_dir: Path,
) -> None:
    """Reproduit les six champs de cotisation sociale au cent près.

    **Limitation connue du corpus** (Introduction des requirements de la
    spec ``cotisations-sociales-qc`` et design §Testing Strategy
    « Limitation héritée du corpus golden ») : les six scénarios
    QC001–QC006 sont tous des paies n° 1 de la saison (``cumul_ytd`` de
    départ nul pour les six catégories). Ce golden test ne valide donc
    **pas directement** le comportement de plafonnement en cours de
    saison (cumul YTD non nul) — ce comportement reste néanmoins
    spécifié (Requirements 2 à 7) et couvert par les property tests des
    tâches 2 à 4 (Property 4 et 5, stratégie ``st_cumuls_ytd_non_nuls``),
    pas par ce corpus golden.

    QC004 confirme en particulier ``rqap_employeur == Decimal("1.77")``
    (résolution de l'anomalie — voir Introduction des requirements et
    Property 18). QC001 confirme ``rrq_employe == Decimal("87.36")``
    (valeur corrigée après ré-exécution WebRAS en 27 périodes, Req 13.6).

    Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
    """
    # Import local — voir le commentaire de section ci-dessus : les
    # modules n'existent pas encore (tâches 9.1/10.1/11.1), l'échec
    # attendu à ce stade est un ``ModuleNotFoundError`` propre, pas un
    # crash de collecte pour le reste du fichier.
    from payroll_engine.assurance_emploi import (
        calcul_ae_employe,
        calcul_ae_employeur,
    )
    from payroll_engine.rqap import calcul_rqap_employe, calcul_rqap_employeur
    from payroll_engine.rrq import calcul_rrq_employe, calcul_rrq_employeur

    scenario_fichier = scenario_id.lower()

    # ------------------------------------------------------------------
    # 1. Chargement de la fixture d'entrée → ``PayrollInput``.
    # ------------------------------------------------------------------
    fixture_input_path = fixtures_inputs_dir / f"{scenario_fichier}.json"
    assert fixture_input_path.exists(), (
        f"Fixture d'entrée manquante : {fixture_input_path}. Les tâches "
        f"14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    payroll_input = PayrollInput.model_validate_json(
        fixture_input_path.read_text(encoding="utf-8")
    )

    # ------------------------------------------------------------------
    # 2. Chargement de la fixture de sortie → sections ``gains``,
    #    ``retenues_employe`` et ``cotisations_employeur``.
    # ------------------------------------------------------------------
    fixture_output_path = fixtures_outputs_dir / f"{scenario_fichier}.json"
    assert fixture_output_path.exists(), (
        f"Fixture de sortie manquante : {fixture_output_path}. Les "
        f"tâches 14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    fixture_output = json.loads(
        fixture_output_path.read_text(encoding="utf-8")
    )
    gains = GainsDecomposes(**fixture_output["gains"])

    # ------------------------------------------------------------------
    # 3. Chargement des paramètres annuels versionnés (règle 05) — fusion
    #    Québec/Canada pour que ``parametres.assurance_emploi`` soit
    #    disponible en plus de ``parametres.rrq``/``.rqap`` (patron
    #    identique à ``tests/strategies.py::_charger_parametres_annee_2026_qc_ca``,
    #    aucune mutation — ``model_copy``).
    # ------------------------------------------------------------------
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    parametres = parametres_qc.model_copy(
        update={"assurance_emploi": parametres_ca.assurance_emploi}
    )

    # ------------------------------------------------------------------
    # 4. Appel des six fonctions.
    # ------------------------------------------------------------------
    rrq_employe, trace_rrq_employe = calcul_rrq_employe(
        payroll_input, gains, parametres
    )
    rrq_employeur, _ = calcul_rrq_employeur(payroll_input, gains, parametres)
    rqap_employe, _ = calcul_rqap_employe(payroll_input, gains, parametres)
    rqap_employeur, _ = calcul_rqap_employeur(
        payroll_input, gains, parametres
    )
    ae_employe, _ = calcul_ae_employe(payroll_input, gains, parametres)
    ae_employeur, _ = calcul_ae_employeur(payroll_input, gains, parametres)

    # ------------------------------------------------------------------
    # 5. Assertions golden (Req 13.1–13.6) — égalité stricte, tolérance
    #    nulle (règle 01).
    # ------------------------------------------------------------------
    retenues = fixture_output["retenues_employe"]
    cotisations = fixture_output["cotisations_employeur"]

    assert rrq_employe == Decimal(retenues["rrq"]["montant"]), (
        f"[{scenario_id}] rrq_employe ({rrq_employe}) != fixture "
        f"({retenues['rrq']['montant']}) (Req 13.1)."
    )
    assert rrq_employeur == Decimal(cotisations["rrq_employeur"]["montant"]), (
        f"[{scenario_id}] rrq_employeur ({rrq_employeur}) != fixture "
        f"({cotisations['rrq_employeur']['montant']}) (Req 13.2)."
    )
    assert rqap_employe == Decimal(retenues["rqap"]["montant"]), (
        f"[{scenario_id}] rqap_employe ({rqap_employe}) != fixture "
        f"({retenues['rqap']['montant']}) (Req 13.3)."
    )
    assert rqap_employeur == Decimal(
        cotisations["rqap_employeur"]["montant"]
    ), (
        f"[{scenario_id}] rqap_employeur ({rqap_employeur}) != fixture "
        f"({cotisations['rqap_employeur']['montant']}) (Req 13.3)."
    )
    assert ae_employe == Decimal(retenues["ae"]["montant"]), (
        f"[{scenario_id}] ae_employe ({ae_employe}) != fixture "
        f"({retenues['ae']['montant']}) (Req 13.4)."
    )
    assert ae_employeur == Decimal(cotisations["ae_employeur"]["montant"]), (
        f"[{scenario_id}] ae_employeur ({ae_employeur}) != fixture "
        f"({cotisations['ae_employeur']['montant']}) (Req 13.4)."
    )

    # (f) Cohérence trace/montant pour au moins ``rrq_employe`` (Req 13.5).
    assert trace_rrq_employe.resultat == rrq_employe, (
        f"[{scenario_id}] trace_rrq_employe.resultat "
        f"({trace_rrq_employe.resultat}) != rrq_employe ({rrq_employe}) "
        f"(Req 13.5)."
    )

    # (g) Assertion dédiée QC004 — résolution de l'anomalie RQAP employeur
    #     (Req 5.8, 13.3, Property 18).
    if scenario_id == "QC004":
        assert rqap_employeur == Decimal("1.77"), (
            f"[QC004] rqap_employeur ({rqap_employeur}) != Decimal('1.77') "
            f"— anomalie non résolue (Req 5.8, 13.3)."
        )

    # (h) Assertion dédiée QC001 — valeur corrigée à 27 périodes
    #     (Req 13.6).
    if scenario_id == "QC001":
        assert rrq_employe == Decimal("87.36"), (
            f"[QC001] rrq_employe ({rrq_employe}) != Decimal('87.36') "
            f"— valeur corrigée à 27 périodes attendue (Req 13.6)."
        )


# ---------------------------------------------------------------------------
# Golden test — retenues d'impôt à la source QC et fédérale (spec
# impots-retenues-source, tâche 4.1).
#
# ``payroll_engine.impot_qc`` et ``payroll_engine.impot_federal`` n'existent
# pas encore à ce stade de la règle 06 (« tests avant code » — implémentés
# par les tâches 9.1/10.1). L'import des quatre fonctions est donc effectué
# **localement**, à l'intérieur du test, afin qu'un ``ModuleNotFoundError``
# sur ces deux modules ne fasse pas échouer la collecte de tout ce fichier
# (les golden tests ci-dessus, portant sur des modules déjà livrés, doivent
# continuer à passer) — même patron que
# ``test_cotisations_sociales_reproduisent_fixture``.
# ---------------------------------------------------------------------------

SCENARIOS_IMPOTS: Final[tuple[str, ...]] = (
    "QC001",
    "QC002",
    "QC003",
    "QC004",
    "QC005",
    "QC006",
)


@pytest.mark.golden
@pytest.mark.parametrize("scenario_id", SCENARIOS_IMPOTS)
def test_impots_reproduisent_fixture(
    scenario_id: str,
    fixtures_inputs_dir: Path,
    fixtures_outputs_dir: Path,
) -> None:
    """Reproduit les quatre champs d'impôt au cent près (Requirement 11).

    Vérifie, pour chacun des six scénarios QC001–QC006, que les quatre
    fonctions livrées par la spec ``impots-retenues-source``
    (``calcul_impot_qc_formule``, ``calcul_impot_qc_retenu``,
    ``calcul_impot_federal_formule``, ``calcul_impot_federal_retenu``)
    reproduisent au cent près les quatre champs
    ``retenues_employe.{impot_qc_formule, impot_qc_retenu,
    impot_federal_formule, impot_federal_retenu}.montant`` des fixtures de
    sortie (Req 11.1–11.4).

    **Comportement sous le seuil d'imposition** (Requirement 7) : QC004 et
    QC006 produisent ``impot_qc_formule == Decimal("0.00")`` et
    ``impot_federal_formule == Decimal("0.00")`` **par la formule
    elle-même** — le revenu annualisé net de crédit personnel est négatif
    ou nul, ce qui est un comportement normal et attendu de la formule à
    paliers progressifs, et non un cas d'erreur ni une variante du
    court-circuit d'exonération. QC004 valide ce comportement
    indépendamment de tout mécanisme d'exonération (Req 11.7).

    QC001 est le seul scénario sans exonération active où la formule
    produit un impôt strictement positif pour les deux juridictions :
    ``impot_qc_formule == Decimal("104.56")`` et ``impot_federal_formule
    == Decimal("86.25")`` (Req 11.6).

    **Limitation connue** : ce test nécessite que les paramètres 2026
    soient intégralement renseignés (paliers, crédits convertibles,
    déduction pour travailleur, montant canadien pour emploi, plafond de
    cotisation de base RRQ, abattement du Québec) — voir tâche 6. Tant que
    ces champs portent la sentinelle ``"TO_FILL"``, ce test échoue par
    ``MissingParameterError`` (et non par écart de logique), et tant que
    les tâches 9.1/10.1 n'ont pas livré les modules, il échoue par
    ``ModuleNotFoundError`` à l'exécution (la collecte reste saine grâce à
    l'import local).

    Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7
    """
    # Import local — voir le commentaire de section ci-dessus : les
    # modules n'existent pas encore (tâches 9.1/10.1), l'échec attendu à
    # ce stade est un ``ModuleNotFoundError`` propre, pas un crash de
    # collecte pour le reste du fichier.
    from payroll_engine.impot_federal import (
        calcul_impot_federal_formule,
        calcul_impot_federal_retenu,
    )
    from payroll_engine.impot_qc import (
        calcul_impot_qc_formule,
        calcul_impot_qc_retenu,
    )

    scenario_fichier = scenario_id.lower()

    # ------------------------------------------------------------------
    # 1. Chargement de la fixture d'entrée → ``PayrollInput``.
    # ------------------------------------------------------------------
    fixture_input_path = fixtures_inputs_dir / f"{scenario_fichier}.json"
    assert fixture_input_path.exists(), (
        f"Fixture d'entrée manquante : {fixture_input_path}. Les tâches "
        f"14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    payroll_input = PayrollInput.model_validate_json(
        fixture_input_path.read_text(encoding="utf-8")
    )

    # ------------------------------------------------------------------
    # 2. Chargement de la fixture de sortie → sections ``gains`` et
    #    ``retenues_employe``.
    # ------------------------------------------------------------------
    fixture_output_path = fixtures_outputs_dir / f"{scenario_fichier}.json"
    assert fixture_output_path.exists(), (
        f"Fixture de sortie manquante : {fixture_output_path}. Les "
        f"tâches 14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    fixture_output = json.loads(
        fixture_output_path.read_text(encoding="utf-8")
    )
    gains = GainsDecomposes(**fixture_output["gains"])

    # ------------------------------------------------------------------
    # 3. Chargement des paramètres annuels versionnés (règle 05) — fusion
    #    Québec/Canada. La racine Québec porte ``rrq``/``rqap``/
    #    ``impot_quebec`` ; on y greffe ``assurance_emploi`` et
    #    ``impot_federal`` de la racine Canada. ``calcul_impot_federal_formule``
    #    a besoin **à la fois** de ``rrq``/``rqap``/``assurance_emploi``
    #    (mécanisme K2Q, design §Components §4) et de ``impot_federal``
    #    (paliers, crédits, montant emploi canadien, plafond cotisation
    #    base RRQ, abattement du Québec). Aucune mutation — ``model_copy``
    #    (patron identique à
    #    ``test_cotisations_sociales_reproduisent_fixture`` et à la fixture
    #    ``parametres_2026_qc_ca_federal`` de ``test_impot_federal.py``).
    # ------------------------------------------------------------------
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    parametres = parametres_qc.model_copy(
        update={
            "assurance_emploi": parametres_ca.assurance_emploi,
            "impot_federal": parametres_ca.impot_federal,
        }
    )

    # ------------------------------------------------------------------
    # 4. Appel des quatre fonctions.
    # ------------------------------------------------------------------
    impot_qc_formule, trace_impot_qc_formule = calcul_impot_qc_formule(
        payroll_input, gains, parametres
    )
    impot_qc_retenu, _ = calcul_impot_qc_retenu(
        payroll_input, gains, parametres
    )
    impot_federal_formule, _ = calcul_impot_federal_formule(
        payroll_input, gains, parametres
    )
    impot_federal_retenu, _ = calcul_impot_federal_retenu(
        payroll_input, gains, parametres
    )

    # ------------------------------------------------------------------
    # 5. Assertions golden (Req 11.1–11.4) — égalité stricte des quatre
    #    champs ``montant``, tolérance nulle (règle 01).
    # ------------------------------------------------------------------
    retenues = fixture_output["retenues_employe"]

    assert impot_qc_formule == Decimal(
        str(retenues["impot_qc_formule"]["montant"])
    ), (
        f"[{scenario_id}] impot_qc_formule ({impot_qc_formule}) != fixture "
        f"({retenues['impot_qc_formule']['montant']}) (Req 11.1)."
    )
    assert impot_qc_retenu == Decimal(
        str(retenues["impot_qc_retenu"]["montant"])
    ), (
        f"[{scenario_id}] impot_qc_retenu ({impot_qc_retenu}) != fixture "
        f"({retenues['impot_qc_retenu']['montant']}) (Req 11.2)."
    )
    assert impot_federal_formule == Decimal(
        str(retenues["impot_federal_formule"]["montant"])
    ), (
        f"[{scenario_id}] impot_federal_formule ({impot_federal_formule}) "
        f"!= fixture ({retenues['impot_federal_formule']['montant']}) "
        f"(Req 11.3)."
    )
    assert impot_federal_retenu == Decimal(
        str(retenues["impot_federal_retenu"]["montant"])
    ), (
        f"[{scenario_id}] impot_federal_retenu ({impot_federal_retenu}) != "
        f"fixture ({retenues['impot_federal_retenu']['montant']}) "
        f"(Req 11.4)."
    )

    # ------------------------------------------------------------------
    # 6. Cohérence trace/montant pour au moins ``impot_qc_formule``
    #    (Req 11.5).
    # ------------------------------------------------------------------
    assert trace_impot_qc_formule.resultat == impot_qc_formule, (
        f"[{scenario_id}] trace_impot_qc_formule.resultat "
        f"({trace_impot_qc_formule.resultat}) != impot_qc_formule "
        f"({impot_qc_formule}) (Req 11.5)."
    )

    # ------------------------------------------------------------------
    # 7. Assertion dédiée QC001 — seul scénario sans exonération où la
    #    formule produit un impôt strictement positif pour les deux
    #    juridictions (Req 11.6).
    # ------------------------------------------------------------------
    if scenario_id == "QC001":
        assert impot_qc_formule == Decimal("104.56"), (
            f"[QC001] impot_qc_formule ({impot_qc_formule}) != "
            f"Decimal('104.56') (Req 11.6)."
        )
        assert impot_federal_formule == Decimal("86.25"), (
            f"[QC001] impot_federal_formule ({impot_federal_formule}) != "
            f"Decimal('86.25') (Req 11.6)."
        )

    # ------------------------------------------------------------------
    # 8. Assertion dédiée QC004 et QC006 — comportement sous le seuil
    #    d'imposition : la formule elle-même produit un impôt nul
    #    (Req 7, Req 11.7). QC004 valide ce comportement indépendamment
    #    de tout mécanisme d'exonération.
    # ------------------------------------------------------------------
    if scenario_id in ("QC004", "QC006"):
        assert impot_qc_formule == Decimal("0.00"), (
            f"[{scenario_id}] impot_qc_formule ({impot_qc_formule}) != "
            f"Decimal('0.00') — comportement sous le seuil d'imposition "
            f"attendu (Req 7, Req 11.7)."
        )
        assert impot_federal_formule == Decimal("0.00"), (
            f"[{scenario_id}] impot_federal_formule "
            f"({impot_federal_formule}) != Decimal('0.00') — comportement "
            f"sous le seuil d'imposition attendu (Req 7, Req 11.7)."
        )


# ---------------------------------------------------------------------------
# Golden test — charges patronales FSS, CNESST, CNT et assemblage
# ``CotisationsEmployeur`` (spec charges-patronales, tâche 5.1).
#
# ``payroll_engine.charges_patronales`` n'existe pas encore à ce stade de la
# règle 06 (« tests avant code » — le module est livré par la tâche 11.1).
# L'import des quatre fonctions est donc effectué **localement**, à
# l'intérieur du test, afin qu'un ``ModuleNotFoundError`` sur ce module ne
# fasse pas échouer la collecte de tout ce fichier (les golden tests
# ci-dessus, portant sur des modules déjà livrés, doivent continuer à
# passer) — même patron que ``test_impots_reproduisent_fixture``.
# ---------------------------------------------------------------------------

SCENARIOS_CHARGES: Final[tuple[str, ...]] = (
    "QC001",
    "QC002",
    "QC003",
    "QC004",
    "QC005",
    "QC006",
)


@pytest.mark.golden
@pytest.mark.parametrize("scenario_id", SCENARIOS_CHARGES)
def test_charges_patronales_reproduisent_fixture(
    scenario_id: str,
    fixtures_inputs_dir: Path,
    fixtures_outputs_dir: Path,
) -> None:
    """Reproduit les trois charges patronales et l'assemblage au cent près.

    Vérifie, pour chacun des six scénarios QC001–QC006, que les trois
    fonctions de calcul livrées par la spec ``charges-patronales``
    (``calcul_fss``, ``calcul_cnesst``, ``calcul_cnt``) reproduisent au
    cent près les champs ``cotisations_employeur.{fss, cnesst, cnt}.montant``
    des fixtures de sortie (Req 11.1–11.3), et que
    ``assembler_cotisations_employeur`` reporte le drapeau
    ``cnesst_en_attente_classification`` et le ``total_cotisations_employeur``
    de la fixture (Req 11.2, identité d'agrégation).

    **Limitation connue** : ce test nécessite que les paramètres ``cnt``
    2026 soient renseignés (``taux = "0.0006"``, ``base_admissible =
    "103000.00"`` d'après LE-39.0.2 (2026-01)) — voir tâche 9 — et que les
    fixtures QC001–QC006 soient régénérées pour porter la CNT calculée (au
    lieu de ``0,00``), les sources corrigées (CNESST → ``www.cnesst.gouv.qc.ca``,
    CNT → ``LE-39.0.2``) et les totaux recalculés — voir tâche 10 (Req 11.6).
    Tant que la section ``cnt`` porte la sentinelle ``"TO_FILL"``, ce test
    échoue par ``MissingParameterError`` (et non par écart de logique) ; tant
    que la tâche 11.1 n'a pas livré le module, il échoue par
    ``ModuleNotFoundError`` à l'exécution (la collecte reste saine grâce à
    l'import local).

    Validates: Requirements 11.1, 11.2, 11.3, 11.5, 11.6
    """
    # Import local — voir le commentaire de section ci-dessus : le module
    # n'existe pas encore (tâche 11.1), l'échec attendu à ce stade est un
    # ``ModuleNotFoundError`` propre, pas un crash de collecte pour le reste
    # du fichier.
    from payroll_engine.charges_patronales import (
        assembler_cotisations_employeur,
        calcul_cnesst,
        calcul_cnt,
        calcul_fss,
    )

    scenario_fichier = scenario_id.lower()

    # ------------------------------------------------------------------
    # 1. Chargement de la fixture d'entrée → ``PayrollInput``.
    # ------------------------------------------------------------------
    fixture_input_path = fixtures_inputs_dir / f"{scenario_fichier}.json"
    assert fixture_input_path.exists(), (
        f"Fixture d'entrée manquante : {fixture_input_path}. Les tâches "
        f"14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    payroll_input = PayrollInput.model_validate_json(
        fixture_input_path.read_text(encoding="utf-8")
    )

    # ------------------------------------------------------------------
    # 2. Chargement de la fixture de sortie → section ``gains`` →
    #    ``GainsDecomposes`` (seule source du Salaire_Assujetti).
    # ------------------------------------------------------------------
    fixture_output_path = fixtures_outputs_dir / f"{scenario_fichier}.json"
    assert fixture_output_path.exists(), (
        f"Fixture de sortie manquante : {fixture_output_path}. Les "
        f"tâches 14.1/14.2 de moteur-paie-contrats doivent produire les "
        f"fixtures QC001–QC006 avant ce golden test."
    )
    fixture_output = json.loads(
        fixture_output_path.read_text(encoding="utf-8")
    )
    gains = GainsDecomposes(**fixture_output["gains"])

    # ------------------------------------------------------------------
    # 3. Chargement des paramètres annuels versionnés (règle 05) — fusion
    #    Québec/Canada. La racine Québec porte ``fss``/``cnesst``/``cnt``
    #    (consommés par les trois fonctions de calcul de charges) ; on y
    #    greffe ``assurance_emploi`` de la racine Canada car
    #    ``assembler_cotisations_employeur`` **invoque** ``calcul_ae_employeur``
    #    (étape 3), qui lit ``parametres.assurance_emploi``. Aucune mutation
    #    — ``model_copy`` (patron identique à
    #    ``test_cotisations_sociales_reproduisent_fixture``).
    # ------------------------------------------------------------------
    parametres_qc = load_parameters(2026, Juridiction.QUEBEC)
    parametres_ca = load_parameters(2026, Juridiction.CANADA)
    parametres = parametres_qc.model_copy(
        update={"assurance_emploi": parametres_ca.assurance_emploi}
    )

    # ------------------------------------------------------------------
    # 4. Appel des trois fonctions de calcul et de l'assemblage.
    # ------------------------------------------------------------------
    fss, trace_fss = calcul_fss(payroll_input, gains, parametres)
    cnesst, _ = calcul_cnesst(payroll_input, gains, parametres)
    cnt, _ = calcul_cnt(payroll_input, gains, parametres)
    cot = assembler_cotisations_employeur(payroll_input, gains, parametres)

    # ------------------------------------------------------------------
    # 5. Assertions golden (Req 11.1–11.3) — égalité stricte des trois
    #    champs ``montant``, tolérance nulle (règle 01).
    # ------------------------------------------------------------------
    cotisations = fixture_output["cotisations_employeur"]

    assert fss == Decimal(cotisations["fss"]["montant"]), (
        f"[{scenario_id}] fss ({fss}) != fixture "
        f"({cotisations['fss']['montant']}) (Req 11.1)."
    )
    assert cnesst == Decimal(cotisations["cnesst"]["montant"]), (
        f"[{scenario_id}] cnesst ({cnesst}) != fixture "
        f"({cotisations['cnesst']['montant']}) (Req 11.2)."
    )
    assert cnt == Decimal(cotisations["cnt"]["montant"]), (
        f"[{scenario_id}] cnt ({cnt}) != fixture "
        f"({cotisations['cnt']['montant']}) (Req 11.3)."
    )

    # ------------------------------------------------------------------
    # 6. Assemblage — report du drapeau CNESST (Req 11.2) et identité
    #    d'agrégation ``total_cotisations_employeur`` (Req 11.1–11.3). Le
    #    drapeau ``cnesst_en_attente_classification`` n'a aucun effet sur le
    #    total : ``cnesst.montant`` (même provisoire) est toujours inclus.
    # ------------------------------------------------------------------
    assert (
        cot.cnesst_en_attente_classification
        == cotisations["cnesst_en_attente_classification"]
    ), (
        f"[{scenario_id}] cnesst_en_attente_classification "
        f"({cot.cnesst_en_attente_classification}) != fixture "
        f"({cotisations['cnesst_en_attente_classification']}) (Req 11.2)."
    )
    assert cot.total_cotisations_employeur == Decimal(
        cotisations["total_cotisations_employeur"]
    ), (
        f"[{scenario_id}] total_cotisations_employeur "
        f"({cot.total_cotisations_employeur}) != fixture "
        f"({cotisations['total_cotisations_employeur']})."
    )

    # ------------------------------------------------------------------
    # 7. Cohérence trace/montant pour ``calcul_fss`` (Req 5.5, Req 11.5).
    # ------------------------------------------------------------------
    assert trace_fss.resultat == fss, (
        f"[{scenario_id}] trace_fss.resultat ({trace_fss.resultat}) != "
        f"fss ({fss}) (Req 5.5)."
    )
