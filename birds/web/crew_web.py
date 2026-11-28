"""Mode Agent in the web app: SSE mapping of the crew's events, the backend hook, and the demo's scripted team.

Kept apart from backends.py (a few hooks there): the crew itself lives in birds.harness.crew.
"""

from __future__ import annotations

import dataclasses
import re
import secrets
import time
from pathlib import Path

from birds.web import tokens
from birds.web.backends import (
    ChatRequest,
    RunContext,
    _plain,
    document_text,
    step_event,
)


def on_agent(ctx: RunContext, lang: str, offset, step_end):
    """The crew's events -> SSE events. ``offset()`` shifts tool step indices (images read before the run);
    ``step_end(index, step, lang)`` is HarnessBackend._step_event. Tool steps carry the lane id as ``agent``."""

    def emit(ev: dict) -> None:
        kind = ev.get("kind")
        if kind == "tool_start":
            ctx.check()
            out = step_event(ev["index"] + offset(), ev["tool"], _plain(ev["arguments"]), "running")
            ctx.emit({**out, "agent": ev["agent"]})
        elif kind == "tool_end":
            ctx.emit({**step_end(ev["index"] + offset(), ev["step"], lang), "agent": ev["agent"]})
        elif kind == "slice":  # a long task's state, signed: the next slice (auto) or a checkpoint after a reload
            token = ctx.sign(_plain(ev["state"]))
            ctx.emit({"type": "agent_slice", "token": token, "final": not ev["auto"], "auto": bool(ev["auto"]),
                      "slice": ev["state"].get("slice", 0), "run": ev["state"].get("run"),
                      "exp": tokens.expiry(token)})  # fmt: skip  # the browser forgets it once expired
        else:
            ctx.check()
            ctx.emit(_plain(ev))

    return emit


def decide_for(request: ChatRequest, words: str, n_docs: int, n_images: int, lang: str):
    from birds.harness.crew import decide

    prior = any(m.get("role") == "assistant" and str(m.get("content") or "").strip() for m in request.messages[:-1])
    return decide(
        words,
        attachments=n_docs,
        images=n_images,
        mode=getattr(request, "agent", "auto") or "auto",
        resume=request.resume is not None,
        lang=lang,
        history=prior,
    )


def run_crew(
    agent, decision, request: ChatRequest, ctx: RunContext, *, user_sent, words, system, lang, names, workspace,
    history=None,
):
    """The crew run for this request, or None when the single agent answers (no recipe, mode off...).
    Activé with nothing to split up: an agent_done event tells the chip, then the single agent answers."""
    from birds.harness import crew_plan
    from birds.harness.agent import Run
    from birds.harness.crew import Crew, Decision

    if request.agent_slice is not None:  # the next slice of a long task: the brief comes from the signed state
        return _continue_slice(agent, request, ctx, history)
    plan = None
    if request.agent_plan is not None:  # « Lancer »: the decision and plan the card showed, with the user's edits
        got = request.agent_plan["payload"]
        decision = Decision(str(got.get("recipe")), str(got.get("reason") or ""), str(got.get("mode") or "auto"),
                            bool(got.get("forced")), got.get("deliverable"), dict(got.get("signals") or {}))  # fmt: skip
        plan = crew_plan.from_public(got.get("plan"))
        if plan is not None:
            plan, _ = crew_plan.apply_edits(plan, request.agent_plan.get("edits"))
    if decision.recipe is None:
        if decision.no_deliverable:
            ctx.emit({"type": "agent_done", "recipe": None, "ok": False, "reason": "no_deliverable",
                      "message": decision.reason, "calls": 0, "caveats": []})  # fmt: skip
        return None
    if plan is None:
        plan = crew_plan.make_plan(decision, words, lang)
        if request.agent_flow == "plan":  # the plan card first: nothing generated, the browser launches it
            payload = {"k": "crew_plan", "recipe": decision.recipe, "reason": decision.reason, "mode": decision.mode,
                       "forced": decision.forced, "deliverable": decision.deliverable,
                       "signals": _plain(decision.signals), "plan": plan.public(lang)}  # fmt: skip
            ctx.emit({"type": "agent_plan", "plan": plan.public(lang), "token": ctx.sign(payload),
                      "auto_start": crew_plan.auto_start(plan, decision.mode), "mode": decision.mode,
                      "recipe": decision.recipe, "reason": decision.reason, "forced": decision.forced})  # fmt: skip
            return Run(lang=lang, stop_reason="plan")
    docs = [(Path(n).name, document_text(Path(workspace) / n, lang)) for n in names]
    run_id = secrets.token_urlsafe(12)
    box = _open_notes(run_id, request, ctx)
    crew = Crew(
        agent,
        decision,
        system=system,
        thinking=request.thinking,
        lang=lang,
        deadline=ctx.deadline - 10,
        attached=bool(names),
        plan=plan,
        notes=box,
        run_id=run_id,
        slices=request.agent_flow == "plan" or request.agent_plan is not None,  # the app continues long tasks
    )
    try:
        return crew.run(user_sent, words, docs=docs, history=history)
    finally:
        crew_plan.REGISTRY.close(run_id, box)


