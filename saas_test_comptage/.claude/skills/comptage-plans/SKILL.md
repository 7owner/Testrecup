---
name: comptage-plans
description: Pipeline de comptage de symboles sur plans PDF (CFO/CFA/SSI/CVC) par détecteur Mask R-CNN entraîné sur dataset auto-étiqueté depuis les DWG. À utiliser pour toute tâche touchant saas_test_comptage/Test_No3 — régénérer le dataset, préparer/entraîner le zip Colab, évaluer, ou construire l'inférence plan-level et l'interface de dépôt de PDF.
---

# Comptage de symboles sur plans PDF

But produit : **l'utilisateur dépose un PDF, l'outil compte les objets de la légende.**
En production il n'y a **jamais de DWG**. Les DWG servent uniquement à fabriquer
gratuitement les étiquettes d'entraînement.

## Environnement

Python du projet : `plan_takeoff/.venv/Scripts/python.exe` (a `fitz`/PyMuPDF, `numpy`).
Il **n'a pas torch**. Pour manipuler un checkpoint : `~/AppData/Local/Programs/Python/Python312/python.exe`.
L'entraînement se fait sur **Colab GPU** (pas de GPU local).

Sous Git Bash, poser `PYTHONIOENCODING=utf-8` avant tout script qui imprime des
libellés accentués, sinon `UnicodeEncodeError` (console cp1252).

## Chaîne actuelle

```
DWG (+ xref architecture)  ──► render_dwg.py  ──► image réaliste + boîtes/masques exacts
                                    │  build_sheet / split_floors / render_floors_by_metier
                                    ▼
   make_dataset_seg.py (DWG apparié à un PDF) + make_dataset_more.py (DWG seul, tri par calque)
                                    ▼
                              4e_dataset/<AFFAIRE>_<METIER>/annotations.json  (COCO, noms de blocs BRUTS)
                                    │  colab/prepare_for_colab.py : canon() + tuilage 800/overlap 200
                                    │    + split STRATIFIÉ par plan + purge boîtes <2px
                                    │    + ~10% tuiles de FOND + zip
                                    ▼
                    colab/coco_colab.zip ──► colab/train_instance_seg.ipynb ──► model_final.pth
```

Commandes :

```bash
cd Test_No3
PY=../plan_takeoff/.venv/Scripts/python.exe
$PY bench.py                     # banc de vérité (compte DWG légende-exact) -> out/bench.csv
$PY make_dataset_seg.py          # régénère 4e_dataset (masques)
$PY qc_dataset.py 4e_dataset     # QC : dégénérées, masques valides
$PY colab/prepare_for_colab.py   # produit colab/coco_colab.zip
$PY canonical.py                 # audit : noms bruts -> classes canoniques
```

## Le dictionnaire canonique

`canonical.py::canon(nom)` ramène les ~222 noms de blocs bruts à **38 classes
fonctionnelles**, et renvoie `None` pour ce qu'il faut exclure (mobilier, en-têtes
de légende, blocs anonymes `A$C…`). Règles regex **ordonnées** : la première qui
matche gagne, donc spécifique avant générique — attention au **shadowing** (une règle
générique en amont peut voler un nom à une règle spécifique en aval ; déjà vu :
`baie sono` capté par `HAUT_PARLEUR` avant `BAIE_VDI`).

C'est la pièce centrale. Sans elle, le même objet porte un nom différent par
affaire (`Prise de Courant 10/16 A 2P+T` chez CROIX ROUGE vs `PC STANDARD 16A P+N+T`
chez ROI RENÉ) et le détecteur éclate sa probabilité entre synonymes.

**Mais un même nom de bloc recouvre parfois plusieurs symboles** (mesuré : `SA` =
31 carrés + 21 rectangles ; `Luminaire A 1300x300` = 274 allongés + 164 carrés).
Et surtout, **les entrées de légende sont plus fines que les classes canoniques**
(`Luminaire A 1300x300` et `Pavé Led 600x600` → tous deux `LUMINAIRE`). Le détecteur
seul ne peut donc pas produire le comptage par entrée de légende : il faut un
**second étage** qui reclasse chaque détection d'après la **géométrie de sa boîte**
(taille, élongation), qui sépare nettement les entrées d'une même famille.

Pour comparer deux symboles, utiliser une signature **invariante par rotation** :
`(sommets de l'enveloppe convexe, max(w,h)/min(w,h))`. Un ratio `w/h` brut fait
passer une rotation de 90° pour une forme nouvelle. Et le nombre de sommets est
bruité sur les courbes : `Caméra Dome` sort en 9, 10 ou 11 sommets — c'est un
cercle, pas trois symboles.

## Impasses — ne pas y revenir

