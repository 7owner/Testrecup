"""Controle qualite d'un dataset COCO (boites + masques). Donne des chiffres reels :
validite du format, distribution des tailles, taux de degenerescence, par classe.
Ce sont des tests de QUALITE DE DONNEES, pas de performance de modele (-> Colab).
"""
import json
import sys
import statistics as st
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "4e_dataset"
print(f"=== QC {root.name} ===\n")
grand = Counter()
for ann_file in sorted(root.glob("*/annotations.json")):
    met = ann_file.parent.name
    d = json.load(open(ann_file, encoding="utf-8"))
    anns = d["annotations"]
    ws = [a["bbox"][2] for a in anns]
    hs = [a["bbox"][3] for a in anns]
    areas = [a["area"] for a in anns]
    tiny = sum(1 for a in anns if a["bbox"][2] < 3 or a["bbox"][3] < 3)
    huge = sum(1 for a in anns if a["bbox"][2] > 200 or a["bbox"][3] > 200)
    has_seg = sum(1 for a in anns if a.get("segmentation") and len(a["segmentation"][0]) >= 6)
    valid_img = all("width" in im and "height" in im for im in d["images"])
    per_class = Counter()
    for a in anns:
        per_class[a["category_id"]] += 1
    cats = {c["id"]: c["name"] for c in d["categories"]}
    print(f"[{met}]  {len(d['images'])} images · {len(anns)} instances · {len(cats)} classes")
    if ws:
        print(f"   boite  w med={st.median(ws):.1f} (min {min(ws):.1f} / max {max(ws):.1f})"
              f"   <3px:{tiny}  >200px:{huge}")
        print(f"   masque polygone valide: {has_seg}/{len(anns)}   images valides: {valid_img}")
    print("   par classe:")
    for cid, n in per_class.most_common():
        print(f"      {n:>4}  {cats.get(cid, cid)}")
    print()
    grand["images"] += len(d["images"])
    grand["instances"] += len(anns)
    grand["tiny"] += tiny
    grand["huge"] += huge

print("=== TOTAL ===")
print(f"  {grand['images']} images · {grand['instances']} instances · "
      f"{grand['tiny']} degenerees (<3px) · {grand['huge']} surdimensionnees (>200px)")
