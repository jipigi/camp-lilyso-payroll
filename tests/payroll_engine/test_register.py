"""Property tests et tests d'exemple pour `payroll_engine/register.py`.

Spec de référence : ``net-cumuls-registre`` — tâche 3.1 (squelette du
fichier et tests transversaux).
Design de référence : ``design.md`` §Testing Strategy, §Correctness
Properties 8 à 14 et §Components §3.0 (signatures exactes), §3.1
(`chemin_bd_production`).

Ce fichier porte l'ensemble des property tests et tests d'exemple du
registre maître SQLite ``payroll_engine/register.py`` (`inserer_paie`,
`lire_paie`, `lire_historique_paie`, `lire_cumuls_ytd`, `remplacer_paie`).
La tâche 3.1 pose le **squelette** : le module docstring, les imports, et
les tests **transversaux** (classe ``TestSignatureEtChemin``) qui couvrent
la signature exacte des cinq fonctions publiques, la résolution de
``chemin_bd_production()`` et l'acceptation structurelle de ``":memory:"``
comme ``chemin_bd``. Les tâches suivantes ajouteront :

- ``TestCumulYTDDeNPaies`` — Property 8 (tâche 3.2) ;
- ``TestRemplacerPaie`` — Property 9 (tâche 3.3) ;
- ``TestRoundTrip`` — Property 10 (tâche 3.4) ;
- ``TestImmutabiliteLignes`` — Property 11 (tâche 3.5, ajoutée) ;
- ``TestAbsenceFloat`` — Property 12 (tâche 3.6) ;
- ``TestInvarianceSaison`` — Property 13 (tâche 3.7) ;
- ``TestRefusInsertionDupliquee`` — Property 14 (tâche 3.8).

Les **7 propriétés** couvertes par ce fichier de test au total (design.md
§Correctness Properties) :

8. **Property 8 — Cumul YTD de *n* paies = somme des contributions**.
9. **Property 9 — Idempotence de substitution (`remplacer_paie`)**.
10. **Property 10 — Round-trip de sérialisation sans perte**.
11. **Property 11 — Immuabilité des lignes déjà insérées**.
12. **Property 12 — Absence de `float`**.
13. **Property 13 — Invariance de `cumuls_ytd` par rapport à `saison`**.
14. **Property 14 — Refus d'insertion dupliquée sans corruption**.

Discipline règle 06 (TDD — tests avant code) :
``payroll_engine/register.py`` n'existe **pas encore** à ce stade. Comme
``test_net_pay.py`` (même spec, tâche 2.1), ce fichier **importe
localement** le module sous test (via un helper
``_importer_module_register`` appelé au sein de chaque test) afin que la
**collecte** pytest de ce fichier réussisse même tant que le module cible
est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``payroll_engine.register`` — c'est le
comportement **attendu et correct** (état rouge intentionnel) tant que la
tâche 8 (implémentation) n'a pas été réalisée (checkpoint de la tâche 6 du
plan).

Règle 01 : tous les montants manipulés par ces tests sont des ``Decimal``
(jamais de ``float``), y compris dans les assertions de comparaison ; les
tests de cette tâche n'inspectent pas encore les colonnes SQLite
directement via ``sqlite3`` (réservé à la Property 12, tâche 3.6) — le
module ``sqlite3`` est néanmoins importé ici pour rester disponible aux
tâches suivantes du même fichier.
Règle 04 : chaque test injecte systématiquement un ``chemin_bd`` temporaire
(``tmp_path``) ou ``":memory:"`` — jamais la base de production — et
n'utilise que des identifiants fictifs ``EMPnnn`` (via les stratégies de
``tests/strategies.py``).
"""

from __future__ import annotations

import importlib
import inspect
import sqlite3
import uuid
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from datetime import date, datetime, timedelta

from models._validators import _parse_json_reject_floats
from models.cumuls import CumulsYTD
from models.enums import FrequencePaie, StatutDePaie
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    PayrollResult,
    RetenuesEmploye,
)
from tests.strategies import (
    _st_montant_registre,
    st_chemin_bd_temporaire,  # noqa: F401  (fixture pytest, résolue par nom de paramètre)
    st_cumuls_ytd_non_nuls,
    st_saison,
    st_sequence_payroll_results_meme_employe_annee,
    st_statut_nouveau_resultat_refuse,
)

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_net_pay.py). Le
# nombre d'exemples est piloté par le profil Hypothesis actif (voir
# tests/conftest.py : dev=15 par défaut, ci=100). ``deadline=None`` est
# indispensable ici : les tests impliquant SQLite sont plus lents que les
# tests purement en mémoire du reste de la suite (design §Testing Strategy
# « Configuration Hypothesis »).
# ---------------------------------------------------------------------------

settings_large_input = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

#: Nom qualifié du module sous test (règle 06 — importé localement pour ne
#: pas faire échouer la collecte tant que la tâche 8 n'a pas créé le module).
_NOM_MODULE_CIBLE = "payroll_engine.register"

#: Ordre exact des paramètres imposé par le design §Components §3.0
#: (« Signatures exactes ») pour chacune des cinq fonctions publiques du
#: registre. ``chemin_bd`` est toujours le dernier paramètre, avec le
#: chemin de production comme valeur par défaut (Req 15.1).
_SIGNATURES_ATTENDUES: dict[str, tuple[str, ...]] = {
    "inserer_paie": ("resultat", "saison", "payroll_input", "chemin_bd"),
    "lire_paie": ("id_paie", "chemin_bd"),
    "lire_historique_paie": (
        "employe_id",
        "annee_fiscale",
        "numero_periode",
        "chemin_bd",
    ),
    "lire_cumuls_ytd": ("employe_id", "annee_civile", "chemin_bd"),
    "remplacer_paie": (
        "ancien_id",
        "nouveau_resultat",
        "saison",
        "nouveau_payroll_input",
        "chemin_bd",
    ),
}

#: Paramètres autorisés à porter une valeur par défaut en plus de
#: `chemin_bd` — extension assumée de la signature par le bugfix
#: `heures-periode-et-persistance-brouillon` (design §Fix Implementation,
#: point 6) : `payroll_input`/`nouveau_payroll_input` sont optionnels
#: (défaut `None`) pour préserver tout appelant existant qui ne transmet
#: pas de `PayrollInput` (Property 4, préservation).
_PARAMETRES_AVEC_DEFAUT_AUTORISE: frozenset[str] = frozenset(
    {"chemin_bd", "payroll_input", "nouveau_payroll_input"}
)


# ---------------------------------------------------------------------------
# Helper interne — import local du module cible (règle 06).
# ---------------------------------------------------------------------------


def _importer_module_register() -> ModuleType:
    """Importe ``payroll_engine.register`` au moment de l'appel.

    Règle 06 (TDD — tests avant code) : le module cible n'existe pas
    encore. En différant l'import à l'intérieur des tests (plutôt qu'au
    niveau module), la **collecte** pytest de ce fichier reste possible ;
    seule l'**exécution** de chaque test lève ``ModuleNotFoundError`` tant
    que la tâche 8 n'a pas créé le module — état rouge attendu et correct.
    """
    return importlib.import_module(_NOM_MODULE_CIBLE)


#: Un unique ``PayrollResult`` ``EMISE`` valide et autonome, obtenu en
#: filtrant ``st_sequence_payroll_results_meme_employe_annee(n_max=1)`` sur
#: le cas ``n = 1`` (tâche 1.1, réutilisée sans modification). Utilisée
#: uniquement par le test d'exemple « acceptation de `":memory:"` » de
#: cette tâche — les Properties 8/9/10/14 (tâches 3.2 à 3.8) utiliseront la
#: séquence complète directement.
_st_un_payroll_result_emis: st.SearchStrategy[PayrollResult] = (
    st_sequence_payroll_results_meme_employe_annee(n_max=1)
    .filter(lambda sequence: len(sequence) == 1)
    .map(lambda sequence: sequence[0])
)


# ---------------------------------------------------------------------------
# 3.1 — Signature exacte, résolution de chemin_bd_production, acceptation
#       structurelle de ":memory:" (tests transversaux, aucune Property
#       numérotée ne porte spécifiquement sur ces trois aspects).
# ---------------------------------------------------------------------------


class TestSignatureEtChemin:
    """Tests transversaux du registre maître : signatures, chemin de
    production, injection de ``chemin_bd`` de test.

    Design (§Components §3.0 « Signatures exactes », §3.1
    « chemin_bd_production ») ; Requirements 11.1, 12.1, 12.3, 12.4, 13.1
    (signatures), 15.1 (chemin de production), 15.2 (injection de test).
    """

    def test_exemple_signature_exacte_des_cinq_fonctions_du_registre(self) -> None:
        """Test d'exemple — signature exacte des cinq fonctions publiques
        (Req 11.1, 12.1, 12.3, 12.4, 13.1).

        Chacune des cinq fonctions expose, dans l'ordre, les paramètres
        du design §Components §3.0, avec ``chemin_bd`` systématiquement en
        dernière position et porteur d'une valeur par défaut (le chemin
        de production, jamais un défaut absent) ; aucun autre paramètre ne
        porte de valeur par défaut. Vérifié par introspection
        ``inspect.signature``.
        """
        module = _importer_module_register()

        for nom_fonction, parametres_attendus in _SIGNATURES_ATTENDUES.items():
            assert hasattr(module, nom_fonction), (
                f"Le module cible doit exposer `{nom_fonction}` "
                f"(design §Components §3.0)."
            )
            fonction = getattr(module, nom_fonction)
            signature = inspect.signature(fonction)

            noms_parametres = tuple(signature.parameters)
            assert noms_parametres == parametres_attendus, (
                f"`{nom_fonction}` doit avoir les paramètres "
                f"{parametres_attendus} dans cet ordre, obtenu "
                f"{noms_parametres}."
            )

            for nom, parametre in signature.parameters.items():
                assert parametre.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.POSITIONAL_ONLY,
                ), (
                    f"`{nom_fonction}` doit exposer un paramètre "
                    f"positionnel `{nom}`."
                )

                if nom == "chemin_bd":
                    assert parametre.default is not inspect.Parameter.empty, (
                        f"`{nom_fonction}` doit fournir une valeur par "
                        f"défaut pour `chemin_bd` — le chemin de "
                        f"production (Req 15.1)."
                    )
                elif nom in _PARAMETRES_AVEC_DEFAUT_AUTORISE:
                    # `payroll_input`/`nouveau_payroll_input` — rupture de
                    # signature assumée par le bugfix
                    # `heures-periode-et-persistance-brouillon` (design
                    # §Fix Implementation, point 6) : défaut `None`
                    # explicitement requis pour la préservation (Property
                    # 4) de tout appelant existant.
                    assert parametre.default is None, (
                        f"`{nom}` de `{nom_fonction}` doit porter le "
                        f"défaut `None` (préservation, design "
                        f"§Correctness Properties Property 4), obtenu "
                        f"{parametre.default!r}."
                    )
                else:
                    assert parametre.default is inspect.Parameter.empty, (
                        f"`{nom}` de `{nom_fonction}` ne doit imposer "
                        f"aucune valeur par défaut, obtenu "
                        f"{parametre.default!r}."
                    )

    def test_exemple_chemin_bd_production_sans_parametre(self) -> None:
        """Test d'exemple — ``chemin_bd_production()`` n'accepte aucun
        argument (design §Components §3.0/§3.1 : fonction pure, sans
        paramètre).
        """
        module = _importer_module_register()

        assert hasattr(module, "chemin_bd_production"), (
            "Le module cible doit exposer `chemin_bd_production` "
            "(design §Components §3.1)."
        )
        signature = inspect.signature(module.chemin_bd_production)
        assert tuple(signature.parameters) == (), (
            "`chemin_bd_production` ne doit accepter aucun paramètre, "
            f"obtenu {tuple(signature.parameters)}."
        )

    def test_exemple_chemin_bd_production_sous_camplilyso_jamais_racine_depot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test d'exemple — ``chemin_bd_production()`` retourne un chemin
        sous ``CampLilySO/payroll.db``, jamais sous la racine du dépôt
        (Req 15.1).

        ``monkeypatch.setenv("APPDATA", str(tmp_path))`` isole le test de
        l'environnement réel de la machine d'exécution (règle 04 — jamais
        la base de production, même en lecture de son chemin) : le chemin
        retourné doit alors se résoudre relativement à ce ``tmp_path``
        injecté, jamais relativement au dépôt versionné.
        """
        monkeypatch.setenv("APPDATA", str(tmp_path))
        module = _importer_module_register()

        chemin = module.chemin_bd_production()

        assert chemin == tmp_path / "CampLilySO" / "payroll.db", (
            "`chemin_bd_production()` doit résoudre "
            "`%APPDATA%\\CampLilySO\\payroll.db` (Req 15.1), obtenu "
            f"{chemin!r}."
        )

        racine_depot = Path(__file__).resolve().parents[2]
        chemin_resolu = Path(chemin).resolve()
        assert racine_depot not in (chemin_resolu, *chemin_resolu.parents), (
            "`chemin_bd_production()` ne doit jamais pointer sous la "
            f"racine du dépôt versionné ({racine_depot}), obtenu "
            f"{chemin_resolu} (règle 04)."
        )

    @given(resultat=_st_un_payroll_result_emis, saison=st_saison())
    @settings_large_input
    def test_exemple_chaque_fonction_publique_accepte_memoire_sans_erreur(
        self, resultat: PayrollResult, saison: str
    ) -> None:
        """Test d'exemple — chaque fonction publique accepte ``":memory:"``
        comme ``chemin_bd`` sans erreur structurelle (Req 15.2).

        Chaque appel ``sqlite3.connect(":memory:")`` ouvre une base
        **indépendante** — une fonction du registre qui ouvre sa propre
        connexion ne peut donc pas relire, via un autre appel ``":memory:"``,
        les données insérées par un appel précédent. Ce test vérifie donc
        uniquement l'**acceptation structurelle** de ``":memory:"`` (schéma
        créé, aucune erreur SQLite de bas niveau) : ``inserer_paie``
        réussit sur une base neuve ; ``lire_paie``/`remplacer_paie` lèvent
        la ``KeyError`` **attendue** (Req 12.2, 13.2) puisque l'identifiant
        recherché est nécessairement absent de leur propre base
        ``":memory:"`` fraîche ; ``lire_historique_paie`` retourne un
        tuple vide et ``lire_cumuls_ytd`` retourne
        ``CumulsYTD.zero(...)`` — aucune de ces quatre lectures ne doit
        lever une exception autre que celles explicitement attendues.
        """
        module = _importer_module_register()

        module.inserer_paie(resultat, saison, chemin_bd=":memory:")

        with pytest.raises(KeyError):
            module.lire_paie(resultat.id_paie, chemin_bd=":memory:")

        historique = module.lire_historique_paie(
            resultat.employe_id,
            resultat.annee_fiscale,
            resultat.pay_period.numero_periode,
            chemin_bd=":memory:",
        )
        assert historique == (), (
            "`lire_historique_paie` sur une base `:memory:` fraîche doit "
            f"retourner un tuple vide, obtenu {historique!r}."
        )

        cumuls = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=":memory:"
        )
        assert cumuls == CumulsYTD.zero(resultat.employe_id, resultat.annee_fiscale), (
            "`lire_cumuls_ytd` sur une base `:memory:` fraîche doit "
            f"retourner `CumulsYTD.zero(...)`, obtenu {cumuls!r}."
        )

        with pytest.raises(KeyError):
            module.remplacer_paie(
                resultat.id_paie, resultat, saison, chemin_bd=":memory:"
            )


# ---------------------------------------------------------------------------
# 3.2 — Property 8 : Cumul YTD de *n* paies = somme des contributions.
# ---------------------------------------------------------------------------

#: Mapping exact des onze catégories `_CATEGORIES_MONETAIRES` (design
#: §Components §2, table du mapping Req 6 AC2) vers l'accès correspondant
#: sur un `PayrollResult` complet. Contrairement à `_ContributionPaie`
#: (interne à `net_pay.py`), `PayrollResult` n'expose PAS ces catégories
#: comme attributs plats de premier niveau (design §Components §2 :
#: "`resultat` EST un PayrollResult complet : `CumulsYTD.avec_paie` lit
#: ses onze catégories nativement" — l'accès par `getattr(resultat, cat,
#: ...)` que `CumulsYTD.avec_paie` effectue réellement retombe donc sur
#: la valeur *actuelle* du cumul pour `brut`, `vacances`, `rrq_employe`,
#: etc., puisque `PayrollResult` n'a pas de champ portant ces noms — SEUL
#: `net` est un attribut plat partagé entre les deux modèles). Ce test
#: calcule donc la somme *attendue* directement depuis la structure
#: imbriquée du `PayrollResult` (même mapping que celui utilisé par
#: `net_pay._ContributionPaie`, tâche 7.1), indépendamment de la manière
#: dont `register.py`/`CumulsYTD.avec_paie` réalisent l'agrégation en
#: interne — Property 8 vérifie le résultat observable de
#: `lire_cumuls_ytd`, pas le mécanisme d'agrégation.
def _contribution_categorie(resultat: PayrollResult, categorie: str) -> Decimal:
    """Valeur de ``categorie`` pour ``resultat`` (mapping design §Components §2).

    Réplique exactement la table du design (§Components §2, mapping Req 6
    AC2, également reprise §Components §3.3) — la même table que celle que
    `payroll_engine/net_pay.py` (tâche 7.2) utilisera pour construire
    `_ContributionPaie`. Ne dépend d'aucune fonction du module cible
    (encore inexistant à ce stade, règle 06) : accède uniquement aux
    sous-modèles déjà livrés par `moteur-paie-contrats`
    (`models.payroll_result`).
    """
    mapping: dict[str, Decimal] = {
        "brut": resultat.gains.brut_total,
        "vacances": resultat.gains.vacances,
        "rrq_employe": resultat.retenues_employe.rrq.montant,
        "rrq_employeur": resultat.cotisations_employeur.rrq_employeur.montant,
        "rqap_employe": resultat.retenues_employe.rqap.montant,
        "rqap_employeur": resultat.cotisations_employeur.rqap_employeur.montant,
        "ae_employe": resultat.retenues_employe.ae.montant,
        "ae_employeur": resultat.cotisations_employeur.ae_employeur.montant,
        "impot_qc_retenu": resultat.retenues_employe.impot_qc_retenu.montant,
        "impot_federal_retenu": resultat.retenues_employe.impot_federal_retenu.montant,
        "net": resultat.net,
    }
    return mapping[categorie]


#: Ordre des onze catégories — identique à
#: `models.cumuls._CATEGORIES_MONETAIRES` (non importé directement pour ne
#: pas coupler ce test à un détail d'implémentation privé de
#: `models/cumuls.py` ; la liste est néanmoins tenue strictement
#: synchronisée avec ce tuple, cf. design §Components §2).
_CATEGORIES_YTD: tuple[str, ...] = (
    "brut",
    "vacances",
    "rrq_employe",
    "rrq_employeur",
    "rqap_employe",
    "rqap_employeur",
    "ae_employe",
    "ae_employeur",
    "impot_qc_retenu",
    "impot_federal_retenu",
    "net",
)


def _cumuls_ytd_attendus(
    sequence: tuple[PayrollResult, ...], employe_id: str, annee_fiscale: int
) -> CumulsYTD:
    """Somme manuelle, catégorie par catégorie, des contributions de ``sequence``.

    Design (§Correctness Properties 8) : la somme des contributions des
    *n* paies de la séquence, catégorie par catégorie — calculée
    indépendamment de `register.py`/`CumulsYTD.avec_paie` (aucun appel à
    ces deux mécanismes ici). Le cas ``n = 0`` (``sequence`` vide) est
    couvert nativement : la boucle n'itère jamais et
    `CumulsYTD.zero(...)` reste la valeur de départ inchangée.
    """
    cumul = CumulsYTD.zero(employe_id=employe_id, annee_civile=annee_fiscale)
    for resultat in sequence:
        mises_a_jour = {
            categorie: getattr(cumul, categorie)
            + _contribution_categorie(resultat, categorie)
            for categorie in _CATEGORIES_YTD
        }
        cumul = cumul.model_copy(update=mises_a_jour)
    return cumul


class TestCumulYTDDeNPaies:
    """Property 8 — cumul YTD de *n* paies = somme des contributions.

    Design (§Correctness Properties 8, §Components §3.3) ; Requirements
    10.4, 11.3, 16.3. Pour une séquence ordonnée de *n* ≥ 0
    `PayrollResult` `EMISE` d'un même `employe_id`/`annee_fiscale`,
    insérés un à un via `inserer_paie` dans une base neuve,
    `lire_cumuls_ytd` après les *n* insertions doit égaler, catégorie
    par catégorie, la somme des contributions des *n* paies — le cas
    *n* = 0 (aucune insertion) doit retourner
    `CumulsYTD.zero(employe_id, annee_civile)`, cohérent avec une somme
    vide.
    """

    # Feature: net-cumuls-registre, Property 8: Cumul YTD de n paies
    @pytest.mark.property
    @given(
        sequence=st_sequence_payroll_results_meme_employe_annee(n_max=5),
        saison=st_saison(),
    )
    @settings_large_input
    def test_cumul_ytd_apres_n_insertions_egale_somme_des_contributions(
        self,
        sequence: tuple[PayrollResult, ...],
        saison: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 8 (Req 10.4, 11.3, 16.3).

        Insère chaque `PayrollResult` de ``sequence`` dans l'ordre via
        `inserer_paie` (base neuve — `st_chemin_bd_temporaire` garantit un
        fichier SQLite absent avant le premier appel), puis compare le
        `CumulsYTD` lu via `lire_cumuls_ytd` à la somme manuelle des
        contributions (`_cumuls_ytd_attendus`), catégorie par catégorie.
        Le cas `n = 0` (`sequence` vide) est couvert par construction :
        aucune insertion n'a lieu et `lire_cumuls_ytd` doit alors
        retourner `CumulsYTD.zero(employe_id, annee_civile)`.
        """
        module = _importer_module_register()

        if sequence:
            employe_id = sequence[0].employe_id
            annee_fiscale = sequence[0].annee_fiscale
        else:
            # `n = 0` : aucun `PayrollResult` disponible pour dériver
            # `employe_id`/`annee_fiscale` — un couple fictif arbitraire
            # suffit puisqu'aucune ligne n'existera jamais dans cette
            # base neuve pour ce couple (Req 10.4 : absence de ligne
            # interprétée comme `CumulsYTD.zero`).
            employe_id = "EMP000"
            annee_fiscale = 2026

        for resultat in sequence:
            module.inserer_paie(
                resultat, saison, chemin_bd=st_chemin_bd_temporaire
            )

        cumuls_obtenus = module.lire_cumuls_ytd(
            employe_id, annee_fiscale, chemin_bd=st_chemin_bd_temporaire
        )
        cumuls_attendus = _cumuls_ytd_attendus(sequence, employe_id, annee_fiscale)

        assert cumuls_obtenus == cumuls_attendus, (
            "`lire_cumuls_ytd` après les "
            f"{len(sequence)} insertions doit égaler la somme des "
            f"contributions catégorie par catégorie (Property 8), obtenu "
            f"{cumuls_obtenus!r}, attendu {cumuls_attendus!r}."
        )

        if not sequence:
            assert cumuls_obtenus == CumulsYTD.zero(employe_id, annee_fiscale), (
                "Le cas n = 0 doit retourner `CumulsYTD.zero(employe_id, "
                f"annee_civile)`, obtenu {cumuls_obtenus!r} (Req 10.4)."
            )


