"""Rend une galerie de revue pour reconstruire les classes par FORME de symbole.

Objectif avant run 6 :
  - ne pas deviner depuis les noms ;
  - voir le dessin DWG reel de chaque nom brut ;
  - separer la classe detectee (forme) du metier d'affichage (CFO/CFA/SSI/CVC...).

Sorties :
  out/symbol_taxonomy.html  : galerie visuelle a valider
  out/symbol_taxonomy.csv   : table brute exploitable
  out/symbol_taxonomy.json  : memes donnees structurees
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from autolabel import detect_metier  # noqa: E402
from bench import find_pairs  # noqa: E402
from canonical import canon  # noqa: E402
from render_dwg import (  # noqa: E402
    _prims_bbox,
    _prims_to_svg_elems,
    build_sheet,
    metier_of_layer,
    render_floors_by_metier,
)

ROOT = HERE.parent / "PLANS_COMPLETS_NEW"
OUT = HERE / "out"
SKIP = ("xref", "/old/", "\\old\\", "plotcfg", ".bak")


def clean(s: str) -> str:
    return (s or "").replace("\ufffd", "").strip()


def primitive_points(prims):
    pts = []
    for p in prims:
        if p[0] == "l":
            pts.extend([p[1], p[2]])
        elif p[0] == "c":
            cx, cy = p[1]
            r = p[2]
            pts.extend((cx + r * math.cos(i * math.pi / 8),
                        cy + r * math.sin(i * math.pi / 8)) for i in range(16))
        elif p[0] == "a":
            cx, cy = p[1]
            r, a0, a1 = p[2], p[3], p[4]
            if a1 < a0:
                a1 += 2 * math.pi
            pts.extend((cx + r * math.cos(a0 + (a1 - a0) * i / 8),
                        cy + r * math.sin(a0 + (a1 - a0) * i / 8)) for i in range(9))
    return pts


def shape_signature(prims) -> str:
    """Signature grossiere et stable pour rapprocher les dessins identiques.

    Ce n'est pas un classifieur automatique : la validation reste visuelle. La signature
    sert seulement a mettre cote a cote les formes objectivement proches.
    """
    bb = _prims_bbox(prims)
    if not bb:
        return "empty"
    x0, y0, x1, y1 = bb
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    qpts = []
    for x, y in primitive_points(prims):
        qpts.append((round((x - x0) / w * 31), round((y - y0) / h * 31)))
    qpts = sorted(set(qpts))
    ops = Counter(p[0] for p in prims)
    ratio = round(w / h, 2) if h else 0
    return f"ops={dict(sorted(ops.items()))}|ratio={ratio}|pts={qpts[:80]}"


def thumb_svg(prims, size=96) -> str:
    bb = _prims_bbox(prims)
    if not bb:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"></svg>'
    x0, y0, x1, y1 = bb
    spanx, spany = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    pad = size * 0.12
    scale = min((size - 2 * pad) / spanx, (size - 2 * pad) / spany)

    def fx(x):
        return pad + (x - x0) * scale

    def fy(y):
        return size - pad - (y - y0) * scale

    elems = _prims_to_svg_elems(prims, fx, fy, "#111", 1.6)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        + "".join(elems) +
        "</svg>"
    )


def unpaired_dwgs():
    out = []
    for dwg in ROOT.rglob("*.dwg"):
        low = str(dwg).lower()
        if any(t in low for t in SKIP):
            continue
        if dwg.with_suffix(".pdf").exists():
            continue
        out.append(dwg)
    return sorted(out)


def add_symbol(rows, reps, *, label, display, layer, source, metier, prims):
    raw = clean(label)
    if not raw:
        return
    current = canon(raw)
    layer_metier = metier_of_layer(layer)
    display_metier = layer_metier or metier
    sig = shape_signature(prims)
    key = (raw, sig)
    reps.setdefault(key, {
        "raw": raw,
        "display": clean(display),
        "current_class": current,
        "display_metier": display_metier,
        "layer": clean(layer),
        "shape_signature": sig,
        "sources": Counter(),
        "count": 0,
        "prims": prims,
    })
    reps[key]["count"] += 1
    reps[key]["sources"][source] += 1
    rows.append({
        "raw": raw,
        "display": clean(display),
        "current_class": current,
        "display_metier": display_metier,
        "layer": clean(layer),
        "source": source,
        "shape_signature": sig,
    })


def collect_from_paired(limit: int | None = None):
    rows = []
    reps = {}
    pairs = find_pairs()
    if limit:
        pairs = pairs[:limit]
    for dwg, pdf in pairs:
        metier = detect_metier(dwg)
        try:
            sheet = build_sheet(dwg, pdf)
        except Exception as e:
            print(f"[WARN] {pdf.name}: {str(e)[:100]}", flush=True)
            continue
        source = f"{dwg.name} | {pdf.name}"
        for s in sheet["symbols"]:
            add_symbol(rows, reps, label=s["label"], display=s["display"],
                       layer=s["layer"], source=source, metier=metier, prims=s["prims"])
        print(f"[OK] {pdf.name[:52]:52} {len(sheet['symbols']):>4} symboles", flush=True)
    return rows, reps


def collect_from_unpaired(limit: int | None = None):
    rows = []
    reps = {}
    dwgs = unpaired_dwgs()
    if limit:
        dwgs = dwgs[:limit]
    for dwg in dwgs:
        try:
            by_metier = render_floors_by_metier(dwg)
        except Exception as e:
            print(f"[WARN] {dwg.name}: {str(e)[:100]}", flush=True)
            continue
        # render_floors_by_metier ne retourne que les boites meta, pas les prims.
        # On recharge la feuille complete pour conserver les dessins representatifs.
        try:
            sheet = build_sheet(dwg, None)
        except Exception:
            continue
        source = dwg.name
        n = 0
        for s in sheet["symbols"]:
            metier = metier_of_layer(s["layer"])
            if not metier or metier not in by_metier:
                continue
            add_symbol(rows, reps, label=s["label"], display=s["display"],
                       layer=s["layer"], source=source, metier=metier, prims=s["prims"])
            n += 1
        print(f"[OK] {dwg.name[:52]:52} {n:>4} symboles", flush=True)
    return rows, reps


def merge_reps(*rep_dicts):
    merged = {}
    for reps in rep_dicts:
        for key, r in reps.items():
            if key not in merged:
                merged[key] = dict(r)
                merged[key]["sources"] = Counter(r["sources"])
                continue
            merged[key]["count"] += r["count"]
            merged[key]["sources"].update(r["sources"])
    return merged


def write_outputs(rows, reps):
    OUT.mkdir(exist_ok=True)
    csv_path = OUT / "symbol_taxonomy.csv"
    json_path = OUT / "symbol_taxonomy.json"
    html_path = OUT / "symbol_taxonomy.html"

    fields = ["raw", "current_class", "display_metier", "display", "layer", "source",
              "shape_signature"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k) for k in fields} for r in rows)

    serial = []
    for r in reps.values():
        serial.append({
            "raw": r["raw"],
            "current_class": r["current_class"],
            "display_metier": r["display_metier"],
            "display": r["display"],
            "layer": r["layer"],
            "count": r["count"],
            "sources": dict(r["sources"].most_common(8)),
            "shape_signature": r["shape_signature"],
        })
    serial.sort(key=lambda r: (str(r["current_class"]), str(r["display_metier"]),
                              -r["count"], r["raw"]))
    json_path.write_text(json.dumps(serial, ensure_ascii=False, indent=1), encoding="utf-8")

    by_class = defaultdict(list)
    for key, r in reps.items():
        by_class[r["current_class"] or "(EXCLU)"].append(r)

    sections = []
    css = """
    body{font-family:Arial,sans-serif;margin:24px;background:#f6f7f9;color:#111}
    h1{font-size:24px;margin:0 0 8px} h2{font-size:18px;margin:28px 0 12px}
    .meta{color:#555;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
    .card{background:white;border:1px solid #d7dce2;border-radius:6px;padding:10px;display:grid;grid-template-columns:104px 1fr;gap:10px;align-items:start}
    .name{font-weight:700;font-size:13px}.small{font-size:11px;color:#555;line-height:1.35;word-break:break-word}
    .pill{display:inline-block;border:1px solid #c8d0da;border-radius:999px;padding:2px 6px;font-size:11px;margin:2px 2px 0 0;background:#f9fafb}
    svg{border:1px solid #e2e6eb;background:white}
    """
    for cls in sorted(by_class, key=lambda x: (x == "(EXCLU)", str(x))):
        cards = []
        items = sorted(by_class[cls], key=lambda r: (-r["count"], r["raw"]))
        for r in items:
            srcs = ", ".join(f"{k} ({v})" for k, v in r["sources"].most_common(3))
            cards.append(
                '<article class="card">'
                f'{thumb_svg(r["prims"])}'
                '<div>'
                f'<div class="name">{html.escape(r["raw"])}</div>'
                f'<div><span class="pill">{html.escape(str(r["display_metier"]))}</span>'
                f'<span class="pill">{r["count"]} inst.</span></div>'
                f'<div class="small">bloc: {html.escape(r["display"])}</div>'
                f'<div class="small">calque: {html.escape(r["layer"])}</div>'
                f'<div class="small">sources: {html.escape(srcs)}</div>'
                '</div></article>'
            )
        sections.append(
            f'<h2>{html.escape(str(cls))} <span class="small">({len(items)} formes/noms)</span></h2>'
            f'<div class="grid">{"".join(cards)}</div>'
        )
    html_doc = (
        "<!doctype html><meta charset='utf-8'>"
        f"<style>{css}</style>"
        "<h1>Revue taxonomie symboles</h1>"
        f"<div class='meta'>{len(reps)} couples nom+forme, {len(rows)} instances sources. "
        "La classe actuelle vient de canon(); le metier est uniquement indicatif pour l'affichage.</div>"
        + "".join(sections)
    )
    html_path.write_text(html_doc, encoding="utf-8")
    return csv_path, json_path, html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("paired", "unpaired", "all"), default="paired",
                    help="paired = DWG+PDF visibles ; unpaired = DWG seuls par calque ; all = les deux")
    ap.add_argument("--limit", type=int, default=None,
                    help="limite de debug sur le nombre de plans traites")
    args = ap.parse_args()

    all_rows = []
    rep_sets = []
    if args.source in ("paired", "all"):
        rows, reps = collect_from_paired(args.limit)
        all_rows.extend(rows)
        rep_sets.append(reps)
    if args.source in ("unpaired", "all"):
        rows, reps = collect_from_unpaired(args.limit)
        all_rows.extend(rows)
        rep_sets.append(reps)
    reps = merge_reps(*rep_sets)
    csv_path, json_path, html_path = write_outputs(all_rows, reps)
    print(f"\n{len(reps)} couples nom+forme, {len(all_rows)} instances")
    print(f"CSV :  {csv_path}")
    print(f"JSON : {json_path}")
    print(f"HTML : {html_path}")


if __name__ == "__main__":
    main()
