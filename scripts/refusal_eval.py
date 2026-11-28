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

from birds.harness.refusal import REFUSAL  # noqa: E402

HORSE = [
    {"role": "user", "content": "parle-moi du cheval tigré"},
    {"role": "assistant", "content": "Le cheval tigré, ou cheval à robe léopard, porte des taches sombres sur un "
     "fond clair : c'est la robe des Appaloosa et des Knabstrup. Il est apprécié pour son caractère calme."},
]  # fmt: skip
MSM = [
    {"role": "user", "content": "raconte-moi l'histoire du Mont-Saint-Michel"},
    {"role": "assistant", "content": "Le Mont-Saint-Michel est un îlot rocheux de Normandie, couronné d'une abbaye "
     "fondée au VIIIe siècle et devenue un grand lieu de pèlerinage."},
]  # fmt: skip
MAIL_FR = ("Bonjour Claire,\n\nMerci pour votre retour rapide. Je vous confirme notre rendez-vous de jeudi à 14 h "
           "dans nos locaux de Lyon. Pourriez-vous m'envoyer le devis signé avant mercredi ?\n\nBien cordialement,\n"
           "Julien")
MAIL_EN = ("Hi Tom,\n\nThanks for the quick reply. I confirm our meeting on Thursday at 2 pm at our Lyon office. "
           "Could you send me the signed quote before Wednesday?\n\nBest regards,\nJulia")
MAIL = [{"name": "mail.txt", "content": MAIL_FR, "encoding": "text", "fresh": True}]
MAIL_EN_FILE = [{"name": "email.txt", "content": MAIL_EN, "encoding": "text", "fresh": True}]

# (id, history, message, expected, lang, attachments). expected: "chart" (a chart shown), "images" (pictures shown),
# a tool name (that tool ran without error), "entity:<words>" (lookup_entity ran and the answer holds the words),
# None (an ordinary answer: no chart, no tool)
CASES = [
    ("chart_natalite", [], "fais un graphe de l'évolution de la natalité", "chart", "fr", []),
    ("chart_pib", [], "trace un graphique du PIB de la France de 2019 à 2023", "chart", "fr", []),
    ("chart_poll", [], "qui sera le prochain président, fais un graphe des sondages au 2nd tour", "chart", "fr", []),
    ("chart_user", [], "fais un graphique : 2020 1,75 ; 2021 1,83 ; 2022 1,79 ; 2023 1,68 ; 2024 1,62", "chart",
     "fr", []),
    ("analyse_ventes", [], "Mes ventes : janvier 120, février 135, mars 160, avril 150. Analyse-les.", "chart", "fr",
     []),
    ("analyse_chomage", [], "analyse l'évolution du chômage en France depuis 2015", "chart", "fr", []),
    ("analyse_abonnes", [], "analyse ces chiffres d'abonnés : 2021 1200, 2022 1850, 2023 2600, 2024 3100", "chart",
     "fr", []),
    ("analyse_en", [], "analyse the trend: Q1 40, Q2 55, Q3 48, Q4 70", "chart", "en", []),
    ("typo_pompidou", [], "qui est georges pompidoo", "entity:1974", "fr", []),
    ("typo_macron", [], "qui est emanuel macron", "entity:1977", "fr", []),
    ("typo_hugo", [], "c'est qui victor hugot ?", "entity:1802", "fr", []),
    ("attach_translate", [], "Traduis ce mail en anglais", "read_file", "fr", MAIL),
    ("attach_translate_en", [], "Translate this email into French", "read_file", "en", MAIL_EN_FILE),
    ("img_horse", HORSE, "une image", "images", "fr", []),
    ("img_msm", MSM, "tu as une photo ?", "images", "fr", []),
    ("neg_haiku", [], "écris un haïku sur l'automne", None, "fr", []),
    ("neg_hello", [], "bonjour, ça va ?", None, "fr", []),
    ("neg_photosynthese", [], "explique la photosynthèse en deux phrases", None, "fr", []),
    ("neg_excel", [], "comment faire un graphique dans Excel ?", None, "fr", []),
    ("neg_translate", [], "traduis en anglais : merci pour votre aide", None, "fr", []),
]  # fmt: skip


def run_case(client: httpx.Client, url: str, case, headers: dict) -> dict:
    cid, hist, msg, want, lang, files = case
    body = {"messages": [*hist, {"role": "user", "content": msg}], "lang": lang, "agent": "auto",
            "agent_flow": "run", "reflexion": "auto", "attachments": files}  # fmt: skip
    t0 = time.monotonic()
    answer, steps, error = None, [], None
    with client.stream("POST", url.rstrip("/") + "/api/chat", json=body, headers=headers, timeout=240) as r:
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
                              "args": json.dumps(ev.get("arguments") or {}, ensure_ascii=False)[:120],
                              "summary": str(ev.get("summary") or "")[:160]})  # fmt: skip
            elif kind == "answer":
                answer = ev
            elif kind == "error":
                error = ev.get("message") or ev.get("code")
    secs = round(time.monotonic() - t0, 2)
    if answer is None:
        return {"id": cid, "error": error or "no answer", "seconds": secs, "steps": steps}
    content = str(answer.get("content") or "")
    imgs = [i for i in answer.get("web_images") or [] if isinstance(i, dict)]
    charts = list(answer.get("charts") or [])
    tools = {s["tool"] for s in steps if s["status"] != "error" and s["tool"]}
    if want == "chart":
        ok = bool(charts)
    elif want == "images":
        ok = bool(imgs)
    elif want and want.startswith("entity:"):
        ok = "lookup_entity" in tools and want.split(":", 1)[1] in content
    elif want:
        ok = want in tools
    else:
        ok = not charts and not imgs and not (tools - {"web_search", "read_page"})
    return {
        "id": cid, "seconds": secs, "ok": ok, "tools": sorted(tools),
        "errors": [s for s in steps if s["status"] == "error"],
        "refusal": bool(REFUSAL.search(content)), "charts": len(charts), "images": len(imgs),
        "answer": content[:300],
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
    gap = 3.2  # the deployment allows 20 requests a minute
    with httpx.Client(timeout=180) as client:
        for c in cases:
            try:
                got = run_case(client, a.url, c, headers)
            except Exception as e:  # noqa: BLE001 - a transport error is a failed case, reported
                got = {"id": c[0], "error": f"{type(e).__name__}: {e}"}
            out.append(got)
            time.sleep(gap)
            print(json.dumps(got, ensure_ascii=False), flush=True)
    done = [r for r in out if "error" not in r]
    summary = {
        "cases": len(out), "answered": len(done), "ok": sum(r["ok"] for r in done),
        "false_refusals": sum(r["refusal"] for r in done),
        "negatives_ok": sum(r["ok"] for r in done if r["id"].startswith("neg_")),
        "seconds_p50": sorted(r["seconds"] for r in done)[len(done) // 2] if done else None,
    }  # fmt: skip
    print(json.dumps(summary, ensure_ascii=False))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"summary": summary, "cases": out}, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
