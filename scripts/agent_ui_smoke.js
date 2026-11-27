// Mode Agent UI smoke test on the demo server (scripted team, no model): focus, screen-reader announcements,
// lane timers, failure and connection-loss states, a stalled stream, and the phone layouts.
//
//   .venv/bin/python scripts/serve.py --demo --port 9231 &
//   BIRD_URL=http://127.0.0.1:9231/ SHOTS=/tmp/agentui node scripts/agent_ui_smoke.js [scenario ...]
//
// Uses the preinstalled Playwright (require('playwright')); never run `playwright install`. WebKit and Firefox are
// used when they launch; otherwise the phones are emulated with Chromium device descriptors (said in the output).
// SOFT=1 records the failed checks without stopping (to measure the state before a fix).
const pw = require("playwright");
const fs = require("fs");
const http = require("http");
const path = require("path");

const URL = process.env.BIRD_URL || "http://127.0.0.1:9231/";
const SHOTS = process.env.SHOTS || path.join(process.cwd(), "agentui-shots");
const SOFT = !!process.env.SOFT;
const DECK =
  "Fais une présentation avec des chiffres sur le télétravail depuis 2019";
const failures = [];

function check(cond, what) {
  if (cond) return console.log(`  ok    ${what}`);
  console.log(`  FAIL  ${what}`);
  failures.push(what);
  if (!SOFT) throw new Error(`FAILED: ${what}`);
}

const dir = (label) => {
  const d = path.join(SHOTS, label);
  fs.mkdirSync(d, { recursive: true });
  return d;
};

async function open(browser, options = {}) {
  const ctx = await browser.newContext({ locale: "fr-FR", ...options });
  const page = await ctx.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(String(e)));
  // every text given to the live region, in order (announce() empties it, then fills it)
  await page.addInitScript(() => {
    window.__said = [];
    new MutationObserver(() => {
      const live = document.getElementById("live");
      if (live && live.textContent) window.__said.push(live.textContent);
    }).observe(document, {
      subtree: true,
      childList: true,
      characterData: true,
    });
  });
  await page.goto(URL);
  await page
    .locator("#welcome-start")
    .click({ timeout: 6000 })
    .catch(() => {});
  await page.waitForTimeout(300);
  return { ctx, page };
}

/** Send a request. A decided team shows its plan card first (wave 2): it is launched at once unless ``plan`` is
 * "keep" (the scenarios of the plan card itself), so the older scenarios see the team at work as before. */
async function send(page, text = DECK, { plan = "launch" } = {}) {
  await page.fill("#composer-input", text);
  await page.press("#composer-input", "Enter");
  if (plan === "keep") return;
  const launch = await page
    .waitForSelector('[data-act="plan-launch"]', { timeout: 8000 })
    .catch(() => null);
  if (launch) await launch.click().catch(() => {});
}

async function idle(page, timeout = 60000) {
  await page.waitForSelector("#btn-send:not([hidden])", { timeout });
}

const active = (page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    return a === document.body
      ? "BODY"
      : `${a.tagName} ${a.className || a.id}`.trim();
  });

// ------------------------------------------------------------------ desktop: focus, announcements, timers

