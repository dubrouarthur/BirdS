"""Pictures and charts of canvas decks: where a chart's figures come from (birds/canvas/figures.py), and the picture
search measured live on 28/11/2026 (docs/CANVAS.md § 9: Commons first, query variants, rate limits, relevance)."""

from __future__ import annotations

import io
import threading
import time

import pytest

from birds.canvas import dsl, figures, images, turn


def _deck(chart_rows, title="Évolution"):
    rows = "\n".join(f"{a}: {b}" for a, b in chart_rows)
    return dsl.parse(f"---\ntitle: T\n---\n# Intro\n- a\n- b\n# {title}\n::: chart type=bar\n{rows}\n:::\n", "deck")


# ------------------------------------------------------------------ figures


def test_numbers_read_thousands_decimals_and_not_inside_words():
    assert figures.numbers("budget 85 000 €, 12,5 % et T1 120 k€") >= {85000.0, 12.5, 120.0}
    assert 1.0 not in figures.numbers("T1 et T2")  # « T1 » is a label, not the figure 1


def test_a_chart_of_figures_nobody_gave_becomes_a_note_asking_for_them():
    doc = _deck([("2023", 12), ("2024", 15), ("2025", 18)])
    repairs: list[str] = []
    n = figures.check(doc, "Prépare un pitch deck de 6 slides pour une startup de livraison à vélo", None, "fr",
                      repairs)  # fmt: skip
    part = doc["blocks"][1]["parts"][0]
    assert n == 1 and part["t"] == "callout" and part["need"] == "figures"
    assert "2023, 2024, 2025" in part["text"] and "Aucun chiffre n'est inventé" in part["text"]
    assert any("found in no source" in r for r in repairs)
    assert dsl.validate(doc)["blocks"][1]["parts"][0]["need"] == "figures"  # survives validation (the chip reads it)


def test_a_chart_of_the_users_figures_is_kept():
    doc = _deck([("T1", 120), ("T2", 135), ("T3", 150), ("T4", 170)])
    ask = "Prépare 5 slides pour le comité : chiffre d'affaires T1 120 k€, T2 135 k€, T3 150 k€, T4 170 k€"
    assert figures.check(doc, ask) == 0 and doc["blocks"][1]["parts"][0]["t"] == "chart"


def test_a_difference_of_given_figures_is_a_computation_not_an_invention():
    doc = _deck([("2024", 36), ("2025", 34)], "Gains d'adhérents")
    assert figures.check(doc, "adhérents 250 en 2023, 286 en 2024 et 320 en 2025") == 0


def test_figures_from_a_tool_result_or_an_earlier_answer_count():
    doc = _deck([("Lyon", 522250), ("Marseille", 873076)])
    history = [
        {"role": "user", "content": "Population de Lyon et Marseille ?"},
        {"role": "assistant", "content": "Lyon : 522 250 habitants ; Marseille : 873 076 (Insee 2021)."},
    ]
    assert figures.check(doc, figures.sources_of("Fais une prez avec ces chiffres", history)) == 0

    class Run:
        messages = [{"role": "tool", "content": '{"rows": [["Lyon", 522250], ["Marseille", 873076]]}'}]
        figures = []

    doc2 = _deck([("Lyon", 522250), ("Marseille", 873076)])
    assert figures.check(doc2, figures.sources_of("Fais une prez", [], Run())) == 0


def test_a_chart_drawn_from_the_decks_own_table_is_kept_and_an_unchanged_chart_too():
    base = dsl.parse("---\ntitle: T\n---\n# Ventes\n| Mois | Ventes |\n|---|---|\n| Janv | 40 |\n| Févr | 55 |\n",
                     "deck")  # fmt: skip
    doc = _deck([("Janv", 40), ("Févr", 55)], "Ventes")
    assert figures.check(doc, "fais un graphique de ce tableau", base) == 0
    old = _deck([("2023", 12), ("2024", 15)])
    again = _deck([("2023", 12), ("2024", 15)])
    assert figures.check(again, "change le titre", old) == 0  # a chart already in the deck is not judged again


