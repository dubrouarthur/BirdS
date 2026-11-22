# Déployer Bird sur Vercel

Vercel n'héberge **que l'interface et le harnais d'agent** (pas de GPU, pas de modèle). Le modèle tourne ailleurs, derrière une API compatible OpenAI (`/v1/completions`), et se branche par des variables d'environnement. Sans rien configurer, le site démarre en **mode démo** (réponses écrites à l'avance, étiquetées « démo »).

Ce guide distingue ce qui a été **vérifié** (dans la documentation, ou localement avec `vercel build`) de ce qui ne le sera **qu'au premier vrai déploiement**. Aucun déploiement réel n'a été fait depuis cet environnement.

## 1. Déployer la démo (5 minutes)

1. Sur vercel.com : **Add New… → Project**, puis importez le dépôt GitHub.
2. Réglages du projet :
   - **Root Directory** : `./` (la racine du dépôt).
   - **Application Preset** : `FastAPI` (détecté automatiquement).
   - **Build Command**, **Output Directory**, **Install Command** : laissez vides (valeurs par défaut).
   - Version de Python : rien à régler, Vercel prend 3.12 d'après `pyproject.toml`.
3. **Environment Variables** : aucune pour la démo.
4. **Deploy**.
5. Ouvrez l'adresse fournie : l'écran d'accueil s'affiche, l'en-tête indique « Bird S 4B · démo ». Cliquez un des quatre exemples : la réponse arrive mot à mot, avec ses étapes et son reçu d'empreinte. `…/api/health` doit répondre `"backend": "demo"`.

Ce que le dépôt contient pour cela :

| Fichier            | Rôle                                                                                                        |
| ------------------ | ----------------------------------------------------------------------------------------------------------- |
| `app.py`           | Point d'entrée : variable `app` (FastAPI) dans un emplacement par défaut.                                   |
| `pyproject.toml`   | `[tool.vercel] entrypoint = "app:app"` et dépendances **légères** (`[project].dependencies`).               |
| `vercel.json`      | Durée maximale de la fonction (300 s) et fichiers exclus du paquet.                                         |
| `.vercelignore`    | Liste blanche : seuls `app.py`, `birds/`, `pyproject.toml`, `requirements.txt`, `vercel.json` sont envoyés. |
| `requirements.txt` | Miroir des dépendances légères, pour d'autres hébergeurs (Vercel lit `pyproject.toml`).                     |

## 2. Variables d'environnement

À saisir dans **Settings → Environment Variables**, puis **redéployer** (une variable ne s'applique qu'aux déploiements suivants).

| Nom                                                                     | Obligatoire ?                               | Exemple                                                  | Effet                                                                                                                               |
| ----------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `BIRD_BASE_URL`                                                         | pour le vrai modèle                         | `https://xxxx.eu-west-1.aws.endpoints.huggingface.cloud` | Adresse de l'API du modèle, avec ou sans `/v1`. Absente : mode démo.                                                                |
| `BIRD_MODEL`                                                            | avec la précédente                          | `bird`                                                   | Valeur du champ `model` envoyée au serveur.                                                                                         |
| `BIRD_API_KEY`                                                          | si l'API est protégée                       | `hf_…`                                                   | Envoyée en `Authorization: Bearer …`. Jamais renvoyée au navigateur ni journalisée.                                                 |
| `BIRD_SIGNING_SECRET`                                                   | **recommandé dès qu'un modèle est branché** | 32 caractères aléatoires                                 | Signe les demandes d'autorisation. Sans elle, une clé est dérivée de `BIRD_API_KEY` (ou, en démo, de l'identifiant du déploiement). |
| `BIRD_ACCESS_CODE`                                                      | conseillé sur une adresse publique          | `un-code-a-partager`                                     | Code demandé une fois dans l'interface pour utiliser le modèle (pas la démo).                                                       |
| `BIRD_SEARXNG_URL`                                                      | non                                         | `https://searx.exemple.org`                              | Moteur SearXNG (format JSON activé). Sans lui, l'outil de recherche n'est pas proposé.                                              |
| `BIRD_ALLOW_USER_ENDPOINT`                                              | non                                         | `0` ou `1`                                               | Autorise « Mon endpoint » dans les réglages. Par défaut : oui **seulement si** `BIRD_BASE_URL` est absente.                         |
| `BIRD_ENDPOINT_ALLOWED_HOSTS`                                           | non                                         | `*.exemple.org`                                          | Hôtes acceptés pour « Mon endpoint », en plus de `*.endpoints.huggingface.cloud`.                                                   |
| `BIRD_GRID_INTENSITY`                                                   | non                                         | `56`                                                     | g CO₂e/kWh du lieu où tourne le modèle. Sans elle, aucun CO₂ n'est affiché.                                                         |
| `BIRD_WH_PER_1K_TOKENS`, `BIRD_CALIBRATION_SOURCE`                      | non                                         | `0.4`, `mesure interne du 3 mars`                        | Votre étalonnage d'énergie ; affiché comme **estimé**, avec sa source.                                                              |
| `BIRD_EQUIVALENT_LABEL`, `BIRD_EQUIVALENT_WH`, `BIRD_EQUIVALENT_SOURCE` | non                                         | `ampoule LED 10 W pendant 1 h`, `10`, `10 W × 1 h`       | Équivalence du quotidien dans la vue Empreinte. Les trois sont nécessaires.                                                         |
| `BIRD_MAX_SECONDS`                                                      | non                                         | `240`                                                    | Budget de temps de l'agent ; doit rester sous la durée maximale de la fonction.                                                     |
| `BIRD_RATE_LIMIT`                                                       | non                                         | `20`                                                     | Requêtes par minute et par adresse IP (0 : désactivé). Voir § 5.                                                                    |
| `BIRD_MODEL_LABEL`                                                      | non                                         | `Bird S 4B`                                              | Nom affiché dans l'interface.                                                                                                       |

## 3. Brancher un Inference Endpoint Hugging Face

### Ce que l'endpoint doit servir

Le **modèle Bird fusionné** (poids complets dans un dépôt Hugging Face), ou un **fichier GGUF** pour le moteur llama.cpp. **Cet export n'est pas encore fait** : aujourd'hui le projet produit un adaptateur LoRA, pas un modèle fusionné ni un GGUF. C'est une étape à part, préalable à tout ce qui suit.

L'endpoint doit exposer **`/v1/completions`** (complétion à partir d'une invite brute, avec `stream: true`) : le harnais met lui-même en forme l'invite avec le gabarit de Qwen3.5 (copie du fichier officiel dans `birds/harness/chat_template.jinja`) et lit lui-même les appels d'outils.

### Quel moteur

- **vLLM** : recommandé par la documentation de Hugging Face, qui indique que TGI est en maintenance depuis le 11/12/2025 et conseille vLLM ou SGLang à la place.
- **llama.cpp** : sélectionné automatiquement quand le dépôt contient un GGUF ; expose une API compatible OpenAI ; adapté à une version quantifiée (plus petite, moins chère).
- **Non vérifié** : la prise en charge de l'architecture Qwen3.5 par la version de vLLM ou de llama.cpp installée sur les Endpoints. Consultez la liste des modèles pris en charge par le moteur avant de créer l'endpoint ; si le modèle ne se charge pas, les journaux de l'endpoint le diront.

Taille d'instance : un modèle de 4 milliards de paramètres pèse environ 8 Go en 16 bits ; un GPU de 16 à 24 Go laisse de la marge pour le contexte. Un GGUF en 4 bits (environ 3 Go) tient sur plus petit. Ce sont des ordres de grandeur, à confirmer au premier lancement.

### Mise en veille (scale-to-zero)

La mise en veille arrête l'endpoint après une période sans requête (1 heure par défaut) : vous ne payez plus le calcul pendant ce temps, et c'est cohérent avec la promesse de sobriété. En contrepartie, la première requête réveille l'endpoint : le proxy répond **503** pendant le démarrage, qui peut prendre quelques minutes. Bird le gère : il affiche « Le modèle se réveille… », réessaie tout seul (3, 5, 8, 12 puis 15 secondes) dans la limite du temps de la fonction, puis propose de réessayer. Ce n'est jamais présenté comme une erreur de l'utilisateur. Pour les tarifs, voir la page officielle : <https://huggingface.co/docs/inference-endpoints/pricing> (aucun prix n'est repris ici).

