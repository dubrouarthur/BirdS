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
VIRTUAL = {t["function"]["name"]: t for t in (RECORD_FACTS, RECORD_TABLE, RECORD_ACTIONS, COST_MODEL)}
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
    },
    "en": {
        "make_slides": "A deck of {n} slides: a short title per slide, 2 to 4 short bullets, every figure followed by "
        "its source [n]",
        "make_document": "A structured document in sections with a clear title, written sentences (not copied notes)",
        "draft_email": "An email of 150 to 350 words: clear subject, one line of context, the offers as a list or "
        "table, an explicit recommendation and its reason, the next step",
        "make_sheet": "A spreadsheet: one row per item, named columns, values as written",
    },
}
ANGLES = {
    "fr": {
        "make_slides": ("factuel et chronologique", "pour décideurs : ce qui change et ce qu'il faut retenir"),
        "draft_email": ("exigences d'abord", "coût total d'abord"),
        "make_document": ("fidèle et complet", "décisions et risques mis en avant"),
        "make_sheet": ("fidèle", "fidèle"),
    },
    "en": {
        "make_slides": ("factual and chronological", "for decision makers: what changes and what to remember"),
        "draft_email": ("requirements first", "total cost first"),
        "make_document": ("faithful and complete", "decisions and risks first"),
        "make_sheet": ("faithful", "faithful"),
    },
}

PROMPTS = {
    "fr": {
        "extract": "Voici un extrait de page [{n}]. Relève au plus 8 chiffres utiles pour : {topic}. Pour chacun : "
        "année, valeur exacte, phrase courte, et la citation exacte de l'extrait. N'invente rien ; si l'extrait n'a "
        "aucun chiffre utile, appelle record_facts avec une liste vide. Appelle record_facts.",
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
    },
    "en": {
        "extract": "Here is a page extract [{n}]. Record at most 8 useful figures for: {topic}. For each: year, exact "
        "value, a short sentence, and the exact quote from the extract. Invent nothing; if the extract has no useful "
        "figure, call record_facts with an empty list. Call record_facts.",
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
    },
}
