"""Text sources: office writing, grounded answers, chat, reasoning, tables, extraction.

Every converter is written as `_name(row) -> list[dict] | str`, where a string is the reason the
row is skipped. `_safe` turns that into the registry contract (`[]` to skip, never raises) and
`why(name, row)` exposes the reason for probing and tests.

Some upstream files are sorted (by task, by sub-dataset, by language). The builder only shuffles
within a 10 000-row buffer and stops at the cap, so for those sources the converter thins rows
deterministically (hash of the row) and `scan` covers the whole file: the kept rows are then spread
over the file instead of being its first block.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Callable

from birds.sources import Source

# --------------------------------------------------------------------------------------------- filters

_CJK = re.compile(r"[ᄀ-ᇿ⺀-〿぀-ヿ㄰-㆏㐀-䶿一-鿿가-힯豈-﫿＀-￯]")
_MARKUP = re.compile(r"</?think>|</?tool_call>|</?tool_response>|<\|im_(?:start|end)\|>")
_BOT = (
    r"ChatGPT|GPT-?\d(?:\.\d)?o?|Claude|Gemini|Bard|Qwen|Tongyi|LLaMA|Copilot|SmolLM\d*|DeepSeek|Grok|"
    r"Mistral|Ernie|Phi-\d|Aya|Command R|Bing|Siri|Alexa|Cortana|Vicuna|Alpaca|Hermes|BIRD-M|Bird-Medium"
)
_VENDOR = (
    r"OpenAI|Open AI|Anthropic|Google|DeepMind|Alibaba|Meta|Microsoft|Mistral|DeepSeek|Hugging ?Face|"
    r"Cohere|xAI|Baidu|Liquid ?AI|Glaive|Nous Research|Stability AI|IBM|Amazon|Apple|Nvidia"
)
_ME = r"I am|I'm|I was|my name is|call me|you are|you're|je suis|je m'appelle|mon nom est|tu es|vous êtes"
_MADE = r"developed|created|trained|built|made|designed|powered|conçue?|créée?|développée?|entraînée?"
_CLAIM = re.compile(
    rf"\b(?:{_ME})\b[^.!?\n]{{0,40}}?\b(?:{_BOT})\b"
    rf"|\b(?:{_ME}|I|je|j'ai été)\b[^.!?\n]{{0,80}}?\b(?:{_MADE})\s+(?:by|par)\s+(?:the\s+)?(?:{_VENDOR})\b"
    rf"|\b(?:assistant|model|modèle|chatbot|AI|IA)\s+(?:{_MADE})\s+(?:by|par)\s+(?:{_VENDOR})\b"
    rf"|\b(?:{_VENDOR})(?:'s)?\s+(?:AI\s+)?(?:language model|assistant|chatbot)\b",
    re.I,
)
_REFUSAL = re.compile(
    r"\bas an? (?:large |advanced )?(?:AI|A\.I\.|artificial intelligence|language model|text-based|digital assistant|virtual assistant)\b"
    r"|\bI(?: am|'m) (?:just |only )?an? (?:AI|artificial intelligence) (?:language )?model\b"
    r"|\ben tant qu(?:e |')(?:IA|intelligence artificielle|modèle de langage|assistant virtuel|assistante virtuelle)\b",
    re.I,
)


def _h(*parts: object) -> int:
    """Stable hash (Python's hash() is salted per process)."""
    return int(hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8", "replace")).hexdigest()[:12], 16)


def _s(x: object) -> str:
    return x.strip() if isinstance(x, str) else ""


def _check(msgs: list[dict], short_ok: bool = False) -> str:
    """Reason to drop a conversation, or '' when it is clean."""
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant":
        return "shape"
    prev = None
    for i, m in enumerate(msgs):
        role, text, reason = m["role"], m["content"], m.get("reasoning_content") or ""
        if role not in ("system", "user", "assistant") or (role == "system" and i) or role == prev:
            return "shape"
        if not text:
            return "empty"
        if _MARKUP.search(text) or _MARKUP.search(reason):
            return "markup"
        if _CJK.search(text) or _CJK.search(reason):
            return "cjk"
        if _CLAIM.search(text) or _CLAIM.search(reason):
            return "other_assistant"
        if role == "assistant":
            if _REFUSAL.search(text):
                return "ai_refusal"
            if not short_ok and len(text.split()) < 2:
                return "one_word"
        prev = role
    if msgs[0]["role"] == "system" and (len(msgs) < 3 or msgs[1]["role"] != "user"):
        return "shape"
    return ""


def _rec(
    msgs: list[dict], lang: str, thinking: bool = False, task: str = "", short_ok: bool = False
) -> list[dict] | str:
    bad = _check(msgs, short_ok)
    if bad:
        return bad
    out = {"messages": msgs, "lang": lang, "thinking": thinking}
    if task:
        out["task"] = task
    return [out]


def _chat(raw: object, keep_reasoning: bool = False) -> list[dict] | None:
    """Normalise an upstream `messages` list to role/content(/reasoning_content) dicts."""
    if not isinstance(raw, list):
        return None
    out = []
    for m in raw:
        if not isinstance(m, dict) or not isinstance(m.get("role"), str) or not isinstance(m.get("content"), str):
            return None
        d = {"role": m["role"], "content": m["content"].strip()}
        if keep_reasoning and m["role"] == "assistant" and _s(m.get("reasoning_content")):
            d["reasoning_content"] = m["reasoning_content"].strip()
        out.append(d)
    return out


def _split_think(text: str) -> tuple[str, str] | None:
    """'<think>reasoning</think>answer' -> (reasoning, answer); None when the markup is not exactly that."""
    m = re.fullmatch(r"\s*<think>(.*?)</think>(.*)", text, re.S)
    if not m or "<think>" in m.group(2) or "</think>" in m.group(2) or "<think>" in m.group(1):
        return None
    return m.group(1).strip(), m.group(2).strip()


def _blocks(docs: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"[{i}] {title}\n{text}" if title else f"[{i}]\n{text}" for i, (title, text) in enumerate(docs, 1)
    )


def _fr_like(text: str) -> bool:
    w = re.findall(r"[a-zàâçéèêëîïôûùüœ']+", text.lower())
    fr = sum(x in _FR_WORDS for x in w)
    en = sum(x in _EN_WORDS for x in w)
    return fr > en


_FR_WORDS = frozenset(
    "le la les des est une un que qui je vous nous pour dans et à au aux du en sur avec pas ce cette mon ma mes quel quelle comment pourquoi peux pouvez".split()
)
_EN_WORDS = frozenset(
    "the is are and of to you i what how why for in on with my a an can could would please do does this that it me".split()
)

MAX_REASONING = 6000  # characters; longer chains are too much for a 4B model
MAX_CHARS = 14000  # whole conversation; the builder still enforces the token limit

# --------------------------------------------------------------------------------------------- bird_medium

_OLD_NAME = re.compile(r"\bBIRD[- ]?M(?:edium)?\b", re.I)
_OLD_ID = re.compile(r"\bBIRD[- ]?M(?:edium)?\b|Qwen", re.I)


def _bird_medium(row: dict) -> list[dict] | str:
    src = _s(row.get("source"))
    if not src or src == "identity":
        return "identity"
    msgs = _chat(row.get("messages"), keep_reasoning=True)
    if not msgs:
        return "shape"
    for m in msgs:
        if m["role"] == "system":
            m["content"] = _OLD_NAME.sub("Bird", m["content"])
        if _OLD_ID.search(m["content"]) or _OLD_ID.search(m.get("reasoning_content", "")):
            return "old_identity"
    thinking = bool(row.get("thinking")) and bool(msgs[-1].get("reasoning_content"))
    if not thinking:
        for m in msgs:
            m.pop("reasoning_content", None)
    lang = row.get("lang")
    if lang not in ("fr", "en"):
        return "lang"
    return _rec(msgs, lang, thinking, task=src, short_ok=src.startswith(("finance", "tables")))


# --------------------------------------------------------------------------------------------- rag_glaive

_DOC_HEAD = re.compile(r"^Document:\s*(\d+)\s*$", re.M)
_CO = re.compile(r"<co:\s*(?:doc(?:ument)?[_:\s]*(?:id)?\s*=?\s*)?(\d+)\s*>(.*?)</co(?::[^>]*)?>", re.S | re.I)
_RAG_SYS = {
    "Grounded": "Answer the question using only the numbered documents provided. Right after each passage taken from a "
    "document, cite that document with its number in square brackets, for example [1].",
    "Mixed": "Answer the question using the numbered documents provided, completed by your own knowledge where they fall "
    "short. Right after each passage taken from a document, cite that document with its number in square "
    "brackets, for example [1].",
}


def _rag_glaive(row: dict) -> list[dict] | str:
    question, raw, answer = _s(row.get("question")), _s(row.get("documents")), _s(row.get("answer"))
    system = _RAG_SYS.get(row.get("answer_mode"))
    if not (question and raw and answer and system):
        return "empty"
    parts = _DOC_HEAD.split(raw)
    if len(parts) < 3 or parts[0].strip():
        return "documents_format"
    ids, docs = [], []
    for num, body in zip(parts[1::2], parts[2::2], strict=True):
        m = re.fullmatch(r"\s*Title:(.*?)\n\s*Text:(.*)", body, re.S)
        if not m or not m.group(2).strip():
            return "documents_format"
        ids.append(int(num))
        docs.append((" ".join(m.group(1).split()), m.group(2).strip()))
    if ids != list(range(len(ids))):
        return "documents_format"
    m = re.fullmatch(r"(?:```\s*)?Cited Documents:[^\n]*\nAnswer:(.*?)(?:```)?", answer, re.S)
    if not m:
        return "answer_format"
    bad = []

    def cite(mm: re.Match) -> str:
        n = int(mm.group(1))
        if n >= len(docs) or "<co" in mm.group(2):
            bad.append(n)
        return f"{mm.group(2).rstrip()} [{n + 1}]"

    text = _CO.sub(cite, m.group(1).strip())
    if bad or re.search(r"</?co\b", text, re.I):
        return "citation_markup"
    text = re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"(\[\d+\])\s*([.,;:])", r"\1\2", text))
    user = f"{_blocks(docs)}\n\nQuestion: {question}"
    return _rec(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": text.strip()},
        ],
        "en",
        task="rag_cited",
    )


