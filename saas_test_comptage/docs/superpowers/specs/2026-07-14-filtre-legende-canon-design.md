# Filtre de légende PDF + corrections de `canon()`

Design validé le 2026-07-14. Projet : `saas_test_comptage/Test_No3`.

## Problème

Le produit vise : l'utilisateur dépose un PDF, l'outil compte **les objets de la légende
de ce PDF**. Le détecteur Mask R-CNN sait déjà détecter 38 classes canoniques ; il manque
le pont qui relie une détection à une **entrée de légende** — c'est-à-dire au libellé que
l'utilisateur reconnaît.

Ce pont existe presque : `plan_takeoff/pdf_takeoff.py::find_legend_templates()` lit déjà la
légende d'un PDF vectoriel (libellé + glyphe gabarit + quantité déclarée), et
`Test_No3/canonical.py::canon()` ramène un libellé à l'une des 38 classes. Mesuré sur un
échantillon de PDF : **179 entrées sur 181 tombent sur une classe connue du détecteur, zéro
sur une classe inconnue.** Le pont est réel.

Mais il est inutilisable en l'état, pour deux raisons mesurées.

### 1. La zone de légende couvre 78 % de la page

Sur `Plans BPCE / DOE-FAU-04-CFA-NORD-N2-008-A-Plan VDI nord.pdf` (page 2384 × 1684) :

```
legend_rect = Rect(524, 1.7, 2384, 1684)      → 78 % de la feuille
130 « entrées » extraites, dont ~25 vraies
```

L'heuristique actuelle prend une bande allant de l'ancre « LEGENDE » jusqu'aux bords de la
page. Elle avale donc le plan lui-même : noms de locaux (« WC FEMMES », « Espace Café »),
surfaces (« S = 10,8 m² »), effectifs (« Effectif : 10p »), et jusqu'au nom de la rue
(« B o u l e v a r d d e D U N K E R Q U E »).

Conséquence directe : **122 des 181 entrées de l'échantillon finissent en `AUTRE_SYMBOLE`**,
la classe fourre-tout. Le bruit est invisible parce que `canon()` ne renvoie jamais `None`.

La vraie légende, dans ce même dump, est parfaitement identifiable : deux colonnes
(x ≈ 614–631 et x ≈ 850–870), y de 38 à 290, **lignes alignées à gauche et régulièrement
espacées**. Rien d'autre sur la feuille n'a cette structure.

### 2. `canon()` a des bugs, mais seulement côté légende

Mesure sur le dataset (`4e_dataset`, 222 noms bruts, 8002 instances) : `canon()` est déjà
quasi parfait — `AUTRE_SYMBOLE` ne pèse que **109 instances (1,4 %)**, réparties sur 6 noms
(`SA`, `PPMS`, `CA BP04`, `L-RDC-30`, `CA BP03`, `LUM TYPE 016`). **Le désastre des 67 %
d'`AUTRE_SYMBOLE` est entièrement côté légende PDF.**

Bugs vérifiés un par un sur des libellés réels :

| Libellé PDF | `canon()` rend | Devrait rendre | Cause |
|---|---|---|---|
| `Bloc d'Eclairage de Sécurité Autonome` | `AUTRE_SYMBOLE` | `BAES` | la règle `bloc d.eclairage securite` n'autorise pas le « de » |
| `PRISE RJ45 CAMERA DE SURVEILLANCE` | `CAMERA` | `PRISE_RJ45` | la règle `cam.ra` passe avant `rj45` (shadowing) |
| `Goulotte double compartiment` | `AUTRE_SYMBOLE` | `None` (exclu) | classe LINÉAIRE, écartée du dataset, mais pas de `canon()` |
| `Poste de réception vidéoportier` | `AUTRE_SYMBOLE` | `INTERPHONE` | synonyme manquant |
| `Tableau Général réseau Normal` | `AUTRE_SYMBOLE` | `TABLEAU_ELEC` | synonyme manquant |

Hypothèse écartée : ce **n'est pas** un problème d'accents. Une normalisation NFD des
libellés avant application des règles a été testée — elle déplace **0 instance sur 8002**
et ne répare aucun des cas ci-dessus.

Décision laissée en l'état : `Interrupteur SA normal` → `LUMINAIRE`. Les commandes
d'éclairage sont volontairement regroupées avec le lot éclairage, et le modèle a été
entraîné ainsi.

## Contraintes

- **Tout déterministe.** Aucun appel LLM dans le chemin de production. Le filtre s'appuie
  sur la structure du tableau de légende, testable sur les 64 PDF, sans coût ni latence.
