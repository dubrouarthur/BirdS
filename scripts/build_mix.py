"""Assemble the training mix from the source registry.

  python scripts/build_mix.py --out out/mix                 # full v0 mix
  python scripts/build_mix.py --out out/probe --only toucan --cap 200   # probe one source

Writes train.jsonl, eval.jsonl, stats.json and rejects.jsonl (a sample of rejected records with reasons).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import traceback
from pathlib import Path

from birds.render import encode, expand
from birds.schema import errors
from birds.sources import all_sources

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--only", nargs="*", default=[])
ap.add_argument("--cap", type=int, default=0, help="override every source cap (probing)")
ap.add_argument("--max-len", type=int, default=4096, help="max tokens per example")
ap.add_argument("--tokenizer", default="Qwen/Qwen3.5-4B")
ap.add_argument("--eval-fraction", type=float, default=0.01)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

from datasets import load_dataset  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(a.tokenizer)
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
rng = random.Random(a.seed)
seen: set[str] = set()
kept: list[dict] = []
stats: dict = {"sources": {}}
rejects = open(out / "rejects.jsonl", "w", encoding="utf-8")


def fingerprint(rec: dict) -> str:
    users = " ".join(m["content"] for m in rec["messages"] if m["role"] == "user")
    return hashlib.sha1(" ".join(users.lower().split())[:2000].encode()).hexdigest()


for src in all_sources():
    if a.only and src.name not in a.only:
        continue
    cap = a.cap or src.cap
    scan = src.scan or 6 * cap
    c = collections.Counter()
    rows = []
    try:
        ds = load_dataset(src.repo, src.config, split=src.split, data_files=src.data_files, streaming=True, **src.kwargs)
        ds = ds.shuffle(seed=a.seed, buffer_size=min(10_000, scan))
        for i, row in enumerate(ds):
            if i >= scan or len(rows) >= cap:
                break
            c["rows"] += 1
            try:
                recs = src.convert(row)
            except Exception as e:  # converters must not raise; count it and keep going
                c["convert_error"] += 1
                if c["convert_error"] <= 3:
                    rejects.write(json.dumps({"source": src.name, "why": f"exception {e!r}"}) + "\n")
                continue
            if not recs:
                c["skipped"] += 1
            for j, r in enumerate(recs):
                r = {"id": f"{src.name}-{i:07d}-{j}", "source": src.name, "license": src.license,
                     "task": r.get("task") or src.task, **{k: v for k, v in r.items() if k != "task"}}
                errs = errors(r)
                if not errs:
                    try:
                        if not all(encode(tok, e, a.max_len) for e in expand(r)):
                            errs = ["too long or nothing to learn"]
                    except Exception as e:
                        errs = [f"render: {e}"]
                if not errs and fingerprint(r) in seen:
                    errs = ["duplicate"]
                if errs:
                    c["rejected"] += 1
                    c["why:" + errs[0].split(":")[0][:40]] += 1
                    if c["rejected"] <= 5:
                        rejects.write(json.dumps({"source": src.name, "why": errs, "rec": r}, ensure_ascii=False)[:3000] + "\n")
                    continue
                seen.add(fingerprint(r))
                rows.append(r)
                if len(rows) >= cap:
                    break
    except Exception:
        c["load_error"] += 1
        stats["sources"][src.name] = {"error": traceback.format_exc()[-800:]}
        print(f"!! {src.name}: load failed", flush=True)
        continue
    c["kept"] = len(rows)
    c["thinking"] = sum(r["thinking"] for r in rows)
    c["fr"] = sum(r["lang"] == "fr" for r in rows)
    c["with_tools"] = sum(bool(r.get("tools")) for r in rows)
    stats["sources"][src.name] = {"repo": src.repo, "license": src.license, "cap": cap, **dict(c)}
    print(f"{src.name:28s} kept {len(rows):6d}/{cap}  rows {c['rows']}  rejected {c['rejected']}  errors {c['convert_error']}", flush=True)
    kept += rows

rng.shuffle(kept)
n_eval = min(2000, int(len(kept) * a.eval_fraction))
splits = {"eval.jsonl": kept[:n_eval], "train.jsonl": kept[n_eval:]}
for name, rows in splits.items():
    with open(out / name, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
stats["total"] = {"train": len(splits["train.jsonl"]), "eval": n_eval,
                  "thinking": sum(r["thinking"] for r in kept), "fr": sum(r["lang"] == "fr" for r in kept),
                  "with_tools": sum(bool(r.get("tools")) for r in kept)}
(out / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
print(json.dumps(stats["total"]))
