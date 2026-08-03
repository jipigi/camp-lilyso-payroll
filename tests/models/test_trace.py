"""Tests d'exemple et property tests de ``CalculationTrace`` (``models/trace.py``).

Spec de référence : ``moteur-paie-contrats`` — tâche 5.1.
Design de référence : sections « Components and Interfaces » §4 et
« Data Models » §3 (``design.md``).

Discipline TDD (règle 06) : ce module de tests est écrit **avant** l'existence
de ``models/trace.py``. Tant que la tâche 5.2 n'a pas fourni l'implémentation,
la collection pytest de ce fichier échoue avec ``ModuleNotFoundError`` — c'est
le comportement attendu par la règle 06 (« tests avant code, sans exception »).

Portée de la tâche 5.1 (``tasks.md`` §5.1) :

- **Property 12 : Liste blanche des sources officielles** — Hypothesis génère
  des chaînes conformes aux regex autorisées (``TP-1015.F/G/3``, ``T4127``,
  ``TD1``, guide de l'employeur ARC, URLs ``.gouv.qc.ca`` et ``.canada.ca``)
  et vérifie que la construction réussit ; génère des chaînes non conformes
  et vérifie que la construction échoue avec un message renvoyant à la
  règle 02. **Validates: Requirements 5.2, 12.9**.
- Test d'exemple : construction sans ``source``, ``annee``,
  ``mode_arrondissement`` ou ``resultat`` lève ``pydantic.ValidationError``
  (Req 5.7).
- Test d'exemple : ``__str__`` liste, dans l'ordre, source, année, section,
  paramètres, entrées, sous-totaux, arrondissement, résultat (Req 5.6).
- Test d'exemple : l'ordre d'insertion des ``sous_totaux`` est préservé après
  round-trip JSON (Req 5.5, dict ordonné Python 3.7+).

Règles applicables (voir ``.kiro/steering/``) :

- Règle 01 — ``Decimal`` obligatoire ; aucun ``float`` dans les tests
  monétaires.
- Règle 02 — liste blanche stricte des sources officielles ; toute autre
  source est rejetée avec un message renvoyant explicitement à la règle 02.
- Règle 06 — TDD, tests avant code.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

import pydantic
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# Import volontairement au niveau module : tant que ``models/trace.py`` n'existe
# pas (tâche 5.2 non réalisée), la collection pytest de ce fichier échoue avec
# ``ModuleNotFoundError``. C'est le comportement attendu par la règle 06 —
# les tests précèdent l'implémentation.
from models.enums import Juridiction, ModeArrondissement
from models.trace import CalculationTrace


# ---------------------------------------------------------------------------
# Liste blanche des sources officielles (design.md §Components 4)
# ---------------------------------------------------------------------------
#
# Cette liste n'est PAS importée depuis ``models.trace`` : les tests vérifient
# le **comportement** attendu de la validation, pas la structure interne du
# module implémenté par la tâche 5.2. Toute divergence entre les regex ici et
# celles de l'implémentation doit être considérée comme un bug d'implémentation
# à corriger côté ``models/trace.py``.

SOURCES_REGEX_AUTORISEES: tuple[str, ...] = (
    r"^TP-1015\.F \d{4}(, section .+)?$",
    r"^TP-1015\.G \d{4}(, section .+)?$",
    r"^TP-1015\.3 \d{4}(, section .+)?$",
    r"^T4127 \d{4}(, section .+)?$",
    r"^TD1 \d{4}(, section .+)?$",
    r"^Guide de l'employeur ARC \d{4}(, section .+)?$",
    r"^https?://[a-z0-9\-\.]+\.gouv\.qc\.ca/.+$",
    r"^https?://[a-z0-9\-\.]+\.canada\.ca/.+$",
)

_MATCHERS_AUTORISES = tuple(re.compile(motif) for motif in SOURCES_REGEX_AUTORISEES)


def _est_source_autorisee(source: str) -> bool:
    """``True`` si ``source`` correspond à l'une des regex de la liste blanche."""
    return any(matcher.match(source) for matcher in _MATCHERS_AUTORISES)


