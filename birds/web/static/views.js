// Secondary views: the footprint ("Empreinte"), settings, about, welcome, keyboard help.
import { saveAgentMode } from "./agent-mode.js";
import {
  $,
  activeMode,
  activeModel,
  button,
  fmtBytes,
  fmtCo2,
  fmtEnergy,
  fmtInt,
  fmtSeconds,
  fmtSig,
  h,
  hasEnergy,
  icon,
  resetPrefs,
  savePrefs,
  state,
  store,
  t,
  toast,
  modelLabel,
} from "./core.js";
import { mountFootprintPage, recordFootprint } from "./footprint.js";
import { footprintNote, localOffered, localPanel } from "./local.js";

let hooks = {};
// replaceChildren would print null/false as text: drop them first
const put = (el, ...children) =>
  el.replaceChildren(
    ...children
      .flat()
      .filter((c) => c !== null && c !== undefined && c !== false),
  );
export const setViewHooks = (value) => (hooks = value);

// ------------------------------------------------------------------ footprint ledger (all-time, local)

const LEDGER_KEY = "bird.ledger";
const LEDGER_MAX = 400;

export function ledgerAdd(usage, convId) {
  const entries = store.json(LEDGER_KEY, []);
  entries.push({ ...usage, type: undefined, ts: Date.now(), conv: convId });
  store.set(LEDGER_KEY, JSON.stringify(entries.slice(-LEDGER_MAX)));
  recordFootprint(usage); // ---- footprint.js hook: device totals, kept beyond the ledger's last answers
}
export const ledgerAll = () =>
  store
    .json(LEDGER_KEY, [])
    .filter((u) => u && typeof u.prompt_tokens === "number");
export const ledgerReset = () => store.set(LEDGER_KEY, null);

export function convUsages(conv) {
  return (conv?.turns || [])
    .filter((x) => x.role === "assistant" && x.usage)
    .map((x) => x.usage);
}

export function totals(usages) {
  const sum = (key) =>
    usages.reduce((total, u) => total + (Number(u[key]) || 0), 0);
  const withEnergy = usages.filter(hasEnergy);
  const withCo2 = withEnergy.filter((u) => typeof u.co2_g === "number");
  return {
    n: usages.length,
    prompt: sum("prompt_tokens"),
    completion: sum("completion_tokens"),
    seconds: sum("seconds"),
    tools: sum("tool_calls"),
    bytes: sum("bytes_fetched"),
    energyN: withEnergy.length,
    energy: withEnergy.reduce((total, u) => total + u.energy_wh, 0),
    energyKind: withEnergy.some((u) => u.energy_kind === "estimated")
      ? "estimated"
      : "measured",
    co2N: withCo2.length,
    co2: withCo2.reduce((total, u) => total + u.co2_g, 0),
  };
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {}))
    el.setAttribute(key, value);
  el.append(...children);
  return el;
}
function topRounded(x, y, w, hgt, r) {
  const rr = Math.min(r, hgt, w / 2);
  return `M${x} ${y + hgt}V${y + rr}a${rr} ${rr} 0 0 1 ${rr}-${rr}h${w - 2 * rr}a${rr} ${rr} 0 0 1 ${rr} ${rr}V${y + hgt}z`;
}

