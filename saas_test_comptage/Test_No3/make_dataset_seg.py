"""Genere `4e_dataset` : SEGMENTATION D'INSTANCES (COCO), range par metier.

Identique a make_dataset mais chaque annotation porte un POLYGONE de masque
(contour reel du symbole = enveloppe convexe de la geometrie du bloc), en plus
de la boite. Format directement exploitable par Mask R-CNN / detectron2 / mmdet.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bench import find_pairs  # noqa: E402
from autolabel import detect_metier  # noqa: E402
from render_dwg import render_floors, svg_to_png  # noqa: E402
from make_dataset import clean_name  # noqa: E402

OUT = HERE / "4e_dataset"


def main():
    pairs = find_pairs()
    coco = defaultdict(lambda: {"images": [], "annotations": [], "categories": []})
    cat_id = defaultdict(dict)
    img_id = defaultdict(int)
    ann_id = defaultdict(int)
    summary = []

    for dwg, pdf in pairs:
        met = detect_metier(dwg)
        if met == "AUTRE":
            continue
        try:
            floors, info = render_floors(dwg, pdf)
        except Exception as e:
            summary.append({"metier": met, "plan": pdf.name, "erreur": str(e)[:80]})
            continue
        if not floors:
            summary.append({"metier": met, "plan": pdf.name, "erreur": info.get("error")})
            continue
        img_dir = OUT / met / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        n_inst = 0
        for svg, meta in floors:
            fname = f"{pdf.stem}_etage{meta['floor']}.png"
            (img_dir / fname).write_bytes(svg_to_png(svg))
            iid = img_id[met]
            img_id[met] += 1
            coco[met]["images"].append({
                "id": iid, "file_name": fname,
                "width": meta["width"], "height": meta["height"],
                "source_dwg": dwg.name, "source_pdf": pdf.name, "floor": meta["floor"],
            })
            for b in meta["boxes"]:
                name = clean_name(b["label"])
                cid = cat_id[met].get(name)
                if cid is None:
                    cid = len(cat_id[met])
                    cat_id[met][name] = cid
                coco[met]["annotations"].append({
                    "id": ann_id[met], "image_id": iid, "category_id": cid,
                    "bbox": [b["x"], b["y"], b["w"], b["h"]],
                    "area": round(b["w"] * b["h"], 1), "iscrowd": 0,
                    "segmentation": [b["seg"]],
                })
                ann_id[met] += 1
                n_inst += 1
        summary.append({"metier": met, "plan": pdf.name, "etages": len(floors), "instances": n_inst})
        print(f"[{met}] {pdf.name[:44]:44} {len(floors)} etage(s), {n_inst} instances", flush=True)

    for met, data in coco.items():
        data["categories"] = [{"id": i, "name": n, "supercategory": met}
                              for n, i in sorted(cat_id[met].items(), key=lambda kv: kv[1])]
        (OUT / met / "annotations.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    OUT.mkdir(exist_ok=True)
    tot = {met: {"images": len(d["images"]), "instances": len(d["annotations"]),
                 "classes": len(cat_id[met])} for met, d in coco.items()}
    (OUT / "summary.json").write_text(
        json.dumps({"par_metier": tot, "detail": summary}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("\n===== 4e_dataset (segmentation d'instances) =====")
    for met, t in sorted(tot.items()):
        print(f"  {met:12} {t['images']:>3} images  {t['instances']:>5} instances  {t['classes']:>3} classes")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
