# Harnais agent de Bird

Code : `birds/harness/` · tests : `tests/test_harness.py` · ligne de commande : `scripts/chat.py`.

## 1. Ce que fait le harnais

Bird est un petit modèle (4 Md de paramètres). Le harnais est donc petit lui aussi : invite système courte (celle de `docs/PERSONA.md`, dans la langue de l'utilisateur), huit outils entraînés, plus trois outils de fiches (lieux, entreprise, devises) proposés seulement quand la demande les appelle, boucle bornée. **Toutes les règles de sécurité sont appliquées par le code, jamais confiées au modèle.**

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

Les schémas sont ceux de `birds/tools.py`, sur lesquels le modèle est entraîné. Ils ne sont pas modifiés : `BIRD_TOOLS` reste octet pour octet le jeu entraîné (données d'entraînement, banc d'essai, tests de cache). `make_chart`, non entraîné, est dans une liste à part (`EXTRA_TOOLS`, `PRODUCT_TOOLS = BIRD_TOOLS + EXTRA_TOOLS`) et vient toujours en dernier dans le bloc d'outils.

| Outil                                        | Ce qu'il fait réellement                                                                                                                                                               |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web_search`                                 | Interroge le premier moteur configuré : SearXNG (`searxng_url`), Brave Search (`brave_api_key`), Tavily (`tavily_api_key`), sinon **Wikipédia** (sans clé, fr/en selon la conversation). Rend une liste numérotée : titre, URL, extrait. Toujours proposé, sauf `search_default="none"` sans moteur. Un moteur à clé qui échoue bascule sur Wikipédia. Voir `birds/harness/tools/search.py` et docs/DEPLOY_VERCEL.md § 2 bis. |
| `read_page`                                  | Télécharge une page (httpx) sous politique de sortie réseau, puis extrait le texte principal avec `trafilatura` (à défaut : conversion HTML minimale). Aucun JavaScript n'est exécuté. |
| `read_file`                                  | Lit un fichier **du dossier de travail uniquement** : txt, md, csv, json ; pdf, docx, xlsx, pptx si les bibliothèques sont installées.                                                 |
| `draft_email`                                | Enregistre un brouillon (destinataires, objet, corps, ton) dans le `Run`. **N'envoie rien** : le harnais n'a aucun moyen d'envoyer un mail.                                            |
| `make_slides`, `make_document`, `make_sheet` | Créent un .pptx, .docx ou .xlsx dans `bird_out/` (`birds/harness/office.py`). Diapositives 16:9 au thème Bird : couverture, intercalaires (diapositive sans puces), titres réels, puces à deux niveaux (`"  sous-point"`), taille de police adaptée, découpe automatique des listes longues en « (1/2) », numéros, notes de l'orateur (`notes`, accepté s'il est fourni, non annoncé au modèle). Document : titre, date, Markdown des sections rendu en titres, listes, tableaux (lignes `|`, tabulations ou `;`), gras. Tableur : en-tête stylé et figé, filtre, largeurs, nombres/monnaies/pourcentages/dates typés, **formules conservées** sauf celles qui sortent du fichier (WEBSERVICE, HYPERLINK, IMPORT…, liens externes, DDE), écrites alors comme texte. Le nom du fichier est généré par le harnais. |
| `make_chart`                                 | Affiche un graphique dans la conversation (barres, courbe, camembert), dessiné en SVG par le navigateur (`birds/web/static/chart.js`). Arguments au format de `make_sheet` : `{title, type?, columns, rows, unit?}`, la première colonne porte les libellés, chaque autre colonne une série. Le serveur ne fait que vérifier et remettre en forme (`birds/harness/tools/chart.py`). **Proposé seulement** quand les mots de l'utilisateur demandent un graphique (voir plus bas). Ce n'est **pas un fichier** (il ne répond pas à « fais un fichier ») ni une action (pas de confirmation, pas dans `SIDE_EFFECT_TOOLS`) ; 3 graphiques au plus par requête. Chaque graphique dit d'où viennent ses chiffres : message, fichier, web, ou Bird (alors marqué « non vérifiés »). « fichier » et « web » exigent que chacun de ses nombres figure dans ce que `read_file`, `web_search` ou `read_page` ont réellement rendu dans le tour (`Context.fetched`) : une recherche sans chiffres ne fait pas passer des chiffres inventés pour des données du web. |
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
| `make_chart` : autres formes (`{labels, series:[{name, values}]}`, `{labels, values}`, `{data: {libellé: valeur}}`, `x`/`y`, `categories`, `chart_type`/`kind`) | `columns`/`rows` ; libellés et valeurs de longueurs différentes : **erreur**, jamais tronqué | — |
| `make_chart` : lignes en texte JSON cassé, une ligne par rangée sans crochet ouvrant, ou sans crochets extérieurs | rangées | endpoint réel, 22/11/2026 (« CA 2025 par trimestre », « website visits ») |
| `make_chart` : `"12,5"`, `"12 %"`, `"1 200 €"`, `"1.234,5"`, `"1,2 M€"`, `"n/a"` | nombres (unité lue dans les valeurs), trou ; `"1,234"` = 1,234 en français, 1234 en anglais ; formule ou mot : erreur qui nomme la cellule (`rows/2/1`) | — |
| `make_chart` : type `histogramme`, `courbe`, `camembert`… ; type absent | `bar`, `line`, `pie` ; déduit : dates → courbe, % qui font 100 → camembert, sinon barres | — |
| `make_chart` : ligne « Total » égale à la somme ; camembert de plus de 8 parts ; courbe d'un seul point | ligne retirée (barres, camembert) ; parts au-delà des 7 plus grandes regroupées en « Autres » ; barres. Dit sous le graphique (« Données remises en forme ») | — |

Chaque réparation est notée sur l'étape (`repairs`, journal d'audit, et « Arguments remis en forme » dans l'interface). Un argument qui reste faux après réparation est refusé, avec un message qui dit quoi corriger et donne un exemple d'appel.

**Appel répété** : le même appel avec les mêmes arguments reçoit une fois un rappel (« déjà appelé, utilise le résultat ») et l'outil est retiré pour le reste de la requête ; à la deuxième répétition, arrêt `loop`.