function chart(all) {
  const usages = all.slice(-40);
  const offset = all.length - usages.length;
  const height = 132;
  const top = 16; // room for the scale label
  const plot = height - top - 2;
  const max = Math.max(
    1,
    ...usages.map((u) => u.prompt_tokens + u.completion_tokens),
  );
  const readout = h("p", {
    class: "chart-readout num",
    "aria-live": "polite",
    text: t("fp.chart.hint"),
  });
  const scroller = h("div", { class: "chart-scroll" });
  let current = usages.length - 1; // roving tabindex: one tab stop, the arrows move between answers
  const labelOf = (u, i) =>
    t("fp.bar", {
      i: offset + i + 1,
      in: fmtInt(u.prompt_tokens),
      out: fmtInt(u.completion_tokens),
      extra:
        (u.thinking ? t("fp.bar.thinking") : "") +
        (u.tool_calls ? t("fp.bar.tools", { n: u.tool_calls }) : ""),
    });
  function draw() {
    const W = Math.max(160, Math.floor(scroller.clientWidth || 640) - 4);
    const n = Math.max(1, usages.length);
    const gap = Math.min(8, Math.max(2, Math.round(W / n / 4)));
    const barW = Math.min(24, Math.max(3, Math.floor((W - gap) / n - gap)));
    const width = Math.min(W, Math.max(n * (barW + gap) + gap, 160));
    const hadFocus = scroller.contains(document.activeElement);
    const el = svg("svg", {
      class: "chart",
      viewBox: `0 0 ${width} ${height}`,
      width,
      height,
      role: "group",
      "aria-label": t("fp.chart"),
    });
    el.append(
      svg("line", {
        class: "chart-grid",
        x1: 0,
        x2: width,
        y1: top + 0.5,
        y2: top + 0.5,
      }),
      svg(
        "text",
        { class: "chart-scale", x: 0, y: top - 5 },
        document.createTextNode(`${fmtInt(max)} tokens`),
      ),
      svg("line", {
        class: "chart-axis",
        x1: 0,
        x2: width,
        y1: height - 0.5,
        y2: height - 0.5,
      }),
    );
    const bars = usages.map((u, i) => {
      const x = gap + i * (barW + gap); // left-aligned
      const hIn = Math.max(
        u.prompt_tokens > 0 ? 2 : 0,
        (u.prompt_tokens / max) * (plot - 2),
      );
      const hOut = Math.max(
        u.completion_tokens > 0 ? 2 : 0,
        (u.completion_tokens / max) * (plot - 2),
      );
      const label = labelOf(u, i);
      const group = svg("g", {
        class: "chart-bar",
        tabindex: i === current ? "0" : "-1",
        role: "img",
        "aria-label": label,
        "data-i": String(i),
      });
      group.append(
        svg("rect", {
          class: "chart-hit",
          x: x - gap / 2,
          y: 0,
          width: barW + gap,
          height,
        }),
        svg("rect", {
          class: "series-in",
          x,
          y: height - 1 - hIn,
          width: barW,
          height: hIn,
        }),
        svg("path", {
          class: "series-out",
          d: topRounded(
            x,
            height - 1 - hIn - 2 - hOut,
            barW,
            hOut,
            Math.min(4, barW / 2),
          ),
        }),
      );
      if (u.thinking)
        group.append(
          svg("circle", {
            class: "chart-dot",
            cx: x + barW / 2,
            cy: Math.max(top + 4, height - 1 - hIn - 2 - hOut - 6),
            r: Math.min(2.2, barW / 2),
          }),
        );
      const show = () => {
        current = i;
        readout.textContent = label;
      };
      group.addEventListener("mouseenter", show);
      group.addEventListener("focus", show);
      group.addEventListener("pointerdown", show); // touch: a tap shows the details
      el.append(group);
      return group;
    });
    el.addEventListener("keydown", (e) => {
      const go = {
        ArrowRight: current + 1,
        ArrowLeft: current - 1,
        Home: 0,
        End: bars.length - 1,
      }[e.key];
      if (go === undefined) return;
      e.preventDefault();
      const next = Math.max(0, Math.min(bars.length - 1, go));
      bars[current]?.setAttribute("tabindex", "-1");
      bars[next].setAttribute("tabindex", "0");
      current = next;
      bars[next].focus();
    });
    scroller.replaceChildren(el);
    if (hadFocus) bars[current]?.focus();
  }
  draw();
  let lastW = 0;
  let timer = 0;
  if (typeof ResizeObserver === "function")
    new ResizeObserver(() => {
      const w = scroller.clientWidth;
      if (!w || w === lastW) return;
      const first = !lastW;
      lastW = w;
      window.clearTimeout(timer);
      if (first)
        draw(); // now in the page: its real width
      else timer = window.setTimeout(draw, 80); // debounced: a window drag redraws once
    }).observe(scroller);
  return h(
    "figure",
    { class: "panel chart-figure" },
    h(
      "figcaption",
      null,
      h("span", {
        class: "eyebrow",
        text:
          all.length > usages.length
            ? `${t("fp.chart")} · ${t("fp.chart.last", { n: usages.length })}`
            : t("fp.chart"),
      }),
      h(
        "span",
        { class: "legend" },
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-in" }),
          t("fp.legend.in"),
        ),
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-out" }),
          t("fp.legend.out"),
        ),
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-dot" }),
          t("composer.thinking").toLowerCase(),
        ),
      ),
    ),
    scroller,
    readout,
    h(
      "details",
      { class: "chart-table" },
      h("summary", null, icon("chevron", "chev"), t("fp.table")),
      h(
        "table",
        null,
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            h("th", { scope: "col", text: t("fp.col.answer") }),
            h("th", { scope: "col", text: t("row.prompt") }),
            h("th", { scope: "col", text: t("row.completion") }),
            h("th", { scope: "col", text: t("row.seconds") }),
          ),
        ),
        h(
          "tbody",
          null,
          usages.map((u, i) =>
            h(
              "tr",
              null,
              h("th", {
                scope: "row",
                class: "num",
                text: String(offset + i + 1),
              }),
              h("td", { class: "num", text: fmtInt(u.prompt_tokens) }),
              h("td", { class: "num", text: fmtInt(u.completion_tokens) }),
              h("td", { class: "num", text: fmtSeconds(u.seconds) }),
            ),
          ),
        ),
      ),
    ),
  );
}

const totalTokens = (u) => u.prompt_tokens + u.completion_tokens;
const writtenTokens = (u) => u.completion_tokens;
const avgBy = (list, f) =>
  list.length ? list.reduce((s, u) => s + f(u), 0) / list.length : 0;

/**
 * The one thinking comparison of the page (the panel and the lever line both use it): tokens the model WROTE,
 * on answers without tools only (a tool turn re-reads pages and would swamp the effect), and at least two
 * answers on each side, else no figure at all.
 */
function thinkingCompare(usages) {
  const plain = usages.filter((u) => !(u.tool_calls > 0));
  const on = plain.filter((u) => u.thinking);
  const off = plain.filter((u) => !u.thinking);
  return {
    asked: usages.some((u) => u.thinking),
    enough: on.length >= 2 && off.length >= 2,
    on: on.length,
    off: off.length,
    avgOn: avgBy(on, writtenTokens),
    avgOff: avgBy(off, writtenTokens),
  };
}

function splitRow(label, usages, max, f, unitKey) {
  const n = usages.length;
  const avg = Math.round(avgBy(usages, f));
  const bar = h(
    "span",
    { class: "split-bar" },
    h("span", { class: "split-fill" }),
  );
  bar.firstChild.style.inlineSize = `${max ? Math.max(n ? 2 : 0, (avg / max) * 100) : 0}%`; // CSSOM, allowed by the CSP
  return h(
    "div",
    { class: "split-row" },
    h("span", { class: "split-label", text: label }),
    bar,
    h("span", {
      class: "split-value num",
      text: n ? t(unitKey, { n: fmtInt(n), avg: fmtInt(avg) }) : "—",
    }),
  );
}

function splits(usages) {
  // thinking rows: tokens written; tool rows: all tokens (a tool turn's cost is mostly what it reads)
  const on = usages.filter((u) => u.thinking);
  const off = usages.filter((u) => !u.thinking);
  const withTools = usages.filter((u) => u.tool_calls > 0);
  const without = usages.filter((u) => !u.tool_calls);
  const maxThink = Math.max(
    avgBy(on, writtenTokens),
    avgBy(off, writtenTokens),
    1,
  );
  const maxTools = Math.max(
    avgBy(withTools, totalTokens),
    avgBy(without, totalTokens),
    1,
  );
  return h(
    "section",
    { class: "panel" },
    h("h3", { class: "eyebrow", text: t("fp.split") }),
    h("p", { class: "split-title", text: t("fp.split.thinking") }),
    splitRow(
      t("fp.split.off"),
      off,
      maxThink,
      writtenTokens,
      "fp.split.avg.out",
    ),
    splitRow(t("fp.split.on"), on, maxThink, writtenTokens, "fp.split.avg.out"),
    h("p", { class: "split-title", text: t("fp.split.tools") }),
    splitRow(
      t("fp.split.without"),
      without,
      maxTools,
      totalTokens,
      "fp.split.avg",
    ),
    splitRow(
      t("fp.split.with"),
      withTools,
      maxTools,
      totalTokens,
      "fp.split.avg",
    ),
  );
}

