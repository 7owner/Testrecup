# Instance Segmentation

Ce module remplace l'ancienne logique de **classification de crops** quand l'objectif est une **vraie segmentation d'instances**.

Ici, on ne part plus de boites approximatives ni d'un dataset de classification :

- une image d'entrainement = une **tuile** de plan ;
- une annotation = une **instance** avec `bbox + segmentation` ;
- le format cible = **COCO instance segmentation** ;
- le modele cible = **Mask R-CNN**.

## Arborescence cible

```text
instance_seg/
  common.py
  dataset.py
  modeling.py
  prepare_pdf_tiles.py
  train_instance.py
  infer_instance.py
```

Dataset attendu :

```text
instance_seg/data/plans_coco/
  train/
    images/
    annotations.json
  val/
    images/
    annotations.json
  test/
    images/
    annotations.json
```

## 1. Generer les tuiles depuis les PDF

```bash
python -m instance_seg.prepare_pdf_tiles \
  --pdf "exemples/FAU-CAZE-EXE-IMP-03-A- Plan Implantation RDC Immeuble Phocea Cazemajou.pdf" \
  --output-root instance_seg/data/plans_coco \
  --split train \
  --pages 1 \
  --zoom 2.5 \
  --tile-size 1024 \
  --overlap 128 \
  --categories-json instance_seg/data/categories_template.json
```

Un template de categories de depart est fourni dans :

- `instance_seg/data/categories_template.json`

Tu peux aussi l'injecter plus tard dans un COCO deja genere :

```bash
python -m instance_seg.apply_categories_to_coco \
  --annotations instance_seg/data/plans_coco/train/annotations.json \
  --categories-json instance_seg/data/categories_template.json
```

## 2. Annoter les vrais masques

Il faut annoter les tuiles dans un outil externe qui supporte COCO polygons ou masks :

- CVAT
- Label Studio
- Roboflow
- Supervisely

## 3. Entrainement

```bash
python -m instance_seg.train_instance \
  --dataset-root instance_seg/data/plans_coco \
  --output models/instance_seg_maskrcnn.pt \
  --run-dir training_runs/instance_seg_run_001 \
  --epochs 20 \
  --batch-size 2
```

## 4. Inference et comptage

```bash
python -m instance_seg.infer_instance \
  --checkpoint models/instance_seg_maskrcnn.pt \
  --input "exemples/FAU-CAZE-EXE-IMP-03-A- Plan Implantation RDC Immeuble Phocea Cazemajou.pdf" \
  --pages 1 \
  --output-dir outputs/instance_seg
```

## Dependances

Le projet a deja `torch`, mais **pas `torchvision`** actuellement.

Il faut installer une version compatible avec la version de `torch` presente sur ta machine :

```bash
pip install torchvision
```

Si `torchvision` n'est pas installe, `train_instance.py` et `infer_instance.py` s'arretent avec un message clair.
