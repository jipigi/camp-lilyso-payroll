"""Tests unitaires et property tests de `app/pages_ui/tableau_de_bord.py`.

Spec de référence : ``tableau-de-bord-periode-globale`` — tâches 8.4,
8.5, 8.7, 8.9.
Design de référence : ``design.md`` Décision 5 (isolation de la
construction du Tableau_Bilan_Fiscal, Requirement 2.3) ; §Components §5
(`_construire_html_liste_employes`) ; §Correctness Properties,
Properties 3 et 4.

Ce module contient :

- le property test de la Property 3 (tâche 8.4) : la colonne
  « No. d'employé » est absente du tableau rendu, les autres en-têtes
  restent inchangés ;
- le property test de la Property 4 (tâche 8.5) : l'identifiant employé
  n'est jamais affiché comme texte visible du tableau des employés,
  tout en continuant d'alimenter au moins un attribut `href`, y compris
  pour des identifiants contenant des caractères spéciaux d'URL ;
- le test unitaire du renommage de colonne (tâche 8.7) : l'en-tête
  affiché est « Paies », jamais « Dernière paie » ;
- le test unitaire d'isolation d'erreur de `_afficher_bilan_fiscal`
  (tâche 8.9) : simule une exception levée pendant la
  construction/génération HTML du Tableau_Bilan_Fiscal et vérifie
  qu'elle ne se propage jamais hors de `_afficher_bilan_fiscal`
  (condition nécessaire et suffisante pour que le reste de `render()` —
  dont la section « Employés », toujours rendue avant, cf. design.md
  Décision 2 — ne soit jamais interrompu).

``streamlit`` (importé sous l'alias ``st`` dans `tableau_de_bord.py`)
est mocké via `unittest.mock.patch("app.pages_ui.tableau_de_bord.st")`
puisqu'aucun contexte d'exécution Streamlit réel n'est disponible en
test (même patron que les tests de garde `tests/app/test_guards.py`,
qui vérifient justement l'absence d'import ``streamlit`` en dehors de
la couche de rendu). Les tests des Properties 3 et 4 et du renommage de
colonne exercent quant à eux directement `_construire_html_liste_employes`,
une fonction pure sans dépendance à `streamlit`/aux lectures disque
(cf. docstring du module sous test) — aucun mock n'y est nécessaire.

Règle 04 : les identifiants et noms employé générés ci-dessous
(fictifs, `EMPnnn` ou combinant lettres/chiffres et caractères spéciaux
d'URL) ne sont jamais des données personnelles réelles.
"""

from __future__ import annotations

import re
import string
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.logique_metier.bilan_fiscal import PeriodeFiscale
from app.logique_metier.erreurs import ErreurDomaineAffichable
from app.pages_ui.tableau_de_bord import (
    _afficher_bilan_fiscal,
    _construire_html_liste_employes,
    _contenu_colonne_paies_html,
    _formater_date_sans_annee,
    _ligne_colonne_paie_html,
)
from app.logique_metier.dernieres_paies import paies_pour_colonne
from models.employee import Employee
from models.enums import Juridiction
from tests.app.strategies import st_employee_valide, st_ligne_paie_resume_arbitraire


