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
# A scripted document per template (the demo « model » picks the template from the words, as the real one
# does from the request): every expected section, with the blocks a document can hold (a key point, a table, a
# picture with its caption, a warning, a footnote). Marked as an example throughout.
DOC_BODIES = {
    "cadrage": [
        ("Contexte", "Le projet répond à un besoin exprimé par les équipes[^1]. Ce document en fixe le cadre.",
         "cle", "Un cadre partagé avant de lancer les travaux."),
        ("Objectifs", "- Clarifier le résultat attendu\n- Fixer les critères de réussite\n- Aligner les équipes", "", ""),
        ("Périmètre", "## Inclus\n- Les équipes pilotes\n- Les outils actuels\n## Exclu\n- La refonte du système "
                      "d'information", "image", ""),
        ("Planning", "| Étape | Échéance | Responsable |\n|---|---|---|\n| Cadrage | Semaine 1 | Chef de projet |\n"
                     "| Pilote | Semaine 3 | Équipe pilote |\n| Bilan | Semaine 6 | Comité |", "", ""),
        ("Risques", "- Disponibilité des équipes\n- Données incomplètes", "attention",
         "Les éléments de cet exemple sont fictifs : à remplacer par les vôtres."),
    ],
    "compte-rendu": [
        ("Participants", "- Équipe projet (exemple)\n- Référent métier (exemple)", "", ""),
        ("Points abordés", "L'équipe a fait le point sur l'avancement[^1].", "", ""),
        ("Décisions", "- Lancer le pilote\n- Revoir le planning dans trois semaines", "cle",
         "Le pilote démarre la semaine prochaine."),
        ("Actions", "| Action | Responsable | Échéance |\n|---|---|---|\n| Préparer le pilote | Équipe projet | "
                    "Semaine 1 |\n| Informer les équipes | Référent | Semaine 2 |", "", ""),
    ],
    "procedure": [
        ("Objet", "Cette procédure décrit les étapes à suivre[^1].", "cle", "Une étape à la fois, dans l'ordre."),
        ("Champ d'application", "- Les équipes concernées\n- Les outils utilisés", "", ""),
        ("Étapes", "1. Préparer\n2. Réaliser\n3. Vérifier\n4. Archiver", "image", ""),
        ("Points de vigilance", "- Vérifier chaque étape avant de passer à la suivante", "attention",
         "Exemple scripté : adaptez chaque étape à votre organisation."),
    ],
    "proposition": [
        ("Votre besoin", "Vous cherchez une solution simple et fiable[^1].", "", ""),
        ("Notre solution", "- Une offre adaptée\n- Un accompagnement dédié\n- Un suivi mensuel", "image", ""),
        ("Bénéfices", "Moins de temps perdu, plus de visibilité.", "cle", "Un interlocuteur unique."),
        ("Tarifs", "| Formule | Contenu | Prix |\n|---|---|---|\n| Essentiel | Exemple | À définir |\n| Complet | "
                   "Exemple | À définir |", "", ""),
        ("Prochaines étapes", "- Un échange pour préciser le besoin\n- Une proposition détaillée", "", ""),
    ],
    "rapport": [
        ("Synthèse", "Ce rapport présente le sujet, les constats et des recommandations[^1].", "cle",
         "Commencer petit, mesurer, puis généraliser."),
        ("Constats", "- Les usages progressent\n- Les attentes des équipes sont claires\n- Le budget reste contraint",
         "image", ""),
        ("Options", "| Option | Avantage | Limite |\n|---|---|---|\n| Pilote court | Rapide | Peu de recul |\n"
                    "| Déploiement large | Effet global | Risque élevé |", "", ""),
        ("Recommandations", "Commencer par un pilote de six semaines, puis décider sur des chiffres mesurés.",
         "attention", "Les éléments de cet exemple sont fictifs : à remplacer par les vôtres."),
        ("Conclusion", "Un pilote court donne les chiffres qui manquent pour décider.", "", ""),
    ],
}  # fmt: skip
LETTER = {
    "fr": "Madame, Monsieur,\n\nPar la présente, je vous fais part de ma demande. Ce courrier est un exemple scripté "
          "(mode démo) : remplacez-le par votre situation.\n\nJe vous remercie de bien vouloir m'en confirmer la "
          "bonne réception.\n\nVeuillez agréer, Madame, Monsieur, mes salutations distinguées.",
    "en": "Dear Sir or Madam,\n\nI am writing to make my request. This letter is a scripted example (demo mode): "
          "replace it with your situation.\n\nThank you for confirming receipt.\n\nYours faithfully,",
}  # fmt: skip


