// Unit tests of the rich answer renderer (markdown.js + richcode.js). Run: node --test tests/js/
// pytest runs them too (tests/test_web.py::test_rich_renderer_node_unit_tests).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { renderBlocks, renderMarkdown, stabilize } from "../../birds/web/static/markdown.js";
import { highlight, langInfo, sniff } from "../../birds/web/static/richcode.js";

const FENCE = "```";
const R = { rich: true, final: true, lang: "fr" };
const md = (s, o = {}) => renderMarkdown(s, { ...R, ...o });
const answers = JSON.parse(readFileSync(new URL("../fixtures/answers_fr.json", import.meta.url), "utf8"));
const answer = (id) => answers.find((a) => a.id === id).answer;
const text = (html) => html.replace(/<[^>]+>/g, "");

// ------------------------------------------------------------------ typography

test("French spacing: no-break spaces before : ; ! ? and inside numbers, never in code or links", () => {
  const out = md("Prix : 185 000 € ; soit +12 % ! Vraiment ? `a : b` https://e.org/x?a=1 et l'été... 3e rang - fin");
  assert.match(out, /Prix\u00a0: 185\u202f000\u202f€\u202f; soit \+12\u202f%\u202f! Vraiment\u202f\?/);
  assert.match(out, /<code>a : b<\/code>/);
  assert.match(out, /href="https:\/\/e\.org\/x\?a=1"/);
  assert.match(out, /l’été…/);
  assert.match(out, /3<sup class="md-ord">e<\/sup> rang – fin/);
  assert.equal(md(text(md("Prix : 1 000 €"))), md("Prix : 1 000 €").replace(/ /g, " ")); // idempotent on its output
});

test("typography leaves glued punctuation, times and English alone", () => {
  assert.match(md("à 10:30, http: ok"), /10:30, http: ok/);
  const en = md("It's 1 000 : fine...", { lang: "en" });
  assert.match(en, /It’s 1 000 : fine…/);
  assert.doesNotMatch(md("Prix : 3", { rich: false, lang: undefined }), /\u00a0/);
});

// ------------------------------------------------------------------ headings

test("pseudo-headings: a short bare line or a bold-only line before a list, table or code", () => {
  const out = md("Intro.\n\nSécurité\n- a\n- b\n\n**Avantages** :\n- c\n\nLancer le script :\n```bash\nls\n```");
  assert.match(out, /<h4 class="md-ph">Sécurité<\/h4>/);
  assert.match(out, /<h4 class="md-ph">Avantages<\/h4>/);
  assert.match(out, /<h4 class="md-ph">Lancer le script<\/h4>/);
});

test("pseudo-headings: near misses stay paragraphs", () => {
  for (const s of [
    "Sécurité\n\nUn paragraphe qui suit.", // not followed by a list
    "Voici un tableau récapitulatif :\n\n| a | b |\n|---|---|\n| 1 | 2 |", // a caption, not a heading
    "Voilà ce que je propose de faire maintenant :\n- a", // a sentence ending with ":"
    "C'est fini.\n- a", // final punctuation
    "1) Étape\n- a",
  ])
    assert.doesNotMatch(md(s), /<h4/, s);
  assert.equal((md("## Sécurité\n\n**Sécurité** :\n- a").match(/<h[34]/g) || []).length, 1); // duplicate kept once
});

// ------------------------------------------------------------------ callouts, pairs

test("callouts: warning, note, decision, GitHub admonitions; the keyword stays in the text", () => {
  const warn = md(answer("definition"));
  assert.match(warn, /md-callout--warn[\s\S]*<strong class="md-callout-label">Attention<\/strong>, cette formule/);
  assert.match(md("Note : à relire."), /md-callout--note/);
  assert.match(md("**Conseil :** testez d'abord."), /md-callout--tip/);
  assert.match(md("> [!WARNING]\n> Sauvegardez."), /md-callout--warn[\s\S]*Attention[\s\S]*Sauvegardez/);
  assert.doesNotMatch(md("> [!WARNING]\n> x"), /\[!WARNING\]/);
});

