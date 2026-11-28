// The footprint experience: an answer's impact (inside the receipt, on demand), running totals, the comparison with
// a large assistant, and the « why small models » story on the Empreinte page. Data and arithmetic live in
// footprint-data.js (sourced constants, pure functions); strings in footprint-i18n.js (footprint.* keys).
//
// Mount hooks (the only places other modules call in):
//   turns.js  fullReceipt()     -> footprintAnswer(usage, conv, { onOpenPage })
//   views.js  renderFootprint() -> mountFootprintPage(body, { scope, usages }) ; ledgerAdd() -> recordFootprint(usage)
import { h, state, store, t } from "./core.js";
import * as F from "./footprint-data.js";
import { FOOTPRINT_STRINGS } from "./footprint-i18n.js";
import { STRINGS } from "./i18n.js";

for (const [lang, strings] of Object.entries(FOOTPRINT_STRINGS))
  Object.assign(STRINGS[lang], strings);

const GRID_KEY = "bird.footprint.grid";
const LEDGER_KEY = "bird.ledger"; // views.js owns it; read here only to seed the device totals once
const lang = () => (state.prefs.lang === "en" ? "en" : "fr");
const operatorG = () => state.health?.grid_intensity_g_per_kwh;
const grid = () => F.pickGrid(store.get(GRID_KEY), operatorG());
const wh = (v) => F.fmtWh(v, lang());
const grams = (v) => F.fmtGrams(v, lang());
const approx = (s) => `≈ ${s}`;

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {}))
    if (value !== null && value !== undefined) el.setAttribute(key, value);
  for (const c of children.flat()) if (c) el.append(c);
  return el;
}
const svgText = (attrs, text) => {
  const el = svg("text", attrs);
  el.textContent = text;
  return el;
};
/** Sizes set through the CSSOM, which the CSP allows (no inline style attribute). */
const sized = (el, styles) => (Object.assign(el.style, styles), el);
const link = (url, text, cls = "fp-src") =>
  h("a", {
    class: cls,
    href: url,
    target: "_blank",
    rel: "noopener noreferrer",
    text,
  });

/** Answers that count: real ones; scripted (demo) ones only when there is nothing else, and then flagged. */
function counted(usages) {
  const all = (usages || []).filter(
    (u) => u && typeof u.prompt_tokens === "number",
  );
  const real = all.filter((u) => u.tokens_kind !== "scripted");
  return real.length
    ? { list: real, demo: false }
    : { list: all, demo: all.length > 0 };
}
const convUsages = (conv) =>
  (conv?.turns || [])
    .filter((x) => x.role === "assistant" && x.usage)
    .map((x) => x.usage);

// ------------------------------------------------------------------ device totals

/** This device's running totals; seeded once from the local ledger so earlier answers are not lost. */
export function deviceTotals() {
  const totals = F.readTotals(store);
  if (totals.since) return totals;
  const ledger = store
    .json(LEDGER_KEY, [])
    .filter((u) => u && typeof u.prompt_tokens === "number");
  if (!ledger.length) return totals;
  for (const u of ledger) F.recordTotals(store, u, u.ts || Date.now());
  return F.readTotals(store);
}

/** Hook of views.js ledgerAdd(): called once per finished answer, after the ledger holds it. */
export function recordFootprint(usage) {
  const totals = F.readTotals(store);
  if (!totals.since)
    deviceTotals(); // the seed already contains this answer
  else F.recordTotals(store, usage);
}

// ------------------------------------------------------------------ small pieces

let gridIds = 0;
/** The grid switch. Only the operator's declared grid is « the » grid; every other one is the reader's hypothesis. */
function gridChooser(onChange) {
  const current = grid().key;
  const keys = [
    ...(typeof operatorG() === "number" ? ["operator"] : []),
    ...F.GRID_ORDER,
  ];
  const label = t(
    current === "operator" ? "footprint.grid.label" : "footprint.grid.label.if",
  );
  const id = `fp-grid-${(gridIds += 1)}`;
  // toggle buttons (aria-pressed), each reachable with Tab: the radio pattern would need arrow keys
  return h(
    "div",
    { class: "fp-grid", role: "group", "aria-labelledby": id },
    h("span", { class: "fp-grid-label", id, text: label }),
    h(
      "span",
      { class: "segs fp-segs" },
      keys.map((key) =>
        h("button", {
          type: "button",
          class: `seg${key === current ? " is-on" : ""}`,
          "aria-pressed": String(key === current),
          "data-grid": key,
          text: t(`footprint.grid.${key}`),
          onclick: () => {
            store.set(GRID_KEY, key);
            document.dispatchEvent(
              new CustomEvent("bird:footprint-grid", { detail: key }),
            );
            onChange();
          },
        }),
      ),
    ),
  );
}

