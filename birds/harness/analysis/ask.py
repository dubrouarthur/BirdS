"""From a question about a table to a query (``query.py``), with fixed templates: no model is involved.

« quel est le CA moyen par mois ? »      -> mean of CA, period month
« top 5 des produits »                   -> sum of the main measure by Produit, top 5
« compare 2024 et 2025 »                 -> compare the main measure, years 2024 and 2025
« répartition des ventes par région »    -> sum by Région, with shares
« combien de clients ? »                 -> distinct count of Client
« corrélation entre prix et volume »     -> Pearson r of Prix and Volume

A question that asks for no computation (« résume ce fichier ») gives None: the model answers it as before.
"""

from __future__ import annotations

import re

from birds.harness.analysis.cells import plain
from birds.harness.analysis.profile import Column, Frame

_STOP = {"de", "du", "des", "la", "le", "les", "l", "d", "un", "une", "en", "et", "par", "pour", "a", "au", "aux",
         "the", "of", "by", "per", "in", "and", "total", "nombre", "nb", "montant", "ht", "ttc", "k", "m", "eur",
         "moyen", "moyenne", "quel", "quelle", "est", "sur", "dans", "avec"}  # fmt: skip
SYNONYMS = [
    {
        "ca",
        "chiffre",
        "affaires",
        "ventes",
        "vente",
        "revenue",
        "revenues",
        "sales",
        "turnover",
        "recette",
        "recettes",
        "facture",
        "factures",
        "facturation",
        "encaissement",
        "encaissements",
    },
    {
        "produit",
        "produits",
        "article",
        "articles",
        "item",
        "items",
        "product",
        "products",
        "sku",
        "reference",
        "references",
        "gamme",
        "offre",
        "offres",
    },
    {"client", "clients", "customer", "customers", "compte", "comptes", "acheteur", "acheteurs"},
    {
        "region",
        "regions",
        "zone",
        "zones",
        "secteur",
        "secteurs",
        "area",
        "territoire",
        "territoires",
        "agence",
        "agences",
    },
    {"prix", "price", "prices", "tarif", "tarifs", "pu", "unitaire"},
    {
        "quantite",
        "quantites",
        "qte",
        "volume",
        "volumes",
        "unites",
        "units",
        "qty",
        "quantity",
        "pieces",
        "vendu",
        "vendus",
        "vendues",
        "sold",
    },
    {"marge", "marges", "margin", "profit", "benefice", "benefices", "resultat"},
    {"vendeur", "vendeurs", "commercial", "commerciaux", "seller", "sellers", "rep", "reps", "salesperson"},
    {"pays", "country", "countries"},
    {"ville", "villes", "city", "cities", "commune", "communes"},
    {"categorie", "categories", "category", "famille", "familles", "type", "types", "segment", "segments"},
    {"cout", "couts", "cost", "costs", "depense", "depenses", "charge", "charges", "spend", "budget"},
    {"canal", "canaux", "channel", "channels", "source", "sources"},
    {"employe", "employes", "salarie", "salaries", "employee", "employees", "collaborateur", "collaborateurs"},
    {"salaire", "salaires", "salary", "remuneration"},
    {"note", "notes", "score", "scores", "satisfaction", "nps"},
    {"commande", "commandes", "order", "orders"},
]
_MAIN_MEASURE = re.compile(r"\b(?:ca|chiffre|ventes?|montant|revenue|sales|total|turnover|recettes?|amount)\b")
_ASK = re.compile(
    r"\b(?:moyen(?:ne)?s?|average|mean|avg|m[ée]dian\w*|totale?s?|somme|cumul\w*|sum|combien|how\s+(?:many|much)|"
    r"nombre|count|max\w*|min\w*|top|flop|meilleur\w*|pires?|best|worst|plus\s+(?:gros|grand|[ée]lev[ée]|vendu|"
    r"rentable|fort|faible|petit)\w*|moins\s+\w+|highest|lowest|largest|biggest|compar\w*|vs|versus|[ée]volution|"
    r"tendance|trend|over\s+time|par\s+(?:mois|an|ann[ée]e|trimestre|semaine|jour)|mensuel\w*|monthly|annuel\w*|"
    r"yearly|trimestriel\w*|quarterly|hebdo\w*|weekly|r[ée]partition|breakdown|part\s+de|parts|proportion|"
    r"pourcentage|share|corr[ée]lation|correlation|lien\s+entre|relation\s+entre|distribution|dispersion|"
    r"classement|ranking|rank|group\w*|regroup\w*|par\s+\w+|by\s+\w+|per\s+\w+|for\s+each|pour\s+chaque|"
    r"selon|calcul\w*|calculate|compute|quel(?:le)?s?\s+(?:est|sont)\s+(?:le|la|les)\s+\w+|which|quels?)\b",
    re.I,
)
_NOT_ASK = re.compile(
    r"\b(?:r[ée]sum\w*|summari[sz]\w*|traduis\w*|translate|r[ée]dige\w*|[ée]cris|write|corrige\w*|explique\w*|"
    r"reformule\w*|mail|e-mail|lettre)\b",
    re.I,
)
_TOP = re.compile(
    r"\btop\s*(\d{1,2}|ten|dix|cinq|five|three|trois)\b|\b(?:les\s+)?(\d{1,2}|trois|cinq|dix)\s+(?:meilleur\w*|"
    r"premi\w*|plus\s+\w+|principa\w*|pires?|derni\w*|best|top|biggest|largest|first|worst)|"
    r"\b(?:the\s+)?(\d{1,2})\s+(?:best|top|largest|biggest|highest|lowest|worst)\b|"
    r"\b(?:les|the|ses|nos|mes)\s+(\d{1,2})\s+(?!(?:derniers?\s+)?(?:mois|ans?|ann[ée]es|jours|semaines|months|years|days|weeks)\b)[a-zà-ÿ]",
    re.I,
)
_WORD_N = {"ten": 10, "dix": 10, "cinq": 5, "five": 5, "three": 3, "trois": 3}
_ASC = re.compile(r"\b(?:flop|pires?|worst|moins\s+(?:vendu|rentable|cher|bon)\w*|lowest|plus\s+(?:faible|bas|petit)\w*|"
                  r"derniers?)\b", re.I)  # fmt: skip
