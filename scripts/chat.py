"""Chat with Bird through the harness.

python scripts/chat.py --base-url http://localhost:8080/v1 --model bird --workspace ./work --searxng http://localhost:8888
python scripts/chat.py --local Qwen/Qwen3.5-4B --adapter out/adapter --workspace ./work
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from birds.harness import Agent, CompletionsClient, Config, LocalClient  # noqa: E402
from birds.harness.agent import compact  # noqa: E402


def confirm(tool: str, arguments: dict) -> bool:
    print(
        f"\n! External content read in this request looked like it contained instructions.\n! Bird now wants to run: {tool}"
    )
    print("! " + json.dumps(arguments, ensure_ascii=False)[:600])
    return input("! Allow this action? [y/N] ").strip().lower() in ("y", "yes", "o", "oui")


def show(run) -> None:
    for s in run.steps:
        extra = "".join(f" [{f}]" for f in s.flags) + (f" -> {s.decision}" if s.decision != "allow" else "")
        print(
            f"  · {s.tool} {json.dumps(s.arguments, ensure_ascii=False)[:160]}{extra} ({s.seconds:.2f}s)"
            + (f"\n    error: {s.error}" if s.error else "")
        )
    print(f"\n{run.answer}\n")
    for d in run.drafts:
        print(f"[draft, not sent] to={d['to']} subject={d['subject']!r} tone={d['tone']}\n{d['body']}\n")
    for label, items in (("sources", run.sources), ("files", run.files)):
        if items:
            print(f"{label}: " + ", ".join(items))
    r = run.report
    energy = (
        "energy: not measured"
        if r["energy_wh"] is None
        else f"energy: {r['energy_wh']} Wh ({r['energy_kind']}, {r['energy_source']})"
    )
    print(
        f"[{run.stop_reason}] tokens in/out: {r['prompt_tokens']}/{r['completion_tokens']} · {r['wall_seconds']}s · "
        f"{r['tool_calls']} tool calls · {r['bytes_fetched']} bytes fetched · {energy}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", help="OpenAI-compatible endpoint ending with /v1 (llama.cpp, vLLM, Ollama)")
    ap.add_argument("--model", default="bird", help="model name on the endpoint")
    ap.add_argument("--api-key", default=os.environ.get("BIRD_API_KEY"))
    ap.add_argument("--local", metavar="MODEL", help="run the model in-process with transformers (GPU box)")
    ap.add_argument("--adapter", metavar="DIR", help="LoRA adapter directory (with --local)")
    ap.add_argument(
        "--tokenizer", default="Qwen/Qwen3.5-4B", help="tokenizer used to render the prompt (endpoint mode)"
    )
    ap.add_argument("--workspace", default="./workspace")
    ap.add_argument("--searxng", metavar="URL", help="SearXNG base URL; without it web_search is not offered")
    ap.add_argument("--think", action="store_true", help="let the model reason before answering (costs more tokens)")
    ap.add_argument(
        "--allow-python", action="store_true", help="enable run_python: NOT a sandbox, disposable container only"
    )
    ap.add_argument(
        "--no-pin-dns", action="store_true", help="only behind an egress proxy that filters destinations itself"
    )
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("message", nargs="*", help="one-shot question; without it, an interactive chat starts")
    a = ap.parse_args()
    if bool(a.base_url) == bool(a.local):
        ap.error("give exactly one of --base-url or --local")

    workspace = Path(a.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = Config(
        workspace=workspace,
        searxng_url=a.searxng,
        allow_python=a.allow_python,
        max_tokens=a.max_tokens,
        pin_dns=not a.no_pin_dns,
    )
    if a.local:
        llm = LocalClient(a.local, a.adapter)
        tok = llm.tok
    else:
        from transformers import AutoTokenizer  # tokenizer only: no model weights are loaded here

        llm, tok = CompletionsClient(a.base_url, a.model, a.api_key), AutoTokenizer.from_pretrained(a.tokenizer)
    http = None
    if a.no_pin_dns:
        import httpx

        http = httpx.Client(follow_redirects=False)  # honours HTTPS_PROXY
    agent = Agent(llm, tok, cfg, confirm=confirm, http=http)

    if a.message:
        show(agent.run(" ".join(a.message), thinking=a.think))
        return
    history = None
    print("Bird — empty line or Ctrl-D to quit.")
    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            break
        run = agent.run(user, history=history, thinking=a.think)
        show(run)
        history = compact(run.messages) if run.stop_reason == "answer" else history


if __name__ == "__main__":
    main()