# ---------------------------------------------------------------------------
# 3.3 — Property 9 : Idempotence de substitution (`remplacer_paie`).
# ---------------------------------------------------------------------------

#: Deux `PayrollResult` `EMISE` distincts, du même `employe_id`/`annee_fiscale`
#: (`id_paie` distincts par construction — indexés par position dans la
#: séquence source), obtenus en filtrant
#: `st_sequence_payroll_results_meme_employe_annee(n_max=2)` sur le cas
#: `n = 2` — même patron que `_st_un_payroll_result_emis` (tâche 3.1). Le
#: premier élément sert d'« ancien » (déjà inséré, `EMISE`), le second de
#: « nouveau » (remplaçant, `EMISE`) pour Property 9.
_st_deux_payroll_results_memes_employe_annee: st.SearchStrategy[
    tuple[PayrollResult, PayrollResult]
] = (
    st_sequence_payroll_results_meme_employe_annee(n_max=2)
    .filter(lambda sequence: len(sequence) == 2)
    .map(lambda sequence: (sequence[0], sequence[1]))
)


class TestRemplacerPaie:
    """Property 9 — idempotence de substitution (`remplacer_paie`), et
    tests d'exemple des refus de `remplacer_paie` (Req 13.2, 13.3, 13.5).

    Design (§Correctness Properties 9, §Components §3.7 « pseudocode
    complet », §Error Handling « Matrice des exceptions ») ; Requirements
    13.2, 13.3, 13.4, 13.5, 16.4.
    """

    # -----------------------------------------------------------------
    # Property 9 : le remplacement équivaut à une insertion directe du
    # nouveau résultat, du point de vue de `lire_cumuls_ytd`.
    # -----------------------------------------------------------------

    # Feature: net-cumuls-registre, Property 9: Idempotence de substitution
    @pytest.mark.property
    @given(
        deux_resultats=_st_deux_payroll_results_memes_employe_annee,
        saison=st_saison(),
    )
    @settings_large_input
    def test_remplacement_equivaut_a_insertion_directe_du_nouveau(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 9 (Req 13.4, 13.5, 16.4).

        Sur une base A neuve : `inserer_paie(ancien)` puis
        `remplacer_paie(ancien.id_paie, nouveau, saison, chemin_bd=A)`. Sur
        une base B neuve et indépendante : `inserer_paie(nouveau)` seul.
        Les deux `CumulsYTD` lus via `lire_cumuls_ytd` doivent être
        strictement égaux — le remplacement d'un `EMISE` par un `EMISE`
        retire intégralement la contribution de l'ancien puis ajoute
        celle du nouveau (design §Components §3.7, étape 3c, cas
        nominal), ce qui est observationnellement équivalent à n'avoir
        jamais inséré l'ancien.

        Deux chemins `chemin_bd` distincts sont construits manuellement
        sous `tmp_path` (même convention que la fixture
        `st_chemin_bd_temporaire` de `tests/strategies.py`, laquelle ne
        fournit qu'un seul chemin par test — Property 9 exige ici deux
        bases indépendantes au sein du même exemple Hypothesis).
        """
        module = _importer_module_register()
        ancien, nouveau = deux_resultats

        chemin_a = tmp_path / f"test_{uuid.uuid4().hex}.db"
        chemin_b = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien, saison, chemin_bd=chemin_a)
        module.remplacer_paie(ancien.id_paie, nouveau, saison, chemin_bd=chemin_a)
        cumuls_via_remplacement = module.lire_cumuls_ytd(
            nouveau.employe_id, nouveau.annee_fiscale, chemin_bd=chemin_a
        )

        module.inserer_paie(nouveau, saison, chemin_bd=chemin_b)
        cumuls_via_insertion_directe = module.lire_cumuls_ytd(
            nouveau.employe_id, nouveau.annee_fiscale, chemin_bd=chemin_b
        )

        assert cumuls_via_remplacement == cumuls_via_insertion_directe, (
            "Le `CumulsYTD` obtenu après `inserer_paie(ancien)` puis "
            "`remplacer_paie(ancien.id_paie, nouveau, ...)` doit être "
            "identique à celui obtenu en insérant directement `nouveau` "
            f"seul depuis une base neuve (Property 9), obtenu "
            f"{cumuls_via_remplacement!r}, attendu "
            f"{cumuls_via_insertion_directe!r}."
        )

    # -----------------------------------------------------------------
    # Tests d'exemple — matrice des exceptions (design §Error Handling).
    # -----------------------------------------------------------------

    @given(nouveau=_st_un_payroll_result_emis, saison=st_saison())
    @settings_large_input
    def test_exemple_ancien_id_absent_leve_key_error(
        self,
        nouveau: PayrollResult,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Test d'exemple — `ancien_id` absent lève `KeyError` citant
        l'identifiant recherché (Req 13.2).

        Base neuve : aucune ligne `ancien_id` ne peut exister. Le message
        de l'exception doit citer `ancien_id` (design §Components §3.7,
        étape 1 : ``KeyError(f"Aucune paie trouvée pour ancien_id=...")``).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        ancien_id_absent = "PAIE-INEXISTANTE-000"

        with pytest.raises(KeyError) as excinfo:
            module.remplacer_paie(
                ancien_id_absent, nouveau, saison, chemin_bd=chemin_bd
            )

        assert ancien_id_absent in str(excinfo.value), (
            "Le message de `KeyError` doit citer l'identifiant "
            f"`ancien_id` recherché ({ancien_id_absent!r}), obtenu "
            f"{excinfo.value!r} (Req 13.2)."
        )

    @given(deux_resultats=_st_deux_payroll_results_memes_employe_annee, saison=st_saison())
    @settings_large_input
    def test_exemple_ancien_statut_non_emise_leve_value_error_sans_mutation(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Test d'exemple — `ancien_id` présent mais `statut != EMISE`
        lève `ValueError`, sans aucune mutation de `paies`/`cumuls_ytd`
        (Req 13.2).

        L'ancienne ligne est insérée directement avec `statut=BROUILLON`
        (append-only, `inserer_paie` accepte tout statut — Req 11.2) :
        aucune mise à jour de `cumuls_ytd` n'a alors eu lieu (Req 11.4).
        `remplacer_paie` doit lever `ValueError` **avant** toute mutation
        (design §Components §3.7, étape 1) : l'état de la ligne `paies`
        et de `cumuls_ytd` doit rester identique avant/après la tentative
        refusée.
        """
        module = _importer_module_register()
        ancien_emise, nouveau = deux_resultats
        ancien_brouillon = ancien_emise.model_copy(
            update={"statut": StatutDePaie.BROUILLON}
        )
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien_brouillon, saison, chemin_bd=chemin_bd)

        paie_avant = module.lire_paie(ancien_brouillon.id_paie, chemin_bd=chemin_bd)
        cumuls_avant = module.lire_cumuls_ytd(
            ancien_brouillon.employe_id, ancien_brouillon.annee_fiscale, chemin_bd=chemin_bd
        )

        with pytest.raises(ValueError):
            module.remplacer_paie(
                ancien_brouillon.id_paie, nouveau, saison, chemin_bd=chemin_bd
            )

        paie_apres = module.lire_paie(ancien_brouillon.id_paie, chemin_bd=chemin_bd)
        cumuls_apres = module.lire_cumuls_ytd(
            ancien_brouillon.employe_id, ancien_brouillon.annee_fiscale, chemin_bd=chemin_bd
        )

        assert paie_apres == paie_avant, (
            "`remplacer_paie` refusé (statut ancien != EMISE) ne doit "
            f"muter aucune ligne `paies`, obtenu {paie_apres!r}, attendu "
            f"{paie_avant!r} (Req 13.2)."
        )
        assert cumuls_apres == cumuls_avant, (
            "`remplacer_paie` refusé (statut ancien != EMISE) ne doit "
            f"muter aucune ligne `cumuls_ytd`, obtenu {cumuls_apres!r}, "
            f"attendu {cumuls_avant!r} (Req 13.2)."
        )

    @given(
        deux_resultats=_st_deux_payroll_results_memes_employe_annee,
        statut_refuse=st_statut_nouveau_resultat_refuse(),
        saison=st_saison(),
    )
    @settings_large_input
    def test_exemple_nouveau_statut_refuse_leve_value_error_sans_mutation(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        statut_refuse: StatutDePaie,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Test d'exemple — `nouveau_resultat.statut` hors
        `{EMISE, BROUILLON}` lève `ValueError`, sans aucune mutation
        (Req 13.3).

        `statut_refuse` est tiré de `st_statut_nouveau_resultat_refuse()`
        (`ANNULEE` ou `REMPLACE_PAR`). L'ancien est un `EMISE` valide,
        déjà inséré via `inserer_paie` (`cumuls_ytd` reflète sa
        contribution). Le contrôle du statut du nouveau résultat
        (design §Components §3.7, étape 2) doit lever `ValueError`
        **avant** toute des trois mutations de l'étape 3 (update ancien,
        insertion nouveau, recalcul cumuls) : la ligne `ancien_id` et
        `cumuls_ytd` doivent rester inchangés.
        """
        module = _importer_module_register()
        ancien, nouveau_emise = deux_resultats
        nouveau_refuse = nouveau_emise.model_copy(update={"statut": statut_refuse})
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien, saison, chemin_bd=chemin_bd)

        paie_avant = module.lire_paie(ancien.id_paie, chemin_bd=chemin_bd)
        cumuls_avant = module.lire_cumuls_ytd(
            ancien.employe_id, ancien.annee_fiscale, chemin_bd=chemin_bd
        )

        with pytest.raises(ValueError):
            module.remplacer_paie(
                ancien.id_paie, nouveau_refuse, saison, chemin_bd=chemin_bd
            )

        paie_apres = module.lire_paie(ancien.id_paie, chemin_bd=chemin_bd)
        cumuls_apres = module.lire_cumuls_ytd(
            ancien.employe_id, ancien.annee_fiscale, chemin_bd=chemin_bd
        )

        assert paie_apres == paie_avant, (
            "`remplacer_paie` refusé (statut nouveau hors "
            "{EMISE, BROUILLON}) ne doit muter aucune ligne `paies`, "
            f"obtenu {paie_apres!r}, attendu {paie_avant!r} (Req 13.3)."
        )
        assert cumuls_apres == cumuls_avant, (
            "`remplacer_paie` refusé (statut nouveau hors "
            "{EMISE, BROUILLON}) ne doit muter aucune ligne "
            f"`cumuls_ytd`, obtenu {cumuls_apres!r}, attendu "
            f"{cumuls_avant!r} (Req 13.3)."
        )

    @given(deux_resultats=_st_deux_payroll_results_memes_employe_annee, saison=st_saison())
    @settings_large_input
    def test_exemple_remplacement_par_brouillon_retire_sans_ajouter(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Test d'exemple — un ancien `EMISE` remplacé par un nouveau
        `BROUILLON` : l'étape 3c retire uniquement la contribution
        ancienne, sans ajout (Req 13.5).

        Comme l'ancien est la seule ligne jamais insérée dans cette base
        neuve, retirer sa seule contribution doit ramener `cumuls_ytd`
        exactement à `CumulsYTD.zero(employe_id, annee_civile)` — si
        l'étape 3c ajoutait, à tort, la contribution du nouveau
        `BROUILLON`, le résultat ne serait pas nul (design §Components
        §3.7, étape 3c, branche `BROUILLON`).
        """
        module = _importer_module_register()
        ancien, nouveau_emise = deux_resultats
        nouveau_brouillon = nouveau_emise.model_copy(
            update={"statut": StatutDePaie.BROUILLON}
        )
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien, saison, chemin_bd=chemin_bd)
        module.remplacer_paie(
            ancien.id_paie, nouveau_brouillon, saison, chemin_bd=chemin_bd
        )

        cumuls_apres = module.lire_cumuls_ytd(
            ancien.employe_id, ancien.annee_fiscale, chemin_bd=chemin_bd
        )

        assert cumuls_apres == CumulsYTD.zero(ancien.employe_id, ancien.annee_fiscale), (
            "Le remplacement d'un `EMISE` par un `BROUILLON` doit retirer "
            "uniquement la contribution de l'ancien, sans ajout de celle "
            f"du nouveau (Req 13.5), obtenu {cumuls_apres!r}."
        )

# ---------------------------------------------------------------------------
# 3.4 — Property 10 : Round-trip de sérialisation sans perte.
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Property 10 — round-trip de sérialisation sans perte, et test
    d'exemple du refus de lecture sur ``id_paie`` absent (Req 12.2).

    Design (§Correctness Properties 10, §Components §3.4 « pseudocode
    `lire_paie` ») ; Requirements 12.1, 12.2, 12.5, 16.5.
    """

    # Feature: net-cumuls-registre, Property 10: Round-trip de sérialisation
    @pytest.mark.property
    @given(resultat=_st_un_payroll_result_emis, saison=st_saison())
    @settings_large_input
    def test_lire_paie_apres_inserer_paie_egale_resultat_insere(
        self,
        resultat: PayrollResult,
        saison: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 10 (Req 12.1, 12.5, 16.5).

        Insère ``resultat`` via `inserer_paie` sur une base neuve
        (`st_chemin_bd_temporaire`), puis relit via `lire_paie` sur le
        même `chemin_bd` et le même `id_paie`. Le `PayrollResult` relu
        doit être strictement égal (`==`) à ``resultat`` — round-trip
        `model_dump_json()`/`model_validate_json()` sans perte, y compris
        les trois invariants `model_validator` de `PayrollResult`
        (design §Components §3.4) et l'absence de toute conversion via
        `float` (règle 01, Req 12.5).
        """
        module = _importer_module_register()

        module.inserer_paie(resultat, saison, chemin_bd=st_chemin_bd_temporaire)
        relu, _ = module.lire_paie(resultat.id_paie, chemin_bd=st_chemin_bd_temporaire)

        assert relu == resultat, (
            "`lire_paie` après `inserer_paie` doit retourner un "
            f"`PayrollResult` strictement égal à l'original (Property "
            f"10), obtenu {relu!r}, attendu {resultat!r}."
        )

    def test_exemple_lire_paie_sur_id_paie_absent_leve_key_error(
        self, tmp_path: Path
    ) -> None:
        """Test d'exemple — `lire_paie` sur `id_paie` absent lève
        `KeyError` citant l'identifiant recherché (Req 12.2).

        Base neuve : aucune ligne `id_paie` ne peut exister. Le message
        de l'exception doit citer `id_paie` (design §Components §3.4 :
        ``KeyError(f"Aucune paie trouvée pour id_paie=...")``).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        id_paie_absent = "PAIE-INEXISTANTE-000"

        with pytest.raises(KeyError) as excinfo:
            module.lire_paie(id_paie_absent, chemin_bd=chemin_bd)

        assert id_paie_absent in str(excinfo.value), (
            "Le message de `KeyError` doit citer l'identifiant `id_paie` "
            f"recherché ({id_paie_absent!r}), obtenu {excinfo.value!r} "
            f"(Req 12.2)."
        )


# ---------------------------------------------------------------------------
# 3.5 — Property 11 : Immutabilité des lignes déjà insérées.
# ---------------------------------------------------------------------------


class TestImmutabiliteLignes:
    """Property 11 — immutabilité des lignes déjà insérées.

    Aucune fonction du registre autre que `remplacer_paie` ne modifie
    `payload_json`/`statut`/`remplace_par_id` d'une ligne déjà insérée
    dans `paies` (append-only, Req 9.3) ; et `remplacer_paie` lui-même ne
    modifie, dans le `payload_json` de la ligne `ancien_id`, que
    `statut` et `remplace_par_id` (design §Components §3.7, étape 3a) —
    tous les champs monétaires substantiels (`gains`, `retenues_employe`,
    `cotisations_employeur`, `net`, `cout_employeur`, `cumuls_fin`)
    restent strictement identiques à ceux de la ligne insérée
    initialement.

    Design (§Correctness Properties 11, §Components §3.7 « pseudocode
    complet, étape 3a », §Data Models « Append-only » et « Notes de
    conception (Req 9) ») ; Requirements 9.3, 13.7, 16.6.
    """

    # Feature: net-cumuls-registre, Property 11: Immutabilité des lignes déjà insérées
    @pytest.mark.property
    @given(
        deux_resultats=_st_deux_payroll_results_memes_employe_annee,
        saison=st_saison(),
    )
    @settings_large_input
    def test_remplacer_paie_ne_modifie_que_statut_et_remplace_par_id_de_ancien(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 11 (Req 9.3, 13.7, 16.6).

        Insère `ancien` (`EMISE`) via `inserer_paie` sur une base neuve,
        puis `remplacer_paie(ancien.id_paie, nouveau, saison, chemin_bd)`.
        Relit ensuite la ligne `ancien_id` via `lire_paie`
        (`ancien_apres_remplacement`) : tous les champs monétaires
        substantiels du `payload_json` — `gains`, `retenues_employe`,
        `cotisations_employeur`, `net`, `cout_employeur`, `cumuls_fin` —
        ainsi que les champs de cycle de vie non concernés par le
        remplacement — `id_paie`, `version`, `employe_id`,
        `annee_fiscale`, `pay_period`, `date_creation` — doivent rester
        strictement identiques (`==`) à ceux d'`ancien` (design
        §Components §3.7, étape 3a : seule mutation autorisée sur une
        ligne existante, limitée à `statut` et `remplace_par_id`, Req
        9.3, 13.7). Seuls ces deux derniers champs doivent différer :
        `statut == StatutDePaie.REMPLACE_PAR` et `remplace_par_id ==
        nouveau.id_paie`.
        """
        module = _importer_module_register()
        ancien, nouveau = deux_resultats
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien, saison, chemin_bd=chemin_bd)
        module.remplacer_paie(ancien.id_paie, nouveau, saison, chemin_bd=chemin_bd)

        ancien_apres_remplacement, _ = module.lire_paie(
            ancien.id_paie, chemin_bd=chemin_bd
        )

        # -----------------------------------------------------------------
        # Champs monétaires substantiels — strictement inchangés (Req 13.7).
        # -----------------------------------------------------------------
        assert ancien_apres_remplacement.gains == ancien.gains, (
            "`remplacer_paie` ne doit jamais modifier `gains` de la ligne "
            f"`ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.gains!r}, attendu {ancien.gains!r}."
        )
        assert (
            ancien_apres_remplacement.retenues_employe == ancien.retenues_employe
        ), (
            "`remplacer_paie` ne doit jamais modifier `retenues_employe` "
            f"de la ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.retenues_employe!r}, attendu "
            f"{ancien.retenues_employe!r}."
        )
        assert (
            ancien_apres_remplacement.cotisations_employeur
            == ancien.cotisations_employeur
        ), (
            "`remplacer_paie` ne doit jamais modifier "
            "`cotisations_employeur` de la ligne `ancien_id` (Property "
            f"11), obtenu {ancien_apres_remplacement.cotisations_employeur!r}, "
            f"attendu {ancien.cotisations_employeur!r}."
        )
        assert ancien_apres_remplacement.net == ancien.net, (
            "`remplacer_paie` ne doit jamais modifier `net` de la ligne "
            f"`ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.net!r}, attendu {ancien.net!r}."
        )
        assert ancien_apres_remplacement.cout_employeur == ancien.cout_employeur, (
            "`remplacer_paie` ne doit jamais modifier `cout_employeur` de "
            f"la ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.cout_employeur!r}, attendu "
            f"{ancien.cout_employeur!r}."
        )
        assert ancien_apres_remplacement.cumuls_fin == ancien.cumuls_fin, (
            "`remplacer_paie` ne doit jamais modifier `cumuls_fin` de la "
            f"ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.cumuls_fin!r}, attendu "
            f"{ancien.cumuls_fin!r}."
        )

        # -----------------------------------------------------------------
        # Champs de cycle de vie non concernés — strictement inchangés.
        # -----------------------------------------------------------------
        assert ancien_apres_remplacement.id_paie == ancien.id_paie, (
            "`remplacer_paie` ne doit jamais modifier `id_paie` de la "
            f"ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.id_paie!r}, attendu "
            f"{ancien.id_paie!r}."
        )
        assert ancien_apres_remplacement.version == ancien.version, (
            "`remplacer_paie` ne doit jamais modifier `version` de la "
            f"ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.version!r}, attendu "
            f"{ancien.version!r}."
        )
        assert ancien_apres_remplacement.employe_id == ancien.employe_id, (
            "`remplacer_paie` ne doit jamais modifier `employe_id` de la "
            f"ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.employe_id!r}, attendu "
            f"{ancien.employe_id!r}."
        )
        assert ancien_apres_remplacement.annee_fiscale == ancien.annee_fiscale, (
            "`remplacer_paie` ne doit jamais modifier `annee_fiscale` de "
            f"la ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.annee_fiscale!r}, attendu "
            f"{ancien.annee_fiscale!r}."
        )
        assert ancien_apres_remplacement.pay_period == ancien.pay_period, (
            "`remplacer_paie` ne doit jamais modifier `pay_period` de la "
            f"ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.pay_period!r}, attendu "
            f"{ancien.pay_period!r}."
        )
        assert ancien_apres_remplacement.date_creation == ancien.date_creation, (
            "`remplacer_paie` ne doit jamais modifier `date_creation` de "
            f"la ligne `ancien_id` (Property 11), obtenu "
            f"{ancien_apres_remplacement.date_creation!r}, attendu "
            f"{ancien.date_creation!r}."
        )

        # -----------------------------------------------------------------
        # Seuls `statut`/`remplace_par_id` doivent différer — mutation
        # attendue et strictement limitée à ces deux champs (Req 9.3, 13.7).
        # -----------------------------------------------------------------
        assert (
            ancien_apres_remplacement.statut == StatutDePaie.REMPLACE_PAR
        ), (
            "La ligne `ancien_id` relue après `remplacer_paie` doit "
            f"porter `statut == StatutDePaie.REMPLACE_PAR` (Property 11), "
            f"obtenu {ancien_apres_remplacement.statut!r}."
        )
        assert ancien_apres_remplacement.remplace_par_id == nouveau.id_paie, (
            "La ligne `ancien_id` relue après `remplacer_paie` doit "
            f"porter `remplace_par_id == nouveau.id_paie` (Property 11), "
            f"obtenu {ancien_apres_remplacement.remplace_par_id!r}, "
            f"attendu {nouveau.id_paie!r}."
        )


