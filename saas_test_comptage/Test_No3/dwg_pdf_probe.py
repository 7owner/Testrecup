"""Probe DWG -> PDF pour une paire dossier.

Objectif: travailler dossier par dossier sans relancer un entrainement.

Pour une paire DWG/PDF, le script extrait:
  - les objets ponctuels visibles depuis le DWG (build_sheet) ;
  - les gabarits de legende detectes dans le PDF vectoriel ;
  - les comptes de la methode PDF actuelle ;
  - une empreinte binaire normalisee par forme DWG representative.

Les sorties sont des artefacts de revue, pas un dataset final.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plan_takeoff"))

import fitz  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import pdf_takeoff as pt  # noqa: E402
from render_dwg import _prims_bbox, _prims_to_svg_elems, build_sheet  # noqa: E402
from render_symbol_taxonomy import shape_signature  # noqa: E402


def _safe_name(value: str) -> str:
    keep = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    return "".join(keep).strip("_")[:120] or "probe"


def _draw_binary(prims, size=64, stroke=2):
    bb = _prims_bbox(prims)
    if not bb:
        return {
            "hash": "empty",
            "bits": "",
            "ink_ratio": 0.0,
            "ratio": 0.0,
            "size": size,
        }

    x0, y0, x1, y1 = bb
    spanx = max(x1 - x0, 1e-9)
    spany = max(y1 - y0, 1e-9)
    pad = size * 0.12
    scale = min((size - 2 * pad) / spanx, (size - 2 * pad) / spany)

    def tf(pt):
        x, y = pt
        return (pad + (x - x0) * scale, size - pad - (y - y0) * scale)

    img = Image.new("1", (size, size), 0)
    draw = ImageDraw.Draw(img)
    for prim in prims:
        if prim[0] == "l":
            draw.line([tf(prim[1]), tf(prim[2])], fill=1, width=stroke)
        elif prim[0] == "c":
            cx, cy = tf(prim[1])
            r = abs(float(prim[2]) * scale)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=1, width=stroke)
        elif prim[0] == "a":
            cx, cy = tf(prim[1])
            r = abs(float(prim[2]) * scale)
            # PIL angles are degrees clockwise-ish in image coordinates. This is
            # only a fingerprint for review, not the final geometric matcher.
            a0 = math.degrees(-prim[4])
            a1 = math.degrees(-prim[3])
            draw.arc([cx - r, cy - r, cx + r, cy + r], start=a0, end=a1, fill=1, width=stroke)

    data = img.tobytes()
    bits = "".join("1" if px else "0" for px in img.getdata())
    ink = bits.count("1") / float(size * size)
    return {
        "hash": hashlib.sha1(data).hexdigest()[:16],
        "bits": bits,
        "ink_ratio": round(ink, 4),
        "ratio": round(spanx / spany, 3),
        "size": size,
    }


def _thumb_svg(prims, size=96):
    bb = _prims_bbox(prims)
    if not bb:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"></svg>'
    x0, y0, x1, y1 = bb
    spanx = max(x1 - x0, 1e-9)
    spany = max(y1 - y0, 1e-9)
    pad = size * 0.12
    scale = min((size - 2 * pad) / spanx, (size - 2 * pad) / spany)

    def fx(x):
        return pad + (x - x0) * scale

    def fy(y):
        return size - pad - (y - y0) * scale

    elems = _prims_to_svg_elems(prims, fx, fy, "#111", 1.6)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        + "".join(elems) +
        "</svg>"
    )


def _summarize_dwg(sheet):
    by_label = Counter(s["label"] for s in sheet["symbols"])
    by_display = Counter(s["display"] for s in sheet["symbols"])
    reps = {}
    for s in sheet["symbols"]:
        sig = shape_signature(s["prims"])
        key = (s["label"], s["display"], sig)
        if key not in reps:
            fp = _draw_binary(s["prims"])
            reps[key] = {
                "label": s["label"],
                "display": s["display"],
                "layer": s["layer"],
                "shape_signature": sig,
                "fingerprint_hash": fp["hash"],
                "fingerprint_bits": fp["bits"],
                "fingerprint_ink_ratio": fp["ink_ratio"],
                "fingerprint_ratio": fp["ratio"],
                "count": 0,
                "thumb_svg": _thumb_svg(s["prims"]),
            }
        reps[key]["count"] += 1
    return by_label, by_display, list(reps.values())


def _summarize_pdf(pdf_path: Path):
    doc = fitz.open(pdf_path)
    page = doc[0]
    clusters, words = pt.extract_page(page)
    templates, legend_rect = pt.find_legend_templates(clusters, words, page.rect)
    doc.close()

    current = pt.count_pdf(pdf_path)
    rows = current.get("rows", [])
    return {
        "clusters": len(clusters),
        "words": len(words),
        "legend_rect": list(legend_rect) if legend_rect else None,
        "templates": [
            {
                "label": t.get("label"),
                "qty_declared": t.get("qty_declared"),
                "bbox": [round(v, 2) for v in t["cluster"]["bbox"]],
                "ops": t["cluster"]["ops"],
                "n_paths": t["cluster"]["n_paths"],
            }
            for t in templates
        ],
        "counts": rows,
    }


def _write_csv(path: Path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_html(path: Path, data):
    dwg_rows = []
    for row in data["dwg"]["fingerprints"]:
        dwg_rows.append(
            "<tr>"
            f"<td>{row['thumb_svg']}</td>"
            f"<td>{html.escape(row['label'])}</td>"
            f"<td>{html.escape(row['display'])}</td>"
            f"<td>{row['count']}</td>"
            f"<td><code>{row['fingerprint_hash']}</code></td>"
            f"<td>{row['fingerprint_ratio']}</td>"
            f"<td>{row['fingerprint_ink_ratio']}</td>"
            f"<td>{html.escape(row['layer'])}</td>"
            "</tr>"
        )

    pdf_rows = []
    for row in data["pdf"]["counts"]:
        pdf_rows.append(
            "<tr>"
            f"<td>{html.escape(row.get('label') or '')}</td>"
            f"<td>{row.get('count', '')}</td>"
            f"<td>{row.get('qty_declared', '')}</td>"
            f"<td>{html.escape(row.get('conf') or '')}</td>"
            f"<td>{html.escape(row.get('layer') or '')}</td>"
            "</tr>"
        )

    tpl_rows = []
    for row in data["pdf"]["templates"]:
        tpl_rows.append(
            "<tr>"
            f"<td>{html.escape(row.get('label') or '')}</td>"
            f"<td>{row.get('qty_declared', '')}</td>"
            f"<td>{html.escape(str(row.get('ops') or ''))}</td>"
            f"<td>{row.get('n_paths', '')}</td>"
            f"<td>{html.escape(str(row.get('bbox') or ''))}</td>"
            "</tr>"
        )

    path.write_text(
        """<!doctype html>
