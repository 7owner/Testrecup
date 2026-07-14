# Filtre de légende PDF + corrections de `canon()` — plan d'implémentation

> **Pour un agent :** SOUS-COMPÉTENCE REQUISE — utiliser superpowers:subagent-driven-development
> (recommandé) ou superpowers:executing-plans pour dérouler ce plan tâche par tâche.
> Les étapes sont cochables (`- [ ]`).

**Spec :** `docs/superpowers/specs/2026-07-14-filtre-legende-canon-design.md`

**But :** lire correctement la légende d'un PDF vectoriel (aujourd'hui 130 « entrées » pour
~25 vraies) et corriger les bugs de `canon()`, **sans invalider le modèle du run 4**.

**Architecture :** un nouveau module `Test_No3/legend_pdf.py` détecte la légende par sa
structure (colonnes de lignes alignées à pas vertical régulier) au lieu d'une bande de page ;
`Test_No3/canonical.py` gagne cinq corrections et un mode strict ; un test de régression
gèle la carte nom-brut → classe du dataset ; un banc score le lecteur contre la légende DWG.

**Stack :** Python 3, PyMuPDF (`fitz`), pytest. Pas de GPU, pas de LLM, pas de réseau.

## Contraintes globales

- **Python du projet : `plan_takeoff/.venv/Scripts/python.exe`** (a `fitz` 1.28, `numpy` 2.5).
  Il n'a **pas** torch — inutile ici.
- **Sous Git Bash, poser `PYTHONIOENCODING=utf-8`** avant tout script qui imprime des
  libellés accentués, sinon `UnicodeEncodeError` (console cp1252).
- **Ne pas modifier `plan_takeoff/`.** `bench.py` s'en sert comme ligne de base
  (« méthode actuelle »). Seul `pdf_takeoff.extract_page` est **importé**, jamais réécrit.
- **Ne pas déplacer les classes du dataset.** `canon()` est appliqué à l'empaquetage
  (`colab/prepare_for_colab.py`) : toute instance qui change de classe rend `model_final.pth`
  et `thresholds.json` caducs. Le test de régression de la tâche 1 est la garde ; il doit
  passer avant tout commit touchant `canonical.py`.
- **Aucun appel LLM.** Tout est déterministe.
- Ligne de base mesurée le 2026-07-13, à ne pas perdre de vue : `4e_dataset` = 222 noms
  bruts, 8002 instances, dont 109 en `AUTRE_SYMBOLE` sur 6 noms (`SA` 55, `PPMS` 30,
  `CA BP04` 18, `L-RDC-30` 4, `CA BP03` 1, `LUM TYPE 016` 1).

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `Test_No3/canonical.py` *(modifié)* | Nom brut ou libellé → classe canonique. Gagne 5 corrections + `strict=`. |
| `Test_No3/legend_pdf.py` *(créé)* | Lit la légende d'un PDF par détection de colonnes. Seul point d'entrée : `read_legend()`. |
| `Test_No3/score_legend.py` *(créé)* | Banc : légende PDF vs légende DWG → précision / rappel / F1. |
| `Test_No3/tests/make_canon_baseline.py` *(créé)* | Fige la carte nom→classe du dataset. Lancé **une fois**, avant toute correction. |
| `Test_No3/tests/canon_baseline.json` *(généré)* | La carte gelée. Committée. |
| `Test_No3/tests/test_canon.py` *(créé)* | Les 5 bugs + le mode strict, sur des libellés réels. |
| `Test_No3/tests/test_canon_regression.py` *(créé)* | Garde-fou : le dataset ne bouge pas. |
| `Test_No3/tests/test_legend_pdf.py` *(créé)* | Le lecteur, sur le PDF pathologique (BPCE VDI). |

---

## Tâche 1 : corriger `canon()` sous garde-fou de régression

**Fichiers :**
- Créer : `Test_No3/tests/make_canon_baseline.py`
- Créer : `Test_No3/tests/canon_baseline.json` (généré par le script ci-dessus)
- Créer : `Test_No3/tests/test_canon.py`
- Créer : `Test_No3/tests/test_canon_regression.py`
- Modifier : `Test_No3/canonical.py` (`_EXCLUDE` ligne 13, `_RULES` lignes 22-81, `canon()` ligne 86)

**Interfaces :**
- Consomme : rien.
- Produit : `canon(name: str, strict: bool = False) -> str | None`. `strict=False` (défaut,
  comportement actuel) renvoie `"AUTRE_SYMBOLE"` quand aucune règle ne matche ; `strict=True`
  renvoie `None`. Les deux renvoient `None` sur un nom exclu. **La tâche 2 appelle
  `canon(label, strict=True)`.**

**L'ordre des étapes est impératif :** la baseline doit être figée **avant** de toucher aux
règles, sinon elle gèle les bugs.

- [ ] **Étape 1 : installer pytest dans le venv du projet**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage
./plan_takeoff/.venv/Scripts/python.exe -m pip install pytest
```

Attendu : `Successfully installed pytest-...`

- [ ] **Étape 2 : écrire le générateur de baseline**

Créer `Test_No3/tests/make_canon_baseline.py` :

```python
"""Fige la carte nom_brut -> classe canonique des noms de 4e_dataset.

A LANCER UNE FOIS, AVANT toute correction de canonical.py : la baseline sert de
temoin. Si une correction "pour la legende" deplace une instance du dataset, le
modele du run 4 et thresholds.json deviennent caducs -- test_canon_regression.py
le detecte en comparant a ce fichier.
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from canonical import canon  # noqa: E402

counts = Counter()
for f in sorted((HERE.parent / "4e_dataset").glob("*/annotations.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in d["categories"]}
    for a in d["annotations"]:
        counts[cats[a["category_id"]]] += 1

out = {
    "mapping": {nm: canon(nm) for nm in sorted(counts)},
    "counts": dict(counts),
}
(HERE / "canon_baseline.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(counts)} noms bruts, {sum(counts.values())} instances -> canon_baseline.json")
```

- [ ] **Étape 3 : générer la baseline et vérifier les chiffres**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe tests/make_canon_baseline.py
```

Attendu, **exactement** : `222 noms bruts, 8002 instances -> canon_baseline.json`

Si les chiffres diffèrent, `4e_dataset` a changé depuis la mesure du 2026-07-13 : **arrêter
et le signaler**, ne pas continuer avec une baseline inconnue.

- [ ] **Étape 4 : écrire les tests des 5 bugs (ils doivent échouer)**

Créer `Test_No3/tests/test_canon.py` :

```python
"""canon() sur des libelles REELS lus dans les legendes PDF (sonde du 2026-07-13)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canonical import canon  # noqa: E402


