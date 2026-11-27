"""Deep research (« Recherche approfondie ») in Mode Agent: a recipe of short, typed generations checked in code.

    plan (1 generation: sub-questions and searches) -> searches in parallel -> 6 to 10 pages read (0 generation)
    -> 3 extractors in parallel (claims with an exact quote, entities, relations) -> checks in code (each quote must be
    in its page, each figure in its quote, each entity in its page, each relation's two ends in its quote)
    -> 1 report (sections, numbered citations) -> checks in code (figures against the cited page, citations moved
    to the page that holds the figure, unsupported sentences removed, weak ones said in « À vérifier »)

A 4B model cannot keep a long research plan in its head; it can write one short JSON at a time. The harness keeps the
plan, the pages and the bookkeeping, and builds the widgets (research card with the sources and their quotes,
relation graph, timeline) from the verified claims only: nothing the model writes outside a quote found in a page
reaches a widget. Budget: 6 generations at most (plan, 3 extractors, report, 1 spare), ends at t0 + 240 s.

``ask`` is the trigger, in the user's own words: « recherche approfondie », « étude approfondie », « deep research »,
« carte des acteurs », « qui est lié à qui ». With pasted text or an attached document, the sources are the user's
own text (no web): « fais la carte des acteurs de ce texte ».
"""

from __future__ import annotations

import itertools
import json
import re
import time
from urllib.parse import unquote, urlsplit

from birds.harness import crew_checks as cc
from birds.harness.agent import Run
from birds.harness.crew import ABSTAIN, Crew, _Fallback
from birds.harness.crew_tools import _fn

# ------------------------------------------------------------------ triggers (own words only)

_DEEP = re.compile(
    r"\b(?:recherches?\s+(?:approfondies?|pouss[ée]es?|compl[èe]tes?\s+et\s+sourc[ée]es?)|"
    r"[ée]tudes?\s+approfondies?|enqu[êe]tes?\s+approfondies?|dossiers?\s+approfondis?|synth[èe]ses?\s+approfondies?|"
    r"(?:fais|faire|lance|mener|m[eè]ne)\s+(?:des|une)\s+recherches?\s+(?:compl[èe]tes?|d[ée]taill[ée]es?)\s+(?:sur|à propos)|"
    r"deep[- ]research|in[- ]depth\s+(?:research|study|investigation)|thorough\s+research|research\s+in\s+depth|"
    r"deep[- ]dive\s+(?:on|into)|creuse\s+(?:à fond|en profondeur)|en profondeur\s+(?:sur|le sujet)|"
    r"approfondis\s+(?:le sujet|la question|la recherche)|recherche approfondie)\b",
    re.I,
)
_GRAPH = re.compile(
    r"\b(?:cartes?\s+des\s+(?:acteurs|parties prenantes|relations|liens)|cartographie\s+des\s+(?:acteurs|parties prenantes|"
    r"relations|liens)|cartographie[rs]?\s+(?:l['’][ée]cosyst[èe]me|les acteurs)|qui\s+est\s+li[ée]e?\s+[àa]\s+qui|"
    r"qui\s+travaille\s+avec\s+qui|graphes?\s+(?:relationnels?|des relations|des liens)|r[ée]seau\s+(?:d['’]acteurs|des acteurs)|"
    r"relations\s+entre\s+(?:les\s+)?(?:acteurs|entreprises|soci[ée]t[ée]s|personnes|personnages|organisations)|"
    r"liens\s+entre\s+(?:les\s+)?(?:acteurs|entreprises|soci[ée]t[ée]s|personnes|organisations)|"
    r"(?:map|graph)\s+of\s+(?:the\s+)?(?:players|actors|stakeholders|relationships)|stakeholder\s+map|"
    r"who\s+is\s+(?:linked|connected|related)\s+to\s+whom|relationship\s+(?:graph|map)|ecosystem\s+map|"
    r"(?:l['’])?[ée]cosyst[èe]me\s+(?:de|du|des|d['’])\s*\S+)",
    re.I,
)
_ASKING = re.compile(
    r"\b(?:fai[st]|faire|r[ée]alise|pr[ée]pare|dresse|lance|m[eè]ne|mener|montre|donne|trace|dessine|cartographie|"
    r"construi[st]|j'ai besoin|il me faut|peux-tu|pourrais-tu|pouvez-vous|quel(?:le)?s?|qui|make|do|run|show|draw|build|"
    r"map|need|can you|could you|give)\b|\?\s*$",
    re.I,
)
_DEFINE = re.compile(
    r"^\s*(?:qu['’]est[- ]ce\s+qu|c['’]est\s+quoi|d[ée]finition|d[ée]finis|explique(?:-moi)?\s+(?:ce qu|la diff[ée]rence|"
    r"comment)|comment\s+(?:faire|fonctionne|marche|r[ée]aliser|on fait)|what\s+is|what's|how\s+(?:do|does|to))",
    re.I,
)
# « range ce dossier approfondi », « l'étude approfondie est en pièce jointe » : no ask, nothing starts
_NOT_ASK = re.compile(r"\b(?:range|classe|archive|supprime|renomme|envoie|transf[eè]re|imprime|relis)\b", re.I)


