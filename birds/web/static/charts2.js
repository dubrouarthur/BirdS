// Richer charts (spec v2, birds/harness/analysis/charts.py), drawn as SVG in the browser. No library, strict CSP:
// colours are the app's series classes (light/dark switch live), text goes through textContent only.
// Types: bar (grouped), stacked, hbar, line (multi), area, stacked_area, scatter, bubble, pie, donut, histogram,
// box, heatmap, waterfall, funnel, combo (bars + line on a 2nd axis), kpi. Interactions: tooltips (pointer and
// keyboard), legend toggles, switch type, sort, click a mark -> « Détaille … » in the composer, export PNG / SVG /
// CSV, « Ajouter au document » (a `bird:add-to-document` event the Canvas can take).
import { button, copyText, download, h, icon, state, toast } from "./core.js";

const NS = "http://www.w3.org/2000/svg";
const MIN_W = 280;
const MAX_W = 960;

// ------------------------------------------------------------------ words (FR first, EN parity)
const WORDS = {
  fr: {
    bar: "Barres", stacked: "Barres empilées", hbar: "Barres horizontales", line: "Courbe", area: "Aire",
    stacked_area: "Aires empilées", scatter: "Nuage de points", bubble: "Bulles", pie: "Camembert",
    donut: "Anneau", histogram: "Histogramme", box: "Boîte à moustaches", heatmap: "Carte de chaleur",
    waterfall: "Cascade", funnel: "Entonnoir", combo: "Barres et courbe", kpi: "Chiffre clé",
    sort: "Trier", sorted: "Trié", type: "Type de graphique", export: "Exporter", png: "Image PNG", svg: "Image SVG",
    csv: "Données CSV", csvDone: "Données copiées (CSV)", toDoc: "Ajouter au document",
    toDocDone: "Tableau copié : collez-le dans votre document", drill: "Détaille", legend: "Séries (cliquer pour masquer)",
    total: "Total", max: "max", min: "min", mean: "moyenne", target: "objectif", data: "Données du graphique",
    src_analysis: "calculé par Bird", src_data: "vos données", src_request: "vos chiffres", src_file: "fichier joint",
    src_web: "web", src_model: "non vérifié", r: "corrélation", n: "points", change: "évolution",
    median: "médiane", q1: "1er quartile", q3: "3e quartile", outliers: "valeurs extrêmes", share: "part",
    others: "Autres", cumul: "cumul", hidden: "série masquée", role: "graphique", empty: "Aucune valeur à afficher",
    trend: "tendance", ofFirst: "du premier",
  },
  en: {
    bar: "Bars", stacked: "Stacked bars", hbar: "Horizontal bars", line: "Line", area: "Area",
    stacked_area: "Stacked areas", scatter: "Scatter", bubble: "Bubbles", pie: "Pie", donut: "Donut",
    histogram: "Histogram", box: "Box plot", heatmap: "Heatmap", waterfall: "Waterfall", funnel: "Funnel",
    combo: "Bars and line", kpi: "Key figure", sort: "Sort", sorted: "Sorted", type: "Chart type", export: "Export",
    png: "PNG image", svg: "SVG image", csv: "CSV data", csvDone: "Data copied (CSV)", toDoc: "Add to document",
    toDocDone: "Table copied: paste it into your document", drill: "Detail", legend: "Series (click to hide)",
    total: "Total", max: "max", min: "min", mean: "mean", target: "target", data: "Chart data",
    src_analysis: "computed by Bird", src_data: "your data", src_request: "your figures", src_file: "attached file",
    src_web: "web", src_model: "not verified", r: "correlation", n: "points", change: "change", median: "median",
    q1: "1st quartile", q3: "3rd quartile", outliers: "outliers", share: "share", others: "Other", cumul: "running total",
    hidden: "series hidden", role: "chart", empty: "No value to show", trend: "trend", ofFirst: "of the first",
  },
}; // prettier-ignore
const L = (lang) => WORDS[lang === "en" ? "en" : "fr"];

// ------------------------------------------------------------------ helpers

function s(tag, attrs, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {}))
    if (v !== null && v !== undefined && v !== false)
      el.setAttribute(k, String(v));
  for (const c of children.flat(3))
    if (c !== null && c !== undefined && c !== false)
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}

const num = (v) => typeof v === "number" && Number.isFinite(v);
const locale = (lang) => (lang === "en" ? "en-GB" : "fr-FR");

export function fmtValue(v, unit, lang, compact = false) {
  if (!num(v)) return "—";
  const abs = Math.abs(v);
  const opts = compact && abs >= 10000
    ? { notation: "compact", maximumFractionDigits: 1 }
    : { maximumFractionDigits: abs >= 1000 ? 0 : abs >= 10 ? 1 : 2 };
  const n = new Intl.NumberFormat(locale(lang), opts).format(v);
  const u = String(unit || "");
  if (!u) return n;
  if (u === "%") return lang === "en" ? `${n}%` : `${n} %`;
  if ((u === "$" || u === "£") && lang === "en") return `${u}${n}`;
  return `${n} ${u}`;
} // prettier-ignore

let measure = null;
function textW(text, size = 12) {
  try {
    if (!measure) {
      measure = document.createElement("canvas").getContext("2d");
    }
    if (measure) {
      measure.font = `${size}px ${getComputedStyle(document.body).fontFamily || "sans-serif"}`;
      const w = measure.measureText(String(text)).width;
      if (w) return w;
    }
  } catch {
    /* estimate */
  }
  return String(text).length * size * 0.56;
}
function fit(text, maxW, size = 12) {
  const str = String(text);
  if (textW(str, size) <= maxW) return str;
  let lo = 0;
  let hi = str.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (textW(`${str.slice(0, mid)}…`, size) <= maxW) lo = mid;
    else hi = mid - 1;
  }
  return lo > 0 ? `${str.slice(0, lo).trimEnd()}…` : "…";
}

export function niceTicks(lo, hi, count = 5) {
  if (!num(lo) || !num(hi)) return [0, 1];
  if (lo === hi) {
    if (lo === 0) return [0, 1];
    [lo, hi] = lo > 0 ? [0, lo] : [lo, 0];
  }
  const span = hi - lo;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((k) => k * mag).find((st) => span / st <= count) ||
    10 * mag;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.5; v += step) {
    out.push(Math.round(v / step) * step);
    if (out.length > 12) break;
  }
  if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
  return out;
}

const cls = (i) => (i % 6) + 1;

