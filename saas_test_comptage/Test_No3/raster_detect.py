"""Detection raster haute-resolution : le plan est rendu en HD, chaque symbole est une
COMPOSANTE CONNEXE (bitmap reel), appariee au glyphe de la LEGENDE par similarite d'image.

Motivation (valide le 2026-07-20) : en vectoriel, un petit symbole (va-et-vient, simple
allumage, BAES) n'a que 2-6 points -> signature de forme degeneree -> confondu avec
d'autres et non regroupe. En rendant le plan a haute resolution, le meme symbole devient
une forme de dizaines de pixels, discriminable par comparaison d'image binaire.

Chaine :
  PDF --render HD (DPI eleve, niveaux de gris)--> image
      --Otsu + fermeture--> binaire
      --composantes connexes (hors legende, hors texte, taille symbole)--> candidats bitmap
  legende --glyphes rasterises (32x32 binaire, 4 rotations)--> prototypes
  candidat --meilleur IoU sur rotations--> label si >= seuil ; sinon "non identifie"
  -> comptes par label + boites + image d'apercu.

`extract_page` fournit aussi les MOTS : tout candidat centre dans une boite de mot est
rejete (c'est du texte, pas un symbole) -> supprime l'essentiel du bruit.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import cv2
import fitz

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plan_takeoff"))

import pdf_takeoff as pt  # noqa: E402
from dwg_pdf_match import _cluster_points  # noqa: E402

NORM = 32            # cote du bitmap normalise pour comparer les formes
DIAG_MIN_PT = 3.0    # taille symbole min (points PDF)
DIAG_MAX_PT = 90.0
MATCH_IOU = 0.55     # IoU min candidat<->prototype de legende pour attribuer un label


def _norm_bitmap(crop):
    """bitmap binaire quelconque -> NxN binaire, ratio preserve (aspect-fit centre)."""
    h, w = crop.shape
    if h == 0 or w == 0:
        return None
    s = (NORM - 2) / max(h, w)
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    small = cv2.resize(crop.astype(np.uint8), (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((NORM, NORM), np.uint8)
    oy, ox = (NORM - nh) // 2, (NORM - nw) // 2
    out[oy:oy + nh, ox:ox + nw] = (small > 0).astype(np.uint8)
    return out


def _iou(a, b):
    inter = int(np.count_nonzero(a & b))
    if inter == 0:
        return 0.0
    union = int(np.count_nonzero(a | b))
    return inter / union if union else 0.0


def _rotations(bm):
    """bm + ses 3 rotations 90deg (les symboles sont poses dans toute orientation)."""
    r = [bm]
    for _ in range(3):
        r.append(np.rot90(r[-1]))
    return r


def detect(pdf_path, dpi=200, match_iou=MATCH_IOU, preview_w=2200):
    doc = fitz.open(pdf_path)
    page = doc[0]
    pr = page.rect
    clusters, words = pt.extract_page(page)
    templates, legend_rect = pt.find_legend_templates(clusters, words, page.rect)

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    _, binz = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binz = cv2.morphologyEx(binz, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    # boites de mots (texte) en pixels -> pour rejeter le texte
    word_boxes = [(w[0] * zoom, w[1] * zoom, w[2] * zoom, w[3] * zoom) for w in words]

    def in_legend(cx, cy):
        return legend_rect is not None and legend_rect.contains(fitz.Point(cx / zoom, cy / zoom))

    def in_text(cx, cy):
        for x0, y0, x1, y1 in word_boxes:
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return True
        return False

    # --- prototypes de legende rasterises (bitmap 32x32 + 4 rotations) ---
    protos = []
    binmap = (binz > 0)
    for t in templates:
        vb = [v["bbox"] for v in (t.get("variants") or [t["cluster"]])]
        bx0 = int(min(b[0] for b in vb) * zoom); by0 = int(min(b[1] for b in vb) * zoom)
        bx1 = int(max(b[2] for b in vb) * zoom); by1 = int(max(b[3] for b in vb) * zoom)
        bx0, by0 = max(0, bx0), max(0, by0)
        bx1, by1 = min(binz.shape[1], bx1), min(binz.shape[0], by1)
        if bx1 - bx0 < 3 or by1 - by0 < 3:
            continue
        bm = _norm_bitmap(binmap[by0:by1, bx0:bx1])
        if bm is None or bm.sum() < 4:
            continue
        protos.append({"label": t["label"], "qty": t.get("qty_declared"),
                       "bmaps": _rotations(bm)})

    # --- composantes connexes = candidats ---
    n, lab, stats, cent = cv2.connectedComponentsWithStats(binz, connectivity=8)
    detections = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        d_pt = math.hypot(w, h) / zoom
        if d_pt < DIAG_MIN_PT or d_pt > DIAG_MAX_PT or area < 6:
            continue
        cx, cy = cent[i]
        if in_legend(cx, cy):
            continue
        comp = (lab[y:y + h, x:x + w] == i)
        bm = _norm_bitmap(comp.astype(np.uint8))
        if bm is None or bm.sum() < 4:
            continue
        best_lab, best_iou = None, match_iou
        for p in protos:
            iou = max(_iou(bm, pb) for pb in p["bmaps"])
            if iou > best_iou:
                best_iou, best_lab = iou, p["label"]
        detections.append({"bbox_pt": [x / zoom, y / zoom, (x + w) / zoom, (y + h) / zoom],
                            "label": best_lab, "iou": round(best_iou, 3)})
    doc.close()

    return {"pr": (pr.width, pr.height), "zoom": zoom, "img_shape": img.shape,
            "legend_rect": list(legend_rect) if legend_rect else None,
            "protos": [{"label": p["label"], "qty": p["qty"]} for p in protos],
            "detections": detections}


if __name__ == "__main__":
    import collections
    pdf = Path(sys.argv[1])
    dpi = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    res = detect(pdf, dpi=dpi)
    named = [d for d in res["detections"] if d["label"]]
    none = [d for d in res["detections"] if not d["label"]]
    counts = collections.Counter(d["label"] for d in named)
    print(f"DPI={dpi} | prototypes legende={len(res['protos'])} | composantes candidates="
          f"{len(res['detections'])} | identifiees={len(named)} | non identifiees={len(none)}")
    print(f"total compte (identifie) = {len(named)}")
    for lab, n in counts.most_common(20):
        print(f"   {n:>4}  {lab[:48]}")
