"""Pure checks for Mode Agent (birds.harness.crew): figures, provenance, JSON repair, notes and costs.

Nothing here calls a model. Every rule is code, so a 4B model's output is judged the same way every time: a figure
is kept only if it exists in what the user gave or in a page that was read (or is a simple difference or ratio of two
such figures); an owner only if the notes name them on the cited line; a cost only if the harness computed it.
"""

from __future__ import annotations

import ast
import json
import operator
import re
import unicodedata

# ------------------------------------------------------------------ numbers

# "1 450", "17 400,5", "14,8", "0.0045", "38 000" (normal, no-break and narrow no-break spaces as thousands marks)
_NUM = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?![\w])")
_CITE = re.compile(r"\[\d{1,2}\]")
_UNIT_AFTER = re.compile(r"^\s?(?:%|€|eur|k€|m€|points?|pts?|heures?|h\b)", re.I)


def to_float(raw: str) -> float:
    return float(re.sub(r"[   ]", "", raw).replace(",", "."))


def numbers(text: str) -> list[float]:
    return [to_float(m.group(0)) for m in _NUM.finditer(_CITE.sub(" ", text or ""))]


def _is_year(raw: str, v: float) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d\d", raw)) and 1900 <= v <= 2100


def figures(text: str) -> list[tuple[str, float]]:
    """Figures worth checking in a draft: years, citation marks and small bare counts (« 6 diapositives »,
    « 3 sites », « section 2 ») are not claims about the world and are skipped."""
    text = _CITE.sub(" ", text or "")
    out = []
    for m in _NUM.finditer(text):
        raw, v = m.group(0), to_float(m.group(0))
        if _is_year(raw, v):
            continue
        unit = bool(_UNIT_AFTER.match(text[m.end() : m.end() + 8]))
        if v < 13 and float(v).is_integer() and not unit:
            continue
        if re.match(r"\s?[/h]\s?\d", text[m.end() : m.end() + 3]) or text[m.start() - 1 : m.start()] == "/":
            continue  # a date (29/11) or a time (10h30)
        out.append((raw, v))
    return out


def allowed_figures(*texts: str) -> set[float]:
    out: set[float] = set()
    for t in texts:
        for raw in _NUM.findall(_CITE.sub(" ", t or "")):
            v = to_float(raw)
            if not _is_year(raw, v):
                out.add(round(v, 6))
    return out


def supported(v: float, allowed: set[float], tol: float = 0.05) -> bool:
    """In the allowed set, or a difference / ratio / percentage ratio of two allowed figures (within ``tol``).
    « 14,8 points » from 19 and 4,2 is accepted; « 4,6 » with no such pair is not."""
    if any(abs(v - a) <= max(0.005, abs(a) * 1e-4) for a in allowed):
        return True
    vals = [a for a in allowed if a > 0][:400]
    for a in vals:
        for b in vals:
            if a == b:
                continue
            if abs(abs(a - b) - v) <= tol or abs(a / b - v) <= tol or abs(a / b * 100 - v) <= tol * 10:
                return True
    return False


def unsupported(text: str, allowed: set[float]) -> list[str]:
    return [raw for raw, v in figures(text) if not supported(v, allowed)]


# ------------------------------------------------------------------ safe arithmetic

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def safe_eval(expr: str) -> float:
    """+ - * / and parentheses over numbers only. Anything else raises ValueError."""

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
            return -ev(node.operand) if isinstance(node.op, ast.USub) else ev(node.operand)
        raise ValueError("only numbers and + - * / ( ) are allowed")

    if len(expr) > 200:
        raise ValueError("expression too long")
    try:
        return ev(ast.parse(expr.replace(",", "."), mode="eval"))
    except (SyntaxError, ZeroDivisionError) as e:
        raise ValueError(str(e)) from None


# ------------------------------------------------------------------ JSON repair and salvage


