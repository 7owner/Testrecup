"""Comptage des objets de legende directement depuis un PDF vectoriel (trace AutoCAD).

Principe (deterministe, zero ML) :
1. paths vectoriels avec leur calque (OCG) -> on ne garde que les calques du lot
   (les calques du fond de plan xref contiennent '|', comme dans le DWG) ;
2. clustering spatial des paths en "glyphes" (un symbole = un cluster) ;
3. la legende (ancre texte LEGENDE) fournit les gabarits : cluster + libelle
   (+ quantite declaree si une colonne QTE est imprimee) ;
4. signature de forme invariante par rotation/translation -> comptage des
   occurrences de chaque gabarit dans le plan, hors zone de legende.
"""
from __future__ import annotations

import base64
import html
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz

# paths plus grands que ce diametre (points PDF) = liaisons/architecture, pas des symboles
MAX_SYMBOL_DIAG = 80.0
CLUSTER_EPS = 6.0          # distance (pt) de fusion des paths en glyphe
RADII_BINS = 20            # echantillons de la signature de forme
LEGENDE_WORDS = ("LEGENDE", "LÉGENDE")


# ------------------------------------------------------------------ extraction

def _path_points(d):
    pts = []
    for it in d["items"]:
        op = it[0]
        if op == "l":
            pts += [it[1], it[2]]
        elif op == "c":
            pts += [it[1], it[2], it[3], it[4]]
        elif op == "re":
            r = it[1]
            pts += [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0),
                    fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)]
        elif op == "qu":
            q = it[1]
            pts += [fitz.Point(q.ul), fitz.Point(q.ur), fitz.Point(q.ll), fitz.Point(q.lr)]
    return pts


def _ops_multiset(d):
    return tuple(sorted(Counter(it[0] for it in d["items"]).items()))


