// Unit tests of the task plan checklist state (plan.js): what is kept from a server event, and what a screen
// reader hears when an item gets ticked. Run: node --test tests/js/*.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { cleanPlan, planNews } from "../../birds/web/static/plan.js";
import { state } from "../../birds/web/static/core.js";

state.prefs.lang = "fr";

const event = (statuses, extra = {}) => ({
  type: "plan",
  items: [
    { kind: "table", label: "tableau", status: statuses[0] },
    { kind: "totals", label: "totaux", status: statuses[1] },
    { kind: "mail", label: "mail", status: statuses[2] },
  ],
  done: statuses.filter((s) => s === "done").length,
  total: 3,
  ...extra,
});

test("a plan of one item, or a malformed one, is not shown", () => {
  assert.equal(cleanPlan(null), null);
  assert.equal(cleanPlan({ items: "x" }), null);
  assert.equal(cleanPlan({ items: [{ label: "mail", status: "todo" }] }), null);
});

test("unknown statuses become « to do », labels are capped, at most 8 items", () => {
  const items = Array.from({ length: 12 }, (_, i) => ({ label: `x${i}`.repeat(30), status: i ? "weird" : "done" }));
  const plan = cleanPlan({ items });
  assert.equal(plan.items.length, 8);
  assert.equal(plan.items[0].status, "done");
  assert.equal(plan.items[1].status, "todo");
  assert.ok(plan.items[0].label.length <= 60);
});

test("only newly done items are announced", () => {
  const a = cleanPlan(event(["todo", "todo", "todo"]));
  const b = cleanPlan(event(["done", "todo", "todo"]));
  const c = cleanPlan(event(["done", "done", "done"]));
  assert.equal(planNews(null, a), "");
  assert.equal(planNews(a, b), "Fait : tableau");
  assert.equal(planNews(b, c), "Fait : totaux, mail");
  assert.equal(planNews(c, c), "");
});

test("a final partial plan keeps what is missing", () => {
  const p = cleanPlan(event(["done", "done", "todo"], { final: true, partial: true, missing: ["mail"] }));
  assert.equal(p.final, true);
  assert.equal(p.partial, true);
  assert.deepEqual(p.missing, ["mail"]);
});

test("the head is ticked only when every item is done (« 0 sur 2 faites » after an error is not)", async () => {
  const { planHead } = await import("../../birds/web/static/plan.js");
  const two = (a, b, extra = {}) => cleanPlan({ items: [{ label: "tableau", status: a }, { label: "mail", status: b }], ...extra });
  assert.equal(planHead(two("todo", "todo"), "running").icon, null);
  assert.equal(planHead(two("todo", "todo"), "error").icon, "alert");
  assert.equal(planHead(two("todo", "todo"), "error").partial, true);
  assert.equal(planHead(two("done", "todo"), "done").icon, "alert");
  assert.equal(planHead(two("done", "done", { final: true }), "done").icon, "check");
  assert.equal(planHead(two("done", "todo"), "stopped").icon, null);
  assert.equal(planHead(two("done", "done", { final: true, partial: true }), "done").icon, "alert");
});
