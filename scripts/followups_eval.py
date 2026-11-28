"""Follow-up chips, before / after, on real answers of the live endpoint (docs/HARNESS.md § 18).

  # 1. record: each prompt of PROMPTS through the real app (HarnessBackend, live endpoint), one turn each; the
  #    answer event and Bird's next steps (nextsteps.generate, raw output kept before validation) are saved
  BIRD_BASE_URL=https://….endpoints.huggingface.cloud/v1 BIRD_API_KEY=… BIRD_SEARXNG_URL=https://… \\
    .venv/bin/python scripts/followups_eval.py --record docs/measures/followups-2026-11-28.json --max-gens 60
  # 2. score: the old chips (followups.js of the base commit: widget chips + clarifyOptions, run in node) against
  #    the new suggestions, on the written rubric below; prints the table of docs/HARNESS.md
  .venv/bin/python scripts/followups_eval.py --score docs/measures/followups-2026-11-28.json [--base 941cfc9]

Rubric (one point per criterion and per chip; a turn with no chip is scored on « silence » instead):
  voix      in the user's voice: a request the user would type, not Bird's question or a fragment of it
  grammaire a whole, grammatical phrase (judged by hand: the ``manual`` field of the record file)
  précis    specific to this answer: names a subject, a name or a figure of the request or the answer
  faisable  actionable here: Bird can do it on this deployment (no « envoie », no tool that is off)
  existe    the capability offered exists (a tool named is on)
  silence   a greeting or thanks gets no chip
The API key is read from the environment and never printed. At most ``--max-gens`` live generations in all.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (id, family, prompt): varied office requests; « ask » ones tend to make Bird ask back
PROMPTS = [
    ("mail_move", "mail", "Rédige un mail à mon équipe pour annoncer le déménagement du bureau le 15 janvier"),
    ("mail_quote", "mail", "Écris un mail de relance pour un devis envoyé il y a deux semaines à la société Martin"),
    ("mail_en", "mail", "Draft an email to a client to postpone our Thursday meeting to next week"),
    ("mail_reply", "mail", "Réponds à ce mail : « Bonjour, pouvez-vous nous envoyer votre catalogue 2027 ? Merci, "
     "Julie »"),
    ("deck_remote", "deck", "Fais une présentation de 4 diapositives sur le télétravail dans les PME"),
    ("deck_training", "deck", "Prépare une diapo sur notre offre de formation continue"),
    ("deck_en", "deck", "Make a 3-slide deck introducing our new expense policy"),
    ("doc_4days", "doc", "Rédige une note de synthèse sur la semaine de quatre jours"),
    ("doc_job", "doc", "Écris une fiche de poste pour un chargé de communication"),
    ("doc_minutes", "doc", "Fais un compte rendu de réunion : budget validé, recrutement reporté, prochain point le 12"),
    ("res_aiact", "research", "Quelles sont les obligations de l'AI Act pour une PME ?"),
    ("res_heatpump", "research", "Fais le point sur le marché des pompes à chaleur en France"),
    ("res_en", "research", "What are the main benefits of a four-day week?"),
    ("wx_lyon", "weather", "Quel temps fera-t-il à Lyon demain ?"),
    ("wx_bdx", "weather", "météo à Bordeaux ce week-end"),
    ("map_resto", "map", "Trouve des restaurants près de la gare Montparnasse"),
    ("map_orsay", "map", "Où est le musée d'Orsay ?"),
    ("data_sales", "data", "Voici nos ventes : janvier 120, février 135, mars 160, avril 150. Analyse la tendance."),
    ("data_loan", "data", "Calcule la mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %"),
    ("data_offers", "data", "Compare ces deux offres : A à 1 200 € par an, B à 110 € par mois. Laquelle choisir ?"),
    ("ask_review", "ask", "Aide-moi à préparer mon entretien annuel"),
    ("ask_doc", "ask", "J'ai besoin d'un document pour présenter notre projet"),
    ("ask_en", "ask", "Can you help me plan a team offsite?"),
    ("talk_hello", "talk", "Bonjour !"),
    ("talk_thanks", "talk", "Merci, c'est parfait"),
]  # fmt: skip


# ---------------------------------------------------------------- 1. record (live)


def record(out: Path, max_gens: int, only: set[str] | None) -> None:
    from fastapi.testclient import TestClient

    from birds.harness import llm as L
    from birds.harness import nextsteps as N
    from birds.web.server import create_app
    from birds.web.settings import Settings

    if not os.environ.get("BIRD_BASE_URL"):
        sys.exit("BIRD_BASE_URL is required (the key comes from BIRD_API_KEY, never the command line)")
    gens = {"n": 0}
    real_generate, real_chat = L.CompletionsClient.generate, L.CompletionsClient.chat

    def counted(self, *a, **kw):
        gens["n"] += 1
        return real_generate(self, *a, **kw)

    def counted_chat(self, *a, **kw):
        gens["n"] += 1
        return real_chat(self, *a, **kw)

    L.CompletionsClient.generate, L.CompletionsClient.chat = counted, counted_chat
    raw: list = []
    real_validate, real_gen = N.validate, N.generate

    def keep_raw(obj, **kw):
        raw.append(obj)
        return real_validate(obj, **kw)

    timing: list = []

    def timed(*a, **kw):
        got = real_gen(*a, **kw)
        timing.append(got)
        return got

    N.validate, N.generate = keep_raw, timed
    rows = json.loads(out.read_text()) if out.exists() else []
    done = {r["id"] for r in rows}
    app = create_app(Settings.from_env())
    with TestClient(app) as client:
        for pid, family, prompt in PROMPTS:
            if pid in done or (only and pid not in only):
                continue
            if gens["n"] >= max_gens - 3:
                print(f"stop: {gens['n']} generations used", file=sys.stderr)
                break
            raw.clear()
            timing.clear()
            before, t0 = gens["n"], time.monotonic()
            lang = "en" if pid.endswith("_en") else "fr"
            body = {"messages": [{"role": "user", "content": prompt}], "lang": lang, "reflexion": "colibri",
                    "agent": "off"}
            r = client.post("/api/chat", json=body, headers={"X-Bird-Mode": "server"})
            events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
            answer = next((e for e in events if e["type"] == "answer"), None)
            sug = next((e for e in events if e["type"] == "suggestions"), None)
            err = next((e for e in events if e["type"] == "error"), None)
            keep = {k: answer.get(k) for k in ("content", "draft_email", "widgets", "charts", "canvas", "files",
                                               "stop_reason")} if answer else None  # fmt: skip
            if keep and keep.get("widgets"):  # the chips read only the widget types and a few fields
                keep["widgets"] = [{k: w.get(k) for k in ("type", "day", "places", "from", "to", "amount", "topic",
                                                          "kind", "inputs", "nodes", "edges") if k in w}
                                   for w in keep["widgets"]]  # fmt: skip
            row = {"id": pid, "family": family, "lang": lang, "prompt": prompt, "answer": keep,
                   "error": err and err.get("code"), "suggestions": (sug or {}).get("items"),
                   "raw": raw[-1] if raw else None, "next_seconds": timing[-1]["seconds"] if timing else None,
                   "next_why": timing[-1].get("why") if timing else None,
                   "next_dropped": timing[-1].get("dropped") if timing else None,
                   "gens": gens["n"] - before, "wall": round(time.monotonic() - t0, 2)}  # fmt: skip
            rows.append(row)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
            print(f"{pid}: gens {row['gens']} (total {gens['n']}), next {row['next_seconds']}s, "
                  f"{len(row['suggestions'] or [])} chips, err {row['error']}", file=sys.stderr)  # fmt: skip
    print(json.dumps({"rows": len(rows), "generations": gens["n"]}))


# ---------------------------------------------------------------- 1b. replay (live, one generation per row)


def replay(src: Path, out: Path, only: set[str] | None) -> None:
    """The next-steps call alone on the SAME recorded answers (request + answer of ``src``), with today's prompt:
    one generation per row, so a prompt change is measured on a fixed set. Raw output and validation are kept."""
    from birds.harness import catalog
    from birds.harness import nextsteps as N
    from birds.harness.llm import CompletionsClient
    from birds.harness.template import TemplateTokenizer

    if not os.environ.get("BIRD_BASE_URL"):
        sys.exit("BIRD_BASE_URL is required (the key comes from BIRD_API_KEY, never the command line)")
    llm = CompletionsClient(os.environ["BIRD_BASE_URL"], os.environ.get("BIRD_MODEL", "adubrou/Bird-S-4B"),
                            os.environ.get("BIRD_API_KEY"))  # fmt: skip
    names = {m.name for m in catalog.MODULES if m.available}
    tools = names | {"web_search", "read_page", "draft_email"}
    raw: list = []
    real_validate = N.validate

    def keep_raw(obj, **kw):
        raw.append(obj)
        return real_validate(obj, **kw)

    N.validate = keep_raw
    rows = []
    for r in json.loads(src.read_text()):
        if only and r["id"] not in only or not (r.get("answer") or {}).get("content"):
            continue
        raw.clear()
        got = N.generate(llm, TemplateTokenizer(), r["prompt"], r["answer"]["content"], lang=r["lang"], names=names,
                         tools=tools, budget=30)  # fmt: skip
        rows.append({k: r[k] for k in ("id", "family", "lang", "prompt", "answer")} | {
            "suggestions": got["items"], "raw": raw[-1] if raw else None, "next_seconds": got["seconds"],
            "next_why": got.get("why"), "next_dropped": got.get("dropped"), "usage": got.get("usage")})  # fmt: skip
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"{r['id']}: {got['seconds']}s {[x['label'] for x in got['items']]} dropped {got.get('dropped')}",
              file=sys.stderr)  # fmt: skip
    N.validate = real_validate


# ---------------------------------------------------------------- 2. score


def old_chips(rows: list[dict], base: str) -> dict[str, list[dict]]:
    """The chips the base commit showed: its followups.js (clarifyOptions first, else the widget chips), in node."""
    tmp = Path(tempfile.mkdtemp(prefix="bird-old-chips-"))
    try:
        static = tmp / "static"
        shutil.copytree(ROOT / "birds/web/static", static)
        old = subprocess.run(["git", "show", f"{base}:birds/web/static/followups.js"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout  # fmt: skip
        (static / "followups_old.js").write_text(old)
        (tmp / "rows.json").write_text(json.dumps(rows, ensure_ascii=False))
        (tmp / "run.mjs").write_text(
            'import fs from "node:fs";\n'
            'import { state } from "./static/core.js";\n'
            'import { clarifyOptions, suggestions } from "./static/followups_old.js";\n'
            'const rows = JSON.parse(fs.readFileSync(new URL("./rows.json", import.meta.url)));\n'
            "const out = {};\n"
            "for (const r of rows) {\n"
            "  state.prefs.lang = r.lang;\n"
            "  if (!r.answer) { out[r.id] = []; continue; }\n"
            "  const c = clarifyOptions(r.answer.content);\n"
            '  out[r.id] = c.length ? c.map((x) => ({ label: x, prompt: x, kind: "clarify" })) : suggestions(r.answer);\n'
            "}\n"
            "console.log(JSON.stringify(out));\n"
        )
        got = subprocess.run(["node", str(tmp / "run.mjs")], check=True, capture_output=True, text=True)
        return json.loads(got.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_STOP = set("""avec dans pour sans sur sous chez entre cette votre notre leurs vous nous elle elles ils mais plus
