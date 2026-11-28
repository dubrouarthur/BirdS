"""Bird's product tools, in OpenAI function format (used by the agent benchmark and the agent data)."""

from __future__ import annotations


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_STR = {"type": "string"}

BIRD_TOOLS: list[dict] = [
    _fn(
        "web_search",
        "Search the web for recent or external information (news, prices, rates, dates, facts to verify). "
        "Returns a list of results with title, URL and snippet.",
        {
            "query": {
                "type": "string",
                "description": "Search query, in the language most likely to find good results.",
            },
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (default 5).",
                "minimum": 1,
                "maximum": 20,
            },
        },
        ["query"],
    ),
    _fn(
        "read_page",
        "Fetch a web page from its URL and return its readable text. Use it when the user gives a link "
        "or after web_search to read a result in full.",
        {"url": {"type": "string", "description": "Full URL of the page, starting with http:// or https://."}},
        ["url"],
    ),
    _fn(
        "read_file",
        "Read a file from the user's workspace (PDF, DOCX, XLSX, CSV, TXT, MD) and return its content as text.",
        {"path": {"type": "string", "description": "Path of the file as given by the user."}},
        ["path"],
    ),
    _fn(
        "draft_email",
        "Prepare an email draft for the user to review. Nothing is sent: Bird cannot send it.",
        {
            "to": {"type": "array", "items": _STR, "description": "Recipient email addresses."},
            "subject": {"type": "string", "description": "Subject line."},
            "body": {"type": "string", "description": "Body of the email, plain text."},
            "tone": {
                "type": "string",
                "enum": ["neutral", "formal", "friendly", "firm"],
                "description": "Tone of the message (default neutral).",
            },
        },
        ["to", "subject", "body"],
    ),
    _fn(
        "make_slides",
        "Create a slide deck (presentation) from a title and a list of slides.",
        {
            "title": {"type": "string", "description": "Title of the presentation."},
            "slides": {
                "type": "array",
                "description": "Slides in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Slide title."},
                        "bullets": {"type": "array", "items": _STR, "description": "Bullet points of the slide."},
                    },
                    "required": ["title", "bullets"],
                },
            },
        },
        ["title", "slides"],
    ),
    _fn(
        "make_document",
        "Create a text document (note, report, minutes, procedure) from a title and a list of sections.",
        {
            "title": {"type": "string", "description": "Title of the document."},
            "sections": {
                "type": "array",
                "description": "Sections in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string", "description": "Section heading."},
                        "content": {"type": "string", "description": "Section text."},
                    },
                    "required": ["heading", "content"],
                },
            },
        },
        ["title", "sections"],
    ),
    _fn(
        "make_sheet",
        "Create a spreadsheet from a title, column names and rows of values.",
        {
            "title": {"type": "string", "description": "Title of the spreadsheet."},
            "columns": {"type": "array", "items": _STR, "description": "Column names."},
            "rows": {
                "type": "array",
                "description": "Rows; each row is a list of cell values in column order.",
                "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}},
            },
        },
        ["title", "columns", "rows"],
    ),
    _fn(
        "run_python",
        "Run Python code in a sandbox and return what it prints. Use it for calculations that are not trivial "
        "to do mentally (statistics, simulations, data processing).",
        {"code": {"type": "string", "description": "Python source code; print the results."}},
        ["code"],
    ),
]

BIRD_TOOL_NAMES = [t["function"]["name"] for t in BIRD_TOOLS]

# Product tools that are NOT part of the trained set: offered only when the harness routes them in
# (birds.harness.intents), appended after the trained tools, so the prompt of an ordinary turn stays byte for byte
# what the model was trained on. Kept tiny and flat (at most 3 string/number arguments).
EXTRA_TOOLS: list[dict] = [
    _fn(
        "make_chart",
        "Show a chart in the chat. Use it when the user asks for a chart, graph or plot of figures. "
        "Give column names and rows like a spreadsheet: the first column holds the labels, each other column "
        "holds the numbers of one series.",
        {
            "title": {"type": "string", "description": "Title of the chart."},
            "type": {
                "type": "string",
                "enum": ["bar", "line", "pie"],
                "description": "bar (compare), line (change over time) or pie (share of a whole).",
            },
            "columns": {
                "type": "array",
                "items": _STR,
                "description": "Column names: label column first, then one per series.",
            },
            "rows": {
                "type": "array",
                "description": "Rows; each row is a label then its numbers, in column order.",
                "items": {"type": "array", "items": {"type": ["string", "number", "null"]}},
            },
            "unit": {"type": "string", "description": "Unit of the numbers, e.g. €, %, k€, h (optional)."},
        },
        ["title", "columns", "rows"],
    ),
    _fn(
        "find_places",
        "Find a place, an address, or places of a kind near somewhere, on OpenStreetMap. Use it when the user asks "
        "where something is, for an address, for places near a location, or to put a list of places or addresses "
        "on one map.",
        {
            "query": {
                "type": "string",
                "description": "What to find: a place name, an address, or a kind of place (e.g. restaurant). "
                "Several places for one map: separated by ' ; ' (up to 25).",
            },
            "near": {"type": "string", "description": "Optional: where to search around (e.g. gare de Lyon, Paris)."},
            "plan": {
                "type": "string",
                "enum": ["order", "distances"],
                "description": "Optional, for a list: 'order' when the user asks in which order to visit the places, "
                "'distances' when they ask the distances between them.",
            },
        },
        ["query"],
    ),
    _fn(
        "find_company",
        "Look up a French company in the official register (name, SIREN, address, activity). Use it when the user "
        "asks about a company, a client or a supplier by name or SIREN.",
        {"name": {"type": "string", "description": "Company name, SIREN (9 digits) or SIRET (14 digits)."}},
        ["name"],
    ),
    _fn(
        "convert_currency",
        "Convert an amount between currencies with the European Central Bank reference rate of the day.",
        {
            "amount": {"type": "number", "description": "Amount to convert (default 1)."},
            "from": {"type": "string", "description": "Currency code to convert from, e.g. USD."},
            "to": {"type": "string", "description": "Currency code to convert to, e.g. EUR."},
        },
        ["from", "to"],
    ),
    _fn(
        "get_weather",
        "Get the weather forecast for a town (MET Norway): temperature, sky, rain and wind, hour by hour and for "
        "the next days.",
        {
            "place": {"type": "string", "description": "Town or place, e.g. Lyon."},
            "day": {
                "type": "string",
                "description": "Optional: the day, e.g. demain, jeudi, 2026-12-03 (default today).",
            },
        },
        ["place"],
    ),
]
EXTRA_TOOL_NAMES = [t["function"]["name"] for t in EXTRA_TOOLS]
PRODUCT_TOOLS = BIRD_TOOLS + EXTRA_TOOLS
PRODUCT_TOOL_NAMES = [t["function"]["name"] for t in PRODUCT_TOOLS]
