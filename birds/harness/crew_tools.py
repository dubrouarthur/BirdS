"""Virtual tools of Mode Agent: typed outputs for the specialists, never offered to the single agent (BIRD_TOOLS).

Each specialist is ONE generation with ONE of these tools. The harness never "runs" them: it reads the arguments,
checks them in code (birds.harness.crew_checks) and keeps what survives. Prompts are short role instructions placed
AFTER the shared data, so parallel siblings share the longest possible prompt prefix (vLLM prefix cache).
"""

from __future__ import annotations

from birds.tools import PRODUCT_TOOLS


def _fn(name: str, desc: str, props: dict, req: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req},
        },
    }


_S = {"type": "string"}
_N = {"type": "number"}

RECORD_FACTS = _fn(
    "record_facts",
    "Record the figures found in the source extract, each with its year, exact value and exact quote.",
    {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": _S,
                    "value": {"type": "string", "description": "The figure exactly as written, with its unit."},
                    "fact": {"type": "string", "description": "One short sentence stating the fact."},
                    "quote": {"type": "string", "description": "The exact words of the extract that hold the figure."},
                },
                "required": ["year", "value", "fact", "quote"],
            },
        }
    },
    ["facts"],
)
RECORD_TABLE = _fn(
    "record_table",
    "Record a table copied from the text: one row per option, values exactly as written.",
    {"columns": {"type": "array", "items": _S}, "rows": {"type": "array", "items": {"type": "array", "items": _S}}},
    ["columns", "rows"],
)
RECORD_ACTIONS = _fn(
    "record_actions",
    "Record every action decided in the numbered notes.",
    {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "description": "Number of the note line (L12 -> 12)."},
                    "owner": {"type": "string", "description": "Who does it, a name from the attendee list."},
                    "action": {"type": "string", "description": "What is to be done, short."},
                    "due": {"type": "string", "description": "Due date exactly as written on that line, or empty."},
                },
                "required": ["line", "owner", "action", "due"],
            },
        }
    },
    ["actions"],
)
COST_MODEL = _fn(
    "cost_model",
    "Describe each offer for the cost computation done by the harness. No arithmetic here.",
    {
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": _S,
                    "monthly_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"label": _S, "amount": _N, "qty": _N},
                            "required": ["label", "amount", "qty"],
                        },
                    },
                    "one_off": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"label": _S, "amount": _N},
                            "required": ["label", "amount"],
                        },
                    },
                    "months": _N,
                    "sla_hours": _N,
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"label": _S, "monthly": _N, "sla_hours": _N},
                            "required": ["label", "monthly"],
                        },
                    },
                },
                "required": ["name", "monthly_items", "one_off", "months"],
            },
        }
    },
    ["offers"],
)
PLAN_SEARCH = _fn(
    "plan_search",
    "Split the request into the sub-questions a researcher would look up, each with one short web query.",
    {
        "sub_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "One precise sub-question of the request."},
                    "query": {"type": "string", "description": "A web search query of 3 to 8 words for it."},
                },
                "required": ["question", "query"],
            },
        }
    },
    ["sub_questions"],
)
VIRTUAL = {t["function"]["name"]: t for t in (RECORD_FACTS, RECORD_TABLE, RECORD_ACTIONS, COST_MODEL, PLAN_SEARCH)}
PRODUCT = {t["function"]["name"]: t for t in PRODUCT_TOOLS}

# What a good deliverable looks like, per tool (the drafters' brief ends with it).
SHAPE = {
    "fr": {
        "make_slides": "Une présentation de {n} diapositives : un titre court par diapositive, 2 à 4 puces courtes, "
        "chaque chiffre suivi de sa source [n]",
        "make_document": "Un document structuré en sections avec un titre clair, des phrases rédigées (pas des notes "
        "recopiées)",
        "draft_email": "Un mail de 150 à 350 mots : objet clair, contexte en une phrase, tableau ou liste des offres, "
        "recommandation explicite et sa raison, prochaine étape",
        "make_sheet": "Un tableur : une ligne par élément, des colonnes nommées, les valeurs telles qu'écrites",
        "make_document_study": "Un document structuré en 4 à 6 sections avec un titre clair, des phrases rédigées "
        "tirées des extraits de sources, chaque chiffre et chaque affirmation tirée d'une source suivie de [n], "
        "toutes les sources utilisées ; si la demande parle d'un tableau ou d'une comparaison, un tableau markdown "
        "(| a | b |) ; une conclusion ou recommandation qui dit sur quoi elle s'appuie",
    },
    "en": {
        "make_slides": "A deck of {n} slides: a short title per slide, 2 to 4 short bullets, every figure followed by "
        "its source [n]",
        "make_document": "A structured document in sections with a clear title, written sentences (not copied notes)",
        "draft_email": "An email of 150 to 350 words: clear subject, one line of context, the offers as a list or "
        "table, an explicit recommendation and its reason, the next step",
        "make_sheet": "A spreadsheet: one row per item, named columns, values as written",
        "make_document_study": "A structured document of 4 to 6 sections with a clear title, written sentences drawn "
        "from the source extracts, every figure and every claim taken from a source followed by [n], every source "
        "used; if the request mentions a table or a comparison, a markdown table (| a | b |); a conclusion or "
        "recommendation that says what it rests on",
    },
}
ANGLES = {
    "fr": {
        "make_slides": ("factuel et chronologique", "pour décideurs : ce qui change et ce qu'il faut retenir"),
        "draft_email": ("exigences d'abord", "coût total d'abord"),
        "make_document": ("fidèle et complet", "décisions et risques mis en avant"),
        "make_sheet": ("fidèle", "fidèle"),
        "make_document_study": ("comparaison structurée, critère par critère", "pour décideurs : synthèse, "
                                "recommandation et limites"),  # fmt: skip
    },
    "en": {
        "make_slides": ("factual and chronological", "for decision makers: what changes and what to remember"),
        "draft_email": ("requirements first", "total cost first"),
        "make_document": ("faithful and complete", "decisions and risks first"),
        "make_sheet": ("faithful", "faithful"),
        "make_document_study": ("structured comparison, criterion by criterion", "for decision makers: summary, "
                                "recommendation and limits"),  # fmt: skip
    },
}

