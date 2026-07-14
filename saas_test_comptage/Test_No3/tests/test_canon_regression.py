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
#
# ATTENTION : les 31 instances listees ci-dessous CHANGENT de classe. Le modele du run 4
# (model_final.pth) les a apprises comme CAMERA. Les accepter impose donc de reempaqueter
# le dataset (colab/prepare_for_colab.py), de relancer un entrainement (run 5), puis de
# recalibrer thresholds.json. Decision utilisateur du 2026-07-13.
EXCEPTIONS: dict[str, tuple[str, str, str]] = {
    "PRISE RJ45 CAMERA DE SURVEILLANCE": (
        "CAMERA", "PRISE_RJ45",
        "Correction d'etiquetage, pas regression : le symbole est le carre de prise RJ45 "
        "(7,8 x 7,7 px, elongation 1,02), identique aux autres prises RJ45 et distinct du "
        "symbole de camera (12,9 x 10,1 px, elongation 1,28) -- le dataset apprenait a tort "
        "qu'un carre de prise est une camera."),
    "PRISE RJ45 POUR CAMERA 360° AVEC RENVOIE VERS REGIE": (
        "CAMERA", "PRISE_RJ45",
        "Correction d'etiquetage, pas regression : meme carre de prise RJ45 que ci-dessus "
        "(elongation ~1,0, taille des prises), et non le symbole de camera (elongation 1,28) "
        "-- 'POUR CAMERA' decrit l'usage de la prise, pas la nature du symbole."),
}


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
