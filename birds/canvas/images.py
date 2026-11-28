"""Pictures of the canvas: ``::: image query="…"`` is resolved by the harness, never by a URL the model wrote.

Server mode: an Openverse search (``search_openverse``: CC0, public-domain mark, CC BY, CC BY-SA only, asked of the
API AND checked again on every result; the result must match the query's words), then Wikimedia Commons (bitmap
files only, licence read on Commons and checked as free: ``office_media.commons_licence``; NC/ND refused). The
credit line (author — licence — source) is kept with the picture, which is fetched through the egress guard and
re-encoded on the server. Results are cached in memory (``CACHE``) so « une autre image » and a second deck on the
same subject do not search again. Demo mode (no network): an abstract illustration drawn here,
labelled as such, never passed off as a photo.

The browser receives the picture as base64 (the app's CSP has no ``data:``; canvas.js turns it into a ``blob:``).
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import io
import re
import time
from contextlib import contextmanager
from urllib.parse import quote, urlsplit

from birds.harness import office_media as om

SHOW_BYTES = 240_000  # a canvas picture: sharp at 1280 px, light enough to travel in the event stream
SEARCH_LIMIT = 10
GEN_CREDIT = {
    "fr": "Illustration générée par Bird (mode démo : aucune image du web)",
    "en": "Illustration drawn by Bird (demo mode: no web picture)",
}


def to_entry(m: om.Media, query: str = "") -> dict:
    """What the browser keeps of one picture: the bytes (base64) and everything the credit needs."""
    return {"id": m.id, "kind": m.kind, "data": base64.b64encode(m.data).decode("ascii"), "fmt": m.fmt,
            "w": m.w, "h": m.h, "alt": m.alt[:160], "title": m.title[:120], "credit": m.credit[:300],
            "licence": m.licence[:120], "source": m.source[:300], "query": query[:120]}  # fmt: skip


OPENVERSE_API = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENCES = {"cc0": "CC0", "pdm": "Domaine public", "by": "CC BY", "by-sa": "CC BY-SA"}
CACHE_SIZE, CACHE_SECONDS = 96, 3600.0


class _Cache:
    """A small in-memory LRU of found pictures: (source, query, excluded) -> Media (or None: nothing found)."""

    def __init__(self, size: int = CACHE_SIZE, ttl: float = CACHE_SECONDS):
        import threading
        from collections import OrderedDict

        self.size, self.ttl, self.lock, self.d = size, ttl, threading.Lock(), OrderedDict()
        self.hits = self.misses = 0

    def get(self, key):
        with self.lock:
            hit = self.d.get(key)
            if hit is None or time.monotonic() - hit[0] > self.ttl:
                self.d.pop(key, None)
                self.misses += 1
                return False, None
            self.d.move_to_end(key)
            self.hits += 1
            return True, hit[1]

    def put(self, key, value) -> None:
        with self.lock:
            self.d[key] = (time.monotonic(), value)
            self.d.move_to_end(key)
            while len(self.d) > self.size:
                self.d.popitem(last=False)

    def clear(self) -> None:
        with self.lock:
            self.d.clear()
            self.hits = self.misses = 0


CACHE = _Cache()

_TRACE: contextvars.ContextVar = contextvars.ContextVar("bird_image_trace", default=None)


@contextmanager
def tracing():
    """Collect what each source answered during a search (``scripts/image_eval.py``, the diagnosis of a miss):
    ``[{"source", "q", "status", "results", "why": {reason: count}}]``. Costs nothing when nobody listens."""
    log: list[dict] = []
    token = _TRACE.set(log)
    try:
        yield log
    finally:
        _TRACE.reset(token)


def _trace(source: str, q: str, status: str, results: int | None = None, why: dict | None = None, **extra) -> None:
    log = _TRACE.get()
    if log is not None:
        log.append({"source": source, "q": q, "status": status, **({"results": results} if results is not None
                    else {}), **({"why": dict(why)} if why else {}), **extra})  # fmt: skip


def public_trace(log: list[dict]) -> list[dict]:
    """The trace a response may carry: which source answered what, never a URL or a key."""
    keep = ("source", "q", "status", "results", "why", "ms")
    return [{k: ev[k] for k in keep if k in ev} for ev in log[:16]]


def error_status(e: Exception) -> str:
    """« 429 », « 403 », « timeout », « blocked »… of a failed request, for the trace and the cool-down."""
    text = str(e)
    m = re.search(r"HTTP (\d{3})", text)
    if m:
        return m.group(1)
    if "too slow" in text or "timeout" in type(e).__name__.lower() or "timed out" in text.lower():
        return "timeout"
    if getattr(e, "code", None):  # guard.FetchError: upstream / image_type / too_large, and why
        return f"{e.code}:{re.sub(r'[^A-Za-z0-9 _/.-]', '', text)[:40]}"
    return f"{type(e).__name__.lower()[:24]}:{re.sub(r'[^A-Za-z0-9 _/.-]', '', text)[:40]}"


# a miss worth remembering is a search that ANSWERED and whose pictures were refused for what they are (licence,
# subject, size), never one cut short by the network (a refused image fetch, a rate limit, the deadline, the look
# cap): remembering those for an hour turned one bad minute into an hour without pictures
TRANSIENT = ("deadline", "fetch_", "judge_cap")


def _lasting(why: dict) -> bool:
    return not any(k.startswith(TRANSIENT) for k in why)


def _renamed(m: om.Media | None, mid: str) -> om.Media | None:
    if m is None:
        return None
    import copy

    out = copy.copy(m)
    out.id = mid
    return out


_TITLE_NOISE = re.compile(
    r"\s+-\s+Flickr\s+-\s+.*$|\s*-\s*geograph\.org\.uk\s*-\s*\d+|\s*-\s*panoramio(?:\s*\(\d+\))?|\(\d{5,}\)|"
    r"\b(?:DSC|IMG|DSCF|P\d{3})[_-]?\d+\b",
    re.I,
)


def clean_title(title: str) -> str:
    """A file title without what is not about the picture: « … - Flickr - Avel-Breizh » (the uploader), a
    geograph / panoramio number, a camera file name. « Breizh » in an uploader's name is not Brittany."""
    return _TITLE_NOISE.sub(" ", str(title or "")).strip()


