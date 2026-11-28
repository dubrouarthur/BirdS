// Deep research UI spec on the demo server (the real research recipe on recorded example pages; no model): the live
// board (sub-questions, sources arriving, graph growing), the cards under the answer, the full-screen report
// (contents, [n] bubble by hover, keyboard and tap, sources tabs, confidence, contradictions), the exports (Word and
// slides through /api/tool, PDF through print), no third-party request, light / dark, 360 px and desktop.
//
//   .venv/bin/python scripts/serve.py --demo --port 9261 &
//   BIRD_URL=http://127.0.0.1:9261/ SHOTS=/tmp/rsshots node scripts/research_ui_smoke.js
//
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
const pw = require("playwright");
const fs = require("fs");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9261/";
const SHOTS = process.env.SHOTS || path.join(process.cwd(), "research-shots");
const ASK = "Fais une recherche approfondie sur la filière hydrogène de la Région Exemple";
const failures = [];
const check = (cond, what) => {
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${what}`);
  if (!cond) failures.push(what);
};

async function shot(page, name, sel) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${name}.png`);
  const el = sel ? page.locator(sel).last() : null;
  if (el && (await el.count())) {
    await el.scrollIntoViewIfNeeded().catch(() => {});
    await el.screenshot({ path: file });
  } else await page.screenshot({ path: file });
  return file;
}