/** The text of the composer gets « text » (at the caret, or after what is typed), then the focus. */
export function composerInsert(text, { replace = false } = {}) {
  const el = document.getElementById("composer-input");
  if (!el) return false;
  const cur = el.value || "";
  if (replace || !cur.trim()) el.value = text;
  else {
    const at =
      typeof el.selectionStart === "number" ? el.selectionStart : cur.length;
    const before = cur.slice(0, at);
    const pad = before && !/\s$/.test(before) ? " " : "";
    el.value = `${before}${pad}${text} ${cur.slice(at)}`.replace(/\s+$/, " ");
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.focus();
  try {
    el.setSelectionRange(el.value.length, el.value.length);
  } catch {
    /* not a text field */
  }
  return true;
}

// ------------------------------------------------------------------ layout of a cartesian plot

function yAxis(g, ticks, y, x0, x1, fmt, right = false) {
  for (const v of ticks) {
    const yy = y(v);
    if (!right) g.append(s("line", { class: v === 0 ? "chart-axis" : "chart-grid", x1: x0, x2: x1, y1: yy, y2: yy }));
    g.append(
      s("text", { class: "chart-tick", x: right ? x1 + 6 : x0 - 6, y: yy + 4, "text-anchor": right ? "start" : "end" },
        fmt(v)),
    );
  }
} // prettier-ignore

/** x labels under a band of ``n`` slots: rotated when crowded, every k-th when still too tight. */
function xLabels(g, labels, cx, slot, baseY, maxRot = 40) {
  const widths = labels.map((l) => textW(l));
  const widest = Math.max(0, ...widths);
  let rotate = 0;
  let every = 1;
  if (widest > slot - 4) {
    rotate = maxRot; // every k-th label when even rotated ones would touch
    every = Math.max(1, Math.ceil(16 / Math.max(slot, 1)));
  }
  const maxLen = rotate ? 92 : slot - 2;
  labels.forEach((l, i) => {
    if (i % every) return;
    const x = cx(i);
    const t = fit(l, maxLen);
    g.append(
      rotate
        ? s("text", { class: "chart-label", x, y: baseY + 12, "text-anchor": "end",
            transform: `rotate(-${rotate} ${x} ${baseY + 12})` }, t) // prettier-ignore
        : s(
            "text",
            { class: "chart-label", x, y: baseY + 16, "text-anchor": "middle" },
            t,
          ),
    );
  });
  return rotate
    ? Math.min(
        70,
        Math.sin((rotate * Math.PI) / 180) * Math.min(92, widest) + 18,
      )
    : 24;
}

function extent(values) {
  const v = values.filter(num);
  if (!v.length) return [0, 1];
  return [Math.min(0, ...v), Math.max(0, ...v)];
}

// ------------------------------------------------------------------ the drawers
// each returns { g, H, hits: [{x, y, w, h, i, label, lines: [[name, text, k?]], tipX, tipY}] }

function drawCartesian(spec, ctx) {
  const { W, lang, visible } = ctx;
  const type = ctx.type;
  const labels = spec.labels;
  const n = labels.length;
  const series = spec.series
    .map((sr, j) => ({ ...sr, j }))
    .filter((sr) => visible[sr.j]);
  const stacked = type === "stacked" || type === "stacked_area";
  const combo = type === "combo";
  const left = series.filter((sr) => !(combo && sr.axis === "y2"));
  const right = combo ? series.filter((sr) => sr.axis === "y2") : [];
  let lo = 0;
  let hi = 1;
  if (stacked) {
    const pos = labels.map((_, i) =>
      left.reduce((a, sr) => a + Math.max(0, sr.values[i] || 0), 0),
    );
    const neg = labels.map((_, i) =>
      left.reduce((a, sr) => a + Math.min(0, sr.values[i] || 0), 0),
    );
    [lo, hi] = [Math.min(0, ...neg), Math.max(1e-9, ...pos)];
  } else [lo, hi] = extent(left.flatMap((sr) => sr.values));
  const target = (spec.annotations || []).find(
    (a) => a.kind === "target" && num(a.value),
  );
  if (target)
    [lo, hi] = [Math.min(lo, target.value), Math.max(hi, target.value)];
  if ((type === "line" || type === "area") && lo >= 0) {
    // a line of values far from 0 is read on its own range (an area always starts at 0)
    const vals = left.flatMap((sr) => sr.values).filter(num);
    const mn = Math.min(...vals);
    if (type === "line" && mn > 0 && mn > (hi - mn) * 1.5)
      lo = mn - (hi - mn) * 0.15;
  }
  const ticks = niceTicks(lo, hi);
  const unit = spec.unit || left[0]?.unit || "";
  const tf = (v) => fmtValue(v, unit, lang, true);
  const rTicks = right.length
    ? niceTicks(...extent(right.flatMap((sr) => sr.values)))
    : [];
  const rUnit = right[0]?.unit || "";
  const rf = (v) => fmtValue(v, rUnit, lang, true);
  const padL = Math.min(90, Math.max(...ticks.map((v) => textW(tf(v)))) + 14);
  const padR = right.length
    ? Math.min(80, Math.max(...rTicks.map((v) => textW(rf(v)))) + 14)
    : 14;
  const plotW = Math.max(60, W - padL - padR);
  const slot = plotW / Math.max(1, n);
  const top = 18;
  const plotH = W < 420 ? 190 : 240;
  const y = (v) =>
    top +
    plotH -
    ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0] || 1)) * plotH;
  const yr = rTicks.length
    ? (v) =>
        top +
        plotH -
        ((v - rTicks[0]) / (rTicks[rTicks.length - 1] - rTicks[0] || 1)) * plotH
    : y;
  const g = s("g", null);
  yAxis(g, ticks, y, padL, padL + plotW, tf);
  if (right.length) yAxis(g, rTicks, yr, padL, padL + plotW, rf, true);
  const lineLike =
    type === "line" || type === "area" || type === "stacked_area";
  // a line keeps a margin at both ends, so the first and last labels are never cut by the card's edge
  const inset = lineLike && n > 1 ? Math.min(28, plotW / (n - 1) / 2, textW(labels[n - 1] || "") / 2 + 2) : 0;
  const span = plotW - 2 * inset;
  const cx = (i) =>
    lineLike
      ? padL + inset + (n === 1 ? span / 2 : (i * span) / Math.max(1, n - 1))
      : padL + slot * (i + 0.5);
  const xh = xLabels(
    g,
    labels,
    cx,
    lineLike ? span / Math.max(1, n - 1) : slot,
    top + plotH,
  );
  const hits = [];
  const fmt = (v, u = unit) => fmtValue(v, u, lang);
  const barsOf = combo
    ? left.filter((sr) => sr.mark !== "line")
    : lineLike
      ? []
      : left;
  const linesOf = combo
    ? [...left.filter((sr) => sr.mark === "line"), ...right]
    : lineLike
      ? left
      : [];
  // ---- bars
  if (barsOf.length) {
    const grouped = !stacked && barsOf.length > 1;
    const bw = Math.max(2, Math.min(64, slot * (grouped ? 0.8 : 0.66)));
    const each = grouped ? bw / barsOf.length : bw;
    const base = y(Math.max(ticks[0], Math.min(0, ticks[ticks.length - 1])));
    labels.forEach((_, i) => {
      let accP = 0;
      let accN = 0;
      barsOf.forEach((sr, k) => {
        const v = sr.values[i];
        if (!num(v)) return;
        let y0;
        let y1;
        if (stacked) {
          const from = v >= 0 ? accP : accN;
          if (v >= 0) accP += v;
          else accN += v;
          y0 = y(from);
          y1 = y(from + v);
        } else {
          y0 = base;
          y1 = y(v);
        }
        const x = cx(i) - bw / 2 + (grouped ? k * each : 0);
        const top_ = Math.min(y0, y1);
        const hgt = Math.max(1, Math.abs(y1 - y0));
        const r = Math.min(4, each / 3, hgt / 2);
        g.append(s("path", { class: `c2-mark series-${cls(sr.j)}`, "data-i": i,
          d: v >= 0 || stacked
            ? `M${x},${top_ + hgt}V${top_ + r}Q${x},${top_} ${x + r},${top_}H${x + each - (grouped ? 1 : 0) - r}Q${x + each - (grouped ? 1 : 0)},${top_} ${x + each - (grouped ? 1 : 0)},${top_ + r}V${top_ + hgt}Z`
            : `M${x},${top_}H${x + each - (grouped ? 1 : 0)}V${top_ + hgt - r}Q${x + each - (grouped ? 1 : 0)},${top_ + hgt} ${x + each - (grouped ? 1 : 0) - r},${top_ + hgt}H${x + r}Q${x},${top_ + hgt} ${x},${top_ + hgt - r}Z` })); // prettier-ignore
        if (!grouped && !stacked && !combo && n <= 14 && slot > textW(fmtValue(v, unit, lang, true)) + 4)
          g.append(s("text", { class: "chart-value", x: x + each / 2, y: v >= 0 ? top_ - 5 : top_ + hgt + 13,
            "text-anchor": "middle" }, fmtValue(v, unit, lang, true))); // prettier-ignore
      });
    });
  }
  // ---- lines / areas
  if (linesOf.length) {
    const acc = labels.map(() => 0);
    linesOf.forEach((sr) => {
      const yy = right.includes(sr) ? yr : y;
      const pts = [];
      sr.values.forEach((v, i) => {
        if (!num(v)) return;
        const val = type === "stacked_area" ? (acc[i] += v) : v;
        pts.push([cx(i), yy(val), i, val]);
      });
      if (!pts.length) return;
      const d = pts
        .map(
          ([px, py], k) => `${k ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`,
        )
        .join("");
      if (type === "area" || type === "stacked_area") {
        const prev = type === "stacked_area" ? null : yy(Math.max(ticks[0], 0));
        const lower = type === "stacked_area" && sr !== linesOf[0]
          ? pts.slice().reverse().map(([px, , i]) => `L${px.toFixed(1)},${yy(acc[i] - sr.values[i]).toFixed(1)}`).join("")
          : `L${pts[pts.length - 1][0].toFixed(1)},${prev ?? yy(0)}L${pts[0][0].toFixed(1)},${prev ?? yy(0)}`; // prettier-ignore
        g.append(
          s("path", {
            class: `c2-area series-${cls(sr.j)}`,
            d: `${d}${lower}Z`,
          }),
        );
      }
      g.append(
        s("path", {
          class: `c2-line stroke-${cls(sr.j)}${sr.axis === "y2" ? " is-y2" : ""}`,
          d,
        }),
      );
      if (pts.length <= 36)
        for (const [px, py, i] of pts)
          g.append(
            s("circle", {
              class: `c2-dot c2-mark series-${cls(sr.j)}`,
              "data-i": i,
              cx: px,
              cy: py,
              r: 3.2,
            }),
          );
    });
  }
  // ---- annotations: max / min of the first series, mean, target
  const first = left[0];
  for (const a of spec.annotations || []) {
    if (!first) break;
    const vals = first.values;
    if (a.kind === "max" || a.kind === "min") {
      const pick = vals.reduce((best, v, i) => (num(v) && (best < 0 || (a.kind === "max" ? v > vals[best] : v < vals[best])) ? i : best), -1); // prettier-ignore
      if (pick < 0 || (a.kind === "min" && vals.filter(num).length < 3))
        continue;
      const px = cx(pick);
      const py = y(vals[pick]);
      const txt = `${L(lang)[a.kind]} ${fmtValue(vals[pick], unit, lang, true)}`;
      const tw = textW(txt, 11) + 10;
      const bx = Math.max(padL, Math.min(padL + plotW - tw, px - tw / 2));
      const by =
        a.kind === "max"
          ? Math.max(0, py - 26)
          : Math.min(top + plotH - 18, py + 9);
      g.append(s("g", { class: `c2-annot is-${a.kind}` },
        s("rect", { x: bx, y: by, width: tw, height: 17, rx: 8.5 }),
        s("text", { x: bx + tw / 2, y: by + 12, "text-anchor": "middle" }, txt))); // prettier-ignore
    } else if (a.kind === "target" || a.kind === "mean") {
      const v =
        a.kind === "target"
          ? a.value
          : vals.filter(num).reduce((p, q) => p + q, 0) /
            Math.max(1, vals.filter(num).length);
      if (!num(v)) continue;
      const yy = y(v);
      g.append(
        s("line", {
          class: "c2-ref",
          x1: padL,
          x2: padL + plotW,
          y1: yy,
          y2: yy,
        }),
      );
      g.append(s("text", { class: "c2-ref-text", x: padL + plotW - 2, y: yy - 5, "text-anchor": "end" },
        `${a.label || L(lang)[a.kind]} ${fmtValue(v, unit, lang, true)}`)); // prettier-ignore
    }
  }
  // ---- hit areas, one per label
  labels.forEach((label, i) => {
    const x0 = lineLike
      ? cx(i) - span / Math.max(1, n - 1) / 2
      : padL + slot * i;
    const w = lineLike ? span / Math.max(1, n - 1) : slot;
    const vis = series.filter((sr) => num(sr.values[i]));
    const peak = Math.min(
      ...vis.map((sr) => (right.includes(sr) ? yr : y)(sr.values[i])),
      top + plotH,
    );
    hits.push({ x: Math.max(padL, x0), y: top, w: Math.min(w, padL + plotW - Math.max(padL, x0)), h: plotH, i, label,
      lines: series.map((sr) => [sr.name, fmt(sr.values[i], right.includes(sr) ? rUnit : unit), cls(sr.j)]),
      tipX: cx(i) / W, tipY: peak - 8 }); // prettier-ignore
  });
  return { g, H: top + plotH + xh + 6, hits };
}

