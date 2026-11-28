# Marchés : cours, historique et comparaison (`get_quote`)

En production, un utilisateur a demandé un graphique de cours et Bird a répondu : « Je n'ai pas accès aux données
boursières récentes… Vérifiez Yahoo Finance ». Bird répond maintenant avec une **fiche de cours** et un **graphique
d'historique** construits à partir des données d'un fournisseur dont les conditions autorisent cet usage. Chaque
chiffre est daté, avec son délai. Il n'est jamais présenté comme « en temps réel » quand il ne l'est pas.

## Ce que Bird sait faire

| Demande | Résultat |
| --- | --- |
| « cours du bitcoin », « combien vaut l'ether ? » | fiche : dernier cours, variation sur 24 h, sparkline, plus haut et plus bas de la période ; courbe sur 6 mois |
| « évolution de l'euro dollar sur 6 mois », « le yen sur 5 ans » | taux de référence BCE (paire croisée par l'euro au besoin), variation depuis le taux précédent ; courbe |
| « compare bitcoin et ethereum sur 1 an » | jusqu'à 3 lignes, **base 100** le premier jour commun (calcul de Bird, signalé) |
| « cours de l'action LVMH », « compare LVMH et Hermès », « le CAC 40 sur 5 ans » | clôture du jour précédent, variation depuis la clôture précédente ; **seulement si le flux sous licence est activé** (voir plus bas) |
| « dois-je acheter du bitcoin ? » | la fiche, plus **une ligne neutre** : « Information sur les cours, pas un conseil en investissement. » Le modèle a pour consigne de ne donner ni recommandation ni prévision. |

La fiche (`birds/web/static/finance.js`, `finance.css`) fonctionne en clair et en sombre, à 360 px comme sur bureau.
La variation est donnée par un **signe, une flèche (▲ ▼) et une couleur** : la couleur n'est jamais le seul
indice. Le contraste dépasse 4,5:1 dans les deux thèmes (vérifié par `tests/js/finance.test.mjs`), et un texte
« en hausse de 0,83 % » est prévu pour les lecteurs d'écran. On y trouve aussi des puces de période
**1M 6M 1A 5A** (5A est masquée pour les cryptoactifs, dont l'historique gratuit s'arrête à 1 an), la ligne
« Données : source — licence » avec ses deux liens, et **« Pour continuer »** : 2 ou 3 demandes construites à partir
de la fiche (« cours de LVMH sur 5 ans », « compare le cours de LVMH avec le CAC 40 », « compare Bitcoin avec
Ethereum », « convertis 100 EUR en USD »). Chaque puce envoie une demande tapée. Le tour suivant **réaffiche la fiche
et le graphique à jour**, ce qui assure la continuité ; les tours précédents restent dans la conversation. Le
graphique vient du moteur commun (`chart.js`) : alternative en tableau (« Voir les données »), export PNG avec la
ligne de source, copie CSV et export .xlsx. La fiche s'affiche au-dessus du graphique qu'elle pilote.

## Sources : choix et raisons (conditions lues et appels testés le 28/11/2026)

| Fournisseur | Usage | Clé | Conditions | Décision |
| --- | --- | --- | --- | --- |
| **CoinGecko** API publique | cryptoactifs | sans clé (clé « Demo » gratuite facultative : `BIRD_COINGECKO_API_KEY`) | API publique documentée, quota par adresse IP, **attribution obligatoire** (« Data provided by CoinGecko », guide d'attribution) ; historique limité à 365 jours sans offre payante | **retenu**, par défaut |
| **BCE, Data Portal** (EXR) | paires de devises | sans clé | politique de réutilisation du SEBC : réutilisation libre et gratuite, **y compris commerciale**, à condition de citer la source et de ne pas modifier les données (la base 100 est signalée comme calculée par Bird) | **retenu**, par défaut |
| **Twelve Data** | actions et indices | **clé obligatoire** : `BIRD_TWELVEDATA_API_KEY`, envoyée en en-tête `Authorization: apikey …`, jamais dans l'URL | licence pour un usage interne ; **l'affichage à des tiers demande une offre ou une option de redistribution** | **branché derrière la clé** : il faut une offre avec droit d'affichage |
| Alpha Vantage | actions | clé | offre gratuite réservée à un « usage personnel, non commercial » | écarté |
| EODHD | actions | clé | offre gratuite : interdiction de « display » et de redistribution | écarté |
| Financial Modeling Prep | actions | clé | page des conditions inaccessible (403) ; clé obligatoire | non retenu |
| FRED (fredgraph.csv) | S&P 500, Nasdaq… | sans clé | les séries d'indices sont la propriété de S&P DJI ou de Nasdaq, et leur reproduction demande une autorisation | écarté |
| Stooq | actions, indices | — | site protégé par une vérification JavaScript anti-robot, connexion coupée depuis le serveur, aucune licence de réutilisation | écarté |
| Yahoo / Google Finance, Euronext live, api.nasdaq.com | — | — | interfaces non officielles ou pages web : du scraping | **refusés** |

**Aucune source sans clé n'autorise l'affichage public de cours d'actions** : c'est un problème de droits des
bourses, pas un problème technique. Bird est donc livré avec les cryptoactifs et les devises activés par défaut.
Les actions et les indices s'activent dès que le propriétaire ajoute la clé d'une offre Twelve Data comportant le
droit d'affichage (secret réseau ou variable d'environnement `BIRD_TWELVEDATA_API_KEY`). En l'absence de clé, une
demande qui ne porte que sur des actions **n'est pas préremplie** : le tour se déroule comme avant (le modèle peut
chercher sur le web, sources citées). Bird n'affiche jamais une fiche qui dirait seulement « indisponible ». Dans
une demande mixte (« LVMH et bitcoin »), la fiche montre le bitcoin et signale en une ligne que les actions ne sont
pas activées.