def _message_mentionne_regle_02(exc: BaseException) -> bool:
    """``True`` si le message d'exception renvoie explicitement à la règle 02.

    On tolère les variantes ``règle 02``, ``regle 02``, ``rule 02`` (mais
    on exige la présence du numéro ``02`` pour éviter les faux positifs sur
    d'autres règles du dépôt). Comparaison insensible à la casse et aux
    accents (normalisation NFKD + strip ASCII).
    """
    message = str(exc)
    normalized = (
        unicodedata.normalize("NFKD", message).encode("ASCII", "ignore").decode().lower()
    )
    return bool(re.search(r"(regle|rule)\s*0*2\b", normalized))


# ---------------------------------------------------------------------------
# Fabrique de traces valides utilisée par les tests d'exemple
# ---------------------------------------------------------------------------


def _trace_valide_minimale(**overrides: object) -> CalculationTrace:
    """Construit une ``CalculationTrace`` valide, prête à être surchargée.

    Cette fabrique n'existe que pour éviter la duplication dans les tests
    « champ manquant » : chaque test construit une ``CalculationTrace``
    complète moins UN champ, sans réécrire les autres.

    Les valeurs choisies respectent les invariants du design :

    - ``source`` : URL ``.gouv.qc.ca`` bien formée (liste blanche).
    - ``annee`` : dans l'intervalle ``[2000, 2100]``.
    - ``precision_arrondissement`` : dans ``[0, 10]``.
    - Tous les montants en ``Decimal`` (règle 01).
    """
    defauts: dict[str, object] = {
        "source": "https://camp-lilyso-fixture.gouv.qc.ca/tp-1015-f-2026",
        "annee": 2026,
        "juridiction": Juridiction.QUEBEC,
        "section": "RRQ base",
        "parametres_utilises": {"taux": Decimal("0.063")},
        "entrees": {"salaire_periode": Decimal("1000.00")},
        "sous_totaux": {"assujettissable": Decimal("1000.00")},
        "mode_arrondissement": ModeArrondissement.ROUND_HALF_UP,
        "precision_arrondissement": 2,
        "resultat": Decimal("63.00"),
    }
    defauts.update(overrides)
    return CalculationTrace(**defauts)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stratégies Hypothesis dédiées à Property 12
# ---------------------------------------------------------------------------


_FORMULAIRES_OFFICIELS: tuple[str, ...] = (
    "TP-1015.F",
    "TP-1015.G",
    "TP-1015.3",
    "T4127",
    "TD1",
    "Guide de l'employeur ARC",
)

_DOMAINES_OFFICIELS: tuple[str, ...] = (
    ".gouv.qc.ca",
    ".canada.ca",
)


@st.composite
def _section_texte(draw: st.DrawFn) -> str:
    """Génère un suffixe ``section <texte>`` non vide, sans espaces flottants.

    ``str_strip_whitespace=True`` s'applique au champ ``source`` complet ;
    pour éviter tout faux positif après stripping, on filtre les textes
    dont le résultat après ``strip()`` serait vide et on interdit les
    caractères de saut de ligne (qui ne matcheraient pas ``.+``).
    """
    brut = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-",
            min_size=1,
            max_size=20,
        )
    )
    strippe = brut.strip()
    assume(strippe)
    return strippe


@st.composite
def _source_officielle_conforme(draw: st.DrawFn) -> str:
    """Génère une chaîne strictement conforme à l'une des regex autorisées.

    Deux familles de sources sont couvertes :

    - **Formulaires officiels** (``TP-1015.F/G/3``, ``T4127``, ``TD1``,
      guide ARC) : ``<formulaire> <annee>[, section <texte>]``.
    - **URLs officielles** (``.gouv.qc.ca``, ``.canada.ca``) :
      ``https?://<hote>.<domaine>/<chemin>`` avec ``<hote>`` en alphabet
      ``[a-z0-9\\-\\.]+`` et ``<chemin>`` non vide.
    """
    est_formulaire = draw(st.booleans())

    if est_formulaire:
        formulaire = draw(st.sampled_from(_FORMULAIRES_OFFICIELS))
        annee = draw(st.integers(min_value=1000, max_value=9999))
        base = f"{formulaire} {annee}"
        if draw(st.booleans()):
            section = draw(_section_texte())
            base = f"{base}, section {section}"
        return base

    # URL officielle.
    domaine = draw(st.sampled_from(_DOMAINES_OFFICIELS))
    protocole = draw(st.sampled_from(["http", "https"]))
    hote = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.",
            min_size=1,
            max_size=15,
        ).filter(lambda s: s[0].isalnum() and s[-1].isalnum())
    )
    chemin = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-_",
            min_size=1,
            max_size=20,
        )
    )
    return f"{protocole}://{hote}{domaine}/{chemin}"


