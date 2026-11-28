// The canvas: the deck, document, code or sheet Bird builds, beside the chat (desktop) or as a full-screen sheet
// (phone). The model never draws a layout: the server sends a document model (birds/canvas/dsl.py) and this file
// draws it into pre-designed themes. Every change (a turn, an inline edit, a reorder, a theme) is a new version.
//
// Security: model and user text only ever reaches the page as text nodes (textContent), or through the chat's
// Markdown renderer (markdown.js, escaped). Code runs only in the sandboxed /canvas/frame (no network, opaque
// origin). Pictures are blob: URLs made from bytes the server re-encoded.
import {
  announce,
  b64ToBytes,
  button,
  copyText,
  download,
  h,
  icon,
  state,
  t,
  toast,
} from "./core.js";
import { STRINGS } from "./i18n.js";
import { CANVAS_STRINGS } from "./canvas-i18n.js";
import { renderMarkdown } from "./markdown.js";
import { chartSvg } from "./previews.js";
import { renderChart } from "./chart.js";
import { flowSvg, parseFlow } from "./canvas-flow.js";
import * as sheet from "./canvas-sheet.js";
import {
  CATALOGUE,
  columnsOf,
  compatible,
  itemsOf,
  mainPart,
  pick as pickLayout,
} from "./canvas-layouts.js";

Object.assign(STRINGS.fr, CANVAS_STRINGS.fr);
Object.assign(STRINGS.en, CANVAS_STRINGS.en);

const MAX_VERSIONS = 24;
const KEEP_MEDIA_B64 = 90_000; // pictures larger than this are kept in memory only (localStorage is small)
const THEMES = ["corporate", "modern", "warm"]; // documents
const DECK_THEMES = ["corporate", "forest", "warm", "night"]; // decks: the four of deck_pptx.py
const PALETTES = {
  corporate: ["1E5BD8", "0B1B3F", "7FA4EE", "5BD69B", "B7C6E8", "586078"],
  modern: ["0D9488", "6366F1", "111827", "5EEAD4", "A5B4FC", "64748B"],
  warm: ["C2410C", "3B1F14", "E8A26B", "9A6B4F", "F2C9A0", "7C6A5E"],
  forest: ["2E7D52", "12301F", "8FC484", "C9A227", "B9D8B0", "5C6B61"],
  night: ["5B8DEF", "A78BFA", "5BD69B", "F2B25C", "7FA4EE", "9AA4BC"],
};

let handlers = {
  send: () => {},
  headers: () => ({}),
  save: () => {},
  busy: () => false,
  mode: () => "demo",
};
let conv = null; // the conversation shown
let panel = null; // the <aside> element
let view = {
  aid: null,
  tab: null,
  sel: null,
  chart: null,
  console: [],
  frameHtml: "",
  codeDraft: null,
};
let target = null; // « Demander à Bird » on one block: sent with the next message only
const media = new Map(); // media id -> { entry, url }
let returnFocus = null;

export function setup(h_) {
  handlers = { ...handlers, ...h_ };
  window.addEventListener("message", onFrameMessage);
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || !panel || panel.hidden)
      return;
    const el = document.activeElement;
    const inside = panel.contains(el);
    if (!inside && !isModal()) return; // on a laptop, Escape in the composer is the chat's (stop an answer)
    if (inside && (el?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el?.tagName || "")))
      return; // something is being edited: its own Escape (cancel, leave the field) comes first
    if (panel.querySelector(".cv-pop:not([hidden])")) return closePops();
    close();
  });
  narrowMq()?.addEventListener?.("change", () => setModal(isOpen() && isModal()));
}

// On phones and tablets the panel is a full-screen sheet over the chat: a modal. What is behind it is inert (no
// focus, no screen-reader reach), focus moves into it, and Escape closes it wherever focus is.
const narrowMq = () => window.matchMedia?.("(max-width: 1000px)");
const isModal = () => !!narrowMq()?.matches;
let modalOn = false;

function setModal(on) {
  if (on === modalOn) return;
  modalOn = on;
  for (const el of document.querySelectorAll(".app > :not(#canvas), body > .skip")) {
    if (on) {
      el.dataset.cvInert = el.inert ? "1" : "0"; // the drawer may already have made it inert (app.js)
      el.inert = true;
    } else if (el.dataset.cvInert !== undefined) {
      el.inert = el.dataset.cvInert === "1";
      delete el.dataset.cvInert;
    }
  }
}

// ------------------------------------------------------------------ store (on the conversation)

function store(c = conv) {
  if (!c) return { list: {}, active: null };
  if (!c.canvas || typeof c.canvas !== "object")
    c.canvas = { list: {}, active: null };
  c.canvas.list ||= {};
  return c.canvas;
}
const art = (aid, c = conv) => store(c).list[aid] || null;
const current = (a) => (a ? a.draft || a.versions[a.cur]?.doc || null : null);

function keepMedia(c, entries) {
  c.canvasMedia ||= {};
  for (const m of entries || []) {
    if (!m || typeof m.id !== "string") continue;
    const old = media.get(m.id);
    if (old?.url) URL.revokeObjectURL(old.url);
    media.set(m.id, { entry: m, url: null });
    c.canvasMedia[m.id] =
      m.data && m.data.length <= KEEP_MEDIA_B64 ? m : { ...m, data: null };
  }
}

function mediaUrl(id) {
  let m = media.get(id);
  if (!m && conv?.canvasMedia?.[id]?.data) {
    m = { entry: conv.canvasMedia[id], url: null };
    media.set(id, m);
  }
  if (!m?.entry?.data) return null;
  if (!m.url) {
    const type = m.entry.fmt === "png" ? "image/png" : "image/jpeg";
    m.url = URL.createObjectURL(new Blob([b64ToBytes(m.entry.data)], { type }));
  }
  return m.url;
}
const mediaMeta = (doc, id) =>
  doc?.media?.[id] || media.get(id)?.entry || conv?.canvasMedia?.[id] || null;

function pushVersion(a, doc, label) {
  a.versions.push({
    n: (a.versions.at(-1)?.n || 0) + 1,
    doc,
    label: String(label || "").slice(0, 80),
    at: Date.now(),
  });
  if (a.versions.length > MAX_VERSIONS)
    a.versions.splice(1, a.versions.length - MAX_VERSIONS); // v1 is kept
  a.cur = a.versions.length - 1;
  a.draft = null;
  a.fresh = true; // the next message carries it even if the panel is closed (« plus court » right after)
}

const clone = (x) => JSON.parse(JSON.stringify(x));

/** A local edit (inline text, reorder, theme…): a new version, the conversation saved, the panel redrawn. */
function commit(mutate, label) {
  const a = art(view.aid);
  if (!a) return;
  const doc = clone(current(a));
  if (mutate(doc) === false) return;
  pushVersion(a, doc, label);
  handlers.save(conv);
  render();
  announce(t("cv.live.version", { n: a.versions.at(-1).n }));
}

// ------------------------------------------------------------------ events from the chat stream

export function setConversation(c) {
  conv = c;
  closePops();
  const s = store(c);
  if (!panel || panel.hidden) return;
  if (!s.active || !s.list[s.active]) close(false);
  else open(s.active, { focus: false });
}

/** ``canvas`` and ``canvas_media`` events. Returns true when the turn's card should be redrawn. */
export function onEvent(c, turn, ev) {
  if (ev.type === "canvas_media") {
    keepMedia(c, ev.media);
    const a = art(ev.aid, c);
    if (a && c === conv && view.aid === ev.aid) render();
    return false;
  }
  if (ev.type !== "canvas" || typeof ev.aid !== "string") return false;
  const s = store(c);
  let a = s.list[ev.aid];
  if (!a) {
    if (!ev.doc) return false;
    a = s.list[ev.aid] = {
      aid: ev.aid,
      kind: ev.kind || ev.doc.kind,
      versions: [],
      cur: 0,
      draft: null,
    };
  }
  if (ev.phase === "reopen") {
    // an edit asked while the panel was closed: it opens again, and the next message carries the document
    if (c === conv && a.versions.length) {
      s.active = ev.aid;
      open(ev.aid, { focus: false });
    }
    return false;
  }
  turn.canvasLive = { aid: ev.aid, phase: ev.phase };
  if (ev.phase === "abort") {
    a.draft = null;
    if (!a.versions.length) delete s.list[ev.aid];
  } else if (ev.phase === "stream" && ev.doc) {
    a.draft = ev.doc;
  } else if (ev.phase === "final" && ev.doc) {
    pushVersion(
      a,
      ev.doc,
      ev.label || (ev.base ? t("cv.edited") : t("cv.label.created")),
    );
    turn.canvasLive = {
      aid: ev.aid,
      phase: "final",
      version: a.versions.at(-1).n,
    };
  }
  if (c !== conv) return true;
  if (ev.open !== false && ev.phase !== "abort") {
    s.active = ev.aid;
    if (!panel || panel.hidden || view.aid !== ev.aid)
      open(ev.aid, { focus: false, quiet: ev.phase === "stream" });
    else render();
  } else if (view.aid === ev.aid) render();
  return true;
}

/** The answer's ``canvas`` field: a document a trained file tool made arrives here (not streamed). */
export function onAnswer(c, turn, ref) {
  if (!ref || typeof ref.aid !== "string") return;
  turn.canvasLive = null;
  if (ref.doc) {
    const s = store(c);
    if (!s.list[ref.aid]) {
      s.list[ref.aid] = {
        aid: ref.aid,
        kind: ref.kind || ref.doc.kind,
        versions: [],
        cur: 0,
        draft: null,
      };
      pushVersion(s.list[ref.aid], ref.doc, t("cv.label.created"));
    }
  }
}

/**
 * What the next message carries. The artifact shown in the panel, whole (and a target block); after the panel is
 * closed, the whole document only for the one turn after it was made or changed, then just a reference
 * ({aid, version, kind}): an ordinary message never carries a 400 kB deck, and never becomes an edit of it.
 */
export function payload(c) {
  const s = store(c);
  const shown = !!panel && !panel.hidden && c === conv && view.aid;
  const aid = shown || s.active;
  const a = aid && s.list[aid];
  const tgt = target;
  target = null;
  if (!a || !a.versions.length) return {};
  const v = a.versions[a.cur];
  const fresh = !!a.fresh;
  a.fresh = false;
  if (!shown && !fresh)
    return {
      canvas: { aid: a.aid, version: v.n, kind: a.kind, open: false },
    };
  const out = { aid: a.aid, version: v.n, doc: clone(v.doc), open: !!shown };
  if (fresh) out.fresh = true;
  if (shown && tgt && tgt.aid === a.aid) out.target = tgt.block;
  return { canvas: out };
}

// ------------------------------------------------------------------ the chat card

