// Footprint data and arithmetic: sourced constants, emissions, water, equivalents, totals, fr/en units.
// Pure module (no DOM, no storage of its own): footprint.js draws it, tests/js/footprint.test.mjs checks it.
// Every constant carries its source, year and licence; nothing here is a guess. See docs/WEB.md, « Empreinte ».

/** Grid carbon intensity, g CO2e per kWh, life cycle (the same scope for all three). */
export const GRIDS = {
  fr: {
    g_per_kwh: 29.0,
    year: 2025,
    source: "RTE, Bilan électrique 2025", // life cycle; 19.6 g counting direct emissions only
    url: "https://analysesetdonnees.rte-france.com/en/annual-review-2025/keyfindings",
    licence: "cite",
  },
  eu: {
    g_per_kwh: 213,
    year: 2024,
    source: "Ember, European Electricity Review 2025", // EU-27
    url: "https://ember-energy.org/latest-insights/european-electricity-review-2025/five-years-of-progress/",
    licence: "cc-by",
  },
  world: {
    g_per_kwh: 473,
    year: 2024,
    source: "Ember, Global Electricity Review 2025",
    url: "https://ember-energy.org/latest-insights/global-electricity-review-2025/global-electricity-trends/",
    licence: "cc-by",
  },
};
export const GRID_ORDER = ["fr", "eu", "world"];

/** Water: the only published per-prompt ratio with its method (0.26 mL for 0.24 Wh, whole service, Aug 2025). */
export const WATER = {
  ml_per_wh: 0.26 / 0.24,
  year: 2025,
  source: "Google, Measuring the environmental impact of AI inference (2025)", // 0.26 mL for 0.24 Wh
  url: "https://arxiv.org/abs/2508.15734",
  licence: "cite",
};

/** Large assistants, per text prompt, whole-service boundary. `method`: "published" (with a method) or "stated". */
export const REFERENCES = [
  {
    key: "published",
    wh: 0.24,
    method: "published",
    date: "2025-08",
    url: "https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference",
  },
  {
    key: "stated",
    wh: 0.34,
    method: "stated",
    date: "2025-06",
    url: "https://blog.samaltman.com/the-gentle-singularity",
  },
];

const IMPACT_CO2 = "ADEME, Impact CO2 (Base Empreinte), 2026"; // factors read on impactco2.fr in November 2026
const IMPACT_CO2_LICENCE = "ademe"; // reuse with ADEME named as the source (impactco2.fr legal notice)

/**
 * Everyday equivalents. `per`: "g" (g CO2e for one unit, life cycle: device, network, data centres) or "wh" (energy
 * for one unit, so independent of the grid). `unit` tells how an amount is written (duration, distance, count).
 */
export const EQUIVALENTS = [
  {
    key: "streaming",
    per: "g",
    value: 64.0, // g CO2e for 1 hour
    unit: "hour",
    source: IMPACT_CO2,
    url: "https://impactco2.fr/outils/usagenumerique/streamingvideo",
    licence: IMPACT_CO2_LICENCE,
  },
  {
    key: "car",
    per: "g",
    value: 142.3, // g CO2e for 1 km, construction included (ADEME hypothesis: average, diesel)
    unit: "km",
    source: IMPACT_CO2,
    url: "https://impactco2.fr/outils/transport/voiturethermique",
    licence: IMPACT_CO2_LICENCE,
  },
  {
    key: "search",
    per: "g",
    value: 1.23, // g CO2e for 1 web search
    unit: "count",
    source: IMPACT_CO2,
    url: "https://impactco2.fr/outils/usagenumerique",
    licence: IMPACT_CO2_LICENCE,
  },
  {
    key: "email",
    per: "g",
    value: 2.46, // g CO2e for 1 email
    unit: "count",
    source: IMPACT_CO2,
    url: "https://impactco2.fr/outils/usagenumerique/email",
    licence: IMPACT_CO2_LICENCE,
  },
  {
    key: "phone",
    per: "wh",
    value: 19, // Wh for 1 full smartphone charge (0.019 kWh)
    unit: "count",
    source: "US EPA, Greenhouse Gas Equivalencies Calculator (2026)",
    url: "https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator-calculations-and-references",
    licence: "public",
  },
];

// ------------------------------------------------------------------ arithmetic

export const hasEnergy = (u) =>
  !!u &&
  typeof u.energy_wh === "number" &&
  (u.energy_kind === "measured" || u.energy_kind === "estimated");

/** The grid in use: an explicit choice, else the operator's (BIRD_GRID_INTENSITY), else France. */
export function pickGrid(choice, operatorG) {
  const operator = typeof operatorG === "number" && operatorG >= 0;
  if (choice === "operator" && operator)
    return { key: "operator", g_per_kwh: operatorG };
  if (GRIDS[choice]) return { key: choice, ...GRIDS[choice] };
  if (operator) return { key: "operator", g_per_kwh: operatorG };
  return { key: "fr", ...GRIDS.fr };
}