test("callouts: near misses", () => {
  assert.doesNotMatch(md("Il faut faire attention : le délai court."), /md-callout/);
  assert.doesNotMatch(md("Note, ce n'est pas grave."), /md-callout/);
  assert.doesNotMatch(md(`${FENCE}\nNote : dans le code\n${FENCE}`), /md-callout/);
  assert.doesNotMatch(md("- Attention : dans une liste"), /md-callout/);
  assert.doesNotMatch(md(`Attention : ${"x ".repeat(400)}`), /md-callout/); // too long for a callout
});

test("label/value rows, framed when they start with Décision", () => {
  const out = md(answer("summary"));
  assert.match(out, /md-callout--decision[\s\S]*<dl class="md-pairs"><div><dt>Décision<\/dt><dd>valider/);
  assert.match(out, /<dt>Actions<\/dt>/);
  assert.doesNotMatch(md("Contexte : un.\nEt ensuite une phrase normale sans deux-points."), /md-pairs/);
  assert.doesNotMatch(md("Label : 3 pommes"), /md-pairs/); // a single line is not a block of pairs
  assert.doesNotMatch(md(`A : b\nC : ${"long ".repeat(60)}`), /md-pairs/); // a real sentence
});

// ------------------------------------------------------------------ lists

test("step lists: numbered procedures with bold labels get badges; prose does not", () => {
  const out = md(answer("procedure+hint"));
  assert.match(out, /<ol class="md-steps[^"]*"><li><span class="md-step-n" aria-hidden="true">1<\/span>/);
  assert.match(out, /<span class="md-step-t">Signaler l’accident<\/span><span class="md-step-b">Informez/);
  assert.doesNotMatch(md("1. a\n2. b\n3. c"), /md-steps/);
  assert.doesNotMatch(md(answer("procedure_v1")), /md-steps|<ol/); // "; …" prose is never split
  assert.match(md("4. **a** x\n5. **b** y\n6. **c** z"), /<ol start="4" class="md-steps"><li><span class="md-step-n" aria-hidden="true">4/);
});

test("key numbers: 3 to 6 label : figure items, only once the answer is final", () => {
  const out = md(answer("figures"));
  assert.match(out, /<figure class="md-kpis"><figcaption>Résultats du 3<sup class="md-ord">e<\/sup> trimestre<\/figcaption>/);
  assert.equal((out.match(/class="md-kpi"/g) || []).length, 5);
  assert.match(out, /<dt>Marge brute<\/dt><dd><span class="md-kpi-v">38\u202f%<\/span>/);
  assert.doesNotMatch(md(answer("figures"), { final: false }), /md-kpis/);
  assert.doesNotMatch(md(answer("figures"), { suppress: ["kpis"] }), /md-kpis/); // a widget owns them
  assert.doesNotMatch(md("- CA : 4 €\n- Marge : 3 %"), /md-kpis/); // two items
  assert.doesNotMatch(md("- CA : 4 €\n- Marge : 3 %\n- Avis : très bon"), /md-kpis/); // one is not a figure
});

