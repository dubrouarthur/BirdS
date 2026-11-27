# Bird : ce qu'il faut prendre chez OpenAI et les autres

Lecture seule : docs/WEB.md, docs/HARNESS.md, docs/UX_BACKLOG.md (titres), ainsi que les fichiers de birds/web/static et les derniers commits. Aucun document ne décrit le Canvas en cours. La partie 2 compare donc les concurrents au périmètre annoncé dans la tâche (docs, diapos, aperçu de code, mini-tableur, construction en direct, patches).

Notation : P = priorité (5 = indispensable), E = effort (5 = lourd). Chaque pattern part de ce que les docs disent déjà de Bird :
- les données viennent des outils ou des mots de l'utilisateur ;
- le code décide, le 4B ne fait que des tâches courtes et typées ;
- le navigateur ne contacte aucun tiers ;
- le français passe en premier.

## 1. Les 25 patterns à adopter (classés par valeur)

| # | Pattern | Vu chez | Comment le faire dans Bird (déterministe, petit modèle) | P | E |
|---|---|---|---|---|---|
| 1 | **Bouton « Sources » et panneau latéral** | ChatGPT search, Perplexity | Sous la réponse, une pile de 3 icônes de sites, le compteur et « Sources ». Le clic ouvre un panneau en deux groupes : « Citées » (numérotées [n]) et « Consultées, non citées ». Ces groupes viennent de `Run.sources`, sans appel au modèle. Les fiches sources existantes restent dans le panneau. | 5 | 2 |
| 2 | **Citations [n] cliquables avec bulle** | ChatGPT, Claude Research, Perplexity | La bulle montre le titre, le domaine, l'icône (`/api/icon`), la date et l'extrait. Le passage cité est surligné **seulement s'il figure mot pour mot** dans le texte lu. Sinon, extrait simple. Un [n] qui ne correspond à aucune source lue est retiré par le code. | 5 | 2 |
| 3 | **Plan éditable avant une tâche longue** (Agent, recherche approfondie, études) | ChatGPT et Gemini Deep Research, Mistral, Office Agent | `crew.decide()` sort déjà une recette. On l'affiche en carte : étapes cochables, puis public, longueur et sites, puis « Lancer ». Modifier le plan, c'est modifier les champs typés de la recette, jamais du texte libre envoyé au modèle. En Auto, très confiant : départ après 5 s avec « Modifier » visible. | 5 | 2 |
| 4 | **Carte « Vérifications faites »** | Excel Agent Mode (« validation steps ») | `crew_checks` vérifie déjà tout. On le rend visible : « 14 chiffres vérifiés · 2 retirés (sans source) · 1 à vérifier ». Le détail se déplie avec la ligne d'origine de chaque chiffre. C'est l'atout de confiance de Bird face aux grands modèles. | 5 | 1 |
| 5 | **Retouche d'un passage sélectionné, appliquée en patch** | ChatGPT Canvas, Gemini, Claude « Edit with Claude », Copilot Rewrite | Une barre flottante sur la sélection : Reformuler, Raccourcir, Plus formel, Expliquer, Traduire, « Consigne… ». Le modèle ne reçoit que le passage et quelques lignes de contexte. Le code vérifie que rien n'a changé hors de la zone (octet pour octet) et que les chiffres et noms propres sont conservés. Il produit 2 variantes en parallèle (le lot vLLM le permet déjà), avec flèches ‹ › puis Remplacer ou Insérer dessous. | 5 | 3 |
| 6 | **Historique des versions avec restauration** | ChatGPT Canvas, Mistral Canvas | Chaque patch, retouche manuelle ou transformation crée une version (stockée en IndexedDB, protégée par try/catch). Barre « ‹ v3/5 › », « Voir les différences », « Restaurer ». Annuler une modification par l'IA ne coûte rien. | 5 | 2 |
| 7 | **Tableau interactif pour un CSV ou XLSX joint** | ChatGPT data analysis | `read_file` produit déjà les lignes. On les affiche en tableau triable avec plein écran. Cliquer une cellule ou une colonne insère une puce dans le compositeur (« colonne CA », « B4 ») ; elle est convertie côté serveur en référence exacte. Les suggestions viennent du type des colonnes (date → « Évolution par mois », nombre + catégorie → « Total par région »), pas du modèle. | 5 | 3 |
| 8 | **Graphiques qui posent une question** | Claude (visuels en ligne), ChatGPT (questions sur le graphique) | Cliquer une barre ou un point préremplit « Détaille T3 2025 » dans le compositeur, sans envoi immédiat. Bascule barres / courbe / anneau et tri dans le navigateur. Les couleurs restent les jetons fixes. | 4 | 2 |
| 9 | **Entités surlignées et panneau de faits** | ChatGPT (janv. 2026), Perplexity (prix en ligne) | On surligne **seulement** les entités déjà renvoyées par un outil : société (SIREN), lieu, devise, ville météo, terme du glossaire, titre de source. Elles sont trouvées dans la réponse par correspondance exacte du texte. Le toucher ouvre la fiche déjà construite. Ni appel ni invention : une entité sans résultat d'outil n'est pas surlignée. | 4 | 3 |
| 10 | **Règle des modes d'affichage** | Apps SDK : carte, carrousel, plein écran, PiP | C'est un contrat pour chaque widget : taille déclarée, **un seul bouton principal** par carte, carrousel de 3 à 8 éléments (lieux, images, sources, offres), plein écran pour carte, tableau, Canvas et rapport. Règle : « la plus petite présentation qui suffit ». | 4 | 2 |
| 11 | **Rapport en plein écran : sommaire, sources, export** | ChatGPT et Perplexity Deep Research, ChatGPT writing blocks | Le sommaire est tiré des titres et la section « Sources utilisées » est écrite par le code. Export .docx (existe), .md (existe) et PDF par feuille de style d'impression (`@media print`, sans bibliothèque). | 4 | 2 |
| 12 | **Progression en direct, avec consigne en cours de route** | ChatGPT Deep Research, ChatGPT agent | Les voies de l'équipe existent déjà. On ajoute « Ajouter une consigne » : le texte est mis en file et injecté **entre deux générations** comme contrainte typée (exclure un site, changer de public ou de longueur). Ensuite, un fil « Activité » repliable. | 4 | 3 |
| 13 | **Écarter / Garder pendant une comparaison** | ChatGPT shopping research | Dans la matrice de comparaison (en cours), une ligne ou une offre peut être marquée « Écarter » ou « Garder ». Le verdict est **recalculé en code** (`cost_model`), sans régénération. Le guide final donne le top, les différences clés et les compromis, écrits par le code à partir du tableau. | 4 | 2 |
| 14 | **Panneau « Livrables » de la conversation** | Perplexity Labs Assets, NotebookLM Studio | Tous les .pptx, .docx et .xlsx, les graphiques, tableaux, .ics et documents Canvas de la conversation sont réunis dans une liste, triés par type, avec aperçu et téléchargement. Source : `Run.files` plus le stockage local. | 4 | 1 |
| 15 | **Menu « Transformer en… » (Créer)** | Gemini Canvas Create, NotebookLM Studio | Il étend les transformations en un clic : Note de synthèse, FAQ, Diapos, Mail, Chronologie, Carte mentale (depuis le graphe de relations) et Quiz ou fiches de révision. Chaque cible est une recette typée (sortie JSON validée par le code), jamais un texte libre. | 4 | 2 |
| 16 | **Curseurs de longueur et de niveau de lecture** | ChatGPT Canvas, Gemini (ton, longueur) | Cinq crans. Le code vérifie l'objectif de mots (±15 %), conserve les chiffres et les noms, et refait une fois si l'écart est trop grand. Niveau : « Grand public / Professionnel / Expert » plutôt que l'échelle scolaire américaine. | 4 | 2 |
| 17 | **« Corriger avec Bird » sur une erreur d'aperçu** | Claude « Try fixing », Gemini Canvas | L'iframe d'aperçu (sandbox, sans réseau) renvoie l'erreur et la ligne par `postMessage`. La demande de réparation est étroite : erreur, extrait, consigne « patch minimal ». Le code relance les vérifications de code existantes avant d'afficher. Deux tentatives au plus, puis on le dit franchement. | 4 | 2 |
| 18 | **« Ce qui a servi pour répondre »** | ChatGPT (sources de mémoire), Copilot Notebooks | Liste des pièces jointes lues, tours antérieurs repris, mémo d'image et fiches automatiques, tirée des étapes du `Run`. Toucher un élément y renvoie. | 4 | 1 |
| 19 | **Aperçu de l'intention pendant la frappe** | Suggestions du compositeur ChatGPT, prédictions acceptées par Tab | `intents.py` tourne déjà sur les mots. En frappant, une puce discrète « → Météo · Lyon · demain » montre ce que le harnais va faire. Tab l'accepte, Échap l'ignore. L'utilisateur voit l'interprétation avant l'envoi, ce qui convient bien à un petit modèle. Côté serveur, c'est un point de terminaison léger sans appel au modèle. | 4 | 3 |
| 20 | **Restreindre ou prioriser des sites** | ChatGPT Deep Research (Manage sites) | Puce « Sites » dans le compositeur, avec préréglages FR (service-public.fr, legifrance.gouv.fr, insee.fr, economie.gouv.fr) et la bascule « Prioriser / Seulement ». Appliqué dans `web_search` : filtre `site:` si le moteur le gère, sinon filtrage a posteriori. Les sites retenus sont rappelés dans les sources. | 3 | 2 |
| 21 | **Position « près de moi » sur option** | ChatGPT (location sharing) | `navigator.geolocation` uniquement après une action explicite. Arrondie à la commune côté serveur (BAN, géocodage inverse), jamais stockée. Elle sert à la météo, aux lieux et à l'horloge. Position précise désactivée par défaut, réglage dédié. | 3 | 2 |
| 22 | **Brancher depuis un message ou modifier une question** | ChatGPT (Branch in new chat), Claude (versions) | Arbre de conversation dans le stockage local. Modifier un message crée une branche « ‹ 1/2 › ». Chaque branche garde ses livrables et ses versions Canvas. | 3 | 3 |
| 23 | **Niveaux d'approbation par outil** | ChatGPT plugins (toujours demander / avant les modifications / seulement l'important) | Réglage par famille : brouillons de mail, création de fichiers, code. La fenêtre Autoriser / Refuser existe. On ajoute « Toujours autoriser pour cette conversation ». La limite de 5 actions à effet reste dans le code. | 3 | 1 |
| 24 | **Mise en page combinée pour les demandes de planification** | Gemini visual layout, Apps in ChatGPT | Pas d'interface générée par le modèle. À la place, des **gabarits déterministes** : « déplacement à Lille jeudi » donne une chronologie, une carte, la météo, l'horloge et un .ics, assemblés à partir des fiches existantes et déclenchés par le harnais. | 3 | 3 |
| 25 | **Tâche répétée (« Refaire chaque lundi ») et veille qui prévient seulement si ça change** | ChatGPT scheduled tasks, Perplexity Tasks, Notion Custom Agents | Après une réponse réussie, une icône horloge propose une fréquence. C'est la même requête typée, rejouée par le serveur. La comparaison se fait sur l'empreinte des faits vérifiés, et l'avis n'arrive que s'il y a un écart. Il faut d'abord un stockage côté serveur ou un appareil qui reste allumé : à planifier après les comptes. | 3 | 4 |