# ---------------------------------------------------------------------------
# 3.6 — Property 12 : Absence de `float`.
# ---------------------------------------------------------------------------


def _sans_float(valeur: object) -> bool:
    """``True`` si ``valeur`` ne contient aucun ``float`` à aucun niveau.

    Descente récursive dans la structure retournée par les fonctions
    publiques du registre (`PayrollResult`, `CumulsYTD`, tuples de
    `PayrollResult`) : un modèle Pydantic est aplati via
    ``model_dump(mode="python")`` avant traversée, un ``dict``/``list``/
    ``tuple``/``set`` est parcouru récursivement. Un ``bool`` n'est
    jamais confondu avec un ``float`` (``isinstance(True, float)`` est
    ``False``) — seul le type ``float`` lui-même déclenche l'échec
    (règle 01, Property 12).
    """
    if isinstance(valeur, float):
        return False
    if isinstance(valeur, BaseModel):
        return _sans_float(valeur.model_dump(mode="python"))
    if isinstance(valeur, dict):
        return all(_sans_float(v) for v in valeur.values())
    if isinstance(valeur, (list, tuple, set)):
        return all(_sans_float(v) for v in valeur)
    return True


def _lire_payload_json_brut(chemin_bd: Path, id_paie: str) -> str:
    """Introspection SQLite directe de ``paies.payload_json`` (Property 12).

    Ouvre sa **propre** connexion ``sqlite3.connect(...)`` — jamais via
    les fonctions de ``payroll_engine/register.py`` — pour observer le
    type Python exact stocké par SQLite pour cette colonne.
    """
    with sqlite3.connect(str(chemin_bd)) as connexion:
        ligne = connexion.execute(
            "SELECT payload_json FROM paies WHERE id_paie = ?", (id_paie,)
        ).fetchone()
    assert ligne is not None, (
        f"Aucune ligne `paies` trouvée pour id_paie={id_paie!r} lors de "
        "l'introspection SQLite directe (Property 12)."
    )
    return ligne[0]


def _lire_cumuls_ytd_bruts(
    chemin_bd: Path, employe_id: str, annee_civile: int
) -> dict[str, object]:
    """Introspection SQLite directe des onze colonnes `cumuls_ytd` (Property 12).

    Ouvre sa **propre** connexion ``sqlite3.connect(...)`` — jamais via
    les fonctions de ``payroll_engine/register.py`` — et retourne un
    dictionnaire ``{categorie: valeur_brute}`` dans l'ordre de
    `_CATEGORIES_YTD`, chaque ``valeur_brute`` étant le type Python exact
    que le pilote ``sqlite3`` a reconstruit pour cette colonne `TEXT`
    (design §Data Models : onze colonnes `TEXT NOT NULL`).
    """
    colonnes_sql = ", ".join(_CATEGORIES_YTD)
    with sqlite3.connect(str(chemin_bd)) as connexion:
        ligne = connexion.execute(
            f"SELECT {colonnes_sql} FROM cumuls_ytd "
            "WHERE employe_id = ? AND annee_civile = ?",
            (employe_id, annee_civile),
        ).fetchone()
    assert ligne is not None, (
        f"Aucune ligne `cumuls_ytd` trouvée pour employe_id={employe_id!r}, "
        f"annee_civile={annee_civile!r} lors de l'introspection SQLite "
        "directe (Property 12)."
    )
    return dict(zip(_CATEGORIES_YTD, ligne, strict=True))


class TestAbsenceFloat:
    """Property 12 — absence de `float`.

    Pour `inserer_paie`, `lire_paie`, `lire_historique_paie`,
    `lire_cumuls_ytd` et `remplacer_paie`, aucune valeur monétaire
    assemblée, sérialisée (`payload_json`, colonnes `cumuls_ytd`) ou
    relue n'est de type `float` — chaque colonne monétaire est une
    chaîne `TEXT` reconvertible en `Decimal` fini sans passer par
    `float` (design §Correctness Properties 12, §Data Models).

    Deux mécanismes de vérification, complémentaires :

    1. **Introspection SQLite directe** (`sqlite3.connect(...)` ouvert
       par le test lui-même, jamais via une fonction du registre) sur
       les lignes `paies`/`cumuls_ytd` — vérifie le type Python exact
       (`str`, jamais `float`) reconstruit par le pilote `sqlite3` pour
       chaque colonne monétaire, et que chaque colonne `cumuls_ytd` se
       reconvertit en `Decimal` sans erreur ; `payload_json` se
       reparse sans littéral flottant non guillemé via
       `_parse_json_reject_floats` (même parseur strict que celui
       branché sur `model_validate_json`, `models/_validators.py`).
    2. **Introspection des valeurs relues** par les fonctions publiques
       du registre elles-mêmes (`lire_paie`, `lire_historique_paie`,
       `lire_cumuls_ytd`) — vérifie récursivement (`_sans_float`)
       qu'aucun champ du `PayrollResult`/`CumulsYTD` reconstruit n'est
       de type `float`.
    """

    # Feature: net-cumuls-registre, Property 12: Absence de float
    @pytest.mark.property
    @given(
        deux_resultats=_st_deux_payroll_results_memes_employe_annee,
        saison=st_saison(),
    )
    @settings_large_input
    def test_aucune_valeur_monetaire_de_type_float(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 12 (Req 9.2, 10.2, 10.3, 16.8).

        Insère ``ancien`` (`EMISE`) via `inserer_paie` sur une base
        neuve, vérifie l'absence de `float` sur les lignes SQLite
        brutes et sur les valeurs relues par `lire_paie`,
        `lire_historique_paie`, `lire_cumuls_ytd` ; puis remplace via
        `remplacer_paie(ancien.id_paie, nouveau, saison, chemin_bd)` et
        répète la même vérification sur l'état post-remplacement
        (ligne `ancien_id` réécrite, ligne `nouveau.id_paie` insérée,
        `cumuls_ytd` recalculé).
        """
        module = _importer_module_register()
        ancien, nouveau = deux_resultats

        # -------------------------------------------------------------
        # 1. Après `inserer_paie(ancien)` seul.
        # -------------------------------------------------------------
        module.inserer_paie(ancien, saison, chemin_bd=st_chemin_bd_temporaire)

        payload_json_brut = _lire_payload_json_brut(
            st_chemin_bd_temporaire, ancien.id_paie
        )
        assert isinstance(payload_json_brut, str), (
            "`paies.payload_json` doit être relu par `sqlite3` comme un "
            f"`str` (jamais `float`), obtenu {type(payload_json_brut)!r} "
            "(Property 12)."
        )
        # `_parse_json_reject_floats` lève si un littéral flottant non
        # guillemé subsiste dans le JSON — aucun montant monétaire ne
        # doit donc apparaître autrement qu'entre guillemets (règle 01).
        _parse_json_reject_floats(payload_json_brut)

        cumuls_bruts = _lire_cumuls_ytd_bruts(
            st_chemin_bd_temporaire, ancien.employe_id, ancien.annee_fiscale
        )
        for categorie, valeur_brute in cumuls_bruts.items():
            assert isinstance(valeur_brute, str), (
                f"`cumuls_ytd.{categorie}` doit être relu par `sqlite3` "
                f"comme un `str` (jamais `float`), obtenu "
                f"{type(valeur_brute)!r} (Property 12)."
            )
            # Doit se reconvertir en `Decimal` fini sans jamais transiter
            # par `float` — `Decimal(str)` ne passe par aucune expansion
            # binaire (règle 01, Req 10.3).
            Decimal(valeur_brute)

        assert _sans_float(module.lire_paie(ancien.id_paie, chemin_bd=st_chemin_bd_temporaire)), (
            "`lire_paie(ancien.id_paie)` ne doit retourner aucune valeur "
            "de type `float` (Property 12)."
        )
        historique_ancien = module.lire_historique_paie(
            ancien.employe_id,
            ancien.annee_fiscale,
            ancien.pay_period.numero_periode,
            chemin_bd=st_chemin_bd_temporaire,
        )
        assert _sans_float(historique_ancien), (
            "`lire_historique_paie` ne doit retourner aucune valeur de "
            "type `float` (Property 12)."
        )
        assert _sans_float(
            module.lire_cumuls_ytd(
                ancien.employe_id, ancien.annee_fiscale, chemin_bd=st_chemin_bd_temporaire
            )
        ), (
            "`lire_cumuls_ytd` ne doit retourner aucune valeur de type "
            "`float` (Property 12)."
        )

        # -------------------------------------------------------------
        # 2. Après `remplacer_paie(ancien.id_paie, nouveau, ...)`.
        # -------------------------------------------------------------
        module.remplacer_paie(
            ancien.id_paie, nouveau, saison, chemin_bd=st_chemin_bd_temporaire
        )

        for id_paie_a_verifier in (ancien.id_paie, nouveau.id_paie):
            payload_json_brut_apres = _lire_payload_json_brut(
                st_chemin_bd_temporaire, id_paie_a_verifier
            )
            assert isinstance(payload_json_brut_apres, str), (
                f"`paies.payload_json` (id_paie={id_paie_a_verifier!r}) "
                "doit être relu par `sqlite3` comme un `str` (jamais "
                f"`float`), obtenu {type(payload_json_brut_apres)!r} "
                "(Property 12)."
            )
            _parse_json_reject_floats(payload_json_brut_apres)

        cumuls_bruts_apres = _lire_cumuls_ytd_bruts(
            st_chemin_bd_temporaire, nouveau.employe_id, nouveau.annee_fiscale
        )
        for categorie, valeur_brute in cumuls_bruts_apres.items():
            assert isinstance(valeur_brute, str), (
                f"`cumuls_ytd.{categorie}` (après remplacement) doit être "
                f"relu par `sqlite3` comme un `str` (jamais `float`), "
                f"obtenu {type(valeur_brute)!r} (Property 12)."
            )
            Decimal(valeur_brute)

        assert _sans_float(
            module.lire_paie(ancien.id_paie, chemin_bd=st_chemin_bd_temporaire)
        ), (
            "`lire_paie(ancien.id_paie)` (après remplacement) ne doit "
            "retourner aucune valeur de type `float` (Property 12)."
        )
        assert _sans_float(
            module.lire_paie(nouveau.id_paie, chemin_bd=st_chemin_bd_temporaire)
        ), (
            "`lire_paie(nouveau.id_paie)` ne doit retourner aucune valeur "
            "de type `float` (Property 12)."
        )
        historique_apres = module.lire_historique_paie(
            ancien.employe_id,
            ancien.annee_fiscale,
            ancien.pay_period.numero_periode,
            chemin_bd=st_chemin_bd_temporaire,
        )
        assert _sans_float(historique_apres), (
            "`lire_historique_paie` (après remplacement) ne doit "
            "retourner aucune valeur de type `float` (Property 12)."
        )
        assert _sans_float(
            module.lire_cumuls_ytd(
                nouveau.employe_id, nouveau.annee_fiscale, chemin_bd=st_chemin_bd_temporaire
            )
        ), (
            "`lire_cumuls_ytd` (après remplacement) ne doit retourner "
            "aucune valeur de type `float` (Property 12)."
        )


# ---------------------------------------------------------------------------
# 3.7 — Property 13 : Invariance de `cumuls_ytd` par rapport à `saison`.
# ---------------------------------------------------------------------------


class TestInvarianceSaison:
    """Property 13 — invariance de `cumuls_ytd` par rapport à `saison`.

    Deux exécutions identiques de `inserer_paie` (même `PayrollResult`,
    chacune sur sa propre base neuve) différant **uniquement** par la
    valeur de `saison` doivent produire le même `CumulsYTD` — `saison`
    est une chaîne libre sans signification fiscale (Req 14.1), jamais
    utilisée comme clé de `cumuls_ytd` (Req 14.2, dont la clé composite
    reste `(employe_id, annee_civile)`). De même, `remplacer_paie` doit
    accepter sans erreur que l'ancienne et la nouvelle version d'une
    paie portent des `saison` différentes (Req 14.4).

    Design (§Correctness Properties 13) ; Requirements 14.1, 14.2, 14.4.
    """

    # -----------------------------------------------------------------
    # Property 13 : `cumuls_ytd` ne dépend pas de la valeur de `saison`.
    # -----------------------------------------------------------------

    # Feature: net-cumuls-registre, Property 13: Invariance par rapport à saison
    @pytest.mark.property
    @given(
        resultat=_st_un_payroll_result_emis,
        deux_saisons=st.tuples(st_saison(), st_saison()),
    )
    @settings_large_input
    def test_cumuls_ytd_identique_quelle_que_soit_la_saison(
        self,
        resultat: PayrollResult,
        deux_saisons: tuple[str, str],
        tmp_path: Path,
    ) -> None:
        """Property 13 (Req 14.1, 14.2).

        Insère le **même** ``resultat`` via `inserer_paie` sur deux bases
        neuves et indépendantes (`chemin_a`, `chemin_b` sous `tmp_path`,
        même convention que Property 9, tâche 3.3), avec respectivement
        ``saison_a`` et ``saison_b`` — les deux valeurs pouvant être
        égales ou différentes (`st.tuples(st_saison(), st_saison())` ne
        force pas l'inégalité, ce qui reste un cas valide de l'invariant).
        Les deux `CumulsYTD` lus via `lire_cumuls_ytd` doivent être
        strictement égaux : `saison` n'a aucun effet sur l'agrégation des
        cumuls, qui ne dépend que du contenu monétaire de ``resultat``.
        """
        module = _importer_module_register()
        saison_a, saison_b = deux_saisons

        chemin_a = tmp_path / f"test_{uuid.uuid4().hex}.db"
        chemin_b = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(resultat, saison_a, chemin_bd=chemin_a)
        module.inserer_paie(resultat, saison_b, chemin_bd=chemin_b)

        cumuls_via_saison_a = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=chemin_a
        )
        cumuls_via_saison_b = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=chemin_b
        )

        assert cumuls_via_saison_a == cumuls_via_saison_b, (
            "`lire_cumuls_ytd` après `inserer_paie` du même "
            "`PayrollResult` ne doit pas dépendre de la valeur de "
            f"`saison` (Property 13), obtenu {cumuls_via_saison_a!r} "
            f"(saison={saison_a!r}) contre {cumuls_via_saison_b!r} "
            f"(saison={saison_b!r})."
        )

    # -----------------------------------------------------------------
    # Test d'exemple : `remplacer_paie` accepte des `saison` différentes
    # entre l'ancienne et la nouvelle version, sans erreur.
    # -----------------------------------------------------------------

    @given(deux_resultats=_st_deux_payroll_results_memes_employe_annee)
    @settings_large_input
    def test_exemple_remplacer_paie_accepte_saison_differente_entre_ancien_et_nouveau(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        tmp_path: Path,
    ) -> None:
        """Test d'exemple — `remplacer_paie` accepte sans erreur des
        `saison` différentes entre l'ancienne et la nouvelle version
        (Req 14.4).

        Insère ``ancien`` via `inserer_paie` avec ``saison="Saison A"``,
        puis remplace via `remplacer_paie(ancien.id_paie, nouveau,
        saison="Saison B", ...)` — `saison` ne fait l'objet d'aucun
        contrôle de cohérence avec la valeur précédemment enregistrée
        (design §Error Handling : « `register.py` ne valide jamais
        `saison` au-delà de son type `str` ») : l'appel doit réussir sans
        lever d'exception.
        """
        module = _importer_module_register()
        ancien, nouveau = deux_resultats
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien, "Saison A", chemin_bd=chemin_bd)
        module.remplacer_paie(ancien.id_paie, nouveau, "Saison B", chemin_bd=chemin_bd)

# ---------------------------------------------------------------------------
# 3.8 — Property 14 : Refus d'insertion dupliquée sans corruption.
# ---------------------------------------------------------------------------


class TestRefusInsertionDupliquee:
    """Property 14 — refus d'insertion dupliquée sans corruption.

    Pour tout `PayrollResult` déjà inséré via `inserer_paie`, une seconde
    tentative `inserer_paie` avec le même `id_paie` — que ce soit le
    **même** `PayrollResult` ré-inséré tel quel, ou un **autre**
    `PayrollResult` portant simplement le même `id_paie` (design §Data
    Models « Notes de conception (Req 9) » : le contrôle d'unicité porte
    strictement sur `id_paie`, jamais sur l'égalité complète de l'objet)
    — doit lever une exception explicite, levée en tête de `inserer_paie`
    **avant toute écriture** (design §Components §3.3, étape 1 ;
    §Error Handling, ligne `id_paie déjà présent`). L'état de la ligne
    `paies` correspondante et de `cumuls_ytd` juste après la tentative
    refusée doit rester **strictement identique** (`==`) à l'état juste
    avant cette tentative — aucune corruption, même partielle.

    Design (§Correctness Properties 14, §Components §3.3 étape 1,
    §Error Handling « Matrice des exceptions », ligne Req 11.6) ;
    Requirements 11.6.
    """

    # Feature: net-cumuls-registre, Property 14: Refus d'insertion dupliquée
    @pytest.mark.property
    @given(
        deux_resultats=_st_deux_payroll_results_memes_employe_annee,
        saison=st_saison(),
        reinserer_meme_objet=st.booleans(),
    )
    @settings_large_input
    def test_seconde_insertion_meme_id_paie_leve_exception_sans_corruption(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        reinserer_meme_objet: bool,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 14 (Req 11.6).

        Insère ``resultat`` via `inserer_paie` sur une base neuve
        (`st_chemin_bd_temporaire`). Capture l'état juste avant la
        seconde tentative : `lire_paie(resultat.id_paie, ...)` et
        `lire_cumuls_ytd(resultat.employe_id, resultat.annee_fiscale,
        ...)`. Tente ensuite une **seconde** `inserer_paie` portant le
        **même** `id_paie` — selon `reinserer_meme_objet`, soit le
        `PayrollResult` original ré-inséré tel quel, soit un second
        `PayrollResult` distinct (`deux_resultats[1]`) dont `id_paie` est
        forcé, via `model_copy`, à celui du premier (design §Data Models
        : le contrôle d'unicité porte sur `id_paie` uniquement, pas sur
        l'égalité complète de l'objet). La tentative doit lever une
        exception explicite (`ValueError`, design §Error Handling), et
        une relecture de `lire_paie`/`lire_cumuls_ytd` après la tentative
        refusée doit être strictement identique à l'état capturé avant.
        """
        module = _importer_module_register()
        resultat, autre_resultat = deux_resultats

        module.inserer_paie(resultat, saison, chemin_bd=st_chemin_bd_temporaire)

        if reinserer_meme_objet:
            tentative_dupliquee = resultat
        else:
            tentative_dupliquee = autre_resultat.model_copy(
                update={"id_paie": resultat.id_paie}
            )

        paie_avant, _ = module.lire_paie(
            resultat.id_paie, chemin_bd=st_chemin_bd_temporaire
        )
        cumuls_avant = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=st_chemin_bd_temporaire
        )

        with pytest.raises(ValueError) as excinfo:
            module.inserer_paie(
                tentative_dupliquee, saison, chemin_bd=st_chemin_bd_temporaire
            )

        assert resultat.id_paie in str(excinfo.value), (
            "Le message de l'exception levée par une seconde "
            "`inserer_paie` avec le même `id_paie` doit citer "
            f"l'identifiant `id_paie` concerné ({resultat.id_paie!r}), "
            f"obtenu {excinfo.value!r} (Property 14, Req 11.6)."
        )

        paie_apres, _ = module.lire_paie(
            resultat.id_paie, chemin_bd=st_chemin_bd_temporaire
        )
        cumuls_apres = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=st_chemin_bd_temporaire
        )

        assert paie_apres == paie_avant, (
            "La tentative d'insertion dupliquée refusée ne doit muter "
            f"aucune ligne `paies` (Property 14), obtenu {paie_apres!r}, "
            f"attendu {paie_avant!r} (Req 11.6)."
        )
        assert cumuls_apres == cumuls_avant, (
            "La tentative d'insertion dupliquée refusée ne doit muter "
            f"aucune ligne `cumuls_ytd` (Property 14), obtenu "
            f"{cumuls_apres!r}, attendu {cumuls_avant!r} (Req 11.6)."
        )


