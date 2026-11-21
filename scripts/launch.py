"""Launch a Bird job on Hugging Face Jobs.

  python scripts/launch.py bench --flavor l40sx1 --timeout 1h -- --model Qwen/Qwen3.5-4B --tag base --out /out/base
  python scripts/launch.py train --flavor l40sx1 --timeout 8h -- --out /out/bird-v0 --tag bird-v0

Everything after `--` goes to jobs/bird_job.py. Volumes (no token is needed inside the job):
  /dataset : hf://datasets/<user>/birds-sft     (train.jsonl, eval.jsonl)   read-only
  /bench   : hf://datasets/<user>/birds-bench   (bench.jsonl)               read-only
  /out     : hf://buckets/<user>/birds-runs     (adapters, logs, reports)   read-write
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["train", "bench"])
ap.add_argument("--flavor", required=True)
ap.add_argument("--timeout", required=True)
ap.add_argument("--user", default="adubrou")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("rest", nargs=argparse.REMAINDER)
a = ap.parse_args()
rest = a.rest[1:] if a.rest[:1] == ["--"] else a.rest

subprocess.run([sys.executable, str(ROOT / "scripts" / "build_job.py")], check=True)
cmd = [
    "hf",
    "jobs",
    "uv",
    "run",
    "--flavor",
    a.flavor,
    "--timeout",
    a.timeout,
    "--detach",
    "--name",
    f"bird-{a.mode}",
    "-e",
    "PYTHONUNBUFFERED=1",
    "-v",
    f"hf://datasets/{a.user}/birds-bench:/bench:ro",
    "-v",
    f"hf://buckets/{a.user}/birds-runs:/out",
]
if a.mode == "train":
    cmd += ["-v", f"hf://datasets/{a.user}/birds-sft:/dataset:ro"]
if a.dry_run:
    cmd.append("--dry-run")
cmd += [str(ROOT / "dist" / "bird_job.py"), a.mode, "--bench", "/bench/bench.jsonl", *rest]
print(" ".join(cmd))
sys.exit(subprocess.run(cmd).returncode)
