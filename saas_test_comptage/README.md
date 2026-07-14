# SaaS test comptage - reconnaissance sur plans PDF

Prototype local pour retrouver avec precision les symboles d'une legende dans un plan PDF de courant fort.

Le projet contient deux approches complementaires:

- une approche **plan PDF + legende image** avec extraction de symboles puis localisation par matching;
- une approche **zero-shot OWLv2** deja preparee pour des images d'appareils ou scenes.

Pour les plans techniques, la premiere approche est la bonne base.

## Installation

Installation complete pour executer la detection:

```bash
cd /mnt/c/Users/takot/Documents/projet_AIX/saas_test_comptage
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Note WSL: sur `/mnt/c`, l'installation de PyTorch peut etre lente. Si besoin, creer le venv sur le disque Linux, par exemple `~/.venvs/saas_test_comptage`, puis lancer les scripts depuis ce dossier projet avec ce Python.

Pour le pipeline PDF de ce prototype, un venv Linux a ete prepare avec:

```bash
~/.venvs/saas_test_comptage/bin/python
```

Des wrappers `bash` sont aussi fournis:

- `./run-render-pdf.sh`
- `./run-split-plan.sh`
- `./run-extract-legend.sh`
- `./run-locate-pdf.sh`
- `./run-export-dataset.sh`
- `./run-export-hdf5.sh`
- `./run-plot-metrics.sh`
- `./run-train-symbols.sh`

Une interface Windows locale est aussi fournie:

- `Lancer_compteur_plan.bat`
- `Lancer_entrainement_symboles.bat`
- `Lancer_courbes_entrainement.bat`

Elle ouvre un ecran de comptage visuel dans le navigateur:

- chargement d'un plan image;
- chargement optionnel de `templates.json` et `detections.json`;
- selection des objets a compter;
- clic sur le plan pour poser des comptes manuels;
- clic droit pour supprimer un point;
- export de la session au format JSON.

Lanceurs Windows disponibles:

- `Lancer_compteur_plan.bat`: ouvre l'interface de comptage
- `Lancer_entrainement_symboles.bat`: lance l'entrainement du classifieur de symboles via WSL
- `Lancer_courbes_entrainement.bat`: genere les courbes a partir de `training_runs/run_001/metrics.jsonl`

## Dataset local

Une structure de dataset locale est prevue dans `datasets/`.
Le format recommande est:

- **source maitre**: images sur disque + annotations JSON
- **format secondaire optionnel**: HDF5 pour accelerer certains pipelines

`pickle` n'est pas retenu comme format principal.

Format:

```text
datasets/plans/
  train/
    images/
    sessions/
    annotations.json
  val/
    images/
    sessions/
    annotations.json
  test/
    images/
    sessions/
    annotations.json
datasets/labels.json
```

Conversion d'une session exportee depuis l'interface:

```bash
./run-export-dataset.sh \
  --session /chemin/vers/plan_counter_session.json \
  --image rendered_cci/page_001.png \
  --dataset datasets/plans \
  --split train
```

Ce convertisseur:

- copie l'image dans le split cible;
- copie la session JSON;
- genere ou met a jour `annotations.json`;
- met a jour `datasets/plans/labels.json`.

Les points poses a la main dans l'interface sont convertis en boites carrees par defaut. La taille est reglable avec `--box-size`.

### Export HDF5 optionnel

```bash
./run-export-hdf5.sh \
  --dataset datasets/plans \
  --output datasets/plans_dataset.h5
```

Usage recommande:

- JSON = verite terrain, versionnable, lisible
- HDF5 = cache de travail pour l'entrainement ou le chargement rapide

## Resultats d'entrainement

### Premier trainer de symboles

Un premier entrainement local est disponible dans `train.py`.
Il entraine un **classifieur de symboles** a partir des crops generes depuis les boites de `annotations.json`.

Lancement:

```bash
./run-train-symbols.sh \
  --dataset datasets/plans \
  --output models/symbol_classifier.pt \
  --run-dir training_runs/run_001 \
  --epochs 12
```

Sorties:

- `models/symbol_classifier.pt`
- `training_runs/run_001/metrics.jsonl`
- `training_runs/run_001/run_info.json`

Le trainer attend:

- `datasets/plans/train/annotations.json`
- `datasets/plans/val/annotations.json`

Chaque objet annote est converti en crop et appris comme une classe de symbole.

Pour suivre l'entrainement, prevois un fichier `metrics.jsonl` dans un dossier de run, par exemple:

```text
training_runs/
  run_001/
    metrics.jsonl
```

Chaque ligne doit etre un objet JSON du type:

```json
{"epoch": 1, "split": "train", "loss": 1.42, "accuracy": 0.61}
{"epoch": 1, "split": "val", "loss": 1.18, "accuracy": 0.69, "precision": 0.71, "recall": 0.66, "f1": 0.68, "symbol_accuracy/prise_rj45": 0.82, "symbol_accuracy/sirene_interieure": 0.58}
```

Generation des courbes:

```bash
./run-plot-metrics.sh \
  --metrics training_runs/run_001/metrics.jsonl \
  --output training_runs/run_001
