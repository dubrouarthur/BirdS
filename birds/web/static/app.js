// Bird web chat. Vanilla ES modules, no framework, no build step, no external request.
// The frontend depends only on the API contract: /api/health, /api/chat (SSE), /api/endpoint/test.
import {
  $,
  activeMode,
  activeModel,
  announce,
  button,
  copyText,
  download,
  fmtDate,
  fmtInt,
  h,
  icon,
  isDemo,
  savePrefs,
  state,
  store,
  t,
  toast,
  uid,
  modelLabel,
} from "./core.js";
import {
  exportMarkdown,
  forgetRendered,
  renderConversation,
  setHandlers,
  tick,
  updateStream,
  updateTurn,
} from "./turns.js";
import {
  addImage,
  bindLightbox,
  busyImages,
  docCard,
  imageCard,
  isImageFile,
  openLightbox,
  pending,
  readDocument,
  readyImages,
  removeImage,
} from "./attach.js";
import {
  convUsages,
  ledgerAdd,
  openShortcuts,
  openWelcome,
  renderAbout,
  renderFootprint,
  renderSettings,
  setViewHooks,
  totals,
} from "./views.js";

const PASTE_AS_FILE = 3000; // characters: longer pasted text becomes an attached document
const KEEP_FILE_B64 = 400_000; // larger generated files are not kept in localStorage

// ------------------------------------------------------------------ conversations (localStorage)

const randomId = () =>
  globalThis.crypto?.randomUUID
    ? crypto.randomUUID()
    : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
        (
          c ^
          (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))
        ).toString(16),
      );
const newConv = () => ({
  id: uid("c"),
  cid: randomId(), // 122 random bits: prefix-cache salt and log id on the server, never shown
  title: "",
  created: Date.now(),
  updated: Date.now(),
  turns: [],
  attachments: [],
});

function slim(conv) {
  return {
    ...conv,
    // office files and PDFs are kept in memory only (too large for localStorage): after a reload they are listed
    // but must be attached again to be read
    attachments: (conv.attachments || []).map((a) =>
      a.encoding === "base64" ? { ...a, content: null, lost: true } : a,
    ),
    turns: conv.turns
      .filter((turn) => turn.role === "user" || turn.status !== "running")
      .map((turn) => {
        if (turn.role === "user")
          return {
            ...turn,
            // images are never stored: only their name and size survive a reload
            images: (turn.images || []).map(({ name, w, h: hh, sent }) => ({
              name,
              w,
              h: hh,
              sent,
            })),
          };
        const { ui, live, text, ...rest } = turn;
        return {
          ...rest,
          files: (rest.files || []).map((f) =>
            f.data && f.data.length > KEEP_FILE_B64 ? { ...f, data: null } : f,
          ),
        };
      }),
  };
}

function saveConv() {
  const conv = state.conv;
  if (!conv) return;
  if (!conv.turns.length) {
    store.set(`bird.conv.${conv.id}`, null);
    state.convs = state.convs.filter((c) => c.id !== conv.id);
  } else {
    conv.updated = Date.now();
    const entry = {
      id: conv.id,
      title: conv.title,
      created: conv.created,
      updated: conv.updated,
      n: conv.turns.length,
      att: conv.turns.some((x) => (x.attachments || []).length)
        ? "doc"
        : conv.turns.some((x) => (x.images || []).length)
          ? "image"
          : "",
    };
    state.convs = [entry, ...state.convs.filter((c) => c.id !== conv.id)];
    let saved = store.set(`bird.conv.${conv.id}`, JSON.stringify(slim(conv)));
    for (let i = 0; !saved && i < 6 && state.convs.length > 1; i++) {
      const oldest = state.convs.pop(); // storage full: let the oldest conversation go
      store.set(`bird.conv.${oldest.id}`, null);
      saved = store.set(`bird.conv.${conv.id}`, JSON.stringify(slim(conv)));
      if (i === 0) toast(t("toast.storage"), "error");
    }
  }
  store.set("bird.convs", JSON.stringify(state.convs));
  store.set("bird.current", conv.turns.length ? conv.id : null);
  renderSidebar();
}

function loadConv(id) {
  const raw = store.json(`bird.conv.${id}`, null);
  if (!raw || !Array.isArray(raw.turns)) return null;
  raw.attachments = Array.isArray(raw.attachments) ? raw.attachments : [];
  raw.turns = raw.turns
    .filter((x) => x && (x.role === "user" || x.role === "assistant"))
    .map((x) =>
      x.role === "user"
        ? {
            role: "user",
            content: String(x.content ?? ""),
            attachments: (x.attachments || []).map((a) =>
              typeof a === "string" ? { name: a } : a,
            ),
            images: Array.isArray(x.images) ? x.images : [],
          }
        : { steps: [], files: [], ...x, ui: {} },
    );
  return raw;
}

function openConv(id) {
  stop();
  const conv = (id && loadConv(id)) || newConv();
  state.conv = conv;
  state.editing = false;
  forgetRendered();
  showView("chat");
  renderChat();
  renderSidebar();
  scrollToEnd(true);
  closeDrawer();
}

