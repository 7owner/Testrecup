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
    # Recherche par sous-chaine : le libelle complet porte souvent une description
    # ("Detecteur de presence - 360 / 180 / 90"), et une ligne de continuation fusionnee
    # rallonge encore le libelle parent.
    labels = [e["label"] for e in legende["entries"]]
    for vraie in (
        # entrees qui survivaient deja
        "Caméra surveillance", "Prise RJ45", "Attente HDMI",
        "Flash lumineux d'alarme incendie", "Contacteur intrusion",
        # entrees perdues par le vol de glyphe (mecanisme A) : un cluster fusionne haut
        # (#1336 h=38, #1363 h=52) etait rafle par la 1re ligne, les suivantes sortaient
        # sans candidat et etaient jetees en silence.
        "Détecteur de présence", "Baie de brassage CFa 42U", "Nourrice RJ",
        "Alimentation spécifique", "Nourrice PC", "Déclencheur manuel",
        "Platine vidéoportier", "Arrêt d'urgence",
        "Attente RJ45 pour borne wifi",
        # entrees perdues par la coupure sur libelle multi-lignes (mecanisme B)
        "Bloc d'Eclairage de Sécurité Autonome", "Ecl-type B", "Ecl-type E",
    ):
        assert any(vraie in l for l in labels), f"entree de legende perdue : {vraie!r}"


def test_le_nombre_d_entrees_est_plausible(legende):
    # Chiffre MESURE sur ce plan (dump des lignes de libelle groupees par x0), pas estime :
    # colonne 0 (x0~662) = 21 lignes de legende, colonne 1 (x0~889) = 15 -> 36 lignes.
    # Deux des 21 sont des lignes de continuation d'un libelle trop long ("recuperee et
    # source remplacee : LED + DALI" ; "Suspension acoustique MUUTO - Under the belt") :
    # elles sont fusionnees dans leur libelle parent et ne comptent pas comme entree.
    # 36 - 2 = 34 entrees attendues. La fourchette laisse +/- 4 de marge, pas 40 %.
    n = len(legende["entries"])
    assert 30 <= n <= 38, f"{n} entrees ; ce plan en compte 34 (21+15 lignes, -2 continuations)"


def test_aucune_quantite_inventee(legende):
    # ce plan n'a AUCUNE colonne QTE : les 80/160/353 observes le 2026-07-13 etaient
    # des nombres du plan (effectifs, surfaces) attrapes par un alignement fortuit.
    inventees = [(e["label"], e["qty_declared"])
                 for e in legende["entries"] if e["qty_declared"] is not None]
    assert not inventees, f"quantites inventees : {inventees}"


def test_gabarit_valide_ou_absence_signalee(legende):
    # Nouveau contrat : etre dans une colonne de legende validee PROUVE qu'on est une
    # entree ; le gabarit est un bonus. extract_page fusionne parfois plusieurs symboles
    # verticalement voisins en un seul cluster : la ligne qui n'obtient pas de glyphe
    # propre sort quand meme, avec glyph_bbox=None -- mais elle doit alors etre NOMMEE
    # dans un warning. Sans gabarit et sans warning = disparition silencieuse = echec.
    blabla = " ".join(legende["warnings"])
    for e in legende["entries"]:
        if e["glyph_bbox"] is None:
            assert e["label"] in blabla, (
                f"entree sans gabarit et sans warning qui la nomme : {e['label']!r}")
        else:
            x0, y0, x1, y1 = e["glyph_bbox"]
            assert x1 > x0 and y1 > y0, f"gabarit degenere pour {e['label']!r}"


def test_les_entrees_sont_mappees_ou_signalees(legende):
    # canon(strict=True) : soit une classe du detecteur, soit None (= "je ne sais pas
    # compter ca"). Jamais AUTRE_SYMBOLE, qui masquerait le probleme.
    for e in legende["entries"]:
        assert e["canon"] != "AUTRE_SYMBOLE"


# --- Legende COURTE sous ANCRE. Mesure du 2026-07-15 : les legendes ROI RENE ne font que
# 2 a 6 entrees ("LEGENDE VIDEOSURVEILLANCE" + 3 cameras avec colonne QTE). Sans support
# d'ancre, les seuils structurels (MIN_ROWS=4, bande verticale) les rejetaient en bloc et
# 6 plans sur 12 rendaient ZERO entree au banc. Ce test verrouille ce chemin.
_ANCRE_GLOB = "*CFA-100-Plan videosurveillance rdc hotel roi rene.pdf"


@pytest.fixture(scope="module")
def legende_ancre():
    hits = list((HERE.parents[1] / "PLANS_COMPLETS_NEW").rglob(_ANCRE_GLOB))
    if not hits:
        pytest.skip(f"PDF de test absent : {_ANCRE_GLOB}")
    return read_legend(hits[0])


def test_legende_courte_sous_ancre_est_detectee(legende_ancre):
    # 3 cameras sous "LEGENDE VIDEOSURVEILLANCE" ; sans ancre, une colonne de 3 lignes plus
    # large que haute serait rejetee.
    labels = [e["label"] for e in legende_ancre["entries"]]
    cams = [l for l in labels if "amera" in l.lower() or "améra" in l.lower()]
    assert len(cams) >= 3, f"cameras sous ancre non detectees : {labels}"


def test_colonne_qte_courte_est_lue(legende_ancre):
    # Cette legende a une vraie colonne QTE alignee (contrairement a BPCE). Au moins une
    # camera doit porter sa quantite -- la garde _qty_column ne doit pas l'ecarter au motif
    # qu'il y a moins de MIN_ROWS lignes (le seuil suit le mode ancre).
    cams = [e for e in legende_ancre["entries"]
            if "amera" in e["label"].lower() or "améra" in e["label"].lower()]
    assert any(e["qty_declared"] is not None for e in cams), \
        f"aucune quantite lue sous ancre : {[(e['label'], e['qty_declared']) for e in cams]}"