<meta charset="utf-8">
<title>DWG PDF probe</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#172033;background:#f7f8fb}
h1,h2{margin:0 0 12px}
section{background:#fff;border:1px solid #d8deea;border-radius:8px;padding:16px;margin:16px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #e5e9f2;padding:7px 8px;text-align:left;vertical-align:middle}
th{background:#f1f4f9}
code{font-size:12px}
.meta{color:#526070}
</style>
"""
        f"<h1>{html.escape(data['pair']['name'])}</h1>"
        f"<p class='meta'>DWG: {html.escape(data['pair']['dwg'])}<br>PDF: {html.escape(data['pair']['pdf'])}</p>"
        "<section><h2>Resume</h2>"
        f"<p>DWG symboles: <b>{data['dwg']['total']}</b> | "
        f"PDF clusters: <b>{data['pdf']['clusters']}</b> | "
        f"gabarits legende PDF: <b>{len(data['pdf']['templates'])}</b></p>"
        "</section>"
        "<section><h2>Empreintes DWG</h2><table><thead><tr>"
        "<th>forme</th><th>label</th><th>display</th><th>count</th><th>hash</th>"
        "<th>ratio</th><th>ink</th><th>layer exemple</th></tr></thead><tbody>"
        + "".join(dwg_rows) +
        "</tbody></table></section>"
        "<section><h2>Comptes PDF actuels</h2><table><thead><tr>"
        "<th>label</th><th>count</th><th>QTE legende</th><th>conf</th><th>layer</th></tr></thead><tbody>"
        + "".join(pdf_rows) +
        "</tbody></table></section>"
        "<section><h2>Gabarits legende PDF</h2><table><thead><tr>"
        "<th>label</th><th>QTE</th><th>ops</th><th>paths</th><th>bbox</th></tr></thead><tbody>"
        + "".join(tpl_rows) +
        "</tbody></table></section>",
        encoding="utf-8",
    )


def run_probe(dwg_path: Path, pdf_path: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet(dwg_path, pdf_path)
    by_label, by_display, fingerprints = _summarize_dwg(sheet)
    pdf = _summarize_pdf(pdf_path)

    name = _safe_name(pdf_path.stem)
    data = {
        "pair": {
            "name": pdf_path.stem,
            "dwg": str(dwg_path),
            "pdf": str(pdf_path),
        },
        "dwg": {
            "total": len(sheet["symbols"]),
            "plotted_layers": sheet["plotted"],
            "by_label": dict(by_label),
            "by_display": dict(by_display),
            "fingerprints": fingerprints,
        },
        "pdf": pdf,
    }

    json_path = out_dir / f"{name}.probe.json"
    csv_path = out_dir / f"{name}.dwg_fingerprints.csv"
    html_path = out_dir / f"{name}.probe.html"

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(csv_path, fingerprints, [
        "label", "display", "count", "layer", "fingerprint_hash",
        "fingerprint_ratio", "fingerprint_ink_ratio", "shape_signature",
    ])
    _write_html(html_path, data)
    return data, json_path, csv_path, html_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dwg", required=True, type=Path)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=HERE / "out" / "dwg_pdf_probe")
    args = parser.parse_args(argv)

    data, json_path, csv_path, html_path = run_probe(args.dwg, args.pdf, args.out_dir)
    print(f"DWG symboles: {data['dwg']['total']}")
    print(f"PDF clusters: {data['pdf']['clusters']}")
    print(f"Gabarits legende PDF: {len(data['pdf']['templates'])}")
    print("Comptes DWG par label:")
    for label, count in sorted(data["dwg"]["by_label"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {count:>4}  {label}")
    print("Comptes PDF actuels:")
    for row in data["pdf"]["counts"]:
        print(f"  {row.get('count', 0):>4}  {row.get('label')}  qte={row.get('qty_declared')}  {row.get('conf')}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"HTML: {html_path}")


if __name__ == "__main__":
    main()
