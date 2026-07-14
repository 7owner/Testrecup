"""Calibre UN SEUIL DE SCORE PAR CLASSE a partir des predictions d'un run.

Le detecteur sort des boites avec un score. Un seuil unique ne convient jamais a
toutes les classes (une classe sur-detecte a 0.3, une autre ne compte juste qu'a
0.7). Ce script cherche, pour chaque classe, le seuil qui donne le meilleur
comptage sur le split de validation.

Methode : par image et par classe, appariement glouton predictions<->verite par
IoU>=IOU_MATCH. On balaie les seuils, on compte TP/FP/FN -> F1 (metrique de
comptage robuste : penalise sur- ET sous-detection). Seuil retenu = meilleur F1,
depart. egalite tranchee par l'erreur de comptage |detecte - verite|.

Sort thresholds.json (classe -> seuil) + un rapport lisible.
ATTENTION : les comptes sont TUILE-level (le tuilage duplique ~x1.6). Les SEUILS,
eux, se transferent au plan entier ; les comptes non.

Usage :
  python calibrate_thresholds.py <run_outputs.zip|coco_instances_results.json> \
                                 [coco_colab.zip|val/annotations.json]
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

IOU_MATCH = 0.5
GRID = [round(0.05 * i, 2) for i in range(1, 19)]  # 0.05 .. 0.90


def _read(path, inner_hint):
    """Charge un JSON, qu'il soit nu ou dans un zip (on cherche inner_hint)."""
    p = Path(path)
    if p.suffix == ".zip":
        z = zipfile.ZipFile(p)
        name = next(n for n in z.namelist() if inner_hint in n and n.endswith(".json"))
        return json.loads(z.read(name).decode("utf-8"))
    return json.loads(p.read_text(encoding="utf-8"))


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def match(gts, preds):
    """Apparie preds (triees par score desc) aux gts par IoU. Retourne, pour chaque
    pred gardee, (score, est_TP)."""
    used = [False] * len(gts)
    out = []
    for pr in sorted(preds, key=lambda p: -p["score"]):
        best_j, best_iou = -1, IOU_MATCH
        for j, g in enumerate(gts):
            if used[j]:
                continue
            v = iou(pr["bbox"], g["bbox"])
            if v >= best_iou:
                best_iou, best_j = v, j
        if best_j >= 0:
            used[best_j] = True
            out.append((pr["score"], True))
        else:
            out.append((pr["score"], False))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    preds_src = sys.argv[1]
    val_src = sys.argv[2] if len(sys.argv) > 2 else "colab/coco_colab.zip"

    preds = _read(preds_src, "coco_instances_results")
    val = _read(val_src, "val/annotations")
    names = {c["id"]: c["name"] for c in val["categories"]}

    # verite et predictions regroupees par (image, classe)
    gt = defaultdict(list)
    for a in val["annotations"]:
        gt[(a["image_id"], a["category_id"])].append(a)
    pr = defaultdict(list)
    for p in preds:
        pr[(p["image_id"], p["category_id"])].append(p)

    imgs = [im["id"] for im in val["images"]]
    truth = defaultdict(int)
    for (im, c), lst in gt.items():
        truth[c] += len(lst)

    # matched[c] = liste de (score, TP) sur toutes les images ; fn deja compte via truth
    matched = defaultdict(list)
    for c in names:
        for im in imgs:
            matched[c] += match(gt.get((im, c), []), pr.get((im, c), []))

    thresholds = {}
    rows = []
    for c in names:
        T = truth[c]
        if T == 0:
            thresholds[names[c]] = 0.5  # pas de verite val -> defaut prudent
            rows.append((names[c], T, None, None, None, None))
            continue
        best = None  # (f1, -abs_count_err, thr, det, tp)
        for thr in GRID:
            tp = sum(1 for s, ok in matched[c] if ok and s >= thr)
            det = sum(1 for s, _ in matched[c] if s >= thr)
            fp = det - tp
            fn = T - tp
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            key = (round(f1, 4), -abs(det - T))
            if best is None or key > best[0]:
                best = (key, thr, det, tp, f1)
        _, thr, det, tp, f1 = best
        thresholds[names[c]] = thr
        rows.append((names[c], T, thr, det, tp, f1))

    Path("thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=1), encoding="utf-8")

    rows.sort(key=lambda r: -(r[1] or 0))
    print(f"{'classe':<22}{'vérité':>7}{'seuil*':>8}{'compté':>8}{'TP':>6}{'F1':>7}")
    print("-" * 58)
    macro = []
    for nm, T, thr, det, tp, f1 in rows:
        if thr is None:
            print(f"{nm:<22}{T:>7}{'—':>8}{'(0 val)':>8}")
            continue
        macro.append(f1)
        print(f"{nm:<22}{T:>7}{thr:>8.2f}{det:>8}{tp:>6}{f1:>7.2f}")
    print("-" * 58)
    if macro:
        print(f"F1 macro (classes avec vérité val) : {sum(macro) / len(macro):.3f}")
    print("-> thresholds.json ecrit")


if __name__ == "__main__":
    main()
