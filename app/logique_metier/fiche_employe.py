"""Pré-remplissage des paramètres effectifs et mise à jour fiscale
immuable d'une Fiche_Employe.

Spec de référence : ``interface-streamlit`` — tâches 18.1
(`ParametresEffectifs` et `parametres_effectifs_par_defaut`) et 18.2
(`mettre_a_jour_donnees_fiscales`).
Design de référence : ``design.md`` §Components §7 (`fiche_employe.py` —
pré-remplissage et mise à jour fiscale immuable, Req 8.1, Req 11.2,
11.4) ; note de correction post-§Components 7.

Ce module porte :

- :class:`ParametresEffectifs` — le ``TypedDict`` des 7 paramètres
  effectifs pré-remplis dans le Formulaire_Paie ;
- :func:`parametres_effectifs_par_defaut` — la projection pure qui
  pré-remplit ces 7 clés depuis une Fiche_Employe (Req 8.1) ;
- :func:`mettre_a_jour_donnees_fiscales` — la reconstruction immuable
  des 6 champs fiscaux d'une Fiche_Employe (Req 11.2, 11.4).

**Point de vigilance corrigé (design §Components 7, note de correction
post-§Components 7)** : le pseudocode initial de
``mettre_a_jour_donnees_fiscales`` utilisait
``employee.model_copy(update={...})``. Cette méthode Pydantic v2
**ne ré-exécute pas** les validateurs (comportement documenté :
``model_copy`` est une copie superficielle sans revalidation). Une
valeur invalide (ex. un montant négatif sur un champ contraint
``Field(..., ge=Decimal("0"))``) passerait alors **silencieusement**,
contournant les gardes de validation d'``Employee``
(``_refuser_hors_matrice``, contraintes ``Field``, etc.).

La correction implémentée ici reconstruit l'instance via le
constructeur complet ``Employee(**{**employee.model_dump(), <6 champs
mis à jour>})``, qui ré-exécute **tous** les validateurs Pydantic
d'``Employee`` sur l'ensemble des champs (dont les 6 nouvelles valeurs
fiscales) — toute violation lève ``pydantic.ValidationError`` (ou
``UnsupportedPayrollCase`` selon le garde-fou concerné), propagée sans
interception (Req 11.4). ``employee.model_dump()`` est appelé en mode
Python par défaut (jamais ``mode="json"``) : il préserve les valeurs
``Decimal``/``date`` natives, directement réutilisables par le
constructeur ``Employee(...)`` sans reconversion depuis des chaînes.

``employee`` (l'original) reste inchangé — ``Employee`` est
``frozen=True`` et ``model_dump()`` ne mute jamais l'instance source ;
l'instance retournée par ``mettre_a_jour_donnees_fiscales`` est
toujours **nouvelle** et intégralement revalidée.

Règle 01 : tous les champs monétaires/taux manipulés ici restent des
``Decimal`` (jamais de conversion ``float``).
Règle 02 : aucune nouvelle ``CalculationTrace`` n'est produite ici — ce
module ne fait qu'assembler/projeter des champs déjà validés
d'``Employee``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from models.employee import Employee


class ParametresEffectifs(TypedDict):
    """Les 7 paramètres effectifs pré-remplis dans le Formulaire_Paie
    depuis une Fiche_Employe (Req 8.1, §Correctness Properties 12).

    Chaque clé correspond exactement à un champ source d'``Employee`` —
    voir :func:`parametres_effectifs_par_defaut`.
    """

    taux_horaire_effectif: Decimal
    taux_vacances: Decimal
    montant_total_TP1015_3_effectif: Decimal
    exoneration_TP1015_3_effectif: bool
    retenue_additionnelle_QC_effective: Decimal
    montant_total_TD1_effectif: Decimal
    exoneration_TD1_effective: bool
    retenue_additionnelle_federale_effective: Decimal


def parametres_effectifs_par_defaut(employee: Employee) -> ParametresEffectifs:
    """Pré-remplit les 7 paramètres effectifs depuis la Fiche_Employe (Req 8.1).

    Projection pure et directe — chacune des 7 clés retournées est
    strictement égale au champ source correspondant de ``employee``
    (``taux_horaire_base`` → ``taux_horaire_effectif``,
    ``taux_indemnite_vacances`` → ``taux_vacances``, etc.). Ne mute jamais
    ``employee`` ; le dict retourné est ensuite modifiable par l'opérateur
    dans la couche de rendu sans effet sur la Fiche_Employe elle-même
    (Req 8.2).
    """
    return ParametresEffectifs(
        taux_horaire_effectif=employee.taux_horaire_base,
        taux_vacances=employee.taux_indemnite_vacances,
        montant_total_TP1015_3_effectif=employee.montant_total_TP1015_3,
        exoneration_TP1015_3_effectif=employee.exoneration_TP1015_3,
        retenue_additionnelle_QC_effective=employee.retenue_additionnelle_QC,
        montant_total_TD1_effectif=employee.montant_total_TD1,
        exoneration_TD1_effective=employee.exoneration_TD1,
        retenue_additionnelle_federale_effective=employee.retenue_additionnelle_federale,
    )


def mettre_a_jour_donnees_fiscales(
    employee: Employee,
    *,
    montant_total_TP1015_3: Decimal,
    exoneration_TP1015_3: bool,
    retenue_additionnelle_QC: Decimal,
    montant_total_TD1: Decimal,
    exoneration_TD1: bool,
    retenue_additionnelle_federale: Decimal,
) -> Employee:
    """Reconstruit un `Employee` immuable avec les 6 champs fiscaux mis à
    jour, tous les autres champs inchangés (Req 11.2).

    **Constructeur complet, jamais `model_copy`** (correction explicite
    du point de vigilance du design §Components 7) : cette fonction
    utilise `Employee(**{**employee.model_dump(), <6 champs mis à
    jour>})` plutôt que `employee.model_copy(update={...})`. La raison
    est documentée dans le module docstring —
    `model_copy(update=...)` est une copie superficielle qui **ne
    ré-exécute pas** les validateurs Pydantic (comportement documenté
    de Pydantic v2). Avec `model_copy`, une valeur invalide (ex. un
    montant négatif sur `montant_total_TP1015_3`, contraint
    `Field(..., ge=Decimal("0"))`) passerait silencieusement, sans
    lever d'erreur, contournant les garde-fous de validation
    d'`Employee` (`_refuser_hors_matrice`, contraintes `Field`, etc.).

    Le constructeur complet `Employee(**{...})` ré-exécute **tous** les
    validateurs Pydantic sur l'ensemble des champs (dont les 6 nouvelles
    valeurs fiscales), garantissant que ces garde-fous restent
    pleinement actifs. Toute violation lève une erreur de validation
    d'origine (`pydantic.ValidationError` ou `UnsupportedPayrollCase`
    selon le garde concerné), propagée sans interception ni
    reformulation (Req 11.4) — cette fonction ne fait elle-même aucune
    validation supplémentaire.

    `employee.model_dump()` est appelé en **mode Python par défaut**
    (jamais `mode="json"`) : il préserve les valeurs `Decimal`/`date`
    natives de `employee`, directement réutilisables par le
    constructeur `Employee(...)` sans reconversion depuis des chaînes.

    `employee` (l'original) reste inchangé — `Employee` est
    `frozen=True` et `model_dump()` ne mute jamais l'instance source ;
    l'instance retournée est toujours **nouvelle** et intégralement
    revalidée.
    """
    return Employee(
        **{
            **employee.model_dump(),
            "montant_total_TP1015_3": montant_total_TP1015_3,
            "exoneration_TP1015_3": exoneration_TP1015_3,
            "retenue_additionnelle_QC": retenue_additionnelle_QC,
            "montant_total_TD1": montant_total_TD1,
            "exoneration_TD1": exoneration_TD1,
            "retenue_additionnelle_federale": retenue_additionnelle_federale,
        }
    )
