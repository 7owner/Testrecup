"""Prepare 4e_dataset pour l'entrainement Colab (Mask R-CNN / detectron2).

- fusionne les metiers en un seul COCO (categories unifiees) ;
- TUILE chaque grande image de plan en imagettes (les symboles font ~5-16 px sur
  le plan entier -> trop petits ; en tuiles ils occupent une part correcte) ;
- split train/val PAR PLAN SOURCE (pas de fuite entre tuiles du meme plan) ;
- ecrit coco_colab/{train,val}/images + annotations.json, puis un .zip a uploader.

Lancer :  python colab/prepare_for_colab.py
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "4e_dataset"
OUT = HERE / "coco_colab"

TILE = 800          # cote de la tuile (px)
OVERLAP = 200       # recouvrement (px) : chaque symbole tient entier dans >=1 tuile
VAL_FRACTION = 0.18  # cible sur le nombre d'INSTANCES (pas de plans) : les plans
                     # sont tres inegaux (1105 vs 12 instances)
SEED = 0
MIN_BOX = 2.0       # px : en dessous, la boite est degeneree (residu de rendu) -> purgee
BG_RATIO = 0.10     # part de tuiles de FOND (sans aucun symbole) dans chaque split.
                    # Sans elles le modele ne voit jamais de vide et sur-detecte
                    # sur les zones vides d'un vrai plan.

sys.path.insert(0, str(ROOT / "plan_takeoff"))
sys.path.insert(0, str(HERE.parent))
import fitz  # noqa: E402
from canonical import canon  # noqa: E402


def load_all():
    """-> (images[], anns[], cat_name_by_gid), categories unifiees par NOM."""
    cat_id = {}
    images, anns = [], []
    gimg = 0
    gann = 0
    for ann_file in sorted(SRC.glob("*/annotations.json")):
        met = ann_file.parent.name
        d = json.load(open(ann_file, encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in d["categories"]}
        remap = {}
        for old, im in [(im["id"], im) for im in d["images"]]:
            remap[old] = gimg
            im2 = dict(im)
            im2["id"] = gimg
            im2["metier"] = met
            im2["path"] = str(ann_file.parent / "images" / im["file_name"])
            images.append(im2)
            gimg += 1
        for a in d["annotations"]:
            name = canon(cats[a["category_id"]])   # -> classe canonique (~37)
            if name is None:
                continue                            # exclu (mobilier/legende/anonyme)
            cid = cat_id.setdefault(name, len(cat_id))
            a2 = dict(a)
            a2["id"] = gann
            a2["image_id"] = remap[a["image_id"]]
            a2["category_id"] = cid
            anns.append(a2)
            gann += 1
    categories = [{"id": i, "name": n} for n, i in sorted(cat_id.items(), key=lambda kv: kv[1])]
    return images, anns, categories


def src_of(im):
    """Plan source d'une image : unite atomique du split (pas la tuile, pas l'image)."""
    return im.get("source_pdf") or im.get("source_dwg") or im["file_name"]


def stratified_split(images, by_img, categories):
    """Choisit les plans de validation. Le split reste PAR PLAN (aucune fuite), mais
    on choisit QUELS plans au lieu d'en tirer 18 % au hasard.

    Trois exigences, par ordre de durete :
      1. aucune classe a 0 instance d'entrainement (sinon elle est ininapprenable) ;
      2. chaque classe presente dans >=2 plans a >=1 instance de validation
         (sinon son AP est un NaN et on ne sait rien d'elle) ;
      3. l'entrainement domine la validation sur chaque classe, et la validation
         pese ~VAL_FRACTION des INSTANCES.

    Recherche : les plans portant une classe mono-plan sont forces en train, puis
    recuit greedy (ajout/retrait/echange) sur les plans restants, multi-departs.
    """
    # On compte les instances REALISEES (celles qui survivront a la mise a l'echelle
    # + purge <MIN_BOX), PAS les annotations brutes. Sinon un plan bourre de boites
    # degenerees (ex. Verdun-B : 18 suspensions rendues a 0.5px) est cru riche d'une
    # classe, choisi pour la validation, puis ces instances s'evaporent au tuilage ->
    # 0 val en realite. Vecu le 2026-07-13 : SUSPENSION/REGLETTE/LAMPE_POSER (41/22/15%
    # de boites degenerees) etaient mal reparties.
    per_plan = defaultdict(Counter)
    for im in images:
        arr, _n, _a = _full_arr(im["path"])
        H, W = arr.shape[:2]
        sx = W / (im["width"] or W)
        sy = H / (im["height"] or H)
        c = per_plan[src_of(im)]
        for a in by_img[im["id"]]:
            if a["bbox"][2] * sx >= MIN_BOX and a["bbox"][3] * sy >= MIN_BOX:
                c[a["category_id"]] += 1

    plans = sorted(per_plan)
    total = Counter()
    for p in plans:
        total.update(per_plan[p])
    n_total = sum(total.values())

    plans_of = defaultdict(set)
    for p in plans:
        for c in per_plan[p]:
            plans_of[c].add(p)
    # Une classe presente dans <=2 plans ne peut pas etre a la fois bien APPRISE et
    # mesuree : le split par plan ne donnerait que 50/50 ou 100/0. On force TOUS ses
    # plans en train -> apprentissage complet, quitte a ne pas la mesurer (elle sera
    # validee sur de futures affaires). Diagnostic 2026-07-12 : NOURRICE et BORNE_WIFI
    # n'existent que dans 2 plans (BPCE) ; en laisser un en val volait ~50% du train
    # et la classe s'effondrait (confondue avec LUMINAIRE). Generalise la regle
    # mono-plan (<=1) a <=2.
    CONCENTRATED = {c for c in plans_of if len(plans_of[c]) <= 2}
    forced_train = {p for c in CONCENTRATED for p in plans_of[c]}
    free = [p for p in plans if p not in forced_train]
    # classes qu'on PEUT encore equilibrer (presentes dans >2 plans) : seules elles
    # doivent peser dans le cout, sinon on optimise pour des classes deja tranchees.
    balanceable = [c for c in total if len(plans_of[c]) > 2]

    def cost(val):
        tr, va = Counter(), Counter()
        for p in plans:
            (va if p in val else tr).update(per_plan[p])
        c = 0.0
        for cls in balanceable:
            if tr[cls] == 0:
                c += 1000                      # inacceptable
            elif va[cls] == 0:
                c += 20                        # AP non mesurable alors qu'evitable
            else:
                vf = va[cls] / (tr[cls] + va[cls])
                if vf > 0.35:                  # trop d'instances en val -> train affame
                    c += 60 * (vf - 0.35)
        c += 300 * abs(sum(va.values()) / n_total - VAL_FRACTION)
        return c

    rng = random.Random(SEED)
    best, best_c = None, float("inf")
    for _ in range(40):                                   # multi-departs
        k = max(1, round(len(free) * VAL_FRACTION))
        val = set(rng.sample(free, min(k, len(free))))
        cur = cost(val)
        improved = True
        while improved:                                    # descente : add / drop / swap
            improved = False
            moves = [val | {p} for p in free if p not in val]
            moves += [val - {p} for p in val]
            moves += [(val - {a}) | {b} for a in val for b in free if b not in val]
            for m in moves:
                if not m:
                    continue
                cm = cost(m)
                if cm < cur - 1e-9:
                    val, cur, improved = m, cm, True
        if cur < best_c:
            best, best_c = set(val), cur

    tr, va = Counter(), Counter()
    for p in plans:
        (va if p in best else tr).update(per_plan[p])
    names = {c["id"]: c["name"] for c in categories}
    zero_tr = [names[c] for c in total if tr[c] == 0]
    zero_va = [names[c] for c in total if va[c] == 0]
    print(f"split stratifie : {len(best)}/{len(plans)} plans en val, "
          f"{sum(va.values()) / n_total:.1%} des instances (cible {VAL_FRACTION:.0%})")
    print(f"  classes sans train : {zero_tr or 'aucune'}")
    print(f"  classes sans val   : {zero_va or 'aucune'}  (mono-plan : inevitable)")
    return best


def tile_image(im, im_anns, occupied):
    """Decoupe une image en tuiles.

    Retourne (tiles, empties) :
      - tiles   = [((tx,ty,w,h), [ann...]), ...]  tuiles portant >=1 annotation
                  ENTIEREMENT contenue ;
      - empties = [(tx,ty,w,h), ...]  tuiles de FOND VRAI : elles ne touchent
                  aucune boite de `occupied`, meme partiellement.

    `occupied` = TOUTES les boites de l'image, y compris celles qu'on a purgees
    parce que degenerees. Une tuile qui rogne un symbole n'est PAS du fond : la
    retenir apprendrait au modele a ignorer un vrai symbole.
    """
    W, H = im["width"], im["height"]
    step = TILE - OVERLAP
    tiles, empties = [], []
    xs = list(range(0, max(1, W - OVERLAP), step))
    ys = list(range(0, max(1, H - OVERLAP), step))
    for ty in ys:
        for tx in xs:
            x1, y1 = min(tx + TILE, W), min(ty + TILE, H)
            keep = []
            for a in im_anns:
                bx, by, bw, bh = a["bbox"]
                if bx >= tx and by >= ty and bx + bw <= x1 and by + bh <= y1:
                    seg = a["segmentation"][0]
                    nseg = [seg[i] - tx if i % 2 == 0 else seg[i] - ty for i in range(len(seg))]
                    keep.append({**a, "bbox": [bx - tx, by - ty, bw, bh],
                                 "segmentation": [nseg]})
            if keep:
                tiles.append(((tx, ty, x1 - tx, y1 - ty), keep))
                continue
            touches = any(bx < x1 and bx + bw > tx and by < y1 and by + bh > ty
                          for bx, by, bw, bh in (a["bbox"] for a in occupied))
            if not touches:
                empties.append((tx, ty, x1 - tx, y1 - ty))
    return tiles, empties


import numpy as np  # noqa: E402
_PIXCACHE = {}


def _full_arr(path):
    """Charge le PNG source en tableau numpy (h, w, n), avec cache."""
    v = _PIXCACHE.get(path)
    if v is None:
        pix = fitz.Pixmap(path)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        v = (arr, pix.n, pix.alpha)
        _PIXCACHE[path] = v
    return v


def render_tile(src_png, tx, ty, w, h):
    """Extrait la tuile du PNG source -> (png_bytes, largeur_reelle, hauteur_reelle).
    Les dims renvoyees font AUTORITE (== pixels du PNG) pour l'annotation."""
    arr, n, alpha = _full_arr(src_png)
    tx, ty, w, h = int(tx), int(ty), int(w), int(h)
    crop = arr[ty:ty + h, tx:tx + w, :].copy()
    ch, cw = crop.shape[:2]
    cs = fitz.csRGB if n >= 3 else fitz.csGRAY
    return fitz.Pixmap(cs, cw, ch, crop.tobytes(), alpha).tobytes("png"), cw, ch


def emit(out, iid, aid, split, im, src_png, tx, ty, w, h, keep):
    """Ecrit une tuile + ses annotations dans `split`. `keep` vide = tuile de fond."""
    png, cw, ch = render_tile(src_png, tx, ty, w, h)
    # id global dans le nom : evite les collisions entre metiers d'un meme DWG
    # (Afrique_rdc CFO/CFA/SSI ont le meme file_name -> tuiles homonymes)
    fname = f"im{im['id']}_{Path(im['file_name']).stem}_t{tx}_{ty}.png"
    (OUT / split / "images" / fname).write_bytes(png)
    tid = iid[split]
    iid[split] += 1
    out[split]["images"].append({"id": tid, "file_name": fname,
                                 "width": cw, "height": ch, "metier": im["metier"]})
    for a in keep:
        seg = a["segmentation"][0]
        bx, by, bw, bh = a["bbox"]
        out[split]["annotations"].append({
            "id": aid[split], "image_id": tid, "category_id": a["category_id"],
            "bbox": [round(bx, 1), round(by, 1), round(bw, 1), round(bh, 1)],
            "area": round(bw * bh, 1), "iscrowd": 0,
            "segmentation": [[round(v, 1) for v in seg]],
        })
        aid[split] += 1


def main():
    images, anns, categories = load_all()
    by_img = defaultdict(list)
    for a in anns:
        by_img[a["image_id"]].append(a)

    # split PAR PLAN/DWG source (evite la fuite entre tuiles du meme plan),
    # mais STRATIFIE : on choisit les plans pour equilibrer les classes.
    val_plans = stratified_split(images, by_img, categories)

    shutil.rmtree(OUT, ignore_errors=True)          # repart propre (pas de tuiles obsoletes)
    for split in ("train", "val"):
        (OUT / split / "images").mkdir(parents=True, exist_ok=True)

    out = {"train": {"images": [], "annotations": [], "categories": categories},
           "val": {"images": [], "annotations": [], "categories": categories}}
    iid = {"train": 0, "val": 0}
    aid = {"train": 0, "val": 0}
    rng = random.Random(SEED)
    n_purged = 0
    n_bg = {"train": 0, "val": 0}
    pending_bg = {"train": [], "val": []}

    for im in images:
        split = "val" if src_of(im) in val_plans else "train"
        src_png = im["path"]
        # Le PNG rendu peut avoir des dimensions != de la taille nominale des
        # annotations (rasterisation SVG). On se cale sur le PNG REEL et on remet
        # les annotations a cette echelle -> tuilage et boites toujours coherents.
        arr, _n, _al = _full_arr(src_png)
        realH, realW = arr.shape[:2]
        sx = realW / (im["width"] or realW)
        sy = realH / (im["height"] or realH)
        im = {**im, "width": realW, "height": realH}
        scaled = []
        for a in by_img[im["id"]]:
            bx, by, bw, bh = a["bbox"]
            seg = a["segmentation"][0]
            scaled.append({**a, "bbox": [bx * sx, by * sy, bw * sx, bh * sy],
                           "segmentation": [[seg[i] * (sx if i % 2 == 0 else sy)
                                             for i in range(len(seg))]]})
        # purge des boites degenerees (sous-pixel) : elles n'apprennent rien et
        # polluent la loss. On les garde dans `occupied` pour que leur tuile ne
        # soit pas prise pour du fond.
        kept = [a for a in scaled if a["bbox"][2] >= MIN_BOX and a["bbox"][3] >= MIN_BOX]
        n_purged += len(scaled) - len(kept)

        tiles, empties = tile_image(im, kept, occupied=scaled)
        for (tx, ty, w, h), keep in tiles:
            emit(out, iid, aid, split, im, src_png, tx, ty, w, h, keep)
        # on ne tire PAS le fond ici : un quota par image s'arrondirait a zero sur
        # les petites images (round(3 * 0.11) == 0) et perdrait l'essentiel du vivier.
        pending_bg[split] += [(im, src_png, c) for c in empties]

    # tuiles de fond : tirage GLOBAL par split, pour viser BG_RATIO du total final
    for split in ("train", "val"):
        n_full = len(out[split]["images"])
        want = round(n_full * BG_RATIO / (1 - BG_RATIO))
        pool = pending_bg[split]
        for im, src_png, (tx, ty, w, h) in rng.sample(pool, min(want, len(pool))):
            emit(out, iid, aid, split, im, src_png, tx, ty, w, h, [])
            n_bg[split] += 1
        if want > len(pool):
            print(f"  ! {split}: seulement {len(pool)} tuiles de fond disponibles "
                  f"sur {want} voulues (plans denses)")

    print(f"boites degenerees purgees (<{MIN_BOX:g}px) : {n_purged}")
    for split in ("train", "val"):
        (OUT / split / "annotations.json").write_text(
            json.dumps(out[split], ensure_ascii=False), encoding="utf-8")
        n_img = len(out[split]["images"])
        print(f"{split}: {n_img} tuiles ({n_bg[split]} de fond = {n_bg[split]/n_img:.0%}), "
              f"{len(out[split]['annotations'])} instances")
    print(f"classes: {len(categories)}  | plans val: {sorted(val_plans)}")

    # zip pour upload Colab
    zpath = HERE / "coco_colab.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in OUT.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(OUT.parent))
    print(f"\n-> ZIP a uploader sur Colab : {zpath}  ({zpath.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