def ask(instr: str) -> str | None:
    """ "deep" | "graph" | None: an explicit request for deep research or for a relation map, in the user's words."""
    words = " ".join(str(instr or "").split())
    if not words or len(words) > 1200 or _DEFINE.search(words) or _NOT_ASK.search(words[:60]):
        return None
    deep = _DEEP.search(words)
    # « Recherche approfondie sur l'AI Act », « deep research on … »: the name of the task first is the ask itself
    if deep and (_ASKING.search(words) or deep.start() <= 2):
        return "deep"
    if _GRAPH.search(words) and _ASKING.search(words):
        return "graph"
    return None


_QUESTION = re.compile(
    r"\?|\b(?:quels?|quelles?|pourquoi|o[ùu] en est|[ée]tat des lieux|panorama|tendances?|enjeux|impact|acteurs|"
    r"compare|comparaison|avantages et inconv[ée]nients|what|which|why|trends?|impact|landscape)\b",
    re.I,
)


def question(instr: str) -> bool:
    """Mode Agent Activé with no deliverable: an informational question worth a research (« quels sont les enjeux de
    l'AI Act pour une PME ? »), not a greeting, a definition or a how-to."""
    words = " ".join(str(instr or "").split())
    return len(words.split()) >= 6 and bool(_QUESTION.search(words)) and not _DEFINE.search(words)


# ------------------------------------------------------------------ virtual tools

_S = {"type": "string"}
PLAN_RESEARCH = _fn(
    "plan_research",
    "Plan a deep research: 3 to 5 precise sub-questions and 3 to 5 short web searches.",
    {"questions": {"type": "array", "items": _S}, "queries": {"type": "array", "items": _S}},
    ["questions", "queries"],
)
ENTITY_TYPES = ("organisation", "personne", "lieu", "produit", "texte", "concept")
RECORD_CLAIMS = _fn(
    "record_claims",
    "Record the claims of the extracts, each with its source number, the exact quote, its entities and relations.",
    {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "integer", "description": "Number of the extract [n]."},
                    "claim": {"type": "string", "description": "One short sentence."},
                    "quote": {"type": "string", "description": "Exact words copied from the extract."},
                    "date": {"type": "string", "description": "Date or year written in the quote, or empty."},
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": _S, "type": {"type": "string", "enum": list(ENTITY_TYPES)}},
                            "required": ["name", "type"],
                        },
                    },
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"from": _S, "to": _S, "label": _S},
                            "required": ["from", "to", "label"],
                        },
                    },
                },
                "required": ["source", "claim", "quote"],
            },
        }
    },
    ["claims"],
)
WRITE_REPORT = _fn(
    "write_report",
    "Write the research report from the verified claims only.",
    {
        "title": _S,
        "summary": {"type": "string", "description": "3 to 4 sentences, the answer in short."},
        "sections": {
            "type": "array",
            "items": {"type": "object", "properties": {"heading": _S, "text": _S}, "required": ["heading", "text"]},
        },
    },
    ["title", "summary", "sections"],
)

PROMPTS = {
    "fr": {
        "plan": "Tu planifies une recherche approfondie sur la demande ci-dessus. Écris 3 à 5 sous-questions précises "
        "(une par aspect : faits et chiffres, acteurs, évolution, enjeux…) et 3 à 5 recherches web courtes en "
        "mots-clés, dans la langue de la demande. Appelle plan_research.",
        "extract": "Voici des extraits numérotés [n]. Relève au plus 10 affirmations utiles pour : {topic}. Pour "
        "chacune : le numéro de l'extrait, une phrase courte, la citation exacte recopiée mot pour mot, la date si "
        "elle est écrite, les entités nommées (organisation, personne, lieu, produit, texte de loi, concept) et les "
        "relations entre elles (de, vers, verbe court : « détient », « a racheté », « régule », « finance »). "
        "N'invente rien. Appelle record_claims.",
        "report": "Écris le rapport de recherche à partir des seules affirmations vérifiées ci-dessus. Titre, résumé "
        "de 3 à 4 phrases, puis une section par sous-question (titre court, 80 à 160 mots). Chaque phrase qui "
        "donne un fait finit par le numéro de sa source, par exemple [2]. Aucun chiffre qui n'est pas dans les "
        "affirmations. Appelle write_report.",
    },
    "en": {
        "plan": "You are planning a deep research on the request above. Write 3 to 5 precise sub-questions (one per "
        "aspect: facts and figures, players, trend, stakes…) and 3 to 5 short keyword web searches, in the language "
        "of the request. Call plan_research.",
        "extract": "Here are numbered extracts [n]. Record at most 10 useful claims for: {topic}. For each: the extract "
        "number, one short sentence, the exact quote copied word for word, the date if written, the named entities "
        "(organisation, person, place, product, law, concept) and the relations between them (from, to, short verb: "
        "« owns », « acquired », « regulates », « funds »). Invent nothing. Call record_claims.",
        "report": "Write the research report from the verified claims above only. Title, a 3-4 sentence summary, then "
        "one section per sub-question (short heading, 80 to 160 words). Every sentence that states a fact ends with "
        "its source number, e.g. [2]. No figure that is not in the claims. Call write_report.",
    },
}

MAX_QUERIES = 5
MAX_READ = 10
MIN_PAGES = 2  # fewer readable pages: the single agent takes over (honest fallback)
EXTRACTORS = 3
PAGE_TEXT = 9000  # page text kept to check quotes
EXTRACT_CHARS = 2200  # a page's extract given to an extractor
GROUP_CHARS = 6600
MAX_CLAIMS = 40
READ_UNTIL = 110.0  # seconds after t0: no page read starts later
WIDGET_BYTES = 7600

