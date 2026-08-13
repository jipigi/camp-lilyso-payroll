"""Property tests et tests d'exemple pour `app/logique_metier/formulaire_paie.py`.

Spec de référence : ``interface-streamlit`` — tâche 7.1 (squelette du
fichier et test de la Property 4).
Design de référence : ``design.md`` §Components §6 (`formulaire_paie.py`
— dérivation de dates, assemblage, génération d'identifiants) et
§Correctness Properties 4, 10, 11, 13.

Ce fichier porte l'ensemble des property tests et tests d'exemple de
`formulaire_paie.py` (`convertir_numero_en_id`,
`deriver_semaines_constituantes`, `construire_payroll_input`,
`generer_id_paie`). La tâche 7.1 pose le **squelette** : le module
docstring, les imports, la Property 4 (classe
``TestConvertirNumeroEnId``) et son test d'exemple d'erreur de saisie.
La tâche 7.2 a ajouté ``TestDerivationSemaines`` (Property 10). La
tâche 7.3 a ajouté ``TestConstructionPayrollInput`` (Property 11). La
tâche 7.4 a ajouté ``TestGenerationIdPaie`` (Property 13). La tâche 7.5
ajoute ``TestPropagationErreursFormulaire`` — tests d'exemple de
propagation des erreurs de validation, **dernière classe de ce
fichier** : elle achève la section 7 du plan d'implémentation
(property tests et tests d'exemple de `formulaire_paie.py`).

Les **4 propriétés** couvertes par ce fichier de test au total (design.md
§Correctness Properties) :

4. **Property 4 — Conversion du numéro d'employé en `id`**.
10. **Property 10 — Dérivation mécanique des `WeekSegment`**.
11. **Property 11 — Assemblage du `PayrollInput` depuis le
    Formulaire_Paie**.
13. **Property 13 — Génération déterministe de `id_paie`**.

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/formulaire_paie.py`` n'existe **pas encore** à ce
stade (implémentation prévue aux tâches 17.1/17.2). Ce fichier importe
donc localement les fonctions du module sous test (au sein de chaque
test) afin que la **collecte** pytest de ce fichier — et de l'ensemble
de ``tests/app/`` — réussisse même tant que le module cible est absent.
À l'exécution, chaque test échoue alors avec ``ModuleNotFoundError`` sur
``app.logique_metier.formulaire_paie`` — c'est le comportement
**attendu et correct** (état rouge intentionnel) tant que la tâche 17
(implémentation) n'a pas été réalisée (checkpoint de la tâche 11 du
plan).

Règle 01 : aucune conversion `float` n'est introduite ici — `convertir_
numero_en_id` manipule exclusivement des chaînes et des entiers (Req
4.7, pas de montant monétaire).
Règle 03 : le test d'exemple ``test_exemple_numero_non_entier_leve_
value_error`` confirme qu'aucun garde-fou de périmètre supplémentaire
n'est ajouté par `convertir_numero_en_id` — seule l'erreur `ValueError`
native de `int(...)` est propagée, sans interception ni message
personnalisé.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from models.cumuls import CumulsYTD
from models.enums import FrequencePaie
from models.exceptions import UnsupportedPayrollCase
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_input import HeuresParSemaine, PayrollInput
from tests.app.strategies import st_dates_periode_valide, st_employee_valide
from tests.strategies import (
    st_heures_par_semaine,
    st_payroll_input,
    st_taux_horaire,
)

__all__: list[str] = []


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
# Property 4 — Conversion du numéro d'employé en `id`
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 4: Conversion du numéro d'employé en id
#
# *Pour tout* entier positif raisonnable (`1` à `999`),
# `convertir_numero_en_id(str(n))` retourne exactement `f"EMP{n:03d}"`.
#
# _Requirements: 4.7_
# _Design: §Components §6 ; §Correctness Properties 4_


class TestConvertirNumeroEnId:
    """Property 4 — conversion du numéro d'employé saisi en `id` `EMPnnn`."""

    # Feature: interface-streamlit, Property 4: Conversion du numéro d'employé en id
    @pytest.mark.property
    @given(n=st.integers(min_value=1, max_value=999))
    @settings_large_input
    def test_retourne_exactement_emp_zero_paddee_sur_3_chiffres(
        self, n: int
    ) -> None:
        """Property 4 (Req 4.7).

        Pour tout entier `n` entre 1 et 999, `convertir_numero_en_id(str(n))`
        doit retourner exactement `f"EMP{n:03d}"` (zero-padding sur 3
        chiffres, préfixe `EMP` fixe) — aucune autre transformation.
        """
        from app.logique_metier.formulaire_paie import convertir_numero_en_id

        resultat = convertir_numero_en_id(str(n))

        assert resultat == f"EMP{n:03d}", (
            f"convertir_numero_en_id({str(n)!r}) doit retourner "
            f"{f'EMP{n:03d}'!r}, obtenu {resultat!r}."
        )

    # Feature: interface-streamlit, Property 4: Conversion du numéro d'employé en id
    def test_exemple_numero_non_entier_leve_value_error(self) -> None:
        """Test d'exemple — saisie non entière (Req 4.7, règle 03).

        `convertir_numero_en_id("abc")` doit laisser se propager le
        `ValueError` natif levé par `int("abc")`, sans aucun garde-fou de
        périmètre supplémentaire ni message personnalisé (règle 03 — ce
        n'est pas un cas hors matrice, seulement une erreur de saisie de
        forme).
        """
        from app.logique_metier.formulaire_paie import convertir_numero_en_id

        with pytest.raises(ValueError):
            convertir_numero_en_id("abc")


# ---------------------------------------------------------------------------
# Property 10 — Dérivation mécanique des `WeekSegment`
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 10: Dérivation mécanique des WeekSegment
#
# *Pour toute* paire de dates telle que `date_fin == date_debut + 13 jours`
# (via `st_dates_periode_valide`, tâche 1.1), `deriver_semaines_constituantes`
# produit deux `WeekSegment` couvrant `[date_debut, date_debut+6]` et
# `[date_debut+7, date_fin]`, satisfaisant par construction les invariants
# de `PayPeriod` (contiguïté, couverture).
#
# _Requirements: 7.3_
# _Design: §Components §6 ; §Correctness Properties 10_


