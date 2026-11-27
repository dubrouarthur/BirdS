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