@st.composite
def _source_non_conforme(draw: st.DrawFn) -> str:
    """Génère une chaîne qui ne matche AUCUNE regex de la liste blanche.

    On génère du texte arbitraire, on le strippe (comme le ferait
    ``str_strip_whitespace=True``), on écarte les valeurs vides (rejet par
    ``min_length=1``, motif différent de la règle 02) et on filtre les
    faux négatifs qui matcheraient accidentellement la liste blanche.
    """
    candidat = draw(st.text(min_size=1, max_size=100))
    strippe = candidat.strip()
    assume(strippe)
    assume(not _est_source_autorisee(strippe))
    return strippe


# ===========================================================================
# Property 12 — Liste blanche des sources officielles (Req 5.2, 12.9)
# ===========================================================================
#
# Feature: moteur-paie-contrats, Property 12: Liste blanche des sources
# officielles. *Pour toute* valeur assignée au champ ``source`` d'une
# ``CalculationTrace`` :
#
# - si la valeur correspond à l'une des expressions régulières autorisées
#   (``TP-1015.F/G/3``, ``T4127``, ``TD1``, guide de l'employeur ARC, URLs
#   ``.gouv.qc.ca`` et ``.canada.ca``), la construction doit réussir ;
# - sinon, la construction doit lever ``pydantic.ValidationError`` avec un
#   message renvoyant explicitement à la règle 02.
#
# **Validates: Requirements 5.2, 12.9**
# ===========================================================================


class TestListeBlancheSourcesExemples:
    """Exemples ancrés pour verrouiller les 8 motifs de la liste blanche.

    Chaque motif ci-dessous est un exemple ancré qui documente le format
    exact attendu par la règle 02 pour une source officielle. Les property
    tests Hypothesis qui suivent généralisent au-delà de ces ancres.
    """

    @pytest.mark.parametrize(
        "source_conforme",
        [
            "TP-1015.F 2026",
            "TP-1015.F 2026, section 3.2 — RRQ",
            "TP-1015.G 2026",
            "TP-1015.G 2026, section 4.1",
            "TP-1015.3 2026",
            "TP-1015.3 2026, section montant total",
            "T4127 2026",
            "T4127 2026, section 8",
            "TD1 2026",
            "TD1 2026, section montant personnel",
            "Guide de l'employeur ARC 2026",
            "Guide de l'employeur ARC 2026, section retenues",
            "https://www.revenuquebec.ca.gouv.qc.ca/documents/tp-1015",
            "http://www.revenuquebec.gouv.qc.ca/citoyens/impots",
            "https://www.canada.ca/fr/agence-revenu/services/impot",
            "http://www.canada.ca/formulaires/td1",
        ],
    )
    def test_source_conforme_a_la_liste_blanche_est_acceptee(
        self, source_conforme: str
    ) -> None:
        """Req 5.2 — une source conforme aux regex autorisées passe la validation."""
        # Sanity : la source ancrée matche bien l'une des regex de la liste
        # blanche (sinon le test lui-même serait mal calibré).
        assert _est_source_autorisee(source_conforme), (
            f"Cette source ancrée '{source_conforme}' ne matche aucune regex "
            f"de la liste blanche du design §Components 4 — corriger le test."
        )
        trace = _trace_valide_minimale(source=source_conforme)
        assert trace.source == source_conforme

    @pytest.mark.parametrize(
        "source_non_conforme",
        [
            # Sources factuellement fausses (mauvais format, année manquante).
            "TP-1015.F",
            "TP-1015.F 26",  # année à 2 chiffres
            "TP-1015.F 20260",  # année à 5 chiffres
            "tp-1015.f 2026",  # casse incorrecte
            "TP-1015 2026",  # sous-formulaire manquant
            "T4127",  # année manquante
            # Sources non officielles (règle 02 — sources autres refusées).
            "Wikipédia — RRQ",
            "Blog fiscal 2026",
            "Communication interne Camp LilySO",
            "Forum de discussion fiscale",
            "https://blog.fiscal.com/tp-1015",
            "https://revenuquebec.example.org/TP-1015.F",
            # URLs mal formées / faux domaines.
            "https://gouv.qc.ca",  # chemin absent
            "https://www.gouv.qc.ca",  # chemin absent (le .+ après / est requis)
            "https://.canada.ca/",  # sous-domaine vide
            "ftp://revenuquebec.gouv.qc.ca/doc",  # protocole non autorisé
            "https://revenuquebec.gouv.qc.CA/doc",  # majuscules dans l'hôte
            # Chaînes visiblement non liées.
            "N/A",
            "à préciser",
            "voir plus tard",
            "42",
        ],
    )
    def test_source_non_conforme_leve_validation_error_mentionnant_regle_02(
        self, source_non_conforme: str
    ) -> None:
        """Req 5.2 — refus fail-fast avec référence explicite à la règle 02."""
        # Sanity : la source ancrée doit effectivement échouer côté regex
        # (sinon le test testerait le comportement inverse).
        assert not _est_source_autorisee(source_non_conforme), (
            f"Cette source ancrée '{source_non_conforme}' matche par erreur "
            f"une regex de la liste blanche — corriger le test."
        )

        with pytest.raises(pydantic.ValidationError) as exc_info:
            _trace_valide_minimale(source=source_non_conforme)

        assert _message_mentionne_regle_02(exc_info.value), (
            f"Le message d'exception pour la source '{source_non_conforme}' "
            f"doit renvoyer explicitement à la règle 02 (traçabilité des "
            f"formules). Reçu :\n{exc_info.value}"
        )