### Les trois valeurs à saisir

| Variable        | Valeur                                                                                                                                                                                                                                          |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BIRD_BASE_URL` | L'« Endpoint URL » affichée sur la page de l'endpoint, telle quelle (`https://….endpoints.huggingface.cloud`). `/v1` est ajouté automatiquement.                                                                                                |
| `BIRD_API_KEY`  | Un jeton d'accès Hugging Face autorisé à appeler l'endpoint (endpoint « Private » : le vôtre ou celui d'un membre de l'organisation).                                                                                                           |
| `BIRD_MODEL`    | `adubrou/Bird-S-4B` (valeur par défaut si la variable est vide). Le nom que le moteur attend dans le champ `model`. **Non vérifié par moteur** : avec vLLM c'est en général le nom du dépôt servi ; llama.cpp l'ignore le plus souvent. Le bouton « Tester la connexion » des réglages dit si le nom est refusé. |

### Variante : « Mon endpoint », dans l'interface

Réglages → Modèle → « Mon endpoint » : adresse, jeton, nom du modèle, puis « Tester la connexion » (réponse en clair : joignable, jeton refusé, modèle en réveil, mauvaise route). À savoir, et l'interface le dit : le jeton est gardé dans le `localStorage` de ce navigateur et envoyé à chaque message à **notre** serveur, qui le transmet à l'endpoint sans l'enregistrer ni le journaliser. **Pour un déploiement partagé, préférez les variables d'environnement.** Cette option est désactivée par défaut dès que `BIRD_BASE_URL` est définie.

