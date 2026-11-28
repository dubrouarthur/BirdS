# SearXNG pour Bird (Railway)

Une instance SearXNG privée, réglée pour Bird :

- **beaucoup de moteurs**, chacun appelé rarement, pour qu'aucun ne bloque : Bing, Brave, Qwant, Mojeek, Yahoo,
  DuckDuckGo, Wikipédia, Wikidata, plus l'actualité (Bing, Qwant, Yahoo, Wikinews) et les images libres
  (Openverse, Wikimedia Commons) ;
- un moteur qui renvoie un CAPTCHA est **mis de côté 30 min**, les autres répondent à sa place ;
- **format JSON** activé (celui que Bird utilise) ;
- **pas de limiteur ni de Valkey** : seul le serveur de Bird appelle l'instance ;
- délais courts (4 s par moteur) : un moteur lent ne retient jamais la réponse.

Google et Startpage sont présents mais **désactivés** : ils bloquent vite les adresses IP de cloud. Activez-les dans
`settings.yml` (`disabled: false`) si votre instance n'est pas bloquée.

## Déployer sur Railway

1. **New Project** puis **Deploy from GitHub repo**, et choisissez ce dépôt.
2. Dans **Settings**, mettez **Root Directory** à `deploy/searxng`. Railway lit `railway.json` et construit le
   `Dockerfile`.
3. Dans **Variables**, ajoutez :

   | Variable              | Valeur                                                                                                            |
   | --------------------- | ----------------------------------------------------------------------------------------------------------------- |
   | `SEARXNG_SECRET`      | une longue chaîne aléatoire, différente pour chaque instance (par exemple `openssl rand -hex 32`)                 |
   | `SEARXNG_CONTACT_URL` | une page de contact publique, par exemple `https://bird-s.vercel.app/a-propos/` (Wikipédia et Wikidata l'exigent) |
   | `SEARXNG_BASE_URL`    | l'URL publique de l'instance, par exemple `https://bird-search-1.up.railway.app/`                                 |

4. Dans **Networking**, générez un domaine public. Le conteneur écoute sur `$PORT`, que Railway fournit.
5. Vérifiez la santé de l'instance : `https://<domaine>/healthz` doit renvoyer `OK`. Puis testez
   `https://<domaine>/search?q=test&format=json`.

## Trois instances

Déployez ce même dossier **trois fois**, comme trois services Railway, avec un `SEARXNG_SECRET` différent pour chacun.
Si possible, placez-les dans des régions différentes : chacune a alors sa propre adresse IP, et un blocage sur l'une ne
touche pas les autres.

Côté Bird, dans les variables d'environnement de Vercel :

| Variable Bird        | Valeur                                                     |
| -------------------- | ---------------------------------------------------------- |
| `BIRD_SEARXNG_URL`   | URL de l'instance 1                                        |
| `BIRD_SEARXNG_URL_2` | URL de l'instance 2                                        |
| `BIRD_SEARXNG_URL_3` | URL de l'instance 3                                        |
| `BIRD_BRAVE_API_KEY` | déjà en place : le secours si les trois instances échouent |

Bird répartit les recherches entre les instances. Il passe à la suivante quand l'une refuse ou ne trouve rien parce que
ses moteurs sont bloqués, puis à Brave, puis à Wikipédia.

## Mettre à jour

L'image est figée sur une version datée (`FROM searxng/searxng:<date>-<hash>` dans le `Dockerfile`). Pour monter de
version, changez l'étiquette, redéployez une instance, vérifiez `/healthz` et une recherche JSON, puis faites de même
pour les deux autres.

## Vérifié avant livraison

`settings.yml` a été chargé par le chargeur de SearXNG lui-même : 15 moteurs actifs, aucune erreur une fois
`SEARXNG_CONTACT_URL` défini. Une vraie recherche JSON a renvoyé 10 résultats, alors que plusieurs moteurs étaient
bloqués depuis la machine de test. C'est l'intérêt d'avoir beaucoup de moteurs. Le conteneur lui-même n'a pas pu être
lancé sur cette machine, qui n'a pas de Docker : le premier déploiement Railway en fait office.
