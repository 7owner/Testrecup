"""Auto-etiquetage : d'une paire (DWG, PDF), produit les boites de chaque symbole
projetees sur les pixels du PDF, la classe = NOM DE BLOC du DWG.

Chaine :
1. DWG -> INSERTs (position modele, nom de bloc, calque) + bbox locale du bloc ;
2. PDF -> glyphes vectoriels (centroide + calque OCG) via plan_takeoff ;
3. calques communs DWG/PDF -> nuages de points -> recouvrement de la similarite
   modele->affichage (align.recover_transform) ;
4. projection de chaque INSERT (sur un calque trace) en boite pixel du PDF.

Aucune annotation manuelle : les etiquettes viennent du DWG.
"""
from __future__ import annotations

import base64
import html
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

import fitz  # noqa: E402
import dwg_reader as dr  # noqa: E402
import pdf_takeoff as pt  # noqa: E402
from align import recover_transform, apply_tf  # noqa: E402

CACHE = HERE / "_cache"

# calques a ecarter du RECALAGE (tags/textes/cartouche : mal correles aux symboles)
NOISE_LAYER_TOKENS = ("designation", "désignation", "texte", "text", "cartouche",
                      "cotation", "reperage", "repérage", "legende", "légende")


def detect_metier(path: Path) -> str:
    """Metier (CFO/CFA/SSI/VDI/CVC...) depuis le chemin ou le nom de fichier."""
    s = str(path).upper()
    # sous-metiers CFA explicites
    for key, met in (("VIDEOSURV", "CFA-VIDEO"), ("SSI", "SSI"), ("SONORIS", "CFA-SONO"),
                     ("VDI", "CFA-VDI"), ("INTRUSION", "CFA-INTRU"), ("CONTROLE", "CFA-ACCES")):
        if key in s:
            return met
    for met in ("CFO", "CFA", "CVC", "PLB"):
        if f"-{met}-" in s or f"/{met}/" in s or f" {met} " in s or f"_{met}" in s:
            return met
    return "AUTRE"


def _is_noise_layer(layer: str) -> bool:
    low = layer.lower()
    return any(tok in low for tok in NOISE_LAYER_TOKENS)
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
           "#f032e6", "#bfef45", "#469990", "#9a6324", "#800000", "#808000",
           "#000075", "#e6beff", "#aaffc3", "#fabed4"]


def block_local_halfextent(block) -> float:
    """Demi-diagonale de la bbox locale du bloc (unites modele). 0 si vide."""
    xs, ys = [], []
    for pr in block.get("prims", ()):
        op = pr[0]
        if op == "l":
            xs += [pr[1][0], pr[2][0]]
            ys += [pr[1][1], pr[2][1]]
        elif op in ("c", "a"):
            cx, cy = pr[1]
            r = pr[2]
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
    if not xs:
        return 0.0
    return 0.5 * math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def load_pair(dwg_path: Path, pdf_path: Path, page_no: int = 0):
    plan = dr.extract_plan(dwg_path, cache_dir=CACHE)
    blocks = plan["blocks"]

    def bname(h):
        b = blocks.get(str(h))
        return (b["name"] if b else f"?{h}").strip()

    inserts = []
    for ins in plan["inserts"]:
        b = blocks.get(str(ins["block"]))
        if b is None or b.get("is_xref"):
            continue
        inserts.append({
            "name": bname(ins["block"]),
            "layer": (ins.get("layer") or "").strip(),
            "pt": ins["pt"],
            "half": block_local_halfextent(b),
        })

    doc = fitz.open(pdf_path)
    page = doc[page_no]
    clusters, words = pt.extract_page(page)
    pdf_glyphs = [{"c": ((c["bbox"][0] + c["bbox"][2]) / 2,
                         (c["bbox"][1] + c["bbox"][3]) / 2),
                   "layer": (c["layer"] or "").strip()} for c in clusters]
    meta = {"rect": [page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1],
            "rotation": page.rotation}
    doc.close()
    return inserts, pdf_glyphs, meta


