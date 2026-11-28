// The answer content beyond Markdown (cluster C2 of the chat audit): typeset math, citation bubbles and the sources
// pill, rich copy (text/html + text/plain), the thumbs-down reasons, the work line. Strings: answers-i18n.js.
//
// Math: markdown.js leaves a placeholder per formula (data-tex, its source as written). typeset() loads the
// self-hosted KaTeX (static/vendor/katex, MIT, licence in « À propos ») the first time an answer has one, renders
// every placeholder in place and keeps the source for copying. The page's CSP forbids inline style attributes, so
// KaTeX's are moved to data-kx-style and applied through the CSSOM. Nothing is fetched from a third party.
import { copyText, icon, t, toast } from "./core.js";

export const KATEX = "/static/vendor/katex/katex.min.js";
export const KATEX_CSS = "/static/vendor/katex/katex.min.css";

/** KaTeX's HTML for one formula, its inline styles moved to data-kx-style (applied by applyStyles). Throws on bad TeX. */
export function katexHtml(katex, tex, display) {
  const html = katex.renderToString(String(tex), {
    displayMode: Boolean(display),
    throwOnError: true,
    strict: "ignore",
    trust: false, // no \href, \url, \htmlClass…: a formula never makes a link or an attribute
    output: "htmlAndMathml", // MathML for screen readers, HTML for the eye
    maxSize: 20,
    maxExpand: 300,
  });
  return html.replace(/ style="([^"]*)"/g, ' data-kx-style="$1"');
}

function applyStyles(root) {
  for (const el of root.querySelectorAll("[data-kx-style]")) {
    el.style.cssText = el.getAttribute("data-kx-style");
    el.removeAttribute("data-kx-style");
  }
}

let loading = null;
function loadKatex() {
  if (globalThis.katex?.renderToString) return Promise.resolve(globalThis.katex);
  if (!loading) {
    if (!document.querySelector(`link[href="${KATEX_CSS}"]`))
      document.head.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href: KATEX_CSS }));
    // the UMD build sets self.katex when imported as a module
    loading = import(KATEX).then(
      () => globalThis.katex || null,
      () => ((loading = null), null), // offline or blocked: the formulas stay as written, retried next time
    );
  }
  return loading;
}

/** Typeset every formula placeholder under root (idempotent: a typeset formula is left alone). */
export async function typeset(root) {
  const nodes = [...root.querySelectorAll(".md-math:not([data-typeset]):not([data-pending])")];
  if (!nodes.length) return 0;
  const katex = await loadKatex();
  if (!katex) return 0;
  let done = 0;
  for (const el of nodes) {
    if (!el.isConnected || el.hasAttribute("data-typeset")) continue;
    try {
      const out = document.createElement("span");
      out.className = "md-math-out";
      out.innerHTML = katexHtml(katex, el.dataset.tex, el.hasAttribute("data-display"));
      applyStyles(out);
      el.prepend(out);
      el.dataset.typeset = "1";
      done += 1;
    } catch {
      // TeX KaTeX does not know: shown as written, never a red error in the answer
      el.dataset.typeset = "raw";
      el.title = t("md.math.raw");
    }
  }
  return done;
}

/** The TeX of a formula placeholder as the reader copies it: delimiters included. */
export function texOf(el) {
  const tex = el.getAttribute("data-tex") || "";
  return el.hasAttribute("data-display") ? `$$${tex}$$` : `$${tex}$`;
}

/**
 * A copied selection that holds formulas gives their TeX, never KaTeX's glyph soup (« 6CO2​+6H2​O »). A selection
 * inside one formula copies the whole formula.
 */
function onCopy(e) {
  const sel = globalThis.getSelection?.();
  if (!sel || sel.isCollapsed || !sel.rangeCount || !e.clipboardData) return;
  const range = sel.getRangeAt(0);
  const node = range.commonAncestorContainer;
  const within = (node.nodeType === 1 ? node : node.parentElement)?.closest?.(".md-math[data-typeset]");
  if (within) {
    e.clipboardData.setData("text/plain", texOf(within));
    e.preventDefault();
    return;
  }
  const frag = range.cloneContents();
  const maths = frag.querySelectorAll(".md-math");
  if (!maths.length) return;
  for (const m of maths) m.replaceWith(document.createTextNode(texOf(m)));
  const box = document.createElement("div");
  box.className = "md-copy-box";
  box.append(frag);
  document.body.append(box);
  const text = box.innerText;
  const html = box.innerHTML;
  box.remove();
  e.clipboardData.setData("text/plain", text);
  e.clipboardData.setData("text/html", html);
  e.preventDefault();
}

