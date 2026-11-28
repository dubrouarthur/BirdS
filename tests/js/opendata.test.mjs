// Unit tests of the open-data cards' pure parts (opendata.js): strings in both languages, the month grid, the
// tender countdown, the next asks and the plain-text copy. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import { state } from "../../birds/web/static/core.js";
import {
  OPENDATA_STRINGS,
  calendarAsks,
  chartSourceText,
  daysLeft,
  monthWeeks,
  opendataText,
  tt,
} from "../../birds/web/static/opendata.js";

state.prefs.lang = "fr";

test("French first, English parity: the same keys, no empty string, the same placeholders", () => {
  const fr = OPENDATA_STRINGS.fr;
  const en = OPENDATA_STRINGS.en;
  assert.deepEqual(Object.keys(fr).sort(), Object.keys(en).sort());
  for (const k of Object.keys(fr)) {
    assert.ok(fr[k] && en[k], k);
    const vars = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
    assert.equal(vars(fr[k]), vars(en[k]), k);
  }
});

test("the month grid starts on Monday and pads full weeks (May 2027 starts on a Saturday)", () => {
  const weeks = monthWeeks(2027, 5);
  assert.equal(weeks.length, 6);
  assert.ok(weeks.every((w) => w.length === 7));
  assert.equal(weeks[0].findIndex(Boolean), 5);
  assert.equal(weeks[0][5].d, "2027-05-01");
  assert.equal(weeks.flat().filter(Boolean).length, 31);
});

test("tender countdown in calendar days, negative once closed", () => {
  const today = new Date(2026, 10, 28);
  assert.equal(daysLeft("2026-12-15", today), 17);
  assert.equal(daysLeft("2026-11-28T12:00:00", today), 0);
  assert.equal(daysLeft("2026-11-20", today), -8);
  assert.equal(daysLeft("", today), null);
});

test("next asks of a calendar card: the following year or month, and the zone when it is not mainland France", () => {
  state.prefs.lang = "fr";
  const year = calendarAsks({ mode: "year", year: 2027, zone: { code: "metropole" }, holidays: [{ d: "2027-01-01" }] });
  assert.deepEqual(year, ["Jours fériés 2028", "Combien de jours ouvrés en janvier 2027 ?"]);
  const dec = calendarAsks({ mode: "month", year: 2027, month: 12, zone: { code: "DE", label: "Allemagne" } });
  assert.deepEqual(dec, ["Jours fériés 2027 Allemagne", "Combien de jours ouvrés en janvier 2028 ?"]);
  state.prefs.lang = "en";
  assert.deepEqual(calendarAsks({ mode: "year", year: 2027, zone: { code: "DE", label: "Germany" }, holidays: [] }), [
    "Public holidays 2028 in Germany",
    "How many working days in May 2027?",
  ]);
  state.prefs.lang = "fr";
});

test("plain-text copy carries the data and the source with its licence", () => {
  const src = { source: { label: "BOAMP / DILA", url: "https://boamp.fr" }, license: { label: "Licence Ouverte 2.0" } };
  const tenders = opendataText({ type: "tenders", items: [{ title: "Nettoyage", url: "https://x.fr/a", buyer: "Ville" }], ...src });
  assert.equal(tenders, "1. Nettoyage — Ville\nDonnées : BOAMP / DILA (Licence Ouverte 2.0)");
  const md = opendataText({ type: "tenders", items: [{ title: "Nettoyage", url: "https://x.fr/a" }], ...src }, true);
  assert.match(md, /^1\. \[Nettoyage\]\(https:\/\/x\.fr\/a\)/);
  const unsafe = opendataText({ type: "papers", items: [{ title: "T", url: "javascript:alert(1)" }], ...src }, true);
  assert.doesNotMatch(unsafe, /javascript:/);
  assert.equal(opendataText({ type: "weather" }), "");
  assert.equal(chartSourceText({ label: "Eurostat", dataset: "une_rt_a", license: "CC BY 4.0" }), "Données : Eurostat (une_rt_a) · CC BY 4.0");
  assert.equal(tt("ten.left", { n: 3 }), "J-3");
});