def test_the_deck_spec_asks_for_figures_of_the_request_and_shows_a_picture():
    for lg in ("fr", "en"):
        spec = turn.SPEC["deck"][lg]
        assert spec.count("::: image") == 2 and ("donné dans la demande" in spec or "given in the request" in spec)


# ------------------------------------------------------------------ pictures


def test_an_uploaders_name_is_not_what_the_picture_shows():
    assert images.clean_title("Cormorans - Flickr - Avel-Breizh") == "Cormorans"
    assert not images.relevant("breizh landscape", "Cormorans - Flickr - Avel-Breizh")
    assert images.relevant("brittany coast", "Coast of Brittany A21151")


def test_openverse_tags_alone_are_not_enough():
    # seen live: « Venice, canalside view from the waterbus » for « night train europe history » (loose Flickr tags)
    tags = ["train", "europe", "night", "history"]
    assert not images.relevant("night train europe history", "Venice, canalside view from the waterbus", tags)
    assert images.relevant("night train europe", "Night train leaving Vienna", ["europe"])


def test_query_variants_drop_words_that_describe_no_picture():
    assert images.variants("happy cyclist delivering food") == [
        "happy cyclist delivering food",
        "cyclist delivering food",
        "cyclist delivering",
    ]
    assert images.variants("tramway") == ["tramway"]
    assert images.variants("  ") == []
    assert images.variants("chart showing quarterly growth") == []  # a chart is drawn from figures, not searched


class Fake:
    """Commons and Openverse: ``commons`` / ``openverse`` are lists of page / result dicts, or an exception."""

    def __init__(self, commons=(), openverse=()):
        self.commons, self.openverse, self.calls = commons, openverse, []
        self.lock = threading.Lock()

    def json(self, url):
        with self.lock:
            self.calls.append(url)
        src = self.openverse if "openverse" in url else self.commons
        if isinstance(src, Exception):
            raise src
        return {"results": list(src)} if "openverse" in url else {"query": {"pages": list(src)}}

    def image(self, url):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1200, 800), (40, 90, 200)).save(buf, "JPEG")
        return buf.getvalue()


def _page(title, i=0):
    meta = {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "Ada"},
            "UsageTerms": {"value": "Creative Commons Attribution-Share Alike 4.0"}}  # fmt: skip
    return {"title": f"File:{title}.jpg", "index": i, "imageinfo": [{
        "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{i}.jpg/1280px-{i}.jpg",
        "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{i}.jpg", "descriptionurl":
        f"https://commons.wikimedia.org/wiki/File:{i}.jpg", "extmetadata": meta, "width": 1600, "height": 1000}]}  # fmt: skip


@pytest.fixture(autouse=True)
def _fresh():
    images.CACHE.clear()
    images.COOL.until.clear()
    yield
    images.COOL.until.clear()


def test_openverse_then_commons_and_a_long_query_is_retried_shorter():
    f = Fake(commons=[_page("Delivery cyclist, Liverpool")])
    # « happy cyclist delivering food » finds nothing as written on Commons (full-text AND): the variants do
    m = images.search_web("happy cyclist delivering food", f)
    assert "openverse" in f.calls[0] and "commons.wikimedia.org" in f.calls[1]
    assert m is not None and m.title.startswith("Delivery cyclist") and m.credit.endswith("Wikimedia Commons")


def test_a_rate_limited_source_is_noted_not_skipped():
    f = Fake(commons=[], openverse=ValueError("HTTP 429"))
    assert images.search_web("tramway lyon", f) is None
    assert images.COOL.hot("openverse")  # the canvas says « réessayez dans une minute »
    n = len([u for u in f.calls if "openverse" in u])
    images.search_web("métro paris", f)
    assert len([u for u in f.calls if "openverse" in u]) > n  # asked again: the refusals come in short windows