@pytest.mark.property
class TestListeBlancheSourcesProperty:
    """Property 12 (Hypothesis) — généralisation sur l'espace des sources."""

    # Feature: moteur-paie-contrats, Property 12: Liste blanche des sources
    # officielles.
    #
    # **Validates: Requirements 5.2, 12.9**
    @given(source=_source_officielle_conforme())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.filter_too_much],
    )
    def test_toute_source_conforme_est_acceptee(self, source: str) -> None:
        """Req 5.2 — *pour toute* source matchant une regex autorisée, succès."""
        # Sanity : la stratégie DOIT produire des sources conformes.
        assert _est_source_autorisee(source), (
            f"La stratégie _source_officielle_conforme a produit '{source}' "
            f"qui ne matche aucune regex de la liste blanche — corriger la "
            f"stratégie."
        )
        trace = _trace_valide_minimale(source=source)
        # ``str_strip_whitespace=True`` : la source stockée est équivalente à
        # ``source.strip()`` (les stratégies génèrent déjà des chaînes stripées).
        assert trace.source == source

    # Feature: moteur-paie-contrats, Property 12: Liste blanche des sources
    # officielles.
    #
    # **Validates: Requirements 5.2, 12.9**
    @given(source=_source_non_conforme())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.filter_too_much],
    )
    def test_toute_source_non_conforme_est_rejetee_avec_reference_regle_02(
        self, source: str
    ) -> None:
        """Req 5.2 — *pour toute* source hors liste blanche, refus + règle 02."""
        # Sanity : la stratégie DOIT produire des sources non conformes.
        assert not _est_source_autorisee(source), (
            f"La stratégie _source_non_conforme a produit '{source}' qui "
            f"matche par erreur une regex de la liste blanche — corriger "
            f"la stratégie."
        )
        with pytest.raises(pydantic.ValidationError) as exc_info:
            _trace_valide_minimale(source=source)
        assert _message_mentionne_regle_02(exc_info.value), (
            f"Le message d'exception pour la source '{source}' doit renvoyer "
            f"explicitement à la règle 02 (traçabilité des formules). "
            f"Reçu :\n{exc_info.value}"
        )


# ===========================================================================
# Champs obligatoires manquants (Req 5.7)
# ===========================================================================


