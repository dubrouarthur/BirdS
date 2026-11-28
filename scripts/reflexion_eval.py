"""Mode Réflexion on the real endpoint: the level Bird chooses, and accuracy / latency before and after.

  .venv/bin/python scripts/reflexion_eval.py --base-url URL --model NAME --levels           # the Auto decision
  .venv/bin/python scripts/reflexion_eval.py --base-url URL --model NAME --calc --arm after # reflexion="auto"
  .venv/bin/python scripts/reflexion_eval.py --base-url URL --model NAME --calc --arm before --root <old checkout>

``--arm before`` runs the harness of ``--root`` (a checkout of the branch before Mode Réflexion) the way the app
called it: ``thinking=True`` (the app's default), no level. ``--arm after`` passes ``reflexion="auto"``: the model
chooses its bird, the budget, the self-check and the review follow. Same prompts (``router_data.REFLEXION_CALC``),
same endpoint, temperature 0, one pass each. Scoring: every expected figure is in the answer
(``router_data.calc_ok``). Prints one JSON line per case and a summary; ``--out`` writes them. Nothing of the
answers is logged beyond the first 400 characters kept in the output file for reading.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--levels", action="store_true", help="the Auto decision on router_data.REFLEXION_LEVELS")
    ap.add_argument("--calc", action="store_true", help="the fixed set router_data.REFLEXION_CALC")
    ap.add_argument("--arm", choices=("before", "after"), default="after")
    ap.add_argument("--root", default=str(HERE.parent), help="checkout whose harness runs the cases")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--pick", default="", help="--levels: comma-separated indexes of REFLEXION_LEVELS (live budget)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    sys.path.insert(0, str(root))  # the harness under test, imported first: router_data then reuses it
    from birds.harness.agent import Agent
    from birds.harness.config import Config
    from birds.harness.llm import CompletionsClient
    from birds.harness.template import TemplateTokenizer

    sys.path.insert(1, str(HERE))  # the data and scoring of this checkout
    import router_data as D

    import birds

    assert Path(birds.__file__).resolve().is_relative_to(root), birds.__file__

    llm = CompletionsClient(a.base_url, a.model, api_key=a.api_key or "proxy-injected", timeout=240.0)
    tok = TemplateTokenizer()
    rows = []
    if a.levels:
        from birds.harness import reflexion as R

        picked = {int(i) for i in a.pick.split(",") if i.strip()}
        for i, (text, ok) in enumerate(D.REFLEXION_LEVELS):
            if picked and i not in picked:
                continue
            from birds.harness.agent import detect_lang

            c = R.decide(llm, tok, text, lang=detect_lang(text), budget=8.0)
            rows.append({"text": text, "level": c.level, "source": c.source, "ok": c.level in ok,
                         "seconds": round(c.seconds, 3)})  # fmt: skip
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        n = len(rows)
        summary = {"n": n, "accuracy": round(sum(r["ok"] for r in rows) / n, 3),
                   "model_answers": sum(r["source"] == "model" for r in rows),
                   "p50_s": round(statistics.median(r["seconds"] for r in rows), 3)}  # fmt: skip
    if a.calc:
        only = {x for x in a.only.split(",") if x}
        work = root / "out" / "reflexion_eval"
        work.mkdir(parents=True, exist_ok=True)
        for cid, text, wants in D.REFLEXION_CALC:
            if only and cid not in only:
                continue
            agent = Agent(llm, tok, Config(workspace=work, audit_file=None), confirm=lambda t, x: False)
            t0 = time.monotonic()
            kw = {"thinking": True} if a.arm == "before" else {"reflexion": "auto"}
            run = agent.run(text, lang="fr", **kw)
            secs = time.monotonic() - t0
            good, hit = D.calc_ok(run.answer, wants)
            rx = getattr(run, "reflexion", None) or {}
            gens = [u for u in run.usage if u.get("kind") not in ("router", "reflexion")]
            rows.append({
                "id": cid, "arm": a.arm, "ok": good, "figures": f"{hit}/{len(wants)}", "seconds": round(secs, 2),
                "generations": len(gens), "completion_tokens": sum(int(u.get("completion_tokens") or 0) for u in gens),
                "stop": run.stop_reason, "level": rx.get("level"), "source": rx.get("source"),
                "checks": rx.get("checks"), "issues": rx.get("issues"), "corrected": rx.get("corrected"), "cut": rx.get("cut"),
                "think_chars": rx.get("think_chars", len(run.reasoning or "")), "answer": (run.answer or "")[:400],
            })  # fmt: skip
            print(json.dumps({k: v for k, v in rows[-1].items() if k != "answer"}, ensure_ascii=False), flush=True)
        n = len([r for r in rows if "id" in r])
        calc = [r for r in rows if "id" in r]
        summary = {"arm": a.arm, "n": n, "correct": sum(r["ok"] for r in calc),
                   "mean_s": round(statistics.mean(r["seconds"] for r in calc), 2),
                   "p50_s": round(statistics.median(r["seconds"] for r in calc), 2),
                   "mean_generations": round(statistics.mean(r["generations"] for r in calc), 2),
                   "mean_completion_tokens": round(statistics.mean(r["completion_tokens"] for r in calc), 1)}  # fmt: skip
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