/** "1,9 fois plus": the ratio as the page words it, shared by the panel and the lever line. */
function thinkRatio(c) {
  const a = c.avgOn;
  const b = c.avgOff;
  const x = a >= b ? a / Math.max(b, 1) : b / Math.max(a, 1);
  return x < 1.15
    ? t("fp.compare.same")
    : t(a >= b ? "fp.compare.more" : "fp.compare.less", {
        x: fmtSig(Math.round(x * 10) / 10),
      });
}

function comparison(usages) {
  const c = thinkingCompare(usages);
  if (!c.asked) return null;
  if (!c.enough)
    return h(
      "section",
      { class: "panel panel-accent", "data-compare": "1" },
      h("h3", { class: "eyebrow", text: t("fp.compare.title") }),
      h("p", { text: t("fp.compare.few", { a: c.on, b: c.off }) }),
    );
  const a = c.avgOn;
  const b = c.avgOff;
  const ratio = thinkRatio(c);
  return h(
    "section",
    { class: "panel panel-accent", "data-compare": "1" },
    h("h3", { class: "eyebrow", text: t("fp.compare.title") }),
    h("p", {
      text: t("fp.compare.text", {
        on: fmtInt(Math.round(a)),
        off: fmtInt(Math.round(b)),
        ratio,
      }),
    }),
    h("p", {
      class: "hint",
      text: t("fp.compare.note", { a: c.on, b: c.off }),
    }),
  );
}

// ------------------------------------------------------------------ what Bird saves (defensible comparisons only)

function bar(label, value, max, text, cls = "") {
  const pct = Math.max(1.5, Math.min(100, (value / max) * 100));
  const fill = h("span", { class: "sbar-fill" });
  fill.style.setProperty("--w", `${pct.toFixed(1)}%`); // CSSOM, allowed by the CSP (no inline style attribute)
  return h(
    "div",
    { class: `sbar ${cls}` },
    h("span", { class: "sbar-label", text: label }),
    h("span", { class: "sbar-track", "aria-hidden": "true" }, fill),
    h("span", { class: "sbar-value num", text }),
  );
}

function savings(usages, s, scripted = false) {
  const cmp = state.health?.compare;
  if (!cmp) return null;
  const lang = state.prefs.lang === "en" ? "en" : "fr";
  const bird = Number(cmp.active_params_b) || 4;
  const tokens = s.prompt + s.completion;
  const gflop = (params, n) => 2 * params * n; // GFLOP: 2 x active parameters (in billions) per token
  const fmtFlop = (g) =>
    g >= 1000 ? `${fmtSig(g / 1000)} TFLOP` : `${fmtSig(g)} GFLOP`;
  const classes = (cmp.classes || []).filter((c) => c.active_params_b > 0);
  const max = Math.max(bird, ...classes.map((c) => c.active_params_b));
  const theory = h(
    "div",
    { class: "save-block", "data-save": "compute" },
    h("p", { class: "save-title", text: t("save.compute.title") }),
    h("p", { class: "hint", text: t("save.compute.label") }),
    bar(
      t("save.bird", { b: fmtSig(bird) }),
      bird,
      max,
      `${fmtSig(2 * bird)} GFLOP/token`,
      "sbar-bird",
    ),
    classes.map((c) =>
      bar(
        `${c[lang] || c.fr} (~${fmtSig(c.active_params_b)} Md)`,
        c.active_params_b,
        max,
        t("save.times", { x: fmtSig(c.active_params_b / bird) }),
      ),
    ),
    tokens > 0 &&
      !scripted && // no FLOP figure computed from scripted token counts
      h("p", {
        class: "save-line",
        text: t("save.compute.here", {
          n: fmtInt(tokens),
          bird: fmtFlop(gflop(bird, tokens)),
          big: fmtFlop(gflop(classes[0]?.active_params_b || bird, tokens)),
          label: classes[0]?.[lang] || "",
        }),
      }),
  );
  const ref = cmp.reference;
  const withE = usages.filter(hasEnergy);
  const avg = withE.length
    ? withE.reduce((a, u) => a + u.energy_wh, 0) / withE.length
    : null;
  // the label says what the entries are: all measured, all an upper bound (power x time), all estimated from
  // tokens (whole-service boundary, like the reference), else an estimate
  const allPower =
    withE.length > 0 && withE.every((u) => u.energy_method === "power_time");
  const allTokens =
    withE.length > 0 && withE.every((u) => u.energy_method === "tokens");
  const overhead = withE.find((u) => u.energy_basis?.serving_overhead)?.energy_basis?.serving_overhead;
  const energyKind =
    withE.length && withE.every((u) => u.energy_kind === "measured")
      ? "measured"
      : allPower
        ? "upper"
        : allTokens
          ? "tokens"
          : "estimated";
  const birdLabel = t("save.energy.bird", {
    kind: t(`save.energy.kind.${energyKind}`),
    k: fmtInt(withE.length),
    n: fmtInt(usages.length),
  });
  const energy =
    ref && ref.wh > 0 && ref.source
      ? h(
          "div",
          { class: "save-block", "data-save": "energy" },
          h("p", { class: "save-title", text: t("save.energy.title") }),
          avg === null
            ? h("p", { class: "hint", text: t("save.energy.none") })
            : [
                bar(
                  birdLabel,
                  avg,
                  Math.max(avg, ref.wh),
                  fmtEnergy(avg, energyKind === "measured" ? "measured" : "estimated"),
                  "sbar-bird",
                ),
                bar(
                  ref[`label_${lang}`] || ref.label_fr || "",
                  ref.wh,
                  Math.max(avg, ref.wh),
                  `${fmtSig(ref.wh)} Wh`,
                ),
                h("p", {
                  class: "save-line",
                  text:
                    avg < ref.wh
                      ? t("save.energy.less", { x: fmtSig(ref.wh / avg) })
                      : t("save.energy.more", { x: fmtSig(avg / ref.wh) }),
                }),
              ],
          h(
            "p",
            { class: "hint" },
            allTokens && overhead
              ? t("save.energy.scope.tokens", { k: fmtSig(overhead) })
              : t(allPower ? "save.energy.scope.max" : "save.energy.scope"),
            " ",
            h("a", {
              href: ref.source,
              target: "_blank",
              rel: "noopener noreferrer",
              text: t("save.source"),
            }),
          ),
        )
      : h("p", { class: "hint", text: t("save.energy.unset") });
  const off = usages.filter((u) => !u.thinking);
  const think = thinkingCompare(usages);
  const levers = h(
    "ul",
    { class: "levers" },
    h(
      "li",
      null,
      h("strong", { text: t("save.lever.small") }),
      " ",
      t("save.lever.small.p", { b: fmtSig(bird) }),
    ),
    h(
      "li",
      null,
      h("strong", { text: t("save.lever.zero") }),
      " ",
      t("save.lever.zero.p"),
    ),
    h(
      "li",
      null,
      h("strong", { text: t("save.lever.short") }),
      " ",
      off.length
        ? t("save.lever.short.p", {
            n: fmtInt(Math.round(avgBy(off, writtenTokens))),
          })
        : t("save.lever.short.none"),
    ),
    h(
      "li",
      null,
      h("strong", { text: t("save.lever.think") }),
      " ",
      think.enough
        ? t("save.lever.think.p", {
            on: fmtInt(Math.round(think.avgOn)),
            off: fmtInt(Math.round(think.avgOff)),
            ratio: thinkRatio(think),
          })
        : think.asked
          ? t("fp.compare.few", { a: think.on, b: think.off })
          : t("save.lever.think.none"),
    ),
  );
  return h(
    "section",
    {
      class: "panel panel-save",
      "aria-labelledby": "save-title",
      "data-savings": "1",
    },
    h("h3", { id: "save-title", class: "save-head", text: t("save.title") }),
    theory,
    energy,
    h(
      "p",
      { class: "save-candid" },
      icon("info"),
      h("span", { text: t("save.candid") }),
    ),
    h("p", { class: "save-title", text: t("save.levers") }),
    levers,
  );
}