def relevant(query: str, title: str, tags: list[str] | None = None) -> bool:
    """Does a result speak of the query? One of the query's words (a word or its first 5 letters: « tramways » ~
    « tramway ») is in the title, or in the tags for a query of one or two words; a query of three words or more
    needs two of them in the title itself (Flickr tags are loose: « Venice, canalside view » and « Rialto Bridge at
    night » were tagged « night train europe »). A picture that matches nothing is not shown: no image rather than
    a wrong one."""
    want = om.words(query)
    if not want:
        return False

    def hits(text: str) -> int:
        have = om.words(text)
        stems = {w[:5] for w in have}
        return sum(1 for w in want if w in have or w[:5] in stems)

    head = clean_title(title)
    in_title = hits(head)
    # tags count for a query of one or two words only, and with one of its words in the title
    total = hits(head + " " + " ".join(tags or [])) if len(want) <= 2 else in_title
    if tags is not None and in_title == 0:
        return False
    # one word of a short query; two of a longer one (« night train europe luxury » is not « Praha Hilton »)
    return total >= (1 if len(want) <= 2 else 2)


def openverse_licence(r: dict) -> str | None:
    """'CC BY-SA 4.0' for a result whose licence allows reuse with a credit, else None (NC, ND, unknown)."""
    lic = str(r.get("license") or "").lower()
    if lic not in OPENVERSE_LICENCES:
        return None
    ver = str(r.get("license_version") or "").strip()
    name = OPENVERSE_LICENCES[lic]
    return f"{name} {ver}".strip() if lic != "pdm" and re.fullmatch(r"\d(?:\.\d)?", ver or "x") else name


