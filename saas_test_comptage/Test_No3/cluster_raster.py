"""Regroupement par APPARENCE en raster HD (auto-supervise, sans DWG, sans legende).

Chaque symbole du plan = une composante connexe rasterisee HD ; les copies d'un meme
symbole (bitmaps quasi identiques) sont regroupees par IoU rotation-invariant. Un groupe
= un type de symbole, que l'utilisateur nommera ensuite.

Points cles vs vectoriel : le rendu HD donne aux petits symboles (va-et-vient, allumage)
une vraie forme en pixels -> regroupables ; le vectoriel ne leur donnait que 2 points.
"""
from __future__ import annotations

import math
import sys
import collections
from pathlib import Path

import numpy as np
import cv2
import fitz

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plan_takeoff"))
import pdf_takeoff as pt  # noqa: E402

NORM = 32
DIAG_MIN_PT, DIAG_MAX_PT = 3.0, 90.0
IOU_MERGE = 0.60     # IoU min (meilleure rotation) pour fusionner deux composantes
COLOR_MERGE = 0.25   # distance couleur max (0..1) pour fusionner deux composantes
MATCH_LEGEND_IOU = 0.55  # IoU min pour qu'un groupe corresponde a un symbole de legende
                         # (fosse net mesure : vrais symboles >=0.62, texte-vectoriel <=0.48)
COLOR_MATCH = 0.30   # distance couleur max (0..1) groupe <-> symbole de legende
SAT_MIN = 60         # saturation (HSV, 0..255) en-dessous = trait NEUTRE (noir/gris anticrenele)
SIZE_RATIO_LO, SIZE_RATIO_HI = 0.6, 1.55  # une vraie copie a ~la meme taille que le glyphe
                         # de legende ; le texte-vectoriel qui matche par hasard derive (ratio 0.27 / 2.3 / 3.0)
# zoom adaptatif par element : plus l'element est petit, plus on zoome pour extraire
# couleur + contour ; on vise ~TARGET_PX sur le plus grand cote.
TARGET_PX = 110.0
ZOOM_HI_MIN, ZOOM_HI_MAX = 4.0, 34.0
MIN_GROUP = 3


def _color_dist(a, b):
    """Distance couleur robuste a l'anticrenelage, dans [0, 1]. On raisonne en HSV :
    un trait peu sature est NEUTRE (noir/gris = pareil, la clarte ne compte pas) ; deux traits
    satures se comparent par la TEINTE (bleu vs rouge). Neutre vs colore = distance max."""
    ha = cv2.cvtColor(np.asarray(a, np.uint8).reshape(1, 1, 3), cv2.COLOR_RGB2HSV)[0, 0]
    hb = cv2.cvtColor(np.asarray(b, np.uint8).reshape(1, 1, 3), cv2.COLOR_RGB2HSV)[0, 0]
    na, nb = int(ha[1]) < SAT_MIN, int(hb[1]) < SAT_MIN
    if na and nb:
        return 0.0
    if na != nb:
        return 1.0
    dh = abs(int(ha[0]) - int(hb[0]))
    dh = min(dh, 180 - dh)   # teinte circulaire (OpenCV H dans 0..180), ecart max 90
    return dh / 90.0


def _norm_bitmap(mask):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = mask[y0:y1 + 1, x0:x1 + 1].astype(np.uint8)
    h, w = crop.shape
    s = (NORM - 2) / max(h, w)
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((NORM, NORM), np.uint8)
    oy, ox = (NORM - nh) // 2, (NORM - nw) // 2
    out[oy:oy + nh, ox:ox + nw] = (small > 0)
    return out


def _rots(bm):
    r = [bm]
    for _ in range(3):
        r.append(np.rot90(r[-1]))
    return r


def _iou(a, b):
    inter = int(np.count_nonzero(a & b))
    if inter == 0:
        return 0.0
    return inter / int(np.count_nonzero(a | b))


