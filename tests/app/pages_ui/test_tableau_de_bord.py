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
)
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
