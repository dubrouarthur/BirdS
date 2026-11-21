// Bird web chat. Vanilla ES modules, no framework, no build step.
// The frontend depends only on the API contract: /api/health, /api/chat (SSE), /api/confirm, /files/{name}.
import { makeT } from "./i18n.js";
import { renderMarkdown, safeUrl } from "./markdown.js";

const $ = (id) => document.getElementById(id);
const store = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {
      /* private mode or quota: persistence is optional */
    }
  },
};

const state = {
  lang: store.get("bird.lang") === "en" ? "en" : "fr",
  thinking: false,
  turns: [],
  health: null,
  busy: false,
  abort: null,
  confirm: null,
  seq: 0,
};
const t = makeT(() => state.lang);

// ------------------------------------------------------------------ DOM helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

// Icons are constants defined here, never model output.
const ICONS = {
  web_search: '<circle cx="9" cy="9" r="5.2"/><path d="M13 13l4 4"/>',
  read_page:
    '<path d="M5.5 3h6l3.5 3.5V17h-9.500z"/><path d="M11.5 3v3.500H15M8 10.500h4.500M8 13.500h4.500"/>',
  read_file:
    '<path d="M5.5 3h6l3.5 3.500V17h-9.500z"/><path d="M11.500 3v3.500H15"/>',
  draft_email:
    '<rect x="3" y="5" width="14" height="10.500" rx="1.500"/><path d="M3.500 6.500l6.500 5 6.500-5"/>',
  make_slides:
    '<rect x="3" y="4" width="14" height="9" rx="1.200"/><path d="M10 13v3.500M7 16.500h6"/>',
  make_document:
    '<path d="M5.500 3h6l3.500 3.500V17h-9.500z"/><path d="M8 9h4.500M8 11.500h4.500M8 14h3"/>',
  make_sheet:
    '<rect x="3.500" y="4" width="13" height="12" rx="1.200"/><path d="M3.500 8h13M3.500 12h13M8 4v12"/>',
  run_python:
    '<rect x="4.500" y="3" width="11" height="14" rx="1.500"/><path d="M7.500 6.500h5M7.500 10.500h.01M10 10.500h.01M12.500 10.500h.01M7.500 13.500h.01M10 13.500h.01M12.500 13.500h.01"/>',
  tool: '<circle cx="10" cy="10" r="2.200"/><circle cx="10" cy="10" r="6.500"/>',
  check: '<path d="M4.500 10.500l3.500 3.500 7.500-8"/>',
  cross: '<path d="M5.500 5.500l9 9M14.500 5.500l-9 9"/>',
  ban: '<circle cx="10" cy="10" r="6.500"/><path d="M5.500 14.500l9-9"/>',
  alert:
    '<path d="M10 3.500l7 12.500H3z"/><path d="M10 8.500v3.500M10 14.200h.01"/>',
  download: '<path d="M10 3.500v9M6 9l4 4 4-4M4 16.500h12"/>',
  copy: '<rect x="7" y="7" width="9.500" height="9.500" rx="1.500"/><path d="M13 7V5a1.500 1.500 0 0 0-1.500-1.500H5A1.500 1.500 0 0 0 3.500 5v6.500A1.500 1.500 0 0 0 5 13h2"/>',
  leaf: '<path d="M4 16c0-6.500 4.200-11 12-12 .2 7.600-3.600 12-9.600 12.400M4 16.600C6 12.500 8.600 10 12 8.200"/>',
  chevron: '<path d="M7.500 5l5 5-5 5"/>',
  file: '<path d="M5.500 3h6l3.500 3.500V17h-9.500z"/><path d="M11.500 3v3.500H15"/>',
  retry: '<path d="M4.500 10a5.500 5.500 0 1 0 1.800-4.100M4.500 4v3h3"/>',
};

function icon(name, cls = "") {
  const wrap = document.createElement("span");
  wrap.className = "icon-wrap";
  wrap.innerHTML = `<svg class="icon ${cls}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${ICONS[name] || ICONS.tool}</svg>`;
  return wrap.firstChild;
}

// ------------------------------------------------------------------ formatting

const nf = (options) =>
  new Intl.NumberFormat(state.lang === "en" ? "en-GB" : "fr-FR", options);
const fmtInt = (n) => nf({ maximumFractionDigits: 0 }).format(n || 0);
const fmtSeconds = (s) =>
  `${nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(s || 0)} ${t("unit.s")}`;
const fmtSig = (v) => nf({ maximumSignificantDigits: 3 }).format(v);

function fmtBytes(bytes) {
  if (!bytes) return `0 ${t("unit.kb")}`;
  if (bytes < 1000) return `${fmtInt(bytes)} ${t("unit.b")}`;
  if (bytes < 1e6)
    return `${nf({ maximumFractionDigits: bytes < 1e4 ? 1 : 0 }).format(bytes / 1000)} ${t("unit.kb")}`;
  return `${nf({ maximumFractionDigits: 1 }).format(bytes / 1e6)} ${t("unit.mb")}`;
}

