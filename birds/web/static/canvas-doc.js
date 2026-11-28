// Word-like documents in the canvas: A4 pages drawn in the document's template (birds/canvas/templates.py), the
// same plan as the .docx (birds/canvas/docx_out.py): a cover page (template name, title, subtitle, date, author),
// a table of contents with page numbers, numbered headings « 1. », « 1.1 », callouts by tone, tables with their
// header row, figures numbered with caption and credit, footnotes as numbered notes, a running header and « n / N »
// on every page. Or a letter. Text stays editable in place: the pages are laid out again after each change.
//
// Security: every model or user text reaches the page as text nodes (h(..., {text}) or the escaped Markdown of
// markdown.js); footnote calls are turned into <sup> elements built here, never parsed HTML.
import { h, state, t } from "./core.js";

// Same table as birds/canvas/templates.py (tests/test_canvas_docs.py checks the flags match).
export const TEMPLATES = {
  cadrage: { fr: "Note de cadrage", en: "Project brief", cover: true, toc: true, numbered: true, letter: false },
  "compte-rendu": { fr: "Compte rendu", en: "Meeting minutes", cover: false, toc: false, numbered: false, letter: false },
  rapport: { fr: "Rapport", en: "Report", cover: true, toc: true, numbered: true, letter: false },
  proposition: { fr: "Proposition commerciale", en: "Business proposal", cover: true, toc: true, numbered: true, letter: false },
  procedure: { fr: "Procédure", en: "Procedure", cover: false, toc: true, numbered: true, letter: false },
  lettre: { fr: "Lettre", en: "Letter", cover: false, toc: false, numbered: false, letter: true },
};
const DEFAULT = "rapport";
const lang = () => (state.prefs.lang === "en" ? "en" : "fr");
const FOOT = /\[\^([\w-]{1,8})\]/g;

/** The page look of a document (docx_out.look). */
export function look(doc) {
  const tpl = TEMPLATES[doc?.template] || TEMPLATES[DEFAULT];
  const n = (doc?.blocks || []).length;
  return {
    template: TEMPLATES[doc?.template] ? doc.template : DEFAULT,
    name: doc?.lang === "en" ? tpl.en : tpl.fr,
    cover: tpl.cover,
    toc: tpl.toc && n >= 3 && !tpl.letter,
    numbered: tpl.numbered,
    letter: tpl.letter,
  };
}

/** The footnotes as numbered on the page (dsl.footnote_order): by first call, then the ones never called. */
export function footnotes(doc) {
  const defs = new Map((doc?.footnotes || []).map((x) => [String(x.n), x.text || ""]));
  const order = [];
  const scan = (s) => {
    for (const m of String(s || "").matchAll(FOOT))
      if (defs.has(m[1]) && !order.includes(m[1])) order.push(m[1]);
  };
  for (const b of doc?.blocks || [])
    for (const p of b.parts || []) {
      scan(p.text);
      for (const i of p.items || []) if (typeof i === "string") scan(i);
      for (const r of p.rows || []) for (const c of r) if (typeof c === "string") scan(c);
    }
  for (const k of defs.keys()) if (!order.includes(k)) order.push(k);
  return order.map((key, i) => ({ key, n: i + 1, text: defs.get(key) }));
}

/** Heading numbers and figure numbers, as docx_out.outline gives them: {heads: {bid: "2."}, subs: Map, figs: Map}. */
export function numbering(doc) {
  const lk = look(doc);
  const heads = {};
  const subs = new Map();
  const figs = new Map();
  let fig = 0;
  (doc?.blocks || []).forEach((b, i) => {
    heads[b.id] = lk.numbered && !lk.letter ? `${i + 1}.` : "";
    let sub = 0;
    for (const p of b.parts || []) {
      if (p.t === "heading" && (p.level || 2) <= 2) {
        sub += 1;
        if (lk.numbered && !lk.letter) subs.set(p, `${i + 1}.${sub}`);
      } else if ((p.t === "image" && p.media) || p.t === "chart") figs.set(p, ++fig);
    }
  });
  return { heads, subs, figs };
}

/** Text with its footnote calls as superscript numbers (text nodes and <sup>, nothing parsed). */
export function withMarks(text, marks) {
  const out = [];
  let pos = 0;
  const s = String(text || "");
  for (const m of s.matchAll(FOOT)) {
    if (m.index > pos) out.push(s.slice(pos, m.index));
    const n = marks.get(m[1]);
    if (n) out.push(h("sup", { class: "cv-fn", text: String(n) }));
    pos = m.index + m[0].length;
  }
  if (pos < s.length) out.push(s.slice(pos));
  return out;
}

