"""Extraction de la legende (modele-espace OU paper space).

Heuristique : ancre TEXT "LEGENDE" -> les TEXT en dessous dans la meme colonne
sont les libelles ; l'INSERT le plus proche a gauche de chaque libelle est le
symbole de la ligne. Donne :
- le mapping display_bloc -> libelle legende (pour le rapport) ;
- les indices des inserts modele-espace en zone legende, a exclure du comptage
  (les exemplaires paper space ne sont jamais comptes, rien a exclure pour eux).
"""
from __future__ import annotations

import re

# libelles invalides : titres d'etage, indices, textes trop courts
_BAD_LABEL = re.compile(
    r"^(RDC|RDJ|R\s*[+-]\s*\d+|NIVEAU\s*\d+|SOUS[- ]SOL.*|COMBLES|TOIT(URE)?|ECHELLE.*|IND[. ].*|\d+([.,]\d+)?)$",
    re.IGNORECASE)


def _valid_label(label: str) -> bool:
    label = label.strip()
    return len(label) >= 3 and not _BAD_LABEL.match(label)


def _candidate_rows(anchor, texts):
    ax, ay = anchor["pt"]
    h = anchor.get("h") or 1.0
    return [t for t in texts
            if t is not anchor
            and t["pt"][1] < ay
            and ay - t["pt"][1] < h * 120
            and -h * 10 < t["pt"][0] - ax < h * 80
            and len(t["text"].strip()) > 1]


def detect_legend_columns(plan: dict, per_insert: list):
    """Detecte les colonnes de legende/nomenclature dessinees dans le modele-espace
    (constate sur CROIX ROUGE : bandes verticales d'exemplaires, sans titre LEGENDE).

    Critere structurel : composante spatiale etroite (h/l >= 3), >= 8 inserts,
    forte proportion de blocs distincts (>= 0.5). Retourne (label_by_display, ids).
    """
    from zones import _grid_components

    live = [(i, ins) for i, ins in enumerate(per_insert) if not ins.get("excluded")]
    if len(live) < 12:
        return {}, set()
    xs = [ins["pt"][0] for _, ins in live]
    ys = [ins["pt"][1] for _, ins in live]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0

    label_by_display: dict[str, str] = {}
    legend_ids: set[int] = set()
    ms_texts = [t for t in plan["texts"] if t.get("space") == "ms"]

    # multi-echelle : a maille grossiere une colonne collee a un etage fusionne
    # avec lui (constate sur MC2) ; les mailles fines la separent.
    comps = []
    for div in (24.0, 48.0, 96.0):
        comps.extend(_grid_components([ins["pt"] for _, ins in live], span / div))

    for comp in comps:
        if len(comp) < 8 or len(comp) > 0.5 * len(live):
            continue
        pts = [live[k][1]["pt"] for k in comp]
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        if w <= 0 or h / w < 3:
            continue
        distinct = len({live[k][1]["display"] for k in comp}) / len(comp)
        if distinct < 0.5:
            continue
        # passe 1 : apparier les libelles ; passe 2 : n'exclure que si la colonne
        # ressemble vraiment a une legende (>= 50 % des lignes ont un libelle texte).
        # Evite d'exclure a tort les colonnes de gaines/synoptiques (sans textes en rangee).
        row_h = h / max(len(comp) - 1, 1)
        pairings = []
        for k in comp:
            i, ins = live[k]
            px, py = ins["pt"]
            best, best_d = None, None
            for t in ms_texts:
                tx, ty = t["pt"]
                if abs(ty - py) < row_h * 0.7 and 0 < tx - px < w + row_h * 30:
                    d = (tx - px) + abs(ty - py) * 2
                    if best_d is None or d < best_d:
                        best, best_d = t, d
            label = None
            if best is not None:
                cand = re.sub(r"\s+", " ", best["text"]).strip()
                if _valid_label(cand):
                    label = cand
            pairings.append((i, ins, label))
        labeled = sum(1 for _, _, lab in pairings if lab)
        if labeled < 0.5 * len(pairings):
            continue
        for i, ins, lab in pairings:
            legend_ids.add(i)
            if lab:
                label_by_display.setdefault(ins["display"], lab)
    return label_by_display, legend_ids


def find_legend(plan: dict, per_insert: list, resolved: dict, config: dict):
    """Retourne (label_by_display, ms_legend_ids)."""
    words = [w.upper() for w in config.get("legend_anchor_words") or ["LEGENDE"]]
    anchors = [t for t in plan["texts"]
               if any(w in t["text"].upper() for w in words) and len(t["text"]) < 30]

    label_by_display: dict[str, str] = {}
    ms_legend_ids: set[int] = set()

    # candidats : inserts du meme espace que l'ancre
    ms_cands = [(i, ins) for i, ins in enumerate(per_insert)]
    ps_cands = []
    for ins in plan.get("ps_inserts") or []:
        info = resolved.get(ins["block"])
        display = info["display"] if info else f"BLOC_{ins['block']}"
        ps_cands.append((None, {**ins, "display": display}))

    for anchor in anchors:
        same_space = [t for t in plan["texts"] if t.get("space") == anchor.get("space")]
        cands = ps_cands if anchor.get("space") == "ps" else ms_cands
        for t in _candidate_rows(anchor, same_space):
            tx, ty = t["pt"]
            th = t.get("h") or (anchor.get("h") or 1.0)
            best, best_d = None, None
            for i, ins in cands:
                px, py = ins["pt"]
                if abs(py - ty) < th * 3 and 0 < tx - px < th * 25:
                    d = (tx - px) + abs(py - ty)
                    if best_d is None or d < best_d:
                        best, best_d = (i, ins), d
            if best is None:
                continue
            i, ins = best
            label = re.sub(r"\s+", " ", t["text"]).strip()
            if not _valid_label(label):
                continue
            label_by_display.setdefault(ins["display"], label)
            if i is not None:  # insert modele-espace -> exemplaire de legende a exclure
                ms_legend_ids.add(i)

    # Cas frequent : la legende est un BLOC (textes + exemplaires dans la definition).
    for h, b in plan["blocks"].items():
        texts = b.get("def_texts") or []
        nested = b.get("nested") or []
        if len(texts) < 3 or len(nested) < 3:
            continue
        name_hit = any(w in b["name"].upper() for w in words)
        anchor_hit = any(any(w in t["text"].upper() for w in words) for t in texts)
        if not (name_hit or anchor_hit):
            continue
        heights = sorted(t["h"] for t in texts if t.get("h"))
        med_h = heights[len(heights) // 2] if heights else 1.0
        for t in texts:
            if len(t["text"].strip()) < 2:
                continue
            tx, ty = t["pt"]
            th = t.get("h") or med_h
            best, best_d = None, None
            for n in nested:
                px, py = n["pt"]
                if abs(py - ty) < th * 3 and 0 < tx - px < th * 30:
                    d = (tx - px) + abs(py - ty)
                    if best_d is None or d < best_d:
                        best, best_d = n, d
            if best is None:
                continue
            info = resolved.get(best["block"])
            display = info["display"] if info else f"BLOC_{best['block']}"
            label = re.sub(r"\s+", " ", t["text"]).strip()
            if not _valid_label(label):
                continue
            label_by_display.setdefault(display, label)

    return label_by_display, ms_legend_ids
