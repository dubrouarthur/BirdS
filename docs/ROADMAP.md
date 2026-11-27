# Feuille de route

Priorités fixées par le propriétaire du produit, dans l'ordre : harnais agentique, contenu enrichi, édition de documents.
Objectif : le niveau d'OpenAI dans les usages de bureau, porté par un petit modèle et beaucoup de modules soignés.

## Vague 1 (en cours)

- Canevas : documents, diapos, code et mini-tableur construits en direct dans un design préconçu, modifiés par patchs ciblés.
- Fiabilité du harnais entre les actions : plan de la demande suivi étape par étape, vérification avant réponse, réparation des arguments.
- Recherche approfondie et graphe relationnel, petits modules (matrice de comparaison, avantages / inconvénients, frise,
  chiffres clés, liste de tâches, calculatrice, cartes de sources, glossaire), suggestions de suite, transformations en un clic.

## Vague 2 (dès la vague 1 fusionnée)

1. Mode Agent : plan affiché et modifiable avant lancement, « Ajouter une consigne » en cours de route,
   carte « Vérifications faites », agents qui agissent sur le Canevas, tâches longues en arrière-plan.
2. Recherche approfondie, affichage dynamique et complet :
   - tableau de bord en direct (sous-questions ouvertes / résolues, requêtes, sources lues qui arrivent au fil de l'eau,
     affirmations recoupées, contradictions) ;
   - graphe relationnel qui grandit pendant la recherche ;
   - rapport final plein écran : sommaire, citations [n] avec bulle, panneau de sources (citées / consultées),
     frise, matrice de comparaison, chiffres clés, niveau de confiance par affirmation, export Word / PDF / diapos.
3. Sources et citations façon ChatGPT / Perplexity : [n] cliquables, bulle, « N sources », panneau latéral.
4. Modules du catalogue (`docs/research/rich-catalogue-2026-11.json`), 3 lots : structure de réponse, données, documents métier.
5. Canevas avancé : retouche d'une sélection avec variantes, versions et restauration, ✦ par diapositive, thèmes,
   mises en page suggérées par le contenu, panneau « Livrables », « Transformer en… », tableau interactif sur CSV/XLSX.

## Plus tard

- Ultra recherche (bêta, comptes autorisés) : des centaines d'itérations par tranches reprises, journal forensique,
  garde-fous RGPD (pas de profilage de personnes privées).
- Connecteurs (`docs/research/connectors-design-2026-11.md`) : correctifs de sécurité d'abord, puis Microsoft 365 en lecture.

Références : `docs/research/competitors-2026-11.md`.
