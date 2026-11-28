// Mode Agent: the plan card before launch, « l'équipe au travail » (one line in the present tense, the plan with
// the current step, sources arriving, the lanes, the instructions added), then one line in the past tense, the
// « Vérifications faites » card and the conversation's « Livrables ».
// Every text comes from the server's events or the i18n table and is set as text, never as HTML.
import {
  h,
  elapsed,
  fmtInt,
  fmtSeconds,
  fmtSig,
  t,
  toolLabel,
} from "./core.js";

// Role icons: constants, 20x20, stroke only (same style as core.js icons).
const ROLE = {
  chercheur: '<circle cx="9" cy="9" r="5.2"/><path d="M13 13l4 4"/>',
  lecteur:
    '<path d="M3 5.5c2.4-1 4.6-1 7 .5 2.4-1.5 4.6-1.5 7-.5V15c-2.4-1-4.6-1-7 .5-2.4-1.5-4.6-1.5-7-.5z"/><path d="M10 6v9.5"/>',
  analyste:
    '<rect x="4" y="3" width="12" height="14" rx="1.6"/><path d="M7 6.5h6M7 10h.01M10 10h.01M13 10h.01M7 13.5h.01M10 13.5h.01M13 13.5h.01"/>',
  planificateur:
    '<path d="M7.5 5.5h8.5M7.5 10h8.5M7.5 14.5h8.5"/><path d="M3.5 5.5l1 1 1.6-2M3.5 10l1 1 1.6-2M4 14.5h.01"/>',
  redacteur:
    '<path d="M4 16l.6-3.2L13.5 4l2.5 2.5-8.8 8.8z"/><path d="M12 5.5L14.5 8"/>',
  verificateur:
    '<path d="M10 3l6 2.2v4.3c0 3.6-2.4 6.3-6 7.5-3.6-1.2-6-3.9-6-7.5V5.2z"/><path d="M7.5 10l1.8 1.8 3.2-3.6"/>',
  correcteur: '<path d="M4.5 10a5.5 5.5 0 1 0 1.8-4.1M4.5 4v3h3"/>',
  assembleur:
    '<path d="M5.5 3h6l3.5 3.5V17h-9.5z"/><path d="M11.5 3v3.5H15M8 11.5l1.5 1.5 3-3"/>',
};
const GLYPH = {
  shield: ROLE.verificateur,
  plus: '<path d="M10 4.5v11M4.5 10h11"/>',
  stop: '<rect x="5.5" y="5.5" width="9" height="9" rx="1.5"/>',
  note: '<path d="M4 4.5h12v8.5H9l-3.5 3v-3H4z"/>',
  chevron: '<path d="M6 8l4 4 4-4"/>',
  close: '<path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/>',
  play: '<path d="M7 5l8 5-8 5z"/>',
  edit: ROLE.redacteur,
  check: '<path d="M5 10.5l3.2 3.2L15 7"/>',
  minus: '<path d="M4.5 10h11"/>',
  quote:
    '<path d="M5 6.5h4v4H6.5c0 1.6.6 2.6 2 3M11 6.5h4v4h-2.5c0 1.6.6 2.6 2 3"/>',
};
const svg = (paths, cls = "") => {
  const wrap = document.createElement("span");
  wrap.innerHTML = `<svg class="icon ${cls}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${paths}</svg>`;
  return wrap.firstChild;
};
const str = (v, n = 400) => String(v ?? "").slice(0, n);
/** t() with a singular form: « 1 chiffre vérifié », « 14 chiffres vérifiés » (key + ".one" when n is 1). */
export const tn = (key, n, vars = {}) => (n === 1 && t(`${key}.one`) !== `${key}.one` ? t(`${key}.one`, { n, ...vars }) : t(key, { n, ...vars }));
const NOTE_KINDS = [
  "exclude_site",
  "prefer_site",
  "audience",
  "length",
  "add_section",
  "focus",
];
const AUDIENCES = ["general", "decision", "experts"];
const LENGTHS = ["short", "standard", "long"];

function cleanPlan(p) {
  if (!p || typeof p !== "object") return null;
  const list = (v, n) =>
    Array.isArray(v) ? v.slice(0, n).map((x) => str(x, 120)) : [];
  return {
    recipe: str(p.recipe, 40),
    deliverable: str(p.deliverable, 40),
    steps: (Array.isArray(p.steps) ? p.steps : [])
      .slice(0, 8)
      .map((s) => ({ id: str(s?.id, 30), label: str(s?.label, 120) })),
    audience: AUDIENCES.includes(p.audience) ? p.audience : "general",
    length: LENGTHS.includes(p.length) ? p.length : "standard",
    n_slides: Number.isInteger(p.n_slides) ? p.n_slides : null,
    sections: list(p.sections, 8),
    prefer: list(p.prefer, 6),
    exclude: list(p.exclude, 6),
    focus: str(p.focus, 100),
    web: !!p.web,
    labels: { deliverable: str(p.labels?.deliverable, 60) },
  };
}

/** Fold one agent_* event into the turn (state only; the caller redraws). Returns the sentence a screen reader
 * should hear for this event (a lane finishing or failing, the version kept, the team's summary), or "". */
