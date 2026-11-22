# /// script
# requires-python = ">=3.11"
# dependencies = ["torch", "transformers>=5.2", "peft>=0.17", "accelerate", "safetensors", "huggingface_hub"]
# ///
"""Merge the Bird LoRA adapter into Qwen3.5-4B and write a FULL checkpoint with the same layout as the base.

Training loads the text-only causal LM, so the adapter keys follow that class. We merge there, then copy
every merged language-model tensor into the original multimodal model (vision tower untouched) and save
it, so the result deploys exactly like Qwen/Qwen3.5-4B (vLLM, Inference Endpoints, GGUF conversion).
Adapted from the BIRD-M project's merge job. Runs on CPU (32 GB RAM): flash-linear-attention is deliberately
not installed, because its Triton kernels need a GPU driver; transformers falls back to plain PyTorch.

  hf jobs uv run --flavor cpu-upgrade --timeout 1h -v hf://buckets/adubrou/birds-runs:/out jobs/merge_job.py \
      --adapter /out/bird-v0/adapter-best --out /out/bird-v0/merged
"""

import argparse
import os
import shutil
import time
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="Qwen/Qwen3.5-4B")
ap.add_argument("--adapter", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
t0 = time.time()


def log(*x):
    print(f"[{round(time.time() - t0)}s]", *x, flush=True)


dev = "cuda" if torch.cuda.is_available() else "cpu"
lm = AutoModelForCausalLM.from_pretrained(a.base, dtype=torch.bfloat16)
before = {k: v.detach().clone() for k, v in lm.state_dict().items() if k.endswith("layers.0.mlp.down_proj.weight")}
lm = PeftModel.from_pretrained(lm, a.adapter).merge_and_unload()
merged = {k: v.detach().to("cpu") for k, v in lm.state_dict().items()}
changed = [k for k, v in before.items() if not torch.equal(v, merged[k])]
assert changed, "the adapter changed nothing: wrong adapter path or target modules"
log("merged text model tensors:", len(merged), "| adapted weight differs from base:", changed)
del lm

full = AutoModelForImageTextToText.from_pretrained(a.base, dtype=torch.bfloat16)
fsd = full.state_dict()
copied, missing = 0, []
with torch.no_grad():
    for k, v in merged.items():
        target = next((c for c in (k, k.replace("model.", "model.language_model.", 1))
                       if c in fsd and fsd[c].shape == v.shape), None)
        if target is None:
            missing.append(k)
            continue
        fsd[target].copy_(v)
        copied += 1
log("copied", copied, "of", len(merged), "| unmapped:", missing[:10])
assert copied == len(merged), f"unmapped merged tensors: {missing[:20]}"
del merged

local = Path("/tmp/merged")
local.mkdir(parents=True, exist_ok=True)
full.save_pretrained(local, safe_serialization=True, max_shard_size="5GB")
AutoTokenizer.from_pretrained(a.adapter if (Path(a.adapter) / "tokenizer_config.json").exists() else a.base).save_pretrained(local)
for f in ("preprocessor_config.json", "video_preprocessor_config.json", "chat_template.jinja", "generation_config.json", "LICENSE"):
    try:
        shutil.copy(hf_hub_download(a.base, f), local / f)
    except Exception as e:  # noqa: BLE001 - not every base ships every file
        log("skip", f, type(e).__name__)
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
for f in sorted(local.iterdir()):
    dst = out / f.name
    shutil.copyfile(f, dst)
    with open(dst, "rb+") as fh:
        os.fsync(fh.fileno())
    log("copied", f.name, f.stat().st_size)
os.sync()
log("waiting for the bucket mount to flush")
time.sleep(int(os.environ.get("FLUSH_WAIT", "240")))
log("done", sorted(p.name for p in out.iterdir()))

# sanity AFTER the files are safely in the bucket: a few greedy tokens are enough to see the new identity
# (bf16 generation on CPU is very slow, so keep it short)
tok_s = AutoTokenizer.from_pretrained(a.adapter if (Path(a.adapter) / "tokenizer_config.json").exists() else a.base)
full.to(dev).eval()
ids = tok_s.apply_chat_template([{"role": "user", "content": "Qui es-tu ?"}], add_generation_prompt=True,
                                enable_thinking=False, return_tensors="pt", return_dict=True).to(dev)
with torch.no_grad():
    gen = full.generate(**ids, max_new_tokens=8 if dev == "cpu" else 40, do_sample=False)
log("SANITY Qui es-tu ? ->", repr(tok_s.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)))
