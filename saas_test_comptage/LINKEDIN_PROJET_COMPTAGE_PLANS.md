# Version LinkedIn - Projet Comptage de Symboles sur Plans PDF

## 1. Version courte - Post LinkedIn

Je travaille actuellement sur un projet de **vision par ordinateur appliquée aux plans techniques PDF**.

Objectif : **extraire automatiquement les symboles d'une légende, les retrouver dans le plan, puis produire un comptage exploitable**.

Le projet a d'abord démarré avec une approche de :

- rendu PDF -> image
- extraction de la légende
- matching de formes et de signatures
- regroupement exploratoire par **KMeans strict** autour des symboles de légende
- interface locale de contrôle visuel

Puis le sujet a évolué vers une base plus robuste : **la segmentation d'instances**.

J'ai donc préparé un nouveau pipeline avec :

- génération de tuiles depuis les PDF
- structuration du dataset au format **COCO**
- définition des catégories métier
- base d'entraînement **Mask R-CNN**
- interface locale pour tester le workflow **plan -> légende -> recherche**
- page d'annotation pour créer les futurs masques d'instances

Le vrai enjeu n'est pas seulement de détecter des objets, mais de construire un outil capable d'aider un chargé d'affaires à **fiabiliser le repérage et le comptage sur des plans réels**.

Technos : **Python, PyTorch, Torchvision, OpenCV, PyMuPDF, COCO, Mask R-CNN**

Méthodes testées : **matching heuristique, clustering KMeans, segmentation d'instances**

#ComputerVision #DeepLearning #PyTorch #OpenCV #Segmentation #PDF #Automation #Engineering #AI

---

## 2. Version detaillee - Post LinkedIn

Je développe actuellement un prototype de **reconnaissance et de comptage de symboles sur plans techniques PDF**.

### Problème traité

Dans les plans CFO/CFA, une grande partie du travail consiste à :

- identifier les symboles présents dans la légende
- retrouver ces mêmes symboles dans le plan
- estimer ou vérifier les quantités

Ce type de tâche paraît simple sur le papier, mais devient vite difficile en pratique à cause :

- du bruit graphique
- des différences d'échelle
- des annotations textuelles
- des traits parasites
- de la variété des symboles

### Première approche

Le projet a commencé avec une chaîne classique de vision :

- conversion PDF -> image
- extraction automatique de la zone légende
- découpe des symboles
- recherche dans le plan par comparaison binaire, couleur, forme et signature

J’ai aussi testé une approche de **clustering KMeans** pour regrouper les composants extraits du plan autour d’un symbole de légende donné, avec une logique de centre fixé sur l’objet recherché.

Cette approche permet déjà de tester rapidement le problème, de visualiser les correspondances et de construire une première base d'évaluation.

### Limite rencontrée

Le matching heuristique reste utile pour prototyper, mais il montre vite ses limites dès qu'on cherche :

- plus de robustesse
- moins de faux positifs
- une meilleure généralisation
- un moteur exploitable sur des plans variés

Le test par **KMeans** a été intéressant comme étape intermédiaire :

- il permettait de structurer les candidats extraits du plan
- il donnait une logique de regroupement autour de l’objet de légende
- mais il restait sensible au bruit, aux variations locales et aux composants parasites

Il a donc servi de **méthode exploratoire**, mais pas de solution finale suffisante.

### Evolution du projet

J'ai donc préparé une nouvelle base orientée **segmentation d'instances** :

- création d'un pipeline dédié, séparé du vieux classifieur de crops
- génération de tuiles depuis les plans PDF
- structuration d'un dataset **COCO instance segmentation**
- définition d'un jeu initial de catégories métier
- mise en place d'un socle **Mask R-CNN**
- création d'une interface locale pour :
  - tester le workflow métier
  - annoter les futurs masques d'instances

### Ce que je cherche à construire

Un outil capable de passer de :

**plan PDF -> légende -> objets retrouvés -> comptage exploitable**

avec un niveau de fiabilité suffisant pour devenir un vrai support opérationnel.

### Stack utilisée

- Python
- PyTorch
- Torchvision
- OpenCV
- PyMuPDF
- format COCO
- Mask R-CNN

Ce projet est intéressant parce qu'il se situe entre :

- vision par ordinateur
- structuration de données métier
- interfaces locales d'annotation et de validation
- automatisation de tâches techniques à forte valeur terrain

Si le sujet vous intéresse, je peux partager plus en détail l'architecture choisie, les difficultés rencontrées et les arbitrages entre matching heuristique et segmentation d'instances.

#ComputerVision #AI #DeepLearning #PyTorch #InstanceSegmentation #OpenCV #PDFProcessing #Automation #Tech #Engineering

---

## 3. Version Projet - Section "Projets" du profil LinkedIn

### Titre

Comptage automatique de symboles sur plans PDF par vision par ordinateur

### Description

Développement d'un prototype de vision par ordinateur pour **extraire les symboles d'une légende de plan technique PDF, les retrouver dans le plan et produire un comptage exploitable**.

Le projet a d'abord été structuré autour d'un pipeline de :

- rendu PDF -> image
- extraction de légende
- découpe des symboles
- matching par forme, couleur et signatures visuelles
- expérimentation d’un **clustering KMeans** pour regrouper les composants du plan autour des objets de légende

Puis il a évolué vers une architecture plus robuste orientée **segmentation d'instances** avec :

- génération de tuiles de plans
- structuration du dataset au format COCO
- définition de catégories métier
- mise en place d'un socle d'entraînement **Mask R-CNN**
- développement d'interfaces locales pour test, visualisation et annotation

### Compétences

- Computer Vision
- Deep Learning
- PyTorch
- OpenCV
- Traitement PDF
- Annotation de données
- Segmentation d'instances
- Prototypage d'outils IA

---

## 4. Version ultra concise - Accroche

Prototype de vision par ordinateur pour **extraire automatiquement la légende d'un plan PDF, retrouver les symboles dans le plan et préparer un moteur de comptage basé sur la segmentation d'instances**.

---

## 5. Points a mettre en avant oralement ou en commentaire

- Le sujet est concret et métier, pas seulement académique.
- Le projet traite un vrai problème de repérage sur plans techniques.
- Il y a eu une transition raisonnée entre heuristiques de matching, expérimentation par KMeans et segmentation d'instances.
- Le pipeline ne se limite pas au modèle : il inclut la donnée, l'annotation, la visualisation et l'évaluation.
- L'objectif final est un outil exploitable, pas juste une démonstration.
