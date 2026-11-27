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

Les réponses sont **écrites à l'avance** (`DemoBackend`) et l'interface l'affiche partout (« démo »). Les quatre exemples de l'écran d'accueil déclenchent chacun un scénario : mail (page signalée comme suspecte, puis demande d'autorisation), compte rendu (tableau), diapositives (fichier .pptx téléchargeable), recherche web (étapes, sources citées). Trois scénarios de test, déclenchés seulement par une phrase explicite (un simple « erreur » ou « réveil » dans une vraie demande ne les déclenche pas) : « simule une erreur » simule une panne ; « test réveil » simule l'attente d'un endpoint en veille ; « test xss » renvoie du contenu hostile pour vérifier le rendu Markdown. Un format nommé (pptx, diapo, xlsx, tableur, docx) l'emporte sur le sujet de la demande.

Démo graphiques et images : « Fais un graphique de la part des demandes » (barres), « Trace la courbe des demandes par mois » (courbe), « Fais un camembert de la part des demandes » (camembert) ; « Cherche la consommation des petits modèles » montre une image de démonstration (`static/demo/`), marquée comme telle.

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
| Énergie (Wh)                          | **Mesurée** (`nvidia-smi`, GPU seul, modèle sur la même machine : `--local` ou `--measure-gpu`) ; sinon **estimée** par votre étalonnage (`BIRD_WH_PER_1K_TOKENS`) ; sinon **estimée d'après les tokens** lus et écrits, avec des valeurs par token tirées de mesures publiées (voir ci-dessous). Toujours étiquetée. |
| Premier mot                           | Temps entre l'envoi au modèle et son premier token, mesuré par le serveur Bird (hors réveil de l'endpoint). |
| Émissions (g CO₂e)                    | Énergie × intensité carbone du réseau : celle que **vous** déclarez avec `--grid-intensity` / `BIRD_GRID_INTENSITY` (g CO₂e/kWh), sinon France (RTE 2025), au choix du lecteur France / Europe / Monde dans le panneau Empreinte (sources ci-dessous). Sans réseau déclaré, le panneau le formule comme une hypothèse (« Émissions si l'électricité vient du réseau : … ») et dit que l'opérateur ne l'a pas déclaré ; « Électricité du réseau » seul est réservé au réseau de l'opérateur. Toujours étiquetées « estimé ». |

## L'estimation d'énergie d'un modèle distant

Sur Vercel il n'y a pas de GPU, et celui de l'Inference Endpoint (vLLM, 1 × NVIDIA L4) ne se lit pas : pas d'accès à `nvidia-smi`, et le `/metrics` de vLLM ne publie **aucune** métrique de puissance (vérifié sur l'endpoint réel le 22/11/2026 : compteurs de tokens, de cache de préfixe, de latence, de FLOP estimés, mais ni watts ni joules). D'où une estimation, toujours affichée quand un vrai modèle répond, et toujours étiquetée « estimé d'après les tokens » :

`énergie ≈ tokens lus non cachés / 1 000 × 0,006 Wh + tokens écrits / 1 000 × 0,10 Wh`

