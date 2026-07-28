"""Compare plusieurs methodes pour retrouver les objets de legende dans les PDF.

Methodes testees par paire resolue DWG/PDF:
  - dwg_vector_quota: prototypes DWG -> clusters vectoriels PDF, avec quotas DWG;
  - vector_segmentation_classification: segmentation vectorielle PDF puis
    classification par empreinte DWG;
  - raster_segmentation_classification: segmentation raster PDF puis
    classification par empreinte DWG;
  - pdf_legend_vector: gabarits de legende PDF -> clusters vectoriels PDF;
  - pdf_legend_raster: gabarits de legende PDF -> image raster du PDF.

Le but est de choisir objectivement la voie la plus controlable par dossier.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plan_takeoff"))

import cv2  # noqa: E402
import fitz  # noqa: E402
import numpy as np  # noqa: E402
import pdf_takeoff as pt  # noqa: E402
import pdf_raster as pr  # noqa: E402
from dwg_pdf_batch_match import DEFAULT_THRESHOLDS, score_result  # noqa: E402
from dwg_pdf_match import _assign, _build_prototypes, _pdf_clusters, _shape_features  # noqa: E402
from dwg_pdf_resolved_batch import resolve_pairs  # noqa: E402
from render_dwg import build_sheet  # noqa: E402


RASTER_THRESHOLDS = [0.62]
RASTER_ROTATIONS = (0, 90, 180, 270)
RASTER_MAX_TEMPLATES = 8
RASTER_MAX_HITS_PER_ROTATION = 3000
RASTER_MAX_COMPONENTS = 2500
SEGMENTATION_THRESHOLDS = [0.25, 0.35, 0.45, 0.55]
DEFAULT_METHODS = [
    "dwg_vector_quota",
    "vector_segmentation_classification",
    "raster_segmentation_classification",
    "pdf_legend_vector",
    "pdf_legend_raster",
]
FAST_METHODS = [
    "dwg_vector_quota",
    "vector_segmentation_classification",
    "raster_segmentation_classification",
    "pdf_legend_vector",
]


def method_score(dwg_total, match_total, warnings=0, over_quota=0):
    return (
        abs(int(match_total) - int(dwg_total)),
        int(over_quota),
        int(warnings),
        -int(match_total),
    )


def run_dwg_vector_from_context(sheet, prototypes, clusters, pdf_meta, thresholds, *, relaxed_ssi=True,
                                method="dwg_vector_quota"):
    candidates = []
    for threshold in thresholds:
        matches, counts, all_candidates, _match_clusters, quota_report = _assign(
            prototypes, clusters, threshold, relaxed_ssi=relaxed_ssi
        )
        data = {
            "dwg": {"total": len(sheet["symbols"])},
            "match": {
                "total": len(matches),
                "by_label": dict(counts),
                "candidate_edges": len(all_candidates),
                "quota": quota_report,
            },
        }
        candidates.append((score_result(data), threshold, data))
    _score, best_threshold, best = sorted(candidates, key=lambda item: item[0])[0]
    over = best["match"]["quota"].get("over_quota_labels") or {}
    return {
        "method": method,
        "dwg_total": len(sheet["symbols"]),
        "match_total": best["match"]["total"],
        "delta": best["match"]["total"] - len(sheet["symbols"]),
        "threshold": best_threshold,
        "templates": pdf_meta["templates"],
        "candidate_clusters": len(clusters),
        "warnings": 0,
        "over_quota": len(over),
        "details": {
            "dwg_by_label": best.get("dwg", {}),
            "match_by_label": best["match"].get("by_label", {}),
            "quota": best["match"].get("quota", {}),
        },
    }


def run_dwg_vector(dwg: Path, pdf: Path, thresholds):
    sheet = build_sheet(dwg, pdf)
    prototypes = _build_prototypes(sheet)
    clusters, pdf_meta = _pdf_clusters(pdf)
    return run_dwg_vector_from_context(sheet, prototypes, clusters, pdf_meta, thresholds)


def run_vector_segmentation_classification_from_context(sheet, prototypes, clusters, pdf_meta, thresholds):
    """Segmente les composants vectoriels PDF puis les classifie par prototypes DWG.

    C'est proche de la voie DWG vectorielle, mais sans fusion relaxee SSI:
    elle mesure la qualite brute de la segmentation PDF avant enrichissement.
    """
    result = run_dwg_vector_from_context(
        sheet,
        prototypes,
        clusters,
        pdf_meta,
        thresholds,
        relaxed_ssi=False,
        method="vector_segmentation_classification",
    )
    result["details"]["segmentation"] = "pdf_vector_clusters"
    result["details"]["classifier"] = "nearest_dwg_shape_signature_with_label_quota"
    return result


def run_vector_segmentation_classification(dwg: Path, pdf: Path, thresholds):
    sheet = build_sheet(dwg, pdf)
    prototypes = _build_prototypes(sheet)
    clusters, pdf_meta = _pdf_clusters(pdf)
    return run_vector_segmentation_classification_from_context(sheet, prototypes, clusters, pdf_meta, thresholds)


def _raster_components(pdf: Path, dpi=60, max_components=RASTER_MAX_COMPONENTS):
    doc = fitz.open(pdf)
    if doc.page_count == 0:
        doc.close()
        return [], {"warnings": ["pdf vide"], "legend_rect": None}
    page = doc[0]
    zoom = dpi / 72.0
    clusters, words = pt.extract_page(page)
    _templates, legend_rect = pt.find_legend_templates(clusters, words, page.rect)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    doc.close()

    blur = cv2.GaussianBlur(img, (3, 3), 0)
    _thr, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    binary = cv2.dilate(binary, kernel, iterations=1)
    contours, _hier = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out = []
    warnings = []
    filtered = []
    for idx, contour in enumerate(contours):
        x, y, w, h = cv2.boundingRect(contour)
        if w < 3 or h < 3:
            continue
        bbox = [x / zoom, y / zoom, (x + w) / zoom, (y + h) / zoom]
        diag = math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])
        area = cv2.contourArea(contour)
        if diag < 1.0 or diag > 80.0 or area < 4:
            continue
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        if legend_rect and legend_rect.contains(fitz.Point(cx, cy)):
            continue
        filtered.append((idx, contour, bbox, cx, cy, area))
    filtered.sort(key=lambda item: -item[5])
    if max_components and len(filtered) > max_components:
        warnings.append(f"segmentation raster bornee a {max_components}/{len(filtered)} composants")
        filtered = filtered[:max_components]

    for idx, contour, bbox, cx, cy, _area in filtered:
        pts = [(float(p[0][0]) / zoom, float(p[0][1]) / zoom) for p in contour]
        feat = _shape_features(pts, Counter({"raster": len(pts)}))
        if not feat:
            continue
        out.append({
            "id": f"rc{idx + 1}",
            "bbox": bbox,
            "center": [cx, cy],
            "layer": "raster_component",
            "ops": (("raster", len(pts)),),
            "n_paths": 1,
            "feature": feat,
        })
    if not out:
        warnings.append("aucun composant raster exploitable")
    return out, {"warnings": warnings, "legend_rect": list(legend_rect) if legend_rect else None}


def run_raster_segmentation_classification_from_context(sheet, prototypes, pdf: Path, thresholds, dpi=60):
    components, meta = _raster_components(pdf, dpi=dpi)
    candidates = []
    for threshold in thresholds:
        matches, counts, all_candidates, _match_clusters, quota_report = _assign(
            prototypes, components, threshold, relaxed_ssi=False
        )
        data = {
            "dwg": {"total": len(sheet["symbols"])},
            "match": {
                "total": len(matches),
                "by_label": dict(counts),
                "candidate_edges": len(all_candidates),
                "quota": quota_report,
            },
        }
        candidates.append((score_result(data), threshold, data))
    _score, best_threshold, best = sorted(candidates, key=lambda item: item[0])[0]
    over = best["match"]["quota"].get("over_quota_labels") or {}
    return {
        "method": "raster_segmentation_classification",
        "dwg_total": len(sheet["symbols"]),
        "match_total": best["match"]["total"],
        "delta": best["match"]["total"] - len(sheet["symbols"]),
        "threshold": best_threshold,
        "templates": "",
        "candidate_clusters": len(components),
        "warnings": len(meta.get("warnings") or []),
        "over_quota": len(over),
        "details": {
            "segmentation": f"raster_connected_components_{dpi}dpi",
            "classifier": "nearest_dwg_shape_signature_with_label_quota",
            "warnings": meta.get("warnings") or [],
            "match_by_label": best["match"].get("by_label", {}),
            "quota": best["match"].get("quota", {}),
        },
    }


def run_raster_segmentation_classification(dwg: Path, pdf: Path, thresholds, dpi=60):
    sheet = build_sheet(dwg, pdf)
    prototypes = _build_prototypes(sheet)
    return run_raster_segmentation_classification_from_context(sheet, prototypes, pdf, thresholds, dpi=dpi)


def run_pdf_vector(pdf: Path):
    res = pt.count_pdf(pdf)
    total = sum(int(row.get("count") or 0) for row in res.get("rows", []))
    templates = len(res.get("rows", []))
    warnings = len(res.get("warnings") or [])
    return {
        "method": "pdf_legend_vector",
        "match_total": total,
        "threshold": "",
        "templates": templates,
        "candidate_clusters": "",
        "warnings": warnings,
        "over_quota": "",
        "details": {
            "rows": res.get("rows", []),
            "warnings": res.get("warnings", []),
        },
    }


def run_pdf_raster(pdf: Path, thresholds, dpi=60, max_templates=RASTER_MAX_TEMPLATES):
    candidates = []
    for threshold in thresholds:
        res = pr.count_pdf_raster(
            pdf,
            threshold=threshold,
            rotations=RASTER_ROTATIONS,
            dpi=dpi,
            max_templates=max_templates,
            max_hits_per_rotation=RASTER_MAX_HITS_PER_ROTATION,
        )
        total = sum(int(row.get("count") or 0) for row in res.get("rows", []))
        candidates.append((threshold, total, res))
    # La comparaison au DWG se fait dans run_pair, ici on retourne tous les seuils.
    return candidates


def run_pair(pair, thresholds, raster_thresholds, raster_dpi=60, methods=None):
    dwg, pdf = pair["dwg"], pair["pdf"]
    methods = set(methods or DEFAULT_METHODS)
    def timed(name, fn):
        start = time.monotonic()
        result = fn()
        result["duration_sec"] = round(time.monotonic() - start, 2)
        print(f"    {name}: {result['duration_sec']}s", flush=True)
        return result

    print("  prepare DWG/PDF context", flush=True)
    start_context = time.monotonic()
    sheet = build_sheet(dwg, pdf)
    prototypes = _build_prototypes(sheet)
    clusters, pdf_meta = _pdf_clusters(pdf)
    context_sec = round(time.monotonic() - start_context, 2)
    print(f"    context: {context_sec}s", flush=True)

    results = []
    dwg_total = len(sheet["symbols"])

    if "dwg_vector_quota" in methods:
        print("  method dwg_vector_quota", flush=True)
        vector_dwg = timed(
            "dwg_vector_quota",
            lambda: run_dwg_vector_from_context(sheet, prototypes, clusters, pdf_meta, thresholds),
        )
        dwg_total = int(vector_dwg["dwg_total"])
        results.append(vector_dwg)

    if "vector_segmentation_classification" in methods:
      try:
        print("  method vector_segmentation_classification", flush=True)
        results.append(timed(
            "vector_segmentation_classification",
            lambda: run_vector_segmentation_classification_from_context(sheet, prototypes, clusters, pdf_meta, thresholds),
        ))
      except Exception as exc:
        results.append({
            "method": "vector_segmentation_classification",
            "dwg_total": dwg_total,
            "match_total": 0,
            "delta": -dwg_total,
            "threshold": "",
            "templates": 0,
            "candidate_clusters": "",
            "warnings": 1,
            "over_quota": "",
            "details": {"error": f"{type(exc).__name__}: {exc}"},
        })

    if "raster_segmentation_classification" in methods:
      try:
        print("  method raster_segmentation_classification", flush=True)
        results.append(timed(
            "raster_segmentation_classification",
            lambda: run_raster_segmentation_classification_from_context(
                sheet, prototypes, pdf, SEGMENTATION_THRESHOLDS, dpi=raster_dpi
            ),
        ))
      except Exception as exc:
        results.append({
            "method": "raster_segmentation_classification",
            "dwg_total": dwg_total,
            "match_total": 0,
            "delta": -dwg_total,
            "threshold": "",
            "templates": 0,
            "candidate_clusters": "",
            "warnings": 1,
            "over_quota": "",
            "details": {"error": f"{type(exc).__name__}: {exc}"},
        })

    if "pdf_legend_vector" in methods:
      try:
        print("  method pdf_legend_vector", flush=True)
        vector_pdf = timed("pdf_legend_vector", lambda: run_pdf_vector(pdf))
        vector_pdf["dwg_total"] = dwg_total
        vector_pdf["delta"] = vector_pdf["match_total"] - dwg_total
        results.append(vector_pdf)
      except Exception as exc:
        results.append({
            "method": "pdf_legend_vector",
            "dwg_total": dwg_total,
            "match_total": 0,
            "delta": -dwg_total,
            "threshold": "",
            "templates": 0,
            "candidate_clusters": "",
            "warnings": 1,
            "over_quota": "",
            "details": {"error": f"{type(exc).__name__}: {exc}"},
        })

    if "pdf_legend_raster" in methods:
      try:
        print("  method pdf_legend_raster", flush=True)
        start = time.monotonic()
        raster_runs = run_pdf_raster(pdf, raster_thresholds, dpi=raster_dpi)
        raster_duration = round(time.monotonic() - start, 2)
        for threshold, total, res in raster_runs:
            results.append({
                "method": "pdf_legend_raster",
                "dwg_total": dwg_total,
                "match_total": total,
                "delta": total - dwg_total,
                "threshold": threshold,
                "templates": len(res.get("rows", [])),
                "candidate_clusters": "",
                "warnings": len(res.get("warnings") or []),
                "over_quota": "",
                "duration_sec": raster_duration,
                "details": {
                    "rows": res.get("rows", []),
                    "warnings": res.get("warnings", []),
                    "bounded": {
                        "max_templates": RASTER_MAX_TEMPLATES,
                        "max_hits_per_rotation": RASTER_MAX_HITS_PER_ROTATION,
                    },
                },
            })
        print(f"    pdf_legend_raster: {raster_duration}s", flush=True)
      except Exception as exc:
        results.append({
            "method": "pdf_legend_raster",
            "dwg_total": dwg_total,
            "match_total": 0,
            "delta": -dwg_total,
            "threshold": "",
            "templates": 0,
            "candidate_clusters": "",
            "warnings": 1,
            "over_quota": "",
            "details": {"error": f"{type(exc).__name__}: {exc}"},
        })

    if not results:
        raise ValueError("aucune methode active")

    for result in results:
        result["score_tuple"] = method_score(
            dwg_total,
            result["match_total"],
            warnings=result.get("warnings") or 0,
            over_quota=result.get("over_quota") or 0,
        )
    best = sorted(results, key=lambda row: row["score_tuple"])[0]
    return results, best


def run_lab(folder: Path, out_dir: Path, thresholds, raster_thresholds, min_score=30, raster_dpi=60,
            limit=0, methods=None, include_pdf_regex=None, exclude_pdf_regex=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs, unresolved = resolve_pairs(folder, min_score=min_score)
    include_re = re.compile(include_pdf_regex, re.IGNORECASE) if include_pdf_regex else None
    exclude_re = re.compile(exclude_pdf_regex, re.IGNORECASE) if exclude_pdf_regex else None
    if include_re or exclude_re:
        filtered = []
        for pair in pairs:
            pdf_text = str(pair["pdf"])
            if include_re and not include_re.search(pdf_text):
                continue
            if exclude_re and exclude_re.search(pdf_text):
                continue
            filtered.append(pair)
        pairs = filtered
    if limit and limit > 0:
        pairs = pairs[:limit]
    rows = []
    details = {
        "schema": "dwg_pdf_method_lab_v1",
        "folder": str(folder),
        "methods": methods or DEFAULT_METHODS,
        "filters": {
            "include_pdf_regex": include_pdf_regex or "",
            "exclude_pdf_regex": exclude_pdf_regex or "",
            "limit": limit or 0,
        },
        "pairs": [],
        "unresolved": unresolved,
        "errors": [],
    }
    for index, pair in enumerate(pairs, 1):
        print(f"[{index}/{len(pairs)}] {pair['pdf'].relative_to(folder)}", flush=True)
        try:
            results, best = run_pair(pair, thresholds, raster_thresholds, raster_dpi=raster_dpi, methods=methods)
            details["pairs"].append({
                "pdf": str(pair["pdf"]),
                "dwg": str(pair["dwg"]),
                "pair_score": pair["score"],
                "pair_reasons": pair["reasons"],
                "results": results,
                "best_method": best["method"],
                "best_threshold": best.get("threshold", ""),
            })
            for result in results:
                rows.append({
                    "pdf": str(pair["pdf"]),
                    "dwg": str(pair["dwg"]),
                    "pair_score": pair["score"],
                    "pair_reasons": json.dumps(pair["reasons"], ensure_ascii=False),
                    "method": result["method"],
                    "threshold": result.get("threshold", ""),
                    "dwg_total": result.get("dwg_total", ""),
                    "match_total": result.get("match_total", ""),
                    "delta": result.get("delta", ""),
                    "templates": result.get("templates", ""),
                    "candidate_clusters": result.get("candidate_clusters", ""),
                    "warnings": result.get("warnings", ""),
                    "over_quota": result.get("over_quota", ""),
                    "duration_sec": result.get("duration_sec", ""),
                    "is_best": result is best,
                })
            print(
                f"  best={best['method']} th={best.get('threshold', '')} "
                f"dwg={best['dwg_total']} match={best['match_total']} delta={best['delta']}",
                flush=True,
            )
        except Exception as exc:
            details["errors"].append({
                "pdf": str(pair["pdf"]),
                "dwg": str(pair["dwg"]),
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  ERROR {type(exc).__name__}: {exc}", flush=True)

    write_outputs(out_dir, rows, details)
    return rows, details


def write_outputs(out_dir: Path, rows, details):
    csv_path = out_dir / "method_lab_summary.csv"
    fields = [
        "pdf", "dwg", "pair_score", "pair_reasons", "method", "threshold",
        "dwg_total", "match_total", "delta", "templates", "candidate_clusters",
        "warnings", "over_quota", "duration_sec", "is_best",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path = out_dir / "method_lab_details.json"
    json_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")

    best_rows = [row for row in rows if str(row.get("is_best")).lower() == "true"]
    method_counts = {}
    for row in best_rows:
        method_counts[row["method"]] = method_counts.get(row["method"], 0) + 1
    lines = [
        "# Method lab summary",
        "",
        f"- Paires resolues: {len(details['pairs'])}.",
        f"- Non resolus: {len(details['unresolved'])}.",
        f"- Erreurs: {len(details['errors'])}.",
        f"- Meilleures methodes: {json.dumps(method_counts, ensure_ascii=False)}.",
        "",
        "| PDF | DWG | meilleure methode | seuil | DWG | match | delta |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for pair in details["pairs"]:
        best = next(r for r in pair["results"] if r["method"] == pair["best_method"]
                    and str(r.get("threshold", "")) == str(pair.get("best_threshold", "")))
        lines.append(
            f"| {Path(pair['pdf']).name} | {Path(pair['dwg']).name} | "
            f"{pair['best_method']} | {pair.get('best_threshold', '')} | "
            f"{best['dwg_total']} | {best['match_total']} | {best['delta']} |"
        )
    if details["unresolved"]:
        lines += ["", "## Non resolus", ""]
        for item in details["unresolved"]:
            lines.append(f"- {item['pdf']} (best={item['best_score']} {item['best_dwg']})")
    if details["errors"]:
        lines += ["", "## Erreurs", ""]
        for item in details["errors"]:
            lines.append(f"- {item['pdf']}: {item['error']}")
    md_path = out_dir / "method_lab_summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(f"MD: {md_path}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--thresholds", default=",".join(str(x) for x in DEFAULT_THRESHOLDS))
    parser.add_argument("--raster-thresholds", default=",".join(str(x) for x in RASTER_THRESHOLDS))
    parser.add_argument("--raster-dpi", type=int, default=60)
    parser.add_argument("--min-score", type=int, default=30)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--methods", default="all",
                        help="all, fast, ou liste separee par virgules")
    parser.add_argument("--include-pdf-regex", default="",
                        help="Filtre optionnel sur le chemin PDF")
    parser.add_argument("--exclude-pdf-regex", default="",
                        help="Exclusion optionnelle sur le chemin PDF")
    args = parser.parse_args(argv)
    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    raster_thresholds = [float(x.strip()) for x in args.raster_thresholds.split(",") if x.strip()]
    if args.methods == "all":
        methods = DEFAULT_METHODS
    elif args.methods == "fast":
        methods = FAST_METHODS
    else:
        methods = [x.strip() for x in args.methods.split(",") if x.strip()]
    run_lab(
        args.folder,
        args.out_dir,
        thresholds,
        raster_thresholds,
        min_score=args.min_score,
        raster_dpi=args.raster_dpi,
        limit=args.limit,
        methods=methods,
        include_pdf_regex=args.include_pdf_regex,
        exclude_pdf_regex=args.exclude_pdf_regex,
    )


if __name__ == "__main__":
    main()
