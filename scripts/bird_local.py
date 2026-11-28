"""Bird local: use Bird's model on your own machine, from the chat (docs/LOCAL.md).

  1. vllm serve adubrou/Bird-S-4B --host 127.0.0.1 --port 8000      (the model server, on your machine)
  2. python scripts/bird_local.py                                    (this command)
  3. type the pairing code it prints in the chat: Réglages → Modèle → Bird local

It checks the model server (GET /v1/models, the model served, structured outputs), then starts the Bird harness on
http://127.0.0.1:8765 — the same app as the deployment, every tool running from this machine — and opens it in the
browser. The hosted chat (https://bird-s.vercel.app) can connect to it too: only that origin, only with the code.

Options: --vllm-url URL (default http://127.0.0.1:8000/v1), --model NAME, --port 8765, --allow-origin ORIGIN
(repeatable; replaces the default list), --no-browser, --new-code, --measure-gpu, --workspace DIR, --searxng URL.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from birds.web import local  # noqa: E402

FR_EN = {
    "checking": ("Vérification du serveur du modèle sur {url} …", "Checking the model server at {url} …"),
    "down": (
        "Aucun serveur de modèle ne répond sur {url}.\nDémarrez-le dans un autre terminal, puis relancez cette commande :",
        "No model server answers at {url}.\nStart it in another terminal, then run this command again:",
    ),
    "no_models": (
        "Le serveur du modèle répond, mais ne sert pas le modèle attendu ({detail}). Modèles servis : {models}.",
        "The model server answers but does not serve the expected model ({detail}). Served: {models}.",
    ),
    "unauthorized": (
        "Le serveur du modèle demande une clé : passez-la dans BIRD_LOCAL_VLLM_KEY (jamais affichée).",
        "The model server wants a key: put it in BIRD_LOCAL_VLLM_KEY (never printed).",
    ),
    "error": (
        "Le serveur du modèle répond de façon inattendue ({detail}).",
        "The model server answers oddly ({detail}).",
    ),
    "ok": ("Modèle servi : {model}", "Model served: {model}"),
    "other_model": (
        "Ce n'est pas un modèle Bird : les modules et le routage sont réglés pour Bird ({bird}). Pour un autre, passez --model.",
        "This is not a Bird model: the modules and routing are tuned for Bird ({bird}). For another one, pass --model.",
    ),
    "structured": ("Sorties structurées : {kind}", "Structured outputs: {kind}"),
    "no_structured": (
        "Sorties structurées : non détectées (le routage reste fiable, avec un filet de réparation).",
        "Structured outputs: not detected (routing still works, with a repair net).",
    ),
    "port": (
        "Le port {port} est déjà pris : fermez l'autre Bird local ou passez --port.",
        "Port {port} is already in use: close the other Bird local or pass --port.",
    ),  # fmt: skip
    "ready": ("Bird local est prêt", "Bird local is ready"),
    "open": ("Sur cette machine   {url}", "On this machine     {url}"),
    "hosted": (
        "Depuis le chat      {origin} → Réglages → Modèle → Bird local",
        "From the chat       {origin} → Settings → Model → Bird local",
    ),  # fmt: skip
    "code": ("Code d'appairage    {code}", "Pairing code        {code}"),
    "stop": (
        "Ctrl+C pour arrêter. Vos conversations restent sur cette machine.",
        "Ctrl+C to stop. Your conversations stay on this machine.",
    ),  # fmt: skip
}


def say(key: str, lang: str, **kw) -> str:
    fr, en = FR_EN[key]
    return (en if lang == "en" else fr).format(**kw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vllm-url", default=os.environ.get("BIRD_LOCAL_VLLM_URL") or local.DEFAULT_VLLM_URL)
    p.add_argument("--model", default=os.environ.get("BIRD_LOCAL_MODEL") or None, help="default: the model served")
    p.add_argument("--port", type=int, default=local.DEFAULT_PORT, help="loopback port of Bird local (8765)")
    p.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        metavar="ORIGIN",
        help="hosted chat allowed to call Bird local (exact origin, repeatable; default https://bird-s.vercel.app)",
    )
    p.add_argument("--no-browser", action="store_true", help="do not open the app in the browser")
    p.add_argument("--new-code", action="store_true", help="make a new pairing code (the old one stops working)")
    p.add_argument("--pairing-code", default=None, help=argparse.SUPPRESS)  # tests: a fixed code
    p.add_argument("--measure-gpu", action="store_true", help="sample nvidia-smi: energy measured on this machine")
    p.add_argument("--workspace", default=None, help="folder the agent may read (default: a temporary folder)")
    p.add_argument("--searxng", default=None, metavar="URL", help="SearXNG instance for the web search")
    p.add_argument("--grid-intensity", type=float, default=None, metavar="G_PER_KWH", help="your grid, g CO2e/kWh")
    p.add_argument("--lang", choices=("fr", "en"), default="fr")
    p.add_argument("--skip-structured-check", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        p.error("--port must be between 1024 and 65535")
    try:
        args.origins = local.clean_origins(args.allow_origin or os.environ.get("BIRD_LOCAL_ORIGINS", "").split(","))
    except ValueError as e:
        p.error(str(e))
    args.origins = args.origins or local.DEFAULT_ORIGINS
    return args


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # like uvicorn: a closed run's TIME_WAIT is free
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def build(args: argparse.Namespace, status: local.VllmStatus, code: str):
    """The app: the deployment's, on the user's model server, with the local guard in front."""
    from birds.web.server import create_app
    from birds.web.settings import Settings

    base = Settings.from_env()
    s = dataclasses.replace(
        base,
        base_url=status.base_url,
        model=status.model,
        model_label="Bird local",
        api_key=os.environ.get("BIRD_LOCAL_VLLM_KEY") or None,
        searxng_url=args.searxng or base.searxng_url,
        allow_user_endpoint=False,
        access_code=None,
        rate_limit=max(base.rate_limit, 120),
        measure_gpu=args.measure_gpu,
        grid_intensity=args.grid_intensity,
        gpu_label="Votre carte graphique",
        gpu_source=None,
        workspace=args.workspace,
        local_bird_port=args.port,
    )
    app = create_app(s)
    cfg = local.LocalConfig(
        code=code, port=args.port, origins=args.origins, vllm_url=status.base_url, model=status.model,
        structured=status.structured, measured=args.measure_gpu,
    )  # fmt: skip
    local.install(app, cfg)
    return app


def safe_console(*streams) -> None:
    """A Windows console or a redirected output in cp1252 cannot print « ─ » or « → »: replace, never crash."""
    for stream in streams or (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    safe_console()
    args = parse_args(argv)
    lang = args.lang
    print(say("checking", lang, url=args.vllm_url), flush=True)
    status = local.probe_vllm(
        args.vllm_url, model=args.model, api_key=os.environ.get("BIRD_LOCAL_VLLM_KEY") or None,
        check_structured=not args.skip_structured_check,
    )  # fmt: skip
    if not status.ok:
        if status.status == "down":
            from birds.harness.llm import normalize_base_url

            vport = (normalize_base_url(args.vllm_url).split("://", 1)[1].split("/", 1)[0].rpartition(":")[2]) or "8000"
            print(say("down", lang, url=status.base_url))
            print(
                "\n    "
                + local.vllm_command(args.model or local.DEFAULT_MODEL, int(vport) if vport.isdigit() else 8000)
            )
            print()
        else:
            print(say(status.status, lang, detail=status.detail, models=", ".join(status.models) or "-"))
        return 2
    print(say("ok", lang, model=status.model))
    if not args.model and "bird" not in (status.model or "").lower():
        print(say("other_model", lang, bird=local.DEFAULT_MODEL))
    print(say("structured", lang, kind=status.structured) if status.structured else say("no_structured", lang))
    if not port_free(args.port):
        print(say("port", lang, port=args.port))
        return 3
    code = args.pairing_code or local.load_or_create_code(rotate=args.new_code)
    app = build(args, status, code)
    url = f"http://127.0.0.1:{args.port}/"
    bar = "─" * 64
    print(f"\n{bar}\n  {say('ready', lang)}\n\n  {say('open', lang, url=url)}")
    for origin in args.origins:
        print("  " + say("hosted", lang, origin=origin))
    print(f"  {say('code', lang, code=code)}\n\n  {say('stop', lang)}\n{bar}\n", flush=True)
    if not args.no_browser:
        # the code rides in the fragment: never sent to any server, removed from the address bar by the page
        threading.Timer(1.0, lambda: webbrowser.open(f"{url}#pair={code}")).start()
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")  # loopback only, never 0.0.0.0
    return 0


if __name__ == "__main__":
    sys.exit(main())