_MEAN = re.compile(r"\b(?:moyen(?:ne)?s?|average|mean|avg|en\s+moyenne)\b", re.I)
_MEDIAN = re.compile(r"\bm[ée]dian\w*\b", re.I)
_MAX = re.compile(r"\b(?:max(?:imum|imal\w*)?|record|highest|plus\s+(?:haut|[ée]lev[ée])\w*)\b", re.I)
_MIN = re.compile(r"\b(?:min(?:imum|imal\w*)?|lowest|plus\s+(?:bas|faible)\w*)\b", re.I)
_COUNT = re.compile(r"\b(?:combien\s+(?:de|d['’])|how\s+many|nombre\s+(?:de|d['’])|count\s+of|number\s+of)\s*(\w+)?",
                    re.I)  # fmt: skip
_SHARE = re.compile(r"\b(?:r[ée]partition|breakdown|parts?\s+(?:de|du|des|par)|proportion|pourcentage|share|"
                    r"camembert|donut|pie)\b", re.I)  # fmt: skip
_CORR = re.compile(r"\b(?:corr[ée]l\w*|correlat\w*|lien\s+entre|relation\s+entre|relationship\s+between|"
                   r"(?:x|scatter|nuage))\b", re.I)  # fmt: skip
_DIST = re.compile(r"\b(?:distribution|dispersion|histogramme\s+(?:de|des|du)|box\s*plot|bo[iî]te\s+[àa]\s+"
                   r"moustaches|quartiles?)\b", re.I)  # fmt: skip
_TREND = re.compile(r"\b(?:[ée]volution|tendance|trend|over\s+time|au\s+fil\s+du\s+temps|courbe|historique|"
                    r"chronolog\w*|progress\w*)\b", re.I)  # fmt: skip
_PERIOD = [
    ("month", re.compile(r"\b(?:par\s+mois|mensuel\w*|monthly|per\s+month|by\s+month|chaque\s+mois|mois\s+par\s+mois)\b", re.I)),
    ("quarter", re.compile(r"\b(?:par\s+trimestre|trimestriel\w*|quarterly|per\s+quarter|by\s+quarter)\b", re.I)),
    ("year", re.compile(r"\b(?:par\s+an(?:n[ée]e)?s?|annuel\w*|yearly|per\s+year|by\s+year|chaque\s+ann[ée]e|"
                        r"ann[ée]e\s+par\s+ann[ée]e)\b", re.I)),
    ("week", re.compile(r"\b(?:par\s+semaine|hebdo\w*|weekly|per\s+week|by\s+week)\b", re.I)),
    ("day", re.compile(r"\b(?:par\s+jour|quotidien\w*|journalier\w*|daily|per\s+day|by\s+day)\b", re.I)),
]  # fmt: skip
_BY = re.compile(r"\b(?:par|by|per|pour\s+chaque|for\s+each|selon|suivant|across|entre\s+les)\s+(?:les?\s+|la\s+|l['’]|"
                 r"des\s+|the\s+|each\s+)?([\w'’-]+(?:\s+[\w'’-]+)?)", re.I)  # fmt: skip
