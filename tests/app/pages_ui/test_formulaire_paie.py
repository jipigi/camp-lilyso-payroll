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


class TestAnneeCouranteSansParametresFiscaux:
    """Bug UI corrigé après livraison (demande explicite de
    l'utilisateur) : l'année civile courante est toujours proposée dans
    le sélecteur d'année du formulaire de nouvelle paie, même sans
    `parameters/<annee_courante>/` sur disque — un message explicite
    bloque alors l'assemblage plutôt que de laisser
    `charger_parametres_fusionnes` lever `FileNotFoundError` (hors des
    4 types interceptés par `executer_avec_capture`)."""

    def test_annee_courante_ajoutee_au_selecteur_si_absente_de_lister_annees_disponibles(
        self,
    ) -> None:
        """Si `lister_annees_disponibles()` ne contient pas l'année
        courante (aucun `parameters/<annee_courante>/` sur disque),
        `render()` l'ajoute quand même aux options du `st.selectbox`."""
        annee_courante = date.today().year
        annees_avec_parametres = (annee_courante - 5,)  # jamais l'année courante
        assert annee_courante not in annees_avec_parametres

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lister_employes",
            return_value=(
                Employee(
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
                ),
            ),
        ), patch(
            "app.pages_ui.formulaire_paie.lister_annees_disponibles",
            return_value=annees_avec_parametres,
        ), patch(
            "app.pages_ui.formulaire_paie._section_nouvelle_paie"
        ) as section_nouvelle_paie_mock:
            st_mock.session_state = {}
            st_mock.query_params = {}
            st_mock.selectbox.return_value = annee_courante

            from app.pages_ui.formulaire_paie import render

            render()

        annees_transmises = section_nouvelle_paie_mock.call_args.args[1]
        assert annee_courante in annees_transmises, (
            "l'année civile courante doit toujours figurer dans les "
            f"années transmises à `_section_nouvelle_paie`, obtenu "
            f"{annees_transmises!r}."
        )

    def test_message_erreur_explicite_si_annee_selectionnee_sans_parametres(
        self,
    ) -> None:
        """Si l'année sélectionnée dans le `st.selectbox` n'a pas de
        `parameters/<annee>/` sur disque, `_section_nouvelle_paie`
        affiche le message d'erreur explicite et n'assemble aucune
        paie (aucun appel à `charger_parametres_fusionnes`)."""
        from app.pages_ui.formulaire_paie import _section_nouvelle_paie

        annee_sans_parametres = 2099

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lister_annees_disponibles",
            return_value=(),  # aucune année n'a de paramètres
        ), patch(
            "app.pages_ui.formulaire_paie.charger_parametres_fusionnes"
        ) as charger_parametres_mock:
            st_mock.session_state = {}
            st_mock.query_params = {}
            st_mock.selectbox.return_value = annee_sans_parametres

            _section_nouvelle_paie((), (annee_sans_parametres,))

        st_mock.error.assert_called_once()
        message_erreur = st_mock.error.call_args.args[0]
        assert str(annee_sans_parametres) in message_erreur
        assert "parameters/" in message_erreur
        charger_parametres_mock.assert_not_called()