def _open_notes(run_id: str, request: ChatRequest, ctx: RunContext):
    """The run's note box, with the notes the browser could not deliver live (sent with this request)."""
    from birds.harness import crew_plan

    box = crew_plan.REGISTRY.open(run_id)
    for n in request.agent_notes or []:
        note = crew_plan.parse_note(n.get("kind"), n.get("value"), n.get("id"))
        if note is not None:
            box.put(note)
    return box


def _continue_slice(agent, request: ChatRequest, ctx: RunContext, history):
    from birds.harness import crew_plan
    from birds.harness.crew import Crew

    state = request.agent_slice
    run_id = str(state.get("run") or "") or secrets.token_urlsafe(12)
    box = _open_notes(run_id, request, ctx)
    try:
        crew = Crew.from_slice(agent, state, deadline=ctx.deadline - 10, notes=box, history=history)
        return crew.continue_()
    finally:
        crew_plan.REGISTRY.close(run_id, box)


def resume_crew(agent, request: ChatRequest, ctx: RunContext):
    from birds.harness.crew import Crew

    state = request.resume.get("state") if isinstance(request.resume, dict) else None
    if not isinstance(state, dict) or state.get("k") != "crew" or not isinstance(state.get("args"), dict):
        raise ValueError("this confirmation carries an invalid state")
    if state.get("tool") not in ("make_slides", "make_document", "make_sheet", "draft_email"):
        raise ValueError("this confirmation carries an invalid state")
    return Crew.resume(agent, state, bool(request.decision), deadline=ctx.deadline - 5)


def usage_extra(report: dict) -> dict:
    """What the usage event gains for a crew run: per-role usage and the GPU time as a union of intervals."""
    if "agents" not in (report or {}):
        return {}
    return {
        "agents": report["agents"],
        "gpu_seconds_union": report.get("gpu_seconds_union"),
        "busy_seconds_sum": report.get("busy_seconds_sum"),
    }


# ------------------------------------------------------------------ demo: one scripted team (no model)

_DEMO_CREW = re.compile(r"pr[ée]sentation|diapo|slides?|deck", re.I)


def demo_match(text: str, request: ChatRequest) -> bool:
    """« présentation … chiffres … depuis 2019 » in Auto or Activé: the scripted team runs."""
    if getattr(request, "agent", "auto") == "off" or request.images or request.attachments:
        return False
    low = text.lower()
    return bool(
        _DEMO_CREW.search(low) and re.search(r"chiffr|figure|statisti", low) and re.search(r"depuis|since", low)
    )


_FACTS = {
    "fr": [
        ("2019", "4 %", "Avant la crise sanitaire, 4 % des salariés télétravaillaient au moins un jour par semaine"),
        ("2021", "22 %", "En 2021, 22 % des salariés ont télétravaillé au moins une fois par mois"),
        ("2023", "26 %", "En 2023, 26 % des salariés du privé télétravaillent au moins un jour par mois"),
        ("2023", "52 %", "Les cadres sont 52 % à télétravailler, contre 6 % des employés"),
    ],
    "en": [
        ("2019", "4%", "Before the pandemic, 4% of employees worked from home at least one day a week"),
        ("2021", "22%", "In 2021, 22% of employees worked from home at least once a month"),
        ("2023", "26%", "In 2023, 26% of private-sector employees work from home at least one day a month"),
        ("2023", "52%", "52% of managers work from home, against 6% of clerical staff"),
    ],
}


def _demo_decision(run):
    from birds.harness.crew import REASONS, Decision

    forced = getattr(run.req, "agent", "auto") == "on"
    sig = {"deliverable": "make_slides", "figures": True, "web": True, "steps": True, "n_docs": 0, "pasted_chars": 0}
    return Decision("deck_research", REASONS[run.lang]["deck_research"], "on" if forced else "auto", forced,
                    "make_slides", sig)  # fmt: skip


