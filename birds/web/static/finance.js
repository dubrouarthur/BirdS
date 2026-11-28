// Quote card under an answer (get_quote): last price, change as a sign + an arrow + a coloured figure (never colour
// alone), sparkline, period chips (1M 6M 1A 5A) and « Pour continuer » asks. The history chart itself is drawn by
// the chart engine (chart.js: table, PNG, CSV). Data come only from the server's widget (tool results, never model
// text); built with h() only (text nodes, no innerHTML with data); no style attribute (CSP).
import { h, state } from "./core.js";
import { safeUrl } from "./markdown.js";

const lang = () => (state.prefs.lang === "en" ? "en" : "fr");
const locale = () => (lang() === "en" ? "en-GB" : "fr-FR");
const NS = "http://www.w3.org/2000/svg";

export const FINANCE_STRINGS = {
  fr: {
    title: "Cours",
    "title.compare": "Comparaison",
    up: "en hausse de {pct}",
    down: "en baisse de {pct}",
    flat: "stable",
    "base.prev": "depuis la clôture précédente",
    "base.24h": "sur 24 h",
    "base.ref": "depuis le taux précédent",
    "asof.close": "Clôture du {date} · pas en temps réel",
    "asof.live": "Cours du {date} à {time} UTC · différé de quelques minutes",
    "asof.reference": "Taux de référence BCE du {date} · publié vers 16 h",
    period: "Sur {range}",
    high: "plus haut",
    low: "plus bas",
    ranges: "Période",
    "range.1m": "1M",
    "range.6m": "6M",
    "range.1y": "1A",
    "range.5y": "5A",
    "range.1m.long": "1 mois",
    "range.6m.long": "6 mois",
    "range.1y.long": "1 an",
    "range.5y.long": "5 ans",
    "range.ask": "{names} sur {range}",
    "range.share": "cours de {names}",
    "range.crypto": "Historique des cryptoactifs : 1 an au plus chez la source.",
    missing: "Actions et indices non affichés ici ({names}) : flux de marché sous licence non activé.",
    unavailable: "Pas de données pour {names} sur cette période.",
    advice: "Information sur les cours, pas un conseil en investissement.",
    next: "Pour continuer",
    data: "Données",
    spark: "Évolution sur {range}",
    and: " et ",
  },
  en: {
    title: "Price",
    "title.compare": "Comparison",
    up: "up {pct}",
    down: "down {pct}",
    flat: "unchanged",
    "base.prev": "from the previous close",
    "base.24h": "over 24 h",
    "base.ref": "from the previous rate",
    "asof.close": "Close of {date} · not real time",
    "asof.live": "Price on {date} at {time} UTC · a few minutes delayed",
    "asof.reference": "ECB reference rate of {date} · published around 4 pm CET",
    period: "Over {range}",
    high: "high",
    low: "low",
    ranges: "Period",
    "range.1m": "1M",
    "range.6m": "6M",
    "range.1y": "1Y",
    "range.5y": "5Y",
    "range.1m.long": "1 month",
    "range.6m.long": "6 months",
    "range.1y.long": "1 year",
    "range.5y.long": "5 years",
    "range.ask": "{names} over {range}",
    "range.share": "{names} stock",
    "range.crypto": "Crypto history: 1 year at most from the source.",
    missing: "Shares and indices not shown here ({names}): licensed market feed not enabled.",
    unavailable: "No data for {names} over this period.",
    advice: "Price information, not investment advice.",
    next: "Next",
    data: "Data",
    spark: "Trend over {range}",
    and: " and ",
  },
};

