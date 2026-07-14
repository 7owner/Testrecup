"""Banc de verite : pour chaque paire DWG+PDF, compare le compte DWG (le corrige)
au compte de la methode PDF actuelle (plan_takeoff). Range par metier.

Le compte DWG est la reference : inserts modele-espace, par NOM DE BLOC, restreints
aux calques effectivement traces dans le PDF (calques communs DWG/PDF). C'est ce que
la feuille montre. Aucun alignement necessaire : on ne compare que des NOMBRES.

Sorties : Test_No3/out/bench.csv (detail par classe) + resume console.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

import json  # noqa: E402
import fitz  # noqa: E402
import pdf_takeoff as pt  # noqa: E402
from takeoff import process_plan  # noqa: E402
from autolabel import detect_metier, CACHE  # noqa: E402

ROOT = HERE.parent / "PLANS_COMPLETS_NEW"
SKIP = ("xref", "/old/", "\\old\\", "plotcfg", ".bak")
CONFIG = json.loads((HERE.parent / "plan_takeoff" / "config.json").read_text(encoding="utf-8"))
# corrige legende-exact : on ecarte aussi les calques de TAGS/DESIGNATION (annotation,
# 1 etiquette par symbole -> sinon double compte). "signation" attrape Designation/
# Désignation quel que soit l'encodage du 'e'.
CONFIG["exclude_layer_patterns"] = list(CONFIG.get("exclude_layer_patterns", [])) + [
    "signation", "REPERAGE", "REPÉRAGE", "\\bTAG", "NUMEROTATION", "ETIQUET",
]


def find_pairs():
    out = []
    for dwg in ROOT.rglob("*.dwg"):
        low = str(dwg).lower()
        if any(t in low for t in SKIP):
            continue
        pdf = dwg.with_suffix(".pdf")
        if pdf.exists():
            out.append((dwg, pdf))
    return sorted(out, key=lambda p: (detect_metier(p[0]), p[0].name))


def _pdf_plotted_layers(pdf_path):
    """Calques OCG effectivement traces dans CE PDF (>= 3 glyphes)."""
    doc = fitz.open(pdf_path)
    clusters, _ = pt.extract_page(doc[0])
    doc.close()
    lc = Counter((c["layer"] or "").strip() for c in clusters)
    return {l for l, n in lc.items() if l and n >= 3}


def dwg_truth(dwg_path, pdf_path):
    """Corrige legende-exact POUR CETTE FEUILLE.

    Un DWG model-space est partage par plusieurs PDF (video, eclairage...), chacun
    ne tracant qu'un sous-ensemble de calques. On prend donc la resolution complete
    de plan_takeoff (resout *U, exclut annotation/cartouche/legende, libelles de
    legende) PUIS on filtre aux calques reellement traces dans ce PDF precis.
    Retourne Counter{label: n}."""
    res = process_plan("bench", dwg_path.stem, dwg_path, CONFIG,
                       cache_dir=CACHE, refresh=False)
    plotted = _pdf_plotted_layers(pdf_path)
    # label par display (depuis les rows deja tallies)
    label_by_display = {r["display"]: r["label"] for r in res["rows"]}
    counts = Counter()
    for ins in res["per_insert"]:
        if ins.get("excluded"):
            continue
        if (ins.get("layer") or "").strip() not in plotted:
            continue
        disp = ins["display"]
        counts[label_by_display.get(disp, disp)] += 1
    return counts, plotted


def current_method(pdf_path):
    """Compte de la methode PDF actuelle : total et par libelle de legende."""
    res = pt.count_pdf(pdf_path)
    per = Counter()
    for r in res["rows"]:
        per[r["label"]] += r["count"]
    return sum(per.values()), per


def main():
    pairs = find_pairs()
    rows = []
    summary = []
    for dwg, pdf in pairs:
        met = detect_metier(dwg)
        try:
            truth, _excl = dwg_truth(dwg, pdf)
        except Exception as e:
            summary.append((met, pdf.name, "ERR DWG", str(e)[:50]))
            continue
        # anonymes non resolus (label encore *U...) ecartes du total, gardes en detail
        truth_named = Counter({k: v for k, v in truth.items() if not k.startswith("*")})
        tot_truth = sum(truth_named.values())
        try:
            tot_cur, _ = current_method(pdf)
        except Exception as e:
            tot_cur = f"ERR({str(e)[:20]})"
        summary.append((met, pdf.name, tot_truth, tot_cur))
        for name, c in truth.most_common():
            rows.append({"metier": met, "plan": pdf.name, "bloc": name, "compte_dwg": c,
                         "anonyme": name.startswith("*")})
        print(f"[{met}] {pdf.name[:45]:45}  DWG_verite={tot_truth:>4}  actuel={tot_cur}", flush=True)

    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    with open(outdir / "bench.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["metier", "plan", "bloc", "compte_dwg", "anonyme"])
        w.writeheader()
        w.writerows(rows)

    print("\n===== RESUME par metier (total objets nommes) =====")
    by_met = defaultdict(lambda: [0, 0])
    for met, plan, tt, tc in summary:
        if isinstance(tt, int):
            by_met[met][0] += tt
        if isinstance(tc, int):
            by_met[met][1] += tc
    for met in sorted(by_met):
        tt, tc = by_met[met]
        print(f"  {met:12}  DWG_verite={tt:>5}   methode_actuelle={tc:>5}   ecart={tc - tt:+d}")
    print(f"\nCSV detaille : {outdir / 'bench.csv'}")


if __name__ == "__main__":
    main()
