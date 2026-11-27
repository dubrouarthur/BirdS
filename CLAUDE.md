# Bird — règles du projet

- **Gold quality.** Tout ce qu'on intègre dans Bird (API, outil, donnée) arrive avec un module visuel ou technique soigné :
  une fiche ou un widget conçu pour lui (light/dark, 360 px et bureau, accessible, source et licence affichées), des
  tests, et une capture regardée avant de livrer. Pas d'intégration « brute » qui renverrait seulement du texte au modèle.
- Le harnais décide (intents déterministes, pré-appels) ; le petit modèle écrit. Les widgets viennent des résultats
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
- CSP stricte : le navigateur ne contacte aucun tiers ; tout passe côté serveur par le garde d'egress.
- Français d'abord, parité anglaise.
- Feuille de route et priorités : `docs/ROADMAP.md`.
- Python : `.venv/bin/python -I` pour les scripts ; tests `pytest -q`, lint `ruff check birds tests scripts`,
  banc des déclenchements `.venv/bin/python -I scripts/trigger_bench.py` (ne doit jamais régresser).
