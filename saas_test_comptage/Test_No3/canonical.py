"""Dictionnaire de classes CANONIQUES : ramene les ~222 noms de blocs bruts
(fragmentes / synonymes entre affaires) a ~36 classes fonctionnelles.

canon(nom) -> label canonique, ou None si a EXCLURE (mobilier, en-tete de legende,
bloc anonyme, etiquette). Regles ORDONNEES : la premiere qui matche gagne, donc
les regles specifiques sont avant les generiques. Le '.' matche une lettre
accentuee quelle que soit son encodage (e/é/mojibake).
"""
from __future__ import annotations

import re

_EXCLUDE = re.compile(
    r"^A\$C|FAU_Type|idloc|^h:\d|under the bell|susp lily|Krusning|^A.{1,2}ria$|"
    r"Groupe-\d|^DAIKIN$|^code alarme$|REPROGRAPHIE|^R-\d|PHOTOCOPIEUR|"
    r"Ecran TV|Ecran de supervision|^Courant faible$|"
    r"^S.curit. incendie$|^Eclairage$|RESERVATION|RACCOREDEMENT|^SR$|^BP$|"
    r"Ecran de sup",
    re.IGNORECASE)

# (motif, label canonique) — ORDRE IMPORTANT (specifique -> generique)
_RULES = [
    # ---- SSI (securite incendie) ----
    (r"d.clencheur|declencheur|\bBGV\b|\bBMAL\b|d.clancheur", "SSI_DECLENCHEUR"),
    (r"volet.*desenfum|desenfum|\bVDF\b", "SSI_VOLET_DESENFUMAGE"),
    (r"flash.*alarme|diffuseur lumineux|\bDL\b$", "SSI_FLASH"),
    (r"diffuseur sonore|non autonome", "SSI_DIFFUSEUR_SONORE"),
    (r"sir.ne", "SIRENE"),
    (r"tecteur.*incendie|optique adressable|fond de pene|tecteur automatique|"
     r"^d.tecteur$|^detecteur$|d.tecteur incendie", "DETECTEUR_INCENDIE"),
    (r"indicateur d.action|\bIA\b|\bNSA\b|\bAIT\b", "SSI_TABLEAU"),
    (r"tableau.*(alarme|repetiteur|incendie)", "SSI_TABLEAU"),
    (r"ventouse", "VENTOUSE"),
    (r"feuillure|fond de pene|g.che", "GACHE_CONTACT"),
    # ---- Detection presence (commande eclairage) ----
    (r"mouvement|d.tecteur de (pr.sence|absence)|d.absence|\bmvt\b|"
     r"detecteur de mvt|pr.sence", "DETECTEUR_PRESENCE"),
    # ---- Intrusion ----
    (r"intrusion|anti.?intrus|centrale anti|clavier.*(alarme|service)|"
     r"contacteur intrusion|controle intrusion", "INTRUSION"),
    # ---- Videosurveillance / interphonie / AV ----
    (r"cam.ra|camera", "CAMERA"),
    (r"interphon|combine interieur|appel eas|platine de rue|poste viso|videophone", "INTERPHONE"),
    (r"lecteur de b|bouton poussoir|deverrouillage|clavier", "CONTROLE_ACCES"),
    # NB : PAS "baie sono" ici -- une baie est un rack, pas un haut-parleur.
    # Elle est reclamee plus bas par BAIE_VDI (qui ne la voyait jamais : shadowing).
    (r"haut.?parleur|caisson de grave|attente sonoris", "HAUT_PARLEUR"),
    (r"video projecteur|point de raccordement|audiovisuel|moniteur video", "VIDEO_PROJ"),
    (r"horloge", "HORLOGE"),
    # ---- VDI / reseau ----
    # avant les regles generiques : "poste de travail" ne doit pas tomber dans
    # "poste viso" (INTERPHONE). C'est un point de raccordement a chiffrer, pas du
    # mobilier -- l'ancien modele l'apprenait a AP 75 sur 166 instances.
    (r"poste de travail", "POSTE_TRAVAIL"),
    (r"nourrice", "NOURRICE"),
    (r"baie (vdi|sono)|vdi ?- ?baie|^baie", "BAIE_VDI"),   # capte aussi "Baie 42U"
    (r"rj45|prise standard rj", "PRISE_RJ45"),
    (r"hdmi", "PRISE_HDMI"),
    (r"coaxial|coax", "PRISE_COAX"),
    (r"\bwifi\b", "BORNE_WIFI"),
    # ---- Eclairage ----
    (r"baes|bloc autonome.*eclairage|bloc d.eclairage securite|bapi", "BAES"),
    (r"hublot", "HUBLOT"),
    (r"applique", "APPLIQUE"),
    (r"r.glette|reglette|tube ?led|ruban led|bandeau", "REGLETTE"),
    (r"lampe a poser|lampe de table|baladeuse|lampe fixe", "LAMPE_POSER"),
    (r"suspension|^susp ", "SUSPENSION"),
    (r"spot|downlight", "SPOT"),
    (r"plafonnier|dalle led|pav. led|luminaire|projecteur|ciel bleu|"
     r"brasseur|park etanche|variateur|int.*gradation|interrupteur|"
     r"simple allumage|va.et.vient", "LUMINAIRE"),
    # ---- CFO puissance ----
    (r"tableau divisionnaire|tgbt|coffret", "TABLEAU_ELEC"),
    (r"coupure d.urgence|arr.t d.urgence|arret d urgence", "COUPURE_URGENCE"),
    (r"alim|autotransfo|24v", "ALIMENTATION"),
    (r"prise de courant|^pc[\s\d]|standard 16a|p\+n\+t|prise standard|"
     r"\b16a\b|\b20a\b|usb", "PRISE_COURANT"),
    # ---- CVC ----
    (r"cvc|gainable|soufflage|reprise|vmc|apport air|renouv air|a.rauli|"
     r"clim|regulation|\bTH\b", "CVC"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), lbl) for p, lbl in _RULES]


def canon(name: str):
    """Nom brut -> label canonique, ou None si a exclure."""
    s = (name or "").strip()
    if not s or _EXCLUDE.search(s):
        return None
    for rx, lbl in _COMPILED:
        if rx.search(s):
            return lbl
    return "AUTRE_SYMBOLE"   # non classe (rare) : regroupe, pas perdu


if __name__ == "__main__":
    import json, glob
    from collections import Counter
    c = Counter()
    raw = Counter()
    for f in glob.glob("4e_dataset/*/annotations.json"):
        d = json.load(open(f, encoding="utf-8"))
        cats = {x["id"]: x["name"] for x in d["categories"]}
        for a in d["annotations"]:
            nm = cats[a["category_id"]]
            raw[nm] += 1
            k = canon(nm)
            c[k if k else "(EXCLU)"] += 1
    print(f"{len(raw)} classes brutes -> {len([k for k in c if k not in ('(EXCLU)',)])} canoniques\n")
    for k, n in c.most_common():
        print(f"{n:>5}  {k}")