_YEARS2 = re.compile(r"\b((?:19|20)\d\d)\b\s*(?:et|à|a|avec|vs\.?|versus|contre|and|to|-|/)\s*((?:19|20)\d\d)\b", re.I)
_VS_YEAR = re.compile(r"\b(?:par\s+rapport\s+[àa]|compar\w*\s+[àa]|vs\.?|versus|than|compared\s+(?:to|with))\s+"
                      r"((?:19|20)\d\d)\b", re.I)  # fmt: skip
_YEAR = re.compile(r"\b(?:en|in|pour|for|de|sur|during|année|annee)\s+((?:19|20)\d\d)\b", re.I)


def tokens(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", plain(text)) if w]


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _family(w: str) -> set[str]:
    for fam in SYNONYMS:
        if w in fam:
            return fam
    return {w}


def column_score(c: Column, words: set[str]) -> float:
    """How strongly the question names this column (its header words, singular/plural, synonyms)."""
    name_words = [w for w in tokens(re.sub(r"\([^)]*\)", " ", c.name)) if w not in _STOP and len(w) > 1]
    if not name_words:
        return 0.0
    stems = {_stem(w) for w in words}
    hit = 0.0
    for w in name_words:
        if w in words or _stem(w) in stems:
            hit += 1
        elif any(_stem(x) in stems or x in words for x in _family(w)):
            hit += 0.8
        elif len(w) >= 5 and any(x.startswith(w[:5]) for x in words if len(x) >= 5):
            hit += 0.6
    return hit / len(name_words) + 0.01 * hit


def _named(f: Frame, words: set[str], kinds: tuple[str, ...], exclude: set[str] = frozenset()) -> Column | None:
    best, score = None, 0.5
    for c in f.columns:
        if c.type not in kinds or c.name in exclude:
            continue
        s = column_score(c, words)
        if s > score:
            best, score = c, s
    return best


def main_measure(f: Frame) -> Column | None:
    nums = [c for c in f.columns if c.type == "number"]
    if not nums:
        return None
    for c in nums:
        if _MAIN_MEASURE.search(plain(c.name)):
            return c
    for c in nums:
        if c.unit in ("€", "$", "£", "k€", "M€", "CHF"):
            return c
    return next((c for c in nums if c.unit != "%"), nums[0])


def main_dimension(f: Frame) -> Column | None:
    dims = [c for c in f.columns if c.type in ("category", "bool")]
    if not dims:
        return None
    fit = [c for c in dims if 2 <= len({v for v in c.values if v is not None}) <= 12]
    return (fit or dims)[0]


def _value_filters(f: Frame, text: str, skip: set[str]) -> list[dict]:
    """« dans le Nord », « pour le produit Alpha »: a category value written in the question becomes a filter."""
    low = f" {plain(text)} "
    raw = f" {text} "
    out = []
    for c in f.columns:
        if c.type != "category" or c.name in skip:
            continue
        vals = {plain(v): v for v in c.values if v is not None}
        if len(vals) > 300:
            continue
        hits = []
        for pv, orig in vals.items():
            if len(pv) < 2:
                continue
            if len(pv) >= 4 and pv not in _STOP and re.search(rf"[^a-z0-9]{re.escape(pv)}[^a-z0-9]", low):
                hits.append(orig)  # « dans le nord »
            elif re.search(rf"(?<!\w){re.escape(str(orig))}(?!\w)", raw):
                hits.append(orig)  # « Est », « RH »: short values only with their own capitals
        if 1 <= len(hits) <= 3 and len(hits) < len(vals):
            out.append({"col": c.name, "op": "eq" if len(hits) == 1 else "in", "value": hits[0] if len(hits) == 1
                        else hits})  # fmt: skip
    return out


_FILE = re.compile(r"\b(?:fichiers?|tableaux?|tableurs?|feuilles?|onglets?|donn[ée]es|csv|xlsx?|excel|export|"
                   r"files?|tables?|sheets?|spreadsheets?|data(?:set)?|jeu\s+de\s+donn[ée]es)\b", re.I)  # fmt: skip
_ROWS = re.compile(r"\b(?:lignes?|rows?|enregistrements?|entr[ée]es|records?|observations?|commandes?|orders?|"
                   r"transactions?)\b", re.I)  # a row of a sales export is an order
# the words that ask for a computation by themselves; « combien », « quel », « meilleur », « total » do not (« quelle
# est la meilleure façon de présenter ce fichier ? », « what is the total population of France? »)
_STRONG = re.compile(
    r"\b(?:moyen(?:ne)?s?|average|mean|avg|m[ée]dian\w*|somme|cumul\w*|sum|top\s*\d*|flop|classement|ranking|"
    r"calcul\w*|calculate|compute|totale?s?\s+(?:de|du|des|of)\b)",
    re.I,
)


def refers_to_table(f: Frame, text: str, *, compute: bool = True) -> bool:
    """Whether ``text`` is about the table: it names a column (header, synonym), one of its values, a year or a
    period of its dates, its rows, or the file itself — with a word that asks for a computation when ``compute``
    (« résume ce fichier » is about it, but asks for none). A question with an attachment in the conversation is not
    about it by default (« Combien font 17 x 23 ? »)."""
    if not text:
        return False
    words = set(tokens(text))
    if any(column_score(c, words) > 0.5 for c in f.columns) or _ROWS.search(text):
        return True
    if any(c.type == "date" for c in f.columns) and (
        _YEARS2.search(text) or _VS_YEAR.search(text) or _YEAR.search(text) or any(rx.search(text) for _, rx in _PERIOD)
    ):
        return True
    if _value_filters(f, text, set()):
        return True
    return bool(_FILE.search(text) and (not compute or _STRONG.search(text) or _SHARE.search(text) or _CORR.search(text)
                                        or _DIST.search(text) or _TREND.search(text)))  # fmt: skip


def plan_question(f: Frame, text: str) -> dict | None:
    """{"query": ..., "why": ...} for an analytical question about ``f``, or None."""
    if not text or not _ASK.search(text) or _NOT_ASK.search(text) and not re.search(r"\b(?:calcul|combien|top)\w*",
                                                                                     text, re.I):  # fmt: skip
        return None
    if not refers_to_table(f, text):
        return None  # « quel / combien » alone is no computation on the table (review 28/11/2026)
    words = set(tokens(text))
    times = [c for c in f.columns if c.type == "date"]
    measure_named = _named(f, words, ("number",))
    # ---- correlation of two measures
    if _CORR.search(text):
        a = measure_named
        b = _named(f, words, ("number",), {a.name} if a else set())
        nums = [c for c in f.columns if c.type == "number"]
        if a and not b and len(nums) == 2:
            b = next(c for c in nums if c is not a)
        if not a and len(nums) == 2:
            a, b = nums
        if a and b:
            return {"query": {"op": "corr", "x": a.name, "y": b.name}, "why": "correlation"}
    # ---- distribution of one measure
    if _DIST.search(text) and (measure_named or main_measure(f)):
        return {"query": {"op": "describe", "measure": (measure_named or main_measure(f)).name}, "why": "describe"}
    q: dict = {"op": "aggregate"}
    filters: list[dict] = []
    # ---- compare two years
    m = _YEARS2.search(text)
    vs = _VS_YEAR.search(text)
    compare_years = None
    if (
        times
        and m
        and re.search(r"compar|vs|versus|contre|[ée]volution|entre|between|diff|progress|and|et", text, re.I)
    ):
        compare_years = [int(m.group(1)), int(m.group(2))]
    elif times and vs:
        other = [int(y) for y in re.findall(r"\b((?:19|20)\d\d)\b", text) if int(y) != int(vs.group(1))]
        have = sorted({v.year for v in times[0].values if v is not None})
        b = other[0] if other else (have[-1] if have else None)
        if b and b != int(vs.group(1)):
            compare_years = sorted([int(vs.group(1)), b])
    elif times and re.search(r"\bcompar\w*\b.*\b(?:ann[ée]es?|years?|n-1|an\s+dernier|last\s+year)\b|\bn\s*-\s*1\b|"
                             r"\byoy\b|year.over.year", text, re.I):  # fmt: skip
        have = sorted({v.year for v in times[0].values if v is not None})
        if len(have) >= 2:
            compare_years = have[-2:]
    # ---- aggregate
    agg = "sum"
    if _MEDIAN.search(text):
        agg = "median"
    elif _MEAN.search(text):
        agg = "mean"
    count = _COUNT.search(text)
    count_col = None
    if count:
        what = set(tokens(count.group(1) or ""))
        count_col = _named(f, what | words, ("category", "id", "text"))
        if count_col and column_score(count_col, what) > 0.5:
            agg = "distinct"
        elif not measure_named or column_score(measure_named, what) <= 0.5:
            agg, count_col = "count", None
    measure = measure_named or (main_measure(f) if agg not in ("count",) else None)
    if agg == "distinct":
        measure = count_col
    if measure is None and agg not in ("count", "distinct"):
        if not f.by_role("measure"):
            agg = "count"
        else:
            return None
    if measure is not None:
        q["measure"] = measure.name
    q["agg"] = agg
    # ---- group by a period or a dimension
    period = next((p for p, rx in _PERIOD if rx.search(text)), None)
    by = None
    for bm in _BY.finditer(text):
        target = set(tokens(bm.group(1)))
        if not target or target <= {"mois", "an", "annee", "trimestre", "semaine", "jour", "month", "year", "week",
                                    "day", "quarter"}:  # fmt: skip
            continue
        c = _named(f, target, ("category", "bool", "id", "text"), {measure.name} if measure else set())
        if c:
            by = c
            break
    top = _TOP.search(text)
    topn = None
    if top:
        g = next(x for x in top.groups() if x)
        topn = _WORD_N.get(g.lower(), None) or int(g)
    elif re.search(r"\b(?:meilleur|best|plus\s+(?:gros|grand|vendu|rentable)|premier|biggest|largest|top)\b", text, re.I) \
            and not period and not _TREND.search(text):  # fmt: skip
        topn = 1 if re.search(r"\b(?:le|la|the|quel(?:le)?)\s+(?:meilleur|best|plus|premier|biggest|largest)", text,
                              re.I) else None  # fmt: skip
        if topn is None:
            topn = 5
    if (topn or _SHARE.search(text) or re.search(r"\bclassement|ranking|rank\b", text, re.I)) and not by:
        by = _named(f, words, ("category", "id", "bool"), {measure.name} if measure else set())
        if not by and (_SHARE.search(text) or topn):
            by = main_dimension(f) if not topn else (main_dimension(f) or next(
                (c for c in f.columns if c.type in ("id", "text")), None))  # fmt: skip
    if not period and times and (_TREND.search(text) or compare_years):
        period = None if compare_years else ""  # "" = the best grain for the span
    if period is not None and not times:
        period = None
    if compare_years:
        q["op"] = "compare"
        q["years"] = compare_years
        q["time"] = times[0].name
        q["period"] = period or "month"
        if by:
            q["by"] = by.name
            q["sort"] = "desc"
    else:
        if period is not None:
            q["time"] = times[0].name
            if period:
                q["period"] = period
            else:
                q["period"] = None
        if by:
            q["by"] = by.name
        if topn:
            q["top"] = topn
            q["sort"] = "asc" if _ASC.search(text) else "desc"
        elif _ASC.search(text) and by:
            q["sort"] = "asc"
        if _SHARE.search(text) and by and agg in ("sum", "count"):
            q["share"] = True
        if agg in ("count", "distinct") and not by and period is None and measure is None:
            pass
        if not by and period is None and agg == "sum" and _MAX.search(text):
            q["agg"] = "max"
        elif not by and period is None and agg == "sum" and _MIN.search(text):
            q["agg"] = "min"
    # ---- filters: a year, a category value
    if not compare_years:
        y = _YEAR.search(text)
        if y and times and q.get("period") != "year":
            filters.append({"col": times[0].name, "op": "year", "value": int(y.group(1))})
    filters += _value_filters(f, text, {q.get("by", ""), q.get("measure", "")})
    if filters:
        q["filters"] = filters
    if q.get("period") is None:
        q.pop("period", None)
        if "time" in q and q["op"] != "compare":
            q["period"] = None
    if q["op"] == "aggregate" and "time" in q and q.get("period") is None:
        q.pop("period", None)
        q["period"] = _best_period(f, q["time"])
    return {"query": q, "why": "template"}


def _best_period(f: Frame, time: str) -> str:
    from birds.harness.analysis.profile import best_grain

    c = f.col(time)
    return best_grain([v for v in c.values if v is not None], c.grain)
