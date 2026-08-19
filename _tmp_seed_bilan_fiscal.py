"""Script temporaire (non versionné) — seed d'une base SQLite de TEST pour
la vérification manuelle de la tâche 11.2 de la spec bilan-fiscal-employeur.

RÈGLE 04 (données sensibles) — mécanisme de sécurité :
Ce script n'écrit JAMAIS dans la base de production. Il s'appuie sur le
même mécanisme d'isolation que `tests/payroll_engine/test_register.py`
(``monkeypatch.setenv("APPDATA", ...)``) : la variable d'environnement
``APPDATA`` DOIT être définie, avant le lancement de ce script, vers un
répertoire temporaire dédié — jamais le vrai ``%APPDATA%`` Windows de la
machine. `payroll_engine.register.chemin_bd_production()` (et les
fonctions dérivées, ex. `chemin_annuaire_employes_production()`) résolvent
alors leur chemin par défaut vers ce répertoire isolé, exactement comme le
ferait l'application Streamlit lancée avec la même variable d'environnement
surchargée.

Garde de sécurité : le script refuse de s'exécuter si ``APPDATA`` ne
contient pas le marqueur de répertoire temporaire attendu (voir
``_MARQUEUR_REPERTOIRE_TEST`` ci-dessous), pour empêcher toute exécution
accidentelle contre la vraie base de production.

Identifiants fictifs uniquement (EMP001..EMP003) — aucune donnée
personnelle réelle. Ce fichier sera supprimé après la vérification
manuelle (tâche 11.2).
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

_RACINE = str(Path(__file__).resolve().parent)
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

# ---------------------------------------------------------------------------
# Garde de sécurité (règle 04) — AVANT tout import de `payroll_engine.register`
# (dont les fonctions publiques évaluent `chemin_bd_production()` comme
# valeur par défaut de paramètre, donc AU MOMENT DE L'IMPORT).
# ---------------------------------------------------------------------------
_MARQUEUR_REPERTOIRE_TEST = "_tmp_test_appdata_bilan_fiscal"

_appdata = os.environ.get("APPDATA", "")
if _MARQUEUR_REPERTOIRE_TEST not in _appdata:
    raise SystemExit(
        "Garde de sécurité (règle 04) : la variable d'environnement "
        "APPDATA doit pointer vers un répertoire temporaire dont le nom "
        f"contient '{_MARQUEUR_REPERTOIRE_TEST}' avant de lancer ce "
        "script — jamais le vrai APPDATA de production. "
        f"Valeur actuelle : {_appdata!r}."
    )

from models.cumuls import CumulsYTD
from models.enums import FrequencePaie, Juridiction, ModeArrondissement, StatutDePaie
from models.pay_period import PayPeriod, WeekSegment
from models.payroll_result import (
    CotisationsEmployeur,
    GainsDecomposes,
    MontantAvecTrace,
    PayrollResult,
    RetenuesEmploye,
)
from models.trace import CalculationTrace
from payroll_engine.register import chemin_bd_production, inserer_paie


def _trace(montant: Decimal) -> CalculationTrace:
    return CalculationTrace(
        source="TP-1015.F 2026",
        annee=2026,
        juridiction=Juridiction.QUEBEC,
        section="seed manuel (test 11.2)",
        mode_arrondissement=ModeArrondissement.ROUND_HALF_UP,
        precision_arrondissement=2,
        resultat=montant,
    )


def _montant(montant: Decimal) -> MontantAvecTrace:
    return MontantAvecTrace(montant=montant, trace=_trace(montant))


def _week(date_debut: date) -> WeekSegment:
    return WeekSegment(
        date_debut=date_debut,
        date_fin=date_debut + timedelta(days=6),
        heures_normales=Decimal("40"),
        heures_supplementaires=Decimal("0"),
    )


def _pay_period(date_debut: date, annee_fiscale: int, numero_periode: int) -> PayPeriod:
    date_fin = date_debut + timedelta(days=13)
    return PayPeriod(
        numero_periode=numero_periode,
        date_debut=date_debut,
        date_fin=date_fin,
        date_paiement=date_fin + timedelta(days=5),
        frequence=FrequencePaie.AUX_DEUX_SEMAINES,
        nb_periodes_annuelles=26,
        annee_fiscale=annee_fiscale,
        semaines=(_week(date_debut), _week(date_debut + timedelta(days=7))),
    )


def _construire_paie(
    *,
    id_paie: str,
    employe_id: str,
    annee_fiscale: int,
    numero_periode: int,
    date_debut: date,
    cnesst_en_attente: bool,
) -> PayrollResult:
    rrq = Decimal("95.00")
    rqap = Decimal("12.00")
    ae = Decimal("20.00")
    impot_qc_retenu = Decimal("150.00")
    impot_federal_retenu = Decimal("130.00")
    impot_qc_formule = Decimal("150.00")
    impot_federal_formule = Decimal("130.00")
    total_retenues = rrq + rqap + ae + impot_qc_retenu + impot_federal_retenu

    retenues_employe = RetenuesEmploye(
        rrq=_montant(rrq),
        rqap=_montant(rqap),
        ae=_montant(ae),
        impot_qc_formule=_montant(impot_qc_formule),
        impot_qc_retenu=_montant(impot_qc_retenu),
        impot_federal_formule=_montant(impot_federal_formule),
        impot_federal_retenu=_montant(impot_federal_retenu),
        total_retenues_employe=total_retenues,
    )

    rrq_er = Decimal("95.00")
    rqap_er = Decimal("17.00")
    ae_er = Decimal("28.00")
    fss = Decimal("40.00")
    cnesst = Decimal("25.00")
    cnt = Decimal("2.00")
    total_cotisations = rrq_er + rqap_er + ae_er + fss + cnesst + cnt

    cotisations_employeur = CotisationsEmployeur(
        rrq_employeur=_montant(rrq_er),
        rqap_employeur=_montant(rqap_er),
        ae_employeur=_montant(ae_er),
        fss=_montant(fss),
        cnesst=_montant(cnesst),
        cnesst_en_attente_classification=cnesst_en_attente,
        cnt=_montant(cnt),
        total_cotisations_employeur=total_cotisations,
    )

    brut_total = total_retenues + Decimal("800.00")
    gains = GainsDecomposes(
        salaire_regulier=brut_total,
        heures_supplementaires_montant=Decimal("0.00"),
        vacances=Decimal("0.00"),
        jours_feries_manuels=Decimal("0.00"),
        brut_total=brut_total,
        multiplicateur_heures_supp=Decimal("1.5"),
        seuil_heures_supp_hebdo=Decimal("40"),
    )

    net = brut_total - total_retenues
    cout_employeur = brut_total + total_cotisations

    return PayrollResult(
        id_paie=id_paie,
        version=1,
        employe_id=employe_id,
        annee_fiscale=annee_fiscale,
        pay_period=_pay_period(date_debut, annee_fiscale, numero_periode),
        gains=gains,
        retenues_employe=retenues_employe,
        cotisations_employeur=cotisations_employeur,
        net=net,
        cout_employeur=cout_employeur,
        cumuls_fin=CumulsYTD.zero(employe_id=employe_id, annee_civile=annee_fiscale),
        statut=StatutDePaie.EMISE,
        remplace_par_id=None,
        date_creation=datetime(annee_fiscale, date_debut.month, date_debut.day, 12, 0, 0),
        date_emission=datetime(annee_fiscale, date_debut.month, date_debut.day, 12, 0, 0)
        + timedelta(days=6),
    )


def main() -> None:
    chemin_bd = chemin_bd_production()
    print(f"APPDATA (isolé) = {_appdata}")
    print(f"Chemin de base résolu (isolé, jamais production) = {chemin_bd}")
    if chemin_bd.exists():
        raise SystemExit(f"Le fichier {chemin_bd} existe déjà — abandon par prudence.")

    scenarios = [
        dict(
            id_paie="PAIE-EMP001-2026-001",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=1,
            date_debut=date(2026, 6, 1),
            cnesst_en_attente=True,
        ),
        dict(
            id_paie="PAIE-EMP002-2026-001",
            employe_id="EMP002",
            annee_fiscale=2026,
            numero_periode=1,
            date_debut=date(2026, 6, 1),
            cnesst_en_attente=False,
        ),
        dict(
            id_paie="PAIE-EMP001-2026-002",
            employe_id="EMP001",
            annee_fiscale=2026,
            numero_periode=2,
            date_debut=date(2026, 6, 15),
            cnesst_en_attente=False,
        ),
        dict(
            id_paie="PAIE-EMP003-2026-001",
            employe_id="EMP003",
            annee_fiscale=2026,
            numero_periode=1,
            date_debut=date(2026, 7, 1),
            cnesst_en_attente=True,
        ),
    ]

    for scenario in scenarios:
        resultat = _construire_paie(**scenario)
        inserer_paie(resultat, saison="Ete 2026 (test 11.2)")  # chemin_bd par défaut (isolé)
        print(f"Inséré : {resultat.id_paie} ({resultat.pay_period.date_paiement})")

    print(f"\nBase de test peuplée (isolée) : {chemin_bd}")


if __name__ == "__main__":
    main()
