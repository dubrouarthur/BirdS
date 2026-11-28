// Conversation engine, pure part (conversation-data.js) and its strings (conversation-i18n.js). Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import * as C from "../../birds/web/static/conversation-data.js";
import { CONVERSATION_STRINGS } from "../../birds/web/static/conversation-i18n.js";

const u = (content, extra = {}) => ({ role: "user", content, ...extra });
const a = (content, extra = {}) => ({ role: "assistant", id: `a-${content}`, answer: { content }, ...extra });

test("strings: French and English have the same keys, all under cx.", () => {
  const fr = Object.keys(CONVERSATION_STRINGS.fr).sort();
  const en = Object.keys(CONVERSATION_STRINGS.en).sort();
  assert.deepEqual(fr, en);
  for (const k of fr) {
    assert.ok(k.startsWith("cx."), k);
    assert.ok(CONVERSATION_STRINGS.fr[k].trim() && CONVERSATION_STRINGS.en[k].trim(), k);
    const vars = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
    assert.equal(vars(CONVERSATION_STRINGS.fr[k]), vars(CONVERSATION_STRINGS.en[k]), k);
  }
});

test("R1: documents split into pending, in context and lost", () => {
  const d = C.contextDocs([{ name: "a" }, { name: "b", sent: true }, { name: "c", sent: true, lost: true }, { name: "d", lost: true }]);
  assert.deepEqual(d.pending.map((x) => x.name), ["a"]);
  assert.deepEqual(d.context.map((x) => x.name), ["b"]);
  assert.deepEqual(d.lost.map((x) => x.name), ["c", "d"]);
  assert.deepEqual(C.contextDocs(undefined), { pending: [], context: [], lost: [] });
});

test("R3: a regenerated answer keeps the first one as version 1/2", () => {
  const turns = [u("q1"), a("r1"), u("q2"), a("r2")];
  assert.equal(C.versionInfo(turns, 3), null);
  C.fork(turns, 3, [a("r2b")]);
  assert.deepEqual(turns.map((x) => x.content || x.answer.content), ["q1", "r1", "q2", "r2b"]);
  assert.deepEqual(C.versionInfo(turns, 3), { n: 2, at: 2 });
  assert.ok(C.switchVersion(turns, 3, 0));
  assert.equal(turns[3].answer.content, "r2");
  assert.deepEqual(C.versionInfo(turns, 3), { n: 2, at: 1 });
  assert.equal(C.switchVersion(turns, 3, 0), false); // already shown
  assert.equal(C.switchVersion(turns, 3, 5), false);
  assert.ok(C.switchVersion(turns, 3, 1));
  assert.equal(turns[3].answer.content, "r2b");
});

test("R3/R6: editing an earlier question branches the whole tail and gives it back as it was", () => {
  const turns = [u("q1"), a("r1"), u("q2"), a("r2")];
  C.fork(turns, 3, [a("r2b")]); // a regenerate deeper down
  C.fork(turns, 0, [u("q1 edited"), a("r1 new")]);
  assert.equal(turns.length, 2);
  assert.deepEqual(C.versionInfo(turns, 0), { n: 2, at: 2 });
  C.switchVersion(turns, 0, 0);
  assert.deepEqual(turns.map((x) => x.content || x.answer.content), ["q1", "r1", "q2", "r2b"]);
  assert.deepEqual(C.versionInfo(turns, 3), { n: 2, at: 2 }); // the nested group survived
  C.switchVersion(turns, 0, 1);
  assert.deepEqual(turns.map((x) => x.content || x.answer.content), ["q1 edited", "r1 new"]);
});

test("R3: at most MAX_VERSIONS versions, the first one kept", () => {
  const turns = [u("q"), a("v0")];
  for (let i = 1; i <= C.MAX_VERSIONS + 3; i++) C.fork(turns, 1, [a(`v${i}`)]);
  const g = turns[1].alts;
  assert.equal(g.list.length, C.MAX_VERSIONS);
  assert.equal(g.at, C.MAX_VERSIONS - 1);
  C.switchVersion(turns, 1, 0);
  assert.equal(turns[1].answer.content, "v0");
});

test("R3: mapTree reaches hidden versions; validGroup refuses a broken stored group", () => {
  const turns = [u("q"), a("r1")];
  C.fork(turns, 1, [a("r2")]);
  const seen = [];
  const out = C.mapTree(turns, (x) => (seen.push(x.content || x.answer.content), { ...x }));
  assert.deepEqual(seen.sort(), ["q", "r1", "r2"]);
  assert.ok(C.validGroup(out[1].alts, "assistant"));
  assert.equal(JSON.parse(JSON.stringify(out))[1].alts.list[1], null);
  assert.equal(C.validGroup({ list: [null], at: 0 }, "assistant"), false);
  assert.equal(C.validGroup({ list: [[u("x")], null], at: 1 }, "assistant"), false);
  assert.equal(C.validGroup({ list: [[a("x")], [a("y")]], at: 1 }, "assistant"), false);
});

test("R15: search ignores case and accents and gives a snippet", () => {
  const text = "Bonjour.\nLe plombier dit que la fuite vient du joint sous l'évier, il passe jeudi.";
  const hit = C.findIn(text, "FUITE");
  assert.equal(hit.match, "fuite");
  assert.ok(hit.before.endsWith("que la "));
  assert.ok(hit.after.startsWith(" vient du joint"));
  assert.equal(C.findIn(text, "evier").match, "évier");
  assert.equal(C.findIn(text, "zzz"), null);
  assert.equal(C.findIn(text, "  "), null);
  const conv = { turns: [u("Où est la fuite ?"), a("Sous l'évier."), u("x", { hidden: true })] };
  assert.equal(C.convText(conv), "Où est la fuite ?\nSous l'évier.");
});

test("R14: the proposed title is cleaned and checked, else the fallback", () => {
  assert.equal(C.cleanTitle("« Demande de congé vendredi »", "Écris un mail"), "Demande de congé vendredi");
  assert.equal(C.cleanTitle("Titre : **recette des crêpes**.", "x"), "Recette des crêpes");
  assert.equal(C.cleanTitle("", "fallback"), "fallback");
  assert.equal(C.cleanTitle("ok", "fallback"), "fallback");
  assert.equal(C.cleanTitle("a ".repeat(40), "fallback"), "fallback");
  assert.equal(C.cleanTitle("voir https://x.y", "fallback"), "fallback");
  assert.equal(C.cleanTitle("Budget 2026\nautre ligne", "f"), "Budget 2026");
});

test("R5: kept files are pruned by age, then oldest first to the byte cap", async () => {
  const { planPrune, KEEP_DAYS } = await import("../../birds/web/static/keep.js");
  const now = 1_000 * 86_400_000;
  const rows = [
    { key: "old", at: now - (KEEP_DAYS + 1) * 86_400_000, bytes: 10 },
    { key: "a", at: now - 3, bytes: 60 },
    { key: "b", at: now - 2, bytes: 30 },
    { key: "c", at: now - 1, bytes: 30 },
  ];
  assert.deepEqual(planPrune(rows, now, 100).sort(), ["a", "old"]);
  assert.deepEqual(planPrune(rows, now, 1000), ["old"]);
});
