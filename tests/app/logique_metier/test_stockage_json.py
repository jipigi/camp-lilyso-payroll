"""Property tests et tests d'exemple pour `app/logique_metier/stockage_json.py`.

Spec de référence : ``interface-streamlit`` — tâche 2.1 (squelette du
fichier et test de la Property 3).
Design de référence : ``design.md`` §Components §1 (`ecrire_atomique`,
`lire_texte_ou_defaut`) et §Correctness Properties 3.

Ce fichier porte l'ensemble des property tests et tests d'exemple des deux
primitives d'E/S génériques ``app/logique_metier/stockage_json.py``
(`ecrire_atomique`, `lire_texte_ou_defaut`). La tâche 2.1 pose le
**squelette** : le module docstring, les imports, et la Property 3
(classe ``TestEcritureAtomique``) — écriture atomique et absence de
fichier temporaire résiduel, y compris lorsqu'une exception interrompt
l'écriture avant la substitution finale (`os.replace`). La tâche 2.2
ajoute :

- ``TestLireTexteOuDefaut`` — tests d'exemple de `lire_texte_ou_defaut`
  (chemin inexistant → `defaut` ; chemin existant → contenu exact).

L'unique propriété couverte par ce fichier (design.md §Correctness
Properties) :

3. **Property 3 — Écriture atomique des annuaires JSON** : pour tout
   contenu textuel arbitraire, après `ecrire_atomique(chemin, contenu)`,
   `chemin.read_text() == contenu` et aucun fichier `*.tmp` résiduel ne
   subsiste dans le répertoire parent ; si l'écriture est interrompue par
   une exception avant `os.replace`, le fichier cible reste dans son état
   antérieur (inchangé ou absent) et aucun `*.tmp` ne subsiste.

Discipline règle 06 (TDD — tests avant code) :
``app/logique_metier/stockage_json.py`` n'existe **pas encore** à ce
stade. Comme ``test_register.py`` (spec ``net-cumuls-registre``, tâche
3.1) et ``test_net_pay.py`` (spec ``net-cumuls-registre``, tâche 2.1), ce
fichier **importe localement** le module sous test (via un helper
``_importer_module_stockage_json`` appelé au sein de chaque test) afin
que la **collecte** pytest de ce fichier réussisse même tant que le
module cible est absent. À l'exécution, chaque test échoue alors avec
``ModuleNotFoundError`` sur ``app.logique_metier.stockage_json`` — c'est
le comportement **attendu et correct** (état rouge intentionnel) tant que
la tâche 12.1 (implémentation) n'a pas été réalisée (checkpoint de la
tâche 11 du plan).

Règle 01 : ces primitives manipulent du texte brut, jamais de montant
monétaire — la règle ``Decimal`` ne s'y applique pas.
Règle 04 : chaque test injecte systématiquement un chemin temporaire
(``tmp_path``) — jamais l'un des deux chemins de production
(`chemin_annuaire_employes_production()` /
`chemin_annuaire_coordonnees_production()`).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec test_register.py /
# test_net_pay.py). Le nombre d'exemples est piloté par le profil
# Hypothesis actif (voir tests/conftest.py : dev=15 par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_defaut = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

#: Nom qualifié du module sous test (règle 06 — importé localement pour ne
#: pas faire échouer la collecte tant que la tâche 12.1 n'a pas créé le
#: module).
_NOM_MODULE_CIBLE = "app.logique_metier.stockage_json"


# ---------------------------------------------------------------------------
# Helper interne — import local du module cible (règle 06).
# ---------------------------------------------------------------------------


def _importer_module_stockage_json() -> ModuleType:
    """Importe ``app.logique_metier.stockage_json`` au moment de l'appel.

    Règle 06 (TDD — tests avant code) : le module cible n'existe pas
    encore. En différant l'import à l'intérieur des tests (plutôt qu'au
    niveau module), la **collecte** pytest de ce fichier reste possible ;
    seule l'**exécution** de chaque test lève ``ModuleNotFoundError`` tant
    que la tâche 12.1 n'a pas créé le module — état rouge attendu et
    correct.
    """
    return importlib.import_module(_NOM_MODULE_CIBLE)


# ---------------------------------------------------------------------------
# 2.1 — Property 3 : Écriture atomique des annuaires JSON.
# ---------------------------------------------------------------------------


class TestEcritureAtomique:
    """Property 3 — écriture atomique des annuaires JSON.

    Design (§Correctness Properties 3, §Components §1) ; Requirements
    2.6, 20.5. Pour tout contenu textuel arbitraire, après
    ``ecrire_atomique(chemin, contenu)``, ``chemin.read_text() ==
    contenu`` et aucun fichier ``*.tmp`` résiduel ne subsiste dans le
    répertoire parent ; si l'écriture est interrompue par une exception
    avant la substitution finale (``os.replace``), le fichier cible reste
    dans son état antérieur et aucun ``*.tmp`` ne subsiste.
    """

    # Feature: interface-streamlit, Property 3: Écriture atomique des annuaires JSON
    @pytest.mark.property
    @given(contenu=st.text())
    @settings_defaut
    def test_ecriture_atomique_lisible_et_sans_tmp_residuel(
        self, contenu: str, tmp_path: Path
    ) -> None:
        """Property 3 — cas nominal (Req 2.6, 20.5).

        Après ``ecrire_atomique(chemin, contenu)`` sur un fichier neuf,
        le contenu relu est identique au contenu écrit et aucun fichier
        ``*.tmp`` ne subsiste dans le répertoire parent.
        """
        module = _importer_module_stockage_json()
        chemin = tmp_path / "annuaire.json"

        module.ecrire_atomique(chemin, contenu)

        assert chemin.read_text(encoding="utf-8", newline="") == contenu, (
            "Le contenu relu après `ecrire_atomique` doit être identique "
            "au contenu écrit (Property 3)."
        )

        fichiers_tmp_residuels = list(tmp_path.glob("*.tmp"))
        assert fichiers_tmp_residuels == [], (
            "Aucun fichier `*.tmp` résiduel ne doit subsister dans le "
            f"répertoire parent après un appel réussi, obtenu "
            f"{fichiers_tmp_residuels!r} (Property 3)."
        )

    # Feature: interface-streamlit, Property 3: Écriture atomique des annuaires JSON
    def test_exemple_exception_avant_os_replace_laisse_fichier_cible_inchange(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Property 3 — cas d'interruption avant `os.replace` (Req 2.6, 20.5).

        En monkeypatchant ``os.replace`` (importé dans le module cible)
        pour lever une exception, ``ecrire_atomique`` doit :

        - propager cette exception (aucune interception silencieuse) ;
        - laisser le fichier cible dans son état antérieur (inchangé
          s'il existait déjà, absent s'il n'existait pas) ;
        - ne laisser subsister aucun fichier ``*.tmp`` résiduel.
        """
        module = _importer_module_stockage_json()
        chemin = tmp_path / "annuaire.json"
        contenu_initial = "contenu-anterieur"
        chemin.write_text(contenu_initial, encoding="utf-8")

        def _os_replace_leve_exception(*_args: object, **_kwargs: object) -> None:
            raise OSError("échec simulé avant la substitution finale")

        monkeypatch.setattr(module.os, "replace", _os_replace_leve_exception)

        with pytest.raises(OSError):
            module.ecrire_atomique(chemin, "contenu-nouveau-jamais-visible")

        assert chemin.read_text(encoding="utf-8") == contenu_initial, (
            "Le fichier cible doit rester dans son état antérieur après "
            "une exception levée avant `os.replace` (Property 3)."
        )

        fichiers_tmp_residuels = list(tmp_path.glob("*.tmp"))
        assert fichiers_tmp_residuels == [], (
            "Aucun fichier `*.tmp` résiduel ne doit subsister après une "
            f"exception avant `os.replace`, obtenu "
            f"{fichiers_tmp_residuels!r} (Property 3)."
        )