export function applyAgentEvent(turn, ev) {
  if (ev.type === "agent_plan") {
    const plan = cleanPlan(ev.plan);
    if (!plan || typeof ev.token !== "string") return "";
    const auto =
      Number.isInteger(ev.auto_start) && ev.auto_start > 0 ? ev.auto_start : 0;
    turn.crewPlan = {
      plan,
      token: ev.token,
      reason: str(ev.reason, 200),
      forced: !!ev.forced,
      demo: ev.demo ? str(ev.demo, 60) : "",
      auto,
      deadline: auto ? Date.now() + auto * 1000 : 0,
      status: "pending",
      edits: {},
    };
    return t(auto ? "agent.plan.say.auto" : "agent.plan.say", { n: auto });
  }
  if (ev.type === "agent_start") {
    const prev = turn.crew;
    turn.crew = {
      recipe: ev.recipe,
      reason: String(ev.reason || ""),
      forced: !!ev.forced,
      demo: ev.demo ? String(ev.demo) : "",
      run: typeof ev.run === "string" ? ev.run.slice(0, 40) : "",
      plan: cleanPlan(ev.plan) || prev?.plan || turn.crewPlan?.plan || null,
      lanes: (ev.lanes || []).map((l) => ({ ...l, status: "queued" })),
      notes: prev?.notes || [],
      questions: prev?.questions || [],
      slice: Number(ev.slice) || 0,
      started: prev?.started || Date.now(),
      checkpoint: prev?.checkpoint || "",
      checkpointExp: prev?.checkpointExp || 0,
      done: null,
    };
    if (turn.crewPlan) turn.crewPlan.status = "launched";
    return "";
  }
  const crew = turn.crew;
  if (ev.type === "agent_checks") {
    const items = (Array.isArray(ev.items) ? ev.items : [])
      .slice(0, 60)
      .map((i) => ({
        value: str(i?.value, 40),
        sentence: str(i?.sentence, 200),
        status: ["verified", "removed", "review"].includes(i?.status)
          ? i.status
          : "review",
        origin: ["source", "request", "computed", "none"].includes(i?.origin)
          ? i.origin
          : "none",
        n: Number.isInteger(i?.n) ? i.n : null,
        line: str(i?.line, 300),
        site: str(i?.site, 80),
        title: str(i?.title, 120),
        why: str(i?.why, 20),
      }));
    turn.checks = {
      verified: Number(ev.verified_n) || 0,
      removed: Number(ev.removed_n) || 0,
      review: Number(ev.review_n) || 0,
      more: Number(ev.more) || 0,
      dropped: Number(ev.read_dropped) || 0,
      actions: (Array.isArray(ev.actions) ? ev.actions : [])
        .slice(0, 20)
        .map((a) => ({
          owner: str(a?.owner, 80),
          action: str(a?.action, 160),
          due: str(a?.due, 40),
          line: Number.isInteger(a?.line) ? a.line : null,
        })),
      costs: Number(ev.costs) || 0,
      items,
    };
    return "";
  }
  if (ev.type === "agent_deliverable") {
    turn.deliverables = [
      ...(turn.deliverables || []),
      {
        tool: str(ev.tool, 30),
        title: str(ev.title, 200),
        file: str(ev.file, 160),
        canvas: str(ev.canvas, 60),
        parts: Number(ev.parts) || 0,
      },
    ];
    return "";
  }
  if (ev.type === "agent_slice") {
    if (!crew || typeof ev.token !== "string") return "";
    // kept with the conversation: « Reprendre » after a reload or a lost connection. The next slice's state is a
    // checkpoint too (a long task sends no other one): a reload during the writing keeps the research
    crew.checkpoint = ev.token;
    // until when the server accepts it (seconds since 1970); without it, the server's default of 15 minutes
    crew.checkpointExp = Number.isInteger(ev.exp) ? ev.exp : Math.floor(Date.now() / 1000) + 900;
    if (ev.auto) {
      crew.next = ev.token; // the browser continues the task in a new request (runTurn)
      return t("agent.slice.say");
    }
    return "";
  }
  if (ev.type === "agent_note") {
    if (!crew) return "";
    const n = crew.notes.find((x) => x.id === ev.id);
    const status = ev.status === "late" ? "late" : "applied";
    if (n) n.status = status;
    else
      crew.notes.push({
        id: str(ev.id, 24),
        kind: NOTE_KINDS.includes(ev.kind) ? ev.kind : "focus",
        value: str(ev.value, 200),
        status,
      });
    return t(`agent.note.say.${status}`);
  }
  if (ev.type === "agent_done") {
    if (!crew) {
      if (ev.reason === "no_deliverable")
        turn.crewNote = String(ev.message || t("agent.nothing"));
      return "";
    }
    crew.done = ev;
    crew.next = "";
    // the task is done: its signed state (pages read, the request) has no use left, and it is large
    if (ev.ok) {
      crew.checkpoint = "";
      crew.checkpointExp = 0;
    }
    for (const lane of crew.lanes) {
      // a lane still waiting when the team ends badly was needed but never ran: « non lancé », not « non nécessaire »
      if (lane.status === "queued")
        lane.status = ev.ok ? "skipped" : "cancelled";
      // the user stopped the team: a neutral « arrêté », not a red failure
      if (lane.status === "running")
        lane.status = ev.ok ? "done" : ev.stopped ? "stopped" : "error";
    }
    for (const n of crew.notes)
      if (n.status === "sent" || n.status === "queued") n.status = "late";
    return summary(turn, crew);
  }
  if (ev.type !== "agent_step" || !crew) return "";
  const lane = crew.lanes.find((l) => l.id === ev.id);
  if (!lane) return "";
  if (Array.isArray(ev.questions))
    crew.questions = ev.questions.slice(0, 3).map((q) => str(q, 160));
  if (ev.status === "scored") {
    lane.score = ev.score;
    lane.chosen = !!ev.chosen;
    return lane.chosen ? t("agent.say.kept", { label: lane.label }) : "";
  }
  if (ev.status === "running" && lane.status !== "running")
    lane.since = Date.now();
  const was = lane.status;
  lane.status = ev.status;
  for (const k of ["progress", "tokens", "seconds", "score"])
    if (ev[k] !== undefined) lane[k] = ev[k];
  if (ev.detail !== undefined) lane.info = String(ev.detail);
  if (typeof ev.chosen === "boolean") lane.chosen = ev.chosen;
  // the checker completed the kept version with parts of the other one: that version is « reprise en partie »
  const lent = ev.merged && crew.lanes.find((l) => l.id === ev.merged);
  if (lent && !lent.lent) {
    lent.lent = true;
    return t("agent.say.merged", { label: lent.label });
  }
  if (ev.status !== "running" && lane.since && !lane.seconds)
    lane.seconds = (Date.now() - lane.since) / 1000;
  if (was === ev.status) return "";
  if (ev.status === "done") return t("agent.say.done", { label: lane.label });
  if (ev.status === "error") return t("agent.say.error", { label: lane.label });
  return "";
}

