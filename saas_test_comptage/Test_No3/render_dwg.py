"""Methode B : rend une feuille DEPUIS le DWG (repere modele que l'on controle) et
pose les boites exactes autour de chaque symbole. Zero alignement PDF.

- inserts non exclus, restreints aux calques traces dans le PDF de la feuille ;
- chaque symbole est dessine (geometrie du bloc resolu, place a sa position+rotation) ;
- la boite = bbox du bloc a l'echelle du rendu, classe = libelle de legende.

Sortie : SVG/PNG de controle + annotations {image, boxes:[{label, x, y, w, h}]}.
Base du futur dataset COCO (un rendu = une image, une boite = une instance).
"""
from __future__ import annotations

import base64
import html
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

import fitz  # noqa: E402
from takeoff import process_plan  # noqa: E402
from report import _prims_to_svg_elems, _prims_bbox  # noqa: E402
from bench import CONFIG, _pdf_plotted_layers, CACHE  # noqa: E402
from autolabel import PALETTE  # noqa: E402

# classes LINEAIRES (chemins de cable, goulottes...) : pas des symboles ponctuels a
# compter -> exclues (leur bbox est un long segment).
import re as _re  # noqa: E402
LINEAR_RE = _re.compile(r"goulotte|chemin\s*de\s*c|c[aâ]ble|cablage|fourreau|liaison|"
                        r"remont[eé]e|descente", _re.IGNORECASE)
# classes PARASITES : entrees de legende / annotations textuelles, pas des symboles
# a detecter (ex. "LEGENDE ASSERVISSEMENTS"). Exclues du dataset.
PARASITE_RE = _re.compile(r"l[eé]gende|asservissement|\bnota\b|rep[eé]rage|"
                          r"designation|d[eé]signation|cartouche|nomenclature", _re.IGNORECASE)


def _median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else 0.0


def split_floors(centers):
    """Separe les ETAGES dessines cote a cote dans un meme DWG (RDC, R+1...).

    Sans k-means : espacement typique -> composantes connexes. Chaque composante
    significative = un etage. Retourne une liste d'ensembles d'indices, triee du
    plus fourni au moins fourni. Les points isoles lointains (artefacts) tombent
    dans des composantes minuscules ecartees par le seuil.
    """
    n = len(centers)
    if n <= 3:
        return [set(range(n))]
    import random
    rng = random.Random(0)
    sample = centers if n <= 300 else [centers[i] for i in rng.sample(range(n), 300)]
    nn = []
    for a in sample:
        best = None
        for b in centers:
            if a is b:
                continue
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if best is None or d < best:
                best = d
        if best:
            nn.append(best)
    spacing = _median(nn) or 1.0
    eps = spacing * 6.0  # relie les symboles d'un meme etage, coupe entre etages

    cell = eps
    grid = {}
    for i, (x, y) in enumerate(centers):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for (gx, gy), idxs in grid.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    for i in idxs:
                        if math.hypot(centers[i][0] - centers[j][0],
                                      centers[i][1] - centers[j][1]) <= eps:
                            parent[find(i)] = find(j)
    from collections import defaultdict
    groups = defaultdict(set)
    for i in range(n):
        groups[find(i)].add(i)
    comps = sorted(groups.values(), key=len, reverse=True)

    def bbox(idxs):
        xs = [centers[i][0] for i in idxs]
        ys = [centers[i][1] for i in idxs]
        return min(xs), min(ys), max(xs), max(ys)

    def centroid(idxs):
        return (sum(centers[i][0] for i in idxs) / len(idxs),
                sum(centers[i][1] for i in idxs) / len(idxs))

    # FUSION en etages : un etage dense se fragmente (vides internes > eps). On
    # regroupe les fragments PROCHES (meme batiment) et on n'isole comme etage
    # distinct qu'un groupe VRAIMENT eloigne (autre niveau MC2) OU on jette les
    # outliers lointains (points xref a des millions d'unites).
    bx0, by0, bx1, by1 = bbox(comps[0])
    core_diag = math.hypot(bx1 - bx0, by1 - by0) or 1.0
    cc = centroid(comps[0])
    merge_r = max(core_diag * 1.5, eps * 20)

    floors = [set(comps[0])]
    floor_cent = [cc]
    for c in comps[1:]:
        cen = centroid(c)
        # rattache au premier etage assez proche, sinon nouvel etage (si assez gros)
        placed = False
        for fi, fc in enumerate(floor_cent):
            if math.hypot(cen[0] - fc[0], cen[1] - fc[1]) <= merge_r:
                floors[fi] |= c
                placed = True
                break
        if not placed and len(c) >= max(5, int(0.15 * len(comps[0]))):
            floors.append(set(c))
            floor_cent.append(cen)
        # sinon : outlier lointain et petit -> ignore
    return [f for f in floors if len(f) >= 3]