# ---------------------------------------------------------------------------
# 2.2 — Tests d'exemple de `lire_texte_ou_defaut`.
# ---------------------------------------------------------------------------


class TestLireTexteOuDefaut:
    """Tests d'exemple de `lire_texte_ou_defaut` (Req 2.2, 20.7).

    Design (§Components §1) : ``lire_texte_ou_defaut`` retourne ``defaut``
    sans lever d'exception lorsque ``chemin`` n'existe pas encore (cas
    nominal d'un annuaire jamais encore écrit), et retourne le contenu
    exact du fichier lorsque ``chemin`` existe.
    """

    def test_exemple_chemin_inexistant_retourne_defaut_sans_exception(
        self, tmp_path: Path
    ) -> None:
        """`lire_texte_ou_defaut` sur un chemin inexistant (Req 2.2, 20.7).

        Aucune exception n'est levée ; la valeur ``defaut`` fournie est
        retournée telle quelle.
        """
        module = _importer_module_stockage_json()
        chemin = tmp_path / "annuaire_jamais_ecrit.json"

        resultat = module.lire_texte_ou_defaut(chemin, defaut="[]")

        assert resultat == "[]", (
            "`lire_texte_ou_defaut` doit retourner `defaut` sans "
            f"exception quand `chemin` n'existe pas, obtenu {resultat!r}."
        )

    def test_exemple_chemin_existant_retourne_contenu_exact_du_fichier(
        self, tmp_path: Path
    ) -> None:
        """`lire_texte_ou_defaut` sur un chemin existant (Req 2.2, 20.7).

        Le contenu exact du fichier est retourné, sans altération, et
        indépendamment de la valeur de ``defaut``.
        """
        module = _importer_module_stockage_json()
        chemin = tmp_path / "annuaire.json"
        contenu_attendu = '[{"id": "EMP001"}]'
        chemin.write_text(contenu_attendu, encoding="utf-8")

        resultat = module.lire_texte_ou_defaut(chemin, defaut="[]")

        assert resultat == contenu_attendu, (
            "`lire_texte_ou_defaut` doit retourner le contenu exact du "
            f"fichier quand `chemin` existe, obtenu {resultat!r}."
        )
