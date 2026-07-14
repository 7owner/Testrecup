"""Lecture DWG via LibreDWG (dwgread -O JSON) -> structure compacte pour le comptage.

Aucune inference : on lit la base de donnees du DWG (INSERTs = symboles poses).
Cache disque : le JSON LibreDWG est lourd (des centaines de Mo sur les gros DWG),
on ne garde que la structure compacte, indexee par hash (chemin, taille, mtime).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).parent / "tools" / "libredwg"
DWGREAD = TOOLS_DIR / "dwgread.exe"
DWG2DXF = TOOLS_DIR / "dwg2dxf.exe"

# LibreDWG emet des nan/inf nus, invalides en JSON
_BAD_NUM = re.compile(r"(?<=[:,\[\s])-?(?:nan|inf|1\.#IND0*|1\.#INF0*)(?=[,\]\s}])")


def habs(h):
    """Handle LibreDWG = [code, size, value(, absolue)] -> reference absolue."""
    if isinstance(h, list) and h:
        return h[-1]
    return h


def _cache_key(dwg_path: Path) -> str:
    st = dwg_path.stat()
    raw = f"{dwg_path.resolve()}|{st.st_size}|{st.st_mtime_ns}|v5"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


_MTEXT_CODES = re.compile(r"\\[A-Za-z][^;\\{}]*;|[{}]|\\\\|\\~")


def clean_mtext(s: str) -> str:
    """Retire les codes de formatage MTEXT (\\pxqc;, {\\f...;}, \\P...)."""
    s = s.replace("\\P", " ")
    return _MTEXT_CODES.sub("", s).strip()


def _run_dwgread(dwg_path: Path) -> dict:
    """dwgread -O JSON vers un fichier temporaire (stdout trop lourd sur les gros DWG)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        proc = subprocess.run(
            [str(DWGREAD), "-O", "JSON", "-o", str(tmp), str(dwg_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=1800,
        )
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"dwgread sans sortie (exit {proc.returncode}): {proc.stderr[:400]}")
        raw = tmp.read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    raw = _BAD_NUM.sub("null", raw)
    return json.loads(raw)


def _pt2(p):
    if isinstance(p, list) and len(p) >= 2 and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float)):
        return [float(p[0]), float(p[1])]
    return None


def _entity_prims(obj: dict) -> list:
    """Entite -> primitives dessinables [(kind, data...)] pour vignettes/overlay/geo-hash."""
    t = (obj.get("entity") or "").upper()
    prims = []
    if t == "LINE":
        a = _pt2(obj.get("start") or obj.get("start_pt"))
        b = _pt2(obj.get("end") or obj.get("end_pt"))
        if a and b:
            prims.append(("l", a, b))
    elif t == "LWPOLYLINE":
        pts = [q for q in (_pt2(p) for p in obj.get("points") or []) if q]
        for a, b in zip(pts, pts[1:]):
            prims.append(("l", a, b))
        if obj.get("flag") and (obj["flag"] & 512 or obj["flag"] & 1) and len(pts) > 2:
            prims.append(("l", pts[-1], pts[0]))
    elif t in ("CIRCLE", "ARC"):
        c = _pt2(obj.get("center"))
        r = obj.get("radius")
        if c and isinstance(r, (int, float)):
            if t == "CIRCLE":
                prims.append(("c", c, float(r)))
            else:
                prims.append(("a", c, float(r),
                              float(obj.get("start_angle") or 0.0),
                              float(obj.get("end_angle") or 0.0)))
    elif t in ("SOLID", "TRACE"):
        pts = [q for q in (_pt2(obj.get(k)) for k in ("corner1", "corner2", "corner3", "corner4")) if q]
        for a, b in zip(pts, pts[1:]):
            prims.append(("l", a, b))
    elif t == "ELLIPSE":
        c = _pt2(obj.get("center"))
        ax = _pt2(obj.get("sm_axis"))
        if c and ax:
            r = math.hypot(ax[0], ax[1])
            prims.append(("c", c, r))
    elif t == "POLYLINE_2D":
        pass  # vertices en entites separees, ignore (rare dans les blocs symboles)
    return prims