async function desktopRun(browser) {
  console.log("desktop-run (1440x900, fr, light)");
  const out = dir("desktop-run");
  const { ctx, page } = await open(browser, {
    viewport: { width: 1440, height: 900 },
  });
  await send(page);
  await page.waitForSelector('[data-act="agent-off"]', { timeout: 15000 });
  check(
    (await page.$$("section.crew[aria-live]")).length === 0,
    "the crew board is not itself a live region",
  );
  await page.focus('[data-act="agent-off"]');
  const before = await active(page);
  // timers: sample the running lanes' elapsed time every 250 ms for 5 s
  let blank = 0;
  let samples = 0;
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(250);
    // a timer is blank in its first second only (as the live line's)
    const times = await page.$$eval(
      '.crew-lane[data-status="running"] .crew-time',
      (els) => els.filter((e) => Date.now() - Number(e.dataset.since) >= 1100).map((e) => e.textContent),
    );
    for (const x of times) {
      samples++;
      if (!x) blank++;
    }
  }
  const after = await active(page);
  check(
    before.includes("crew-out") && after.includes("crew-out"),
    `focus stays on « Revenir au mode simple » (${before} -> ${after})`,
  );
  check(
    samples > 0 && blank <= samples / 4,
    `running lanes show their time (${blank}/${samples} blank)`,
  );
  const hidden = await page.$$eval(".crew-time", (els) =>
    els.every((e) => e.getAttribute("aria-hidden") === "true"),
  );
  check(hidden, "lane timers are aria-hidden");
  await page.screenshot({ path: path.join(out, "1-running.png") });
  // Escape with the focus in the turn does not stop the team (the focus never falls back to <body>)
  await page.waitForSelector(
    '[data-phase="drafts"] .crew-lane[data-status="running"]',
    { timeout: 20000 },
  );
  await idle(page);
  await page.screenshot({ path: path.join(out, "2-done.png") });
  const said = await page.evaluate(() => window.__said);
  check(
    said.some((s) => /retenue/.test(s)),
    `the kept version is announced (${said.filter((s) => /Version|retenue/.test(s)).join(" | ")})`,
  );
  check(
    said.some((s) => /terminé/.test(s)),
    "a lane finishing is announced",
  );
  check(
    said.some((s) => /Équipe : \d+ agents/.test(s)),
    "the team summary is announced",
  );
  // focus on the folded summary survives the end of the run's redraws
  check(page.errors.length === 0, `no page error (${page.errors.join(" | ")})`);
  await ctx.close();
}

async function desktopAgentOff(browser) {
  console.log("desktop-agent-off (keyboard)");
  const out = dir("desktop-agent-off");
  const { ctx, page } = await open(browser, {
    viewport: { width: 1440, height: 900 },
  });
  await send(page);
  await page.waitForSelector('[data-act="agent-off"]', { timeout: 15000 });
  await page.waitForTimeout(800);
  await page.focus('[data-act="agent-off"]');
  await page.keyboard.press("Enter");
  await page.waitForTimeout(600);
  const where = await active(page);
  check(
    where.includes("composer-input"),
    `after Enter on « Revenir au mode simple », focus is in the composer (${where})`,
  );
  await idle(page);
  await page.screenshot({ path: path.join(out, "after.png") });
  await ctx.close();
}

// ------------------------------------------------------------------ wave 2: plan card, instructions, checks, deliverables

/** The plan card in Activé (waits for « Lancer »), edited (typed fields only), then launched; an instruction
 * added while the team works is acknowledged; the verification card and « Livrables » at the end. Screenshots at
 * 360 and 1280 px, light and dark. */
