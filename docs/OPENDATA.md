# Données ouvertes : douze sources publiques, six fiches

Bird répond avec la donnée officielle elle-même, sourcée et sous licence, dans une fiche conçue pour elle : jours
fériés et jours ouvrés, fiche Wikipédia, séries statistiques officielles en graphique, appels d'offres publics,
publications scientifiques, communes et adresses. Toutes les sources sont **sans clé**, ouvertes et compatibles avec
l'usage d'un assistant ; le navigateur n'en contacte aucune (CSP stricte) : tout passe côté serveur par le garde-fou
réseau.

## Ce que Bird sait faire

| Fiche | Outil (module du catalogue) | Exemples | Sources | Licence affichée |
| --- | --- | --- | --- | --- |
| **Calendrier** : mois avec grille, année, jour, échéance « J+n ouvrés » | `work_calendar` | « jours fériés de mai 2027 », « J+30 ouvrés à partir du 3 décembre », « public holidays in Germany in 2027 » | calendrier.api.gouv.fr (métropole, Alsace-Moselle, DOM) ; Nager.Date (autres pays) | Licence Ouverte 2.0 ; MIT (données Nager.Date) |
| **Fiche** (organisation, pays, ville, lieu) | `lookup_entity` | « c'est quoi l'OCDE ? », « fiche Wikipédia du Portugal » | Wikipédia (résumé REST), Wikidata (faits), Wikimedia Commons (auteur et licence de l'image) | CC BY-SA 4.0 (extrait), CC0 (faits), licence de l'image |
| **Graphique d'une série officielle** | `get_statistics` | « le chômage en France et en Allemagne depuis 2015 », « population de Roubaix depuis 1968 » | Eurostat (chômage, inflation, électricité), Banque mondiale (PIB, croissance, population, exportations), Insee Melodi (populations communales, créations d'entreprises) | Eurostat (réutilisation avec mention), CC BY 4.0, Licence Ouverte 2.0 |
| **Appels d'offres** | `find_tenders` | « appels d'offres nettoyage de locaux dans le Nord » | BOAMP (DILA, Opendatasoft v2.1) | Licence Ouverte 2.0 |
| **Publications** | `find_papers` | « articles les plus cités sur le deep learning », « vérifie ce DOI 10.1038/nature14539 » | OpenAlex (recherche), Crossref (DOI) | CC0 ; métadonnées libres Crossref |
| **Commune / adresse** | `find_commune` | « code postal de Roubaix », « normalise l'adresse 8 bd du port 95000 cergy » | geo.api.gouv.fr ; Base Adresse Nationale (Géoplateforme IGN) | Licence Ouverte 2.0 |

Chaque fiche : clair et sombre, 360 px et bureau, structure accessible (titres, `dl`, tableaux avec en-têtes, listes
ordonnées, textes alternatifs, contrastes du thème), ligne « Données : source · licence » avec les deux liens, et
**« Pour continuer »** : 2 ou 3 demandes suivantes construites à partir des champs de la fiche (mois suivant, les plus
citées, population depuis 1968, météo de la commune, restaurants près de l'adresse…), envoyées comme un message tapé ;
chacune déclenche la bonne fiche (vérifié). Le graphique d'une série reprend le module graphique de Bird (PNG, CSV,
.xlsx) avec la ligne de source, le jeu de données, la date de mise à jour et les ruptures de série signalées.

Code : `birds/harness/tools/opendata/` (clients), `birds/opendata_schemas.py` (schémas), `birds/web/static/opendata.js`
(fiches), `birds/web/opendata_widgets.py` (image signée et carte côté serveur).

## Le modèle décide

