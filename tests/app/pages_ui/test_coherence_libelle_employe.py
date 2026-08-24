"""Test unitaire de cohérence du Libelle_Employe entre écrans.

Spec de référence : ``formulaire-paie-suppression-et-ux`` — tâche 2.2.
Design de référence : ``design.md`` §Components et Interfaces #1
(`annuaire_coordonnees.py::libelle_employe`) et #2 (sélecteur d'employé
du Formulaire_Paie) ; §Correctness Properties Property 1 (règles de
repli exhaustives, ``Validates: Requirements 1.1, 1.2, 1.3, 1.4``).

Requirement 1.4 : « THE Formulaire_Paie SHALL produire, pour un même
employé et les mêmes Fiche_Coordonnees, un Libelle_Employe strictement
identique à celui affiché par la Fiche_Employe_Detaillee pour ce même
employé. »

Le Selecteur_Employe_Formulaire (`app/pages_ui/formulaire_paie.py::
_section_nouvelle_paie`) et la Fiche_Employe_Detaillee
(`app/pages_ui/fiche_employe_detaillee.py::render`) construisent tous
deux leur ``format_func`` par un appel direct à
``libelle_employe(eid, coordonnees_par_employe_id)`` — la même fonction
pure importée depuis ``app.logique_metier.annuaire_coordonnees`` (tâches
1.4 et 2.1, déjà complétées), plutôt qu'une logique de formatage locale
dupliquée à chaque écran. ``st.selectbox`` étant un widget Streamlit
difficile à exercer sans harnais de test dédié (aucun
``streamlit.testing.v1.AppTest`` n'est utilisé ailleurs dans cette
suite pour les modules de ``app/pages_ui/**`` — voir
``tests/app/pages_ui/test_formulaire_paie.py``, qui mocke ``st``
directement), ce test vérifie la cohérence à un niveau plus direct et
tout aussi significatif :

1. Les deux modules importent et exposent `libelle_employe` comme le
   **même objet fonction** (même source, `annuaire_coordonnees.py`) —
   aucune redéfinition ni logique de formatage locale dans l'un ou
   l'autre module.
2. Pour un même `employe_id` et les mêmes `FicheCoordonnees` (couvrant
   les quatre cas de repli du design), invoquer cette fonction via la
   référence importée par chaque module produit un résultat strictement
   identique.

Règle 04 : identifiants fictifs `EMP001`/`EMP002` uniquement, aucune
donnée personnelle réelle.
"""

from __future__ import annotations

import app.pages_ui.fiche_employe_detaillee as fiche_employe_detaillee
import app.pages_ui.formulaire_paie as formulaire_paie
from app.logique_metier.annuaire_coordonnees import FicheCoordonnees


class TestCoherenceLibelleEmployeEntreEcrans:
    """Cohérence du Libelle_Employe entre le Selecteur_Employe_Formulaire
    (`formulaire_paie.py`) et la Fiche_Employe_Detaillee
    (`fiche_employe_detaillee.py`) — Requirement 1.4."""

    def test_les_deux_ecrans_importent_la_meme_fonction_libelle_employe(
        self,
    ) -> None:
        """`formulaire_paie.libelle_employe` et
        `fiche_employe_detaillee.libelle_employe` sont le **même objet
        fonction**, importé depuis `annuaire_coordonnees.py` — aucune
        logique de formatage locale dupliquée dans l'un ou l'autre
        écran (Req 2.1, 2.2)."""
        assert (
            formulaire_paie.libelle_employe
            is fiche_employe_detaillee.libelle_employe
        )

    def test_libelle_identique_pour_employe_avec_coordonnees_completes(
        self,
    ) -> None:
        """**Validates: Requirements 1.1, 1.4**"""
        coordonnees_par_employe_id = {
            "EMP001": FicheCoordonnees(
                employe_id="EMP001",
                prenom="Fictif",
                nom="EmployeUn",
                courriel="fictif.employeun@example.invalid",
            )
        }

        libelle_formulaire = formulaire_paie.libelle_employe(
            "EMP001", coordonnees_par_employe_id
        )
        libelle_fiche = fiche_employe_detaillee.libelle_employe(
            "EMP001", coordonnees_par_employe_id
        )

        assert libelle_formulaire == libelle_fiche
        assert libelle_formulaire == "Fictif EmployeUn (fictif.employeun@example.invalid)"

    def test_libelle_identique_pour_employe_avec_prenom_nom_sans_courriel(
        self,
    ) -> None:
        """**Validates: Requirements 1.2, 1.4**"""
        coordonnees_par_employe_id = {
            "EMP001": FicheCoordonnees(
                employe_id="EMP001",
                prenom="Fictif",
                nom="EmployeUn",
                courriel=None,
            )
        }

        libelle_formulaire = formulaire_paie.libelle_employe(
            "EMP001", coordonnees_par_employe_id
        )
        libelle_fiche = fiche_employe_detaillee.libelle_employe(
            "EMP001", coordonnees_par_employe_id
        )

        assert libelle_formulaire == libelle_fiche
        assert libelle_formulaire == "Fictif EmployeUn"

    def test_libelle_identique_pour_employe_sans_fiche_coordonnees(self) -> None:
        """**Validates: Requirements 1.3, 1.4**"""
        coordonnees_par_employe_id: dict[str, FicheCoordonnees] = {}

        libelle_formulaire = formulaire_paie.libelle_employe(
            "EMP002", coordonnees_par_employe_id
        )
        libelle_fiche = fiche_employe_detaillee.libelle_employe(
            "EMP002", coordonnees_par_employe_id
        )

        assert libelle_formulaire == libelle_fiche
        assert libelle_formulaire == "EMP002"

    def test_libelle_identique_pour_fiche_sans_prenom_ni_nom(self) -> None:
        """**Validates: Requirements 1.3, 1.4**"""
        coordonnees_par_employe_id = {
            "EMP002": FicheCoordonnees(
                employe_id="EMP002",
                prenom=None,
                nom="",
                courriel="fictif.employedeux@example.invalid",
            )
        }

        libelle_formulaire = formulaire_paie.libelle_employe(
            "EMP002", coordonnees_par_employe_id
        )
        libelle_fiche = fiche_employe_detaillee.libelle_employe(
            "EMP002", coordonnees_par_employe_id
        )

        assert libelle_formulaire == libelle_fiche
        assert libelle_formulaire == "EMP002"
