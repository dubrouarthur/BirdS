// Bird web chat. Vanilla ES modules, no framework, no build step, no external request.
// The frontend depends only on the API contract: /api/health, /api/chat (SSE), /api/endpoint/test.
import {
  $,
  activeMode,
  activeModel,
  announce,
  b64ToBytes,
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
  localPair,
} from "./core.js";
import { wire as wireRich } from "./richcode.js";
import {
  editUser,
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
import { addNote, applyAgentEvent, countdownText, deliverablesOf } from "./agents.js";
import { cleanPlan, planNews } from "./plan.js"; // task plan checklist (w1-harness)
import * as canvas from "./canvas.js"; // the canvas beside the chat (decks, documents, code, sheets)
import { setModuleHooks } from "./modules.js";
import { applyResearchEvent } from "./research.js";
import { mountPicker, updatePicker } from "./reflexion.js"; // Mode Réflexion: the bird picker
import { normalizeChoice, thinks } from "./reflexion-data.js";
import { chipsWaiting, cleanSuggestions } from "./followups.js"; // Bird's next steps (the suggestions event)
import * as cx from "./conversation.js"; // versions, inline edit, documents in context, dialogs, back button
import * as kept from "./keep.js"; // PDFs, office files and image thumbnails kept across a reload (IndexedDB)
import { cleanTitle, contextDocs, convText, findIn, fork, switchVersion, validGroup } from "./conversation-data.js";

import { installRouting, localizeEvent, openPairDialog, refreshLocal } from "./local.js"; // Bird local (docs/LOCAL.md)
import { loadAgentMode } from "./agent-mode.js"; // Mode Agent: Auto by default; Activé for this session only
let planTimer = 0; // the plan card's countdown (Auto, high confidence)
let teamDone = false; // a team finished while the tab was hidden: « ✓ » in the tab title
// Mode Réflexion and the Settings reasoning switch say the same thing: the bird picked is the more precise choice,
// so the switch follows it; onPrefs applies the switch only when the switch itself changed
if (!!state.prefs.thinking !== state.thinking) {
  state.prefs.thinking = state.thinking;
  savePrefs();
}
let prefsThinking = !!state.prefs.thinking;
// No byte (data or heartbeat) for this long: the stream is dead. Just over 3x the server's heartbeat (10 s).
const STALL_MS = 35000;
state.agent = loadAgentMode(globalThis.localStorage, globalThis.sessionStorage);

const PASTE_AS_FILE = 3000; // characters: longer pasted text becomes an attached document
const KEEP_FILE_B64 = 400_000; // larger generated files are not kept in localStorage

// ------------------------------------------------------------------ conversations (localStorage)

// The answers being written, by conversation id: {conv, turn, controller}. Each conversation has its own; the
// composer's busy state and Stop follow the conversation on screen.
const running = new Map();
function syncBusy() {
  const r = state.conv && running.get(state.conv.id);
  state.busy = !!r;
  state.abort = r ? r.controller : null;
}

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

function browserTz() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

function slim(conv) {
  return {
    ...conv,
    // office files and PDFs are kept in memory only (too large for localStorage): after a reload they are listed
    // but must be attached again to be read
    attachments: (conv.attachments || []).map((a) =>
      a.encoding === "base64" ? { ...a, content: null, lost: true } : a,
    ),
    turns: slimTurns(conv.turns),
  };
}

/** The turns as stored, the hidden versions (« ‹ 1/2 › ») included. */
function slimTurns(list) {
  return list
    // a signed state the server no longer accepts is not kept (it holds the pages read: up to ~160 kB)
    .map((turn) => (turn.crew?.checkpoint && !(turn.crew.checkpointExp > Date.now() / 1000)
      ? { ...turn, crew: { ...turn.crew, checkpoint: "", next: "", checkpointExp: 0 } }
      : turn))
    // a team at work is kept once it sent a checkpoint: after a reload, « Reprendre la tâche » continues it; an
    // answer that heads versions is kept too (as interrupted), so the earlier versions survive a reload
    .filter((turn) => turn.role === "user" || turn.status !== "running" || turn.crew?.checkpoint || turn.alts)
    .map((turn) => {
      const out = slimTurn(turn);
      if (turn.alts && Array.isArray(turn.alts.list))
        out.alts = { at: turn.alts.at, list: turn.alts.list.map((tail) => (Array.isArray(tail) ? slimTurns(tail) : null)) };
      return out;
    });
}

function slimTurn(turn) {
  // running, or between two slices of a long task: after a reload, the task resumes from its checkpoint
  if (turn.role === "assistant" && (turn.status === "running" || turn.status === "slice"))
    turn = {
      ...turn,
      status: "error",
      error: { code: "dropped", message: t("error.dropped") },
      crew: { ...turn.crew, next: "", done: { ok: false, dropped: true, caveats: [] } },
    };
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
}

function saveConv(conv = state.conv) {
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
  // a conversation saved in the background (its answer ended after a switch) never takes the "current" slot
  if (conv === state.conv)
    store.set("bird.current", conv.turns.length ? conv.id : null);
  renderSidebar();
}

function loadConv(id) {
  const raw = store.json(`bird.conv.${id}`, null);
  if (!raw || !Array.isArray(raw.turns)) return null;
  raw.attachments = Array.isArray(raw.attachments) ? raw.attachments : [];
  raw.turns = loadTurns(raw.turns);
  return raw;
}

/** Stored turns back in memory, their hidden versions included (a broken group is dropped, never half-shown). */
function loadTurns(list) {
  return (Array.isArray(list) ? list : [])
    .filter((x) => x && (x.role === "user" || x.role === "assistant"))
    .map((x) => {
      const out =
        x.role === "user"
          ? {
              role: "user",
              ...(typeof x.id === "string" ? { id: x.id } : {}),
              content: String(x.content ?? ""),
              // the exact text the model got (image and scan transcriptions included): keep it for the history
              sent: typeof x.sent === "string" ? x.sent : undefined,
              attachments: (x.attachments || []).map((a) =>
                typeof a === "string" ? { name: a } : a,
              ),
              images: Array.isArray(x.images) ? x.images : [],
              ...(x.hidden ? { hidden: true } : {}),
            }
          : { steps: [], files: [], ...x, ui: {} };
      delete out.alts;
      if (validGroup(x.alts, x.role))
        out.alts = { at: x.alts.at, list: x.alts.list.map((tail) => (Array.isArray(tail) ? loadTurns(tail) : null)) };
      return out;
    });
}

function openConv(id) {
  if (menuFor !== null) {
    menuFor = null;
    document.removeEventListener("pointerdown", convMenuOutside, true);
  }
  if (id && id === state.conv?.id) {
    // the conversation already open (maybe still streaming): just come back to it
    showView("chat");
    closeDrawer();
    return;
  }
  // an answer being written keeps going in the background and lands in its own conversation (runTurn keeps a
  // reference to it); that conversation is opened from memory, never from its saved copy
  const conv = (id && running.get(id)?.conv) || (id && loadConv(id)) || newConv();
  state.conv = conv;
  syncBusy();
  restoreKept(conv);
  state.editing = false;
  forgetRendered();
  showView("chat");
  renderChat();
  renderSidebar();
  scrollToEnd(true);
  closeDrawer();
}

/** The thumbnails of a question's images, kept in this browser so a reload shows them (never sent anywhere). */
function keepThumbs(conv, user) {
  for (const img of user?.images || []) {
    const blob = img.thumb && kept.blobs.get(img.thumb);
    if (blob) kept.keep(conv.id, "img", `${user.id}:${img.name}`, { blob });
  }
}

/** What this browser kept of the conversation's files (IndexedDB): the PDFs and office files come back, and the
 * images of earlier messages get their thumbnails back; what is gone stays « à joindre de nouveau ». */
async function restoreKept(conv) {
  const lost = (conv.attachments || []).filter((a) => a.lost);
  const ghosts = [];
  const walk = (list) => {
    for (const turn of list || []) {
      if (turn.role === "user" && turn.id) for (const img of turn.images || []) if (!img.thumb) ghosts.push([turn, img]);
      for (const tail of turn.alts?.list || []) if (Array.isArray(tail)) walk(tail);
    }
  };
  walk(conv.turns);
  if (!lost.length && !ghosts.length) return;
  const map = await kept.load(conv.id);
  let changed = false;
  for (const doc of lost) {
    const got = map.get(`doc/${doc.name}`);
    if (got?.content) {
      Object.assign(doc, { content: got.content, encoding: got.encoding || "base64", size: got.size || doc.size, lost: false });
      changed = true;
    }
  }
  for (const [turn, img] of ghosts) {
    const blob = map.get(`img/${turn.id}:${img.name}`)?.blob;
    if (blob instanceof Blob) {
      img.thumb = URL.createObjectURL(blob);
      kept.blobs.set(img.thumb, blob);
      changed = true;
    }
  }
  if (!changed || state.conv !== conv) return;
  renderAttachments();
  updateComposer();
  renderConversation();
}

/** After the first answer: a short title summarised by the model (or a mail's subject), checked here too; the
 * start of the question stays when nothing usable comes back, or when the user renamed it meanwhile. */
async function proposeTitle(conv, turn) {
  const users = conv.turns.filter((x) => x.role === "user" && !x.hidden);
  if (users.length !== 1 || !turn.answer?.content) return;
  conv.titled = true;
  const before = conv.title;
  try {
    const response = await fetch("/api/title", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({
        question: users[0].content.slice(0, 4000),
        answer: String(turn.answer.content).slice(0, 1500),
        lang: conv.lang === "en" ? "en" : "fr",
        subject: String(turn.answer.draft_email?.subject || "").slice(0, 300),
      }),
    });
    if (!response.ok) return;
    const title = cleanTitle((await response.json())?.title, "");
    if (!title || conv.title !== before || title === before) return;
    conv.title = title;
    if (state.convs.some((c) => c.id === conv.id)) saveConv(conv);
    if (state.conv === conv) {
      updateTop();
      syncTitle();
    }
  } catch {
    /* the start of the question stays */
  }
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
let sideFocus = null; // {id, what: "more" | "open" | "menu"}: where focus goes once the list is drawn again

/** Close a row's menu (Escape, outside click, navigation); `refocus` puts focus back on its « … » button. */
function closeConvMenu(refocus = false) {
  if (menuFor === null) return;
  const id = menuFor;
  menuFor = null;
  document.removeEventListener("pointerdown", convMenuOutside, true);
  if (refocus) sideFocus = { id, what: "more" };
  renderSidebar();
}
function convMenuOutside(e) {
  if (!e.target.closest?.(`[data-conv="${CSS.escape(menuFor || "")}"]`)) closeConvMenu(false);
}
function convMenuKeys(e) {
  const items = [...e.currentTarget.querySelectorAll("[role=menuitem]")];
  const i = items.indexOf(document.activeElement);
  const go = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: items.length - 1 }[e.key];
  if (go !== undefined) {
    e.preventDefault();
    items[(go + items.length) % items.length]?.focus();
  } else if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    closeConvMenu(true);
  } else if (e.key === "Tab") closeConvMenu(false);
}

