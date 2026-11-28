// Unit tests of the canvas's pure logic: the mini-sheet formulas, sort, chart and CSV (canvas-sheet.js), the
// flowchart parser (canvas-flow.js) and the FR/EN parity of the canvas strings. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import * as sheet from "../../birds/web/static/canvas-sheet.js";
import { layoutFlow, parseFlow, wrapLabel } from "../../birds/web/static/canvas-flow.js";
import { CANVAS_STRINGS } from "../../birds/web/static/canvas-i18n.js";

test("formulas: arithmetic, ranges, functions in French and English, errors", () => {
  const rows = [
    ["Poste", "Montant", "TVA"],
    ["A", "1 200,50", "=B2*20%"],
    ["B", "800", "=B3*0,2"],
    ["Total", "=SOMME(B2:B3)", "=SUM(C2:C3)"],
    ["Moy", "=MOYENNE(B2:B3)", "=ARRONDI(C4/3;2)"],
    ["Si", '=SI(B4>1000;"gros";"petit")', "=B9/0"],
    ["Cycle", "=C7", "=B7"],
    ["Nom", "=FOO(1)", "=1+"],
  ];
  const v = sheet.compute(rows);
  assert.equal(v[1][1], 1200.5);
  assert.ok(Math.abs(v[1][2] - 240.1) < 1e-9);
  assert.equal(v[3][1], 2000.5);
  assert.ok(Math.abs(v[3][2] - 400.1) < 1e-9);
  assert.equal(v[4][1], 1000.25);
  assert.equal(v[4][2], 133.37);
  assert.equal(v[5][1], "gros");
  assert.equal(v[5][2], "#DIV/0!");
  assert.equal(v[6][1], "#CYCLE!");
  assert.equal(v[7][1], "#NOM?");
  assert.equal(v[7][2], "#ERREUR");
  assert.ok(sheet.isError(v[6][1]) && !sheet.isError("#hashtag"));
});

test("formulas never run code", () => {
  const v = sheet.compute([["=constructor.constructor('return 1')()", "=alert(1)", "=A1:B2"]]);
  assert.ok(v[0].every((x) => sheet.isError(x)));
});

test("sort keeps rows whole and puts empty cells last", () => {
  const rows = [["b", "3"], ["a", ""], ["c", "1"]];
  const out = sheet.sortRows(rows, sheet.compute(rows), 1, 1);
  assert.deepEqual(out, [["c", "1"], ["b", "3"], ["a", ""]]);
  assert.deepEqual(sheet.sortRows(rows, sheet.compute(rows), 0, -1).map((r) => r[0]), ["c", "b", "a"]);
});

test("chart from a selection: labels then numeric series", () => {
  const rows = [["2023", "10", "x"], ["2024", "12", "y"], ["2025", "15", "z"]];
  const spec = sheet.chartFrom(["Année", "CA", "Note"], sheet.compute(rows), { r0: 0, r1: 2, c0: 0, c1: 2 }, "CA");
  assert.equal(spec.type, "line");
  assert.deepEqual(spec.columns, ["Année", "CA"]);
  assert.deepEqual(spec.rows, [["2023", 10], ["2024", 12], ["2025", 15]]);
  assert.equal(sheet.chartFrom(["a", "b"], [["x", "y"]], { r0: 0, r1: 0, c0: 0, c1: 1 }), null);
});

test("CSV cannot inject formulas", () => {
  const csv = sheet.toCsv(["a", "b"], [["=cmd|' /C calc'!A0", 12.5], ["@SUM(1)", "+1"], ["-x", "ok"]]);
  assert.ok(csv.includes(`"'=cmd|' /C calc'!A0"`) || csv.includes("'=cmd"));
  assert.ok(csv.includes("'@SUM(1)") && csv.includes("'+1") && csv.includes("'-x"));
  assert.ok(csv.includes("12,5"));
});

test("selection as a Markdown table, pipes escaped", () => {
  const md = sheet.selectionMarkdown(["A", "B"], [["x|y", 2]], { r0: 0, r1: 0, c0: 0, c1: 1 });
  assert.equal(md, "| A | B |\n|---|---|\n| x\\|y | 2 |");
});

test("flowchart: shapes, labels, chains, comments, back edges", () => {
  const f = parseFlow(`flowchart LR
    %% a comment
    A[Demande reçue] --> B{Complète ?}
    B -->|oui| C(Analyse) --> D((Fin))
    B -- non --> E[Relance]
    E -.-> B
    classDef x fill:#f00
    F[<b>gras</b>]`);
  assert.equal(f.dir, "LR");
  assert.deepEqual(f.nodes.map((n) => [n.id, n.shape]), [["A", "rect"], ["B", "diamond"], ["C", "round"], ["D", "circle"], ["E", "rect"], ["F", "rect"]]);
  assert.equal(f.nodes.find((n) => n.id === "F").label, "gras"); // markup dropped, text kept
  assert.deepEqual(f.edges.map((e) => `${e.from}>${e.to}:${e.label}`), ["A>B:", "B>C:oui", "C>D:", "B>E:non", "E>B:"]);
  assert.ok(f.edges.at(-1).dashed);
  const { layers } = layoutFlow(f);
  assert.deepEqual(layers[0], ["A", "F"]);
  assert.ok(layers.findIndex((l) => l.includes("E")) > layers.findIndex((l) => l.includes("B")));
});

test("flowchart: garbage never throws", () => {
  for (const s of ["", "flowchart", "-->", "A[", "{{{", "A-->", "x".repeat(5000), "A --> B --> C --> A"]) parseFlow(s);
  const many = parseFlow(Array.from({ length: 100 }, (_, i) => `N${i} --> N${i + 1}`).join("\n"));
  assert.ok(many.nodes.length <= 60);
  assert.deepEqual(wrapLabel("un deux trois quatre cinq six sept huit neuf dix onze douze", 10).length, 4);
});

test("canvas strings: same keys in French and English", () => {
  assert.deepEqual(Object.keys(CANVAS_STRINGS.fr).sort(), Object.keys(CANVAS_STRINGS.en).sort());
});
