# Entraînement Colab — segmentation d'instances des symboles de plans

Tout ce qu'il faut pour entraîner un détecteur (Mask R-CNN) sur `4e_dataset`,
puis compter les symboles sur des plans **PDF sans DWG**.

## Fichiers

| Fichier | Rôle |
|---|---|
| `prepare_for_colab.py` | fusionne les métiers, **tuile** les grands plans, split train/val **par plan**, produit `coco_colab.zip` |
| `coco_colab.zip` | **le dataset à uploader sur Colab** (généré par le script ci-dessus) |
| `train_instance_seg.ipynb` | **le notebook à ouvrir dans Colab** (installe, entraîne, évalue, compte) |

## Marche à suivre

1. **En local** (déjà fait si `coco_colab.zip` existe) :
   ```
   ../plan_takeoff/.venv/Scripts/python.exe prepare_for_colab.py
   ```
2. **Colab** : ouvre `train_instance_seg.ipynb` → *Exécution → Type d'exécution → **GPU***.
3. Exécute les cellules dans l'ordre ; à la cellule 2, **uploade `coco_colab.zip`**.
4. La cellule 5 (évaluation) donne l'**AP COCO sur le split val** = plans jamais vus.
   La cellule 6 compare **compté vs vérité** par classe. C'est **ça**, la viabilité.
5. Télécharge `output/model_final.pth` (cellule 7) : c'est le détecteur de prod.

## À savoir (honnêteté)

- **Dataset actuel** : 5 affaires (ROI RENÉ, CROIX ROUGE, VERDUN, BPCE + orphelins),
  **~504 tuiles / 13 185 instances / 222 classes**, split val = 5 plans gelés.
  `MAX_ITER` est auto-calculé selon la taille (cellule 4).
- **Longue traîne** : 222 classes car le MÊME objet porte des noms différents selon
  l'affaire (ex. « DETECTEUR AUTOMATIQUE » vs « DETECTEUR OPTIQUE ADRESSABLE »).
  Prochain gain : un **dictionnaire de classes canoniques** (fusion des synonymes)
  pour concentrer les données. Les classes bien représentées s'apprennent ; la
  traîne rare, non — c'est attendu.
- **Régénérer / enrichir** : `make_dataset_seg.py` (DWG appariés à un PDF) +
  `make_dataset_more.py` (DWG sans PDF, tri métier par calque) → puis
  `prepare_for_colab.py` reconstruit `coco_colab.zip`.
- **Split par plan** (pas par tuile) : évite qu'une tuile d'entraînement et sa
  voisine de validation viennent du même plan (sinon score gonflé, faux).

## Réglages utiles dans le notebook (cellule 4)

- `MAX_ITER` : augmente si la perte descend encore ; baisse si sur-apprentissage.
- `ANCHOR_GENERATOR.SIZES` : déjà réglé petit (symboles ~5-16 px).
- `DETECTIONS_PER_IMAGE` : monté à 300 pour les plans denses (RJ45).
- `SCORE_THRESH_TEST` (cellule 5) : seuil de confiance ; monte-le si sur-comptage.