def extract_page(page):
    """-> (glyph_clusters, words). Cluster = {bbox, layer, pts, ops, n_paths}.

    Toutes les coordonnees sont ramenees au repere d'AFFICHAGE (page.rect) via
    rotation_matrix : les traces AutoCAD sont souvent tournes (rotation 90/270),
    et get_drawings/get_text renvoient le repere non tourne.
    """
    rot = page.rotation_matrix
    drawings = page.get_drawings()
    # calques du lot = sans '|' (xref). '' (sans calque) garde : cartouche/legende parfois.
    cand = []
    for d in drawings:
        layer = d.get("layer") or ""
        if "|" in layer:
            continue
        r = fitz.Rect(d["rect"]) * rot
        r.normalize()
        if math.hypot(r.width, r.height) > MAX_SYMBOL_DIAG:
            continue
        cand.append({
            "rect": r,
            "layer": layer,
            "pts": [fitz.Point(p) * rot for p in _path_points(d)],
            "ops": Counter(it[0] for it in d["items"]),
        })

    # union-find par proximite de bbox (grille de hachage pour rester O(n))
    parent = list(range(len(cand)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    cell = 12.0
    grid = defaultdict(list)
    for i, d in enumerate(cand):
        r = d["rect"]
        for gx in range(int(r.x0 // cell), int(r.x1 // cell) + 1):
            for gy in range(int(r.y0 // cell), int(r.y1 // cell) + 1):
                grid[(gx, gy)].append(i)
    for bucket in grid.values():
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, b = bucket[i], bucket[j]
                if find(a) == find(b):
                    continue
                if cand[a]["layer"] != cand[b]["layer"]:
                    continue
                ra_, rb_ = cand[a]["rect"], cand[b]["rect"]
                if (ra_ + (-CLUSTER_EPS, -CLUSTER_EPS, CLUSTER_EPS, CLUSTER_EPS)).intersects(rb_):
                    union(a, b)

    groups = defaultdict(list)
    for i in range(len(cand)):
        groups[find(i)].append(i)

    clusters = []
    for idxs in groups.values():
        pts = []
        ops = Counter()
        bbox = None
        layer = cand[idxs[0]]["layer"]
        for i in idxs:
            d = cand[i]
            pts.extend(d["pts"])
            for op, n in d["ops"].items():
                ops[op] += n
            bbox = fitz.Rect(d["rect"]) if bbox is None else bbox | d["rect"]
        if not pts or bbox is None:
            continue
        diag = math.hypot(bbox.width, bbox.height)
        if diag > MAX_SYMBOL_DIAG * 1.6 or diag < 1.0:
            continue
        clusters.append({
            "bbox": [bbox.x0, bbox.y0, bbox.x1, bbox.y1],
            "layer": layer,
            "pts": [(p.x, p.y) for p in pts],
            "ops": tuple(sorted(ops.items())),
            "n_paths": len(idxs),
        })

    words = []
    for w in page.get_text("words"):  # x0,y0,x1,y1,texte,block,line,word
        r = fitz.Rect(w[:4]) * rot
        r.normalize()
        words.append((r.x0, r.y0, r.x1, r.y1, w[4], w[5], w[6], w[7]))
    return clusters, words


# ------------------------------------------------------------------ signature

def _quantiles(radii, norm):
    sig = []
    n = len(radii)
    for k in range(RADII_BINS):
        v = radii[min(int(k * n / RADII_BINS), n - 1)] / (norm or 1.0)
        sig.append(round(v * 20) / 20)
    return tuple(sig)


def signature(cluster):
    """Signature invariante translation+rotation : rayons tries normalises.

    'core' = signature des 60 % de points les plus proches du centre, renormalisee :
    insensible aux appendices fusionnes (cone de visee, amorce de liaison).
    """
    pts = cluster["pts"]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    radii = sorted(math.hypot(p[0] - cx, p[1] - cy) for p in pts)
    rmax = radii[-1] or 1.0
    core = radii[:max(3, int(len(radii) * 0.6))]
    return {"radii": _quantiles(radii, rmax),
            "core": _quantiles(core, core[-1]),
            "rmax": rmax, "ops": cluster["ops"], "n_paths": cluster["n_paths"]}


def match_score(tpl_sig, sig, tol=0.10):
    """Score de correspondance gabarit -> cluster (None = pas de match).

    Invariant d'echelle (l'exemplaire de legende est souvent dessine plus grand
    que les instances) et tolerant a un peu de contexte fusionne dans le cluster
    (fleche de visee, amorce de liaison) : les comptes d'operations du cluster
    peuvent depasser ceux du gabarit de ~70 %, jamais etre nettement inferieurs.
    """
    t_ops = dict(tpl_sig["ops"])
    c_ops = dict(sig["ops"])
    if set(c_ops) != set(t_ops):
        return None
    for op, tn in t_ops.items():
        cn = c_ops.get(op, 0)
        if cn < tn * 0.8 or cn > tn * 1.7 + 2:
            return None
    if sig["n_paths"] < tpl_sig["n_paths"] * 0.8 or sig["n_paths"] > tpl_sig["n_paths"] * 1.9 + 1:
        return None
    diff = sum(abs(x - y) for x, y in zip(tpl_sig["radii"], sig["radii"])) / RADII_BINS
    if diff <= tol:
        return diff + 0.01 * abs(sig["n_paths"] - tpl_sig["n_paths"])
    # cluster avec contexte fusionne : la signature de coeur doit coller
    excess = sig["n_paths"] > tpl_sig["n_paths"]
    if excess:
        core_diff = sum(abs(x - y) for x, y in zip(tpl_sig["core"], sig["core"])) / RADII_BINS
        if core_diff <= 0.08:
            return 0.1 + core_diff + 0.01 * abs(sig["n_paths"] - tpl_sig["n_paths"])
    return None


# ------------------------------------------------------------------ legende

def find_legend_templates(clusters, words, page_rect):
    """Repere l'ancre LEGENDE, associe gabarits/libelles/QTE.

    Retourne (templates, legend_rect) : templates = [{label, qty_declared, cluster}].
    """
    anchors = [w for w in words if any(k in w[4].upper() for k in LEGENDE_WORDS)]
    if not anchors:
        return [], None
    ax0, ay0, ax1, ay1 = anchors[0][:4]
    # ZONE DE RECHERCHE (large) : bande a droite/dessous de l'ancre jusqu'au bord de
    # page. Sert seulement a RASSEMBLER les gabarits/libelles candidats. Le rectangle
    # d'EXCLUSION renvoye au caller est ensuite RESSERRE sur le contenu reellement
    # apparie (voir plus bas) : sinon, quand le titre "LEGENDE" est vers la gauche, la
    # zone engloutit tout le plan a droite et fait disparaitre les symboles a compter.
    lx0 = min(ax0, ax1) - max(160.0, page_rect.width * 0.05)
    search_rect = fitz.Rect(lx0, min(ay0, ay1) - 20, page_rect.x1, page_rect.y1)

    leg_clusters = [c for c in clusters
                    if search_rect.contains(fitz.Point((c["bbox"][0] + c["bbox"][2]) / 2,
                                                       (c["bbox"][1] + c["bbox"][3]) / 2))]
    leg_words = [w for w in words
                 if search_rect.contains(fitz.Point(w[0], w[1])) and w not in anchors]

    # lignes de texte : regrouper les mots par ligne (block,line)
    lines = defaultdict(list)
    for w in leg_words:
        lines[(w[5], w[6])].append(w)
    rows = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws)
        y = sum((w[1] + w[3]) / 2 for w in ws) / len(ws)
        x0 = min(w[0] for w in ws)
        x1 = max(w[2] for w in ws)
        h = max(6.0, sum(abs(w[3] - w[1]) for w in ws) / len(ws))
        rows.append({"text": text.strip(), "y": y, "x0": x0, "x1": x1, "h": h})

    # colonnes QTE : lignes purement numeriques, appariees par alignement vertical
    qty_rows = [r for r in rows if re.fullmatch(r"\d{1,4}", r["text"])]
    label_rows = [r for r in rows if r not in qty_rows]

    def credible(c):
        return not (c["n_paths"] < 2 and sum(n for _, n in c["ops"]) < 3)

    templates = []
    used = set()
    bad_label = re.compile(r"^(ECHELLE|DATE|IND\b|DESIGNATION|DESSINATEUR|OPERATION|NIVEAU|PLAN\b|PLA\b|FAU-"
                           r"|ADRESSE|TEL[. ]|FAX|MAIRIE|AGENCE|LOT\b|DOE\b|EXE\b|DCE\b)",
                           re.IGNORECASE)
    for row in label_rows:
        label = row["text"]
        if len(label) < 4 or label.upper() in ("QTE", "QUANTITE", "QUANTITES"):
            continue
        if bad_label.search(label):
            continue
        # QTE : uniquement depuis une colonne numerique alignee (jamais un nombre du
        # libelle : "Spot L-RDC-25" -> le 25 fait partie du nom, pas une quantite).
        qty = None
        qty_row = None
        for q in qty_rows:
            if abs(q["y"] - row["y"]) < 8 and q["x0"] > row["x0"]:
                qty = int(q["text"])
                qty_row = q
                break
        # candidats : glyphes credibles de la ligne, a gauche du libelle
        row_h = row["h"]
        band = max(row_h * 1.6, 12.0)
        cand = []
        for ci, c in enumerate(leg_clusters):
            if ci in used:
                continue
            cy = (c["bbox"][1] + c["bbox"][3]) / 2
            gh = c["bbox"][3] - c["bbox"][1]
            if (abs(cy - row["y"]) < max(band, gh * 0.8)
                    and c["bbox"][2] <= row["x0"] + 4
                    and c["bbox"][0] >= row["x0"] - 22 * row_h
                    and credible(c)):
                cand.append(c)
        if not cand:
            continue
        # primaire = glyphe le plus proche du libelle ; variantes = glyphes
        # CONTIGUS et de TAILLE COMPARABLE (ex. RJ45 = 3 carres cote a cote sous un
        # seul libelle). On s'arrete au premier grand trou pour ne pas happer un
        # symbole decoratif eloigne (evite les faux positifs type "Cable XLR").
        cand.sort(key=lambda c: -c["bbox"][2])  # du plus proche du libelle vers la gauche
        def diag(c):
            return math.hypot(c["bbox"][2] - c["bbox"][0], c["bbox"][3] - c["bbox"][1])
        primary = cand[0]
        pdiag = diag(primary) or 1.0
        chosen = [primary]
        left_edge = primary["bbox"][0]
        for c in cand[1:]:
            gap = left_edge - c["bbox"][2]
            if gap > pdiag * 2.0:
                break
            if 0.4 * pdiag <= diag(c) <= 2.5 * pdiag:
                chosen.append(c)
                left_edge = min(left_edge, c["bbox"][0])
        for c in chosen:
            used.add(leg_clusters.index(c))
        templates.append({"label": label, "qty_declared": qty,
                          "cluster": primary, "variants": chosen,
                          "row": row, "qty_row": qty_row})

    # rectangle d'EXCLUSION resserre : borne le contenu legende reellement apparie
    # (titre + libelles + glyphes + colonne QTE), avec une marge. Evite de masquer le
    # plan quand le titre est loin du bord. Sans template credible -> aucune exclusion.
    if not templates:
        return templates, None
    boxes = [tuple(anchors[0][:4])]
    for t in templates:
        r = t["row"]
        boxes.append((r["x0"], r["y"] - r["h"], r["x1"], r["y"] + r["h"]))
        for c in t["variants"]:
            boxes.append(tuple(c["bbox"]))
        q = t.get("qty_row")
        if q:
            boxes.append((q["x0"], q["y"] - q["h"], q["x1"], q["y"] + q["h"]))
    pad = 10.0
    legend_rect = fitz.Rect(min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
                            max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)
    legend_rect &= page_rect

    # GARDE DE CREDIBILITE : une vraie legende est une table compacte (colonne de lignes
    # alignees). Si "LEGENDE" est en fait un champ de CARTOUCHE sans table, l'appariement
    # happe des annotations du plan (baby-foot, casiers, Elec...) etalees sur toute la
    # feuille. Symptomes : rectangle couvrant une grande part de page ET libelles repartis
    # sur de nombreuses colonnes x. Dans ce cas -> pas de legende exploitable, aucune
    # exclusion (mieux vaut un leger sur-comptage que faire disparaitre le plan).
    area_frac = (legend_rect.width * legend_rect.height) / max(page_rect.width * page_rect.height, 1.0)
    x_cols = len({int(t["row"]["x0"] // 100) for t in templates})
    if area_frac > 0.25 and x_cols > 4:
        return [], None
    return templates, legend_rect


# ------------------------------------------------------------------ comptage

def count_pdf(pdf_path: Path) -> dict:
    doc = fitz.open(pdf_path)
    all_rows = []
    overlays = []
    warnings = []
    thumbs = {}
    for pno, page in enumerate(doc):
        clusters, words = extract_page(page)
        templates, legend_rect = find_legend_templates(clusters, words, page.rect)
        if not templates:
            warnings.append(f"page {pno + 1} : pas de legende exploitable "
                            f"({len(clusters)} glyphes detectes)")
            continue
        # vignettes : extrait du PDF autour du gabarit de legende
        for t in templates:
            if t["label"] in thumbs:
                continue
            bb = fitz.Rect(t["cluster"]["bbox"]) + (-3, -3, 3, 3)
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=bb * ~page.rotation_matrix)
                thumbs[t["label"]] = base64.b64encode(pix.tobytes("png")).decode("ascii")
            except Exception:
                pass
        # signatures des variantes + calques par gabarit
        for t in templates:
            vs = t.get("variants") or [t["cluster"]]
            t["_sigs"] = [signature(v) for v in vs]
            t["_layers"] = {v["layer"] for v in vs}
        # garde de calque adaptative : on n'exige l'appartenance aux calques du gabarit
        # que si ces calques sont vraiment utilises dans le plan (sinon la legende vit
        # sur son propre calque, ex. FAU LEGENDE, et la garde tuerait tous les matchs).
        plan_layer_counts = Counter()
        for c in clusters:
            cx = (c["bbox"][0] + c["bbox"][2]) / 2
            cy = (c["bbox"][1] + c["bbox"][3]) / 2
            if not (legend_rect and legend_rect.contains(fitz.Point(cx, cy))):
                plan_layer_counts[c["layer"]] += 1
        enforce_layer = [sum(plan_layer_counts.get(l, 0) for l in t["_layers"]) >= 5
                         for t in templates]
        # affectation : chaque cluster du plan va au MEILLEUR gabarit (pas de double compte)
        assigned = [[] for _ in templates]
        for c in clusters:
            cx = (c["bbox"][0] + c["bbox"][2]) / 2
            cy = (c["bbox"][1] + c["bbox"][3]) / 2
            if legend_rect and legend_rect.contains(fitz.Point(cx, cy)):
                continue
            s = signature(c)
            best_ti, best_score = None, None
            for ti, t in enumerate(templates):
                if enforce_layer[ti] and c["layer"] and c["layer"] not in t["_layers"]:
                    continue
                for vsig in t["_sigs"]:
                    score = match_score(vsig, s)
                    if score is not None and (best_score is None or score < best_score):
                        best_ti, best_score = ti, score
            if best_ti is not None:
                assigned[best_ti].append((cx, cy))
        marks = []
        for ti, t in enumerate(templates):
            hits = assigned[ti]
            q = t["qty_declared"]
            n = len(hits)
            # confiance : compare a la QTE imprimee quand elle existe (peut etre un
            # total projet, donc "diff" != forcement faux, mais a verifier).
            if q is None:
                conf = "estim"
            elif q == n:
                conf = "match"
            else:
                conf = "diff"
            all_rows.append({
                "zone": f"page {pno + 1}" if len(doc) > 1 else "",
                "display": t["label"],
                "label": t["label"],
                "layer": t["cluster"]["layer"] or "-",
                "count": n,
                "qty_declared": q,
                "conf": conf,
            })
            marks.append({"label": t["label"], "hits": hits})
        overlays.append({"page": pno, "marks": marks, "legend_rect": list(legend_rect) if legend_rect else None})
    doc.close()
    return {"rows": all_rows, "overlays": overlays, "warnings": warnings, "thumbs": thumbs}


# ------------------------------------------------------------------ overlay SVG

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
           "#f032e6", "#bfef45", "#469990", "#9a6324", "#800000", "#808000"]


def overlay_svg_pdf(pdf_path: Path, overlay: dict, dpi=110) -> str:
    doc = fitz.open(pdf_path)
    page = doc[overlay["page"]]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
    w, h = pix.width, pix.height
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">',
             f'<image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>']
    for mi, m in enumerate(overlay["marks"]):
        col = PALETTE[mi % len(PALETTE)]
        for (x, y) in m["hits"]:
            parts.append(f'<circle cx="{x * zoom:.0f}" cy="{y * zoom:.0f}" r="9" fill="none" '
                         f'stroke="{col}" stroke-width="2.5">'
                         f'<title>{html.escape(m["label"])}</title></circle>')
    parts.append("</svg>")
    doc.close()
    return "".join(parts)
