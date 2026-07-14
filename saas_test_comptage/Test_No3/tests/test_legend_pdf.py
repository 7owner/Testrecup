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
