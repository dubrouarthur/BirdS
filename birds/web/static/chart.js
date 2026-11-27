// Charts drawn in the browser as SVG, from the spec the server normalised (birds/harness/tools/chart.py).
// No library. Colours are CSS classes (series-1..6) so the theme switches live and the CSP stays strict;
// the PNG export copies the computed colours into a standalone SVG before drawing it on a canvas.
import { button, copyText, download, h, icon, t, toast } from "./core.js";
// ---- data analysis extension: richer charts (spec v2) are drawn by charts2.js
import { chartMarkdown2, renderChart2 } from "./charts2.js";

const NS = "http://www.w3.org/2000/svg";
// viewBox width = the plot's real width in CSS px, so 12px text is drawn at 12px on every screen (the chart is
// drawn again when its width changes). Set by renderChart before each draw.
let W = 640;
const MIN_W = 260;
const MAX_W = 900;
const MAX_SERIES = 6;

function s(tag, attrs, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {}))
    if (v !== null && v !== undefined && v !== false)
      el.setAttribute(k, String(v));
  for (const c of children.flat())
    if (c) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}

const cut = (text, n) =>
  String(text).length > n ? `${String(text).slice(0, n - 1)}…` : String(text);

export function formatter(lang, unit) {
  const nf = new Intl.NumberFormat(lang === "en" ? "en-GB" : "fr-FR", {
    maximumFractionDigits: 2,
  });
  const u = String(unit || "");
  const f = (v) => {
    if (v === null || v === undefined || Number.isNaN(v))
      return t("chart.missing");
    const n = nf.format(v);
    if (!u) return n;
    if (u === "%") return lang === "en" ? `${n}%` : `${n} %`;
    return `${n} ${u}`;
  };
  f.lang = lang;
  f.unit = u;
  return f;
}

