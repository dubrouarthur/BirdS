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

ap = argparse.ArgumentParser()
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
train: list[str] = []
stats = {}
for src, lines in sorted(by_source.items()):
    cap = CAPS_V0.get(src)
    kept = rng.sample(lines, cap) if cap and len(lines) > cap else lines
    stats[src] = {"pool": len(lines), "kept": len(kept)}
    train += kept
ident = [line for path in a.identity for line in open(path, encoding="utf-8") if line.strip()]
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
