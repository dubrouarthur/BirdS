"""The corporate site and the chat welcome tell the brand story, with nothing invented.

Lightness, freedom to install the models anywhere (varied energy sources) and « conçu en France » come first;
no placeholder address, no hardware count, no base-model name, no third-party request (strict CSP).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES = sorted(SITE.glob("*.html")) + sorted((SITE / "en").glob("*.html"))
STATIC = ROOT / "birds" / "web" / "static"


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_no_placeholder_address_and_contact_leads_somewhere_real(page):
    html = text(page)
    assert "birdmodels.example" not in html and "TODO" not in html
    for href in re.findall(r'<a class="contact-mail" href="([^"]+)"', html):
        target, _, anchor = href.partition("#")
        if target:  # another page of the site, with the anchor it names
            other = SITE / (target.strip("/") + ".html")
            assert other.is_file(), href
            assert f'id="{anchor}"' in text(other), href
        else:
            assert f'id="{anchor}"' in html, href


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_strict_csp_nothing_inline_nothing_third_party(page):
    html = text(page)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline script"
    assert " style=" not in html and " onclick=" not in html
    assert not re.search(r'(src|srcset)="https?://|<link[^>]+href="https?://', html), "third-party resource"
    for a in re.findall(r'<a [^>]*href="https?://[^"]*"[^>]*>', html):  # source links in the notes: a visit, not a load
        assert 'rel="noopener' in a or "noreferrer" in a, a


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_no_hardware_count_no_base_model(page):
    words = re.sub(r"<[^>]+>", " ", text(page))
    assert not re.search(r"\bqwen\b|\bH100\b|\bA100\b|\d+\s*(GPU|cartes graphiques)", words, re.I)
    assert not re.search(r"mat[ée]riel modeste|modest hardware", words, re.I)


def test_contact_address_is_not_invented():
    cfg = text(SITE / "config.js")
    mail = re.search(r'CONTACT_EMAIL:\s*"([^"]*)"', cfg).group(1)
    assert mail == "" or not mail.endswith(".example")


@pytest.mark.parametrize(
    ("page", "words"),
    [
        ("index.html", ["Des petits modèles", "vrais", "usages", "légèreté", "où vous voulez", "Conçu en France",
                        "sources d’énergie variées"]),
        ("en/index.html", ["Small models", "real", "work", "lightness", "wherever you want", "Designed in France",
                           "varied energy sources"]),
    ],
)  # fmt: skip
def test_home_puts_lightness_freedom_and_france_first(page, words):
    html = text(SITE / page)
    hero = html[html.index('class="hero"') : html.index("</section>", html.index('class="hero"'))]
    for w in words:
        assert w in hero, w
    assert html.index('id="installer"' if page == "index.html" else 'id="install"') < html.index('id="rse"')


def test_home_sections_match_in_both_languages():
    def sections(p):
        return re.findall(r'<section class="([a-z -]+)"', text(SITE / p))

    assert sections("index.html") == sections("en/index.html")


def test_chat_welcome_tells_the_same_story_in_both_languages():
    i18n = text(STATIC / "i18n.js")
    for key in ("welcome.where", "welcome.where.p", "about.where", "about.where.p"):
        assert i18n.count(f'"{key}":') == 2, key
    assert "la liberté d'installer nos modèles où vous voulez" in i18n
    assert "the freedom to install our models wherever you want" in i18n
    views = text(STATIC / "views.js")
    assert 'value("find_places", "welcome.where")' in views and "welcome.fast" not in i18n + views


def test_runtime_system_keeps_the_trained_text_and_adds_the_brand():
    from birds.sources.identity import BRAND_NOTE, DEFAULT_SYSTEM, RUNTIME_SYSTEM

    for lang in ("fr", "en"):
        assert RUNTIME_SYSTEM[lang].startswith(DEFAULT_SYSTEM[lang] + " ")
        assert RUNTIME_SYSTEM[lang].endswith(BRAND_NOTE[lang])
    assert "en France" in BRAND_NOTE["fr"] and "in France" in BRAND_NOTE["en"]
    assert not re.search(r"qwen|gpu", " ".join(BRAND_NOTE.values()), re.I)
