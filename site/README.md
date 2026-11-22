# Site corporate Bird Models

Site statique (HTML, CSS, ~4 Ko de JavaScript), sans framework ni étape de build.
Aucune requête externe : polices système, images locales, pas de traceur.

## Arborescence

```
site/
├── index.html          Accueil — La philosophie (FR)
├── demarche.html       Notre démarche (FR)
├── empreinte.html      Empreinte (FR)
├── en/                 Version anglaise (index, approach, footprint)
├── config.js           URL du bouton « Essayer Bird » (une seule constante)
├── assets/             site.css, site.js, images WebP, favicon, marque
├── vercel.json         URL propres + en-têtes de sécurité (CSP stricte)
├── .vercelignore       Exclut COPY.md, ce README (et un éventuel screenshots/) du déploiement
└── COPY.md             Texte de référence (non publié)
```

## Avant la mise en ligne

1. **Bouton « Essayer Bird »** : dans `config.js`, remplacer `TRY_URL: "#essayer"` par l'URL de l'application.
2. **Adresse de contact** : remplacer `contact@birdmodels.example` (6 pages, section Contact) et supprimer l'étiquette `[À REMPLACER …]` / `[TO BE REPLACED …]`.
3. **Poids affiché en pied de page** : chaque page affiche son propre poids. Si une page change, remesurer et mettre à jour son pied de page.
   Méthode : charger la page dans Chromium (1440 px, cache désactivé), faire défiler jusqu'en bas pour charger toutes les images, additionner la taille des fichiers reçus, puis ajouter la favicon (`assets/favicon.svg`, que Chromium sans interface ne demande pas). 1 Ko = 1 000 octets. Le chiffre « compressé » est la même somme avec les fichiers texte (HTML, CSS, JS, SVG) compressés en gzip niveau 9 ; les images WebP sont comptées telles quelles.
   Valeurs actuelles : accueil FR **205 Ko** (10 requêtes, ≈ 164 Ko compressés) ; accueil EN 204 KB (10) ; Notre démarche 46 Ko (5) ; Empreinte 85 Ko (6) ; Our approach 46 KB (5) ; Footprint 85 KB (6). Au premier affichage, avant les images différées, l'accueil charge environ 98 Ko en 5 requêtes.

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

Aucun fait hors de la liste vérifiée (voir `COPY.md`). Chaque chiffre est donné avec sa méthode.
Ne jamais écrire « hébergé en France » ni nommer le modèle de base.
