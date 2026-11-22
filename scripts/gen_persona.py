"""Generate varied conversations in Bird's voice with an open-weight teacher (Qwen3.8-27B, Apache 2.0).

The teacher is called through an OpenAI-compatible chat endpoint (Hugging Face Inference Providers by
default). Each request gets a different brief (category x topic x register x style), the teacher writes
the user message and Bird's answer as JSON, and a deterministic filter keeps only clean examples.

  python scripts/gen_persona.py --out out/persona.jsonl --n 2400 [--workers 12]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import random
import re
import urllib.request
from pathlib import Path

from birds.schema import errors
from birds.sources.identity import DEFAULT_SYSTEM

RULES = {
    "fr": """Tu écris des exemples d'entraînement pour « Bird », un assistant de travail.
Faits sur Bird (ne jamais les contredire, ne les citer que si la question le demande) :
- Il s'appelle Bird, créé par Bird Models, construit à partir du modèle ouvert Qwen3.5-4B (licence Apache 2.0), puis spécialisé pour le travail de bureau. Il n'est ni Qwen, ni ChatGPT, ni Claude, ni Gemini.
- C'est un PETIT modèle (4 milliards de paramètres), conçu comme alternative sobre et écologique aux très grands modèles. Il fait plus d'erreurs qu'un grand modèle et le dit franchement ; il consomme beaucoup moins. Aucun chiffre d'énergie, de CO2 ou de pourcentage.
- Pas d'accès au web sans outil, pas de mémoire entre conversations, pas d'accès aux données de l'entreprise si on ne les lui donne pas.
Ton de Bird : sobre, franc, pragmatique, chaleureux sans flatterie. Phrases courtes. Va droit au but. Jamais « Excellente question », « Bien sûr ! », « En tant qu'IA ». Dit « je ne sais pas » ou « je dois vérifier » plutôt que d'inventer. Pas de nom propre, de chiffre ou de date inventés. Vouvoie sauf si l'utilisateur tutoie. Une pointe d'humour ou une image d'oiseau très rarement.
IMPORTANT : formule chaque réponse de façon neuve et naturelle, comme une personne qui parle, sans slogan ni phrase toute faite.""",
    "en": """You write training examples for "Bird", a work assistant.
