"""Audit a built training mix against explicit volume and balance targets. Exit code 1 if a check fails.

  python scripts/audit_mix.py --mix out/mix [--bench out/bench/bench_stats.json]

Checks: total volume, share of French, of reasoning traces, of tool use, minimum volume per product
skill, weight of the largest source, example-length distribution, duplicates and benchmark leakage.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import statistics
import sys
from pathlib import Path

# source -> product skill. A source missing here is reported as "other" so nothing is counted silently.
SKILL = {
    "toucan_kimi": "tools",
    "toucan_oss": "tools",
    "toucan_qwen3": "tools",
    "nemotron_agentic": "tools",
    "nemotron_agentic_knowledge": "tools",
    "hermes_fc_glaive": "tools",
    "hermes_json_agentic": "structured",
    "hermes_json_single": "structured",
    "hermes_agent_traces_kimi": "agent",
    "hermes_agent_traces_glm": "agent",
    "when2call": "tools",
    "xlam_irrelevance": "tools",
    "hermes_fc": "tools",
    "toolcall_fr": "tools",
    "s1_deepresearch": "agent",
    "deepresearch_sft": "agent",
    "rag_glaive": "grounded",
    "grounded_qa": "grounded",
    "frenchqa": "grounded",
    "synth_fr": "grounded",
    "smol_rewrite": "writing",
    "smol_summarize": "writing",
    "coedit": "writing",
    "emails_fr_en": "emails",
    "smol_smoltalk": "chat",
    "aya_fr": "chat",
    "smoltalk2_fr": "chat",
    "openthoughts": "reasoning",
    "glaive_reasoning": "reasoning",
    "multilingual_thinking": "reasoning",
    "nemotron_fr": "reasoning",
    "table_gpt": "tables",
    "text_to_sql": "tables",
    "structured_extraction": "structured",
    "slides_officesmith": "slides",
    "bird_identity": "identity",
    "bird_guardrails": "guardrails",
}
BIRD_MEDIUM_TASK = {
    "emails": "emails",
    "slides": "slides",
    "finance_fr": "finance",
    "finance_en": "finance",
    "tables_en": "tables",
    "general_fr": "chat",
    "distill": "reasoning",
}
# (label, minimum, maximum) — shares are fractions of all examples
TARGETS = {
    "examples": (100_000, None),
    "label_tokens": (25_000_000, None),
    "share_fr": (0.30, 0.60),
    "share_thinking": (0.40, 0.60),
    "share_tools": (0.25, 0.45),
    "largest_source_share": (None, 0.20),
    "share_identity": (0.005, 0.02),
    "duplicate_prompts": (None, 0),
    "bench_leaks": (None, 0),
}
# v0 floors. Slides (1 000) and agent (5 000) are what open data gives today; the generated data of v1 raises them.
MIN_PER_SKILL = {
    "tools": 25_000,
    "agent": 5_000,
    "grounded": 20_000,
    "writing": 12_000,
    "emails": 5_000,
    "slides": 1_000,
    "tables": 6_000,
    "structured": 4_000,
    "reasoning": 15_000,
    "chat": 15_000,
    "finance": 2_000,
    "identity": 1_000,
    "guardrails": 500,
}


def fingerprint(rec: dict) -> str:
    users = " ".join(m["content"] for m in rec["messages"] if m["role"] == "user")
    return hashlib.sha1(" ".join(users.lower().split())[:2000].encode()).hexdigest()


def skill_of(rec: dict) -> str:
    if rec["source"] == "bird_medium":
        return BIRD_MEDIUM_TASK.get(rec.get("task", ""), "other")
    return SKILL.get(rec["source"], "other")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mix", required=True)
    ap.add_argument("--bench", default="")
    ap.add_argument("--tokenizer", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--floor-scale", type=float, default=1.0, help="scale the volume floors (budget-sized mixes)")
    ap.add_argument("--sample", type=int, default=4000, help="examples tokenised to estimate lengths")
    a = ap.parse_args()
    from transformers import AutoTokenizer

    from birds.render import IGNORE, encode, expand

    recs = [json.loads(line) for line in open(Path(a.mix) / "train.jsonl", encoding="utf-8")]
    n = len(recs)
    by_source = collections.Counter(r["source"] for r in recs)
    by_skill = collections.Counter(skill_of(r) for r in recs)
    fr_by_skill = collections.Counter(skill_of(r) for r in recs if r["lang"] == "fr")
    # identity questions are deliberately repeated with different answers and system prompts
    fps = collections.Counter(fingerprint(r) for r in recs if not r["source"].startswith("bird_"))
    bench_hashes = set(json.loads(Path(a.bench).read_text())["prompt_hashes"]) if a.bench else set()

    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    step = max(1, n // a.sample)
    lens, labs = [], []
    for r in recs[::step]:
        for ex in expand(r):
            e = encode(tok, ex, 10**9)
            if e:
                lens.append(len(e["input_ids"]))
                labs.append(sum(x != IGNORE for x in e["labels"]))
    examples_per_record = len(lens) / max(1, len(recs[::step]))
    m = {
        "examples": round(n * examples_per_record),
        "label_tokens": round(n * examples_per_record * statistics.mean(labs)),
        "total_tokens": round(n * examples_per_record * statistics.mean(lens)),
        "share_fr": sum(r["lang"] == "fr" for r in recs) / n,
        "share_thinking": sum(bool(r["thinking"]) for r in recs) / n,
        "share_tools": sum(bool(r.get("tools")) for r in recs) / n,
        "largest_source_share": max(by_source.values()) / n,
        "share_identity": by_skill["identity"] / n,
        "duplicate_prompts": sum(c - 1 for c in fps.values() if c > 1),
        "bench_leaks": sum(1 for f in fps if f in bench_hashes),
    }
    q = statistics.quantiles(lens, n=100)
    ok = True
    print(
        f"records {n}   examples/record {examples_per_record:.2f}   tokens/example p50 {q[49]:.0f} p90 {q[89]:.0f} p99 {q[98]:.0f}"
    )
    print(f"{'check':24s} {'value':>14s}   target")
    for k, (lo, hi) in TARGETS.items():
        v = m[k]
        if k in ("examples", "label_tokens"):
            lo = lo * a.floor_scale
        if k == "share_identity" and a.floor_scale < 1:
            hi = 0.04  # identity keeps its absolute size in a smaller mix
        good = (lo is None or v >= lo) and (hi is None or v <= hi)
        ok &= good
        val = f"{v:.3f}" if isinstance(v, float) else f"{v:,}"
        print(
            f"{k:24s} {val:>14s}   {'≥ ' + str(lo) if lo is not None else ''} {'≤ ' + str(hi) if hi is not None else ''}  {'ok' if good else 'FAIL'}"
        )
    print(f"\n{'skill':12s} {'records':>8s} {'share':>6s} {'fr':>6s}   minimum")
    for k in sorted(set(MIN_PER_SKILL) | set(by_skill)):
        need = int(MIN_PER_SKILL.get(k, 0) * (1.0 if k in ("identity", "guardrails") else a.floor_scale))
        good = by_skill[k] >= need and k != "other"
        ok &= good or (k == "other" and by_skill[k] == 0)
        print(
            f"{k:12s} {by_skill[k]:8d} {by_skill[k] / n:6.1%} {fr_by_skill[k] / max(1, by_skill[k]):6.0%}   ≥ {need}  {'ok' if good else 'FAIL'}"
        )
    print("\nsources:", ", ".join(f"{s} {c}" for s, c in by_source.most_common()))
    (Path(a.mix) / "audit.json").write_text(
        json.dumps({"metrics": m, "by_skill": by_skill, "by_source": by_source, "pass": ok}, indent=1)
    )
    print("\nAUDIT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
