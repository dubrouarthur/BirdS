// Unit tests of the canvas's code mode without a browser (canvas-code.js): the files of a document, the page the
// preview runs, where an error comes from, the per-file change (same numbers as birds/canvas/code.py), the .zip.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as cc from "../../birds/web/static/canvas-code.js";

const page = {
  kind: "code",
  code: {
    lang: "html",
    text: "",
    files: [
      {
        name: "index.html",
        lang: "html",
        text: '<!doctype html>\n<html>\n<head>\n<link rel="stylesheet" href="./style.css">\n</head>\n<body>\n<h1>Hi</h1>\n<script>\nconsole.log(1)\n</script>\n<script src="script.js" defer></script>\n<p>end</p>\n</body>\n</html>',
      },
      { name: "style.css", lang: "css", text: "h1 { color: red }" },
      { name: "script.js", lang: "js", text: 'const s = "</script>";\nnull.x();' },
      { name: "extra.css", lang: "css", text: "p { margin: 0 }" },
    ],
  },
};

test("files of both shapes; the entry; setFile keeps the mirror", () => {
  assert.deepEqual(
    cc.filesOf({ code: { lang: "python", text: "print(1)" } }).map((f) => f.name),
    ["main.py"],
  );
  const files = cc.filesOf(page);
  assert.equal(files[cc.entryIndex(files)].name, "index.html");
  const d = structuredClone(page);
  cc.setFile(d, "style.css", "h1{}");
  cc.setFile(d, "new.js", "1");
  assert.equal(d.code.entry, "index.html");
  assert.equal(d.code.lang, "html");
  assert.ok(d.code.text.startsWith("<!doctype"));
  assert.equal(cc.filesOf(d).find((f) => f.name === "new.js").lang, "js");
  assert.equal(cc.nameLang("a.MJS"), "js");
});

test("bundle: linked files inline, defer at the end, unlinked styles added, sourceURL on every script", () => {
  const b = cc.bundle(page);
  assert.ok(b.previewable);
  assert.ok(!/<link/.test(b.html), "the linked stylesheet is inlined");
  assert.match(b.html, /<style data-file="style.css">h1 \{ color: red \}<\/style>/);
  assert.match(b.html, /<style data-file="extra.css">p \{ margin: 0 \}<\/style><\/head>/);
  assert.ok(!/src="script.js"/.test(b.html));
  // the deferred script runs after the page is parsed: it is placed at the end of body, after <p>end</p>
  assert.ok(b.html.indexOf("null.x()") > b.html.indexOf("<p>end</p>"));
  assert.match(b.html, /<\\\/script>/, "a closing tag in a string cannot end the inlined script");
  assert.match(b.html, /\/\/# sourceURL=script\.js/);
  assert.match(b.html, /\/\/# sourceURL=index\.html@8/, "an inline script names its line in the page");
  assert.deepEqual(b.used.sort(), ["extra.css", "index.html", "script.js", "style.css"]);
  // a file still being written is left out
  const partial = cc.bundle(page, { skip: new Set(["script.js"]), partial: true });
  assert.ok(!partial.html.includes("null.x()"));
  assert.ok(!partial.html.includes("absent"), "a file that may still come is not reported while streaming");
  const lost = cc.bundle({ code: { files: [{ name: "index.html", lang: "html", text: '<link rel="stylesheet" href="theme.css"><script src="app.js"></script>' }] } });
  assert.ok(!/href="theme.css"|src="app.js"/.test(lost.html), "no request for a file nobody wrote");
  assert.match(lost.html, /console\.warn\("fichier absent : theme\.css"\)/);
  assert.match(lost.html, /console\.warn\("fichier absent : app\.js"\)/);
  // external resources are left as written (the frame's CSP blocks them, the console says so)
  const ext = cc.bundle({ code: { files: [{ name: "index.html", lang: "html", text: '<script src="https://cdn.example/x.js"></script>' }] } });
  assert.match(ext.html, /https:\/\/cdn\.example\/x\.js/);
  // a fragment is wrapped; svg, css, js alone are previewable; python is not
  assert.match(cc.bundle({ code: { lang: "html", text: "<p>x</p>" } }).html, /^<!doctype html>/);
  assert.ok(cc.bundle({ code: { lang: "svg", text: "<svg/>" } }).previewable);
  assert.ok(!cc.bundle({ code: { lang: "python", text: "print(1)" } }).previewable);
  // JSON data blocks are not scripts
  const data = cc.bundle({ code: { lang: "html", text: '<script type="application/json">{"a":1}</script>' } });
  assert.ok(!data.html.includes("sourceURL"));
});

test("whereIs: the frame's location turned into file and line", () => {
  assert.deepEqual(cc.whereIs("TypeError: x (script.js, l. 2)"), { text: "TypeError: x", file: "script.js", line: 2 });
  assert.deepEqual(cc.whereIs("Oops (index.html@8, l. 3)"), { text: "Oops", file: "index.html", line: 10 });
  assert.deepEqual(cc.whereIs("plain"), { text: "plain", file: null, line: null });
});

test("diffFiles: added, changed, removed, unchanged left out; same numbers as code.py", () => {
  const a = { code: { files: [
    { name: "index.html", text: "a\nb\nc" },
    { name: "style.css", text: "x" },
    { name: "old.js", text: "1\n2" },
  ] } };
  const b = { code: { files: [
    { name: "index.html", text: "a\nB\nc\nd" },
    { name: "style.css", text: "x" },
    { name: "new.js", text: "z" },
  ] } };
  assert.deepEqual(cc.diffFiles(a, b), [
    { name: "index.html", status: "changed", plus: 2, minus: 1 },
    { name: "new.js", status: "added", plus: 1, minus: 0 },
    { name: "old.js", status: "removed", plus: 0, minus: 2 },
  ]);
});

test("zip: a valid stored archive with UTF-8 names and CRC-32", () => {
  assert.equal(cc.crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
  const files = [
    { name: "index.html", text: "<p>é</p>" },
    { name: "café.js", text: "x" },
  ];
  const z = cc.zip(files, new Date(2026, 10, 28, 10, 30, 0));
  const dv = new DataView(z.buffer);
  const end = z.length - 22;
  assert.equal(dv.getUint32(end, true), 0x06054b50);
  assert.equal(dv.getUint16(end + 10, true), 2);
  let off = dv.getUint32(end + 16, true);
  const dec = new TextDecoder();
  for (const f of files) {
    assert.equal(dv.getUint32(off, true), 0x02014b50);
    const nlen = dv.getUint16(off + 28, true);
    const local = dv.getUint32(off + 42, true);
    assert.equal(dec.decode(z.slice(off + 46, off + 46 + nlen)), f.name);
    const size = dv.getUint32(local + 18, true);
    const lnl = dv.getUint16(local + 26, true);
    const data = z.slice(local + 30 + lnl, local + 30 + lnl + size);
    assert.equal(dec.decode(data), f.text);
    assert.equal(dv.getUint32(local + 14, true), cc.crc32(data));
    off += 46 + nlen;
  }
});
