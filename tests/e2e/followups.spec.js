// Short follow-ups in the browser, on the demo server (recorded answers, no model): « et à Lille ? » after a weather
// card, « et Sydney ? » after a world clock. The client sends each turn's memo back; the demo reads its context.
//   .venv/bin/python scripts/serve.py --demo --port 9211 &
//   BIRD_URL=http://127.0.0.1:9211/ SHOTS=/tmp/shots node tests/e2e/followups.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: the follow-up draws a new card for the new place, no third-party request, no CSP or script error, no
// horizontal scroll; screenshots at 360 px and 1280 px, light and dark (look at them). ONLY=<config part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9211/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const CONVERSATIONS = [
  [
    "weather",
    ["météo à Lyon demain", "et à Lille ?"],
    ".widget-weather",
    "Lille",
  ],
  [
    "clock",
    ["quelle heure est-il à Tokyo ?", "et Sydney ?"],
    ".widget-clock",
    "Sydney",
  ],
];
const CONFIGS = [
  {
    name: "m360-light",
    viewport: { width: 360, height: 780 },
    deviceScaleFactor: 2,
    colorScheme: "light",
    isMobile: true,
    hasTouch: true,
  },
  {
    name: "m360-dark",
    viewport: { width: 360, height: 780 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    isMobile: true,
    hasTouch: true,
  },
  {
    name: "desk-light",
    viewport: { width: 1280, height: 900 },
    colorScheme: "light",
  },
  {
    name: "desk-dark",
    viewport: { width: 1280, height: 900 },
    colorScheme: "dark",
  },
];

async function send(page, text) {
  const before = await page.locator(".turn-user").count();
  for (let attempt = 0; attempt < 2; attempt++) {
    // the first keystrokes can land while the welcome screen is still settling: send again once if nothing started
    await page.fill("#composer-input", text);
    await page.press("#composer-input", "Enter");
    await page.waitForTimeout(1200);
    if ((await page.locator(".turn-user").count()) > before) break;
  }
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForFunction(
    () => !document.querySelector('.turn-bird[aria-busy="true"]'),
    null,
    { timeout: 60000 },
  );
  await page.waitForTimeout(400);
}

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({
      ...opts,
      locale: "fr-FR",
      timezoneId: "Europe/Paris",
    });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (
        !u.startsWith("http://127.0.0.1") &&
        !u.startsWith("data:") &&
        !u.startsWith("blob:")
      )
        problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      if (
        m.type() === "error" ||
        /Content Security Policy|Refused/.test(m.text())
      )
        problems.push(`${name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) =>
      problems.push(`${name}: pageerror ${e.message}`),
    );
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    for (const [id, turns, card, place] of CONVERSATIONS) {
      const narrow = await page.evaluate(() => innerWidth < 900);
      await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
      await page.waitForTimeout(150);
      for (const t of turns) await send(page, t);
      const last = page.locator(".turn-bird").last();
      const w = last.locator(card);
      if (!(await w.count()) || !(await last.innerText()).includes(place)) {
        problems.push(
          `${name}/${id}: the follow-up drew no ${card} for ${place}`,
        );
        await page.screenshot({
          path: path.join(OUT, `FAIL-followup-${id}-${name}.png`),
        });
        continue;
      }
      const [sw, cw] = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
      ]);
      if (sw > cw + 1)
        problems.push(`${name}/${id}: horizontal scroll ${sw} > ${cw}`);
      const vp = page.viewportSize();
      await page.setViewportSize({ width: vp.width, height: 2600 });
      await page.waitForTimeout(300);
      await page.locator(".turn-user").last().scrollIntoViewIfNeeded();
      await page.screenshot({
        path: path.join(OUT, `followup-${id}-${name}.png`),
      });
      await page.setViewportSize(vp);
      await page.waitForTimeout(150);
    }
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log(
    "ok: follow-ups drew their cards; no third-party request, no CSP error, no overflow",
  );
})();
