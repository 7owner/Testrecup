"""Comptage PDF par appariement raster (template matching sur l'image rendue).

Complementaire de pdf_takeoff.py (vecteur) : ici on rend la page en pixels et on
fait glisser le symbole de la legende sur le plan. Robuste quand le symbole touche
un fil / un texte (la structure vectorielle fusionne, mais l'apparence reste).

Verite terrain pour le reglage : les DWG ROI RENE (comptage exact par bloc).
"""
from __future__ import annotations

import base64
import io
import math
from pathlib import Path

import numpy as np
import cv2
import fitz

from pdf_takeoff import extract_page, find_legend_templates

DPI = 200
ZOOM = DPI / 72.0
DEFAULT_THRESHOLD = 0.62
ROTATIONS = (0, 90, 180, 270, 45, 135, 225, 315)


def render_gray(page, zoom=ZOOM):
    """Page -> (image grise uint8 en coords d'AFFICHAGE, zoom)."""
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return img.copy(), zoom


def _rotate(tpl, angle):
    if angle == 0:
        return tpl
    if angle == 90:
        return np.rot90(tpl, 1)
    if angle == 180:
        return np.rot90(tpl, 2)
    if angle == 270:
        return np.rot90(tpl, 3)
    h, w = tpl.shape
    diag = int(math.ceil(math.hypot(h, w)))
    canvas = np.full((diag, diag), 255, np.uint8)
    oy, ox = (diag - h) // 2, (diag - w) // 2
    canvas[oy:oy + h, ox:ox + w] = tpl
    M = cv2.getRotationMatrix2D((diag / 2, diag / 2), angle, 1.0)
    return cv2.warpAffine(canvas, M, (diag, diag), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def _crop_template(img, bbox, zoom, pad_ratio=0.18):
    x0, y0, x1, y1 = bbox
    w = x1 - x0
    h = y1 - y0
    pad = max(w, h) * pad_ratio
    px0 = int(max(0, (x0 - pad) * zoom))
    py0 = int(max(0, (y0 - pad) * zoom))
    px1 = int(min(img.shape[1], (x1 + pad) * zoom))
    py1 = int(min(img.shape[0], (y1 + pad) * zoom))
    if px1 - px0 < 6 or py1 - py0 < 6:
        return None
    return img[py0:py1, px0:px1]


def _match_one(img, tpl, threshold, rotations):
    """Retourne la liste des detections (x_pixel, y_pixel, score) apres NMS multi-rotation."""
    ih, iw = img.shape
    dets = []
    for ang in rotations:
        rt = _rotate(tpl, ang)
        th, tw = rt.shape
        if th >= ih or tw >= iw or th < 6 or tw < 6:
            continue
        # ecart-type nul => matchTemplate NaN ; on saute les gabarits plats
        if rt.std() < 3:
            continue
        res = cv2.matchTemplate(img, rt, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for x, y in zip(xs, ys):
            dets.append((x + tw / 2.0, y + th / 2.0, float(res[y, x]), max(tw, th)))
    if not dets:
        return []
    # NMS glouton par proximite
    dets.sort(key=lambda d: -d[2])
    kept = []
    for x, y, s, sz in dets:
        r = sz * 0.55
        if all((x - kx) ** 2 + (y - ky) ** 2 > r * r for kx, ky, _ in kept):
            kept.append((x, y, s))
    return kept


def count_pdf_raster(pdf_path: Path, threshold=DEFAULT_THRESHOLD, rotations=ROTATIONS,
                     dpi=DPI, progress=False) -> dict:
    doc = fitz.open(pdf_path)
    all_rows = []
    overlays = []
    warnings = []
    thumbs = {}
    zoom_req = dpi / 72.0
    for pno, page in enumerate(doc):
        clusters, words = extract_page(page)
        templates, legend_rect = find_legend_templates(clusters, words, page.rect)
        if not templates:
            warnings.append(f"page {pno + 1} : pas de legende exploitable "
                            f"({len(clusters)} glyphes)")
            continue
        img, zoom = render_gray(page, zoom_req)
        lr = None
        if legend_rect:
            lr = (legend_rect.x0 * zoom, legend_rect.y0 * zoom,
                  legend_rect.x1 * zoom, legend_rect.y1 * zoom)
        marks = []
        for t in templates:
            tpl = _crop_template(img, t["cluster"]["bbox"], zoom)
            if tpl is None:
                all_rows.append(_row(pno, doc, t, 0))
                marks.append({"label": t["label"], "hits": []})
                continue
            if t["label"] not in thumbs:
                ok, buf = cv2.imencode(".png", tpl)
                if ok:
                    thumbs[t["label"]] = base64.b64encode(buf.tobytes()).decode("ascii")
            dets = _match_one(img, tpl, threshold, rotations)
            # retirer les detections dans la zone de legende
            if lr:
                dets = [d for d in dets if not (lr[0] <= d[0] <= lr[2] and lr[1] <= d[1] <= lr[3])]
            if progress:
                print(f"      [{t['label'][:30]:30s}] {len(dets)}", flush=True)
            all_rows.append(_row(pno, doc, t, len(dets)))
            marks.append({"label": t["label"], "hits": [(x / zoom, y / zoom) for x, y, _ in dets]})
        overlays.append({"page": pno, "marks": marks,
                         "legend_rect": list(legend_rect) if legend_rect else None})
    doc.close()
    return {"rows": all_rows, "overlays": overlays, "warnings": warnings, "thumbs": thumbs}


def _row(pno, doc, t, count):
    return {
        "zone": f"page {pno + 1}" if len(doc) > 1 else "",
        "display": t["label"],
        "label": t["label"],
        "layer": t["cluster"]["layer"] or "-",
        "count": count,
        "qty_declared": t["qty_declared"],
    }