PROMPTS = {
    "fr": {
        "extract": "Voici un ou plusieurs extraits de pages (à partir de [{n}]). Relève au plus 8 chiffres utiles pour : "
        "{topic}. Pour chacun : année (celle écrite dans la même phrase que le chiffre), valeur exacte, phrase "
        "courte, et la citation exacte. Une hausse ou une baisse n'est pas un total : dis « hausse de ». N'invente "
        "rien ; si aucun chiffre utile, appelle record_facts avec une liste vide. Appelle record_facts.",
        "actions": "Notes numérotées ci-dessus. Liste chaque action décidée : ligne, responsable (nom de la liste des "
        "présents), action, échéance telle qu'écrite (vide si aucune). Une décision n'est pas une action. "
        "Appelle record_actions.",
        "actions_repair": "Ces lignes des notes contiennent peut-être des actions oubliées : {lines}. Pour ces lignes "
        "seulement, liste chaque action : ligne, responsable, action, échéance telle qu'écrite. Appelle record_actions.",
        "table": "Recopie chaque offre en tableau, valeurs telles qu'écrites, une ligne par offre. Appelle record_table.",
        "analyst": "Décris chaque offre pour le calcul : postes mensuels (montant, quantité), frais uniques, durée en "
        "mois, délai d'intervention en heures, options. Ne calcule rien. Exemple d'une autre activité : « Boulangerie : "
        "location four 300 € par mois, 2 vitrines à 45 € par mois, livraison 120 € une fois, 24 mois, dépannage sous "
        "6 h » donne monthly_items [{{label: four, amount: 300, qty: 1}}, {{label: vitrine, amount: 45, qty: 2}}], "
        "one_off [{{label: livraison, amount: 120}}], months 24, sla_hours 6. Appelle cost_model.",
        "planner": "Liste 4 à 8 points indispensables à la demande, et 0 à 3 recherches web si des chiffres récents "
        'manquent. Réponds en JSON {"points":[...],"recherches":[...]} uniquement.',
        "draft": "{shape}. Utilise uniquement les faits, calculs vérifiés et notes ci-dessus ; chaque chiffre suivi de "
        "[n] quand il vient d'une source. Angle : {angle}. Appelle maintenant {tool}.",
        "fix": "Voici ta version :\n{draft}\n\nCorrige uniquement : {findings}. Garde tout le reste. Appelle {tool}.",
        "search_plan": "Sujet : {topic}. Découpe cette demande en 3 sous-questions précises qu'un chargé d'études "
        "chercherait (par exemple les acteurs et leurs offres, les chiffres du marché, les tendances ou les risques), "
        "chacune avec une requête web courte de 3 à 8 mots, sans guillemets ni opérateur. Une requête au moins vise "
        "une source primaire ou officielle (statistique publique, rapport, site de l'éditeur). Année en cours : "
        "{year}. Appelle plan_search.",
    },
    "en": {
        "extract": "Here are one or more page extracts (from [{n}]). Record at most 8 useful figures for: {topic}. For "
        "each: year (the one written in the same sentence as the figure), exact value, a short sentence, and the exact "
        "quote. A rise or a fall is not a total: say « a rise of ». Invent nothing; if no useful figure, call "
        "record_facts with an empty list. Call record_facts.",
        "actions": "Numbered notes above. List every action decided: line, owner (a name from the attendee list), "
        "action, due date as written (empty if none). A decision is not an action. Call record_actions.",
        "actions_repair": "These note lines may hold missed actions: {lines}. For these lines only, list each action: "
        "line, owner, action, due date as written. Call record_actions.",
        "table": "Copy each offer into a table, values as written, one row per offer. Call record_table.",
        "analyst": "Describe each offer for the computation: monthly items (amount, quantity), one-off fees, term in "
        "months, response time in hours, options. Compute nothing. Example from another trade: « Bakery: oven rental "
        "€300 a month, 2 display cases at €45 a month, delivery €120 once, 24 months, repair within 6 h » gives "
        "monthly_items [{{label: oven, amount: 300, qty: 1}}, {{label: display, amount: 45, qty: 2}}], one_off "
        "[{{label: delivery, amount: 120}}], months 24, sla_hours 6. Call cost_model.",
        "planner": "List 4 to 8 points the request needs, and 0 to 3 web searches if recent figures are missing. "
        'Answer in JSON {"points":[...],"recherches":[...]} only.',
        "draft": "{shape}. Use only the facts, verified computations and notes above; every figure that comes from a "
        "source is followed by [n]. Angle: {angle}. Call {tool} now.",
        "fix": "Here is your version:\n{draft}\n\nFix only: {findings}. Keep everything else. Call {tool}.",
        "search_plan": "Topic: {topic}. Split this request into 3 precise sub-questions a research analyst would look "
        "up (for instance the players and their offers, the market figures, the trends or the risks), each with a "
        "short web query of 3 to 8 words, no quotes or operators. At least one query targets a primary or official "
        "source (public statistics, a report, the vendor's site). Current year: {year}. Call plan_search.",
    },
}
