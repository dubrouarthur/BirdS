// A cold start: /api/health fails at first. Settings must say the model is waking up (never « Serveur
// indisponible » nor a demo card beside a real model), then show the real model once health answers.
//   .venv/bin/python scripts/serve.py --port 9073 &   (any server with a model; the demo server lacks one)
//   BIRD_URL=http://127.0.0.1:9073/ SHOTS=/tmp/shots node tests/e2e/health_waking.spec.js
const { chromium } = require("playwright");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9073/";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const check = (cond, what) => {
  if (!cond) throw new Error(`FAILED: ${what}`);
  console.log(`  ok  ${what}`);
};

(async () => {
  const browser = await chromium.launch();
  for (const colorScheme of ["light", "dark"]) {
    const page = await browser.newPage({ viewport: { width: 360, height: 780 }, colorScheme, deviceScaleFactor: 2 });
    await page.addInitScript(() => localStorage.setItem("bird.prefs", JSON.stringify({ lang: "fr", welcomed: true })));
    let failing = true;
    await page.route("**/api/health*", (route) => (failing ? route.abort() : route.continue()));
    await page.goto(URL);
    await page.waitForTimeout(8000); // the four first tries fail
    await page.evaluate(() => document.getElementById("nav-settings").click());
    const server = page.locator('input[name="mode"][value="server"]');
    check(!(await server.isDisabled()), `${colorScheme}: the server card stays selectable while waking`);
    check((await page.locator('input[name="mode"][value="demo"]').count()) === 0, `${colorScheme}: no demo card`);
    const text = await page.locator(".modes").innerText();
    check(/réveille|waking/.test(text) && !/Aucun modèle|No model/.test(text), `${colorScheme}: « se réveille »`);
    await page.screenshot({ path: path.join(SHOTS, `health-waking-${colorScheme}.png`) });
    failing = false;
    await page.waitForFunction(() => /Bird|model/i.test(document.querySelector(".modes")?.innerText || "") &&
      !/réveille|waking/.test(document.querySelector(".modes")?.innerText || ""), null, { timeout: 15000 });
    check(true, `${colorScheme}: the real model appears once health answers`);
    await page.screenshot({ path: path.join(SHOTS, `health-ready-${colorScheme}.png`) });
    await page.close();
  }
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
