// The slide layouts of a canvas deck: the browser's copy of birds/canvas/layouts.py. The preview and the exported
// .pptx draw the SAME layout: both implementations run the cases of tests/fixtures/canvas_layouts.json
// (tests/js/canvas-layouts.test.mjs and tests/test_canvas_decks.py). Pure functions, no DOM.

export const CATALOGUE = {
  section: ["Intercalaire", "Section divider"],
  agenda: ["Sommaire", "Agenda"],
  statement: ["Message clé", "Statement"],
  bullets: ["Points", "Bullets"],
  columns: ["Deux colonnes", "Two columns"],
  figure: ["Chiffre clé", "Key figure"],
  kpis: ["Chiffres clés", "Key figures"],
  versus: ["Face à face", "Versus"],
  compare: ["Comparaison", "Comparison"],
  timeline: ["Frise", "Timeline"],
  steps: ["Étapes", "Process"],
  quote: ["Citation", "Quote"],
  "image-left": ["Image à gauche", "Image left"],
  "image-right": ["Image à droite", "Image right"],
  "image-full": ["Plein cadre", "Full bleed"],
  "image-grid": ["Galerie", "Image grid"],
  chart: ["Graphique", "Chart"],
  table: ["Tableau", "Table"],
  cards: ["Cartes", "Cards"],
  closing: ["Clôture", "Closing"],
  code: ["Code", "Code"],
};
export const NAMES = Object.keys(CATALOGUE);

const MAIN = ["chart", "table", "compare", "steps", "cards", "timeline", "kpi", "quote", "code"];
const TEXT = ["list", "text", "callout", "heading"];
// \b is ASCII-only in JS: the word ends are written out (same words as layouts.py)
const AGENDA =
  /^\s*(?:sommaire|agenda|programme|au menu|plan de la pr[ée]sentation|ordre du jour|outline|contents|table des mati[èe]res)(?![\p{L}\p{N}_])/iu;
const CLOSING =
  /^\s*(?:merci|thank|questions?(?![\p{L}\p{N}_])|conclusion|en conclusion|pour conclure|contact|et maintenant|à vous|a vous|next steps|prochaines? [ée]tapes|passons [àa] l'action|call to action|rejoignez|let's|lan[çc]ons)/iu;
const CARD = /^(?<title>[^:|—–]{1,80}?)\s*(?::|\||—|–|\s-\s)\s*(?<text>.+)$/su;

const partsOf = (b, ts) => (b.parts || []).filter((p) => ts.includes(p.t));

export function mainPart(b) {
  for (const t of MAIN) {
    const p = (b.parts || []).find((x) => x.t === t);
    if (p) return p;
  }
  return null;
}

export function groups(b) {
  const out = [];
  for (const p of b.parts || []) {
    if (p.t === "heading") out.push({ title: p.text || "", items: [] });
    else if (p.t === "list" && out.length && !out.at(-1).items.length)
      out.at(-1).items = (p.items || [])
        .filter((x) => x.trim())
        .map((x) => x.trim())
        .slice(0, 6);
    else if (TEXT.includes(p.t) && out.length) return [];
  }
  return out.length >= 2 && out.length <= 3 && out.every((g) => g.items.length) ? out : [];
}

export function columnsOf(b) {
  const p = partsOf(b, ["compare"])[0];
  return p ? p.columns || [] : groups(b);
}

export function itemsOf(b) {
  const p = partsOf(b, ["steps", "cards"])[0];
  if (p) return p.items || [];
  const tl = partsOf(b, ["timeline"])[0];
  if (tl) return (tl.items || []).map((x) => ({ title: x.when || "", text: x.what || "" }));
  const out = [];
  for (const l of partsOf(b, ["list"]))
    for (const it of l.items || []) {
      if (!it.trim() || it.startsWith("  ")) continue;
      const m = CARD.exec(it.trim());
      out.push(m ? { title: m.groups.title, text: m.groups.text } : { title: it.trim(), text: "" });
    }
  return out.slice(0, 8);
}

const listItems = (b) => partsOf(b, ["list"]).flatMap((p) => (p.items || []).filter((x) => x.trim()));
// Python's len() counts code points: so do we
const plen = (s) => [...String(s)].length;