let scope = "conv";
/** Bird local: under the scope switch, one line on where the energy of these answers is measured or estimated. */
function localNote(body) {
  const note = footprintNote();
  if (note) (body.querySelector(".segs") || body.firstChild)?.after(note);
}

export function renderFootprint() {
  const body = $("view-footprint-body");
  const usages = scope === "all" ? ledgerAll() : convUsages(state.conv);
  // scripted (demo) answers never count in the totals when real ones exist; if all are scripted, they are shown
  // but tagged as such
  const real = usages.filter((u) => u.tokens_kind !== "scripted");
  const demoN = usages.length - real.length;
  const allScripted = usages.length > 0 && !real.length;
  const counted = allScripted ? usages : real;
  const s = totals(counted);
  const demo = activeMode() === "demo" || allScripted;
  const scriptedTag = allScripted
    ? h("span", { class: "tag tag-scripted", text: t("kind.scripted") })
    : null;
  const gi = state.health?.grid_intensity_g_per_kwh;
  const eq = state.health?.equivalent;
  const partial = (k) => (k < s.n ? t("fp.partial", { k, n: s.n }) : "");
  const stat = (label, value, sub, cls = "") =>
    h(
      "div",
      { class: `stat ${cls}` },
      h("dt", { text: label }),
      h(
        "dd",
        null,
        h("span", { class: "stat-value num", text: value }),
        cls.includes("stat-scripted") && scriptedTag?.cloneNode(true),
        sub && h("span", { class: "stat-sub", text: sub }),
      ),
    );
  const seg = (value, label) =>
    h("button", {
      class: `seg${scope === value ? " is-on" : ""}`,
      type: "button",
      role: "radio",
      "aria-checked": String(scope === value),
      "data-scope": value,
      onclick: () => ((scope = value), renderFootprint()),
      text: label,
    });
  const head = h(
    "div",
    { class: "segs", role: "radiogroup", "aria-label": t("fp.scope") },
    seg("conv", t("fp.scope.conv")),
    seg("all", t("fp.scope.all")),
  );
  const how = h(
    "section",
    { class: "panel" },
    h("h3", { class: "eyebrow", text: t("fp.how") }),
    h(
      "ul",
      { class: "how" },
      ["counted", "measured", "estimated", "unavailable"].map((k) =>
        h(
          "li",
          null,
          h("span", { class: `tag tag-${k}`, text: t(`kind.${k}`) }),
          h("span", { text: t(`fp.how.${k}`).replace(/^[^:]+:\s*/, "") }),
        ),
      ),
    ),
    typeof gi === "number" &&
      h("p", { class: "hint", text: t("fp.method", { gi: fmtSig(gi) }) }),
  );
  if (!s.n) {
    put(
      body,
      head,
      h("p", { class: "panel panel-empty", text: t("fp.empty") }),
      demo && h("p", { class: "demo-note", text: t("demo.note") }),
      how,
      h("p", { class: "hint", text: t("fp.note") }),
    );
    mountFootprintPage(body, { scope, usages, rerender: renderFootprint }); // ---- footprint.js hook
  localNote(body);
    return;
  }
  const energyStat = s.energyN
    ? stat(
        t("fp.energy"),
        fmtEnergy(s.energy, s.energyKind),
        [t(`kind.${s.energyKind}`), partial(s.energyN)]
          .filter(Boolean)
          .join(" · "),
        "stat-wide",
      )
    : stat(
        t("fp.energy"),
        t("meter.energy.none.long"),
        t(
          usages.some((u) => u.tokens_kind === "scripted") &&
            !real.some(hasEnergy)
            ? "why.energy.demo"
            : "why.energy.none",
        ),
        "stat-wide stat-none",
      );
  const co2Stat = s.co2N
    ? stat(
        t("fp.co2"),
        fmtCo2(s.co2),
        [t("kind.estimated"), partial(s.co2N)].filter(Boolean).join(" · "),
        "stat-wide",
      )
    : stat(
        t("fp.co2"),
        t("co2.none"),
        t(s.energyN ? "why.co2.nogrid" : "why.co2.noenergy"),
        "stat-wide stat-none",
      );
  // An everyday comparison only when the operator configured a factor AND its source; never a built-in guess.
  const equivalent =
    s.energyN && eq && eq.wh > 0 && eq.label && eq.source
      ? h(
          "section",
          { class: "panel", "data-equivalent": "1" },
          h("p", {
            text: t("fp.equiv", {
              n: fmtSig(s.energy / eq.wh),
              label: eq.label,
            }),
          }),
          h("p", {
            class: "hint",
            text: t("fp.equiv.source", {
              wh: fmtSig(eq.wh),
              source: eq.source,
            }),
          }),
        )
      : null;
  put(
    body,
    head,
    allScripted && h("p", { class: "demo-note", text: t("demo.note") }),
    h(
      "dl",
      { class: "stats" },
      stat(
        t("fp.tokens"),
        fmtInt(s.prompt + s.completion),
        t("meter.tokens.split", {
          in: fmtInt(s.prompt),
          out: fmtInt(s.completion),
        }),
        `stat-hero${allScripted ? " stat-scripted" : ""}`,
      ),
      stat(t("fp.answers"), fmtInt(s.n)),
      stat(
        t("fp.time"),
        fmtSeconds(s.seconds),
        null,
        allScripted ? "stat-scripted" : "",
      ),
      stat(t("fp.tools"), fmtInt(s.tools)),
      stat(t("fp.fetched"), fmtBytes(s.bytes)),
      energyStat,
      co2Stat,
    ),
    equivalent,
    demoN > 0 &&
      !allScripted &&
      h("p", {
        class: "hint fp-demo-excluded",
        text: t(demoN === 1 ? "fp.demo.excluded.one" : "fp.demo.excluded", {
          n: demoN,
        }),
      }),
    chart(usages),
    savings(counted, s, allScripted),
    scope === "conv" ? comparison(counted) : null,
    splits(counted),
    how,
    demo &&
      !allScripted &&
      h("p", { class: "demo-note", text: t("demo.note") }),
    h("p", { class: "hint", text: t("fp.note") }),
    scope === "all" &&
      button("btn-outline btn-small", "trash", t("fp.reset"), () => {
        if (window.confirm(t("fp.reset.confirm"))) {
          ledgerReset();
          renderFootprint();
        }
      }),
  );
  mountFootprintPage(body, { scope, usages, rerender: renderFootprint }); // ---- footprint.js hook
  localNote(body);
}