/** A note typed in « Ajouter une consigne », before the server acknowledges it. */
export function addNote(turn, note, delivered) {
  if (!turn.crew) return;
  turn.crew.notes.push({ ...note, status: delivered ? "sent" : "queued" });
}

// set through CSSOM: the CSP forbids style attributes
function bar(progress) {
  const fill = h("span", { class: "crew-bar-fill" });
  fill.style.inlineSize = `${Math.round(Math.max(0.04, Math.min(1, Number(progress) || 0)) * 100)}%`;
  return fill;
}

const pct = (v) => `${Math.round((Number(v) || 0) * 100)} %`;

function detailOf(lane) {
  if (lane.role === "redacteur" && lane.score) {
    const n = lane.score.unsupported || 0;
    return t(n ? "agent.score.bad" : "agent.score.ok", {
      p: pct(lane.score.points),
      n,
    });
  }
  if (lane.status === "skipped")
    return lane.info && !["budget", "time"].includes(lane.info)
      ? lane.info
      : t("agent.skipped");
  if (lane.status === "error") return t("agent.error");
  if (lane.status === "stopped") return t("agent.status.stopped");
  if (lane.status === "cancelled") return t("agent.status.cancelled");
  return lane.info || lane.detail || "";
}

function laneCard(turn, lane) {
  const tools = (turn.steps || []).filter((s) => s.agent === lane.id);
  const counts = new Map();
  for (const s of tools)
    counts.set(toolLabel(s.tool), (counts.get(toolLabel(s.tool)) || 0) + 1);
  const running = lane.status === "running";
  const state =
    {
      done: "✓",
      error: "✕",
      skipped: "–",
      cancelled: "–",
      stopped: "■",
      queued: "",
      running: "",
    }[lane.status] ?? "";
  return h(
    "li",
    {
      class: `crew-lane is-${lane.status}${lane.chosen ? " is-chosen" : ""}`,
      "data-lane": lane.id,
      "data-status": lane.status,
    },
    h("span", { class: "crew-ic" }, svg(ROLE[lane.role] || ROLE.planificateur)),
    h(
      "div",
      { class: "crew-body" },
      h(
        "p",
        { class: "crew-label" },
        h("span", { text: lane.label }),
        lane.chosen && h("span", { class: "crew-kept", text: t("agent.kept") }),
        !lane.chosen &&
          lane.lent &&
          h("span", { class: "crew-kept is-part", text: t("agent.kept.part") }),
      ),
      detailOf(lane) && h("p", { class: "crew-detail", text: detailOf(lane) }),
      counts.size > 0 &&
        h("p", {
          class: "crew-tools",
          text: [...counts]
            .map(([k, n]) => (n > 1 ? `${k} ×${n}` : k))
            .join(" · "),
        }),
      running &&
        h(
          "span",
          { class: "crew-bar", role: "presentation" },
          bar(lane.progress),
        ),
    ),
    h(
      "span",
      { class: "crew-state" },
      h("span", { class: "crew-dot", "aria-hidden": "true", text: state }),
      h("span", { class: "sr-only", text: t(`agent.status.${lane.status}`) }),
      // filled at once (the board is redrawn faster than the 1 s ticker), and hidden from screen readers: the
      // sr-only status above carries the state, a timer read out every second would be noise
      running && lane.since
        ? h("span", {
            class: "num crew-time",
            "data-since": String(lane.since),
            "aria-hidden": "true",
            text: elapsed(lane.since),
          })
        : lane.seconds > 0 && !["skipped", "cancelled"].includes(lane.status)
          ? h("span", {
              class: "num crew-time",
              "aria-hidden": "true",
              text: fmtSeconds(lane.seconds),
            })
          : null,
    ),
  );
}

function board(turn, crew) {
  const groups = [];
  for (const lane of crew.lanes) {
    let g = groups.find((x) => x.id === lane.group);
    if (!g) groups.push((g = { id: lane.group, lanes: [] }));
    g.lanes.push(lane);
  }
  return h(
    "div",
    { class: "crew-board" },
    groups.map((g) =>
      h(
        "div",
        {
          class: `crew-phase${g.lanes.every((l) => ["skipped", "cancelled"].includes(l.status)) ? " is-skipped" : ""}`,
          "data-phase": g.id,
        },
        h("p", { class: "crew-phase-name", text: t(`agent.phase.${g.id}`) }),
        h(
          "ol",
          {
            class: `crew-lanes${g.lanes.length > 1 ? " is-parallel" : ""}`,
            "aria-label": t(`agent.phase.${g.id}`),
          },
          g.lanes.map((l) => laneCard(turn, l)),
        ),
      ),
    ),
  );
}

// ------------------------------------------------------------------ what the team is doing, in one line

const host = (url) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
};
/** Pages the team reads or read, in order, one per site: {site, status}. From the tool steps (never the model). */
function pagesOf(turn) {
  const out = [];
  for (const s of turn.steps || []) {
    if (!s.agent || s.tool !== "read_page") continue;
    const site = host(s.arguments?.url);
    if (!site) continue;
    const got = out.find((x) => x.site === site);
    const status = s.status === "running" ? "running" : s.status === "done" ? "done" : "error";
    if (got) {
      got.status = got.status === "done" ? "done" : status;
      got.pages += 1;
      got.read += status === "done" ? 1 : 0;
    } else out.push({ site, status, pages: 1, read: status === "done" ? 1 : 0 });
  }
  return out;
}
const pagesRead = (turn) => pagesOf(turn).reduce((n, p) => n + p.read, 0);
const PHASE_STEP = {
  research: ["research", "plan"],
  brief: ["read", "read_offers", "read_notes", "read_table", "research"],
  drafts: ["drafts", "draft_one"],
  check: ["check"],
  fix: ["check"],
  build: ["build"],
};
/** The phase the team is in: the latest one with a lane running, else the latest one that finished. */
function currentPhase(crew) {
  const order = [
    "research",
    "plan",
    "brief",
    "drafts",
    "check",
    "fix",
    "build",
  ];
  let cur = "";
  for (const id of order) {
    const lanes = crew.lanes.filter((l) => l.group === id);
    if (lanes.some((l) => l.status === "running")) cur = id;
  }
  if (cur) return cur;
  for (const id of order)
    if (
      crew.lanes.some(
        (l) => l.group === id && ["done", "error"].includes(l.status),
      )
    )
      cur = id;
  return cur || "research";
}

