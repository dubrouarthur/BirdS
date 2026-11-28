// Mode Agent preference (agent-mode.js): a stored « on » from the old composer selector is migrated once to « auto »;
// « on » chosen in Settings lasts the session only. Run: node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import { loadAgentMode, saveAgentMode } from "../../birds/web/static/agent-mode.js";

function mem(init = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    m,
  };
}

test("the old selector's stored « on » becomes « auto », once", () => {
  const local = mem({ "bird.agent": "on" });
  assert.equal(loadAgentMode(local, mem()), "auto");
  assert.equal(local.getItem("bird.agent"), "auto");
  assert.equal(local.getItem("bird.agent.v"), "2");
});

test("« on » chosen in Settings forces the team for this session only", () => {
  const local = mem({ "bird.agent": "auto" });
  const session = mem();
  assert.equal(saveAgentMode("on", local, session), "on");
  assert.equal(loadAgentMode(local, session), "on"); // a reload in the same session
  assert.equal(loadAgentMode(local, mem()), "auto"); // a new session: Auto again
  assert.equal(local.getItem("bird.agent"), "auto");
});

test("« off » and « auto » are kept for the browser; bad values read as auto", () => {
  const local = mem();
  const session = mem({ "bird.agent.session": "on" });
  saveAgentMode("off", local, session);
  assert.equal(loadAgentMode(local, session), "off");
  assert.equal(saveAgentMode("nope", local, session), "auto");
  assert.equal(loadAgentMode(mem({ "bird.agent": "weird", "bird.agent.v": "2" }), mem()), "auto");
});

test("blocked storage: Auto", () => {
  const broken = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
    removeItem() {},
  };
  assert.equal(loadAgentMode(broken, broken), "auto");
  assert.equal(loadAgentMode(undefined, undefined), "auto");
});
