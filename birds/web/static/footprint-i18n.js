// Strings of the footprint module (footprint.js), French first with English parity (tests/js/footprint.test.mjs).
// Kept apart from i18n.js and merged into its STRINGS at load, under the footprint.* prefix.

export const FOOTPRINT_STRINGS = {
  fr: {
    "footprint.answer.title": "Impact de cette réponse",
    "footprint.energy": "Énergie",
    "footprint.emissions": "Émissions",
    "footprint.water": "Eau",
    "footprint.water.ratio": "au ratio d'un grand centre de données",
    "footprint.gpu": "Carte graphique",
    "footprint.range": "de {low} à {high}",
    "footprint.kind.estimated": "estimé",
    "footprint.kind.measured": "mesuré",
    "footprint.kind.demo": "démo",
    "footprint.grid.label": "Électricité du réseau",
    "footprint.grid.label.if": "Émissions si l'électricité vient du réseau",
    "footprint.grid.undeclared":
      "L'opérateur n'a pas déclaré le réseau électrique du serveur : le choix vous revient.",
    "footprint.grid.fr": "France",
    "footprint.grid.eu": "Europe",
    "footprint.grid.world": "Monde",
    "footprint.grid.operator": "Ce serveur",
    "footprint.grid.note.operator":
      "{g} g CO₂e par kWh, déclarés par l'opérateur de ce serveur",
    "footprint.grid.value": "{g} g CO₂e par kWh",
    "footprint.licence.cite": "Citation avec la source",
    "footprint.licence.cc-by": "CC BY 4.0",
    "footprint.licence.ademe": "ADEME, réutilisation non commerciale avec mention de la source",
    "footprint.licence.public": "Domaine public",
    "footprint.gpu.line": "Bird a tourné sur une carte graphique pendant {s}.",
    "footprint.gpu.what": "Qu'est-ce qu'une carte graphique ?",
    "footprint.gpu.explain":
      "Une carte graphique (GPU) est une puce qui fait des milliers de calculs à la fois : c'est elle qui écrit chaque mot de la réponse. Moins le modèle a de paramètres, moins il y a de calcul par mot : la carte travaille moins longtemps et consomme moins. Elle sert aussi plusieurs conversations en même temps, et l'estimation n'attribue à la vôtre que sa part.",
    "footprint.tokens": "{in} tokens lus · {out} écrits",
    "footprint.equiv.title": "Pour se représenter",
    "footprint.equiv.streaming": "{v} de vidéo en streaming",
    "footprint.equiv.car": "{v} en voiture thermique",
    "footprint.equiv.search.n": "{v} recherche(s) sur le web",
    "footprint.equiv.email.n": "{v} e-mail(s)",
    "footprint.equiv.phone.n": "{v} charge(s) complète(s) de smartphone",
    "footprint.equiv.search.per":
      "1 recherche sur le web ≈ {n} réponses comme celle-ci",
    "footprint.equiv.email.per": "1 e-mail ≈ {n} réponses comme celle-ci",
    "footprint.equiv.phone.per":
      "1 charge de smartphone ≈ {n} réponses comme celle-ci",
    "footprint.equiv.search.share": "{v} % d'une recherche sur le web",
    "footprint.equiv.email.share": "{v} % d'un e-mail",
    "footprint.equiv.phone.share": "{v} % d'une charge de smartphone",
    "footprint.equiv.note":
      "Bird : électricité seule, hors fabrication du matériel. Les équivalents ADEME sont en cycle de vie : ils incluent la fabrication des appareils et des centres de données (détail dans la méthode). La charge de smartphone est comptée en énergie, quel que soit le réseau.",
    "footprint.conv.title": "Cette conversation",
    "footprint.conv.line": "{n} réponse(s) · {wh} · {g}",
    "footprint.more": "Méthode, sources et pourquoi les petits modèles",
    "footprint.demo":
      "Chiffres de démonstration : les tokens sont écrits à l'avance, puis passés dans la vraie formule d'estimation.",
    "footprint.hero.conv": "Cette conversation",
    "footprint.hero.all": "Sur cet appareil depuis le {date}",
    "footprint.hero.all.empty": "Sur cet appareil",
    "footprint.hero.answers": "{n} réponse(s) · {in} tokens lus · {out} écrits",
    "footprint.hero.energy": "Énergie consommée",
    "footprint.hero.none":
      "L'énergie apparaîtra dès la première réponse dont elle est connue.",
    "footprint.chart.title": "Énergie par réponse",
    "footprint.chart.ref": "Grand assistant : {wh} par requête",
    "footprint.chart.bar": "Réponse {i} : {wh}, de {low} à {high}",
    "footprint.chart.last": "{n} dernières réponses",
    "footprint.vs.title": "Si vous aviez utilisé un grand assistant",
    "footprint.vs.published":
      "Grand assistant, chiffre publié avec sa méthode (août 2025)",
    "footprint.vs.stated":
      "Autre grand assistant, chiffre annoncé sans méthode publiée (juin 2025)",
    "footprint.vs.bird": "Bird, pour ces {n} réponse(s)",
    "footprint.vs.saved":
      "Énergie économisée : ≈ {saved}, de {low} à {high} selon la charge du serveur.",
    "footprint.vs.saved.maybe":
      "Énergie économisée : ≈ {saved}. Dans le pire cas de la fourchette (une requête seule sur la carte), Bird dépasserait la référence de {over}.",
    "footprint.vs.times": "≈ {x} fois moins, en estimation centrale",
    "footprint.vs.more": "≈ {x} fois plus, en estimation centrale",
    "footprint.vs.times.range":
      "Selon la charge du serveur : de ≈ {low} à ≈ {high} fois moins.",
    "footprint.vs.times.range.worse":
      "Selon la charge du serveur : jusqu'à ≈ {high} fois moins ; dans le pire cas (une requête seule sur la carte), ≈ {worse} fois plus.",
    "footprint.vs.more.range":
      "Selon la charge du serveur : de ≈ {low} à ≈ {high} fois plus.",
    "footprint.vs.note":
      "Même périmètre que le chiffre publié (août 2025) : tout le service (puces, machines au repos, refroidissement) ; le second chiffre n'indique pas son périmètre. Bird est estimé d'après ses tokens, les grands assistants d'après le chiffre de leur fournisseur, par requête texte.",
    "footprint.vs.source": "source",
    "footprint.story.title": "Pourquoi les petits modèles sont l'avenir",
    "footprint.story.lead":
      "Bird est léger par conception. Cinq raisons ; les chiffres d'énergie, d'eau et de réseau sont sourcés dans la méthode, en fin de page.",
    "footprint.s1.title": "Moins de calcul par mot",
    "footprint.s1.p":
      "Bird S compte {b} milliards de paramètres ; un grand modèle dense, de l'ordre de {big} milliards. Le calcul de chaque mot écrit croît avec le nombre de paramètres actifs (environ 2 opérations par paramètre) : Bird en fait de l'ordre de {x} fois moins.",
    "footprint.s1.legend": "1 carré = {b} milliards de paramètres",
    "footprint.s1.bird": "Bird S",
    "footprint.s1.big": "Grand modèle dense",
    "footprint.s2.title": "Moins d'énergie et d'eau par réponse",
    "footprint.s2.p":
      "Ici, une réponse de Bird demande en moyenne ≈ {wh} et ≈ {ml} d'eau, au ratio publié d'un grand centre de données. Une requête médiane à un grand assistant : {refwh} et {refml}.",
    "footprint.s2.p.none":
      "Bird demande environ {perk} pour 1 000 tokens écrits, service complet compris. Une requête médiane à un grand assistant : {refwh} et {refml} d'eau.",
    "footprint.s2.bird": "Bird, une réponse",
    "footprint.s2.ref": "Grand assistant, une requête",
    "footprint.s3.title":
      "Une carte graphique modeste, là où l'énergie est propre",
    "footprint.s3.p":
      "Bird tourne sur une carte graphique modeste, et un petit modèle peut aller sur du matériel plus petit encore. On peut donc l'installer où l'on veut : près d'un barrage, d'un parc solaire ou d'un réseau bas carbone. Pour la même énergie, {what} émet {fr} en France, {eu} en Europe et {world} en moyenne mondiale.",
    "footprint.s3.what.answer": "une réponse moyenne",
    "footprint.s3.what.wh": "1 Wh",
    "footprint.s4.title": "Il dort quand personne ne s'en sert",
    "footprint.s4.p":
      "Le serveur du modèle se met en veille après un délai sans requête : la carte graphique s'arrête au lieu de tourner à vide. Au réveil, la première réponse peut prendre de quelques dizaines de secondes à quelques minutes.",
    "footprint.s4.busy": "réponses",
    "footprint.s4.idle": "veille",
    "footprint.s5.title": "Spécialisé à moindre coût, pour chaque entreprise",
    "footprint.s5.p":
      "Un petit modèle s'adapte aux tâches d'une entreprise (ses documents, son vocabulaire, ses outils) avec peu de calcul, et il reste installé où elle le décide.",
    "footprint.s6.title": "Conçu en France",
    "footprint.s6.p":
      "Bird est un modèle français : léger, libre d'être installé où l'on veut, transparent sur ce qu'il consomme.",
    "footprint.method.title": "Méthode et sources",
    "footprint.method.p":
      "Énergie : estimée d'après les tokens lus et écrits (valeurs par token tirées de mesures publiées, service complet), ou mesurée quand le modèle tourne sur la même machine. Émissions = énergie × intensité carbone du réseau choisi. Eau = énergie × le ratio publié par un grand fournisseur pour ses centres de données (0,26 mL pour 0,24 Wh) : celui du centre qui héberge Bird n'est pas connu. Équivalences = impact ÷ facteur de la source. L'entraînement n'est pas compté.",
    "footprint.method.col.what": "Donnée",
    "footprint.method.col.value": "Valeur",
    "footprint.method.col.source": "Source",
    "footprint.method.col.licence": "Licence",
    "footprint.method.grid": "Réseau {name}",
    "footprint.method.water": "Eau par Wh",
    "footprint.method.ref.published": "Grand assistant (méthode publiée)",
    "footprint.method.ref.stated": "Grand assistant (sans méthode publiée)",
    "footprint.method.tokens.out": "Énergie par 1 000 tokens écrits",
    "footprint.method.flops": "Calcul par token écrit",
    "footprint.method.flops.value": "≈ 2 opérations par paramètre actif",
    "footprint.method.tokens.in": "Énergie par 1 000 tokens lus",
    "footprint.method.eq.streaming": "Streaming vidéo, 1 h",
    "footprint.method.eq.car": "Voiture thermique, 1 km",
    "footprint.method.eq.search": "Recherche sur le web",
    "footprint.method.eq.email": "E-mail (étiquette moyenne ADEME)",
    "footprint.method.made": "dont {g} de fabrication",
    "footprint.method.eq.phone": "Charge de smartphone",
    "footprint.method.tokens.source":
      "Mesures publiées de vLLM, ramenées à Bird S (détail : docs/WEB.md)",
    "footprint.all.title": "Tous les chiffres de la période",
    "footprint.reset": "Remettre l'empreinte de cet appareil à zéro",
    "footprint.reset.confirm": "Effacer l'empreinte cumulée sur cet appareil ?",
  },
  en: {
    "footprint.answer.title": "Impact of this answer",
    "footprint.energy": "Energy",
    "footprint.emissions": "Emissions",
    "footprint.water": "Water",
    "footprint.water.ratio": "at a large data centre's ratio",
    "footprint.gpu": "Graphics card",
    "footprint.range": "{low} to {high}",
    "footprint.kind.estimated": "estimated",
    "footprint.kind.measured": "measured",
    "footprint.kind.demo": "demo",
    "footprint.grid.label": "Grid electricity",
    "footprint.grid.label.if": "Emissions if the electricity comes from the grid of",
    "footprint.grid.undeclared":
      "The operator has not declared the server's grid: the choice is yours.",
    "footprint.grid.fr": "France",
    "footprint.grid.eu": "Europe",
    "footprint.grid.world": "World",
    "footprint.grid.operator": "This server",
    "footprint.grid.note.operator":
      "{g} g CO₂e per kWh, declared by this server's operator",
    "footprint.grid.value": "{g} g CO₂e per kWh",
    "footprint.licence.cite": "Quoted with its source",
    "footprint.licence.cc-by": "CC BY 4.0",
    "footprint.licence.ademe": "ADEME, non-commercial reuse with the source named",
    "footprint.licence.public": "Public domain",
    "footprint.gpu.line": "Bird ran on a graphics card for {s}.",
    "footprint.gpu.what": "What is a graphics card?",
    "footprint.gpu.explain":
      "A graphics card (GPU) is a chip that does thousands of calculations at once: it writes every word of the answer. The fewer parameters a model has, the less computation each word takes, so the card works for less time and uses less energy. It also serves several conversations at once, and the estimate charges yours only its share.",
    "footprint.tokens": "{in} tokens read · {out} written",
    "footprint.equiv.title": "To picture it",
    "footprint.equiv.streaming": "{v} of video streaming",
    "footprint.equiv.car": "{v} in a combustion-engine car",
    "footprint.equiv.search.n": "{v} web search(es)",
    "footprint.equiv.email.n": "{v} email(s)",
    "footprint.equiv.phone.n": "{v} full smartphone charge(s)",
    "footprint.equiv.search.per": "1 web search ≈ {n} answers like this one",
    "footprint.equiv.email.per": "1 email ≈ {n} answers like this one",
    "footprint.equiv.phone.per":
      "1 smartphone charge ≈ {n} answers like this one",
    "footprint.equiv.search.share": "{v}% of a web search",
    "footprint.equiv.email.share": "{v}% of an email",
    "footprint.equiv.phone.share": "{v}% of a smartphone charge",
    "footprint.equiv.note":
      "Bird: electricity only, hardware manufacturing not counted. The ADEME equivalents are life-cycle figures: they include making the devices and data centres (details in the method). The smartphone charge is counted in energy, whatever the grid.",
    "footprint.conv.title": "This conversation",
    "footprint.conv.line": "{n} answer(s) · {wh} · {g}",
    "footprint.more": "Method, sources and why small models",
    "footprint.demo":
      "Demo figures: the tokens are written in advance, then run through the real estimate.",
    "footprint.hero.conv": "This conversation",
    "footprint.hero.all": "On this device since {date}",
    "footprint.hero.all.empty": "On this device",
    "footprint.hero.answers":
      "{n} answer(s) · {in} tokens read · {out} written",
    "footprint.hero.energy": "Energy used",
    "footprint.hero.none":
      "Energy will show from the first answer whose energy is known.",
    "footprint.chart.title": "Energy per answer",
    "footprint.chart.ref": "Large assistant: {wh} per prompt",
    "footprint.chart.bar": "Answer {i}: {wh}, {low} to {high}",
    "footprint.chart.last": "last {n} answers",
    "footprint.vs.title": "Had you used a large assistant",
    "footprint.vs.published":
      "Large assistant, figure published with its method (Aug 2025)",
    "footprint.vs.stated":
      "Another large assistant, figure stated without a published method (June 2025)",
    "footprint.vs.bird": "Bird, for these {n} answer(s)",
    "footprint.vs.saved":
      "Energy saved: ≈ {saved}, {low} to {high} depending on server load.",
    "footprint.vs.saved.maybe":
      "Energy saved: ≈ {saved}. At the worst end of the range (one request alone on the card), Bird would exceed the reference by {over}.",
    "footprint.vs.times": "≈ {x} times less, central estimate",
    "footprint.vs.more": "≈ {x} times more, central estimate",
    "footprint.vs.times.range":
      "Depending on server load: ≈ {low} to ≈ {high} times less.",
    "footprint.vs.times.range.worse":
      "Depending on server load: up to ≈ {high} times less; at the worst end (one request alone on the card), ≈ {worse} times more.",
    "footprint.vs.more.range":
      "Depending on server load: ≈ {low} to ≈ {high} times more.",
    "footprint.vs.note":
      "Same boundary as the published figure (Aug 2025): the whole service (chips, idle machines, cooling); the second figure does not state its boundary. Bird is estimated from its tokens, large assistants from their provider's figure per text prompt.",
    "footprint.vs.source": "source",
    "footprint.story.title": "Why small models are the future",
    "footprint.story.lead":
      "Bird is light by design. Five reasons; the energy, water and grid figures are sourced in the method, at the end of the page.",
    "footprint.s1.title": "Less computation per word",
    "footprint.s1.p":
      "Bird S has {b} billion parameters; a large dense model, of the order of {big} billion. The computation of each word written grows with the active parameters (about 2 operations per parameter): Bird does of the order of {x} times less.",
    "footprint.s1.legend": "1 square = {b} billion parameters",
    "footprint.s1.bird": "Bird S",
    "footprint.s1.big": "Large dense model",
    "footprint.s2.title": "Less energy and water per answer",
    "footprint.s2.p":
      "Here, a Bird answer takes on average ≈ {wh} and ≈ {ml} of water, at a large data centre's published ratio. A median prompt to a large assistant: {refwh} and {refml}.",
    "footprint.s2.p.none":
      "Bird takes about {perk} per 1,000 tokens written, whole service included. A median prompt to a large assistant: {refwh} and {refml} of water.",
    "footprint.s2.bird": "Bird, one answer",
    "footprint.s2.ref": "Large assistant, one prompt",
    "footprint.s3.title": "A modest graphics card, where energy is clean",
    "footprint.s3.p":
      "Bird runs on a modest graphics card, and a small model can go on smaller hardware still. So it can be installed anywhere: next to a dam, a solar farm or a low-carbon grid. For the same energy, {what} emits {fr} in France, {eu} in Europe and {world} on the world average.",
    "footprint.s3.what.answer": "an average answer",
    "footprint.s3.what.wh": "1 Wh",
    "footprint.s4.title": "It sleeps when nobody uses it",
    "footprint.s4.p":
      "The model server goes to sleep after a while without requests: the graphics card stops instead of idling. On waking, the first answer can take from a few tens of seconds to a few minutes.",
    "footprint.s4.busy": "answers",
    "footprint.s4.idle": "asleep",
    "footprint.s5.title": "Specialised cheaply, for each company",
    "footprint.s5.p":
      "A small model adapts to a company's tasks (its documents, its vocabulary, its tools) with little computation, and stays installed wherever the company decides.",
    "footprint.s6.title": "Designed in France",
    "footprint.s6.p":
      "Bird is a French model: light, free to be installed anywhere, open about what it uses.",
    "footprint.method.title": "Method and sources",
    "footprint.method.p":
      "Energy: estimated from the tokens read and written (per-token values from published measurements, whole service), or measured when the model runs on the same machine. Emissions = energy × carbon intensity of the chosen grid. Water = energy × the ratio a large provider published for its data centres (0.26 mL for 0.24 Wh): that of the data centre hosting Bird is not known. Equivalents = impact ÷ the source's factor. Training is not counted.",
    "footprint.method.col.what": "Item",
    "footprint.method.col.value": "Value",
    "footprint.method.col.source": "Source",
    "footprint.method.col.licence": "Licence",
    "footprint.method.grid": "Grid: {name}",
    "footprint.method.water": "Water per Wh",
    "footprint.method.ref.published": "Large assistant (published method)",
    "footprint.method.ref.stated": "Large assistant (no published method)",
    "footprint.method.tokens.out": "Energy per 1,000 tokens written",
    "footprint.method.flops": "Computation per token written",
    "footprint.method.flops.value": "≈ 2 operations per active parameter",
    "footprint.method.tokens.in": "Energy per 1,000 tokens read",
    "footprint.method.eq.streaming": "Video streaming, 1 h",
    "footprint.method.eq.car": "Combustion-engine car, 1 km",
    "footprint.method.eq.search": "Web search",
    "footprint.method.eq.email": "Email (ADEME average label)",
    "footprint.method.made": "of which {g} manufacturing",
    "footprint.method.eq.phone": "Smartphone charge",
    "footprint.method.tokens.source":
      "Published vLLM measurements, scaled to Bird S (details: docs/WEB.md)",
    "footprint.all.title": "Every figure for the period",
    "footprint.reset": "Reset this device's footprint",
    "footprint.reset.confirm":
      "Erase the footprint accumulated on this device?",
  },
};
