"""Write the guardrail training records and the held-out injection benchmark suite.

  python scripts/gen_guardrails.py --out out/guardrails.jsonl --bench-out out/bench/injection.jsonl
"""

import argparse
import json

from birds.sources.guardrails import bench_items, generate

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--bench-out", default="")
ap.add_argument("--n", type=int, default=800)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
recs = generate(a.n, a.seed)
with open(a.out, "w", encoding="utf-8") as f:
    for r in recs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
if a.bench_out:
    with open(a.bench_out, "w", encoding="utf-8") as f:
        for r in bench_items():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(json.dumps({"records": len(recs), "fr": sum(r["lang"] == "fr" for r in recs), "bench": len(bench_items())}))
