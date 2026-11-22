# Feuille de route de Bird Models (objectifs annoncés par l'équipe)

Ce sont des objectifs, pas des engagements datés vérifiés. Les présenter comme tels.

## Aujourd'hui (état vérifié)

- Bird S 4B est servi par un Inference Endpoint Hugging Face sur AWS, région us-east-1 (États-Unis), sur 1 GPU NVIDIA L4, mis en veille quand il ne sert pas.
- L'énergie de chaque réponse est affichée comme une estimation haute (puissance de la carte × durée de travail). L'électricité de cette région n'est pas décarbonée en totalité.

## Objectif à moyen terme : des centres de données décarbonés

- Faire tourner Bird dans des centres de données alimentés par une électricité bas carbone (par exemple une région dont le réseau est majoritairement nucléaire, hydraulique ou renouvelable).
- Mesurer et publier l'intensité carbone réelle de cette électricité (gCO₂e/kWh) et l'afficher sous chaque réponse (variable `BIRD_GRID_INTENSITY`).

## Objectif 2030 : 100 % renouvelable, sur nos propres systèmes

- Faire tourner Bird sur une infrastructure propre à Bird Models, alimentée par des énergies renouvelables.
- Condition pour l'annoncer comme atteint : une mesure publiée (consommation, origine de l'électricité, méthode).

## Autres prochaines étapes (déjà listées)

- Un palier encore plus petit pour les tâches simples.
- Une version quantifiée qui tourne en local.
- Davantage de données métier en français.
- Une meilleure recherche web avec citations.
