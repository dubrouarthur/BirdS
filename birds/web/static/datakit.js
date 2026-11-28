// The data card: what Bird read in an attached CSV / XLSX or a pasted table (birds/harness/analysis), drawn from the
// harness's profile only (never from model text). Header (rows × columns), column chips with a type glyph and a
// mini-histogram or sparkline, suggested analyses that run at once (results computed by the harness, shipped with
// the card), and an interactive table: sort, filter, search, sticky header, totals row, full screen, virtualised for
// 50 000 rows. A click on a column or a cell puts a reference in the composer (« colonne CA », « ligne 12 »).
import { activeMode, h, icon, state, toast } from "./core.js";
import { composerInsert, fmtValue, renderChart2 } from "./charts2.js";

const NS = "http://www.w3.org/2000/svg";
const ROW_H = 34;
const OVERSCAN = 8;

const WORDS = {
  fr: {
    rows: "lignes", cols: "colonnes", complete: "complet", read: "Lu par Bird", suggestions: "Analyses en un clic",
    table: "Tableau", search: "Rechercher dans le tableau", filter: "Filtrer", clear: "Effacer", full: "Plein écran",
    exitFull: "Quitter le plein écran", loadAll: "Charger les {n} lignes", loading: "Chargement…", of: "sur",
    total: "Total", mean: "Moyenne", count: "Valeurs", column: "colonne", row: "ligne", missing: "vides",
    distinct: "valeurs", sum: "Σ", noRow: "Aucune ligne ne correspond", sortAsc: "Tri croissant", sortDesc: "Tri décroissant",
    refCol: "Ajouter « colonne {name} » au message", refCell: "Ajouter cette cellule au message", sep: "séparateur",
    sheet: "feuille", header2: "en-tête sur 2 lignes", totalRow: "ligne « Total » mise à part", skipped: "{n} ligne(s) de titre ignorée(s)",
    truncated: "fichier tronqué à 50 000 lignes", lost: "Joignez à nouveau le fichier pour voir toutes ses lignes",
    types: { number: "Nombre", date: "Date", category: "Catégorie", text: "Texte", bool: "Oui / non", id: "Identifiant" },
    op: { contains: "contient", eq: "=", gt: ">", lt: "<" }, value: "valeur", result: "Résultat", more: "+ {n} lignes",
    asked: "Votre question", outliers: "{n} valeur(s) extrême(s)", source: "Source : {name} — analyse calculée par Bird, sans modèle",
    edit: "Modifier le graphique", version: "Version {n}", tableOf: "Tableau complet ({n} lignes)",
    sourceAsked: "Source : {name} — analyse recalculée par Bird sur le fichier",
  },
  en: {
    rows: "rows", cols: "columns", complete: "complete", read: "Read by Bird", suggestions: "One-click analyses",
    table: "Table", search: "Search the table", filter: "Filter", clear: "Clear", full: "Full screen",
    exitFull: "Exit full screen", loadAll: "Load all {n} rows", loading: "Loading…", of: "of", total: "Total",
    mean: "Mean", count: "Values", column: "column", row: "row", missing: "empty", distinct: "values", sum: "Σ",
    noRow: "No row matches", sortAsc: "Sorted ascending", sortDesc: "Sorted descending",
    refCol: "Add “column {name}” to the message", refCell: "Add this cell to the message", sep: "separator",
    sheet: "sheet", header2: "2-row header", totalRow: "“Total” row set aside", skipped: "{n} title line(s) skipped",
    truncated: "file cut at 50,000 rows", lost: "Attach the file again to see all its rows",
    types: { number: "Number", date: "Date", category: "Category", text: "Text", bool: "Yes / no", id: "Identifier" },
    op: { contains: "contains", eq: "=", gt: ">", lt: "<" }, value: "value", result: "Result", more: "+ {n} rows",
    asked: "Your question", outliers: "{n} outlier(s)", source: "Source: {name} — analysis computed by Bird, no model",
    edit: "Edit the chart", version: "Version {n}", tableOf: "Full table ({n} rows)",
    sourceAsked: "Source: {name} — analysis recomputed by Bird on the file",
  },
}; // prettier-ignore
const L = (lang) => WORDS[lang === "en" ? "en" : "fr"];
const fill = (text, vars) =>
  String(text).replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
const num = (v) => typeof v === "number" && Number.isFinite(v);

