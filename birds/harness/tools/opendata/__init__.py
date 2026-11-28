"""Open-data tools (keyless, licence-clean public APIs): holidays and working days, entity cards, official
statistics drawn as charts, public tenders, scholarly works, communes and addresses. See docs/WEB.md « Données
ouvertes » and birds/opendata_schemas.py for the schemas the model sees when the harness routes one in."""

from .calendar import work_calendar
from .commune import find_commune
from .entity import lookup_entity
from .papers import find_papers
from .stats import get_statistics
from .tenders import find_tenders

OPENDATA_TOOLS = {
    "work_calendar": work_calendar,
    "lookup_entity": lookup_entity,
    "get_statistics": get_statistics,
    "find_tenders": find_tenders,
    "find_papers": find_papers,
    "find_commune": find_commune,
}

__all__ = ["OPENDATA_TOOLS"]
