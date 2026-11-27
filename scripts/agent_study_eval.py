"""Live A/B: Mode Agent forced ("on") vs simple ("off") on study prompts, through the real server (SSE).

usage: .venv/bin/python -I scripts/agent_study_eval.py PORT OUTDIR [index...] [--arms on,off]
Writes OUTDIR/<i>-<arm>.json with the answer, the file's arguments, sources, usage and wall time.
"""

import json
import sys
import time
import urllib.request

PROMPTS = [
    "Fais une étude comparative des 3 principaux CRM du marché pour une PME avec un tableau et une recommandation",
    "Fais un dossier de veille sur l'IA générative en entreprise en 2026 : tendances, chiffres, risques",
    "Rédige un rapport sur la transition énergétique des PME françaises avec des chiffres récents et des sources",
    "Fais un benchmark des outils de visioconférence du marché pour une PME de 50 personnes",
]

port, out = sys.argv[1], sys.argv[2]
arms = ["on", "off"]
idx = []
for a in sys.argv[3:]:
    if a.startswith("--arms="):
        arms = a.split("=", 1)[1].split(",")
    else:
        idx.append(int(a))
idx = idx or list(range(len(PROMPTS)))
base = f"http://127.0.0.1:{port}"
for i in idx:
    for arm in arms:
        body = {"messages": [{"role": "user", "content": PROMPTS[i]}], "agent": arm, "lang": "fr"}
        req = urllib.request.Request(
            base + "/api/chat",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "x-bird-mode": "server"},
        )
        t0 = time.monotonic()
        events = []
        with urllib.request.urlopen(req, timeout=320) as r:
            buf = b""
            for chunk in iter(lambda: r.read(4096), b""):
                buf += chunk
                while b"\n\n" in buf:
                    frame, buf = buf.split(b"\n\n", 1)
                    line = frame.decode("utf-8", "replace")
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
        wall = round(time.monotonic() - t0, 1)
        files = [
            e
            for e in events
            if e.get("type") in ("step", "tool_start")
            and e.get("tool") in ("make_document", "make_slides", "draft_email")
        ]
        answer = next((e for e in events if e.get("type") == "answer"), {})
        usage = next((e for e in events if e.get("type") == "usage"), {})
        done = next((e for e in events if e.get("type") == "agent_done"), None)
        rec = {
            "prompt": PROMPTS[i],
            "arm": arm,
            "wall": wall,
            "answer": answer,
            "usage": usage,
            "agent_done": done,
            "file_args": [f.get("arguments") for f in files if f.get("arguments")],
            "tools": [
                (e.get("tool"), (e.get("arguments") or {}).get("query") or (e.get("arguments") or {}).get("url"))
                for e in events
                if e.get("type") == "step" and e.get("tool")
            ],
            "errors": [e for e in events if e.get("type") == "error"],
        }
        with open(f"{out}/{i}-{arm}.json", "w") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        print(
            i,
            arm,
            "wall",
            wall,
            "gens",
            usage.get("generations"),
            "crew_calls",
            usage.get("crew_calls"),
            "files",
            answer.get("files"),
            "sources",
            len(answer.get("sources") or []),
            "err",
            rec["errors"][:1],
            flush=True,
        )