const textCache = new Map(); // conversation id -> {updated, text}: what the sidebar search reads
function searchText(c) {
  const hit = textCache.get(c.id);
  if (hit && hit.updated === c.updated) return hit.text;
  const conv = state.conv?.id === c.id ? state.conv : running.get(c.id)?.conv || loadConv(c.id);
  const text = conv ? convText(conv) : "";
  textCache.set(c.id, { updated: c.updated, text });
  return text;
}

function renderSidebar() {
  const list = $("conv-list");
  const q = search.trim();
  // the title first, then the questions and answers (accents and case ignored); a match in the text shows its snippet
  const snippets = new Map();
  const items = state.convs.filter((c) => {
    if (!q || findIn(c.title || "", q)) return true;
    const hit = findIn(searchText(c), q, 12);
    if (hit) snippets.set(c.id, hit);
    return !!hit;
  });
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
        sideFocus = { id: c.id, what: save ? "open" : "more" }; // back to the row, never to <body>
        const value = input.value.trim();
        if (save && value) {
          c.title = value;
          const conv = current ? state.conv : loadConv(c.id);
          if (conv) {
            conv.title = value;
            conv.titled = true; // the user's own title: never replaced by a proposed one
            store.set(`bird.conv.${c.id}`, JSON.stringify(slim(conv)));
          }
          store.set("bird.convs", JSON.stringify(state.convs));
          updateTop();
        }
        renderSidebar();
      };
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault(); // focus moves to the row: the same Enter must not open it (and close the drawer)
          done(true);
        }
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
        snippets.has(c.id)
          ? h(
              "span",
              { class: "cx-hit" },
              h("span", { class: "conv-title", text: title }),
              h(
                "span",
                { class: "cx-snippet", title: t("cx.search.in") },
                snippets.get(c.id).before,
                h("mark", { text: snippets.get(c.id).match }),
                snippets.get(c.id).after,
              ),
            )
          : h("span", { class: "conv-title", text: title }),
        running.has(c.id) &&
          h("span", { class: "cx-live", role: "img", "aria-label": t("cx.live.side"), title: t("cx.live.side") }),
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
          "aria-haspopup": "menu",
          "aria-expanded": String(open),
          "data-conv-more": c.id,
          onclick: () => {
            if (open) return closeConvMenu(true);
            menuFor = c.id;
            sideFocus = { id: c.id, what: "menu" };
            document.addEventListener("pointerdown", convMenuOutside, true);
            renderSidebar();
          },
          onkeydown: (e) => {
            if (e.key === "ArrowDown" && !open) {
              e.preventDefault();
              e.currentTarget.click();
            }
          },
        },
        icon("more"),
      ),
      open &&
        h(
          "div",
          {
            class: "conv-menu cx-menu",
            role: "menu",
            "aria-label": t("side.more", { title }),
            onkeydown: convMenuKeys,
          },
          button(
            "btn-quiet btn-small",
            "edit",
            t("side.rename"),
            () => {
              document.removeEventListener("pointerdown", convMenuOutside, true);
              renaming = c.id;
              menuFor = null;
              renderSidebar();
            },
            { "data-conv-act": "rename", role: "menuitem", tabindex: "-1" },
          ),
          button(
            "btn-quiet btn-small",
            "download",
            t("side.export"),
            () => exportConv(c.id),
            { "data-conv-act": "export", role: "menuitem", tabindex: "-1" },
          ),
          button(
            "btn-quiet btn-small btn-danger",
            "trash",
            t("side.delete"),
            () => deleteConv(c.id, title),
            { "data-conv-act": "delete", role: "menuitem", tabindex: "-1" },
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
  if (sideFocus) {
    const { id, what } = sideFocus;
    sideFocus = null;
    const row = list.querySelector(`[data-conv="${CSS.escape(id)}"]`);
    const el =
      what === "menu"
        ? row?.querySelector("[role=menuitem]")
        : what === "open"
          ? row?.querySelector(".conv-open")
          : row?.querySelector(".conv-more");
    el?.focus({ preventScroll: true });
  }
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
  closeConvMenu(true);
  toast(t("toast.exported"), "ok");
}

/** Delete at once, with « Annuler » in the toast for a few seconds (no blocking confirm()). */
function deleteConv(id, title) {
  running.get(id)?.controller.abort(); // an answer still being written there stops with it
  const wasOpen = state.conv?.id === id;
  const raw = wasOpen && state.conv.turns.length ? JSON.stringify(slim(state.conv)) : store.get(`bird.conv.${id}`);
  const at = state.convs.findIndex((c) => c.id === id);
  const entry = state.convs[at];
  store.set(`bird.conv.${id}`, null);
  state.convs = state.convs.filter((c) => c.id !== id);
  store.set("bird.convs", JSON.stringify(state.convs));
  if (menuFor !== null) {
    menuFor = null;
    document.removeEventListener("pointerdown", convMenuOutside, true);
  }
  if (wasOpen) openConv(null);
  else renderSidebar();
  if (!$("sidebar").contains(document.activeElement) || document.activeElement === document.body) $("conv-search").focus({ preventScroll: true });
  window.setTimeout(() => !state.convs.some((c) => c.id === id) && kept.drop(id), 9000); // after « Annuler »
  toast(t("cx.side.deleted", { title }), "ok", {
    ms: 8000,
    action: {
      label: t("act.undo"),
      run: () => {
        if (!raw || !entry || state.convs.some((c) => c.id === id)) return;
        store.set(`bird.conv.${id}`, raw);
        state.convs.splice(Math.min(Math.max(at, 0), state.convs.length), 0, entry);
        store.set("bird.convs", JSON.stringify(state.convs));
        if (wasOpen && !state.conv?.turns.length) openConv(id);
        else renderSidebar();
        sideFocus = null;
        announce(t("cx.side.restored"));
        document.querySelector(`[data-conv="${CSS.escape(id)}"] .conv-open`)?.focus({ preventScroll: true });
      },
    },
  });
}

/** « Tout effacer »: a styled dialog (light and dark, the app's tone), the safe answer focused. */
async function clearAll() {
  const ok = await cx.confirmDialog({
    title: t("cx.clear.title"),
    text: t("cx.clear.text"),
    ok: t("cx.clear.ok"),
    cancel: t("cx.clear.cancel"),
  });
  if (!ok) return;
  for (const r of running.values()) r.controller.abort();
  for (const key of store.keys("bird.conv.")) store.set(key, null);
  kept.dropAll();
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
  if (open) cx.openLayer("photo", () => setPhotoMenu(false, true));
  else cx.closedLayer("photo");
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
  // the open drawer on a phone is closed by the back button, not the app
  if (modal) cx.openLayer("drawer", () => setSidebar(false));
  else cx.closedLayer("drawer");
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
  // the back button (or swipe-back) brings Settings, Empreinte and À propos back to the chat, never out of the app
  if (view !== "chat") cx.openLayer("view", () => (showView("chat"), input().focus({ preventScroll: true })));
  else cx.closedLayer("view");
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
  $("btn-model").classList.toggle("is-local", activeMode() === "local" || !!state.health?.bird_local);
  const label = t("nav.model", {
    model: isDemo() ? model : `${model} (${activeModel()})`,
  });
  $("btn-model").setAttribute("aria-label", label);
  $("btn-model").title = label;
  const deliv = allDeliverables(state.conv);
  $("btn-deliverables").hidden = !deliv.length || state.view !== "chat";
  $("deliverables-n").textContent = deliv.length ? String(deliv.length) : "";
  const s = totals(convUsages(state.conv));
  $("footprint-total").textContent = s.n
    ? `${fmtInt(s.prompt + s.completion)} tokens`
    : t("nav.footprint");
  syncTitle();
}

/** While the model wakes up and the tab is in the background, the tab title says so. */
function syncTitle() {
  const base = state.conv?.title ? `${state.conv.title} — Bird` : t("app.title");
  const last = state.conv?.turns?.[state.conv.turns.length - 1];
  const waking = state.busy && last?.live?.state === "waking";
  // a team that finished while the tab was hidden: a mark in the tab title until the user comes back
  const mark = teamDone && document.hidden ? "✓ " : "";
  document.title = waking && document.hidden ? `${t("title.waking")} · ${base}` : mark + base;
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
            // without a document, a starter fills the composer with a short form to complete (the slash
            // templates) instead of sending a canned request into a throwaway conversation; with a
            // document, the action applies to it and is sent as is
            title: withDoc ? t(`ex.${key}.prompt`) : t(`slash.${STARTER[key]}.hint`),
            "aria-label": withDoc
              ? `${t(`ex.${key}.title`)} — ${t(`ex.${key}.prompt`)}`
              : `${t(`ex.${key}.title`)} — ${t("ex.starter.aria", { what: t(`slash.${STARTER[key]}.hint`) })}`,
            onclick: () => (withDoc ? send(t(`ex.${key}.prompt`)) : pickSlash(STARTER[key])),
          },
          h("span", { class: "chip-icon" }, icon(ico)),
          h(
            "span",
            { class: "chip-text" },
            h("span", { class: "chip-title", text: t(`ex.${key}.title`) }),
            h("span", { class: "chip-prompt", text: withDoc ? t(`ex.${key}.prompt`) : t(`ex.${key}.starter`) }),
          ),
        ),
      ),
    ),
  );
}