const hasEnergy = (u) =>
  u &&
  typeof u.energy_wh === "number" &&
  (u.energy_kind === "measured" || u.energy_kind === "estimated");
const fmtEnergy = (wh, kind) =>
  `${kind === "estimated" ? "≈ " : ""}${fmtSig(wh)} Wh`;
const fmtCo2 = (g, kind) =>
  `${kind === "estimated" ? "≈ " : ""}${fmtSig(g)} g CO₂e`;
const isDemo = () => state.health?.backend === "demo";
const toolLabel = (tool) => {
  const key = `tool.${tool}`;
  const label = t(key);
  return label === key ? tool : label;
};

function argsSummary(tool, args) {
  const a = args && typeof args === "object" ? args : {};
  const pick = (...keys) =>
    keys.map((k) => a[k]).find((v) => typeof v === "string" && v.trim());
  let text;
  if (tool === "draft_email")
    text = [pick("to"), pick("subject")].filter(Boolean).join(" — ");
  else if (pick("url")) {
    const url = safeUrl(pick("url"));
    text = url
      ? new URL(url).host + new URL(url).pathname.replace(/\/$/, "")
      : pick("url");
  } else
    text = pick(
      "query",
      "q",
      "title",
      "path",
      "name",
      "filename",
      "file",
      "subject",
    );
  if (!text) {
    const first = Object.entries(a).find(
      ([, v]) => typeof v === "string" || typeof v === "number",
    );
    text = first ? `${first[0]} : ${first[1]}` : "";
  }
  return String(text).replace(/\s+/g, " ").slice(0, 140);
}

// ------------------------------------------------------------------ i18n + chrome

function applyStrings() {
  document.documentElement.lang = state.lang;
  document.title = t("app.title");
  for (const el of document.querySelectorAll("[data-i18n]"))
    el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-aria]"))
    el.setAttribute("aria-label", t(el.dataset.i18nAria));
  for (const el of document.querySelectorAll("[data-i18n-title]"))
    el.title = t(el.dataset.i18nTitle);
  for (const el of document.querySelectorAll("[data-i18n-placeholder]"))
    el.placeholder = t(el.dataset.i18nPlaceholder);
  $("btn-lang").textContent = state.lang === "fr" ? "EN" : "FR";
  $("btn-lang").lang = state.lang === "fr" ? "en" : "fr";
  updateThemeButton();
  renderExamples();
}