export function canvasCard(turn) {
  const ref = turn.answer?.canvas || turn.canvasLive;
  if (!ref?.aid) return null;
  const a = art(ref.aid);
  if (!a) return null;
  const v = ref.version ? a.versions.find((x) => x.n === ref.version) : null;
  const doc = v?.doc || current(a);
  if (!doc) return null;
  const writing =
    turn.status === "running" && turn.canvasLive?.phase === "stream";
  const kind = doc.kind || a.kind;
  const thumb = kind === "deck" ? deckThumb(doc) : null;
  return h(
    "div",
    { class: `cv-card cv-card-${kind}${thumb ? " has-thumb" : ""}` },
    thumb ||
    h(
      "span",
      { class: "cv-card-icon" },
      icon(
        kind === "deck"
          ? "make_slides"
          : kind === "sheet"
            ? "make_sheet"
            : kind === "code"
              ? "spark"
              : "make_document",
      ),
    ),
    h(
      "span",
      { class: "cv-card-text" },
      h("strong", { text: doc.title || t(`cv.kind.${kind}`) }),
      h("span", {
        class: "cv-card-meta",
        text: [
          t(`cv.kind.${kind}`),
          writing
            ? t("cv.card.writing")
            : v
              ? t("cv.card.version", { n: v.n })
              : "",
          sizeText(doc),
        ]
          .filter(Boolean)
          .join(" · "),
      }),
    ),
    button(
      "btn-outline btn-small cv-card-open",
      "expand",
      turn.answer?.canvas?.doc ? t("cv.open.canvas") : t("cv.open"),
      () => {
        if (v) a.cur = a.versions.indexOf(v);
        store().active = a.aid;
        open(a.aid, { focus: true });
      },
      { "data-act": `cv-open-${a.aid}` },
    ),
  );
}

/** The deck's cover, small: the chat card shows what was made, not an icon. */
function deckThumb(doc) {
  const cv = doc.cover || {};
  const url = cv.media && !cv.off ? mediaUrl(cv.media) : null;
  return h(
    "span",
    { class: `cv-thumb cvt-${doc.theme || "corporate"}${url ? " has-img" : ""}`, "aria-hidden": "true" },
    url ? h("img", { src: url, alt: "", decoding: "async" }) : h("span", { class: "cv-disc cv-disc-1" }),
    h("span", { class: "cv-thumb-veil" }),
    h("span", { class: "cv-thumb-bar" }),
    h("span", { class: "cv-thumb-title", text: doc.title || "" }),
  );
}

/** The 2-3 next steps of a deck the chat just showed (followups.js): concrete, from what the deck lacks. */
export function canvasSuggestions(ref) {
  if (!ref?.aid) return [];
  const a = art(ref.aid);
  const v = a && (ref.version ? a.versions.find((x) => x.n === ref.version) : a.versions.at(-1));
  const doc = v?.doc;
  if (!doc || doc.kind !== "deck") return [];
  const out = [];
  const add = (k, vars = {}) => out.push({ label: t(k, vars), prompt: t(`${k}.p`, vars), kind: "follow" });
  const parts = (doc.blocks || []).flatMap((b) => b.parts || []);
  if (!parts.some((p) => p.t === "image")) add("cv.chip.images");
  if (!parts.some((p) => p.t === "kpi" || p.t === "chart")) add("cv.chip.figures");
  const n = (doc.blocks || []).length;
  const last = doc.blocks?.[n - 1];
  if (last && pickLayout(last, n - 1, n) !== "closing") add("cv.chip.closing");
  if (n >= 8) add("cv.chip.shorter");
  const next = DECK_THEMES[(DECK_THEMES.indexOf(doc.theme || "corporate") + 1) % DECK_THEMES.length];
  add("cv.chip.theme", { name: t(`cv.theme.${next}`).toLowerCase() });
  return out.slice(0, 3);
}

function sizeText(doc) {
  if (doc.kind === "deck") {
    const n = (doc.blocks || []).length;
    const kinds = new Set((doc.blocks || []).map((b, i) => pickLayout(b, i, n)));
    return t("cv.card.slides", { n, layouts: kinds.size }); // as the chat says it: the cover is not counted
  }
  if (doc.kind === "doc")
    return t("cv.sections", { n: (doc.blocks || []).length });
  if (doc.kind === "code")
    return t("cv.lines", {
      n: String(doc.code?.text || "").split("\n").length,
    });
  if (doc.kind === "sheet")
    return t("cv.rows", {
      n: doc.sheet?.rows?.length || 0,
      c: doc.sheet?.columns?.length || 0,
    });
  return "";
}

/** Open a piece of code from the chat (« Aperçu » on an HTML, SVG or diagram block) as a new artifact. */
export function openCode(c, lang, code, title = "") {
  const aid = `l${Date.now().toString(16)}${Math.random().toString(16).slice(2, 6)}`;
  const doc = {
    v: 1,
    kind: "code",
    title,
    lang: state.prefs.lang === "en" ? "en" : "fr",
    code: { lang, text: code },
    media: {},
  };
  const s = store(c);
  s.list[aid] = { aid, kind: "code", versions: [], cur: 0, draft: null };
  pushVersion(s.list[aid], doc, t("cv.label.created"));
  s.active = aid;
  handlers.save(c);
  open(aid, { focus: true });
}

// ------------------------------------------------------------------ the panel

function ensurePanel() {
  if (panel) return panel;
  panel = h("aside", {
    id: "canvas",
    class: "cv",
    hidden: true,
    "aria-labelledby": "cv-title",
    tabindex: "-1",
  });
  document.querySelector(".app")?.append(panel);
  return panel;
}

export function open(aid, { focus = true, quiet = false } = {}) {
  const a = art(aid);
  if (!a) return;
  ensurePanel();
  const was = view.aid;
  if (was !== aid)
    view = {
      aid,
      tab: null,
      sel: null,
      chart: null,
      console: [],
      frameHtml: "",
      codeDraft: null,
    };
  const first = panel.hidden;
  if (first) returnFocus = document.activeElement;
  panel.hidden = false;
  document.documentElement.classList.add("cv-open");
  if (first) handlers.onOpen?.();
  store().active = aid;
  render();
  const modal = isModal();
  setModal(modal);
  if (first && !quiet)
    announce(
      t("cv.live.opened", {
        title: current(a)?.title || t(`cv.kind.${a.kind}`),
      }),
    );
  // a full-screen sheet takes the focus even when it opens by itself (a streamed creation): what is under it is inert
  if (focus || (modal && first))
    panel.querySelector("#cv-title")?.focus({ preventScroll: true });
}

export function close(refocus = true) {
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  setModal(false);
  document.documentElement.classList.remove("cv-open");
  handlers.onClose?.();
  closePops();
  if (refocus && returnFocus?.isConnected)
    returnFocus.focus({ preventScroll: true });
}

export const isOpen = () => !!panel && !panel.hidden;

function closePops() {
  panel?.querySelectorAll(".cv-pop").forEach((p) => (p.hidden = true));
  panel
    ?.querySelectorAll("[aria-expanded='true']")
    .forEach((b) => b.setAttribute("aria-expanded", "false"));
}

function render() {
  if (!panel || panel.hidden) return;
  const a = art(view.aid);
  if (!a) return close(false);
  const doc = current(a);
  if (!doc) return;
  const body = panel.querySelector(".cv-body");
  const scroll = body ? body.scrollTop : 0;
  const keep =
    document.activeElement && panel.contains(document.activeElement)
      ? focusPath(document.activeElement)
      : null;
  panel.replaceChildren(head(a, doc), status(a, doc), bodyOf(a, doc));
  const nb = panel.querySelector(".cv-body");
  if (nb) nb.scrollTop = scroll;
  if (keep) restorePath(keep);
}

function focusPath(el) {
  const k = el.closest("[data-k]");
  return k ? k.dataset.k : null;
}
function restorePath(k) {
  const el = panel.querySelector(`[data-k="${CSS.escape(k)}"]`);
  el?.focus({ preventScroll: true });
}

function head(a, doc) {
  const kind = doc.kind || a.kind;
  const versions = h(
    "select",
    {
      class: "cv-select",
      "aria-label": t("cv.version"),
      "data-k": "versions",
      disabled: !!a.draft || a.versions.length < 2,
      onchange: (e) => {
        a.cur = Number(e.target.value);
        a.draft = null;
        handlers.save(conv);
        render();
      },
    },
    a.versions.map((v, i) =>
      h("option", {
        value: String(i),
        selected: i === a.cur,
        text: v.label
          ? t("cv.version.label", { n: v.n, label: v.label })
          : t("cv.version.n", { n: v.n }),
      }),
    ),
  );
  const themes =
    kind === "deck" || kind === "doc"
      ? h(
          "div",
          {
            class: "cv-themes",
            role: "radiogroup",
            "aria-label": t("cv.theme"),
          },
          (kind === "deck" ? DECK_THEMES : THEMES).map((name) =>
            h("button", {
              type: "button",
              role: "radio",
              class: `cv-swatch cvt-${name}`,
              "aria-checked": String((doc.theme || "corporate") === name),
              "aria-label": t(`cv.theme.${name}`),
              title: t(`cv.theme.${name}`),
              "data-k": `theme-${name}`,
              disabled: !!a.draft,
              onclick: () =>
                commit((d) => {
                  if (d.theme === name) return false;
                  d.theme = name;
                }, t("cv.label.theme")),
            }),
          ),
        )
      : null;
  return h(
    "header",
    { class: "cv-head" },
    h(
      "div",
      { class: "cv-heading" },
      h("span", { class: "cv-kind", text: t(`cv.kind.${kind}`) }),
      h("h2", {
        id: "cv-title",
        class: "cv-title",
        tabindex: "-1",
        text: doc.title || t(`cv.kind.${kind}`),
      }),
    ),
    h(
      "div",
      { class: "cv-tools" },
      versions,
      !a.draft && a.cur < a.versions.length - 1
        ? button("btn-outline btn-small cv-restore", "retry", t("cv.restore"), () => {
            const old = a.versions[a.cur];
            pushVersion(a, clone(old.doc), t("cv.restored", { n: old.n }));
            handlers.save(conv);
            render();
            announce(t("cv.live.version", { n: a.versions.at(-1).n }));
          }, { "data-k": "restore" })
        : null,
      themes,
      button("btn-quiet btn-icon", "copy", t("cv.copy"), () => copyDoc(doc), {
        "data-k": "copy",
      }),
      downloadMenu(doc),
      button(
        "btn-quiet btn-icon cv-close",
        "cross",
        t("cv.close"),
        () => close(),
        { "data-k": "close" },
      ),
    ),
  );
}

function status(a, doc) {
  const what = sizeText(doc);
  return h("p", {
    class: `cv-status${a.draft ? " is-writing" : ""}`,
    role: "status",
    "aria-live": "polite",
    text: a.draft ? t("cv.writing", { what }) : t("cv.ready", { what }),
  });
}

