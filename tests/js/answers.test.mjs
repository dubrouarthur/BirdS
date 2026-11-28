// Answer content (cluster C2 of the chat audit), pure parts: tool labels, math, citations, rich copy, feedback.
// Run: node --test tests/js/*.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { ANSWER_STRINGS } from "../../birds/web/static/answers-i18n.js";
import { state, toolLabel } from "../../birds/web/static/core.js";

test("answer strings: French first, English parity", () => {
  assert.deepEqual(Object.keys(ANSWER_STRINGS.fr).sort(), Object.keys(ANSWER_STRINGS.en).sort());
});

test("a tool id never reaches the screen", () => {
  state.prefs.lang = "fr";
  assert.equal(toolLabel("lookup_entity"), "Fiche encyclopédique");
  assert.equal(toolLabel("web_search"), "Recherche web");
  assert.equal(toolLabel("some_new_tool"), "Outil");
  state.prefs.lang = "en";
  assert.equal(toolLabel("lookup_entity"), "Encyclopedia card");
  assert.equal(toolLabel("some_new_tool"), "Tool");
  state.prefs.lang = "fr";
});

test("the code badge names what was checked (syntax), never a run, and only on the server's verdict", async () => {
  const { renderMarkdown } = await import("../../birds/web/static/markdown.js");
  const { STRINGS } = await import("../../birds/web/static/i18n.js");
  for (const lang of ["fr", "en"]) {
    const ok = STRINGS[lang]["code.check.ok"];
    const tip = STRINGS[lang]["code.check.title"];
    assert.match(ok, /valide|valid/i, lang);
    assert.doesNotMatch(ok, /vérifi|testé|exécut|checked|tested|runs?\b/i, lang);
    assert.match(tip, /sans exécuter|without running/, lang);
  }
  const code = "```python\nfrom datetime import datetime\nprint(datetime.strptime('14 juillet 1789', '%d %B %Y'))\n```";
  const parsed = renderMarkdown(code, { rich: true, final: true, codeChecks: [{ i: 0, n: 2, lang: "python", ok: true, kind: "ok" }] });
  assert.match(parsed, /code-check--ok[^>]*>.*Syntaxe Python valide/);
  assert.doesNotMatch(parsed, /vérifiée/);
  // no verdict from the server (the code did not parse there, or was not sent): no badge at all
  assert.doesNotMatch(renderMarkdown(code, { rich: true, final: true, codeChecks: [] }), /code-check--ok/);
});

test("math: \\[…\\], \\(…\\), $$…$$ and $…$ with TeX become placeholders; prices and code stay text", async () => {
  const { renderMarkdown } = await import("../../birds/web/static/markdown.js");
  const r = (x, o = {}) => renderMarkdown(x, { rich: true, final: true, ...o });
  const block = r("Équation globale :\n\\[\n6\\,CO_2 + 6\\,H_2O \\xrightarrow{\\text{lumière}} C_6H_{12}O_6 + 6\\,O_2\n\\]\nFin.");
  assert.match(block, /<p>Équation globale :<\/p>\n<div class="md-math md-math--block" data-tex="6\\,CO_2 [^"]*O_2" data-display>/);
  assert.match(block, /data-copy-tex/);
  assert.match(block, /<p>Fin\.<\/p>$/);
  const inline = r("Soit \\(x^2 + 1\\), $\\alpha$, $x$ ; 5 $ et 10 $ ; $5 et $10 ; `\\(code\\)`.");
  assert.equal((inline.match(/class="md-math"/g) || []).length, 3);
  assert.match(inline, /5 \$ et 10 \$ ; \$5 et \$10/);
  assert.match(inline, /<code>\\\(code\\\)<\/code>/);
  // the model's TeX is escaped like any text: no tag can come out of a formula
  assert.doesNotMatch(r("\\(<img src=x onerror=alert(1)>\\)"), /<img/);
  assert.doesNotMatch(r('\\["><script>alert(1)</script>\\]'), /<script/);
  // streaming: an unclosed formula shows as written (not typeset yet); a final one without its end is text
  assert.match(r("\\[\na+b", { final: false }), /data-pending/);
  assert.doesNotMatch(r("\\[\na+b"), /md-math/);
  // the plain renderer (tool steps) has no math
  assert.doesNotMatch(renderMarkdown("\\(x\\)"), /md-math/);
});

