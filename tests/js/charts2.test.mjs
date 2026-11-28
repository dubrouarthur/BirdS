// Rendering snapshots of the v2 charts (charts2.js) and of the data card (datakit.js) under Node, with the tiny DOM
// of tests/fixtures/fakedom.mjs. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import { install } from "../fixtures/fakedom.mjs";

const document = install();
document.createElementNS = (_ns, tag) => document.createElement(tag);
globalThis.getComputedStyle = () => ({ fontFamily: "sans-serif", getPropertyValue: () => "" });
globalThis.CustomEvent = class {};
// what fakedom does not have and the charts use: prepend / replaceWith, and a click that bubbles to the svg
const proto = Object.getPrototypeOf(document.createElement("div"));
proto.prepend = function (...nodes) {
  const old = this.childNodes;
  this.childNodes = [];
  this.append(...nodes);
  for (const c of old) this.childNodes.push(c);
};
proto.replaceWith = function (node) {
  const p = this.parentNode;
  if (!p) return;
  const i = p.childNodes.indexOf(this);
  node.remove?.();
  node.parentNode = p;
  p.childNodes[i] = node;
  this.parentNode = null;
};
const setAttr = proto.setAttribute;
proto.setAttribute = function (k, v) {
  setAttr.call(this, k, v);
  if (k === "class") this.className = String(v); // SVG elements get their classes as an attribute
};
proto.dispatchEvent = function () {
  return true;
};
Object.defineProperty(proto, "clientWidth", { get: () => 600 });
Object.defineProperty(proto, "offsetWidth", { get: () => 100 });

const { renderChart2, chartCsv, chartMarkdown2, fmtValue, niceTicks, CHART_TYPES } = await import("../../birds/web/static/charts2.js");
const { renderDataCard } = await import("../../birds/web/static/datakit.js");
const { state } = await import("../../birds/web/static/core.js");
state.prefs.lang = "fr";

const all = (el, cls) => el.querySelectorAll(`.${cls}`);
const texts = (el) => el._all().filter((e) => e.tagName === "TEXT").map((e) => e.textContent);
const base = { v: 2, title: "T", unit: "€", source: "analysis", x: { name: "Région", kind: "category" }, annotations: [] };
const bars = { ...base, type: "bar", labels: ["Nord", "Sud", "Est"], series: [{ name: "CA", values: [120, 99.5, 80] }] };

test("number formatting is French by default, English on demand", () => {
  assert.equal(fmtValue(1234.5, "€", "fr"), "1 234,5 €".replace(",5", ",5").replace("1 234,5", new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(1234.5)));
  assert.equal(fmtValue(12.5, "%", "en"), "12.5%");
  assert.equal(fmtValue(null, "€", "fr"), "—");
  assert.deepEqual(niceTicks(0, 243), [0, 50, 100, 150, 200, 250]);
});

test("every type draws marks and a stable structure (snapshot)", () => {
  const specs = {
    bar: bars,
    stacked: { ...bars, type: "stacked", series: [{ name: "A", values: [1, 2, 3] }, { name: "B", values: [3, 2, 1] }] },
    hbar: { ...bars, type: "hbar" },
    line: { ...bars, type: "line", labels: ["janv.", "févr.", "mars", "avr."], series: [{ name: "CA", values: [1, 3, 2, 4] }], annotations: [{ kind: "max" }] },
    area: { ...bars, type: "area", labels: ["a", "b", "c"] },
    stacked_area: { ...bars, type: "stacked_area", series: [{ name: "A", values: [1, 2, 3] }, { name: "B", values: [3, 2, 1] }] },
    scatter: { ...base, type: "scatter", labels: [], series: [], points: [["a", 1, 2], ["b", 2, 4], ["c", 3, 5]], axes: ["x", "y"], stat: { r: 0.99, n: 3 } },
    bubble: { ...base, type: "bubble", labels: [], series: [], points: [["a", 1, 2, 10], ["b", 2, 4, 40]], axes: ["x", "y"] },
    pie: { ...bars, type: "pie" },
    donut: { ...bars, type: "donut" },
    histogram: { ...base, type: "histogram", labels: [], series: [], bins: { counts: [1, 4, 2], lo: 0, hi: 30 } },
    box: { ...base, type: "box", labels: [], series: [], box: { min: 1, q1: 2, median: 3, mean: 3.2, q3: 4, max: 9, outliers: [9] } },
    heatmap: { ...bars, type: "heatmap", series: [{ name: "Matin", values: [1, 2, 3] }, { name: "Soir", values: [3, 2, 1] }] },
    waterfall: { ...bars, type: "waterfall", series: [{ name: "Δ", values: [100, -30, -20] }] },
    funnel: { ...bars, type: "funnel", series: [{ name: "N", values: [100, 40, 10] }] },
    combo: { ...bars, type: "combo", series: [{ name: "CA", values: [1, 2, 3], mark: "bar" }, { name: "Marge", values: [30, 31, 35], unit: "%", mark: "line", axis: "y2" }] },
    kpi: { ...bars, type: "kpi", kpi: { value: 502602, label: "CA 2025", spark: [1, 3, 2] } },
  }; // prettier-ignore
  assert.deepEqual(Object.keys(specs).sort(), [...CHART_TYPES].sort());
  const snapshot = {};
  for (const [type, spec] of Object.entries(specs)) {
    const card = renderChart2(spec, { lang: "fr" });
    assert.ok(card, type);
    const svg = card.querySelector("svg");
    assert.ok(svg && svg.getAttribute("viewBox"), `${type}: an svg with a viewBox`);
    snapshot[type] = all(card, "c2-mark").length;
  }
  assert.deepEqual(snapshot, {
    bar: 3, stacked: 6, hbar: 3, line: 4, area: 3, stacked_area: 6, scatter: 3, bubble: 2, pie: 3, donut: 3,
    histogram: 3, box: 1, heatmap: 6, waterfall: 4, funnel: 3, combo: 6, kpi: 0,
  }); // prettier-ignore
});

