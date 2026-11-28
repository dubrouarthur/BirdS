# Le canevas de Bird

Code : `birds/canvas/` (format, patchs, images, exports, tours), `birds/web/canvas_web.py` (événements, points d'accès,
cadre d'aperçu), `birds/web/canvas_demo.py` (démo scriptée), `birds/web/static/canvas*.js|css` (panneau).
Tests : `tests/test_canvas.py`, `tests/js/canvas.test.mjs`, `tests/e2e/canvas.spec.js`. Essai réel : `scripts/canvas_eval.py`.

## 1. Le principe

Bird est un petit modèle : il ne dessine jamais une mise en page. Il écrit du **contenu** dans un petit format texte,
proche du Markdown, que le harnais lit avec indulgence et range dans un **modèle de document** unique ; ce document est
dessiné dans des thèmes déjà conçus (Sobre, Moderne, Chaleureux — les mêmes que le moteur bureautique), en direct dans
le canevas et en .pptx / .docx / .xlsx. Comme les artefacts de Claude : le modèle écrit, le harnais compose.

```
---
title: Plan mobilité 2027
subtitle: Comité de direction
theme: moderne
---
# Contexte
- 40 % des trajets font moins de 5 km
::: image query="vélo en ville"
:::
# Chiffres clés
::: kpi
1,2 M€ | Budget | +8 %
31 % | Part modale
:::
# Évolution
::: chart type=bar unit="M€"
2023: 1,1
2024: 1,4
:::
# Calendrier
::: timeline
T1 2026 : pilote
:::
> « Mesurer avant de généraliser. » — Une élue
```

Blocs : `kpi`, `chart` (bar, line, pie), `table` (ou un tableau `| a | b |`), `timeline`, `steps` (étapes d'une
méthode), `compare` (`A | B` puis les points, ou « A : » suivi de puces), `cards` (`Nom : description`),
`image query="…"`, `quote` (ou `>`), `code` (ou une clôture ` ``` `), `note` / `attention` (encadrés), `notes` (notes
de l'orateur). En tête : `image: <mots>` pour la photo de couverture. Une mise en page peut être demandée
(`# Titre {versus}` ou `layout: étapes`) ; le harnais ne la garde que si le contenu s'y prête (§ 9). Les
alias français sont lus (`graphique`, `frise`, `citation`, `tableau`, `chiffres`…).

**Le parseur ne plante jamais** (`dsl.parse`, essai à données aléatoires dans les tests) et liste ses réparations :
bloc `:::` non fermé, titres numérotés (« Diapositive 3 : »), titre du deck en `#` et diapositives en `##`, « Titre : »
au lieu d'un en-tête, séparateurs `---` (Marp), image Markdown `![vélo](url)` (l'URL n'est **jamais** suivie : ses mots
deviennent la requête), phrase d'introduction avant le premier titre (laissée dans le chat), réponse coupée par la
limite de longueur (le début est gardé, le chat le dit). Une liste simple est lue pour ce qu'elle est (`convert.enrich`,
mêmes règles que le moteur bureautique) : « 2023 : 1,1 M€ » × 4 → graphique, dates → frise, « « … » — Auteur » →
citation, 1 à 4 chiffres courts → tuiles. Aucun chiffre n'est inventé : tout vient des puces.

## 2. Quand le canevas s'ouvre

`birds/canvas/intents.py`, sur les seuls mots de l'utilisateur : une présentation, un document (rapport, note de
synthèse, compte rendu…), une page web / du code visuel (HTML, CSS, JS, SVG, script Python), un schéma (organigramme,
logigramme, flowchart). Jamais sur une question pratique (« comment faire une présentation ? »), un mail, un résumé, une
traduction ; la liste `OFFICE_NO` du banc de déclenchement ne l'ouvre pas (test). **Un format de fichier nommé**
(« une présentation pptx », « un document Word ») garde le chemin entraîné `make_slides` / `make_document` : le fichier
est livré comme avant **et** proposé dans le canevas (« Ouvrir dans le canevas »). Un tableur reste fait par
`make_sheet` et s'ouvre en mini-tableur. Les présentations de recherche du Mode Agent restent à l'équipe ; leur
fichier est aussi proposé dans le canevas.

## 3. Un tour de canevas

- **Création.** Pour ce tour seulement, `make_slides` / `make_document` / `make_sheet` sortent du bloc d'outils, et
  le message utilisateur reçoit la courte spécification du format (`turn.SPEC`, ~170 tokens). Les tours ordinaires
  gardent le bloc d'outils entraîné **octet pour octet** (test). Pendant que le modèle écrit, le texte est relu toutes
  les 0,35 s : chaque nouveau bloc apparaît dans le canevas (`canvas` phase `stream`), le chat ne reçoit pas le
  contenu (une carte « Rédaction en cours… »). Rattrapages d'un 4B : un appel `make_slides` fait quand même est capté
  (`canvas_sink`) et ses arguments deviennent le document ; les arguments écrits en JSON dans le texte aussi ; les
  relances « aucun fichier n'a été créé » / « appelle make_chart » sont coupées sur ces tours.
- **Modification, sans modèle** (`patch.direct_ops`) : « supprime la diapo 3 », « duplique la slide 2 », « inverse
  les slides 2 et 3 », « mets la diapo 4 au début », « passe en thème chaleureux », « remplace l'image de la slide 1 par
  une photo de tramway », « une autre image pour la diapo 2 », « retire l'image… », « renomme la slide 2 en … ».
- **Modification par le modèle** (`patch.parse_patch`) : il reçoit le plan avec les repères `[b1]`, `[b2]`… et écrit
  `@replace b3` + le bloc, `@after b4` + le bloc, `@delete b2`, `@theme warm`. Indulgent : verbes français, `@`
  oublié (ligne en capitales), bloc qui garde son repère `[b3]` (= remplacer b3), nouveaux blocs sans opération
  (placés où l'utilisateur l'a dit, sinon avant la diapositive de clôture), document entier réécrit (« plus court ») :
  nouvelle version qui garde le thème, les images et les repères des blocs au même titre. Sur un tour de
  modification, aucun outil n'est proposé, sauf la recherche web si les mots la demandent.