function sv(tag, attrs, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {}))
    if (v !== null && v !== undefined) el.setAttribute(k, String(v));
  for (const c of children.flat()) if (c) el.append(c);
  return el;
}

// ------------------------------------------------------------------ formatting

function fmtDate(iso, lang) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?/.exec(
    String(iso || ""),
  );
  if (!m) return String(iso ?? "");
  const t = m[4] ? ` ${m[4]}:${m[5]}` : "";
  return lang === "en"
    ? `${m[1]}-${m[2]}-${m[3]}${t}`
    : `${m[3]}/${m[2]}/${m[1]}${t}`;
}

function cellText(v, col, lang) {
  if (v === null || v === undefined || v === "") return "";
  if (col.type === "number") return fmtValue(v, col.unit, lang);
  if (col.type === "date") return fmtDate(v, lang);
  if (col.type === "bool")
    return v ? (lang === "en" ? "Yes" : "Oui") : lang === "en" ? "No" : "Non";
  return String(v);
}

// ------------------------------------------------------------------ glyphs and mini charts

const TYPE_PATH = {
  number: "M5 4l-1 12M11 4l-1 12M3 8h11M2 12h11",
  date: "M4 6h12v10H4zM4 9h12M7 4v3M13 4v3",
  category: "M3 10l7-7h6v6l-7 7zM13 7h.1",
  text: "M4 15l3.5-9 3.5 9M5.3 12h4.4M13 9.5c2.5-1 4 0 4 2v3.5M17 12.5c-3-.5-4.5.3-4.5 1.6 0 1.6 2.6 1.6 4.5-.6",
  bool: "M4 10l4 4 8-8",
  id: "M7 4L5 16M13 4l-2 12M3.5 8h13M2.5 12h13",
};
function typeGlyph(type) {
  return sv("svg", { class: "icon dk-glyph", viewBox: "0 0 20 20", "aria-hidden": "true", focusable: "false" },
    sv("path", { d: TYPE_PATH[type] || TYPE_PATH.text })); // prettier-ignore
}

function miniBars(values, cls = "series-1") {
  const n = values.length;
  const max = Math.max(1, ...values);
  const w = 64;
  const hh = 22;
  const bw = w / Math.max(1, n);
  return sv("svg", { class: "dk-mini", viewBox: `0 0 ${w} ${hh}`, "aria-hidden": "true", focusable: "false" },
    ...values.map((v, i) => sv("rect", { class: cls, x: (i * bw + 0.5).toFixed(2), y: (hh - (v / max) * hh).toFixed(2),
      width: Math.max(1, bw - 1).toFixed(2), height: Math.max(v ? 1 : 0, (v / max) * hh).toFixed(2), rx: 1 }))); // prettier-ignore
}