def doc_text(subject: str, query: str, lg: str, words: str) -> str:
    from birds.canvas import templates

    tid = templates.hint(words) or templates.DEFAULT
    head = f"---\ntitle: {subject}\nsubtitle: {'Exemple de démonstration' if lg == 'fr' else 'Demo example'}\n"
    head += f"template: {tid}\n---\n"
    if tid == "lettre":
        return head + f"# {'Lettre' if lg == 'fr' else 'Letter'}\n" + LETTER[lg] + "\n"
    out = [head]
    for title, body, extra, extra_text in DOC_BODIES.get(tid, DOC_BODIES["rapport"]):
        out.append(f"# {title}\n{body}\n")
        if extra == "image":
            out.append(f'::: image query="{query}" caption="Illustration de l\'exemple"\n:::\n')
        elif extra:
            out.append(f"::: {extra}\n{extra_text}\n:::\n")
    out.append("[^1]: Exemple de source (contenu scripté du mode démo).\n")
    return "".join(out)


PAGE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{subject}</title>
<style>
  :root {{ --ink: #14213d; --accent: #1e5bd8; --soft: #eef3fd; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, sans-serif; color: var(--ink); background: #fff; }}
  header {{ padding: 56px 24px 40px; background: linear-gradient(135deg, var(--soft), #fff); text-align: center; }}
  h1 {{ font-size: clamp(28px, 6vw, 44px); margin: 0 0 12px; }}
  p.lead {{ font-size: 18px; color: #4a5568; max-width: 560px; margin: 0 auto 24px; }}
  button {{ font: inherit; padding: 12px 22px; border: 0; border-radius: 999px; background: var(--accent);
           color: #fff; cursor: pointer; }}
  section {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            padding: 32px 24px; max-width: 900px; margin: 0 auto; }}
  .card {{ padding: 20px; border-radius: 14px; background: var(--soft); }}
  .card b {{ display: block; margin-bottom: 6px; }}
  #count {{ font-weight: 700; }}
</style>
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
<script>
  let n = 0;
  document.getElementById("cta").addEventListener("click", () => {{
    n += 1;
    document.getElementById("count").textContent = n;
    console.log("clic", n);
  }});
</script>
</body>
</html>"""
PAGE_TEXT = {
    "fr": {"lead": "Une page d'exemple, écrite en démo : HTML, CSS et JavaScript dans un seul fichier.",
           "cta": "Essayer", "clicks": "Clics :", "c1": "Rapide", "c1t": "Aucune ressource externe.",
           "c2": "Lisible", "c2t": "Un seul fichier à relire.", "c3": "Sûr", "c3t": "Aperçu isolé, sans réseau."},
    "en": {"lead": "A sample page, written in demo mode: HTML, CSS and JavaScript in one file.",
           "cta": "Try it", "clicks": "Clicks:", "c1": "Fast", "c1t": "No external resource.",
           "c2": "Readable", "c2t": "One file to review.", "c3": "Safe", "c3t": "Isolated preview, no network."},
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
            return doc_text(subject, _q(subject), lg, words)
        if p.kind == "diagram":
            return f"```mermaid\n{FLOW[lg]}\n```\n" + SCRIPTED[lg]
        t = PAGE_TEXT[lg]
        return f"```html\n{PAGE.format(lang=lg, subject=subject, **t)}\n```\n" + SCRIPTED[lg]
    base = p.base or {}
    if base.get("kind") == "code":
        code = (base.get("code") or {}).get("text") or ""
        colors = {"bleu": "#1e5bd8", "blue": "#1e5bd8", "vert": "#0d9488", "green": "#0d9488", "rouge": "#c2410c",
                  "red": "#c2410c", "orange": "#ea580c", "violet": "#6d28d9", "purple": "#6d28d9"}  # fmt: skip
        hit = next((v for k, v in colors.items() if re.search(rf"\b{k}\b", words, re.I)), None)
        if hit and "--accent:" in code:
            code = re.sub(r"--accent:\s*#[0-9a-fA-F]{3,8}", f"--accent: {hit}", code)
            return f"```{(base.get('code') or {}).get('lang') or 'html'}\n{code}\n```"
        return ""
    if p.target and p.variants:
        b = next(x for x in base.get("blocks") or [] if x["id"] == p.target)
        return variants_text(b, lg)
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
                  words, re.I) or re.search(r"\b(?:ajoute|add)\w*\s+(?:une|la|a|the)\s+(?:section|partie)\s+"
                                            r"(?P<s>[^.?!\n]{2,40}?)\s+(?:au|to the)\s+document", words, re.I)  # fmt: skip
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


def variants_text(b: dict, lg: str) -> str:
    """Two scripted rewrites of a section: a concise one (first sentence, two points) and one that leads with a
    key point taken from the section itself (nothing new is said)."""
    short, lead = [f"# {b.get('title') or ''}"], [f"# {b.get('title') or ''}"]
    first = ""
    for part in b.get("parts") or []:
        if part["t"] == "list":
            items = [i.strip() for i in part["items"] if i.strip()]
            first = first or (items[0] if items else "")
            short += [f"- {i}" for i in items[:2]]
            lead += [f"- {i}" for i in items]
        elif part["t"] == "text":
            sentence = part["text"].split(". ")[0].rstrip(".") + "."
            first = first or sentence
            short.append(sentence)
            lead.append(part["text"])
        else:
            lead += dsl._part_dsl(part)
    key = "cle" if lg == "fr" else "key"
    lead[1:1] = [f"::: {key}", first or (b.get("title") or ""), ":::"]
    marker = "@variante" if lg == "fr" else "@variant"
    return f"{marker} 1\n" + "\n".join(short) + f"\n{marker} 2\n" + "\n".join(lead) + "\n"


def _ref(demo_run, p: turn.Plan, doc: dict | None, version: int, variants: bool = False) -> None:
    """The answer's link to the artifact (its version, and for a document the next-step chips)."""
    from types import SimpleNamespace

    from birds.web.canvas_web import ref

    info = {"aid": p.aid, "version": version, "doc": doc or p.base or {}}
    if variants:
        info["variants"] = True
    demo_run.adopted = ref(SimpleNamespace(canvas=info))


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
        _ref(demo_run, p, doc, p.version + 1)
        demo_run.finish(p.said if done else DEMO_LIMIT[lg])
        return
    text = scripted(p, words, lang)
    if not text:
        demo_run.finish(DEMO_LIMIT[lg])
        return
    demo_run.think("Je rédige le contenu bloc par bloc ; le canevas l'affiche au fur et à mesure.",
                   "I write the content block by block; the canvas shows it as it comes.")  # fmt: skip
    if p.variants:
        base = next(b for b in p.base["blocks"] if b["id"] == p.target)
        found = turn.parse_variants(text, base, lang)
        demo_run.pause(0.4)
        ctx.emit({"type": "canvas", "phase": "variants", "aid": p.aid, "base": p.version, "kind": "doc",
                  "target": p.target, "blocks": found[:2]})  # fmt: skip
        _ref(demo_run, p, None, p.version, variants=True)
        title = base.get("title") or ""
        demo_run.finish((f"Deux variantes de la section « {title} » : choisissez-en une dans le canevas, ou gardez "
                         "l'actuelle." if lg == "fr" else f"Two variants of the section \"{title}\": choose one in "
                         "the canvas, or keep the current one.") + "\n\n" + SCRIPTED[lg])  # fmt: skip
        return
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
    emit_doc(ctx, p, doc, "final", lang, label="Création" if p.mode == "create" else words[:80])
    version = 1 if p.mode == "create" else p.version + 1
    _ref(demo_run, p, doc, version)
    said = turn.chat_text("code" if p.kind == "diagram" else kind, doc, lang,
                          verb="create" if p.mode == "create" else "patch", version=version)  # fmt: skip
    demo_run.extra_completion += len(text) // 4
    demo_run.finish(said + "\n\n" + SCRIPTED[lg])


def _illustrate(ctx, p: turn.Plan, doc: dict, lang: str) -> None:
    if doc.get("kind") not in ("deck", "doc"):
        return
    found = images.resolve(doc, images.finder("demo", theme=doc.get("theme"), lang=lang), limit=turn.IMAGE_LIMIT)
    if found:
        ctx.emit({"type": "canvas_media", "aid": p.aid, "media": found})