function autoTitle(text) {
  const clean = String(text).replace(/\s+/g, " ").trim();
  if (clean.length <= 52) return clean;
  const cut = clean.slice(0, 52);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), 24))}…`;
}

// ------------------------------------------------------------------ sidebar

let search = "";
let menuFor = null;
let renaming = null;

function renderSidebar() {
  const list = $("conv-list");
  const q = search.trim().toLowerCase();
  const items = state.convs.filter(
    (c) => !q || (c.title || "").toLowerCase().includes(q),
  );
  if (!items.length) {
    list.replaceChildren(
      h("p", {
        class: "side-empty",
        text: t(state.convs.length ? "side.none" : "side.empty"),
      }),
    );
    $("btn-clear").hidden = !state.convs.length;
    return;
  }
  const day = 86_400_000;
  const start = new Date().setHours(0, 0, 0, 0);
  const groups = [
    ["side.today", items.filter((c) => c.updated >= start)],
    [
      "side.week",
      items.filter((c) => c.updated < start && c.updated >= start - 7 * day),
    ],
    ["side.older", items.filter((c) => c.updated < start - 7 * day)],
  ];
  const row = (c) => {
    const title = c.title || t("side.untitled");
    const current = state.conv?.id === c.id;
    if (renaming === c.id) {
      const input = h("input", {
        class: "rename",
        type: "text",
        value: title,
        maxlength: "80",
        "aria-label": t("side.rename.prompt"),
      });
      const done = (save) => {
        if (renaming !== c.id) return;
        renaming = null;
        const value = input.value.trim();
        if (save && value) {
          c.title = value;
          const conv = current ? state.conv : loadConv(c.id);
          if (conv) {
            conv.title = value;
            store.set(`bird.conv.${c.id}`, JSON.stringify(slim(conv)));
          }
          store.set("bird.convs", JSON.stringify(state.convs));
          updateTop();
        }
        renderSidebar();
      };
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") done(true);
        if (e.key === "Escape") {
          e.stopPropagation();
          done(false);
        }
      });
      input.addEventListener("blur", () => done(true));
      window.setTimeout(() => {
        input.focus();
        input.select();
      }, 0);
      return h("li", { class: "conv is-renaming" }, input);
    }
    const open = menuFor === c.id;
    return h(
      "li",
      { class: `conv${current ? " is-current" : ""}`, "data-conv": c.id },
      h(
        "button",
        {
          class: "conv-open",
          type: "button",
          "aria-current": current ? "page" : null,
          title: `${title} — ${fmtDate(c.updated)}`,
          onclick: () => openConv(c.id),
        },
        h("span", { class: "conv-title", text: title }),
        c.att &&
          h(
            "span",
            {
              class: "conv-att",
              title: t(c.att === "image" ? "att.has.image" : "att.has.doc"),
            },
            icon(c.att === "image" ? "image" : "clip"),
            h("span", {
              class: "sr-only",
              text: t(c.att === "image" ? "att.has.image" : "att.has.doc"),
            }),
          ),
      ),
      h(
        "button",
        {
          class: "btn btn-quiet btn-icon btn-small conv-more",
          type: "button",
          "aria-label": t("side.more", { title }),
          "aria-expanded": String(open),
          onclick: () => ((menuFor = open ? null : c.id), renderSidebar()),
        },
        icon("more"),
      ),
      open &&
        h(
          "div",
          {
            class: "conv-menu",
            role: "group",
            "aria-label": t("side.more", { title }),
          },
          button(
            "btn-quiet btn-small",
            "edit",
            t("side.rename"),
            () => ((renaming = c.id), (menuFor = null), renderSidebar()),
            { "data-conv-act": "rename" },
          ),
          button(
            "btn-quiet btn-small",
            "download",
            t("side.export"),
            () => exportConv(c.id),
            { "data-conv-act": "export" },
          ),
          button(
            "btn-quiet btn-small btn-danger",
            "trash",
            t("side.delete"),
            () => deleteConv(c.id, title),
            { "data-conv-act": "delete" },
          ),
        ),
    );
  };
  list.replaceChildren(
    ...groups
      .filter(([, g]) => g.length)
      .map(([label, g]) =>
        h(
          "section",
          null,
          h("h3", { class: "eyebrow", text: t(label) }),
          h("ul", null, g.map(row)),
        ),
      ),
  );
  $("btn-clear").hidden = false;
}

function exportConv(id) {
  const conv = state.conv?.id === id ? state.conv : loadConv(id);
  if (!conv) return;
  const name = `${
    (conv.title || "bird")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40) || "bird"
  }.md`;
  download(name, "text/markdown;charset=utf-8", exportMarkdown(conv));
  menuFor = null;
  renderSidebar();
  toast(t("toast.exported"), "ok");
}

function deleteConv(id, title) {
  if (!window.confirm(t("side.delete.confirm", { title }))) return;
  store.set(`bird.conv.${id}`, null);
  state.convs = state.convs.filter((c) => c.id !== id);
  store.set("bird.convs", JSON.stringify(state.convs));
  menuFor = null;
  if (state.conv?.id === id) openConv(null);
  else renderSidebar();
  toast(t("toast.deleted"), "ok");
}

function clearAll() {
  if (!window.confirm(t("side.clear.confirm"))) return;
  for (const key of store.keys("bird.conv.")) store.set(key, null);
  state.convs = [];
  store.set("bird.convs", null);
  store.set("bird.current", null);
  openConv(null);
  toast(t("toast.cleared"), "ok");
}

const photoItems = () => [...$("photo-menu").querySelectorAll("[role=menuitem]")].filter((b) => !b.hidden);
/** Open or close the photo sheet and its scrim; `refocus` puts focus back on the button that opened it. */
function setPhotoMenu(open, refocus = false) {
  $("photo-menu").hidden = !open;
  $("photo-scrim").hidden = !open;
  $("btn-photo").setAttribute("aria-expanded", String(open));
  if (!open && refocus) $("btn-photo").focus();
}

const isNarrow = () => window.matchMedia("(max-width: 900px)").matches;
function setSidebar(open) {
  const side = $("sidebar");
  const modal = open && isNarrow(); // on phones and tablets the open drawer is a modal: what is behind it is inert
  document.body.classList.toggle("side-open", open);
  document.body.classList.toggle("side-closed", !open);
  delete document.documentElement.dataset.side;
  $("btn-menu").setAttribute("aria-expanded", String(open));
  $("backdrop").hidden = !modal;
  for (const el of document.querySelectorAll(".main, .skip")) el.inert = modal;
  // focus leaves the drawer before it turns inert, back to the button that opened it
  if (!open && side.contains(document.activeElement)) $("btn-menu").focus();
  side.inert = !open;
  if (!isNarrow()) store.set("bird.side", open ? "1" : "0");
  if (modal) $("btn-new").focus();
}
/** Tab and Shift+Tab wrap inside the open drawer on narrow screens, so focus never leaves the modal. */
function trapDrawer(e) {
  if (
    e.key !== "Tab" ||
    !isNarrow() ||
    !document.body.classList.contains("side-open")
  )
    return;
  const items = [
    ...$("sidebar").querySelectorAll(
      "button, input, a[href], [tabindex]:not([tabindex='-1'])",
    ),
  ].filter((el) => !el.disabled && !el.hidden && el.getClientRects().length);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
const closeDrawer = () => isNarrow() && setSidebar(false);

// ------------------------------------------------------------------ views and chrome

function showView(view) {
  state.view = view;
  for (const name of ["chat", "footprint", "settings", "about"])
    $(`view-${name}`).hidden = name !== view;
  $("dock").hidden = view !== "chat";
  $("btn-back").hidden = view === "chat";
  if (view === "footprint") renderFootprint();
  if (view === "settings") renderSettings();
  if (view === "about") renderAbout();
  updateTop();
  if (view !== "chat") {
    $("scroll").scrollTop = 0;
    closeDrawer();
    $(`view-${view}`).querySelector("h2").focus();
  }
  updateJump();
}

function updateTop() {
  const titles = {
    footprint: t("fp.title"),
    settings: t("set.title"),
    about: t("about.title"),
  };
  $("top-title").textContent =
    titles[state.view] || state.conv?.title || t("side.untitled");
  const model = isDemo()
    ? `${modelLabel()} · ${t("demo.badge")}`
    : modelLabel();
  $("model-name").textContent = model;
  $("btn-model").classList.toggle("is-demo", isDemo());
  const label = t("nav.model", {
    model: isDemo() ? model : `${model} (${activeModel()})`,
  });
  $("btn-model").setAttribute("aria-label", label);
  $("btn-model").title = label;
  const s = totals(convUsages(state.conv));
  $("footprint-total").textContent = s.n
    ? `${fmtInt(s.prompt + s.completion)} tokens`
    : t("nav.footprint");
  document.title = state.conv?.title
    ? `${state.conv.title} — Bird`
    : t("app.title");
}

function applyTheme() {
  const theme = state.prefs.theme;
  if (theme === "light" || theme === "dark")
    document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const dark =
    theme === "dark" ||
    (theme !== "light" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document
    .querySelector('meta[name="theme-color"]')
    .setAttribute("content", dark ? "#0b1220" : "#f6f5f0");
}

function applyStrings() {
  document.documentElement.lang = state.prefs.lang;
  for (const el of document.querySelectorAll("[data-i18n]"))
    el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-aria]")) {
    el.setAttribute("aria-label", t(el.dataset.i18nAria));
    if (el.classList.contains("btn-icon")) el.title = t(el.dataset.i18nAria);
  }
  for (const el of document.querySelectorAll("[data-i18n-placeholder]"))
    el.placeholder = t(el.dataset.i18nPlaceholder);
}

function showBanner(text) {
  $("banner").textContent = text || "";
  $("banner").hidden = !text;
}

// ------------------------------------------------------------------ empty state and suggestions

function renderEmpty() {
  const empty = $("empty");
  const turns = state.conv?.turns || [];
  empty.hidden = turns.length > 0;
  if (turns.length) return;
  const withDoc = (state.conv?.attachments || []).length > 0;
  const set = withDoc
    ? [
        ["doc.summary", "read_file"],
        ["doc.minutes", "make_document"],
        ["doc.email", "draft_email"],
        ["doc.slides", "make_slides"],
      ]
    : [
        ["email", "draft_email"],
        ["minutes", "make_document"],
        ["slides", "make_slides"],
        ["search", "web_search"],
      ];
  $("examples-title").textContent = t(
    withDoc ? "empty.examples.doc" : "empty.examples",
  );
  $("demo-note").hidden = !isDemo();
  $("examples").replaceChildren(
    ...set.map(([key, ico]) =>
      h(
        "li",
        null,
        h(
          "button",
          {
            class: "chip",
            type: "button",
            "data-example": key,
            title: t(`ex.${key}.prompt`),
            "aria-label": `${t(`ex.${key}.title`)} — ${t(`ex.${key}.prompt`)}`,
            onclick: () => send(t(`ex.${key}.prompt`)),
          },
          h("span", { class: "chip-icon" }, icon(ico)),
          h(
            "span",
            { class: "chip-text" },
            h("span", { class: "chip-title", text: t(`ex.${key}.title`) }),
            h("span", { class: "chip-prompt", text: t(`ex.${key}.prompt`) }),
          ),
        ),
      ),
    ),
  );
}

function renderChat() {
  renderEmpty();
  renderConversation();
  renderAttachments();
  updateComposer();
  updateTop();
}

// ------------------------------------------------------------------ scrolling

let stick = true;
// pinned: a long answer reached the top of the view; we hold it there so it is read from its start, and the scroll
// listener never clears this (only an explicit jump, a send or opening a conversation does)
let pinned = false;
let followTurn = null; // id of the answer being streamed: the only one we anchor to
const scroller = () => $("scroll");
const nearBottom = () =>
  scroller().scrollHeight - scroller().scrollTop - scroller().clientHeight <
  120;
/** Top of the user turn that asked for `turnId`, in the scroller's content coordinates (null when not found). */
function anchorOf(turnId) {
  const el = turnId && document.querySelector(`[data-turn="${turnId}"]`);
  if (!el) return null;
  const prev = el.previousElementSibling;
  const target = prev?.classList.contains("turn-user") ? prev : el;
  const sc = scroller();
  return (
    target.getBoundingClientRect().top -
    sc.getBoundingClientRect().top +
    sc.scrollTop
  );
}
function scrollToEnd(force) {
  const sc = scroller();
  if (state.view === "chat" && !(state.conv?.turns || []).length) {
    // an empty chat opens at its top (the welcome lines and the examples), never scrolled to its bottom
    stick = true;
    pinned = false;
    sc.scrollTop = 0;
    updateJump();
    return;
  }
  if (force) {
    stick = true;
    pinned = false;
    followTurn = null;
  }
  const bottom = sc.scrollHeight - sc.clientHeight;
  // once the stream is over, an answer that overflows by less than the "near bottom" margin just ends at the bottom
  const slack = state.busy ? 0 : 120;
  if (pinned && !state.busy && bottom - sc.scrollTop <= slack) pinned = false;
  if (stick && !pinned) {
    const anchor = anchorOf(followTurn);
    if (anchor !== null && anchor - 8 < bottom - slack) {
      sc.scrollTop = Math.max(0, anchor - 8); // the answer is taller than the view: stop at its question
      pinned = true;
    } else sc.scrollTop = sc.scrollHeight;
  }
  updateJump();
}
function updateJump() {
  const btn = $("btn-jump");
  const away = pinned ? !nearBottom() : !stick;
  btn.hidden =
    state.view !== "chat" || !away || !(state.conv?.turns || []).length;
  const key = pinned && state.busy ? "turn.jump.more" : "turn.jump";
  const label = btn.querySelector("span");
  if (label && label.dataset.i18n !== key) {
    label.dataset.i18n = key;
    label.textContent = t(key);
  }
}

// ------------------------------------------------------------------ composer

const input = () => $("composer-input");

function autosize() {
  const el = input();
  el.style.height = "auto";
  // never more than 28% of what is visible (the keyboard takes the rest on phones), never more than 240px
  const visible = window.visualViewport?.height || window.innerHeight || 857;
  el.style.height = `${Math.min(el.scrollHeight, Math.round(visible * 0.28), 240)}px`;
}

// The app fills the visual viewport, so the dock stays above an on-screen keyboard.
function trackViewport() {
  const vv = window.visualViewport;
  if (!vv) return;
  let frame = 0;
  const apply = () => {
    frame = 0;
    document.documentElement.style.setProperty("--vvh", `${Math.round(vv.height)}px`);
    autosize();
  };
  const soon = () => frame || (frame = requestAnimationFrame(apply));
  vv.addEventListener("resize", soon);
  vv.addEventListener("scroll", soon);
  apply();
}

function pendingConfirm() {
  const turns = state.conv?.turns || [];
  const last = turns[turns.length - 1];
  return last && last.role === "assistant" && last.status === "confirm"
    ? last
    : null;
}

function updateComposer() {
  const el = input();
  const text = el.value;
  const send = $("btn-send");
  const awaiting = pendingConfirm();
  const images = readyImages().length;
  const reason = !state.online
    ? "composer.send.offline"
    : state.busy
      ? "composer.send.busy"
      : awaiting
        ? "composer.send.pending"
        : busyImages()
          ? "att.reading"
          : !text.trim() && !images
            ? "composer.send.empty"
            : "";
  const nAtt =
    images +
    (state.conv?.attachments || []).filter((a) => !a.sent && !a.lost).length;
  send.disabled = !!reason;
  send.hidden = state.busy;
  const label = nAtt
    ? t(nAtt === 1 ? "att.send.one" : "att.send.many", { n: nAtt })
    : t("composer.send");
  send.title = reason ? t(reason) : label;
  send.setAttribute("aria-label", label);
  const photo = $("btn-photo");
  const canImages = imagesAvailable();
  photo.setAttribute("aria-disabled", String(!canImages));
  photo.title = canImages ? t("att.photo") : t("att.img.unsupported");
  $("photo-take").hidden = $("photo-pick").hidden = !canImages;
  $("photo-note").textContent = canImages
    ? t("att.photo.note")
    : t("att.img.unsupported");
  const nDocs = nAtt - images;
  $("btn-attach").dataset.count = nDocs ? String(nDocs) : "";
  $("btn-photo").dataset.count = images ? String(images) : "";
  // most reasons stay for screen readers only; a pending approval is shown, with a way to reach the request
  const why = $("send-why");
  const shown = reason === "composer.send.pending" || reason === "composer.send.offline";
  why.className = shown ? "send-why" : "sr-only";
  why.replaceChildren(
    reason ? h("span", { text: t(reason) }) : "",
    reason === "composer.send.pending"
      ? h("button", {
          class: "link",
          type: "button",
          text: t("composer.send.pending.see"),
          onclick: () => {
            const deny = document.querySelector("[data-confirm-deny]");
            deny?.scrollIntoView({ block: "center" });
            deny?.focus();
          },
        })
      : "",
  );
  $("btn-stop").hidden = !state.busy;
  const count = $("composer-count");
  if (text.length > 1200) {
    count.hidden = false;
    count.textContent = `${t("composer.count", { chars: fmtInt(text.length), tokens: fmtInt(Math.ceil(text.length / 4)) })}${text.length > 6000 ? ` — ${t("composer.count.long")}` : ""}`;
    count.classList.toggle("is-long", text.length > 6000);
  } else count.hidden = true;
  $("editing").hidden = !state.editing;
  $("btn-thinking").setAttribute("aria-checked", String(state.thinking));
  updateSlash();
}

const shownAttachments = new Set(); // the entrance animation plays once per attachment, not at every redraw
const isNew = (key) => !shownAttachments.has(key) && shownAttachments.add(key);
/** Where focus goes after the tray is redrawn: the same card, else the one now at that place, else the input. */
function keepTrayFocus(box, draw) {
  const removes = () => [...box.querySelectorAll(".att-x")];
  const was = document.activeElement;
  const index = removes().indexOf(was);
  const key = index >= 0 ? was.closest("[data-att]")?.dataset.att : null;
  draw();
  if (index < 0 || box.contains(document.activeElement)) return;
  const now = removes();
  const same = key && now.find((b) => b.closest("[data-att]")?.dataset.att === key);
  (same || now[index] || now[index - 1] || input()).focus();
}

function renderAttachments() {
  const box = $("attachments");
  keepTrayFocus(box, () => drawAttachments(box));
}
function drawAttachments(box) {
  const docs = state.conv?.attachments || [];
  const imgs = pending.images;
  box.hidden = !docs.length && !imgs.length;
  if (box.hidden) return box.replaceChildren();
  const rerender = () => (renderAttachments(), updateComposer());
  const removeDoc = (i) => () => {
    announce(t("att.removed", { name: docs[i].name }));
    docs.splice(i, 1);
    rerender();
    renderEmpty();
    saveIfStarted();
  };
  box.replaceChildren(
    h(
      "ul",
      { class: "att-tray", "aria-label": t("att.tray") },
      imgs.map((img) =>
        h(
          "li",
          { class: `att-in${isNew(img.id) ? " att-new" : ""}` },
          imageCard(img, {
            onRemove: () => removeImage(img.id, rerender),
            onOpen: () =>
              openLightbox(readyImages(), readyImages().indexOf(img)),
          }),
        ),
      ),
      docs.map((doc, i) =>
        h(
          "li",
          { class: `att-in${isNew(doc.name) ? " att-new" : ""}` },
          docCard(
            {
              ...doc,
              size: doc.size || (doc.content ? doc.content.length : 0),
            },
            {
              onRemove: removeDoc(i),
              status: doc.lost
                ? { kind: "err", text: t("att.doc.lost") }
                : doc.sent
                  ? { kind: "ok", text: t("att.doc.inconv") }
                  : { kind: "ok", text: t("att.ready") },
            },
          ),
        ),
      ),
    ),
    h(
      "p",
      { class: "att-note" },
      icon("info"),
      t(imgs.length ? "att.note.images" : "composer.attach.note"),
    ),
  );
}
const saveIfStarted = () => state.conv.turns.length && saveConv();

function addAttachment(name, content, encoding = "text", size = 0) {
  const limits = state.health?.limits || {};
  const maxChars = limits.max_attachment_chars || 60_000;
  const maxCount = limits.max_attachments || 4;
  const list = state.conv.attachments;
  if (list.length >= maxCount)
    return toast(t("composer.attach.toomany", { max: maxCount }), "error");
  if (encoding === "text" && content.length > maxChars)
    return toast(
      t("composer.attach.toolarge", {
        name,
        n: fmtInt(content.length),
        max: fmtInt(maxChars),
      }),
      "error",
    );
  let safe =
    name
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[-.]+|[-.]+$/g, "")
      .slice(0, 60) || "document.txt";
  if (!/\.[A-Za-z0-9]{1,8}$/.test(safe)) safe += ".txt";
  const stem = safe.replace(/(\.[^.]+)$/, "");
  const ext = safe.slice(stem.length);
  for (let n = 2; list.some((a) => a.name === safe); n++)
    safe = `${stem}-${n}${ext}`;
  list.push({ name: safe, content, encoding, size: size || content.length });
  announce(t("att.added", { name: safe }));
  renderAttachments();
  updateComposer();
  renderEmpty();
  saveIfStarted();
  return true;
}

/** Images work in the demo (scripted), with the operator's model if it serves /v1/chat/completions, and with
 * "Mon endpoint" unless "Tester la connexion" found no such route. */
function imagesAvailable() {
  const modes = state.health?.images_modes || {};
  const mode = activeMode();
  if (mode === "user")
    return modes.user !== false && state.prefs.userImages !== false;
  return !!modes[mode];
}

async function onFiles(files) {
  const imageMode = imagesAvailable();
  const maxImages = state.health?.image_limits?.max || 3;
  let room = Math.max(0, maxImages - pending.images.length); // computed once: one message for the whole drop
  let skipped = 0;
  for (const file of files) {
    if (isImageFile(file)) {
      if (!imageMode) {
        toast(t("att.img.unsupported"), "error");
        continue;
      }
      if (room <= 0) {
        skipped++;
        continue;
      }
      room--;
      addImage(file, () => (renderAttachments(), updateComposer()));
      continue;
    }
    if (file.size > 2_000_000 && !/\.(pdf|docx|xlsx|pptx)$/i.test(file.name)) {
      toast(
        t("composer.attach.toolarge", {
          name: file.name,
          n: fmtInt(file.size),
          max: fmtInt(state.health?.limits?.max_attachment_chars || 60_000),
        }),
        "error",
      );
      continue;
    }
    const doc = await readDocument(file);
    if (doc.error) {
      toast(t(doc.error, { name: doc.name }), "error");
      continue;
    }
    addAttachment(doc.name, doc.content, doc.encoding, doc.size);
  }
  if (skipped) toast(t(skipped > 1 ? "att.img.skipped" : "att.img.skipped1", { n: skipped, max: maxImages }), "error");
  input().focus();
}

// slash-style quick actions
const SLASH = [
  ["mail", "draft_email"],
  ["cr", "make_document"],
  ["pres", "make_slides"],
  ["search", "web_search"],
];
let slashIndex = 0;
function slashMatches() {
  const value = input().value;
  if (!/^\/[^\s]*$/.test(value)) return null;
  const q = value.slice(1).toLowerCase();
  return SLASH.filter(
    ([key]) =>
      key.startsWith(q) || t(`slash.${key}`).toLowerCase().startsWith(q),
  );
}
function updateSlash() {
  const menu = $("slash-menu");
  const matches = slashMatches();
  const open = !!matches && matches.length > 0 && !state.busy;
  menu.hidden = !open;
  input().setAttribute("aria-expanded", String(open));
  if (!open) return input().removeAttribute("aria-activedescendant");
  slashIndex = Math.min(slashIndex, matches.length - 1);
  menu.replaceChildren(
    h("p", { class: "eyebrow", text: t("slash.title") }),
    h(
      "ul",
      { role: "listbox", id: "slash-list", "aria-label": t("slash.title") },
      matches.map(([key, ico], i) =>
        h(
          "li",
          {
            role: "option",
            id: `slash-${key}`,
            class: i === slashIndex ? "is-active" : "",
            "aria-selected": String(i === slashIndex),
            onmousedown: (e) => (e.preventDefault(), pickSlash(key)),
          },
          h("span", { class: "chip-icon" }, icon(ico)),
          h("span", { class: "slash-name", text: `/${key}` }),
          h("span", { class: "slash-title", text: t(`slash.${key}`) }),
          h("span", { class: "slash-hint", text: t(`slash.${key}.hint`) }),
        ),
      ),
    ),
  );
  input().setAttribute(
    "aria-activedescendant",
    `slash-${matches[slashIndex][0]}`,
  );
}
function pickSlash(key) {
  const el = input();
  const tpl = t(`slash.${key}.tpl`);
  el.value = tpl;
  autosize();
  updateComposer();
  el.focus();
  const firstBlank = tpl.search(/: ?$/m); // put the caret on the first field left to fill
  const pos = firstBlank >= 0 ? tpl.indexOf("\n", firstBlank) : -1;
  el.setSelectionRange(
    pos >= 0 ? pos : tpl.length,
    pos >= 0 ? pos : tpl.length,
  );
}

// ------------------------------------------------------------------ chat engine

function newAssistantTurn() {
  return {
    role: "assistant",
    id: uid("a"),
    steps: [],
    files: [],
    reasoning: "",
    text: "",
    answer: null,
    usage: null,
    error: null,
    confirm: null,
    status: "running",
    started: Date.now(),
    thinking: state.thinking,
    mode: activeMode(),
    ts: Date.now(),
    feedback: null,
    ui: {},
  };
}

function apiMessages(resend = false) {
  const messages = [];
  const turns = state.conv.turns;
  const lastUser = turns.map((x) => x.role).lastIndexOf("user");
  turns.forEach((turn, i) => {
    if (turn.role === "user") {
      const answered =
        turns[i + 1]?.role === "assistant" && turns[i + 1].answer?.content;
      if (i !== lastUser && !answered) return; // a request that never got an answer is not history
      // the exact text the model received for that turn (image transcriptions and notes included)
      if (turn.sent && (i !== lastUser || resend)) {
        messages.push({ role: "user", content: turn.sent });
        return;
      }
      // past images are never sent again: only a mention (what Bird read in them is in its memo)
      const notes =
        i === lastUser
          ? []
          : (turn.images || []).map(
              (img) => `[${t("att.img.note")} : ${img.name}]`,
            );
      messages.push({
        role: "user",
        content: [turn.content, ...notes].join("\n"),
      });
    } else if (turn.answer?.content) {
      const m = { role: "assistant", content: turn.answer.content };
      if (turn.answer.memo) m.memo = turn.answer.memo;
      if (["stopped", "length"].includes(turn.answer.stop_reason))
        m.interrupted = true;
      messages.push(m);
    }
  });
  // The API expects the conversation to end with the user's message.
  while (messages.length && messages[messages.length - 1].role !== "user")
    messages.pop();
  return messages;
}

function requestHeaders() {
  const p = state.prefs;
  const mode = activeMode();
  const headers = {
    "Content-Type": "application/json",
    "X-Bird-Mode": mode,
    "X-Bird-Lang": p.lang,
  };
  if (mode !== "demo" && p.access) headers["X-Bird-Access"] = p.access;
  if (mode === "user") {
    headers["X-Bird-Endpoint"] = p.endpoint;
    if (p.token) headers["X-Bird-Token"] = p.token;
    if (p.model) headers["X-Bird-Model"] = p.model;
  }
  return headers;
}

async function testEndpoint() {
  try {
    const response = await fetch("/api/endpoint/test", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ lang: state.prefs.lang }),
    });
    const data = await response.json();
    if (!response.ok)
      return {
        ok: false,
        status: data?.detail?.code || "server",
        message: httpMessage(response.status, data?.detail),
      };
    return data;
  } catch {
    return { ok: false, status: "network", message: t("error.network") };
  }
}

function httpMessage(status, detail) {
  const code = detail?.code || "";
  if (code === "access_code") return t("error.access");
  if (code === "rate_limited") return t("error.rate");
  if (code === "confirm_invalid") return t("confirm.expired");
  if (status === 413) return t("error.toolong");
  return detail?.message || `HTTP ${status}`;
}

let painting = false;
function paintSoon(turn) {
  if (painting) return;
  painting = true;
  requestAnimationFrame(() => {
    painting = false;
    updateStream(turn);
    scrollToEnd(false);
  });
}

function handleEvent(turn, event) {
  switch (event.type) {
    case "delta":
      turn.text += String(event.content ?? "");
      turn.live = null;
      return paintSoon(turn);
    case "user": {
      // the exact user text the model got: stored on the user turn and sent back as history from now on
      const turns = state.conv.turns;
      const userTurn = turns[turns.indexOf(turn) - 1];
      if (userTurn?.role === "user")
        userTurn.sent = String(event.content ?? "");
      return;
    }
    case "delta_reset":
      turn.text = "";
      break;
    case "status":
      turn.live =
        event.state === "waking"
          ? { ...event, since: turn.live?.since || Date.now() }
          : null;
      if (event.state === "waking" && (event.attempt || 1) === 1)
        announce(t("live.waking"));
      break;
    case "step": {
      const i = turn.steps.findIndex((s) => s.index === event.index);
      if (i >= 0) turn.steps[i] = event;
      else turn.steps.push(event);
      turn.live = null;
      if (event.status === "running")
        announce(
          `${t(`live.${event.tool}`) === `live.${event.tool}` ? t("live.tool") : t(`live.${event.tool}`)}…`,
        );
      break;
    }
    case "confirm":
      turn.confirm = {
        tool: event.tool,
        arguments: event.arguments,
        reason: event.reason,
        token: event.token,
      };
      turn.files.push(...(event.files || []));
      turn.status = "confirm";
      announce(t("live.confirm"));
      break;
    case "reasoning":
      turn.reasoning +=
        (turn.reasoning ? "\n\n" : "") + String(event.content ?? "");
      break;
    case "answer":
      turn.answer = {
        content: String(event.content ?? ""),
        sources: event.sources || [],
        draft_email: event.draft_email || null,
        stop_reason: event.stop_reason || "answer",
        memo: String(event.memo || ""),
        images: event.images || [],
      };
      turn.files.push(...(event.files || []));
      turn.text = "";
      announce(t("live.answer"));
      break;
    case "usage":
      turn.usage = event;
      break;
    case "error":
      turn.error = {
        code: event.code || "internal",
        message: String(event.message || t("turn.error")),
        detail: event.detail ? String(event.detail) : "",
      };
      turn.status = "error";
      break;
    default:
      break;
  }
  updateTurn(turn);
  scrollToEnd(false);
}

async function runTurn(turn, extra = {}) {
  const controller = new AbortController();
  state.abort = controller;
  state.busy = true;
  turn.status = "running";
  turn.error = null;
  updateComposer();
  updateTurn(turn);
  followTurn = turn.id;
  let finished = false;
  turn.started = Date.now();
  const ticker = window.setInterval(tick, 1000);
  try {
    const { resend, ...rest } = extra;
    extra = rest;
    if (!state.conv.cid) state.conv.cid = randomId();
    if (!state.conv.lang)
      state.conv.lang = state.prefs.lang === "en" ? "en" : "fr"; // pinned for the conversation
    const body = {
      messages: apiMessages(!!resend),
      conv_lang: state.conv.lang,
      conversation_id: state.conv.cid,
      thinking: !!turn.thinking,
      lang: state.prefs.lang,
      attachments: state.conv.attachments
        .filter((a) => a.content && !a.lost)
        .map(({ name, content, encoding }) => ({
          name,
          content,
          encoding: encoding || "text",
        })),
      ...extra,
    };
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { ...requestHeaders(), Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      let detail = null;
      try {
        detail = (await response.json()).detail;
      } catch {
        /* not JSON */
      }
      turn.error = {
        code: detail?.code || `http_${response.status}`,
        message: httpMessage(response.status, detail),
      };
      turn.status = "error";
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:")) // lines starting with ":" are heartbeats
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!data) continue;
        let event;
        try {
          event = JSON.parse(data);
        } catch {
          continue;
        }
        if (event.type === "done") finished = true;
        else handleEvent(turn, event);
      }
    }
    if (!finished && turn.status === "running") {
      turn.status = "error"; // the stream closed without its final event: proxy timeout, function killed, network
      turn.error = { code: "dropped", message: t("error.dropped") };
    } else if (turn.status === "running")
      turn.status = turn.answer ? "done" : "error";
    if (turn.status === "error" && !turn.error)
      turn.error = { code: "dropped", message: t("error.dropped") };
  } catch (error) {
    if (controller.signal.aborted) turn.status = "stopped";
    else {
      turn.status = "error";
      turn.error = {
        code: state.online ? "network" : "offline",
        message: finished
          ? String(error?.message || error)
          : t(state.online ? "error.dropped" : "toast.offline"),
      };
      if (!turn.text && !turn.steps.length)
        turn.error.message = t(
          state.online ? "error.network" : "toast.offline",
        );
    }
  } finally {
    window.clearInterval(ticker);
    state.abort = null;
    state.busy = false;
    turn.live = null;
    if (turn.status !== "confirm")
      for (const step of turn.steps)
        if (step.status === "running")
          step.status = turn.status === "stopped" ? "denied" : "error";
    if (turn.status === "stopped" && turn.text && !turn.answer)
      turn.answer = {
        content: turn.text,
        sources: [],
        draft_email: null,
        stop_reason: "stopped",
      };
    if (turn.usage && turn.status === "done" && !turn.counted) {
      turn.counted = true;
      ledgerAdd(turn.usage, state.conv.id);
    }
    renderConversation(); // the last-turn actions (regenerate, edit) depend on the busy state
    updateComposer();
    updateTop();
    saveConv();
    scrollToEnd(false);
    const sheet = document.querySelector("[data-confirm-deny]");
    if (turn.status === "confirm" && sheet) sheet.focus();
  }
}

function send(text) {
  const images = readyImages();
  let content = String(text ?? "").trim();
  if (!content && images.length) content = t("att.img.default");
  if (
    !content ||
    state.busy ||
    pendingConfirm() ||
    !state.online ||
    busyImages()
  )
    return;
  const conv = state.conv;
  if (state.editing) {
    while (
      conv.turns.length &&
      conv.turns[conv.turns.length - 1].role !== "user"
    )
      conv.turns.pop();
    conv.turns.pop();
    state.editing = false;
  }
  if (!conv.turns.length) conv.title = autoTitle(content);
  const turn = newAssistantTurn();
  const newDocs = conv.attachments.filter((a) => !a.sent && !a.lost);
  conv.turns.push(
    {
      role: "user",
      content,
      attachments: newDocs.map(({ name, size, encoding, content: c }) => ({
        name,
        size: size || (c ? c.length : 0),
        encoding: encoding || "text",
      })),
      images: images.map(({ name, w, h: hh, sent, thumb, view }) => ({
        name,
        w,
        h: hh,
        sent,
        thumb,
        view,
      })),
    },
    turn,
  );
  for (const a of newDocs) a.sent = true;
  const payload = images.map(({ name, url }) => ({ name, url }));
  lastImages = payload; // kept in memory only, so "regenerate" can send them again
  pending.images = [];
  input().value = "";
  autosize();
  renderChat();
  scrollToEnd(true);
  announce(t("live.sent"));
  input().focus();
  runTurn(turn, payload.length ? { images: payload } : {});
}

let lastImages = [];
function regenerate() {
  if (state.busy) return;
  const turns = state.conv.turns;
  if (!turns.length || turns[turns.length - 1].role !== "assistant") return;
  const conv = state.conv;
  const previous = turns[turns.length - 1];
  const turn = newAssistantTurn();
  turns[turns.length - 1] = turn;
  renderChat();
  scrollToEnd(true);
  const user = turns[turns.length - 2];
  let again = {};
  if ((user?.images || []).length && lastImages.length) {
    user.sent = undefined; // the images are still here: read them again
    again = { images: lastImages };
  } else if (user?.sent) again = { resend: true }; // reuse the exact text, transcriptions included
  const running = runTurn(turn, again);
  // the replaced answer (text, files, receipt) can come back for 8 s; what the new run cost stays counted
  toast(t("toast.regenerated"), "info", {
    ms: 8000,
    action: {
      label: t("act.undo"),
      run: async () => {
        if (state.conv !== conv || conv.turns[conv.turns.length - 1] !== turn) return;
        if (state.abort && state.busy) state.abort.abort();
        await running;
        if (state.conv !== conv || conv.turns[conv.turns.length - 1] !== turn) return;
        conv.turns[conv.turns.length - 1] = previous;
        forgetRendered();
        renderChat();
        saveConv();
        updateComposer();
        announce(t("toast.restored"));
        input().focus();
      },
    },
  });
}

// ------------------------------------------------------------------ helpers that need no model

/** Run a file step again on the server (same validation and generator, no model call). */
async function retryStep(turn, step) {
  try {
    const response = await fetch("/api/tool", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({
        tool: step.tool,
        arguments: step.arguments || {},
        lang: state.prefs.lang,
      }),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(httpMessage(response.status, data?.detail));
    if (!data.ok)
      return toast(
        t("retry.failed", { error: String(data.error || "").slice(0, 220) }),
        "error",
      );
    turn.files.push(...(data.files || []));
    step.retried = true;
    step.status = "done";
    step.summary = t("retry.done");
    updateTurn(turn);
    saveConv();
    toast(t("retry.done"), "ok");
  } catch (error) {
    toast(String(error?.message || error), "error");
  }
}

/** Any answer as a Word document (made on the server from its Markdown) or as a Markdown file (here). */
async function exportAnswer(turn, format) {
  const content = String(turn.answer?.content || "");
  const userTurn = state.conv.turns[state.conv.turns.indexOf(turn) - 1];
  const title = (state.conv.title || userTurn?.content || "Bird").slice(0, 80);
  const base =
    title
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^A-Za-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 50) || "bird";
  if (format === "md")
    return download(
      `${base}.md`,
      "text/markdown",
      new Blob([content], { type: "text/markdown" }),
    );
  try {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ format: "docx", title, content }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const mime =
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    download(
      `${base}.docx`,
      mime,
      new Blob([await response.arrayBuffer()], { type: mime }),
    );
    toast(t("export.done"), "ok");
  } catch (error) {
    toast(
      t("export.failed", { error: String(error?.message || error) }),
      "error",
    );
  }
}

function editLast() {
  if (state.busy) return;
  const lastUser = [...state.conv.turns]
    .reverse()
    .find((x) => x.role === "user");
  if (!lastUser) return;
  state.editing = true;
  input().value = lastUser.content;
  autosize();
  updateComposer();
  input().focus();
}

function answerConfirm(turn, allow, { refine = false } = {}) {
  if (state.busy || turn.status !== "confirm" || !turn.confirm) return;
  const token = turn.confirm.token;
  turn.confirm.decision = allow;
  turn.confirm.token = null; // one use: the server continues the paused run from this token
  const el = input();
  el.focus(); // whatever was typed meanwhile stays in the composer
  if (refine) {
    el.setSelectionRange(el.value.length, el.value.length);
    announce(t("confirm.refine.next"));
  }
  runTurn(turn, allow ? { approved: [token] } : { denied: [token] });
}

function stop() {
  state.abort?.abort();
}

// ------------------------------------------------------------------ wiring

function bind() {
  const el = input();
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    send(el.value);
  });
  el.addEventListener("input", () => {
    slashIndex = 0;
    autosize();
    updateComposer();
  });
  el.addEventListener("keydown", (e) => {
    const matches = !$("slash-menu").hidden && slashMatches();
    if (matches && matches.length) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        slashIndex =
          (slashIndex + (e.key === "ArrowDown" ? 1 : matches.length - 1)) %
          matches.length;
        return updateSlash();
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        return pickSlash(matches[slashIndex][0]);
      }
      if (e.key === "Escape") {
        e.stopPropagation();
        el.value = "";
        return updateComposer();
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send(el.value);
    }
  });
  el.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])].filter(isImageFile);
    if (files.length) {
      e.preventDefault(); // a pasted screenshot becomes an image attachment
      onFiles(files);
      return;
    }
    const text = e.clipboardData?.getData("text/plain") || "";
    if (text.length < PASTE_AS_FILE) return;
    e.preventDefault(); // a long paste becomes a document chip instead of flooding the message
    const n =
      state.conv.attachments.filter((a) =>
        a.name.startsWith(t("composer.pasted.name")),
      ).length + 1;
    if (addAttachment(`${t("composer.pasted.name")}-${n}.txt`, text) === true)
      toast(t("composer.attach.pasted"), "ok");
  });
  $("btn-attach").addEventListener("click", () => $("file-input").click());
  for (const id of ["file-input", "photo-camera", "photo-library"])
    $(id).addEventListener("change", (e) => {
      onFiles([...e.target.files]);
      e.target.value = "";
      setPhotoMenu(false);
    });
  $("btn-photo").addEventListener("click", () => {
    const open = $("photo-menu").hidden;
    setPhotoMenu(open);
    if (open) photoItems()[0]?.focus();
  });
  $("photo-take").addEventListener("click", () => $("photo-camera").click());
  $("photo-pick").addEventListener("click", () => $("photo-library").click());
  // the scrim takes the tap that closes the sheet, so it never reaches the example card under it
  $("photo-scrim").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    setPhotoMenu(false, true);
  });
  $("photo-menu").addEventListener("keydown", (e) => {
    const items = photoItems();
    const i = items.indexOf(document.activeElement);
    let next = null;
    if (e.key === "Escape") {
      e.stopPropagation(); // never reaches the global Escape, which would stop a streaming answer
      e.preventDefault();
      setPhotoMenu(false, true);
      return;
    }
    if (e.key === "ArrowDown") next = items[(i + 1) % items.length];
    else if (e.key === "ArrowUp") next = items[(i - 1 + items.length) % items.length];
    else if (e.key === "Home") next = items[0];
    else if (e.key === "End") next = items[items.length - 1];
    if (next) {
      e.preventDefault();
      next.focus();
    }
  });
  $("photo-menu").addEventListener("focusout", (e) => {
    if (e.relatedTarget && !e.relatedTarget.closest("#photo-menu, #btn-photo")) setPhotoMenu(false);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest?.("#photo-menu, #btn-photo")) setPhotoMenu(false);
  });
  // drag-and-drop anywhere on the composer
  const zone = $("composer");
  let depth = 0;
  zone.addEventListener("dragenter", (e) => {
    if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
    e.preventDefault();
    depth += 1;
    zone.classList.add("is-drop");
  });
  zone.addEventListener("dragover", (e) => {
    if ([...(e.dataTransfer?.types || [])].includes("Files"))
      e.preventDefault();
  });
  zone.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (!depth) zone.classList.remove("is-drop");
  });
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    depth = 0;
    zone.classList.remove("is-drop");
    onFiles([...(e.dataTransfer?.files || [])]);
  });
  bindLightbox();
  $("btn-stop").addEventListener("click", stop);
  $("btn-thinking").addEventListener("click", () => {
    state.thinking = !state.thinking;
    updateComposer();
  });
  $("editing-cancel").addEventListener("click", () => {
    state.editing = false;
    el.value = "";
    autosize();
    updateComposer();
  });
  $("btn-new").addEventListener("click", () => openConv(null) || el.focus());
  $("btn-new-top").addEventListener(
    "click",
    () => openConv(null) || el.focus(),
  );
  $("btn-menu").addEventListener("click", () =>
    setSidebar(!document.body.classList.contains("side-open")),
  );
  $("btn-side-close").addEventListener("click", () => setSidebar(false));
  $("backdrop").addEventListener("click", () => setSidebar(false));
  $("sidebar").addEventListener("keydown", trapDrawer);
  $("btn-clear").addEventListener("click", clearAll);
  $("conv-search").addEventListener("input", (e) => {
    search = e.target.value;
    renderSidebar();
  });
  $("btn-back").addEventListener("click", () => showView("chat") || el.focus());
  $("btn-model").addEventListener("click", () => showView("settings"));
  $("btn-footprint").addEventListener("click", () => showView("footprint"));
  for (const [id, view] of [
    ["nav-footprint", "footprint"],
    ["nav-settings", "settings"],
    ["nav-about", "about"],
  ])
    $(id).addEventListener("click", () => showView(view));
  $("nav-shortcuts").addEventListener("click", openShortcuts);
  $("btn-jump").addEventListener("click", () => scrollToEnd(true));
  scroller().addEventListener(
    "scroll",
    () => {
      stick = nearBottom(); // the user scrolled up: stop following the stream until they come back down
      updateJump();
    },
    { passive: true },
  );
  for (const id of ["shortcuts"]) {
    $(id).addEventListener(
      "click",
      (e) => e.target === e.currentTarget && e.currentTarget.close(),
    );
    $(`${id}-close`)?.addEventListener("click", () => $(id).close());
  }
  $("welcome").addEventListener("close", () => {
    state.prefs.welcomed = true;
    savePrefs();
    const back = $("welcome").returnTo;
    $("welcome").returnTo = null;
    // reopened from About: focus goes back to its button (redrawn if the language changed meanwhile)
    const target = back?.isConnected && back !== document.body ? back : back?.id && $(back.id);
    (target || el).focus();
  });

  // Code blocks: copy only the code (read at click time, so a block redrawn while streaming copies its latest text).
  $("conversation").addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-copy-code]");
    if (!btn) return;
    const code = btn.closest(".code-block")?.querySelector("pre code");
    if (code) copyText(code.textContent, t("code.copied"));
  });
  // Citation links move focus to the source entry.
  $("conversation").addEventListener("click", (e) => {
    const link = e.target.closest?.(".cite a");
    if (!link) return;
    const targetEl = document.getElementById(
      link.getAttribute("href").slice(1),
    );
    if (targetEl) {
      e.preventDefault();
      targetEl.focus();
      targetEl.scrollIntoView({ block: "center" });
    }
  });
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(
      document.activeElement?.tagName || "",
    );
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openConv(null);
      el.focus();
    } else if (mod && e.key.toLowerCase() === "b") {
      e.preventDefault();
      setSidebar(!document.body.classList.contains("side-open"));
    } else if (e.key === "Escape") {
      if (document.querySelector("dialog[open]")) return;
      if (isNarrow() && document.body.classList.contains("side-open"))
        setSidebar(false); // the open drawer is on top: Escape closes it first, an answer keeps streaming
      else if (state.busy) stop();
      else if (state.view !== "chat") showView("chat");
    } else if (!typing && !mod && !e.altKey && e.key === "/") {
      e.preventDefault();
      if (state.view !== "chat") showView("chat");
      el.focus();
    } else if (!typing && !mod && e.key === "?") {
      e.preventDefault();
      openShortcuts();
    }
  });
  window.addEventListener("online", () => {
    state.online = true;
    toast(t("toast.online"), "ok");
    updateComposer();
  });
  window.addEventListener("offline", () => {
    state.online = false;
    toast(t("toast.offline"), "error");
    updateComposer();
  });
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", applyTheme);
  window
    .matchMedia("(max-width: 900px)")
    .addEventListener("change", () =>
      setSidebar(!isNarrow() && store.get("bird.side") !== "0"),
    );
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error(String(response.status));
    state.health = await response.json();
    showBanner("");
    if (
      state.prefs.mode === "demo" &&
      !state.prefs.demoChosen &&
      state.health?.modes?.server
    ) {
      // a visitor who tried the demo before the operator connected a model would otherwise stay in demo mode
      state.prefs.mode = "";
      savePrefs();
      toast(t("mode.switched"), "ok");
    }
  } catch {
    state.health = null;
    showBanner(t("error.health"));
  }
}

function refreshAll() {
  applyTheme();
  applyStrings();
  forgetRendered();
  renderSidebar();
  renderChat();
  if (state.view === "footprint") renderFootprint();
  if (state.view === "settings") renderSettings();
  if (state.view === "about") renderAbout();
  updateTop();
}

async function init() {
  setHandlers({
    onConfirm: answerConfirm,
    onRegenerate: regenerate,
    onRetry: regenerate,
    onEdit: editLast,
    onChange: (turn) => (updateTurn(turn), saveConv()),
    onOpenFootprint: () => showView("footprint"),
    onOpenSettings: () => showView("settings"),
    onRetryStep: retryStep,
    onExport: exportAnswer,
    onLightbox: openLightbox,
  });
  setViewHooks({
    onPrefs: () => {
      state.thinking = !!state.prefs.thinking;
      refreshAll();
    },
    onReset: () => {
      state.convs = [];
      state.thinking = false;
      state.conv = newConv();
      refreshAll();
    },
    onSaved: updateTop,
    onExample: (text) => send(text),
    onGuardDemo: (text) => {
      openConv(null); // the protection demo runs in a fresh conversation, never appended to the one being read
      send(text);
    },
    testEndpoint,
  });
  state.convs = store.json("bird.convs", []).filter((c) => c && c.id);
  const current = store.get("bird.current");
  state.conv = (current && loadConv(current)) || newConv();
  bind();
  trackViewport();
  applyTheme();
  applyStrings();
  setSidebar(!isNarrow() && store.get("bird.side") !== "0");
  renderSidebar();
  renderChat();
  await loadHealth();
  renderChat();
  autosize();
  scrollToEnd(true);
  document.body.classList.add("ready");
  if (!state.prefs.welcomed) openWelcome();
  else input().focus();
}

init();
