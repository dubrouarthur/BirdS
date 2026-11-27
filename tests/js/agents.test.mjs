// Unit tests of the Mode Agent state (agents.js applyAgentEvent): lane states at the end of a run, the folded line,
// and what a screen reader hears. Run: node --test tests/js/  (pytest runs it too: tests/test_web.py).
import assert from "node:assert/strict";
import { test } from "node:test";

import { activity, addNote, applyAgentEvent, deliverablesOf, noteText, tn } from "../../birds/web/static/agents.js";
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

// ------------------------------------------------------------------ wave 2: plan card, notes, checks, slices

test("the plan card: typed fields kept, a countdown only when the server gives one", () => {
  const turn = { status: "running", steps: [] };
  const plan = {
    recipe: "deck_research",
    deliverable: "make_slides",
    steps: [{ id: "research", label: "Chercher" }],
    audience: "everyone",
    length: "long",
    n_slides: 6,
    sections: ["<b>x</b>"],
    prefer: [],
    exclude: [],
    web: true,
  };
  const said = applyAgentEvent(turn, { type: "agent_plan", plan, token: "tok.sig", auto_start: 5 });
  assert.match(said, /5 secondes/);
  assert.equal(turn.crewPlan.plan.audience, "general"); // an unknown value falls back to the default
  assert.equal(turn.crewPlan.plan.length, "long");
  assert.ok(turn.crewPlan.deadline > Date.now());
  const manual = { status: "running", steps: [] };
  applyAgentEvent(manual, { type: "agent_plan", plan, token: "t", auto_start: null });
  assert.equal(manual.crewPlan.deadline, 0);
  assert.equal(applyAgentEvent({ steps: [] }, { type: "agent_plan", plan, token: 42 }), ""); // no token, no card
});

test("instructions: queued or sent, then acknowledged by the team", () => {
  const turn = team();
  addNote(turn, { id: "n1", kind: "exclude_site", value: "lemonde.fr" }, false);
  assert.equal(turn.crew.notes[0].status, "queued");
  assert.equal(
    applyAgentEvent(turn, { type: "agent_note", id: "n1", status: "applied" }),
    "Consigne appliquée par l'équipe",
  );
  assert.equal(turn.crew.notes[0].status, "applied");
  addNote(turn, { id: "n2", kind: "audience", value: "experts" }, true);
  assert.equal(noteText(turn.crew.notes[1]), "Public : Experts");
  applyAgentEvent(turn, { type: "agent_done", ok: true, caveats: [] });
  assert.equal(turn.crew.notes[1].status, "late"); // never acknowledged before the end
});

test("the verification card keeps typed values only", () => {
  const turn = team();
  applyAgentEvent(turn, {
    type: "agent_checks",
    verified_n: 14,
    removed_n: 2,
    review_n: 1,
    items: [
      { value: "26 %", sentence: "s", status: "verified", origin: "source", n: 2, line: "l", site: "insee.fr" },
      { value: "37 %", sentence: "s", status: "bogus", origin: "<script>" },
    ],
  });
  assert.equal(turn.checks.verified, 14);
  assert.equal(turn.checks.items[1].status, "review");
  assert.equal(turn.checks.items[1].origin, "none");
  assert.equal(tn("agent.check.verified", 1), "chiffre vérifié");
  assert.equal(tn("agent.check.verified", 14), "chiffres vérifiés");
});

test("a long task: the next slice token, then a checkpoint; the line says what the team does", () => {
  const turn = team();
  turn.steps = [
    { agent: "chercheur", tool: "read_page", status: "running", arguments: { url: "https://www.insee.fr/a" } },
  ];
  step(turn, "chercheur", "running");
  assert.equal(activity(turn), "Lit 1 page");
  applyAgentEvent(turn, { type: "agent_slice", token: "cp", auto: false });
  assert.equal(turn.crew.checkpoint, "cp");
  assert.equal(
    applyAgentEvent(turn, { type: "agent_slice", token: "next", auto: true }),
    "L'équipe continue la tâche dans une nouvelle étape.",
  );
  assert.equal(activity(turn), "Poursuit la tâche (étape suivante)");
  // the next slice's agent_start keeps what the team did so far
  turn.crew.notes.push({ id: "q", kind: "focus", value: "x", status: "sent" });
  applyAgentEvent(turn, { type: "agent_start", recipe: "deck_research", lanes: LANES, slice: 1 });
  assert.equal(turn.crew.notes.length, 1);
  assert.equal(turn.crew.checkpoint, "cp");
});

test("« Livrables »: every file of the conversation, newest first", () => {
  const conv = {
    turns: [
      { role: "user" },
      { role: "assistant", id: "a1", files: [{ name: "deck.pptx", preview: { kind: "slides", title: "Deck" } }], crew: {} },
      { role: "assistant", id: "a2", files: [{ name: "note.docx" }] },
    ],
  };
  assert.deepEqual(
    deliverablesOf(conv).map((d) => [d.name, d.kind, d.team]),
    [
      ["note.docx", "document", false],
      ["deck.pptx", "slides", true],
    ],
  );
});
