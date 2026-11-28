// Bird's next steps under an answer (birds/harness/nextsteps.py, the « suggestions » event), on the demo server
// (scripted next steps, no model):
//   BIRD_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9213 &
//   BIRD_URL=http://127.0.0.1:9213/ SHOTS=/tmp/shots node tests/e2e/nextsteps.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: the chips arrive after the answer and read as the user's requests (never a fragment of Bird's question),
// the widget chips still fill in after a weather card, a chip is reachable with the keyboard and Enter sends its
// request, no third-party request, no CSP or script error, no horizontal scroll; screenshots at 360 px and
// 1280 px, light and dark (look at them). ONLY=<config part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9213/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
];

async function send(page, text) {
  const before = await page.locator(".turn-user").count();
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.fill("#composer-input", text);
    await page.press("#composer-input", "Enter");
    await page.waitForTimeout(1200);
    if ((await page.locator(".turn-user").count()) > before) break;
  }
  await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, { timeout: 60000 });
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForTimeout(500);
}

async function closeCanvas(page) {
  // the deck opens beside the chat (over it on a phone): back to the conversation to see the chips
  const close = page.locator('[data-act="canvas-close"], .cv-close, button[aria-label*="Fermer le canevas"]');
  if (await close.count()) await close.first().click().catch(() => {});
  await page.waitForTimeout(300);
}

async function shot(page, file) {
  const vp = page.viewportSize();
  await page.setViewportSize({ width: vp.width, height: 1600 });
  await page.waitForTimeout(300);
  await page.locator(".turn-bird").last().locator(".chips-row").scrollIntoViewIfNeeded().catch(() => {});
  await page.screenshot({ path: path.join(OUT, file) });
  await page.setViewportSize(vp);
  await page.waitForTimeout(150);
}

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (!u.startsWith("http://127.0.0.1") && !u.startsWith("data:") && !u.startsWith("blob:"))
        problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      if (m.type() === "error" || /Content Security Policy|Refused/.test(m.text()))
        problems.push(`${name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);

    // 1. a deck: Bird's own next steps, in the user's voice
    await send(page, "fais une présentation sur le télétravail");
    await closeCanvas(page);
    const row = page.locator(".turn-bird").last().locator(".chips-row");
    const next = row.locator(".mchip-next");
    const labels = await next.allInnerTexts();
    if (labels.length !== 2) problems.push(`${name}: expected 2 next-step chips, got ${JSON.stringify(labels)}`);
    for (const l of labels)
      if (/^(?:↳\s*)?(?:vous|à |souhait|oui)/i.test(l)) problems.push(`${name}: chip in Bird's voice: ${l}`);
    const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    if (sw > cw + 1) problems.push(`${name}: horizontal scroll ${sw} > ${cw}`);
    for (const box of await next.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().right)))
      if (box > cw + 1) problems.push(`${name}: a chip overflows (${box} > ${cw})`);
    await shot(page, `nextsteps-deck-${name}.png`);

    // 2. keyboard: focus the first chip, Enter sends its request as the next user turn
    if (labels.length) {
      const prompt = await next.first().getAttribute("title");
      // by the keyboard, as a user would: Tab from the « Plus » button lands on the first chip
      await page.locator(".turn-bird").last().locator('[data-act="more"]').focus();
      await page.keyboard.press("Tab");
      const onChip = await next.first().evaluate((e) => e === document.activeElement);
      if (!onChip) problems.push(`${name}: Tab from « Plus » does not reach the first chip`);
      const ring = await next.first().evaluate((e) => getComputedStyle(e).outlineStyle);
      if (ring === "none") problems.push(`${name}: no visible focus ring on a chip`);
      await page.keyboard.press("Enter");
      await page.waitForTimeout(1200);
      await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, { timeout: 60000 });
      const sent = await page.locator(".turn-user").last().innerText();
      if (!sent.includes(prompt)) problems.push(`${name}: Enter on a chip sent ${JSON.stringify(sent)}, not ${prompt}`);
      await closeCanvas(page);
    }

    // 3. a weather card: no scripted next steps, the widget chips fill in
    const narrow = await page.evaluate(() => innerWidth < 900);
    await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
    await page.waitForTimeout(200);
    await send(page, "météo à Lyon demain");
    const wx = await page.locator(".turn-bird").last().locator(".chips-row .mchip").allInnerTexts();
    if (!wx.some((l) => /après-demain|Restaurants/.test(l))) problems.push(`${name}: weather chips missing: ${JSON.stringify(wx)}`);
    await shot(page, `nextsteps-weather-${name}.png`);
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log("ok: next steps in the user's voice, widget chips kept, keyboard, no third-party request, no CSP error, no overflow");
})();