test("pros and cons: two labelled lists become one two-column block", () => {
  const out = md(answer("proscons"));
  assert.match(out, /<div class="md-proscons"><section class="md-pc md-pc--pro"><h4 class="md-pc-t">Avantages<\/h4><ul>/);
  assert.match(out, /md-pc--con"><h4 class="md-pc-t">Inconvénients/);
  assert.doesNotMatch(md(answer("proscons"), { final: false }), /md-proscons/);
  assert.doesNotMatch(md("Avantages :\n- a\n\nRemarques :\n- b"), /md-proscons/);
});

test("keyed lists and long-list folding keep every item", () => {
  assert.match(md(answer("comparison")), /<li><span class="md-li-k">Microsoft Teams<\/span>\u00a0: inclus/);
  const items = Array.from({ length: 20 }, (_, k) => `- étape ${k}`).join("\n");
  const out = md(items);
  assert.equal((out.match(/<li hidden>/g) || []).length, 12);
  assert.equal((out.match(/<li/g) || []).length, 20);
  assert.match(out, /data-md-more[\s\S]*Afficher les 12 autres/);
  assert.doesNotMatch(md(items, { final: false }), /hidden/);
});

test("hard line breaks inside a list item, formula chips, file names, formula lines", () => {
  const out = md(answer("excel"));
  assert.match(out, /fin de mois\u00a0:<br><span class="md-chip"><code class="md-chip-code"><span class="tk-op">=<\/span><span class="tk-fn">EOMONTH<\/span>/);
  assert.match(out, /data-copy-inline/);
  assert.match(md("Ouvrez `rapport.xlsx`."), /<code class="md-file">rapport\.xlsx<\/code>/);
  assert.match(md(answer("definition")), /<span class="md-formula"><code>BFR = \(stocks \+ clients\) - \(fournisseurs \+ charges sociales\)<\/code><span class="md-formula-p">\.<\/span><\/span> C’est/);
  assert.doesNotMatch(md("`a = b` et `c = d + e`"), /md-formula/); // two codes: not a definition
});

test("quotes with a source", () => {
  const out = md("> Le temps, c'est de l'argent.\n> — Benjamin Franklin");
  assert.match(out, /<figure class="md-quote"><blockquote><p>Le temps, c’est de l’argent\.<\/p><\/blockquote><figcaption><cite>Benjamin Franklin<\/cite>/);
  assert.match(md("> juste une citation"), /^<blockquote>/);
});

// ------------------------------------------------------------------ tables

test("tables: wide tables wrap, numeric columns align, best only when marked", () => {
  const wide = md(answer("comparison+hint"));
  assert.match(wide, /<table class="md-table md-table--wide">/);
  const t = md("| Offre | Prix | Note |\n|---|---|---|\n| A | 1 200 € | **top** |\n| B | 900 € | ok ✅ |");
  assert.match(t, /<td class="md-num">1\u202f200\u202f€<\/td>/);
  assert.match(t, /<td class="md-best"><strong>top<\/strong><\/td>/);
  assert.match(t, /<td class="md-best">ok ✅<\/td>/);
  assert.doesNotMatch(md("| a | b |\n|---|---|\n| x | 1 |\n| y | 2 |"), /md-best/);
  assert.match(md("| a | b |\n|---|---:|\n| x | 1 |"), /<td class="al-right">1<\/td>/); // explicit alignment wins
});

// ------------------------------------------------------------------ code blocks

test("code blocks: language label, file name from the line above, download, copy, line numbers, collapse", () => {
  const out = md(answer("json_bash"));
  assert.match(out, /<span class="code-lang">JSON<\/span><span class="code-file">backup-config\.json<\/span>/);
  assert.match(out, /<span class="code-lang">Bash<\/span><span class="code-file">backup\.sh<\/span>/);
  assert.doesNotMatch(out, /Fichier\u00a0:/); // the line moved into the head
  assert.match(out, /data-code-download data-file="backup\.sh"/);
  assert.match(out, /code-check--ok[\s\S]*Syntaxe JSON valide/);
  assert.match(out, /data-lang="bash" data-lines="36" data-long data-collapsed/);
  assert.match(out, /Afficher les 36 lignes/);
  assert.match(out, /data-lang="bash" data-lines="2">/); // short: no numbers, no collapse
});

test("code text content is exactly the source: copy and download never see numbers or markup", () => {
  const src = 'x = "<b>&"  # c\n\n  y = 1';
  const out = md(`${FENCE}python\n${src}\n${FENCE}`);
  const code = out.match(/<code>([\s\S]*)<\/code><\/pre>/)[1];
  const decoded = code.replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
  assert.equal(decoded, src);
  assert.equal((code.match(/<span class="ln/g) || []).length, 3);
});

test("syntax badges: server verdicts by index and line count, JSON checked locally, never while streaming", () => {
  const py = `${FENCE}python\ndef f(:\n    pass\n${FENCE}`;
  const bad = [{ i: 0, n: 2, lang: "python", ok: false, kind: "error", line: 1, msg: "invalid syntax" }];
  const out = md(py, { codeChecks: bad });
  assert.match(out, /code-check--err[^>]*title="Vérification[^"]*invalid syntax"[\s\S]*Syntaxe à vérifier, ligne 1/);
  assert.match(out, /<span class="ln ln--err">/);
  assert.doesNotMatch(md(py, { codeChecks: [{ ...bad[0], n: 5 }] }), /code-check/); // another block's verdict
  assert.doesNotMatch(md(py, { codeChecks: bad, final: false }), /code-check/);
  assert.match(md(`${FENCE}json\n{\n  "a": 1,\n}\n${FENCE}`), /code-check--err[\s\S]*Syntaxe à vérifier, ligne 3/);
  assert.match(md(`${FENCE}json\n{"a": 1, ...}\n${FENCE}`), /code-check--excerpt"[^>]*>Extrait/);
  assert.doesNotMatch(md(`${FENCE}sql\nSELECT 1;\n${FENCE}`), /code-check/); // no claim for other languages
  for (const word of ["testé", "correct", ">Code vérifié"]) assert.doesNotMatch(md(answer("json_bash")), new RegExp(word));
});

test("an open fence renders plain while streaming, highlighted once closed", () => {
  const open = renderBlocks(stabilize(`Voici :\n${FENCE}python\ndef f():\n    return 1`), { rich: true, lang: "fr" });
  assert.doesNotMatch(open.join(""), /tk-|class="ln/);
  const closed = renderBlocks(`Voici :\n${FENCE}python\ndef f():\n    return 1\n${FENCE}`, { rich: true, lang: "fr" });
  assert.match(closed.join(""), /<span class="tk-kw">def<\/span> <span class="tk-fn">f<\/span>/);
});

test("languages: aliases, sniffing, unknown names", () => {
  assert.equal(langInfo("py").label, "Python");
  assert.equal(langInfo("sh").ext, "sh");
  assert.equal(langInfo("postgresql").key, "sql");
  assert.equal(langInfo("brainfuck").key, null);
  assert.equal(sniff("#!/bin/bash\nls"), "bash");
  assert.equal(sniff("select * from t"), "sql");
  assert.equal(sniff('{"a": 1}'), "json");
  assert.equal(sniff("def f():\n  pass"), "python");
  assert.equal(sniff("=SOMME(A1:A3)"), "excel");
  assert.equal(sniff("hello"), "text");
  assert.match(md(`${FENCE}brainfuck\n+[]\n${FENCE}`), /<span class="code-lang">brainfuck<\/span>/);
});

test("highlighter: every language, every line self-contained", () => {
  const samples = {
    python: '@dataclass\nclass A:\n    """doc\n    string"""\n    x: int = 0x1F  # c\n    def f(self): return f"{self.x}"',
    javascript: "const a = `t ${b}\nline`; /* multi\nline */ fn(1e3) // c",
    typescript: "interface A { readonly x: number }\nexport type B = A;",
    sql: "SELECT nom, SUM(montant) AS ca -- total\nFROM ventes WHERE d = :d AND n = 'l''a'\nGROUP BY nom;",
    json: '{"a": [1, true, null], "b": "c"}',
    bash: 'readonly X="$HOME/a"\nfor f in *.txt; do echo "$f" --flag; done # c\ncat <<EOF\nbody $X\nEOF',
    html: '<!-- c\nd --><a href="x" disabled>t &amp; u</a>',
    css: "@media (max-width: 4px) {\n  .a > b { color: #fff; margin: 0 2px !important; }\n}",
    excel: "=SI(Feuil1!A1>0;RECHERCHEV(B2;'Ma feuille'!$A$1:$C$9;2;FAUX);\"non\")",
    yaml: "a: 1 # c\nb:\n  - 'x'\n  - true",
  };
  for (const [lang, src] of Object.entries(samples)) {
    const lines = highlight(src, lang);
    assert.equal(lines.length, src.split("\n").length, lang);
    for (const l of lines) {
      assert.equal((l.match(/<span/g) || []).length, (l.match(/<\/span>/g) || []).length, `${lang}: ${l}`);
    }
    const back = lines.join("\n").replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
    assert.equal(back, src, lang);
    assert.match(lines.join(""), /tk-/, lang);
  }
  assert.match(highlight(samples.excel, "excel").join(""), /<span class="tk-ref">&#39;Ma feuille&#39;!\$A\$1:\$C\$9<\/span>/);
});

test("highlighter fuzz: hostile and broken input stays escaped text", () => {
  const nasty = ["</span><script>alert(1)</script>", '"unterminated', "'''open", "/* never closed", "<<EOF\nno end", "x".repeat(10_000), "\u0000\u0001"];
  for (const lang of ["python", "javascript", "sql", "json", "bash", "html", "css", "excel", "yaml"])
    for (const s of nasty) {
      const html = highlight(s, lang).join("\n");
      assert.doesNotMatch(html.replace(/<\/?span( class="tk-\w+")?>/g, ""), /[<>]/, `${lang}: ${s.slice(0, 20)}`);
    }
});

test("performance: all saved answers plus a 2 000-line block render in under 30 ms", () => {
  const big = `${FENCE}python\n${Array.from({ length: 2000 }, (_, k) => `x${k} = f(${k}, "s")  # c`).join("\n")}\n${FENCE}`;
  const run = () => {
    const t0 = performance.now();
    for (const a of answers) md(a.answer);
    md(big);
    return performance.now() - t0;
  };
  run(); // warm-up (JIT)
  run();
  const ms = Math.min(run(), run());
  assert.ok(ms < 30 * (process.env.CI ? 4 : 1), `${ms.toFixed(1)} ms`);
});

test("streaming a rich answer: only the last two blocks ever change, and the final render upgrades once", () => {
  for (const id of ["comparison", "json_bash", "proscons", "summary", "figures"]) {
    const src = answer(id);
    let prev = [];
    for (let i = 1; i <= src.length; i += 3) {
      const blocks = renderBlocks(stabilize(src.slice(0, i)), { rich: true, lang: "fr" });
      let common = 0;
      while (common < Math.min(prev.length, blocks.length) && prev[common] === blocks[common]) common++;
      assert.ok(common >= prev.length - 2, `${id} at ${i}`);
      prev = blocks;
    }
  }
});

test("the plain renderer (tool steps) is unchanged: no detectors without options.rich", () => {
  const out = renderMarkdown("Sécurité\n- a\n\nAttention, x.\n\nDécision : a\nActions : b");
  assert.doesNotMatch(out, /md-ph|md-callout|md-pairs/);
});

// A live answer collected after the first round (2026-11-22): bare "Avantages courants" labels and a
// "Recommandation" line glued to its paragraph.
const LEASING =
  "Je peux cependant résumer ce que l'on sait généralement.\n\nAvantages courants\n" +
  "- flux de trésorerie régulier : une mensualité unique plutôt qu'un achat à la fois.\n" +
  "- assurance et entretien inclus : souvent simplifiés dans le contrat.\n\nInconvénients courants\n" +
  "- coût total souvent supérieur à l'achat : intérêts et frais de gestion ajoutés.\n" +
  "- flexibilité limitée : changer de véhicule avant la fin du contrat est possible mais coûteux.\n\n" +
  "Recommandation\nPour une PME de 15 salariés, le leasing convient si vous voulez lisser vos charges ; " +
  "vérifiez cependant le coût total sur 4 à 5 ans.";

test("labels with a qualifier still pair up, and a title glued to its paragraph becomes a heading", () => {
  const out = md(LEASING);
  assert.match(out, /md-pc--pro"><h4 class="md-pc-t">Avantages courants/);
  assert.match(out, /<li><span class="md-li-k">assurance et entretien inclus<\/span>\u00a0: souvent/);
  assert.match(out, /<h4 class="md-ph">Recommandation<\/h4>\n<p>Pour une PME/);
  for (const s of [
    "Décision : valider le budget\nActions : Hugo envoie le calendrier avant le 1er décembre, Sophie lance l'appel.",
    "Plan de déménagement des bureaux — 35 personnes\nemménagement le 15 mars 2027",
    "Bonjour Camille,\nmerci pour votre message, je reviens vers vous dès que possible avec le devis.",
  ])
    assert.doesNotMatch(md(s), /md-ph/, s);
  assert.doesNotMatch(md("Avantages fiscaux du leasing pour les petites entreprises\n- a\n\nInconvénients\n- b"), /md-proscons/);
});

test("salutations and closings are never headings", () => {
  for (const s of [
    "Bonjour Madame Martin\nJe me permets de revenir vers vous au sujet de votre commande du 3 mars, livrée hier.",
    "Madame, Monsieur\nNous avons bien reçu votre dossier et nous vous en remercions vivement par avance.",
    "Merci pour votre retour.\n\nCordialement\n- Paul Durand\n- Service client",
    "**Bonjour Camille**\n- point 1\n- point 2",
    "Chère cliente\n- a\n- b",
    "Dear Mr Smith\nThank you for your letter of 3 March, which we received yesterday morning.",
    "Point d'étape, semaine 12\nLe projet avance bien et les équipes ont livré les deux premiers lots prévus.",
  ])
    assert.doesNotMatch(md(s), /<h4/, s);
  assert.match(md("Sécurité\n- a\n- b"), /<h4 class="md-ph">Sécurité/); // still a heading
});

test("Attention, …: a warning, but not inside a letter, and the closing offer stays outside the box", () => {
  const def = md(answer("definition"));
  assert.match(def, /<\/div><\/div>\n<p>Je peux vous aider à construire un tableau de bord/);
  assert.doesNotMatch(def, /md-callout-body[^]*Je peux vous aider[^]*<\/div><\/div>/);
  const mail =
    "Bonjour M. Dupont,\n\nAttention, nous avons le regret de vous informer que la livraison est reportée au 12 mars.\n\nCordialement,\nPaul";
  assert.doesNotMatch(md(mail), /md-callout/);
  assert.doesNotMatch(md("Attention, nous avons le regret de vous informer du report."), /md-callout/);
  assert.doesNotMatch(md("Bonjour,\n\nAttention : le bureau sera fermé lundi."), /md-callout/);
  assert.match(md("Attention, vous devez sauvegarder avant la mise à jour."), /md-callout--warn/);
  const offer = md("Attention : sauvegardez avant. Souhaitez-vous la procédure complète ?");
  assert.match(offer, /md-callout--warn[^]*sauvegardez avant\.<\/p><\/div><\/div>\n<p>Souhaitez-vous la procédure complète \?<\/p>/);
  assert.match(md("**Conseil :** testez d'abord."), /<strong class="md-callout-label">Conseil<\/strong> : testez/);
});

test("dialogues and transcripts stay text lines, not label/value rows", () => {
  for (const s of [
    "Client : Bonjour\nMoi : Bonjour, que puis-je faire ?\nClient : Rien",
    "Agent : Que puis-je faire pour vous ?\nClient : Je voudrais un devis.",
    "Marie : On lance quand ?\nPaul : Lundi !",
  ]) {
    const out = md(s);
    assert.doesNotMatch(out, /md-pairs/, s);
    assert.match(out, /^<p>[^]*<br>/, s);
  }
  assert.match(md("Date : 12 mars\nLieu : Paris\nDurée : 2 h"), /md-pairs/);
});

test("pros/cons need real pros and cons labels", () => {
  for (const s of [
    "Pour vos salariés\n- a\n- b\n\nRisques juridiques\n- c\n- d",
    "Pour l'entreprise\n- a\n\nContre-indications\n- b",
    "Atouts du site\n- a\n\nRisques\n- b",
  ])
    assert.doesNotMatch(md(s), /md-proscons/, s);
  for (const s of ["Pour\n- a\n\nContre\n- b", "Avantages\n- a\n\nRisques\n- b", "Points forts\n- a\n\nLimites\n- b"])
    assert.match(md(s), /md-proscons/, s);
});

test("key numbers: dates, phone numbers and years are not figures", () => {
  for (const s of [
    "- Dépôt du dossier : 15 mars 2025\n- Instruction : 2 avril 2025\n- Décision : 30 juin 2025",
    "- Téléphone : 01 23 45 67 89\n- Fax : 01 23 45 67 90\n- Poste : 0612345678",
    "- Création : 1998\n- Rachat : 2012\n- Introduction en bourse : 2021",
    "- Salles : 3\n- Étages : 2\n- Bureaux : 14",
  ])
    assert.doesNotMatch(md(s), /md-kpis/, s);
  assert.match(md("- CA : 412 000 €\n- Marge : 38 %\n- Clients : 14"), /md-kpis/);
  assert.match(md("- Visiteurs : 12 400\n- Inscrits : 860\n- Abonnés : 95"), /md-kpis/);
});

test("an indented paragraph under a list item stays in that item", () => {
  const out = md("* x\n\n  suite de x\n* y");
  assert.doesNotMatch(out, /<h4/);
  assert.equal((out.match(/<ul/g) || []).length, 1);
  assert.match(out, /<li>x<br><br>suite de x<\/li><li>y<\/li>/);
  assert.match(md("- a\n\n    détail du point a\n\n- b"), /<li>a<br><br>détail du point a<\/li><li>b/);
  assert.match(md("- a\n\n```\ncode\n```"), /<\/ul>\n<figure class="code-block/); // a fence is not a continuation
  assert.match(md("- a\n\nSuite du texte."), /<\/ul>\n<p>Suite du texte/); // not indented: a new paragraph
  assert.doesNotMatch(md("  Sécurité\n- a"), /<h4/); // an indented line is never a heading
});