function downloadMenu(doc) {
  const items = [];
  if (doc.kind === "deck")
    items.push(
      ["pptx", t("cv.download.pptx")],
      ["docx", t("cv.download.docx")],
      ["pdf", t("cv.download.pdf")],
    );
  else if (doc.kind === "doc")
    items.push(["docx", t("cv.download.docx")], ["pdf", t("cv.download.pdf")]);
  else if (doc.kind === "sheet")
    items.push(["xlsx", t("cv.download.xlsx")], ["csv", t("cv.download.csv")]);
  else
    items.push([
      "file",
      t("cv.download.file", { ext: codeExt(doc.code?.lang) }),
    ]);
  const pop = h(
    "div",
    { class: "cv-pop cv-menu", role: "menu", hidden: true },
    items.map(([fmt, label]) =>
      h(
        "button",
        {
          type: "button",
          role: "menuitem",
          class: "cv-menu-item",
          "data-k": `dl-${fmt}`,
          onclick: () => {
            closePops();
            exportAs(doc, fmt);
          },
        },
        icon(fmt === "pdf" ? "file" : "download"),
        h("span", { text: label }),
      ),
    ),
  );
  const btn = button(
    "btn-quiet btn-icon",
    "download",
    t("cv.download"),
    (e) => {
      const openNow = pop.hidden;
      closePops();
      pop.hidden = !openNow;
      e.currentTarget.setAttribute("aria-expanded", String(openNow));
      if (openNow) pop.querySelector("button")?.focus();
    },
    { "aria-haspopup": "menu", "aria-expanded": "false", "data-k": "download" },
  );
  return h("div", { class: "cv-menu-wrap" }, btn, pop);
}

const codeExt = (lang) =>
  ({
    html: "html",
    svg: "svg",
    css: "css",
    js: "js",
    python: "py",
    mermaid: "mmd",
    markdown: "md",
    json: "json",
  })[lang] || "txt";

async function exportAs(doc, fmt) {
  if (fmt === "pdf") return printDoc(doc);
  if (fmt === "file") {
    const lang = doc.code?.lang;
    const mime =
      lang === "html"
        ? "text/html"
        : lang === "svg"
          ? "image/svg+xml"
          : "text/plain";
    return download(
      `${slug(doc.title)}.${codeExt(lang)}`,
      `${mime};charset=utf-8`,
      String(doc.code?.text || ""),
    );
  }
  if (fmt === "csv") {
    const values = sheet.compute(doc.sheet.rows);
    return download(
      `${slug(doc.title)}.csv`,
      "text/csv;charset=utf-8",
      "﻿" + sheet.toCsv(doc.sheet.columns, values),
    );
  }
  const used = {};
  for (const b of doc.blocks || [])
    for (const p of b.parts || [])
      if (p.t === "image" && p.media) {
        const m = media.get(p.media)?.entry || conv?.canvasMedia?.[p.media];
        if (m?.data) used[p.media] = m.data;
      }
  toast(t("cv.downloading"));
  try {
    const r = await fetch("/api/canvas/export", {
      method: "POST",
      headers: { ...handlers.headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ doc, format: fmt, media: used }),
    });
    if (!r.ok) {
      let why = `HTTP ${r.status}`;
      try {
        why = (await r.json()).detail?.message || why;
      } catch {
        /* not JSON */
      }
      return toast(t("cv.download.failed", { why }), "error");
    }
    const blob = await r.blob();
    download(`${slug(doc.title)}.${fmt}`, blob.type, blob);
  } catch (e) {
    toast(t("cv.download.failed", { why: String(e?.message || e) }), "error");
  }
}

const slug = (s) =>
  String(s || "bird")
    .replace(/[^\p{L}\p{N} _-]+/gu, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 60) || "bird";

function copyDoc(doc) {
  if (doc.kind === "code")
    return copyText(String(doc.code?.text || ""), t("cv.copied"));
  if (doc.kind === "sheet")
    return copyText(
      sheet.toCsv(doc.sheet.columns, sheet.compute(doc.sheet.rows), "\t"),
      t("cv.copied"),
    );
  return copyText(docText(doc), t("cv.copied"));
}

/** The document as Markdown (copy, and what « Copier » puts in an e-mail or a note). */
export function docText(doc) {
  const out = [`# ${doc.title || ""}`];
  if (doc.subtitle) out.push(`_${doc.subtitle}_`);
  for (const b of doc.blocks || []) {
    out.push("", `## ${b.title || ""}`);
    for (const p of b.parts || []) {
      if (p.t === "text" || p.t === "callout") out.push(p.text);
      else if (p.t === "heading") out.push(`### ${p.text}`);
      else if (p.t === "list")
        out.push(
          ...p.items.map((i) =>
            i.startsWith("  ") ? `  - ${i.trim()}` : `- ${i}`,
          ),
        );
      else if (p.t === "kpi")
        out.push(
          ...p.items.map(
            (k) =>
              `- **${k.value}** ${k.label}${k.delta ? ` (${k.delta})` : ""}`,
          ),
        );
      else if (p.t === "timeline")
        out.push(...p.items.map((x) => `- **${x.when}** ${x.what}`));
      else if (p.t === "quote")
        out.push(`> ${p.text}${p.by ? ` — ${p.by}` : ""}`);
      else if (p.t === "table")
        out.push(
          ...p.rows.map(
            (r, i) =>
              `| ${r.join(" | ")} |${i === 0 ? `\n|${r.map(() => "---").join("|")}|` : ""}`,
          ),
        );
      else if (p.t === "chart")
        out.push(
          `| ${p.columns.join(" | ")} |`,
          `|${p.columns.map(() => "---").join("|")}|`,
          ...p.rows.map((r) => `| ${r.join(" | ")} |`),
        );
      else if (p.t === "code") out.push("```" + (p.lang || ""), p.text, "```");
      else if (p.t === "image") {
        const m = mediaMeta(doc, p.media);
        if (m?.credit) out.push(`_${t("cv.credit")} : ${m.credit}_`);
      }
    }
    if (b.notes) out.push("", `> ${b.notes}`);
  }
  return out.join("\n");
}

function bodyOf(a, doc) {
  const kind = doc.kind || a.kind;
  if (kind === "code") return codeView(a, doc);
  if (kind === "sheet") return sheetView(a, doc);
  return h(
    "div",
    { class: `cv-body cv-kind-${kind} cvt-${doc.theme || "corporate"}` },
    kind === "deck" ? deckView(a, doc) : docView(a, doc),
  );
}

// ------------------------------------------------------------------ inline editing

function editable(
  tag,
  cls,
  text,
  path,
  { multiline = false, label = "" } = {},
) {
  const el = h(tag, {
    class: `${cls} cv-ed`,
    tabindex: "0",
    "data-k": `ed-${path}`,
    "data-path": path,
    title: t("cv.edit.hint"),
    "aria-label": label ? `${label} — ${t("cv.edit.hint")}` : t("cv.edit.hint"),
    text: text ?? "",
  });
  const start = () => {
    const a = art(view.aid);
    if (!a || a.draft || el.isContentEditable) return;
    const before = el.textContent;
    el.contentEditable = "plaintext-only";
    if (el.contentEditable !== "plaintext-only") el.contentEditable = "true";
    el.classList.add("is-editing");
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const finish = (save) => {
      el.removeEventListener("blur", onBlur);
      el.removeEventListener("keydown", onKey);
      el.contentEditable = "false";
      el.removeAttribute("contenteditable");
      el.classList.remove("is-editing");
      const value = el.textContent
        .replace(/ /g, " ")
        .replace(/\s+\n/g, "\n")
        .trim();
      if (!save || value === before.trim()) {
        el.textContent = before;
        return;
      }
      commit((d) => setPath(d, path, value), t("cv.edited"));
    };
    const onBlur = () => finish(true);
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        finish(false);
        el.focus();
      } else if (e.key === "Enter" && (!multiline || e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        finish(true);
      }
    };
    el.addEventListener("blur", onBlur);
    el.addEventListener("keydown", onKey);
  };
  el.addEventListener("click", start);
  el.addEventListener("keydown", (e) => {
    if (!el.isContentEditable && (e.key === "Enter" || e.key === "F2")) {
      e.preventDefault();
      start();
    }
  });
  return el;
}

/** Write ``value`` at ``path`` ("title", "subtitle", "b3:title", "b3:p0:text", "b3:p1:i2", "b3:p0:k1:value",
 * "b3:p0:t1:what", "b3:p0:r1:c2", "b3:p0:by") in the document. Returns false when the path does not exist. */
export function setPath(doc, path, value) {
  const col = /^col:(\d+)$/.exec(String(path)); // a sheet's column name
  if (col) {
    if (doc.sheet?.columns?.[Number(col[1])] === undefined) return false;
    doc.sheet.columns[Number(col[1])] = value.slice(0, 120);
    return true;
  }
  const bits = String(path).split(":");
  if (bits.length === 1) {
    if (!["title", "subtitle"].includes(bits[0])) return false;
    doc[bits[0]] = value.slice(0, 200);
    return true;
  }
  const b = (doc.blocks || []).find((x) => x.id === bits[0]);
  if (!b) return false;
  if (bits[1] === "title" || bits[1] === "notes") {
    b[bits[1]] = value.slice(0, bits[1] === "title" ? 200 : 4000);
    return true;
  }
  const p = b.parts?.[Number(bits[1].slice(1))];
  if (!p) return false;
  const leaf = bits[2];
  if (leaf === "text" || leaf === "by") p[leaf] = value.slice(0, 4000);
  else if (/^i\d+$/.test(leaf) && p.items) {
    const i = Number(leaf.slice(1));
    if (!value) p.items.splice(i, 1);
    else
      p.items[i] =
        (String(p.items[i] || "").startsWith("  ") ? "  " : "") +
        value.slice(0, 600);
  } else if (/^k\d+$/.test(leaf) && p.items?.[Number(leaf.slice(1))])
    p.items[Number(leaf.slice(1))][bits[3]] = value.slice(0, 120);
  else if (/^s\d+$/.test(leaf) && p.items?.[Number(leaf.slice(1))] && ["title", "text"].includes(bits[3]))
    p.items[Number(leaf.slice(1))][bits[3]] = value.slice(0, bits[3] === "title" ? 80 : 300);
  else if (/^c\d+$/.test(leaf) && p.columns?.[Number(leaf.slice(1))]) {
    const c = p.columns[Number(leaf.slice(1))];
    if (bits[3] === "title") c.title = value.slice(0, 80);
    else if (/^i\d+$/.test(bits[3] || "")) {
      const i = Number(bits[3].slice(1));
      if (!value) c.items.splice(i, 1);
      else c.items[i] = value.slice(0, 300);
    } else return false;
  } else if (/^t\d+$/.test(leaf) && p.items?.[Number(leaf.slice(1))])
    p.items[Number(leaf.slice(1))][bits[3]] = value.slice(0, 300);
  else if (/^r\d+$/.test(leaf) && p.rows?.[Number(leaf.slice(1))])
    p.rows[Number(leaf.slice(1))][Number(bits[3].slice(1))] = value.slice(
      0,
      300,
    );
  else return false;
  return true;
}

// ------------------------------------------------------------------ block tools (move, duplicate, delete, image, ask)

function moveBlock(id, delta) {
  commit((d) => {
    const i = d.blocks.findIndex((b) => b.id === id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= d.blocks.length) return false;
    [d.blocks[i], d.blocks[j]] = [d.blocks[j], d.blocks[i]];
  }, t("cv.label.moved"));
  panel
    ?.querySelector(`[data-k="${delta < 0 ? "up" : "down"}-${id}"]`)
    ?.focus();
}

