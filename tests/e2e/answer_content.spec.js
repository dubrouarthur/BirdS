// Answer content in the browser (chat audit, cluster C2), on the demo server with a conversation recorded from
// production (tests/fixtures/answer_content.json: real answers of the audit, the entity picture pointed at an
// unsigned /api/img link, the mail draft as the server now sends it):
//   BIRD_RATE_LIMIT=0 BIRD_IMG_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9361 &
//   BIRD_URL=http://127.0.0.1:9361/ SHOTS=/tmp/shots node tests/e2e/answer_content.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks: math typeset by the self-hosted KaTeX (no raw \[ … \], copy gives the TeX), human tool labels and no tick
// on « 0 sur 2 faites », « Syntaxe Python valide », the entity picture's slot gone when it fails, the mail card's
// « adresse à ajouter », inline citations with their bubble and the « N sources » pill, rich copy (text/html with a
// real table), thumbs-down reasons, one work line before a short answer; no third-party request, no CSP or script
// error, no horizontal scroll. Screenshots at 360 px and 1280 px, light and dark (look at them). ONLY=<config>.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9361/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
const BASE = process.env.BASE === "1"; // the branch before the fixes: screenshots only, no checks
fs.mkdirSync(OUT, { recursive: true });
const FIXTURE = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "answer_content.json"), "utf8"));
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
];

/** The recorded conversation, stored the way app.js stores one, opened as the current conversation. */
function seed(fixture) {
  const id = "cac2fixture01";
  const now = Date.now();
  const conv = { id, title: fixture.title, created: now - 60000, updated: now, turns: fixture.turns, attachments: [], canvas: { list: {}, active: null }, lang: "fr" };
  localStorage.setItem(`bird.conv.${id}`, JSON.stringify(conv));
  localStorage.setItem("bird.convs", JSON.stringify([{ id, title: fixture.title, created: conv.created, updated: now, n: fixture.turns.length }]));
  localStorage.setItem("bird.current", id);
  localStorage.setItem("bird.prefs", JSON.stringify({ lang: "fr", theme: "system", thinking: true, thinkingV: 2, mode: "", endpoint: "", token: "", model: "", access: "", welcomed: true }));
}

const birds = (page) => page.locator(".turn-bird");

