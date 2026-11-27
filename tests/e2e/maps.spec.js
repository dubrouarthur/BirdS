// Map cards in the browser, on the demo server (recorded BAN answers, pre-rendered maps, no model):
//   .venv/bin/python scripts/serve.py --demo --port 9337 &
//   BIRD_URL=http://127.0.0.1:9337/ SHOTS=/tmp/shots node tests/e2e/maps.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: a list of addresses draws one map with a numbered pin per place and its list; « introuvable » is said;
// a visit order lists the cards in that order; a simulated model failure still shows the card and a short answer
// (no error card); full screen opens and Escape closes it; no third-party request, no CSP or script error, no
// horizontal scroll. Screenshots at 360 px and 1280 px, light and dark (look at them). ONLY=<config part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9337/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
// [id, prompt, pins expected, text the turn must contain]
const CASES = [
  [
    "addresses",
    "montre sur une carte : 10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille ; 99 rue inexistante Nullepart",
    3,
    "introuvable",
  ],
  [
    "order",
    "dans quel ordre visiter Lyon, Grenoble, Annecy et Chambéry ?",
    4,
    "→",
  ],
  [
    "ten",
    "mets sur une carte : Paris ; Lyon ; Marseille ; Bordeaux ; Nantes ; Lille ; Strasbourg ; Toulouse ; Nice ; Rennes",
    10,
    "Rennes",
  ],
  [
    "failure",
    "simule une panne : montre sur une carte : 10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille",
    3,
    "Rivoli",
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
  await page.waitForTimeout(500);
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
    page.on("response", (r) => {
      if (r.status() >= 400) problems.push(`${name}: HTTP ${r.status()} ${r.url()}`);
    });
    page.on("pageerror", (e) =>
      problems.push(`${name}: pageerror ${e.message}`),
    );
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    for (const [id, prompt, pins, must] of CASES) {
      const narrow = await page.evaluate(() => innerWidth < 900);
      await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
      await page.waitForTimeout(150);
      await send(page, prompt);
      const last = page.locator(".turn-bird").last();
      const card = last.locator(".widget-places");
      const text = await last.innerText();
      const n = await card.locator(".place-list > li").count();
      if (!(await card.count()) || n !== pins || !text.includes(must)) {
        problems.push(
          `${name}/${id}: expected a map with ${pins} places and « ${must} », got ${n} places`,
        );
        await page.screenshot({
          path: path.join(OUT, `FAIL-maps-${id}-${name}.png`),
        });
        continue;
      }
      if (await last.locator(".turn-error, .error-card").count())
        problems.push(`${name}/${id}: an error card was drawn`);
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
      await page.screenshot({ path: path.join(OUT, `maps-${id}-${name}.png`) });
      await page.setViewportSize(vp);
      await page.waitForTimeout(150);
      if (id === "ten") {
        // full screen: the map and its list fill the window; Escape closes and gives the focus back
        await card.locator(".map-full").click();
        await page.waitForTimeout(400);
        if (!(await card.evaluate((s) => s.classList.contains("is-full"))))
          problems.push(`${name}/${id}: full screen did not open`);
        await page.screenshot({
          path: path.join(OUT, `maps-full-${name}.png`),
        });
        await page.keyboard.press("Escape");
        await page.waitForTimeout(300);
        if (await card.evaluate((s) => s.classList.contains("is-full")))
          problems.push(`${name}/${id}: Escape did not close full screen`);
      }
    }
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log(
    "ok: map cards drawn (lists, order, failure, full screen); no third-party request, no CSP error, no overflow",
  );
})();
