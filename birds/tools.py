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
        "Prepare an email draft for the user to review. Nothing is sent.",
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
