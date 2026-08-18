"""Stratégies Hypothesis dédiées à la spec ``interface-streamlit``.

Design de référence : ``design.md`` §Testing Strategy « Stratégies
Hypothesis réutilisées et nouvelles » (spec ``interface-streamlit``,
tâche 1.1).

Ce module regroupe les stratégies et fixtures **nouvelles** nécessaires
aux property tests des tâches 2 à 8 (round-trip des deux annuaires JSON,
dérivation des semaines constituantes, assemblage du ``PayrollInput``
depuis le Formulaire_Paie) :

- ``st_employee_valide()`` — ``Employee`` valide dans le périmètre Camp
  LilySO (province :attr:`~models.enums.Juridiction.QUEBEC` uniquement,
  ``taux_indemnite_vacances`` ∈ ``{0.04, 0.06}`` — contraintes déjà
  portées par le modèle lui-même, non dupliquées ici), identifiant
  exclusivement fictif ``EMPnnn`` (règle 04).
- ``st_fiche_coordonnees_valide()`` — ``FicheCoordonnees`` valide,
  ``employe_id`` de forme ``EMPnnn``, coordonnées manifestement fictives
  (``"555-01XX"``, ``"test-XX@example.invalid"``, Req 19.4).
- ``st_dates_periode_valide()`` — paire ``(date_debut, date_fin)`` telle
  que ``date_fin == date_debut + timedelta(days=13)``, satisfaisant par
  construction la contrainte de contiguïté/couverture de ``PayPeriod``
  (Properties 10, 11).
- ``st_chemin_json_temporaire(tmp_path)`` — fixture pytest (pas une
  stratégie Hypothesis) qui fournit une fabrique de chemins
  ``tmp_path / f"{prefixe}_{uuid4().hex}.json"``, un chemin neuf et
  distinct à chaque appel (un annuaire employés, un annuaire
  coordonnées — Properties 1, 2, 3, 15), jamais un chemin de production
  (règle 04).

**Réutilisation directe, sans duplication (Property 9)** : la fusion
``ParametresAnnee`` Québec + Canada nécessaire à
``charger_parametres_fusionnes`` (tâche 6.2) réutilise **telle quelle**
``tests/strategies.py::st_parametres_annee_2026_qc_ca`` — aucune
nouvelle génération de ``ParametresAnnee`` n'est ajoutée dans ce module.
Les tests de la tâche 6.2 importent directement
``from tests.strategies import st_parametres_annee_2026_qc_ca``.

Import différé de ``FicheCoordonnees`` (règle 06, TDD) : ce modèle est
défini par ``app/logique_metier/annuaire_coordonnees.py``, qui n'existe
pas encore au moment où ce fichier de stratégies est écrit (tâche 1.1
précède la tâche 4.1/14.1). L'import est donc effectué **à l'intérieur**
du corps de ``st_fiche_coordonnees_valide()``, jamais au niveau module,
pour que l'import de ``tests.app.strategies`` (et donc la collecte des
tests qui l'utilisent) ne lève pas ``ModuleNotFoundError`` avant que le
module cible existe. L'appel effectif de cette stratégie continuera de
lever ``ModuleNotFoundError`` tant que la tâche 4.1/14.1 n'est pas faite
— comportement attendu et correct au titre de la règle 06 (tests rouges
avant implémentation).

Règle 01 : chaque stratégie manipulant un montant ou une durée d'heures
DOIT retourner un ``Decimal`` (jamais un ``float``). ``FicheCoordonnees``
ne porte aucun champ ``Decimal`` (absence de montant monétaire) — la
règle ne s'y applique donc pas, cohérent avec le Glossary de
``requirements.md``.

Règle 04 : tous les identifiants générés sont exclusivement de forme
fictive ``EMPnnn`` ; tous les téléphones/courriels générés sont
manifestement fictifs (préfixe ``555-01`` réservé aux exemples fictifs
nord-américains, domaine ``example.invalid`` réservé par la RFC 2606 aux
exemples ne devant jamais résoudre).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest
from hypothesis import strategies as st

from models.employee import Employee
from models.enums import Juridiction

__all__ = [
    "st_employee_valide",
    "st_fiche_coordonnees_valide",
    "st_dates_periode_valide",
    "st_chemin_json_temporaire",
]


# ===========================================================================
# Bornes internes partagées (non exportées)
# ===========================================================================
#
# Fenêtre de dates cohérente avec ``tests/strategies.py`` (même ordre de
# grandeur), sans viser une réutilisation directe : ce module a ses
# propres besoins (dates de naissance/embauche d'un ``Employee`` de
# Formulaire_Paie plutôt que d'un ``PayrollInput`` complet).
_DATE_MIN = date(2024, 1, 1)
_DATE_MAX = date(2028, 6, 30)

#: Bornes des montants monétaires génériques d'``Employee`` (crédits
#: TP-1015.3 / TD1, retenues additionnelles) — mêmes ordres de grandeur
#: que ``tests/strategies.py::_MAX_CREDIT`` /
#: ``_MAX_RETENUE_ADDITIONNELLE``, dupliqués ici volontairement pour ne
#: pas créer de dépendance entre les deux modules de stratégies (l'un
#: dédié au moteur, l'autre à l'interface).
_MAX_CREDIT = Decimal("50000.00")
_MAX_RETENUE_ADDITIONNELLE = Decimal("500.00")


@st.composite
def _st_employe_id(draw: st.DrawFn) -> str:
    """Identifiant employé fictif ``EMPnnn`` (règle 04 — jamais de NAS réel)."""
    n = draw(st.integers(min_value=1, max_value=999))
    return f"EMP{n:03d}"


def _st_decimal_monetaire(*, max_value: Decimal) -> st.SearchStrategy[Decimal]:
    """``Decimal`` ∈ [0.00, max_value], deux décimales (règle 01)."""
    return st.decimals(
        min_value=Decimal("0.00"),
        max_value=max_value,
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


# ===========================================================================
# Stratégies nouvelles (design §Testing Strategy « ... et nouvelles »)
# ===========================================================================


@st.composite
def st_employee_valide(draw: st.DrawFn) -> Employee:
    """``Employee`` valide dans le périmètre Camp LilySO (Req 19.1).

    Design (§Testing Strategy « Stratégies Hypothesis réutilisées et
    nouvelles ») : cette stratégie **délègue** aux contraintes déjà
    connues et déjà validées du modèle :class:`~models.employee.Employee`
    (``moteur-paie-contrats``) — elle ne réimplémente aucune règle
    métier, elle se contente de fournir des valeurs qui satisfont ces
    contraintes par construction :

    - ``province_travail`` fixée à :attr:`Juridiction.QUEBEC` (règle 03,
      seule valeur non rejetée à la construction) ;
    - ``taux_indemnite_vacances`` tiré dans
      ``{Decimal("0.04"), Decimal("0.06")}`` (règle 03, Req 11.3 de
      ``moteur-paie-contrats``) ;
    - ``id`` exclusivement de forme ``EMPnnn`` fictive (règle 04) —
      jamais un identifiant nominatif réel ;
    - ``nom_affichage`` généré à partir de l'``id`` fictif
      (``f"Employe Test {id}"``), jamais un nom réel (règle 04).

    Toute autre combinaison générée par cette stratégie reste dans la
    matrice supportée (aucune valeur hors matrice n'est produite ici :
    ce n'est pas son rôle — voir les tests dédiés de
    ``tests/models/test_employee.py`` pour les cas de refus).
    """
    employe_id = draw(_st_employe_id())
    date_embauche = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    return Employee(
        id=employe_id,
        nom_affichage=f"Employe Test {employe_id}",
        date_naissance=draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX)),
        province_travail=Juridiction.QUEBEC,
        titre_emploi=draw(st.sampled_from(["Moniteur", "Monitrice", "Cuisinier"])),
        taux_horaire_base=draw(
            st.decimals(
                min_value=Decimal("10.00"),
                max_value=Decimal("50.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        date_embauche=date_embauche,
        date_fin_emploi=None,
        taux_indemnite_vacances=draw(
            st.sampled_from([Decimal("0.04"), Decimal("0.06")])
        ),
        exoneration_TP1015_3=draw(st.booleans()),
        exoneration_TD1=draw(st.booleans()),
        montant_total_TP1015_3=draw(_st_decimal_monetaire(max_value=_MAX_CREDIT)),
        montant_total_TD1=draw(_st_decimal_monetaire(max_value=_MAX_CREDIT)),
        retenue_additionnelle_QC=draw(
            _st_decimal_monetaire(max_value=_MAX_RETENUE_ADDITIONNELLE)
        ),
        retenue_additionnelle_federale=draw(
            _st_decimal_monetaire(max_value=_MAX_RETENUE_ADDITIONNELLE)
        ),
    )


@st.composite
def st_fiche_coordonnees_valide(draw: st.DrawFn) -> "FicheCoordonnees":  # noqa: F821
    """``FicheCoordonnees`` valide (Req 19.4, Req 20).

    Design (§Testing Strategy « Stratégies Hypothesis réutilisées et
    nouvelles ») : ``employe_id`` exclusivement de forme ``EMPnnn``
    fictive (règle 04, cohérent avec ``st_employee_valide``) ; les
    champs optionnels (``nom_complet_reel``, ``nas``,
    ``adresse_residentielle``, ``courriel``, ``telephone``) sont soit
    absents (``None``), soit des valeurs **manifestement fictives** :

    - téléphone : ``f"555-01{nn:02d}"`` (préfixe ``555-01`` réservé aux
      exemples fictifs nord-américains, jamais un numéro assignable
      réel) ;
    - courriel : ``f"test-{nn:02d}@example.invalid"`` (domaine
      ``.invalid`` réservé par la RFC 2606, ne résout jamais) ;
    - nom complet / adresse / NAS : chaînes fictives explicitement
      préfixées ``"Fictif"`` — jamais une donnée nominative réelle
      (règle 04).

    Import différé de :class:`FicheCoordonnees` (voir docstring de
    module) : ce modèle n'existe pas encore tant que la tâche 4.1/14.1
    n'a pas créé ``app/logique_metier/annuaire_coordonnees.py``. L'appel
    de cette stratégie lève ``ModuleNotFoundError`` jusque là —
    comportement attendu (règle 06).
    """
    from app.logique_metier.annuaire_coordonnees import FicheCoordonnees

    employe_id = draw(_st_employe_id())
    nn = draw(st.integers(min_value=0, max_value=99))

    prenom = draw(st.one_of(st.none(), st.just(f"Fictif Prénom {nn:02d}")))
    nom = draw(st.one_of(st.none(), st.just(f"Fictif Nom {nn:02d}")))
    nas = draw(st.one_of(st.none(), st.just(f"Fictif NAS {nn:02d}")))
    adresse_residentielle = draw(
        st.one_of(st.none(), st.just(f"Fictif Adresse {nn:02d}"))
    )
    courriel = draw(
        st.one_of(st.none(), st.just(f"test-{nn:02d}@example.invalid"))
    )
    telephone = draw(st.one_of(st.none(), st.just(f"555-01{nn:02d}")))

    return FicheCoordonnees(
        employe_id=employe_id,
        prenom=prenom,
        nom=nom,
        nas=nas,
        adresse_residentielle=adresse_residentielle,
        courriel=courriel,
        telephone=telephone,
    )


@st.composite
def st_dates_periode_valide(draw: st.DrawFn) -> tuple[date, date]:
    """Paire ``(date_debut, date_fin)`` satisfaisant la contiguïté de ``PayPeriod``.

    Design (§Testing Strategy « Stratégies Hypothesis réutilisées et
    nouvelles ») : génère ``date_debut`` puis calcule mécaniquement
    ``date_fin = date_debut + timedelta(days=13)`` — quatorze jours
    couvrant exactement deux semaines contiguës de sept jours chacune.
    Cette construction satisfait *par construction* la contrainte de
    contiguïté/couverture déjà validée par
    :class:`~models.pay_period.PayPeriod` (aucune régénération
    indépendante de ``date_fin`` qui risquerait de produire une paire
    incohérente) — utilisée par ``deriver_semaines_constituantes``
    (Property 10) et ``construire_payroll_input`` (Property 11).
    """
    date_debut = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_fin = date_debut + timedelta(days=13)
    return date_debut, date_fin


# ===========================================================================
# Fixture pytest — chemins JSON temporaires (pas une stratégie Hypothesis)
# ===========================================================================


@pytest.fixture
def st_chemin_json_temporaire(tmp_path: Path) -> Callable[[str], Path]:
    """Fabrique de chemins JSON temporaires, un par annuaire (Req 19.3).

    Design (§Testing Strategy « Stratégies Hypothesis réutilisées et
    nouvelles », Injection systématique de chemins temporaires) : retourne
    une fonction ``fabrique(prefixe) -> Path`` qui fournit
    ``tmp_path / f"{prefixe}_{uuid4().hex}.json"`` — un chemin distinct à
    chaque appel, garantissant qu'aucun exemple Hypothesis ni aucun test
    ne réutilise accidentellement le fichier d'un autre (Properties 1, 2,
    3, 15 — annuaires employés et coordonnées, potentiellement les deux
    au sein d'un même test).

    **Ceci est une fixture pytest, pas une stratégie Hypothesis** (même
    convention que ``tests/strategies.py::st_chemin_bd_temporaire``) :
    elle est déclarée comme paramètre de fonction de test ordinaire,
    résolue automatiquement par pytest, jamais passée à ``@given(...)``.
    Le niveau d'indirection supplémentaire (fabrique plutôt que chemin
    unique) est nécessaire ici car deux annuaires distincts
    (``employees.json``, ``coordonnees.json``) peuvent être requis au
    sein d'un même test — contrairement à ``st_chemin_bd_temporaire`` qui
    ne sert qu'un seul registre SQLite.

    Règle 04 : jamais un chemin de production (`chemin_annuaire_employes_
    production()` / `chemin_annuaire_coordonnees_production()`) — toujours
    un chemin neuf sous ``tmp_path``, hors du dépôt versionné.
    """

    def _fabrique(prefixe: str) -> Path:
        return tmp_path / f"{prefixe}_{uuid.uuid4().hex}.json"

    return _fabrique
