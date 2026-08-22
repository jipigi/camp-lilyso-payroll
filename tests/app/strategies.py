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

Stratégies dédiées à la spec ``bilan-fiscal-employeur`` (design.md
§Testing Strategy « Stratégies Hypothesis nécessaires », tâche 1.1) :

- ``st_payroll_result_arbitraire(*, statut=None, date_paiement=None)`` —
  variante généralisée de la stratégie privée
  ``tests/strategies.py::_st_payroll_result_pour_registre``, acceptant
  un ``statut`` et une ``date_paiement`` arbitraires (fixes ou eux-mêmes
  des ``SearchStrategy``) au lieu de forcer ``EMISE`` et une période
  dérivée uniquement de ``annee_fiscale`` — nécessaire pour les
  Properties 1, 7, 8, 9, 11, 12, 13, 14 de cette spec, qui exigent de
  faire varier indépendamment le statut et le mois/année de
  ``pay_period.date_paiement``. **Réutilise directement, sans
  duplication**, les helpers internes déjà existants de
  ``tests/strategies.py`` (``_st_montant_registre``,
  ``_st_decimal_monetaire``, ``_st_employe_id``, ``_st_annee_fiscale``,
  ``_st_pay_period_deux_semaines``), importés au niveau module
  (aliasés en ``*_registre`` pour éviter toute collision avec les
  helpers homonymes déjà déclarés localement dans ce fichier, ex.
  ``_st_employe_id`` utilisé par ``st_employee_valide``).
- ``st_periode_fiscale()`` — génère une ``PeriodeFiscale`` arbitraire
  (``mois=None`` pour une Annee_Complete, ou ``mois`` ∈ ``[1, 12]`` pour
  un Mois_Fiscal), pour les Properties 4, 11. Import différé (règle 06,
  TDD) de ``app.logique_metier.bilan_fiscal.PeriodeFiscale`` — ce module
  n'existe pas encore (tâche 9.1 le crée) ; l'import est effectué **à
  l'intérieur** du corps de la stratégie pour que l'import de ce fichier
  de stratégies (et la collecte pytest des tests qui l'utilisent) ne
  lève pas ``ModuleNotFoundError`` avant que le module cible existe.
  L'appel effectif de cette stratégie continue de lever
  ``ModuleNotFoundError`` tant que la tâche 9.1 n'est pas faite —
  comportement attendu (règle 06).
- ``st_cellule_montant_ou_indisponible()`` — ``st.one_of(st.none(),
  _st_decimal_monetaire())`` (helper local de ce module), pour la
  Property 10 (``calculer_total``), testée en isolation sans passer par
  le pipeline complet.

Règle 01 (pour ces trois stratégies) : chaque cellule monétaire générée
reste un ``Decimal`` (jamais un ``float``) ; ``st_periode_fiscale`` ne
porte aucun champ ``Decimal`` (``PeriodeFiscale`` n'a que des champs
``int``/``int | None``) — la règle ne s'y applique donc pas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest
from hypothesis import strategies as st

from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import Juridiction, StatutDePaie
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    PayrollResult,
    RetenuesEmploye,
)
from tests.strategies import (
    _st_annee_fiscale,
    _st_decimal_monetaire as _st_decimal_monetaire_registre,
    _st_employe_id as _st_employe_id_registre,
    _st_montant_registre,
    _st_pay_period_deux_semaines,
)