/** Axis ticks: compact from 10 000 up (« 1,5 M € », "1.5M €"), so a long number never runs off the card. */
export function tickFormatter(lang, unit, ticks) {
  const big = Math.max(...ticks.map((v) => Math.abs(v))) >= 10000;
  if (!big) return formatter(lang, unit);
  const nf = new Intl.NumberFormat(lang === "en" ? "en-GB" : "fr-FR", {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const u = String(unit || "");
  return (v) => {
    const n = nf.format(v);
    if (!u) return n;
    if (u === "%") return lang === "en" ? `${n}%` : `${n}\u202f%`;
    return `${n}\u00a0${u}`;
  };
}

let measureCtx = null;
/** Width of a 12px chart label in CSS px (canvas measure; an estimate where there is no canvas). */
export function textWidth(text) {
  const str = String(text);
  try {
    if (!measureCtx) {
      measureCtx = document.createElement("canvas").getContext("2d");
      const family = getComputedStyle(document.body).fontFamily || "sans-serif";
      measureCtx.font = `12px ${family}`;
    }
    const w = measureCtx?.measureText(str).width;
    if (w) return w;
  } catch {
    /* no canvas: estimate below */
  }
  return str.length * 6.6;
}

/** ``text`` cut with "…" to fit ``maxW`` px. */
function fitText(text, maxW) {
  let str = String(text);
  if (textWidth(str) <= maxW) return str;
  while (str.length > 1 && textWidth(`${str}…`) > maxW) str = str.slice(0, -1);
  return `${str.trimEnd()}…`;
}

/** A label on at most 2 lines of ``maxW`` px (words kept whole when they fit). */
function wrapLabel(label, maxW) {
  const lines = [""];
  for (const word of String(label).split(/\s+/).filter(Boolean)) {
    const last = lines[lines.length - 1];
    const cand = last ? `${last} ${word}` : word;
    if (!last || textWidth(cand) <= maxW) lines[lines.length - 1] = cand;
    else if (lines.length < 2) lines.push(word);
    else lines[1] = cand;
  }
  return lines.map((l) => fitText(l, maxW));
}

/** Show every k-th tick label so that two labels never touch (at least 12px apart). */
function tickStep(ticks, tf, spacing) {
  const widest = Math.max(...ticks.map((tk) => textWidth(tf(tk))));
  return Math.max(1, Math.ceil((widest + 12) / Math.max(1, spacing)));
}

/** Left margin that fits the longest y tick label (8px gap), within [36, 40% of the width]. */
function leftFor(ticks, tf) {
  const widest = Math.max(...ticks.map((tk) => textWidth(tf(tk))));
  return Math.round(Math.max(36, Math.min(W * 0.4, widest + 14)));
}

/** 4 to 6 "nice" ticks (steps of 1, 2 or 5 x 10^k) covering [lo, hi]. */
export function niceTicks(lo, hi) {
  if (lo === hi) hi = lo + 1;
  const raw = (hi - lo) / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 5, 10].map((m) => m * mag).find((x) => (hi - lo) / x <= 6) ||
    10 * mag;
  const start = Math.floor(lo / step) * step;
  const out = [];
  for (let v = start; v <= hi + step * 0.001; v += step)
    out.push(Math.round(v / step) * step);
  if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
  return out;
}

function roundedBar(x, y, w, hgt, up) {
  // a rectangle whose data end (top when up, bottom when down) has 4px rounded corners
  const r = Math.max(0, Math.min(4, w / 2, Math.abs(hgt)));
  if (hgt <= 0) return "";
  if (up)
    return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
  return `M${x},${y}V${y + hgt - r}Q${x},${y + hgt} ${x + r},${y + hgt}H${x + w - r}Q${x + w},${y + hgt} ${x + w},${y + hgt - r}V${y}Z`;
}

function roundedHBar(x, y, w, hgt, right) {
  const r = Math.max(0, Math.min(4, hgt / 2, Math.abs(w)));
  if (w <= 0) return "";
  if (right)
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt - r}Q${x + w},${y + hgt} ${x + w - r},${y + hgt}H${x}Z`;
  return `M${x + w},${y}H${x + r}Q${x},${y} ${x},${y + r}V${y + hgt - r}Q${x},${y + hgt} ${x + r},${y + hgt}H${x + w}Z`;
}

function valuesOf(spec) {
  return spec.rows
    .flatMap((r) => r.slice(1))
    .filter((v) => typeof v === "number");
}

// ------------------------------------------------------------------ the three forms

function drawBars(spec, fmt) {
  const labels = spec.rows.map((r) => String(r[0]));
  const nS = spec.columns.length - 1;
  const horizontal =
    labels.length > 8 || Math.max(...labels.map((l) => l.length)) > 12;
  const vals = valuesOf(spec);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const ticks = niceTicks(lo, hi);
  const t0 = ticks[0];
  const t1 = ticks[ticks.length - 1];
  const marks = [];
  const hits = [];
  const g = s("g");
  const valueLabels = labels.length * nS <= 8;
  const tf = tickFormatter(fmt.lang, fmt.unit, ticks);
  if (!horizontal) {
    const H = 320;
    const m = { l: leftFor(ticks, tf), r: 12, t: 20, b: 46 };
    const pw = W - m.l - m.r;
    const ph = H - m.t - m.b;
    const y = (v) => m.t + ph - ((v - t0) / (t1 - t0)) * ph;
    for (const tk of ticks) {
      g.append(
        s("line", {
          class: "chart-grid",
          x1: m.l,
          x2: W - m.r,
          y1: y(tk),
          y2: y(tk),
        }),
      );
      g.append(
        s(
          "text",
          {
            class: "chart-tick",
            x: m.l - 8,
            y: y(tk) + 4,
            "text-anchor": "end",
          },
          tf(tk),
        ),
      );
    }
    const band = pw / labels.length;
    const inner = band * 0.72;
    const bw = Math.min(56, inner / nS);
    const rotate = labels.some((l) => cut(l, 18).length * 6.4 > band - 4);
    labels.forEach((label, i) => {
      const x0 = m.l + band * i + (band - bw * nS) / 2;
      const group = [];
      for (let j = 0; j < nS; j++) {
        const v = spec.rows[i][j + 1];
        if (typeof v !== "number") continue;
        const top = y(Math.max(0, v));
        const hgt = Math.abs(y(v) - y(0));
        const path = s("path", {
          class: `chart-mark series-${j + 1}`,
          d: roundedBar(x0 + j * bw + 1, top, Math.max(1, bw - 2), hgt, v >= 0),
        });
        group.push(path);
        g.append(path);
        if (valueLabels)
          g.append(
            s(
              "text",
              {
                class: "chart-value",
                x: x0 + j * bw + bw / 2,
                y: v >= 0 ? top - 6 : top + hgt + 14,
                "text-anchor": "middle",
              },
              fmt(v),
            ),
          );
      }
      marks.push(group);
      const cx = m.l + band * i + band / 2;
      g.append(
        rotate
          ? s(
              "text",
              {
                class: "chart-label",
                x: cx,
                y: H - m.b + 14,
                "text-anchor": "end",
                transform: `rotate(-35 ${cx} ${H - m.b + 14})`,
              },
              cut(label, 18),
            )
          : s(
              "text",
              {
                class: "chart-label",
                x: cx,
                y: H - m.b + 18,
                "text-anchor": "middle",
              },
              cut(label, 18),
            ),
      );
      hits.push({
        x: m.l + band * i,
        y: m.t,
        w: band,
        h: ph,
        tipX: cx / W,
        tipY: 0.04,
      });
    });
    g.append(
      s("line", {
        class: "chart-axis",
        x1: m.l,
        x2: W - m.r,
        y1: y(0),
        y2: y(0),
      }),
    );
    return { g, H, marks, hits };
  }
  // horizontal bars: one row per label, labels on the left
  // at least 22px per row so that 12px labels never shrink: a long list makes a taller card, never a smaller font
  const rowH =
    Math.max(22, Math.min(28, 240 / labels.length)) * Math.max(1, nS * 0.8);
  const tall = labels.length > 14; // ticks are repeated above the rows, so the scale stays in view
  // labels on up to 2 lines in at most ~36% of the width (170px on a wide card); the margin fits the longest line
  const wrapped = labels.map((l) => wrapLabel(l, W < 600 ? W * 0.36 - 14 : 170));
  const twoLines = wrapped.some((w) => w.length > 1);
  const rowHt = twoLines ? Math.max(rowH, 34) : rowH;
  const widestLabel = Math.max(...wrapped.flat().map((l) => textWidth(l)));
  const widestValue = valueLabels
    ? Math.max(...vals.map((v) => textWidth(fmt(v))))
    : 0;
  const m = {
    l: Math.round(widestLabel + 14),
    r: Math.round(valueLabels ? widestValue + 12 : 16),
    t: tall ? 28 : 12,
    b: 32,
  };
  const H = Math.round(m.t + m.b + rowHt * labels.length + 8);
  const pw = W - m.l - m.r;
  const x = (v) => m.l + ((v - t0) / (t1 - t0)) * pw;
  const every = tickStep(ticks, tf, pw / Math.max(1, ticks.length - 1));
  for (const [k, tk] of ticks.entries()) {
    g.append(
      s("line", {
        class: "chart-grid",
        x1: x(tk),
        x2: x(tk),
        y1: m.t,
        y2: H - m.b,
      }),
    );
    if (k % every) continue;
    g.append(
      s(
        "text",
        {
          class: "chart-tick",
          x: x(tk),
          y: H - m.b + 16,
          "text-anchor": "middle",
        },
        tf(tk),
      ),
    );
    if (tall)
      g.append(
        s(
          "text",
          { class: "chart-tick", x: x(tk), y: m.t - 10, "text-anchor": "middle" },
          tf(tk),
        ),
      );
  }
  const bh = (rowH * 0.76) / nS;
  labels.forEach((label, i) => {
    const y0 = m.t + rowHt * i + (rowHt - bh * nS) / 2;
    const group = [];
    for (let j = 0; j < nS; j++) {
      const v = spec.rows[i][j + 1];
      if (typeof v !== "number") continue;
      const left = x(Math.min(0, v));
      const w = Math.abs(x(v) - x(0));
      const path = s("path", {
        class: `chart-mark series-${j + 1}`,
        d: roundedHBar(left, y0 + j * bh + 1, w, Math.max(1, bh - 2), v >= 0),
      });
      group.push(path);
      g.append(path);
      if (valueLabels)
        g.append(
          s(
            "text",
            {
              class: "chart-value",
              x: x(v) + (v >= 0 ? 6 : -6),
              y: y0 + j * bh + bh / 2 + 4,
              "text-anchor": v >= 0 ? "start" : "end",
            },
            fmt(v),
          ),
        );
    }
    marks.push(group);
    const lines = wrapped[i];
    const cy = m.t + rowHt * i + rowHt / 2;
    g.append(
      s(
        "text",
        {
          class: "chart-label",
          x: m.l - 8,
          y: lines.length > 1 ? cy - 3 : cy + 4,
          "text-anchor": "end",
        },
        lines.length > 1
          ? lines.map((line, k) =>
              s("tspan", { x: m.l - 8, dy: k ? 14 : 0 }, line),
            )
          : lines[0],
      ),
    );
    hits.push({
      x: 0,
      y: m.t + rowHt * i,
      w: W,
      h: rowHt,
      tipX: 0.5,
      tipY: (m.t + rowHt * i) / H,
    });
  });
  g.append(
    s("line", {
      class: "chart-axis",
      x1: x(0),
      x2: x(0),
      y1: m.t,
      y2: H - m.b,
    }),
  );
  return { g, H, marks, hits };
}

function drawLine(spec, fmt) {
  const H = 320;
  const labels = spec.rows.map((r) => String(r[0]));
  const nS = spec.columns.length - 1;
  const direct = nS >= 2 && nS <= 4;
  const vals = valuesOf(spec);
  const ticks = niceTicks(
    Math.min(...vals) >= 0 &&
      Math.min(...vals) < Math.max(...vals) - Math.min(...vals)
      ? 0
      : Math.min(...vals),
    Math.max(...vals),
  );
  const tf = tickFormatter(fmt.lang, fmt.unit, ticks);
  const m = { l: leftFor(ticks, tf), r: direct ? 92 : 16, t: 20, b: 46 };
  const pw = W - m.l - m.r;
  const ph = H - m.t - m.b;
  const t0 = ticks[0];
  const t1 = ticks[ticks.length - 1];
  const y = (v) => m.t + ph - ((v - t0) / (t1 - t0)) * ph;
  const band = pw / labels.length;
  const x = (i) => m.l + band * i + band / 2;
  const g = s("g");
  for (const tk of ticks) {
    g.append(
      s("line", {
        class: "chart-grid",
        x1: m.l,
        x2: W - m.r,
        y1: y(tk),
        y2: y(tk),
      }),
    );
    g.append(
      s(
        "text",
        { class: "chart-tick", x: m.l - 8, y: y(tk) + 4, "text-anchor": "end" },
        tf(tk),
      ),
    );
  }
  const step = Math.ceil(labels.length / Math.max(1, Math.floor(pw / 64)));
  labels.forEach((label, i) => {
    if (i % step === 0)
      g.append(
        s(
          "text",
          {
            class: "chart-label",
            x: x(i),
            y: H - m.b + 18,
            "text-anchor": "middle",
          },
          cut(label, 12),
        ),
      );
  });
  const marks = labels.map(() => []);
  const ends = [];
  const markers = labels.length <= 24;
  for (let j = 0; j < nS; j++) {
    let d = "";
    let pen = false;
    spec.rows.forEach((r, i) => {
      const v = r[j + 1];
      if (typeof v !== "number") {
        pen = false; // a gap: the line breaks, nothing is interpolated
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    g.append(s("path", { class: `chart-line stroke-${j + 1}`, d }));
    spec.rows.forEach((r, i) => {
      const v = r[j + 1];
      if (typeof v !== "number") return;
      const dot = s("circle", {
        class: `chart-mark chart-point series-${j + 1}${markers ? "" : " chart-point-hidden"}`,
        cx: x(i),
        cy: y(v),
        r: 4,
      });
      marks[i].push(dot);
      g.append(dot);
    });
    if (direct) {
      const lastIdx = spec.rows
        .map((r) => r[j + 1])
        .findLastIndex((v) => typeof v === "number");
      if (lastIdx >= 0)
        ends.push({
          x: x(lastIdx) + 8,
          y: y(spec.rows[lastIdx][j + 1]) + 4,
          text: cut(spec.columns[j + 1], 14),
        });
    }
  }
  // end labels: pushed apart to 14px at least (sorted by height); dropped if they cannot fit (the legend stays)
  ends.sort((p, q) => p.y - q.y);
  for (let k = 1; k < ends.length; k++)
    ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 14);
  const over = ends.length ? ends[ends.length - 1].y - (H - m.b + 4) : 0;
  if (over > 0) for (const e of ends) e.y -= over;
  if (!ends.length || ends[0].y >= m.t + 4)
    for (const e of ends)
      g.append(s("text", { class: "chart-direct", x: e.x, y: e.y }, e.text));
  const hits = labels.map((_, i) => ({
    x: m.l + band * i,
    y: m.t,
    w: band,
    h: ph,
    tipX: x(i) / W,
    tipY: 0.08,
  }));
  return { g, H, marks, hits };
}

function drawPie(spec, fmt, lang) {
  // narrow: the outer labels are only the percentage (the names are in the legend), so the ring can stay big
  const narrow = W < 480;
  const R = narrow ? Math.max(56, Math.min(90, W / 2 - 48)) : 112;
  const H = Math.round(2 * R + (narrow ? 56 : 76));
  const cx = W / 2;
  const cy = H / 2;
  const r0 = R * 0.55;
  const total = spec.rows.reduce((a, r) => a + (r[1] || 0), 0);
  const g = s("g");
  const marks = [];
  const hits = [];
  let a = -Math.PI / 2;
  const nf = new Intl.NumberFormat(lang === "en" ? "en-GB" : "fr-FR", {
    maximumFractionDigits: 0,
  });
  spec.rows.forEach((row, i) => {
    const v = row[1] || 0;
    const da = (v / total) * Math.PI * 2;
    const a1 = a + da;
    const large = da > Math.PI ? 1 : 0;
    const p = (rad, ang) =>
      `${(cx + rad * Math.cos(ang)).toFixed(2)},${(cy + rad * Math.sin(ang)).toFixed(2)}`;
    const d =
      da >= Math.PI * 2 - 1e-6
        ? `M${cx},${cy - R}A${R},${R} 0 1 1 ${cx - 0.01},${cy - R}L${cx - 0.01},${cy - r0}A${r0},${r0} 0 1 0 ${cx},${cy - r0}Z`
        : `M${p(R, a)}A${R},${R} 0 ${large} 1 ${p(R, a1)}L${p(r0, a1)}A${r0},${r0} 0 ${large} 0 ${p(r0, a)}Z`;
    const slice = s("path", {
      // 6 hues, then two neutral greys for slices 7-8 (the last one is "Autres"): never a cycled hue
      class: `chart-mark chart-slice series-${Math.min(i, 7) + 1}`,
      d,
    });
    g.append(slice);
    marks.push([slice]);
    const mid = a + da / 2;
    if (v / total >= 0.05) {
      const lx = cx + (R + 16) * Math.cos(mid);
      const ly = cy + (R + 16) * Math.sin(mid);
      g.append(
        s(
          "text",
          {
            class: "chart-label",
            x: lx,
            y: ly + 4,
            "text-anchor": Math.cos(mid) >= 0 ? "start" : "end",
          },
          `${narrow ? "" : `${cut(row[0], 16)} `}${nf.format((v / total) * 100)}${lang === "en" ? "%" : " %"}`,
        ),
      );
    }
    hits.push({
      path: slice,
      tipX: (cx + R * 0.8 * Math.cos(mid)) / W,
      tipY: (cy + R * 0.8 * Math.sin(mid)) / H,
    });
    a = a1;
  });
  return { g, H, marks, hits, total };
}

// ------------------------------------------------------------------ exports

function sanitize(name) {
  return (
    String(name || "graphique")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^A-Za-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "graphique"
  );
}

/** RFC 4180 CSV; ';' and decimal commas in French. Text cells starting with = + - @ get a leading quote. */
export function toCsv(spec, lang) {
  const sep = lang === "en" ? "," : ";";
  const text = (v) => {
    let x = String(v ?? "");
    if (/^[=+\-@\t\r]/.test(x)) x = `'${x}`;
    return /["\n\r;,]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x;
  };
  const num = (v) =>
    typeof v === "number"
      ? lang === "en"
        ? String(v)
        : String(v).replace(".", ",")
      : "";
  const lines = [
    spec.columns.map(text).join(sep),
    ...spec.rows.map((r) => [text(r[0]), ...r.slice(1).map(num)].join(sep)),
  ];
  return lines.join("\n");
}

