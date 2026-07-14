"""Recalage DWG->PDF sur UN etage propre (retente apres separation des etages).

L'echec precedent venait du bruit : plusieurs etages + tags de designation
melanges dans le nuage de points. Ici on aligne un seul cluster d'etage (symboles
propres, bien repartis) sur les glyphes du PDF portes par LES MEMES calques.
Si ca verrouille, on obtient le vrai PDF comme image + boites exactes.
"""
from __future__ import annotations

import base64
import html
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

import fitz  # noqa: E402
import pdf_takeoff as pt  # noqa: E402
from render_dwg import build_sheet, split_floors  # noqa: E402
from align import recover_transform, apply_tf  # noqa: E402
from autolabel import PALETTE  # noqa: E402


def align_floor(dwg_path, pdf_path, page_no=0):
    sheet = build_sheet(dwg_path, pdf_path)
    syms = sheet["symbols"]
    if not syms:
        return None
    centers = [((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2) for s in syms]
    floors = split_floors(centers)
    floor = max(floors, key=len)           # le plus gros etage
    fsyms = [syms[i] for i in floor]

    # calques symboles de cet etage
    sym_layers = {s["layer"] for s in fsyms if s["layer"]}

    # glyphes PDF sur ces memes calques
    doc = fitz.open(pdf_path)
    page = doc[page_no]
    clusters, _ = pt.extract_page(page)
    doc.close()
    pdf_pts = [((c["bbox"][0] + c["bbox"][2]) / 2, (c["bbox"][1] + c["bbox"][3]) / 2)
               for c in clusters if (c["layer"] or "").strip() in sym_layers]

    model_pts = [s["pt"] for s in fsyms]
    res = recover_transform(model_pts, pdf_pts, tol=20.0, iters=8000)
    return {"sheet": sheet, "fsyms": fsyms, "sym_layers": sorted(sym_layers),
            "n_model": len(model_pts), "n_pdf": len(pdf_pts), "align": res}


def overlay_on_pdf(pdf_path, fsyms, tf, dpi=90):
    doc = fitz.open(pdf_path)
    page = doc[0]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
    w, h = pix.width, pix.height
    classes = sorted({s["label"] for s in fsyms})
    color = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(classes)}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">',
             f'<image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>']
    for s in fsyms:
        # bbox modele -> 4 coins -> affichage
        x0, y0, x1, y1 = s["bbox"]
        corners = [apply_tf(tf, p) for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        xs = [c[0] * zoom for c in corners]
        ys = [c[1] * zoom for c in corners]
        X, Y, W, H = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        parts.append(f'<rect x="{X:.1f}" y="{Y:.1f}" width="{W:.1f}" height="{H:.1f}" '
                     f'fill="none" stroke="{color[s["label"]]}" stroke-width="2">'
                     f'<title>{html.escape(s["label"])}</title></rect>')
    parts.append("</svg>")
    doc.close()
    tmp = HERE / "out" / "_tmp_alignpdf.svg"
    tmp.write_text("".join(parts), encoding="utf-8")
    d = fitz.open(str(tmp))
    png = d[0].get_pixmap().tobytes("png")
    d.close()
    return png


if __name__ == "__main__":
    dwg, pdf = Path(sys.argv[1]), Path(sys.argv[2])
    r = align_floor(dwg, pdf)
    if r is None or r["align"] is None:
        print("ECHEC alignement", None if r is None else
              {"n_model": r["n_model"], "n_pdf": r["n_pdf"], "layers": r["sym_layers"]})
    else:
        a = r["align"]
        print(f"n_model(etage)={r['n_model']}  n_pdf={r['n_pdf']}  calques={r['sym_layers']}")
        print(f"inliers={a['inliers']}/{a['n_model']}  scale={a['scale']:.3f}  "
              f"rot={a['deg']:.1f} deg  rms={a['rms']:.2f}px")
        out = HERE / "out" / (pdf.stem + "_alignPDF.png")
        out.write_bytes(overlay_on_pdf(pdf, r["fsyms"], a["tf"]))
        print("overlay:", out)