__all__ = [
    "st_employee_valide",
    "st_fiche_coordonnees_valide",
    "st_dates_periode_valide",
    "st_chemin_json_temporaire",
    "st_payroll_result_arbitraire",
    "st_periode_fiscale",
    "st_cellule_montant_ou_indisponible",
    "st_ligne_paie_resume_arbitraire",
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


# ===========================================================================
# Stratégies dédiées à la spec ``bilan-fiscal-employeur``
# (design.md §Testing Strategy « Stratégies Hypothesis nécessaires »,
#  tâche 1.1)
# ===========================================================================


def _tirer_valeur_ou_strategie(
    draw: st.DrawFn,
    valeur: object,
    strategie_defaut: "st.SearchStrategy[object]",
) -> object:
    """Résout un paramètre optionnel ``valeur: T | SearchStrategy[T] | None``.

    Helper interne partagé par ``st_payroll_result_arbitraire`` pour les
    deux paramètres ``statut`` et ``date_paiement`` (design §Testing
    Strategy « Stratégies Hypothesis nécessaires ») :

    - ``valeur is None`` → tire un exemple depuis ``strategie_defaut``
      (l'appelant n'a exprimé aucune contrainte, la valeur varie
      librement) ;
    - ``valeur`` est déjà une ``SearchStrategy`` → tire un exemple depuis
      cette stratégie fournie par l'appelant (contrainte partielle,
      ex. ``st.sampled_from([...])``) ;
    - sinon (valeur concrète, ex. ``StatutDePaie.EMISE`` ou une
      ``date`` précise) → retournée telle quelle (contrainte totale,
      aucun tirage).
    """
    if valeur is None:
        return draw(strategie_defaut)
    if isinstance(valeur, st.SearchStrategy):
        return draw(valeur)
    return valeur


@st.composite
def st_payroll_result_arbitraire(
    draw: st.DrawFn,
    *,
    statut: "StatutDePaie | st.SearchStrategy[StatutDePaie] | None" = None,
    date_paiement: "date | st.SearchStrategy[date] | None" = None,
) -> PayrollResult:
    """``PayrollResult`` arbitraire, statut et ``date_paiement`` libres.

    Design (§Testing Strategy « Stratégies Hypothesis nécessaires ») :
    variante généralisée de la stratégie privée
    ``tests/strategies.py::_st_payroll_result_pour_registre`` (spec
    ``net-cumuls-registre``), qui forçait ``statut=StatutDePaie.EMISE``
    et laissait ``pay_period.date_paiement`` dériver uniquement du
    tirage interne de ``_st_pay_period_deux_semaines``. Cette variante
    accepte en plus :

    - ``statut`` : une valeur fixe :class:`~models.enums.StatutDePaie`,
      une ``SearchStrategy[StatutDePaie]`` (ex.
      ``st.sampled_from([StatutDePaie.BROUILLON, StatutDePaie.ANNULEE])``),
      ou ``None`` pour un tirage libre parmi les quatre statuts
      (:func:`_tirer_valeur_ou_strategie`) ;
    - ``date_paiement`` : une ``date`` fixe, une
      ``SearchStrategy[date]``, ou ``None`` pour un tirage libre — permet
      de faire varier indépendamment le mois/année de rattachement
      (décision n° 1 des requirements : dérivé exclusivement de
      ``PayPeriod.date_paiement``, jamais de ``annee_fiscale``).

    Nécessaire pour les Properties 1, 7, 8, 9, 11, 12, 13, 14 de la spec
    ``bilan-fiscal-employeur``, qui exigent de faire varier
    indépendamment le statut d'une paie et le mois/année de
    ``pay_period.date_paiement``, ce que l'ancienne stratégie ne
    permettait pas (statut et période toujours fixés à ``EMISE`` /
    dérivés de ``annee_fiscale``).

    **Réutilisation directe, sans duplication** (design §Testing
    Strategy) : les montants de ``RetenuesEmploye``/``CotisationsEmployeur``
    et le drapeau ``cnesst_en_attente_classification`` sont générés en
    réutilisant **tels quels** les helpers internes déjà existants de
    ``tests/strategies.py`` — ``_st_montant_registre`` (construit chaque
    ``MontantAvecTrace``) et ``_st_decimal_monetaire`` (borne chaque
    montant à deux décimales, règle 01) — importés localement ci-dessous
    plutôt que réimplémentés. ``_st_employe_id``, ``_st_annee_fiscale``
    et ``_st_pay_period_deux_semaines`` sont réutilisés de la même
    façon pour la structure ``PayPeriod`` (le champ ``date_paiement``
    obtenu est ensuite remplacé via ``model_copy`` par la valeur résolue
    de ce paramètre — ``PayPeriod`` n'impose aucun invariant croisé sur
    ``date_paiement``, voir ``models/pay_period.py``).

    La biconditionnelle ``statut`` ⟺ ``remplace_par_id`` ⟺
    ``date_emission`` (Req 6.3-6.5, 6.7 de ``moteur-paie-contrats``) est
    satisfaite par construction : ``remplace_par_id`` n'est renseigné
    que pour ``StatutDePaie.REMPLACE_PAR`` ; ``date_emission`` est
    toujours renseignée (autorisé pour les quatre statuts, requis pour
    trois d'entre eux — Req 6.7).

    Règle 01 : chaque montant reste un ``Decimal`` (jamais un ``float``).
    """
    employe_id = draw(_st_employe_id_registre())
    annee_fiscale = draw(_st_annee_fiscale())

    statut_resolu = _tirer_valeur_ou_strategie(
        draw, statut, st.sampled_from(list(StatutDePaie))
    )
    date_paiement_resolue = _tirer_valeur_ou_strategie(
        draw,
        date_paiement,
        st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX),
    )

    pay_period = draw(_st_pay_period_deux_semaines(annee_fiscale=annee_fiscale))
    pay_period = pay_period.model_copy(
        update={"date_paiement": date_paiement_resolue}
    )

    rrq = draw(_st_decimal_monetaire_registre(max_value=Decimal("500.00")))
    rqap = draw(_st_decimal_monetaire_registre(max_value=Decimal("100.00")))
    ae = draw(_st_decimal_monetaire_registre(max_value=Decimal("200.00")))
    impot_qc_retenu = draw(
        _st_decimal_monetaire_registre(max_value=Decimal("1000.00"))
    )
    impot_federal_retenu = draw(
        _st_decimal_monetaire_registre(max_value=Decimal("1000.00"))
    )
    impot_qc_formule = draw(
        _st_decimal_monetaire_registre(max_value=Decimal("1000.00"))
    )
    impot_federal_formule = draw(
        _st_decimal_monetaire_registre(max_value=Decimal("1000.00"))
    )
    total_retenues = rrq + rqap + ae + impot_qc_retenu + impot_federal_retenu

    retenues_employe = RetenuesEmploye(
        rrq=_st_montant_registre(rrq),
        rqap=_st_montant_registre(rqap),
        ae=_st_montant_registre(ae),
        impot_qc_formule=_st_montant_registre(impot_qc_formule),
        impot_qc_retenu=_st_montant_registre(impot_qc_retenu),
        impot_federal_formule=_st_montant_registre(impot_federal_formule),
        impot_federal_retenu=_st_montant_registre(impot_federal_retenu),
        total_retenues_employe=total_retenues,
    )

    rrq_er = draw(_st_decimal_monetaire_registre(max_value=Decimal("500.00")))
    rqap_er = draw(_st_decimal_monetaire_registre(max_value=Decimal("100.00")))
    ae_er = draw(_st_decimal_monetaire_registre(max_value=Decimal("300.00")))
    fss = draw(_st_decimal_monetaire_registre(max_value=Decimal("200.00")))
    cnesst = draw(_st_decimal_monetaire_registre(max_value=Decimal("200.00")))
    cnt = draw(_st_decimal_monetaire_registre(max_value=Decimal("50.00")))
    total_cotisations = rrq_er + rqap_er + ae_er + fss + cnesst + cnt

    cotisations_employeur = CotisationsEmployeur(
        rrq_employeur=_st_montant_registre(rrq_er),
        rqap_employeur=_st_montant_registre(rqap_er),
        ae_employeur=_st_montant_registre(ae_er),
        fss=_st_montant_registre(fss),
        cnesst=_st_montant_registre(cnesst),
        cnesst_en_attente_classification=draw(st.booleans()),
        cnt=_st_montant_registre(cnt),
        total_cotisations_employeur=total_cotisations,
    )

    # ``brut_total`` doit couvrir les cinq retenues effectivement retenues
    # (sinon ``net = brut_total - total_retenues < 0``, refusé par
    # ``ge=0``) — même patron que ``_st_payroll_result_pour_registre``.
    marge_net = draw(_st_decimal_monetaire_registre(max_value=Decimal("2000.00")))
    brut_total = total_retenues + marge_net
    gains = GainsDecomposes(
        salaire_regulier=brut_total,
        heures_supplementaires_montant=Decimal("0.00"),
        vacances=Decimal("0.00"),
        jours_feries_manuels=Decimal("0.00"),
        brut_total=brut_total,
        multiplicateur_heures_supp=Decimal("1.5"),
        seuil_heures_supp_hebdo=Decimal("40"),
    )

    net = brut_total - total_retenues
    cout_employeur = brut_total + total_cotisations

    # Suffixe tiré d'un espace large (``uuid.uuid4().hex``, même convention
    # que ``st_chemin_json_temporaire`` ci-dessus) plutôt qu'un entier
    # ``[1, 999]`` : ce dernier collisionnait trop facilement, à la fois
    # entre éléments d'une même liste générée (plusieurs `PayrollResult`
    # insérés dans le même registre SQLite append-only) et entre essais
    # Hypothesis successifs réutilisant le même fichier de base temporaire
    # (``st_chemin_bd_temporaire``, `HealthCheck.function_scoped_fixture`
    # explicitement suppressed — voir ``tests/conftest.py``), provoquant un
    # ``sqlite3.IntegrityError: UNIQUE constraint failed: paies.id_paie``
    # sans rapport avec la logique testée.
    id_paie = f"PAIE-{employe_id}-{annee_fiscale}-{uuid.uuid4().hex}"

    # Biconditionnelle statut ⟺ remplace_par_id ⟺ date_emission
    # (Req 6.3-6.5, 6.7 de ``moteur-paie-contrats``) — satisfaite par
    # construction, voir docstring ci-dessus.
    remplace_par_id = (
        f"{id_paie}-REMPLACANTE"
        if statut_resolu is StatutDePaie.REMPLACE_PAR
        else None
    )

    return PayrollResult(
        id_paie=id_paie,
        version=1,
        employe_id=employe_id,
        annee_fiscale=annee_fiscale,
        pay_period=pay_period,
        gains=gains,
        retenues_employe=retenues_employe,
        cotisations_employeur=cotisations_employeur,
        net=net,
        cout_employeur=cout_employeur,
        cumuls_fin=CumulsYTD.zero(employe_id=employe_id, annee_civile=annee_fiscale),
        statut=statut_resolu,
        remplace_par_id=remplace_par_id,
        date_creation=datetime(2026, 6, 19, 12, 0, 0),
        date_emission=datetime(2026, 6, 20, 12, 0, 0),
    )