/** Computed light-theme styles of ``els``: the export is always light (it goes into documents), whatever the
 * screen shows. The theme attribute is switched and restored synchronously, so nothing is ever painted. */
function lightStyles(els, props, tokens) {
  const root = document.documentElement;
  const prev = root.dataset.theme;
  root.dataset.theme = "light";
  try {
    const rootCs = getComputedStyle(root);
    return {
      els: els.map((el) => {
        const cs = getComputedStyle(el);
        return Object.fromEntries(props.map((p) => [p, cs.getPropertyValue(p)]));
      }),
      tokens: Object.fromEntries(
        tokens.map((k) => [k, rootCs.getPropertyValue(k).trim()]),
      ),
    };
  } finally {
    if (prev === undefined) delete root.dataset.theme;
    else root.dataset.theme = prev;
  }
}

function standaloneSvg(svg, { title = "", foot = "", legend = [] } = {}) {
  // a standalone, light SVG: title on top, the plot, its legend, then the source line; colours and fonts are
  // copied from the computed styles, because the PNG is drawn without our stylesheet
  const props = ["fill", "stroke", "stroke-width", "opacity", "font-size", "font-weight"];
  const src = [svg, ...svg.querySelectorAll("*")];
  const swatches = legend.map(([, k]) => {
    const el = document.createElement("span");
    el.className = `series-bg-${k}`;
    document.body.append(el);
    return el;
  });
  const { els, tokens } = lightStyles(
    [...src, ...swatches],
    [...props, "background-color"],
    ["--surface", "--ink", "--muted", "--line"],
  );
  swatches.forEach((el) => el.remove());
  const plot = svg.cloneNode(true);
  const dst = [plot, ...plot.querySelectorAll("*")];
  dst.forEach((out, i) => {
    for (const p of props) if (els[i][p]) out.setAttribute(p, els[i][p]);
    out.removeAttribute("class");
  });
  for (const r of plot.querySelectorAll("rect")) r.remove(); // hit areas
  const vb = svg.viewBox.baseVal;
  const pad = 16;
  const ink = tokens["--ink"] || "#1a1a1a";
  const muted = tokens["--muted"] || "#666666";
  const titleLines = wrapLabel(title, (vb.width - 2 * pad) * 0.75).filter(Boolean); // 16px text
  const head = 14 + titleLines.length * 20;
  // legend: swatch + name, wrapped to the width
  const items = [];
  let lx = pad;
  let ly = 0;
  legend.forEach(([name, k], i) => {
    const label = fitText(name, vb.width - 2 * pad - 16);
    const w = 16 + textWidth(label) + 14;
    if (lx > pad && lx + w > vb.width - pad) {
      lx = pad;
      ly += 18;
    }
    items.push(
      s("rect", { x: lx, y: ly - 9, width: 10, height: 10, rx: 2, fill: els[src.length + i]["background-color"] }),
      s("text", { x: lx + 16, y: ly, "font-size": 12, fill: ink }, label),
    );
    lx += w;
  });
  const legendH = legend.length ? ly + 26 : 0;
  const footLines = [foot]
    .flat()
    .filter(Boolean)
    .flatMap((line) => wrapLabel(line, (vb.width - 2 * pad) * (12 / 11)).filter(Boolean)); // 11px text
  const H = head + vb.height + legendH + 10 + footLines.length * 16 + 10;
  const k = Math.max(2, 1280 / vb.width); // at least 1280 px wide, whatever the screen it was drawn for
  const out = s(
    "svg",
    {
      xmlns: NS,
      viewBox: `0 0 ${vb.width} ${H}`,
      width: Math.round(vb.width * k),
      height: Math.round(H * k),
      "font-family": "system-ui, sans-serif",
    },
    s("rect", { x: 0, y: 0, width: vb.width, height: H, fill: tokens["--surface"] || "#ffffff" }),
    titleLines.map((line, i) =>
      s("text", { x: pad, y: 24 + i * 20, "font-size": 16, "font-weight": 650, fill: ink }, line),
    ),
    s("g", { transform: `translate(0 ${head})` }, ...plot.childNodes),
    legend.length && s("g", { transform: `translate(0 ${head + vb.height + 18})` }, items),
    footLines.map((line, i) =>
      s(
        "text",
        { x: pad, y: head + vb.height + legendH + 22 + i * 16, "font-size": 11, fill: muted },
        line,
      ),
    ),
  );
  return {
    text: new XMLSerializer().serializeToString(out),
    w: Math.round(vb.width * k),
    h: Math.round(H * k),
  };
}

