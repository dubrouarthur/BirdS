# Interface web de Bird

Code : `birds/web/` (serveur FastAPI + frontend statique) · lancement : `scripts/serve.py` · tests : `tests/test_web.py`.

Pas d'étape de compilation, pas de CDN, pas de police distante, pas de traceur : quelques petits fichiers (`index.html`, `app.css`, `app.js` et ses modules `core.js`, `turns.js`, `views.js`, `attach.js`, `markdown.js`, `i18n.js`) servis par le serveur lui-même.

## Installer

```bash
uv pip install --python .venv/bin/python -e ".[web]"            # démo seule
uv pip install --python .venv/bin/python -e ".[web,harness]"    # avec le vrai modèle
```

## Mode démo (aucun modèle)

```bash
.venv/bin/python scripts/serve.py --demo            # puis http://127.0.0.1:8000
```

Les réponses sont **écrites à l'avance** (`DemoBackend`) et l'interface l'affiche partout (« démo »). Les quatre exemples de l'écran d'accueil déclenchent chacun un scénario : mail (page signalée comme suspecte, puis demande d'autorisation), compte rendu (tableau), diapositives (fichier .pptx téléchargeable), recherche web (étapes, sources citées). Deux scénarios de test : un message contenant « erreur » simule une panne ; « test xss » renvoie du contenu hostile pour vérifier le rendu Markdown.

## Mode réel (modèle derrière le harnais)

```bash
# modèle servi par llama.cpp, vLLM… (API compatible OpenAI, /v1/completions)
.venv/bin/python scripts/serve.py --base-url http://127.0.0.1:8080/v1 --model bird \
    --workspace ./travail --searxng http://127.0.0.1:8888

# modèle chargé dans le processus (machine à GPU)
.venv/bin/python scripts/serve.py --local Qwen/Qwen3.5-4B --adapter out/adapter --workspace ./travail
```

Options utiles : `--host`, `--port`, `--tokenizer` (mode `--base-url`), `--api-key`, `--measure-gpu`, `--wh-per-1k-tokens` et `--calibration-source`, `--grid-intensity`.

`HarnessBackend` (`birds/web/backends.py`) adapte le harnais de `birds/harness/` (voir `docs/HARNESS.md`) : la boucle de l'agent tourne dans un fil d'exécution, ses étapes, sa demande de confirmation et son bilan deviennent les événements SSE de l'API. Seuls les fichiers de `<workspace>/bird_out/` sont téléchargeables ; le journal d'audit et vos documents ne sont jamais servis. Sans `--workspace`, un dossier temporaire neuf est créé.

## Ce que montre le compteur

Sous chaque réponse, une ligne : tokens lus → écrits, durée, appels d'outils, données téléchargées, énergie, modèle, réflexion. « détail » donne, pour chaque chiffre, sa valeur, son origine et une phrase d'explication. Le bouton d'en-tête ouvre le cumul de la conversation et un petit graphique des tokens par réponse.

| Chiffre                               | D'où il vient                                                                                                                                                                                                  |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tokens lus / écrits                   | Comptés par le serveur de modèle (ou le tokenizer en mode local). En démo : calculés d'après la longueur des textes scriptés, et étiquetés « scripté ».                                                        |
| Durée                                 | Temps écoulé côté serveur pour toute la requête, outils compris.                                                                                                                                               |
| Appels d'outils, données téléchargées | Comptés par le harnais.                                                                                                                                                                                        |
| Énergie (Wh)                          | **Mesurée** (`nvidia-smi`, GPU seul, modèle sur la même machine : `--local` ou `--measure-gpu`) ; sinon **estimée** par votre étalonnage (`BIRD_WH_PER_1K_TOKENS`) ; sinon **estimée, borne haute** = puissance nominale du GPU distant × temps de génération (voir ci-dessous). Toujours étiquetée. |
| Premier mot                           | Temps entre l'envoi au modèle et son premier token, mesuré par le serveur Bird (hors réveil de l'endpoint). |
| Émissions (g CO₂e)                    | Énergie × intensité carbone que **vous** déclarez avec `--grid-intensity` (g CO₂e/kWh). Toujours étiquetées « estimé ».                                                                                        |

## L'estimation d'énergie d'un modèle distant

Sur Vercel il n'y a pas de GPU, et celui de l'Inference Endpoint (vLLM, 1 × NVIDIA L4) ne se lit pas : pas d'accès à `nvidia-smi`, et le `/metrics` de vLLM ne publie **aucune** métrique de puissance (vérifié sur l'endpoint réel le 22/11/2026 : compteurs de tokens, de cache de préfixe, de latence, de FLOP estimés, mais ni watts ni joules). D'où une estimation, toujours affichée quand un vrai modèle répond, et toujours étiquetée « estimation, borne haute » :

`énergie ≈ puissance nominale du GPU × temps pendant lequel nos générations l'ont occupé × PUE`