async function wave2(browser, { width = 1280, scheme = "light" } = {}) {
  const label = `wave2-${width}-${scheme}`;
  console.log(label);
  const out = dir(label);
  const { ctx, page } = await open(browser, {
    viewport: { width, height: width < 500 ? 780 : 900 },
    colorScheme: scheme,
    ...(width < 500 ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}),
  });
  await page.selectOption("#agent-mode", "on");
  const bodies = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/chat")) bodies.push(JSON.parse(r.postData() || "{}"));
  });
  await send(page, DECK, { plan: "keep" });
  await page.waitForSelector(".crew-plan", { timeout: 15000 });
  check(bodies[0]?.agent_flow === "plan", "the app asks for the plan card first");
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, "1-plan.png") });
  check(!(await page.isVisible("[data-plan-countdown]")), "Activé: no countdown, the card waits for « Lancer »");
  const steps = await page.$$eval(".crew-plan .crew-step", (els) => els.length);
  check(steps >= 4, `the plan lists its steps (${steps})`);
  // « Modifier »: typed fields only
  await page.click('[data-act="plan-edit"]');
  await page.waitForSelector("[data-plan-editor]");
  await page.click('.plan-seg-opt:has(input[value="decision"])');
  await page.click('button[aria-label="Une diapositive de moins"]');
  await page.fill("[data-plan-section]", "Ce qu'il faut retenir");
  await page.click('.plan-add button');
  await page.fill('[data-plan-sites="prefer"]', "insee.fr");
  await page.dispatchEvent('[data-plan-sites="prefer"]', "change");
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(out, "2-plan-edit.png") });
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  check(sw <= width + 1, `${width} px: no horizontal scroll while editing (${sw})`);
  await page.click('[data-act="plan-edit"]'); // Terminer
  await page.click('[data-act="plan-launch"]');
  await page.waitForSelector("[data-crew-now]", { timeout: 15000 });
  const launch = bodies[bodies.length - 1];
  check(
    launch?.agent_plan?.token && launch.agent_plan.edits.audience === "decision" && launch.agent_plan.edits.n_slides === 5,
    `« Lancer » sends the signed plan and typed edits (${JSON.stringify(launch?.agent_plan?.edits || {})})`,
  );
  check(
    JSON.stringify(launch?.agent_plan?.edits?.sections) === JSON.stringify(["Ce qu'il faut retenir"]) &&
      JSON.stringify(launch?.agent_plan?.edits?.prefer) === JSON.stringify(["insee.fr"]),
    "sections and sites are sent as typed lists",
  );
  check(await page.isVisible('[data-act="agent-stop"]'), "« Arrêter » is visible while the team works");
  const line = await page.textContent(".crew-now-text");
  check(/^(Prépare|Lance|Lit|Relève|Rédige|Vérifie|Corrige|Crée|Passe)/.test(line || ""), `one line in the present tense (« ${line} »)`);
  // « Ajouter une consigne »
  await page.click('[data-act="agent-note"]');
  await page.waitForSelector("[data-note-form]");
  await page.selectOption("[data-note-kind]", "add_section");
  await page.fill("[data-note-value]", "Méthode");
  await page.screenshot({ path: path.join(out, "3-note-form.png") });
  await page.click('[data-note-form] button[type="submit"]');
  await page.waitForSelector('.crew-note[data-status="applied"], .crew-note[data-status="late"]', { timeout: 20000 });
  const noteState = await page.getAttribute(".crew-note", "data-status");
  check(noteState === "applied", `the instruction is applied between two steps (${noteState})`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(out, "4-running.png") });
  const current = await page.$$eval('.crew-step[aria-current="step"]', (els) => els.length);
  check(current === 1, "the plan shows the current step");
  await idle(page);
  await page.waitForTimeout(300);
  const past = await page.textContent(".crew-fold > summary");
  check(/lues|vérifiés/.test(past || ""), `the folded line is in the past tense (« ${past} »)`);
  await page.click(".vc-head");
  await page.waitForTimeout(250);
  await page.locator(".vc").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, "5-checks.png") });
  const counts = await page.textContent(".vc-counts");
  check(/4\s+chiffres vérifiés/.test(counts) && /1\s+retiré/.test(counts), `the verification card counts (« ${counts} »)`);
  const lines = await page.$$eval(".vc-line", (els) => els.length);
  check(lines >= 4, `each verified figure shows its source line (${lines})`);
  await page.click(".crew-fold > summary");
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(out, "6-did.png"), fullPage: true });
  check(await page.isVisible("#btn-deliverables"), "« Livrables » appears in the top bar");
  await page.click("#btn-deliverables");
  await page.waitForSelector("#deliverables[open] .deliv-item");
  await page.screenshot({ path: path.join(out, "7-deliverables.png") });
  const n = await page.$$eval("#deliverables .deliv-item", (els) => els.length);
  check(n === 1, `the conversation lists its deliverable (${n})`);
  await page.keyboard.press("Escape");
  const sw2 = await page.evaluate(() => document.documentElement.scrollWidth);
  check(sw2 <= width + 1, `${width} px: no horizontal scroll (${sw2})`);
  check(page.errors.length === 0, `no page error (${page.errors.join(" | ")})`);
  await ctx.close();
}