- **`plan_takeoff` n'est pas touché.** `bench.py` utilise `pdf_takeoff.count_pdf()` comme
  colonne « méthode actuelle » ; la modifier déplacerait la ligne de base déjà mesurée
  (VDI −65 %, SSI −44 %).
- **Le modèle du run 4 ne doit pas être invalidé silencieusement.** `canon()` est appliqué
  au moment de l'empaquetage (`colab/prepare_for_colab.py`), donc toute correction du
  dictionnaire peut changer les classes du dataset et rendre `model_final.pth` et
  `thresholds.json` caducs.

## Architecture

Quatre fichiers, tous dans `Test_No3/`.

### `legend_pdf.py` — le lecteur

Nouveau module. Importe `pdf_takeoff.extract_page` (l'extraction des glyphes vectoriels
fonctionne bien, on ne la réécrit pas) et implémente sa propre détection de légende.

Interface publique :

```python
read_legend(pdf_path, page=0) -> LegendResult

LegendResult = {
    "entries":  [Entry],      # entrées retenues
    "columns":  [Rect],       # bbox des colonnes de légende (à exclure du comptage)
    "warnings": [str],        # ex. "aucune colonne de légende détectée"
}

Entry = {
    "label":        str,          # libellé lu dans le PDF
    "canon":        str | None,   # classe canonique, None si non reconnue (mode strict)
    "glyph_bbox":   [x0,y0,x1,y1],# gabarit : géométrie de référence du 2e étage
    "variants":     [cluster],    # glyphes contigus sous un même libellé (ex. 3 carrés RJ45)
    "qty_declared": int | None,   # quantité imprimée, seulement si colonne QTE valide
    "column":       int,          # index de la colonne d'origine
}
```

Algorithme `find_legend_columns(clusters, words)` :

1. **Lignes.** Regrouper les mots par `(block, line)` → texte, y, x0, hauteur.
   *(inchangé par rapport au code actuel)*
2. **Appariement.** Pour chaque ligne, prendre le glyphe crédible le plus proche **à gauche**,
   dans la bande verticale de la ligne, plus ses variantes contiguës de taille comparable.
   *(inchangé — cette partie du code actuel est correcte)*
3. **Colonnes.** Regrouper les paires (glyphe, libellé) par **x0 de libellé**, à une tolérance
   d'une hauteur de ligne près.
4. **Régularité verticale.** Dans chaque colonne, trier par y et ne garder que la **plus
   longue suite** de lignes dont l'écart entre lignes consécutives reste dans
   `[0.6 × pas_médian, 1.6 × pas_médian]`. C'est ce qui coupe la légende du plan.
5. **Seuils structurels.** Ne retenir une colonne que si : ≥ 4 lignes, **hauteur / largeur ≥ 3**
   (c'est une bande verticale), et ≥ 60 % des lignes portent un glyphe.

Les cinq constantes (`TOL_X` = 1 hauteur de ligne, `PITCH_LO` = 0.6, `PITCH_HI` = 1.6,
`MIN_ROWS` = 4, `MIN_GLYPH_RATIO` = 0.6) sont des valeurs de départ, à régler sur le banc.
6. La légende = l'union des colonnes retenues. Leurs bbox servent à exclure les glyphes
   gabarits du comptage.

Ces critères sont la transposition au PDF de ce que `plan_takeoff/legend_extract.py::
detect_legend_columns()` fait déjà côté DWG (« composante spatiale étroite h/l ≥ 3, ≥ 8
inserts, forte proportion de blocs distincts »). Ils tiennent sans le mot « LEGENDE »,
ce qui compte : certaines affaires n'en ont pas.

**`qty_declared`** n'est retenue que si la colonne de nombres est elle-même une colonne
alignée de la légende. Aujourd'hui les valeurs 80 / 160 / 353 observées sont des nombres
attrapés au hasard sur le plan ; les vraies entrées de ce plan n'ont **pas** de quantité.

### `canonical.py` — les corrections

Modifications des règles, chacune adossée à un libellé réel :

- `BAES` : `bloc d.eclairage securite` → `bloc.*eclairage.*s.curit`
- `PRISE_RJ45` remonté **avant** `CAMERA`
- `INTERPHONE` : ajouter `videoportier|visiophone`
- `TABLEAU_ELEC` : ajouter `tableau g.n.ral`
- `_EXCLUDE` : ajouter les classes **linéaires** (`goulotte`, `chemin de c.ble`) — elles sont
  déjà écartées du dataset, `canon()` doit rendre `None` et non `AUTRE_SYMBOLE`

Nouvelle signature :

```python
canon(name, strict=False) -> str | None
```

`strict=False` (défaut, inchangé) : renvoie `AUTRE_SYMBOLE` quand aucune règle ne matche.
C'est ce que le dataset attend — `AUTRE_SYMBOLE` est une classe entraînée.

`strict=True` (chemin légende) : renvoie `None`. Une entrée de légende non reconnue doit être
**signalée**, pas rangée silencieusement dans un fourre-tout : c'est un objet que l'outil ne
sait pas compter, et l'utilisateur doit le savoir.

### `test_canon_regression.py` — le garde-fou

Passe les 8002 instances de `4e_dataset` dans `canon()` et vérifie qu'**aucune ne change de
classe**, hors exceptions explicitement listées et justifiées dans le test.

C'est la pièce qui protège le modèle. Sans elle, une correction faite « pour la légende »
peut déplacer des classes du dataset et rendre `model_final.pth` + `thresholds.json` caducs
sans que personne ne le voie.

Ligne de base à figer dans le test : 222 noms bruts, 8002 instances, 109 en `AUTRE_SYMBOLE`
sur 6 noms.

### `score_legend.py` — le banc

Pour chaque paire DWG + PDF (`bench.py::find_pairs()`, ~24 paires), compare l'ensemble des
libellés lus dans le PDF par `read_legend()` à ceux que `plan_takeoff/legend_extract.py::
find_legend()` sort du **DWG**. Le PDF étant tracé depuis ce DWG, les libellés doivent être
les mêmes chaînes : l'appariement se fait par égalité après normalisation (espaces, casse,
accents).

