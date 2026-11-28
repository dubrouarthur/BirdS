"""A / B of the picture search on the same queries, at the same time (the two runs alternate query by query, so a
rate limit hits both alike): ``--old FILE`` is the previous birds/canvas/images.py (git show <rev>:…), with the
previous fetcher (no second try on 429, the bare image User-Agent); the new one is this checkout's.

    BIRD_PIN_DNS=0 .venv/bin/python scripts/image_ab.py --old /tmp/old_images.py --out docs/measures/x.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUERIES = ['city mobility', 'green bike delivery food', 'night train Europe', 'Bretagne mer et forêt', 'busy bees',
           'abeille pollinise fleur', 'growing community', 'French forest climate change', 'city streets bicycle',
           'a cyclist delivering a meal bag on a city street', 'night train europe history', 'breizh tourism',
           'Bretagne coastline', 'Saint-Malo Bretagne', 'team celebrating together', 'busy bees in a flower',
           'chart showing quarterly growth', 'French forest', 'honey bee pollination', 'bicycle courier city']  # fmt: skip


def main() -> int:
    import httpx

    from birds.canvas import images as new
    from birds.harness import guard
    from birds.harness import office_media as om
    from birds.harness.config import Config

    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--out", default="out/image_ab.json")
    ap.add_argument("--thumbs", default="", help="write each picture found, small, to be looked at")
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("old_images", args.old)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    pin = os.environ.get("BIRD_PIN_DNS", "1") != "0"
    cfg = Config(workspace=Path(tempfile.mkdtemp()), pin_dns=pin)

    def client():
        return httpx.Client(trust_env=False, follow_redirects=False) if pin else httpx.Client(follow_redirects=False)

    class OldFetcher(om.Fetcher):
        def user_agent(self, url):
            return guard.IMAGE_USER_AGENT

        def json(self, url, retry=0.0):
            return super().json(url, retry=0.0)

    judge = None
    if os.environ.get("BIRD_BASE_URL"):  # the new search with the model's look, as in the app
        from birds.harness.llm import CompletionsClient

        judge = new.vision_judge(CompletionsClient(os.environ["BIRD_BASE_URL"], os.environ.get("BIRD_MODEL", "")))
    rows = []
    for q in QUERIES:
        row = {"query": q}
        for name, mod, fetch in (("old", old, OldFetcher(client(), cfg)), ("new", new, om.Fetcher(client(), cfg))):
            mod.CACHE.clear()
            t0 = time.monotonic()
            if mod is new:
                m = mod.search_web(q, fetch, deadline=time.monotonic() + 12, judge=judge)
            else:
                m = mod.search_web(q, fetch, deadline=time.monotonic() + 12)
            if m is not None and args.thumbs:
                import io

                from PIL import Image

                Path(args.thumbs).mkdir(parents=True, exist_ok=True)
                im = Image.open(io.BytesIO(m.data)).convert("RGB")
                im.thumbnail((360, 240))
                im.save(Path(args.thumbs) / f"{QUERIES.index(q):02d}-{name}.jpg", "JPEG", quality=80)
            row[name] = {"found": m is not None, "seconds": round(time.monotonic() - t0, 1),
                         "title": m.title if m else "", "credit": m.credit if m else "",
                         "relevant": bool(m and new.relevant(q, m.title))}  # fmt: skip
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    tot = {k: {"found": sum(r[k]["found"] for r in rows), "relevant": sum(r[k]["relevant"] for r in rows),
               "seconds": round(sum(r[k]["seconds"] for r in rows), 1)} for k in ("old", "new")}  # fmt: skip
    print(json.dumps({"queries": len(rows), **tot}))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"rows": rows, "total": tot}, ensure_ascii=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
