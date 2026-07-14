"""CLI de comptage : parcourt PLANS_COMPLETS_NEW, compte les INSERTs des DWG,
genere rapport HTML + CSV. Zero entrainement, zero intervention.

Usage :
  python takeoff.py --root "..\\PLANS_COMPLETS_NEW" --out rapport
  python takeoff.py --root ... --affaire "CROIX ROUGE" --refresh-cache
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
import zipfile
from pathlib import Path

from dwg_reader import extract_plan
from block_resolver import resolve_blocks, annotate_inserts
from legend_extract import find_legend, detect_legend_columns
from zones import assign_zones
from report import write_outputs, tally, tally_excluded

HERE = Path(__file__).parent
SKIP_DIR_TOKENS = ("xref", "old", "plotcfgs")


def discover_dwgs(root: Path, extracted_dir: Path):
    """Liste (affaire, plan_name, dwg_path). Ignore .bak, dossiers xref/old ; extrait les zips contenant des DWG."""
    found = []
    for dwg in sorted(root.rglob("*.dwg")):
        rel = dwg.relative_to(root)
        low = [p.lower() for p in rel.parts[:-1]]
        if any(any(tok in part for tok in SKIP_DIR_TOKENS) for part in low):
            continue
        affaire = rel.parts[1] if len(rel.parts) > 1 and rel.parts[0].upper() == "PLANS" else rel.parts[0]
        found.append((affaire, dwg.stem, dwg))
    # zips avec DWG dedans (ex : MC2)
    for z in sorted(root.rglob("*.zip")):
        rel = z.relative_to(root)
        low = [p.lower() for p in rel.parts[:-1]]
        if any(any(tok in part for tok in SKIP_DIR_TOKENS) for part in low):
            continue
        try:
            zf = zipfile.ZipFile(z)
        except Exception:
            continue
        dwg_entries = [e for e in zf.namelist() if e.lower().endswith(".dwg") and "xref" not in e.lower()]
        for entry in dwg_entries:
            target = extracted_dir / z.stem / Path(entry).name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(entry) as src, open(target, "wb") as dst:
                    dst.write(src.read())
            affaire = rel.parts[1] if len(rel.parts) > 1 and rel.parts[0].upper() == "PLANS" else rel.parts[0]
            found.append((affaire, Path(entry).stem, target))
        zf.close()
    # dedoublonnage par (affaire, nom)
    seen = set()
    out = []
    for affaire, name, path in found:
        key = (affaire, name.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((affaire, name, path))
    return out


def process_plan(affaire: str, plan_name: str, dwg_path: Path, config: dict,
                 cache_dir: Path, refresh: bool) -> dict:
    plan = extract_plan(dwg_path, cache_dir=cache_dir, refresh=refresh)
    resolved = resolve_blocks(plan, config)
    per_insert = annotate_inserts(plan, resolved, config)
    label_by_display, legend_ids = find_legend(plan, per_insert, resolved, config)
    col_labels, col_ids = detect_legend_columns(plan, per_insert)
    label_by_display = {**col_labels, **label_by_display}
    for i in legend_ids | col_ids:
        if not per_insert[i].get("excluded"):
            per_insert[i]["excluded"] = "legende"
    zones = assign_zones(plan, per_insert, config)
    rows = tally(per_insert, label_by_display)
    excluded = tally_excluded(per_insert)
    blocks_prims = {info["display"]: info["prims"]
                    for info in resolved.values() if info["prims"]}
    return {
        "affaire": affaire, "plan_name": plan_name, "source": str(dwg_path),
        "rows": rows, "excluded": excluded, "per_insert": per_insert,
        "zones": zones, "blocks_prims": blocks_prims, "_plan": plan,
    }


def process_pdfs(pdf_arg: str, out_dir: Path):
    """Mode PDF : compte les objets de legende directement dans des PDF vectoriels."""
    from pdf_takeoff import count_pdf

    src = Path(pdf_arg)
    pdfs = [src] if src.is_file() else sorted(src.rglob("*.pdf"))
    print(f"{len(pdfs)} PDF a compter")
    results = []
    for pdf in pdfs:
        print(f"  {pdf.name} ...", flush=True)
        try:
            res = count_pdf(pdf)
            n = sum(r["count"] for r in res["rows"])
            print(f"      {n} objets comptes, {len(res['rows'])} lignes"
                  + (f", avertissements: {'; '.join(res['warnings'])}" if res["warnings"] else ""))
            results.append({
                "affaire": pdf.parent.name, "plan_name": pdf.stem, "source": str(pdf),
                "rows": res["rows"], "excluded": [], "zones": {}, "blocks_prims": {},
                "_pdf": pdf, "overlays": res["overlays"], "thumbs": res["thumbs"],
                "error": None if res["rows"] else "aucune legende exploitable",
            })
        except Exception as e:
            traceback.print_exc()
            results.append({"affaire": pdf.parent.name, "plan_name": pdf.stem,
                            "source": str(pdf), "error": f"{type(e).__name__}: {e}",
                            "rows": [], "excluded": [], "blocks_prims": {}})
    write_outputs(results, out_dir)
    ok = sum(1 for r in results if not r.get("error"))
    print(f"\nRapport : {out_dir / 'index.html'}  ({ok}/{len(results)} PDF comptes)")
    return 0 if ok else 1


def load_config():
    return json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def count_dwg_file(dwg_path: Path, config: dict | None = None) -> dict:
    """Comptage EXACT depuis un DWG -> resultat rendu web (lignes, overlay SVG, vignettes SVG)."""
    from report import overlay_svg, block_thumbnail_svg
    config = config or load_config()
    cache_dir = HERE / config.get("cache_dir", "cache")
    r = process_plan(dwg_path.parent.name, dwg_path.stem, dwg_path, config, cache_dir, False)
    for row in r["rows"]:
        row["conf"] = "exact"
    svg = overlay_svg(r["_plan"], r["per_insert"], r.get("zones") or {})
    thumbs = {disp: block_thumbnail_svg(prims) for disp, prims in r["blocks_prims"].items() if prims}
    return {"rows": r["rows"], "overlay_svg": svg, "thumbs_svg": thumbs,
            "excluded": r["excluded"], "warnings": [], "source": "DWG (exact)"}


def find_sibling_dwg(pdf_path: Path) -> Path | None:
    """Cherche un DWG correspondant a cote du PDF (meme dossier ou dossiers proches)."""
    import re
    stem = pdf_path.stem
    code = re.search(r"(CFA|CFO|SSI|CFO CFA|IMP)[- ]?\d+", stem, re.IGNORECASE)
    search_dirs = [pdf_path.parent, pdf_path.parent.parent]
    for d in search_dirs:
        if not d.exists():
            continue
        for dwg in d.rglob("*.dwg"):
            if any(tok in p.lower() for p in dwg.parts for tok in SKIP_DIR_TOKENS):
                continue
            if dwg.stem == stem:
                return dwg
            if code and code.group(0).replace(" ", "") in dwg.stem.replace(" ", ""):
                return dwg
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Comptage deterministe des objets de legende (DWG ou PDF)")
    ap.add_argument("--root", default=None, help="Dossier racine des plans DWG (PLANS_COMPLETS_NEW)")
    ap.add_argument("--pdf", default=None, help="PDF (fichier ou dossier) a compter directement")
    ap.add_argument("--out", default=str(HERE / "rapport"), help="Dossier de sortie")
    ap.add_argument("--affaire", default=None, help="Limiter a une affaire (sous-dossier)")
    ap.add_argument("--refresh-cache", action="store_true")
    args = ap.parse_args(argv)

    if args.pdf:
        return process_pdfs(args.pdf, Path(args.out))
    if not args.root:
        ap.error("--root (DWG) ou --pdf requis")

    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    root = Path(args.root)
    out_dir = Path(args.out)
    cache_dir = HERE / config.get("cache_dir", "cache")
    extracted_dir = cache_dir / "extracted_zips"

    plans = discover_dwgs(root, extracted_dir)
    if args.affaire:
        plans = [p for p in plans if args.affaire.lower() in p[0].lower()]
    print(f"{len(plans)} plans DWG a traiter")

    results = []
    for affaire, plan_name, dwg_path in plans:
        print(f"  [{affaire}] {plan_name} ...", flush=True)
        try:
            r = process_plan(affaire, plan_name, dwg_path, config, cache_dir, args.refresh_cache)
            n = sum(row["count"] for row in r["rows"])
            print(f"      {n} objets comptes, {len(r['rows'])} lignes, "
                  f"{len(r['zones'] or {})} zones, {sum(e['count'] for e in r['excluded'])} exclus")
            results.append(r)
        except Exception as e:
            traceback.print_exc()
            results.append({"affaire": affaire, "plan_name": plan_name,
                            "source": str(dwg_path), "error": f"{type(e).__name__}: {e}",
                            "rows": [], "excluded": [], "blocks_prims": {}})

    write_outputs(results, out_dir)
    ok = sum(1 for r in results if not r.get("error"))
    print(f"\nRapport : {out_dir / 'index.html'}  ({ok}/{len(results)} plans parses)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