- **« Demander à Bird » sur un bloc** : seul ce bloc est donné au modèle, qui le réécrit.
- **Code** : le fichier complet est rendu et réécrit en entier (« mets le bouton en vert »).

Chaque résultat est une **version** (v1, v2…) du même artefact ; le navigateur les garde (localStorage, 24 au plus,
v1 toujours) et passe de l'une à l'autre sans diff. L'historique du modèle reçoit une ligne de mémo
(`[canvas deck v3 « … »: b1 Contexte; b2 …]`).

## 4. Le panneau

Bureau : à droite du chat (la barre latérale se replie sous 1 700 px tant qu'il est ouvert, la préférence enregistrée
n'est pas touchée). Téléphone (< 1 000 px) : feuille plein écran, Échap ou × pour revenir au chat.

- **Présentation / document** : couverture, puis une diapositive ou une section par bloc, dessinée selon son contenu
  principal (graphique, tableau, frise, tuiles, citation, image à côté du texte, phrase seule). Clic (ou Entrée / F2)
  sur un texte : édition sur place, Entrée ou sortie du champ = nouvelle version, Échap annule. Par bloc : monter,
  descendre, dupliquer, supprimer, image (chercher, une autre, importer, retirer), « Demander à Bird ». Thème en trois
  pastilles. Télécharger : .pptx, .docx (moteur bureautique, mêmes thèmes, graphiques natifs, images créditées, sans
  sommaire ni diapositive de clôture que le canevas ne montre pas), PDF (impression, une diapositive 16:9 par page).
  « Copier » donne le Markdown.
- **Code** : onglets Aperçu / Code (aperçu par défaut une fois le fichier complet). HTML, CSS, JS et SVG tournent dans
  `/canvas/frame` ; les erreurs de console s'affichent, avec « Corriger avec Bird ». Les schémas `flowchart` / `graph`
  sont dessinés par un petit moteur maison (`canvas-flow.js`, formes, étiquettes, retours en arrière) : pas de
  bibliothèque Mermaid. Python et JSON : vérification de syntaxe côté serveur (`/api/canvas/check`), **jamais
  d'exécution**.
- **Mini-tableur** : grille éditable (barre de formule, flèches, Maj+flèches pour sélectionner), formules `=SOMME`,
  `=MOYENNE`, `MIN`, `MAX`, `NB`, `ARRONDI(x;n)`, `SI(c;a;b)`, `PRODUIT` (et leurs noms anglais), références et plages,
  `%`, décimales françaises ; erreurs `#DIV/0!`, `#CYCLE!`, `#NOM?`… — évaluées sans `eval()`. Tri par colonne,
  « Graphique » sur une sélection (libellés + colonnes numériques), « Demander à Bird » sur une sélection (tableau
  Markdown dans la zone de saisie), export .xlsx et CSV. À l'export .xlsx (`birds/canvas/sheetfx.py`), les formules
  passent en OOXML (noms anglais, séparateur `,`, décimales `.`, lignes décalées sous l'en-tête) et chaque valeur
  calculable est écrite en cache (`<v>`), pour les aperçus de fichiers.

Accessibilité : boutons nommés, barre d'outils par bloc, onglets au clavier (flèches), grille `role=grid` avec
cellule active, statut `aria-live` (« Bird écrit… 3 diapositives »), annonce de chaque nouvelle version, focus rendu
au bouton d'origine à la fermeture.

## 5. Sécurité

- Le texte du modèle et de l'utilisateur n'entre dans la page qu'en nœuds texte (`textContent`) ou par le rendu
  Markdown échappé du chat. Les icônes sont des constantes.
- **Aperçu du code** : `iframe src="/canvas/frame" sandbox="allow-scripts"` (sans `allow-same-origin` : origine
  opaque, aucun accès à l'application, à son stockage ni à ses cookies). Le cadre a sa propre CSP :
  `default-src 'none'; connect-src 'none'; img-src data: blob:; font-src data:; form-action 'none'; sandbox
allow-scripts` — **aucune requête réseau**. La CSP de l'application n'autorise que `frame-src 'self'` : le cadre ne
  peut pas naviguer ailleurs. Le code arrive par `postMessage` ; la console revient de même (source vérifiée). Le test
  de bout en bout vérifie depuis le cadre : `parent.document`, `localStorage`, `fetch` local et distant échouent.
- **Images** : `::: image query="…"` est résolu par le harnais (Wikimedia Commons, fichiers bitmap, licence lue sur
  Commons et vérifiée libre — CC0, domaine public, CC BY, CC BY-SA ; NC/ND refusées —, crédit et lien source gardés,
  octets re-encodés côté serveur). Jamais une URL écrite par le modèle. En démo : une illustration abstraite dessinée
  sur place, étiquetée « Illustration (démo) ». Aucune image trouvée : un emplacement « Chercher une image », rien
  d'inventé. Le navigateur ne contacte aucun tiers (test : aucune requête hors origine).
- **Points d'accès** (`same-origin`, limite de débit, code d'accès comme `/api/tool`) : `POST /api/canvas/export`
  (document revalidé champ par champ — types, tailles, identifiants `b\d+`, parties connues ; corps ≤ 4,4 Mo pour
  Vercel ; images ≤ 10 × 700 Ko base64 ; aucun chemin de fichier venu du client), `POST /api/canvas/image` (requête de
  mots, identifiant de média contrôlé), `POST /api/canvas/check`, `GET /canvas/frame`. Le document envoyé avec un
  message est revalidé ; invalide, il est ignoré (le tour reste ordinaire), trop gros (> 400 000 caractères) : 413.
- **Injection de formules** : à l'export .xlsx, les formules qui sortent du fichier (`HYPERLINK`, `WEBSERVICE`, DDE
  `cmd|…`, liens externes…) sont écrites comme texte (moteur bureautique) ; le CSV préfixe d'une apostrophe toute
  cellule texte commençant par `= + - @`.

## 6. Mesures

|                                                     | avant (base + office-engine) | après                                                                |
| --------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------- |
| pytest                                              | 1 510 réussis                | 1 616 réussis (+106 canevas)                                         |
| node --test tests/js                                | 39                           | 48                                                                   |
| banc de déclenchement                               | 872/875                      | 872/875 (inchangé : le canevas a sa propre détection, testée à part) |
| poids statique de l'app                             | 736 Ko                       | 863 Ko (+126 Ko brut, +34 Ko gzip)                                   |
| e2e canevas (démo, 1440 et 360 px, clair et sombre) | —                            | 4 parcours, 60 vérifications, 0 erreur de page, 0 requête tierce     |

## 7. Ce qui reste à vérifier

- **Le vrai modèle** : mesuré le 27/11/2026 (Bird S 4B, vLLM, `scripts/canvas_eval.py`, 16 générations en tout),
  voir § 8. Le format texte est suivi ; les opérations de modification copiaient l'exemple du format (corrigé, à
  re-mesurer en direct).
