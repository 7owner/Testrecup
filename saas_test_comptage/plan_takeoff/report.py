"""Sorties : CSV consolide, rapport HTML auditable (vignettes + overlays SVG)."""
from __future__ import annotations

import csv
import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
           "#f032e6", "#bfef45", "#469990", "#9a6324", "#800000", "#808000",
           "#000075", "#dcbeff", "#fabed4", "#aaffc3"]


def color_for(name: str) -> str:
    return PALETTE[hash(name) % len(PALETTE)]


def tally(per_insert: list, label_by_display: dict):
    """Comptage final par (zone, display, layer) sur les inserts non exclus."""
    c = Counter()
    for ins in per_insert:
        if ins.get("excluded"):
            continue
        c[(ins.get("zone", ""), ins["display"], ins.get("layer", "?"))] += 1
    rows = []
    for (zone, display, layer), n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])):
        rows.append({
            "zone": zone, "display": display, "layer": layer, "count": n,
            "label": label_by_display.get(display, display),
        })
    return rows


def tally_excluded(per_insert: list):
    c = Counter()
    for ins in per_insert:
        if ins.get("excluded"):
            c[(ins["display"], ins["excluded"])] += 1
    return [{"display": d, "reason": r, "count": n} for (d, r), n in c.most_common()]


# ---------------------------------------------------------------- SVG helpers

def _prims_bbox(prims):
    xs, ys = [], []
    for p in prims:
        if p[0] == "l":
            xs += [p[1][0], p[2][0]]; ys += [p[1][1], p[2][1]]
        elif p[0] in ("c", "a"):
            xs += [p[1][0] - p[2], p[1][0] + p[2]]
            ys += [p[1][1] - p[2], p[1][1] + p[2]]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _prims_to_svg_elems(prims, fx, fy, stroke="#222", width=1.0):
    out = []
    for p in prims:
        if p[0] == "l":
            out.append(f'<line x1="{fx(p[1][0]):.1f}" y1="{fy(p[1][1]):.1f}" '
                       f'x2="{fx(p[2][0]):.1f}" y2="{fy(p[2][1]):.1f}" '
                       f'stroke="{stroke}" stroke-width="{width}"/>')
        elif p[0] == "c":
            r = abs(fx(p[1][0] + p[2]) - fx(p[1][0]))
            out.append(f'<circle cx="{fx(p[1][0]):.1f}" cy="{fy(p[1][1]):.1f}" r="{r:.1f}" '
                       f'fill="none" stroke="{stroke}" stroke-width="{width}"/>')
        elif p[0] == "a":
            cx, cy, r = p[1][0], p[1][1], p[2]
            a0, a1 = p[3], p[4]
            if a1 < a0:
                a1 += 2 * math.pi
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            rr = abs(fx(cx + r) - fx(cx))
            large = 1 if (a1 - a0) > math.pi else 0
            out.append(f'<path d="M {fx(x0):.1f} {fy(y0):.1f} A {rr:.1f} {rr:.1f} 0 {large} 0 '
                       f'{fx(x1):.1f} {fy(y1):.1f}" fill="none" stroke="{stroke}" stroke-width="{width}"/>')
    return out


def block_thumbnail_svg(prims, size=44) -> str:
    bb = _prims_bbox(prims)
    if bb is None:
        return f'<svg width="{size}" height="{size}"><rect width="100%" height="100%" fill="#f2f2f2"/></svg>'
    x0, y0, x1, y1 = bb
    span = max(x1 - x0, y1 - y0) or 1.0
    pad = span * 0.1
    x0 -= pad; y0 -= pad; span += 2 * pad
    scale = size / span
    fx = lambda x: (x - x0) * scale
    fy = lambda y: size - (y - y0) * scale
    elems = _prims_to_svg_elems(prims[:200], fx, fy, "#1c2230", 1.1)
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">' + "".join(elems) + "</svg>"


