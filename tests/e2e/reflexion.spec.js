// Mode Réflexion in the browser, on the demo server (recorded answers, no model): the bird picker in the composer,
// the request it sends, and the answer's « Bird a pris son vol en Faucon » header with its summary and checks.
//   .venv/bin/python scripts/serve.py --demo --port 9351 &
//   BIRD_URL=http://127.0.0.1:9351/ SHOTS=/tmp/shots node tests/e2e/reflexion.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: six choices with their drawings, the keyboard (Enter opens, arrows move, Escape closes and gives the
// focus back), the choice kept after a reload and sent as `reflexion`, Faucon's header (votre choix, summary, the
// calculations redone by Bird), Auto's header (« choix de la démo »: no model in the demo, the fallback cues choose), Colibri for « bonjour » (no reasoning), no motion
// with prefers-reduced-motion, no third-party request, no CSP or script error, no horizontal scroll; screenshots at
// 360 px and 1440 px, light and dark (look at them). ONLY=<config part> narrows.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9351/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const CALC = "Un abonnement coûte 14,90 € par mois, ou 149 € par an. Sur deux ans, lequel est le moins cher et de combien ?";
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1440, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1440, height: 900 }, colorScheme: "dark", reducedMotion: "reduce" },
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
  await page.waitForTimeout(500);
}

