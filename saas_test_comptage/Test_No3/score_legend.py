"""Banc du lecteur de legende : legende lue dans le PDF vs legende lue dans le DWG.

Le PDF est TRACE depuis le DWG : les libelles de legende sont les memes chaines. Le DWG
fournit donc une verite gratuite, dans l'esprit du reste du projet (les DWG servent a
fabriquer la verite, jamais a la production).

Precision = part des entrees trouvees dans le PDF qui existent vraiment dans la legende.
Rappel    = part des entrees de la legende DWG qu'on retrouve dans le PDF.

Sortie : out/legend_bench.csv + resume console.
Usage  : PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe score_legend.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

from bench import find_pairs                # noqa: E402
from autolabel import detect_metier, CACHE                       # noqa: E402
from dwg_reader import extract_plan                              # noqa: E402
from block_resolver import resolve_blocks, annotate_inserts      # noqa: E402
from legend_extract import find_legend, detect_legend_columns    # noqa: E402
from legend_pdf import read_legend                               # noqa: E402

CONFIG = json.loads((HERE.parent / "plan_takeoff" / "config.json")
                    .read_text(encoding="utf-8"))


def norm(s: str) -> str:
    """Normalise un libelle pour l'appariement PDF <-> DWG : sans accents, sans casse,
    espaces ecrases. Les deux sources tracent le MEME texte ; la normalisation ne sert
    qu'a absorber les differences d'encodage et d'espacement."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def dwg_legend_labels(dwg_path: Path) -> set[str]:
    """Les libelles de legende IMPRIMES du DWG. Reproduit takeoff.process_plan (lignes 71-76).

    On prend l'ENSEMBLE des libelles de legende, PAS l'intersection avec les symboles poses
    sur la feuille. Le but est de mesurer la LECTURE de la legende, pas le comptage : une
    entree imprimee dans la legende ("DETECTEUR OPTIQUE") est une vraie entree meme si aucun
    de ces detecteurs n'est dessine sur cette feuille precise. Restreindre aux symboles traces
    (essai du 2026-07-14) transformait ces vraies entrees en faux positifs et faussait la
    precision a la baisse.

    Contrepartie assumee : un DWG model-space partage entre plusieurs feuilles rend la legende
    de TOUTES les feuilles (mesure : la verite du plan incendie SSI-240 contient "camera dome",
    entree de videosurveillance). Ces entrees hors-feuille comptent alors comme des MANQUES,
    jamais comme des faux positifs -- la precision reste honnete, le rappel devient une BORNE
    BASSE. C'est le bon compromis : on veut une precision fiable et un rappel prudent.
    """
    plan = extract_plan(dwg_path, cache_dir=CACHE, refresh=False)
    resolved = resolve_blocks(plan, CONFIG)
    per_insert = annotate_inserts(plan, resolved, CONFIG)
    by_display, _ = find_legend(plan, per_insert, resolved, CONFIG)
    col_labels, _ = detect_legend_columns(plan, per_insert)
    return {norm(v) for v in {**col_labels, **by_display}.values() if norm(v)}


def prf(tp: int, fp: int, fn: int):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main():
    rows = []
    tot_tp = tot_fp = tot_fn = 0
    for dwg, pdf in find_pairs():
        met = detect_metier(dwg)
        try:
            truth = dwg_legend_labels(dwg)
        except Exception as e:
            print(f"[{met}] {pdf.name[:45]:45} ERR DWG {str(e)[:40]}", flush=True)
            continue
        if not truth:
            print(f"[{met}] {pdf.name[:45]:45} (aucune legende DWG -> plan ignore)",
                  flush=True)
            continue
        try:
            res = read_legend(pdf)
        except Exception as e:
            print(f"[{met}] {pdf.name[:45]:45} ERR PDF {str(e)[:40]}", flush=True)
            continue

        found = {norm(e["label"]) for e in res["entries"]}
        tp = len(found & truth)
        fp = len(found - truth)
        fn = len(truth - found)
        tot_tp, tot_fp, tot_fn = tot_tp + tp, tot_fp + fp, tot_fn + fn
        p, r, f = prf(tp, fp, fn)
        print(f"[{met}] {pdf.name[:45]:45} verite={len(truth):>3} trouve={len(found):>3} "
              f"P={p:.2f} R={r:.2f} F1={f:.2f}", flush=True)

        for lab in sorted(found - truth):
            rows.append({"metier": met, "plan": pdf.name, "cas": "FAUX_POSITIF",
                         "libelle": lab})
        for lab in sorted(truth - found):
            rows.append({"metier": met, "plan": pdf.name, "cas": "MANQUE", "libelle": lab})
        for lab in sorted(found & truth):
            rows.append({"metier": met, "plan": pdf.name, "cas": "OK", "libelle": lab})

    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    with open(outdir / "legend_bench.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["metier", "plan", "cas", "libelle"])
        w.writeheader()
        w.writerows(rows)

    p, r, f = prf(tot_tp, tot_fp, tot_fn)
    print("\n===== GLOBAL =====")
    print(f"  vrais positifs {tot_tp}   faux positifs {tot_fp}   manques {tot_fn}")
    print(f"  precision {p:.3f}   rappel {r:.3f}   F1 {f:.3f}")
    print(f"\nDetail : {outdir / 'legend_bench.csv'}")


if __name__ == "__main__":
    main()