// ------------------------------------------------------------------ settings

function field(id, label, hint, control) {
  return h(
    "div",
    { class: "field" },
    h("label", { for: id, text: label }),
    control,
    hint && h("p", { class: "hint", id: `${id}-hint`, text: hint }),
  );
}

/** Which tools Bird may use on this deployment, and why the others are off. */
export function toolsPanel() {
  const info = state.health?.tools_info;
  if (!info) return null;
  const lang = state.prefs.lang === "en" ? "en" : "fr";
  const demo = activeMode() === "demo";
  const label = {
    on: t("tools.on"),
    off: t("tools.off"),
    attach: t("tools.attach"),
  };
  return h(
    "details",
    { class: "panel tools-panel", id: "settings-tools" },
    h(
      "summary",
      null,
      icon("chevron", "chev"),
      h(
        "span",
        { class: "tools-sum" },
        h("span", {
          id: "set-tools-title",
          class: "tools-sum-title",
          text: t("tools.title"),
        }),
        h("span", {
          class: "hint",
          text: demo ? t("tools.demo") : t("tools.lead"),
        }),
      ),
    ),
    h(
      "ul",
      { class: "tools-list" },
      info.tools.map((x) =>
        h(
          "li",
          { class: `tool-row tool-${x.state}`, "data-tool": x.name },
          h("span", { class: "card-icon" }, icon(x.name)),
          h(
            "span",
            { class: "tool-text" },
            h("span", { class: "tool-name", text: t(`tool.${x.name}`) }),
            h("span", { class: "tool-why", text: x[lang] || "" }),
          ),
          h("span", {
            class: `tag tag-tool-${x.state}`,
            text: label[x.state] || x.state,
          }),
        ),
      ),
    ),
    info.search?.fallback &&
      h("p", {
        class: "hint",
        text: t("tools.fallback", {
          label: info.search.label,
          fallback: info.search.fallback,
        }),
      }),
  );
}

