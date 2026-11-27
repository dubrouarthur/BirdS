"""Mode Agent, wave 2: the team's deck or document written into the Canvas document model, section by section.

An adapter, so the crew does not depend on the canvas package: when ``birds.canvas`` (branch w1-canvas) is there
and the flag allows it, ``Sink`` converts the checked deliverable with the canvas's public functions
(``birds.canvas.convert.from_tool``, ``birds.canvas.turn.finish_doc`` and ``new_aid``) and streams it to the
browser as the canvas panel expects (``{"type": "canvas", "phase": "stream"|"final", ...}``), one more section or
slide per snapshot. Without the canvas (or with ``BIRD_CREW_CANVAS=0``) nothing is emitted and the deliverable is the
file the trained tool builds, as before. Either way the file is built and listed under « Livrables ».

The content is the one the checker kept: the canvas never receives a section the code has not checked.
"""

from __future__ import annotations

import copy
import os

FLAG = "BIRD_CREW_CANVAS"  # "0": off; anything else (default): on when the canvas package is installed
TOOLS = {"make_slides": "slides", "make_document": "sections"}


def _modules():
    """(convert, turn) of the canvas package, or None. Patched in tests."""
    try:
        from birds.canvas import convert, turn  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - the canvas is optional (not merged, or broken): the file path is used
        return None
    return convert, turn


def available(tool: str | None) -> bool:
    return tool in TOOLS and os.environ.get(FLAG, "1") != "0" and _modules() is not None


class Sink:
    """One deliverable written into the canvas model. ``emit`` sends the crew's events (to the browser)."""

    def __init__(self, emit, tool: str, lang: str = "fr"):
        mods = _modules()
        if mods is None or tool not in TOOLS:
            raise RuntimeError("canvas unavailable")
        self.convert, self.turn = mods
        self.emit, self.tool, self.lang = emit, tool, lang
        self.aid = self.turn.new_aid()
        self.kind = None
        self.doc = None

    def _doc(self, args: dict, final: bool):
        doc = self.convert.from_tool(self.tool, args, self.lang)
        if doc is None:
            return None
        if final and doc.get("kind") in ("deck", "doc"):
            self.turn.finish_doc(doc, doc["kind"], doc.get("title") or "", self.lang)
        return doc

    def write(self, args: dict, label: str = "") -> dict | None:
        """Stream ``args`` one section (or slide) at a time, then the final document. Returns the canvas reference
        the answer carries ({"aid", "version", "doc"}), or None when the canvas could not read the deliverable."""
        key = TOOLS[self.tool]
        parts = list(args.get(key) or [])
        for k in range(1, len(parts)):
            partial = copy.deepcopy(args)
            partial[key] = parts[:k]
            doc = self._doc(partial, final=False)
            if doc is None:
                return None
            self.emit({"type": "canvas", "phase": "stream", "aid": self.aid, "base": None, "kind": doc.get("kind"),
                       "label": label, "open": True, "doc": doc, "agent": "assembleur",
                       "progress": {"done": k, "total": len(parts)}})  # fmt: skip
        doc = self._doc(args, final=True)
        if doc is None:
            return None
        self.doc = doc
        self.emit({"type": "canvas", "phase": "final", "aid": self.aid, "base": None, "kind": doc.get("kind"),
                   "label": label, "open": True, "doc": doc, "agent": "assembleur",
                   "progress": {"done": len(parts), "total": len(parts)}})  # fmt: skip
        return {"aid": self.aid, "version": 1, "doc": doc}
