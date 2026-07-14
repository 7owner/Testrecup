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