/** Footnote calls inside rendered Markdown: walk its text nodes and split them around « [^x] ». */
export function markTextNodes(root, marks) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const hits = [];
  while (walker.nextNode()) if (/\[\^[\w-]{1,8}\]/.test(walker.currentNode.nodeValue)) hits.push(walker.currentNode);
  for (const node of hits) node.replaceWith(...withMarks(node.nodeValue, marks));
}

const dateText = (doc) =>
  doc.date ||
  new Date().toLocaleDateString(lang() === "en" ? "en-GB" : "fr-FR", { day: "numeric", month: "long", year: "numeric" });

/**
 * The document view: pages of paper. ``api`` gives the canvas's own pieces (editable text, the section tools, the
 * picture, chart and table views, the variants chooser) so this file only lays out.
 */
export function docView(a, doc, api) {
  const lk = look(doc);
  const num = numbering(doc);
  const notes = footnotes(doc);
  const marks = new Map(notes.map((x) => [x.key, x.n]));
  const flow = []; // the elements of the body, in order: laid out on pages by paginate()
  const tocRows = [];
  if (lk.letter) flow.push(...letterHead(doc, api));
  doc.blocks.forEach((b, i) => {
    const pending = api.pendingFor(a, b.id);
    const head = h(
      "div",
      { class: "cv-sec-head", "data-bid": b.id, "data-keep": "1" },
      api.sectionTools(a, doc, b, i),
      !lk.letter &&
        h(
          "h3",
          { class: "cv-h1", id: `cv-h-${b.id}` },
          num.heads[b.id] && h("span", { class: "cv-num", text: num.heads[b.id] }),
          api.editable("span", "cv-h1-text", b.title, `${b.id}:title`, { label: t("cv.edit.title") }),
        ),
    );
    flow.push(head);
    if (!lk.letter) tocRows.push({ level: 1, num: num.heads[b.id], text: b.title, anchor: `cv-h-${b.id}` });
    if (pending) {
      flow.push(api.variantsBox(a, doc, b, pending));
      return;
    }
    b.parts.forEach((p, k) => {
      const el = part(doc, b, p, k, { api, num, marks, lk });
      if (!el) return;
      if (p.t === "heading" && (p.level || 2) <= 2 && !lk.letter)
        tocRows.push({ level: 2, num: num.subs.get(p) || "", text: p.text, anchor: el.id });
      flow.push(el);
    });
  });
  if (notes.length)
    flow.push(
      h("h4", { class: "cv-h2 cv-notes-title", "data-keep": "1", text: t("cv.doc.notes") }),
      h(
        "ol",
        { class: "cv-notes" },
        notes.map((x) => h("li", { value: String(x.n) }, h("sup", { class: "cv-fn", text: String(x.n) }), " ", x.text)),
      ),
    );
  const front = [];
  if (lk.cover) front.push(coverPage(doc, lk, api));
  const head = !lk.cover && !lk.letter ? compactHead(doc, lk, api) : null;
  const toc = lk.toc ? tocBox(tocRows) : null;
  const root = h("div", {
    class: `cv-doc cv-tpl-${lk.template}${lk.letter ? " is-letter" : ""}`,
    "data-template": lk.template,
  });
  root._layout = { front, head, toc, flow, cover: lk.cover, letter: lk.letter, title: doc.title || "" };
  paginate(root);
  return root;
}

