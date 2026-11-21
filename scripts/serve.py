"""Serve the Bird web chat locally (same app as the Vercel deployment).

Demo (scripted answers, no model):      python scripts/serve.py --demo
Real model, OpenAI-compatible server:   python scripts/serve.py --base-url http://127.0.0.1:8080/v1 --model bird
Real model, loaded in this process:     python scripts/serve.py --local MODEL [--adapter DIR]
Exactly like the deployment:            BIRD_BASE_URL=... BIRD_API_KEY=... python scripts/serve.py --from-env
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_argument_group("backend (choose one)")
    mode.add_argument("--demo", action="store_true", help="scripted demo backend, no model")
    mode.add_argument("--from-env", action="store_true", help="read BIRD_* variables, like the deployed app")
    mode.add_argument("--base-url", help="OpenAI-compatible endpoint, with or without /v1")
    mode.add_argument("--model", help="model name to request from --base-url")
    mode.add_argument("--api-key", default=None, help="API key for --base-url (default: BIRD_API_KEY)")
    mode.add_argument("--local", metavar="MODEL", help="load this model in-process with transformers (heavy)")
    mode.add_argument("--adapter", metavar="DIR", help="LoRA adapter directory for --local")
    p.add_argument("--workspace", help="folder the agent may read (default: a temporary folder per request)")
    p.add_argument("--searxng", metavar="URL", help="SearXNG instance used by web_search")
    p.add_argument(
        "--grid-intensity",
        type=float,
        default=None,
        metavar="G_PER_KWH",
        help="grid carbon intensity in g CO2e/kWh; without it no CO2 figure is shown",
    )
    p.add_argument("--tokenizer", default=None, help="real tokenizer instead of the vendored chat template")
    p.add_argument("--measure-gpu", action="store_true", help="sample nvidia-smi during generation")
    p.add_argument("--wh-per-1k-tokens", type=float, default=None, help="your own calibration; shown as an estimate")
    p.add_argument("--calibration-source", default=None, help="where that calibration comes from")
    p.add_argument("--access-code", default=None, help="ask visitors for this code before using the model")
    p.add_argument("--allow-user-endpoint", action="store_true", help="let visitors type their own endpoint")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    chosen = [bool(args.demo), bool(args.base_url), bool(args.local), bool(args.from_env)]
    if sum(chosen) != 1:
        p.error("choose exactly one of --demo, --from-env, --base-url (with --model) or --local")
    if args.base_url and not args.model:
        p.error("--base-url needs --model")
    if args.adapter and not args.local:
        p.error("--adapter only applies to --local")
    if args.grid_intensity is not None and args.grid_intensity < 0:
        p.error("--grid-intensity must be >= 0")
    return args


def build_settings(args: argparse.Namespace):
    from birds.web.settings import Settings

    base = Settings.from_env()  # BIRD_SIGNING_SECRET, BIRD_RATE_LIMIT... apply locally too
    if args.from_env:
        return base
    s = dataclasses.replace(
        base,
        base_url=args.base_url,
        model=args.model or base.model,
        api_key=args.api_key or os.environ.get("BIRD_API_KEY") or None,
        searxng_url=args.searxng or base.searxng_url,
        grid_intensity=args.grid_intensity if args.grid_intensity is not None else base.grid_intensity,
        wh_per_1k_tokens=args.wh_per_1k_tokens,
        calibration_source=args.calibration_source,
        measure_gpu=args.measure_gpu,
        access_code=args.access_code or base.access_code,
        allow_user_endpoint=args.allow_user_endpoint or (not args.base_url and not args.local),
        workspace=args.workspace,
        tokenizer=args.tokenizer,
    )
    if args.demo:
        s.base_url = None
    if args.local:
        from birds.harness import LocalClient

        s.local_llm = LocalClient(args.local, args.adapter)
        s.local_tok, s.model = s.local_llm.tok, Path(args.adapter or args.local).name
    return s


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    import uvicorn

    from birds.web.server import create_app

    settings = build_settings(args)
    app = create_app(settings)
    shown = app.state.server_backend or app.state.demo
    print(f"Bird [{shown.kind}: {shown.model}]  http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