/** Auto: the plan card counts down and the team starts by itself; « Modifier » stops the countdown. */
async function autoStart(browser) {
  console.log("auto-start (1280, light)");
  const out = dir("auto-start");
  const { ctx, page } = await open(browser, { viewport: { width: 1280, height: 900 } });
  await page.selectOption("#agent-mode", "auto");
  await send(page, DECK, { plan: "keep" });
  await page.waitForSelector("[data-plan-countdown]", { timeout: 15000 });
  await page.screenshot({ path: path.join(out, "1-countdown.png") });
  const t0 = Date.now();
  await page.waitForSelector("[data-crew-now]", { timeout: 12000 });
  const waited = (Date.now() - t0) / 1000;
  check(waited >= 3 && waited <= 8, `Auto, high confidence: starts after the countdown (${waited.toFixed(1)} s)`);
  await idle(page);
  // a second request: « Modifier » stops the countdown
  await send(page, DECK, { plan: "keep" });
  await page.waitForSelector("[data-plan-countdown]", { timeout: 15000 });
  await page.click('[data-act="plan-edit"]');
  await page.waitForTimeout(6500);
  check(await page.isVisible(".crew-plan.is-editing"), "« Modifier » stops the countdown: still the plan after 6 s");
  check(page.errors.length === 0, `no page error (${page.errors.join(" | ")})`);
  await ctx.close();
}

// ------------------------------------------------------------------ scripted failures (page.route over the demo stream)

function frames(body) {
  return body.split("\n\n").filter(Boolean);
}
const evOf = (f) => {
  const line = f.split("\n").find((l) => l.startsWith("data:"));
  try {
    return line ? JSON.parse(line.slice(5)) : null;
  } catch {
    return null;
  }
};
const frame = (ev) => `data: ${JSON.stringify(ev)}`;

const TRANSFORMS = {
  // the server fails after the reading phase
  serverError(fs) {
    const i = fs.findIndex(
      (f) => evOf(f)?.type === "agent_step" && evOf(f).phase === "drafts",
    );
    return [
      ...fs.slice(0, i + 1),
      frame({ type: "error", code: "internal", message: "boom" }),
      frame({ type: "done" }),
    ];
  },
  // the connection is cut while the drafts run (no « done »)
  cut(fs) {
    const i = fs.findIndex(
      (f) => evOf(f)?.type === "agent_step" && evOf(f).phase === "drafts",
    );
    return fs.slice(0, i + 1);
  },
  // one drafter fails, the other is kept
  laneError(fs) {
    return fs
      .map((f) => {
        const ev = evOf(f);
        if (
          ev?.type === "agent_step" &&
          ev.id === "redacteur_b" &&
          ev.status === "done"
        )
          return frame({ ...ev, status: "error" });
        if (
          ev?.type === "agent_step" &&
          ev.id === "redacteur_b" &&
          ev.status === "scored"
        )
          return null;
        return f;
      })
      .filter(Boolean);
  },
};

