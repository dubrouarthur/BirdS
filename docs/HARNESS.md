# Harnais agent de Bird

Code : `birds/harness/` · tests : `tests/test_harness.py` · ligne de commande : `scripts/chat.py`.

## 1. Ce que fait le harnais

Bird est un petit modèle (4 Md de paramètres). Le harnais est donc petit lui aussi : invite système courte (celle de `docs/PERSONA.md`, dans la langue de l'utilisateur), huit outils au plus, boucle bornée. **Toutes les règles de sécurité sont appliquées par le code, jamais confiées au modèle.**

Déroulé d'une requête :

1. Le harnais construit la conversation et la met en forme avec le gabarit de conversation du modèle (`birds.render.prompt`). La réflexion (`thinking`) est désactivée par défaut, par sobriété.
2. Le modèle génère. Le harnais lit sa sortie (`birds.parse.parse_output`) : soit une réponse, soit des appels d'outils.
3. Chaque appel est validé, filtré par les garde-fous, exécuté, puis son résultat est rendu au modèle comme **donnée** (message `tool`).
4. On recommence jusqu'à une réponse sans appel d'outil, ou jusqu'à une limite.

Le résultat est un objet `Run` : réponse finale, étapes (outil, arguments, résumé du résultat, durée, erreur, signalements, décision), sources (URL réellement lues), brouillons de mail, fichiers créés, consommation par génération, bilan de ressources, raison d'arrêt.

Limites par défaut (`birds/harness/config.py`) :

| Limite                                             | Valeur                                  |
| -------------------------------------------------- | --------------------------------------- |
| Générations par requête                            | 6                                       |
| Appels d'outils par génération                     | 3                                       |
| Taille d'un résultat d'outil                       | 6 000 caractères, puis `[truncated]`    |
| Total des résultats d'outils dans le contexte      | 24 000 caractères                       |
| Tokens par génération                              | 1 024                                   |
| Durée totale                                       | 180 s (vérifiée entre deux générations) |
| Actions à effet (mail, fichiers, code) par requête | 5                                       |

Raisons d'arrêt : `answer`, `max_steps`, `loop` (même appel répété à l'identique), `invalid_tool_calls` (deux générations de suite avec des appels invalides : une seule relance est accordée), `malformed_output`, `empty_output`, `timeout`. Hors `answer`, l'utilisateur reçoit un message franc disant que Bird n'a pas abouti.

## 2. Les outils

Les schémas sont ceux de `birds/tools.py`, sur lesquels le modèle est entraîné. Ils ne sont pas modifiés.

| Outil                                        | Ce qu'il fait réellement                                                                                                                                                               |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web_search`                                 | Interroge le premier moteur configuré : SearXNG (`searxng_url`), Brave Search (`brave_api_key`), Tavily (`tavily_api_key`), sinon **Wikipédia** (sans clé, fr/en selon la conversation). Rend une liste numérotée : titre, URL, extrait. Toujours proposé, sauf `search_default="none"` sans moteur. Un moteur à clé qui échoue bascule sur Wikipédia. Voir `birds/harness/tools/search.py` et docs/DEPLOY_VERCEL.md § 2 bis. |
| `read_page`                                  | Télécharge une page (httpx) sous politique de sortie réseau, puis extrait le texte principal avec `trafilatura` (à défaut : conversion HTML minimale). Aucun JavaScript n'est exécuté. |
| `read_file`                                  | Lit un fichier **du dossier de travail uniquement** : txt, md, csv, json ; pdf, docx, xlsx, pptx si les bibliothèques sont installées.                                                 |
| `draft_email`                                | Enregistre un brouillon (destinataires, objet, corps, ton) dans le `Run`. **N'envoie rien** : le harnais n'a aucun moyen d'envoyer un mail.                                            |
| `make_slides`, `make_document`, `make_sheet` | Créent un .pptx, .docx ou .xlsx dans `bird_out/` (`birds/harness/office.py`). Diapositives 16:9 au thème Bird : couverture, intercalaires (diapositive sans puces), titres réels, puces à deux niveaux (`"  sous-point"`), taille de police adaptée, découpe automatique des listes longues en « (1/2) », numéros, notes de l'orateur (`notes`, accepté s'il est fourni, non annoncé au modèle). Document : titre, date, Markdown des sections rendu en titres, listes, tableaux (lignes `|`, tabulations ou `;`), gras. Tableur : en-tête stylé et figé, filtre, largeurs, nombres/monnaies/pourcentages/dates typés, **formules conservées** sauf celles qui sortent du fichier (WEBSERVICE, HYPERLINK, IMPORT…, liens externes, DDE), écrites alors comme texte. Le nom du fichier est généré par le harnais. |
| `run_python`                                 | **Désactivé par défaut** : il répond « non activé » et n'est pas proposé au modèle. Voir §4.                                                                                           |