function gridNote() {
  const g = grid();
  const value = F.num(g.g_per_kwh, lang(), 3);
  if (g.key === "operator")
    return h("p", {
      class: "fp-note",
      text: t("footprint.grid.note.operator", { g: value }),
    });
  return h(
    "p",
    { class: "fp-note" },
    t("footprint.grid.value", { g: value }),
    " · ",
    link(g.url, g.source),
    typeof operatorG() !== "number" && [" ", t("footprint.grid.undeclared")],
  );
}

const fig = (value, label, sub, cls = "") =>
  h(
    "div",
    { class: `fp-fig ${cls}` },
    h("span", { class: "fp-fig-label", text: label }),
    h("span", { class: "fp-fig-value num", text: value }),
    sub && h("span", { class: "fp-fig-sub num", text: sub }),
  );

const EQ_ICONS = {
  streaming:
    '<rect x="3" y="4.5" width="14" height="9.5" rx="1.5"/><path d="M8.5 7.2v4.2l3.6-2.1z"/><path d="M7 16.5h6"/>',
  car: '<path d="M3.5 13.5v-3l1.8-4h9.4l1.8 4v3z"/><circle cx="6.5" cy="14" r="1.6"/><circle cx="13.5" cy="14" r="1.6"/><path d="M5 10.5h10"/>',
  search: '<circle cx="9" cy="9" r="5.2"/><path d="M13 13l4 4"/>',
  email:
    '<rect x="3" y="5" width="14" height="10.5" rx="1.5"/><path d="M3.5 6.5l6.5 5 6.5-5"/>',
  phone:
    '<rect x="6" y="2.5" width="8" height="15" rx="1.8"/><path d="M10.6 6.8l-2 3.4h2.8l-2 3.4"/>',
};
function eqIcon(key) {
  const el = svg("svg", {
    class: "fp-eq-icon",
    viewBox: "0 0 20 20",
    "aria-hidden": "true",
    focusable: "false",
  });
  el.innerHTML = EQ_ICONS[key] || "";
  return el;
}

/** One equivalent's sentence: a duration or a distance as such; a count directly, or « 1 X ≈ N answers » / « N % of X ». */
export function equivalentText(e, context) {
  const L = lang();
  if (e.unit !== "count")
    return t(`footprint.equiv.${e.key}`, { v: F.fmtAmount(e, L) });
  if (e.amount >= 1)
    return t(`footprint.equiv.${e.key}.n`, { v: F.num(e.amount, L) });
  if (context === "answer")
    return t(`footprint.equiv.${e.key}.per`, { n: F.fmtPerUnit(e, L) });
  return t(`footprint.equiv.${e.key}.share`, { v: F.num(e.amount * 100, L) });
}

function equivalentsList(energyWh, context) {
  return h(
    "div",
    { class: "fp-eq" },
    h("p", { class: "fp-eyebrow", text: t("footprint.equiv.title") }),
    h(
      "ul",
      { class: "fp-eq-list" },
      F.equivalents(energyWh, grid()).map((e) =>
        h(
          "li",
          { "data-eq": e.key },
          eqIcon(e.key),
          h("span", {
            class: "fp-eq-text num",
            text: equivalentText(e, context),
          }),
          link(e.url, e.key === "phone" ? "EPA" : "ADEME"),
        ),
      ),
    ),
    h("p", { class: "fp-note", text: t("footprint.equiv.note") }),
  );
}

/** Bars of the energy of each answer, the one being read highlighted. */
function sparkline(usages, current) {
  const list = usages.filter(F.hasEnergy).slice(-24);
  if (list.length < 2) return null;
  const max = Math.max(...list.map((u) => u.energy_wh));
  const W = 96;
  const H = 22;
  const step = W / list.length;
  return svg(
    "svg",
    {
      class: "fp-spark",
      viewBox: `0 0 ${W} ${H}`,
      width: W,
      height: H,
      "aria-hidden": "true",
      focusable: "false",
    },
    list.map((u, i) => {
      const hh = Math.max(2, (u.energy_wh / max) * (H - 2));
      return svg("rect", {
        x: (i * step + step * 0.15).toFixed(2),
        y: (H - hh).toFixed(2),
        width: (step * 0.7).toFixed(2),
        height: hh.toFixed(2),
        rx: 1,
        class: u === current ? "is-current" : null,
      });
    }),
  );
}