/** g CO2e from Wh and g CO2e/kWh. */
export const grams = (wh, gPerKwh) =>
  ((Number(wh) || 0) / 1000) * (Number(gPerKwh) || 0);
export const water = (wh) => (Number(wh) || 0) * WATER.ml_per_wh;

/** Time the graphics card worked on the answer: generation streams when reported, else the answer's time. */
export function gpuSeconds(u) {
  const busy = Number(u?.busy_seconds);
  if (busy > 0) return busy;
  return Math.max(0, Number(u?.generation_seconds) || Number(u?.seconds) || 0);
}

/** One answer's figures. The range comes from the token estimate; a measurement is its own range. */
export function answerFigures(u, grid) {
  if (!hasEnergy(u)) return null;
  const wh = u.energy_wh;
  const b = u.energy_basis || {};
  const low = typeof b.low_wh === "number" ? b.low_wh : wh;
  const high = typeof b.high_wh === "number" ? b.high_wh : wh;
  const g = grid.g_per_kwh;
  return {
    wh,
    low,
    high,
    kind: u.energy_kind,
    g: grams(wh, g),
    gLow: grams(low, g),
    gHigh: grams(high, g),
    ml: water(wh),
    gpuS: gpuSeconds(u),
    tokensIn: Number(u.prompt_tokens) || 0,
    tokensOut: Number(u.completion_tokens) || 0,
  };
}

/** Amount of each equivalent for `wh` (and the grams it emits on `grid`), exactly: amount = impact / factor. */
export function equivalents(wh, grid) {
  const g = grams(wh, grid.g_per_kwh);
  return EQUIVALENTS.map((e) => {
    const amount = (e.per === "wh" ? wh : g) / e.value;
    return { ...e, amount, answersPerUnit: amount > 0 ? 1 / amount : Infinity };
  });
}

/** Sums over answers that carry energy; `n` counts every answer, `energyN` those with an energy figure. */
export function sumUsages(usages) {
  const out = {
    n: 0,
    energyN: 0,
    wh: 0,
    low: 0,
    high: 0,
    tokensIn: 0,
    tokensOut: 0,
    gpuS: 0,
    measured: true,
  };
  for (const u of usages || []) {
    if (!u) continue;
    out.n += 1;
    out.tokensIn += Number(u.prompt_tokens) || 0;
    out.tokensOut += Number(u.completion_tokens) || 0;
    out.gpuS += gpuSeconds(u);
    if (!hasEnergy(u)) continue;
    const b = u.energy_basis || {};
    out.energyN += 1;
    out.wh += u.energy_wh;
    out.low += typeof b.low_wh === "number" ? b.low_wh : u.energy_wh;
    out.high += typeof b.high_wh === "number" ? b.high_wh : u.energy_wh;
    if (u.energy_kind !== "measured") out.measured = false;
  }
  if (!out.energyN) out.measured = false;
  return out;
}

/**
 * « Had you used a large assistant »: the same number of answers at the reference's per-prompt figure. Saved =
 * reference - Bird, with its range (reference - Bird's high bound .. reference - Bird's low bound); may be negative.
 */
export function versus(sum, ref) {
  const refWh = sum.energyN * ref.wh;
  return {
    refWh,
    saved: refWh - sum.wh,
    savedLow: refWh - sum.high,
    savedHigh: refWh - sum.low,
    ratio: sum.wh > 0 ? refWh / sum.wh : null,
    // the ratio at Bird's high bound (worst case) and low bound (best case): the headline never hides its range
    ratioLow: sum.high > 0 ? refWh / sum.high : null,
    ratioHigh: sum.low > 0 ? refWh / sum.low : null,
  };
}

// ------------------------------------------------------------------ device totals (kept beyond the 400-answer ledger)

export const TOTALS_KEY = "bird.footprint.totals";
const EMPTY = () => ({
  n: 0,
  energyN: 0,
  wh: 0,
  low: 0,
  high: 0,
  tokensIn: 0,
  tokensOut: 0,
  gpuS: 0,
});

/** Running totals on this device: `real` answers and scripted `demo` ones kept apart. `kv`: {get, set} strings. */
export function readTotals(kv) {
  let t = null;
  try {
    t = JSON.parse(kv.get(TOTALS_KEY) || "null");
  } catch {
    t = null;
  }
  if (!t || t.v !== 1)
    return { v: 1, since: null, real: EMPTY(), demo: EMPTY() };
  return {
    v: 1,
    since: t.since ?? null,
    real: { ...EMPTY(), ...t.real },
    demo: { ...EMPTY(), ...t.demo },
  };
}