async function scripted(browser, kind, { lang = "fr", scheme = "light" } = {}) {
  const label = `err-${kind}-${lang}-${scheme}`;
  console.log(label);
  const out = dir(label);
  const { ctx, page } = await open(browser, {
    viewport: { width: 1280, height: 860 },
    colorScheme: scheme,
    locale: lang === "en" ? "en-US" : "fr-FR",
  });
  await page.route("**/api/chat", async (route) => {
    const resp = await route.fetch();
    const text = await resp.text();
    // the plan card's request is left alone: the failure is scripted on the team's own stream
    const body = text.includes('"agent_plan"')
      ? text
      : TRANSFORMS[kind](frames(text)).join("\n\n") + "\n\n";
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body,
    });
  });
  await send(page);
  await idle(page, 90000);
  await page.waitForTimeout(300);
  await page
    .locator(".crew-fold > summary")
    .click()
    .catch(() => {});
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(out, "state.png"), fullPage: true });
  const line =
    (await page.textContent(".crew-fold > summary").catch(() => "")) || "";
  const statuses = await page.$$eval(".crew-lane", (els) =>
    els.map((e) => e.dataset.status),
  );
  const details = await page.$$eval(".crew-lane .crew-detail", (els) =>
    els.map((e) => e.textContent),
  );
  if (kind === "serverError") {
    check(
      !/interrompue|stopped/i.test(line),
      `server error: not « interrompue » (${line})`,
    );
    check(
      /n'a pas abouti|did not finish/.test(line),
      `server error: « l'équipe n'a pas abouti » (${line})`,
    );
    check(
      !details.some((d) => /non nécessaire|not needed/.test(d)),
      `server error: no lane « non nécessaire » (${statuses.join(",")})`,
    );
  } else if (kind === "cut") {
    check(
      /connexion perdue|connection lost/.test(line),
      `cut: « connexion perdue » (${line})`,
    );
    check(
      !statuses.includes("stopped"),
      `cut: no lane « arrêté » (${statuses.join(",")})`,
    );
    check(
      await page.isVisible('[data-act="retry"], .notice [data-act]'),
      "cut: the retry card is shown",
    );
  } else if (kind === "laneError") {
    check(
      /n'a pas abouti|did not finish/.test(line),
      `lane error: the folded line says one agent failed (${line})`,
    );
  }
  check(page.errors.length === 0, `no page error (${page.errors.join(" | ")})`);
  await ctx.close();
}

// ------------------------------------------------------------------ a stalled stream (proxy stops forwarding)

function stallProxy(target, port) {
  const t = new globalThis.URL(target);
  const server = http.createServer((req, res) => {
    const up = http.request(
      {
        host: t.hostname,
        port: t.port,
        path: req.url,
        method: req.method,
        headers: req.headers,
      },
      (r) => {
        res.writeHead(r.statusCode, r.headers);
        let sent = 0;
        r.on("data", (chunk) => {
          if (req.url.startsWith("/api/chat") && sent > 5000) return; // swallow: the socket stays open
          sent += chunk.length;
          res.write(chunk);
        });
        r.on(
          "end",
          () => !(req.url.startsWith("/api/chat") && sent > 5000) && res.end(),
        );
      },
    );
    req.pipe(up);
  });
  return new Promise((resolve) => server.listen(port, () => resolve(server)));
}

async function stall(browser) {
  console.log("sse-stall (proxy stops forwarding after 5 kB)");
  const out = dir("sse-stall");
  const proxy = await stallProxy(URL, 9299);
  const ctx = await browser.newContext({
    locale: "fr-FR",
    viewport: { width: 1280, height: 860 },
  });
  const page = await ctx.newPage();
  await page.goto("http://127.0.0.1:9299/");
  await page
    .locator("#welcome-start")
    .click({ timeout: 6000 })
    .catch(() => {});
  await send(page);
  await page.waitForTimeout(45000);
  await page.screenshot({ path: path.join(out, "after.png"), fullPage: true });
  check(
    await page.isVisible("#btn-send"),
    "after 45 s without a byte: Send is back",
  );
  check(
    !(await page.isVisible("#btn-stop")),
    "after 45 s without a byte: Stop is gone",
  );
  const text = (await page.textContent(".turn-bird:last-child")) || "";
  check(
    /interrompue avant la fin|connexion/.test(text),
    "after 45 s without a byte: the connection-loss card",
  );
  await ctx.close();
  proxy.close();
}

// ------------------------------------------------------------------ phones

const PHONES = {
  iPhone13: "iPhone 13",
  Pixel7: "Pixel 7",
  iPhoneSE: "iPhone SE",
  iPhone14: "iPhone 14",
};