def test_baes_tolere_le_de_au_milieu():
    # la regle s'ecrivait "bloc d.eclairage securite" : pas de place pour le "de"
    assert canon("Bloc d'Eclairage de Sécurité Autonome") == "BAES"


def test_baes_forme_deja_correcte_ne_regresse_pas():
    assert canon("BLOC AUTONOME D'ECLAIRAGE DE SECURITE") == "BAES"


def test_prise_rj45_de_camera_est_une_prise():
    # shadowing : la regle CAMERA passait avant la regle RJ45
    assert canon("PRISE RJ45 CAMERA DE SURVEILLANCE") == "PRISE_RJ45"


def test_camera_seule_reste_une_camera():
    assert canon("Caméra surveillance") == "CAMERA"


def test_prise_rj45_pour_borne_wifi_reste_une_prise():
    assert canon("PRISE RJ45 POUR BORNE WIFI") == "PRISE_RJ45"


def test_videoportier_est_un_interphone():
    assert canon("Poste de réception vidéoportier") == "INTERPHONE"


def test_tableau_general_est_un_tableau_elec():
    assert canon("Tableau Général réseau Normal") == "TABLEAU_ELEC"


def test_tableau_d_alarme_incendie_reste_un_tableau_ssi():
    assert canon("TABLEAU D'ALARME INCENDIE") == "SSI_TABLEAU"


def test_goulotte_est_exclue():
    # classe LINEAIRE : deja ecartee du dataset en amont, canon doit rendre None
    assert canon("Goulotte double compartiment") is None


def test_mode_strict_signale_l_inconnu():
    inconnu = "Sèche main électrique"
    assert canon(inconnu) == "AUTRE_SYMBOLE"        # defaut : le dataset attend cette classe
    assert canon(inconnu, strict=True) is None      # legende : signaler, pas ranger


def test_mode_strict_ne_change_rien_quand_une_regle_matche():
    assert canon("Caméra surveillance", strict=True) == "CAMERA"


def test_mode_strict_conserve_les_exclusions():
    assert canon("A$C1234") is None
    assert canon("A$C1234", strict=True) is None
```

- [ ] **Étape 5 : lancer les tests, vérifier qu'ils échouent**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/test_canon.py -v
```

Attendu : **5 échecs** — `test_baes_tolere_le_de_au_milieu` (rend `AUTRE_SYMBOLE`),
`test_prise_rj45_de_camera_est_une_prise` (rend `CAMERA`), `test_videoportier_est_un_interphone`
(rend `AUTRE_SYMBOLE`), `test_tableau_general_est_un_tableau_elec` (rend `AUTRE_SYMBOLE`),
`test_goulotte_est_exclue` (rend `AUTRE_SYMBOLE`). Plus `test_mode_strict_signale_l_inconnu`
qui échoue sur `TypeError: canon() got an unexpected keyword argument 'strict'`, ainsi que
les deux autres tests de mode strict. Les tests « ne régresse pas » doivent **passer** dès
maintenant.

- [ ] **Étape 6 : écrire le garde-fou de régression**

Créer `Test_No3/tests/test_canon_regression.py` :

```python
"""GARDE-FOU DU MODELE.

canon() est applique a l'empaquetage (colab/prepare_for_colab.py). Toute correction du
dictionnaire faite "pour la legende" peut deplacer des classes du DATASET, et donc rendre
model_final.pth + thresholds.json caducs -- sans que rien ne le signale.

Ce test verifie qu'AUCUNE instance de 4e_dataset ne change de classe par rapport a la
baseline gelee. Une exception doit etre listee ET justifiee dans EXCEPTIONS.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from canonical import canon  # noqa: E402

BASELINE = json.loads((HERE / "canon_baseline.json").read_text(encoding="utf-8"))

# nom_brut -> (classe_avant, classe_apres, justification)
# Vide = le dataset ne bouge pas, le modele reste valide.
EXCEPTIONS: dict[str, tuple[str, str, str]] = {}


def test_la_baseline_est_celle_qu_on_croit():
    assert len(BASELINE["mapping"]) == 222
    assert sum(BASELINE["counts"].values()) == 8002


def test_aucune_instance_du_dataset_ne_change_de_classe():
    mapping = BASELINE["mapping"]
    counts = BASELINE["counts"]
    moved = {}
    for nm, avant in mapping.items():
        apres = canon(nm)
        if apres != avant and nm not in EXCEPTIONS:
            moved[nm] = (avant, apres, counts[nm])
    detail = "\n".join(
        f"  {n:>5} inst.  {a} -> {b}   {nm}"
        for nm, (a, b, n) in sorted(moved.items(), key=lambda kv: -kv[1][2]))
    total = sum(n for _, _, n in moved.values())
    assert not moved, (
        f"{total} instances du dataset changent de classe : le modele du run 4 et "
        f"thresholds.json deviennent caducs.\n{detail}\n"
        "Soit la regle est trop large (corrige-la), soit le deplacement est voulu "
        "(liste-le dans EXCEPTIONS avec sa justification, et prevois un run 5).")


def test_les_exceptions_declarees_correspondent_a_la_realite():
    mapping = BASELINE["mapping"]
    for nm, (avant, apres, _why) in EXCEPTIONS.items():
        assert mapping[nm] == avant, f"{nm} : la baseline dit {mapping[nm]}, pas {avant}"
        assert canon(nm) == apres, f"{nm} : canon() rend {canon(nm)}, pas {apres}"
```