class TestChampsObligatoiresManquants:
    """Req 5.7 — la construction sans un champ obligatoire lève ``ValidationError``.

    Le task 5.1 exige explicitement de couvrir les 4 champs suivants :
    ``source``, ``annee``, ``mode_arrondissement`` et ``resultat``. Les
    autres champs obligatoires (``juridiction``, ``section``,
    ``precision_arrondissement``) ne sont pas testés ici pour rester
    strictement dans la portée de la tâche 5.1.
    """

    def test_construction_sans_source_leve_validation_error(self) -> None:
        with pytest.raises(pydantic.ValidationError) as exc_info:
            CalculationTrace(  # type: ignore[call-arg]
                # source omis
                annee=2026,
                juridiction=Juridiction.QUEBEC,
                section="RRQ",
                mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
                precision_arrondissement=2,
                resultat=Decimal("100.00"),
            )
        # Le rapport d'erreur Pydantic v2 doit référencer le champ manquant.
        assert "source" in str(exc_info.value).lower()

    def test_construction_sans_annee_leve_validation_error(self) -> None:
        with pytest.raises(pydantic.ValidationError) as exc_info:
            CalculationTrace(  # type: ignore[call-arg]
                source="TP-1015.F 2026",
                # annee omise
                juridiction=Juridiction.QUEBEC,
                section="RRQ",
                mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
                precision_arrondissement=2,
                resultat=Decimal("100.00"),
            )
        assert "annee" in str(exc_info.value).lower()

    def test_construction_sans_mode_arrondissement_leve_validation_error(self) -> None:
        with pytest.raises(pydantic.ValidationError) as exc_info:
            CalculationTrace(  # type: ignore[call-arg]
                source="TP-1015.F 2026",
                annee=2026,
                juridiction=Juridiction.QUEBEC,
                section="RRQ",
                # mode_arrondissement omis
                precision_arrondissement=2,
                resultat=Decimal("100.00"),
            )
        assert "mode_arrondissement" in str(exc_info.value).lower()

    def test_construction_sans_resultat_leve_validation_error(self) -> None:
        with pytest.raises(pydantic.ValidationError) as exc_info:
            CalculationTrace(  # type: ignore[call-arg]
                source="TP-1015.F 2026",
                annee=2026,
                juridiction=Juridiction.QUEBEC,
                section="RRQ",
                mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
                precision_arrondissement=2,
                # resultat omis
            )
        assert "resultat" in str(exc_info.value).lower()


# ===========================================================================
# Représentation textuelle ordonnée ``__str__`` (Req 5.6)
# ===========================================================================


class TestRepresentationTextuelleOrdonnee:
    """Req 5.6 — ``__str__`` liste, dans l'ordre : source, année, section,
    paramètres, entrées, sous-totaux, arrondissement, résultat.
    """

    def test_str_liste_les_sections_dans_lordre_impose(self) -> None:
        """Les 8 sections DOIVENT apparaître dans la représentation, dans l'ordre.

        Stratégie : chaque section reçoit un marqueur unique dans sa valeur,
        puis on vérifie que ces marqueurs apparaissent dans un ordre
        strictement croissant dans ``str(trace)``. Les marqueurs sont choisis
        pour être disjoints (aucun n'est un sous-chaîne d'un autre) et
        n'apparaître que dans la section correspondante.
        """
        trace = CalculationTrace(
            source="https://zzz-marqueur-source-unique.gouv.qc.ca/document",
            annee=2077,  # année unique, ne peut apparaître nulle part ailleurs
            juridiction=Juridiction.QUEBEC,
            section="MARQUEUR-SECTION-UNIQUE",
            parametres_utilises={"MARQUEUR-PARAM-UNIQUE": Decimal("111.11")},
            entrees={"MARQUEUR-ENTREE-UNIQUE": Decimal("222.22")},
            sous_totaux={"MARQUEUR-SOUSTOTAL-UNIQUE": Decimal("333.33")},
            mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
            precision_arrondissement=2,
            resultat=Decimal("999.99"),
        )

        representation = str(trace)

        # Chaque marqueur identifie sa section de manière univoque et
        # n'apparaît nulle part ailleurs dans la trace.
        marqueurs_ordonnes = [
            ("source", "zzz-marqueur-source-unique"),
            ("annee", "2077"),
            ("section", "MARQUEUR-SECTION-UNIQUE"),
            ("parametres", "MARQUEUR-PARAM-UNIQUE"),
            ("entrees", "MARQUEUR-ENTREE-UNIQUE"),
            ("sous_totaux", "MARQUEUR-SOUSTOTAL-UNIQUE"),
            ("arrondissement", "ROUND_HALF_UP"),
            ("resultat", "999.99"),
        ]

        positions: list[tuple[str, int]] = []
        for nom_section, marqueur in marqueurs_ordonnes:
            position = representation.find(marqueur)
            assert position != -1, (
                f"Section '{nom_section}' (marqueur '{marqueur}') absente "
                f"de la représentation textuelle. Reçu :\n{representation}"
            )
            positions.append((nom_section, position))

        # Itération pairwise « courant, suivant » : ``positions[1:]`` a par
        # construction un élément de moins que ``positions``, donc ``strict``
        # doit rester à False (comportement par défaut de ``zip``).
        for (nom_actuel, pos_actuelle), (nom_suivant, pos_suivante) in zip(
            positions, positions[1:]
        ):
            assert pos_actuelle < pos_suivante, (
                f"Ordre incorrect : '{nom_actuel}' (position {pos_actuelle}) "
                f"doit précéder '{nom_suivant}' (position {pos_suivante}). "
                f"L'ordre imposé par Req 5.6 est : source, année, section, "
                f"paramètres, entrées, sous-totaux, arrondissement, résultat.\n"
                f"Représentation reçue :\n{representation}"
            )