À écarter pour l'instant :
- **Audio Overview et voix** : coût de calcul, et pas de synthèse vocale locale propre en français.
- **Essayage virtuel et cours de bourse** : déjà écartés, hors des usages d'entreprise.
- **Interface entièrement générée par le modèle (Gemini dynamic view)** : contraire au principe déterministe.

## 2. Ce qui manque au Canvas en cours, face aux concurrents

**Édition et contrôle**
1. **Retouche ciblée sur une sélection** (ChatGPT, Gemini, Claude, Copilot). C'est la fonction centrale des Canvas concurrents. Chaque bloc doit avoir un identifiant stable ; un patch vise `block_id` + plage, et le code refuse tout changement hors de la plage.
2. **Le document du Canvas fait foi** (ChatGPT, Mistral). Les modifications manuelles (contenteditable) doivent être envoyées au modèle sous forme d'état courant ou de diff, pas de l'historique du chat. Sinon le 4B réécrit sur une version périmée.
3. **Suggestions en commentaires, à accepter ou refuser une par une** (ChatGPT « Suggest edits »). Le modèle rend `[{citation exacte, suggestion, raison}]`. Le code écarte toute citation introuvable mot pour mot et affiche des marques dans la marge.
4. **Variantes à parcourir avant d'accepter** (Copilot Rewrite, flèches puis Remplacer ou Insérer dessous). Rien ne change sans clic.
5. **Historique, différences, restauration** (ChatGPT, Mistral). Voir pattern 6. Il faut aussi « Annuler » au clavier (Ctrl+Z = version précédente).
6. **Raccourcis d'écriture** en bas à droite : longueur, niveau, « Relecture finale » (orthographe, typographie française : espaces insécables, guillemets « »), traduire FR↔EN.