## Le modèle décide

- Catalogue : `get_quote(symbols*, range=1m|6m|1y|5y)`, famille `finance` (`birds/harness/catalog.py`). Le préfixe
  statique du routeur passe de 985 à 1 049 jetons en FR et de 922 à 986 en EN (tokenizer Qwen3.5). Il reste dans le
  cache de vLLM.
- Liste validée (`birds/harness/tools/opendata/markets.py`) : 40 actions (CAC 40, grandes valeurs américaines,
  Xetra) et 5 indices (CAC 40, SBF 120, DAX, FTSE 100, Nikkei 225), chacun vérifié avec son symbole et son code de
  marché (MIC) dans `/symbol_search` et `/indices` de Twelve Data. S'y ajoutent 7 cryptoactifs (identifiants
  CoinGecko) et toutes les devises publiées par la BCE. Un nom absent de la liste n'est **jamais deviné** : l'outil
  répond qu'il ne le connaît pas.
- Ancrage (`opendata_route._ground_quote`) : chaque instrument écrit par le modèle doit être nommé par
  l'utilisateur. Veto contre les faux déclenchements connus : « cours » au sens de leçon, « action » au sens de
  tâche, prix d'un produit, comptes d'une entreprise (CA, effectifs, dirigeants), définition ou mode d'emploi,
  rédaction, portefeuille de l'utilisateur.
- L'analyseur `birds/harness/finance_intents.py` sert d'indice, de repli et de garde-fou. Les noms ambigus
  (Orange, Apple, Total, Vinci…) ne comptent qu'à côté d'un mot boursier fort. Les tickers de deux lettres (« CA »,
  « AI ») ne sont lus que sous la forme `CA.PA`.