def _openverse_urls(r: dict) -> list[str]:
    """The copies of one Openverse result to try, best first: the original (or a 1280 px Commons thumbnail), then
    Openverse's own full-size copy (``/thumb/?full_size=true``, served by api.openverse.org). Measured in production
    on 28/11/2026: the original hosts (Flickr mostly) refused the hosting provider's addresses for 10 results out of
    10 on « Paris skyline », while the API answered: its copy is the same picture, same licence."""
    out = []
    big = _big_url(r)
    if big.startswith("https://"):
        out.append(big)
    thumb = str(r.get("thumbnail") or "")
    if re.fullmatch(r"https://api\.openverse\.org/v1/images/[0-9a-f-]{36}/thumb/", thumb):
        out.append(thumb + "?full_size=true")
    return list(dict.fromkeys(out))


def _big_url(r: dict) -> str:
    """The picture to fetch: a 1280 px Commons thumbnail for a Commons file, the original when small enough, else
    Openverse's own thumbnail."""
    url = str(r.get("url") or "")
    name = om.commons_file(url)
    if name and "/thumb/" not in url:
        m = re.match(r"^(https://upload\.wikimedia\.org/wikipedia/commons)/([0-9a-f]/[0-9a-f]{2})/([^/]+)$", url)
        if m and (r.get("width") or 0) > 1280:
            return f"{m.group(1)}/thumb/{m.group(2)}/{m.group(3)}/1280px-{m.group(3)}"
    if url.startswith("https://") and (r.get("filesize") or 0) <= 3_500_000:
        return url
    return str(r.get("thumbnail") or "")


# words that describe no picture a search can find (the 4B writes « happy cyclist delivering food »)
FLUFF = set("""happy busy beautiful modern smiling typical nice great amazing successful professional concept
conceptual illustration photo photograph picture image stock background abstract various several different
diverse innovative dynamic vibrant inspiring future futuristic""".split())


_PLACEHOLDER_WORDS = re.compile(
    r"^\s*(?:une?\s+|des\s+|la\s+|le\s+|les\s+|a\s+|an\s+|the\s+)?(?:photos?|images?|illustrations?|pictures?|"
    r"visuels?|pictogrammes?)\s*(?:de|d['’]|du|des|of|:|-)?\s*",
    re.I,
)


def clean_query(query: str) -> str:
    """What a search engine can use: « [Paris bike cargo 1] » -> « Paris bike cargo », « Photo : chaton heureux » ->
    « chaton heureux ». Brackets, numbering, quotes and a leading « photo de / image of » are the model's notation,
    never words of the picture."""
    q = re.sub(r"[\[\]{}()«»\"“”<>]", " ", str(query or ""))
    q = _PLACEHOLDER_WORDS.sub("", q)
    q = re.sub(r"(?<![\w-])(?:n°\s*)?\d{1,2}(?![\w-])", " ", q)  # « 1 », « n° 2 » (years such as 2024 stay)
    return re.sub(r"\s+", " ", q).strip(" .,:;-_")[:120]


def short_query(query: str) -> str:
    """« cyclistes et piétons dans une rue urbaine » -> « cyclistes piétons »: the two first content words, for a
    second search when the long phrase finds nothing."""
    out = [w for w in re.findall(r"[\wÀ-ÿ'-]{3,}", str(query or "")) if om.words(w) and w.lower() not in FLUFF]
    return " ".join(out[:2])


# a photo « of a chart » is never the answer: the slide wants a real chart (from figures), not a picture of one
_NO_PHOTO = re.compile(r"\b(?:charts?|graphs?|diagrams?|infographics?|graphiques?|diagrammes?|courbes?|"
                       r"statisti\w*|spreadsheets?|tableaux?)\b", re.I)


# French words that describe no picture a search can find (« chaton heureux »: Commons has « chaton », never
# « chaton heureux »)
FLUFF_FR = set("""heureux heureuse heureuses souriant souriante souriants moderne modernes beau belle beaux belles
typique typiques divers diverses différents différentes innovant innovante dynamique concept photo image illustration
""".split())


def head_noun(query: str) -> str:
    """« électricien au travail » -> « électricien », « chaton heureux » -> « chaton »: the first content word of a
    French phrase (its head noun), for a last search. Not used for English, whose head comes last."""
    for w in re.findall(r"[\wÀ-ÿ'-]{4,}", str(query or "")):
        if om.words(w) and w.lower() not in FLUFF and w.lower() not in FLUFF_FR:
            return w
    return ""


