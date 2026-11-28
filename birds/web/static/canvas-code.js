// Code in the canvas, without the DOM: the files of a code document, the page the preview frame runs (local
// stylesheets and scripts inlined), where a console error comes from, the change between two versions, and the
// .zip of the files. Pure functions: tests/js/canvas-code.test.mjs runs them under Node.
//
// Same rules as birds/canvas/code.py (names, languages, the entry file, the per-file change).

export const DEFAULT_NAME = {
  html: "index.html",
  css: "style.css",
  js: "script.js",
  svg: "image.svg",
  python: "main.py",
  json: "data.json",
  markdown: "README.md",
  mermaid: "schema.mmd",
  text: "notes.txt",
  ts: "main.ts",
  sql: "query.sql",
  bash: "script.sh",
  yaml: "config.yaml",
};
const EXT_LANG = {
  html: "html",
  htm: "html",
  css: "css",
  js: "js",
  mjs: "js",
  svg: "svg",
  py: "python",
  json: "json",
  md: "markdown",
  mmd: "mermaid",
  txt: "text",
  ts: "ts",
  sql: "sql",
  sh: "bash",
  yml: "yaml",
  yaml: "yaml",
};
/** The highlighter's language (richcode.js) for a canvas language. */
export const HL = {
  html: "html",
  svg: "html",
  css: "css",
  js: "javascript",
  ts: "typescript",
  python: "python",
  json: "json",
  sql: "sql",
  bash: "bash",
  yaml: "yaml",
};
export const MIME = {
  html: "text/html",
  svg: "image/svg+xml",
  css: "text/css",
  js: "text/javascript",
  json: "application/json",
};
export const WEB = new Set(["html", "css", "js", "svg"]);

export const nameLang = (name) =>
  EXT_LANG[
    String(name || "")
      .split(".")
      .pop()
      .toLowerCase()
  ] || "text";

/** The files of a code document, whichever shape it has (one ``text`` from an older version, or ``files``). */
export function filesOf(doc) {
  const c = doc?.code || {};
  if (Array.isArray(c.files) && c.files.length)
    return c.files.map((f) => ({
      name: String(f.name),
      lang: f.lang || nameLang(f.name),
      text: String(f.text ?? ""),
    }));
  const lang = c.lang || "text";
  return [
    {
      name: DEFAULT_NAME[lang] || "notes.txt",
      lang,
      text: String(c.text ?? ""),
    },
  ];
}

export function entryIndex(files) {
  const tests = [
    (f) => f.name.toLowerCase() === "index.html",
    (f) => f.lang === "html",
    (f) => f.lang === "svg",
  ];
  for (const test of tests) {
    const i = files.findIndex(test);
    if (i >= 0) return i;
  }
  return 0;
}

/** Replace (or add) one file of the document, the entry's mirror kept (code.lang / code.text). */
export function setFile(doc, name, text) {
  const files = filesOf(doc);
  const f = files.find((x) => x.name === name);
  if (f) f.text = text;
  else files.push({ name, lang: nameLang(name), text });
  const e = files[entryIndex(files)];
  doc.code = { lang: e.lang, text: e.text, entry: e.name, files };
  return doc;
}

// ------------------------------------------------------------------ the page the preview runs