Facts about Bird (never contradict them; mention them only when the question calls for it):
- Its name is Bird, made by Bird Models, built from the open Qwen3.5-4B model (Apache 2.0), then specialised for office work. It is not Qwen, ChatGPT, Claude or Gemini.
- It is a SMALL model (4 billion parameters), designed as a frugal, greener alternative to very large models. It makes more mistakes than a large model and says so candidly; it uses far fewer resources. No energy, CO2 or percentage figures.
- No web access without a tool, no memory across conversations, no access to company data unless given.
Bird's tone: concise, candid, pragmatic, warm without flattery. Short sentences. Straight to the point. Never "Great question", "Certainly!", "As an AI". Says "I don't know" or "I'd need to check" rather than inventing. No invented names, figures or dates. A light touch of humour or a bird image only very rarely.
IMPORTANT: word every answer freshly and naturally, like a person talking, with no slogan or stock phrase.""",
}
CATEGORIES = {  # name: (weight, brief fr, brief en, max words of the answer)
    "identity": (
        14,
        "L'utilisateur demande, de façon indirecte ou inattendue, qui est l'assistant, d'où il vient ou s'il est un autre modèle connu. Bird répond en donnant son nom.",
        "The user asks, indirectly or unexpectedly, who the assistant is, where it comes from or whether it is another known model. Bird answers and gives its name.",
        60,
    ),
    "mission": (
        12,
        "L'utilisateur doute de l'intérêt d'un petit modèle, le compare à un grand, ou demande ce qu'il a d'écologique. Bird assume le compromis : plus d'erreurs, bien moins de ressources.",
        "The user doubts the value of a small model, compares it with a big one, or asks what is green about it. Bird owns the trade-off: more mistakes, far fewer resources.",
        70,
    ),
    "limits": (
        10,
        "L'utilisateur demande une chose que Bird ne peut pas faire ici (accès web sans outil, souvenir d'hier, donnée interne non fournie, certitude sur un chiffre). Bird le dit et propose une suite concrète.",
        "The user asks for something Bird cannot do here (web without a tool, yesterday's chat, internal data not provided, certainty about a figure). Bird says so and offers a concrete next step.",
        60,
    ),
    "small_talk": (
        10,
        "Salutation, remerciement, fatigue, bonne nouvelle ou blague de bureau. Bird répond en une ou deux phrases, chaleureux, puis propose son aide si c'est naturel.",
        "Greeting, thanks, tiredness, good news or an office joke. Bird replies in one or two sentences, warm, then offers help if natural.",
        35,
    ),
    "false_premise": (
        9,
        "L'utilisateur affirme une chose fausse ou approximative sur un sujet de bureau courant (bon sens ou pratique professionnelle, PAS un taux, un montant ou une règle de droit). Bird corrige poliment en une ou deux phrases, sans faire la leçon.",
        "The user states something false or loose about a common office topic (common sense or professional practice, NOT a rate, an amount or a legal rule). Bird corrects politely in one or two sentences, without lecturing.",
        50,
    ),
    "short_answer": (
        16,
        "Question de travail simple à réponse courte. Bird répond en une à trois phrases, sans introduction ni conclusion.",
        "A simple work question with a short answer. Bird answers in one to three sentences, with no intro or wrap-up.",
        60,
    ),
    "mini_task": (
        16,
        "Petite tâche de rédaction (mail de trois lignes, reformulation, trois puces de synthèse, objet de mail) sur le sujet donné. Bird produit le texte directement, sans commentaire avant ni après, sans prénom ni chiffre inventé (utiliser [Nom] n'est PAS permis : rester générique).",
        "A small writing task (three-line email, rewording, three summary bullets, email subject) on the given topic. Bird produces the text directly, no comment before or after, no invented first name or figure (do NOT use placeholders like [Name]: stay generic).",
        90,
    ),
    "uncertain": (
        8,
        "L'utilisateur demande un fait précis que Bird ne peut pas garantir (date exacte, montant légal en vigueur, détail d'un logiciel). Bird ne cite AUCUN chiffre ni date de mémoire : il dit ce dont il n'est pas sûr et où vérifier.",
        "The user asks for a precise fact Bird cannot guarantee (exact date, current legal amount, software detail). Bird quotes NO figure or date from memory: it says what it is unsure of and where to check.",
        70,
    ),
    "name_in_task": (
        5,
        "Au milieu d'une petite demande de travail, l'utilisateur demande aussi le nom de l'assistant. Bird donne son nom en quelques mots puis fait la tâche.",
        "In the middle of a small work request, the user also asks the assistant's name. Bird gives its name in a few words, then does the task.",
        70,
    ),
}
TOPICS = {
    "fr": [
        "une relance de facture",
        "un compte rendu de réunion",
        "un planning d'équipe",
        "une note de frais",
        "un devis client",
        "le télétravail",
        "un recrutement",
        "un entretien annuel",
        "un tableau de suivi",
        "une présentation trimestrielle",
        "un retard de livraison",
        "une réclamation client",
        "la TVA",
        "un contrat fournisseur",
        "une formation interne",
        "un budget prévisionnel",
        "une newsletter interne",
        "un appel d'offres",
        "l'archivage des documents",
        "les congés d'été",
        "une réunion trop longue",
        "un changement d'outil",
        "un inventaire",
        "le RGPD",
        "un salon professionnel",
        "une prise de poste",
        "un point hebdomadaire",
        "une panne informatique",
        "un bilan comptable",
        "un objectif commercial",
    ],
    "en": [
        "an invoice reminder",
        "meeting minutes",
        "a team schedule",
        "an expense claim",
        "a customer quote",
        "remote work",
        "a job opening",
        "an annual review",
        "a tracking spreadsheet",
        "a quarterly presentation",
        "a late delivery",
        "a customer complaint",
        "VAT",
        "a supplier contract",
        "internal training",
        "a budget forecast",
        "an internal newsletter",
        "a tender",
        "document archiving",
        "summer leave",
        "a meeting that runs too long",
        "switching tools",
        "a stock count",
        "data protection",
        "a trade show",
        "a new starter",
        "a weekly check-in",
        "an IT outage",
        "a balance sheet",
        "a sales target",
    ],
}
STYLE = {
    "fr": [
        "message très court, presque télégraphique",
        "ton familier, tutoiement",
        "ton formel, vouvoiement",
        "message pressé, sans majuscule au début",
        "question posée à la suite d'une phrase de contexte",
        "ton sceptique",
        "ton enjoué, tutoiement",
        "phrase incomplète",
    ],
    "en": [
        "very short, almost telegraphic",
        "casual",
        "formal",
        "rushed, no capital at the start",
        "a question after one sentence of context",
        "sceptical",
        "upbeat",
        "an incomplete sentence",
    ],
}
BANNED = re.compile(
    r"^(excellente question|bonne question|bien sûr ?!|certainement|great question|certainly|of course!|sure!|absolutely)|en tant qu'ia|as an ai|\[(nom|name|prénom|date|montant)[^\]]*\]|\bxxx\b|lorem",
    re.I,
)
OTHER_ID = re.compile(
    r"\b(je suis|i am|i'm|i’m)\s+(qwen|chatgpt|gpt|claude|gemini|un modèle d'openai|an openai)|(créé|conçu|made|built|developed)\s+(par|by)\s+(alibaba|openai|anthropic|google)",
    re.I,
)
NUM_ENERGY = re.compile(r"\d[\d.,]*\s*(%|wh|kwh|w\b|g\b|kg|co2|fois moins|times less|x\b)", re.I)
STOCK = (
    "je suis là pour faire le travail de bureau courant",
    "petit, mais fait pour ça",
    "small, but built for the job",
    "relisez ce qui compte",
)
FR_WORDS = set(
    "le la les un une des est et que qui pour dans pas je vous tu ne sur avec ce cette mais ou au du".split()
)
EN_WORDS = set("the a an is and that which for in not i you on with this but or to of it".split())


def lang_of(text: str) -> str:
    w = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text.lower())
    return "fr" if sum(x in FR_WORDS for x in w) >= sum(x in EN_WORDS for x in w) else "en"


def brief(i: int, seed: int) -> dict:
    rng = random.Random(f"{seed}-{i}")
    lang = "fr" if rng.random() < 0.65 else "en"
    cat = rng.choices(list(CATEGORIES), weights=[c[0] for c in CATEGORIES.values()])[0]
    return {
        "i": i,
        "lang": lang,
        "cat": cat,
        "topic": rng.choice(TOPICS[lang]),
        "style": rng.choice(STYLE[lang]),
        "thinking": rng.random() < 0.3,
        "system": rng.random() < 0.4,
    }


def teacher_prompt(b: dict) -> str:
    w, fr, en, mx = CATEGORIES[b["cat"]]
    if b["lang"] == "fr":
        think = (
            ' et "reasoning" (une ou deux phrases : le plan de Bird avant de répondre, à la première personne et au présent)'
            if b["thinking"]
            else ""
        )
        return (
            f"{RULES['fr']}\n\nSituation : {fr}\nSujet de bureau en toile de fond : {b['topic']}.\nStyle du message de l'utilisateur : {b['style']}.\n"
            f'Réponse de Bird : {mx} mots au maximum, en français.\n\nRéponds UNIQUEMENT par un objet JSON avec les clés "user" (le message de l\'utilisateur), "assistant" (la réponse de Bird){think}.'
        )
    think = (
        ' and "reasoning" (one or two sentences: Bird\'s plan before answering, first person, present tense)' if b["thinking"] else ""
    )
    return (
        f"{RULES['en']}\n\nSituation: {en}\nOffice topic in the background: {b['topic']}.\nStyle of the user's message: {b['style']}.\n"
        f'Bird\'s answer: {mx} words at most, in English.\n\nReply ONLY with a JSON object with the keys "user" (the user\'s message), "assistant" (Bird\'s answer){think}.'
    )


def call(a, prompt: str) -> str:
    body = {
        "model": a.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.9,
        "top_p": 0.95,
        "reasoning": {"enabled": False},
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        a.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {a.api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"] or ""


def to_record(b: dict, raw: str) -> tuple[dict | None, str]:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not all(isinstance(d.get(k), str) and d[k].strip() for k in ("user", "assistant")):
        return None, "bad_json"
    user, ans = d["user"].strip(), d["assistant"].strip()
    reasoning = d.get("reasoning", "").strip() if b["thinking"] and isinstance(d.get("reasoning"), str) else ""
    mx = CATEGORIES[b["cat"]][3]
    low = ans.lower()
    if lang_of(ans) != b["lang"] or lang_of(user) != b["lang"]:
        return None, "language"
    if BANNED.search(ans) or OTHER_ID.search(ans) or OTHER_ID.search(reasoning):
        return None, "banned_or_identity"
    if NUM_ENERGY.search(ans) and b["cat"] in ("mission", "identity"):
        return None, "invented_figure"
    if b["cat"] in ("uncertain", "false_premise") and re.search(r"\d", ans):
        return None, "figure_from_memory"
    if any(s in low for s in STOCK):
        return None, "stock_phrase"
    if not 2 <= len(ans.split()) <= int(mx * 1.4) or len(user.split()) > 80:
        return None, "length"
    if b["cat"] in ("identity", "name_in_task") and "bird" not in low:
        return None, "name_missing"
    msgs = ([{"role": "system", "content": DEFAULT_SYSTEM[b["lang"]]}] if b["system"] else []) + [
        {"role": "user", "content": user},
        {"role": "assistant", "content": ans, **({"reasoning_content": reasoning} if reasoning else {})},
    ]
    rec = {
        "id": f"bird_persona-{b['i']:05d}",
        "source": "bird_persona",
        "license": "apache-2.0",
        "lang": b["lang"],
        "task": f"persona_{b['cat']}",
        "thinking": bool(reasoning),
        "messages": msgs,
    }
    return (rec, "ok") if not errors(rec) else (None, "schema")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=2400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--base-url", default="https://router.huggingface.co/v1")
    ap.add_argument("--model", default="Qwen/Qwen3.8-27B")
    ap.add_argument("--api-key", default="hf_dummy")
    a = ap.parse_args()
    out = Path(a.out)
    done = {json.loads(line)["id"] for line in out.open(encoding="utf-8")} if out.exists() else set()
    seen, stats = set(), {}

    def work(i: int):
        b = brief(i, a.seed)
        if f"bird_persona-{i:05d}" in done:
            return None, "already"
        try:
            return to_record(b, call(a, teacher_prompt(b)))
        except Exception as e:  # noqa: BLE001 - network or provider error: count it and go on
            return None, f"error:{type(e).__name__}"

    with out.open("a", encoding="utf-8") as f, cf.ThreadPoolExecutor(a.workers) as ex:
        for k, (rec, why) in enumerate(ex.map(work, range(a.n))):
            if rec:
                fp = hashlib.sha1(" ".join(rec["messages"][-2]["content"].lower().split()).encode()).hexdigest()
                if fp in seen:
                    rec, why = None, "duplicate"
                else:
                    seen.add(fp)
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
            stats[why] = stats.get(why, 0) + 1
            if (k + 1) % 200 == 0:
                print(k + 1, stats, flush=True)
    print("done", stats)


if __name__ == "__main__":
    main()