def extract_plan(dwg_path: Path, cache_dir: Path | None = None, refresh: bool = False) -> dict:
    """DWG -> structure compacte {blocks, layers, inserts, texts, skeleton, source}."""
    dwg_path = Path(dwg_path)
    cache_file = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{_cache_key(dwg_path)}.json"
        if cache_file.exists() and not refresh:
            return json.loads(cache_file.read_text(encoding="utf-8"))

    data = _run_dwgread(dwg_path)
    objs = data.get("OBJECTS", [])

    by_handle = {}
    for o in objs:
        h = habs(o.get("handle"))
        if h is not None:
            by_handle[h] = o

    layers = {}
    for o in objs:
        if o.get("object") == "LAYER":
            layers[habs(o.get("handle"))] = o.get("name") or "?"

    blocks = {}
    for o in objs:
        if o.get("object") == "BLOCK_HEADER":
            h = habs(o.get("handle"))
            name = o.get("name") or f"BLOC_{h}"
            ent_handles = [habs(e) for e in (o.get("entities") or [])]
            prims = []
            nested = []     # inserts imbriques dans la definition (avec position locale)
            def_texts = []  # textes de la definition (legendes en bloc)
            for eh in ent_handles:
                e = by_handle.get(eh)
                if not e:
                    continue
                et = (e.get("entity") or "").upper()
                if et == "INSERT":
                    npt = _pt2(e.get("ins_pt"))
                    nested.append({"block": str(habs(e.get("block_header"))),
                                   "pt": npt or [0.0, 0.0]})
                elif et in ("TEXT", "MTEXT"):
                    tpt = _pt2(e.get("ins_pt") or e.get("insertion_pt"))
                    tval = e.get("text_value") if et == "TEXT" else e.get("text")
                    if tpt and tval:
                        tval = clean_mtext(str(tval)) if et == "MTEXT" else str(tval)
                        if tval:
                            def_texts.append({"pt": tpt, "text": tval,
                                              "h": float(e.get("height") or e.get("text_height") or 0.0)})
                else:
                    prims.extend(_entity_prims(e))
            blocks[str(h)] = {
                "name": name,
                "anonymous": bool(o.get("anonymous")),
                "is_xref": bool(o.get("blkisxref")) or "|" in name,
                "xref_path": o.get("xref_pname") or o.get("pathname") or None,
                "prims": prims[:400],
                "nested": nested[:600],
                "def_texts": def_texts[:600],
            }

    inserts = []      # modele-espace : la matiere du comptage
    ps_inserts = []   # paper space : exemplaires de legende, jamais comptes
    texts = []        # modele + paper space (marques "space")
    attribs = []      # attributs de blocs (tags SR0.1A... : ancres d'alignement)
    skeleton = []
    for o in objs:
        t = (o.get("entity") or "").upper()
        if not t:
            continue
        entmode = o.get("entmode")  # 2 = modele-espace, 1 = paper space, 0 = def de bloc
        if t == "INSERT":
            if entmode not in (1, 2):
                continue
            pt = _pt2(o.get("ins_pt"))
            if pt is None:
                continue
            sc = o.get("scale") or [1.0, 1.0, 1.0]
            rec = {
                "block": str(habs(o.get("block_header"))),
                "layer": layers.get(habs(o.get("layer")), "?"),
                "pt": pt,
                "rot": float(o.get("rotation") or 0.0),
                "scale": [float(sc[0]) if sc else 1.0, float(sc[1]) if len(sc) > 1 else 1.0],
            }
            (inserts if entmode == 2 else ps_inserts).append(rec)
        elif t in ("TEXT", "MTEXT"):
            if entmode not in (1, 2):
                continue
            pt = _pt2(o.get("ins_pt") or o.get("insertion_pt"))
            val = o.get("text_value") if t == "TEXT" else o.get("text")
            if pt is None or not val:
                continue
            val = clean_mtext(str(val)) if t == "MTEXT" else str(val)
            if not val:
                continue
            texts.append({
                "pt": pt,
                "text": val,
                "h": float(o.get("height") or o.get("text_height") or 0.0),
                "layer": layers.get(habs(o.get("layer")), "?"),
                "space": "ms" if entmode == 2 else "ps",
            })
        elif t == "ATTRIB":
            pt = _pt2(o.get("ins_pt") or o.get("insertion_pt"))
            val = o.get("text_value") or o.get("text")
            if pt is None or not val:
                continue
            attribs.append({
                "pt": pt,
                "tag": str(o.get("tag") or "").strip(),
                "text": clean_mtext(str(val)).strip(),
                "space": "ms" if entmode == 2 else ("ps" if entmode == 1 else "def"),
            })
        elif t in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE"):
            if entmode != 2:
                continue
            if len(skeleton) < 30000:
                skeleton.extend(_entity_prims(o))

    plan = {
        "source": str(dwg_path),
        "layers": sorted(set(layers.values())),
        "blocks": blocks,
        "inserts": inserts,
        "ps_inserts": ps_inserts,
        "texts": texts,
        "attribs": attribs,
        "skeleton": skeleton[:30000],
    }
    if cache_file is not None:
        cache_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return plan


if __name__ == "__main__":
    p = extract_plan(Path(sys.argv[1]))
    print(json.dumps({
        "source": p["source"],
        "n_blocks": len(p["blocks"]),
        "n_inserts": len(p["inserts"]),
        "n_texts": len(p["texts"]),
        "n_skeleton": len(p["skeleton"]),
    }, indent=2, ensure_ascii=False))
