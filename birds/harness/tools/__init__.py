"""The product tools (8 trained + make_chart). Each takes arguments already validated against its schema
(birds.tools) and a Context."""

from birds.harness.tools.actions import draft_email, run_python
from birds.harness.tools.chart import make_chart
from birds.harness.tools.files import make_document, make_sheet, make_slides, read_file
from birds.harness.tools.web import (
    BraveBackend,
    SearxngBackend,
    StaticBackend,
    TavilyBackend,
    WikipediaBackend,
    make_search,
    read_page,
    web_search,
)

TOOLS = {
    "web_search": web_search,
    "read_page": read_page,
    "read_file": read_file,
    "draft_email": draft_email,
    "make_slides": make_slides,
    "make_document": make_document,
    "make_sheet": make_sheet,
    "run_python": run_python,
    "make_chart": make_chart,
}

__all__ = [
    "TOOLS",
    "BraveBackend",
    "SearxngBackend",
    "StaticBackend",
    "TavilyBackend",
    "WikipediaBackend",
    "make_search",
]