function onClick(e) {
  const btn = e.target.closest?.("[data-copy-tex]");
  if (!btn) return;
  const el = btn.closest(".md-math");
  if (el) copyText(texOf(el), t("md.math.copied"));
}

// ------------------------------------------------------------------ rich copy (text/html + text/plain)
// « Copier » puts the answer on the clipboard twice: as HTML (headings, bold, lists and real tables land as such in
// Word, Outlook or Google Docs) and as plain text (Markdown-like, tables as | a | b |). Built from the rendered answer
// with an allow-list of tags: no class, no script, no style of ours; the formulas as their TeX, [n] as text.

const CHROME = /(?:^|\s)(?:code-head|code-more|md-more|md-chip-copy|md-math-copy|md-math-out|sr-only|cite-bubble|tplan-head-icon)(?:\s|$)/;
const KEEP = new Set(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th",
  "td", "pre", "code", "blockquote", "strong", "em", "a", "br", "hr", "del", "dl", "dt", "dd"]);
const ALIAS = { b: "strong", i: "em", s: "del" };
const BLOCK = new Set(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "li", "table", "tr", "pre", "blockquote", "hr",
  "dl", "dt", "dd", "div", "section", "figure", "figcaption", "details", "summary", "aside"]);

/** A plain tree of the rendered answer ({tag, attrs, children} or {text}), without the interface's chrome. */
export function treeOf(node) {
  if (node.nodeType === 3) return { text: node.nodeValue };
  if (node.nodeType !== 1) return null;
  const tag = node.tagName.toLowerCase();
  const cls = node.getAttribute("class") || "";
  if (["svg", "script", "style", "template", "img"].includes(tag) || CHROME.test(cls)) return null;
  if (node.getAttribute("aria-hidden") === "true") return null;
  if (/(?:^|\s)md-math(?:\s|$)/.test(cls)) return { text: texOf(node) };
  if (tag === "sup" && /(?:^|\s)cite(?:\s|$)/.test(cls)) return { text: `[${node.textContent.trim()}]` };
  if (tag === "figure" && /code-block/.test(cls)) {
    const code = (node.querySelector("pre code")?.textContent || "").replace(/\n$/, "");
    return { tag: "pre", attrs: {}, children: [{ tag: "code", attrs: {}, children: [{ text: code }] }] };
  }
  if (tag === "input") return node.type === "checkbox" ? { text: node.checked ? "☑ " : "☐ " } : null;
  const attrs = {};
  if (tag === "a" && /^https?:\/\//i.test(node.getAttribute("href") || "")) attrs.href = node.getAttribute("href");
  if (tag === "ol" && node.getAttribute("start")) attrs.start = node.getAttribute("start");
  if ((tag === "td" || tag === "th") && /\b(?:md-num|al-right)\b/.test(cls)) attrs.align = "right";
  return { tag, attrs, children: [...node.childNodes].map(treeOf).filter(Boolean) };
}

const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function htmlOf(n) {
  if (n.text !== undefined) return esc(n.text);
  const inner = n.children.map(htmlOf).join("");
  const tag = ALIAS[n.tag] || n.tag;
  if (!KEEP.has(tag)) return BLOCK.has(tag) && !inner.trim().startsWith("<") ? `<p>${inner}</p>` : inner;
  if (tag === "br" || tag === "hr") return `<${tag}>`;
  if (tag === "a") return n.attrs.href ? `<a href="${esc(n.attrs.href)}">${inner}</a>` : inner;
  // presentational attributes, not style="": the browser sanitises the copied HTML under the page's CSP (no inline
  // style), and Word, Outlook and Google Docs read border / cellpadding / align / bgcolor
  if (tag === "table") return `<table border="1" cellspacing="0" cellpadding="6">${inner}</table>`;
  if (tag === "th") return `<th align="left" valign="top" bgcolor="#eceae2">${inner}</th>`;
  if (tag === "td") return `<td valign="top"${n.attrs.align ? ' align="right"' : ""}>${inner}</td>`;
  if (tag === "ol" && n.attrs.start) return `<ol start="${esc(n.attrs.start)}">${inner}</ol>`;
  return `<${tag}>${inner}</${tag}>`;
}

const flat = (n) => (n.text !== undefined ? n.text : n.children.map(flat).join(""));
const oneLine = (s) => s.replace(/\s+/g, " ").trim();

function textOf(n, out, depth = 0) {
  if (n.text !== undefined) {
    out.push({ inline: n.text });
    return;
  }
  const tag = ALIAS[n.tag] || n.tag;
  if (tag === "br") return void out.push({ inline: "\n" });
  if (tag === "hr") return void out.push({ block: "---" });
  if (tag === "pre") return void out.push({ block: flat(n) });
  if (tag === "table") {
    const rows = [];
    const walk = (x) => (x.tag === "tr" ? rows.push(x) : (x.children || []).forEach(walk));
    walk(n);
    const lines = rows.map((r) => `| ${r.children.filter((c) => c.tag === "th" || c.tag === "td").map((c) => oneLine(flat(c)).replace(/\|/g, "\\|")).join(" | ")} |`);
    if (rows[0]?.children.some((c) => c.tag === "th")) {
      const cols = rows[0].children.filter((c) => c.tag === "th").length;
      lines.splice(1, 0, `| ${Array(cols).fill("---").join(" | ")} |`);
    }
    return void out.push({ block: lines.join("\n") });
  }
  if (tag === "ul" || tag === "ol") {
    let k = Number(n.attrs.start || 1);
    const items = n.children.filter((c) => c.tag === "li");
    const lines = items.map((li) => {
      const sub = [];
      for (const c of li.children) textOf(c, sub, depth + 1);
      const body = join(sub).replace(/\n(?!\s*$)/g, "\n  ");
      return `${"  ".repeat(depth)}${tag === "ol" ? `${k++}.` : "-"} ${body}`;
    });
    return void out.push({ block: lines.join("\n") });
  }
  const sub = [];
  for (const c of n.children) textOf(c, sub, depth);
  if (BLOCK.has(tag) || KEEP.has(tag) && /^h\d$/.test(tag)) out.push({ block: join(sub) });
  else out.push(...sub);
}

function join(parts) {
  let text = "";
  let pending = "";
  for (const p of parts) {
    if (p.block !== undefined) {
      const b = p.block.trim();
      if (!b) continue;
      text = `${text.trimEnd()}${text.trim() ? "\n\n" : ""}${b}`;
      pending = "\n\n";
    } else {
      text += pending && p.inline.trim() ? pending : "";
      pending = "";
      text += p.inline;
    }
  }
  return text.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** {html, text} of a plain tree: the two flavours « Copier » writes. */
export function serialize(tree) {
  const out = [];
  for (const c of tree.children || [tree]) textOf(c, out);
  const body = (tree.children || [tree]).map(htmlOf).join("");
  return { html: `<meta charset="utf-8">${body}`, text: join(out) };
}

/** Write both flavours; true when the clipboard took them (ClipboardItem, else plain text, else execCommand). */
export async function writeRich({ html, text }) {
  try {
    if (globalThis.ClipboardItem && navigator.clipboard?.write) {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        }),
      ]);
      return true;
    }
  } catch {
    /* refused (permissions, an iframe): the plain way below */
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    /* no async clipboard: the selection way */
  }
  const box = document.createElement("div");
  box.className = "md-copy-box";
  box.setAttribute("contenteditable", "true");
  box.innerHTML = html; // our own allow-listed markup, built above from escaped text
  document.body.append(box);
  const range = document.createRange();
  range.selectNodeContents(box);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  let ok = false;
  try {
    ok = document.execCommand("copy") === true;
  } catch {
    ok = false;
  }
  sel.removeAllRanges();
  box.remove();
  return ok;
}

