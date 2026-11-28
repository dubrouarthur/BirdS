"""Live evaluation of the harness between actions: 20 multi-step tasks on the real model, scored by a rubric.

The tasks are the scenario suite's (tests/scenarios/cases.py): the same request, attachments, history and tool
data (search results and pages are fixed, so only the model varies), and the same rubric (tests/scenarios/runner.py
`score`): deliverables made, figures kept, language, no repeated call, a real answer, honesty about what is missing.
Only the scripted model is replaced by the live endpoint.

    .venv/bin/python scripts/harness_eval.py --base-url https://…/v1 --model bird            # plan on
    .venv/bin/python scripts/harness_eval.py --base-url … --arms on,off --json out/harness_eval.json
    .venv/bin/python scripts/harness_eval.py --base-url … --only 'ocr|multi'

Arms: "on" is the harness as shipped; "off" turns the task plan and its final check off (Config.task_plan=False),
the call and argument repairs stay. Each task runs ``--repeats`` times per arm (the model samples). The endpoint
key is read from BIRD_API_KEY. Nothing is sent anywhere but the endpoint: no search engine, no web page.

Rubric (one point per check, a task passes when all its checks pass):
  answered    the run ends on an answer, not a fallback          tool:X      tool X succeeded
  figure:N    the number N reaches the answer, the draft or file  table       a table in the answer or a sheet
  lang        the answer is in the user's language                no_repeat   no successful call made twice
  says / not  the answer matches / avoids a pattern               honest      the plan reports what is missing
  gens        generations within the task's budget (plain asks)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.scenarios.cases import SCENARIOS  # noqa: E402
from tests.scenarios.runner import run_one, score  # noqa: E402

TASKS = [  # 20 tasks: every family, the hardest first; two plain controls for latency; 8 false-trigger controls
    "ocr_table_totals_mail", "ocr_totals_dropped", "ocr_sheet_then_mail", "ocr_big_rounded",
    "search_compare_chart", "search_premature", "search_read_summary_mail", "multi_search_sheet_mail",
    "file_summary_deck", "file_premature", "file_doc_and_sheet", "file_wrong_path",
    "multi_slides_mail", "multi_doc_slides_mail_partial", "multi_minutes_table_mail", "multi_en_deck_mail",
    "followup_totals_mail", "followup_reread_image", "ordinary_mail", "ordinary_question",
    # false-trigger controls: correct first answers that the checks must leave alone (one generation each, or two
    # with a tool); select them with --only '^ordinary_'
    "ordinary_translate_en", "ordinary_write_in_french", "ordinary_je_cherche", "ordinary_excel_formula",
    "ordinary_mail_with_link", "ordinary_signature_link", "ordinary_code_with_call_line", "ordinary_json_example",
]  # fmt: skip


class Counted:
    """Wraps the endpoint client: counts generations (the rubric's `gens`) like the scripted model's views."""

    def __init__(self, llm):
        self.llm, self.views = llm, []

    def generate(self, prompt, max_tokens, stop, **kw):
        self.views.append(None)
        return self.llm.generate(prompt, max_tokens, stop, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default=os.environ.get("BIRD_BASE_URL"), help="OpenAI-compatible URL ending /v1")
    ap.add_argument("--model", default=os.environ.get("BIRD_MODEL", "bird"))
    ap.add_argument("--tokenizer", default="Qwen/Qwen3.5-4B", help="tokenizer that renders the prompt")
    ap.add_argument("--arms", default="on", help="on, off or on,off (task plan and final check)")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--only", help="regex on task ids")
    ap.add_argument("--json", help="write every run (answer, steps, checks) to this file")
    a = ap.parse_args(argv)
    if not a.base_url:
        ap.error("--base-url (or BIRD_BASE_URL) is required: this evaluation runs the live model")
    import re

    from transformers import AutoTokenizer  # tokenizer only: no weights

    from birds.harness import CompletionsClient, Config

    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    llm = CompletionsClient(a.base_url, a.model, os.environ.get("BIRD_API_KEY"))
    by_id = {s.id: s for s in SCENARIOS}
    tasks = [by_id[t] for t in TASKS if not a.only or re.search(a.only, t)]
    rows = []
    with tempfile.TemporaryDirectory(prefix="bird-eval-") as tmp:
        for arm in a.arms.split(","):
            for sc in tasks:
                for k in range(a.repeats):
                    model = Counted(llm)
                    t0 = time.monotonic()
                    try:
                        known = {f.name for f in dataclasses.fields(Config)}  # an older harness has no task_plan
                        conf = {k: v for k, v in {"task_plan": arm == "on"}.items() if k in known}
                        run, _, _ = run_one(sc, Path(tmp) / f"{arm}-{k}", model=model, tok=tok, config=conf)
                        checks, err = score(sc, run, model), ""
                    except Exception as e:  # noqa: BLE001 - an endpoint error is a failed task, reported
                        run, checks, err = None, {"crash": False}, f"{type(e).__name__}: {e}"
                    row = {"arm": arm, "id": sc.id, "family": sc.family, "try": k, "pass": all(checks.values()),
                           "checks": checks, "gens": len(model.views), "seconds": round(time.monotonic() - t0, 1),
                           "error": err}  # fmt: skip
                    if run is not None:
                        row.update(answer=run.answer, stop=run.stop_reason, plan=getattr(run, "plan", None),
                                   steps=[{"tool": s.tool, "error": s.error, "repairs": s.repairs} for s in run.steps])  # fmt: skip
                    rows.append(row)
                    bad = [c for c, v in checks.items() if not v]
                    print(f"[{arm}] {sc.id:32s} {'PASS' if row['pass'] else 'fail'} gens={row['gens']} "
                          f"{row['seconds']:>5}s {' '.join(bad)} {err}", flush=True)  # fmt: skip
    print("\n| arm | tasks passed | checks passed | avg generations | avg seconds |\n|---|---|---|---|---|")
    for arm in a.arms.split(","):
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        c = sum(len(r["checks"]) for r in rs)
        k = sum(sum(r["checks"].values()) for r in rs)
        print(f"| {arm} | {sum(r['pass'] for r in rs)}/{len(rs)} | {k}/{c} | "
              f"{sum(r['gens'] for r in rs) / len(rs):.2f} | {sum(r['seconds'] for r in rs) / len(rs):.1f} |")  # fmt: skip
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