def variants(query: str, lang: str = "", also: list[str] | tuple[str, ...] = ()) -> list[str]:
    """The searches tried for one query, most precise first: as written, without the words that describe no
    picture (« happy », « modern », « heureux »), then its two first content words; then ``also`` (the same subject
    in English when the model gave it: Openverse is mostly English) the same way; last, for French, the head noun
    alone. None for a query of a chart or a table (« chart showing quarterly growth »: seen live, it found a
    pulsar's radio plot)."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not q or _NO_PHOTO.search(q):
        return []
    out: list[str] = []
    for one in (q, *[re.sub(r"\s+", " ", str(a or "")).strip()[:120] for a in also]):
        if not one or _NO_PHOTO.search(one):
            continue
        plain = " ".join(w for w in one.split() if w.lower().strip(",.;:") not in FLUFF | FLUFF_FR)
        for v in (one, plain, short_query(one)):
            if v and v.lower() not in {x.lower() for x in out}:
                out.append(v)
    if lang == "fr":
        v = head_noun(q)
        if v and v.lower() not in {x.lower() for x in out}:
            out.append(v)
    return out


class _Cool:
    """When a source last answered 429 (rate limit). Not used to skip it: the refusals come in short, scattered
    windows (measured: skipping a source for 20 to 120 s lost pictures the next call would have got); it tells
    the canvas to say « réessayez » rather than « aucune image »."""

    def __init__(self):
        self.until: dict[str, float] = {}

    def hot(self, source: str) -> bool:
        return time.monotonic() < self.until.get(source, 0.0)

    def refuse(self, source: str, seconds: float = 20.0) -> None:
        self.until[source] = time.monotonic() + seconds


COOL = _Cool()


JUDGED = 6  # pictures shown to the model per search at most (0.2 to 0.4 s each, measured)


def _looks(judge, want: str, m: om.Media, tries: list[int]) -> bool:
    """The model's look at a candidate (``judge(query, media)`` -> True / False / None): False rejects it; None (no
    answer, an error) keeps it. After ``JUDGED`` looks the search stops: no picture rather than a wrong one."""
    if judge is None:
        return True
    tries[0] += 1
    try:
        return judge(want, m) is not False
    except Exception:  # noqa: BLE001 - the look is a filter, never a failure
        return True


def search_openverse(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                     deadline: float | None = None, judge=None, want: str = "") -> om.Media | None:  # fmt: skip
    """The first relevant, free-licence Openverse picture for ``query`` (the model's notation cleaned first)."""
    query = clean_query(query) or query
    return _search_openverse(query, fetch, exclude, mid, deadline, judge, want)


def _search_openverse(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                      deadline: float | None = None, judge=None, want: str = "") -> om.Media | None:  # fmt: skip
    q = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not q or fetch is None:
        return None
    want = want or q
    tries = [0]
    key = ("openverse", q.lower(), tuple(sorted(exclude or [])), want.lower() if judge else None)
    hit, m = CACHE.get(key)
    if hit:
        _trace("openverse", q, "cache_hit" if m else "cache_miss")
        return _renamed(m, mid)
    url = (f"{OPENVERSE_API}?q={quote(q)}&license={','.join(OPENVERSE_LICENCES)}&page_size={SEARCH_LIMIT}"
           "&mature=false")  # fmt: skip
    try:
        results = fetch.json(url).get("results") or []
    except Exception as e:  # noqa: BLE001 - no picture rather than a failed turn
        status = error_status(e)
        if status == "429":
            COOL.refuse("openverse")
        _trace("openverse", q, status)
        return None  # not cached: the next try may get an answer
    skip = set(exclude or [])
    found = None
    why: dict[str, int] = {}

    def no(reason: str) -> None:
        why[reason] = why.get(reason, 0) + 1

    for r in results:
        if deadline is not None and time.monotonic() > deadline:
            no("deadline")
            break
        if not isinstance(r, dict) or r.get("mature") or r.get("unstable__sensitivity"):
            no("sensitive")
            continue
        lic = openverse_licence(r)
        title = str(r.get("title") or "")
        tags = [str(t.get("name") or "") for t in r.get("tags") or [] if isinstance(t, dict)]
        source = str(r.get("foreign_landing_url") or r.get("url") or "")
        if not lic or source in skip or str(r.get("url") or "") in skip:
            no("licence" if not lic else "excluded")
            continue
        if str(r.get("filetype") or "").lower() in ("svg", "gif", "tif", "tiff", "pdf"):
            no("filetype")
            continue
        if not relevant(q, title, tags):
            no("relevance")
            continue
        creator = re.sub(r"\s+", " ", str(r.get("creator") or "")).strip()[:100]
        if not creator and not lic.startswith(("CC0", "Domaine")):
            no("no_author")
            continue  # a CC BY licence needs its author
        m, errs = None, []
        for big in _openverse_urls(r):
            try:
                m = om.prepare(fetch.image(big), mid, "web", max_bytes=SHOW_BYTES, alt=q, title=title[:120],
                               licence=lic, source=source[:300])  # fmt: skip
                m.src = big
                break
            except Exception as e:  # noqa: BLE001 - this copy fails, the next one may not
                errs.append(f"{error_status(e)}@{urlsplit(big).hostname or '?'}")
        if m is None:
            no("fetch_" + ("+".join(errs) or "no_url"))
            continue
        if m.w < 400 or m.h < 260:
            no("small")
            continue
        if tries[0] >= JUDGED:
            no("judge_cap")
            break
        if not _looks(judge, want, m, tries):
            no("judge")
            continue
        provider = str(r.get("provider") or r.get("source") or "").replace("_", " ").title()[:40]
        m.credit = f"{creator or 'Domaine public'} — {lic} — {provider + ' via ' if provider else ''}Openverse"
        found = m
        break
    _trace("openverse", q, "found" if found else "none", len(results), why)
    if found is not None or _lasting(why):
        CACHE.put(key, found)
    return _renamed(found, mid)


def search_commons(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                   deadline: float | None = None, judge=None, want: str = "") -> om.Media | None:  # fmt: skip
    """The first free-licence Commons photograph for ``query`` (files in ``exclude``, by source URL, skipped)."""
    q = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not q or fetch is None:
        return None
    want = want or q
    tries = [0]
    key = ("commons", q.lower(), tuple(sorted(exclude or [])), want.lower() if judge else None)
    hit, cached = CACHE.get(key)
    if hit:
        _trace("commons", q, "cache_hit" if cached else "cache_miss")
        return _renamed(cached, mid)
    url = (f"{om.COMMONS_API}?action=query&format=json&formatversion=2&generator=search&gsrnamespace=6"
           f"&gsrlimit={SEARCH_LIMIT}&gsrsearch={quote(q + ' filetype:bitmap')}&prop=imageinfo"
           f"&iiprop=url|extmetadata|size|mime&iiurlwidth=1280")  # fmt: skip
    try:
        pages = (fetch.json(url).get("query") or {}).get("pages") or []
    except Exception as e:  # noqa: BLE001 - no picture rather than a failed turn
        status = error_status(e)
        if status == "429":
            COOL.refuse("commons")
        _trace("commons", q, status)
        return None
    pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index", 99))
    skip = set(exclude or [])
    why: dict[str, int] = {}

    def no(reason: str) -> None:
        why[reason] = why.get(reason, 0) + 1

    for p in pages:
        if deadline is not None and time.monotonic() > deadline:
            no("deadline")
            break
        title = str(p.get("title") or "")
        if re.search(r"\.(svg|tiff?|pdf|djvu|gif)$", title, re.I):
            no("filetype")
            continue
        if not relevant(q, re.sub(r"^File:|\.[a-z]{3,4}$", "", title).replace("_", " ")):
            no("relevance")
            continue  # Commons full-text search also matches descriptions: « équipe en réunion » gave a calendar
        info = (p.get("imageinfo") or [{}])[0]
        lic = om.commons_licence(info)
        if not lic or not str(lic.get("thumb") or "").startswith("https://upload.wikimedia.org/"):
            no("licence")
            continue
        if lic.get("url") in skip or title in skip:
            no("excluded")
            continue
        try:
            raw = fetch.image(lic["thumb"])
            name = re.sub(r"^File:", "", title)
            label = re.sub(r"\.[a-z]{3,4}$", "", name, flags=re.I).replace("_", " ")[:120]
            m = om.prepare(raw, mid, "web", max_bytes=SHOW_BYTES, alt=q, title=label, licence=lic["licence"],
                           source=lic["url"] or f"https://commons.wikimedia.org/wiki/{quote(title)}")  # fmt: skip
        except Exception as e:  # noqa: BLE001 - this file fails, the next one may not
            no("fetch_" + error_status(e))
            continue
        m.credit = f"{lic['author']} — {lic['licence']} — Wikimedia Commons"
        m.src = lic["thumb"]
        if m.w < 400 or m.h < 260:
            no("small")
            continue
        if tries[0] >= JUDGED:
            no("judge_cap")
            break
        if not _looks(judge, want, m, tries):
            no("judge")
            continue
        _trace("commons", q, "found", len(pages), why)
        CACHE.put(key, m)
        return _renamed(m, mid)
    _trace("commons", q, "none", len(pages), why)
    if _lasting(why):
        CACHE.put(key, None)
    return None


def search_web(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
               deadline: float | None = None, judge=None, lang: str = "", also: tuple[str, ...] = ()
               ) -> om.Media | None:  # fmt: skip
    """For each variant of the cleaned query (``variants``: as written, plainer, shorter, then ``also`` — the model's
    English words for the same subject — and, for French, the head noun alone): Openverse (wide: Flickr, museums,
    Commons), then Wikimedia Commons directly (its descriptions are multilingual: the French words find French
    files); the source that refused us (429) in the last seconds is asked second. Then Pexels when the deployment
    has a key (BIRD_PEXELS_API_KEY): a keyed quota, never shared with the hosting provider's other tenants. The first
    relevant picture wins. ``judge`` (``vision_judge``): the model looks at each candidate and says whether it shows
    the query as asked — the words of a title are only a first sieve (« Night train at Høje Taastrup Station » was a
    politician on a stage)."""
    query = clean_query(query) or str(query or "")
    tried = variants(query, lang, tuple(clean_query(a) for a in also if a))
    for q in tried:
        if deadline is not None and time.monotonic() > deadline:
            break
        order = (search_openverse, search_commons)
        if COOL.hot("openverse") and not COOL.hot("commons"):
            order = (search_commons, search_openverse)
        # judged against the words searched: the shorter variants keep the core of the query (« night train »)
        for source in order:
            m = source(q, fetch, exclude, mid, deadline, judge, q)
            if m is not None:
                return m
    if not tried:
        return None  # a chart or a table: no photograph stands for it
    m = search_pexels(next((a for a in also if a), query), fetch, exclude, mid, deadline)
    if m is not None and not _looks(judge, query, m, [0]):
        return None
    return m


PEXELS_API = "https://api.pexels.com/v1/search"


def search_pexels(query: str, fetch, exclude: list[str] | None = None, mid: str = "w1",
                  deadline: float | None = None) -> om.Media | None:  # fmt: skip
    """A Pexels photograph (Pexels licence: free to use, credit shown), only with a key set by the operator."""
    import os

    key = os.environ.get("BIRD_PEXELS_API_KEY", "").strip()
    q = clean_query(query)
    if not key or not q or fetch is None:
        _trace("pexels", q, "no_key" if not key else "skipped")
        return None
    ck = ("pexels", q.lower(), tuple(sorted(exclude or [])))
    hit, cached = CACHE.get(ck)
    if hit:
        return _renamed(cached, mid)
    try:
        photos = fetch.json(f"{PEXELS_API}?query={quote(q)}&per_page={SEARCH_LIMIT}&orientation=landscape",
                            headers={"Authorization": key}).get("photos") or []  # fmt: skip
    except Exception as e:  # noqa: BLE001 - no picture rather than a failed turn
        _trace("pexels", q, error_status(e))
        return None
    skip = set(exclude or [])
    found = None
    for p in photos:
        if deadline is not None and time.monotonic() > deadline:
            break
        if not isinstance(p, dict):
            continue
        page = str(p.get("url") or "")
        src = str((p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("large") or "")
        alt = str(p.get("alt") or "")
        if not page or page in skip or not src.startswith("https://images.pexels.com/"):
            continue
        if alt and not relevant(q, alt):
            continue
        try:
            m = om.prepare(fetch.image(src), mid, "web", max_bytes=SHOW_BYTES, alt=q, title=(alt or q)[:120],
                           licence="Licence Pexels", source=page[:300])  # fmt: skip
        except Exception:  # noqa: BLE001 - this file fails, the next one may not
            continue
        if m.w < 400 or m.h < 260:
            continue
        m.credit = f"{str(p.get('photographer') or 'Pexels')[:80]} — Licence Pexels — Pexels"
        m.src = src
        found = m
        break
    _trace("pexels", q, "found" if found else "none", len(photos))
    CACHE.put(ck, found)
    return _renamed(found, mid)


_PALETTES = {
    "corporate": ((11, 27, 63), (30, 91, 216), (127, 164, 238), (226, 233, 248)),
    "modern": ((17, 24, 39), (13, 148, 136), (99, 102, 241), (204, 251, 241)),
    "forest": ((16, 42, 30), (46, 125, 82), (143, 196, 132), (221, 238, 214)),
    "night": ((10, 14, 26), (91, 141, 239), (167, 139, 250), (40, 48, 72)),
    "warm": ((59, 31, 20), (194, 65, 12), (232, 162, 107), (253, 231, 215)),
}


def generated(query: str, mid: str = "g1", theme: str | None = None, lang: str = "fr") -> om.Media:
    """An abstract, theme-coloured illustration for ``query`` (demo mode): soft shapes, no text, deterministic."""
    from PIL import Image, ImageDraw, ImageFilter

    seed = int(hashlib.sha256(str(query).encode("utf-8")).hexdigest()[:12], 16)
    pal = _PALETTES.get(theme or "corporate", _PALETTES["corporate"])
    w, h = 1280, 800
    small = Image.new("RGB", (16, 10))
    a, b = pal[0], pal[1]
    for y in range(10):  # a diagonal gradient, drawn small then smoothed up
        for x in range(16):
            t = min(1.0, max(0.0, (x / 15) * 0.6 + (y / 9) * 0.4))
            small.putpixel((x, y), tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3)))
    im = small.resize((w, h), Image.BICUBIC)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rnd = seed
    for k in range(7):
        rnd = (rnd * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        cx, cy = (rnd >> 8) % w, (rnd >> 24) % h
        r = 90 + (rnd >> 40) % 260
        col = pal[2] if k % 2 else pal[3]
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*col, 70 + (rnd >> 50) % 70))
    layer = layer.filter(ImageFilter.GaussianBlur(28))
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    m = om.prepare(buf.getvalue(), mid, "user", max_bytes=SHOW_BYTES, alt=str(query)[:160], title=str(query)[:120])
    m.kind = "gen"
    m.credit = GEN_CREDIT["en" if lang == "en" else "fr"]
    return m


