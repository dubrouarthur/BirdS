// Small modules UI smoke test on the demo server (the real research recipe on recorded example pages, the real
// calculator, the user's own modules; no model): rendering, keyboard, chips, transforms, screenshots.
//
//   .venv/bin/python scripts/serve.py --demo --port 9245 &
//   BIRD_URL=http://127.0.0.1:9245/ SHOTS=/tmp/modshots node scripts/modules_ui_smoke.js
//
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const pw = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9245/";
const SHOTS = process.env.SHOTS || path.join(process.cwd(), "modules-shots");
const failures = [];
const check = (cond, what) => {
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${what}`);
  if (!cond) failures.push(what);
};

const ASKS = {
  research:
    "Fais une recherche approfondie sur la filière hydrogène de la Région Exemple",
  calc: "mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %",
  matrix:
    "Compare ces offres :\n| Offre | Prix mensuel | Délai | Note |\n|---|---|---|---|\n| Alpha | 120 € | 4 h | 4,5 |\n| Beta | 95 € | 8 h | 4,1 |\n| Gamma | 140 € | 2 h | 4,8 |",
  timeline:
    "Fais une frise chronologique : 2015 création à Lyon, 2018 premier client export, 2021 levée de fonds, 2024 ouverture de Lille",
  checklist:
    "Transforme en liste de tâches :\n- appeler le fournisseur\n- envoyer le devis\n- relancer Paul\n- réserver la salle",
  weather: "météo à Lyon demain",
};

async function open(browser, opts) {
  const ctx = await browser.newContext({ locale: "fr-FR", ...opts });
  const page = await ctx.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && page.errors.push(m.text()));
  await page.goto(URL);
  await page
    .locator("#welcome-start")
    .click({ timeout: 6000 })
    .catch(() => {});
  await page.waitForTimeout(200);
  return { ctx, page };
}

async function ask(page, text) {
  await page.fill("#composer-input", text);
  await page.press("#composer-input", "Enter");
  await page.waitForTimeout(400);
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForTimeout(500);
}

async function shot(page, name, sel) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${name}.png`);
  const el = sel ? page.locator(sel).last() : null;
  if (el && (await el.count())) {
    await el.scrollIntoViewIfNeeded();
    await el.screenshot({ path: file });
  } else await page.screenshot({ path: file, fullPage: false });
  return file;
}

async function noHScroll(page) {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
}

