"""Lecture de la LEGENDE d'un PDF vectoriel, par detection des colonnes alignees.

Pourquoi un nouveau module plutot qu'un correctif de plan_takeoff : celui-ci sert de ligne
de base a bench.py ("methode actuelle"), on n'y touche pas. Seul extract_page est importe.

Pourquoi une nouvelle detection : pdf_takeoff.find_legend_templates() prend une bande allant
de l'ancre LEGENDE jusqu'aux bords de la page. Mesure du 2026-07-13 sur le plan VDI de BPCE
(page 2384x1684) : legend_rect = Rect(524, 1.7, 2384, 1684), soit 78 % de la feuille. Elle
sort 130 "entrees" pour ~25 vraies -- noms de locaux, surfaces, effectifs, et jusqu'au nom
de la rue ("B o u l e v a r d d e D U N K E R Q U E").

Ici on ne cherche pas une bande, on cherche la STRUCTURE : une legende est un tableau de
lignes alignees a gauche, a pas vertical regulier, en bande verticale. Rien d'autre sur la
feuille n'a cette forme. C'est la transposition au PDF du critere que
plan_takeoff/legend_extract.py::detect_legend_columns() applique deja cote DWG.

CONTRAT DE SORTIE -- lire avant d'utiliser `glyph_bbox` :

    Entry = {"label": str, "canon": str | None, "glyph_bbox": [x0,y0,x1,y1] | None,
             "variants": [cluster], "qty_declared": int | None, "column": int}

`glyph_bbox` peut valoir None. Etre dans une colonne de legende validee PROUVE qu'on est une
entree ; le gabarit est un bonus, pas une condition d'existence. Une entree sans gabarit sort
quand meme, et un warning la NOMME -- elle ne disparait jamais en silence. C'est le meme
principe que canon(strict=True) : signaler plutot que masquer.

Pourquoi une entree peut n'avoir aucun gabarit : extract_page fusionne parfois plusieurs
symboles de legende verticalement voisins en UN seul cluster (mesure sur le plan VDI de BPCE :
cluster #1336 haut de 38 pt, #1363 de 52 pt, #1390 de 55 pt, pour des lignes espacees de
~14 pt). Un tel cluster est candidat pour 3 a 6 lignes d'affilee ; une seule peut l'obtenir.
Les autres lignes sont de vraies entrees, sans gabarit propre : on les sort et on le dit.
(Avant le correctif du 2026-07-14, elles etaient jetees en silence -- 16 entrees perdues sur
36, soit 44 % de la legende.)
"""
from __future__ import annotations

import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import fitz

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "plan_takeoff"))

from canonical import canon        # noqa: E402
from pdf_takeoff import extract_page  # noqa: E402

# --- constantes de detection. Valeurs de depart, a regler sur score_legend.py ---
TOL_X = 1.0             # alignement des libelles, en hauteurs de ligne
PITCH_LO = 0.6          # pas vertical admis, en fraction du pas median de la colonne
PITCH_HI = 1.6
MIN_ROWS = 4            # colonne SANS ancre : au moins 4 lignes (la structure doit parler seule)
MIN_ASPECT = 3.0        # hauteur / largeur : une colonne est une bande VERTICALE
MIN_GLYPH_RATIO = 0.6   # part des lignes qui doivent porter un glyphe
CONT_PITCH = 0.6        # sous cette fraction du pas median, la ligne est une CONTINUATION
                        # du libelle precedent, pas une entree (cf. _merge_continuations)

# --- ancre. Mesure du 2026-07-14 : les legendes ROI RENE ne font que 2 a 6 entrees
# ("LEGENDE VIDEOSURVEILLANCE" + "Camera Dome" + "Camera dome double objectif"), la ou celle
# de BPCE en a une trentaine. Sur 2 lignes, la STRUCTURE ne dit rien : c'est le titre qui
# porte l'information. Les seuils structurels (MIN_ROWS, MIN_ASPECT) rejetaient ces legendes
# en bloc -> 6 plans sur 12 rendaient ZERO entree au banc.
#
# L'ancre n'est donc PAS une zone (l'erreur de find_legend_templates, qui prenait une bande
# jusqu'aux bords de page). C'est un signal qui ASSOUPLIT les seuils d'une colonne deja
# reperee par alignement. Une colonne sans ancre doit toujours prouver sa structure seule
# -- BPCE n'a pas d'ancre exploitable et marche tres bien comme ca.
MIN_ROWS_ANCHORED = 2       # sous une ancre, 2 lignes suffisent
MIN_GLYPH_RATIO_ANCHORED = 0.5
ANCHOR_GAP = 8.0            # l'ancre est au-dessus de la 1re ligne, a <= 8 hauteurs de ligne
ANCHOR_X_TOL = 30.0         # ... et a <= 30 hauteurs de ligne du bord gauche de la colonne