Sortie : précision, rappel, F1 par plan et global → `out/legend_bench.csv`.

C'est le chiffre qui remplace « 122 entrées sur 181 en `AUTRE_SYMBOLE` » et qui dit si le
filtre marche. Il ne couvre pas les 40 PDF sans DWG apparié — limite assumée.

## Flux de données

```
PDF vectoriel
   │
   │  pdf_takeoff.extract_page()        (réutilisé tel quel)
   ▼
clusters (glyphes + bbox + calque) + words
   │
   │  legend_pdf.find_legend_columns()  (NOUVEAU : colonnes alignées + pas régulier)
   ▼
entrées de légende  ──►  canon(label, strict=True)  ──►  classe canonique | None
   │
   ▼
LegendResult { entries, columns, warnings }
   │
   └──►  (plus tard) fusion avec les détections du Mask R-CNN
```

Le module ne fait **que** lire la légende. L'inférence plan-level (rendu, tuilage,
détection, NMS) et la fusion détections × légende sont hors périmètre de cette spec.

## Gestion des erreurs

- **Aucune colonne détectée** → `entries = []` + un warning. Cas légitime : le plan de
  synthèse `COMPTAGE PLAN GENERAL IMPLANTATION.pdf` n'a pas de légende du tout.
- **Libellé non reconnu par `canon(strict=True)`** → l'entrée est retournée avec
  `canon = None`. Elle est comptée dans les entrées, mais signalée comme non comptable.
- **PDF non vectoriel** (scan) → `extract_page` ne rend aucun glyphe → aucune colonne →
  warning. Hors périmètre de traiter ce cas ici.

## Tests

Deux bancs, tous deux ancrés dans les données réelles du projet ; pas de test unitaire
synthétique.

1. `test_canon_regression.py` — le dataset ne bouge pas. Doit passer avant tout commit
   touchant `canonical.py`.
2. `score_legend.py` — précision / rappel du filtre contre la légende DWG, sur les ~24 paires.
   C'est la métrique de réussite du travail.

## Critère de réussite

Sur les paires DWG + PDF : le rappel et la précision des libellés de légende, mesurés contre
la légende DWG. À l'état actuel du code, la précision est catastrophique (≈ 25 vraies entrées
sur 130 extraites sur le plan BPCE, soit ~19 %). Le filtre doit remonter la précision sans
sacrifier le rappel.

Aucun seuil chiffré n'est fixé d'avance : le premier passage du banc donne la ligne de base,
et c'est cette mesure — pas une intuition — qui dira si l'approche par colonnes suffit.

## Hors périmètre

- L'inférence plan-level (rendu à 1800 px, tuilage 800/600, detectron2, seuils par classe,
  NMS inter-tuiles).
- Le 2e étage géométrique qui répartit une classe canonique entre plusieurs entrées de
  légende (`LUMINAIRE` couvre 5 libellés distincts).
- Les PDF scannés (non vectoriels).
- Le run 5 d'entraînement.
