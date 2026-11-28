// The footprint experience in the browser, on the demo server with its opt-in energy estimate:
//   .venv/bin/python scripts/serve.py --demo --demo-energy --port 9213 &
//   BIRD_URL=http://127.0.0.1:9213/ SHOTS=/tmp/shots node tests/e2e/footprint.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: the receipt chip stays one line; opening it shows the answer's impact (emissions, water, graphics card,
// equivalents with sources); the grid switch changes the emissions; the Empreinte page shows the totals, the chart,
// the comparison, the story and the sources; no third-party request, no CSP or script error, no horizontal scroll.
// Screenshots at 360 px and 1280 px, light and dark (look at them). ONLY=<config part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9213/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const PROMPTS = [
  "Bonjour",
  "Cherche des sources sur les petits modèles",
  "Rédige le compte rendu",
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
  await page.waitForTimeout(400);
}

async function noScroll(page, label, problems) {
  const [sw, cw] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  if (sw > cw + 1) problems.push(`${label}: horizontal scroll ${sw} > ${cw}`);
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
    await page.keyboard.press("Escape").catch(() => {});
    for (const p of PROMPTS) await send(page, p);
    // « Rédige le compte rendu » opens the document canvas (w1-canvas); on a phone it is a modal sheet
    if (await page.locator("#canvas").isVisible())
      await page.locator('#canvas [data-k="close"]').click();

    // the chip: one discreet line
    const last = page.locator(".turn-bird").last();
    const chip = last.locator(".receipt-chip");
    const box = await chip.boundingBox();
    if (!box || box.height > 46)
      problems.push(
        `${name}: the receipt chip is not one line (${box?.height})`,
      );
    await chip.click();
    await page.waitForTimeout(250);
    const fp = last.locator(".fp-answer");
    if (!(await fp.count())) {
      problems.push(`${name}: no .fp-answer in the open receipt`);
      await page.screenshot({
        path: path.join(OUT, `FAIL-footprint-${name}.png`),
      });
      continue;
    }
    const text = await fp.innerText();
    for (const needle of [
      "carte graphique",
      "CO₂e",
      "mL",
      "ADEME",
      "EPA",
      "France",
    ])
      if (!text.includes(needle))
        problems.push(`${name}: the answer's impact misses « ${needle} »`);
    // no grid declared by the operator: the grid is the reader's hypothesis, never « where Bird runs »
    if (!/si l'électricité vient du réseau/.test(text) || !/pas déclaré/.test(text))
      problems.push(`${name}: the default grid is not worded as a hypothesis`);
    const before = await fp.locator(".fp-fig-value").first().innerText();
    await fp.locator('[data-grid="world"]').click();
    await page.waitForTimeout(150);
    const after = await last
      .locator(".fp-answer .fp-fig-value")
      .first()
      .innerText();
    if (before === after)
      problems.push(
        `${name}: the grid switch did not change the emissions (${before})`,
      );
    await last.locator('.fp-answer [data-grid="fr"]').click();
    await last.locator(".fp-answer .fp-gpu-what > summary").click();
    await page.waitForTimeout(150);
    await noScroll(page, `${name}/receipt`, problems);
    // a tall viewport, so the sticky header and composer do not cover the open receipt
    const small = page.viewportSize();
    await page.setViewportSize({ width: small.width, height: 2600 });
    await page.waitForTimeout(300);
    await last.locator(".receipt").scrollIntoViewIfNeeded();
    await last
      .locator(".receipt-fold")
      .screenshot({ path: path.join(OUT, `footprint-receipt-${name}.png`) });
    await page.setViewportSize(small);

    // the Empreinte page
    await page.click("#btn-footprint");
    await page.waitForTimeout(400);
    const body = page.locator("#view-footprint-body");
    for (const sel of [
      '[data-fp="hero"]',
      '[data-fp="chart"]',
      '[data-fp="versus"]',
      '[data-fp="story"]',
      '[data-fp="method"]',
    ])
      if (!(await body.locator(sel).count()))
        problems.push(`${name}: the page misses ${sel}`);
    if ((await body.locator(".fp-story-item").count()) < 5)
      problems.push(`${name}: the story has fewer than 5 sections`);
    await body.locator('[data-fp="method"] > summary').click();
    await page.waitForTimeout(150);
    await noScroll(page, `${name}/page`, problems);
    const vp = page.viewportSize();
    const full = await page.evaluate(
      () => document.querySelector("#view-footprint").scrollHeight + 200,
    );
    await page.setViewportSize({
      width: vp.width,
      height: Math.min(9000, full),
    });
    await page.waitForTimeout(300);
    await page.screenshot({
      path: path.join(OUT, `footprint-page-${name}.png`),
      fullPage: true,
    });
    await page.setViewportSize(vp);
    // device scope
    await body.locator('[data-scope="all"]').click();
    await page.waitForTimeout(250);
    const hero = await body.locator('[data-fp="hero"]').innerText();
    if (!/appareil/.test(hero))
      problems.push(
        `${name}: the device scope does not say « Sur cet appareil »`,
      );
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log("footprint e2e: ok");
})();
