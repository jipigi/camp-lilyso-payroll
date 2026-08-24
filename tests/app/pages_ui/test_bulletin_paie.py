"""Test de propriété — visibilité conditionnelle du bouton « Supprimer la
paie » (`app/pages_ui/bulletin_paie.py`).

Spec de référence : ``formulaire-paie-suppression-et-ux`` — tâche 8.3.
Design de référence : ``design.md`` §Correctness Properties, Property 6 :
« For all `PayrollResult` affichés dans le Bulletin_De_Paie, le bouton
« Supprimer la paie » est affiché si et seulement si le statut de la paie
affichée est `EMISE` — ce qui implique en particulier qu'après une
annulation réussie (statut devenu `ANNULEE`), ni ce bouton ni le bouton
« Corriger cette paie » ne sont affichés pour cette même paie. »

**Validates: Requirements 4.1, 4.2, 4.10**

``render()`` (le seul point d'entrée public de ce module) construit son
affichage à partir d'un grand nombre de lectures disque
(`lire_paie`/`lire_employe`/`lire_coordonnees`) et de widgets Streamlit
imbriqués (`st.columns`, `st.container`, `st.expander`) — le mocker
entièrement pour un test Hypothesis (des centaines d'exemples) serait
fragile et coûteux, et n'apporterait rien de plus que les deux lignes de
`render()` réellement responsables de la Property 6 :

```python
if paie.statut == StatutDePaie.EMISE:
    with st.popover("", icon=":material/more_vert:", ...):
        if st.button("Corriger", icon=":material/edit:", ...):
            ...
        if st.button("Supprimer", icon=":material/delete:", ...):
            ...
```

(les deux boutons sont désormais regroupés dans un menu à trois points
plutôt que deux boutons distincts de la barre d'actions — demande
explicite de l'utilisateur — mais partagent toujours la même condition
de visibilité `statut == EMISE`.)

Ce test property-based exerce donc directement cette condition — `paie.
statut == StatutDePaie.EMISE` — pour tout `PayrollResult` généré par
Hypothesis (les quatre statuts possibles), en invoquant `render()` avec
``streamlit`` intégralement mocké (même patron que
`tests/app/pages_ui/test_tableau_de_bord.py::TestIsolationErreurTableauBilanFiscal`
et `tests/app/pages_ui/test_formulaire_paie.py` — `unittest.mock.patch(
"app.pages_ui.bulletin_paie.st")`), et les trois lectures disque
(`lire_paie`, `lire_employe`, `lire_coordonnees`) mockées pour isoler le
test de toute base SQLite réelle. La visibilité du bouton est observée à
travers `st_mock.button.call_args_list` : le libellé exact « Supprimer la
paie » est-il présent parmi les appels à `st.button` ?

Règle 04 : l'employé construit ci-dessous (``EMP001``, « Employé Test
EMP001 ») est fictif, aucune donnée personnelle réelle.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.logique_metier.erreurs import ErreurDomaineAffichable
from app.pages_ui.bulletin_paie import (
    _dialogue_confirmation_suppression_paie,
    render,
)
from models.cumuls import CumulsYTD
from models.employee import Employee
from models.enums import Juridiction, ModeArrondissement, StatutDePaie
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
    PayrollResult,
    RetenuesEmploye,
)
from models.trace import CalculationTrace


def _make_trace(resultat: Decimal = Decimal("0.00")) -> CalculationTrace:
    """``CalculationTrace`` valide minimale (même patron que
    `tests/models/test_payroll_result.py::_make_trace`)."""
    return CalculationTrace(
        source="TP-1015.F 2026",
        annee=2026,
        juridiction=Juridiction.QUEBEC,
        section="Section fixture",
        parametres_utilises={},
        entrees={},
        sous_totaux={},
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=resultat,
    )


def _make_montant(montant: Decimal) -> MontantAvecTrace:
    return MontantAvecTrace(montant=montant, trace=_make_trace(montant))


def _make_pay_period() -> PayPeriod:
    """``PayPeriod`` valide aux deux semaines (même patron que
    `tests/models/test_payroll_result.py::_make_pay_period`)."""
    debut = date(2026, 6, 1)
    fin = debut + timedelta(days=13)
    semaine_1 = WeekSegment(
        date_debut=debut,
        date_fin=debut + timedelta(days=6),
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )
    semaine_2 = WeekSegment(
        date_debut=debut + timedelta(days=7),
        date_fin=fin,
        heures_normales=Decimal("0"),
        heures_supplementaires=Decimal("0"),
    )
    from models.enums import FrequencePaie

    return PayPeriod(
        numero_periode=12,
        date_debut=debut,
        date_fin=fin,
        date_paiement=fin + timedelta(days=5),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=27,
        annee_fiscale=2026,
        semaines=(semaine_1, semaine_2),
    )


def _make_payroll_result(statut: StatutDePaie) -> PayrollResult:
    """``PayrollResult`` valide pour ``EMP001``, de statut ``statut``.

    Respecte la biconditionnelle statut ⟺ remplace_par_id ⟺ date_emission
    (`models/payroll_result.py`, Req 6.3-6.5, 6.7) : ``date_emission`` est
    renseignée dès que ``statut != BROUILLON`` ; ``remplace_par_id`` n'est
    renseigné que pour ``REMPLACE_PAR``.
    """
    gains = GainsDecomposes(
        salaire_regulier=Decimal("1000.00"),
        heures_supplementaires_montant=Decimal("0.00"),
        vacances=Decimal("0.00"),
        jours_feries_manuels=Decimal("0.00"),
        brut_total=Decimal("1000.00"),
        multiplicateur_heures_supp=Decimal("1.5"),
        seuil_heures_supp_hebdo=Decimal("40"),
    )
    retenues = RetenuesEmploye(
        rrq=_make_montant(Decimal("0.00")),
        rqap=_make_montant(Decimal("0.00")),
        ae=_make_montant(Decimal("0.00")),
        impot_qc_formule=_make_montant(Decimal("0.00")),
        impot_qc_retenu=_make_montant(Decimal("0.00")),
        impot_federal_formule=_make_montant(Decimal("0.00")),
        impot_federal_retenu=_make_montant(Decimal("0.00")),
        total_retenues_employe=Decimal("0.00"),
    )
    cotisations = CotisationsEmployeur(
        rrq_employeur=_make_montant(Decimal("0.00")),
        rqap_employeur=_make_montant(Decimal("0.00")),
        ae_employeur=_make_montant(Decimal("0.00")),
        fss=_make_montant(Decimal("0.00")),
        cnesst=_make_montant(Decimal("0.00")),
        cnesst_en_attente_classification=False,
        cnt=_make_montant(Decimal("0.00")),
        total_cotisations_employeur=Decimal("0.00"),
    )
    date_emission = None if statut == StatutDePaie.BROUILLON else datetime(
        2026, 6, 20, 12, 0, 0
    )
    remplace_par_id = (
        "PAIE-EMP001-2026-013" if statut == StatutDePaie.REMPLACE_PAR else None
    )
    return PayrollResult(
        id_paie="PAIE-EMP001-2026-012",
        version=1,
        employe_id="EMP001",
        annee_fiscale=2026,
        pay_period=_make_pay_period(),
        gains=gains,
        retenues_employe=retenues,
        cotisations_employeur=cotisations,
        net=Decimal("1000.00"),
        cout_employeur=Decimal("1000.00"),
        cumuls_fin=CumulsYTD.zero(employe_id="EMP001", annee_civile=2026),
        statut=statut,
        remplace_par_id=remplace_par_id,
        date_creation=datetime(2026, 6, 19, 12, 0, 0),
        date_emission=date_emission,
    )


def _employe_test() -> Employee:
    """``Employee`` fictif minimal (règle 04)."""
    return Employee(
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


def _st_mock_avec_colonnes() -> MagicMock:
    """``MagicMock`` de ``streamlit`` dont ``st.columns(n)`` retourne un
    tuple de ``n`` gestionnaires de contexte factices — nécessaire pour
    que les affectations ``col_a, col_b, col_c = st.columns(3)`` de
    `render()` ne lèvent pas ``ValueError`` (un `MagicMock` seul n'est
    pas itérable en nombre fixe)."""
    st_mock = MagicMock()

    def _columns(spec, **_kwargs):
        # `render()` invoque `st.columns(3)` (nombre de colonnes) et
        # `st.columns([3, 2])` (largeurs relatives) — les deux formes
        # doivent produire le bon nombre de gestionnaires de contexte.
        nombre = spec if isinstance(spec, int) else len(spec)
        return tuple(MagicMock() for _ in range(nombre))

    st_mock.columns.side_effect = _columns
    st_mock.container.return_value = MagicMock()
    st_mock.expander.return_value = MagicMock()
    st_mock.session_state = {"bulletin_id_paie_cible": "PAIE-EMP001-2026-012"}
    st_mock.query_params = {}
    # Aucun bouton jamais cliqué par défaut — seule la *visibilité*
    # (l'appel à `st.button(...)`) est exercée par ce test, jamais le
    # câblage des dialogues (déjà couvert par les tâches 8.1/8.2).
    st_mock.button.return_value = False
    return st_mock


def _libelles_boutons_affiches(st_mock: MagicMock) -> list[str]:
    """Libellés (premier argument positionnel) de chaque appel à
    `st.button(...)` effectué pendant `render()`."""
    return [
        call.args[0]
        for call in st_mock.button.call_args_list
        if call.args
    ]


#: Les quatre statuts possibles d'un `PayrollResult` (`models/enums.py::
#: StatutDePaie`) — Property 6 porte sur l'ensemble du domaine, pas
#: seulement sur `EMISE`/`ANNULEE`.
_TOUS_LES_STATUTS = (
    StatutDePaie.BROUILLON,
    StatutDePaie.EMISE,
    StatutDePaie.ANNULEE,
    StatutDePaie.REMPLACE_PAR,
)


# Feature: formulaire-paie-suppression-et-ux, Property 6: Visibilité conditionnelle du bouton « Supprimer la paie »
@given(statut=st.sampled_from(_TOUS_LES_STATUTS))
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_property_6_bouton_supprimer_la_paie_affiche_ssi_statut_emise(
    statut: StatutDePaie,
) -> None:
    """**Validates: Requirements 4.1, 4.2, 4.10**

    Pour tout `PayrollResult` affiché dans le Bulletin_De_Paie (les
    quatre statuts possibles), le bouton « Supprimer la paie » est
    affiché si et seulement si `statut == StatutDePaie.EMISE`. Comme
    `ANNULEE` fait partie des statuts exercés, ce test couvre aussi le
    cas particulier du Req 4.10 (après une annulation réussie, ni ce
    bouton ni « Corriger cette paie » ne sont affichés pour cette même
    paie relue)."""
    paie = _make_payroll_result(statut)
    employe = _employe_test()

    with patch("app.pages_ui.bulletin_paie.st", new=_st_mock_avec_colonnes()) as st_mock, patch(
        "app.pages_ui.bulletin_paie.lire_paie",
        return_value=(paie, None),
    ), patch(
        "app.pages_ui.bulletin_paie.lire_employe", return_value=employe
    ), patch(
        "app.pages_ui.bulletin_paie.lire_coordonnees",
        side_effect=KeyError("aucune fiche de coordonnées pour ce test"),
    ), patch(
        "app.pages_ui.bulletin_paie.components.html"
    ):
        render()

    libelles = _libelles_boutons_affiches(st_mock)

    if statut == StatutDePaie.EMISE:
        assert "Supprimer" in libelles, (
            f"le bouton « Supprimer » (menu à trois points) doit être "
            f"affiché pour une paie de statut EMISE ; boutons affichés : "
            f"{libelles!r}."
        )
        assert "Corriger" in libelles, (
            "le bouton « Corriger » (menu à trois points) doit rester "
            f"affiché pour une paie EMISE ; boutons affichés : {libelles!r}."
        )
    else:
        assert "Supprimer" not in libelles, (
            f"le bouton « Supprimer » ne doit jamais être affiché pour "
            f"une paie de statut {statut.value!r} ; boutons affichés : "
            f"{libelles!r}."
        )
        assert "Corriger" not in libelles, (
            f"le bouton « Corriger » ne doit jamais être affiché pour une "
            f"paie de statut {statut.value!r} (en particulier ANNULEE, "
            f"Req 4.10) ; boutons affichés : {libelles!r}."
        )


# Feature: formulaire-paie-suppression-et-ux, Property 7: Construction dynamique du titre et du texte de la Popup_Confirmation_Paie_Emise
@given(
    prenom_affiche=st.text(min_size=1, max_size=50),
    nom_affiche=st.text(min_size=1, max_size=50),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_property_7_titre_et_texte_dynamiques_popup_confirmation_paie_emise(
    prenom_affiche: str,
    nom_affiche: str,
) -> None:
    """**Validates: Requirements 4.3**

    Pour tout `prenom_affiche`/`nom_affiche` arbitraires (y compris des
    chaînes contenant des caractères spéciaux HTML tels que `<`, `>`,
    `&`, `"`), le titre de la Popup_Confirmation_Paie_Emise (premier
    `st.write` du corps de la popup) contient exactement « Supprimer la
    paie de {prenom_affiche} {nom_affiche} ? » et le bouton de
    confirmation porte exactement le texte « Supprimer la paie de
    {prenom_affiche} {nom_affiche} ».

    `_dialogue_confirmation_suppression_paie` est décorée par
    `@st.dialog(...)` — invoquée directement, cette décoration
    déclenche l'ouverture réelle d'une popup Streamlit (nécessite un
    contexte de script en cours d'exécution, absent ici). Le test
    invoque donc `__wrapped__`, la fonction non décorée sous-jacente
    (attribut standard posé par `functools.wraps`, utilisé par
    `st.dialog` — voir la docstring de la fonction), avec ``streamlit``
    intégralement mocké (même patron que Property 6 ci-dessus,
    `unittest.mock.patch("app.pages_ui.bulletin_paie.st")`). Le bouton
    de confirmation n'est jamais cliqué (``st.button.return_value =
    False``) : seule la *construction* du titre/texte est exercée, pas
    l'invocation d'`annuler_paie` (déjà couverte par la tâche 8.2 et la
    Property 8/9/10 de `TestAnnulerPaie`).
    """
    nom_complet_attendu = f"{prenom_affiche} {nom_affiche}".strip()

    with patch(
        "app.pages_ui.bulletin_paie.st", new=_st_mock_avec_colonnes()
    ) as st_mock:
        _dialogue_confirmation_suppression_paie.__wrapped__(
            "PAIE-EMP001-2026-012", prenom_affiche, nom_affiche
        )

    textes_ecrits = [
        call.args[0] for call in st_mock.write.call_args_list if call.args
    ]
    libelles_boutons = _libelles_boutons_affiches(st_mock)

    titre_attendu = f"Supprimer la paie de {nom_complet_attendu} ?"
    bouton_attendu = f"Supprimer la paie de {nom_complet_attendu}"

    assert titre_attendu in textes_ecrits, (
        f"le titre exact {titre_attendu!r} doit être écrit via st.write ; "
        f"textes écrits : {textes_ecrits!r}."
    )
    assert bouton_attendu in libelles_boutons, (
        f"le bouton de confirmation doit porter exactement le texte "
        f"{bouton_attendu!r} ; boutons affichés : {libelles_boutons!r}."
    )


# ---------------------------------------------------------------------------
# Tâche 8.5 — tests unitaires de câblage de
# `_dialogue_confirmation_suppression_paie`.
#
# Design de référence : ``design.md`` §Components et Interfaces #6
# (``_dialogue_confirmation_suppression_paie``, `bulletin_paie.py`).
# Requirements de référence : 4.5 (le bouton « Annuler » ferme la popup
# sans invoquer `annuler_paie`), 4.8/4.9 (`annuler_paie` refuse une paie
# dont le statut n'est pas `EMISE`, ou un `id_paie` absent du Registre —
# capturé par `executer_avec_capture` et affiché via `st.error`, sans
# jamais appeler `st.rerun()`).
#
# Même patron que Property 7 ci-dessus (invocation directe de
# `_dialogue_confirmation_suppression_paie.__wrapped__`, contournant le
# décorateur `st.dialog` qui exige un contexte d'exécution Streamlit réel
# absent en test unitaire) et que
# `tests/app/pages_ui/test_absence_reference_residuelle_suppression_brouillon.py`
# (``st.button.side_effect`` ciblant explicitement une seule ``key`` à la
# fois, pour ne jamais déclencher les deux branches du dialogue avec un
# unique ``return_value=True``).
# ---------------------------------------------------------------------------


def _bouton_annuler_seulement(*_args: object, **kwargs: object) -> bool:
    """``st.button(...)`` retourne ``True`` uniquement pour le bouton
    « Annuler » (``key="bulletin_supprimer_annuler"``), ``False`` pour le
    bouton de confirmation — sans quoi un unique
    ``st_mock.button.return_value = True`` ferait retourner ``True`` pour
    les deux boutons du dialogue."""
    return kwargs.get("key") == "bulletin_supprimer_annuler"


def _bouton_confirmer_suppression_paie_seulement(
    *_args: object, **kwargs: object
) -> bool:
    """``st.button(...)`` retourne ``True`` uniquement pour le bouton de
    confirmation (``key="bulletin_supprimer_confirmer"``), ``False`` pour
    le bouton « Annuler »."""
    return kwargs.get("key") == "bulletin_supprimer_confirmer"


def test_bouton_annuler_ferme_la_popup_sans_appeler_annuler_paie() -> None:
    """**Validates: Requirements 4.5**

    Quand l'opérateur actionne le bouton « Annuler » de la Popup_
    Confirmation_Paie_Emise, la popup se ferme (`st.rerun()` invoqué)
    sans jamais invoquer `annuler_paie` — le bouton de confirmation
    n'est jamais cliqué (``st.button.side_effect`` ne retourne ``True``
    que pour la ``key`` « Annuler »)."""
    with patch(
        "app.pages_ui.bulletin_paie.st", new=_st_mock_avec_colonnes()
    ) as st_mock, patch(
        "app.pages_ui.bulletin_paie.annuler_paie"
    ) as annuler_paie_mock:
        st_mock.button.side_effect = _bouton_annuler_seulement

        _dialogue_confirmation_suppression_paie.__wrapped__(
            "PAIE-EMP001-2026-012", "Prénom", "Nom"
        )

    annuler_paie_mock.assert_not_called()
    st_mock.rerun.assert_called_once()
    st_mock.error.assert_not_called()


def test_erreur_du_registre_affichee_via_st_error_sans_rerun() -> None:
    """**Validates: Requirements 4.8, 4.9**

    Quand `annuler_paie` lève `ValueError` (statut courant ≠ `EMISE`,
    Req 4.8) ou `KeyError` (`id_paie` absent du Registre, Req 4.9),
    l'exception est capturée par `executer_avec_capture` et affichée via
    `st.error` — `st.rerun()` n'est jamais invoqué, la popup reste
    ouverte pour que l'opérateur en prenne connaissance."""
    for exception in (
        ValueError("statut actuel 'annulee' != EMISE"),
        KeyError("Aucune paie trouvée pour id_paie='PAIE-EMP001-2026-012'."),
    ):
        with patch(
            "app.pages_ui.bulletin_paie.st", new=_st_mock_avec_colonnes()
        ) as st_mock, patch(
            "app.pages_ui.bulletin_paie.annuler_paie",
            side_effect=exception,
        ) as annuler_paie_mock:
            st_mock.button.side_effect = (
                _bouton_confirmer_suppression_paie_seulement
            )

            _dialogue_confirmation_suppression_paie.__wrapped__(
                "PAIE-EMP001-2026-012", "Prénom", "Nom"
            )

        annuler_paie_mock.assert_called_once()
        st_mock.error.assert_called_once()
        st_mock.rerun.assert_not_called()