# --------------------------------------------------------------------------------------------- grounded_qa

_GQA_SYS = {
    "en": 'Answer the question using only the documents provided. If they do not contain the answer, reply exactly: "{f}"',
    "fr": "Réponds à la question en t'appuyant uniquement sur les documents fournis. S'ils ne contiennent pas la "
    "réponse, réponds exactement : « {f} »",
}


def _grounded_qa(row: dict) -> list[dict] | str:
    lang = row.get("language")
    if lang not in _GQA_SYS:
        return "lang"
    question, fallback = _s(row.get("question")), _s(row.get("fallback"))
    docs = [(_s(d.get("title")), _s(d.get("text"))) for d in row.get("documents") or [] if isinstance(d, dict)]
    docs = [d for d in docs if d[1]]
    answer = _s(row.get("reference_answer")) if row.get("answerable") else fallback
    if not (question and fallback and docs and answer) or not isinstance(row.get("answerable"), bool):
        return "empty"
    if row["answerable"] and answer == fallback:
        return "inconsistent"
    user = f"{_blocks(docs)}\n\nQuestion : {question}" if lang == "fr" else f"{_blocks(docs)}\n\nQuestion: {question}"
    return _rec(
        [
            {"role": "system", "content": _GQA_SYS[lang].format(f=fallback)},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ],
        lang,
        task="grounded_qa" if row["answerable"] else "grounded_qa_unanswerable",
    )