export function renderSettings() {
  const body = $("view-settings-body");
  const p = state.prefs;
  const hl = state.health || {};
  const modes = hl.modes || { demo: true };
  const mode = activeMode();
  // the choice shown: « Bird local » opens its connect flow before it becomes the mode (once paired)
  const shown = state.localPanel && localOffered() ? "local" : mode;
  const select = (id, value, options, onchange) =>
    h(
      "select",
      { id, onchange: (e) => onchange(e.target.value) },
      options.map(([v, label]) =>
        h("option", { value: v, selected: v === value }, label),
      ),
    );

  const modeCard = (value, title, hint, enabled) =>
    h(
      "label",
      {
        class: `mode${shown === value ? " is-on" : ""}${enabled ? "" : " is-off"}${value === "local" ? " mode-local" : ""}`,
      },
      h("input", {
        type: "radio",
        name: "mode",
        value,
        checked: shown === value,
        disabled: !enabled,
        onchange: () => {
          if (value === "local") {
            state.localPanel = true; // the connect flow; the mode changes once the code is accepted
            renderSettings();
            document.querySelector('input[name="mode"][value="local"]')?.focus();
            return;
          }
          state.localPanel = false;
          apply({ mode: value, demoChosen: value === "demo" });
        },
      }),
      h(
        "span",
        { class: "mode-text" },
        h(
          "span",
          { class: "mode-title" },
          title,
          !enabled &&
            h("span", {
              class: "tag tag-unavailable",
              text: t("kind.unavailable"),
            }),
        ),
        h("span", { class: "mode-hint", text: hint }),
      ),
    );

  const result = h("p", {
    class: "test-result",
    id: "endpoint-result",
    role: "status",
    "aria-live": "polite",
  });
  const urlInput = h("input", {
    id: "set-endpoint",
    type: "url",
    inputmode: "url",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "https://xxxx.endpoints.huggingface.cloud",
    value: p.endpoint,
    "aria-describedby": "set-endpoint-hint",
  });
  const tokenInput = h("input", {
    id: "set-token",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "hf_…",
    value: p.token,
    "aria-describedby": "set-token-hint",
  });
  const modelInput = h("input", {
    id: "set-model",
    type: "text",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "adubrou/Bird-S-4B",
    value: p.model,
    "aria-describedby": "set-model-hint",
  });
  const accessInput = h("input", {
    id: "set-access",
    type: "password",
    autocomplete: "off",
    value: p.access,
    "aria-describedby": "set-access-hint",
  });
  const reveal = h("button", {
    class: "btn btn-outline btn-small",
    type: "button",
    "aria-pressed": "false",
    "aria-controls": "set-token",
    text: t("set.endpoint.show"),
  });
  reveal.addEventListener("click", () => {
    const show = tokenInput.type === "password";
    tokenInput.type = show ? "text" : "password";
    reveal.textContent = t(show ? "set.endpoint.hide" : "set.endpoint.show");
    reveal.setAttribute("aria-pressed", String(show));
  });
  const collect = () => ({
    endpoint: urlInput.value.trim(),
    token: tokenInput.value.trim(),
    model: modelInput.value.trim(),
    access: accessInput.value.trim(),
  });
  function apply(patch, quiet) {
    Object.assign(state.prefs, collect(), patch || {});
    savePrefs();
    if (patch)
      hooks.onPrefs(); // a mode, language or theme change redraws the app
    else hooks.onSaved(); // a typed field is only saved: redrawing here would steal the next click
    if (!quiet) toast(t("toast.saved"), "ok");
  }
  for (const input of [urlInput, tokenInput, modelInput, accessInput])
    input.addEventListener("change", () => apply(null, true));

  const testBtn = button(
    "btn-outline",
    "check",
    t("set.endpoint.test"),
    async () => {
      apply(null, true);
      testBtn.disabled = true;
      result.className = "test-result";
      result.textContent = t("set.endpoint.testing");
      const out = await hooks.testEndpoint();
      if (out.ok && typeof out.images === "boolean") {
        state.prefs.userImages = out.images; // the photo button follows what this endpoint can do
        savePrefs();
      }
      testBtn.disabled = false;
      result.className = `test-result ${out.ok ? "is-ok" : out.status === "waking" ? "is-calm" : "is-bad"}`;
      result.replaceChildren(
        icon(out.ok ? "check" : out.status === "waking" ? "moon" : "alert"),
        h("span", { text: out.message }),
      );
      result.dataset.status = out.status;
    },
  );
  testBtn.id = "endpoint-test";

  const hosts = (hl.endpoint_hosts || ["*.endpoints.huggingface.cloud"]).join(
    ", ",
  );
  put(
    body,
    h(
      "section",
      { class: "panel", "aria-labelledby": "set-general-title" },
      h("h3", { id: "set-general-title", text: t("set.general") }),
      field(
        "set-lang",
        t("set.lang"),
        null,
        select(
          "set-lang",
          p.lang,
          [
            ["fr", "Français"],
            ["en", "English"],
          ],
          (v) => apply({ lang: v }),
        ),
      ),
      field(
        "set-theme",
        t("set.theme"),
        null,
        select(
          "set-theme",
          p.theme,
          [
            ["system", t("set.theme.system")],
            ["light", t("set.theme.light")],
            ["dark", t("set.theme.dark")],
          ],
          (v) => apply({ theme: v }),
        ),
      ),
      h(
        "label",
        { class: "check" },
        h("input", {
          type: "checkbox",
          id: "set-thinking",
          checked: !!p.thinking,
          onchange: (e) => apply({ thinking: e.target.checked }),
        }),
        h(
          "span",
          null,
          h("span", { class: "check-title", text: t("set.thinking") }),
          h("span", { class: "hint", text: t("set.thinking.hint") }),
        ),
      ),
      // the Mode Agent lives here, not in the composer (one button fewer): Auto lets Bird call the team when needed
      field(
        "agent-mode",
        t("composer.agent.aria"),
        t("composer.agent.hint"),
        select(
          "agent-mode",
          ["auto", "on", "off"].includes(state.agent) ? state.agent : "auto",
          [
            ["auto", t("composer.agent.auto")],
            ["on", t("composer.agent.on")],
            ["off", t("composer.agent.off")],
          ],
          (v) => {
            state.agent = saveAgentMode(v, globalThis.localStorage, globalThis.sessionStorage);
            toast(t("toast.saved"), "ok");
          },
        ),
      ),
    ),
    h(
      "section",
      {
        class: "panel",
        id: "settings-model",
        "aria-labelledby": "set-model-title",
      },
      h("h3", { id: "set-model-title", text: t("set.model") }),
      h("p", { class: "hint", text: t("set.model.lead") }),
      h(
        "div",
        {
          class: "modes",
          role: "radiogroup",
          "aria-labelledby": "set-model-title",
        },
        // the demo exists only where no model is connected (a showcase deployment, the e2e server): never beside a real one
        !modes.server && modeCard("demo", t("set.mode.demo"), t("set.mode.demo.hint"), true),
        modeCard(
          "server",
          t("set.mode.server"),
          modes.server
            ? t("set.mode.server.hint", { model: hl.model || "bird" })
            : t("set.mode.server.off"),
          !!modes.server,
        ),
        modeCard(
          "user",
          t("set.mode.user"),
          modes.user ? t("set.mode.user.hint") : t("set.mode.user.off"),
          !!modes.user,
        ),
        localOffered() && modeCard("local", t("local.mode"), t("local.mode.hint"), true),
      ),
      shown === "local" && localPanel({ onPrefs: () => hooks.onPrefs() }),
      hl.bird_local && h("p", { class: "tradeoff" }, icon("monitor"), h("span", { text: t("local.here") })),
      modes.user &&
        shown !== "user" &&
        shown !== "local" &&
        h("p", { class: "hint endpoint-off", text: t("set.endpoint.choose") }),
      modes.user &&
        shown === "user" &&
        h(
          "fieldset",
          { class: "endpoint" },
          h("legend", { class: "sr-only", text: t("set.mode.user") }),
          field(
            "set-endpoint",
            t("set.endpoint.url"),
            t("set.endpoint.url.hint", { hosts }),
            urlInput,
          ),
          field(
            "set-token",
            t("set.endpoint.token"),
            t("set.endpoint.token.hint"),
            h("div", { class: "input-row" }, tokenInput, reveal),
          ),
          field(
            "set-model",
            t("set.endpoint.model"),
            t("set.endpoint.model.hint"),
            modelInput,
          ),
        ),
      modes.user &&
        shown === "user" &&
        h(
          "p",
          { class: "tradeoff" },
          icon("info"),
          h("span", { text: t("set.endpoint.tradeoff") }),
        ),
      shown !== "local" &&
        (hl.access_required || p.access) &&
        field(
          "set-access",
          t("set.access"),
          t(hl.access_required ? "set.access.needed" : "set.access.hint"),
          accessInput,
        ),
      shown !== "demo" && shown !== "local" && h("div", { class: "test-row" }, testBtn, result),
    ),
    toolsPanel(),
    h(
      "section",
      { class: "panel", "aria-labelledby": "set-data-title" },
      h("h3", { id: "set-data-title", text: t("set.data") }),
      h("p", { class: "hint", text: t("set.data.lead") }),
      button("btn-outline btn-danger", "trash", t("set.data.reset"), () => {
        if (!window.confirm(t("set.data.reset.confirm"))) return;
        for (const key of store.keys("bird.")) store.set(key, null);
        resetPrefs();
        savePrefs();
        hooks.onReset();
        toast(t("toast.cleared"), "ok");
      }),
    ),
  );
}

