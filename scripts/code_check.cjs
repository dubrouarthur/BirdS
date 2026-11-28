// Runs canvas code documents in the real preview frame (/canvas/frame of a running Bird server) and reports, for
// each: whether the page renders, its JavaScript errors (load, then one click on each of up to 6 buttons), the
// requests the frame's CSP blocked (external resources the model asked for), and horizontal overflow at 390, 768
// and 1280 px. Nothing is judged by eye: every number is counted from the browser's own events.
//   node scripts/code_check.cjs http://127.0.0.1:9251/ docs.json > report.json
// docs.json: [{"id": "...", "doc": {kind: "code", code: {...}}}]. Uses the preinstalled Playwright.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const WIDTHS = [390, 768, 1280];

async function bundler() {
  const file = path.join(__dirname, "..", "birds", "web", "static", "canvas-code.js");
  if (!fs.existsSync(file)) return null; // the base before this track: one file, wrapped as the panel did
  return import(file);
}

function legacyHtml(code) {
  const lang = code.lang;
  const text = String(code.text || "");
  if (lang === "html")
    return /<html|<!doctype/i.test(text) ? text : `<!doctype html><meta charset="utf-8"><body>${text}</body>`;
  if (lang === "svg") return `<!doctype html><meta charset="utf-8">${text}`;
  if (lang === "js") return `<!doctype html><meta charset="utf-8"><body><script>${text}</script></body>`;
  return "";
}

async function checkOne(browser, base, html, width) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  const page = await ctx.newPage();
  const errors = [];
  const blocked = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 300)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const s = m.text();
    if (/Content Security Policy|Refused to (load|connect|frame|apply)/i.test(s)) blocked.push(s.slice(0, 200));
    else errors.push(s.slice(0, 300));
  });
  await page.goto(new URL("canvas/frame", base).href);
  await page.evaluate((h) => window.postMessage({ bird: "render", html: h }, "*"), html);
  await page.waitForTimeout(900);
  const shape = await page.evaluate(() => {
    const b = document.body;
    const vis = b
      ? [...b.querySelectorAll("*")].filter((e) => {
          const r = e.getBoundingClientRect();
          return r.width > 4 && r.height > 4;
        }).length
      : 0;
    const de = document.documentElement;
    return {
      visible: vis,
      text: (b?.innerText || "").trim().length,
      overflow: Math.max(de.scrollWidth, b?.scrollWidth || 0) - de.clientWidth,
    };
  });
  let clicked = 0;
  if (width === 1280) {
    const buttons = await page.locator("button:visible, input[type=button]:visible").all();
    for (const btn of buttons.slice(0, 6)) {
      try {
        await btn.click({ timeout: 800 });
        clicked++;
      } catch {
        /* covered or detached: not an error of the page */
      }
    }
    await page.waitForTimeout(400);
  }
  await ctx.close();
  return { errors, blocked, shape, clicked };
}

(async () => {
  const [base, file] = process.argv.slice(2);
  const docs = JSON.parse(fs.readFileSync(file, "utf8"));
  const mod = await bundler();
  const browser = await chromium.launch();
  const out = [];
  for (const { id, doc } of docs) {
    const code = doc?.code || {};
    let html = "";
    if (mod && code.files) html = mod.bundle(doc).html;
    else html = legacyHtml(code);
    if (!html) {
      out.push({ id, previewable: false });
      continue;
    }
    const row = { id, previewable: true, widths: {} };
    const errs = new Set();
    let blocked = 0;
    for (const w of WIDTHS) {
      const r = await checkOne(browser, base, html, w);
      r.errors.forEach((e) => errs.add(e));
      blocked = Math.max(blocked, r.blocked.length);
      row.widths[w] = { overflow: r.shape.overflow, visible: r.shape.visible, text: r.shape.text };
      if (w === 1280) row.clicked = r.clicked;
    }
    row.errors = [...errs];
    row.blocked = blocked;
    row.renders = row.widths[1280].visible >= 3;
    row.responsive = WIDTHS.every((w) => row.widths[w].overflow <= 1);
    out.push(row);
  }
  await browser.close();
  process.stdout.write(JSON.stringify(out, null, 1));
})();