def test_resolve_searches_in_parallel_and_shares_one_picture_per_query():
    starts: list[float] = []

    def find(q, exclude, mid):
        starts.append(time.monotonic())
        time.sleep(0.3)
        return images.generated(q, mid)

    doc = dsl.parse("---\ntitle: T\nimage: forest\n---\n# A\n- x\n::: image query=\"forest\"\n:::\n# B\n- y\n"
                    "::: image query=\"sea\"\n:::\n# C\n- z\n::: image query=\"city\"\n:::\n", "deck")  # fmt: skip
    t0 = time.monotonic()
    found = images.resolve(doc, find, limit=8, deadline=time.monotonic() + 10)
    assert len(found) == 3 and time.monotonic() - t0 < 0.8  # three searches at once, not 0.9 s in a row
    assert doc["cover"]["media"] == doc["blocks"][0]["parts"][1]["media"]  # same query, same picture
    assert len({p["media"] for b in doc["blocks"] for p in b["parts"] if p["t"] == "image"}) == 3


def test_resolve_leaves_a_placeholder_when_a_search_fails_or_overruns():
    def find(q, exclude, mid):
        if q == "slow":
            time.sleep(3)
        if q == "boom":
            raise RuntimeError("x")
        return images.generated(q, mid)

    doc = dsl.parse("---\ntitle: T\n---\n# A\n::: image query=\"slow\"\n:::\n# B\n::: image query=\"boom\"\n:::\n"
                    "# C\n::: image query=\"ok\"\n:::\n", "deck")  # fmt: skip
    found = images.resolve(doc, find, limit=8, deadline=time.monotonic() + 0.5)
    parts = [b["parts"][0] for b in doc["blocks"]]
    assert [p.get("missing") for p in parts] == [True, True, None] and len(found) == 1


def test_the_fetcher_asks_a_rate_limited_api_once_more(monkeypatch):
    from birds.harness import guard
    from birds.harness import office_media as om

    answers = [guard.ToolError("HTTP 429"), (200, "application/json", b'{"ok": 1}', {})]
    agents = []

    def fake(http, cfg, url, **kw):
        agents.append(kw.get("user_agent"))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(guard, "fetch_bytes", fake)

    class Cfg:
        search_contact = "https://bird.example"

    assert om.Fetcher(None, Cfg()).json("https://commons.wikimedia.org/w/api.php?x", retry=0.01) == {"ok": 1}
    assert len(agents) == 2 and "bird.example" in agents[0]  # Wikimedia's policy: a User-Agent with a contact


def _ov(i, title):
    return {"id": str(i), "title": title, "url": f"https://live.staticflickr.com/{i}.jpg", "creator": "Ada",
            "license": "by", "license_version": "2.0", "foreign_landing_url": f"https://www.flickr.com/p/{i}",
            "provider": "flickr", "filetype": "jpg", "filesize": 300000, "width": 1600, "height": 1000,
            "tags": []}  # fmt: skip


def test_the_model_looks_at_each_candidate_and_a_no_rejects_it():
    seen = []

    def judge(query, m):
        seen.append((query, m.source))
        return m.source.endswith("/p/2")  # the second one shows the subject

    f = Fake(openverse=[_ov(1, "Night train party"), _ov(2, "Night train in Vienna")])
    m = images.search_web("night train europe", f, judge=judge)
    assert m is not None and m.source.endswith("/p/2")
    assert [q for q, _ in seen] == ["night train europe"] * 2  # judged against the words searched


def test_after_six_noes_a_search_gives_no_picture():
    f = Fake(openverse=[_ov(i, f"Night train {i}") for i in range(1, 9)])
    n = []

    def no(q, m):
        n.append(1)
        return False

    assert images.search_web("night train", f, judge=no) is None
    assert len(n) <= images.JUDGED * len(images.variants("night train"))


def test_vision_judge_reads_yes_and_no_and_needs_a_model_that_sees():
    class Llm:
        def __init__(self, text):
            self.text, self.msgs = text, []

        def chat(self, messages, max_tokens, **kw):
            self.msgs.append(messages)
            return {"text": self.text}

    m = images.generated("forest", "g1")
    for text, want in (("Yes.", True), ("non", False), ("No", False), ("maybe", None)):
        llm = Llm(text)
        assert images.vision_judge(llm)("forest", m) is want
        content = llm.msgs[0][0]["content"]
        assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,") and "forest" in content[1]["text"]
    assert images.vision_judge(object()) is None  # a model without the chat route: no look, the words decide