function drawHBar(spec, ctx) {
  const { W, lang, visible } = ctx;
  const series = spec.series
    .map((sr, j) => ({ ...sr, j }))
    .filter((sr) => visible[sr.j]);
  const labels = spec.labels;
  const unit = spec.unit || series[0]?.unit || "";
  const [lo, hi] = extent(series.flatMap((sr) => sr.values));
  const ticks = niceTicks(lo, hi, W < 420 ? 3 : 5);
  const padL = Math.min(
    W * 0.38,
    Math.max(...labels.map((l) => textW(l))) + 14,
  );
  const valW =
    Math.max(
      ...series
        .flatMap((sr) => sr.values)
        .map((v) => textW(fmtValue(v, unit, lang, true))),
    ) + 10;
  const plotW = Math.max(60, W - padL - valW - 6);
  const row = series.length > 1 ? 14 * series.length + 10 : 26;
  const top = 6;
  const x = (v) =>
    padL + ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0] || 1)) * plotW;
  const g = s("g", null);
  const H = top + row * labels.length + 22;
  for (const v of ticks) {
    g.append(
      s("line", {
        class: v === 0 ? "chart-axis" : "chart-grid",
        x1: x(v),
        x2: x(v),
        y1: top,
        y2: H - 20,
      }),
    );
    g.append(
      s(
        "text",
        { class: "chart-tick", x: x(v), y: H - 6, "text-anchor": "middle" },
        fmtValue(v, unit, lang, true),
      ),
    );
  }
  const hits = [];
  labels.forEach((label, i) => {
    const y0 = top + row * i;
    g.append(s("text", { class: "chart-label", x: padL - 8, y: y0 + row / 2 + 4, "text-anchor": "end" },
      fit(label, padL - 12))); // prettier-ignore
    const bh = series.length > 1 ? 12 : 16;
    series.forEach((sr, k) => {
      const v = sr.values[i];
      if (!num(v)) return;
      const yy =
        y0 +
        (row - bh * series.length - (series.length - 1) * 2) / 2 +
        k * (bh + 2);
      const a = x(Math.max(0, ticks[0]));
      const b = x(v);
      const xx = Math.min(a, b);
      const w = Math.max(1, Math.abs(b - a));
      const r = Math.min(4, w / 2, bh / 2);
      g.append(s("path", { class: `c2-mark series-${cls(sr.j)}`, "data-i": i,
        d: v >= 0 ? `M${xx},${yy}H${xx + w - r}Q${xx + w},${yy} ${xx + w},${yy + r}V${yy + bh - r}Q${xx + w},${yy + bh} ${xx + w - r},${yy + bh}H${xx}Z`
          : `M${xx + w},${yy}H${xx + r}Q${xx},${yy} ${xx},${yy + r}V${yy + bh - r}Q${xx},${yy + bh} ${xx + r},${yy + bh}H${xx + w}Z` })); // prettier-ignore
      g.append(s("text", { class: "chart-value", x: v >= 0 ? xx + w + 5 : xx - 5, y: yy + bh / 2 + 4,
        "text-anchor": v >= 0 ? "start" : "end" }, fmtValue(v, unit, lang, true))); // prettier-ignore
    });
    hits.push({ x: 0, y: y0, w: W, h: row, i, label, tipX: Math.min(0.8, (padL + plotW * 0.6) / W), tipY: y0 - 4,
      lines: series.map((sr) => [sr.name, fmtValue(sr.values[i], unit, lang), cls(sr.j)]) }); // prettier-ignore
  });
  return { g, H, hits };
}