Protection contre le détournement (l'adresse saisie est appelée par notre serveur) : `https` uniquement, port par défaut, hôte dans la liste autorisée, adresses publiques uniquement, connexion épinglée sur l'adresse vérifiée, redirections refusées.

## 4. Vérifier après le branchement

1. `…/api/health` : `"backend": "completions"`, `"default_mode": "server"`.
2. Réglages → Modèle → « Tester la connexion ».
3. Une question simple, puis une demande de mail : la réponse doit s'écrire au fil de l'eau.

## 5. Limites à connaître

- **Durée** : sur l'offre Hobby, une fonction dure au plus **300 s** (valeur par défaut et maximum, avec Fluid compute). `vercel.json` demande 300 s et l'agent s'arrête de lui-même à 240 s avec un message clair. Un réveil d'endpoint plus long que cela demande de renvoyer le message.
- **Pas de disque durable** : les fichiers générés (pptx, docx, xlsx) sont envoyés au navigateur dans la réponse (3 Mo au plus par fichier) ; rien n'est conservé côté serveur. Le journal d'audit part dans les journaux Vercel (une ligne JSON par appel d'outil, secrets masqués).
- **Sans état** : une demande d'autorisation est un jeton signé valable 15 minutes, que le navigateur renvoie. Elle fonctionne quelle que soit l'instance qui répond, à condition que la clé de signature soit stable (`BIRD_SIGNING_SECRET`). Un jeton peut être rejoué pendant sa durée de vie pour la même conversation : il ne produit qu'un brouillon ou un fichier rendu au même utilisateur.
- **Limite de débit** : elle est tenue en mémoire, **par instance** ; sur du serverless c'est un garde-fou au mieux. Une vraie limite demande un stockage partagé (Vercel KV, Upstash) ou le pare-feu de Vercel.
- **Corps de requête** : 4,5 Mo au plus côté Vercel ; l'application refuse bien avant (24 000 caractères par message, 4 documents de 60 000 caractères).
- **Pas de comptes** : `BIRD_ACCESS_CODE` est un code partagé, pas une authentification.

## 6. Dépannage

| Symptôme                                                                        | Cause et remède                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `FASTAPI_ENTRYPOINT_NOT_FOUND … found potential entrypoints: tests/test_web.py` | **Erreur rencontrée au premier essai**, avant l'ajout du point d'entrée. Corrigé par `app.py` à la racine, `[tool.vercel] entrypoint = "app:app"` dans `pyproject.toml`, et `.vercelignore` qui n'envoie plus `tests/`. Si elle revient : vérifiez que ces trois fichiers sont bien sur la branche déployée. |
| Build très long, ou paquet de plusieurs centaines de Mo                         | `[project].dependencies` contient de nouveau une dépendance lourde (transformers, torch, datasets). Elles vont dans les groupes `data` / `train`.                                                                                                                                                            |
| Le site reste en démo                                                           | `BIRD_BASE_URL` absente pour cet environnement (Production / Preview), ou pas de redéploiement depuis son ajout.                                                                                                                                                                                             |
| « Le modèle se réveille » qui dure                                              | Endpoint en veille : attendez une à quelques minutes et réessayez ; vérifiez qu'il n'est pas en pause ou en échec dans la console Hugging Face.                                                                                                                                                              |
| « L'endpoint refuse le jeton d'accès »                                          | Jeton expiré, ou sans droit sur cet endpoint.                                                                                                                                                                                                                                                                |
| « L'adresse répond, mais pas sur /v1/completions »                              | Mauvaise adresse, ou moteur sans API compatible OpenAI.                                                                                                                                                                                                                                                      |
| « Cette demande a expiré » après Autoriser                                      | Plus de 15 minutes, ou clé de signature différente entre deux instances : définissez `BIRD_SIGNING_SECRET`.                                                                                                                                                                                                  |
| Réponse coupée, « La connexion s'est interrompue »                              | Durée maximale atteinte ou réseau : « Réessayer ». Si c'est systématique, réduisez `BIRD_MAX_SECONDS`.                                                                                                                                                                                                       |
| Erreur 429                                                                      | Limite de débit : `BIRD_RATE_LIMIT`.                                                                                                                                                                                                                                                                         |
| Erreur 401 dans l'interface                                                     | Code d'accès manquant : Réglages → Modèle.                                                                                                                                                                                                                                                                   |

## 7. Ce qui a été vérifié, et où

Dans la documentation de Vercel (lue le 21/11/2026) :

- Points d'entrée (`app.py`, `index.py`, `server.py`, `main.py`… à la racine, dans `src/` ou `app/`), variable `app`, clé `[tool.vercel] entrypoint` ; Python 3.12 par défaut (3.13 et 3.14 disponibles) ; dépendances dans `pyproject.toml`, `requirements.txt` ou `Pipfile` ; streaming pris en charge ; taille maximale 500 Mo non compressés ; `excludeFiles` : <https://vercel.com/docs/functions/runtimes/python>
- Préréglage FastAPI, `public/` servi par le CDN, `StaticFiles` gardé dans la fonction quand l'application a un middleware global (c'est notre cas : l'en-tête CSP s'applique donc aux fichiers statiques), `functions` indexé par le fichier d'entrée : <https://vercel.com/docs/frameworks/backend/fastapi>
- Durée : « Hobby: 300s default and maximum » ; requête 4,5 Mo ; réponse 4,5 Mo sauf en streaming : <https://vercel.com/docs/functions/limitations>
- `.vercelignore`, forme liste blanche (`/*` puis `!…`) : <https://vercel.com/docs/deployments/vercel-ignore>
- Root Directory et réglages de build : <https://vercel.com/docs/builds/configure-a-build>

Constaté localement avec `npx vercel build` (CLI récente, sans connexion à un compte) :

- **Quand `pyproject.toml` et `requirements.txt` coexistent, c'est `pyproject.toml` qui est installé** (« Installing required dependencies from pyproject.toml »). La documentation ne le précise pas : c'est pourquoi les dépendances de base du projet ont été allégées.
- Le build réussit sur la racine du dépôt : une fonction `fastapi`, Python 3.12, `maxDuration` 300, streaming activé, **environ 66 Mo**, sans transformers, torch ni datasets ; `tests/`, `docs/`, `scripts/` absents du paquet.
- Les fichiers hors du Root Directory ne sont **pas** embarqués dans la fonction : d'où le choix de la racine du dépôt plutôt qu'un sous-dossier.

Dans la documentation des Inference Endpoints :

- 503 pendant le réveil, mise en veille après 1 h par défaut, en-tête `X-Scale-Up-Timeout` (non utilisé : Bird préfère réessayer et montrer l'attente) : <https://huggingface.co/docs/inference-endpoints/guides/autoscaling>
- Accès « Private » par jeton Hugging Face, « Public », « Authenticated » : <https://huggingface.co/docs/inference-endpoints/guides/configuration>
- TGI en maintenance, vLLM ou SGLang conseillés ; TGI annonce des API `/v1/chat` et `/v1/completions` : <https://huggingface.co/docs/inference-endpoints/engines/tgi>
- vLLM : <https://huggingface.co/docs/inference-endpoints/engines/vllm> · llama.cpp (GGUF, API compatible OpenAI) : <https://huggingface.co/docs/inference-endpoints/engines/llama_cpp>

## 8. Ce qui reste à vérifier sur un vrai déploiement

- Le déploiement lui-même (aucun compte Vercel ici) : le streaming de bout en bout à travers le réseau de Vercel, et l'absence de coupure pendant les silences (un commentaire SSE est envoyé toutes les 10 s pour cela).
- Que `.vercelignore` s'applique bien aux déploiements faits depuis Git, comme à ceux de la CLI.
- Le temps de démarrage à froid réel (mesuré localement : 1,4 s d'import dans un environnement neuf, 63 Mo de dépendances).
- Pour chaque moteur : la route `/v1/completions` avec invite brute et `stream: true` sur les Endpoints, la forme exacte des morceaux du flux et du champ `usage`, la valeur attendue pour `model`, la forme de l'adresse. Le client est écrit pour tolérer les variantes connues (avec ou sans `usage`, morceaux de type complétion, chat ou llama.cpp natif, refus de `stream_options` ou de plus de quatre séquences d'arrêt) et testé sur des réponses **reconstituées**, pas capturées.
- Le modèle lui-même : aucun essai n'a été fait avec le vrai Bird ; l'export fusionné ou GGUF reste à produire.
