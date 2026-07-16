"""Inference plan-level : PDF -> detections du modele sur le plan entier.

Chaine (aucun DWG, aucun detectron2 -- torch-CPU + torchvision + fitz seuls) :
  PDF --render--> image a l'echelle d'entrainement (plan a TARGET_W px de large)
      --tuilage 800/overlap 200--> tuiles
      --model.ts (TorchScript)--> boites/classes/scores par tuile
      --seuil par classe + drop bord de tuile--> detections propres
      --remise en coords plan + NMS inter-tuiles--> detections uniques
  -> [{cls, name, box(px plan), score}], comptes par classe.

L'echelle est CRUCIALE : le modele a appris les symboles quand le plan fait TARGET_W px
de large (symboles ~10 px). On rend donc le PDF au zoom = TARGET_W / largeur_du_plan, la
largeur du plan etant l'etendue des glyphes vectoriels (percentiles 2-98, pour ecarter le
cartouche). Valide le 2026-07-16 sur un plan CFO ROI RENE : detections metier-coherentes.

torchvision DOIT etre importe avant de charger model.ts (il enregistre torchvision::nms).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
import torchvision  # noqa: F401  -- enregistre torchvision::nms, requis par model.ts
from torchvision.ops import nms as tv_nms

import fitz

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))
from pdf_takeoff import extract_page  # noqa: E402

TARGET_W = 1800      # largeur du plan en px = echelle d'entrainement (render_dwg width=1800)
TILE = 800
OVERLAP = 200
STEP = TILE - OVERLAP
BORDER = 6           # px : on jette une detection dont la boite touche le bord INTERIEUR
                     # d'une tuile (symbole tronque) -- l'overlap la rattrape entiere ailleurs
NMS_IOU = 0.40       # NMS inter-tuiles, par classe
DEFAULT_THRESH = 0.30


def load_model(model_ts: Path):
    m = torch.jit.load(str(model_ts), map_location="cpu")
    m.eval()
    return m


def load_meta(meta_json: Path):
    d = json.loads(Path(meta_json).read_text(encoding="utf-8"))
    return d["classes"]


def load_thresholds(path: Path, names):
    """Seuil par classe (thresholds.json) ; DEFAULT_THRESH pour les classes absentes."""
    if path and Path(path).exists():
        t = json.loads(Path(path).read_text(encoding="utf-8"))
        return {n: float(t.get(n, DEFAULT_THRESH)) for n in names}
    return {n: DEFAULT_THRESH for n in names}


def render_plan(pdf_path, page_no=0, target_w=TARGET_W):
    """PDF -> (image RGB HxWx3, zoom, plan_bbox_px). L'image est la PAGE ENTIERE rendue au
    zoom qui met le PLAN a `target_w` px de large ; plan_bbox_px borne la zone plan (hors
    cartouche) en pixels."""
    doc = fitz.open(pdf_path)
    page = doc[page_no]
    clusters, _ = extract_page(page)
    if not clusters:
        doc.close()
        raise ValueError("aucun glyphe vectoriel : PDF scanne ou vide")
    xs0 = [c["bbox"][0] for c in clusters]; xs1 = [c["bbox"][2] for c in clusters]
    ys0 = [c["bbox"][1] for c in clusters]; ys1 = [c["bbox"][3] for c in clusters]
    px0, px1 = float(np.percentile(xs0, 2)), float(np.percentile(xs1, 98))
    py0, py1 = float(np.percentile(ys0, 2)), float(np.percentile(ys1, 98))
    zoom = target_w / max(px1 - px0, 1.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    doc.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    arr = arr[:, :, :3].copy()
    plan_bbox = (int(px0 * zoom), int(py0 * zoom), int(px1 * zoom), int(py1 * zoom))
    return arr, zoom, plan_bbox


def _tiles(plan_bbox, W, H):
    """Positions (tx, ty) des tuiles couvrant la zone plan, avec overlap. La derniere
    ligne/colonne est calee sur le bord pour ne rien laisser depasser."""
    x0, y0, x1, y1 = plan_bbox
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    xs = list(range(x0, max(x0 + 1, x1 - TILE), STEP)) or [x0]
    ys = list(range(y0, max(y0 + 1, y1 - TILE), STEP)) or [y0]
    if xs[-1] != x1 - TILE and x1 - TILE > x0:
        xs.append(x1 - TILE)
    if ys[-1] != y1 - TILE and y1 - TILE > y0:
        ys.append(y1 - TILE)
    return [(tx, ty) for ty in ys for tx in xs]


def _run_tile(model, tile_rgb):
    """tile RGB 800x800 -> (boxes[N,4], classes[N], scores[N]) numpy. Entree modele :
    BGR 0-255 CHW (la normalisation est faite DANS le modele)."""
    bgr = tile_rgb[:, :, ::-1].copy()
    t = torch.from_numpy(bgr).permute(2, 0, 1).float()
    with torch.no_grad():
        boxes, classes, _masks, scores, _sz = model(t)
    return boxes.numpy(), classes.numpy(), scores.numpy()


def infer(pdf_path, model_ts, meta_json, thresholds_json=None, page_no=0, progress=None):
    """PDF -> dict {detections:[{cls,name,box,score}], counts:{name:n}, image, zoom,
    plan_bbox, n_tiles}. `box` en pixels de l'image rendue."""
    names = load_meta(meta_json)
    thr = load_thresholds(thresholds_json, names)
    model = load_model(model_ts)
    arr, zoom, plan_bbox = render_plan(pdf_path, page_no)
    H, W = arr.shape[:2]
    positions = _tiles(plan_bbox, W, H)

    all_boxes, all_scores, all_cls = [], [], []
    for k, (tx, ty) in enumerate(positions):
        if progress:
            progress(k + 1, len(positions))
        tile = arr[ty:ty + TILE, tx:tx + TILE]
        if tile.shape[0] < TILE or tile.shape[1] < TILE:
            pad = np.full((TILE, TILE, 3), 255, np.uint8)
            pad[:tile.shape[0], :tile.shape[1]] = tile
            tile = pad
        boxes, classes, scores = _run_tile(model, tile)
        for (bx0, by0, bx1, by1), cl, s in zip(boxes, classes, scores):
            if s < thr[names[cl]]:
                continue
            # symbole tronque au bord interieur de la tuile -> jete (rattrape entier ailleurs
            # grace a l'overlap). On ne jette PAS au bord qui coincide avec le bord du plan.
            touch = (bx0 < BORDER or by0 < BORDER or bx1 > TILE - BORDER or by1 > TILE - BORDER)
            at_plan_edge = (tx <= plan_bbox[0] and bx0 < BORDER) or \
                           (ty <= plan_bbox[1] and by0 < BORDER) or \
                           (tx + TILE >= plan_bbox[2] and bx1 > TILE - BORDER) or \
                           (ty + TILE >= plan_bbox[3] and by1 > TILE - BORDER)
            if touch and not at_plan_edge:
                continue
            all_boxes.append([bx0 + tx, by0 + ty, bx1 + tx, by1 + ty])
            all_scores.append(float(s))
            all_cls.append(int(cl))

    dets = _nms_per_class(all_boxes, all_scores, all_cls)
    counts = {}
    out = []
    for box, score, cl in dets:
        nm = names[cl]
        counts[nm] = counts.get(nm, 0) + 1
        out.append({"cls": cl, "name": nm, "box": [round(v, 1) for v in box],
                    "score": round(score, 3)})
    return {"detections": out, "counts": counts, "image": arr, "zoom": zoom,
            "plan_bbox": plan_bbox, "n_tiles": len(positions)}