- La recherche d'images Commons n'a été testée qu'avec un faux client (pas de réseau ici).
- L'impression PDF repose sur les pages nommées CSS (Chromium) ; Firefox imprime en portrait.
- L'édition sur place utilise `contenteditable="plaintext-only"` (repli sur `true` ailleurs).

## 8. Le canevas, interrupteur mesuré (`BIRD_CANVAS_OFF`)

`BIRD_CANVAS_OFF=1` (réglage du déploiement, `Settings.canvas`) : chaque tour est ordinaire, les outils entraînés
`make_slides` / `make_document` / `make_sheet` font le fichier, et le canevas l'adopte seulement (« Ouvrir dans le
canevas »). Par défaut (activé) : une demande de création claire est écrite au format texte à côté du chat ; tout ce
qui n'est pas clairement une création reste un tour ordinaire, où le modèle choisit lui-même son outil entraîné.

Mesure en direct, 27/11/2026, Bird S 4B (endpoint de production, mêmes cas que `canvas_eval.py`) :

| Cas                                   | Canevas activé (format texte)                                   | `BIRD_CANVAS_OFF=1` (outil entraîné adopté)        |
| ------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------- |
| Présentation 5 diapositives           | ✔ 5 diapositives, kpi + graphique + frise + citation, 1 réparation (bloc non fermé) | ✔ 5 diapositives, listes seules ; le chat recopie tout le contenu |
| Note de synthèse                      | ✔ 5 sections, encadré, 351 jetons, 7 s                          | ✔ 5 sections, 373 jetons                           |
| Page web                              | ✔ HTML complet (après une recherche web)                        | —                                                  |
| Schéma                                | ✔ Mermaid, 123 jetons                                           | —                                                  |
| **Format suivi (création)**           | **4/4**                                                         | 2/2 par l'outil (sans blocs riches)                |
| Bloc ciblé (« Demander à Bird »)      | ✔ réécrit, 6/6 identifiants gardés                              | —                                                  |
| « ajoute une slide sur les risques »  | ✘ 2/2 : l'exemple du format recopié (`@replace b3`, `@delete b2`) : une diapositive perdue | —                         |
| « plus court »                        | ✘ 2/2 : même recopie, le deck s'allonge                         | —                                                  |
| « passe en thème chaleureux »         | ✘ non reconnu comme modification (corrigé : `passe` est un verbe d'édition, appliqué sans modèle) | —           |
| **Modifications réussies**            | **1/6** avant correction                                        | —                                                  |

Décision : le canevas reste activé pour la création (le format est suivi et plus riche que le chemin entraîné).
Les modifications libres sont réparées côté harnais (exemple sans identifiants réels, opérations non demandées
écartées, voir le commit suivant) ; à re-mesurer en direct avant toute autre décision. Si elles restent sous 5/6,
`BIRD_CANVAS_OFF=1` reste le repli.

Réparations du harnais après cette mesure (rejouées hors ligne sur les réponses réelles, `tests/test_canvas.py`
`LIVE_ADD` / `LIVE_SHORT`) : l'exemple du format n'a plus d'identifiant réel (`@after <repère>`) ; une opération que
les mots de la personne ne demandent pas est écartée (`patch.fit` : suppression, thème ou déplacement non demandés, un
remplacement à côté du bloc demandé en ajout, un ajout ou un bloc rallongé sur « plus court ») ; si rien ne reste, le
chat le dit au lieu d'afficher les opérations. Sur les deux réponses réelles : « ajoute une slide » donne 6 diapositives
sur 6 attendues, toutes gardées ; « plus court » ne casse plus rien. L'effet du nouvel exemple sur le modèle reste à
mesurer en direct (budget de générations atteint).

## 9. Diapositives « exceptionnelles » : 21 mises en page, quatre thèmes, images libres (branche `canvas-decks`)

Code : `birds/canvas/layouts.py` (catalogue et choix), `birds/canvas/deck_pptx.py` (le .pptx), `birds/canvas/images.py`
(Openverse, Commons, cache), `birds/web/static/canvas-layouts.js` (la même règle dans le navigateur). Tests :
`tests/test_canvas_decks.py`, `tests/js/canvas-layouts.test.mjs`, `tests/e2e/canvas-decks.spec.js`. Mesure :
`scripts/deck_eval.py`, fichiers `docs/measures/deck-eval-2026-11-28-*.json`.

**Le modèle type, le harnais compose.** Le modèle écrit des diapositives typées (`kpi`, `compare`, `steps`, `cards`,
`chart`, `image`…) et peut nommer une mise en page ; `layouts.pick` choisit parmi 21 mises en page conçues —
intercalaire, sommaire, message clé, points, deux colonnes, chiffre clé géant, rangée de chiffres, face à face (VS),
comparaison à 3 colonnes, frise, étapes, citation, image à gauche / à droite, plein cadre, galerie, graphique + message
clé, tableau, cartes (équipe, piliers), clôture, code — plus la couverture plein cadre avec photo. Le choix du modèle
n'est gardé que si le contenu s'y prête (`fits` : un « chiffre clé » sans chiffre est refusé, jamais forcé). Une liste
écrite à côté d'un bloc dessiné seul (`- …` puis `::: cards`, habitude du 4B) devient deux diapositives (`split`) :
rien n'est perdu. Menu « Mise en page » par diapositive : seules les mises en page compatibles sont proposées.

**Aperçu = fichier.** Le navigateur (`canvas-layouts.js`) et le .pptx (`deck_pptx.py`) appliquent la même règle,
vérifiée sur un jeu commun (`tests/fixtures/canvas_layouts.json`, 34 cas, pytest et node). Les palettes CSS (`--d-*`)
sont celles de `deck_pptx.PALETTES` (test). Même grille (1 pouce = 7,5 cqi), même police (Carlito, jumelle métrique de
Calibri ; Georgia pour les titres Terracotta). Chaque thème a son masque .pptx (fond) ; graphiques natifs éditables ;
crédit de chaque image sur la diapositive et dans les notes.

**Thèmes** : Bleu Bird, Forêt, Terracotta, Nuit (sombre). « passe en thème nuit » est appliqué sans modèle.

**Images** : la requête vient du modèle (en anglais depuis la mesure ci-dessous, les fonds Openverse / Commons étant
surtout anglophones), jamais une URL. Openverse d'abord (licences demandées à l'API ET revérifiées par résultat :
CC0, marque domaine public, CC BY, CC BY-SA ; auteur obligatoire hors domaine public), puis Commons ; le résultat doit
parler de la requête (`relevant` : un mot pour une requête courte, deux au-delà ; Commons aussi depuis la mesure),
une requête longue est retentée courte, rien plutôt qu'une image hors sujet. Récupération par le garde d'egress,
ré-encodage serveur, cache mémoire (96 entrées, 1 h), 8 images par deck au plus en 20 s. Le navigateur reçoit des
octets (blob:) : aucune requête tierce (e2e). « Une autre image » / « Sans image » par diapositive et pour la couverture.

