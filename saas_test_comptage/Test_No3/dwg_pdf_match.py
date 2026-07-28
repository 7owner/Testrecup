"""Matching experimental DWG -> PDF par forme visible.

Ce script teste l'idee centrale du pivot DWG-first :
  DWG = source des objets/prototypes ; PDF = cible ou retrouver les occurrences.

Il ne s'appuie pas sur le calque pour decider. Le calque reste seulement dans les
sorties de diagnostic. La decision vient d'une signature de forme normalisee
calculee sur les primitives DWG et sur les clusters vectoriels PDF.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import io
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plan_takeoff"))

import fitz  # noqa: E402
import h5py  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import pdf_takeoff as pt  # noqa: E402
from render_dwg import _prims_bbox, _prims_to_svg_elems, build_sheet  # noqa: E402
from render_symbol_taxonomy import shape_signature  # noqa: E402

RADII_BINS = 24
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080",
           "#f032e6", "#469990", "#9a6324", "#800000", "#808000", "#000075"]


def _safe_name(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    return "".join(out).strip("_")[:120] or "match"


def _sample_prims(prims):
    pts = []
    ops = Counter()
    for prim in prims:
        kind = prim[0]
        ops[kind] += 1
        if kind == "l":
            (x0, y0), (x1, y1) = prim[1], prim[2]
            for i in range(9):
                t = i / 8.0
                pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        elif kind == "c":
            cx, cy = prim[1]
            r = float(prim[2])
            for i in range(32):
                a = 2 * math.pi * i / 32
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        elif kind == "a":
            cx, cy = prim[1]
            r, a0, a1 = float(prim[2]), float(prim[3]), float(prim[4])
            if a1 < a0:
                a1 += 2 * math.pi
            for i in range(17):
                a = a0 + (a1 - a0) * i / 16.0
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts, ops


def _cluster_points(cluster):
    pts = [(float(x), float(y)) for x, y in cluster.get("pts", [])]
    ops = Counter(dict(cluster.get("ops") or ()))
    return pts, ops


def _bbox_diag(bbox):
    return math.hypot(float(bbox[2]) - float(bbox[0]), float(bbox[3]) - float(bbox[1]))


def _bbox_center(bbox):
    return ((float(bbox[0]) + float(bbox[2])) / 2.0,
            (float(bbox[1]) + float(bbox[3])) / 2.0)


def _bbox_union(boxes):
    return [
        min(float(b[0]) for b in boxes),
        min(float(b[1]) for b in boxes),
        max(float(b[2]) for b in boxes),
        max(float(b[3]) for b in boxes),
    ]


def _expanded_intersects(a, b, pad):
    return not (
        float(a[2]) + pad < float(b[0])
        or float(b[2]) + pad < float(a[0])
        or float(a[3]) + pad < float(b[1])
        or float(b[3]) + pad < float(a[1])
    )


def _shape_features(points, ops=None):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    diag = math.hypot(w, h) or 1.0
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    radii = sorted(math.hypot(x - cx, y - cy) for x, y in points)
    rmax = radii[-1] or 1.0
    core = radii[:max(3, int(len(radii) * 0.6))]

    def q(vals, norm):
        return tuple(round((vals[min(int(k * len(vals) / RADII_BINS), len(vals) - 1)] / (norm or 1.0)) * 30) / 30
                     for k in range(RADII_BINS))

    # occupation grossiere 8x8, utile pour distinguer carre plein de formes ouvertes.
    cells = set()
    for x, y in points:
        gx = int(max(0, min(7, ((x - min(xs)) / (w or 1.0)) * 8)))
        gy = int(max(0, min(7, ((y - min(ys)) / (h or 1.0)) * 8)))
        cells.add((gx, gy))
    return {
        "ratio": w / (h or 1.0),
        "diag": diag,
        "radii": q(radii, rmax),
        "core": q(core, core[-1] or rmax),
        "cells": cells,
        "ops": ops or Counter(),
        "n_points": len(points),
    }


def _feature_distance(a, b):
    if not a or not b:
        return None
    radii = sum(abs(x - y) for x, y in zip(a["radii"], b["radii"])) / RADII_BINS
    core = sum(abs(x - y) for x, y in zip(a["core"], b["core"])) / RADII_BINS
    ar = math.log(max(a["ratio"], 1e-6))
    br = math.log(max(b["ratio"], 1e-6))
    ratio = min(abs(ar - br), 2.0) / 2.0
    inter = len(a["cells"] & b["cells"])
    union = len(a["cells"] | b["cells"]) or 1
    cells = 1.0 - inter / union

    # Penalite douce seulement: les exports PDF peuvent exploser une primitive DWG
    # en plusieurs chemins, donc les ops ne peuvent pas etre une condition dure.
    a_kinds = set(a["ops"])
    b_kinds = set(b["ops"])
    ops = 0.0 if a_kinds == b_kinds else 0.12
    return 0.45 * radii + 0.25 * core + 0.20 * ratio + 0.10 * cells + ops


def _is_ssi_context(prototypes):
    needles = (
        "SSI", "INCENDIE", "DETECTEUR", "DECLENCHEUR", "DESENFUM",
        "VOLET", "INDICATEUR", "DIFFUSEUR", "VENTOUSE", "NSA",
        "ALARME", "BMAL", "RELAIS",
    )
    for p in prototypes:
        text = f"{p.get('label', '')} {p.get('display', '')}".upper()
        if any(n in text for n in needles):
            return True
    return False


def _merge_clusters(clusters, cluster_ids, merged_id):
    parts = [c for c in clusters if c["id"] in cluster_ids]
    pts = []
    ops = Counter()
    paths = 0
    layers = []
    for c in parts:
        c_pts, c_ops = _cluster_points(c)
        pts.extend(c_pts)
        ops.update(c_ops)
        paths += int(c.get("n_paths") or 0)
        if c.get("layer"):
            layers.append(c["layer"])
    feat = _shape_features(pts, ops)
    bbox = _bbox_union([c["bbox"] for c in parts])
    cx, cy = _bbox_center(bbox)
    return {
        "id": merged_id,
        "bbox": bbox,
        "center": [cx, cy],
        "layer": " | ".join(sorted(set(layers)))[:200],
        "ops": tuple(sorted(ops.items())),
        "n_paths": paths,
        "feature": feat,
        "source_cluster_ids": list(cluster_ids),
        "generated": "relaxed_ssi_merge",
    }


def _relaxed_ssi_clusters(clusters, assigned_ids, max_diag=85.0, pad=5.0):
    """Fusionne de petits clusters PDF voisins pour les symboles SSI fragmentes.

    Le matching de base reste prioritaire. Ce passage ne fabrique que des
    candidats supplementaires, bornes en taille, et les quotas DWG evitent les
    sur-comptages.
    """
    base = [
        c for c in clusters
        if c["id"] not in assigned_ids
        and _bbox_diag(c["bbox"]) <= max_diag
        and int(c.get("n_paths") or 0) <= 10
    ]
    if len(base) < 2:
        return []

    parent = {c["id"]: c["id"] for c in base}
    by_id = {c["id"]: c for c in base}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(base):
        for b in base[i + 1:]:
            if not _expanded_intersects(a["bbox"], b["bbox"], pad):
                continue
            merged_bbox = _bbox_union([a["bbox"], b["bbox"]])
            if _bbox_diag(merged_bbox) <= max_diag:
                union(a["id"], b["id"])

    groups = defaultdict(list)
    for c in base:
        groups[find(c["id"])].append(c["id"])

    out = []
    seen = set()
    for ids in groups.values():
        ids = sorted(ids)
        if len(ids) < 2 or len(ids) > 5:
            continue
        bbox = _bbox_union([by_id[i]["bbox"] for i in ids])
        if _bbox_diag(bbox) > max_diag:
            continue
        key = tuple(ids)
        if key in seen:
            continue
        seen.add(key)
        out.append(_merge_clusters(base, ids, f"m{len(out) + 1:04d}"))
    return out


def _prototype_thumb(prototype, size=92):
    prims = prototype["prims"]
    bb = _prims_bbox(prims)
    if not bb:
        return f'<svg width="{size}" height="{size}"></svg>'
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
        f'xmlns="http://www.w3.org/2000/svg"><rect width="{size}" height="{size}" fill="#fff"/>'
        + "".join(elems) + "</svg>"
    )


def _prototype_png_and_binary(prototype, size=96):
    prims = prototype["prims"]
    bb = _prims_bbox(prims)
    rgb = Image.new("RGB", (size, size), "white")
    binary = Image.new("L", (size, size), 0)
    if not bb:
        buf = io.BytesIO()
        rgb.save(buf, format="PNG")
        return buf.getvalue(), np.array(binary, dtype=np.uint8)

    x0, y0, x1, y1 = bb
    spanx = max(x1 - x0, 1e-9)
    spany = max(y1 - y0, 1e-9)
    pad = size * 0.12
    scale = min((size - 2 * pad) / spanx, (size - 2 * pad) / spany)

    def tf(point):
        x, y = point
        return (pad + (x - x0) * scale, size - pad - (y - y0) * scale)

    draw_rgb = ImageDraw.Draw(rgb)
    draw_bin = ImageDraw.Draw(binary)

    def line(points, width=2):
        draw_rgb.line(points, fill=(17, 17, 17), width=width)
        draw_bin.line(points, fill=255, width=width)

    for prim in prims:
        if prim[0] == "l":
            line([tf(prim[1]), tf(prim[2])])
        elif prim[0] == "c":
            cx, cy = tf(prim[1])
            r = abs(float(prim[2]) * scale)
            box = [cx - r, cy - r, cx + r, cy + r]
            draw_rgb.ellipse(box, outline=(17, 17, 17), width=2)
            draw_bin.ellipse(box, outline=255, width=2)
        elif prim[0] == "a":
            cx, cy = tf(prim[1])
            r = abs(float(prim[2]) * scale)
            box = [cx - r, cy - r, cx + r, cy + r]
            a0 = math.degrees(-prim[4])
            a1 = math.degrees(-prim[3])
            draw_rgb.arc(box, start=a0, end=a1, fill=(17, 17, 17), width=2)
            draw_bin.arc(box, start=a0, end=a1, fill=255, width=2)

    buf = io.BytesIO()
    rgb.save(buf, format="PNG")
    return buf.getvalue(), np.array(binary, dtype=np.uint8)


def _build_prototypes(sheet, *, group_by="label"):
    buckets = {}
    for s in sheet["symbols"]:
        sig = shape_signature(s["prims"])
        name = s["label"] if group_by == "label" else s["display"]
        key = (name, sig)
        if key not in buckets:
            pts, ops = _sample_prims(s["prims"])
            buckets[key] = {
                "id": f"p{len(buckets) + 1}",
                "label": s["label"],
                "display": s["display"],
                "name": name,
                "shape_signature": sig,
                "layer_sample": s["layer"],
                "count_dwg": 0,
                "prims": s["prims"],
                "feature": _shape_features(pts, ops),
            }
        buckets[key]["count_dwg"] += 1
    return list(buckets.values())


def _pdf_clusters(pdf_path: Path):
    doc = fitz.open(pdf_path)
    page = doc[0]
    clusters, words = pt.extract_page(page)
    templates, legend_rect = pt.find_legend_templates(clusters, words, page.rect)
    out = []
    for idx, c in enumerate(clusters):
        cx = (c["bbox"][0] + c["bbox"][2]) / 2
        cy = (c["bbox"][1] + c["bbox"][3]) / 2
        if legend_rect and legend_rect.contains(fitz.Point(cx, cy)):
            continue
        pts, ops = _cluster_points(c)
        feat = _shape_features(pts, ops)
        if not feat:
            continue
        out.append({
            "id": f"c{idx + 1}",
            "bbox": c["bbox"],
            "center": [cx, cy],
            "layer": c["layer"],
            "ops": c["ops"],
            "n_paths": c["n_paths"],
            "feature": feat,
        })
    doc.close()
    return out, {"clusters_total": len(clusters), "templates": len(templates),
                 "legend_rect": list(legend_rect) if legend_rect else None}


def _candidate_edges(prototypes, clusters, threshold, match_pass="direct"):
    out = []
    for p in prototypes:
        for c in clusters:
            score = _feature_distance(p["feature"], c["feature"])
            if score is None or score > threshold:
                continue
            out.append({
                "prototype_id": p["id"],
                "cluster_id": c["id"],
                "score": score,
                "match_pass": match_pass,
            })
    return out


def _assign(prototypes, clusters, threshold, relaxed_ssi=True):
    proto_by_id = {p["id"]: p for p in prototypes}
    label_quota = Counter()
    proto_quota = {}
    for p in prototypes:
        count = int(p.get("count_dwg") or 0)
        proto_quota[p["id"]] = count
        label_quota[p["label"]] += count

    cluster_by_id = {c["id"]: c for c in clusters}
    all_clusters = list(clusters)
    all_candidates = _candidate_edges(prototypes, clusters, threshold, match_pass="direct")
    all_candidates.sort(key=lambda x: x["score"])
    assigned_clusters = set()
    consumed_source_clusters = set()
    matches = []

    def accept(cand, c, p):
        if c["id"] in assigned_clusters:
            return
        source_ids = list(c.get("source_cluster_ids") or [c["id"]])
        if any(sid in consumed_source_clusters for sid in source_ids):
            return
        if label_quota[p["label"]] <= 0:
            return
        if proto_quota[p["id"]] > 0:
            proto_quota[p["id"]] -= 1
        label_quota[p["label"]] -= 1
        assigned_clusters.add(c["id"])
        consumed_source_clusters.update(source_ids)
        matches.append({
            "prototype_id": p["id"],
            "label": p["label"],
            "display": p["display"],
            "score": round(cand["score"], 4),
            "cluster_id": c["id"],
            "source_cluster_ids": source_ids,
            "match_pass": cand.get("match_pass") or "direct",
            "quota_remaining": int(label_quota[p["label"]]),
            "prototype_quota_remaining": int(proto_quota[p["id"]]),
            "bbox": [round(v, 2) for v in c["bbox"]],
            "center": [round(v, 2) for v in c["center"]],
            "pdf_layer": c["layer"],
            "pdf_ops": c["ops"],
            "pdf_n_paths": c["n_paths"],
        })

    for cand in all_candidates:
        p = proto_by_id[cand["prototype_id"]]
        c = cluster_by_id[cand["cluster_id"]]
        accept(cand, c, p)

    if relaxed_ssi and _is_ssi_context(prototypes) and any(v > 0 for v in label_quota.values()):
        relaxed = _relaxed_ssi_clusters(clusters, consumed_source_clusters)
        if relaxed:
            relaxed_by_id = {c["id"]: c for c in relaxed}
            relaxed_threshold = min(threshold + 0.08, 0.43)
            relaxed_candidates = _candidate_edges(
                [p for p in prototypes if label_quota[p["label"]] > 0],
                relaxed,
                relaxed_threshold,
                match_pass="relaxed_ssi",
            )
            relaxed_candidates.sort(key=lambda x: x["score"])
            all_clusters.extend(relaxed)
            cluster_by_id.update(relaxed_by_id)
            all_candidates.extend(relaxed_candidates)
            for cand in relaxed_candidates:
                p = proto_by_id[cand["prototype_id"]]
                c = relaxed_by_id[cand["cluster_id"]]
                accept(cand, c, p)

    counts = Counter(m["label"] for m in matches)
    quota_report = {
        "by_label_remaining": dict(label_quota),
        "by_prototype_remaining": dict(proto_quota),
        "over_quota_labels": {
            label: counts[label] - sum(int(p.get("count_dwg") or 0) for p in prototypes if p["label"] == label)
            for label in counts
            if counts[label] > sum(int(p.get("count_dwg") or 0) for p in prototypes if p["label"] == label)
        },
    }
    return matches, counts, all_candidates, all_clusters, quota_report


def _dataset_rows(prototypes, clusters, matches, candidates):
    proto_by_id = {p["id"]: p for p in prototypes}
    cluster_by_id = {c["id"]: c for c in clusters}
    matched_ids = {m["cluster_id"] for m in matches}
    consumed_source_ids = {sid for m in matches for sid in (m.get("source_cluster_ids") or [m["cluster_id"]])}
    cand_by_cluster = defaultdict(list)
    for cand in candidates:
        cand_by_cluster[cand["cluster_id"]].append(cand)

    positives = []
    for m in matches:
        positives.append({
            "kind": "positive",
            "label": m["label"],
            "display": m["display"],
            "score": m["score"],
            "prototype_id": m.get("prototype_id", ""),
            "cluster_id": m["cluster_id"],
            "source_cluster_ids": m.get("source_cluster_ids") or [m["cluster_id"]],
            "match_pass": m.get("match_pass", "direct"),
            "quota_remaining": m.get("quota_remaining", ""),
            "bbox": m["bbox"],
            "pdf_layer": m["pdf_layer"],
        })

    negatives = []
    ambiguous = []
    for c in clusters:
        if c.get("generated") and c["id"] not in matched_ids:
            continue
        if c["id"] in matched_ids or c["id"] in consumed_source_ids:
            continue
        cands = sorted(cand_by_cluster.get(c["id"], []), key=lambda x: x["score"])
        if len(cands) >= 2 and cands[1]["score"] - cands[0]["score"] <= 0.03:
            labels = [proto_by_id[x["prototype_id"]]["label"] for x in cands[:4]]
            ambiguous.append({
                "kind": "ambiguous",
                "label": " | ".join(labels),
                "display": "",
                "score": round(cands[0]["score"], 4),
                "prototype_id": cands[0].get("prototype_id", ""),
                "cluster_id": c["id"],
                "source_cluster_ids": c.get("source_cluster_ids") or [c["id"]],
                "match_pass": cands[0].get("match_pass", ""),
                "quota_remaining": "",
                "bbox": [round(v, 2) for v in c["bbox"]],
                "pdf_layer": c["layer"],
            })
        else:
            negatives.append({
                "kind": "negative",
                "label": "",
                "display": "",
                "score": "",
                "prototype_id": "",
                "cluster_id": c["id"],
                "source_cluster_ids": c.get("source_cluster_ids") or [c["id"]],
                "match_pass": "",
                "quota_remaining": "",
                "bbox": [round(v, 2) for v in c["bbox"]],
                "pdf_layer": c["layer"],
            })
    return positives, negatives, ambiguous


def _write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({field: row.get(field, "") for field in fields})


def _png_bytes_dataset(group, name, data: bytes):
    group.create_dataset(name, data=np.frombuffer(data, dtype=np.uint8),
                         compression="gzip", compression_opts=4)


def _write_hdf5(
    path,
    pdf_path,
    data,
    prototypes,
    matches,
    clusters,
    positives,
    negatives,
    ambiguous,
    max_negative_crops=200,
):
    cluster_by_id = {c["id"]: c for c in clusters}
    match_cluster_ids = {m["cluster_id"] for m in matches}

    def crop_pdf(page, bbox, zoom=4.0, pad=4.0):
        rect = fitz.Rect(bbox) + (-pad, -pad, pad, pad)
        rect &= page.rect
        if rect.is_empty or rect.width <= 0.2 or rect.height <= 0.2:
            return b""
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect * ~page.rotation_matrix)
            if pix.width <= 0 or pix.height <= 0:
                return b""
            return pix.tobytes("png")
        except Exception:
            return b""

    with h5py.File(path, "w") as h5:
        h5.attrs["schema"] = "dwg_pdf_match_objects_v1"
        h5.attrs["pair_name"] = data["pair"]["name"]
        h5.attrs["dwg_path"] = data["pair"]["dwg"]
        h5.attrs["pdf_path"] = data["pair"]["pdf"]
        h5.attrs["threshold"] = float(data["threshold"])
        h5.attrs["dwg_total"] = int(data["dwg"]["total"])
        h5.attrs["match_total"] = int(data["match"]["total"])
        h5.attrs["legend_templates"] = int(data["pdf"]["legend_templates"])
        h5.attrs["max_negative_crops"] = int(max_negative_crops)
        h5.attrs["note"] = (
            "HDF5 contient les objets visualisables: prototypes DWG en PNG/binaire, "
            "crops PDF pour positifs/ambigus et echantillon borne de negatifs."
        )

        meta = h5.create_group("metadata")
        meta.attrs["dwg_by_label_json"] = json.dumps(data["dwg"]["by_label"], ensure_ascii=False)
        meta.attrs["match_by_label_json"] = json.dumps(data["match"]["by_label"], ensure_ascii=False)

        gp = h5.create_group("dwg_prototypes")
        for idx, prototype in enumerate(prototypes):
            g = gp.create_group(f"{idx:04d}")
            g.attrs["prototype_id"] = prototype["id"]
            g.attrs["label"] = prototype["label"]
            g.attrs["display"] = prototype["display"]
            g.attrs["count_dwg"] = int(prototype["count_dwg"])
            g.attrs["layer_sample"] = prototype["layer_sample"]
            g.attrs["shape_signature"] = prototype["shape_signature"]
            png, binary = _prototype_png_and_binary(prototype)
            _png_bytes_dataset(g, "thumb_png", png)
            g.create_dataset("binary_96", data=binary, compression="gzip", compression_opts=4)

        doc = fitz.open(pdf_path)
        page = doc[0]
        gm = h5.create_group("pdf_matches")
        for idx, match in enumerate(matches):
            g = gm.create_group(f"{idx:05d}")
            for key in ("label", "display", "prototype_id", "cluster_id", "match_pass", "pdf_layer"):
                g.attrs[key] = str(match.get(key, ""))
            g.attrs["score"] = float(match.get("score") or 0.0)
            g.attrs["quota_remaining"] = int(match.get("quota_remaining") or 0)
            g.attrs["prototype_quota_remaining"] = int(match.get("prototype_quota_remaining") or 0)
            g.attrs["source_cluster_ids"] = json.dumps(match.get("source_cluster_ids") or [])
            g.attrs["bbox"] = json.dumps(match.get("bbox") or [])
            g.attrs["center"] = json.dumps(match.get("center") or [])
            g.attrs["pdf_ops"] = json.dumps(match.get("pdf_ops") or [])
            crop = crop_pdf(page, match["bbox"])
            if crop:
                _png_bytes_dataset(g, "crop_png", crop)

        gc = h5.create_group("dataset_candidates")
        for kind, rows in (("positive", positives), ("ambiguous", ambiguous), ("negative", negatives)):
            kg = gc.create_group(kind)
            for idx, row in enumerate(rows):
                g = kg.create_group(f"{idx:05d}")
                for key in ("kind", "label", "display", "prototype_id", "cluster_id", "match_pass", "pdf_layer"):
                    g.attrs[key] = str(row.get(key, ""))
                score = row.get("score")
                g.attrs["score"] = float(score) if score not in ("", None) else -1.0
                quota = row.get("quota_remaining")
                g.attrs["quota_remaining"] = int(quota) if quota not in ("", None) else -1
                g.attrs["source_cluster_ids"] = json.dumps(row.get("source_cluster_ids") or [])
                g.attrs["bbox"] = json.dumps(row.get("bbox") or [])
                c = cluster_by_id.get(row.get("cluster_id"))
                if c:
                    g.attrs["matched"] = row.get("cluster_id") in match_cluster_ids
                    g.attrs["pdf_ops"] = json.dumps(c.get("ops") or [])
                    g.attrs["pdf_n_paths"] = int(c.get("n_paths") or 0)
                should_crop = kind != "negative" or idx < max_negative_crops
                g.attrs["crop_stored"] = bool(should_crop)
                bbox = row.get("bbox")
                if should_crop and bbox:
                    crop = crop_pdf(page, bbox)
                    if crop:
                        _png_bytes_dataset(g, "crop_png", crop)
        doc.close()


def validate_hdf5(path: Path):
    result = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "ok": False,
        "errors": [],
    }
    if not path.exists():
        result["errors"].append("missing_file")
        return result
    try:
        with h5py.File(path, "r") as h5:
            result["schema"] = h5.attrs.get("schema", "")
            result["pair_name"] = h5.attrs.get("pair_name", "")
            result["dwg_total_attr"] = int(h5.attrs.get("dwg_total", -1))
            result["match_total_attr"] = int(h5.attrs.get("match_total", -1))
            result["dwg_prototypes"] = len(h5.get("dwg_prototypes", {}))
            result["pdf_matches"] = len(h5.get("pdf_matches", {}))
            candidates = h5.get("dataset_candidates")
            for kind in ("positive", "ambiguous", "negative"):
                group = candidates.get(kind) if candidates else None
                result[f"{kind}_candidates"] = len(group) if group else 0
                result[f"{kind}_crops"] = (
                    sum(1 for item in group.values() if "crop_png" in item)
                    if group else 0
                )

            prototypes = h5.get("dwg_prototypes", {})
            result["prototype_thumbs"] = sum(1 for item in prototypes.values() if "thumb_png" in item)
            result["prototype_binaries"] = sum(1 for item in prototypes.values() if "binary_96" in item)
            result["pdf_match_crops"] = sum(
                1 for item in h5.get("pdf_matches", {}).values() if "crop_png" in item
            )

            required_groups = ["dwg_prototypes", "pdf_matches", "dataset_candidates"]
            for group_name in required_groups:
                if group_name not in h5:
                    result["errors"].append(f"missing_group:{group_name}")
            if result["dwg_prototypes"] <= 0:
                result["errors"].append("no_dwg_prototypes")
            if result["prototype_thumbs"] != result["dwg_prototypes"]:
                result["errors"].append("prototype_thumb_mismatch")
            if result["prototype_binaries"] != result["dwg_prototypes"]:
                result["errors"].append("prototype_binary_mismatch")
            if result["pdf_matches"] != result["match_total_attr"]:
                result["errors"].append("pdf_match_count_mismatch")
            result["ok"] = not result["errors"]
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    return result


def _overlay_svg(pdf_path, matches, legend_rect=None, dpi=100):
    doc = fitz.open(pdf_path)
    page = doc[0]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
    labels = sorted({m["label"] for m in matches})
    color = {label: PALETTE[i % len(PALETTE)] for i, label in enumerate(labels)}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pix.width}" height="{pix.height}">',
        f'<image href="data:image/png;base64,{b64}" width="{pix.width}" height="{pix.height}"/>',
    ]
    if legend_rect:
        x0, y0, x1, y1 = legend_rect
        parts.append(
            f'<rect x="{x0 * zoom:.1f}" y="{y0 * zoom:.1f}" width="{(x1 - x0) * zoom:.1f}" '
            f'height="{(y1 - y0) * zoom:.1f}" fill="none" stroke="#888" stroke-dasharray="6 5" '
            f'stroke-width="2"/>'
        )
    for m in matches:
        x0, y0, x1, y1 = m["bbox"]
        col = color[m["label"]]
        parts.append(
            f'<rect x="{x0 * zoom:.1f}" y="{y0 * zoom:.1f}" width="{(x1 - x0) * zoom:.1f}" '
            f'height="{(y1 - y0) * zoom:.1f}" fill="none" stroke="{col}" stroke-width="2.5">'
            f'<title>{html.escape(m["label"])} score={m["score"]}</title></rect>'
        )
    parts.append("</svg>")
    doc.close()
    return "".join(parts)


def _write_html(path, data, prototypes, matches):
    counts = Counter(m["label"] for m in matches)
    proto_rows = []
    for p in prototypes:
        proto_rows.append(
            "<tr>"
            f"<td>{_prototype_thumb(p)}</td>"
            f"<td>{html.escape(p['label'])}</td>"
            f"<td>{html.escape(p['display'])}</td>"
            f"<td>{p['count_dwg']}</td>"
            f"<td>{counts.get(p['label'], 0)}</td>"
            f"<td>{html.escape(p['layer_sample'])}</td>"
            "</tr>"
        )
    match_rows = []
    for m in matches[:500]:
        match_rows.append(
            "<tr>"
            f"<td>{html.escape(m['label'])}</td>"
            f"<td>{html.escape(m.get('match_pass') or '')}</td>"
            f"<td>{m['score']}</td>"
            f"<td>{html.escape(m['cluster_id'])}</td>"
            f"<td>{html.escape(str(m['bbox']))}</td>"
            f"<td>{html.escape(m.get('pdf_layer') or '')}</td>"
            f"<td>{html.escape(str(m.get('pdf_ops') or ''))}</td>"
            "</tr>"
        )
    path.write_text(
        """<!doctype html>
