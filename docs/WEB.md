# Interface web de Bird

Code : `birds/web/` (serveur FastAPI + frontend statique) · lancement : `scripts/serve.py` · tests : `tests/test_web.py`.

Pas d'étape de compilation, pas de CDN, pas de police distante, pas de traceur : trois petits fichiers (`index.html`, `app.css`, `app.js` et ses deux modules `markdown.js`, `i18n.js`) servis par le serveur lui-même.

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
| Énergie (Wh)                          | **Mesurée** (`nvidia-smi`, GPU seul, modèle sur la même machine : `--local` ou `--measure-gpu`) ou **estimée** si vous fournissez votre propre étalonnage (`--wh-per-1k-tokens`). Les deux cas sont étiquetés. |
| Émissions (g CO₂e)                    | Énergie × intensité carbone que **vous** déclarez avec `--grid-intensity` (g CO₂e/kWh). Toujours étiquetées « estimé ».                                                                                        |

## Ce qu'il ne montre pas

- **Pas de chiffre inventé.** Sans mesure ni étalonnage, l'interface écrit « énergie non mesurée sur ce serveur », jamais zéro. Sans `--grid-intensity`, aucune émission n'est affichée : il n'y a pas de valeur « typique » dans le code.
- La mesure GPU ne compte ni le processeur, ni la mémoire, ni le refroidissement, ni le réseau, ni la fabrication du matériel. Elle couvre le GPU entier, autres processus compris.
- L'intensité carbone est une valeur fixe donnée au lancement, pas celle du réseau à l'instant de la requête.
- Pas de coût en euros, pas de comparaison avec un « grand modèle », pas de tableau de bord par organisation (prévus au cadrage, non faits).
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
- Le mode réel n'a été testé qu'avec un modèle scripté (`FakeClient`), pas encore avec le vrai modèle.
- Les sources affichées sont les pages réellement lues par le harnais ; leur titre est leur adresse.