- Entraînement : famille `finance` de `scripts/build_tools_mix.py`, avec 188 demandes gabaritées FR/EN, dont
  22 négatives. Cela donne 475 enregistrements d'entraînement (routeur et appel natif) et 44 d'évaluation
  (gabarits `fi6`, `fi9` tenus à l'écart).
- Évaluation : `scripts/bench_finance.py`. La famille `finance` compte 55 « oui » et 39 « non », la famille
  `finance_cross` 486 « non » des autres familles, et `finance_router` 3 demandes que l'analyseur ne voit pas.

## Mesures

| Jeu | avant | après |
| --- | --- | --- |
| banc des déclenchements, total | 2 094/2 094 | **2 674/2 674** (familles existantes inchangées ; `finance` 94/94, `finance_cross` 486/486) |
| routeur réel, `finance` + `finance_router` (2 par classe, graine 0, hybride, `structured_outputs`) | 0/4 « oui » (aucun module dans le catalogue) | **6/6** ; analyseurs seuls 4/6 ; p50 0,79 s ; 0 JSON invalide, 0 repli |
| routeur réel, non-régression `charts+` et `company_fx` (1 par classe) | — | **4/4** |

Détail : `docs/measures/router-eval-2026-11-28-finance.json`. Exemples : « is Nvidia up or down this week? » →
`get_quote {Nvidia}` alors que l'analyseur ne dit rien ; « prépare un cours sur la bourse pour des lycéens » →
`office(slides)`, sans fiche. L'échantillon est petit (budget de 25 générations) : il montre que rien de visible ne
casse, sans plus.

## Contrôle en réel (28/11/2026, `scripts/serve.py --from-env` sur l'endpoint réel, sans clé Twelve Data)

| Demande | Résultat |
| --- | --- |
| cours du bitcoin | `get_quote` en 1,1 s ; fiche, courbe et source CoinGecko ; phrase juste (54 402 EUR, −3,29 % sur 24 h, −11,23 % sur 6 mois). Le modèle a écrit « Source : Bird Tools » au lieu de [1]. |
| évolution de l'euro dollar sur 6 mois | `get_quote` en 1,0 s ; fiche BCE et courbe ; chiffres justes (1,0957, −5,90 %, haut 1,1699, bas 1,0935) |
| compare LVMH et Hermès sur 1 an | sans clé, aucune fiche (comportement attendu) ; recherche web vide ; le modèle répond qu'il n'a pas de données fiables, sans renvoyer vers un site |
| dois-je acheter du bitcoin maintenant ? | **défaut trouvé** : aucune fiche, et « consultez un site fiable ». Corrigé après la mesure : une demande de conseil d'achat, de vente ou d'investissement sur un instrument listé ouvre la fiche avec la ligne neutre (ajoutée au banc et à l'entraînement). Non revérifié en réel, faute de budget. |
| cours de piano à Lyon le samedi | aucune fiche de cours (vérifié) |

Captures 360 / 1 280 px en clair et en sombre de chaque demande, regardées : pas de défilement horizontal, aucun
appel à un tiers. Deux défauts corrigés après coup : à 360 px, « EUR/USD » se coupait sur la barre oblique, et les
dates de l'axe horizontal se chevauchaient (`chart.js` espace désormais les étiquettes selon leur largeur réelle).

E2E sur le serveur de démo (`scripts/finance_ui_smoke.js`) : 7 cas × 4 mises en page. Tout passe : fiche, chiffre
daté, signe et flèche, source et licence liées, graphique avec tableau, PNG et CSV, base 100, puces de période et
« Pour continuer » qui redessinent, aucune fiche sur les quasi-pièges, pas de défilement horizontal, aucun tiers
contacté, aucune erreur CSP.

## Démo, tests

- Démo : les réponses CoinGecko et BCE enregistrées par `scripts/finance_live.py --demo --record
  birds/web/demo_data/finance.json` (87 ko, réduites aux colonnes lues) sont rejouées à l'instant de
  l'enregistrement. Les réponses de Twelve Data ne sont **jamais** enregistrées, et la démo ne montre pas d'actions.
- `tests/test_finance.py` : liste, analyseur, ancrage, veto, outil sur réponses enregistrées, calcul de la paire
  croisée, base 100, barre du jour écartée tant que la séance est ouverte, clé envoyée en en-tête, refus de clé,
  usage sans clé, agent, widget, démo. `tests/js/finance.test.mjs` : parité FR/EN, formats, ligne de date, puces,
  sparkline, contrastes, copie.

## Non vérifié

- Actions et indices en réel avec une vraie clé. Seule la clé `demo` de Twelve Data a été essayée, sur Apple
  (358,54 USD, clôture du 27/11). Les indices américains (S&P 500, Nasdaq, Dow Jones) ne figurent pas dans la liste
  des indices de Twelve Data accessible sans clé : ils sont absents de la liste validée.
- La phrase du modèle sous la fiche (citation [n], sens d'une tendance) n'est pas contrôlée par le harnais.

## Vérification avant fusion (28/11/2026)

Noms ambigus rejoués sur l'analyseur, l'ancrage et l'outil (Total, Orange, Apple, Air Liquide, LVMH, bitcoin,
CAC 40, S&P 500, l'or, Bitcoin Cash, Ethereum Classic…), puis 12 demandes en réel sur l'endpoint (`serve.py`, sans
clé Twelve Data). Défauts trouvés et corrigés :

| demande | avant | après |
| --- | --- | --- |
| « cours du Bitcoin Cash », « Ethereum Classic », « Wrapped Bitcoin », « Bitcoin Gold », « bitcoin ETF » | fiche **Bitcoin** (ou Ethereum) : mauvais instrument, affiché sans clé | aucune fiche : `find_all` ne lit plus une pièce listée dans le nom d'un autre actif, l'ancrage exige que la pièce soit lue telle quelle, et l'outil refuse une pièce que la demande nomme autrement |
| « l'or », « or » écrits par le modèle | L'Oréal (ticker `OR`) | non reconnu ; `OR` et `OR.PA` en capitales restent L'Oréal |

Réel après correctifs : bitcoin, « dois-je acheter du bitcoin » (fiche + ligne neutre), euro dollar sur 6 mois et
« l'or et le bitcoin » (fiche bitcoin, l'or dit absent) : bons instruments, chiffres de la fiche repris ; Bitcoin Cash,
Total, Orange, Apple, Air Liquide, LVMH, CAC 40, S&P 500 sans clé : aucune fiche, le tour part en recherche web
(comportement prévu). Banc : `finance` 98/98 (+4 négatifs), total 2 715/2 715.