// ------------------------------------------------------------------ hook 1: one answer (inside the receipt)

/** The impact of one answer: emissions on the chosen grid, water, graphics-card time, equivalents, the conversation. */
export function footprintAnswer(u, conv, { onOpenPage } = {}) {
  const f = F.answerFigures(u, grid());
  if (!f) return null;
  const L = lang();
  const demo = u.tokens_kind === "scripted";
  const kind = demo ? t("footprint.kind.demo") : t(`footprint.kind.${f.kind}`);
  const conversation = counted(convUsages(conv));
  const sum = F.sumUsages(conversation.list);
  const range = (lo, hi, fmt) =>
    lo !== hi ? t("footprint.range", { low: fmt(lo), high: fmt(hi) }) : kind;
  const el = h(
    "section",
    { class: "fp-answer", "aria-label": t("footprint.answer.title") },
    h(
      "div",
      { class: "fp-figs" },
      fig(
        approx(grams(f.g)),
        t("footprint.emissions"),
        range(f.gLow, f.gHigh, grams),
      ),
      fig(approx(F.fmtWater(f.ml, L)), t("footprint.water"), t("footprint.water.ratio")),
    ),
    gridChooser(() => el.replaceWith(footprintAnswer(u, conv, { onOpenPage }))),
    gridNote(),
    h(
      "div",
      { class: "fp-gpu" },
      h("p", {
        class: "fp-gpu-line",
        text: t("footprint.gpu.line", { s: F.fmtDuration(f.gpuS, L) }),
      }),
      h(
        "details",
        { class: "fp-gpu-what" },
        h("summary", { text: t("footprint.gpu.what") }),
        h("p", { text: t("footprint.gpu.explain") }),
      ),
    ),
    equivalentsList(f.wh, "answer"),
    sum.energyN > 1 &&
      h(
        "p",
        { class: "fp-conv" },
        h("span", { class: "fp-eyebrow", text: t("footprint.conv.title") }),
        h("span", {
          class: "num",
          text: t("footprint.conv.line", {
            n: sum.n,
            wh: approx(wh(sum.wh)),
            g: approx(grams(F.grams(sum.wh, grid().g_per_kwh))),
          }),
        }),
        sparkline(conversation.list, u),
      ),
    demo && h("p", { class: "fp-note fp-demo", text: t("footprint.demo") }),
    onOpenPage &&
      h("button", {
        class: "link fp-more",
        type: "button",
        text: t("footprint.more"),
        onclick: onOpenPage,
      }),
  );
  return el;
}

// ------------------------------------------------------------------ hook 2: the Empreinte page

function hero(scope, sum, since, demo, rerender) {
  const L = lang();
  const g = grid();
  const title =
    scope === "all"
      ? since
        ? t("footprint.hero.all", {
            date: new Intl.DateTimeFormat(L === "en" ? "en-GB" : "fr-FR", {
              dateStyle: "long",
            }).format(new Date(since)),
          })
        : t("footprint.hero.all.empty")
      : t("footprint.hero.conv");
  const kind = demo
    ? t("footprint.kind.demo")
    : sum.measured
      ? t("footprint.kind.measured")
      : t("footprint.kind.estimated");
  if (!sum.energyN)
    return h(
      "section",
      { class: "panel fp-hero" },
      h("p", { class: "fp-eyebrow", text: title }),
      h("p", { class: "hint", text: t("footprint.hero.none") }),
    );
  return h(
    "section",
    { class: "panel fp-hero", "data-fp": "hero" },
    h("p", { class: "fp-eyebrow", text: title }),
    h(
      "div",
      { class: "fp-hero-main" },
      h("span", { class: "fp-hero-value num", text: approx(wh(sum.wh)) }),
      h(
        "span",
        { class: "fp-hero-sub num" },
        `${t("footprint.hero.energy")} · ${kind}`,
        sum.low !== sum.high &&
          ` · ${t("footprint.range", { low: wh(sum.low), high: wh(sum.high) })}`,
      ),
      h("span", {
        class: "fp-hero-sub num",
        text: t("footprint.hero.answers", {
          n: sum.n,
          in: F.int(sum.tokensIn, L),
          out: F.int(sum.tokensOut, L),
        }),
      }),
    ),
    h(
      "div",
      { class: "fp-figs" },
      fig(
        approx(grams(F.grams(sum.wh, g.g_per_kwh))),
        t("footprint.emissions"),
        sum.low !== sum.high &&
          t("footprint.range", {
            low: grams(F.grams(sum.low, g.g_per_kwh)),
            high: grams(F.grams(sum.high, g.g_per_kwh)),
          }),
      ),
      fig(
        approx(F.fmtWater(F.water(sum.wh), L)),
        t("footprint.water"),
        t("footprint.water.ratio"),
      ),
      fig(F.fmtDuration(sum.gpuS, L), t("footprint.gpu"), null),
    ),
    gridChooser(rerender),
    gridNote(),
    equivalentsList(sum.wh, "period"),
  );
}

