"""The two hooks a backend calls around a model run when the user sent a table.

``prepare`` (before the run): reads the attached CSV / XLSX (or a table pasted in the message), profiles it, runs the
suggested analyses and, when the question asks for a computation, runs it. It returns the note added to the user's
message (the computed result, which the model only has to explain) and what ``finish`` needs.

``finish`` (after the run): adds the chart of the result and the data card, and checks every number of the answer
against the result; an answer with a number found nowhere is replaced by the harness's own exact sentence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from birds.harness.analysis import planner
from birds.harness.analysis.ask import refers_to_table
from birds.harness.analysis.card import build_card, explain, profile_text, result_text
from birds.harness.analysis.charts import chart_from_result
from birds.harness.analysis.profile import Frame, frame_of, profile_table
from birds.harness.analysis.query import QueryError, result_numbers, run_query
from birds.harness.analysis.suggest import slim_result, suggestions
from birds.harness.analysis.table import TableError, is_tabular, looks_like_table, read_table, read_text_table
from birds.harness.analysis.verify import check_numbers
from birds.harness.guard import ToolError

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


UNCOMPUTED = {
    "fr": "J'ai lu « {name} » ({rows} lignes × {cols} colonnes) : la fiche ci-dessous montre chaque colonne, le "
    "tableau complet et des analyses en un clic. Dites-moi le calcul voulu (par exemple « CA par région » ou « top 5 "
    "des clients ») et Bird le fera sur le fichier.",
    "en": "I read '{name}' ({rows} rows × {cols} columns): the card below shows every column, the full table and "
    "one-click analyses. Tell me the computation you want (for example \"revenue by region\" or \"top 5 "
    "customers\") and Bird will run it on the file.",
}


def _without_unverified(answer: str, allowed: list[float], request: str) -> tuple[str, int]:
    """(the answer without its sentences or list lines that carry an unverified number, how many were dropped)."""
    parts = re.split(r"(?<=[.!?])[ \t]+|\n", answer)
    kept = [p for p in parts if not check_numbers(p, allowed, request)]
    return " ".join(p.strip() for p in kept if p.strip()), len(parts) - len(kept)


def _quotes_file(text: str, allowed: list[float]) -> bool:
    """Whether ``text`` quotes at least one figure of the file (a small count or a year alone does not count)."""
    from birds.harness.analysis.verify import numbers_in

    figures = [v for v, raw in numbers_in(text) if not (float(v).is_integer() and (0 <= v <= 12 or 1900 <= v <= 2100))]
    return any(not check_numbers(f"{v}", allowed) for v in figures)


MARKERS = ("\n\n[Bird a analysé « ", "\n\n[Bird analysed '", "\n\n[Bird a lu « ", "\n\n[Bird read '")


def strip_note(text: str) -> str:
    """``text`` without the data note added to it (always last): a regenerated turn never gets it twice, and the
    user's own words never include it."""
    cut = min((i for i in (text.find(m) for m in MARKERS) if i >= 0), default=-1)
    return text if cut < 0 else text[:cut]


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
    plan: dict | None = None  # the analysis spec computed this turn (planner.py), written in the memo
    planned: dict = field(default_factory=dict)  # how it was chosen: source (model, hybrid, rules, fallback), meta
    about: bool = True  # the turn is about the table (a computed result, or a question naming it): numbers checked


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


_NOTED = re.compile(r"\[(?:Fichier joint|Attached file) : ([^\]\n]{1,200})\]")


def brought(attachments: list[dict], history: list[dict] | None) -> list[str] | None:
    """The names of the attachments THIS message brings (the client re-sends every attachment of the conversation
    each turn). The app marks them (``fresh``); for another client, a file already noted in an earlier user message
    (« [Fichier joint : ventes.csv] ») was brought before. None: no attachment."""
    if not attachments:
        return None
    if any("fresh" in a for a in attachments):
        return [Path(str(a["name"])).name for a in attachments if a.get("fresh")]
    seen = {Path(n.strip()).name for m in history or [] if m.get("role") == "user"
            for n in _NOTED.findall(str(m.get("content") or ""))}  # fmt: skip
    return [Path(str(a["name"])).name for a in attachments if Path(str(a["name"])).name not in seen]


