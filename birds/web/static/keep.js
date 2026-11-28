// Attachments kept across a reload, in this browser only (IndexedDB): the PDFs and office files a conversation
// carries (too large for localStorage) and the thumbnails of the images it sent. Nothing leaves the browser.
// Bounded: KEEP_BYTES in all (the oldest go first) and KEEP_DAYS since last use. Every call is optional: private
// mode, a blocked or full storage just means the file has to be attached again (the composer says so).

export const KEEP_BYTES = 40_000_000;
export const KEEP_DAYS = 30;
const DB = "bird-files";
const STORE = "files";

let opening = null;
function db() {
  if (opening) return opening;
  opening = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        const s = req.result.createObjectStore(STORE, { keyPath: "key" });
        s.createIndex("conv", "conv");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return opening;
}

function run(mode, fn) {
  return db().then(
    (d) =>
      d &&
      new Promise((resolve) => {
        try {
          const tx = d.transaction(STORE, mode);
          const out = fn(tx.objectStore(STORE));
          tx.oncomplete = () => resolve(out?.result ?? out ?? true);
          tx.onerror = tx.onabort = () => resolve(null);
        } catch {
          resolve(null);
        }
      }),
  );
}

/** The blob behind a thumbnail's object URL (made here or restored), so it can be kept. */
export const blobs = new Map();

const sizeOf = (v) => (typeof v === "string" ? v.length : v?.size || 0);

/** Keep one file of conversation `conv`: {name, content, encoding, size}, or an image thumbnail {name, blob}. */
export async function keep(conv, kind, name, value) {
  const rec = { key: `${conv}/${kind}/${name}`, conv, kind, name, value, bytes: sizeOf(value.content ?? value.blob), at: Date.now() };
  if (rec.bytes > KEEP_BYTES / 4) return false; // one file never takes the room of the others
  const ok = await run("readwrite", (s) => s.put(rec));
  if (ok) prune();
  return !!ok;
}

/** Every record of a conversation, by kind/name (their last use is refreshed). */
export async function load(conv) {
  const rows = await run("readonly", (s) => s.index("conv").getAll(conv));
  if (!Array.isArray(rows)) return new Map();
  const now = Date.now();
  run("readwrite", (s) => rows.forEach((r) => s.put({ ...r, at: now })));
  return new Map(rows.map((r) => [`${r.kind}/${r.name}`, r.value]));
}

export function drop(conv) {
  return run("readwrite", (s) => {
    const req = s.index("conv").getAllKeys(conv);
    req.onsuccess = () => req.result.forEach((k) => s.delete(k));
  });
}

export function dropAll() {
  return run("readwrite", (s) => s.clear());
}

/** Older than KEEP_DAYS, then the oldest until the total fits KEEP_BYTES. */
export async function prune(now = Date.now()) {
  const rows = await run("readonly", (s) => s.getAll());
  if (!Array.isArray(rows)) return;
  const gone = planPrune(rows, now);
  if (gone.length) await run("readwrite", (s) => gone.forEach((k) => s.delete(k)));
}

/** Pure: the keys to delete. */
export function planPrune(rows, now = Date.now(), limit = KEEP_BYTES, days = KEEP_DAYS) {
  const old = now - days * 86_400_000;
  const gone = rows.filter((r) => r.at < old).map((r) => r.key);
  const left = rows.filter((r) => r.at >= old).sort((a, b) => a.at - b.at);
  let total = left.reduce((n, r) => n + (r.bytes || 0), 0);
  for (const r of left) {
    if (total <= limit) break;
    gone.push(r.key);
    total -= r.bytes || 0;
  }
  return gone;
}
