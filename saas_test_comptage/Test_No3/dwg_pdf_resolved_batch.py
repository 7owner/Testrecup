"""Batch DWG -> PDF avec appariement resolu par dossier.

Contrairement a `dwg_pdf_batch_match.py`, ce batch accepte les dossiers ou un
DWG d'etage sert a plusieurs PDF de lots differents. Chaque association PDF/DWG
est tracee dans un manifeste pour rester verifiable.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dwg_pdf_batch_match import DEFAULT_THRESHOLDS, score_result, write_hdf5_manifest, write_ssi_diagnostics  # noqa: E402
from dwg_pdf_match import _assign, _build_prototypes, _pdf_clusters, run_match, validate_hdf5  # noqa: E402
from render_dwg import build_sheet  # noqa: E402


BUILDINGS = ("AFRIQUE", "AMERIQUE", "EUROPE", "VERDUN", "BPCE", "TRIUM", "NORD", "SUD")
LEVEL_PATTERNS = [
    (re.compile(r"\bRDC\b"), "RDC"),
    (re.compile(r"\bRDJ\b"), "RDJ"),
    (re.compile(r"\bR\s*\+\s*([1-9])\b"), lambda m: f"R+{m.group(1)}"),
    (re.compile(r"\bN\s*([0-9])\b"), lambda m: f"N{m.group(1)}"),
    (re.compile(r"\bCOMBLES?\b"), "COMBLES"),
]


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper().replace("+", " + ")
    return re.sub(r"[^A-Z0-9+]+", " ", text)


def level_tokens(value):
    text = normalize(value)
    out = set()
    for pattern, token in LEVEL_PATTERNS:
        for match in pattern.finditer(text):
            out.add(token(match) if callable(token) else token)
    return out


def building_tokens(value):
    text = normalize(value)
    out = {token for token in BUILDINGS if token in text}
    if "AMERIQUE" in out:
        out.add("AMERICA")
    return out


def lot_tokens(value):
    text = normalize(value)
    return {token for token in ("CFO", "CFA", "SSI", "VDI", "ECL", "ECLAIRAGE", "CDC") if token in text}


def list_dwg(folder: Path):
    out = []
    for path in folder.rglob("*.dwg"):
        low_parts = {p.lower() for p in path.parts}
        if {"00-xref", "0-xref", "old"} & low_parts:
            continue
        out.append(path)
    return sorted(out, key=lambda p: str(p).lower())


def list_pdf(folder: Path):
    return sorted(folder.rglob("*.pdf"), key=lambda p: str(p).lower())


def score_pair(pdf: Path, dwg: Path):
    pdf_text = normalize(pdf.relative_to(pdf.parents[0]))
    dwg_text = normalize(dwg.name)
    score = 0
    reasons = []

    if pdf.with_suffix(".dwg") == dwg:
        score += 100
        reasons.append("exact_stem")

    pb, db = building_tokens(pdf_text), building_tokens(dwg_text)
    common_building = pb & db
    if common_building:
        score += 30 * len(common_building)
        reasons.append("building:" + ",".join(sorted(common_building)))

    pl, dl = level_tokens(pdf_text), level_tokens(dwg_text)
    common_level = pl & dl
    if common_level:
        score += 35 * len(common_level)
        reasons.append("level:" + ",".join(sorted(common_level)))

    if "COMPTAGE" in dwg_text and "COMPTAGE" in pdf_text:
        score += 40
        reasons.append("comptage")
    if "TRIUM" in dwg_text and "MOE" in normalize(str(pdf.parent)):
        score += 35
        reasons.append("moe_trium")
    if "PLAN R + 2" in dwg_text or "PLAN R 2" in dwg_text:
        if "N2" in normalize(pdf_text):
            score += 30
            reasons.append("bpce_n2")
    if "VERDUN" in dwg_text and "VERDUN" in pdf_text:
        score += 25
        reasons.append("verdun")
    if "-C-" in dwg.name.upper() or " 01 C " in dwg_text:
        score += 2
        reasons.append("prefer_newer_revision")

    # Les lots ne doivent pas piloter le matching, mais aident a eviter les DWG
    # manifestement hors dossier quand les noms sont pauvres.
    if lot_tokens(pdf_text) & lot_tokens(dwg_text):
        score += 5
        reasons.append("lot_hint")

    return score, reasons


def resolve_pairs(folder: Path, min_score=30):
    pdfs = list_pdf(folder)
    dwgs = list_dwg(folder)
    pairs = []
    unresolved = []
    for pdf in pdfs:
        ranked = []
        for dwg in dwgs:
            score, reasons = score_pair(pdf, dwg)
            ranked.append((score, reasons, dwg))
        ranked.sort(key=lambda item: (-item[0], str(item[2]).lower()))
        best_score, reasons, best_dwg = ranked[0] if ranked else (0, [], None)
        if best_dwg and best_score >= min_score:
            pairs.append({
                "pdf": pdf,
                "dwg": best_dwg,
                "score": best_score,
                "reasons": reasons,
            })
        else:
            unresolved.append({
                "pdf": str(pdf),
                "best_score": best_score,
                "best_dwg": str(best_dwg) if best_dwg else "",
                "reasons": reasons,
            })
    return pairs, unresolved


def run_resolved_batch(folder: Path, out_dir: Path, thresholds, max_negative_crops=200, min_score=30):
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs, unresolved = resolve_pairs(folder, min_score=min_score)
    rows = []
    errors = []
    manifest_pairs = []
    for index, pair in enumerate(pairs, 1):
        dwg, pdf = pair["dwg"], pair["pdf"]
        print(f"[{index}/{len(pairs)}] {pdf.relative_to(folder)} <- {dwg.relative_to(folder)}", flush=True)
        manifest_pairs.append({
            "pdf": str(pdf),
            "dwg": str(dwg),
            "score": pair["score"],
            "reasons": pair["reasons"],
        })
        try:
            sheet = build_sheet(dwg, pdf)
            prototypes = _build_prototypes(sheet)
            clusters, _pdf_meta = _pdf_clusters(pdf)
            candidates = []
            for th in thresholds:
                matches, counts, all_candidates, _match_clusters, quota_report = _assign(prototypes, clusters, th)
                data = {
                    "dwg": {"total": len(sheet["symbols"])},
                    "match": {
                        "total": len(matches),
                        "by_label": dict(counts),
                        "ambiguous": 0,
                        "candidate_edges": len(all_candidates),
                        "quota": quota_report,
                    },
                }
                candidates.append((score_result(data), th, data))
                print(
                    f"  th={th:.2f} dwg={data['dwg']['total']} match={data['match']['total']} "
                    f"edges={data['match']['candidate_edges']}",
                    flush=True,
                )
            _, best_th, _best = sorted(candidates, key=lambda x: x[0])[0]
            final, _json_path, _csv_path, _html_path, _overlay_path, h5_path = run_match(
                dwg, pdf, out_dir / "best", threshold=best_th, max_negative_crops=max_negative_crops
            )
            h5_validation = validate_hdf5(h5_path)
            rows.append({
                "plan": pdf.stem,
                "dwg": str(dwg),
                "pdf": str(pdf),
                "pair_score": pair["score"],
                "pair_reasons": json.dumps(pair["reasons"], ensure_ascii=False),
                "hdf5": str(h5_path),
                "hdf5_ok": h5_validation["ok"],
                "hdf5_size_bytes": h5_validation["size_bytes"],
                "best_threshold": best_th,
                "dwg_total": final["dwg"]["total"],
                "match_total": final["match"]["total"],
                "delta": final["match"]["total"] - final["dwg"]["total"],
                "candidate_clusters": final["pdf"]["candidate_clusters"],
                "legend_templates": final["pdf"]["legend_templates"],
                "positives": final["match"]["positives"],
                "ambiguous": final["match"]["ambiguous"],
                "negatives": final["match"]["negatives"],
                "match_by_pass": json.dumps(final["match"].get("by_pass") or {}, ensure_ascii=False),
                "quota_remaining": json.dumps(final["match"].get("quota", {}).get("by_label_remaining", {}), ensure_ascii=False),
                "over_quota_labels": json.dumps(final["match"].get("quota", {}).get("over_quota_labels", {}), ensure_ascii=False),
                "dwg_by_label": json.dumps(final["dwg"]["by_label"], ensure_ascii=False),
                "match_by_label": json.dumps(final["match"]["by_label"], ensure_ascii=False),
            })
        except Exception as exc:
            errors.append({
                "pdf": str(pdf),
                "dwg": str(dwg),
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  ERROR {type(exc).__name__}: {exc}", flush=True)

    write_summary(out_dir, rows, manifest_pairs, unresolved, errors)
    if rows:
        write_hdf5_manifest(out_dir, rows)
        write_ssi_diagnostics(out_dir, rows)
    return rows, unresolved, errors


def write_summary(out_dir: Path, rows, manifest_pairs, unresolved, errors):
    fields = [
        "plan", "best_threshold", "dwg_total", "match_total", "delta",
        "candidate_clusters", "legend_templates", "positives", "ambiguous",
        "negatives", "hdf5_ok", "hdf5_size_bytes", "hdf5", "pair_score",
        "pair_reasons", "over_quota_labels", "dwg_by_label", "match_by_label",
        "dwg", "pdf",
    ]
    csv_path = out_dir / "resolved_batch_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema": "dwg_pdf_resolved_pairs_v1",
        "pairs": manifest_pairs,
        "unresolved": unresolved,
        "errors": errors,
    }
    (out_dir / "resolved_pairs_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Resolved batch summary",
        "",
        f"- Paires resolues: {len(manifest_pairs)}.",
        f"- Paires executees OK: {len(rows)}.",
        f"- Non resolus: {len(unresolved)}.",
        f"- Erreurs execution: {len(errors)}.",
        f"- HDF5 valides: {sum(1 for r in rows if r['hdf5_ok'])}/{len(rows)}.",
        f"- Total DWG: {sum(int(r['dwg_total']) for r in rows)}.",
        f"- Total matchs: {sum(int(r['match_total']) for r in rows)}.",
        f"- Sur-quotas label: {sum(1 for r in rows if json.loads(r.get('over_quota_labels') or '{}'))}.",
        "",
        "| Plan | DWG | score paire | seuil | DWG objets | matchs | delta | HDF5 |",
        "|---|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['plan']} | {Path(row['dwg']).name} | {row['pair_score']} | "
            f"{row['best_threshold']} | {row['dwg_total']} | {row['match_total']} | "
            f"{row['delta']} | {'OK' if row['hdf5_ok'] else 'KO'} |"
        )
    if unresolved:
        lines += ["", "## Non resolus", ""]
        for row in unresolved:
            lines.append(f"- {row['pdf']} (best={row['best_score']} {row['best_dwg']})")
    if errors:
        lines += ["", "## Erreurs", ""]
        for row in errors:
            lines.append(f"- PDF `{row['pdf']}` avec DWG `{row['dwg']}`: {row['error']}")
    md_path = out_dir / "resolved_batch_summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"CSV: {csv_path}")
    print(f"MD:  {md_path}")
    print(f"Pairs manifest: {out_dir / 'resolved_pairs_manifest.json'}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=HERE / "out" / "dwg_pdf_match" / "resolved_batch")
    parser.add_argument("--thresholds", default=",".join(str(x) for x in DEFAULT_THRESHOLDS))
    parser.add_argument("--max-negative-crops", type=int, default=200)
    parser.add_argument("--min-score", type=int, default=30)
    args = parser.parse_args(argv)
    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    run_resolved_batch(
        args.folder,
        args.out_dir,
        thresholds,
        max_negative_crops=args.max_negative_crops,
        min_score=args.min_score,
    )


if __name__ == "__main__":
    main()