class TestDerivationSemaines:
    """Property 10 — dérivation mécanique des `WeekSegment` constituants."""

    # Feature: interface-streamlit, Property 10: Dérivation mécanique des WeekSegment
    @pytest.mark.property
    @given(dates=st_dates_periode_valide())
    @settings_large_input
    def test_deux_semaines_couvrent_exactement_les_bornes_attendues(
        self, dates: tuple
    ) -> None:
        """Property 10 (Req 7.3).

        Pour toute paire `(date_debut, date_fin)` telle que
        `date_fin == date_debut + 13 jours`,
        `deriver_semaines_constituantes(date_debut, date_fin)` doit
        produire deux `WeekSegment` :

        - la première couvre `[date_debut, date_debut + 6 jours]` ;
        - la seconde couvre `[date_debut + 7 jours, date_fin]`.
        """
        from app.logique_metier.formulaire_paie import (
            deriver_semaines_constituantes,
        )

        date_debut, date_fin = dates

        semaine_1, semaine_2 = deriver_semaines_constituantes(date_debut, date_fin)

        assert semaine_1.date_debut == date_debut, (
            "La première semaine doit débuter à date_debut, obtenu "
            f"{semaine_1.date_debut!r} pour date_debut={date_debut!r}."
        )
        assert semaine_1.date_fin == date_debut + timedelta(days=6), (
            "La première semaine doit se terminer à date_debut + 6 jours, "
            f"obtenu {semaine_1.date_fin!r}."
        )
        assert semaine_2.date_debut == date_debut + timedelta(days=7), (
            "La seconde semaine doit débuter à date_debut + 7 jours, "
            f"obtenu {semaine_2.date_debut!r}."
        )
        assert semaine_2.date_fin == date_fin, (
            "La seconde semaine doit se terminer à date_fin, obtenu "
            f"{semaine_2.date_fin!r} pour date_fin={date_fin!r}."
        )

    # Feature: interface-streamlit, Property 10: Dérivation mécanique des WeekSegment
    @pytest.mark.property
    @given(dates=st_dates_periode_valide())
    @settings_large_input
    def test_semaines_assemblees_satisfont_invariants_payperiod(
        self, dates: tuple
    ) -> None:
        """Property 10 (Req 7.3) — assemblage complet dans un `PayPeriod`.

        Les deux `WeekSegment` produits, assemblés dans un `PayPeriod`
        complet (`date_debut`, `date_fin`, fréquence
        `AUX_DEUX_SEMAINES`), ne doivent lever aucune erreur de
        validation de contiguïté/couverture — confirmant que la
        dérivation satisfait par construction les invariants déjà
        portés par `PayPeriod`.
        """
        from app.logique_metier.formulaire_paie import (
            deriver_semaines_constituantes,
        )

        date_debut, date_fin = dates

        semaine_1, semaine_2 = deriver_semaines_constituantes(date_debut, date_fin)

        pay_period = PayPeriod(
            numero_periode=1,
            date_debut=date_debut,
            date_fin=date_fin,
            date_paiement=date_fin + timedelta(days=5),
            frequence=FrequencePaie.AUX_DEUX_SEMAINES,
            nb_periodes_annuelles=26,
            annee_fiscale=date_debut.year,
            semaines=(semaine_1, semaine_2),
        )

        assert pay_period.semaines == (semaine_1, semaine_2)


# ---------------------------------------------------------------------------
# Property 11 — Assemblage du `PayrollInput` depuis le Formulaire_Paie
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 11: Assemblage du PayrollInput depuis le Formulaire_Paie
#
# *Pour toute* combinaison valide (Fiche_Employe, dates cohérentes, heures,
# paramètres effectifs), `construire_payroll_input` produit un
# `PayrollInput` dont chaque champ scalaire égale l'argument fourni,
# `pay_period.annee_fiscale` égale `annee_fiscale`, et `pay_period.semaines`
# égale le résultat de `deriver_semaines_constituantes` sur les mêmes
# dates.
#
# _Requirements: 6.3, 7.7_
# _Design: §Components §6 ; §Correctness Properties 11_