/** Energy of each answer against the large assistant's per-prompt figure (dashed line). */
function energyChart(list, ref) {
  const answers = list.filter(F.hasEnergy).slice(-30);
  if (!answers.length) return null;
  const offset = list.filter(F.hasEnergy).length - answers.length;
  const W = 640;
  const H = 150;
  const top = 18;
  const plot = H - top - 4;
  const max =
    Math.max(ref ? ref.wh * 1.12 : 0, ...answers.map((u) => u.energy_wh)) || 1;
  const y = (v) => top + plot - Math.min(1, v / max) * plot;
  const step = W / Math.max(answers.length, 8);
  const barW = Math.min(28, step * 0.62);
  const L = lang();
  const bars = answers.map((u, i) => {
    const b = u.energy_basis || {};
    const x = i * step + (step - barW) / 2;
    const lo = typeof b.low_wh === "number" ? b.low_wh : u.energy_wh;
    const hi = typeof b.high_wh === "number" ? b.high_wh : u.energy_wh;
    const label = t("footprint.chart.bar", {
      i: offset + i + 1,
      wh: approx(wh(u.energy_wh)),
      low: wh(lo),
      high: wh(hi),
    });
    const title = svg("title");
    title.textContent = label;
    return svg(
      "g",
      { class: "fp-bar" },
      title,
      svg("rect", {
        x: x.toFixed(1),
        y: y(u.energy_wh).toFixed(1),
        width: barW.toFixed(1),
        height: (top + plot - y(u.energy_wh)).toFixed(1),
        rx: 3,
      }),
      lo !== hi &&
        svg("line", {
          class: "fp-whisker",
          x1: (x + barW / 2).toFixed(1),
          x2: (x + barW / 2).toFixed(1),
          y1: y(lo).toFixed(1),
          y2: y(hi).toFixed(1),
        }),
    );
  });
  const refLine =
    ref &&
    svg(
      "g",
      { class: "fp-ref" },
      svg("line", {
        x1: 0,
        x2: W,
        y1: y(ref.wh).toFixed(1),
        y2: y(ref.wh).toFixed(1),
      }),
    );
  const avg = answers.reduce((a, u) => a + u.energy_wh, 0) / answers.length;
  return h(
    "figure",
    { class: "panel fp-chart", "data-fp": "chart" },
    h(
      "figcaption",
      null,
      h("span", { class: "fp-eyebrow", text: t("footprint.chart.title") }),
      list.length > answers.length &&
        h("span", {
          class: "hint",
          text: t("footprint.chart.last", { n: answers.length }),
        }),
      // the legend is HTML: the SVG stretches to the column, its text would too
      ref &&
        h(
          "span",
          { class: "fp-chart-legend" },
          h(
            "span",
            { class: "fp-legend-item" },
            h("span", { class: "fp-legend-bird", "aria-hidden": "true" }),
            h("span", { text: "Bird" }),
          ),
          h(
            "span",
            { class: "fp-legend-item" },
            h("span", { class: "fp-legend-ref", "aria-hidden": "true" }),
            h("span", { text: t("footprint.chart.ref", { wh: wh(ref.wh) }) }),
          ),
        ),
    ),
    svg(
      "svg",
      {
        class: "fp-chart-svg",
        viewBox: `0 0 ${W} ${H}`,
        preserveAspectRatio: "none",
        role: "img",
        "aria-label": `${t("footprint.chart.title")} : ${approx(wh(avg))} (${F.num(answers.length, L)})`,
      },
      svg("line", {
        class: "fp-axis",
        x1: 0,
        x2: W,
        y1: top + plot,
        y2: top + plot,
      }),
      bars,
      refLine,
    ),
  );
}