@st.composite
def st_periode_fiscale(draw: st.DrawFn) -> "PeriodeFiscale":  # noqa: F821
    """``PeriodeFiscale`` arbitraire — Mois_Fiscal ou Annee_Complete.

    Design (§Testing Strategy « Stratégies Hypothesis nécessaires ») :
    tire une ``annee`` arbitraire puis ``mois`` soit ``None``
    (Annee_Complete) soit un entier ∈ ``[1, 12]`` (Mois_Fiscal), pour les
    Properties 4 (présélection par défaut) et 11 (filtrage exact par
    Periode_Fiscale).

    Import différé de :class:`~app.logique_metier.bilan_fiscal.PeriodeFiscale`
    (règle 06, TDD) : ce module n'existe pas encore (tâche 9.1 le crée).
    L'import est effectué **à l'intérieur** du corps de cette stratégie
    pour que l'import de ``tests.app.strategies`` (et la collecte pytest
    des tests qui l'utilisent) ne lève pas ``ModuleNotFoundError`` avant
    que le module cible existe. L'appel effectif de cette stratégie
    continue de lever ``ModuleNotFoundError`` tant que la tâche 9.1
    n'est pas faite — comportement attendu et correct au titre de la
    règle 06.
    """
    from app.logique_metier.bilan_fiscal import PeriodeFiscale

    annee = draw(st.integers(min_value=2020, max_value=2035))
    mois = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=12)))
    return PeriodeFiscale(annee=annee, mois=mois)


