"""The canvas in demo mode: scripted content (no model), streamed and parsed by the same code as a real turn.

Every scripted figure is marked as an example, and the chat says the content is scripted. Pictures are the drawn
illustrations of birds.canvas.images (labelled as such): the demo never fetches anything.
"""

from __future__ import annotations

import hashlib
import re

from birds.canvas import convert, dsl, images, patch, turn

DECK = {
    "fr": """---
title: {subject}
subtitle: Exemple de démonstration
---
# Contexte
- Pourquoi le sujet compte aujourd'hui
- Ce que l'équipe a déjà observé
- Ce qui reste à décider
::: image query="{query}"
:::
# Chiffres clés (exemple)
::: kpi
3 | équipes pilotes
6 semaines | de test
2 | indicateurs suivis
:::
# Calendrier
::: timeline
Semaine 1 : cadrage
Semaine 3 : pilote
Semaine 6 : bilan
:::
# Ce qu'on attend
> « Mesurer avant de généraliser. »
> — Principe du pilote
# Prochaines étapes
- Choisir l'équipe pilote
- Fixer les indicateurs
- Planifier le bilan
""",
    "en": """---
title: {subject}
subtitle: Demo example
---
# Context
- Why the topic matters now
- What the team has already seen
- What is still to decide
::: image query="{query}"
:::
# Key figures (example)
::: kpi
3 | pilot teams
6 weeks | of testing
2 | indicators followed
:::
# Timeline
::: timeline
Week 1: scoping
Week 3: pilot
Week 6: review
:::
# What we expect
> "Measure before rolling out."
> — Pilot principle
# Next steps
- Pick the pilot team
- Set the indicators
- Plan the review
""",
}
DOC = {
    "fr": """---
title: {subject}
subtitle: Exemple de démonstration
---
# Objet
Cette note présente le sujet, les options et une recommandation. Le contenu est un exemple scripté.
# Constat
- Les usages progressent
- Les attentes des équipes sont claires
- Le budget reste contraint
::: image query="{query}"
:::
# Options
| Option | Avantage | Limite |
|---|---|---|
| Pilote court | Rapide | Peu de recul |
| Déploiement large | Effet global | Risque élevé |
# Recommandation
Commencer par un pilote de six semaines, puis décider sur des chiffres mesurés.
::: attention
Les chiffres de cet exemple sont fictifs : à remplacer par les vôtres.
:::
""",
    "en": """---
title: {subject}
subtitle: Demo example
---
# Purpose
This note presents the topic, the options and a recommendation. The content is a scripted example.
# Findings
- Usage is growing
- The teams' expectations are clear
- The budget is tight
::: image query="{query}"
:::
# Options
| Option | Upside | Limit |
|---|---|---|
| Short pilot | Fast | Little hindsight |
| Wide rollout | Global effect | High risk |
# Recommendation
Start with a six-week pilot, then decide on measured figures.
::: warning
The figures of this example are made up: replace them with yours.
:::
""",
}
PAGE_HTML = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{subject}</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>{subject}</h1>
  <p class="lead">{lead}</p>
  <button id="cta" type="button">{cta}</button>
  <p>{clicks} <span id="count">0</span></p>
</header>
<section>
  <div class="card"><b>{c1}</b>{c1t}</div>
  <div class="card"><b>{c2}</b>{c2t}</div>
  <div class="card"><b>{c3}</b>{c3t}</div>