def _construire_employe(employe_id: str, nom_affichage: str) -> Employee:
    """`Employee` valide minimal pour un test d'exemple (Req 04 — id/nom
    fictifs, jamais de donnée personnelle réelle). Même patron que
    `tests/app/logique_metier/test_tri_employes.py::_construire_employe`.
    """
    return Employee(
        id=employe_id,
        nom_affichage=nom_affichage,
        date_naissance=date(2000, 1, 1),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Monitrice",
        taux_horaire_base=Decimal("20.00"),
        date_embauche=date(2024, 6, 1),
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("0.00"),
        montant_total_TD1=Decimal("0.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# Test unitaire du renommage de colonne (tâche 8.7)
# ---------------------------------------------------------------------------
#
# _Requirements: 5.1_
#
# Un seul exemple concret (pas Hypothesis, non universel) — vérifie que
# l'en-tête affiché par `_construire_html_liste_employes` est bien
# « Paies » et non plus l'ancien libellé « Dernière paie ».


class TestRenommageColonnePaies:
    """Renommage de l'en-tête « Dernière paie » en « Paies » (Req 5.1)."""

    def test_entete_affichee_est_paies_et_non_derniere_paie(self) -> None:
        """`_construire_html_liste_employes` affiche `<th>Paies</th>`
        et jamais `<th>Dernière paie</th>` (Req 5.1)."""
        employe_un = _construire_employe("EMP001", "Camille Tremblay")
        employe_deux = _construire_employe("EMP002", "Alex Roy")
        contenu_colonne_paies_par_employe = {
            "EMP001": "Aucune paie pour cette année.",
            "EMP002": "Aucune paie pour cette année.",
        }

        html_tableau = _construire_html_liste_employes(
            (employe_un, employe_deux), contenu_colonne_paies_par_employe
        )

        assert "<th>Paies</th>" in html_tableau, (
            "l'en-tête de la Colonne_Paies doit être « Paies » ; "
            f"obtenu {html_tableau!r}."
        )
        assert "<th>Dernière paie</th>" not in html_tableau, (
            "l'ancien libellé « Dernière paie » ne doit plus apparaître "
            f"dans le tableau ; obtenu {html_tableau!r}."
        )


# ---------------------------------------------------------------------------
# Property 3 — Colonne « No. d'employé » absente, colonnes restantes
# inchangées (design.md §Correctness Properties, Property 3 ; tâche 8.4)
# ---------------------------------------------------------------------------
#
# Feature: tableau-de-bord-periode-globale, Property 3: Colonne « No. d'employé » absente, colonnes restantes inchangées
#
# *Pour tout* tuple non vide d'employés (identifiants et noms
# arbitraires), le HTML produit par le rendu du tableau des employés ne
# contient jamais `<th>No. d'employé</th>` ni de cellule
# `<td>{employe.id}</td>` répétée par ligne, et l'ensemble ordonné des
# autres en-têtes de colonnes (« Prénom et nom », « Paies », « Actions »)
# reste inchangé.
#
# Validates: Requirements 3.1
# ---------------------------------------------------------------------------


settings_liste_employes = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@given(employes=st.lists(st_employee_valide(), min_size=1, max_size=8, unique_by=lambda e: e.id))
@settings_liste_employes
def test_property_3_colonne_no_employe_absente(
    employes: list[Employee],
) -> None:
    """Pour tout tuple non vide d'employés, le HTML produit ne contient
    jamais `<th>No. d'employé</th>` ni de cellule `<td>{employe.id}</td>`
    isolée, et les en-têtes restants sont exactement, dans l'ordre :
    « Prénom et nom », « Paies », « Actions »."""
    contenu_colonne_paies_par_employe = {
        employe.id: "Aucune paie pour cette année." for employe in employes
    }

    tableau_html = _construire_html_liste_employes(
        tuple(employes), contenu_colonne_paies_par_employe
    )

    assert "<th>No. d'employé</th>" not in tableau_html, (
        "la colonne « No. d'employé » ne doit plus apparaître dans le "
        f"tableau ; obtenu {tableau_html!r}."
    )
    for employe in employes:
        assert f"<td>{employe.id}</td>" not in tableau_html, (
            f"aucune cellule isolée <td>{employe.id}</td> ne doit "
            f"apparaître ; obtenu {tableau_html!r}."
        )

    entetes = re.findall(r"<th>([^<]*)</th>", tableau_html)
    assert entetes == ["Prénom et nom", "Paies", "Actions"], (
        "les en-têtes restants doivent être exactement, dans l'ordre, "
        f"['Prénom et nom', 'Paies', 'Actions'] ; obtenu {entetes!r}."
    )


class TestIsolationErreurTableauBilanFiscal:
    """Isolation de l'erreur de construction du Tableau_Bilan_Fiscal (Req 2.3)."""

    def test_exception_construction_tableau_naffiche_pas_lexception_mais_st_error(
        self,
    ) -> None:
        """Une exception levée par `construire_tableau_bilan_fiscal` est
        capturée par le `executer_avec_capture(lambda: ...)` unique de
        `_afficher_bilan_fiscal` (design.md Décision 5) : `st.error(...)`
        est appelé à la place du tableau, et aucune exception ne se
        propage hors de `_afficher_bilan_fiscal` — condition nécessaire
        et suffisante pour que le reste de `render()` (dont la section
        Employés, déjà rendue avant) ne soit jamais interrompu."""
        with patch(
            "app.pages_ui.tableau_de_bord.construire_tableau_bilan_fiscal",
            side_effect=ValueError("échec simulé de construction du tableau"),
        ), patch("app.pages_ui.tableau_de_bord.st") as st_mock:
            _afficher_bilan_fiscal(
                paies_emises=(),
                periode_selectionnee=PeriodeFiscale(annee=2026, mois=None),
            )

        st_mock.error.assert_called_once()
        message_affiche = st_mock.error.call_args[0][0]
        assert "ValueError" in message_affiche
        assert "échec simulé de construction du tableau" in message_affiche
        st_mock.markdown.assert_not_called()


# ---------------------------------------------------------------------------
# Property 4 — Identifiant employé jamais affiché comme texte visible
# (design.md §Correctness Properties, Property 4 ; tâche 8.5)
# ---------------------------------------------------------------------------
#
# Feature: tableau-de-bord-periode-globale, Property 4: Identifiant employé jamais affiché comme texte visible
#
# *Pour tout* employé (identifiant arbitraire, y compris des valeurs
# contenant des caractères spéciaux d'URL), le texte visible du tableau
# rendu (contenu hors des balises et des attributs HTML) ne contient
# jamais `employe.id`, alors que ce même identifiant continue
# d'apparaître dans au moins un attribut `href`.
#
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------


#: Alphabet incluant des caractères spéciaux d'URL (espace, `&`, `?`,
#: `#`, `/`, `%`, `=`, `+`) en plus de lettres/chiffres ASCII — `st_
#: employee_valide()` contraint `id` à la forme fictive `EMPnnn` (règle
#: 04), trop stricte pour exercer cette property : `employe.id` doit ici
#: pouvoir contenir n'importe quel caractère spécial d'URL, encodé par
#: `urllib.parse.quote` avant d'alimenter un attribut `href` (voir
#: `_construire_html_liste_employes`, `_lien_action_employe`).
_ALPHABET_ID_CARACTERES_SPECIAUX_URL = string.ascii_letters + string.digits + " &?#/%=+"


def _construire_employe_id_arbitraire(employe_id: str) -> Employee:
    """`Employee` valide minimal dont l'`id` est fourni tel quel (Property
    4 — jamais la forme fictive `EMPnnn` imposée par `st_employee_valide`,
    voir alphabet ci-dessus). Tous les autres champs sont des valeurs
    passe-partout dans le périmètre Camp LilySO (règle 04 — aucune
    donnée personnelle réelle), seul `id` varie d'un appel à l'autre."""
    return Employee(
        id=employe_id,
        nom_affichage="Employe Test",
        date_naissance=date(2000, 1, 1),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Monitrice",
        taux_horaire_base=Decimal("20.00"),
        date_embauche=date(2024, 6, 1),
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("0.00"),
        montant_total_TD1=Decimal("0.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )


#: Texte de remplissage fixe (`nom_affichage`, action « Ajouter une
#: paie », contenu factice de la Colonne_Paies) injecté par
#: `_construire_employe_id_arbitraire`/le test ci-dessous dans chaque
#: ligne du tableau, en plus de `employe.id` — un `id` trop court/générique
#: (ex. `"i"`) peut coïncidentiellement apparaître comme sous-chaîne de ce
#: remplissage (ex. `"i"` dans `"Ajouter"`), un faux positif de la
#: property sans rapport avec le comportement réel de
#: `_construire_html_liste_employes` (qui n'affiche jamais `employe.id`
#: comme texte visible). Filtré ci-dessous.
_TEXTE_REMPLISSAGE_LIGNE = "Employe TestContenu paies facticeAjouter une paie"


def _st_employe_id_arbitraire() -> "st.SearchStrategy[str]":
    """Chaîne arbitraire de `_ALPHABET_ID_CARACTERES_SPECIAUX_URL`, sans
    espace de bord — `Employee` (`str_strip_whitespace=True`) retirerait
    silencieusement tout espace de début/fin, ce qui romprait l'égalité
    attendue entre la chaîne tirée et `employe.id` une fois l'instance
    construite (voire produirait un `id` vide, rejeté par
    `min_length=1`, si la chaîne tirée n'était composée que d'espaces).

    Exclut aussi toute valeur qui serait une sous-chaîne du texte de
    remplissage fixe des autres cellules de la ligne (`_TEXTE_
    REMPLISSAGE_LIGNE`) — sans quoi un `id` court/générique produirait un
    faux positif de la property (voir docstring de cette constante).
    """
    return st.text(
        alphabet=_ALPHABET_ID_CARACTERES_SPECIAUX_URL,
        min_size=2,
        max_size=12,
    ).filter(
        lambda s: s.strip() == s
        and s != ""
        and s not in _TEXTE_REMPLISSAGE_LIGNE
    )


@st.composite
def _st_employes_id_arbitraire(
    draw: st.DrawFn, max_size: int = 6
) -> "tuple[Employee, ...]":
    """1 à `max_size` `Employee`, `id` arbitraires (incluant des
    caractères spéciaux d'URL), uniques entre eux au sein d'un même
    tuple — évite qu'un `id` ne soit accidentellement absent du
    dictionnaire `contenu_colonne_paies_par_employe` (clé requise par
    `_construire_html_liste_employes` pour chaque employé)."""
    ids = draw(
        st.lists(
            _st_employe_id_arbitraire(),
            min_size=1,
            max_size=max_size,
            unique=True,
        )
    )
    return tuple(_construire_employe_id_arbitraire(employe_id) for employe_id in ids)


def _texte_visible(html_brut: str) -> str:
    """Texte visible d'un bloc HTML — retire toutes les balises (motif
    simple `<[^>]+>`, suffisant pour le HTML sémantique généré par
    `_construire_html_liste_employes`, sans attribut contenant `<`/`>`)
    ainsi que leurs attributs (compris dans la balise retirée)."""
    return re.sub(r"<[^>]+>", "", html_brut)


settings_id_arbitraire = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@given(employes=_st_employes_id_arbitraire())
@settings_id_arbitraire
def test_property_4_identifiant_employe_jamais_affiche_comme_texte_visible(
    employes: "tuple[Employee, ...]",
) -> None:
    """Pour tout employé d'identifiant arbitraire (y compris des valeurs
    contenant des caractères spéciaux d'URL), le texte visible du
    tableau rendu ne contient jamais `employe.id`, alors que ce même
    identifiant continue d'apparaître dans au moins un attribut `href`
    du HTML brut.
    """
    contenu_colonne_paies_par_employe = {
        employe.id: "Contenu paies factice" for employe in employes
    }

    tableau_html = _construire_html_liste_employes(
        employes, contenu_colonne_paies_par_employe
    )

    texte_visible = _texte_visible(tableau_html)

    for employe in employes:
        # 1. Jamais affiché comme texte visible (hors balises/attributs).
        assert employe.id not in texte_visible, (
            f"l'identifiant {employe.id!r} ne doit jamais apparaître "
            f"dans le texte visible du tableau ; texte visible obtenu : "
            f"{texte_visible!r}."
        )

        # 2. Continue d'apparaître dans au moins un attribut `href`
        # (encodé via `urllib.parse.quote`, même fonction que le code
        # sous test).
        href_attendu = f'href="/fiche-employe?employe_id={quote(employe.id)}"'
        assert href_attendu in tableau_html, (
            f"l'identifiant {employe.id!r} (encodé : {quote(employe.id)!r}) "
            "doit apparaître dans au moins un attribut `href` du tableau ; "
            f"HTML obtenu : {tableau_html!r}."
        )


# ---------------------------------------------------------------------------
# Property 8 — Isolation des erreurs de lecture par employé
# (design.md §Correctness Properties, Property 8 ; tâche 8.6)
# ---------------------------------------------------------------------------
#
# Feature: tableau-de-bord-periode-globale, Property 8: Isolation des erreurs de lecture par employé
#
# *Pour tout* tuple d'employés et *tout* sous-ensemble arbitraire d'entre
# eux dont la lecture des résumés de paie échoue (simulée par mock), les
# employés dont la lecture réussit affichent toujours leur contenu normal
# de Colonne_Paies, indépendamment des échecs des autres lignes.
#
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


#: Contenu fixe simulant l'échec de `executer_avec_capture(lambda:
#: lire_resumes_paies(employe.id))` — même forme que la véritable
#: `ErreurDomaineAffichable` produite par `app/logique_metier/erreurs.py`.
#: Fixe (plutôt que tiré arbitrairement) pour que la vérification « le
#: contenu d'un employé qui réussit ne contient jamais ce texte » ne
#: dépende d'aucune coïncidence entre un texte d'erreur tiré au hasard et
#: le contenu normal (statuts/dates) produit pour les employés dont la
#: lecture réussit.
_TYPE_EXCEPTION_SIMULEE = "ValueError"
_MESSAGE_EXCEPTION_SIMULEE = "échec simulé de lire_resumes_paies pour cet employé"


@st.composite
def _st_ligne_employe_avec_echec_isole(
    draw: st.DrawFn,
) -> "tuple[Employee, tuple[object, ...] | ErreurDomaineAffichable]":
    """Un employé (`st_employee_valide`) associé soit à un tuple de
    `LignePaieResume` (lecture réussie, 0 à 3 résumés), soit à
    l'`ErreurDomaineAffichable` fixe ci-dessus (lecture échouée) —
    simule le retour de `executer_avec_capture(lambda:
    lire_resumes_paies(employe.id))` pour cet employé, indépendamment de
    tout autre employé du tuple généré par le test."""
    employe = draw(st_employee_valide())
    echec = draw(st.booleans())
    if echec:
        resultat: "tuple[object, ...] | ErreurDomaineAffichable" = (
            ErreurDomaineAffichable(
                type_exception=_TYPE_EXCEPTION_SIMULEE,
                message=_MESSAGE_EXCEPTION_SIMULEE,
            )
        )
    else:
        resumes = draw(
            st.lists(st_ligne_paie_resume_arbitraire(), min_size=0, max_size=3)
        )
        resultat = tuple(resumes)
    return employe, resultat


settings_isolation_erreurs = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@given(
    lignes=st.lists(
        _st_ligne_employe_avec_echec_isole(),
        min_size=1,
        max_size=8,
        unique_by=lambda ligne: ligne[0].id,
    ),
    annee_selectionnee=st.integers(min_value=2020, max_value=2035),
)
@settings_isolation_erreurs
def test_property_8_isolation_erreurs_lecture_par_employe(
    lignes: "list[tuple[Employee, tuple[object, ...] | ErreurDomaineAffichable]]",
    annee_selectionnee: int,
) -> None:
    """Pour tout tuple d'employés et tout sous-ensemble arbitraire
    d'entre eux dont la lecture des résumés de paie échoue (simulée),
    les employés dont la lecture réussit affichent toujours leur
    contenu normal de Colonne_Paies (jamais le texte d'erreur simulé),
    et les employés dont la lecture échoue affichent bien le message
    d'erreur — chaque appel à `_contenu_colonne_paies_html` étant
    indépendant des autres (aucun état partagé, aucun argument portant
    sur les autres employés)."""
    for employe, resultat_resumes in lignes:
        contenu = _contenu_colonne_paies_html(
            employe.id, resultat_resumes, annee_selectionnee=annee_selectionnee
        )

        if isinstance(resultat_resumes, ErreurDomaineAffichable):
            assert _TYPE_EXCEPTION_SIMULEE in contenu, (
                f"le contenu de l'employé en échec {employe.id!r} doit "
                f"contenir le type d'exception simulé ; obtenu {contenu!r}."
            )
            assert _MESSAGE_EXCEPTION_SIMULEE in contenu, (
                f"le contenu de l'employé en échec {employe.id!r} doit "
                f"contenir le message d'erreur simulé ; obtenu {contenu!r}."
            )
        else:
            assert _TYPE_EXCEPTION_SIMULEE not in contenu, (
                f"le contenu de l'employé en succès {employe.id!r} ne doit "
                "jamais contenir le type d'exception simulé (isolation "
                f"des erreurs des autres lignes) ; obtenu {contenu!r}."
            )
            assert _MESSAGE_EXCEPTION_SIMULEE not in contenu, (
                f"le contenu de l'employé en succès {employe.id!r} ne doit "
                "jamais contenir le message d'erreur simulé (isolation "
                f"des erreurs des autres lignes) ; obtenu {contenu!r}."
            )


# ---------------------------------------------------------------------------
# Exploration (Bug Condition) — Bug B, libellé de la Colonne_Paies
# (bugfix ``unicite-paie-active-par-periode``, tâche 7)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Design de référence : ``design.md`` §Bug Details (Bug B),
# §Correctness Properties (Property 2), §Testing Strategy « Exploratory
# Bug Condition Checking ».
#
# Tâche 7 du plan d'implémentation (méthodologie bug condition,
# observation-first, règle 06) : ces tests d'exploration DOIVENT
# échouer sur le code non corrigé — `_ligne_colonne_paie_html` affiche
# actuellement l'année et omet le numéro de période, quel que soit le
# statut. Ces échecs confirment `isBugCondition_Libelle(X)` (toujours
# vraie sur le code non corrigé, pour tout statut BROUILLON/EMISE).
#
# **NE PAS corriger ces tests ni le code lorsqu'ils échouent** —
# l'échec est le résultat attendu de cette tâche d'exploration (voir
# tâches 7, 8).
#
# _Requirements: 1.4, 1.5_


def _construire_ligne_paie_resume_exploration(
    *,
    statut: str,
    numero_periode: int,
    date_paiement: str | None = None,
) -> "LignePaieResume":
    """`LignePaieResume` minimal pour un test d'exploration (Req 04 —
    jamais de donnée personnelle réelle, uniquement des champs
    fictifs)."""
    from app.logique_metier.dernieres_paies import LignePaieResume

    return LignePaieResume(
        id_paie=f"PAIE-TEST-EXPLORATION-{statut}-{numero_periode}",
        numero_periode=numero_periode,
        version=1,
        statut=statut,
        net="0.00",
        saison="",
        annee_fiscale=2026,
        date_creation="2026-07-01T00:00:00",
        date_emission="2026-07-29T00:00:00" if statut == "emise" else None,
        date_paiement=date_paiement,
    )


class TestExplorationLibelleColonnePaies:
    """Property 2 (Bug Condition) — exploration, Bug B (libellé
    redondant/incomplet de la Colonne_Paies).

    **NE PAS corriger ces tests ni le code lorsqu'ils échouent** —
    l'échec est le résultat attendu de cette tâche d'exploration
    (tâche 7 du plan). Le fix (tâche 8) rendra ces mêmes assertions
    fausses (comportement volontairement inversé pour ce test
    d'exploration).
    """

    def test_exemple_libelle_emise_contient_annee_et_omet_numero_periode(
        self,
    ) -> None:
        """Test 1 (exemple) — Req 1.4.

        Sur le code non corrigé, un `LignePaieResume` EMISE avec
        `date_paiement="2026-07-29"` et `numero_periode=1` produit un
        texte contenant l'année (`"2026"`) et ne contenant PAS
        `"Paie #1"` — contre-exemple attendu (design §Testing Strategy,
        Test Case 3). Ce test est désormais exécuté APRÈS le fix
        (tâche 8) : il échoue intentionnellement, documentant le
        comportement bugué d'origine — ne jamais le corriger (règle
        06)."""
        resume = _construire_ligne_paie_resume_exploration(
            statut="emise",
            numero_periode=1,
            date_paiement="2026-07-29",
        )

        html_ligne = _ligne_colonne_paie_html("EMP001", resume)

        assert "2026" in html_ligne and "Paie #1" not in html_ligne, (
            "contre-exemple attendu (Bug B, code non corrigé) : le "
            f"libellé devait contenir l'année et omettre le numéro de "
            f"période ; obtenu {html_ligne!r} sur le code désormais "
            "corrigé (tâche 8) — échec intentionnel, ne pas corriger."
        )

    def test_exemple_libelle_brouillon_affiche_une_date(self) -> None:
        """Test 2 (exemple) — Req 1.5.

        Sur le code non corrigé, un `LignePaieResume` BROUILLON affiche
        quand même une date (alors qu'un brouillon ne devrait jamais en
        afficher une) — contre-exemple attendu (design §Testing
        Strategy, Test Case 4). Échec intentionnel après le fix (tâche
        8) — ne jamais corriger ce test (règle 06)."""
        resume = _construire_ligne_paie_resume_exploration(
            statut="brouillon",
            numero_periode=2,
            date_paiement="2026-08-12",
        )

        html_ligne = _ligne_colonne_paie_html("EMP001", resume)

        texte_visible = re.sub(r"<[^>]+>", "", html_ligne)
        assert texte_visible != "Paie #2 - brouillon", (
            "contre-exemple attendu (Bug B, code non corrigé) : une "
            f"date devait apparaître pour un BROUILLON ; obtenu "
            f"{texte_visible!r} sur le code désormais corrigé (tâche 8) "
            "— échec intentionnel, ne pas corriger."
        )


# ---------------------------------------------------------------------------
# Property 2 (Fix Checking) — Bug B, libellé de la Colonne_Paies sans
# année (bugfix ``unicite-paie-active-par-periode``, tâche 9)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Design de référence : ``design.md`` §Correctness Properties (Property
# 2), §Testing Strategy « Fix Checking ».
#
# Tâche 9 du plan d'implémentation. Le fix (tâche 8) est déjà en place
# dans `_ligne_colonne_paie_html` — ce test vérifie, pour tout
# `LignePaieResume` généré par Hypothesis, que le libellé produit ne
# contient jamais l'année, contient toujours `f"Paie #{numero_periode}"`,
# et respecte le suffixe exact attendu selon le statut.
#
# _Requirements: 2.4, 2.5, 2.6_


class TestFixLibelleColonnePaies:
    """Property 2 (Fix Checking) — Bug B, libellé sans année après le
    fix de la tâche 8."""

    # Feature: unicite-paie-active-par-periode, Property 2: Bug Condition - Libellé Colonne_Paies sans année
    @given(resume=st_ligne_paie_resume_arbitraire())
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_libelle_ne_contient_jamais_annee_et_contient_toujours_numero_periode(
        self, resume: "LignePaieResume"
    ) -> None:
        """Property 2 (Req 2.4, 2.5, 2.6).

        `st_ligne_paie_resume_arbitraire` génère aussi des statuts hors
        périmètre de la Colonne_Paies (``annulee``, ``remplace_par``) —
        seuls ``brouillon``/``emise`` sont exercés ici (les autres
        statuts ne sont jamais passés à `_ligne_colonne_paie_html` par
        l'appelant réel, `_contenu_colonne_paies_html`, qui les filtre
        déjà via `paies_pour_colonne`). Pour ``emise``, `date_paiement`
        doit être non `None` (exigence de `_formater_date_sans_annee`).
        """
        if resume.statut not in ("brouillon", "emise"):
            return
        if resume.statut == "emise" and resume.date_paiement is None:
            return

        html_ligne = _ligne_colonne_paie_html("EMP001", resume)
        texte_visible = re.sub(r"<[^>]+>", "", html_ligne)

        assert str(resume.annee_fiscale) not in texte_visible, (
            "le libellé ne doit jamais afficher l'année fiscale ; "
            f"obtenu {texte_visible!r} (annee_fiscale="
            f"{resume.annee_fiscale!r})."
        )
        if resume.date_paiement is not None:
            annee_extraite = resume.date_paiement[:4]
            assert annee_extraite not in texte_visible, (
                "le libellé ne doit jamais afficher l'année extraite de "
                f"date_paiement ; obtenu {texte_visible!r}."
            )

        assert f"Paie #{resume.numero_periode}" in texte_visible, (
            f"le libellé doit toujours afficher le numéro de période ; "
            f"obtenu {texte_visible!r}."
        )

        if resume.statut == "emise":
            date_attendue = _formater_date_sans_annee(resume.date_paiement)
            assert texte_visible == (
                f"Paie #{resume.numero_periode} - déposée le {date_attendue}"
            ), (
                "le suffixe EMISE doit être exact ; obtenu "
                f"{texte_visible!r}."
            )
        else:
            assert texte_visible == f"Paie #{resume.numero_periode} - brouillon", (
                "le suffixe BROUILLON doit être exact, sans date ; "
                f"obtenu {texte_visible!r}."
            )


# ---------------------------------------------------------------------------
# Property 4 (Preservation Checking) — Bug B, filtrage/tri/navigation
# de la Colonne_Paies inchangés (bugfix
# ``unicite-paie-active-par-periode``, tâche 10)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Design de référence : ``design.md`` §Correctness Properties (Property
# 4), §Testing Strategy « Preservation Checking ».
#
# Tâche 10 du plan d'implémentation (optionnelle). Le fix (tâche 8) ne
# touche jamais la construction du `href` de `_ligne_colonne_paie_html`
# ni le filtrage/tri de `paies_pour_colonne` (non modifiée) — seul le
# texte affiché change.
#
# _Requirements: 3.6, 3.7, 3.8_


class TestPreservationNavigationEtFiltrageColonnePaies:
    """Property 4 (Preservation) — Bug B, href et filtrage/tri
    inchangés après le fix de la tâche 8."""

    # Feature: unicite-paie-active-par-periode, Property 4: Preservation - Filtrage, tri et navigation de la Colonne_Paies
    @given(resume=st_ligne_paie_resume_arbitraire())
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_href_reste_identique_au_modele_dorigine(
        self, resume: "LignePaieResume"
    ) -> None:
        """Property 4 (Req 3.8).

        Le `href` produit par `_ligne_colonne_paie_html` doit rester
        strictement identique à celui produit par la logique de
        navigation d'origine (jamais modifiée par ce bugfix) :
        `/formulaire-paie?employe_id=...&id_paie=...` si BROUILLON,
        `/bulletin-paie?id_paie=...` si EMISE."""
        if resume.statut not in ("brouillon", "emise"):
            return
        if resume.statut == "emise" and resume.date_paiement is None:
            return

        html_ligne = _ligne_colonne_paie_html("EMP001", resume)
        correspondance = re.search(r'href="([^"]+)"', html_ligne)
        assert correspondance is not None, (
            f"aucun href trouvé dans le HTML produit ; obtenu {html_ligne!r}."
        )
        href_obtenu = correspondance.group(1)

        if resume.statut == "brouillon":
            href_attendu = (
                "/formulaire-paie"
                f"?employe_id={quote('EMP001')}"
                f"&id_paie={quote(resume.id_paie)}"
            )
        else:
            href_attendu = f"/bulletin-paie?id_paie={quote(resume.id_paie)}"

        assert href_obtenu == href_attendu, (
            "le href doit rester strictement identique au modèle "
            f"d'origine ; obtenu {href_obtenu!r}, attendu {href_attendu!r}."
        )

    # Feature: unicite-paie-active-par-periode, Property 4: Preservation - Filtrage, tri et navigation de la Colonne_Paies
    @given(
        resumes=st.lists(st_ligne_paie_resume_arbitraire(), min_size=0, max_size=8),
        annee=st.integers(min_value=2020, max_value=2035),
    )
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_paies_pour_colonne_filtre_et_trie_sans_regression(
        self, resumes: list, annee: int
    ) -> None:
        """Property 4 (Req 3.6, 3.7).

        `paies_pour_colonne` doit continuer à ne retourner que les
        résumés de statut BROUILLON/EMISE dont `date_paiement`
        appartient à ``annee``, triés BROUILLON avant EMISE puis date
        de paiement croissante puis numéro de période croissant
        (demande explicite de l'utilisateur — tri croissant, ajusté
        après la livraison de ce bugfix)."""
        resultat = paies_pour_colonne(tuple(resumes), annee)

        for resume in resultat:
            assert resume.statut in ("brouillon", "emise"), (
                f"seuls BROUILLON/EMISE doivent apparaître ; obtenu "
                f"{resume.statut!r}."
            )
            assert resume.date_paiement is not None, (
                "aucun résumé sans date_paiement ne doit apparaître."
            )
            assert date.fromisoformat(resume.date_paiement).year == annee, (
                "seuls les résumés de l'année sélectionnée doivent "
                f"apparaître ; obtenu {resume.date_paiement!r} pour "
                f"l'année {annee!r}."
            )

        for premier, second in zip(resultat, resultat[1:]):
            cle_premier = (
                0 if premier.statut == "brouillon" else 1,
                date.fromisoformat(premier.date_paiement).toordinal(),
                premier.numero_periode,
            )
            cle_second = (
                0 if second.statut == "brouillon" else 1,
                date.fromisoformat(second.date_paiement).toordinal(),
                second.numero_periode,
            )
            assert cle_premier <= cle_second, (
                "l'ordre BROUILLON avant EMISE, puis date croissante, "
                "puis numero_periode croissant doit être respecté ; "
                f"obtenu {cle_premier!r} après {cle_second!r}."
            )


# ---------------------------------------------------------------------------
# Tests unitaires (régression) — Bug B, Colonne_Paies (bugfix
# ``unicite-paie-active-par-periode``, tâche 11)
# ---------------------------------------------------------------------------
#
# Vérifie, sur le code corrigé, que `_ligne_colonne_paie_html` produit
# exactement le nouveau format de libellé (numéro de période toujours
# affiché, année jamais affichée) et que `_formater_date_sans_annee`
# formate correctement une date ISO sans année.
#
# Validates: Requirements 2.4, 2.5, 2.6, 3.6, 3.7, 3.8
# ---------------------------------------------------------------------------


def _construire_ligne_paie_resume(
    *,
    statut: str,
    numero_periode: int,
    date_paiement: str | None = None,
) -> "LignePaieResume":
    """`LignePaieResume` minimal pour un test d'exemple (Req 04 — jamais
    de donnée personnelle réelle, uniquement des champs fictifs)."""
    from app.logique_metier.dernieres_paies import LignePaieResume

    return LignePaieResume(
        id_paie=f"PAIE-TEST-{statut}-{numero_periode}",
        numero_periode=numero_periode,
        version=1,
        statut=statut,
        net="0.00",
        saison="",
        annee_fiscale=2026,
        date_creation="2026-07-01T00:00:00",
        date_emission="2026-07-29T00:00:00" if statut == "emise" else None,
        date_paiement=date_paiement,
    )


class TestRegressionLibelleColonnePaies:
    """Tests de régression du libellé de la Colonne_Paies (Bug B corrigé)."""

    def test_exemple_ligne_emise_produit_texte_exact_sans_annee(self) -> None:
        """`LignePaieResume` EMISE avec `date_paiement="2026-07-29"` et
        `numero_periode=1` → texte exact `"Paie #1 - déposée le 29
        juillet"` (Req 2.4, 2.6)."""
        resume = _construire_ligne_paie_resume(
            statut="emise",
            numero_periode=1,
            date_paiement="2026-07-29",
        )

        html_ligne = _ligne_colonne_paie_html("EMP001", resume)

        assert "Paie #1 - déposée le 29 juillet" in html_ligne, (
            "le texte affiché doit être exactement "
            f"'Paie #1 - déposée le 29 juillet' ; obtenu {html_ligne!r}."
        )
        assert "2026" not in html_ligne, (
            f"l'année ne doit jamais apparaître dans le libellé ; obtenu {html_ligne!r}."
        )

    def test_exemple_ligne_brouillon_produit_texte_exact_sans_date(self) -> None:
        """`LignePaieResume` BROUILLON, `numero_periode=2` → texte exact
        `"Paie #2 - brouillon"`, aucune date dans le HTML produit (Req
        2.5, 2.6)."""
        resume = _construire_ligne_paie_resume(
            statut="brouillon",
            numero_periode=2,
            date_paiement="2026-08-12",
        )

        html_ligne = _ligne_colonne_paie_html("EMP001", resume)

        assert "Paie #2 - brouillon" in html_ligne, (
            "le texte affiché doit être exactement 'Paie #2 - brouillon' ; "
            f"obtenu {html_ligne!r}."
        )
        texte_visible = re.sub(r"<[^>]+>", "", html_ligne)
        assert texte_visible == "Paie #2 - brouillon", (
            "aucune date ne doit apparaître dans le texte visible pour un "
            f"BROUILLON ; obtenu {texte_visible!r}."
        )

    def test_formater_date_sans_annee_jour_sans_zero_mois_minuscule(self) -> None:
        """`_formater_date_sans_annee` : `"2026-07-29T00:00:00"` →
        `"29 juillet"` (jour sans zéro initial, mois en minuscules,
        aucune année, Req 2.4, 2.6)."""
        resultat = _formater_date_sans_annee("2026-07-29T00:00:00")

        assert resultat == "29 juillet", (
            f"attendu '29 juillet' ; obtenu {resultat!r}."
        )
        assert "2026" not in resultat, (
            f"aucune année ne doit apparaître ; obtenu {resultat!r}."
        )