// ------------------------------------------------------------------ about, welcome, shortcuts

export function renderAbout() {
  const block = (title, ...children) =>
    h("section", { class: "panel" }, h("h3", { text: title }), ...children);
  put(
    $("view-about-body"),
    h(
      "div",
      { class: "about-brand" },
      h("img", {
        class: "lockup only-light",
        src: "/static/brand/logo-stacked.svg",
        alt: "Bird S 4B",
        width: "87",
        height: "112",
      }),
      h("img", {
        class: "lockup only-dark",
        src: "/static/brand/logo-stacked-dark.svg",
        alt: "Bird S 4B",
        width: "87",
        height: "112",
      }),
      h("p", { class: "page-lead", text: t("about.tagline") }),
    ),
    h(
      "p",
      { class: "about-intro" },
      h(
        "button",
        {
          id: "about-intro",
          class: "btn",
          type: "button",
          onclick: () => openWelcome(),
        },
        icon("info"),
        h("span", { class: "btn-label", text: t("about.intro") }),
      ),
    ),
    block(t("about.what"), h("p", { text: t("about.what.p") })),
    block(t("about.deal"), h("p", { text: t("about.deal.p") })),
    block(t("about.where"), h("p", { text: t("about.where.p") })),
    block(t("about.built"), h("p", { text: t("about.built.p") })),
    block(
      t("about.data"),
      h(
        "ul",
        { class: "data-list" },
        h(
          "li",
          null,
          icon("check"),
          h("span", { text: t("about.data.browser") }),
        ),
        h(
          "li",
          null,
          icon("send"),
          h("span", { text: t("about.data.server") }),
        ),
        h(
          "li",
          null,
          icon("read_page"),
          h("span", { text: t("about.data.web") }),
        ),
      ),
    ),
    block(t("about.meter"), h("p", { text: t("about.meter.p") })),
    block(
      t("ex.guard.title"),
      h("p", { text: t("ex.guard.p") }),
      h("button", {
        class: "btn",
        type: "button",
        "data-example": "guard",
        text: t("ex.guard.title"),
        onclick: () => hooks.onGuardDemo?.(t("ex.guard.prompt")),
      }),
    ),
    h("p", {
      class: "hint",
      text: t("about.current", {
        model: activeModel(),
        mode: t(`mode.${activeMode()}`),
      }),
    }),
  );
}

// The bird mark: a constant drawn here, never model output.
const MARK =
  '<svg class="w-mark" viewBox="0 0 64 56" aria-hidden="true" focusable="false"><path d="M5 49C15 45.5 26 40.5 36 34.5c3-1.8 5.2-5.1 8.4-7.1 3.9-2.4 8.6-1.5 10.8 1.9L61.5 30.4l-5.6 2.3c-1 3.1-3.4 5.7-6.9 7.4C38 45.2 22 49.5 5 49z"/><path d="M40.5 31.5C38.5 21 30 10.5 14.5 5.5c4.2 6.8 6.2 14.2 8.2 20.9 1.3 4.3 3.3 8.2 6.8 11.3z"/><path d="M43.5 28.5c.5-7.8 3.8-15.8 10.8-22.3-1 5.9-.3 10.7-.8 15.3-.3 3.2-1.7 5.8-4.6 7.6z"/></svg>';
const svgFrom = (markup) => {
  const wrap = document.createElement("span");
  wrap.innerHTML = markup;
  return wrap.firstChild;
};

function setWelcomeLang(lang) {
  if (state.prefs.lang !== lang) {
    state.prefs.lang = lang;
    savePrefs();
    hooks.onPrefs?.(); // applyStrings() and a redraw of the app behind the dialog
  }
  openWelcome({ focusLang: lang });
}

// the tagline with its accent word (three keys, so each language places the accent itself)
const tagline = () => [
  h("span", { "data-i18n": "empty.title", text: t("empty.title") }),
  h("em", { "data-i18n": "empty.title.em", text: t("empty.title.em") }),
  h("span", { "data-i18n": "empty.title.end", text: t("empty.title.end") }),
];