- **Pourquoi les tokens** : écrire un token (décodage) relit les ~8 Go de poids du modèle une fois pour tout le lot de requêtes servies ensemble ; lire un token (préremplissage) est du calcul pur, environ 17 fois moins cher par token. Le coût d'une réponse suit donc surtout ses tokens écrits.
- **D'où viennent les valeurs** (détail et calcul en tête de `birds/web/settings.py`) : mesures publiées de vLLM (ML.ENERGY Benchmark, <https://arxiv.org/html/2505.06371v2> : Llama 3.1 8B, 0,057 J par token écrit et 0,017 J par token lu sur H100, GPU seul ; <https://arxiv.org/html/2601.22076v2> : le regroupement divise l'énergie par token par 3 à 5), ramenées à un modèle dense de 4 milliards de paramètres en bf16 sur une L4 (72 W, 300 Go/s) à charge modeste (8 à 16 requêtes simultanées) : 0,2 J par token écrit, 0,012 J par token lu, GPU seul. **Cette concurrence est une hypothèse, non mesurée** (la métrique vLLM `num_requests_running` de `/metrics` la donnerait) ; l'interface la nomme (« une dizaine de requêtes à la fois »). Un serveur dédié peu sollicité, qui ne sert qu'une requête à la fois, tire 50 à 70 W pendant ~40 s pour 1 000 tokens, soit 2 à 2,9 J par token : près de la borne haute, environ 10 fois la valeur centrale.
- **Périmètre** : ces valeurs GPU sont multipliées par **1,72**, le rapport mesuré par Google entre le service complet (machine hôte, capacité au repos, PUE 1,09) et les accélérateurs actifs (<https://arxiv.org/html/2508.15734v1>). L'estimation a donc un périmètre comparable à celui de la référence (0,24 Wh par requête texte médiane, même source), sans être identique : ce facteur vient du parc de Google, bien chargé (10 % de machines au repos, PUE 1,09), et ne compte pas le temps de veille ni les réveils de ce serveur L4 dédié, le plus souvent inactif. L'interface le dit.
- **Contrôle indépendant** : Jegham et al. (<https://arxiv.org/html/2505.09598v5>, tableau 4) estiment Llama 3.1 8B à ~0,17 Wh pour 1 000 tokens écrits et ~0,018 Wh pour 1 000 tokens lus, service complet ; divisé par deux pour 4B : 0,09 et 0,009.
- **Fourchette** (affichée dans le détail), au même périmètre × 1,72 que la valeur centrale : 0,036 Wh pour 1 000 tokens écrits sur une L4 bien chargée (~64 requêtes simultanées), jusqu'à 1,38 Wh si la requête occupe seule la carte à pleine puissance (72 W × 40 s = 0,8 Wh GPU seul). Tokens lus : 0,004 à 0,0143 Wh pour 1 000.
- **Cache de préfixe** : les tokens du prompt servis par le cache de vLLM (`cached_tokens`, avec `--enable-prompt-tokens-details`) ne sont pas recalculés et ne sont pas comptés.
- **Mode Agent** : les tokens de tous les appels s'additionnent.
- **Réglages** : `BIRD_WH_PER_1K_OUT`, `BIRD_WH_PER_1K_IN` (la fourchette suit) ; `BIRD_ENERGY_METHOD=off` masque l'estimation.
- **Priorités** : mesure `nvidia-smi` > étalonnage explicite (`BIRD_WH_PER_1K_TOKENS` + `BIRD_CALIBRATION_SOURCE`) > estimation d'après les tokens.
- **Ancienne méthode, sur demande seulement** : `BIRD_ENERGY_METHOD=power_time` rétablit « puissance nominale du GPU (`BIRD_GPU_WATTS`, 72 W) × durée du flux HTTP × `BIRD_PUE` ». Elle comptait la latence réseau, l'attente et le temps jusqu'au premier token comme du calcul, et attribuait toute la carte à une seule requête alors que vLLM en sert plusieurs à la fois : jusqu'à 5 à 15 fois trop haut quand le serveur regroupe les requêtes (0,40 Wh au lieu de ~0,06 Wh pour 1 500 tokens lus et 500 écrits en 20 s) ; environ 1,5 fois quand la carte ne sert qu'une requête (elle tire moins que sa puissance nominale, et le premier token arrive en ~0,6 s sur ~10 s).
- **CO₂** : le champ `co2_g` du flux reste rempli seulement si `BIRD_GRID_INTENSITY` est fixée ; le panneau Empreinte calcule les émissions dans le navigateur avec le réseau choisi (par défaut celui de l'opérateur, sinon la France), sourcé.
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

## Graphiques

Quand on demande un graphique (« fais un graphique… », « trace la courbe… », « un camembert de… »), Bird appelle `make_chart` et le graphique s'affiche sous la réponse : barres (horizontales au-delà de 8 libellés ou pour des libellés longs), courbe ou camembert (anneau). Il est dessiné en SVG par le navigateur (`static/chart.js`, sans bibliothèque) ; rien n'est rendu côté serveur. Il est dessiné à la largeur réelle de la carte (un `ResizeObserver` le redessine quand elle change), donc le texte reste à 12 px sur téléphone comme sur ordinateur ; camembert étroit : pourcentages autour de l'anneau, noms dans la légende.

- **Lire** : survol ou flèches du clavier (le graphique est un seul arrêt de tabulation ; Début/Fin, Échap) ; la bulle est annoncée par les lecteurs d'écran. Légende dès 2 séries (camembert : toujours), et « Voir les données » ouvre le tableau.
- **Exporter** : « Télécharger PNG » (canevas, 1 280 px de large au moins, toujours en thème clair, avec le titre, la légende, la ligne d'origine des chiffres — dont « non vérifiés » — et la remise en forme éventuelle), « Copier les données (CSV) » (`;` et virgule décimale en français, `,` en anglais, protégé contre l'injection de formules), « Exporter .xlsx » (le générateur `make_sheet` existant, par `POST /api/tool`).
- **Honnêteté** : la légende dit d'où viennent les chiffres (votre message, le fichier joint, le web) ; des chiffres fournis par Bird lui-même portent l'étiquette « Chiffres fournis par Bird, non vérifiés ». Une remise en forme (ligne Total retirée, petites parts regroupées en « Autres ») est écrite sous le graphique.
- **Couleurs** : 6 teintes dans un ordre fixe (jetons `--series-1…6`, clair et sombre), vérifiées avec le script de palette dataviz sur les surfaces de Bird ; trois teintes claires sont sous 3:1 de contraste, compensé par la légende et le tableau toujours présents. Couleurs forcées : marques en `CanvasText`.

## Images du web

Une demande d'images (« montre-moi une photo de X », « à quoi ressemble X ») en montre jusqu'à 4, dont le titre ou l'adresse de la page nomme X (voir docs/HARNESS.md, « Images demandées »). Une réponse qui a utilisé le web peut montrer jusqu'à 3 images, chacune sous un cadre 4:3 fixe (rien ne bouge au chargement), créditée du titre de la page et de son domaine (et du numéro de source [n] quand la page est citée), cliquable vers la page source. La mention « Images issues des pages consultées, non créées par Bird » les accompagne. Aucune image si aucune n'est pertinente (le titre de la page doit partager un mot avec la réponse et la demande), ni pour une réponse sans web.

**Vie privée** : le navigateur ne contacte que l'application. Les images passent par `GET /api/img?u=&e=&s=` : URL signée par le serveur (7 jours, `BIRD_IMAGE_TTL`), garde de sortie réseau à chaque redirection, aucun cookie ni en-tête du navigateur transmis, 2 Mo au plus, PNG/JPEG/WebP/GIF vérifiés sur les octets, réencodage WebP 640 px, limite propre (`BIRD_IMG_RATE_LIMIT`, 60/min). Codes d'erreur : 400 `bad_request`, 403 `bad_signature` / `cross_origin` / `blocked`, 410 `expired`, 413 `too_large`, 415 `image_type`, 422 `image_invalid` / `image_too_small`, 429 `rate_limited`, 502 `upstream` (enveloppe habituelle `{"detail": {"code", "message"}}`). Seule route `/api/` mise en cache (`public, max-age=3600`). Une image qui ne se charge pas (lien expiré après 7 jours, erreur en amont) est retirée ; la section disparaît s'il n'en reste aucune. Sur téléphone, les vignettes forment une seule rangée qui défile horizontalement.

**Ce qu'il ne fait pas** : il ne vérifie pas les licences au-delà du `pilicense=free` de Wikipédia ; une `og:image` peut être hors sujet ou promotionnelle ; une image n'est jamais présentée comme faite par Bird.

## Autres aides

- **Outils disponibles** (Réglages) : la liste des outils actifs sur ce déploiement, ceux qui sont éteints et pourquoi, et le moteur de recherche qui répond.
- **Exporter une réponse** en `.docx` (titres, listes et tableaux du Markdown conservés, généré côté serveur sans appel au modèle) ou en `.md`.
- **Créer le fichier** : quand une étape `make_*` échoue, un encadré propose de la refaire avec les mêmes arguments (réparés), sans relancer le modèle (`POST /api/tool`).
- **Aperçus** : diapositives rendues en cartes (même plan que le .pptx), document en page, premières lignes du tableur.
- **Progression** : la ligne d'état dit ce que fait Bird, avec le temps écoulé, le moteur de recherche interrogé, et l'attente de réveil de l'endpoint.
- **Petits téléphones** : en écrivant, les notes sous le compositeur s'effacent (classe `.dock.is-typing`, posée en JS) ; elles ne reviennent qu'après le clic d'un toucher dans la conversation, pour que le dock ne grandisse pas sous le doigt (iPhone SE 320/375 × 568 : « Réessayer », « Revenir au mode simple » et le pli de l'équipe étaient perdus). Test : `node scripts/agent_ui_smoke.js smallTouch`.

## Le panneau Empreinte (footprint.js) : émissions, eau, carte graphique, équivalences

Le reçu d'une réponse reste une ligne discrète ; ouvert, il montre l'impact de la réponse (module `static/footprint.js`, données et calculs purs dans `static/footprint-data.js`, textes `footprint.*` dans `static/footprint-i18n.js`) :

- **Émissions** = énergie × intensité carbone du réseau choisi (France par défaut, ou celle de l'opérateur), avec la fourchette de l'estimation d'énergie ; **eau** = énergie × 0,26 mL / 0,24 Wh (seul ratio publié avec sa méthode) ; **carte graphique** : « Bird a tourné sur une carte graphique pendant X s » (temps des flux de génération, `busy_seconds`), avec une explication simple de ce qu'est un GPU. Jamais de nombre ni de modèle de carte.
- **Équivalences** calculées exactement (impact ÷ facteur), chacune avec sa source : secondes de streaming, distance en voiture thermique, recherches web, e-mails, charges de smartphone.
- **Conversation et appareil** : cumul de la conversation (petit graphique), totaux de l'appareil conservés dans `localStorage` (`bird.footprint.totals`, réponses réelles et de démo séparées, au-delà des 400 dernières réponses du registre local).
- **« Si vous aviez utilisé un grand assistant »** : même nombre de réponses × chiffre par requête, au même périmètre (service complet) ; économie = différence, avec la fourchette de Bird ; le pire cas est écrit s'il dépasse la référence.
- La page Empreinte devient un récit, « Pourquoi les petits modèles sont l'avenir » (calcul par mot, énergie et eau, une carte graphique modeste installable près d'énergies propres, mise en veille, spécialisation, conçu en France), illustrations SVG maison ; les anciens chiffres détaillés sont repliés sous « Tous les chiffres de la période » ; méthode et sources repliées en fin de page.
- Démo : `scripts/serve.py --demo --demo-energy` (ou `BIRD_DEMO_ENERGY=1`) passe les tokens écrits à l'avance dans la vraie formule d'estimation, pour voir le panneau avec des chiffres ; tout reste étiqueté « démo ». Désactivé par défaut. Test navigateur : `tests/e2e/footprint.spec.js`.

| Donnée | Valeur | Année | Source | Licence |
| --- | --- | --- | --- | --- |
| Réseau France (cycle de vie) | 29 g CO₂e/kWh (19,6 g en émissions directes) | 2025 | RTE, Bilan électrique 2025 : <https://analysesetdonnees.rte-france.com/en/annual-review-2025/keyfindings> | citation avec la source |
| Réseau Union européenne | 213 g CO₂e/kWh | 2024 | Ember, European Electricity Review 2025 : <https://ember-energy.org/latest-insights/european-electricity-review-2025/five-years-of-progress/> | CC BY 4.0 |
| Réseau monde | 473 g CO₂e/kWh | 2024 | Ember, Global Electricity Review 2025 : <https://ember-energy.org/latest-insights/global-electricity-review-2025/global-electricity-trends/> | CC BY 4.0 |
| Eau par Wh | 0,26 mL pour 0,24 Wh (1,08 mL/Wh) | 2025 | Google, *Measuring the environmental impact of AI inference* : <https://arxiv.org/abs/2508.15734> | citation avec la source |
| Grand assistant, méthode publiée | 0,24 Wh par requête texte médiane | août 2025 | <https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference> | citation |
| Grand assistant, sans méthode publiée | 0,34 Wh par requête moyenne | juin 2025 | <https://blog.samaltman.com/the-gentle-singularity> | citation |
| Streaming vidéo, 1 h | 64 g CO₂e | 2026 | ADEME Impact CO2 (Base Empreinte) : <https://impactco2.fr/outils/usagenumerique/streamingvideo> | ADEME, réutilisation non commerciale avec mention de la source |
| Voiture thermique, 1 km (hypothèse ADEME : moyenne, diesel ; construction comprise) | 142,3 g CO₂e | 2026 | ADEME Impact CO2 : <https://impactco2.fr/outils/transport/voiturethermique> | ADEME, réutilisation non commerciale avec mention de la source |
| Recherche sur le web | 1,23 g CO₂e | 2026 | ADEME Impact CO2 : <https://impactco2.fr/outils/usagenumerique/rechercheweb> | ADEME, réutilisation non commerciale avec mention de la source |
| E-mail | 2,46 g CO₂e | 2026 | ADEME Impact CO2 : <https://impactco2.fr/outils/usagenumerique/email> | ADEME, réutilisation non commerciale avec mention de la source |
| Charge complète de smartphone | 0,019 kWh | 2026 | US EPA, Greenhouse Gas Equivalencies Calculator : <https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator-calculations-and-references> | domaine public |

Les facteurs ADEME sont en cycle de vie (appareil, réseau, centres de données) ; ils ont été lus sur impactco2.fr (API v1) en novembre 2026. Les mentions légales d'impactco2.fr autorisent la réutilisation non commerciale et pédagogique avec mention de l'ADEME ; un usage commercial demande l'accord de l'ADEME : à vérifier avant une offre payante.

## Ce qu'il ne montre pas

- **Pas de chiffre inventé.** Sans mesure ni étalonnage, l'interface écrit « énergie non mesurée sur ce serveur », jamais zéro. Les émissions utilisent l'intensité déclarée par l'opérateur, sinon une valeur annuelle publiée et sourcée (France, Europe, Monde : tableau ci-dessus), choisie par le lecteur et toujours affichée avec sa source et son année.
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
## Résultats enrichis : cartes, lieux, entreprises, devises, météo, horloge, agenda

Sous la réponse, Bird peut afficher des fiches construites **à partir des résultats d'outils ou de vos propres mots, jamais du texte du modèle** : une coordonnée, un SIREN ou un taux inventés par le modèle ne peuvent pas arriver sur une carte ou une fiche.

| Fiche                | Déclenchée par                                                                                                                                    | Données (sans clé)                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Lieux + carte**    | « restaurants près de la gare de Lyon », « où se trouve… », « itinéraire de A à B », « compare ces 3 sites : A, B, C », une adresse postale tapée | Nominatim (OpenStreetMap), Base Adresse Nationale (Géoplateforme) pour les adresses, Photon en secours |
| **Entreprise**       | un SIREN/SIRET valide, « fiche de la société X »                                                                                                  | Annuaire des entreprises (recherche-entreprises.api.gouv.fr)                                           |
| **Conversion**       | « convertis 1 200 dollars en euros », « taux de change euro livre »                                                                               | taux de référence quotidiens de la BCE                                                                 |
| **Météo**            | « météo à Lyon demain », « il va pleuvoir à Nantes ? », « quel temps pour jeudi à Lille », « weather in London tomorrow »                         | MET Norway (Locationforecast 2.0 compact, CC BY 4.0) ; ville géocodée comme les lieux                  |
| **Horloge**          | « quelle heure est-il à New York », « décalage horaire avec Tokyo », « créneau commun Paris Montréal Singapour »                                 | aucune : calcul local (table ville → fuseau IANA, `tzdata`)                                            |
| **Événement (.ics)** | « réunion avec Paul jeudi à 14h » (un jour écrit, sinon rien)                                                                                     | vos mots ; jours fériés de calendrier.api.gouv.fr                                                      |
| **Sources**          | toute réponse sourcée                                                                                                                             | domaine, icône du site (ou monogramme), date et extrait du résultat de recherche                       |

Le harnais lit la demande (`birds/harness/intents.py`, `when.py`) ; quand il est sûr, il lance l'outil lui-même avant la première génération (étape marquée « automatique ») ; quand il hésite, il propose seulement l'outil au modèle. Les quatre outils (`find_places`, `find_company`, `convert_currency`, `get_weather`) ne sont dans le prompt que sur ces tours : un tour ordinaire garde le bloc d'outils d'entraînement, octet pour octet.

**Cartes** : `GET /api/map?t=<jeton signé>&dz=<-2..3>&s=<1|2>` assemble côté serveur les tuiles OpenStreetMap en une image WebP 640×360 (`s=2` : 1280×720 au zoom + 1, servie par `srcset` aux écrans haute densité ; le cadre ne dépasse jamais 640 px et garde le format 16/9 de l'image), attribution « © OpenStreetMap contributors » incrustée (et affichée en texte). Les repères numérotés sont dessinés par le navigateur. `GET /api/icon?d=<domaine>&s=<signature>` sert l'icône d'un site déjà cité, en PNG 32×32 (SVG refusé). Mêmes règles que `/api/img` : même origine, limiteur propre, aucun en-tête relayé, chaque requête sortante passe par le garde-fou réseau, cache LRU, erreurs JSON sans URL amont.

**Météo** : la fiche donne le lieu (ville la plus importante de ce nom), le jour, la température (actuelle, ou maximum prévu pour un autre jour), l'icône du ciel (les codes `symbol_code` de MET ramenés à 12 icônes SVG dessinées dans la page), min/max, pluie en mm (et sa probabilité quand MET la donne : le format compact ne la donne pas), vent en km/h. Rien n'est inventé quand MET ne donne pas une valeur : un jour sans aucun champ de précipitation affiche « – » (pas « 0 », et le modèle ne lit pas « pas de pluie prévue ») ; un code de ciel absent ou inconnu donne une icône neutre (cercle pointillé) et « Ciel non précisé », jamais « Nuageux » ; les deux codes mal orthographiés de la liste de MET (`lightssleetshowersandthunder`, `lightssnowshowersandthunder`) sont lus comme « light… ». Une frise de 24 h (courbe de température, barres de pluie, horaire puis toutes les 6 h au-delà de 2–3 jours) et 7 vignettes journalières. Heures du lieu quand son fuseau est sûr (ville de la table de l'horloge, pays à un seul fuseau, France métropolitaine), sinon UTC, écrit. Tout est étiqueté « prévision » ; au-delà de l'horizon de MET (~9 jours) ou pour un jour passé, l'outil le dit au modèle au lieu d'inventer. Le modèle reçoit un résumé compact et écrit 1 ou 2 phrases. Une fiche d'événement du même jour affiche une ligne météo. Conditions de MET respectées : User-Agent qui nomme l'application et un site (`BirdHarness/0.1 (+https://bird-s.vercel.app)`, jamais une personne), lat/lon à 4 décimales, cache selon `Expires` puis requête conditionnelle `If-Modified-Since` (304 : la prévision en cache est gardée), attribution « Données : MET Norway » et lien CC BY 4.0.

**Horloge** : heure locale de chaque ville (rafraîchie par le navigateur, avec sa propre base de fuseaux : aucune requête), décalage avec vous ; pour 2 à 4 fuseaux, une frise de 24 colonnes dans votre fuseau avec les heures de bureau (9 h–18 h, lundi-vendredi) de chacun, le créneau commun encadré, ou à défaut le meilleur compromis en horaires élargis (7 h–21 h, signalé), et « Copier le créneau ». Un pays à plusieurs fuseaux (États-Unis, Canada…) répond par sa capitale, et la fiche le dit.

**Vie privée** : le navigateur ne contacte aucun tiers (ni tuiles, ni icônes, ni géocodeur). Le serveur n'envoie à un fournisseur que ce que vous avez tapé avec une demande de lieu, d'entreprise ou de conversion ; **une adresse contenue dans une pièce jointe n'est jamais géocodée** : avec une pièce jointe, aucun appel automatique, et `find_places` refuse toute requête qui n'est pas écrite dans vos propres mots (`tools/places.py`, `own_words`). User-Agent générique (jamais un nom ni un e-mail). Le `.ics` est fabriqué dans le navigateur (METHOD:PUBLISH, aucun invité) : rien n'est envoyé. Pour un entrepreneur individuel, la fiche n'affiche ni adresse, ni carte, ni chiffres ; les dirigeants ne sont jamais listés (lien vers la fiche officielle).

**Politiques d'usage respectées dans le code** : Nominatim et Photon au plus 1 requête / 1,1 s pour tout le processus, résultats en cache 7 jours, au plus 4 requêtes de géocodage par réponse ; tuiles : 2 téléchargements simultanés au plus, 120 tuiles non cachées par minute pour tout le processus, en-têtes de cache respectés (1 à 7 jours), aucune pré-lecture. Un déploiement chargé doit utiliser **son propre** Nominatim / serveur de tuiles, ou un fournisseur commercial : les tuiles de l'OSMF interdisent l'usage intensif.

| Variable                                                                                   | Rôle                                                                         |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `BIRD_GEO=off`                                                                             | retire les outils de fiches, les fiches (horloge comprise) et `/api/map` (503) |
| `BIRD_TILE_URL`, `BIRD_TILE_LAYER=ign`                                                     | serveur de tuiles (défaut OSM) ; couche IGN Plan v2                          |
| `BIRD_NOMINATIM_URL`, `BIRD_PHOTON_URL`, `BIRD_BAN_URL`, `BIRD_COMPANY_URL`, `BIRD_FX_URL`, `BIRD_MET_URL` | instances des fournisseurs |
| `BIRD_HOLIDAY_ZONE`                                                                        | zone des jours fériés (défaut `metropole`)                                   |
| `BIRD_GEO_USER_AGENT`                                                                      | User-Agent générique envoyé aux fournisseurs                                 |
| `BIRD_GEO_CACHE_DIR`, `BIRD_TILE_CACHE_DIR`                                                | caches disque facultatifs (noms de fichiers = empreintes, jamais la requête) |
| `BIRD_TRUSTED_PROXIES`                                                                     | proxys devant le serveur (0 ; 1 sur Vercel) ; à 0, `X-Forwarded-For` est ignoré|

Écartés : cours de bourse, temps de trajet (distance à vol d'oiseau + lien d'itinéraire OpenStreetMap), Overpass, bibliothèques de cartes côté client (Leaflet, MapLibre), service d'icônes de Google. Le mode démo rejoue les vraies fonctions d'outils sur des réponses de fournisseurs enregistrées (`birds/web/demo_data/` ; météo de Lyon, Lille, Nantes et Londres enregistrée le 23 novembre 2026 à 07:25 UTC, rejouée à cet instant) et des cartes pré-rendues (`static/demo/`, `scripts/demo_maps.py`).
