"""Evaluate the model router on the whole trigger bench, against the regex parsers.

  # the real endpoint (vLLM), when it is up:
  .venv/bin/python -I scripts/router_eval.py --base-url https://…/v1 --model bird-s-4b [--mode model|hybrid]
  # plumbing only, with the scripted stand-in (no network):
  .venv/bin/python -I scripts/router_eval.py --fake

The API key is read from BIRD_API_KEY (never on the command line). Prints, per bench family, accuracy, precision
and recall of the router and of the parsers (``router.regex_decision``), then latency p50/p95, the invalid-JSON
rate and the fallback rate. ``--out`` writes every row (text, label, both decisions) as JSON lines for review.
A "yes" counts as found only with the right arguments where the bench names them (place, cities, query…).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import router_data as D  # noqa: E402

from birds.harness import router as R  # noqa: E402
from birds.harness.template import TemplateTokenizer  # noqa: E402


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def sample(data: list[dict], per_class: int, seed: int = 0) -> list[dict]:
    """At most ``per_class`` items per (family, label), drawn with a fixed seed, in bench order."""
    import random

    rng, keep = random.Random(seed), set()
    groups: dict[tuple, list[int]] = {}
    for i, it in enumerate(data):
        groups.setdefault((it["family"], it["label"]), []).append(i)
    for idx in groups.values():
        keep.update(rng.sample(idx, min(per_class, len(idx))))
    return [it for i, it in enumerate(data) if i in keep]


def run(llm, tok, data, *, mode: str, structured: str, budget: float, lang_of, names=None) -> list[dict]:
    rows = []
    for i, it in enumerate(data):
        lang = lang_of(it["text"])
        base = R.regex_decision(it["text"], history=it["history"], lang=lang)
        t0 = time.monotonic()
        d = R.decide(llm, tok, it["text"], history=it["history"], lang=lang, mode=mode, structured=structured,
                     budget=budget, base=base, names=names)  # fmt: skip
        wall = time.monotonic() - t0
        # hybrid is the same call, merged afterwards with the parsers: scored from this one call. ``plain`` is the
        # merge before own_words (every parser call of a family the model left out comes back), kept for comparison
        own = R.own_decision(it["text"], history=it["history"], lang=lang)
        h = d if d.source in ("fallback", "regex") or mode == "hybrid" else R.merge(d, base, own)
        p = d if d.source in ("fallback", "regex") or mode == "hybrid" else R.merge(d, base)
        jm, jb, jh, jp = D.judge(d, it), D.judge(base, it), D.judge(h, it), D.judge(p, it)
        rows.append({**{k: it[k] for k in ("family", "label", "text")}, "ok": jm["ok"], "pred": jm["pred"],
                     "regex_ok": jb["ok"], "regex_pred": jb["pred"],
                     "hybrid_ok": jh["ok"], "hybrid_pred": jh["pred"], "plain_ok": jp["ok"], "plain_pred": jp["pred"],
                     "source": d.source,
                     "fallback": d.meta.get("fallback"), "invalid": bool(d.meta.get("invalid")),
                     "seconds": d.meta.get("seconds", round(wall, 3)), "router": d.as_dict(),
                     "regex": base.as_dict(), "dropped": d.meta.get("dropped", []),
                     "vetoed": d.meta.get("vetoed", [])})  # fmt: skip
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(data)}", file=sys.stderr, flush=True)
    return rows


def report(rows: list[dict]) -> dict:
    model = D.summarise(rows)
    regex = D.summarise([{**r, "ok": r["regex_ok"], "pred": r["regex_pred"]} for r in rows])
    hybrid = D.summarise([{**r, "ok": r["hybrid_ok"], "pred": r["hybrid_pred"]} for r in rows])
    plain = D.summarise([{**r, "ok": r.get("plain_ok", r["hybrid_ok"]), "pred": r.get("plain_pred", r["hybrid_pred"])}
                         for r in rows])  # fmt: skip
    fmt = lambda v: "  -  " if v is None else f"{v:.3f}"  # noqa: E731
    trio = lambda x: f"{fmt(x['accuracy'])} {fmt(x['precision'])} {fmt(x['recall'])}"  # noqa: E731
    print(f"{'family':14s} {'n':>4s}   {'router acc/prec/rec':>17s}   {'hybrid acc/prec/rec':>17s}   "
          f"{'plain merge':>17s}   {'regex acc/prec/rec':>17s}  wrong args")  # fmt: skip
    for fam in sorted(model):
        m = model[fam]
        print(f"{fam:14s} {m['n']:4d}   {trio(m)}   {trio(hybrid[fam])}   {trio(plain[fam])}   {trio(regex[fam])}  "
              f"{m['wrong_args']}")  # fmt: skip
    lat = [r["seconds"] for r in rows if r["seconds"] is not None and r["source"] != "regex"]
    out = {
        "items": len(rows),
        "router_accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "hybrid_accuracy": round(sum(r["hybrid_ok"] for r in rows) / len(rows), 3),
        "plain_merge_accuracy": round(sum(r.get("plain_ok", r["hybrid_ok"]) for r in rows) / len(rows), 3),
        "regex_accuracy": round(sum(r["regex_ok"] for r in rows) / len(rows), 3),
        "latency_p50": _pct(lat, 0.5),
        "latency_p95": _pct(lat, 0.95),
        "invalid_json_rate": round(sum(r["invalid"] for r in rows) / len(rows), 3),
        "fallback_rate": round(sum(r["source"] == "fallback" for r in rows) / len(rows), 3),
        "vetoed": sum(bool(r["vetoed"]) for r in rows),
        "router_only_right": sum(r["ok"] and not r["regex_ok"] for r in rows),
        "regex_only_right": sum(r["regex_ok"] and not r["ok"] for r in rows),
        "families": {"router": model, "hybrid": hybrid, "plain_merge": plain, "regex": regex},
    }
    print(json.dumps({k: v for k, v in out.items() if k != "families"}))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BIRD_BASE_URL", ""))
    ap.add_argument("--model", default=os.environ.get("BIRD_MODEL", "bird-s-4b"))
    ap.add_argument("--mode", choices=["model", "hybrid"], default="model")
    ap.add_argument(
        "--structured", default="auto", help="auto (probe once), none, or one of " + ", ".join(R.STRUCTURED_KINDS)
    )
    ap.add_argument("--budget", type=float, default=R.BUDGET_S, help="latency budget per call, seconds")
    ap.add_argument("--families", nargs="*", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--per-class", type=int, default=0, help="at most N items per (family, yes/no), seeded: a capped live run"
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fake", action="store_true", help="scripted stand-in, no network (plumbing check)")
    ap.add_argument("--out", default="", help="JSON lines of every row")
    ap.add_argument("--without-family", default="", help="catalogue without this family's modules (a 'before' run)")
    a = ap.parse_args(argv)
    from birds.harness.agent import detect_lang

    data = [it for it in D.items() if not a.families or it["family"] in a.families]
    if a.per_class:
        data = sample(data, a.per_class, a.seed)
    data = data[: a.limit] if a.limit else data
    tok = TemplateTokenizer()
    if a.fake:
        llm, structured = D.Imitator(data), ""
    else:
        if not a.base_url:
            ap.error("--base-url (or BIRD_BASE_URL) is required, or --fake")
        from birds.harness.llm import CompletionsClient

        llm = CompletionsClient(a.base_url, a.model, os.environ.get("BIRD_API_KEY") or None, timeout=60.0)
        if a.structured == "auto":
            structured = R.structured_kind(llm, deadline=time.monotonic() + 30)
        else:
            structured = "" if a.structured == "none" else a.structured
        print(f"structured outputs: {structured or 'none (prompt + JSON repair)'}", file=sys.stderr)
    from birds.harness import catalog

    names = None
    if a.without_family:
        names = {m.name for m in catalog.MODULES if m.available and m.family != a.without_family}
    rows = run(llm, tok, data, mode=a.mode, structured=structured, budget=a.budget, lang_of=detect_lang, names=names)
    out = report(rows)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        Path(a.out).with_suffix(".summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