/**
 * The copy button's answer: the icon turns into a check for 2 s and a screen reader hears « Copié »; when the copy
 * failed, a toast says how to copy by hand. Returns whether it worked.
 */
export async function copyAnswer(button, payload) {
  const ok = await writeRich(payload);
  if (!ok) {
    toast(t("toast.copy.failed"), "error");
    return false;
  }
  if (button) {
    if (!button._resting) button._resting = { kids: [...button.childNodes], label: button.getAttribute("aria-label") };
    button.classList.add("is-copied");
    button.replaceChildren(icon("check"));
    button.setAttribute("aria-label", t("act.copied"));
    button.title = t("act.copied");
    const live = document.getElementById("live");
    if (live) live.textContent = t("act.copied");
    clearTimeout(button._copiedTimer);
    button._copiedTimer = setTimeout(() => {
      const { kids, label } = button._resting;
      button.classList.remove("is-copied");
      button.replaceChildren(...kids);
      button.setAttribute("aria-label", label);
      button.title = label;
      button._resting = null;
    }, 2000);
  }
  return true;
}

// ------------------------------------------------------------------ thumbs down: reasons and a comment
// Kept with the conversation in this browser only (there is no feedback endpoint on the server: nothing leaves the
// device). Reasons are fixed keys, the comment is plain text capped at 500 characters.

