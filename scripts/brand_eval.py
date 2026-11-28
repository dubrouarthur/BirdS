"""Live check of how Bird introduces itself: the brand message, before / after a system prompt change.

Five identity questions (FR and EN) and three ordinary tasks, run through the full harness on the real endpoint,
with the system prompt of one arm. Only the model varies: no search engine, no web page.

    BIRD_BASE_URL=https://…/v1 BIRD_API_KEY=… .venv/bin/python scripts/brand_eval.py --arms before,after

Arms: "before" is the system prompt as trained (identity.DEFAULT_SYSTEM), "after" the runtime one
(identity.RUNTIME_SYSTEM, the trained text plus one sentence on Bird Models). Rubric, per answer:
  identity questions  light (léger / light), place (an affirmative « s'installe… / où vous voulez / centre de
                      données », never a bare "install"; any « je ne connais pas » answer scores no brand point),
                      france (conçu en France / designed in France), clean (no base model name, no hardware count,
                      no self-deprecation up front, no other assistant's name), lang (answers in the asker's language)
  ordinary tasks      clean, lang, quiet (does not slip the brand into a mail or a summary)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

IDENTITY = [
    ("fr", "Qui es-tu ?"),
    ("fr", "Présente Bird en deux phrases."),
    ("fr", "Où peut-on installer Bird ?"),
    ("fr", "Pourquoi choisir un petit modèle comme toi ?"),
    ("en", "Who are you?"),
]
ORDINARY = [
    ("fr", "Rédige un mail court à Claire : on décale la réunion de jeudi à vendredi 10 h."),
    ("fr", "Résume en une phrase : le télétravail concerne 26 % des salariés du privé en 2023 selon la Dares."),
    ("en", "Write a two-line thank-you note to a colleague who covered my shift."),
]
LIGHT = re.compile(r"\bl[ée]g[eè]re?s?\b|l[ée]g[èe]ret[ée]|\blight(weight)?\b|\bsmall\b|\bpetit", re.I)
# « Où l'installer » : an affirmative answer only. A bare "install" also matches a refusal (« je n'ai pas d'infos
# d'installation »), so the verb must say where Bird goes, and any « je ne connais pas » vetoes the whole answer.
PLACE = re.compile(
    r"s'install\w*|\binstalls? (it |bird )?(wherever|anywhere|on|in)\b|\bcan be installed\b|"
    r"o[ùu] (vous|tu) (le |la )?(voul|souhait)|wherever|centre de donn|data ?cent|chez (vous|toi)|on[- ]premises?\b|"
    r"sur (votre|vos|ta|tes) (propres? )?(machine|serveur|ordinateur|infrastructure)",
    re.I,
)
NOT_KNOWN = re.compile(  # « I don't know Bird »: the model does not know the product it is asked about
    r"ne (connais|sais) (pas|rien)( de| du| le| la| ce| cette)? ?(produit|bird|logiciel|outil)|pas d'infos?|"
    r"aucune info|(don't|do not) know (of |about )?(any |a |the )?(product|bird|tool)|not familiar with|"
    r"no information (about|on)",
    re.I,
)
FRANCE = re.compile(r"(con[çc]u|d[ée]velopp[ée]|cr[ée]{2}) en France|designed in France|French", re.I)
DIRTY = re.compile(
    r"qwen|alibaba|\bgpu\b|carte graphique|graphics card|\bh100\b|\ba100\b|"
    r"plus d'erreurs|more mistakes|moins (performant|capable) que|less capable|"
    r"\bchatgpt\b|\bclaude\b|\bgemini\b|openai|anthropic",
    re.I,
)
BRAND = re.compile(r"Bird Models|centre de donn|data ?cent|sources? d'[ée]nergie|energy sources", re.I)


def lang_ok(text: str, lang: str) -> bool:
    fr = len(re.findall(r"\b(le|la|les|des|est|et|vous|une|pour|que)\b", text, re.I))
    en = len(re.findall(r"\b(the|is|and|you|for|that|of|to)\b", text, re.I))
    return fr >= en if lang == "fr" else en > fr


def score(kind: str, lang: str, text: str) -> dict:
    c = {"clean": not DIRTY.search(text), "lang": lang_ok(text, lang)}
    if kind == "identity":
        known = not NOT_KNOWN.search(text)  # a refusal scores nothing, whatever words it happens to contain
        c.update(
            light=known and bool(LIGHT.search(text)),
            place=known and bool(PLACE.search(text)),
            france=known and bool(FRANCE.search(text)),
        )
    else:
        c["quiet"] = not BRAND.search(text)
    return c


def table(rows: list[dict], arms: list[str]) -> None:
    print("\n| arm | identity: light | place | France | clean | ordinary: clean | quiet | all checks |")
    print("|---|---|---|---|---|---|---|---|")
    for arm in arms:
        ids = [r for r in rows if r["arm"] == arm and r["kind"] == "identity"]
        ords = [r for r in rows if r["arm"] == arm and r["kind"] == "ordinary"]

        def n(rs, k):
            return f"{sum(r['checks'].get(k, False) for r in rs)}/{len(rs)}"

        tot = sum(len(r["checks"]) for r in rows if r["arm"] == arm)
        ok = sum(sum(r["checks"].values()) for r in rows if r["arm"] == arm)
        print(f"| {arm} | {n(ids, 'light')} | {n(ids, 'place')} | {n(ids, 'france')} | {n(ids, 'clean')} | "
              f"{n(ords, 'clean')} | {n(ords, 'quiet')} | {ok}/{tot} |")  # fmt: skip


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default=os.environ.get("BIRD_BASE_URL"))
    ap.add_argument("--model", default=os.environ.get("BIRD_MODEL", "bird"))
    ap.add_argument("--tokenizer", default=os.environ.get("BIRD_TOKENIZER", "Qwen/Qwen3.5-4B"))
    ap.add_argument("--arms", default="before,after")
    ap.add_argument("--json", help="write every answer and check to this file")
    ap.add_argument("--only", help="regex on the questions (a smaller run)")
    ap.add_argument("--rescore", nargs="+", metavar="JSON",
                    help="re-score saved answers with the current rubric (no generation), rewrite their checks")  # fmt: skip
    a = ap.parse_args(argv)
    if a.rescore:
        for f in a.rescore:
            rows = json.loads(Path(f).read_text(encoding="utf-8"))
            for r in rows:
                if r["answer"].strip():
                    r["checks"] = score(r["kind"], r["lang"], r["answer"])
            Path(f).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f)
            table(rows, sorted({r["arm"] for r in rows}, key=["before", "after"].index))
        return 0
    if not a.base_url:
        ap.error("--base-url (or BIRD_BASE_URL) is required: this evaluation runs the live model")
    import tempfile

    import httpx
    from transformers import AutoTokenizer  # tokenizer only

    from birds.harness import Agent, CompletionsClient, Config, guard
    from birds.sources.identity import DEFAULT_SYSTEM, RUNTIME_SYSTEM

    class NoSearch:
        def search(self, *a, **k):
            raise RuntimeError("no search in this evaluation")

    prompts = {"before": DEFAULT_SYSTEM, "after": RUNTIME_SYSTEM}
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    llm = CompletionsClient(a.base_url, a.model, os.environ.get("BIRD_API_KEY"))
    rows = []
    with tempfile.TemporaryDirectory(prefix="bird-brand-") as tmp:
        cfg = Config(workspace=Path(tmp), audit_file=None)
        for arm in a.arms.split(","):
            for kind, cases in (("identity", IDENTITY), ("ordinary", ORDINARY)):
                for lang, ask in cases:
                    if a.only and not re.search(a.only, ask):
                        continue
                    agent = Agent(llm, tok, cfg, confirm=lambda t, x: True, search=NoSearch(),
                                  http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))  # fmt: skip
                    agent.audit = guard.Audit(None)
                    t0 = time.monotonic()
                    try:
                        run = agent.run(ask, system=prompts[arm][lang], lang=lang)
                        drafts = "\n".join(f"{d.get('subject', '')}\n{d.get('body', '')}" for d in run.drafts)
                        text, err = f"{run.answer or ''}\n{drafts}", ""
                    except Exception as e:  # noqa: BLE001 - an endpoint error is a failed case, reported
                        text, err = "", f"{type(e).__name__}: {e}"
                    checks = score(kind, lang, text) if text.strip() else {"answered": False}
                    rows.append({"arm": arm, "kind": kind, "lang": lang, "ask": ask, "answer": text.strip(),
                                 "checks": checks, "seconds": round(time.monotonic() - t0, 1), "error": err,
                                 "gens": len(run.usage) if not err else 0})  # fmt: skip
                    bad = [k for k, v in checks.items() if not v]
                    print(f"[{arm}] {ask[:48]:48s} {'PASS' if not bad else 'fail'} gens={rows[-1]['gens']} {' '.join(bad)} {err}",
                          flush=True)  # fmt: skip
    table(rows, a.arms.split(","))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