test("math: the vendored KaTeX renders without inline styles (CSP style-src 'self') and with MathML", async () => {
  const { createRequire } = await import("node:module");
  const require = createRequire(import.meta.url);
  const katex = require("../../birds/web/static/vendor/katex/katex.min.js");
  const { katexHtml, texOf } = await import("../../birds/web/static/answers.js");
  const html = katexHtml(katex, "C_6H_{12}O_6 \\xrightarrow{\\text{lumière}} \\frac{a}{b}", true);
  assert.doesNotMatch(html, / style="/);
  assert.match(html, /data-kx-style="/);
  assert.match(html, /<math[^>]*>[\s\S]*<annotation encoding="application\/x-tex">/);
  assert.throws(() => katexHtml(katex, "\\frac{", false));
  // trust is off: no link or class can be injected through TeX
  assert.doesNotMatch(katexHtml(katex, "\\href{javascript:alert(1)}{x}", false), /<a /);
  const fake = (tex, display) => ({ getAttribute: () => tex, hasAttribute: () => display });
  assert.equal(texOf(fake("x^2", false)), "$x^2$");
  assert.equal(texOf(fake("E=mc^2", true)), "$$E=mc^2$$");
});

test("the citation bubble reads the source card, never the model's text", async () => {
  const { citeFacts } = await import("../../birds/web/static/answers.js");
  const q = (map) => (sel) => (map[sel] === undefined ? null : map[sel]);
  const item = {
    querySelector: q({
      ".source-body > a": { textContent: " Artemis II ", href: "https://fr.wikipedia.org/wiki/Artemis_II" },
      ".source-n": { textContent: "1" },
      ".source-host > span:not(.source-mono):not(.badge)": { textContent: "fr.wikipedia.org · 2 avr. 2026" },
      ".source-snippet": { textContent: "Mission habitée autour de la Lune." },
    }),
  };
  assert.deepEqual(citeFacts(item), {
    n: "1",
    title: "Artemis II",
    url: "https://fr.wikipedia.org/wiki/Artemis_II",
    host: "fr.wikipedia.org · 2 avr. 2026",
    snippet: "Mission habitée autour de la Lune.",
  });
});

test("rich copy: real headings, lists and one table with its header row; no interface chrome; plain text alongside", async () => {
  const { serialize } = await import("../../birds/web/static/answers.js");
  const T = (text) => ({ text });
  const E = (tag, children = [], attrs = {}) => ({ tag, attrs, children });
  // the shape treeOf() gives for a rendered answer (sortable header buttons unwrapped, chrome already dropped)
  const tree = E("div", [
    E("h3", [T("Les 3 plus grandes villes")]),
    E("p", [T("Paris est "), E("strong", [T("la plus peuplée")]), T(" [1].")]),
    E("div", [E("table", [
      E("thead", [E("tr", [E("th", [E("button", [T("Ville")])]), E("th", [E("button", [T("Population")])], { align: "right" })])]),
      E("tbody", [E("tr", [E("td", [T("Paris")]), E("td", [T("2 102 650")], { align: "right" })]),
        E("tr", [E("td", [T("Marseille")]), E("td", [T("877 215")], { align: "right" })])]),
    ])]),
    E("ul", [E("li", [T("un")]), E("li", [T("deux "), E("code", [T("x<y")])])]),
    E("pre", [E("code", [T("print('ok')\nprint(2)")])]),
  ]);
  const { html, text } = serialize(tree);
  assert.match(html, /^<meta charset="utf-8"><h3>Les 3 plus grandes villes<\/h3><p>Paris est <strong>la plus peuplée<\/strong> \[1\]\.<\/p>/);
  assert.match(html, /<table border="1"[^>]*><thead><tr><th align="left"[^>]*>Ville<\/th><th align="left"[^>]*>Population<\/th><\/tr><\/thead>/);
  assert.match(html, /<td valign="top" align="right">2 102 650<\/td>/);
  assert.doesNotMatch(html, /style=/); // the page's CSP would strip it on copy
  assert.equal((html.match(/<table/g) || []).length, 1);
  assert.doesNotMatch(html, /<button|<div|class=|<script|onerror/);
  assert.match(html, /<code>x&lt;y<\/code>/);
  assert.equal(
    text,
    "Les 3 plus grandes villes\n\nParis est la plus peuplée [1].\n\n| Ville | Population |\n| --- | --- |\n| Paris | 2 102 650 |\n| Marseille | 877 215 |\n\n- un\n- deux x<y\n\nprint('ok')\nprint(2)",
  );
  // a link keeps only an http(s) address
  assert.equal(serialize(E("div", [E("p", [E("a", [T("x")], { href: "https://e.org/a" })])])).html, '<meta charset="utf-8"><p><a href="https://e.org/a">x</a></p>');
});

test("thumbs down: known reasons only, a short plain comment, French and English labels", async () => {
  const { REASONS, cleanFeedback } = await import("../../birds/web/static/answers.js");
  const d = cleanFeedback({ reasons: ["wrong", "wrong", "<script>", "long"], comment: `  trop\n\nlong  ${"x".repeat(900)}` }, 7);
  assert.deepEqual(d.reasons, ["wrong", "long"]);
  assert.ok(d.comment.startsWith("trop long ") && d.comment.length === 500);
  assert.equal(d.at, 7);
  assert.deepEqual(cleanFeedback(null, 1), { reasons: [], comment: "", at: 1 });
  for (const lang of ["fr", "en"])
    for (const r of REASONS) assert.ok(ANSWER_STRINGS[lang][`fb.r.${r}`], `${lang} fb.r.${r}`);
});