_NUM = re.compile(r"^\d{1,4}$")
_ANCHOR = re.compile(r"^\s*(l.gendes?|symboles?|nomenclature)\b", re.IGNORECASE)
_BAD_LABEL = re.compile(
    r"^(ECHELLE|DATE|IND\b|DESIGNATION|DESSINATEUR|OPERATION|NIVEAU|PLAN\b|PLA\b|FAU-"
    r"|ADRESSE|TEL[. ]|FAX|MAIRIE|AGENCE|LOT\b|DOE\b|EXE\b|DCE\b"
    r"|QTE|QUANTITES?|LEGENDE|L.GENDE|SYMBOLES?)",
    re.IGNORECASE)


# ---------------------------------------------------------------- lignes de texte

def _rows_from_words(words):
    """Mots PyMuPDF -> (lignes de libelle, lignes numeriques, ancres).

    Une ligne = un couple (block, line) de PyMuPDF.

    - Les lignes numeriques sont mises de cote : elles ne deviennent une quantite que si
      elles forment une VRAIE colonne QTE (cf. _qty_column) -- sinon ce sont des nombres
      du plan.
    - Les titres de legende ("LEGENDE VIDEOSURVEILLANCE", "LEGENDES", "SYMBOLES") ne sont
      pas des entrees (_BAD_LABEL les ecarte deja) mais ce sont des ANCRES : ils assouplissent
      les seuils de la colonne qu'ils surplombent (cf. _anchored).
    """
    grouped = defaultdict(list)
    for w in words:
        grouped[(w[5], w[6])].append(w)

    labels, qtys, anchors = [], [], []
    for ws in grouped.values():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws).strip()
        if not text:
            continue
        row = {
            "text": text,
            "y": sum((w[1] + w[3]) / 2 for w in ws) / len(ws),
            "x0": min(w[0] for w in ws),
            "h": max(6.0, sum(abs(w[3] - w[1]) for w in ws) / len(ws)),
        }
        if _ANCHOR.match(text):
            anchors.append(row)
        elif _NUM.fullmatch(text):
            qtys.append(row)
        elif len(text) >= 3 and not _BAD_LABEL.search(text):
            labels.append(row)
    return labels, qtys, anchors


# ---------------------------------------------------------------- glyphes

def _credible(c):
    """Un trait isole n'est pas un symbole."""
    return not (c["n_paths"] < 2 and sum(n for _, n in c["ops"]) < 3)


def _diag(c):
    b = c["bbox"]
    return math.hypot(b[2] - b[0], b[3] - b[1])


def _candidates(row, clusters, used):
    """Glyphes admissibles pour un libelle : credibles, A GAUCHE, dans la bande verticale."""
    band = max(row["h"] * 1.6, 12.0)
    cand = []
    for ci, c in enumerate(clusters):
        if ci in used:
            continue
        b = c["bbox"]
        cy = (b[1] + b[3]) / 2
        gh = b[3] - b[1]
        if (abs(cy - row["y"]) < max(band, gh * 0.8)
                and b[2] <= row["x0"] + 4
                and b[0] >= row["x0"] - 22 * row["h"]
                and _credible(c)):
            cand.append((ci, c))
    return cand


def _expand_variants(primary, cand):
    """Variantes contigues autour du glyphe principal.

    Plusieurs glyphes contigus de taille comparable sous un seul libelle (ex. RJ45 = 3 carres
    cote a cote). On s'arrete au premier grand trou pour ne pas happer un symbole decoratif
    eloigne. Logique reprise telle quelle de pdf_takeoff (elle est correcte -- c'est la ZONE
    qui etait fausse, pas l'appariement).
    """
    others = sorted((ic for ic in cand if ic[0] != primary[0]),
                    key=lambda ic: -ic[1]["bbox"][2])   # du plus proche du libelle, vers la gauche
    pdiag = _diag(primary[1]) or 1.0
    chosen = [primary]
    left = primary[1]["bbox"][0]
    for ci, c in others:
        if left - c["bbox"][2] > pdiag * 2.0:     # grand trou : on arrete
            break
        if 0.4 * pdiag <= _diag(c) <= 2.5 * pdiag:
            chosen.append((ci, c))
            left = min(left, c["bbox"][0])
    return chosen


