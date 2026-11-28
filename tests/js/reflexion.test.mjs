// Mode Réflexion, pure part (reflexion-data.js) and its strings (reflexion-i18n.js). Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import * as R from "../../birds/web/static/reflexion-data.js";
import { REFLEXION_STRINGS } from "../../birds/web/static/reflexion-i18n.js";

test("five birds and Auto, each with its own drawing", () => {
  assert.deepEqual(R.LEVELS, ["colibri", "hirondelle", "faucon", "chouette", "albatros"]);
  assert.deepEqual(R.CHOICES, ["auto", ...R.LEVELS]);
  const drawn = new Set();
  for (const k of R.CHOICES) {
    assert.ok(/<path/.test(R.BIRDS[k]), k);
    assert.ok(!/<script|on\w+=|href/i.test(R.BIRDS[k]), k); // constants, no script or link
    drawn.add(R.BIRDS[k]);
  }
  assert.equal(drawn.size, 6);
});

test("choices are normalised and only the hummingbird skips reasoning", () => {
  assert.equal(R.normalizeChoice("faucon"), "faucon");
  assert.equal(R.normalizeChoice("x"), "auto");
  assert.equal(R.normalizeChoice(undefined), "auto");
  assert.equal(R.thinks("colibri"), false);
  for (const k of ["auto", "hirondelle", "faucon", "chouette", "albatros"]) assert.equal(R.thinks(k), true, k);
});

test("facts say only what the server checked", () => {
  assert.deepEqual(R.flightFacts(null), []);
  assert.deepEqual(R.flightFacts({ level: "nope" }), []);
  assert.deepEqual(R.flightFacts({ level: "colibri", checks: {} }).map((f) => f.key), ["rf.fact.instant"]);
  const ok = R.flightFacts({ level: "faucon", checks: { calcs: 3, calc_wrong: 0, points: 2, missing: 0 } });
  assert.deepEqual(ok.map((f) => f.key), ["rf.fact.calc.ok.n", "rf.fact.points.ok"]);
  const fixed = R.flightFacts({ level: "faucon", corrected: true, checks: { calcs: 2, calc_wrong: 0 } });
  assert.equal(fixed[0].key, "rf.fact.calc.fixed");
  const warn = R.flightFacts({ level: "chouette", checks: { calcs: 2, calc_wrong: 1, points: 3, missing: 1 }, reviewed: true, cut: "repetition" });
  assert.deepEqual(warn.map((f) => f.kind), ["warn", "warn", "ok", "info"]);
  assert.equal(R.flightFacts({ level: "hirondelle", checks: {}, cut: "think_budget" })[0].key, "rf.fact.cut.budget");
});

test("meta names the level and who chose it", () => {
  assert.deepEqual(R.flightMetaKeys({ level: "faucon", auto: true }), ["rf.level.faucon.label", "rf.by.bird"]);
  assert.deepEqual(R.flightMetaKeys({ level: "faucon", auto: false }), ["rf.level.faucon.label", "rf.by.you"]);
  assert.deepEqual(R.flightMetaKeys({ level: "albatros", source: "crew" }), ["rf.level.albatros.label", "rf.by.crew"]);
  assert.deepEqual(R.flightMetaKeys({ level: "faucon", auto: true, source: "demo" }), ["rf.level.faucon.label", "rf.by.demo"]);
});

test("every string in French and English, every key used exists", () => {
  const fr = Object.keys(REFLEXION_STRINGS.fr).sort();
  assert.deepEqual(Object.keys(REFLEXION_STRINGS.en).sort(), fr);
  for (const k of R.CHOICES) for (const s of ["", ".label", ".hint"]) assert.ok(fr.includes(`rf.level.${k}${s}`), k + s);
  const rf = { level: "chouette", corrected: true, reviewed: true, review_changed: true, cut: "think_budget",
    checks: { calcs: 1, calc_wrong: 1, points: 2, missing: 1 } };
  for (const f of [...R.flightFacts(rf), ...R.flightFacts({ ...rf, checks: { calcs: 1 }, corrected: false })])
    assert.ok(fr.includes(f.key), f.key);
  for (const k of ["rf.by.bird", "rf.by.you", "rf.by.crew", "rf.flight", "rf.flying", "rf.fact.points.fixed"]) assert.ok(fr.includes(k), k);
  assert.equal(REFLEXION_STRINGS.fr["rf.flight"], "Bird a pris son vol en {bird}");
});