function part(doc, b, p, k, { api, num, marks, lk }) {
  const path = `${b.id}:p${k}`;
  if (p.t === "text") {
    const el = api.mdBlock(p.text, `${path}:text`);
    markTextNodes(el, marks);
    return el;
  }
  if (p.t === "heading") {
    const level = (p.level || 2) <= 2 ? 2 : 3;
    const n = level === 2 ? num.subs.get(p) : "";
    return h(
      level === 2 ? "h4" : "h5",
      { class: `cv-h${level}`, id: `cv-h-${b.id}-${k}`, "data-keep": "1" },
      n && h("span", { class: "cv-num", text: n }),
      api.editable("span", "", p.text, `${path}:text`),
    );
  }
  if (p.t === "callout") {
    const tone = p.tone === "ok" ? "key" : p.tone || "info";
    return h(
      "aside",
      { class: `cv-callout cv-tone-${tone}`, role: "note", "aria-label": t(`cv.doc.tone.${tone}`) },
      h("span", { class: "cv-callout-label", text: t(`cv.doc.tone.${tone}`) }),
      api.editable("p", "", p.text, `${path}:text`, { multiline: true }),
    );
  }
  if (p.t === "list") {
    const el = api.textParts(b, [p])[0];
    markTextNodes(el, marks);
    return el;
  }
  if (p.t === "table") {
    const el = api.tableOf(b, p, k);
    markTextNodes(el, marks);
    return el;
  }
  if (p.t === "image") {
    const n = num.figs.get(p);
    const m = api.mediaMeta(doc, p.media);
    const fig = api.picture(doc, b, p, { cls: "cv-figure" });
    if (n) fig.append(caption(n, p.caption || (m?.kind === "web" ? m?.alt : "") || "", m));
    return fig;
  }
  if (p.t === "chart") {
    const n = num.figs.get(p);
    return h(
      "figure",
      { class: "cv-figure cv-figure-chart" },
      api.chartBox(p, doc.theme),
      caption(n, p.title || b.title || "", p.source ? { credit: p.source } : null),
    );
  }
  return api.docPart(doc, b, p, k);
}

function caption(n, text, meta) {
  const credit = [meta?.credit, meta?.licence].filter(Boolean).join(" · ");
  return h(
    "figcaption",
    { class: "cv-caption" },
    h("strong", { text: `${t("cv.doc.figure")} ${n}` }),
    text ? ` – ${text}` : "",
    credit
      ? h(
          "span",
          { class: "cv-caption-src" },
          ` · ${t("cv.source")} : ${credit}`,
          meta?.source && /^https:\/\//.test(meta.source)
            ? [" — ", h("a", { href: meta.source, target: "_blank", rel: "noopener noreferrer", text: t("cv.doc.see") })]
            : null,
        )
      : null,
  );
}

function coverPage(doc, lk, api) {
  return h(
    "section",
    { class: "cv-a4 cv-a4-cover", "aria-label": t("cv.cover") },
    h(
      "div",
      { class: "cv-cover-in" },
      h("p", { class: "cv-kicker", text: lk.name }),
      api.editable("h3", "cv-doc-title", doc.title, "title", { label: t("cv.edit.title") }),
      api.editable("p", `cv-doc-sub${doc.subtitle ? "" : " cv-faint"}`, doc.subtitle || "", "subtitle"),
      h("p", { class: "cv-doc-meta", text: [dateText(doc), doc.author].filter(Boolean).join(" · ") }),
    ),
    h("div", { class: "cv-a4-foot", text: "1" }),
  );
}

function compactHead(doc, lk, api) {
  return h(
    "header",
    { class: "cv-doc-head" },
    h("p", { class: "cv-kicker", text: lk.name }),
    api.editable("h3", "cv-doc-title", doc.title, "title", { label: t("cv.edit.title") }),
    doc.subtitle ? api.editable("p", "cv-doc-sub", doc.subtitle, "subtitle") : null,
    h("p", { class: "cv-doc-meta", text: [dateText(doc), doc.author].filter(Boolean).join(" · ") }),
  );
}

function letterHead(doc, api) {
  const en = lang() === "en";
  return [
    h(
      "div",
      { class: "cv-letter-top", "data-keep": "1" },
      h("p", { class: "cv-letter-from", text: doc.author || "" }),
      h("p", { class: "cv-letter-date", text: `${en ? "" : "Le "}${dateText(doc)}` }),
    ),
    doc.recipient
      ? h(
          "p",
          { class: "cv-letter-to" },
          String(doc.recipient)
            .split(/\s*[\n,;]\s*/)
            .slice(0, 5)
            .flatMap((x, i) => (i ? [h("br"), x] : [x])),
        )
      : null,
    h(
      "p",
      { class: "cv-letter-obj" },
      h("strong", { text: `${t("cv.doc.object")} ` }),
      api.editable("strong", "cv-doc-title", doc.title, "title", { label: t("cv.edit.title") }),
    ),
  ].filter(Boolean);
}

