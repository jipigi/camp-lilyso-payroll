"""Script d'entretien — corrige les paies BROUILLON en trop pour une
même Paie_Logique (employe_id, annee_fiscale, numero_periode),
accumulées par le bogue corrigé dans `payroll_engine/register.py`
(`inserer_paie` n'invalidait auparavant jamais les lignes BROUILLON
actives précédentes — voir la spec `unicite-paie-active-par-periode`).

Usage :

    python scripts/corriger_doublons_brouillon.py [--chemin-bd CHEMIN] [--appliquer]

Sans `--appliquer`, le script fonctionne en mode DRY-RUN (par défaut) :
il affiche les lignes détectées et l'action qui serait prise, sans
écrire quoi que ce soit. Ajouter `--appliquer` pour effectuer réellement
la correction.

Ce script applique rétroactivement l'invariant « au plus une ligne
active (BROUILLON ou EMISE) par Paie_Logique » désormais imposé par
`inserer_paie` (tâche 3 de la spec `unicite-paie-active-par-periode`) :

1. Identifie chaque Paie_Logique portant plus d'une ligne active
   (`statut ∈ {BROUILLON, EMISE}`).
2. Pour chaque Paie_Logique :
   - si une ligne `EMISE` est active, elle est conservée (une seule
     `EMISE` active peut exister, déjà garanti par le garde-fou
     existant et par `scripts/corriger_doublons_emise.py`) — TOUTES
     les lignes `BROUILLON` actives de la même période sont marquées
     `REMPLACE_PAR`, pointant vers cette `EMISE` ;
   - sinon (aucune `EMISE`, plusieurs `BROUILLON`), la ligne
     `BROUILLON` la plus récente (`version` la plus haute) est
     conservée — les AUTRES `BROUILLON` de la période sont marqués
     `REMPLACE_PAR`, pointant vers elle.
3. Chaque ligne corrigée ne subit que la mutation `statut` /
   `remplace_par_id` / `payload_json` (jamais `payload_input_json`),
   exactement le modèle déjà utilisé par `remplacer_paie` et par le
   fix runtime de `inserer_paie`. `date_emission` (requise par
   l'invariant `PayrollResult`, Req 6.7, dès que `statut ∈ {EMISE,
   ANNULEE, REMPLACE_PAR}`) est renseignée avec `date_creation` de la
   ligne conservée — jamais `datetime.now()`, pour rester pur et
   déterministe.

Un `BROUILLON` ne contribuant jamais à `cumuls_ytd` (Req 11.3/11.4),
cette correction ne nécessite AUCUN recalcul de `cumuls_ytd` — à la
différence de `corriger_doublons_emise.py`.

Toute la correction est effectuée dans UNE SEULE transaction SQLite —
pas de corruption partielle possible en cas d'interruption.

**Sauvegarde recommandée avant `--appliquer`** : copier le fichier
`payroll.db` cible avant exécution (`Copy-Item payroll.db
payroll.db.bak`), en particulier pour la base de production.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from models.enums import StatutDePaie
from models.payroll_result import PayrollResult
from payroll_engine.register import _creer_schema_si_absent, chemin_bd_production

_STATUTS_ACTIFS = (StatutDePaie.BROUILLON.value, StatutDePaie.EMISE.value)


def _identifier_paie_logiques_avec_lignes_actives_en_trop(
    connexion: sqlite3.Connection,
) -> list[tuple[str, int, int]]:
    """Retourne les triplets `(employe_id, annee_fiscale, numero_periode)`
    portant strictement plus d'une ligne active (`BROUILLON`/`EMISE`)."""
    lignes = connexion.execute(
        "SELECT employe_id, annee_fiscale, numero_periode, COUNT(*) AS nb "
        "FROM paies WHERE statut IN (?, ?) "
        "GROUP BY employe_id, annee_fiscale, numero_periode "
        "HAVING COUNT(*) > 1",
        _STATUTS_ACTIFS,
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in lignes]


def _lire_lignes_actives_du_groupe(
    connexion: sqlite3.Connection, employe_id: str, annee_fiscale: int, numero_periode: int
) -> list[tuple[str, str, str]]:
    """Retourne `(id_paie, payload_json, statut)` pour chaque ligne active
    du groupe, triées de sorte que la ligne à CONSERVER apparaisse en
    premier : `EMISE` avant `BROUILLON` (une seule `EMISE` active
    possible), puis `version` décroissante en cas de `BROUILLON`
    multiples."""
    lignes = connexion.execute(
        "SELECT id_paie, payload_json, statut FROM paies "
        "WHERE employe_id = ? AND annee_fiscale = ? AND numero_periode = ? "
        "AND statut IN (?, ?) "
        "ORDER BY (statut = ?) DESC, version DESC",
        (
            employe_id,
            annee_fiscale,
            numero_periode,
            *_STATUTS_ACTIFS,
            StatutDePaie.EMISE.value,
        ),
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in lignes]


def corriger(chemin_bd: Path, *, appliquer: bool) -> None:
    connexion = sqlite3.connect(str(chemin_bd))
    try:
        _creer_schema_si_absent(connexion)
        groupes = _identifier_paie_logiques_avec_lignes_actives_en_trop(connexion)

        if not groupes:
            print("Aucune ligne active en trop détectée — rien à corriger.")
            return

        print(f"{len(groupes)} période(s) avec plusieurs lignes actives :\n")

        for employe_id, annee_fiscale, numero_periode in groupes:
            lignes = _lire_lignes_actives_du_groupe(
                connexion, employe_id, annee_fiscale, numero_periode
            )
            id_paie_conserve, payload_conserve, statut_conserve = lignes[0]
            lignes_a_corriger = lignes[1:]

            print(
                f"  Employé={employe_id} Année={annee_fiscale} "
                f"Période={numero_periode} : "
                f"{len(lignes)} ligne(s) active(s) trouvée(s)."
            )
            print(
                f"    -> Conservée ({statut_conserve.upper()}) : "
                f"{id_paie_conserve}"
            )

            resultat_conserve = PayrollResult.model_validate_json(payload_conserve)

            for id_paie_a_corriger, payload_json, statut_a_corriger in lignes_a_corriger:
                print(
                    f"    -> Marquée REMPLACE_PAR : {id_paie_a_corriger} "
                    f"(était {statut_a_corriger.upper()}, "
                    f"remplace_par_id = {id_paie_conserve})"
                )
                if appliquer:
                    resultat = PayrollResult.model_validate_json(payload_json)
                    payload_maj = resultat.model_copy(
                        update={
                            "statut": StatutDePaie.REMPLACE_PAR,
                            "remplace_par_id": id_paie_conserve,
                            "date_emission": resultat_conserve.date_creation,
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

        if not appliquer:
            print(
                "\nMode DRY-RUN (aucune écriture effectuée). Relancer avec "
                "--appliquer pour effectuer la correction."
            )
            return

        # Un BROUILLON ne contribuant jamais à cumuls_ytd (Req 11.3/11.4),
        # aucun recalcul n'est nécessaire ici (à la différence de
        # corriger_doublons_emise.py).
        connexion.commit()
        print("\nCorrection appliquée avec succès.")
    finally:
        connexion.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Corrige les paies BROUILLON en trop pour une même période "
            "(bogue corrigé dans payroll_engine/register.py, spec "
            "unicite-paie-active-par-periode)."
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