class TestPreselectionRadioStatut:
    """Tâche 9.2 — présélection des Radio_Statut_Correction/Radio_Statut_
    Nouvelle_Paie (Req 6.1, 6.2).

    Vérifie le **câblage** des deux appels `st.radio` distincts du
    Formulaire_Paie : seul le `Radio_Statut_Correction` de
    `_section_corriger_paie` (flux « Corriger une paie émise ») doit
    recevoir `index=1` (présélection `EMISE`, tâche 9.1) ; le
    `Radio_Statut_Nouvelle_Paie` de `_section_enregistrement` (flux
    « Nouvelle paie », `cle_prefixe="fp_nouvelle"`) doit continuer à être
    invoqué sans argument `index` (présélection `BROUILLON` inchangée).

    Règle 04 : l'employé construit ci-dessous (`EMP001`, « Employé Test
    EMP001 ») est fictif, aucune donnée personnelle réelle.
    """

    def test_radio_statut_correction_preselectionne_sur_emise(self) -> None:
        """Le Radio_Statut_Correction du flux « Corriger une paie
        émise » (`_section_corriger_paie`) est invoqué avec `index=1`
        (Req 6.1)."""
        from app.pages_ui.formulaire_paie import _section_corriger_paie
        from models.payroll_result import PayrollResult

        paie_brouillon, _ = _construire_paie_assemblee(date(2026, 1, 23))
        # Réutilise le même patron que le code source
        # (`_section_corriger_paie`, construction de `nouveau_resultat`)
        # pour obtenir une variante EMISE valide de la paie ciblée.
        ancienne_paie_emise = PayrollResult(
            **{
                **paie_brouillon.model_dump(),
                "statut": StatutDePaie.EMISE,
                "date_emission": datetime(2026, 1, 1, 12, 0),
            }
        )
        employe = Employee(
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

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            return_value=(ancienne_paie_emise, None),
        ), patch(
            "app.pages_ui.formulaire_paie.lire_coordonnees",
            side_effect=KeyError("aucune fiche"),
        ), patch(
            "app.pages_ui.formulaire_paie.charger_parametres_fusionnes",
            return_value=_charger_parametres_annee_2026_qc_ca(),
        ), patch(
            "app.pages_ui.formulaire_paie.lire_cumuls_ytd",
            return_value=CumulsYTD.zero(
                employe_id="EMP001",
                annee_civile=ancienne_paie_emise.annee_fiscale,
            ),
        ):
            # `fp_corriger_paie_reassemblee` pré-rempli en session pour
            # atteindre directement le bloc d'affichage du
            # Radio_Statut_Correction sans dépendre du câblage du
            # bouton « Réassembler la paie » (`st.button` mocké à
            # `False`, hors périmètre de cette tâche).
            st_mock.session_state = {
                "fp_corriger_ancien_id_actif": ancienne_paie_emise.id_paie,
                "fp_corriger_paie_reassemblee": paie_brouillon,
            }
            st_mock.button.return_value = False
            st_mock.checkbox.return_value = True
            st_mock.date_input.return_value = date(2026, 1, 5)
            st_mock.text_input.return_value = "0.00"
            st_mock.selectbox.return_value = "0.04"

            _section_corriger_paie(
                (employe,), (ancienne_paie_emise.annee_fiscale,)
            )

        st_mock.radio.assert_called_once()
        radio_call = st_mock.radio.call_args
        assert radio_call.kwargs.get("index") == 1, (
            "le Radio_Statut_Correction doit être présélectionné sur "
            f"EMISE (index=1) ; obtenu {radio_call}"
        )
        assert radio_call.kwargs.get("key") == "fp_corriger_statut_choisi"

    def test_radio_statut_nouvelle_paie_reste_preselectionne_sur_brouillon(
        self,
    ) -> None:
        """Le Radio_Statut_Nouvelle_Paie du flux « Nouvelle paie »
        (`_section_enregistrement`, `cle_prefixe="fp_nouvelle"`) reste
        invoqué sans argument `index` — présélection `BROUILLON`
        inchangée (Req 6.2)."""
        paie_assemblee, date_fin = _construire_paie_assemblee(date(2026, 1, 23))

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            side_effect=KeyError("paie introuvable"),
        ), patch("app.pages_ui.formulaire_paie.inserer_paie"):
            st_mock.session_state = {}
            st_mock.radio.return_value = "BROUILLON"
            st_mock.text_input.return_value = "Été 2026"
            st_mock.checkbox.return_value = True
            st_mock.button.return_value = True

            _section_enregistrement(
                paie_assemblee,
                paie_assemblee.annee_fiscale,
                date_fin=date_fin,
                date_paiement=date_fin,
                cle_prefixe="fp_nouvelle",
            )

        st_mock.radio.assert_called_once()
        radio_call = st_mock.radio.call_args
        assert "index" not in radio_call.kwargs, (
            "le Radio_Statut_Nouvelle_Paie ne doit recevoir aucun "
            f"argument index (comportement existant inchangé) ; obtenu {radio_call}"
        )
        assert radio_call.kwargs.get("key") == "fp_nouvelle_statut_choisi"