```

Sorties:

- `loss_curve.png`
- `accuracy_curve.png`
- `precision_curve.png`
- `recall_curve.png`
- `f1_curve.png`
- `summary.json`

Le `summary.json` garde notamment:

- meilleure `val loss`
- meilleure `val accuracy`
- meilleure accuracy par symbole

## Workflow PDF + legende

### 0. PDF multipage -> images de travail

```bash
./run-render-pdf.sh \
  --pdf "exemples/CCI STE VICTOIRE CRF-DCE-LOT 19 CFO CFA-PLANS.0.pdf" \
  --output rendered_cci
```

Sorties:

- `rendered_cci/page_001.png`, `page_002.png`, etc.
- `rendered_cci/pages_manifest.json`

Cette etape sert a inspecter ou isoler une page de travail quand le PDF contient plusieurs pages.

### 1. Si l'entree est une image composite avec legende + plusieurs plans

```bash
./run-split-plan.sh \
  --image exemples/plan_exemple.png \
  --output split_output
```

Sorties:

- `split_output/legend.png`
- `split_output/plan_r_plus_1.png`
- `split_output/plan_rdc.png`
- `split_output/split_manifest.json`

Le decoupage par defaut correspond au format de l'exemple fourni. Les ratios peuvent etre ajustes si besoin.

### 2. Extraire les symboles depuis la legende

```bash
python3 extract_legend_templates.py \
  --image /chemin/vers/legende.png \
  --output legend_templates
```

Ou via le wrapper:

```bash
./run-extract-legend.sh \
  --image /chemin/vers/legende.png \
  --output legend_templates
```

Sorties:

- `legend_templates/crops/` : un crop par symbole detecte;
- `legend_templates/legend_mask.png` : masque debug des elements colores;
- `legend_templates/templates.json` : manifeste a verifier.

Le script extrait les elements colores de la legende. C'est volontairement semi-automatique:

- il detecte les symboles;
- il cree des ids `symbol_001`, `symbol_002`, etc.;
- tu renommes les `label` utiles dans `templates.json`;
- tu supprimes les entrees parasites si besoin.

### 3. Localiser les symboles dans le PDF ou une image

```bash
python3 locate_symbols_in_pdf.py \
  --pdf /chemin/vers/plan.pdf \
  --templates legend_templates/templates.json \
  --output results
```

Ou via le wrapper:

```bash
./run-locate-pdf.sh \
  --pdf /chemin/vers/plan.pdf \
  --templates legend_templates/templates.json \
  --output results
```

Pour une image de plan deja rendue ou decoupee:

```bash
./run-locate-pdf.sh \
  --image split_output/plan_r_plus_1.png \
  --templates legend_templates/templates.json \
  --output results_r1
```

Sorties:

- `results/detections.json` : detections structurees par page;
- `results/pages/page_001.png` etc. : pages annotees.

Parametres utiles:

- `--threshold 0.62` : seuil de score;
- `--min-scale 0.5 --max-scale 1.6` : plage de taille du symbole dans le plan;
- `--dpi 220` : rendu plus fin si le PDF est dense.

### Limites actuelles

- le matching est robuste pour des symboles geometriques repetitifs;
- les rotations fortes, deformes ou symboles tres proches peuvent demander des reglages;
- la precision finale dependra de la qualite du PDF et de la legende.

La suite logique est d'ajouter une interface de revue et de produire un dataset pour entrainer un detecteur specialise.

## Telecharger le modele OWLv2

```bash
python3 download_model.py
```

Le modele sera stocke dans `models/owlv2-base-patch16-ensemble`.

Pour seulement telecharger le modele, `huggingface-hub` suffit:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install huggingface-hub
python3 download_model.py
```

## Tester une image

```bash
python3 detect.py \
  --image /chemin/vers/image.jpg \
  --labels "compteur electrique" "disjoncteur" "borne de recharge" \
  --output outputs/result.jpg
```

Le script affiche les detections au format JSON et genere une image annotee.

## Entrainer ensuite

Le zero-shot est le meilleur point de depart: il permet de tester les legendes et les choix utilisateur sans attendre un dataset annote.

Pour entrainer vraiment le modele sur vos appareils, il faudra constituer un dataset avec:

- des images terrain;
- les objets attendus;
- les boites englobantes de chaque objet;
- les libelles associes.

Format conseille pour le dataset:

```text
datasets/appareils/
  train/
    images/
    annotations.json
  val/
    images/
    annotations.json
```

`annotations.json` doit contenir une liste d'images et de boites:

```json
[
  {
    "image": "images/photo-001.jpg",
    "objects": [
      {
        "label": "compteur electrique",
        "box": [120, 80, 340, 260]
      }
    ]
  }
]
```

Les boites sont au format `[x_min, y_min, x_max, y_max]`, en pixels.