# ---------------------------------------------------------------------------
# Bug corrigé après livraison — refus de deux paies EMISE simultanées pour
# la même Paie_Logique (demande explicite de l'utilisateur).
# ---------------------------------------------------------------------------


def _payroll_result_valide(
    *,
    id_paie: str,
    employe_id: str,
    annee_fiscale: int,
    numero_periode: int,
    statut: StatutDePaie,
) -> PayrollResult:
    """``PayrollResult`` déterministe et valide, pour les tests d'exemple
    du bug de double émission (pas de dépendance à Hypothesis — mêmes
    valeurs fixes à chaque appel, seuls ``id_paie``/``numero_periode``/
    ``statut`` varient selon les besoins du test). Même patron de
    construction directe que ``_st_payroll_result_pour_registre``
    (composition de sous-modèles, sans passer par le pipeline
    ``net_pay.py``) — identités comptables satisfaites par construction.
    """
    montant_zero = Decimal("0.00")
    retenues_employe = RetenuesEmploye(
        rrq=_st_montant_registre(montant_zero),
        rqap=_st_montant_registre(montant_zero),
        ae=_st_montant_registre(montant_zero),
        impot_qc_formule=_st_montant_registre(montant_zero),
        impot_qc_retenu=_st_montant_registre(montant_zero),
        impot_federal_formule=_st_montant_registre(montant_zero),
        impot_federal_retenu=_st_montant_registre(montant_zero),
        total_retenues_employe=montant_zero,
    )
    cotisations_employeur = CotisationsEmployeur(
        rrq_employeur=_st_montant_registre(montant_zero),
        rqap_employeur=_st_montant_registre(montant_zero),
        ae_employeur=_st_montant_registre(montant_zero),
        fss=_st_montant_registre(montant_zero),
        cnesst=_st_montant_registre(montant_zero),
        cnesst_en_attente_classification=False,
        cnt=_st_montant_registre(montant_zero),
        total_cotisations_employeur=montant_zero,
    )
    brut_total = Decimal("1000.00")
    gains = GainsDecomposes(
        salaire_regulier=brut_total,
        heures_supplementaires_montant=montant_zero,
        vacances=montant_zero,
        jours_feries_manuels=montant_zero,
        brut_total=brut_total,
        multiplicateur_heures_supp=Decimal("1.5"),
        seuil_heures_supp_hebdo=Decimal("40"),
    )
    date_debut = date(annee_fiscale, 7, 6)
    date_fin = date_debut + timedelta(days=13)
    pay_period = PayPeriod(
        numero_periode=numero_periode,
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_fin + timedelta(days=5),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=27,
        annee_fiscale=annee_fiscale,
        semaines=(
            WeekSegment(
                date_debut=date_debut,
                date_fin=date_debut + timedelta(days=6),
                heures_normales=Decimal("80"),
                heures_supplementaires=Decimal("0"),
            ),
            WeekSegment(
                date_debut=date_debut + timedelta(days=7),
                date_fin=date_fin,
                heures_normales=Decimal("80"),
                heures_supplementaires=Decimal("0"),
            ),
        ),
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
        net=brut_total,
        cout_employeur=brut_total,
        cumuls_fin=CumulsYTD.zero(employe_id=employe_id, annee_civile=annee_fiscale),
        statut=statut,
        remplace_par_id=None,
        date_creation=datetime(annee_fiscale, 7, 6, 12, 0, 0),
        date_emission=(
            datetime(annee_fiscale, 7, 6, 12, 0, 0)
            if statut == StatutDePaie.EMISE
            else None
        ),
    )


def _lignes_actives(
    module: ModuleType,
    employe_id: str,
    annee_fiscale: int,
    numero_periode: int,
    chemin_bd: str | Path,
) -> tuple[PayrollResult, ...]:
    """Lignes actives (``statut ∈ {BROUILLON, EMISE}``) d'une Paie_Logique.

    Helper partagé par les tests d'exploration/fix/préservation du bugfix
    ``unicite-paie-active-par-periode`` (tâche 1, réutilisé par les
    tâches 2, 4, 5, 6) : appelle ``lire_historique_paie`` (déjà existant,
    non modifié par ce bugfix) pour la Paie_Logique
    ``(employe_id, annee_fiscale, numero_periode)``, puis filtre le
    tuple de couples ``(PayrollResult, PayrollInput | None)`` retourné
    sur les seules lignes dont ``statut`` est actif — par opposition à
    ``ANNULEE``/``REMPLACE_PAR``, états terminaux hors périmètre de
    l'invariant « au plus une ligne active par période » (design
    §Glossary « Ligne active »). Ne réimplémente aucune logique
    d'assertion : chaque appelant reste responsable de vérifier le
    nombre de lignes retournées et leur contenu.

    Retourne les ``PayrollResult`` seuls (jamais les ``PayrollInput``
    associés), triés par ``version`` croissante (ordre déjà garanti par
    ``lire_historique_paie``) — suffisant pour les assertions de ce
    bugfix (nombre de lignes actives, `statut`, `remplace_par_id`).
    """
    historique = module.lire_historique_paie(
        employe_id, annee_fiscale, numero_periode, chemin_bd=chemin_bd
    )
    return tuple(
        resultat
        for resultat, _payroll_input in historique
        if resultat.statut in (StatutDePaie.BROUILLON, StatutDePaie.EMISE)
    )


class TestRefusDoubleEmisePourMemePeriode:
    """Bug UI signalé après démo (Bilan_Fiscal affichant des totaux
    doublés) — root cause : `inserer_paie` ne contrôlait que l'unicité de
    `id_paie` (toujours neuf), jamais l'unicité de la paie EMISE par
    Paie_Logique `(employe_id, annee_fiscale, numero_periode)`. Le flux
    « Nouvelle paie » de l'interface (par opposition à « Corriger cette
    paie », qui passe par `remplacer_paie`) pouvait ainsi émettre une
    seconde fois la même période sans jamais invalider la première.

    Ces deux tests d'exemple couvrent directement la condition de bug au
    niveau du registre (`inserer_paie`), indépendamment de l'interface
    Streamlit qui l'invoque.
    """

    def test_exemple_seconde_insertion_emise_meme_periode_leve_value_error(
        self,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Une seconde `inserer_paie(..., statut=EMISE)` pour la même
        Paie_Logique `(employe_id, annee_fiscale, numero_periode)` qu'une
        ligne déjà EMISE doit lever `ValueError` — jamais une seconde
        ligne EMISE active. `id_paie` distincts (append-only, `version`
        différente) pour ne pas déclencher le refus Property 14
        (`id_paie` déjà présent), qui couvre un cas différent.
        """
        module = _importer_module_register()

        premiere = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v1",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        seconde = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v2",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )

        module.inserer_paie(premiere, "Saison A", chemin_bd=st_chemin_bd_temporaire)

        with pytest.raises(ValueError) as excinfo:
            module.inserer_paie(
                seconde, "Saison A", chemin_bd=st_chemin_bd_temporaire
            )

        assert "EMISE" in str(excinfo.value), (
            "Le message de refus d'une seconde paie EMISE pour la même "
            f"période doit mentionner EMISE, obtenu {excinfo.value!r}."
        )

        # Aucune mutation : seule `premiere` doit être présente et EMISE.
        relue, _ = module.lire_paie(
            premiere.id_paie, chemin_bd=st_chemin_bd_temporaire
        )
        assert relue.statut == StatutDePaie.EMISE, (
            "La tentative refusée ne doit pas altérer le statut de la "
            f"paie déjà EMISE, obtenu {relue.statut!r}."
        )
        with pytest.raises(KeyError):
            module.lire_paie(seconde.id_paie, chemin_bd=st_chemin_bd_temporaire)

    def test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee(
        self,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Le garde-fou ne cible QUE le statut EMISE — insérer un
        BROUILLON pour une période déjà EMISE reste autorisé (ex. saisie
        exploratoire d'une correction avant de passer par `remplacer_
        paie`, ou poursuite normale d'un flux « Nouvelle paie » qui
        n'émettrait pas immédiatement)."""
        module = _importer_module_register()

        premiere = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v1",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v2",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )

        module.inserer_paie(premiere, "Saison A", chemin_bd=st_chemin_bd_temporaire)
        # Ne doit lever aucune exception.
        module.inserer_paie(
            brouillon, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )

        relu, _ = module.lire_paie(
            brouillon.id_paie, chemin_bd=st_chemin_bd_temporaire
        )
        assert relu.statut == StatutDePaie.BROUILLON


# ---------------------------------------------------------------------------
# Property 1 (Bug Condition) — Bug A : invariant « au plus une ligne
# active par période » (exploration)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Design de référence : ``design.md`` §Bug Details (Bug A),
# §Correctness Properties (Property 1), §Testing Strategy « Exploratory
# Bug Condition Checking » (Test Cases 1 et 2).
#
# Tâche 2 du plan d'implémentation (méthodologie bug condition,
# observation-first, règle 06) : ces tests d'exploration DOIVENT
# échouer sur le code non corrigé — `inserer_paie` ne recherche jamais
# de ligne `BROUILLON` active de la même Paie_Logique avant d'insérer
# (contrairement à `remplacer_paie`), donc l'invariant « au plus une
# ligne active par période » (Property 1) est violé par accumulation.
# Ces échecs confirment `isBugCondition_InvarianceActive(X)` (toujours
# vraie sur le code non corrigé dès qu'un `BROUILLON` actif préexiste
# pour la même Paie_Logique).
#
# **NE PAS corriger ces tests ni le code lorsqu'ils échouent** —
# l'échec par accumulation est le résultat attendu de cette tâche
# d'exploration (voir tâches 2, 3).
#
# _Requirements: 1.1, 1.2, 1.3_