async function phone(browsers, key, scheme = "light") {
  const desc = pw.devices[PHONES[key]];
  const engine =
    desc.defaultBrowserType === "webkit" && browsers.webkit
      ? "webkit"
      : "chromium";
  const label = `mobile-${key}-${scheme}`;
  console.log(
    `${label} (${engine}${engine === "chromium" && desc.defaultBrowserType !== "chromium" ? ", emulated" : ""})`,
  );
  const out = dir(label);
  const { ctx, page } = await open(browsers[engine], {
    ...desc,
    colorScheme: scheme,
  });
  // the pill: every value readable
  for (const v of ["auto", "on", "off"]) {
    await page.selectOption("#agent-mode", v);
    await page.waitForTimeout(100);
    const m = await page.evaluate(pillFit);
    check(
      m.need <= m.room + 0.5,
      `${key}: « ${m.text} » fits in the pill (${m.need.toFixed(0)} <= ${m.room.toFixed(0)} px)`,
    );
    if (v === "on")
      await page.screenshot({
        path: path.join(out, "pill-on.png"),
        clip: {
          x: 0,
          y: desc.viewport.height - 160,
          width: desc.viewport.width,
          height: 160,
        },
      });
    if (v === "off")
      await page.screenshot({
        path: path.join(out, "pill-off.png"),
        clip: {
          x: 0,
          y: desc.viewport.height - 160,
          width: desc.viewport.width,
          height: 160,
        },
      });
    if (desc.hasTouch) {
      check(
        m.pill[1] >= 44,
        `${key}: the pill is at least 44 px high (${m.pill.map(Math.round).join("x")})`,
      );
      check(
        m.sel[1] >= 40 && m.sel[0] >= m.pill[0] - 30,
        `${key}: the select covers the pill (${m.sel.map(Math.round).join("x")})`,
      );
    }
  }
  await page.selectOption("#agent-mode", "auto");
  await send(page);
  await page.waitForSelector(
    '[data-phase="brief"] .crew-lane[data-status="running"], [data-phase="drafts"] .crew-lane[data-status="running"]',
    { timeout: 20000 },
  );
  if (desc.hasTouch) {
    const stop = await page.evaluate(() =>
      document.getElementById("btn-stop").getBoundingClientRect(),
    );
    check(
      stop.width >= 44 && stop.height >= 44,
      `${key}: Stop is at least 44x44 (${Math.round(stop.width)}x${Math.round(stop.height)})`,
    );
  }
  await page.waitForSelector(
    '[data-phase="drafts"] .crew-lane[data-status="running"]',
    { timeout: 20000 },
  );
  await page.$eval('[data-phase="drafts"]', (e) => e.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(out, "1-running.png") });
  const lanes = await page.$$eval('[data-phase="drafts"] .crew-lane', (els) =>
    els.map((e) => e.getBoundingClientRect().width),
  );
  const board = await page.$eval(
    ".crew-board",
    (e) => e.getBoundingClientRect().width,
  );
  check(
    lanes.every((w) => w >= board - 2),
    `${key}: parallel lanes stack (${lanes.map(Math.round).join(", ")} of ${Math.round(board)} px)`,
  );
  await idle(page);
  if (desc.hasTouch) {
    const sum = await page.$eval(
      ".crew-fold > summary",
      (e) => e.getBoundingClientRect().height,
    );
    check(
      sum >= 44,
      `${key}: the folded line is at least 44 px high (${Math.round(sum)})`,
    );
  }
  await page.click(".crew-fold > summary");
  await page.waitForTimeout(200);
  check(
    (await page.$$eval(".crew-kept.is-part", (els) => els.length)) === 1,
    `${key}: the version the checker borrowed from says « reprise en partie »`,
  );
  await page.screenshot({
    path: path.join(out, "2-done-open.png"),
    fullPage: true,
  });
  const [sw, cw] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  check(sw <= cw + 1, `${key}: no horizontal scroll (${sw} <= ${cw})`);
  check(page.errors.length === 0, `no page error (${page.errors.join(" | ")})`);
  await ctx.close();
}

