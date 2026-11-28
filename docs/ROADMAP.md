# Feuille de route

Priorités fixées par le propriétaire du produit, dans l'ordre : harnais agentique, contenu enrichi, édition de documents.
Objectif : le niveau d'OpenAI dans les usages de bureau, porté par un petit modèle et beaucoup de modules soignés.

## Vague 1 (en cours)

- Canevas : documents, diapos, code et mini-tableur construits en direct dans un design préconçu, modifiés par patchs ciblés.
- Fiabilité du harnais entre les actions : plan de la demande suivi étape par étape, vérification avant réponse, réparation des arguments.
- Recherche approfondie et graphe relationnel, petits modules (matrice de comparaison, avantages / inconvénients, frise,
  chiffres clés, liste de tâches, calculatrice, cartes de sources, glossaire), suggestions de suite, transformations en un clic.
  **Fusionné dans le déploiement le 28/11/2026** (`w1-modules`, docs/HARNESS.md, section 14) : petits modules = module
  `card` du catalogue, choisi par le routeur ; reste : évaluation routeur en réel de la famille `cards` (endpoint en pause).

## Vague 2 (dès la vague 1 fusionnée)

1. Mode Agent : plan affiché et modifiable avant lancement, « Ajouter une consigne » en cours de route,
   carte « Vérifications faites », agents qui agissent sur le Canevas, tâches longues en arrière-plan.
   Fait sur la branche `agents-w2` (docs/HARNESS.md, section 11 bis) ; reste : brancher l'adaptateur Canevas une fois
   `w1-canvas` fusionnée, mesurer sur plusieurs passages.
1 bis. Mode Réflexion : réflexion adaptative (le modèle décide s'il réfléchit et combien, budget selon la tâche),
   résumé lisible de la réflexion, auto-vérification avant réponse (chiffres, demandes couvertes), reprise propre
   quand la réflexion tourne en rond ; mesuré avant / après sur un jeu fixe.
   **Fusionné le 28/11/2026** (`reflexion`, docs/HARNESS.md, section 16) ; reste : relancer `reflexion_eval` en réel
   (pourcentages, demandes à plusieurs questions) quand l'endpoint reprend.
   Niveaux de réflexion illustrés par des oiseaux (icônes SVG maison, petite animation de vol, clair/sombre) :
   - **Colibri** · Instantané : pas de réflexion, réponse immédiate (questions simples, reformulations) ;
   - **Hirondelle** · Rapide : réflexion courte (mails, résumés, la plupart des tâches) ;
   - **Faucon** · Précis : réflexion standard avec vérification (calculs, comparaisons, code) ;
   - **Chouette** · Approfondi : longue réflexion, auto-vérification et relecture (analyses, problèmes difficiles) ;
   - **Albatros** · Endurance : tâches longues en Mode Agent et recherche approfondie (vole des heures sans se poser).
   « Auto » laisse Bird choisir l'oiseau selon la demande ; le choix s'affiche dans la réponse (« Bird a pris son vol en
   Faucon »).
1 ter. Harnais : décisions par le modèle (routeur à sortie structurée, puis fine-tuning des outils), plan et
   vérification d'achèvement, mémoire des résultats, réparation des appels.
2. Recherche approfondie, affichage dynamique et complet :
   - tableau de bord en direct (sous-questions ouvertes / résolues, requêtes, sources lues qui arrivent au fil de l'eau,
     affirmations recoupées, contradictions) ;
   - graphe relationnel qui grandit pendant la recherche ;
   - rapport final plein écran : sommaire, citations [n] avec bulle, panneau de sources (citées / consultées),
     frise, matrice de comparaison, chiffres clés, niveau de confiance par affirmation, export Word / PDF / diapos.
   Fusionné le 28/11/2026 (`w1-modules`, docs/HARNESS.md, section 14) ; reste : une course complète en réel (recherche web
   indisponible le jour de la mesure).
3. Sources et citations façon ChatGPT / Perplexity : [n] cliquables, bulle, « N sources », panneau latéral.
4. Modules du catalogue (`docs/research/rich-catalogue-2026-11.json`), 3 lots : structure de réponse, données, documents métier.
   Données ouvertes : **fusionné le 28/11/2026** (`open-apis`, `docs/OPENDATA.md`, 12 sources sans clé, 6 fiches
   choisies par le routeur ; catalogue du routeur 985 jetons) ; reste : mesure du routeur en réel ; prochain lot : Hub'Eau, qualité de l'air, catalogue data.gouv.fr.
5. Canevas avancé, objectif « exceptionnel » (dès la vérification du Canevas terminée) :
   - diapos : ~20 mises en page (couverture plein cadre, chiffre clé géant, comparaison, frise, grille d'images, citation,
     graphique + message clé, clôture), thèmes marqués, mise en page choisie d'après le contenu ; images Openverse +
     Wikimedia (licences vérifiées, crédits), « Remplacer » / « Sans image » par diapositive ;
   - documents type Word au même niveau : page de garde, sommaire, styles de titres, encadrés, tableaux, figures légendées,
     images, notes, sources ; édition en place, sections déplaçables, export .docx fidèle à l'aperçu ;
   - code avec Web preview façon ChatGPT : aperçu HTML/CSS/JS en direct (iframe isolée), plusieurs fichiers, console,
     responsive (mobile / tablette / bureau), « Corriger avec Bird », itérations versionnées, export / copie ;
   - ✦ par bloc, retouche d'une sélection avec variantes, versions + restauration, le document modifié fait foi ;
   - contrôle : directeur artistique en taille réelle, aperçu = fichier exporté, mesure live.
   Détails initiaux : retouche d'une sélection avec variantes, versions et restauration, ✦ par diapositive, thèmes,
   mises en page suggérées par le contenu, panneau « Livrables », « Transformer en… », tableau interactif sur CSV/XLSX.
   Analyse de données (fiche du fichier, tableau interactif, analyse choisie par le modèle et calculée par le moteur,
   graphiques versionnés avec suites) : **fusionné le 28/11/2026** (`data-analysis`, docs/HARNESS.md, section 15) ;
   reste : grain du trimestre et « par produit » d'une comparaison au prochain affinage.

6. Marque dans le modèle : réécrire les fiches d'identité d'entraînement pour que Bird se présente par la légèreté,
   la liberté d'installer nos modèles où l'on veut (sources d'énergie variées) et « conçu en France », sans
   auto-dénigrement ni modèle de base ; l'invite seule ne suffit pas (mesure : `docs/measures/brand-2026-11-28.md`,
   banc `scripts/brand_eval.py`).
   Site corporate et accueil du chat au message de marque : **fusionné le 28/11/2026** (`brand-site`, `site/COPY.md`) ;
   reste : la phrase finale d'Entraîner (« Parlez-nous de vos tâches ») tant que l'adresse de contact n'est pas
   décidée, et la réponse par défaut de la démo qui cite un nombre de paramètres.

## Plus tard

- Ultra recherche (bêta, comptes autorisés) : des centaines d'itérations par tranches reprises, journal forensique,
  garde-fous RGPD (pas de profilage de personnes privées).
- Connecteurs (`docs/research/connectors-design-2026-11.md`) : correctifs de sécurité d'abord, puis Microsoft 365 en lecture.

Références : `docs/research/competitors-2026-11.md`.
