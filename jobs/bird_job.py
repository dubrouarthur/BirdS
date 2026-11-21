# /// script
# requires-python = ">=3.11"
# dependencies = ["torch", "transformers>=5.2", "peft>=0.17", "accelerate", "flash-linear-attention", "jsonschema"]
# ///
"""Bird job: LoRA fine-tuning and/or benchmark of a Qwen3.5 model. Runs on Hugging Face Jobs or locally.

  bench : python jobs/bird_job.py bench --model Qwen/Qwen3.5-4B --bench /bench/bench.jsonl --out /out/base
  train : python jobs/bird_job.py train --model Qwen/Qwen3.5-4B --data /dataset --out /out/bird-v0 \
              --bench /bench/bench.jsonl

On Jobs, scripts/build_job.py embeds the `birds` package in this file (PAYLOAD) so the job needs no
repository access. Volumes: dataset repos mounted read-only, a bucket mounted at /out for results.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

PAYLOAD = ""  # filled by scripts/build_job.py (zip of the birds package, base64)
if PAYLOAD:
    zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))).extractall("/tmp/birds_pkg")
    sys.path.insert(0, "/tmp/birds_pkg")
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LORA_TARGETS = [  # every weight matrix of the language model; the tiny in_proj_a/b gates are left alone
    "in_proj_qkv",
    "in_proj_z",
    "out_proj",
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]
T0 = time.time()


def log(*x):
    print(f"[{round(time.time() - T0)}s]", *x, flush=True)


class PowerMeter:
    """Integrates GPU power (nvidia-smi) into watt-hours. Reports None when no GPU is visible."""

    def __init__(self, period: float = 2.0):
        self.period, self.joules, self.samples, self._stop = period, 0.0, 0, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _read(self) -> float | None:
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            return sum(float(x) for x in out.split())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _run(self):
        last = time.time()
        while not self._stop.wait(self.period):
            w, now = self._read(), time.time()
            if w is not None:
                self.joules += w * (now - last)
                self.samples += 1
            last = now

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()

    @property
    def wh(self) -> float | None:
        return round(self.joules / 3600, 3) if self.samples else None


def save_tree(src: Path, dst: Path):
    """Copy a directory to the mounted bucket, file by file (FUSE-friendly)."""
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        d = dst / f.relative_to(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, d)
        try:
            fd = os.open(d, os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path("/tmp") / f"{path.name}.{os.getpid()}"
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copyfile(tmp, path)


def read_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_model(name: str, adapter: str | None, train: bool):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(name)
    if tok.pad_token is None:
        tok.pad_token = "<|endoftext|>"
    model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.bfloat16 if dev == "cuda" else torch.float32)
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter, is_trainable=train)
        if not train:
            model = model.merge_and_unload()
    model.to(dev)
    log("model", name, type(model).__name__, "device", dev, "adapter", adapter)
    return tok, model, dev


# ------------------------------------------------------------------ benchmark
def run_bench(tok, model, dev, items: list[dict], batch_tokens: int, tag: str, out: Path) -> dict:
    """Generate one answer per benchmark item (greedy), score it, write <out>/bench_<tag>.json."""
    import torch

    from birds.parse import parse_output
    from birds.render import prompt
    from birds.scoring import aggregate, score

    stop = [tok.convert_tokens_to_ids("<|im_end|>"), tok.convert_tokens_to_ids("<|endoftext|>")]
    tok.padding_side = "left"
    enc = []
    for it in items:
        ids = tok(prompt(tok, it["messages"], it.get("tools"), bool(it.get("thinking"))), add_special_tokens=False)[
            "input_ids"
        ]
        enc.append((it, ids))
    enc.sort(key=lambda x: (x[0]["max_new_tokens"], len(x[1])))
    batches, cur = [], []
    for it, ids in enc:
        # a batch costs (prompt + generation) tokens per row; rows share the same max_new_tokens
        if cur and (
            cur[0][0]["max_new_tokens"] != it["max_new_tokens"]
            or (len(cur) + 1) * (len(ids) + it["max_new_tokens"]) > batch_tokens
        ):
            batches.append(cur)
            cur = []
        cur.append((it, ids))
    if cur:
        batches.append(cur)
    log(f"bench {tag}: {len(items)} items in {len(batches)} batches")
    model.eval()
    results, gen_tokens, t_start = [], 0, time.time()
    with PowerMeter() as pm, torch.no_grad():
        for bi, batch in enumerate(batches):
            width = max(len(ids) for _, ids in batch)
            inp = torch.full((len(batch), width), tok.pad_token_id, dtype=torch.long)
            att = torch.zeros((len(batch), width), dtype=torch.long)
            for r, (_, ids) in enumerate(batch):
                inp[r, width - len(ids) :] = torch.tensor(ids)
                att[r, width - len(ids) :] = 1
            gen = model.generate(
                input_ids=inp.to(dev),
                attention_mask=att.to(dev),
                do_sample=False,
                max_new_tokens=batch[0][0]["max_new_tokens"],
                eos_token_id=stop,
                pad_token_id=tok.pad_token_id,
            )
            for r, (it, _) in enumerate(batch):
                new = gen[r, width:].tolist()
                cut = next((k for k, t in enumerate(new) if t in stop), len(new))
                gen_tokens += cut
                text = tok.decode(new[:cut], skip_special_tokens=False)
                if it.get("thinking") and "</think>" not in text:
                    text = "<think>" + text + "</think>"  # ran out of budget while reasoning: no answer
                parsed = parse_output(text)
                s = score(it, parsed)
                results.append(
                    {
                        "id": it["id"],
                        "suite": it["suite"],
                        "lang": it["lang"],
                        "score": s["score"],
                        "detail": s.get("detail"),
                        "output": text[-3000:],
                        "tokens": cut,
                    }
                )
            if bi % 10 == 0:
                log(f"  batch {bi + 1}/{len(batches)} rows {len(results)}")
    secs = time.time() - t_start
    report = {
        "tag": tag,
        "n": len(results),
        "seconds": round(secs),
        "generated_tokens": gen_tokens,
        "tokens_per_second": round(gen_tokens / max(secs, 1e-9), 1),
        "energy_wh": pm.wh,
        "wh_per_1k_generated_tokens": round(pm.wh / gen_tokens * 1000, 4) if pm.wh and gen_tokens else None,
        "scores": aggregate(results),
    }
    write_json(out / f"bench_{tag}.json", {**report, "results": results})
    log("BENCH", tag, json.dumps({k: v for k, v in report.items()}, ensure_ascii=False))
    return report


# ------------------------------------------------------------------ training
def make_batches(examples: list[dict], batch_tokens: int, rng: random.Random) -> list[list[dict]]:
    """Length-bucketed batches of at most `batch_tokens` padded tokens, in random order."""
    exs = sorted(examples, key=lambda e: len(e["input_ids"]))
    out, cur = [], []
    for e in exs:
        if cur and (len(cur) + 1) * len(e["input_ids"]) > batch_tokens:
            out.append(cur)
            cur = []
        cur.append(e)
    if cur:
        out.append(cur)
    rng.shuffle(out)
    return out


def collate(group, pad_id, dev):
    import torch

    from birds.render import IGNORE

    width = max(len(e["input_ids"]) for e in group)
    ids = torch.full((len(group), width), pad_id, dtype=torch.long)
    lab = torch.full((len(group), width), IGNORE, dtype=torch.long)
    att = torch.zeros((len(group), width), dtype=torch.long)
    for i, e in enumerate(group):
        n = len(e["input_ids"])
        ids[i, :n] = torch.tensor(e["input_ids"])
        lab[i, :n] = torch.tensor(e["labels"])
        att[i, :n] = 1
    return ids.to(dev), lab.to(dev), att.to(dev)


def encode_file(tok, path, max_len: int, limit: int, seed: int) -> tuple[list[dict], dict]:
    from birds.render import IGNORE, encode, expand

    recs = read_jsonl(path)
    if limit:
        recs = random.Random(seed).sample(recs, min(limit, len(recs)))
    out, dropped = [], 0
    for r in recs:
        for ex in expand(r):
            e = encode(tok, ex, max_len)
            if e is None:
                dropped += 1
                continue
            e["source"] = r["source"]
            out.append(e)
    stats = {
        "records": len(recs),
        "examples": len(out),
        "dropped": dropped,
        "tokens": sum(len(e["input_ids"]) for e in out),
        "label_tokens": sum(sum(x != IGNORE for x in e["labels"]) for e in out),
    }
    return out, stats


def label_losses(model, ids, lab, att):
    """Loss of every label token of the batch: (losses, row index of each).

    The vocabulary has 248k entries, so logits are computed only where there is something to learn
    (the hidden state just before each label token), not for every position of the batch.
    """
    import torch

    from birds.render import IGNORE

    core = model.get_base_model() if hasattr(model, "get_base_model") else model
    hidden = core.model(input_ids=ids, attention_mask=att).last_hidden_state
    keep = lab[:, 1:] != IGNORE
    rows = keep.nonzero()[:, 0]
    logits = core.lm_head(hidden[:, :-1][keep])
    return torch.nn.functional.cross_entropy(logits.float(), lab[:, 1:][keep], reduction="none"), rows


def evaluate(model, eval_batches, pad_id, dev) -> dict:
    """Mean loss per label token, overall and per source."""
    import torch

    model.eval()
    tot, n, per = 0.0, 0, {}
    with torch.no_grad():
        for g in eval_batches:
            ids, lab, att = collate(g, pad_id, dev)
            losses, rows = label_losses(model, ids, lab, att)
            sums = torch.zeros(len(g), device=losses.device).index_add_(0, rows, losses)
            cnts = torch.bincount(rows, minlength=len(g))
            for i, e in enumerate(g):
                s, c = sums[i].item(), cnts[i].item()
                tot, n = tot + s, n + c
                a = per.setdefault(e["source"], [0.0, 0])
                a[0], a[1] = a[0] + s, a[1] + c
    model.train()
    return {
        "loss": round(tot / max(n, 1), 4),
        "by_source": {k: round(v[0] / max(v[1], 1), 4) for k, v in sorted(per.items())},
    }


def train(a):
    import torch
    from peft import LoraConfig, get_peft_model

    out, local = Path(a.out), Path("/tmp/bird_run")
    local.mkdir(parents=True, exist_ok=True)
    tok, model, dev = load_model(a.model, None, True)
    rng = random.Random(a.seed)
    train_ex, st = encode_file(tok, Path(a.data) / "train.jsonl", a.max_len, a.max_examples, a.seed)
    eval_ex, est = encode_file(tok, Path(a.data) / "eval.jsonl", a.max_len, a.max_eval, a.seed)
    log("train", st, "eval", est)

    model.config.use_cache = False
    if dev == "cuda" and a.grad_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    cfg = LoraConfig(
        r=a.lora_r,
        lora_alpha=a.lora_alpha,
        lora_dropout=a.lora_dropout,
        target_modules=LORA_TARGETS,
        use_rslora=False,
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, cfg)
    params = [p for p in model.parameters() if p.requires_grad]
    log("trainable params", sum(p.numel() for p in params), "of", sum(p.numel() for p in model.parameters()))
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=a.weight_decay, betas=(0.9, 0.999))

    epoch_batches = make_batches(train_ex, a.batch_tokens, rng)
    eval_batches = make_batches(eval_ex, a.batch_tokens, random.Random(0))
    steps_per_epoch = math.ceil(len(epoch_batches) / a.grad_accum)
    total = math.ceil(steps_per_epoch * a.epochs)
    if a.max_steps > 0:
        total = min(total, a.max_steps)
    warm = max(1, int(total * a.warmup))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: (
            min(1.0, (s + 1) / warm)
            * (a.min_lr_ratio + (1 - a.min_lr_ratio) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, total)))))
        ),
    )
    plan = {
        "steps": total,
        "steps_per_epoch": steps_per_epoch,
        "batches_per_epoch": len(epoch_batches),
        "warmup_steps": warm,
        "args": vars(a),
        "train": st,
        "eval": est,
    }
    write_json(out / "plan.json", plan)
    log("plan", {k: plan[k] for k in ("steps", "steps_per_epoch", "batches_per_epoch", "warmup_steps")})

    history, best, step, seen_tokens, bi = [], None, 0, 0, 0
    model.train()
    t_train = time.time()
    with PowerMeter() as pm:
        ev = evaluate(model, eval_batches, tok.pad_token_id, dev) if eval_batches else None
        history.append({"step": 0, "eval": ev})
        log("eval step 0", ev and ev["loss"])
        run_loss, run_n = 0.0, 0
        while step < total:
            opt.zero_grad(set_to_none=True)
            for _ in range(a.grad_accum):
                if bi >= len(epoch_batches):
                    epoch_batches, bi = make_batches(train_ex, a.batch_tokens, rng), 0
                ids, lab, att = collate(epoch_batches[bi], tok.pad_token_id, dev)
                bi += 1
                loss = label_losses(model, ids, lab, att)[0].mean()
                (loss / a.grad_accum).backward()
                run_loss, run_n, seen_tokens = run_loss + loss.item(), run_n + 1, seen_tokens + int(att.sum())
            torch.nn.utils.clip_grad_norm_(params, a.max_grad_norm)
            opt.step()
            sched.step()
            step += 1
            elapsed = time.time() - t_train
            if step % a.log_steps == 0 or step == total:
                rec = {
                    "step": step,
                    "loss": round(run_loss / run_n, 4),
                    "lr": sched.get_last_lr()[0],
                    "tokens_per_second": round(seen_tokens / elapsed),
                    "minutes": round(elapsed / 60, 1),
                    "energy_wh": pm.wh,
                    "gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 1) if dev == "cuda" else None,
                }
                history.append(rec)
                log("train", rec)
                run_loss, run_n = 0.0, 0
            stop_now = a.time_budget and elapsed / 60 > a.time_budget
            if step % a.eval_steps == 0 or step == total or stop_now:
                ev = evaluate(model, eval_batches, tok.pad_token_id, dev) if eval_batches else None
                history.append({"step": step, "eval": ev})
                log("eval step", step, ev and ev["loss"])
                model.save_pretrained(local / "last")
                save_tree(local / "last", out / "adapter-last")
                if ev and (best is None or ev["loss"] < best["loss"]):
                    best = {"step": step, "loss": ev["loss"]}
                    shutil.rmtree(local / "best", ignore_errors=True)
                    shutil.copytree(local / "last", local / "best")
                    save_tree(local / "best", out / "adapter-best")
                write_json(out / "history.json", {"history": history, "best": best})
            if stop_now:
                log("time budget reached, stopping cleanly at step", step)
                break
    summary = {
        "steps_done": step,
        "best": best,
        "train_minutes": round((time.time() - t_train) / 60, 1),
        "train_energy_wh": pm.wh,
        "tokens_seen": seen_tokens,
    }
    final = local / ("best" if best else "last")
    tok.save_pretrained(final)
    save_tree(final, out / ("adapter-best" if best else "adapter-last"))
    write_json(out / "summary.json", summary)
    log("TRAIN DONE", summary)
    if a.bench:
        # benchmark the checkpoint we would ship: the best one on eval loss, merged into the base weights
        del model, opt
        if dev == "cuda":
            torch.cuda.empty_cache()
        tok, model, dev = load_model(a.model, str(final), False)
        items = read_jsonl(a.bench)
        if a.bench_limit:
            items = random.Random(0).sample(items, min(a.bench_limit, len(items)))
        run_bench(tok, model, dev, items, a.gen_batch_tokens, a.tag, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["train", "bench"])
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--adapter", default=None, help="bench: LoRA adapter directory to evaluate")
    ap.add_argument("--data", default="/dataset", help="directory with train.jsonl and eval.jsonl")
    ap.add_argument("--bench", default="", help="bench.jsonl (train: run at the end; bench: required)")
    ap.add_argument("--bench-limit", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--min-lr-ratio", type=float, default=0.1)
    ap.add_argument("--warmup", type=float, default=0.05)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--max-grad-norm", type=float, default=1.0)
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--lora-alpha", type=float, default=32, help="alpha = r (scale 1), the community default for Qwen3.5")
    ap.add_argument("--lora-dropout", type=float, default=0.0)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--batch-tokens", type=int, default=8192, help="padded tokens per forward pass")
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--no-grad-checkpointing", dest="grad_checkpointing", action="store_false")
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--max-examples", type=int, default=0)
    ap.add_argument("--max-eval", type=int, default=600)
    ap.add_argument("--eval-steps", type=int, default=250)
    ap.add_argument("--log-steps", type=int, default=25)
    ap.add_argument("--time-budget", type=float, default=0, help="training minutes; clean stop beyond (0 = none)")
    ap.add_argument("--gen-batch-tokens", type=int, default=48000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    random.seed(a.seed)
    import torch

    torch.manual_seed(a.seed)
    if shutil.which("nvidia-smi"):
        subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], check=False)
    if a.mode == "train":
        train(a)
    else:
        tok, model, dev = load_model(a.model, a.adapter, False)
        items = read_jsonl(a.bench)
        if a.bench_limit:
            items = random.Random(0).sample(items, min(a.bench_limit, len(items)))
        run_bench(tok, model, dev, items, a.gen_batch_tokens, a.tag, Path(a.out))


if __name__ == "__main__":
    main()
