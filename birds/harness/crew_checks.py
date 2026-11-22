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


_CHANGE_BEFORE = re.compile(
    r"(?:croissance|hausse|augmentation|progression|baisse|recul|diminution|gain|perte|plus|moins|increase|growth|"
    r"rise|decline|drop|fall)\s+(?:de\s+|d['’]|of\s+|by\s+)?(?:\S+\s+){0,1}$",
    re.I,
)
_CHANGE_FACT = re.compile(
    r"croiss|hauss|augment|progress|baiss|recul|diminu|gagn|perd|de plus|de moins|\+\s?\d|increas|grow|rise|declin|"
    r"drop|fell|fall",
    re.I,
)
_YEAR = re.compile(r"\b((?:19|20)\d\d)\b")


def _positions(sent: str, v: float) -> list[int]:
    return [m.start() for m in _NUM.finditer(sent) if abs(to_float(m.group(0)) - v) < 0.006 and not _is_year(m.group(0), v)]


def _year_of(sent: str, p: int, years: list[tuple[int, str]]) -> str | None:
    """The year a value at ``p`` belongs to: « 22 % en 2021 » (a year right after it, nothing in between), else the
    nearest year before it (« En 2021, 22 % … »)."""
    for at, y in years:
        gap = sent[p:at]
        if at > p and len(gap) <= 30 and len(_NUM.findall(gap)) <= 1 and not re.search(r"[.;]", gap):
            return y
    before = [(at, y) for at, y in years if at < p]
    return before[-1][1] if before else None


def _fact_sentence(sent: str, vals: set, year: str, fact: str) -> bool:
    """Every value of the fact in this sentence, the claimed year in it and the nearest year to the value, and a
    change (« en croissance de 700 000 ») never recorded as a level."""
    have = allowed_figures(sent)
    if not all(any(abs(v - w) < 0.006 for w in have) for v in vals):
        return False
    years = [(m.start(), m.group(1)) for m in _YEAR.finditer(sent)]
    for v in vals:
        pos = _positions(sent, v)
        if not pos:
            return False
        if year:
            if not years or year not in {y for _, y in years}:
                return False
            if not any(_year_of(sent, p, years) == year for p in pos):
                return False
        if any(_CHANGE_BEFORE.search(sent[max(0, p - 40) : p]) for p in pos) and not _CHANGE_FACT.search(fact):
            return False
    return True


def check_facts(facts, window: str) -> tuple[list[dict], int]:
    """Keep the facts whose value (every number in it) sits in ONE sentence of ``window`` together with the claimed
    year, that year being the nearest one to the value, and that do not turn a change into a level. From « En
    croissance de 700 000 en 2019, ils sont 5,2 millions », « 2023 : 5,2 millions » (2023 is not in the sentence)
    and « 2019 : 700 000 » (a growth, not a count) are both rejected. Returns (kept, dropped)."""
    kept, dropped = [], 0
    sents = sentences(window)
    for f in facts if isinstance(facts, list) else []:
        if not isinstance(f, dict):
            dropped += 1
            continue
        value, year = str(f.get("value") or ""), str(f.get("year") or "").strip()
        fact = str(f.get("fact") or "").strip()
        m = _YEAR.search(year)
        year = m.group(1) if m else ""
        vals = allowed_figures(value) or allowed_figures(fact)
        if not vals or not any(_fact_sentence(st, vals, year, fact + " " + value) for st in sents):
            dropped += 1
            continue
        kept.append({"year": year, "value": value.strip(), "fact": fact or value, "quote": f.get("quote") or ""})
    return kept, dropped


# ------------------------------------------------------------------ email recipient and signature

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CLOSING = re.compile(
    r"^\s*(bien\s+cordialement|cordialement|bien\s+[àa]\s+(?:vous|toi)|tr[èe]s\s+cordialement|sinc[èe]res\s+salutations|"
    r"salutations(?:\s+distingu[ée]es)?|[àa]\s+bient[ôo]t|merci(?:\s+d.avance)?|best\s+regards|kind\s+regards|regards|"
    r"sincerely|best\s+wishes|thanks)\b\s*[,.!]?",
    re.I,
)


