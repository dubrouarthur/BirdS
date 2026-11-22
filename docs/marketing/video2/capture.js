// Capture real Bird conversations from the live endpoint, as PNG sequences.
// Usage: node capture.js <scene numbers...>   (server must run on :8820 with --from-env)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const ROOT =
  "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video2";
const URL = process.env.BIRD_URL || "http://127.0.0.1:8820/";
const INVOICE = path.join(ROOT, "invoice.png");

const SCENES = {
  2: {
    prompt:
      "Écris un mail de 3 lignes à Claire pour décaler notre réunion de jeudi à vendredi 10h.",
  },
  3: {
    prompt:
      "Crée une présentation de 5 slides : lancement d'une newsletter interne.",
    openPreview: true,
  },
  4: {
    prompt: "Quel est le total TTC de cette facture ? Réponds en une ligne.",
    image: INVOICE,
  },
  5: {
    prompt: "En 3 lignes : comment écrire un bon objet de mail ?",
    openMeter: true,
  },
};

const HIDE = `
  ::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
  * { scrollbar-width: none !important; }
  textarea, input { caret-color: auto; }
`;

async function run(n, tag) {
  const sc = { ...SCENES[n], ...(process.env.PROMPT ? { prompt: process.env.PROMPT } : {}) };
  const dir = path.join(ROOT, "cap", `scene${n}${tag || ""}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    colorScheme: "light",
    bypassCSP: true,
    locale: "fr-FR",
    isMobile: true,
    hasTouch: true,
  });
  const page = await ctx.newPage();
  await page.goto(URL);
  await page.addStyleTag({ content: HIDE });
  await page
    .locator("#welcome-start")
    .click({ timeout: 8000 })
    .catch(() => {});
  await page.waitForTimeout(500);
  await page
    .locator("#btn-new-top")
    .click()
    .catch(() => {});
  await page.waitForTimeout(300);

  let i = 0;
  const times = [];
  const t0 = Date.now();
  let shooting = true;
  const shot = async () => {
    i += 1;
    await page.screenshot({
      path: path.join(dir, String(i).padStart(4, "0") + ".png"),
    });
    times.push({ i, t: (Date.now() - t0) / 1000 });
  };
  const loop = (async () => {
    while (shooting) {
      const s = Date.now();
      await shot().catch(() => {});
      const wait = 250 - (Date.now() - s);
      if (wait > 0) await page.waitForTimeout(wait);
    }
  })();

  if (sc.image) {
    await page.locator("#photo-library").setInputFiles(sc.image);
    await page.waitForTimeout(1200);
  }
  await page.locator("#composer-input").click();
  await page.keyboard.type(sc.prompt, { delay: 35 });
  await page.waitForTimeout(400);
  await page.locator("#btn-send").click();
  const tSend = (Date.now() - t0) / 1000;
  // wait for the stop button to appear then disappear (turn finished)
  await page
    .locator("#btn-stop")
    .waitFor({ state: "visible", timeout: 15000 })
    .catch(() => {});
  await page.locator("#btn-stop").waitFor({ state: "hidden", timeout: 300000 });
  const tDone = (Date.now() - t0) / 1000;
  await page.waitForTimeout(1500);

  if (sc.openPreview) {
    const prev = page.locator(".file-card .card-preview").last();
    if (await prev.count()) {
      await prev.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(500);
      const sum = prev.locator("summary").first();
      if (await sum.count()) await sum.click().catch(() => {});
      else await prev.click().catch(() => {});
      await page.waitForTimeout(800);
      for (let k = 0; k < 14; k++) {
        await page.mouse.wheel(0, 120);
        await page.waitForTimeout(250);
      }
      await page.waitForTimeout(800);
    }
  }
  if (sc.openMeter) {
    const r = page.locator(".receipt").last();
    await r.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(700);
    await r
      .locator("summary")
      .first()
      .click()
      .catch(() => {});
    await page.waitForTimeout(800);
    await r.scrollIntoViewIfNeeded().catch(() => {});
    await page
      .locator(".receipt-more")
      .last()
      .scrollIntoViewIfNeeded()
      .catch(() => {});
    await page.waitForTimeout(1500);
  }
  shooting = false;
  await loop;
  await page.screenshot({ path: path.join(dir, "final.png") });
  const card = page.locator("#conversation .card").last();
  if (await card.count()) {
    await card.evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => {});
    await page.evaluate(() => document.querySelector("#scroll").scrollBy(0, -70));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(dir, "final_card.png") });
  }
  await page
    .screenshot({ path: path.join(dir, "final_full.png"), fullPage: true })
    .catch(() => {});
  const answer = await page.evaluate(() => {
    const c = document.querySelector("#conversation");
    return c ? c.innerText : "";
  });
  fs.writeFileSync(path.join(dir, "answer.txt"), answer);
  fs.writeFileSync(
    path.join(dir, "timing.json"),
    JSON.stringify({ tSend, tDone, frames: times }, null, 1),
  );
  // also a still of the conversation element alone
  await page
    .locator("#conversation")
    .screenshot({ path: path.join(dir, "conversation.png") })
    .catch(() => {});
  console.log(
    `scene${n}${tag || ""}: ${i} frames, send ${tSend.toFixed(1)}s, done ${tDone.toFixed(1)}s`,
  );
  console.log(answer);
  await browser.close();
}

(async () => {
  const args = process.argv.slice(2);
  const tag = process.env.TAG || "";
  for (const a of args) await run(Number(a), tag);
})();