function nextId(d) {
  const used = d.blocks.map((b) => Number(String(b.id).slice(1)) || 0);
  const n = Math.max(Number(d._next) || 1, ...used.map((u) => u + 1));
  d._next = n + 1;
  return `b${n}`;
}

function blockTools(a, doc, b, index, layout = null) {
  const busy = !!a.draft;
  const n = doc.blocks.length;
  const imgPart = b.parts.findIndex((p) => p.t === "image");
  const ask = h(
    "form",
    {
      class: "cv-pop cv-ask",
      hidden: true,
      onsubmit: (e) => {
        e.preventDefault();
        const text = e.currentTarget.querySelector("input").value.trim();
        if (!text) return;
        if (handlers.busy()) return toast(t("cv.ask.busy"), "error");
        closePops();
        target = { aid: a.aid, block: b.id };
        handlers.send(text);
      },
    },
    h("label", {
      class: "sr-only",
      for: `cv-ask-${b.id}`,
      text: t("cv.ask.placeholder"),
    }),
    h("input", {
      id: `cv-ask-${b.id}`,
      type: "text",
      maxlength: "600",
      placeholder: t("cv.ask.placeholder"),
      autocomplete: "off",
    }),
    button("btn-primary btn-small", "send", t("cv.ask.send"), null, {
      type: "submit",
    }),
  );
  const imgMenu = h(
    "div",
    { class: "cv-pop cv-menu", role: "menu", hidden: true },
    h(
      "button",
      {
        type: "button",
        role: "menuitem",
        class: "cv-menu-item",
        onclick: () => {
          closePops();
          searchImage(b, imgPart, { ask: true });
        },
      },
      icon("search"),
      h("span", { text: t("cv.image.search") }),
    ),
    imgPart >= 0 &&
      h(
        "button",
        {
          type: "button",
          role: "menuitem",
          class: "cv-menu-item",
          onclick: () => {
            closePops();
            searchImage(b, imgPart, { again: true });
          },
        },
        icon("retry"),
        h("span", { text: t("cv.image.replace") }),
      ),
    h(
      "button",
      {
        type: "button",
        role: "menuitem",
        class: "cv-menu-item",
        onclick: () => {
          closePops();
          uploadImage(b, imgPart);
        },
      },
      icon("image"),
      h("span", { text: t("cv.image.upload") }),
    ),
    imgPart >= 0 &&
      h(
        "button",
        {
          type: "button",
          role: "menuitem",
          class: "cv-menu-item",
          onclick: () => {
            closePops();
            commit((d) => {
              d.blocks.find((x) => x.id === b.id).parts.splice(imgPart, 1);
            }, t("cv.label.image"));
          },
        },
        icon("trash"),
        h("span", { text: t("cv.image.none.short") }),
      ),
  );
  const toggle = (pop) => (e) => {
    const openNow = pop.hidden;
    closePops();
    pop.hidden = !openNow;
    e.currentTarget.setAttribute("aria-expanded", String(openNow));
    if (openNow)
      (pop.querySelector("input") || pop.querySelector("button"))?.focus();
  };
  return h(
    "div",
    {
      class: "cv-block-tools",
      role: "toolbar",
      "aria-label":
        doc.kind === "deck"
          ? t("cv.slide.n", { n: index + 1 })
          : t("cv.section.n", { n: index + 1 }),
    },
    doc.kind === "deck"
      ? h(
          "span",
          {
            class: "cv-grip",
            draggable: busy ? "false" : "true",
            role: "img",
            title: t("cv.drag"),
            "aria-label": t("cv.drag"),
            "data-k": `grip-${b.id}`,
            ondragstart: (e) => dragStart(e, b.id),
            ondragend: dragEnd,
          },
          h("span", { class: "cv-block-n", text: String(index + 1) }),
        )
      : h("span", { class: "cv-block-n", text: String(index + 1) }),
    button(
      "btn-quiet btn-icon btn-small cv-up",
      "down",
      t("cv.up"),
      () => moveBlock(b.id, -1),
      { disabled: busy || index === 0, "data-k": `up-${b.id}` },
    ),
    button(
      "btn-quiet btn-icon btn-small",
      "down",
      t("cv.down"),
      () => moveBlock(b.id, 1),
      { disabled: busy || index === n - 1, "data-k": `down-${b.id}` },
    ),
    button(
      "btn-quiet btn-icon btn-small",
      "copy",
      t("cv.duplicate"),
      () =>
        commit((d) => {
          const i = d.blocks.findIndex((x) => x.id === b.id);
          d.blocks.splice(i + 1, 0, { ...clone(d.blocks[i]), id: nextId(d) });
        }, t("cv.label.dup")),
      { disabled: busy || n >= 40, "data-k": `dup-${b.id}` },
    ),
    button(
      "btn-quiet btn-icon btn-small",
      "trash",
      t("cv.delete"),
      () =>
        commit((d) => {
          if (d.blocks.length <= 1) return false;
          d.blocks = d.blocks.filter((x) => x.id !== b.id);
        }, t("cv.label.deleted")),
      { disabled: busy || n <= 1, "data-k": `del-${b.id}` },
    ),
    h(
      "span",
      { class: "cv-menu-wrap" },
      button(
        "btn-quiet btn-icon btn-small",
        "image",
        t("cv.image"),
        toggle(imgMenu),
        {
          disabled: busy,
          "aria-haspopup": "menu",
          "aria-expanded": "false",
          "data-k": `img-${b.id}`,
        },
      ),
      imgMenu,
    ),
    layout && layoutMenu(a, b, layout, toggle),
    h(
      "span",
      { class: "cv-menu-wrap cv-ask-wrap" },
      button(
        "btn-quiet btn-small cv-ask-btn",
        "spark",
        t("cv.ask"),
        toggle(ask),
        { disabled: busy, "aria-expanded": "false", "data-k": `ask-${b.id}` },
      ),
      ask,
    ),
  );
}

/** « Mise en page »: the layouts this slide's content can take (canvas-layouts.js), the current one checked. */
function layoutMenu(a, b, layout, toggle) {
  const lang = state.prefs.lang === "en" ? 1 : 0;
  const menu = h(
    "div",
    { class: "cv-pop cv-menu cv-layouts", role: "menu", hidden: true },
    compatible(b).map((name) =>
      h(
        "button",
        {
          type: "button",
          role: "menuitemradio",
          class: "cv-menu-item",
          "aria-checked": String(name === layout),
          "data-k": `layout-${b.id}-${name}`,
          onclick: () => {
            closePops();
            if (name === layout) return;
            commit((d) => {
              d.blocks.find((x) => x.id === b.id).layout = name;
            }, CATALOGUE[name][lang]);
          },
        },
        h("span", { class: `cv-lay-ico cv-lay-${name}`, "aria-hidden": "true" }),
        h("span", { text: CATALOGUE[name][lang] }),
      ),
    ),
  );
  return h(
    "span",
    { class: "cv-menu-wrap" },
    button(
      "btn-quiet btn-small cv-layout-btn",
      "make_slides",
      CATALOGUE[layout]?.[lang] || t("cv.layout"),
      toggle(menu),
      {
        disabled: !!a.draft,
        "aria-haspopup": "menu",
        "aria-expanded": "false",
        "aria-label": t("cv.layout.now", { name: CATALOGUE[layout]?.[lang] || layout }),
        "data-k": `layout-${b.id}`,
      },
    ),
    menu,
  );
}

async function fetchImage(query, exclude, theme) {
  const r = await fetch("/api/canvas/image", {
    method: "POST",
    headers: { ...handlers.headers(), "Content-Type": "application/json" },
    body: JSON.stringify({
      query: query.slice(0, 120),
      exclude: exclude.slice(0, 8),
      theme: theme || null,
      lang: state.prefs.lang === "en" ? "en" : "fr",
      mid: freeMediaId(handlers.mode() === "demo" ? "g" : "w"),
    }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function freeMediaId(prefix) {
  const used = new Set([
    ...media.keys(),
    ...Object.keys(conv?.canvasMedia || {}),
  ]);
  const a = art(view.aid);
  for (const v of a?.versions || [])
    for (const k of Object.keys(v.doc.media || {})) used.add(k);
  let n = 1;
  while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

async function searchImage(b, partIndex, { ask = false, again = false } = {}) {
  const a = art(view.aid);
  const doc = current(a);
  const part = partIndex >= 0 ? b.parts[partIndex] : null;
  let query = part?.query || b.title || doc.title || "";
  if (ask) {
    const q = window.prompt(t("cv.image.query"), query);
    if (q === null) return;
    query = q.trim();
    if (!query) return;
  }
  const exclude =
    again && part?.media
      ? [mediaMeta(doc, part.media)?.source || part.media]
      : [];
  toast(t("cv.image.searching"));
  try {
    const res = await fetchImage(query, exclude, doc.theme);
    if (!res.ok) return toast(t("cv.image.none", { q: query }), "error");
    const m = res.media;
    keepMedia(conv, [m]);
    commit((d) => {
      d.media ||= {};
      d.media[m.id] = {
        kind: m.kind,
        alt: m.alt,
        credit: m.credit,
        licence: m.licence,
        source: m.source,
        w: m.w,
        h: m.h,
        query,
      };
      const blk = d.blocks.find((x) => x.id === b.id);
      const p = {
        t: "image",
        query,
        alt: m.alt || query,
        caption: "",
        media: m.id,
      };
      const i = blk.parts.findIndex((x) => x.t === "image");
      if (i >= 0) blk.parts[i] = p;
      else blk.parts.push(p);
    }, t("cv.label.image"));
  } catch (e) {
    toast(t("cv.download.failed", { why: String(e?.message || e) }), "error");
  }
}

function uploadImage(b) {
  const input = h("input", {
    type: "file",
    accept: "image/png,image/jpeg,image/webp",
    class: "sr-only",
  });
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    input.remove();
    if (!file) return;
    try {
      const m = await shrink(file, freeMediaId("u"));
      keepMedia(conv, [m]);
      commit((d) => {
        d.media ||= {};
        d.media[m.id] = {
          kind: "user",
          alt: m.alt,
          credit: "",
          licence: "",
          source: "",
          w: m.w,
          h: m.h,
          query: "",
        };
        const blk = d.blocks.find((x) => x.id === b.id);
        const p = {
          t: "image",
          query: m.alt,
          alt: m.alt,
          caption: "",
          media: m.id,
        };
        const i = blk.parts.findIndex((x) => x.t === "image");
        if (i >= 0) blk.parts[i] = p;
        else blk.parts.push(p);
      }, t("cv.label.image"));
    } catch {
      toast(t("cv.image.none", { q: file.name }), "error");
    }
  });
  document.body.append(input);
  input.click();
}

/** The user's picture, re-encoded here (JPEG, long side 1600 px): what is kept and sent for the exports. */
async function shrink(file, id) {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
  const w = Math.max(1, Math.round(bmp.width * k));
  const hh = Math.max(1, Math.round(bmp.height * k));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = hh;
  c.getContext("2d").drawImage(bmp, 0, 0, w, hh);
  const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.85));
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000)
    bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return {
    id,
    kind: "user",
    data: btoa(bin),
    fmt: "jpeg",
    w,
    h: hh,
    alt: file.name.replace(/\.[a-z]+$/i, "").slice(0, 120),
    credit: "",
    licence: "",
    source: "",
  };
}