def emails(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0).rstrip(".") for m in _EMAIL.finditer(text or "")))


def fix_recipients(to, known: list[str], preferred: str = "") -> list[str]:
    """Each address of a draft that is not written in the user's text replaced by the one it was meant to be: the
    same local part (« nathalie.roux@alvea.fr » -> « nathalie.roux@groupe-alvea.fr »), else the closest, else the
    recipient chosen from the request. Without any address in the text, the draft's own addresses are kept."""
    import difflib

    to = [str(t).strip() for t in (to if isinstance(to, list) else [to] if to else []) if str(t).strip()]
    if not known:
        return to or ([preferred] if preferred else [])
    low = {k.lower(): k for k in known}
    out = []
    for t in to:
        if t.lower() in low:
            out.append(low[t.lower()])
            continue
        local = t.split("@")[0].lower()
        same = [k for k in known if k.split("@")[0].lower() == local]
        near = difflib.get_close_matches(t.lower(), list(low), n=1, cutoff=0.6)
        out.append(same[0] if same else low[near[0]] if near else preferred or "")
    out = [x for x in dict.fromkeys(out) if x]
    return out or ([preferred] if preferred else [])


def strip_signature(body: str, user_text: str) -> tuple[str, int]:
    """Signature lines after the closing formula that the user never wrote (« Pierre Dubois », « Responsable
    informatique », « La direction de la communication ») removed; a placeholder like « [Votre nom] » is kept.
    Returns (body, lines removed)."""
    lines = str(body or "").split("\n")
    at = max((i for i, ln in enumerate(lines) if _CLOSING.match(ln)), default=None)
    if at is None or at < len(lines) - 6:
        return body, 0
    whole = fold(user_text)
    head = _CLOSING.match(lines[at])
    rest_inline = lines[at][head.end() :].strip(" ,")
    removed = 0
    if rest_inline and fold(rest_inline) not in whole and not re.fullmatch(r"\[[^\]]+\]", rest_inline):
        lines[at] = lines[at][: head.end()].rstrip()
        removed += 1
    keep = lines[: at + 1]
    for ln in lines[at + 1 :]:
        x = ln.strip()
        if not x or re.fullmatch(r"\[[^\]]+\]", x) or (len(fold(x)) >= 3 and fold(x) in whole):
            keep.append(ln)
        else:
            removed += 1
    return "\n".join(keep).rstrip(), removed


# ------------------------------------------------------------------ meeting notes