def demo_plan(run) -> None:
    """The demo's plan card (agent_flow « plan »): the same typed plan as a real run, nothing generated."""
    from birds.harness import crew_plan

    d = _demo_decision(run)
    last = next((m["content"] for m in reversed(run.req.messages) if m["role"] == "user"), "")
    plan = crew_plan.make_plan(d, last, run.lang)
    payload = {"k": "crew_plan", "recipe": d.recipe, "reason": d.reason, "mode": d.mode, "forced": d.forced,
               "deliverable": d.deliverable, "signals": d.signals, "plan": plan.public(run.lang)}  # fmt: skip
    run.ctx.emit({"type": "agent_plan", "plan": plan.public(run.lang), "token": run.ctx.sign(payload),
                  "auto_start": crew_plan.auto_start(plan, d.mode), "mode": d.mode, "recipe": d.recipe,
                  "reason": d.reason, "forced": d.forced, "demo": run.t("scénario de démonstration", "demo scenario")})  # fmt: skip


def demo_crew(run) -> None:
    """The demo's scripted Mode Agent: realistic lanes and timings, labelled « scénario de démonstration »."""
    from birds.harness import crew_plan

    if getattr(run.req, "agent_flow", None) == "plan" and run.req.agent_plan is None:
        return demo_plan(run)
    t, lang, ctx = run.t, run.lang, run.ctx
    forced = getattr(run.req, "agent", "auto") == "on"
    plan = None
    if run.req.agent_plan is not None:
        plan = crew_plan.from_public(run.req.agent_plan["payload"].get("plan"))
        if plan is not None:
            plan, _ = crew_plan.apply_edits(plan, run.req.agent_plan.get("edits"))
    run_id = secrets.token_urlsafe(12)
    box = _open_notes(run_id, run.req, ctx)
    try:
        _demo_team(run, t, lang, ctx, forced, plan, run_id, box)
    finally:
        crew_plan.REGISTRY.close(run_id, box)