// ------------------------------------------------------------------ pictures

function picture(doc, b, part, { cls = "" } = {}) {
  const url = part.media ? mediaUrl(part.media) : null;
  const meta = mediaMeta(doc, part.media);
  if (!url) {
    return h(
      "figure",
      { class: `cv-img cv-img-empty ${cls}` },
      h(
        "div",
        { class: "cv-img-ph" },
        icon("image"),
        h("span", {
          text: part.media
            ? t("cv.image.lost")
            : t("cv.image.pending", { q: part.query || "" }),
        }),
        button(
          "btn-outline btn-small",
          "search",
          t("cv.image.search"),
          () => searchImage(b, b.parts.indexOf(part)),
          { "data-k": `ph-${b.id}` },
        ),
      ),
    );
  }
  const credit = meta?.credit ? `${meta.credit}` : "";
  return h(
    "figure",
    { class: `cv-img ${cls}` },
    h("img", {
      src: url,
      alt: part.alt || meta?.alt || "",
      loading: "lazy",
      decoding: "async",
    }),
    (credit || meta?.kind === "gen") &&
      h(
        "figcaption",
        { class: "cv-credit" },
        meta?.kind === "gen" ? t("cv.image.gen") : credit,
        meta?.source && /^https:\/\//.test(meta.source)
          ? [
              " · ",
              h("a", {
                href: meta.source,
                target: "_blank",
                rel: "noopener noreferrer",
                text: t("cv.source"),
              }),
            ]
          : null,
      ),
  );
}

// ------------------------------------------------------------------ the deck

// The layout of each slide comes from canvas-layouts.js (the same choice as the exported .pptx: deck_pptx.py).
const slideCount = (doc) => (doc.blocks || []).length + 1;

function deckView(a, doc) {
  const slides = [coverSlide(a, doc)];
  const total = doc.blocks.length;
  let sections = 0;
  doc.blocks.forEach((b, i) => {
    const layout = layoutOf(b, i, total);
    if (layout === "section") sections += 1;
    slides.push(
      h(
        "section",
        {
          class: `cv-slide-wrap${a.draft && i === total - 1 ? " is-new" : ""}`,
          "data-block": b.id,
          "aria-label": `${t("cv.slide.n", { n: i + 1 })} : ${b.title || ""}`,
          ondragover: (e) => dragOver(e, b.id),
          ondragleave: (e) => e.currentTarget.classList.remove("is-drop-before", "is-drop-after"),
          ondrop: (e) => dropOn(e, b.id),
        },
        blockTools(a, doc, b, i, layout),
        slide(doc, b, i, layout, sections),
      ),
    );
  });
  return h("div", { class: "cv-deck" }, slides);
}

// ------------------------------------------------------------------ drag to reorder (the arrows do the same by keyboard)

let dragging = null;
function dragStart(e, id) {
  dragging = id;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", id);
  e.currentTarget.closest(".cv-slide-wrap")?.classList.add("is-dragging");
}
function dragOver(e, id) {
  if (!dragging || dragging === id) return;
  e.preventDefault();
  const r = e.currentTarget.getBoundingClientRect();
  const after = e.clientY > r.top + r.height / 2;
  e.currentTarget.classList.toggle("is-drop-after", after);
  e.currentTarget.classList.toggle("is-drop-before", !after);
}
function dropOn(e, id) {
  if (!dragging) return;
  e.preventDefault();
  const after = e.currentTarget.classList.contains("is-drop-after");
  e.currentTarget.classList.remove("is-drop-before", "is-drop-after");
  const from = dragging;
  dragging = null;
  if (from === id) return;
  commit((d) => {
    const i = d.blocks.findIndex((x) => x.id === from);
    if (i < 0) return false;
    const [blk] = d.blocks.splice(i, 1);
    let j = d.blocks.findIndex((x) => x.id === id);
    if (after) j += 1;
    d.blocks.splice(j, 0, blk);
  }, t("cv.label.moved"));
}
function dragEnd(e) {
  dragging = null;
  panel?.querySelectorAll(".is-dragging, .is-drop-before, .is-drop-after").forEach((el) =>
    el.classList.remove("is-dragging", "is-drop-before", "is-drop-after"),
  );
}

// ------------------------------------------------------------------ the cover