def st_cellule_montant_ou_indisponible() -> st.SearchStrategy[Decimal | None]:
    """``Decimal | None`` — une cellule de total, disponible ou non.

    Design (§Testing Strategy « Stratégies Hypothesis nécessaires ») :
    ``st.one_of(st.none(), _st_decimal_monetaire())`` (helper local de
    ce module) pour la Property 10 (``calculer_total``), testée en
    isolation sans passer par le pipeline complet — ``None`` représente
    l'indicateur d'indisponibilité (Requirements 7.3, 9.4), une valeur
    ``Decimal`` représente un montant agrégé disponible. La borne
    supérieure (``1 000 000.00``) couvre largement l'ordre de grandeur
    d'un total de Tableau_Bilan_Fiscal (agrégation de plusieurs
    employés sur une Annee_Complete), sans signification métier propre.
    """
    return st.one_of(
        st.none(),
        _st_decimal_monetaire(max_value=Decimal("1000000.00")),
    )


# ===========================================================================
# Stratégies dédiées à la spec ``tableau-de-bord-periode-globale``
# (design.md §Testing Strategy « Stratégies Hypothesis nécessaires »,
#  tâche 2.2)
# ===========================================================================


#: Statuts admis par `paies_pour_colonne` (BROUILLON, EMISE) — réutilisés
#: tels quels par `st_ligne_paie_resume_arbitraire` ci-dessous.
_STATUTS_COLONNE_PAIES_TEST = ("brouillon", "emise")