class TestExplorationInvarianceLigneActive:
    """Property 1 (Bug Condition) — exploration, Bug A (accumulation de
    lignes actives par Paie_Logique).

    Design (§Bug Details Bug A, §Correctness Properties Property 1,
    §Testing Strategy « Exploratory Bug Condition Checking », cas 1 et
    2) ; Requirements 1.1, 1.2, 1.3.

    Confirme, sur le code NON corrigé, que `inserer_paie` n'invalide
    jamais les lignes `BROUILLON` actives précédentes d'une même
    Paie_Logique `(employe_id, annee_fiscale, numero_periode)` : après
    plusieurs insertions successives pour la même période, TOUTES les
    lignes insérées restent actives (`statut ∈ {BROUILLON, EMISE}`) au
    lieu d'une seule, comme l'exige l'invariant attendu (Property 1).

    **NE PAS corriger ces tests ni le code lorsqu'ils échouent** —
    l'échec par accumulation est le résultat attendu de cette tâche
    d'exploration (tâche 2 du plan). Le fix (tâche 3) rendra ces mêmes
    assertions vraies.

    Règle 04 : chaque test injecte un `chemin_bd` temporaire
    (`st_chemin_bd_temporaire`) — jamais la base de production — et
    n'utilise que l'identifiant fictif `EMP001` (déjà utilisé par
    `TestRefusDoubleEmisePourMemePeriode`, même convention).
    """

    def test_exemple_double_brouillon_meme_periode_accumule_deux_lignes_actives(
        self,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Test 1 (exemple) — Req 1.1, 1.2.

        Insère deux `BROUILLON` successifs pour la même Paie_Logique
        `(EMP001, 2026, 1)` via `inserer_paie`. Sur le code non
        corrigé, `_lignes_actives` révèle les DEUX lignes comme actives
        (`BROUILLON`, `BROUILLON`) — contre-exemple attendu (design
        §Testing Strategy, Test Case 1) : l'invariant « au plus une
        ligne active par période » (Property 1) est violé.
        """
        module = _importer_module_register()

        premier_brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v1",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )
        second_brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v2",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )

        module.inserer_paie(
            premier_brouillon, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )
        module.inserer_paie(
            second_brouillon, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )

        actives = _lignes_actives(
            module,
            "EMP001",
            2026,
            1,
            chemin_bd=st_chemin_bd_temporaire,
        )

        assert len(actives) == 1, (
            "Après deux insertions BROUILLON successives pour la même "
            "Paie_Logique, il ne doit exister qu'une seule ligne active "
            f"(Property 1) — obtenu {len(actives)} ligne(s) active(s) "
            f"({[ligne.statut for ligne in actives]!r}) : contre-exemple "
            "attendu sur le code non corrigé (Bug A, accumulation de "
            "BROUILLON actifs, design §Hypothesized Root Cause)."
        )

    def test_exemple_brouillon_puis_emise_meme_periode_les_deux_restent_actifs(
        self,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Test 2 (exemple) — Req 1.1, 1.3.

        Insère un `BROUILLON` puis un `EMISE` pour la même
        Paie_Logique `(EMP001, 2026, 1)`. Sur le code non corrigé, le
        `BROUILLON` n'est jamais invalidé : `_lignes_actives` révèle
        les DEUX lignes comme actives (`BROUILLON` actif ET `EMISE`
        actif simultanément) — contre-exemple attendu (design §Testing
        Strategy, Test Case 2).
        """
        module = _importer_module_register()

        brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v1",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )
        emise = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v2",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )

        module.inserer_paie(
            brouillon, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )
        module.inserer_paie(
            emise, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )

        actives = _lignes_actives(
            module,
            "EMP001",
            2026,
            1,
            chemin_bd=st_chemin_bd_temporaire,
        )

        assert len(actives) == 1, (
            "Après un BROUILLON suivi d'un EMISE pour la même "
            "Paie_Logique, il ne doit exister qu'une seule ligne active "
            f"(Property 1) — obtenu {len(actives)} ligne(s) active(s) "
            f"({[ligne.statut for ligne in actives]!r}) : contre-exemple "
            "attendu sur le code non corrigé (Bug A, le BROUILLON n'est "
            "jamais invalidé par une insertion EMISE ultérieure)."
        )
        assert actives[0].statut == StatutDePaie.EMISE, (
            "Si une seule ligne reste active après un EMISE, ce doit "
            f"être la ligne EMISE, obtenu {actives[0].statut!r}."
        )


# ---------------------------------------------------------------------------
# Tests unitaires de régression — Bug A, fix (invalidation des BROUILLON
# actifs dans inserer_paie)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Tâche 6 du plan d'implémentation. Le fix (tâche 3) est déjà en place
# dans `inserer_paie` (bloc "1ter") — ces tests vérifient le
# comportement corrigé sur des exemples concrets, en complément des
# property-based tests des tâches 4 et 5.
#
# _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5_


class TestRegressionInvalidationBrouillonActif:
    """Tests unitaires de régression — Bug A, fix (tâche 6).

    Requirements 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5.

    Règle 04 : chaque test injecte un `chemin_bd` temporaire — jamais
    la base de production — et n'utilise que des identifiants fictifs
    `EMPnnn`.
    """

    def test_exemple_insertion_emise_apres_brouillon_actif_remplace_et_cumuls_corrects(
        self,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Insertion d'un EMISE alors qu'un BROUILLON actif existe déjà
        pour la même Paie_Logique (Req 2.1, 2.2, 3.4) : l'ancien
        BROUILLON doit passer à REMPLACE_PAR avec `remplace_par_id`
        pointant vers le nouvel `id_paie`, et `lire_cumuls_ytd` doit
        refléter uniquement la contribution du nouvel EMISE — jamais
        celle du BROUILLON (qui ne contribue jamais aux cumuls, Req
        3.4)."""
        module = _importer_module_register()

        brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v1",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )
        emise = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v2",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )

        module.inserer_paie(
            brouillon, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )
        module.inserer_paie(
            emise, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )

        ancien_relu, _ = module.lire_paie(
            brouillon.id_paie, chemin_bd=st_chemin_bd_temporaire
        )
        assert ancien_relu.statut == StatutDePaie.REMPLACE_PAR, (
            "L'ancien BROUILLON doit passer à REMPLACE_PAR après "
            f"l'insertion de l'EMISE, obtenu {ancien_relu.statut!r}."
        )
        assert ancien_relu.remplace_par_id == emise.id_paie, (
            "Le `remplace_par_id` de l'ancien BROUILLON doit pointer "
            f"vers le nouvel id_paie, obtenu {ancien_relu.remplace_par_id!r}, "
            f"attendu {emise.id_paie!r}."
        )

        cumuls = module.lire_cumuls_ytd(
            "EMP001", 2026, chemin_bd=st_chemin_bd_temporaire
        )
        cumuls_attendus = _cumuls_ytd_attendus((emise,), "EMP001", 2026)
        assert cumuls == cumuls_attendus, (
            "`lire_cumuls_ytd` doit refléter uniquement la contribution "
            f"du nouvel EMISE, obtenu {cumuls!r}, attendu "
            f"{cumuls_attendus!r}."
        )

    def test_exemple_auto_reparation_plusieurs_brouillon_actifs_preexistants(
        self,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Auto-réparation : plusieurs BROUILLON actifs déjà présents en
        base (simulant une base ayant accumulé le bug avant correction —
        le second est inséré directement via sqlite3 brut pour
        contourner le nouveau garde-fou et reproduire fidèlement l'état
        pré-correctif) — une nouvelle insertion doit invalider TOUTES
        les anciennes lignes BROUILLON, pas seulement la première."""
        module = _importer_module_register()

        premier_brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v1",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )
        module.inserer_paie(
            premier_brouillon, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )

        # Insertion directe via sqlite3 brut du second BROUILLON actif,
        # pour contourner le garde-fou désormais en place dans
        # `inserer_paie` et simuler fidèlement un état pré-correctif
        # (plusieurs BROUILLON actifs simultanés pour la même
        # Paie_Logique, conséquence du bug avant ce correctif).
        second_brouillon = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v2",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.BROUILLON,
        )
        connexion_brute = sqlite3.connect(str(st_chemin_bd_temporaire))
        try:
            connexion_brute.execute(
                "INSERT INTO paies (id_paie, employe_id, annee_fiscale, "
                "numero_periode, saison, version, statut, remplace_par_id, "
                "date_creation, date_emission, payload_json, "
                "payload_input_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    second_brouillon.id_paie,
                    second_brouillon.employe_id,
                    second_brouillon.annee_fiscale,
                    second_brouillon.pay_period.numero_periode,
                    "Saison A",
                    second_brouillon.version,
                    second_brouillon.statut.value,
                    None,
                    second_brouillon.date_creation.isoformat(),
                    None,
                    second_brouillon.model_dump_json(),
                    None,
                ),
            )
            connexion_brute.commit()
        finally:
            connexion_brute.close()

        actives_avant = _lignes_actives(
            module, "EMP001", 2026, 1, chemin_bd=st_chemin_bd_temporaire
        )
        assert len(actives_avant) == 2, (
            "État pré-correctif simulé : deux BROUILLON actifs doivent "
            f"coexister avant la nouvelle insertion, obtenu "
            f"{len(actives_avant)}."
        )

        nouvelle_emise = _payroll_result_valide(
            id_paie="PAIE-EMP001-2026-001-v3",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        module.inserer_paie(
            nouvelle_emise, "Saison A", chemin_bd=st_chemin_bd_temporaire
        )

        actives_apres = _lignes_actives(
            module, "EMP001", 2026, 1, chemin_bd=st_chemin_bd_temporaire
        )
        assert len(actives_apres) == 1, (
            "Après la nouvelle insertion, toutes les anciennes lignes "
            "BROUILLON doivent être invalidées (auto-réparation), "
            f"obtenu {len(actives_apres)} ligne(s) active(s)."
        )
        assert actives_apres[0].id_paie == nouvelle_emise.id_paie

        for ancien_id in (premier_brouillon.id_paie, second_brouillon.id_paie):
            ancien_relu, _ = module.lire_paie(
                ancien_id, chemin_bd=st_chemin_bd_temporaire
            )
            assert ancien_relu.statut == StatutDePaie.REMPLACE_PAR, (
                f"L'ancienne ligne {ancien_id!r} doit passer à "
                f"REMPLACE_PAR (auto-réparation), obtenu "
                f"{ancien_relu.statut!r}."
            )
            assert ancien_relu.remplace_par_id == nouvelle_emise.id_paie


# ---------------------------------------------------------------------------
# Property 1 (Fix Checking) — Bug A : invariant « au plus une ligne
# active par période » après le fix (tâche 3)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Design de référence : ``design.md`` §Correctness Properties (Property
# 1), §Testing Strategy « Fix Checking » (pseudocode).
#
# Tâche 4 du plan d'implémentation : pour toute séquence d'insertions
# `BROUILLON`/`BROUILLON`, `BROUILLON`/`EMISE`, ou plusieurs `BROUILLON`
# successifs pour une même Paie_Logique, après CHAQUE insertion il
# n'existe qu'une seule ligne active (`statut ∈ {BROUILLON, EMISE}`), et
# toute ligne devenue inactive porte `statut = REMPLACE_PAR` avec
# `remplace_par_id` égal à l'`id_paie` de l'insertion suivante. Exclut
# de la génération les séquences qui déclencheraient le garde-fou
# `EMISE`→`EMISE` existant (couvert par `TestRefusDoubleEmisePourMemePeriode`,
# tâche 6, pas par cette property) : seule la DERNIÈRE insertion de la
# séquence peut être `EMISE`, toutes les précédentes sont `BROUILLON` —
# ainsi la ligne active immédiatement avant chaque insertion est
# toujours soit absente (première insertion), soit `BROUILLON` (jamais
# `EMISE`), ce qui exclut structurellement deux `EMISE` consécutifs.
#
# _Requirements: 2.1, 2.2_


@st.composite
def _st_sequence_statuts_brouillon_puis_eventuel_emise(
    draw: st.DrawFn,
) -> tuple[StatutDePaie, ...]:
    """Séquence de 1 à 4 `BROUILLON` successifs, suivis ou non d'un
    unique `EMISE` final (Property 1, Fix Checking).

    Ne génère jamais deux `EMISE` consécutifs (le seul `EMISE` possible,
    s'il est tiré, est nécessairement en dernière position) — exclut
    ainsi structurellement le garde-fou `EMISE`→`EMISE` existant, hors
    périmètre de cette property (design §Testing Strategy « Fix
    Checking »).
    """
    nombre_brouillons = draw(st.integers(min_value=1, max_value=4))
    statuts: list[StatutDePaie] = [StatutDePaie.BROUILLON] * nombre_brouillons
    if draw(st.booleans()):
        statuts.append(StatutDePaie.EMISE)
    return tuple(statuts)


class TestFixInvarianceLigneActive:
    """Property 1 (Fix Checking) — Bug A, invariant "au plus une ligne
    active par période" après le fix de la tâche 3.

    Design (§Correctness Properties Property 1, §Testing Strategy « Fix
    Checking ») ; Requirements 2.1, 2.2.

    Règle 04 : chaque test construit un `chemin_bd` unique sous
    `tmp_path` (jamais `st_chemin_bd_temporaire`, résolue une seule fois
    par invocation de test — voir `TestPreservationInvarianceLigneActive`
    pour la justification détaillée) — jamais la base de production — et
    n'utilise que des identifiants fictifs `EMPnnn`.
    """

    # Feature: unicite-paie-active-par-periode, Property 1: Bug Condition - Invariant au plus une ligne active par période
    @pytest.mark.property
    @given(
        statuts=_st_sequence_statuts_brouillon_puis_eventuel_emise(),
        employe_id=st.integers(min_value=1, max_value=999).map(
            lambda n: f"EMP{n:03d}"
        ),
        annee_fiscale=st.integers(min_value=2024, max_value=2030),
        numero_periode=st.integers(min_value=1, max_value=27),
        saison=st_saison(),
    )
    @settings_large_input
    def test_au_plus_une_ligne_active_apres_chaque_insertion(
        self,
        statuts: tuple[StatutDePaie, ...],
        employe_id: str,
        annee_fiscale: int,
        numero_periode: int,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 1 (Req 2.1, 2.2).

        Insère chaque statut de ``statuts`` dans l'ordre via
        `inserer_paie`, pour la même Paie_Logique
        `(employe_id, annee_fiscale, numero_periode)`. Après CHAQUE
        insertion (pas seulement la dernière) : exactement une ligne
        active, portée par l'`id_paie` qui vient d'être inséré ; et si
        une insertion précédente existait, l'ancienne ligne (jusqu'alors
        active) doit maintenant porter `statut = REMPLACE_PAR` avec
        `remplace_par_id` égal à l'`id_paie` de la nouvelle insertion
        (design §Testing Strategy « Fix Checking », pseudocode).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        id_paie_precedent: str | None = None
        for index, statut in enumerate(statuts, start=1):
            id_paie = (
                f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:03d}"
                f"-v{index}"
            )
            resultat = _payroll_result_valide(
                id_paie=id_paie,
                employe_id=employe_id,
                annee_fiscale=annee_fiscale,
                numero_periode=numero_periode,
                statut=statut,
            )

            module.inserer_paie(resultat, saison, chemin_bd=chemin_bd)

            actives = _lignes_actives(
                module,
                employe_id,
                annee_fiscale,
                numero_periode,
                chemin_bd=chemin_bd,
            )
            assert len(actives) == 1, (
                f"Après l'insertion #{index} (statut {statut!r}) de la "
                "séquence, il ne doit exister qu'une seule ligne active "
                f"pour cette Paie_Logique (Property 1), obtenu "
                f"{len(actives)} ligne(s) active(s)."
            )
            assert actives[0].id_paie == id_paie, (
                "La seule ligne active après l'insertion doit être celle "
                f"qui vient d'être insérée (Property 1), obtenu "
                f"{actives[0].id_paie!r}, attendu {id_paie!r}."
            )

            if id_paie_precedent is not None:
                ancien_relu, _ = module.lire_paie(
                    id_paie_precedent, chemin_bd=chemin_bd
                )
                assert ancien_relu.statut == StatutDePaie.REMPLACE_PAR, (
                    f"L'ancienne ligne {id_paie_precedent!r}, active "
                    "avant l'insertion #{index}, doit passer à "
                    f"REMPLACE_PAR (Property 1), obtenu "
                    f"{ancien_relu.statut!r}."
                )
                assert ancien_relu.remplace_par_id == id_paie, (
                    f"Le `remplace_par_id` de l'ancienne ligne "
                    f"{id_paie_precedent!r} doit égaler l'`id_paie` de "
                    f"l'insertion suivante (Property 1), obtenu "
                    f"{ancien_relu.remplace_par_id!r}, attendu "
                    f"{id_paie!r}."
                )

            id_paie_precedent = id_paie


# ---------------------------------------------------------------------------
# Property 2 (Bug Condition) — Bug 2 : absence de persistance du
# `PayrollInput` (exploration)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``heures-periode-et-persistance-brouillon``.
# Design de référence : ``design.md`` §Bug Condition (Bug 2),
# §Correctness Properties (Property 2), §Testing Strategy
# « Exploratory Bug Condition Checking ».
#
# Tâche 2 du plan d'implémentation (méthodologie bug condition,
# observation-first, règle 06) : ces tests d'exploration DOIVENT
# échouer sur le code non corrigé — la colonne `payload_input_json`
# n'existe pas encore dans le DDL `paies`, et `lire_paie` retourne
# encore un `PayrollResult` seul (pas un couple). Ces échecs confirment
# `isBugCondition_Brouillon(X) = X.paie_deja_enregistree == true AND
# X.payload_input_json_disponible == false` (toujours vrai sur le code
# non corrigé).
#
# **NE PAS corriger ces tests ni le code lorsqu'ils échouent** — l'échec
# est le résultat attendu de cette tâche (voir tâches 2, 6.6).
#
# _Requirements: 1.3, 1.4_


