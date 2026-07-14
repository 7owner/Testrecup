# Legend Zero

Sous-projet reconstruit proprement pour repartir de zéro.

Objectif de l'étape 1 :
- ouvrir un PDF,
- détecter la page de légende,
- extraire les objets de légende,
- afficher les crops,
- exporter le résultat en JSON.

## Structure

- `legend_zero/pdf_utils.py` : scan des PDF, rendu et utilitaires PDF.
- `legend_zero/legend_detector.py` : logique d'extraction des objets de légende.
- `legend_zero/pipeline.py` : orchestration simple PDF -> objets de légende.
- `legend_zero/server.py` : petite API HTTP locale.
- `legend_zero/web/` : interface minimaliste dédiée.
- `legend_zero/runs/` : sorties générées.

## Lancement

Depuis la racine du dépôt :

```powershell
python legend_zero\run_server.py
```

Puis ouvrir :

`http://127.0.0.1:8870`

## Sortie

Chaque PDF produit un dossier unique dans `legend_zero/runs/<slug>/` contenant :

- `result.json`
- `pages/`
- `objects/`

L'étape suivante du projet pourra partir de ces objets de légende pour retrouver leurs occurrences dans le plan.

