"""Script d'entretien — corrige les doublons de paies EMISE simultanées
pour une même Paie_Logique (employe_id, annee_fiscale, numero_periode),
introduits par le bogue corrigé dans `payroll_engine/register.py`
(`inserer_paie` ne contrôlait auparavant que l'unicité de `id_paie`,
jamais l'unicité de la paie EMISE par période).

Usage :

    python scripts/corriger_doublons_emise.py [--chemin-bd CHEMIN] [--appliquer]

Sans `--appliquer`, le script fonctionne en mode DRY-RUN (par défaut) :
il affiche les doublons détectés et l'action qui serait prise, sans
écrire quoi que ce soit. Ajouter `--appliquer` pour effectuer réellement
la correction.

Ce script :

1. Identifie tous les groupes `(employe_id, annee_fiscale,
   numero_periode)` portant plus d'une ligne `statut = 'emise'`.
2. Pour chaque groupe, conserve la ligne EMISE la plus récente (par
   `date_emission`, puis `date_creation` en cas d'égalité) — c'est
   généralement la version issue de la correction la plus récente,
   donc la plus proche de la réalité.
3. Marque chacune des AUTRES lignes EMISE du groupe `REMPLACE_PAR` en
   pointant vers la ligne conservée (même mutation que
   `remplacer_paie` — étape 3a de `payroll_engine/register.py` —
   uniquement `statut`/`remplace_par_id`/`payload_json` sont modifiés,
   jamais `payload_input_json`, immutabilité respectée sur le reste).
4. Une fois toutes les corrections de statut appliquées, **recalcule
   entièrement `cumuls_ytd`** (à partir de zéro, pas d'ajustement
   incrémental) pour chaque `(employe_id, annee_fiscale)` affecté, en
   ne sommant que les lignes actuellement `EMISE` — approche robuste
   qui ne dépend d'aucune hypothèse sur l'état antérieur (possiblement
   déjà faussé par le bogue) de `cumuls_ytd`.

Toute la correction (mutations `paies` + recalcul `cumuls_ytd`) est
effectuée dans UNE SEULE transaction SQLite globale — pas de
corruption partielle possible en cas d'interruption.

**Sauvegarde recommandée avant `--appliquer`** : copier le fichier
`payroll.db` cible avant exécution (`Copy-Item payroll.db
payroll.db.bak`), en particulier pour la base de production.
"""

from __future__ import annotations

import argparse
import sqlite3
from decimal import Decimal
from pathlib import Path

from models.cumuls import CumulsYTD
from models.enums import StatutDePaie
from models.payroll_result import PayrollResult
from payroll_engine.register import (
    _ContributionResultat,
    _creer_schema_si_absent,
    _upsert_cumuls_ytd,
    chemin_bd_production,
)


def _identifier_groupes_doublons(
    connexion: sqlite3.Connection,
) -> list[tuple[str, int, int]]:
    """Retourne les triplets `(employe_id, annee_fiscale, numero_periode)`
    portant strictement plus d'une ligne `statut = 'emise'`."""
    lignes = connexion.execute(
        "SELECT employe_id, annee_fiscale, numero_periode, COUNT(*) AS nb "
        "FROM paies WHERE statut = ? "
        "GROUP BY employe_id, annee_fiscale, numero_periode "
        "HAVING COUNT(*) > 1",
        (StatutDePaie.EMISE.value,),
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in lignes]


def _lire_lignes_emises_du_groupe(
    connexion: sqlite3.Connection, employe_id: str, annee_fiscale: int, numero_periode: int
) -> list[tuple[str, str, str | None]]:
    """Retourne `(id_paie, payload_json, date_emission)` pour chaque ligne
    EMISE du groupe, triées par `date_emission` puis `date_creation`
    décroissants (la première ligne retournée est celle à conserver)."""
    lignes = connexion.execute(
        "SELECT id_paie, payload_json, date_emission FROM paies "
        "WHERE employe_id = ? AND annee_fiscale = ? AND numero_periode = ? "
        "AND statut = ? "
        "ORDER BY date_emission DESC, date_creation DESC",
        (employe_id, annee_fiscale, numero_periode, StatutDePaie.EMISE.value),
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in lignes]