**Panneau** : diapositives qui apparaissent une à une pendant l'écriture (animation coupée si `prefers-reduced-motion`),
poignée pour glisser-déposer (les flèches restent pour le clavier), ✦ « Demander à Bird » par diapositive, versions
avec « Restaurer cette version », thème appliqué à l'instant. Carte du chat : la couverture en miniature, « N
diapositives · M mises en page », puis 2-3 suites concrètes selon ce qui manque (images, chiffres clés, clôture,
« Plus court », thème suivant).

### Mesure en direct, 28/11/2026 (Bird S 4B, endpoint de production, 6 demandes fixes, 26 générations au total)

« avant » = la base `8d439bd` ; « après » = cette branche (passage `after3`, spécification finale ; `after` et
`after2` sont les passages intermédiaires, gardés). Mises en page comptées telles que dessinées (règle de canvas.js
pour la base, `layouts.pick` après). Recherche d'images : `BIRD_PIN_DNS=0` (le bac à sable passe par un proxy).

| Demande | avant : sortie | avant : diapos / mises en page distinctes | après : sortie | après : diapos / distinctes | images après (demandées / trouvées) | réparations après | s (avant → après) |
|---|---|---|---|---|---|---|---|
| 1 mobilité douce, conseil municipal | ✘ chat (veto « conseil ») | — | ✔ canevas | 10 / 6 | 1 / 1 | 1 | 12,4 → 20,2 |
| 2 pitch deck livraison à vélo | ✔ canevas | 7 / 3 | ✔ canevas | 11 / 8 | 1 / 0 | 5 | 12,2 → 19,5 |
| 3 cybersécurité, nouveaux arrivants | ✔ canevas | 7 / 4 | ✔ canevas | 7 / 5 | 2 / 0 | 2 | 13,6 → 10,6 |
| 4 bilan du club (chiffres donnés) | fichier de l'équipe Agent, 2 diapos | 2 / 2 | idem (l'Agent garde ce cas) | 2 / 2 | 0 / 0 | 0 | 8,5 → 9,2 |
| 5 télétravail vs bureau | ✘ fichier .pptx seul (veto « compare ») | — | ✔ canevas | 12 / 5 | 1 / 0 | 4 | 16,4 → 16,6 |
| 6 train de nuit en Europe | ✘ chat (le modèle refuse) | — | ✔ canevas | 10 / 7 | 2 / 1 (écartée ensuite par la règle des deux mots) | 3 | 5,9 → 22,2 |
| **Total** | **2 decks / 6 au canevas** | moyenne 3,5 mises en page | **5 / 6 au canevas** | moyenne **6,2** mises en page (4 à 8) | **7 demandées, 2 trouvées** | — | — |

