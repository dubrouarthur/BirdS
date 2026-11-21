"""Model clients behind one small interface.

    generate(prompt, max_tokens, stop) -> {"text", "prompt_tokens", "completion_tokens", "seconds"}

The prompt is the RAW text rendered with the model's own chat template (birds.render.prompt). We deliberately do
not use the server's chat template or tool-call parser: the model is trained on one exact format and we parse it
ourselves (birds.parse).
"""

from __future__ import annotations

import time

STOP = ["<|im_end|>"]


def _cut(text: str, stop: list[str]) -> str:
    for s in stop or []:
        text = text.split(s, 1)[0]
    return text


class CompletionsClient:
    """OpenAI-compatible /v1/completions (llama.cpp server, vLLM, Ollama's OpenAI endpoint)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        temperature: float = 0.0,
        timeout: float = 300.0,
        extra: dict | None = None,
        transport=None,
    ):
        import httpx

        self.url = base_url.rstrip("/") + "/completions"  # base_url ends with /v1
        self.model, self.temperature, self.extra = model, temperature, extra or {}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    def generate(self, prompt: str, max_tokens: int, stop: list[str]) -> dict:
        t0 = time.monotonic()
        body = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "stop": stop,
            "temperature": self.temperature,
            "stream": False,
            **self.extra,
        }
        r = self.http.post(self.url, json=body)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage") or {}
        return {
            "text": _cut(data["choices"][0].get("text") or "", stop),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "seconds": round(time.monotonic() - t0, 3),
        }


class LocalClient:
    """transformers in-process, greedy decoding. For a GPU box; imports are lazy so the harness stays light."""

    local = True  # the model runs on this machine: GPU power sampling is meaningful

    def __init__(self, model_id_or_path: str, adapter: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(adapter or model_id_or_path)
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(model_id_or_path, torch_dtype=dtype, device_map="auto")
        if adapter:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter)
        self.model.eval()

    def generate(self, prompt: str, max_tokens: int, stop: list[str]) -> dict:
        t0 = time.monotonic()
        enc = self.tok(prompt, add_special_tokens=False, return_tensors="pt").to(self.model.device)
        eos = [i for i in (self.tok.convert_tokens_to_ids(s) for s in stop or STOP) if isinstance(i, int) and i >= 0]
        with self.torch.no_grad():
            out = self.model.generate(
                **enc,
                do_sample=False,
                max_new_tokens=max_tokens,
                eos_token_id=eos or None,
                pad_token_id=self.tok.pad_token_id,
            )
        new = out[0, enc["input_ids"].shape[1] :]
        return {
            "text": _cut(self.tok.decode(new, skip_special_tokens=False), stop),
            "prompt_tokens": int(enc["input_ids"].shape[1]),
            "completion_tokens": int(new.shape[0]),
            "seconds": round(time.monotonic() - t0, 3),
        }


class FakeClient:
    """Scripted outputs for tests. Records the prompts it was given."""

    def __init__(self, outputs: list[str], seconds: float = 0.01):
        self.outputs, self.prompts, self.seconds = list(outputs), [], seconds

    def generate(self, prompt: str, max_tokens: int, stop: list[str]) -> dict:
        self.prompts.append(prompt)
        text = self.outputs.pop(0) if self.outputs else ""
        return {
            "text": _cut(text, stop),
            "prompt_tokens": len(prompt) // 4,
            "completion_tokens": len(text) // 4,
            "seconds": self.seconds,
        }
