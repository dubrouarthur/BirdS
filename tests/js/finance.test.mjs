// Unit tests of the quote card's pure parts (finance.js): strings in both languages, price and change formatting
// (a sign and an arrow, never colour alone), the dated delay line, the period chips' asks, the sparkline, the
// contrast of the up/down colours in both themes (finance.css), and the plain-text copy. Run: node --test tests/js/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { state } from "../../birds/web/static/core.js";
import {
  FINANCE_STRINGS,
  asofLine,
  direction,
  fmtPct,
  fmtPrice,
  quoteText,
  rangeAsk,
  sparkPoints,
} from "../../birds/web/static/finance.js";

state.prefs.lang = "fr";
const nbsp = (s) => s.replace(/[  ]/g, " ");

test("French first, English parity: the same keys, no empty string, the same placeholders", () => {
  const { fr, en } = FINANCE_STRINGS;
  assert.deepEqual(Object.keys(fr).sort(), Object.keys(en).sort());
  for (const k of Object.keys(fr)) {
    assert.ok(fr[k] && en[k], k);
    const vars = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
    assert.equal(vars(fr[k]), vars(en[k]), k);
  }
});

test("a change is said with a sign and a direction, flat under half a hundredth of a point", () => {
  assert.equal(nbsp(fmtPct(0.83244)), "+0,83 %");
  assert.equal(nbsp(fmtPct(-1.2)), "−1,20 %");
  assert.equal(nbsp(fmtPct(0)), "0,00 %");
  assert.equal(direction(0.83), "up");
  assert.equal(direction(-0.01), "down");
  assert.equal(direction(0.004), "flat");
  assert.equal(direction(null), "flat");
  state.prefs.lang = "en";
  assert.equal(fmtPct(2.5), "+2.50%");
  state.prefs.lang = "fr";
});

test("prices in their currency: 2 decimals, 4 under 10 (a rate), none from 10 000", () => {
  assert.equal(nbsp(fmtPrice(358.54001, "USD", "equity")), "358,54 $US");
  assert.equal(nbsp(fmtPrice(54436, "EUR", "crypto")), "54 436 €");
  assert.equal(nbsp(fmtPrice(1.0957, "USD", "fx")), "1,0957");
  assert.equal(fmtPrice(undefined, "EUR", "equity"), "—");
});

test("the figure is always dated with its delay, never « temps réel »", () => {
  assert.equal(asofLine({ asof_kind: "close", asof: "2026-11-27" }), "Clôture du 27 novembre 2026 · pas en temps réel");
  assert.equal(
    asofLine({ asof_kind: "live", asof: "2026-11-28T09:13Z" }),
    "Cours du 28 novembre 2026 à 09:13 UTC · différé de quelques minutes",
  );
  assert.match(asofLine({ asof_kind: "reference", asof: "2026-11-27" }), /^Taux de référence BCE du 27 novembre 2026/);
  state.prefs.lang = "en";
  assert.equal(asofLine({ asof_kind: "close", asof: "2026-11-27" }), "Close of 27 November 2026 · not real time");
  state.prefs.lang = "fr";
});

test("a period chip sends an ask the harness reads as the same quote (« cours de » for a share)", () => {
  const shares = { items: [{ name: "LVMH", kind: "equity" }, { name: "Hermès", kind: "equity" }] };
  assert.equal(rangeAsk(shares, "5y"), "cours de LVMH et Hermès sur 5 ans");
  assert.equal(rangeAsk({ items: [{ name: "Bitcoin", kind: "crypto" }] }, "1m"), "Bitcoin sur 1 mois");
  state.prefs.lang = "en";
  assert.equal(rangeAsk({ items: [{ name: "Apple", kind: "equity" }] }, "1y"), "Apple stock over 1 year");
  state.prefs.lang = "fr";
});

test("sparkline points fit the box, the highest close on top", () => {
  const pts = sparkPoints([1, 3, 2], 120, 32, 2).split(" ").map((p) => p.split(",").map(Number));
  assert.equal(pts.length, 3);
  assert.deepEqual(pts[0], [2, 30]);
  assert.deepEqual(pts[1], [60, 2]);
  assert.equal(pts[2][0], 118);
  assert.equal(sparkPoints([5]), "");
});

// WCAG relative luminance and contrast ratio
const lum = (hex) => {
  const c = hex.match(/[0-9a-f]{2}/gi).map((x) => parseInt(x, 16) / 255);
  const l = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

test("up, down and flat keep 4.5:1 on the card surface in light and dark", () => {
  const css = readFileSync(new URL("../../birds/web/static/finance.css", import.meta.url), "utf8");
  const app = readFileSync(new URL("../../birds/web/static/app.css", import.meta.url), "utf8");
  const light = css.split("@media")[0];
  const dark = css.split(':root[data-theme="dark"]')[1];
  const surfLight = app.match(/:root \{[^}]*?--surface: (#[0-9a-f]{6})/i)[1];
  const surfDark = app.split(':root[data-theme="dark"]')[1].match(/--surface: (#[0-9a-f]{6})/i)[1];
  for (const name of ["up", "down", "flat"]) {
    const l = light.match(new RegExp(`--mkt-${name}: (#[0-9a-f]{6})`, "i"))[1];
    const d = dark.match(new RegExp(`--mkt-${name}: (#[0-9a-f]{6})`, "i"))[1];
    assert.ok(ratio(l, surfLight) >= 4.5, `${name} light ${ratio(l, surfLight)}`);
    assert.ok(ratio(d, surfDark) >= 4.5, `${name} dark ${ratio(d, surfDark)}`);
  }
});

test("the plain-text copy keeps the figure, its date, the source and its licence", () => {
  const w = {
    advice: true,
    items: [{ name: "Bitcoin", last: 54436, currency: "EUR", kind: "crypto", change_pct: -3.25,
              change_base: "24h", asof_kind: "live", asof: "2026-11-28T09:13Z" }],
    sources: [{ label: "CoinGecko", license: "Données fournies par CoinGecko, attribution requise" }],
  };
  const txt = nbsp(quoteText(w));
  assert.match(txt, /^Bitcoin : 54 436 € \(−3,25 % sur 24 h\) — Cours du 28 novembre 2026 à 09:13 UTC/);
  assert.match(txt, /pas un conseil en investissement/);
  assert.match(txt, /CoinGecko \(Données fournies par CoinGecko, attribution requise\)$/);
});