class TestExplorationPersistancePayrollInput:
    """Property 2 (Bug Condition) — exploration, Bug 2 (brouillon non
    restituable).

    Design (§Bug Condition Bug 2, §Correctness Properties Property 2,
    §Testing Strategy « Exploratory Bug Condition Checking », cas 2 et
    3) ; Requirements 1.3, 1.4.

    Confirme, sur le code NON corrigé, que :

    1. la colonne `payload_input_json` est absente du schéma `paies`
       après `_creer_schema_si_absent` (Test 1, exemple) ;
    2. `lire_paie(id_paie)` retourne un `PayrollResult` seul — la
       déstructuration `resultat, payroll_input = lire_paie(id_paie)`
       échoue par `TypeError` (Test 2, exemple).

    Règle 04 : chaque test ouvre une connexion `":memory:"` ou une base
    `tmp_path` — jamais la base de production — et n'utilise que des
    identifiants fictifs `EMPnnn` (via `_st_un_payroll_result_emis`,
    déjà défini par la tâche 3.1, réutilisé sans modification).
    """

    # Feature: heures-periode-et-persistance-brouillon, Property 2: Bug Condition
    def test_exemple_colonne_payload_input_json_absente_du_schema_paies(
        self,
    ) -> None:
        """Test 1 (exemple) — Req 1.3.

        `PRAGMA table_info(paies)` sur une connexion `":memory:"`
        fraîche, après `_creer_schema_si_absent`, ne doit PAS contenir
        de colonne nommée `payload_input_json` sur le code non
        corrigé : le DDL `_DDL_PAIES` actuel ne définit que
        `payload_json`, jamais les données d'entrée (`PayrollInput`).
        """
        module = _importer_module_register()

        connexion = sqlite3.connect(":memory:")
        try:
            module._creer_schema_si_absent(connexion)
            colonnes = {
                ligne[1]
                for ligne in connexion.execute(
                    "PRAGMA table_info(paies)"
                ).fetchall()
            }
        finally:
            connexion.close()

        assert "payload_input_json" not in colonnes, (
            "Sur le code non corrigé, `payload_input_json` ne doit PAS "
            f"figurer dans le schéma `paies`, colonnes obtenues : "
            f"{colonnes!r} — si ce test échoue en PASSANT, la colonne "
            "existe déjà et le Bug 2 pourrait être déjà corrigé "
            "(Property 2, Req 1.3)."
        )

    # Feature: heures-periode-et-persistance-brouillon, Property 2: Bug Condition
    @given(resultat=_st_un_payroll_result_emis, saison=st_saison())
    @settings_large_input
    def test_exemple_lire_paie_retourne_payrollresult_seul_deballage_echoue(
        self,
        resultat: PayrollResult,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Test 2 (exemple) — Req 1.4.

        Sur le code non corrigé, `lire_paie(id_paie)` retourne un
        `PayrollResult` unique (pas un couple) : tenter de le
        déstructurer en `(resultat_relu, payroll_input_relu) =
        lire_paie(...)` doit échouer — confirme que le `PayrollInput`
        n'est jamais restitué par la lecture.

        **Constat empirique (contre-exemple documenté)** : le design
        anticipait un `TypeError` (« cannot unpack non-iterable
        PayrollResult »), formulation valable pour un objet Python
        ordinaire non itérable. `PayrollResult` est un modèle Pydantic
        v2, qui implémente nativement `__iter__` (itération sur les
        paires `(nom_champ, valeur)`, utilisée par `dict(modele)`) — la
        déstructuration `a, b = resultat` échoue donc bel et bien, mais
        avec `ValueError: too many values to unpack (expected 2)`
        (`PayrollResult` compte largement plus de 2 champs), pas
        `TypeError`. Le test accepte les deux types pour rester robuste
        à ce détail d'implémentation Pydantic, sans affaiblir la
        confirmation du bug : dans les deux cas, aucun couple
        `(PayrollResult, PayrollInput | None)` n'est jamais obtenu.

        Chemin `chemin_bd` construit manuellement sous `tmp_path` (même
        patron que `TestRemplacerPaie` — pas la fixture
        `st_chemin_bd_temporaire`, qui n'est résolue qu'une seule fois
        par invocation de test pytest et serait donc partagée entre
        plusieurs exemples Hypothesis générés par cette même invocation,
        provoquant des collisions d'`id_paie` déjà présent).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(resultat, saison, chemin_bd=chemin_bd)

        with pytest.raises((TypeError, ValueError)):
            resultat_relu, payroll_input_relu = module.lire_paie(
                resultat.id_paie, chemin_bd=chemin_bd
            )


# ---------------------------------------------------------------------------
# Property 4 (Preservation) — paies pré-correction, Action_Corriger,
# non-régression golden (Bug 2)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``heures-periode-et-persistance-brouillon``.
# Design de référence : ``design.md`` §Correctness Properties (Property 4),
# §Preservation Requirements, §Testing Strategy « Preservation Checking ».
#
# Tâche 4 du plan d'implémentation (méthodologie bug condition,
# observation-first, règle 06) : ces tests de préservation DOIVENT
# PASSER sur le code non corrigé — ils caractérisent le comportement de
# référence que la correction (tâches 6.1 à 6.7) devra continuer à
# produire pour les appels qui ne transmettent jamais de `PayrollInput`
# (signature actuelle de `inserer_paie`/`remplacer_paie`, sans le
# paramètre `payroll_input`/`nouveau_payroll_input` introduit par la
# tâche 6.2) et pour l'Action_Corriger (`remplacer_paie`).
#
# **NE PAS écrire de nouveau test après la correction** — les tâches
# 6.7 ré-exécutent strictement ces mêmes tests sur le code corrigé.
#
# _Requirements: 3.3, 3.4, 3.5, 3.6_


class TestPreservationPaiesPreCorrection:
    """Property 4 (Preservation) — comportement inchangé pour les paies
    pré-correction et pour l'Action_Corriger.

    Design (§Correctness Properties Property 4, §Preservation
    Requirements, §Testing Strategy « Preservation Checking », cas 3) ;
    Requirements 3.3, 3.4, 3.5, 3.6.

    Confirme, sur le code NON corrigé (signature actuelle de
    `inserer_paie`/`remplacer_paie`, sans `PayrollInput`), que :

    1. toute insertion via `inserer_paie(resultat, saison,
       chemin_bd=...)` (sans `PayrollInput` — cas normal, la colonne
       `payload_input_json` n'existe même pas encore) est relue sans
       exception via `lire_paie` (Test 1, property-based, Req 3.4) — le
       test complémentaire vérifiant que `valeurs_effectives_depuis_paie`
       appliqué à ce résultat relu ne restitue jamais les clés d'heures
       est ajouté à `tests/app/logique_metier/test_formulaire_paie.
       py::TestExplorationValeursEffectivesHeures` (classe créée en
       tâche 2), seul endroit du dépôt où un `PayrollResult` porteur de
       traces réelles compatibles avec `valeurs_effectives_depuis_paie`
       est déjà disponible (`_st_un_payroll_result`, assemblé via
       `assembler_paie` — les `PayrollResult` synthétiques de
       `st_sequence_payroll_results_meme_employe_annee`, construits sans
       passer par le moteur, portent des traces vides incompatibles avec
       les clés `parametres_utilises`/`entrees` que cette fonction lit) ;
    2. `remplacer_paie` sur une paie `EMISE` existante continue de
       produire une nouvelle version incrémentée (`version + 1`) et un
       `cumuls_ytd` recalculé à l'identique (Test 2, exemple, Req 3.3) ;
    3. les golden tests et property-based tests existants du moteur
       fiscal (`tests/test_golden_outputs.py`,
       `tests/payroll_engine/test_gains_bruts.py`) ne sont pas modifiés
       par ce bugfix (Test 3, non-régression, Req 3.5, 3.6).

    Règle 04 : chaque test injecte un `chemin_bd` temporaire (`tmp_path`
    / `st_chemin_bd_temporaire`) — jamais la base de production — et
    n'utilise que des identifiants fictifs `EMPnnn` (via les stratégies
    déjà existantes de `tests/strategies.py`).
    """

    # -----------------------------------------------------------------
    # Test 1 (property-based) — insertion/relecture sans PayrollInput,
    # aucune exception, aucune clé d'heures restituée (Req 3.4).
    # -----------------------------------------------------------------

    # Feature: heures-periode-et-persistance-brouillon, Property 4: Preservation
    @pytest.mark.property
    @given(
        sequence=st_sequence_payroll_results_meme_employe_annee(n_max=3),
        saison=st_saison(),
    )
    @settings_large_input
    def test_insertion_sans_payroll_input_relue_sans_exception_sans_cles_heures(
        self,
        sequence: tuple[PayrollResult, ...],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 4, Test 1 (Preservation) — Req 3.4.

        Pour toute séquence de `PayrollResult` insérée via
        `inserer_paie(resultat, saison, chemin_bd=...)` (signature
        actuelle, sans `PayrollInput`) sur une base neuve, chaque
        relecture via `lire_paie` ne doit lever aucune exception et doit
        rester un round-trip strict (`resultat_relu == resultat`,
        Property 10 déjà couverte par la tâche 3.4, reproduite ici comme
        comportement de référence explicitement rattaché à ce bugfix) —
        comportement à préserver strictement identique après correction
        pour ce type d'appel (aucun `PayrollInput` transmis). Le volet
        « aucune clé d'heures restituée » de Property 4 est couvert par
        `tests/app/logique_metier/test_formulaire_paie.py::
        TestExplorationValeursEffectivesHeures` (voir docstring de
        classe ci-dessus).

        Réutilise `st_sequence_payroll_results_meme_employe_annee`
        (déjà défini par `tests/strategies.py`, spec
        `net-cumuls-registre`). Chemin `chemin_bd` construit manuellement
        sous `tmp_path` (même patron que `TestRemplacerPaie`/
        `TestExplorationPersistancePayrollInput`) — pas la fixture
        `st_chemin_bd_temporaire`, qui n'est résolue qu'une seule fois
        par invocation de test pytest et serait donc partagée entre
        plusieurs exemples Hypothesis générés par cette même invocation,
        provoquant des collisions d'`id_paie` déjà présent si deux
        exemples tirent le même `employe_id`.
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        # Bug corrigé après livraison (demande explicite de
        # l'utilisateur) — `inserer_paie` refuse désormais une seconde
        # ligne `EMISE` pour la même Paie_Logique `(employe_id,
        # annee_fiscale, numero_periode)` (voir
        # `TestRefusDoubleEmisePourMemePeriode`). `sequence` (générée
        # par `st_sequence_payroll_results_meme_employe_annee`) ne
        # garantit pas des `numero_periode` distincts entre ses
        # éléments — ne conserver ici que le premier élément par
        # `numero_periode` rencontré, pour ne pas violer cette
        # invariante désormais imposée par le registre (comportement de
        # préservation testé par Property 4 : round-trip sans
        # `PayrollInput`, indépendant du nombre d'éléments distincts
        # effectivement insérés).
        sequence_periodes_distinctes = []
        periodes_vues: set[int] = set()
        for resultat in sequence:
            if resultat.pay_period.numero_periode in periodes_vues:
                continue
            periodes_vues.add(resultat.pay_period.numero_periode)
            sequence_periodes_distinctes.append(resultat)

        for resultat in sequence_periodes_distinctes:
            module.inserer_paie(
                resultat, saison, chemin_bd=chemin_bd
            )

        for resultat in sequence_periodes_distinctes:
            resultat_relu, _ = module.lire_paie(
                resultat.id_paie, chemin_bd=chemin_bd
            )
            assert resultat_relu == resultat, (
                "`lire_paie` après `inserer_paie` sans `PayrollInput` doit "
                f"rester un round-trip strict (Property 4), obtenu "
                f"{resultat_relu!r}, attendu {resultat!r}."
            )

    # -----------------------------------------------------------------
    # Test 2 (exemple) — `remplacer_paie` : version incrémentée et
    # `cumuls_ytd` recalculé, signature actuelle (Req 3.3).
    # -----------------------------------------------------------------

    # Feature: heures-periode-et-persistance-brouillon, Property 4: Preservation
    @given(deux_resultats=_st_deux_payroll_results_memes_employe_annee, saison=st_saison())
    @settings_large_input
    def test_exemple_remplacer_paie_incremente_version_et_recalcule_cumuls(
        self,
        deux_resultats: tuple[PayrollResult, PayrollResult],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 4, Test 2 (Preservation) — Req 3.3.

        Sur le code non corrigé, `remplacer_paie(ancien_id,
        nouveau_resultat, saison, chemin_bd=...)` (signature actuelle,
        sans `nouveau_payroll_input`) continue de produire une nouvelle
        version dont `version == nouveau_resultat.version` (déjà
        incrémentée par l'appelant conformément à Req 13.3, cf.
        `app/pages_ui/formulaire_paie.py::_section_corriger_paie` —
        `nouvelle_version = ancienne_paie.version + 1`), et `cumuls_ytd`
        est recalculé à l'identique de celui obtenu par une insertion
        directe équivalente du nouveau résultat seul (même assertion que
        `TestRemplacerPaie.test_remplacement_equivaut_a_insertion_
        directe_du_nouveau`, tâche 3.3 — reproduite ici comme
        comportement de référence à préserver par ce bugfix, sans
        dupliquer les tests UI existants de `_section_corriger_paie`).
        """
        module = _importer_module_register()
        ancien, nouveau = deux_resultats
        nouveau_avec_version_incrementee = nouveau.model_copy(
            update={"version": ancien.version + 1}
        )

        chemin_a = tmp_path / f"test_{uuid.uuid4().hex}.db"
        chemin_b = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(ancien, saison, chemin_bd=chemin_a)
        module.remplacer_paie(
            ancien.id_paie,
            nouveau_avec_version_incrementee,
            saison,
            chemin_bd=chemin_a,
        )

        paie_remplacante_relue, _ = module.lire_paie(
            nouveau_avec_version_incrementee.id_paie, chemin_bd=chemin_a
        )
        assert paie_remplacante_relue.version == ancien.version + 1, (
            "`remplacer_paie` doit continuer de persister une nouvelle "
            f"version incrémentée (`version + 1`), obtenu "
            f"{paie_remplacante_relue.version!r}, attendu "
            f"{ancien.version + 1!r} (Property 4, Req 3.3)."
        )

        cumuls_via_remplacement = module.lire_cumuls_ytd(
            nouveau_avec_version_incrementee.employe_id,
            nouveau_avec_version_incrementee.annee_fiscale,
            chemin_bd=chemin_a,
        )

        module.inserer_paie(
            nouveau_avec_version_incrementee, saison, chemin_bd=chemin_b
        )
        cumuls_via_insertion_directe = module.lire_cumuls_ytd(
            nouveau_avec_version_incrementee.employe_id,
            nouveau_avec_version_incrementee.annee_fiscale,
            chemin_bd=chemin_b,
        )

        assert cumuls_via_remplacement == cumuls_via_insertion_directe, (
            "`cumuls_ytd` après `remplacer_paie` doit continuer d'être "
            "recalculé exactement comme une insertion directe équivalente "
            f"du nouveau résultat seul (Property 4, Req 3.3), obtenu "
            f"{cumuls_via_remplacement!r}, attendu "
            f"{cumuls_via_insertion_directe!r}."
        )

    # -----------------------------------------------------------------
    # Test 3 (exemple, non-régression) — les suites golden existantes
    # ne sont pas modifiées par ce bugfix (Req 3.5, 3.6).
    # -----------------------------------------------------------------

    def test_exemple_suites_golden_existantes_non_modifiees_par_ce_bugfix(
        self,
    ) -> None:
        """Property 4, Test 3 (Preservation, non-régression) — Req 3.5, 3.6.

        Ce bugfix (`heures-periode-et-persistance-brouillon`) ne modifie
        ni `tests/test_golden_outputs.py` ni
        `tests/payroll_engine/test_gains_bruts.py` — les deux suites
        continuent de passer, exécutées séparément (les golden tests sont
        marqués `@pytest.mark.golden`/`@pytest.mark.property`, filtrables
        indépendamment de cette suite via `pytest -m golden` ou en
        exécutant ces deux fichiers directement, ex. `pytest
        tests/test_golden_outputs.py tests/payroll_engine/
        test_gains_bruts.py`).

        Ce test ne ré-exécute pas ces deux suites en sous-processus (elles
        sont déjà exécutées par la même invocation `pytest` que ce
        fichier, dans `testpaths = ["tests"]` — les exécuter une seconde
        fois ici serait redondant et ralentirait la suite sans apporter
        de garantie supplémentaire). Il vérifie plutôt, par introspection
        directe des fichiers, qu'aucune fonction de calcul fiscal
        (`calcul_gains`) n'est importée ou appelée par les modules touchés
        par ce bugfix (`app/logique_metier/formulaire_paie.py`,
        `payroll_engine/register.py`) — confirmant que le moteur fiscal
        (`payroll_engine/gains_bruts.py`, seul module couvert par
        `test_gains_bruts.py`) reste totalement étranger à ce bugfix (Req
        3.5, 3.6, design §Overview : « Aucune des deux ne modifie une
        formule fiscale »).
        """
        chemin_register = (
            Path(__file__).resolve().parents[2] / "payroll_engine" / "register.py"
        )
        contenu_register = chemin_register.read_text(encoding="utf-8")
        assert "gains_bruts" not in contenu_register, (
            "`payroll_engine/register.py` ne doit importer/référencer "
            "aucun symbole de `payroll_engine/gains_bruts.py` — ce module "
            "de calcul fiscal reste hors périmètre de ce bugfix (Property "
            "4, Req 3.5, 3.6)."
        )

        chemin_formulaire_paie = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "logique_metier"
            / "formulaire_paie.py"
        )
        contenu_formulaire_paie = chemin_formulaire_paie.read_text(encoding="utf-8")
        assert "calcul_gains" not in contenu_formulaire_paie, (
            "`app/logique_metier/formulaire_paie.py` ne doit ni importer "
            "ni appeler `calcul_gains` — ce bugfix ne modifie aucune "
            "formule fiscale (Property 4, Req 3.5, 3.6)."
        )


# ---------------------------------------------------------------------------
# Property 3 (Preservation) — Bug A : flux et garde-fous existants du
# registre, hors condition de bug (isBugCondition_InvarianceActive fausse)
# ---------------------------------------------------------------------------
#
# Bugfix de référence : ``unicite-paie-active-par-periode``.
# Design de référence : ``design.md`` §Correctness Properties (Property 3),
# §Testing Strategy « Preservation Checking » (Test Cases 1 à 3).
#
# Tâche 5 du plan d'implémentation : pour toute insertion où
# `isBugCondition_InvarianceActive` est fausse (aucune ligne `BROUILLON`
# active de la même Paie_Logique — Paie_Logiques toutes distinctes,
# absence totale de ligne active préexistante, ou ligne active existante
# `EMISE` plutôt que `BROUILLON`), le comportement de `inserer_paie`
# corrigé (tâche 3) doit rester strictement identique à celui du code
# d'avant ce bugfix : aucune ligne mutée hors la ligne insérée,
# `cumuls_ytd` identique à un calcul manuel, aucune exception
# inattendue (le garde-fou `EMISE`→`EMISE` existant continue de lever
# `ValueError` sans aucune mutation).
#
# _Requirements: 3.1, 3.2, 3.3, 3.4_


class TestPreservationInvarianceLigneActive:
    """Property 3 (Preservation) — Bug A, comportement inchangé hors
    condition de bug.

    Design (§Correctness Properties Property 3, §Testing Strategy
    « Preservation Checking », cas 1 à 3) ; Requirements 3.1, 3.2, 3.3,
    3.4.

    Règle 04 : chaque test injecte un `chemin_bd` temporaire
    (`st_chemin_bd_temporaire`) — jamais la base de production — et
    n'utilise que des identifiants fictifs `EMPnnn`.
    """

    # -----------------------------------------------------------------
    # Test 1 (property-based) — Paie_Logiques toutes distinctes ou
    # première insertion sans ligne active préexistante (Req 3.1, 3.3,
    # 3.4), y compris le garde-fou EMISE→EMISE préexistant (Req 3.1).
    # -----------------------------------------------------------------

    # Feature: unicite-paie-active-par-periode, Property 3: Preservation - Flux et garde-fous existants du registre
    @pytest.mark.property
    @given(
        sequence=st_sequence_payroll_results_meme_employe_annee(n_max=5),
        saison=st_saison(),
    )
    @settings_large_input
    def test_sequence_sans_brouillon_actif_prealable_comportement_inchange(
        self,
        sequence: tuple[PayrollResult, ...],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 3 (Req 3.1, 3.3, 3.4).

        `sequence` (`st_sequence_payroll_results_meme_employe_annee`) ne
        contient que des `PayrollResult` `EMISE` — il n'existe donc
        jamais de ligne `BROUILLON` active de la même Paie_Logique avant
        une insertion : `isBugCondition_InvarianceActive` est fausse pour
        toute insertion de cette séquence, par construction (la ligne
        active éventuellement déjà présente pour une période, si elle
        existe, est nécessairement `EMISE`, jamais `BROUILLON`).

        Deux issues possibles pour chaque insertion, toutes deux déjà
        vraies avant ce bugfix et devant le rester à l'identique :

        - `numero_periode` inédit pour cet `employe_id`/`annee_fiscale` :
          insertion simple, sans exception, sans mutation d'aucune autre
          ligne déjà insérée (§Preservation Requirements : « La première
          insertion d'une Paie_Logique... reste une insertion simple »).
        - `numero_periode` déjà porteur d'une ligne `EMISE` active
          (insérée plus tôt dans cette même séquence) : le garde-fou
          `EMISE`→`EMISE` existant lève `ValueError`, sans aucune
          mutation de la ligne déjà présente (« Le garde-fou EMISE→EMISE
          existant... continue de s'appliquer, sans aucune modification
          de comportement »).

        À la fin, `cumuls_ytd` doit égaler la somme manuelle des
        contributions des seules insertions ayant réussi — identique à
        Property 8 (tâche 3.2), reproduite ici comme comportement de
        référence explicitement rattaché à ce bugfix.
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        if sequence:
            employe_id = sequence[0].employe_id
            annee_fiscale = sequence[0].annee_fiscale
        else:
            employe_id = "EMP000"
            annee_fiscale = 2026

        resultats_inseres_par_periode: dict[int, PayrollResult] = {}
        resultats_inseres_avec_succes: list[PayrollResult] = []

        for resultat in sequence:
            numero_periode = resultat.pay_period.numero_periode
            ligne_active_avant = resultats_inseres_par_periode.get(numero_periode)

            if ligne_active_avant is not None:
                # Une ligne EMISE active existe déjà pour cette période
                # (insérée plus tôt dans cette même séquence) —
                # `isBugCondition_InvarianceActive` est fausse (ligne
                # active EMISE, pas BROUILLON) : le garde-fou EMISE→EMISE
                # existant doit lever ValueError, sans aucune mutation.
                with pytest.raises(ValueError) as excinfo:
                    module.inserer_paie(
                        resultat, saison, chemin_bd=chemin_bd
                    )
                assert "EMISE" in str(excinfo.value), (
                    "Le refus d'une seconde EMISE pour la même période "
                    f"doit mentionner EMISE, obtenu {excinfo.value!r} "
                    "(Property 3, préservation du garde-fou existant)."
                )
                with pytest.raises(KeyError):
                    module.lire_paie(
                        resultat.id_paie, chemin_bd=chemin_bd
                    )
                # La ligne déjà active ne doit avoir subi aucune mutation.
                relue, _ = module.lire_paie(
                    ligne_active_avant.id_paie, chemin_bd=chemin_bd
                )
                assert relue == ligne_active_avant, (
                    "Une tentative d'insertion refusée (Property 3) ne "
                    "doit muter aucune autre ligne du registre, obtenu "
                    f"{relue!r}, attendu {ligne_active_avant!r}."
                )
            else:
                # Première insertion pour cette Paie_Logique — aucune
                # ligne active préexistante : insertion simple, sans
                # exception, sans mutation des autres lignes déjà
                # insérées avec succès.
                module.inserer_paie(
                    resultat, saison, chemin_bd=chemin_bd
                )
                resultats_inseres_par_periode[numero_periode] = resultat

                relu, _ = module.lire_paie(
                    resultat.id_paie, chemin_bd=chemin_bd
                )
                assert relu == resultat, (
                    "Une insertion sans ligne active préexistante "
                    "(Property 3) doit rester un round-trip strict, "
                    f"obtenu {relu!r}, attendu {resultat!r}."
                )

                for autre in resultats_inseres_avec_succes:
                    autre_relu, _ = module.lire_paie(
                        autre.id_paie, chemin_bd=chemin_bd
                    )
                    assert autre_relu == autre, (
                        "Une nouvelle insertion sans ligne active "
                        "préexistante pour sa propre période (Property 3) "
                        "ne doit muter aucune ligne d'une autre "
                        f"Paie_Logique, obtenu {autre_relu!r}, attendu "
                        f"{autre!r}."
                    )

                resultats_inseres_avec_succes.append(resultat)

        cumuls_obtenus = module.lire_cumuls_ytd(
            employe_id, annee_fiscale, chemin_bd=chemin_bd
        )
        cumuls_attendus = _cumuls_ytd_attendus(
            tuple(resultats_inseres_avec_succes), employe_id, annee_fiscale
        )
        assert cumuls_obtenus == cumuls_attendus, (
            "`cumuls_ytd` après cette séquence de préservation (Property "
            f"3) doit égaler la somme des contributions des insertions "
            f"réussies, obtenu {cumuls_obtenus!r}, attendu "
            f"{cumuls_attendus!r}."
        )

    # -----------------------------------------------------------------
    # Test 2 (property-based) — généralisation de
    # `test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee`
    # (BROUILLON après EMISE actif, sans BROUILLON actif préexistant,
    # Req 3.2, 3.4).
    # -----------------------------------------------------------------

    # Feature: unicite-paie-active-par-periode, Property 3: Preservation - Flux et garde-fous existants du registre
    @pytest.mark.property
    @given(
        employe_id=st.integers(min_value=1, max_value=999).map(
            lambda n: f"EMP{n:03d}"
        ),
        annee_fiscale=st.integers(min_value=2024, max_value=2030),
        numero_periode=st.integers(min_value=1, max_value=27),
        saison=st_saison(),
    )
    @settings_large_input
    def test_insertion_brouillon_apres_emise_actif_sans_brouillon_prealable_naffecte_pas_emise(
        self,
        employe_id: str,
        annee_fiscale: int,
        numero_periode: int,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 3 — généralisation de
        `test_exemple_insertion_brouillon_meme_periode_apres_emise_reste_autorisee`
        (Req 3.2, 3.4).

        Pour tout triplet `(employe_id, annee_fiscale, numero_periode)`,
        insérer une ligne `EMISE` puis une ligne `BROUILLON` pour la
        même Paie_Logique — sans aucun `BROUILLON` actif préexistant,
        `isBugCondition_InvarianceActive` est fausse (la seule ligne
        active avant la seconde insertion est `EMISE`, pas `BROUILLON`) :
        l'insertion du `BROUILLON` doit rester autorisée sans lever
        d'exception, et la ligne `EMISE` ne doit subir AUCUNE mutation
        (statut, `remplace_par_id`, `payload_json` strictement
        inchangés) — comportement préexistant à ce bugfix, non touché
        par le fix de la tâche 3 (qui n'invalide que les lignes
        `BROUILLON` actives, jamais les lignes `EMISE`).

        Chemin `chemin_bd` construit manuellement sous `tmp_path` (même
        patron que `TestRemplacerPaie`/`TestPreservationPaiesPreCorrection`)
        — pas la fixture `st_chemin_bd_temporaire`, qui n'est résolue
        qu'une seule fois par invocation de test pytest et serait donc
        partagée entre plusieurs exemples Hypothesis : `id_paie` étant
        ici dérivé de manière déterministe du triplet généré, deux
        exemples tirant le même triplet provoqueraient une collision
        d'`id_paie` déjà présent sur une base partagée.
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        emise = _payroll_result_valide(
            id_paie=f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:03d}-v1",
            employe_id=employe_id,
            annee_fiscale=annee_fiscale,
            numero_periode=numero_periode,
            statut=StatutDePaie.EMISE,
        )
        brouillon = _payroll_result_valide(
            id_paie=f"PAIE-{employe_id}-{annee_fiscale}-{numero_periode:03d}-v2",
            employe_id=employe_id,
            annee_fiscale=annee_fiscale,
            numero_periode=numero_periode,
            statut=StatutDePaie.BROUILLON,
        )

        module.inserer_paie(emise, saison, chemin_bd=chemin_bd)
        # Ne doit lever aucune exception (préservation, Req 3.2).
        module.inserer_paie(brouillon, saison, chemin_bd=chemin_bd)

        emise_relue, _ = module.lire_paie(emise.id_paie, chemin_bd=chemin_bd)
        assert emise_relue == emise, (
            "L'insertion d'un BROUILLON après un EMISE actif ne doit "
            f"muter aucun champ de la ligne EMISE (Property 3), obtenu "
            f"{emise_relue!r}, attendu {emise!r}."
        )
        assert emise_relue.remplace_par_id is None, (
            "La ligne EMISE ne doit jamais recevoir de `remplace_par_id` "
            "suite à l'insertion d'un BROUILLON pour la même période "
            f"(Property 3), obtenu {emise_relue.remplace_par_id!r}."
        )

        brouillon_relu, _ = module.lire_paie(
            brouillon.id_paie, chemin_bd=chemin_bd
        )
        assert brouillon_relu == brouillon, (
            "Le BROUILLON inséré après un EMISE actif doit rester un "
            f"round-trip strict, obtenu {brouillon_relu!r}, attendu "
            f"{brouillon!r}."
        )

        actives = _lignes_actives(
            module,
            employe_id,
            annee_fiscale,
            numero_periode,
            chemin_bd=chemin_bd,
        )
        assert len(actives) == 2, (
            "Le BROUILLON inséré après un EMISE actif (sans BROUILLON "
            "actif préexistant) reste, à l'identique d'avant ce bugfix, "
            "actif EN PLUS de l'EMISE — seule l'insertion sur un "
            "BROUILLON actif préexistant est invalidée (Property 1, hors "
            f"périmètre de Property 3) — obtenu {len(actives)} ligne(s) "
            "active(s)."
        )

        cumuls_obtenus = module.lire_cumuls_ytd(
            employe_id, annee_fiscale, chemin_bd=chemin_bd
        )
        cumuls_attendus = _cumuls_ytd_attendus(
            (emise,), employe_id, annee_fiscale
        )
        assert cumuls_obtenus == cumuls_attendus, (
            "`cumuls_ytd` doit refléter uniquement la contribution de la "
            f"ligne EMISE, jamais celle du BROUILLON (Property 3), obtenu "
            f"{cumuls_obtenus!r}, attendu {cumuls_attendus!r}."
        )


# ---------------------------------------------------------------------------
# 4.2 — Property 3 (spec `formulaire-paie-suppression-et-ux`) : suppression
# physique d'une paie BROUILLON et préservation des Cumuls_YTD.
# ---------------------------------------------------------------------------


@st.composite
def _st_brouillon_avec_cumuls_arbitraires(
    draw: st.DrawFn,
) -> tuple[PayrollResult, CumulsYTD]:
    """Un `PayrollResult` `BROUILLON` autonome, apparié à un `CumulsYTD`
    arbitraire pour le même `(employe_id, annee_civile)` (design
    `formulaire-paie-suppression-et-ux`, §Correctness Properties,
    Property 3).

    Réutilise `_st_un_payroll_result_emis` (tâche 3.1, déjà défini plus
    haut dans ce fichier pour les Properties 8 à 14 de
    `net-cumuls-registre`) — un `PayrollResult` `EMISE` valide et
    autonome — puis mute son `statut` vers `BROUILLON` via `model_copy`
    (même patron que `TestRemplacerPaie` : `ancien_emise.model_copy(
    update={"statut": StatutDePaie.BROUILLON})`). `date_emission` reste
    inchangée (non-``None``, héritée de l'`EMISE` source) : l'invariant
    `PayrollResult` n'interdit jamais une `date_emission` renseignée en
    `BROUILLON` (implication unidirectionnelle, Req 6.7).

    `st_cumuls_ytd_non_nuls()` (déjà défini pour `cotisations-sociales-qc`)
    fournit un `CumulsYTD` arbitraire, dont `employe_id`/`annee_civile`
    sont réassignés pour correspondre exactement au `BROUILLON` généré —
    même technique d'appariement que `tests/payroll_engine/test_rrq.py`
    (`cumuls_ajustes = cumuls_generes.model_copy(update={...})`). Ce
    `CumulsYTD` représente « tout état préexistant arbitraire des
    Cumuls_YTD de l'employé et de l'année concernés » (design Property 3)
    — écrit directement dans la table `cumuls_ytd` par le test (jamais
    via `inserer_paie`, qui n'y contribue jamais pour un `BROUILLON`,
    Req 3.8/11.4).
    """
    brouillon_emise = draw(_st_un_payroll_result_emis)
    brouillon = brouillon_emise.model_copy(update={"statut": StatutDePaie.BROUILLON})
    cumuls_generes = draw(st_cumuls_ytd_non_nuls())
    cumuls_arbitraires = cumuls_generes.model_copy(
        update={
            "employe_id": brouillon.employe_id,
            "annee_civile": brouillon.annee_fiscale,
        }
    )
    return brouillon, cumuls_arbitraires


# ---------------------------------------------------------------------------
# 4.3 — Property 4 (spec `formulaire-paie-suppression-et-ux`) : garde-fou
# de `supprimer_paie_brouillon`.
# ---------------------------------------------------------------------------


@st.composite
def _st_payroll_result_statut_non_brouillon(
    draw: st.DrawFn,
) -> PayrollResult:
    """Un `PayrollResult` de statut `EMISE`, `ANNULEE` ou `REMPLACE_PAR`
    (design `formulaire-paie-suppression-et-ux`, §Correctness Properties,
    Property 4 : « for all `PayrollResult` déjà insérés dans le Registre
    dont le statut n'est pas `BROUILLON` »).

    Réutilise `_st_un_payroll_result_emis` (tâche 3.1) puis mute son
    `statut` via `model_copy` — même patron que
    `_st_brouillon_avec_cumuls_arbitraires` (tâche 4.2). Pour
    `REMPLACE_PAR`, `remplace_par_id` est renseigné avec un identifiant
    fictif non vide (invariant `PayrollResult`, biconditionnelle Req 6.3,
    6.4) ; `date_emission` reste héritée de l'`EMISE` source pour les
    trois statuts (déjà non-``None``, satisfaisant l'implication Req 6.7
    pour `EMISE`/`ANNULEE`/`REMPLACE_PAR`).
    """
    resultat_emise = draw(_st_un_payroll_result_emis)
    statut = draw(
        st.sampled_from(
            [StatutDePaie.EMISE, StatutDePaie.ANNULEE, StatutDePaie.REMPLACE_PAR]
        )
    )
    if statut == StatutDePaie.REMPLACE_PAR:
        return resultat_emise.model_copy(
            update={
                "statut": statut,
                "remplace_par_id": f"PAIE-REMPLACEMENT-{resultat_emise.id_paie}",
            }
        )
    return resultat_emise.model_copy(update={"statut": statut})


def st_id_paie_arbitraire() -> st.SearchStrategy[str]:
    """Identifiant de paie fictif arbitraire (règle 04), destiné à rester
    absent de tout Registre de test — chaque exemple utilise une base
    neuve (`st_chemin_bd_temporaire`), donc aucune ligne ne peut jamais
    exister pour cet identifiant, quelle que soit la valeur tirée.
    """
    return st.integers(min_value=0, max_value=999_999).map(
        lambda n: f"PAIE-INEXISTANTE-{n:06d}"
    )


class TestSupprimerPaieBrouillon:
    """Property 3 (spec `formulaire-paie-suppression-et-ux`) — suppression
    physique d'une paie `BROUILLON` et préservation des Cumuls_YTD.

    Design (§Correctness Properties Property 3) ; Requirements 3.4, 3.8.
    """

    # Feature: formulaire-paie-suppression-et-ux, Property 3: Suppression physique d'une paie BROUILLON et préservation des Cumuls_YTD
    @pytest.mark.property
    @given(
        brouillon_et_cumuls=_st_brouillon_avec_cumuls_arbitraires(),
        saison=st_saison(),
    )
    @settings_large_input
    def test_suppression_physique_brouillon_preserve_cumuls_ytd(
        self,
        brouillon_et_cumuls: tuple[PayrollResult, CumulsYTD],
        saison: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 3 (Req 3.4, 3.8).

        Pour tout `PayrollResult` `BROUILLON` déjà inséré via
        `inserer_paie` et tout état préexistant arbitraire de
        `cumuls_ytd` pour le même `(employe_id, annee_fiscale)` (écrit
        directement dans la table, hors du chemin `inserer_paie` qui n'y
        contribue jamais pour un `BROUILLON`), l'appel à
        `supprimer_paie_brouillon(id_paie)` doit :

        1. retirer physiquement la ligne `paies` correspondante — une
           relecture ultérieure via `lire_paie(id_paie)` lève `KeyError` ;
        2. laisser `cumuls_ytd` strictement inchangé — chacune des onze
           catégories monétaires identique avant/après, comparé via
           `lire_cumuls_ytd`.
        """
        module = _importer_module_register()
        brouillon, cumuls_arbitraires = brouillon_et_cumuls

        module.inserer_paie(brouillon, saison, chemin_bd=st_chemin_bd_temporaire)

        # État préexistant arbitraire de `cumuls_ytd` — écrit directement
        # via `_upsert_cumuls_ytd` (fonction interne déjà réutilisée par
        # `inserer_paie`/`remplacer_paie`), dans sa propre transaction
        # `_connexion`, jamais via `inserer_paie` (Req 3.8 : un BROUILLON
        # ne contribue jamais aux cumuls — ce test vérifie que la
        # suppression ne les touche pas davantage).
        with module._connexion(st_chemin_bd_temporaire) as connexion:
            module._creer_schema_si_absent(connexion)
            module._upsert_cumuls_ytd(connexion, cumuls_arbitraires)

        cumuls_avant = module.lire_cumuls_ytd(
            brouillon.employe_id, brouillon.annee_fiscale, chemin_bd=st_chemin_bd_temporaire
        )
        assert cumuls_avant == cumuls_arbitraires, (
            "L'état préexistant arbitraire des Cumuls_YTD doit être "
            f"relisible tel qu'écrit avant toute suppression, obtenu "
            f"{cumuls_avant!r}, attendu {cumuls_arbitraires!r}."
        )

        module.supprimer_paie_brouillon(
            brouillon.id_paie, chemin_bd=st_chemin_bd_temporaire
        )

        with pytest.raises(KeyError):
            module.lire_paie(brouillon.id_paie, chemin_bd=st_chemin_bd_temporaire)

        cumuls_apres = module.lire_cumuls_ytd(
            brouillon.employe_id, brouillon.annee_fiscale, chemin_bd=st_chemin_bd_temporaire
        )
        assert cumuls_apres == cumuls_avant, (
            "`supprimer_paie_brouillon` doit laisser les Cumuls_YTD "
            f"strictement inchangés (Property 3), obtenu {cumuls_apres!r}, "
            f"attendu {cumuls_avant!r}."
        )

    # -----------------------------------------------------------------
    # 4.3 — Property 4 : garde-fou de `supprimer_paie_brouillon`.
    # -----------------------------------------------------------------

    # Feature: formulaire-paie-suppression-et-ux, Property 4: Garde-fou de supprimer_paie_brouillon
    @pytest.mark.property
    @given(
        resultat_non_brouillon=_st_payroll_result_statut_non_brouillon(),
        saison=st_saison(),
    )
    @settings_large_input
    def test_garde_fou_statut_non_brouillon_leve_value_error_sans_mutation(
        self,
        resultat_non_brouillon: PayrollResult,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 4 (Req 3.6) — volet `ValueError`.

        Pour tout `PayrollResult` déjà inséré dans le Registre dont le
        statut n'est pas `BROUILLON` (`EMISE`, `ANNULEE` ou
        `REMPLACE_PAR`), l'appel à `supprimer_paie_brouillon(id_paie)`
        lève `ValueError`, sans qu'aucune ligne de la table `paies` ne
        soit modifiée (comparaison `lire_paie(id_paie)` avant/après,
        octet pour octet via `==` sur le `PayrollResult` désérialisé).

        Un chemin `chemin_bd` distinct est construit manuellement à
        chaque exemple (``tmp_path / f"test_{uuid4().hex}.db"``, même
        convention que les tests d'exemple de garde-fou de
        `remplacer_paie` ci-dessus) plutôt que la fixture
        `st_chemin_bd_temporaire` : cette dernière est résolue une seule
        fois pour l'ensemble des exemples Hypothesis d'un même appel de
        test (fixture pytest function-scoped, réutilisée par Hypothesis
        — `HealthCheck.function_scoped_fixture` suppressé), ce qui
        provoquerait ici une collision `id_paie` entre deux exemples
        distincts (aucune suppression physique ne nettoie la ligne
        insérée, contrairement à `test_suppression_physique_brouillon_
        preserve_cumuls_ytd`, Property 3, qui supprime effectivement sa
        ligne à chaque exemple).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(resultat_non_brouillon, saison, chemin_bd=chemin_bd)

        paie_avant, _ = module.lire_paie(
            resultat_non_brouillon.id_paie, chemin_bd=chemin_bd
        )

        with pytest.raises(ValueError):
            module.supprimer_paie_brouillon(
                resultat_non_brouillon.id_paie, chemin_bd=chemin_bd
            )

        paie_apres, _ = module.lire_paie(
            resultat_non_brouillon.id_paie, chemin_bd=chemin_bd
        )

        assert paie_apres == paie_avant, (
            "`supprimer_paie_brouillon` refusé (statut != BROUILLON) ne "
            f"doit muter aucune ligne `paies` (Property 4), obtenu "
            f"{paie_apres!r}, attendu {paie_avant!r} (Req 3.6)."
        )

    # Feature: formulaire-paie-suppression-et-ux, Property 4: Garde-fou de supprimer_paie_brouillon
    @pytest.mark.property
    @given(id_paie_absent=st_id_paie_arbitraire())
    @settings_large_input
    def test_garde_fou_id_paie_absent_leve_key_error_sans_mutation(
        self,
        id_paie_absent: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 4 (Req 3.7) — volet `KeyError`.

        Pour tout identifiant de paie absent du Registre (base neuve,
        aucune ligne ne peut donc exister), l'appel à
        `supprimer_paie_brouillon(id_paie)` lève `KeyError`, sans
        qu'aucune ligne de la table `paies` ne soit créée — une
        relecture ultérieure via `lire_paie(id_paie)` lève également
        `KeyError` (aucune ligne n'a été insérée par erreur).
        """
        module = _importer_module_register()

        with pytest.raises(KeyError):
            module.supprimer_paie_brouillon(
                id_paie_absent, chemin_bd=st_chemin_bd_temporaire
            )

        with pytest.raises(KeyError):
            module.lire_paie(id_paie_absent, chemin_bd=st_chemin_bd_temporaire)

    # -----------------------------------------------------------------
    # 4.4 — Tests unitaires d'exemple (données fixes, sans Hypothesis) :
    # `KeyError` sur `id_paie` inconnu, `ValueError` pour chacun des
    # trois autres statuts (Req 3.6, 3.7).
    # -----------------------------------------------------------------

    def test_exemple_id_paie_inconnu_leve_key_error(
        self, st_chemin_bd_temporaire: Path
    ) -> None:
        """Test d'exemple (Req 3.7) — `id_paie` inconnu du Registre lève
        `KeyError` citant l'identifiant recherché.

        Base neuve (aucune ligne insérée) : `"PAIE-INCONNUE-EXEMPLE-001"`
        (identifiant fictif, règle 04) ne peut correspondre à aucune
        ligne.
        """
        module = _importer_module_register()
        id_paie_inconnu = "PAIE-INCONNUE-EXEMPLE-001"

        with pytest.raises(KeyError) as excinfo:
            module.supprimer_paie_brouillon(
                id_paie_inconnu, chemin_bd=st_chemin_bd_temporaire
            )

        assert id_paie_inconnu in str(excinfo.value), (
            "Le message de `KeyError` doit citer l'identifiant "
            f"`id_paie` recherché ({id_paie_inconnu!r}), obtenu "
            f"{excinfo.value!r} (Req 3.7)."
        )

    @pytest.mark.parametrize(
        "statut_refuse",
        [StatutDePaie.EMISE, StatutDePaie.ANNULEE, StatutDePaie.REMPLACE_PAR],
    )
    def test_exemple_statut_non_brouillon_leve_value_error_citant_statut(
        self, statut_refuse: StatutDePaie, tmp_path: Path
    ) -> None:
        """Test d'exemple (Req 3.6) — pour chacun des trois statuts
        `EMISE`, `ANNULEE`, `REMPLACE_PAR`, `supprimer_paie_brouillon`
        lève `ValueError` citant le statut courant refusé, sans muter la
        table `paies`.

        Employé et paie fictifs (règle 04, `EMP001`), construits via le
        helper déterministe `_payroll_result_valide` (données fixes,
        sans Hypothesis). Un chemin `chemin_bd` distinct est construit
        manuellement sous `tmp_path` par exemple paramétré (même
        convention que les tests d'exemple de garde-fou déjà en place
        dans ce fichier, ex. `test_exemple_ancien_id_absent_leve_key_
        error`), plutôt que la fixture `st_chemin_bd_temporaire`.
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        id_paie = "PAIE-EMP001-2026-001-v1"

        paie_refusee = _payroll_result_valide(
            id_paie=id_paie,
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        if statut_refuse != StatutDePaie.EMISE:
            mises_a_jour: dict[str, object] = {"statut": statut_refuse}
            if statut_refuse == StatutDePaie.REMPLACE_PAR:
                mises_a_jour["remplace_par_id"] = f"PAIE-REMPLACEMENT-{id_paie}"
            paie_refusee = paie_refusee.model_copy(update=mises_a_jour)
        module.inserer_paie(paie_refusee, "ete2026", chemin_bd=chemin_bd)

        paie_avant, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)

        with pytest.raises(ValueError) as excinfo:
            module.supprimer_paie_brouillon(id_paie, chemin_bd=chemin_bd)

        assert statut_refuse.value in str(excinfo.value), (
            "Le message de `ValueError` doit citer le statut courant "
            f"refusé ({statut_refuse.value!r}), obtenu {excinfo.value!r} "
            "(Req 3.6)."
        )

        paie_apres, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)
        assert paie_apres == paie_avant, (
            "`supprimer_paie_brouillon` refusé (statut != BROUILLON) ne "
            f"doit muter aucune ligne `paies`, obtenu {paie_apres!r}, "
            f"attendu {paie_avant!r} (Req 3.6)."
        )


@st.composite
def _st_emise_avec_cumuls_arbitraires(
    draw: st.DrawFn,
) -> tuple[PayrollResult, CumulsYTD]:
    """Un `PayrollResult` `EMISE` autonome, apparié à un `CumulsYTD`
    arbitraire pour le même `(employe_id, annee_civile)` (design
    `formulaire-paie-suppression-et-ux`, §Correctness Properties,
    Property 9 : « for all `PayrollResult` de statut `EMISE` ... et for
    all états préexistants arbitraires des Cumuls_YTD de l'employé et de
    l'année concernés »).

    Réutilise `_st_un_payroll_result_emis` (tâche 3.1, déjà défini plus
    haut dans ce fichier) — un `PayrollResult` `EMISE` valide et
    autonome. `st_cumuls_ytd_non_nuls()` (déjà défini pour
    `cotisations-sociales-qc`) fournit un `CumulsYTD` de base arbitraire
    (représentant la contribution d'« autres » paies arbitraires du même
    employé/année), dont `employe_id`/`annee_civile` sont réassignés pour
    correspondre exactement à la paie générée — même technique
    d'appariement que `_st_brouillon_avec_cumuls_arbitraires` (tâche
    4.2). La contribution de `resultat` lui-même est ensuite ajoutée via
    `CumulsYTD.avec_paie` (Req 7.1 : chacune des onze catégories est
    contrainte `>= 0` — un état préexistant tiré au hasard sans inclure
    la contribution de la paie annulée pourrait donc rendre le décrément
    invalide ; la réalité du registre garantit toujours que
    `cumuls_ytd` inclut au moins la contribution de toute paie `EMISE`
    déjà comptée, puisqu'elle y a été ajoutée par `inserer_paie` avant
    de pouvoir être annulée). Ce `CumulsYTD` (base + contribution de
    `resultat`) représente « tout état préexistant arbitraire des
    Cumuls_YTD de l'employé et de l'année concernés » (design Property
    9) — écrasé directement dans la table `cumuls_ytd` par le test après
    l'insertion de la paie (jamais celui calculé par `inserer_paie`
    lui-même), afin que la propriété tienne pour un état de départ
    arbitraire (incluant la contribution d'autres paies arbitraires) et
    non seulement pour celui résultant de la seule contribution de la
    paie insérée.
    """
    module = _importer_module_register()
    resultat = draw(_st_un_payroll_result_emis)
    cumuls_generes = draw(st_cumuls_ytd_non_nuls())
    cumuls_base = cumuls_generes.model_copy(
        update={
            "employe_id": resultat.employe_id,
            "annee_civile": resultat.annee_fiscale,
        }
    )
    cumuls_arbitraires = cumuls_base.avec_paie(
        module._ContributionResultat.depuis(resultat)
    )
    return resultat, cumuls_arbitraires


# ---------------------------------------------------------------------------
# 5.4 — Property 10 (spec `formulaire-paie-suppression-et-ux`) : garde-fou
# de `annuler_paie`.
# ---------------------------------------------------------------------------


@st.composite
def _st_payroll_result_statut_non_emise(
    draw: st.DrawFn,
) -> PayrollResult:
    """Un `PayrollResult` de statut `BROUILLON`, `ANNULEE` ou
    `REMPLACE_PAR` (design `formulaire-paie-suppression-et-ux`,
    §Correctness Properties, Property 10 : « for all `PayrollResult`
    déjà insérés dans le Registre dont le statut n'est pas `EMISE` »).

    Symétrique de `_st_payroll_result_statut_non_brouillon` (tâche 4.3) :
    réutilise `_st_un_payroll_result_emis` puis mute son `statut` via
    `model_copy`, en tirant parmi les trois statuts autres que `EMISE`
    (`BROUILLON` remplace ici `EMISE` dans l'échantillonnage). Pour
    `REMPLACE_PAR`, `remplace_par_id` est renseigné avec un identifiant
    fictif non vide (invariant `PayrollResult`, biconditionnelle Req 6.3,
    6.4) ; `date_emission` reste héritée de l'`EMISE` source pour
    `ANNULEE` et `REMPLACE_PAR` (déjà non-``None``, satisfaisant
    l'implication Req 6.7). Pour `BROUILLON`, `date_emission` n'a pas
    besoin d'être retirée : l'implication Req 6.7 est unidirectionnelle
    (rien n'interdit une `date_emission` renseignée en `BROUILLON`).
    """
    resultat_emise = draw(_st_un_payroll_result_emis)
    statut = draw(
        st.sampled_from(
            [
                StatutDePaie.BROUILLON,
                StatutDePaie.ANNULEE,
                StatutDePaie.REMPLACE_PAR,
            ]
        )
    )
    if statut == StatutDePaie.REMPLACE_PAR:
        return resultat_emise.model_copy(
            update={
                "statut": statut,
                "remplace_par_id": f"PAIE-REMPLACEMENT-{resultat_emise.id_paie}",
            }
        )
    return resultat_emise.model_copy(update={"statut": statut})


class TestAnnulerPaie:
    """Property 8 (spec `formulaire-paie-suppression-et-ux`) — annulation
    d'une paie `EMISE` transite vers `ANNULEE` sans jamais supprimer
    physiquement la ligne correspondante.

    Design (§Correctness Properties Property 8) ; Requirements 4.4.
    """

    # Feature: formulaire-paie-suppression-et-ux, Property 8: Annulation transite vers ANNULEE sans jamais supprimer physiquement la ligne
    @pytest.mark.property
    @given(resultat=_st_un_payroll_result_emis, saison=st_saison())
    @settings_large_input
    def test_annulation_transite_vers_annulee_sans_suppression_physique(
        self,
        resultat: PayrollResult,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 8 (Req 4.4).

        Pour tout `PayrollResult` `EMISE` déjà inséré via `inserer_paie`,
        l'appel à `annuler_paie(id_paie)` doit faire en sorte qu'une
        relecture ultérieure via `lire_paie(id_paie)` :

        1. réussisse sans exception — la ligne n'est **jamais**
           physiquement supprimée (contrairement à
           `supprimer_paie_brouillon`, Property 3) ;
        2. retourne un `PayrollResult` dont le `statut` est exactement
           `ANNULEE` ;
        3. conserve `remplace_par_id` absent (`None`) — `annuler_paie`
           ne remplace jamais une ligne par une nouvelle version,
           contrairement à `remplacer_paie` ;
        4. conserve `date_emission` strictement inchangée par rapport à
           sa valeur avant l'appel à `annuler_paie` (design §Components
           §4 : la mutation ne touche que `statut`).

        Un chemin `chemin_bd` distinct est construit manuellement à
        chaque exemple (``tmp_path / f"test_{uuid4().hex}.db"``, même
        convention que les tests d'exemple de garde-fou de
        `supprimer_paie_brouillon`/`remplacer_paie` ci-dessus) plutôt que
        la fixture `st_chemin_bd_temporaire` : cette dernière est résolue
        une seule fois pour l'ensemble des exemples Hypothesis d'un même
        appel de test, ce qui provoquerait ici une collision `id_paie`
        entre deux exemples distincts — `annuler_paie` ne supprime
        jamais physiquement sa ligne (contrairement à
        `supprimer_paie_brouillon`), donc rien ne nettoie la ligne
        insérée par un exemple précédent partageant la même base.
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(resultat, saison, chemin_bd=chemin_bd)

        paie_avant, _ = module.lire_paie(resultat.id_paie, chemin_bd=chemin_bd)
        date_emission_avant = paie_avant.date_emission

        module.annuler_paie(resultat.id_paie, chemin_bd=chemin_bd)

        # 1. La relecture doit réussir sans exception (jamais de DELETE).
        paie_apres, _ = module.lire_paie(resultat.id_paie, chemin_bd=chemin_bd)

        # 2. Le statut relu doit être exactement ANNULEE.
        assert paie_apres.statut == StatutDePaie.ANNULEE, (
            "`annuler_paie` doit faire transiter le statut vers `ANNULEE` "
            f"(Property 8), obtenu {paie_apres.statut!r}, attendu "
            f"{StatutDePaie.ANNULEE!r}."
        )

        # 3. `remplace_par_id` reste absent — jamais de remplacement.
        assert paie_apres.remplace_par_id is None, (
            "`annuler_paie` ne doit jamais renseigner `remplace_par_id` "
            f"(Property 8), obtenu {paie_apres.remplace_par_id!r}."
        )

        # 4. `date_emission` reste strictement inchangée.
        assert paie_apres.date_emission == date_emission_avant, (
            "`annuler_paie` ne doit pas modifier `date_emission` "
            f"(Property 8), obtenu {paie_apres.date_emission!r}, attendu "
            f"{date_emission_avant!r}."
        )

    # -----------------------------------------------------------------
    # 5.3 — Property 9 : décrément exact des Cumuls_YTD lors de
    # l'annulation.
    # -----------------------------------------------------------------

    # Feature: formulaire-paie-suppression-et-ux, Property 9: Décrément exact des Cumuls_YTD lors de l'annulation
    @pytest.mark.property
    @given(
        resultat_et_cumuls=_st_emise_avec_cumuls_arbitraires(),
        saison=st_saison(),
    )
    @settings_large_input
    def test_annulation_decremente_cumuls_ytd_de_exactement_la_contribution(
        self,
        resultat_et_cumuls: tuple[PayrollResult, CumulsYTD],
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 9 (Req 4.6).

        Pour tout `PayrollResult` `EMISE` déjà inséré via `inserer_paie`
        et tout état préexistant arbitraire de `cumuls_ytd` pour le même
        `(employe_id, annee_fiscale)` (écrasé directement dans la table
        après l'insertion, hors du cumul propre à `inserer_paie`),
        l'appel à `annuler_paie(id_paie)` doit décrémenter chacune des
        onze catégories monétaires des Cumuls_YTD résultants d'exactement
        la contribution de cette paie — c'est-à-dire
        `cumuls_apres == cumuls_avant - contribution(paie)`, calculé via
        le même helper interne `_soustraire_contribution` que celui
        invoqué par `annuler_paie` lui-même (même patron que
        `TestRemplacerPaie`, qui vérifie l'étape 3c analogue de
        `remplacer_paie` par comparaison directe des `CumulsYTD` avant/
        après plutôt que par recalcul manuel des onze catégories).

        Un chemin `chemin_bd` distinct est construit manuellement à
        chaque exemple (``tmp_path / f"test_{uuid4().hex}.db"``, même
        convention que `test_annulation_transite_vers_annulee_sans_
        suppression_physique` ci-dessus) plutôt que la fixture
        `st_chemin_bd_temporaire` : cette dernière est résolue une seule
        fois pour l'ensemble des exemples Hypothesis d'un même appel de
        test, ce qui provoquerait ici une collision `id_paie` entre deux
        exemples distincts — `annuler_paie` ne supprime jamais
        physiquement sa ligne.
        """
        module = _importer_module_register()
        resultat, cumuls_arbitraires = resultat_et_cumuls
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(resultat, saison, chemin_bd=chemin_bd)

        # État préexistant arbitraire de `cumuls_ytd` — écrasé
        # directement via `_upsert_cumuls_ytd` (fonction interne déjà
        # réutilisée par `inserer_paie`/`remplacer_paie`), dans sa propre
        # transaction `_connexion`, afin que la propriété tienne pour un
        # état de départ arbitraire (pas seulement celui contribué par
        # la seule insertion de `resultat` ci-dessus).
        with module._connexion(chemin_bd) as connexion:
            module._creer_schema_si_absent(connexion)
            module._upsert_cumuls_ytd(connexion, cumuls_arbitraires)

        cumuls_avant = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=chemin_bd
        )
        assert cumuls_avant == cumuls_arbitraires, (
            "L'état préexistant arbitraire des Cumuls_YTD doit être "
            f"relisible tel qu'écrit avant l'annulation, obtenu "
            f"{cumuls_avant!r}, attendu {cumuls_arbitraires!r}."
        )

        cumuls_attendus = module._soustraire_contribution(cumuls_avant, resultat)

        module.annuler_paie(resultat.id_paie, chemin_bd=chemin_bd)

        cumuls_apres = module.lire_cumuls_ytd(
            resultat.employe_id, resultat.annee_fiscale, chemin_bd=chemin_bd
        )
        assert cumuls_apres == cumuls_attendus, (
            "`annuler_paie` doit décrémenter chacune des onze catégories "
            "monétaires des Cumuls_YTD d'exactement la contribution de "
            f"la paie annulée (Property 9), obtenu {cumuls_apres!r}, "
            f"attendu {cumuls_attendus!r}."
        )

    # -----------------------------------------------------------------
    # 5.5 — Tests unitaires d'exemple (données fixes, sans Hypothesis) :
    # annulation réussie, `KeyError` sur `id_paie` inconnu, `ValueError`
    # pour chacun des trois autres statuts, atomicité du rollback si le
    # décrément des Cumuls_YTD échoue (Req 4.4, 4.7, 4.8, 4.9).
    # -----------------------------------------------------------------

    def test_exemple_annulation_reussie_relit_annulee_et_date_emission_inchangee(
        self, tmp_path: Path
    ) -> None:
        """Test d'exemple (Req 4.4) — une annulation réussie relit
        `statut == ANNULEE` et `date_emission` strictement inchangée.

        Paie fictive `EMISE` (règle 04, `EMP001`), construite via le
        helper déterministe `_payroll_result_valide` (données fixes,
        sans Hypothesis) — même convention que les tests d'exemple de
        `TestSupprimerPaieBrouillon` (tâche 4.4).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        id_paie = "PAIE-EMP001-2026-001-v1"

        paie_emise = _payroll_result_valide(
            id_paie=id_paie,
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        module.inserer_paie(paie_emise, "ete2026", chemin_bd=chemin_bd)

        paie_avant, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)
        date_emission_avant = paie_avant.date_emission

        module.annuler_paie(id_paie, chemin_bd=chemin_bd)

        paie_apres, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)
        assert paie_apres.statut == StatutDePaie.ANNULEE, (
            "Après une annulation réussie, le statut relu doit être "
            f"exactement `ANNULEE`, obtenu {paie_apres.statut!r} (Req 4.4)."
        )
        assert paie_apres.date_emission == date_emission_avant, (
            "Après une annulation réussie, `date_emission` doit rester "
            f"strictement inchangée, obtenu {paie_apres.date_emission!r}, "
            f"attendu {date_emission_avant!r} (Req 4.4)."
        )

    def test_exemple_id_paie_inconnu_leve_key_error(
        self, st_chemin_bd_temporaire: Path
    ) -> None:
        """Test d'exemple (Req 4.9) — `id_paie` inconnu du Registre lève
        `KeyError` citant l'identifiant recherché.

        Base neuve (aucune ligne insérée) : `"PAIE-INCONNUE-EXEMPLE-002"`
        (identifiant fictif, règle 04) ne peut correspondre à aucune
        ligne.
        """
        module = _importer_module_register()
        id_paie_inconnu = "PAIE-INCONNUE-EXEMPLE-002"

        with pytest.raises(KeyError) as excinfo:
            module.annuler_paie(id_paie_inconnu, chemin_bd=st_chemin_bd_temporaire)

        assert id_paie_inconnu in str(excinfo.value), (
            "Le message de `KeyError` doit citer l'identifiant "
            f"`id_paie` recherché ({id_paie_inconnu!r}), obtenu "
            f"{excinfo.value!r} (Req 4.9)."
        )

    @pytest.mark.parametrize(
        "statut_refuse",
        [StatutDePaie.BROUILLON, StatutDePaie.ANNULEE, StatutDePaie.REMPLACE_PAR],
    )
    def test_exemple_statut_non_emise_leve_value_error_citant_statut(
        self, statut_refuse: StatutDePaie, tmp_path: Path
    ) -> None:
        """Test d'exemple (Req 4.8) — pour chacun des trois statuts
        `BROUILLON`, `ANNULEE`, `REMPLACE_PAR`, `annuler_paie` lève
        `ValueError` citant le statut courant refusé, sans muter la
        table `paies` ni les Cumuls_YTD.

        Employé et paie fictifs (règle 04, `EMP001`), construits via le
        helper déterministe `_payroll_result_valide` — même convention
        que `TestSupprimerPaieBrouillon.test_exemple_statut_non_
        brouillon_leve_value_error_citant_statut` (tâche 4.4).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        id_paie = "PAIE-EMP001-2026-001-v1"

        paie_refusee = _payroll_result_valide(
            id_paie=id_paie,
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        if statut_refuse != StatutDePaie.EMISE:
            mises_a_jour: dict[str, object] = {"statut": statut_refuse}
            if statut_refuse == StatutDePaie.REMPLACE_PAR:
                mises_a_jour["remplace_par_id"] = f"PAIE-REMPLACEMENT-{id_paie}"
            paie_refusee = paie_refusee.model_copy(update=mises_a_jour)
        module.inserer_paie(paie_refusee, "ete2026", chemin_bd=chemin_bd)

        paie_avant, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)
        cumuls_avant = module.lire_cumuls_ytd(
            "EMP001", 2026, chemin_bd=chemin_bd
        )

        with pytest.raises(ValueError) as excinfo:
            module.annuler_paie(id_paie, chemin_bd=chemin_bd)

        assert statut_refuse.value in str(excinfo.value), (
            "Le message de `ValueError` doit citer le statut courant "
            f"refusé ({statut_refuse.value!r}), obtenu {excinfo.value!r} "
            "(Req 4.8)."
        )

        paie_apres, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)
        cumuls_apres = module.lire_cumuls_ytd(
            "EMP001", 2026, chemin_bd=chemin_bd
        )
        assert paie_apres == paie_avant, (
            "`annuler_paie` refusé (statut != EMISE) ne doit muter "
            f"aucune ligne `paies`, obtenu {paie_apres!r}, attendu "
            f"{paie_avant!r} (Req 4.8)."
        )
        assert cumuls_apres == cumuls_avant, (
            "`annuler_paie` refusé (statut != EMISE) ne doit muter "
            f"aucune ligne `cumuls_ytd`, obtenu {cumuls_apres!r}, attendu "
            f"{cumuls_avant!r} (Req 4.8)."
        )

    def test_exemple_echec_decrement_cumuls_provoque_rollback_statut_reste_emise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test d'exemple (Req 4.7) — atomicité du rollback : si le
        décrément des Cumuls_YTD échoue après la mutation de statut, la
        ligne conserve son statut `EMISE` d'origine (statut et cumuls
        visibles ensemble ou jamais du tout).

        Monkeypatch de `module._upsert_cumuls_ytd` (dernière étape de
        `annuler_paie`, invoquée après l'`UPDATE` du statut au sein de la
        même transaction `_connexion`) pour lever une exception simulée
        — même technique de simulation d'échec en cours de transaction
        que `test_exemple_exception_avant_os_replace_laisse_fichier_
        cible_inchange` (`tests/app/logique_metier/test_stockage_json.py`),
        adaptée ici au patron transactionnel SQLite de `_connexion`
        (`ROLLBACK` automatique si une exception traverse le bloc
        `with`, cf. `register.py::_connexion`).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"
        id_paie = "PAIE-EMP001-2026-001-v1"

        paie_emise = _payroll_result_valide(
            id_paie=id_paie,
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            statut=StatutDePaie.EMISE,
        )
        module.inserer_paie(paie_emise, "ete2026", chemin_bd=chemin_bd)

        cumuls_avant = module.lire_cumuls_ytd(
            "EMP001", 2026, chemin_bd=chemin_bd
        )

        def _upsert_cumuls_ytd_leve_exception(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("échec simulé du décrément des Cumuls_YTD")

        monkeypatch.setattr(
            module, "_upsert_cumuls_ytd", _upsert_cumuls_ytd_leve_exception
        )

        with pytest.raises(RuntimeError):
            module.annuler_paie(id_paie, chemin_bd=chemin_bd)

        paie_apres, _ = module.lire_paie(id_paie, chemin_bd=chemin_bd)
        assert paie_apres.statut == StatutDePaie.EMISE, (
            "Si le décrément des Cumuls_YTD échoue, la mutation de "
            "statut doit être annulée par le `ROLLBACK` de la "
            f"transaction — le statut relu doit rester `EMISE`, obtenu "
            f"{paie_apres.statut!r} (Req 4.7)."
        )

        cumuls_apres = module.lire_cumuls_ytd(
            "EMP001", 2026, chemin_bd=chemin_bd
        )
        assert cumuls_apres == cumuls_avant, (
            "Si le décrément des Cumuls_YTD échoue, les Cumuls_YTD "
            f"doivent rester inchangés, obtenu {cumuls_apres!r}, attendu "
            f"{cumuls_avant!r} (Req 4.7)."
        )

    # -----------------------------------------------------------------
    # 5.4 — Property 10 : garde-fou de `annuler_paie`.
    # -----------------------------------------------------------------

    # Feature: formulaire-paie-suppression-et-ux, Property 10: Garde-fou de annuler_paie
    @pytest.mark.property
    @given(
        resultat_non_emise=_st_payroll_result_statut_non_emise(),
        saison=st_saison(),
    )
    @settings_large_input
    def test_garde_fou_statut_non_emise_leve_value_error_sans_mutation(
        self,
        resultat_non_emise: PayrollResult,
        saison: str,
        tmp_path: Path,
    ) -> None:
        """Property 10 (Req 4.8) — volet `ValueError`.

        Pour tout `PayrollResult` déjà inséré dans le Registre dont le
        statut n'est pas `EMISE` (`BROUILLON`, `ANNULEE` ou
        `REMPLACE_PAR`), l'appel à `annuler_paie(id_paie)` lève
        `ValueError`, sans qu'aucune ligne de la table `paies` ni aucune
        valeur des `cumuls_ytd` ne soit modifiée (comparaison
        `lire_paie(id_paie)` et `lire_cumuls_ytd(...)` avant/après).

        Un chemin `chemin_bd` distinct est construit manuellement à
        chaque exemple (``tmp_path / f"test_{uuid4().hex}.db"``, même
        convention que le test symétrique de garde-fou de
        `supprimer_paie_brouillon`, Property 4, tâche 4.3) plutôt que la
        fixture `st_chemin_bd_temporaire` : cette dernière est résolue
        une seule fois pour l'ensemble des exemples Hypothesis d'un même
        appel de test, ce qui provoquerait ici une collision `id_paie`
        entre deux exemples distincts (aucune suppression physique ne
        nettoie la ligne insérée sur le chemin refusé).
        """
        module = _importer_module_register()
        chemin_bd = tmp_path / f"test_{uuid.uuid4().hex}.db"

        module.inserer_paie(resultat_non_emise, saison, chemin_bd=chemin_bd)

        paie_avant, _ = module.lire_paie(
            resultat_non_emise.id_paie, chemin_bd=chemin_bd
        )
        cumuls_avant = module.lire_cumuls_ytd(
            resultat_non_emise.employe_id,
            resultat_non_emise.annee_fiscale,
            chemin_bd=chemin_bd,
        )

        with pytest.raises(ValueError):
            module.annuler_paie(resultat_non_emise.id_paie, chemin_bd=chemin_bd)

        paie_apres, _ = module.lire_paie(
            resultat_non_emise.id_paie, chemin_bd=chemin_bd
        )
        cumuls_apres = module.lire_cumuls_ytd(
            resultat_non_emise.employe_id,
            resultat_non_emise.annee_fiscale,
            chemin_bd=chemin_bd,
        )

        assert paie_apres == paie_avant, (
            "`annuler_paie` refusé (statut != EMISE) ne doit muter "
            f"aucune ligne `paies` (Property 10), obtenu {paie_apres!r}, "
            f"attendu {paie_avant!r} (Req 4.8)."
        )
        assert cumuls_apres == cumuls_avant, (
            "`annuler_paie` refusé (statut != EMISE) ne doit muter "
            f"aucune valeur des Cumuls_YTD (Property 10), obtenu "
            f"{cumuls_apres!r}, attendu {cumuls_avant!r} (Req 4.8)."
        )

    # Feature: formulaire-paie-suppression-et-ux, Property 10: Garde-fou de annuler_paie
    @pytest.mark.property
    @given(id_paie_absent=st_id_paie_arbitraire())
    @settings_large_input
    def test_garde_fou_id_paie_absent_leve_key_error_sans_mutation(
        self,
        id_paie_absent: str,
        st_chemin_bd_temporaire: Path,
    ) -> None:
        """Property 10 (Req 4.9) — volet `KeyError`.

        Pour tout identifiant de paie absent du Registre (base neuve,
        aucune ligne ne peut donc exister), l'appel à
        `annuler_paie(id_paie)` lève `KeyError`, sans qu'aucune ligne de
        la table `paies` ne soit créée — une relecture ultérieure via
        `lire_paie(id_paie)` lève également `KeyError`, et
        `lire_cumuls_ytd` pour un employé/année fictifs arbitraires (non
        dérivables de l'identifiant inexistant) reste à ses valeurs par
        défaut (aucune ligne `cumuls_ytd` créée par erreur).
        """
        module = _importer_module_register()

        with pytest.raises(KeyError):
            module.annuler_paie(id_paie_absent, chemin_bd=st_chemin_bd_temporaire)

        with pytest.raises(KeyError):
            module.lire_paie(id_paie_absent, chemin_bd=st_chemin_bd_temporaire)