// The text the pill shows for its value (the <select>'s option, or the short word over a see-through select on
// phones), the width it needs and the room it has; and whether Send stays inside the composer.
function pillFit() {
  const s = document.getElementById("agent-mode");
  const v = document.getElementById("agent-pill-value");
  const shown = v && getComputedStyle(v).display !== "none" ? v : s;
  const text = shown === s ? s.options[s.selectedIndex].text : v.textContent;
  const probe = document.createElement("span");
  probe.style.font = getComputedStyle(shown).font;
  probe.style.position = "absolute";
  probe.style.whiteSpace = "nowrap";
  probe.textContent = text;
  document.body.append(probe);
  const need = probe.getBoundingClientRect().width;
  probe.remove();
  const cs = getComputedStyle(shown);
  const room = shown.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const r = s.getBoundingClientRect();
  const p = document.getElementById("agent-pill").getBoundingClientRect();
  const send = document.getElementById("btn-send").getBoundingClientRect();
  const box = document.getElementById("composer").getBoundingClientRect();
  return { text, need, room, sel: [r.width, r.height], pill: [p.width, p.height], sendIn: send.right <= box.right - 1 };
}

// every phone width: the selected value is never ellipsized
async function pillWidths(browser) {
  console.log("pill widths 320-412 (fr)");
  for (const width of [320, 360, 375, 390, 412]) {
    const { ctx, page } = await open(browser, {
      ...pw.devices["iPhone 14"],
      viewport: { width, height: 760 },
    });
    for (const v of ["auto", "on", "off"]) {
      await page.selectOption("#agent-mode", v);
      const ok = await page.evaluate(pillFit);
      check(
        ok.need <= ok.room + 0.5 && ok.sendIn,
        `${width} px: « ${ok.text} » fits (${ok.need.toFixed(0)}/${ok.room.toFixed(0)}), Send inside`,
      );
    }
    await ctx.close();
  }
}

// landscape phone, keyboard up (viewport 180 px shorter): the conversation keeps room
async function landscape(browser) {
  console.log("keyboard landscape (iPhone 14 landscape, emulated)");
  const out = dir("keyboard");
  const desc = pw.devices["iPhone 14 landscape"];
  const { ctx, page } = await open(browser, { ...desc });
  await send(page);
  await page.waitForSelector(
    '[data-phase="drafts"] .crew-lane[data-status="running"]',
    { timeout: 20000 },
  );
  const free = await page.$eval(
    "#scroll",
    (e) => e.getBoundingClientRect().height,
  );
  await page.screenshot({ path: path.join(out, "landscape-nokeyboard.png") });
  check(
    free >= 160,
    `landscape: the conversation keeps ${Math.round(free)} px (>= 160)`,
  );
  await page.setViewportSize({
    width: desc.viewport.width,
    height: desc.viewport.height - 180,
  });
  await page.focus("#composer-input");
  await page.waitForTimeout(300);
  const kb = await page.$eval(
    "#scroll",
    (e) => e.getBoundingClientRect().height,
  );
  await page.screenshot({ path: path.join(out, "landscape.png") });
  check(
    kb >= 90,
    `landscape with the keyboard: the conversation keeps ${Math.round(kb)} px (>= 90)`,
  );
  await idle(page);
  await ctx.close();
}

// iPhone SE (320 and 375 x 568), composer focused: a real touch (down, 90 ms, up) on a control just above the dock
// lands on it. The dock's notes used to come back on blur, grow the dock mid-tap and swallow the click.
async function touchTap(page, ctx, selector, what) {
  const target = await page.evaluate((sel) => {
    const dock = document.getElementById("dock").getBoundingClientRect();
    const sc = document.getElementById("scroll");
    const el = [...document.querySelectorAll(sel)].filter((e) => e.getBoundingClientRect().height > 0).pop();
    if (!el) return null;
    // the control right above the dock, where the notes would cover it
    sc.scrollTop += el.getBoundingClientRect().bottom - dock.top + 2;
    const r = el.getBoundingClientRect();
    el.setAttribute("data-probe", "1");
    window.__hits = [];
    document.addEventListener("click", (ev) => window.__hits.push(!!ev.target.closest("[data-probe]")), {
      capture: true,
      once: true,
    });
    return { x: r.x + r.width / 2, y: r.bottom - 4 };
  }, selector);
  check(!!target, `${what}: control found`);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: target.x, y: target.y }] });
  await page.waitForTimeout(90);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await page.waitForTimeout(500);
  const hits = await page.evaluate(() => window.__hits);
  check(hits.length === 1 && hits[0], `${what}: the tap lands on the control (${JSON.stringify(hits)})`);
}

