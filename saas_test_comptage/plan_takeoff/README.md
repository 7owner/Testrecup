# plan_takeoff — comptage déterministe des objets de légende

Compte les symboles (prises, luminaires, détecteurs, RJ45, BAES, caméras…) des
plans CFO/CFA/SSI, **sans ML, sans entraînement, sans annotation**. Deux voies :

1. **DWG (exacte)** : chaque symbole posé est une entité `INSERT` référençant un
   bloc nommé. Compter = additionner les INSERTs par bloc.
2. **PDF (import direct — le cas d'usage principal)** : les tracés AutoCAD sont
   vectoriels ; les symboles sont regroupés en glyphes, la légende imprimée
   fournit les gabarits + libellés (+ QTE déclarée quand elle existe), et chaque
   glyphe du plan est rattaché au gabarit correspondant par signature de forme
   (invariante rotation/translation/échelle). Validé sur ROI RENÉ : comptage PDF
   = comptage DWG au symbole près (18/5/4 caméras).

(L'approche vision d'avril — template matching, classifieur, k-means — reste dans
le dossier parent mais n'est plus la voie : elle re-détectait dans des pixels une
information déjà structurée dans les fichiers sources.)

## Usage

- **Interface web (recommandé)** : double-cliquer `Ouvrir_Interface_Comptage.bat`
  → une page s'ouvre dans le navigateur ; clique « Choisir des fichiers » ou
  glisse des plans dessus. Accepte **PDF** (estimation par forme) **et DWG**
  (comptage exact). Chaque ligne porte un indice de confiance :
  `exact` (DWG) · `= QTE` (colle à la quantité imprimée) · `à vérifier`
  (diffère de la QTE) · `estim.` (pas de QTE de référence).
  **Quand tu as le DWG, importe-le : le comptage est exact.**
- **PDF en lot (sans navigateur)** : glisser-déposer un PDF ou un dossier sur
  `Lancer_comptage_pdf.bat` (ou déposer dans `PDF_A_COMPTER\`).
- **DWG** : double-cliquer `Lancer_comptage_plans.bat` (traite
  `..\PLANS_COMPLETS_NEW`).

Ou en ligne de commande :

```
.venv\Scripts\python.exe takeoff.py --pdf "chemin\vers\plans.pdf|dossier" --out rapport_pdf
.venv\Scripts\python.exe takeoff.py --root "..\PLANS_COMPLETS_NEW" --out rapport
  --affaire "CROIX ROUGE"   # limiter a une affaire
  --refresh-cache           # forcer la relecture des DWG
```

## Sorties (`rapport/`)

- `index.html` — rapport auditable : par affaire/plan, tableau des quantités avec
  **vignette du symbole** (dessinée depuis la définition du bloc), zone/étage,
  calque ; lien vers l'**overlay SVG** du plan (un point coloré par objet compté,
  survolable) ; section « blocs exclus » (rien n'est retiré silencieusement).
- `comptage.csv` — consolidé (`;`, UTF-8 BOM, ouvrable dans Excel) :
  affaire / plan / zone / libellé légende / bloc / calque / quantité.
- `plans/*.json` + `plans/*.svg` — détail et overlay par plan.

## Comment ça marche

1. **Inventaire** : tous les `*.dwg` sous la racine (ignore `.bak`, dossiers
   `xref`/`old`/`PlotCfgs`) ; les `.zip` contenant des DWG sont extraits en cache.
2. **Lecture** : `tools/libredwg/dwgread.exe -O JSON` (LibreDWG 0.14, portable).
   Sanitisation `nan/inf`, résolution des handles, cache disque par hash fichier.
3. **Comptage** : INSERTs du **modèle-espace uniquement** (entmode 2). Pas
   d'expansion des blocs imbriqués : certains blocs anonymes sont des copies
   complètes d'étage, l'expansion doublerait le comptage.
4. **Résolution** : blocs anonymes (`*U…`, `A$C…`) rapprochés de leur jumeau
   nommé par empreinte géométrique de la définition ; blocs xref (`nom|bloc`)
   et annotations (flèches, cartouche — voir `config.json`) exclus mais listés.
5. **Légende** : si une légende existe (texte ancre `LEGENDE` en modèle-espace,
   paper space, ou dans une définition de bloc), les libellés sont appariés aux
   symboles et les exemplaires de légende retirés du comptage. Sinon le nom de
   bloc sert de libellé (les DWG Fauché nomment déjà les blocs comme la légende).
6. **Zones/étages** : si un DWG contient plusieurs niveaux côte à côte (MC2),
   clustering spatial + rattachement au titre le plus proche (RDC, R+1…).
   Désactivé quand le plan est mono-étage.

## Comment marche la voie PDF

1. `page.get_drawings()` : paths vectoriels **avec leur calque** (OCG AutoCAD
   préservé) ; les calques du fond de plan xref (`fichier|calque`) sont ignorés ;
   coordonnées ramenées au repère d'affichage (les tracés sont souvent tournés).
2. Clustering spatial des paths en glyphes (un symbole = un cluster).
3. Ancre texte `LEGENDE` → lignes libellé/QTE, gabarit = glyphe à gauche du
   libellé.
4. Signature de forme (rayons triés normalisés + signature de cœur qui ignore
   les appendices fusionnés type cône de visée) → chaque glyphe du plan est
   affecté au **meilleur** gabarit (pas de double compte). Garde de calque
   adaptative (activée seulement si le calque du gabarit est utilisé dans le plan).
5. Rapport : la colonne **QTE légende** compare le compté au déclaré (vert =,
   rouge ≠) ; overlay = page rendue + un cercle par objet compté (survolable) ;
   vignettes = extraits du PDF.

## Limites connues

### Voie PDF — précision mesurée (validée contre les DWG ROI RENÉ)

- **Symboles ponctuels discrets** (caméras, haut-parleurs, détecteurs, spots,
  appliques) : **fiable, ±1** (ex. caméras CFA-100 : 18/5/4 vs DWG 18/6/4).
- **Prises/câbles et grilles denses de symboles** (ex. patch-panels RJ45
  serrés) : **sous-comptage** — les symboles collés fusionnent en un bloc
  vectoriel unique (CFA-400 RJ45 : 35 comptés vs ~100). L'indice « à vérifier »
  le signale. **Pour ces cas, importe le DWG (exact).**
- Feuilles **multi-lots à légendes empilées** : comptage partiel, lignes à 0
  signalées.
- PDF scannés (raster) : non supportés (aucun dans le corpus).

### Pourquoi pas le template-matching raster (ancienne approche) ?

Testé et mesuré : sur ce corpus il fait **pire** — sur-comptage massif des formes
génériques (caméras CFA-100 : 109 détectées au lieu de 18, le gabarit corrèle
avec le fond) et ratés ailleurs, pour ~30 s/plan. La voie vectorielle est plus
sûre sur les symboles discrets ; le DWG reste la référence exacte.

### Voie DWG

- Les blocs anonymes non appariés apparaissent sous leur nom brut (`A$C…`) avec
  leur vignette — l'utilisateur arbitre visuellement.
- Le comptage reflète le contenu du DWG : un objet dessiné « à la main » (lignes
  libres, pas un bloc) n'est pas compté.
- PDF : utilisés pour recoupement visuel uniquement ; le comptage vectoriel PDF
  n'est pas la voie primaire (symboles aplatis en milliers de paths).
- DWG non lisible par LibreDWG → signalé « non parsé » dans le rapport, jamais
  de chiffre silencieusement faux.