const base = (href) =>
  String(href || "")
    .trim()
    .replace(/^\.\//, "")
    .split(/[?#]/)[0]
    .toLowerCase();
const attr = (tag, name) => {
  const m = tag.match(
    new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i"),
  );
  return m ? (m[1] ?? m[2] ?? m[3]) : null;
};
const lineAt = (text, i) => text.slice(0, i).split("\n").length;
const scriptBody = (js, url) =>
  js.replace(/<\/script/gi, "<\\/script") + `\n//# sourceURL=${url}\n`;
const styleBody = (css) => css.replace(/<\/style/gi, "<\\/style");

/**
 * The single HTML document the sandboxed frame runs: the entry page with the local stylesheets and scripts it
 * links put inline (a script keeps its place, a ``defer`` one goes to the end of body: the same order a browser
 * runs them), and the local files it does not link added (styles in head, scripts at the end). Each script ends
 * with ``//# sourceURL=<file>`` so an error names its file and line. External URLs are left as written: the frame's
 * CSP blocks them, and the console says so. A local file the page links but nobody wrote is left out: while the
 * files stream (``partial``) silently, it may still come; otherwise with a console warning (``missing(name)``).
 * ``skip``: names not to use (a file still being written). Returns {html, used: [names], previewable}.
 */
export function bundle(doc, { skip = null, partial = false, missing = (n) => `fichier absent : ${n}` } = {}) {
  const files = filesOf(doc).filter((f) => !skip || !skip.has(f.name));
  const isLocal = (u) => !!u && !/^(?:[a-z][\w+.-]*:|\/\/|#)/i.test(u.trim());
  const absent = (u) =>
    partial ? "" : `<script>console.warn(${JSON.stringify(missing(base(u)))})</script>`;
  if (!files.length) return { html: "", used: [], previewable: false };
  const byName = new Map(files.map((f) => [f.name.toLowerCase(), f]));
  const entry = files[entryIndex(files)];
  const css = files.filter((f) => f.lang === "css");
  const js = files.filter((f) => f.lang === "js");
  const used = new Set();
  if (entry.lang !== "html") {
    if (entry.lang === "svg")
      return {
        html: `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;height:100%;display:grid;place-items:center;background:#fff}svg{max-width:100%;max-height:100vh}</style>${entry.text}`,
        used: [entry.name],
        previewable: true,
      };
    if (entry.lang === "css")
      return {
        html: `<!doctype html><meta charset="utf-8"><style>${styleBody(entry.text)}</style><body><h1>Titre</h1><p>Paragraphe <a href="#">lien</a></p><button>Bouton</button></body>`,
        used: [entry.name],
        previewable: true,
      };
    if (entry.lang === "js")
      return {
        html: `<!doctype html><meta charset="utf-8"><body><script>${scriptBody(entry.text, entry.name)}</script></body>`,
        used: [entry.name],
        previewable: true,
      };
    return { html: "", used: [], previewable: false };
  }
  used.add(entry.name);
  let html = entry.text;
  if (!/<html|<!doctype|<body/i.test(html))
    html = `<!doctype html><meta charset="utf-8"><body>${html}</body>`;
  const deferred = [];
  // inline scripts the page itself holds: their errors are located in the entry file
  html = html.replace(
    /(<script\b(?![^>]*\bsrc\s*=)[^>]*>)([\s\S]*?)(<\/script\s*>)/gi,
    (all, open, body, close, at) => {
      if (/\btype\s*=\s*["']?(?!module|text\/javascript|javascript)[\w/+-]+/i.test(open))
        return all; // a JSON or template block: not a script
      return `${open}${body}\n//# sourceURL=${entry.name}@${lineAt(entry.text, entry.text.indexOf(all) >= 0 ? entry.text.indexOf(all) : at)}\n${close}`;
    },
  );
  html = html.replace(/<link\b[^>]*>/gi, (tag) => {
    const href = attr(tag, "href");
    const f = href && byName.get(base(href));
    const rel = (attr(tag, "rel") || "").toLowerCase();
    if (rel && !rel.includes("stylesheet")) return tag;
    if (!f && isLocal(href) && /\.css$/i.test(base(href))) return absent(href);
    if (!f || f.lang !== "css") return tag;
    used.add(f.name);
    return `<style data-file="${f.name}">${styleBody(f.text)}</style>`;
  });
  html = html.replace(
    /<script\b([^>]*?)\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))([^>]*)>\s*<\/script\s*>/gi,
    (tag, a1, s1, s2, s3, a2) => {
      const src = s1 ?? s2 ?? s3;
      const f = byName.get(base(src));
      if (!f && isLocal(src) && /\.m?js$/i.test(base(src))) return absent(src);
      if (!f || f.lang !== "js") return tag;
      used.add(f.name);
      const attrs = `${a1} ${a2}`
        .replace(/\b(?:defer|async)\b(?:\s*=\s*["']?[^"'\s>]*["']?)?/gi, "")
        .replace(/\s+/g, " ")
        .trimEnd();
      const out = `<script${attrs}>${scriptBody(f.text, f.name)}</script>`;
      if (/\bdefer\b/i.test(a1 + a2) && !/\btype\s*=\s*["']?module/i.test(a1 + a2)) {
        deferred.push(out);
        return "";
      }
      return out;
    },
  );
  const extraCss = css
    .filter((f) => !used.has(f.name))
    .map((f) => {
      used.add(f.name);
      return `<style data-file="${f.name}">${styleBody(f.text)}</style>`;
    })
    .join("");
  if (extraCss)
    html = /<\/head\s*>/i.test(html)
      ? html.replace(/<\/head\s*>/i, (m) => extraCss + m)
      : extraCss + html;
  const tail =
    deferred.join("") +
    js
      .filter((f) => !used.has(f.name))
      .map((f) => {
        used.add(f.name);
        return `<script>${scriptBody(f.text, f.name)}</script>`;
      })
      .join("");
  if (tail) {
    const i = html.search(/<\/body\s*>(?![\s\S]*<\/body\s*>)/i);
    html = i >= 0 ? html.slice(0, i) + tail + html.slice(i) : html + tail;
  }
  return { html, used: [...used], previewable: true };
}

/**
 * Where a console message of the frame comes from: the frame sends « message (fichier, l. N) » with the script's
 * sourceURL; an inline script of the page (« index.html@12 ») is turned into its line in that file.
 * Returns {text, file, line}.
 */
export function whereIs(text) {
  const s = String(text || "");
  const m = s.match(/\s*\(([\w.@-]*), l\. (\d+)\)\s*$/);
  if (!m) return { text: s, file: null, line: null };
  let [file, line] = [m[1], Number(m[2])];
  const at = file.match(/^(.+)@(\d+)$/);
  if (at) {
    file = at[1];
    line = Number(at[2]) + line - 1;
  }
  return { text: s.slice(0, m.index), file: file || null, line };
}

// ------------------------------------------------------------------ the change between two versions

function counts(text) {
  const m = new Map();
  for (const l of String(text || "").split(/\r?\n/))
    m.set(l, (m.get(l) || 0) + 1);
  if (text === "" || text == null) m.clear();
  return m;
}

/** Per file {name, status: added|changed|removed, plus, minus}; lines counted as multisets (as code.py). */
export function diffFiles(oldDoc, newDoc) {
  const a = new Map(filesOf(oldDoc).map((f) => [f.name, f.text]));
  const b = new Map(filesOf(newDoc).map((f) => [f.name, f.text]));
  const out = [];
  for (const name of [...b.keys(), ...[...a.keys()].filter((n) => !b.has(n))]) {
    const x = counts(a.get(name) ?? "");
    const y = counts(b.get(name) ?? "");
    let plus = 0;
    let minus = 0;
    for (const [l, n] of y) plus += Math.max(0, n - (x.get(l) || 0));
    for (const [l, n] of x) minus += Math.max(0, n - (y.get(l) || 0));
    const status = !a.has(name) ? "added" : !b.has(name) ? "removed" : "changed";
    if (status !== "changed" || plus || minus)
      out.push({ name, status, plus, minus });
  }
  return out;
}

// ------------------------------------------------------------------ .zip (stored, no compression: small files)

const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++)
    c = CRC[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** A .zip of the files ({name, text}), names in UTF-8, stored. Returns a Uint8Array. */
export function zip(files, when = new Date()) {
  const enc = new TextEncoder();
  const time =
    (when.getHours() << 11) | (when.getMinutes() << 5) | (when.getSeconds() >> 1);
  const date =
    ((Math.max(1980, when.getFullYear()) - 1980) << 9) |
    ((when.getMonth() + 1) << 5) |
    when.getDate();
  const parts = [];
  const central = [];
  let offset = 0;
  for (const f of files) {
    const name = enc.encode(f.name);
    const data = enc.encode(f.text);
    const crc = crc32(data);
    const head = new DataView(new ArrayBuffer(30));
    head.setUint32(0, 0x04034b50, true);
    head.setUint16(4, 20, true);
    head.setUint16(6, 0x0800, true); // UTF-8 names
    head.setUint16(8, 0, true); // stored
    head.setUint16(10, time, true);
    head.setUint16(12, date, true);
    head.setUint32(14, crc, true);
    head.setUint32(18, data.length, true);
    head.setUint32(22, data.length, true);
    head.setUint16(26, name.length, true);
    head.setUint16(28, 0, true);
    parts.push(new Uint8Array(head.buffer), name, data);
    const cd = new DataView(new ArrayBuffer(46));
    cd.setUint32(0, 0x02014b50, true);
    cd.setUint16(4, 20, true);
    cd.setUint16(6, 20, true);
    cd.setUint16(8, 0x0800, true);
    cd.setUint16(10, 0, true);
    cd.setUint16(12, time, true);
    cd.setUint16(14, date, true);
    cd.setUint32(16, crc, true);
    cd.setUint32(20, data.length, true);
    cd.setUint32(24, data.length, true);
    cd.setUint16(28, name.length, true);
    cd.setUint32(42, offset, true);
    central.push(new Uint8Array(cd.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const cdSize = central.reduce((n, p) => n + p.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, cdSize, true);
  end.setUint32(16, offset, true);
  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((n, p) => n + p.length, 0));
  let i = 0;
  for (const p of all) {
    out.set(p, i);
    i += p.length;
  }
  return out;
}