def _nms_per_class(boxes, scores, cls):
    """NMS inter-tuiles, classe par classe. -> [(box, score, cls)] gardees."""
    if not boxes:
        return []
    b = torch.tensor(boxes, dtype=torch.float32)
    s = torch.tensor(scores, dtype=torch.float32)
    c = np.array(cls)
    kept = []
    for cl in set(cls):
        idx = np.where(c == cl)[0]
        keep = tv_nms(b[idx], s[idx], NMS_IOU).numpy()
        for j in keep:
            i = idx[j]
            kept.append((boxes[i], scores[i], cl))
    return kept


if __name__ == "__main__":
    import time
    d4 = HERE / "resultat_fine_tunning" / "new_resultats4"
    model_ts = d4 / "model.ts"
    meta = d4 / "model_meta (1).json"
    thr = HERE / "thresholds.json"
    pdf = Path(sys.argv[1])
    t0 = time.time()
    res = infer(pdf, model_ts, meta, thr,
                progress=lambda k, n: print(f"  tuile {k}/{n}", end="\r", flush=True))
    print(f"\n{res['n_tiles']} tuiles, {len(res['detections'])} detections en {time.time()-t0:.0f}s\n")
    for nm, n in sorted(res["counts"].items(), key=lambda kv: -kv[1]):
        print(f"   {n:>4}  {nm}")
    if len(sys.argv) > 2:
        from PIL import Image, ImageDraw
        im = Image.fromarray(res["image"])
        dr = ImageDraw.Draw(im)
        for det in res["detections"]:
            x0, y0, x1, y1 = det["box"]
            dr.rectangle([x0, y0, x1, y1], outline=(230, 0, 0), width=2)
        im.save(sys.argv[2])
        print(f"\n-> {sys.argv[2]}")