- [ ] **Étape 7 : lancer le garde-fou sur le code NON corrigé, vérifier qu'il passe**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/test_canon_regression.py -v
```

Attendu : **3 passed**. Le garde-fou est un témoin : sur le code d'origine il doit être vert.
S'il est rouge ici, la baseline est incohérente — arrêter.

- [ ] **Étape 8 : corriger `canonical.py`**

Cinq modifications, chacune adossée à un libellé réel.

**8a.** `_EXCLUDE` (ligne 13) — ajouter les classes **linéaires**, déjà écartées du dataset
en amont mais que `canon()` rangeait dans `AUTRE_SYMBOLE`. Ajouter `goulotte|chemin de c.ble`
à l'alternance :

```python
_EXCLUDE = re.compile(
    r"^A\$C|FAU_Type|idloc|^h:\d|under the bell|susp lily|Krusning|^A.{1,2}ria$|"
    r"Groupe-\d|^DAIKIN$|^code alarme$|REPROGRAPHIE|^R-\d|PHOTOCOPIEUR|"
    r"Ecran TV|Ecran de supervision|^Courant faible$|"
    r"^S.curit. incendie$|^Eclairage$|RESERVATION|RACCOREDEMENT|^SR$|^BP$|"
    r"Ecran de sup|"
    r"goulotte|chemin de c.ble",          # classes LINEAIRES : jamais comptees
    re.IGNORECASE)
```

**8b.** Déplacer la règle `PRISE_RJ45` **avant** `CAMERA`. Dans `_RULES`, supprimer la ligne
`(r"rj45|prise standard rj", "PRISE_RJ45"),` de la section VDI, et l'insérer juste avant la
règle CAMERA, avec le commentaire qui explique pourquoi :

```python
    # ---- Videosurveillance / interphonie / AV ----
    # PRISE_RJ45 passe AVANT CAMERA : "PRISE RJ45 CAMERA DE SURVEILLANCE" est une PRISE,
    # pas une camera. La regle `cam.ra` la volait (shadowing).
    (r"rj45|prise standard rj", "PRISE_RJ45"),
    (r"cam.ra|camera", "CAMERA"),
    (r"interphon|combine interieur|appel eas|platine de rue|poste viso|videophone|"
     r"vid.oportier|visiophon", "INTERPHONE"),
```

Dans la section VDI, à l'emplacement laissé vide, mettre un commentaire :

```python
    (r"baie (vdi|sono)|vdi ?- ?baie|^baie", "BAIE_VDI"),   # capte aussi "Baie 42U"
    # NB : la regle rj45 est remontee plus haut (avant CAMERA) -- voir commentaire la-bas.
    (r"hdmi", "PRISE_HDMI"),
```

**8c.** `BAES` — la règle exigeait « eclairage securite » collés. Élargir :

```python
    (r"baes|bloc autonome.*eclairage|bloc.*eclairage.*s.curit|bapi", "BAES"),
```

**8d.** `TABLEAU_ELEC` — ajouter `tableau g.n.ral` :

```python
    (r"tableau divisionnaire|tableau g.n.ral|tgbt|coffret", "TABLEAU_ELEC"),
```

**8e.** `canon()` (ligne 86) — le mode strict :

```python
def canon(name: str, strict: bool = False):
    """Nom brut ou libelle de legende -> label canonique, ou None.

    strict=False (defaut) : ce qui ne matche aucune regle tombe dans AUTRE_SYMBOLE.
        C'est ce que le DATASET attend -- AUTRE_SYMBOLE est une classe entrainee.
    strict=True (chemin LEGENDE) : renvoie None. Une entree de legende non reconnue
        doit etre SIGNALEE a l'utilisateur ("je ne sais pas compter ca"), pas rangee
        silencieusement dans un fourre-tout.
    """
    s = (name or "").strip()
    if not s or _EXCLUDE.search(s):
        return None
    for rx, lbl in _COMPILED:
        if rx.search(s):
            return lbl
    return None if strict else "AUTRE_SYMBOLE"
```

- [ ] **Étape 9 : lancer les deux fichiers de test**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/ -v
```

Attendu : **tout passe.**

