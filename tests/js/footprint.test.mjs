// Unit tests of the footprint data and arithmetic (footprint-data.js) and its strings. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import * as F from "../../birds/web/static/footprint-data.js";
import { FOOTPRINT_STRINGS } from "../../birds/web/static/footprint-i18n.js";
import { STRINGS } from "../../birds/web/static/i18n.js";

const NB = " ";
const strip = (s) => s.replaceAll(NB, " ").replaceAll(" ", " ");
const usage = (over = {}) => ({
  prompt_tokens: 1500,
  completion_tokens: 500,
  tokens_kind: "counted",
  seconds: 6,
  busy_seconds: 4.2,
  energy_wh: 0.059,
  energy_kind: "estimated",
  energy_basis: { low_wh: 0.024, high_wh: 0.71 },
  ...over,
});

// ------------------------------------------------------------------ sourced constants

test("every grid, water, reference and equivalent carries a value, a year or date, an https source and a licence", () => {
  for (const [key, g] of Object.entries(F.GRIDS)) {
    assert.ok(g.g_per_kwh > 0 && g.year >= 2024 && g.source && /^https:\/\//.test(g.url), key);
    assert.ok(FOOTPRINT_STRINGS.fr[`footprint.licence.${g.licence}`], key);
  }
  assert.deepEqual(F.GRID_ORDER, ["fr", "eu", "world"]);
  assert.ok(F.GRIDS.fr.g_per_kwh < F.GRIDS.eu.g_per_kwh && F.GRIDS.eu.g_per_kwh < F.GRIDS.world.g_per_kwh);
  assert.ok(/^https:\/\//.test(F.WATER.url) && Math.abs(F.WATER.ml_per_wh - 0.26 / 0.24) < 1e-12);
  assert.deepEqual(F.REFERENCES.map((r) => [r.key, r.wh]), [["published", 0.24], ["stated", 0.34]]);
  for (const e of F.EQUIVALENTS) {
    assert.ok(e.value > 0 && ["g", "wh"].includes(e.per) && ["hour", "km", "count"].includes(e.unit), e.key);
    assert.ok(e.source && /^https:\/\//.test(e.url) && FOOTPRINT_STRINGS.en[`footprint.licence.${e.licence}`], e.key);
    assert.ok(FOOTPRINT_STRINGS.fr[`footprint.method.eq.${e.key}`], e.key);
  }
});

// ------------------------------------------------------------------ emissions

test("emissions = energy x grid intensity, France by default, the operator's grid when set", () => {
  assert.equal(F.grams(1000, 29), 29); // 1 kWh x 29 g/kWh
  assert.equal(F.grams(0.059, 473), 0.059 / 1000 * 473);
  assert.equal(F.pickGrid(null, null).key, "fr");
  assert.equal(F.pickGrid("world", null).g_per_kwh, 473);
  assert.deepEqual(F.pickGrid(null, 52), { key: "operator", g_per_kwh: 52 });
  assert.equal(F.pickGrid("operator", null).key, "fr"); // stale choice, operator grid gone
  assert.equal(F.pickGrid("eu", 52).key, "eu"); // the viewer's explicit choice wins
});

test("an answer's figures: range from the token estimate, water, graphics-card time", () => {
  const f = F.answerFigures(usage(), F.pickGrid("fr"));
  assert.equal(f.g, 0.059 / 1000 * 29);
  assert.equal(f.gLow, 0.024 / 1000 * 29);
  assert.equal(f.gHigh, 0.71 / 1000 * 29);
  assert.equal(f.ml, 0.059 * F.WATER.ml_per_wh);
  assert.equal(f.gpuS, 4.2);
  assert.equal(F.answerFigures(usage({ energy_wh: null, energy_kind: null }), F.pickGrid()), null);
  // measured: no basis, so the range collapses on the value
  const m = F.answerFigures(usage({ energy_kind: "measured", energy_basis: null }), F.pickGrid());
  assert.equal(m.low, m.wh);
  assert.equal(F.gpuSeconds({ seconds: 3 }), 3);
});

test("equivalents are exact quotients of the source factors", () => {
  const grid = F.pickGrid("world");
  const wh = 2;
  const g = (wh / 1000) * 473;
  const byKey = Object.fromEntries(F.equivalents(wh, grid).map((e) => [e.key, e]));
  assert.equal(byKey.streaming.amount, g / 64.0);
  assert.equal(byKey.car.amount, g / 142.3);
  assert.equal(byKey.email.amount, g / 2.46);
  assert.equal(byKey.search.amount, g / 1.23);
  assert.equal(byKey.phone.amount, wh / 19); // energy: the grid does not matter
  assert.equal(F.equivalents(wh, F.pickGrid("fr")).find((e) => e.key === "phone").amount, wh / 19);
  assert.equal(byKey.email.answersPerUnit, 1 / byKey.email.amount);
});

// ------------------------------------------------------------------ totals and comparison

test("sums and « had you used a large assistant », with an honest range", () => {
  const s = F.sumUsages([usage(), usage({ energy_wh: 0.041, energy_basis: { low_wh: 0.02, high_wh: 0.5 } }), usage({ energy_wh: null, energy_kind: null })]);
  assert.equal(s.n, 3);
  assert.equal(s.energyN, 2);
  assert.equal(s.wh, 0.059 + 0.041);
  assert.equal(s.low, 0.024 + 0.02);
  assert.equal(s.high, 0.71 + 0.5);
  assert.equal(s.tokensOut, 1500);
  const v = F.versus(s, F.REFERENCES[0]);
  assert.equal(v.refWh, 2 * 0.24);
  assert.equal(v.saved, 0.48 - 0.1);
  assert.equal(v.savedLow, 0.48 - 1.21); // negative: the worst case is said, not hidden
  assert.equal(v.savedHigh, 0.48 - 0.044);
  assert.equal(v.ratio, 0.48 / 0.1);
});

test("device totals persist, keep demo answers apart, survive bad storage and reset", () => {
  const mem = new Map();
  const kv = { get: (k) => mem.get(k) ?? null, set: (k, v) => (v === null ? mem.delete(k) : mem.set(k, v)) };
  assert.equal(F.readTotals(kv).since, null);
  F.recordTotals(kv, usage(), 1000);
  F.recordTotals(kv, usage(), 2000);
  F.recordTotals(kv, usage({ tokens_kind: "scripted" }), 3000);
  F.recordTotals(kv, { nonsense: true });
  const t = F.readTotals(kv);
  assert.equal(t.since, 1000);
  assert.equal(t.real.n, 2);
  assert.equal(t.real.wh, 0.118);
  assert.equal(t.real.gpuS, 8.4);
  assert.equal(t.demo.n, 1);
  // what is stored is JSON a second reader can use
  assert.equal(JSON.parse(mem.get(F.TOTALS_KEY)).real.tokensIn, 3000);
  mem.set(F.TOTALS_KEY, "{broken");
  assert.equal(F.readTotals(kv).real.n, 0);
  F.recordTotals(kv, usage(), 5000);
  F.resetTotals(kv);
  assert.equal(mem.has(F.TOTALS_KEY), false);
});

// ------------------------------------------------------------------ units, fr / en

test("units in French and English, never « 0 », with no-break spaces", () => {
  assert.equal(F.fmtWh(0.059, "fr"), `0,059${NB}Wh`);
  assert.equal(F.fmtWh(0.059, "en"), `0.059${NB}Wh`);
  assert.equal(F.fmtWh(1.234, "fr"), `1,23${NB}Wh`);
  assert.equal(F.fmtWh(0.0004, "fr"), `0,4${NB}mWh`);
  assert.equal(F.fmtWh(2500, "en"), `2.5${NB}kWh`);
  assert.equal(strip(F.fmtWh(0, "fr")), "< 0,01 mWh");
  assert.equal(F.fmtGrams(0.00171, "fr"), `1,7${NB}mg${NB}CO₂e`);
  assert.equal(F.fmtGrams(0.00066, "en"), `660${NB}µg${NB}CO₂e`);
  assert.equal(F.fmtGrams(12.34, "en"), `12.3${NB}g${NB}CO₂e`);
  assert.equal(F.fmtGrams(3100, "fr"), `3,1${NB}kg${NB}CO₂e`);
  assert.equal(F.fmtWater(0.064, "fr"), `0,064${NB}mL`);
  assert.equal(F.fmtWater(1500, "en"), `1.5${NB}L`);
  assert.equal(F.fmtDuration(0.11, "fr"), `110${NB}ms`);
  assert.equal(F.fmtDuration(4.2, "en"), `4.2${NB}s`);
  assert.equal(strip(F.fmtDuration(245, "fr")), "4 min 05 s");
  assert.equal(strip(F.fmtDuration(59.6, "fr")), "60 s");
  assert.equal(strip(F.fmtDuration(3899, "en")), "1 h 05 min");
  assert.equal(F.fmtDistance(0.014, "fr"), `1,4${NB}cm`);
  assert.equal(F.fmtDistance(0.004, "fr"), `4${NB}mm`);
  assert.equal(F.fmtDistance(2400, "en"), `2.4${NB}km`);
});

test("equivalent amounts: a duration, a distance, or « 1 X ≈ N answers » rounded to 2 digits", () => {
  const [streaming, car, , email] = F.equivalents(0.059, F.pickGrid("fr"));
  assert.equal(strip(F.fmtAmount(streaming, "fr")), "96 ms"); // 0.059 Wh x 29 g/kWh / 64 g per hour
  assert.equal(strip(F.fmtAmount(car, "en")), "1.2 cm");
  assert.equal(strip(F.fmtPerUnit(email, "fr")), "1 400"); // 2.46 / 0.001711 = 1 437.7 -> 1 400
  assert.equal(F.fmtPerUnit(email, "en"), "1,400");
});

test("footprint strings: French and English parity, footprint.* prefix, same placeholders", () => {
  const fr = FOOTPRINT_STRINGS.fr;
  const en = FOOTPRINT_STRINGS.en;
  assert.deepEqual(Object.keys(fr).sort(), Object.keys(en).sort());
  const vars = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  for (const k of Object.keys(fr)) {
    assert.ok(k.startsWith("footprint."), k);
    assert.deepEqual(vars(fr[k]), vars(en[k]), k);
  }
  // the brand rules: a graphics card is explained, never counted or named; no base model; no training energy figure
  const all = Object.values(fr).join(" ") + Object.values(en).join(" ");
  assert.doesNotMatch(all, /\b(L4|A10G|H100|NVIDIA|Qwen|Llama)\b/i);
  assert.doesNotMatch(all, /\b(deux|trois|two|three|\d+) (cartes|GPUs?|graphics cards)\b/i);
});

test("brand rules on every UI string: no card model, no card count (the receipt and Empreinte panels included)", () => {
  // about.built.p is the open-source licence notice (Apache 2.0 asks for the original work to be named)
  const shown = (lang) =>
    Object.entries({ ...STRINGS[lang], ...FOOTPRINT_STRINGS[lang] })
      .filter(([k]) => k !== "about.built.p")
      .map(([k, v]) => `${k}: ${v}`);
  for (const line of [...shown("fr"), ...shown("en")]) {
    assert.doesNotMatch(line, /\b(L4|L40S?|A10G?|A100|H100|H200|T4|NVIDIA|Qwen|Llama)\b/i, line);
    assert.doesNotMatch(line, /\b(deux|trois|two|three|\d+) (cartes|GPUs?|graphics cards)\b/i, line);
  }
});