function miniLine(values) {
  const n = values.length;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const w = 64;
  const hh = 22;
  const d = values
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${((i * w) / Math.max(1, n - 1)).toFixed(1)},${(hh - 2 - ((v - lo) / (hi - lo || 1)) * (hh - 4)).toFixed(1)}`,
    )
    .join("");
  return sv("svg", { class: "dk-mini", viewBox: `0 0 ${w} ${hh}`, "aria-hidden": "true", focusable: "false" },
    sv("path", { class: "dk-spark stroke-1", d })); // prettier-ignore
}

function miniTop(top, count) {
  const w = 64;
  let x = 0;
  const parts = [];
  (top || []).slice(0, 4).forEach(([, k], i) => {
    const ww = (k / Math.max(1, count)) * w;
    parts.push(
      sv("rect", {
        class: `series-${i + 1}`,
        x: x.toFixed(2),
        y: 8,
        width: Math.max(1, ww - 1).toFixed(2),
        height: 8,
        rx: 2,
      }),
    );
    x += ww;
  });
  if (x < w)
    parts.push(
      sv("rect", {
        class: "series-8",
        x: x.toFixed(2),
        y: 8,
        width: (w - x).toFixed(2),
        height: 8,
        rx: 2,
      }),
    );
  return sv(
    "svg",
    {
      class: "dk-mini",
      viewBox: `0 0 ${w} 22`,
      "aria-hidden": "true",
      focusable: "false",
    },
    ...parts,
  );
}

function columnStat(c, lang) {
  const w = L(lang);
  if (c.type === "number" && c.stats) {
    const st = c.stats;
    const additive = c.unit !== "%" && !/prix|price|taux|rate/i.test(c.name);
    return additive
      ? `${w.sum} ${fmtValue(st.sum, c.unit, lang, true)}`
      : `${w.mean} ${fmtValue(st.mean, c.unit, lang, true)}`;
  }
  if (c.type === "date" && c.span)
    return `${fmtDate(c.span.start, lang)} → ${fmtDate(c.span.end, lang)}`;
  if (c.top) return `${c.distinct} ${w.distinct}`;
  return `${c.count} ${w.count.toLowerCase()}`;
}

function columnTitle(c, lang) {
  const w = L(lang);
  const lines = [
    `${c.name} — ${w.types[c.type] || c.type}${c.unit ? ` (${c.unit})` : ""}`,
  ];
  if (c.stats) {
    const st = c.stats;
    lines.push(`min ${fmtValue(st.min, c.unit, lang)} · max ${fmtValue(st.max, c.unit, lang)}`,
      `${w.mean.toLowerCase()} ${fmtValue(st.mean, c.unit, lang)} · médiane ${fmtValue(st.median, c.unit, lang)}`); // prettier-ignore
    if (st.outliers?.n) lines.push(fill(w.outliers, { n: st.outliers.n }));
  }
  if (c.top)
    lines.push(
      c.top
        .slice(0, 3)
        .map(([k, n]) => `${k} (${n})`)
        .join(", "),
    );
  if (c.missing) lines.push(`${c.missing} ${w.missing}`);
  return lines.join("\n");
}

// ------------------------------------------------------------------ full table (fetched on demand)

const tableCache = new Map(); // card id -> {columns, rows, totals}

function attachmentFor(card) {
  if (card.origin !== "attachment") return null;
  const docs = state.conv?.attachments || [];
  return docs.find((a) => a.name === card.name && a.content && !a.lost) || null;
}

async function loadFull(card) {
  if (tableCache.has(card.id)) return tableCache.get(card.id);
  const doc = attachmentFor(card);
  if (!doc) return null;
  const headers = { "Content-Type": "application/json" };
  if (activeMode() !== "demo" && state.prefs?.access)
    headers["X-Bird-Access"] = state.prefs.access;
  const res = await fetch("/api/data/table", {
    method: "POST",
    headers,
    body: JSON.stringify({
      name: doc.name,
      content: doc.content,
      encoding: doc.encoding || "text",
      lang: card.lang || "fr",
    }),
  });
  if (!res.ok) throw new Error(String(res.status));
  const data = await res.json();
  tableCache.set(card.id, data);
  return data;
}

// ------------------------------------------------------------------ the interactive table

function interactiveTable(card, lang) {
  const w = L(lang);
  const cols = card.columns.map((c) => ({
    name: c.name,
    type: c.type,
    unit: c.unit || "",
  }));
  let rows = card.sample || [];
  let full = !!card.complete_rows;
  let sortCol = -1;
  let sortDir = 0; // 1 asc, -1 desc
  let query = "";
  let filter = null; // {col, op, value}
  let view = rows.map((_, i) => i);
  // column widths from the header and a sample of the cells (ch units, capped)
  const widths = cols.map((c, j) => {
    const longest = Math.max(
      c.name.length + 3,
      ...rows.slice(0, 60).map((r) => cellText(r[j], c, lang).length),
    );
    return Math.max(c.type === "number" ? 9 : 7, Math.min(28, longest + 2));
  });
  const scroller = h("div", {
    class: "dk-scroll",
    tabindex: "0",
    role: "grid",
    "aria-label": `${w.table} — ${card.name}`,
  });
  scroller.style.setProperty(
    "--dk-cols",
    `4.2em ${widths.map((x) => `minmax(${x}ch, 1fr)`).join(" ")}`,
  );
  // head, body and footer share one width: the container's, or the columns' minimum when wider (scrolls sideways)
  scroller.style.setProperty("--dk-w", `max(100%, calc(4.2em + ${widths.reduce((a, b) => a + b, 0)}ch + ${cols.length * 20}px))`);
  const headRow = h("div", {
    class: "dk-row dk-head",
    role: "row",
    "aria-rowindex": "1",
  });
  const body = h("div", { class: "dk-body", role: "rowgroup" });
  const foot = h("div", { class: "dk-row dk-foot", role: "row" });
  scroller.append(headRow, body, foot);
  const count = h("span", { class: "dk-count", "aria-live": "polite" });
  const more = h("button", {
    type: "button",
    class: "btn btn-outline btn-small dk-load",
    hidden: true,
  });

  const headCells = cols.map((c, j) => {
    const btn = h("button", { type: "button", class: "dk-sort", title: c.name,
      onclick: () => {
        if (sortCol !== j) (sortCol = j), (sortDir = c.type === "number" || c.type === "date" ? -1 : 1);
        else if (sortDir === -1) sortDir = 1;
        else if (sortDir === 1 && (c.type === "number" || c.type === "date")) sortCol = -1;
        else sortDir = -1;
        ensureFull().then(apply);
      } }, typeGlyph(c.type), h("span", { class: "dk-th-name", text: c.name }), h("span", { class: "dk-arrow", "aria-hidden": "true" })); // prettier-ignore
    const ref = h("button", { type: "button", class: "dk-ref", "aria-label": fill(w.refCol, { name: c.name }), title: fill(w.refCol, { name: c.name }),
      onclick: () => composerInsert(`${w.column} « ${c.name} »`) }, icon("plus")); // prettier-ignore
    return h(
      "div",
      {
        class: `dk-cell dk-th${c.type === "number" ? " dk-num" : ""}`,
        role: "columnheader",
        "aria-sort": "none",
      },
      btn,
      ref,
    );
  });
  headRow.append(
    h("div", { class: "dk-cell dk-th dk-n", role: "columnheader", text: "#" }),
    ...headCells,
  );

  const footCells = () => {
    const tot = tableCache.get(card.id)?.totals || card.totals || [];
    const filtered = view.length !== rows.length || !!query.trim() || !!filter;
    const mean = lang === "en" ? "avg" : "moy.";
    foot.replaceChildren(h("div", { class: "dk-cell dk-n", role: "rowheader", text: w.total }),
      ...cols.map((c, j) => {
        let text = "";
        if (c.type === "number") {
          const t = tot[j] || {};
          if (filtered || !full) {
            const xs = view.map((i) => rows[i][j]).filter(num);
            const v = "sum" in t ? xs.reduce((a, b) => a + b, 0) : xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
            text = `${"sum" in t ? "" : `${mean} `}${fmtValue(v, c.unit, lang)}`;
          } else text = "sum" in t ? fmtValue(t.sum, c.unit, lang) : `${mean} ${fmtValue(t.mean, c.unit, lang)}`;
          if (!full && !filtered) text = "sum" in t ? fmtValue(t.sum, c.unit, lang) : `${mean} ${fmtValue(t.mean, c.unit, lang)}`;
        } else if (j === 0) text = `${fmtValue(full || filtered ? view.length : card.rows, "", lang)} ${w.rows}`;
        return h("div", { class: `dk-cell${c.type === "number" ? " dk-num" : ""}`, role: "gridcell", text });
      })); // prettier-ignore
  };

  let first = -1;
  let last = -1;
  const paint = (force = false) => {
    const top = scroller.scrollTop;
    const hgt = scroller.clientHeight || 360;
    const s0 = Math.max(0, Math.floor(top / ROW_H) - OVERSCAN);
    const s1 = Math.min(view.length, Math.ceil((top + hgt) / ROW_H) + OVERSCAN);
    if (!force && s0 === first && s1 === last) return;
    first = s0;
    last = s1;
    body.style.setProperty("--dk-h", `${view.length * ROW_H}px`);
    const out = [];
    for (let k = s0; k < s1; k++) {
      const i = view[k];
      const r = rows[i];
      const row = h("div", {
        class: "dk-row",
        role: "row",
        "aria-rowindex": String(k + 2),
      });
      row.style.setProperty("--dk-y", `${k * ROW_H}px`);
      row.append(h("div", { class: "dk-cell dk-n", role: "rowheader" },
        h("button", { type: "button", class: "dk-rowref", text: String(i + 1), title: `${w.row} ${i + 1}`,
          onclick: () => composerInsert(`${w.row} ${i + 1}`) }))); // prettier-ignore
      cols.forEach((c, j) => {
        const text = cellText(r[j], c, lang);
        row.append(h("div", { class: `dk-cell${c.type === "number" ? " dk-num" : ""}${text ? "" : " is-empty"}`, role: "gridcell",
          title: text, "data-ref": "1", onclick: () => composerInsert(`${w.row} ${i + 1}, ${c.name} = ${text || "—"}`) }, text)); // prettier-ignore
      });
      out.push(row);
    }
    body.replaceChildren(...out);
    if (!view.length) body.append(h("p", { class: "dk-none", text: w.noRow }));
  };
  scroller.addEventListener(
    "scroll",
    () => {
      paint();
      if (
        !full &&
        scroller.scrollTop + scroller.clientHeight >
          body.offsetHeight - ROW_H * 4
      )
        ensureFull().then((ok) => ok && apply());
    },
    { passive: true },
  );

  const apply = () => {
    const q = query.trim().toLowerCase();
    view = rows
      .map((_, i) => i)
      .filter((i) => {
        const r = rows[i];
        if (
          q &&
          !r.some((v, j) =>
            cellText(v, cols[j], lang).toLowerCase().includes(q),
          )
        )
          return false;
        if (filter && filter.value !== "") {
          const c = cols[filter.col];
          const v = r[filter.col];
          if (c.type === "number" && filter.op !== "contains") {
            const x = Number(
              String(filter.value).replace(/\s/g, "").replace(",", "."),
            );
            if (!num(v) || !Number.isFinite(x)) return false;
            if (filter.op === "eq" && v !== x) return false;
            if (filter.op === "gt" && !(v > x)) return false;
            if (filter.op === "lt" && !(v < x)) return false;
          } else {
            const t = cellText(v, c, lang).toLowerCase();
            const f = String(filter.value).toLowerCase();
            if (filter.op === "eq" ? t !== f : !t.includes(f)) return false;
          }
        }
        return true;
      });
    if (sortCol >= 0) {
      const j = sortCol;
      const c = cols[j];
      view.sort((a, b) => {
        const x = rows[a][j];
        const y = rows[b][j];
        if (x === null || x === undefined || x === "") return 1;
        if (y === null || y === undefined || y === "") return -1;
        const d =
          c.type === "number"
            ? x - y
            : String(x).localeCompare(String(y), lang === "en" ? "en" : "fr", {
                numeric: true,
              });
        return d * sortDir;
      });
    }
    headCells.forEach((cell, j) => {
      cell.setAttribute(
        "aria-sort",
        j === sortCol ? (sortDir > 0 ? "ascending" : "descending") : "none",
      );
      cell.querySelector(".dk-arrow").textContent =
        j === sortCol ? (sortDir > 0 ? "↑" : "↓") : "";
    });
    scroller.setAttribute("aria-rowcount", String(view.length + 1));
    const total = full ? rows.length : card.rows;
    count.textContent =
      view.length === total
        ? `${fmtValue(total, "", lang)} ${w.rows}`
        : `${fmtValue(view.length, "", lang)} ${w.of} ${fmtValue(total, "", lang)} ${w.rows}`;
    more.hidden = full;
    footCells();
    paint(true);
  };

  let loading = null;
  const ensureFull = () => {
    if (full) return Promise.resolve(false);
    if (!attachmentFor(card)) {
      more.textContent = w.lost;
      more.disabled = true;
      more.hidden = false;
      return Promise.resolve(false);
    }
    if (!loading) {
      more.textContent = w.loading;
      more.disabled = true;
      loading = loadFull(card)
        .then((data) => {
          if (!data) return false;
          rows = data.rows;
          full = true;
          return true;
        })
        .catch(() => {
          more.disabled = false;
          more.textContent = fill(w.loadAll, {
            n: fmtValue(card.rows, "", lang),
          });
          loading = null;
          toast(
            lang === "en"
              ? "The full table could not be loaded"
              : "Le tableau complet n'a pas pu être chargé",
            "error",
          );
          return false;
        });
    }
    return loading;
  };
  more.textContent = fill(w.loadAll, { n: fmtValue(card.rows, "", lang) });
  more.addEventListener("click", () => ensureFull().then(apply));

  // ---- toolbar: search, filter, full screen
  const search = h("input", { type: "search", class: "dk-search", placeholder: w.search, "aria-label": w.search,
    oninput: (e) => {
      query = e.target.value;
      ensureFull().then(apply);
      apply();
    } }); // prettier-ignore
  const fCol = h(
    "select",
    { class: "dk-select", "aria-label": `${w.filter} — ${w.column}` },
    cols.map((c, j) => h("option", { value: String(j), text: c.name })),
  );
  const fOp = h(
    "select",
    { class: "dk-select dk-op", "aria-label": `${w.filter} — op` },
    Object.entries(w.op).map(([k, v]) => h("option", { value: k, text: v })),
  );
  const fVal = h("input", {
    type: "text",
    class: "dk-search dk-fval",
    placeholder: w.value,
    "aria-label": `${w.filter} — ${w.value}`,
  });
  const runFilter = () => {
    filter = fVal.value.trim()
      ? { col: Number(fCol.value), op: fOp.value, value: fVal.value.trim() }
      : null;
    ensureFull().then(apply);
    apply();
  };
  for (const el of [fCol, fOp]) el.addEventListener("change", runFilter);
  fVal.addEventListener("input", runFilter);
  const filterBox = h("div", { class: "dk-filter", hidden: true }, fCol, fOp, fVal,
    h("button", { type: "button", class: "btn btn-outline btn-small", text: w.clear, onclick: () => { fVal.value = ""; runFilter(); } })); // prettier-ignore
  const filterBtn = h("button", { type: "button", class: "btn btn-outline btn-small", "aria-expanded": "false",
    onclick: () => {
      filterBox.hidden = !filterBox.hidden;
      filterBtn.setAttribute("aria-expanded", filterBox.hidden ? "false" : "true");
      if (!filterBox.hidden) fVal.focus();
    } }, icon("search"), h("span", { class: "btn-label", text: w.filter })); // prettier-ignore
  const wrap = h("div", { class: "dk-table" });
  const fullBtn = h("button", { type: "button", class: "btn btn-outline btn-small btn-icon", "aria-label": w.full, title: w.full,
    onclick: () => {
      const on = !wrap.classList.contains("is-full");
      wrap.classList.toggle("is-full", on);
      document.documentElement.classList.toggle("dk-has-full", on);
      fullBtn.setAttribute("aria-label", on ? w.exitFull : w.full);
      fullBtn.title = on ? w.exitFull : w.full;
      if (on) ensureFull().then(apply);
      requestAnimationFrame(() => paint(true));
      scroller.focus();
    } }, icon("expand")); // prettier-ignore
  wrap.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && wrap.classList.contains("is-full"))
      fullBtn.click();
  });
  wrap.append(
    h("div", { class: "dk-tools" }, search, filterBtn, count, fullBtn),
    filterBox,
    scroller,
    more,
  );
  apply();
  // the whole file is fetched once the card is drawn (the browser already holds it): sort and search see every row
  if (!full && attachmentFor(card)) setTimeout(() => ensureFull().then((ok) => ok && apply()), 250);
  if (typeof ResizeObserver !== "undefined")
    new ResizeObserver(() => paint(true)).observe(scroller);
  return wrap;
}

// ------------------------------------------------------------------ results of an analysis (chart + small table)

function resultTable(res, lang) {
  const w = L(lang);
  const cols = res.columns || [];
  const units = cols.map((c, j) =>
    j === 0
      ? ""
      : /\(%\)|%$/.test(c) || (res.kind === "compare" && j === 3)
        ? "%"
        : res.kind === "scatter"
          ? ""
          : res.unit || "",
  );
  return h(
    "div",
    { class: "dk-result-wrap" },
    h("table", { class: "dk-result" },
      h("thead", null, h("tr", null, cols.map((c, j) => h("th", { scope: "col", class: j ? "num" : "", text: c })))),
      h("tbody", null, (res.rows || []).slice(0, 8).map((r) => h("tr", null, r.map((v, j) => (j === 0
        ? h("th", { scope: "row", text: String(v ?? "") })
        : h("td", { class: "num", text: num(v) ? fmtValue(v, units[j], lang) : String(v ?? "—") }))))))), // prettier-ignore
    (res.rows || []).length > 8 || res.more
      ? h("p", {
          class: "dk-more",
          text: fill(w.more, { n: res.rows.length - 8 + (res.more || 0) }),
        })
      : null,
  );
}

/** « Modifier le graphique »: 2 or 3 edits computed by the harness for the chart just shown; a click sends the edit
 * as the next message, and the next turn shows the updated chart (its own version). */
function nextSteps(item, lang) {
  const w = L(lang);
  const steps = Array.isArray(item.next) ? item.next.slice(0, 3) : [];
  if (!steps.length) return null;
  return h("div", { class: "dk-next", role: "group", "aria-label": w.edit },
    h("span", { class: "dk-next-h" }, icon("edit"), h("span", { text: w.edit })),
    h("div", { class: "dk-next-list" }, steps.map((st) =>
      h("button", { type: "button", class: "dk-next-chip", onclick: () => askNext(st.ask || st.label) },
        h("span", { text: st.label }), icon("send"))))); // prettier-ignore
}

function askNext(text) {
  const ev = new CustomEvent("bird:send", { cancelable: true, detail: { text } });
  if (window.dispatchEvent(ev)) composerInsert(text, { replace: true }); // nobody sent it: the composer gets it
}

function analysisView(item, card, lang) {
  const chart = item.chart && renderChart2(item.chart, { lang, onDrill: (label) =>
    composerInsert(`${lang === "en" ? "Detail" : "Détaille"} « ${label} » (${item.label}, ${card.name}) : `, { replace: true }) }); // prettier-ignore
  return h(
    "div",
    { class: "dk-analysis" },
    chart,
    item.id === "answer" ? nextSteps(item, lang) : null,
    item.result &&
      item.result.kind !== "scalar" &&
      resultTable(item.result, lang),
  );
}

// ------------------------------------------------------------------ the card

export function renderDataCard(card) {
  if (!card || !Array.isArray(card.columns)) return null;
  const lang =
    state.prefs?.lang === "en" ? "en" : card.lang === "en" ? "en" : "fr";
  const w = L(lang);
  const meta = card.meta || {};
  const notes = [
    meta.separator && `${w.sep} « ${meta.separator} »`,
    meta.sheet && `${w.sheet} « ${meta.sheet} »`,
    meta.header_rows === 2 && w.header2,
    meta.total_row && w.totalRow,
    meta.skipped > 0 && fill(w.skipped, { n: meta.skipped }),
    meta.truncated && w.truncated,
  ].filter(Boolean);
  const complete = num(card.complete)
    ? Math.round(card.complete * 1000) / 10
    : null;
  const head = h("div", { class: "dk-head-row" },
    h("span", { class: "dk-badge", "aria-hidden": "true" }, typeGlyph("number")),
    h("div", { class: "dk-title" },
      h("p", { class: "card-name dk-name", text: card.name }),
      h("p", { class: "card-meta" },
        h("strong", { text: `${fmtValue(card.rows, "", lang)} ${w.rows} × ${card.cols} ${w.cols}` }),
        complete !== null && h("span", { class: `dk-complete${complete < 95 ? " is-low" : ""}`, text: `${fmtValue(complete, "%", lang)} ${w.complete}` }),
        notes.length ? h("span", { class: "dk-notes", text: notes.join(" · ") }) : null)),
    h("span", { class: "tag c2-tag-ok", text: w.read })); // prettier-ignore

  const chips = h("ul", { class: "dk-cols", "aria-label": w.cols },
    card.columns.map((c) => h("li", null, h("button", { type: "button", class: `dk-col is-${c.type}`, title: columnTitle(c, lang),
      "aria-label": `${fill(w.refCol, { name: c.name })} — ${w.types[c.type] || c.type}, ${columnStat(c, lang)}`,
      onclick: () => composerInsert(`${w.column} « ${c.name} »`) },
      h("span", { class: "dk-col-top" }, typeGlyph(c.type), h("span", { class: "dk-col-name", text: c.name }),
        c.missing ? h("span", { class: "dk-miss", text: `${c.missing} ${w.missing}` }) : null),
      h("span", { class: "dk-col-bottom" },
        c.hist ? miniBars(c.hist) : c.spark && c.spark.length > 1 ? miniLine(c.spark) : c.top ? miniTop(c.top, c.count) : null,
        h("span", { class: "dk-col-stat", text: columnStat(c, lang) })))))); // prettier-ignore

  if (card.compact && card.answer) return compactCard(card, lang, head);
  // suggested analyses: chips, one result shown at a time (the question's own result first)
  const items = [
    ...(card.answer
      ? [{ id: "answer", label: w.asked, icon: "spark", ...card.answer }]
      : []),
    ...(card.suggestions || []),
  ];
  const stage = h("div", { class: "dk-stage", "aria-live": "polite" });
  const views = new Map();
  let current = null;
  const select = (item, btn) => {
    current = item.id;
    for (const b of bar.querySelectorAll(".dk-chip")) {
      const on = b === btn;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    }
    if (!views.has(item.id)) views.set(item.id, analysisView(item, card, lang));
    stage.replaceChildren(views.get(item.id));
  };
  const bar = h(
    "div",
    { class: "dk-chips", role: "group", "aria-label": w.suggestions },
    items.map((item) => {
      const btn = h("button", { type: "button", class: `dk-chip${item.id === "answer" ? " is-asked" : ""}`, "aria-pressed": "false",
        onclick: () => (current === item.id ? (current = null, stage.replaceChildren(), btn.classList.remove("is-on"), btn.setAttribute("aria-pressed", "false")) : select(item, btn)) },
        item.id === "answer" ? icon("spark") : chipGlyph(item.icon), h("span", { text: item.label })); // prettier-ignore
      return btn;
    }),
  );
  const section = (title, ...kids) =>
    h(
      "section",
      { class: "dk-section" },
      h("h4", { class: "dk-h", text: title }),
      ...kids,
    );
  const el = h("article", { class: "card widget dk-card", "data-card": card.id, lang },
    h("div", { class: "dk-top" }, head, chips),
    items.length ? section(w.suggestions, bar, stage) : null,
    section(w.table, interactiveTable(card, lang)),
    h("p", { class: "dk-source" }, icon("shield"), fill(w.source, { name: card.name }))); // prettier-ignore

  // first one open at once, so the card never looks empty (also before the next frame, for tests and print)
  if (items.length) select(items[0], bar.querySelector(".dk-chip"));
  return el;
}

/** A follow-up that edited the chart: the new version first (continuity rule), the table folded; the earlier
 * versions stay in the conversation above. */
function compactCard(card, lang, head) {
  const w = L(lang);
  const item = { id: "answer", label: w.asked, ...card.answer };
  const n = Number(card.answer.version) || 2;
  const table = h("details", { class: "dk-fold" },
    h("summary", { class: "dk-fold-sum" }, icon("chevron"), h("span", { text: fill(w.tableOf, { n: fmtValue(card.rows, "", lang) }) })),
    h("div", { class: "dk-fold-body" }, interactiveTable(card, lang))); // prettier-ignore
  return h("article", { class: "card widget dk-card is-compact", "data-card": card.id, lang },
    h("div", { class: "dk-top" }, head),
    h("section", { class: "dk-section" },
      h("h4", { class: "dk-h" }, h("span", { text: w.asked }), h("span", { class: "dk-version", text: fill(w.version, { n }) })),
      h("div", { class: "dk-stage" }, analysisView(item, card, lang))),
    h("section", { class: "dk-section" }, table),
    h("p", { class: "dk-source" }, icon("shield"), fill(w.sourceAsked, { name: card.name }))); // prettier-ignore
}

function chipGlyph(kind) {
  const d = {
    line: "M3 14l4-5 4 3 6-7", bar: "M4 16V9M8 16V5M12 16V11M16 16V7", rank: "M4 5h9M4 9h12M4 13h6M4 17h3",
    donut: "M10 3a7 7 0 1 1-6.9 8.2M10 6.5a3.5 3.5 0 1 0 3.5 3.5", compare: "M4 16V8M7 16V5M12 16V10M15 16V6",
    scatter: "M5 14h.1M8 9h.1M11 12h.1M14 6h.1M15 10h.1", box: "M3 10h3M14 10h3M6 7h8v6H6zM10 7v6",
  }; // prettier-ignore
  return sv(
    "svg",
    {
      class: "icon",
      viewBox: "0 0 20 20",
      "aria-hidden": "true",
      focusable: "false",
    },
    sv("path", { d: d[kind] || d.bar }),
  );
}

/** Plain text of a data card (copy / export of the turn). */
export function dataCardText(card, lang = "fr") {
  const w = L(lang);
  const lines = [
    `${card.name} — ${card.rows} ${w.rows} × ${card.cols} ${w.cols}`,
  ];
  for (const c of card.columns || [])
    lines.push(
      `- ${c.name} (${w.types[c.type] || c.type}${c.unit ? `, ${c.unit}` : ""}) : ${columnStat(c, lang)}`,
    );
  return lines.join("\n");
}
