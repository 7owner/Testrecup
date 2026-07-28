"""Batch de resolution DWG -> PDF sur un dossier.

Le batch travaille sur les paires exactes DWG/PDF d'un dossier, teste plusieurs
seuils de matching de forme, puis retient le seuil qui rapproche le mieux le
nombre de matchs du nombre d'objets DWG. C'est une calibration de developpement :
elle sert a comprendre les dossiers et a remplir des exemples, pas a definir le
mode SaaS final.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from render_dwg import build_sheet  # noqa: E402
from dwg_pdf_match import (  # noqa: E402
    _assign,
    _build_prototypes,
    _pdf_clusters,
    run_match,
    validate_hdf5,
)


DEFAULT_THRESHOLDS = [0.16, 0.19, 0.22, 0.25, 0.30, 0.35, 0.40, 0.45]


def exact_pairs(folder: Path):
    pairs = []
    for dwg in folder.rglob("*.dwg"):
        low_parts = {p.lower() for p in dwg.parts}
        if {"00-xref", "0-xref", "old"} & low_parts:
            continue
        pdf = dwg.with_suffix(".pdf")
        if pdf.exists():
            pairs.append((dwg, pdf))
    return sorted(pairs, key=lambda p: str(p[0]).lower())


def score_result(data):
    # Premier critere: total retrouve proche du total DWG.
    # Deuxieme critere: le moins de sur-detection possible.
    dwg_total = int(data["dwg"]["total"])
    match_total = int(data["match"]["total"])
    return (abs(match_total - dwg_total), max(0, match_total - dwg_total), -match_total)


def run_batch(folder: Path, out_dir: Path, thresholds, max_negative_crops=200):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    pairs = exact_pairs(folder)
    for index, (dwg, pdf) in enumerate(pairs, 1):
        print(f"[{index}/{len(pairs)}] {pdf.relative_to(folder)}", flush=True)
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
        _, best_th, best = sorted(candidates, key=lambda x: x[0])[0]
        final_dir = out_dir / "best"
        final, _json_path, _csv_path, _html_path, _overlay_path, h5_path = run_match(
            dwg,
            pdf,
            final_dir,
            threshold=best_th,
            max_negative_crops=max_negative_crops,
        )
        h5_validation = validate_hdf5(h5_path)
        rows.append({
            "plan": pdf.stem,
            "dwg": str(dwg),
            "pdf": str(pdf),
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
    write_summary(out_dir, rows)
    write_hdf5_manifest(out_dir, rows)
    write_ssi_diagnostics(out_dir, rows)
    return rows


def write_hdf5_manifest(out_dir: Path, rows):
    manifest = {
        "schema": "dwg_pdf_match_hdf5_manifest_v1",
        "hdf5_is_primary_artifact": True,
        "files": [validate_hdf5(Path(row["hdf5"])) for row in rows],
    }
    path = out_dir / "hdf5_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HDF5 manifest: {path}")


def _loads_map(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _is_ssi_row(row):
    text = f"{row.get('plan', '')} {row.get('dwg_by_label', '')}".upper()
    return any(k in text for k in ("SSI", "INCENDIE", "DETECTEUR", "DECLENCHEUR", "DIFFUSEUR", "VENTOUSE", "NSA"))


def write_ssi_diagnostics(out_dir: Path, rows):
    ssi_rows = [row for row in rows if _is_ssi_row(row)]
    lines = [
        "# Diagnostic SSI",
        "",
        "Ce rapport controle les plans SSI apres matching avec quotas DWG. "
        "Un label ne doit plus depasser sa quantite DWG; les deltas restants "
        "sont des sous-detections ou des symboles non resolus.",
        "",
        "| Plan | DWG | matchs | delta | sur-quotas | passes |",
        "|---|---:|---:|---:|---|---|",
    ]
    details = []
    for row in ssi_rows:
        dwg = _loads_map(row.get("dwg_by_label"))
        match = _loads_map(row.get("match_by_label"))
        over = _loads_map(row.get("over_quota_labels"))
        passes = _loads_map(row.get("match_by_pass"))
        labels = sorted(set(dwg) | set(match))
        missing = {label: int(dwg.get(label, 0)) - int(match.get(label, 0))
                   for label in labels if int(dwg.get(label, 0)) > int(match.get(label, 0))}
        details.append((row["plan"], dwg, match, missing, over, passes))
        lines.append(
            f"| {row['plan']} | {row['dwg_total']} | {row['match_total']} | {row['delta']} | "
            f"{json.dumps(over, ensure_ascii=False) if over else '-'} | "
            f"{json.dumps(passes, ensure_ascii=False)} |"
        )
    lines += ["", "## Detail par label", ""]
    for plan, dwg, match, missing, over, passes in details:
        lines += [
            f"### {plan}",
            "",
            "| Label | DWG | match | delta |",
            "|---|---:|---:|---:|",
        ]
        for label in sorted(set(dwg) | set(match)):
            d = int(dwg.get(label, 0))
            m = int(match.get(label, 0))
            lines.append(f"| {label} | {d} | {m} | {m - d} |")
        if over:
            lines.append("")
            lines.append(f"- Sur-quotas a corriger: {json.dumps(over, ensure_ascii=False)}")
        if missing:
            lines.append("")
            lines.append(f"- Sous-detections restantes: {json.dumps(missing, ensure_ascii=False)}")
        lines.append("")

    path = out_dir / "ssi_match_diagnostics.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"SSI diagnostics: {path}")


def write_summary(out_dir: Path, rows):
    csv_path = out_dir / "batch_match_summary.csv"
    fields = [
        "plan", "best_threshold", "dwg_total", "match_total", "delta",
        "candidate_clusters", "legend_templates", "positives", "ambiguous",
        "negatives", "hdf5_ok", "hdf5_size_bytes", "hdf5", "match_by_pass",
        "quota_remaining", "over_quota_labels", "dwg_by_label", "match_by_label",
        "dwg", "pdf",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    md_path = out_dir / "batch_match_summary.md"
    lines = [
        "# Batch match summary",
        "",
        "| Plan | seuil | DWG | matchs | delta | ambigus | HDF5 | gabarits legende |",
        "|---|---:|---:|---:|---:|---:|:---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['plan']} | {row['best_threshold']} | {row['dwg_total']} | "
            f"{row['match_total']} | {row['delta']} | {row['ambiguous']} | "
            f"{'OK' if row['hdf5_ok'] else 'KO'} | {row['legend_templates']} |"
        )
    lines += [
        "",
        "## Lecture",
        "",
        f"- Paires traitees: {len(rows)}.",
        f"- Total DWG: {sum(int(r['dwg_total']) for r in rows)}.",
        f"- Total matchs retenus: {sum(int(r['match_total']) for r in rows)}.",
        f"- Fichiers HDF5 valides: {sum(1 for r in rows if r['hdf5_ok'])}/{len(rows)}.",
        f"- Plans avec sur-quota label: {sum(1 for r in rows if _loads_map(r.get('over_quota_labels')))}.",
        "- Les seuils sont calibres par dossier contre le DWG; ils ne sont pas encore une regle production.",
        "- L'assignation est bornee par quota DWG de label; le quota prototype reste trace en diagnostic.",
        "- Les fichiers `*.objects.h5` du dossier `best` sont les artefacts principaux: ils contiennent les prototypes DWG, les crops PDF et les candidats dataset visualisables.",
        "- Les fichiers `*.dataset_candidates.csv` restent de petits index lisibles, pas la source principale des objets.",
        "- `hdf5_manifest.json` valide la presence des groupes, empreintes binaires, vignettes prototypes et comptes PDF.",
        "- `ssi_match_diagnostics.md` detaille les deltas SSI par label.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"CSV: {csv_path}")
    print(f"MD:  {md_path}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=HERE / "out" / "dwg_pdf_match" / "batch")
    parser.add_argument("--thresholds", default=",".join(str(x) for x in DEFAULT_THRESHOLDS))
    parser.add_argument("--max-negative-crops", type=int, default=200)
    args = parser.parse_args(argv)
    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    run_batch(args.folder, args.out_dir, thresholds, max_negative_crops=args.max_negative_crops)


if __name__ == "__main__":
    main()