const currentTheme = () =>
  document.documentElement.dataset.theme ||
  (window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light");

function updateThemeButton() {
  const label = t(
    currentTheme() === "dark" ? "nav.theme.light" : "nav.theme.dark",
  );
  $("btn-theme").setAttribute("aria-label", label);
  $("btn-theme").title = label;
}

function renderExamples() {
  const list = $("examples");
  list.replaceChildren(
    ...[
      ["email", "draft_email"],
      ["minutes", "make_document"],
      ["slides", "make_slides"],
      ["search", "web_search"],
    ].map(([key, ico]) =>
      h(
        "li",
        null,
        h(
          "button",
          {
            class: "chip",
            type: "button",
            "data-example": key,
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

function announce(text) {
  const live = $("live");
  live.textContent = "";
  window.setTimeout(() => (live.textContent = text), 30);
}

function showBanner(text) {
  $("banner").textContent = text || "";
  $("banner").hidden = !text;
}

// ------------------------------------------------------------------ turns

function newAssistantTurn() {
  return {
    role: "assistant",
    id: `a${Date.now().toString(36)}${state.seq++}`,
    steps: [],
    reasoning: "",
    answer: null,
    usage: null,
    error: null,
    status: "running",
    ui: {},
  };
}

function persist() {
  const turns = state.turns.filter(
    (turn) => turn.role === "user" || turn.status !== "running",
  );
  store.set(
    "bird.conversation",
    turns.length ? JSON.stringify({ v: 1, turns }) : null,
  );
}

function restore() {
  try {
    const saved = JSON.parse(store.get("bird.conversation") || "null");
    if (!saved || saved.v !== 1 || !Array.isArray(saved.turns)) return;
    state.turns = saved.turns
      .filter(
        (turn) => turn && (turn.role === "user" || turn.role === "assistant"),
      )
      .map((turn) =>
        turn.role === "user"
          ? { role: "user", content: String(turn.content ?? "") }
          : {
              ...newAssistantTurn(),
              ...turn,
              steps: Array.isArray(turn.steps) ? turn.steps : [],
              ui: {},
              status: turn.status === "running" ? "stopped" : turn.status,
            },
      );
  } catch {
    state.turns = [];
  }
}

function details(cls, open, onToggle, summaryChildren, ...body) {
  const el = h(
    "details",
    { class: cls, open },
    h("summary", null, ...summaryChildren),
    ...body,
  );
  el.addEventListener("toggle", () => onToggle(el.open));
  return el;
}

function renderSteps(turn) {
  if (!turn.steps.length) return null;
  const flagged = turn.steps.some((s) =>
    (s.flags || []).includes("possible_injection"),
  );
  const total = turn.steps.reduce((sum, s) => sum + (s.seconds || 0), 0);
  const open = turn.ui.steps ?? (turn.status === "running" || flagged);
  const n = turn.steps.length;
  const items = turn.steps.map((step) => {
    const injection = (step.flags || []).includes("possible_injection");
    const statusIcon = { done: "check", error: "cross", denied: "ban" }[
      step.status
    ];
    return h(
      "li",
      { class: `step step-${step.status}${injection ? " step-flagged" : ""}` },
      h("span", { class: "step-icon" }, icon(step.tool)),
      h(
        "div",
        { class: "step-main" },
        h(
          "div",
          { class: "step-head" },
          h("span", { class: "step-label", text: toolLabel(step.tool) }),
          injection &&
            h(
              "span",
              { class: "badge badge-warn" },
              icon("alert"),
              t("steps.flagged"),
            ),
          h(
            "span",
            { class: "step-status" },
            step.status === "running"
              ? h("span", { class: "spinner", "aria-hidden": "true" })
              : icon(statusIcon || "check", `status-${step.status}`),
            h("span", { class: "sr-only", text: t(`status.${step.status}`) }),
            step.status !== "running" &&
              h("span", { class: "num", text: fmtSeconds(step.seconds) }),
          ),
        ),
        h("p", {
          class: "step-args",
          text: argsSummary(step.tool, step.arguments),
        }),
        step.summary && h("p", { class: "step-summary", text: step.summary }),
        injection &&
          h("p", { class: "step-warning", text: t("steps.injection") }),
      ),
    );
  });
  return details(
    "steps",
    open,
    (value) => (turn.ui.steps = value),
    [
      icon("chevron", "chev"),
      h("span", {
        class: "steps-count",
        text: n === 1 ? t("steps.count.one") : t("steps.count.many", { n }),
      }),
      h("span", {
        class: "steps-names",
        text: [...new Set(turn.steps.map((s) => toolLabel(s.tool)))].join(", "),
      }),
      flagged &&
        h(
          "span",
          { class: "badge badge-warn" },
          icon("alert"),
          t("steps.flagged"),
        ),
      turn.status !== "running" &&
        h("span", { class: "num steps-time", text: fmtSeconds(total) }),
    ],
    h("ol", { class: "timeline" }, items),
  );
}

function renderSources(turn) {
  const sources = turn.answer?.sources || [];
  if (!sources.length) return null;
  return h(
    "section",
    { class: "sources", "aria-label": t("sources.title") },
    h("h3", { class: "eyebrow", text: t("sources.title") }),
    h(
      "ol",
      { class: "source-list" },
      sources.map((source) => {
        const url = safeUrl(source.url);
        const title = String(source.title || source.url || "");
        return h(
          "li",
          { id: `src-${turn.id}-${Number(source.n) || 0}`, tabindex: "-1" },
          h("span", {
            class: "source-n num",
            text: String(Number(source.n) || ""),
          }),
          h(
            "span",
            { class: "source-body" },
            url
              ? h("a", {
                  href: url,
                  target: "_blank",
                  rel: "noopener noreferrer",
                  text: title,
                })
              : h("span", { text: title }),
            url && h("span", { class: "source-host", text: new URL(url).host }),
          ),
        );
      }),
    ),
  );
}

function renderFiles(turn) {
  const files = (turn.answer?.files || []).filter(
    (f) =>
      typeof f?.url === "string" &&
      /^\/files\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(f.url),
  );
  if (!files.length) return null;
  return h(
    "section",
    { class: "files", "aria-label": t("files.title") },
    files.map((file) => {
      const name = String(file.name || file.url.slice(7));
      const ext = (name.match(/\.([A-Za-z0-9]{1,5})$/) || [
        ,
        "",
      ])[1].toUpperCase();
      return h(
        "a",
        { class: "file-card", href: file.url, download: name },
        h(
          "span",
          { class: "file-icon" },
          icon("file"),
          ext && h("span", { class: "file-ext", text: ext }),
        ),
        h(
          "span",
          { class: "file-meta" },
          h("span", { class: "file-name", text: name }),
          h(
            "span",
            { class: "file-action" },
            icon("download"),
            t("files.download"),
          ),
        ),
      );
    }),
  );
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = h("textarea", { class: "sr-only", "aria-hidden": "true" });
    area.value = text;
    document.body.append(area);
    area.select();
    try {
      document.execCommand("copy");
    } catch {
      /* nothing else to try */
    }
    area.remove();
  }
  const label = button.querySelector(".btn-label");
  const before = label.textContent;
  label.textContent = t("email.copied");
  announce(t("email.copied"));
  window.setTimeout(() => (label.textContent = before), 1600);
}

function renderEmail(turn) {
  const draft = turn.answer?.draft_email;
  if (!draft || typeof draft !== "object") return null;
  const to = String(draft.to ?? "");
  const subject = String(draft.subject ?? "");
  const body = String(draft.body ?? "");
  const copyBtn = (key, text) =>
    h(
      "button",
      {
        class: "btn btn-outline btn-small",
        type: "button",
        onclick: (e) => copyText(text, e.currentTarget),
      },
      icon("copy"),
      h("span", { class: "btn-label", text: t(key) }),
    );
  return h(
    "section",
    { class: "email-card", "aria-label": t("email.title") },
    h(
      "header",
      { class: "email-head" },
      h(
        "span",
        { class: "email-kicker" },
        icon("draft_email"),
        t("email.title"),
      ),
    ),
    h(
      "dl",
      { class: "email-fields" },
      h(
        "div",
        null,
        h("dt", { text: t("email.to") }),
        h("dd", { text: to || "—" }),
      ),
      h(
        "div",
        null,
        h("dt", { text: t("email.subject") }),
        h("dd", { class: "email-subject", text: subject || "—" }),
      ),
    ),
    h("div", { class: "email-body", text: body }),
    h(
      "div",
      { class: "email-actions" },
      copyBtn("email.copy.subject", subject),
      copyBtn("email.copy.body", body),
      copyBtn(
        "email.copy.all",
        `${t("email.to")} : ${to}\n${t("email.subject")} : ${subject}\n\n${body}`,
      ),
    ),
    h(
      "p",
      { class: "email-note" },
      icon("ban"),
      h("span", { text: t("email.notsent") }),
    ),
  );
}

// ------------------------------------------------------------------ resource meter

function meterRows(usage) {
  const demo = isDemo();
  const gi = state.health?.grid_intensity_g_per_kwh;
  const energy = hasEnergy(usage);
  const rows = [
    [
      "row.prompt",
      fmtInt(usage.prompt_tokens),
      demo ? "scripted" : "counted",
      demo ? "why.tokens.demo" : "why.prompt",
    ],
    [
      "row.completion",
      fmtInt(usage.completion_tokens),
      demo ? "scripted" : "counted",
      demo ? "why.tokens.demo" : "why.completion",
    ],
    [
      "row.seconds",
      fmtSeconds(usage.seconds),
      "measured",
      demo ? "why.seconds.demo" : "why.seconds",
    ],
    ["row.tools", fmtInt(usage.tool_calls), "counted", "why.tools"],
    [
      "row.fetched",
      fmtBytes(usage.bytes_fetched),
      demo ? "scripted" : "counted",
      demo ? "why.fetched.demo" : "why.fetched",
    ],
    energy
      ? [
          "row.energy",
          fmtEnergy(usage.energy_wh, usage.energy_kind),
          usage.energy_kind,
          `why.energy.${usage.energy_kind}`,
        ]
      : [
          "row.energy",
          t("meter.energy.none.long"),
          "unavailable",
          demo ? "why.energy.demo" : "why.energy.none",
        ],
    energy && typeof usage.co2_g === "number"
      ? [
          "row.co2",
          fmtCo2(usage.co2_g, "estimated"),
          "estimated",
          "why.co2",
          { gi: gi ?? "?" },
        ]
      : [
          "row.co2",
          t("co2.none"),
          "unavailable",
          energy ? "why.co2.nogrid" : "why.co2.noenergy",
        ],
    ["row.model", String(usage.model || "?"), "configured", "why.model"],
    [
      "row.thinking",
      usage.thinking ? t("yes") : t("no"),
      "configured",
      usage.thinking ? "why.thinking.on" : "why.thinking.off",
    ],
  ];
  return rows;
}

function renderMeter(turn) {
  const u = turn.usage;
  if (!u) return null;
  const energy = hasEnergy(u);
  const parts = [
    h("span", {
      class: "num",
      "aria-label": t("meter.tokens.aria", {
        in: fmtInt(u.prompt_tokens),
        out: fmtInt(u.completion_tokens),
      }),
      text: t("meter.tokens", {
        in: fmtInt(u.prompt_tokens),
        out: fmtInt(u.completion_tokens),
      }),
    }),
    h("span", { class: "num", text: fmtSeconds(u.seconds) }),
    h("span", {
      class: "num",
      text:
        u.tool_calls === 0
          ? t("meter.tools.zero")
          : u.tool_calls === 1
            ? t("meter.tools.one")
            : t("meter.tools.many", { n: u.tool_calls }),
    }),
    u.bytes_fetched > 0 &&
      h("span", {
        class: "num",
        text: t("meter.fetched", { v: fmtBytes(u.bytes_fetched) }),
      }),
    energy
      ? h("span", {
          class: "num meter-energy",
          text: fmtEnergy(u.energy_wh, u.energy_kind),
        })
      : h("span", { class: "meter-none", text: t("meter.energy.none") }),
    energy &&
      typeof u.co2_g === "number" &&
      h("span", { class: "num", text: fmtCo2(u.co2_g, "estimated") }),
    h("span", { class: "meter-model", text: String(u.model || "") }),
    h("span", {
      text: t(u.thinking ? "meter.thinking.on" : "meter.thinking.off"),
    }),
  ].filter(Boolean);
  const table = h(
    "table",
    { class: "meter-table" },
    h("caption", { class: "eyebrow", text: t("meter.how") }),
    h(
      "tbody",
      null,
      meterRows(u).map(([label, value, kind, why, vars]) =>
        h(
          "tr",
          { class: `kind-${kind}` },
          h("th", { scope: "row", text: t(label) }),
          h(
            "td",
            { class: "meter-value" },
            h("span", { class: "num", text: value }),
            h("span", { class: `tag tag-${kind}`, text: t(`kind.${kind}`) }),
          ),
          h("td", { class: "meter-why", text: t(why, vars) }),
        ),
      ),
    ),
  );
  return details(
    "meter",
    turn.ui.meter ?? false,
    (value) => (turn.ui.meter = value),
    [
      h("span", { class: "meter-mark" }, icon("leaf")),
      h("span", { class: "sr-only", text: `${t("meter.label")} : ` }),
      h("span", { class: "meter-line" }, parts),
      h(
        "span",
        { class: "meter-more" },
        t("meter.detail"),
        icon("chevron", "chev"),
      ),
    ],
    table,
  );
}

function sessionTotals() {
  const usages = state.turns
    .filter((turn) => turn.role === "assistant" && turn.usage)
    .map((turn) => turn.usage);
  const sum = (key) =>
    usages.reduce((total, u) => total + (Number(u[key]) || 0), 0);
  const withEnergy = usages.filter(hasEnergy);
  const withCo2 = withEnergy.filter((u) => typeof u.co2_g === "number");
  return {
    usages,
    n: usages.length,
    prompt: sum("prompt_tokens"),
    completion: sum("completion_tokens"),
    seconds: sum("seconds"),
    tools: sum("tool_calls"),
    bytes: sum("bytes_fetched"),
    energyN: withEnergy.length,
    energy: withEnergy.reduce((total, u) => total + u.energy_wh, 0),
    energyKind: withEnergy.some((u) => u.energy_kind === "estimated")
      ? "estimated"
      : "measured",
    co2N: withCo2.length,
    co2: withCo2.reduce((total, u) => total + u.co2_g, 0),
  };
}

function updateSessionButton() {
  const s = sessionTotals();
  $("session-total").textContent = s.n
    ? `${fmtInt(s.prompt + s.completion)} tokens`
    : t("nav.session.short");
  if ($("session-panel").open) renderSession();
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {}))
    el.setAttribute(key, value);
  el.append(...children);
  return el;
}

function topRounded(x, y, w, hgt, r) {
  const rr = Math.min(r, hgt, w / 2);
  return `M${x} ${y + hgt}V${y + rr}a${rr} ${rr} 0 0 1 ${rr}-${rr}h${w - 2 * rr}a${rr} ${rr} 0 0 1 ${rr} ${rr}V${y + hgt}z`;
}

function renderChart(usages) {
  const barW = 16;
  const gap = 8;
  const height = 104;
  const plot = height - 8;
  const max = Math.max(
    1,
    ...usages.map((u) => u.prompt_tokens + u.completion_tokens),
  );
  const width = Math.max(usages.length * (barW + gap) + gap, 120);
  const readout = h("p", {
    class: "chart-readout num",
    text: t("session.chart.hint"),
  });
  const chart = svg("svg", {
    class: "chart",
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    role: "group",
    "aria-label": t("session.chart"),
  });
  chart.append(
    svg("line", {
      class: "chart-axis",
      x1: 0,
      x2: width,
      y1: height - 0.5,
      y2: height - 0.5,
    }),
  );
  usages.forEach((u, i) => {
    const x = gap + i * (barW + gap);
    const hIn = Math.max(
      u.prompt_tokens > 0 ? 2 : 0,
      (u.prompt_tokens / max) * plot,
    );
    const hOut = Math.max(
      u.completion_tokens > 0 ? 2 : 0,
      (u.completion_tokens / max) * plot,
    );
    const label = t("session.bar", {
      i: i + 1,
      in: fmtInt(u.prompt_tokens),
      out: fmtInt(u.completion_tokens),
    });
    const group = svg("g", {
      class: "chart-bar",
      tabindex: "0",
      role: "img",
      "aria-label": label,
    });
    group.append(
      svg("rect", {
        class: "chart-hit",
        x: x - gap / 2,
        y: 0,
        width: barW + gap,
        height,
      }),
      svg("rect", {
        class: "series-in",
        x,
        y: height - 1 - hIn,
        width: barW,
        height: hIn,
      }),
      svg("path", {
        class: "series-out",
        d: topRounded(x, height - 1 - hIn - 2 - hOut, barW, hOut, 4),
      }),
    );
    const show = () => (readout.textContent = label);
    group.addEventListener("mouseenter", show);
    group.addEventListener("focus", show);
    chart.append(group);
  });
  return h(
    "figure",
    { class: "chart-figure" },
    h(
      "figcaption",
      null,
      h("span", { class: "eyebrow", text: t("session.chart") }),
      h(
        "span",
        { class: "legend" },
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-in" }),
          t("session.legend.in"),
        ),
        h(
          "span",
          { class: "legend-item" },
          h("span", { class: "swatch swatch-out" }),
          t("session.legend.out"),
        ),
      ),
    ),
    h("div", { class: "chart-scroll" }, chart),
    readout,
    h(
      "details",
      { class: "chart-table" },
      h("summary", null, icon("chevron", "chev"), t("session.table")),
      h(
        "table",
        null,
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            h("th", { scope: "col", text: t("session.col.answer") }),
            h("th", { scope: "col", text: t("row.prompt") }),
            h("th", { scope: "col", text: t("row.completion") }),
          ),
        ),
        h(
          "tbody",
          null,
          usages.map((u, i) =>
            h(
              "tr",
              null,
              h("th", { scope: "row", class: "num", text: String(i + 1) }),
              h("td", { class: "num", text: fmtInt(u.prompt_tokens) }),
              h("td", { class: "num", text: fmtInt(u.completion_tokens) }),
            ),
          ),
        ),
      ),
    ),
  );
}

function renderSession() {
  const s = sessionTotals();
  const body = $("session-body");
  if (!s.n) {
    body.replaceChildren(
      h("p", { class: "panel-empty", text: t("session.empty") }),
      isDemo() && h("p", { class: "demo-note", text: t("demo.note") }),
      h("p", { class: "hint", text: t("session.note") }),
    );
    return;
  }
  const partial = (k) => (k < s.n ? t("session.partial", { k, n: s.n }) : "");
  const stat = (label, value, sub, cls = "") =>
    h(
      "div",
      { class: `stat ${cls}` },
      h("dt", { text: label }),
      h(
        "dd",
        null,
        h("span", { class: "stat-value num", text: value }),
        sub && h("span", { class: "stat-sub", text: sub }),
      ),
    );
  body.replaceChildren(
    h(
      "dl",
      { class: "stats" },
      stat(
        t("session.tokens"),
        fmtInt(s.prompt + s.completion),
        t("session.tokens.split", {
          in: fmtInt(s.prompt),
          out: fmtInt(s.completion),
        }),
        "stat-wide",
      ),
      stat(t("session.answers"), fmtInt(s.n)),
      stat(t("session.time"), fmtSeconds(s.seconds)),
      stat(t("session.tools"), fmtInt(s.tools)),
      stat(t("session.fetched"), fmtBytes(s.bytes)),
      s.energyN
        ? stat(
            t("session.energy"),
            fmtEnergy(s.energy, s.energyKind),
            [t(`kind.${s.energyKind}`), partial(s.energyN)]
              .filter(Boolean)
              .join(" · "),
            "stat-wide",
          )
        : stat(
            t("session.energy"),
            t("meter.energy.none.long"),
            t(isDemo() ? "why.energy.demo" : "why.energy.none"),
            "stat-wide stat-none",
          ),
      s.co2N
        ? stat(
            t("session.co2"),
            fmtCo2(s.co2, "estimated"),
            [t("kind.estimated"), partial(s.co2N)].filter(Boolean).join(" · "),
            "stat-wide",
          )
        : stat(
            t("session.co2"),
            t("co2.none"),
            t(s.energyN ? "why.co2.nogrid" : "why.co2.noenergy"),
            "stat-wide stat-none",
          ),
    ),
    renderChart(s.usages),
    isDemo() && h("p", { class: "demo-note", text: t("demo.note") }),
    h("p", { class: "hint", text: t("session.note") }),
  );
}

// ------------------------------------------------------------------ conversation rendering

function renderUser(turn) {
  return h(
    "article",
    { class: "turn turn-user" },
    h("h2", { class: "sr-only", text: t("turn.you") }),
    h("div", { class: "bubble", text: turn.content }),
  );
}

function fillAssistant(el, turn) {
  const children = [
    h(
      "header",
      { class: "byline" },
      h("h2", { class: "byline-name", text: t("turn.bird") }),
      isDemo() &&
        h("span", {
          class: "badge badge-demo",
          title: t("demo.title"),
          text: t("demo.badge"),
        }),
    ),
    renderSteps(turn),
  ];
  if (turn.reasoning) {
    children.push(
      details(
        "reasoning",
        turn.ui.reasoning ?? false,
        (value) => (turn.ui.reasoning = value),
        [icon("chevron", "chev"), t("reasoning.title")],
        h("div", { class: "reasoning-body", text: turn.reasoning }),
      ),
    );
  }
  if (turn.answer) {
    const md = h("div", { class: "md" });
    // Safe by construction: renderMarkdown escapes all model text before emitting its own tags.
    md.innerHTML = renderMarkdown(turn.answer.content, {
      cites: (turn.answer.sources || []).map((s) => Number(s.n)),
      anchor: `src-${turn.id}`,
      citeLabel: `${t("sources.title")} {n}`,
    });
    children.push(
      md,
      renderSources(turn),
      renderFiles(turn),
      renderEmail(turn),
    );
  }
  if (turn.status === "running" && !turn.answer) {
    children.push(
      h(
        "p",
        { class: "working" },
        h(
          "span",
          { class: "dots", "aria-hidden": "true" },
          h("i"),
          h("i"),
          h("i"),
        ),
        h("span", { text: t("turn.working") }),
      ),
    );
  }
  if (turn.error) {
    children.push(
      h(
        "div",
        { class: "error-box", role: "alert" },
        icon("alert"),
        h(
          "div",
          null,
          h("strong", { text: t("turn.error") }),
          h("p", { text: turn.error }),
        ),
        !state.busy &&
          turn === state.turns[state.turns.length - 1] &&
          h(
            "button",
            {
              class: "btn btn-outline btn-small",
              type: "button",
              onclick: retry,
            },
            icon("retry"),
            h("span", { text: t("turn.retry") }),
          ),
      ),
    );
  }
  if (turn.status === "stopped")
    children.push(h("p", { class: "stopped", text: t("turn.stopped") }));
  children.push(renderMeter(turn));
  el.replaceChildren(...children.filter(Boolean));
}

function renderAll() {
  const root = $("conversation");
  root.replaceChildren(
    ...state.turns.map((turn) => {
      if (turn.role === "user") return renderUser(turn);
      const el = h("article", {
        class: "turn turn-bird",
        "data-turn": turn.id,
      });
      fillAssistant(el, turn);
      return el;
    }),
  );
  $("empty").hidden = state.turns.length > 0;
  updateSessionButton();
}

function updateTurn(turn) {
  const el = document.querySelector(`[data-turn="${turn.id}"]`);
  if (el) fillAssistant(el, turn);
}

const nearBottom = () =>
  window.innerHeight + window.scrollY >=
  document.documentElement.scrollHeight - 160;
function scrollDown(force) {
  if (force || nearBottom())
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: "instant",
    });
}

