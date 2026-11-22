"""Charts and web images in the web app: answer event, image choice, image extraction, /api/img, the demo."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from birds.harness import FakeClient, guard
from birds.harness.tools import StaticBackend, WikipediaBackend
from birds.harness.tools.web import extract_image
from birds.web import tokens
from birds.web.backends import HarnessBackend, pick_scenario, pick_web_images
from birds.web.server import CSP, STATIC_DIR, create_app, tools_info
from birds.web.settings import Settings

SECRET = b"img-test-secret"
CSP_TODAY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; "
    "manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class Tok:
    def apply_chat_template(self, messages, tools=None, **_):
        return json.dumps({"tools": [t["function"]["name"] for t in tools or []], "messages": messages})


def call(name, **args):
    params = "".join(
        f"<parameter={k}>\n{v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}\n</parameter>\n"
        for k, v in args.items()
    )
    return f"<tool_call>\n<function={name}>\n{params}</function>\n</tool_call>"


def sse(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(f[6:]) for f in response.text.split("\n\n") if f.startswith("data: ")]


def answer_of(events):
    return next(e for e in events if e["type"] == "answer")


def png(w=200, h=150, color="red") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- 14 answer event


def test_answer_event_carries_charts_and_web_images(monkeypatch):
    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])
    results = [
        {
            "title": "Marie Curie",
            "url": "https://fr.wikipedia.org/wiki/Marie_Curie",
            "snippet": "Physicienne.",
            "image": "https://upload.wikimedia.org/curie.jpg",
        }
    ]
    llm = FakeClient([call("web_search", query="Marie Curie"), "Marie Curie était une physicienne et chimiste [1]."])
    backend = HarnessBackend(llm, Tok(), search=StaticBackend(results))
    app = create_app(Settings(rate_limit=0, signing_secret=SECRET, signing="configured"), server_backend=backend)
    with TestClient(app) as c:
        body = {"messages": [{"role": "user", "content": "Cherche qui était Marie Curie."}], "lang": "fr"}
        ans = answer_of(sse(c.post("/api/chat", json=body)))
    assert ans["charts"] == [] and ans["images"] == []  # "images" stays the user's transcriptions
    (img,) = ans["web_images"]
    assert img["src"].startswith("/api/img?") and "upload.wikimedia.org" in img["src"]
    assert img["page"] == "https://fr.wikipedia.org/wiki/Marie_Curie" and img["domain"] == "fr.wikipedia.org"
    assert "upload.wikimedia.org" not in json.dumps(llm.prompts)  # the model never saw the image URL


def test_answer_event_carries_the_chart_spec():
    rows = [["T1", "120"], ["T2", "135,5"]]
    llm = FakeClient([call("make_chart", title="CA", columns=["T", "CA (k€)"], rows=rows), "Voici le graphique."])
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, Tok()))
    with TestClient(app) as c:
        body = {"messages": [{"role": "user", "content": "Fais un graphique : T1 120, T2 135,5"}], "lang": "fr"}
        events = sse(c.post("/api/chat", json=body))
    ans = answer_of(events)
    assert ans["charts"][0]["rows"] == [["T1", 120], ["T2", 135.5]] and ans["files"] == []
    step = [e for e in events if e["type"] == "step" and e["status"] == "done"][0]
    assert step["summary"] == "Graphique affiché (2 valeurs, 1 série)" and step["info"]["chart"] == "c1"
    assert "graphique affiché" in ans["memo"]


def test_a_quoted_chart_tool_result_is_not_shown():
    # live model: « Voici le graphique : [Chart shown to the user in the chat: bar chart « … », …] Paris domine… »
    rows = [["Paris", 2161000], ["Lyon", 522000]]
    echo = (
        "Voici le graphique : [Chart displayed to the user (do not quote this note): bar chart « Population », "
        "2 labels, 1 series (Habitants), values from 522000 to 2161000.] Paris domine largement."
    )
    llm = FakeClient([call("make_chart", title="Population", columns=["Ville", "Habitants"], rows=rows), echo])
    app = create_app(Settings(rate_limit=0), server_backend=HarnessBackend(llm, Tok()))
    with TestClient(app) as c:
        body = {"messages": [{"role": "user", "content": "Fais un graphique : Paris 2161000, Lyon 522000"}]}
        ans = answer_of(sse(c.post("/api/chat", json=body)))
    assert ans["content"] == "Voici le graphique : Paris domine largement." and ans["charts"]
    from birds.web.backends import strip_tool_echo

    assert strip_tool_echo("Chart shown to the user in the chat: bar chart.\nAdjusted: x\nBien.") == "Bien."


# --------------------------------------------------------------------------- 15 image choice


def step(tool, error=None, results=None):
    return SimpleNamespace(tool=tool, error=error, info={"results": results or []} if results is not None else {})


def run(steps, images, sources=(), stop="answer"):
    return SimpleNamespace(stop_reason=stop, steps=steps, images=images, sources=list(sources))


def cand(i, domain="a.test", origin="search", title="Marie Curie physicienne", src=None):
    return {
        "src": src or f"https://img.{domain}/{i}.jpg",
        "page": f"https://{domain}/p{i}",
        "title": title,
        "alt": "",
        "origin": origin,
    }


SIGN = lambda u: "/api/img?u=" + u  # noqa: E731
ANS, REQ = "Marie Curie était une physicienne.", "Cherche Marie Curie"
OK = [step("web_search", results=[{"title": "x", "url": "u"}])]


def test_pick_web_images_rules():
    assert pick_web_images(run([], [cand(1)]), ANS, REQ, [], SIGN) == []  # no web step
    failed = [step("web_search", error="quota")]
    assert pick_web_images(run(failed, [cand(1)]), ANS, REQ, [], SIGN) == []
    empty = [step("web_search", results=[])]
    assert pick_web_images(run(empty, [cand(1)]), ANS, REQ, [], SIGN) == []
    many = [cand(i, domain=f"d{i}.test") for i in range(6)]
    assert len(pick_web_images(run(OK, many), ANS, REQ, [], SIGN)) == 3
    same = [cand(1), cand(2)]  # one per domain
    assert len(pick_web_images(run(OK, same), ANS, REQ, [], SIGN)) == 1
    off = [cand(1, title="Recette du clafoutis")]
    assert pick_web_images(run(OK, off), ANS, REQ, [], SIGN) == []
    twice = [cand(1, domain="x.test", src="https://i.test/a.jpg"), cand(2, domain="y.test", src="https://i.test/a.jpg")]
    assert len(pick_web_images(run(OK, twice), ANS, REQ, [], SIGN)) == 1
    assert pick_web_images(run(OK, [cand(1)]), ANS, REQ, [], None) == []  # no signer, no image


def test_pick_web_images_read_page_first_with_its_number():
    page = cand(9, domain="b.test", origin="page")
    out = pick_web_images(
        run(OK + [step("read_page")], [cand(1), page], sources=[page["page"]]),
        ANS,
        REQ,
        [{"n": 1, "url": page["page"], "title": "t"}],
        SIGN,
    )
    assert out[0]["page"] == page["page"] and out[0]["n"] == 1 and "n" not in out[1]


# --------------------------------------------------------------------------- 16 image extraction


@pytest.mark.parametrize(
    "html,want",
    [
        ('<meta property="og:image" content="https://e.test/a.jpg">', "https://e.test/a.jpg"),
        ('<meta name="twitter:image" content="/img/b.png">', "https://site.test/img/b.png"),
        ('<meta property="og:image" content="data:image/png;base64,AAA">', None),
        ('<meta property="og:image" content="https://e.test/a.svg">', None),
        ('<meta property="og:image" content="https://e.test/logo.png">', None),
        (
            '<article><img src="/p/photo.jpg" width="640" height="400" alt="Photo"></article>',
            "https://site.test/p/photo.jpg",
        ),
        ('<article><img src="/p/tiny.jpg" width="40" height="40"></article>', None),
        ("<p>Rien</p>", None),
    ],
)
def test_extract_image(html, want):
    got = extract_image(f"<html><head>{html}</head><body>{html}</body></html>", "https://site.test/page")
    assert (got or {}).get("src") == want


# --------------------------------------------------------------------------- 17 Wikipedia page images


def test_wikipedia_asks_for_page_images_in_the_same_request():
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        data = {
            "query": {
                "pages": [
                    {
                        "index": 1,
                        "title": "Marie Curie",
                        "fullurl": "https://fr.wikipedia.org/wiki/Marie_Curie",
                        "extract": "Physicienne.",
                        "thumbnail": {"source": "https://upload.wikimedia.org/c.jpg", "width": 640, "height": 800},
                    }
                ]
            }
        }
        return httpx.Response(200, json=data)

    out = WikipediaBackend(httpx.Client(transport=httpx.MockTransport(handler))).search("Curie", 3, lang="fr")
    assert len(seen) == 1 and "pageimages" in seen[0]["prop"] and seen[0]["piprop"] == "thumbnail"
    assert "pilicense" not in seen[0]  # default: free-licence images only
    assert out[0]["image"] == "https://upload.wikimedia.org/c.jpg"


# --------------------------------------------------------------------------- 18 /api/img


@pytest.fixture
def img_app(monkeypatch):
    ips = {"img.test": ["93.184.216.34"], "private.test": ["10.0.0.1"], "hop.test": ["93.184.216.34"]}

    def resolve(host):
        import ipaddress

        try:
            return [str(ipaddress.ip_address(host.strip("[]")))]  # a literal resolves to itself, as getaddrinfo does
        except ValueError:
            return ips.get(host, ["93.184.216.34"])

    monkeypatch.setattr(guard, "resolve", resolve)
    seen = []

    def handler(req):
        seen.append(req)
        path = req.url.path
        if req.headers["host"] == "hop.test":
            return httpx.Response(302, headers={"location": "http://private.test/x.png"})
        if path == "/ok.png":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png(1200, 900))
        if path == "/page.html":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
        if path == "/x.svg":
            return httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=b"<svg/>")
        if path == "/liar.png":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\xff\xd8\xff" + b"0" * 100)
        if path == "/big.png":
            return httpx.Response(
                200, headers={"content-type": "image/png"}, content=b"\x89PNG\r\n\x1a\n" + b"0" * 3_000_000
            )
        if path == "/declared.png":
            return httpx.Response(
                200, headers={"content-type": "image/png", "content-length": "3000000"}, content=b"\x89PNG"
            )
        if path == "/bomb.png":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=_png_header(10000, 10000))
        if path == "/small.png":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png(32, 32))
        return httpx.Response(404)

    s = Settings(rate_limit=0, img_rate_limit=0, signing_secret=SECRET, signing="configured")
    app = create_app(s)
    app.state.image_client = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        yield c, seen, app


def _png_header(w, h) -> bytes:
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def signed(u, ttl=3600, now=None):
    return tokens.sign_image_url(u, SECRET, ttl, now)


def code(r):
    return r.json()["detail"]["code"]


def test_api_img_serves_a_signed_image_re_encoded(img_app):
    c, seen, _ = img_app
    r = c.get(
        signed("https://img.test/ok.png"), headers={"Cookie": "a=b", "Referer": "https://x", "Authorization": "x"}
    )
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert "set-cookie" not in r.headers and r.headers["cache-control"].startswith("public, max-age=3600")
    from PIL import Image

    im = Image.open(io.BytesIO(r.content))
    assert im.format == "WEBP" and max(im.size) <= 640
    up = seen[-1].headers
    assert not {"cookie", "referer", "authorization", "accept-language"} & {k.lower() for k in up}
    assert up["user-agent"].startswith("BirdHarness")
    assert r.headers["content-security-policy"] == CSP_TODAY


@pytest.mark.parametrize(
    "path,status,err",
    [
        ("/page.html", 415, "image_type"),
        ("/x.svg", 415, "image_type"),
        ("/liar.png", 415, "image_type"),
        ("/big.png", 413, "too_large"),
        ("/declared.png", 413, "too_large"),
        ("/bomb.png", 422, "image_invalid"),
        ("/small.png", 422, "image_too_small"),
        ("/missing.png", 502, "upstream"),
    ],
)
def test_api_img_refusals(img_app, path, status, err):
    c, _, _ = img_app
    r = c.get(signed("https://img.test" + path))
    assert r.status_code == status and code(r) == err
    assert r.headers["cache-control"] == "no-store"


def test_api_img_signature_and_egress(img_app):
    c, _, _ = img_app
    good = signed("https://img.test/ok.png")
    assert c.get(good.replace("ok.png", "ok2.png")).status_code == 403  # u changed: signature no longer matches
    assert c.get("/api/img?u=https://img.test/ok.png").status_code == 400  # unsigned
    old = signed("https://img.test/ok.png", ttl=10, now=time.time() - 100)
    assert c.get(old).status_code == 410
    for ip in ("10.0.0.1", "127.0.0.1", "169.254.169.254", "::1"):
        r = c.get(signed(f"http://{ip if ':' not in ip else '[' + ip + ']'}/x.png"))
        assert r.status_code == 403 and code(r) == "blocked", ip
    r = c.get(signed("http://private.test/x.png"))
    assert r.status_code == 403 and code(r) == "blocked"
    r = c.get(signed("http://hop.test/x.png"))  # redirect to a private address
    assert r.status_code == 403 and code(r) == "blocked"
    r = c.get(good, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and code(r) == "cross_origin"


def test_api_img_rate_limit(monkeypatch):
    monkeypatch.setattr(guard, "resolve", lambda host: ["93.184.216.34"])
    app = create_app(Settings(rate_limit=0, img_rate_limit=2, signing_secret=SECRET, signing="configured"))
    with TestClient(app) as c:
        codes = [c.get("/api/img?u=x").status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_reencode_bounds_decoding_and_keeps_orientation():
    from PIL import Image

    from birds.web.server import ApiError, reencode_image

    with pytest.raises(ApiError) as err:  # 20 Mpx: a small compressible file that would decode to 80 MB
        reencode_image("image/png", _png_header(5000, 4000))
    assert err.value.detail["code"] == "image_invalid"
    im = Image.new("RGB", (4000, 1000), "blue")  # JPEG decoded at reduced scale, EXIF rotation applied
    exif = im.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    out = Image.open(io.BytesIO(reencode_image("image/jpeg", buf.getvalue())))
    assert out.format == "WEBP" and out.size == (160, 640) and not out.getexif()


def _trickler(script):
    """A local HTTP server that runs ``script(conn)`` for each connection (a slow or hostile upstream)."""
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.recv(65536)
            try:
                script(conn)
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv, srv.getsockname()[1]


def _trickle_headers(conn):
    for ch in b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nX-Pad: " + b"a" * 400:
        conn.send(bytes([ch]))
        time.sleep(0.05)


def test_fetch_image_deadline_covers_trickled_headers(monkeypatch):
    # an upstream that sends its status line and headers one byte at a time must not hold the worker: each read
    # is quick, so only a wall-clock deadline for the whole fetch stops it
    from birds.harness import Config

    srv, port = _trickler(_trickle_headers)
    monkeypatch.setattr(guard, "resolve", lambda host: ["127.0.0.1"])
    monkeypatch.setattr(guard, "ip_is_public", lambda ip: True)
    cfg = Config(workspace=Path("."), audit_file=None, allowed_ports=(port,))
    t = time.monotonic()
    with httpx.Client(trust_env=False) as http, pytest.raises(guard.FetchError) as err:
        guard.fetch_image(http, cfg, f"http://slow.test:{port}/x.png", timeout=0.4)
    srv.close()
    assert err.value.code == "upstream" and str(err.value) == "too slow"
    assert time.monotonic() - t < 2.0  # 2 x timeout, not 400 x 0.05 s


def test_fetch_deadline_counts_every_redirect_hop(monkeypatch):
    # each hop answers a redirect just under the per-read timeout: the hops share one budget
    from birds.harness import Config

    def slow_redirect(conn):
        time.sleep(0.3)
        conn.send(b"HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")

    srv, port = _trickler(slow_redirect)
    monkeypatch.setattr(guard, "resolve", lambda host: ["127.0.0.1"])
    monkeypatch.setattr(guard, "ip_is_public", lambda ip: True)
    cfg = Config(workspace=Path("."), audit_file=None, allowed_ports=(port,), max_redirects=20)
    t = time.monotonic()
    with httpx.Client(trust_env=False) as http, pytest.raises(guard.FetchError) as err:
        guard.fetch_image(http, cfg, f"http://slow.test:{port}/x.png", timeout=0.4)
    srv.close()
    assert str(err.value) == "too slow" and time.monotonic() - t < 1.5


# --------------------------------------------------------------------------- 19 CSP unchanged


def test_csp_is_unchanged():
    assert CSP == CSP_TODAY


# --------------------------------------------------------------------------- 20 demo


def demo_events(text, lang="fr"):
    app = create_app(Settings(rate_limit=0, demo_delay=0))
    with TestClient(app) as c:
        return sse(c.post("/api/chat", json={"messages": [{"role": "user", "content": text}], "lang": lang}))


def test_demo_chart_and_image():
    assert pick_scenario("Fais un graphique de la part des demandes") == "chart"
    assert pick_scenario("Fais un tableur avec un graphique") == "sheet"
    assert pick_scenario("Corrige l'orthographe de ce paragraphe") != "chart"
    (spec,) = answer_of(demo_events("Fais un graphique de la part des demandes"))["charts"]
    assert spec["type"] == "bar" and len(spec["rows"]) == 5 and spec["unit"] == "%"
    assert [r[1] for r in spec["rows"]][1:4] == [27.5, 18, 12.5]
    assert answer_of(demo_events("Trace la courbe"))["charts"][0]["type"] == "line"
    assert answer_of(demo_events("Make a pie chart", "en"))["charts"][0]["type"] == "pie"
    (img,) = answer_of(demo_events("Cherche la consommation des petits modèles"))["web_images"]
    assert img["src"].startswith("/static/demo/") and img["demo"] is True
    asset = STATIC_DIR / "demo" / "petits-modeles.webp"
    assert asset.read_bytes()[8:12] == b"WEBP" and asset.stat().st_size <= 15_000


# --------------------------------------------------------------------------- 21 i18n and tools_info


def test_tools_info_lists_make_chart():
    info = tools_info(Settings(), SimpleNamespace(tools=["make_chart"], kind="demo"))
    chart = next(t for t in info["tools"] if t["name"] == "make_chart")
    assert chart["state"] == "on" and "graphique" in chart["fr"]


def test_chart_and_image_strings_exist_in_both_languages():
    text = (Path(STATIC_DIR) / "i18n.js").read_text(encoding="utf-8")
    for key in ("chart.png", "chart.csv", "chart.xlsx", "chart.data", "webimg.note", "webimg.demo", "tool.make_chart"):
        assert text.count(f'"{key}"') == 2, key