def _scan(s: str) -> tuple[str, list[str], bool]:
    """Walk ``s`` keeping string state: drop closers that close nothing, return (text, open stack, in_string)."""
    out, stack, in_str, esc = [], [], False, False
    pairs = {"}": "{", "]": "["}
    for ch in s:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack or stack[-1] != pairs[ch]:
                continue  # an extra brace (seen live in a slides draft): dropped
            stack.pop()
        out.append(ch)
    return "".join(out), stack, in_str


def json_repair(raw: object):
    """A JSON value from a model's broken output, or None: unmatched closers dropped, open strings, arrays and
    objects closed, a trailing comma or a cut item removed."""
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    start = min((i for i in (s.find("{"), s.find("[")) if i >= 0), default=-1)
    if start < 0:
        return None
    s = s[start:]
    try:
        return json.loads(s)
    except ValueError:
        pass
    text, stack, in_str = _scan(s)
    for cut in range(0, 6):
        cand = text
        if cut:
            # cut back to the last complete item separator and close from there
            pos = [m.start() for m in re.finditer(r"[,}\]]", text)]
            if len(pos) < cut:
                break
            cand = text[: pos[-cut] + (0 if text[pos[-cut]] == "," else 1)]
        fixed, st, open_str = _scan(cand)
        fixed = fixed + ('"' if open_str else "")
        fixed = re.sub(r"[,:]\s*$", "", fixed.rstrip())
        fixed += "".join("}" if c == "{" else "]" for c in reversed(st))
        try:
            return json.loads(fixed)
        except ValueError:
            continue
    return None


def _objects(text: str) -> list[dict]:
    """Every complete top-level {...} of ``text`` (nested objects allowed), in order."""
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
            if depth == 1:
                start = i
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict):
                        out.append(obj)
                except ValueError:
                    pass
    return out


def salvage_items(raw: str, name: str) -> dict | None:
    """A tool call cut by max_tokens: ``{param: [complete items]}`` from ``<function=name><parameter=param>[...``."""
    m = re.search(r"<function=" + re.escape(name) + r">\s*<parameter=([\w-]+)>\s*\[(.*)", raw or "", re.S)
    if not m:
        return None
    items = _objects(m.group(2))
    return {m.group(1): items, "_salvaged": True} if items else None


# ------------------------------------------------------------------ time


def union_seconds(intervals) -> float:
    """Length of the union of [t0, t1] intervals: parallel calls share the GPU, their seconds are not added."""
    total, end = 0.0, None
    for a, b in sorted((float(a), float(b)) for a, b in intervals if b is not None and a is not None and b > a):
        if end is None or a > end:
            total += b - a
            end = b
        elif b > end:
            total += b - end
            end = b
    return round(total, 3)


# ------------------------------------------------------------------ text helpers


