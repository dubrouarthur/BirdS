// Deep research wording (birds/web/static/research.js): the plural is chosen by the count, never « (s) ».
import assert from "node:assert/strict";
import { test } from "node:test";

import { state } from "../../birds/web/static/core.js";
import { tn } from "../../birds/web/static/research.js";

test("counts choose their form: French 0 and 1 singular, English 1 only", () => {
  state.prefs.lang = "fr";
  assert.equal(tn("rs.q.claims", 1), "1 affirmation");
  assert.equal(tn("rs.q.claims", 0), "0 affirmation");
  assert.equal(tn("rs.q.claims", 2), "2 affirmations");
  assert.equal(tn("rp.n.claims", 2), "2 affirmations vérifiées");
  assert.equal(tn("rp.n.read", 1), "1 page lue");
  assert.equal(tn("rs.stat.sources", 1), "source retenue");
  state.prefs.lang = "en";
  assert.equal(tn("rs.q.claims", 1), "1 claim");
  assert.equal(tn("rs.q.claims", 0), "0 claims");
  assert.equal(tn("rp.n.claims", 2), "2 claims checked");
  assert.equal(tn("rp.vs", 0), "against");
  state.prefs.lang = "fr";
});
