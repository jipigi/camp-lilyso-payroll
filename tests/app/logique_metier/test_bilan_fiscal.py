"""Property tests et tests d'exemple pour `app/logique_metier/bilan_fiscal.py`.

Spec de référence : ``bilan-fiscal-employeur``.
Design de référence : ``design.md`` §Components (§1 à §5) et
§Correctness Properties 1 à 14.

Ce fichier porte l'ensemble des property tests, tests d'exemple et test
de garde structurel du module `bilan_fiscal.py` (agrégation du Bilan
Fiscal du Tableau_De_Bord). Les tâches successives du plan
d'implémentation ajoutent chacune une classe de test dédiée à l'une des
14 properties du design :

1. Property 1 — Détermination du Mois_De_Rattachement et exactitude des
   options générées.
2. Property 2 — Formatage des libellés d'options.
3. Property 3 — Ordre des options du Selecteur_De_Periode.
4. Property 4 — Présélection par défaut de la période.
5. Property 5 — Persistance du choix manuel de l'opérateur.
6. Property 6 — Détection de l'absence totale de Paie_Agregee.
7. Property 7 — Répartition QC/CA à sens unique des lignes
   mono-juridictionnelles.
8. Property 8 — Ligne Impôt et exclusion des montants formule.
9. Property 9 — Agrégation du drapeau CNESST en attente de
   classification.
10. Property 10 — Calcul générique des lignes de total avec propagation
    de l'indisponibilité.
11. Property 11 — Filtrage exact des Paies_Agregees par Periode_Fiscale.
12. Property 12 — La lecture SQL n'agrège que les paies de statut EMISE.
13. Property 13 — Préservation stricte du type Decimal de bout en bout.
14. Property 14 — Interruption de l'agrégation sur échec de
    désérialisation.

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/bilan_fiscal.py`` n'existe **pas encore** à ce
stade (implémentation prévue à la tâche 9). Ce fichier importe donc
localement les symboles du module sous test (au sein de chaque test)
afin que la **collecte** pytest de ce fichier réussisse même tant que le
module cible est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``app.logique_metier.bilan_fiscal`` — c'est
le comportement **attendu et correct** (état rouge intentionnel) tant
que la tâche 9 (implémentation) n'a pas été réalisée (checkpoint de la
tâche 8.2 du plan).

Règle 01 : chaque `PayrollResult` généré par
`tests.app.strategies.st_payroll_result_arbitraire` porte exclusivement
des champs `Decimal` (jamais de `float`) — ce fichier ne réintroduit
aucune conversion `float`.
Règle 04 : chaque test injecte systématiquement un chemin de base
temporaire (`st_chemin_bd_temporaire`, `tmp_path`) ou `":memory:"` —
jamais le chemin de production (`chemin_bd_production()`) — et
n'utilise que des identifiants fictifs `EMPnnn`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from models.enums import StatutDePaie
from models.payroll_result import PayrollResult
from tests.app.strategies import (
    st_cellule_montant_ou_indisponible,
    st_payroll_result_arbitraire,
    st_periode_fiscale,
)
from tests.strategies import (
    st_chemin_bd_temporaire,  # noqa: F401  (fixture pytest, résolue par nom de paramètre)
)

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


def _st_paies_emises(max_size: int = 8) -> st.SearchStrategy[tuple[PayrollResult, ...]]:
    """0 à `max_size` `PayrollResult` de statut `EMISE`, `date_paiement` libres.

    Réutilisation directe de `st_payroll_result_arbitraire` (tâche 1.1)
    avec `statut` fixé à `StatutDePaie.EMISE` — seul le mois/année de
    `pay_period.date_paiement` varie librement d'un exemple à l'autre
    (Property 1, Requirements 2.2, 2.3, 2.4).

    `unique_by=lambda p: p.id_paie` : plusieurs tests de ce fichier
    insèrent chaque élément généré via `payroll_engine.register.
    inserer_paie` (append-only, refuse toute ré-insertion d'un `id_paie`
    déjà présent — Req 11.6 de `net-cumuls-registre`) dans une même base
    SQLite temporaire au sein d'une seule boucle. `id_paie` est construit
    par `st_payroll_result_arbitraire` à partir d'`employe_id`/
    `annee_fiscale`/un suffixe entier tiré indépendamment par élément —
    deux éléments de la même liste générée peuvent donc, sans cette
    contrainte, collisionner sur le même `id_paie` et faire échouer
    `inserer_paie` avec un `ValueError` non lié aux properties sous test.
    """
    return st.lists(
        st_payroll_result_arbitraire(statut=StatutDePaie.EMISE),
        min_size=0,
        max_size=max_size,
        unique_by=lambda p: p.id_paie,
    ).map(tuple)


# ---------------------------------------------------------------------------
# Property 1 — Détermination du Mois_De_Rattachement et exactitude des
# options générées
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 1: Détermination du Mois_De_Rattachement et exactitude des options générées
#
# *Pour tout* ensemble de `PayrollResult` `EMISE` (`date_paiement`
# arbitraires), l'ensemble des `OptionPeriode` produit par
# `construire_options_periode` correspond exactement à l'ensemble des
# années et couples (mois, année) présents dans `date_paiement`.
#
# _Requirements: 2.2, 2.3, 2.4_
# _Design: §Components §1 ; §Correctness Properties 1_


class TestConstructionOptionsPeriode:
    """Property 1 — Détermination du Mois_De_Rattachement et exactitude
    des options générées."""

    # Feature: bilan-fiscal-employeur, Property 1: Détermination du Mois_De_Rattachement et exactitude des options générées
    @pytest.mark.property
    @given(paies_emises=_st_paies_emises())
    @settings_large_input
    def test_options_generees_correspondent_exactement_aux_annees_et_couples_mois_annee_presents(
        self,
        paies_emises: tuple[PayrollResult, ...],
    ) -> None:
        """Property 1 (Requirements 2.2, 2.3, 2.4).

        Pour chaque `PayrollResult` de ``paies_emises``, le
        Mois_De_Rattachement (et l'année de rattachement) est déterminé
        via `mois_annee_rattachement(pay_period.date_paiement)`
        (Requirement 2.2). L'ensemble des `PeriodeFiscale` produites par
        `construire_options_periode` doit alors correspondre exactement
        à l'union de :

        - une `PeriodeFiscale(annee, mois=None)` par année distincte de
          rattachement présente dans ``paies_emises`` (Requirement 2.3) ;
        - une `PeriodeFiscale(annee, mois)` par couple (mois, année) de
          rattachement distinct présent dans ``paies_emises``
          (Requirement 2.4) ;

        jamais une option supplémentaire, jamais une option manquante —
        y compris le tuple vide en options lorsque ``paies_emises`` est
        vide.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            construire_options_periode,
            mois_annee_rattachement,
        )

        annees_attendues: set[int] = set()
        couples_attendus: set[tuple[int, int]] = set()
        for paie in paies_emises:
            annee, mois = mois_annee_rattachement(paie.pay_period.date_paiement)
            annees_attendues.add(annee)
            couples_attendus.add((annee, mois))

        periodes_attendues = {
            PeriodeFiscale(annee=annee, mois=None) for annee in annees_attendues
        } | {
            PeriodeFiscale(annee=annee, mois=mois)
            for annee, mois in couples_attendus
        }

        options: tuple[OptionPeriode, ...] = construire_options_periode(
            paies_emises
        )
        periodes_obtenues = {option.periode for option in options}

        assert periodes_obtenues == periodes_attendues, (
            "`construire_options_periode(paies_emises)` doit produire "
            "exactement l'ensemble des `PeriodeFiscale` correspondant "
            "aux années et couples (mois, année) de rattachement "
            f"présents dans `paies_emises` ; attendu {periodes_attendues!r}, "
            f"obtenu {periodes_obtenues!r}."
        )
        assert len(options) == len(periodes_attendues), (
            "`construire_options_periode(paies_emises)` ne doit produire "
            "aucune option dupliquée (une `OptionPeriode` par "
            f"`PeriodeFiscale` distincte) ; attendu {len(periodes_attendues)} "
            f"option(s), obtenu {len(options)}."
        )


# ---------------------------------------------------------------------------
# Property 6 — Détection de l'absence totale de Paie_Agregee
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 6: Détection de l'absence totale de Paie_Agregee
#
# *Pour tout* ensemble de paies dont aucune n'est de statut `EMISE`, la
# lecture (`lire_paies_emises`) retourne un tuple vide ; et *pour tout*
# tuple vide en entrée de `construire_options_periode`, le résultat est
# un tuple vide d'options — le même comportement d'absence s'applique
# donc que la cause soit une base sans aucune paie, une base sans
# employé, ou une base avec uniquement des statuts non-`EMISE`
# (`BROUILLON`, `ANNULEE`, `REMPLACE_PAR`).
#
# _Requirements: 1.2, 4.1_
# _Design: §Components §5 ; §Correctness Properties 6_


def _st_statut_non_emise() -> st.SearchStrategy[StatutDePaie]:
    """Statut de paie arbitraire, exclusivement non-`EMISE` (Property 6).

    Échantillonne parmi les trois statuts qui ne doivent jamais
    contribuer à une Paie_Agregee (`BROUILLON`, `ANNULEE`,
    `REMPLACE_PAR`) — jamais `EMISE`, pour garantir que l'ensemble de
    paies inséré ne contient **aucune** paie émise.
    """
    return st.sampled_from(
        [StatutDePaie.BROUILLON, StatutDePaie.ANNULEE, StatutDePaie.REMPLACE_PAR]
    )