export function ft(key, vars) {
  let s = FINANCE_STRINGS[lang()][key] ?? FINANCE_STRINGS.fr[key] ?? key;
  for (const [k, v] of Object.entries(vars || {}))
    s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

const RANGES = ["1m", "6m", "1y", "5y"];

/** A price in its currency (« 358,54 $US », « 1,0957 »), 2 decimals, 4 under 10, none from 10 000. */
export function fmtPrice(v, currency, kind) {
  const x = Number(v);
  if (!Number.isFinite(x)) return "—";
  const digits = Math.abs(x) >= 10000 ? 0 : Math.abs(x) >= 10 ? 2 : 4;
  const o = { minimumFractionDigits: digits, maximumFractionDigits: digits };
  if (kind !== "fx" && /^[A-Z]{3}$/.test(String(currency || ""))) {
    try {
      return new Intl.NumberFormat(locale(), {
        ...o,
        style: "currency",
        currency,
      }).format(x);
    } catch {
      /* an unknown code: the plain number and the code */
    }
  }
  const n = new Intl.NumberFormat(locale(), o).format(x);
  return kind === "fx" || !currency ? n : `${n} ${currency}`;
}

/** « +0,83 % » / « −1,20 % » with a real minus sign; « 0,00 % » when flat. */
export function fmtPct(p) {
  const x = Number(p);
  if (!Number.isFinite(x)) return "—";
  const s = new Intl.NumberFormat(locale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(x));
  const sign = x > 0.004 ? "+" : x < -0.004 ? "−" : "";
  return `${sign}${s}${lang() === "fr" ? " %" : "%"}`;
}

/** "up" | "down" | "flat" for a percentage change (half a hundredth of a point counts as flat). */
export function direction(p) {
  const x = Number(p);
  if (!Number.isFinite(x) || Math.abs(x) < 0.005) return "flat";
  return x > 0 ? "up" : "down";
}

function fmtDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return "";
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 12)).toLocaleDateString(
    locale(),
    { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" },
  );
}

/** The line that dates the figure and states its delay (never « real time » when it is not). */
export function asofLine(item) {
  const at = String(item.asof || "");
  const kind = ["close", "live", "reference"].includes(item.asof_kind)
    ? item.asof_kind
    : "close";
  return ft(`asof.${kind}`, { date: fmtDay(at), time: at.slice(11, 16) });
}

/** The ask a period chip sends: « LVMH et Hermès sur 5 ans » (the harness reads it like a typed message). */
export function rangeAsk(w, r) {
  const items = w.items || [];
  let names = items.map((i) => i.name).join(ft("and"));
  // « Apple » alone is a brand: the ask names the share (the same words as the tool's own asks)
  if (items.some((i) => i.kind === "equity"))
    names = ft("range.share", { names });
  return ft("range.ask", { names, range: ft(`range.${r}.long`) });
}