function renderChat() {
  canvas.setConversation(state.conv); // the canvas follows the conversation shown
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
  btn.title = t(key); // a round arrow, as in other chat apps: its words on hover and for screen readers
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

// Typing on a narrow screen hides the dock's notes (.dock.is-typing, app.css). A tap in the conversation takes the
// focus from the composer; if the notes came back at once, the dock would grow by a line mid-tap, cover the bottom of
// the conversation and the click would land on the dock instead (seen on an iPhone SE, 320 and 375 x 568: « Réessayer »,
// « Revenir au mode simple », the team's fold lost). So the notes stay hidden while a pointer is down outside the
// dock, and come back only once its click has fired.
function trackTyping() {
  const dock = $("dock");
  let held = false;
  let timer = 0;
  const sync = () => {
    if (!held)
      dock.classList.toggle("is-typing", dock.contains(document.activeElement));
  };
  dock.addEventListener("focusin", () => dock.classList.add("is-typing"));
  dock.addEventListener("focusout", () => setTimeout(sync, 0));
  document.addEventListener(
    "pointerdown",
    (e) => {
      if (dock.classList.contains("is-typing") && !dock.contains(e.target)) {
        held = true;
        clearTimeout(timer);
      }
    },
    true,
  );
  const release = () => {
    if (!held) return;
    clearTimeout(timer);
    // the click of a touch comes after pointerup (up to ~300 ms on older WebKit): let it land first
    timer = setTimeout(() => {
      held = false;
      sync();
    }, 400);
  };
  document.addEventListener("pointerup", release, true);
  document.addEventListener("pointercancel", release, true);
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
  // a document of the conversation whose content this browser lost: attach it again (or remove it) first, never
  // a question about it answered « je n'ai pas accès à vos fichiers »
  const lostDoc = (state.conv?.attachments || []).find((a) => a.lost);
  const reason = !state.online
    ? "composer.send.offline"
    : state.busy
      ? "composer.send.busy"
      : awaiting
        ? "composer.send.pending"
        : busyImages()
          ? "att.reading"
          : lostDoc
            ? "cx.ctx.lost.block"
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
  send.title = reason ? t(reason, { name: lostDoc?.name || "" }) : label;
  send.setAttribute("aria-label", label);
  const photo = $("btn-photo");
  const canImages = imagesAvailable();
  photo.setAttribute("aria-disabled", String(!canImages));
  photo.title = canImages ? t("att.photo") : t("att.img.unsupported");
  $("photo-take").hidden = $("photo-pick").hidden = !canImages;
  $("photo-note").textContent = canImages
    ? t("att.photo.note")
    : t("att.img.unsupported");
  // the paperclip counts the images too where it is the only button (no photo button on a large screen)
  const photoShown = photo.offsetParent !== null && getComputedStyle(photo).display !== "none";
  const nDocs = photoShown ? nAtt - images : nAtt;
  $("btn-attach").dataset.count = nDocs ? String(nDocs) : "";
  $("btn-photo").dataset.count = images && photoShown ? String(images) : "";
  // most reasons stay for screen readers only; a pending approval is shown, with a way to reach the request
  const why = $("send-why");
  const shown = reason === "composer.send.pending" || reason === "composer.send.offline" || reason === "cx.ctx.lost.block";
  why.className = shown ? "send-why" : "sr-only";
  why.replaceChildren(
    reason ? h("span", { text: t(reason, { name: lostDoc?.name || "" }) }) : "",
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
  updatePicker();
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
  const all = state.conv?.attachments || [];
  // the composer holds only what the next message brings; the files of earlier messages sit in their message, and
  // a small « 2 documents en contexte » pill lists them (read only when a question is about them)
  const { pending: docs, context, lost } = contextDocs(all);
  const imgs = pending.images;
  box.hidden = !docs.length && !imgs.length && !context.length && !lost.length;
  if (box.hidden) return box.replaceChildren();
  const rerender = () => (renderAttachments(), updateComposer());
  const dropDoc = (doc, said) => {
    const i = all.indexOf(doc);
    if (i < 0) return;
    announce(t(said, { name: doc.name }));
    all.splice(i, 1);
    rerender();
    renderEmpty();
    saveIfStarted();
  };
  const tray = (docs.length || imgs.length) && [
    h(
      "ul",
      { class: "att-tray cx-tray", "aria-label": t("att.tray") },
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
      docs.map((doc) =>
        h(
          "li",
          { class: `att-in${isNew(doc.name) ? " att-new" : ""}` },
          docCard(
            {
              ...doc,
              size: doc.size || (doc.content ? doc.content.length : 0),
            },
            {
              onRemove: () => dropDoc(doc, "att.removed"),
              onOpen: () => cx.previewDialog(doc),
              status: { kind: "ok", text: t("att.ready") },
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
  ];
  box.replaceChildren(
    ...(tray || []),
    cx.contextPill(context, lost, {
      onRemove: (doc) => dropDoc(doc, "cx.ctx.removed"),
      onPreview: (doc) => cx.previewDialog(doc),
      onReattach: () => $("file-input").click(),
    }) || [],
  );
}
const saveIfStarted = () => state.conv.turns.length && saveConv();

function addAttachment(name, content, encoding = "text", size = 0) {
  const limits = state.health?.limits || {};
  const maxChars = limits.max_attachment_chars || 60_000;
  const maxCount = limits.max_attachments || 4;
  const list = state.conv.attachments;
  if (list.filter((a) => !a.lost).length >= maxCount && !list.some((a) => a.lost))
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
  // the same file attached again after a reload took its content away: it takes its place back (same name)
  const lost = list.find((a) => a.lost && a.name === safe);
  if (lost) Object.assign(lost, { content, encoding, size: size || content.length, lost: false });
  else {
    for (let n = 2; list.some((a) => a.name === safe); n++)
      safe = `${stem}-${n}${ext}`;
    list.push({ name: safe, content, encoding, size: size || content.length });
  }
  if (encoding === "base64") kept.keep(state.conv.id, "doc", safe, { content, encoding, size: size || content.length });
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
const STARTER = { email: "mail", minutes: "cr", slides: "pres", search: "search" }; // empty-state chip -> template
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
    thinking: thinks(state.reflexion),
    reflexion: state.reflexion, // Mode Réflexion: « auto » or the bird chosen when the turn was sent
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
      if (["stopped", "length", "repetition"].includes(turn.answer.stop_reason))
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
  if (code === "agent_state_used") return t("agent.used");
  if (code === "pair_required" || code === "pair_invalid") return t("local.err.pair");
  if (code === "pair_locked") return t("local.err.locked");
  if (status === 413) return t("error.toolong");
  if (detail?.message) return detail.message;
  // a gateway or a cold start answers 502/503/504 with an HTML page: say it in words; the status goes in the details
  if ([502, 503, 504].includes(status)) return t("error.unavailable");
  if (status >= 500) return t("error.internal");
  return `HTTP ${status}`;
}

const painting = new Set(); // one frame per streaming turn (two conversations can stream at once)
function paintSoon(turn) {
  if (painting.has(turn)) return;
  painting.add(turn);
  requestAnimationFrame(() => {
    painting.delete(turn);
    if (!state.conv?.turns.includes(turn)) return; // written in the background: drawn when its conversation opens
    updateStream(turn);
    scrollToEnd(false);
  });
}

/** The model answered after a wake-up: keep how long the wait was, for the receipt. */
function endWake(turn) {
  if (turn.wakeStart && !turn.wake_s) turn.wake_s = Math.round((Date.now() - turn.wakeStart) / 100) / 10;
  turn.wakeStart = 0;
  if (turn.live?.state === "waking") {
    turn.live = null;
    syncTitle();
  }
}

function handleEvent(turn, event, conv = state.conv, docs = []) {
  if (turn.wakeStart && event.type !== "status") endWake(turn);
  switch (event.type) {
    case "delta":
      if (turn.cont && turn.text === turn.cont) turn.text += joinCont(turn.cont, String(event.content ?? ""));
      turn.text += String(event.content ?? "");
      if (turn.live) endWake(turn);
      turn.live = null;
      return paintSoon(turn);
    case "user": {
      if (turn.cont) return; // « Continuer »: the question stays as it was
      // the exact user text the model got: stored on the user turn and sent back as history from now on
      const turns = conv.turns;
      const userTurn = turns[turns.indexOf(turn) - 1];
      if (userTurn?.role === "user")
        userTurn.sent = String(event.content ?? "");
      return;
    }
    case "delta_reset":
      turn.text = turn.cont || "";
      break;
    case "attachment_text": {
      // what the server read on the scanned pages of a PDF: kept with the attachment and sent back, so the
      // next turns do not read (and pay for) the same pages again
      const doc = docs[event.index];
      if (doc && event.pages && typeof event.pages === "object") doc.ocr = event.pages;
      return;
    }
    case "status":
      if (event.state === "waking") {
        turn.wakeStart = turn.wakeStart || Date.now();
        turn.live = { ...event, since: turn.live?.since || Date.now(), at: Date.now() };
      } else {
        endWake(turn);
        turn.live = null;
      }
      if (event.state === "waking" && (event.attempt || 1) === 1)
        announce(t("live.waking"));
      syncTitle();
      break;
    case "step": {
      if (turn.stepBase) event = { ...event, index: event.index + turn.stepBase }; // « Continuer »: after the first steps
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
    case "widget": {
      // a pre-called tool's card (map, company, rate, forecast), sent as soon as the tool returns: shown at once and
      // kept in the turn (saved with it) even if the model then fails; the answer's own list supersedes it
      const cards = (Array.isArray(event.widgets) ? event.widgets : []).map((w) => ({ ...w, step: event.index }));
      turn.widgets = [...(turn.widgets || []).filter((w) => w.step !== event.index), ...cards];
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
    case "reflexion": // the bird the server chose or was given, before the first word (birds/harness/reflexion.py)
      turn.flight = { level: String(event.level || ""), auto: !!event.auto };
      break;
    case "reasoning":
      turn.reasoning +=
        (turn.reasoning ? "\n\n" : "") + String(event.content ?? "");
      break;
    case "answer":
      turn.answer = {
        content: turn.cont
          ? turn.cont + joinCont(turn.cont, String(event.content ?? "")) + String(event.content ?? "")
          : String(event.content ?? ""),
        sources: event.sources || [],
        draft_email: event.draft_email || null,
        stop_reason: event.stop_reason || "answer",
        memo: String(event.memo || ""),
        images: event.images || [],
        charts: Array.isArray(event.charts) ? event.charts : [],
        web_images: Array.isArray(event.web_images) ? event.web_images : [],
        code_checks: Array.isArray(event.code_checks) ? event.code_checks.slice(0, 50) : [], // syntax badges
        widgets: Array.isArray(event.widgets) ? event.widgets : [],
        fallback: event.fallback ? String(event.fallback) : "", // written from the results, not by the model
        canvas: event.canvas?.aid ? canvasRef(event.canvas) : null,
        reflexion: event.reflexion && typeof event.reflexion === "object" ? event.reflexion : null, // checked when drawn
      };
      if (event.plan !== undefined) turn.plan = cleanPlan(event.plan); // the final checklist, or none
      canvas.onAnswer(conv, turn, event.canvas);
      turn.files.push(...(event.files || []));
      turn.text = "";
      announce(t("live.answer"));
      break;
    case "plan": {
      // the task plan ticked from what really happened (birds/harness/plan.py); read out when an item is done
      const next = cleanPlan(event);
      const news = planNews(turn.plan, next);
      turn.plan = next;
      if (news) announce(news);
      break;
    }
    case "usage":
      turn.usage = event;
      break;
    case "suggestions": // Bird's next steps (birds/harness/nextsteps.py): normally late, after « final »
      if (turn.answer) turn.answer.suggestions = cleanSuggestions(event.items);
      chipsWaiting.delete(turn);
      break;
    case "agent_plan": {
      const said = applyAgentEvent(turn, event);
      if (turn.crewPlan) {
        turn.ui.planArmed = turn.crewPlan.auto > 0; // the countdown runs in this page only, never after a reload
        armPlanTimer();
      }
      if (said) announce(said);
      break;
    }
    case "canvas":
    case "canvas_media":
      if (!canvas.onEvent(conv, turn, event)) return;
      if (event.type === "canvas" && event.phase === "final") saveConv(conv); // a reload keeps each version
      break;
    case "agent_research": {
      // deep research's live board: replaced whole by each event; only its transitions are read out
      const said = applyResearchEvent(turn, event);
      if (said) announce(said);
      break;
    }
    case "agent_start":
    case "agent_step":
    case "agent_done":
    case "agent_note":
    case "agent_checks":
    case "agent_deliverable":
    case "agent_slice": {
      // the board itself is not a live region (it is redrawn on every event): only the transitions are read out
      const said = applyAgentEvent(turn, event);
      if (event.type === "agent_start" && !turn.crew?.slice) announce(t("agent.chip"));
      else if (said) announce(said);
      if (event.type === "agent_slice") saveConv(conv); // the checkpoint survives a reload
      break;
    }
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
  if (state.conv !== conv) return; // the user switched conversation: nothing on screen to update
  updateTurn(turn);
  scrollToEnd(false);
}

/** The events of an SSE response body, one by one (heartbeats skipped); ``onByte`` on every read. */
async function* sseEvents(reader, onByte) {
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    onByte(); // heartbeats included
    if (done) return;
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
      try {
        yield JSON.parse(data);
      } catch {
        /* not JSON: skipped */
      }
    }
  }
}

/** After « final »: the turn is over for the user (Send is back, a Stop changes nothing); the same stream still
 * brings its late events (Bird's next steps, the receipt that counts them) until « done ». A new turn, a lost
 * connection or a server error only end the wait: the answer stays as it is. */
async function readLate(turn, conv, events, controller, stopWatch) {
  state.late = controller;
  try {
    for (;;) {
      const { value: event, done } = await events.next();
      if (done || event.type === "done") break;
      if (event.type === "suggestions" || event.type === "usage") handleEvent(turn, event, conv);
    }
  } catch {
    /* aborted (a new turn) or dropped: nothing to undo */
  } finally {
    stopWatch();
    if (state.late === controller) state.late = null;
    const waited = chipsWaiting.delete(turn);
    countUsage(turn, conv);
    saveConv(conv);
    if (waited && state.conv === conv) updateTurn(turn); // no next steps after all: the widget chips show
  }
}

/** The turn's receipt in the local ledger (« Consommation »), once, when its last usage event is in. */
function countUsage(turn, conv) {
  if (turn.usage && turn.status === "done" && !turn.counted) {
    turn.counted = true;
    ledgerAdd(turn.usage, conv.id);
  }
}

async function runTurn(turn, extra = {}) {
  const conv = state.conv; // the conversation this answer belongs to, even if the user opens another one
  if (state.late) state.late.abort(); // the previous turn's late next steps: this new request comes first
  const controller = new AbortController();
  running.set(conv.id, { conv, turn, controller });
  syncBusy();
  renderSidebar(); // the row shows that an answer is being written
  let release;
  state.runDone = new Promise((resolve) => (release = resolve)); // awaited by « Revenir au mode simple »
  turn.status = "running";
  turn.error = null;
  updateComposer();
  updateTurn(turn);
  followTurn = turn.id;
  let finished = false;
  let late = false; // « final » came with events still to read (readLate)
  let events = null;
  turn.started = Date.now();
  const ticker = window.setInterval(tick, 1000);
  // a stream that goes silent (tunnel, Wi-Fi to 4G handover, NAT timeout) never ends on its own: the server sends
  // a heartbeat every 10 s, so no byte for STALL_MS means the connection is gone
  let stalled = false;
  let lastByte = Date.now();
  let watchdog = 0;
  const onVisible = () => {
    if (!document.hidden) lastByte = Date.now(); // a background tab's reads were paused, not lost
  };
  try {
    const { resend, ...rest } = extra;
    extra = rest;
    if (!conv.cid) conv.cid = randomId();
    if (!conv.lang)
      conv.lang = state.prefs.lang === "en" ? "en" : "fr"; // pinned for the conversation
    const docs = conv.attachments.filter((a) => a.content && !a.lost);
    // the files this message brings: a table of an earlier message is analysed only when the turn asks for it
    const lastUser = conv.turns.filter((x) => x.role === "user").pop();
    const brought = new Set((lastUser?.attachments || []).map((a) => a.name));
    const body = {
      messages: apiMessages(!!resend),
      conv_lang: conv.lang,
      conversation_id: conv.cid,
      tz: browserTz(),
      thinking: !!turn.thinking,
      reflexion: normalizeChoice(turn.reflexion || state.reflexion),
      agent: turn.agent || state.agent, // "off" for the resend of « Revenir au mode simple »
      // a decided team starts at once: no plan card to approve (asked for nothing but the task); "run" lets the
      // server split a long task into slices the app continues on its own
      // (the plan-card-first flow stays for its tests: localStorage « bird.agentPlan » = "1")
      ...((turn.agent || state.agent) !== "off" ? { agent_flow: store.get("bird.agentPlan") === "1" ? "plan" : "run" } : {}),
      lang: state.prefs.lang,
      attachments: docs.map(({ name, content, encoding, ocr }) => ({
        name,
        content,
        encoding: encoding || "text",
        fresh: brought.has(name),
        ...(ocr && encoding === "base64" ? { ocr } : {}),
      })),
      ...canvas.payload(conv), // the artifact open in the canvas, so « ajoute une slide » changes it
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
        detail: `HTTP ${response.status}`, // the raw status, folded under "Détails techniques"
      };
      turn.status = "error";
      return;
    }
    const reader = response.body.getReader();
    lastByte = Date.now();
    document.addEventListener("visibilitychange", onVisible);
    watchdog = window.setInterval(() => {
      if (!document.hidden && Date.now() - lastByte > STALL_MS) {
        stalled = true;
        controller.abort();
      }
    }, 5000);
    events = sseEvents(reader, () => (lastByte = Date.now()));
    for (;;) {
      const { value: event, done } = await events.next();
      if (done) break;
      if (event.type === "done") finished = true;
      else if (event.type === "final") {
        // the answer and its receipt are in: the turn ends here for the user, late events follow (readLate)
        finished = true;
        late = Array.isArray(event.pending) && event.pending.length > 0;
        if (late && event.pending.includes("suggestions") && turn.answer) chipsWaiting.add(turn);
        break;
      } else handleEvent(turn, turn.mode === "local" ? localizeEvent(event) : event, conv, docs);
    }
    if (finished && turn.status === "running" && !turn.answer) {
      // the plan card waits for « Lancer »; a long task's slice ended: the next one starts below
      if (turn.crewPlan && ["pending", "editing"].includes(turn.crewPlan.status) && !turn.crew) turn.status = "plan";
      else if (turn.crew?.next && !turn.crew.done) turn.status = "slice";
    }
    if (!finished && turn.status === "running") {
      turn.status = "error"; // the stream closed without its final event: proxy timeout, function killed, network
      turn.error = { code: "dropped", message: t("error.dropped") };
    } else if (turn.status === "running")
      turn.status = turn.answer ? "done" : "error";
    if (turn.status === "error" && !turn.error)
      turn.error = { code: "dropped", message: t("error.dropped") };
  } catch (error) {
    if (stalled) {
      turn.status = "error"; // not the user's Stop: the « Réessayer » card
      turn.error = { code: "dropped", message: t("error.dropped") };
    } else if (controller.signal.aborted) turn.status = "stopped";
    else if (turn.mode === "local" && !finished && state.online) {
      turn.status = "error"; // the user's machine did not answer: the three steps to start Bird local
      turn.error = { code: "local_unreachable", message: t("local.down.title") };
    } else {
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
    const stopWatch = () => {
      window.clearInterval(watchdog);
      document.removeEventListener("visibilitychange", onVisible);
    };
    late = late && turn.status === "done";
    if (late) readLate(turn, conv, events, controller, stopWatch);
    else {
      stopWatch();
      chipsWaiting.delete(turn);
    }
    // the team did not report its end: the user stopped it, the server failed, or the connection was lost
    if (turn.status === "stopped" && turn.crew) turn.crew.checkpoint = ""; // Stop frees everything: no resume
    if (turn.crew && !turn.crew.done && !["confirm", "slice"].includes(turn.status))
      applyAgentEvent(turn, {
        type: "agent_done",
        ok: false,
        stopped: turn.status === "stopped",
        error: turn.status !== "stopped",
        dropped: turn.status === "error" && ["dropped", "network", "offline"].includes(turn.error?.code),
        caveats: [],
      });
    if (running.get(conv.id)?.controller === controller) running.delete(conv.id);
    syncBusy();
    if (turn.wakeStart) endWake(turn);
    turn.live = null;
    syncTitle();
    if (!["confirm", "slice"].includes(turn.status))
      for (const step of turn.steps)
        if (step.status === "running") {
          if (turn.status === "stopped") turn.stoppedAt = step.tool; // named in the notice
          step.status = turn.status === "stopped" ? "stopped" : "error";
        }
    if (turn.status === "stopped" && turn.text && !turn.answer)
      turn.answer = {
        content: turn.text,
        sources: [],
        draft_email: null,
        stop_reason: "stopped",
      };
    if (turn.cont) {
      delete turn.cont; // « Continuer » is over: the answer is one text again
      delete turn.stepBase;
    }
    if (turn.status === "done" && !conv.titled) proposeTitle(conv, turn);
    if (!late) countUsage(turn, conv); // with late events: once their receipt is in (readLate)
    const shown = state.conv === conv;
    if (shown) renderConversation(); // the last-turn actions (regenerate, edit) depend on the busy state
    else if (turn.status === "done") toast(t("cx.live.done", { title: conv.title || t("side.untitled") }), "ok", {
      action: { label: t("deliv.show"), run: () => openConv(conv.id) },
    });
    if (shown && turn.status === "stopped") announce(t("turn.stopped"));
    else if (shown && turn.status === "error" && turn.error) {
      // the sentence the error notice shows (a raw internal message is never read out)
      const shownText = document.querySelector(`[data-turn="${turn.id}"] .notice-text p`)?.textContent;
      announce(shownText || turn.error.message);
    }
    if (shown) {
      updateComposer();
      updateTop();
    }
    saveConv(conv);
    if (shown) scrollToEnd(false);
    if (turn.status === "slice") window.setTimeout(() => continueSlice(turn, conv), 0);
    else if (turn.crew?.done?.ok) notifyDone(turn);
    const sheet = document.querySelector("[data-confirm-deny]");
    if (turn.status === "confirm" && sheet) sheet.focus();
    release();
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
    busyImages() ||
    (state.conv.attachments || []).some((a) => a.lost) // attach it again or remove it first (the pill says so)
  )
    return;
  const conv = state.conv;
  const prev = conv.turns[conv.turns.length - 1];
  if (prev?.status === "plan" && prev.crewPlan) {
    prev.crewPlan.status = "declined"; // a new message instead of « Lancer »: the plan is set aside
    prev.status = "done";
    prev.crewNote = t("agent.plan.declined");
  }
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
      id: uid("u"),
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
  keepThumbs(conv, conv.turns[conv.turns.length - 2]);
  saveConv(conv); // the question is stored before the answer starts: a reload or a switch never loses it
  const payload = images.map(({ name, url }) => ({ name, url }));
  sentImages.set(conv.turns[conv.turns.length - 2], payload);
  pending.images = [];
  input().value = "";
  autosize();
  renderChat();
  scrollToEnd(true);
  announce(t("live.sent"));
  input().focus();
  runTurn(turn, payload.length ? { images: payload } : {});
}

const sentImages = new WeakMap(); // user turn -> the images it sent (in memory only), for a regenerate or an edit

/** The request part that sends the question of `user` again: its images while this page still has them, else the
 * exact text the model got (transcriptions included). */
function againFor(user) {
  const imgs = (user && sentImages.get(user)) || [];
  if ((user?.images || []).length && imgs.length) {
    user.sent = undefined; // the images are still here: read them again
    return { images: imgs };
  }
  return user?.sent ? { resend: true } : {};
}

/** A new answer to the question before turns[at] (the last answer by default). The answer it replaces stays one
 * click away: the « ‹ 1/2 › » pager under the answer. */
function regenerate(at) {
  if (state.busy) return;
  const conv = state.conv;
  const turns = conv.turns;
  const i = Number.isInteger(at) ? at : turns.length - 1;
  if (turns[i]?.role !== "assistant" || turns[i - 1]?.role !== "user") return;
  const failed = turns[i].status === "error";
  const turn = newAssistantTurn();
  fork(turns, i, [turn]);
  if ($("scroll").contains(document.activeElement)) keepFocus(); // the Regenerate button is about to be redrawn
  renderChat();
  scrollToEnd(true);
  announce(t(failed ? "cx.retry.note" : "toast.regenerated"));
  runTurn(turn, againFor(turns[i - 1]));
}

/** What goes between the words written before Stop and the ones « Continuer » adds. */
function joinCont(before, next) {
  return !before || /\s$/.test(before) || /^[\s.,;:!?)\]»]/.test(next) ? "" : " ";
}

/** « Continuer »: the stopped answer is picked up where it stopped, in the same turn (no new question shown). */
function continueAnswer(turn) {
  const conv = state.conv;
  const turns = conv.turns;
  if (state.busy || turns[turns.length - 1] !== turn || !turn.answer?.content || !state.online) return;
  const partial = turn.answer.content;
  const messages = [
    ...apiMessages(true), // up to the question (its exact text)
    { role: "assistant", content: partial, interrupted: true },
    { role: "user", content: t("cx.continue.prompt") },
  ];
  turn.cont = partial;
  turn.text = partial;
  turn.answer = null;
  turn.stepBase = turn.steps.length;
  turn.counted = false;
  keepFocus();
  runTurn(turn, { messages });
}

/** Show version j of the group headed by turns[i] (an answer regenerated, a question edited). */
function showVersion(i, j) {
  if (state.busy) return;
  const turns = state.conv.turns;
  if (!switchVersion(turns, i, j)) return;
  const g = turns[i].alts;
  renderChat();
  saveConv();
  updateComposer();
  announce(t("cx.ver.shown", { at: g.at + 1, n: g.list.length }));
  const at = document.querySelectorAll("#conversation > .turn")[i];
  at?.querySelector(`[data-act="${j < g.list.length - 1 ? "ver-prev" : "ver-next"}"]:not(:disabled), [data-act^="ver-"]:not(:disabled)`)?.focus({ preventScroll: true });
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

/** A chart's data as an .xlsx, made by the existing make_sheet generator on the server (no model call). */
async function chartXlsx(turn, spec) {
  try {
    const response = await fetch("/api/tool", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({
        tool: "make_sheet",
        arguments: {
          title: String(spec.title || "Graphique").slice(0, 120),
          columns: spec.columns,
          rows: spec.rows,
        },
        lang: state.prefs.lang,
      }),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(httpMessage(response.status, data?.detail));
    const file = (data.files || [])[0];
    if (!data.ok || !file?.data) return toast(t("chart.xlsx.error"), "error");
    download(
      file.name,
      file.mime,
      new Blob([b64ToBytes(file.data)], { type: file.mime }),
    );
  } catch {
    toast(t("chart.xlsx.error"), "error");
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
    if (!response.ok) {
      let detail = null;
      try {
        detail = (await response.json()).detail;
      } catch {
        /* not JSON */
      }
      throw new Error(httpMessage(response.status, detail));
    }
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

/** « Modifier » on the last question (shortcut): it opens in place, like any other. */
function editLast() {
  if (state.busy) return;
  editUser([...state.conv.turns].reverse().find((x) => x.role === "user" && !x.hidden));
}

/** A question edited in place: a new version of the conversation from there, its files and images kept. */
function editSend(i, text) {
  const conv = state.conv;
  const turns = conv.turns;
  const old = turns[i];
  if (state.busy || old?.role !== "user" || !state.online) return renderChat();
  // the text the model got for it, with the new words in front: image transcriptions and file notes stay
  const sent = old.sent && old.sent.startsWith(old.content) ? text + old.sent.slice(old.content.length) : undefined;
  const user = {
    role: "user",
    id: uid("u"),
    content: text,
    attachments: (old.attachments || []).map((a) => ({ ...a })),
    images: (old.images || []).map((img) => ({ ...img })),
    ...(sent ? { sent } : {}),
  };
  const imgs = sentImages.get(old);
  if (imgs) sentImages.set(user, imgs);
  const turn = newAssistantTurn();
  fork(turns, i, [user, turn]);
  keepThumbs(conv, user);
  if (i === 0) conv.title = autoTitle(text);
  saveConv(conv);
  renderChat();
  scrollToEnd(true);
  announce(t("live.sent"));
  runTurn(turn, againFor(user));
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

/** Keep the keyboard user's place when the button they pressed disappears (Stop, Regenerate). On a touch
 * screen the focus is left alone: moving it would pop the keyboard up. */
function keepFocus() {
  if (window.matchMedia?.("(pointer: fine)").matches) input().focus({ preventScroll: true });
}

/** « Revenir au mode simple »: stop the team, then send the same request again with Mode Agent off, for this
 * request only (the composer setting is unchanged). */
async function agentOff(turn) {
  const conv = state.conv;
  if (conv.turns[conv.turns.length - 1] !== turn) return;
  const done = state.runDone;
  stop();
  await done;
  if (state.conv !== conv || conv.turns[conv.turns.length - 1] !== turn || state.busy) return;
  const fresh = newAssistantTurn();
  fresh.agent = "off";
  conv.turns[conv.turns.length - 1] = fresh;
  renderChat();
  keepFocus(); // the button pressed is gone with the team: the keyboard user lands in the composer, not on <body>
  scrollToEnd(true);
  runTurn(fresh, againFor(conv.turns[conv.turns.length - 2]));
}

// ------------------------------------------------------------------ Mode Agent, wave 2: plan, notes, slices

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && teamDone) {
    teamDone = false;
    syncTitle();
  }
});

/** The plan cards counting down (Auto, high confidence): the text is updated in place, the team starts at 0. */
function armPlanTimer() {
  if (planTimer) return;
  planTimer = window.setInterval(() => {
    const turn = state.conv?.turns?.[state.conv.turns.length - 1];
    const cp = turn?.crewPlan;
    if (!cp || turn.status !== "plan" || cp.status !== "pending" || !turn.ui?.planArmed) {
      window.clearInterval(planTimer);
      planTimer = 0;
      return;
    }
    const left = document.querySelector(`[data-turn="${turn.id}"] [data-plan-count]`);
    if (left) left.textContent = countdownText(cp);
    if (Date.now() >= cp.deadline) {
      window.clearInterval(planTimer);
      planTimer = 0;
      launchPlan(turn);
    }
  }, 250);
}

/** « Lancer »: the signed plan and the typed fields the user changed (the server validates each one again). */
function launchPlan(turn) {
  const cp = turn.crewPlan;
  if (state.busy || turn.status !== "plan" || !cp || !cp.token) return;
  cp.status = "launched";
  turn.ui.planArmed = false;
  const edits = {};
  for (const k of ["audience", "length", "n_slides", "sections", "prefer", "exclude", "focus"])
    if (cp.edits[k] !== undefined) edits[k] = cp.edits[k];
  cp.plan = { ...cp.plan, ...edits };
  const token = cp.token;
  cp.token = null; // one use
  keepFocus(); // the card and its buttons are gone: the keyboard user lands in the composer, never on <body>
  runTurn(turn, { agent_plan: { token, edits } });
}

function editPlan(turn) {
  const cp = turn.crewPlan;
  if (!cp || turn.status !== "plan") return;
  cp.status = cp.status === "editing" ? "pending" : "editing";
  turn.ui.planArmed = false; // editing stops the countdown: the user launches when ready
  cp.deadline = 0;
  updateTurn(turn);
  const first = document.querySelector(
    `[data-turn="${turn.id}"] ${cp.status === "editing" ? ".plan-editor input" : '[data-act="plan-edit"]'}`,
  );
  first?.focus({ preventScroll: true });
}

/** « Ajouter une consigne »: sent at once to the team at work, or queued for its next slice. */
async function sendNote(turn, note) {
  const crew = turn.crew;
  if (!crew || crew.done) return;
  const id = `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  let delivered = false;
  let value = note.value;
  try {
    const r = await fetch("/api/agent/note", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ run: crew.run, kind: note.kind, value: note.value, id }),
    });
    if (r.status === 422) {
      toast(t("agent.note.invalid"), "error");
      return;
    }
    if (r.ok) {
      const got = await r.json();
      delivered = !!got.delivered;
      value = String(got.value || value);
    }
  } catch {
    /* offline or another instance: the note goes with the next slice */
  }
  addNote(turn, { id, kind: note.kind, value }, delivered);
  updateTurn(turn);
  document.querySelector(`[data-turn="${turn.id}"] [data-act="agent-note"]`)?.focus({ preventScroll: true });
}

/** The next slice of a long task: the signed state the server sent, the notes it has not seen yet. */
function continueSlice(turn, conv) {
  if (state.busy || turn.status !== "slice" || !turn.crew?.next || state.conv !== conv) return;
  const token = turn.crew.next;
  turn.crew.next = "";
  const notes = turn.crew.notes.filter((n) => n.status === "queued");
  for (const n of notes) n.status = "sent";
  runTurn(turn, { agent_slice: token, agent_notes: notes.map(({ id, kind, value }) => ({ id, kind, value })) });
}

/** « Reprendre la tâche » after a reload or a lost connection: from the last checkpoint (the research is kept). */
function resumeTask(turn) {
  const conv = state.conv;
  if (state.busy || !turn.crew?.checkpoint || conv.turns[conv.turns.length - 1] !== turn) return;
  const token = turn.crew.checkpoint;
  turn.crew.done = null;
  turn.error = null;
  turn.crew.next = "";
  runTurn(turn, { agent_slice: token });
}

/** The team finished while the tab was hidden: a mark in the tab title, and a notification if allowed. */
function notifyDone(turn) {
  if (!document.hidden) return;
  teamDone = true;
  syncTitle();
  try {
    if (window.Notification?.permission === "granted") {
      const name = (turn.files || [])[0]?.name || state.conv?.title || "";
      new Notification(t("agent.notify.title"), { body: t("agent.notify.body", { t: name }), tag: turn.id });
    }
  } catch {
    /* notifications blocked: the title mark is enough */
  }
}

function askNotify() {
  try {
    window.Notification?.requestPermission?.().then(() => renderConversation());
  } catch {
    /* not supported */
  }
}

/** « Livrables »: every file of the conversation, newest first, with its turn and a download. */
/** What the conversation made, newest first: the canvas's decks, documents, pages and sheets (with their versions),
 * the mails drafted in the chat, and the other files. A file shown by a canvas card is listed once, as the canvas. */
function allDeliverables(conv) {
  if (!conv) return [];
  const turns = conv.turns || [];
  const inCanvas = new Set(turns.flatMap((x) => x.answer?.canvas?.files || []));
  const out = [];
  for (const a of Object.values(conv.canvas?.list || {})) {
    const last = a?.versions?.at(-1);
    if (!last) continue;
    const doc = a.versions[a.cur]?.doc || last.doc;
    out.push({ type: "canvas", aid: a.aid, kind: a.kind, title: doc?.title || t(`cv.kind.${a.kind}`), n: a.versions.length, at: last.at || 0 });
  }
  turns.forEach((turn, i) => {
    const mail = turn.role === "assistant" && turn.answer?.draft_email;
    if (mail?.subject)
      out.push({ type: "mail", turn: turn.id, title: String(mail.subject), to: [].concat(mail.to || []).join(", "), at: turn.ts || i });
  });
  for (const d of deliverablesOf(conv)) if (!inCanvas.has(d.name)) out.push({ type: "file", ...d, at: 0 });
  return out.sort((x, y) => (y.at || 0) - (x.at || 0));
}

function openDeliverables() {
  const dialog = $("deliverables");
  const body = $("deliverables-body");
  body.replaceChildren();
  const list = allDeliverables(state.conv);
  if (!list.length) body.append(h("p", { class: "hint", text: t("deliv.empty") }));
  const showTurn = (turnId, sel) => {
    dialog.close();
    const el = (sel && document.querySelector(`[data-turn="${turnId}"] ${sel}`)) || document.querySelector(`[data-turn="${turnId}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    el?.querySelector("button")?.focus({ preventScroll: true });
  };
  const item = (badge, cls, title, meta, ...acts) =>
    h(
      "li",
      { class: "deliv-item" },
      h("span", { class: `deliv-ic ${cls}`, "aria-hidden": "true", text: badge }),
      h("div", { class: "deliv-text" }, h("p", { class: "deliv-name", text: title }), h("p", { class: "deliv-meta", text: meta })),
      h("div", { class: "deliv-acts" }, ...acts),
    );
  const ul = h("ul", { class: "deliv-list" });
  for (const d of list) {
    if (d.type === "canvas") {
      const kind = t(`cx.deliv.kind.${d.kind}`) === `cx.deliv.kind.${d.kind}` ? t("deliv.kind.file") : t(`cx.deliv.kind.${d.kind}`);
      const badge = { deck: "PPT", doc: "DOC", code: "</>", sheet: "XLS", page: "WEB" }[d.kind] || "•";
      const cls = { deck: "is-slides", doc: "is-document", sheet: "is-sheet" }[d.kind] || "is-file";
      ul.append(
        item(badge, cls, d.title, [kind, d.n > 1 ? t("cx.deliv.versions", { n: d.n }) : "v1"].join(" · "),
          h("button", { class: "btn btn-primary btn-small", type: "button", "data-deliv": "open", text: t("cx.deliv.open"),
            onclick: () => (dialog.close(), canvas.open(d.aid)) }),
        ),
      );
    } else if (d.type === "mail") {
      ul.append(
        item("@", "cx-deliv-mail", d.title, [t("cx.deliv.kind.mail"), d.to && t("cx.deliv.mail.to", { to: d.to })].filter(Boolean).join(" · "),
          h("button", { class: "btn btn-outline btn-small", type: "button", "data-deliv": "show", text: t("deliv.show"),
            onclick: () => showTurn(d.turn, ".email-card") }),
        ),
      );
    } else {
      const acts = [
        h("button", { class: "btn btn-outline btn-small", type: "button", text: t("deliv.show"),
          onclick: () => showTurn(d.turn, `.file-card[data-file="${CSS.escape(d.name.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 120))}"]`) }),
      ];
      if (d.file.data)
        acts.push(
          h("button", { class: "btn btn-primary btn-small", type: "button", text: t("files.download"),
            onclick: () => download(d.name, d.file.mime || "application/octet-stream", new Blob([b64ToBytes(d.file.data)], { type: d.file.mime || "application/octet-stream" })) }),
        );
      ul.append(
        item((d.name.match(/\.([a-z0-9]{1,5})$/i) || ["", "?"])[1].toUpperCase(), `is-${d.kind}`, d.title,
          [t(`deliv.kind.${d.kind}`), d.team && t("deliv.team"), !d.file.data && t("deliv.lost")].filter(Boolean).join(" · "), ...acts),
      );
    }
  }
  if (list.length) body.append(ul);
  if (!dialog.open) {
    dialog.returnTo = document.activeElement;
    dialog.showModal();
  }
}

function stop() {
  syncBusy();
  if (!state.abort) return;
  if (document.activeElement?.id === "btn-stop") keepFocus();
  state.abort.abort();
}

// ------------------------------------------------------------------ wiring

function bind() {
  const el = input();
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    send(el.value);
  });
  // a tap on Send keeps the focus (and the phone keyboard) in the message box, so the layout does not move under the finger
  $("btn-send").addEventListener("mousedown", (e) => e.preventDefault());
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
  mountPicker($("rf-slot"), (choice) => {
    state.reflexion = choice;
    state.thinking = thinks(choice);
    store.set("bird.reflexion", choice);
    // the Settings switch follows the bird picked, so a later Settings change never undoes this choice
    if (!!state.prefs.thinking !== state.thinking) {
      state.prefs.thinking = state.thinking;
      savePrefs();
    }
    prefsThinking = state.thinking;
    announce(t("rf.changed", { name: t(`rf.level.${choice}`) }));
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
  $("btn-model").addEventListener("click", () => {
    showView("settings"); // the model pill opens the model choice (Bird local included)
    $("settings-model")?.scrollIntoView({ block: "start" });
  });
  $("btn-footprint").addEventListener("click", () => showView("footprint"));
  for (const [id, view] of [
    ["nav-footprint", "footprint"],
    ["nav-settings", "settings"],
  ])
    $(id).addEventListener("click", () => showView(view));
  // "À propos" opens the corporate site (served under /a-propos/ by the same deployment)
  $("nav-about").addEventListener("click", () => {
    if (state.health?.site_url) window.location.href = state.health.site_url;
    else showView("about");
  });
  $("nav-shortcuts").addEventListener("click", openShortcuts);
  $("btn-jump").addEventListener("click", () => scrollToEnd(true));
  document.addEventListener("visibilitychange", syncTitle);
  scroller().addEventListener(
    "scroll",
    () => {
      stick = nearBottom(); // the user scrolled up: stop following the stream until they come back down
      updateJump();
    },
    { passive: true },
  );
  $("btn-deliverables").addEventListener("click", openDeliverables);
  $("deliverables").addEventListener("close", () => {
    const back = $("deliverables").returnTo;
    $("deliverables").returnTo = null;
    if (back?.isConnected) back.focus({ preventScroll: true });
  });
  for (const id of ["shortcuts", "deliverables"]) {
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

  // Code blocks: wrap, download, expand; formula chips; folded lists (delegated once, see richcode.js).
  wireRich($("conversation"), { copy: (text, done) => copyText(text, done), download });
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
      if (e.defaultPrevented || document.querySelector("dialog[open]")) return;
      const target = e.target;
      // Escape in another field (the conversation search, a rename box) never stops the answer that is being
      // written; it still closes the drawer or leaves a page view (the stop() branch below checks the target)
      if (isNarrow() && document.body.classList.contains("side-open"))
        setSidebar(false); // the open drawer is on top: Escape closes it first, an answer keeps streaming
      else if (state.busy) {
        const where = target?.id || (target === document.body ? "body" : "");
        if (!target || ["composer-input", "body", "scroll", "btn-stop"].includes(where))
          stop();
      } else if (state.view !== "chat") showView("chat");
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
  // a cold start or a slow network must never drop a visitor into the demo: retry before giving up
  let health = null;
  for (const wait of [0, 800, 2000, 4000]) {
    if (wait) await new Promise((r) => setTimeout(r, wait));
    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error(String(response.status));
      health = await response.json();
      break;
    } catch {
      /* next attempt */
    }
  }
  if (!health) {
    state.health = null;
    showBanner(t("error.health"));
    // never leave the page believing there is no model: keep asking quietly, then show the real state
    clearTimeout(loadHealth.retry);
    loadHealth.retry = setTimeout(() => loadHealth().then(() => state.health && refreshAll()), 5000);
    return;
  }
  state.health = health;
  showBanner("");
  if (state.prefs.mode === "demo" && state.health?.modes?.server) {
    // a real model is connected: the demo is gone, whatever an earlier visit stored
    state.prefs.mode = "";
    state.prefs.demoChosen = false;
    savePrefs();
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

let canvasClosedSide = false; // the canvas closed the sidebar: it opens again when the canvas closes
async function init() {
  cx.ensureStyles();
  cx.bindLayers(); // back closes the open layer (drawer, canvas, sheet, Settings, a dialog)
  cx.watchLayer("canvas", document.documentElement, () => document.documentElement.classList.contains("cv-open"), () => canvas.close());
  installRouting(); // Bird local: in its mode, the page's /api/ calls go to the user's machine
  setHandlers({
    onConfirm: answerConfirm,
    onRegenerate: (turn) => regenerate(state.conv.turns.indexOf(turn)),
    onRetry: (turn) => regenerate(state.conv.turns.indexOf(turn)),
    onVersion: showVersion,
    onEdit: editLast,
    onEditSend: editSend,
    onContinue: continueAnswer,
    onChange: (turn) => (updateTurn(turn), saveConv()),
    onOpenFootprint: () => showView("footprint"),
    onOpenSettings: () => showView("settings"),
    onLocalOff: () => {
      state.prefs.mode = "";
      savePrefs();
      refreshAll();
    },
    onRetryStep: retryStep,
    onChartXlsx: chartXlsx,
    onExport: exportAnswer,
    onLightbox: openLightbox,
    onAgentOff: agentOff,
    onSuggest: (text) => send(text), // follow-up chips and transforms (followups.js)
    onPlanLaunch: launchPlan,
    onPlanEdit: editPlan,
    onAgentNote: sendNote,
    onNoteToggle: (turn) => {
      turn.ui.noteOpen = !turn.ui.noteOpen;
      updateTurn(turn);
      if (turn.ui.noteOpen)
        document.querySelector(`[data-turn="${turn.id}"] [data-note-form] [data-note-value]`)?.focus({ preventScroll: true });
    },
    onCrewToggle: (turn) => {
      turn.ui.crewCollapsed = !turn.ui.crewCollapsed;
      updateTurn(turn);
      document.querySelector(`[data-turn="${turn.id}"] [data-act="agent-toggle"]`)?.focus({ preventScroll: true });
    },
    onStop: stop,
    onResume: resumeTask,
    onNotify: askNotify,
  });
  // data card hook (datakit.js): « Modifier le graphique » sends its edit as the next message
  window.addEventListener("bird:send", (e) => {
    if (state.busy || !state.online || pendingConfirm()) return; // the composer gets the text instead
    e.preventDefault();
    send(String(e.detail?.text || ""));
  });
  canvas.setup({
    send: (text) => send(text),
    compose: (text) => {
      input().value = text;
      autosize();
      input().focus();
      input().setSelectionRange(text.length, text.length);
    },
    headers: requestHeaders,
    save: (c) => saveConv(c),
    // a document changed in the canvas (an edit, a chosen variant, a restore): its cards in the chat follow
    changed: (aid) => {
      for (const tn of state.conv?.turns || []) if (tn.answer?.canvas?.aid === aid) updateTurn(tn);
    },
    busy: () => state.busy || !!pendingConfirm(),
    mode: activeMode,
    // on a laptop the canvas takes the sidebar's room while it is open; the saved preference is kept
    onOpen: () => {
      if (isNarrow() || window.innerWidth >= 1700 || !document.body.classList.contains("side-open")) return;
      const keep = store.get("bird.side");
      setSidebar(false);
      store.set("bird.side", keep);
      canvasClosedSide = true;
    },
    onClose: () => {
      if (!canvasClosedSide || isNarrow()) return;
      canvasClosedSide = false;
      const keep = store.get("bird.side");
      setSidebar(true);
      store.set("bird.side", keep);
    },
  });
  setModuleHooks({ onChange: () => saveConv(), onSuggest: (text) => send(text), headers: requestHeaders });
  setViewHooks({
    onPrefs: () => {
      // the Settings switch, only when it is the switch that changed (a theme or language change keeps the bird):
      // off is the hummingbird (no reasoning); on again gives the choice back to Bird
      const now = !!state.prefs.thinking;
      if (now !== prefsThinking) {
        if (!now) state.reflexion = "colibri";
        else if (state.reflexion === "colibri") state.reflexion = "auto";
        store.set("bird.reflexion", state.reflexion);
        state.thinking = thinks(state.reflexion);
      }
      prefsThinking = now;
      refreshAll();
    },
    onReset: () => {
      state.convs = [];
      state.reflexion = "auto";
      store.set("bird.reflexion", "auto");
      state.thinking = thinks(state.reflexion);
      prefsThinking = !!state.prefs.thinking;
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
  // a card's next ask (opendata.js « Pour continuer »): sent like a typed message, never while a turn runs
  document.addEventListener("bird:ask", (e) => {
    const text = typeof e.detail === "string" ? e.detail.trim() : "";
    if (text && text.length <= 300 && !state.busy && !pendingConfirm()) send(text);
  });
  state.convs = store.json("bird.convs", []).filter((c) => c && c.id);
  const current = store.get("bird.current");
  state.conv = (current && loadConv(current)) || newConv();
  restoreKept(state.conv);
  bind();
  trackViewport();
  trackTyping();
  applyTheme();
  applyStrings();
  setSidebar(!isNarrow() && store.get("bird.side") !== "0");
  renderSidebar();
  renderChat();
  await loadHealth();
  renderChat();
  // the page served by Bird local, opened without its code: ask for it once; the hosted page in Bird local mode:
  // what the local Bird says about itself (model, measured energy), for the header and the footprint
  if (state.health?.bird_local && !state.health.bird_local.paired && localPair.get()) {
    await loadHealth(); // the first health call went without the code (the page did not know it was Bird local yet)
    refreshAll();
  }
  if (state.health?.bird_local && !state.health.bird_local.paired)
    openPairDialog(() => loadHealth().then(refreshAll));
  else if (activeMode() === "local") refreshLocal().then(() => updateTop());
  autosize();
  scrollToEnd(true);
  document.body.classList.add("ready");
  if (!state.prefs.welcomed) openWelcome();
  else input().focus();
}

init();

/** The answer's link to its canvas artifact, as kept on the turn: the next-step chips the harness computed from
 * the document's structure, the file cards it replaces (a Word document is one card, in the canvas), and for a
 * code page what it already has (for its next-step chips). */
function canvasRef(c) {
  const str = (x) => typeof x === "string";
  const out = {
    aid: c.aid,
    version: c.version,
    doc: !!c.doc,
    variants: !!c.variants,
    next: (Array.isArray(c.next) ? c.next : [])
      .filter((x) => x && str(x.label) && str(x.prompt))
      .slice(0, 3)
      .map((x) => ({ label: x.label.slice(0, 60), prompt: x.prompt.slice(0, 200) })),
    files: (Array.isArray(c.files) ? c.files : []).filter(str).slice(0, 8),
  };
  if (c.kind === "code" && c.hints && typeof c.hints === "object") {
    out.kind = "code";
    out.hints = Object.fromEntries(
      ["web", "dark", "mobile", "js"].map((k) => [k, c.hints[k] === true]),
    );
    out.hints.lang = typeof c.hints.lang === "string" ? c.hints.lang.slice(0, 12) : "";
  }
  return out;
}
