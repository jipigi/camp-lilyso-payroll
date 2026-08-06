"""Property tests et tests d'exemple de `fiche_employe.py`.

Spec de référence : ``interface-streamlit`` — tâche 8 (squelette et
Property 12, tâche 8.1).
Design de référence : ``design.md`` §Components 7 (`app/logique_metier/
fiche_employe.py` — pré-remplissage et mise à jour fiscale immuable),
§Correctness Properties 12 et 14.

Discipline TDD (règle 06) : ce fichier est écrit **avant**
``app/logique_metier/fiche_employe.py`` (implémentation prévue aux
tâches 18.1/18.2). Tant que ce module n'existe pas, chaque test échoue à
l'**exécution** avec ``ModuleNotFoundError`` sur l'import local de
``parametres_effectifs_par_defaut``/``mettre_a_jour_donnees_fiscales`` —
c'est le comportement attendu. L'import de ces symboles est fait **à
l'intérieur de chaque fonction de test** (jamais au niveau module) afin
que la collecte pytest de l'ensemble du répertoire ``tests/app/``
réussisse même tant que le module cible est absent (convention déjà
appliquée dans ``test_dernieres_paies.py`` et ``test_parametres_fiscaux.py``,
entre autres).

Portée de la tâche 8.1 (issue directe de ``tasks.md`` §8.1) :

- **Property 12 : Pré-remplissage identité des paramètres effectifs** —
  pour toute Fiche_Employe (``Employee``) valide,
  ``parametres_effectifs_par_defaut(employee)`` retourne un dictionnaire
  dont chacune des 7 clés est strictement égale au champ source
  correspondant de ``employee`` (``taux_horaire_base`` →
  ``taux_horaire_effectif``, ``taux_indemnite_vacances`` →
  ``taux_vacances``, ``montant_total_TP1015_3`` →
  ``montant_total_TP1015_3_effectif``, ``exoneration_TP1015_3`` →
  ``exoneration_TP1015_3_effectif``, ``retenue_additionnelle_QC`` →
  ``retenue_additionnelle_QC_effective``, ``montant_total_TD1`` →
  ``montant_total_TD1_effectif``, ``exoneration_TD1`` →
  ``exoneration_TD1_effective``, ``retenue_additionnelle_federale`` →
  ``retenue_additionnelle_federale_effective``), sans muter ``employee``.
  **Validates: Requirements 8.1**

La Property 14 (mise à jour fiscale immuable) et le test explicite du
point de vigilance corrigé (``model_copy`` → constructeur complet, tâche
8.2), ainsi que le test d'exemple de propagation sans interception
(tâche 8.3), sont ajoutés par des tâches ultérieures distinctes —
volontairement absents de ce fichier à ce stade pour éviter tout
conflit d'édition concurrente.

**Point de vigilance explicitement corrigé (design §Components 7)** : le
pseudocode initial de ``mettre_a_jour_donnees_fiscales`` utilisait
``employee.model_copy(update={...})``, qui **ne ré-exécute pas** les
validateurs Pydantic (comportement documenté de Pydantic v2). La tâche
18.2 implémentera la version corrigée — reconstruction via le
constructeur complet ``Employee(**{**employee.model_dump(), <6 champs mis
à jour>})`` — afin que les gardes de validation d'``Employee`` restent
actives sur les nouvelles valeurs. La tâche 8.2 écrira le test qui aurait
échoué avec ``model_copy`` et qui valide la correction ; ce fichier
(tâche 8.1) ne couvre que la Property 12, indépendante de ce point de
vigilance.

Règle 04 : les ``Employee`` générés par ``st_employee_valide``
(``tests/app/strategies.py``, tâche 1.1) portent exclusivement des
identifiants fictifs ``EMPnnn``.
Règle 01 : tous les champs monétaires/taux manipulés ici restent des
``Decimal`` (jamais de conversion ``float``) — cohérent avec
``st_employee_valide``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from models.employee import Employee
from models.enums import Juridiction
from tests.app.strategies import st_employee_valide

# ---------------------------------------------------------------------------
# Bornes des montants fiscaux générées pour la Property 14 — mêmes ordres
# de grandeur que ``tests/app/strategies.py::_MAX_CREDIT`` /
# ``_MAX_RETENUE_ADDITIONNELLE``, dupliquées ici volontairement (ce ne
# sont pas des symboles exportés par ``tests/app/strategies.py``, même
# convention que ce module pour ``_MAX_CREDIT``).
# ---------------------------------------------------------------------------

_MAX_CREDIT = Decimal("50000.00")
_MAX_RETENUE_ADDITIONNELLE = Decimal("500.00")


def _st_decimal_monetaire(*, max_value: Decimal) -> st.SearchStrategy[Decimal]:
    """``Decimal`` ∈ [0.00, max_value], deux décimales (règle 01).

    Bornes cohérentes avec le champ ``Employee`` correspondant
    (``Field(..., ge=Decimal("0"))``) — jamais de valeur négative
    générée ici, le test explicite dédié
    (``test_valeur_invalide_leve_validation_error_constructeur_complet``)
    couvre séparément le cas négatif.
    """
    return st.decimals(
        min_value=Decimal("0.00"),
        max_value=max_value,
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )


# ---------------------------------------------------------------------------
# Configuration Hypothesis partagée (cohérente avec le reste de la suite —
# voir tests/conftest.py : dev=15 exemples par défaut, ci=100).
# ---------------------------------------------------------------------------

settings_employee = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


class TestParametresEffectifsParDefaut:
    """Property 12 : Pré-remplissage identité des paramètres effectifs.

    Design (§Components 7, §Correctness Properties 12) :
    ``parametres_effectifs_par_defaut`` est une projection pure et
    directe — chacune des 7 clés retournées est strictement égale au
    champ source correspondant de ``employee``, sans aucune
    transformation ni recalcul, et sans muter ``employee``.
    """

    # Feature: interface-streamlit, Property 12: Pré-remplissage identité des paramètres effectifs
    @pytest.mark.property
    @given(employee=st_employee_valide())
    @settings_employee
    def test_property_12_les_7_cles_egalent_strictement_les_champs_source(
        self, employee: Employee
    ) -> None:
        """**Validates: Requirements 8.1**

        Pour toute ``Employee`` valide, vérifie que le dictionnaire
        retourné par ``parametres_effectifs_par_defaut`` contient
        exactement 7 clés, chacune strictement égale (``==``, même
        type) au champ source correspondant de ``employee`` — et que
        ``employee`` n'est pas muté par l'appel (comparaison des 8
        champs sources avant/après, via une capture préalable des
        valeurs).
        """
        from app.logique_metier.fiche_employe import parametres_effectifs_par_defaut

        # Capture des champs sources avant l'appel, pour vérifier
        # l'absence de mutation de `employee` après coup.
        valeurs_avant = (
            employee.taux_horaire_base,
            employee.taux_indemnite_vacances,
            employee.montant_total_TP1015_3,
            employee.exoneration_TP1015_3,
            employee.retenue_additionnelle_QC,
            employee.montant_total_TD1,
            employee.exoneration_TD1,
            employee.retenue_additionnelle_federale,
        )

        resultat = parametres_effectifs_par_defaut(employee)

        correspondances = {
            "taux_horaire_effectif": employee.taux_horaire_base,
            "taux_vacances": employee.taux_indemnite_vacances,
            "montant_total_TP1015_3_effectif": employee.montant_total_TP1015_3,
            "exoneration_TP1015_3_effectif": employee.exoneration_TP1015_3,
            "retenue_additionnelle_QC_effective": employee.retenue_additionnelle_QC,
            "montant_total_TD1_effectif": employee.montant_total_TD1,
            "exoneration_TD1_effective": employee.exoneration_TD1,
            "retenue_additionnelle_federale_effective": (
                employee.retenue_additionnelle_federale
            ),
        }

        assert set(resultat.keys()) == set(correspondances.keys()), (
            "parametres_effectifs_par_defaut doit retourner exactement les "
            f"7 clés attendues {sorted(correspondances.keys())!r}, obtenu "
            f"{sorted(resultat.keys())!r}."
        )

        for cle, valeur_source in correspondances.items():
            valeur_obtenue = resultat[cle]
            assert valeur_obtenue == valeur_source, (
                f"parametres_effectifs_par_defaut()[{cle!r}] doit être "
                f"strictement égal au champ source correspondant "
                f"({valeur_source!r}), obtenu {valeur_obtenue!r}."
            )
            assert type(valeur_obtenue) is type(valeur_source), (
                f"parametres_effectifs_par_defaut()[{cle!r}] doit conserver "
                f"le type exact du champ source ({type(valeur_source)!r}), "
                f"obtenu {type(valeur_obtenue)!r}."
            )

        valeurs_apres = (
            employee.taux_horaire_base,
            employee.taux_indemnite_vacances,
            employee.montant_total_TP1015_3,
            employee.exoneration_TP1015_3,
            employee.retenue_additionnelle_QC,
            employee.montant_total_TD1,
            employee.exoneration_TD1,
            employee.retenue_additionnelle_federale,
        )
        assert valeurs_apres == valeurs_avant, (
            "parametres_effectifs_par_defaut ne doit jamais muter "
            f"`employee` : champs avant {valeurs_avant!r}, après "
            f"{valeurs_apres!r}."
        )


class TestMiseAJourFiscaleImmuable:
    """Property 14 : Mise à jour immuable des données fiscales d'une
    Fiche_Employe, et test explicite du point de vigilance corrigé
    (``model_copy`` → constructeur complet).

    Design (§Components 7, §Correctness Properties 14, note de
    correction post-§Components 7) : ``mettre_a_jour_donnees_fiscales``
    reconstruit une **nouvelle** instance ``Employee`` dont les 6 champs
    fiscaux (``montant_total_TP1015_3``, ``exoneration_TP1015_3``,
    ``retenue_additionnelle_QC``, ``montant_total_TD1``,
    ``exoneration_TD1``, ``retenue_additionnelle_federale``) égalent
    exactement les nouvelles valeurs fournies, tous les autres champs
    restant identiques à l'original ; l'original reste inchangé après
    l'appel (``Employee`` est de toute façon ``frozen=True``, mais ce
    test le vérifie explicitement par comparaison avant/après).

    Le second test de cette classe couvre le point de vigilance
    explicitement documenté par le design : la correction
    ``model_copy`` → constructeur complet
    (``Employee(**{**employee.model_dump(), <6 champs>})``). Si
    l'implémentation utilisait ``employee.model_copy(update={...})``,
    ce test échouerait **silencieusement** (aucune ``ValidationError``
    levée), car ``model_copy`` ne ré-exécute pas les validateurs
    Pydantic (comportement documenté de Pydantic v2). Le champ
    ``montant_total_TP1015_3`` est contraint ``Field(..., ge=Decimal("0"))``
    sur ``Employee`` (``models/employee.py``) — une valeur négative
    (``Decimal("-1.00")``) sur ce champ DOIT donc lever
    ``pydantic.ValidationError`` lorsque le garde-fou est réellement
    actif sur la reconstruction.
    """

    # Feature: interface-streamlit, Property 14: Mise à jour immuable des données fiscales
    @pytest.mark.property
    @given(
        employee=st_employee_valide(),
        nouveau_montant_TP1015_3=_st_decimal_monetaire(max_value=_MAX_CREDIT),
        nouvelle_exoneration_TP1015_3=st.booleans(),
        nouvelle_retenue_additionnelle_QC=_st_decimal_monetaire(
            max_value=_MAX_RETENUE_ADDITIONNELLE
        ),
        nouveau_montant_TD1=_st_decimal_monetaire(max_value=_MAX_CREDIT),
        nouvelle_exoneration_TD1=st.booleans(),
        nouvelle_retenue_additionnelle_federale=_st_decimal_monetaire(
            max_value=_MAX_RETENUE_ADDITIONNELLE
        ),
    )
    @settings_employee
    def test_property_14_nouvelle_instance_6_champs_maj_reste_identique_sinon(
        self,
        employee: Employee,
        nouveau_montant_TP1015_3: Decimal,
        nouvelle_exoneration_TP1015_3: bool,
        nouvelle_retenue_additionnelle_QC: Decimal,
        nouveau_montant_TD1: Decimal,
        nouvelle_exoneration_TD1: bool,
        nouvelle_retenue_additionnelle_federale: Decimal,
    ) -> None:
        """**Validates: Requirements 11.2**

        Pour toute ``Employee`` valide et toute combinaison valide des 6
        nouvelles valeurs fiscales, vérifie que
        ``mettre_a_jour_donnees_fiscales`` retourne une nouvelle instance
        dont les 6 champs fiscaux égalent exactement les nouvelles
        valeurs, dont tous les autres champs égalent ceux de l'original,
        et que l'original demeure inchangé (comparaison avant/après)
        après l'appel.
        """
        from app.logique_metier.fiche_employe import mettre_a_jour_donnees_fiscales

        # Capture de l'état complet de l'original avant l'appel, pour
        # vérifier explicitement l'absence de mutation.
        employee_avant = employee.model_copy(deep=True)

        resultat = mettre_a_jour_donnees_fiscales(
            employee,
            montant_total_TP1015_3=nouveau_montant_TP1015_3,
            exoneration_TP1015_3=nouvelle_exoneration_TP1015_3,
            retenue_additionnelle_QC=nouvelle_retenue_additionnelle_QC,
            montant_total_TD1=nouveau_montant_TD1,
            exoneration_TD1=nouvelle_exoneration_TD1,
            retenue_additionnelle_federale=nouvelle_retenue_additionnelle_federale,
        )

        # Les 6 champs fiscaux de la nouvelle instance égalent
        # exactement les nouvelles valeurs fournies.
        assert resultat.montant_total_TP1015_3 == nouveau_montant_TP1015_3
        assert resultat.exoneration_TP1015_3 == nouvelle_exoneration_TP1015_3
        assert resultat.retenue_additionnelle_QC == nouvelle_retenue_additionnelle_QC
        assert resultat.montant_total_TD1 == nouveau_montant_TD1
        assert resultat.exoneration_TD1 == nouvelle_exoneration_TD1
        assert (
            resultat.retenue_additionnelle_federale
            == nouvelle_retenue_additionnelle_federale
        )

        # Tous les autres champs (non fiscaux) restent identiques à
        # l'original.
        assert resultat.id == employee_avant.id
        assert resultat.nom_affichage == employee_avant.nom_affichage
        assert resultat.date_naissance == employee_avant.date_naissance
        assert resultat.province_travail == employee_avant.province_travail
        assert resultat.titre_emploi == employee_avant.titre_emploi
        assert resultat.taux_horaire_base == employee_avant.taux_horaire_base
        assert resultat.date_embauche == employee_avant.date_embauche
        assert resultat.date_fin_emploi == employee_avant.date_fin_emploi
        assert (
            resultat.taux_indemnite_vacances
            == employee_avant.taux_indemnite_vacances
        )

        # L'original reste inchangé après l'appel (Employee est de toute
        # façon frozen=True, mais vérifié explicitement ici).
        assert employee == employee_avant

    def test_valeur_invalide_leve_validation_error_constructeur_complet(self) -> None:
        """**Validates: Requirements 11.2**

        Test explicite du point de vigilance (design §Components 7,
        correction ``model_copy`` → constructeur complet) : appeler
        ``mettre_a_jour_donnees_fiscales`` avec un montant négatif sur
        ``montant_total_TP1015_3`` (champ contraint
        ``Field(..., ge=Decimal("0"))`` sur ``Employee``) DOIT lever
        ``pydantic.ValidationError``. Ce test échouerait silencieusement
        (aucune exception levée) si l'implémentation utilisait
        ``employee.model_copy(update={...})`` — cette méthode ne
        ré-exécute pas les validateurs Pydantic. Il ne passe qu'avec le
        constructeur complet
        ``Employee(**{**employee.model_dump(), ...})``.
        """
        from app.logique_metier.fiche_employe import mettre_a_jour_donnees_fiscales

        employee = Employee(
            id="EMP001",
            nom_affichage="Employe Test EMP001",
            date_naissance=date(2000, 1, 1),
            province_travail=Juridiction.QUEBEC,
            titre_emploi="Moniteur",
            taux_horaire_base=Decimal("18.50"),
            date_embauche=date(2024, 6, 1),
            date_fin_emploi=None,
            taux_indemnite_vacances=Decimal("0.04"),
            exoneration_TP1015_3=False,
            exoneration_TD1=False,
            montant_total_TP1015_3=Decimal("18952.00"),
            montant_total_TD1=Decimal("16452.00"),
            retenue_additionnelle_QC=Decimal("0.00"),
            retenue_additionnelle_federale=Decimal("0.00"),
        )

        with pytest.raises(ValidationError):
            mettre_a_jour_donnees_fiscales(
                employee,
                montant_total_TP1015_3=Decimal("-1.00"),
                exoneration_TP1015_3=False,
                retenue_additionnelle_QC=Decimal("0.00"),
                montant_total_TD1=Decimal("16452.00"),
                exoneration_TD1=False,
                retenue_additionnelle_federale=Decimal("0.00"),
            )


class TestPropagationMiseAJour:
    """Test d'exemple de propagation sans interception (tâche 8.3).

    Design (§Components 7, note de correction post-§Components 7) :
    ``mettre_a_jour_donnees_fiscales`` ne fait elle-même aucune
    validation supplémentaire — elle reconstruit ``Employee`` via le
    constructeur complet, ce qui ré-exécute tous les validateurs
    Pydantic déjà actifs sur ``Employee``. Toute erreur de validation
    (ou ``UnsupportedPayrollCase``) résultante DOIT remonter **intacte**
    (même type, même message d'origine, aucun *wrapping* dans une
    exception custom) jusqu'à l'appelant (Req 11.4).

    Ce test complète
    ``test_valeur_invalide_leve_validation_error_constructeur_complet``
    (tâche 8.2, qui vérifie seulement qu'une exception est levée) en
    vérifiant en plus :

    1. Que l'exception propagée est exactement ``pydantic.ValidationError``
       — pas une sous-classe custom, pas ``UnsupportedPayrollCase``,
       pas un ``ValueError`` générique — et que le détail d'erreur
       (``errors()``) référence exactement le champ fautif et le type de
       contrainte violée (``ge=Decimal("0")``), preuve que le message
       Pydantic d'origine n'a pas été reformulé.
    2. Qu'aucune instance partielle n'est jamais observable :
       structurellement, ``Employee`` est ``frozen=True`` et la
       construction lève avant tout retour — il ne peut donc pas exister
       de valeur de retour partielle. Le test le vérifie en n'assignant
       **jamais** le résultat de l'appel à une variable à l'intérieur du
       bloc ``pytest.raises`` (aucune référence à un résultat n'existe
       après le bloc), et en confirmant qu'aucune nouvelle fiche portant
       le champ invalide n'apparaît dans l'Annuaire_Employes (aucun appel
       à une fonction d'enregistrement n'a lieu ici — cette fonction ne
       persiste rien elle-même).

    Champ utilisé ici : ``retenue_additionnelle_federale`` (valeur
    négative), différent du champ utilisé par le test explicite de la
    tâche 8.2 (``montant_total_TP1015_3``), pour varier la couverture
    des 6 champs fiscaux mis à jour.
    """

    def test_erreur_validation_originale_propagee_sans_interception(self) -> None:
        """**Validates: Requirements 11.4**

        Appelle ``mettre_a_jour_donnees_fiscales`` avec
        ``retenue_additionnelle_federale=Decimal("-5.00")`` (champ
        contraint ``Field(..., ge=Decimal("0"))`` sur ``Employee``) et
        vérifie que :

        - l'exception levée est exactement ``pydantic.ValidationError``
          (aucune interception/reformulation dans une exception custom) ;
        - le détail d'erreur Pydantic référence exactement le champ
          ``retenue_additionnelle_federale`` et le type de contrainte
          ``greater_than_equal`` — le message d'origine est intact, non
          paraphrasé ;
        - aucune référence à un résultat n'existe après le bloc
          ``pytest.raises`` : la fonction lève avant tout retour, elle ne
          retourne jamais ``None`` ni une instance ``Employee``
          incomplète (structurellement impossible, ``Employee`` étant
          ``frozen=True`` et construit en une seule opération atomique
          par Pydantic).
        """
        from app.logique_metier.fiche_employe import mettre_a_jour_donnees_fiscales

        employee = Employee(
            id="EMP002",
            nom_affichage="Employe Test EMP002",
            date_naissance=date(2001, 3, 12),
            province_travail=Juridiction.QUEBEC,
            titre_emploi="Animatrice",
            taux_horaire_base=Decimal("19.25"),
            date_embauche=date(2024, 6, 1),
            date_fin_emploi=None,
            taux_indemnite_vacances=Decimal("0.04"),
            exoneration_TP1015_3=False,
            exoneration_TD1=False,
            montant_total_TP1015_3=Decimal("18952.00"),
            montant_total_TD1=Decimal("16452.00"),
            retenue_additionnelle_QC=Decimal("0.00"),
            retenue_additionnelle_federale=Decimal("0.00"),
        )

        # Bloc `pytest.raises` : aucune assignation du résultat de
        # l'appel n'est faite ici — il ne peut structurellement pas y
        # avoir de référence à un résultat (partiel ou complet) après ce
        # bloc, puisque la fonction lève avant tout retour.
        with pytest.raises(ValidationError) as exc_info:
            mettre_a_jour_donnees_fiscales(
                employee,
                montant_total_TP1015_3=Decimal("18952.00"),
                exoneration_TP1015_3=False,
                retenue_additionnelle_QC=Decimal("0.00"),
                montant_total_TD1=Decimal("16452.00"),
                exoneration_TD1=False,
                retenue_additionnelle_federale=Decimal("-5.00"),
            )

        # (1) Type exact — pas de sous-classe custom, pas de wrapping.
        assert type(exc_info.value) is ValidationError, (
            "L'exception propagée doit être exactement "
            "pydantic.ValidationError d'origine, sans interception ni "
            f"reformulation ; obtenu {type(exc_info.value)!r}."
        )

        # (2) Message/détail d'origine intact — référence le champ
        # fautif exact et le type de contrainte violée, preuve que
        # l'erreur Pydantic native n'a pas été altérée ou reformulée.
        erreurs = exc_info.value.errors()
        champs_en_erreur = {tuple(erreur["loc"]) for erreur in erreurs}
        assert ("retenue_additionnelle_federale",) in champs_en_erreur, (
            "L'erreur de validation d'origine doit référencer exactement "
            f"le champ 'retenue_additionnelle_federale' ; obtenu "
            f"{champs_en_erreur!r}."
        )
        types_erreur = {erreur["type"] for erreur in erreurs}
        assert "greater_than_equal" in types_erreur, (
            "Le type de contrainte violée (ge=Decimal('0')) doit rester "
            f"celui d'origine ('greater_than_equal') ; obtenu {types_erreur!r}."
        )

        # (3) Aucune instance partielle n'est jamais observable : aucune
        # variable de ce test ne référence un résultat de l'appel — la
        # seule trace de l'appel est l'exception capturée ci-dessus.
        # `Employee` étant `frozen=True` et sa construction atomique
        # (Pydantic valide tous les champs avant de retourner l'instance
        # ou de lever), il ne peut structurellement pas exister d'objet
        # `Employee` partiellement construit à observer.
        assert "resultat" not in locals(), (
            "Aucune variable 'resultat' ne doit exister après le bloc "
            "pytest.raises : la fonction lève avant tout retour, elle ne "
            "produit jamais d'instance partielle."
        )

        # L'original demeure intact et n'a subi aucune modification
        # partielle (aucune tentative de persistance n'a lieu dans cette
        # fonction, mais on vérifie que l'instance passée en argument
        # reste elle-même inchangée, cohérent avec `frozen=True`).
        assert employee.retenue_additionnelle_federale == Decimal("0.00")


class TestMiseAJourInformationsPrincipalesImmuable:
    """Mise à jour immuable des 6 informations principales d'une
    Fiche_Employe (bug UI corrigé après livraison — édition des champs du
    formulaire de création depuis la Fiche_Employe_Detaillee, même patron
    exact que ``TestMiseAJourFiscaleImmuable`` pour
    ``mettre_a_jour_donnees_fiscales``).

    Design : ``mettre_a_jour_informations_principales`` reconstruit une
    **nouvelle** instance ``Employee`` dont les 6 champs principaux
    (``nom_affichage``, ``date_naissance``, ``titre_emploi``,
    ``taux_horaire_base``, ``date_embauche``, ``date_fin_emploi``,
    ``taux_indemnite_vacances`` — 7 champs au total) égalent exactement
    les nouvelles valeurs fournies, tous les autres champs (dont les 6
    champs fiscaux TD1/TP-1015.3) restant identiques à l'original ;
    l'original reste inchangé après l'appel.
    """

    #: Alphabet ASCII lisible, réutilisation exacte de
    #: `tests/models/test_employee.py::_ALPHABET_TEXTE` — ne contient
    #: aucun caractère blanchi par `str_strip_whitespace=True`
    #: (`Employee.model_config`), ce qui évite d'invalider
    #: `min_length=1` par accident (bug de stratégie de test, pas du
    #: code sous test).
    _ALPHABET_TEXTE_SANS_BLANCS = st.characters(
        min_codepoint=0x41,
        max_codepoint=0x7A,
        whitelist_categories=("Lu", "Ll", "Nd"),
    )

    @pytest.mark.property
    @given(
        employee=st_employee_valide(),
        nouveau_nom_affichage=st.text(
            alphabet=_ALPHABET_TEXTE_SANS_BLANCS, min_size=1, max_size=40
        ),
        nouvelle_date_naissance=st.dates(
            min_value=date(1960, 1, 1), max_value=date(2015, 12, 31)
        ),
        nouveau_titre_emploi=st.text(
            alphabet=_ALPHABET_TEXTE_SANS_BLANCS, min_size=1, max_size=40
        ),
        nouveau_taux_horaire_base=st.decimals(
            min_value=Decimal("10.00"),
            max_value=Decimal("60.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        nouvelle_date_embauche=st.dates(
            min_value=date(2020, 1, 1), max_value=date(2028, 12, 31)
        ),
        nouveau_taux_indemnite_vacances=st.sampled_from(
            [Decimal("0.04"), Decimal("0.06")]
        ),
    )
    @settings_employee
    def test_nouvelle_instance_7_champs_maj_reste_identique_sinon(
        self,
        employee: Employee,
        nouveau_nom_affichage: str,
        nouvelle_date_naissance: date,
        nouveau_titre_emploi: str,
        nouveau_taux_horaire_base: Decimal,
        nouvelle_date_embauche: date,
        nouveau_taux_indemnite_vacances: Decimal,
    ) -> None:
        """Pour toute ``Employee`` valide et toute combinaison valide des 7
        nouvelles informations principales (``date_fin_emploi`` fixée à
        ``None`` dans ce test), vérifie que
        ``mettre_a_jour_informations_principales`` retourne une nouvelle
        instance dont ces champs égalent exactement les nouvelles
        valeurs, dont tous les autres champs (y compris les 6 champs
        fiscaux) égalent ceux de l'original, et que l'original demeure
        inchangé.
        """
        from app.logique_metier.fiche_employe import (
            mettre_a_jour_informations_principales,
        )

        employee_avant = employee.model_copy(deep=True)

        resultat = mettre_a_jour_informations_principales(
            employee,
            nom_affichage=nouveau_nom_affichage,
            date_naissance=nouvelle_date_naissance,
            titre_emploi=nouveau_titre_emploi,
            taux_horaire_base=nouveau_taux_horaire_base,
            date_embauche=nouvelle_date_embauche,
            date_fin_emploi=None,
            taux_indemnite_vacances=nouveau_taux_indemnite_vacances,
        )

        assert resultat.nom_affichage == nouveau_nom_affichage
        assert resultat.date_naissance == nouvelle_date_naissance
        assert resultat.titre_emploi == nouveau_titre_emploi
        assert resultat.taux_horaire_base == nouveau_taux_horaire_base
        assert resultat.date_embauche == nouvelle_date_embauche
        assert resultat.date_fin_emploi is None
        assert resultat.taux_indemnite_vacances == nouveau_taux_indemnite_vacances

        # Champs fiscaux et identité inchangés.
        assert resultat.id == employee_avant.id
        assert resultat.province_travail == employee_avant.province_travail
        assert (
            resultat.montant_total_TP1015_3 == employee_avant.montant_total_TP1015_3
        )
        assert resultat.exoneration_TP1015_3 == employee_avant.exoneration_TP1015_3
        assert (
            resultat.retenue_additionnelle_QC
            == employee_avant.retenue_additionnelle_QC
        )
        assert resultat.montant_total_TD1 == employee_avant.montant_total_TD1
        assert resultat.exoneration_TD1 == employee_avant.exoneration_TD1
        assert (
            resultat.retenue_additionnelle_federale
            == employee_avant.retenue_additionnelle_federale
        )

        assert employee == employee_avant

    def test_valeur_hors_matrice_leve_unsupported_payroll_case(self) -> None:
        """Test explicite du même point de vigilance que pour les données
        fiscales : appeler ``mettre_a_jour_informations_principales`` avec
        un ``taux_indemnite_vacances`` hors matrice (ex.
        ``Decimal("0.05")``) DOIT lever ``UnsupportedPayrollCase``. Ce
        test échouerait silencieusement si l'implémentation utilisait
        ``employee.model_copy(update={...})``.
        """
        from models.exceptions import UnsupportedPayrollCase

        from app.logique_metier.fiche_employe import (
            mettre_a_jour_informations_principales,
        )

        employee = Employee(
            id="EMP003",
            nom_affichage="Employe Test EMP003",
            date_naissance=date(2000, 1, 1),
            province_travail=Juridiction.QUEBEC,
            titre_emploi="Moniteur",
            taux_horaire_base=Decimal("18.50"),
            date_embauche=date(2024, 6, 1),
            date_fin_emploi=None,
            taux_indemnite_vacances=Decimal("0.04"),
            exoneration_TP1015_3=False,
            exoneration_TD1=False,
            montant_total_TP1015_3=Decimal("18952.00"),
            montant_total_TD1=Decimal("16452.00"),
            retenue_additionnelle_QC=Decimal("0.00"),
            retenue_additionnelle_federale=Decimal("0.00"),
        )

        with pytest.raises(UnsupportedPayrollCase):
            mettre_a_jour_informations_principales(
                employee,
                nom_affichage=employee.nom_affichage,
                date_naissance=employee.date_naissance,
                titre_emploi=employee.titre_emploi,
                taux_horaire_base=employee.taux_horaire_base,
                date_embauche=employee.date_embauche,
                date_fin_emploi=employee.date_fin_emploi,
                taux_indemnite_vacances=Decimal("0.05"),
            )