(async () => {
  const browser = await pw.chromium.launch();
  const sizes = [
    ["desk", { viewport: { width: 1280, height: 900 } }],
    [
      "phone",
      {
        viewport: { width: 360, height: 780 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
    ],
  ];
  for (const [size, opts] of sizes)
    for (const scheme of ["light", "dark"]) {
      const tag = `${size}-${scheme}`;
      console.log(`# ${tag}`);
      const { ctx, page } = await open(browser, {
        ...opts,
        colorScheme: scheme,
      });
      // ---- deep research: team board, research card, graph, timeline
      await ask(page, ASKS.research);
      check(
        (await page.locator(".mod-research").count()) === 1,
        `${tag} research card`,
      );
      check(
        (await page.locator(".rs-source").count()) === 3,
        `${tag} three sources read`,
      );
      check(
        (await page.locator(".gr-node").count()) >= 4,
        `${tag} graph nodes`,
      );
      check(
        (await page.locator(".tl-item").count()) >= 3,
        `${tag} timeline from dated claims`,
      );
      const answer = await page.locator(".md").last().innerText();
      check(
        !/3\s?000 emplois/.test(answer),
        `${tag} invented figure removed from the report`,
      );
      check(
        /40\s?millions d.euros \[1\]|40 millions d’euros/.test(answer) ||
          answer.includes("40"),
        `${tag} report kept`,
      );
      await shot(page, `${tag}-research-board`, ".crew");
      await shot(page, `${tag}-research-card`, ".mod-research");
      // keyboard: focus a node, Enter, the panel lists its sources
      await page.locator(".gr-node").first().focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(150);
      check(
        (await page
          .locator(".gr-panel .gr-links li, .gr-panel .gr-claims li")
          .count()) > 0,
        `${tag} node panel (keyboard)`,
      );
      check(
        (await page.locator('.gr-node[aria-pressed="true"]').count()) === 1,
        `${tag} node aria-pressed`,
      );
      await page.locator('[data-act="gr-zoom-in"]').last().click();
      await shot(page, `${tag}-graph`, ".mod-graph");
      await page.locator(".gr-filter").first().click();
      check(
        (await page.locator(".gr-node.is-hidden").count()) > 0,
        `${tag} type filter hides nodes`,
      );
      await page.locator(".gr-filter").first().click();
      await page.locator(".gr-list summary").last().click();
      check(
        (await page.locator(".gr-list li").count()) >= 3,
        `${tag} list fallback`,
      );
      await shot(page, `${tag}-timeline`, ".mod-timeline");
      const chips = await page.locator(".chips-row .mchip").allInnerTexts();
      check(
        chips.some((c) => c.startsWith("Approfondir")),
        `${tag} research chips: ${chips.join(" | ")}`,
      );
      check(await noHScroll(page), `${tag} no horizontal scroll (research)`);
      // ---- calculator
      await ask(page, ASKS.calc);
      check(
        (await page.locator(".mod-calc").count()) === 1,
        `${tag} calculator card`,
      );
      const main = await page
        .locator(".mod-calc .calc-row.is-main dd")
        .last()
        .innerText();
      check(
        /1\s?159,92/.test(main.replace(/ /g, " ")),
        `${tag} exact monthly payment (${main})`,
      );
      await page.locator(".mod-calc .calc-in").nth(1).fill("25");
      const after = await page
        .locator(".mod-calc .calc-row.is-main dd")
        .last()
        .innerText();
      check(
        /1\s?001,25/.test(after.replace(/ /g, " ")),
        `${tag} recomputed over 25 years (${after})`,
      );
      await shot(page, `${tag}-calc`, ".mod-calc");
      // ---- matrix: sortable, best marked
      await ask(page, ASKS.matrix);
      check(
        (await page.locator(".mod-matrix .is-best").count()) === 3,
        `${tag} best values marked`,
      );
      await page.locator(".mod-matrix .mx-sort").nth(1).click();
      const first = await page
        .locator(".mod-matrix tbody tr")
        .first()
        .locator("th")
        .innerText();
      check(first.startsWith("Beta"), `${tag} sorted by price (${first})`);
      check(
        (await page
          .locator('.mod-matrix th[aria-sort="ascending"]')
          .count()) === 1,
        `${tag} aria-sort`,
      );
      await shot(page, `${tag}-matrix`, ".mod-matrix");
      // ---- timeline from the user's dates
      await ask(page, ASKS.timeline);
      check(
        (await page
          .locator(".mod-timeline")
          .last()
          .locator(".tl-item")
          .count()) === 4,
        `${tag} user timeline`,
      );
      // ---- checklist: tick, saved
      await ask(page, ASKS.checklist);
      await page.locator(".mod-check .chk-box").first().check();
      check(
        (await page.locator(".mod-check .chk-item.is-done").count()) === 1,
        `${tag} tick`,
      );
      check(
        (
          await page.locator(".mod-check .ck-progress").last().innerText()
        ).startsWith("1 sur 4"),
        `${tag} progress`,
      );
      await shot(page, `${tag}-checklist`, ".mod-check");
      // ---- weather: follow-up chips; transforms in the menu
      await ask(page, ASKS.weather);
      const wchips = await page.locator(".chips-row .mchip").allInnerTexts();
      check(
        wchips.includes("Et après-demain ?"),
        `${tag} weather chips: ${wchips.join(" | ")}`,
      );
      await shot(
        page,
        `${tag}-chips`,
        ".turn:last-child, .assistant:last-of-type",
      );
      await page.locator('[data-act="more"]').last().click();
      check(
        (await page.locator('[data-act^="tf-"]').count()) === 6,
        `${tag} six transforms in the menu`,
      );
      await page.keyboard.press("Escape");
      check(await noHScroll(page), `${tag} no horizontal scroll (end)`);
      check(
        page.errors.length === 0,
        `${tag} no page error ${page.errors.join(" | ")}`,
      );
      await ctx.close();
    }
  await browser.close();
  console.log(
    failures.length ? `\n${failures.length} failure(s)` : "\nall checks passed",
  );
  process.exit(failures.length ? 1 : 0);
})();
