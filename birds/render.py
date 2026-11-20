"""Turn a record into token ids + labels with the model's own chat template.

Rules (they mirror what the model sees at inference time):
  * A conversation is split into one training example per user query (`expand`).
  * Loss is only on the assistant turns that follow the last user query (the answer, or the
    tool-calling loop that leads to it). Earlier turns are context.
  * thinking=True  : the generation prompt ends with "<think>\n"; the label is reasoning + "</think>" + answer.
  * thinking=False : the generation prompt ends with an empty think block; the label is the answer only.
"""

from __future__ import annotations

IGNORE = -100


def expand(rec: dict) -> list[dict]:
    """One example per user query: messages up to the end of that query's assistant turns."""
    msgs = rec["messages"]
    cuts = [i for i, m in enumerate(msgs) if m["role"] == "user"][1:] + [len(msgs)]
    out = []
    for n, end in enumerate(cuts):
        part = msgs[:end]
        if part and part[-1]["role"] == "assistant":
            out.append({**rec, "id": f"{rec['id']}#{n}", "messages": part})
    return out


def _clean(msgs: list[dict], thinking: bool) -> list[dict]:
    out = []
    for m in msgs:
        m = dict(m)
        if m["role"] == "assistant":
            m["reasoning_content"] = (m.get("reasoning_content") or "") if thinking else ""
        out.append(m)
    return out


def spans(tok, rec: dict) -> tuple[str, list[tuple[int, int]]]:
    """(full text, [(start, end) character spans to learn])."""
    thinking = bool(rec.get("thinking"))
    msgs = _clean(rec["messages"], thinking)
    kw = {"tools": rec.get("tools") or None, "enable_thinking": thinking, "tokenize": False}
    full = tok.apply_chat_template(msgs, **kw).rstrip("\n")
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    out = []
    for k in range(last_user + 1, len(msgs)):
        if msgs[k]["role"] != "assistant":
            continue
        prompt = tok.apply_chat_template(msgs[:k], add_generation_prompt=True, **kw)
        if not full.startswith(prompt):
            raise ValueError("generation prompt is not a prefix of the rendered conversation")
        end = full.find("<|im_end|>", len(prompt))
        if end < 0:
            raise ValueError("assistant turn is not closed")
        out.append((len(prompt), end + len("<|im_end|>")))
    return full, out


def encode(tok, rec: dict, max_len: int) -> dict | None:
    """Token ids and labels, or None when the example is too long or has nothing to learn."""
    full, sp = spans(tok, rec)
    enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
    ids = enc["input_ids"]
    if len(ids) > max_len or not sp:
        return None
    labels = [IGNORE] * len(ids)
    for j, (a, b) in enumerate(enc["offset_mapping"]):
        if any(a >= s and b <= e for s, e in sp) and b > a:
            labels[j] = ids[j]
    if all(x == IGNORE for x in labels):
        return None
    return {"input_ids": ids, "labels": labels}


def prompt(tok, messages: list[dict], tools: list | None, thinking: bool) -> str:
    """Generation prompt for inference/benchmark."""
    return tok.apply_chat_template(
        _clean(messages, thinking), tools=tools or None, enable_thinking=thinking, tokenize=False,
        add_generation_prompt=True,
    )