Six entrées du catalogue du routeur (`birds/harness/catalog.py`, famille `opendata`) : le modèle choisit le module et
écrit ses arguments, validés (`catalog.check_args`, schéma imposé à vLLM) et **ancrés** dans les mots de
l'utilisateur (`birds/harness/opendata_route.py` : une année, un pays, une commune, un DOI absents de la demande sont
refusés ; « Germany » ancre « Allemagne »). Les analyseurs écrits à la main (`birds/harness/opendata_intents.py`)
sont des indices, le repli quand le routeur ne répond pas, et un veto contre les faux déclenchements connus :
rédaction (« rédige un article sur l'inflation »), mode d'emploi (« comment compter les jours ouvrés dans Excel ? »),
définition d'un nom commun (« c'est quoi un KPI ? »), données de l'utilisateur (« nos ventes depuis 2015 »,
« la population cible de notre campagne »), ou aucun mot de la famille. Le veto ne retire jamais ce que l'analyseur
de la famille lance lui-même.

Catalogue : 598 → 918 jetons (FR, tokenizer Qwen3.5), préfixe statique gardé en cache par vLLM.
Entraînement : `scripts/build_tools_mix.py`, famille `opendata` (390 demandes FR/EN gabaritées et 19 quasi-pièges ;
chaque étiquette valide, ancrée et non vetoée), soit 478 appels natifs et autant de décisions de routeur.
Évaluation : `scripts/router_data.py`, familles `opendata` (56 oui, 39 non) et `opendata_router` (9 demandes que les
analyseurs ne voient pas) ; un graphique de série officielle tracé par `get_statistics` compte comme le graphique
attendu de la famille `charts`.

## Règles de chaque client

- URL construites par le serveur à partir d'une base fixe, hôte dans une liste fermée (`http.HOSTS`), redirections
  interdites hors de l'hôte, `guard.fetch_bytes` (listes de refus, adresses privées, épinglage DNS, taille ≤ 2,5 Mo,
  délai ≤ 12 s).
- Espacement poli par hôte pour tout le processus (Insee Melodi : 2,1 s, quota anonyme ≈ 30 requêtes/min ;
  Nager.Date 0,5 s), au plus 6 requêtes amont par réponse, un nouvel essai après un 429 (1,2 s) ou une coupure, puis
  un message calme (« service occupé, réessayez dans une minute »), jamais un plantage.
- Cache selon la source : tables de jours fériés 30 jours, Wikipédia / Wikidata / Eurostat / Banque mondiale / Insee /
  OpenAlex / Crossref 1 jour, BOAMP 1 heure, communes et adresses 7 jours ; une réponse `no-store` n'est jamais gardée ;
  noms de fichiers du cache disque = empreintes.
- User-Agent générique qui nomme l'application et son site (étiquette Wikimedia, Crossref, OpenAlex), jamais une
  personne. Seule la demande elle-même part chez le fournisseur ; avec une pièce jointe, aucun appel automatique.
- Wikidata occupé : la fiche se construit avec le seul résumé Wikipédia ; une image n'est montrée que si Commons
  donne sa licence et son auteur, servie par `/api/img` (signée, même origine).
- Le texte des fournisseurs est une donnée externe (`guard.EXTERNAL_TOOLS`) : aucune instruction qu'il contient
  n'est suivie.

## Écartées, et pourquoi