async function newConv(page) {
  const narrow = await page.evaluate(() => innerWidth < 900);
  await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
  await page.waitForTimeout(200);
}

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const page = await ctx.newPage();
    const bodies = [];
    page.on("request", (r) => {
      const u = r.url();
      if (!u.startsWith("http://127.0.0.1") && !u.startsWith("data:") && !u.startsWith("blob:"))
        problems.push(`${name}: third-party request ${u}`);
      if (u.includes("/api/chat") && r.method() === "POST") bodies.push(r.postData() || "");
    });
    page.on("console", (m) => {
      if (m.type() === "error" || /Content Security Policy|Refused/.test(m.text()))
        problems.push(`${name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await page.evaluate(() => document.querySelector("dialog[open]")?.close());
    const pill = page.locator("#rf-button");
    if ((await pill.getAttribute("aria-label")) !== "Réflexion : Auto") problems.push(`${name}: pill label ${await pill.getAttribute("aria-label")}`);
    // ---- the menu, with the keyboard
    await pill.focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(250);
    const opts6 = await page.locator('#rf-menu [role="menuitemradio"]').count();
    if (opts6 !== 6) problems.push(`${name}: ${opts6} choices`);
    const drawn = await page.locator("#rf-menu .rf-opt-icon svg path").count();
    if (drawn < 6) problems.push(`${name}: ${drawn} drawings`);
    const focused = await page.evaluate(() => document.activeElement?.dataset.level);
    if (focused !== "auto") problems.push(`${name}: focus on open ${focused}`);
    await page.screenshot({ path: path.join(OUT, `rf-menu-${name}.png`) });
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
    if ((await page.evaluate(() => document.activeElement?.dataset.level)) !== "faucon") problems.push(`${name}: arrows`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
    if (!(await page.locator("#rf-menu").isHidden())) problems.push(`${name}: Escape did not close`);
    if ((await page.evaluate(() => document.activeElement?.id)) !== "rf-button") problems.push(`${name}: focus not returned`);
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(150);
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(200);
    if ((await pill.getAttribute("data-level")) !== "faucon") problems.push(`${name}: Faucon not picked`);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    await page.evaluate(() => document.querySelector("dialog[open]")?.close());
    if ((await pill.getAttribute("data-level")) !== "faucon") problems.push(`${name}: choice not kept after reload`);
    await page.screenshot({ path: path.join(OUT, `rf-pill-${name}.png`) });
    // ---- Faucon, chosen
    await newConv(page);
    await send(page, CALC);
    if (!/"reflexion":"faucon"/.test(bodies.at(-1) || "")) problems.push(`${name}: request body ${String(bodies.at(-1)).slice(0, 80)}`);
    let last = page.locator(".turn-bird").last();
    const flight = last.locator("details.rf-flight");
    if (!(await flight.count())) {
      problems.push(`${name}: no flight header`);
      await page.screenshot({ path: path.join(OUT, `FAIL-rf-${name}.png`) });
      await ctx.close();
      continue;
    }
    const line = (await flight.locator(".rf-line").innerText()).trim();
    if (line !== "Bird a pris son vol en Faucon") problems.push(`${name}: « ${line} »`);
    const meta = (await flight.locator(".rf-meta").innerText()).trim();
    if (meta !== "Précis · votre choix") problems.push(`${name}: meta « ${meta} »`);
    if (await flight.evaluate((el) => el.open)) problems.push(`${name}: header opens by itself`);
    await flight.locator(":scope > summary").focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(200);
    if (!(await flight.evaluate((el) => el.open))) problems.push(`${name}: Enter did not open the header`);
    const sum = await flight.locator(".rf-sum li").count();
    if (sum < 2) problems.push(`${name}: summary lines ${sum}`);
    const facts = await flight.locator(".rf-facts").innerText();
    if (!/calculs refaits par Bird : tous justes/.test(facts)) problems.push(`${name}: facts « ${facts} »`);
    if (!(await flight.locator("details.rf-full").count())) problems.push(`${name}: no full reasoning`);
    // the arrival plays once per answer (redraws drop the class): read it on a copy that carries it
    const anim = await flight.evaluate((el) => {
      const copy = el.cloneNode(true);
      copy.classList.add("rf-arrive");
      el.after(copy);
      const name = getComputedStyle(copy.querySelector(".rf-badge .rf-bird")).animationName;
      copy.remove();
      return name;
    });
    if (opts.reducedMotion === "reduce" ? anim !== "none" : anim !== "rf-glide") problems.push(`${name}: animation ${anim}`);
    const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    if (sw > cw + 1) problems.push(`${name}: horizontal scroll ${sw} > ${cw}`);
    await page.waitForTimeout(900);
    const vp = page.viewportSize();
    await page.setViewportSize({ width: vp.width, height: 1500 });
    await page.waitForTimeout(250);
    await page.locator(".turn-user").last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(OUT, `rf-faucon-${name}.png`) });
    await last.screenshot({ path: path.join(OUT, `rf-faucon-${name}-crop.png`) });
    await page.setViewportSize(vp);
    await page.waitForTimeout(300);
    // ---- Auto: Bird chooses (in the demo, the fallback cues: no model)
    await pill.click();
    await page.waitForTimeout(200);
    await page.locator('#rf-menu .rf-opt[data-level="auto"]').click({ timeout: 5000 });
    await page.waitForTimeout(150);
    await newConv(page);
    await send(page, CALC);
    last = page.locator(".turn-bird").last();
    const meta2 = (await last.locator(".rf-flight .rf-meta").innerText().catch(() => "")).trim();
    if (meta2 !== "Précis · choix de la démo") problems.push(`${name}: auto meta « ${meta2} »`);
    await send(page, "bonjour");
    last = page.locator(".turn-bird").last();
    const line3 = (await last.locator(".rf-flight .rf-line").innerText().catch(() => "")).trim();
    if (line3 !== "Bird a pris son vol en Colibri") problems.push(`${name}: bonjour « ${line3} »`);
    if (await last.locator("details.rf-full").count()) problems.push(`${name}: Colibri shows a reasoning`);
    const [sw2, cw2] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    if (sw2 > cw2 + 1) problems.push(`${name}: horizontal scroll ${sw2} > ${cw2}`);
    await last.screenshot({ path: path.join(OUT, `rf-colibri-${name}-crop.png`) });
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log("PROBLEMS:\n" + problems.join("\n"));
    process.exit(1);
  }
  console.log("reflexion e2e: all checks passed");
})();
