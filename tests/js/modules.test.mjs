// Unit tests of the small modules (modules.js) and the follow-up chips (followups.js): pure functions only.
// Run: node --test tests/js/*.mjs  (pytest runs it too: tests/test_modules_web.py).
import assert from "node:assert/strict";
import { test } from "node:test";

import { state } from "../../birds/web/static/core.js";
import { calcCompute, checklistMarkdown, layoutGraph, parseCell, sortRows } from "../../birds/web/static/modules.js";
import * as followups from "../../birds/web/static/followups.js";
import { chipItems, cleanSuggestions, hasNumericTable, suggestions, transforms } from "../../birds/web/static/followups.js";

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
  // a connected graph stays spread once the forces cool (the centre pull used to fold it onto the centre)
  const ring = ["e0", "e1", "e2", "e3", "e4", "e5", "e6"].map((id) => ({ id }));
  const links = [["e1", "e0"], ["e2", "e3"], ["e4", "e5"], ["e3", "e6"], ["e6", "e5"], ["e2", "e6"]].map(([s, t]) => ({ s, t }));
  const p = layoutGraph(ring, links, { width: 640, height: 360 });
  const ids = Object.keys(p);
  let near = Infinity;
  for (let i = 0; i < ids.length; i++)
    for (let j = i + 1; j < ids.length; j++)
      near = Math.min(near, Math.hypot(p[ids[i]][0] - p[ids[j]][0], p[ids[i]][1] - p[ids[j]][1]));
  assert.ok(near > 45, `nodes too close: ${near}`);
  // a graph that grows: the nodes already placed start where they were and stay near
  const seed = new Map([["e0", [100, 100]], ["e1", [180, 100]]]);
  const q = layoutGraph(ring, links, { width: 640, height: 360, iterations: 140, seed });
  assert.ok(Math.hypot(q.e0[0] - 100, q.e0[1] - 100) < 160);
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

test("Bird's question is never cut into chips any more (the bug of « Vous aide à intégrer… »)", () => {
  assert.equal(followups.clarifyOptions, undefined);
  const answer = { content: "Voici la diapositive.\n\nSouhaitez-vous que je vous aide à intégrer des images spécifiques ou à structurer la diapositive visuellement ?" };
  assert.deepEqual(chipItems(answer), []); // without Bird's own next steps: nothing, rather than fragments
  const withNext = { ...answer, suggestions: [
    { label: "Ajoute des images à la diapositive", prompt: "Ajoute des images libres de droits à la diapositive." },
    { label: "Structure la diapo en 3 blocs", prompt: "Structure la diapositive en trois blocs visuels." },
  ] };
  assert.deepEqual(chipItems(withNext).map((c) => [c.label, c.kind]), [
    ["Ajoute des images à la diapositive", "next"], ["Structure la diapo en 3 blocs", "next"]]);
});

test("Bird's next steps: cleaned (strings, lengths, three at most, no duplicate), widget chips fill in", () => {
  const long = "Compare les trois offres sur le prix et la durée d'engagement";
  const got = cleanSuggestions([
    { label: long, prompt: "Compare les trois offres." },
    { label: "compare les trois offres", prompt: "Compare les trois offres !" },
    { label: "", prompt: "x" }, null, "texte", { label: 3, prompt: {} },
    { label: "Rédige le mail", prompt: "Rédige le mail d'annonce." },
    { label: "Fais un tableau", prompt: "Fais un tableau." }, { label: "Quatrième", prompt: "Quatrième." },
  ]);
  assert.equal(got.length, 3);
  assert.ok(got[0].label.length <= 42 && got[0].label.endsWith("…"));
  assert.deepEqual(cleanSuggestions("nope"), []);
  const weather = { widgets: [{ type: "weather", day: "aujourd'hui" }], suggestions: [
    { label: "Prévois une tenue adaptée", prompt: "Que faut-il prévoir comme tenue pour demain à Lyon ?" }] };
  assert.deepEqual(chipItems(weather).map((c) => c.kind), ["next", "follow", "follow"]);
  const dup = { widgets: [{ type: "weather", day: "aujourd'hui" }], suggestions: [{ label: "Et demain ?", prompt: "et demain ?" }] };
  assert.deepEqual(chipItems(dup).map((c) => c.label), ["Et demain ?", "Restaurants autour"]);
});

test("transforms: six one-click requests", () => {
  const tf = transforms();
  assert.equal(tf.length, 6);
  assert.equal(tf[0][1], "Raccourcis ta réponse précédente.");
});
