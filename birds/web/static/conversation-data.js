// Conversation engine, pure part (no DOM): versions of a turn (regenerate, edit), search in the messages, the title
// the model proposes, the documents in context. Tested in tests/js/conversation.test.mjs.

// ------------------------------------------------------------------ versions (« ‹ 1/2 › »)
//
// The conversation shown is the list `turns`. A turn that was regenerated (an answer) or edited (a question) heads a
// version group `turn.alts = {list, at}`: `list[k]` is the whole tail of the conversation from that turn on, as it
// was in version k; the version on screen is `list[at]`, kept as null (it lives in `turns`). Older tails keep their own
// groups deeper down, so every branch can be shown again as it was.

export const MAX_VERSIONS = 12;

/** {n, at} for the group headed by turns[i] (1-based `at`), or null when the turn has a single version. */
export function versionInfo(turns, i) {
  const g = turns?.[i]?.alts;
  if (!g || !Array.isArray(g.list) || g.list.length < 2) return null;
  return { n: g.list.length, at: g.at + 1 };
}

/** Replace the tail from `i` with `head` (new turns), keeping the old tail as a version. Returns the group. */
export function fork(turns, i, head) {
  const old = turns.splice(i);
  const g = old[0]?.alts && Array.isArray(old[0].alts.list) ? old[0].alts : { list: [null], at: 0 };
  if (old[0]) delete old[0].alts;
  g.list[g.at] = old;
  g.list.push(null);
  g.at = g.list.length - 1;
  while (g.list.length > MAX_VERSIONS) {
    g.list.splice(1, 1); // the first version is kept, as for the canvas
    g.at = g.list.length - 1;
  }
  head[0].alts = g;
  turns.push(...head);
  return g;
}

/** Show version `j` (0-based) of the group headed by turns[i]. Returns false when there is nothing to switch. */
export function switchVersion(turns, i, j) {
  const g = turns?.[i]?.alts;
  if (!g || !Array.isArray(g.list) || j === g.at || j < 0 || j >= g.list.length || !Array.isArray(g.list[j]))
    return false;
  const live = turns.splice(i);
  delete live[0].alts;
  g.list[g.at] = live;
  const next = g.list[j];
  g.list[j] = null;
  g.at = j;
  next[0].alts = g;
  turns.push(...next);
  return true;
}

/** Apply `fn` to every turn of the conversation, the hidden versions included (to slim or load them). */
export function mapTree(turns, fn) {
  return (turns || []).map((turn) => {
    const out = fn(turn);
    const g = turn?.alts;
    if (out && g && Array.isArray(g.list))
      out.alts = {
        at: Math.min(Math.max(0, g.at | 0), g.list.length - 1),
        list: g.list.map((tail) => (Array.isArray(tail) ? mapTree(tail, fn) : null)),
      };
    return out;
  });
}

/** Whether a group stored in the browser is usable (one live slot, tails headed by a turn of the same role). */
export function validGroup(g, role) {
  if (!g || !Array.isArray(g.list) || g.list.length < 2) return false;
  if (!Number.isInteger(g.at) || g.at < 0 || g.at >= g.list.length || g.list[g.at] !== null) return false;
  return g.list.every((tail, k) => k === g.at || (Array.isArray(tail) && tail.length && tail[0]?.role === role));
}

// ------------------------------------------------------------------ search in the messages

const fold = (ch) => ch.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Lowercase, without accents, with a map back to the original positions. */
function folded(text) {
  let out = "";
  const at = [];
  let i = 0;
  for (const ch of String(text || "")) {
    const f = fold(ch);
    for (let k = 0; k < f.length; k++) at.push(i);
    out += f;
    i += ch.length;
  }
  at.push(i);
  return { out, at };
}

/** The text a conversation is searched in: its questions and answers (the version on screen). */
export function convText(conv) {
  const parts = [];
  for (const turn of conv?.turns || []) {
    if (turn.hidden) continue;
    if (turn.role === "user") parts.push(String(turn.content || ""));
    else if (turn.answer?.content) parts.push(String(turn.answer.content));
  }
  return parts.join("\n");
}

/** Where `query` appears in `text` (accents and case ignored): {start, end, before, match, after} or null. */
export function findIn(text, query, room = 28) {
  const q = folded(String(query || "").trim()).out;
  if (!q) return null;
  const src = String(text || "");
  const f = folded(src);
  const k = f.out.indexOf(q);
  if (k < 0) return null;
  const start = f.at[k];
  const end = f.at[k + q.length];
  const flat = (s) => s.replace(/\s+/g, " ");
  let from = Math.max(0, start - room);
  let to = Math.min(src.length, end + room * 2);
  const sp = src.slice(from, start).search(/\s/); // start on a whole word
  if (from > 0 && sp >= 0 && from + sp + 1 < start) from += sp + 1;
  const sp2 = src.indexOf(" ", end + room);
  if (to < src.length && sp2 > 0 && sp2 < to) to = sp2;
  return {
    start,
    end,
    before: (from > 0 ? "…" : "") + flat(src.slice(from, start)).trimStart(),
    match: flat(src.slice(start, end)),
    after: flat(src.slice(end, to)).trimEnd() + (to < src.length ? "…" : ""),
  };
}

// ------------------------------------------------------------------ the title Bird proposes

/** A title the model proposed, cleaned and checked; `fallback` (the start of the question) when it is not usable. */
export function cleanTitle(raw, fallback = "") {
  let s = String(raw ?? "").split(/\r?\n/).find((l) => l.trim()) || "";
  s = s
    .replace(/^\s*(?:titre|title)\s*:\s*/i, "")
    .replace(/[*_`#>]+/g, "")
    .replace(/^[\s"'«“‘(\[]+|[\s"'»”’)\].,;:!]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const words = s.split(" ").filter(Boolean).length;
  if (s.length < 3 || s.length > 60 || words > 9 || /https?:|<|>|\{|\}/.test(s)) return fallback;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ------------------------------------------------------------------ documents in context

/** The conversation's documents split as the composer shows them: to send with the next message, already in context
 * (sent with an earlier message), and lost (to attach again: a reload without their content). */
export function contextDocs(attachments) {
  const list = Array.isArray(attachments) ? attachments : [];
  return {
    pending: list.filter((a) => !a.sent && !a.lost),
    context: list.filter((a) => a.sent && !a.lost),
    lost: list.filter((a) => a.lost),
  };
}