async function shot(page, el, file) {
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const box = await el.boundingBox();
  const vp = page.viewportSize();
  const top = Math.max(0, box.y - 12);
  await page.screenshot({ path: path.join(OUT, file), clip: { x: 0, y: top, width: vp.width, height: Math.min(vp.height - top, Math.max(box.height + 24, 200)) } });
}

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  let checks = 0;
  const check = (ok, msg) => {
    checks += 1;
    if (!ok && !BASE) problems.push(msg);
  };
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris", permissions: ["clipboard-read", "clipboard-write"] });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (!u.startsWith("http://127.0.0.1") && !u.startsWith("data:") && !u.startsWith("blob:")) problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      const text = m.text();
      // the unsigned entity picture is refused by the proxy on purpose (403): that one error is expected
      if (/Failed to load resource.*(403|502)/.test(text)) return;
      if (m.type() === "error" || /Content Security Policy|Refused/.test(text)) problems.push(`${name}: console ${m.type()}: ${text}`);
    });
    page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.evaluate(seed, FIXTURE);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    await page.evaluate(() => document.querySelector("dialog[open]")?.close());
    const n = await birds(page).count();
    check(n === 7, `${name}: ${n} answers drawn`);

    // ---- R9 math: the photosynthesis answer (third), typeset; no raw \[ left; copy gives the TeX
    const photo = birds(page).nth(2);
    await photo.locator(".md-math").first().waitFor({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(800);
    const math = await photo.locator(".md-math").count();
    const typeset = await photo.locator('.md-math[data-typeset="1"] .katex').count();
    check(math >= 1 && typeset === math, `${name}: math ${typeset}/${math} typeset`);
    const rawLeft = await photo.locator(".md").evaluate((md) => {
      const copy = md.cloneNode(true);
      copy.querySelectorAll(".md-math").forEach((m) => m.remove());
      return /\\\[|\\xrightarrow|C_6H_\{12\}/.test(copy.textContent);
    });
    check(!rawLeft, `${name}: raw TeX left in the answer`);
    if (math) {
      const block = photo.locator(".md-math--block").first();
      if (await block.count()) {
        await shot(page, block, `math-${name}.png`);
        const styled = await block.evaluate((b) => [...b.querySelectorAll(".katex-html [style]")].length);
        check(styled > 0, `${name}: KaTeX layout styles not applied (CSSOM)`);
        await block.locator("[data-copy-tex]").click();
        await page.waitForTimeout(200);
        const clip = await page.evaluate(() => navigator.clipboard.readText()).catch(() => "");
        check(/^\$\$[\s\S]*C_6H_\{12\}O_6[\s\S]*\$\$$/.test(clip), `${name}: TeX copy gave « ${clip.slice(0, 60)} »`);
      }
    }
    // the same place in the answer, typeset or (base) raw: the paragraph or block holding the global equation
    const eq = photo.locator(".md-math--block, .md p:has-text('\\[')").first();
    if (await eq.count()) await shot(page, eq, `math-${name}.png`);

    // ---- R27 citations: the [1] the harness added (backed by the entity card), its bubble, the « 1 source » pill
    const artemis = birds(page).nth(1);
    const cite = artemis.locator("sup.cite > a").first();
    check((await cite.count()) === 1, `${name}: no inline citation`);
    const pill = artemis.locator(".src-pill");
    check((await pill.count()) === 1 && /1 source/.test(await pill.innerText().catch(() => "")), `${name}: no « 1 source » pill`);
    if (await pill.count()) {
      check(await artemis.locator(".src-panel").isHidden(), `${name}: sources panel open by itself`);
      await shot(page, pill, `sources-pill-${name}.png`);
    }
    if (await cite.count()) {
      await cite.scrollIntoViewIfNeeded();
      if (opts.hasTouch) await cite.tap();
      else await cite.hover();
      await page.waitForTimeout(300);
      const bub = page.locator(".cite-bubble");
      check((await bub.count()) === 1 && /wikipedia/i.test(await bub.innerText().catch(() => "")), `${name}: no citation bubble`);
      check((await cite.getAttribute("aria-describedby")) === (await bub.getAttribute("id").catch(() => "")), `${name}: bubble not tied to its mark`);
      const box = await bub.boundingBox().catch(() => null);
      const vp = page.viewportSize();
      check(box && box.x >= 0 && box.x + box.width <= vp.width, `${name}: bubble outside the screen`);
      await page.screenshot({ path: path.join(OUT, `cite-bubble-${name}.png`), clip: { x: 0, y: Math.max(0, (box?.y || 0) - 40), width: vp.width, height: Math.min(260, vp.height) } });
      if (await bub.count()) await bub.locator(".cite-bubble-all").click();
      await page.waitForTimeout(400);
      check(await artemis.locator(".src-panel").isVisible(), `${name}: « Voir toutes les sources » did not open the panel`);
      check((await page.locator(".cite-bubble").count()) === 0, `${name}: bubble stayed open`);
      check((await page.evaluate(() => document.activeElement?.className || "")).includes("source-card"), `${name}: focus not on the source`);
      if (await artemis.locator(".sources").count()) await shot(page, artemis.locator(".sources"), `sources-open-${name}.png`);
      // keyboard: focus shows the bubble, Escape closes it and keeps the focus on the mark
      await cite.focus();
      await page.waitForTimeout(150);
      check((await page.locator(".cite-bubble").count()) === 1, `${name}: focus shows no bubble`);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(150);
      check((await page.locator(".cite-bubble").count()) === 0, `${name}: Escape did not close the bubble`);
    }

    // ---- R11 rich copy: the Révolution answer (headings, a table, code) as text/html with one real table
    const revo = birds(page).nth(6);
    const copyBtn = revo.locator('[data-act="copy"]');
    await copyBtn.scrollIntoViewIfNeeded();
    await copyBtn.click();
    await page.waitForTimeout(300);
    const flavours = await page.evaluate(async () => {
      try {
        const items = await navigator.clipboard.read();
        const out = {};
        for (const type of items[0].types) out[type] = await (await items[0].getType(type)).text();
        return out;
      } catch (e) {
        return { error: String(e) };
      }
    });
    const html = flavours["text/html"] || "";
    check((html.match(/<table/g) || []).length === 1 && /<thead><tr><th[^>]*>[^<]+<\/th><th/.test(html), `${name}: copied HTML has no real table (${html.slice(0, 80)})`);
    check(/<h\d>/.test(html) && !/<button|class=|<svg/.test(html), `${name}: copied HTML keeps chrome or lost headings`);
    check(/\| --- \|/.test(flavours["text/plain"] || ""), `${name}: plain text has no table`);
    check(!/Copier|Télécharger|Retour à la ligne/.test(flavours["text/plain"] || ""), `${name}: plain text carries buttons' words`);
    check(await copyBtn.evaluate((b) => b.classList.contains("is-copied") && b.getAttribute("aria-label") === "Copié"), `${name}: copy button did not say « Copié »`);
    check((await page.locator(".toast", { hasText: /^Copié$/ }).count()) === 0, `${name}: a toast instead of the icon`);
    await shot(page, revo.locator(".actions-row"), `copied-${name}.png`);
    await page.waitForTimeout(2200);
    check(!(await copyBtn.evaluate((b) => b.classList.contains("is-copied"))), `${name}: « Copié » did not go back after 2 s`);

    // ---- R8: the code badge says what was checked
    const badge = revo.locator(".code-check--ok").first();
    check((await badge.count()) === 1 && (await badge.innerText()).trim() === "Syntaxe Python valide", `${name}: badge « ${await badge.innerText().catch(() => "")} »`);
    if (await badge.count()) await shot(page, badge.locator("xpath=ancestor::figure[1]").locator(".code-head"), `badge-${name}.png`);

    // ---- R10: human tool labels, no tick on « 0 sur 2 faites »
    const names = await page.locator(".steps-names").allInnerTexts();
    check(!names.some((x) => /\b[a-z]+_[a-z_]+\b/.test(x)), `${name}: tool id in the steps line: ${names.join(" / ")}`);
    check(names.some((x) => /Fiche encyclopédique/.test(x)), `${name}: no « Fiche encyclopédique » label`);
    const failed = birds(page).nth(3).locator(".tplan").first();
    if (await failed.count()) {
      check(/0 sur 2 faites/.test(await failed.innerText()), `${name}: plan count`);
      const tick = await failed.locator(":scope > summary .tplan-head-icon").evaluate((el) => el.closest("summary") && el.innerHTML).catch(() => "");
      check(!/M4\.5 10\.5l3\.5 3\.5/.test(tick || ""), `${name}: green check on « 0 sur 2 faites »`);
      await shot(page, failed, `plan-${name}.png`);
    }

    // ---- R7: the entity picture the proxy refused leaves no broken image, no alt text, no credit
    const ent = birds(page).nth(1).locator(".od-ent");
    if (await ent.count()) {
      await ent.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
      check((await ent.locator("img").count()) === 0 && (await ent.getAttribute("data-img")) === "failed", `${name}: broken entity picture still shown`);
      check((await birds(page).nth(1).locator(".od-credit").count()) === 0, `${name}: credit of a picture not shown`);
      await shot(page, ent.locator("xpath=ancestor::section[1]"), `entity-${name}.png`);
    }

    // ---- R20: the mail card's « À » is empty with the designed hint
    const mail = birds(page).nth(5).locator(".email-card");
    check((await mail.locator(".email-missing").count()) === 1 && !/@/.test(await mail.locator(".card-meta").innerText()), `${name}: mail recipient`);
    await shot(page, mail.locator(".card-head"), `mail-${name}.png`);

    // ---- R26: thumbs down opens reasons and a comment; « Envoyer » stores them in this browser and says thanks
    const summary = birds(page).nth(0);
    const down = summary.locator('[data-act="down"]');
    await down.scrollIntoViewIfNeeded();
    await down.click();
    await page.waitForTimeout(300);
    const panel = summary.locator(".fb-panel");
    check((await panel.count()) === 1 && (await panel.locator(".fb-chip").count()) === 6, `${name}: no reasons panel`);
    if (await panel.count()) {
      check((await page.evaluate(() => document.activeElement?.className || "")).includes("fb-chip"), `${name}: focus not on the first reason`);
      await panel.locator('.fb-chip[data-reason="wrong"]').click();
      await panel.locator('.fb-chip[data-reason="long"]').click();
      await panel.locator(".fb-comment").fill("La date de la Bastille est fausse.");
      await shot(page, panel, `feedback-${name}.png`);
      await panel.locator('[data-act="fb-send"]').click();
      await page.waitForTimeout(300);
      check((await summary.locator(".fb-thanks").count()) === 1 && (await summary.locator(".fb-panel").count()) === 0, `${name}: no thank-you`);
      await shot(page, summary.locator(".actions-row"), `feedback-thanks-${name}.png`);
      const saved = await page.evaluate(() => {
        const conv = JSON.parse(localStorage.getItem("bird.conv.cac2fixture01") || "{}");
        return conv.turns?.[1]?.feedbackDetail || null;
      });
      check(saved && saved.reasons.join() === "wrong,long" && /Bastille/.test(saved.comment), `${name}: feedback not stored (${JSON.stringify(saved)})`);
      // taking the thumbs down back drops what was said
      await summary.locator('[data-act="down"]').click();
      await page.waitForTimeout(300);
      const after = await page.evaluate(() => JSON.parse(localStorage.getItem("bird.conv.cac2fixture01")).turns[1].feedbackDetail ?? null);
      check(after === null, `${name}: feedback kept after the thumbs down was taken back`);
    }

    const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    check(sw <= cw + 1, `${name}: horizontal scroll ${sw} > ${cw}`);

    // ---- R9: the math renderer's licence in « À propos » (the site under /a-propos/), served by Bird itself
    if (name.startsWith("desk")) {
      await page.goto(new globalThis.URL("/a-propos/", URL).href, { waitUntil: "networkidle" });
      const oss = page.locator(".footer-oss");
      check((await oss.count()) === 1 && /KaTeX[\s\S]*MIT/.test(await oss.innerText().catch(() => "")), `${name}: no KaTeX licence in À propos`);
      if (await oss.count()) {
        const href = await oss.locator("a").first().evaluate((a) => a.href);
        const status = await page.evaluate((u) => fetch(u).then((r) => r.status), href);
        check(new globalThis.URL(href).pathname === "/static/vendor/katex/LICENSE.txt" && status === 200, `${name}: licence link ${href} ${status}`);
        await shot(page, oss, `about-oss-${name}.png`);
      }
    }
    await ctx.close();
  }
  await browser.close();
  console.log(problems.length ? problems.join("\n") : `ok: ${checks} checks, 0 problems${BASE ? " (base: screenshots only)" : ""}`);
  process.exit(problems.length ? 1 : 0);
})();