# ===========================================================================
# Round-trip JSON : ordre d'insertion des ``sous_totaux`` préservé (Req 5.5)
# ===========================================================================


class TestOrdreInsertionSousTotauxApresRoundTrip:
    """Req 5.5 — l'ordre d'insertion des ``sous_totaux`` est préservé après
    ``model_dump_json`` puis ``model_validate_json`` (round-trip déterministe).

    Cette contrainte s'appuie sur le fait que les ``dict`` Python (3.7+)
    conservent l'ordre d'insertion, et que la sérialisation JSON produite
    par Pydantic v2 respecte cet ordre. Le parseur ``model_validate_json``
    doit à son tour recréer un ``dict`` dans le même ordre d'insertion.
    """

    def test_ordre_dinsertion_conserve_apres_round_trip(self) -> None:
        # Ordre d'insertion volontairement non alphabétique pour distinguer
        # « préservation de l'ordre d'insertion » d'un éventuel tri implicite.
        sous_totaux_ordonnes = {
            "zeta_premiere_etape": Decimal("100.00"),
            "alpha_deuxieme_etape": Decimal("200.00"),
            "mu_troisieme_etape": Decimal("300.00"),
            "beta_quatrieme_etape": Decimal("400.00"),
        }
        trace_originale = _trace_valide_minimale(sous_totaux=sous_totaux_ordonnes)

        json_serialise = trace_originale.model_dump_json()
        trace_reconstituee = CalculationTrace.model_validate_json(json_serialise)

        # Ordre d'insertion strictement identique après le round-trip.
        assert list(trace_reconstituee.sous_totaux.keys()) == list(
            sous_totaux_ordonnes.keys()
        ), (
            "L'ordre d'insertion des sous_totaux DOIT être préservé après "
            "round-trip JSON. Ordre attendu : "
            f"{list(sous_totaux_ordonnes.keys())}. Ordre reçu : "
            f"{list(trace_reconstituee.sous_totaux.keys())}."
        )

        # Valeurs strictement égales (au cent près, sans conversion float).
        for cle, valeur_attendue in sous_totaux_ordonnes.items():
            assert trace_reconstituee.sous_totaux[cle] == valeur_attendue

    def test_ordre_est_deterministe_deux_appels_successifs(self) -> None:
        """Deux sérialisations d'une même instance produisent le même ordre.

        Complément robustesse du round-trip : ``model_dump_json`` doit être
        déterministe (aucun état interne ne modifie l'ordre entre deux
        appels), sinon le round-trip ne serait pas idempotent.
        """
        sous_totaux_ordonnes = {
            "etape_1_brut": Decimal("1000.00"),
            "etape_2_exemption": Decimal("50.00"),
            "etape_3_assujettissable": Decimal("950.00"),
        }
        trace = _trace_valide_minimale(sous_totaux=sous_totaux_ordonnes)

        premier_dump = trace.model_dump_json()
        second_dump = trace.model_dump_json()
        assert premier_dump == second_dump

        # Deux reconstructions successives donnent des instances avec le
        # même ordre de clés.
        reconstituee_1 = CalculationTrace.model_validate_json(premier_dump)
        reconstituee_2 = CalculationTrace.model_validate_json(premier_dump)
        assert list(reconstituee_1.sous_totaux.keys()) == list(
            reconstituee_2.sous_totaux.keys()
        )