def fold(text: str) -> str:
    """Lowercase, no accents, single spaces: for robust substring tests."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(t.replace("’", "'").split())


def flat_text(value) -> str:
    """Every string of a JSON value, one per line (a draft's arguments as text)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(flat_text(v) for v in value.values())
    if isinstance(value, list | tuple):
        return "\n".join(flat_text(v) for v in value)
    return "" if value is None else str(value)


_STOPWORDS = set(
    "avec dans pour sont plus cette leurs entre depuis apres avant selon chez notre votre elles nous vous "
    "about which there their these those from with that this have were been".split()
)


def covered(point: str, text: str, ratio: float = 0.6) -> bool:
    """A point is covered when its figures are all there and most of its long words are."""
    t = fold(text)
    nums = allowed_figures(point)
    have = allowed_figures(text)
    if nums and not all(any(abs(n - h) < 0.006 for h in have) for n in nums):
        return False
    words = [w for w in re.findall(r"[a-z]{5,}", fold(point)) if w not in _STOPWORDS]
    if not words:
        return bool(nums) or fold(point) in t
    return sum(w[:7] in t for w in words) >= max(1, round(len(words) * ratio))


def coverage(points: list[str], text: str) -> float:
    return 1.0 if not points else sum(covered(p, text) for p in points) / len(points)


# ------------------------------------------------------------------ web evidence


def evidence(text: str, head: list[str], since: int | None = None, cap: int = 4000) -> str:
    """Whole paragraphs and table rows of a page that carry a figure and a head word, recent years first."""
    paras = [p.strip() for p in (text or "").split("\n") if len(p.strip()) > 30]
    heads = [fold(w) for w in head if len(w) >= 4]

    def score(p: str) -> float:
        low = fold(p)
        hits = sum(h[:7] in low for h in heads)
        if heads and not hits:
            return 0
        nums = [v for _, v in figures(p)]
        if not nums:
            return 0
        years = [int(y) for y in re.findall(r"\b((?:19|20)\d\d)\b", p)]
        recent = sum(y >= since for y in years) if since else len(years)
        return hits * 2 + min(len(nums), 4) + recent * 3 - (len(p) > 900) * 3

    ranked = sorted((p for p in paras if score(p) > 2), key=score, reverse=True)
    out, n = [], 0
    for p in ranked:
        p = p[:1200]
        if n + len(p) > cap:
            continue
        out.append(p)
        n += len(p) + 1
    order = {p: i for i, p in enumerate(paras)}
    return "\n".join(sorted(out, key=lambda p: order.get(p, 0)))


def check_facts(facts, window: str) -> tuple[list[dict], int]:
    """Keep the facts whose value (every number in it) and year are in ``window`` and whose quote is in it
    (whitespace and case folded). A fact without a usable quote is kept only when its value and year sit in the
    same paragraph. Returns (kept, dropped)."""
    kept, dropped = [], 0
    paras = [fold(p) for p in (window or "").split("\n") if p.strip()]
    whole = fold(window)
    in_window = allowed_figures(window)
    for f in facts if isinstance(facts, list) else []:
        if not isinstance(f, dict):
            dropped += 1
            continue
        value, year = str(f.get("value") or ""), str(f.get("year") or "").strip()
        quote, fact = fold(f.get("quote") or ""), str(f.get("fact") or "").strip()
        vals = allowed_figures(value) or allowed_figures(fact)
        if not vals or not all(any(abs(v - w) < 0.006 for w in in_window) for v in vals):
            dropped += 1
            continue
        if year and year not in (window or ""):
            dropped += 1
            continue
        ok = len(quote) >= 12 and quote in whole
        if not ok:
            ok = any(
                (not year or year in p) and all(any(abs(v - w) < 0.006 for w in allowed_figures(p)) for v in vals)
                for p in paras
            )
        if not ok:
            dropped += 1
            continue
        kept.append({"year": year, "value": value.strip(), "fact": fact or value, "quote": f.get("quote") or ""})
    return kept, dropped


# ------------------------------------------------------------------ meeting notes

# « Présents : », « Participants : », « Excusé : », and per side: « Côté client (Maison Vernet) : », « Pour le client : »
_ROSTER = re.compile(
    r"^\s*[-*•]?\s*(pr[ée]sents?|participants?|excus[ée]e?s?|absents?|c[ôo]t[ée]\s+[^:\n]{2,50}?|"
    r"pour\s+(?:le|la|l['’])\s*(?:client|agence|prestataire|fournisseur|soci[ée]t[ée]|cabinet|mairie|direction)[^:\n]{0,40}?)"
    r"\s*:\s*(.+)$",
    re.I | re.M,
)
_ACTION_MARK = re.compile(
    r"->|→|\bpour le\b|\bavant le\b|\bla semaine du\b|\bs'en occupe\b|\brelance\b|\borganise\b|\bfournit\b|"
    r"\btransmet\b|\bfait le\b|\bpr[ée]sentera\b|\b[a-zé]{3,}(?:era|ira|ra)\b|\bà réserver\b|\bà rédiger\b",
    re.I,
)


def number_lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in (text or "").split("\n")]