/** « Had you used a large assistant »: same answers, same boundary, saved = difference, with Bird's range. */
function versusPanel(sum, refs) {
  if (!sum.energyN || !refs.length) return null;
  const rows = [
    {
      label: t("footprint.vs.bird", { n: sum.energyN }),
      value: sum.wh,
      low: sum.low,
      high: sum.high,
      cls: "is-bird",
    },
    ...refs.map((r) => ({
      label: t(`footprint.vs.${r.key}`),
      value: sum.energyN * r.wh,
      url: r.url,
      cls: `is-${r.key}`,
    })),
  ];
  const max = Math.max(...rows.map((r) => Math.max(r.value, r.high || 0))) || 1;
  const main = F.versus(sum, refs[0]);
  const ratio = main.ratio;
  const saved =
    main.savedLow >= 0
      ? t("footprint.vs.saved", {
          saved: wh(main.saved),
          low: wh(main.savedLow),
          high: wh(main.savedHigh),
        })
      : t("footprint.vs.saved.maybe", {
          saved: wh(Math.max(0, main.saved)),
          over: wh(-main.savedLow),
        });
  return h(
    "section",
    { class: "panel fp-vs", "data-fp": "versus" },
    h("h3", { class: "fp-h", text: t("footprint.vs.title") }),
    h(
      "ul",
      { class: "fp-vs-rows" },
      rows.map((r) =>
        h(
          "li",
          { class: r.cls },
          h(
            "span",
            { class: "fp-vs-label" },
            r.label,
            r.url && [" · ", link(r.url, t("footprint.vs.source"))],
          ),
          h(
            "span",
            { class: "fp-vs-track", "aria-hidden": "true" },
            typeof r.low === "number" &&
              r.low !== r.high &&
              sized(h("span", { class: "fp-vs-range" }), {
                insetInlineStart: `${(r.low / max) * 100}%`,
                inlineSize: `${((Math.min(r.high, max) - r.low) / max) * 100}%`,
              }),
            sized(h("span", { class: "fp-vs-fill" }), {
              inlineSize: `${Math.max(0.6, (r.value / max) * 100)}%`,
            }),
          ),
          h("span", { class: "fp-vs-value num", text: approx(wh(r.value)) }),
        ),
      ),
    ),
    ratio &&
      h("p", {
        class: "fp-vs-times num",
        text:
          ratio >= 1
            ? t("footprint.vs.times", { x: F.num(ratio, lang()) })
            : t("footprint.vs.more", { x: F.num(1 / ratio, lang()) }),
      }),
    ratio && ratioRange(main),
    h("p", { class: "fp-vs-saved num", text: saved }),
    h("p", { class: "fp-note", text: t("footprint.vs.note") }),
  );
}

/** The ratio's range from Bird's low and high bounds, so the headline « ≈ N times less » is never read alone. */
function ratioRange(v) {
  const { ratioLow: lo, ratioHigh: hi } = v;
  if (!(lo > 0 && hi > 0) || lo === hi) return null;
  const x = (r) => F.num(r, lang());
  const text =
    lo >= 1
      ? t("footprint.vs.times.range", { low: x(lo), high: x(hi) })
      : hi >= 1
        ? t("footprint.vs.times.range.worse", { high: x(hi), worse: x(1 / lo) })
        : t("footprint.vs.more.range", { low: x(1 / hi), high: x(1 / lo) });
  return h("p", { class: "fp-vs-times-range num", text });
}

/** The configured reference (BIRD_REFERENCE_*), plus the stated figure when it is the default published one. */
function references() {
  const ref = state.health?.compare?.reference;
  if (!ref || !(ref.wh > 0)) return [];
  const published = F.REFERENCES[0];
  if (ref.wh === published.wh && ref.source === published.url)
    return F.REFERENCES;
  return [{ key: "published", wh: ref.wh, url: ref.source }];
}