# « Présents : », « Participants : », « Excusé : », and per side: « Côté client (Maison Vernet) : », « Pour le client : »
_ROSTER = re.compile(
    r"^\s*[-*•]?\s*(pr[ée]sents?|participants?|excus[ée]e?s?|absents?|c[ôo]t[ée]\s+[^:\n]{2,50}?|"
    r"pour\s+(?:le|la|l['’])\s*(?:client|agence|prestataire|fournisseur|soci[ée]t[ée]|cabinet|mairie|direction)[^:\n]{0,40}?)"
    r"\s*:\s*(.+)$",
    re.I | re.M,
)
_ACTION_MARK = re.compile(
    r"->|→|\bpour le\b|\bavant le\b|\bau plus tard\b|\bd'ici\b|\bla semaine du\b|\bs'en occupe\b|\brelance\b|"
    r"\borganise\b|\bfournit\b|\btransmet\b|\bfait le\b|\bpr[ée]sente(?:ra)?\b|\b[a-zé]{3,}(?:era|ira|ra)\b|"
    r"\bà (?:réserver|rédiger|faire|envoyer|prévoir)\b|\benvoie\b|\bcommande\b|\bchiffre\b|\bpr[ée]pare\b|"
    r"\bv[ée]rifie\b|\binstalle\b|\bmet à jour\b|\br[ée]serve\b|\bprend\b|\bdoit\b|\bdoivent\b|\br[ée]dige\b|"
    r"\bcontacte\b|\bappelle\b|\bplanifie\b|\bdemande\s+(?:à|au|aux|un|une|le|la|les|l')",
    re.I,
)
_DECISION_LINE = re.compile(r"^\s*[-*•]?\s*d[ée]cisions?\b", re.I)
_MONTHS = (
    "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre|"
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
_WEEKDAY = r"(?:(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|monday|tuesday|wednesday|thursday|friday)\s+)?"
_DATE = (
    rf"{_WEEKDAY}(?:1er|\d{{1,2}})(?:\s*/\s*\d{{1,2}}(?:\s*/\s*\d{{2,4}})?|\s+(?:{_MONTHS})(?:\s+(?:19|20)\d\d)?)"
    rf"|(?:fin|d[ée]but|mi-)\s*(?:{_MONTHS})"
)
_DUE = re.compile(
    r"(?P<mark>d'ici\s+(?:le\s+|la\s+)?|pour\s+le\s+|avant\s+le\s+|au\s+plus\s+tard\s+(?:le\s+)?|"
    r"(?:objectif\s+)?fin\s+le\s+|by\s+|before\s+)?(?:le\s+)?(?P<date>" + _DATE + r")"
    r"|cette\s+semaine|la\s+semaine\s+(?:prochaine|du\s+\d{1,2}(?:\s*/\s*\d{1,2})?(?:\s+(?:" + _MONTHS + r"))?)|demain|"
    r"(?:pour|avant)\s+la\s+prochaine\s+r[ée]union|d'ici\s+la\s+fin\s+(?:du\s+mois|de\s+la\s+semaine)|this\s+week|"
    r"tomorrow|next\s+week",
    re.I,
)


def due_on(line: str) -> str:
    """The due date written on a note line, verbatim: « d'ici lundi 23/11 », « pour le 10/12 », « avant le 4/12 »,
    « le 3 décembre », « cette semaine », « demain ». A date range (« entre le 18 et le 29 janvier », « du 4 au 15
    janvier ») is not a due date; a date after « d'ici / pour le / avant le » wins over a bare one. Empty if none."""
    marked, bare = [], []
    line = line or ""
    for m in _DUE.finditer(line):
        before = line[max(0, m.start() - 16) : m.start()]
        if re.search(r"(?:\bentre\b.*|\bet|\bdu|\bau|\bà partir du|\bdepuis le)\s*$", before, re.I):
            continue
        text = m.group(0).strip()
        (marked if m.group("mark") or m.group("date") is None else bare).append(text)
    return (marked + bare)[0] if marked or bare else ""


_MONTH_NUM = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}  # fmt: skip