def _pair_glyph(row, clusters, used):
    """Glyphe le plus proche A GAUCHE du libelle, + ses variantes contigues.

    Sert a la 1re passe (reperage des colonnes) et a la detection des continuations. Pour
    l'appariement definitif, voir _assign_glyphs : glouton dans l'ordre des y, il faisait
    voler le glyphe des lignes suivantes par la premiere quand extract_page fusionne
    plusieurs symboles en un cluster haut.

    Retourne (index, cluster) du glyphe principal et la liste [(index, cluster)] des
    variantes, ou (None, []) si aucun candidat.
    """
    cand = _candidates(row, clusters, used)
    if not cand:
        return None, []
    primary = max(cand, key=lambda ic: ic[1]["bbox"][2])   # le plus proche du libelle
    return primary, _expand_variants(primary, cand)


def _merge_continuations(items, clusters):
    """Fusionne les lignes de CONTINUATION de libelle dans la ligne qui les precede.

    Un libelle trop long deborde sur une 2e ligne PDF ("Ecl-type A:Luminaire encastre avec
    ossature metallique" / "recuperee et source remplacee : LED + DALI"). PyMuPDF en fait
    deux lignes (block, line) distinctes. Cette 2e ligne cree un ecart vertical anormalement
    PETIT (mesure : 7,6 et 7,3 pt pour un pas median de ~14 pt), qui casse la suite reguliere
    et fait jeter par _longest_regular_run tout ce qui suit la coupure.

    D'ou l'ordre : fusionner AVANT l'analyse du pas, sinon le pas reste casse.

    Critere : ecart < CONT_PITCH * pas median ET la ligne n'apporte aucun glyphe PROPRE
    (aucun candidat, ou le meme cluster que la ligne precedente). Le 2e conjoint est une
    garde : une ligne qui a son propre symbole distinct est une entree, meme a demi-pas.

    NB : le critere "aucun glyphe candidat" seul ne discrimine pas sur ce plan -- les deux
    continuations mesurees ONT un candidat (le cluster fusionne haut de leur voisine).
    """
    items = sorted(items, key=lambda p: p["row"]["y"])
    if len(items) < 2:
        return items, []
    gaps = [items[i + 1]["row"]["y"] - items[i]["row"]["y"] for i in range(len(items) - 1)]
    med = sorted(gaps)[len(gaps) // 2] or 1.0

    kept, merged = [dict(items[0], row=dict(items[0]["row"]))], []
    for i, g in enumerate(gaps):
        p = items[i + 1]
        prev = kept[-1]
        gi = p["glyph"][0] if p["glyph"] else None
        pgi = prev["glyph"][0] if prev["glyph"] else None
        propre = gi is not None and gi != pgi
        if g < CONT_PITCH * med and not propre:
            merged.append(p["row"]["text"])
            prev["row"]["text"] = f"{prev['row']['text']} {p['row']['text']}".strip()
        else:
            kept.append(dict(p, row=dict(p["row"])))
    return kept, merged


def _assign_glyphs(runs, clusters):
    """Appariement GLOBAL ligne <-> glyphe, du couple le plus proche au plus lointain.

    L'ancienne 2e passe reservait gloutonnement dans l'ordre des y croissants. Quand
    extract_page fusionne plusieurs symboles voisins en un cluster haut (#1363 : 52 pt pour
    des lignes espacees de 14 pt), ce cluster est candidat pour 5 ou 6 lignes d'affilee :
    la premiere le raflait, les suivantes repartaient les mains vides et etaient jetees.

    Ici on classe tous les couples (ligne, candidat) par distance verticale croissante et on
    affecte en sautant ce qui est deja pris : une ligne dont le meilleur candidat est deja
    pris recupere son 2e choix au lieu de rien. Deterministe (les ex aequo sont departages
    par l'index du cluster puis celui de la ligne).

    Retourne {id(row): (primary, variants)} ; une ligne absente n'a aucun glyphe.
    """
    rows = [p["row"] for run in runs for p in run]
    couples = []
    for ri, row in enumerate(rows):
        for ci, c in _candidates(row, clusters, used=set()):
            b = c["bbox"]
            couples.append((abs((b[1] + b[3]) / 2 - row["y"]), ci, ri, c))
    couples.sort(key=lambda t: (t[0], t[1], t[2]))

    primary_of, taken = {}, set()
    for _, ci, ri, c in couples:
        if ri in primary_of or ci in taken:
            continue
        primary_of[ri] = (ci, c)
        taken.add(ci)

    # variantes : une fois les principaux fixes, on etend autour du principal sans jamais
    # reprendre le principal d'une autre ligne.
    out = {}
    used_var = set()
    for ri, row in enumerate(rows):
        if ri not in primary_of:
            continue
        primary = primary_of[ri]
        blocked = (taken | used_var) - {primary[0]}
        cand = _candidates(row, clusters, used=blocked)
        variants = _expand_variants(primary, cand)
        used_var.update(ci for ci, _ in variants)
        out[id(row)] = (primary, variants)
    return out


# ---------------------------------------------------------------- colonnes

def _group_columns(pairs):
    """Regroupe les paires (glyphe, libelle) par x0 de LIBELLE.

    Tri par x0 puis coupure : on ouvre une nouvelle colonne des que le x0 s'ecarte de plus de
    TOL_X hauteurs de ligne du PRECEDENT. Stable et independant de l'ordre d'insertion.

    NB : ne PAS regrouper autour d'une moyenne glissante (1re version). La moyenne derivait au
    fil des ajouts et pouvait s'eloigner de tous les membres ; l'appartenance dependait alors
    de l'ordre. Mesure du 2026-07-15 (CFA-100 videosurveillance) : les 3 cameras a x0=2887,8
    se noyaient dans un blob dont la moyenne avait derive, et leur colonne n'existait plus.
    """
    cols = []
    for p in sorted(pairs, key=lambda p: p["row"]["x0"]):
        x0 = p["row"]["x0"]
        if cols and x0 - cols[-1]["x0_last"] <= TOL_X * p["row"]["h"]:
            cols[-1]["items"].append(p)
            cols[-1]["x0_last"] = x0
        else:
            cols.append({"x0_last": x0, "items": [p]})
    for col in cols:
        col["x0"] = min(p["row"]["x0"] for p in col["items"])
    return cols


def _regular_runs(items):
    """Toutes les suites maximales de lignes a pas vertical LOCALEMENT coherent.

    C'est l'etape qui COUPE la legende du plan : les textes du plan qui partagent par hasard
    le x0 d'une colonne n'ont aucune raison d'en respecter le pas vertical.

    Une colonne peut contenir DEUX groupes reguliers de pas differents : une vraie legende
    serree (pas ~37) et des lignes de cartouche au meme x0 mais espacees (~140). Un pas median
    unique pour toute la colonne (1re version) etait domine par le groupe le plus etale et
    rejetait le groupe serre comme "hors norme". Mesure du 2026-07-15 (CFA-100) : les 3 cameras
    (pas 37/38) perdaient face a 3 lignes de cartouche (pas 139/184), le pas median de la
    colonne etant 139. On renvoie donc TOUS les runs ; c'est la validite + l'ancre qui tranchent.

    Un gap prolonge le run courant s'il reste dans [PITCH_LO, PITCH_HI] x le pas median de CE
    run (pas de la colonne entiere). Runs de >= 2 lignes seulement.
    """
    items = sorted(items, key=lambda p: p["row"]["y"])
    if len(items) < 2:
        return [items] if items else []
    runs = []
    cur = [items[0]]
    cur_gaps = []
    for i in range(len(items) - 1):
        g = items[i + 1]["row"]["y"] - items[i]["row"]["y"]
        if cur_gaps:
            med = sorted(cur_gaps)[len(cur_gaps) // 2] or 1.0
            ok = PITCH_LO * med <= g <= PITCH_HI * med
        else:
            ok = True   # 1er gap : il fixe le pas du run
        if ok:
            cur.append(items[i + 1])
            cur_gaps.append(g)
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = [items[i + 1]]
            cur_gaps = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def _col_bbox(run):
    xs = [p["row"]["x0"] for p in run]
    ys = [p["row"]["y"] for p in run]
    for p in run:
        if p["glyph"]:
            xs.append(p["glyph"][1]["bbox"][0])
    return [min(xs), min(ys), max(xs), max(ys)]


def _anchored(run, anchors):
    """Un titre de legende surplombe-t-il cette colonne ?

    Critere : l'ancre est AU-DESSUS de la 1re ligne (a <= ANCHOR_GAP hauteurs de ligne) et
    son x0 est proche du bord gauche de la colonne (<= ANCHOR_X_TOL hauteurs de ligne).
    L'ancre ne definit PAS la zone -- elle confirme une colonne deja reperee par alignement.
    """
    first = min(run, key=lambda p: p["row"]["y"])["row"]
    left = _col_bbox(run)[0]
    h = first["h"]
    for a in anchors:
        if 0 < first["y"] - a["y"] <= ANCHOR_GAP * h and abs(a["x0"] - left) <= ANCHOR_X_TOL * h:
            return a
    return None


def _min_rows(anchor):
    return MIN_ROWS_ANCHORED if anchor else MIN_ROWS


def _valid_column(run, anchor):
    """Une colonne de legende : assez de lignes, en bande verticale, majoritairement
    porteuse de glyphes.

    Sous une ancre, les seuils STRUCTURELS s'assouplissent : 2 lignes suffisent et la
    contrainte de bande verticale saute (une legende de 2 entrees est plus large que haute).
    La part de glyphes reste exigee -- une colonne de texte sans aucun symbole n'est pas une
    legende, ancre ou pas (c'est le cartouche : "Maitre d'ouvrage", "Hauteur sous dalle").
    """
    if len(run) < _min_rows(anchor):
        return False
    if not anchor:
        x0, y0, x1, y1 = _col_bbox(run)
        if (y1 - y0) / max(x1 - x0, 1.0) < MIN_ASPECT:
            return False
    ratio = MIN_GLYPH_RATIO_ANCHORED if anchor else MIN_GLYPH_RATIO
    with_glyph = sum(1 for p in run if p["glyph"])
    return with_glyph / len(run) >= ratio


# ---------------------------------------------------------------- quantites

def _qty_column(qty_rows, run, min_rows):
    """Les lignes numeriques ne sont une colonne QTE que si elles sont DANS l'etendue en y
    de la colonne de legende, A DROITE des libelles, et alignees entre elles.

    Sans cette garde, on ramasse les nombres du plan : sur le plan VDI de BPCE, les valeurs
    80 / 160 / 353 observees le 2026-07-13 etaient des effectifs et des surfaces.

    `min_rows` suit le seuil de la colonne : les legendes ROI RENE ont 2 entrees ET une vraie
    colonne QTE ("LEGENDE VIDEOSURVEILLANCE / Camera Dome / QTE / 4 / 3").
    """
    y0 = min(p["row"]["y"] for p in run)
    y1 = max(p["row"]["y"] for p in run)
    x_lab = max(p["row"]["x0"] for p in run)
    cand = [q for q in qty_rows if y0 - 8 <= q["y"] <= y1 + 8 and q["x0"] > x_lab]
    if len(cand) < min_rows:
        return []
    xs = sorted(q["x0"] for q in cand)
    med = xs[len(xs) // 2]
    cand = [q for q in cand if abs(q["x0"] - med) <= 2 * q["h"]]
    return cand if len(cand) >= min_rows else []


# ---------------------------------------------------------------- API

def build_legend(clusters, words):
    """clusters + words (de pdf_takeoff.extract_page) -> legende. Sans I/O.

    Aucune ligne d'une colonne validee n'est jetee : elle sort comme entree, avec un
    glyph_bbox a None si aucun gabarit n'a pu lui etre attribue, et un warning la nomme.
    """
    label_rows, qty_rows, anchors = _rows_from_words(words)
    warnings = []

    # 1re passe : apparier SANS reserver les glyphes. Une ligne de bruit ne doit pas voler
    # le glyphe d'une vraie entree avant qu'on ait decide qui est bruit.
    pairs = []
    for row in label_rows:
        glyph, variants = _pair_glyph(row, clusters, used=set())
        pairs.append({"row": row, "glyph": glyph, "variants": variants})

    runs, run_anchors = [], []
    for col in _group_columns(pairs):
        items, merged = _merge_continuations(col["items"], clusters)
        col_runs = _regular_runs(items)
        # une ligne d'un run valide n'est jamais "coupee" ; on ne signale la coupure que
        # pour les lignes qui n'entrent dans AUCUN run de la colonne.
        in_a_run = {id(p) for r in col_runs for p in r}
        for run in col_runs:
            anchor = _anchored(run, anchors)
            if _valid_column(run, anchor):
                runs.append(run)
                run_anchors.append(anchor)
            elif len(run) >= _min_rows(anchor):
                # run assez long mais ecarte par un filtre ULTERIEUR (bande verticale, part
                # de glyphes) : c'est la seule facon de perdre une vraie legende -> on signale.
                x0, y0, x1, y1 = _col_bbox(run)
                ratio = sum(1 for p in run if p["glyph"]) / len(run)
                why = ("bande pas assez verticale"
                       if not anchor and (y1 - y0) / max(x1 - x0, 1.0) < MIN_ASPECT
                       else f"seulement {ratio:.0%} des lignes portent un glyphe")
                warnings.append(
                    "colonne candidate rejetee (x0~{:.0f}, {} lignes regulieres, {}{}) : {}"
                    .format(col["x0"], len(run), why,
                            ", sous ancre " + repr(anchor["text"][:30]) if anchor else "",
                            ", ".join(repr(p["row"]["text"]) for p in run[:6])))
        coupees = [p["row"]["text"] for p in items if id(p) not in in_a_run]
        if coupees and any(_anchored(r, anchors) or _valid_column(r, _anchored(r, anchors))
                           for r in col_runs):
            warnings.append(
                "lignes sans pas regulier ecartees (colonne x0~{:.0f}) : {}"
                .format(col["x0"], ", ".join(repr(t) for t in coupees[:8])))
    order = sorted(range(len(runs)), key=lambda i: (_col_bbox(runs[i])[0], _col_bbox(runs[i])[1]))
    runs = [runs[i] for i in order]
    run_anchors = [run_anchors[i] for i in order]

    # 2e passe : appariement GLOBAL du plus proche au plus lointain, sur les seules colonnes
    # retenues. Une ligne sans glyphe reste une entree -- elle est signalee, pas jetee.
    assigned = _assign_glyphs(runs, clusters)

    entries, columns, orphelines = [], [], []
    for ci, run in enumerate(runs):
        qty_rows_col = _qty_column(qty_rows, run, _min_rows(run_anchors[ci]))
        for p in sorted(run, key=lambda p: p["row"]["y"]):
            row = p["row"]
            glyph, variants = assigned.get(id(row), (None, []))
            if glyph is None:
                orphelines.append(row["text"])
            qty = next((int(q["text"]) for q in qty_rows_col
                        if abs(q["y"] - row["y"]) < 8), None)
            entries.append({
                "label": row["text"],
                "canon": canon(row["text"], strict=True),
                "glyph_bbox": list(glyph[1]["bbox"]) if glyph else None,
                "variants": [c for _, c in variants],
                "qty_declared": qty,
                "column": ci,
            })
        columns.append(_col_bbox(run))

    if orphelines:
        warnings.append(
            "{} entree(s) sans gabarit (symboles fusionnes par extract_page en un seul "
            "cluster) : {}".format(len(orphelines), ", ".join(repr(t) for t in orphelines)))
    if not entries:
        warnings.append(
            f"aucune colonne de legende detectee ({len(clusters)} glyphes, "
            f"{len(label_rows)} lignes de texte)")
    return {"entries": entries, "columns": columns, "warnings": warnings}


def read_legend(pdf_path, page_no: int = 0):
    """Lit la legende de la page `page_no` d'un PDF vectoriel."""
    doc = fitz.open(pdf_path)
    try:
        clusters, words = extract_page(doc[page_no])
    finally:
        doc.close()
    return build_legend(clusters, words)


if __name__ == "__main__":
    res = read_legend(Path(sys.argv[1]))
    for w in res["warnings"]:
        print(f"!! {w}\n")
    sans = sum(1 for e in res["entries"] if e["glyph_bbox"] is None)
    print(f"{len(res['entries'])} entrees, {len(res['columns'])} colonne(s), "
          f"{sans} sans gabarit\n")
    print(f"{'col':>3} {'qte':>4} {'gab':>4}  {'canon':<22} libelle")
    print("-" * 96)
    for e in res["entries"]:
        print(f"{e['column']:>3} {str(e['qty_declared']):>4} "
              f"{'-' if e['glyph_bbox'] is None else 'ok':>4}  "
              f"{str(e['canon']):<22} {e['label'][:55]}")