class TestNumeroPeriodeSuggereReflectToujoursLetatCourantDuRegistre:
    """Bug signalé après démo (suite à la spec
    ``formulaire-paie-suppression-et-ux``) : après suppression d'un
    brouillon (ex. période 3), le formulaire de nouvelle paie
    continuait à suggérer la période 4 plutôt que de recalculer 3 —
    `st.number_input(..., value=X, key="K")` n'honore `value=X` qu'à la
    toute première création du widget de cette clé ; les rendus
    suivants gardaient l'ancienne valeur mémorisée dans
    `st.session_state["K"]`, quel que soit le nouveau `value=` transmis.

    Le correctif écrase explicitement `st.session_state[
    "fp_nouvelle_numero_periode"]` avec le numéro recalculé juste avant
    l'instanciation du widget, à chaque rendu — ce test vérifie que
    cette écriture reflète bien `max(numeros_deja_utilises) + 1` (ou `1`
    si aucune paie existante), à la fois quand `st.session_state`
    contenait déjà une valeur périmée (rendu précédent) et quand elle
    est absente (premier rendu).

    Règle 04 : l'employé/les résumés de paie construits ci-dessous
    (`EMP001`) sont fictifs, aucune donnée personnelle réelle.
    """

    def _executer_section_nouvelle_paie_et_capturer_numero_periode(
        self, numeros_deja_utilises: tuple[int, ...], valeur_perimee: int | None
    ) -> int:
        """Exécute `_section_nouvelle_paie` avec `lire_resumes_paies`
        mocké pour retourner des résumés portant les `numero_periode`
        de `numeros_deja_utilises`, et retourne la valeur finale écrite
        dans `st.session_state["fp_nouvelle_numero_periode"]` juste
        avant l'appel à `st.number_input` (capturée via
        `side_effect`)."""
        from app.logique_metier.dernieres_paies import LignePaieResume
        from app.pages_ui.formulaire_paie import _section_nouvelle_paie

        annee_fiscale = 2026
        employe = Employee(
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
        resumes = tuple(
            LignePaieResume(
                id_paie=f"PAIE-EMP001-{annee_fiscale}-{n:02d}-v1",
                numero_periode=n,
                version=1,
                # Valeur réelle de l'enum `StatutDePaie.EMISE.value`
                # ("emise", minuscule) — telle que persistée en base
                # (`payroll_engine.register`), jamais la valeur littérale
                # du membre Python (`StatutDePaie.EMISE.name` serait
                # "EMISE"). Une valeur incorrecte ici masquerait
                # silencieusement le filtre sur statuts actifs ajouté
                # par le correctif (bug signalé après démo).
                statut=StatutDePaie.EMISE.value,
                net="1000.00",
                saison="Été 2026",
                annee_fiscale=annee_fiscale,
                date_creation="2026-01-01T00:00:00",
            )
            for n in numeros_deja_utilises
        )

        session_state: dict[str, object] = {}
        if valeur_perimee is not None:
            session_state["fp_nouvelle_numero_periode"] = valeur_perimee

        numeros_periode_captures: list[int] = []

        def _capturer_numero_periode(*_args: object, **_kwargs: object) -> int:
            numeros_periode_captures.append(
                session_state["fp_nouvelle_numero_periode"]
            )
            return session_state["fp_nouvelle_numero_periode"]

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lister_annees_disponibles",
            return_value=(annee_fiscale,),
        ), patch(
            "app.pages_ui.formulaire_paie.charger_parametres_fusionnes",
            return_value=_charger_parametres_annee_2026_qc_ca(),
        ), patch(
            "app.pages_ui.formulaire_paie.lister_coordonnees",
            return_value=(),
        ), patch(
            "app.pages_ui.formulaire_paie.lire_resumes_paies",
            return_value=resumes,
        ), patch(
            "app.pages_ui.formulaire_paie.lire_cumuls_ytd"
        ):
            st_mock.session_state = session_state
            st_mock.query_params = {}

            def _selectbox_side_effect(
                libelle: str, options: object, *_args: object, **_kwargs: object
            ) -> object:
                # Distingue le sélecteur d'année (options = annees
                # disponibles, valeur = `annee_fiscale`) du sélecteur
                # d'employé (options = liste d'`employe_id`, valeur =
                # premier employé) — un unique `return_value` renverrait
                # à tort `annee_fiscale` pour les deux appels.
                if libelle.startswith("Année"):
                    return annee_fiscale
                return employe.id

            st_mock.selectbox.side_effect = _selectbox_side_effect
            st_mock.number_input.side_effect = _capturer_numero_periode
            st_mock.text_input.return_value = "0.00"
            st_mock.checkbox.return_value = False
            st_mock.date_input.return_value = None
            st_mock.button.return_value = False
            st_mock.columns.side_effect = lambda spec: tuple(
                st_mock.__class__() for _ in (spec if isinstance(spec, list) else range(spec))
            )

            _section_nouvelle_paie((employe,), (annee_fiscale,))

        assert numeros_periode_captures, (
            "`st.number_input` doit avoir été invoqué pour le champ "
            "« Numéro de période »."
        )
        return numeros_periode_captures[0]

    def test_recalcule_le_numero_suggere_meme_si_session_state_contient_une_valeur_perimee(
        self,
    ) -> None:
        """Périodes 1 et 2 déjà en BD (le brouillon de la période 3 a
        été supprimé) : le numéro suggéré doit être 3, même si
        `st.session_state["fp_nouvelle_numero_periode"]` contient
        encore la valeur périmée `4` d'un rendu précédent (avant
        suppression du brouillon 3)."""
        numero_suggere = self._executer_section_nouvelle_paie_et_capturer_numero_periode(
            numeros_deja_utilises=(1, 2), valeur_perimee=4
        )
        assert numero_suggere == 3, (
            "le numéro de période suggéré doit toujours refléter "
            "`max(numeros_deja_utilises) + 1` recalculé à partir de "
            f"l'état courant du Registre, obtenu {numero_suggere!r}, "
            "attendu 3 (périodes 1 et 2 existantes, brouillon 3 "
            "supprimé)."
        )

    def test_premier_rendu_sans_valeur_perimee_suggere_egalement_le_bon_numero(
        self,
    ) -> None:
        """Premier rendu (aucune valeur préexistante dans
        `st.session_state`) : le numéro suggéré est également
        `max(numeros_deja_utilises) + 1`."""
        numero_suggere = self._executer_section_nouvelle_paie_et_capturer_numero_periode(
            numeros_deja_utilises=(1, 2), valeur_perimee=None
        )
        assert numero_suggere == 3

    def test_aucune_paie_existante_suggere_la_periode_1(self) -> None:
        """Aucune paie existante pour cet employé/année : le numéro
        suggéré est `1`, même si `st.session_state` contient une valeur
        périmée d'un rendu précédent pour un autre employé."""
        numero_suggere = self._executer_section_nouvelle_paie_et_capturer_numero_periode(
            numeros_deja_utilises=(), valeur_perimee=5
        )
        assert numero_suggere == 1

    def _executer_avec_resumes_explicites(
        self, resumes: tuple, valeur_perimee: int | None
    ) -> int:
        """Variante de l'helper ci-dessus acceptant directement un tuple
        de `LignePaieResume` (plutôt qu'une liste de `numero_periode`
        tous `EMISE`) — nécessaire pour simuler des statuts mixtes
        (`REMPLACE_PAR`, `ANNULEE`) sur une même période."""
        from app.pages_ui.formulaire_paie import _section_nouvelle_paie

        annee_fiscale = 2026
        employe = Employee(
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

        session_state: dict[str, object] = {}
        if valeur_perimee is not None:
            session_state["fp_nouvelle_numero_periode"] = valeur_perimee

        numeros_periode_captures: list[int] = []

        def _capturer_numero_periode(*_args: object, **_kwargs: object) -> int:
            numeros_periode_captures.append(
                session_state["fp_nouvelle_numero_periode"]
            )
            return session_state["fp_nouvelle_numero_periode"]

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lister_annees_disponibles",
            return_value=(annee_fiscale,),
        ), patch(
            "app.pages_ui.formulaire_paie.charger_parametres_fusionnes",
            return_value=_charger_parametres_annee_2026_qc_ca(),
        ), patch(
            "app.pages_ui.formulaire_paie.lister_coordonnees",
            return_value=(),
        ), patch(
            "app.pages_ui.formulaire_paie.lire_resumes_paies",
            return_value=resumes,
        ), patch(
            "app.pages_ui.formulaire_paie.lire_cumuls_ytd"
        ):
            st_mock.session_state = session_state
            st_mock.query_params = {}

            def _selectbox_side_effect(
                libelle: str, options: object, *_args: object, **_kwargs: object
            ) -> object:
                if libelle.startswith("Année"):
                    return annee_fiscale
                return employe.id

            st_mock.selectbox.side_effect = _selectbox_side_effect
            st_mock.number_input.side_effect = _capturer_numero_periode
            st_mock.text_input.return_value = "0.00"
            st_mock.checkbox.return_value = False
            st_mock.date_input.return_value = None
            st_mock.button.return_value = False
            st_mock.columns.side_effect = lambda spec: tuple(
                st_mock.__class__() for _ in (spec if isinstance(spec, list) else range(spec))
            )

            _section_nouvelle_paie((employe,), (annee_fiscale,))

        assert numeros_periode_captures
        return numeros_periode_captures[0]

    def test_periode_dont_lunique_ligne_active_a_ete_supprimee_naffiche_plus_comme_utilisee(
        self,
    ) -> None:
        """Reproduction exacte du bug signalé après démo : la période 3
        n'a plus, en base, qu'une ligne `REMPLACE_PAR` orpheline (sa
        version successeure `BROUILLON` a été supprimée physiquement via
        « Supprimer le brouillon »). Les périodes 1 et 2 ont chacune une
        ligne `EMISE` active. Le numéro suggéré doit être `3` — la
        période 3 ne doit plus jamais compter comme « déjà utilisée »
        puisqu'aucune de ses lignes n'est dans un statut actif
        (`BROUILLON`/`EMISE`)."""
        from app.logique_metier.dernieres_paies import LignePaieResume

        annee_fiscale = 2026

        def _resume(numero_periode: int, statut: str, version: int) -> LignePaieResume:
            return LignePaieResume(
                id_paie=f"PAIE-EMP001-{annee_fiscale}-{numero_periode:02d}-v{version}",
                numero_periode=numero_periode,
                version=version,
                statut=statut,
                net="1000.00",
                saison="Été 2026",
                annee_fiscale=annee_fiscale,
                date_creation="2026-01-01T00:00:00",
            )

        resumes = (
            _resume(1, "emise", 1),
            _resume(2, "emise", 1),
            # Période 3 : seule ligne restante, `remplace_par` orpheline
            # (son successeur `v2` a été physiquement supprimé).
            _resume(3, "remplace_par", 1),
        )

        numero_suggere = self._executer_avec_resumes_explicites(
            resumes, valeur_perimee=4
        )
        assert numero_suggere == 3, (
            "une période dont l'unique ligne restante est `REMPLACE_PAR` "
            "(orpheline, successeur supprimé) ne doit plus être comptée "
            f"comme utilisée, obtenu {numero_suggere!r}, attendu 3."
        )