class TestAbsenceTotalePaieAgregee:
    """Property 6 — détection de l'absence totale de Paie_Agregee."""

    # Feature: bilan-fiscal-employeur, Property 6: Détection de l'absence totale de Paie_Agregee
    @pytest.mark.property
    @given(
        paies_non_emises=st.lists(
            st_payroll_result_arbitraire(statut=_st_statut_non_emise()),
            min_size=0,
            max_size=6,
            unique_by=lambda p: p.id_paie,
        )
    )
    @settings_large_input
    def test_lire_paies_emises_retourne_tuple_vide_sans_aucun_statut_emise(
        self,
        paies_non_emises: list,
        st_chemin_bd_temporaire,
    ) -> None:
        """Property 6, volet lecture (Req 1.2, 4.1).

        Insère, dans une base SQLite temporaire neuve, un ensemble
        arbitraire (potentiellement vide) de paies dont **aucune** n'est
        de statut `EMISE` (`BROUILLON`, `ANNULEE`, `REMPLACE_PAR`
        uniquement). `lire_paies_emises` doit alors retourner un tuple
        vide — que la base soit vide (aucune paie insérée, cas « aucune
        paie ») ou qu'elle contienne exclusivement des statuts
        non-`EMISE` (cas « uniquement des statuts non-EMISE ») : même
        comportement d'absence dans les deux cas.
        """
        from payroll_engine.register import inserer_paie

        from app.logique_metier.bilan_fiscal import lire_paies_emises

        for resultat in paies_non_emises:
            inserer_paie(resultat, saison="", chemin_bd=st_chemin_bd_temporaire)

        resultat_obtenu = lire_paies_emises(chemin_bd=st_chemin_bd_temporaire)

        assert resultat_obtenu == (), (
            "`lire_paies_emises` doit retourner un tuple vide lorsque "
            f"aucune paie de statut EMISE n'est présente ; obtenu "
            f"{resultat_obtenu!r} pour {len(paies_non_emises)} paie(s) "
            "non-EMISE insérée(s)."
        )

    # Feature: bilan-fiscal-employeur, Property 6: Détection de l'absence totale de Paie_Agregee
    def test_lire_paies_emises_retourne_tuple_vide_sur_base_neuve_sans_employe(
        self,
    ) -> None:
        """Property 6, cas « aucun employé / base neuve » (Req 1.2, 4.1).

        Une base SQLite `":memory:"` fraîchement ouverte n'a encore créé
        aucune table `paies` (aucun employé, aucune paie jamais insérée)
        — `lire_paies_emises` doit intercepter explicitement
        `sqlite3.OperationalError` (« no such table ») et retourner un
        tuple vide, jamais laisser l'exception se propager (même
        comportement d'absence que le cas « uniquement des statuts
        non-EMISE », décision n° 5 de `interface-streamlit`).
        """
        from app.logique_metier.bilan_fiscal import lire_paies_emises

        resultat = lire_paies_emises(chemin_bd=":memory:")

        assert resultat == (), (
            "`lire_paies_emises` sur une base `:memory:` neuve (sans "
            f"table `paies`, sans employé) doit retourner un tuple vide, "
            f"obtenu {resultat!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 6: Détection de l'absence totale de Paie_Agregee
    @pytest.mark.property
    @given(st.just(()))
    @settings_large_input
    def test_construire_options_periode_dun_tuple_vide_retourne_tuple_vide_options(
        self,
        paies_vides: tuple,
    ) -> None:
        """Property 6, volet options (Req 1.2, 4.1).

        Pour tout tuple vide de `PayrollResult` `EMISE` en entrée de
        `construire_options_periode` — qu'il résulte d'une absence totale
        de paie, d'une absence totale d'employé, ou d'un filtrage
        préalable ne conservant aucun statut `EMISE` — le résultat doit
        être un tuple vide d'`OptionPeriode`, sans lever d'exception.
        """
        from app.logique_metier.bilan_fiscal import construire_options_periode

        resultat_obtenu = construire_options_periode(paies_vides)

        assert resultat_obtenu == (), (
            "`construire_options_periode(())` doit retourner un tuple "
            f"vide d'options, obtenu {resultat_obtenu!r}."
        )


# ---------------------------------------------------------------------------
# Property 10 — Calcul générique des lignes de total avec propagation de
# l'indisponibilité
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 10: Calcul générique des lignes de total avec propagation de l'indisponibilité
#
# *Pour toute* séquence arbitraire de cellules `Decimal | None` :
# `calculer_total` retourne `None` si la séquence ne contient aucune
# valeur `Decimal` (toutes `None`, y compris la séquence vide) ; sinon,
# elle retourne la somme exacte (arithmétique `Decimal`, sans
# arrondissement additionnel) des valeurs non `None`, chaque `None`
# individuel comptant comme zéro dans cette somme.
#
# Test isolé (sans passer par le pipeline complet), réutilise
# `st_cellule_montant_ou_indisponible` (tâche 1.1).
#
# _Requirements: 7.1, 7.2, 7.3, 9.1, 9.2, 9.3, 9.4_
# _Design: §Components §4 ; §Correctness Properties 10_


class TestCalculerTotal:
    """Property 10 — calcul générique des lignes de total avec
    propagation de l'indisponibilité."""

    # Feature: bilan-fiscal-employeur, Property 10: Calcul générique des lignes de total avec propagation de l'indisponibilité
    @pytest.mark.property
    @given(
        cellules=st.lists(
            st_cellule_montant_ou_indisponible(), min_size=0, max_size=10
        )
    )
    @settings_large_input
    def test_calculer_total_retourne_none_ssi_toutes_les_cellules_sont_none(
        self,
        cellules: list,
    ) -> None:
        """Property 10, volet indisponibilité (Req 7.3, 9.4).

        Si ``cellules`` (y compris la séquence vide) ne contient aucune
        valeur `Decimal` (toutes `None`), `calculer_total(*cellules)`
        doit retourner exactement `None` — jamais `Decimal("0")` ni
        aucune autre valeur.
        """
        from app.logique_metier.bilan_fiscal import calculer_total

        resultat = calculer_total(*cellules)

        toutes_indisponibles = all(cellule is None for cellule in cellules)
        if toutes_indisponibles:
            assert resultat is None, (
                "`calculer_total(*cellules)` doit retourner `None` "
                f"lorsque toutes les cellules sont `None` ; obtenu "
                f"{resultat!r} pour cellules={cellules!r}."
            )

    # Feature: bilan-fiscal-employeur, Property 10: Calcul générique des lignes de total avec propagation de l'indisponibilité
    @pytest.mark.property
    @given(
        cellules=st.lists(
            st_cellule_montant_ou_indisponible(), min_size=0, max_size=10
        )
    )
    @settings_large_input
    def test_calculer_total_retourne_la_somme_exacte_des_valeurs_disponibles(
        self,
        cellules: list,
    ) -> None:
        """Property 10, volet sommation (Req 7.1, 7.2, 9.1, 9.2, 9.3).

        Si ``cellules`` contient au moins une valeur `Decimal` non
        `None`, `calculer_total(*cellules)` doit retourner exactement la
        somme `Decimal` des cellules non `None` (chaque `None`
        individuel comptant comme zéro dans la somme), sans
        arrondissement additionnel.
        """
        from decimal import Decimal

        from app.logique_metier.bilan_fiscal import calculer_total

        resultat = calculer_total(*cellules)

        au_moins_une_disponible = any(
            cellule is not None for cellule in cellules
        )
        if au_moins_une_disponible:
            somme_attendue = sum(
                (cellule for cellule in cellules if cellule is not None),
                Decimal("0"),
            )
            assert resultat == somme_attendue, (
                "`calculer_total(*cellules)` doit retourner la somme "
                f"exacte des valeurs non `None` ; attendu "
                f"{somme_attendue!r}, obtenu {resultat!r} pour "
                f"cellules={cellules!r}."
            )


# ---------------------------------------------------------------------------
# Property 12 — La lecture SQL n'agrège que les paies de statut EMISE
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 12: La lecture SQL n'agrège que les paies de statut EMISE
#
# *Pour tout* mélange arbitraire de statuts (`BROUILLON`, `EMISE`,
# `ANNULEE`, `REMPLACE_PAR`) insérés dans une base SQLite temporaire,
# `lire_paies_emises` doit retourner exactement l'ensemble des
# `PayrollResult` dont le statut persisté est `EMISE`, jamais un statut
# différent — y compris un tuple vide si aucune paie `EMISE` n'est
# présente, et sans lever d'exception sur une base neuve sans table
# `paies`.
#
# _Requirements: 10.3_
# _Design: §Components §5 ; §Correctness Properties 12 ; décision n° 5_


class TestLirePaiesEmises:
    """Property 12 — la lecture SQL n'agrège que les paies de statut EMISE
    (intégration légère SQLite, `st_chemin_bd_temporaire`/`inserer_paie`)."""

    # Feature: bilan-fiscal-employeur, Property 12: La lecture SQL n'agrège que les paies de statut EMISE
    @pytest.mark.property
    @given(
        paies_mixtes=st.lists(
            st_payroll_result_arbitraire(
                statut=st.sampled_from(list(StatutDePaie))
            ),
            min_size=0,
            max_size=10,
            unique_by=lambda p: p.id_paie,
        )
    )
    @settings_large_input
    def test_retourne_exactement_lensemble_des_paies_de_statut_emise(
        self,
        paies_mixtes: list[PayrollResult],
        tmp_path,
    ) -> None:
        """Property 12 (Req 10.3).

        Insère, dans une base SQLite temporaire neuve, un mélange
        arbitraire (potentiellement vide) de paies dont le `statut`
        varie librement parmi les quatre valeurs de `StatutDePaie`
        (`inserer_paie`, append-only). Compare alors l'ensemble des
        `id_paie` retournés par `lire_paies_emises` à l'ensemble de
        référence calculé indépendamment sur ``paies_mixtes``
        (`{p.id_paie for p in paies_mixtes if p.statut is
        StatutDePaie.EMISE}`) — les deux ensembles doivent être
        rigoureusement identiques, et chaque `PayrollResult` retourné doit
        lui-même porter `statut == StatutDePaie.EMISE` (jamais un statut
        différent), y compris pour ``paies_mixtes`` vide ou ne contenant
        aucun statut `EMISE` (tuple vide attendu).

        Remarque (règle 04, isolation Hypothesis) : le chemin de base
        n'est **pas** injecté via la fixture pytest
        `st_chemin_bd_temporaire` (résolue une seule fois par appel de
        fonction de test, donc partagée entre tous les essais Hypothesis
        d'un même `@given` — même avec
        `HealthCheck.function_scoped_fixture` supprimé, cette suppression
        ne fait que masquer l'avertissement, elle ne rend pas la fixture
        fraîche par essai). Le chemin est construit ici directement dans
        le corps du test à partir de `tmp_path` (lui-même function-scoped,
        mais réutilisé sans risque puisqu'on ne s'appuie que sur son
        répertoire) et d'un suffixe `uuid.uuid4().hex` tiré à chaque
        exécution du corps — donc à chaque essai Hypothesis — garantissant
        une base SQLite réellement neuve par essai.
        """
        from payroll_engine.register import inserer_paie

        from app.logique_metier.bilan_fiscal import lire_paies_emises

        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        # Bug corrigé après livraison (demande explicite de
        # l'utilisateur) — `inserer_paie` refuse désormais une seconde
        # ligne EMISE pour la même Paie_Logique `(employe_id,
        # annee_fiscale, numero_periode)` (voir
        # `TestRefusDoubleEmisePourMemePeriode` de
        # `tests/payroll_engine/test_register.py`). `paies_mixtes` ne
        # garantit pas des périodes distinctes entre ses éléments EMISE
        # — ignorer ici toute paie EMISE dont la période est déjà
        # occupée par une EMISE déjà retenue, pour ne pas violer cette
        # invariante désormais imposée par le registre (comportement de
        # préservation : seul le sous-ensemble effectivement inséré doit
        # apparaître dans l'ensemble de référence).
        paies_effectivement_inserees: list[PayrollResult] = []
        periodes_emises_occupees: set[tuple[str, int, int]] = set()
        for resultat in paies_mixtes:
            if resultat.statut is StatutDePaie.EMISE:
                cle_periode = (
                    resultat.employe_id,
                    resultat.annee_fiscale,
                    resultat.pay_period.numero_periode,
                )
                if cle_periode in periodes_emises_occupees:
                    continue
                periodes_emises_occupees.add(cle_periode)
            inserer_paie(resultat, saison="", chemin_bd=chemin_bd)
            paies_effectivement_inserees.append(resultat)

        ids_emises_attendus = {
            paie.id_paie
            for paie in paies_effectivement_inserees
            if paie.statut is StatutDePaie.EMISE
        }

        resultat_obtenu = lire_paies_emises(chemin_bd=chemin_bd)

        ids_obtenus = {paie.id_paie for paie in resultat_obtenu}
        statuts_obtenus = {paie.statut for paie in resultat_obtenu}

        assert ids_obtenus == ids_emises_attendus, (
            "`lire_paies_emises` doit retourner exactement l'ensemble des "
            f"`id_paie` de statut EMISE ; attendu {ids_emises_attendus!r}, "
            f"obtenu {ids_obtenus!r}."
        )
        assert statuts_obtenus <= {StatutDePaie.EMISE}, (
            "`lire_paies_emises` ne doit jamais retourner une paie d'un "
            f"statut différent de EMISE ; obtenu les statuts "
            f"{statuts_obtenus!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 12: La lecture SQL n'agrège que les paies de statut EMISE
    def test_exemple_base_memoire_neuve_sans_table_paies_retourne_tuple_vide(
        self,
    ) -> None:
        """Test d'exemple — base `:memory:` neuve, sans table `paies` (Req 10.3).

        Une base SQLite `":memory:"` fraîchement ouverte n'a encore créé
        aucune table `paies` (base neuve, jamais aucune insertion) —
        `lire_paies_emises` doit intercepter explicitement
        `sqlite3.OperationalError` (message contenant « no such table »)
        et retourner un tuple vide, jamais laisser l'exception se
        propager (même discipline que `dernieres_paies.derniere_annee_paie`,
        décision n° 5 de `interface-streamlit`).
        """
        from app.logique_metier.bilan_fiscal import lire_paies_emises

        resultat = lire_paies_emises(chemin_bd=":memory:")

        assert resultat == (), (
            "`lire_paies_emises` sur une base `:memory:` neuve (sans "
            f"table `paies`) doit retourner un tuple vide, obtenu "
            f"{resultat!r}."
        )


# ---------------------------------------------------------------------------
# Property 2 — Formatage des libellés d'options
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 2: Formatage des libellés d'options
#
# *Pour toute* année et *tout* mois (1 à 12) associé à une année,
# `formater_option_annee_complete(annee)` doit produire exactement
# `f"{annee} (année complète)"`, et `formater_option_mois_fiscal(annee,
# mois)` doit produire exactement `f"{_NOMS_MOIS[mois]} {annee}"`, où
# `_NOMS_MOIS` associe chacun des 12 mois à son nom français avec
# l'orthographe et la casse exactes imposées par le Requirement 2.6.
#
# _Requirements: 2.5, 2.6_
# _Design: §Components §1 ; §Correctness Properties 2_

#: Référence indépendante des 12 noms français attendus (orthographe et
#: casse exactes du Requirement 2.6) — définie ici plutôt qu'importée du
#: module sous test, pour que ce test détecte toute divergence entre
#: `_NOMS_MOIS` (implémentation) et la spec, plutôt que de comparer le
#: module à lui-même.
NOMS_MOIS_ATTENDUS: dict[int, str] = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}


class TestFormatageLibelles:
    """Property 2 — formatage des libellés d'options."""

    # Feature: bilan-fiscal-employeur, Property 2: Formatage des libellés d'options
    @pytest.mark.property
    @given(annee=st.integers(min_value=2020, max_value=2035))
    @settings_large_input
    def test_formater_option_annee_complete_produit_le_libelle_impose(
        self,
        annee: int,
    ) -> None:
        """Property 2, volet Annee_Complete (Req 2.5).

        Pour toute ``annee`` arbitraire,
        `formater_option_annee_complete(annee)` doit produire exactement
        ``f"{annee} (année complète)"`` — jamais une variante
        d'orthographe, de casse ou de ponctuation.
        """
        from app.logique_metier.bilan_fiscal import formater_option_annee_complete

        resultat = formater_option_annee_complete(annee)

        assert resultat == f"{annee} (année complète)", (
            "`formater_option_annee_complete(annee)` doit produire "
            f"exactement '{annee} (année complète)' ; obtenu {resultat!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 2: Formatage des libellés d'options
    @pytest.mark.property
    @given(
        annee=st.integers(min_value=2020, max_value=2035),
        mois=st.integers(min_value=1, max_value=12),
    )
    @settings_large_input
    def test_formater_option_mois_fiscal_produit_le_libelle_impose(
        self,
        annee: int,
        mois: int,
    ) -> None:
        """Property 2, volet Mois_Fiscal (Req 2.6).

        Pour toute ``annee`` et tout ``mois`` (1 à 12) arbitraires,
        `formater_option_mois_fiscal(annee, mois)` doit produire
        exactement ``f"{NOMS_MOIS_ATTENDUS[mois]} {annee}"``, avec l'un
        des douze noms français exacts (orthographe et casse, y compris
        les accents de Février/Août/Décembre) — jamais une variante.
        """
        from app.logique_metier.bilan_fiscal import formater_option_mois_fiscal

        resultat = formater_option_mois_fiscal(annee, mois)

        libelle_attendu = f"{NOMS_MOIS_ATTENDUS[mois]} {annee}"
        assert resultat == libelle_attendu, (
            "`formater_option_mois_fiscal(annee, mois)` doit produire "
            f"exactement {libelle_attendu!r} ; obtenu {resultat!r} pour "
            f"annee={annee!r}, mois={mois!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 2: Formatage des libellés d'options
    def test_exemple_douze_mois_formates_avec_orthographe_exacte(self) -> None:
        """Test d'exemple — les 12 libellés de mois, orthographe exacte (Req 2.6).

        Vérifie littéralement, pour une année fixe (2026), les 12
        libellés `formater_option_mois_fiscal(2026, mois)` produits pour
        ``mois`` de 1 à 12 — notamment l'orthographe et la casse exactes
        de Février, Août et Décembre (lettres accentuées).
        """
        from app.logique_metier.bilan_fiscal import formater_option_mois_fiscal

        annee = 2026
        libelles_attendus = {
            1: "Janvier 2026",
            2: "Février 2026",
            3: "Mars 2026",
            4: "Avril 2026",
            5: "Mai 2026",
            6: "Juin 2026",
            7: "Juillet 2026",
            8: "Août 2026",
            9: "Septembre 2026",
            10: "Octobre 2026",
            11: "Novembre 2026",
            12: "Décembre 2026",
        }

        for mois, libelle_attendu in libelles_attendus.items():
            resultat = formater_option_mois_fiscal(annee, mois)
            assert resultat == libelle_attendu, (
                f"`formater_option_mois_fiscal({annee}, {mois})` doit "
                f"produire exactement {libelle_attendu!r} ; obtenu "
                f"{resultat!r}."
            )


# ---------------------------------------------------------------------------
# Property 7 — Répartition QC/CA à sens unique des lignes
# mono-juridictionnelles
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 7: Répartition QC/CA à sens unique des lignes mono-juridictionnelles
#
# *Pour tout* ensemble arbitraire de `PayrollResult`, chacune des neuf
# lignes mono-juridictionnelles (RRQ, RQAP, AE côté retenues employé ;
# RRQ employeur, RQAP employeur, AE employeur, FSS, CNESST, CNT côté
# cotisations employeur) doit avoir, dans sa colonne de juridiction
# attribuée, une valeur égale à la somme exacte des montants sources
# correspondants (`MontantAvecTrace.montant`) de toutes les paies de
# l'ensemble, arrondie à deux décimales ; sa colonne de l'autre
# juridiction doit valoir explicitement `Decimal("0.00")` — y compris
# pour un ensemble vide, où les deux colonnes de chaque ligne valent
# zéro.
#
# _Requirements: 6.2, 6.3, 6.4, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_
# _Design: §Components §4 ; §Correctness Properties 7_


#: Description déclarative des neuf lignes mono-juridictionnelles —
#: nom de l'attribut `TableauBilanFiscal` correspondant, extracteur du
#: montant source sur un `PayrollResult`, et nom de la colonne
#: attribuée (« qc » pour RRQ/RQAP/RRQ employeur/RQAP employeur/FSS/
#: CNESST/CNT, « ca » pour AE/AE employeur — Requirements 6.2-6.4,
#: 8.2-8.7). Défini indépendamment du module sous test pour que ce test
#: détecte toute divergence entre l'implémentation et la spec, plutôt
#: que de comparer le module à lui-même.
_LIGNES_MONO_JURIDICTIONNELLES: tuple[tuple[str, "Callable[[PayrollResult], object]", str], ...] = (
    ("ligne_rrq", lambda p: p.retenues_employe.rrq.montant, "qc"),
    ("ligne_rqap", lambda p: p.retenues_employe.rqap.montant, "qc"),
    ("ligne_ae", lambda p: p.retenues_employe.ae.montant, "ca"),
    (
        "ligne_rrq_employeur",
        lambda p: p.cotisations_employeur.rrq_employeur.montant,
        "qc",
    ),
    (
        "ligne_rqap_employeur",
        lambda p: p.cotisations_employeur.rqap_employeur.montant,
        "qc",
    ),
    (
        "ligne_ae_employeur",
        lambda p: p.cotisations_employeur.ae_employeur.montant,
        "ca",
    ),
    ("ligne_fss", lambda p: p.cotisations_employeur.fss.montant, "qc"),
    ("ligne_cnesst", lambda p: p.cotisations_employeur.cnesst.montant, "qc"),
    ("ligne_cnt", lambda p: p.cotisations_employeur.cnt.montant, "qc"),
)


def _st_paies_arbitraires(max_size: int = 8) -> st.SearchStrategy[tuple[PayrollResult, ...]]:
    """0 à `max_size` `PayrollResult` de statut arbitraire.

    Property 7 s'applique à « tout ensemble arbitraire de
    `PayrollResult` » — `construire_tableau_bilan_fiscal` est une
    fonction pure qui agrège les paies qu'on lui fournit sans filtrer
    par statut (ce filtrage a déjà eu lieu en amont, à la lecture SQL
    et au filtrage par période). Le statut est donc laissé libre ici,
    contrairement à `_st_paies_emises` (Property 1) qui le fixait à
    `EMISE`.
    """
    return st.lists(
        st_payroll_result_arbitraire(),
        min_size=0,
        max_size=max_size,
    ).map(tuple)


class TestRepartitionQcCaSensUnique:
    """Property 7 — répartition QC/CA à sens unique des lignes
    mono-juridictionnelles."""

    # Feature: bilan-fiscal-employeur, Property 7: Répartition QC/CA à sens unique des lignes mono-juridictionnelles
    @pytest.mark.property
    @given(paies=_st_paies_arbitraires())
    @settings_large_input
    def test_chaque_ligne_mono_juridictionnelle_est_a_sens_unique(
        self,
        paies: tuple[PayrollResult, ...],
    ) -> None:
        """Property 7 (Requirements 6.2, 6.3, 6.4, 8.2, 8.3, 8.4, 8.5,
        8.6, 8.7).

        Pour chacune des neuf lignes mono-juridictionnelles décrites par
        `_LIGNES_MONO_JURIDICTIONNELLES`, la colonne de juridiction
        attribuée du `LigneBilan` produit par
        `construire_tableau_bilan_fiscal(paies)` doit égaler exactement
        la somme des montants sources correspondants de ``paies``,
        arrondie à deux décimales ; la colonne de l'autre juridiction
        doit valoir explicitement `Decimal("0.00")` — y compris pour
        ``paies`` vide, où la somme attendue est nulle.
        """
        from decimal import ROUND_HALF_UP, Decimal

        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        tableau = construire_tableau_bilan_fiscal(paies)

        for nom_ligne, extracteur, colonne_attribuee in _LIGNES_MONO_JURIDICTIONNELLES:
            ligne = getattr(tableau, nom_ligne)

            somme_attendue = sum(
                (extracteur(paie) for paie in paies), Decimal("0")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            valeur_attribuee = ligne.qc if colonne_attribuee == "qc" else ligne.ca
            valeur_autre = ligne.ca if colonne_attribuee == "qc" else ligne.qc

            assert valeur_attribuee == somme_attendue, (
                f"`tableau.{nom_ligne}.{colonne_attribuee}` doit égaler "
                f"la somme exacte des montants sources arrondie à deux "
                f"décimales ; attendu {somme_attendue!r}, obtenu "
                f"{valeur_attribuee!r} pour {len(paies)} paie(s)."
            )
            assert valeur_autre == Decimal("0.00"), (
                f"`tableau.{nom_ligne}` doit avoir sa colonne non "
                f"attribuée explicitement à `Decimal('0.00')` ; obtenu "
                f"{valeur_autre!r} pour {len(paies)} paie(s)."
            )

    # Feature: bilan-fiscal-employeur, Property 7: Répartition QC/CA à sens unique des lignes mono-juridictionnelles
    def test_exemple_ensemble_vide_toutes_les_lignes_sont_a_zero_dans_les_deux_colonnes(
        self,
    ) -> None:
        """Property 7, cas explicite de l'ensemble vide (Req 6.2-6.4,
        8.2-8.7).

        Pour ``paies=()``, chacune des neuf lignes mono-juridictionnelles
        doit avoir ses deux colonnes (QC et CA) explicitement à
        `Decimal("0.00")` — jamais `None`, jamais une valeur non nulle.
        """
        from decimal import Decimal

        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        tableau = construire_tableau_bilan_fiscal(())

        for nom_ligne, _extracteur, _colonne_attribuee in _LIGNES_MONO_JURIDICTIONNELLES:
            ligne = getattr(tableau, nom_ligne)
            assert ligne.qc == Decimal("0.00"), (
                f"`tableau.{nom_ligne}.qc` doit valoir `Decimal('0.00')` "
                f"pour un ensemble vide de paies ; obtenu {ligne.qc!r}."
            )
            assert ligne.ca == Decimal("0.00"), (
                f"`tableau.{nom_ligne}.ca` doit valoir `Decimal('0.00')` "
                f"pour un ensemble vide de paies ; obtenu {ligne.ca!r}."
            )


# ---------------------------------------------------------------------------
# Property 4 — Présélection par défaut de la période
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 4: Présélection par défaut de la période
#
# *Pour toute* date arbitraire ``aujourdhui`` et tout ensemble d'options
# disponibles : si `1 <= aujourdhui.day <= 15`, `determiner_periode_par_defaut`
# doit cibler le mois précédant celui de `aujourdhui` ; si
# `16 <= aujourdhui.day`, il doit cibler le mois de `aujourdhui` ; si le mois
# ciblé (l'une ou l'autre branche) ne correspond à aucune option Mois_Fiscal
# disponible, la fonction doit retourner le Mois_Fiscal disponible dont
# `(annee, mois)` est maximal (le plus récent) ; si aucune option Mois_Fiscal
# n'est disponible, elle doit retourner `None`.
#
# _Requirements: 3.1, 3.2, 3.3_
# _Design: §Components §2 ; §Correctness Properties 4_


def _st_couples_mois_annee_disponibles(
    min_size: int = 0, max_size: int = 10
) -> st.SearchStrategy[list[tuple[int, int]]]:
    """0 à `max_size` couples `(annee, mois)` distincts, `mois` ∈ [1, 12].

    Représente les Mois_Fiscal effectivement disponibles dans le
    Selecteur_De_Periode (Property 4) — indépendant de tout accès
    disque, aucun `OptionPeriode`/`PeriodeFiscale` construit ici (import
    différé, règle 06 — construit dans le corps du test).
    """
    return st.lists(
        st.tuples(
            st.integers(min_value=2000, max_value=2100),
            st.integers(min_value=1, max_value=12),
        ),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    )


def _st_annees_completes_disponibles(
    min_size: int = 0, max_size: int = 5
) -> st.SearchStrategy[list[int]]:
    """0 à `max_size` années distinctes représentant des Annee_Complete
    disponibles (mois=None) — présentes dans les options pour vérifier
    qu'elles n'influencent jamais le résultat de
    `determiner_periode_par_defaut` (seuls les Mois_Fiscal comptent)."""
    return st.lists(
        st.integers(min_value=2000, max_value=2100),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    )


class TestPeriodeParDefaut:
    """Property 4 — présélection par défaut de la période."""

    # Feature: bilan-fiscal-employeur, Property 4: Présélection par défaut de la période
    @pytest.mark.property
    @given(
        aujourdhui=st.dates(
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)
        ),
        couples_mois_disponibles=_st_couples_mois_annee_disponibles(),
        annees_completes_disponibles=_st_annees_completes_disponibles(),
    )
    @settings_large_input
    def test_determiner_periode_par_defaut_respecte_les_trois_branches(
        self,
        aujourdhui: date,
        couples_mois_disponibles: list[tuple[int, int]],
        annees_completes_disponibles: list[int],
    ) -> None:
        """Property 4 (Requirements 3.1, 3.2, 3.3).

        Construit un ensemble arbitraire d'options (Mois_Fiscal et
        Annee_Complete confondus) et vérifie les trois branches :

        - jour ∈ [1, 15] : le mois précédant celui de ``aujourdhui``
          (avec bascule d'année pour janvier -> décembre de l'année
          précédente) est ciblé (Requirement 3.1) ;
        - jour ∈ [16, dernier jour du mois] : le mois de ``aujourdhui``
          est ciblé (Requirement 3.2) ;
        - si le mois ciblé (l'une ou l'autre branche) ne correspond à
          aucune option Mois_Fiscal disponible, le Mois_Fiscal disponible
          dont `(annee, mois)` est maximal est retourné (Requirement
          3.3) ;
        - si aucune option Mois_Fiscal n'est disponible (``mois`` absent
          de toutes les options, y compris lorsque seules des
          Annee_Complete sont disponibles), `None` est retourné.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            determiner_periode_par_defaut,
            formater_option_annee_complete,
            formater_option_mois_fiscal,
        )

        options_mois_fiscal = [
            OptionPeriode(
                libelle=formater_option_mois_fiscal(annee, mois),
                periode=PeriodeFiscale(annee=annee, mois=mois),
            )
            for annee, mois in couples_mois_disponibles
        ]
        options_annee_complete = [
            OptionPeriode(
                libelle=formater_option_annee_complete(annee),
                periode=PeriodeFiscale(annee=annee, mois=None),
            )
            for annee in annees_completes_disponibles
        ]
        options: tuple[OptionPeriode, ...] = tuple(
            options_mois_fiscal + options_annee_complete
        )

        if 1 <= aujourdhui.day <= 15:
            if aujourdhui.month == 1:
                annee_cible, mois_cible = aujourdhui.year - 1, 12
            else:
                annee_cible, mois_cible = aujourdhui.year, aujourdhui.month - 1
        else:
            annee_cible, mois_cible = aujourdhui.year, aujourdhui.month

        ensemble_couples_disponibles = set(couples_mois_disponibles)

        resultat = determiner_periode_par_defaut(aujourdhui, options)

        if (annee_cible, mois_cible) in ensemble_couples_disponibles:
            assert resultat == PeriodeFiscale(annee=annee_cible, mois=mois_cible), (
                "`determiner_periode_par_defaut` doit retourner le "
                f"Mois_Fiscal cible {(annee_cible, mois_cible)!r} lorsqu'il "
                f"est disponible parmi les options ; obtenu {resultat!r}."
            )
        elif ensemble_couples_disponibles:
            annee_plus_recente, mois_plus_recent = max(
                ensemble_couples_disponibles
            )
            assert resultat == PeriodeFiscale(
                annee=annee_plus_recente, mois=mois_plus_recent
            ), (
                "`determiner_periode_par_defaut` doit retourner le "
                "Mois_Fiscal disponible le plus récent "
                f"{(annee_plus_recente, mois_plus_recent)!r} lorsque le mois "
                f"cible {(annee_cible, mois_cible)!r} est absent des options "
                f"; obtenu {resultat!r}."
            )
        else:
            assert resultat is None, (
                "`determiner_periode_par_defaut` doit retourner `None` "
                "lorsqu'aucune option Mois_Fiscal n'est disponible (y "
                "compris lorsque seules des Annee_Complete sont "
                f"présentes) ; obtenu {resultat!r}."
            )

    # Feature: bilan-fiscal-employeur, Property 4: Présélection par défaut de la période
    def test_exemple_frontiere_jour_15_cible_mois_precedent(self) -> None:
        """Test d'exemple — frontière jour 15 (Requirement 3.1).

        Le 15 juillet 2026 (dernier jour de la fenêtre « 1 au 15 »), le
        mois précédent (Juin 2026) doit être présélectionné lorsqu'il
        est disponible parmi les options.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            determiner_periode_par_defaut,
            formater_option_mois_fiscal,
        )

        aujourdhui = date(2026, 7, 15)
        options = (
            OptionPeriode(
                libelle=formater_option_mois_fiscal(2026, 6),
                periode=PeriodeFiscale(annee=2026, mois=6),
            ),
            OptionPeriode(
                libelle=formater_option_mois_fiscal(2026, 7),
                periode=PeriodeFiscale(annee=2026, mois=7),
            ),
        )

        resultat = determiner_periode_par_defaut(aujourdhui, options)

        assert resultat == PeriodeFiscale(annee=2026, mois=6), (
            "Le 15 juillet 2026 (jour <= 15), le mois précédent "
            f"(Juin 2026) doit être présélectionné ; obtenu {resultat!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 4: Présélection par défaut de la période
    def test_exemple_frontiere_jour_16_cible_mois_courant(self) -> None:
        """Test d'exemple — frontière jour 16 (Requirement 3.2).

        Le 16 juillet 2026 (premier jour de la fenêtre « 16 au dernier
        jour »), le mois courant (Juillet 2026) doit être présélectionné
        lorsqu'il est disponible parmi les options.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            determiner_periode_par_defaut,
            formater_option_mois_fiscal,
        )

        aujourdhui = date(2026, 7, 16)
        options = (
            OptionPeriode(
                libelle=formater_option_mois_fiscal(2026, 6),
                periode=PeriodeFiscale(annee=2026, mois=6),
            ),
            OptionPeriode(
                libelle=formater_option_mois_fiscal(2026, 7),
                periode=PeriodeFiscale(annee=2026, mois=7),
            ),
        )

        resultat = determiner_periode_par_defaut(aujourdhui, options)

        assert resultat == PeriodeFiscale(annee=2026, mois=7), (
            "Le 16 juillet 2026 (jour >= 16), le mois courant (Juillet "
            f"2026) doit être présélectionné ; obtenu {resultat!r}."
        )


# ---------------------------------------------------------------------------
# Property 11 — Filtrage exact des Paies_Agregees par Periode_Fiscale
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 11: Filtrage exact des Paies_Agregees par Periode_Fiscale
#
# *Pour tout* ensemble arbitraire de `PayrollResult` `EMISE` et toute
# `PeriodeFiscale` (Mois_Fiscal ou Annee_Complete) : si `periode.mois`
# est renseigné, `filtrer_paies_par_periode` doit retourner exactement
# le sous-ensemble dont `mois_annee_rattachement(...) ==
# (periode.annee, periode.mois)` ; si `periode.mois` est `None`, elle
# doit retourner exactement le sous-ensemble dont l'année de
# rattachement égale `periode.annee`, tous mois confondus — y compris
# le tuple vide lorsque aucun élément ne correspond.
#
# _Requirements: 10.1, 10.2_
# _Design: §Components §3 ; §Correctness Properties 11_


class TestFiltrageParPeriode:
    """Property 11 — filtrage exact des Paies_Agregees par Periode_Fiscale."""

    # Feature: bilan-fiscal-employeur, Property 11: Filtrage exact des Paies_Agregees par Periode_Fiscale
    @pytest.mark.property
    @given(paies_emises=_st_paies_emises(), periode=st_periode_fiscale())
    @settings_large_input
    def test_filtrer_paies_par_periode_retourne_exactement_le_sous_ensemble_attendu(
        self,
        paies_emises: tuple[PayrollResult, ...],
        periode,
    ) -> None:
        """Property 11 (Requirements 10.1, 10.2).

        Calcule indépendamment le sous-ensemble attendu de
        ``paies_emises`` selon que ``periode.mois`` est renseigné
        (Mois_Fiscal : `mois_annee_rattachement(...) == (periode.annee,
        periode.mois)`) ou `None` (Annee_Complete : année de
        rattachement == `periode.annee`, tous mois confondus), puis
        compare cet ensemble attendu (par `id_paie`, pour tolérer un
        réordonnancement) au résultat de `filtrer_paies_par_periode` —
        les deux doivent être rigoureusement identiques, y compris le
        tuple vide lorsque aucun élément ne correspond (``paies_emises``
        vide, ou aucune paie ne correspondant à ``periode``).
        """
        from app.logique_metier.bilan_fiscal import (
            filtrer_paies_par_periode,
            mois_annee_rattachement,
        )

        if periode.mois is not None:
            paies_attendues = tuple(
                paie
                for paie in paies_emises
                if mois_annee_rattachement(paie.pay_period.date_paiement)
                == (periode.annee, periode.mois)
            )
        else:
            paies_attendues = tuple(
                paie
                for paie in paies_emises
                if mois_annee_rattachement(paie.pay_period.date_paiement)[0]
                == periode.annee
            )

        resultat_obtenu = filtrer_paies_par_periode(paies_emises, periode)

        ids_attendus = {paie.id_paie for paie in paies_attendues}
        ids_obtenus = {paie.id_paie for paie in resultat_obtenu}

        assert ids_obtenus == ids_attendus, (
            "`filtrer_paies_par_periode(paies_emises, periode)` doit "
            "retourner exactement le sous-ensemble des Paies_Agregees "
            f"correspondant à periode={periode!r} ; attendu "
            f"{ids_attendus!r}, obtenu {ids_obtenus!r}."
        )
        assert len(resultat_obtenu) == len(paies_attendues), (
            "`filtrer_paies_par_periode` ne doit ni dupliquer ni omettre "
            f"d'élément ; attendu {len(paies_attendues)} paie(s), obtenu "
            f"{len(resultat_obtenu)}."
        )

    # Feature: bilan-fiscal-employeur, Property 11: Filtrage exact des Paies_Agregees par Periode_Fiscale
    def test_exemple_tuple_vide_en_entree_retourne_tuple_vide(self) -> None:
        """Test d'exemple — ``paies_emises`` vide (Req 10.1, 10.2).

        Pour tout ``periode`` (Mois_Fiscal ou Annee_Complete),
        `filtrer_paies_par_periode((), periode)` doit retourner un
        tuple vide, sans lever d'exception.
        """
        from app.logique_metier.bilan_fiscal import (
            PeriodeFiscale,
            filtrer_paies_par_periode,
        )

        resultat_mois = filtrer_paies_par_periode((), PeriodeFiscale(annee=2026, mois=7))
        resultat_annee = filtrer_paies_par_periode((), PeriodeFiscale(annee=2026, mois=None))

        assert resultat_mois == (), (
            "`filtrer_paies_par_periode((), PeriodeFiscale(annee=2026, "
            f"mois=7))` doit retourner un tuple vide ; obtenu {resultat_mois!r}."
        )
        assert resultat_annee == (), (
            "`filtrer_paies_par_periode((), PeriodeFiscale(annee=2026, "
            f"mois=None))` doit retourner un tuple vide ; obtenu {resultat_annee!r}."
        )


# ---------------------------------------------------------------------------
# Property 13 — Préservation stricte du type Decimal de bout en bout
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 13: Préservation stricte du type Decimal de bout en bout
#
# *Pour tout* ensemble arbitraire de `PayrollResult` insérés dans une base
# SQLite temporaire, chaque cellule numérique non `None` produite par le
# pipeline complet (lecture → filtrage → agrégation) est de type
# `decimal.Decimal` exactement.
#
# _Requirements: 11.2_
# _Design: §Components §5 ; §Correctness Properties 13_


class TestPreservationDecimal:
    """Property 13 — préservation stricte du type Decimal de bout en bout
    (intégration légère SQLite, pipeline complet lire→filtrer→agréger)."""

    # Feature: bilan-fiscal-employeur, Property 13: Préservation stricte du type Decimal de bout en bout
    @pytest.mark.property
    @given(paies_emises=_st_paies_emises())
    @settings_large_input
    def test_pipeline_complet_ne_produit_jamais_une_cellule_non_decimal(
        self,
        paies_emises: tuple[PayrollResult, ...],
        tmp_path,
    ) -> None:
        """Property 13 (Req 11.2).

        Insère ``paies_emises`` (statut `EMISE`, `date_paiement` libres)
        dans une base SQLite temporaire, exécute le pipeline complet
        (`lire_paies_emises` → `filtrer_paies_par_periode` →
        `construire_tableau_bilan_fiscal`), puis inspecte génériquement
        chaque champ du `TableauBilanFiscal` produit (via
        `dataclasses.fields`, en récursant d'un niveau dans chaque
        `LigneBilan`) : toute valeur non `None` doit être de type
        `decimal.Decimal` exactement (`type(valeur) is Decimal`), jamais
        `float`, `int` nu, ni `str`.

        La `PeriodeFiscale` utilisée pour le filtrage est une
        Annee_Complete dérivée de l'année de rattachement de la première
        paie de ``paies_emises`` (garantit un recoupement non trivial
        lorsque ``paies_emises`` n'est pas vide) ; une année arbitraire
        fixe est utilisée lorsque ``paies_emises`` est vide (le pipeline
        doit alors produire un tableau où chaque `LigneBilan` vaut
        `Decimal("0")`, toujours de type `Decimal` exactement).
        """
        import dataclasses
        from decimal import Decimal

        from payroll_engine.register import inserer_paie

        from app.logique_metier.bilan_fiscal import (
            PeriodeFiscale,
            construire_tableau_bilan_fiscal,
            filtrer_paies_par_periode,
            lire_paies_emises,
            mois_annee_rattachement,
        )

        # Bug corrigé après livraison (demande explicite de
        # l'utilisateur) — `inserer_paie` refuse désormais une seconde
        # ligne EMISE pour la même Paie_Logique `(employe_id,
        # annee_fiscale, numero_periode)` (voir
        # `TestRefusDoubleEmisePourMemePeriode` de
        # `tests/payroll_engine/test_register.py`). ``paies_emises``
        # (tous EMISE) ne garantit pas des périodes distinctes entre ses
        # éléments — ne conserver que le premier élément par période
        # rencontré, comportement de préservation pour cette property
        # (l'absence de `float` ne dépend pas du nombre d'éléments
        # effectivement insérés).
        paies_periodes_distinctes = []
        periodes_vues: set[tuple[str, int, int]] = set()
        for resultat in paies_emises:
            cle_periode = (
                resultat.employe_id,
                resultat.annee_fiscale,
                resultat.pay_period.numero_periode,
            )
            if cle_periode in periodes_vues:
                continue
            periodes_vues.add(cle_periode)
            paies_periodes_distinctes.append(resultat)

        # Bug de test signalé après démo (indépendant du bug ci-dessus) :
        # `st_chemin_bd_temporaire` est une fixture pytest résolue une
        # seule fois par appel de fonction de test, donc partagée entre
        # tous les essais Hypothesis d'un même `@given` — deux essais
        # successifs réutilisaient donc la même base SQLite, provoquant
        # des collisions d'`id_paie` déjà présent sans rapport avec la
        # property sous test. `tmp_path` (elle aussi function-scoped,
        # mais dont on ne réutilise ici que le répertoire) plus un
        # suffixe `uuid.uuid4().hex` tiré à chaque exécution du corps du
        # test garantit une base réellement neuve par essai (même patron
        # que `TestLirePaiesEmises`/`TestEchecDeserialisation`).
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        for resultat in paies_periodes_distinctes:
            inserer_paie(resultat, saison="", chemin_bd=chemin_bd)

        if paies_periodes_distinctes:
            annee_reference, _ = mois_annee_rattachement(
                paies_periodes_distinctes[0].pay_period.date_paiement
            )
        else:
            annee_reference = 2026
        periode = PeriodeFiscale(annee=annee_reference, mois=None)

        paies_lues = lire_paies_emises(chemin_bd=chemin_bd)
        paies_filtrees = filtrer_paies_par_periode(paies_lues, periode)
        tableau = construire_tableau_bilan_fiscal(paies_filtrees)

        def _verifier_valeur(valeur: object, chemin_champ: str) -> None:
            if valeur is None or isinstance(valeur, (str, bool)):
                return
            assert type(valeur) is Decimal, (
                f"`{chemin_champ}` doit être de type `decimal.Decimal` "
                f"exactement lorsqu'il n'est pas `None` ; obtenu "
                f"{type(valeur)!r} (valeur={valeur!r})."
            )

        for champ in dataclasses.fields(tableau):
            valeur_champ = getattr(tableau, champ.name)
            if dataclasses.is_dataclass(valeur_champ):
                for sous_champ in dataclasses.fields(valeur_champ):
                    sous_valeur = getattr(valeur_champ, sous_champ.name)
                    _verifier_valeur(
                        sous_valeur, f"tableau.{champ.name}.{sous_champ.name}"
                    )
            else:
                _verifier_valeur(valeur_champ, f"tableau.{champ.name}")


# ---------------------------------------------------------------------------
# Property 3 — Ordre des options du Selecteur_De_Periode
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 3: Ordre des options du Selecteur_De_Periode
#
# *Pour tout* ensemble arbitraire d'années et de couples (mois, année)
# présents, la liste des `OptionPeriode` produite par
# `construire_options_periode` doit être ordonnée par année décroissante,
# et pour chaque année, l'option Annee_Complete doit précéder toutes les
# options Mois_Fiscal de cette année, elles-mêmes ordonnées par mois
# croissant.
#
# _Requirements: 2.7_
# _Design: §Components §1 ; §Correctness Properties 3_


class TestOrdreOptions:
    """Property 3 — ordre des options du Selecteur_De_Periode."""

    # Feature: bilan-fiscal-employeur, Property 3: Ordre des options du Selecteur_De_Periode
    @pytest.mark.property
    @given(paies_emises=_st_paies_emises())
    @settings_large_input
    def test_options_ordonnees_par_annee_decroissante_puis_annee_complete_avant_mois_fiscal_croissants(
        self,
        paies_emises: tuple[PayrollResult, ...],
    ) -> None:
        """Property 3 (Requirement 2.7).

        `construire_options_periode(paies_emises)` doit retourner ses
        options déjà ordonnées selon la clé
        ``(-periode.annee, periode.mois is not None, periode.mois or 0)``
        — année de rattachement décroissante en priorité ; pour une même
        année, l'option Annee_Complete (``periode.mois is None``, clé
        secondaire ``False``) précède toutes les options Mois_Fiscal de
        cette année (``periode.mois is not None``, clé secondaire
        ``True``) ; ces dernières sont elles-mêmes ordonnées par mois
        croissant (clé tertiaire).

        Vérifié en comparant la séquence `PeriodeFiscale` réellement
        retournée à cette même séquence explicitement retriée avec la
        clé ci-dessus (construite indépendamment de l'implémentation) :
        si l'ordre retourné diffère de l'ordre imposé par la spec, ce
        tri produit une séquence différente et l'égalité de liste (pas
        seulement d'ensemble — l'ordre compte ici) échoue.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            construire_options_periode,
        )

        options: tuple[OptionPeriode, ...] = construire_options_periode(
            paies_emises
        )

        periodes_obtenues = [option.periode for option in options]
        periodes_triees_attendues = sorted(
            periodes_obtenues,
            key=lambda periode: (
                -periode.annee,
                periode.mois is not None,
                periode.mois or 0,
            ),
        )

        assert periodes_obtenues == periodes_triees_attendues, (
            "`construire_options_periode(paies_emises)` doit ordonner "
            "ses options par année de rattachement décroissante, "
            "l'option Annee_Complete précédant les options Mois_Fiscal "
            "(elles-mêmes ordonnées par mois croissant) de chaque année ; "
            f"obtenu {periodes_obtenues!r}, ordre attendu "
            f"{periodes_triees_attendues!r}."
        )


# ---------------------------------------------------------------------------
# Property 8 — Ligne Impôt et exclusion des montants formule
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 8: Ligne Impôt et exclusion des montants formule
#
# *Pour tout* ensemble arbitraire de `PayrollResult` (y compris des cas
# où `impot_qc_formule`/`impot_federal_formule` diffèrent
# significativement de `impot_qc_retenu`/`impot_federal_retenu`, simulant
# une exonération TP-1015.3/TD1), la colonne QC de la ligne « Impôt sur
# le revenu retenu » doit égaler exactement la somme des
# `impot_qc_retenu.montant`, et sa colonne CA doit égaler exactement la
# somme des `impot_federal_retenu.montant` — les valeurs
# `impot_qc_formule.montant` et `impot_federal_formule.montant` ne
# doivent jamais influencer cette somme ni aucune autre somme du
# Tableau_Bilan_Fiscal.
#
# _Requirements: 6.5, 6.6_
# _Design: §Components §4 ; §Correctness Properties 8_

from decimal import Decimal  # noqa: E402  (import local à cette section, style existant du fichier)


class TestLigneImpotExclusionFormule:
    """Property 8 — ligne Impôt et exclusion des montants formule."""

    # Feature: bilan-fiscal-employeur, Property 8: Ligne Impôt et exclusion des montants formule
    @pytest.mark.property
    @given(paies=st.lists(st_payroll_result_arbitraire(), min_size=0, max_size=8))
    @settings_large_input
    def test_ligne_impot_utilise_exclusivement_les_montants_retenus(
        self,
        paies: list[PayrollResult],
    ) -> None:
        """Property 8, volet sommation (Requirements 6.5, 6.6).

        Pour tout ensemble arbitraire de ``paies`` (les valeurs
        ``impot_qc_formule``/``impot_federal_formule`` générées par
        ``st_payroll_result_arbitraire`` divergent librement de
        ``impot_qc_retenu``/``impot_federal_retenu`` d'un exemple à
        l'autre, simulant naturellement des cas d'exonération), la
        colonne QC de ``tableau.ligne_impot`` doit égaler exactement la
        somme des ``retenues_employe.impot_qc_retenu.montant``, et sa
        colonne CA doit égaler exactement la somme des
        ``retenues_employe.impot_federal_retenu.montant`` — jamais une
        somme incluant les montants ``*_formule``.
        """
        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        tableau = construire_tableau_bilan_fiscal(tuple(paies))

        somme_qc_attendue = round(
            sum(p.retenues_employe.impot_qc_retenu.montant for p in paies),
            2,
        )
        somme_ca_attendue = round(
            sum(p.retenues_employe.impot_federal_retenu.montant for p in paies),
            2,
        )

        assert tableau.ligne_impot.qc == somme_qc_attendue, (
            "`tableau.ligne_impot.qc` doit égaler exactement la somme des "
            f"`impot_qc_retenu.montant` ; attendu {somme_qc_attendue!r}, "
            f"obtenu {tableau.ligne_impot.qc!r}."
        )
        assert tableau.ligne_impot.ca == somme_ca_attendue, (
            "`tableau.ligne_impot.ca` doit égaler exactement la somme des "
            f"`impot_federal_retenu.montant` ; attendu {somme_ca_attendue!r}, "
            f"obtenu {tableau.ligne_impot.ca!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 8: Ligne Impôt et exclusion des montants formule
    @pytest.mark.property
    @given(
        paies=st.lists(st_payroll_result_arbitraire(), min_size=0, max_size=8),
        impot_qc_formule_variante=st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("5000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        impot_federal_formule_variante=st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("5000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings_large_input
    def test_variation_des_montants_formule_ninfluence_aucune_somme_du_tableau(
        self,
        paies: list[PayrollResult],
        impot_qc_formule_variante: Decimal,
        impot_federal_formule_variante: Decimal,
    ) -> None:
        """Property 8, volet exclusion stricte (Requirements 6.5, 6.6).

        Construit une seconde variante de ``paies`` où **seuls**
        ``retenues_employe.impot_qc_formule``/``impot_federal_formule``
        sont remplacés (via ``model_copy``) par des valeurs arbitraires
        indépendantes (``impot_qc_formule_variante``,
        ``impot_federal_formule_variante``), tous les autres champs
        (dont ``impot_qc_retenu``/``impot_federal_retenu``) restant
        identiques. ``construire_tableau_bilan_fiscal`` doit alors
        produire un ``TableauBilanFiscal`` **rigoureusement identique**
        pour les deux variantes — preuve directe que les montants
        ``*_formule`` n'influencent aucune somme du tableau, quelle que
        soit leur valeur.
        """
        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        paies_variantes = tuple(
            paie.model_copy(
                update={
                    "retenues_employe": paie.retenues_employe.model_copy(
                        update={
                            "impot_qc_formule": paie.retenues_employe.impot_qc_formule.model_copy(
                                update={"montant": impot_qc_formule_variante}
                            ),
                            "impot_federal_formule": paie.retenues_employe.impot_federal_formule.model_copy(
                                update={"montant": impot_federal_formule_variante}
                            ),
                        }
                    )
                }
            )
            for paie in paies
        )

        tableau_original = construire_tableau_bilan_fiscal(tuple(paies))
        tableau_variante = construire_tableau_bilan_fiscal(paies_variantes)

        assert tableau_original == tableau_variante, (
            "`construire_tableau_bilan_fiscal` doit produire un "
            "`TableauBilanFiscal` identique que ``impot_qc_formule``/"
            "``impot_federal_formule`` valent leurs valeurs d'origine ou "
            "des valeurs arbitraires distinctes "
            f"({impot_qc_formule_variante!r}, "
            f"{impot_federal_formule_variante!r}) — ces montants ne "
            "doivent jamais influencer aucune somme du tableau ; "
            f"original={tableau_original!r}, variante={tableau_variante!r}."
        )


# ---------------------------------------------------------------------------
# Property 5 — Persistance du choix manuel de l'opérateur
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 5: Persistance du choix manuel de l'opérateur
#
# *Pour toute* séquence arbitraire d'appels à `resoudre_periode_a_afficher`
# simulant plusieurs réaffichages successifs d'une même session : une fois
# qu'un libellé a été résolu et écrit (``cle_deja_definie=True``,
# ``valeur_en_session`` fixée à ce libellé) et que ce libellé correspond
# encore à une option disponible, tout appel subséquent avec les mêmes
# ``cle_deja_definie``/``valeur_en_session`` doit retourner exactement
# cette même valeur, sans jamais la remplacer par un nouveau calcul de
# `determiner_periode_par_defaut` — y compris lorsque ``periode_par_defaut``
# fourni à cet appel diffère de la valeur déjà en session (simulant un
# jour différent).
#
# _Requirements: 3.4_
# _Design: §Components §2 ; §Correctness Properties 5_


@st.composite
def _st_options_periode_directe(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 10
) -> tuple:
    """Tuple non vide de `OptionPeriode` construites directement, sans
    passer par `construire_options_periode`/`formater_option_*` — le
    formatage des libellés n'est pas sous test ici (Property 2 couvre
    déjà le formatage). Chaque libellé est déterministe
    (``f"opt-{annee}-{mois}"``), associé à une `PeriodeFiscale` distincte
    (couples ``(annee, mois)`` uniques).

    Import différé de `OptionPeriode`/`PeriodeFiscale` (règle 06, TDD) :
    ce module n'existe pas encore (tâche 9 le crée) — l'import est
    effectué à l'intérieur du corps de cette stratégie composite pour que
    la collecte pytest des tests qui l'utilisent réussisse même en
    l'absence du module cible.
    """
    from app.logique_metier.bilan_fiscal import OptionPeriode, PeriodeFiscale

    couples = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=2020, max_value=2035),
                st.integers(min_value=1, max_value=12),
            ),
            min_size=min_size,
            max_size=max_size,
            unique=True,
        )
    )
    return tuple(
        OptionPeriode(
            libelle=f"opt-{annee}-{mois}",
            periode=PeriodeFiscale(annee=annee, mois=mois),
        )
        for annee, mois in couples
    )


#: Génère soit ``None``, soit un couple ``(annee, mois)`` arbitraire
#: (plage volontairement plus large que celle des options générées par
#: `_st_options_periode_directe`, pour couvrir aussi bien le cas où
#: ``periode_par_defaut`` correspond à une option disponible que le cas
#: où elle n'y correspond à aucune) — converti en `PeriodeFiscale` dans le
#: corps de chaque test (import différé, règle 06).
_st_periode_par_defaut_arbitraire = st.one_of(
    st.none(),
    st.tuples(
        st.integers(min_value=2000, max_value=2100),
        st.integers(min_value=1, max_value=12),
    ),
)


class TestPersistanceChoixManuel:
    """Property 5 — persistance du choix manuel de l'opérateur."""

    # Feature: bilan-fiscal-employeur, Property 5: Persistance du choix manuel de l'opérateur
    @pytest.mark.property
    @given(
        options=_st_options_periode_directe(),
        index_option_choisie=st.integers(min_value=0),
        periode_par_defaut_1=_st_periode_par_defaut_arbitraire,
        periode_par_defaut_2=_st_periode_par_defaut_arbitraire,
    )
    @settings_large_input
    def test_libelle_deja_resolu_et_toujours_disponible_est_conserve_a_travers_plusieurs_reaffichages(
        self,
        options: tuple,
        index_option_choisie: int,
        periode_par_defaut_1,
        periode_par_defaut_2,
    ) -> None:
        """Property 5 (Requirement 3.4).

        Choisit une option de ``options`` comme libellé « déjà résolu »
        de la session (``cle_deja_definie=True``,
        ``valeur_en_session=option_choisie.libelle`` — ce libellé
        correspond, par construction, toujours à une option encore
        disponible de ``options``). Simule ensuite une séquence de
        plusieurs réaffichages en appelant
        `resoudre_periode_a_afficher` deux fois de suite avec les mêmes
        ``cle_deja_definie``/``valeur_en_session``, mais avec deux
        ``periode_par_defaut`` arbitraires et potentiellement distincts
        à chaque appel (simulant un jour différent d'un réaffichage à
        l'autre, y compris `None`) : les deux appels doivent retourner
        exactement ``valeur_en_session``, inchangée, jamais un nouveau
        calcul basé sur ``periode_par_defaut``.
        """
        from app.logique_metier.bilan_fiscal import (
            PeriodeFiscale,
            resoudre_periode_a_afficher,
        )

        option_choisie = options[index_option_choisie % len(options)]
        valeur_en_session = option_choisie.libelle

        def _vers_periode_fiscale(couple) -> "PeriodeFiscale | None":
            if couple is None:
                return None
            annee, mois = couple
            return PeriodeFiscale(annee=annee, mois=mois)

        for periode_par_defaut_appel in (
            _vers_periode_fiscale(periode_par_defaut_1),
            _vers_periode_fiscale(periode_par_defaut_2),
        ):
            resultat = resoudre_periode_a_afficher(
                cle_deja_definie=True,
                valeur_en_session=valeur_en_session,
                periode_par_defaut=periode_par_defaut_appel,
                options=options,
            )

            assert resultat == valeur_en_session, (
                "`resoudre_periode_a_afficher` doit conserver le libellé "
                "déjà résolu et toujours disponible "
                f"({valeur_en_session!r}), sans le remplacer par un "
                "nouveau calcul de présélection, même lorsque "
                f"`periode_par_defaut`={periode_par_defaut_appel!r} "
                f"diffère de la valeur en session ; obtenu {resultat!r}."
            )

    # Feature: bilan-fiscal-employeur, Property 5: Persistance du choix manuel de l'opérateur
    @pytest.mark.property
    @given(
        options=_st_options_periode_directe(),
        periode_par_defaut_couple=_st_periode_par_defaut_arbitraire,
    )
    @settings_large_input
    def test_cle_non_encore_definie_recalcule_depuis_periode_par_defaut(
        self,
        options: tuple,
        periode_par_defaut_couple,
    ) -> None:
        """Property 5, branche « première résolution de la session »
        (Requirement 3.4).

        Lorsque ``cle_deja_definie`` est faux (première résolution de la
        session — ``valeur_en_session`` n'a alors aucune portée),
        `resoudre_periode_a_afficher` doit recalculer et retourner le
        libellé de l'option de ``options`` dont `.periode ==
        periode_par_defaut` (ou `None` si ``periode_par_defaut`` est
        `None`, ou si aucune option de ``options`` ne correspond) —
        jamais une valeur figée d'une session précédente.
        """
        from app.logique_metier.bilan_fiscal import (
            PeriodeFiscale,
            resoudre_periode_a_afficher,
        )

        if periode_par_defaut_couple is None:
            periode_par_defaut = None
            libelle_attendu = None
        else:
            annee, mois = periode_par_defaut_couple
            periode_par_defaut = PeriodeFiscale(annee=annee, mois=mois)
            option_correspondante = next(
                (option for option in options if option.periode == periode_par_defaut),
                None,
            )
            libelle_attendu = (
                option_correspondante.libelle if option_correspondante else None
            )

        resultat = resoudre_periode_a_afficher(
            cle_deja_definie=False,
            valeur_en_session=None,
            periode_par_defaut=periode_par_defaut,
            options=options,
        )

        assert resultat == libelle_attendu, (
            "`resoudre_periode_a_afficher(cle_deja_definie=False, ...)` "
            "doit recalculer le libellé à partir de `periode_par_defaut` "
            f"; attendu {libelle_attendu!r}, obtenu {resultat!r} pour "
            f"periode_par_defaut={periode_par_defaut!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 5: Persistance du choix manuel de l'opérateur
    @pytest.mark.property
    @given(
        options=_st_options_periode_directe(),
        libelle_perime=st.text(min_size=1, max_size=20),
        periode_par_defaut_couple=_st_periode_par_defaut_arbitraire,
    )
    @settings_large_input
    def test_valeur_en_session_devenue_indisponible_recalcule_depuis_periode_par_defaut(
        self,
        options: tuple,
        libelle_perime: str,
        periode_par_defaut_couple,
    ) -> None:
        """Property 5, branche « option devenue indisponible »
        (Requirement 3.4).

        Lorsque ``cle_deja_definie`` est vrai mais que
        ``valeur_en_session`` ne correspond plus à aucune option de
        ``options`` (l'option précédemment choisie a disparu entre deux
        réaffichages), `resoudre_periode_a_afficher` doit recalculer et
        retourner le libellé de l'option dont `.periode ==
        periode_par_defaut` (ou `None` selon les mêmes règles que la
        branche « première résolution »), jamais la valeur périmée de
        ``valeur_en_session``.
        """
        from app.logique_metier.bilan_fiscal import (
            PeriodeFiscale,
            resoudre_periode_a_afficher,
        )

        libelles_disponibles = {option.libelle for option in options}
        assume(libelle_perime not in libelles_disponibles)

        if periode_par_defaut_couple is None:
            periode_par_defaut = None
            libelle_attendu = None
        else:
            annee, mois = periode_par_defaut_couple
            periode_par_defaut = PeriodeFiscale(annee=annee, mois=mois)
            option_correspondante = next(
                (option for option in options if option.periode == periode_par_defaut),
                None,
            )
            libelle_attendu = (
                option_correspondante.libelle if option_correspondante else None
            )

        resultat = resoudre_periode_a_afficher(
            cle_deja_definie=True,
            valeur_en_session=libelle_perime,
            periode_par_defaut=periode_par_defaut,
            options=options,
        )

        assert resultat == libelle_attendu, (
            "`resoudre_periode_a_afficher` doit recalculer le libellé à "
            "partir de `periode_par_defaut` lorsque `valeur_en_session` "
            f"({libelle_perime!r}) ne correspond plus à aucune option "
            f"disponible ; attendu {libelle_attendu!r}, obtenu "
            f"{resultat!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 5: Persistance du choix manuel de l'opérateur
    def test_exemple_choix_manuel_conserve_malgre_periode_par_defaut_differente_simulant_un_autre_jour(
        self,
    ) -> None:
        """Test d'exemple — choix manuel conservé malgré un
        `periode_par_defaut` différent, simulant un jour différent
        (Requirement 3.4).

        Un opérateur a choisi manuellement « Juin 2026 » durant sa
        session (``cle_deja_definie=True``,
        ``valeur_en_session="opt-2026-6"``). Un réaffichage ultérieur,
        simulant un jour différent où la présélection automatique
        cible désormais « Juillet 2026 »
        (``periode_par_defaut=PeriodeFiscale(2026, 7)``), doit tout de
        même retourner le choix manuel inchangé, tant que l'option
        « Juin 2026 » demeure disponible.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            resoudre_periode_a_afficher,
        )

        options = (
            OptionPeriode(
                libelle="opt-2026-6", periode=PeriodeFiscale(annee=2026, mois=6)
            ),
            OptionPeriode(
                libelle="opt-2026-7", periode=PeriodeFiscale(annee=2026, mois=7)
            ),
        )

        resultat = resoudre_periode_a_afficher(
            cle_deja_definie=True,
            valeur_en_session="opt-2026-6",
            periode_par_defaut=PeriodeFiscale(annee=2026, mois=7),
            options=options,
        )

        assert resultat == "opt-2026-6", (
            "Le choix manuel « opt-2026-6 » doit être conservé même si "
            "`periode_par_defaut` a changé pour Juillet 2026 (simulant "
            f"un autre jour) ; obtenu {resultat!r}."
        )


# ---------------------------------------------------------------------------
# Property 14 — Interruption de l'agrégation sur échec de désérialisation
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 14: Interruption de l'agrégation sur échec de désérialisation
#
# *Pour toute* base SQLite temporaire contenant au moins une ligne `paies`
# de statut `EMISE` dont le `payload_json` est syntaxiquement invalide ou
# structurellement non conforme au schéma `PayrollResult`,
# `lire_paies_emises` doit lever une exception (`json.JSONDecodeError` ou
# `pydantic.ValidationError`, toutes deux sous-classes de `ValueError`)
# plutôt que de retourner silencieusement un résultat partiel ou de
# substituer une valeur par défaut à la paie corrompue.
#
# _Requirements: 11.3_
# _Design: §Components §5 ; §Correctness Properties 14 ; §Error Handling_


#: DDL locale de la table `paies`, dupliquée volontairement depuis
#: `payroll_engine.register._DDL_PAIES` plutôt qu'importée : ce fichier de
#: test n'appelle jamais de fonction privée de `payroll_engine.register`
#: (même discipline que le module sous test, décision n° 5) — seule une
#: définition de schéma strictement locale au test permet d'insérer une
#: ligne `paies` dont le `payload_json` est délibérément corrompu (une
#: insertion via `inserer_paie` validerait le `PayrollResult` via Pydantic
#: *avant* toute écriture, ce qui rendrait impossible la construction du
#: cas testé ici).
_DDL_PAIES_TEST_CORROMPU = """
CREATE TABLE IF NOT EXISTS paies (
    id_paie             TEXT    PRIMARY KEY,
    employe_id          TEXT    NOT NULL,
    annee_fiscale       INTEGER NOT NULL,
    numero_periode      INTEGER NOT NULL,
    saison              TEXT    NOT NULL,
    version             INTEGER NOT NULL,
    statut              TEXT    NOT NULL,
    remplace_par_id     TEXT,
    date_creation       TEXT    NOT NULL,
    date_emission       TEXT,
    payload_json        TEXT    NOT NULL,
    payload_input_json  TEXT
);
"""


def _inserer_ligne_paie_corrompue(
    chemin_bd,
    payload_json_corrompu: str,
    id_paie: str = "PAIE-CORROMPUE-001",
) -> None:
    """Insère, en SQL direct, une ligne `paies` de statut `EMISE` dont le
    `payload_json` est délibérément corrompu (Property 14, Req 11.3).

    Contourne intentionnellement `payroll_engine.register.inserer_paie`
    (qui validerait ``payload_json_corrompu`` via
    `PayrollResult.model_validate_json` avant toute écriture, empêchant
    la construction du cas testé) — insertion brute via `sqlite3`,
    schéma créé localement par :data:`_DDL_PAIES_TEST_CORROMPU` si absent
    (idempotent, `CREATE TABLE IF NOT EXISTS`). Toutes les autres
    colonnes portent des valeurs fictives minimales (règle 04 —
    ``employe_id`` fictif ``EMPnnn``), sans incidence sur ce test :
    seule `lire_paies_emises` désérialise `payload_json`.
    """
    import sqlite3
    from datetime import datetime

    connexion = sqlite3.connect(str(chemin_bd))
    try:
        connexion.execute(_DDL_PAIES_TEST_CORROMPU)
        connexion.execute(
            "INSERT INTO paies (id_paie, employe_id, annee_fiscale, "
            "numero_periode, saison, version, statut, remplace_par_id, "
            "date_creation, date_emission, payload_json, "
            "payload_input_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id_paie,
                "EMP999",
                2026,
                1,
                "",
                1,
                StatutDePaie.EMISE.value,
                None,
                datetime(2026, 1, 1).isoformat(),
                datetime(2026, 1, 1).isoformat(),
                payload_json_corrompu,
                None,
            ),
        )
        connexion.commit()
    finally:
        connexion.close()


def _st_payload_json_invalide() -> st.SearchStrategy[str]:
    """Payload `payload_json` invalide arbitraire (Property 14, Req 11.3).

    Échantillonne parmi des payloads représentatifs des deux sous-cas
    explicitement cités par le Requirement 11.3 : JSON syntaxiquement
    invalide (non parsable par :func:`json.loads`), et JSON
    syntaxiquement valide mais structurellement non conforme au schéma
    `PayrollResult` (champs manquants ou de forme incorrecte).
    """
    return st.sampled_from(
        [
            # Syntaxiquement invalide (json.JSONDecodeError attendu).
            "{not valid json",
            "[1, 2,",
            "",
            "{'cle': 'guillemets simples'}",
            # Syntaxiquement valide, non conforme au schéma
            # PayrollResult (pydantic.ValidationError attendu).
            '{"foo": "bar"}',
            '{"id_paie": "X"}',
            "null",
            "[]",
        ]
    )


class TestEchecDeserialisation:
    """Property 14 — interruption de l'agrégation sur échec de
    désérialisation (intégration légère SQLite, insertion brute d'une
    ligne `payload_json` corrompue)."""

    # Feature: bilan-fiscal-employeur, Property 14: Interruption de l'agrégation sur échec de désérialisation
    @pytest.mark.property
    @given(
        paies_valides=_st_paies_emises(max_size=5),
        payload_json_corrompu=_st_payload_json_invalide(),
    )
    @settings_large_input
    def test_lire_paies_emises_leve_une_exception_plutot_que_de_retourner_un_resultat_partiel(
        self,
        paies_valides: tuple[PayrollResult, ...],
        payload_json_corrompu: str,
        tmp_path,
    ) -> None:
        """Property 14 (Req 11.3).

        Insère, dans une base SQLite temporaire, un ensemble arbitraire
        (potentiellement vide) de paies `EMISE` valides via
        `inserer_paie`, puis une ligne `paies` supplémentaire de statut
        `EMISE` dont le `payload_json` est délibérément corrompu (soit
        syntaxiquement invalide, soit syntaxiquement valide mais non
        conforme au schéma `PayrollResult`). `lire_paies_emises` doit
        alors lever une exception (`json.JSONDecodeError` ou
        `pydantic.ValidationError`, toutes deux sous-classes de
        `ValueError`) plutôt que de retourner un tuple partiel ignorant
        silencieusement la ligne corrompue — y compris lorsqu'aucune
        paie valide n'accompagne la ligne corrompue.

        Remarque (règle 04, isolation Hypothesis) : voir la remarque
        équivalente de `TestLirePaiesEmises` ci-dessus — le chemin de
        base est construit directement dans le corps du test à partir de
        `tmp_path` et d'un suffixe `uuid.uuid4().hex` tiré à chaque essai
        Hypothesis, plutôt que via la fixture `st_chemin_bd_temporaire`
        (resolue une seule fois par appel de fonction de test, donc
        partagée entre tous les essais d'un même `@given` malgré la
        suppression de `HealthCheck.function_scoped_fixture`).
        """
        from payroll_engine.register import inserer_paie

        from app.logique_metier.bilan_fiscal import lire_paies_emises

        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        # Bug corrigé après livraison (demande explicite de
        # l'utilisateur) — `inserer_paie` refuse désormais une seconde
        # ligne EMISE pour la même Paie_Logique `(employe_id,
        # annee_fiscale, numero_periode)` (voir
        # `TestRefusDoubleEmisePourMemePeriode` de
        # `tests/payroll_engine/test_register.py`). ``paies_valides``
        # (tous EMISE) ne garantit pas des périodes distinctes entre ses
        # éléments — ne conserver que le premier élément par période
        # rencontré, comportement de préservation pour cette property
        # (le comportement testé — interruption sur ligne corrompue —
        # ne dépend pas du nombre d'éléments valides effectivement
        # insérés).
        periodes_vues: set[tuple[str, int, int]] = set()
        for resultat in paies_valides:
            cle_periode = (
                resultat.employe_id,
                resultat.annee_fiscale,
                resultat.pay_period.numero_periode,
            )
            if cle_periode in periodes_vues:
                continue
            periodes_vues.add(cle_periode)
            inserer_paie(resultat, saison="", chemin_bd=chemin_bd)

        _inserer_ligne_paie_corrompue(chemin_bd, payload_json_corrompu)

        with pytest.raises(ValueError):
            lire_paies_emises(chemin_bd=chemin_bd)

    # Feature: bilan-fiscal-employeur, Property 14: Interruption de l'agrégation sur échec de désérialisation
    def test_exemple_payload_json_syntaxiquement_invalide_leve_json_decode_error(
        self,
        st_chemin_bd_temporaire,
    ) -> None:
        """Test d'exemple — sous-cas « JSON syntaxiquement invalide » (Req 11.3).

        Un `payload_json` qui n'est pas un JSON syntaxiquement valide
        (``"{not valid json"``) doit faire lever à `lire_paies_emises`
        exactement `json.JSONDecodeError` — jamais une exception
        différente, jamais un résultat partiel.
        """
        import json

        from app.logique_metier.bilan_fiscal import lire_paies_emises

        _inserer_ligne_paie_corrompue(st_chemin_bd_temporaire, "{not valid json")

        with pytest.raises(json.JSONDecodeError):
            lire_paies_emises(chemin_bd=st_chemin_bd_temporaire)

    # Feature: bilan-fiscal-employeur, Property 14: Interruption de l'agrégation sur échec de désérialisation
    def test_exemple_payload_json_valide_mais_non_conforme_leve_validation_error(
        self,
        st_chemin_bd_temporaire,
    ) -> None:
        """Test d'exemple — sous-cas « JSON valide, schéma non conforme » (Req 11.3).

        Un `payload_json` syntaxiquement valide (``'{"foo": "bar"}'``)
        mais qui ne correspond pas au schéma `PayrollResult` (champs
        requis manquants) doit faire lever à `lire_paies_emises`
        exactement `pydantic.ValidationError` — jamais une exception
        différente, jamais un résultat partiel.
        """
        import pydantic

        from app.logique_metier.bilan_fiscal import lire_paies_emises

        _inserer_ligne_paie_corrompue(st_chemin_bd_temporaire, '{"foo": "bar"}')

        with pytest.raises(pydantic.ValidationError):
            lire_paies_emises(chemin_bd=st_chemin_bd_temporaire)

    # Feature: bilan-fiscal-employeur, Property 14: Interruption de l'agrégation sur échec de désérialisation
    def test_exemple_executer_avec_capture_transforme_echec_deserialisation_en_erreur_affichable(
        self,
        st_chemin_bd_temporaire,
    ) -> None:
        """Test d'exemple — propagation jusqu'à `executer_avec_capture` (Req 11.3).

        `lire_paies_emises` n'intercepte localement ni
        `json.JSONDecodeError` ni `pydantic.ValidationError` (§Error
        Handling « Disjonction stricte ») : l'exception se propage
        intacte jusqu'à la couche de rendu, où `executer_avec_capture`
        (`app/logique_metier/erreurs.py`) la capture via sa branche
        générique `except ValueError` et la transforme en
        `ErreurDomaineAffichable("ValueError", <message d'origine
        intact>)`. Ce test vérifie cette transformation de bout en
        bout, sans aucune capture locale intermédiaire dans
        `bilan_fiscal.py`.
        """
        from app.logique_metier.bilan_fiscal import lire_paies_emises
        from app.logique_metier.erreurs import (
            ErreurDomaineAffichable,
            executer_avec_capture,
        )

        _inserer_ligne_paie_corrompue(st_chemin_bd_temporaire, "{not valid json")

        try:
            lire_paies_emises(chemin_bd=st_chemin_bd_temporaire)
        except ValueError as exc:
            message_attendu = str(exc)
        else:  # pragma: no cover - défensif, ne doit jamais être atteint
            pytest.fail(
                "`lire_paies_emises` devait lever une exception pour un "
                "`payload_json` syntaxiquement invalide, avant même "
                "l'appel à `executer_avec_capture`."
            )

        resultat = executer_avec_capture(
            lambda: lire_paies_emises(chemin_bd=st_chemin_bd_temporaire)
        )

        assert resultat == ErreurDomaineAffichable("ValueError", message_attendu), (
            "`executer_avec_capture` doit transformer l'échec de "
            "désérialisation propagé par `lire_paies_emises` en "
            "`ErreurDomaineAffichable(\"ValueError\", <message intact>)`, "
            f"sans capture locale intermédiaire ; attendu message "
            f"{message_attendu!r}, obtenu {resultat!r}."
        )


# ---------------------------------------------------------------------------
# Property 9 — Agrégation du drapeau CNESST en attente de classification
# ---------------------------------------------------------------------------
#
# Feature: bilan-fiscal-employeur, Property 9: Agrégation du drapeau CNESST en attente de classification
#
# *Pour tout* ensemble arbitraire de `PayrollResult` dont chacun porte un
# `cnesst_en_attente_classification` arbitraire (vrai ou faux), le
# drapeau agrégé du `TableauBilanFiscal` doit égaler exactement le OU
# logique de ce drapeau sur l'ensemble des paies — vrai si et seulement
# si au moins une paie de l'ensemble porte ce drapeau à vrai, faux (y
# compris pour l'ensemble vide) sinon.
#
# _Requirements: 8.8_
# _Design: §Components §4 ; §Correctness Properties 9_


class TestAgregationDrapeauCnesst:
    """Property 9 — agrégation du drapeau CNESST en attente de
    classification."""

    # Feature: bilan-fiscal-employeur, Property 9: Agrégation du drapeau CNESST en attente de classification
    @pytest.mark.property
    @given(paies=st.lists(st_payroll_result_arbitraire(), min_size=0, max_size=8))
    @settings_large_input
    def test_drapeau_agrege_egale_le_ou_logique_sur_lensemble_des_paies(
        self,
        paies: list[PayrollResult],
    ) -> None:
        """Property 9 (Requirement 8.8).

        Pour tout ensemble arbitraire de ``paies`` (dont chacune porte un
        ``cotisations_employeur.cnesst_en_attente_classification``
        arbitraire, généré librement par
        ``st_payroll_result_arbitraire``), le drapeau
        ``tableau.cnesst_en_attente_classification`` produit par
        ``construire_tableau_bilan_fiscal`` doit égaler exactement le OU
        logique de ce drapeau sur l'ensemble de ``paies`` — cette
        propriété couvre naturellement le cas de l'ensemble vide
        (``any(())`` vaut ``False``).
        """
        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        tableau = construire_tableau_bilan_fiscal(tuple(paies))

        drapeau_attendu = any(
            p.cotisations_employeur.cnesst_en_attente_classification
            for p in paies
        )

        assert tableau.cnesst_en_attente_classification == drapeau_attendu, (
            "`tableau.cnesst_en_attente_classification` doit égaler le OU "
            "logique de `cnesst_en_attente_classification` sur l'ensemble "
            f"des paies ; attendu {drapeau_attendu!r}, obtenu "
            f"{tableau.cnesst_en_attente_classification!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 9: Agrégation du drapeau CNESST en attente de classification
    def test_exemple_ensemble_vide_produit_un_drapeau_faux(self) -> None:
        """Test d'exemple — ensemble vide de paies (Req 8.8).

        Pour un tuple vide de `PayrollResult` (aucune Paie_Agregee),
        `construire_tableau_bilan_fiscal` doit produire un drapeau
        `cnesst_en_attente_classification` explicitement `False` — le OU
        logique d'un ensemble vide (`any(())`).
        """
        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        tableau = construire_tableau_bilan_fiscal(())

        assert tableau.cnesst_en_attente_classification is False, (
            "`construire_tableau_bilan_fiscal(())` doit produire "
            "`cnesst_en_attente_classification is False` pour l'ensemble "
            f"vide ; obtenu {tableau.cnesst_en_attente_classification!r}."
        )

    # Feature: bilan-fiscal-employeur, Property 9: Agrégation du drapeau CNESST en attente de classification
    @pytest.mark.property
    @given(paies=st.lists(st_payroll_result_arbitraire(), min_size=1, max_size=8))
    @settings_large_input
    def test_exemple_au_moins_une_paie_a_vrai_produit_un_drapeau_vrai(
        self,
        paies: list[PayrollResult],
    ) -> None:
        """Test d'exemple (déterministe) — au moins une paie à `True` (Req 8.8).

        Force, via `model_copy`, le drapeau
        `cnesst_en_attente_classification` de la **première** paie d'un
        ensemble arbitraire non vide à `True`, sans contraindre les
        autres paies. `construire_tableau_bilan_fiscal` doit alors
        produire un drapeau agrégé `True`, quelles que soient les
        valeurs des autres paies — exerçant déterministement la branche
        « au moins une paie à vrai » du OU logique.
        """
        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        premiere, *reste = paies
        premiere_forcee_vraie = premiere.model_copy(
            update={
                "cotisations_employeur": premiere.cotisations_employeur.model_copy(
                    update={"cnesst_en_attente_classification": True}
                )
            }
        )
        paies_avec_au_moins_un_vrai = (premiere_forcee_vraie, *reste)

        tableau = construire_tableau_bilan_fiscal(paies_avec_au_moins_un_vrai)

        assert tableau.cnesst_en_attente_classification is True, (
            "`construire_tableau_bilan_fiscal` doit produire "
            "`cnesst_en_attente_classification is True` lorsqu'au moins "
            "une paie de l'ensemble porte ce drapeau à `True` ; obtenu "
            f"{tableau.cnesst_en_attente_classification!r}."
        )


# ---------------------------------------------------------------------------
# Test de garde structurel (complément non-PBT au Requirement 11.1)
# ---------------------------------------------------------------------------
#
# Inspection `ast` du **code source** de `app/logique_metier/bilan_fiscal.py`
# (même patron que `tests/app/logique_metier/test_dernieres_paies.py::
# _noms_prives_importes_de_register`/`_alias_modules_register`/
# `_appelle_fonction_privee_de_register`) confirmant qu'aucune fonction de
# `payroll_engine/` autre que `chemin_bd_production` n'est importée ou
# appelée par ce module.
#
# Règle stricte, DIFFÉRENTE de celle appliquée à `dernieres_paies.py` :
# `dernieres_paies.py` interdit uniquement les fonctions PRIVÉES
# (préfixées `_`) de `payroll_engine.register`. Ce module-ci va plus loin
# (Requirement 11.1 — sommation directe, sans aucune formule fiscale) : il
# interdit TOUTE fonction de `payroll_engine/` (privée ou publique, dans
# `register` ou dans tout autre sous-module — `gains_bruts`, `rrq`,
# `rqap`, `impot_qc`, `impot_federal`, `charges_patronales`, `net_pay`,
# `assurance_emploi`, `parameters_loader`, `stockage_distant`), à la seule
# exception de `chemin_bd_production` (le point d'E/S déjà utilisé par
# `dernieres_paies.py`, décision n° 5, §Components §5 du design).
#
# Deux formes syntaxiques sont couvertes :
#
# 1. `ast.ImportFrom` dont le `module` est `"payroll_engine"` ou tout
#    sous-module `"payroll_engine.<x>"` — chaque nom importé doit être
#    exactement `"chemin_bd_production"`, sinon c'est une violation
#    (couvre `from payroll_engine.register import inserer_paie`,
#    `from payroll_engine import register`, `from payroll_engine.rrq
#    import calcul_rrq_employe`, etc.).
# 2. Accès par attribut (`ast.Attribute`) sur un alias local du module
#    `payroll_engine.register` obtenu par un import module-level
#    (`import payroll_engine.register as reg`,
#    `from payroll_engine import register`) — seul `.chemin_bd_production`
#    est autorisé sur un tel alias ; tout autre attribut
#    (`reg.inserer_paie`, `reg._creer_schema_si_absent`, etc.) est une
#    violation.
#
# _Requirements: 11.1_
# _Design: §Testing Strategy « Test de garde structurel »_


# ---------------------------------------------------------------------------
# Property 2 (tableau-de-bord-periode-globale) — Présélection par défaut
# toujours disponible
# ---------------------------------------------------------------------------
#
# Feature: tableau-de-bord-periode-globale, Property 2: Présélection par défaut toujours disponible
#
# *Pour toute* année courante et *tout* tuple de `PayrollResult` `EMISE`,
# `determiner_annee_par_defaut(annee_courante)` retourne
# `PeriodeFiscale(annee=annee_courante, mois=None)`, et cette période
# correspond toujours à une option de
# `construire_options_annee(paies_emises, annee_courante)`.
#
# _Requirements: 1.4, 1.5_
# _Design: `tableau-de-bord-periode-globale/design.md` §Components §1 ;
# §Correctness Properties 2_


class TestPreselectionAnneeParDefautToujoursDisponible:
    """Property 2 (`tableau-de-bord-periode-globale`) — présélection par
    défaut toujours disponible."""

    # Feature: tableau-de-bord-periode-globale, Property 2: Présélection par défaut toujours disponible
    @pytest.mark.property
    @given(
        paies_emises=_st_paies_emises(),
        annee_courante=st.integers(min_value=2020, max_value=2035),
    )
    @settings_large_input
    def test_annee_par_defaut_correspond_toujours_a_une_option_de_construire_options_annee(
        self,
        paies_emises: tuple[PayrollResult, ...],
        annee_courante: int,
    ) -> None:
        """Property 2 (Requirements 1.4, 1.5).

        Pour toute ``annee_courante`` et tout ``paies_emises`` (paies
        `EMISE` arbitraires, `date_paiement` libres),
        `determiner_annee_par_defaut(annee_courante)` doit retourner
        exactement `PeriodeFiscale(annee=annee_courante, mois=None)` —
        jamais une autre année, jamais un `Mois_Fiscal` (`mois` non
        `None`). Cette période retournée doit toujours correspondre à
        exactement une des options produites par
        `construire_options_annee(paies_emises, annee_courante)` (Req
        1.4 si l'année courante est déjà une Annee_Avec_Paie_Emise ;
        Req 1.5 via l'Option_Annee_Courante_De_Repli sinon) —
        `construire_options_annee` garantissant, par construction,
        qu'`annee_courante` y figure toujours exactement une fois.
        """
        from app.logique_metier.bilan_fiscal import (
            PeriodeFiscale,
            construire_options_annee,
            determiner_annee_par_defaut,
        )

        periode_par_defaut = determiner_annee_par_defaut(annee_courante)

        assert periode_par_defaut == PeriodeFiscale(
            annee=annee_courante, mois=None
        ), (
            "`determiner_annee_par_defaut(annee_courante)` doit retourner "
            f"exactement PeriodeFiscale(annee={annee_courante!r}, "
            f"mois=None) ; obtenu {periode_par_defaut!r}."
        )

        options = construire_options_annee(paies_emises, annee_courante)
        periodes_options = tuple(option.periode for option in options)

        assert periode_par_defaut in periodes_options, (
            "La période présélectionnée par défaut "
            f"({periode_par_defaut!r}) doit toujours correspondre à une "
            f"option de `construire_options_annee(paies_emises, "
            f"{annee_courante!r})` ; options obtenues : "
            f"{periodes_options!r}."
        )

        occurrences = periodes_options.count(periode_par_defaut)
        assert occurrences == 1, (
            "La période présélectionnée par défaut doit correspondre à "
            f"exactement une option (jamais un doublon) ; obtenu "
            f"{occurrences} occurrence(s) parmi {periodes_options!r}."
        )


#: Symboles de `payroll_engine/` autorisés dans `bilan_fiscal.py`
#: (règle 02, Requirement 11.1) — `chemin_bd_production` (point d'E/S,
#: résolution pure du chemin) et `telecharger_si_absent`
#: (`payroll_engine.stockage_distant` — utilitaire de synchronisation
#: de fichier sur hébergement à système de fichiers éphémère, JAMAIS
#: une fonction de calcul fiscal ; même exception déjà appliquée sans
#: restriction par `dernieres_paies.py`, bug corrigé après incident
#: `sqlite3.OperationalError: unable to open database file` constaté au
#: premier accès disque après un redémarrage à froid du conteneur).
#: Toute autre fonction de `payroll_engine/` (calcul de gains, retenues,
#: cotisations, etc.) reste interdite — le Bilan_Fiscal doit obtenir
#: chaque montant exclusivement par sommation directe des champs déjà
#: calculés et tracés de `PayrollResult`.
_SYMBOLES_PAYROLL_ENGINE_AUTORISES = frozenset(
    {"chemin_bd_production", "telecharger_si_absent"}
)


class TestAucunImportInterditPayrollEngine:
    """Test de garde structurel — aucune fonction de `payroll_engine/`
    en dehors de `_SYMBOLES_PAYROLL_ENGINE_AUTORISES` n'est importée par
    `bilan_fiscal.py` (règle 02, Requirement 11.1)."""

    def test_bilan_fiscal_nimporte_aucune_fonction_de_payroll_engine_sauf_chemin_bd_production(
        self,
    ) -> None:
        """`bilan_fiscal.py` n'importe/n'appelle aucune fonction de
        `payroll_engine/` en dehors de
        `_SYMBOLES_PAYROLL_ENGINE_AUTORISES` (Req 11.1).

        Inspection statique (`ast`) du **code source** du fichier — pas
        un import du module — afin que ce test reste collectable et
        significatif avant même que le fichier existe (règle 06). Tant
        que ``app/logique_metier/bilan_fiscal.py`` n'existe pas
        (implémentation prévue à la tâche 9), ce test est explicitement
        marqué ``skip`` plutôt que d'échouer de façon confuse
        (``FileNotFoundError``) — même discipline que
        `test_dernieres_paies.py::
        test_dernieres_paies_napelle_aucune_fonction_privee_de_register`.

        `import ast`/`from pathlib import Path` sont importés localement
        (aucun de ces deux symboles n'est encore présent dans le bloc
        d'imports de tête de ce fichier) plutôt que d'ajouter un import
        de module partagé par l'ensemble du fichier.
        """
        import ast
        from pathlib import Path

        repo_root = Path(__file__).parent.parent.parent.parent
        chemin_module = repo_root / "app" / "logique_metier" / "bilan_fiscal.py"

        if not chemin_module.exists():
            pytest.skip(
                "app/logique_metier/bilan_fiscal.py n'existe pas encore "
                "— tâche 9"
            )

        arbre = ast.parse(chemin_module.read_text(encoding="utf-8"))

        violations: list[str] = []

        # --- Forme 1 : `ast.ImportFrom` depuis `payroll_engine` ou tout
        #     sous-module `payroll_engine.<x>` — seul le nom
        #     `chemin_bd_production` est autorisé.
        alias_modules_register: set[str] = set()

        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.ImportFrom) and noeud.module is not None:
                if noeud.module == "payroll_engine" or noeud.module.startswith(
                    "payroll_engine."
                ):
                    for alias in noeud.names:
                        if alias.name not in _SYMBOLES_PAYROLL_ENGINE_AUTORISES:
                            violations.append(
                                f"from {noeud.module} import {alias.name}"
                                + (f" as {alias.asname}" if alias.asname else "")
                            )
                        # `from payroll_engine import register` (ou tout
                        # alias) désigne aussi le module lui-même — tracé
                        # pour la vérification par attribut ci-dessous,
                        # même si déjà signalé comme violation
                        # ci-dessus (import du sous-module entier).
                        if (
                            noeud.module == "payroll_engine"
                            and alias.name == "register"
                        ):
                            alias_modules_register.add(alias.asname or alias.name)

            # --- Alias module-level de `payroll_engine.register`
            #     (`import payroll_engine.register as reg`) — tracé pour
            #     la vérification par attribut ci-dessous.
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    if alias.name in ("payroll_engine.register", "payroll_engine"):
                        alias_modules_register.add(
                            alias.asname or alias.name.split(".")[0]
                        )

        # --- Forme 2 : accès par attribut sur un alias de
        #     `payroll_engine.register` — seul `.chemin_bd_production`
        #     est autorisé.
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Attribute) and isinstance(
                noeud.value, ast.Name
            ):
                if (
                    noeud.value.id in alias_modules_register
                    and noeud.attr not in _SYMBOLES_PAYROLL_ENGINE_AUTORISES
                ):
                    violations.append(f"{noeud.value.id}.{noeud.attr}(...)")

        if violations:
            pytest.fail(
                "bilan_fiscal.py importe ou appelle une fonction de "
                "`payroll_engine/` en dehors des symboles autorisés "
                "(Requirement 11.1, règle 02) — le Bilan_Fiscal doit "
                "obtenir chaque montant exclusivement par sommation "
                "directe des champs déjà calculés et tracés de "
                "`PayrollResult`, sans jamais appeler une fonction du "
                "moteur de paie (autre que le point d'E/S "
                "`chemin_bd_production`). Violations détectées : "
                + ", ".join(sorted(violations))
            )


# ---------------------------------------------------------------------------
# Spec ``tableau-de-bord-periode-globale`` — Property 1 : Options d'année
# exactes et sans doublon (Selecteur_De_Periode_Global, `construire_options_
# annee`)
# ---------------------------------------------------------------------------
#
# Feature: tableau-de-bord-periode-globale, Property 1: Options d'année exactes et sans doublon
#
# *Pour tout* tuple de `PayrollResult` `EMISE` et *toute* année courante,
# l'ensemble des années produites par `construire_options_annee` est
# exactement l'union des années de rattachement présentes dans les paies
# et de l'année courante, chacune apparaissant exactement une fois,
# triées par année décroissante, et aucune option ne porte de
# `periode.mois` non `None`.
#
# Validates: Requirements 1.1, 1.2, 1.3


def _st_annee_courante() -> st.SearchStrategy[int]:
    """Année courante arbitraire, même fenêtre que `st_periode_fiscale`
    (`tests/app/strategies.py`) — aucune signification métier propre au
    delà de couvrir un ordre de grandeur cohérent avec les années de
    rattachement générées par `st_payroll_result_arbitraire`."""
    return st.integers(min_value=2020, max_value=2035)


def _construire_paie_emise_exemple(*, date_paiement: date) -> PayrollResult:
    """`PayrollResult` `EMISE` concret minimal, `date_paiement` imposée
    (tâche 1.4, tests d'exemple des cas limites de
    `construire_options_annee`).

    Fabrique locale directe (même patron que
    `tests/models/test_payroll_result.py::_make_result`) plutôt qu'un
    tirage Hypothesis : ces tests d'exemple n'ont besoin de faire varier
    que ``date_paiement`` — tous les autres champs (montants à zéro,
    identifiants fixes) sont sans incidence sur le comportement de
    `construire_options_annee`, qui ne lit que `pay_period.date_paiement`
    et `statut`. Seule `date_paiement` diffère d'un appel à l'autre.
    """
    from datetime import datetime, timedelta
    from decimal import Decimal

    from models.cumuls import CumulsYTD
    from models.enums import FrequencePaie, Juridiction, ModeArrondissement
    from models.pay_period import PayPeriod, WeekSegment
    from models.payroll_result import (
        CotisationsEmployeur,
        GainsDecomposes,
        MontantAvecTrace,
        RetenuesEmploye,
    )
    from models.trace import CalculationTrace

    def _trace(resultat: Decimal) -> CalculationTrace:
        return CalculationTrace(
            source="TP-1015.F 2026",
            annee=2026,
            juridiction=Juridiction.QUEBEC,
            section="Section fixture (tâche 1.4)",
            parametres_utilises={},
            entrees={},
            sous_totaux={},
            mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
            precision_arrondissement=2,
            resultat=resultat,
        )

    def _montant(montant: Decimal) -> MontantAvecTrace:
        return MontantAvecTrace(montant=montant, trace=_trace(montant))

    zero = Decimal("0.00")

    date_debut = date_paiement - timedelta(days=18)
    date_fin = date_debut + timedelta(days=13)
    semaine_1 = WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=zero,
        heures_supplementaires=zero,
    )
    semaine_2 = WeekSegment(
        date_debut=date_debut + timedelta(days=7),
        date_fin=date_fin,
        heures_normales=zero,
        heures_supplementaires=zero,
    )
    pay_period = PayPeriod(
        numero_periode=1,
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_paiement,
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=26,
        annee_fiscale=date_paiement.year,
        semaines=(semaine_1, semaine_2),
    )

    retenues_employe = RetenuesEmploye(
        rrq=_montant(zero),
        rqap=_montant(zero),
        ae=_montant(zero),
        impot_qc_formule=_montant(zero),
        impot_qc_retenu=_montant(zero),
        impot_federal_formule=_montant(zero),
        impot_federal_retenu=_montant(zero),
        total_retenues_employe=zero,
    )
    cotisations_employeur = CotisationsEmployeur(
        rrq_employeur=_montant(zero),
        rqap_employeur=_montant(zero),
        ae_employeur=_montant(zero),
        fss=_montant(zero),
        cnesst=_montant(zero),
        cnesst_en_attente_classification=False,
        cnt=_montant(zero),
        total_cotisations_employeur=zero,
    )
    gains = GainsDecomposes(
        salaire_regulier=zero,
        heures_supplementaires_montant=zero,
        vacances=zero,
        jours_feries_manuels=zero,
        brut_total=zero,
        multiplicateur_heures_supp=Decimal("1.5"),
        seuil_heures_supp_hebdo=Decimal("40"),
    )

    return PayrollResult(
        id_paie=f"PAIE-EMP001-{date_paiement.year}-1-EXEMPLE-{date_paiement.isoformat()}",
        version=1,
        employe_id="EMP001",
        annee_fiscale=date_paiement.year,
        pay_period=pay_period,
        gains=gains,
        retenues_employe=retenues_employe,
        cotisations_employeur=cotisations_employeur,
        net=zero,
        cout_employeur=zero,
        cumuls_fin=CumulsYTD.zero("EMP001", date_paiement.year),
        statut=StatutDePaie.EMISE,
        remplace_par_id=None,
        date_creation=datetime(date_paiement.year, 1, 1, 12, 0, 0),
        date_emission=datetime(date_paiement.year, 1, 1, 12, 0, 0),
    )


class TestConstruireOptionsAnneeExactesEtSansDoublon:
    """Property 1 (spec ``tableau-de-bord-periode-globale``) — options
    d'année exactes et sans doublon."""

    # Feature: tableau-de-bord-periode-globale, Property 1: Options d'année exactes et sans doublon
    @pytest.mark.property
    @given(
        paies_emises=_st_paies_emises(),
        annee_courante=_st_annee_courante(),
    )
    @settings_large_input
    def test_options_annee_exactes_sans_doublon_triees_decroissant(
        self,
        paies_emises: tuple[PayrollResult, ...],
        annee_courante: int,
    ) -> None:
        """Property 1 (Requirements 1.1, 1.2, 1.3).

        L'ensemble des années portées par les `OptionPeriode` retournées
        par `construire_options_annee(paies_emises, annee_courante)` doit
        correspondre exactement à l'union des années de rattachement
        (`mois_annee_rattachement(pay_period.date_paiement)[0]`) de
        ``paies_emises`` et de ``annee_courante`` — chaque année
        n'apparaissant qu'une seule fois (aucun doublon, notamment quand
        ``annee_courante`` est déjà une Annee_Avec_Paie_Emise), triées
        par année décroissante, et sans jamais produire d'option
        `periode.mois` non `None` (aucune option de type Mois_Fiscal).
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            construire_options_annee,
            formater_option_annee_complete,
            mois_annee_rattachement,
        )

        annees_attendues = {
            mois_annee_rattachement(paie.pay_period.date_paiement)[0]
            for paie in paies_emises
        }
        annees_attendues.add(annee_courante)

        options: tuple[OptionPeriode, ...] = construire_options_annee(
            paies_emises, annee_courante
        )

        annees_obtenues = [option.periode.annee for option in options]

        assert set(annees_obtenues) == annees_attendues, (
            "`construire_options_annee(paies_emises, annee_courante)` doit "
            "produire exactement l'union des années de rattachement des "
            "paies et de `annee_courante` ; attendu "
            f"{sorted(annees_attendues, reverse=True)!r}, obtenu "
            f"{sorted(annees_obtenues, reverse=True)!r}."
        )
        assert len(options) == len(annees_attendues), (
            "`construire_options_annee` ne doit produire aucune année en "
            f"double ; attendu {len(annees_attendues)} option(s) distincte(s), "
            f"obtenu {len(options)}."
        )
        assert annees_obtenues == sorted(annees_attendues, reverse=True), (
            "`construire_options_annee` doit trier ses options par année "
            f"décroissante ; attendu {sorted(annees_attendues, reverse=True)!r}, "
            f"obtenu {annees_obtenues!r}."
        )
        assert all(option.periode.mois is None for option in options), (
            "`construire_options_annee` ne doit jamais produire d'option "
            "de type Mois_Fiscal (`periode.mois` doit toujours valoir "
            f"`None`) ; obtenu {[o.periode for o in options]!r}."
        )
        assert all(
            option.libelle == formater_option_annee_complete(option.periode.annee)
            for option in options
        ), (
            "chaque `OptionPeriode.libelle` doit correspondre à "
            "`formater_option_annee_complete(periode.annee)`."
        )

    # Feature: tableau-de-bord-periode-globale, Property 1: Options d'année exactes et sans doublon
    def test_exemple_annee_courante_deja_presente_parmi_les_annee_avec_paie_emise_ne_produit_pas_de_doublon(
        self,
    ) -> None:
        """Test d'exemple — cas limite « année courante déjà présente
        parmi les Annee_Avec_Paie_Emise » (Requirements 1.2, 1.3).

        ``paies_emises`` contient une paie `EMISE` concrète dont l'année
        de rattachement (`mois_annee_rattachement(pay_period.
        date_paiement)[0]`) est exactement ``annee_courante`` (2026).
        Puisque l'année courante est déjà une Annee_Avec_Paie_Emise,
        `construire_options_annee` NE DOIT PAS ajouter
        l'Option_Annee_Courante_De_Repli (Req 1.3) — il ne doit y avoir
        qu'une seule option pour 2026, jamais un doublon (Req 1.2).
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            construire_options_annee,
            formater_option_annee_complete,
        )

        annee_courante = 2026
        paies_emises = (
            _construire_paie_emise_exemple(date_paiement=date(2026, 7, 10)),
        )

        options = construire_options_annee(paies_emises, annee_courante)

        annees_obtenues = [option.periode.annee for option in options]

        assert annees_obtenues.count(annee_courante) == 1, (
            "Lorsque l'année courante (2026) est déjà une "
            "Annee_Avec_Paie_Emise, `construire_options_annee` ne doit "
            "produire qu'une seule option pour cette année (jamais de "
            f"doublon) ; obtenu {annees_obtenues!r}."
        )
        assert options == (
            OptionPeriode(
                libelle=formater_option_annee_complete(annee_courante),
                periode=PeriodeFiscale(annee=annee_courante, mois=None),
            ),
        ), (
            "`construire_options_annee` doit produire exactement une "
            f"option unique pour 2026 ; obtenu {options!r}."
        )

    # Feature: tableau-de-bord-periode-globale, Property 1: Options d'année exactes et sans doublon
    def test_exemple_paies_emises_vide_produit_une_seule_option_de_repli(
        self,
    ) -> None:
        """Test d'exemple — cas limite « `paies_emises` vide » (Requirements
        1.2, 1.3).

        Lorsque ``paies_emises`` est un tuple vide (aucune
        Annee_Avec_Paie_Emise, quelle que soit l'année courante),
        `construire_options_annee` doit produire exactement une seule
        option : l'Option_Annee_Courante_De_Repli, portant `annee_courante`
        et `periode.mois is None`.
        """
        from app.logique_metier.bilan_fiscal import (
            OptionPeriode,
            PeriodeFiscale,
            construire_options_annee,
            formater_option_annee_complete,
        )

        annee_courante = 2026

        options = construire_options_annee((), annee_courante)

        assert options == (
            OptionPeriode(
                libelle=formater_option_annee_complete(annee_courante),
                periode=PeriodeFiscale(annee=annee_courante, mois=None),
            ),
        ), (
            "`construire_options_annee((), annee_courante)` doit produire "
            "exactement une seule option de repli pour l'année courante "
            f"; obtenu {options!r}."
        )

# ---------------------------------------------------------------------------
# Requirement 2.2 (spec ``tableau-de-bord-periode-globale``) — cas
# `paies_emises = ()` avec l'Option_Annee_Courante_De_Repli sélectionnée
# ---------------------------------------------------------------------------
#
# Critère d'acceptation non universel (un seul cas explicite suffit,
# design §Testing Strategy) : aucune ligne ni aucun total du
# Tableau_Bilan_Fiscal ne doit afficher l'indicateur d'indisponibilité
# (`None`) lorsque `construire_tableau_bilan_fiscal` est appelée avec un
# tuple de paies vide — cas produit par la sélection de l'Option_Annee_
# Courante_De_Repli (aucune Paie_Emise pour l'année sélectionnée).
#


class TestEnsembleVideAvecOptionAnneeCouranteDeRepli:
    """Requirement 2.2 (spec ``tableau-de-bord-periode-globale``) — le
    Tableau_Bilan_Fiscal de l'Option_Annee_Courante_De_Repli n'affiche
    jamais l'indicateur d'indisponibilité."""

    def test_exemple_paies_emises_vide_aucun_total_ni_aucune_ligne_nest_indisponible(
        self,
    ) -> None:
        """Test d'exemple — `construire_tableau_bilan_fiscal(())` (Req 2.2).

        Lorsque `paies_emises` est vide (Option_Annee_Courante_De_Repli
        sélectionnée, aucune Paie_Emise pour l'année sélectionnée),
        chacune des neuf `LigneBilan` mono-juridictionnelles ET chacun
        des six totaux (`total_retenues_qc`/`ca`, `total_cotisations_qc`/
        `ca`, `grand_total_qc`/`ca`, `grand_total_combine`,
        `total_salaires_nets`, `masse_salariale_totale`) doivent valoir
        explicitement `Decimal("0.00")` — jamais `None` (l'indicateur
        d'indisponibilité).
        """
        from decimal import Decimal

        from app.logique_metier.bilan_fiscal import construire_tableau_bilan_fiscal

        tableau = construire_tableau_bilan_fiscal(())

        zero = Decimal("0.00")

        for nom_ligne, _extracteur, _colonne_attribuee in _LIGNES_MONO_JURIDICTIONNELLES:
            ligne = getattr(tableau, nom_ligne)
            assert ligne.qc == zero, (
                f"`tableau.{nom_ligne}.qc` doit valoir `Decimal('0.00')` "
                f"pour `paies_emises = ()` ; obtenu {ligne.qc!r}."
            )
            assert ligne.ca == zero, (
                f"`tableau.{nom_ligne}.ca` doit valoir `Decimal('0.00')` "
                f"pour `paies_emises = ()` ; obtenu {ligne.ca!r}."
            )

        # Ligne Impôt (bi-juridictionnelle) — également jamais None.
        assert tableau.ligne_impot.qc == zero, (
            "`tableau.ligne_impot.qc` doit valoir `Decimal('0.00')` pour "
            f"`paies_emises = ()` ; obtenu {tableau.ligne_impot.qc!r}."
        )
        assert tableau.ligne_impot.ca == zero, (
            "`tableau.ligne_impot.ca` doit valoir `Decimal('0.00')` pour "
            f"`paies_emises = ()` ; obtenu {tableau.ligne_impot.ca!r}."
        )

        totaux = {
            "total_retenues_qc": tableau.total_retenues_qc,
            "total_retenues_ca": tableau.total_retenues_ca,
            "total_cotisations_qc": tableau.total_cotisations_qc,
            "total_cotisations_ca": tableau.total_cotisations_ca,
            "grand_total_qc": tableau.grand_total_qc,
            "grand_total_ca": tableau.grand_total_ca,
            "grand_total_combine": tableau.grand_total_combine,
            "total_salaires_nets": tableau.total_salaires_nets,
            "masse_salariale_totale": tableau.masse_salariale_totale,
        }
        for nom_total, valeur in totaux.items():
            assert valeur is not None, (
                f"`tableau.{nom_total}` ne doit jamais être `None` "
                "(indicateur d'indisponibilité) pour `paies_emises = ()` "
                "— l'Option_Annee_Courante_De_Repli doit produire un "
                f"Tableau_Bilan_Fiscal intégralement à zéro ; obtenu None pour {nom_total!r}."
            )
            assert valeur == zero, (
                f"`tableau.{nom_total}` doit valoir explicitement "
                f"`Decimal('0.00')` pour `paies_emises = ()` ; obtenu "
                f"{valeur!r}."
            )

        assert tableau.cnesst_en_attente_classification is False, (
            "`tableau.cnesst_en_attente_classification` doit valoir "
            "`False` pour `paies_emises = ()` ; obtenu "
            f"{tableau.cnesst_en_attente_classification!r}."
        )
