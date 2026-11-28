"""Live measurement of deep research on the real endpoint: the planning step before / after on 6 fixed prompts, and
whole runs (plan, SearXNG searches, pages read, extraction, report) after.

  BIRD_BASE_URL=https://….endpoints.huggingface.cloud BIRD_API_KEY=… BIRD_SEARXNG_URL=https://… \
    .venv/bin/python scripts/research_live.py --plan OUT.json [--before path/to/old_research.py]
  … scripts/research_live.py --full OUT.json --index 0

« before » is the planner of the previous recipe (its own plan_research tool: sub-questions and queries written
apart); « after » is Mode Agent's plan_search reused (each sub-question with its query, checked by
crew.checked_sub_questions). One generation per prompt and arm. The API key is read from the environment, never
printed. Results are written as JSON; docs/HARNESS.md holds the table.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPTS = [
    "Fais une recherche approfondie sur la filière hydrogène vert en France",
    "Recherche approfondie : l'AI Act et ses obligations pour une PME française",
    "Deep research on the European battery industry",
    "Fais une étude approfondie du marché des pompes à chaleur en France",
    "Peux-tu faire la carte des acteurs de l'éolien en mer en France ?",
    "Lance une recherche approfondie sur la semaine de quatre jours en Europe",
]
_OFFICIAL = re.compile(r"insee|gouv|ademe|eurostat|europa|rapport|report|statisti|officiel|official|loi\b|law|"
                       r"r[èe]glement|regulation|commission|minist|dares|iea|agence", re.I)  # fmt: skip


def agent(search: bool):
    import httpx

    from birds.harness import Agent, CompletionsClient, Config
    from birds.harness.agent import Hooks
    from birds.harness.template import TemplateTokenizer
    from birds.harness.tools.search import SearxngBackend

    llm = CompletionsClient(os.environ["BIRD_BASE_URL"], os.environ.get("BIRD_MODEL", "adubrou/Bird-S-4B"),
                            os.environ.get("BIRD_API_KEY", "proxy-injected"), timeout=240)  # fmt: skip
    http = httpx.Client(timeout=20, follow_redirects=False)
    backend = None
    if search == "wikipedia":  # SearXNG's engines answered nothing (CAPTCHA, quota): the no-key Wikipedia search
        from birds.harness.tools.search import WikipediaBackend

        backend = WikipediaBackend(http, lang="fr")
    elif search:
        backend = SearxngBackend(os.environ["BIRD_SEARXNG_URL"], http)
    events: list[dict] = []
    a = Agent(llm, TemplateTokenizer(), Config(workspace=Path("/tmp"), audit_file=None), search=backend, http=http,
              hooks=Hooks(on_agent=events.append, on_token=lambda t: None))  # fmt: skip
    return a, events


def wait_awake(limit: float = 900.0) -> float:
    """The endpoint scales to zero: GET /v1/models until it answers (no generation spent)."""
    import httpx

    from birds.harness.llm import normalize_base_url

    url = normalize_base_url(os.environ["BIRD_BASE_URL"]) + "/models"
    head = {"Authorization": f"Bearer {os.environ.get('BIRD_API_KEY', 'proxy-injected')}"}
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        try:
            if httpx.get(url, headers=head, timeout=20).status_code == 200:
                return time.monotonic() - t0
        except httpx.HTTPError:
            pass
        time.sleep(15)
    raise SystemExit("endpoint still asleep")


def _team(cls, a, prompt):
    from birds.harness.crew import decide, split_request

    d = decide(prompt, mode="auto")
    lang = "en" if prompt.startswith("Deep") else "fr"
    t = cls(a, d, lang=lang)
    t.message = t.own = prompt
    t.instr, t.pasted = split_request(prompt)
    t.docs, t.history, t.max_calls = [], "", 6
    return t


def plan_arm(cls, prompt, after: bool) -> dict:
    a, events = agent(search=False)
    t = _team(cls, a, prompt)
    topic = t._subject()
    if after:
        t._board_init(topic)
    t0 = time.monotonic()
    questions, queries = t._research_plan(topic)
    used = [u for u in t.usage]
    planned = (
        bool(t.trace.get("planned"))
        if after
        else any(e.get("planned") for e in events if e.get("id") == "planificateur")
    )
    linked = len(t.board["questions"]) if after else 0
    return {"prompt": prompt, "arm": "after" if after else "before", "planned": planned, "questions": questions,
            "queries": queries, "n_questions": len(questions), "n_queries": len(queries),
            "linked": linked if planned else 0, "official": sum(bool(_OFFICIAL.search(q)) for q in queries),
            "seconds": round(time.monotonic() - t0, 1),
            "tokens": sum(int(u.get("completion_tokens") or 0) for u in used)}  # fmt: skip


def full_run(prompt, search="searxng", plan=None, extractors=None) -> dict:
    """One whole run. ``plan``: the (questions, queries) a recorded --plan run gave for this prompt (temperature 0:
    the same generation), to spare the budget; ``extractors``: fewer extraction calls."""
    from birds.harness import research as rs
    from birds.harness.research import Research

    if extractors:
        rs.EXTRACTORS = extractors
    if plan is not None:
        def recorded(self, topic, _p=plan):
            self._board(phase="search", questions=[{"id": f"q{i + 1}", "text": q, "query": qq, "status": "open",
                                                    "claims": 0} for i, (q, qq) in enumerate(zip(*_p, strict=False))],
                        queries=[{"q": q, "status": "queued", "results": 0} for q in _p[1]])  # fmt: skip
            return list(_p[0]), list(_p[1])

        Research._research_plan = recorded
    a, events = agent(search=search)
    from birds.harness.crew import decide

    d = decide(prompt, mode="auto")
    t0 = time.monotonic()
    run = Research(a, d, lang="en" if prompt.startswith("Deep") else "fr").run(prompt, prompt)
    boards = [e for e in events if e.get("type") == "agent_research"]
    rep = next((w for w in run.widgets if w.get("type") == "report"), None)
    done = next((e for e in reversed(events) if e.get("type") == "agent_done"), {})
    last = boards[-1] if boards else {}
    return {
        "prompt": prompt, "seconds": round(time.monotonic() - t0, 1), "stop": run.stop_reason,
        "generations": len([u for u in run.usage if u]), "ok": done.get("ok"),
        "board_events": len(boards), "phases": list(dict.fromkeys(b["phase"] for b in boards)),
        "graph_sizes": list(dict.fromkeys(len((b.get("graph") or {}).get("nodes", [])) for b in boards)),
        "questions": last.get("questions"), "claims": last.get("claims"),
        "contradictions": last.get("contradictions"),
        "widgets": [w["type"] for w in run.widgets],
        "report": None if rep is None else {
            "sections": len(rep["sections"]), "sources": len(rep["sources"]),
            "cited": sum(1 for s in rep["sources"] if s["cited"]), "claims": len(rep["claims"]),
            "conf": {k: sum(1 for c in rep["claims"] if c["conf"] == k) for k in ("high", "medium", "low")},
            "figures": [f["value"] for f in rep["figures"]], "consulted": len(rep["consulted"]),
            "bytes": len(json.dumps(rep, ensure_ascii=False))},
        "answer_head": run.answer[:1200],
    }  # fmt: skip


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan")
    p.add_argument("--full")
    p.add_argument("--index", type=int, nargs="*", default=[0])
    p.add_argument("--before", help="the previous research.py (git show 81760d7:birds/harness/research.py)")
    p.add_argument("--search", default="searxng", choices=("searxng", "wikipedia"))
    p.add_argument("--plan-from", help="a --plan output: reuse its « after » plan instead of generating it again")
    p.add_argument("--extractors", type=int)
    args = p.parse_args(argv)
    print(f"endpoint awake after {wait_awake():.0f} s", flush=True)
    if args.plan:
        from birds.harness.research import Research as After

        spec = importlib.util.spec_from_file_location("research_before", args.before)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        rows = []
        for prompt in PROMPTS:
            for cls, after in ((old.Research, False), (After, True)):
                rows.append(plan_arm(cls, prompt, after))
                r = rows[-1]
                print(
                    f"{r['arm']:6} planned={r['planned']} q={r['n_questions']} queries={r['n_queries']} "
                    f"linked={r['linked']} official={r['official']} {r['seconds']} s  {prompt[:50]}",
                    flush=True,
                )
        Path(args.plan).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    if args.full:
        recorded = {}
        if args.plan_from:
            for r in json.loads(Path(args.plan_from).read_text()):
                if r["arm"] == "after" and r["planned"]:
                    recorded[r["prompt"]] = (r["questions"], r["queries"])
        rows = [full_run(PROMPTS[i], args.search, recorded.get(PROMPTS[i]), args.extractors) for i in args.index]
        for r in rows:
            print(json.dumps({k: v for k, v in r.items() if k != "answer_head"}, ensure_ascii=False), flush=True)
        Path(args.full).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