| Source | Raison |
| --- | --- |
| Légifrance (API PISTE), Insee Sirene, France Travail, API Entreprise | clé ou compte obligatoire (PISTE / habilitation) |
| recherche-entreprises.api.gouv.fr, taux BCE | déjà intégrées (fiche entreprise, conversion de devises) |
| Hub'Eau, Open-Meteo qualité de l'air, data.gouv.fr (catalogue) | sans clé et ouvertes : prochain lot (fiche dédiée à concevoir d'abord) ; Open-Meteo interdit l'usage commercial sans abonnement |
| Google Scholar, Semantic Scholar sans clé | pas d'API ouverte (Scholar) ; quota anonyme partagé trop bas pour un service (Semantic Scholar) |
| DILA Légi / JORF en open data | archives en masse (XML), pas d'API de requête : demande un index local |

## Contrôle en direct des fournisseurs (28/11/2026)

`scripts/opendata_live.py` : un appel réel par fournisseur, avec le code des outils et le garde-fou réseau, depuis
l'environnement de développement (sortie partagée derrière un proxy).

| Fournisseur | Résultat | Durée |
| --- | --- | --- |
| calendrier.api.gouv.fr | ✓ mai 2027 : 4 fériés, 19 jours ouvrés | 0,6–0,8 s |
| Nager.Date | ✓ Allemagne 2027 : 19 fériés (dont régionaux) | 0,4 s |
| Wikipédia | ✓ résumé « Airbus », « Portugal » | 0,1–0,5 s |
| Wikidata, Commons | ✗ HTTP 429 à chaque essai (quota de la sortie partagée de l'environnement de développement, `Retry-After` ≈ 40 s) ; la fiche se replie sur le résumé Wikipédia | — |
| Eurostat | ✓ chômage France / Allemagne 2015-2025, 11 valeurs | 0,6 s |
| Banque mondiale | ✓ PIB France / Japon 2010-2025, 16 valeurs | 0,3–0,6 s |
| Insee Melodi | ✓ population de Roubaix, 18 recensements (1 coupure du proxy au 1er essai) | 1,3–1,4 s |
| BOAMP | ✓ 8 avis « maintenance informatique » (1 coupure du proxy au 1er essai) | 0,8–1,0 s |
| OpenAlex | ✓ 6 publications | 0,6–0,9 s |
| Crossref | ✓ DOI 10.1038/nature14539 « Deep learning » | 0,3–0,4 s |
| geo.api.gouv.fr | ✓ Roubaix 59512, 59100, 98 286 hab. (1 coupure du proxy au 1er essai) | 0,2 s |
| Base Adresse Nationale | ✓ 20 avenue de Ségur 75007 Paris | 0,7–1,2 s |

Le mode démo rejoue les vraies fonctions sur ces réponses enregistrées (`scripts/opendata_live.py --demo --record
birds/web/demo_data/opendata.json`, 60 ko, dates normalisées) ; la phrase de la démo est écrite à partir de la fiche
(`birds/web/opendata_demo.py`).

## Mesure du routeur en réel (28/11/2026, Bird S 4B, vLLM `structured_outputs`, `BIRD_ROUTER=hybrid`)

Jeu fixe : `scripts/router_eval.py --families … --per-class N --seed 0` (budget de la piste : 25 générations au plus).
« Avant » = le déploiement d'avant (aucun module de données ouvertes) ; pour les familles existantes, même appel avec
le catalogue sans la famille `opendata` (`--without-family opendata`).

| Jeu | n | avant (déploiement) | analyseurs seuls (hors ligne) | routeur réel, après |
| --- | --- | --- | --- | --- |
| `opendata` (3 oui, 3 non) | 6 | 0,500 (aucune fiche : 3 oui manqués) | 1,000 | **1,000** |
| `opendata_router` (3 oui que les analyseurs ne voient pas) | 3 | 0,000 | 0,000 | **1,000** |
| familles existantes `charts+`, `maps+`, `company_fx` (1 oui, 1 non chacune) | 6 | 1,000 (routeur réel, ancien catalogue) | 1,000 | **1,000** |

Latence d'un appel : p50 0,77 s (ouvertes), 0,70 s (existantes, 0,72 s avant) ; le premier appel après le réveil de
l'endpoint a dépassé le budget de 3 s et s'est replié sur les analyseurs (qui avaient raison). Aucun JSON invalide,
aucun veto. Constat en passant : avec l'ancien catalogue, le routeur proposait `get_weather` (Paris, demain) pour « la
population de Paris depuis 2012 » ; avec le nouveau, `get_statistics {population, Paris, 2012}`. Échantillon minuscule
(15 demandes) : il dit que l'intégration ne casse rien de visible, pas plus ; la mesure complète
(`--per-class 15`) reste à faire avec un budget plus large.

Tour complet dans l'application (même jour, `scripts/serve.py` sur l'endpoint réel, 1 280 px clair et 360 px sombre) :
« le chômage en France et en Allemagne depuis 2015 » → routeur `get_statistics` (+ `make_chart`, retiré par le harnais),
une étape `get_statistics` (0,4 s), courbe Eurostat avec source, jeu de données, licence et rupture de série, source
[1] Eurostat ; aucune requête vers un tiers, pas de défilement horizontal. Phrase du modèle : chiffres justes (10,4 → 7,7 %
et 4,4 → 3,8 %), mais « l'écart s'élargit » est faux (6,0 → 3,9 points) : le commentaire de tendance n'est pas
vérifié par le harnais (voir « Non vérifié »).

## Correctifs d'audit (28/11/2026) : données de l'utilisateur, J+N, tâches sur un texte, unités

Faux déclenchements relevés par l'audit, corrigés dans l'analyseur **et** dans `veto_reason` (le veto s'applique même
quand un analyseur se déclenche) : chiffres de l'utilisateur (« inflation de mes loyers », « le chômage dans mon
équipe », « exportations de notre PME », « inflation des salaires »), aucun pays rempli quand l'utilisateur n'en nomme
pas (ancrage), congés / contrat / projet de l'utilisateur, « J+30 » nu (jours calendaires : plus de carte en jours
ouvrés, et l'ancrage refuse un `add_days` sans « ouvrés / working days »), tâches sur un texte (translate, summarize,
proofread, rewrite, corrige, mets en forme), appels d'offres de l'utilisateur (« que nous avons perdus ») et requête
BOAMP qui commence par une relative. Fiche entité : moins de 10 → deux chiffres significatifs (« 0,44 km² », plus
« 0 km² ») ; une somme sans devise connue n'est plus affichée (SEK ajoutée).

