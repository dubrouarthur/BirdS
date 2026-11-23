// v5: capture real, unedited Bird sessions of the current app (new UI) as PNG sequences.
// Usage: node capture5.js <scene names...>   (server: scripts/serve.py ... --port 9081)
//   scenes: mail deck chart rich places weather clock agent
//   BIRD_URL=http://127.0.0.1:9082/ (demo server) for the cards whose live data calls are blocked
// Each scene: one live request typed into the real composer, screenshots every ~250 ms on an
// iPhone-like viewport (390x844 @3x), timing.json with the capture clock. Nothing is retouched.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const ROOT =
  "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video5";
const URL = process.env.BIRD_URL || "http://127.0.0.1:9081/";

const SCENES = {
  mail: {
    prompt:
      "Écris un mail de 3 lignes à Claire pour décaler notre réunion de jeudi à vendredi 10h.",
  },
  deck: {
    prompt:
      "Crée une présentation de 5 slides : lancement d'une newsletter interne.",
    deck: true,
  },
  chart: {
    prompt:
      "Fais un graphique en barres de nos ventes 2025 : T1 120 k€, T2 150 k€, T3 135 k€, T4 190 k€.",
    chart: true,
  },
  rich: {
    prompt:
      "Explique les listes en compréhension en Python : une phrase, trois points clés en liste, puis un court exemple de code.",
    fast: true, // as many frames as the screenshots allow: the bird's wings beat next to « Bird »
  },
  places: {
    prompt: "Restaurants près de la gare de Lyon",
    widget: ".widget-places .map-frame",
  },
  weather: { prompt: "Météo à Lyon demain", widget: ".widget-weather" },
  clock: {
    prompt: "Trouve un créneau commun Paris Montréal Singapour",
    widget: ".widget-clock",
  },
  agent: {
    prompt:
      "Prépare une présentation de 5 slides pour lancer notre newsletter interne : objectifs, contenu, rythme, équipe, prochaines étapes.",
    agent: "on",
    deck: true,
  },
};

const HIDE = `
  ::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
  * { scrollbar-width: none !important; }
`;

async function run(name, tag) {
  const sc = {
    ...SCENES[name],
    ...(process.env.HIDE_DEMO ? { hideDemo: true } : {}),
    ...(process.env.PROMPT ? { prompt: process.env.PROMPT } : {}),
  };
  const dir = path.join(ROOT, "cap", `${name}${tag || ""}`);
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
  const marks = {};
  const t0 = Date.now();
  const now = () => (Date.now() - t0) / 1000;
  let shooting = true;
  const shot = async () => {
    i += 1;
    await page.screenshot({
      path: path.join(dir, String(i).padStart(4, "0") + ".png"),
    });
    times.push({ i, t: now() });
  };
  const loop = (async () => {
    while (shooting) {
      const s = Date.now();
      await shot().catch(() => {});
      const wait = (sc.fast ? 0 : 250) - (Date.now() - s);
      if (wait > 0) await page.waitForTimeout(wait);
    }
  })();

  if (sc.agent) {
    await page.selectOption("#agent-mode", sc.agent).catch(() => {});
    await page.waitForTimeout(400);
  }
  if (sc.hideDemo) await page.addStyleTag({ content: ".badge-demo, .tag-scripted { display: none !important; }" });
  await page.locator("#composer-input").click();
  await page.keyboard.type(sc.prompt, { delay: 35 });
  await page.waitForTimeout(400);
  await page.locator("#btn-send").click();
  marks.send = now();
  await page
    .locator("#btn-stop")
    .waitFor({ state: "visible", timeout: 15000 })
    .catch(() => {});
  await page.locator("#btn-stop").waitFor({ state: "hidden", timeout: 300000 });
  marks.done = now();
  await page.waitForTimeout(1500);

  if (sc.deck) {
    const deck = page.locator("section.deck").last();
    if (await deck.count()) {
      await deck.evaluate((el) =>
        el.scrollIntoView({ block: "center", behavior: "smooth" }),
      );
      await page.waitForTimeout(1200);
      marks.deckShown = now();
      // step through two slides with the real "next" button
      for (let k = 0; k < 2; k++) {
        await deck
          .locator(".deck-next")
          .click()
          .catch(() => {});
        await page.waitForTimeout(900);
      }
      marks.fullOpen = now();
      await deck.locator('button[aria-label="Plein écran"]').click().catch(() => {});
      await page.waitForTimeout(1200);
      const full = page.locator("dialog.deck-dialog");
      marks.fullShown = (await full.count()) ? now() : null;
      for (let k = 0; k < 2; k++) {
        await full
          .locator(".deck-next")
          .click()
          .catch(() => {});
        await page.waitForTimeout(1000);
      }
      await page.waitForTimeout(600);
      await full
        .locator(".deck-close")
        .click()
        .catch(() => {});
      await page.waitForTimeout(800);
      marks.fullClosed = now();
    }
  }
  if (sc.widget) {
    const w = page.locator(sc.widget).last();
    if (await w.count()) {
      await w.evaluate((el) =>
        el.scrollIntoView({ block: "center", behavior: "smooth" }),
      );
      await page.waitForTimeout(2200);
      marks.widgetShown = now();
    }
  }
  if (sc.chart) {
    const ch = page.locator(".chart-cards").last();
    if (await ch.count()) {
      await ch.evaluate((el) =>
        el.scrollIntoView({ block: "center", behavior: "smooth" }),
      );
      await page.waitForTimeout(1800);
      marks.chartShown = now();
    }
  }
  // the compact consumption line under the answer
  const rc = page.locator(".receipt-chip").last();
  if (await rc.count()) {
    await rc.evaluate((el) =>
      el.scrollIntoView({ block: "center", behavior: "smooth" }),
    );
    await page.waitForTimeout(1500);
    marks.receipt = now();
  }
  shooting = false;
  await loop;
  await page.screenshot({ path: path.join(dir, "final.png") });
  await page
    .screenshot({ path: path.join(dir, "final_full.png"), fullPage: true })
    .catch(() => {});
  const answer = await page.evaluate(
    () => document.querySelector("#conversation")?.innerText || "",
  );
  fs.writeFileSync(path.join(dir, "answer.txt"), answer);
  fs.writeFileSync(
    path.join(dir, "timing.json"),
    JSON.stringify({ prompt: sc.prompt, ...marks, frames: times }, null, 1),
  );
  console.log(`${name}${tag || ""}: ${i} frames`, JSON.stringify(marks));
  console.log(answer);
  await browser.close();
}

(async () => {
  const tag = process.env.TAG || "";
  for (const a of process.argv.slice(2)) await run(a, tag);
})();