function arc(cx, cy, r, a0, a1) {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const p = (a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return { x0, y0, x1, y1, large };
}

function drawPie(spec, ctx) {
  const { W, lang, visible } = ctx;
  const donut = ctx.type === "donut";
  const sr = spec.series[0];
  const unit = spec.unit || sr.unit || "";
  const items = spec.labels
    .map((label, i) => ({ label, v: sr.values[i], i }))
    .filter((x) => num(x.v) && x.v > 0 && visible[`p${x.i}`] !== false);
  const total = items.reduce((a, x) => a + x.v, 0);
  const H = Math.min(300, Math.max(200, W * 0.55));
  const r = H / 2 - 14;
  const cx = W < 520 ? W / 2 : Math.min(W / 2, r + 40);
  const cy = H / 2;
  const g = s("g", null);
  const hits = [];
  let a = 0;
  for (const it of items) {
    const sweep = (it.v / total) * Math.PI * 2;
    const a1 = a + sweep;
    const ri = donut ? r * 0.58 : 0;
    let d;
    if (sweep >= Math.PI * 2 - 1e-6) {
      d =
        `M${cx},${cy - r}A${r},${r} 0 1 1 ${cx - 0.01},${cy - r}Z` +
        (donut
          ? `M${cx},${cy - ri}A${ri},${ri} 0 1 0 ${cx + 0.01},${cy - ri}Z`
          : "");
    } else {
      const o = arc(cx, cy, r, a, a1);
      if (donut) {
        const ii = arc(cx, cy, ri, a, a1);
        d = `M${o.x0},${o.y0}A${r},${r} 0 ${o.large} 1 ${o.x1},${o.y1}L${ii.x1},${ii.y1}A${ri},${ri} 0 ${o.large} 0 ${ii.x0},${ii.y0}Z`;
      } else
        d = `M${cx},${cy}L${o.x0},${o.y0}A${r},${r} 0 ${o.large} 1 ${o.x1},${o.y1}Z`;
    }
    const k = Math.min(it.i, 7) + 1;
    const path = s("path", {
      class: `c2-mark c2-slice series-${k}`,
      "data-i": it.i,
      d,
    });
    g.append(path);
    const mid = a + sweep / 2;
    const share = (it.v / total) * 100;
    if (share >= 7) {
      const lr = donut ? r * 0.79 : r * 0.64;
      g.append(s("text", { class: "c2-slice-text", x: cx + lr * Math.sin(mid), y: cy - lr * Math.cos(mid) + 4,
        "text-anchor": "middle" }, fmtValue(Math.round(share), "%", lang))); // prettier-ignore
    }
    hits.push({ path, i: it.i, label: it.label, tipX: (cx + r * 0.7 * Math.sin(mid)) / W, tipY: cy - r * 0.7 * Math.cos(mid),
      lines: [[sr.name, `${fmtValue(it.v, unit, lang)} (${fmtValue(Math.round(share * 10) / 10, "%", lang)})`, k]] }); // prettier-ignore
    a = a1;
  }
  if (donut) {
    g.append(
      s(
        "text",
        { class: "c2-donut-total", x: cx, y: cy + 2, "text-anchor": "middle" },
        fmtValue(total, unit, lang, true),
      ),
    );
    g.append(
      s(
        "text",
        { class: "c2-donut-label", x: cx, y: cy + 20, "text-anchor": "middle" },
        L(lang).total,
      ),
    );
  }
  return { g, H, hits };
}

function drawScatter(spec, ctx) {
  const { W, lang } = ctx;
  const pts = spec.points || [];
  const [ux, uy] = spec.units || ["", ""];
  const xs = pts.map((p) => p[1]);
  const ys = pts.map((p) => p[2]);
  const pad = (lo, hi) => [lo - (hi - lo) * 0.05, hi + (hi - lo) * 0.05];
  const xt = niceTicks(
    ...pad(Math.min(...xs), Math.max(...xs)),
    W < 420 ? 4 : 6,
  );
  const yt = niceTicks(...pad(Math.min(...ys), Math.max(...ys)));
  const yf = (v) => fmtValue(v, uy, lang, true);
  const padL = Math.min(80, Math.max(...yt.map((v) => textW(yf(v)))) + 14);
  const top = 12;
  const plotW = W - padL - 16;
  const plotH = W < 420 ? 200 : 250;
  const x = (v) =>
    padL + ((v - xt[0]) / (xt[xt.length - 1] - xt[0] || 1)) * plotW;
  const y = (v) =>
    top + plotH - ((v - yt[0]) / (yt[yt.length - 1] - yt[0] || 1)) * plotH;
  const g = s("g", null);
  yAxis(g, yt, y, padL, padL + plotW, yf);
  for (const v of xt) {
    g.append(
      s("line", {
        class: "chart-grid",
        x1: x(v),
        x2: x(v),
        y1: top,
        y2: top + plotH,
      }),
    );
    g.append(
      s(
        "text",
        {
          class: "chart-tick",
          x: x(v),
          y: top + plotH + 16,
          "text-anchor": "middle",
        },
        fmtValue(v, ux, lang, true),
      ),
    );
  }
  const axes = spec.axes || [];
  if (axes[0])
    g.append(
      s(
        "text",
        {
          class: "c2-axis-name",
          x: padL + plotW,
          y: top + plotH + 34,
          "text-anchor": "end",
        },
        axes[0],
      ),
    );
  if (axes[1])
    g.append(
      s(
        "text",
        { class: "c2-axis-name", x: padL, y: top - 2, "text-anchor": "start" },
        `↑ ${axes[1]}`,
      ),
    );
  // least-squares trend line, drawn only when the correlation is not weak
  const r = spec.stat?.r;
  if (num(r) && Math.abs(r) >= 0.3 && pts.length >= 3) {
    const mx = xs.reduce((a, b) => a + b, 0) / xs.length;
    const my = ys.reduce((a, b) => a + b, 0) / ys.length;
    const sxy = xs.reduce((a, v, i) => a + (v - mx) * (ys[i] - my), 0);
    const sxx = xs.reduce((a, v) => a + (v - mx) ** 2, 0) || 1;
    const b = sxy / sxx;
    const a0 = my - b * mx;
    const [x0, x1] = [xt[0], xt[xt.length - 1]];
    const clampY = (v) => Math.max(yt[0], Math.min(yt[yt.length - 1], v));
    g.append(
      s("line", {
        class: "c2-trend",
        x1: x(x0),
        y1: y(clampY(a0 + b * x0)),
        x2: x(x1),
        y2: y(clampY(a0 + b * x1)),
      }),
    );
  }
  const sizes = pts.map((p) => p[3]).filter(num);
  const smax = Math.max(1e-9, ...sizes);
  const hits = [];
  const many = pts.length > 300;
  pts.forEach((p, i) => {
    const rad =
      ctx.type === "bubble" && num(p[3])
        ? 4 + 16 * Math.sqrt(p[3] / smax)
        : many
          ? 2.2
          : 4;
    const c = s("circle", {
      class: `c2-mark c2-pt series-1${ctx.type === "bubble" ? " is-bubble" : ""}`,
      "data-i": i,
      cx: x(p[1]),
      cy: y(p[2]),
      r: rad,
    });
    g.append(c);
    if (!many)
      hits.push({ path: c, i, label: p[0], tipX: x(p[1]) / W, tipY: y(p[2]) - rad - 4,
        lines: [[axes[0] || "x", fmtValue(p[1], ux, lang), 1], [axes[1] || "y", fmtValue(p[2], uy, lang), 1],
          ...(num(p[3]) ? [["", fmtValue(p[3], "", lang), 1]] : [])] }); // prettier-ignore
  });
  return { g, H: top + plotH + 40, hits };
}

function drawHistogram(spec, ctx) {
  const { W, lang } = ctx;
  const bins = spec.bins || {};
  const counts = bins.counts || [];
  const lo = bins.lo ?? 0;
  const hi = bins.hi ?? 1;
  const unit = spec.unit || "";
  const step = (hi - lo) / Math.max(1, counts.length);
  const labels = counts.map(
    (_, i) =>
      `${fmtValue(lo + i * step, unit, lang, true)} – ${fmtValue(lo + (i + 1) * step, unit, lang, true)}`,
  );
  const ticks = niceTicks(0, Math.max(1, ...counts));
  const padL = 40;
  const top = 12;
  const plotW = W - padL - 12;
  const plotH = W < 420 ? 180 : 220;
  const y = (v) => top + plotH - (v / (ticks[ticks.length - 1] || 1)) * plotH;
  const g = s("g", null);
  yAxis(g, ticks, y, padL, padL + plotW, (v) => fmtValue(v, "", lang));
  const bw = plotW / Math.max(1, counts.length);
  const hits = [];
  counts.forEach((c, i) => {
    const x0 = padL + i * bw;
    g.append(
      s("rect", {
        class: "c2-mark series-1",
        "data-i": i,
        x: x0 + 1,
        y: y(c),
        width: Math.max(1, bw - 2),
        height: Math.max(0, top + plotH - y(c)),
        rx: 2,
      }),
    );
    hits.push({ x: x0, y: top, w: bw, h: plotH, i, label: labels[i], tipX: (x0 + bw / 2) / W, tipY: y(c) - 6,
      lines: [[lang === "en" ? "Rows" : "Lignes", fmtValue(c, "", lang), 1]] }); // prettier-ignore
  });
  const edge = [0, Math.floor(counts.length / 2), counts.length];
  for (const k of edge)
    g.append(s("text", { class: "chart-tick", x: padL + k * bw, y: top + plotH + 16, "text-anchor": k === 0 ? "start" : k === counts.length ? "end" : "middle" },
      fmtValue(lo + k * step, unit, lang, true))); // prettier-ignore
  return { g, H: top + plotH + 26, hits };
}

function drawBox(spec, ctx) {
  const { W, lang } = ctx;
  const b = spec.box || {};
  const unit = spec.unit || "";
  const vals = [b.min, b.max, ...(b.outliers || [])].filter(num);
  const ticks = niceTicks(
    Math.min(...vals),
    Math.max(...vals),
    W < 420 ? 4 : 6,
  );
  const padL = 28;
  const plotW = W - 56;
  const x = (v) =>
    padL + ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0] || 1)) * plotW;
  const g = s("g", null);
  const cy = 60;
  for (const v of ticks) {
    g.append(
      s("line", { class: "chart-grid", x1: x(v), x2: x(v), y1: 20, y2: 104 }),
    );
    g.append(
      s(
        "text",
        { class: "chart-tick", x: x(v), y: 122, "text-anchor": "middle" },
        fmtValue(v, unit, lang, true),
      ),
    );
  }
  g.append(
    s("line", {
      class: "c2-whisker",
      x1: x(b.min),
      x2: x(b.q1),
      y1: cy,
      y2: cy,
    }),
  );
  g.append(
    s("line", {
      class: "c2-whisker",
      x1: x(b.q3),
      x2: x(b.max),
      y1: cy,
      y2: cy,
    }),
  );
  for (const v of [b.min, b.max])
    g.append(
      s("line", {
        class: "c2-whisker",
        x1: x(v),
        x2: x(v),
        y1: cy - 12,
        y2: cy + 12,
      }),
    );
  g.append(
    s("rect", {
      class: "c2-mark c2-box series-1",
      "data-i": 0,
      x: x(b.q1),
      y: cy - 22,
      width: Math.max(2, x(b.q3) - x(b.q1)),
      height: 44,
      rx: 6,
    }),
  );
  g.append(
    s("line", {
      class: "c2-median",
      x1: x(b.median),
      x2: x(b.median),
      y1: cy - 22,
      y2: cy + 22,
    }),
  );
  if (num(b.mean))
    g.append(
      s("path", {
        class: "c2-mean",
        d: `M${x(b.mean)},${cy - 6}l6,6l-6,6l-6,-6z`,
      }),
    );
  for (const o of b.outliers || [])
    g.append(s("circle", { class: "c2-outlier", cx: x(o), cy, r: 3.5 }));
  const w = L(lang);
  const lines = [
    ["min", b.min],
    [w.q1, b.q1],
    [w.median, b.median],
    [w.mean, b.mean],
    [w.q3, b.q3],
    ["max", b.max],
  ].map(([k, v]) => [k, fmtValue(v, unit, lang), 1]);
  return { g, H: 132, hits: [{ x: x(b.min) - 6, y: cy - 26, w: x(b.max) - x(b.min) + 12, h: 52, i: 0, label: spec.title, lines,
    tipX: x(b.median) / W, tipY: cy - 30 }] }; // prettier-ignore
}