// ------------------------------------------------------------------ chat

function setBusy(busy) {
  state.busy = busy;
  $("btn-stop").hidden = !busy;
  $("btn-send").hidden = busy;
  updateSendButton();
}

function updateSendButton() {
  $("btn-send").disabled = state.busy || !$("composer-input").value.trim();
}

function apiMessages() {
  const messages = [];
  for (const turn of state.turns) {
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

function handleEvent(turn, event) {
  switch (event.type) {
    case "step": {
      const i = turn.steps.findIndex((s) => s.index === event.index);
      if (i >= 0) turn.steps[i] = event;
      else turn.steps.push(event);
      if (event.status === "running") announce(`${toolLabel(event.tool)}…`);
      break;
    }
    case "confirm":
      openConfirm(event);
      break;
    case "reasoning":
      turn.reasoning +=
        (turn.reasoning ? "\n\n" : "") + String(event.content ?? "");
      break;
    case "answer":
      turn.answer = {
        content: String(event.content ?? ""),
        sources: event.sources || [],
        files: event.files || [],
        draft_email: event.draft_email || null,
      };
      announce(t("live.answer"));
      break;
    case "usage":
      turn.usage = event;
      break;
    case "error":
      turn.error = String(event.message || t("turn.error"));
      turn.status = "error";
      break;
    default:
      break;
  }
}

async function runTurn(turn) {
  const controller = new AbortController();
  state.abort = controller;
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        messages: apiMessages(),
        thinking: state.thinking,
        lang: state.lang,
      }),
      signal: controller.signal,
    });
    if (!response.ok || !response.body)
      throw new Error(`HTTP ${response.status}`);
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
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!data) continue;
        let event;
        try {
          event = JSON.parse(data);
        } catch {
          continue;
        }
        if (event.type === "done") continue;
        const stick = nearBottom();
        handleEvent(turn, event);
        updateTurn(turn);
        if (stick) scrollDown(true);
      }
    }
    if (turn.status === "running") turn.status = "done";
  } catch (error) {
    if (controller.signal.aborted) turn.status = "stopped";
    else {
      turn.status = "error";
      turn.error = `${t("error.network")} (${error?.message || error})`;
    }
  } finally {
    state.abort = null;
    closeConfirm();
    for (const step of turn.steps)
      if (step.status === "running")
        step.status = turn.status === "stopped" ? "denied" : "error";
    setBusy(false);
    updateTurn(turn);
    updateSessionButton();
    persist();
  }
}