## 2 bis. Robustesse face aux erreurs d'un petit modèle

**Réparation des arguments, avant validation** (la validation reste la même) :

| Forme reçue | Devient | Cas réel |
| --- | --- | --- |
| tableau ou objet écrit en texte JSON, même sans le dernier `]` ni `}`, virgule finale, guillemets simples Python | la structure | `make_slides` : `"slides": "[{...}, {...}"` (endpoint réel, 22/11/2026 : la présentation n'était pas créée) |
| nombre ou booléen en texte (`"5"`, `"12,5"`, `"oui"`) | nombre, booléen | `max_results: "5"` |
| un objet seul où une liste est attendue | liste d'un élément | `slides: {"title":…, "bullets":…}` |
| liste de textes écrite d'un bloc (lignes, puces, virgules, points-virgules) | liste | `to: "a@x.fr; b@y.fr"`, `bullets: "- un\n- deux"` |
| clés synonymes évidentes | clé attendue | `content`/`points` → `bullets`, `title` → `heading`, `text` → `content` |
| lignes de tableur en objets `{colonne: valeur}` ou en texte JSON | listes dans l'ordre des colonnes | `make_sheet` |

Chaque réparation est notée sur l'étape (`repairs`, journal d'audit, et « Arguments remis en forme » dans l'interface). Un argument qui reste faux après réparation est refusé, avec un message qui dit quoi corriger et donne un exemple d'appel.

**Appel répété** : le même appel avec les mêmes arguments reçoit une fois un rappel (« déjà appelé, utilise le résultat ») et l'outil est retiré pour le reste de la requête ; à la deuxième répétition, arrêt `loop`.

**Outils proposés selon la demande** (`agent.route`) : une demande de fichier ou de brouillon (présentation, document, compte rendu, tableur, mail…) qui ne demande aucune information extérieure (cherche, web, actualité, récent, prix, taux, une année, une URL…) ne reçoit pas `web_search` ni `read_page`. Raison mesurée sur l'endpoint réel : avec la recherche proposée, « fais une présentation de 4 diapositives sur le télétravail » déclenchait une recherche, puis la même recherche en boucle, et jamais le .pptx ; sans elle, le .pptx est créé du premier coup. Coût : sur les tours concernés, le bloc d'outils du prompt change, donc le préfixe mis en cache par vLLM n'est pas réutilisé pour ce tour (voir § 9). `Config.route_tools=False` le désactive.

**Réponse coupée** : si la dernière génération s'arrête sur `finish_reason = "length"`, la raison d'arrêt est `length` (et non `answer`) ; la réponse est gardée et marquée « [réponse interrompue] » dans l'historique.

**Texte en boucle** (`llm.find_loop`) : pendant le flux, toutes les 48 nouvelles lettres, le harnais regarde si la fin du texte répète un même motif exact (mot, ligne, paragraphe) au moins 3 fois et sur au moins 400 caractères (3 200 si le motif n'a ni lettre ni chiffre : espaces, tirets, lignes de tableau vides). Si oui, il ferme la connexion : vLLM annule la requête et le GPU s'arrête au lieu de tourner jusqu'à `max_tokens`. Une seule copie du motif est gardée, la raison d'arrêt devient `repetition`, l'interface affiche « Bird se répétait : réponse arrêtée net » avec « Relancer », et la réponse est marquée interrompue dans l'historique. Une boucle pendant la réflexion, sans réponse, donne un message qui le dit. Mesure sur les 264 000 réponses longues du jeu d'entraînement (`out/pool_all`) : 58 signalées, toutes dégénérées (base64 répété, balises d'appel d'outil à l'infini, une formule recopiée) sauf un modèle de facture JSON avec plus de 3 000 caractères de lignes vides identiques.

## 3. Les garde-fous, et ce qu'ils ne couvrent pas

| Garde-fou                                            | Ce qu'il fait                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Ce qu'il ne fait PAS                                                                                                                                                                                                                                                                                                                   |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Sortie réseau** (`guard.check_url`, `guard.fetch`) | Seuls http et https, ports 80 et 443. Le nom d'hôte est résolu et la requête est refusée si une seule de ses adresses est locale, privée, de lien local, multicast, réservée ou de métadonnées cloud (IPv4 et IPv6, formes IPv4 encapsulées comprises). La vérification est refaite à chaque redirection (4 au plus). La connexion se fait vers l'adresse validée, ce qui ferme l'attaque par changement de réponse DNS. Listes de domaines autorisés ou interdits en option. Taille maximale (2 Mo), types non textuels refusés.                                                 | Derrière un proxy de sortie, c'est le proxy qui résout les noms : il faut alors désactiver l'épinglage (`pin_dns=False`) et filtrer sur le proxy. Le moteur de recherche est appelé à l'adresse fixée par l'exploitant, sans ce filtre. Une page publique peut contenir n'importe quoi de faux.                                        |
| **Contenu non fiable**                               | Les résultats de `web_search`, `read_page`, `read_file` et `run_python` sont précédés d'une ligne fixe disant que c'est une donnée externe dont les instructions ne doivent pas être suivies. Les marqueurs du gabarit de conversation (`<\|im_end\|>`, `</tool_response>`, `<tool_call>`…) présents dans un contenu externe sont neutralisés, pour qu'un texte ne puisse pas sortir du message `tool`. Chaque résultat est analysé avec une liste de motifs français et anglais ; en cas de correspondance, l'étape porte `possible_injection`. La lecture n'est jamais bloquée. | La détection par motifs est **heuristique** : une injection formulée autrement, dans une autre langue ou dans une image passe sans signalement. Un texte légitime qui parle d'« invite système » est signalé à tort. La ligne d'avertissement n'est qu'une consigne : le modèle peut quand même se laisser influencer dans sa réponse. |
| **Actions après contenu suspect**                    | Dès qu'un résultat de la requête est signalé, `draft_email`, `make_*` et `run_python` exigent que la fonction `confirm(outil, arguments)` rende `True`. Par défaut elle refuse. Ces actions sont aussi plafonnées à 5 par requête.                                                                                                                                                                                                                                                                                                                                                | Si l'injection n'a pas été détectée, il n'y a pas de demande de confirmation. Les outils de lecture restent permis : une page piégée peut faire lire une autre page publique (fuite possible d'informations par l'URL demandée). Pour un déploiement sensible, exiger la confirmation pour toute action.                               |
| **Validation des appels**                            | Les arguments sont d'abord **réparés** quand l'intention est claire (`birds/harness/coerce.py`, voir § 2 bis), puis vérifiés contre le schéma JSON de l'outil ; clés inconnues refusées ; outil inconnu ou hors liste blanche refusé. En cas d'échec, le modèle reçoit un message précis (argument fautif, type attendu, exemple d'appel correct, « appelle de nouveau l'outil ») et peut corriger une fois. | Un appel valide dans sa forme peut être mauvais sur le fond (mauvais destinataire, mauvais chiffre).                                                                                                                                                                                                                                   |
| **Fichiers**                                         | `read_file` résout le chemin (liens symboliques compris) et refuse tout ce qui sort du dossier de travail ; taille limitée. Les formules de tableur qui sortent du fichier (requêtes web, liens, classeurs externes, DDE) sont écrites comme du texte ; les autres formules sont gardées. | Tout ce qui se trouve dans le dossier de travail est lisible, journal d'audit compris. N'y placez que ce que l'assistant a le droit de lire.                                                                                                                                                                                           |
| **Secrets**                                          | Les résultats d'outils, la réponse et le journal passent par un filtre qui masque les chaînes ayant la forme de clés, jetons, mots de passe (`[REDACTED]`). Le harnais ne met jamais de variable d'environnement dans une invite.                                                                                                                                                                                                                                                                                                                                                 | Quelques motifs prudents seulement : un secret de forme inhabituelle n'est pas masqué. Ne mettez pas de secrets dans le dossier de travail.                                                                                                                                                                                            |
| **Journal d'audit**                                  | Une ligne JSON par appel d'outil et par requête dans `bird_audit.jsonl` : date, outil, arguments (abrégés), durée, taille, signalements, décision.                                                                                                                                                                                                                                                                                                                                                                                                                                | Le journal est un fichier local simple : il n'est ni signé ni protégé contre la modification.                                                                                                                                                                                                                                          |

Dans tous les cas, **le modèle peut se tromper** : résumé inexact, chiffre mal recopié, source mal citée. La liste `sources` dit quelles pages ont été lues, pas que la réponse leur est fidèle. Pour ce qui compte, on relit.

## 4. `run_python` : ce n'est PAS un bac à sable

Activé (`allow_python=True`, option `--allow-python`), l'outil lance `python -I` dans un sous-processus : dossier temporaire neuf, environnement vidé (aucun jeton ni réglage de proxy transmis), limites de temps processeur, de durée, de mémoire et de taille de fichier, sortie tronquée.

Ces mesures sont de l'hygiène, **pas de l'isolation**. Le code s'exécute avec les droits de l'utilisateur du harnais : il peut lire et écrire des fichiers, ouvrir des connexions réseau, lancer d'autres programmes. **À n'activer que dans un conteneur jetable**, sans secret, sans montage de données sensibles, avec un réseau restreint. Le vrai bac à sable prévu au cadrage reste à construire.

## 5. Mesure des ressources

`Run.report` donne : tokens en entrée et en sortie, secondes de génération et durée totale, nombre d'appels d'outils, octets téléchargés.

Énergie : `energy_wh` vaut `null` tant qu'il n'y a pas de mesure. **Aucune estimation n'est inventée.**

- `measured` : puissance du GPU relevée par `nvidia-smi` pendant les générations (client local, ou `measure_gpu=True` si le serveur tourne sur la même machine). C'est la consommation du GPU entier, hors processeur et reste de la machine.
- `estimated` : seulement si l'exploitant fixe `wh_per_1k_tokens` ; le bilan porte alors la mention « estimated » et la source de l'étalonnage.

## 6. Lancer le harnais

Installation : `uv pip install --python .venv/bin/python -e ".[harness]"`.

Servir le modèle derrière un point d'accès compatible OpenAI, puis :

```bash
# llama.cpp
llama-server -m bird.gguf --port 8080
# ou vLLM
vllm serve <dossier-du-modèle> --served-model-name bird --port 8080

.venv/bin/python scripts/chat.py --base-url http://localhost:8080/v1 --model bird \
    --workspace ./travail --searxng http://localhost:8888
```

Options : `--think` (réflexion), `--allow-python` (voir §4), `--local MODÈLE [--adapter DOSSIER]` pour charger le modèle dans le processus sur une machine à GPU, `--no-pin-dns` derrière un proxy de sortie. La ligne de commande affiche les étapes, la réponse, les sources et le bilan, et demande confirmation au terminal quand une action est soumise à validation.

Le harnais appelle **`/v1/completions` avec l'invite brute** qu'il a lui-même mise en forme. C'est voulu : on ne dépend ni du gabarit de conversation du serveur, ni de son analyseur d'appels d'outils. Seul le tokenizer est chargé côté harnais (pas les poids). SearXNG doit avoir le format `json` activé dans sa configuration.

## 7. Compatibilité OpenClaw, Hermes Agent et autres clients

Le modèle est servi derrière un point d'accès standard (`/v1/chat/completions`). Tout client compatible OpenAI peut donc s'y brancher, à condition que le serveur applique le gabarit du modèle et sache lire son format d'appel d'outils.

Limite à dire clairement : ces clients envoient **leurs propres invites système et leurs propres schémas d'outils**, souvent longs et nombreux. Bird n'a pas été entraîné dessus. Il faut s'attendre à des appels d'outils moins fiables, à un contexte vite saturé et à la perte du gain énergétique. Surtout, **aucun des garde-fous ci-dessus ne s'applique** dans ce cas : la sécurité est alors celle du client. Cette compatibilité est à tester, pas à promettre ; le chemin pris en charge est ce harnais.

## 9. Historique de conversation et cache de préfixe

Référence : docs/HISTORY_SPEC.md. Code : `birds/harness/history.py`, `birds/web/backends.py` (`prepare_turn`, `conv_lang`, `run_lang`, `cache_salt`).

- **Budget** : `BIRD_HISTORY_TOKENS` (6 000 tokens estimés, longueur / 3,5) pour les tours précédents ; chaque message passé est plafonné à `BIRD_HISTORY_MSG_TOKENS` (3 168 : 2/3 du début + 1/3 de la fin), de la même façon quelle que soit sa position.
- **Coupe à hystérésis** : quand l'historique dépasse le budget, les tours les plus anciens sont retirés **entiers** jusqu'à la moitié du budget. La coupe est rejouée depuis le début de la conversation (fonction pure, serveur sans état) et ne bouge qu'environ une fois par demi-budget : entre deux coupes, le prompt du tour N+1 commence exactement par les octets du tour N, ce que le cache de préfixe de vLLM réutilise. Les tours retirés sont résumés sans appel au modèle (première ligne de chaque demande, fichiers et sources produits), à la fin du message système.
- **Mémo d'outils** : chaque réponse garde un mémo déterministe (outils et arguments clés, titres et URL des résultats de recherche, pages lues, fichiers créés, objet du brouillon), jamais le texte brut des outils. Il est rendu à la fin de la réponse correspondante dans l'historique. Le modèle a parfois recopié ce format à la fin d'une réponse : cet écho est retiré (`strip_memo`).
- **Texte exact** : le serveur envoie au navigateur, par un événement `user`, le texte exact que le modèle a reçu (transcriptions d'images plafonnées à 2 400 caractères et précédées de la mention « donnée externe », notes de pièces jointes) ; le navigateur le renvoie tel quel aux tours suivants. Les images ne sont jamais renvoyées.
- **Langue** : fixée par le navigateur au premier message (`conv_lang`), jamais détectée ; une requête n'est traitée dans l'autre langue que si elle en porte au moins 3 marqueurs, deux fois plus que l'autre.
- **Réponses interrompues** (`finish_reason = length` ou arrêt) : marquées « [réponse interrompue] ».
- **Isolation du cache** : `cache_salt` par conversation (sha256 d'un UUID aléatoire du navigateur). Vérifié sur l'endpoint réel : même sel → 1 056 tokens servis par le cache sur un prompt de 1 396 tokens ; autre sel → 0. Taille de bloc observée : 528. `BIRD_CACHE_SALT=off` partage le cache entre conversations (meilleur taux, moins de confidentialité).
- **Écarts assumés par rapport à la spécification** : (1) l'outil `read_file` est toujours proposé (bloc d'outils stable), mais le routage du § 2 bis retire les outils web sur les demandes de fichier, ce qui change le bloc d'outils de ces tours : mesuré, sans routage le modèle a fait des recherches au lieu de créer le document, le tableur et le mail (3 échecs sur 3 dans une conversation de 8 tours) ; avec routage il les crée (voir ci-dessous). (2) Pas de sonde `cache_salt` au démarrage : sur Vercel elle réveillerait l'endpoint à chaque démarrage à froid ; l'acceptation a été vérifiée à la main. (3) Le contrôle de gabarit `BIRD_TOKENIZER` (§ 3.9) n'est pas fait. (4) `cached_tokens` par génération n'est pas disponible : l'endpoint n'a pas `--enable-prompt-tokens-details` (réglage de l'endpoint, non modifié ici) ; seuls les compteurs de `/metrics` ont servi.

**Mesure réelle** (22/11/2026, endpoint vLLM, une conversation française de 8 tours : recherche, « la deuxième source », note Word, ajout d'une section, tableur, ajout d'une colonne, mail, résumé ; compteurs `vllm:prefix_cache_queries_total` / `hits_total` lus avant et après chaque tour, en séquence, sans autre trafic connu) :

| Version | Tokens de prompt (8 tours) | Tokens servis par le cache | Premier token (médiane) | Fichiers / brouillons créés quand demandés |
| --- | --- | --- | --- | --- |
| Avant (historique complet, sans mémo, sans sel) | 17 960 | 12 672 (71 %) | 0,20 s | note, tableur, mail (les « mises à jour » sont annoncées sans être refaites) |
| Après (fenêtre, mémo, texte exact, sel par conversation) | 23 692 | 12 672 (53 %) | 0,37 s | note ; tableur et mail rédigés dans la réponse sans outil |

Lecture franche : le mémo et les résultats de recherche rendent « la deuxième source » vérifiable (réponse identique sur ces deux runs, la source étant hors sujet : Wikipédia renvoie « Noms des jours de la semaine »), mais coûtent des tokens ; le sel par conversation supprime le partage du préfixe système + outils entre conversations, d'où un taux de cache plus bas. Sur des conversations plus longues que le budget, la fenêtre borne le prompt (le naïf grossit sans limite jusqu'au refus 413). Les demandes de modification de fichier (« ajoute une colonne et refais-le ») ne sont pas refaites par le modèle dans les deux versions : limite du modèle, pas du harnais.