**Outils proposés selon la demande** (`agent.route`) : une demande de fichier ou de brouillon (présentation, document, compte rendu, tableur, mail…) qui ne demande aucune information extérieure (cherche, web, actualité, récent, prix, taux, une année, une URL…) ne reçoit pas `web_search` ni `read_page`. Raison mesurée sur l'endpoint réel : avec la recherche proposée, « fais une présentation de 4 diapositives sur le télétravail » déclenchait une recherche, puis la même recherche en boucle, et jamais le .pptx ; sans elle, le .pptx est créé du premier coup. Coût : sur les tours concernés, le bloc d'outils du prompt change, donc le préfixe mis en cache par vLLM n'est pas réutilisé pour ce tour (voir § 9). `Config.route_tools=False` le désactive. La règle s'applique aussi à toute demande accompagnée d'un document ou d'une image, et ne regarde que les mots de l'utilisateur, jamais la transcription : les dates et les prix d'une facture photographiée déclenchaient la recherche web, et le modèle réel appelait `read_page` sur la pièce jointe. **OCR seul** (« fais l'OCR », « extrais le texte », « transcris »…, sans autre demande) : la transcription de l'image est la réponse, sans deuxième génération (`backends.ocr_only`). Une demande d'OCR utilise une consigne stricte (le texte exact, sans description, 1 800 tokens, 6 000 caractères gardés). **PDF scannés** : les pages sans couche texte (moins de 40 caractères) sont rendues en image (pypdfium2, 1 568 px) et lues par le modèle de vision, 6 pages au plus par requête ; `read_file` rend ce texte, et dit explicitement quelles pages restent illisibles pour que le modèle n'invente rien. Mesure sur l'endpoint réel (lettre A4 connue) : PDF scanné 2 % de similarité (lettre inventée) → 98 % ; image 95 % → 98 % (en-tête désormais lu).

**Graphiques** (`make_chart`) : l'outil n'est proposé que si les mots de l'utilisateur contiennent un nom de graphique (graphique, graphe, courbe, diagramme, camembert, histogramme, visualiser, chart, graph, plot…), après retrait des expressions qui n'en sont pas (« charte graphique », « identité graphique », « courbe en J », « courbe d'apprentissage »). « secteurs » et « barres » seuls ne comptent pas. Sinon le prompt est identique, octet pour octet, à celui d'avant. Sur un tour de graphique, le bloc d'outils change (coût de cache, comme pour la recherche). Une demande de graphique garde `web_search`/`read_page` (« graphique de la population des 5 plus grandes villes » cherche d'abord) ; elle ne les perd que si le message porte lui-même les chiffres (au moins deux nombres) ou un document, et ne demande rien d'extérieur. Faux positifs acceptés pour l'offre de l'outil : « camembert » (le fromage), « explique ce qu'est un histogramme ». Le rappel et le remplacement ci-dessous, eux, n'ont lieu que pour une demande claire : un verbe d'action près du nom (« fais / trace / montre / refais-le en courbe / make / draw / plot ») ou des chiffres dans le message, et jamais si un fichier ou un brouillon a été produit dans le tour. Une demande de graphique à laquelle le modèle répond en texte reçoit **un** rappel (`NO_CHART_NUDGE`, même budget que le rappel de fichier) ; il indique, pour une reprise (« refais-le en courbe »), que les données sont dans le mémo du tour précédent (`history.memo` y garde 400 caractères des données du graphique) et le type demandé. Une réponse qui présente encore un graphique inexistant (« Voici la courbe : ») est remplacée par une phrase qui le dit.

**Images du web** : les moteurs rattachent une image à un résultat quand ils en ont une (Wikipédia : `prop=pageimages` dans la même requête, licence libre seulement ; Brave et SearXNG : leur vignette) ; `read_page` prend l'`og:image`, puis `twitter:image`, puis une grande image de l'article, et refuse logos, icônes, SVG. L'URL d'une image n'est **jamais** donnée au modèle. Le choix se fait à la réponse (`backends.pick_web_images`) : seulement si la réponse a utilisé le web, 3 au plus, une par page et par domaine, pages lues d'abord, et le titre de la page doit partager un mot avec la réponse **et** la demande ; sinon aucune image.

**Réponse coupée** : si la dernière génération s'arrête sur `finish_reason = "length"`, la raison d'arrêt est `length` (et non `answer`) ; la réponse est gardée et marquée « [réponse interrompue] » dans l'historique.

**Texte en boucle** (`llm.find_loop`) : pendant le flux, toutes les 48 nouvelles lettres, le harnais regarde si la fin du texte répète un même motif exact (mot, ligne, paragraphe) au moins 3 fois et sur au moins 400 caractères (3 200 si le motif n'a ni lettre ni chiffre : espaces, tirets, lignes de tableau vides). Si oui, il ferme la connexion : vLLM annule la requête et le GPU s'arrête au lieu de tourner jusqu'à `max_tokens`. Une seule copie du motif est gardée, la raison d'arrêt devient `repetition`, l'interface affiche « Bird se répétait : réponse arrêtée net » avec « Relancer », et la réponse est marquée interrompue dans l'historique. Une boucle pendant la réflexion, sans réponse, donne un message qui le dit. Mesure sur les 264 000 réponses longues du jeu d'entraînement (`out/pool_all`) : 58 signalées, toutes dégénérées (base64 répété, balises d'appel d'outil à l'infini, une formule recopiée) sauf un modèle de facture JSON avec plus de 3 000 caractères de lignes vides identiques.

**Outils de fiches et pré-appel** (`birds/harness/intents.py`) : Bird S 4B n'a jamais été entraîné sur `find_places`, `find_company`, `convert_currency` et `get_weather`. Le harnais lit donc les mots de l'utilisateur : quand il est sûr (« restaurants près de la gare de Lyon », un SIREN valide, « 1 200 dollars en euros »), il fait l'appel lui-même avant la première génération, par le même chemin qu'un appel du modèle (validation, garde-fous, détection d'injection) ; l'étape porte `info.auto` (« automatique » dans l'interface). Quand il n'a qu'un indice (« et des hôtels près de là ? »), l'outil est seulement proposé. Sinon les trois outils sont retirés : un tour ordinaire garde le bloc d'outils d'entraînement octet pour octet (cache de préfixe intact). Ils sont petits (au plus trois arguments plats) et placés après les outils entraînés. Pour une demande de rendez-vous datée sans besoin web, le harnais retire la recherche et ajoute au message une note qui donne le jour exact résolu (le modèle réel avait écrit « dimanche 25 décembre » pour un vendredi). Mesures réelles et détails : `docs/WEB.md`, « Résultats enrichis ».

**Météo et horloge** : « météo à Lyon demain », « il va pleuvoir à Nantes ? », « weather in London tomorrow » sont pré-appelés (`intents.weather` : lieu et jour lus dans les mots de l'utilisateur ; « la météo des marchés », « temps de réponse », « quel temps de livraison », « il pleut des bugs en production », « le parapluie de garantie », « le projet Météo », « weather station » ne déclenchent rien : « temps de <nom> » et « quel temps faut-il » ne sont jamais une demande, « il pleut/neige » exige à/au/en/sur, « parapluie » et « météo » pris dans un groupe nominal ne comptent pas ; sans lieu, ou avec un lieu en minuscules qui n'est ni une ville de la table ni un repère nommé (« le salon de Lyon »), l'outil est seulement proposé). Côté horloge, « la réunion » est une réunion, pas l'île (seuls « île de la Réunion », « à la Réunion », « La Réunion », « Réunion island » la nomment), et « réunion/visio/call … entre » ne demande un créneau qu'entre deux villes nommées (« entre Londres et Singapour »), jamais « entre 10h et 11h » ; « point » seul n'est pas une réunion. `get_weather` géocode la ville la plus importante de ce nom, interroge MET Norway, et le web est retiré même pour « aujourd'hui » : l'outil a la réponse. L'horloge (« quelle heure est-il à New York », « décalage horaire avec Tokyo », « créneau commun Paris Montréal Singapour ») n'est **pas un outil** : `birds/harness/clock.py` calcule les heures et le créneau sans réseau (table ville → fuseau IANA, ~190 villes et ~75 pays FR/EN ; heures de bureau 9 h–18 h lun.–ven., au quart d'heure près pour Bombay ou Terre-Neuve ; heure d'été par les vrais instants), la fiche part dans `run.widgets` et le harnais ajoute au message une note avec les chiffres exacts, le web retiré : le modèle écrit une phrase. Une ville absente de la table n'est géocodée que pour connaître son pays ; le fuseau vient toujours de la table (pays à un seul fuseau, France métropolitaine), jamais des coordonnées. Le fuseau de l'utilisateur est celui du navigateur (`tz`), Europe/Paris sinon. Banc : `scripts/trigger_bench.py` (familles weather et clock, oui/non).

**Relances courtes** (`birds/harness/followup.py`) : après une fiche météo, lieux, devises, entreprise, horloge ou un graphique, « et à Lyon ? », « et demain ? », « et en livres ? », « et Tokyo ? », « et des restaurants autour ? », « en camembert plutôt » refont le même appel avec la seule case changée, sans passer par le modèle. Le contexte vient du **mémo écrit par le serveur** à la fin du tour précédent (`contexte : get_weather {"place": "Lyon", "day": "demain"}`), jamais du texte du modèle : seul un mémo qui termine le dernier message de l'assistant est lu (le serveur retire les mémos que le modèle imite), l'outil doit être l'un des cinq connus, les clés connues et les valeurs courtes et sans balisage (sinon le contexte est ignoré en entier). Une relance n'est faite que de cases (lieu nommé, jour, devise, montant, type de lieu, type de graphique) et de mots outils : « et à Lyon, combien de salariés ? », « et Paul ? », « et maintenant rédige le mail » ne sont pas des relances. Banc : famille `followups` (21 relances, 44 demandes de bureau × 7 contextes sans aucun déclenchement).

**Images demandées** : « montre-moi une photo de la tour Eiffel », « à quoi ressemble le Mont-Saint-Michel », « show me a picture of a koala » : le harnais lance lui-même `web_search` sur le sujet (le web reste proposé), ajoute une note qui dit que les images correspondantes, s'il y en a, s'affichent sous la réponse, et l'application montre jusqu'à 4 images dont le **titre ou l'adresse de la page nomme le sujet demandé** (tous ses mots, ou tous moins un au-delà de deux) : « Gustave Eiffel » n'est jamais montré pour « tour Eiffel », et la réponse du modèle ne compte pas. Jamais sur « image de marque », « l'image de l'entreprise », « droit à l'image », une image à générer, insérer ou décrire, une personne ou « les photos de la soirée ».

**Questions sur les graphiques** : « comment faire un graphique dans Excel ? », « tuto pour faire une courbe », « quel graphique choisir ? », « dans quel cas utiliser un camembert ? » ne proposent pas `make_chart` et la réponse n'est jamais remplacée par « je n'ai pas pu afficher le graphique » (`chart_howto`). Les chiffres de l'utilisateur, ou un verbe d'action en tête (« fais un graphique… et explique la tendance »), en refont une demande.

## 3. Les garde-fous, et ce qu'ils ne couvrent pas

**Images du web** (`/api/img`, `birds/web/server.py`) : le navigateur ne contacte jamais un autre hôte. Le serveur ne sert que des URL qu'il a lui-même signées (HMAC, 7 jours) : ce n'est pas un proxy ouvert. Chaque redirection passe par `guard.check_url` (même politique que `read_page`, IP épinglée), aucun en-tête du navigateur n'est transmis (ni cookie, ni Referer, ni Authorization), le pot à cookies est vidé. Délai total de 16 s pour tout le téléchargement (connexion, redirections, en-têtes et corps) : les délais de httpx valent pour chaque lecture, donc un serveur qui envoie ses en-têtes octet par octet tiendrait la requête des heures ; un minuteur coupe les sockets ouvertes à l'échéance (`guard._Deadline`, même règle pour `read_page`, 2 × `http_timeout`). PNG, JPEG, WebP ou GIF vérifiés sur les premiers octets, 2 Mo au plus (refusé, pas tronqué), 16 Mpx et 8 000 px au plus, 3 décodages à la fois, JPEG décodé à échelle réduite et aucune copie pleine taille (≈ 70 Mo de mémoire au pire au lieu de 300) ; réencodage en WebP 640 px (métadonnées et contenus cachés supprimés). La CSP est inchangée.

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

Énergie : `energy_wh` vaut `null` tant qu'il n'y a ni mesure, ni étalonnage, ni valeurs par token configurées. **Aucune estimation n'est inventée** : chacune dit sa méthode (`energy_method`) et sa base (`energy_basis`).

- `measured` : puissance du GPU relevée par `nvidia-smi` pendant les générations (client local, ou `measure_gpu=True` si le serveur tourne sur la même machine). C'est la consommation du GPU entier, hors processeur et reste de la machine.
- `estimated`, `calibration` : l'exploitant fixe `wh_per_1k_tokens` ; le bilan porte la mention « estimated » et la source de l'étalonnage.
- `estimated`, `tokens` (par défaut dans l'application web, qui fournit `wh_per_1k_in` / `wh_per_1k_out`) : tokens lus non cachés × Wh par 1 000 + tokens écrits × Wh par 1 000, avec une fourchette basse et haute ; valeurs et sources dans `birds/web/settings.py`, méthode dans docs/WEB.md. Les tokens du cache de préfixe (`cached_tokens`) ne sont pas comptés.
- `estimated`, `power_time` : seulement si `energy_method="power_time"` ; puissance nominale × durée des générations × PUE, une borne haute grossière.

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

### Graphiques et images (22/11/2026, endpoint réel, 15 requêtes)

| # | Demande | Résultat |
| --- | --- | --- |
| 1 | « Fais un graphique en barres du CA 2025 par trimestre : T1 120 k€… » | `make_chart` au 2e essai : le 1er avait `rows` en texte cassé (`'["T1", 120],\n"T2", 135],…'`), réparé depuis par la coercition. Barres, 4 valeurs exactes, unité k€, source « votre message », pas de recherche. 195 s (réveil du GPU compris). |
| 2 | « Trace la courbe des ventes : janvier 12, février 15,5… » | 1er essai : courbe, 15,5 lu, 4 points (6,1 s). |
| 3 | « Fais un camembert de la répartition du budget : loyer 40 %… » | 1er essai : camembert, %, 3 parts = 100 (5,8 s). |
| 4 | « Compare en graphique 2024 et 2025 : T1 10 et 12… » | 1er essai : 2 séries « 2024 » / « 2025 », 6 valeurs exactes (6,8 s). |
| 5 | CSV joint + « fais un graphique des montants par poste » | `read_file` puis `make_chart`, 4 montants exacts, source « fichier », pas d'outil web (7,6 s). |
| 6 | Suite de 1 : « refais-le en courbe » | **Échec** : aucun appel ; la réponse disait « Voici la courbe du CA 2025 par trimestre : » sans graphique, même après le rappel. Corrigé côté honnêteté (la réponse dit maintenant qu'aucun graphique n'a été affiché) et rappel enrichi (mémo + type) ; nouvel essai : toujours aucun appel. Reste à traiter (données d'entraînement de reprise, ou reprise déterministe depuis le mémo). |
| 7 | « Make a bar chart of website visits: Mon 120… » | 2e essai (1er : `rows` sans crochets extérieurs, réparé depuis). Valeurs exactes, réponse en anglais ; la réponse relistait les chiffres sous le graphique (consigne du résultat renforcée). |
| 8 | « Explique ce qu'est un histogramme en statistiques. » | Réponse en texte, aucun appel, pas de rappel (2,5 s). |
| 9 | « Fais un tableur du budget : loyer 1200, salaires 5400. » | `make_sheet`, `make_chart` non proposé (prompt inchangé). |
| 10, 11, 13 | recherches (Marie Curie, TVA Belgique, prix de l'électricité + graphique) | Non concluant : Wikipédia répondait 429 à l'adresse de sortie de l'environnement d'essai (vérifié hors modèle). Les réponses le disent ; #13 a refusé d'inventer des chiffres et n'a pas fait de graphique. |
| 12 | « Lis https://fr.wikipedia.org/wiki/Tour_Eiffel et résume-la. » | `read_page`, 1 image (og:image de la page) créditée « Tour Eiffel — Wikipédia [1], fr.wikipedia.org » ; `/api/img` : 200, WebP, 24 Ko (339 Ko en amont). Vérifié dans Chromium : image chargée, aucune requête vers un autre hôte, aucune violation CSP. |

Bilan : barres, courbe, camembert, deux séries et données d'un fichier joint justes (5/5 sur #1–#4 et #7, toutes en 2 générations au plus) ; les formes de `rows` ratées étaient du texte JSON, pas une autre forme de données. Reprise « refais-le » : non résolue.

## 8. Ce qui reste à vérifier

- Graphiques : la reprise « refais-le en courbe » ne déclenche pas `make_chart` sur l'endpoint réel (§ 10). Les images de résultats de recherche (Wikipédia `pageimages`) n'ont pas pu être vérifiées en réel (429 depuis l'environnement d'essai) ; seules celles des pages lues l'ont été. Les licences des images ne sont vérifiées que par `pilicense=free` de Wikipédia ; une `og:image` peut être hors sujet ou promotionnelle.
- Essais réels faits (§ 9 et § 10), mais sur quelques dizaines de requêtes seulement. Le comportement face à une page piégée (injection) n'a pas été testé en réel : aucune page piégée n'a été hébergée.
- La ligne d'avertissement placée devant les résultats d'outils n'existe pas dans les données d'entraînement actuelles (`birds/sources/guardrails.py`). Il faut soit l'y ajouter, soit vérifier qu'elle ne dégrade pas les réponses.
- Le client local (`LocalClient`) et la mesure `nvidia-smi` n'ont pas été exécutés sur GPU.
- Les serveurs (llama.cpp, vLLM, Ollama) n'ont pas été testés en vrai ; seul le format de la requête l'est.

## 11. Mode Agent : une petite équipe autour d'un livrable

Un modèle de 4 milliards de paramètres fait bien une tâche courte et typée, mal un long plan libre. Le mode Agent
découpe donc une demande lourde en générations courtes, en parallèle sur le même endpoint (vLLM les regroupe dans un
même lot), et confie le jugement au code. Modules : `birds/harness/crew.py` (décision, recettes, orchestration),
`crew_checks.py` (vérifications, sans modèle), `crew_tools.py` (outils virtuels et consignes), `birds/web/crew_web.py`
(événements SSE, démo), `static/agents.js` et `agents.css` (« l'équipe au travail »).

```
décision (code) -> brief (0 à 3 spécialistes en parallèle, vérifiés en code) -> 2 versions en parallèle (un seul outil)
-> vérificateur (code) -> au plus 1 correction ciblée -> l'outil s'exécute une fois via Agent._call -> réponse écrite par le code
```

**Quand.** Le réglage « Agent » du compositeur (Auto par défaut, Activé, Désactivé, gardé dans le navigateur) part
dans `ChatRequest.agent`. `crew.decide()` ne regarde que les mots de l'utilisateur (le texte collé compte pour sa
taille, ses offres et sa liste de présents, jamais pour l'intention) et ne fait aucun appel au modèle.

| Recette           | Signaux                                            | Spécialistes                                   | Auto |
| ----------------- | -------------------------------------------------- | ---------------------------------------------- | ---- |
| `deck_research`   | présentation, web, chiffres                        | recherche (0 appel), 2 lecteurs `record_facts` | oui  |
| `compare_write`   | texte collé, comparer, ≥ 2 offres, mail ou document | lecteur `record_table` + analyste `cost_model` | oui  |
| `minutes_actions` | texte collé avec présents, compte rendu / actions  | lecteur `record_actions` (+ 1 reprise)         | oui  |
| `doc_research`    | document, web, chiffres ou étude du marché         | comme `deck_research`, extraits aux rédacteurs | non  |
| `sheet_pasted`    | tableur, texte collé, chiffres                     | lecteur `record_table`, 1 version              | non  |

En Auto, il faut en plus une demande non simple (salutation, question « comment », mail court, retouche d'un fichier
et image seule sont exclus) et deux signaux de charge parmi : plusieurs étapes, chiffres avec un fichier, au moins 2
documents, web puis livrable, texte collé long ou structuré (liste de présents). Activé lance la recette même si son
drapeau Auto est éteint ; sans recette, la recette `generic` (un plan court en JSON, recherches éventuelles, 2
versions) ; sans livrable, le mode simple répond et la puce dit « Rien à répartir ». Désactivé : `Agent.run`, inchangé.

**Vérifications en code.** Un chiffre d'une version n'est gardé que s'il figure dans la demande, le texte collé, un
fait vérifié ou un calcul du harnais, ou s'il en est la différence ou le rapport (« 14,8 points » = 19 − 4,2) ; les
puces qui portent un chiffre sans source sont retirées avant la création du fichier. Un fait relevé sur une page doit
avoir sa valeur et son année dans l'extrait, et sa citation dedans. Un responsable d'action doit être dans la liste des
présents ET sur la ligne citée ; une échéance absente de la ligne est vidée, jamais devinée ; le tableau des actions
du compte rendu est écrit par le code. Les coûts sont calculés par le harnais à partir de la description typée de
l'analyste (`cost_model`, sans expression libre), puis le verdict (offre conforme la moins chère par an). Note :
`score = 2 × points couverts + 1,5 × faits obligatoires + structure − 1 par chiffre sans source`, les versions sans
chiffre inventé passent toujours devant. Ce qui reste douteux est dit dans la réponse (« À vérifier »).

**Études, veille, benchmark (`doc_research`).** « étude comparative », « étude de marché », « dossier / note de
veille », « veille concurrentielle », « benchmark », « livre blanc » sont des livrables document (jamais « étude » ou
« dossier » seuls). Une étude *du marché* (« du marché », « concurrents », « comparatif », « état de l'art », « avec
des sources »…) demande le web, sauf si l'objet est à l'utilisateur (« benchmark de nos fournisseurs », « à partir de
ces liens ») ou si rien n'est demandé (« range ce dossier de veille », « qu'est-ce qu'un benchmark ? »). Banc :
famille `agent_study` de `scripts/trigger_bench.py` (10 oui, 20 demandes de bureau avec un mot d'étude qui ne
déclenchent rien, même drapeau Auto allumé).

**Mesure live (27/11/2026, Bird S 4B, recherche SearXNG, `scripts/agent_study_eval.py`).** 4 demandes d'étude
(comparatif CRM, veille IA générative, rapport transition énergétique, benchmark visioconférence), Mode Agent forcé
contre mode simple :

| | Mode Agent | Mode simple |
|---|---|---|
| Livrable Word produit | 3/4 (le 4ᵉ s'est arrêté sur une demande de confirmation) | 0/4 (réponse dans le chat) |
| Sections du document | 10 à 16 | — |
| Citations numérotées + section Sources | oui (3/3) | non |
| Temps total | 29 à 58 s | 14 à 26 s |

Décision : `doc_research` passe en Auto. Une première mesure du même jour, recherche limitée à Wikipédia, n'était pas
concluante (Wikipédia refusait les recherches parallèles : HTTP 429).

**Qualité de l'équipe.** La recherche prend le premier résultat de chaque requête à tour de rôle et lit une page par
site d'abord (2 à 3 sources distinctes, pas trois pages d'un même site) ; si moins de 2 pages donnent un extrait et
qu'il reste du temps, elle lit jusqu'à 2 pages d'autres sites (0 génération, lecture une à une). Pour un document,
les rédacteurs reçoivent aussi les extraits des pages (1,5 Ko chacun) ; une page sans chiffre vérifié n'est une
source que si elle dit assez (300 caractères). Chaque phrase qui cite [n] est vérifiée contre la page n : un chiffre
qui n'y est pas mais figure dans une autre page lue reçoit le bon numéro (« citation corrigée »), une phrase dont la
plupart des mots manquent à la page citée est dite dans « À vérifier » (pénalité 0,25, au plus 1), et le document
doit citer chaque chiffre et chaque source. Quand les deux versions sont propres, la version retenue est complétée
par les sections (ou diapositives) de l'autre qui portent un fait vérifié ou un point manquant, ou le tableau
comparatif absent ; la fusion n'est gardée que si sa note est au moins égale, sans chiffre non sourcé de plus. La
voie de l'autre version affiche « reprise en partie ». La réponse se termine par « Ce que l'équipe a fait »
(recherches, pages lues et sites retenus, chiffres vérifiés et écartés, versions, fusion, corrections), écrit par le
code à partir de compteurs, jamais par le modèle. Aucun appel de plus : 7 générations au plus, fin à t0 + 240 s
(fonction Vercel : 300 s).

**Drapeau Auto de `doc_research` : pas encore basculé.** Protocole : `scripts/agent_study_eval.py` (serveur réel,
4 demandes d'étude, Mode Agent Activé contre Désactivé, au plus 25 générations en tout), noté à la main sur 4 critères
de 0 à 2 : fidélité (aucun chiffre ni affirmation absent des sources lues ; un chiffre inventé donne 0), complétude
(tableau, recommandation, tendances ou risques demandés), sources (au moins 2 sources distinctes citées [n] et
listées), structure (sections titrées, tableau quand une comparaison est demandée). Le drapeau ne passe à « oui » que
si l'équipe gagne d'au moins 1 point sur 8 en moyenne, sans jamais perdre en fidélité, en moins de 240 s. Le
23/11/2026, l'endpoint a répondu 503 puis « endpoint in error » pendant plus de 45 minutes : 0 génération faite,
aucun chiffre mesuré, le drapeau reste « non » (Activé lance la recette ; Auto reste en mode simple pour ces demandes,
d'où les 3 « MISS » de la famille `agent` du banc).

**Limites.** 4 générations en même temps, 7 par demande (5 pour `generic`), 2 versions, 3 pages lues (4 Ko d'extrait
chacune, 12 Ko au total), fin à t0 + 240 s (brief 90 s, versions avant t0 + 190 s, correction seulement s'il reste
plus de 45 s, 20 s réservées au fichier). Si le réveil de l'endpoint a pris plus de 120 s : une seule version, pas de
correction. Les pages sont lues une à une (l'analyse HTML a fait planter le processus en parallèle) ; les recherches
partent en parallèle.

**Repli.** Aucun fait vérifié, aucune version valide ou une exception : `Agent.run` reprend avec le brief (faits,
sources, actions) s'il reste du temps, sinon Bird dit honnêtement qu'il ne peut pas plutôt que d'inventer des
chiffres. « Revenir au mode simple » arrête l'équipe et renvoie la même demande avec `agent: "off"`, pour cette
demande seulement.

**Confirmation.** Seule l'étape de création peut s'arrêter sur une confirmation (`guard.gate`). Une page signalée
n'entache la demande que si son texte a été donné à un modèle. Le jeton signé porte `{k: "crew", tool, args, sources,
caveats, usage, answer_ctx, carry}` (24 Ko au plus) ; à la reprise, rien n'est régénéré.

**Énergie.** Les jetons sont additionnés exactement, et l'estimation par défaut part de ces jetons. Pour l'estimation
puissance × temps (sur demande seulement), le temps GPU est l'union des intervalles des appels
(`meter.report(busy_seconds_override=…)`), pas leur somme : des appels en parallèle partagent le même lot. L'événement `usage` gagne `agents` (par rôle), `gpu_seconds_union` et `busy_seconds_sum` (borne haute).

**Événements SSE** (en plus des existants) : `agent_start {recipe, reason, mode, forced, lanes[{id, role, label,
group}], budget}`, `agent_step {id, role, phase, status, label, progress, tokens, seconds, detail, score, chosen}`,
`agent_done {recipe, ok, chosen, calls, seconds, gpu_seconds_union, caveats, reason, fallback}`. Les étapes d'outil de
l'équipe portent `agent` (l'identifiant de la voie) et s'affichent dans leur voie.

**Démo.** `scripts/serve.py --demo` joue une équipe scriptée sur « présentation … chiffres … depuis 2019 »,
étiquetée « scénario de démonstration ». Test navigateur : `node tests/e2e/agent_mode.spec.js` (serveur démo sur
le port 9071 ; iPhone 14 et 1440 × 900, clair et sombre).

**Essais réels (22/11/2026, 8 générations).** Présentation « télétravail depuis 2019 » : 4 générations, 21,6 s,
union GPU 19,6 s contre 33,8 s de somme ; 2 faits vérifiés sur 1 page Wikipédia (2 recherches sur 3 en 429). Comparaison
des 3 offres de maintenance + mail : 4 générations, 26,7 s, verdict juste (InfoServ Rhône, 19 400 € la 1re année, seule
offre sous 4 h et dans le budget), union 26,6 s contre 51,1 s. Restent à faire : l'évaluation à l'aveugle de la
section 9 de la spécification (12 tâches, 60 requêtes) qui doit confirmer ou éteindre chaque drapeau Auto ; les
coûts d'une offre plafonnée (« 16 € par poste au-delà de 90 ») restent mal décrits par l'analyste (15 672 € au lieu
de 15 480 €), sans changer le verdict ; les touches de cache de préfixe ne sont pas vérifiables (l'endpoint ne
renvoie pas `cached_tokens`).
### 11 bis. Mode Agent, vague 2 : plan modifiable, consignes, vérifications, tâches longues, livrables

Modules : `birds/harness/crew_plan.py` (plan typé, consignes typées, file des consignes), `crew_canvas.py` (adaptateur
Canevas), `crew_checks.ledger` / `renumber` / `autocite` / `near_duplicate`, `birds/web/crew_web.py` (déroulé web),
`static/agents.js` (carte de plan, activité, carte « Vérifications faites », « Livrables »).

**Plan avant lancement.** L'application envoie `agent_flow: "plan"` : quand `crew.decide()` choisit une équipe, le
serveur ne génère rien et renvoie `agent_plan {plan, token, auto_start, mode, reason}` (jeton signé, lié à la
conversation). Le plan est construit en code : étapes de la recette, livrable, public (Grand public / Décideurs /
Experts), longueur (Courte / Standard / Approfondie), nombre de diapositives (3 à 12), sections à couvrir (8 au plus,
80 caractères), sites à privilégier ou exclure (noms de domaine validés), accent (100 caractères). « Modifier » ne
change que ces champs ; le serveur revalide chaque valeur (`crew_plan.apply_edits`) et les rend dans le brief commun
par des gabarits (« Public : décideurs (l'essentiel d'abord…) »), jamais le texte brut comme instruction. Les
sections deviennent des points vérifiés comme les autres. En Auto, tout plan part après 5 s (compte à rebours
visible, « Modifier » l'arrête) : Auto ne bloque jamais, comme avant la carte de plan ; la confiance (haute à partir
de 3 signaux de charge) est notée sur le plan, pas dans le délai. Activé attend « Lancer » ; « Répondre sans
l'équipe » renvoie la demande en mode simple. Un client API sans `agent_flow` lance l'équipe aussitôt, comme avant.

**Consignes en cours de route.** « Ajouter une consigne » : `POST /api/agent/note {run, kind, value}` avec un type
parmi exclure un site, privilégier un site, public, longueur, ajouter une section, mettre l'accent sur. La consigne
part dans la file de la voie (`crew_plan.REGISTRY`, en mémoire du processus, 15 min au plus) et l'équipe la prend
entre deux générations (avant la recherche, avant la lecture, avant les versions, avant la correction) : un site
exclu n'est plus lu, et une page déjà lue sort du brief (faits, extraits, citations) ; une consigne d'écriture
arrivée après les versions passe par la correction si elle peut encore tourner ; sinon, et toujours au moment du
fichier, elle est dite « trop tard pour ce livrable ». Chaque consigne est acquittée (`agent_note {id, status:
applied|late, stage}`). Sur Vercel, une autre instance peut recevoir la consigne : `delivered: false`, le navigateur
la joint à la tranche suivante (`agent_notes`). « Arrêter » reste visible ; l'arrêt efface le point de reprise.

**Activité en direct.** Repliée, une ligne au présent (« Lit 3 pages · 0:42 », « Rédige 2 versions en
parallèle »), tirée des voies et des étapes d'outils, jamais du modèle ; dépliée, le plan avec l'étape en cours, les
sous-questions de la recherche, les sites lus en puces qui arrivent, les voies, les consignes. À la fin, une ligne
au passé (« Équipe : 5 agents · 3 pages lues · 14 chiffres vérifiés · 2 versions · 48 s ») et « Ce que l'équipe a
fait » replié.

**« Vérifications faites ».** `agent_checks` : chaque chiffre du livrable, titres et intertitres compris, avec son
origine (la page qu'il cite et la ligne de cette page, votre texte, un calcul du harnais), les passages retirés faute
de source, les chiffres à relire, les actions d'un compte rendu vérifiées ligne par ligne. « Vérifié » demande le
chiffre écrit tel quel sur la page (`on_page`) : un chiffre seulement déduit de deux autres (37 depuis 40 et 3) est
« à vérifier » (`why: derived`), sauf s'il vient d'un calcul du harnais ; une phrase qui cite [n] est jugée sur la
page n seule (`why: cited` si n ne contient pas le chiffre, jamais une autre page à sa place) ; `why: claim` quand la
page contient le chiffre mais pas l'essentiel de la phrase. Un chiffre non sourcé dans un titre en est retiré
(`drop_figures`), comme d'une puce. Calculé par `crew_checks.ledger` à partir des contrôles déjà faits, sans modèle.

**Qualité de l'équipe.** La recherche est planifiée par le modèle : une génération courte (`plan_search`, 260
jetons) découpe la demande en 3 sous-questions avec chacune sa requête ; le code garde une requête de 2 à 10 mots,
sans URL ni opérateur, qui reprend un mot de la demande, sans doublon, et complète avec les requêtes fixes. Pages
lues : sites privilégiés, puis sources officielles, puis l'ordre du moteur ; forums, réseaux sociaux et vidéo en
dernier ; un texte quasi identique sur un autre site (Jaccard des 6-grammes ≥ 0,7) compte une fois. Citations
cohérentes : numérotées dans l'ordre où le livrable les cite (le fichier ne liste que les sources citées), et un
chiffre écrit sans [n] reçoit le numéro de la page où il est écrit tel quel (`autocite` ; jamais pour un chiffre
seulement déductible de la page ; vos propres chiffres et les tableaux restent tels quels).

**Tâches longues en tranches.** Après le brief, si l'écriture ne tient plus dans la requête (moins de 110 s) ou si le
plan est « Approfondie » (5 pages lues au lieu de 3, 20 Ko d'extraits), le serveur s'arrête et envoie
`agent_slice {token, auto: true}` : état signé (brief, traces, usage, voies, consignes), porté par le navigateur,
qui relance aussitôt avec `agent_slice`. Rien n'est relu ni régénéré ; le budget de générations est cumulé, temps et
énergie aussi. Un point de reprise part après le brief : `auto: false` quand l'écriture suit dans la même requête,
l'état de la tranche suivante lui-même pour une tâche longue. Il est gardé avec la conversation (avec son `exp`), et
après un rechargement ou une coupure « Reprendre la tâche » repart de la rédaction (jeton valable 15 min) ; il est
effacé à la fin réussie de la tâche, à l'arrêt ou à expiration. Un jeton de plan ou de tranche ne tourne qu'une fois
à la fois et plus après une fin normale (409 `agent_state_used`, en mémoire du processus : au mieux sur plusieurs
instances) ; une requête coupée le libère pour « Reprendre ». Fin de tâche onglet caché : « ✓ » dans le titre, et une notification si l'utilisateur l'a autorisée (« M'avertir
à la fin »).

**Agents qui construisent.** Pour une présentation ou un document, si le Canevas (`birds.canvas`) est installé et
`BIRD_CREW_CANVAS` ≠ 0, le livrable vérifié est écrit dans son modèle de document section par section
(`{"type": "canvas", "phase": "stream"|"final"}`, fonctions publiques `convert.from_tool`, `turn.finish_doc`,
`turn.new_aid`), et le fichier est créé comme avant. Sans Canevas (`BIRD_CREW_CANVAS=0` ou module absent), le chemin du fichier
reste seul. `agent_deliverable` décrit le livrable ; « Livrables » (barre du haut) liste tous les fichiers de la
conversation, du plus récent au plus ancien, avec « Voir dans la conversation » et le téléchargement.

**Mesure live (27/11/2026, Bird S 4B, SearXNG, `scripts/agent_study_eval.py --set=all`, Mode Agent forcé, même
client, avant = commit `d2899c1`, après = cette branche ; 1 passage par demande, une confirmation acceptée comme le
ferait l'utilisateur).** Livrable produit, sections (hors Sources), citations valides ([n] présents et tous dans la
liste des sources), phrases chiffrées citées ou tirées du texte collé, temps total :

| Demande                        | Avant                                   | Après                            |
| ------------------------------ | --------------------------------------- | -------------------------------- |
| Étude comparative CRM          | oui · 4 sections · valides · 1/2 · 33 s | oui · 5 · valides · 1/1 · 38 s   |
| Veille IA générative           | oui · 4 · **non** · 3/3 · 35 s          | oui · 5 · valides · 5/5 · 50 s   |
| Rapport transition énergétique | oui · 5 · valides · 4/4 · 33 s          | oui · 5 · valides · 6/6 · 30 s ¹ |
| Benchmark visioconférence      | oui · 5 · valides · 0/0 · 38 s          | oui · 7 · valides · 0/0 · 44 s ¹ |
| Diapos télétravail             | oui · 6 · valides · 4/4 · 24 s          | oui · 6 · valides · 4/4 · 28 s   |
| Diapos véhicules électriques   | oui · 6 · valides · 2/2 · 28 s          | oui · 6 · valides · 3/3 · 33 s   |
| 3 offres + mail                | oui · 1 · valides · 2/3 · 12 s          | oui · 1 · valides · 3/4 · 12 s   |
| Compte rendu + actions         | oui · 9 · valides · 4/4 · 15 s          | oui · 6 · valides · 3/3 · 24 s   |

¹ Passage du code d'avant `autocite` (même recherche) : au second passage complet, SearXNG renvoyait 0 résultat
(« google cse : Suspended: too many requests », duckduckgo en timeout) pour ces 4 demandes, ce qui ne mesure pas
l'équipe.

Ce qui change : la veille IA générative avait des citations invalides et passe à valides ; les requêtes ne sont plus
la phrase de l'utilisateur plus « tendances » (« l'IA générative en entreprise en 2026 : tendances, chiffres, risques
tendances ») mais des sous-questions (« marché IA générative entreprise 2026 chiffres », « tendances IA générative
entreprise 2026 ») ; diapos véhicules électriques : 2 sources officielles au lieu d'1 ; la carte de vérification
compte 2 à 15 chiffres vérifiés par livrable, 0 retiré, 0 à vérifier. Coût : + 1 génération (le plan de recherche),

- 3 à 15 s sur les demandes recherchées. Le compte rendu est passé de 9 à 6 sections et de 15 à 24 s sur un passage
  unique : à confirmer sur plusieurs passages (la recette ne change pas, seule la variance du modèle joue). Le plan de
  recherche n'a pas toujours été valide (CRM, visioconférence : requêtes fixes gardées).

Essais du déroulé complet (même jour) : carte de plan puis « Lancer » avec une consigne « Ajouter une section : Ce qui
change pour les managers » envoyée 1 s après le départ : appliquée avant la lecture, le livrable a la section (le 4B
l'a déclinée sur 3 diapositives). Rapport « Approfondie » + « Décideurs » : 2 requêtes (tranche de recherche, puis
écriture), 110 s, 6 sections dont « Synthèse pour les décideurs » ; aucun [n] écrit par le modèle, d'où `autocite`
(test dédié ; pas de nouveau passage live après ce correctif, faute de recherche disponible).
Banc des déclenchements : 875/875 (inchangé, `crew.decide()` n'a pas bougé).

**Événements SSE (vague 2)** : `agent_plan`, `agent_note`, `agent_checks {verified_n, removed_n, review_n, items[{value,
sentence, status, origin, n, line, site}], actions, sources}`, `agent_slice {token, auto, slice, run}`,
`agent_deliverable {tool, title, file, parts, canvas}`, `canvas` (si Canevas) ; `agent_start` gagne `run`, `plan`,
`slice` ; `agent_step` du chercheur gagne `questions`.

**Tests.** `tests/test_crew_w2.py` (plan typé et retouches, consignes appliquées / trop tard, site exclu en cours de
route, plan de recherche validé, sources officielles et doublons, carte de vérification, tranches et reprise, Canevas
simulé et absent, déroulé web complet, jetons falsifiés refusés), `tests/js/agents.test.mjs`, et
`scripts/agent_ui_smoke.js wave2 autoStart` (démo, 360 et 1280 px, clair et sombre).

## 12. Routeur piloté par le modèle

**Principe.** Avant la génération principale, Bird décide lui-même des modules du tour en **un appel court**
(≤ 80 jetons, température 0) : `{"modules":[{"tool":"get_weather","args":{"place":"Lyon","day":"demain"}}],
"agent":"off","needs_web":false}`. Une seule source de vérité, `birds/harness/catalog.py` : nom, ligne FR/EN, petit
schéma d'arguments et exemples de chaque module (météo, lieux, société, devises, horloge, événement, images,
graphique, et les indices bureautique / recherche / données). Le prompt est le catalogue (statique, en préfixe :
le cache de vLLM le réutilise), des exemples fixes, puis le tour : contexte du tour précédent (mémo du serveur,
jamais le texte du modèle), **indices** des analyseurs regex (qui peuvent se tromper) et les mots de l'utilisateur.
La sortie est contrainte par schéma quand l'endpoint le permet (`structured_outputs: {json}` sur vLLM ≥ 0.10,
détecté une fois par sonde et mis en cache), sinon réparée et validée. Chaque argument est vérifié
(`catalog.check_args`) et **ancré** : écrit dans les mots de l'utilisateur ou dans le contexte du tour précédent.

**Rôle des règles écrites à la main** (`intents.py`, `clock.py`, `when.py`) : indices dans le prompt ; **repli**
quand le routeur est absent, trop lent (budget 3 s, `BIRD_ROUTER_BUDGET_S`) ou illisible ; **veto** seulement pour
les familles de faux déclenchements connues du banc (« météo des marchés », « charte graphique », « image de
marque », « heures de pointe »…), et seulement si l'analyseur de la famille ne se déclenche pas lui-même.

**Réglage** `BIRD_ROUTER` : `model` (le routeur décide seul), `hybrid` (le routeur décide, et un appel sûr d'un
analyseur d'une famille que le routeur a laissée de côté est ajouté, sauf s'il ne vient que d'un texte collé), `regex` (aucun appel : comportement
d'avant), `auto` (défaut) = **`hybrid`** pour un endpoint distant, `regex` pour un client local ou scripté.
Journaux : métadonnées seulement (outils, noms d'arguments, durée, source, repli, veto), jamais le texte.
Le champ `agent` de la décision est mesuré mais ne pilote pas encore le mode Agent (qui reste `crew.decide`).

**Mesure réelle (27/11/2026, endpoint vLLM 0.32, Bird S 4B, `structured_outputs` détecté).**
`scripts/router_eval.py --per-class 15` : 389 appels, au plus 15 exemples tirés (graine 0) par famille du banc et
par classe oui/non ; l'hybride est noté sur le même appel. Résumé : `docs/measures/router-eval-2026-11-27.json`.

| Famille | n | routeur seul (exact. / préc. / rappel) | hybride | regex |
| --- | --- | --- | --- | --- |
| weather | 30 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 |
| maps | 22 | 0,955 / 1,000 / 0,933 | 0,955 / 1,000 / 0,933 | 0,955 / 1,000 / 0,933 |
| maps+ | 30 | 0,967 / 1,000 / 0,933 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 |
| company_fx | 30 | 0,933 / 0,933 / 0,933 | 0,967 / 0,938 / 1,000 | 1,000 / 1,000 / 1,000 |
| clock | 29 | 0,931 / 0,882 / 1,000 | 0,931 / 0,882 / 1,000 | 0,931 / 0,882 / 1,000 |
| events | 30 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 | 0,967 / 1,000 / 0,933 |
| images | 30 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 |
| charts | 21 | 0,952 / 1,000 / 0,933 | 0,952 / 1,000 / 0,933 | 0,762 / 1,000 / 0,667 |
| charts+ | 30 | 0,967 / 1,000 / 0,933 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 |
| chart_howto | 11 | 1,000 / – / – | 1,000 / – / – | 1,000 / – / – |
| followups | 30 | 0,933 / 1,000 / 0,867 | 0,933 / 1,000 / 0,867 | 1,000 / 1,000 / 1,000 |
| realistic | 30 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 | 1,000 / 1,000 / 1,000 |
| **modules (323)** | | **0,969** | **0,978** | **0,972** |
| agent | 11 | 1,000 / 1,000 / 1,000 | idem | 0,727 / 1,000 / 0,500 |
| office_agent | 30 | 0,867 / 0,824 / 0,933 | idem | 1,000 / 1,000 / 1,000 |
| agent_study | 25 | 0,640 / 0,526 / 1,000 | idem | 0,600 / – / 0,000 |

Latence d'un appel : **p50 0,67 s, p95 0,89 s** (≈ 830 jetons de prompt, ≈ 50 de sortie). JSON invalide : 0,3 %
(1 sur 389, repli sur les analyseurs). Veto appliqué 11 fois. Le routeur seul a raison là où les regex se trompent
18 fois, l'inverse 19 fois : les erreurs se compensent, d'où le choix de **`hybrid` par défaut** (0,978 contre
0,972 pour les regex et 0,969 pour le routeur seul sur les familles de modules, pour 0,67 s par tour). Erreurs
restantes du routeur : deux reprises (« et en yens » sans le montant, « et à New York ? » qui garde Tokyo), « trouve
un créneau pour une réunion à Lyon » pris pour l'horloge (regex aussi), « montre-moi sur une carte les agences de
Lyon, Marseille et Lille » manqué (regex aussi), et surtout `agent: "on"` pour des documents internes (« rapport
d'incident », « note de synthèse sur la réunion d'hier ») : 12 faux positifs sur 23 erreurs, raison pour laquelle le
champ `agent` ne pilote rien pour l'instant. Lecture franche : le banc a servi à régler les regex, il les avantage ;
la capacité du routeur à généraliser à des tournures nouvelles se mesure sur `eval.jsonl` de `build_tools_mix.py`
(gabarits retenus), pas encore fait en réel. Correctif trouvé pendant la mesure : la sonde de sortie structurée
demandait 16 jetons, vLLM 0.32 répond `{\n  "probe": …\n}` en 20 et la sonde concluait « non pris en charge »
(`PROBE_TOKENS = 40`).

**Dans l'application** (même jour, `scripts/serve.py` port 9335, `BIRD_ROUTER` par défaut, 360 px et 1 280 px, clair
et sombre, 8 tours) : « il fera quel temps demain du côté de Strasbourg ? », que les regex **ne voient pas**
(`hint_tools: []`), est routé vers `get_weather {place, day}` (0,85 à 1,16 s) et la fiche météo s'affiche ; « fais-moi
la météo des marchés » ne déclenche aucun module (`needs_web: true`, 0,51 à 0,55 s), Bird cherche et cite sa source.
Aucune requête vers un tiers, aucune erreur CSP, pas de défilement horizontal.

**Texte collé : le modèle n'est plus contredit par les regex (27/11/2026).** En `hybrid`, un appel d'analyseur d'une
famille que le routeur laissait de côté était toujours rajouté : « Résume ce mail : « … Météo à Lyon demain : pluie… »
» relançait la fiche météo que le modèle avait, à raison, écartée. Désormais, pour une tâche sur un texte fourni
(résume, corrige, traduis, reformule, analyse… suivi d'une citation ou de deux-points, `router.own_words`), seuls les
appels que les analyseurs trouvent **dans la consigne elle-même** sont rajoutés (`merge(model, base, own)`), et le
veto écarte un appel du routeur dont les arguments ne figurent que dans le texte collé (« only in the pasted text »).
Nouvelle famille `pasted` dans `router_data.py` (8 « non », 3 « oui » : une consigne qui demande aussi un module) ;
elle reste hors du banc des déclenchements, car les regex s'y trompent (connu, non corrigé côté regex).
Mesure réelle, même graine (`--per-class 15 --seed 0`, 400 appels, résumé `docs/measures/router-eval-2026-11-27-pasted.json`) :

| Jeu | routeur seul | hybride (nouveau) | hybride (ancien) | regex |
| --- | --- | --- | --- | --- |
| `pasted` (11) | 1,000 (0,545 avant le veto) | **1,000** | 0,273 | 0,273 |
| familles de modules hors `pasted` (323) | 0,966 | 0,975 | 0,975 | 0,972 |
| familles de modules (334) | 0,967 | **0,976** | 0,952 | 0,949 |

Hors texte collé, rien ne change (mêmes décisions ; écart de 0,003 avec la mesure précédente : une reprise « et en
livres ? » sans montant, bruit du tirage). Latence p50 0,64 s, p95 0,84 s ; JSON invalide 0,3 %.

**Légendes et tableaux (27/11/2026).** Vus dans l'application avec le routeur : « rédige la légende d'une photo de la
tour Eiffel » lançait une recherche d'images, « mets en forme ce tableau : Paris 12, Lyon 8, Marseille 5 » dessinait un
graphique. Six tournures (FR/EN) rejoignent le banc comme négatifs (`IMAGES_NO`, `CHART_NO2` : 872/875 → 878/881) et
`build_tools_mix.py` comme négatifs du routeur (gabarits `nt16`, `nt17`, `nte2`, `nte3`, plus `nt18` pour le texte
collé). En attendant l'entraînement, le veto connaît deux familles de plus : légende / texte alternatif pour les
images, tableau nommé sans mot de graphique pour `make_chart` (« tableau de bord » exclu). Réel, routeur sur les six
négatifs : 3 faux déclenchements avant, 0 après ; les deux positifs témoins restent servis.

**Ancrage des nombres et des types de lieux.** Un nombre est comparé en entier (`intents.parse_amount`), jamais comme
morceau d'un autre : 20 n'est plus « dans » « 2025 », ni « 202 » dans « 2021 » ; un SIREN doit être écrit d'un seul
tenant. Un type de lieu (`pharmacy`) n'est ancré que par ce même type dans les mots (« un restaurant » n'ancre plus
une pharmacie).

**Dans l'application** (même jour, port 9337, `BIRD_ROUTER` par défaut, 360 px et 1 280 px, clair et sombre, 12 tours) :
« mets en forme ce tableau : Paris 12, Lyon 8, Marseille 5 » donne un tableau, aucun graphique (veto `make_chart`) ;
« rédige la légende d'une photo de la tour Eiffel » donne une réponse écrite, aucune bande d'images (veto `images`) ;
« Résume ce mail : « … Météo à Lyon demain… » » donne le résumé sans fiche météo (`hint_tools` `get_weather`, non
rajouté). Aucun widget, aucune requête vers un tiers, aucune erreur CSP, pas de défilement horizontal.

### Apprentissage natif des modules

`scripts/build_tools_mix.py --out out/tools_mix` prépare (sans lancer) un jeu au format exact du mélange
d'entraînement (`birds/schema.py`, `train.jsonl` / `eval.jsonl` lus par `jobs/bird_job.py`) :

- `router` : le prompt exact du routeur (`router.messages`) et la décision en un seul tour assistant, positifs et
  **négatifs** (`{"modules":[]}` : faux déclenchements, demandes bureautiques, conversation) ; les indices sont ceux
  des analyseurs, parfois faux, parfois retirés, pour que le modèle apprenne à les corriger ;
- `tool_call_extra` : le prompt système de Bird, les outils (bloc entraîné puis `EXTRA_TOOLS`), la demande et l'appel
  natif de `get_weather` / `find_places` / `find_company` / `convert_currency` / `web_search` (images) / `make_chart` ;
- `eval.jsonl` : gabarits **retenus en entier** (12 %, jamais vus à l'entraînement) ; `bench_heldout.jsonl` : toutes
  les tournures du banc, exclues de `train` ; `stats.json`.

Sortie mesurée (graine 0, 8,5 s) : train 5 207 enregistrements (3 205 routeur dont 739 négatifs et 172 reprises,
2 002 appels natifs ; 86 % FR), eval 517, bench retenu 875 ; 1 235 doublons, 92 recoupements avec le banc et 77
étiquettes rejetées par les contrôles. Le gisement des gabarits plafonne à ≈ 3 200 décisions : `--n` au-delà ne
change rien. Taille comptée avec le vrai tokenizer : **7,15 M jetons** en train (dont 170 k de cible), 0,69 M en eval.

**Coût et durée attendus.** La passe v1 a tenu ≈ 2 000 jetons/s (`out/curves/bird-v1.log` : 1 338 pas, 325 min,
1,78 kWh). Au même réglage (LoRA r 32, `--batch-tokens 8192`, `--grad-accum 4`, 1 époque) : **≈ 1 h** de calcul
pour le jeu seul (7,15 M jetons), **≈ 2 h** avec un rappel du mélange v1 à parts égales (recommandé contre l'oubli :
≈ 5 000 enregistrements tirés de `out/mix_v1/train.jsonl`), plus ≈ 10 min de chargement et d'évaluation ; énergie
≈ 0,33 kWh par heure de calcul (même mesure). Coût : la durée × le tarif horaire publié de la machine du job v1 (même
`--flavor` que `scripts/launch.py`), soit quelques dollars ; aucun prix n'est repris ici. Ensuite : `router_eval.py`
sur `bench_heldout` et `eval.jsonl`, et banc complet, avant/après, chiffres notés ici. À valider d'abord par un essai
court (`--max-steps 50`).

## 13. Entre les actions : plan de tâche, réparations, mémoire des résultats

Code : `birds/harness/plan.py`, `repair.py`, `facts.py` (branchés dans `agent.py`) · tests : `tests/test_task_plan.py`,
`tests/scenarios/` · navigateur : `tests/e2e/plan_checklist.spec.js` · évaluation réelle : `scripts/harness_eval.py`.

Un modèle de 4 Md enchaîne mal les demandes en plusieurs étapes : il fait le tableau et oublie les totaux et le
mail, répond avant d'avoir lu la pièce jointe, appelle `google_search` ou `read_file(file=…)`, écrit l'appel en
JSON, arrondit 1 284,37 € en « environ 1 284 € », répond en anglais à une question en français. Le harnais porte
cette expérience, sans appel de modèle supplémentaire tant que rien ne manque, et au plus **un** rappel.

**Plan de tâche** (`plan.extract`, mots de l'utilisateur seulement) : liste des livrables demandés — tableau,
totaux, mail, présentation, document, tableur, graphique, synthèse, comparaison, recherche web, lecture de la page
donnée, lecture du fichier joint — dans l'ordre de la demande. Un nom ne compte que précédé d'un verbe de
fabrication ou d'un article indéfini (« prépare un mail », « et un tableur ») ; « résume ce mail », « d'après le
tableau », « crée un tableur avec les colonnes nom, prénom, email », « envoyer le compte rendu » n'en sont pas.
Le plan n'est **actif** qu'à partir de deux éléments : une note courte s'ajoute au message (« cette demande
comporte 3 éléments : 1. tableau ; 2. totaux ; 3. mail »), une ligne « [Bird checklist …] » suit le dernier
résultat de chaque étape, cochée d'après ce qui s'est réellement passé (outil réussi, texte de la réponse et des
fichiers). Une demande ordinaire garde son invite octet pour octet (testé). Deux éléments valent même seuls,
parce que répondre sans eux, c'est répondre avant le résultat : lire un fichier joint **dans ce tour** (pas un
fichier joint plus tôt, que l'application renvoie à chaque requête), et une recherche explicite : « cherche … » à
l'impératif en tête de proposition, « sur internet / en ligne », « fais une recherche » (satisfaite aussi par un
outil de fiche : « cherche un garage à Versailles ») ; jamais « je cherche à comprendre », « je recherche un
stagiaire ». L'article doit gouverner le livrable : « une formule Excel », « une macro Excel » ne demandent pas de
tableur, une question « comment faire un tableau croisé » ne demande aucun fichier. Un lien n'est une page à lire
que si la demande le dit (« lis / résume / que dit cette page », ou un lien seul) ; un lien à insérer (lien
d'inscription, signature) est du contenu, et la lecture d'un lien n'est vérifiée que dans un plan actif. Banc de
déclenchement : aucune des 52 demandes de bureau ordinaires n'active de plan ; 936/939 (les 3 mêmes manques).

**Vérification finale** (une fois par requête, avant d'accepter la réponse) : élément manquant, fichier joint non
lu, chiffres clés absents, mauvaise langue → **un seul** rappel qui liste tout (« Not done yet… mail: call
draft_email ; totaux: write the totals with their exact figures from the results: Total HT : 250,00 € ; … »).
Pas après une question de clarification, ni pour un graphique quand un fichier a été produit. Si le modèle ne
complète pas, le plan final dit ce qui manque (`Run.plan.partial`, `missing`) : l'interface affiche « Partiellement
fait : mail manque. », et le mémo du tour garde « reste à faire : mail ». La réponse donnée avant un rappel de
livrable (« Voici le tableau : … ») est gardée devant la nouvelle ; jamais après un rappel de lecture, de recherche,
de chiffres ou de langue (c'était elle le problème), ni quand la nouvelle réponse la reprend déjà (mêmes lignes de
tableau au séparateur près, ou l'essentiel de ses mots) ; une phrase antérieure qui refusait le livrable ensuite
fait (« je ne peux pas envoyer de mail… ») est retirée.

**Chiffres clés** (`facts.key_figures`) : lignes qui commencent par un libellé de total (Total HT/TTC, TVA, montant,
net à payer…), dernier montant de la ligne (« TVA 20 % : 50,00 € » donne 50,00 €). Vérifiés seulement si la
demande parle de totaux, montants ou TVA, et seulement ceux qu'elle nomme (« le total TTC » : pas la TVA). Sources :
résultats d'outils du tour et messages de l'utilisateur et de l'historique (la facture d'un tour précédent).
**Langue** : réponse d'au moins 40 lettres dont les mots courants sont au moins 3 fois plus ceux de l'autre langue
(code, citations, liens, tableaux et notes entre crochets ignorés). Pas de vérification quand la demande demande
une traduction ou une autre langue (« traduis en anglais », « réponds en anglais à ce client », « write it in
French »).

**Réparations** (`repair.py`, notées sur l'étape comme celles de `coerce.py`) : appel au format JSON
(`<tool_call>{"name", "arguments"}</tool_call>` suivi de texte), JSON nu ou en bloc de code dans la prose,
`read_file(path="x")` ; seulement pour un outil proposé à ce tour, et seulement quand la sortie *est* l'appel (en
tête, après au plus une courte ligne ; jamais dans un exemple de code, jamais depuis une ligne `search()` ou
`plot()` générique). Quand la demande porte sur du code ou un exemple (`repair.CODE_ASK`), ou après une injection
repérée dans le tour, seule la balise `<tool_call>` est lue : une page qui fait recopier un appel JSON au modèle
n'obtient ni `read_page` ni `web_search`. Une phrase qui cite un outil n'est jamais exécutée. Noms inventés (`google_search`, `send_email`, `create_presentation`, `functions.read_file`) ; noms
d'arguments (`q`, `link`, `file`, `recipient`, `headers`, `data`, `titre`…) ; objet enveloppe `{"arguments": …}` ;
ton français (« formel ») ; objet de mail absent (première ligne utile du corps) ; requête vide (les mots de
l'utilisateur) ; `https://` ajouté ; chemin d'un fichier joint mal écrit (même nom dans un autre dossier, ou
orthographe proche et unique). Un fichier introuvable : l'erreur liste les fichiers présents.

**Mémoire des résultats** : une note par résultat (`Run.notes` : « read_file « facture.jpg »: 412 characters read;
figures: Total HT : 250,00 € ; … »). Rappelée quand le modèle répète un appel (comparé à la casse et aux espaces
près), et dans la dernière chance après une boucle ratée ; les totaux lus vont dans le mémo du tour (« chiffres lus :
… »), donc « envoie ces totaux par mail » les retrouve au tour suivant, et dans le résumé des tours retirés.

**Interface** : `birds/web/static/plan.js`. Événements `plan {items:[{kind,label,status}], done, total, final,
partial?, missing?}` et `answer.plan`. Liste compacte repliable (pastilles cochées), ouverte pendant le tour, repliée
quand tout est fait, ouverte avec la ligne « Partiellement fait » sinon ; chaque élément coché est lu par la zone
`aria-live` (« Fait : présentation »). Démo : « Prépare une présentation … et un mail … » (port 9243 dans
`tests/e2e/plan_checklist.spec.js`).

**Mesure** (suite de scénarios, `python -m tests.scenarios.runner`, modèle scripté qui reproduit les erreurs d'un
4B et réagit à ce que le harnais lui rend ; « avant » = e23b517 avec la même suite) :

| famille                               | scénarios | avant  | après  | contrôles avant / après |
| ------------------------------------- | --------- | ------ | ------ | ----------------------- |
| OCR → tableau → totaux → mail         | 7         | 1      | 7      | 28/38 → 39/39           |
| recherche → comparaison → graphique   | 8         | 3      | 8      | 36/43 → 43/43           |
| fichier → synthèse → présentation     | 8         | 2      | 8      | 34/45 → 45/45           |
| plusieurs livrables                   | 7         | 2      | 7      | 30/37 → 39/39           |
| relances sur des résultats antérieurs | 6         | 2      | 6      | 22/31 → 31/31           |
| erreurs d'outil et reprises           | 7         | 2      | 7      | 21/28 → 26/26           |
| garde-fous (doublons, langue)         | 3         | 2      | 3      | 10/11 → 11/11           |
| demandes ordinaires (témoins)         | 6         | 6      | 6      | 26/26 → 26/26           |
| **total**                             | **52**    | **20** | **52** | **207/259 → 260/260**   |

Générations moyennes 2,38 → 2,65 (le rappel unique, seulement quand il manque quelque chose ; témoins : 1,33 = 1,33).
Limite : la suite a été écrite en même temps que les correctifs, par la même personne ; elle mesure les modes
d'échec connus, pas un modèle réel. L'évaluation réelle (20 tâches, même rubrique, bras `on`/`off`) reste à lancer
quand l'endpoint sera de nouveau disponible : `scripts/harness_eval.py --base-url … --arms on,off`.

**Faux déclenchements corrigés (27/11/2026).** Revue sur le modèle réel : une traduction correcte réécrite en
français, « je cherche à comprendre … » renvoyé vers `web_search`, « une formule Excel » comptée comme tableur,
un lien d'inscription pris pour une page à lire, un `draft_email(...)` d'exemple de code exécuté, un tableau
répété affiché deux fois. Huit scénarios témoins (`ordinary_translate_en`, `ordinary_write_in_french`,
`ordinary_je_cherche`, `ordinary_excel_formula`, `ordinary_mail_with_link`, `ordinary_signature_link`,
`ordinary_code_with_call_line`, `ordinary_json_example`) échouent tous sur 78c0c7d et passent ; suite : 60/60.

**Évaluation réelle** (27/11/2026, endpoint vLLM 0.32, Bird S 4B, `scripts/harness_eval.py`, 1 passage par
tâche, 12 tâches : les 8 témoins ci-dessus, `ordinary_mail`, `ordinary_question`, `ocr_table_totals_mail`,
`multi_slides_mail`). « Avant » = branche de base ccr-f7b26c02-9v78gg (46bb440, sans plan ni réparations), avec la
même suite et la même rubrique ; « après » = cette branche, plan actif.

| bras                       | tâches réussies | contrôles | générations moy. | secondes moy. |
| -------------------------- | --------------- | --------- | ---------------- | ------------- |
| avant (base 46bb440)       | 5/12            | 51/62     | 1,50             | 3,1           |
| après (w1-harness)         | 7/12            | 54/62     | 1,67             | 3,5           |

Sur les 8 témoins, le harnais n'ajoute plus aucun rappel : mêmes générations qu'avant sur chacun (le surcoût
moyen vient de `multi_slides_mail`, 1 → 3 générations, où le plan fait faire la présentation et le mail que la base
ne faisait pas). Les échecs restants sont du modèle, identiques dans les deux bras : la traduction et l'exemple JSON
appellent `web_search`, « write it in French » produit un document (2 générations), « je cherche à comprendre »
et la signature reçoivent un refus prudent. Un passage par tâche, modèle échantillonné : l'écart avant / après sur
`ocr_table_totals_mail` (TVA 50,00 € absente avant) peut tenir du tirage. Pour les témoins, la rubrique « contient »
est générale (« welcom », « SOMME.SI | SUMIF », « linkedin.com/in/test ») ; la base a été re-notée sur ses réponses
enregistrées après cet assouplissement (aucune génération de plus).

## 14. Mode Réflexion : cinq oiseaux, un vrai budget, une vérification avant réponse

Code : `birds/harness/reflexion.py` (branché dans `agent.py`), `birds/web/static/reflexion*.js|css` · tests :
`tests/test_reflexion.py`, `tests/js/reflexion.test.mjs`, `tests/e2e/reflexion.spec.js` · mesure réelle :
`scripts/reflexion_eval.py` · cas : `scripts/router_data.py` (`REFLEXION_LEVELS`, `REFLEXION_CALC`) · exemples
d'entraînement : `scripts/build_tools_mix.py` (tâche `reflexion`).

| Oiseau | Réflexion | Budget (caractères ; jetons ajoutés à `max_tokens`) | Vérification | Relecture |
| --- | --- | --- | --- | --- |
| **Colibri** · Instantané | non | 0 | non | non |
| **Hirondelle** · Rapide | oui | 1 500 (≈ 690) | non | non |
| **Faucon** · Précis | oui | 4 000 (≈ 1 730) | 1 tour | non |
| **Chouette** · Approfondi | oui | 9 000 (≈ 3 820) | 2 tours | oui |
| **Albatros** · Endurance | oui | 12 000 (≈ 5 070) | 2 tours | oui, et l'équipe du Mode Agent quand la demande en est une (`crew.decide` en « on ») |

**Ce que l'endpoint permet (mesuré le 28/11/2026, vLLM, Bird S 4B).** La réflexion passe par le gabarit
(`<think>` ouvert dans l'invite) ; aucun budget de jetons de réflexion côté serveur n'est utilisé : le budget est
tenu par le client, qui lit le flux et coupe (`_LoopGuard.think_limit`), donc il marche sur tout moteur compatible.
Mesure : 144 jetons de sortie pour 349 caractères (≈ 2,4 caractères par jeton), ≈ 51 jetons/s après un premier jeton
à 0,6 s. Sur les 8 calculs du jeu fixe, la réflexion spontanée de Bird va de 143 à 520 caractères : **le budget ne
mord jamais sur ces demandes**, il sert de plafond (boucles, demandes ouvertes).

**Reprise propre** (tous niveaux, et le chemin `thinking=True` d'avant) : une réflexion qui dépasse son budget, ou qui
tourne en rond (coupée au début de la boucle par le client), n'est plus jetée ni refaite sans réflexion : le
harnais garde ce qui a été établi (jusqu'à la dernière phrase complète), écrit « (Budget de réflexion atteint : je
m'arrête là et je réponds avec ce que j'ai établi.) » ou « (Je tourne en rond : …) », ferme `</think>` et le modèle
répond à partir de là (budget forcing). Une génération de plus, comme avant, mais elle part du raisonnement.

**Auto : le modèle décide.** Un appel court (≤ 16 jetons, température 0, schéma `{"level": colibri | hirondelle |
faucon | chouette}` imposé quand l'endpoint le permet, même détection que le routeur ; invite statique en préfixe,
réutilisée par le cache), lancé **en même temps** que l'appel du routeur : pas d'attente de plus. Albatros n'est
jamais deviné : c'est le niveau d'un tour pris par l'équipe du Mode Agent. `hint_level` (quelques indices écrits à la
main) n'est que le repli : client local, endpoint trop lent, réponse illisible. L'événement `reflexion` part avant le
premier mot (l'oiseau bat des ailes dans la ligne d'état), le champ `answer.reflexion` porte niveau, qui l'a choisi,
budget, coupure, résumé, vérifications.

**Vérification avant réponse** (Faucon et au-delà, aucun appel tant que tout est juste) : chaque « a op b … = c »
de la réponse est recalculé par le harnais (priorités, parenthèses, pourcentages « 20 % de 1 200 », un ratio écrit
en % ; « ≈ » jamais jugé ; « 3 + 4 × 2 = 14 » écrit de gauche à droite n'est pas une faute ; une étape
intermédiaire « = 1 200 + 900 = 2 100 » n'est pas un résultat ; tolérance : l'arrondi affiché) ; un calcul faux de la
réflexion compte seulement si son résultat faux est arrivé dans la réponse ; une demande à plusieurs points (liste
numérotée, ou au moins deux questions) est vérifiée point par point. Ce qui ne va pas part en **un** rappel qui le
nomme (« 14,90 € × 24 = 357,60 (not 375,60) »), le modèle réécrit. **Relecture** (Chouette, Albatros) : une
génération sans outils ni flux relit le brouillon et répond « OK » ou le texte corrigé (un « OK » ou une réponse
trop courte garde le brouillon). **Résumé lisible** : trois ou quatre phrases de la réflexion du modèle lui-même
(celles qui portent des chiffres ou une conclusion, dans leur ordre), jamais réécrites.

**Interface.** Le bouton « Réflexion » devient un sélecteur : Auto et les cinq oiseaux, chacun son dessin SVG maison,
son nom, son niveau et une ligne (clavier : Entrée, flèches, Début/Fin, Échap rend le focus ; feuille en bas
d'écran sur téléphone ; choix gardé dans le navigateur ; l'ancien réglage « sans réflexion » devient Colibri). La
réponse s'ouvre sur « Bird a pris son vol en Faucon · Précis · choisi par Bird » : résumé de la réflexion,
vérifications (« 2 calculs refaits par Bird : tous justes », « Un calcul faux a été corrigé avant de répondre »,
« Budget de réflexion atteint… »), réflexion complète repliée. L'oiseau arrive en vol une fois, bat des ailes pendant
la réflexion, rien avec `prefers-reduced-motion`. Démo : « Auto » y est décidé par les indices (aucun modèle) et
dit « choix de la démo ». Vu à 360 px et 1 440 px, clair et sombre (`tests/e2e/reflexion.spec.js`) : aucune requête
vers un tiers, aucune erreur CSP, pas de défilement horizontal. Deux défauts trouvés dans le navigateur et corrigés :
un rafraîchissement entre l'appui et le relâchement faisait perdre le clic ; le focus donné au dock le déplaçait à
360 px et le relâchement tombait sur la zone de texte.

**Mesure réelle (28/11/2026, endpoint vLLM, Bird S 4B, température 0, un passage, `BIRD_ROUTER` par défaut).**
Jeu fixe `REFLEXION_CALC` : 8 calculs et comparaisons (abonnement, remise + TVA, devis, carburant, salaire en deux
points, offres, intérêts composés, taux de conversion). Note : chaque chiffre attendu dans la réponse, et pour une
comparaison, jamais le mauvais gagnant. « Avant » = branche de base (60572e5) comme l'appelait l'application
(`thinking=True`) ; « après » = `reflexion="auto"`. Résumés : `docs/measures/reflexion-eval-2026-11-28.json`.

| bras | justes | secondes moy. | p50 | générations moy. | jetons de sortie moy. |
| --- | --- | --- | --- | --- | --- |
| avant (base, réflexion binaire) | 7/8 | 4,30 | 4,03 | 1,25 | 170 |
| après (Auto) | 7/8 | 4,70 | 4,41 | 1,38 | 191 |

Lecture franche. **Aucun gain de justesse sur ce jeu** : Bird S 4B y est déjà juste 7 fois sur 8 avec sa réflexion
spontanée, et à température 0 les 8 réponses finales d'après sont identiques, mot pour mot, à celles d'avant (le
budget de Faucon ne mord pas ; `calc_salary` et `calc_compound` font 2 générations dans les deux bras, rappel du plan
de tâche).
La seule erreur, identique dans les deux bras, n'est pas un calcul : « Février a le meilleur taux : 3 % contre
2,6 % » (le gagnant inversé, chiffres justes) ; la vérification recalcule les deux taux, justes, et ne juge pas une
phrase de comparaison. Coût : +0,4 s en moyenne (une génération de plus sur `cmp_offers`, où la vérification a
demandé une correction : le brouillon n'était pas enregistré, la cause probable, une étape intermédiaire
« 1 200 + 900 = 2 100 » de la réflexion lue comme un résultat faux, est corrigée et testée depuis, **non remesurée en
réel**). Décision Auto : Faucon 8 fois sur 8 sur ce jeu (choix du modèle chaque fois) ; sur 8 des 12 cas
`REFLEXION_LEVELS` (budget d'appels), **7/8** justes, p50 **0,32 s** par appel (l'erreur : une requête SQL prise
pour Hirondelle au lieu de Faucon). À faire : un jeu plus dur où le 4B se trompe en calcul (pour mesurer la
correction), la relecture de Chouette en réel, l'échantillonnage (plusieurs passages), et les 12 cas de niveaux.

**Entraînement.** `build_tools_mix.py` ajoute la tâche `reflexion` : l'invite exacte de `reflexion.messages` et
`{"level": …}` comme seul tour à apprendre, 9 gabarits FR/EN (≈ 95 enregistrements en train, gabarits retenus
entiers pour l'évaluation ; les phrases de `REFLEXION_LEVELS` n'entrent jamais en train).