def fix_years(text: str, notes: str) -> tuple[str, int]:
    """Every « <month> <year> » of a draft checked against the notes: the year the notes give that month, or, when
    the notes name the month without a year, the one that follows the meeting date (training « en janvier » after a
    meeting on 19 novembre 2026 is janvier 2027, never janvier 2026). Returns (text, years changed)."""
    nf = fold(notes)
    ref = re.search(r"\b(?:1er|\d{1,2})\s+(" + "|".join(_MONTH_NUM) + r")\s+((?:19|20)\d\d)\b", nf)
    changed = 0

    def repl(m):
        nonlocal changed
        mon, yr = fold(m.group(1)), m.group(2)
        explicit = set(re.findall(rf"\b{mon}\s+((?:19|20)\d\d)\b", nf))
        if yr in explicit or (not explicit and not re.search(rf"\b{mon}\b", nf)):
            return m.group(0)
        if len(explicit) == 1:
            good = explicit.pop()
        elif explicit or not ref:
            return m.group(0)
        else:
            good = str(int(ref.group(2)) + (_MONTH_NUM[mon] < _MONTH_NUM[ref.group(1)]))
        if good != yr:
            changed += 1
        return f"{m.group(1)} {good}"

    return re.sub(rf"\b({_MONTHS})\s+((?:19|20)\d\d)\b", repl, text or "", flags=re.I), changed


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
    """Keep actions whose owner(s) are in the roster AND on the cited line, the line being neither a decision nor a
    line without anything to do. The due date is read in code from that line (due_on); a date the model gives that
    is not written there is blanked, never guessed. Returns (kept, dropped)."""
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
        # a decision is not an action (« Décision : on gèle… »), nor a line where nobody is to do anything
        # (« Camille relaie la demande des bureaux… ») : no action verb and no due date
        code_due = due_on(line)
        if _DECISION_LINE.match(line) or not (code_due or _ACTION_MARK.search(line)):
            continue
        due = str(a.get("due") or "").strip()
        due = code_due or (due if due and fold(due) in fold(line) else "")
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
        if not ln.strip() or _ROSTER.match(ln) or _DECISION_LINE.match(ln):
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
    """« budget annuel maximal de 20 000 € », « budget validé … de 7 000 € HT maximum », « sous 4 heures »,
    « contrat de 48 mois », « rétention d'au moins 60 jours », « hébergées en France » from the user's text."""
    t = text or ""
    out: dict = {}
    m = re.search(r"budget[^.\n€;]{0,60}?(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(k)?\s*€", t, re.I)
    if m:
        v = to_float(m.group(1).strip(" .,"))
        out["budget_year"] = v * (1000 if m.group(2) else 1)
    m = re.search(r"(?:intervention|d[ée]lai|r[ée]tablissement)[^.\n]{0,40}?sous\s+(\d+)\s*(?:h\b|heures?)", t, re.I)
    if m:
        out["sla_hours"] = float(m.group(1))
    m = re.search(r"(?:dur[ée]e|contrat|engagement)\s+(?:de\s+|sur\s+)?(\d{2})\s*mois", t, re.I)
    if m:
        out["months"] = int(m.group(1))
    m = re.search(r"r[ée]tention[^.\n;]{0,25}?(?:d.au moins|minimum|minimale? de|≥|>=)\s*(\d+)\s*jours", t, re.I)
    if m:
        out["retention_days"] = int(m.group(1))
    m = re.search(r"h[ée]berg[ée]?\w*\s+(?:en|dans l[ae']\s*)\s*(France|Europe|Union europ[ée]enne|UE)\b", t, re.I)
    if m:
        out["country"] = m.group(1)
    return out


# ------------------------------------------------------------------ costs read from the pasted offers, in code

_AMOUNT = re.compile(r"(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(k)?\s*(?:€|eur\b|euros?\b)", re.I)
_UNITS = {
    "utilisateur": "utilisateur", "user": "utilisateur", "salarie": "utilisateur", "collaborateur": "utilisateur",
    "licence": "licence", "poste": "poste", "machine": "machine", "copieur": "machine", "multifonction": "machine",
    "imprimante": "machine", "serveur": "serveur", "site": "site", "ligne": "ligne", "badge": "badge",
}  # fmt: skip
_PER_UNIT = re.compile(r"^\s*(?:HT\s*)?(?:/\s*|par\s+|chacun\w*\s+par\s+)(" + "|".join(_UNITS) + r")s?\b", re.I)
_MONTHLY = re.compile(r"(?:/\s*|par\s+|\ble\s+)mois\b|mensuel", re.I)
_ONE_OFF = re.compile(r"une (?:seule )?fois|unique|mise en (?:service|place)|install|frais d.acc[eè]s|setup|ponctuel", re.I)
_VARIABLE = re.compile(r"^\s*(?:HT\s*)?(?:/|par|la|le|l')\s*(?:min\w*|appel|sms|go\b|to\b|km|heure)", re.I)
_PAGE_KIND = re.compile(r"(n\s*&\s*b|noir(?: et blanc)?|mono\w*|couleurs?|colou?r)", re.I)