// ------------------------------------------------------------------ the story (in-house SVG)

function storySection(key, art, text) {
  return h(
    "section",
    { class: "fp-story-item", "data-story": key },
    h("div", { class: "fp-art", "aria-hidden": "true" }, art),
    h(
      "div",
      { class: "fp-story-text" },
      h("h4", { class: "fp-h4", text: t(`footprint.${key}.title`) }),
      h("p", { text }),
    ),
  );
}

function artParams(b, big) {
  const n = Math.max(1, Math.min(400, Math.round(big / b)));
  const cols = Math.ceil(Math.sqrt(n));
  const cell = 9;
  const gx = 64;
  const width = gx + cols * cell + 4;
  const rows = Math.ceil(n / cols);
  const height = Math.max(rows * cell, 24) + 22;
  const squares = [];
  for (let i = 0; i < n; i += 1)
    squares.push(
      svg("rect", {
        x: gx + (i % cols) * cell,
        y: Math.floor(i / cols) * cell,
        width: cell - 2,
        height: cell - 2,
        rx: 1.5,
        class: "fp-sq-big",
      }),
    );
  return svg(
    "svg",
    { viewBox: `0 0 ${width} ${height}`, class: "fp-art-svg" },
    svg("rect", {
      x: 18,
      y: 0,
      width: cell - 2,
      height: cell - 2,
      rx: 1.5,
      class: "fp-sq-bird",
    }),
    svgText(
      {
        x: 21.5,
        y: height - 6,
        "text-anchor": "middle",
        class: "fp-art-label",
      },
      t("footprint.s1.bird"),
    ),
    squares,
    svgText(
      { x: gx, y: height - 6, class: "fp-art-label" },
      t("footprint.s1.big"),
    ),
  );
}

/** Labelled horizontal bars in HTML (text stays legible at any width; widths through the CSSOM). */
function artBars(rows, unitFmt) {
  const max = Math.max(...rows.map((r) => r.value)) || 1;
  return h(
    "div",
    { class: "fp-art-bars" },
    rows.map((r) =>
      h(
        "div",
        { class: "fp-art-row" },
        h("span", { class: "fp-art-rlabel", text: r.label }),
        h(
          "span",
          { class: "fp-art-track" },
          sized(h("span", { class: `fp-art-fill ${r.cls}` }), {
            inlineSize: `${Math.max(1.5, (r.value / max) * 100)}%`,
          }),
        ),
        h("span", { class: "fp-art-rvalue num", text: unitFmt(r.value) }),
      ),
    ),
  );
}

function artSleep() {
  const pulses = [
    [14, 34],
    [44, 22],
    [62, 40],
    [110, 26],
  ];
  return svg(
    "svg",
    { viewBox: "0 0 300 70", class: "fp-art-svg" },
    svg("line", { x1: 0, x2: 300, y1: 52, y2: 52, class: "fp-axis" }),
    pulses.map(([x, hgt]) =>
      svg("rect", {
        x,
        y: 52 - hgt,
        width: 12,
        height: hgt,
        rx: 3,
        class: "fp-sq-bird",
      }),
    ),
    svg("path", { d: "M140 50 H300", class: "fp-sleep-line" }),
    svgText(
      { x: 60, y: 66, "text-anchor": "middle", class: "fp-art-label" },
      t("footprint.s4.busy"),
    ),
    svgText(
      { x: 220, y: 40, "text-anchor": "middle", class: "fp-art-label" },
      `${t("footprint.s4.idle")}  z z`,
    ),
  );
}

function artNodes() {
  const sat = [
    [40, 20],
    [40, 70],
    [260, 20],
    [260, 70],
  ];
  return svg(
    "svg",
    { viewBox: "0 0 300 90", class: "fp-art-svg" },
    sat.map(([x, y]) =>
      svg("line", { x1: 150, y1: 45, x2: x, y2: y, class: "fp-link" }),
    ),
    sat.map(([x, y]) =>
      svg("rect", {
        x: x - 18,
        y: y - 10,
        width: 36,
        height: 20,
        rx: 6,
        class: "fp-node",
      }),
    ),
    svg("circle", { cx: 150, cy: 45, r: 20, class: "fp-sq-bird" }),
    svgText(
      { x: 150, y: 49, "text-anchor": "middle", class: "fp-art-core" },
      "Bird",
    ),
  );
}

