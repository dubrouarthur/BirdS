// Unit tests of the small modules (modules.js) and the follow-up chips (followups.js): pure functions only.
// Run: node --test tests/js/*.mjs  (pytest runs it too: tests/test_modules_web.py).
import assert from "node:assert/strict";
import { test } from "node:test";

import { state } from "../../birds/web/static/core.js";
import { calcCompute, checklistMarkdown, layoutGraph, parseCell, sortRows } from "../../birds/web/static/modules.js";
import { clarifyOptions, hasNumericTable, suggestions, transforms } from "../../birds/web/static/followups.js";

state.prefs.lang = "fr";

test("graph layout: deterministic, inside the box, linked nodes closer than unlinked ones", () => {
  const nodes = ["a", "b", "c", "d", "e", "f"].map((id) => ({ id }));
  const edges = [{ s: "a", t: "b" }, { s: "b", t: "c" }, { s: "d", t: "e" }];
  const p1 = layoutGraph(nodes, edges, { width: 640, height: 400 });
  const p2 = layoutGraph(nodes, edges, { width: 640, height: 400 });
  assert.deepEqual(p1, p2);
  for (const [x, y] of Object.values(p1)) assert.ok(x >= 40 && x <= 600 && y >= 24 && y <= 376);
  const d = (u, v) => Math.hypot(p1[u][0] - p1[v][0], p1[u][1] - p1[v][1]);
  assert.ok(d("a", "b") < d("a", "f") && d("d", "e") < d("d", "f"));
  assert.deepEqual(Object.keys(layoutGraph([{ id: "x" }], [])), ["x"]);
});

test("matrix sort: numbers when every row has one, French formats read", () => {
  assert.equal(parseCell("1 450 €"), 1450);
  assert.equal(parseCell("4,5"), 4.5);
  assert.equal(parseCell("—"), null);
  const rows = [["A", "120 €"], ["B", "1 095 €"], ["C", "95 €"]];
  assert.deepEqual(sortRows(rows, 1, "asc"), [2, 0, 1]);
  assert.deepEqual(sortRows(rows, 1, "desc"), [1, 0, 2]);
  assert.deepEqual(sortRows([["b"], ["a"], ["c"]], 0), [1, 0, 2]);
});

test("calculator: the browser recomputes with the harness's formulas", () => {
  const loan = calcCompute({ kind: "loan" }, { principal: 200000, years: 20, rate: 3.5 });
  assert.equal(loan.payment.toFixed(2), "1159.92");
  assert.equal(loan.interest.toFixed(2), "78380.66");
  const vat = calcCompute({ kind: "vat", base: "ttc" }, { amount: 1440, rate: 20 });
  assert.equal(vat.ht.toFixed(2), "1200.00");
  assert.equal(calcCompute({ kind: "unit", dim: "temp", from: "°C", to: "°F" }, { value: 30 }).result, 86);
  assert.equal(calcCompute({ kind: "unit", dim: "len", factor: "1.609344" }, { value: 5 }).result.toFixed(4), "8.0467");
  assert.equal(calcCompute({ kind: "margin" }, { cost: 80, price: 120 }).rate.toFixed(2), "33.33");
  assert.equal(calcCompute({ kind: "change", down: true }, { base: 89.9, pct: 15 }).result.toFixed(3), "76.415");
});

test("checklist export keeps ticks, owners and due dates", () => {
  const w = { items: [{ text: "Planning", owner: "Thomas", due: "21/10" }, { text: "Devis" }] };
  assert.equal(checklistMarkdown(w, [true, false]), "- [x] Planning — Thomas (21/10)\n- [ ] Devis");
});

test("follow-up chips depend on what the answer is", () => {
  const weather = suggestions({ widgets: [{ type: "weather", day: "demain" }] });
  assert.deepEqual(weather.map((s) => s.prompt), ["et après-demain ?", "et des restaurants autour ?"]);
  const places = suggestions({ widgets: [{ type: "places", places: [{ name: "Gare de Lyon" }] }] });
  assert.equal(places[0].prompt, "itinéraire pour aller à Gare de Lyon");
  const mail = suggestions({ draft_email: { to: "a@b.fr" } });
  assert.deepEqual(mail.map((s) => s.label), ["Plus court", "Plus formel", "En anglais"]);
  const table = suggestions({ content: "| Mois | CA |\n|---|---|\n| Janvier | 120 |\n| Février | 135 |" });
  assert.equal(table[0].prompt, "mets ça sous forme de graphique");
  assert.deepEqual(suggestions({ content: "| Mois | CA |\n|---|---|\n| a | 1 |\n| b | 2 |", charts: [{}] }), []);
  const research = suggestions({ widgets: [
    { type: "research", topic: "hydrogène" },
    { type: "graph", nodes: [{ id: "a", label: "Air Liquide", type: "organisation" }, { id: "b", label: "Paris", type: "lieu" },
      { id: "c", label: "Hysetco", type: "organisation" }], edges: [{ s: "a", t: "c" }, { s: "c", t: "b" }] },
  ] });
  assert.deepEqual(research.map((s) => s.label), ["Approfondir Hysetco", "Approfondir Air Liquide"]);
  assert.equal(research[0].prompt, "Fais une recherche approfondie sur Hysetco");
  assert.deepEqual(suggestions({ content: "Bonjour, voici la réponse." }), []);
  assert.ok(!hasNumericTable("| a | b |\n|---|---|\n| x | y |"));
});

test("clarify chips: only a question Bird asks back with 2 to 4 options", () => {
  assert.deepEqual(clarifyOptions("Je peux le faire.\n\nSouhaitez-vous un mail, une note ou un tableau ?"), ["Un mail", "Une note", "Un tableau"]);
  assert.deepEqual(clarifyOptions("Voulez-vous la version courte ou la version détaillée ?"), ["La version courte", "La version détaillée"]);
  assert.deepEqual(clarifyOptions("Quelle est la date de la réunion ?"), []);
  assert.deepEqual(clarifyOptions("Souhaitez-vous que je continue ?"), []);
  assert.deepEqual(clarifyOptions("Voici le mail. Bonne journée."), []);
});

test("transforms: six one-click requests", () => {
  const tf = transforms();
  assert.equal(tf.length, 6);
  assert.equal(tf[0][1], "Raccourcis ta réponse précédente.");
});