@st.composite
def _st_kwargs_construction_payroll_input(draw: st.DrawFn) -> dict:
    """Kwargs valides et cohérents pour `construire_payroll_input` (Property 11).

    Compose `st_employee_valide` et `st_dates_periode_valide` (tâche 1.1)
    avec des générateurs locaux pour les heures par semaine et les
    paramètres effectifs de rémunération/fiscaux, et un `CumulsYTD.zero`
    apparié à l'employé et à l'année fiscale — même patron que
    `tests/strategies.py::st_payroll_input` (réutilisé directement pour
    les bornes `Decimal` de rémunération via `st_heures_par_semaine` /
    `st_taux_horaire`, sans duplication).

    `annee_fiscale` est fixée à `date_debut.year` : aucun invariant du
    design ne lie explicitement `annee_fiscale` aux dates de la période,
    mais ce choix reste réaliste et garantit par construction
    `cumuls_debut.annee_civile == annee_fiscale` (contrainte de
    cohérence croisée déjà portée par `PayrollInput`, Req 3.1).
    `date_paiement` est fixée à `date_fin + 5 jours`, cohérent avec le
    test d'exemple de la tâche 7.2 (`TestDerivationSemaines`).
    """
    employee = draw(st_employee_valide())
    date_debut, date_fin = draw(st_dates_periode_valide())
    annee_fiscale = date_debut.year

    heures_semaine_1 = HeuresParSemaine(
        heures_normales=draw(st_heures_par_semaine()),
        heures_supplementaires=draw(st_heures_par_semaine()),
    )
    heures_semaine_2 = HeuresParSemaine(
        heures_normales=draw(st_heures_par_semaine()),
        heures_supplementaires=draw(st_heures_par_semaine()),
    )

    def _decimal_non_negatif(max_value: Decimal) -> Decimal:
        return draw(
            st.decimals(
                min_value=Decimal("0.00"),
                max_value=max_value,
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        )

    cumuls_debut = CumulsYTD.zero(employe_id=employee.id, annee_civile=annee_fiscale)

    return {
        "employee": employee,
        "numero_periode": draw(st.integers(min_value=1, max_value=27)),
        "date_debut": date_debut,
        "date_fin": date_fin,
        "date_paiement": date_fin + timedelta(days=5),
        "annee_fiscale": annee_fiscale,
        "nb_periodes_annuelles": draw(st.integers(min_value=1, max_value=53)),
        "heures_semaine_1": heures_semaine_1,
        "heures_semaine_2": heures_semaine_2,
        "taux_horaire_effectif": draw(st_taux_horaire()),
        "taux_vacances": draw(st.sampled_from([Decimal("0.04"), Decimal("0.06")])),
        "jours_feries_manuels": _decimal_non_negatif(Decimal("500.00")),
        "montant_total_TP1015_3_effectif": _decimal_non_negatif(Decimal("50000.00")),
        "exoneration_TP1015_3_effectif": draw(st.booleans()),
        "retenue_additionnelle_QC_effective": _decimal_non_negatif(Decimal("500.00")),
        "montant_total_TD1_effectif": _decimal_non_negatif(Decimal("50000.00")),
        "exoneration_TD1_effective": draw(st.booleans()),
        "retenue_additionnelle_federale_effective": _decimal_non_negatif(
            Decimal("500.00")
        ),
        "cumuls_debut": cumuls_debut,
    }


class TestConstructionPayrollInput:
    """Property 11 — assemblage du `PayrollInput` depuis le Formulaire_Paie."""

    # Feature: interface-streamlit, Property 11: Assemblage du PayrollInput depuis le Formulaire_Paie
    @pytest.mark.property
    @given(kwargs=_st_kwargs_construction_payroll_input())
    @settings_large_input
    def test_champs_scalaires_et_pay_period_egalent_les_arguments_fournis(
        self, kwargs: dict
    ) -> None:
        """Property 11 (Req 6.3, 7.7).

        Pour toute combinaison valide de Fiche_Employe, dates cohérentes,
        heures par semaine et paramètres effectifs,
        `construire_payroll_input(**kwargs)` doit produire un
        `PayrollInput` dont :

        - chaque champ scalaire (`taux_horaire_effectif`, `taux_vacances`,
          `jours_feries_manuels`, les 6 champs TP-1015.3/TD1 effectifs,
          `cumuls_debut`) égale exactement l'argument fourni ;
        - `pay_period.annee_fiscale` égale `annee_fiscale` ;
        - `pay_period.semaines` — bornes de dates uniquement — égale le
          résultat de `deriver_semaines_constituantes` sur les mêmes
          dates. Les heures des `WeekSegment` produits par
          `deriver_semaines_constituantes` sont des heures provisoires
          à `Decimal("0")` (voir Property 10) et ne représentent pas les
          heures effectivement saisies (`heures_semaine_1`/
          `heures_semaine_2`, portées par
          `PayrollInput.heures_par_semaine`) — la comparaison porte donc
          strictement sur les dates de chaque semaine, pas sur l'égalité
          complète de l'objet `WeekSegment`.
        """
        from app.logique_metier.formulaire_paie import (
            construire_payroll_input,
            deriver_semaines_constituantes,
        )

        resultat = construire_payroll_input(**kwargs)

        # -- Champs scalaires (Req 7.7) ------------------------------------
        assert resultat.employee == kwargs["employee"], (
            "`employee` du PayrollInput doit égaler l'argument fourni."
        )
        assert resultat.taux_horaire_effectif == kwargs["taux_horaire_effectif"], (
            "`taux_horaire_effectif` doit égaler l'argument fourni, obtenu "
            f"{resultat.taux_horaire_effectif!r}."
        )
        assert resultat.taux_vacances == kwargs["taux_vacances"], (
            "`taux_vacances` doit égaler l'argument fourni, obtenu "
            f"{resultat.taux_vacances!r}."
        )
        assert resultat.jours_feries_manuels == kwargs["jours_feries_manuels"], (
            "`jours_feries_manuels` doit égaler l'argument fourni, obtenu "
            f"{resultat.jours_feries_manuels!r}."
        )
        assert (
            resultat.montant_total_TP1015_3_effectif
            == kwargs["montant_total_TP1015_3_effectif"]
        ), (
            "`montant_total_TP1015_3_effectif` doit égaler l'argument "
            f"fourni, obtenu {resultat.montant_total_TP1015_3_effectif!r}."
        )
        assert (
            resultat.exoneration_TP1015_3_effectif
            == kwargs["exoneration_TP1015_3_effectif"]
        ), (
            "`exoneration_TP1015_3_effectif` doit égaler l'argument "
            f"fourni, obtenu {resultat.exoneration_TP1015_3_effectif!r}."
        )
        assert (
            resultat.retenue_additionnelle_QC_effective
            == kwargs["retenue_additionnelle_QC_effective"]
        ), (
            "`retenue_additionnelle_QC_effective` doit égaler l'argument "
            f"fourni, obtenu {resultat.retenue_additionnelle_QC_effective!r}."
        )
        assert (
            resultat.montant_total_TD1_effectif
            == kwargs["montant_total_TD1_effectif"]
        ), (
            "`montant_total_TD1_effectif` doit égaler l'argument fourni, "
            f"obtenu {resultat.montant_total_TD1_effectif!r}."
        )
        assert (
            resultat.exoneration_TD1_effective == kwargs["exoneration_TD1_effective"]
        ), (
            "`exoneration_TD1_effective` doit égaler l'argument fourni, "
            f"obtenu {resultat.exoneration_TD1_effective!r}."
        )
        assert (
            resultat.retenue_additionnelle_federale_effective
            == kwargs["retenue_additionnelle_federale_effective"]
        ), (
            "`retenue_additionnelle_federale_effective` doit égaler "
            "l'argument fourni, obtenu "
            f"{resultat.retenue_additionnelle_federale_effective!r}."
        )
        assert resultat.cumuls_debut == kwargs["cumuls_debut"], (
            "`cumuls_debut` doit égaler l'argument fourni, obtenu "
            f"{resultat.cumuls_debut!r}."
        )
        assert resultat.heures_par_semaine == (
            kwargs["heures_semaine_1"],
            kwargs["heures_semaine_2"],
        ), (
            "`heures_par_semaine` doit égaler exactement "
            "`(heures_semaine_1, heures_semaine_2)`, obtenu "
            f"{resultat.heures_par_semaine!r}."
        )

        # -- annee_fiscale du PayPeriod (Req 6.3) --------------------------
        assert resultat.pay_period.annee_fiscale == kwargs["annee_fiscale"], (
            "`pay_period.annee_fiscale` doit égaler l'argument "
            f"`annee_fiscale` fourni, obtenu {resultat.pay_period.annee_fiscale!r}."
        )

        # -- WeekSegment dérivés des mêmes dates (Req 7.3, comparaison sur
        #    les dates uniquement — voir docstring ci-dessus) ---------------
        semaine_1_attendue, semaine_2_attendue = deriver_semaines_constituantes(
            kwargs["date_debut"], kwargs["date_fin"]
        )
        assert len(resultat.pay_period.semaines) == 2, (
            "`pay_period.semaines` doit contenir exactement 2 `WeekSegment`, "
            f"obtenu {len(resultat.pay_period.semaines)}."
        )
        semaine_1_obtenue, semaine_2_obtenue = resultat.pay_period.semaines
        assert (
            semaine_1_obtenue.date_debut,
            semaine_1_obtenue.date_fin,
        ) == (
            semaine_1_attendue.date_debut,
            semaine_1_attendue.date_fin,
        ), (
            "Les dates de la première semaine de `pay_period.semaines` "
            "doivent égaler celles produites par "
            f"`deriver_semaines_constituantes`, obtenu "
            f"({semaine_1_obtenue.date_debut!r}, {semaine_1_obtenue.date_fin!r})."
        )
        assert (
            semaine_2_obtenue.date_debut,
            semaine_2_obtenue.date_fin,
        ) == (
            semaine_2_attendue.date_debut,
            semaine_2_attendue.date_fin,
        ), (
            "Les dates de la seconde semaine de `pay_period.semaines` "
            "doivent égaler celles produites par "
            f"`deriver_semaines_constituantes`, obtenu "
            f"({semaine_2_obtenue.date_debut!r}, {semaine_2_obtenue.date_fin!r})."
        )


# ---------------------------------------------------------------------------
# Property 13 — Génération déterministe de `id_paie`
# ---------------------------------------------------------------------------
#
# Feature: interface-streamlit, Property 13: Génération déterministe de id_paie
#
# *Pour tout* `employe_id`, `annee_fiscale`, `numero_periode` (`1` à `27`)
# et *toute* `version` entière `>= 1`, `generer_id_paie(...)` produit
# exactement `f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:02d}-v{version}"`.
#
# _Requirements: 10.1, 13.3_
# _Design: §Components §6 ; §Correctness Properties 13_


class TestGenerationIdPaie:
    """Property 13 — génération déterministe de `id_paie`."""

    # Feature: interface-streamlit, Property 13: Génération déterministe de id_paie
    @pytest.mark.property
    @given(
        employe_id=st.from_regex(r"EMP[0-9]{3}", fullmatch=True),
        annee_fiscale=st.integers(min_value=2020, max_value=2100),
        numero_periode=st.integers(min_value=1, max_value=27),
        version=st.integers(min_value=1, max_value=50),
    )
    @settings_large_input
    def test_produit_exactement_le_format_paie_attendu(
        self, employe_id: str, annee_fiscale: int, numero_periode: int, version: int
    ) -> None:
        """Property 13 (Req 10.1, 13.3).

        Pour tout `employe_id` fictif (`EMPnnn`), toute `annee_fiscale`,
        tout `numero_periode` entre 1 et 27, et toute `version` entière
        `>= 1`, `generer_id_paie(employe_id, annee_fiscale, numero_periode,
        version)` doit produire exactement
        `f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:02d}-v{version}"`.
        """
        from app.logique_metier.formulaire_paie import generer_id_paie

        resultat = generer_id_paie(employe_id, annee_fiscale, numero_periode, version)

        attendu = f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:02d}-v{version}"
        assert resultat == attendu, (
            f"generer_id_paie({employe_id!r}, {annee_fiscale!r}, "
            f"{numero_periode!r}, {version!r}) doit retourner {attendu!r}, "
            f"obtenu {resultat!r}."
        )

    # Feature: interface-streamlit, Property 13: Génération déterministe de id_paie
    def test_exemple_regeneration_apres_increment_de_version(self) -> None:
        """Test d'exemple explicite — régénération après incrément (Req 13.3).

        Pour une paie ciblée `employe_id="EMP001"`, `annee_fiscale=2026`,
        `numero_periode=3`, de version `version_ciblee=1`, la
        régénération avec `version=version_ciblee + 1` doit produire
        exactement `"PAIE-EMP001-2026-03-v2"`, tandis que l'`id_paie`
        initial reste `"PAIE-EMP001-2026-03-v1"` — même convention de
        format pour les deux appels, seul le suffixe `-v<version>`
        change entre la création initiale et la régénération.
        """
        from app.logique_metier.formulaire_paie import generer_id_paie

        employe_id = "EMP001"
        annee_fiscale = 2026
        numero_periode = 3
        version_ciblee = 1

        id_paie_v1 = generer_id_paie(
            employe_id, annee_fiscale, numero_periode, version_ciblee
        )
        id_paie_v2 = generer_id_paie(
            employe_id, annee_fiscale, numero_periode, version_ciblee + 1
        )

        assert id_paie_v1 == "PAIE-EMP001-2026-03-v1", (
            f"id_paie initial (version={version_ciblee}) doit égaler "
            f"'PAIE-EMP001-2026-03-v1', obtenu {id_paie_v1!r}."
        )
        assert id_paie_v2 == "PAIE-EMP001-2026-03-v2", (
            f"id_paie régénéré (version={version_ciblee + 1}) doit égaler "
            f"'PAIE-EMP001-2026-03-v2', obtenu {id_paie_v2!r}."
        )


