"""Select the training mix for one run from the full assembled pool (out/mix), within a token budget.

  python scripts/select_mix.py --pool out/mix --identity out/identity.jsonl --out out/mix_v0

The pool holds everything the converters produce (~205k conversations, ~320M tokens: too much for a
first run). This keeps every French and product-specific conversation and caps the large English
generic sources, which also brings French to about a third of the mix.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

# caps for the large English sources; any source not listed is kept in full
CAPS_V0 = {
    # sources with reasoning traces are favoured: they keep the base model's thinking ability alive
    "toucan_kimi": 4000, "toucan_oss": 10000, "toucan_qwen3": 4000, "nemotron_agentic": 14000,
    "nemotron_agentic_knowledge": 5000, "when2call": 4000, "smol_rewrite": 4500, "smol_summarize": 4500,
    "smol_smoltalk": 4000, "rag_glaive": 5000, "glaive_reasoning": 6000, "table_gpt": 4000, "text_to_sql": 2500,
    "coedit": 3000,
}

# starting caps of the budget profile: what matters most for Bird first (its own business data, French,
# when-to-call decisions, reasoning-bearing tool use); --token-budget then scales them down evenly
CAPS_BUDGET = {
    "bird_medium": 8000, "emails_fr_en": 3000,
    "when2call": 3500, "frenchqa": 3000, "smoltalk2_fr": 3000, "nemotron_fr": 4500, "synth_fr": 3500,
    "nemotron_agentic": 8000, "toucan_oss": 5500, "toucan_kimi": 1500, "toucan_qwen3": 1500,
    "nemotron_agentic_knowledge": 3000, "hermes_fc_glaive": 1500, "hermes_agent_traces_kimi": 1400,
    "hermes_agent_traces_glm": 700, "s1_deepresearch": 1400, "rag_glaive": 2500, "grounded_qa": 2074,
    "smol_rewrite": 2500, "smol_summarize": 2500, "coedit": 1500, "smol_smoltalk": 1500, "glaive_reasoning": 3500,
    "openthoughts": 800, "table_gpt": 2500, "text_to_sql": 1500, "structured_extraction": 1500,
    "xlam_irrelevance": 500, "hermes_json_agentic": 600, "hermes_json_single": 600,
}
PROTECTED = {"bird_medium", "slides_officesmith", "emails_fr_en", "toolcall_fr", "aya_fr"}  # never scaled down
BYTES_PER_TOKEN = 3.29  # measured on mix v0 (687 MB of JSON lines for 209 M training tokens)

ap = argparse.ArgumentParser()
ap.add_argument("--profile", choices=["v0", "budget"], default="v0")
ap.add_argument("--token-budget", type=float, default=0, help="millions of training tokens to fit (budget profile)")
ap.add_argument("--pool", required=True)
ap.add_argument("--identity", required=True, nargs="+", help="ready-made record files (identity, guardrails)")
ap.add_argument("--out", required=True)
ap.add_argument("--eval-size", type=int, default=1000)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
rng = random.Random(a.seed)
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)

by_source: dict[str, list[str]] = collections.defaultdict(list)
with open(Path(a.pool) / "train.jsonl", encoding="utf-8") as f:
    for line in f:
        head = line[:400]
        src = head.split('"source": "', 1)[1].split('"', 1)[0]
        by_source[src].append(line)
caps = dict(CAPS_V0 if a.profile == "v0" else CAPS_BUDGET)
ident = [line for path in a.identity for line in open(path, encoding="utf-8") if line.strip()]


def pick(scale: float) -> tuple[list[str], dict]:
    r, rows, st = random.Random(a.seed), [], {}
    for src, lines in sorted(by_source.items()):
        cap = caps.get(src)
        if cap and src not in PROTECTED:
            cap = max(1, int(cap * scale))
        kept = r.sample(lines, cap) if cap and len(lines) > cap else lines
        st[src] = {"pool": len(lines), "kept": len(kept)}
        rows += kept
    return rows, st


def tokens(rows: list[str]) -> float:
    return sum(len(x.encode()) for x in rows) / BYTES_PER_TOKEN / 1e6


scale = 1.0
train, stats = pick(scale)
if a.token_budget:
    fixed = tokens(ident)
    while tokens(train) + fixed > a.token_budget and scale > 0.05:
        scale *= 0.95
        train, stats = pick(scale)
print(f"scale {scale:.2f}  estimated training tokens {tokens(train) + tokens(ident):.1f} M")
rng.shuffle(ident)
n_id_eval = 60
train += ident[n_id_eval:]
stats["bird_identity+guardrails"] = {"pool": len(ident), "kept": len(ident) - n_id_eval}
rng.shuffle(train)
evals = [line for line in open(Path(a.pool) / "eval.jsonl", encoding="utf-8") if line.strip()]
evals = rng.sample(evals, min(a.eval_size, len(evals))) + ident[:n_id_eval]
(out / "train.jsonl").write_text("".join(train), encoding="utf-8")
(out / "eval.jsonl").write_text("".join(evals), encoding="utf-8")
(out / "stats.json").write_text(json.dumps({"train": len(train), "eval": len(evals), "sources": stats}, indent=1))
print(json.dumps({"train": len(train), "eval": len(evals)}))
