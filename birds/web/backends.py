"""Chat backends behind one small protocol.

A backend exposes ``kind``, ``model``, ``tools`` and a blocking ``run(request, ctx)``.
It reports progress only through ``ctx`` (``emit``, ``confirm``, ``sleep``), so the HTTP
layer in ``server.py`` never needs to know which backend is in use.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

Event = dict[str, Any]

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sanitize_filename(name: str) -> str:
    """Reduce an arbitrary name to a safe basename (letters, digits, ``._-``)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.")
    base = re.sub(r"\.{2,}", ".", base)[:120]
    return base if base and SAFE_NAME.match(base) else "fichier"


class Cancelled(Exception):
    """Raised inside a backend when the client went away or pressed stop."""


class ConfirmRegistry:
    """Pending human confirmations, resolved by ``POST /api/confirm``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, list[bool]]] = {}

    def create(self) -> str:
        cid = uuid.uuid4().hex
        with self._lock:
            self._pending[cid] = (threading.Event(), [False])
        return cid

    def pending(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    def resolve(self, cid: str, allow: bool) -> bool:
        with self._lock:
            entry = self._pending.get(cid)
        if entry is None:
            return False
        entry[1][0] = bool(allow)
        entry[0].set()
        return True

    def wait(self, cid: str, cancel: threading.Event, timeout: float) -> bool:
        with self._lock:
            event, box = self._pending[cid]
        deadline = time.monotonic() + timeout
        try:
            while not event.wait(0.05):
                if cancel.is_set():
                    raise Cancelled
                if time.monotonic() > deadline:
                    return False
            return box[0]
        finally:
            with self._lock:
                self._pending.pop(cid, None)


@dataclass
class ChatRequest:
    messages: list[dict[str, str]]
    thinking: bool = False
    lang: str = "fr"


@dataclass
class RunContext:
    emit: Callable[[Event], None]
    confirms: ConfirmRegistry
    cancel: threading.Event
    workspace: Path
    confirm_timeout: float = 300.0

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled

    def sleep(self, seconds: float) -> None:
        if seconds > 0 and self.cancel.wait(seconds):
            raise Cancelled
        self.check()

    def confirm(self, tool: str, arguments: dict[str, Any], reason: str) -> bool:
        """Emit a ``confirm`` event and block until the user answers (deny on timeout)."""
        cid = self.confirms.create()
        self.emit({"type": "confirm", "id": cid, "tool": tool, "arguments": arguments, "reason": reason})
        return self.confirms.wait(cid, self.cancel, self.confirm_timeout)


class Backend(Protocol):
    kind: str  # "demo" | "completions" | "local"
    model: str
    tools: list[str]

    def run(self, request: ChatRequest, ctx: RunContext) -> None: ...


def step_event(
    index: int,
    tool: str,
    arguments: dict[str, Any],
    status: str,
    summary: str = "",
    seconds: float = 0.0,
    flags: list[str] | None = None,
) -> Event:
    return {
        "type": "step",
        "index": index,
        "tool": tool,
        "arguments": arguments,
        "status": status,
        "summary": summary,
        "seconds": round(float(seconds), 2),
        "flags": list(flags or []),
    }


def usage_event(
    *,
    model: str,
    thinking: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    seconds: float = 0.0,
    tool_calls: int = 0,
    bytes_fetched: int = 0,
    energy_wh: float | None = None,
    energy_kind: str | None = None,
) -> Event:
    if energy_wh is None or energy_kind not in ("measured", "estimated"):
        energy_wh, energy_kind = None, None
    return {
        "type": "usage",
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "seconds": round(float(seconds), 2),
        "tool_calls": int(tool_calls),
        "bytes_fetched": int(bytes_fetched),
        "energy_wh": energy_wh,
        "energy_kind": energy_kind,
        "co2_g": None,  # filled by the server only when a grid intensity is configured
        "model": model,
        "thinking": bool(thinking),
    }


# --------------------------------------------------------------------------- demo


def _t(lang: str, fr: str, en: str) -> str:
    return en if lang == "en" else fr


def pick_scenario(text: str) -> str:
    """Map the last user message to a scripted scenario (deterministic keyword match)."""
    low = text.lower()
    rules = [
        ("xss", ("xss", "injection html", "html injection")),
        ("error", ("erreur", "error", "panne")),
        ("slides", ("diapo", "slide", "présentation", "presentation", "pptx")),
        ("email", ("mail", "courriel")),
        ("search", ("cherche", "search", "web", "source", "compare", "trouve", "find")),
        ("minutes", ("compte rendu", "compte-rendu", "minutes", "réunion", "reunion", "meeting")),
    ]
    for name, keys in rules:
        if any(k in low for k in keys):
            return name
    return "plain"


@dataclass
class DemoBackend:
    """Scripted, deterministic backend. No model is involved: nothing here is measured."""

    delay: float = 1.0  # multiplier on the scripted pauses (0 in tests)
    kind: str = "demo"
    model: str = "bird-demo"
    tools: list[str] = field(default_factory=lambda: ["web_search", "read_page", "draft_email", "make_slides"])

    def run(self, request: ChatRequest, ctx: RunContext) -> None:
        lang = "en" if request.lang == "en" else "fr"
        last = next((m["content"] for m in reversed(request.messages) if m["role"] == "user"), "")
        run = _DemoRun(self, request, ctx, lang)
        getattr(run, "scenario_" + pick_scenario(last))()


class _DemoRun:
    def __init__(self, backend: DemoBackend, request: ChatRequest, ctx: RunContext, lang: str) -> None:
        self.b, self.req, self.ctx, self.lang = backend, request, ctx, lang
        self.t0 = time.monotonic()
        self.steps = 0
        self.bytes = 0
        self.extra_prompt = 0
        self.extra_completion = 0

    # -- helpers
    def t(self, fr: str, en: str) -> str:
        return _t(self.lang, fr, en)

    def pause(self, seconds: float) -> None:
        self.ctx.sleep(seconds * self.b.delay)

    def step(self, tool: str, arguments: dict, summary: str, pause: float, flags=None, fetched: int = 0) -> None:
        index = self.steps
        self.steps += 1
        start = time.monotonic()
        self.ctx.emit(step_event(index, tool, arguments, "running"))
        self.pause(pause)
        self.bytes += fetched
        self.extra_prompt += fetched // 16  # cleaned page text re-read by the model (scripted ratio)
        self.extra_completion += 24
        self.ctx.emit(step_event(index, tool, arguments, "done", summary, time.monotonic() - start, flags))

    def think(self, fr: str, en: str) -> None:
        if self.req.thinking:
            self.pause(0.7)
            content = self.t(fr, en)
            self.extra_completion += len(content) // 4
            self.ctx.emit({"type": "reasoning", "content": content})

    def finish(self, content: str, sources=None, files=None, draft_email=None) -> None:
        self.pause(0.5)
        self.ctx.emit(
            {
                "type": "answer",
                "content": content,
                "sources": sources or [],
                "files": files or [],
                "draft_email": draft_email,
            }
        )
        prompt = 60 + sum(len(m["content"]) for m in self.req.messages) // 4 + self.extra_prompt
        completion = len(content) // 4 + self.extra_completion
        self.ctx.emit(
            usage_event(
                model=self.b.model,
                thinking=self.req.thinking,
                prompt_tokens=prompt,
                completion_tokens=completion,
                seconds=time.monotonic() - self.t0,
                tool_calls=self.steps,
                bytes_fetched=self.bytes,
            )
        )

    # -- scenarios
    def scenario_plain(self) -> None:
        self.think(
            "Question simple, pas besoin d'outil. Je réponds directement et brièvement.",
            "Simple question, no tool needed. I answer directly and briefly.",
        )
        self.pause(0.6)
        self.finish(
            self.t(
                "Je suis **Bird**, un petit assistant de travail (4 milliards de paramètres) conçu par Bird Models.\n\n"
                "Ceci est le **mode démo** : cette réponse est écrite à l'avance, aucun modèle ne tourne. "
                "Essayez l'un des exemples (mail, compte rendu, diapositives, recherche web) pour voir les étapes "
                "de l'agent et le compteur de ressources.",
                "I am **Bird**, a small work assistant (4 billion parameters) built by Bird Models.\n\n"
                "This is **demo mode**: this answer is written in advance, no model is running. "
                "Try one of the examples (email, meeting minutes, slides, web research) to see the agent steps "
                "and the resource meter.",
            )
        )

    def scenario_minutes(self) -> None:
        self.think(
            "L'utilisateur veut un compte rendu. Structure : décisions, actions avec responsable et échéance, points ouverts.",
            "The user wants meeting minutes. Structure: decisions, actions with owner and due date, open points.",
        )
        self.pause(0.9)
        self.finish(
            self.t(
                "## Compte rendu — point projet\n\n"
                "**Participants :** Camille, Idriss, Lou\n\n"
                "### Décisions\n\n"
                "- Le lancement est décalé d'une semaine, au **12 mars**.\n"
                "- Le devis révisé est accepté tel quel.\n\n"
                "### Actions\n\n"
                "| Action | Responsable | Échéance |\n"
                "|---|---|---|\n"
                "| Prévenir le client du nouveau calendrier | Camille | 28 février |\n"
                "| Mettre à jour le budget | Idriss | 3 mars |\n"
                "| Préparer la démonstration | Lou | 10 mars |\n\n"
                "### Points ouverts\n\n"
                "1. Qui valide la communication externe ?\n"
                "2. La date du prochain point reste à fixer.\n\n"
                "*Exemple scripté du mode démo : collez vos notes pour un vrai compte rendu avec le modèle réel.*",
                "## Minutes — project check-in\n\n"
                "**Attendees:** Camille, Idriss, Lou\n\n"
                "### Decisions\n\n"
                "- The launch moves back one week, to **12 March**.\n"
                "- The revised quote is accepted as is.\n\n"
                "### Actions\n\n"
                "| Action | Owner | Due |\n"
                "|---|---|---|\n"
                "| Tell the client about the new schedule | Camille | 28 February |\n"
                "| Update the budget | Idriss | 3 March |\n"
                "| Prepare the demo | Lou | 10 March |\n\n"
                "### Open points\n\n"
                "1. Who signs off the external announcement?\n"
                "2. The date of the next check-in is still to be set.\n\n"
                "*Scripted demo example: paste your notes to get real minutes from the real model.*",
            )
        )

    def scenario_search(self) -> None:
        self.think(
            "Il faut des sources. Je cherche, je lis la page la plus pertinente, puis je cite.",
            "Sources are needed. I search, read the most relevant page, then cite.",
        )
        query = self.t("consommation énergie petits modèles de langage", "energy use small language models")
        self.step(
            "web_search",
            {"query": query},
            self.t("3 résultats (fictifs, mode démo)", "3 results (fictional, demo mode)"),
            0.9,
            fetched=6_200,
        )
        url = "https://example.org/demo/petits-modeles"
        self.step(
            "read_page",
            {"url": url},
            self.t("Page nettoyée, 1 850 mots", "Cleaned page, 1,850 words"),
            1.1,
            fetched=41_300,
        )
        sources = [
            {
                "n": 1,
                "title": self.t(
                    "Petits modèles, petite facture (page de démonstration)", "Small models, small bill (demo page)"
                ),
                "url": url,
            },
            {
                "n": 2,
                "title": self.t(
                    "Mesurer l'énergie d'une requête (page de démonstration)",
                    "Measuring the energy of a request (demo page)",
                ),
                "url": "https://example.org/demo/mesure-energie",
            },
        ]
        self.finish(
            self.t(
                "En bref : un petit modèle demande moins de calcul par réponse qu'un très grand, donc moins "
                "d'énergie, au prix d'erreurs plus fréquentes [1].\n\n"
                "- **Ce qui pèse le plus :** la taille du modèle et la longueur du contexte relu à chaque "
                "requête [1].\n"
                "- **Ce qu'on peut mesurer :** la puissance de la machine pendant la requête, quand on la "
                "maîtrise ; sinon on estime, et on le dit [2].\n\n"
                "Ces deux pages sont **fictives** (mode démo) : elles montrent la mise en forme des citations, "
                "pas des faits vérifiés.",
                "In short: a small model needs less compute per answer than a very large one, so less energy, "
                "at the cost of more frequent mistakes [1].\n\n"
                "- **What weighs most:** model size and the length of the context re-read on every request [1].\n"
                "- **What can be measured:** the machine's power draw during the request, when you control "
                "it; otherwise it is an estimate, and labelled as such [2].\n\n"
                "Both pages are **fictional** (demo mode): they show how citations look, not verified facts.",
            ),
            sources=sources,
        )

    def scenario_email(self) -> None:
        self.think(
            "Je lis la page, puis je prépare un brouillon. La page contient une instruction qui ne vient pas de l'utilisateur : je l'ignore.",
            "I read the page, then prepare a draft. The page contains an instruction that does not come from the user: I ignore it.",
        )
        url = "https://example.org/demo/offre-fournisseur"
        self.step(
            "read_page",
            {"url": url},
            self.t(
                "Offre lue. Une instruction cachée dans la page a été ignorée.",
                "Offer read. An instruction hidden in the page was ignored.",
            ),
            1.0,
            flags=["possible_injection"],
            fetched=18_400,
        )
        arguments = {
            "to": "camille@example.org",
            "subject": self.t("Votre offre du 14 février", "Your offer of 14 February"),
            "body": self.t(
                "Bonjour Camille,\n\nMerci pour votre offre. Le périmètre nous convient. Avant de valider, "
                "pourriez-vous confirmer le délai de livraison et les conditions de paiement ?\n\n"
                "Bien cordialement,",
                "Hello Camille,\n\nThank you for your offer. The scope works for us. Before we confirm, "
                "could you confirm the delivery time and the payment terms?\n\nKind regards,",
            ),
        }
        index = self.steps
        self.steps += 1
        start = time.monotonic()
        self.ctx.emit(step_event(index, "draft_email", arguments, "running"))
        allowed = self.ctx.confirm(
            "draft_email",
            arguments,
            self.t(
                "Bird veut préparer un brouillon de mail. La page lue juste avant contenait une instruction "
                "suspecte : vérifiez le destinataire et le texte.",
                "Bird wants to prepare an email draft. The page read just before contained a suspicious "
                "instruction: check the recipient and the text.",
            ),
        )
        elapsed = time.monotonic() - start
        if not allowed:
            self.ctx.emit(
                step_event(
                    index, "draft_email", arguments, "denied", self.t("Refusé par vous", "Denied by you"), elapsed
                )
            )
            self.finish(
                self.t(
                    "D'accord, je n'ai préparé aucun brouillon. Dites-moi ce qu'il faut changer "
                    "(destinataire, ton, contenu) et je recommence.",
                    "Understood, I did not prepare any draft. Tell me what to change (recipient, tone, "
                    "content) and I will start again.",
                )
            )
            return
        self.extra_completion += len(arguments["body"]) // 4
        self.ctx.emit(
            step_event(index, "draft_email", arguments, "done", self.t("Brouillon prêt", "Draft ready"), elapsed)
        )
        self.finish(
            self.t(
                "Voici un brouillon de réponse. La page contenait une phrase demandant d'envoyer des données "
                "à une autre adresse : je l'ai **ignorée**, ce n'était pas votre demande.\n\n"
                "Relisez le délai et les conditions avant d'envoyer vous-même.",
                "Here is a draft reply. The page contained a sentence asking to send data to another "
                "address: I **ignored** it, as it was not your request.\n\n"
                "Check the delivery time and the terms before sending it yourself.",
            ),
            draft_email=arguments,
        )

    def scenario_slides(self) -> None:
        self.think(
            "Cinq diapositives suffisent : contexte, constat, proposition, calendrier, prochaine étape.",
            "Five slides are enough: context, finding, proposal, timeline, next step.",
        )
        title = self.t("Sobriété numérique : plan d'action", "Digital sobriety: action plan")
        slides = [
            (title, [self.t("Présentation de démonstration générée par Bird", "Demo deck generated by Bird")]),
            (
                self.t("Contexte", "Context"),
                [
                    self.t("Des usages en hausse", "Growing usage"),
                    self.t("Un budget énergie contraint", "A constrained energy budget"),
                ],
            ),
            (
                self.t("Constat", "Finding"),
                [
                    self.t("La plupart des tâches de bureau sont simples", "Most office tasks are simple"),
                    self.t("Un petit modèle suffit souvent", "A small model is often enough"),
                ],
            ),
            (
                self.t("Proposition", "Proposal"),
                [
                    self.t("Petit modèle par défaut", "Small model by default"),
                    self.t("Compteur visible pour chaque réponse", "A visible meter for every answer"),
                ],
            ),
            (
                self.t("Prochaine étape", "Next step"),
                [self.t("Pilote de quatre semaines avec une équipe", "Four-week pilot with one team")],
            ),
        ]
        index = self.steps
        self.steps += 1
        start = time.monotonic()
        arguments = {"title": title, "slides": len(slides)}
        self.ctx.emit(step_event(index, "make_slides", arguments, "running"))
        self.pause(1.2)
        name = _write_demo_deck(self.ctx.workspace, self.lang, slides)
        self.extra_completion += 180
        self.ctx.emit(
            step_event(
                index,
                "make_slides",
                arguments,
                "done",
                self.t(f"{len(slides)} diapositives", f"{len(slides)} slides"),
                time.monotonic() - start,
            )
        )
        outline = "\n".join(f"{i}. **{s[0]}**" for i, s in enumerate(slides, 1))
        self.finish(
            self.t(
                f"La présentation est prête : {len(slides)} diapositives, à télécharger ci-dessous.\n\n{outline}\n\n"
                "Le contenu est un exemple scripté ; ouvrez le fichier et ajustez les chiffres.",
                f"The deck is ready: {len(slides)} slides, available below.\n\n{outline}\n\n"
                "The content is a scripted example; open the file and adjust the figures.",
            ),
            files=[{"name": name, "url": f"/files/{name}"}],
        )

    def scenario_xss(self) -> None:
        self.pause(0.3)
        self.finish(
            self.t("Test du rendu Markdown avec du contenu hostile :", "Markdown rendering test with hostile content:")
            + "\n\n"
            '<img src=x onerror="window.__pwned=1">\n\n'
            "<script>window.__pwned=2</script>\n\n"
            "[x](javascript:alert(1)) · [ok](https://example.org/demo/ok) · "
            "[data](data:text/html,<script>window.__pwned=3</script>)\n\n"
            '`<b>code</b>` · **gras"onmouseover="window.__pwned=4** [1]',
            sources=[{"n": 1, "title": "<b>titre</b>", "url": "javascript:alert(2)"}],
        )

    def scenario_error(self) -> None:
        self.step(
            "web_search",
            {"query": self.t("test de panne", "failure test")},
            self.t("Aucun résultat", "No result"),
            0.5,
        )
        self.pause(0.4)
        raise RuntimeError(
            self.t(
                "Erreur simulée (mode démo) : le serveur de modèle ne répond pas.",
                "Simulated error (demo mode): the model server is not responding.",
            )
        )


def _write_demo_deck(workspace: Path, lang: str, slides: list[tuple[str, list[str]]]) -> str:
    """Write the demo deck into the workspace: a real PPTX when python-pptx is present, else a Markdown outline."""
    workspace.mkdir(parents=True, exist_ok=True)
    stem = f"bird-demo-{'deck' if lang == 'en' else 'presentation'}"
    try:
        from pptx import Presentation
    except ImportError:
        name = sanitize_filename(stem + ".md")
        lines = []
        for title, bullets in slides:
            lines += [f"# {title}", "", *[f"- {b}" for b in bullets], "", "---", ""]
        (workspace / name).write_text("\n".join(lines), encoding="utf-8")
        return name
    name = sanitize_filename(stem + ".pptx")
    deck = Presentation()
    for i, (title, bullets) in enumerate(slides):
        slide = deck.slides.add_slide(deck.slide_layouts[0 if i == 0 else 1])
        slide.shapes.title.text = title
        frame = slide.placeholders[1].text_frame
        frame.text = bullets[0]
        for bullet in bullets[1:]:
            frame.add_paragraph().text = bullet
    deck.save(str(workspace / name))
    return name


# ------------------------------------------------------------------------ harness


class HarnessUnavailable(RuntimeError):
    pass


class HarnessBackend:
    """Placeholder until wired to birds.harness (see end of file)."""

    kind = "completions"
    model = "?"
    tools: list[str] = []

    @classmethod
    def completions(cls, *a, **k):
        raise HarnessUnavailable("HarnessBackend is not wired yet")

    local = completions
