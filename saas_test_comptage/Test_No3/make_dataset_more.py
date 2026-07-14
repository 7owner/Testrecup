"""Ajoute au dataset (4e_dataset) TOUS les DWG SANS PDF apparie, de toutes les
affaires (CROIX ROUGE, VERDUN, BPCE, + DWG orphelins de ROI RENE).

Tri par metier via le CALQUE (pas de PDF). Ecrit dans des dossiers
`4e_dataset/<AFFAIRE>_<METIER>/` -> prepare_for_colab les fusionne automatiquement
(categories unifiees par nom). Segmentation d'instances (polygones).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

from render_dwg import render_floors_by_metier, svg_to_png  # noqa: E402
from make_dataset import clean_name  # noqa: E402

ROOT = HERE.parent / "PLANS_COMPLETS_NEW"
OUT = HERE / "4e_dataset"
SKIP = ("xref", "/old/", "\\old\\", "plotcfg", ".bak")


def affaire_slug(p: Path) -> str:
    parts = [x.upper() for x in p.parts]
    try:
        i = parts.index("PLANS")
        raw = p.parts[i + 1]
    except ValueError:
        raw = "AUTRE"
    return re.sub(r"[^A-Z0-9]+", "", raw.upper())[:12] or "AUTRE"


def unpaired_dwgs():
    out = []
    for dwg in ROOT.rglob("*.dwg"):
        low = str(dwg).lower()
        if any(t in low for t in SKIP):
            continue
        if dwg.with_suffix(".pdf").exists():
            continue  # deja traite par le pipeline apparie (make_dataset_seg)
        out.append(dwg)
    return sorted(out, key=lambda p: (affaire_slug(p), p.name))


def main():
    dwgs = unpaired_dwgs()
    print(f"{len(dwgs)} DWG sans PDF a traiter\n")
    summary = []
    for dwg in dwgs:
        aff = affaire_slug(dwg)
        try:
            by_met = render_floors_by_metier(dwg)
        except Exception as e:
            print(f"  [ERR] {dwg.name[:50]}: {str(e)[:60]}", flush=True)
            continue
        for met, floors in by_met.items():
            folder = f"{aff}_{met}"
            img_dir = OUT / folder / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            ann_path = OUT / folder / "annotations.json"
            if ann_path.exists():
                coco = json.loads(ann_path.read_text(encoding="utf-8"))
                cat_id = {c["name"]: c["id"] for c in coco["categories"]}
            else:
                coco = {"images": [], "annotations": [], "categories": []}
                cat_id = {}
            iid = len(coco["images"])
            aid = len(coco["annotations"])
            n = 0
            for svg, meta in floors:
                fname = f"{dwg.stem}_etage{meta['floor']}.png".replace(" ", "_")
                (img_dir / fname).write_bytes(svg_to_png(svg))
                coco["images"].append({"id": iid, "file_name": fname,
                                       "width": meta["width"], "height": meta["height"],
                                       "source_dwg": dwg.name, "floor": meta["floor"]})
                for b in meta["boxes"]:
                    name = clean_name(b["label"])
                    cid = cat_id.get(name)
                    if cid is None:
                        cid = len(cat_id); cat_id[name] = cid
                    coco["annotations"].append({
                        "id": aid, "image_id": iid, "category_id": cid,
                        "bbox": [b["x"], b["y"], b["w"], b["h"]],
                        "area": round(b["w"] * b["h"], 1), "iscrowd": 0,
                        "segmentation": [b["seg"]]})
                    aid += 1; n += 1
                iid += 1
            coco["categories"] = [{"id": i, "name": nm} for nm, i in sorted(cat_id.items(), key=lambda kv: kv[1])]
            ann_path.write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
            summary.append((folder, len(floors), n))
            print(f"  [{aff}] {dwg.stem[:36]:36} {met:4} {len(floors)} et. {n:>4} inst.", flush=True)

    print("\n===== AJOUTS =====")
    from collections import defaultdict
    tot = defaultdict(lambda: [0, 0])
    for folder, nf, n in summary:
        tot[folder][0] += nf; tot[folder][1] += n
    for folder in sorted(tot):
        print(f"  {folder:22} {tot[folder][0]:>3} images  {tot[folder][1]:>5} instances")


if __name__ == "__main__":
    main()