function shortText(b, limit) {
  const text = partsOf(b, TEXT);
  if (text.length !== 1) return false;
  const p = text[0];
  const s = p.t !== "list" ? p.text : (p.items || []).length === 1 ? p.items.join(" ") : null;
  return !!s && plen(s) <= limit;
}

export function fits(b, name) {
  const main = mainPart(b);
  const imgs = partsOf(b, ["image"]);
  const text = partsOf(b, TEXT);
  const mt = main ? main.t : null;
  switch (name) {
    case "section":
    case "closing":
      return mt === null && text.length <= 2 && imgs.length <= 1;
    case "statement":
      return mt === null && shortText(b, 220) && imgs.length <= 1;
    case "agenda":
      return mt === null && listItems(b).length >= 2 && !imgs.length;
    case "bullets":
    case "columns":
      return mt === null && !!text.length && !imgs.length;
    case "figure":
      return mt === "kpi" && imgs.length <= 1;
    case "kpis":
      return mt === "kpi" && (main.items || []).length >= 2 && !imgs.length;
    case "versus":
    case "compare": {
      const cols = columnsOf(b);
      return (
        (mt === null || mt === "compare") &&
        cols.length >= 2 &&
        cols.length <= (name === "versus" ? 2 : 3) &&
        !imgs.length
      );
    }
    case "steps": {
      const n = itemsOf(b).length;
      return ["steps", "timeline", null].includes(mt) && n >= 2 && n <= 6 && !imgs.length;
    }
    case "cards": {
      const n = itemsOf(b).length;
      return ["cards", "steps", null].includes(mt) && n >= 2 && n <= 6 && !imgs.length;
    }
    case "timeline":
      return mt === "timeline" && !imgs.length;
    case "quote":
      return mt === "quote" && imgs.length <= 1;
    case "image-left":
    case "image-right":
      return mt === null && imgs.length === 1;
    case "image-full":
      return mt === null && imgs.length === 1 && (!text.length || shortText(b, 160));
    case "image-grid":
      return mt === null && imgs.length >= 2 && imgs.length <= 4;
    case "chart":
    case "table":
    case "code":
      return mt === name && !imgs.length;
  }
  return false;
}

export function pick(b, index, total) {
  const hint = b.layout;
  if (hint && CATALOGUE[hint] && fits(b, hint)) return hint;
  const main = mainPart(b);
  const imgs = partsOf(b, ["image"]);
  const title = b.title || "";
  const last = total > 1 && index === total - 1;
  if (main) {
    const t = main.t;
    if (t === "kpi") return (main.items || []).length === 1 || imgs.length ? "figure" : "kpis";
    if (t === "compare") {
      const cols = main.columns || [];
      return cols.length === 2 && cols.every((c) => (c.items || []).length <= 4) ? "versus" : "compare";
    }
    if (t === "steps" || t === "cards" || t === "timeline") return t;
    return t;
  }
  const text = partsOf(b, TEXT);
  if (imgs.length >= 2) return "image-grid";
  if (imgs.length === 1) {
    if (!text.length || shortText(b, 160)) return "image-full";
    return index % 2 === 0 ? "image-right" : "image-left";
  }
  if (!text.length) return last ? "closing" : "section";
  if (last && CLOSING.test(title) && listItems(b).length <= 4) return "closing";
  if (AGENDA.test(title) && fits(b, "agenda")) return "agenda";
  const g = groups(b);
  if (g.length) return g.length === 2 ? "versus" : "compare";
  if (shortText(b, 180)) return "statement";
  const items = listItems(b);
  if (items.length > 6 && items.every((x) => plen(x) <= 90)) return "columns";
  return "bullets";
}

export const compatible = (b) => NAMES.filter((n) => fits(b, n));

/** The deck's size line key (« 3 diapositives · 1 mise en page »): singular forms where the count is one. */
export function sizeKey(n, layouts) {
  return n === 1 ? "cv.card.slides.s1" : layouts === 1 ? "cv.card.slides.l1" : "cv.card.slides";
}