function tocBox(rows) {
  return h(
    "nav",
    { class: "cv-toc", "aria-label": t("cv.doc.toc") },
    h("p", { class: "cv-toc-title", text: t("cv.doc.toc") }),
    h(
      "ol",
      null,
      rows.map((r) =>
        h(
          "li",
          { class: `cv-toc-${r.level}` },
          h(
            "a",
            {
              href: `#${r.anchor}`,
              "data-anchor": r.anchor,
              onclick: (e) => {
                e.preventDefault();
                document.getElementById(r.anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
              },
            },
            r.num ? h("span", { class: "cv-num", text: r.num }) : null,
            h("span", { class: "cv-toc-text", text: r.text || "" }),
            h("span", { class: "cv-toc-page", text: "" }),
          ),
        ),
      ),
    ),
  );
}

// ------------------------------------------------------------------ pages

const NARROW = 520; // below this width the document reads as one continuous sheet (a phone)

/**
 * Lay the body out on A4 pages (aspect 210 x 297, margins and type in container units, like a page at zoom): fill a
 * page, move on when the next element does not fit, never leave a heading alone at the bottom. Again on resize.
 */
export function paginate(root) {
  const L = root._layout;
  if (!L) return;
  const pages = [...L.front];
  const width = root.clientWidth || root.parentElement?.clientWidth || 0;
  const narrow = width > 0 && width < NARROW;
  root.classList.toggle("is-narrow", narrow);
  const start = pages.length + 1;
  const body = [L.head, L.toc, ...L.flow].filter(Boolean);
  const page = (n) =>
    h(
      "section",
      { class: "cv-a4", "aria-label": t("cv.doc.page", { n }) },
      n > 1 && !L.letter ? h("div", { class: "cv-a4-head", text: L.title }) : null,
      h("div", { class: "cv-a4-body" }),
      h("div", { class: "cv-a4-foot" }),
    );
  root.replaceChildren(...pages);
  if (!root.isConnected || narrow || !width) {
    const one = page(start);
    one.querySelector(".cv-a4-body").append(...body);
    root.append(one);
    finish(root);
    return;
  }
  // a first page to measure in: every element at its final width
  let cur = page(start);
  root.append(cur);
  let box = cur.querySelector(".cv-a4-body");
  const limit = box.clientHeight;
  let n = start;
  const breakAfter = L.cover && L.toc ? L.toc : null; // after a cover page the contents have a page of their own
  for (let i = 0; i < body.length; i++) {
    const el = body[i];
    if (i > 0 && body[i - 1] === breakAfter) {
      n += 1;
      cur = page(n);
      root.append(cur);
      box = cur.querySelector(".cv-a4-body");
    }
    box.append(el);
    if (box.scrollHeight <= limit + 1 || box.children.length === 1) continue;
    // over the page: this element (and the heading right before it) starts the next page
    const moved = [el];
    const prev = el.previousElementSibling;
    if (prev?.dataset.keep && box.children.length > 2) moved.unshift(prev);
    n += 1;
    cur = page(n);
    root.append(cur);
    box = cur.querySelector(".cv-a4-body");
    box.append(...moved);
  }
  finish(root);
}

function finish(root) {
  const all = [...root.querySelectorAll(".cv-a4")];
  all.forEach((p, i) => {
    const f = p.querySelector(".cv-a4-foot");
    if (f) f.textContent = `${i + 1} / ${all.length}`;
  });
  // the table of contents gets the page of each heading, like Word's « Update field »
  for (const a of root.querySelectorAll(".cv-toc a[data-anchor]")) {
    const target = root.querySelector(`#${CSS.escape(a.dataset.anchor)}`);
    const pg = target?.closest(".cv-a4");
    a.querySelector(".cv-toc-page").textContent = pg && !root.classList.contains("is-narrow") ? String(all.indexOf(pg) + 1) : "";
  }
}

/** Watch the width: a new layout when the panel is resized (debounced). */
export function watch(root) {
  if (!("ResizeObserver" in window) || root._ro) return;
  let w = root.clientWidth;
  let timer = null;
  root._ro = new ResizeObserver(() => {
    const now = root.clientWidth;
    if (Math.abs(now - w) < 2) return;
    w = now;
    clearTimeout(timer);
    timer = setTimeout(() => paginate(root), 120);
  });
  root._ro.observe(root);
}

// ------------------------------------------------------------------ the card in the chat

/** A small first page for the chat card: the template name, the title, the subtitle, a few grey lines. */
export function thumb(doc) {
  const lk = look(doc);
  return h(
    "div",
    { class: `cv-thumb cvt-${doc.theme || "corporate"}${lk.letter ? " is-letter" : ""}`, "aria-hidden": "true" },
    h("span", { class: "cv-thumb-kicker", text: lk.name }),
    h("span", { class: "cv-thumb-title", text: doc.title || "" }),
    doc.subtitle && !lk.letter ? h("span", { class: "cv-thumb-sub", text: doc.subtitle }) : null,
    h("span", { class: "cv-thumb-lines" }, h("i"), h("i"), h("i")),
  );
}
