"""A conversation's title, summarised by the model after its first answer (one short structured call).

The sidebar used to show the first words of the first question (« Écris un mail à mon propriéta… »): every mail
conversation looked the same. The model reads the question and the start of the answer and proposes a short noun
phrase (« Fuite dans la salle de bains »); the output is parsed and checked here (``clean``), and anything unusable
gives ``""`` so the app keeps its fallback (the start of the question). A mail drafted in that answer needs no call:
its subject is the title (taken from the result, not written by the model).
"""

from __future__ import annotations

import json
import re
import time

MAX_TOKENS = 24
BUDGET_S = 4.0
MAX_CHARS = 60
STOP = ["<|im_end|>", "<|endoftext|>", "\n"]
PREFIX = '{"title":"'

_GUIDE = {
    "fr": (
        "Tu donnes un titre à une conversation, pour la liste des conversations. Réponds en JSON : "
        '{"title": …}. Le titre : 2 à 6 mots, en français, sans guillemets, sans point final, sans emoji, qui '
        "dit le sujet précis (pas « Question », pas « Demande d'aide »).\n"
        "Exemples :\n"
        'Question : Écris un mail à mon propriétaire pour la fuite sous l\'évier → {"title": "Fuite sous l\'évier"}\n'
        'Question : c\'est quoi la différence entre un PEA et une assurance vie ? → {"title": "PEA ou assurance vie"}\n'
        'Question : fais une présentation sur le vélo en ville → {"title": "Le vélo en ville"}'
    ),
    "en": (
        'You title a conversation for the list of conversations. Answer in JSON: {"title": …}. The title: 2 to 6 '
        "words, in English, no quotes, no final full stop, no emoji, naming the precise subject (not « Question », "
        "not « Help request »).\n"
        "Examples:\n"
        'Question: Write an email to my landlord about the leak under the sink → {"title": "Leak under the sink"}\n'
        'Question: what is the difference between an ISA and a pension? → {"title": "ISA or pension"}\n'
        'Question: make a deck about cycling in cities → {"title": "Cycling in cities"}'
    ),
}


def schema() -> dict:
    return {
        "type": "object",
        "properties": {"title": {"type": "string", "minLength": 3, "maxLength": MAX_CHARS}},
        "required": ["title"],
        "additionalProperties": False,
    }


def messages(question: str, answer: str, lang: str = "fr") -> list[dict]:
    lg = "en" if lang == "en" else "fr"
    q = " ".join((question or "").split())[:500]
    a = " ".join((answer or "").split())[:400]
    label = ("Question: ", "Start of the answer: ") if lg == "en" else ("Question : ", "Début de la réponse : ")
    return [
        {"role": "system", "content": _GUIDE[lg]},
        {"role": "user", "content": f"{label[0]}{q}\n{label[1]}{a}"},
    ]


def clean(raw: str) -> str:
    """The title, checked (same rules as conversation-data.js cleanTitle), or ''."""
    s = next((ln for ln in str(raw or "").splitlines() if ln.strip()), "")
    s = re.sub(r"^\s*(?:titre|title)\s*:\s*", "", s, flags=re.I)
    s = re.sub(r"[*_`#>]+", "", s)
    s = re.sub(r"^[\s\"'«“‘(\[]+|[\s\"'»”’)\].,;:!]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 3 or len(s) > MAX_CHARS or len(s.split()) > 9 or re.search(r"https?:|[<>{}]", s):
        return ""
    return s[0].upper() + s[1:]


def parse(raw: str, prefix: str = "") -> str:
    s = re.sub(r"^<think>.*?</think>\s*", "", (raw or "").strip(), flags=re.S)
    if prefix and not s.startswith("{"):
        s = prefix + s
        if not s.rstrip().endswith("}"):
            s = s.rstrip().rstrip('"') + '"}'
    try:
        obj = json.loads(s[s.find("{") : s.rfind("}") + 1]) if "{" in s and "}" in s else None
    except ValueError:
        obj = None
    return clean(obj.get("title", "")) if isinstance(obj, dict) and isinstance(obj.get("title"), str) else ""


def from_result(draft: dict | None) -> str:
    """A mail drafted in the answer: its subject is the conversation's title."""
    return clean(str((draft or {}).get("subject") or "")) if isinstance(draft, dict) else ""


def propose(llm, tok, question: str, answer: str, *, lang: str = "fr", cache_salt: str | None = None) -> dict:
    """{"title": str, "source": "model" | "none", "reason"?: str, "usage"?: dict}. Never raises."""
    from birds.harness import router
    from birds.harness.llm import EndpointError
    from birds.render import prompt as render_prompt

    t0 = time.monotonic()
    if llm is None or tok is None or not router.probeable(llm):
        return {"title": "", "source": "none", "reason": "no_endpoint"}
    try:
        kind = router.structured_kind(llm, deadline=t0 + BUDGET_S)
        p = render_prompt(tok, messages(question, answer, lang), [], False) + ("" if kind else PREFIX)
        extra = {"temperature": 0, **router.structured_extra(kind, schema())}
        if cache_salt:
            extra["cache_salt"] = cache_salt
        out = llm.generate(p, MAX_TOKENS, STOP, deadline=t0 + BUDGET_S, extra=extra)
    except EndpointError as e:
        return {"title": "", "source": "none", "reason": e.kind}
    except Exception as e:  # noqa: BLE001 - a title is never worth an error
        return {"title": "", "source": "none", "reason": type(e).__name__}
    title = parse(out.get("text") or "", "" if kind else PREFIX)
    usage = {k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "seconds") if k in out}
    if not title:
        return {"title": "", "source": "none", "reason": "invalid", "usage": usage}
    return {"title": title, "source": "model", "usage": usage}
