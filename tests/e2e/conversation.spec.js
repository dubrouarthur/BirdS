// Conversation engine (cluster C1 of the chat audit), on the demo server (recorded answers, no model):
//   BIRD_RATE_LIMIT=0 BIRD_IMG_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --demo --port 9311 &
//   BIRD_URL=http://127.0.0.1:9311/ SHOTS=/tmp/shots node tests/e2e/conversation.spec.js
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`.
// Checks, at 360 px and 1280 px, light and dark: documents in context (R1), an answer that keeps streaming in the
// background (R2), versions « ‹ 1/2 › » for regenerate and edit (R3), editing any question in place and copying it
// (R6), the sidebar menu (R12), delete with undo and the styled « Tout effacer » (R13), search in the messages (R15),
// the back button (R4), « Continuer » (R23). No third-party request, no CSP or script error, no horizontal scroll.
// ONLY=<config part> narrows the configs, PART=<name,name> the parts.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9311/";
const OUT = process.env.SHOTS || path.join(__dirname, "shots");
const ONLY = process.env.ONLY || "";
const PARTS = (process.env.PART || "").split(",").filter(Boolean);
fs.mkdirSync(OUT, { recursive: true });
const CONFIGS = [
  { name: "m360-light", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "light", isMobile: true, hasTouch: true },
  { name: "m360-dark", viewport: { width: 360, height: 780 }, deviceScaleFactor: 2, colorScheme: "dark", isMobile: true, hasTouch: true },
  { name: "desk-light", viewport: { width: 1280, height: 900 }, colorScheme: "light" },
  { name: "desk-dark", viewport: { width: 1280, height: 900 }, colorScheme: "dark" },
];
const DOC = "Compte rendu de la réunion du 12 mars.\nPrésents : Alice, Bruno, Chloé.\nBudget validé : 48 500 euros.\n";

async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]'), null, { timeout: 60000 });
  await page.waitForTimeout(300);
}

async function send(page, text, wait = true) {
  const before = await page.locator(".turn-user").count();
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.fill("#composer-input", text);
    await page.press("#composer-input", "Enter");
    await page.waitForTimeout(900);
    if ((await page.locator(".turn-user").count()) > before) break;
  }
  if (wait) await idle(page);
}

async function newChat(page) {
  const narrow = await page.evaluate(() => innerWidth < 900);
  await page.click(narrow ? "#btn-new-top" : "#btn-new").catch(() => {});
  await page.waitForTimeout(200);
}

async function openDrawer(page) {
  if (await page.evaluate(() => innerWidth < 900 && !document.body.classList.contains("side-open")))
    await page.click("#btn-menu");
  await page.waitForTimeout(250);
}

const PART_FNS = {};
const part = (name, fn) => (PART_FNS[name] = fn);

// ---------------------------------------------------------------- R1: documents in context
part("context", async (page, name, fail, shot) => {
  await newChat(page);
  await page.setInputFiles("#file-input", { name: "compte-rendu.txt", mimeType: "text/plain", buffer: Buffer.from(DOC) });
  await page.waitForSelector(".att-tray .att-card");
  await shot("r1-tray");
  await send(page, "Résume ce document.");
  if (await page.locator(".att-tray").count()) fail("R1: the composer still holds the sent document");
  if (!(await page.locator(".cx-pill").count())) fail("R1: no « document en contexte » pill");
  const pill = (await page.locator(".cx-pill").innerText()).trim();
  if (!/1 document en contexte/.test(pill)) fail(`R1: pill says « ${pill} »`);
  if (!(await page.locator(".turn-user .bubble-files .att-card").count())) fail("R1: the file is not in its message");
  await send(page, "Quelle est la capitale de l'Australie ?");
  const last = page.locator(".turn-bird").last();
  if (await last.locator(".based-on").count()) fail("R1: a general answer says « D'après » the document");
  if (await last.locator('[data-tool="read_file"], .step:has-text("Lecture du document")').count())
    fail("R1: a general question read the document");
  await page.click(".cx-pill");
  await page.waitForSelector(".cx-ctx-pop:not([hidden])");
  await shot("r1-pill-open");
  await page.click(".cx-ctx-name");
  await page.waitForSelector("dialog.cx-preview[open]");
  await page.waitForTimeout(350);
  if (!(await page.locator(".cx-preview-text").innerText()).includes("Budget validé")) fail("R1: the preview shows no text");
  await shot("r1-preview");
  await page.keyboard.press("Escape");
});

// ---------------------------------------------------------------- R2: an answer keeps going in the background
part("background", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Cherche des sources récentes sur le vélo en ville", false);
  await page.waitForSelector('.turn-bird[aria-busy="true"]', { timeout: 10000 });
  await openDrawer(page);
  await page.waitForSelector(".conv .cx-live", { timeout: 5000 }).catch(() => fail("R2: no live mark on the row"));
  await shot("r2-live-row");
  await newChat(page);
  await page.waitForTimeout(400);
  if (!(await page.locator("#btn-send").isVisible())) fail("R2: the new conversation is busy");
  // back to the first conversation while (or after) its answer is written
  await openDrawer(page);
  await page.locator(".conv-open", { hasText: "vélo en ville" }).first().click();
  await idle(page);
  const last = page.locator(".turn-bird").last();
  const text = await last.innerText();
  if (/Réponse interrompue|interrompu/.test(text)) fail("R2: the answer was stopped by the switch");
  if (!(await last.locator(".actions-row").count())) fail("R2: the answer did not finish in its conversation");
  await shot("r2-back");
});

// ---------------------------------------------------------------- R3: regenerate keeps the first answer (« ‹ 1/2 › »)
part("versions", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Écris un mail à mon propriétaire pour signaler une fuite");
  const first = await page.locator(".turn-bird").last().locator(".md").innerText();
  await page.locator('.turn-bird [data-act="regenerate"]').last().click();
  await page.waitForTimeout(500);
  await idle(page);
  const pager = page.locator(".turn-bird .cx-pager").last();
  if ((await pager.getAttribute("data-versions")) !== "2/2") fail("R3: no 2/2 pager after regenerate");
  if (await page.locator(".toast .toast-action").count()) fail("R3: an undo toast is still offered");
  await shot("r3-pager");
  await pager.locator('[data-act="ver-prev"]').click();
  await page.waitForTimeout(300);
  const back = await page.locator(".turn-bird").last().locator(".md").innerText();
  if (back !== first) fail("R3: version 1/2 is not the first answer");
  if ((await page.locator(".turn-bird .cx-pager").last().getAttribute("data-versions")) !== "1/2") fail("R3: pager not at 1/2");
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  if ((await page.locator(".turn-bird .cx-pager").last().getAttribute("data-versions").catch(() => "")) !== "1/2")
    fail("R3: the versions did not survive a reload");
});

// ---------------------------------------------------------------- R6: edit any question in place, copy it
part("edit", async (page, name, fail, shot, ctx) => {
  await newChat(page);
  await page.setInputFiles("#file-input", { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from(DOC) });
  await page.waitForSelector(".att-tray .att-card");
  await send(page, "Résume ce document.");
  await send(page, "Quelle heure est-il à Tokyo ?");
  const firstUser = page.locator(".turn-user").first();
  await firstUser.hover().catch(() => {});
  await firstUser.locator('[data-act="copy-user"]').click();
  await page.waitForSelector('.toast:has-text("Message copié")', { timeout: 3000 }).catch(() => fail("R6: no copy toast"));
  await firstUser.locator('[data-act="edit"]').click();
  await page.waitForSelector(".cx-edit textarea");
  if ((await page.locator(".cx-edit textarea").inputValue()) !== "Résume ce document.") fail("R6: the editor lost the text");
  if (!(await page.locator(".cx-edit-note").count())) fail("R6: no note that the files are kept");
  await shot("r6-editing");
  await page.keyboard.press("Escape");
  if (await page.locator(".cx-edit").count()) fail("R6: Escape did not cancel");
  await page.locator(".turn-user").first().locator('[data-act="edit"]').click();
  await page.fill(".cx-edit textarea", "Fais la liste des présents.");
  await page.click('[data-act="edit-send"]');
  await page.waitForTimeout(500);
  await idle(page);
  if ((await page.locator(".turn-user").count()) !== 1) fail("R6: the edit did not branch from the first question");
  const u = page.locator(".turn-user").first();
  if (!(await u.locator(".bubble-files .att-card").count())) fail("R6: the edited question lost its file");
  if ((await u.locator(".cx-pager").getAttribute("data-versions").catch(() => "")) !== "2/2") fail("R6: no 2/2 on the question");
  await shot("r6-edited");
  await u.locator('[data-act="ver-prev"]').click();
  await page.waitForTimeout(300);
  if ((await page.locator(".turn-user").count()) !== 2) fail("R6: version 1/2 did not bring the old tail back");
  if (!(await page.locator(".turn-user").last().innerText()).includes("Tokyo")) fail("R6: the old follow-up is missing");
});

// ---------------------------------------------------------------- R23: « Continuer » after Stop
part("continue", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Explique-moi le compostage en détail", false);
  await page.waitForFunction(() => (document.querySelector(".turn-bird .md")?.innerText || "").length > 20, null, { timeout: 15000 });
  await page.click("#btn-stop");
  await idle(page);
  const partial = (await page.locator(".turn-bird").last().locator(".md").innerText()).trim();
  if (await page.locator('[data-act="restart"]').count()) fail("R23: « Relancer » still shown beside « Régénérer »");
  if (!(await page.locator('[data-act="continue"]').count())) fail("R23: no « Continuer »");
  await shot("r23-stopped");
  await page.click('[data-act="continue"]');
  await page.waitForTimeout(400);
  await idle(page);
  if ((await page.locator(".turn-bird").count()) !== 1 || (await page.locator(".turn-user").count()) !== 1)
    fail("R23: « Continuer » added a turn");
  const full = (await page.locator(".turn-bird").last().locator(".md").innerText()).trim();
  if (!full.startsWith(partial.slice(0, Math.min(40, partial.length))) || full.length <= partial.length)
    fail("R23: the answer did not continue from where it stopped");
  if (full.indexOf(partial.slice(0, 20), 1) > 0) fail("R23: the continued answer repeats its beginning");
  if (await page.locator(".turn-bird .stopped").count()) fail("R23: still marked as stopped");
  await shot("r23-continued");
});

// ---------------------------------------------------------------- R22: a failed turn stays retryable
part("retry", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Simule une panne");
  if (!(await page.locator(".notice-error").count())) fail("R22: the demo failure did not show");
  await send(page, "Bonjour");
  const failed = page.locator(".turn-bird").first();
  if (!(await failed.locator('[data-act="retry"]').count())) fail("R22: the failed turn lost « Réessayer » after a new message");
  await shot("r22-failed");
  await failed.locator('[data-act="retry"]').click();
  await page.waitForTimeout(300);
  if (await page.locator(".toast .toast-action").count()) fail("R22: retry offers an undo");
  await idle(page);
  if ((await page.locator(".turn-bird .cx-pager").first().getAttribute("data-versions").catch(() => "")) !== "2/2")
    fail("R22: the retry is not a new version");
  await page.locator('.turn-bird [data-act="ver-prev"]').first().click();
  await page.waitForTimeout(300);
  if (!(await page.locator(".turn-user").last().innerText()).includes("Bonjour")) fail("R22: the later exchange is lost");
});

// ---------------------------------------------------------------- R12: the sidebar row menu
part("menu", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Bonjour");
  await openDrawer(page);
  const row = page.locator(".conv.is-current");
  await row.locator(".conv-more").click();
  await page.waitForTimeout(150);
  if ((await row.locator(".conv-menu").getAttribute("role")) !== "menu") fail("R12: the row menu is not a menu");
  if (!(await page.evaluate(() => document.activeElement?.getAttribute("role") === "menuitem"))) fail("R12: focus is not on the first item");
  await shot("r12-menu");
  await page.keyboard.press("ArrowDown");
  if (!(await page.evaluate(() => document.activeElement?.dataset.convAct === "export"))) fail("R12: arrow keys do not move");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(100);
  if (await page.locator(".conv-menu").count()) fail("R12: Escape did not close the menu");
  if (!(await page.evaluate(() => document.activeElement?.classList.contains("conv-more")))) fail("R12: focus did not go back to « … »");
  await page.locator(".conv.is-current .conv-more").click();
  await page.mouse.click(5, 5);
  await page.waitForTimeout(150);
  if (await page.locator(".conv-menu").count()) fail("R12: an outside click did not close the menu");
  await page.locator(".conv.is-current .conv-more").click();
  await page.locator('[data-conv-act="rename"]').click();
  await page.fill(".rename", "Salutations");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  if (!(await page.evaluate(() => document.activeElement?.classList.contains("conv-open")))) fail("R12: focus lost after rename");
  if (!(await page.locator(".conv.is-current .conv-title").innerText()).includes("Salutations")) fail("R12: not renamed");
  await page.locator(".conv.is-current .conv-more").click();
  await page.locator('[data-conv-act="rename"]').click();
  await page.waitForSelector(".rename:focus");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  if (!(await page.evaluate(() => document.activeElement?.classList.contains("conv-more")))) fail("R12: focus lost after a cancelled rename");
});

// ---------------------------------------------------------------- R13: delete with undo, styled « Tout effacer »
part("delete", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Quelle heure est-il à Tokyo ?");
  await openDrawer(page);
  const before = await page.locator(".conv").count();
  await page.locator(".conv.is-current .conv-more").click();
  await page.locator('[data-conv-act="delete"]').click();
  await page.waitForTimeout(200);
  if ((await page.locator(".conv").count()) !== before - 1) fail("R13: not deleted at once");
  const undo = page.locator(".toast .toast-action");
  if (!(await undo.count())) fail("R13: no « Annuler » toast");
  await shot("r13-undo-toast");
  await undo.first().click();
  await page.waitForTimeout(300);
  if ((await page.locator(".conv").count()) !== before) fail("R13: « Annuler » did not bring it back");
  if (!(await page.locator(".turn-user").count())) fail("R13: the restored conversation is not shown");
  await openDrawer(page);
  await page.click("#btn-clear");
  await page.waitForSelector("dialog.cx-confirm[open]");
  await page.waitForTimeout(300);
  if (!(await page.evaluate(() => document.activeElement?.dataset.act === "confirm-cancel"))) fail("R13: the safe answer is not focused");
  await shot("r13-clear-dialog");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  if ((await page.locator(".conv").count()) !== before) fail("R13: Escape cleared the conversations");
});

// ---------------------------------------------------------------- R15: search in the messages
part("search", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Écris un mail à mon propriétaire pour signaler une fuite");
  await openDrawer(page);
  // R14: the title comes from the result (the mail's subject), not the first words of the question
  await page.waitForFunction(() => /Votre offre/.test(document.querySelector(".conv.is-current .conv-title")?.textContent || ""), null, { timeout: 5000 })
    .catch(() => fail("R14: the mail's subject did not become the title"));
  await page.fill("#conv-search", "Camille"); // in the answer only, not in the title
  await page.waitForTimeout(200);
  const row = page.locator(".conv").first();
  if (!(await row.count())) fail("R15: a word of the answer finds nothing");
  else if (!(await row.locator(".cx-snippet mark").innerText().catch(() => "")).match(/Camille/i)) fail("R15: no snippet");
  await shot("r15-search");
  await page.fill("#conv-search", "fuíte"); // accents ignored, in the title
  await page.waitForTimeout(150);
  if (!(await page.locator(".conv").count())) fail("R15: accents are not ignored");
  await page.fill("#conv-search", "");
});

// ---------------------------------------------------------------- R16: « Livrables » lists decks, documents, mails
part("deliverables", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Fais une présentation de 3 diapositives sur le vélo en ville");
  await page.evaluate(() => document.querySelector('.cv-panel [data-act="close"], .cv-close')?.click());
  await send(page, "Écris un mail à mon propriétaire pour signaler une fuite");
  const btn = page.locator("#btn-deliverables");
  if (!(await btn.isVisible())) {
    fail("R16: no « Livrables » button for a deck and a mail");
    return;
  }
  await btn.click();
  await page.waitForSelector("#deliverables[open] .deliv-item");
  await page.waitForTimeout(300);
  const text = await page.locator("#deliverables-body").innerText();
  if (!/Présentation/.test(text)) fail("R16: the canvas deck is not listed");
  if (!/Brouillon de mail/.test(text)) fail("R16: the mail draft is not listed");
  await shot("r16-deliverables");
  await page.locator('#deliverables [data-deliv="open"]').first().click();
  await page.waitForTimeout(400);
  if (!(await page.evaluate(() => !!document.querySelector(".cv-panel:not([hidden]), #canvas:not([hidden])")))) fail("R16: « Ouvrir » did not open the canvas");
});

// ---------------------------------------------------------------- R4: back closes the open layer, never the app
part("back", async (page, name, fail, shot) => {
  await newChat(page);
  await send(page, "Bonjour");
  const narrow = await page.evaluate(() => innerWidth < 900);
  const stillHere = async (what) => {
    if (!page.url().startsWith(URL)) fail(`R4: back after ${what} left the app (${page.url()})`);
  };
  if (narrow) {
    await page.click("#btn-menu");
    await page.waitForTimeout(250);
    await page.goBack({ waitUntil: "commit" }).catch(() => {});
    await page.waitForTimeout(350);
    await stillHere("the drawer");
    if (await page.evaluate(() => document.body.classList.contains("side-open"))) fail("R4: back did not close the drawer");
    await shot("r4-drawer-closed");
  }
  await page.evaluate(() => document.querySelector("#btn-model")?.click());
  await page.waitForTimeout(300);
  if (await page.locator("#view-settings").isHidden()) fail("R4: Settings did not open");
  await page.goBack({ waitUntil: "commit" }).catch(() => {});
  await page.waitForTimeout(350);
  await stillHere("Settings");
  if (!(await page.locator("#view-settings").isHidden())) fail("R4: back did not return from Settings");
  await send(page, "Fais une présentation de 3 diapositives sur le vélo en ville");
  await page.waitForTimeout(400);
  if (await page.evaluate(() => document.documentElement.classList.contains("cv-open"))) {
    await page.goBack({ waitUntil: "commit" }).catch(() => {});
    await page.waitForTimeout(350);
    await stillHere("the canvas");
    if (await page.evaluate(() => document.documentElement.classList.contains("cv-open"))) fail("R4: back did not close the canvas");
  } else fail("R4: the canvas did not open for the deck");
  await page.click("#btn-deliverables").catch(() => {});
  await page.waitForTimeout(300);
  if (await page.locator("#deliverables[open]").count()) {
    await page.goBack({ waitUntil: "commit" }).catch(() => {});
    await page.waitForTimeout(350);
    await stillHere("Livrables");
    if (await page.locator("#deliverables[open]").count()) fail("R4: back did not close the dialog");
  }
  await shot("r4-after-backs");
});

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const cfg of CONFIGS) {
    if (ONLY && !cfg.name.includes(ONLY)) continue;
    const { name, ...opts } = cfg;
    const ctx = await browser.newContext({ ...opts, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const page = await ctx.newPage();
    page.on("request", (r) => {
      const u = r.url();
      if (!u.startsWith("http://127.0.0.1") && !u.startsWith("data:") && !u.startsWith("blob:"))
        problems.push(`${name}: third-party request ${u}`);
    });
    page.on("console", (m) => {
      if (m.type() === "error" || /Content Security Policy|Refused/.test(m.text()))
        problems.push(`${name}: console ${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`${name}: pageerror ${e.message}`));
    page.on("dialog", (d) => (problems.push(`${name}: native dialog « ${d.message()} »`), d.dismiss()));
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await page.evaluate(() => document.querySelector("dialog[open]")?.close());
    for (const [pname, fn] of Object.entries(PART_FNS)) {
      if (PARTS.length && !PARTS.includes(pname)) continue;
      const fail = (msg) => problems.push(`${name}/${pname}: ${msg}`);
      const shot = async (label) => {
        const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
        if (sw > cw + 1) fail(`horizontal scroll ${sw} > ${cw} at ${label}`);
        await page.screenshot({ path: path.join(OUT, `${label}-${name}.png`) });
      };
      try {
        await fn(page, name, fail, shot, ctx);
      } catch (e) {
        fail(`threw ${e.message.split("\n")[0]}`);
        await page.screenshot({ path: path.join(OUT, `FAIL-${pname}-${name}.png`) }).catch(() => {});
      }
    }
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log("ok: conversation engine; no third-party request, no CSP error, no native dialog, no overflow");
})();