function coverSlide(a, doc) {
  const cv = doc.cover || {};
  const url = cv.media && !cv.off ? mediaUrl(cv.media) : null;
  const meta = url ? mediaMeta(doc, cv.media) : null;
  const tools = h(
    "div",
    { class: "cv-block-tools cv-block-tools-cover", role: "toolbar", "aria-label": t("cv.cover") },
    h("span", { class: "cv-block-n", text: t("cv.cover") }),
    url &&
      button("btn-quiet btn-small", "retry", t("cv.image.again"), () => coverImage(a, "again"), {
        disabled: !!a.draft,
        "data-k": "cover-again",
      }),
    url &&
      button("btn-quiet btn-small", "trash", t("cv.image.none.short"), () => coverImage(a, "off"), {
        disabled: !!a.draft,
        "data-k": "cover-off",
      }),
    !url &&
      button("btn-quiet btn-small", "image", t("cv.image.cover"), () => coverImage(a, "search"), {
        disabled: !!a.draft,
        "data-k": "cover-search",
      }),
  );
  return h(
    "section",
    { class: "cv-slide-wrap", "aria-label": t("cv.cover") },
    tools,
    h(
      "div",
      { class: `cv-slide cv-cover${url ? " has-img" : ""}`, "data-layout": "cover" },
      url
        ? h("img", { class: "cv-bleed", src: url, alt: meta?.alt || cv.query || "", decoding: "async" })
        : [h("span", { class: "cv-disc cv-disc-1", "aria-hidden": "true" }), h("span", { class: "cv-disc cv-disc-2", "aria-hidden": "true" })],
      url && h("span", { class: "cv-veil", "aria-hidden": "true" }),
      url && creditLine(meta, "cv-credit-top"),
      h("div", { class: "cv-cover-accent", "aria-hidden": "true" }),
      editable("h3", "cv-cover-title", doc.title, "title", { label: t("cv.edit.title") }),
      doc.subtitle || !doc.blocks?.length
        ? editable("p", "cv-cover-sub", doc.subtitle || "", "subtitle")
        : editable("p", "cv-cover-sub cv-faint", "", "subtitle"),
      h("p", {
        class: "cv-cover-date",
        text: new Date().toLocaleDateString(state.prefs.lang === "en" ? "en-GB" : "fr-FR", {
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
      }),
    ),
  );
}

function creditLine(meta, cls = "") {
  if (!meta) return null;
  const text = meta.kind === "gen" ? t("cv.image.gen") : meta.credit || "";
  if (!text) return null;
  return h(
    "span",
    { class: `cv-credit ${cls}` },
    text,
    meta.source && /^https:\/\//.test(meta.source)
      ? [" · ", h("a", { href: meta.source, target: "_blank", rel: "noopener noreferrer", text: t("cv.source") })]
      : null,
  );
}

async function coverImage(a, how) {
  const doc = current(a);
  const cv = doc.cover || {};
  if (how === "off") return commit((d) => { d.cover = { ...(d.cover || {}), off: true }; }, t("cv.label.image"));
  let query = cv.query || doc.title || "";
  if (how === "search") {
    if (cv.off && cv.media && mediaUrl(cv.media))
      return commit((d) => { delete d.cover.off; }, t("cv.label.image"));
    const q = window.prompt(t("cv.image.query"), query);
    if (q === null || !q.trim()) return;
    query = q.trim();
  }
  const exclude = how === "again" && cv.media ? [mediaMeta(doc, cv.media)?.source || cv.media] : [];
  toast(t("cv.image.searching"));
  try {
    const res = await fetchImage(query, exclude, doc.theme);
    if (!res.ok) return toast(t("cv.image.none", { q: query }), "error");
    keepMedia(conv, [res.media]);
    commit((d) => {
      storeMedia(d, res.media, query);
      d.cover = { query, media: res.media.id };
    }, t("cv.label.image"));
  } catch (e) {
    toast(t("cv.download.failed", { why: String(e?.message || e) }), "error");
  }
}

function storeMedia(d, m, query) {
  d.media ||= {};
  d.media[m.id] = {
    kind: m.kind,
    alt: m.alt,
    credit: m.credit,
    licence: m.licence,
    source: m.source,
    w: m.w,
    h: m.h,
    query,
  };
}

// ------------------------------------------------------------------ one slide

const layoutOf = (b, i, total) => pickLayout(b, i, total);
const isDark = (layout) => ["section", "closing", "image-full"].includes(layout);
const OWN_FOOT = new Set(["section", "closing", "image-full"]);

function slide(doc, b, index, layout, sections) {
  const total = doc.blocks.length;
  const parts = b.parts || [];
  const main = mainPart(b);
  const imgs = parts.filter((p) => p.t === "image");
  const text = parts.filter((p) => ["list", "text", "callout", "heading"].includes(p.t));
  const title = (cls = "cv-slide-title") =>
    editable("h3", cls, b.title, `${b.id}:title`, { label: t("cv.edit.title") });
  const rule = () => h("div", { class: "cv-slide-rule", "aria-hidden": "true" });
  const foot = () =>
    h(
      "footer",
      { class: "cv-slide-foot" },
      h("span", { text: doc.title || "" }),
      h("span", { text: `${index + 2} / ${total + 1}` }),
    );
  const k = main ? b.parts.indexOf(main) : -1;
  const shell = (body, extra = {}) =>
    h(
      "div",
      { class: `cv-slide cv-L-${layout}${extra.cls || ""}`, "data-layout": layout },
      extra.before || null,
      extra.noTitle ? null : title(extra.titleCls),
      extra.noTitle ? null : rule(),
      h("div", { class: "cv-slide-body" }, body),
      foot(),
    );
  const img0 = imgs[0];
  const sideImg = img0 && mediaUrl(img0.media || "") ? img0 : null;

  switch (layout) {
    case "section":
      return h(
        "div",
        { class: `cv-slide cv-L-section${sideImg ? " has-img" : ""}`, "data-layout": layout },
        sideImg ? picture(doc, b, sideImg, { cls: "cv-half" }) : h("span", { class: "cv-disc cv-disc-1", "aria-hidden": "true" }),
        h("div", { class: "cv-divider-num", "aria-hidden": "true", text: String(sections).padStart(2, "0") }),
        h("div", { class: "cv-cover-accent", "aria-hidden": "true" }),
        title("cv-slide-title cv-divider-title"),
        text.length ? h("div", { class: "cv-divider-sub" }, textParts(b, text)) : null,
        foot(),
      );
    case "closing": {
      const url = img0 && mediaUrl(img0.media || "");
      return h(
        "div",
        { class: `cv-slide cv-L-closing${url ? " has-img" : ""}`, "data-layout": layout },
        url
          ? [h("img", { class: "cv-bleed", src: url, alt: img0.alt || "", decoding: "async" }), h("span", { class: "cv-veil", "aria-hidden": "true" }), creditLine(mediaMeta(doc, img0.media), "cv-credit-top")]
          : h("span", { class: "cv-disc cv-disc-3", "aria-hidden": "true" }),
        h("div", { class: "cv-cover-accent", "aria-hidden": "true" }),
        title("cv-slide-title cv-close-title"),
        text.length ? h("div", { class: "cv-close-body" }, textParts(b, text)) : null,
        foot(),
      );
    }
    case "image-full": {
      const meta = img0 ? mediaMeta(doc, img0.media) : null;
      const url = img0?.media ? mediaUrl(img0.media) : null;
      return h(
        "div",
        { class: "cv-slide cv-L-image-full", "data-layout": layout },
        url ? h("img", { class: "cv-bleed", src: url, alt: img0.alt || meta?.alt || "", decoding: "async" }) : picture(doc, b, img0, { cls: "cv-bleed-ph" }),
        h("span", { class: "cv-veil cv-veil-foot", "aria-hidden": "true" }),
        url && creditLine(meta, "cv-credit-top"),
        h("div", { class: "cv-cover-accent", "aria-hidden": "true" }),
        title("cv-slide-title cv-full-title"),
        text.length ? h("div", { class: "cv-full-sub" }, textParts(b, text)) : null,
        foot(),
      );
    }
    case "image-left":
    case "image-right":
      return h(
        "div",
        { class: `cv-slide cv-L-side cv-L-${layout}`, "data-layout": layout },
        picture(doc, b, img0, { cls: "cv-side-img" }),
        h(
          "div",
          { class: "cv-side-text" },
          title(),
          rule(),
          h("div", { class: "cv-slide-body" }, textParts(b, text)),
          foot(),
        ),
      );
    case "statement":
      return shell(h("div", { class: "cv-statement" }, textParts(b, text)), { titleCls: "cv-slide-title cv-eyebrow" });
    case "bullets":
      return shell(h("div", { class: `cv-bullets n${text.reduce((n, p) => n + (p.items?.length || 1), 0)}` }, textParts(b, text)));
    case "columns":
      return shell(h("div", { class: "cv-columns" }, textParts(b, text)));
    case "agenda": {
      const lp = parts.find((p) => p.t === "list");
      const kk = parts.indexOf(lp);
      return shell(
        h(
          "ol",
          { class: `cv-agenda n${lp.items.length}` },
          lp.items.map((it, i) =>
            it.startsWith("  ")
              ? null
              : h(
                  "li",
                  null,
                  h("span", { class: "cv-agenda-n", "aria-hidden": "true", text: String(i + 1).padStart(2, "0") }),
                  editable("span", "cv-agenda-t", it.trim(), `${b.id}:p${kk}:i${i}`),
                ),
          ),
        ),
      );
    }
    case "figure": {
      const it = main.items[0] || {};
      return h(
        "div",
        { class: `cv-slide cv-L-figure${sideImg ? " has-img" : ""}`, "data-layout": layout },
        title(),
        rule(),
        h(
          "div",
          { class: "cv-slide-body cv-figure" },
          editable("strong", "cv-fig-value", it.value, `${b.id}:p${k}:k0:value`),
          editable("span", "cv-fig-label", it.label, `${b.id}:p${k}:k0:label`),
          it.delta && h("span", { class: `cv-delta ${/^[-−]/.test(it.delta) ? "is-down" : "is-up"}`, text: it.delta }),
          !sideImg && text.length ? h("div", { class: "cv-fig-rest" }, textParts(b, text)) : null,
        ),
        sideImg ? picture(doc, b, sideImg, { cls: "cv-half" }) : null,
        foot(),
      );
    }
    case "kpis":
      return shell([
        h(
          "div",
          { class: `cv-kpis n${main.items.length}` },
          main.items.slice(0, 4).map((it, i) =>
            h(
              "div",
              { class: "cv-kpi" },
              editable("strong", "cv-kpi-value", it.value, `${b.id}:p${k}:k${i}:value`),
              editable("span", "cv-kpi-label", it.label, `${b.id}:p${k}:k${i}:label`),
              it.delta && h("span", { class: `cv-delta ${/^[-−]/.test(it.delta) ? "is-down" : "is-up"}`, text: it.delta }),
            ),
          ),
        ),
        textParts(b, text),
      ]);
    case "versus":
    case "compare": {
      const cols = columnsOf(b).slice(0, layout === "versus" ? 2 : 3);
      const own = main && main.t === "compare";
      return shell(
        h(
          "div",
          { class: `cv-cols cv-${layout} n${cols.length}` },
          cols.map((c, j) =>
            h(
              "div",
              { class: "cv-col" },
              own
                ? editable("h4", "cv-col-title", c.title, `${b.id}:p${k}:c${j}:title`)
                : h("h4", { class: "cv-col-title", text: c.title }),
              h(
                "ul",
                { class: "cv-list" },
                (c.items || []).map((x, i) =>
                  own ? editable("li", "", x, `${b.id}:p${k}:c${j}:i${i}`) : h("li", { text: x }),
                ),
              ),
            ),
          ),
          layout === "versus" && cols.length === 2 ? h("span", { class: "cv-vs", "aria-hidden": "true", text: "VS" }) : null,
        ),
      );
    }
    case "steps":
    case "cards": {
      const items = itemsOf(b).slice(0, 6);
      const own = main && (main.t === "steps" || main.t === "cards");
      return shell(
        h(
          "ol",
          { class: `cv-${layout} n${items.length}` },
          items.map((it, i) =>
            h(
              "li",
              null,
              h("span", {
                class: "cv-step-n",
                "aria-hidden": "true",
                text: layout === "steps" ? String(i + 1) : (it.title || "?").trim().slice(0, 1).toUpperCase(),
              }),
              own
                ? editable("strong", "cv-step-t", it.title, `${b.id}:p${k}:s${i}:title`)
                : h("strong", { class: "cv-step-t", text: it.title }),
              it.text
                ? own
                  ? editable("span", "cv-step-d", it.text, `${b.id}:p${k}:s${i}:text`)
                  : h("span", { class: "cv-step-d", text: it.text })
                : null,
            ),
          ),
        ),
      );
    }
    case "timeline":
      return shell(
        h(
          "ol",
          { class: `cv-timeline n${main.items.length}` },
          main.items.map((it, i) =>
            h(
              "li",
              null,
              h("span", { class: "cv-dot", "aria-hidden": "true" }),
              editable("strong", "cv-when", it.when, `${b.id}:p${k}:t${i}:when`),
              editable("span", "cv-what", it.what, `${b.id}:p${k}:t${i}:what`),
            ),
          ),
        ),
      );
    case "quote":
      return h(
        "div",
        { class: `cv-slide cv-L-quote${sideImg ? " has-img" : ""}`, "data-layout": layout },
        title("cv-slide-title cv-eyebrow"),
        h(
          "div",
          { class: "cv-slide-body" },
          h(
            "blockquote",
            { class: "cv-quote" },
            editable("p", "", main.text, `${b.id}:p${k}:text`, { multiline: true }),
            main.by ? editable("cite", "", main.by, `${b.id}:p${k}:by`) : null,
          ),
        ),
        sideImg ? picture(doc, b, sideImg, { cls: "cv-half" }) : null,
        foot(),
      );
    case "image-grid":
      return shell(h("div", { class: `cv-grid n${imgs.length}` }, imgs.slice(0, 4).map((p) => picture(doc, b, p))));
    case "chart":
      return shell(
        h(
          "div",
          { class: `cv-chart-slide${text.length ? " has-msg" : ""}` },
          chartBox(main, doc.theme),
          text.length ? h("div", { class: "cv-takeaway" }, textParts(b, text)) : null,
        ),
      );
    case "table":
      return shell(tableOf(b, main, k));
    case "code":
      return shell(h("pre", { class: "cv-code-slide" }, h("code", { text: main.text })));
  }
  return shell(textParts(b, text));
}

function textParts(b, parts) {
  return parts.map((p) => {
    const k = b.parts.indexOf(p);
    if (p.t === "list")
      return h(
        p.ordered ? "ol" : "ul",
        { class: "cv-list" },
        p.items.map((it, i) =>
          editable(
            "li",
            it.startsWith("  ") ? "cv-sub" : "",
            it.trim(),
            `${b.id}:p${k}:i${i}`,
          ),
        ),
      );
    if (p.t === "callout")
      return h(
        "div",
        { class: `cv-callout cv-tone-${p.tone || "info"}` },
        editable("p", "", p.text, `${b.id}:p${k}:text`, { multiline: true }),
      );
    if (p.t === "heading")
      return editable("h4", "cv-subhead", p.text, `${b.id}:p${k}:text`);
    return editable("p", "cv-para", p.text, `${b.id}:p${k}:text`, {
      multiline: true,
    });
  });
}

function chartBox(p, theme) {
  const pal = PALETTES[theme] || PALETTES.corporate;
  const ch = {
    t: p.type,
    u: p.unit || "",
    cats: p.rows.map((r) => String(r[0])),
    ser: p.columns.slice(1).map((n, j) => ({
      n,
      v: p.rows.map((r) => (typeof r[j + 1] === "number" ? r[j + 1] : 0)),
    })),
    pal,
  };
  const svg = chartSvg(ch, 960, 420);
  svg.setAttribute("role", "img");
  svg.removeAttribute("aria-hidden");
  svg.setAttribute(
    "aria-label",
    `${p.title || ""} ${p.rows.map((r) => `${r[0]} ${r.slice(1).join(" ")}`).join(", ")}`.slice(
      0,
      300,
    ),
  );
  return h("div", { class: "cv-chart" }, svg);
}

function tableOf(b, p, k) {
  const rows = p.rows || [];
  return h(
    "div",
    { class: "cv-table-wrap" },
    h(
      "table",
      { class: "cv-table" },
      rows.length
        ? h(
            "thead",
            null,
            h(
              "tr",
              null,
              rows[0].map((c, j) =>
                editable("th", "", c, `${b.id}:p${k}:r0:c${j}`),
              ),
            ),
          )
        : null,
      h(
        "tbody",
        null,
        rows.slice(1).map((r, i) =>
          h(
            "tr",
            null,
            r.map((c, j) =>
              editable(
                "td",
                /^[-+−]?[\d\s ,.]+\s?(?:%|€|k€|M€|\$)?$/.test(c)
                  ? "is-num"
                  : "",
                c,
                `${b.id}:p${k}:r${i + 1}:c${j}`,
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

// ------------------------------------------------------------------ the document

function docView(a, doc) {
  const page = h(
    "article",
    { class: "cv-page" },
    h(
      "header",
      { class: "cv-page-head" },
      h("span", { class: "cv-page-kind", text: t("cv.kind.doc") }),
      editable("h3", "cv-page-title", doc.title, "title", {
        label: t("cv.edit.title"),
      }),
      editable(
        "p",
        `cv-page-sub${doc.subtitle ? "" : " cv-faint"}`,
        doc.subtitle || "",
        "subtitle",
      ),
      h("p", {
        class: "cv-page-date",
        text: new Date().toLocaleDateString(
          state.prefs.lang === "en" ? "en-GB" : "fr-FR",
          { day: "numeric", month: "long", year: "numeric" },
        ),
      }),
    ),
    doc.blocks.map((b, i) =>
      h(
        "section",
        {
          class: "cv-sec",
          "aria-label": b.title || t("cv.section.n", { n: i + 1 }),
        },
        blockTools(a, doc, b, i),
        editable("h4", "cv-sec-title", b.title, `${b.id}:title`, {
          label: t("cv.edit.title"),
        }),
        b.parts.map((p, k) => docPart(doc, b, p, k)),
      ),
    ),
  );
  return page;
}

function mdBlock(text, path) {
  // rendered Markdown (escaped by markdown.js); a click swaps it for the raw text, edited in place
  const box = h("div", {
    class: "cv-md cv-ed",
    tabindex: "0",
    "data-path": path,
    "data-k": `ed-${path}`,
    title: t("cv.edit.hint"),
    "aria-label": t("cv.edit.hint"),
  });
  box.innerHTML = renderMarkdown(text);
  const start = () => {
    if (box.isContentEditable || art(view.aid)?.draft) return;
    const raw = h("p", { class: "cv-para" });
    raw.textContent = text;
    box.replaceChildren(raw);
    box.classList.add("is-raw");
    const ed = editable("p", "cv-para", text, path, { multiline: true });
    box.replaceChildren(ed);
    ed.click();
  };
  box.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    start();
  });
  box.addEventListener("keydown", (e) => {
    if (e.target === box && (e.key === "Enter" || e.key === "F2")) {
      e.preventDefault();
      start();
    }
  });
  return box;
}

function docPart(doc, b, p, k) {
  const path = `${b.id}:p${k}`;
  if (p.t === "text") return mdBlock(p.text, `${path}:text`);
  if (p.t === "heading")
    return editable("h5", "cv-subhead", p.text, `${path}:text`);
  if (p.t === "list") return textParts(b, [p]);
  if (p.t === "callout") return textParts(b, [p]);
  if (p.t === "quote")
    return h(
      "blockquote",
      { class: "cv-quote cv-quote-doc" },
      editable("p", "", p.text, `${path}:text`, { multiline: true }),
      p.by ? editable("cite", "", p.by, `${path}:by`) : null,
    );
  if (p.t === "kpi")
    return h(
      "div",
      { class: "cv-kpis cv-kpis-doc" },
      p.items.map((it, i) =>
        h(
          "div",
          { class: "cv-kpi" },
          editable("strong", "cv-kpi-value", it.value, `${path}:k${i}:value`),
          editable("span", "cv-kpi-label", it.label, `${path}:k${i}:label`),
          it.delta &&
            h("span", {
              class: `cv-delta ${/^[-−]/.test(it.delta) ? "is-down" : "is-up"}`,
              text: it.delta,
            }),
        ),
      ),
    );
  if (p.t === "table") return tableOf(b, p, k);
  if (p.t === "timeline")
    return h(
      "ol",
      { class: "cv-steps" },
      p.items.map((it, i) =>
        h(
          "li",
          null,
          editable("strong", "", it.when, `${path}:t${i}:when`),
          " ",
          editable("span", "", it.what, `${path}:t${i}:what`),
        ),
      ),
    );
  if (p.t === "chart")
    return h(
      "figure",
      { class: "cv-figure" },
      chartBox(p, doc.theme),
      p.title ? h("figcaption", { text: p.title }) : null,
    );
  if (p.t === "image") return picture(doc, b, p, { cls: "cv-figure" });
  if (p.t === "code")
    return h("pre", { class: "cv-pre" }, h("code", { text: p.text }));
  return null;
}

// ------------------------------------------------------------------ code

const PREVIEW = new Set(["html", "svg", "js", "css", "mermaid", "markdown"]);

function wrapForFrame(lang, code) {
  if (lang === "html")
    return /<html|<!doctype/i.test(code)
      ? code
      : `<!doctype html><meta charset="utf-8"><body>${code}</body>`;
  if (lang === "svg")
    return `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;height:100%;display:grid;place-items:center;background:#fff}svg{max-width:100%;max-height:100vh}</style>${code}`;
  if (lang === "css")
    return `<!doctype html><meta charset="utf-8"><style>${code.replace(/<\/style/gi, "<\\/style")}</style><body><h1>Titre</h1><p>Paragraphe <a href="#">lien</a></p><button>Bouton</button></body>`;
  if (lang === "js")
    return `<!doctype html><meta charset="utf-8"><body><script>${code.replace(/<\/script/gi, "<\\/script")}</script></body>`;
  return "";
}

function codeView(a, doc) {
  const lang = doc.code?.lang || "text";
  const code = String(doc.code?.text || "");
  // while the file streams the code is shown as it comes; once complete, the preview (unless the user chose a tab)
  if (a.draft) view.tab = "code";
  else if (!view.userTab) view.tab = PREVIEW.has(lang) ? "preview" : "code";
  const tabs = h(
    "div",
    { class: "cv-tabs", role: "tablist", "aria-label": t("cv.kind.code") },
    [
      ["preview", t("cv.tab.preview")],
      ["code", t("cv.tab.code")],
    ].map(([id, label]) =>
      h(
        "button",
        {
          type: "button",
          role: "tab",
          id: `cv-tab-${id}`,
          class: "cv-tab",
          "aria-selected": String(view.tab === id),
          "aria-controls": `cv-pane-${id}`,
          tabindex: view.tab === id ? "0" : "-1",
          "data-k": `tab-${id}`,
          disabled: id === "preview" && !!a.draft,
          onclick: () => {
            view.tab = id;
            view.userTab = true;
            render();
            panel.querySelector(`#cv-tab-${id}`)?.focus();
          },
          onkeydown: (e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
              view.userTab = true;
              view.tab = view.tab === "preview" ? "code" : "preview";
              render();
              panel.querySelector(`#cv-tab-${view.tab}`)?.focus();
            }
          },
        },
        label,
      ),
    ),
    h("span", { class: "cv-lang", text: lang.toUpperCase() }),
  );
  const pane =
    view.tab === "preview"
      ? previewPane(a, doc, lang, code)
      : codePane(a, doc, lang, code);
  return h("div", { class: "cv-body cv-codebody" }, tabs, pane);
}

function codePane(a, doc, lang, code) {
  const area = h("textarea", {
    class: "cv-code",
    spellcheck: "false",
    "aria-label": t("cv.code.label"),
    "aria-description": t("cv.code.tabhint"),
    "data-k": "code",
    readonly: !!a.draft,
    wrap: "off",
  });
  area.value = view.codeDraft ?? code;
  const apply = button(
    "btn-primary btn-small",
    "check",
    t("cv.code.apply"),
    () => {
      const value = area.value;
      view.codeDraft = null;
      commit((d) => {
        if (d.code.text === value) return false;
        d.code.text = value.slice(0, 60000);
      }, t("cv.label.code"));
    },
    { disabled: true, "data-k": "apply" },
  );
  const note = h("span", { class: "cv-muted", "aria-live": "polite" });
  area.addEventListener("input", () => {
    view.codeDraft = area.value;
    apply.disabled = area.value === code;
    note.textContent = area.value === code ? "" : t("cv.code.changed");
  });
  // Tab indents, as in a code editor; Escape releases it (the next Tab leaves the field), as in most editors
  let tabFree = false;
  area.addEventListener("focus", () => (tabFree = false));
  area.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      tabFree = true;
      announce(t("cv.code.tabfree"));
      return;
    }
    if (e.key !== "Tab") tabFree = false;
    if (
      !tabFree &&
      e.key === "Tab" &&
      !e.shiftKey &&
      !e.ctrlKey &&
      !e.altKey &&
      !e.metaKey
    ) {
      e.preventDefault();
      area.setRangeText("  ", area.selectionStart, area.selectionEnd, "end");
      area.dispatchEvent(new Event("input"));
    }
  });
  if (view.codeDraft !== null && view.codeDraft !== code) {
    apply.disabled = false;
    note.textContent = t("cv.code.changed");
  }
  const check = ["python", "json"].includes(lang)
    ? h("p", { class: "cv-check", role: "status" })
    : null;
  if (check && !a.draft) runCheck(lang, code, check);
  return h(
    "div",
    {
      class: "cv-pane",
      id: "cv-pane-code",
      role: "tabpanel",
      "aria-labelledby": "cv-tab-code",
    },
    area,
    h("div", { class: "cv-code-bar" }, apply, note),
    check,
    !PREVIEW.has(lang) && h("p", { class: "cv-muted", text: t("cv.noexec") }),
  );
}

async function runCheck(lang, code, out) {
  try {
    const r = await fetch("/api/canvas/check", {
      method: "POST",
      headers: { ...handlers.headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ lang, code: code.slice(0, 60000) }),
    });
    const v = await r.json();
    if (v.ok) {
      out.textContent = t("cv.check.ok");
      out.className = "cv-check is-ok";
    } else if (v.kind === "error") {
      out.replaceChildren(
        h("span", { text: t("cv.check.bad", { line: v.line, msg: v.msg }) }),
        button(
          "btn-outline btn-small",
          "spark",
          t("cv.fix"),
          () => handlers.send(t("cv.check.fix", { line: v.line, msg: v.msg })),
          { "data-k": "fix-check" },
        ),
      );
      out.className = "cv-check is-bad";
    }
  } catch {
    /* offline: no verdict */
  }
}

function previewPane(a, doc, lang, code) {
  const pane = h("div", {
    class: "cv-pane cv-preview",
    id: "cv-pane-preview",
    role: "tabpanel",
    "aria-labelledby": "cv-tab-preview",
  });
  if (lang === "mermaid") {
    const svg = flowSvg(parseFlow(code), { title: doc.title });
    pane.append(
      svg
        ? h("div", { class: "cv-flow" }, svg)
        : h(
            "div",
            { class: "cv-flow-bad" },
            h("p", { text: t("cv.flow.bad") }),
            button(
              "btn-outline btn-small",
              "spark",
              t("cv.fix"),
              () => handlers.send(t("cv.flow.fix")),
              { "data-k": "fix-flow" },
            ),
          ),
    );
    return pane;
  }
  if (lang === "markdown") {
    const md = h("div", { class: "cv-page cv-md-preview" });
    md.innerHTML = renderMarkdown(code);
    pane.append(md);
    return pane;
  }
  const html = wrapForFrame(lang, code);
  view.frameHtml = html;
  view.console = view.console || [];
  const frame = h("iframe", {
    class: "cv-frame",
    src: "/canvas/frame",
    sandbox: "allow-scripts",
    referrerpolicy: "no-referrer",
    title: `${t("cv.tab.preview")} — ${doc.title || ""}`,
    loading: "eager",
  });
  pane.append(
    frame,
    h("p", { class: "cv-muted cv-sandbox", text: t("cv.sandbox") }),
    consoleBox(),
  );
  return pane;
}

function consoleBox() {
  const list = view.console.slice(-30);
  const err = list.find((m) => m.level === "error");
  return h(
    "details",
    { class: "cv-console", open: !!err },
    h("summary", null, t("cv.console"), list.length ? ` (${list.length})` : ""),
    list.length
      ? h(
          "ul",
          null,
          list.map((m) => h("li", { class: `is-${m.level}`, text: m.text })),
        )
      : h("p", { class: "cv-muted", text: t("cv.console.empty") }),
    err &&
      button(
        "btn-outline btn-small",
        "spark",
        t("cv.fix"),
        () => handlers.send(t("cv.fix.msg", { err: err.text.slice(0, 300) })),
        { "data-k": "fix-console" },
      ),
  );
}

function onFrameMessage(e) {
  const frame = panel?.querySelector(".cv-frame");
  if (
    !frame ||
    e.source !== frame.contentWindow ||
    !e.data ||
    typeof e.data !== "object"
  )
    return;
  if (e.data.bird === "frame") {
    view.console = [];
    frame.contentWindow.postMessage(
      { bird: "render", html: view.frameHtml },
      "*",
    );
  } else if (e.data.bird === "console" && e.data.level !== "ready") {
    view.console.push({
      level: ["error", "warn", "log", "info"].includes(e.data.level)
        ? e.data.level
        : "log",
      text: String(e.data.text || "").slice(0, 600),
    });
    const box = panel.querySelector(".cv-console");
    if (box) box.replaceWith(consoleBox());
  }
}

// ------------------------------------------------------------------ the mini-sheet

function sheetView(a, doc) {
  const sh = doc.sheet || { columns: [], rows: [] };
  const values = sheet.compute(sh.rows);
  const sel = view.sel || { r0: 0, c0: 0, r1: 0, c1: 0, r: 0, c: 0 };
  view.sel = sel;
  const inSel = (r, c) =>
    r >= Math.min(sel.r0, sel.r1) &&
    r <= Math.max(sel.r0, sel.r1) &&
    c >= Math.min(sel.c0, sel.c1) &&
    c <= Math.max(sel.c0, sel.c1);
  const norm = () => ({
    r0: Math.min(sel.r0, sel.r1),
    r1: Math.max(sel.r0, sel.r1),
    c0: Math.min(sel.c0, sel.c1),
    c1: Math.max(sel.c0, sel.c1),
  });
  const ref = sheet.cellName(sel.r, sel.c);
  const bar = h("input", {
    class: "cv-fx",
    type: "text",
    "aria-label": t("cv.sheet.formula"),
    "data-k": "fx",
    value: sh.rows[sel.r]?.[sel.c] ?? "",
    placeholder: t("cv.sheet.help"),
    readonly: !!a.draft,
  });
  const setCell = (r, c, value) =>
    commit((d) => {
      const rows = d.sheet.rows;
      while (rows.length <= r) rows.push(d.sheet.columns.map(() => ""));
      if ((rows[r][c] ?? "") === value) return false;
      rows[r][c] = value.slice(0, 1000);
    }, t("cv.label.sheet"));
  bar.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      setCell(sel.r, sel.c, bar.value);
      move(1, 0);
    } else if (e.key === "Escape") {
      bar.value = sh.rows[sel.r]?.[sel.c] ?? "";
      panel.querySelector(".cv-grid")?.focus();
    }
  });
  const move = (dr, dc, extend = false) => {
    const r = Math.max(0, Math.min(sh.rows.length - 1, sel.r + dr));
    const c = Math.max(0, Math.min(sh.columns.length - 1, sel.c + dc));
    view.sel = extend
      ? { ...sel, r1: r, c1: c, r, c }
      : { r0: r, c0: c, r1: r, c1: c, r, c };
    render();
    panel.querySelector(".cv-grid")?.focus({ preventScroll: true });
    panel
      .querySelector(".cv-grid td.is-cur")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };
  const grid = h(
    "table",
    {
      class: "cv-grid",
      tabindex: "0",
      role: "grid",
      "aria-label": doc.title || t("cv.kind.sheet"),
      "aria-rowcount": String(sh.rows.length + 1),
      "aria-colcount": String(sh.columns.length),
      "data-k": "grid",
      "aria-activedescendant": `cv-c-${sel.r}-${sel.c}`,
      onkeydown: (e) => {
        const keys = {
          ArrowUp: [-1, 0],
          ArrowDown: [1, 0],
          ArrowLeft: [0, -1],
          ArrowRight: [0, 1],
        };
        if (keys[e.key]) {
          e.preventDefault();
          move(...keys[e.key], e.shiftKey);
        } else if (e.key === "Enter" || e.key === "F2") {
          e.preventDefault();
          panel.querySelector(".cv-fx")?.focus();
        } else if (e.key === "Delete" || e.key === "Backspace") {
          e.preventDefault();
          setCell(sel.r, sel.c, "");
        } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !a.draft) {
          const fx = panel.querySelector(".cv-fx");
          fx.value = "";
          fx.focus();
        }
      },
    },
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        h("th", { class: "cv-corner", "aria-hidden": "true" }),
        sh.columns.map((c, j) =>
          h(
            "th",
            {
              scope: "col",
              "aria-sort":
                view.sort?.c === j
                  ? view.sort.dir > 0
                    ? "ascending"
                    : "descending"
                  : null,
            },
            h("span", { class: "cv-colletter", text: sheet.colName(j) }),
            editable("span", "cv-colname", c, `col:${j}`),
          ),
        ),
      ),
    ),
    h(
      "tbody",
      null,
      sh.rows.map((row, r) =>
        h(
          "tr",
          null,
          h("th", { scope: "row", class: "cv-rownum", text: String(r + 1) }),
          row.map((raw, c) => {
            const v = values[r]?.[c];
            const shown = typeof v === "number" ? fmtNum(v) : String(v ?? "");
            return h("td", {
              id: `cv-c-${r}-${c}`,
              role: "gridcell",
              class: [
                typeof v === "number" ? "is-num" : "",
                sheet.isError(v) ? "is-err" : "",
                String(raw).startsWith("=") ? "is-fx" : "",
                inSel(r, c) ? "is-sel" : "",
                r === sel.r && c === sel.c ? "is-cur" : "",
              ]
                .filter(Boolean)
                .join(" "),
              "aria-selected": String(inSel(r, c)),
              title: String(raw).startsWith("=") ? String(raw) : null,
              onmousedown: (e) => {
                e.preventDefault();
                view.sel = e.shiftKey
                  ? { ...sel, r1: r, c1: c, r, c }
                  : { r0: r, c0: c, r1: r, c1: c, r, c };
                render();
                panel.querySelector(".cv-grid")?.focus({ preventScroll: true });
              },
              ondblclick: () => panel.querySelector(".cv-fx")?.focus(),
              text: shown,
            });
          }),
        ),
      ),
    ),
  );
  // header names are edited in place (path "col:j")
  grid.querySelectorAll(".cv-colname").forEach((el) => {
    el.addEventListener("keydown", (e) => e.stopPropagation());
  });
  const tools = h(
    "div",
    {
      class: "cv-sheet-tools",
      role: "toolbar",
      "aria-label": t("cv.kind.sheet"),
    },
    h("span", {
      class: "cv-ref",
      text: ref,
      "aria-label": t("cv.sheet.cell", { ref }),
    }),
    bar,
    button(
      "btn-quiet btn-icon btn-small cv-up",
      "down",
      t("cv.sheet.sort.asc"),
      () => sortBy(sel.c, 1),
      { disabled: !!a.draft, "data-k": "sort-asc" },
    ),
    button(
      "btn-quiet btn-icon btn-small",
      "down",
      t("cv.sheet.sort.desc"),
      () => sortBy(sel.c, -1),
      { disabled: !!a.draft, "data-k": "sort-desc" },
    ),
    button(
      "btn-outline btn-small",
      "make_chart",
      t("cv.sheet.chart"),
      () => {
        const spec = sheet.chartFrom(
          sh.columns,
          values,
          norm(),
          doc.title || "",
        );
        if (!spec) return toast(t("cv.sheet.chart.none"), "error");
        view.chart = spec;
        render();
      },
      { "data-k": "chart" },
    ),
    button(
      "btn-outline btn-small",
      "spark",
      t("cv.ask"),
      () => {
        const table = sheet.selectionMarkdown(sh.columns, values, norm());
        handlers.compose?.(
          t("cv.sheet.ask", { title: doc.title || "", table }),
        );
      },
      { "data-k": "ask-sheet" },
    ),
    button(
      "btn-quiet btn-icon btn-small",
      "plus",
      t("cv.sheet.addrow"),
      () =>
        commit((d) => {
          if (d.sheet.rows.length >= sheet.MAX_ROWS) return false;
          d.sheet.rows.push(d.sheet.columns.map(() => ""));
        }, t("cv.label.sheet")),
      { disabled: !!a.draft, "data-k": "addrow" },
    ),
    button(
      "btn-quiet btn-small",
      "plus",
      sheet.colName(sh.columns.length),
      () =>
        commit((d) => {
          if (d.sheet.columns.length >= sheet.MAX_COLS) return false;
          d.sheet.columns.push(sheet.colName(d.sheet.columns.length));
          d.sheet.rows.forEach((r) => r.push(""));
        }, t("cv.label.sheet")),
      {
        disabled: !!a.draft,
        "aria-label": t("cv.sheet.addcol"),
        title: t("cv.sheet.addcol"),
        "data-k": "addcol",
      },
    ),
  );
  const chart = view.chart
    ? renderChart(view.chart, { lang: state.prefs.lang === "en" ? "en" : "fr" })
    : null;
  return h(
    "div",
    { class: "cv-body cv-sheetbody" },
    tools,
    h("div", { class: "cv-grid-wrap" }, grid),
    chart && h("div", { class: "cv-sheet-chart" }, chart),
  );
}