def numbered(lines: list[str]) -> str:
    return "\n".join(f"L{i}: {ln}" for i, ln in enumerate(lines, 1) if ln.strip())


def roster(text: str) -> list[str]:
    """Names from the Présents / Participants / Excusés lines (role in parentheses dropped)."""
    names = []
    for m in _ROSTER.finditer(text or ""):
        body = re.sub(r"\([^)]*\)", "", m.group(2))
        for part in re.split(r"[,;]|\bet\b|\.\s", body):
            name = " ".join(part.split()).strip(" .")
            if 2 <= len(name) <= 60 and re.match(r"[A-ZÀ-Ý]", name):
                names.append(name)
    return list(dict.fromkeys(names))


def _name_on(name: str, text: str) -> bool:
    t = fold(text)
    return any(re.search(rf"\b{re.escape(p)}\b", t) for p in fold(name).split() if len(p) >= 3)


def _match_roster(owner: str, names: list[str]) -> str | None:
    o = fold(owner)
    for n in names:
        parts = [p for p in fold(n).split() if len(p) >= 3]
        if fold(n) == o or any(re.search(rf"\b{re.escape(p)}\b", o) for p in parts):
            return n
    return None


def check_actions(actions, lines: list[str], names: list[str]) -> tuple[list[dict], int]:
    """Keep actions whose owner(s) are in the roster AND on the cited line; a due date not written on that line is
    blanked, never guessed. Returns (kept, dropped)."""
    kept, dropped = [], 0
    for a in actions if isinstance(actions, list) else []:
        if not isinstance(a, dict):
            dropped += 1
            continue
        try:
            n = int(str(a.get("line") or "").lstrip("Ll"))
        except ValueError:
            n = 0
        line = lines[n - 1] if 1 <= n <= len(lines) else ""
        owner_raw = str(a.get("owner") or "").strip()
        owners = [o.strip() for o in re.split(r",|&|\bet\b|/|\+", owner_raw) if o.strip()]
        matched = [_match_roster(o, names) for o in owners]
        if not line or not owners or not all(matched) or not all(_name_on(o, line) for o in owners):
            dropped += 1
            continue
        due = str(a.get("due") or "").strip()
        if due and fold(due) not in fold(line):
            due = ""
        action = " ".join(str(a.get("action") or "").split())
        if not action:
            dropped += 1
            continue
        kept.append({"line": n, "owner": " et ".join(dict.fromkeys(matched)), "action": action, "due": due})
    return kept, dropped


def action_lines(lines: list[str], names: list[str]) -> list[int]:
    """Line numbers that look like an action: a roster first name and an action marker, not a decision line."""
    firsts = {fold(n).split()[0] for n in names if n.strip()}
    out = []
    for i, ln in enumerate(lines, 1):
        low = fold(ln)
        if not ln.strip() or _ROSTER.match(ln) or re.match(r"^\s*[-*•]?\s*d[ée]cision", ln, re.I):
            continue
        if any(re.search(rf"\b{re.escape(f)}\b", low) for f in firsts) and _ACTION_MARK.search(ln):
            out.append(i)
    return out


def actions_table(actions: list[dict], lang: str = "fr") -> str:
    head = ("| Action | Responsable | Échéance |" if lang != "en" else "| Action | Owner | Due |") + "\n|---|---|---|"
    cell = lambda s: str(s).replace("|", "/").replace("\n", " ")  # noqa: E731
    rows = [f"| {cell(a['action'])} | {cell(a['owner'])} | {cell(a['due'] or '—')} |" for a in actions]
    return head + "\n" + "\n".join(rows)


# ------------------------------------------------------------------ offers and costs

