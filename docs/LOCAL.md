# Bird local — le modèle sur votre machine

**Le plus simple :**

- Linux / macOS : `curl -fsSL https://bird-s.vercel.app/install.sh | sh`
- Windows (PowerShell) : `irm https://bird-s.vercel.app/install.ps1 | iex` — avec WSL (recommandé pour une carte
  NVIDIA, `wsl --install` une fois) tout s'installe dans WSL ; sans WSL, Bird se branche sur un serveur compatible
  OpenAI déjà lancé (LM Studio, Ollama, vLLM : `$env:BIRD_VLLM_URL`).

La page qui s'ouvre (http://127.0.0.1:8765) marche tout de suite, **sans code**. Pour utiliser votre Bird local depuis
bird-s.vercel.app, ouvrez le lien que la commande affiche (« Depuis bird-s.vercel.app, ouvrez : … ») : il est déjà
appairé, rien à taper.

Bird est léger : son modèle s'installe où vous voulez, y compris sur votre propre machine. **Bird local** fait tourner
le harnais complet de Bird (routage, outils, modules, empreinte) chez vous, devant votre serveur vLLM, et vous l'utilisez
soit depuis le chat hébergé (https://bird-s.vercel.app), soit directement dans votre navigateur
(http://127.0.0.1:8765). Vos conversations vont de votre navigateur à votre machine : nos serveurs ne les voient pas.

## Démarrer en trois étapes

1. **Le serveur du modèle**, sur votre machine :

   ```bash
   pip install vllm
   vllm serve adubrou/Bird-S-4B --host 127.0.0.1 --port 8000
   ```

2. **Bird local**, dans le dossier de Bird (`pip install -r requirements.txt` une fois) :

   ```bash
   python scripts/bird_local.py
   ```

   La commande vérifie le serveur du modèle (`GET /v1/models`, le modèle servi, les sorties structurées), démarre
   Bird sur http://127.0.0.1:8765, ouvre l'application dans votre navigateur et affiche un **code d'appairage**
   (par exemple `K7QM-W4XD`). Si vLLM ne répond pas, elle affiche la commande exacte à lancer et s'arrête.

3. **Dans le chat** : Réglages → Modèle → « Bird local (votre machine) » (ou un clic sur la pastille du modèle, en haut),
   tapez le code, « Se connecter au Bird local ». La pastille affiche « Bird local » (badge vert calme) ; « Revenir au
   modèle hébergé » vous ramène au modèle hébergé, « Oublier le code » l'efface de ce navigateur.

Tout-en-un : `curl -fsSL https://bird-s.vercel.app/install.sh | sh` installe Bird dans `~/.bird`, démarre vLLM puis
cette commande, et ouvre la page déjà appairée (`sh ~/.bird/stop.sh` pour arrêter).

Options : `--vllm-url URL` (défaut `http://127.0.0.1:8000/v1`), `--model NOM` (défaut : le modèle servi, un Bird de
préférence), `--port 8765`, `--allow-origin ORIGINE` (répétable, remplace la liste par défaut), `--no-browser`,
`--new-code` (nouveau code, l'ancien ne marche plus), `--measure-gpu` (énergie mesurée par nvidia-smi),
`--grid-intensity G` (votre réseau électrique, g CO₂e/kWh), `--workspace DOSSIER`, `--searxng URL`, `--lang en`.
Variables : `BIRD_LOCAL_VLLM_URL`, `BIRD_LOCAL_MODEL`, `BIRD_LOCAL_ORIGINS`, `BIRD_LOCAL_VLLM_KEY` (clé du serveur
vLLM si vous en avez mis une, jamais affichée). Les autres variables `BIRD_*` (recherche, cartes…) s'appliquent aussi.

## Ce que fait chaque côté

| | Chat hébergé | Bird local (votre machine) |
|---|---|---|
| Page | servie par Vercel | la même page, ou rien (vous restez sur la page hébergée) |
| `/api/chat`, outils, exports, canevas | **votre machine** (127.0.0.1:8765) | harnais Bird, outils exécutés chez vous |
| Modèle | — | votre vLLM (127.0.0.1:8000) |
| Conversations | stockées dans votre navigateur | jamais conservées côté serveur |
| `/api/health` | décrit le déploiement hébergé | décrit Bird local (`bird_local`) |

En mode Bird local, toutes les requêtes `/api/*` de la page partent vers la machine (sauf `/api/health`, qui décrit le
déploiement hébergé) ; les en-têtes propres au mode hébergé (code d'accès, endpoint personnel) sont retirés. Les images
signées par Bird local (`/api/img`, `/api/map`, `/api/icon`) sont affichées depuis la machine.

## Sécurité

- **Boucle locale seulement.** Bird local n'écoute que sur 127.0.0.1 (aucune option pour 0.0.0.0) et refuse toute
  requête dont l'en-tête `Host` n'est pas exactement `127.0.0.1:8765` ou `localhost:8765` (protection contre le
  *DNS rebinding* : un nom hostile résolu vers 127.0.0.1 arrive avec son propre `Host`, réponse 421).
- **Une seule origine.** Les appels d'une autre page ne sont acceptés que depuis une liste exacte d'origines (par défaut
  `https://bird-s.vercel.app` ; `--allow-origin` pour une autre instance ; https obligatoire, http seulement pour
  127.0.0.1/localhost ; aucun joker). CORS ne renvoie que cette origine (`Vary: Origin`), jamais `*`, jamais de
  cookies (`credentials: "omit"`). Une autre origine reçoit 403 sans en-tête CORS : elle ne peut rien lire.
- **Private / Local Network Access.** La prévalidation de Chrome (`Access-Control-Request-Private-Network: true`) reçoit
  `Access-Control-Allow-Private-Network: true` pour l'origine autorisée seulement. Les navigateurs récents peuvent
  demander l'autorisation d'accéder aux appareils du réseau local : acceptez-la pour le site du chat. La page passe
  `targetAddressSpace: "loopback"` à ses requêtes (ignoré ailleurs).
- **Code d'appairage.** Chaque appel d'API (y compris depuis la page servie par Bird local) porte l'en-tête
  `X-Bird-Pair` ; comparaison à temps constant (`hmac.compare_digest`). Code de 8 caractères sans lettres ambiguës
  (~39 bits), conservé entre deux lancements dans `~/.config/bird/local.json` (droits 0600) ; `--new-code` le change.
  Après 8 codes faux en une minute, l'API se verrouille une minute (429), y compris pour le bon code : celui qui
  devine n'apprend rien pendant le verrou. Seuls `/api/health` (sans le code ni l'URL
  vLLM) et les images signées répondent sans code. La commande ouvre `http://127.0.0.1:8765/#pair=CODE` : le fragment
  ne quitte jamais le navigateur et la page l'efface de la barre d'adresse.
- **Côté navigateur**, le code est gardé dans `sessionStorage` (cet onglet) ; dans `localStorage` seulement avec « Se
  souvenir de ce code sur cet appareil ». « Oublier le code » et « Tout effacer » le suppriment. Un nouvel onglet sans
  le code reste en Bird local : la requête part vers la machine, qui demande le code ; jamais de repli silencieux vers
  le modèle hébergé.
- **Journaux** : `install.sh` met `~/.bird/logs` (qui contient le code affiché) en mode 700.
- **CSP du chat hébergé.** L'unique exception à « aucun tiers » : `connect-src` et `img-src` gagnent exactement
  `http://127.0.0.1:8765 http://localhost:8765` (votre propre machine), rien de plus large, aucun autre port.
  `BIRD_LOCAL_BIRD_PORT=off` retire le choix et l'exception ; `BIRD_LOCAL_BIRD_PORT=9876` change de port (≥ 1024).
- **Limite de débit** : 240 requêtes par minute sur la machine, en plus de la limite du harnais.
- **Confidentialité** : le serveur hébergé ne reçoit aucun message, aucune pièce jointe, aucun appel d'outil d'une
  conversation Bird local (vérifié par l'e2e : aucun `/api/*` hors `/api/health` vers l'hôte pendant un tour).

## Empreinte

Sur Bird local, l'énergie est **estimée pour votre machine** à partir des tokens (les repères publiés d'un serveur vLLM,
comme sur le déploiement), ou **mesurée** sur votre carte graphique avec `--measure-gpu` (échantillonnage nvidia-smi).
La page Empreinte le dit en une ligne ; `--grid-intensity` donne les émissions de votre réseau électrique.

## Quand Bird local ne répond pas

Le chat ne montre jamais d'erreur brute : une carte « Bird local ne répond pas » donne les trois étapes (commandes à
copier), « Réessayer » et « Revenir au modèle hébergé ». Si Bird local a été relancé avec un nouveau code, le tour
demande de se reconnecter dans les réglages. Si Bird local répond mais pas vLLM, la carte « Le modèle ne répond pas
sur votre machine » donne la commande `vllm serve …`. Si le serveur sert un autre modèle que Bird (sans `--model`), la
commande le signale.

Limites connues : Safari bloque les appels d'une page https vers `http://127.0.0.1` ; utilisez alors directement
http://127.0.0.1:8765 (l'application complète, servie par Bird local) ; sur Safari (et tout navigateur iOS), la carte
« ne répond pas » le dit. Firefox et les navigateurs Chromium acceptent. Sous Windows, la commande s'affiche sans
planter sur une console cp1252.

## Tests

- `tests/test_local.py` : Host, origines, CORS et prévalidation PNA, code (forme, comparaison, verrouillage), limite de
  débit, CSP hébergée, sonde vLLM simulée (modèle choisi, sorties structurées, panne, clé), commande.
- `tests/js/local.test.mjs` : code, stockage, routage des requêtes, images, sonde et appairage (fetch simulé),
  bascule de mode dans `core.js`, parité FR/EN.
- `tests/e2e/bird_local.spec.js` : un faux serveur compatible OpenAI (`tests/fixtures/fake_vllm.py`), Bird local et une
  page hébergée ; choix, carte « ne répond pas », appairage (code faux puis juste), tour complet par la machine,
  empreinte, déconnexion, page servie localement, arrêt en cours de conversation ; captures 360/1280, clair/sombre.

---

# Bird local (English)

Bird is light: its model installs wherever you want, your own machine included. **Bird local** runs Bird's full harness
on your machine, in front of your vLLM server; use it from the hosted chat or directly at http://127.0.0.1:8765.
Your conversations go from your browser to your machine, never through our servers.

1. `vllm serve adubrou/Bird-S-4B --host 127.0.0.1 --port 8000`
2. `python scripts/bird_local.py` (checks `/v1/models`, the served model and structured outputs; starts Bird on
   127.0.0.1:8765; opens it; prints a pairing code; if vLLM is down, prints the exact command and stops)
3. In the chat: Settings → Model → « Bird local (your machine) », type the code, « Connect to Bird local ».

Security: loopback bind and exact `Host` check (DNS rebinding); one exact allowed origin (default
`https://bird-s.vercel.app`, `--allow-origin` to change), CORS for it alone, no credentials; Chrome's Private Network
Access preflight answered for it alone; every API call carries the pairing code (`X-Bird-Pair`, constant-time compare,
lock after 8 wrong codes a minute, the right code included); the code is kept in `sessionStorage`, or `localStorage` with « Remember », and
« Forget the code » removes it; the hosted CSP gains exactly `http://127.0.0.1:8765 http://localhost:8765` in
`connect-src` and `img-src`, nothing wider (`BIRD_LOCAL_BIRD_PORT=off` removes it); rate limit; the hosted server never
sees a local conversation, not even from a new tab without the code (it asks the machine, which asks for the code).
A model server down behind Bird local gets its own card with the `vllm serve` command; Safari users are told to open
http://127.0.0.1:8765 directly. Energy is estimated for your machine from tokens, or measured with `--measure-gpu`.