function exportPng(svg, title, meta) {
  const { text, w, h: hh } = standaloneSvg(svg, { title, ...meta });
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = hh;
    canvas.getContext("2d").drawImage(img, 0, 0, w, hh);
    URL.revokeObjectURL(url);
    canvas.toBlob(
      (blob) => blob && download(`${sanitize(title)}.png`, "image/png", blob),
      "image/png",
    );
  };
  img.onerror = () => {
    URL.revokeObjectURL(url);
    toast(t("chart.png.error"), "error");
  };
  img.src = url;
}

// ------------------------------------------------------------------ the card

/** One reshaping the server did ({code, n, label, items}), in the UI language. An older stored conversation may
 * hold the server's English sentence: it is shown as it is. */
function reshapedText(item) {
  if (!item || typeof item !== "object") return String(item ?? "");
  const items = (Array.isArray(item.items) ? item.items : []).join(", ");
  const key = `chart.reshaped.${item.code}`;
  const text = t(key, { n: item.n ?? "", label: item.label ?? "", items });
  return text === key ? String(item.code || "") : text;
}

let seq = 0;

/** A chart card: title, plot (hover and keyboard), legend, data table and actions. ``onXlsx(spec)`` exports. */
export function renderChart(spec, { lang = "fr", onXlsx } = {}) {
  if (spec && spec.v === 2) return renderChart2(spec, { lang }); // data analysis extension (charts2.js)
  if (
    !spec ||
    !Array.isArray(spec.rows) ||
    !Array.isArray(spec.columns) ||
    spec.columns.length < 2
  )
    return null;
  const uid = `chart-${++seq}`;
  const fmt = formatter(lang, spec.unit);
  const type = ["bar", "line", "pie"].includes(spec.type) ? spec.type : "bar";
  const series = spec.columns.slice(1, 1 + MAX_SERIES);
  const n = spec.rows.length;
  // what a screen reader hears: max and min of the series, or of each series when there are several
  const extremes = (j) => {
    const pts = spec.rows
      .map((r, i) => ({ i, v: r[j] }))
      .filter((x) => typeof x.v === "number");
    if (!pts.length) return null;
    return {
      max: pts.reduce((a, b) => (b.v > a.v ? b : a)),
      min: pts.reduce((a, b) => (b.v < a.v ? b : a)),
    };
  };
  const summary =
    series.length > 1
      ? series
          .map((name, j) => {
            const e = extremes(j + 1);
            return e
              ? t("chart.series.range", {
                  name,
                  min: fmt(e.min.v),
                  minLabel: spec.rows[e.min.i][0],
                  max: fmt(e.max.v),
                  maxLabel: spec.rows[e.max.i][0],
                })
              : "";
          })
          .filter(Boolean)
          .join(". ")
      : (() => {
          const e = extremes(1);
          return e
            ? [
                t("chart.max", { label: spec.rows[e.max.i][0], value: fmt(e.max.v) }),
                t("chart.min", { label: spec.rows[e.min.i][0], value: fmt(e.min.v) }),
              ].join(". ")
            : "";
        })();
  const tip = h("div", {
    class: "chart-tip",
    role: "status",
    "aria-live": "polite",
  });
  const plot = h(
    "div",
    {
      class: "chart-plot",
      tabindex: "0",
      role: "group",
      "aria-roledescription": t("chart.role"),
      "aria-label": t("chart.aria", {
        title: spec.title,
        type: t(`chart.type.${type}`),
        n,
        s: type === "pie" ? 1 : series.length,
      }),
      "aria-describedby": `${uid}-sum`,
    },
    tip,
  );
  const pctFmt = formatter(lang, "%");
  let active = -1;
  let svg = null;
  let drawn = null;
  let drawnW = 0;
  const tipText = (i) => {
    const row = spec.rows[i];
    if (type === "pie") {
      // the share in the UI language; not repeated when the values already are percentages adding up to ~100
      const share = (row[1] / drawn.total) * 100;
      if (spec.unit === "%" && Math.abs(drawn.total - 100) <= 1)
        return `${row[0]} — ${fmt(row[1])}`;
      return `${row[0]} — ${fmt(row[1])} (${pctFmt(Math.round(share * 10) / 10)})`;
    }
    if (series.length === 1) return `${row[0]} — ${fmt(row[1])}`;
    return null; // several series: one line each (tipLines)
  };
  const show = (i) => {
    if (i < 0 || i >= n || !drawn) return;
    drawn.marks.forEach((group, k) =>
      group.forEach((m) => m.classList.toggle("is-active", k === i)),
    );
    plot.classList.add("has-active");
    active = i;
    const text = tipText(i);
    const sep = lang === "en" ? ":" : "\u00a0:";
    tip.replaceChildren(
      ...(text !== null
        ? [text]
        : [
            h("span", { class: "chart-tip-head", text: String(spec.rows[i][0]) }),
            ...series.map((name, j) =>
              h(
                "span",
                { class: "chart-tip-row" },
                h("span", {
                  class: `chart-swatch series-bg-${j + 1}`,
                  "aria-hidden": "true",
                }),
                `${name}${sep} ${fmt(spec.rows[i][j + 1])}`,
              ),
            ),
          ]),
    );
    tip.classList.add("is-shown");
    // placed in px against the plot after measuring: centred on the item, never past either edge
    const hit = drawn.hits[i];
    const pw = plot.clientWidth;
    const ph = plot.clientHeight;
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    // near an edge it flips to the other side of the item rather than covering it
    const cx = hit.tipX * pw;
    let left = cx - tw / 2;
    if (left + tw > pw - 4) left = cx - tw - 10;
    else if (left < 4) left = cx + 10;
    left = Math.max(4, Math.min(pw - tw - 4, left));
    const top = Math.max(2, Math.min(ph - th - 2, hit.tipY * ph));
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
  };
  const hide = () => {
    drawn?.marks.forEach((group) =>
      group.forEach((m) => m.classList.remove("is-active")),
    );
    plot.classList.remove("has-active");
    tip.classList.remove("is-shown");
    tip.textContent = "";
    active = -1;
  };
  let dismissing = false;
  const dismissOnOutsideTap = () => {
    if (dismissing) return;
    dismissing = true;
    const off = () => {
      dismissing = false;
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("scroll", onScroll, true);
    };
    const outside = (e) => {
      if (!plot.contains(e.target)) (hide(), off());
    };
    const top = plot.getBoundingClientRect().top;
    const onScroll = () => {
      // a real scroll by the reader, not the small jump a tap's focus can cause
      if (Math.abs(plot.getBoundingClientRect().top - top) > 24) hide(), off();
    };
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("scroll", onScroll, { capture: true, passive: true });
  };
  const draw = (width) => {
    W = Math.round(Math.max(MIN_W, Math.min(MAX_W, width)));
    drawnW = W;
    drawn =
      type === "pie"
        ? drawPie(spec, fmt, lang)
        : type === "line"
          ? drawLine(spec, fmt)
          : drawBars(spec, fmt);
    const next = s(
      "svg",
      {
        viewBox: `0 0 ${W} ${drawn.H}`,
        role: "img",
        "aria-labelledby": `${uid}-title ${uid}-sum`,
        focusable: "false",
        class: `chart-svg chart-kind-${type}`,
      },
      drawn.g,
    );
    drawn.hits.forEach((hit, i) => {
      const target =
        hit.path ||
        s("rect", {
          class: "chart-hit",
          x: hit.x,
          y: hit.y,
          width: hit.w,
          height: hit.h,
        });
      if (!hit.path) drawn.g.append(target);
      target.addEventListener("pointerenter", (e) => {
        if (e.pointerType !== "touch") show(i);
      });
      target.addEventListener("pointerdown", (e) => {
        if (e.pointerType !== "touch") return show(i);
        // touch: a tap shows the value and keeps it (pointerleave follows every lift); a second tap hides it
        if (active === i) return hide();
        show(i);
        dismissOnOutsideTap();
      });
    });
    next.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "touch") hide();
    });
    if (svg) svg.replaceWith(next);
    else plot.prepend(next);
    svg = next;
    if (active >= 0) show(active);
  };
  // first draw at the width the card will most likely get; the observer corrects it before the first paint
  const vw = typeof window !== "undefined" ? window.innerWidth || 640 : 640;
  draw(Math.min(720, vw - (vw < 560 ? 46 : 120)));
  if (typeof ResizeObserver !== "undefined") {
    let pending = 0;
    new ResizeObserver((entries) => {
      const w = entries[entries.length - 1].contentRect.width;
      if (!w || Math.abs(Math.round(w) - drawnW) < 2) return;
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(() => draw(w));
    }).observe(plot);
  }
  plot.addEventListener("keydown", (e) => {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (e.key in keys)
      show(
        active < 0
          ? keys[e.key] > 0
            ? 0
            : n - 1
          : Math.max(0, Math.min(n - 1, active + keys[e.key])),
      );
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(n - 1);
    else if (e.key === "Escape") hide();
    else return;
    e.preventDefault();
  });
  plot.addEventListener("blur", hide);

  const legendItems =
    type === "pie"
      ? spec.rows.map((r, i) => [String(r[0]), Math.min(i, 7) + 1])
      : series.length >= 2
        ? series.map((name, j) => [name, j + 1])
        : [];
  const legend =
    legendItems.length > 0 &&
    h(
      "ul",
      { class: "chart-legend" },
      legendItems.map(([name, k]) =>
        h(
          "li",
          null,
          h("span", {
            class: `chart-swatch series-bg-${k}${type === "line" ? " is-line" : ""}`,
            "aria-hidden": "true",
          }),
          h("span", { text: name }),
        ),
      ),
    );
  const table = h(
    "details",
    { class: "chart-data" },
    h("summary", null, icon("chevron", "chev"), t("chart.data")),
    h(
      "div",
      { class: "chart-table-wrap" },
      h(
        "table",
        null,
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            spec.columns.map((c) => h("th", { scope: "col", text: c })),
          ),
        ),
        h(
          "tbody",
          null,
          spec.rows.map((r) =>
            h(
              "tr",
              null,
              h("th", { scope: "row", text: String(r[0]) }),
              r.slice(1).map((v) => h("td", { class: "num", text: fmt(v) })),
            ),
          ),
        ),
      ),
    ),
  );
  const source = ["request", "file", "web", "model"].includes(spec.source)
    ? spec.source
    : "model";
  const meta = [
    t(`chart.type.${type}`),
    spec.unit || "",
    source !== "model" ? t(`chart.source.${source}`) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const reshapedNote =
    Array.isArray(spec.reshaped) && spec.reshaped.length > 0
      ? t("chart.reshaped", {
          notes: spec.reshaped.map(reshapedText).join(lang === "en" ? "; " : " ; "),
        })
      : "";
  let xlsxBusy = false;
  const xlsxBtn = button(
    "btn-outline btn-small",
    "make_sheet",
    t("chart.xlsx"),
    async () => {
      if (xlsxBusy || !onXlsx) return;
      xlsxBusy = true;
      xlsxBtn.disabled = true;
      try {
        await onXlsx(spec);
      } finally {
        xlsxBusy = false;
        xlsxBtn.disabled = false;
      }
    },
    { "data-act": "chart-xlsx" },
  );
  return h(
    "figure",
    { class: "card chart-card", "data-chart": spec.id || uid },
    h(
      "figcaption",
      { class: "chart-head" },
      h("p", { class: "card-name", id: `${uid}-title`, text: spec.title }),
      h(
        "p",
        { class: "card-meta" },
        meta,
        source === "model" &&
          h("span", {
            class: "tag tag-estimated",
            text: t("chart.source.model"),
          }),
      ),
    ),
    plot,
    h("p", { id: `${uid}-sum`, class: "sr-only", text: summary }),
    legend,
    reshapedNote &&
      h("p", { class: "chart-note" }, icon("info"), reshapedNote),
    table,
    h(
      "div",
      { class: "chart-actions" },
      button(
        "btn-outline btn-small",
        "download",
        t("chart.png"),
        () => {
          hide();
          exportPng(svg, spec.title, {
            legend: legendItems,
            // the honesty label travels with the image: where the numbers come from, or "not verified"
            foot: [
              [t(`chart.type.${type}`), spec.unit || "", t(`chart.source.${source}`), "Bird"]
                .filter(Boolean)
                .join(" · "),
              reshapedNote,
            ],
          });
        },
        { "data-act": "chart-png" },
      ),
      button(
        "btn-outline btn-small",
        "copy",
        t("chart.csv"),
        () => copyText(toCsv(spec, lang), t("chart.csv.done")),
        { "data-act": "chart-csv" },
      ),
      onXlsx && xlsxBtn,
    ),
  );
}

/** Markdown table of a chart, for the conversation export. */
export function chartMarkdown(spec, lang) {
  if (spec && spec.v === 2) return chartMarkdown2(spec, lang); // data analysis extension (charts2.js)
  const fmt = formatter(lang, spec.unit);
  const cell = (v) => String(v).replace(/\|/g, "\\|");
  return [
    `| ${spec.columns.map(cell).join(" | ")} |`,
    `| ${spec.columns.map(() => "---").join(" | ")} |`,
    ...spec.rows.map(
      (r) =>
        `| ${[cell(r[0]), ...r.slice(1).map((v) => cell(fmt(v)))].join(" | ")} |`,
    ),
  ].join("\n");
}