def _demo_team(run, t, lang, ctx, forced, plan, run_id, box) -> None:
    stages = {"brief": "read", "drafts": "drafts", "check": "fix", "fix": "fix", "build": "build"}

    def notes(stage: str) -> None:  # the scripted team acknowledges the instructions as the real one does
        for n in box.take() if stage != "end" else box.close():
            late = stage in ("build", "end") or (n.kind == "prefer_site" and stage != "research")
            ctx.emit({"type": "agent_note", "id": n.id, "kind": n.kind, "value": n.value,
                      "status": "late" if late else "applied", "stage": stage})  # fmt: skip

    lanes = [
        ("chercheur", "chercheur", t("Recherche web", "Web search"), "research", ""),
        ("lecteur_1", "lecteur", t("Lecture page 1", "Reading page 1"), "brief", ""),
        ("lecteur_2", "lecteur", t("Lecture page 2", "Reading page 2"), "brief", ""),
        ("redacteur_a", "redacteur", t("Version A", "Version A"), "drafts", t("factuel et chronologique", "factual")),
        ("redacteur_b", "redacteur", t("Version B", "Version B"), "drafts", t("pour décideurs", "for decision makers")),
        ("verificateur", "verificateur", t("Vérification", "Check"), "check", ""),
        ("correcteur", "correcteur", t("Correction", "Fix"), "fix", ""),
        ("assembleur", "assembleur", t("Création du fichier", "Building the file"), "build", ""),
    ]
    ctx.emit(
        {
            "type": "agent_start",
            "recipe": "deck_research",
            "reason": t("présentation avec chiffres à sourcer", "a deck with figures to source"),
            "mode": "on" if forced else "auto",
            "forced": forced,
            "demo": t("scénario de démonstration", "demo scenario"),
            "lanes": [
                {"id": i, "role": r, "label": lab, "group": g, **({"detail": d} if d else {})}
                for i, r, lab, g, d in lanes
            ],
            "budget": {"max_calls": 7, "max_seconds": 240},
            "run": run_id,
            **({"plan": plan.public(lang)} if plan else {}),
        }
    )
    t0 = time.monotonic()

    def step(lane, role, phase, status, **extra):
        if status == "running" and phase in stages:
            notes(stages[phase])
        label = next(lab for i, _, lab, _, _ in lanes if i == lane)
        ctx.emit(
            {"type": "agent_step", "id": lane, "role": role, "phase": phase, "status": status, "label": label, **extra}
        )

    def tool(lane, name, args, summary, pause):
        index = run.steps
        run.steps += 1
        start = time.monotonic()
        ctx.emit({**step_event(index, name, args, "running"), "agent": lane})
        run.pause(pause)
        run.extra_completion += 24
        ctx.emit({**step_event(index, name, args, "done", summary, time.monotonic() - start), "agent": lane})

    def generate(lanes_, phase, seconds, tokens, done_detail):
        for lane, role in lanes_:
            step(lane, role, phase, "running", progress=0)
        for k in range(1, 5):
            run.pause(seconds / 4)
            for j, (lane, role) in enumerate(lanes_):
                step(lane, role, phase, "running", progress=round(min(1, k / 4 - j * 0.08), 2), tokens=tokens * k // 4)
        for (lane, role), detail in zip(lanes_, done_detail, strict=True):
            step(lane, role, phase, "done", progress=1, tokens=tokens, seconds=seconds, detail=detail)
        run.extra_completion += tokens * len(lanes_)

    step(
        "chercheur",
        "chercheur",
        "brief",
        "running",
        detail=t("télétravail France · statistiques · INSEE", "remote work France · statistics"),
    )
    q = t("télétravail en France statistiques", "remote work France statistics")
    tool("chercheur", "web_search", {"query": q}, t("5 résultats", "5 results"), 0.9)
    tool("chercheur", "read_page", {"url": "https://example.org/teletravail-2023"}, t("Page lue", "Page read"), 0.8)
    tool("chercheur", "read_page", {"url": "https://example.org/dares-teletravail"}, t("Page lue", "Page read"), 0.4)
    run.bytes += 18_000
    step("chercheur", "chercheur", "brief", "done", detail=t("2 pages lues", "2 pages read"), seconds=2.1)
    generate([("lecteur_1", "lecteur"), ("lecteur_2", "lecteur")], "brief", 1.6, 320,
             [t("3 chiffres vérifiés", "3 verified figures"), t("2 chiffres vérifiés", "2 verified figures")])  # fmt: skip
    generate([("redacteur_a", "redacteur"), ("redacteur_b", "redacteur")], "drafts", 2.6, 980, ["", ""])
    step("verificateur", "verificateur", "check", "running")
    run.pause(0.5)
    a = {"points": 1.0, "must": 1.0, "unsupported": 0, "structure": 1.0}
    b = {"points": 0.83, "must": 0.75, "unsupported": 0, "structure": 1.0}
    step("redacteur_a", "redacteur", "check", "scored", score=a, chosen=True)
    step("redacteur_b", "redacteur", "check", "scored", score=b, chosen=False)
    step("verificateur", "verificateur", "check", "done", chosen="redacteur_a", score=a,
         detail=t("Version A : 100 % des points, 0 chiffre non sourcé ✓ retenue", "Version A: 100% of points, 0 unsourced figure ✓ kept"))  # fmt: skip
    # both versions clean: the kept one takes a slide of the other that carries a fact it missed
    step("verificateur", "verificateur", "check", "done", chosen="redacteur_a", score=a, merged="redacteur_b",
         detail=t("Version A : 100 % des points, 0 chiffre non sourcé ✓ retenue · complétée par 1 partie(s) de Version B",
                  "Version A: 100% of points, 0 unsourced figure ✓ kept · completed with 1 part(s) of Version B"))  # fmt: skip
    step("correcteur", "correcteur", "fix", "skipped", detail=t("rien à corriger", "nothing to fix"))
    step("assembleur", "assembleur", "build", "running")
    facts = _FACTS[lang]
    slides = [
        {
            "title": t("Avant 2020 : une pratique marginale", "Before 2020: a marginal practice"),
            "bullets": [f"{facts[0][2]} [1]"],
        },
        {"title": t("2020-2021 : la bascule", "2020-2021: the switch"), "bullets": [f"{facts[1][2]} [1]"]},
        {"title": t("2023 : un usage installé", "2023: an established practice"), "bullets": [f"{facts[2][2]} [2]"]},
        {"title": t("Des écarts selon les métiers", "Gaps between jobs"), "bullets": [f"{facts[3][2]} [2]"]},
        {
            "title": t("Ce qu'il faut retenir", "What to remember"),
            "bullets": [
                t(
                    "Le télétravail s'est installé, surtout chez les cadres",
                    "Remote work is here to stay, mostly for managers",
                )
            ],
        },  # fmt: skip
        {
            "title": t("Pistes pour l'entreprise", "Options for the company"),
            "bullets": [t("Charte et outils communs", "A shared charter and tools")],
        },  # fmt: skip
        {"title": "Sources", "bullets": ["[1] example.org/teletravail-2023", "[2] example.org/dares-teletravail"]},
    ]
    arguments = {
        "title": t("Le télétravail en France depuis 2019", "Remote work in France since 2019"),
        "slides": slides,
    }
    emit = ctx.emit  # the file step is folded under the assembler's lane
    run.ctx = dataclasses.replace(
        ctx, emit=lambda e: emit({**e, "agent": "assembleur"} if e.get("type") == "step" else e)
    )
    try:
        entry = run.make_file("make_slides", arguments, t("7 diapositives", "7 slides"))
    finally:
        run.ctx = ctx
    step("assembleur", "assembleur", "build", "done", detail="pptx")
    notes("end")
    ctx.emit({"type": "agent_deliverable", "tool": "make_slides", "title": arguments["title"],
              "file": entry.get("name", ""), "parts": len(slides), "canvas": None})  # fmt: skip
    # the verification card: every figure of the scripted deck with the line of its (fictional) page
    pages = {1: "example.org", 2: "example.org"}
    items = [{"value": v, "sentence": f, "status": "verified", "origin": "source", "n": 1 if k < 2 else 2,
              "line": f"… {f.lower()} …", "site": pages[1 if k < 2 else 2], "title": ""}
             for k, (_, v, f) in enumerate(_FACTS[lang])]  # fmt: skip
    items.insert(0, {"value": "37 %", "sentence": t("Le télétravail atteint 37 % des salariés",
                                                    "Remote work reaches 37% of employees"),
                     "status": "removed", "origin": "none", "line": ""})  # fmt: skip
    ctx.emit({"type": "agent_checks", "verified_n": 4, "removed_n": 1, "review_n": 0, "items": items, "more": 0,
              "read_dropped": 1, "actions": [], "costs": 0,
              "sources": [{"n": 1, "title": "", "site": "example.org"}, {"n": 2, "title": "", "site": "example.org"}]})  # fmt: skip
    ctx.emit(
        {
            "type": "agent_done",
            "recipe": "deck_research",
            "ok": True,
            "chosen": "redacteur_a",
            "calls": 5,
            "agents": 7,
            "seconds": round(time.monotonic() - t0, 1),
            "gpu_seconds_union": None,
            "energy_wh": None,
            "caveats": [],
            "fixed": False,
        }
    )
    run.finish(
        t(
            "**Scénario de démonstration** (aucun modèle ne tourne ici) : voici ce que fait le mode Agent.\n\n"
            "La présentation « Le télétravail en France depuis 2019 » est prête : 6 diapositives et une diapositive "
            "Sources. Deux versions ont été rédigées en parallèle ; la vérification a retenu la version A, dont chaque "
            "chiffre se retrouve dans une page lue.\n\n"
            "**Ce que l'équipe a fait** :\n"
            "- Recherche : 1 recherche(s), 2 page(s) lue(s), 2 source(s) retenue(s) (example.org)\n"
            "- Lecture : 5 chiffre(s) vérifié(s) dans leur page\n"
            "- Rédaction : 2 version(s) en parallèle, Version A retenue, complétée par 1 partie(s) de Version B\n"
            "- Vérification : chiffres contrôlés contre le texte et les sources",
            "**Demo scenario** (no model runs here): this is what Agent mode does.\n\n"
            "The deck “Remote work in France since 2019” is ready: 6 slides and a Sources slide. Two versions were "
            "written in parallel; the check kept version A, whose every figure is found in a page that was read.\n\n"
            "**What the team did**:\n"
            "- Research: 1 search(es), 2 page(s) read, 2 source(s) kept (example.org)\n"
            "- Reading: 5 figure(s) checked in their page\n"
            "- Writing: 2 version(s) in parallel, Version A kept, completed with 1 part(s) of Version B\n"
            "- Check: figures checked against the text and sources",
        ),
        files=[entry],
        sources=[
            {
                "n": 1,
                "title": t("Télétravail en 2023 (exemple)", "Remote work in 2023 (example)"),
                "url": "https://example.org/teletravail-2023",
            },
            {
                "n": 2,
                "title": t("Le télétravail selon les métiers (exemple)", "Remote work by job (example)"),
                "url": "https://example.org/dares-teletravail",
            },
        ],  # fmt: skip
    )
