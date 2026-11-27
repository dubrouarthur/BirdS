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

Blocs : `kpi`, `chart` (bar, line, pie), `table` (ou un tableau `| a | b |`), `timeline`, `image query="…"`, `quote`
(ou `>`), `code` (ou une clôture ` ``` `), `note` / `attention` (encadrés), `notes` (notes de l'orateur). Les
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
  Markdown dans la zone de saisie), export .xlsx et CSV.

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

- **Le vrai modèle** (endpoint en pause pendant ce travail) : le 4B suit-il le format texte, ou appelle-t-il quand même
  `make_slides` (rattrapé) ? Écrit-il des opérations `@replace` exploitables ? `scripts/canvas_eval.py` mesure les deux
  modes (défaut, et `BIRD_CANVAS_OFF=1` : chemin entraîné seul). Si le format texte rate trop, passer le canevas en
  « mode outil » (garder le bloc d'outils, adopter les arguments) est une option simple côté harnais.
- La recherche d'images Commons n'a été testée qu'avec un faux client (pas de réseau ici).
- L'impression PDF repose sur les pages nommées CSS (Chromium) ; Firefox imprime en portrait.
- L'édition sur place utilise `contenteditable="plaintext-only"` (repli sur `true` ailleurs).
