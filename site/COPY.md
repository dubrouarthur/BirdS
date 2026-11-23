> **Obsolète (refonte promotionnelle, novembre 2026)** : les pages HTML font foi ; ce fichier décrit l'ancienne version du site. Règles éditoriales à jour : voir README.md.

> Note : le texte publié fait foi (pages HTML). Ce fichier reprend les corrections de relecture principales ; titres, sections « Ce que fait Bird », limites et précautions d'Empreinte ont été resserrés dans les pages.

# Bird Models — copy du site corporate

Document de référence pour tout le texte du site. Français d'abord, anglais ensuite.
Règle : aucun fait hors de la liste vérifiée. Chaque chiffre est donné avec sa méthode.
Le site lui-même doit respecter la promesse : léger, sans traceur, sans requête externe.

---

## 0. Plateforme de marque

**Positionnement (interne)**
Pour les équipes qui veulent un assistant de travail utile sans dépense démesurée, Bird S 4B est un petit modèle de 4 milliards de paramètres, conçu en France, qui fait le travail courant — mails, documents, recherche — et montre ce que chaque réponse a coûté. Là où le secteur grossit par réflexe, Bird Models choisit la taille juste, mesure, et le dit.

**Credo** — « Nous créons de tout petits modèles, performants et sobres, plutôt que toujours plus gros. »

**Signature** — « Petit par conviction. »

**Ton** — Phrases courtes. Concret avant abstrait. Chaleureux, un peu audacieux, jamais moralisateur. On prouve, on ne proclame pas. On dit ce qu'on ne sait pas.

**Trois mots** — Juste. Sobre. Franc.

**À ne jamais écrire** : « le meilleur », « révolutionnaire », « zéro impact », « vert », « hébergé en France », « données en France », le nom du modèle de base, des dates de feuille de route.

---

# VERSION FRANÇAISE

## Navigation (FR)

- Logo : Bird Models
- Liens : La philosophie · Notre démarche · Empreinte · Contact
- Langue : EN
- Bouton : **Essayer Bird**

---

## Page 1 — Accueil : « La philosophie »

`<title>` Bird Models — Petit par conviction
`meta description` Bird Models conçoit de tout petits modèles d'IA, performants et sobres. Bird S 4B, assistant de travail en français et en anglais, montre ce que coûte chaque réponse.

### Hero

Surtitre : Bird Models · conçu en France

# Petit par conviction.

Nous créons de tout petits modèles, performants et sobres, plutôt que toujours plus gros.

Bird S 4B est un assistant de travail de 4 milliards de paramètres. Il rédige, il cherche, il prépare vos fichiers. Et il vous dit ce que ça a coûté.

[Essayer Bird]  ·  Lire notre démarche →

