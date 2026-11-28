// Mode Agent: « l'équipe au travail ». Parallel lanes per phase, live states, the version kept, then one line.
// Every text comes from the server's events or the i18n table and is set as text, never as HTML.
import { h, elapsed, fmtSeconds, fmtSig, t, toolLabel } from "./core.js";

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
const svg = (paths, cls = "") => {
  const wrap = document.createElement("span");
  wrap.innerHTML = `<svg class="icon ${cls}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${paths}</svg>`;
  return wrap.firstChild;
};

/** Fold one agent_* event into the turn (state only; the caller redraws). Returns the sentence a screen reader
 * should hear for this event (a lane finishing or failing, the version kept, the team's summary), or "". */
export function applyAgentEvent(turn, ev) {
  if (ev.type === "agent_start") {
    turn.crew = {
      recipe: ev.recipe,
      reason: String(ev.reason || ""),
      forced: !!ev.forced,
      demo: ev.demo ? String(ev.demo) : "",
      lanes: (ev.lanes || []).map((l) => ({ ...l, status: "queued" })),
      done: null,
    };
    return "";
  }
  const crew = turn.crew;
  if (ev.type === "agent_done") {
    if (!crew) {
      if (ev.reason === "no_deliverable")
        turn.crewNote = String(ev.message || t("agent.nothing"));
      return "";
    }
    crew.done = ev;
    for (const lane of crew.lanes) {
      // a lane still waiting when the team ends badly was needed but never ran: « non lancé », not « non nécessaire »
      if (lane.status === "queued") lane.status = ev.ok ? "skipped" : "cancelled";
      // the user stopped the team: a neutral « arrêté », not a red failure
      if (lane.status === "running")
        lane.status = ev.ok ? "done" : ev.stopped ? "stopped" : "error";
    }
    return summary(turn, crew);
  }
  if (ev.type !== "agent_step" || !crew) return "";
  const lane = crew.lanes.find((l) => l.id === ev.id);
  if (!lane) return "";
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
  // deep research: the sub-questions of the plan and the domains read (chips, text only)
  for (const k of ["items", "domains"])
    if (Array.isArray(ev[k])) lane[k] = ev[k].slice(0, 12).map((x) => String(x).slice(0, 160));
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
      lane.items?.length > 0 &&
        h("ol", { class: "crew-items" }, lane.items.map((x) => h("li", { text: x }))),
      lane.domains?.length > 0 &&
        h("ul", { class: "crew-chips", "aria-label": t("mod.research.sources") }, lane.domains.map((d) => h("li", { class: "crew-chip", text: d }))),
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

function summary(turn, crew) {
  const d = crew.done;
  if (d.stopped) return t("agent.stopped");
  if (d.fallback === "single") return t("agent.fallback");
  if (d.dropped) return t("agent.dropped");
  // a refused confirmation is the user's choice, not a failure: the plain summary
  if (!d.ok && !d.denied) return t("agent.failed");
  const n =
    crew.lanes.filter(
      (l) =>
        !["skipped", "cancelled"].includes(l.status) &&
        !["verificateur", "assembleur"].includes(l.role), // the checker and the builder are code
    ).length;
  const parts = [t("agent.summary", { n })];
  if (d.seconds) parts.push(fmtSeconds(d.seconds));
  const wh = turn.usage?.energy_wh ?? d.energy_wh;
  if (typeof wh === "number") parts.push(`${fmtSig(wh)} Wh`);
  return parts.join(" · ");
}

/** The chip (with the way out while it runs), then the board; once done, the board folds into one line. */
export function renderAgents(turn, handlers) {
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
  const chip = h(
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
  if (!crew.done)
    return h(
      "section",
      { class: "crew", "aria-label": t("agent.title") },
      chip,
      board(turn, crew),
    );
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
          text: t(failed === 1 ? "agent.lane.failed.one" : "agent.lane.failed", { n: failed }),
        }),
    ),
    board(turn, crew),
  );
  box.addEventListener("toggle", () => {
    if (turn.ui) turn.ui.crewOpen = box.open;
  });
  return h(
    "section",
    { class: "crew is-done", "aria-label": t("agent.title") },
    chip,
    box,
  );
}