**Code et aperçus**

7. **Raccourcis de code** (ChatGPT) : relire, commenter, corriger, ajouter des logs, porter en Python, JS ou TS. Les résultats des vérifications de code existantes deviennent des marques dans la gouttière, chacune avec « Corriger ».
8. **Boucle sur les erreurs d'aperçu** (Claude, Gemini). Voir pattern 17. L'aperçu se fait dans une iframe `sandbox="allow-scripts"` servie par une route `/preview` qui a sa propre CSP (`connect-src 'none'`) : aucun appel réseau, compatible avec la CSP de la page (`frame-src 'self'`).

**Forme et place du Canvas**

9. **D'abord dans le fil, ouverture ensuite** (ChatGPT a remplacé Canvas par des blocs dans le fil en mai 2026 ; règle Claude : à partir d'environ 15 lignes). Un contenu court reste un bloc dans la réponse, avec « Ouvrir dans le Canvas ». Un document long s'ouvre en plein écran avec sommaire. Pas de changement de mode forcé.
10. **Plusieurs documents** : bibliothèque locale des Canvas, « Reprendre », lien depuis le panneau Livrables. Claude permet aussi de mettre en file des modifications sur plusieurs fichiers ; c'est moins prioritaire.

**Diapos (Gamma, Copilot)**

