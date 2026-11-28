"""Live evaluation of false refusals and asked images: 20 fixed prompts and short conversations on a running Bird.

Each case is one POST /api/chat on a Bird server (the production app, or ``scripts/serve.py`` on the live endpoint):
the history of a follow-up is written here (the user's words and a short assistant answer, with the memo the
server would have written), so every case costs one turn and only the turn under test varies.

    .venv/bin/python scripts/refusal_eval.py --url https://<app> --json docs/measures/refusal-eval-before.json
    .venv/bin/python scripts/refusal_eval.py --url http://127.0.0.1:8000 --only 'img_|fu_'

Scored per case: ``tool`` the expected tool ran (``images`` = a picture search whose pictures were shown),
``refusal`` the answer claims Bird has no access to the internet, to its tools or to recent data, or sends the
user elsewhere (``agent.NO_ACCESS``), ``licence`` every picture shown carries its licence and author, ``seconds``
wall time to the answer event, ``team_note`` a « Rien à répartir » line was sent without the team being asked.
Nothing is sent anywhere but ``--url``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from birds.harness.agent import NO_ACCESS  # noqa: E402

HORSE = [
    {"role": "user", "content": "parle-moi du cheval tigré"},
    {"role": "assistant", "content": "Le cheval tigré, ou cheval à robe léopard, porte des taches sombres sur un "
     "fond clair : c'est la robe des Appaloosa et des Knabstrup. Il est apprécié pour son caractère calme."},
]  # fmt: skip
EIFFEL_IMG = [
    {"role": "user", "content": "montre-moi une photo de la tour Eiffel"},
    {"role": "assistant", "content": "Voici la tour Eiffel, construite pour l'Exposition universelle de 1889.",
     "memo": "[Mémo de ce tour — outils : web_search « tour Eiffel » | contexte : images {\"subject\": \"tour "
             "Eiffel\"}]"},
]  # fmt: skip
LEOPARD_IMG = [
    {"role": "user", "content": "image of a snow leopard"},
    {"role": "assistant", "content": "Here is the snow leopard, a big cat of the mountains of Central Asia.",
     "memo": "[Memo of this turn — tools: web_search « snow leopard » | context : images {\"subject\": \"snow "
             "leopard\"}]"},
]  # fmt: skip
MSM = [
    {"role": "user", "content": "raconte-moi l'histoire du Mont-Saint-Michel"},
    {"role": "assistant", "content": "Le Mont-Saint-Michel est un îlot rocheux de Normandie, couronné d'une abbaye "
     "fondée au VIIIe siècle et devenue un grand lieu de pèlerinage."},
]  # fmt: skip
PYTHON = [
    {"role": "user", "content": "c'est quoi Python ?"},
    {"role": "assistant", "content": "Python est un langage de programmation généraliste, lisible et très utilisé "
     "en science des données et en automatisation."},
]  # fmt: skip

# (id, history, message, expected tool or None, lang, agent mode)
CASES = [
    ("img_eiffel", [], "montre-moi une photo de la tour Eiffel", "images", "fr", "auto"),
    ("img_horse", [], "une image d'un cheval tigré", "images", "fr", "auto"),
    ("img_leopard_en", [], "image of a snow leopard", "images", "en", "auto"),
    ("img_looks_msm", [], "à quoi ressemble le Mont-Saint-Michel ?", "images", "fr", "auto"),
    ("fu_horse_image", HORSE, "une image", "images", "fr", "auto"),
    ("fu_horse_image_team", HORSE, "une image", "images", "fr", "on"),
    ("fu_horse_show", HORSE, "montre-moi à quoi il ressemble", "images", "fr", "auto"),
    ("fu_msm_photo", MSM, "tu as une photo ?", "images", "fr", "auto"),
    ("fu_eiffel_another", EIFFEL_IMG, "une autre", "images", "fr", "auto"),
    ("fu_eiffel_bigger", EIFFEL_IMG, "en plus grand", "images", "fr", "auto"),
    ("fu_leopard_more_en", LEOPARD_IMG, "another one", "images", "en", "auto"),
    ("fu_eiffel_night", EIFFEL_IMG, "et de nuit ?", "images", "fr", "auto"),
    ("web_lvmh", [], "cours de l'action LVMH aujourd'hui", "web_search", "fr", "auto"),
    ("web_news", [], "quelles sont les dernières actualités sur la réforme des retraites ?", "web_search", "fr",
     "auto"),
    ("web_ucl_en", [], "who won the last Champions League final?", "web_search", "en", "auto"),
    ("fu_python_new", PYTHON, "et quoi de neuf dans la dernière version ?", "web_search", "fr", "auto"),
    ("web_loyer", [], "cherche sur internet le loyer moyen à Bordeaux", "web_search", "fr", "auto"),
    ("wx_lyon", [], "quel temps fera-t-il à Lyon demain ?", "get_weather", "fr", "auto"),
    ("fx_usd", [], "combien valent 100 dollars en euros ?", "convert_currency", "fr", "auto"),
    ("ctrl_haiku", [], "écris un haïku sur l'automne", None, "fr", "auto"),
]  # fmt: skip


def run_case(client: httpx.Client, url: str, case, headers: dict) -> dict:
    cid, hist, msg, want, lang, agent = case
    body = {"messages": [*hist, {"role": "user", "content": msg}], "lang": lang, "agent": agent,
            "agent_flow": "run", "reflexion": "auto"}  # fmt: skip
    t0 = time.monotonic()
    answer, steps, team_note, error = None, [], None, None
    with client.stream("POST", url.rstrip("/") + "/api/chat", json=body, headers=headers, timeout=180) as r:
        if r.status_code != 200:
            return {"id": cid, "error": f"HTTP {r.status_code}: {r.read()[:200]!r}"}
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "step" and ev.get("status") in ("ok", "done", "error"):
                steps.append({"tool": ev.get("tool"), "status": ev.get("status"),
                              "query": (ev.get("arguments") or {}).get("query")})  # fmt: skip
            elif kind == "agent_done" and ev.get("reason") == "no_deliverable":
                team_note = ev.get("message")
            elif kind == "answer":
                answer = ev
            elif kind == "error":
                error = ev.get("message") or ev.get("code")
    secs = round(time.monotonic() - t0, 2)
    if answer is None:
        return {"id": cid, "error": error or "no answer", "seconds": secs, "steps": steps}
    content = str(answer.get("content") or "")
    imgs = [i for i in answer.get("web_images") or [] if isinstance(i, dict)]
    tools = {s["tool"] for s in steps if s["status"] != "error"}
    if want == "images":
        ok = bool(imgs)
    elif want:
        ok = want in tools
    else:
        ok = not tools
    return {
        "id": cid, "seconds": secs, "tool_ok": ok, "tools": sorted(t for t in tools if t),
        "refusal": bool(NO_ACCESS.search(content)), "images": len(imgs),
        "licence": bool(imgs) and all(i.get("licence") and i.get("author") for i in imgs),
        "team_note": team_note if agent != "on" else None, "team_note_forced": team_note if agent == "on" else None,
        "answer": content[:400],
    }  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="the Bird app (origin), e.g. http://127.0.0.1:8000")
    ap.add_argument("--only", default="", help="regex on case ids")
    ap.add_argument("--json", default="")
    ap.add_argument("--access", default="", help="access code of the deployment, if any")
    a = ap.parse_args()
    host = re.sub(r"^https?://", "", a.url.rstrip("/"))
    headers = {"Origin": a.url.rstrip("/"), "Host": host, "Accept": "text/event-stream"}
    if a.access:
        headers["x-bird-access"] = a.access
    cases = [c for c in CASES if not a.only or re.search(a.only, c[0])]
    out = []
    with httpx.Client(timeout=180) as client:
        for c in cases:
            try:
                got = run_case(client, a.url, c, headers)
            except Exception as e:  # noqa: BLE001 - a transport error is a failed case, reported
                got = {"id": c[0], "error": f"{type(e).__name__}: {e}"}
            out.append(got)
            print(json.dumps(got, ensure_ascii=False), flush=True)
    done = [r for r in out if "error" not in r]
    n = max(1, len(done))
    summary = {
        "cases": len(out), "answered": len(done),
        "tool_ok": sum(r["tool_ok"] for r in done),
        "false_refusals": sum(r["refusal"] for r in done),
        "image_cases": sum(1 for c in cases if c[3] == "images"),
        "images_shown": sum(1 for r in done if r["images"]),
        "images_with_licence": sum(1 for r in done if r["licence"]),
        "team_note_unasked": sum(1 for r in done if r.get("team_note")),
        "seconds_mean": round(sum(r["seconds"] for r in done) / n, 2),
        "seconds_p50": sorted(r["seconds"] for r in done)[len(done) // 2] if done else None,
    }  # fmt: skip
    print(json.dumps(summary, ensure_ascii=False))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"summary": summary, "cases": out}, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
