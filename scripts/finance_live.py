"""Live check of the market providers (get_quote): one real call each, through the tools' own code and the egress
guard. ``--record FILE`` keeps the keyless answers (CoinGecko, ECB) for the scripted demo; a licensed feed's answer
(Twelve Data) is never recorded: its terms do not allow showing it outside a licensed deployment.

    .venv/bin/python scripts/finance_live.py                       # keyless providers
    BIRD_TWELVEDATA_API_KEY=… .venv/bin/python scripts/finance_live.py   # shares and indices too
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from birds.harness import guard  # noqa: E402
from birds.harness.config import Config, Context  # noqa: E402
from birds.harness.tools.opendata.finance import get_quote  # noqa: E402

CASES = [
    ("CoinGecko", {"symbols": "bitcoin", "range": "1y"}, "fr"),
    ("CoinGecko (2)", {"symbols": "bitcoin, ethereum", "range": "6m"}, "fr"),
    ("BCE", {"symbols": "EUR/USD", "range": "6m"}, "fr"),
    ("BCE (croisé)", {"symbols": "USD/JPY", "range": "1m"}, "en"),
    ("Twelve Data", {"symbols": "Apple", "range": "1m"}, "fr"),
    ("Twelve Data (2)", {"symbols": "LVMH, Hermès", "range": "1y"}, "fr"),
]
# the scripted demo's asks (birds/web/backends.py) and the next asks their cards offer
DEMO = [
    ({"symbols": "Bitcoin", "range": "6m"}, "fr"),
    ({"symbols": "Bitcoin", "range": "1y"}, "fr"),
    ({"symbols": "Bitcoin", "range": "1m"}, "fr"),
    ({"symbols": "Bitcoin, Ethereum", "range": "6m"}, "fr"),
    ({"symbols": "Bitcoin, Ethereum", "range": "1y"}, "fr"),
    ({"symbols": "EUR/USD", "range": "6m"}, "fr"),
    ({"symbols": "EUR/USD", "range": "1y"}, "fr"),
    ({"symbols": "EUR/USD", "range": "5y"}, "fr"),
    ({"symbols": "Bitcoin", "range": "6m", "currency": "USD"}, "en"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", help="write the keyless providers' answers (URL -> body) for the scripted demo")
    ap.add_argument("--demo", action="store_true", help="the demo's asks")
    a = ap.parse_args(argv)
    pin = os.environ.get("BIRD_PIN_DNS", "0") not in ("0", "false", "")
    cfg = Config(workspace=Path(tempfile.gettempdir()), audit_file=None, pin_dns=pin,
                 twelvedata_api_key=os.environ.get("BIRD_TWELVEDATA_API_KEY") or None,
                 coingecko_api_key=os.environ.get("BIRD_COINGECKO_API_KEY") or None)  # fmt: skip
    client = httpx.Client(trust_env=not pin, follow_redirects=False, timeout=15.0)
    seen: dict[str, object] = {}
    real = guard.fetch_bytes

    def spy(c, conf, url, **kw):
        out = real(c, conf, url, **kw)
        if "twelvedata" not in url:
            body = out[2].decode("utf-8", errors="replace")
            try:
                seen[url] = json.loads(body)
            except ValueError:
                seen[url] = body  # the ECB's CSV
        return out

    guard.fetch_bytes = spy
    ok_all = True
    cases = [(f"demo {i}", args, lang) for i, (args, lang) in enumerate(DEMO)] if a.demo else CASES
    for name, args, lang in cases:
        ctx = Context(config=cfg, http=client, lang=lang, request="")
        t0 = time.monotonic()
        try:
            get_quote(dict(args), ctx)
            w = ctx.step_info["widget"]
            what = "; ".join(f"{i['name']} {i['last']} {i['currency']} {i['change_pct']} % ({i['asof']})"
                             for i in w["items"]) + f" — {len(ctx.charts[-1]['rows'])} points"  # fmt: skip
            if w.get("missing"):
                what += f" — missing {w['missing']}"
            ok = True
        except Exception as e:  # a provider down (or a feed without a key) is a row, not a crash
            ok, what = False, f"{type(e).__name__}: {e}"[:200]
        ok_all &= ok or "Twelve" in name
        print(f"{'OK  ' if ok else 'FAIL'} {name:<16} {time.monotonic() - t0:5.2f}s  {what}")
    guard.fetch_bytes = real
    if a.record:
        from birds.web.demo_widgets import opendata_key

        old = json.loads(Path(a.record).read_text()) if Path(a.record).is_file() else {}
        old.update({opendata_key(u): v for u, v in seen.items()})
        Path(a.record).write_text(json.dumps(old, ensure_ascii=False, sort_keys=True, indent=0))
        print(f"recorded {len(seen)} answers in {a.record}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