test("annotations, the type switch and the legend", () => {
  const card = renderChart2({ ...bars, alts: ["bar", "hbar", "donut"], annotations: [{ kind: "target", value: 100, label: "objectif" }] }, { lang: "fr" });
  assert.ok(texts(card).some((t) => t.startsWith("objectif")));
  const types = all(card, "c2-type");
  assert.equal(types.length, 3);
  types[2].click(); // donut
  assert.equal(all(card, "c2-slice").length, 3);
  const multi = renderChart2({ ...bars, series: [{ name: "2024", values: [1, 2, 3] }, { name: "2025", values: [2, 3, 4] }] }, { lang: "fr" });
  const legs = all(multi, "c2-leg");
  assert.equal(legs.length, 2);
  legs[1].click();
  assert.equal(all(multi, "c2-leg")[1].getAttribute("aria-pressed"), "false"); // redrawn, the series is off
  assert.equal(all(multi, "c2-mark").length, 3);
});

test("export text: CSV with ; and decimal commas, Markdown table", () => {
  assert.equal(chartCsv(bars, "fr"), "Région;CA\nNord;120\nSud;99,5\nEst;80");
  assert.match(chartMarkdown2(bars, "fr"), /\| Région \| CA \|\n\| --- \| --- \|\n\| Nord \| 120\s€ \|/);
});

test("a click on a bar fills the composer with « Détaille … »", () => {
  const input = document.createElement("textarea");
  input.id = "composer-input";
  input.value = "";
  input.setSelectionRange = () => {};
  document.body.append(input);
  const card = renderChart2(bars, { lang: "fr" });
  card.querySelectorAll("[data-hit]")[1].click();
  assert.match(input.value, /^Détaille « Sud »/);
  input.remove();
});

test("data card: header, column chips, analyses and the table", () => {
  const card = {
    type: "datacard", id: "d1", name: "ventes.csv", origin: "pasted", rows: 3, cols: 2, complete: 1, lang: "fr", meta: { separator: ";" },
    columns: [
      { name: "Région", type: "category", count: 3, missing: 0, distinct: 3, top: [["Nord", 1], ["Sud", 1], ["Est", 1]] },
      { name: "CA (€)", type: "number", unit: "€", count: 3, missing: 0, distinct: 3, stats: { sum: 299.5, mean: 99.8, min: 80, max: 120, median: 99.5 }, hist: [1, 0, 2] },
    ],
    sample: [["Nord", 120], ["Sud", 99.5], ["Est", 80]], totals: [{ count: 3 }, { sum: 299.5 }], complete_rows: true,
    suggestions: [{ id: "by", label: "Total par région", icon: "bar", result: { title: "T", kind: "ranking", columns: ["Région", "CA (€)"], rows: [["Nord", 120]], unit: "€" }, chart: bars }],
  }; // prettier-ignore
  const el = renderDataCard(card);
  assert.ok(el.textContent.includes("3 lignes × 2 colonnes"), el.textContent.slice(0, 200));
  assert.equal(all(el, "dk-col").length, 2);
  assert.equal(all(el, "dk-chip").length, 1);
  assert.equal(all(el, "c2-card").length, 1); // the first analysis is open at once
  assert.ok(el.textContent.includes("299,5"), "the totals row sums the measure");
});
