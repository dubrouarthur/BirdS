// Bird web chat. Vanilla ES modules, no framework, no build step, no external request.
// The frontend depends only on the API contract: /api/health, /api/chat (SSE), /api/endpoint/test.
import {
  $,
  activeMode,
  activeModel,
  announce,
  button,
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
  updateStream,
  updateTurn,
} from "./turns.js";
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
const TEXT_EXT = /\.(txt|md|markdown|csv|tsv|json|log|rst|yaml|yml)$/i;

// ------------------------------------------------------------------ conversations (localStorage)

const newConv = () => ({
  id: uid("c"),
  title: "",
  created: Date.now(),
  updated: Date.now(),
  turns: [],
  attachments: [],
});

function slim(conv) {
  return {
    ...conv,
    turns: conv.turns
      .filter((turn) => turn.role === "user" || turn.status !== "running")
      .map((turn) => {
        if (turn.role === "user") return turn;
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
            attachments: x.attachments || [],
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

const isNarrow = () => window.matchMedia("(max-width: 900px)").matches;
function setSidebar(open) {
  document.body.classList.toggle("side-open", open);
  document.body.classList.toggle("side-closed", !open);
  delete document.documentElement.dataset.side;
  $("btn-menu").setAttribute("aria-expanded", String(open));
  $("backdrop").hidden = !(open && isNarrow());
  $("sidebar").inert = !open;
  if (!isNarrow()) store.set("bird.side", open ? "1" : "0");
  if (open && isNarrow()) $("btn-new").focus();
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
  const model = isDemo() ? `${modelLabel()} · ${t("demo.badge")}` : modelLabel();
  $("model-name").textContent = model;
  $("btn-model").classList.toggle("is-demo", isDemo());
  const label = t("nav.model", { model: isDemo() ? model : `${model} (${activeModel()})` });
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
const scroller = () => $("scroll");
const nearBottom = () =>
  scroller().scrollHeight - scroller().scrollTop - scroller().clientHeight <
  120;
function scrollToEnd(force) {
  if (force) stick = true;
  if (stick) scroller().scrollTop = scroller().scrollHeight;
  updateJump();
}
function updateJump() {
  $("btn-jump").hidden =
    state.view !== "chat" || stick || !(state.conv?.turns || []).length;
}

// ------------------------------------------------------------------ composer

const input = () => $("composer-input");

function autosize() {
  const el = input();
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
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
  const pending = pendingConfirm();
  const reason = !state.online
    ? "composer.send.offline"
    : state.busy
      ? "composer.send.busy"
      : pending
        ? "composer.send.pending"
        : !text.trim()
          ? "composer.send.empty"
          : "";
  send.disabled = !!reason;
  send.hidden = state.busy;
  send.title = t(reason || "composer.send");
  $("send-why").textContent = reason ? t(reason) : "";
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

function renderAttachments() {
  const list = state.conv?.attachments || [];
  const box = $("attachments");
  box.hidden = !list.length;
  box.replaceChildren(
    h(
      "ul",
      { class: "att-list" },
      list.map((a, i) =>
        h(
          "li",
          { class: "att" },
          icon("file"),
          h("span", { class: "att-name", text: a.name }),
          h("span", { class: "att-size num", text: fmtInt(a.content.length) }),
          h(
            "button",
            {
              class: "att-remove",
              type: "button",
              "aria-label": t("composer.attach.remove", { name: a.name }),
              onclick: () => (
                state.conv.attachments.splice(i, 1),
                renderAttachments(),
                renderEmpty(),
                saveIfStarted()
              ),
            },
            icon("cross"),
          ),
        ),
      ),
    ),
    h("p", { class: "att-note" }, icon("info"), t("composer.attach.note")),
  );
}
const saveIfStarted = () => state.conv.turns.length && saveConv();

function addAttachment(name, content) {
  const limits = state.health?.limits || {};
  const maxChars = limits.max_attachment_chars || 60_000;
  const maxCount = limits.max_attachments || 4;
  const list = state.conv.attachments;
  if (list.length >= maxCount)
    return toast(t("composer.attach.toomany", { max: maxCount }), "error");
  if (content.length > maxChars)
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
  list.push({ name: safe, content });
  renderAttachments();
  renderEmpty();
  saveIfStarted();
  return true;
}

async function onFiles(files) {
  for (const file of files) {
    if (
      !(
        TEXT_EXT.test(file.name) ||
        /^text\//.test(file.type) ||
        file.type === "application/json"
      )
    ) {
      toast(t("composer.attach.type", { name: file.name }), "error");
      continue;
    }
    if (file.size > 2_000_000) {
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
    addAttachment(file.name, await file.text());
  }
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
    thinking: state.thinking,
    mode: activeMode(),
    ts: Date.now(),
    feedback: null,
    ui: {},
  };
}

function apiMessages() {
  const messages = [];
  for (const turn of state.conv.turns) {
    if (turn.role === "user")
      messages.push({ role: "user", content: turn.content });
    else if (turn.answer?.content)
      messages.push({ role: "assistant", content: turn.answer.content });
  }
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
    case "delta_reset":
      turn.text = "";
      break;
    case "status":
      turn.live = event.state === "waking" ? event : null;
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
  let finished = false;
  try {
    const body = {
      messages: apiMessages(),
      thinking: !!turn.thinking,
      lang: state.prefs.lang,
      attachments: state.conv.attachments,
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
  const content = String(text ?? "").trim();
  if (!content || state.busy || pendingConfirm() || !state.online) return;
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
  conv.turns.push(
    { role: "user", content, attachments: conv.attachments.map((a) => a.name) },
    turn,
  );
  input().value = "";
  autosize();
  renderChat();
  scrollToEnd(true);
  announce(t("live.sent"));
  input().focus();
  runTurn(turn);
}

function regenerate() {
  if (state.busy) return;
  const turns = state.conv.turns;
  if (!turns.length || turns[turns.length - 1].role !== "assistant") return;
  const turn = newAssistantTurn();
  turns[turns.length - 1] = turn;
  renderChat();
  scrollToEnd(true);
  runTurn(turn);
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

function answerConfirm(turn, allow) {
  if (state.busy || turn.status !== "confirm" || !turn.confirm) return;
  const token = turn.confirm.token;
  turn.confirm.decision = allow;
  turn.confirm.token = null; // one use: the server continues the paused run from this token
  input().focus();
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
  $("file-input").addEventListener("change", (e) => {
    onFiles([...e.target.files]);
    e.target.value = "";
  });
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
  for (const id of ["welcome", "shortcuts"]) {
    $(id).addEventListener(
      "click",
      (e) => e.target === e.currentTarget && e.currentTarget.close(),
    );
    $(`${id}-close`)?.addEventListener("click", () => $(id).close());
  }
  $("welcome").addEventListener("close", () => {
    state.prefs.welcomed = true;
    savePrefs();
    el.focus();
  });
  $("welcome-start").addEventListener("click", () => $("welcome").close());
  $("welcome-about").addEventListener("click", () => {
    $("welcome").close();
    showView("about");
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
      if (state.busy) stop();
      else if (isNarrow() && document.body.classList.contains("side-open"))
        setSidebar(false);
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
    testEndpoint,
  });
  state.convs = store.json("bird.convs", []).filter((c) => c && c.id);
  const current = store.get("bird.current");
  state.conv = (current && loadConv(current)) || newConv();
  bind();
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