Lecture :
- Variété : 3,5 → 6,2 mises en page distinctes par deck (base : surtout « liste » et tuiles de chiffres). Les
  diapositives alternent souvent points / bloc depuis `split` (la liste n'est plus perdue).
- Réparations : surtout des blocs `:::` non fermés (lus comme voulu) et une tête sans `---` d'ouverture (réparée).
- Images : le modèle demande une image de couverture presque toujours, rarement sur les diapositives malgré la
  consigne. Trouvées : 2 sur 7, car l'API anonyme d'Openverse et celle de Commons renvoyaient **429 (limite de
  débit)** depuis le bac à sable pendant la mesure : chiffre plancher, à refaire depuis le déploiement. Une image
  trouvée hors sujet (« Calendrier sept 2024 » pour « équipe en réunion », Commons) a conduit à vérifier aussi
  Commons ; une autre (« Praha Hilton » pour « night train europe luxury ») à exiger deux mots d'une requête longue.
- La demande 4 (« bilan 2025 … 320 adhérents … ») part à l'équipe du Mode Agent (signaux « chiffres » + « 2025 ») et
  sort en fichier de 2 diapositives : non modifié ici (le Mode Agent reste en Auto ; un essai « deck d'abord au
  canevas » cassait les decks de recherche sourcés de l'Agent, testés : retiré).
- Le modèle écrit parfois un chiffre qui n'est pas dans la demande (« 30 % » dans le deck 1) : la consigne le
  défend, aucun contrôle automatique ici.
- Déclenchement : 2094/2094 avant et après (`trigger_bench.py`) ; les deux faux veto corrigés ont leurs tests.

Captures regardées : chaque mise en page en 1280 et 360 px, clair et sombre, et les quatre thèmes
(`tests/e2e/canvas-decks.spec.js`). Le .pptx de la galerie a été rendu par LibreOffice et regardé.

Reste à vérifier : les images en production (limites Openverse / Commons ; une clé Openverse enregistrée lèverait la
limite), l'ouverture du .pptx dans PowerPoint (seul LibreOffice a été regardé), l'effet de la consigne « image sur 2-3
diapositives » (peu suivie), le rendu des thèmes dans Keynote / Google Slides.
### Images et graphiques dans les présentations (28/11/2026, demande du produit)

Plainte : « les images marchent mal dans les prez ; il faut pouvoir intégrer des graphes aussi ». Mesuré, corrigé,
remesuré. Code : `birds/canvas/images.py` (recherche), `birds/canvas/figures.py` (provenance des chiffres),
`birds/harness/office_media.py` (`Fetcher`). Tests : `tests/test_canvas_media.py` (18). Mesures :
`scripts/deck_media_eval.py` (8 demandes fixes, de bout en bout), `scripts/image_ab.py` (20 requêtes d'image fixes,
ancienne et nouvelle recherche en alternance, donc sous les mêmes limites de débit), fichiers
`docs/measures/deck-media-2026-11-28-*.json` et `docs/measures/deck-images-ab-2026-11-28.json`.

**Pourquoi les images échouaient** (constaté, pas supposé) :
- **Production : 0 image sur 10 demandées** (8 decks, `--url https://bird-s.vercel.app`). Le point d'accès
  `/api/canvas/image` de production trouve « brittany coast » mais pas « honey bee » : la chaîne fonctionne, ce sont
  les **limites de débit (HTTP 429)** d'Openverse (API anonyme) et de l'API Commons (`imageinfo` + vignettes) qui
  refusent par fenêtres courtes, depuis des adresses partagées (Vercel comme le bac à sable). Un 429 était lu comme
  « rien trouvé », sans seconde tentative.
- **Pertinence** : la règle des mots acceptait les mots-clés Flickr (« Venice, canalside view » étiquetée
  « train ») et le nom de l'auteur (« … - Flickr - Avel-Breizh » pour « breizh »). Regardées une à une, 3 images sur 8
  étaient hors sujet (une femme photographe pour « Bretagne tourism », Venise pour « night train »).
- **Requêtes** : le modèle écrit « happy cyclist delivering food » (zéro résultat tel quel sur Commons) ou demande
  la photo d'un graphique (« chart showing quarterly growth » donnait le tracé radio d'un pulsar).
- **Temps** : 8 recherches l'une après l'autre (jusqu'à 10 téléchargements chacune) dans les 20 s du tour.

**Corrections** :
- **Le modèle regarde chaque candidate** (`images.vision_judge`, il lit les images) : « Does this photo show « … »,
  well enough to illustrate a slide about it? » — oui / non, vignette 448 px, 3 jetons, 0,2 à 0,4 s ; 6 regards au
  plus par recherche, puis aucune image plutôt qu'une fausse. Sur 20 images étiquetées à la main, d'accord 15 fois
  (une formulation plus permissive testée : 12/20, et elle acceptait une oratrice pour « night train » : écartée).
- Règle des mots : titre nettoyé (auteur Flickr, n° geograph / panoramio, nom de fichier d'appareil), un mot du
  titre exigé, mots-clés comptés pour une requête d'un ou deux mots seulement, deux mots du titre au-delà.
- Variantes de requête (`variants`) : telle quelle, sans les mots qui ne se photographient pas (« happy »,
  « modern »…), puis ses deux premiers mots ; aucune recherche pour un graphique ou un tableau (il se dessine).
- 429 : une seconde demande après 1,2 s (`Fetcher.json`) ; User-Agent conforme à la politique Wikimedia (contact
  `BIRD_CONTACT`) pour Commons ; le refus est noté (`images.COOL`) et « Chercher une image » répond « Les banques
  d'images libres sont très demandées : réessayez dans une minute » au lieu de « aucune image ». Une mise à l'écart
  de la source pendant 20 à 120 s a été essayée puis retirée : mesurée, elle perdait des images que l'appel suivant
  aurait eues.
- Recherches **en parallèle** (3 à la fois) : une requête partagée par la couverture et une diapositive ne cherche
  qu'une fois.
- Format du deck : l'exemple montre une diapositive illustrée (`::: image`) ; s'il manque des chiffres, « écris
  quand même la présentation, avec « à compléter » » (avant : « Fais une présentation sur notre boulangerie » →
  refus « je n'ai pas accès à vos chiffres », vu en direct ; après : 7 diapositives).

**Graphiques** (« graphique + message clé », natif et éditable dans le .pptx) :
- **Aucun chiffre inventé** (`figures.check`) : un graphique n'est gardé que si chacune de ses valeurs est dans la
  demande, les messages précédents, les résultats d'outils du tour (statistiques, données ouvertes, moteur de
  données, page lue) ou le deck lui-même (« fais un graphique de ce tableau ») ; une différence de deux chiffres
  donnés compte (calcul, pas invention). Sinon il devient l'encadré « Graphique à compléter : donnez vos chiffres
  (2023, 2024, 2025) et Bird le trace » (`need: figures`), le chat le dit, et la puce « Donner les chiffres »
  **écrit le début du message** dans la zone de saisie (puce `fill`) au lieu d'envoyer « ajoute des chiffres ».
  Mesuré avant : le pitch deck de la livraison à vélo traçait « 2023 : 12 %, 2024 : 15 %, 2025 : 18 % », chiffres
  que personne n'avait donnés.
- Les chiffres des **tableaux et tuiles** sans source deviennent « à compléter » (`figures.cells`) : vu en direct,
  « ajoute une diapositive avec un graphique de nos ventes » donnait un tableau de 20 montants inventés ; il garde
  sa forme, pas les montants.
- « Voici les chiffres du graphique : pain 45 %, viennoiseries 30 %, pâtisseries 25 % » : tracé **sans appel au
  modèle** (`figures.fill_ops`, les chiffres tels que tapés) à la place de l'encadré, ou du tableau dont les lignes
  sont nommées ; une part en % qui fait 100 devient un camembert. Sans le mot « graphique », les cases « à
  compléter » du tableau reçoivent les chiffres. Le modèle ne recopie plus le plan (« [b1] Introduction… ») dans
  une diapositive ajoutée (retiré, `patch._drop_outline_copies`). La puce « Une diapo de chiffres clés » (qui
  appelait des chiffres inventés) est remplacée par « Un graphique de vos chiffres » (`fill`).

**Avant / après** (Bird S 4B en direct ; Mode Agent désactivé comme décidé aujourd'hui ; images regardées une à une) :

| Mesure | avant | après |
|---|---|---|
| Production, 8 decks : images trouvées / demandées | **0 / 10** | (pas encore déployé ici) |
| Local, 8 decks : images trouvées / demandées | 8 / 12 | 5 / 8 |
| Local, 8 decks : images hors sujet affichées (à l'œil) | 3 sur 8 | 2 sur 5 (rue de New York pour « cyclists », pulsar pour un graphique, corrigé depuis) |
| 20 requêtes fixes, alternées (`image_ab`) : trouvées | 20 | 14 |
| 20 requêtes fixes : **justes à l'œil** / **fausses affichées** | 13 / **7** | 12 / **2** |
| 20 requêtes fixes : secondes par requête (moyenne) | 0,7 | 2,6 (en parallèle dans un deck) |
| Licence + crédit présents, image qui s'ouvre, image dans le .pptx | 8 / 8 / 8 sur 8 | 5 / 5 / 5 sur 5 |
| Graphiques des decks aux chiffres donnés (6 et 7) | 2 sur 2 (7 valeurs sur 7 sourcées) ; production : 1 sur 2 | 2 sur 2 (8 sur 8, l'objectif 2026 compris), 2 graphiques natifs dans le .pptx |
| Graphiques aux chiffres inventés affichés (8 decks) | local 1 (deck 2 : 12 / 15 / 18 %) ; production 1 (deck 2 : 45 / 20) | 0 (encadré « à compléter » si le modèle en écrit un) |
| « Fais une présentation sur notre boulangerie » | refus, pas de deck | 7 diapositives |

Lecture honnête : la recherche affiche nettement moins d'images fausses (7 → 2 sur 20) pour une image juste de moins
(13 → 12) ; le nombre d'images trouvées dépend surtout des limites de débit du moment (le bac à sable est limité
par Wikimedia pendant toute la mesure, Openverse par intermittence). En production, le chiffre de départ est 0 sur
10 : à remesurer dès le déploiement (`scripts/deck_media_eval.py --url https://bird-s.vercel.app`). Une clé
Openverse (`client_credentials`) relèverait la limite : non branchée (aucune clé ici).

## 10. Documents type Word (branche `canvas-docs`)

Un document se lit et s'édite comme une page Word, au niveau des diapositives :

- **Un livrable, une carte.** « Rédige un document Word : … », « une lettre en Word », « le compte rendu en docx »
  ouvrent le canevas (`intents.ask` : un format Word nommé n'envoie plus vers l'outil entraîné, sauf avec un autre
  format, une question, un mail, une traduction, un résumé). Si le modèle appelle quand même `make_document` (tour
  ordinaire), le document est adopté, le canevas s'ouvre aussitôt (`ref.open`), sa carte remplace la carte fichier
  (`ref.files`) et la ligne « Fichier : x.docx » est retirée du texte (`canvas_web.strip_file_lines`). Une
  présentation ou un tableur adoptés gardent leur carte fichier. La carte du chat montre la première page, le modèle,
  « Version N », et télécharge .docx / PDF sur place ; la carte la plus récente suit les éditions faites depuis.
- **Modèles** (`birds/canvas/templates.py`) : note de cadrage, compte rendu, rapport, proposition commerciale,
  procédure, lettre. **Le modèle choisit** (`template:` dans l'en-tête du format, lu avec indulgence : accents,
  alias, anglais) ; un indice tiré des mots de la personne ne sert que s'il n'a rien écrit (`template_by` = `model`
  | `hint` | `default`). Le code vérifie la structure (sections attendues trouvées, manquantes, taux sur les
  obligatoires) et n'ajoute **jamais** de contenu : une section manquante devient une puce de suite (« Ajouter
  « Périmètre » »), placée à son rang du modèle quand on l'ajoute (`patch._template_place`). Un auteur ou un
  destinataire n'est gardé que si la demande le nomme ; la date est fixée une fois (aperçu et fichier identiques).
- **Page** (`canvas-doc.js`) : pages A4 (210 × 297, unités de conteneur, mise en page refaite à chaque changement et
  au redimensionnement ; une feuille continue sous 520 px), couverture (nom du modèle, titre, sous-titre, date,
  auteur), sommaire avec numéros de page, titres numérotés « 1. » / « 1.1 » (H1-H3), encadrés « À retenir » /
  « Attention » / « Info », tableaux à en-tête, figures numérotées « Figure n – légende · Source : crédit · licence »
  (images par le même chemin serveur Commons, ou graphiques du moteur), notes `[^1]` en exposant puis listées à la fin,
  en-tête courant et « n / N ». Lettre : expéditeur, date, destinataire, « Objet : », corps sans titres.
- **Édition** : texte sur place par bloc ; par section : monter, descendre, dupliquer, supprimer, **Insérer** (image,
  tableau, trois encadrés, sous-titre), **✦ Retravailler** (plus concis / clair / formel / développer, ou une
  consigne) : le modèle écrit **deux variantes** (`turn.VARIANTS`, `parse_variants`), montrées côte à côte à la place
  de la section (`canvas` phase `variants`) ; « Choisir » crée la version suivante, « Garder l'actuelle » ne change
  rien ; une seule variante lisible est appliquée comme un « Demander à Bird ». Historique : chaque version porte son
  libellé et son heure ; une version ancienne affichée propose « Restaurer » (nouvelle version, rien n'est perdu).
- **Export fidèle** (`birds/canvas/docx_out.py`) : le .docx suit le même plan que la page (`outline`) — couverture,
  sommaire Word (champ TOC), titres numérotés aux mêmes niveaux, encadrés, tableaux, figures à légende numérotée
  (champ SEQ) avec crédit et licence, notes, numéros de page. Vérifié : `tests/test_canvas_docs.py` (python-docx,
  rendu LibreOffice), et l'e2e télécharge le .docx depuis la carte, `scripts/check_docx.py` compare ses titres à ceux
  de l'aperçu (identiques) et le rend en PNG.
- **Continuité** : chaque tour qui fait évoluer le document dit « Version N du document », la carte montre la nouvelle
  version, et 2-3 puces viennent de la structure (`templates.next_steps` : section manquante, tableau d'actions /
  de risques / de tarifs, image, plus concis ; lettre : plus formelle, plus courte).

### Mesures

| | avant (base 8d439bd) | après |
| --- | --- | --- |
| pytest | 2 432 réussis, 1 ignoré | 2 467 réussis, 1 ignoré (+35 documents) |
| node --test tests/js | 93 | 96 (+3 plan de page) |
| banc de déclenchement | 2 094/2 094 | 2 094/2 094 |
| e2e `canvas_docs.spec.js` (démo, 1280 et 360 px, clair et sombre) | — | 4 parcours (36 vérifications au bureau, 32 au téléphone), 0 erreur de page, 0 requête tierce ; `canvas.spec.js` inchangé : réussi |
| poids statique de l'app | 1 380 878 o (398 Ko gzip) | 1 427 833 o (+47 Ko brut, +12 Ko gzip) |
| .docx téléchargé vs aperçu (`check_docx.py`) | — | titres identiques (8/8), tableau, figure, notes, n° de page |

**En réel, avant** (production, base, 28/11/2026, `scripts/canvas_docs_live.js`, 6 demandes fixes, une conversation
chacune ; complétude = sections obligatoires du modèle attendu présentes, calculée après coup par `templates.check`) :

| Demande | Chemin | Cartes | Canevas ouvert | « Fichier : » | Sections | Complétude | Temps |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Note de cadrage (Word) | `make_document` adopté | 2 (canevas + fichier) | non | oui | 4 | 0,8 (Contexte manque) | 14 s |
| Compte rendu | canevas | 1 | oui | non | 4 | 1,0 | 7 s |
| Rapport | canevas | 1 | oui | non | 5 | 0,33 | 14 s |
| Proposition commerciale | canevas | 1 | oui | non | 5 | 0,75 | 18 s |
| Procédure | `make_document` **échoué** : contenu recopié dans le chat | 0 | non | non | 0 | 0 | 34 s |
| Lettre (Word) | `make_document` adopté | 2 | non | non | 5 | 1,0 | 12 s |

Base : 3/6 en une carte, 3/6 canevas ouvert, modèle choisi 0/6 (aucun), réparations non comptées.

**En réel, après : non mesuré.** Le serveur local de cette branche n'a pas d'accès à l'endpoint du modèle dans cette
session (pas de clé dans l'environnement) ; la mesure se relance telle quelle sur un serveur `--from-env` :
`node scripts/canvas_docs_live.js http://127.0.0.1:<port>/ out/docs-after` (≤ 6 générations + 3 pour ✦). À
relever : modèle choisi par le modèle (`template_by`), complétude, réparations (`ref.repairs`), temps ; puis ✦ sur une
section (deux variantes lues ou non). Hors ligne, le chemin entraîné réel de la note de cadrage (4 sections
`make_document`) donne désormais une seule carte, le canevas ouvert, sans ligne « Fichier » (test
`test_an_adopted_word_document_opens_in_the_canvas_with_one_card`).

## 11. Présentations et documents progressifs (`birds/canvas/progressive.py`)

Une nouvelle présentation ou un nouveau document (pas un fichier joint ; `BIRD_CANVAS_PROGRESSIVE=0` revient à la
génération unique) se fait en quatre temps, avant l'équipe du Mode Agent (Mode Agent « activé » garde l'équipe) :

1. **Plan** — une génération en sortie structurée, validée champ par champ (`parse_outline`) : public, message, 6 à
   12 diapositives (4 à 8 sections), et pour chacune son visuel : `image` (une requête concrète en anglais),
   `chart` (seulement une vraie série : `get_statistics`, ou les chiffres de l'utilisateur), `diagram` (dessiné en
   étapes), `kpi`, `table`, `timeline`, `compare`, `cards`, `quote` ou `none`. Garde-fous (veto, jamais des choix) :
   une photo « de statistiques » devient un graphique ou des chiffres clés ; une requête sans chose à montrer
   (« uniquement une photo », écho des consignes) ou déjà prise par une autre diapositive ne crée pas d'emplacement
   photo ; une série que ni la demande ni la diapositive ne nomme (la population dans une présentation sur la
   mobilité douce) est remplacée par des faits du web ; une série n'est tracée qu'une fois.
2. **Collecte en parallèle** (5 fils, 38 s au plus) — images libres de droits (Openverse, Commons, Pexels si une clé
   est configurée ; licence vérifiée, cache, jamais deux fois le même fichier), séries officielles, recherche web
   et lecture d'une page par diapositive qui demande des faits (un résultat qui ne partage aucun mot avec la
   diapositive n'est pas lu). Filet de secours : un plan qui ne demande aucun fait reçoit des faits du web pour ses
   premières sections (Faucon, Chouette, Albatros ; Colibri et Hirondelle : plan, images et rédaction seulement).
3. **Rédaction** — une génération par diapositive ou section, avec SES faits et son visuel : 4 à 6 points précis
   (un fait, un nom, une date, un chiffre des faits) par diapositive, 2 à 4 paragraphes par section. Chaque
   diapositive apparaît dans le canevas dès qu'elle est écrite ; les lignes de progression disent « Plan :
   7 diapositives », « 1 graphique à partir de Eurostat », « 3 images trouvées », « Rédaction : 4/7 ».
4. **Vérification** (code) — tout chiffre absent de la demande, des faits lus et des séries est retiré ; la notation
   du modèle (« [Graphique des données officielles : …] », « <étape> ») et un point qui ne fait qu'annoncer le
   graphique sont retirés ; une liste qui répète la frise de la même diapositive part ; sources numérotées dans
   l'ordre de lecture (diapositive « Sources » avec leurs adresses, notes de bas de page dans un document).

Une image introuvable devient un **emplacement conçu** (`missing`) : « Image à ajouter », les mots de la recherche
nettoyés, « Chercher une image » et « Importer une image » ; il n'est pas recherché une seconde fois dans le tour, et
la puce « Compléter les N images manquantes » relance la recherche (modification directe, `patch.direct_ops`). La
génération unique applique la même règle aux photos (`turn.photo_queries`). Exports : photos et graphiques natifs
dans le .pptx (la photo de couverture est désormais envoyée par le navigateur), figures dans le .docx (test
`test_exports_carry_the_pictures_and_a_native_chart` ; un .pptx de production relu : photo et crédit présents).

### Mesure en direct, 28/11/2026 (production, Faucon, 6 demandes fixes, 27 générations au total)

`scripts/progressive_eval.py` (par défaut les demandes 1, 2, 3 : présentations — chômage pour des lycéens, mobilité
douce pour un conseil municipal, pitch de livraison de repas à vélo ; 6, 7, 8 : documents — population des grandes
villes, note sur le vélo en ville, cadrage d'un jardin partagé). Tout est compté sur les événements, rien n'est
jugé à la main : visuels = diapositives ou sections avec une image affichée, un graphique, des chiffres clés, un
tableau, une frise… ; « précis » = part des phrases et des points portant un chiffre ou un nom propre ; fuites =
notation du modèle visible ou requête d'image « statistique ». Fichiers : `docs/measures/progressive-2026-11-28-*.json`.

| Version | Canevas | Visuels | Images trouvées | Emplacements | Graphiques réels | Citations avec adresse | Précis | Mots / bloc | Fuites | 1re diapo | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Avant (une génération) | 5/6 | 13/39 | 1/6 | 3 | 0/1 | 0/0 | 0,22 | 49 | 0 | 17,7 s | 40,4 s |
| Après 4e9342f | 6/6 | 19/44 | 5/7 | 1 | 4/4 | 1/3 | 0,36 | 80 | 2 | 15,0 s | 23,1 s |
| Après 00b3309 | 6/6 | 17/43 | 1/11 | 8 | 5/5 | 10/10 | 0,39 | 80 | 0 | 18,9 s | 30,3 s |
| Après 486b330 | 6/6 | 23/45 | 3/8 | 4 | 5/5 | 16/16 | 0,32 | 88 | 0 | 22,6 s | 32,6 s |
| **Après 5fb370f** | **6/6** | 18/41 | 3/8 | 4 | **3/3** | **16/16** | **0,38** | **83** | **0** | **16,8 s** | **26,4 s** |

Lecture :
- **Avant**, la présentation sur le chômage n'était pas faite (réponse dans le chat), aucun graphique ne venait de
  données réelles, aucune citation n'avait d'adresse, 1 image sur 6 demandées.
- **Images** : leur nombre varie d'un passage à l'autre avec les mêmes demandes (5/7, 1/11, 3/8, 3/8) et des
  requêtes correctes (« Paris skyline », « cyclist delivering food to office » non trouvées) : les banques libres
  limitent les adresses partagées de l'hébergeur (429). Les 5 images de 4e9342f comptaient trois fois la même photo
  d'un studio pour « uniquement » (corrigé dans 00b3309 : écho, doublon). Sur 5fb370f, lues une à une : « City
  Mobility Center », un jardin partagé aux Clayes-sous-Bois (pertinentes), « Bois de Boulogne with People Walking »
  de Van Gogh pour « people walking on a city street » (littérale).
- **Graphiques** : tous tracés depuis Eurostat, la Banque mondiale ou l'Insee ; 486b330 traçait chômage, croissance
  et créations d'entreprises dans la présentation chômage (pertinents).
- **Contenu** : deux fois plus de texte utile par bloc, toutes les citations ont leur source ; les chiffres non
  sourcés sont retirés (15 sur le pitch, où le modèle invente un marché). La note sur le vélo (demande 7) reste
  générale (0,13 de phrases précises) malgré 4 sources lues : le modèle reformule plus qu'il ne cite.
- **Temps** : 26 s en moyenne au lieu de 40 s (les diapositives s'écrivent en parallèle), première diapositive
  visible en 17 s.

Pas vérifié ici : la recherche d'images depuis cet environnement (le garde d'egress se connecte sans le proxy du
bac à sable : `ConnectError`) ; la capture d'un emplacement d'image en production (aucun dans la présentation
capturée) a été faite sur le serveur de démonstration en simulant l'échec (bureau clair, téléphone sombre).
Configuration : `BIRD_PEXELS_API_KEY` (clé gratuite, pexels.com/api) donne une source d'images à quota par clé,
non limitée par l'adresse partagée ; c'est le levier principal pour que les emplacements se remplissent.