# ===========================================================================
# Extension de la liste blanche : motif ``LE-39.0.2 <année>`` (CNT)
# ===========================================================================
#
# Portée : spec ``charges-patronales`` — tâche 4.1.
# Design de référence : ``charges-patronales/design.md`` §Data Models
# « Extension de la liste blanche ``CalculationTrace`` ».
#
# La cotisation relative aux normes du travail (CNT) est tracée avec la
# source officielle ``"LE-39.0.2 <année>"`` (formulaire Revenu Québec, source
# réelle du Taux_CNT). Ce motif n'est **pas encore** admis par
# ``_SOURCES_OFFICIELLES_REGEX`` : son ajout — strictement additif — est une
# dépendance de contrat (Req 5.7, Req 12.3) réalisée par la tâche 8.1.
#
# Discipline TDD (règle 06) : la classe ci-dessous est écrite **avant** que la
# tâche 8.1 n'étende la liste blanche. Tant que le motif
# ``r"^LE-39\.0\.2 \d{4}(, .+)?$"`` n'est pas ajouté à ``models/trace.py``, le
# test d'acceptation ``test_source_le_39_est_acceptee`` échoue avec
# ``pydantic.ValidationError`` — c'est le comportement rouge attendu. Les
# tests de non-régression, eux, doivent passer immédiatement (aucun motif
# existant n'est retiré ni modifié par cette extension).
# ===========================================================================


class TestListeBlancheLE39:
    """Req 5.7, 12.3 — extension additive de la liste blanche pour ``LE-39.0.2``.

    Trois garanties sont vérifiées :

    1. **Acceptation** — après extension, ``source="LE-39.0.2 2026"`` construit
       une ``CalculationTrace`` sans erreur (test rouge jusqu'à la tâche 8.1).
    2. **Non-régression des sources déjà admises** — la source FSS
       ``"TP-1015.F 2026, section 5 — FSS"`` et une URL CNESST
       ``www.cnesst.gouv.qc.ca`` restent acceptées.
    3. **Non-régression du refus** — une source non officielle
       (``"blog interne"``) reste rejetée avec un message renvoyant à la
       règle 02.
    """

    # --- 1. Acceptation du nouveau motif (rouge jusqu'à la tâche 8.1) ------

    @pytest.mark.parametrize(
        "source_cnt",
        [
            "LE-39.0.2 2026",
            "LE-39.0.2 2027",
            "LE-39.0.2 2026, ligne 35 — CNT",
        ],
    )
    def test_source_le_39_est_acceptee(self, source_cnt: str) -> None:
        """Req 5.7, 12.3 — le motif ``LE-39.0.2 <année>`` passe la validation.

        Comportement attendu **avant** la tâche 8.1 : ``pydantic.ValidationError``
        (motif absent de la liste blanche). **Après** l'extension additive :
        construction réussie et ``trace.source == source_cnt``.
        """
        trace = _trace_valide_minimale(source=source_cnt)
        assert trace.source == source_cnt

    # --- 2. Non-régression : sources déjà admises restent acceptées -------

    @pytest.mark.parametrize(
        "source_deja_admise",
        [
            # FSS — formulaire TP-1015.F avec sous-section (Req 5.1 charges).
            "TP-1015.F 2026, section 5 — FSS",
            # CNESST — URL officielle .gouv.qc.ca (motif URL déjà présent).
            "https://www.cnesst.gouv.qc.ca/fr/organisation/documentation/taux-cotisation",
            "http://www.cnesst.gouv.qc.ca/fr/demarches-formulaires/classification",
        ],
    )
    def test_sources_officielles_existantes_restent_acceptees(
        self, source_deja_admise: str
    ) -> None:
        """Req 5.7 — l'extension est additive : aucune source déjà admise ne casse."""
        trace = _trace_valide_minimale(source=source_deja_admise)
        assert trace.source == source_deja_admise

    # --- 3. Non-régression : sources non officielles restent rejetées -----

    @pytest.mark.parametrize(
        "source_non_officielle",
        [
            "blog interne",
            "LE-39.0.2",  # année manquante — ne matche pas le nouveau motif
            "LE-39 2026",  # sous-formulaire incomplet
        ],
    )
    def test_sources_non_officielles_restent_rejetees(
        self, source_non_officielle: str
    ) -> None:
        """Req 5.7 — une source hors liste blanche est refusée (règle 02).

        L'extension n'assouplit pas la validation : toute source non conforme,
        y compris un ``LE-39.0.2`` mal formé (année manquante), doit lever
        ``pydantic.ValidationError`` avec un message renvoyant à la règle 02.
        """
        with pytest.raises(pydantic.ValidationError) as exc_info:
            _trace_valide_minimale(source=source_non_officielle)
        assert _message_mentionne_regle_02(exc_info.value), (
            f"Le refus de la source '{source_non_officielle}' doit renvoyer "
            f"explicitement à la règle 02. Reçu :\n{exc_info.value}"
        )
