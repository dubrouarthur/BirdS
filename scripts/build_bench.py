"""Build the Bird benchmark: bench.jsonl + bench_stats.json.

    python scripts/build_bench.py --out out/bench

One item per line:
    {"id", "suite", "lang", "thinking", "messages", "tools"?, "max_new_tokens", "scorer", "expected", "meta"}
`messages` ends with a user turn; the model generates the next assistant turn, `birds.scoring.score` grades it.
Deterministic: same seed, same upstream files => same benchmark.

Only held-out data is used: BFCL v3, When2Call `test` (never `train`), grounded-qa `test`/`test_unseen` (never `train`),
PIAF, JSONSchemaBench `test` splits, bird-bench finance and hand-written prompts (bench/handwritten.py).
`prompt_hashes` in bench_stats.json uses the same recipe as `fingerprint()` in scripts/build_mix.py, so the
training mix can drop any colliding prompt.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import random
import re
import runpy

import jsonschema
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from birds.checks import extract_numbers
from birds.scoring import contains, is_refusal, norm, score
from birds.tools import BIRD_TOOLS

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED = 20261120
MAX_TOKENS = {"tool": 384, "text": 512, "finance": 700, "think": 1536}
THINK_COPIES = {"tool_bfcl": 60, "finance_exact": 60, "agent_tools": None}  # None = all
BFCL = "gorilla-llm/Berkeley-Function-Calling-Leaderboard"
BFCL_PLAN = {"simple": 50, "multiple": 40, "parallel": 40, "live_simple": 35, "live_multiple": 35}
IRRELEVANCE_PLAN = {"irrelevance": 50, "live_irrelevance": 50}
MAX_TOOLS_CHARS = 6000


def rng(name: str) -> random.Random:
    return random.Random(f"{SEED}:{name}")


def fetch(repo: str, path: str) -> str:
    return hf_hub_download(repo, path, repo_type="dataset")


def jsonl(repo: str, path: str) -> list[dict]:
    with open(fetch(repo, path), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parquet(repo: str, path: str) -> list[dict]:
    return pq.read_table(fetch(repo, path)).to_pylist()


def fingerprint(messages: list[dict]) -> str:
    users = " ".join(m["content"] for m in messages if m["role"] == "user")
    return hashlib.sha1(" ".join(users.lower().split())[:2000].encode()).hexdigest()


def spread(groups: dict[str, list]) -> list:
    """Interleave groups proportionally, so that any prefix keeps the stratification."""
    keyed = [
        ((i + 0.5) / len(rows), name, i, row) for name, rows in sorted(groups.items()) for i, row in enumerate(rows)
    ]
    return [row for *_, row in sorted(keyed, key=lambda t: t[:3])]


def item(suite, key, lang, messages, scorer, expected, budget, tools=None, **meta) -> dict:
    it = {"id": f"{suite}-{key}", "suite": suite, "lang": lang, "thinking": False, "messages": messages}
    if tools:
        it["tools"] = tools
    it.update({"max_new_tokens": MAX_TOKENS[budget], "scorer": scorer, "expected": expected, "meta": meta})
    return it


# ---------------------------------------------------------------- BFCL helpers

_TYPES = {
    "dict": "object",
    "object": "object",
    "float": "number",
    "double": "number",
    "number": "number",
    "int": "integer",
    "integer": "integer",
    "long": "integer",
    "bool": "boolean",
    "boolean": "boolean",
    "str": "string",
    "string": "string",
    "tuple": "array",
    "list": "array",
    "array": "array",
    "null": "null",
    "none": "null",
}


def fix_schema(s):
    """BFCL parameter spec -> JSON Schema: python-style type names are mapped, unknown ones ("any") are dropped."""
    if not isinstance(s, dict):
        return {}
    out = {}
    for k, v in s.items():
        if k == "type":
            names = [v] if isinstance(v, str) else v if isinstance(v, list) else []
            names = [_TYPES[n.lower()] for n in names if isinstance(n, str) and n.lower() in _TYPES]
            if names:
                out["type"] = names[0] if len(names) == 1 else names
        elif k == "properties" and isinstance(v, dict):
            out[k] = {name: fix_schema(sub) for name, sub in v.items()}
        elif k in ("items", "additionalProperties") and isinstance(v, dict):
            out[k] = fix_schema(v)
        elif k == "required":
            if isinstance(v, list):
                out[k] = [x for x in v if isinstance(x, str)]
        elif k in ("anyOf", "oneOf", "allOf") and isinstance(v, list):
            out[k] = [fix_schema(x) for x in v]
        elif k == "optional":
            continue
        else:
            out[k] = v
    if "properties" in out and "required" in out:
        out["required"] = [x for x in out["required"] if x in out["properties"]]
    return out


def to_tools(functions: list) -> list[dict] | None:
    """BFCL / When2Call function specs -> OpenAI tools (None when the spec cannot be made valid)."""
    tools, seen = [], set()
    for fn in functions:
        fn = json.loads(fn) if isinstance(fn, str) else fn
        name = fn.get("name")
        if not isinstance(name, str) or not name or name in seen:
            return None
        seen.add(name)
        params = fix_schema(fn.get("parameters") or {})
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        if params["type"] != "object":
            return None
        try:
            jsonschema.Draft202012Validator.check_schema(params)
        except jsonschema.SchemaError:
            return None
        tools.append(
            {
                "type": "function",
                "function": {"name": name, "description": str(fn.get("description") or ""), "parameters": params},
            }
        )
    return tools


def single_user_turn(question) -> str | None:
    if len(question) == 1 and len(question[0]) == 1 and question[0][0].get("role") == "user":
        text = question[0][0].get("content")
        return text if isinstance(text, str) and text.strip() else None
    return None


_SEEN_QUESTIONS: set[str] = set()


def bfcl_rows(category: str, with_answers: bool) -> list[dict]:
    answers = {}
    if with_answers:
        answers = {r["id"]: r["ground_truth"] for r in jsonl(BFCL, f"possible_answer/BFCL_v3_{category}.json")}
    rows = []
    for r in jsonl(BFCL, f"BFCL_v3_{category}.json"):
        q = single_user_turn(r["question"])
        if q is None or not r["function"] or len(json.dumps(r["function"])) > MAX_TOOLS_CHARS:
            continue
        key = " ".join(q.lower().split())
        if key in _SEEN_QUESTIONS:  # BFCL repeats some questions within and across categories
            continue
        _SEEN_QUESTIONS.add(key)
        tools = to_tools(r["function"])
        if not tools:
            continue
        row = {"id": r["id"], "question": q, "tools": tools}
        if with_answers:
            gt = answers.get(r["id"])
            names = {t["function"]["name"] for t in tools}
            if not gt or any(len(c) != 1 or next(iter(c)) not in names for c in gt):
                continue
            row["calls"] = [{"name": n, "arguments": a} for c in gt for n, a in c.items()]
        rows.append(row)
    return rows


def build_bfcl() -> list[dict]:
    groups = {}
    for cat, n in BFCL_PLAN.items():
        rows = bfcl_rows(cat, True)
        groups[cat] = rng(f"bfcl:{cat}").sample(rows, n)
    out = []
    for cat, rows in groups.items():
        groups[cat] = [
            item(
                "tool_bfcl",
                r["id"],
                "en",
                [{"role": "user", "content": r["question"]}],
                "tool_call",
                {"calls": r["calls"]},
                "tool",
                tools=r["tools"],
                source=f"BFCL_v3_{cat}",
                source_id=r["id"],
            )
            for r in rows
        ]
    out = spread(groups)
    return out


def build_irrelevance() -> list[dict]:
    groups = {}
    for cat, n in IRRELEVANCE_PLAN.items():
        rows = rng(f"bfcl:{cat}").sample(bfcl_rows(cat, False), n)
        groups[cat] = [
            item(
                "tool_irrelevance",
                r["id"],
                "en",
                [{"role": "user", "content": r["question"]}],
                "no_call",
                {},
                "tool",
                tools=r["tools"],
                source=f"BFCL_v3_{cat}",
                source_id=r["id"],
            )
            for r in rows
        ]
    return spread(groups)


# ---------------------------------------------------------------- When2Call

# correct_answer (MCQ ground truth of the test file) -> behaviour we can check without a judge
W2C_BEHAVIOR = {"tool_call": "call", "request_for_info": "ask", "cannot_answer": "decline"}


def build_when2call(skip_source_ids: set[str], n_per_class: int = 50) -> list[dict]:
    rows = jsonl("nvidia/When2Call", "test/when2call_test_mcq.jsonl")
    r = rng("when2call")
    r.shuffle(rows)
    groups, used = collections.defaultdict(list), set(skip_source_ids)
    for row in rows:
        kind = row["correct_answer"]
        behavior = W2C_BEHAVIOR.get(kind)
        if behavior is None or len(groups[kind]) >= n_per_class or row["source_id"] in used:
            continue
        if not isinstance(row["question"], str) or len(json.dumps(row["tools"])) > MAX_TOOLS_CHARS:
            continue
        tools = to_tools(row["tools"]) if row["tools"] else []
        if tools is None:
            continue
        expected = {"behavior": behavior}
        if behavior == "call":
            expected["tool"] = json.loads(row["answers"]["tool_call"])["name"]
            if expected["tool"] not in {t["function"]["name"] for t in tools}:
                continue
        elif behavior == "ask" and "?" not in row["answers"]["request_for_info"]:
            continue  # the reference itself would fail the rule
        elif behavior == "decline" and "?" in row["answers"]["cannot_answer"]:
            continue
        used.add(row["source_id"])
        groups[kind].append(
            item(
                "tool_when2call",
                row["uuid"][:13],
                "en",
                [{"role": "user", "content": row["question"]}],
                "when2call",
                expected,
                "tool",
                tools=tools,
                source="When2Call/test_mcq",
                source_id=row["source_id"],
                correct_answer=kind,
                reference=row["answers"][kind],
            )
        )
    return spread(groups)


# ---------------------------------------------------------------- grounded QA

GROUNDED_HEAD = {
    "fr": (
        "Réponds à la question en t'appuyant uniquement sur les documents ci-dessous. "
        "Si la réponse ne s'y trouve pas, dis-le clairement.",
        "Document",
        "Question :",
    ),
    "en": (
        "Answer the question using only the documents below. If the answer is not in the documents, say so clearly.",
        "Document",
        "Question:",
    ),
}


def build_grounded(n: int = 150) -> list[dict]:
    rows = []
    for split in ("test", "test_unseen"):
        for r in parquet("LiquidAI/grounded-qa", f"{split}.parquet"):
            if r["language"] not in ("fr", "en"):
                continue
            ref = r["reference_answer"] or ""
            if r["answerable"] and (not ref or is_refusal(ref)):
                continue  # reference worded like a refusal: the rule could not tell it apart
            if not r["answerable"] and not is_refusal(r["fallback"]):
                continue
            rows.append({**r, "split": split})
    rows.sort(key=lambda r: r["id"])
    fr = [r for r in rows if r["language"] == "fr"]
    en = [r for r in rows if r["language"] == "en"]
    n_en = n - len(fr)
    r = rng("grounded")
    yes, no = [x for x in en if x["answerable"]], [x for x in en if not x["answerable"]]
    picked = fr + r.sample(yes, n_en - n_en // 2) + r.sample(no, n_en // 2)
    groups = collections.defaultdict(list)
    for row in picked:
        lang = row["language"]
        head, doc, qlabel = GROUNDED_HEAD[lang]
        docs = "\n\n".join(f"[{doc} {i}] {d['title']}\n{d['text']}" for i, d in enumerate(row["documents"], 1))
        content = f"{head}\n\n{docs}\n\n{qlabel} {row['question']}"
        expected = {
            "answerable": bool(row["answerable"]),
            "answer": row["answer"],
            "reference_answer": row["reference_answer"],
            "fallback": row["fallback"],
        }
        groups[f"{lang}{row['answerable']}"].append(
            item(
                "grounded_fr_en",
                row["id"],
                lang,
                [{"role": "user", "content": content}],
                "grounded",
                expected,
                "text",
                source=f"LiquidAI/grounded-qa:{row['split']}",
                source_id=row["id"],
                unanswerable_type=row["unanswerable_type"],
            )
        )
    return spread(groups)


# ---------------------------------------------------------------- PIAF


def build_piaf(n: int = 100) -> list[dict]:
    rows = parquet("AgentPublic/piaf", "plain_text/train-00000-of-00001.parquet")
    r = rng("piaf")
    r.shuffle(rows)
    out, seen = [], set()
    for row in rows:
        golds = sorted({a.strip() for a in row["answers"]["text"] if a and a.strip()})
        short = [g for g in golds if 1 <= len(norm(g).split()) <= 5 and len(norm(g)) >= 2]
        ctx = row["context"]
        if not short or not (300 <= len(ctx) <= 1500) or ctx in seen or contains(row["question"], short[0]):
            continue
        seen.add(ctx)
        content = (
            f"Contexte :\n{ctx}\n\nQuestion : {row['question']}\nRéponds en une phrase courte, à partir du contexte."
        )
        out.append(
            item(
                "qa_fr",
                row["id"],
                "fr",
                [{"role": "user", "content": content}],
                "contains_any", {"any": short, "max_words": 60},
                "text",
                source="AgentPublic/piaf",
                source_id=row["id"],
            )
        )
        if len(out) == n:
            break
    return out


# ---------------------------------------------------------------- JSON schema

JSON_HEAD = {
    "en": "Generate a JSON instance with realistic values that conforms to the following JSON Schema. Reply with the JSON only, no explanation.",
    "fr": "Génère une instance JSON, avec des valeurs réalistes, conforme au schéma JSON suivant. Réponds uniquement avec le JSON, sans explication.",
}
_FORMATS = {
    "date-time": "2025-01-15T10:30:00Z",
    "date": "2025-01-15",
    "time": "10:30:00Z",
    "email": "anna@example.com",
    "uri": "https://example.com/a",
    "url": "https://example.com/a",
    "uuid": "3f2b8c1e-5d4a-4f6b-9a7c-1e2d3c4b5a69",
    "ipv4": "192.168.1.10",
    "hostname": "example.com",
}


def example_instance(schema, root, depth: int = 0):
    """A simple instance for an easy schema (raises ValueError when the schema uses something we do not handle)."""
    if depth > 8:
        raise ValueError("too deep")
    if schema is True or schema == {}:
        return "example"
    if not isinstance(schema, dict):
        raise ValueError("unsupported schema")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("remote $ref")
        node = root
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return example_instance(node, root, depth + 1)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for k in ("anyOf", "oneOf"):
        if schema.get(k):
            rest = {a: b for a, b in schema.items() if a not in ("anyOf", "oneOf")}
            return example_instance({**rest, **schema[k][0]}, root, depth + 1)
    if schema.get("allOf"):
        merged = {a: b for a, b in schema.items() if a != "allOf"}
        for sub in schema["allOf"]:
            if "$ref" in sub:
                raise ValueError("allOf with $ref")
            merged = {**merged, **sub}
        return example_instance(merged, root, depth + 1)
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t is None:
        t = "object" if "properties" in schema else "array" if "items" in schema else "string"
    if t == "object":
        props = schema.get("properties") or {}
        return {k: example_instance(props.get(k, {}), root, depth + 1) for k in schema.get("required") or []}
    if t == "array":
        items = schema.get("items", {})
        if isinstance(items, list):
            return [example_instance(x, root, depth + 1) for x in items]
        return [example_instance(items, root, depth + 1) for _ in range(max(1, schema.get("minItems", 1)))]
    if t == "string":
        if "pattern" in schema:
            raise ValueError("pattern")
        base = _FORMATS.get(schema.get("format", ""), "example")
        return base + "x" * max(0, schema.get("minLength", 0) - len(base))
    if t in ("integer", "number"):
        v = schema.get("minimum", schema.get("exclusiveMinimum", 0) + 1 if "exclusiveMinimum" in schema else 1)
        if isinstance(schema.get("exclusiveMinimum"), bool):
            v = schema.get("minimum", 0) + 1
        if "maximum" in schema:
            v = min(v, schema["maximum"])
        if "multipleOf" in schema:
            v = schema["multipleOf"]
        return int(v) if t == "integer" else v
    if t == "boolean":
        return True
    if t == "null":
        return None
    raise ValueError(f"type {t}")


def build_json(plan: dict[str, int]) -> list[dict]:
    groups = {}
    for subset, n in plan.items():
        rows = parquet("epfl-dlab/JSONSchemaBench", f"{subset}/test-00000-of-00001.parquet")
        rows.sort(key=lambda r: r["unique_id"])
        rng(f"json:{subset}").shuffle(rows)
        kept = []
        for row in rows:
            raw = row["json_schema"]
            if len(raw) > 1500:
                continue
            try:
                schema = json.loads(raw)
                if (
                    not isinstance(schema, dict)
                    or schema.get("type") != "object"
                    or len(schema.get("properties") or {}) < 2
                ):
                    continue
                if not schema.get("required"):
                    continue  # "{}" would pass: nothing to measure
                cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
                cls.check_schema(schema)
                example = example_instance(schema, schema)
                if not cls(schema).is_valid(example) or cls(schema).is_valid({}):
                    continue
            except Exception:
                continue
            kept.append((row["unique_id"], schema, example))
            if len(kept) == n:
                break
        groups[subset] = kept
    out = []
    for i, (subset, uid, schema, example) in enumerate(spread({s: [(s, *k) for k in v] for s, v in groups.items()})):
        lang = "fr" if i % 3 == 2 else "en"
        content = f"{JSON_HEAD[lang]}\n\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```"
        out.append(
            item(
                "json_schema",
                f"{subset}-{uid}",
                lang,
                [{"role": "user", "content": content}],
                "json_schema",
                {"schema": schema, "example": example},
                "text",
                source=f"JSONSchemaBench/{subset}:test",
                source_id=uid,
            )
        )
    return out


# ---------------------------------------------------------------- finance


def build_finance() -> list[dict]:
    rows = [r for r in jsonl("adubrou/bird-bench", "finance/bench.jsonl") if r.get("kind") == "exact"]
    groups = collections.defaultdict(list)
    for row in sorted(rows, key=lambda r: r["id"]):
        msgs = [{"role": m["role"], "content": m["content"]} for m in row["messages"]]
        if not msgs or msgs[-1]["role"] != "user" or "numbers" not in (row.get("checks") or []):
            continue
        facts = {
            k: v for k, v in (row.get("facts") or {}).items() if isinstance(v, int | float) and not isinstance(v, bool)
        }
        # a figure already printed in the prompt proves nothing: grade only what has to be computed
        given = set(extract_numbers(" ".join(m["content"] for m in msgs)))
        computed = {k: v for k, v in facts.items() if float(v) not in given}
        if not facts:
            continue
        groups[f"{row['task_id']}:{row['lang']}"].append(
            item(
                "finance_exact",
                row["id"],
                row["lang"],
                msgs,
                "numbers",
                {"facts": computed or facts, "target": row["target"]},
                "finance",
                source="adubrou/bird-bench:finance",
                source_id=row["id"],
                task_id=row["task_id"],
                facts_given_in_prompt=sorted(set(facts) - set(computed)) if computed else [],
            )
        )
    for key, v in groups.items():
        rng(f"finance:{key}").shuffle(v)
    return spread(groups)


# ---------------------------------------------------------------- hand-written suites


def persona_prompts() -> dict[str, str]:
    text = (ROOT / "docs" / "PERSONA.md").read_text(encoding="utf-8")
    return {lang.lower(): re.search(rf"^{lang} : `([^`]+)`", text, re.M).group(1) for lang in ("FR", "EN")}


def build_handwritten() -> list[dict]:
    hw = runpy.run_path(str(ROOT / "bench" / "handwritten.py"))
    sys = persona_prompts()
    assert sys == {"fr": hw["SYS_FR"], "en": hw["SYS_EN"]}, "bench/handwritten.py is out of sync with docs/PERSONA.md"
    out, n = [], collections.Counter()
    for i, (lang, q) in enumerate(hw["IDENTITY"]):
        msgs = [{"role": "user", "content": q}]
        company = None
        if i % 2:
            pool = hw["COMPANY_FR"] if lang == "fr" else hw["COMPANY_EN"]
            company = pool[n[lang] % len(pool)]
            n[lang] += 1
            msgs.insert(0, {"role": "system", "content": company})
        out.append(
            item(
                "identity",
                f"{lang}-{i:02d}",
                lang,
                msgs,
                "identity",
                {"must_contain": "Bird"},
                "tool",
                source="handwritten",
                system="company" if company else "none",
            )
        )
    for i, (lang, q, tool, args) in enumerate(hw["AGENT"]):
        expected = {"tool": tool, **({"args_contains": args} if args else {})}
        out.append(
            item(
                "agent_tools",
                f"{lang}-{i:02d}",
                lang,
                [{"role": "system", "content": sys[lang]}, {"role": "user", "content": q}],
                "first_tool",
                expected,
                "tool",
                tools=BIRD_TOOLS,
                source="handwritten",
            )
        )
    for i, (lang, system, q) in enumerate(hw["LANG_FOLLOW"]):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": q}]
        out.append(
            item(
                "lang_follow",
                f"{lang}-{i:02d}",
                lang,
                msgs,
                "language",
                {"lang": lang},
                "tool",
                source="handwritten",
                system="english" if system else "none",
            )
        )
    for i, (lang, q, golds) in enumerate(hw["CONCISION"]):
        out.append(
            item(
                "concision",
                f"{lang}-{i:02d}",
                lang,
                [{"role": "user", "content": q}],
                "concise",
                {"any": golds, "max_words": 60},
                "tool",
                source="handwritten",
            )
        )
    return out


# ---------------------------------------------------------------- assembly and checks


def problems(it: dict) -> list[str]:
    out = []
    msgs = it["messages"]
    if it["lang"] not in ("fr", "en") or not isinstance(it["thinking"], bool):
        out.append("lang/thinking")
    if not msgs or msgs[-1]["role"] not in ("user", "tool"):
        out.append("must end with a user or tool message")
    for i, m in enumerate(msgs):
        if (
            m["role"] not in ("system", "user", "assistant", "tool")
            or not isinstance(m["content"], str)
            or not m["content"].strip()
        ):
            out.append(f"msg {i}")
        if m["role"] == "system" and i:
            out.append("system not first")
    names = set()
    for t in it.get("tools") or []:
        fn = t.get("function") or {}
        if t.get("type") != "function" or not fn.get("name") or fn["name"] in names:
            out.append("tool name")
        names.add(fn.get("name"))
        try:
            jsonschema.Draft202012Validator.check_schema(fn.get("parameters"))
            if fn["parameters"].get("type") != "object":
                out.append("tool parameters must be an object")
        except Exception:
            out.append("tool schema")
    try:
        r = score(it, {"reasoning": "", "content": "", "tool_calls": []})
        if not 0.0 <= r["score"] <= 1.0:
            out.append("score range")
    except Exception as e:
        out.append(f"scorer crashed: {e!r}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    bfcl = build_bfcl()
    items = bfcl + build_irrelevance()
    items += build_when2call({it["meta"]["source_id"] for it in bfcl})
    items += build_grounded() + build_piaf()
    items += build_json({"Glaiveai2K": 70, "Github_easy": 50})
    items += build_finance() + build_handwritten()

    seen_prompts = set()
    unique = []
    for it in items:  # the same question must not be graded twice
        fp = fingerprint(it["messages"])
        if fp not in seen_prompts:
            seen_prompts.add(fp)
            unique.append(it)
    dropped = len(items) - len(unique)
    items = unique

    by_suite = collections.defaultdict(list)
    for it in items:
        by_suite[it["suite"]].append(it)
    for suite, limit in THINK_COPIES.items():
        for it in by_suite[suite][:limit]:
            items.append(
                {
                    **it,
                    "id": it["id"] + "-think",
                    "suite": suite + "_think",
                    "thinking": True,
                    "max_new_tokens": MAX_TOKENS["think"],
                }
            )

    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)), "duplicate ids"
    bad = [(it["id"], p) for it in items if (p := problems(it))]
    assert not bad, bad[:5]

    with open(out / "bench.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    suites = {}
    for it in items:
        s = suites.setdefault(
            it["suite"],
            {
                "n": 0,
                "fr": 0,
                "en": 0,
                "scorer": it["scorer"],
                "thinking": it["thinking"],
                "max_new_tokens": it["max_new_tokens"],
                "source_ids": [],
            },
        )
        s["n"] += 1
        s[it["lang"]] += 1
        s["source_ids"].append(it["meta"].get("source_id") or it["id"])
    stats = {
        "seed": SEED,
        "n_items": len(items),
        "n_unique_prompts": len(seen_prompts),
        "duplicates_dropped": dropped,
        "suites": suites,
        "when2call_mapping": W2C_BEHAVIOR,
        "prompt_hashes": sorted(seen_prompts),
    }
    (out / "bench_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, s in suites.items():
        print(f"{name:22s} n={s['n']:4d} fr={s['fr']:3d} en={s['en']:3d} {s['scorer']}")
    print(f"total {len(items)} items, {len(seen_prompts)} unique prompts, {dropped} duplicates dropped -> {out}")


if __name__ == "__main__":
    main()