async function smallTouch(browser) {
  console.log("small phone touch, composer focused (iPhone SE 320/375 x 568, emulated)");
  const out = dir("small-touch");
  for (const width of [320, 375]) {
    const { ctx, page } = await open(browser, {
      ...pw.devices["iPhone SE"],
      viewport: { width, height: 568 },
    });
    await send(page);
    await page.waitForSelector('[data-phase="drafts"] .crew-lane[data-status="running"]', { timeout: 20000 });
    await page.tap("#composer-input");
    await page.keyboard.type("ok");
    await touchTap(page, ctx, '[data-act="agent-off"]', `${width} px, running: « Revenir au mode simple »`);
    await idle(page);
    await send(page);
    await idle(page);
    await page.tap("#composer-input");
    await page.keyboard.type("ok");
    await page.waitForTimeout(200);
    const typing = await page.$eval("#dock", (e) => e.getBoundingClientRect().top);
    await touchTap(page, ctx, ".crew-fold > summary", `${width} px, done: the team's fold`);
    check(
      await page.$eval(".crew-fold", (e) => e.open),
      `${width} px: the fold opened`,
    );
    await page.screenshot({ path: path.join(out, `se-${width}.png`) });
    const rest = await page.$eval("#dock", (e) => e.getBoundingClientRect().top);
    check(rest < typing, `${width} px: the notes come back after the tap (${Math.round(typing)} -> ${Math.round(rest)})`);
    check(page.errors.length === 0, `no page error (${page.errors.join(" | ")})`);
    await ctx.close();
  }
}

(async () => {
  const browsers = { chromium: await pw.chromium.launch() };
  for (const name of ["webkit", "firefox"]) {
    try {
      browsers[name] = await pw[name].launch();
      console.log(`${name}: available`);
    } catch {
      console.log(
        `${name}: not installed, phones emulated with Chromium device descriptors`,
      );
    }
  }
  const all = {
    desktopRun: () => desktopRun(browsers.chromium),
    desktopAgentOff: () => desktopAgentOff(browsers.chromium),
    serverError: () =>
      scripted(browsers.chromium, "serverError", {
        lang: "en",
        scheme: "dark",
      }),
    laneError: () => scripted(browsers.chromium, "laneError"),
    cut: () => scripted(browsers.chromium, "cut"),
    phones: async () => {
      for (const k of Object.keys(PHONES)) await phone(browsers, k);
      await phone(browsers, "iPhone13", "dark");
    },
    pillWidths: () => pillWidths(browsers.chromium),
    landscape: () => landscape(browsers.chromium),
    smallTouch: () => smallTouch(browsers.chromium),
    stall: () => stall(browsers.chromium),
    firefox: async () => browsers.firefox && desktopRun(browsers.firefox),
    wave2: async () => {
      for (const width of [1280, 360])
        for (const scheme of ["light", "dark"]) await wave2(browsers.chromium, { width, scheme });
    },
    autoStart: () => autoStart(browsers.chromium),
  };
  const only = process.argv.slice(2);
  for (const [name, fn] of Object.entries(all))
    if (!only.length || only.includes(name)) {
      try {
        await fn();
      } catch (e) {
        if (!SOFT) throw e;
        console.log(
          `  ERROR ${name}: ${String(e.message || e).split("\n")[0]}`,
        );
        failures.push(`${name}: error`);
      }
    }
  for (const b of Object.values(browsers)) await b.close();
  console.log(
    failures.length
      ? `${failures.length} check(s) failed`
      : "all checks passed",
  );
  process.exit(failures.length ? 1 : 0);
})().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