def next_media_id(doc: dict, prefix: str = "w") -> str:
    used = set((doc.get("media") or {}).keys())
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def resolve(doc: dict, find, limit: int = 4, deadline: float | None = None, workers: int = 3) -> list[dict]:
    """Give a picture to the image parts that have none (at most ``limit`` searches, ``workers`` at a time: eight
    searches one after the other did not fit in the turn's 20 s). ``find(query, exclude, mid)`` returns a Media or
    None. Returns the browser entries of the pictures found; ``doc['media']`` gets their metadata and each part its
    ``media`` id. A part with no picture found keeps its query (the canvas shows a placeholder with « Chercher une
    image »), nothing is made up."""
    from concurrent.futures import ThreadPoolExecutor, wait

    cover = doc.get("cover") if doc.get("kind") == "deck" else None
    targets = [cover] if isinstance(cover, dict) and not cover.get("off") else []
    for b in doc.get("blocks") or []:
        targets += [p for p in b.get("parts") or [] if p.get("t") == "image"]
    jobs: list[tuple[str, list[str], str, list[dict]]] = []  # query, exclude, media id, the parts it serves
    by_query: dict[str, tuple] = {}
    used = set((doc.get("media") or {}).keys())
    for p in targets:
        if p.get("media") or p.get("missing"):  # « missing »: already searched this turn, the placeholder stays
            continue
        q = str(p.get("query") or "").strip()
        if not q:
            continue
        if q.lower() in by_query and not p.get("exclude"):
            by_query[q.lower()][3].append(p)
            continue
        if len(jobs) >= limit or (deadline is not None and time.monotonic() > deadline):
            p["pending"] = True
            continue
        exclude = []
        for mid in p.get("exclude") or []:
            src = ((doc.get("media") or {}).get(mid) or {}).get("source")
            exclude.append(src or mid)  # a drawn illustration has no source: its id is enough
        n = 1
        while f"w{n}" in used:
            n += 1
        used.add(f"w{n}")
        job = (q, exclude, f"w{n}", [p])
        jobs.append(job)
        if not p.get("exclude"):
            by_query[q.lower()] = job
    if not jobs:
        return []

    def run(job):
        try:
            return find(job[0], job[1], job[2])
        except Exception:  # noqa: BLE001 - one search failing leaves its placeholder
            return None

    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(jobs))))
    futures = [pool.submit(run, j) for j in jobs]
    left = None if deadline is None else max(0.0, deadline - time.monotonic()) + 2.0
    wait(futures, timeout=left)
    pool.shutdown(wait=False, cancel_futures=True)
    found = []
    for job, fut in zip(jobs, futures, strict=True):
        m = fut.result() if fut.done() and not fut.cancelled() else None
        for p in job[3]:
            p.pop("exclude", None)
            p.pop("pending", None)
            if m is None:
                p["missing"] = True
                continue
            p["media"] = m.id
            p.pop("missing", None)
        if m is None:
            continue
        entry = to_entry(m, job[0])
        doc.setdefault("media", {})[m.id] = {k: entry[k] for k in ("kind", "alt", "credit", "licence", "source",
                                                                    "w", "h", "query", "title")}  # fmt: skip
        found.append(entry)
    return found