function send(text) {
  const content = String(text ?? "").trim();
  if (!content || state.busy) return;
  const turn = newAssistantTurn();
  state.turns.push({ role: "user", content }, turn);
  const input = $("composer-input");
  input.value = "";
  autosize();
  renderAll();
  scrollDown(true);
  announce(t("live.sent"));
  input.focus();
  runTurn(turn);
}

function retry() {
  if (state.busy) return;
  const last = state.turns[state.turns.length - 1];
  if (!last || last.role !== "assistant") return;
  const turn = newAssistantTurn();
  state.turns[state.turns.length - 1] = turn;
  renderAll();
  runTurn(turn);
}

function stop() {
  state.abort?.abort();
}

function newConversation() {
  stop();
  state.turns = [];
  persist();
  renderAll();
  window.scrollTo({ top: 0 });
  $("composer-input").focus();
}

// ------------------------------------------------------------------ confirm dialog

function openConfirm(event) {
  state.confirm = { id: String(event.id) };
  $("confirm-tool").textContent = toolLabel(event.tool);
  $("confirm-reason").textContent = String(event.reason || "");
  const args =
    event.arguments && typeof event.arguments === "object"
      ? event.arguments
      : {};
  const names = {
    to: t("email.to"),
    subject: t("email.subject"),
    body: t("email.body"),
  };
  $("confirm-args").replaceChildren(
    ...Object.entries(args).map(([key, value]) =>
      h(
        "div",
        null,
        h("dt", { text: names[key] || key }),
        h("dd", {
          class: key === "body" ? "kv-long" : "",
          text: typeof value === "string" ? value : JSON.stringify(value),
        }),
      ),
    ),
  );
  const dialog = $("confirm-dialog");
  if (!dialog.open) dialog.showModal();
  $("confirm-deny").focus();
  announce(t("live.confirm"));
}