# « 1) Konica Minolta », « 2. Nexa IT », « Devis 1 – Sauvegardia (Nantes) », « Offre B : Orka », « Fournisseur n° 2 - X »
_OFFER_HEAD = re.compile(
    r"^\s*(?:\d{1,2}\s*[.)]\s+|(?i:offre|fournisseur|option|devis|proposition|prestataire|candidat)\s*"
    r"(?:(?i:n)[°o]\s*)?[A-Z\d]{0,2}\s*[:–—-]\s*)"
    r"([A-ZÀ-Ý][\w&' .-]{1,60})",
    re.M,
)
_BLOCK_END = re.compile(
    r"^\s*(?:remarques?|notes?|contraintes?|besoins?|commentaires?|conclusion|synth[èe]se|pi[èe]ces? jointes?)\b",
    re.I,
)
_PRICE = re.compile(r"\d\s*(?:k\s*)?(?:€|eur\b|euros?\b)|€\s*\d", re.I)
_NOT_OFFER = re.compile(
    r"^(?:planning|budget|formation|divers|reprise|contexte|objet|besoin|point|d[ée]cision|remarques?|synth)",
    re.I,
)


def offer_blocks(text: str) -> list[tuple[str, str]]:
    """(name, block text) of each offer of a pasted comparison: from its heading to the next heading, the last one
    ending at a « Remarques / Contrainte / Besoin » paragraph. A block counts only if it carries a price (€): a
    numbered agenda (« 1. Approbation du PV », « 3. Santé ») is not a list of offers."""
    text = text or ""
    heads = []
    for m in _OFFER_HEAD.finditer(text):
        name = re.split(r"\s+[–—(-]\s*|\s*\(|\s*:", m.group(1).strip())[0].strip(" .")
        if name and not _NOT_OFFER.match(name):
            heads.append((m.start(), name))
    out = []
    for i, (start, name) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        lines, body = text[start:end].split("\n"), []
        for k, ln in enumerate(lines):
            if k and _BLOCK_END.match(ln):
                break
            body.append(ln)
        block = "\n".join(body).strip()
        if _PRICE.search(block):
            out.append((name, block))
    seen, uniq = set(), []
    for name, block in out:
        if name not in seen:
            seen.add(name)
            uniq.append((name, block))
    return uniq


def offer_names(text: str) -> list[str]:
    return [name for name, _ in offer_blocks(text)]


def constraints(text: str) -> dict:
    """« budget annuel maximal de 20 000 € », « sous 4 heures », « contrat de 48 mois » from the user's text."""
    t = text or ""
    out: dict = {}
    m = re.search(
        r"budget\s+(?:annuel\s+)?(?:maxi(?:mal|mum)\s+)?(?:annuel\s+)?(?:de\s+|:\s*)?(\d[\d  .,]*)\s*(k)?\s*€", t, re.I
    )
    if m:
        v = to_float(m.group(1).strip(" .,"))
        out["budget_year"] = v * (1000 if m.group(2) else 1)
    m = re.search(r"(?:intervention|d[ée]lai|r[ée]tablissement)[^.\n]{0,40}?sous\s+(\d+)\s*(?:h\b|heures?)", t, re.I)
    if m:
        out["sla_hours"] = float(m.group(1))
    m = re.search(r"(?:dur[ée]e|contrat|engagement)\s+(?:de\s+|sur\s+)?(\d{2})\s*mois", t, re.I)
    if m:
        out["months"] = int(m.group(1))
    return out


def _num(v, default: float = 0.0) -> float:
    if isinstance(v, bool):
        return default
    if isinstance(v, int | float):
        return float(v)
    vals = numbers(str(v or ""))
    return vals[0] if vals else default


