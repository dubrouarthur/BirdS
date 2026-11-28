"""Before / after of the data planner on fixed cases (scripts/router_data.py: DATA_PLAN, LIVE_8).

  # the fixed rules only (no network): the « before »
  .venv/bin/python scripts/data_eval.py --rules
  # Bird chooses the analysis (one structured call per case), scored against the rules; --answers also runs the
  # answer of each case (the engine's result + the model's comment) and checks every number of it
  BIRD_BASE_URL=https://…/v1 .venv/bin/python scripts/data_eval.py --cases live8 --answers --out out/data_eval.jsonl

The API key is read from BIRD_API_KEY (never on the command line). Each case costs one planner generation, plus one
or two with --answers (max_steps=2). The planner answer is reused for the answer run (no second planner call).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import router_data as D  # noqa: E402

from birds.harness.analysis import hooks  # noqa: E402
from birds.harness.analysis import planner as P  # noqa: E402
from birds.harness.analysis.profile import frame_of  # noqa: E402
from birds.harness.analysis.table import read_table  # noqa: E402
from birds.harness.template import TemplateTokenizer  # noqa: E402

DATA = ROOT / "tests" / "fixtures" / "data"


class Replay:
    """The planner's recorded answer, served again to ``hooks.prepare`` (no second generation)."""

    def __init__(self, out: dict):
        self.out = out

    def generate(self, *a, **k) -> dict:
        return self.out


class Recorder:
    def __init__(self, llm):
        self.llm, self.last = llm, None

    def generate(self, *a, **k) -> dict:
        self.last = self.llm.generate(*a, **k)
        return self.last


def history_of(prev: dict | None) -> list[dict] | None:
    if not prev:
        return None
    line = P.memo_line("ventes.csv", {"query": prev["analysis"], "chart": prev.get("chart")})
    return [{"role": "user", "content": "CA par région"}, {"role": "assistant", "content": "Voilà.", "memo": line}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BIRD_BASE_URL", ""))
    ap.add_argument("--model", default=os.environ.get("BIRD_MODEL", "bird-s-4b"))
    ap.add_argument("--rules", action="store_true", help="the fixed rules only, no network")
    ap.add_argument("--cases", choices=["all", "live8"], default="all")
    ap.add_argument("--structured", default="structured_outputs", help="none, or one of router.STRUCTURED_KINDS")
    ap.add_argument("--mode", choices=["model", "hybrid"], default="hybrid")
    ap.add_argument("--answers", action="store_true", help="also run the answer of each case and check its numbers")
    ap.add_argument("--budget", type=float, default=60.0, help="seconds per planner call (a waking endpoint)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    f = frame_of(read_table(DATA / "ventes.csv"))
    tok = TemplateTokenizer()
    cases = [c for c in D.DATA_PLAN if a.cases == "all" or c[0] in D.LIVE_8]
    llm = None
    if not a.rules:
        if not a.base_url:
            ap.error("--base-url (or BIRD_BASE_URL) is required, or --rules")
        from birds.harness.llm import CompletionsClient

        llm = CompletionsClient(a.base_url, a.model, os.environ.get("BIRD_API_KEY") or None, timeout=180.0)
    structured = "" if a.structured == "none" else a.structured
    rows = []
    for cid, text, prev, gold, charts in cases:
        hist = history_of(prev)
        rules = P.rule_plan(f, text, P.previous_spec(hist))
        row = {"id": cid, "text": text, "rules": D.data_judge(rules, gold, charts),
               "rules_plan": rules and {"query": rules["query"], "chart": rules.get("chart")}}  # fmt: skip
        if llm is not None:
            rec = Recorder(llm)
            t0 = time.monotonic()
            got = P.decide(rec, tok, f, text, history=hist, mode=a.mode, structured=structured, budget=a.budget)
            row.update({"source": got.source, "seconds": round(time.monotonic() - t0, 2), "meta": got.meta,
                        "model": D.data_judge(got.plan, gold, charts),
                        "model_plan": got.plan and {"query": got.plan["query"], "chart": got.plan.get("chart")}})  # fmt: skip
            if a.answers and rec.last is not None:
                row["answer"] = answer_of(llm, tok, text, hist, Replay(rec.last), a.mode, structured)
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("id", "rules", "model", "source", "seconds")}, ensure_ascii=False),
              file=sys.stderr, flush=True)  # fmt: skip
    summary = {"cases": len(rows)}
    for arm in ("rules", "model"):
        got = [r[arm] for r in rows if arm in r]
        if got:
            summary[arm] = {"analysis_ok": sum(g["ok"] for g in got), "chart_ok": sum(g["chart_ok"] for g in got),
                            "n": len(got)}  # fmt: skip
    if any("answer" in r for r in rows):
        ans = [r["answer"] for r in rows if "answer" in r]
        summary["answers"] = {"n": len(ans), "numbers_ok": sum(x["check"] == {"ok": True} for x in ans),
                              "replaced": sum(bool(x["check"].get("replaced")) for x in ans),
                              "seconds_p50": sorted(x["seconds"] for x in ans)[len(ans) // 2]}  # fmt: skip
    print(json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        Path(a.out).with_suffix(".summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


def answer_of(llm, tok, text: str, hist, replay, mode: str, structured: str) -> dict:
    """The answer turn as the server runs it: the data hook (planner answer replayed), then the model comments."""
    from birds.harness.agent import Agent
    from birds.harness.config import Config

    os.environ["BIRD_ROUTER"] = "regex"  # no module-router call here: one answer generation per case
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "ventes.csv").write_bytes((DATA / "ventes.csv").read_bytes())
        prep = hooks.prepare(ws, ["ventes.csv"], text, "fr", llm=replay, tok=tok, history=hist, mode=mode,
                             structured=structured)  # fmt: skip
        agent = Agent(llm, tok, Config(workspace=ws, max_steps=2), confirm=lambda tool, args: False)
        user = text + (prep.note if prep else "")
        t0 = time.monotonic()
        run = agent.run(user, lang="fr", request_text=text, attached=True, history=hist)
        seconds = round(time.monotonic() - t0, 2)
        raw = str(run.answer or "")
        hooks.finish(run, prep, text)
        return {"seconds": seconds, "raw": raw[:800], "final": str(run.answer or "")[:800],
                "check": (run.report or {}).get("data_check", {}), "steps": [s.tool for s in run.steps],
                "result": prep.result["title"] if prep and prep.result else None}  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