/** « Lit 3 pages », « Rédige 2 versions en parallèle »… (present tense, from the lanes and tool steps). */
export function activity(turn) {
  const crew = turn.crew;
  if (!crew) return "";
  if (crew.next) return t("agent.now.slice");
  const running = crew.lanes.filter((l) => l.status === "running");
  const steps = (turn.steps || []).filter((s) => s.agent);
  const reading = steps.filter(
    (s) => s.tool === "read_page" && s.status === "running",
  ).length;
  const searching = steps.filter(
    (s) => s.tool === "web_search" && s.status === "running",
  ).length;
  const read = pagesRead(turn);
  const role = (r) => running.some((l) => l.role === r);
  if (role("assembleur"))
    return t(
      `agent.now.build.${turn.crewPlan?.plan?.deliverable || crew.plan?.deliverable || "file"}`,
    );
  if (role("correcteur")) return t("agent.now.fix");
  if (role("verificateur")) return t("agent.now.check");
  if (role("redacteur"))
    return t(
      running.filter((l) => l.role === "redacteur").length > 1
        ? "agent.now.drafts"
        : "agent.now.draft",
    );
  if (role("lecteur"))
    return read
      ? tn("agent.now.extract", read)
      : t("agent.now.read.notes");
  if (role("analyste")) return t("agent.now.costs");
  if (reading)
    return tn("agent.now.reading", Math.max(reading, read + reading));
  if (searching) return tn("agent.now.search", searching);
  if (role("chercheur"))
    return crew.questions.length
      ? tn("agent.now.search", crew.questions.length)
      : t("agent.now.plan");
  if (role("planificateur")) return t("agent.now.plan");
  return t("agent.now.next");
}

/** « 3 pages lues · 14 chiffres vérifiés · 2 versions » (past tense, counts only). */
function pastBits(turn, crew) {
  const bits = [];
  const read = pagesRead(turn);
  if (read) bits.push(tn("agent.past.read", read));
  if (turn.checks?.verified)
    bits.push(tn("agent.past.verified", turn.checks.verified));
  else if (turn.checks?.actions?.length)
    bits.push(tn("agent.past.actions", turn.checks.actions.length));
  const drafts = crew.lanes.filter(
    (l) => l.role === "redacteur" && ["done"].includes(l.status),
  ).length;
  if (drafts > 1) bits.push(tn("agent.past.drafts", drafts));
  return bits;
}

function summary(turn, crew) {
  const d = crew.done;
  if (d.stopped) return t("agent.stopped");
  if (d.fallback === "single") return t("agent.fallback");
  if (d.dropped) return t("agent.dropped");
  // a refused confirmation is the user's choice, not a failure: the plain summary
  if (!d.ok && !d.denied) return t("agent.failed");
  const n = crew.lanes.filter(
    (l) =>
      !["skipped", "cancelled"].includes(l.status) &&
      !["verificateur", "assembleur"].includes(l.role), // the checker and the builder are code
  ).length;
  const parts = [t("agent.summary", { n }), ...pastBits(turn, crew)];
  if (d.seconds) parts.push(fmtSeconds(d.seconds));
  const wh = turn.usage?.energy_wh ?? d.energy_wh;
  if (typeof wh === "number") parts.push(`${fmtSig(wh)} Wh`);
  return parts.join(" · ");
}

// ------------------------------------------------------------------ the plan, its current step, sources, notes

function planSteps(crew, done) {
  const steps = crew.plan?.steps || [];
  if (!steps.length) return null;
  const phase = currentPhase(crew);
  const cur = PHASE_STEP[phase] || [];
  const ids = steps.map((s) => s.id);
  const at = ids.indexOf(cur.find((id) => ids.includes(id)));
  return h(
    "ol",
    { class: "crew-steps", "aria-label": t("agent.plan.steps") },
    steps.map((s, i) => {
      const state = done || i < at ? "done" : i === at ? "current" : "next";
      return h(
        "li",
        {
          class: `crew-step is-${state}`,
          "data-step": s.id,
          ...(state === "current" ? { "aria-current": "step" } : {}),
        },
        h(
          "span",
          { class: "crew-step-mark", "aria-hidden": "true" },
          state === "done" ? svg(GLYPH.check) : String(i + 1),
        ),
        h("span", { class: "crew-step-label", text: s.label }),
      );
    }),
  );
}

function sourceChips(turn) {
  const pages = pagesOf(turn);
  if (!pages.length) return null;
  return h(
    "div",
    { class: "crew-sources" },
    h("p", { class: "crew-sub", text: t("agent.sources.read") }),
    h(
      "ul",
      { class: "crew-chips", "aria-label": t("agent.sources.read") },
      pages.map((p) =>
        h("li", {
          class: `crew-chip-site is-${p.status}`,
          "data-site": p.site,
          text: p.site,
        }),
      ),
    ),
  );
}

function noteFeed(crew) {
  if (!crew.notes.length) return null;
  return h(
    "div",
    { class: "crew-notes" },
    h("p", { class: "crew-sub", text: t("agent.notes.title") }),
    h(
      "ul",
      { class: "crew-note-list" },
      crew.notes.map((n) =>
        h(
          "li",
          {
            class: `crew-note is-${n.status}`,
            "data-note": n.id,
            "data-status": n.status,
          },
          svg(GLYPH.note),
          h("span", { class: "crew-note-text", text: noteText(n) }),
          h("span", {
            class: "crew-note-state",
            text: t(`agent.note.${n.status}`),
          }),
        ),
      ),
    ),
  );
}

export function noteText(n) {
  const v =
    n.kind === "audience"
      ? t(`agent.aud.${n.value}`)
      : n.kind === "length"
        ? t(`agent.len.${n.value}`)
        : n.value;
  return t(`agent.note.kind.${n.kind}`, { v });
}