Mesure avant / après sur le jeu fixe (`scripts/trigger_bench.py`, 22 nouveaux « non » + 1 nouveau « oui » dans
`bench_opendata.py`, repris par `router_data.py` pour l'évaluation du routeur) :

| Jeu | avant (c4635bb) | après |
| --- | --- | --- |
| famille `opendata` (118) | 99/118 (19 faux déclenchements sur 61 « non ») | **118/118** |
| 22 nouveaux « non », fusion hybride si le modèle ne choisit rien | 14 cartes rajoutées par `router.merge` | **0** |
| banc complet | 1 954/1 973 | **1 973/1 973** |

Douze exemples négatifs d'entraînement ajoutés (`build_tools_mix.py`, `odn8`–`odn12`, `odne3`), formulés autrement
que le banc. E2E `scripts/opendata_ui_smoke.js` : 5 demandes « non » ajoutées (aucune fiche, 360 / 1 280 px, clair / sombre),
17 cas × 4 mises en page, toutes les vérifications passent. Mesure du routeur en réel non refaite : l'endpoint était en pause (« ask a maintainer to restart it »).

## Non vérifié

- Faits Wikidata et images Commons en direct de façon répétée : la sortie partagée de l'environnement reçoit des 429 ;
  la fiche Unesco de la démo a été enregistrée lors d'une fenêtre où Wikidata a répondu (faits, sans image).
- Le commentaire de tendance écrit par le modèle sous un graphique (sens d'un écart) n'est pas contrôlé.
- La mesure du routeur sur le jeu complet, et l'effet de l'entraînement (`build_tools_mix.py`) : pas de fine-tuning ici.

## Tests

`tests/test_opendata.py` (outils sur réponses enregistrées, hôtes, plafond, cache, 429, ancrage, veto, indices,
image signée, démo), `tests/js/opendata.test.mjs` (parité FR/EN des textes, grille, compte à rebours, demandes
suivantes, copie), `scripts/trigger_bench.py` familles `opendata` (118) et `opendata_cross` (394 « non » des autres
familles), `scripts/opendata_ui_smoke.js` (11 demandes × 360 / 1 280 px × clair / sombre : fiche, source et licence
liées, pas de défilement horizontal, aucun tiers contacté, aucune erreur CSP ; « Pour continuer » lance la fiche
suivante).