def _prim_points(prims):
    """Points echantillonnes de la geometrie placee (pour l'enveloppe/le masque)."""
    pts = []
    for p in prims:
        if p[0] == "l":
            pts += [p[1], p[2]]
        elif p[0] == "c":
            cx, cy = p[1]
            r = p[2]
            pts += [(cx + r * math.cos(t), cy + r * math.sin(t))
                    for t in [i * math.pi / 4 for i in range(8)]]
        elif p[0] == "a":
            cx, cy = p[1]
            r, a0, a1 = p[2], p[3], p[4]
            if a1 < a0:
                a1 += 2 * math.pi
            n = 6
            pts += [(cx + r * math.cos(a0 + (a1 - a0) * k / n),
                     cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
    return pts


def _convex_hull(points):
    """Enveloppe convexe (monotone chain). Retourne les sommets ordonnes."""
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _rot_translate(prims, pt, ang, scale=(1.0, 1.0)):
    """Place des prims (repere bloc) a la position pt : ECHELLE d'insert puis rotation
    puis translation. Sans l'echelle, les symboles inseres a une echelle != 1
    ressortent a une taille fausse (SSI minuscule, VDI enorme)."""
    ca, sa = math.cos(ang), math.sin(ang)
    ox, oy = pt
    sx, sy = scale
    rs = math.sqrt(abs(sx * sy)) or 1.0  # echelle radiale pour cercles/arcs

    def tf(p):
        x, y = p[0] * sx, p[1] * sy
        return (ox + x * ca - y * sa, oy + x * sa + y * ca)

    out = []
    for p in prims:
        if p[0] == "l":
            out.append(("l", tf(p[1]), tf(p[2])))
        elif p[0] == "c":
            out.append(("c", tf(p[1]), p[2] * rs))
        elif p[0] == "a":
            out.append(("a", tf(p[1]), p[2] * rs, p[3] + ang, p[4] + ang))
    return out


def _resolve_xref_file(xref_path, block_name, dwg_path: Path):
    """Localise le .dwg xref : chemin relatif du DWG, sinon par nom dans 00-xref/."""
    cands = []
    if xref_path:
        p = Path(str(xref_path).replace("\\", "/"))
        cands.append((dwg_path.parent / p).resolve())
        cands.append(dwg_path.parent / p.name)
    # recherche par nom de bloc dans les dossiers xref voisins
    stem = (block_name or "").strip()
    for base in (dwg_path.parent, dwg_path.parent.parent):
        for xdir in base.glob("**/00-xref"):
            cands.append(xdir / f"{stem}.dwg")
    for c in cands:
        if c and c.exists():
            return c
    return None


def load_xref_skeletons(plan, dwg_path: Path):
    """Charge les murs des DWG xref references et les place dans le repere de la feuille."""
    import dwg_reader as dr
    blocks = plan["blocks"]
    extra = []
    for ins in plan["inserts"]:
        b = blocks.get(str(ins["block"]))
        if not b or not b.get("is_xref"):
            continue
        xf = _resolve_xref_file(b.get("xref_path"), b.get("name"), dwg_path)
        if not xf:
            continue
        try:
            xp = dr.extract_plan(xf, cache_dir=CACHE)
        except Exception:
            continue
        sk = xp.get("skeleton") or []
        ox, oy = ins["pt"]
        ang = float(ins.get("rot") or 0.0)
        sx, sy = (ins.get("scale") or [1.0, 1.0])[:2]
        ca, sa = math.cos(ang), math.sin(ang)

        def tf(p):
            x, y = p[0] * sx, p[1] * sy
            return (ox + x * ca - y * sa, oy + x * sa + y * ca)

        for pr in sk:
            if pr[0] == "l":
                extra.append(("l", tf(pr[1]), tf(pr[2])))
            elif pr[0] == "c":
                extra.append(("c", tf(pr[1]), pr[2] * abs(sx)))
            elif pr[0] == "a":
                extra.append(("a", tf(pr[1]), pr[2] * abs(sx), pr[3] + ang, pr[4] + ang))
    return extra


def metier_of_layer(layer: str):
    """Metier top-niveau depuis le nom de calque (INDI-CFO, GI-CFA, 0-FAU-VDI...).
    Retourne CFO/CFA/SSI/CVC/ENEDIS ou None (calque non identifiable -> ignore)."""
    u = (layer or "").upper()
    if "SSI" in u or "INCENDIE" in u or "DESENFUM" in u:
        return "SSI"
    if any(k in u for k in ("CFA", "VDI", "VIDEO", "SONO", "INTRUS", "CONTROLE ACCES", "GI-CFA")):
        return "CFA"
    if "CFO" in u or "ECLAIRAG" in u or "PRISE" in u or "COURANT FORT" in u:
        return "CFO"
    if "CVC" in u or "CLIM" in u:
        return "CVC"
    if "ENEDIS" in u:
        return "ENEDIS"
    return None


def build_sheet(dwg_path: Path, pdf_path: Path | None):
    """-> dict {symbols (avec layer), skeleton feuille+xref, plotted}.
    Si pdf_path est None : pas de filtre 'calques traces' (on garde tous les
    symboles non exclus) -> le tri par metier se fera via le calque en aval."""
    # refresh une fois pour disposer de xref_path/scale dans le cache
    import dwg_reader as dr
    dr.extract_plan(dwg_path, cache_dir=CACHE, refresh=True)
    res = process_plan("ds", dwg_path.stem, dwg_path, CONFIG, cache_dir=CACHE, refresh=False)
    plan = res["_plan"]
    plotted = _pdf_plotted_layers(pdf_path) if pdf_path is not None else None
    label_by_display = {r["display"]: r["label"] for r in res["rows"]}
    blocks_prims = res["blocks_prims"]

    symbols = []
    for ins in res["per_insert"]:
        if ins.get("excluded"):
            continue
        if plotted is not None and (ins.get("layer") or "").strip() not in plotted:
            continue
        disp = ins["display"]
        lbl = label_by_display.get(disp, disp)
        if LINEAR_RE.search(lbl) or LINEAR_RE.search(disp):
            continue  # element lineaire (goulotte/chemin de cable) : non compte
        if PARASITE_RE.search(lbl) or PARASITE_RE.search(disp):
            continue  # entree de legende / annotation textuelle : pas un symbole
        prims = blocks_prims.get(disp) or []
        sc = ins.get("scale") or [1.0, 1.0]
        placed = _rot_translate(prims, ins["pt"], float(ins.get("rot") or 0.0),
                                (sc[0] or 1.0, (sc[1] if len(sc) > 1 else sc[0]) or 1.0))
        bb = _prims_bbox(placed)
        if bb is None:
            # pas de geometrie (bloc vide) : petite boite par defaut autour du point
            x, y = ins["pt"]
            bb = (x - 2, y - 2, x + 2, y + 2)
        symbols.append({"label": label_by_display.get(disp, disp), "display": disp,
                        "prims": placed, "bbox": bb, "pt": ins["pt"],
                        "layer": (ins.get("layer") or "").strip()})
    skeleton = (plan.get("skeleton") or []) + load_xref_skeletons(plan, dwg_path)
    return {"symbols": symbols, "skeleton": skeleton,
            "plotted": sorted(plotted) if plotted is not None else None}


def _render_group(syms, skeleton, width=1800):
    """Rend UN etage (liste de symboles) -> (svg, meta)."""
    xs = [s["bbox"][0] for s in syms] + [s["bbox"][2] for s in syms]
    ys = [s["bbox"][1] for s in syms] + [s["bbox"][3] for s in syms]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    padx, pady = (x1 - x0) * 0.05 + 5, (y1 - y0) * 0.05 + 5
    x0 -= padx; x1 += padx; y0 -= pady; y1 += pady
    spanx, spany = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    height = min(int(width * spany / spanx) or 1, 6000)
    scale = min(width / spanx, height / spany)
    fx = lambda x: (x - x0) * scale
    fy = lambda y: height - (y - y0) * scale

    classes = sorted({s["label"] for s in syms})
    color = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(classes)}

    elems = []
    # murs : squelette clippe a l'etendue de CET etage (contexte du plan)
    sk = []
    for p in skeleton:
        bb = _prims_bbox([p])
        if bb and x0 <= bb[0] <= x1 and y0 <= bb[1] <= y1:
            sk.append(p)
    elems += _prims_to_svg_elems(sk[:20000], fx, fy, "#111", 0.6)
    for s in syms:
        elems += _prims_to_svg_elems(s["prims"], fx, fy, "#000", 1.1)
    boxes = []
    for s in syms:
        bx0, by0, bx1, by1 = s["bbox"]
        X, Y = fx(bx0), fy(by1)
        W, H = fx(bx1) - fx(bx0), fy(by0) - fy(by1)
        # polygone d'instance (masque) : enveloppe convexe de la geometrie, en pixels
        hull = _convex_hull([(fx(px), fy(py)) for px, py in _prim_points(s["prims"])])
        if len(hull) >= 3:
            seg = [round(v, 1) for xy in hull for v in xy]
        else:  # bloc sans geometrie -> masque = la boite
            seg = [X, Y, X + W, Y, X + W, Y + H, X, Y + H]
        boxes.append({"label": s["label"], "x": round(X, 1), "y": round(Y, 1),
                      "w": round(W, 1), "h": round(H, 1), "seg": seg})
        # NE PAS dessiner la boite dans l'image : c'est la VERITE. La dessiner (ancienne
        # version, 2026-07 et avant) fuitait la reponse dans l'image d'entrainement -> le
        # modele apprenait a detecter le rectangle colore, absent du PDF de production ->
        # detections catastrophiques sur PDF propre (diagnostic 2026-07-16). La boite/masque
        # reste UNIQUEMENT en metadonnee (boxes[]), jamais dans les pixels.
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'style="background:#fff">' + "".join(elems) + "</svg>")
    meta = {"width": width, "height": height, "classes": classes,
            "n_boxes": len(boxes), "boxes": boxes, "n_walls": len(sk)}
    return svg, meta


