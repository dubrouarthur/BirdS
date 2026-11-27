"""What the tools returned, kept short: key figures, one note per tool result, and the checks that use them.

* ``key_figures``: labelled totals in a text (« Total TTC : 1 284,37 € », « TVA 20 % : 214,06 € »), the numbers a
  4B model most often drops or rounds when it re-reads an invoice. Labels and numbers only, never free text.
* ``note_of``: one line per tool result (« read_file « facture.jpg » : 412 chars ; Total HT 250,00 ; … »), the
  run's result memory. It is re-injected where the full result is no longer in view: a repeated call, the last
  answer after a failed loop, and the next turn's memo (birds.harness.history).
* ``missing_figures``: key figures that do not reach the answer or a file made in the run.
* ``wrong_language``: an answer clearly written in the other language than the user's.

Nothing here calls the model or reads model prose as data: figures come from tool results and the user's messages.
"""

from __future__ import annotations

import re

_NUM = r"[-+]?\d{1,3}(?:[  .]\d{3})+(?:,\d+)?|[-+]?\d+(?:[.,]\d+)?"
# a line that starts with a label naming a total: « Total TTC : 300,00 € », « | Net à payer | 1 200 € | »
_KEY = re.compile(
    r"^[ \t|*\-•]*(?:sous[- ]total|total|totaux|montant|net\s+[àa]\s+payer|reste\s+[àa]\s+payer|solde|tva|vat|"
    r"amount\s+due|grand\s+total|subtotal|balance\s+due)\b",
    re.I,
)
_AMOUNT = re.compile(r"(?<![\w.,])(?P<num>" + _NUM + r")(?![\d])\s*(?P<unit>€|eur\b|euros?\b|\$|usd\b|%)?", re.I)
_SPECIFIC = {  # a figure the user named: only these are checked when the request names one
    "ttc": re.compile(r"\bttc\b|toutes taxes", re.I),
    "ht": re.compile(r"\bht\b|hors[- ]taxes?", re.I),
    "tva": re.compile(r"\btva\b|\bvat\b|\btaxes?\b", re.I),
    "net": re.compile(r"net\s+[àa]\s+payer|reste\s+[àa]\s+payer|amount due|balance due", re.I),
}
# the request asks about totals, amounts or VAT (never « combien » alone: an earlier invoice is not every question)
FIGURE_ASK = re.compile(
    r"\b(?:totaux|totals?|sous-totaux|subtotals?|montants?|amounts?|tva|vat|ttc|ht|net [àa] payer|amount due)\b",
    re.I,
)


def values(text: str) -> set[float]:
    """Every reading of every number in ``text`` (« 1 234,50 », « 1234.5 », « 1.234 » in both conventions)."""
    out: set[float] = set()
    for m in re.finditer(r"(?<![\w.,])(?:" + _NUM + r")(?![\d])", text or ""):
        s = re.sub(r"[\s  ]", "", m.group(0))
        for cand in (s.replace(".", "").replace(",", "."), s.replace(",", ""), s.replace(",", ".")):
            try:
                out.add(round(float(cand), 2))
            except ValueError:
                pass
    return out


def key_figures(text: str, limit: int = 8) -> list[tuple[str, str]]:
    """[(label, amount)] of labelled totals in ``text``: the last amount of each line that starts with a total's
    label (« TVA 20 % : 50,00 € » is 50,00 €, a rate alone is not an amount). First occurrence of each label."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        if not _KEY.match(line):
            continue
        amounts = [m for m in _AMOUNT.finditer(line) if m.group("unit") != "%"]
        if not amounts:
            continue
        last = amounts[-1]
        label = re.split(r"[:=|]", line[: last.start()].strip(" \t|*-•"), maxsplit=1)[0]
        label = " ".join(label.split()).strip(" :.-")
        if not label or len(label) > 32 or label.lower() in seen:
            continue
        seen.add(label.lower())
        unit = last.group("unit") or ""
        out.append((label, last.group("num") + (" " + unit if unit else "")))
        if len(out) >= limit:
            break
    return out


def wanted(figures: list[tuple[str, str]], request: str) -> list[tuple[str, str]]:
    """The figures the request is about: the ones it names (TTC, HT, TVA…), else all the totals."""
    named = [k for k, rx in _SPECIFIC.items() if rx.search(request or "")]
    if not named:
        return figures
    return [f for f in figures if any(_SPECIFIC[k].search(f[0]) for k in named)]


def missing_figures(figures: list[tuple[str, str]], text: str) -> list[tuple[str, str]]:
    have = values(text)
    out = []
    for label, num in figures:
        want = values(num)
        if want and not any(abs(w - h) < 0.006 for w in want for h in have):
            out.append((label, num))
    return out


def figures_line(figures: list[tuple[str, str]]) -> str:
    return " ; ".join(f"{label} : {num}" for label, num in figures)


# ---------------------------------------------------------------- result memory


def _key(args: dict) -> str:
    a = args or {}
    v = a.get("query") or a.get("url") or a.get("path") or a.get("title") or a.get("subject") or a.get("name") or ""
    v = " ".join(str(v).split())
    return v if len(v) <= 70 else v[:69] + "…"


def note_of(tool: str, args: dict, result: str, error: str | None) -> str:
    """One short line about one tool result, in the harness's words (never an instruction found in the result)."""
    key = _key(args)
    head = f"{tool} « {key} »" if key else tool
    if error:
        return f"{head}: error ({' '.join(str(error).split())[:90]})"
    body = result or ""
    if body.startswith("["):  # the fixed "external data" line
        body = body.split("\n", 1)[-1]
    if tool == "web_search":
        n = len(re.findall(r"(?m)^\d+\. ", body))
        return f"{head}: {n} result(s)" if n else f"{head}: no results"
    if tool in ("read_file", "read_page"):
        figs = key_figures(body, 5)
        extra = f"; figures: {figures_line(figs)}" if figs else ""
        return f"{head}: {len(body)} characters read{extra}"
    if tool == "draft_email":
        return f"{head}: draft shown to the user (not sent)"
    if tool.startswith("make_") and tool != "make_chart":
        return f"{head}: file created and shown to the user"
    if tool == "make_chart":
        return f"{head}: chart shown to the user"
    return f"{head}: done"


# ---------------------------------------------------------------- language

_FR_W = re.compile(
    r"\b(?:le|la|les|des|une?|est|sont|et|pour|que|qui|dans|sur|avec|vous|nous|je|du|au|aux|ce|cette|ou|mais|pas|"
    r"plus|par|il|elle|ils|leur|à|été|être|fait|très)\b",
    re.I,
)
_EN_W = re.compile(
    r"\b(?:the|is|are|and|for|that|with|you|we|this|of|to|in|it|be|was|have|has|not|but|or|by|they|their|from|"
    r"which|will|would|can|should)\b",
    re.I,
)


def wrong_language(answer: str, lang: str) -> bool:
    """The answer is clearly in the other language: 40 letters or more, and its common words are at least three times
    more often those of the other language. Code, quotes, links and tables are ignored."""
    text = re.sub(r"```.*?```|`[^`]*`|https?://\S+|«[^»]*»|\"[^\"]*\"|^\s*\|.*$|\[[^\]\n]*\]", " ", answer or "", flags=re.S | re.M)
    if len(re.findall(r"[^\W\d_]", text)) < 40:
        return False
    fr, en = len(_FR_W.findall(text)), len(_EN_W.findall(text))
    if lang == "fr":
        return en >= 5 and en >= 3 * max(fr, 1)
    if lang == "en":
        return fr >= 5 and fr >= 3 * max(en, 1)
    return False
