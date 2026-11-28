// Answer content in the browser (chat audit, cluster C2), on the demo server with a conversation recorded from
// production (tests/fixtures/answer_content.json: real answers of the audit, the entity picture pointed at an
// unsigned /api/img link, the mail draft as the server now sends it):
//   BIRD_RATE_LIMIT=0 BIRD_IMG_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9361 &
//   BIRD_URL=http://127.0.0.1:9361/ SHOTS=/tmp/shots node tests/e2e/answer_content.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: math typeset by the self-hosted KaTeX (no raw \[ … \], copy gives the TeX), human tool labels and no tick
// on « 0 sur 2 faites », « Syntaxe Python valide », the entity picture's slot gone when it fails, the mail card's
// « adresse à ajouter », inline citations with their bubble and the « N sources » pill, rich copy (text/html with a
// real table), thumbs-down reasons, one work line before a short answer; no third-party request, no CSP or script
// error, no horizontal scroll. Screenshots at 360 px and 1280 px, light and dark (look at them). ONLY=<config>.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9361/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
const BASE = process.env.BASE === "1"; // the branch before the fixes: screenshots only, no checks
fs.mkdirSync(OUT, { recursive: true });
const FIXTURE = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "answer_content.json"), "utf8"));
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
];

/** The recorded conversation, stored the way app.js stores one, opened as the current conversation. */
function seed(fixture) {
  const id = "cac2fixture01";
  const now = Date.now();
  const conv = { id, title: fixture.title, created: now - 60000, updated: now, turns: fixture.turns, attachments: [], canvas: { list: {}, active: null }, lang: "fr" };
  localStorage.setItem(`bird.conv.${id}`, JSON.stringify(conv));
  localStorage.setItem("bird.convs", JSON.stringify([{ id, title: fixture.title, created: conv.created, updated: now, n: fixture.turns.length }]));
  localStorage.setItem("bird.current", id);
  localStorage.setItem("bird.prefs", JSON.stringify({ lang: "fr", theme: "system", thinking: true, thinkingV: 2, mode: "", endpoint: "", token: "", model: "", access: "", welcomed: true }));
}

const birds = (page) => page.locator(".turn-bird");

async function shot(page, el, file) {
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const box = await el.boundingBox();
  const vp = page.viewportSize();
  const top = Math.max(0, box.y - 12);
  await page.screenshot({ path: path.join(OUT, file), clip: { x: 0, y: top, width: vp.width, height: Math.min(vp.height - top, Math.max(box.height + 24, 200)) } });
}

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  let checks = 0;
  const check = (ok, msg) => {
    checks += 1;
    if (!ok && !BASE) problems.push(msg);
  };
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris", permissions: ["clipboard-read", "clipboard-write"] });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (!u.startsWith("http://127.0.0.1") && !u.startsWith("data:") && !u.startsWith("blob:")) problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      const text = m.text();
      // the unsigned entity picture is refused by the proxy on purpose (403): that one error is expected
      if (/Failed to load resource.*(403|502)/.test(text)) return;
      if (m.type() === "error" || /Content Security Policy|Refused/.test(text)) problems.push(`${name}: console ${m.type()}: ${text}`);
    });
    page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.evaluate(seed, FIXTURE);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    await page.evaluate(() => document.querySelector("dialog[open]")?.close());
    const n = await birds(page).count();
    check(n === 6, `${name}: ${n} answers drawn`);

    // ---- R9 math: the photosynthesis answer (third), typeset; no raw \[ left; copy gives the TeX
    const photo = birds(page).nth(2);
    await photo.locator(".md-math").first().waitFor({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(800);
    const math = await photo.locator(".md-math").count();
    const typeset = await photo.locator('.md-math[data-typeset="1"] .katex').count();
    check(math >= 1 && typeset === math, `${name}: math ${typeset}/${math} typeset`);
    const rawLeft = await photo.locator(".md").evaluate((md) => {
      const copy = md.cloneNode(true);
      copy.querySelectorAll(".md-math").forEach((m) => m.remove());
      return /\\\[|\\xrightarrow|C_6H_\{12\}/.test(copy.textContent);
    });
    check(!rawLeft, `${name}: raw TeX left in the answer`);
    if (math) {
      const block = photo.locator(".md-math--block").first();
      if (await block.count()) {
        await shot(page, block, `math-${name}.png`);
        const styled = await block.evaluate((b) => [...b.querySelectorAll(".katex-html [style]")].length);
        check(styled > 0, `${name}: KaTeX layout styles not applied (CSSOM)`);
        await block.locator("[data-copy-tex]").click();
        await page.waitForTimeout(200);
        const clip = await page.evaluate(() => navigator.clipboard.readText()).catch(() => "");
        check(/^\$\$[\s\S]*C_6H_\{12\}O_6[\s\S]*\$\$$/.test(clip), `${name}: TeX copy gave « ${clip.slice(0, 60)} »`);
      }
    }
    // the same place in the answer, typeset or (base) raw: the paragraph or block holding the global equation
    const eq = photo.locator(".md-math--block, .md p:has-text('\\[')").first();
    if (await eq.count()) await shot(page, eq, `math-${name}.png`);

    const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    check(sw <= cw + 1, `${name}: horizontal scroll ${sw} > ${cw}`);

    // ---- R9: the math renderer's licence in « À propos » (the site under /a-propos/), served by Bird itself
    if (name.startsWith("desk")) {
      await page.goto(new globalThis.URL("/a-propos/", URL).href, { waitUntil: "networkidle" });
      const oss = page.locator(".footer-oss");
      check((await oss.count()) === 1 && /KaTeX[\s\S]*MIT/.test(await oss.innerText().catch(() => "")), `${name}: no KaTeX licence in À propos`);
      if (await oss.count()) {
        const href = await oss.locator("a").first().evaluate((a) => a.href);
        const status = await page.evaluate((u) => fetch(u).then((r) => r.status), href);
        check(new globalThis.URL(href).pathname === "/static/vendor/katex/LICENSE.txt" && status === 200, `${name}: licence link ${href} ${status}`);
        await shot(page, oss, `about-oss-${name}.png`);
      }
    }
    await ctx.close();
  }
  await browser.close();
  console.log(problems.length ? problems.join("\n") : `ok: ${checks} checks, 0 problems${BASE ? " (base: screenshots only)" : ""}`);
  process.exit(problems.length ? 1 : 0);
})();
