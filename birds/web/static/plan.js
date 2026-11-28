// The task plan of a turn: a compact checklist of what the request asked for (« tableau », « totaux », « mail »),
// ticked from what the harness saw really happen (birds/harness/plan.py), never from the model's text.
// Shown only for a request that asked for two things or more. Open while the turn runs; folded once everything
// is done; open with a plain « Partiellement fait : mail manque » when something could not be done.
import { h, icon, t } from "./core.js";

const MARK = {
  done: "check",
  failed: "cross",
  unavailable: "minus",
  todo: null,
};

/** A plan event from the server, kept only when it is well formed (labels are plain text, at most 8 items). */
export function cleanPlan(raw) {
  if (!raw || !Array.isArray(raw.items)) return null;
  const items = raw.items
    .slice(0, 8)
    .filter((i) => i && typeof i.label === "string")
    .map((i) => ({
      kind: String(i.kind || ""),
      label: i.label.slice(0, 60),
      status: MARK[i.status] !== undefined ? i.status : "todo",
    }));
  if (items.length < 2) return null;
  return {
    items,
    final: !!raw.final,
    partial: !!raw.partial,
    missing: Array.isArray(raw.missing)
      ? raw.missing.map((m) => String(m).slice(0, 60)).slice(0, 8)
      : [],
  };
}

/** What a screen reader hears when an item gets ticked: « Fait : présentation ». */
export function planNews(before, after) {
  if (!after) return "";
  const was = new Map((before?.items || []).map((i) => [i.label, i.status]));
  const now = after.items.filter(
    (i) => i.status === "done" && was.get(i.label) !== "done",
  );
  return now.length
    ? t("plan.ticked", { items: now.map((i) => i.label).join(", ") })
    : "";
}

function missingText(plan) {
  const left = plan.missing.length
    ? plan.missing
    : plan.items.filter((i) => i.status !== "done").map((i) => i.label);
  return left.length === 1
    ? t("plan.partial.one", { item: left[0] })
    : t("plan.partial.many", { items: left.join(", ") });
}

/**
 * The head of the checklist: the check only when every item is done, the alert when the turn ended short (a final
 * partial plan, or an answer that failed before the plan's last word: « 0 sur 2 faites » is never ticked), nothing
 * while it runs or once stopped by the reader.
 */
export function planHead(plan, status) {
  const total = plan.items.length;
  const done = plan.items.filter((i) => i.status === "done").length;
  const running = (status === "running" || status === "confirm") && !plan.final;
  const ended = plan.final || status === "error" || status === "done";
  const partial = ended && !running && (plan.partial || done < total) && status !== "stopped";
  const icon = done === total && !plan.partial ? "check" : partial ? "alert" : null;
  return { done, total, running, partial, icon };
}

export function renderPlan(turn) {
  const plan = turn.plan;
  if (!plan || !Array.isArray(plan.items) || plan.items.length < 2) return null;
  const { done, running, partial, icon: head } = planHead(plan, turn.status);
  turn.ui = turn.ui || {};
  const open = turn.ui.planOpen ?? (running || partial);
  const box = h(
    "details",
    {
      class: `tplan${partial ? " tplan-partial" : ""}${plan.final && !partial ? " tplan-done" : ""}`,
      open,
    },
    h(
      "summary",
      { "data-act": "plan" },
      icon("chevron", "chev"),
      head && icon(head, "tplan-head-icon"),
      h("span", { class: "tplan-title", text: t("plan.title") }),
      h("span", {
        class: "tplan-count",
        text: t("plan.count", { done, total: plan.items.length }),
      }),
    ),
    h(
      "ol",
      { class: "tplan-list" },
      plan.items.map((item) =>
        h(
          "li",
          { class: `tplan-item is-${item.status}` },
          h(
            "span",
            { class: "tplan-mark", "aria-hidden": "true" },
            MARK[item.status] ? icon(MARK[item.status]) : null,
          ),
          h("span", { class: "tplan-label", text: item.label }),
          h("span", {
            class: "sr-only",
            text: ` — ${t(`plan.status.${item.status}`)}`,
          }),
        ),
      ),
    ),
  );
  let byUser = false;
  box.firstChild.addEventListener("click", () => (byUser = true));
  box.addEventListener("toggle", () => byUser && (turn.ui.planOpen = box.open));
  return h(
    "div",
    { class: "tplan-wrap" },
    box,
    // an answer that failed says so in its own notice: the « manquent » line is for a plan that ended short
    partial &&
      plan.final &&
      h(
        "p",
        { class: "tplan-missing", role: "status" },
        icon("alert"),
        h("span", { text: missingText(plan) }),
      ),
  );
}
