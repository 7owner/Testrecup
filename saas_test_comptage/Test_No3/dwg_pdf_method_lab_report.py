"""Consolide les sorties de dwg_pdf_method_lab.py.

Le rapport sert a comparer les methodes par dossier sans relancer les calculs.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_runs(root: Path):
    for path in sorted(root.rglob("method_lab_details.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            yield path, None, f"{type(exc).__name__}: {exc}"
            continue
        yield path, data, ""


def best_result(pair):
    method = pair.get("best_method", "")
    threshold = str(pair.get("best_threshold", ""))
    for result in pair.get("results", []):
        if result.get("method") == method and str(result.get("threshold", "")) == threshold:
            return result
    return {}


def write_report(root: Path, out_path: Path):
    rows = []
    method_counts = Counter()
    run_counts = defaultdict(lambda: {"pairs": 0, "errors": 0, "unresolved": 0})
    load_errors = []

    for details_path, data, error in load_runs(root):
        run_name = str(details_path.parent.relative_to(root))
        if error:
            load_errors.append((run_name, error))
            continue
        pairs = data.get("pairs", [])
        errors = data.get("errors", [])
        unresolved = data.get("unresolved", [])
        run_counts[run_name]["pairs"] += len(pairs)
        run_counts[run_name]["errors"] += len(errors)
        run_counts[run_name]["unresolved"] += len(unresolved)
        for pair in pairs:
            best = best_result(pair)
            method = pair.get("best_method", "")
            method_counts[method] += 1
            rows.append({
                "run": run_name,
                "pdf": Path(pair.get("pdf", "")).name,
                "dwg": Path(pair.get("dwg", "")).name,
                "method": method,
                "threshold": pair.get("best_threshold", ""),
                "dwg_total": best.get("dwg_total", ""),
                "match_total": best.get("match_total", ""),
                "delta": best.get("delta", ""),
                "warnings": best.get("warnings", ""),
                "over_quota": best.get("over_quota", ""),
            })

    lines = [
        "# Method lab consolidated report",
        "",
        f"- Racine: `{root}`",
        f"- Runs lus: {len(run_counts)}",
        f"- Paires consolidees: {len(rows)}",
        f"- Meilleures methodes: {json.dumps(dict(method_counts), ensure_ascii=False)}",
        "",
        "## Runs",
        "",
        "| Run | paires | erreurs | non resolus |",
        "|---|---:|---:|---:|",
    ]
    for run_name, counts in sorted(run_counts.items()):
        lines.append(
            f"| {run_name} | {counts['pairs']} | {counts['errors']} | {counts['unresolved']} |"
        )

    if load_errors:
        lines += ["", "## Erreurs de lecture", ""]
        for run_name, error in load_errors:
            lines.append(f"- `{run_name}`: {error}")

    lines += [
        "",
        "## Meilleurs resultats par PDF",
        "",
        "| Run | PDF | DWG | methode | seuil | DWG | match | delta | alertes |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['pdf']} | {row['dwg']} | {row['method']} | "
            f"{row['threshold']} | {row['dwg_total']} | {row['match_total']} | "
            f"{row['delta']} | {row['warnings']} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("saas_test_comptage/Test_No3/out/method_lab"))
    parser.add_argument("--out", type=Path, default=Path("saas_test_comptage/Test_No3/out/method_lab/consolidated_report.md"))
    args = parser.parse_args(argv)
    path = write_report(args.root, args.out)
    print(path)


if __name__ == "__main__":
    main()