moins tres tout tous toute toutes faire fais peux peut veux voulez souhaitez quel quelle quels quelles comment
about with from into your their this that these those what which would could should make write draft give more
less some very then than also réponse demande version""".split())  # fmt: skip


def _words(text: str) -> set[str]:
    from birds.harness.nextsteps import fold

    return {w for w in fold(text).split() if len(w) >= 5 and w not in _STOP}


def score_chip(chip: dict, row: dict, tools: set[str]) -> dict:
    from birds.harness import nextsteps as N

    both = f"{chip['label']} {chip['prompt']}"
    ctx = _words(row["prompt"] + " " + ((row.get("answer") or {}).get("content") or ""))
    voice = not (N._BIRD_VOICE.search(chip["label"]) or N._BIRD_VOICE.search(chip["prompt"]))
    exists = not any(p.search(both) and need not in tools for p, need in N._NEEDS)
    doable = exists and not N._CANT_DO.search(both)
    return {"voix": voice, "précis": bool(_words(both) & ctx), "faisable": doable, "existe": exists}


def score(path: Path, base: str, tools: set[str]) -> dict:
    rows = json.loads(path.read_text())
    old = old_chips(rows, base)
    arms = {"avant": {}, "après (brut)": {}, "après": {}}
    for r in rows:
        arms["avant"][r["id"]] = old.get(r["id"], [])
        rawlist = (r.get("raw") or {}).get("suggestions") if isinstance(r.get("raw"), dict) else None
        arms["après (brut)"][r["id"]] = [
            {"label": str(x.get("label", "")), "prompt": str(x.get("prompt", ""))}
            for x in (rawlist or []) if isinstance(x, dict)
        ]  # fmt: skip
        # the validation of today's code on the raw output (the record keeps what the run itself showed)
        from birds.harness import nextsteps as N

        arms["après"][r["id"]] = N.validate(r.get("raw") or {}, lang=r["lang"], available=tools)[0]
    # the hand judgement, read chip by chip: {"<arm>|<id>|<label>": {"grammaire": bool, "faisable": bool}}; a
    # chip of the « après » arm not listed was not read (it counts in « jugées » only when listed)
    manual = {k: v for r in rows for k, v in (r.get("manual") or {}).items()}
    table = {}
    for arm, by in arms.items():
        crit = {"voix": 0, "grammaire": 0, "précis": 0, "faisable": 0, "existe": 0}
        n = judged = 0
        talk_ok = talk = turns_with = 0
        for r in rows:
            chips = by.get(r["id"], [])
            if r["family"] == "talk":
                talk += 1
                talk_ok += not chips
                continue
            turns_with += bool(chips)
            for c in chips:
                s = score_chip(c, r, tools)
                n += 1
                for k, v in s.items():
                    crit[k] += v
                g = manual.get(f"{arm}|{r['id']}|{c['label']}")
                if g is not None:
                    judged += 1
                    crit["grammaire"] += bool(g.get("grammaire"))
                    if g.get("faisable") is False and s["faisable"]:
                        crit["faisable"] -= 1  # offered, but Bird has no such capability (a weather map)
        table[arm] = {"chips": n, **{k: round(v / n, 2) if n else None for k, v in crit.items() if k != "grammaire"},
                      "grammaire": round(crit["grammaire"] / judged, 2) if judged else None, "jugées": judged,
                      "tours avec chips": f"{turns_with}/{len(rows) - talk}", "silence": f"{talk_ok}/{talk}"}  # fmt: skip
    secs = [r["next_seconds"] for r in rows if r.get("next_seconds")]
    lat = {"p50": round(statistics.median(secs), 2), "p95": round(sorted(secs)[max(0, int(0.95 * len(secs)) - 1)], 2),
           "n": len(secs)} if secs else {}  # fmt: skip
    return {"table": table, "latency": lat, "rows": len(rows), "old": old, "arms": arms}


def strict(before: Path, after: Path, judged: Path) -> dict:
    """The strict re-score (review of 28/11): « faisable » judged by hand against what Bird's tools do with what
    the conversation holds (no invented origin, assumption or user fact), not by the patterns. Three arms on the
    same 20 recorded answers: « livré » (the chips the first run showed), « avant » (that prompt's raw output
    under today's validation) and « après » (today's prompt, replayed live, today's validation).
    ``judged``: {arm: {"<id>|<label>": "F" not doable, "G" generic / redundant / near duplicate, "W" badly worded}};
    a chip not listed was read and passes all three."""
    from birds.harness import catalog
    from birds.harness import nextsteps as N

    tools = {m.name for m in catalog.MODULES} | {"web_search", "read_page", "draft_email"}
    marks = json.loads(judged.read_text())
    b, a = json.loads(before.read_text()), json.loads(after.read_text())
    arms = {
        "livré": {r["id"]: r.get("suggestions") or [] for r in b},
        "avant": {r["id"]: N.validate(r.get("raw") or {}, lang=r["lang"], available=tools)[0] for r in b},
        "après": {r["id"]: N.validate(r.get("raw") or {}, lang=r["lang"], available=tools)[0] for r in a},
    }
    table = {}
    for arm, by in arms.items():
        n = bad = gen = worded = turns_bad = 0
        for pid, chips in by.items():
            flags = [marks.get(arm, {}).get(f"{pid}|{c['label']}", "") for c in chips]
            n += len(chips)
            bad += sum("F" in f for f in flags)
            gen += sum("G" in f for f in flags)
            worded += sum("W" in f for f in flags)
            turns_bad += any("F" in f for f in flags)
        table[arm] = {"puces": n, "faisable": round(1 - bad / n, 2), "utile": round(1 - gen / n, 2),
                      "bien formulée": round(1 - worded / n, 2), "irréprochables": round(
                          sum(not marks.get(arm, {}).get(f"{p}|{c['label']}") for p, cs in by.items() for c in cs) / n, 2),
                      "tours avec une puce infaisable": f"{turns_bad}/{len(by)}"}  # fmt: skip
    return table


def cases(base: str, live: bool) -> dict:
    """router_data.NEXTSTEPS_CASES: the old chips (offline, no model) and, with ``live``, Bird's next steps (one
    generation per case on BIRD_BASE_URL), each judged by router_data.nextsteps_ok."""
    import router_data as D

    rows = [{"id": c[0], "lang": c[1], "prompt": c[2], "answer": {"content": c[3]}} for c in D.NEXTSTEPS_CASES]
    old = old_chips(rows, base)
    out = {"avant": {}, "après": {}}
    for cid, *_, expect in D.NEXTSTEPS_CASES:
        out["avant"][cid] = {"chips": [c["label"] for c in old[cid]], "ok": D.nextsteps_ok(old[cid], expect)}
    if live:
        from birds.harness import nextsteps as N
        from birds.harness.llm import CompletionsClient
        from birds.harness.template import TemplateTokenizer

        llm = CompletionsClient(os.environ["BIRD_BASE_URL"], os.environ.get("BIRD_MODEL", "adubrou/Bird-S-4B"),
                                os.environ.get("BIRD_API_KEY"))  # fmt: skip
        for cid, lang, req, ans, expect in D.NEXTSTEPS_CASES:
            got = N.generate(llm, TemplateTokenizer(), req, ans, lang=lang, budget=30)
            out["après"][cid] = {"chips": [c["label"] for c in got["items"]], "ok": D.nextsteps_ok(got["items"], expect),
                                 "seconds": got["seconds"]}  # fmt: skip
    for arm in out:
        if out[arm]:
            out[arm]["score"] = f"{sum(v['ok'] for v in out[arm].values())}/{len(D.NEXTSTEPS_CASES)}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", type=Path)
    ap.add_argument("--score", type=Path)
    ap.add_argument("--base", default="941cfc9")
    ap.add_argument("--max-gens", type=int, default=60)
    ap.add_argument("--replay", type=Path, help="with --out: today's prompt on the recorded answers of this file")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--strict", nargs=3, type=Path, metavar=("BEFORE", "AFTER", "JUDGED"),
                    help="the strict hand re-score of three arms (docs/HARNESS.md § 18)")
    ap.add_argument("--only", default="")
    ap.add_argument("--dump", action="store_true", help="print every chip of each arm (for the hand judgement)")
    ap.add_argument("--cases", action="store_true", help="router_data.NEXTSTEPS_CASES: old chips offline")
    ap.add_argument("--live", action="store_true", help="with --cases: also Bird's next steps, live (8 gens)")
    a = ap.parse_args(argv)
    if a.record:
        record(a.record, a.max_gens, set(filter(None, a.only.split(","))) or None)
    if a.strict:
        print(json.dumps(strict(*a.strict), ensure_ascii=False, indent=1))
    if a.replay:
        replay(a.replay, a.out, set(filter(None, a.only.split(","))) or None)
    if a.cases:
        print(json.dumps(cases(a.base, a.live), ensure_ascii=False, indent=1))
    if a.score:
        # the tools of the production deployment (web search on, every open-data module on)
        from birds.harness import catalog

        tools = {m.name for m in catalog.MODULES} | {"web_search", "read_page", "draft_email"}
        got = score(a.score, a.base, tools)
        if a.dump:
            for arm, by in got["arms"].items():
                for pid, chips in by.items():
                    for c in chips:
                        print(json.dumps({"key": f"{arm}|{pid}|{c['label']}", "prompt": c["prompt"]},
                                         ensure_ascii=False))  # fmt: skip
        print(json.dumps({k: got[k] for k in ("table", "latency", "rows")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
