"""Genere le dataset de detection COCO `3e_dataset`, range PAR METIER.

Pour chaque paire DWG+PDF de PLANS_COMPLETS_NEW :
  - rend chaque etage depuis le DWG + xref (murs) -> image realiste ;
  - boites exactes autour de chaque symbole (classe = libelle de legende) ;
  - elements lineaires (goulottes/chemins de cable) exclus (1re passe).

Sortie : 3e_dataset/<METIER>/images/*.png + annotations.json (format COCO),
plus 3e_dataset/summary.json.
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

OUT = HERE / "3e_dataset"


def clean_name(s: str) -> str:
    """Nom de categorie sans mojibake (le U+FFFD des octets illisibles est retire)."""
    return (s.replace("�", "").replace("  ", " ").strip()) or "SYMBOLE"


def main():
    pairs = find_pairs()
    # etat COCO par metier
    coco = defaultdict(lambda: {"images": [], "annotations": [], "categories": []})
    cat_id = defaultdict(dict)   # metier -> {name: id}
    img_id = defaultdict(int)
    ann_id = defaultdict(int)
    summary = []

    for dwg, pdf in pairs:
        met = detect_metier(dwg)
        if met == "AUTRE":
            continue  # plan general de synthese, pas une feuille de comptage
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
        plan_boxes = 0
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
                })
                ann_id[met] += 1
                plan_boxes += 1
        summary.append({"metier": met, "plan": pdf.name,
                        "etages": len(floors), "boites": plan_boxes})
        print(f"[{met}] {pdf.name[:44]:44} {len(floors)} etage(s), {plan_boxes} boites", flush=True)

    # ecrit les annotations COCO par metier
    for met, data in coco.items():
        data["categories"] = [{"id": i, "name": n} for n, i in sorted(cat_id[met].items(), key=lambda kv: kv[1])]
        (OUT / met / "annotations.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    OUT.mkdir(exist_ok=True)
    tot = {met: {"images": len(d["images"]), "annotations": len(d["annotations"]),
                 "classes": len(cat_id[met])} for met, d in coco.items()}
    (OUT / "summary.json").write_text(
        json.dumps({"par_metier": tot, "detail": summary}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("\n===== 3e_dataset : RESUME =====")
    for met, t in sorted(tot.items()):
        print(f"  {met:12} {t['images']:>3} images  {t['annotations']:>5} boites  {t['classes']:>3} classes")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