/** The one-line thank-you that follows a sent thumbs down. */
export function feedbackThanks() {
  const thanks = document.createElement("p");
  thanks.className = "fb-thanks";
  thanks.setAttribute("role", "status");
  thanks.append(icon("check"), document.createTextNode(` ${t("fb.thanks")}`));
  return thanks;
}

export const REASONS = ["wrong", "incomplete", "offtopic", "long", "format", "refusal"];

/** What is stored for a thumbs down: known reasons only, a trimmed comment, the time. */
export function cleanFeedback(raw, now = Date.now()) {
  const reasons = [...new Set((raw?.reasons || []).filter((r) => REASONS.includes(r)))];
  const comment = String(raw?.comment || "").replace(/\s+/g, " ").trim().slice(0, 500);
  return { reasons, comment, at: now };
}

/**
 * The small panel under a thumbs down: reason chips (toggle buttons), an optional comment, « Envoyer » and
 * « Fermer ». onSave(detail) stores it with the turn (the turn then shows feedbackThanks()).
 */
export function feedbackPanel(turn, { onSave, onClose }) {
  const picked = new Set(turn.feedbackDetail?.reasons || []);
  const id = `fb-${turn.id}`;
  const box = document.createElement("section");
  box.className = "fb-panel";
  box.setAttribute("aria-labelledby", `${id}-t`);
  const title = document.createElement("p");
  title.className = "fb-title";
  title.id = `${id}-t`;
  title.textContent = t("fb.title");
  const chips = document.createElement("div");
  chips.className = "fb-chips";
  chips.setAttribute("role", "group");
  chips.setAttribute("aria-labelledby", `${id}-t`);
  for (const key of REASONS) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "fb-chip";
    chip.dataset.reason = key;
    chip.textContent = t(`fb.r.${key}`);
    chip.setAttribute("aria-pressed", String(picked.has(key)));
    chip.addEventListener("click", () => {
      const on = !picked.has(key);
      if (on) picked.add(key);
      else picked.delete(key);
      chip.setAttribute("aria-pressed", String(on));
    });
    chips.append(chip);
  }
  const label = document.createElement("label");
  label.className = "fb-label";
  label.htmlFor = `${id}-c`;
  label.textContent = t("fb.comment");
  const area = document.createElement("textarea");
  area.id = `${id}-c`;
  area.className = "fb-comment";
  area.rows = 2;
  area.maxLength = 500;
  area.placeholder = t("fb.comment.ph");
  area.value = turn.feedbackDetail?.comment || "";
  const note = document.createElement("p");
  note.className = "fb-note";
  note.textContent = t("act.feedback.note");
  const row = document.createElement("div");
  row.className = "fb-row";
  const send = document.createElement("button");
  send.type = "button";
  send.className = "btn btn-primary btn-small";
  send.textContent = t("fb.send");
  send.dataset.act = "fb-send";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "btn btn-quiet btn-small";
  close.textContent = t("fb.close");
  close.dataset.act = "fb-close";
  row.append(send, close, note);
  send.addEventListener("click", () => onSave(cleanFeedback({ reasons: [...picked], comment: area.value })));
  close.addEventListener("click", () => onClose());
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    }
  });
  box.append(title, chips, label, area, row);
  return box;
}

// ------------------------------------------------------------------ citations: the bubble and the sources panel

/** Open or close the « N sources » panel that a pill controls. */
export function setSourcesOpen(pill, open) {
  const panel = pill && document.getElementById(pill.getAttribute("aria-controls"));
  if (!panel) return;
  pill.setAttribute("aria-expanded", String(open));
  panel.hidden = !open;
  pill.closest(".sources")?.classList.toggle("is-open", open);
}

/** What the bubble of citation [n] says, read from the source card it points to (never from the model's text). */
export function citeFacts(item) {
  const link = item.querySelector(".source-body > a");
  const title = (link || item.querySelector(".source-body > span"))?.textContent?.trim() || "";
  return {
    n: item.querySelector(".source-n")?.textContent?.trim() || "",
    title,
    url: link?.href || "",
    host: item.querySelector(".source-host > span:not(.source-mono):not(.badge)")?.textContent?.trim() || "",
    snippet: item.querySelector(".source-snippet")?.textContent?.trim() || "",
  };
}

let bubble = null; // {el, anchor}
let hideTimer = 0;