def compute_offers(offers, cons: dict) -> dict:
    """Costs computed by the harness from the analyst's typed description, then the verdict.

    For each offer and each configuration (base, base + one option): monthly, annual, one-off, year-1 and
    full-term cost, and whether it meets the budget (year-1 cost), the response time and the term. The verdict is the
    compliant configuration with the lowest cost per year over its term."""
    rows = []
    for o in offers if isinstance(offers, list) else []:
        if not isinstance(o, dict) or not str(o.get("name") or "").strip():
            continue
        items = [i for i in o.get("monthly_items") or [] if isinstance(i, dict)]
        monthly = sum(_num(i.get("amount")) * (_num(i.get("qty"), 1.0) or 1.0) for i in items)
        one_off = sum(_num(i.get("amount")) for i in o.get("one_off") or [] if isinstance(i, dict))
        months = int(_num(o.get("months"), 12.0)) or 12
        sla = _num(o.get("sla_hours"), 0.0) or None
        configs = [("", monthly, sla)]
        for opt in o.get("options") or []:
            if isinstance(opt, dict) and _num(opt.get("monthly")):
                configs.append((str(opt.get("label") or "option"), monthly + _num(opt.get("monthly")),
                                _num(opt.get("sla_hours"), 0.0) or sla))  # fmt: skip
        for label, m, s in configs:
            annual = m * 12
            year1 = annual + one_off if months >= 12 else m * months + one_off
            term = m * months + one_off
            why = []
            if "budget_year" in cons and year1 > cons["budget_year"] + 0.5:
                why.append("budget")
            if "sla_hours" in cons and (s is None or s > cons["sla_hours"]):
                why.append("délai")
            if "months" in cons and months > cons["months"]:
                why.append("durée")
            rows.append(
                {
                    "offer": str(o["name"]).strip(),
                    "option": label,
                    "monthly": round(m, 2),
                    "annual": round(annual, 2),
                    "one_off": round(one_off, 2),
                    "year1": round(year1, 2),
                    "term": round(term, 2),
                    "months": months,
                    "per_year": round(term / months * 12, 2),
                    "sla_hours": s,
                    "ok": not why,
                    "fails": why,
                }
            )
    good = [r for r in rows if r["ok"]]
    best = min(good, key=lambda r: r["per_year"]) if good else None
    return {"rows": rows, "verdict": best, "constraints": cons}


def money(v: float, lang: str = "fr") -> str:
    if lang == "en":
        return f"€{v:,.0f}" if float(v).is_integer() else f"€{v:,.2f}"
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return s.replace(",", " ").replace(".", ",") + " €"


def euro_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n") if re.search(r"\d\s*(?:€|eur\b)", ln, re.I)]


def cost_coverage(offers, text: str) -> list[str]:
    """Lines of the pasted offers with a € amount that no item, one-off or option accounts for."""
    amounts = set()
    for o in offers if isinstance(offers, list) else []:
        if not isinstance(o, dict):
            continue
        for key in ("monthly_items", "one_off"):
            for i in o.get(key) or []:
                if isinstance(i, dict):
                    amounts.add(round(_num(i.get("amount")), 4))
        for opt in o.get("options") or []:
            if isinstance(opt, dict):
                amounts.add(round(_num(opt.get("monthly")), 4))
    missing = []
    for ln in euro_lines(text):
        vals = [round(v, 4) for v in numbers(re.sub(r"\b(?:19|20)\d\d\b", " ", ln))]
        euros = [v for v in vals if v > 0]
        if euros and not any(any(abs(v - a) < 0.006 for a in amounts) for v in euros):
            missing.append(ln[:160])
    return missing


_REQUIREMENT = re.compile(r"contrainte|exig|besoin|imp[ée]rati|souhait|demand[ée]|budget|requirement|must|need", re.I)


def requirement_lines(text: str) -> str:
    """The lines of a pasted text that state the buyer's own constraints (« Contrainte interne : … », « Besoin : … »),
    not the offers' terms: an offer's « contrat de 24 mois » is not a requirement."""
    return "\n".join(ln for ln in (text or "").split("\n") if _REQUIREMENT.search(ln) and not _OFFER_HEAD.match(ln))
