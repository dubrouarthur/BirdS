// The page plan of a Word-like document (canvas-doc.js), the same as birds/canvas/docx_out.outline: heading and
// figure numbers per template, footnotes numbered by first call. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import { footnotes, look, numbering } from "../../birds/web/static/canvas-doc.js";

const DOC = {
  kind: "doc",
  template: "cadrage",
  blocks: [
    { id: "b1", title: "Contexte", parts: [{ t: "text", text: "Trois outils[^b]." }, { t: "heading", level: 2, text: "Situation" }] },
    { id: "b2", title: "Objectifs", parts: [{ t: "image", media: "w1" }, { t: "image" }, { t: "chart", rows: [] }] },
    { id: "b3", title: "Risques", parts: [{ t: "list", items: ["Coût[^a]", "Délai[^b]"] }] },
  ],
  footnotes: [{ n: "a", text: "Note A" }, { n: "b", text: "Note B" }, { n: "z", text: "Jamais appelée" }],
};

test("look: the template's flags, a default for an unknown one", () => {
  assert.deepEqual(
    { ...look(DOC), name: undefined },
    { template: "cadrage", name: undefined, cover: true, toc: true, numbered: true, letter: false },
  );
  assert.equal(look({ template: "x", blocks: [] }).template, "rapport");
  assert.equal(look({ template: "lettre", blocks: [{}, {}, {}] }).toc, false);
  assert.equal(look({ template: "compte-rendu", blocks: [] }).numbered, false);
});

test("numbering: « 1. », « 1.1 », figures only for placed pictures and charts", () => {
  const n = numbering(DOC);
  assert.deepEqual(n.heads, { b1: "1.", b2: "2.", b3: "3." });
  assert.equal(n.subs.get(DOC.blocks[0].parts[1]), "1.1");
  const [img, pending, chart] = DOC.blocks[1].parts;
  assert.equal(n.figs.get(img), 1);
  assert.equal(n.figs.get(pending), undefined);
  assert.equal(n.figs.get(chart), 2);
  assert.deepEqual(numbering({ ...DOC, template: "compte-rendu" }).heads, { b1: "", b2: "", b3: "" });
});

test("footnotes: numbered by first call, then the ones never called", () => {
  assert.deepEqual(
    footnotes(DOC).map((x) => [x.key, x.n]),
    [["b", 1], ["a", 2], ["z", 3]],
  );
});