def _kind_of_page(word: str) -> str:
    return "couleur" if fold(word).startswith(("couleur", "color", "colour")) else "nb"


def counts(text: str) -> dict:
    """Quantities stated in the text: « 45 utilisateurs », « dont 20 ont besoin d'un poste », « 38 000 pages N&B »,
    « 1,8 To de données ». The first statement of each wins."""
    t = text or ""
    out: dict = {}
    for m in re.finditer(r"dont\s+(\d[\d  ]*)\s+(?:ont|a)\s+besoin\s+d.une?\s+([a-zà-ÿ]+)", t, re.I):
        unit = _UNITS.get(fold(m.group(2)).rstrip("s"))
        if unit:
            out.setdefault(unit, to_float(m.group(1)))
    for m in re.finditer(r"(\d{1,3}(?:[   ]\d{3})+|\d+)\s+([a-zà-ÿ]+)", t, re.I):
        unit = _UNITS.get(fold(m.group(2)).rstrip("s"))
        if unit:
            out.setdefault(unit, to_float(m.group(1)))
    for m in re.finditer(r"(\d{1,3}(?:[   ]\d{3})+|\d+)\s*(?:pages?|copies?|impressions?)\s+" + _PAGE_KIND.pattern, t, re.I):
        out.setdefault("pages_" + _kind_of_page(m.group(2)), to_float(m.group(1)))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(To|Go|TB|GB)\s+de\s+donn[ée]es", t, re.I)
    if m:
        out["storage_go"] = to_float(m.group(1)) * (1000 if m.group(2).upper() in ("TO", "TB") else 1)
    return out