# --------------------------------------------------------------------------------------------- frenchqa

_FQA_INSTR = (
    "Réponds à la question en t'appuyant uniquement sur le document fourni. Si le document ne contient pas la "
    "réponse, dis-le simplement."
)
_FQA_NO = (
    "Le document ne contient pas la réponse à cette question.",
    "Je ne trouve pas cette information dans le document fourni.",
    "Le document fourni ne permet pas de répondre à cette question.",
    "Cette information ne figure pas dans le document.",
    "Le texte ne donne pas cette information.",
    "Je ne peux pas répondre à partir de ce document : l'information n'y figure pas.",
    "D'après le document fourni, il n'est pas possible de répondre à cette question.",
    "La réponse ne se trouve pas dans le document.",
)
_FQA_LEAD = ("D'après le document : {a}", "Le document indique : {a}", "Selon le document : {a}")
# sub-dataset -> (answerable?) -> share kept, in 1/1000. Tuned on the 200 617 training rows for ~10 400 answerable
# and ~5 500 unanswerable (35 %). fquad_v2 and newsquadfr* are left out: their upstream licences are non-commercial.
_FQA_KEEP = {
    ("piaf", True): 0,  # PIAF is in our benchmark (suite qa_fr): never train on it
    ("pragnakalp/squad_v2_french_translated", True): 70,
    ("piaf_v2", False): 0,
    ("pragnakalp/squad_v2_french_translated", False): 80,
}