## 10. Essais réels (22/11/2026, endpoint vLLM, Bird S 4B)

`out/ops/e2e_web.py` (API web, mode serveur) : recherche → Wikipédia, réponse correcte (5,3 s, ≈ 0,085 Wh estimés) ; présentation → .pptx de 4 diapositives (7,9 s) ; compte rendu → .docx (5,0 s) ; tableur avec formule de total → .xlsx (5,9 s) ; mail → brouillon « Réunion décalée au vendredi 10 h » ; question TVA sans outil → 1 440 € TTC (2,5 s) ; image de facture → « Total TTC 1 320,00 € » exact (9,3 s). Avant les corrections : recherche « non configurée », présentation refusée (liste écrite en texte JSON), puis présentation jamais créée après une recherche en boucle.

## 8. Ce qui reste à vérifier

- Essais réels faits (§ 9 et § 10), mais sur quelques dizaines de requêtes seulement. Le comportement face à une page piégée (injection) n'a pas été testé en réel : aucune page piégée n'a été hébergée.
- La ligne d'avertissement placée devant les résultats d'outils n'existe pas dans les données d'entraînement actuelles (`birds/sources/guardrails.py`). Il faut soit l'y ajouter, soit vérifier qu'elle ne dégrade pas les réponses.
- Le client local (`LocalClient`) et la mesure `nvidia-smi` n'ont pas été exécutés sur GPU.
- Les serveurs (llama.cpp, vLLM, Ollama) n'ont pas été testés en vrai ; seul le format de la requête l'est.
