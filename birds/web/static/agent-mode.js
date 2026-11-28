// Mode Agent preference, per browser (Réglages): « auto » (default) or « off » are kept; « on » (Activé) lasts this
// session only, so a team is forced only when the user chose it in Settings in this session. A stored « on » from
// the old composer selector (which forced the team on every request, forever) is migrated once to « auto ».
export const AGENT_MODES = ["auto", "on", "off"];
const KEY = "bird.agent";
const SESSION_KEY = "bird.agent.session";
const MIGRATED = "bird.agent.v"; // "2": the old « on » was migrated

function safe(fn, fallback = null) {
  try {
    return fn();
  } catch {
    return fallback; // private mode, blocked storage: the default applies
  }
}

/** The Mode Agent for this page, from ``local`` (localStorage) and ``session`` (sessionStorage). */
export function loadAgentMode(local, session) {
  if (safe(() => local?.getItem(MIGRATED)) !== "2") {
    if (safe(() => local?.getItem(KEY)) === "on") safe(() => local.setItem(KEY, "auto"));
    safe(() => local?.setItem(MIGRATED, "2"));
  }
  if (safe(() => session?.getItem(SESSION_KEY)) === "on") return "on";
  const kept = safe(() => local?.getItem(KEY));
  return kept === "off" ? "off" : "auto";
}

/** Keep the choice made in Settings: « on » for this session only, « auto » / « off » for this browser. */
export function saveAgentMode(mode, local, session) {
  const v = AGENT_MODES.includes(mode) ? mode : "auto";
  if (v === "on") {
    safe(() => session?.setItem(SESSION_KEY, "on"));
  } else {
    safe(() => session?.removeItem(SESSION_KEY));
    safe(() => local?.setItem(KEY, v));
  }
  return v;
}