def overlay_svg(plan: dict, per_insert: list, zones: dict, width=1600) -> str:
    pts = [ins["pt"] for ins in per_insert if not ins.get("excluded")]
    sk = plan.get("skeleton") or []
    bb = _prims_bbox(sk)
    xs = [p[0] for p in pts] + ([bb[0], bb[2]] if bb else [])
    ys = [p[1] for p in pts] + ([bb[1], bb[3]] if bb else [])
    if not xs:
        return "<svg/>"
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    spanx = (x1 - x0) or 1.0
    spany = (y1 - y0) or 1.0
    height = int(width * spany / spanx) or 1
    if height > 6000:
        height = 6000
    scale = min(width / spanx, height / spany)
    fx = lambda x: (x - x0) * scale + 4
    fy = lambda y: height - (y - y0) * scale + 4

    elems = _prims_to_svg_elems(sk[:20000], fx, fy, "#c8cdd6", 0.6)
    for name, (bx0, by0, bx1, by1) in (zones or {}).items():
        elems.append(f'<rect x="{fx(bx0):.0f}" y="{fy(by1):.0f}" width="{(fx(bx1)-fx(bx0)):.0f}" '
                     f'height="{(fy(by0)-fy(by1)):.0f}" fill="none" stroke="#8899bb" stroke-dasharray="6 4"/>')
        elems.append(f'<text x="{fx(bx0):.0f}" y="{fy(by1)-6:.0f}" font-size="16" fill="#556">{html.escape(name)}</text>')
    for ins in per_insert:
        if ins.get("excluded"):
            continue
        x, y = fx(ins["pt"][0]), fy(ins["pt"][1])
        col = color_for(ins["display"])
        elems.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{col}" fill-opacity="0.85">'
                     f'<title>{html.escape(ins["display"])}</title></circle>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + 8}" height="{height + 8}" '
            f'style="background:#fff">' + "".join(elems) + "</svg>")


# ---------------------------------------------------------------- rapport

def write_outputs(results: list, out_dir: Path):
    """results: [{affaire, plan_name, source, rows, excluded, per_insert, zones, blocks_prims, error?}]"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plans").mkdir(exist_ok=True)

    # CSV consolide
    with open(out_dir / "comptage.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["affaire", "plan", "zone", "libelle_legende", "bloc", "calque",
                    "quantite", "qte_declaree_legende"])
        for r in results:
            for row in r.get("rows") or []:
                w.writerow([r["affaire"], r["plan_name"], row["zone"], row["label"],
                            row["display"], row["layer"], row["count"],
                            row.get("qty_declared", "")])

    # JSON par plan + overlay
    for r in results:
        safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in f'{r["affaire"]}__{r["plan_name"]}')
        (out_dir / "plans" / f"{safe}.json").write_text(
            json.dumps({k: r[k] for k in ("affaire", "plan_name", "source", "rows", "excluded") if k in r},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        if r.get("per_insert"):
            svg = overlay_svg(r["_plan"], r["per_insert"], r.get("zones") or {})
            (out_dir / "plans" / f"{safe}.svg").write_text(svg, encoding="utf-8")
            r["overlay"] = f"plans/{safe}.svg"
        elif r.get("_pdf") and r.get("overlays"):
            from pdf_takeoff import overlay_svg_pdf
            for ov in r["overlays"]:
                svg = overlay_svg_pdf(r["_pdf"], ov)
                suffix = f"_p{ov['page'] + 1}" if len(r["overlays"]) > 1 else ""
                (out_dir / "plans" / f"{safe}{suffix}.svg").write_text(svg, encoding="utf-8")
                r.setdefault("overlay", f"plans/{safe}{suffix}.svg")

    # HTML
    parts = ["""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Comptage plans - rapport</title><style>