async function run(browser, size, theme) {
  const tag = `${size[0]}-${theme}`;
  console.log(`# ${tag}`);
  const ctx = await browser.newContext({ locale: "fr-FR", colorScheme: theme, ...size[1] });
  const page = await ctx.newPage();
  const errors = [];
  const outside = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("request", (r) => {
    const u = new globalThis.URL(r.url());
    if (!["127.0.0.1", "localhost"].includes(u.hostname) && !u.protocol.startsWith("data")) outside.push(r.url());
  });
  await page.goto(URL);
  await page.locator("#welcome-start").click({ timeout: 5000 }).catch(() => {});
  await page.fill("#composer-input", ASK);
  await page.press("#composer-input", "Enter");

  // ---- the live board
  const seen = { phases: new Set(), reading: false, graphGrew: [], resolved: 0 };
  let liveShot = false;
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(150);
    const b = page.locator(".rsb").last();
    if (!(await b.count())) {
      if (await page.locator("#btn-send:not([hidden])").count()) break;
      continue;
    }
    const st = await b
      .evaluate((el) => ({
        phase: el.dataset.phase,
        reading: !!el.querySelector(".rsb-src.is-reading"),
        nodes: el.querySelectorAll(".gr-live .gr-node").length,
        resolved: el.querySelectorAll(".rsb-q.is-resolved").length,
      }))
      .catch(() => null);
    if (!st) continue;
    seen.phases.add(st.phase);
    seen.reading ||= st.reading;
    if (st.nodes) seen.graphGrew.push(st.nodes);
    seen.resolved = Math.max(seen.resolved, st.resolved);
    if (!liveShot && st.phase === "extract" && st.nodes) {
      await shot(page, `board-live-${tag}`, ".rsb");
      liveShot = true;
    }
  }
  await page.waitForSelector("#btn-send:not([hidden])", { timeout: 60000 });
  await page.waitForTimeout(500);
  check(["search", "read", "extract"].every((p) => seen.phases.has(p)), `${tag}: board went through search, read, extract`);
  check(seen.reading, `${tag}: a source was shown while being read`);
  const grew = [...new Set(seen.graphGrew)];
  check(grew.length >= 2 && grew.at(-1) > grew[0] && grew.at(-1) >= 4, `${tag}: the graph grew during the research (${grew.join(" → ")} nodes)`);
  check(seen.resolved >= 1, `${tag}: a sub-question was marked resolved`);

  // ---- the cards under the answer
  const kinds = await page.locator(".widget.mod").evaluateAll((els) => els.map((e) => e.className.split(" ").pop()));
  check(["mod-research", "mod-graph", "mod-timeline", "mod-matrix", "rp-card"].every((k) => kinds.includes(k)), `${tag}: research, graph, timeline, matrix and report cards (${kinds.join(" ")})`);
  check(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    `${tag}: no horizontal scroll`,
  );
  await shot(page, `card-research-${tag}`, ".mod-research");
  await shot(page, `card-report-${tag}`, ".rp-card");
  await shot(page, `card-graph-${tag}`, ".mod-graph");

  // ---- graph keyboard: Tab to a node, arrows move, Enter selects
  const node = page.locator(".mod-graph .gr-node").first();
  await node.focus();
  await page.keyboard.press("ArrowRight");
  const moved = await page.evaluate(() => document.activeElement?.classList.contains("gr-node"));
  await page.keyboard.press("Enter");
  check(moved && (await page.locator(".mod-graph .gr-node[aria-pressed='true']").count()) === 1, `${tag}: graph nodes reachable by arrows, Enter selects`);

  // ---- the full-screen report
  await page.locator('[data-act="rp-open"]').last().click();
  await page.waitForSelector("dialog.rp[open]");
  check(await page.evaluate(() => document.activeElement?.dataset.act === "rp-close"), `${tag}: focus moves into the report`);
  const toc = await page.locator(".rp-toc a").allTextContents();
  check(toc.includes("Résumé") && toc.includes("Chiffres clés") && toc.includes("Affirmations et niveau de confiance"), `${tag}: contents (${toc.length} entries)`);
  check((await page.locator(".rp-fig").count()) >= 2, `${tag}: key figures`);
  check((await page.locator(".rp-conf.is-high").count()) >= 1 && (await page.locator(".rp-conf.is-low").count()) >= 1, `${tag}: confidence per claim (high and low)`);
  check((await page.locator(".rp-contra li").count()) >= 1, `${tag}: contradiction shown`);
  check((await page.locator(".rp-sec .mod-timeline").count()) === 1 && (await page.locator(".rp-sec .mod-matrix").count()) === 1, `${tag}: timeline and comparison in the report`);
  const sentence = await page.locator(".rp-p").first().textContent();
  check(/\[1\]\./.test(sentence), `${tag}: citation before the final mark (« … [1]. »)`);
  await shot(page, `report-top-${tag}`);

  // bubble: tap / click, then Escape closes it and keeps the dialog open
  const cite = page.locator(".rp-cite").first();
  await cite.click();
  check((await page.locator(".rp-bubble").count()) === 1 && /«/.test(await page.locator(".rp-bubble").textContent()), `${tag}: bubble with the source and its quote`);
  await shot(page, `report-bubble-${tag}`);
  await cite.focus();
  await page.keyboard.press("Escape");
  check((await page.locator(".rp-bubble").count()) === 0 && (await page.locator("dialog.rp[open]").count()) === 1, `${tag}: Escape closes the bubble first`);

  // sources tabs, by keyboard
  await page.locator(".rp-tab").first().focus();
  await page.keyboard.press("ArrowRight");
  check(await page.locator("#rp-tab-other").isVisible(), `${tag}: « Consultées » tab by arrow key`);
  await page.locator(".rp-tab").first().click();

  // contents: a link scrolls to its section
  await page.locator('.rp-toc a[data-toc="claims"]').click();
  await page.waitForTimeout(600);
  await shot(page, `report-claims-${tag}`);
  // a narrower scope (« des transports publics ») is a different figure, not a contradiction: confidence kept
  const scope = page.locator(".rp-claim", { hasText: "transports publics" });
  const scopeText = (await scope.count()) ? await scope.first().textContent() : "";
  check(
    /chiffres différents \(autre périmètre\)/.test(scopeText) && (await scope.first().locator(".rp-conf.is-medium").count()) === 1,
    `${tag}: different scopes shown as « chiffres différents », confidence kept`,
  );
  check(!/\(s\)/.test(await page.locator("dialog.rp").textContent()), `${tag}: no « (s) » plural in the report`);
  if (await scope.count()) {
    await scope.first().scrollIntoViewIfNeeded();
    await scope.first().screenshot({ path: path.join(SHOTS, `report-scope-${tag}.png`) });
  }

  // exports: Word and slides through the office engine; PDF prints the report
  for (const [act, ext] of [["rp-docx", ".docx"], ["rp-pptx", ".pptx"]]) {
    const dl = page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
    await page.locator(`dialog.rp [data-act="${act}"]`).click();
    const got = await dl;
    const name = got ? got.suggestedFilename() : "";
    check(name.endsWith(ext), `${tag}: export ${ext} (${name})`);
    if (got && size[0] === "desk" && theme === "light") await got.saveAs(path.join(SHOTS, `report${ext}`));
  }
  await page.evaluate(() => {
    window.__printed = 0;
    window.print = () => (window.__printed += 1);
  });
  await page.locator('dialog.rp [data-act="rp-pdf"]').click();
  await page.waitForTimeout(150);
  check((await page.evaluate(() => window.__printed)) === 1, `${tag}: PDF prints the report`);
  await page.emulateMedia({ media: "print" });
  await shot(page, `report-print-${tag}`);
  await page.emulateMedia({ media: "screen" });

  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  check((await page.locator("dialog.rp").count()) === 0, `${tag}: Escape closes the report`);
  check(await page.evaluate(() => document.activeElement?.dataset.act === "rp-open"), `${tag}: focus back on « Ouvrir le rapport »`);

  // reload: the cards come back from the saved conversation
  await page.reload();
  await page.waitForTimeout(800);
  check((await page.locator(".rp-card").count()) === 1, `${tag}: report card kept after a reload`);

  check(outside.length === 0, `${tag}: no third-party request (${outside.slice(0, 2).join(" ")})`);
  check(errors.length === 0, `${tag}: no console error (${errors.slice(0, 2).join(" | ")})`);
  await ctx.close();
}

(async () => {
  const browser = await pw.chromium.launch();
  const sizes = [
    ["desk", { viewport: { width: 1280, height: 900 } }],
    ["m360", { viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }],
  ];
  for (const size of sizes) for (const theme of ["light", "dark"]) await run(browser, size, theme);
  await browser.close();
  console.log(failures.length ? `\n${failures.length} failure(s)` : "\nall checks passed");
  process.exit(failures.length ? 1 : 0);
})();
