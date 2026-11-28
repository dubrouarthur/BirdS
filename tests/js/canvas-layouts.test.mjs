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
