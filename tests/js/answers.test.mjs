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
