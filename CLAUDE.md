# Bird — règles du projet

- **Gold quality.** Tout ce qu'on intègre dans Bird (API, outil, donnée) arrive avec un module visuel ou technique soigné :
  une fiche ou un widget conçu pour lui (light/dark, 360 px et bureau, accessible, source et licence affichées), des
  tests, et une capture regardée avant de livrer. Pas d'intégration « brute » qui renverrait seulement du texte au modèle.
- **Le modèle décide, pas des regex.** Choix des outils et modules par le modèle (function calling natif après
  fine-tuning, sorties structurées validées par schéma en attendant) ; les règles écrites à la main ne sont que des
  indices, un filet de secours et un garde-fou contre les faux déclenchements connus. Pas de hard-coding au cas par cas :
  un nouveau module = une entrée de catalogue + des exemples d'entraînement + des cas d'évaluation.
- Best practices : chaque changement de prompt, de routage ou de modèle est mesuré avant / après sur un jeu fixe
  (banc, évaluations live) et les chiffres sont notés ; sorties du modèle toujours validées ; sécurité (injection,
  egress) et confidentialité par défaut.
- Le harnais exécute et vérifie ; les widgets viennent des résultats
  d'outils ou des données de l'utilisateur, jamais du texte du modèle. Rien n'est inventé.
- Ton promotionnel et confiant ; jamais d'auto-dépréciation en avant. Jamais de nombre de GPU ni de matériel, jamais
  l'énergie d'entraînement, jamais le modèle de base, jamais où le modèle tourne.
  Exception voulue : dans le panneau Consommation / Empreinte du chat, on explique que Bird tourne sur une carte
  graphique (GPU) et on détaille énergie et émissions, sourcées ; sans en faire un argument de nombre de cartes.
- Message de marque : Bird, c'est avant tout la **légèreté** et la **liberté d'installer nos modèles** où l'on veut, sur
  des sources d'énergie variées ; toujours mettre en avant le **modèle français** (« conçu en France »). C'est l'introduction
  du site corporate comme de l'accueil du chat.
- Interface claire et simple, au niveau de Claude ou ChatGPT : peu d'éléments à l'écran, beaucoup d'espace, la
  richesse apparaît quand elle sert (modules), jamais d'encombrement.
- **Continuité des échanges.** Quand un échange fait évoluer un élément (document, diapos, site web, graphique, carte,
  tableau…), chaque tour réaffiche l'élément à jour (nouvelle version visible, jamais seulement « c'est fait ») et propose
  2-3 suites pertinentes et concrètes (puces cliquables) ; l'historique des versions reste accessible.
- CSP stricte : le navigateur ne contacte aucun tiers ; tout passe côté serveur par le garde d'egress.
- Français d'abord, parité anglaise.
- Feuille de route et priorités : `docs/ROADMAP.md`.
- Python : `.venv/bin/python -I` pour les scripts ; tests `pytest -q`, lint `ruff check birds tests scripts`,
  banc des déclenchements `.venv/bin/python -I scripts/trigger_bench.py` (ne doit jamais régresser).
- Dans un worktree au `.venv` en lien symbolique, lancer pytest et les scripts **sans** `-I` (`.venv/bin/python -m pytest -q`,
  `.venv/bin/python scripts/trigger_bench.py`) : avec `-I`, Python importe le paquet `birds` du dépôt principal.
- Avant tout commit, lire le vrai résultat des tests : `set -o pipefail` dès qu'on pipe une commande (`… | tail -1 && git commit` committe même si les tests échouent).
