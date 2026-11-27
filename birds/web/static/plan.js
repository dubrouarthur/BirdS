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

export function renderPlan(turn) {
  const plan = turn.plan;
  if (!plan || !Array.isArray(plan.items) || plan.items.length < 2) return null;
  const done = plan.items.filter((i) => i.status === "done").length;
  const running = turn.status === "running" && !plan.final;
  const partial =
    plan.final &&
    (plan.partial || done < plan.items.length) &&
    turn.status !== "stopped";
  turn.ui = turn.ui || {};
  const open = turn.ui.planOpen ?? (running || partial);
  const box = h(
    "details",
    {
      class: `plan${partial ? " plan-partial" : ""}${plan.final && !partial ? " plan-done" : ""}`,
      open,
    },
    h(
      "summary",
      { "data-act": "plan" },
      icon("chevron", "chev"),
      icon(partial ? "alert" : "check", "plan-head-icon"),
      h("span", { class: "plan-title", text: t("plan.title") }),
      h("span", {
        class: "plan-count",
        text: t("plan.count", { done, total: plan.items.length }),
      }),
    ),
    h(
      "ol",
      { class: "plan-list" },
      plan.items.map((item) =>
        h(
          "li",
          { class: `plan-item is-${item.status}` },
          h(
            "span",
            { class: "plan-mark", "aria-hidden": "true" },
            MARK[item.status] ? icon(MARK[item.status]) : null,
          ),
          h("span", { class: "plan-label", text: item.label }),
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
    { class: "plan-wrap" },
    box,
    partial &&
      h(
        "p",
        { class: "plan-missing", role: "status" },
        icon("alert"),
        h("span", { text: missingText(plan) }),
      ),
  );
}
