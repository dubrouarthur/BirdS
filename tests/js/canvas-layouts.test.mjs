// The browser's layout choice equals the Python one (birds/canvas/layouts.py) on the shared fixture: the canvas
// preview and the exported .pptx draw each slide the same way.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pick, compatible, NAMES } from "../../birds/web/static/canvas-layouts.js";

const cases = JSON.parse(
  readFileSync(new URL("../fixtures/canvas_layouts.json", import.meta.url), "utf8"),
);

test("the fixture covers every layout", () => {
  const seen = new Set(cases.map((c) => c.layout));
  for (const n of NAMES) assert.ok(seen.has(n), n);
});

test("same layout and same choices as the Python catalogue", () => {
  for (const c of cases) {
    const where = `${c.note} #${c.index} ${c.block.title}`;
    assert.equal(pick(c.block, c.index, c.total), c.layout, where);
    assert.deepEqual(compatible(c.block), c.fits, where);
  }
});

test("the deck's size line says « 1 mise en page », never « 1 mises en page » (FR and EN)", async () => {
  const { sizeKey } = await import("../../birds/web/static/canvas-layouts.js");
  const { CANVAS_STRINGS } = await import("../../birds/web/static/canvas-i18n.js");
  const fill = (lang, n, layouts) =>
    CANVAS_STRINGS[lang][sizeKey(n, layouts)].replace("{n}", n).replace("{layouts}", layouts);
  assert.equal(fill("fr", 3, 1), "3 diapositives · 1 mise en page");
  assert.equal(fill("fr", 1, 1), "1 diapositive · 1 mise en page");
  assert.equal(fill("fr", 7, 4), "7 diapositives · 4 mises en page");
  assert.equal(fill("en", 3, 1), "3 slides · 1 layout");
  assert.equal(fill("en", 1, 1), "1 slide · 1 layout");
});