function artFrance() {
  return svg(
    "svg",
    { viewBox: "0 0 60 40", class: "fp-art-svg fp-art-fr" },
    svg("rect", {
      x: 0,
      y: 0,
      width: 20,
      height: 40,
      rx: 0,
      class: "fp-fr-blue",
    }),
    svg("rect", { x: 20, y: 0, width: 20, height: 40, class: "fp-fr-white" }),
    svg("rect", { x: 40, y: 0, width: 20, height: 40, class: "fp-fr-red" }),
  );
}

function story(avgWh) {
  const L = lang();
  const cmp = state.health?.compare || {};
  const b = Number(cmp.active_params_b) || 4;
  const dense =
    (cmp.classes || []).find((c) => c.fr === "grand modèle dense") ||
    (cmp.classes || [])[0];
  const big = dense?.active_params_b || 400;
  const ref = F.REFERENCES[0];
  const refMl = F.water(ref.wh);
  const perk = state.health?.energy?.tokens?.wh_per_1k_out;
  const s2 = avgWh
    ? t("footprint.s2.p", {
        wh: wh(avgWh),
        ml: F.fmtWater(F.water(avgWh), L),
        refwh: wh(ref.wh),
        refml: F.fmtWater(refMl, L),
      })
    : t("footprint.s2.p.none", {
        perk: wh(perk || 0.1),
        refwh: wh(ref.wh),
        refml: F.fmtWater(refMl, L),
      });
  const basis = avgWh || 1;
  const gridRows = F.GRID_ORDER.map((k) => ({
    label: `${t(`footprint.grid.${k}`)} · ${F.GRIDS[k].g_per_kwh} g/kWh`,
    value: F.grams(basis, F.GRIDS[k].g_per_kwh),
    cls: k === "fr" ? "fp-bar-eco" : "fp-bar-muted",
  }));
  const [fr, eu, world] = gridRows.map((r) => grams(r.value));
  return h(
    "section",
    {
      class: "fp-story",
      "data-fp": "story",
      "aria-labelledby": "fp-story-title",
    },
    h("h3", {
      id: "fp-story-title",
      class: "fp-story-title",
      text: t("footprint.story.title"),
    }),
    h("p", { class: "fp-story-lead", text: t("footprint.story.lead") }),
    storySection(
      "s1",
      artParams(b, big),
      t("footprint.s1.p", {
        b: F.num(b, L),
        big: F.num(big, L),
        x: F.num(big / b, L),
      }),
    ),
    storySection(
      "s2",
      artBars(
        avgWh
          ? [
              {
                label: t("footprint.s2.bird"),
                value: avgWh,
                cls: "fp-bar-eco",
              },
              {
                label: t("footprint.s2.ref"),
                value: ref.wh,
                cls: "fp-bar-muted",
              },
            ]
          : [
              {
                label: `${t("footprint.s2.bird")} (1 000 tokens)`,
                value: perk || 0.1,
                cls: "fp-bar-eco",
              },
              {
                label: t("footprint.s2.ref"),
                value: ref.wh,
                cls: "fp-bar-muted",
              },
            ],
        wh,
      ),
      s2,
    ),
    storySection(
      "s3",
      artBars(gridRows, grams),
      t("footprint.s3.p", {
        what: t(avgWh ? "footprint.s3.what.answer" : "footprint.s3.what.wh"),
        fr,
        eu,
        world,
      }),
    ),
    storySection("s4", artSleep(), t("footprint.s4.p")),
    storySection("s5", artNodes(), t("footprint.s5.p")),
    h(
      "div",
      { class: "fp-story-fr", "data-story": "s6" },
      artFrance(),
      h(
        "div",
        null,
        h("h4", { class: "fp-h4", text: t("footprint.s6.title") }),
        h("p", { text: t("footprint.s6.p") }),
      ),
    ),
  );
}

