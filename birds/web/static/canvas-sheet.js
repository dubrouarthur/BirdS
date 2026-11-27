// The canvas mini-sheet's logic: cell references, a small formula language evaluated without eval(), sorting,
// chart specs from a selection and a CSV that cannot inject formulas. Pure (node tests): canvas.js draws the grid.
//
// Formulas: =A1+B2*3, =SUM(B2:B9), SOMME, AVERAGE/MOYENNE, MIN, MAX, COUNT/NB, ROUND/ARRONDI(x;n), ABS, IF/SI(c;a;b),
// comparisons (=, <>, <, >, <=, >=), percentages (12%), French decimals (1,5) and « ; » or « , » as separators.

export const MAX_ROWS = 200;
export const MAX_COLS = 26;

export const colName = (i) => String.fromCharCode(65 + i);
export const cellName = (r, c) => `${colName(c)}${r + 1}`;

/** « B3 » -> {r: 2, c: 1}; null when not a reference. */
export function parseRef(ref) {
  const m = /^\$?([A-Z])\$?(\d{1,3})$/i.exec(String(ref).trim());
  if (!m) return null;
  const c = m[1].toUpperCase().charCodeAt(0) - 65;
  const r = Number(m[2]) - 1;
  return r >= 0 && c >= 0 && c < MAX_COLS ? { r, c } : null;
}