def detect_components(pdf_path, dpi=200):
    """-> (components, rgb_img, zoom, legend_rect_pt, legend_protos). Chaque composante :
    {bbox_pt, cx, cy, bmaps(rotations), color, diag, npix, ar}. legend_protos = memes champs
    pour les glyphes-symboles de la COLONNE de gauche de la legende.

    Detection des composantes sur un rendu de base (dpi) ; couleur + contour de CHAQUE element
    sont extraits par un ZOOM adaptatif via la DISPLAY-LIST construite une seule fois (net pour
    les petits symboles, sans re-rendre le PDF a chaque appel)."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    clusters, words = pt.extract_page(page)
    templates, legend_rect = pt.find_legend_templates(clusters, words, page.rect)
    zoom = dpi / 72.0
    pixc = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    rgb = np.frombuffer(pixc.samples, dtype=np.uint8).reshape(pixc.height, pixc.width, pixc.n)[:, :, :3].copy()
    dl = page.get_displaylist()   # construite UNE fois -> decoupes zoomes rapides
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # EFFACER LE TEXTE avant seuillage : on blanchit chaque boite de mot (PyMuPDF donne
    # leur position exacte). Le texte est la 1re source de faux groupes -> on l'enleve a
    # la source plutot que de filtrer les composantes apres coup.
    for w in words:
        x0, y0, x1, y1 = int(w[0]*zoom), int(w[1]*zoom), int(w[2]*zoom), int(w[3]*zoom)
        gray[max(0, y0):y1+1, max(0, x0):x1+1] = 255
    _, binz = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binz = cv2.morphologyEx(binz, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    # boites de mots (px) : composante ENTIEREMENT dans un mot -> texte, ecarte
    wboxes = [(w[0] * zoom, w[1] * zoom, w[2] * zoom, w[3] * zoom) for w in words]

    def contained_in_word(x, y, w, h):
        for X0, Y0, X1, Y1 in wboxes:
            if X0 - 1 <= x and y >= Y0 - 1 and x + w <= X1 + 1 and y + h <= Y1 + 1:
                return True
        return False

    # limite droite de la COLONNE des symboles de la legende = debut des libelles
    sym_x1_pt = min((t["row"]["x0"] for t in templates), default=None)

    def sig(bbox_pt, mask_base):
        """ZOOM adaptatif sur l'element via la display-list (net meme pour les petits
        symboles) ; isole par le masque de la composante. -> (bmaps_contour, couleur_RGB)."""
        x0p, y0p, x1p, y1p = bbox_pt
        diag = math.hypot(x1p - x0p, y1p - y0p) or 1.0
        zhi = min(ZOOM_HI_MAX, max(ZOOM_HI_MIN, TARGET_PX / diag))
        pix = dl.get_pixmap(matrix=fitz.Matrix(zhi, zhi), clip=fitz.Rect(*bbox_pt), alpha=False)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        H, W = arr.shape[:2]
        if H < 2 or W < 2:
            return None
        m = cv2.resize(mask_base.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        white = (arr[..., 0] > 232) & (arr[..., 1] > 232) & (arr[..., 2] > 232)
        fg = m & ~white
        if int(fg.sum()) < 6:
            fg = m
        if int(fg.sum()) < 6:
            return None
        col = np.median(arr[fg], axis=0).astype(np.float32)
        bm = _norm_bitmap(fg.astype(np.uint8))
        if bm is None or bm.sum() < 4:
            return None
        return _rots(bm), col

    n, lab, stats, cent = cv2.connectedComponentsWithStats(binz, connectivity=8)
    comps = []
    legend_protos = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        d_pt = math.hypot(w, h) / zoom
        if d_pt < DIAG_MIN_PT or d_pt > DIAG_MAX_PT or area < 6:
            continue
        cx, cy = cent[i]
        cx_pt, cy_pt = cx / zoom, cy / zoom
        mask = (lab[y:y + h, x:x + w] == i)
        bbox_pt = [x / zoom, y / zoom, (x + w) / zoom, (y + h) / zoom]
        s = sig(bbox_pt, mask)
        if s is None:
            continue
        bmaps, color = s
        rec = {"bbox_pt": bbox_pt, "cx": cx_pt, "cy": cy_pt, "bmaps": bmaps,
               "color": color, "diag": d_pt, "npix": int(bmaps[0].sum()),
               "ar": round(math.log(max(w, 1) / max(h, 1)), 1)}
        in_legend = legend_rect is not None and legend_rect.contains(fitz.Point(cx_pt, cy_pt))
        if in_legend:
            # glyphe dans la COLONNE de symboles (a gauche des libelles) -> prototype
            if sym_x1_pt is not None and cx_pt < sym_x1_pt:
                legend_protos.append(rec)
            continue  # jamais compte comme instance du plan
        if contained_in_word(x, y, w, h):
            continue
        comps.append(rec)
    doc.close()
    return comps, rgb, zoom, (list(legend_rect) if legend_rect else None), legend_protos


def cluster(comps):
    """Clustering par REPRESENTANT (leader), PAS union-find : chaque composante rejoint le
    groupe dont le REPRESENTANT lui ressemble le plus (IoU>=seuil), sinon nouveau groupe.
    Pas de transitivite -> pas de chainage A~B~C ni de mega-groupe. On traite de la + grande
    composante a la + petite pour que les symboles nets amorcent les groupes."""
    order = sorted(range(len(comps)), key=lambda i: -comps[i]["npix"])
    reps = []          # (bmaps, color) de chaque representant
    assign = {}
    for i in order:
        bi = comps[i]["bmaps"][0]
        ci = comps[i]["color"]
        best_r, best_iou = -1, IOU_MERGE
        for ri, (rbm, rcol) in enumerate(reps):
            if _color_dist(ci, rcol) > COLOR_MERGE:   # couleur differente -> pas le meme symbole
                continue
            iou = max(_iou(bi, pr) for pr in rbm)
            if iou > best_iou:
                best_iou, best_r = iou, ri
        if best_r < 0:
            reps.append((comps[i]["bmaps"], ci))
            assign[i] = len(reps) - 1
        else:
            assign[i] = best_r
    groups = collections.defaultdict(list)
    for i, g in assign.items():
        groups[g].append(i)
    return sorted(groups.values(), key=len, reverse=True)


def best_legend_match(rep, legend_protos):
    """Meilleure correspondance d'un representant de groupe (rec complet) avec un symbole de
    legende : COULEUR proche ET IoU de forme ET taille absolue coherente (ratio de diagonale
    dans [LO, HI]). -> (proto_idx, iou) ; proto_idx=-1 si aucun au-dessus des seuils."""
    rep_bmaps = rep["bmaps"]; rd = rep.get("diag", 0.0); rc = rep["color"]
    best_i, best_iou = -1, MATCH_LEGEND_IOU
    for pi, proto in enumerate(legend_protos):
        pd = proto.get("diag", 0.0)
        if pd <= 0 or not (SIZE_RATIO_LO <= rd / pd <= SIZE_RATIO_HI):
            continue
        if _color_dist(rc, proto["color"]) > COLOR_MATCH:  # couleur differente -> pas ce symbole
            continue
        iou = max(_iou(rb, pb) for rb in rep_bmaps for pb in proto["bmaps"])
        if iou > best_iou:
            best_iou, best_i = iou, pi
    return best_i, best_iou


TEXT_NEIGHBOR_FRAC = 0.6   # si >=60% des membres ont un voisin-texte -> groupe = texte-vectoriel


def _has_text_neighbor(i, comps):
    """Un caractere de texte a un autre caractere de MEME hauteur immediatement a gauche/droite
    (meme ligne de base). Les vrais symboles sont isoles ou en grille, pas en ligne serree."""
    b = comps[i]["bbox_pt"]; w = b[2] - b[0]; h = b[3] - b[1]; cy = (b[1] + b[3]) / 2
    for j, c in enumerate(comps):
        if j == i:
            continue
        cb = c["bbox_pt"]; ch = cb[3] - cb[1]; cyj = (cb[1] + cb[3]) / 2
        if abs(cyj - cy) > 0.5 * h or abs(ch - h) > 0.5 * h:
            continue
        if -2 < cb[0] - b[2] < 0.8 * w or -2 < b[0] - cb[2] < 0.8 * w:  # colle a droite/gauche
            return True
    return False


def group_is_text(g, comps):
    """Vrai si la majorite des membres du groupe sont alignes en ligne de texte."""
    if len(g) == 0:
        return False
    frac = sum(_has_text_neighbor(i, comps) for i in g) / len(g)
    return frac >= TEXT_NEIGHBOR_FRAC


if __name__ == "__main__":
    from PIL import Image, ImageDraw, ImageFont
    pdf = Path(sys.argv[1])
    comps, rgb, zoom, lr, protos = detect_components(pdf, dpi=200)
    groups = cluster(comps)
    # ne garder que les groupes qui matchent un symbole de la legende
    if protos:
        kept = []
        for g in groups:
            rep = max(g, key=lambda i: comps[i]["npix"])
            mi, iou = best_legend_match(comps[rep], protos)
            if mi >= 0:   # couleur + contour + taille correspondent a un symbole de legende
                kept.append(g)
        print(f"prototypes legende={len(protos)} | groupes gardes (match legende)={len(kept)}/{len(groups)}")
        groups = kept
    big = [g for g in groups if len(g) >= MIN_GROUP]
    singles = sum(1 for g in groups if len(g) == 1)
    print(f"composantes={len(comps)} | groupes>=3={len(big)} | singletons={singles}")
    print("tailles top20:", [len(g) for g in big[:20]])
    # planche : par groupe, jusqu'a 8 membres
    img = Image.fromarray(rgb)
    CELL = 84; PER = 8; LAB = 70; rows = big[:22]
    W = LAB + PER * CELL; H = len(rows) * CELL
    sheet = Image.new("RGB", (W, H), "white"); dr = ImageDraw.Draw(sheet)
    try: fb = ImageFont.truetype("arialbd.ttf", 13)
    except Exception: fb = ImageFont.load_default()
    for i, g in enumerate(rows):
        y = i * CELL; dr.rectangle([0, y, W, y + CELL], outline="#ddd")
        dr.text((6, y + 30), f"{len(g)}", fill="#111", font=fb)
        for j, idx in enumerate(g[:PER]):
            b = comps[idx]["bbox_pt"]; pad = 6
            x0 = max(0, int(b[0] * zoom) - pad); y0 = max(0, int(b[1] * zoom) - pad)
            x1 = min(img.width, int(b[2] * zoom) + pad); y1 = min(img.height, int(b[3] * zoom) + pad)
            cell = Image.new("RGB", (CELL, CELL), "white")
            if x1 > x0 and y1 > y0:
                c = img.crop((x0, y0, x1, y1)); c.thumbnail((CELL - 6, CELL - 6))
                cell.paste(c, ((CELL - c.width) // 2, (CELL - c.height) // 2))
            sheet.paste(cell, (LAB + j * CELL, y))
    out = ROOT / "Test_No3/out/cluster_groups_sheet.png"; sheet.save(out)
    print(f"-> {out}")