function drawHeatmap(spec, ctx) {
  const { W, lang } = ctx;
  const rows = spec.matrix?.rows || spec.labels;
  const cols = spec.matrix?.cols || spec.series.map((sr) => sr.name);
  const values =
    spec.matrix?.values ||
    rows.map((_, i) => spec.series.map((sr) => sr.values[i]));
  const flat = values.flat().filter(num);
  const lo = Math.min(...flat);
  const hi = Math.max(...flat);
  const padL = Math.min(W * 0.32, Math.max(...rows.map((r) => textW(r))) + 12);
  const cw = (W - padL - 8) / Math.max(1, cols.length);
  const ch = 30;
  const g = s("g", null);
  const hits = [];
  cols.forEach((c, j) =>
    g.append(
      s(
        "text",
        {
          class: "chart-label",
          x: padL + cw * (j + 0.5),
          y: 14,
          "text-anchor": "middle",
        },
        fit(c, cw - 4),
      ),
    ),
  );
  rows.forEach((r, i) => {
    const y0 = 22 + i * ch;
    g.append(
      s(
        "text",
        {
          class: "chart-label",
          x: padL - 8,
          y: y0 + ch / 2 + 4,
          "text-anchor": "end",
        },
        fit(r, padL - 10),
      ),
    );
    cols.forEach((c, j) => {
      const v = values[i]?.[j];
      const t = num(v) ? (v - lo) / (hi - lo || 1) : 0;
      const cell = s("rect", { class: `c2-mark c2-heat series-1${num(v) ? "" : " is-empty"}`, "data-i": i, x: padL + cw * j + 1, y: y0 + 1, width: cw - 2, height: ch - 2, rx: 4,
        "fill-opacity": num(v) ? (0.12 + 0.88 * t).toFixed(3) : 0.04 }); // prettier-ignore
      g.append(cell);
      if (num(v) && cw > 34)
        g.append(s("text", { class: `c2-heat-text${t > 0.55 ? " is-dark" : ""}`, x: padL + cw * (j + 0.5), y: y0 + ch / 2 + 4, "text-anchor": "middle" },
          fmtValue(v, spec.unit, lang, true))); // prettier-ignore
      hits.push({
        path: cell,
        i,
        label: `${r} · ${c}`,
        tipX: (padL + cw * (j + 0.5)) / W,
        tipY: y0 - 4,
        lines: [["", fmtValue(v, spec.unit, lang), 1]],
      });
    });
  });
  return { g, H: 26 + rows.length * ch, hits };
}

function drawWaterfall(spec, ctx) {
  const { W, lang } = ctx;
  const sr = spec.series[0];
  const unit = spec.unit || sr.unit || "";
  const labels = [...spec.labels, L(lang).total];
  let acc = 0;
  const steps = sr.values.map((v) => {
    const from = acc;
    acc += num(v) ? v : 0;
    return [from, acc, v];
  });
  steps.push([0, acc, acc]);
  const ticks = niceTicks(
    Math.min(0, ...steps.flatMap((x) => x.slice(0, 2)).filter(num)),
    Math.max(0, ...steps.flatMap((x) => x.slice(0, 2)).filter(num)),
  );
  const tf = (v) => fmtValue(v, unit, lang, true);
  const padL = Math.min(90, Math.max(...ticks.map((v) => textW(tf(v)))) + 14);
  const plotW = W - padL - 12;
  const plotH = W < 420 ? 190 : 230;
  const top = 18;
  const y = (v) =>
    top +
    plotH -
    ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0] || 1)) * plotH;
  const slot = plotW / labels.length;
  const g = s("g", null);
  yAxis(g, ticks, y, padL, padL + plotW, tf);
  const hits = [];
  steps.forEach(([a, b, v], i) => {
    const last = i === steps.length - 1;
    const x = padL + slot * i + slot * 0.17;
    const w = slot * 0.66;
    const k = last ? 1 : v >= 0 ? 3 : 2;
    g.append(
      s("rect", {
        class: `c2-mark series-${k}`,
        "data-i": i,
        x,
        y: Math.min(y(a), y(b)),
        width: w,
        height: Math.max(1, Math.abs(y(a) - y(b))),
        rx: 3,
      }),
    );
    if (!last)
      g.append(
        s("line", {
          class: "c2-connector",
          x1: x + w,
          x2: x + slot,
          y1: y(b),
          y2: y(b),
        }),
      );
    if (slot > 48) g.append(s("text", { class: "chart-value", x: x + w / 2, y: Math.min(y(a), y(b)) - 5, "text-anchor": "middle" },
      `${!last && v > 0 ? "+" : ""}${fmtValue(v, unit, lang, true)}`)); // prettier-ignore
    hits.push({ x: padL + slot * i, y: top, w: slot, h: plotH, i, label: labels[i], tipX: (x + w / 2) / W, tipY: Math.min(y(a), y(b)) - 8,
      lines: [[last ? L(lang).total : sr.name, fmtValue(v, unit, lang), k], [L(lang).cumul, fmtValue(b, unit, lang), k]] }); // prettier-ignore
  });
  const xh = xLabels(
    g,
    labels,
    (i) => padL + slot * (i + 0.5),
    slot,
    top + plotH,
  );
  return { g, H: top + plotH + xh + 6, hits };
}

function drawFunnel(spec, ctx) {
  const { W, lang } = ctx;
  const sr = spec.series[0];
  const unit = spec.unit || sr.unit || "";
  const vals = sr.values.map((v) => (num(v) ? v : 0));
  const maxV = Math.max(1e-9, ...vals);
  const row = 34;
  const g = s("g", null);
  const hits = [];
  const labW = Math.min(
    W * 0.3,
    Math.max(...spec.labels.map((l) => textW(l))) + 12,
  );
  const plotW = W - labW - 12;
  spec.labels.forEach((label, i) => {
    const w = Math.max(4, (vals[i] / maxV) * plotW);
    const x = labW + (plotW - w) / 2;
    const y0 = 4 + i * row;
    g.append(
      s("rect", {
        class: `c2-mark series-${cls(i)}`,
        "data-i": i,
        x,
        y: y0,
        width: w,
        height: row - 6,
        rx: 5,
      }),
    );
    g.append(
      s(
        "text",
        {
          class: "chart-label",
          x: labW - 8,
          y: y0 + row / 2 + 1,
          "text-anchor": "end",
        },
        fit(label, labW - 10),
      ),
    );
    const pct = vals[0] ? Math.round((vals[i] / vals[0]) * 1000) / 10 : null;
    const txt = `${fmtValue(vals[i], unit, lang, true)}${i && pct !== null ? ` · ${fmtValue(pct, "%", lang)}` : ""}`;
    const inside = textW(txt) + 12 < w;
    g.append(s("text", { class: inside ? "c2-on-mark" : "chart-value", x: inside ? x + w / 2 : x + w + 6, y: y0 + row / 2 + 1,
      "text-anchor": inside ? "middle" : "start" }, txt)); // prettier-ignore
    hits.push({ x: 0, y: y0, w: W, h: row, i, label, tipX: 0.5, tipY: y0 - 4,
      lines: [[sr.name, fmtValue(vals[i], unit, lang), cls(i)], ...(i && pct !== null ? [[L(lang).ofFirst, fmtValue(pct, "%", lang), cls(i)]] : [])] }); // prettier-ignore
  });
  return { g, H: 8 + row * spec.labels.length, hits };
}

