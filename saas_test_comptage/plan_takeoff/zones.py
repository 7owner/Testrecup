"""Decoupage spatial d'un DWG multi-etages (plusieurs niveaux dessines cote a cote).

Clustering par grille : les inserts sont projetes sur une grille grossiere,
les composantes connexes forment les zones. Chaque zone est etiquetee par le
TEXT de titre d'etage (RDC, R+1...) le plus proche, sinon ZONE_n.
"""
from __future__ import annotations

import re
from collections import defaultdict


def _grid_components(points, cell):
    occupied = {}
    for idx, (x, y) in enumerate(points):
        occupied.setdefault((int(x // cell), int(y // cell)), []).append(idx)
    seen = set()
    comps = []
    for start in occupied:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        cells = []
        while stack:
            c = stack.pop()
            cells.append(c)
            cx, cy = c
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (cx + dx, cy + dy)
                    if nb in occupied and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        idxs = [i for c in cells for i in occupied[c]]
        comps.append(idxs)
    return comps


def assign_zones(plan: dict, per_insert: list, config: dict) -> dict:
    """Pose ins['zone'] sur chaque insert. Retourne {zone: bbox}."""
    live = [(i, ins) for i, ins in enumerate(per_insert) if not ins.get("excluded")]
    if not live:
        return {}
    xs = [ins["pt"][0] for _, ins in live]
    ys = [ins["pt"][1] for _, ins in live]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    cell = span / 24.0  # grossier : les etages sont separes par de grands vides

    comps = _grid_components([ins["pt"] for _, ins in live], cell)

    # zonage significatif seulement : au moins 2 composantes portant chacune >= 10 %
    # des objets (vrai multi-etages). Sinon un plan mono-etage serait fragmente
    # par ses ilots peripheriques (TD, cartouche...).
    big_threshold = max(3, int(0.10 * len(live)))
    significant = [c for c in comps if len(c) >= big_threshold]
    if len(significant) <= 1:
        for _, ins in live:
            ins["zone"] = ""
        return {}

    patterns = [re.compile(p, re.IGNORECASE) for p in config.get("floor_title_patterns") or []]
    titles = []
    for t in plan["texts"]:
        for p in patterns:
            m = p.search(t["text"])
            if m and len(t["text"]) < 60:
                titles.append((t["pt"], m.group(0).upper().replace("  ", " ")))
                break

    zones = {}
    big = sorted(significant, key=len, reverse=True)
    small = [c for c in comps if len(c) < big_threshold]
    for zi, comp in enumerate(big):
        pts = [live[k][1]["pt"] for k in comp]
        bx0, bx1 = min(p[0] for p in pts), max(p[0] for p in pts)
        by0, by1 = min(p[1] for p in pts), max(p[1] for p in pts)
        name = f"ZONE_{zi + 1}"
        best_d = None
        for (tx, ty), label in titles:
            # titre dans ou pres de la bbox
            dx = max(bx0 - tx, 0, tx - bx1)
            dy = max(by0 - ty, 0, ty - by1)
            d = dx + dy
            if d < span / 8 and (best_d is None or d < best_d):
                name, best_d = label, d
        zones[name] = [bx0, by0, bx1, by1]
        for k in comp:
            live[k][1]["zone"] = name
    # petites composantes isolees -> zone la plus proche
    for comp in small:
        for k in comp:
            x, y = live[k][1]["pt"]
            best, best_d = "", None
            for name, (bx0, by0, bx1, by1) in zones.items():
                d = max(bx0 - x, 0, x - bx1) + max(by0 - y, 0, y - by1)
                if best_d is None or d < best_d:
                    best, best_d = name, d
            live[k][1]["zone"] = best
    return zones
