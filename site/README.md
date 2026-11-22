# Site corporate Bird Models

Site statique (HTML, CSS, ~4 Ko de JavaScript), sans framework ni étape de build.
Aucune requête externe : polices système, images locales, pas de traceur.

## Arborescence

```
site/
├── index.html          Accueil (FR)
├── demarche.html       Notre démarche (FR)
├── empreinte.html      Sobriété (FR ; le nom de fichier reste empreinte.html)
├── en/                 Version anglaise (index, approach, footprint = « Frugality »)
├── config.js           URL du bouton « Essayer Bird » et adresse de contact
├── assets/             site.css, site.js, images WebP, favicon, marque
├── vercel.json         URL propres + en-têtes de sécurité (CSP stricte)
├── .vercelignore       Exclut COPY.md, ce README (et un éventuel screenshots/) du déploiement
└── COPY.md             Texte de référence (non publié)
```

## Avant la mise en ligne

1. **Bouton « Essayer Bird »** : dans `config.js`, remplacer `TRY_URL: "#essayer"` par l'URL de l'application.
2. **Adresse de contact** : dans `config.js`, remplacer `CONTACT_EMAIL` (provisoire : `contact@birdmodels.example`). Le script l'applique aux 6 pages ; pour les visiteurs sans JavaScript, remplacer aussi `contact@birdmodels.example` dans les 6 pages (lien `data-contact`).
3. **Poids affiché en pied de page** : chaque page affiche son propre poids. Si une page change, remesurer et mettre à jour son pied de page.
   Méthode : charger la page dans Chromium (1440 px, cache désactivé), faire défiler jusqu'en bas pour charger toutes les images, additionner la taille des fichiers reçus, puis ajouter la favicon (`assets/favicon.svg`, que Chromium sans interface ne demande pas). 1 Ko = 1 000 octets. Le chiffre « compressé » est la même somme avec les fichiers texte (HTML, CSS, JS, SVG) compressés en gzip niveau 9 ; les images WebP sont comptées telles quelles.
   Valeurs actuelles : accueil FR **162 Ko** (8 requêtes) ; accueil EN 161 KB (8) ; Notre démarche 54 Ko (5) ; Sobriété 99 Ko (7) ; Our approach 53 KB (5) ; Frugality 98 KB (7).

## Déployer sur Vercel

1. Sur vercel.com : **Add New… → Project**, importer le dépôt `BirdS`.
2. **Root Directory** : cliquer **Edit** et choisir `site`.
3. **Framework Preset** : `Other`. Laisser **Build Command** et **Install Command** vides (ou cocher « Override » avec une commande vide). **Output Directory** : laisser vide (`.` = le dossier `site`).
4. Cliquer **Deploy**.
5. Vérifier : `/`, `/demarche`, `/empreinte`, `/en`, `/en/approach`, `/en/footprint`, et les en-têtes (`curl -I https://<domaine>/` doit montrer `content-security-policy`).
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

## Règles éditoriales

Ton promotionnel, mais chaque affirmation doit être vraie et vérifiable (publicité comparative : comparaisons objectives, sources en notes).
Chiffres autorisés : 4 Md de paramètres, ≈ 400 Md pour un grand modèle dense (≈ 100× plus petit ; « 100× moins de calcul par mot » seulement avec « en théorie »),
≤ 0,13 Wh et ≈ 0,02 mL par requête courte (estimation haute, ≈ 0,04 Wh pour les plus brèves), 0,34 Wh / 0,32 mL (ChatGPT, Altman, juin 2025),
0,24 Wh / 0,26 mL (Gemini, Google, août 2025), « 3 à 8 fois moins d'électricité », « environ 15 fois moins d'eau », 1,8 kWh d'entraînement (L40S, 5 h 26),
le banc d'essai interne de Notre démarche. Écrire « conçu en France » uniquement : jamais hébergé / entraîné en France, ni renouvelable aujourd'hui,
ni neutre en carbone, ni « le plus sobre du marché » ; ne pas nommer le modèle de base ni la région du serveur. Les objectifs énergie se lisent comme des objectifs.