class TestNettoyageQueryParamsApresBrouillonSupprime:
    """Bug signalé après démo : le lien HTML « Modifier » du tableau des
    Paies transmet l'``id_paie`` du brouillon ciblé via
    ``st.query_params["id_paie"]`` (jamais retiré automatiquement par la
    navigation). Une fois ce brouillon supprimé physiquement (bouton
    « Supprimer le brouillon »), ``st.query_params["id_paie"]``
    continuait à référencer un ``id_paie`` désormais inexistant,
    provoquant une `KeyError` affichée en boucle à chaque rendu suivant
    du formulaire — jamais nettoyée puisque seule la clé de
    `st.session_state` était retirée. Ce test vérifie que
    `st.query_params.pop("id_paie", None)` est bien invoqué dès que la
    relecture du brouillon échoue avec `KeyError` (id_paie absent du
    Registre), afin que le prochain rendu ne re-tente plus cette
    lecture.

    Règle 04 : l'``id_paie`` utilisé ci-dessous (``PAIE-EMP001-2026-
    03-v1``) est fictif, aucune donnée personnelle réelle.
    """

    def test_key_error_sur_relecture_du_brouillon_retire_id_paie_des_query_params(
        self,
    ) -> None:
        from app.pages_ui.formulaire_paie import _section_nouvelle_paie

        id_paie_supprime = "PAIE-EMP001-2026-03-v1"
        annee_fiscale = 2026
        employe = Employee(
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
        query_params: dict[str, str] = {"id_paie": id_paie_supprime}

        with patch("app.pages_ui.formulaire_paie.st") as st_mock, patch(
            "app.pages_ui.formulaire_paie.lister_annees_disponibles",
            return_value=(annee_fiscale,),
        ), patch(
            "app.pages_ui.formulaire_paie.charger_parametres_fusionnes",
            return_value=_charger_parametres_annee_2026_qc_ca(),
        ), patch(
            "app.pages_ui.formulaire_paie.lister_coordonnees",
            return_value=(),
        ), patch(
            "app.pages_ui.formulaire_paie.lire_resumes_paies",
            return_value=(),
        ), patch(
            "app.pages_ui.formulaire_paie.lire_cumuls_ytd"
        ), patch(
            "app.pages_ui.formulaire_paie.lire_paie",
            side_effect=KeyError(f"Aucune paie trouvée pour id_paie={id_paie_supprime!r}."),
        ):
            st_mock.session_state = {}
            st_mock.query_params = query_params

            def _selectbox_side_effect(
                libelle: str, options: object, *_args: object, **_kwargs: object
            ) -> object:
                if libelle.startswith("Année"):
                    return annee_fiscale
                return employe.id

            st_mock.selectbox.side_effect = _selectbox_side_effect
            st_mock.number_input.return_value = 1
            st_mock.text_input.return_value = "0.00"
            st_mock.checkbox.return_value = False
            st_mock.date_input.return_value = None
            st_mock.button.return_value = False
            st_mock.columns.side_effect = lambda spec: tuple(
                st_mock.__class__() for _ in (spec if isinstance(spec, list) else range(spec))
            )

            _section_nouvelle_paie((employe,), (annee_fiscale,))

        st_mock.error.assert_called_once()
        assert "id_paie" not in query_params, (
            "après une `KeyError` sur la relecture du brouillon "
            "pré-chargé, `st.query_params[\"id_paie\"]` doit être "
            "retiré pour ne pas re-déclencher la même erreur au rendu "
            f"suivant, obtenu {query_params!r}."
        )
