# Test_No3 — Comptage de symboles par détecteur appris (dataset auto-étiqueté DWG)

Doc de reprise. But : **compter les symboles CFO/CFA/SSI sur des plans PDF, sans DWG
en production**, via un détecteur (Mask R-CNN) entraîné sur un dataset **auto-étiqueté
depuis les DWG** (positions + noms de blocs = annotations gratuites, zéro clic).

En prod : PDF seul → détecteur → boîtes/masques + comptage.
À l'entraînement (une fois) : DWG dispo → génère les images + étiquettes exactes.

---

## Décision d'architecture (importante, ne pas refaire les impasses)

- **La méthode d'avril** (template-matching / KMeans dans le dossier parent) était
  mono-plan et sous-comptait ; abandonnée. Mesuré vs corrigé DWG : CFA-VIDEO −13 %,
  SSI −44 %, VDI (RJ45 denses) **−65 %** (voir `bench.py`).
- **Alignement DWG→PDF : IMPASSE.** 4 tentatives (nuage de points, ancres texte,
  viewport analytique, étage propre) → au mieux 6/24. Cause : ces DWG bourrés d'xref
  ont des repères incohérents (symboles à ~millions d'unités, viewport à ~centaines).
  **Ne pas y revenir** (code laissé dans `autolabel.py` / `align.py` pour mémoire).
- **Méthode retenue = B + xref** : on **rend l'image depuis le DWG** (repère qu'on
  contrôle → boîtes exactes, aucun recalage). Les murs viennent d'un **xref
  d'architecture** (`00-xref/…`) qu'on charge et replace. Marche sur tous les métiers.

## Pipeline (de bout en bout)

```
DWG (symboles: pos+bloc+calque+scale+rot)  ─┐
DWG xref architecture (murs)  ──────────────┤ render_dwg.py
PDF de la feuille (calques tracés)  ─────────┘
        │  process_plan (résout *U, exclut annot/légende/tags) + filtre calques du PDF
        │  + exclusion classes LINÉAIRES (goulottes/chemins de câble) — 1re passe
        │  + split_floors (sépare les étages, fusionne les fragments d'un même étage)
        ▼
  image réaliste (murs+symboles) + boîtes/masques exacts, PAR ÉTAGE, PAR MÉTIER
        │  make_dataset.py (boîtes)  |  make_dataset_seg.py (masques polygones)
        ▼
  3e_dataset (détection) / 4e_dataset (segmentation d'instances), COCO par métier
        │  colab/prepare_for_colab.py (fusion + tuilage 800px + split train/val PAR PLAN + zip)
        ▼
  colab/coco_colab.zip  ──►  colab/train_instance_seg.ipynb (Colab GPU) ──► model_final.pth
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `bench.py` | **Banc de vérité** : compte DWG légende-exact (par feuille) vs méthode `plan_takeoff`. Sort `out/bench.csv`. Sert à SCORER n'importe quelle méthode (dont le futur détecteur). |
| `canonical.py` | `canon()` : 222 noms de blocs bruts → 38 classes canoniques (ou exclus). |
| `calibrate_thresholds.py` | Calibre un **seuil de score par classe** depuis un run (`run_outputs.zip` + `coco_colab.zip`) → `thresholds.json`. Local, pas de GPU. |
| `render_dwg.py` | Cœur B+xref : `build_sheet` (symboles+murs xref), `split_floors`, `render_floors` → (svg, meta{boxes,seg}) par étage. |
| `make_dataset.py` | Génère `3e_dataset` (COCO boîtes). |
| `make_dataset_seg.py` | Génère `4e_dataset` (COCO segmentation, polygones). |
| `qc_dataset.py` | Contrôle qualité d'un dataset (tailles, dégénérées, masques valides, par classe). |
| `autolabel.py`, `align.py` | Recalage PDF — **voie morte**, conservés. `detect_metier()` (utile) vit dans `autolabel.py`. |
| `colab/` | Package d'entraînement (voir `colab/README.md`). |
| `_cache/` | Cache des DWG parsés (JSON). `out/` : rapports/images. |

## Commandes (Windows, PowerShell ou bash)

Python : **`../plan_takeoff/.venv/Scripts/python.exe`** (a `fitz`/pymupdf, `numpy`).

```bash
cd Test_No3
PY=../plan_takeoff/.venv/Scripts/python.exe
$PY bench.py                              # banc vérité vs méthode actuelle
$PY render_dwg.py "<chemin.dwg>" "<chemin.pdf>"   # rend 1 plan (debug), PNG dans out/
$PY make_dataset_seg.py                   # (re)génère 4e_dataset
$PY qc_dataset.py 4e_dataset              # QC
$PY colab/prepare_for_colab.py            # produit colab/coco_colab.zip
```

## Pièges / gotchas (vécus)

- **dwgread est LENT** (~1-2 min par DWG). Le cache `_cache/` accélère, MAIS
  `build_sheet` fait `refresh=True` (pour avoir `xref_path`/`scale`) → re-parse
  quand même. Générer un dataset complet = ~30-40 min. Lancer en arrière-plan.
- **Coordonnées chaotiques** : des inserts (xref) sont à des millions d'unités →
  outliers écartés par `split_floors`. Un même DWG peut contenir plusieurs étages
  côte à côte.
- **Un DWG model-space sert plusieurs feuilles PDF** (video/éclairage…) : toujours
  **filtrer aux calques réellement tracés dans CE PDF** (fait dans bench/render).
- **Bug corrigé (ne pas régresser)** : appliquer l'**ÉCHELLE d'insert** à la
  géométrie du bloc (`render_dwg._rot_translate`), sinon boîtes fausses
  (SSI sub-pixel, VDI géantes).
- `dwg_reader.py` (dans `plan_takeoff/`) a été étendu de façon **additive** :
  champs `attribs`, `xref_path`, `scale`. Ne pas casser `plan_takeoff` qui l'utilise.
- **Mojibake** des libellés dans le terminal = affichage ; les données JSON sont a
  priori correctes (UTF-8).

## État actuel (2026-07-06)

- `3e_dataset` + `4e_dataset` générés : **1 seule affaire (ROI RENÉ), 11 plans,
  ~365 instances**. QC OK (3 boîtes dégénérées / 365, masques 365/365 valides).
- Package Colab prêt : `colab/coco_colab.zip` (49 tuiles, val = SSI-210 gelé).
- **Pas encore entraîné.** Le vrai chiffre de viabilité (AP val + compté-vs-vérité
  sur plans jamais vus) sort des cellules 5-6 du notebook Colab.

## Honnêteté (à ne pas oublier)

« Le compte des boîtes colle au DWG » est **circulaire** (les boîtes SONT les
symboles DWG) : ça prouve la fidélité de l'étiquetage, **pas** qu'un détecteur
comptera juste. Seul l'entraînement + éval sur plans **jamais vus** le prouve.

## Reste à faire

1. Lancer l'entraînement Colab → rapporter l'AP réel et compté-vs-vérité.
2. Ajouter **CFO** (le DWG `CFO-010-011` a un nom ≠ des PDF → non capté par
   `find_pairs` qui exige le même stem ; l'apparier explicitement).
3. Ajouter d'autres affaires (CROIX ROUGE / VERDUN / BPCE) dès qu'un DWG est
   dispo → couvrir plus de styles de symboles = meilleure généralisation.
4. (option) régler `split_floors` sur plans très étalés (CFO ~83 % capté).