def shared_layers(inserts, pdf_glyphs, min_count=3):
    dwg_l = Counter(i["layer"] for i in inserts if i["layer"])
    pdf_l = Counter(g["layer"] for g in pdf_glyphs if g["layer"])
    shared = {l for l in dwg_l if l in pdf_l
              and dwg_l[l] >= min_count and pdf_l[l] >= min_count}
    return shared, dwg_l, pdf_l


def autolabel(dwg_path: Path, pdf_path: Path, page_no: int = 0):
    inserts, pdf_glyphs, meta = load_pair(dwg_path, pdf_path, page_no)
    shared, dwg_l, pdf_l = shared_layers(inserts, pdf_glyphs)

    # RECALAGE : calques communs, hors calques de bruit (tags/textes) et hors blocs
    # anonymes *U (frames de tag, mal correles). L'ETIQUETAGE, lui, garde tout.
    align_layers = {l for l in shared if not _is_noise_layer(l)}
    model_pts = [i["pt"] for i in inserts
                 if i["layer"] in align_layers and not i["name"].startswith("*")]
    pdf_pts = [g["c"] for g in pdf_glyphs if g["layer"] in align_layers]
    res = recover_transform(model_pts, pdf_pts)
    if res is None:
        return {"ok": False, "reason": "alignement impossible",
                "shared_layers": sorted(shared),
                "dwg_layers": dwg_l.most_common(), "pdf_layers": pdf_l.most_common()}

    tf = res["tf"]
    s = res["scale"]
    # boites (repere d'affichage PDF)
    boxes = []
    for i in inserts:
        if i["layer"] not in shared:
            continue
        cx, cy = apply_tf(tf, i["pt"])
        half = max(i["half"] * s, 6.0)  # pixels d'affichage
        boxes.append({"name": i["name"], "layer": i["layer"],
                      "cx": cx, "cy": cy, "half": half})
    counts = Counter(b["name"] for b in boxes)
    return {"ok": True, "boxes": boxes, "meta": meta,
            "align": {k: res[k] for k in ("inliers", "n_model", "n_pdf", "scale", "deg", "rms")},
            "shared_layers": sorted(shared), "counts": counts.most_common()}


def render_overlay(pdf_path: Path, result: dict, dpi=90) -> bytes:
    """PNG : page PDF + boites auto-etiquetees, couleur par classe."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
    w, h = pix.width, pix.height
    names = [n for n, _ in result["counts"]]
    color = {n: PALETTE[k % len(PALETTE)] for k, n in enumerate(names)}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">',
             f'<image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>']
    for b in result["boxes"]:
        col = color.get(b["name"], "#e6194b")
        x = (b["cx"] - b["half"]) * zoom
        y = (b["cy"] - b["half"]) * zoom
        wd = 2 * b["half"] * zoom
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{wd:.1f}" height="{wd:.1f}" '
                     f'fill="none" stroke="{col}" stroke-width="2">'
                     f'<title>{html.escape(b["name"])}</title></rect>')
    parts.append("</svg>")
    svg = "".join(parts)
    doc.close()
    tmp = HERE / "out" / "_tmp_overlay.svg"
    tmp.write_text(svg, encoding="utf-8")
    d2 = fitz.open(str(tmp))
    png = d2[0].get_pixmap().tobytes("png")
    d2.close()
    return png


if __name__ == "__main__":
    dwg = Path(sys.argv[1])
    pdf = Path(sys.argv[2])
    r = autolabel(dwg, pdf)
    if not r["ok"]:
        print("ECHEC:", r["reason"])
        print("calques communs:", r["shared_layers"])
    else:
        print("alignement:", r["align"])
        print("calques traces:", r["shared_layers"])
        print("comptes (nom de bloc):")
        for n, c in r["counts"]:
            print(f"  {c:>4}  {n}")
        out = HERE / "out" / (pdf.stem + "_overlay.png")
        out.write_bytes(render_overlay(pdf, r))
        print("overlay:", out)