<meta charset="utf-8">
<title>DWG PDF match</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#172033;background:#f7f8fb}
section{background:#fff;border:1px solid #d8deea;border-radius:8px;padding:16px;margin:16px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #e5e9f2;padding:7px 8px;text-align:left;vertical-align:middle}
th{background:#f1f4f9}
.meta{color:#526070}
</style>
"""
        f"<h1>{html.escape(data['pair']['name'])}</h1>"
        f"<p class='meta'>threshold={data['threshold']} | clusters candidats={data['pdf']['candidate_clusters']}</p>"
        "<section><h2>Prototypes DWG vs matchs PDF</h2><table><thead><tr>"
        "<th>forme DWG</th><th>label</th><th>display</th><th>DWG</th><th>match PDF</th><th>layer exemple</th>"
        "</tr></thead><tbody>" + "".join(proto_rows) + "</tbody></table></section>"
        "<section><h2>Matchs</h2><table><thead><tr>"
        "<th>label</th><th>passe</th><th>score</th><th>cluster</th><th>bbox</th><th>layer PDF</th><th>ops PDF</th>"
        "</tr></thead><tbody>" + "".join(match_rows) + "</tbody></table></section>",
        encoding="utf-8",
    )


def run_match(dwg_path: Path, pdf_path: Path, out_dir: Path, threshold=0.19, max_negative_crops=200):
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet(dwg_path, pdf_path)
    prototypes = _build_prototypes(sheet)
    clusters, pdf_meta = _pdf_clusters(pdf_path)
    matches, counts, candidates, match_clusters, quota_report = _assign(prototypes, clusters, threshold)
    positives, negatives, ambiguous = _dataset_rows(prototypes, match_clusters, matches, candidates)
    dwg_counts = Counter(s["label"] for s in sheet["symbols"])
    name = _safe_name(pdf_path.stem)
    data = {
        "pair": {"name": pdf_path.stem, "dwg": str(dwg_path), "pdf": str(pdf_path)},
        "threshold": threshold,
        "dwg": {"total": len(sheet["symbols"]), "by_label": dict(dwg_counts),
                "prototype_count": len(prototypes)},
        "pdf": {"clusters_total": pdf_meta["clusters_total"],
                "candidate_clusters": len(clusters),
                "legend_templates": pdf_meta["templates"],
                "legend_rect": pdf_meta["legend_rect"]},
        "match": {"total": len(matches), "by_label": dict(counts),
                  "candidate_edges": len(candidates),
                  "positives": len(positives),
                  "negatives": len(negatives),
                  "ambiguous": len(ambiguous),
                  "quota": quota_report,
                  "by_pass": dict(Counter(m.get("match_pass", "direct") for m in matches))},
        "matches": matches,
        "prototypes": [
            {
                "id": p["id"],
                "label": p["label"],
                "display": p["display"],
                "count_dwg": p["count_dwg"],
                "layer_sample": p["layer_sample"],
                "shape_signature": p["shape_signature"],
            }
            for p in prototypes
        ],
    }
    json_path = out_dir / f"{name}.match.json"
    csv_path = out_dir / f"{name}.matches.csv"
    dataset_path = out_dir / f"{name}.dataset_candidates.csv"
    h5_path = out_dir / f"{name}.objects.h5"
    html_path = out_dir / f"{name}.match.html"
    overlay_path = out_dir / f"{name}.match_overlay.svg"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(csv_path, matches, [
        "label", "display", "prototype_id", "score", "match_pass", "cluster_id",
        "source_cluster_ids", "quota_remaining", "prototype_quota_remaining",
        "bbox", "center", "pdf_layer", "pdf_ops", "pdf_n_paths",
    ])
    _write_csv(dataset_path, positives + ambiguous + negatives, [
        "kind", "label", "display", "prototype_id", "score", "match_pass",
        "cluster_id", "source_cluster_ids", "quota_remaining", "bbox", "pdf_layer",
    ])
    _write_html(html_path, data, prototypes, matches)
    overlay_path.write_text(_overlay_svg(pdf_path, matches, pdf_meta["legend_rect"]), encoding="utf-8")
    _write_hdf5(
        h5_path,
        pdf_path,
        data,
        prototypes,
        matches,
        match_clusters,
        positives,
        negatives,
        ambiguous,
        max_negative_crops=max_negative_crops,
    )
    return data, json_path, csv_path, html_path, overlay_path, h5_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dwg", required=True, type=Path)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=HERE / "out" / "dwg_pdf_match")
    parser.add_argument("--threshold", type=float, default=0.19)
    parser.add_argument("--max-negative-crops", type=int, default=200)
    args = parser.parse_args(argv)
    data, json_path, csv_path, html_path, overlay_path, h5_path = run_match(
        args.dwg,
        args.pdf,
        args.out_dir,
        args.threshold,
        max_negative_crops=args.max_negative_crops,
    )
    print(f"DWG total: {data['dwg']['total']}")
    print(f"PDF candidate clusters: {data['pdf']['candidate_clusters']}")
    print(f"Matches: {data['match']['total']}")
    print("DWG -> PDF par label:")
    for label, n in sorted(data["dwg"]["by_label"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {label}: dwg={n} match={data['match']['by_label'].get(label, 0)}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"HTML: {html_path}")
    print(f"SVG:  {overlay_path}")
    print(f"HDF5: {h5_path}")
    validation = validate_hdf5(h5_path)
    print(f"HDF5 validation: {'OK' if validation['ok'] else 'KO'}")


if __name__ == "__main__":
    main()