- **Puissance** : `BIRD_GPU_WATTS`, par défaut **72 W**, puissance thermique maximale (TDP) de la NVIDIA L4 d'après la fiche de NVIDIA (<https://www.nvidia.com/en-us/data-center/l4/>, ligne « Max thermal design power (TDP) : 72W »).
- **Temps** : pour chaque génération, du début de la tentative réussie (attente de réveil exclue) au dernier token reçu, soit temps jusqu'au premier token + durée du flux. Il inclut la latence réseau : c'est une borne haute du temps de calcul.
- **PUE** : `BIRD_PUE`, par défaut 1,0, c'est-à-dire **GPU seul** (ni processeur, ni refroidissement, ni réseau) ; l'interface le dit.
- **Pourquoi « borne haute »** : la carte tourne rarement à pleine puissance pendant le décodage d'un petit modèle, et vLLM regroupe les requêtes simultanées sur le même GPU. La consommation réelle attribuable à une réponse est en dessous.
- **Priorités** : mesure `nvidia-smi` > étalonnage explicite (`BIRD_WH_PER_1K_TOKENS` + `BIRD_CALIBRATION_SOURCE`) > puissance × temps. `BIRD_GPU_WATTS=0` désactive l'estimation.
- **CO₂** : seulement si `BIRD_GRID_INTENSITY` est fixée.
- **Repères mesurés chez nous** (lots de calcul, **pas** des requêtes interactives isolées) : 0,36 Wh pour 1 000 tokens générés sur 1 × A10G (1 369 réponses en lot, `nvidia-smi`, GPU seul) ; entraînement : 1,8 kWh (GPU seul).

## Le compte rendu « Empreinte » : ce que Bird économise

La vue Empreinte (bouton en haut à droite) cumule la conversation ou tout l'historique local : tokens, durée, outils, données, énergie (mesurée / estimée / non disponible), CO₂ si configuré, graphique par réponse avec son tableau, répartition avec et sans réflexion, avec et sans outils. Elle ajoute une section **« Ce que Bird économise »**, avec deux comparaisons défendables et une note franche :

1. **Calcul théorique par token** : un décodeur dépense environ 2 × (paramètres actifs) opérations par token. Bird : 4 milliards. Classes de référence sans nom de marque, configurables (`BIRD_COMPARE_CLASSES`) : « grand modèle dense ~400 Md » (100 ×) et « grand modèle à experts ~40 Md actifs » (10 ×). Étiquette : « calcul théorique par token, à conditions de service égales ».
2. **Énergie par requête**, uniquement face à une référence **publiée et sourcée**. Choix par défaut, justifié : la médiane publiée par Google pour une requête texte de son assistant, **0,24 Wh** (21 août 2025), parce que c'est le seul chiffre de fournisseur qui détaille sa méthode et son périmètre complet (puces actives, machines au repos, processeur et mémoire, PUE du centre de données) : <https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference> (article technique : <https://arxiv.org/abs/2508.15734>). L'interface ne nomme pas le fournisseur mais montre le lien. `BIRD_REFERENCE_WH_PER_QUERY=off` masque la comparaison ; un autre chiffre exige aussi `BIRD_REFERENCE_LABEL` et `BIRD_REFERENCE_SOURCE`.
   Autres chiffres publics relevés (non utilisés par défaut) : OpenAI, « about 0.34 watt-hours » pour une requête moyenne (billet de Sam Altman, 10 juin 2025, sans méthode publiée : <https://blog.samaltman.com/the-gentle-singularity>) ; Epoch AI, « roughly 0.3 watt-hours » pour une requête typique à GPT-4o (estimation indépendante, 7 février 2025, hypothèses : ~500 tokens de sortie, 10 % d'utilisation d'un H100 : <https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use>).
   Les périmètres diffèrent (la référence compte tout le service, Bird le GPU seul à pleine puissance) : l'interface l'écrit sous les barres.
3. **Note franche** : un petit modèle sur un GPU dédié, souvent au repos, n'est pas automatiquement plus sobre par requête qu'un très grand modèle servi à pleine charge. Les économies viennent du calcul par token, de la mise en veille, de réponses courtes et de la réflexion désactivée par défaut ; la page montre ce que ces leviers donnent sur vos réponses (tokens écrits avec et sans réflexion, longueur moyenne).

## Pièces jointes et images

- **Documents** : texte, Markdown, CSV, JSON… (lus dans le navigateur) et **PDF, Word, Excel, PowerPoint** (envoyés en base64, 2 Mo au plus chacun, lus par `read_file` côté serveur, jamais stockés). Ils restent disponibles pour toute la conversation ; les PDF/Office ne sont pas gardés dans le navigateur après un rechargement (carte « à joindre de nouveau »).
- **Images** (PNG, JPEG, WebP ; HEIC si le navigateur sait le décoder) : bouton trombone, glisser-déposer sur la zone de saisie, coller une capture, et sur téléphone un bouton **photo** (« Prendre une photo » ouvre l'appareil avec `capture="environment"`, « Choisir une image » ouvre la galerie). Le navigateur décode l'image en respectant l'orientation EXIF, la réduit à 1 568 px de côté au plus (49 tuiles de 32 px : la vision de Qwen3.5 découpe en carrés de 16 px fusionnés par 2), la réencode en JPEG et refuse les images trop petites (< 200 000 pixels ou < 300 px de côté : sur l'endpoint réel, une image de 400 × 220 a produit une réponse entièrement inventée). Trois images par message.
- **Côté serveur**, une image passe par `/v1/chat/completions` (seule route qui transporte des images), **sans outils** : vLLM refuse le champ `tools` sans analyseur d'appels configuré. Bird lui demande une transcription fidèle (texte mot pour mot, tableaux en Markdown, « [illisible] » plutôt qu'inventer), affichée comme une étape « Lecture de l'image », puis la boucle normale répond avec ses outils sur cette transcription (« mets cette facture dans un tableur » fonctionne). Les tokens d'image comptent dans les tokens lus.
- Les images ne sont **jamais** stockées : ni sur le serveur, ni dans le `localStorage` (après un rechargement, une carte neutre « Image envoyée (non conservée) »). Elles ne sont envoyées qu'une fois ; les tours suivants n'en gardent que le nom et ce que Bird y a lu (mémo).
- CSP : `img-src 'self' blob:` — les miniatures sont des URL `blob:` créées par la page ; aucune image `data:` ni externe.

