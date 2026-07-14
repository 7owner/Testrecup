"""Normalisation des comptages de blocs.

- exclusion des blocs xref / annotation / cartouche (config)
- resolution des blocs anonymes (*U..., A$C...) vers leur jumeau nomme
  par hash geometrique de la definition
- expansion des blocs imbriques (un bloc qui contient N symboles compte N)
"""
from __future__ import annotations

import math
import re
from collections import Counter


def _geo_hash(prims: list) -> str:
    """Empreinte geometrique invariante par translation d'une definition de bloc."""
    if not prims:
        return "empty"
    xs, ys = [], []
    for p in prims:
        kind = p[0]
        if kind == "l":
            xs += [p[1][0], p[2][0]]
            ys += [p[1][1], p[2][1]]
        elif kind in ("c", "a"):
            xs.append(p[1][0])
            ys.append(p[1][1])
    if not xs:
        return "empty"
    x0, y0 = min(xs), min(ys)
    span = max(max(xs) - x0, max(ys) - y0) or 1.0
    sig = []
    for p in prims:
        kind = p[0]
        if kind == "l":
            sig.append((kind,
                        round((p[1][0] - x0) / span, 2), round((p[1][1] - y0) / span, 2),
                        round((p[2][0] - x0) / span, 2), round((p[2][1] - y0) / span, 2)))
        elif kind == "c":
            sig.append((kind, round((p[1][0] - x0) / span, 2), round((p[1][1] - y0) / span, 2),
                        round(p[2] / span, 2)))
        elif kind == "a":
            sig.append((kind, round((p[1][0] - x0) / span, 2), round((p[1][1] - y0) / span, 2),
                        round(p[2] / span, 2), round(p[3], 1), round(p[4], 1)))
    return str(hash(tuple(sorted(sig))))


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns or []]


def _matches(name: str, regexes) -> bool:
    return any(r.search(name) for r in regexes)


def resolve_blocks(plan: dict, config: dict) -> dict:
    """Annule les anonymes, marque les exclusions. Retourne {handle: info_enrichie}."""
    blocks = plan["blocks"]
    excl_block = _compile(config.get("exclude_block_patterns"))

    # jumeaux geometriques : hash -> premier bloc NOMME rencontre
    named_by_hash = {}
    for h, b in blocks.items():
        if not b["anonymous"] and not b["name"].startswith(("*", "A$")) and b["prims"]:
            named_by_hash.setdefault(_geo_hash(b["prims"]), b["name"])

    resolved = {}
    for h, b in blocks.items():
        name = b["name"]
        display = name
        anon = b["anonymous"] or name.startswith(("*", "A$"))
        if anon and b["prims"]:
            twin = named_by_hash.get(_geo_hash(b["prims"]))
            if twin:
                display = twin
        excluded = None
        if b["is_xref"]:
            excluded = "xref"
        elif _matches(display, excl_block):
            excluded = "annotation"
        resolved[h] = {
            **b,
            "display": display,
            "excluded": excluded,
        }
    return resolved


def annotate_inserts(plan: dict, resolved: dict, config: dict) -> list:
    """Annote chaque insert modele-espace (display, excluded).

    NOTE : PAS d'expansion des blocs imbriques. Certains blocs anonymes sont des
    copies completes d'etage (constate sur CROIX ROUGE : A$C763126ac contient tout
    le niveau) -> une expansion doublerait silencieusement le comptage. La legende
    decrit les symboles tels que poses : on compte les INSERTs de premier niveau.
    """
    excl_layer = _compile(config.get("exclude_layer_patterns"))

    per_insert = []
    for ins in plan["inserts"]:
        info = resolved.get(ins["block"])
        if info is None:
            per_insert.append({**ins, "display": f"BLOC_{ins['block']}", "excluded": "inconnu"})
            continue
        excluded = info["excluded"]
        if excluded is None and _matches(ins["layer"], excl_layer):
            excluded = "calque"
        per_insert.append({**ins, "display": info["display"], "excluded": excluded})
    return per_insert