/** Points of a sparkline in a W x H box (pure, tested). */
export function sparkPoints(values, W = 120, H = 32, pad = 2) {
  const v = (values || []).map(Number).filter(Number.isFinite);
  if (v.length < 2) return "";
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const span = hi - lo || 1;
  return v
    .map((x, i) => {
      const px = pad + (i * (W - 2 * pad)) / (v.length - 1);
      const py = H - pad - ((x - lo) * (H - 2 * pad)) / span;
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

function spark(item, range) {
  const pts = sparkPoints(item.spark);
  if (!pts) return null;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 120 32");
  svg.setAttribute("class", `fin-spark fin-${direction(item.period_pct)}`);
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    `${ft("spark", { range: ft(`range.${range}.long`) })} : ${fmtPct(item.period_pct)}`,
  );
  const line = document.createElementNS(NS, "polyline");
  line.setAttribute("points", pts);
  line.setAttribute("fill", "none");
  line.setAttribute("vector-effect", "non-scaling-stroke");
  svg.append(line);
  return svg;
}

function arrow(dir) {
  return h("span", {
    class: "fin-arrow",
    "aria-hidden": "true",
    text: dir === "up" ? "▲" : dir === "down" ? "▼" : "■",
  });
}

const baseKey = (i) =>
  i.change_base === "24h" ? "base.24h" : i.change_base === "prev_ref" ? "base.ref" : "base.prev";

function change(item) {
  const dir = direction(item.change_pct);
  const pct = fmtPct(item.change_pct);
  const said =
    dir === "flat"
      ? ft("flat")
      : ft(dir, { pct: pct.replace(/^[+−]/, "") });
  return h(
    "p",
    { class: `fin-change fin-${dir}` },
    arrow(dir),
    h("span", { class: "fin-pct num", "aria-hidden": "true", text: pct }),
    h("span", { class: "sr-only", text: said }),
    h("span", {
      class: "fin-base",
      text: ft(baseKey(item)),
    }),
  );
}

function row(item, w) {
  const market = [["crypto", "fx"].includes(item.kind) ? "" : item.symbol, item.mic]
    .filter(Boolean)
    .join(" · ");
  const dirP = direction(item.period_pct);
  return h(
    "li",
    { class: "fin-item", "data-key": item.key },
    h(
      "div",
      { class: "fin-id" },
      h("p", { class: "fin-name", text: item.name }),
      market && h("p", { class: "fin-sym muted", text: market }),
    ),
    h(
      "div",
      { class: "fin-figures" },
      h("p", {
        class: "fin-price num",
        text: fmtPrice(item.last, item.currency, item.kind),
      }),
      change(item),
    ),
    h(
      "div",
      { class: "fin-trend" },
      spark(item, w.range),
      h(
        "p",
        { class: "fin-period muted" },
        `${ft("period", { range: ft(`range.${w.range}.long`) })} `,
        h("span", {
          class: `fin-pp num fin-${dirP}`,
          text: `${dirP === "up" ? "▲ " : dirP === "down" ? "▼ " : ""}${fmtPct(item.period_pct)}`,
        }),
        !w.compare &&
          ` · ${ft("high")} ${fmtPrice(item.high, item.currency, item.kind)} · ${ft("low")} ${fmtPrice(item.low, item.currency, item.kind)}`,
      ),
    ),
    h("p", { class: "fin-asof", text: asofLine(item) }),
  );
}

function ask(q) {
  document.dispatchEvent(new CustomEvent("bird:ask", { detail: q }));
}

function rangeChips(w) {
  const list = (w.ranges || RANGES).filter((r) => RANGES.includes(r));
  return h(
    "div",
    { class: "fin-ranges", role: "group", "aria-label": ft("ranges") },
    list.map((r) =>
      h("button", {
        type: "button",
        class: "fin-range",
        "aria-pressed": r === w.range ? "true" : "false",
        "aria-label": ft(`range.${r}.long`),
        disabled: r === w.range ? true : null,
        text: ft(`range.${r}`),
        onclick: () => ask(rangeAsk(w, r)),
      }),
    ),
  );
}

function link(href, label) {
  const url = safeUrl(href || "");
  return url
    ? h(
        "a",
        {
          class: "widget-link",
          href: url,
          target: "_blank",
          rel: "noopener noreferrer",
          referrerpolicy: "no-referrer",
        },
        label,
      )
    : h("span", { text: label });
}

function sourceLine(w) {
  const parts = [];
  for (const s of w.sources || []) {
    if (parts.length) parts.push(" · ");
    parts.push(link(s.url, s.label), " — ", link(s.license_url, s.license));
  }
  return h(
    "footer",
    { class: "widget-source od-source fin-source" },
    `${ft("data")}${lang() === "fr" ? " : " : ": "}`,
    parts,
  );
}

function nextAsks(w) {
  const list = [...new Set((w.asks || []).filter(Boolean))].slice(0, 3);
  if (!list.length) return null;
  return h(
    "div",
    { class: "od-next", role: "group", "aria-label": ft("next") },
    list.map((q) =>
      h(
        "button",
        { type: "button", class: "od-next-chip", onclick: () => ask(q) },
        h("span", { text: q }),
      ),
    ),
  );
}

export function renderQuote(w) {
  const items = (w.items || []).filter((i) => i && i.name);
  if (!items.length) return null;
  const id = `w-quote-${Math.random().toString(36).slice(2, 8)}`;
  return h(
    "section",
    {
      class: "widget widget-quote od-card",
      "aria-labelledby": id,
      "data-widget": "quote",
    },
    h(
      "div",
      { class: "fin-head" },
      h("h3", {
        class: "eyebrow widget-title",
        id,
        text: ft(w.compare ? "title.compare" : "title"),
      }),
      rangeChips(w),
    ),
    h(
      "ul",
      { class: `fin-list${items.length > 1 ? " fin-multi" : ""}` },
      items.map((i) => row(i, w)),
    ),
    w.range_note === "crypto" &&
      h("p", { class: "fin-note muted", text: ft("range.crypto") }),
    (w.missing || []).length > 0 &&
      h("p", {
        class: "fin-note muted",
        text: ft("missing", { names: w.missing.join(", ") }),
      }),
    (w.unavailable || []).length > 0 &&
      h("p", {
        class: "fin-note muted",
        text: ft("unavailable", { names: w.unavailable.join(", ") }),
      }),
    w.advice && h("p", { class: "fin-note fin-advice", text: ft("advice") }),
    sourceLine(w),
    nextAsks(w),
  );
}

/** The card as plain text (copy, export). */
export function quoteText(w) {
  const lines = (w.items || []).map(
    (i) =>
      `${i.name} : ${fmtPrice(i.last, i.currency, i.kind)} (${fmtPct(i.change_pct)} ${ft(baseKey(i))}) — ${asofLine(i)}`,
  );
  if (w.advice) lines.push(ft("advice"));
  lines.push(
    `${ft("data")} : ${(w.sources || []).map((s) => `${s.label} (${s.license})`).join(" · ")}`,
  );
  return lines.join("\n");
}

export const FINANCE_RENDER = { quote: renderQuote };