def _frenchqa(row: dict) -> list[dict] | str:
    context, question, title = _s(row.get("context")), _s(row.get("question")), row.get("title")
    answers = row.get("answers") if isinstance(row.get("answers"), dict) else {}
    spans = [a.strip() for a in answers.get("text") or [] if isinstance(a, str) and a.strip()]
    keep = _FQA_KEEP.get((title, bool(spans)))
    if keep is None:
        return "sub_dataset_excluded"
    if len(context) < 200 or len(question) < 8:
        return "too_short"
    h = _h(row.get("id"), question)
    if h % 1000 >= keep:
        return "thinned"
    if spans:
        span = spans[0].strip(" \t\n.,;:")
        if not span or span not in context or len(span) > 300:
            return "span_not_in_document"
        if len(span.split()) >= 5:
            target = span[0].upper() + span[1:]
        else:
            target = _FQA_LEAD[(h // 1000) % len(_FQA_LEAD)].format(a=span)
        if target[-1] not in ".!?»":
            target += "."
    else:
        target = _FQA_NO[(h // 1000) % len(_FQA_NO)]
    if (h // 7919) % 2:
        msgs = [
            {"role": "system", "content": _FQA_INSTR},
            {"role": "user", "content": f"Document :\n{context}\n\nQuestion : {question}"},
        ]
    else:
        msgs = [{"role": "user", "content": f"Document :\n{context}\n\nQuestion : {question}\n\n{_FQA_INSTR}"}]
    return _rec(
        [*msgs, {"role": "assistant", "content": target}],
        "fr",
        task="doc_qa" if spans else "doc_qa_unanswerable",
        short_ok=True,
    )


# --------------------------------------------------------------------------------------------- smoltalk

_SMOL_PREFIX = re.compile(r"^You(?:'re| are) an AI assistant for text re-?writing\.\s*", re.I)


def _smol_task(task: str) -> Callable[[dict], list[dict] | str]:
    def conv(row: dict) -> list[dict] | str:
        msgs = _chat(row.get("messages"))
        if not msgs or [m["role"] for m in msgs] != ["system", "user", "assistant"]:
            return "shape"
        instruction, text, answer = (m["content"] for m in msgs)
        if not (instruction and text and answer):
            return "empty"
        if len(answer.split()) < 4 or answer == text:
            return "trivial_answer"
        instruction = _SMOL_PREFIX.sub("", instruction)
        if _h(text) % 2:  # half of the rows carry the instruction in the user turn, as people actually write it
            head = [{"role": "user", "content": f"{instruction}\n\n{text}"}]
        else:
            head = [{"role": "system", "content": instruction}, {"role": "user", "content": text}]
        return _rec([*head, {"role": "assistant", "content": answer}], "en", task=task)

    return conv


_SMOL_SKIP = {
    "smollm-rewrite-30k",
    "smol-summarize-20k",
    "longalign",
}  # first two are already smol_rewrite / smol_summarize


def _smol_smoltalk(row: dict) -> list[dict] | str:
    if row.get("source") in _SMOL_SKIP:
        return "source_excluded"
    msgs = _chat(row.get("messages"))
    if not msgs:
        return "shape"
    if sum(len(m["content"]) for m in msgs) > 8000:
        return "too_long"
    return _rec(msgs, "en")


# --------------------------------------------------------------------------------------------- coedit

_RUDE = re.compile(
    r"\b(?:fuck\w*|shit\w*|bitch\w*|cunt\w*|nigg\w*|whore\w*|asshole\w*|dick|pussy|bastard\w*|rape[ds]?)\b", re.I
)


def _coedit(row: dict) -> list[dict] | str:
    src, tgt, task = _s(row.get("src")), _s(row.get("tgt")), _s(row.get("task"))
    if ":" not in src or not tgt:
        return "shape"
    text = src.split(":", 1)[1].strip()
    if len(text.split()) < 6 or len(tgt.split()) < 4:
        return "too_short"
    if tgt == text:
        return "no_change"
    if _RUDE.search(src) or _RUDE.search(tgt):
        return "rude"
    if not (text[0].isupper() or text[0].isdigit() or text[0] in "\"'“(") or text[-1] not in ".!?\"'”)":
        return "fragment"
    if _h(src) % 100 >= 10:  # file is sorted by task: thin to ~1.1 x cap over the whole file
        return "thinned"
    return _rec(
        [{"role": "user", "content": src}, {"role": "assistant", "content": tgt}], "en", task=f"edit_{task or 'text'}"
    )


# --------------------------------------------------------------------------------------------- aya_fr


def _aya_fr(row: dict) -> list[dict] | str:
    if row.get("language_code") != "fra":
        return "lang"
    q, a = _s(row.get("inputs")), _s(row.get("targets"))
    if len(q) < 8:
        return "empty"
    if len(a.split()) < 3 or len(a) < 15:
        return "short_answer"
    if re.search(r"réponse correcte|bonne réponse\s*:", a, re.I):
        return "annotation_noise"
    return _rec([{"role": "user", "content": q}, {"role": "assistant", "content": a}], "fr")


# --------------------------------------------------------------------------------------------- reasoning


def _reasoned(question: str, response: str, task: str = "") -> list[dict] | str:
    parts = _split_think(response)
    if not question or parts is None:
        return "think_format"
    reasoning, answer = parts
    if len(reasoning) < 80:
        return "no_reasoning"
    if len(reasoning) > MAX_REASONING:
        return "reasoning_too_long"
    if len(question) + len(answer) > MAX_CHARS - MAX_REASONING:
        return "too_long"
    return _rec(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer, "reasoning_content": reasoning},
        ],
        "en",
        True,
        task=task,
    )


def _openthoughts(row: dict) -> list[dict] | str:
    conv = row.get("conversations")
    if not isinstance(conv, list) or len(conv) != 2 or not all(isinstance(m, dict) for m in conv):
        return "shape"
    if conv[0].get("from") not in ("human", "user") or conv[1].get("from") not in ("gpt", "assistant"):
        return "shape"
    domain = _s(row.get("domain"))
    return _reasoned(_s(conv[0].get("value")), _s(conv[1].get("value")), task=f"reasoning_{domain}" if domain else "")


def _glaive_reasoning(row: dict) -> list[dict] | str:
    return _reasoned(_s(row.get("prompt")), _s(row.get("response")))


def _multilingual_thinking(row: dict) -> list[dict] | str:
    lang_r = row.get("reasoning_language")
    if lang_r not in ("French", "English"):
        return "lang"
    user, reasoning, final, dev = (
        _s(row.get("user")),
        _s(row.get("analysis")),
        _s(row.get("final")),
        _s(row.get("developer")),
    )
    if not (user and reasoning and final):
        return "empty"
    if len(reasoning) > MAX_REASONING:
        return "reasoning_too_long"
    if _fr_like(reasoning) != (lang_r == "French"):
        return "reasoning_language_mismatch"
    # the reasoning language is a request of the prompt: keep it visible, otherwise the model would learn to
    # reason in French on English questions for no reason
    system = f"Reasoning language: {lang_r}." + (f"\n\n{dev}" if dev else "")
    return _rec(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": final, "reasoning_content": reasoning},
        ],
        "fr" if _fr_like(user) else "en",
        True,
    )


# --------------------------------------------------------------------------------------------- tables, SQL, JSON

_TABLE_KEEP = {"EntityMatching": 30, "SchemaMatching": 30}  # the two largest and least office-like tasks, in %


def _table_gpt(row: dict) -> list[dict] | str:
    prompt, completion, task = _s(row.get("prompt")), _s(row.get("completion")), _s(row.get("task"))
    if not (prompt and completion):
        return "empty"
    if len(prompt) > 9000:
        return "too_long"
    if _h(prompt) % 100 >= _TABLE_KEEP.get(task, 60):
        return "thinned"
    return _rec(
        [{"role": "user", "content": prompt}, {"role": "assistant", "content": completion}],
        "en",
        task=f"table_{task}" if task else "",
        short_ok=True,
    )


_SQL_HEAD = (
    "Database schema:\n```sql\n{c}\n```\n\n{q}",
    "Here is the database schema:\n```sql\n{c}\n```\n\nQuestion: {q}",
    "{q}\n\nSchema:\n```sql\n{c}\n```",
)


def _text_to_sql(row: dict) -> list[dict] | str:
    q, ctx, sql, expl = (_s(row.get(k)) for k in ("sql_prompt", "sql_context", "sql", "sql_explanation"))
    if not (q and ctx and sql and expl):
        return "empty"
    if "```" in ctx + sql or "\n\n" in expl:
        return "format"
    user = _SQL_HEAD[_h(q, ctx) % len(_SQL_HEAD)].format(c=ctx, q=q)
    return _rec(
        [{"role": "user", "content": user}, {"role": "assistant", "content": f"```sql\n{sql}\n```\n\n{expl}"}], "en"
    )


_EXT = {
    "en": (
        "Extract the information from the document into a JSON object that follows the JSON Schema below. Reply with "
        "the JSON object only. Copy strings as written; use YYYY-MM-DD for dates, HH:MM for times, numbers for "
        "amounts, and null (or [] for lists) when the document does not give the information.",
        "JSON Schema:",
        "Document:",
    ),
    "fr": (
        "Extrais les informations du document dans un objet JSON conforme au schéma JSON ci-dessous. Réponds "
        "uniquement avec l'objet JSON. Recopie les chaînes telles qu'elles sont écrites ; utilise AAAA-MM-JJ pour les "
        "dates, HH:MM pour les heures, des nombres pour les montants, et null (ou [] pour les listes) quand le "
        "document ne donne pas l'information.",
        "Schéma JSON :",
        "Document :",
    ),
}


def _structured_extraction(row: dict) -> list[dict] | str:
    lang = row.get("language")
    if lang not in _EXT:
        return "lang"
    schema, doc, out = _s(row.get("schema")), _s(row.get("document")), _s(row.get("extraction"))
    try:
        if not isinstance(json.loads(out), dict) or not isinstance(json.loads(schema), dict):
            return "invalid_json"
    except ValueError:
        return "invalid_json"
    if not doc:
        return "empty"
    instr, schema_label, doc_label = _EXT[lang]
    if _h(doc) % 2:
        head = [{"role": "system", "content": f"{instr}\n\n{schema_label}\n{schema}"}, {"role": "user", "content": doc}]
    else:
        head = [{"role": "user", "content": f"{instr}\n\n{schema_label}\n{schema}\n\n{doc_label}\n{doc}"}]
    return _rec([*head, {"role": "assistant", "content": out}], lang, short_ok=True)


def _slides_officesmith(row: dict) -> list[dict] | str:
    msgs, target, lang = _chat(row.get("messages")), _s(row.get("target")), row.get("lang")
    if not msgs or lang not in ("fr", "en") or msgs[-1]["role"] != "user":
        return "shape"
    try:
        deck = json.loads(target)
    except ValueError:
        return "invalid_json"
    if not isinstance(deck, dict) or not deck.get("slides"):
        return "invalid_json"
    return _rec([*msgs, {"role": "assistant", "content": target}], lang, short_ok=True)


# --------------------------------------------------------------------------------------------- French sources

_STOP = {
    "fr": "le la les des est une un que qui je vous nous pour dans et au aux du sur avec pas ce cette sont ont être il elle on plus par mais ou comme très aussi",
    "en": "the is are and of to you what how why for in on with my an can would this that it was were be have has from by as at or not",
    "es": "el los las es una que por para con y del al se su como más pero muy también son está en lo",
    "pt": "o os as é uma que por para com e do da em não um se como mais mas também são está no na",
    "it": "il lo gli è una che per con e del della di non un si come più ma anche sono nel alla",
    "de": "der die das ist eine und zu von mit für nicht den dem ein auf sich auch es im wie",
}
_STOP = {k: frozenset(v.split()) for k, v in _STOP.items()}
_WORD = re.compile(r"[a-zàâäçéèêëîïôöûùüœñáíóúãõß]+")


def _is_french(text: str) -> bool:
    """Stop-word ratio check: French must be the best-scoring language and reach 10 % of the words."""
    words = _WORD.findall(text[:3000].lower())
    if len(words) < 4:
        return False
    score = {k: sum(w in s for w in words) for k, s in _STOP.items()}
    fr = score.pop("fr")
    return fr >= 0.10 * len(words) and fr > max(score.values())


def _nemotron_fr(row: dict) -> list[dict] | str:
    msgs = _chat(row.get("messages"))
    if not msgs:
        return "shape"
    if msgs[0]["role"] == "system" and not msgs[0]["content"]:
        msgs = msgs[1:]
    if not msgs or msgs[-1]["role"] != "assistant":
        return "shape"
    if not _is_french(" ".join(m["content"] for m in msgs if m["role"] == "user")):
        return "not_french"
    thinking = False
    for i, m in enumerate(msgs):
        if m["role"] != "assistant" or "think>" not in m["content"]:
            continue
        parts = _split_think(m["content"])
        if parts is None:
            return "think_format"
        m["content"] = parts[1]
        if i == len(msgs) - 1 and parts[0]:
            if len(parts[0]) > MAX_REASONING:
                return "reasoning_too_long"
            m["reasoning_content"] = parts[0]
            thinking = True
    if sum(len(m["content"]) for m in msgs) > MAX_CHARS - MAX_REASONING:
        return "too_long"
    return _rec(msgs, "fr", thinking, short_ok=True)


def _synth_fr(row: dict) -> list[dict] | str:
    if row.get("language") != "fr":
        return "lang"
    if row.get("exercise") != "memorization" or _s(row.get("constraints")) or _s(row.get("script")):
        return "exercise_excluded"
    q, reasoning, a = _s(row.get("query")), _s(row.get("synthetic_reasoning")), _s(row.get("synthetic_answer"))
    if not (q and a):
        return "empty"
    if not (_is_french(q) and _is_french(a)):
        return "not_french"
    if len(reasoning) > 1500:  # keep the short traces only
        return "reasoning_too_long"
    if len(reasoning) < 80:
        return "no_reasoning"
    return _rec(
        [{"role": "user", "content": q}, {"role": "assistant", "content": a, "reasoning_content": reasoning}],
        "fr",
        True,
    )


def _smoltalk2_fr(row: dict) -> list[dict] | str:
    kw = row.get("chat_template_kwargs") if isinstance(row.get("chat_template_kwargs"), dict) else {}
    if kw.get("python_tools") or kw.get("xml_tools") or kw.get("enable_thinking"):
        return "shape"
    msgs = _chat(row.get("messages"))
    if not msgs:
        return "shape"
    if not all(_is_french(m["content"]) for m in msgs if m["role"] != "system" and len(m["content"]) > 40):
        return "not_french"
    if not _is_french(" ".join(m["content"] for m in msgs)):
        return "not_french"
    if sum(len(m["content"]) for m in msgs) > 8000:
        return "too_long"
    return _rec(msgs, "fr")


_MAIL_ASK = {
    "fr": (
        "Propose un objet pour ce mail :\n\n{b}",
        "Quel objet mettre à ce mail ?\n\n{b}",
        "{b}\n\nTrouve un objet pour ce mail.",
        "Voici un mail que je vais envoyer. Donne-moi uniquement son objet.\n\n{b}",
        "Rédige la ligne d'objet de ce message :\n\n{b}",
        "{b}\n\nQuel objet proposez-vous pour ce courriel ?",
    ),
    "en": (
        "Suggest a subject line for this email:\n\n{b}",
        "What subject should I give this email?\n\n{b}",
        "{b}\n\nWrite a subject line for this email.",
        "Here is an email I am about to send. Give me its subject line only.\n\n{b}",
        "Write the subject line for this message:\n\n{b}",
        "{b}\n\nWhat subject line would you suggest for this email?",
    ),
}
_MAIL_KEEP = {"fr": 100, "en": 16}  # % of usable rows, for ~2/3 French
_MAIL_PREFIX = re.compile(r"^(?:re|tr|fw|fwd|aw|wg|rif|r|i)\s*:", re.I)


def _emails_fr_en(row: dict) -> list[dict] | str:
    lang = row.get("lang")
    if lang not in _MAIL_KEEP:
        return "lang"
    if _s(row.get("in_reply_to")) or _s(row.get("calendar_method")) or _s(row.get("duplicate_of")):
        return "reply_or_calendar"
    subject, text = " ".join(_s(row.get("subject")).split()), _s(row.get("text"))
    sender = _s((row.get("from") or {}).get("name")) if isinstance(row.get("from"), dict) else ""
    if _MAIL_PREFIX.match(subject) or len(subject.split()) < 2 or len(subject) > 120:
        return "subject"
    # the export appends an automatic signature block (name line, job title, phone, legal notice): cut it
    lines = text.split("\n")
    cut = next((i for i, line in enumerate(lines) if sender and line.strip() == sender), None)
    if cut is None:
        return "signature_not_found"
    body = re.sub(r"\n\s*--\s*$", "", "\n".join(lines[:cut]).strip()).strip()
    if len(body.split()) < 15 or len(body) > 4000:
        return "body_length"
    if subject.lower() in body.lower():
        return "subject_in_body"
    h = _h(row.get("message_id"), subject)
    if h % 100 >= _MAIL_KEEP[lang]:
        return "thinned"
    ask = _MAIL_ASK[lang][(h // 100) % len(_MAIL_ASK[lang])].format(b=body)
    return _rec([{"role": "user", "content": ask}, {"role": "assistant", "content": subject}], lang, task="emails")


_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)


def _toolcall_fr(row: dict) -> list[dict] | str:
    kw = row.get("chat_template_kwargs") if isinstance(row.get("chat_template_kwargs"), dict) else {}
    raw = row.get("messages")
    if kw.get("python_tools") or not isinstance(raw, list) or len(raw) < 2:
        return "shape"
    tools = []
    try:
        for blob in kw.get("xml_tools") or []:
            tools += [json.loads(line) for line in blob.splitlines() if line.strip()]
    except ValueError:
        return "tools_format"
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if not (isinstance(fn, dict) and isinstance(fn.get("name"), str) and isinstance(fn.get("parameters"), dict)):
            return "tools_format"
    names = {t["function"]["name"] for t in tools} - {"final_answer"}
    msgs: list[dict] = []
    pending = 0
    for i, m in enumerate(raw):
        role, text = m.get("role"), m.get("content")
        if not isinstance(text, str) or role not in ("system", "user", "assistant", "tool"):
            return "shape"
        if role == "tool":
            if pending <= 0:
                return "tool_without_call"
            pending -= 1
            msgs.append({"role": "tool", "content": re.sub(r"^\s*Observation:\s*", "", text).strip()})
            continue
        if pending:
            return "missing_tool_result"
        if role != "assistant":
            msgs.append({"role": role, "content": text.strip()})
            continue
        mm = re.fullmatch(r"\s*(?:<think>(.*?)</think>)?(.*)", text, re.S)
        reasoning, rest = (mm.group(1) or "").strip(), mm.group(2)
        calls = []
        for blob in _CALL.findall(rest):
            try:
                call = ast.literal_eval(blob.strip())
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                try:  # raw line breaks inside a quoted argument (final answers often end with one)
                    call = ast.literal_eval(blob.strip().replace("\r", "").replace("\n", "\\n"))
                except (ValueError, SyntaxError, MemoryError, RecursionError):
                    return "call_format"
            if not (
                isinstance(call, dict) and isinstance(call.get("name"), str) and isinstance(call.get("arguments"), dict)
            ):
                return "call_format"
            calls.append(call)
        out = {"role": "assistant", "content": _CALL.sub("", rest).strip()}
        if reasoning:
            out["reasoning_content"] = reasoning
        if any(c["name"] == "final_answer" for c in calls):
            # smolagents ends with final_answer(answer=...): for a chat model that is simply the reply
            answer = calls[0]["arguments"].get("answer")
            if len(calls) != 1 or i != len(raw) - 1 or out["content"] or not isinstance(answer, str | int | float):
                return "final_answer_format"
            out["content"] = str(answer).strip()
        elif calls:
            if any(c["name"] not in names for c in calls):
                return "undeclared_tool"
            try:
                json.dumps(calls)
            except (TypeError, ValueError):
                return "call_format"
            out["tool_calls"] = [
                {"type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls
            ]
            pending = len(calls)
        msgs.append(out)
    if pending or msgs[-1]["role"] != "assistant" or msgs[-1].get("tool_calls"):
        return "unfinished"
    if not any(m.get("tool_calls") for m in msgs):
        return "no_tool_call"
    if not _is_french(" ".join(m["content"] for m in msgs if m["role"] == "user")):
        return "not_french"
    if len(msgs[-1]["content"].split()) < 2:
        return "one_word"
    if sum(len(m["content"]) for m in msgs) > 20000:
        return "too_long"
    for m in msgs:
        text = m["content"] + " " + m.get("reasoning_content", "")
        if _MARKUP.search(text):
            return "markup"
        if m["role"] != "tool" and _CJK.search(text):
            return "cjk"
        if m["role"] == "assistant" and (_CLAIM.search(text) or _REFUSAL.search(m["content"])):
            return "other_assistant"
    thinking = bool(msgs[-1].get("reasoning_content"))
    if not thinking:
        for m in msgs:
            m.pop("reasoning_content", None)
    used = {c["function"]["name"] for m in msgs for c in m.get("tool_calls", [])}
    tools = [t for t in tools if t["function"]["name"] in names]
    if not used <= {t["function"]["name"] for t in tools}:
        return "undeclared_tool"
    return [{"messages": msgs, "lang": "fr", "thinking": thinking, "tools": tools}]


# --------------------------------------------------------------------------------------------- registry

_RAW: dict[str, Callable[[dict], list[dict] | str]] = {
    "bird_medium": _bird_medium,
    "rag_glaive": _rag_glaive,
    "grounded_qa": _grounded_qa,
    "frenchqa": _frenchqa,
    "smol_rewrite": _smol_task("rewrite"),
    "smol_summarize": _smol_task("summarize"),
    "coedit": _coedit,
    "smol_smoltalk": _smol_smoltalk,
    "aya_fr": _aya_fr,
    "openthoughts": _openthoughts,
    "glaive_reasoning": _glaive_reasoning,
    "multilingual_thinking": _multilingual_thinking,
    "table_gpt": _table_gpt,
    "text_to_sql": _text_to_sql,
    "structured_extraction": _structured_extraction,
    "slides_officesmith": _slides_officesmith,
    "nemotron_fr": _nemotron_fr,
    "synth_fr": _synth_fr,
    "smoltalk2_fr": _smoltalk2_fr,
    "emails_fr_en": _emails_fr_en,
    "toolcall_fr": _toolcall_fr,
}


def why(name: str, row: dict) -> str:
    """Reason why `row` is skipped by source `name` ('' when it is kept). For probing and tests."""
    try:
        out = _RAW[name](row)
    except Exception as e:  # noqa: BLE001 - odd rows must never break the build
        return f"exception:{type(e).__name__}"
    return out if isinstance(out, str) else ""


def _safe(name: str) -> Callable[[dict], list[dict]]:
    def convert(row: dict) -> list[dict]:
        try:
            out = _RAW[name](row)
        except Exception:  # noqa: BLE001 - odd rows must never break the build
            return []
        return out if isinstance(out, list) else []

    return convert


def _src(name: str, repo: str, license: str, task: str, cap: int, **kw) -> Source:
    return Source(name=name, repo=repo, license=license, task=task, cap=cap, convert=_safe(name), **kw)


SOURCES: list[Source] = [
    _src(
        "bird_medium",
        "adubrou/bird-medium-sft",
        "apache-2.0",
        "office",
        12500,
        data_files="train.jsonl",
        scan=13000,
        note="own curated French business data; train.jsonl only (eval.jsonl is held out); identity rows dropped",
    ),
    _src(
        "rag_glaive",
        "glaiveai/RAG-v1",
        "apache-2.0",
        "rag_cited",
        12000,
        note="<co:n> citation markup rewritten as [n+1] after the cited span",
    ),
    _src(
        "grounded_qa",
        "LiquidAI/grounded-qa",
        "apache-2.0",
        "grounded_qa",
        3500,
        scan=4072,
        note="train split only (test splits are benchmarks); fr + en; about half unanswerable",
    ),
    _src(
        "frenchqa",
        "CATIE-AQ/frenchQA",
        "cc-by-4.0",
        "doc_qa",
        6000,
        scan=200617,
        note="translated SQuAD 2 only (PIAF excluded: benchmark); ~35 % unanswerable; file sorted by sub-dataset, hence the thinning",
    ),
    _src("smol_rewrite", "HuggingFaceTB/smoltalk", "apache-2.0", "rewrite", 10000, config="smol-rewrite"),
    _src("smol_summarize", "HuggingFaceTB/smoltalk", "apache-2.0", "summarize", 10000, config="smol-summarize"),
    _src(
        "coedit",
        "grammarly/coedit",
        "apache-2.0",
        "edit",
        5000,
        scan=69071,
        note="file sorted by task, hence the thinning",
    ),
    _src("smol_smoltalk", "HuggingFaceTB/smol-smoltalk", "apache-2.0", "chat", 12000),
    _src(
        "aya_fr",
        "CohereLabs/aya_dataset",
        "apache-2.0",
        "chat_fr",
        5000,
        scan=202362,
        note="human-written; only ~1 400 French rows exist",
    ),
    _src(
        "openthoughts",
        "open-thoughts/OpenThoughts3-1.2M",
        "apache-2.0",
        "reasoning",
        5000,
        scan=100000,
        data_files=[f"data/train-{i:05d}-of-00120.parquet" for i in range(110, 120)],
        note="science shards only: code and math reasoning is far above the 6 000-character limit",
    ),
    _src("glaive_reasoning", "glaiveai/reasoning-v1-20m", "apache-2.0", "reasoning", 6000),
    _src(
        "multilingual_thinking",
        "HuggingFaceH4/Multilingual-Thinking",
        "apache-2.0",
        "reasoning_chat",
        1000,
        scan=1000,
        note="French and English reasoning rows only (400 of 1 000)",
    ),
    _src("table_gpt", "LipengCS/Table-GPT", "mit", "table", 6000, config="All", scan=13222),
    _src("text_to_sql", "gretelai/synthetic_text_to_sql", "apache-2.0", "text_to_sql", 4000),
    _src(
        "structured_extraction",
        "LiquidAI/structured-extraction",
        "apache-2.0",
        "extraction",
        5000,
        scan=6000,
        note="train split only; fr + en",
    ),
    _src(
        "slides_officesmith",
        "adubrou/bird-m-sft",
        "apache-2.0",
        "slides",
        1000,
        data_files="open/slides_officesmith.jsonl",
        scan=850,
        note="BIRD-Deck JSON decks from Benitoow/OfficeSmith-PPTX-IR",
    ),
    _src(
        "nemotron_fr",
        "nvidia/Nemotron-Post-Training-Dataset-v2",
        "cc-by-4.0",
        "reasoning_fr",
        8000,
        split="multilingual_fr",
        scan=60000,
        note="gated; French prompts and answers, reasoning traces in English",
    ),
    _src(
        "synth_fr",
        "PleIAs/SYNTH",
        "cc-by-4.0",
        "knowledge_fr",
        8000,
        scan=400000,
        data_files=[f"synth_{i:03d}.parquet" for i in (1, 100, 200, 300, 400, 500)],
        note="6 of the 500 files (resolving them all is very slow); French is ~3 % of the rows; Wikipedia seeds are CC-BY-SA",
    ),
    _src(
        "smoltalk2_fr",
        "HuggingFaceTB/smoltalk2",
        "apache-2.0",
        "chat_fr",
        8000,
        config="SFT",
        split="smoltalk_multilingual_8languages_lang_5_no_think",
        scan=90000,
        note="French is ~1 row in 8 (stop-word check)",
    ),
    _src(
        "emails_fr_en",
        "sinabis-group/sinabis-100k-synthetic-emails",
        "cc-by-4.0",
        "emails",
        6000,
        scan=101000,
        note="email -> subject line only; the rows have no purpose/tone metadata for a faithful writing task",
    ),
    _src(
        "toolcall_fr",
        "CATIE-AQ/smoltalk2_smolagents_toolcalling_french",
        "apache-2.0",
        "tool_call",
        5000,
        scan=9100,
        note="French question and final answer, English tool traces; final_answer call turned into the reply",
    ),
]