#: Statuts hors périmètre de la Colonne_Paies (ANNULEE, REMPLACE_PAR) —
#: générés délibérément par `st_ligne_paie_resume_arbitraire` (Property
#: 6) pour vérifier que `paies_pour_colonne` les exclut bien du résultat.
_STATUTS_HORS_COLONNE_PAIES_TEST = ("annulee", "remplace_par")


def _st_date_paiement_iso_ou_none() -> st.SearchStrategy[str | None]:
    """Chaîne ISO de date de paiement arbitraire, ou `None`.

    Design (§Testing Strategy « Stratégies Hypothesis nécessaires »,
    tâche 2.2) : `LignePaieResume.date_paiement` est une chaîne ISO
    simple (`date.isoformat()`), jamais un `datetime` — cette stratégie
    tire une `date` arbitraire (bornée à `_DATE_MIN`/`_DATE_MAX`, mêmes
    bornes que le reste de ce module) puis la sérialise. Inclut `None`
    (cas défensif de `LignePaieResume`, voir docstring du modèle dans
    `dernieres_paies.py`) pour vérifier que `paies_pour_colonne` exclut
    bien ces résumés du résultat plutôt que de lever une exception.
    """
    return st.one_of(
        st.none(),
        st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX).map(date.isoformat),
    )


