"""Live measurement of local practical asks (« supermarchés à Saint-Cloud »): 12 fixed prompts through serve.py and
the real endpoint. Per prompt: the tool chosen and its arguments, the places shown and their distance to the anchor,
whether the answer names a place the tool returned, duplicate cards, forbidden phrasings, the time.

  .venv/bin/python scripts/serve.py --base-url https://….endpoints.huggingface.cloud --model … --searxng … &
  .venv/bin/python scripts/local_live.py --base http://127.0.0.1:8011 OUT.json [--only 0,3] [--reflexion albatros]

One chat turn per prompt. Results are written as JSON; docs/HARNESS.md holds the table.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
import urllib.request

PROMPTS = [
    "comment aller faire ses courses a saint cloud quels sont les supermarchés",
    "pharmacie de garde à Lyon 3e",
    "boulangerie près de la gare de Rennes",
    "parking près de l'hôpital de Nantes",
    "restaurants végétariens à Bordeaux centre",
    "distributeur près de la Défense",
    "où trouver une station-service à Annecy ?",
    "bureau de poste à Vannes",
    "quels supermarchés à Montreuil ?",
    "une banque à Saint-Malo",
    "écoles à Versailles",
    "gare la plus proche de Chantilly",
]
RADIUS_M = 6000  # a place this far from the anchor is not « near » it
# the answer must never give up when the tool found places, nor send the user elsewhere
FORBIDDEN = re.compile(
    r"je n'ai pas trouv|aucune information fiable|demandez à un voisin|demander à un voisin|vérifiez sur une carte|"
    r"je ne peux pas|je ne suis pas en mesure",
    re.I,
)


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def dist(a, b) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def post(base: str, body: dict) -> list[dict]:
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-bird-mode": "server"})  # fmt: skip
    events, buf = [], b""
    with urllib.request.urlopen(req, timeout=320) as r:
        for chunk in iter(lambda: r.read(4096), b""):
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                line = frame.decode("utf-8", "replace")
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except ValueError:
                        pass
    return events


def score(prompt: str, events: list[dict], seconds: float) -> dict:
    steps = [e for e in events if e.get("type") == "step" and e.get("status") != "running"]
    answer = next((e for e in reversed(events) if e.get("type") == "answer"), {}) or {}
    text = str(answer.get("content") or "")
    widgets = [w for w in answer.get("widgets") or [] if isinstance(w, dict)]
    places = [w for w in widgets if w.get("type") == "places"]
    keys = [json.dumps({k: v for k, v in w.items() if k not in ("map", "auto")}, sort_keys=True) for w in places]
    shown = [p for w in places for p in w.get("places") or []]
    far = []
    for w in places:
        c = w.get("center")
        if c and w.get("mode") in ("near", "route"):
            far += [p for p in w.get("places") or [] if dist((c["lat"], c["lon"]), (p["lat"], p["lon"])) > RADIUS_M]
    named = [p["name"] for p in shown if p.get("name") and fold(p["name"]) in fold(text)]
    crew = [e for e in events if e.get("type") in ("agent_plan", "agent_start", "agent_done")]
    return {
        "prompt": prompt,
        "tools": [(s.get("tool"), s.get("arguments")) for s in steps],
        "statuses": [(s.get("tool"), s.get("status"), (s.get("summary") or "")[:80]) for s in steps],
        "modes": [w.get("mode") for w in places],
        "titles": [w.get("title") or w.get("query") for w in places],
        "n_places": len(shown),
        "far": len(far),
        "duplicates": len(keys) - len(set(keys)),
        "named": len(named),
        "uses_results": bool(named) if shown else None,
        "forbidden": bool(FORBIDDEN.search(text)),
        "crew": [e.get("type") + ":" + str(e.get("recipe") or e.get("reason") or "") for e in crew],
        "forced": any(e.get("forced") for e in crew),
        "chips": answer.get("followups") or answer.get("suggestions") or [],
        "seconds": round(seconds, 1),
        "answer": text[:900],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out")
    p.add_argument("--base", default="http://127.0.0.1:8011")
    p.add_argument("--only", default="")
    p.add_argument("--reflexion", default="auto")
    p.add_argument("--agent", default="auto")
    p.add_argument("--plan-only", action="store_true", help="a team's plan card is not launched (the decision only)")
    p.add_argument("--prompt", default="", help="one prompt of your own instead of the fixed set")
    a = p.parse_args(argv)
    if a.prompt:
        PROMPTS[:] = [a.prompt]
    idx = [int(x) for x in a.only.split(",") if x.strip()] or list(range(len(PROMPTS)))
    rows = []
    for i in idx:
        body = {"messages": [{"role": "user", "content": PROMPTS[i]}], "lang": "fr", "agent": a.agent,
                "reflexion": a.reflexion, "agent_flow": "plan", "tz": "Europe/Paris"}  # fmt: skip
        t0 = time.monotonic()
        try:
            events = post(a.base, body)
            plan = next((e for e in events if e.get("type") == "agent_plan"), None)
            if plan is not None and not a.plan_only:  # the app launches the plan card (« Lancer », or its countdown)
                events += post(a.base, {**body, "agent_plan": {"token": plan["token"], "edits": {}}})
            row = score(PROMPTS[i], events, time.monotonic() - t0)
        except Exception as e:  # noqa: BLE001 - recorded, the next prompt goes on
            row = {"prompt": PROMPTS[i], "error": f"{type(e).__name__}: {e}"}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False)[:600], flush=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    ok = [r for r in rows if "error" not in r]
    print(
        json.dumps(
            {
                "n": len(rows),
                "find_places": sum(any(t == "find_places" for t, _ in r["tools"]) for r in ok),
                "places_shown": sum(r["n_places"] > 0 for r in ok),
                "far": sum(r["far"] for r in ok),
                "duplicates": sum(r["duplicates"] for r in ok),
                "uses_results": sum(bool(r["uses_results"]) for r in ok),
                "forbidden": sum(r["forbidden"] for r in ok),
                "crew": sum(bool(r["crew"]) for r in ok),
                "median_s": sorted(r["seconds"] for r in ok)[len(ok) // 2] if ok else None,
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