**Si `test_aucune_instance_du_dataset_ne_change_de_classe` échoue :** ne pas le contourner.
Le message liste les noms et le nombre d'instances déplacées. Deux cas, et un seul est
acceptable sans décision humaine :
- la règle élargie est **trop large** (elle capte un nom qu'elle ne devrait pas) → resserrer
  la règle et relancer ;
- le déplacement est **juste sur le fond** (le nom était mal classé) → **s'arrêter et le
  remonter à l'utilisateur** : accepter le déplacement veut dire réempaqueter le dataset
  (`colab/prepare_for_colab.py`) et **réentraîner (run 5)**, et recalibrer `thresholds.json`.
  C'est sa décision, pas la tienne.

- [ ] **Étape 10 : commit**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage
git add Test_No3/canonical.py Test_No3/tests/
git commit -m "fix(canon): BAES avec 'de', RJ45 avant CAMERA, videoportier, tableau general, goulotte exclue + mode strict

Bugs mesures sur des libelles reels de legendes PDF (sonde 2026-07-13).
Garde-fou de regression : les 8002 instances de 4e_dataset ne changent pas
de classe, le modele du run 4 reste valide."
```

---

## Tâche 2 : `legend_pdf.py` — le lecteur par colonnes

**Fichiers :**
- Créer : `Test_No3/legend_pdf.py`
- Créer : `Test_No3/tests/test_legend_pdf.py`

**Interfaces :**
- Consomme : `canon(label, strict=True)` de la tâche 1 ; `pdf_takeoff.extract_page(page)`
  (existant, non modifié) qui rend `(clusters, words)`. Un `cluster` est un dict
  `{"bbox": [x0,y0,x1,y1], "layer": str, "pts": [(x,y)], "ops": tuple, "n_paths": int}` ;
  un `word` est le tuple PyMuPDF `(x0, y0, x1, y1, texte, block, line, word)`.
- Produit :
  ```python
  read_legend(pdf_path: Path | str, page_no: int = 0) -> dict
  # {"entries": [Entry], "columns": [[x0,y0,x1,y1]], "warnings": [str]}
  # Entry = {"label": str, "canon": str | None, "glyph_bbox": [x0,y0,x1,y1],
  #          "variants": [cluster], "qty_declared": int | None, "column": int}
  build_legend(clusters: list, words: list) -> dict   # meme sortie, sans I/O
  ```
  **La tâche 3 appelle `read_legend()`.**

- [ ] **Étape 1 : vérifier la prémisse avant d'écrire 200 lignes**

Toute l'approche repose sur une hypothèse : *dans une vraie légende, les libellés partagent
le même x0 et les lignes ont un pas vertical régulier.* Le dump du 2026-07-13 le montrait sur
les **glyphes** ; il faut le confirmer sur les **libellés**.

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage
PYTHONIOENCODING=utf-8 ./plan_takeoff/.venv/Scripts/python.exe - <<'PY'
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "plan_takeoff")
import fitz
from pdf_takeoff import extract_page

PDF = Path("PLANS_COMPLETS_NEW/PLANS/Plans BPCE/"
           "DOE-FAU-04-CFA-NORD-N2-008-A-Plan VDI nord.pdf")
doc = fitz.open(PDF); page = doc[0]
_, words = extract_page(page); doc.close()

lines = defaultdict(list)
for w in words:
    lines[(w[5], w[6])].append(w)
rows = []
for ws in lines.values():
    ws.sort(key=lambda w: w[0])
    rows.append((min(w[0] for w in ws),
                 sum((w[1] + w[3]) / 2 for w in ws) / len(ws),
                 " ".join(w[4] for w in ws).strip()))
# la legende de ce plan vit dans y < 320 (mesure du dump)
for x0, y, t in sorted(r for r in rows if r[1] < 320):
    print(f"x0={x0:8.1f}  y={y:7.1f}  {t[:60]}")
PY
```

Attendu : deux paquets de lignes, l'un autour d'un x0 commun (≈ 640), l'autre autour d'un
second (≈ 880), chacun avec un y qui progresse par pas réguliers (~12-14 pt).

**Si les libellés ne sont PAS alignés en x**, l'approche par colonnes tombe : s'arrêter et
le remonter à l'utilisateur avant d'écrire le module.

- [ ] **Étape 2 : écrire le test (il doit échouer : le module n'existe pas)**

Créer `Test_No3/tests/test_legend_pdf.py` :

```python
"""Le PDF pathologique. find_legend_templates() (plan_takeoff) en sort 130 "entrees"
pour ~25 vraies : sa zone de legende couvre 78 % de la page et avale le plan.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from legend_pdf import read_legend  # noqa: E402

PDF = (HERE.parents[1] / "PLANS_COMPLETS_NEW" / "PLANS" / "Plans BPCE"
       / "DOE-FAU-04-CFA-NORD-N2-008-A-Plan VDI nord.pdf")


@pytest.fixture(scope="module")
def legende():
    assert PDF.exists(), f"PDF de test introuvable : {PDF}"
    return read_legend(PDF)      # ~25 s : extract_page est lent sur ce plan


def test_le_texte_du_plan_a_disparu(legende):
    labels = {e["label"] for e in legende["entries"]}
    for bruit in ("WC FEMMES", "Rayonnage", "Confidentiel", "Fontaine"):
        assert bruit not in labels, f"{bruit!r} est un texte du plan, pas une entree"
    rue = [l for l in labels if "DUNKERQUE" in l.upper()]
    assert not rue, f"nom de rue capte comme entree de legende : {rue}"


def test_les_vraies_entrees_sont_la(legende):
    labels = {e["label"] for e in legende["entries"]}
    for vraie in ("Caméra surveillance", "Prise RJ45", "Attente HDMI",
                  "Flash lumineux d'alarme incendie", "Contacteur intrusion"):
        assert vraie in labels, f"entree de legende perdue : {vraie!r}"


def test_le_nombre_d_entrees_est_plausible(legende):
    n = len(legende["entries"])
    assert 15 <= n <= 45, f"{n} entrees ; la legende de ce plan en compte ~25"


def test_aucune_quantite_inventee(legende):
    # ce plan n'a AUCUNE colonne QTE : les 80/160/353 observes le 2026-07-13 etaient
    # des nombres du plan (effectifs, surfaces) attrapes par un alignement fortuit.
    inventees = [(e["label"], e["qty_declared"])
                 for e in legende["entries"] if e["qty_declared"] is not None]
    assert not inventees, f"quantites inventees : {inventees}"


def test_chaque_entree_porte_un_gabarit(legende):
    for e in legende["entries"]:
        x0, y0, x1, y1 = e["glyph_bbox"]
        assert x1 > x0 and y1 > y0, f"gabarit degenere pour {e['label']!r}"


def test_les_entrees_sont_mappees_ou_signalees(legende):
    # canon(strict=True) : soit une classe du detecteur, soit None (= "je ne sais pas
    # compter ca"). Jamais AUTRE_SYMBOLE, qui masquerait le probleme.
    for e in legende["entries"]:
        assert e["canon"] != "AUTRE_SYMBOLE"
```

- [ ] **Étape 3 : lancer le test, vérifier qu'il échoue**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/test_legend_pdf.py -v
```

Attendu : `ModuleNotFoundError: No module named 'legend_pdf'` (erreur de collecte).

- [ ] **Étape 4 : écrire le module**

Créer `Test_No3/legend_pdf.py` :

```python
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
MIN_ROWS = 4            # une colonne de legende a au moins 4 lignes
MIN_ASPECT = 3.0        # hauteur / largeur : une colonne est une bande VERTICALE
MIN_GLYPH_RATIO = 0.6   # part des lignes qui doivent porter un glyphe

_NUM = re.compile(r"^\d{1,4}$")
_BAD_LABEL = re.compile(
    r"^(ECHELLE|DATE|IND\b|DESIGNATION|DESSINATEUR|OPERATION|NIVEAU|PLAN\b|PLA\b|FAU-"
    r"|ADRESSE|TEL[. ]|FAX|MAIRIE|AGENCE|LOT\b|DOE\b|EXE\b|DCE\b"
    r"|QTE|QUANTITES?|LEGENDE|L.GENDE|SYMBOLES?)",
    re.IGNORECASE)


# ---------------------------------------------------------------- lignes de texte

def _rows_from_words(words):
    """Mots PyMuPDF -> (lignes de libelle, lignes purement numeriques).

    Une ligne = un couple (block, line) de PyMuPDF. Les lignes numeriques sont mises de
    cote : elles ne deviennent une quantite que si elles forment une VRAIE colonne QTE
    (cf. _qty_column) -- sinon ce sont des nombres du plan.
    """
    grouped = defaultdict(list)
    for w in words:
        grouped[(w[5], w[6])].append(w)

    labels, qtys = [], []
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
        if _NUM.fullmatch(text):
            qtys.append(row)
        elif len(text) >= 3 and not _BAD_LABEL.search(text):
            labels.append(row)
    return labels, qtys


# ---------------------------------------------------------------- glyphes

def _credible(c):
    """Un trait isole n'est pas un symbole."""
    return not (c["n_paths"] < 2 and sum(n for _, n in c["ops"]) < 3)


def _diag(c):
    b = c["bbox"]
    return math.hypot(b[2] - b[0], b[3] - b[1])


def _pair_glyph(row, clusters, used):
    """Glyphe le plus proche A GAUCHE du libelle, + ses variantes contigues.

    Les variantes : plusieurs glyphes contigus de taille comparable sous un seul libelle
    (ex. RJ45 = 3 carres cote a cote). On s'arrete au premier grand trou pour ne pas happer
    un symbole decoratif eloigne. Logique reprise telle quelle de pdf_takeoff (elle est
    correcte -- c'est la ZONE qui etait fausse, pas l'appariement).

    Retourne (index, cluster) du glyphe principal et la liste [(index, cluster)] des
    variantes, ou (None, []) si aucun candidat.
    """
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
    if not cand:
        return None, []

    cand.sort(key=lambda ic: -ic[1]["bbox"][2])   # du plus proche du libelle, vers la gauche
    primary = cand[0]
    pdiag = _diag(primary[1]) or 1.0
    chosen = [primary]
    left = primary[1]["bbox"][0]
    for ci, c in cand[1:]:
        if left - c["bbox"][2] > pdiag * 2.0:     # grand trou : on arrete
            break
        if 0.4 * pdiag <= _diag(c) <= 2.5 * pdiag:
            chosen.append((ci, c))
            left = min(left, c["bbox"][0])
    return primary, chosen


# ---------------------------------------------------------------- colonnes

def _group_columns(pairs):
    """Regroupe les paires (glyphe, libelle) par x0 de LIBELLE."""
    cols = []
    for p in sorted(pairs, key=lambda p: p["row"]["x0"]):
        for col in cols:
            if abs(p["row"]["x0"] - col["x0"]) <= TOL_X * p["row"]["h"]:
                col["items"].append(p)
                col["x0"] = sum(q["row"]["x0"] for q in col["items"]) / len(col["items"])
                break
        else:
            cols.append({"x0": p["row"]["x0"], "items": [p]})
    return cols


def _longest_regular_run(items):
    """Dans une colonne : la plus longue suite de lignes a pas vertical regulier.

    C'est l'etape qui COUPE la legende du plan : les textes du plan qui partagent par hasard
    le x0 d'une colonne n'ont aucune raison d'en respecter le pas vertical.
    """
    items = sorted(items, key=lambda p: p["row"]["y"])
    if len(items) < 2:
        return items
    gaps = [items[i + 1]["row"]["y"] - items[i]["row"]["y"] for i in range(len(items) - 1)]
    med = sorted(gaps)[len(gaps) // 2] or 1.0
    lo, hi = PITCH_LO * med, PITCH_HI * med

    best, cur = [], [items[0]]
    for i, g in enumerate(gaps):
        if lo <= g <= hi:
            cur.append(items[i + 1])
        else:
            if len(cur) > len(best):
                best = cur
            cur = [items[i + 1]]
    return cur if len(cur) > len(best) else best


def _col_bbox(run):
    xs = [p["row"]["x0"] for p in run]
    ys = [p["row"]["y"] for p in run]
    for p in run:
        if p["glyph"]:
            xs.append(p["glyph"][1]["bbox"][0])
    return [min(xs), min(ys), max(xs), max(ys)]


def _valid_column(run):
    """Une colonne de legende : assez de lignes, en bande verticale, majoritairement
    porteuse de glyphes."""
    if len(run) < MIN_ROWS:
        return False
    x0, y0, x1, y1 = _col_bbox(run)
    w = max(x1 - x0, 1.0)
    h = y1 - y0
    if h / w < MIN_ASPECT:
        return False
    with_glyph = sum(1 for p in run if p["glyph"])
    return with_glyph / len(run) >= MIN_GLYPH_RATIO


# ---------------------------------------------------------------- quantites

def _qty_column(qty_rows, run):
    """Les lignes numeriques ne sont une colonne QTE que si elles sont DANS l'etendue en y
    de la colonne de legende, A DROITE des libelles, et alignees entre elles.

    Sans cette garde, on ramasse les nombres du plan : sur le plan VDI de BPCE, les valeurs
    80 / 160 / 353 observees le 2026-07-13 etaient des effectifs et des surfaces.
    """
    y0 = min(p["row"]["y"] for p in run)
    y1 = max(p["row"]["y"] for p in run)
    x_lab = max(p["row"]["x0"] for p in run)
    cand = [q for q in qty_rows if y0 - 8 <= q["y"] <= y1 + 8 and q["x0"] > x_lab]
    if len(cand) < MIN_ROWS:
        return []
    xs = sorted(q["x0"] for q in cand)
    med = xs[len(xs) // 2]
    cand = [q for q in cand if abs(q["x0"] - med) <= 2 * q["h"]]
    return cand if len(cand) >= MIN_ROWS else []


# ---------------------------------------------------------------- API

def build_legend(clusters, words):
    """clusters + words (de pdf_takeoff.extract_page) -> legende. Sans I/O."""
    label_rows, qty_rows = _rows_from_words(words)

    # 1re passe : apparier SANS reserver les glyphes. Une ligne de bruit ne doit pas voler
    # le glyphe d'une vraie entree avant qu'on ait decide qui est bruit.
    pairs = []
    for row in label_rows:
        glyph, variants = _pair_glyph(row, clusters, used=set())
        pairs.append({"row": row, "glyph": glyph, "variants": variants})

    runs = []
    for col in _group_columns(pairs):
        run = _longest_regular_run(col["items"])
        if _valid_column(run):
            runs.append(run)
    runs.sort(key=lambda r: _col_bbox(r)[0])

    # 2e passe, sur les seules colonnes retenues : cette fois on reserve les glyphes pour
    # qu'une entree n'en vole pas une autre.
    entries, columns = [], []
    used = set()
    for ci, run in enumerate(runs):
        qty_rows_col = _qty_column(qty_rows, run)
        for p in sorted(run, key=lambda p: p["row"]["y"]):
            row = p["row"]
            glyph, variants = _pair_glyph(row, clusters, used)
            if glyph is None:
                continue
            for gi, _ in variants:
                used.add(gi)
            qty = next((int(q["text"]) for q in qty_rows_col
                        if abs(q["y"] - row["y"]) < 8), None)
            entries.append({
                "label": row["text"],
                "canon": canon(row["text"], strict=True),
                "glyph_bbox": list(glyph[1]["bbox"]),
                "variants": [c for _, c in variants],
                "qty_declared": qty,
                "column": ci,
            })
        columns.append(_col_bbox(run))

    warnings = []
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
        print(f"!! {w}")
    print(f"{len(res['entries'])} entrees, {len(res['columns'])} colonne(s)\n")
    print(f"{'col':>3} {'qte':>4}  {'canon':<22} libelle")
    print("-" * 90)
    for e in res["entries"]:
        print(f"{e['column']:>3} {str(e['qty_declared']):>4}  "
              f"{str(e['canon']):<22} {e['label'][:55]}")
```

- [ ] **Étape 5 : lancer le test**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/test_legend_pdf.py -v
```

Attendu : **6 passed** (comptez ~30 s, `extract_page` est lent sur ce plan).

Si `test_le_nombre_d_entrees_est_plausible` échoue **par le haut** (trop d'entrées), une
colonne de bruit passe : durcir `MIN_ASPECT` ou `MIN_GLYPH_RATIO`. S'il échoue **par le bas**
(pas assez), la coupe est trop agressive : élargir `PITCH_HI`. Ne changer **qu'une constante
à la fois** et relancer — c'est la leçon du correctif d'ancres du 2026-07-12, où plusieurs
changements empilés ont rendu l'échec inanalysable.

- [ ] **Étape 6 : regarder la sortie à l'œil, pas seulement le test**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe legend_pdf.py \
  "../PLANS_COMPLETS_NEW/PLANS/Plans BPCE/DOE-FAU-04-CFA-NORD-N2-008-A-Plan VDI nord.pdf"
```

Attendu : ~25 lignes, deux colonnes, des libellés qui ressemblent tous à des symboles, et
aucune quantité. Un `canon` à `None` de temps en temps est normal (« Sèche main électrique » :
l'outil ne sait pas le compter, et il le dit). Une avalanche de `None` est un signal — la
légende est peut-être mal coupée.

- [ ] **Étape 7 : commit**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage
git add Test_No3/legend_pdf.py Test_No3/tests/test_legend_pdf.py
git commit -m "feat(legende): lecteur PDF par colonnes alignees

Remplace la bande de page de find_legend_templates (78 % de la feuille, 130
'entrees' pour ~25 vraies) par une detection de la STRUCTURE : colonnes de
lignes alignees a pas vertical regulier. plan_takeoff n'est pas touche."
```

---

## Tâche 3 : `score_legend.py` — le banc contre la légende DWG

**Fichiers :**
- Créer : `Test_No3/score_legend.py`
- Sortie : `Test_No3/out/legend_bench.csv`

**Interfaces :**
- Consomme : `legend_pdf.read_legend(pdf)` (tâche 2) ; `bench.find_pairs()` (existant) ;
  `plan_takeoff` : `dwg_reader.extract_plan`, `block_resolver.resolve_blocks` /
  `annotate_inserts`, `legend_extract.find_legend` / `detect_legend_columns` — l'enchaînement
  exact des lignes 71-76 de `plan_takeoff/takeoff.py::process_plan`.
- Produit : `out/legend_bench.csv` + un résumé console. Rien que la tâche 4 importe.

- [ ] **Étape 1 : écrire le banc**

Créer `Test_No3/score_legend.py` :

```python
"""Banc du lecteur de legende : legende lue dans le PDF vs legende lue dans le DWG.

Le PDF est TRACE depuis le DWG : les libelles de legende sont les memes chaines. Le DWG
fournit donc une verite gratuite, dans l'esprit du reste du projet (les DWG servent a
fabriquer la verite, jamais a la production).

Precision = part des entrees trouvees dans le PDF qui existent vraiment dans la legende.
Rappel    = part des entrees de la legende DWG qu'on retrouve dans le PDF.

Sortie : out/legend_bench.csv + resume console.
Usage  : PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe score_legend.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "plan_takeoff"))

from bench import find_pairs                                     # noqa: E402
from autolabel import detect_metier, CACHE                       # noqa: E402
from dwg_reader import extract_plan                              # noqa: E402
from block_resolver import resolve_blocks, annotate_inserts      # noqa: E402
from legend_extract import find_legend, detect_legend_columns    # noqa: E402
from legend_pdf import read_legend                               # noqa: E402

CONFIG = json.loads((HERE.parent / "plan_takeoff" / "config.json")
                    .read_text(encoding="utf-8"))


def norm(s: str) -> str:
    """Normalise un libelle pour l'appariement PDF <-> DWG : sans accents, sans casse,
    espaces ecrases. Les deux sources tracent le MEME texte, la normalisation ne sert
    qu'a absorber les differences d'encodage et d'espacement."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def dwg_legend_labels(dwg_path: Path) -> set[str]:
    """Les libelles de legende du DWG. Reproduit process_plan (takeoff.py:71-76) sans
    faire le comptage, qui ne nous interesse pas ici."""
    plan = extract_plan(dwg_path, cache_dir=CACHE, refresh=False)
    resolved = resolve_blocks(plan, CONFIG)
    per_insert = annotate_inserts(plan, resolved, CONFIG)
    by_display, _ = find_legend(plan, per_insert, resolved, CONFIG)
    col_labels, _ = detect_legend_columns(plan, per_insert)
    return {norm(v) for v in {**col_labels, **by_display}.values() if norm(v)}


def prf(tp: int, fp: int, fn: int):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main():
    rows = []
    tot_tp = tot_fp = tot_fn = 0
    for dwg, pdf in find_pairs():
        met = detect_metier(dwg)
        try:
            truth = dwg_legend_labels(dwg)
        except Exception as e:
            print(f"[{met}] {pdf.name[:45]:45} ERR DWG {str(e)[:40]}", flush=True)
            continue
        if not truth:
            print(f"[{met}] {pdf.name[:45]:45} (aucune legende DWG -> plan ignore)",
                  flush=True)
            continue
        try:
            res = read_legend(pdf)
        except Exception as e:
            print(f"[{met}] {pdf.name[:45]:45} ERR PDF {str(e)[:40]}", flush=True)
            continue

        found = {norm(e["label"]) for e in res["entries"]}
        tp = len(found & truth)
        fp = len(found - truth)
        fn = len(truth - found)
        tot_tp, tot_fp, tot_fn = tot_tp + tp, tot_fp + fp, tot_fn + fn
        p, r, f = prf(tp, fp, fn)
        print(f"[{met}] {pdf.name[:45]:45} verite={len(truth):>3} trouve={len(found):>3} "
              f"P={p:.2f} R={r:.2f} F1={f:.2f}", flush=True)

        for lab in sorted(found - truth):
            rows.append({"metier": met, "plan": pdf.name, "cas": "FAUX_POSITIF",
                         "libelle": lab})
        for lab in sorted(truth - found):
            rows.append({"metier": met, "plan": pdf.name, "cas": "MANQUE", "libelle": lab})
        for lab in sorted(found & truth):
            rows.append({"metier": met, "plan": pdf.name, "cas": "OK", "libelle": lab})

    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    with open(outdir / "legend_bench.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["metier", "plan", "cas", "libelle"])
        w.writeheader()
        w.writerows(rows)

    p, r, f = prf(tot_tp, tot_fp, tot_fn)
    print("\n===== GLOBAL =====")
    print(f"  vrais positifs {tot_tp}   faux positifs {tot_fp}   manques {tot_fn}")
    print(f"  precision {p:.3f}   rappel {r:.3f}   F1 {f:.3f}")
    print(f"\nDetail : {outdir / 'legend_bench.csv'}")


if __name__ == "__main__":
    main()
```

- [ ] **Étape 2 : lancer le banc et enregistrer la ligne de base**

C'est long (`extract_plan` lit les DWG depuis le cache, `extract_page` est lent) : compter
**10-20 minutes**, lancer en arrière-plan.

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe score_legend.py \
  | tee out/legend_bench.log
```

Attendu : une ligne par paire, puis le bloc `===== GLOBAL =====` avec précision, rappel et F1.

**Il n'y a pas de seuil à atteindre fixé d'avance.** Ce premier passage EST la ligne de base.
Ce qu'on sait déjà : sur le plan BPCE, l'ancien code sortait ~25 vraies entrées sur 130, soit
une précision de ~0,19. Tout ce qui est nettement au-dessus est un progrès ; le chiffre exact
et la répartition faux-positifs / manques dictent la suite (tâche 4).

- [ ] **Étape 3 : commit**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage
git add Test_No3/score_legend.py
git commit -m "feat(legende): banc de scoring contre la legende DWG

Le PDF est trace depuis le DWG : les libelles sont les memes chaines. Le DWG
donne donc precision/rappel gratuitement, sans annotation manuelle."
```

---

## Tâche 4 : régler les constantes et consigner ce qu'on a appris

**Fichiers :**
- Modifier : `Test_No3/legend_pdf.py` (les 5 constantes, lignes ~40-46) — seulement si le banc le demande
- Modifier : `.claude/skills/comptage-plans/SKILL.md` (sections « Pièges vécus » et « État & reste à faire »)
- Modifier : `Test_No3/README.md` (tableau des fichiers)

**Interfaces :** aucune nouvelle. Cette tâche ne crée pas de code, elle règle et documente.

- [ ] **Étape 1 : lire le CSV et classer les erreurs**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe - <<'PY'
import csv
from collections import Counter
c = Counter()
ex = {"FAUX_POSITIF": [], "MANQUE": []}
with open("out/legend_bench.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        c[r["cas"]] += 1
        if r["cas"] in ex and len(ex[r["cas"]]) < 20:
            ex[r["cas"]].append(f'{r["plan"][:30]:30} {r["libelle"][:45]}')
for k, n in c.most_common():
    print(f"{n:>5}  {k}")
for k in ("FAUX_POSITIF", "MANQUE"):
    print(f"\n--- {k} (20 premiers) ---")
    for line in ex[k]:
        print("  ", line)
PY
```

- [ ] **Étape 2 : régler, une constante à la fois**

Diagnostic → levier, dans cet ordre. **Ne changer qu'une constante par passage du banc**, et
relancer le banc entre chaque : c'est la leçon du 2026-07-12, où empiler des changements
théoriques a rendu l'échec du correctif d'ancres inanalysable.

| Ce que dit le CSV | Levier | Sens |
|---|---|---|
| Beaucoup de FAUX_POSITIF, tous d'un même plan | `MIN_ASPECT` 3.0 → 4.0 | une colonne de bruit passe : exiger une bande plus étroite |
| FAUX_POSITIF qui sont des textes sans symbole | `MIN_GLYPH_RATIO` 0.6 → 0.75 | exiger que plus de lignes portent un glyphe |
| Beaucoup de MANQUE, entrées d'une même colonne | `PITCH_HI` 1.6 → 2.2 | la coupe est trop stricte : tolérer un pas plus irrégulier |
| MANQUE sur des légendes courtes (2-3 entrées) | `MIN_ROWS` 4 → 3 | attention : baisse la précision, à vérifier au banc |
| MANQUE dont le libellé est décalé en x | `TOL_X` 1.0 → 1.5 | libellés moins bien alignés que prévu |

Après chaque changement : relancer `score_legend.py`, comparer le F1 global au précédent.
**Garder le changement seulement s'il améliore le F1.** Noter chaque passage (constante,
valeur, F1) — la trace vaut mieux que le souvenir.

- [ ] **Étape 3 : lancer toute la suite de tests**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage/Test_No3
PYTHONIOENCODING=utf-8 ../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/ -v
```

Attendu : **tout passe.** En particulier `test_canon_regression.py` : le réglage des
constantes ne doit rien avoir déplacé du dataset (il n'y touche pas, mais on vérifie).

- [ ] **Étape 4 : consigner dans SKILL.md**

Ajouter à la section « Pièges vécus » de `.claude/skills/comptage-plans/SKILL.md` :

```markdown
- **La légende n'est pas une bande de page, c'est un TABLEAU.** `pdf_takeoff.
  find_legend_templates()` prenait une bande de l'ancre LEGENDE jusqu'aux bords : mesuré
  sur le plan VDI de BPCE, 78 % de la feuille, 130 « entrées » pour ~25 vraies (noms de
  locaux, surfaces, jusqu'au nom de la rue). `Test_No3/legend_pdf.py` cherche la STRUCTURE
  à la place : colonnes de lignes alignées à gauche, à pas vertical régulier, en bande
  verticale. Même critère que `legend_extract.detect_legend_columns()` côté DWG.
- **`canon()` renvoyait `AUTRE_SYMBOLE` pour tout, y compris le bruit** — ce qui rendait
  l'échec invisible (67 % des entrées de légende y tombaient). `canon(label, strict=True)`
  renvoie `None` sur le chemin légende : une entrée non reconnue doit être SIGNALÉE.
  Le mode par défaut reste le fourre-tout, parce que le DATASET a `AUTRE_SYMBOLE` comme
  classe entraînée.
- **`canon()` est appliqué à l'empaquetage** (`prepare_for_colab`) : le corriger peut
  déplacer des classes du dataset et rendre `model_final.pth` + `thresholds.json` caducs.
  `tests/test_canon_regression.py` gèle la carte des 222 noms / 8002 instances et casse si
  une instance bouge. Le lancer avant tout commit touchant `canonical.py`.
- **La QTE imprimée n'est fiable que si elle forme une VRAIE colonne** (alignée, dans
  l'étendue en y de la légende, à droite des libellés). Sans cette garde on ramasse les
  nombres du plan : sur BPCE, les 80/160/353 « quantités » étaient des effectifs et des
  surfaces.
```

Et mettre à jour « État & reste à faire » : le pont légende passe de « à faire » à « lecteur
fait, mesuré au banc à P=… R=… F1=… ; reste la fusion avec les détections ».

- [ ] **Étape 5 : mettre à jour le tableau des fichiers de `Test_No3/README.md`**

Ajouter trois lignes :

```markdown
| `legend_pdf.py` | Lit la LÉGENDE d'un PDF vectoriel par détection de colonnes alignées. `read_legend(pdf)` → entrées {libellé, classe canonique, gabarit, quantité}. Ne dépend de `plan_takeoff` que par `extract_page`. |
| `score_legend.py` | Banc du lecteur de légende : PDF vs légende DWG → précision / rappel / F1. Sort `out/legend_bench.csv`. |
| `tests/` | `test_canon.py` (les 5 bugs), `test_canon_regression.py` (**garde-fou : le dataset ne bouge pas**), `test_legend_pdf.py`. Lancer : `../plan_takeoff/.venv/Scripts/python.exe -m pytest tests/ -v` |
```

- [ ] **Étape 6 : commit**

```bash
cd /c/Users/takot/Documents/projet_AIX/saas_test_comptage
git add Test_No3/legend_pdf.py Test_No3/README.md ../.claude/skills/comptage-plans/SKILL.md
git commit -m "chore(legende): reglage des constantes sur le banc + consignation

Ligne de base du banc et lecons apprises consignees dans SKILL.md."
```

---

## Ce que ce plan ne fait PAS

Volontairement hors périmètre, conformément à la spec :

- l'inférence plan-level (rendu à 1800 px de large — **pas** un DPI fixe —, tuilage 800/600,
  detectron2, seuils par classe, NMS inter-tuiles) ;
- le 2e étage géométrique qui répartit une classe canonique entre plusieurs entrées de
  légende (`LUMINAIRE` couvre 5 libellés distincts sur un même plan) ;
- la fusion détections × légende ;
- les PDF scannés (non vectoriels) ;
- le run 5 d'entraînement.
