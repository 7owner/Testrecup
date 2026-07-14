"""Fige la carte nom_brut -> classe canonique des noms de 4e_dataset.

A LANCER UNE FOIS, AVANT toute correction de canonical.py : la baseline sert de
temoin. Si une correction "pour la legende" deplace une instance du dataset, le
modele du run 4 et thresholds.json deviennent caducs -- test_canon_regression.py
le detecte en comparant a ce fichier.

GARDE-FOU : si canon_baseline.json existe deja, ce script REFUSE d'ecrire et sort
en erreur. Regenerer la baseline depuis canon() APRES avoir modifie canonical.py
efface le temoin : la comparaison test_canon_regression.py se ferait alors entre
la nouvelle sortie de canon() et... la nouvelle sortie de canon(), donc reussirait
toujours, meme si une regle a bouge une instance du dataset vers une autre classe.
Le signal "le modele entraine est peut-etre perime" disparaitrait silencieusement.

Si un deplacement de classe est reellement voulu (decision utilisateur, avec plan
de reentrainement), il se DECLARE dans EXCEPTIONS de test_canon_regression.py --
il ne s'efface pas en relancant ce script. Pour regenerer quand meme la baseline
(ex: premiere creation, ou changement de perimetre du dataset lui-meme), passer
--force explicitement.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from canonical import canon  # noqa: E402

BASELINE_PATH = HERE / "canon_baseline.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fige canon_baseline.json a partir de canon() sur 4e_dataset.")
    parser.add_argument(
        "--force", action="store_true",
        help="Ecrase canon_baseline.json meme s'il existe deja. A n'utiliser que "
             "pour une premiere creation ou un changement de perimetre du dataset "
             "-- PAS pour effacer un signal de regression apres avoir touche "
             "canonical.py (declare le deplacement dans EXCEPTIONS a la place).")
    args = parser.parse_args()

    if BASELINE_PATH.exists() and not args.force:
        print(
            f"REFUS : {BASELINE_PATH} existe deja.\n\n"
            "Ce fichier est le temoin qui prouve qu'aucune instance du dataset ne "
            "change de classe quand on modifie canonical.py. Le regenerer a partir "
            "de canon() APRES une correction rend le test de regression "
            "tautologique : il comparerait la nouvelle sortie de canon() a "
            "elle-meme, et repasserait au vert meme si une regle a deplace des "
            "instances vers une autre classe -- le signal \"le modele entraine "
            "(model_final.pth / thresholds.json) est peut-etre perime\" "
            "disparaitrait sans que rien ne le detecte.\n\n"
            "Si un deplacement de classe est voulu, il se declare dans "
            "EXCEPTIONS de test_canon_regression.py (avec sa justification), il "
            "ne s'efface pas en relancant ce script.\n\n"
            "Pour regenerer quand meme (premiere creation, changement de "
            "perimetre du dataset), relance avec --force.",
            file=sys.stderr)
        raise SystemExit(1)

    counts = Counter()
    for f in sorted((HERE.parent / "4e_dataset").glob("*/annotations.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in d["categories"]}
        for a in d["annotations"]:
            counts[cats[a["category_id"]]] += 1

    out = {
        "mapping": {nm: canon(nm) for nm in sorted(counts)},
        "counts": dict(counts),
    }
    BASELINE_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(counts)} noms bruts, {sum(counts.values())} instances -> canon_baseline.json")


if __name__ == "__main__":
    main()
