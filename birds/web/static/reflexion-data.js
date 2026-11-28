// Mode Réflexion, pure part (no DOM): the five birds, their own SVG drawings and the readable facts of a flight.
// The server decides and checks (birds/harness/reflexion.py); this file only names and draws what it sent.
// Tested by tests/js/reflexion.test.mjs.

export const LEVELS = ["colibri", "hirondelle", "faucon", "chouette", "albatros"];
export const CHOICES = ["auto", ...LEVELS];

// Bird drawings, made for Bird (24 × 24, one filled silhouette each, currentColor). Constants, never model output.
export const BIRDS = {
  // hovering hummingbird, long beak to the left, wing raised
  colibri:
    '<path d="M1.6 9.9l6.2.5"/><path class="rf-fill" d="M7.6 10.6c0-1.7 1.4-3 3.1-3 1.2 0 2.1.6 2.700 1.600l4.8 6c.4.500-.1 1.200-.7.900l-3.300-1.600-1.400 3.700c-.2.600-1.100.500-1.100-.1v-2.900c-2.300-.4-4.200-2.300-4.200-4.600z"/><path class="rf-fill rf-wing" d="M12.400 9.300c1.200-3.800 4.300-6.200 9-6.800-1.400 3.300-4.100 6-7.700 7.500z"/><circle class="rf-eye" cx="10.300" cy="10" r=".75"/>',
  // swallow seen from below: swept wings, long forked tail
  hirondelle:
    '<path class="rf-fill rf-wing" d="M12 6.600c.9 0 1.500.8 1.500 1.800l8.300-2.300c-1.700 2.900-4.400 4.800-7.900 5.400l.3 3.100 2.700 5.600-3.800-3.400-1.100 2.200-1.100-2.200-3.800 3.400 2.700-5.600.3-3.100c-3.500-.6-6.200-2.500-7.900-5.400l8.300 2.300c0-1 .6-1.800 1.500-1.800z"/>',
  // falcon from below: wings bent at the wrist, pointed tips swept back, head and a fanned tail
  faucon:
    '<path class="rf-fill rf-wing" d="M12 4.300c.9 0 1.500.7 1.500 1.700v1.300l4.300-1.300 5 6.900c-3.400-1.300-6.400-1.700-9.300-1.300l-.2 3.200 2.300 5.100-3.600-1.400-3.600 1.400 2.300-5.100-.2-3.200c-2.900-.4-5.900 0-9.300 1.300l5-6.900 4.300 1.300V6c0-1 .6-1.700 1.500-1.700z"/>',
  // owl, front view: ear tufts, round face, two eyes and a small beak
  chouette:
    '<path class="rf-fill" fill-rule="evenodd" d="M6.300 8.600 5.400 3.600l3.700 2.500a7 7 0 0 1 5.800 0l3.700-2.500-.9 5c.8 1.100 1.200 2.400 1.200 3.800 0 4.600-3.200 8.300-6.900 8.300s-6.900-3.700-6.900-8.300c0-1.400.4-2.700 1.200-3.800zM9.400 13.600a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm5.200 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM11.200 14.400h1.600l-.8 1.600z"/><circle class="rf-fill" cx="9.400" cy="11.600" r=".85"/><circle class="rf-fill" cx="14.600" cy="11.600" r=".85"/>',
  // albatross gliding: very long, slender wings, slightly bowed
  albatros:
    '<path class="rf-fill rf-wing" d="M12 9.400c.7 0 1.200.4 1.500 1l9.700-1.900c-2.600 2.100-6 3.300-9.500 3.700l-.5 2.700 1.700 1.700h-5.800l1.700-1.700-.5-2.700c-3.500-.4-6.900-1.600-9.500-3.700l9.700 1.900c.3-.6.800-1 1.500-1z"/>',
  // Auto: a bird and the spark of the choice
  auto:
    '<path class="rf-fill rf-wing" d="M10 9.800c.8 0 1.300.7 1.300 1.500l6.900-1.900c-1.400 2.400-3.700 4-6.600 4.500l.3 2.600 2.200 4.600-3.200-2.800-.9 1.800-.9-1.800-3.200 2.800 2.200-4.600.3-2.600c-2.900-.5-5.200-2.100-6.600-4.500l6.900 1.900c0-.8.500-1.500 1.300-1.500z"/><path class="rf-fill" d="M18.500 1.800l.9 2.400 2.400.9-2.400.9-.9 2.400-.9-2.400-2.400-.9 2.400-.9z"/>',
};

export const normalizeChoice = (value) => (CHOICES.includes(value) ? value : "auto");

/** The reasoning switch older code reads: every bird but the hummingbird reasons; « Auto » lets the server see. */
export const thinks = (choice) => normalizeChoice(choice) !== "colibri";

/**
 * Readable facts of one flight, from the answer's ``reflexion`` field (birds/harness/reflexion.py ``public``):
 * [{kind, key, vars}] for t(key, vars). Only what the server reports: nothing is inferred here.
 */
export function flightFacts(rf) {
  if (!rf || !LEVELS.includes(rf.level)) return [];
  const out = [];
  const c = rf.checks || {};
  const calcs = Number(c.calcs) || 0;
  const wrong = Number(c.calc_wrong) || 0;
  const points = Number(c.points) || 0;
  const missing = Number(c.missing) || 0;
  if (rf.level === "colibri") out.push({ kind: "info", key: "rf.fact.instant" });
  if (calcs && rf.corrected && !wrong) out.push({ kind: "fixed", key: "rf.fact.calc.fixed", vars: { n: calcs } });
  else if (calcs && wrong) out.push({ kind: "warn", key: "rf.fact.calc.wrong", vars: { n: wrong } });
  else if (calcs) out.push({ kind: "ok", key: calcs > 1 ? "rf.fact.calc.ok.n" : "rf.fact.calc.ok.1", vars: { n: calcs } });
  if (points && missing) out.push({ kind: "warn", key: "rf.fact.points.missing", vars: { n: missing, total: points } });
  else if (points && rf.corrected && !calcs) out.push({ kind: "fixed", key: "rf.fact.points.fixed", vars: { n: points } });
  else if (points) out.push({ kind: "ok", key: "rf.fact.points.ok", vars: { n: points } });
  if (rf.reviewed) out.push({ kind: rf.review_changed ? "fixed" : "ok", key: rf.review_changed ? "rf.fact.review.fixed" : "rf.fact.review.ok" });
  if (rf.cut === "think_budget") out.push({ kind: "info", key: "rf.fact.cut.budget" });
  if (rf.cut === "repetition") out.push({ kind: "info", key: "rf.fact.cut.loop" });
  return out;
}

/** The muted line after the bird's name: its label, and who chose it. */
export function flightMetaKeys(rf) {
  if (!rf || !LEVELS.includes(rf.level)) return [];
  const who = rf.source === "crew" ? "rf.by.crew" : rf.source === "demo" ? "rf.by.demo" : rf.auto ? "rf.by.bird" : "rf.by.you";
  return [`rf.level.${rf.level}.label`, who];
}