function closeConfirm() {
  state.confirm = null;
  const dialog = $("confirm-dialog");
  if (dialog.open) dialog.close();
}

async function answerConfirm(allow) {
  const pending = state.confirm;
  closeConfirm();
  $("composer-input").focus();
  if (!pending) return;
  try {
    await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: pending.id, allow }),
    });
  } catch {
    /* the stream reports the outcome */
  }
}

// ------------------------------------------------------------------ wiring

function autosize() {
  const input = $("composer-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
  updateSendButton();
}

function setThinking(on) {
  state.thinking = on;
  $("btn-thinking").setAttribute("aria-checked", String(on));
}

function bind() {
  const input = $("composer-input");
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    send(input.value);
  });
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send(input.value);
    }
  });
  $("btn-stop").addEventListener("click", stop);
  $("btn-thinking").addEventListener("click", () =>
    setThinking(!state.thinking),
  );
  $("btn-new").addEventListener("click", newConversation);
  $("btn-lang").addEventListener("click", () => {
    state.lang = state.lang === "fr" ? "en" : "fr";
    store.set("bird.lang", state.lang);
    applyStrings();
    renderAll();
  });
  $("btn-theme").addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("bird.theme", next);
    updateThemeButton();
  });
  $("btn-session").addEventListener("click", () => {
    renderSession();
    $("session-panel").showModal();
  });
  $("session-close").addEventListener("click", () =>
    $("session-panel").close(),
  );
  $("session-panel").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) e.currentTarget.close(); // click on the backdrop
  });
  $("confirm-allow").addEventListener("click", () => answerConfirm(true));
  $("confirm-deny").addEventListener("click", () => answerConfirm(false));
  $("confirm-dialog").addEventListener("cancel", (e) => {
    e.preventDefault(); // Escape means "deny", never a silent dismissal
    answerConfirm(false);
  });
  // Citation links move focus to the source entry.
  $("conversation").addEventListener("click", (e) => {
    const link = e.target.closest?.(".cite a");
    if (!link) return;
    const target = document.getElementById(link.getAttribute("href").slice(1));
    if (target) {
      e.preventDefault();
      target.focus();
      target.scrollIntoView({ block: "center" });
    }
  });
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
  const demo = isDemo();
  $("demo-badge").hidden = !demo;
  $("demo-note").hidden = !demo;
  if (state.health?.thinking_default) setThinking(true);
}

async function init() {
  restore();
  bind();
  applyStrings();
  renderAll();
  await loadHealth();
  renderAll();
  autosize();
}

init();
