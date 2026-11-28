"""Data card routes: the whole table of an attached CSV / XLSX for the interactive table, and one-click analyses.

No model is called: the file the browser already holds is read again here with the same parser as the chat
(``birds.harness.analysis``), so the table, the totals and every chart agree with what the model was given.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field

MAX_TEXT = 8_000_000  # characters of a CSV sent for its table (the chat itself caps what the model reads)
MAX_B64 = 4_000_000  # base64 characters of an XLSX (about 3 MB)


class DataBody(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=MAX_TEXT)
    encoding: Literal["text", "base64"] = "text"
    lang: Literal["fr", "en"] = "fr"
    query: dict | None = None
    question: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=50_000, ge=1, le=50_000)


def _frame(body: DataBody, api_error):
    from birds.harness.analysis import TableError, read_table, read_text_table
    from birds.harness.analysis.profile import frame_of
    from birds.harness.analysis.table import is_tabular
    from birds.harness.guard import ToolError

    from .backends import sanitize_filename

    name = sanitize_filename(body.name)
    try:
        if body.encoding == "base64":
            if len(body.content) > MAX_B64 or not name.lower().endswith((".xlsx", ".xlsm")):
                raise api_error(415, "data_type", "only an .xlsx file is sent as binary for its table")
            try:
                raw = base64.b64decode(body.content, validate=True)
            except (binascii.Error, ValueError):
                raise api_error(422, "attachment_invalid", "the file is not valid base64") from None
            tmp = Path(tempfile.mkdtemp(prefix="bird-data-"))
            try:
                (tmp / name).write_bytes(raw)
                table = read_table(tmp / name, name)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            if not (is_tabular(name) or name.lower().endswith((".txt", ".md"))):
                raise api_error(415, "data_type", "this file is not a table")
            table = read_text_table(body.content, name)
    except (TableError, ToolError) as e:
        raise api_error(422, "data_unreadable", str(e)) from None
    return name, frame_of(table)


def register(app, guard_request, check_access, api_error) -> None:
    """Adds POST /api/data/table and POST /api/data/query to ``app`` (birds.web.server.create_app)."""

    @app.post("/api/data/table")
    def data_table(body: DataBody, request: Request) -> dict:
        guard_request(request)
        check_access(request)
        from birds.harness.analysis.card import table_rows, totals

        name, f = _frame(body, api_error)
        return {
            "ok": True,
            "name": name,
            "n": f.n,
            "columns": [{"name": c.name, "type": c.type, "unit": c.unit} for c in f.columns],
            "rows": table_rows(f, body.limit),
            "totals": totals(f),
            "truncated": bool(f.meta.get("truncated")) or f.n > body.limit,
        }

    @app.post("/api/data/query")
    def data_query(body: DataBody, request: Request) -> dict:
        guard_request(request)
        check_access(request)
        from birds.harness.analysis import QueryError, chart_from_result, plan_question, run_query
        from birds.harness.analysis.card import explain
        from birds.harness.analysis.suggest import slim_result

        name, f = _frame(body, api_error)
        q = body.query
        if q is None and body.question:
            plan = plan_question(f, body.question)
            q = plan["query"] if plan else None
        if q is None:
            return {"ok": False, "error": "no_query"}
        try:
            res = run_query(f, q, body.lang)
        except QueryError as e:
            return {"ok": False, "error": str(e)}
        chart = chart_from_result(res, body.lang, "analysis", name)
        chart["id"] = (
            "q-" + hashlib.sha256(json.dumps(res["query"], sort_keys=True, default=str).encode()).hexdigest()[:10]
        )
        return {"ok": True, "result": slim_result(res, 200), "chart": chart, "text": explain(res, body.lang)}