function noteForm(turn, crew, handlers) {
  const ui = (turn.ui.noteForm = turn.ui.noteForm || {
    kind: "focus",
    value: "",
  });
  const choice =
    ui.kind === "audience" ? AUDIENCES : ui.kind === "length" ? LENGTHS : null;
  const kind = h(
    "select",
    {
      class: "crew-input",
      "aria-label": t("agent.note.kind"),
      "data-note-kind": "",
    },
    NOTE_KINDS.map((k) =>
      h("option", {
        value: k,
        selected: k === ui.kind,
        text: t(`agent.note.pick.${k}`),
      }),
    ),
  );
  kind.addEventListener("change", () => {
    ui.kind = kind.value;
    ui.value = "";
    handlers.onChange?.(turn);
  });
  const value = choice
    ? h(
        "select",
        {
          class: "crew-input",
          "aria-label": t("agent.note.value"),
          "data-note-value": "",
        },
        choice.map((v) =>
          h("option", {
            value: v,
            selected: v === ui.value,
            text: t(`agent.${ui.kind === "audience" ? "aud" : "len"}.${v}`),
          }),
        ),
      )
    : h("input", {
        class: "crew-input",
        type: "text",
        maxlength: ui.kind === "focus" ? "100" : "80",
        value: ui.value,
        placeholder: t(`agent.note.ph.${ui.kind}`),
        "aria-label": t("agent.note.value"),
        "data-note-value": "",
        autocomplete: "off",
      });
  if (choice && !ui.value) ui.value = choice[0];
  value.addEventListener(
    choice ? "change" : "input",
    () => (ui.value = value.value),
  );
  const submit = (e) => {
    e.preventDefault();
    const v = String(value.value || "").trim();
    if (!v) return value.focus();
    turn.ui.noteOpen = false;
    turn.ui.noteForm = { kind: ui.kind, value: "" };
    handlers.onAgentNote?.(turn, { kind: ui.kind, value: v.slice(0, 200) });
  };
  return h(
    "form",
    { class: "crew-note-form", "data-note-form": "", onsubmit: submit },
    h("label", { class: "crew-sub", text: t("agent.note.title") }),
    h(
      "div",
      { class: "crew-note-row" },
      kind,
      value,
      h("button", {
        class: "btn btn-primary btn-small",
        type: "submit",
        text: t("agent.note.send"),
      }),
    ),
    h("p", { class: "crew-hint", text: t("agent.note.hint") }),
  );
}

// ------------------------------------------------------------------ the plan card (before launch)

function chip(label, value) {
  return h(
    "li",
    { class: "plan-fact" },
    h("span", { class: "plan-fact-k", text: label }),
    h("span", { class: "plan-fact-v", text: value }),
  );
}

function siteList(sites) {
  return sites.length ? sites.join(", ") : "";
}

function editor(turn, cp, handlers) {
  const p = { ...cp.plan, ...cp.edits };
  const set = (k, v) => {
    cp.edits[k] = v;
    handlers.onChange?.(turn);
  };
  const seg = (name, values, cur, prefix) =>
    h(
      "fieldset",
      { class: "plan-field" },
      h("legend", { text: t(`agent.plan.${name}`) }),
      h(
        "div",
        { class: "plan-seg", role: "radiogroup" },
        values.map((v) =>
          h(
            "label",
            { class: `plan-seg-opt${v === cur ? " is-on" : ""}` },
            h("input", {
              type: "radio",
              name: `${name}-${turn.id}`,
              value: v,
              checked: v === cur,
              onchange: () => set(name, v),
            }),
            h("span", { text: t(`agent.${prefix}.${v}`) }),
          ),
        ),
      ),
    );
  const sections = Array.isArray(p.sections) ? p.sections : [];
  const secInput = h("input", {
    class: "crew-input",
    type: "text",
    maxlength: "80",
    placeholder: t("agent.plan.section.ph"),
    "aria-label": t("agent.plan.section.add"),
    "data-plan-section": "",
  });
  const addSection = () => {
    const v = secInput.value.trim();
    if (!v || sections.length >= 8) return;
    set("sections", [...sections, v.slice(0, 80)]);
  };
  secInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addSection();
    }
  });
  const sites = (key) => {
    const input = h("input", {
      class: "crew-input",
      type: "text",
      maxlength: "200",
      value: siteList(p[key] || []),
      placeholder: t(`agent.plan.${key}.ph`),
      "aria-label": t(`agent.plan.${key}`),
      "data-plan-sites": key,
      inputmode: "url",
      autocomplete: "off",
    });
    input.addEventListener("change", () => {
      cp.edits[key] = input.value
        .split(/[\s,;]+/)
        .map((x) => x.trim())
        .filter(Boolean)
        .slice(0, 6);
    });
    return h(
      "label",
      { class: "plan-field" },
      h("span", { class: "plan-label", text: t(`agent.plan.${key}`) }),
      input,
    );
  };
  const focus = h("input", {
    class: "crew-input",
    type: "text",
    maxlength: "100",
    value: p.focus || "",
    placeholder: t("agent.plan.focus.ph"),
    "data-plan-focus": "",
  });
  focus.addEventListener("input", () => (cp.edits.focus = focus.value));
  return h(
    "div",
    { class: "plan-editor", "data-plan-editor": "" },
    seg("audience", AUDIENCES, p.audience, "aud"),
    seg("length", LENGTHS, p.length, "len"),
    Number.isInteger(p.n_slides) &&
      h(
        "div",
        { class: "plan-field plan-count" },
        h("span", { class: "plan-label", text: t("agent.plan.slides") }),
        h(
          "button",
          {
            class: "btn btn-outline btn-small btn-icon",
            type: "button",
            "aria-label": t("agent.plan.less"),
            disabled: p.n_slides <= 3,
            onclick: () => set("n_slides", Math.max(3, p.n_slides - 1)),
          },
          svg(GLYPH.minus),
        ),
        h("output", {
          class: "num plan-count-n",
          "data-plan-count-n": "",
          text: String(p.n_slides),
        }),
        h(
          "button",
          {
            class: "btn btn-outline btn-small btn-icon",
            type: "button",
            "aria-label": t("agent.plan.more"),
            disabled: p.n_slides >= 12,
            onclick: () => set("n_slides", Math.min(12, p.n_slides + 1)),
          },
          svg(GLYPH.plus),
        ),
      ),
    h(
      "div",
      { class: "plan-field" },
      h("span", { class: "plan-label", text: t("agent.plan.sections") }),
      sections.length > 0 &&
        h(
          "ul",
          { class: "plan-tags" },
          sections.map((s, i) =>
            h(
              "li",
              { class: "plan-tag" },
              h("span", { text: s }),
              h(
                "button",
                {
                  class: "plan-tag-x",
                  type: "button",
                  "aria-label": t("agent.plan.section.remove", { s }),
                  onclick: () =>
                    set(
                      "sections",
                      sections.filter((_, j) => j !== i),
                    ),
                },
                svg(GLYPH.close),
              ),
            ),
          ),
        ),
      sections.length < 8 &&
        h(
          "div",
          { class: "plan-add" },
          secInput,
          h("button", {
            class: "btn btn-outline btn-small",
            type: "button",
            onclick: addSection,
            text: t("agent.plan.section.add"),
          }),
        ),
    ),
    cp.plan.web && sites("prefer"),
    cp.plan.web && sites("exclude"),
    h(
      "label",
      { class: "plan-field" },
      h("span", { class: "plan-label", text: t("agent.plan.focus") }),
      focus,
    ),
  );
}

