// Conversation engine, DOM part: the « N documents en contexte » pill, the « ‹ 1/2 › » version pager, the inline
// editor of a question, the styled confirmation dialog, the text preview of a document and the back button that closes
// the open layer. Pure logic: conversation-data.js; strings: conversation-i18n.js (cx.* keys).
import { h, icon, t } from "./core.js";
import { STRINGS } from "./i18n.js";
import { CONVERSATION_STRINGS } from "./conversation-i18n.js";
import { versionInfo } from "./conversation-data.js";

for (const [lang, strings] of Object.entries(CONVERSATION_STRINGS)) Object.assign(STRINGS[lang], strings);

/** conversation.css, linked once (index.html links it too; a missing link never leaves these parts unstyled). */
export function ensureStyles() {
  if (typeof document === "undefined") return;
  if (document.querySelector('link[href$="/static/conversation.css"]')) return;
  document.head.append(h("link", { rel: "stylesheet", href: "/static/conversation.css" }));
}

// ------------------------------------------------------------------ « ‹ 1/2 › »

/** The version pager of the group headed by turns[i], or null. `onSwitch(j)` shows version j (0-based). */
export function versionPager(turns, i, onSwitch, disabled = false) {
  const info = versionInfo(turns, i);
  if (!info) return null;
  const go = (d) => () => onSwitch(info.at - 1 + d);
  return h(
    "span",
    { class: "cx-pager", role: "group", "aria-label": t("cx.ver.label", info), "data-versions": `${info.at}/${info.n}` },
    h(
      "button",
      {
        class: "btn btn-quiet btn-icon btn-small cx-pager-prev",
        type: "button",
        "aria-label": t("cx.ver.prev"),
        title: t("cx.ver.prev"),
        disabled: disabled || info.at <= 1,
        "data-act": "ver-prev",
        onclick: go(-1),
      },
      icon("chevron", "cx-flip"),
    ),
    h("span", { class: "cx-pager-n num", "aria-hidden": "true", text: `${info.at}/${info.n}` }),
    h(
      "button",
      {
        class: "btn btn-quiet btn-icon btn-small cx-pager-next",
        type: "button",
        "aria-label": t("cx.ver.next"),
        title: t("cx.ver.next"),
        disabled: disabled || info.at >= info.n,
        "data-act": "ver-next",
        onclick: go(1),
      },
      icon("chevron"),
    ),
  );
}

// ------------------------------------------------------------------ editing a question in place