export function openWelcome({ focusLang } = {}) {
  const dialog = $("welcome");
  const start = h("button", {
    id: "welcome-start",
    class: "btn btn-primary btn-cta",
    type: "button",
    text: t("welcome.start"),
    onclick: () => dialog.close(),
  });
  // Short on purpose: brand, the promise, three strengths, what it makes, one button. The story lives on the
  // « À propos » site; the starters wait on the empty screen behind the dialog.
  const value = (ico, key) =>
    h(
      "li",
      { class: "w-value" },
      h("span", { class: "w-vicon" }, icon(ico)),
      h("b", { text: t(key) }),
      h("span", { text: t(`${key}.p`) }),
    );
  const site = state.health?.site_url;
  put(
    $("welcome-body"),
    h(
      "section",
      { class: "w-step" },
      h(
        "header",
        { class: "w-head" },
        h(
          "span",
          { class: "w-brand" },
          svgFrom(MARK),
          h("b", { text: "Bird" }),
          h("span", { text: "S 4B" }),
        ),
        h(
          "span",
          { class: "w-tools" },
          h(
            "span",
            { class: "w-lang", role: "group", "aria-label": t("welcome.lang") },
            ["fr", "en"].map((lang) =>
              h("button", {
                class: "w-lang-opt",
                type: "button",
                lang,
                "data-lang": lang,
                "aria-pressed": String(state.prefs.lang === lang),
                "aria-label": lang === "fr" ? "Français" : "English",
                text: lang.toUpperCase(),
                onclick: () => setWelcomeLang(lang),
              }),
            ),
          ),
          h(
            "button",
            {
              id: "welcome-close",
              class: "btn btn-quiet btn-icon w-close",
              type: "button",
              "aria-label": t("close"),
              title: t("close"),
              onclick: () => dialog.close(),
            },
            icon("cross"),
          ),
        ),
      ),
      h(
        "p",
        { class: "w-kicker" },
        h("i", { "aria-hidden": "true" }),
        t("welcome.france"),
      ),
      h("h2", { id: "welcome-title", class: "w-title" }, tagline()),
      h("p", { id: "welcome-lead", class: "w-lead", text: t("welcome.credo") }),
      h(
        "ul",
        { class: "w-values", "aria-label": t("welcome.values") },
        value("leaf", "welcome.light"),
        value("find_places", "welcome.where"),
        value("eye", "welcome.clear"),
      ),
      h(
        "ul",
        { class: "w-caps", "aria-label": t("start.title") },
        STARTERS.map(([key, ico]) =>
          h("li", null, icon(ico), h("span", { text: t(`start.${key}`) })),
        ),
      ),
      h(
        "div",
        { class: "w-actions" },
        h(
          "p",
          { class: "w-foot" },
          h("span", { text: t("welcome.local") }),
          site &&
            h("a", { class: "w-more", href: site, text: t("welcome.more") }),
        ),
        start,
      ),
    ),
  );
  if (!dialog.open) {
    dialog.returnTo = document.activeElement;
    dialog.showModal();
    dialog.scrollTop = 0;
  }
  const lang = focusLang && dialog.querySelector(`[data-lang="${focusLang}"]`);
  (lang || start).focus({ preventScroll: true });
}

// ------------------------------------------------------------------ first impression (fi-app): starter cards
// The empty chat shows what Bird does best. A card never sends anything: it fills the message box with a ready
// request (the same forms as the slash actions, or a full example) and selects the part to make one's own.
const STARTERS = [
  ["mail", "draft_email", "slash.mail.tpl"],
  ["deck", "make_slides", "slash.pres.tpl"],
  ["search", "web_search", "slash.search.tpl"],
  ["map", "find_places"],
  ["chart", "make_chart"],
  ["weather", "get_weather"],
];

function fillStarter(key) {
  const [, , form] = STARTERS.find(([k]) => k === key) || [];
  const el = $("composer-input");
  const text = form ? t(form) : t(`start.${key}.tpl`);
  el.value = text;
  el.dispatchEvent(new Event("input", { bubbles: true })); // app.js sizes the box and enables Send
  el.focus();
  let from = text.length;
  let to = from;
  if (form) {
    // the caret goes to the first field left blank (« Destinataire : »)
    const blank = text.search(/: ?$/m);
    const eol = blank >= 0 ? text.indexOf("\n", blank) : -1;
    if (eol >= 0) from = to = eol;
  } else {
    const sel = t(`start.${key}.sel`);
    const at = text.lastIndexOf(sel);
    if (at >= 0) [from, to] = [at, at + sel.length];
  }
  el.setSelectionRange(from, to);
}

function renderStarters() {
  const list = $("starters");
  if (!list) return;
  put(
    list,
    STARTERS.map(([key, ico]) =>
      h(
        "li",
        null,
        h(
          "button",
          {
            class: `starter starter-${key}`,
            type: "button",
            "data-starter": key,
            "aria-describedby": "starter-hint",
            onclick: () => fillStarter(key),
          },
          h("span", { class: "starter-icon" }, icon(ico)),
          h(
            "span",
            { class: "starter-text" },
            h("span", {
              class: "starter-title",
              "data-i18n": `start.${key}`,
              text: t(`start.${key}`),
            }),
            h("span", {
              class: "starter-desc",
              "data-i18n": `start.${key}.p`,
              text: t(`start.${key}.p`),
            }),
          ),
        ),
      ),
    ),
  );
  // the cards arrive one after the other (CSSOM, allowed by the CSP: no inline style attribute)
  [...list.children].forEach((li, i) => li.style.setProperty("--i", i));
}
renderStarters();
// the eco chip opens « Empreinte »
$("fi-eco")?.addEventListener("click", () => $("nav-footprint")?.click());

export function openShortcuts() {
  const mac = /Mac|iPhone|iPad/.test(navigator.platform || "");
  const mod = mac ? "⌘" : "Ctrl";
  const row = (keys, label) =>
    h(
      "div",
      null,
      h(
        "dt",
        null,
        keys.map((k) => h("kbd", { text: k })),
      ),
      h("dd", { text: label }),
    );
  put(
    $("shortcuts-body"),
    h(
      "dl",
      { class: "keys" },
      row([mod, "K"], t("keys.new")),
      row(["/"], t("keys.focus")),
      row(
        ["Entrée"].map((k) => (state.prefs.lang === "en" ? "Enter" : k)),
        t("keys.send"),
      ),
      row(
        [
          state.prefs.lang === "en" ? "Shift" : "Maj",
          state.prefs.lang === "en" ? "Enter" : "Entrée",
        ],
        t("keys.newline"),
      ),
      row([state.prefs.lang === "en" ? "Esc" : "Échap"], t("keys.stop")),
      row([mod, "B"], t("keys.side")),
      row(["/"], t("keys.slash")),
      row(["?"], t("keys.help")),
    ),
  );
  const dialog = $("shortcuts");
  if (!dialog.open) dialog.showModal();
}