export function countdownText(cp) {
  const left = Math.max(0, Math.ceil((cp.deadline - Date.now()) / 1000));
  return t("agent.plan.count", { n: left });
}

function renderPlan(turn, handlers) {
  const cp = turn.crewPlan;
  const p = { ...cp.plan, ...cp.edits };
  const editing = cp.status === "editing";
  const counting =
    cp.status === "pending" && cp.deadline > 0 && turn.status === "plan";
  const facts = [
    p.labels?.deliverable &&
      chip(t("agent.plan.deliverable"), p.labels.deliverable),
    chip(t("agent.plan.audience"), t(`agent.aud.${p.audience}`)),
    chip(t("agent.plan.length"), t(`agent.len.${p.length}`)),
    Number.isInteger(p.n_slides) &&
      chip(t("agent.plan.slides"), String(p.n_slides)),
    (p.sections || []).length > 0 &&
      chip(t("agent.plan.sections"), p.sections.join(" · ")),
    (p.prefer || []).length > 0 &&
      chip(t("agent.plan.prefer"), siteList(p.prefer)),
    (p.exclude || []).length > 0 &&
      chip(t("agent.plan.exclude"), siteList(p.exclude)),
    p.focus && chip(t("agent.plan.focus"), p.focus),
  ];
  const live = turn.status === "plan";
  const card = h(
    "section",
    {
      class: `crew-plan${editing ? " is-editing" : ""}`,
      "aria-labelledby": `plan-${turn.id}`,
      "data-plan": cp.status,
    },
    h(
      "header",
      { class: "plan-head" },
      h("span", { class: "crew-mark", "aria-hidden": "true", text: "✦" }),
      h("h3", {
        class: "plan-title",
        id: `plan-${turn.id}`,
        text: t("agent.plan.title"),
      }),
      cp.reason && h("span", { class: "crew-why", text: cp.reason }),
      cp.demo && h("span", { class: "badge badge-demo", text: cp.demo }),
    ),
    h(
      "ol",
      { class: "crew-steps is-plan", "aria-label": t("agent.plan.steps") },
      (p.steps || []).map((s, i) =>
        h(
          "li",
          { class: "crew-step is-next" },
          h("span", {
            class: "crew-step-mark",
            "aria-hidden": "true",
            text: String(i + 1),
          }),
          h("span", { class: "crew-step-label", text: s.label }),
        ),
      ),
    ),
    !editing && h("ul", { class: "plan-facts" }, facts),
    editing && editor(turn, cp, handlers),
    live &&
      h(
        "footer",
        { class: "plan-foot" },
        h(
          "button",
          {
            class: "btn btn-primary btn-small",
            type: "button",
            "data-act": "plan-launch",
            onclick: () => handlers.onPlanLaunch?.(turn),
          },
          svg(GLYPH.play),
          h("span", { text: t("agent.plan.launch") }),
        ),
        h(
          "button",
          {
            class: "btn btn-outline btn-small",
            type: "button",
            "data-act": "plan-edit",
            "aria-expanded": editing ? "true" : "false",
            onclick: () => handlers.onPlanEdit?.(turn),
          },
          svg(editing ? GLYPH.check : GLYPH.edit),
          h("span", {
            text: t(editing ? "agent.plan.done" : "agent.plan.edit"),
          }),
        ),
        counting &&
          h(
            "span",
            {
              class: "plan-count-down",
              "data-plan-countdown": "",
              role: "timer",
              "aria-live": "off",
            },
            h("span", { class: "plan-ring", "aria-hidden": "true" }),
            h("span", { "data-plan-count": "", text: countdownText(cp) }),
          ),
        h("button", {
          class: "link plan-simple",
          type: "button",
          "data-act": "plan-simple",
          onclick: () => handlers.onAgentOff?.(turn),
          text: t("agent.plan.simple"),
        }),
      ),
  );
  if (counting) card.style.setProperty("--plan-s", `${cp.auto}s`);
  return card;
}

// ------------------------------------------------------------------ the team card