function sortBy(col, dir) {
  commit((d) => {
    const values = sheet.compute(d.sheet.rows);
    d.sheet.rows = sheet.sortRows(d.sheet.rows, values, col, dir);
  }, t("cv.label.sheet"));
  view.sort = { c: col, dir };
  if (
    art(view.aid) &&
    current(art(view.aid)).sheet.rows.some((r) =>
      r.some((x) => String(x).startsWith("=")),
    )
  )
    toast(t("cv.sheet.sorted"));
}

const fmtNum = (v) =>
  new Intl.NumberFormat(state.prefs.lang === "en" ? "en-GB" : "fr-FR", {
    maximumFractionDigits: 6,
  }).format(v);

// ------------------------------------------------------------------ print (PDF)

function printDoc(doc) {
  const kind = doc.kind;
  const old = document.getElementById("cv-print");
  old?.remove();
  const a = art(view.aid);
  const box = h(
    "div",
    {
      id: "cv-print",
      class: `cv-print cv-print-${kind} cvt-${doc.theme || "corporate"}`,
    },
    kind === "deck"
      ? deckView({ ...a, draft: null }, doc)
      : docView({ ...a, draft: null }, doc),
  );
  box.querySelectorAll(".cv-block-tools").forEach((x) => x.remove());
  box
    .querySelectorAll("[tabindex]")
    .forEach((x) => x.removeAttribute("tabindex"));
  document.body.append(box);
  document.documentElement.classList.add("cv-printing");
  const done = () => {
    document.documentElement.classList.remove("cv-printing");
    box.remove();
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.setTimeout(() => window.print(), 50);
}