LABELS = {
    "planificateur": ("Plan de recherche", "Research plan"),
    "chercheur": ("Recherche et lecture", "Search and reading"),
    "lecteur": ("Extraction", "Extraction"),
    "redacteur": ("Rapport", "Report"),
    "verificateur": ("Vérification des sources", "Source check"),
}
REASON = {"fr": {"deep": "recherche approfondie : plan, sources, vérification",
                 "graph": "carte des acteurs à partir des sources"},
          "en": {"deep": "deep research: plan, sources, checks", "graph": "a map of the players from the sources"}}  # fmt: skip


def _size(w: dict) -> int:
    return len(json.dumps(w, ensure_ascii=False, separators=(",", ":")))


def _domain(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", cc.fold(text))


def quoted(quote: str, text: str) -> bool:
    """The quote is in the page: verbatim once folded, or at least 80 % of its 4-word runs are (a small model
    drops an article or changes an apostrophe)."""
    q, t = _words(quote), " ".join(_words(text))
    if len(q) < 4:
        return False
    if " ".join(q) in t:
        return True
    runs = [" ".join(q[i : i + 4]) for i in range(len(q) - 3)]
    return sum(r in t for r in runs) / len(runs) >= 0.8


def _named(name: str, text: str) -> bool:
    n = " ".join(_words(name))
    return len(n) >= 2 and bool(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", " ".join(_words(text))))


_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_MONTHS = ("janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
           "january february march april may june july august september october november december".split())  # fmt: skip


def date_key(date: str) -> str | None:
    """« mars 2024 » -> "2024-03", « 2019 » -> "2019", « 12 juin 2023 » -> "2023-06-12", else None."""
    d = cc.fold(date)
    y = _YEAR.search(d)
    if not y:
        return None
    month = next((i + 1 for names in _MONTHS for i, m in enumerate(names) if cc.fold(m) in d), None)
    if month is None:
        return y.group(1)
    day = re.search(r"\b([0-3]?\d)(?:er)?\s+[a-z]+\s+" + y.group(1), d)
    return f"{y.group(1)}-{month:02d}" + (f"-{int(day.group(1)):02d}" if day and 1 <= int(day.group(1)) <= 31 else "")


_DATE_NUM = re.compile(r"\d{1,2}[/h.]\d{1,2}|\d{1,2}[/h.]$")


def nums(text: str) -> list[tuple[str, float, bool]]:
    """Every number of a text (citation marks out): (raw, value, is_year). Small counts count too: a claim with
    « 3 usines » is checked like one with « 9 milliards »; dates (29/11) and times (10h30) are skipped."""
    text = cc._CITE.sub(" ", text or "")
    out = []
    for m in cc._NUM.finditer(text):
        raw = m.group(0)
        if _DATE_NUM.match(text[m.start() : m.end() + 3]) or text[m.start() - 1 : m.start()] == "/":
            continue
        v = cc.to_float(raw)
        out.append((raw, v, cc._is_year(raw, v)))
    return out


def numbers_in(sentence: str, quote: str, *, years_from: str = "") -> bool:
    """Each number of ``sentence`` is in ``quote`` (a year may also come from ``years_from``, its page)."""
    have = {round(v, 6) for _, v, _ in nums(quote)}
    years = have | {round(v, 6) for _, v, y in nums(years_from) if y}
    return all(round(v, 6) in (years if y else have) for _, v, y in nums(sentence))


def check_claims(raw, pages: dict[int, dict]) -> tuple[list[dict], dict]:
    """Keep the claims whose quote is in their page, whose figures are in their quote, and keep only the entities
    named in the page (and in the claim or quote) and the relations whose two ends are named in the quote."""
    stats = {"seen": 0, "no_quote": 0, "figure": 0, "weak": 0}
    out, seen = [], set()
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        stats["seen"] += 1
        try:
            n = int(c.get("source"))
        except (TypeError, ValueError):
            n = -1
        page = pages.get(n)
        claim, quote = (
            " ".join(str(c.get("claim") or "").split())[:240],
            " ".join(str(c.get("quote") or "").split())[:400],
        )
        if page is None or not claim or not quoted(quote, page["text"]):
            stats["no_quote"] += 1
            continue
        if not numbers_in(claim, quote, years_from=page["text"]):
            stats["figure"] += 1
            continue
        if cc.support(claim, quote + " " + page["text"][:4000]) < 0.5:
            stats["weak"] += 1
            continue
        key = cc.fold(claim)
        if key in seen:
            continue
        seen.add(key)
        both = claim + " " + quote
        ents, names = [], {}
        for e in c.get("entities") or []:
            if not isinstance(e, dict):
                continue
            name = " ".join(str(e.get("name") or "").split())[:60]
            if len(name) < 2 or not _named(name, page["text"]) or not _named(name, both):
                continue
            kind = str(e.get("type") or "concept").lower()
            kind = {"organization": "organisation", "person": "personne", "place": "lieu", "product": "produit",
                    "law": "texte", "loi": "texte"}.get(kind, kind)  # fmt: skip
            ents.append({"name": name, "type": kind if kind in ENTITY_TYPES else "concept"})
            names[cc.fold(name)] = name
        rels = []
        for r in c.get("relations") or []:
            if not isinstance(r, dict):
                continue
            a, b = names.get(cc.fold(str(r.get("from") or ""))), names.get(cc.fold(str(r.get("to") or "")))
            label = " ".join(str(r.get("label") or "").split())[:40]
            if a and b and a != b and label and _named(a, quote) and _named(b, quote) and not cc.unsupported(
                    label, cc.allowed_figures(quote)):  # fmt: skip
                rels.append({"from": a, "to": b, "label": label})
        date = " ".join(str(c.get("date") or "").split())[:40]
        if date and not (_YEAR.search(date) and _YEAR.search(date).group(1) in quote):
            date = ""
        out.append({"n": n, "claim": claim, "quote": quote, "date": date, "entities": ents, "relations": rels})
        if len(out) >= MAX_CLAIMS:
            break
    return out, stats


def build_graph(claims: list[dict], lang: str = "fr") -> dict | None:
    """The relation graph of the verified claims: nodes (entities merged by name), edges (relations merged), the
    claims they come from. None when fewer than 2 relations survived (no graph rather than a thin one)."""
    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    for i, c in enumerate(claims):
        for e in c["entities"]:
            k = cc.fold(e["name"])
            node = nodes.setdefault(k, {"id": f"e{len(nodes)}", "label": e["name"], "types": {}, "sources": set(),
                                        "claims": set()})  # fmt: skip
            node["types"][e["type"]] = node["types"].get(e["type"], 0) + 1
            node["sources"].add(c["n"])
            node["claims"].add(i)
            if len(e["name"]) > len(node["label"]):
                node["label"] = e["name"]
        for r in c["relations"]:
            a, b = cc.fold(r["from"]), cc.fold(r["to"])
            if a not in nodes or b not in nodes:
                continue
            k = (a, b, cc.fold(r["label"]))
            edge = edges.setdefault(k, {"s": a, "t": b, "label": r["label"], "sources": set(), "claims": set()})
            edge["sources"].add(c["n"])
            edge["claims"].add(i)
    if len(edges) < 2:
        return None
    degree = {k: 0 for k in nodes}
    for e in edges.values():
        degree[e["s"]] += 1
        degree[e["t"]] += 1
    keep = sorted(nodes, key=lambda k: (-degree[k], -len(nodes[k]["claims"]), nodes[k]["label"]))[:24]
    keep = [k for k in keep if degree[k] or len(nodes[k]["claims"]) >= 2]
    kept = set(keep)
    out_edges = [e for e in edges.values() if e["s"] in kept and e["t"] in kept][:40]
    used = sorted({i for k in keep for i in nodes[k]["claims"]} | {i for e in out_edges for i in e["claims"]})
    w = {
        "type": "graph",
        "v": 1,
        "title": "Carte des acteurs et des relations" if lang == "fr" else "Map of players and relations",
        "nodes": [{"id": nodes[k]["id"], "label": nodes[k]["label"],
                   "type": max(nodes[k]["types"], key=nodes[k]["types"].get),
                   "sources": sorted(nodes[k]["sources"]), "claims": sorted(nodes[k]["claims"])} for k in keep],
        "edges": [{"s": nodes[e["s"]]["id"], "t": nodes[e["t"]]["id"], "label": e["label"],
                   "sources": sorted(e["sources"]), "claims": sorted(e["claims"])} for e in out_edges],
        "claims": [{"i": i, "n": claims[i]["n"], "text": claims[i]["claim"][:150]} for i in used],
    }  # fmt: skip
    while _size(w) > WIDGET_BYTES and len(w["claims"]) > 4:
        w["claims"] = w["claims"][:-1]
    while _size(w) > WIDGET_BYTES and len(w["edges"]) > 2:
        w["edges"] = w["edges"][:-1]
    return w if _size(w) <= WIDGET_BYTES else None


def build_timeline(claims: list[dict], lang: str = "fr", sources: dict | None = None) -> dict | None:
    """Dated claims (the date written in the quote), in order. None under 3 dates."""
    events = []
    for c in claims:
        k = date_key(c["date"]) if c["date"] else None
        if k:
            events.append({"key": k, "date": c["date"], "label": c["claim"][:160], "n": c["n"]})
    events.sort(key=lambda e: e["key"])
    seen, uniq = set(), []
    for e in events:
        if (e["key"], cc.fold(e["label"])[:60]) not in seen:
            seen.add((e["key"], cc.fold(e["label"])[:60]))
            uniq.append(e)
    if len({e["key"] for e in uniq}) < 3:
        return None
    w = {"type": "timeline", "v": 1, "title": "Chronologie" if lang == "fr" else "Timeline", "events": uniq[:16],
         "origin": "sources"}  # fmt: skip
    while _size(w) > WIDGET_BYTES and len(w["events"]) > 3:
        w["events"] = w["events"][:-1]
    return w


def research_card(topic: str, questions: list[str], pages: list[dict], claims: list[dict], counts: dict,
                  lang: str = "fr") -> dict:  # fmt: skip
    """The research card: the question, the plan, each source read (domain, title, how many claims, one quote)."""
    by_n: dict[int, list[dict]] = {}
    for c in claims:
        by_n.setdefault(c["n"], []).append(c)
    srcs = []
    for p in pages:
        cl = by_n.get(p["n"], [])
        srcs.append({"n": p["n"], "title": p["title"][:90], "url": p.get("url", "")[:300], "domain": p.get("domain", ""),
                     "claims": len(cl), "quote": (cl[0]["quote"][:180] if cl else "")})  # fmt: skip
    w = {"type": "research", "v": 1, "topic": topic[:160], "questions": [q[:160] for q in questions][:5],
         "sources": srcs, "counts": counts}  # fmt: skip
    while _size(w) > WIDGET_BYTES and any(s["quote"] for s in w["sources"]):
        last = max((s for s in w["sources"] if s["quote"]), key=lambda s: s["n"])
        last["quote"] = ""
    while _size(w) > WIDGET_BYTES and len(w["sources"]) > 1:
        w["sources"] = w["sources"][:-1]
    return w


# ------------------------------------------------------------------ the recipe


class Research(Crew):
    """Deep research, on the crew's machinery (generations, tool steps, events, accounting, fallbacks)."""

    def _label(self, lane: str) -> str:
        role, _, rest = lane.partition("_")
        if role in LABELS:
            base = LABELS[role][1 if self.lang == "en" else 0]
            return f"{base} {rest}" if role == "lecteur" and rest else base
        return super()._label(lane)

    def _plan(self) -> list[tuple[str, str]]:
        own = bool(self.pasted or self.docs)
        lanes = [] if own else [("planificateur", "plan"), ("chercheur", "research")]
        lanes += [(f"lecteur_{i}", "brief") for i in range(1, EXTRACTORS + 1)]
        return lanes + [("redacteur_a", "drafts"), ("verificateur", "check")]

    def run(self, message: str, own: str, *, docs=None, history=None) -> Run:
        from concurrent.futures import ThreadPoolExecutor

        from birds.harness import guard
        from birds.harness.crew import MAX_CONCURRENT, Cancelled, split_request

        self.message, self.own, self.docs = message, own, list(docs or [])
        self.history, self.kept = self._digest(history or []), list(history or [])
        self.instr, self.pasted = split_request(own)
        self.max_calls = 6
        self.pool = ThreadPoolExecutor(MAX_CONCURRENT, thread_name_prefix="bird-research")
        try:
            self._start(self._plan())
            return self._research_run()
        except Cancelled:
            raise
        except _Fallback as f:
            return self._fallback(f.reason, None)
        except Exception as e:  # noqa: BLE001 - logged, then the single agent takes over
            self.agent.audit.log("crew_error", error=f"{type(e).__name__}: {guard.redact(str(e))[:200]}")
            return self._fallback("error", None)
        finally:
            self.pool.shutdown(wait=False, cancel_futures=True)

    # -------------------------------------------------------------- 1. plan
    def _subject(self) -> str:
        t = re.sub(r"^\s*(?:(?:bonjour|salut|hello)[,!]?\s*)?(?:peux-tu|pourrais-tu|pouvez-vous|can you|could you)?\s*",
                   "", self.instr, flags=re.I)  # fmt: skip
        m = re.search(r"\b(?:sur|à propos de|au sujet de|concernant|de l['’]|du|des|on|about|of|into)\s+(.+)", t, re.I)
        subject = m.group(1) if m and (_DEEP.search(t) or _GRAPH.search(t)) else t
        subject = _DEEP.sub(" ", subject)
        subject = re.sub(r"\b(?:fais|faire|lance|mène|réalise|une?|des|la|le|les|moi|stp|svp|please|make|do|a|an|the)\b",
                         " ", subject, flags=re.I)  # fmt: skip
        subject = re.split(r"[.?!\n]|\s+(?:avec|with)\s+(?:des|les)?\s*(?:sources|chiffres)", subject)[0]
        return " ".join(subject.split())[:120] or " ".join(self.instr.split())[:120]

    def _research_plan(self, topic: str) -> tuple[list[str], list[str]]:
        fr = self.lang == "fr"
        year = time.localtime().tm_year
        data = ("Demande : " if fr else "Request: ") + self.instr + (f"\nAnnée : {year}" if fr else f"\nYear: {year}")
        if self.history:
            data = self.history + "\n\n" + data
        g = self._gen("planificateur", "plan", self._user(data, PROMPTS[self.lang]["plan"]), [PLAN_RESEARCH], 320,
                      temperature=0.0, until=self.t0 + 40)  # fmt: skip
        args = self._args(g, "plan_research") or {}
        questions, queries = [], []
        for q in args.get("questions") or []:
            q = " ".join(str(q).split())
            if 8 <= len(q) <= 180 and cc.fold(q) not in {cc.fold(x) for x in questions}:
                questions.append(q)
        for q in args.get("queries") or []:
            q = " ".join(str(q).split()).strip("\"'«» ")
            if 3 <= len(q) <= 90 and cc.fold(q) not in {cc.fold(x) for x in queries}:
                queries.append(q)
        planned = bool(questions and queries)
        if not questions:  # the plan failed: generic sub-questions, written by code (no facts in them)
            questions = ([f"Quels sont les faits et chiffres clés sur {topic} ?", f"Qui sont les principaux acteurs de "
                          f"{topic} et comment sont-ils liés ?", f"Quelles évolutions récentes pour {topic} ?"] if fr else
                         [f"What are the key facts and figures on {topic}?", f"Who are the main players in {topic} "
                          f"and how are they linked?", f"What recent changes for {topic}?"])  # fmt: skip
        head = [topic] + [q for q in queries if cc.fold(q) != cc.fold(topic)]
        if len(head) < 3:
            head += [f"{topic} {'chiffres clés' if fr else 'key figures'}", f"{topic} {'acteurs' if fr else 'players'}",
                     f"{topic} {year}"]  # fmt: skip
        out, seen = [], set()
        for q in head:
            if cc.fold(q) not in seen:
                seen.add(cc.fold(q))
                out.append(q)
        if g:
            self._step("planificateur", "done", "plan", tokens=g["tokens"], seconds=g["seconds"],
                       detail=f"{len(questions)} sous-questions" if fr else f"{len(questions)} sub-questions",
                       items=questions[:5], planned=planned)  # fmt: skip
        else:
            self._step("planificateur", "done", "plan", detail="plan par défaut" if fr else "default plan",
                       items=questions[:5])  # fmt: skip
        return questions[:5], out[:MAX_QUERIES]

    # -------------------------------------------------------------- 2. search and read
    def _gather(self, queries: list[str], topic: str) -> list[dict]:
        fr = self.lang == "fr"
        lane = "chercheur"
        self._step(lane, "running", "research", detail=" · ".join(queries))
        results = list(self.pool.map(lambda q: self._tool(lane, "web_search", {"query": q, "max_results": 6}), queries))
        rows = [re.findall(r"^\s+(https?://\S+)\s*$", text, re.M) for _, step, text, _ in results if not step.error]
        urls, seen = [], set()
        for row in itertools.zip_longest(*rows):
            for u in row:
                if not u:
                    continue
                p = urlsplit(unquote(u))
                key = (p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), p.query)
                if key not in seen:
                    seen.add(key)
                    urls.append(u)
        if not urls:
            self._step(lane, "error", "research", detail="no_results")
            raise _Fallback("no_results")
        firsts, sites = [], set()
        for u in urls:  # one page per site first: several points of view, not one site read three times
            if _domain(u) not in sites:
                sites.add(_domain(u))
                firsts.append(u)
        urls = (firsts + [u for u in urls if u not in firsts])[: MAX_READ + 4]
        self.trace["queries"] = len(queries)
        head = [w for w in re.findall(r"[\wÀ-ÿ'-]{3,}", topic)][:8]
        pages: list[dict] = []
        read, skipped, domains = 0, 0, []
        for u in urls:
            if len(pages) >= MAX_READ or time.monotonic() - self.t0 > READ_UNTIL or self._left() < 110:
                break
            _, step, text, _ = self._tool(lane, "read_page", {"url": u})
            read += 1
            if step.error:
                continue
            if step.flags:  # a page that talks to the assistant is not given to a model at all
                skipped += 1
                continue
            url = (re.search(r"^URL: (\S+)", text, re.M) or [None, u])[1]
            title = (re.search(r"^Title: ([^\n]+)", text, re.M) or [None, ""])[1].strip()
            body = text.split("\n\n", 1)[-1]
            ext = cc.evidence(body, head, None, EXTRACT_CHARS, need_figure=False)
            if len(ext) < 200:
                ext = "\n".join(p for p in body.split("\n") if len(p.strip()) > 60)[:EXTRACT_CHARS]
            if len(ext) < 200:
                continue
            n = len(pages) + 1
            pages.append({"n": n, "url": url, "title": title or _domain(url), "domain": _domain(url),
                          "text": body[:PAGE_TEXT], "extract": ext})  # fmt: skip
            domains.append(_domain(url))
            self._step(lane, "running", "research", detail=(f"{len(pages)} page(s) retenue(s)" if fr else
                       f"{len(pages)} page(s) kept"), domains=list(dict.fromkeys(domains))[:12],
                       progress=round(min(1.0, len(pages) / MAX_READ), 2))  # fmt: skip
        self.trace.update(read=read, kept=len(pages), suspicious=skipped)
        self._step(lane, "done", "research", seconds=round(time.monotonic() - self.t0, 1),
                   detail=(f"{read} page(s) lue(s), {len(pages)} retenue(s)" if fr else f"{read} page(s) read, "
                           f"{len(pages)} kept"), domains=list(dict.fromkeys(domains))[:12])  # fmt: skip
        if len(pages) < MIN_PAGES:
            raise _Fallback("no_facts")
        return pages

    def _own_pages(self) -> list[dict]:
        """The user's own text as the only sources (pasted text, attached documents): nothing is searched."""
        fr = self.lang == "fr"
        texts = [(n, t) for n, t in self.docs if t.strip()] or [("Votre texte" if fr else "Your text", self.pasted)]
        pages = []
        for name, text in texts[:4]:
            body = text[:PAGE_TEXT]
            pages.append({"n": len(pages) + 1, "url": "", "title": name[:90], "domain": "", "text": body,
                          "extract": body[:EXTRACT_CHARS * 2]})  # fmt: skip
        self.trace.update(read=len(pages), kept=len(pages), own=True)
        return pages

    # -------------------------------------------------------------- 3. extract
    def _extract(self, pages: list[dict], topic: str) -> tuple[list[dict], dict]:
        groups: list[list[dict]] = [[] for _ in range(EXTRACTORS)]
        if len(pages) == 1 and len(pages[0]["extract"]) > EXTRACT_CHARS:  # one long own text: cut in parts
            body = pages[0]["extract"]
            cut = [body[i : i + EXTRACT_CHARS] for i in range(0, len(body), EXTRACT_CHARS)][:EXTRACTORS]
            for i, part in enumerate(cut):
                groups[i].append({**pages[0], "extract": part})
        else:
            for i, p in enumerate(pages):
                groups[i % EXTRACTORS].append(p)
        by_n = {p["n"]: p for p in pages}
        jobs = [(f"lecteur_{i + 1}", g) for i, g in enumerate(groups) if g]
        for i in range(len(jobs), EXTRACTORS):
            self._step(f"lecteur_{i + 1}", "skipped", "brief", detail="—")

        def one(job):
            lane, group = job
            data, size = [], 0
            for p in group:
                block = f"[{p['n']}] {p['title']}" + (f" ({p['domain']})" if p["domain"] else "") + "\n" + p["extract"]
                if size + len(block) > GROUP_CHARS:
                    block = block[: max(0, GROUP_CHARS - size)]
                data.append(block)
                size += len(block)
            g = self._gen(lane, "brief", self._user("\n\n".join(data), PROMPTS[self.lang]["extract"].format(topic=topic)),
                          [RECORD_CLAIMS], 1400, temperature=0.0, until=self.t0 + 175)  # fmt: skip
            args = self._args(g, "record_claims") or {}
            raw = args.get("claims")
            if isinstance(raw, str):
                raw = cc.json_repair(raw)
            got, stats = check_claims(raw, {p["n"]: by_n[p["n"]] for p in group})
            if g:
                self._step(lane, "done", "brief", tokens=g["tokens"], seconds=g["seconds"],
                           detail=(f"{len(got)} affirmation(s) vérifiée(s) sur {stats['seen']}" if self.lang == "fr"
                                   else f"{len(got)} claim(s) checked of {stats['seen']}"))  # fmt: skip
            return got, stats

        claims, totals = [], {"seen": 0, "no_quote": 0, "figure": 0, "weak": 0}
        seen = set()
        for got, stats in self.pool.map(one, jobs):
            for k in totals:
                totals[k] += stats[k]
            for c in got:
                if cc.fold(c["claim"]) not in seen:
                    seen.add(cc.fold(c["claim"]))
                    claims.append(c)
        claims.sort(key=lambda c: c["n"])
        self.trace.update(claims=len(claims), claims_seen=totals["seen"])
        return claims[:MAX_CLAIMS], totals

    # -------------------------------------------------------------- 4. report, checked in code
    def _report_text(self, title: str, summary: str, sections: list[dict], pages: list[dict]) -> tuple[str, dict]:
        by_source = {p["n"]: p["text"] for p in pages}
        stats = {"removed": 0, "recited": 0, "weak": []}
        cite = re.compile(r"\[(\d{1,2})\]")

        def clean(text: str) -> str:
            keep = []
            for sent in re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split())):
                if not sent:
                    continue
                cited = [n for n in dict.fromkeys(int(x) for x in cite.findall(sent)) if n in by_source]
                if nums(sent) and not (cited and all(numbers_in(sent, by_source[n]) for n in cited[:1])):
                    # a number not in the cited page: the page that holds every number of the sentence, or nothing
                    holder = next((n for n in sorted(by_source) if numbers_in(sent, by_source[n])), None)
                    if holder is None:
                        stats["removed"] += 1
                        continue
                    sent = (cite.sub("", sent).rstrip(" .") + f" [{holder}].") if len(cited) <= 1 else sent
                    stats["recited"] += 1
                    cited = [holder]
                if cited and cc.support(sent, " ".join(by_source[n] for n in cited)) < 0.34:
                    stats["weak"].append({"sentence": sent[:160], "cited": cited})
                keep.append(sent)
            return " ".join(keep)

        parts = [f"## {title}", "", clean(summary)]
        for s in sections:
            body = clean(s["text"])
            if body:
                parts += ["", f"### {s['heading']}", "", body]
        return "\n".join(parts).strip(), stats

    def _code_report(self, topic: str, claims: list[dict], pages: list[dict]) -> tuple[str, str, list[dict]]:
        """The report written by code from the verified claims, when the writer failed: one section per source."""
        fr = self.lang == "fr"
        sections = []
        for p in pages:
            mine = [c for c in claims if c["n"] == p["n"]][:5]
            if mine:
                sections.append({"heading": p["title"][:80],
                                 "text": " ".join(f"{c['claim'].rstrip('.')} [{p['n']}]." for c in mine)})  # fmt: skip
        title = (f"Recherche : {topic}" if fr else f"Research: {topic}")[:120]
        summary = (f"{len(claims)} affirmations vérifiées dans {len({c['n'] for c in claims})} sources." if fr else
                   f"{len(claims)} claims checked in {len({c['n'] for c in claims})} sources.")  # fmt: skip
        return title, summary, sections

    def _write(self, topic, questions, claims, pages) -> tuple[str, dict, bool]:
        fr = self.lang == "fr"
        lines = [("Demande : " if fr else "Request: ") + self.instr, "",
                 "Sous-questions :" if fr else "Sub-questions:", *[f"- {q}" for q in questions], "",
                 "Affirmations vérifiées (numéro de la source entre crochets) :" if fr else
                 "Verified claims (source number in brackets):"]  # fmt: skip
        lines += [f"[{c['n']}] {c['claim']}" + (f" ({c['date']})" if c["date"] else "") for c in claims]
        lines += ["", "Sources :" if fr else "Sources:"] + [f"[{p['n']}] {p['title']}" + (f" — {p['domain']}" if p["domain"] else "")
                                                           for p in pages]  # fmt: skip
        g = self._gen("redacteur_a", "drafts", self._user("\n".join(lines), PROMPTS[self.lang]["report"]), [WRITE_REPORT],
                      1700, temperature=0.2, until=self.deadline - 15)  # fmt: skip
        args = self._args(g, "write_report") or {}
        sections = []
        raw = args.get("sections")
        if isinstance(raw, str):
            raw = cc.json_repair(raw)
        for s in raw if isinstance(raw, list) else []:
            if isinstance(s, dict) and str(s.get("heading") or "").strip() and len(str(s.get("text") or "")) >= 40:
                sections.append({"heading": " ".join(str(s["heading"]).split())[:90], "text": str(s["text"])[:2400]})
        written = bool(sections and str(args.get("summary") or "").strip())
        if written:
            title = " ".join(str(args.get("title") or topic).split())[:120]
            summary = str(args["summary"])[:1200]
        else:
            title, summary, sections = self._code_report(topic, claims, pages)
        if g:
            self._step("redacteur_a", "done" if written else "error", "drafts", tokens=g["tokens"], seconds=g["seconds"],
                       detail=(f"{len(sections)} section(s)" if written else ("rapport écrit par le code" if fr else
                               "report written by code")))  # fmt: skip
        text, stats = self._report_text(title, summary, sections, pages)
        if written and len(re.findall(r"^### ", text, re.M)) == 0:  # every section lost its sentences
            title, summary, sections = self._code_report(topic, claims, pages)
            text, stats = self._report_text(title, summary, sections, pages)
            written = False
        return text, stats, written

    # -------------------------------------------------------------- the whole run
    def _research_run(self) -> Run:
        fr = self.lang == "fr"
        topic = self._subject()
        own = bool(self.pasted or self.docs)
        if own:
            questions, queries = [], []
            pages = self._own_pages()
        else:
            questions, queries = self._research_plan(topic)
            pages = self._gather(queries, topic)
        claims, cstats = self._extract(pages, topic)
        if not claims:
            raise _Fallback("no_facts")
        self._step("verificateur", "running", "check")
        text, rstats, written = self._write(topic, questions, claims, pages)
        caveats = []
        dropped = cstats["seen"] - len(claims)
        if dropped:
            caveats.append(f"{dropped} affirmation(s) écartée(s) : citation absente de la page ou chiffre absent de la "
                           "citation" if fr else f"{dropped} claim(s) set aside: quote not in the page or figure not in "
                           "the quote")  # fmt: skip
        if rstats["removed"]:
            caveats.append(f"{rstats['removed']} phrase(s) du rapport retirée(s) : chiffre absent des sources" if fr else
                           f"{rstats['removed']} report sentence(s) removed: figure in no source")  # fmt: skip
        for w in rstats["weak"][:3]:
            caveats.append(f"à vérifier dans la source [{w['cited'][0]}] : « {w['sentence'][:110]} »" if fr else
                            f"to check in source [{w['cited'][0]}]: “{w['sentence'][:110]}”")  # fmt: skip
        self._step("verificateur", "done", "check",
                   detail=(f"{len(claims)} affirmation(s) vérifiée(s) · {rstats['recited']} citation(s) corrigée(s)"
                           if fr else f"{len(claims)} claim(s) checked · {rstats['recited']} citation(s) fixed"))  # fmt: skip
        counts = {"queries": len(queries), "read": self.trace.get("read", 0), "kept": len(pages), "claims": len(claims),
                  "dropped": dropped, "removed": rstats["removed"], "recited": rstats["recited"]}  # fmt: skip
        parts = [text]
        if caveats:
            parts += ["", "### À vérifier" if fr else "### To check", ""] + [f"- {c}" for c in caveats]
        team = [
            (f"{len(queries)} recherche(s), {counts['read']} page(s) lue(s), {len(pages)} source(s) retenue(s) sur "
             f"{len({p['domain'] for p in pages})} site(s)" if fr else f"{len(queries)} search(es), {counts['read']} "
             f"page(s) read, {len(pages)} source(s) kept from {len({p['domain'] for p in pages})} site(s)")
            if not own else ("vos documents comme seules sources, rien n'a été cherché sur le web" if fr else
                             "your documents as the only sources, nothing searched on the web"),
            (f"{cstats['seen']} affirmation(s) relevée(s), {len(claims)} vérifiée(s) mot pour mot dans leur source"
             if fr else f"{cstats['seen']} claim(s) found, {len(claims)} checked word for word in their source"),
            ("rapport rédigé par le modèle puis vérifié phrase par phrase" if written else
             "rapport écrit par le code à partir des affirmations vérifiées") if fr else
            ("report written by the model, then checked sentence by sentence" if written else
             "report written by code from the checked claims"),
        ]  # fmt: skip
        parts += ["", "### Ce que l'équipe a fait" if fr else "### What the team did", ""] + [f"- {t}" for t in team]
        answer = "\n".join(parts)
        run = Run(lang=self.lang, flagged=self.flagged, stop_reason="answer")
        web = [p for p in pages if p["url"]]
        run.sources = [p["url"] for p in web] if len(web) == len(pages) else []
        run.source_titles = {p["url"]: p["title"] for p in web}
        run.widgets = [research_card(topic, questions, pages, claims, counts, self.lang)]
        graph = build_graph(claims, self.lang)
        if graph:
            run.widgets.append(graph)
        tl = build_timeline(claims, self.lang)
        if tl:
            run.widgets.append(tl)
        run.answer = answer
        self._stream(answer)
        run.usage = list(self.usage)
        run.steps = [s for _, s in sorted(self.steps, key=lambda x: x[0])]
        run.images = list(self.images)
        run.messages = [{"role": "assistant", "content": answer}]
        run.report = self._report()
        self._emit(self._done_event(True, "redacteur_a", run.report, caveats))
        return run


def fallback_text(lang: str) -> str:
    return ABSTAIN["en" if lang == "en" else "fr"]["no_facts"]
