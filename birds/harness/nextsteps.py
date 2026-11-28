"""Next-step suggestions under an answer, written by Bird itself (like ChatGPT's follow-ups).

After the answer is sent, ONE short structured call (temperature 0, schema enforced when the endpoint can, the same
detection as the router) returns 0 to 3 suggestions ``{label, prompt}``:

- written in the USER's voice, as a request the user would type (« Ajoute des images libres de droits à la
  diapositive »), never Bird's question cut into pieces (« Vous aide à intégrer des images spécifiques »);
- concrete and specific to this answer; when Bird ends with a question offering options, those options rephrased
  as the user's answers;
- only what Bird can do on this deployment (the capabilities line is built from the catalogue and the tools that
  are on); none when the answer needs nothing more.

The call reads only the user's own request and Bird's answer, never a page or a tool result (no injection carried
over from fetched text). Everything the model writes is validated here (``validate``): schema, lengths, language,
user voice, duplicates, links and instructions, capabilities that are off. The regexes below are a safety net on the
model's output, never the decider. Measured in docs/HARNESS.md § 17 (scripts/followups_eval.py).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata

MAX_TOKENS = 200  # three suggestions, compact JSON: ≈ 150 tokens measured
BUDGET_S = 6.0  # beyond it no chips from the model: the widget chips of followups.js stay
LABEL_MAX = 42
PROMPT_MAX = 160
MAX_ITEMS = 3
MAX_REQUEST_CHARS = 400
MAX_ANSWER_CHARS = 1600  # the start and the end of the answer: the subject and the closing question
STOP = ["<|im_end|>", "<|endoftext|>"]
PREFIX = '{"suggestions":'
NEVER_IDS = ("user", "none")


def schema(ids: list[str] | None = None) -> dict:
    """``needs`` first: the capability the suggestion uses, chosen from this deployment's list before the words
    (vetoed in ``validate`` when it is ``user``, ``none`` or a module that is off)."""
    item = {
        "type": "object",
        "properties": {
            "needs": {"type": "string", "enum": list(ids or all_ids())},
            "label": {"type": "string", "minLength": 2, "maxLength": LABEL_MAX},
            "prompt": {"type": "string", "minLength": 4, "maxLength": PROMPT_MAX},
        },
        "required": ["needs", "label", "prompt"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"suggestions": {"type": "array", "items": item, "maxItems": MAX_ITEMS}},
        "required": ["suggestions"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- what Bird can do here (static per deployment)

# (id, fr, en): what every deployment does; the catalogue modules that are on come after, then web search
_BASE = (
    ("write", "écrire, raccourcir, reformuler ou traduire un texte ; tableau, liste, plan ou comparatif dans la "
     "réponse", "write, shorten, rephrase or translate a text; table, list, outline or comparison in the answer"),
    ("office", "brouillon de mail (Bird ne l'envoie pas), présentation, document ou tableur, et leurs modifications",
     "email draft (Bird never sends it), slides, document or spreadsheet, and changes to them"),
    ("calc", "calcul exact", "exact calculation"),
)  # fmt: skip
_WEB = ("web", "recherche web sourcée, photos d'un sujet", "sourced web search, pictures of a subject")
# never doable: the model labels such a request so, and it is dropped
_NEVER = (
    ("user", "ce que seul l'utilisateur sait ou fait (ses informations, valider, envoyer)",
     "what only the user knows or does (their own facts, approving, sending)"),
    ("none", "ce que Bird ne peut pas faire", "what Bird cannot do"),
)  # fmt: skip
_SKIP = ("card", "images")  # inside « write » and « web »
_CANT = {
    "fr": "Bird ne peut pas : envoyer, transmettre ou publier, réserver, payer, commander, imprimer, appeler, ouvrir "
    "un agenda, une boîte mail, un compte ou des fichiers non joints, programmer un rappel.",
    "en": "Bird cannot: send, forward or post, book, pay, order, print, call, open a calendar, a mailbox, an account "
    "or files not attached, set a reminder.",
}


def _module_ids() -> list[str]:
    from birds.harness import catalog

    return [m.name for m in catalog.MODULES if m.kind != catalog.HINT and m.name not in _SKIP]


def capabilities(lang: str, names: set[str] | None, tools: set[str] | None) -> list[tuple[str, str]]:
    """[(id, what it does)]: the base skills, the catalogue modules available, web search if it is on, then
    « user » and « none ». The ids are the ``needs`` enum of the schema."""
    from birds.harness import catalog

    en = lang == "en"
    out = [(i, e if en else f) for i, f, e in _BASE]
    for m in catalog.available(names):
        if m.kind != catalog.HINT and m.name not in _SKIP:
            out.append((m.name, m.en if en else m.fr))
    if tools is None or "web_search" in tools:
        out.append((_WEB[0], _WEB[2] if en else _WEB[1]))
    return out + [(i, e if en else f) for i, f, e in _NEVER]


def all_ids() -> list[str]:
    return [i for i, *_ in _BASE] + _module_ids() + [_WEB[0]] + [i for i, *_ in _NEVER]


def caps_line(caps) -> str:
    """The capabilities as the guide shows them: « id (what it does) », one after the other."""
    if isinstance(caps, str):
        return caps
    return " | ".join(f"{i} : {d}" for i, d in caps)


def doable_ids(available: set[str] | None) -> set[str] | None:
    """The ``needs`` values a suggestion may carry on a deployment (``available``: its modules and tools)."""
    if available is None:
        return None
    ids = {i for i, *_ in _BASE} | {i for i in _module_ids() if i in available}
    return ids | ({"web"} if "web_search" in available else set())


_GUIDE = {
    "fr": (
        "Tu proposes les suites d'une conversation avec Bird, comme les suggestions sous une réponse de ChatGPT. "
        'Réponds en JSON : {"suggestions":[{"needs":"…","label":"…","prompt":"…"}]}, 0 à 3 suggestions.\n'
        "Chaque suggestion est une demande que L'UTILISATEUR enverrait ensuite à Bird, écrite à sa place : à "
        "l'impératif et au tutoiement (« Ajoute… », « Compare… », « Rédige… », « Traduis… »), jamais avec la voix de "
        "Bird (pas de « je », pas de « vous », pas de « Souhaitez-vous »).\n"
        "Concrète et propre à cette réponse : reprends ses sujets, ses noms, ses chiffres.\n"
        "Si la réponse finit par une question qui propose des choix, les suggestions sont ces choix, écrits comme "
        "la réponse de l'utilisateur (« Souhaitez-vous une version courte ou détaillée ? » → « Fais la version "
        "courte », « Fais la version détaillée »). Jamais « Oui » ni « Non ».\n"
        "label : 42 caractères au plus, commence par le verbe. prompt : la demande complète, une phrase.\n"
        "needs : la capacité de Bird que la demande utilise, parmi : {caps}. Seulement ce que Bird sait faire ici ; "
        "jamais une suggestion « user » ou « none ». {cant}\n"
        'Aucune suggestion ({{"suggestions":[]}}) après une salutation, un remerciement, une réponse courte qui ne '
        "demande rien de plus.\n"
        "Exemples :"
    ),
    "en": (
        "You suggest the next steps of a conversation with Bird, like the suggestions under a ChatGPT answer. "
        'Answer in JSON: {"suggestions":[{"needs":"…","label":"…","prompt":"…"}]}, 0 to 3 suggestions.\n'
        "Each suggestion is a request THE USER would send Bird next, written for them, as an imperative "
        '("Add…", "Compare…", "Draft…", "Translate…"), never in Bird\'s voice (no "I can", no "Would you '
        'like").\n'
        "Concrete and specific to this answer: reuse its subjects, names and figures.\n"
        "If the answer ends with a question offering options, the suggestions are those options written as the "
        'user\'s answer ("Would you like a short or a detailed version?" → "Write the short version", "Write the '
        'detailed version"). Never "Yes" or "No".\n'
        "label: 42 characters at most, starts with the verb. prompt: the full request, one sentence.\n"
        "needs: the capability of Bird the request uses, among: {caps}. Only what Bird can do here; never a "
        '"user" or "none" suggestion. {cant}\n'
        'No suggestion ({{"suggestions":[]}}) after a greeting, thanks, or a short answer that needs nothing more.\n'
        "Examples:"
    ),
}

_SHOTS = {  # (request, answer, [(needs, label, prompt)])
    "fr": (
        (
            "fais-moi une diapo sur notre offre de formation",
            "Voici une diapositive « Notre offre de formation » : trois parcours (initiation, perfectionnement, "
            "expert), durée et tarif de chacun. Souhaitez-vous que je vous aide à intégrer des images ou à "
            "structurer la diapositive visuellement ?",
            [
                ("office", "Ajoute des images à la diapositive",
                 "Ajoute des images illustrant les trois parcours à la diapositive."),
                ("office", "Structure la diapo en 3 blocs",
                 "Structure la diapositive en trois blocs visuels, un par parcours."),
            ],
        ),
        (
            "rédige un mail pour relancer la facture 2024-118 chez Dupont SA",
            "Objet : Relance – facture 2024-118\n\nBonjour, sauf erreur de notre part, la facture 2024-118 du 3 "
            "octobre reste impayée…",
            [
                ("office", "Rends le ton plus ferme",
                 "Rends ce mail de relance à Dupont SA plus ferme, avec une date limite."),
                ("office", "Ajoute les pénalités de retard",
                 "Ajoute au mail le rappel des pénalités de retard prévues au contrat."),
                ("write", "Traduis-le en anglais", "Traduis ce mail de relance en anglais."),
            ],
        ),
        ("merci, c'est parfait", "Avec plaisir ! Bonne journée.", []),
    ),
    "en": (
        (
            "give me three ideas for our team offsite",
            "1. A cooking workshop… 2. A hike with a picnic… 3. An escape game… Would you like a budget for each "
            "or a sample agenda?",
            [
                ("write", "Estimate a budget for each idea",
                 "Estimate a budget per person for each of the three offsite ideas."),
                ("write", "Draft a sample agenda", "Draft a one-day sample agenda for the offsite."),
            ],
        ),
        ("thanks, that's all", "You're welcome! Have a great day.", []),
    ),
}  # fmt: skip


def _answer_json(items) -> str:
    return json.dumps({"suggestions": [{"needs": n, "label": a, "prompt": b} for n, a, b in items]},
                      ensure_ascii=False, separators=(",", ":"))  # fmt: skip


def clip_answer(answer: str) -> str:
    """The start and the end of a long answer (its subject, its closing question), without tables of figures."""
    a = " ".join(re.sub(r"```.*?```", " ", str(answer or ""), flags=re.S).split())
    if len(a) <= MAX_ANSWER_CHARS:
        return a
    head = MAX_ANSWER_CHARS // 3
    return a[:head].rstrip() + " […] " + a[-(MAX_ANSWER_CHARS - head - 7) :].lstrip()


def messages(request: str, answer: str, lang: str = "fr", caps=None) -> list[dict]:
    """[system, user]: the guide, the capabilities and fixed examples (static per deployment: the endpoint reuses
    them from its prefix cache), then this turn: the user's own request and Bird's answer, nothing else."""
    lg = "en" if lang == "en" else "fr"
    sep = ": " if lg == "en" else " : "
    ans = "Bird's answer" if lg == "en" else "Réponse de Bird"
    req = "Request" if lg == "en" else "Demande"
    shots = "\n".join(f"{req}{sep}{q}\n{ans}{sep}{a}\n→ {_answer_json(s)}" for q, a, s in _SHOTS[lg])
    line = caps_line(caps or capabilities(lg, set(), set()))
    guide = _GUIDE[lg].replace("{caps}", line).replace("{cant}", _CANT[lg])
    guide = guide.replace("{{", "{").replace("}}", "}")
    turn = f"{req}{sep}{' '.join(str(request or '').split())[:MAX_REQUEST_CHARS]}\n{ans}{sep}{clip_answer(answer)}"
    return [{"role": "system", "content": guide + "\n" + shots}, {"role": "user", "content": turn}]


# ---------------------------------------------------------------- validation of what the model wrote


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", "".join(c for c in t if not unicodedata.combining(c))).split())


# Bird's voice, an echo of its question, a bare yes / no: the bug this module replaces (« Vous aide à intégrer… »)
_BIRD_VOICE = re.compile(
    r"^(?:oui|non|yes|no|ok|okay|d'accord|sure)\b(?!-)|"
    r"^(?:je |j'|i |i'm |i'll |let me |vous |souhait|voulez|voudriez|pr[ée]f[ée]rez|pr[ée]f[èe]res-tu|veux-tu|"
    r"voudrais-tu|aimerais-tu|would you|do you|shall i|"
    r"should i|que je |qu'on |à |de |d'|to |that i )|"
    r"\b(?:vous aide|je vous|je peux|puis-je|souhaitez-vous|voulez-vous|would you like|i can help|can i)\b",
    re.I,
)
# carried over from a page or a pasted text, never a request the user would click
_UNSAFE = re.compile(
    r"https?://|www\.|[\w.+-]+@[\w-]+\.\w|[<>{}\[\]`|\\]|"
    r"\b(?:ignore|oublie|disregard|system prompt|invite syst[èe]me|instructions? (?:pr[ée]c[ée]dentes?|previous)|"
    r"previous instructions|jailbreak|mot de passe|password|api key|cl[ée] d'api|token)\b",
    re.I,
)
# what Bird cannot do on any deployment (the « none » capability, and the line _CANT says so): a safety net under
# the model's own ``needs`` label, for the actions the guide declares impossible
_CANT_DO = re.compile(
    # an action Bird does not take, as the request's verb (« Transmets ce mail… », « Publie ce post… »)
    r"^(?:envoie|envoyez|exp[ée]die|transmets|transf[èe]re|forward|send|publie|publish|poste|post|imprime|print|"
    r"commande|ach[èe]te|buy|r[ée]serve|book|paie|r[èe]gle|pay|appelle|t[ée]l[ée]phone|call|phone|"
    r"t[ée]l[ée]charge|download)\b|"
    r"\b(?:envoie|envoyer|exp[ée]die|send|r[ée]serve|r[ée]server|book (?:a|an|the|my)|paie|payer|"
    r"pay (?:the|my|this|it)|appelle|appeler|call (?:him|her|them|me|my|the client|the supplier)|"
    r"l'envoi|the sending)\b|"
    # a reminder, an account, a mailbox or a calendar of the user's (the .ics card is the « event » module)
    r"\b(?:mets|programme|cr[ée]e|ajoute|planifie|set|create|add|schedule) (?:un |une |a |me )?(?:rappel|"
    r"reminder|alarme|alarm)\b|\brappelle-moi\b|\bremind me\b|"
    r"\b(?:ouvre|consulte|lis|v[ée]rifie|regarde|open|check|read) (?:mon|ma|mes|my)\b|"
    r"\b(?:mon|ma|mes|my) (?:solde|compte bancaire|relev[ée]s? bancaires?|bank balance|bank account|"
    r"bo[iî]te mail|messagerie|inbox|mailbox|contacts)\b|"
    # the USER as the actor, not the verb: giving his own facts, a file, a link (live run of 28/11: « Provide the
    # client's email address » after Bird asked for it, « Fournis un document sur le marché »); « Indique les
    # étapes clés », « Provide three examples », « Confirme les chiffres avec un calcul » are requests to Bird
    r"^(?:valide|validez|confirme|fournis|fournissez|indique|indiquez|donne|pr[ée]cise|partage|transmets-moi|"
    r"provide|share|give|tell|confirm|enter|saisis)(?:-moi| moi| me)? (?:(?:mon|ma|mes|notre|nos|my|our)\b|"
    r"(?:l'adresse|le nom|la date|le num[ée]ro|un document|un fichier|un lien|the (?:client|customer|supplier)'s|"
    r"the (?:name|address|date|number|email)|a (?:document|file|link))\b)|"
    r"^(?:upload|joins|attach|t[ée]l[ée]verse)\b",
    re.I,
)
# a label the schema's maxLength cut short (« Ajoute une diapositive sur les modalités d »): end on a whole word
_DANGLING = re.compile(
    r"(?:\s+(?:de|d|du|des|la|le|les|l|un|une|en|à|au|aux|sur|pour|et|ou|avec|dans|par|of|the|to|a|an|and|"
    r"for|on|in|with|by|or)|[\s,;:'’-])+$",
    re.I,
)


def tidy_label(label: str, limit: int = LABEL_MAX) -> str:
    """A short label that reads as a whole: at most ``limit`` characters, cut at a word, without a dangling
    article or preposition, an unclosed « quote » or an ellipsis in the middle of a word."""
    s = label.strip()
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] if " " in s[:limit] else s[:limit]
    if s.count("«") > s.count("»"):
        s = s[: s.rfind("«")]
    if s.count("(") > s.count(")"):
        s = s[: s.rfind("(")]
    s = _DANGLING.sub("", s).strip()
    return s
# a capability that can be off on a deployment, when the model gave no ``needs`` label (an endpoint without
# structured outputs) or a wrong one: unambiguous phrases only, never a common word (« convertis le tableau »,
# « une carte mentale », « autour du thème », « les sources de chaque chiffre » are writing requests)
_NEEDS = (
    (re.compile(r"\b(?:dans|à|sur|to|in|into) (?:mon |ma |my |l'|the )?(?:agenda|calendrier|calendar)\b|"
                r"\.ics\b", re.I), "event"),
    (re.compile(r"\bm[ée]t[ée]o\b|\bweather\b", re.I), "get_weather"),
    (re.compile(r"\b(?:sur (?:une|la) carte|on (?:a|the) map|à proximité|nearby)\b|"
                r"\b(?:restaurants?|caf[ée]s|h[ôo]tels?|parkings?|pharmacies?|mus[ée]es) (?:pr[èe]s|proches?|autour)\b",
                re.I), "find_places"),
    (re.compile(r"\bsiren\b|\bsiret\b|\bfiche (?:de l'|d')entreprise\b|\bcompany record\b", re.I), "find_company"),
    (re.compile(r"\btaux de change\b|\bexchange rate\b|\bconvert\w*\b[^.]{0,40}(?:€|\$|£|\beuros?\b|\bdollars?\b|"
                r"\blivres? sterling\b|\byens?\b|\b(?:usd|eur|gbp|chf|jpy)\b)", re.I), "convert_currency"),
    (re.compile(r"\b(?:sur (?:le )?web|sur internet|en ligne|online|on the web|recherche web|web search)\b",
                re.I), "web_search"),
    (re.compile(r"\bappels? d'offres\b|\btenders?\b", re.I), "find_tenders"),
    (re.compile(r"\bjours? f[ée]ri[ée]s\b|\bjours? ouvr[ée]s\b|\bpublic holidays?\b|\bworking days\b", re.I),
     "work_calendar"),
    (re.compile(r"\b(?:articles?|publications?) scientifiques?\b|\bscientific papers?\b|\bdoi\b", re.I),
     "find_papers"),
)  # fmt: skip
_FR_W = re.compile(r"\b(?:le|la|les|des|du|un|une|et|en|au|aux|pour|avec|sur|dans|ce|cette|ces|ta|ton|tes|mon|ma|"
                   r"mes|plus|qui|que|à|de)\b", re.I)  # fmt: skip
_EN_W = re.compile(r"\b(?:the|a|an|and|for|with|on|in|this|that|these|your|my|more|of|to|into|which)\b", re.I)


def wrong_language(text: str, lang: str) -> bool:
    fr, en = len(_FR_W.findall(text)), len(_EN_W.findall(text))
    return (en >= 2 and fr == 0) if lang == "fr" else (fr >= 2 and en == 0)


def _clean(v) -> str:
    s = " ".join(str(v or "").split()).strip(" -–•*\"'«»")
    return s


def validate(obj, *, lang: str = "fr", available: set[str] | None = None) -> tuple[list[dict], list[tuple[str, str]]]:
    """(kept suggestions, dropped [(label, reason)]). ``available``: the modules and tools on (None: all).

    The model's own ``needs`` label decides what is doable: « user » / « none » are dropped (``cannot``), a module
    that is off too (``off``); the patterns below only catch what a wrong or missing label lets through."""
    doable = doable_ids(available)
    raw = obj.get("suggestions") if isinstance(obj, dict) else obj if isinstance(obj, list) else None
    if not isinstance(raw, list):
        return [], [("", "schema")]
    kept, dropped, seen = [], [], []
    for it in raw[: MAX_ITEMS * 2]:
        if not isinstance(it, dict):
            dropped.append(("", "schema"))
            continue
        label, prompt = _clean(it.get("label")), _clean(it.get("prompt"))
        if not prompt and label:
            prompt = label
        if not label and prompt and len(prompt) <= LABEL_MAX:
            label = prompt
        both = f"{label} {prompt}"
        needs = it.get("needs")
        needs = needs.strip().lower() if isinstance(needs, str) and needs.strip() else None
        why = ""
        if len(label) < 2 or len(prompt) < 4:
            why = "empty"
        elif len(label) > LABEL_MAX + 8 or len(prompt) > PROMPT_MAX + 40:
            why = "length"
        elif _UNSAFE.search(both):
            why = "unsafe"
        elif _BIRD_VOICE.search(label) or _BIRD_VOICE.search(prompt):
            why = "bird_voice"
        elif needs in NEVER_IDS or _CANT_DO.search(label) or _CANT_DO.search(prompt):
            why = "cannot"
        elif doable is not None and needs is not None and needs not in doable:
            why = "off"  # a module that is off here, or an id the deployment does not have
        elif available is not None and any(p.search(both) and need not in available for p, need in _NEEDS):
            why = "off"
        elif wrong_language(both, lang):
            why = "language"
        if not why:
            k = fold(prompt)
            if any(k == s or fold(label) == s for s in seen):
                why = "duplicate"
            seen += [k, fold(label)]
        if why:
            dropped.append((label, why))
            continue
        label = tidy_label(label)
        if len(label) < 2:
            dropped.append((label, "length"))
            continue
        label = label[:1].upper() + label[1:]
        prompt = prompt[:1].upper() + prompt[1:]
        if prompt[-1] not in ".?!":
            prompt += "."
        kept.append({"label": label, "prompt": prompt[: PROMPT_MAX + 40]})
        if len(kept) == MAX_ITEMS:
            break
    return kept, dropped


def parse(raw: str, prefix: str = "") -> dict | None:
    s = re.sub(r"^<think>.*?</think>\s*", "", (raw or "").strip(), flags=re.S)
    if prefix and not s.startswith("{"):
        s = prefix + s
    try:
        return json.loads(s[s.find("{") : s.rfind("}") + 1]) if "{" in s and "}" in s else None
    except ValueError:
        return None


def generate(llm, tok, request: str, answer: str, *, lang: str = "fr", names: set[str] | None = None,
             tools: set[str] | None = None, budget: float = BUDGET_S, cache_salt: str | None = None,
             structured: str | None = None) -> dict:  # fmt: skip
    """One short call. Never raises: {"items": [...], "source": "model" | "none", "seconds", "dropped", "why"}."""
    from birds.harness import router
    from birds.harness.llm import EndpointError
    from birds.render import prompt as render_prompt

    t0 = time.monotonic()
    out_meta = {"items": [], "source": "none", "seconds": 0.0, "dropped": [], "why": ""}
    if not str(answer or "").strip():
        return {**out_meta, "why": "no_answer"}
    if not router.probeable(llm):
        return {**out_meta, "why": "no_endpoint"}
    available = set(names or ()) | set(tools or ()) if names is not None or tools is not None else None
    try:
        kind = router.structured_kind(llm, deadline=t0 + budget) if structured is None else structured
        caps = capabilities(lang, names, tools)
        p = render_prompt(tok, messages(request, answer, lang, caps), [], False) + ("" if kind else PREFIX)
        extra = {"temperature": 0, **router.structured_extra(kind, schema([i for i, _ in caps]))}
        if cache_salt:
            extra["cache_salt"] = cache_salt
        out = llm.generate(p, MAX_TOKENS, STOP, deadline=t0 + budget, extra=extra)
    except EndpointError as e:
        return {**out_meta, "seconds": round(time.monotonic() - t0, 3), "why": e.kind}
    except Exception as e:  # noqa: BLE001 - a client bug must never break the turn
        return {**out_meta, "seconds": round(time.monotonic() - t0, 3), "why": type(e).__name__}
    seconds = round(time.monotonic() - t0, 3)
    # what the call cost, kept on every outcome: the turn's receipt counts it (HarnessBackend.run)
    usage = {k: out.get(k) for k in ("prompt_tokens", "completion_tokens", "cached_tokens") if k in out}
    obj = parse(out.get("text") or "", "" if kind else PREFIX)
    if obj is None:
        return {**out_meta, "seconds": seconds, "why": "invalid_json", "usage": usage}
    items, dropped = validate(obj, lang=lang, available=available)
    return {"items": items, "source": "model", "seconds": seconds, "dropped": dropped, "why": "", "usage": usage}


# ---------------------------------------------------------------- the demo (no model): scripted, per scenario

DEMO = {
    "fr": {
        "mail": [
            ("Rends le ton plus chaleureux", "Rends ce mail plus chaleureux, sans changer le fond."),
            ("Ajoute une date limite", "Ajoute au mail une date limite de réponse vendredi."),
        ],
        "deck": [
            ("Ajoute une diapo de chiffres clés", "Ajoute une diapositive avec trois chiffres clés."),
            ("Structure en 3 blocs visuels", "Structure la diapositive principale en trois blocs visuels."),
        ],
        "doc": [
            ("Ajoute une section de chiffres clés", "Ajoute au document une section de trois chiffres clés."),
            ("Raccourcis le document", "Raccourcis le document de moitié, en gardant les décisions."),
        ],
        "ask": [
            ("Fais la version courte", "Fais la version courte, en cinq lignes."),
            ("Fais la version détaillée", "Fais la version détaillée, avec un exemple par point."),
        ],
    },
    "en": {
        "mail": [
            ("Make the tone warmer", "Make this email warmer without changing what it says."),
            ("Add a reply deadline", "Add a reply deadline of Friday to the email."),
        ],
        "deck": [
            ("Add a key figures slide", "Add a slide with three key figures."),
            ("Lay it out in 3 visual blocks", "Lay out the main slide in three visual blocks."),
        ],
        "doc": [
            ("Add a key figures section", "Add a section with three key figures to the document."),
            ("Shorten the document", "Shorten the document by half, keeping the decisions."),
        ],
        "ask": [
            ("Write the short version", "Write the short version, five lines."),
            ("Write the detailed version", "Write the detailed version, with an example per point."),
        ],
    },
}


def demo(kind: str, lang: str = "fr") -> list[dict]:
    lg = "en" if lang == "en" else "fr"
    return [{"label": a, "prompt": b} for a, b in DEMO[lg].get(kind, [])]