11. **Thème séparé du contenu** : changer de thème sans toucher au texte (Gamma). Le générateur .pptx a déjà un thème Bird ; il faut au moins 2 à 3 thèmes et une bascule dans l'aperçu.
12. **Bouton « ✦ » par diapositive** (Gamma). Chaque carte se retouche seule ; « Toutes les diapos » sert pour la traduction et le ton.
13. **Suggestions de mise en page par le code** (Copilot Design Suggestions). Une règle sur la forme du contenu : un grand chiffre → diapo « chiffre clé » ; 2 listes → deux colonnes ; une citation → diapo citation ; 3 à 5 étapes → chronologie. Pas de modèle.
14. **Image par diapositive à partir des images du web**, créditée (titre et domaine, comme aujourd'hui), avec « Remplacer » et « Sans image ».
15. **« Présentation à partir d'un fichier »** (Copilot) et mention « /fichier » dans le compositeur pour ancrer un brouillon sur une pièce jointe (Copilot Draft).
16. **Questions avant de lancer** (Office Agent : longueur, thème, public, angle). Elles sont reprises dans la carte de plan (pattern 3), avec aperçu en direct des diapos pendant la construction.

**Mini-tableur**

17. **Vraies formules** dans l'export .xlsx (Claude Create files). Il faut aussi :
    - cliquer une cellule pour la citer (pattern 7) ;
    - « Graphique de la sélection » (`make_chart` sur la plage choisie) ;
    - « Présenter en tableau » sur un texte sélectionné (Copilot Visualize as table) : extraction par le code d'abord, modèle en secours.

**Parité et partage**

18. **Ce qu'on voit = ce qu'on obtient.** L'export doit passer par les mêmes générateurs `make_*` que l'aperçu, avec un test visuel aperçu ↔ fichier.
19. **Partage** : Claude et Copilot partagent par lien. Bird n'a pas de comptes, donc rien de public. On propose un export HTML autonome, « Copier pour Word / Mail » (HTML dans le presse-papiers) et l'impression en PDF. Il faut le dire clairement dans l'interface.
20. **Chiffres sources dans le Canvas.** Un chiffre ajouté par une retouche passe la même vérification que celle de l'équipe ; s'il n'a pas de source, il est marqué « non vérifié ». Les concurrents ne le font pas : c'est un différenciateur à garder.

## 3. Conventions d'interface à copier

**Citations**
- Pastille numérotée [1] collée à la fin de la phrase. Si une phrase a plusieurs sources : « [1] +2 ».
- Survol ou toucher : bulle avec icône, titre, domaine, date et extrait (passage surligné s'il est exact).
- Bas de réponse : pile d'icônes + « N sources », qui ouvre le panneau (ChatGPT).
- Pas de liste de sources en tête de réponse comme Perplexity : la réponse d'abord, en français.

**Carrousel de sources, lieux, images et offres**
- 3 à 8 cartes de taille fixe, défilement avec accroche (scroll-snap), flèches sur ordinateur, balayage sur téléphone.
- Pour les images, cadre fixe (le 4:3 existe) pour que rien ne bouge au chargement.
- Une seule action par carte (ouvrir la source).

**Progression des agents**
- Repliée, une ligne au présent : « Lit 3 pages · 0:42 » ; au passé une fois fini (« 3 pages lues »).
- Dépliée, le plan en liste avec l'étape en cours mise en avant.
- « Arrêter » toujours visible, « Ajouter une consigne » pendant les longues tâches.
- À la fin, « Ce que l'équipe a fait » replié, plus la carte de vérifications.
- Si l'onglet est caché : badge dans le titre de l'onglet, puis notification si l'utilisateur l'a autorisée.

**Suggestions de relance**
- Sous les fiches, à la fin de la réponse, 3 au plus, alignées à gauche.
- Rédigées à la voix de l'utilisateur (« Compare avec Marseille »), tirées des résultats d'outils.
- Elles disparaissent dès qu'il tape ou au tour suivant.
- Envoi direct si la suggestion est complète, préremplissage s'il manque un paramètre.
- Un clic dans un graphique ou une cellule préremplit le compositeur (Claude, ChatGPT).

**Raccourcis d'édition**
- Barre flottante sur la sélection (Gemini, Claude), ou icône dans la marge gauche (Copilot) sur téléphone, où la barre gêne le menu natif.
- Menu de raccourcis en bas à droite du Canvas (ChatGPT).
- Commandes « / » dans le compositeur (/canvas, /recherche, /sites, /fichier).
- Tab accepte une suggestion, Échap la refuse, Ctrl+Z revient à la version précédente.
- Résultat toujours en aperçu avec Remplacer, Insérer dessous ou Annuler.

**Confirmations**
- Carte dans le fil avec un seul bouton principal pour les actions ordinaires.
- Fenêtre modale réservée aux actions à effet (existe déjà).

**Fraîcheur et origine des données**
- Chaque fiche dit sa source et son heure (« MET Norway · 07:25 »), comme ChatGPT avec ses partenaires.
- Les étiquettes « automatique » et « non vérifié » restent : elles sont déjà au-dessus de l'usage chez les concurrents.

**Les cinq premiers chantiers (gain maximal, effort faible)** : n° 4 (vérifications visibles), n° 1 et 2 (sources et citations), n° 3 (plan éditable), n° 6 et n° 5 (versions, puis retouche d'une sélection en patch), n° 14 (panneau Livrables).