def prepare(workspace: Path, names: list[str], words: str, lang: str = "fr", *, llm=None, tok=None, history=None,
            mode: str = "rules", structured: str = "", budget: float = planner.BUDGET_S,
            cache_salt: str | None = None, fresh: list[str] | None = None) -> Prep | None:  # fmt: skip
    """``llm`` / ``tok`` given and ``mode`` model or hybrid: Bird chooses the analysis (``planner.decide``, one short
    structured call); otherwise, or when that call fails, the fixed rules do. ``history``: the conversation before
    this message (a follow-up edits the previous turn's analysis). ``fresh``: the attachments this message brings
    (``brought``), None for all of them; a table brought by an earlier message is only used when the planner asks
    for an analysis of it (« Quelle est la population de Canberra ? » next is answered by the model alone)."""
    lang = "en" if lang == "en" else "fr"
    try:
        loaded = _load(workspace, names, words)
        if loaded is None:
            return None
        name, table, origin = loaded
        new = origin == "pasted" or fresh is None or name in {Path(n).name for n in fresh}
        if origin == "pasted" and lang == "en":
            name = "pasted table"
        f = frame_of(table)
        prof = profile_table(f)
        sugg = suggestions(f, lang, source_label=name)
        question = words if origin == "attachment" else _question_part(words)
        planned = planner.decide(llm if mode != "rules" else None, tok, f, question or "", history=history,
                                 lang=lang, mode=mode, structured=structured, budget=budget,
                                 cache_salt=cache_salt)  # fmt: skip
        plan = planned.plan
        result = chart = None
        if plan:
            try:
                result = run_query(f, plan["query"], lang)
                chart = chart_from_result(result, lang, "analysis", name, type_=_chart_type(plan, result))
                chart["id"] = "a1"
            except (QueryError, ToolError):
                result = chart = plan = None
        if result is None and not new:
            return None  # a table of an earlier message, and no analysis asked of it: not this turn's topic
        previous = planner.previous_spec(history)
        version = int(previous.get("version") or 1) + 1 if plan and _edits(plan, previous) else 1
        answer = {"label": result["title"], "query": result["query"], "result": slim_result(result), "chart": chart,
                  "next": next_steps(f, result, lang), "version": version} if result else None  # fmt: skip
        card = build_card(f, prof, sugg, name=name, origin=origin, lang=lang, answer=answer)
        if answer and version > 1:
            card["compact"] = True  # a follow-up that edits the chart: the chart first, the profile folded
        if result:
            note = NOTE[lang].format(name=name, rows=f.n, cols=len(f.columns), title=result["title"],
                                     table=result_text(result, lang))  # fmt: skip
            allowed = result_numbers(result)
        else:
            note = PROFILE_NOTE[lang].format(name=name, profile=profile_text(prof, lang))
            allowed = _profile_numbers(prof)
        if plan is not None:
            plan = {**plan, "version": version}
        about = result is not None or refers_to_table(f, question or "", compute=False)
        return Prep(name, f, prof, card, note, result, chart, allowed, lang, plan,
                    {"source": planned.source, **planned.meta}, about)  # fmt: skip
    except Exception:  # noqa: BLE001 - the analysis must never lose the turn
        log.warning("data analysis failed", exc_info=True)
        return None


def _edits(plan: dict, previous: dict | None) -> bool:
    """Whether ``plan`` is a new version of the previous turn's analysis (its version number goes up): an edit by
    rule (« en courbe », « par trimestre »), or the model's spec on the same measure with the same operation. Any
    other analysis that follows one starts again at version 1."""
    if not previous:
        return False
    if plan.get("why") == "revised":
        return True
    if plan.get("why") != "model":
        return False
    a, b = plan.get("query") or {}, previous.get("analysis") or {}
    subject = lambda q: q.get("measure") or frozenset((q.get("x"), q.get("y")))  # noqa: E731
    return a.get("op") == b.get("op") and subject(a) == subject(b)


def _chart_type(plan: dict, result: dict) -> str | None:
    """The chart the planner chose, when it suits the result (a donut of a time series is not drawn)."""
    want = plan.get("chart")
    kind = result.get("kind")
    if not want:
        return None
    if kind == "scatter" or kind == "scalar":
        return None
    if kind == "describe":
        return want if want in ("box", "histogram") else None
    if want == "donut" and (kind == "time" or len(result.get("columns") or []) > 2 and kind != "share"):
        return None
    if want == "scatter":
        return None
    return want


_NEXT = {
    "fr": {"donut": "En camembert", "line": "En courbe", "bar": "En barres", "top5": "Seulement le top 5",
           "quarter": "Par trimestre", "month": "Par mois", "year": "Par année", "window": "Avec une moyenne mobile sur 3 mois",
           "change": "Évolution en % d'une période à l'autre", "by": "Par {name}", "heatmap": "En carte de chaleur",
           "m_month": "{m} par mois", "m_by": "{m} par {name}", "dist": "Distribution de {m}"},
    "en": {"donut": "As a donut", "line": "As a line", "bar": "As bars", "top5": "Only the top 5",
           "quarter": "By quarter", "month": "By month", "year": "By year", "window": "With a 3-month moving average",
           "change": "Percent change from one period to the next", "by": "By {name}", "heatmap": "As a heat map",
           "m_month": "{m} by month", "m_by": "{m} by {name}", "dist": "Distribution of {m}"},
}  # fmt: skip


