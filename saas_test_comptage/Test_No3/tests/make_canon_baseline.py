"""Fige la carte nom_brut -> classe canonique des noms de 4e_dataset.

A LANCER UNE FOIS, AVANT toute correction de canonical.py : la baseline sert de
temoin. Si une correction "pour la legende" deplace une instance du dataset, le
modele du run 4 et thresholds.json deviennent caducs -- test_canon_regression.py
le detecte en comparant a ce fichier.
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from canonical import canon  # noqa: E402

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
(HERE / "canon_baseline.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(counts)} noms bruts, {sum(counts.values())} instances -> canon_baseline.json")