function drawKpi(spec, ctx) {
  const { W, lang } = ctx;
  const k = spec.kpi || {};
  const unit = spec.unit || "";
  const g = s("g", null);
  g.append(
    s(
      "text",
      { class: "c2-kpi-value", x: 8, y: 46 },
      fmtValue(k.value, unit, lang),
    ),
  );
  g.append(s("text", { class: "c2-kpi-label", x: 8, y: 70 }, k.label || ""));
  const spark = (k.spark || []).filter(num);
  if (spark.length >= 2) {
    const sw = Math.min(220, W * 0.4);
    const x0 = W - sw - 8;
    const lo = Math.min(...spark);
    const hi = Math.max(...spark);
    const d = spark
      .map(
        (v, i) =>
          `${i ? "L" : "M"}${(x0 + (i * sw) / (spark.length - 1)).toFixed(1)},${(64 - ((v - lo) / (hi - lo || 1)) * 44).toFixed(1)}`,
      )
      .join("");
    g.append(s("path", { class: "c2-line stroke-1", d }));
  }
  return { g, H: 84, hits: [] };
}

const DRAW = {
  bar: drawCartesian, stacked: drawCartesian, line: drawCartesian, area: drawCartesian, stacked_area: drawCartesian,
  combo: drawCartesian, hbar: drawHBar, pie: drawPie, donut: drawPie, scatter: drawScatter, bubble: drawScatter,
  histogram: drawHistogram, box: drawBox, heatmap: drawHeatmap, waterfall: drawWaterfall, funnel: drawFunnel,
  kpi: drawKpi,
}; // prettier-ignore

// ------------------------------------------------------------------ export

export function chartCsv(spec, lang) {
  const sep = lang === "en" ? "," : ";";
  const cell = (v) => {
    if (num(v)) return lang === "en" ? String(v) : String(v).replace(".", ",");
    let x = String(v ?? "");
    if (/^[=+\-@\t\r]/.test(x)) x = `'${x}`;
    return /["\n\r;,]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x;
  };
  if (spec.points)
    return [
      ["", ...(spec.axes || ["x", "y"])].map(cell).join(sep),
      ...spec.points.map((p) => p.slice(0, 3).map(cell).join(sep)),
    ].join("\n");
  return [
    [spec.x?.name || "", ...spec.series.map((sr) => sr.name)]
      .map(cell)
      .join(sep),
    ...spec.labels.map((l, i) =>
      [l, ...spec.series.map((sr) => sr.values[i])].map(cell).join(sep),
    ),
  ].join("\n");
}

export function chartMarkdown2(spec, lang) {
  const c = (v) => String(v).replace(/\|/g, "\\|");
  if (spec.points) {
    const ax = spec.axes || ["x", "y"];
    return [`| | ${c(ax[0])} | ${c(ax[1])} |`, "| --- | --- | --- |",
      ...spec.points.slice(0, 200).map((p) => `| ${c(p[0])} | ${fmtValue(p[1], "", lang)} | ${fmtValue(p[2], "", lang)} |`)].join("\n"); // prettier-ignore
  }
  const head = [spec.x?.name || "", ...spec.series.map((sr) => sr.name)];
  return [`| ${head.map(c).join(" | ")} |`, `| ${head.map(() => "---").join(" | ")} |`,
    ...spec.labels.map((l, i) => `| ${[c(l), ...spec.series.map((sr) => c(fmtValue(sr.values[i], sr.unit || spec.unit, lang)))].join(" | ")} |`)].join("\n"); // prettier-ignore
}

function sanitize(name) {
  return String(name || "graphique").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 60) || "graphique"; // prettier-ignore
}

/** A standalone light SVG (title, plot, legend, source line), colours copied from the computed styles. */
function standalone(svg, { title, foot, legend }) {
  const root = document.documentElement;
  const prev = root.dataset.theme;
  root.dataset.theme = "light";
  let text;
  try {
    const props = [
      "fill",
      "stroke",
      "stroke-width",
      "stroke-dasharray",
      "opacity",
      "fill-opacity",
      "font-size",
      "font-weight",
    ];
    const src = [svg, ...svg.querySelectorAll("*")];
    const styles = src.map((el) => {
      const cs = getComputedStyle(el);
      return Object.fromEntries(props.map((p) => [p, cs.getPropertyValue(p)]));
    });
    const sw = legend.map((k) => {
      const el = document.createElement("span");
      el.className = `series-bg-${k}`;
      document.body.append(el);
      const c = getComputedStyle(el).backgroundColor;
      el.remove();
      return c;
    });
    const rcs = getComputedStyle(root);
    const ink = rcs.getPropertyValue("--ink").trim() || "#121a2e";
    const muted = rcs.getPropertyValue("--muted").trim() || "#586078";
    const surface = rcs.getPropertyValue("--surface").trim() || "#ffffff";
    const plot = svg.cloneNode(true);
    [plot, ...plot.querySelectorAll("*")].forEach((el, i) => {
      for (const p of props)
        if (
          styles[i][p] &&
          !(p === "fill-opacity" && el.getAttribute("fill-opacity"))
        )
          el.setAttribute(p, styles[i][p]);
      el.removeAttribute("class");
    });
    for (const r of plot.querySelectorAll(".c2-hit, [data-hit]")) r.remove();
    const vb = svg.viewBox.baseVal;
    const head = 34;
    const items = legend.map((k, i) => [k, sw[i]]);
    const H = head + vb.height + (items.length ? 24 : 0) + 30;
    const k = Math.max(2, 1280 / vb.width);
    let lx = 16;
    const out = s("svg", { xmlns: NS, viewBox: `0 0 ${vb.width} ${H}`, width: Math.round(vb.width * k), height: Math.round(H * k), "font-family": "system-ui, sans-serif" },
      s("rect", { x: 0, y: 0, width: vb.width, height: H, fill: surface }),
      s("text", { x: 16, y: 24, "font-size": 16, "font-weight": 650, fill: ink }, fit(title, vb.width - 32, 16)),
      s("g", { transform: `translate(0 ${head})` }, ...plot.childNodes),
      ...(foot.legendNames || []).map((name, i) => {
        const x = lx;
        lx += textW(name) + 30;
        return s("g", null, s("rect", { x, y: head + vb.height + 6, width: 10, height: 10, rx: 2, fill: items[i]?.[1] || ink }),
          s("text", { x: x + 15, y: head + vb.height + 15, "font-size": 12, fill: ink }, name)); // prettier-ignore
      }),
      s("text", { x: 16, y: H - 10, "font-size": 11, fill: muted }, foot.line)); // prettier-ignore
    text = new XMLSerializer().serializeToString(out);
    return { text, w: Math.round(vb.width * k), h: Math.round(H * k) };
  } finally {
    if (prev === undefined) delete root.dataset.theme;
    else root.dataset.theme = prev;
  }
}

// ------------------------------------------------------------------ the card

let seq = 0;