## Autres aides

- **Outils disponibles** (Réglages) : la liste des outils actifs sur ce déploiement, ceux qui sont éteints et pourquoi, et le moteur de recherche qui répond.
- **Exporter une réponse** en `.docx` (titres, listes et tableaux du Markdown conservés, généré côté serveur sans appel au modèle) ou en `.md`.
- **Créer le fichier** : quand une étape `make_*` échoue, un encadré propose de la refaire avec les mêmes arguments (réparés), sans relancer le modèle (`POST /api/tool`).
- **Aperçus** : diapositives rendues en cartes (même plan que le .pptx), document en page, premières lignes du tableur.
- **Progression** : la ligne d'état dit ce que fait Bird, avec le temps écoulé, le moteur de recherche interrogé, et l'attente de réveil de l'endpoint.

## Ce qu'il ne montre pas

- **Pas de chiffre inventé.** Sans mesure ni étalonnage, l'interface écrit « énergie non mesurée sur ce serveur », jamais zéro. Sans `--grid-intensity`, aucune émission n'est affichée : il n'y a pas de valeur « typique » dans le code.
- La mesure GPU ne compte ni le processeur, ni la mémoire, ni le refroidissement, ni le réseau, ni la fabrication du matériel. Elle couvre le GPU entier, autres processus compris.
- L'intensité carbone est une valeur fixe donnée au lancement, pas celle du réseau à l'instant de la requête.
- Pas de coût en euros, pas de tableau de bord par organisation (prévus au cadrage, non faits). La comparaison avec de grands modèles est théorique (calcul par token) ou appuyée sur un chiffre publié et sourcé, jamais sur une estimation maison.
- Le cumul ne couvre que la conversation ouverte dans l'onglet. Rien n'est stocké côté serveur ; la dernière conversation est gardée dans le `localStorage` du navigateur.

## Sécurité, en bref

- En-tête `Content-Security-Policy` strict (`default-src 'none'`, scripts et styles de la même origine uniquement, aucun code en ligne).
- Le rendu Markdown échappe tout le texte du modèle avant de produire ses propres balises ; seuls les liens `http(s)` deviennent cliquables, avec `rel="noopener noreferrer"`.
- `/files/{nom}` n'accepte qu'un nom simple (lettres, chiffres, `. _ -`) situé dans le dossier des fichiers générés.
- Une action soumise à validation ouvre une fenêtre Autoriser / Refuser ; Échap, l'arrêt ou cinq minutes sans réponse valent refus. Bird n'envoie jamais de mail : il prépare un brouillon à copier.

## Limites connues

- Pas d'authentification ni de comptes : à n'exposer que sur une machine ou un réseau de confiance.
- La réponse arrive en un bloc (les étapes, elles, s'affichent au fil de l'eau) ; « Arrêter » ferme le flux, mais une génération en cours côté modèle se termine avant que la boucle s'arrête.
- Une seule requête à la fois en mode réel.
- Le mode réel a été testé contre l'endpoint réel (vLLM, Bird S 4B) le 22/11/2026 : voir docs/HARNESS.md § 10.
- Les sources affichées sont les pages réellement lues par le harnais ; leur titre est leur adresse.