body{font-family:"Segoe UI",Arial,sans-serif;margin:24px;background:#f4f6fa;color:#182033}
h1{color:#21479b}h2{color:#17366f;margin-top:34px;border-bottom:2px solid #d9e2f1;padding-bottom:4px}
h3{margin:18px 0 6px}table{border-collapse:collapse;background:#fff;box-shadow:0 4px 14px rgba(23,34,58,.08)}
th,td{border:1px solid #dbe3f0;padding:5px 10px;font-size:13px;text-align:left}
th{background:#eef2fa}td.n{text-align:right;font-weight:700}
.thumb svg{vertical-align:middle}.excl{color:#888;font-size:12px}
.badge{display:inline-block;border-radius:8px;padding:1px 8px;font-size:11px;color:#fff;background:#21479b}
a{color:#21479b}details{margin:8px 0}.err{color:#b42318;font-weight:700}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
</style></head><body>
<h1>Comptage des objets de legende - rapport</h1>
<p>Comptage deterministe depuis les DWG (entites INSERT par bloc). CSV consolide :
<a href="comptage.csv">comptage.csv</a>. Les points de chaque overlay sont survolables (nom du bloc).</p>"""]

    by_affaire = defaultdict(list)
    for r in results:
        by_affaire[r["affaire"]].append(r)

    for affaire in sorted(by_affaire):
        parts.append(f"<h2>{html.escape(affaire)}</h2>")
        for r in by_affaire[affaire]:
            parts.append(f"<h3>{html.escape(r['plan_name'])}</h3>")
            if r.get("error"):
                parts.append(f'<p class="err">Non parse : {html.escape(r["error"])}</p>')
                continue
            total = sum(row["count"] for row in r["rows"])
            parts.append(f'<p><span class="badge">{total} objets comptes</span> '
                         f'&nbsp;<a href="{r.get("overlay", "#")}" target="_blank">overlay du plan</a></p>')
            has_declared = any(row.get("qty_declared") is not None for row in r["rows"])
            decl_th = "<th>QTE legende</th>" if has_declared else ""
            parts.append("<table><tr><th></th><th>Symbole</th><th>Libelle legende</th>"
                         f"<th>Bloc</th><th>Zone</th><th>Calque</th><th>Qte</th>{decl_th}</tr>")
            for row in r["rows"]:
                thumb_b64 = (r.get("thumbs") or {}).get(row["label"])
                if thumb_b64:
                    thumb = f'<img src="data:image/png;base64,{thumb_b64}" style="max-width:60px;max-height:44px">'
                else:
                    prims = r["blocks_prims"].get(row["display"]) or []
                    thumb = block_thumbnail_svg(prims)
                dot = f'<span class="dot" style="background:{color_for(row["display"])}"></span>'
                decl_td = ""
                if has_declared:
                    q = row.get("qty_declared")
                    if q is None:
                        decl_td = "<td></td>"
                    elif q == row["count"]:
                        decl_td = f'<td class="n" style="color:#1f8a3c">{q} =</td>'
                    else:
                        decl_td = f'<td class="n" style="color:#b42318">{q} &ne;</td>'
                parts.append(
                    f'<tr><td class="thumb">{thumb}</td>'
                    f'<td>{dot}{html.escape(row["display"])}</td>'
                    f'<td>{html.escape(row["label"]) if row["label"] != row["display"] else ""}</td>'
                    f'<td>{html.escape(row["display"])}</td>'
                    f'<td>{html.escape(row["zone"])}</td>'
                    f'<td>{html.escape(row["layer"])}</td>'
                    f'<td class="n">{row["count"]}</td>{decl_td}</tr>')
            parts.append("</table>")
            if r.get("excluded"):
                items = ", ".join(f'{e["display"]} ({e["reason"]}: {e["count"]})' for e in r["excluded"][:40])
                parts.append(f'<details><summary class="excl">Blocs exclus du comptage '
                             f'({sum(e["count"] for e in r["excluded"])})</summary>'
                             f'<p class="excl">{html.escape(items)}</p></details>')

    parts.append("</body></html>")
    (out_dir / "index.html").write_text("".join(parts), encoding="utf-8")
