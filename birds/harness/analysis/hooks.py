"""The two hooks a backend calls around a model run when the user sent a table.

``prepare`` (before the run): reads the attached CSV / XLSX (or a table pasted in the message), profiles it, runs the
suggested analyses and, when the question asks for a computation, runs it. It returns the note added to the user's
message (the computed result, which the model only has to explain) and what ``finish`` needs.

``finish`` (after the run): adds the chart of the result and the data card, and checks every number of the answer
against the result; an answer with a number found nowhere is replaced by the harness's own exact sentence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from birds.harness.analysis.ask import plan_question
from birds.harness.analysis.card import build_card, explain, profile_text, result_text
from birds.harness.analysis.charts import chart_from_result
from birds.harness.analysis.profile import Frame, frame_of, profile_table
from birds.harness.analysis.query import QueryError, result_numbers, run_query
from birds.harness.analysis.suggest import slim_result, suggestions
from birds.harness.analysis.table import TableError, is_tabular, looks_like_table, read_table, read_text_table
from birds.harness.analysis.verify import check_numbers

log = logging.getLogger(__name__)

NOTE = {
    "fr": "\n\n[Bird a analysé « {name} » ({rows} lignes × {cols} colonnes) et calculé, à partir du fichier :\n"
    "{title}\n{table}\nÉcris 2 à 4 phrases qui commentent ce résultat, en reprenant ces chiffres uniquement "
    "(arrondis si tu veux) ; n'en calcule et n'en invente aucun autre, ne refais pas le tableau : il est affiché, "
    "avec son graphique.]",
    "en": "\n\n[Bird analysed '{name}' ({rows} rows × {cols} columns) and computed, from the file:\n{title}\n{table}\n"
    "Write 2 to 4 sentences commenting on this result, quoting these figures only (rounded if you like); do not "
    "compute or invent any other, do not redo the table: it is shown, with its chart.]",
}
PROFILE_NOTE = {
    "fr": "\n\n[Bird a lu « {name} » et affiche sa fiche (colonnes, types, valeurs) avec des analyses en un clic. "
    "Profil calculé :\n{profile}\nSi tu cites des chiffres, ce sont uniquement ceux-ci.]",
    "en": "\n\n[Bird read '{name}' and shows its data card (columns, types, values) with one-click analyses. "
    "Computed profile:\n{profile}\nIf you quote figures, quote these only.]",
}
CHECKED = {
    "fr": "\n\n_Chiffres recalculés par Bird à partir de « {name} »._",
    "en": "\n\n_Figures recomputed by Bird from '{name}'._",
}


@dataclass
class Prep:
    name: str
    frame: Frame
    profile: dict
    card: dict
    note: str
    result: dict | None = None
    chart: dict | None = None
    allowed: list[float] = field(default_factory=list)
    lang: str = "fr"


def _load(workspace: Path, names: list[str], words: str) -> tuple[str, object, str] | None:
    """(display name, table, origin) of the first table among the attachments, or in the user's own words."""
    for n in names:
        p = workspace / n
        if not p.is_file():
            continue
        try:
            if is_tabular(p.name):
                return p.name, read_table(p), "attachment"
            if p.suffix.lower() in (".txt", ".md") and p.stat().st_size < 3_000_000:
                text = p.read_text(encoding="utf-8", errors="replace")
                if looks_like_table(text):
                    return p.name, read_text_table(text, p.name), "attachment"
        except TableError:
            continue
        except Exception:  # noqa: BLE001 - a damaged file: the model reads it as before
            log.debug("table read failed", exc_info=True)
            continue
    if looks_like_table(words):
        try:
            return "tableau collé", read_text_table(words, "tableau.md"), "pasted"
        except TableError:
            return None
    return None


def prepare(workspace: Path, names: list[str], words: str, lang: str = "fr") -> Prep | None:
    lang = "en" if lang == "en" else "fr"
    try:
        loaded = _load(workspace, names, words)
        if loaded is None:
            return None
        name, table, origin = loaded
        if origin == "pasted" and lang == "en":
            name = "pasted table"
        f = frame_of(table)
        prof = profile_table(f)
        sugg = suggestions(f, lang, source_label=name)
        question = words if origin == "attachment" else _question_part(words)
        plan = plan_question(f, question) if question else None
        result = chart = None
        if plan:
            try:
                result = run_query(f, plan["query"], lang)
                chart = chart_from_result(result, lang, "analysis", name)
                chart["id"] = "a1"
            except QueryError:
                result = chart = None
        answer = {"label": result["title"], "query": result["query"], "result": slim_result(result),
                  "chart": chart} if result else None  # fmt: skip
        card = build_card(f, prof, sugg, name=name, origin=origin, lang=lang, answer=answer)
        if result:
            note = NOTE[lang].format(name=name, rows=f.n, cols=len(f.columns), title=result["title"],
                                     table=result_text(result, lang))  # fmt: skip
            allowed = result_numbers(result)
        else:
            note = PROFILE_NOTE[lang].format(name=name, profile=profile_text(prof, lang))
            allowed = _profile_numbers(prof)
        return Prep(name, f, prof, card, note, result, chart, allowed, lang)
    except Exception:  # noqa: BLE001 - the analysis must never lose the turn
        log.warning("data analysis failed", exc_info=True)
        return None


def _question_part(words: str) -> str:
    """The user's words around a pasted table (the lines that are not table rows)."""
    lines = [ln for ln in words.splitlines() if ln.strip()]
    return " ".join(ln for ln in lines if not ln.strip().startswith("|") and ln.count("\t") < 1 and ln.count(";") < 2)


def _profile_numbers(prof: dict) -> list[float]:
    out = [float(prof["rows"]), float(prof["cols"]), float(prof.get("missing") or 0)]
    for c in prof["columns"]:
        out += [float(c.get("count") or 0), float(c.get("missing") or 0), float(c.get("distinct") or 0)]
        for v in (c.get("stats") or {}).values():
            if isinstance(v, int | float):
                out.append(float(v))
        for _, k in c.get("top") or []:
            out.append(float(k))
    return out


def finish(run, prep: Prep | None, request: str = "") -> None:
    """Chart, card and the number check, on the finished ``run`` (an agent Run)."""
    if prep is None:
        return
    lang = prep.lang
    if prep.chart and not any(c.get("v") == 2 and c.get("id") == prep.chart.get("id") for c in run.charts):
        run.charts.insert(0, prep.chart)
    answer = str(getattr(run, "answer", "") or "")
    bad = check_numbers(answer, prep.allowed + [float(prep.frame.n)], request) if answer else []
    if prep.result is not None and (bad or not answer.strip()):
        log.info("answer numbers not in the computed result: %s", bad[:5])
        run.answer = explain(prep.result, lang) + CHECKED[lang].format(name=prep.name)
        run.report = {**(getattr(run, "report", None) or {}), "data_check": {"replaced": True, "unverified": bad[:10]}}
    elif bad:
        run.report = {**(getattr(run, "report", None) or {}), "data_check": {"unverified": bad[:10]}}
    else:
        run.report = {**(getattr(run, "report", None) or {}), "data_check": {"ok": True}}


__all__ = ["Prep", "finish", "prepare"]