@st.composite
def st_ligne_paie_resume_arbitraire(draw: st.DrawFn) -> "LignePaieResume":  # noqa: F821
    """``LignePaieResume`` arbitraire — statut, date de paiement et
    ``numero_periode`` libres (Property 6).

    Design (§Testing Strategy « Stratégies Hypothesis nécessaires »,
    tâche 2.2) : cette stratégie exerce délibérément **tous** les
    statuts de :class:`~models.enums.StatutDePaie` (``BROUILLON``,
    ``EMISE``, mais aussi ``ANNULEE``/``REMPLACE_PAR`` hors périmètre de
    la Colonne_Paies) ainsi que ``date_paiement=None`` (cas défensif),
    pour que la Property 6 (`app/logique_metier/dernieres_paies.py::
    paies_pour_colonne`) puisse vérifier à la fois le filtrage (statut
    hors `{BROUILLON, EMISE}` ou `date_paiement` absente/hors année →
    exclu) et l'ordre (BROUILLON avant EMISE, puis date de paiement
    décroissante, puis `numero_periode` croissant en cas d'égalité).

    `id_paie`, `version`, `net`, `saison`, `annee_fiscale`,
    `date_creation`, `date_emission` sont des valeurs fictives simples
    sans rapport avec cette property (non exercées par
    `paies_pour_colonne`) — même patron que `_st_champs_ligne_paie_
    resume` de `tests/app/logique_metier/test_dernieres_paies.py`, dont
    cette stratégie est la version réutilisable/exportée pour la tâche
    2.2 (Property 6).

    Import différé de :class:`LignePaieResume` (règle 06, TDD) : ce
    modèle est défini par `app/logique_metier/dernieres_paies.py`,
    importé ici **à l'intérieur** du corps de la stratégie pour rester
    cohérent avec les autres stratégies à import différé de ce module.

    Règle 01 : `net` reste une chaîne (`str`), jamais un `float`.
    """
    from app.logique_metier.dernieres_paies import LignePaieResume

    statut = draw(
        st.sampled_from(
            _STATUTS_COLONNE_PAIES_TEST + _STATUTS_HORS_COLONNE_PAIES_TEST
        )
    )
    numero_periode = draw(st.integers(min_value=1, max_value=27))
    date_paiement = draw(_st_date_paiement_iso_ou_none())

    return LignePaieResume(
        id_paie=f"PAIE-TEST-{draw(st.integers(min_value=0, max_value=999_999))}",
        numero_periode=numero_periode,
        version=draw(st.integers(min_value=1, max_value=5)),
        statut=statut,
        net=str(draw(st.integers(min_value=0, max_value=100_000))),
        saison="Été 2026",
        annee_fiscale=draw(st.integers(min_value=2020, max_value=2035)),
        date_creation="2026-01-01T00:00:00",
        date_emission=None,
        date_paiement=date_paiement,
    )


# ---------------------------------------------------------------------------
# Property 9 — Validation de la date de paiement à l'émission
# (design.md §Testing Strategy « Stratégies Hypothesis nécessaires »,
#  tâche 6.2)
# ---------------------------------------------------------------------------


@st.composite
def st_dates_fin_et_paiement_arbitraire(
    draw: st.DrawFn,
) -> tuple[date, date | None]:
    """Paire `(date_fin, date_paiement)` arbitraire, `date_paiement`
    incluant `None` (Property 9).

    Design (§Testing Strategy « Stratégies Hypothesis nécessaires »,
    tâche 6.2) : contrairement à `st_dates_periode_valide()` (couple
    contigu `date_debut`/`date_fin` d'une même `PayPeriod`), cette
    stratégie tire deux dates totalement indépendantes — `date_fin`
    (toujours une `date`) et `date_paiement` (`date` ou `None`, cas
    d'absence de saisie) — pour couvrir tous les cas exercés par
    `valider_date_paiement_pour_emission` : `date_paiement` absente,
    strictement antérieure à `date_fin`, égale à `date_fin`, ou
    strictement postérieure. Mêmes bornes (`_DATE_MIN`/`_DATE_MAX`) que
    le reste de ce module.
    """
    date_fin = draw(st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX))
    date_paiement = draw(
        st.one_of(
            st.none(),
            st.dates(min_value=_DATE_MIN, max_value=_DATE_MAX),
        )
    )
    return date_fin, date_paiement