def render_floors(dwg_path: Path, pdf_path: Path, width=1800):
    """Un DWG multi-etages -> une image PAR etage. Retourne liste de (svg, meta)."""
    sheet = build_sheet(dwg_path, pdf_path)
    syms = sheet["symbols"]
    if not syms:
        return [], {"error": "aucun symbole", "plotted": sheet["plotted"]}
    centers = [((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2) for s in syms]
    floors = split_floors(centers)
    out = []
    for fi, idxs in enumerate(floors):
        grp = [syms[i] for i in idxs]
        svg, meta = _render_group(grp, sheet["skeleton"], width)
        meta["floor"] = fi + 1
        out.append((svg, meta))
    return out, {"n_floors": len(floors), "n_symbols_total": len(syms),
                 "plotted": sheet["plotted"]}


def render_floors_by_metier(dwg_path: Path, width=1800):
    """DWG SANS PDF : tri des symboles par metier (via calque) puis rendu par
    (metier, etage). Retourne {metier: [(svg, meta), ...]}."""
    from collections import defaultdict
    sheet = build_sheet(dwg_path, None)
    by_met = defaultdict(list)
    for s in sheet["symbols"]:
        m = metier_of_layer(s["layer"])
        if m:
            by_met[m].append(s)
    result = {}
    for met, msyms in by_met.items():
        if len(msyms) < 3:
            continue
        centers = [((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2)
                   for s in msyms]
        floors = split_floors(centers)
        fout = []
        for fi, idxs in enumerate(floors):
            grp = [msyms[i] for i in idxs]
            svg, meta = _render_group(grp, sheet["skeleton"], width)
            meta["floor"] = fi + 1
            fout.append((svg, meta))
        result[met] = fout
    return result


def svg_to_png(svg: str) -> bytes:
    """Rasterise le SVG a EXACTEMENT sa taille nominale (width/height), sinon fitz
    peut rendre a une echelle differente -> PNG != annotations."""
    tmp = HERE / "out" / "_tmp_render.svg"
    tmp.write_text(svg, encoding="utf-8")
    d = fitz.open(str(tmp))
    page = d[0]
    m = _re.search(r'width="(\d+)"\s+height="(\d+)"', svg)
    if m and page.rect.width and page.rect.height:
        zx = int(m.group(1)) / page.rect.width
        zy = int(m.group(2)) / page.rect.height
        pix = page.get_pixmap(matrix=fitz.Matrix(zx, zy))
    else:
        pix = page.get_pixmap()
    png = pix.tobytes("png")
    d.close()
    return png


if __name__ == "__main__":
    dwg, pdf = Path(sys.argv[1]), Path(sys.argv[2])
    floors, info = render_floors(dwg, pdf)
    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    if not floors:
        print("ECHEC:", info)
    else:
        print(f"{info['n_floors']} etage(s), {info['n_symbols_total']} symboles au total")
        for svg, meta in floors:
            name = f"{pdf.stem}_etage{meta['floor']}.png"
            (outdir / name).write_bytes(svg_to_png(svg))
            print(f"  etage {meta['floor']}: {meta['n_boxes']:>3} boites, {meta['n_walls']:>5} murs, "
                  f"{meta['width']}x{meta['height']}  classes={meta['classes']}")
