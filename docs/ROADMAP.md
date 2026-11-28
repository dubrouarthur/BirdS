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
   Marchés (`finance-api`, `docs/FINANCE.md`) : fiche de cours et historique (cryptoactifs CoinGecko, devises BCE
   sans clé ; actions et indices via Twelve Data dès que `BIRD_TWELVEDATA_API_KEY` d'une offre avec droit d'affichage
   est fournie) ; reste : la clé, et revérifier en réel « dois-je acheter … ».
5. Canevas avancé, objectif « exceptionnel » (dès la vérification du Canevas terminée) :
   - diapos : ~20 mises en page (couverture plein cadre, chiffre clé géant, comparaison, frise, grille d'images, citation,
     graphique + message clé, clôture), thèmes marqués, mise en page choisie d'après le contenu ; images Openverse +
     Wikimedia (licences vérifiées, crédits), « Remplacer » / « Sans image » par diapositive ;
     Fait sur la branche `canvas-decks` (docs/CANVAS.md § 9) : 21 mises en page + couverture, 4 thèmes avec masques
     .pptx, aperçu = fichier (règle commune testée), Openverse + Commons, menu « Mise en page », glisser-déposer,
     restauration de version, carte avec couverture et suites ; mesure live 3,5 → 6,2 mises en page par deck, 2 → 5
     decks sur 6 au canevas ; reste : images en production (limites de débit des API), ouverture dans PowerPoint ;
   - documents type Word au même niveau : page de garde, sommaire, styles de titres, encadrés, tableaux, figures légendées,
     images, notes, sources ; édition en place, sections déplaçables, export .docx fidèle à l'aperçu ;
     **Fait sur la branche `canvas-docs`** (docs/CANVAS.md, section 9 : six modèles choisis par le modèle, pages A4,
     ✦ à deux variantes, historique avec restauration, une seule carte, .docx vérifié contre l'aperçu) ; reste : la
     mesure en réel « après » sur les 6 demandes fixes (l'avant est noté).
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

## Outils à développer (audit du 28/11)

Classés par valeur et faisabilité ; chaque outil suit la règle « gold » (entrée de catalogue `birds/harness/catalog.py`,
exemples `scripts/build_tools_mix.py`, cas `scripts/router_data.py`, fiche soignée, tests, captures, egress côté serveur).
Format : nom — pourquoi — source — effort.

1. **(en cours)** `route_travel` : itinéraire, durée et distance (voiture, piéton, vélo) tracés sur la carte — `find_places` ne donne que des liens OSM, sans temps de trajet (« Paris-Lyon en voiture ») — Itinéraire IGN Géoplateforme `data.geopf.fr/navigation/itineraire` (bdtopo-osrm, sans clé, Licence Ouverte, 200 vérifié ; démo OSRM écartée, usage interdit en service) — S.
2. **(en cours)** Vacances scolaires (zones A, B, C, Corse, DOM) dans `work_calendar` — très demandé (« vacances de février zone B ») — data.education.gouv.fr, `fr-en-calendrier-scolaire` (Opendatasoft, sans clé, Licence Ouverte 2.0, réponse gzip) — S.
3. **(en cours)** `check_identifier` : IBAN, SIREN/SIRET, TVA intracommunautaire avec contrôle VIES — calcul exact que le modèle seul ne fait pas fiablement — calcul local (mod 97, Luhn, clé TVA FR) + API REST VIES de la Commission (sans clé ; si indisponible, « validité de format seule ») — S.
4. **(en cours)** Bac à sable Python dans le navigateur (Pyodide auto-hébergé) — tous les concurrents l'offrent, débloque `data_analysis` et le Canevas code — Pyodide (MPL-2.0) servi par Bird, CSP `'wasm-unsafe-eval'`, résultat rendu au harnais comme résultat d'outil — M.
5. Simulateur salaire brut/net, coût employeur, impôt sur le revenu — question RH fréquente où le modèle se trompe — OpenFisca France (API sans clé, moteur AGPL-3.0 à auto-héberger ; avertissement « simulation ») — M.
6. Annonces BODACC dans `find_company` — savoir si un fournisseur est en redressement — bodacc-datadila.opendatasoft.com, `annonces-commerciales` (DILA, Licence Ouverte 2.0 ; RGPD : personnes morales) — S.
7. Agenda .ics : lire un fichier joint, plusieurs événements, créneaux libres — la fiche event ne fait qu'écrire — calcul local RFC 5545 (icalendar BSD, dateutil.rrule) — S.
8. Prix des carburants autour d'un lieu — question française courante — data.economie.gouv.fr, `prix-des-carburants-en-france-flux-instantane-v2` (Licence Ouverte) — S.
9. Traduction de documents avec mise en page conservée (.docx, .pptx, .xlsx, PDF texte) — DeepL, Copilot, Le Chat le font — calcul local (python-docx, python-pptx, openpyxl) + modèle Bird par segment, banc de qualité fixe — M.
10. Vigilance et alertes météo dans `get_weather` — attente de sécurité pour les déplacements — MeteoAlarm Atom CAP France (sans clé, conditions à valider ; Météo-France demande une clé) — S.
11. `diagram` : module Mermaid (organigramme, séquence, Gantt, carte mentale) — rendu en ligne chez les concurrents — mermaid (MIT) déjà servi par Bird, code validé par le harnais comme résultat d'outil, SVG + PNG — S.
12. Extraction de tableaux PDF et OCR des scans — point faible pour factures et relevés — pdfplumber (MIT), pypdfium2, tesseract fra (Apache-2.0) sur l'hôte du modèle, sortie vers `analyze_table` — M.
13. Annuaire de l'administration (mairies, préfectures, CAF) — « horaires de la mairie de Cergy » — api-lannuaire.service-public.fr (DILA, Licence Ouverte, cache et réessai) — S.
14. Trains SNCF : horaires, départs, retards — besoin quotidien des déplacements — transport.data.gouv.fr GTFS + GTFS-RT (ODbL), gares data.sncf.com ; index local à construire — L.
15. Textes juridiques : codes, lois, JORF, droit de l'UE — demande quotidienne des juristes et RH — Légifrance API PISTE (clé gratuite) ou dumps DILA LEGI ; Cellar SPARQL et EUR-Lex pour l'UE — L.
16. Risques d'une commune (Géorisques) — immobilier, implantation — georisques.gouv.fr/api/v1/gaspar/risques (sans clé, Licence Ouverte) — S.
17. Convertisseur d'inflation — calcul exact et sourcé — Insee IPC via Melodi ou HICP BCE (Licence Ouverte, mention BCE) — S.
18. Génération de QR code (URL, vCard, Wi-Fi, IBAN EPC) — petit outil de bureau local — segno (BSD), SVG ou PNG — S.
19. Calculs de dates (écart, âge, semaine ISO, date + N mois) — à confirmer dans `calc.py`, ajouter si absent — dateutil — S.
20. Actualité : dépêches récentes avec sources — vue « actualités » chez Perplexity, Copilot, Gemini — catégorie news de SearXNG (titre, extrait court, lien ; droits voisins) — M.
21. Dictée vocale et lecture à voix haute — la voix est partout chez les concurrents ; Web Speech interdit (CSP) — faster-whisper et Piper (MIT) côté serveur Bird, rien conservé — M.
22. Nutrition et recettes (Nutri-Score) — usage grand public secondaire — Open Food Facts v2 (ODbL), table Ciqual (Licence Ouverte) — M.
23. Prix de l'immobilier (DVF) — question française fréquente — fichiers geo-dvf d'Etalab indexés en local (agrégés) — M.
24. Rappels de produits (RappelConso) — utile et officiel — data.economie.gouv.fr, `rappelconso-v2-gtin-espaces` (Licence Ouverte) — S.
25. Connecteurs mail et agenda (Microsoft 365, Gmail) — écart majeur face à Copilot et Gemini — Graph et Gmail API (OAuth), `docs/research/connectors-design-2026-11.md` ; sécurité d'abord (voir « Plus tard ») — L.
26. Qualité de l'eau potable (Hub'Eau) — déjà prévue au prochain lot de données ouvertes — hubeau.eaufrance.fr (Licence Ouverte) — S.
27. Génération d'images — offerte par les concurrents — FLUX.1-schnell (Apache-2.0) sur l'hôte du modèle ; sécurité des contenus et transparence AI Act — L.
28. Dictionnaire et synonymes (Wiktionnaire) — plus mineur, le modèle couvre l'essentiel — fr.wiktionary.org REST (CC BY-SA, quotas) — S.
29. Scores et calendriers sportifs — peu de valeur pour le bureau — OpenLigaDB ou TheSportsDB (licences restrictives) — M.

## Plus tard

- Ultra recherche (bêta, comptes autorisés) : des centaines d'itérations par tranches reprises, journal forensique,
  garde-fous RGPD (pas de profilage de personnes privées).
- Connecteurs (`docs/research/connectors-design-2026-11.md`) : correctifs de sécurité d'abord, puis Microsoft 365 en lecture.

Références : `docs/research/competitors-2026-11.md`.
