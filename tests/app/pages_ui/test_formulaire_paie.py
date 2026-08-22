"""Tests unitaires du câblage de validation de `app/pages_ui/formulaire_paie.py`.

Spec de référence : ``tableau-de-bord-periode-globale`` — tâche 10.2.
Design de référence : ``design.md`` Décision 8 (validation de la date de
paiement lue depuis les widgets vifs, jamais depuis `paie_assemblee`) ;
§Components §6 (`_section_enregistrement`).

Ce module vérifie le **câblage** de `_section_enregistrement` (déjà
modifiée par la tâche 10.1, nouvelle signature avec les paramètres
mot-clé `date_fin`/`date_paiement`) plutôt que la logique pure déjà
couverte par les Properties 9 et 10 (`tests/app/logique_metier/
test_formulaire_paie.py`, fonctions `valider_date_paiement_pour_
emission`/`message_erreur_date_paiement`) :

1. La validation utilise bien les valeurs **vives** des widgets
   `date_fin`/`date_paiement` transmises en paramètre, jamais
   `paie_assemblee.pay_period.date_paiement` — devenue potentiellement
   obsolète si l'opérateur modifie les widgets sans ré-assembler
   (Req 6.1, design Décision 8).
2. Le blocage est effectif : si la date de paiement vive est absente ou
   invalide au moment de l'émission, `st.error(...)` est appelé et
   `inserer_paie` n'est **jamais** appelée (Req 6.1, 6.2).
3. La validation ne s'applique pas en BROUILLON : `inserer_paie` peut
   être appelée normalement même si la date de paiement vive est
   absente (Req 6.2, 6.4).

``streamlit`` (importé sous l'alias ``st`` dans `formulaire_paie.py`)
est mocké via `unittest.mock.patch("app.pages_ui.formulaire_paie.st")`
— même patron que
`tests/app/pages_ui/test_tableau_de_bord.py::TestIsolationErreurTableauBilanFiscal`.
``st.session_state`` est simulé par un vrai `dict` Python (assigné à
`st_mock.session_state`) pour un comportement réaliste de `.get`/
`__setitem__`. ``inserer_paie``/``lire_paie`` (importées directement
dans l'espace de noms de `formulaire_paie.py` depuis
`payroll_engine.register`) sont mockées pour isoler le câblage de
validation de toute écriture disque réelle.

Règle 04 : l'employé construit ci-dessous (`EMP001`, « Employé Test
EMP001 ») est fictif, aucune donnée personnelle réelle.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from app.logique_metier.formulaire_paie import construire_payroll_input, generer_id_paie
from app.pages_ui.formulaire_paie import _section_enregistrement
from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import Juridiction, StatutDePaie
from models.payroll_input import HeuresParSemaine
from payroll_engine.net_pay import assembler_paie
from tests.strategies import _charger_parametres_annee_2026_qc_ca


def _construire_paie_assemblee(date_paiement_assemblage: date):
    """`PayrollResult` (BROUILLON) réel, assemblé une seule fois, dont
    ``pay_period.date_paiement`` vaut ``date_paiement_assemblage`` —
    valeur destinée à devenir *obsolète* dans le test 1 (Req 6.1,
    design Décision 8). Même patron que
    `tests/app/logique_metier/test_formulaire_paie.py::
    _kwargs_valides_construction_payroll_input`/`test_round_trip_
    reconstruit_exactement_les_valeurs_dentree` (pipeline réel
    `construire_payroll_input` → `assembler_paie`, moteur non modifié).

    Retourne ``(paie_assemblee, date_fin)`` — ``date_fin`` est la borne
    utilisée pour construire la période, réutilisée par les tests comme
    valeur *vive* transmise à `_section_enregistrement`.
    """
    employee = Employee(
        id="EMP001",
        nom_affichage="Employé Test EMP001",
        date_naissance=date(2000, 1, 1),
        province_travail=Juridiction.QUEBEC,
        titre_emploi="Moniteur",
        taux_horaire_base=Decimal("20.00"),
        date_embauche=date(2024, 1, 1),
        date_fin_emploi=None,
        taux_indemnite_vacances=Decimal("0.04"),
        exoneration_TP1015_3=False,
        exoneration_TD1=False,
        montant_total_TP1015_3=Decimal("0.00"),
        montant_total_TD1=Decimal("0.00"),
        retenue_additionnelle_QC=Decimal("0.00"),
        retenue_additionnelle_federale=Decimal("0.00"),
    )

    date_debut = date(2026, 1, 5)
    date_fin = date_debut + timedelta(days=13)
    annee_fiscale = date_debut.year

    payroll_input = construire_payroll_input(
        employee=employee,
        numero_periode=1,
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_paiement_assemblage,
        annee_fiscale=annee_fiscale,
        nb_periodes_annuelles=26,
        heures_semaine_1=HeuresParSemaine(
            heures_normales=Decimal("40.00"), heures_supplementaires=Decimal("0.00")
        ),
        heures_semaine_2=HeuresParSemaine(
            heures_normales=Decimal("40.00"), heures_supplementaires=Decimal("0.00")
        ),
        taux_horaire_effectif=Decimal("20.00"),
        taux_vacances=Decimal("0.04"),
        jours_feries_manuels=Decimal("0.00"),
        montant_total_TP1015_3_effectif=Decimal("0.00"),
        exoneration_TP1015_3_effectif=False,
        retenue_additionnelle_QC_effective=Decimal("0.00"),
        montant_total_TD1_effectif=Decimal("0.00"),
        exoneration_TD1_effective=False,
        retenue_additionnelle_federale_effective=Decimal("0.00"),
        cumuls_debut=CumulsYTD.zero(employe_id=employee.id, annee_civile=annee_fiscale),
    )
    parametres_annee = _charger_parametres_annee_2026_qc_ca()
    id_paie = generer_id_paie(employee.id, annee_fiscale, 1, 1)
    paie_assemblee = assembler_paie(
        payroll_input,
        parametres_annee,
        id_paie,
        1,
        StatutDePaie.BROUILLON,
        datetime(2026, 1, 1, 12, 0),
    )
    return paie_assemblee, date_fin


class TestValidationUtiliseLesValeursViveDesWidgets:
    """La validation utilise `date_fin`/`date_paiement` vifs, jamais
    `paie_assemblee.pay_period.date_paiement` obsolète (Req 6.1)."""

    def test_insertion_tentee_malgre_date_paiement_assemblage_obsolete(self) -> None:
        """`paie_assemblee.pay_period.date_paiement` est délibérément
        différente de la `date_paiement` vive transmise à
        `_section_enregistrement` (simulant une modification du widget
        sans ré-assemblage). La `date_paiement` vive est valide
        (>= `date_fin`) : l'insertion doit être tentée — la validation ne
        doit jamais bloquer à tort à cause de l'ancienne valeur figée
        dans `paie_assemblee`."""
        date_paiement_assemblage = date(2026, 1, 23)  # devient obsolète
        paie_assemblee, date_fin = _construire_paie_assemblee(
            date_paiement_assemblage
        )
        # Valeur vive distincte de `date_paiement_assemblage`, mais
        # toujours valide (>= date_fin) — Req 6.1, 6.3.
        date_paiement_vive = date_fin + timedelta(days=20)
        assert date_paiement_vive != paie_assemblee.pay_period.date_paiement

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            side_effect=KeyError("paie introuvable"),
        ), patch("app.pages_ui.formulaire_paie.inserer_paie") as inserer_paie_mock:
            st_mock.session_state = {}
            st_mock.radio.return_value = "EMISE"
            st_mock.text_input.return_value = "Été 2026"
            st_mock.checkbox.return_value = True
            st_mock.button.return_value = True

            _section_enregistrement(
                paie_assemblee,
                paie_assemblee.annee_fiscale,
                date_fin=date_fin,
                date_paiement=date_paiement_vive,
                cle_prefixe="test_valeurs_vives",
            )

        st_mock.error.assert_not_called()
        inserer_paie_mock.assert_called_once()


class TestBlocageEffectifSiDateVivInvalide:
    """Blocage effectif de l'insertion si la date de paiement vive est
    absente ou invalide (Req 6.1, 6.2)."""

    def test_date_paiement_vive_absente_bloque_insertion(self) -> None:
        """`date_paiement` vive = `None` à l'émission : `st.error(...)`
        est appelé, et `inserer_paie` n'est jamais appelée."""
        paie_assemblee, date_fin = _construire_paie_assemblee(date(2026, 1, 23))

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            side_effect=KeyError("paie introuvable"),
        ), patch("app.pages_ui.formulaire_paie.inserer_paie") as inserer_paie_mock:
            st_mock.session_state = {}
            st_mock.radio.return_value = "EMISE"
            st_mock.text_input.return_value = "Été 2026"
            st_mock.checkbox.return_value = True
            st_mock.button.return_value = True

            _section_enregistrement(
                paie_assemblee,
                paie_assemblee.annee_fiscale,
                date_fin=date_fin,
                date_paiement=None,
                cle_prefixe="test_blocage_absente",
            )

        st_mock.error.assert_called_once()
        inserer_paie_mock.assert_not_called()

    def test_date_paiement_vive_antérieure_a_date_fin_bloque_insertion(self) -> None:
        """`date_paiement` vive strictement antérieure à `date_fin` à
        l'émission : `st.error(...)` est appelé avec un message
        pertinent, et `inserer_paie` n'est jamais appelée."""
        paie_assemblee, date_fin = _construire_paie_assemblee(date(2026, 1, 23))
        date_paiement_vive_invalide = date_fin - timedelta(days=1)

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            side_effect=KeyError("paie introuvable"),
        ), patch("app.pages_ui.formulaire_paie.inserer_paie") as inserer_paie_mock:
            st_mock.session_state = {}
            st_mock.radio.return_value = "EMISE"
            st_mock.text_input.return_value = "Été 2026"
            st_mock.checkbox.return_value = True
            st_mock.button.return_value = True

            _section_enregistrement(
                paie_assemblee,
                paie_assemblee.annee_fiscale,
                date_fin=date_fin,
                date_paiement=date_paiement_vive_invalide,
                cle_prefixe="test_blocage_anterieure",
            )

        st_mock.error.assert_called_once()
        message_affiche = st_mock.error.call_args[0][0]
        assert date_paiement_vive_invalide.isoformat() in message_affiche
        inserer_paie_mock.assert_not_called()


class TestNonApplicationEnBrouillon:
    """La validation de date de paiement ne s'applique pas en BROUILLON
    (Req 6.2, 6.4)."""

    def test_brouillon_avec_date_paiement_vive_absente_insere_normalement(
        self,
    ) -> None:
        """Statut choisi `BROUILLON`, `date_paiement` vive = `None`
        (qui bloquerait si le statut était `EMISE`) : l'insertion se
        produit normalement, `inserer_paie` est appelée sans blocage lié
        à la date de paiement."""
        paie_assemblee, date_fin = _construire_paie_assemblee(date(2026, 1, 23))

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            side_effect=KeyError("paie introuvable"),
        ), patch("app.pages_ui.formulaire_paie.inserer_paie") as inserer_paie_mock:
            st_mock.session_state = {}
            st_mock.radio.return_value = "BROUILLON"
            st_mock.text_input.return_value = "Été 2026"
            st_mock.checkbox.return_value = True
            st_mock.button.return_value = True

            _section_enregistrement(
                paie_assemblee,
                paie_assemblee.annee_fiscale,
                date_fin=date_fin,
                date_paiement=None,
                cle_prefixe="test_brouillon",
            )

        inserer_paie_mock.assert_called_once()