- **Alignement DWG→PDF** : 4 tentatives (nuage de points, ancres texte, viewport
  analytique, étage propre), au mieux 6/24 inliers. Ces DWG bourrés d'xref ont des
  repères incohérents (symboles à ~millions d'unités, viewport à ~centaines).
  Code laissé dans `autolabel.py` / `align.py` pour mémoire. Remplacé par la
  méthode **B+xref** : on rend l'image depuis le DWG, repère qu'on contrôle.
- **Template-matching / KMeans** (dossier parent) : mono-plan, sous-compte
  lourdement (VDI −65 %, SSI −44 %). Abandonné.

## Pièges vécus

- `dwgread` est **lent** (~1-2 min/DWG). `_cache/` aide, mais `build_sheet` force
  `refresh=True` → re-parse. Dataset complet ≈ 30-40 min : lancer en arrière-plan.
- Un DWG model-space sert **plusieurs feuilles PDF** → toujours filtrer aux calques
  réellement tracés dans CE PDF.
- Un DWG contient souvent **plusieurs étages côte à côte** → `split_floors`.
- **Ne pas régresser** : appliquer l'ÉCHELLE d'insert à la géométrie du bloc
  (`render_dwg._rot_translate`), sinon boîtes sub-pixel (SSI) ou géantes (VDI).
- Les images CFO/CFA/SSI d'un même DWG ont le même `file_name` → les tuiles
  doivent être préfixées par l'id global (fait dans `prepare_for_colab`).
- **Tuiles de fond** : une tuile n'est du fond que si elle ne touche **aucune**
  boîte, même partiellement et même purgée. Une tuile qui rogne un symbole
  apprendrait au modèle à l'ignorer. Et leur quota se tire **globalement par
  split** : par image, `round(3 * 0.11) == 0` mange le vivier.
- **Colab** : sans `cfg.DATALOADER.FILTER_EMPTY_ANNOTATIONS = False`, detectron2
  jette silencieusement toutes les tuiles de fond.
- **CUDA OOM dans `pairwise_iou`** : `ANCHOR_GENERATOR.SIZES` attend **une liste par
  niveau FPN**. `[[8, 16, 32, 64, 128]]` (une seule liste) est diffusé à tous les
  niveaux → 15 ancres/position au lieu de 3, ~800k ancres sur une tuile 800 px. Croisé
  avec nos tuiles denses (jusqu'à **507 instances**), la matrice IoU dépasse le Go.
  Compléter au besoin par `RPN.PRE_NMS_TOPK_TRAIN=4000`, `POST_NMS_TOPK_TRAIN=1000`,
  `SOLVER.AMP.ENABLED=True`.
- **Diagnostiquer une classe ratée par CE QUE LE MODÈLE PRÉDIT À SON EMPLACEMENT**,
  pas par le nb de détections. Croiser chaque boîte-vérité de la classe avec les
  prédictions (toutes classes) par IoU : si le modèle tire mais met une autre
  étiquette = **confusion** (pas les ancres, pas les données brutes) ; s'il ne tire
  pas = recall. Sur ce projet, SUSPENSION/NOURRICE/BORNE_WIFI étaient de la confusion
  avec la classe dominante (LUMINAIRE), PAS un problème d'ancres — le correctif
  d'ancres (10/pos) a échoué et **baissé** le recall de NOURRICE.
- **Le correctif d'ancres a été une fausse piste.** Le calcul IoU géométrique
  (couverture 89 %) ne prédit PAS la détection réelle. Toujours valider une
  hypothèse par un run avant d'y croire ; ne pas empiler des changements théoriques.
- **Split par plan + peu de plans = piège de diversité.** Une classe présente dans
  ≤2 plans ne peut avoir un bon ratio train/val (50/50 ou 100/0 seulement).
  `stratified_split` force donc ses plans en train (règle mono-plan généralisée à
  ≤2). Corollaire : NOURRICE/BORNE_WIFI (2 plans BPCE) ne se réparent qu'avec **plus
  d'affaires**, pas par du réglage.
- **Le split doit compter les instances RÉALISÉES, pas les annotations brutes.**
  Certains plans ont des boîtes **dégénérées 0.5px** (rendu) concentrées sur les
  classes d'éclairage allongées (SUSPENSION 41 %, REGLETTE 22 %). Elles sont purgées
  au tuilage. Si le split les compte, il croit un plan riche d'une classe, le met en
  val, et la classe finit à 0 val réel (vécu run 4). `stratified_split` filtre donc
  par `bbox×scale >= MIN_BOX` (2026-07-13). Toujours vérifier le train/val au niveau
  TUILE dans le zip final, pas au niveau plan.
- **RepeatFactorSampler ne règle PAS la confusion des symboles d'éclairage allongés**
  (REGLETTE mesurable a échoué au run 4). Piste non testée : rendre à plus haute
  résolution (symboles ~10px, l'œil distingue le détail sur le PDF pleine réso, pas
  le modèle à cette taille).
- **Une classe à ~0 détection = souvent la GRILLE D'ANCRES, pas les données.** Le RPN
  ne propose que là où une ancre atteint IoU>=0.7. Un objet dont la **taille** tombe
  entre deux tailles d'ancres (progression géométrique = gros trous), ou dont
  l'**élongation** dépasse le ratio max, n'a jamais d'ancre positive → jamais détecté,
  même bien fourni (ex. NOURRICE 4:1, 515 inst. → 5 détectées ; SUSPENSION/WIFI carrées
  mais entre 2 tailles). Diagnostic : calculer le % de boîtes de la classe atteignant
  IoU>=0.7 contre le jeu d'ancres. Config qui couvre nos symboles :
  `SIZES=[[8,12],[16,24],[32,48],[64,96],[128,192]]` + `ASPECT_RATIOS=[[.25,.5,1,2,4]]*5`
  (= 10 ancres/pos ; **même nombre à tous les niveaux** car la tête RPN FPN est
  partagée). Repli si OOM : `ASPECT_RATIOS=[[.5,1,2,4]]*5` (8/pos).
- La cellule d'entraînement du notebook est **autonome** (réenregistre les datasets) :
  un redémarrage de runtime Colab ne doit pas obliger à tout réexécuter.
- `dwg_reader.py` (dans `plan_takeoff/`) est étendu de façon **additive**
  (`attribs`, `xref_path`, `scale`) : ne pas casser `plan_takeoff`.

## Lire une évaluation correctement

- Le **tuilage duplique les instances** (~×1,6) : un symbole entier dans deux tuiles
  qui se recouvrent est compté deux fois. Les comptes des cellules 6/6bis sont donc
  **tuile-level**, pas plan-level.
- L'AP moyenne sur beaucoup de classes est trompeuse. Regarder l'**AP par classe**,
  et l'écart AP50/AP75 (faible = localisation bonne, le problème est le rappel).
- `score_max = 0.00` sur une classe = le modèle ne tire **jamais** dessus → problème
  de données ou de synonyme, pas de seuil.
- **Aucun seuil global ne convient** : `Luminaire A 1300x300` compte juste vers 0,05,
  `TYPE 02 : LUMINAIRE` vers 0,3-0,5. Calibrer **un seuil par classe** sur le val.

## État & reste à faire (2026-07-11)

Dataset courant `coco_colab.zip` : **38 classes, train 466 tuiles (47 de fond = 10 %)
/ 9755 inst., val 83 (5 de fond) / 2597**. Split stratifié, boîtes <2 px purgées.

**2e entraînement fait** (`Test_No3/resultat_fine_tunning/`, iter 9319, loss 0.194) :
le regroupement canonique marche — **33/35 classes val détectées**, beaucoup à
score 1.00 ; SSI_*, VENTOUSE, POSTE_TRAVAIL bien calibrés. Reste à régler par le
seuil : LUMINAIRE / PRISE_COURANT / SPOT sur-détectent à seuil bas. Deux échecs
durs (pas un pb de seuil) : `NOURRICE` s'effondre (515 vérité, ~5 détections),
`SUSPENSION` + `BORNE_WIFI` = 0 détection. Métriques dans `run_outputs.zip`
(`metrics.json` + `coco_instances_results.json`) ; recalcul à la main car pas de
pycocotools local ; **compté-vs-vérité = TUILE-level** (×1,6), pas plan-level.

Fait : split stratifié · fond + purge · `POSTE_TRAVAIL` · fix OOM · 2e entraînement.
Reste, dans l'ordre :
1. **NOURRICE / SUSPENSION / BORNE_WIFI** : diagnostiquer sur images (forme étirée ?
   ancres ? hétérogénéité des sous-formes fusionnées ?).
2. **Seuil par classe** : `calibrate_thresholds.py` (fait, local) → `thresholds.json`.
   Le charger dans l'inférence. F1 macro 0.486 sur le run actuel ; classes fiables
   dès maintenant : SSI_FLASH, VENTOUSE, VIDEO_PROJ, HUBLOT, BAES, SPOT, POSTE_TRAVAIL.
3. **Inférence plan-level** (n'existe pas) : PDF → rendu DPI fixe → tuilage →
   détection → **fusion NMS inter-tuiles** → comptage. Scorer contre `bench.py`.
4. **Pont légende** : lire les libellés de la légende du PDF, mapper via `canon()`,
   puis 2e étage géométrique pour retrouver l'entrée fine (cf. `canon()` ci-dessus).
5. **UI web** de dépôt de PDF. Bases réutilisables dans le dossier parent :
   `plan_counter_ui/`, `instance_seg/dashboard_server.py`.

## Honnêteté (exigée par l'utilisateur)

« Le compte des boîtes colle au DWG » est **circulaire** : les boîtes SONT les symboles
DWG. Ça prouve la fidélité de l'étiquetage, pas qu'un détecteur comptera juste.
Seul l'AP val + le compté-vs-vérité sur plans **jamais vus** le prouve.
Ne jamais annoncer un résultat d'entraînement sans avoir lu les métriques.