/** The plan card, or the chip and the activity; once done, one folded line. */
export function renderAgents(turn, handlers) {
  if (
    turn.crewPlan &&
    !turn.crew &&
    ["pending", "editing"].includes(turn.crewPlan.status)
  )
    return renderPlan(turn, handlers);
  const crew = turn.crew;
  if (!crew) {
    return turn.crewNote
      ? h(
          "div",
          { class: "crew-chip is-note" },
          h("span", { class: "crew-mark", "aria-hidden": "true", text: "✦" }),
          h("span", { text: turn.crewNote }),
        )
      : null;
  }
  const live = turn.status === "running" && !crew.done;
  const chip_ = h(
    "div",
    { class: "crew-chip" },
    h("span", { class: "crew-mark", "aria-hidden": "true", text: "✦" }),
    h("span", {
      class: "crew-title",
      text: t(crew.forced ? "agent.chip.forced" : "agent.chip"),
    }),
    crew.reason && h("span", { class: "crew-why", text: crew.reason }),
    crew.demo && h("span", { class: "badge badge-demo", text: crew.demo }),
    live &&
      h("button", {
        class: "link crew-out",
        type: "button",
        "data-act": "agent-off",
        text: t("agent.out"),
        onclick: () => handlers.onAgentOff?.(turn),
      }),
  );
  if (!crew.done) {
    const open = turn.ui?.crewCollapsed !== true;
    const now = h(
      "div",
      { class: "crew-now", "data-crew-now": "" },
      h("span", {
        class: `crew-pulse${live ? "" : " is-idle"}`,
        "aria-hidden": "true",
      }),
      h("span", { class: "crew-now-text", text: activity(turn) }),
      live &&
        h("span", {
          class: "num crew-now-time",
          "data-since": String(crew.started),
          "aria-hidden": "true",
          text: elapsed(crew.started),
        }),
      h(
        "span",
        { class: "crew-now-acts" },
        live &&
          crew.run &&
          h(
            "button",
            {
              class: "btn btn-quiet btn-small crew-act",
              type: "button",
              "data-act": "agent-note",
              "aria-label": t("agent.note.add"),
              "aria-expanded": turn.ui?.noteOpen ? "true" : "false",
              onclick: () => handlers.onNoteToggle?.(turn),
            },
            svg(GLYPH.plus),
            h("span", { class: "crew-act-long", text: t("agent.note.add") }),
            h("span", { class: "crew-act-short", "aria-hidden": "true", text: t("agent.note.add.short") }),
          ),
        live &&
          h(
            "button",
            {
              class: "btn btn-quiet btn-small crew-act crew-stop",
              type: "button",
              "data-act": "agent-stop",
              onclick: () => handlers.onStop?.(),
            },
            svg(GLYPH.stop),
            h("span", { text: t("agent.stop") }),
          ),
        h(
          "button",
          {
            class: "btn btn-quiet btn-small btn-icon crew-toggle",
            type: "button",
            "aria-expanded": open ? "true" : "false",
            "aria-label": t(open ? "agent.less" : "agent.more"),
            "data-act": "agent-toggle",
            onclick: () => handlers.onCrewToggle?.(turn),
          },
          svg(GLYPH.chevron),
        ),
      ),
    );
    const notify =
      live && typeof window !== "undefined" && window.Notification?.permission === "default" && handlers.onNotify
        ? h("button", { class: "link crew-notify", type: "button", "data-act": "agent-notify", onclick: () => handlers.onNotify(), text: t("agent.notify.ask") })
        : null;
    return h(
      "section",
      { class: "crew", "aria-label": t("agent.title") },
      chip_,
      now,
      notify,
      live && turn.ui?.noteOpen && noteForm(turn, crew, handlers),
      open && planSteps(crew, false),
      open &&
        crew.questions.length > 0 &&
        h(
          "ul",
          { class: "crew-questions", "aria-label": t("agent.questions") },
          crew.questions.map((q) => h("li", { text: q })),
        ),
      open && sourceChips(turn),
      open && board(turn, crew),
      noteFeed(crew),
    );
  }
  const caveats = (crew.done.caveats || []).length;
  const failed = crew.lanes.filter((l) => l.status === "error").length;
  const box = h(
    "details",
    { class: "crew-fold", open: !!turn.ui?.crewOpen },
    h(
      "summary",
      { "data-crew-summary": "" },
      h("span", { class: "crew-sum-text", text: summary(turn, crew) }),
      turn.usage?.energy_method === "power_time" &&
        turn.usage?.busy_seconds_sum > 0 &&
        h("span", {
          class: "crew-sum-hint",
          title: t("agent.energy.hint", {
            s: fmtSig(turn.usage.gpu_seconds_union || 0),
            sum: fmtSig(turn.usage.busy_seconds_sum),
          }),
          text: t("agent.energy.union"),
        }),
      caveats > 0 &&
        h("span", {
          class: "badge badge-warn",
          text: t("agent.caveats", { n: caveats }),
        }),
      // seen while the board is folded: one specialist failed even if the team delivered
      failed > 0 &&
        crew.done.ok &&
        h("span", {
          class: "badge badge-warn",
          "data-lane-failed": String(failed),
          text: t(
            failed === 1 ? "agent.lane.failed.one" : "agent.lane.failed",
            { n: failed },
          ),
        }),
    ),
    h("p", { class: "crew-sub crew-did", text: t("agent.did") }),
    planSteps(crew, !!crew.done.ok),
    crew.questions.length > 0 &&
      h(
        "ul",
        { class: "crew-questions", "aria-label": t("agent.questions") },
        crew.questions.map((q) => h("li", { text: q })),
      ),
    sourceChips(turn),
    board(turn, crew),
    noteFeed(crew),
  );
  box.addEventListener("toggle", () => {
    if (turn.ui) turn.ui.crewOpen = box.open;
  });
  // the connection was lost after the research: the team resumes from its checkpoint (the pages are not read again)
  const resume =
    crew.checkpoint &&
    crew.done.dropped &&
    turn.status !== "running" &&
    handlers.onResume &&
    !(crew.checkpointExp && crew.checkpointExp <= Date.now() / 1000) // the server would refuse an expired state
      ? h(
          "div",
          { class: "crew-resume" },
          h("button", { class: "btn btn-primary btn-small", type: "button", "data-act": "agent-resume", onclick: () => handlers.onResume(turn) }, svg(GLYPH.play), h("span", { text: t("agent.resume") })),
          h("span", { class: "crew-hint", text: t("agent.resume.hint") }),
        )
      : null;
  return h(
    "section",
    { class: "crew is-done", "aria-label": t("agent.title") },
    chip_,
    box,
    resume,
  );
}

// ------------------------------------------------------------------ « Vérifications faites »

