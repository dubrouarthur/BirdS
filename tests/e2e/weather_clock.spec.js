// Weather and world-clock cards in the browser, on the demo server (recorded MET answers, no model).
//   .venv/bin/python scripts/serve.py --demo --port 9071 &
//   BIRD_URL=http://127.0.0.1:9071/ SHOTS=/tmp/shots node tests/e2e/weather_clock.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: no request to any third party, no CSP or script error, no horizontal scroll, nothing outside the card;
// screenshots at 360 px and 1280 px, light and dark (look at them). ONLY=<config part>, P=<prompt id> narrow it.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9071/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
fs.mkdirSync(OUT, { recursive: true });
const PROMPTS = [
  ["weather-lyon", "météo à Lyon demain"],
  ["weather-nantes", "il va pleuvoir à Nantes ?"],
  ["weather-lille", "quel temps pour jeudi à Lille"],
  ["clock-ny", "quelle heure est-il à New York"],
  [
    "clock-slot",
    "trouve un créneau commun Paris Montréal Singapour pour une réunion",
  ],
  ["clock-tokyo", "décalage horaire avec Tokyo"],
  ["event-weather", "réunion jeudi à Lille à 14h, il va pleuvoir ?"],
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
    await page.waitForTimeout(1500);
    for (const [id, text] of PROMPTS) {
      if (process.env.P && !id.includes(process.env.P)) continue;
      const narrow = await page.evaluate(() => innerWidth < 900);
      await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
      await page.waitForTimeout(150);
      await page.fill("#composer-input", text);
      await page.press("#composer-input", "Enter");
      await page.waitForTimeout(1200);
      if (!(await page.locator(".turn-user").count())) {
        await page.fill("#composer-input", text);
        await page.press("#composer-input", "Enter");
        await page.waitForTimeout(1200);
      }
      await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
      await page.waitForFunction(
        () => !document.querySelector('.turn-bird[aria-busy="true"]'),
        null,
        { timeout: 60000 },
      );
      await page.waitForTimeout(400);
      const w = page.locator(".turn-bird .widgets").last();
      if (!(await w.count())) {
        problems.push(`${name}/${id}: no widgets`);
        await page.screenshot({ path: path.join(OUT, `FAIL-${id}-${name}.png`) });
        continue;
      }
      await w.scrollIntoViewIfNeeded();
      const [sw, cw] = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        document.documentElement.clientWidth,
      ]);
      if (sw > cw + 1)
        problems.push(`${name}/${id}: horizontal scroll ${sw} > ${cw}`);
      const overflow = await page.evaluate(() => {
        const out = [];
        for (const el of document.querySelectorAll(
          ".widget-weather *, .widget-clock *",
        )) {
          const r = el.getBoundingClientRect();
          const box = el.closest(".widget").getBoundingClientRect();
          if (r.width && (r.right > box.right + 1 || r.left < box.left - 1))
            out.push(
              `${el.className?.baseVal ?? el.className} ${Math.round(r.left)}-${Math.round(r.right)} vs ${Math.round(box.left)}-${Math.round(box.right)}`,
            );
        }
        return out.slice(0, 5);
      });
      if (overflow.length)
        problems.push(`${name}/${id}: overflow ${overflow.join(" | ")}`);
      // a tall viewport at the same width: the composer and « go to end » no longer cover the card
      const vp = page.viewportSize();
      await page.setViewportSize({ width: vp.width, height: 2600 });
      await page.waitForTimeout(300);
      await w.screenshot({ path: path.join(OUT, `${id}-${name}.png`) });
      if (name.startsWith("m360")) {
        const turn = page.locator(".turn-bird").last();
        await turn.screenshot({
          path: path.join(OUT, `${id}-${name}-turn.png`),
        });
      }
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
  console.log("ok: no third-party request, no CSP error, no overflow");
})();