Visuel : capture `welcome` (écran d'accueil de Bird).
Texte alternatif : « Écran d'accueil de l'assistant Bird. »

### Le problème — « Toujours plus gros »

## Toujours plus gros. Pour quoi faire ?

La course dominante de l'IA va vers toujours plus gros : plus de paramètres, plus de calcul.

Pourtant, l'essentiel de nos journées tient en tâches simples. Répondre à un mail. Mettre une facture dans un tableau. Préparer cinq diapositives. Trouver une source.

Pour ça, on n'a pas besoin d'un géant. On a besoin d'un outil juste.

### Notre réponse

## La bonne taille, pas la plus grande.

Bird S 4B part d'un modèle ouvert sous licence Apache 2.0. Nous l'avons spécialisé pour le travail de bureau, en français et en anglais.

Le calcul nécessaire pour écrire un mot croît avec la taille du modèle. Avec 4 milliards de paramètres actifs contre environ 400 milliards pour un grand modèle dense, Bird demande en théorie environ 100 fois moins de calcul par mot généré.

En théorie seulement : ça ne se traduit pas un pour un en énergie. Nous le disons, et nous mesurons le reste.

### Nos principes

## Cinq principes. Une preuve pour chacun.

**1. Petit d'abord.**
On commence par le plus petit modèle qui fait le travail.
*Preuve : 4 milliards de paramètres. Le dernier entraînement a consommé 1,8 kWh mesurés sur un seul GPU.*

**2. Chaque réponse a un prix, et on l'affiche.**
Pas de dépense invisible.
*Preuve : sous chaque réponse, Bird montre les tokens, le temps de calcul et une estimation d'énergie d'après les tokens, avec sa fourchette et ses sources.*

**3. Rien de superflu par défaut.**
Le mode « Réflexion » existe, mais il est coupé tant que vous ne l'activez pas : il coûte plus.
*Preuve : le serveur se met en veille quand personne ne l'utilise.*

**4. Vous gardez la main.**
Bird propose. Vous décidez.
*Preuve : il rédige vos mails mais ne les envoie jamais. Il demande votre accord avant d'agir après un contenu suspect.*

**5. On dit ce qu'on ne sait pas.**
Un petit modèle se trompe plus qu'un très grand. Nous préférons l'écrire ici que vous le laisser découvrir.
*Preuve : le produit l'écrit en clair : Bird est un petit modèle, il peut se tromper. Relisez ce qui compte.*

### Ce que fait Bird

## Ce que Bird fait aujourd'hui.

Tout ce qui suit fonctionne dans le produit. Captures réelles.

**Des présentations, prêtes à ouvrir.**
Bird crée des fichiers PowerPoint, Word et Excel, avec un aperçu avant de télécharger.
Visuel : `real-slides` — alt : « Bird génère une présentation PowerPoint avec aperçu. »

**Des documents, pas des brouillons perdus.**
Une note, un compte rendu, un courrier : Bird produit un vrai fichier Word.
Visuel : `real-document` — alt : « Document Word créé par Bird, avec aperçu. »

**Une photo de facture devient un tableau.**
Bird lit les images et les documents joints. Il montre les étapes suivies et cite le fichier source.
Visuel : `image` — alt : « Bird transforme la photo d'une facture en tableau, avec ses étapes et sa source. »

**Vos pièces jointes, lues pour vous.**
Déposez un document : Bird le résume, en extrait l'utile, répond à vos questions dessus.
Visuel : `attachments` — alt : « Documents joints à une conversation avec Bird. »

**Le web, avec ses sources.**
Bird cherche en ligne et cite d'où vient l'information. S'il repère des instructions cachées dans une page, il le signale et vous demande confirmation avant d'agir.

**Des mails, jamais envoyés à votre place.**
Bird rédige. Vous relisez, vous envoyez.

**Dans la poche aussi.**
Prenez une photo, posez la question.
Visuel : `mobile-photo` — alt : « Bird sur mobile, à partir d'une photo. »

### Nos limites, sans détour

## Ce que Bird ne fait pas aussi bien.

Bird est petit. Il fait plus d'erreurs que les très grands modèles.

Il peut se tromper sur un calcul. Il lui arrive d'inventer un détail, comme un lien.

Alors relisez ce qui compte. C'est vrai pour tout assistant. Chez nous, c'est écrit.

### Empreinte — teaser

## Ce que coûte une réponse.

Pour une requête courte (2 000 tokens lus, 500 écrits), notre estimation d'après les tokens : **≈ 0,07 Wh**.
*Méthode : 2 × 0,006 Wh + 0,5 × 0,10 Wh = 0,062 Wh, arrondi à 0,07 Wh, service complet compris.*

En génération, sur notre banc de mesure : **0,36 Wh pour 1 000 tokens générés**.
*GPU seul, NVIDIA A10G, requêtes groupées.*

Pour situer, chiffres publiés par d'autres :
- OpenAI : environ 0,34 Wh par requête ChatGPT moyenne (Sam Altman, « The Gentle Singularity », juin 2025 ; méthode non publiée).
- Google : 0,24 Wh pour la requête texte médiane de Gemini (août 2025, arxiv.org/abs/2508.15734).

Les méthodes diffèrent. Ces chiffres ne se comparent pas ligne à ligne. Nous expliquons pourquoi.

→ Voir la méthode complète

Visuel : capture `report` — alt : « Écran Empreinte de Bird : tokens, temps de calcul et énergie estimée d'une conversation. »

### Prochaines étapes

## Prochaines étapes.

Ce sont des intentions, pas des promesses datées.

- **Encore plus petit.** Un modèle plus léger pour les tâches simples.
- **Chez vous.** Une version quantifiée, capable de tourner en local.
- **Plus de français métier.** Davantage de données d'entreprise en français.
- **Une meilleure recherche.** Des recherches web plus solides, toujours citées.

### CTA final

## Essayez la bonne taille.

Bird S 4B est prêt pour vos mails, vos fichiers et vos recherches. Vous verrez ce que chaque réponse coûte.

[Essayer Bird]

---

## Page 2 — « Notre démarche »

`<title>` Notre démarche — Bird Models
`meta description` Petits modèles, mesures réelles, honnêteté sur les limites et une base ouverte : comment Bird Models construit Bird S 4B.

# Notre démarche.

Construire petit demande plus de rigueur, pas moins. Voici comment nous travaillons.

### 1. Des petits modèles, choisis exprès

## Partir du besoin, pas de la taille.

On ne se demande pas « quel est le plus gros modèle possible ? ». On se demande « quel est le plus petit qui fait bien ce travail ? ».

Bird S 4B compte 4 milliards de paramètres. Il est spécialisé pour le travail courant : rédiger, résumer, chercher, produire des fichiers. En français et en anglais.

Un modèle plus petit demande moins de calcul à chaque mot écrit. C'est un levier direct sur le calcul ; l'énergie dépend aussi du matériel et de l'usage.

### 2. Mesurer, puis publier

## Ce qu'on ne mesure pas, on ne le promet pas.

- **Entraînement** : la version actuelle a consommé 1,8 kWh, mesurés sur le GPU (1 × NVIDIA L40S, 5 h 26).
- **Génération** : 0,36 Wh pour 1 000 tokens générés sur notre banc (GPU seul, NVIDIA A10G, requêtes groupées).
- **Dans le produit** : chaque réponse affiche ses tokens, son temps et une estimation d'énergie d'après ses tokens.

Nous testons aussi la qualité. Notre banc d'essai interne compte 1 369 cas automatiques, notés de 0 à 1 :

| Ce qu'on teste | Score |
|---|---|
| Appel d'outils | 0,89 |
| Sortie JSON valide | 0,98 |
| Concision | 0,97 |
| Résistance aux instructions cachées | 1,00 |
| Réponse dans la langue de l'utilisateur | 1,00 |

*Banc d'essai interne. Ces scores mesurent nos cas, pas tous les usages.*

### 3. Honnêtes sur les limites

## Un petit modèle se trompe plus. On le dit.

Bird fait plus d'erreurs que les très grands modèles. Il peut se tromper sur un calcul ou inventer un détail.

Nous ne le cachons pas : le produit l'écrit en clair, « Bird est un petit modèle : il peut se tromper ». Et le produit est conçu pour que vous gardiez la main :

- il montre ses étapes ;
- il cite ses sources ;
- il rédige les mails sans jamais les envoyer ;
- il signale les instructions cachées dans une page web et demande confirmation avant d'agir.

### 4. Une base ouverte

## Construit sur l'ouvert.

Bird S 4B part d'un modèle ouvert, publié sous licence Apache 2.0. Nous l'avons ensuite spécialisé.

Partir d'une base ouverte, c'est éviter de refaire un entraînement complet. C'est aussi s'appuyer sur un travail que d'autres peuvent examiner.

### 5. Sobre par défaut

## Le réglage le plus économe est le réglage d'origine.

- Le mode « Réflexion » est coupé par défaut, parce qu'il coûte plus.
- Le serveur se met en veille quand personne ne l'utilise.
- Vos conversations restent dans votre navigateur.

### Qui nous sommes

## Une équipe française.

Bird Models est une équipe française. Bird S 4B est conçu en France.

[Essayer Bird]

---

## Page 3 — « Empreinte »

`<title>` Empreinte — Bird Models
`meta description` Méthode, mesures et comparaisons sourcées : ce que consomment l'entraînement et les réponses de Bird S 4B, et les limites de ces chiffres.

# Empreinte.

Nos chiffres, comment on les obtient, et ce qu'ils ne disent pas.

### Notre méthode

## Comment on compte.

**Dans le produit.** Chaque réponse affiche trois choses : les tokens lus et écrits, le temps de calcul, et une estimation d'énergie.

Cette estimation part des **tokens** : 0,10 Wh pour 1 000 tokens écrits et 0,006 Wh pour 1 000 tokens lus, valeurs tirées de mesures publiées de serveurs vLLM, ramenées à Bird S 4B sur une NVIDIA L4 et comptées pour tout le service (GPU × 1,72). Le détail de la réponse donne la fourchette et les sources.

**Ce qu'on ne compte pas.** La fabrication du matériel, le réseau, votre appareil. L'eau est estimée à partir de la même énergie : 0,15 L d'eau de refroidissement par kWh, soit ≈ 0,011 mL par requête courte (0,0105 arrondi au-dessus). Nous ne convertissons pas en CO₂ quand l'intensité carbone du réseau n'est pas déclarée.

**Où ça tourne.** Le modèle est servi depuis AWS, région us-east-1. Conçu en France, oui ; hébergé en France, non. Vos conversations, elles, restent dans votre navigateur.

### Nos chiffres

## Ce que nous avons mesuré.

| | Valeur | Méthode |
|---|---|---|
| Entraînement de la version actuelle | **1,8 kWh** | Mesuré sur le GPU. 1 × NVIDIA L40S, 5 h 26. |
| Génération | **0,36 Wh / 1 000 tokens** | Notre banc de mesure. GPU seul, NVIDIA A10G, requêtes groupées. |
| Une requête courte | **≈ 0,07 Wh** | D'après les tokens : 2 000 lus × 0,006 Wh / 1 000 + 500 écrits × 0,10 Wh / 1 000 = 0,062 Wh, arrondi à 0,07 Wh. |

### Le calcul par token

## Pourquoi la taille compte.

Le calcul nécessaire pour générer un token croît avec le nombre de paramètres actifs. Bird en a 4 milliards. Un grand modèle dense peut en avoir autour de 400 milliards.

Soit environ **100 fois moins de calcul par token, en théorie**.

En pratique, l'énergie ne suit pas un pour un : le matériel, le taux d'occupation, la longueur des réponses et l'infrastructure changent tout. Ce ratio indique une direction, pas une économie garantie.

### Les chiffres publiés par d'autres

## Pour situer.

| Source | Énergie | Eau | Précisions |
|---|---|---|---|
| OpenAI — requête ChatGPT moyenne | ≈ 0,34 Wh | ≈ 0,32 mL | Sam Altman, « The Gentle Singularity », juin 2025. Méthode non publiée. |
| Google — requête texte médiane de Gemini | 0,24 Wh | 0,26 mL | Août 2025. arxiv.org/abs/2508.15734 |
| Bird S 4B — requête courte | ≈ 0,07 Wh | ≈ 0,011 mL | 2 000 tokens lus, 500 écrits. Service complet (× 1,72), périmètre comparable à Google. Eau : 0,15 L/kWh (WUE 2024 publiée par l'hébergeur, AWS Sustainability Report 2024 ; ne pas nommer sur le site). |

### Les précautions

## Ce que ce tableau ne permet pas de dire.

- **Les méthodes diffèrent.** Moyenne d'un côté, médiane de l'autre, requête courte type chez nous. Périmètres différents. Une méthode n'est même pas publiée.
- **Les requêtes diffèrent.** Une « requête » ne fait pas la même longueur partout.
- **Ce n'est pas un classement.** Nous publions nos chiffres à côté des leurs pour donner un ordre de grandeur, pas pour annoncer une victoire.

Si vous avez une meilleure méthode, écrivez-nous. Nous la préférerons à la nôtre.

[Essayer Bird]

---

## Section — « Contact »

## Parlons-en.

Une question, une idée, une méthode plus juste ? Écrivez-nous.

**contact@birdmodels.example**
`[À REMPLACER : adresse de contact provisoire]`

---

## Pied de page (FR)

Bird Models · Équipe française · Bird S 4B conçu en France
Petit par conviction.

Cette page pèse **[XXX] Ko**. Mesuré, pas estimé. Aucun traceur, aucune police externe.
*(Remplacer [XXX] par le poids réel mesuré de la page d'accueil.)*

La philosophie · Notre démarche · Empreinte · Contact · English

---
---

# ENGLISH VERSION

## Navigation (EN)

- Logo: Bird Models
- Links: Philosophy · Our approach · Footprint · Contact
- Language: FR
- Button: **Try Bird**

---

## Page 1 — Home: "Philosophy"

`<title>` Bird Models — Small by conviction
`meta description` Bird Models builds very small AI models that are capable and frugal. Bird S 4B, a work assistant in French and English, shows what every answer costs.

### Hero

Eyebrow: Bird Models · designed in France

# Small by conviction.

We build very small models, capable and frugal, instead of ever bigger ones.

Bird S 4B is a 4-billion-parameter work assistant. It drafts, it searches, it prepares your files. And it tells you what that cost.

[Try Bird]  ·  Read our approach →

Visual: `welcome` — alt: "Bird's welcome screen."

### The problem

## Ever bigger. To do what?

The dominant race in AI is towards ever bigger: more parameters, more compute.

Yet most of our working day is simple tasks. Reply to an email. Put an invoice into a spreadsheet. Build five slides. Find a source.

For that, you don't need a giant. You need the right tool.

### Our answer

## The right size, not the biggest.

Bird S 4B starts from an open model released under the Apache 2.0 licence. We specialised it for office work, in French and English.

The compute needed to write each word grows with model size. With 4 billion active parameters versus about 400 billion for a large dense model, Bird needs roughly 100 times less compute per generated token, in theory.

Only in theory: it doesn't translate one-to-one into energy. We say so, and we measure the rest.

### Principles

## Five principles. One proof each.

**1. Small first.**
We start with the smallest model that does the job.
*Proof: 4 billion parameters. The latest training run used 1.8 kWh, measured on a single GPU.*

**2. Every answer has a cost, and we show it.**
No hidden spend.
*Proof: under every answer, Bird shows tokens, compute time and an energy estimate from tokens, with its range and sources.*

**3. Nothing extra by default.**
Reasoning mode exists, but it stays off until you turn it on: it costs more.
*Proof: the server goes to sleep when nobody is using it.*

**4. You stay in charge.**
Bird suggests. You decide.
*Proof: it drafts your emails but never sends them. It asks for your go-ahead before acting after suspicious content.*

**5. We say what we don't know.**
A small model makes more mistakes than a very large one. We'd rather write it here than let you find out.
*Proof: the product says it plainly: Bird is a small model, it can be wrong. Check what matters.*

### What Bird does

## What Bird does today.

Everything below works in the product. Real screenshots.

**Slides, ready to open.**
Bird creates PowerPoint, Word and Excel files, with a preview before you download.
Visual: `real-slides` — alt: "Bird generating a PowerPoint deck with preview."

**Documents, not lost drafts.**
A memo, minutes, a letter: Bird produces a real Word file.
Visual: `real-document` — alt: "Word document created by Bird, with preview."

**An invoice photo becomes a table.**
Bird reads images and attached documents. It shows its steps and cites the source file.
Visual: `image` — alt: "Bird turning an invoice photo into a table, with its steps and source."

**Your attachments, read for you.**
Drop in a document: Bird summarises it, pulls out what matters, answers your questions.
Visual: `attachments` — alt: "Documents attached to a Bird conversation."

**The web, with sources.**
Bird searches online and cites where information comes from. If it spots hidden instructions in a page, it flags them and asks you before acting.

**Emails, never sent for you.**
Bird drafts. You read, you send.

**In your pocket too.**
Take a photo, ask your question.
Visual: `mobile-photo` — alt: "Bird on mobile, working from a photo."

### Limits

## What Bird doesn't do as well.

Bird is small. It makes more mistakes than very large models.

It can get a calculation wrong. It sometimes invents a detail, such as a link.

So check what matters. That's true of any assistant. We just write it down.

### Footprint teaser

## What an answer costs.

For a short request (2,000 tokens read, 500 written), our token-based estimate: **≈ 0.07 Wh**.
*Method: 2 × 0.006 Wh + 0.5 × 0.10 Wh = 0.062 Wh, rounded up to 0.07 Wh, whole service included.*

For generation, on our benchmark: **0.36 Wh per 1,000 generated tokens**.
*GPU only, NVIDIA A10G, batched requests.*

For context, figures published by others:
- OpenAI: about 0.34 Wh per average ChatGPT query (Sam Altman, "The Gentle Singularity", June 2025; method not published).
- Google: 0.24 Wh for the median Gemini text prompt (August 2025, arxiv.org/abs/2508.15734).

Methods differ. These numbers don't compare line by line. We explain why.

→ See the full method

Visual: `report` — alt: "Bird's Footprint screen: tokens, compute time and estimated energy for a conversation."

### Next steps

## Next steps.

Intentions, not dated promises.

- **Even smaller.** A lighter model for simple tasks.
- **On your machine.** A quantised version that can run locally.
- **More business French.** More French business data.
- **Better research.** Stronger web research, always with citations.

### Final CTA

## Try the right size.

Bird S 4B is ready for your emails, files and research. You'll see what every answer costs.

[Try Bird]

---

## Page 2 — "Our approach"

`<title>` Our approach — Bird Models
`meta description` Small models, real measurements, honesty about limits and an open base: how Bird Models builds Bird S 4B.

# Our approach.

Building small takes more rigour, not less. Here's how we work.

### 1. Small models, on purpose

## Start from the need, not the size.

We don't ask "what's the biggest model we can run?". We ask "what's the smallest one that does this job well?".

Bird S 4B has 4 billion parameters. It's specialised for everyday work: drafting, summarising, searching, producing files. In French and English.

A smaller model needs less compute for every word it writes. It is a direct lever on compute; energy also depends on hardware and utilisation.

### 2. Measure, then publish

## If we haven't measured it, we don't promise it.

- **Training**: the current version used 1.8 kWh, measured on the GPU (1 × NVIDIA L40S, 5 h 26 min).
- **Generation**: 0.36 Wh per 1,000 generated tokens on our benchmark (GPU only, NVIDIA A10G, batched).
- **In the product**: every answer shows its tokens, its time and an energy estimate from its tokens.

We test quality too. Our internal benchmark has 1,369 automatic cases, scored 0 to 1:

| What we test | Score |
|---|---|
| Tool calling | 0.89 |
| Valid JSON output | 0.98 |
| Concision | 0.97 |
| Resistance to hidden instructions | 1.00 |
| Answers in the user's language | 1.00 |

*Internal benchmark. These scores measure our cases, not every use.*

### 3. Honest about limits

## A small model gets more wrong. We say so.

Bird makes more mistakes than very large models. It can get a calculation wrong or invent a detail.

We don't hide it: the product says it plainly, “Bird is a small model: it can be wrong”. And the product is built so you stay in charge:

- it shows its steps;
- it cites its sources;
- it drafts emails but never sends them;
- it flags hidden instructions in web pages and asks before acting.

### 4. An open base

## Built on open work.

Bird S 4B starts from an open model released under the Apache 2.0 licence. We then specialised it.

Starting from an open base means not repeating a full training run. It also means building on work others can examine.

### 5. Frugal by default

## The leanest setting is the default one.

- Reasoning mode is off by default, because it costs more.
- The server goes to sleep when nobody is using it.
- Your conversations stay in your browser.

### Who we are

## A French team.

Bird Models is a French team. Bird S 4B is designed in France.

[Try Bird]

---

## Page 3 — "Footprint"

`<title>` Footprint — Bird Models
`meta description` Method, measurements and sourced comparisons: what training and answers from Bird S 4B consume, and the limits of those numbers.

# Footprint.

Our numbers, how we get them, and what they don't say.

### Method

## How we count.

**In the product.** Every answer shows three things: tokens read and written, compute time, and an energy estimate.

That estimate starts from **tokens**: 0.10 Wh per 1,000 tokens written and 0.006 Wh per 1,000 tokens read, values drawn from published measurements of vLLM servers, scaled to Bird S 4B on an NVIDIA L4 and counted for the whole service (GPU × 1.72). The answer's detail gives the range and the sources.

**What we don't count.** Hardware manufacturing, the network, your device. Water is estimated from the same energy: 0.15 L of cooling water per kWh, i.e. ≈ 0.011 mL per short request (0.0105 rounded up). We don't convert to CO₂ when the grid's carbon intensity isn't declared.

**Where it runs.** The model is served from AWS, us-east-1 region. Designed in France, yes; hosted in France, no. Your conversations stay in your browser.

### Our numbers

## What we measured.

| | Value | Method |
|---|---|---|
| Training the current version | **1.8 kWh** | Measured on the GPU. 1 × NVIDIA L40S, 5 h 26 min. |
| Generation | **0.36 Wh / 1,000 tokens** | Our benchmark. GPU only, NVIDIA A10G, batched. |
| One short request | **≈ 0.07 Wh** | From tokens: 2,000 read × 0.006 Wh / 1,000 + 500 written × 0.10 Wh / 1,000 = 0.062 Wh, rounded up to 0.07 Wh. |

### Compute per token

## Why size matters.

The compute needed to generate a token grows with the number of active parameters. Bird has 4 billion. A large dense model can have around 400 billion.

That's roughly **100 times less compute per token, in theory**.

In practice, energy doesn't follow one-to-one: hardware, utilisation, answer length and infrastructure all change the result. The ratio shows a direction, not a guaranteed saving.

### Published figures

## For context.

| Source | Energy | Water | Notes |
|---|---|---|---|
| OpenAI — average ChatGPT query | ≈ 0.34 Wh | ≈ 0.32 mL | Sam Altman, "The Gentle Singularity", June 2025. Method not published. |
| Google — median Gemini text prompt | 0.24 Wh | 0.26 mL | August 2025. arxiv.org/abs/2508.15734 |
| Bird S 4B — short request | ≈ 0.07 Wh | ≈ 0.011 mL | 2,000 tokens read, 500 written. Whole service (× 1.72), comparable scope to Google. Water: 0.15 L/kWh (host's published 2024 WUE, AWS Sustainability Report 2024; do not name on the site). |

### Caveats

## What this table doesn't tell you.

- **Methods differ.** An average on one side, a median on the other, a typical short request for us. Different scopes. One method isn't even published.
- **Queries differ.** A "query" isn't the same length everywhere.
- **It's not a ranking.** We put our numbers next to theirs to give an order of magnitude, not to claim a win.

If you have a better method, write to us. We'll prefer it to ours.

[Try Bird]

---

## Section — "Contact"

## Let's talk.

A question, an idea, a better method? Write to us.

**contact@birdmodels.example**
`[TO BE REPLACED: placeholder contact address]`

---

## Footer (EN)

Bird Models · French team · Bird S 4B designed in France
Small by conviction.

This page weighs **[XXX] KB**. Measured, not estimated. No trackers, no external fonts.
*(Replace [XXX] with the real measured weight of the home page.)*

Philosophy · Our approach · Footprint · Contact · Français