/** The inline editor that replaces a bubble: Annuler / Envoyer, Enter sends, Escape cancels. */
export function inlineEditor(text, { onSend, onCancel, keeps = false }) {
  const area = h("textarea", { class: "cx-edit-input", rows: "2", "aria-label": t("cx.edit.label"), maxlength: "24000" });
  area.value = text;
  const fit = () => {
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 320)}px`;
  };
  const sendBtn = h("button", { class: "btn btn-primary btn-small", type: "button", "data-act": "edit-send", text: t("cx.edit.send") });
  const sync = () => (sendBtn.disabled = !area.value.trim());
  sendBtn.addEventListener("click", () => area.value.trim() && onSend(area.value.trim()));
  area.addEventListener("input", () => (fit(), sync()));
  area.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onCancel();
    } else if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (area.value.trim()) onSend(area.value.trim());
    }
  });
  const box = h(
    "div",
    { class: "cx-edit" },
    area,
    keeps && h("p", { class: "cx-edit-note", text: t("cx.edit.keeps") }),
    h(
      "div",
      { class: "cx-edit-acts" },
      h("button", { class: "btn btn-outline btn-small", type: "button", "data-act": "edit-cancel", text: t("cx.edit.cancel"), onclick: onCancel }),
      sendBtn,
    ),
  );
  window.setTimeout(() => {
    fit();
    sync();
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  }, 0);
  return box;
}

// ------------------------------------------------------------------ dialogs (no native confirm())

function dialogShell(cls, label) {
  const dialog = h("dialog", { class: `cx-dialog ${cls}`, "aria-label": label });
  dialog.addEventListener("close", () => {
    const back = dialog.returnTo;
    dialog.remove();
    if (back?.isConnected) back.focus();
  });
  dialog.addEventListener("click", (e) => e.target === dialog && dialog.close()); // a click on the backdrop
  return dialog;
}

/** A styled confirmation (light and dark, the app's tone). Resolves true on the confirm button only. */
export function confirmDialog({ title, text, ok, cancel, danger = true }) {
  return new Promise((resolve) => {
    let answer = false;
    const dialog = dialogShell("cx-confirm", title);
    const okBtn = h("button", {
      class: `btn ${danger ? "btn-danger-solid" : "btn-primary"}`,
      type: "button",
      "data-act": "confirm-ok",
      text: ok,
      onclick: () => ((answer = true), dialog.close()),
    });
    const cancelBtn = h("button", { class: "btn btn-outline", type: "button", "data-act": "confirm-cancel", text: cancel, onclick: () => dialog.close() });
    dialog.append(
      h("h2", { class: "cx-dialog-title", text: title }),
      h("p", { class: "cx-dialog-text", text }),
      h("div", { class: "cx-dialog-acts" }, cancelBtn, okBtn),
    );
    dialog.addEventListener("close", () => resolve(answer));
    dialog.returnTo = document.activeElement;
    document.body.append(dialog);
    dialog.showModal();
    cancelBtn.focus(); // the safe answer has the focus
  });
}

/** What Bird will read in a document: its extracted text (text files), else a sentence saying it is read on the server. */
export function previewDialog(doc) {
  const dialog = dialogShell("cx-preview", t("cx.ctx.preview", { name: doc.name }));
  const text = doc.encoding !== "base64" && typeof doc.content === "string" ? doc.content : "";
  const close = h("button", { class: "btn btn-quiet btn-icon btn-small cx-dialog-x", type: "button", "aria-label": t("cx.ctx.close"), title: t("cx.ctx.close"), onclick: () => dialog.close() }, icon("cross"));
  dialog.append(
    h("header", { class: "cx-dialog-head" }, h("h2", { class: "cx-dialog-title", text: doc.name }), close),
    text
      ? h("p", { class: "cx-dialog-sub", text: t("cx.ctx.preview.chars", { n: text.length.toLocaleString() }) })
      : null,
    text ? h("pre", { class: "cx-preview-text", tabindex: "0", text: text.slice(0, 20000) + (text.length > 20000 ? "\n…" : "") }) : h("p", { class: "cx-dialog-text", text: t("cx.ctx.preview.none") }),
  );
  dialog.returnTo = document.activeElement;
  document.body.append(dialog);
  dialog.showModal();
  close.focus();
  return dialog;
}

// ------------------------------------------------------------------ « 2 documents en contexte »

/** The pill under which the documents of earlier messages wait (read only when a question is about them). */
export function contextPill(context, lost, { onRemove, onPreview, onReattach }) {
  if (!context.length && !lost.length) return null;
  const panelId = "cx-ctx-pop";
  const label = lost.length
    ? t(lost.length > 1 ? "cx.ctx.lost.many" : "cx.ctx.lost.one", { n: lost.length })
    : t(context.length > 1 ? "cx.ctx.many" : "cx.ctx.one", { n: context.length });
  const pill = h(
    "button",
    {
      class: `cx-pill${lost.length ? " is-lost" : ""}`,
      type: "button",
      "aria-expanded": "false",
      "aria-controls": panelId,
      "data-act": "ctx-pill",
    },
    icon(lost.length ? "alert" : "clip"),
    h("span", { text: label }),
    icon("chevron", "cx-chev"),
  );
  const row = (doc, isLost) =>
    h(
      "li",
      { class: `cx-ctx-row${isLost ? " is-lost" : ""}` },
      h("button", { class: "cx-ctx-name", type: "button", title: doc.name, "data-act": "ctx-preview", onclick: () => onPreview(doc), disabled: isLost }, icon("file"), h("span", { text: doc.name })),
      isLost &&
        h("button", { class: "btn btn-outline btn-small", type: "button", "data-act": "ctx-reattach", text: t("cx.ctx.reattach"), onclick: () => onReattach(doc) }),
      h(
        "button",
        { class: "btn btn-quiet btn-icon btn-small", type: "button", "aria-label": t("cx.ctx.remove", { name: doc.name }), title: t("cx.ctx.remove", { name: doc.name }), "data-act": "ctx-remove", onclick: () => onRemove(doc) },
        icon("cross"),
      ),
    );
  const pop = h(
    "div",
    { class: "cx-ctx-pop", id: panelId, hidden: true },
    h("p", { class: "cx-ctx-title", text: t("cx.ctx.title") }),
    h("ul", { class: "cx-ctx-list" }, lost.map((d) => row(d, true)), context.map((d) => row(d, false))),
    h("p", { class: "cx-ctx-note", text: lost.length ? t("cx.ctx.lost.block", { name: lost[0].name }) : t("cx.ctx.note") }),
  );
  const wrap = h("div", { class: "cx-ctx" }, pill, pop);
  const set = (open) => {
    pop.hidden = !open;
    pill.setAttribute("aria-expanded", String(open));
    if (open) document.addEventListener("pointerdown", outside, true);
    else document.removeEventListener("pointerdown", outside, true);
  };
  const outside = (e) => !wrap.contains(e.target) && set(false);
  pill.addEventListener("click", () => set(pop.hidden));
  wrap.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pop.hidden) {
      e.stopPropagation();
      set(false);
      pill.focus();
    }
  });
  wrap.open = () => set(true);
  return wrap;
}

// ------------------------------------------------------------------ the back button closes the open layer (R4)
//
// Each layer (drawer, canvas, photo sheet, Settings, a dialog) pushes one history entry when it opens; the back
// button or the swipe-back gesture then closes it instead of leaving the app. Closing a layer by its own button
// takes its entry back, so the history never fills with dead entries.

const layers = []; // [{name, close}]
let skipPop = 0;

export function openLayer(name, close) {
  if (typeof history === "undefined" || layers.some((l) => l.name === name)) return;
  layers.push({ name, close });
  try {
    history.pushState({ birdLayer: name, depth: layers.length }, "");
  } catch {
    /* sandboxed frame: the layer still works */
  }
}

/** The layer was closed by the page (its button, Escape): its history entry is taken back. */
export function closedLayer(name) {
  const i = layers.findIndex((l) => l.name === name);
  if (i < 0) return;
  const n = layers.length - i;
  layers.splice(i);
  if (history.state?.birdLayer) {
    skipPop += 1;
    history.go(-n);
  }
}

export const hasLayer = (name) => layers.some((l) => l.name === name);

export function bindLayers() {
  window.addEventListener("popstate", () => {
    if (skipPop > 0) {
      skipPop -= 1;
      return;
    }
    const top = layers.pop();
    if (top) top.close();
  });
}

/** For layers drawn by other modules: an attribute or a class that says « open » is watched. */
export function watchLayer(name, el, isOpen, close) {
  if (!el || typeof MutationObserver === "undefined") return;
  let was = isOpen();
  new MutationObserver(() => {
    const now = isOpen();
    if (now === was) return;
    was = now;
    if (now) openLayer(name, close);
    else closedLayer(name);
  }).observe(el, { attributes: true, attributeFilter: ["hidden", "class", "open"] });
}

