// Unit tests of the Mode Agent state (agents.js applyAgentEvent): lane states at the end of a run, the folded line,
// and what a screen reader hears. Run: node --test tests/js/  (pytest runs it too: tests/test_web.py).
import assert from "node:assert/strict";
import { test } from "node:test";

import { applyAgentEvent } from "../../birds/web/static/agents.js";
import { state } from "../../birds/web/static/core.js";

state.prefs.lang = "fr";

const LANES = [
  { id: "chercheur", role: "chercheur", label: "Recherche", group: "research" },
  { id: "redacteur_a", role: "redacteur", label: "Version A", group: "drafts" },
  { id: "redacteur_b", role: "redacteur", label: "Version B", group: "drafts" },
  { id: "verificateur", role: "verificateur", label: "Vérification", group: "check" },
  { id: "assembleur", role: "assembleur", label: "Fichier", group: "build" },
];

function team() {
  const turn = { status: "running", steps: [] };
  applyAgentEvent(turn, { type: "agent_start", recipe: "deck_research", lanes: LANES });
  return turn;
}
const step = (turn, id, status, extra = {}) => applyAgentEvent(turn, { type: "agent_step", id, status, ...extra });
const statuses = (turn) => Object.fromEntries(turn.crew.lanes.map((l) => [l.id, l.status]));

test("transitions are announced: a lane done or failed, the version kept, the summary", () => {
  const turn = team();
  assert.equal(step(turn, "chercheur", "running"), "");
  assert.equal(step(turn, "chercheur", "done"), "Recherche : terminé");
  assert.equal(step(turn, "chercheur", "done"), ""); // no repeat
  assert.equal(step(turn, "redacteur_b", "error"), "Version B : n'a pas abouti");
  assert.equal(step(turn, "redacteur_a", "scored", { score: {}, chosen: true }), "Version A retenue");
  assert.equal(step(turn, "redacteur_b", "scored", { score: {}, chosen: false }), "");
  const said = applyAgentEvent(turn, { type: "agent_done", ok: true, seconds: 10.1, caveats: [] });
  assert.match(said, /^Équipe : \d agents/);
});

test("a server error or a lost connection: lanes never read « non nécessaire », the line says so", () => {
  for (const [ev, line] of [
    [{ error: true }, "L'équipe n'a pas abouti"],
    [{ error: true, dropped: true }, "Équipe interrompue : connexion perdue"],
    [{ reason: "no_facts" }, "L'équipe n'a pas abouti"], // crew._fallback with no time left: the abstain answer
  ]) {
    const turn = team();
    step(turn, "chercheur", "done");
    step(turn, "redacteur_a", "running");
    assert.equal(applyAgentEvent(turn, { type: "agent_done", ok: false, caveats: [], ...ev }), line);
    const s = statuses(turn);
    assert.equal(s.redacteur_a, "error");
    assert.equal(s.redacteur_b, "cancelled");
    assert.equal(s.assembleur, "cancelled");
  }
});

test("the user's Stop: running lanes « arrêté », waiting ones « non lancé », the line « interrompue »", () => {
  const turn = team();
  step(turn, "redacteur_a", "running");
  const said = applyAgentEvent(turn, { type: "agent_done", ok: false, stopped: true, caveats: [] });
  assert.equal(said, "Équipe interrompue");
  assert.equal(statuses(turn).redacteur_a, "stopped");
  assert.equal(statuses(turn).verificateur, "cancelled");
});

test("a successful team: lanes it did not need are « non nécessaire »; a refused confirmation is no failure", () => {
  const turn = team();
  applyAgentEvent(turn, { type: "agent_done", ok: true, caveats: [] });
  assert.equal(statuses(turn).assembleur, "skipped");
  const refused = team();
  for (const l of LANES) step(refused, l.id, "done");
  step(refused, "assembleur", "skipped", { detail: "refusé" });
  const said = applyAgentEvent(refused, { type: "agent_done", ok: false, denied: true, seconds: 2.1, caveats: [] });
  assert.match(said, /^Équipe : \d agents/);
  assert.equal(statuses(refused).assembleur, "skipped");
});