const ORIGIN = {
  source: "agent.check.origin.source",
  request: "agent.check.origin.request",
  computed: "agent.check.origin.computed",
  none: "agent.check.origin.none",
};

function checkRow(i) {
  return h(
    "li",
    { class: `vc-item is-${i.status}`, "data-check": i.status },
    h("span", { class: "vc-value num", text: i.value || "—" }),
    h(
      "div",
      { class: "vc-body" },
      h("p", { class: "vc-sentence", text: i.sentence }),
      i.status === "removed"
        ? h("p", { class: "vc-why", text: t("agent.check.why.removed") })
        : i.origin === "source" && i.line
          ? h(
              "blockquote",
              { class: "vc-line" },
              svg(GLYPH.quote),
              h("span", { text: i.line }),
              h("cite", {
                class: "vc-src",
                text: [i.n ? `[${i.n}]` : "", i.site].filter(Boolean).join(" "),
              }),
            )
          : h("p", {
              class: "vc-why",
              text:
                ["claim", "derived", "cited"].includes(i.why)
                  ? t(`agent.check.why.${i.why}`, { n: i.n || "" })
                  : [t(ORIGIN[i.origin]), i.line && `« ${i.line} »`]
                      .filter(Boolean)
                      .join(" : "),
            }),
    ),
    h(
      "span",
      { class: "vc-state" },
      h("span", { class: "sr-only", text: t(`agent.check.${i.status}.one`) }),
      h("span", {
        "aria-hidden": "true",
        text: { verified: "✓", removed: "−", review: "!" }[i.status],
      }),
    ),
  );
}

/** The verification card: counts in one line, every figure with the line of the page it comes from. */
export function renderChecks(turn) {
  const c = turn.checks;
  if (!c || !(c.verified || c.removed || c.review || c.actions.length))
    return null;
  const open = !!turn.ui?.checksOpen;
  const counts = [
    c.verified > 0 &&
      h(
        "span",
        { class: "vc-count is-verified" },
        h("b", { class: "num", text: fmtInt(c.verified) }),
        ` ${tn("agent.check.verified", c.verified)}`,
      ),
    c.removed > 0 &&
      h(
        "span",
        { class: "vc-count is-removed" },
        h("b", { class: "num", text: fmtInt(c.removed) }),
        ` ${tn("agent.check.removed", c.removed)}`,
      ),
    c.review > 0 &&
      h(
        "span",
        { class: "vc-count is-review" },
        h("b", { class: "num", text: fmtInt(c.review) }),
        ` ${tn("agent.check.review", c.review)}`,
      ),
    !c.verified &&
      c.actions.length > 0 &&
      h(
        "span",
        { class: "vc-count is-verified" },
        h("b", { class: "num", text: fmtInt(c.actions.length) }),
        ` ${tn("agent.check.actions", c.actions.length)}`,
      ),
  ];
  const groups = ["review", "removed", "verified"]
    .map((s) => [s, c.items.filter((i) => i.status === s)])
    .filter(([, l]) => l.length);
  const box = h(
    "details",
    { class: "vc", open, "data-checks": "" },
    h(
      "summary",
      { class: "vc-head" },
      h(
        "span",
        { class: "vc-badge", "aria-hidden": "true" },
        svg(GLYPH.shield),
      ),
      h(
        "span",
        { class: "vc-title-wrap" },
        h("span", { class: "vc-title", text: t("agent.check.title") }),
        h("span", { class: "vc-counts" }, counts),
      ),
      h(
        "span",
        { class: "vc-chev", "aria-hidden": "true" },
        svg(GLYPH.chevron),
      ),
    ),
    h(
      "div",
      { class: "vc-body-wrap" },
      groups.map(([s, list]) =>
        h(
          "section",
          { class: "vc-group" },
          h("h4", {
            class: "vc-group-title",
            text: t(`agent.check.group.${s}`),
          }),
          h("ol", { class: "vc-list" }, list.map(checkRow)),
        ),
      ),
      c.actions.length > 0 &&
        h(
          "section",
          { class: "vc-group" },
          h("h4", {
            class: "vc-group-title",
            text: t("agent.check.group.actions"),
          }),
          h(
            "ol",
            { class: "vc-list" },
            c.actions.map((a) =>
              h(
                "li",
                { class: "vc-item is-verified" },
                h("span", { class: "vc-value", text: a.owner || "—" }),
                h(
                  "div",
                  { class: "vc-body" },
                  h("p", { class: "vc-sentence", text: a.action }),
                  h("p", {
                    class: "vc-why",
                    text: [
                      a.due && t("agent.check.due", { d: a.due }),
                      a.line && t("agent.check.line", { n: a.line }),
                    ]
                      .filter(Boolean)
                      .join(" · "),
                  }),
                ),
                h("span", {
                  class: "vc-state",
                  "aria-hidden": "true",
                  text: "✓",
                }),
              ),
            ),
          ),
        ),
      c.more > 0 &&
        h("p", {
          class: "crew-hint",
          text: tn("agent.check.more", c.more),
        }),
      h("p", { class: "vc-foot", text: t("agent.check.foot") }),
    ),
  );
  box.addEventListener("toggle", () => {
    if (turn.ui) turn.ui.checksOpen = box.open;
  });
  return box;
}

// ------------------------------------------------------------------ « Livrables » of the conversation

/** Every file the conversation produced, newest first: {name, title, kind, turn, file}. From the turns' files. */
export function deliverablesOf(conv) {
  const out = [];
  for (const turn of conv?.turns || []) {
    if (turn.role !== "assistant") continue;
    for (const f of turn.files || []) {
      if (!f || typeof f.name !== "string") continue;
      const kind =
        f.preview?.kind ||
        (/\.pptx$/i.test(f.name)
          ? "slides"
          : /\.docx$/i.test(f.name)
            ? "document"
            : /\.xlsx$/i.test(f.name)
              ? "sheet"
              : "file");
      out.push({
        name: f.name,
        title: f.preview?.title || f.name,
        kind,
        turn: turn.id,
        file: f,
        team: !!turn.crew,
      });
    }
  }
  return out.reverse();
}
