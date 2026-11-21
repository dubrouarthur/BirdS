"""Serve the Bird web chat.

Demo (scripted answers, no model):      python scripts/serve.py --demo
Real model, OpenAI-compatible server:   python scripts/serve.py --base-url http://127.0.0.1:8080/v1 --model bird-4b
Real model, loaded in this process:     python scripts/serve.py --local MODEL [--adapter DIR]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_argument_group("backend (choose one)")
    mode.add_argument("--demo", action="store_true", help="scripted demo backend, no model")
    mode.add_argument("--base-url", help="OpenAI-compatible endpoint, e.g. http://127.0.0.1:8080/v1")
    mode.add_argument("--model", help="model name to request from --base-url")
    mode.add_argument("--api-key", default=None, help="API key for --base-url, if the server needs one")
    mode.add_argument("--local", metavar="MODEL", help="load this model in-process with transformers (heavy)")
    mode.add_argument("--adapter", metavar="DIR", help="LoRA adapter directory for --local")
    p.add_argument("--workspace", help="directory for generated files (default: a fresh temporary directory)")
    p.add_argument("--searxng", metavar="URL", help="SearXNG instance used by web_search")
    p.add_argument(
        "--grid-intensity",
        type=float,
        default=None,
        metavar="G_PER_KWH",
        help="grid carbon intensity in g CO2e/kWh; without it no CO2 figure is shown",
    )
    p.add_argument(
        "--tokenizer", default="Qwen/Qwen3.5-4B", help="tokenizer used to render the prompt (--base-url mode)"
    )
    p.add_argument(
        "--measure-gpu", action="store_true", help="sample nvidia-smi during generation (model on this machine)"
    )
    p.add_argument("--wh-per-1k-tokens", type=float, default=None, help="your own calibration; shown as an estimate")
    p.add_argument("--calibration-source", default=None, help="where that calibration comes from")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    chosen = [bool(args.demo), bool(args.base_url), bool(args.local)]
    if sum(chosen) != 1:
        p.error("choose exactly one of --demo, --base-url (with --model) or --local")
    if args.base_url and not args.model:
        p.error("--base-url needs --model")
    if args.adapter and not args.local:
        p.error("--adapter only applies to --local")
    if args.grid_intensity is not None and args.grid_intensity < 0:
        p.error("--grid-intensity must be >= 0")
    return args


def build_backend(args: argparse.Namespace, workspace: Path | None = None):
    from birds.web.backends import DemoBackend, HarnessBackend

    if args.demo:
        return DemoBackend()
    config = {
        "searxng_url": args.searxng,
        "measure_gpu": args.measure_gpu,
        "wh_per_1k_tokens": args.wh_per_1k_tokens,
        "calibration_source": args.calibration_source,
    }
    if args.base_url:
        return HarnessBackend.completions(
            args.base_url, args.model, workspace=workspace, api_key=args.api_key, tokenizer=args.tokenizer, **config
        )
    return HarnessBackend.local(args.local, workspace=workspace, adapter=args.adapter, **config)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    import uvicorn

    from birds.web.server import create_app

    workspace = Path(args.workspace or tempfile.mkdtemp(prefix="bird-workspace-")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    backend = build_backend(args, workspace)
    app = create_app(backend, workspace=workspace, grid_intensity=args.grid_intensity)
    print(f"Bird [{backend.kind}: {backend.model}]  http://{args.host}:{args.port}  workspace={app.state.workspace}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
