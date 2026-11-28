"""Live evaluation of answer content (chat audit, cluster C2): date facts, a line-count instruction, runnable code,
LaTeX math the chat can typeset, and sourced answers with inline citations [n].

    BIRD_BASE_URL=https://… BIRD_API_KEY=… BIRD_RATE_LIMIT=0 .venv/bin/python scripts/serve.py --from-env --port 8021 &
    .venv/bin/python scripts/answer_eval.py --server http://127.0.0.1:8021 --label before --out out/answer_eval.json

Talks to a running Bird server (the same web stack as the app: harness, tidy, citations) with one request per case,
French, a fresh conversation each time. Every score is computed from the answer event, never judged by eye:

- ``dates``: each event the answer names carries its true date (Bastille 14 juillet 1789, …); wrong dates counted.
- ``poem8``: « un poème de 8 vers » has exactly 8 verse lines (title and blank lines not counted).
- ``code``: the Python block parses and runs to the end (subprocess, isolated, 10 s, no network use expected).
- ``math``: every TeX command in the answer sits inside a delimiter the chat typesets (markdown.js, run with Node).
- ``cite_*``: the sources returned, the inline citations [n] that point to one of them, the share of sentences cited.

Each case is one generation of the live budget. ``--only`` narrows to some case ids.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

CASES = [
    {"id": "dates", "ask": "Raconte l'histoire de la Révolution française en 6 dates clés."},
    {"id": "poem8", "ask": "Écris un poème de 8 vers sur la mer."},
    {
        "id": "code",
        "ask": "Écris une fonction Python qui transforme « 14 juillet 1789 » en objet date, sans dépendre de la "
        "locale du système, avec un exemple d'utilisation.",
    },
    {"id": "math", "ask": "Explique la photosynthèse étape par étape, avec l'équation chimique globale."},
    {
        "id": "cite_news",
        "ask": "Quelles sont les dernières nouvelles sur la mission Artemis II de la NASA ? Cite tes sources.",
    },
    {"id": "cite_def", "ask": "Qu'est-ce que la directive européenne CSRD ? Donne tes sources."},
]

# (what the answer names, its true date written the French way, the month and year a wrong day would carry)
FACTS = [
    (r"Bastille", r"14 juillet 1789", "juillet 1789"),
    (r"Déclaration des droits de l['’]homme", r"26 août 1789", "août 1789"),
    (r"abolition des privilèges|nuit du 4 août", r"4 août 1789", "août 1789"),
    (r"exécution de Louis XVI|Louis XVI (?:est )?(?:guillotiné|exécuté)", r"21 janvier 1793", "janvier 1793"),
    (r"(?:chute|exécution|mort) de Robespierre|Thermidor", r"2[78] juillet 1794|9 thermidor", "juillet 1794"),
    (r"abolition de la monarchie|proclamation de la République|Première République", r"2[12] septembre 1792",
     "septembre 1792"),
    (r"18 [Bb]rumaire", r"9 novembre 1799|18 brumaire", "novembre 1799"),
]  # fmt: skip


def chat(client: httpx.Client, server: str, ask: str) -> dict:
    t0 = time.monotonic()
    r = client.post(f"{server}/api/chat", json={"messages": [{"role": "user", "content": ask}], "lang": "fr"})
    events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
    answer = next((e for e in events if e.get("type") == "answer"), {})
    steps = [e.get("tool") for e in events if e.get("type") == "step" and e.get("status") != "running"]
    return {"seconds": round(time.monotonic() - t0, 1), "answer": answer, "steps": steps, "status": r.status_code}


def score_dates(text: str) -> dict:
    """Each named event with its true date nearby (the same line, else 120 characters around); another day of the
    same month and year nearby is a wrong date."""
    named, right, wrong = 0, 0, []
    for name, true, month_year in FACTS:
        m = re.search(name, text, re.I)
        if not m:
            continue
        named += 1
        line = text[text.rfind("\n", 0, m.start()) + 1 : (text.find("\n", m.end()) + 1 or len(text) + 1) - 1]
        around = line if re.search(r"\d{4}", line) else text[max(0, m.start() - 120) : m.end() + 120]
        bad = re.search(rf"\b\d{{1,2}}(?:er)? {month_year}", around)
        if re.search(true, around, re.I):
            right += 1
        elif bad:
            wrong.append(f"{m.group(0)}: {bad.group(0)}")
    if re.search(r"\bDirectory\b", text):
        wrong.append("Directory")
    return {"named": named, "right": right, "wrong": wrong, "ok": not wrong and named >= 3}


def score_poem(text: str, want: int = 8) -> dict:
    lines = [x.strip() for x in text.split("\n")]
    verses = [
        x
        for x in lines
        if x
        and not x.startswith(("#", "```", "---"))
        and not re.fullmatch(r"\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_", x)  # a title alone on its line
        and not re.match(r"(?:Voici|Voilà|J['’]espère|N['’]hésitez)\b", x)
    ]
    return {"verses": len(verses), "ok": len(verses) == want}


def score_code(text: str) -> dict:
    blocks = re.findall(r"```(?:python|py)\s*\n(.*?)```", text, re.S)
    if not blocks:
        return {"blocks": 0, "parses": False, "runs": False, "ok": False}
    code = "\n\n".join(blocks)
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return {"blocks": len(blocks), "parses": False, "runs": False, "error": str(exc)[:120], "ok": False}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "answer.py"
        path.write_text(code)
        try:
            run = subprocess.run([sys.executable, "-I", str(path)], cwd=tmp, capture_output=True, text=True,
                                 timeout=10, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})  # fmt: skip
            runs, err = run.returncode == 0, run.stderr.strip().splitlines()[-1:] if run.returncode else []
        except subprocess.TimeoutExpired:
            runs, err = False, ["timeout"]
    return {"blocks": len(blocks), "parses": True, "runs": runs, "error": (err or [""])[0][:160], "ok": runs}


def score_math(text: str) -> dict:
    """TeX commands outside the delimiters markdown.js typesets (\\[…\\], \\(…\\), $$…$$, $…$ with TeX inside)."""
    js = (
        "import('" + (ROOT / "birds/web/static/markdown.js").as_uri() + "').then(m => {"
        "const html = m.renderMarkdown(process.argv[1], {rich: true, final: true});"
        'const math = (html.match(/class="md-math/g) || []).length;'
        "const rest = html.replace(/<(span|div) class=\"md-math[\\s\\S]*?<\\/\\1>/g, '');"
        "const raw = (rest.match(/\\\\(?:frac|text|rightarrow|xrightarrow|cdot|times|sqrt|mathrm|left|right)\\b/g) || []).length;"
        "console.log(JSON.stringify({math, raw}));})"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", js, text], capture_output=True, text=True, timeout=30)
    got = json.loads(out.stdout or '{"math": 0, "raw": -1}')
    tex = len(re.findall(r"\\[a-zA-Z]+|_\{|\^\{", text))
    return {"tex_commands": tex, "typeset": got["math"], "raw_left": got["raw"], "ok": got["raw"] == 0}


def score_cites(answer: dict) -> dict:
    text = str(answer.get("content") or "")
    ns = {int(s.get("n")) for s in answer.get("sources") or [] if str(s.get("n", "")).isdigit()}
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body)) if len(s) > 30]
    cited = [s for s in sentences if any(int(n) in ns for n in re.findall(r"\[(\d{1,2})\]", s))]
    marks = [int(n) for n in re.findall(r"\[(\d{1,2})\]", text)]
    return {"sources": len(ns), "citations": sum(n in ns for n in marks), "dangling": sum(n not in ns for n in marks),
            "sentences": len(sentences), "cited_sentences": len(cited),
            "ok": bool(ns) and bool(cited) and not any(n not in ns for n in marks)}  # fmt: skip


SCORERS = {
    "dates": lambda answer: score_dates(str(answer.get("content") or "")),
    "poem8": lambda answer: score_poem(str(answer.get("content") or "")),
    "code": lambda answer: score_code(str(answer.get("content") or "")),
    "math": lambda answer: score_math(str(answer.get("content") or "")),
    "cite": score_cites,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="a running Bird server, e.g. http://127.0.0.1:8021")
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    only = {x for x in a.only.split(",") if x}
    rows = []
    with httpx.Client(timeout=300) as client:
        for case in CASES:
            if only and case["id"] not in only:
                continue
            got = chat(client, a.server.rstrip("/"), case["ask"])
            text = str(got["answer"].get("content") or "")
            score = SCORERS[case["id"].split("_")[0]](got["answer"])
            row = {"label": a.label, "id": case["id"], "seconds": got["seconds"], "steps": got["steps"], **score,
                   "excerpt": text[:400]}  # fmt: skip
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "excerpt"}, ensure_ascii=False), flush=True)
    ok = sum(r["ok"] for r in rows)
    print(f"{a.label}: {ok}/{len(rows)} ok")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