function methodTable() {
  const L = lang();
  const tok = state.health?.energy?.tokens;
  const tokSrc = (tok?.sources || [])[0];
  const row = (what, value, source, url, licence) =>
    h(
      "tr",
      null,
      h("th", { scope: "row", text: what }),
      h("td", { class: "num", text: value }),
      h("td", null, url ? link(url, source, "") : source),
      h("td", { text: licence ? t(`footprint.licence.${licence}`) : "" }),
    );
  const rows = [
    tok &&
      row(
        t("footprint.method.tokens.out"),
        wh(tok.wh_per_1k_out),
        t("footprint.method.tokens.source"),
        tokSrc?.url,
        "cite",
      ),
    tok &&
      row(
        t("footprint.method.tokens.in"),
        wh(tok.wh_per_1k_in),
        t("footprint.method.tokens.source"),
        tokSrc?.url,
        "cite",
      ),
    row(
      t("footprint.method.flops"),
      t("footprint.method.flops.value"),
      F.FLOPS.source,
      F.FLOPS.url,
      F.FLOPS.licence,
    ),
    ...F.GRID_ORDER.map((k) => {
      const g = F.GRIDS[k];
      return row(
        t("footprint.method.grid", { name: t(`footprint.grid.${k}`) }),
        `${F.num(g.g_per_kwh, L, 3)} g CO₂e/kWh`,
        `${g.source} (${g.year})`,
        g.url,
        g.licence,
      );
    }),
    row(
      t("footprint.method.water"),
      F.fmtWater(F.WATER.ml_per_wh, L),
      F.WATER.source,
      F.WATER.url,
      F.WATER.licence,
    ),
    ...F.REFERENCES.map((r) =>
      row(
        t(`footprint.method.ref.${r.key}`),
        wh(r.wh),
        r.url.replace(/^https:\/\/([^/]+).*/, "$1"),
        r.url,
        "cite",
      ),
    ),
    ...F.EQUIVALENTS.map((e) =>
      row(
        t(`footprint.method.eq.${e.key}`),
        e.per === "wh"
          ? wh(e.value)
          : e.made
            ? `${grams(e.value)}, ${t("footprint.method.made", { g: grams(e.made) })}`
            : grams(e.value),
        e.source,
        e.url,
        e.licence,
      ),
    ),
  ];
  return h(
    "details",
    { class: "panel fp-method", "data-fp": "method" },
    h("summary", { text: t("footprint.method.title") }),
    h("p", { class: "hint", text: t("footprint.method.p") }),
    h(
      "div",
      { class: "fp-table-wrap" },
      h(
        "table",
        { class: "fp-table" },
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            ["what", "value", "source", "licence"].map((c) =>
              h("th", { scope: "col", text: t(`footprint.method.col.${c}`) }),
            ),
          ),
        ),
        h("tbody", null, rows),
      ),
    ),
  );
}

/**
 * Hook of views.js renderFootprint(): keeps the scope switch on top, adds the totals, the chart, the comparison and
 * the story, and folds the page's former detailed figures under « Every figure for the period ».
 */
export function mountFootprintPage(body, { scope, usages, rerender }) {
  if (!body) return;
  const children = [...body.children];
  const head = children.find((c) => c.classList.contains("segs"));
  const rest = children.filter((c) => c !== head);
  const { list, demo } = counted(usages);
  let sum = F.sumUsages(list);
  let since = null;
  let isDemo = demo;
  if (scope === "all") {
    const totals = deviceTotals();
    const real = totals.real.n > 0;
    sum = { ...(real ? totals.real : totals.demo), measured: false };
    since = totals.since;
    isDemo = !real && totals.demo.n > 0;
  }
  const again = () =>
    rerender ? rerender() : mountFootprintPage(body, { scope, usages });
  const refs = references();
  const avg = sum.energyN ? sum.wh / sum.energyN : null;
  const all = h(
    "details",
    { class: "fp-all", "data-fp": "all" },
    h("summary", { text: t("footprint.all.title") }),
    h("div", { class: "page-body fp-all-body" }, rest),
  );
  body.replaceChildren(
    ...[
      head,
      hero(scope, sum, since, isDemo, again),
      energyChart(list, refs[0]),
      versusPanel(sum, refs),
      isDemo && h("p", { class: "demo-note", text: t("footprint.demo") }),
      story(avg),
      rest.length && all,
      methodTable(),
      scope === "all" &&
        since &&
        h("button", {
          class: "btn btn-outline btn-small fp-reset",
          type: "button",
          text: t("footprint.reset"),
          onclick: () => {
            if (!window.confirm(t("footprint.reset.confirm"))) return;
            F.resetTotals(store);
            store.set(LEDGER_KEY, null);
            again();
          },
        }),
    ].filter(Boolean),
  );
}
