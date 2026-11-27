# Site corporate Bird Models

Site statique (HTML, CSS, ~4 Ko de JavaScript), sans framework ni étape de build.
Aucune requête externe : polices système, images locales, pas de traceur.

## Arborescence

```
site/
├── index.html          Accueil (FR)
├── entrainer.html      Entraîner Bird sur vos tâches (FR, pour les entreprises)
├── demarche.html       Notre démarche (FR)
├── empreinte.html      Sobriété (FR ; le nom de fichier reste empreinte.html)
├── en/                 Version anglaise (index, training, approach, footprint = « Frugality »)
├── config.js           URL du bouton « Essayer Bird » et adresse de contact
├── assets/             site.css, site.js, images WebP (img/app/ : captures de l'application, claire et sombre), favicon, marque
├── vercel.json         URL propres + en-têtes de sécurité (CSP stricte)
├── .vercelignore       Exclut COPY.md, ce README (et un éventuel screenshots/) du déploiement
└── COPY.md             Texte de référence (non publié)
```

## Avant la mise en ligne

1. **Bouton « Essayer Bird »** : dans `config.js`, remplacer `TRY_URL: "#essayer"` par l'URL de l'application.
2. **BLOQUANT — adresse de contact** : `contact@birdmodels.example` est un domaine réservé qui ne reçoit rien ; tous les boutons « Nous écrire », « Parler de votre projet » et Contact y mènent. Dans `config.js`, remplacer `CONTACT_EMAIL` par l'adresse réelle avant toute mise en ligne. Le script l'applique aux 8 pages (liens `data-contact`, et `data-contact-href` pour les boutons « Nous écrire ») ; pour les visiteurs sans JavaScript, remplacer aussi `contact@birdmodels.example` dans les 8 pages.
3. **Poids affiché en pied de page** : chaque page affiche son propre poids. Si une page change, remesurer et mettre à jour son pied de page.
   Méthode : charger la page dans Chromium (1440 px, cache désactivé), faire défiler jusqu'en bas pour charger toutes les images, additionner la taille des fichiers reçus, puis ajouter la favicon (`assets/favicon.svg`, que Chromium sans interface ne demande pas). 1 Ko = 1 000 octets. Le chiffre « compressé » est la même somme avec les fichiers texte (HTML, CSS, JS, SVG) compressés en gzip niveau 9 ; les images WebP sont comptées telles quelles.
   Valeurs actuelles (thème clair, 1440 px) : accueil FR **436 Ko** (13 requêtes, 345 Ko compressé) ; accueil EN 435 KB (13) ; Entraîner Bird 91 Ko (5) ; Train Bird 91 KB (5) ; Notre démarche 89 Ko (5) ; Sobriété 144 Ko (7, 68 Ko compressé) ; Our approach 88 KB (5) ; Frugality 143 KB (7).

## Déployer sur Vercel

1. Sur vercel.com : **Add New… → Project**, importer le dépôt `BirdS`.
2. **Root Directory** : cliquer **Edit** et choisir `site`.
3. **Framework Preset** : `Other`. Laisser **Build Command** et **Install Command** vides (ou cocher « Override » avec une commande vide). **Output Directory** : laisser vide (`.` = le dossier `site`).
4. Cliquer **Deploy**.
5. Vérifier : `/`, `/entrainer`, `/en/training`, `/demarche`, `/empreinte`, `/en`, `/en/approach`, `/en/footprint`, et les en-têtes (`curl -I https://<domaine>/` doit montrer `content-security-policy`).
6. Domaine personnalisé : **Settings → Domains**.

En ligne de commande (équivalent) :

```bash
cd site
npx vercel@latest          # première fois : lier le projet, répondre "./" comme dossier
npx vercel@latest --prod
```

`vercel.json` active `cleanUrls` (`/demarche` sert `demarche.html`) et ajoute une CSP stricte :
`default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'` … Aucun script ni style en ligne n'est autorisé :
tout nouveau code va dans `assets/site.js` ou `assets/site.css`, jamais dans un attribut `style=` ou `onclick=`.

