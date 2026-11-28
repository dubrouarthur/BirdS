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