function hideBubble(refocus = false) {
  clearTimeout(hideTimer);
  if (!bubble) return;
  const { el, anchor } = bubble;
  anchor.removeAttribute("aria-describedby");
  anchor.setAttribute("aria-expanded", "false");
  el.remove();
  bubble = null;
  if (refocus) anchor.focus();
}

function place(el, anchor) {
  const r = anchor.getBoundingClientRect();
  const w = Math.min(320, innerWidth - 24);
  el.style.width = `${w}px`;
  const left = Math.min(Math.max(12, r.left + r.width / 2 - w / 2), innerWidth - w - 12);
  const h = el.offsetHeight;
  const above = r.top - h - 8 >= 12;
  el.style.left = `${left}px`;
  el.style.top = `${above ? r.top - h - 8 : Math.min(r.bottom + 8, innerHeight - h - 12)}px`;
  el.dataset.side = above ? "above" : "below";
}

function showBubble(anchor) {
  const item = document.getElementById(decodeURIComponent((anchor.getAttribute("href") || "").slice(1)));
  if (!item) return;
  if (bubble?.anchor === anchor) return;
  hideBubble();
  const f = citeFacts(item);
  const el = document.createElement("div");
  el.className = "cite-bubble";
  el.id = `cb-${item.id}`;
  el.setAttribute("role", "tooltip");
  const head = document.createElement("p");
  head.className = "cite-bubble-host";
  head.textContent = `${f.n} · ${f.host}`.replace(/^ · /, "");
  const title = document.createElement(f.url ? "a" : "p");
  title.className = "cite-bubble-title";
  title.textContent = f.title;
  if (f.url) Object.assign(title, { href: f.url, target: "_blank", rel: "noopener noreferrer", referrerPolicy: "no-referrer" });
  el.append(head, title);
  if (f.snippet) {
    const p = document.createElement("p");
    p.className = "cite-bubble-snippet";
    p.textContent = f.snippet;
    el.append(p);
  }
  const all = document.createElement("button");
  all.type = "button";
  all.className = "cite-bubble-all";
  all.textContent = t("src.bubble.all");
  all.addEventListener("click", () => {
    const pill = item.closest(".sources")?.querySelector(".src-pill");
    if (pill) setSourcesOpen(pill, true);
    hideBubble();
    item.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    item.focus({ preventScroll: true });
  });
  el.append(all);
  el.addEventListener("pointerenter", () => clearTimeout(hideTimer));
  el.addEventListener("pointerleave", () => !bubble?.pinned && (hideTimer = setTimeout(hideBubble, 250)));
  document.body.append(el);
  place(el, anchor);
  anchor.setAttribute("aria-describedby", el.id);
  anchor.setAttribute("aria-expanded", "true");
  bubble = { el, anchor };
}

const citeOf = (target) => target?.closest?.("sup.cite > a");

function onCiteClick(e) {
  const a = citeOf(e.target);
  if (a) {
    // a tap (or a click) opens the bubble instead of jumping to a list that is folded
    e.preventDefault();
    // a second click closes the bubble that the first one pinned; a bubble opened by hover or focus stays
    if (bubble?.anchor === a && bubble.pinned) hideBubble();
    else {
      showBubble(a);
      if (bubble) bubble.pinned = true;
    }
    return;
  }
  if (bubble && !bubble.el.contains(e.target)) hideBubble();
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("copy", onCopy);
  document.addEventListener("click", onClick);
  document.addEventListener("click", onCiteClick);
  const fine = () => matchMedia("(hover: hover) and (pointer: fine)").matches;
  document.addEventListener("pointerover", (e) => {
    const a = citeOf(e.target);
    if (a && fine()) {
      clearTimeout(hideTimer);
      showBubble(a);
    }
  });
  document.addEventListener("pointerout", (e) => {
    const a = citeOf(e.target);
    if (a && bubble?.anchor === a && !bubble.pinned && fine() && !bubble.el.contains(e.relatedTarget))
      hideTimer = setTimeout(hideBubble, 250);
  });
  document.addEventListener("focusin", (e) => {
    const a = citeOf(e.target);
    if (a) showBubble(a);
    else if (bubble && !bubble.el.contains(e.target)) hideBubble();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && bubble) {
      e.stopPropagation();
      hideBubble(true);
    }
  }, true);
  // the bubble follows its mark while the conversation scrolls, and goes when the mark leaves the screen
  addEventListener(
    "scroll",
    () => {
      if (!bubble) return;
      const r = bubble.anchor.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) hideBubble();
      else place(bubble.el, bubble.anchor);
    },
    true,
  );
  addEventListener("resize", () => bubble && hideBubble());
}