/** A number written by a person: « 1 234,5 », « 12 % », « 1,2 M€ » -> 1234.5, 0.12, 1.2 ; NaN otherwise. */
export function toNumber(v) {
  if (typeof v === "number") return v;
  const s = String(v ?? "")
    .trim()
    .replace(/[   ]/g, "");
  if (!s) return NaN;
  const pct = s.endsWith("%");
  let t = s.replace(/%$/, "").replace(/(?:k€|M€|Md€|€|\$|£|EUR|USD)$/i, "");
  if (/^[-+]?\d+,\d+$/.test(t)) t = t.replace(",", ".");
  else if (/^[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$/.test(t))
    t = t.replace(/,/g, "");
  else if (/^[-+]?\d{1,3}(?:\.\d{3})+,\d+$/.test(t))
    t = t.replace(/\./g, "").replace(",", ".");
  if (!/^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i.test(t)) return NaN;
  const n = Number(t);
  return pct ? n / 100 : n;
}

const FUNCS = {
  SUM: "SUM", SOMME: "SUM", AVERAGE: "AVG", MOYENNE: "AVG", AVG: "AVG", MIN: "MIN", MAX: "MAX", COUNT: "COUNT",
  NB: "COUNT", ROUND: "ROUND", ARRONDI: "ROUND", ABS: "ABS", IF: "IF", SI: "IF", PRODUCT: "PRODUCT",
  PRODUIT: "PRODUCT",
}; // prettier-ignore

class FormulaError extends Error {}

function tokenize(src) {
  const out = [];
  let i = 0;
  const s = src;
  while (i < s.length) {
    const ch = s[i];
    if (/\s/.test(ch)) {
      i++;
      continue;
    }
    const rest = s.slice(i);
    let m;
    if (
      (m =
        /^\$?[A-Za-z]\$?\d{1,3}(?::\$?[A-Za-z]\$?\d{1,3})?(?![A-Za-z0-9(])/.exec(
          rest,
        ))
    ) {
      out.push({ t: "ref", v: m[0].replace(/\$/g, "").toUpperCase() });
    } else if ((m = /^[A-Za-zÀ-ÿ]+(?=\s*\()/.exec(rest))) {
      out.push({ t: "fn", v: m[0].toUpperCase() });
    } else if ((m = /^\d+(?:[.,]\d+)?%?/.exec(rest))) {
      out.push({ t: "num", v: toNumber(m[0]) });
    } else if ((m = /^"([^"]*)"/.exec(rest))) {
      out.push({ t: "str", v: m[1] });
    } else if ((m = /^(?:<=|>=|<>|[-+*/^()<>=;,&])/.exec(rest))) {
      out.push({ t: "op", v: m[0] });
    } else throw new FormulaError("syntax");
    i += m[0].length;
  }
  return out;
}

/** Evaluate a formula (without its leading « = ») with ``get(r, c)`` returning a cell's value. */
export function evaluate(src, get) {
  const toks = tokenize(src);
  let k = 0;
  const peek = () => toks[k];
  const take = (v) => {
    const t = toks[k];
    if (!t || (v !== undefined && t.v !== v)) throw new FormulaError("syntax");
    k++;
    return t;
  };
  const range = (ref) => {
    const [a, b] = ref.split(":");
    const p = parseRef(a);
    const q = parseRef(b || a);
    if (!p || !q) throw new FormulaError("ref");
    const out = [];
    for (let r = Math.min(p.r, q.r); r <= Math.max(p.r, q.r); r++)
      for (let c = Math.min(p.c, q.c); c <= Math.max(p.c, q.c); c++)
        out.push(get(r, c));
    return out;
  };
  const num = (v) => {
    if (typeof v === "number") return v;
    if (v === "" || v === null || v === undefined) return 0;
    const n = toNumber(v);
    if (Number.isNaN(n)) throw new FormulaError("value");
    return n;
  };
  function args() {
    take("(");
    const list = [];
    if (peek()?.v === ")") {
      k++;
      return list;
    }
    for (;;) {
      const t = peek();
      if (t?.t === "ref" && t.v.includes(":")) {
        k++;
        list.push(range(t.v));
      } else list.push(comparison());
      const sep = take();
      if (sep.v === ")") return list;
      if (sep.v !== ";" && sep.v !== ",") throw new FormulaError("syntax");
    }
  }
  function primary() {
    const t = take();
    if (t.t === "num") return t.v;
    if (t.t === "str") return t.v;
    if (t.t === "ref") {
      if (t.v.includes(":")) throw new FormulaError("range");
      const p = parseRef(t.v);
      if (!p) throw new FormulaError("ref");
      return get(p.r, p.c);
    }
    if (t.v === "(") {
      const v = comparison();
      take(")");
      return v;
    }
    if (t.v === "-") return -num(power());
    if (t.v === "+") return num(power());
    if (t.t === "fn") {
      const name = FUNCS[t.v];
      if (!name) throw new FormulaError("name");
      const a = args();
      const flat = a
        .flat()
        .filter((v) => v !== "" && v !== null && v !== undefined);
      const nums = flat
        .map((v) => (typeof v === "number" ? v : toNumber(v)))
        .filter((v) => !Number.isNaN(v));
      if (name === "SUM") return nums.reduce((x, y) => x + y, 0);
      if (name === "PRODUCT") return nums.reduce((x, y) => x * y, 1);
      if (name === "AVG") {
        if (!nums.length) throw new FormulaError("div0");
        return nums.reduce((x, y) => x + y, 0) / nums.length;
      }
      if (name === "MIN") return nums.length ? Math.min(...nums) : 0;
      if (name === "MAX") return nums.length ? Math.max(...nums) : 0;
      if (name === "COUNT") return nums.length;
      if (name === "ABS") return Math.abs(num(a[0]));
      if (name === "ROUND") {
        const f = 10 ** Math.max(0, Math.min(10, Math.trunc(num(a[1] ?? 0))));
        return Math.round(num(a[0]) * f) / f;
      }
      if (name === "IF")
        return a[0] && a[0] !== 0 ? (a[1] ?? true) : (a[2] ?? false);
    }
    throw new FormulaError("syntax");
  }
  function power() {
    let v = primary();
    while (peek()?.v === "^") {
      k++;
      v = num(v) ** num(primary());
    }
    return v;
  }
  function product() {
    let v = power();
    while (peek()?.v === "*" || peek()?.v === "/") {
      const op = take().v;
      const r = num(power());
      if (op === "/" && r === 0) throw new FormulaError("div0");
      v = op === "*" ? num(v) * r : num(v) / r;
    }
    return v;
  }
  function sum() {
    let v = product();
    while (peek()?.v === "+" || peek()?.v === "-" || peek()?.v === "&") {
      const op = take().v;
      const r = product();
      v =
        op === "&"
          ? `${v ?? ""}${r ?? ""}`
          : op === "+"
            ? num(v) + num(r)
            : num(v) - num(r);
    }
    return v;
  }
  function comparison() {
    const v = sum();
    const op = peek()?.v;
    if (["=", "<>", "<", ">", "<=", ">="].includes(op)) {
      k++;
      const r = sum();
      const a = typeof v === "number" ? v : toNumber(v);
      const b = typeof r === "number" ? r : toNumber(r);
      const both = !Number.isNaN(a) && !Number.isNaN(b);
      const x = both ? a : String(v);
      const y = both ? b : String(r);
      return {
        "=": x === y,
        "<>": x !== y,
        "<": x < y,
        ">": x > y,
        "<=": x <= y,
        ">=": x >= y,
      }[op]
        ? 1
        : 0;
    }
    return v;
  }
  const v = comparison();
  if (k !== toks.length) throw new FormulaError("syntax");
  return v;
}

const ERR = { syntax: "#ERREUR", ref: "#REF!", name: "#NOM?", value: "#VALEUR!", div0: "#DIV/0!", cycle: "#CYCLE!",
  range: "#VALEUR!" }; // prettier-ignore

/** Every cell's displayed value: numbers for formulas and numeric text, the text otherwise, an error code. */
export function compute(rows) {
  const memo = new Map();
  const busy = new Set();
  const get = (r, c) => {
    const key = `${r},${c}`;
    if (memo.has(key)) return memo.get(key);
    const raw = rows[r]?.[c];
    if (typeof raw !== "string" || !raw.startsWith("=")) {
      const n = toNumber(raw);
      const v =
        raw === undefined || raw === null || raw === ""
          ? ""
          : Number.isNaN(n)
            ? String(raw)
            : n;
      memo.set(key, v);
      return v;
    }
    if (busy.has(key)) throw new FormulaError("cycle");
    busy.add(key);
    let v;
    try {
      v = evaluate(raw.slice(1), get);
      if (typeof v === "number" && !Number.isFinite(v)) v = ERR.div0;
    } catch (e) {
      if (e instanceof FormulaError && e.message === "cycle") {
        busy.delete(key);
        memo.set(key, ERR.cycle);
        throw e;
      }
      v = e instanceof FormulaError ? ERR[e.message] || ERR.syntax : ERR.syntax;
    }
    busy.delete(key);
    memo.set(key, v);
    return v;
  };
  return rows.map((row, r) =>
    row.map((_, c) => {
      try {
        return get(r, c);
      } catch {
        return ERR.cycle;
      }
    }),
  );
}

export const isError = (v) =>
  typeof v === "string" && v.startsWith("#") && /[!?]$|^#ERREUR$/.test(v);

/** Rows sorted by one column's computed values (numbers before text; empty last). Returns a new array. */
export function sortRows(rows, values, col, dir = 1) {
  const idx = rows.map((_, i) => i);
  idx.sort((a, b) => {
    const x = values[a]?.[col];
    const y = values[b]?.[col];
    const ex = x === "" || x === undefined;
    const ey = y === "" || y === undefined;
    if (ex !== ey) return ex ? 1 : -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
    if (typeof x === "number") return -1 * dir;
    if (typeof y === "number") return 1 * dir;
    return String(x).localeCompare(String(y), "fr", { numeric: true }) * dir;
  });
  return idx.map((i) => rows[i]);
}

/**
 * A chart spec (the chat's chart.js format: {type, columns, rows, unit, title}) from a rectangular selection of
 * computed values: the first column gives the labels, the numeric columns the series. Null when nothing numeric.
 */
export function chartFrom(columns, values, sel, title = "") {
  const { r0, r1, c0, c1 } = sel;
  if (c1 <= c0) return null;
  const series = [];
  for (let c = c0 + 1; c <= c1; c++) {
    const nums = [];
    for (let r = r0; r <= r1; r++) nums.push(values[r]?.[c]);
    if (
      nums.filter((v) => typeof v === "number").length >=
      Math.max(1, Math.ceil(nums.length / 2))
    )
      series.push(c);
  }
  if (!series.length || r1 - r0 + 1 < 1) return null;
  const rows = [];
  for (let r = r0; r <= r1; r++) {
    const label = String(values[r]?.[c0] ?? "").slice(0, 40);
    rows.push([
      label || String(r + 1),
      ...series.map((c) =>
        typeof values[r]?.[c] === "number" ? values[r][c] : null,
      ),
    ]);
  }
  const timeish = rows.every((x) =>
    /^(?:19|20)\d{2}|^(?:janv|févr|fév|mars|avr|mai|juin|juil|août|sept|oct|nov|déc|jan|feb|mar|apr|may|jun|jul|aug|sep|dec|t[1-4]|q[1-4])/i.test(
      x[0],
    ),
  );
  return {
    type: timeish && rows.length >= 3 ? "line" : "bar",
    title: title.slice(0, 120),
    columns: [
      String(columns[c0] ?? ""),
      ...series.map((c) => String(columns[c] ?? colName(c))),
    ].map((x) => x.slice(0, 60)),
    rows,
    unit: "",
  };
}

/** CSV of the displayed values; a text that starts with = + - @ (or a tab/CR) is prefixed with « ' » so a
 * spreadsheet never runs it as a formula (CSV/formula injection). */
export function toCsv(columns, values, sep = ";") {
  const cell = (v) => {
    let s =
      typeof v === "number"
        ? String(v).replace(".", sep === ";" ? "," : ".")
        : String(v ?? "");
    if (typeof v !== "number" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /["\n\r;,]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns, ...values]
    .map((row) => row.map(cell).join(sep))
    .join("\r\n");
}

/** A Markdown table of a selection (for « Demander à Bird »), cells escaped. */
export function selectionMarkdown(columns, values, sel) {
  const esc = (v) =>
    String(typeof v === "number" ? v : (v ?? ""))
      .replace(/\|/g, "\\|")
      .replace(/\n/g, " ");
  const head = [];
  for (let c = sel.c0; c <= sel.c1; c++)
    head.push(esc(columns[c] ?? colName(c)));
  const lines = [
    `| ${head.join(" | ")} |`,
    `|${head.map(() => "---").join("|")}|`,
  ];
  for (let r = sel.r0; r <= sel.r1; r++) {
    const row = [];
    for (let c = sel.c0; c <= sel.c1; c++) row.push(esc(values[r]?.[c]));
    lines.push(`| ${row.join(" | ")} |`);
  }
  return lines.join("\n");
}