def next_steps(f: Frame, result: dict, lang: str = "fr") -> list[dict]:
    """2 or 3 concrete edits of the chart just shown (« Modifier le graphique »): each one is sent as the user's next
    message, and the planner edits the analysis (continuity rule: the updated chart is shown again)."""
    w = _NEXT["en" if lang == "en" else "fr"]
    q = result.get("query") or {}
    kind = result.get("kind")
    rows = result.get("rows") or []
    dates = [c for c in f.columns if c.type == "date"]
    cats = [c for c in f.columns if c.type in ("category", "bool") and c.name not in (q.get("by"), q.get("pivot"))
            and 2 <= len({v for v in c.values if v is not None}) <= 12]  # fmt: skip
    out: list[str] = []
    if kind == "time" and not q.get("pivot"):
        out.append(w["quarter"] if q.get("period") != "quarter" else w["month"])
        if not q.get("window"):
            out.append(w["window"])
        if not q.get("change"):
            out.append(w["change"])
    elif kind in ("ranking", "category", "share") and q.get("by"):
        if kind != "share" and len(rows) <= 8 and q.get("agg") in ("sum", "count"):
            out.append(w["donut"])
        elif kind == "share":
            out.append(w["bar"])
        if len(rows) > 5 and not q.get("top"):
            out.append(w["top5"])
        if dates:
            out.append(w["month"])
        if cats and len(out) < 3:
            out.append(w["by"].format(name=cats[0].name))
    elif kind == "compare":
        if cats and not q.get("by"):
            out.append(w["by"].format(name=cats[0].name))
        out.append(w["line"])
    elif q.get("pivot"):
        out.append(w["heatmap"])
        if dates and not q.get("period"):
            out.append(w["month"])
    elif kind == "describe" and cats:
        out.append(w["by"].format(name=cats[0].name))
    elif kind == "scalar":  # « Total CA (€) »: broken down by a category, over time
        out += [w["by"].format(name=c.name) for c in cats[:1]]
        if dates:
            out.append(w["month"])
        out += [w["by"].format(name=c.name) for c in cats[1:2]]
    elif kind == "scatter" and q.get("op") == "corr":  # each measure of the pair, on its own
        y = q.get("y") or ""
        if dates:
            out.append(w["m_month"].format(m=y))
        if cats:
            out.append(w["m_by"].format(m=y, name=cats[0].name))
        out.append(w["dist"].format(m=q.get("x") or ""))
    return [{"label": x, "ask": x} for x in out[:3]]


def memo_line(prep: Prep | None) -> str:
    """The analysis spec of this turn, for the memo (a follow-up edits it), or ''."""
    if prep is None or not prep.plan:
        return ""
    line = planner.memo_line(prep.name, prep.plan, prep.lang)
    spec = {"analysis": prep.plan["query"], "chart": prep.plan.get("chart") or "auto", "version": prep.plan["version"]}
    return line.rsplit(" — ", 1)[0] + " — " + planner._dump(spec) + "]" if line else ""


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
    # the chart of the result is drawn in the data card (with « Modifier le graphique »), not a second time below
    answer = str(getattr(run, "answer", "") or "")
    if prep.result is None and not prep.about:
        # the table was just attached but the turn is about something else (« écris un mail pour la réunion de
        # lundi à 14 h 30 ») : its numbers are not the file's, nothing to check
        run.report = {**(getattr(run, "report", None) or {}), "data_check": {"skipped": "not about the table"}}
        return
    allowed = prep.allowed + [float(prep.frame.n)]
    bad = check_numbers(answer, allowed, request) if answer else []
    if prep.result is not None and (bad or not answer.strip()):
        log.info("answer numbers not in the computed result: %s", bad[:5])
        run.answer = explain(prep.result, lang) + CHECKED[lang].format(name=prep.name)
        run.report = {**(getattr(run, "report", None) or {}), "data_check": {"replaced": True, "unverified": bad[:10]}}
    elif bad:
        # no computed result (the card only): the sentences carrying a number found nowhere are taken out; when
        # little is left, the harness says what it read and asks for the computation (never an invented figure)
        kept, dropped = _without_unverified(answer, allowed, request)
        if dropped and len(kept.split()) >= 12 and len(kept) >= 0.4 * len(answer):
            # « recomputed by Bird » only over figures that do come from the file
            run.answer = kept + (CHECKED[lang].format(name=prep.name) if _quotes_file(kept, allowed) else "")
        else:
            run.answer = UNCOMPUTED[lang].format(name=prep.name, rows=prep.frame.n, cols=len(prep.frame.columns))
        run.report = {**(getattr(run, "report", None) or {}),
                      "data_check": {"unverified": bad[:10], "stripped": dropped}}  # fmt: skip
    else:
        run.report = {**(getattr(run, "report", None) or {}), "data_check": {"ok": True}}


__all__ = ["MARKERS", "Prep", "brought", "finish", "memo_line", "next_steps", "prepare", "strip_note"]
