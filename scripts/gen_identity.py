"""Write the Bird identity records (see birds/sources/identity.py and docs/PERSONA.md).

python scripts/gen_identity.py --out out/identity.jsonl [--n-fr 900 --n-en 500 --seed 0]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from birds.schema import errors
from birds.sources.identity import generate

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--n-fr", type=int, default=900)
ap.add_argument("--n-en", type=int, default=500)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

recs = generate(a.n_fr, a.n_en, a.seed)
bad = [(r["id"], errors(r)) for r in recs if errors(r)]
if bad:
    raise SystemExit(f"invalid records: {bad[:3]}")
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    for r in recs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
answers = {r["messages"][-1]["content"] for r in recs}
print(
    json.dumps(
        {
            "records": len(recs),
            "fr": sum(r["lang"] == "fr" for r in recs),
            "thinking": sum(r["thinking"] for r in recs),
            "unique_answers": round(len(answers) / max(1, len(recs)), 3),
            "out": str(out),
        }
    )
)