LOOK = ("Does this photo show « {q} », well enough to illustrate a slide about it? Answer only yes or no.")


def vision_judge(llm, deadline: float | None = None):
    """``judge(query, media)`` for the searches: the model sees the candidate (small, 448 px) and answers yes or no
    (temperature of the endpoint, no reasoning, 3 tokens). None when the model cannot read images."""
    if llm is None or not hasattr(llm, "chat"):
        return None

    def judge(query: str, m: om.Media) -> bool | None:
        from PIL import Image

        im = Image.open(io.BytesIO(m.data)).convert("RGB")
        im.thumbnail((448, 448))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        msg = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                            {"type": "text", "text": LOOK.format(q=str(query)[:120])}]}]  # fmt: skip
        out = llm.chat(msg, 3, deadline=deadline)
        word = re.sub(r"[^a-z]", "", str(out.get("text") or "").strip().lower())[:4]
        return True if word.startswith(("yes", "oui")) else False if word.startswith(("no", "non")) else None

    return judge


def finder(mode: str, fetch=None, theme: str | None = None, lang: str = "fr", judge=None,
           deadline: float | None = None):  # fmt: skip
    """The ``find`` function for ``resolve``: Openverse and Commons (looked at by the model when ``judge``) in
    server mode, the drawn illustration in demo mode."""
    if mode == "demo":
        return lambda q, exclude, mid: generated(q + "|" + "|".join(exclude), mid.replace("w", "g", 1), theme, lang)
    return lambda q, exclude, mid: search_web(q, fetch, exclude, mid, deadline, judge)
