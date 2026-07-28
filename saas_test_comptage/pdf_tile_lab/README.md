# PDF Tile Lab

Page de validation pour tester la methode finale visee :

1. importer un PDF,
2. choisir une page,
3. decouper la page en matrice,
4. rendre chaque cellule en haute definition,
5. comparer une amelioration locale avant de brancher un modele de detection.

Ce labo ne remplace pas l'entrainement. Il sert a valider visuellement si le
decoupage + zoom haute qualite donne des cellules exploitables pour reconnaitre
les symboles.

## Lancement

Depuis `saas_test_comptage` :

```powershell
python pdf_tile_lab\server.py
```

Puis ouvrir :

```text
http://127.0.0.1:8891
```

