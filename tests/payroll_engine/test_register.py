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

from models._validators import _parse_json_reject_floats
from models.cumuls import CumulsYTD
from models.enums import StatutDePaie
from models.payroll_result import PayrollResult
from tests.strategies import (
    st_chemin_bd_temporaire,  # noqa: F401  (fixture pytest, résolue par nom de paramètre)
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
    "inserer_paie": ("resultat", "saison", "chemin_bd"),
    "lire_paie": ("id_paie", "chemin_bd"),
    "lire_historique_paie": (
        "employe_id",
        "annee_fiscale",
        "numero_periode",
        "chemin_bd",
    ),
    "lire_cumuls_ytd": ("employe_id", "annee_civile", "chemin_bd"),
    "remplacer_paie": ("ancien_id", "nouveau_resultat", "saison", "chemin_bd"),
}


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
        relu = module.lire_paie(resultat.id_paie, chemin_bd=st_chemin_bd_temporaire)

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

        ancien_apres_remplacement = module.lire_paie(
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

        paie_avant = module.lire_paie(
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

        paie_apres = module.lire_paie(
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