## Tester en local

```bash
cd site
python3 -m http.server 8890
```

Avec `http.server`, les URL propres ne marchent pas : ouvrir `http://localhost:8890/demarche.html`
ou passer par `npx vercel dev`, qui applique `vercel.json`.

Les captures de contrôle ne sont pas rangées dans `site/` : elles alourdiraient le dépôt sans être publiées.

## Captures et scènes

- `assets/img/app/*-light.webp` / `*-dark.webp` : captures réelles de l'application (`scripts/serve.py --demo`, Chromium, échelle 2),
  recadrées au plus près de la carte riche (graphique, tableur, diapositive, note Word, code, Mode Agent), prises à 390-600 px de large
  pour s'afficher à leur taille réelle : le texte reste à 11 px ou plus à 1440 px comme sur téléphone. `map-m-*` et `slides-m-*` sont les
  recadrages téléphone, servis par `<picture>` sous 760 px. Les badges propres au mode démo sont masqués. La version sombre ne se charge qu'en thème sombre (`.th-l` / `.th-d`).
- Scènes (`[data-scene]` dans le HTML, lecteur dans `site.js`) : un échange rejoué en HTML et CSS, sans vidéo.
  `data-at` (apparition, en ms), `data-out` (disparition), `data-type` / `data-stream` (texte écrit lettre à lettre / mot à mot pendant `data-dur`).
  Sans JavaScript ou avec « réduire les animations », l'état final s'affiche ; la lecture ne tourne que quand la scène est visible.
  Les scènes sont des simulations : elles n'affichent aucun chiffre mesuré.

## Règles éditoriales

Ton promotionnel, mais chaque affirmation doit être vraie et vérifiable (publicité comparative : comparaisons objectives, sources en notes).
Chiffres autorisés : 4 Md de paramètres, ≈ 400 Md pour un grand modèle dense (≈ 100× plus petit ; « 100× moins de calcul par mot » seulement avec « en théorie »),
≈ 0,07 Wh et ≈ 0,011 mL par requête courte (2 000 tokens lus, 500 écrits ; estimation d'après les tokens, la méthode du compteur), 0,34 Wh / 0,32 mL (ChatGPT, Altman, juin 2025),
0,24 Wh / 0,26 mL (Gemini, Google, août 2025), « plus de 4 fois moins d'électricité », « environ 30 fois moins d'eau »,
le banc d'essai interne de Notre démarche. Écrire « conçu en France » uniquement : jamais hébergé / entraîné en France, ni renouvelable aujourd'hui,
ni neutre en carbone, ni « le plus sobre du marché » ; ne pas nommer le modèle de base ni la région du serveur. Les objectifs énergie se lisent comme des objectifs.
Jamais de nombre de GPU ni de matériel, jamais d'énergie d'entraînement, jamais où ni sur quoi Bird tourne. Vitesse et coût d'entraînement : en qualitatif
(« répond vite », « pour un coût bien inférieur ») ; aucun chiffre de latence tant qu'il n'est pas mesuré sur le modèle réel.
Notes de méthode : 0,006 Wh / 1 000 tokens lus et 0,10 Wh / 1 000 tokens écrits (`birds/web/settings.py`, service complet, × 1,72 compris),
0,062 Wh arrondi à 0,07 Wh ; eau : 0,15 L/kWh d'eau de refroidissement (efficacité d'usage de l'eau publiée par l'hébergeur pour 2024, source dans COPY.md), sans nommer l'hébergeur ni de centre de données ; 0,07 × 0,15 = 0,0105 mL, affiché 0,011 mL.
Ratios arrondis en défaveur de Bird : 0,34 / 0,07 ≈ 4,9 (« plus de 4× ») ; 0,32 / 0,011 ≈ 29 (« environ 30× ») ; Gemini, périmètre comparable : 0,24 / 0,07 ≈ 3,4 (« plus de 3× »), 0,26 / 0,011 ≈ 23 (« plus de 20× »). Si les constantes de `settings.py` changent, recalculer ces chiffres.
