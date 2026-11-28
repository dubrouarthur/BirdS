// Live measure of the six fixed document prompts (docs/CANVAS.md, section 9): one fresh conversation each, on a Bird
// page (production = before, a local server on the live model = after). node scripts/canvas_docs_live.js <url> <outdir> [ids]
const { chromium } = require("playwright");
const fs = require("fs");
const URL = process.argv[2], OUT = process.argv[3], ONLY = (process.argv[4] || "").split(",").filter(Boolean);
const CASES = [
  { id: "cadrage", ask: "Rédige un document Word : note de cadrage pour un projet de CRM, avec objectifs, périmètre, planning et risques", want: ["objectif", "p[ée]rim[èe]tre", "planning|calendrier|jalon", "risque"] },
  { id: "cr", ask: "Rédige le compte rendu de la réunion d'équipe de lundi : participants Paul, Marie et Inès ; décision : télétravail deux jours par semaine ; action : Paul prépare la charte avant vendredi", want: ["participant", "d[ée]cision", "action"] },
  { id: "rapport", ask: "Rédige un rapport sur la sobriété numérique au bureau", want: [] },
  { id: "propal", ask: "Prépare une proposition commerciale pour un service de nettoyage de bureaux destiné aux PME", want: [] },
  { id: "procedure", ask: "Rédige une procédure d'accueil d'un nouvel arrivant dans l'entreprise, étape par étape", want: ["[ée]tape"] },
  { id: "lettre", ask: "Rédige une lettre en Word pour résilier mon abonnement à la salle de sport", want: [] },
];
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch();
  const rows = [];
  for (const c of CASES) {
    if (ONLY.length && !ONLY.includes(c.id)) continue;
    const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "fr-FR" });
    await ctx.addInitScript(() => localStorage.setItem("bird.prefs", JSON.stringify({ lang: "fr", welcomed: true })));
    const p = await ctx.newPage();
    let body = null;
    p.on("response", async (r) => { if (r.url().includes("/api/chat") && r.request().method() === "POST") { try { body = await r.text(); } catch (e) { body = "ERR " + e; } } });
    await p.goto(URL);
    await p.waitForTimeout(1500);
    await p.locator("#composer-input").fill(c.ask);
    const t0 = Date.now();
    await p.locator("#btn-send").click();
    await p.waitForFunction(() => !document.querySelector('.turn-bird[aria-busy="true"]') && !!document.querySelector(".turn-bird"), null, { timeout: 420000 }).catch(() => {});
    for (let i = 0; i < 40 && body === null; i++) await p.waitForTimeout(500);
    const secs = (Date.now() - t0) / 1000;
    await p.waitForTimeout(1200);
    await p.screenshot({ path: `${OUT}/${c.id}.png` });
    const ui = await p.evaluate(() => ({
      cvCards: document.querySelectorAll(".turn-bird .cv-card").length,
      fileCards: document.querySelectorAll(".turn-bird .file-card, .turn-bird .files .file, .turn-bird [class*='file-card']").length,
      canvasOpen: !!document.querySelector("#canvas:not([hidden])"),
      text: (document.querySelector(".turn-bird .md")?.innerText || "").slice(0, 600),
    }));
    const evs = String(body || "").split("\n\n").filter((f) => f.startsWith("data: ")).map((f) => { try { return JSON.parse(f.slice(6)); } catch { return {}; } });
    const fin = evs.filter((e) => e.type === "canvas" && e.phase === "final").at(-1);
    const ans = evs.find((e) => e.type === "answer") || {};
    const doc = fin?.doc || ans.canvas?.doc || null;
    const titles = (doc?.blocks || []).map((x) => x.title || "");
    const hay = titles.join(" | ").toLowerCase();
    const got = c.want.filter((w) => new RegExp(w, "i").test(hay)).length;
    const steps = evs.filter((e) => e.type === "step" && e.status !== "running").map((e) => e.tool);
    const usage = evs.find((e) => e.type === "usage") || {};
    const row = { id: c.id, secs: Math.round(secs), path: fin ? "canvas" : ans.canvas?.doc ? "adopted" : "none", steps,
      cvCards: ui.cvCards, fileCards: (ans.files || []).length, canvasOpen: ui.canvasOpen,
      rawFileLine: /Fichier\s*:|\.docx\b/i.test(ans.content || ""), template: doc?.template || null,
      structure: doc?.structure || null, sections: titles.length, titles, requested: `${got}/${c.want.length}`,
      parts: [...new Set((doc?.blocks || []).flatMap((x) => (x.parts || []).map((q) => q.t)))],
      repairs: ans.canvas?.repairs ?? null, tokens: [usage.prompt_tokens, usage.completion_tokens], error: evs.find((e) => e.type === "error") || null,
      chat: (ans.content || "").slice(0, 300) };
    rows.push(row);
    console.log(JSON.stringify(row));
    fs.writeFileSync(`${OUT}/${c.id}.sse.txt`, String(body || ""));
    await ctx.close();
  }
  fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(rows, null, 1));
  await b.close();
})();
