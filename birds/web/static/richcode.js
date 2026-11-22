// Code blocks: language table, a small in-house highlighter, and the delegated behaviour of the block buttons.
// Safety: the scanner reads raw text and escapes every token itself; the only tags it writes are
// <span class="tk-…"> and <span class="ln">. No dependency, linear time, nothing runs while a block is streaming.

const ESC = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
const RE_ESC = /[&<>"']/;
const esc = (s) => (RE_ESC.test(s) ? s.replace(/[&<>"']/g, (c) => ESC[c]) : s);

// ------------------------------------------------------------------ languages

const LANGS = {
  python: ["Python", "py"],
  javascript: ["JavaScript", "js"],
  typescript: ["TypeScript", "ts"],
  sql: ["SQL", "sql"],
  json: ["JSON", "json"],
  bash: ["Bash", "sh"],
  html: ["HTML", "html"],
  css: ["CSS", "css"],
  excel: ["Excel", "txt"],
  csv: ["CSV", "csv"],
  yaml: ["YAML", "yml"],
  text: ["", "txt"],
};
const ALIAS = {
  py: "python",
  python3: "python",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  node: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  postgres: "sql",
  postgresql: "sql",
  mysql: "sql",
  sqlite: "sql",
  tsql: "sql",
  plsql: "sql",
  jsonc: "json",
  json5: "json",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  terminal: "bash",
  xml: "html",
  svg: "html",
  scss: "css",
  xlsx: "excel",
  formula: "excel",
  formule: "excel",
  yml: "yaml",
  txt: "text",
  plain: "text",
  plaintext: "text",
};
const MIME = { json: "application/json", csv: "text/csv" };

/** {key, label, ext, mime}: key is null for a language we do not know (shown by its own name, not highlighted). */
export function langInfo(name) {
  const raw = String(name || "").toLowerCase();
  const key = LANGS[raw] ? raw : ALIAS[raw] || null;
  if (!key)
    return {
      key: null,
      label: String(name || ""),
      ext: "txt",
      mime: "text/plain",
    };
  return {
    key,
    label: LANGS[key][0],
    ext: LANGS[key][1],
    mime: MIME[key] || "text/plain",
  };
}

/** A cheap, deterministic guess for an unlabelled fence. */
export function sniff(code) {
  const first = code.split("\n", 1)[0];
  if (/^#!.*\b(ba|z)?sh\b/.test(first) || /^\$ /.test(first)) return "bash";
  if (/^\s*(SELECT|WITH|INSERT|UPDATE|CREATE|DELETE)\b/i.test(code))
    return "sql";
  if (/^\s*[{[]/.test(code)) {
    try {
      JSON.parse(code);
      return "json";
    } catch {
      /* not JSON */
    }
  }
  if (/^\s*(def|class|import|from)\b/.test(first) || /:\s*$/.test(first))
    return "python";
  if (/^=\s*[A-Z][A-Z.]+\(/.test(first)) return "excel";
  if (/^\s*</.test(code)) return "html";
  return "text";
}

// ------------------------------------------------------------------ scanner

const words = (s) => new Set(s.split(" "));
const KW = {
  python: words(
    "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case",
  ),
  py_bi: words(
    "print len range open dict list set int float str sum min max enumerate zip sorted reversed isinstance type round abs any all map filter tuple bool super object input format repr iter next hasattr getattr setattr self cls",
  ),
  js: words(
    "const let var function return if else for while do switch case break continue new this class extends import from export default async await try catch finally throw typeof instanceof in of null undefined true false yield delete void static get set super",
  ),
  ts: words(
    "interface type enum implements readonly as declare namespace public private protected abstract keyof",
  ),
  js_bi: words(
    "console Math JSON Object Array Promise Number String Boolean Date Map Set document window fetch Error RegExp",
  ),
  sql: words(
    "select from where and or not in is null as join inner left right full outer cross on group by order having limit offset union all distinct insert into values update set delete create table view index drop alter add column primary key foreign references default case when then else end with exists between like ilike asc desc true false interval returning over partition window cast if begin commit rollback transaction grant revoke unique check constraint database schema replace temporary temp materialized recursive lateral natural using fetch first next rows only top",
  ),
  bash: words(
    "if then else elif fi for while until do done case esac function in return local export readonly set select time continue break",
  ),
  sh_bi: words(
    "echo printf cd mkdir rm cp mv ls cat tar find jq grep sed awk curl wget chmod chown sudo exit source read test date basename dirname command xargs sort uniq head tail tee touch ln ps kill git docker python python3 pip npm node make ssh scp rsync sleep true false eval exec trap shift unset declare",
  ),
};

/** Run `step(s, i, st)` -> [type, length] until the end; returns [[type, text], …] (adjacent same types merged). */
function lex(code, step) {
  const toks = [];
  const st = { prev: "", cmd: true, tag: false, depth: 0 };
  let i = 0;
  while (i < code.length) {
    let [type, len] = step(code, i, st);
    if (!len) len = 1;
    const text = code.slice(i, i + len);
    const last = toks[toks.length - 1];
    if (last && last[0] === type) last[1] += text;
    else toks.push([type, text]);
    if (type && type !== "com") st.prev = text; // whitespace is always untyped
    i += len;
  }
  return toks;
}

const at = (re, s, i) => {
  re.lastIndex = i; // sticky regexes: test() allocates no match array (the scanner calls this per character)
  return re.test(s) ? re.lastIndex - i : 0;
};
const RX = {
  ws: /[ \t]+|\n/y,
  word: /[A-Za-z_][\w]*/y,
  num: /(?:0[xXoObB][\da-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?|\.\d+)[jJnL]?/y,
  op: /[-+*/%=<>!&|^~?:]+/y,
  dq: /"(?:\\.|[^"\\\n])*"?/y,
  sq: /'(?:\\.|[^'\\\n])*'?/y,
  bt: /`(?:\\[\s\S]|[^`\\])*`?/y,
  py_str:
    /[rRbBuUfF]{0,2}(?:"""[\s\S]*?(?:"""|$(?![\s\S]))|'''[\s\S]*?(?:'''|$(?![\s\S]))|"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?)/y,
  hash_com: /#[^\n]*/y,
  sl_com: /\/\/[^\n]*/y,
  ml_com: /\/\*[\s\S]*?(?:\*\/|$(?![\s\S]))/y,
  sql_com: /--[^\n]*/y,
  call: /\s*\(/y,
};

function common(s, i) {
  let n;
  if ((n = at(RX.ws, s, i))) return ["", n];
  if ((n = at(RX.num, s, i)) && !/\w/.test(s[i - 1] || "")) return ["num", n];
  return null;
}

const STEP = {
  python(s, i, st) {
    let n;
    if ((n = at(RX.hash_com, s, i))) return ["com", n];
    if ((n = at(RX.py_str, s, i))) return ["str", n];
    const c = common(s, i);
    if (c) return c;
    if (
      s[i] === "@" &&
      (n = at(/@[\w.]+/y, s, i)) &&
      /^\s*$|\n\s*$/.test(s.slice(Math.max(0, i - 40), i))
    )
      return ["fn", n];
    if ((n = at(RX.word, s, i))) {
      const w = s.slice(i, i + n);
      if (st.prev === "def" || st.prev === "class") return ["fn", n];
      if (KW.python.has(w)) return ["kw", n];
      if (KW.py_bi.has(w)) return ["bi", n];
      return [at(RX.call, s, i + n) ? "fn" : "", n];
    }
    if ((n = at(RX.op, s, i))) return ["op", n];
    return ["", 1];
  },
  javascript(s, i, st, ts = false) {
    let n;
    if ((n = at(RX.sl_com, s, i)) || (n = at(RX.ml_com, s, i)))
      return ["com", n];
    if ((n = at(RX.dq, s, i)) || (n = at(RX.sq, s, i)) || (n = at(RX.bt, s, i)))
      return ["str", n];
    const c = common(s, i);
    if (c) return c;
    if ((n = at(/[A-Za-z_$][\w$]*/y, s, i))) {
      const w = s.slice(i, i + n);
      if (st.prev === "function" || st.prev === "class") return ["fn", n];
      if (KW.js.has(w) || (ts && KW.ts.has(w))) return ["kw", n];
      if (KW.js_bi.has(w)) return ["bi", n];
      return [at(RX.call, s, i + n) ? "fn" : "", n];
    }
    if ((n = at(RX.op, s, i))) return ["op", n];
    return ["", 1];
  },
  typescript(s, i, st) {
    return STEP.javascript(s, i, st, true);
  },
  sql(s, i) {
    let n;
    if ((n = at(RX.sql_com, s, i)) || (n = at(RX.ml_com, s, i)))
      return ["com", n];
    if ((n = at(/'(?:''|[^'])*'?/y, s, i))) return ["str", n];
    if ((n = at(RX.dq, s, i)) || (n = at(/`[^`\n]*`?/y, s, i)))
      return ["prop", n];
    if (
      (s[i] === "@" ||
        (s[i] === ":" && s[i - 1] !== ":" && s[i + 1] !== ":")) &&
      (n = at(/[@:][A-Za-z_]\w*/y, s, i))
    )
      return ["var", n];
    const c = common(s, i);
    if (c) return c;
    if ((n = at(RX.word, s, i))) {
      const w = s.slice(i, i + n).toLowerCase();
      if (at(RX.call, s, i + n) && !KW.sql.has(w)) return ["fn", n];
      if (
        at(RX.call, s, i + n) &&
        /^(count|sum|avg|min|max|coalesce|cast|extract|replace|left|right)$/.test(
          w,
        )
      )
        return ["fn", n];
      return [KW.sql.has(w) ? "kw" : "", n];
    }
    if ((n = at(/[-+*/%=<>!|]+/y, s, i))) return ["op", n];
    return ["", 1];
  },
  json(s, i) {
    let n;
    if ((n = at(RX.sl_com, s, i)) || (n = at(RX.ml_com, s, i)))
      return ["com", n];
    if ((n = at(RX.dq, s, i)))
      return [at(/\s*:/y, s, i + n) ? "prop" : "str", n];
    if ((n = at(/-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/y, s, i))) return ["num", n];
    if ((n = at(/\b(?:true|false|null)\b/y, s, i))) return ["kw", n];
    return ["", at(/[ \t\n]+/y, s, i) || 1];
  },
  bash(s, i, st) {
    let n;
    const before = s[i - 1] || "\n";
    if (s[i] === "\n") {
      st.cmd = true;
      return ["", 1];
    }
    if ((n = at(/[ \t]+/y, s, i))) return ["", n];
    if (s[i] === "#" && /\s/.test(before))
      return ["com", at(RX.hash_com, s, i)];
    if ((n = at(/<<-?\s*(['"]?)(\w+)\1[^\n]*\n/y, s, i))) {
      const tag = /<<-?\s*['"]?(\w+)/.exec(s.slice(i, i + n))[1];
      const end = new RegExp(`^\\s*${tag}\\s*$`, "m");
      const rest = s.slice(i + n);
      const m = end.exec(rest);
      return ["str", n + (m ? m.index + m[0].length : rest.length)];
    }
    if ((n = at(/'[^']*'?/y, s, i))) return ["str", n];
    if (s[i] === '"') return ["dq", at(/"(?:\\[\s\S]|[^"\\])*"?/y, s, i)]; // split below so $vars inside show
    if ((n = at(/\$(?:\{[^}\n]*\}?|\(\(?|[A-Za-z_]\w*|[0-9@#?$!*-])/y, s, i))) {
      if (s[i + 1] === "(") st.cmd = true;
      return ["var", n];
    }
    if ((n = at(/[;&|()]+|`/y, s, i))) {
      st.cmd = true;
      return ["op", n];
    }
    if (st.cmd && (n = at(/[A-Za-z_]\w*(?==)/y, s, i))) return ["var", n];
    if ((n = at(/--?[A-Za-z][\w-]*/y, s, i)) && /\s/.test(before)) {
      st.cmd = false;
      return ["attr", n];
    }
    if ((n = at(/[\w./~+-]+/y, s, i))) {
      const w = s.slice(i, i + n);
      const wasCmd = st.cmd;
      st.cmd = KW.bash.has(w);
      if (
        KW.bash.has(w) &&
        (wasCmd || /^(then|do|in|else|fi|done|esac)$/.test(w))
      )
        return ["kw", n];
      if (wasCmd && KW.sh_bi.has(w)) return ["bi", n];
      if (wasCmd && /^\.?\.?\//.test(w)) return ["fn", n];
      return [/^\d+$/.test(w) ? "num" : "", n];
    }
    if ((n = at(/[<>=!]+/y, s, i))) return ["op", n];
    return ["", 1];
  },
  html(s, i, st) {
    let n;
    if (!st.tag) {
      if ((n = at(/<!--[\s\S]*?(?:-->|$(?![\s\S]))/y, s, i))) return ["com", n];
      if ((n = at(/<\/?[A-Za-z!][\w:-]*/y, s, i))) {
        st.tag = true;
        return ["tag", n];
      }
      if ((n = at(/&#?\w+;/y, s, i))) return ["num", n];
      return ["", at(/[^<&]+/y, s, i) || 1];
    }
    if ((n = at(/\/?>/y, s, i))) {
      st.tag = false;
      return ["tag", n];
    }
    if ((n = at(/\s+/y, s, i))) return ["", n];
    if ((n = at(/"[^"]*"?|'[^']*'?/y, s, i))) return ["str", n];
    if ((n = at(/[^\s=>/"']+/y, s, i))) return ["attr", n];
    return ["op", 1];
  },
  css(s, i, st) {
    let n;
    if ((n = at(RX.ml_com, s, i))) return ["com", n];
    if ((n = at(RX.dq, s, i)) || (n = at(RX.sq, s, i))) return ["str", n];
    if ((n = at(/@[\w-]+/y, s, i))) return ["kw", n];
    if (s[i] === "{") st.depth++;
    if (s[i] === "}") st.depth = Math.max(0, st.depth - 1);
    if (/[{};]/.test(s[i])) return ["", 1];
    if (!st.depth) return ["tag", at(/[^{}/;"'@]+/y, s, i) || 1];
    if (
      (n = at(/--?[A-Za-z][\w-]*(?=\s*:)|[A-Za-z][\w-]*(?=\s*:)/y, s, i)) &&
      !/[\w-]/.test(s[i - 1] || "")
    )
      return ["prop", n];
    if (
      (n = at(
        /#[\da-fA-F]{3,8}\b|-?\d*\.?\d+(?:px|r?em|%|vh|vw|vmin|vmax|s|ms|deg|fr|ch|ex|dvh|svh)?/y,
        s,
        i,
      ))
    )
      return ["num", n];
    if ((n = at(/[A-Za-z-][\w-]*(?=\()/y, s, i))) return ["fn", n];
    if ((n = at(/!important\b/y, s, i))) return ["kw", n];
    return ["", at(/[A-Za-z-][\w-]*|\s+/y, s, i) || 1];
  },
  excel(s, i) {
    let n;
    if ((n = at(/"(?:""|[^"])*"?/y, s, i))) return ["str", n];
    if (
      (n = at(
        /(?:'[^'\n]+'|[A-Za-z_][\w.]*)!\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?/y,
        s,
        i,
      ))
    )
      return ["ref", n];
    if ((n = at(/[A-Za-z][A-Za-z0-9._]*(?=\()/y, s, i))) return ["fn", n];
    if (
      (n = at(/\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![\w(])/y, s, i))
    )
      return ["ref", n];
    if ((n = at(/\d+(?:[.,]\d+)?%?/y, s, i))) return ["num", n];
    if ((n = at(/(?:TRUE|FALSE|VRAI|FAUX)\b/y, s, i))) return ["kw", n];
    if ((n = at(/[=+\-*/^&<>;,:%]+/y, s, i))) return ["op", n];
    return ["", 1];
  },
  yaml(s, i) {
    let n;
    const lineStart = i === 0 || s[i - 1] === "\n";
    if (s[i] === "#" && (lineStart || /\s/.test(s[i - 1])))
      return ["com", at(RX.hash_com, s, i)];
    if (lineStart && (n = at(/[ \t]*(?:- )?[\w.-]+(?=\s*:(?:\s|$))/y, s, i)))
      return ["prop", n];
    if ((n = at(RX.dq, s, i)) || (n = at(RX.sq, s, i))) return ["str", n];
    if ((n = at(/\b(?:true|false|null|yes|no|on|off)\b/y, s, i)))
      return ["kw", n];
    const c = common(s, i);
    return c || ["", at(/[A-Za-z_][\w]*/y, s, i) || 1];
  },
};

/** A bash double-quoted string with its $vars highlighted. */
function splitDq(text) {
  const out = [];
  const re = /\$(?:\{[^}]*\}|\([^)]*\)|[A-Za-z_]\w*|[0-9@#?$!*-])/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(["str", text.slice(last, m.index)]);
    out.push(["var", m[0]]);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(["str", text.slice(last)]);
  return out;
}

export const MAX_LINES = 2000;
export const MAX_BYTES = 120_000;

/** One HTML string per source line, each self-contained (a token across lines is reopened on the next one). */
export function highlight(code, key) {
  const step = STEP[key];
  let toks;
  if (!step || code.length > MAX_BYTES || code.split("\n").length > MAX_LINES)
    toks = [["", code]];
  else
    toks = lex(code, step).flatMap((t) =>
      t[0] === "dq" ? splitDq(t[1]) : [t],
    );
  const lines = [];
  let cur = "";
  const add = (type, part) => {
    if (part)
      cur += type ? `<span class="tk-${type}">${esc(part)}</span>` : esc(part);
  };
  for (const [type, text] of toks) {
    if (!text.includes("\n")) {
      add(type, text);
      continue;
    }
    const parts = text.split("\n");
    for (let k = 0; k < parts.length; k++) {
      if (k) {
        lines.push(cur);
        cur = "";
      }
      add(type, parts[k]);
    }
  }
  lines.push(cur);
  return lines;
}

// ------------------------------------------------------------------ icons (literal SVG, same 20-unit grid as core.js)

const svg = (d) =>
  `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${d}</svg>`;
export const ICON = {
  copy: svg(
    '<rect x="7" y="7" width="9.5" height="9.5" rx="1.5"/><path d="M13 7V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v6.5A1.5 1.5 0 0 0 5 13h2"/>',
  ),
  download: svg('<path d="M10 3.5v9M6 9l4 4 4-4M4 16.5h12"/>'),
  wrap: svg(
    '<path d="M3.5 5h13M3.5 10h10.5a2.5 2.5 0 0 1 0 5H10M11.5 13l-2 2 2 2M3.5 15h3"/>',
  ),
  check: svg('<path d="M4.5 10.5l3.5 3.5 7.5-8"/>'),
  alert: svg(
    '<path d="M10 3.5l7 12.5H3z"/><path d="M10 8.5v3.5M10 14.2h.01"/>',
  ),
  info: svg(
    '<circle cx="10" cy="10" r="6.5"/><path d="M10 9.2v4M10 6.6h.01"/>',
  ),
  bulb: svg(
    '<path d="M7.5 14.5h5M8 17h4M10 3a5 5 0 0 0-3 9c.6.5 1 1.2 1 2h4c0-.8.4-1.5 1-2a5 5 0 0 0-3-9z"/>',
  ),
  star: svg(
    '<path d="M10 3l2.1 4.4 4.9.6-3.6 3.3.9 4.8L10 13.8 5.7 16.1l.9-4.8L3 8l4.9-.6z"/>',
  ),
  chevron: svg('<path d="M6 8l4 4 4-4"/>'),
  file: svg('<path d="M5.5 3h6l3.5 3.5V17h-9.5z"/><path d="M11.5 3v3.5H15"/>'),
};

// ------------------------------------------------------------------ behaviour (event delegation, registered once)

const WRAP_KEY = "bird.code.wrap";

/** The viewer's line-wrap preference (remembered per browser), off until they ask for it. */
export function wrapPref() {
  try {
    const v = globalThis.localStorage?.getItem(WRAP_KEY);
    if (v === "1" || v === "0") return v === "1";
  } catch {
    /* storage blocked: fall back to the screen width */
  }
  return false; // off by default: wrapping breaks the visual indentation of code (scroll shadows show the overflow)
}

function setWrap(root, on) {
  try {
    globalThis.localStorage?.setItem(WRAP_KEY, on ? "1" : "0");
  } catch {
    /* not remembered, still applied */
  }
  for (const fig of root.querySelectorAll(".code-block"))
    fig.classList.toggle("is-wrapped", on);
  for (const b of root.querySelectorAll("[data-code-wrap]"))
    b.setAttribute("aria-pressed", String(on));
}

/**
 * Wire the code-block and fold buttons under `root` (once). `io.copy(text, toast)` and `io.download(name, mime, text)`
 * come from the app, so the clipboard fallback and the Blob download stay in one place.
 */
export function wire(root, io) {
  root.addEventListener("click", (e) => {
    const el = e.target.closest?.(
      "[data-code-wrap],[data-code-download],[data-code-more],[data-copy-inline],[data-md-more]",
    );
    if (!el || !root.contains(el)) return;
    const fig = el.closest(".code-block");
    if (el.hasAttribute("data-code-wrap"))
      setWrap(
        root.ownerDocument || root,
        el.getAttribute("aria-pressed") !== "true",
      );
    else if (el.hasAttribute("data-code-download") && fig) {
      const code = fig.querySelector("pre code")?.textContent ?? "";
      io.download(
        el.dataset.file || "code.txt",
        el.dataset.mime || "text/plain",
        code.endsWith("\n") ? code : `${code}\n`,
      );
    } else if (el.hasAttribute("data-code-more") && fig) {
      const open = fig.hasAttribute("data-collapsed");
      fig.toggleAttribute("data-collapsed", !open);
      el.setAttribute("aria-expanded", String(open));
      el.querySelector(".code-more-t").textContent = open
        ? el.dataset.less
        : el.dataset.more;
      if (!open) fig.scrollIntoView({ block: "nearest" });
    } else if (el.hasAttribute("data-copy-inline")) {
      const code = el.closest(".md-chip")?.querySelector("code");
      if (code) io.copy(code.textContent, el.dataset.done);
    } else if (el.hasAttribute("data-md-more")) {
      const fold = el.closest(".md-fold");
      for (const li of fold?.querySelectorAll(
        ":scope > ul > li[hidden], :scope > ol > li[hidden]",
      ) || [])
        li.hidden = false;
      const next = fold?.querySelector(
        ":scope > ul > li:nth-child(9) , :scope > ol > li:nth-child(9)",
      );
      el.remove();
      next?.setAttribute("tabindex", "-1");
      next?.focus({ preventScroll: true });
    }
  });
}