# ---------------------------------------------------------------------------
# Tests d'exemple de propagation des erreurs de validation
# ---------------------------------------------------------------------------
#
# Tâche 7.5 — dernière classe de ce fichier (section 7 du plan complète
# après celle-ci).
#
# _Requirements: 7.4, 7.7_
# _Design: §Components §6_


def _kwargs_valides_construction_payroll_input() -> dict:
    """Kwargs valides fixes pour `construire_payroll_input` (tâche 7.5).

    Même patron que `TestGenerationIdPaie.test_exemple_regeneration_
    apres_increment_de_version` (tâche 7.4) : valeurs fixes et
    déterministes plutôt qu'un tirage Hypothesis, pour des tests
    d'exemple reproductibles. `date_debut`/`date_fin` respectent par
    défaut `date_fin == date_debut + 13 jours` (cas valide) ; chaque
    test d'exemple ci-dessous altère uniquement le ou les champs
    nécessaires pour déclencher le cas d'erreur visé.
    """
    from models.employee import Employee
    from models.enums import Juridiction

    employee = Employee(
        id="EMP001",
        nom_affichage="Employé Test EMP001",
        date_naissance=date(2000, 1, 1),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Moniteur",
        taux_horaire_base=Decimal("20.00"),
        date_embauche=date(2024, 1, 1),
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("0.00"),
        montant_total_TD1=Decimal("0.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )

    date_debut = date(2026, 1, 5)
    date_fin = date_debut + timedelta(days=13)
    annee_fiscale = date_debut.year

    heures_semaine_1 = HeuresParSemaine(
        heures_normales=Decimal("40.00"), heures_supplementaires=Decimal("0.00")
    )
    heures_semaine_2 = HeuresParSemaine(
        heures_normales=Decimal("40.00"), heures_supplementaires=Decimal("0.00")
    )

    cumuls_debut = CumulsYTD.zero(employe_id=employee.id, annee_civile=annee_fiscale)

    return {
        "employee": employee,
        "numero_periode": 1,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "date_paiement": date_fin + timedelta(days=5),
        "annee_fiscale": annee_fiscale,
        "nb_periodes_annuelles": 26,
        "heures_semaine_1": heures_semaine_1,
        "heures_semaine_2": heures_semaine_2,
        "taux_horaire_effectif": Decimal("20.00"),
        "taux_vacances": Decimal("0.04"),
        "jours_feries_manuels": Decimal("0.00"),
        "montant_total_TP1015_3_effectif": Decimal("0.00"),
        "exoneration_TP1015_3_effectif": False,
        "retenue_additionnelle_QC_effective": Decimal("0.00"),
        "montant_total_TD1_effectif": Decimal("0.00"),
        "exoneration_TD1_effective": False,
        "retenue_additionnelle_federale_effective": Decimal("0.00"),
        "cumuls_debut": cumuls_debut,
    }


class TestPropagationErreursFormulaire:
    """Tests d'exemple — propagation sans interception des erreurs de
    validation d'origine (Req 7.4, 7.7, règle 03).

    Ces trois tests d'exemple confirment que `formulaire_paie.py`
    n'ajoute **aucun** garde-fou de périmètre supplémentaire ni
    interception silencieuse autour des constructions
    `WeekSegment`/`PayPeriod`/`HeuresParSemaine`/`PayrollInput` : toute
    erreur de validation d'origine remonte telle quelle à l'appelant.
    """

    # Feature: interface-streamlit, tâche 7.5 — propagation sans interception (Req 7.4)
    def test_exemple_date_fin_non_contigue_propage_erreur_validation_origine(
        self,
    ) -> None:
        """Test d'exemple (Req 7.4).

        Pour `date_fin != date_debut + 13 jours`, l'erreur de validation
        d'origine remonte sans interception, aussi bien depuis
        `deriver_semaines_constituantes` que depuis
        `construire_payroll_input`.

        Vecteur utilisé : `date_fin = date_debut + 5 jours` (< 7 jours).
        Vérification empirique préalable (contre `models/pay_period.py`
        directement, la dérivation mécanique `[date_debut, date_debut+6]`
        / `[date_debut+7, date_fin]` étant déjà fixée par le design) :
        pour tout `date_fin = date_debut + delta` avec `delta >= 7`,
        les contrôles de contiguïté/couverture de `PayPeriod`
        (`_semaines_contigues_et_couvrantes`) sont **toujours**
        satisfaits par construction — aucune erreur n'est levée par
        `PayPeriod` pour un `delta` différent de 13 mais `>= 7`. C'est
        uniquement pour `delta < 7` qu'une erreur de validation
        d'origine est réellement déclenchée, cette fois par
        `WeekSegment` lui-même (Req 2.3 du modèle `moteur-paie-contrats`
        — `date_fin` de la seconde semaine dérivée,
        `date_debut + delta`, serait alors antérieure à sa
        `date_debut`, `date_debut + 7 jours`). Ce test utilise donc ce
        vecteur réel (`delta=5`) plutôt que `delta=10` (suggéré par la
        tâche mais qui, vérifié empiriquement, ne déclenche aucune
        erreur) — écart documenté avec le design.md §Components 6, qui
        attribue cette erreur à `PayPeriod` alors qu'elle provient en
        réalité de `WeekSegment` pour ce type de vecteur. Dans les deux
        cas, l'erreur est une `pydantic.ValidationError` (erreur de
        validation de forme, pas un cas hors matrice) — cohérent avec
        Req 7.4 : « l'Interface_Streamlit DOIT afficher le message
        d'origine de l'erreur de validation à l'opérateur sans
        l'intercepter silencieusement ».
        """
        from app.logique_metier.formulaire_paie import (
            construire_payroll_input,
            deriver_semaines_constituantes,
        )

        date_debut = date(2026, 1, 5)
        date_fin_non_contigue = date_debut + timedelta(days=5)

        with pytest.raises(ValidationError):
            deriver_semaines_constituantes(date_debut, date_fin_non_contigue)

        kwargs = _kwargs_valides_construction_payroll_input()
        kwargs["date_debut"] = date_debut
        kwargs["date_fin"] = date_fin_non_contigue
        kwargs["date_paiement"] = date_fin_non_contigue + timedelta(days=5)

        with pytest.raises(ValidationError):
            construire_payroll_input(**kwargs)

    # Feature: interface-streamlit, tâche 7.5 — propagation sans interception (Req 7.7)
    def test_exemple_cas_hors_matrice_propage_unsupported_payroll_case(self) -> None:
        """Test d'exemple (Req 7.7).

        `construire_payroll_input` avec un cas hors matrice détecté par
        l'un des modèles construits doit laisser remonter
        `UnsupportedPayrollCase` d'origine, sans interception.

        Vecteur réel identifié (`models/payroll_input.py` —
        `PayrollInput._coherence_croisee`, invariant 3) : `taux_vacances`
        hors `{Decimal("0.04"), Decimal("0.06")}` (règle 03, Req 3.5,
        Req 11.3). Ce n'est PAS un vecteur par `frequence` :
        `construire_payroll_input` fixe toujours
        `frequence=FrequencePaie.AUX_DEUX_SEMAINES` (seule valeur
        supportée, voir design.md §Components 6), donc aucun cas hors
        matrice n'est atteignable via ce paramètre depuis le
        Formulaire_Paie. `taux_vacances` reste en revanche un paramètre
        librement saisi par l'opérateur (Req 8, Formulaire_Paie) et
        constitue donc un vecteur réaliste de cas hors matrice détecté
        à l'assemblage du `PayrollInput`.
        """
        from app.logique_metier.formulaire_paie import construire_payroll_input

        kwargs = _kwargs_valides_construction_payroll_input()
        kwargs["taux_vacances"] = Decimal("0.10")

        with pytest.raises(UnsupportedPayrollCase):
            construire_payroll_input(**kwargs)

    # Feature: interface-streamlit, tâche 7.5 — inspection ast (Req 7.4, 7.7)
    def test_exemple_absence_de_try_except_dans_formulaire_paie(self) -> None:
        """Inspection `ast` — absence de `try/except` dans `formulaire_paie.py`.

        Vérifie, par inspection du code source (lecture texte, sans
        import), l'absence de tout bloc `try/except` (`ast.Try`) dans
        `app/logique_metier/formulaire_paie.py` — patron identique aux
        tâches 3.3/4.2/5.4 pour l'inspection de fichiers pas encore
        créés (`pytest.skip` si absent).

        Choix simplifié documenté ici (comme autorisé par la tâche 7.5) :
        plutôt que de rechercher spécifiquement un `try/except` dont le
        corps contient une construction de
        `WeekSegment`/`PayPeriod`/`HeuresParSemaine`/`PayrollInput`
        (analyse fine du contenu de chaque bloc), ce test vérifie
        l'absence de **tout** bloc `try/except` dans le fichier entier.
        Ce choix simplifié reste fidèle à l'esprit de la règle 03/06
        (aucune interception silencieuse des erreurs de validation
        d'origine) : `formulaire_paie.py` n'a, selon le design.md
        §Components 6, aucune raison légitime de contenir un
        `try/except` (aucune gestion de ressource, aucun nettoyage
        similaire à `ecrire_atomique`) — la présence de n'importe quel
        `try/except` dans ce module signalerait donc une interception
        indue.
        """
        chemin_module = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "logique_metier"
            / "formulaire_paie.py"
        )

        if not chemin_module.exists():
            pytest.skip(
                "app/logique_metier/formulaire_paie.py n'existe pas encore "
                "(implémentation prévue tâche 17.1/17.2) — état rouge attendu "
                "(règle 06)."
            )

        arbre = ast.parse(chemin_module.read_text(encoding="utf-8"))

        blocs_try = [noeud for noeud in ast.walk(arbre) if isinstance(noeud, ast.Try)]

        assert not blocs_try, (
            "formulaire_paie.py ne doit contenir aucun bloc try/except "
            "(Req 7.4, 7.7, règle 03) : les erreurs de validation "
            "d'origine (WeekSegment/PayPeriod/HeuresParSemaine/"
            "PayrollInput) doivent remonter sans interception. Bloc(s) "
            f"try trouvé(s) à la(aux) ligne(s) "
            f"{[bloc.lineno for bloc in blocs_try]}."
        )


class TestValeursEffectivesDepuisPaie:
    """Test d'exemple de `valeurs_effectives_depuis_paie` — bug UI corrigé
    après livraison (pré-remplissage du Formulaire_Paie pour poursuivre
    l'édition d'un brouillon ou corriger une paie émise).

    Construit un vrai `PayrollResult` via `assembler_paie` (moteur déjà
    figé et testé par les six specs antérieures — réutilisé ici sans
    duplication de logique de calcul), puis vérifie que
    `valeurs_effectives_depuis_paie` reconstitue exactement les valeurs
    d'entrée d'origine (round-trip `PayrollInput` → `PayrollResult` →
    dict reconstruit).
    """

    def test_round_trip_reconstruit_exactement_les_valeurs_dentree(self) -> None:
        """Round-trip : les valeurs reconstruites par
        `valeurs_effectives_depuis_paie(resultat)` égalent exactement
        celles fournies au `PayrollInput` d'origine.

        Ne couvre volontairement PAS les heures par semaine
        (`heures_normales_1`/`heures_supplementaires_1`/
        `heures_normales_2`/`heures_supplementaires_2`) — décision
        explicite (discussion utilisateur) documentée dans le docstring
        de `valeurs_effectives_depuis_paie` : ces valeurs ne sont pas
        récupérables depuis un `PayrollResult` déjà assemblé (non
        persistées par `assembler_paie`), la fonction ne les inclut
        donc pas dans le dict retourné.
        """
        from datetime import datetime

        from app.logique_metier.formulaire_paie import (
            construire_payroll_input,
            generer_id_paie,
            valeurs_effectives_depuis_paie,
        )
        from models.enums import StatutDePaie
        from payroll_engine.net_pay import assembler_paie
        from tests.strategies import _charger_parametres_annee_2026_qc_ca

        kwargs = _kwargs_valides_construction_payroll_input()
        # Valeurs non nulles pour vérifier une reconstruction significative
        # (une valeur à 0.00 partout masquerait un bug de mapping de champ).
        kwargs["heures_semaine_1"] = HeuresParSemaine(
            heures_normales=Decimal("40.00"), heures_supplementaires=Decimal("2.00")
        )
        kwargs["heures_semaine_2"] = HeuresParSemaine(
            heures_normales=Decimal("38.50"), heures_supplementaires=Decimal("0.00")
        )
        kwargs["jours_feries_manuels"] = Decimal("50.00")
        kwargs["montant_total_TP1015_3_effectif"] = Decimal("18952.00")
        kwargs["exoneration_TP1015_3_effectif"] = False
        kwargs["retenue_additionnelle_QC_effective"] = Decimal("10.00")
        kwargs["montant_total_TD1_effectif"] = Decimal("16452.00")
        kwargs["exoneration_TD1_effective"] = False
        kwargs["retenue_additionnelle_federale_effective"] = Decimal("5.00")

        payroll_input = construire_payroll_input(**kwargs)
        parametres_annee = _charger_parametres_annee_2026_qc_ca()
        id_paie = generer_id_paie(
            kwargs["employee"].id, kwargs["annee_fiscale"], 1, 1
        )
        resultat = assembler_paie(
            payroll_input,
            parametres_annee,
            id_paie,
            1,
            StatutDePaie.BROUILLON,
            datetime(2026, 1, 1, 12, 0),
        )

        reconstruit = valeurs_effectives_depuis_paie(resultat)

        assert reconstruit["numero_periode"] == kwargs["numero_periode"]
        assert reconstruit["date_debut"] == kwargs["date_debut"]
        assert reconstruit["date_fin"] == kwargs["date_fin"]
        assert reconstruit["date_paiement"] == kwargs["date_paiement"]
        assert reconstruit["annee_fiscale"] == kwargs["annee_fiscale"]
        # Les heures par semaine ne sont volontairement PAS reconstruites
        # (voir docstring de `valeurs_effectives_depuis_paie`) — absentes
        # du dict retourné.
        assert "heures_normales_1" not in reconstruit
        assert "heures_supplementaires_1" not in reconstruit
        assert "heures_normales_2" not in reconstruit
        assert "heures_supplementaires_2" not in reconstruit
        assert reconstruit["jours_feries_manuels"] == kwargs["jours_feries_manuels"]
        assert (
            reconstruit["montant_total_TP1015_3_effectif"]
            == kwargs["montant_total_TP1015_3_effectif"]
        )
        assert (
            reconstruit["exoneration_TP1015_3_effectif"]
            == kwargs["exoneration_TP1015_3_effectif"]
        )
        assert (
            reconstruit["retenue_additionnelle_QC_effective"]
            == kwargs["retenue_additionnelle_QC_effective"]
        )
        assert (
            reconstruit["montant_total_TD1_effectif"]
            == kwargs["montant_total_TD1_effectif"]
        )
        assert (
            reconstruit["exoneration_TD1_effective"]
            == kwargs["exoneration_TD1_effective"]
        )
        assert (
            reconstruit["retenue_additionnelle_federale_effective"]
            == kwargs["retenue_additionnelle_federale_effective"]
        )


# ---------------------------------------------------------------------------
# Property 1 (Bug Condition) — Bug 1 : absence de répartition des heures
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``heures-periode-et-persistance-brouillon``.
# Design de référence : ``design.md`` §Bug Condition (Bug 1),
# §Correctness Properties (Property 1).
#
# Tâche 1 du plan d'implémentation (méthodologie bug condition,
# observation-first, règle 06) : ce test d'exploration DOIT échouer sur
# le code non corrigé — la fonction `repartir_heures_sur_semaines`
# n'existe pas encore dans `app/logique_metier/formulaire_paie.py`. Cet
# échec confirme `isBugCondition_Heures(X) = X.frequence ==
# AUX_DEUX_SEMAINES` (toujours vrai) : le formulaire actuel exige
# toujours 4 champs de saisie d'heures pour toute période aux deux
# semaines, faute d'une fonction de répartition interne à partir de
# 2 totaux.
#
# **NE PAS corriger ce test ni le code lorsqu'il échoue** — l'échec est
# le résultat attendu de cette tâche (voir tâches 1, 5.1, 5.3).
#
# _Requirements: 1.1, 1.2_


class TestRepartirHeuresSurSemaines:
    """Property 1 (Bug Condition) — exploration, Bug 1 (saisie à 4 champs).

    `repartir_heures_sur_semaines` est absente de
    `app/logique_metier/formulaire_paie.py` sur le code non corrigé.
    Les deux tests ci-dessous documentent cette absence : un cas
    déterministe (import direct) et une propriété générative (l'appel
    échoue systématiquement, quels que soient les totaux saisis dans
    les bornes `[0, 168]` de `HeuresParSemaine`).
    """

    # Feature: heures-periode-et-persistance-brouillon, Property 1: Bug Condition
    def test_exemple_import_repartir_heures_sur_semaines_echoue(self) -> None:
        """Test d'exemple — cas déterministe (Req 1.1, 1.2).

        `from app.logique_metier.formulaire_paie import
        repartir_heures_sur_semaines` doit échouer par `ImportError`
        (nom absent du module) sur le code non corrigé — confirme
        l'absence de toute fonction de répartition permettant de
        construire un `PayrollInput.heures_par_semaine` à partir de 2
        totaux plutôt que de 4 champs saisis séparément par semaine.
        """
        with pytest.raises((ImportError, AttributeError)):
            from app.logique_metier.formulaire_paie import (  # noqa: F401
                repartir_heures_sur_semaines,
            )

    # Feature: heures-periode-et-persistance-brouillon, Property 1: Bug Condition
    @pytest.mark.property
    @given(
        total_heures_normales=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("168"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        total_heures_supplementaires=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("168"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings_large_input
    def test_property_appel_repartir_heures_sur_semaines_echoue_systematiquement(
        self,
        total_heures_normales: Decimal,
        total_heures_supplementaires: Decimal,
    ) -> None:
        """Property 1 (Bug Condition) — Req 1.1, 1.2.

        Pour tout couple de totaux `(total_heures_normales,
        total_heures_supplementaires)` généré dans `[0, 168]` (bornes
        de `HeuresParSemaine`), l'appel à
        `repartir_heures_sur_semaines(total_heures_normales=...,
        total_heures_supplementaires=...)` doit échouer sur le code non
        corrigé — la fonction n'existe pas encore comme attribut du
        module `app.logique_metier.formulaire_paie`, quel que soit le
        couple de totaux fourni. Le module lui-même est importé
        normalement (il existe déjà) ; c'est l'accès à l'attribut
        `repartir_heures_sur_semaines` qui échoue par `AttributeError`.
        """
        import app.logique_metier.formulaire_paie as module_formulaire_paie

        with pytest.raises((ImportError, AttributeError)):
            module_formulaire_paie.repartir_heures_sur_semaines(
                total_heures_normales=total_heures_normales,
                total_heures_supplementaires=total_heures_supplementaires,
            )


# ---------------------------------------------------------------------------
# Property 2 (Bug Condition) — Bug 2 : absence de restitution des heures
# via `valeurs_effectives_depuis_paie` (exploration)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``heures-periode-et-persistance-brouillon``.
# Design de référence : ``design.md`` §Bug Condition (Bug 2),
# §Correctness Properties (Property 2), §Testing Strategy
# « Exploratory Bug Condition Checking », cas 4.
#
# Tâche 2 du plan d'implémentation (méthodologie bug condition,
# observation-first, règle 06) : ce test d'exploration DOIT échouer
# (l'assertion doit être satisfaite, confirmant l'absence des clés) sur
# le code non corrigé — `valeurs_effectives_depuis_paie` n'accepte
# encore qu'un seul argument (`resultat`) et ne restitue jamais les
# clés `total_heures_normales`/`total_heures_supplementaires`, quel
# que soit le `PayrollResult` généré.
#
# **NE PAS corriger ce test ni le code lorsqu'il échoue** — le résultat
# attendu de cette tâche est que l'assertion d'absence des clés soit
# TOUJOURS vérifiée (voir tâches 2, 6.6).
#
# _Requirements: 1.3, 1.4_


@st.composite
def _st_un_payroll_result(draw: st.DrawFn) -> "PayrollResult":
    """Un `PayrollResult` `BROUILLON` réel, assemblé via `assembler_paie`.

    Design (§Testing Strategy « réutilise tests/strategies.py::
    st_payroll_input/générateur de PayrollResult existant ») : cette
    stratégie réutilise directement `st_payroll_input()` (déjà défini
    par la spec `gains-bruts-vacances-hs`, tâche 1.1) et
    `_charger_parametres_annee_2026_qc_ca()`, assemblés via le pipeline
    réel `assembler_paie` (`payroll_engine/net_pay.py`, moteur déjà
    figé, non modifié par ce bugfix) — même patron que
    `TestValeursEffectivesDepuisPaie.test_round_trip_reconstruit_
    exactement_les_valeurs_dentree` (classe existante de ce fichier).

    Contrairement à `_st_payroll_result_pour_registre` (utilisée par
    `tests/payroll_engine/test_register.py`, qui construit des
    sous-modèles à la main sans `CalculationTrace` réelle), un
    `PayrollResult` assemblé par `assembler_paie` porte des traces
    complètes (`parametres_utilises["exoneration_active"]`, etc.),
    seule forme compatible avec `valeurs_effectives_depuis_paie`
    (règle 02 — aucune nouvelle `CalculationTrace`, cette fonction lit
    les traces déjà produites par le moteur).
    """
    from datetime import datetime

    from models.enums import StatutDePaie
    from payroll_engine.net_pay import assembler_paie
    from tests.strategies import _charger_parametres_annee_2026_qc_ca

    payroll_input = draw(st_payroll_input())
    parametres_annee = _charger_parametres_annee_2026_qc_ca()
    id_paie = generer_id_paie_pour_test(
        payroll_input.employee.id, payroll_input.pay_period.annee_fiscale
    )
    return assembler_paie(
        payroll_input,
        parametres_annee,
        id_paie,
        1,
        StatutDePaie.BROUILLON,
        datetime(2026, 1, 1, 12, 0),
    )


def generer_id_paie_pour_test(employe_id: str, annee_fiscale: int) -> str:
    """`id_paie` déterministe local, sans dépendre de `generer_id_paie`
    (dont la Property 13 est déjà testée ailleurs dans ce fichier) —
    évite tout couplage entre cette stratégie d'exploration et une
    fonction dont la correction n'est pas l'objet de ce test."""
    return f"PAIE-{employe_id}-{annee_fiscale}-EXPLORATION-v1"


class TestExplorationValeursEffectivesHeures:
    """Property 2 (Bug Condition) — exploration, Bug 2 (brouillon non
    restituable).

    Design (§Bug Condition Bug 2, §Correctness Properties Property 2,
    §Testing Strategy « Exploratory Bug Condition Checking », cas 4) ;
    Requirements 1.3, 1.4.

    Confirme, sur le code NON corrigé, que pour tout `PayrollResult`
    généré, `valeurs_effectives_depuis_paie(resultat)` ne contient
    JAMAIS les clés `total_heures_normales`/
    `total_heures_supplementaires`, quelles que soient les heures
    d'origine — la fonction actuelle ne connaît qu'un seul paramètre
    (`resultat`) et ne restitue jamais les heures saisies (voir
    docstring existante de `valeurs_effectives_depuis_paie` :
    limitation documentée, "les clés ... sont volontairement absentes
    du dict retourné").

    Cas d'exemple ajoutés par la tâche 4 (Property 4 — Preservation,
    Req 3.4) : reprend le même constat pour une paie insérée puis relue
    via le registre maître (`payroll_engine.register.inserer_paie`/
    `lire_paie`, signature actuelle, sans `PayrollInput`) — comportement
    de référence à préserver strictement après la correction pour ce
    type d'appel (aucun `PayrollInput` transmis).
    """

    # Feature: heures-periode-et-persistance-brouillon, Property 2: Bug Condition
    @pytest.mark.property
    @given(resultat=_st_un_payroll_result())
    @settings_large_input
    def test_property_dict_ne_contient_jamais_les_cles_heures(
        self, resultat
    ) -> None:
        """Property 2, Test 3 (Bug Condition) — Req 1.3, 1.4.

        Pour tout `PayrollResult` généré (`_st_un_payroll_result`,
        assemblé via `assembler_paie` à partir de `st_payroll_input()`),
        `valeurs_effectives_depuis_paie(resultat)` ne doit JAMAIS
        contenir les clés `total_heures_normales` ni
        `total_heures_supplementaires` sur le code non corrigé,
        quelles que soient les heures d'origine du `PayrollResult`
        généré (`resultat.pay_period.semaines[*].heures_normales`/
        `.heures_supplementaires`, dérivées à `Decimal("0")` par
        `deriver_semaines_constituantes` dans le pipeline de
        génération de `PayrollResult`, ou toute autre valeur produite
        par une future répartition — sans objet ici puisque la
        fonction actuelle ne reçoit qu'un seul argument).
        """
        from app.logique_metier.formulaire_paie import (
            valeurs_effectives_depuis_paie,
        )

        reconstruit = valeurs_effectives_depuis_paie(resultat)

        assert "total_heures_normales" not in reconstruit, (
            "Sur le code non corrigé, `valeurs_effectives_depuis_paie` "
            "ne doit JAMAIS restituer `total_heures_normales`, obtenu "
            f"dans le dict : {reconstruit!r} — si ce test échoue en "
            "PASSANT (la clé est absente comme attendu, l'assertion "
            "est satisfaite), cela confirme le Bug 2 (Property 2, "
            "Req 1.3, 1.4)."
        )
        assert "total_heures_supplementaires" not in reconstruit, (
            "Sur le code non corrigé, `valeurs_effectives_depuis_paie` "
            "ne doit JAMAIS restituer `total_heures_supplementaires`, "
            f"obtenu dans le dict : {reconstruit!r} (Property 2, Req "
            "1.3, 1.4)."
        )

    # -----------------------------------------------------------------
    # Property 4 (Preservation) — même constat pour une paie insérée
    # puis relue via le registre maître, signature actuelle du registre
    # (sans `PayrollInput`) — comportement de référence à préserver
    # après correction (tâche 4, Req 3.4).
    # -----------------------------------------------------------------

    # Feature: heures-periode-et-persistance-brouillon, Property 4: Preservation
    @pytest.mark.property
    @given(resultat=_st_un_payroll_result())
    @settings_large_input
    def test_property_dict_ne_contient_jamais_les_cles_heures_apres_registre(
        self, resultat, tmp_path: Path
    ) -> None:
        """Property 4 (Preservation) — Req 3.4.

        Pour tout `PayrollResult` généré (`_st_un_payroll_result`,
        assemblé via `assembler_paie`), inséré via
        `payroll_engine.register.inserer_paie(resultat, saison,
        chemin_bd=...)` (signature actuelle, sans `PayrollInput`) sur
        une base neuve puis relu via `lire_paie`,
        `valeurs_effectives_depuis_paie(resultat_relu)` ne doit JAMAIS
        contenir les clés `total_heures_normales` ni
        `total_heures_supplementaires` — comportement de référence à
        préserver strictement identique après la correction (tâches 6.1
        à 6.7) pour ce type d'appel, qui ne transmet aucun
        `PayrollInput`.
        """
        import uuid as _uuid

        from app.logique_metier.formulaire_paie import (
            valeurs_effectives_depuis_paie,
        )
        from payroll_engine.register import inserer_paie, lire_paie

        chemin_bd = tmp_path / f"test_{_uuid.uuid4().hex}.db"
        inserer_paie(resultat, "Saison Test", chemin_bd=chemin_bd)
        resultat_relu, _ = lire_paie(resultat.id_paie, chemin_bd=chemin_bd)

        reconstruit = valeurs_effectives_depuis_paie(resultat_relu)

        assert "total_heures_normales" not in reconstruit, (
            "Sur le code non corrigé, `valeurs_effectives_depuis_paie` "
            "appliqué à une paie insérée/relue via le registre (sans "
            "`PayrollInput`) ne doit JAMAIS restituer "
            f"`total_heures_normales`, obtenu {reconstruit!r} (Property "
            "4, Req 3.4)."
        )
        assert "total_heures_supplementaires" not in reconstruit, (
            "Sur le code non corrigé, `valeurs_effectives_depuis_paie` "
            "appliqué à une paie insérée/relue via le registre (sans "
            "`PayrollInput`) ne doit JAMAIS restituer "
            f"`total_heures_supplementaires`, obtenu {reconstruit!r} "
            "(Property 4, Req 3.4)."
        )