/** A v2 chart card. ``onDrill(label, series)`` defaults to « Détaille … » in the composer. */
export function renderChart2(
  spec,
  { lang = state.prefs?.lang || "fr", onDrill, compact = false } = {},
) {
  if (!spec || !DRAW[spec.type]) return null;
  const w = L(lang);
  const uid = `c2-${++seq}`;
  let type = spec.type;
  let sorted = null; // null | "desc" | "asc"
  const visible = Object.fromEntries(
    (spec.series || []).map((_, j) => [j, true]),
  );
  const base = {
    ...spec,
    labels: [...(spec.labels || [])],
    series: (spec.series || []).map((sr) => ({
      ...sr,
      values: [...sr.values],
    })),
  };
  const view = () => {
    if (
      !sorted ||
      !base.labels.length ||
      ["line", "area", "stacked_area"].includes(type)
    )
      return base;
    const order = base.labels.map((_, i) => i);
    const v = base.series[0].values;
    order.sort(
      (a, b) =>
        (num(v[b]) ? v[b] : -Infinity) * (sorted === "desc" ? 1 : -1) -
        (num(v[a]) ? v[a] : -Infinity) * (sorted === "desc" ? 1 : -1),
    );
    return {
      ...base,
      labels: order.map((i) => base.labels[i]),
      series: base.series.map((sr) => ({
        ...sr,
        values: order.map((i) => sr.values[i]),
      })),
    };
  };
  const tip = h("div", {
    class: "chart-tip c2-tip",
    role: "status",
    "aria-live": "polite",
  });
  const plot = h("div", { class: "chart-plot c2-plot", tabindex: "0", role: "group", "aria-roledescription": w.role,
    "aria-label": `${spec.title} — ${w[type] || type}` }, tip); // prettier-ignore
  let svg = null;
  let drawn = null;
  let active = -1;
  let drawnW = 0;
  let cur = view();
  const drill = (i) => {
    const label = drawn?.hits.find((hh) => hh.i === i)?.label ?? cur.labels[i];
    if (label === undefined || type === "kpi" || type === "box") return;
    if (onDrill) return onDrill(label, cur);
    composerInsert(
      `${w.drill} « ${label} »${spec.source_label ? ` (${spec.source_label})` : ""} : `,
      { replace: true },
    );
  };
  const show = (k) => {
    if (!drawn || k < 0 || k >= drawn.hits.length) return;
    active = k;
    const hit = drawn.hits[k];
    for (const m of svg.querySelectorAll(".c2-mark"))
      m.classList.toggle(
        "is-active",
        Number(m.dataset.i) === hit.i && (!hit.path || m === hit.path),
      );
    plot.classList.add("has-active");
    tip.replaceChildren(
      h("span", { class: "chart-tip-head", text: String(hit.label) }),
      ...hit.lines.filter((ln) => ln[1] !== "—" || hit.lines.length === 1).map(([name, text, kk]) =>
        h("span", { class: "chart-tip-row" }, h("span", { class: `chart-swatch series-bg-${kk || 1}`, "aria-hidden": "true" }),
          name ? `${name}${lang === "en" ? ":" : " :"} ${text}` : text)), // prettier-ignore
    );
    tip.classList.add("is-shown");
    const pw = plot.clientWidth;
    const ph = plot.clientHeight;
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    const scale = pw / drawnW || 1;
    let left = hit.tipX * pw - tw / 2;
    left = Math.max(4, Math.min(pw - tw - 4, left));
    const topPx = Math.max(2, Math.min(ph - th - 2, hit.tipY * scale - th));
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(topPx)}px`;
  };
  const hide = () => {
    active = -1;
    plot.classList.remove("has-active");
    tip.classList.remove("is-shown");
    if (svg)
      for (const m of svg.querySelectorAll(".c2-mark.is-active"))
        m.classList.remove("is-active");
  };
  const draw = (width) => {
    const W = Math.round(Math.max(MIN_W, Math.min(MAX_W, width)));
    drawnW = W;
    cur = view();
    const hasValue =
      type === "scatter" || type === "bubble"
        ? (cur.points || []).length
        : type === "box"
          ? !!cur.box
          : type === "histogram"
            ? !!cur.bins
            : cur.series.some((sr, j) => visible[j] && sr.values.some(num));
    if (!hasValue) {
      const empty = s(
        "svg",
        { viewBox: `0 0 ${W} 60`, class: "chart-svg c2-svg", role: "img" },
        s(
          "text",
          { class: "chart-tick", x: W / 2, y: 34, "text-anchor": "middle" },
          w.empty,
        ),
      );
      if (svg) svg.replaceWith(empty);
      else plot.prepend(empty);
      svg = empty;
      drawn = { hits: [] };
      return;
    }
    drawn = DRAW[type](cur, { W, lang, visible, type });
    const next = s(
      "svg",
      {
        viewBox: `0 0 ${W} ${drawn.H}`,
        class: `chart-svg c2-svg c2-kind-${type}`,
        role: "img",
        "aria-labelledby": `${uid}-t`,
        focusable: "false",
      },
      drawn.g,
    );
    drawn.hits.forEach((hit, k) => {
      const target =
        hit.path ||
        s("rect", {
          class: "c2-hit",
          "data-hit": "1",
          x: hit.x,
          y: hit.y,
          width: Math.max(0, hit.w),
          height: Math.max(0, hit.h),
        });
      if (!hit.path) next.append(target);
      target.addEventListener(
        "pointerenter",
        (e) => e.pointerType !== "touch" && show(k),
      );
      target.addEventListener("click", () => {
        show(k);
        drill(hit.i);
      });
    });
    next.addEventListener(
      "pointerleave",
      (e) => e.pointerType !== "touch" && hide(),
    );
    if (svg) svg.replaceWith(next);
    else plot.prepend(next);
    svg = next;
    if (active >= 0) show(Math.min(active, drawn.hits.length - 1));
  };
  const vw = typeof window !== "undefined" ? window.innerWidth || 640 : 640;
  draw(Math.min(720, vw - (vw < 560 ? 46 : 120)));
  if (typeof ResizeObserver !== "undefined") {
    let pending = 0;
    new ResizeObserver((entries) => {
      const cw = entries[entries.length - 1].contentRect.width;
      if (!cw || Math.abs(Math.round(cw) - drawnW) < 2) return;
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(() => draw(cw));
    }).observe(plot);
  }
  plot.addEventListener("keydown", (e) => {
    const n = drawn?.hits.length || 0;
    if (!n) return;
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[
      e.key
    ];
    if (step)
      show(
        active < 0
          ? step > 0
            ? 0
            : n - 1
          : Math.max(0, Math.min(n - 1, active + step)),
      );
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(n - 1);
    else if (e.key === "Enter" && active >= 0) drill(drawn.hits[active].i);
    else if (e.key === "Escape") hide();
    else return;
    e.preventDefault();
  });
  plot.addEventListener("blur", hide);

  // ---- legend: one toggle per series (or per slice)
  const legend = h("div", {
    class: "c2-legend",
    role: "group",
    "aria-label": w.legend,
  });
  const drawLegend = () => {
    const pie = type === "pie" || type === "donut" || type === "funnel";
    const multi =
      (spec.series || []).length > 1 &&
      ![
        "scatter",
        "bubble",
        "histogram",
        "box",
        "kpi",
        "heatmap",
        "waterfall",
      ].includes(type);
    if (!pie && !multi) return legend.replaceChildren();
    const items = pie ? cur.labels.map((l, i) => [l, Math.min(i, 7) + 1, `p${base.labels.indexOf(l)}`])
      : (spec.series || []).map((sr, j) => [sr.name, cls(j), j]); // prettier-ignore
    legend.replaceChildren(
      ...items.map(([name, k, key]) => {
        const on = visible[key] !== false;
        return h("button", { type: "button", class: `c2-leg${on ? "" : " is-off"}`, "aria-pressed": on ? "true" : "false",
        onclick: () => {
          const shown = Object.entries(visible).filter(([kk, v]) => v !== false && (pie ? String(kk).startsWith("p") || true : !String(kk).startsWith("p"))).length;
          if (on && !pie && shown <= 1) return; // the last series stays
          visible[key] = !on;
          draw(drawnW);
          drawLegend();
        } }, h("span", { class: `chart-swatch series-bg-${k}${type === "line" ? " is-line" : ""}`, "aria-hidden": "true" }),
        h("span", { text: String(name) })); // prettier-ignore
      }),
    );
  };
  drawLegend();

  // ---- toolbar: type, sort, export, add to document
  const alts = (spec.alts || [type]).filter((t) => DRAW[t]);
  const typeBar = alts.length > 1 && h("div", { class: "c2-types", role: "radiogroup", "aria-label": w.type },
    alts.map((t) => h("button", { type: "button", class: `c2-type${t === type ? " is-on" : ""}`, role: "radio",
      "aria-checked": t === type ? "true" : "false", "data-type": t, title: w[t] || t,
      onclick: (e) => {
        type = t;
        for (const b of typeBar.querySelectorAll(".c2-type")) {
          const onB = b.dataset.type === t;
          b.classList.toggle("is-on", onB);
          b.setAttribute("aria-checked", onB ? "true" : "false");
        }
        meta.textContent = metaText();
        draw(drawnW);
        drawLegend();
        e.currentTarget.focus();
      } }, typeGlyph(t), h("span", { class: "c2-type-name", text: w[t] || t })))); // prettier-ignore
  const canSort = () =>
    base.labels.length > 2 &&
    ![
      "line",
      "area",
      "stacked_area",
      "scatter",
      "bubble",
      "box",
      "histogram",
      "kpi",
      "heatmap",
      "waterfall",
      "funnel",
    ].includes(type) &&
    base.x?.kind !== "time";
  const sortBtn = h("button", { type: "button", class: "btn btn-outline btn-small c2-sort", "aria-pressed": "false",
    onclick: () => {
      sorted = sorted === null ? "desc" : sorted === "desc" ? "asc" : null;
      sortBtn.setAttribute("aria-pressed", sorted ? "true" : "false");
      sortBtn.querySelector(".btn-label").textContent = sorted ? `${w.sorted} ${sorted === "desc" ? "↓" : "↑"}` : w.sort;
      draw(drawnW);
      drawLegend();
    } }, icon("swap"), h("span", { class: "btn-label", text: w.sort })); // prettier-ignore
  const legendNames = () =>
    (spec.series || []).length > 1
      ? (spec.series || []).map((sr) => sr.name)
      : [];
  const footLine = () =>
    [
      w[type],
      spec.unit,
      w[`src_${spec.source || "model"}`],
      spec.source_label,
      "Bird",
    ]
      .filter(Boolean)
      .join(" · ");
  const exportImage = (kind) => {
    hide();
    const out = standalone(svg, {
      title: spec.title,
      foot: { line: footLine(), legendNames: legendNames() },
      legend: legendNames().map((_, j) => cls(j)),
    });
    if (kind === "svg")
      return download(
        `${sanitize(spec.title)}.svg`,
        "image/svg+xml",
        new Blob([out.text], { type: "image/svg+xml" }),
      );
    const url = URL.createObjectURL(
      new Blob([out.text], { type: "image/svg+xml" }),
    );
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = out.w;
      canvas.height = out.h;
      canvas.getContext("2d").drawImage(img, 0, 0, out.w, out.h);
      URL.revokeObjectURL(url);
      canvas.toBlob(
        (blob) =>
          blob && download(`${sanitize(spec.title)}.png`, "image/png", blob),
        "image/png",
      );
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  };
  const exportMenu = h("details", { class: "c2-menu" },
    h("summary", { class: "btn btn-outline btn-small" }, icon("download"), h("span", { class: "btn-label", text: w.export })),
    h("div", { class: "c2-menu-list" },
      button("btn-ghost btn-small", "image", w.png, () => (exportMenu.open = false, exportImage("png")), { "data-act": "c2-png" }),
      button("btn-ghost btn-small", "image", w.svg, () => (exportMenu.open = false, exportImage("svg")), { "data-act": "c2-svg" }),
      button("btn-ghost btn-small", "copy", w.csv, () => (exportMenu.open = false, copyText(chartCsv(cur, lang), w.csvDone)), { "data-act": "c2-csv" }))); // prettier-ignore
  const toDoc = button(
    "btn-outline btn-small",
    "make_document",
    w.toDoc,
    () => {
      // the Canvas listens for this event and calls preventDefault() when it took the chart
      const ev = new CustomEvent("bird:add-to-document", { cancelable: true, detail: { kind: "chart", spec: cur, type,
      markdown: chartMarkdown2(cur, lang), svg: svg ? standalone(svg, { title: spec.title, foot: { line: footLine(), legendNames: legendNames() }, legend: legendNames().map((_, j) => cls(j)) }).text : "" } }); // prettier-ignore
      const taken = !window.dispatchEvent(ev);
      if (!taken)
        copyText(
          `**${spec.title}**\n\n${chartMarkdown2(cur, lang)}`,
          w.toDocDone,
        );
    },
    { "data-act": "c2-to-doc" },
  );
  const meta = h("p", { class: "card-meta" });
  const metaText = () =>
    [w[type], spec.unit, spec.source_label].filter(Boolean).join(" · ");
  meta.textContent = metaText();
  const srcTag = h("span", {
    class: `tag ${spec.source === "model" ? "tag-estimated" : "c2-tag-ok"}`,
    text: w[`src_${spec.source || "model"}`] || "",
  });
  const stat = spec.stat && num(spec.stat.r)
    ? `${w.r} r = ${fmtValue(spec.stat.r, "", lang)} (${spec.stat.strength || ""}) · ${fmtValue(spec.stat.n, "", lang)} ${w.n}`
    : spec.change && num(spec.change.pct) ? `${w.change} ${spec.change.pct > 0 ? "+" : ""}${fmtValue(spec.change.pct, "%", lang)}` : ""; // prettier-ignore
  const table = !compact && h("details", { class: "chart-data" }, h("summary", null, icon("chevron", "chev"), w.data),
    h("div", { class: "chart-table-wrap" }, dataTable(spec, lang))); // prettier-ignore
  const sortWrap = canSort() && sortBtn;
  return h("figure", { class: `card chart-card c2-card${compact ? " is-compact" : ""}`, "data-chart": spec.id || uid, "data-type": spec.type },
    h("figcaption", { class: "chart-head c2-head" },
      h("div", { class: "c2-title-row" }, h("p", { class: "card-name", id: `${uid}-t`, text: spec.title }), srcTag),
      meta),
    (typeBar || sortWrap) && h("div", { class: "c2-toolbar" }, typeBar, sortWrap),
    plot,
    legend,
    stat && h("p", { class: "c2-stat" }, icon("info"), stat),
    table,
    h("div", { class: "chart-actions c2-actions" }, exportMenu, toDoc)); // prettier-ignore
}

function dataTable(spec, lang) {
  if (spec.points) {
    const ax = spec.axes || ["x", "y"];
    return h("table", null, h("thead", null, h("tr", null, h("th", { text: "" }), h("th", { scope: "col", text: ax[0] }), h("th", { scope: "col", text: ax[1] }))),
      h("tbody", null, spec.points.slice(0, 100).map((p) => h("tr", null, h("th", { scope: "row", text: String(p[0]) }),
        h("td", { class: "num", text: fmtValue(p[1], (spec.units || [])[0], lang) }), h("td", { class: "num", text: fmtValue(p[2], (spec.units || [])[1], lang) }))))); // prettier-ignore
  }
  if (spec.type === "box" && spec.box) {
    const w = L(lang);
    const rows = [
      ["min", spec.box.min],
      [w.q1, spec.box.q1],
      [w.median, spec.box.median],
      [w.mean, spec.box.mean],
      [w.q3, spec.box.q3],
      ["max", spec.box.max],
    ];
    return h(
      "table",
      null,
      h(
        "tbody",
        null,
        rows.map(([k, v]) =>
          h(
            "tr",
            null,
            h("th", { scope: "row", text: k }),
            h("td", { class: "num", text: fmtValue(v, spec.unit, lang) }),
          ),
        ),
      ),
    );
  }
  return h("table", null,
    h("thead", null, h("tr", null, h("th", { scope: "col", text: spec.x?.name || "" }), spec.series.map((sr) => h("th", { scope: "col", text: sr.name })))),
    h("tbody", null, spec.labels.map((l, i) => h("tr", null, h("th", { scope: "row", text: String(l) }),
      spec.series.map((sr) => h("td", { class: "num", text: fmtValue(sr.values[i], sr.unit || spec.unit, lang) })))))); // prettier-ignore
}

/** A tiny glyph per chart type (SVG built here, never markup from data). */
function typeGlyph(t) {
  const paths = {
    bar: "M4 16V9M8 16V5M12 16V11M16 16V7", hbar: "M4 5h9M4 9h12M4 13h6M4 17h3", stacked: "M5 16V8M5 12h0M10 16V5M15 16V10",
    line: "M3 14l4-5 4 3 6-7", area: "M3 15l4-5 4 3 6-7V16H3z", stacked_area: "M3 15l4-4 4 2 6-6V16H3zM3 12l4-3 4 1 6-4",
    pie: "M10 3a7 7 0 1 0 7 7h-7z", donut: "M10 3a7 7 0 1 1-6.9 8.2M10 6.5a3.5 3.5 0 1 0 3.5 3.5", scatter: "M5 14h.1M8 9h.1M11 12h.1M14 6h.1M15 10h.1",
    bubble: "M6 13a2 2 0 1 0 .1 0M12 7a3 3 0 1 0 .1 0", histogram: "M3 16V12h3V8h3V5h3V9h3v7z", box: "M3 10h3M14 10h3M6 7h8v6H6zM10 7v6",
    heatmap: "M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z", waterfall: "M4 16V11M8 11V7M12 7V10M16 16V6", funnel: "M3 4h14l-5 6v6l-4-2v-4z",
    combo: "M4 16V10M9 16V7M14 16V11M3 9l6-4 8 3", kpi: "M4 14h4M4 6h8M4 10h12",
  }; // prettier-ignore
  return s(
    "svg",
    {
      class: "icon c2-glyph",
      viewBox: "0 0 20 20",
      "aria-hidden": "true",
      focusable: "false",
    },
    s("path", { d: paths[t] || paths.bar }),
  );
}

export const CHART_TYPES = Object.keys(DRAW);