</section>
<script src="script.js"></script>
</body>
</html>"""
PAGE_CSS = """:root { --ink: #14213d; --accent: #1e5bd8; --soft: #eef3fd; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; color: var(--ink); background: #fff; }
header { padding: 56px 24px 40px; background: linear-gradient(135deg, var(--soft), #fff); text-align: center; }
h1 { font-size: clamp(28px, 6vw, 44px); margin: 0 0 12px; }
p.lead { font-size: 18px; color: #4a5568; max-width: 560px; margin: 0 auto 24px; }
button { font: inherit; padding: 12px 22px; border: 0; border-radius: 999px; background: var(--accent);
  color: #fff; cursor: pointer; }
section { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  padding: 32px 24px; max-width: 900px; margin: 0 auto; }
.card { padding: 20px; border-radius: 14px; background: var(--soft); }
.card b { display: block; margin-bottom: 6px; }
#count { font-weight: 700; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e6ebf5; --soft: #1b2436; }
  body { background: #0f1522; }
  header { background: linear-gradient(135deg, var(--soft), #0f1522); }
  p.lead { color: #aab4c8; }
}"""
PAGE_JS = """let n = 0;
const count = document.getElementById("count");
document.getElementById("cta").addEventListener("click", () => {
  n += 1;
  count.textContent = n;
  console.log("clic", n);
});"""
PAGE_TEXT = {
    "fr": {"lead": "Une page d'exemple, écrite en démo : HTML, CSS et JavaScript en trois fichiers.",
           "cta": "Essayer", "clicks": "Clics :", "c1": "Rapide", "c1t": "Aucune ressource externe.",
           "c2": "Lisible", "c2t": "Trois fichiers courts à relire.", "c3": "Sûr", "c3t": "Aperçu isolé, sans réseau."},
    "en": {"lead": "A sample page, written in demo mode: HTML, CSS and JavaScript in three files.",
           "cta": "Try it", "clicks": "Clicks:", "c1": "Fast", "c1t": "No external resource.",
           "c2": "Readable", "c2t": "Three short files to review.", "c3": "Safe", "c3t": "Isolated preview, no network."},
}  # fmt: skip
FLOW = {
    "fr": """flowchart TD
  A[Demande reçue] --> B{Informations complètes ?}
  B -->|oui| C[Analyse]
  B -->|non| D[Relance du demandeur]
  D --> B
  C --> E{Validation ?}
  E -->|oui| F[Mise en œuvre]
  E -->|non| G[Clôture motivée]
  F --> H[Bilan]""",
    "en": """flowchart TD
  A[Request received] --> B{Complete information?}
  B -->|yes| C[Analysis]
  B -->|no| D[Follow up with requester]
  D --> B
  C --> E{Approved?}
  E -->|yes| F[Implementation]
  E -->|no| G[Reasoned closure]
  F --> H[Review]""",
}
SCRIPTED = {
    "fr": "Contenu scripté (mode démo : aucun modèle ne tourne).",
    "en": "Scripted content (demo mode: no model runs).",
}
DEMO_LIMIT = {
    "fr": "En mode démo, je sais ajouter une diapositive ou une section, raccourcir, changer le thème, déplacer, "
    "dupliquer, supprimer ou changer une image. Le vrai modèle fait le reste.",
    "en": "In demo mode I can add a slide or a section, shorten, change the theme, move, duplicate, delete or change "
    "a picture. The real model does the rest.",
}


def _q(text: str) -> str:
    return re.sub(r"[\"\n]", " ", text)[:60].strip()


def scripted(p: turn.Plan, words: str, lang: str) -> str:
    """What the « model » writes in demo mode for this plan."""
    lg = "en" if lang == "en" else "fr"
    subject = convert.subject(words) or ("Projet pilote" if lg == "fr" else "Pilot project")
    if p.mode == "create":
        if p.kind == "deck":
            return DECK[lg].format(subject=subject, query=_q(subject))
        if p.kind == "doc":
            return DOC[lg].format(subject=subject, query=_q(subject))
        if p.kind == "diagram":
            return f"```mermaid\n{FLOW[lg]}\n```\n" + SCRIPTED[lg]
        t = PAGE_TEXT[lg]
        html = PAGE_HTML.format(lang=lg, subject=subject, **t)
        return (f"```html index.html\n{html}\n```\n```css style.css\n{PAGE_CSS}\n```\n"
                f"```js script.js\n{PAGE_JS}\n```\n" + SCRIPTED[lg])  # fmt: skip
    base = p.base or {}
    if base.get("kind") == "code":
        from birds.canvas import code as codefiles

        files = {f["name"]: f for f in codefiles.files_of(base)}
        if re.search(r"\b(?:corrige\w*|r[ée]pare\w*|fix\w*)\b", words, re.I):
            # « Corriger avec Bird »: the scripted files are the demo's known-good version
            fixed = {"script.js": ("js", PAGE_JS), "style.css": ("css", PAGE_CSS)}
            out = [f"```{lang_} {name}\n{text}\n```" for name, (lang_, text) in fixed.items()
                   if name in files and files[name]["text"] != text]  # fmt: skip
            return "\n".join(out)
        colors = {"bleu": "#1e5bd8", "blue": "#1e5bd8", "vert": "#0d9488", "green": "#0d9488", "rouge": "#c2410c",
                  "red": "#c2410c", "orange": "#ea580c", "violet": "#6d28d9", "purple": "#6d28d9"}  # fmt: skip
        hit = next((v for k, v in colors.items() if re.search(rf"\b{k}\b", words, re.I)), None)
        for f in files.values():
            if hit and "--accent:" in f["text"]:
                text = re.sub(r"--accent:\s*#[0-9a-fA-F]{3,8}", f"--accent: {hit}", f["text"])
                return f"```{f['lang']} {f['name']}\n{text}\n```"
        return ""
    if p.target:
        b = next(x for x in base.get("blocks") or [] if x["id"] == p.target)
        lines = [f"# {b.get('title') or ''}"]
        for part in b.get("parts") or []:
            if part["t"] == "list":
                lines += [f"- {' '.join(i.split()[:6])}" for i in part["items"][:3]]
            elif part["t"] == "text":
                lines.append(part["text"].split(". ")[0].rstrip(".") + ".")
            else:
                lines += dsl._part_dsl(part)
        return "\n".join(lines)
    if re.search(r"\b(?:plus court|raccourci\w*|r[ée]sum\w*|all[èe]ge\w*|condense\w*|shorter|shorten)\b", words, re.I):
        out = dsl.clone(base)
        for b in out.get("blocks") or []:
            for part in b.get("parts") or []:
                if part["t"] == "list":
                    part["items"] = [i for i in part["items"] if not i.startswith("  ")][:2]
                elif part["t"] == "text":
                    part["text"] = part["text"].split(". ")[0].rstrip(".") + "."
        return dsl.to_dsl(out, ids=True)
    m = re.search(r"\b(?:ajoute|rajoute|ins[èe]re|add)\w*\b.{0,40}?\b(?:sur|about|on|concernant)\s+(?P<s>[^.?!\n]{2,60})",
                  words, re.I)  # fmt: skip
    if m:
        title = m.group("s").strip()
        title = title[:1].upper() + title[1:]
        after = re.search(r"\b(?:apr[èe]s|after)\b", words, re.I)
        head = "" if after else "@add\n"
        if lg == "fr":
            body = f"- {title} : point à préciser\n- Ce qui pourrait arriver\n- Comment le limiter"
        else:
            body = f"- {title}: point to specify\n- What could happen\n- How to limit it"
        return f"{head}# {title}\n{body}\n"
    return ""


def run(demo_run, p: turn.Plan, words: str) -> None:
    """One demo canvas turn, start to end (events, answer, usage)."""
    from birds.web.canvas_web import emit_doc

    ctx, lang = demo_run.ctx, demo_run.lang
    lg = "en" if lang == "en" else "fr"
    if p.mode == "create":  # the demo is deterministic: same words, same artifact id
        p.aid = "a" + hashlib.sha256(words.encode("utf-8")).hexdigest()[:12]
    if p.mode == "reopen":
        from birds.web.canvas_web import emit_reopen

        emit_reopen(ctx, p)
        demo_run.finish(p.said)
        return
    if p.mode == "direct":
        doc, done, failed = patch.apply_all(p.base, p.ops or [])
        _illustrate(ctx, p, doc, lang)
        emit_doc(ctx, p, doc, "final", lang, label=p.said)
        demo_run.finish(p.said if done else DEMO_LIMIT[lg])
        return
    text = scripted(p, words, lang)
    if not text:
        demo_run.finish(DEMO_LIMIT[lg])
        return
    demo_run.think("Je rédige le contenu bloc par bloc ; le canevas l'affiche au fur et à mesure.",
                   "I write the content block by block; the canvas shows it as it comes.")  # fmt: skip
    stream = turn.Stream(turn.compute_for(p, words, lang), lambda d: emit_doc(ctx, p, d, "stream", lang))
    for piece in re.findall(r"[^\n]*\n|[^\n]+", text):
        stream.feed(piece)
        demo_run.pause(0.06)
    stream.flush()
    doc = turn.compute_for(p, words, lang)(text)
    if doc is None:
        demo_run.finish(DEMO_LIMIT[lg])
        return
    kind = doc.get("kind")
    if p.mode == "create" and kind in ("deck", "doc"):
        turn.finish_doc(doc, kind, words, lang)
    _illustrate(ctx, p, doc, lang)
    from birds.web.canvas_web import code_changes

    doc.get("code", {}).pop("open", None)
    changes = code_changes(p, doc)
    if changes == []:
        emit_doc(ctx, p, None, "abort", lang)
        demo_run.finish(DEMO_LIMIT[lg])
        return
    emit_doc(ctx, p, doc, "final", lang, label="Création" if p.mode == "create" else words[:80], changes=changes)
    said = turn.chat_text("code" if p.kind == "diagram" else kind, doc, lang,
                          verb="create" if p.mode == "create" else "patch", changes=changes)  # fmt: skip
    demo_run.extra_completion += len(text) // 4
    from types import SimpleNamespace

    from birds.web.canvas_web import ref

    version = 1 if p.mode == "create" else p.version + 1
    demo_run.adopted = ref(SimpleNamespace(canvas={"aid": p.aid, "version": version, "doc": doc}))  # the answer's link
    demo_run.finish(said + "\n\n" + SCRIPTED[lg])


def _illustrate(ctx, p: turn.Plan, doc: dict, lang: str) -> None:
    if doc.get("kind") not in ("deck", "doc"):
        return
    found = images.resolve(doc, images.finder("demo", theme=doc.get("theme"), lang=lang), limit=turn.IMAGE_LIMIT)
    if found:
        ctx.emit({"type": "canvas_media", "aid": p.aid, "media": found})
