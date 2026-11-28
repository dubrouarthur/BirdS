"""Bird's canvas: documents, decks, code and small sheets built beside the chat (see docs/CANVAS.md).

The small model never draws a layout. It writes CONTENT in a tiny, forgiving text format (``dsl``); the harness
parses it leniently into one document model, patches it on follow-up turns (``patch``), resolves its pictures
(``images``) and renders it: live in the app's canvas panel (static/canvas.js, pre-designed themes) and to
.pptx / .docx / .xlsx through the office engine (``export``).
"""

from .dsl import KINDS, THEMES, new_id, outline, parse, parse_code, to_dsl, validate

__all__ = ["KINDS", "THEMES", "new_id", "outline", "parse", "parse_code", "to_dsl", "validate"]