def _recalculer_cumuls_depuis_zero(
    connexion: sqlite3.Connection, employe_id: str, annee_fiscale: int
) -> CumulsYTD:
    """Recalcule `cumuls_ytd` à partir de zéro pour `(employe_id,
    annee_fiscale)`, en sommant exclusivement les lignes actuellement
    `EMISE` (donc post-correction) — jamais un ajustement incrémental
    sur un cumul potentiellement déjà faussé par le bogue."""
    lignes_emises = connexion.execute(
        "SELECT payload_json FROM paies WHERE employe_id = ? AND "
        "annee_fiscale = ? AND statut = ?",
        (employe_id, annee_fiscale, StatutDePaie.EMISE.value),
    ).fetchall()

    cumul = CumulsYTD.zero(employe_id=employe_id, annee_civile=annee_fiscale)
    for (payload_json,) in lignes_emises:
        resultat = PayrollResult.model_validate_json(payload_json)
        contribution = _ContributionResultat.depuis(resultat)
        cumul = cumul.avec_paie(contribution)
    return cumul


def corriger(chemin_bd: Path, *, appliquer: bool) -> None:
    connexion = sqlite3.connect(str(chemin_bd))
    try:
        _creer_schema_si_absent(connexion)
        groupes = _identifier_groupes_doublons(connexion)

        if not groupes:
            print("Aucun doublon de paie EMISE détecté — rien à corriger.")
            return

        print(f"{len(groupes)} période(s) avec des paies EMISE en double :\n")

        employes_annees_a_recalculer: set[tuple[str, int]] = set()

        for employe_id, annee_fiscale, numero_periode in groupes:
            lignes = _lire_lignes_emises_du_groupe(
                connexion, employe_id, annee_fiscale, numero_periode
            )
            id_paie_conserve, _payload_conserve, _date_conserve = lignes[0]
            lignes_a_corriger = lignes[1:]

            print(
                f"  Employé={employe_id} Année={annee_fiscale} "
                f"Période={numero_periode} : "
                f"{len(lignes)} paies EMISE trouvées."
            )
            print(f"    -> Conservée (EMISE) : {id_paie_conserve}")

            for id_paie_a_corriger, payload_json, _date in lignes_a_corriger:
                print(
                    f"    -> Marquée REMPLACE_PAR : {id_paie_a_corriger} "
                    f"(remplace_par_id = {id_paie_conserve})"
                )
                if appliquer:
                    resultat = PayrollResult.model_validate_json(payload_json)
                    payload_maj = resultat.model_copy(
                        update={
                            "statut": StatutDePaie.REMPLACE_PAR,
                            "remplace_par_id": id_paie_conserve,
                        }
                    ).model_dump_json()
                    connexion.execute(
                        "UPDATE paies SET statut = ?, remplace_par_id = ?, "
                        "payload_json = ? WHERE id_paie = ?",
                        (
                            StatutDePaie.REMPLACE_PAR.value,
                            id_paie_conserve,
                            payload_maj,
                            id_paie_a_corriger,
                        ),
                    )

            employes_annees_a_recalculer.add((employe_id, annee_fiscale))

        if not appliquer:
            print(
                "\nMode DRY-RUN (aucune écriture effectuée). Relancer avec "
                "--appliquer pour effectuer la correction."
            )
            return

        print("\nRecalcul complet de cumuls_ytd (depuis zéro, lignes EMISE actuelles)...")
        for employe_id, annee_fiscale in employes_annees_a_recalculer:
            nouveau_cumul = _recalculer_cumuls_depuis_zero(
                connexion, employe_id, annee_fiscale
            )
            _upsert_cumuls_ytd(connexion, nouveau_cumul)
            print(f"    -> cumuls_ytd recalculé pour {employe_id}/{annee_fiscale}.")

        connexion.commit()
        print("\nCorrection appliquée avec succès.")
    finally:
        connexion.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Corrige les doublons de paies EMISE simultanées pour une "
            "même période (bogue corrigé dans payroll_engine/register.py)."
        )
    )
    parser.add_argument(
        "--chemin-bd",
        type=Path,
        default=chemin_bd_production(),
        help="Chemin du fichier payroll.db à corriger (défaut : base de production).",
    )
    parser.add_argument(
        "--appliquer",
        action="store_true",
        help="Applique réellement la correction (sans cet indicateur : DRY-RUN).",
    )
    args = parser.parse_args()

    print(f"Base de données ciblée : {args.chemin_bd}")
    if not args.appliquer:
        print("Mode DRY-RUN — aucune écriture ne sera effectuée.\n")
    else:
        print(
            "Mode APPLICATION — des écritures seront effectuées. "
            "Assurez-vous d'avoir une copie de sauvegarde du fichier.\n"
        )

    corriger(args.chemin_bd, appliquer=args.appliquer)


if __name__ == "__main__":
    main()