def _segments(block: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n|\s;\s", block) if s.strip()]


def _label(left: str) -> str:
    part = re.split(r",\s|[;(]|:\s", left)
    for p in reversed(part):
        p = re.sub(r"\s+(?:de|à|a|pour|:)$", "", p.strip(" -–:.")).strip()
        if len(p) >= 3:
            return p[:50]
    return ""


def parse_offer(name: str, block: str, qty: dict) -> dict:
    """One offer in the cost_model shape, read in code from its block: monthly items (unit price x stated quantity,
    per-page price x stated volume, per-tranche price x tranches needed), one-off fees, options, term, response time,
    retention and hosting. ``unknown`` lists the € amounts it could not place: the offer is then not complete."""
    o: dict = {"name": name, "monthly_items": [], "one_off": [], "options": [], "unknown": [], "variable": []}
    m = re.search(r"(?:engagement|contrat|dur[ée]e)[^.\n;]{0,30}?(\d{1,3})\s*mois", block, re.I)
    if m:
        o["months"] = int(m.group(1))
    m = re.search(r"(?:intervention|d[ée]lai d.intervention|r[ée]tablissement|RTO|restauration|d[ée]pannage)"
                  r"[^.\n;(]{0,50}?(\d+)\s*(?:h\b|heures?)", block, re.I)  # fmt: skip
    if m:
        o["sla_hours"] = float(m.group(1))
    m = re.search(r"r[ée]tention\s*:?\s*(\d+)\s*jours", block, re.I)
    if m:
        o["retention_days"] = int(m.group(1))
    host = [ln for ln in block.split("\n") if re.search(r"h[ée]berg|centre de donn|datacenter|data center", ln, re.I)]
    if host:
        o["hosting"] = " ".join(host)
    included = re.search(r"(\d+(?:[.,]\d+)?)\s*(To|Go)\s+inclus", block, re.I)
    for seg in _segments(block):
        amounts = list(_AMOUNT.finditer(seg))
        for i, a in enumerate(amounts):
            value = to_float(a.group(1)) * (1000 if a.group(2) else 1)
            left = seg[amounts[i - 1].end() if i else 0 : a.start()]
            right = seg[a.end() : amounts[i + 1].start() if i + 1 < len(amounts) else len(seg)][:80]
            if value <= 0:
                continue
            if _VARIABLE.match(right) and not re.match(r"^\s*(?:HT\s*)?(?:/|par)\s*mois", right, re.I):
                o["variable"].append(seg[:160])  # per minute, per Go...: no volume to multiply by, left out (said)
                continue
            page = _PAGE_KIND.search(right[:30]) or (
                _PAGE_KIND.search(left) if re.search(r"cop|page|impression", seg, re.I) and value < 1 else None
            )
            if page and value < 5:
                vol = qty.get("pages_" + _kind_of_page(page.group(1)))
                if vol is None:
                    o["unknown"].append(seg[:160])
                    continue
                o["monthly_items"].append({"label": f"pages {page.group(1)}", "amount": value, "qty": vol})
                continue
            tail = re.split(r"[.!?]\s", left)[-1][-60:]
            option = re.search(r"\boption", tail + right[:20], re.I)
            monthly = bool(_MONTHLY.search(right[:40]) or re.search(r"mensuel", _label(left), re.I))
            if option:
                label = _label(re.sub(r"\s*\b(?:en\s+)?option(?:nel\w*)?\b", " ", left, flags=re.I))
                opt = {"label": label[:60] or "option"}
                h = re.search(r"(\d+)\s*(?:h\b|heures?)", label)
                if h:
                    opt["sla_hours"] = float(h.group(1))
                d = re.search(r"(\d+)\s*jours", label)
                if d:
                    opt["retention_days"] = int(d.group(1))
                opt["monthly" if monthly else "one_off"] = value
                o["options"].append(opt)
                continue
            if monthly:
                q, unit = 1.0, None
                per = _PER_UNIT.match(right)
                each = re.search(r"\b(?:les\s+)?(\d+)\s+([a-zà-ÿ]+)\s+à\s*$", left, re.I)
                tranche = re.search(r"par tranche de\s+(\d+)\s*(Go|To)", right, re.I)
                if per:
                    unit = _UNITS[fold(per.group(1)).rstrip("s")]
                    q = qty.get(unit)
                elif each and re.match(r"^\s*(?:HT\s*)?chacun", right, re.I):
                    q = to_float(each.group(1))
                elif tranche:
                    need = qty.get("storage_go")
                    if need is None or not included:
                        q = None
                    else:
                        inc = to_float(included.group(1)) * (1000 if included.group(2).upper() == "TO" else 1)
                        size = to_float(tranche.group(1)) * (1000 if tranche.group(2).upper() == "TO" else 1)
                        q = max(0.0, float(-(-round((need - inc) / size, 6) // 1)))
                if q is None:
                    o["unknown"].append(seg[:160])
                    continue
                label = unit or ("tranche de " + " ".join(tranche.groups()) if tranche else "") or _label(left)
                o["monthly_items"].append({"label": label or "mensuel", "amount": value, "qty": q})
                continue
            if _ONE_OFF.search(left + right[:30]):
                o["one_off"].append({"label": _label(left) or "frais", "amount": value})
                continue
            o["unknown"].append(seg[:160])
    o["complete"] = bool(o["monthly_items"]) and not o["unknown"]
    return o


def parse_offers(text: str) -> list[dict]:
    """Every offer of a pasted comparison, read in code (see parse_offer). Quantities come from the text outside
    the offers first (the buyer's need), then from each offer's own block."""
    blocks = offer_blocks(text)
    outside = text or ""
    for _, b in blocks:
        outside = outside.replace(b, "")
    base = counts(outside)
    return [parse_offer(name, block, {**counts(block), **base}) for name, block in blocks]


def same_offer(a: str, b: str) -> bool:
    fa, fb = fold(a), fold(b)
    return bool(fa and fb) and (fa == fb or fa.startswith(fb) or fb.startswith(fa) or fa.split()[0] == fb.split()[0])


def _num(v, default: float = 0.0) -> float:
    if isinstance(v, bool):
        return default
    if isinstance(v, int | float):
        return float(v)
    vals = numbers(str(v or ""))
    return vals[0] if vals else default


_EU = ("france", "allemagne", "irlande", "belgique", "pays-bas", "luxembourg", "espagne", "italie", "portugal",
       "autriche", "suede", "finlande", "danemark", "pologne", "europe", "ue")  # fmt: skip


def _hosted_in(country: str, hosting: str) -> bool:
    c = fold(country)
    if c in ("europe", "ue", "union europeenne"):
        return any(re.search(rf"\b{re.escape(x)}\b", hosting) for x in _EU)
    return c in hosting


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
        retention = o.get("retention_days")
        hosting = fold(o.get("hosting") or "")
        configs = [("", monthly, one_off, sla, retention)]
        for opt in o.get("options") or []:
            if isinstance(opt, dict) and (_num(opt.get("monthly")) or _num(opt.get("one_off"))):
                configs.append((str(opt.get("label") or "option"), monthly + _num(opt.get("monthly")),
                                one_off + _num(opt.get("one_off")), _num(opt.get("sla_hours"), 0.0) or sla,
                                opt.get("retention_days") or retention))  # fmt: skip
        for label, m, once, s, keep in configs:
            annual = m * 12
            year1 = annual + once if months >= 12 else m * months + once
            term = m * months + once
            why = []
            if "budget_year" in cons and year1 > cons["budget_year"] + 0.5:
                why.append("budget")
            if "sla_hours" in cons and (s is None or s > cons["sla_hours"]):
                why.append("délai")
            if "months" in cons and months > cons["months"]:
                why.append("durée")
            if "retention_days" in cons and keep is not None and keep < cons["retention_days"]:
                why.append("rétention")
            if "country" in cons and hosting and not _hosted_in(cons["country"], hosting):
                why.append("hébergement")
            rows.append(
                {
                    "offer": str(o["name"]).strip(),
                    "option": label,
                    "monthly": round(m, 2),
                    "annual": round(annual, 2),
                    "one_off": round(once, 2),
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


def sentences(text: str) -> list[str]:
    """Sentences and lines of a text (« 1,5 » and « 0.0045 » are not cut)."""
    return [p for p in re.split(r"(?<=[.!?;])\s+|\n", text or "") if p.strip()]


def cost_claims(text: str, costs: dict | None, blocks: dict | None = None, tol: float = 0.05) -> list[str]:
    """€ amounts a draft ties to ONE offer that match neither a cost the harness computed for it (within ``tol``)
    nor an amount of that offer's own pasted block. « Konica : 170 424 € par an » when the code computed 19 944 € is
    returned; a sentence naming no offer or several is left to the provenance check."""
    rows = (costs or {}).get("rows") or []
    if not rows:
        return []
    names = list(dict.fromkeys(r["offer"] for r in rows))
    figs = {n: [r[k] for r in rows if r["offer"] == n for k in ("monthly", "annual", "one_off", "year1", "term",
                                                                  "per_year")] for n in names}  # fmt: skip
    own = {n: allowed_figures((blocks or {}).get(n, "")) for n in names}
    budget = (costs.get("constraints") or {}).get("budget_year")
    bad = []
    for sent in sentences(text):
        low = fold(sent)
        named = [n for n in names if fold(n) in low or (len(fold(n).split()[0]) >= 4 and fold(n).split()[0] in low)]
        if len(named) != 1:
            continue
        n = named[0]
        for m in _AMOUNT.finditer(sent):
            v = to_float(m.group(1)) * (1000 if m.group(2) else 1)
            if v < 100 or (budget and abs(v - budget) < 0.5):
                continue
            if any(abs(v - f) <= tol * max(abs(f), 1) for f in figs[n] if f) or any(abs(v - a) < 0.006 for a in own[n]):
                continue
            bad.append(m.group(1))
    return bad


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
