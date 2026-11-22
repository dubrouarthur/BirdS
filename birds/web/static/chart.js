// Charts drawn in the browser as SVG, from the spec the server normalised (birds/harness/tools/chart.py).
// No library. Colours are CSS classes (series-1..6) so the theme switches live and the CSP stays strict;
// the PNG export copies the computed colours into a standalone SVG before drawing it on a canvas.
import { button, copyText, download, h, icon, t, toast } from "./core.js";

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
  return (v) => {
    if (v === null || v === undefined || Number.isNaN(v))
      return t("chart.missing");
    const n = nf.format(v);
    if (!u) return n;
    if (u === "%") return lang === "en" ? `${n}%` : `${n} %`;
    return `${n} ${u}`;
  };
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
  if (!horizontal) {
    const H = 320;
    const m = { l: 56, r: 12, t: 20, b: 46 };
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
          fmt(tk),
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
  const m = { l: W < 600 ? 112 : 150, r: 40, t: tall ? 28 : 12, b: 32 };
  const H = Math.round(m.t + m.b + rowH * labels.length + 8);
  const pw = W - m.l - m.r;
  const x = (v) => m.l + ((v - t0) / (t1 - t0)) * pw;
  for (const tk of ticks) {
    g.append(
      s("line", {
        class: "chart-grid",
        x1: x(tk),
        x2: x(tk),
        y1: m.t,
        y2: H - m.b,
      }),
    );
    g.append(
      s(
        "text",
        {
          class: "chart-tick",
          x: x(tk),
          y: H - m.b + 16,
          "text-anchor": "middle",
        },
        fmt(tk),
      ),
    );
    if (tall)
      g.append(
        s(
          "text",
          { class: "chart-tick", x: x(tk), y: m.t - 10, "text-anchor": "middle" },
          fmt(tk),
        ),
      );
  }
  const bh = (rowH * 0.76) / nS;
  labels.forEach((label, i) => {
    const y0 = m.t + rowH * i + (rowH - bh * nS) / 2;
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
    g.append(
      s(
        "text",
        {
          class: "chart-label",
          x: m.l - 8,
          y: m.t + rowH * i + rowH / 2 + 4,
          "text-anchor": "end",
        },
        cut(label, W < 600 ? 16 : 22),
      ),
    );
    hits.push({
      x: 0,
      y: m.t + rowH * i,
      w: W,
      h: rowH,
      tipX: 0.5,
      tipY: (m.t + rowH * i) / H,
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
  const m = { l: 56, r: direct ? 92 : 16, t: 20, b: 46 };
  const pw = W - m.l - m.r;
  const ph = H - m.t - m.b;
  const vals = valuesOf(spec);
  const ticks = niceTicks(
    Math.min(...vals) >= 0 &&
      Math.min(...vals) < Math.max(...vals) - Math.min(...vals)
      ? 0
      : Math.min(...vals),
    Math.max(...vals),
  );
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
        fmt(tk),
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
        g.append(
          s(
            "text",
            {
              class: "chart-direct",
              x: x(lastIdx) + 8,
              y: y(spec.rows[lastIdx][j + 1]) + 4,
            },
            cut(spec.columns[j + 1], 14),
          ),
        );
    }
  }
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

function standaloneSvg(svg) {
  // copy the computed colours and fonts onto a clone: the PNG is drawn without our stylesheet
  const clone = svg.cloneNode(true);
  const src = [svg, ...svg.querySelectorAll("*")];
  const dst = [clone, ...clone.querySelectorAll("*")];
  src.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const out = dst[i];
    for (const p of [
      "fill",
      "stroke",
      "stroke-width",
      "opacity",
      "font-size",
      "font-weight",
    ]) {
      const v = cs.getPropertyValue(p);
      if (v) out.setAttribute(p, v);
    }
    out.removeAttribute("class");
  });
  const vb = svg.viewBox.baseVal;
  clone.setAttribute("xmlns", NS);
  const k = Math.max(2, 1280 / vb.width); // at least 1280 px wide, whatever the screen it was drawn for
  clone.setAttribute("width", String(Math.round(vb.width * k)));
  clone.setAttribute("height", String(Math.round(vb.height * k)));
  clone.setAttribute("font-family", "system-ui, sans-serif");
  const bg =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--surface")
      .trim() || "#ffffff";
  clone.insertBefore(
    s("rect", { x: 0, y: 0, width: vb.width, height: vb.height, fill: bg }),
    clone.firstChild,
  );
  return {
    text: new XMLSerializer().serializeToString(clone),
    w: Math.round(vb.width * k),
    h: Math.round(vb.height * k),
  };
}

function exportPng(svg, title) {
  const { text, w, h: hh } = standaloneSvg(svg);
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
  const vals = spec.rows
    .map((r, i) => ({ i, v: r[1] }))
    .filter((x) => typeof x.v === "number");
  const max = vals.reduce((a, b) => (b.v > a.v ? b : a), vals[0]);
  const min = vals.reduce((a, b) => (b.v < a.v ? b : a), vals[0]);
  const summary = max
    ? [
        t("chart.max", { label: spec.rows[max.i][0], value: fmt(max.v) }),
        t("chart.min", { label: spec.rows[min.i][0], value: fmt(min.v) }),
      ].join(". ")
    : "";
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
  let active = -1;
  let svg = null;
  let drawn = null;
  let drawnW = 0;
  const tipText = (i) => {
    const row = spec.rows[i];
    if (type === "pie") {
      const pct = new Intl.NumberFormat(lang === "en" ? "en-GB" : "fr-FR", {
        maximumFractionDigits: 1,
      }).format((row[1] / drawn.total) * 100);
      return `${row[0]} — ${fmt(row[1])} (${pct} %)`;
    }
    if (series.length === 1) return `${row[0]} — ${fmt(row[1])}`;
    return `${row[0]} — ${series.map((name, j) => `${name}${lang === "en" ? ":" : " :"} ${fmt(row[j + 1])}`).join(" ; ")}`;
  };
  const show = (i) => {
    if (i < 0 || i >= n || !drawn) return;
    drawn.marks.forEach((group, k) =>
      group.forEach((m) => m.classList.toggle("is-active", k === i)),
    );
    plot.classList.add("has-active");
    active = i;
    tip.textContent = tipText(i);
    const hit = drawn.hits[i];
    tip.style.left = `${Math.max(4, Math.min(96, hit.tipX * 100))}%`;
    tip.style.top = `${Math.max(2, hit.tipY * 100)}%`;
    tip.classList.add("is-shown");
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
      target.addEventListener("pointerenter", () => show(i));
      target.addEventListener("pointerdown", () => show(i));
    });
    next.addEventListener("pointerleave", hide);
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
    Array.isArray(spec.reshaped) &&
      spec.reshaped.length > 0 &&
      h(
        "p",
        { class: "chart-note" },
        icon("info"),
        t("chart.reshaped", {
          notes: spec.reshaped.map(reshapedText).join(lang === "en" ? "; " : " ; "),
        }),
      ),
    table,
    h(
      "div",
      { class: "chart-actions" },
      button(
        "btn-outline btn-small",
        "download",
        t("chart.png"),
        () => (hide(), exportPng(svg, spec.title)),
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