export function recordTotals(kv, u, now = Date.now()) {
  if (!u || typeof u.prompt_tokens !== "number") return readTotals(kv);
  const t = readTotals(kv);
  const bucket = u.tokens_kind === "scripted" ? t.demo : t.real;
  const s = sumUsages([u]);
  for (const k of Object.keys(EMPTY())) bucket[k] += s[k];
  t.since ??= now;
  kv.set(TOTALS_KEY, JSON.stringify(t));
  return t;
}

export const resetTotals = (kv) => kv.set(TOTALS_KEY, null);

// ------------------------------------------------------------------ units, fr / en

const LOCALE = { fr: "fr-FR", en: "en-GB" };
const NB = " "; // no-break space between a number and its unit
const nf = (lang, digits) =>
  new Intl.NumberFormat(LOCALE[lang] || LOCALE.fr, {
    maximumSignificantDigits: digits,
  });
export const num = (v, lang, digits = 2) => nf(lang, digits).format(v);
export const int = (v, lang) =>
  new Intl.NumberFormat(LOCALE[lang] || LOCALE.fr, {
    maximumFractionDigits: 0,
  }).format(Math.round(v));

/** 0,052 Wh · 1,3 Wh · 0,4 mWh · 12 kWh */
export function fmtWh(wh, lang) {
  const v = Math.max(0, Number(wh) || 0);
  if (v >= 1000) return `${num(v / 1000, lang, 3)}${NB}kWh`;
  if (v >= 1) return `${num(v, lang, 3)}${NB}Wh`;
  if (v >= 0.001) return `${num(v, lang)}${NB}Wh`;
  if (v >= 0.00001) return `${num(v * 1000, lang)}${NB}mWh`;
  return `<${NB}${num(0.01, lang)}${NB}mWh`;
}

/** 3,2 µg CO₂e · 1,5 mg CO₂e · 0,42 g CO₂e · 3,1 kg CO₂e */
export function fmtGrams(g, lang) {
  const v = Math.max(0, Number(g) || 0);
  const co2 = `${NB}CO₂e`;
  if (v >= 1000) return `${num(v / 1000, lang, 3)}${NB}kg${co2}`;
  if (v >= 1) return `${num(v, lang, 3)}${NB}g${co2}`;
  if (v >= 0.001) return `${num(v * 1000, lang)}${NB}mg${co2}`;
  if (v > 0) return `${num(Math.max(v * 1e6, 0.01), lang)}${NB}µg${co2}`;
  return `0${NB}g${co2}`;
}

/** 0,054 mL · 12 mL · 1,2 L */
export function fmtWater(ml, lang) {
  const v = Math.max(0, Number(ml) || 0);
  if (v >= 1000) return `${num(v / 1000, lang, 3)}${NB}L`;
  if (v >= 1) return `${num(v, lang, 3)}${NB}mL`;
  if (v >= 0.001) return `${num(v, lang)}${NB}mL`;
  return `<${NB}${num(0.001, lang)}${NB}mL`;
}

/** 80 ms · 3,2 s · 4 min 05 s · 1 h 05 min */
export function fmtDuration(s, lang) {
  const v = Math.max(0, Number(s) || 0);
  if (v < 1) return `${num(Math.max(v * 1000, 0.01), lang)}${NB}ms`;
  if (v < 60) return `${num(v, lang)}${NB}s`;
  const whole = Math.round(v);
  if (whole < 3600) {
    const sec = String(whole % 60).padStart(2, "0");
    return `${Math.floor(whole / 60)}${NB}min${NB}${sec}${NB}s`;
  }
  const mins = Math.round(v / 60);
  return `${Math.floor(mins / 60)}${NB}h${NB}${String(mins % 60).padStart(2, "0")}${NB}min`;
}

/** 0,4 mm · 1,3 cm · 85 m · 2,4 km */
export function fmtDistance(m, lang) {
  const v = Math.max(0, Number(m) || 0);
  if (v >= 1000) return `${num(v / 1000, lang)}${NB}km`;
  if (v >= 1) return `${num(v, lang)}${NB}m`;
  if (v >= 0.01) return `${num(v * 100, lang)}${NB}cm`;
  return `${num(Math.max(v * 1000, 0.01), lang)}${NB}mm`;
}

/** The amount of an equivalent, written in its own unit: duration, distance or a plain count (2 digits). */
export function fmtAmount(e, lang) {
  if (e.unit === "hour") return fmtDuration(e.amount * 3600, lang);
  if (e.unit === "km") return fmtDistance(e.amount * 1000, lang);
  return num(e.amount, lang);
}

/** « 1 for N answers »: N rounded to 2 significant digits, so a count never looks more precise than its inputs. */
export const fmtPerUnit = (e, lang) => int(Number(e.answersPerUnit.toPrecision(2)), lang);
