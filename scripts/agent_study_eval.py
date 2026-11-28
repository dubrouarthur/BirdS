"""Live A/B of the Mode Agent through the real server (SSE), and the rubric table of docs/HARNESS.md.

usage:
  .venv/bin/python -I scripts/agent_study_eval.py PORT OUTDIR [index...] [--arms=on,off] [--set=study|office|all]
                                                  [--plan] [--edits=JSON] [--note=KIND:VALUE]
  .venv/bin/python -I scripts/agent_study_eval.py --table OUTDIR [OUTDIR2]

Writes OUTDIR/<i>-<arm>.json with the answer, the file's arguments, sources, usage, checks and wall time.
``--plan`` goes through the plan card (agent_flow="plan", then « Lancer » with the signed plan, as the app does);
``--note`` sends one typed mid-run instruction once the team has started (wave 2). ``--table`` scores each run on
the rubric (deliverable produced, sections, citations valid, figures verified, time) and prints a Markdown table;
with two folders, before / after side by side.
"""

import json
import re
import sys
import threading
import time
import urllib.request

PROMPTS = [
    "Fais une étude comparative des 3 principaux CRM du marché pour une PME avec un tableau et une recommandation",
    "Fais un dossier de veille sur l'IA générative en entreprise en 2026 : tendances, chiffres, risques",
    "Rédige un rapport sur la transition énergétique des PME françaises avec des chiffres récents et des sources",
    "Fais un benchmark des outils de visioconférence du marché pour une PME de 50 personnes",
]
OFFERS = """Objet : consultation maintenance du parc informatique (85 postes, 2 sites : Lyon et Villeurbanne)

1. InfoServ Rhône
Contrat de maintenance sur 36 mois. Forfait mensuel de 1 450 € HT pour l'ensemble du parc (85 postes et 4 serveurs). Frais de mise en place : 2 000 € HT, facturés une seule fois. Intervention sur site garantie sous 4 heures ouvrées. Préavis de résiliation : 3 mois.

2. Nexa IT Services
Contrat de 24 mois, tarif de 19 € HT par poste et par mois, les 4 serveurs à 60 € HT chacun par mois. Aucuns frais de mise en place. Intervention sur site sous 8 heures ouvrées (sous 4 heures en option pour 150 € HT par mois). Préavis : 1 mois.

3. Groupe Calyx
Engagement de 36 mois. Forfait de 1 290 € HT par mois, plafonné à 90 postes. Frais de mise en place : 4 500 € HT, comprenant un audit complet du parc. Intervention sous 6 heures ouvrées. Préavis : 6 mois.

Contrainte interne : budget annuel maximal de 20 000 € HT, intervention sous 4 heures demandée pour le site de Lyon (production)."""
NOTES = """Réunion du comité de pilotage — projet migration ERP — mardi 14 octobre 2025, 10 h - 11 h 30
Présents : Sophie Lambert (DAF), Karim Benali (DSI), Julie Moreau (responsable logistique), Thomas Petit (chef de projet)
Excusé : Marc Girard (directeur commercial)

1. Planning
- Thomas : la phase de paramétrage a 3 semaines de retard (12 000 références dont 30 % de doublons)
- go-live décalé du 5 janvier au 2 février 2026, validé par Sophie
- Karim demande un planning révisé détaillé avant le 21/10 -> Thomas

2. Reprise des données
- Julie : nettoyage des doublons articles fait à 60 %, fin prévue le 31/10
- Karim : test de reprise complet sur l'environnement de recette la semaine du 17/11

3. Formation
- Thomas fournit les supports de formation pour le 15/12
- Sophie présentera l'avenant au comité de direction du 28/10

Prochaine réunion le 4 novembre, 10 h, salle Rhône"""
OFFICE = [
    "Fais une présentation de 6 diapos sur l'évolution du télétravail en France depuis 2019 avec des chiffres sourcés",
    "Prépare une présentation de 6 diapos sur le marché des véhicules électriques en France depuis 2020 avec des "
    "chiffres sourcés",
    "Compare les offres de 3 fournisseurs à partir de ce texte et rédige un mail de recommandation à notre directrice "
    "administrative, Claire Martin (claire.martin@atelier-durand.fr).\n\n" + OFFERS,
    "Fais le compte rendu de ces notes de réunion avec un tableau des actions.\n\n" + NOTES,
]
SETS = {"study": PROMPTS, "office": OFFICE, "all": PROMPTS + OFFICE}


def _post(base: str, body: dict, on_event=None) -> list[dict]:
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-bird-mode": "server"})  # fmt: skip
    events = []
    with urllib.request.urlopen(req, timeout=320) as r:
        buf = b""
        for chunk in iter(lambda: r.read(4096), b""):
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                line = frame.decode("utf-8", "replace")
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    events.append(ev)
                    if on_event:
                        on_event(ev)
    return events


def _note(base: str, run: str, kind: str, value: str) -> None:
    req = urllib.request.Request(base + "/api/agent/note", method="POST",
                                 data=json.dumps({"run": run, "kind": kind, "value": value}).encode(),
                                 headers={"Content-Type": "application/json", "x-bird-mode": "server"})  # fmt: skip
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001 - printed, the run goes on
        print("note failed:", e, flush=True)


def run_one(base: str, prompt: str, arm: str, plan: bool, note: str | None, edits: dict | None = None) -> dict:
    body = {"messages": [{"role": "user", "content": prompt}], "agent": arm, "lang": "fr"}
    t0 = time.monotonic()
    events: list[dict] = []
    if plan and arm != "off":
        body["agent_flow"] = "plan"
        first = _post(base, body)
        events += first
        card = next((e for e in first if e.get("type") == "agent_plan"), None)
        if card:  # « Lancer », the plan unchanged
            body = {**body, "agent_plan": {"token": card["token"], "edits": edits or {}}}
    sent = {"done": False}

    def on_event(ev):
        if note and ev.get("type") == "agent_start" and ev.get("run") and not sent["done"]:
            sent["done"] = True
            kind, _, value = note.partition(":")
            threading.Timer(1.0, _note, (base, ev["run"], kind, value)).start()

    events += _post(base, body, on_event)
    for _ in range(3):  # a long task continues in slices: the client carries the signed state
        sl = next((e for e in reversed(events) if e.get("type") == "agent_slice" and e.get("auto") and not e.get("used")), None)
        if not sl or any(e.get("type") in ("answer", "confirm") for e in events):
            break
        nxt = {k: v for k, v in body.items() if k != "agent_plan"}
        events += _post(base, {**nxt, "agent_slice": sl["token"]}, on_event)
        sl["used"] = True
    confirm = next((e for e in events if e.get("type") == "confirm"), None)
    if confirm and not any(e.get("type") == "answer" for e in events):
        # a page looked like an injection and the file waits for a confirmation: « Autoriser », as a user would
        plain = {k: v for k, v in body.items() if k not in ("agent_plan", "agent_flow")}
        events += _post(base, {**plain, "approved": [confirm["token"]]}, on_event)
    wall = round(time.monotonic() - t0, 1)
    files = [e for e in events if e.get("type") in ("step", "tool_start")
             and e.get("tool") in ("make_document", "make_slides", "draft_email")]  # fmt: skip
    answer = next((e for e in events if e.get("type") == "answer"), {})
    return {
        "prompt": prompt,
        "arm": arm,
        "wall": wall,
        "answer": answer,
        "usage": next((e for e in events if e.get("type") == "usage"), {}),
        "agent_done": next((e for e in events if e.get("type") == "agent_done"), None),
        "checks": next((e for e in events if e.get("type") == "agent_checks"), None),
        "notes": [e for e in events if e.get("type") == "agent_note"],
        "slices": sum(1 for e in events if e.get("type") == "agent_slice" and e.get("auto")),
        "confirmed": confirm is not None,
        "file_args": [f.get("arguments") for f in files if f.get("arguments")],
        "tools": [
            (e.get("tool"), (e.get("arguments") or {}).get("query") or (e.get("arguments") or {}).get("url"))
            for e in events
            if e.get("type") == "step" and e.get("tool") and e.get("status") == "done"
        ],
        "errors": [e for e in events if e.get("type") == "error"],
    }


# ------------------------------------------------------------------ rubric

_FIG = re.compile(r"(?<![\w\[])\d[\d  ,.]*\s?(?:%|€|M€|Md€|milliards?|millions?|points?|To|Go|h\b)", re.I)


def _text(args: dict) -> tuple[str, int]:
    """The deliverable's text and its number of sections / slides (the Sources part excluded)."""
    if not isinstance(args, dict):
        return "", 0
    parts = args.get("sections") or args.get("slides") or []
    keep = [p for p in parts if str(p.get("heading") or p.get("title") or "").strip().lower() != "sources"]
    text = "\n".join(str(p.get("content") or "") + "\n".join(map(str, p.get("bullets") or [])) for p in keep)
    if args.get("body"):
        text, keep = str(args["body"]), [1]
    return text, len(keep)


def score(rec: dict) -> dict:
    args = (rec.get("file_args") or [None])[-1]
    text, n_sections = _text(args or {})
    sources = (rec.get("answer") or {}).get("sources") or []
    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
    n_src = len(sources) or len(re.findall(r"^\[\d+\] ", json.dumps(args or {}, ensure_ascii=False), re.M))
    valid = bool(cited) and all(1 <= n <= max(n_src, 1) for n in cited) if n_src else not cited
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n", text) if _FIG.search(s)]
    pasted = rec["prompt"]
    sourced = [s for s in sentences if re.search(r"\[\d{1,2}\]", s)
               or all(m.group(0).split()[0] in pasted for m in _FIG.finditer(s))]  # fmt: skip
    checks = rec.get("checks") or {}
    return {
        "deliverable": bool(args) and not rec.get("errors"),
        "sections": n_sections,
        "citations_valid": valid,
        "figures": len(sentences),
        "figures_sourced": len(sourced),
        "verified": checks.get("verified_n"),
        "removed": checks.get("removed_n"),
        "review": checks.get("review_n"),
        "sources": len(sources),
        "time": rec.get("wall"),
    }


def table(dirs: list[str]) -> str:
    import glob
    import os

    rows = {}
    for k, d in enumerate(dirs):
        for path in sorted(glob.glob(os.path.join(d, "*-on.json"))):
            rec = json.load(open(path))
            i = int(os.path.basename(path).split("-")[0])
            rows.setdefault((rec["prompt"][:58], i), [None] * len(dirs))[k] = score(rec)
    head = ["Demande", *(f"{x} ({'avant' if k == 0 else 'après'})" for k in range(len(dirs))
                         for x in ("livrable", "sections", "citations", "chiffres sourcés", "temps"))]  # fmt: skip
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for (p, _), cols in sorted(rows.items(), key=lambda kv: kv[0][1]):
        cells = [p.replace("|", "/") + "…"]
        for s in cols:
            if s is None:
                cells += ["—"] * 5
                continue
            cells += ["oui" if s["deliverable"] else "non", str(s["sections"]),
                      "valides" if s["citations_valid"] else "non", f"{s['figures_sourced']}/{s['figures']}",
                      f"{s['time']:.0f} s"]  # fmt: skip
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main() -> None:
    if sys.argv[1] == "--table":
        print(table(sys.argv[2:]))
        return
    port, out = sys.argv[1], sys.argv[2]
    arms, idx, plan, note, prompts, edits = ["on", "off"], [], False, None, PROMPTS, None
    for a in sys.argv[3:]:
        if a.startswith("--arms="):
            arms = a.split("=", 1)[1].split(",")
        elif a.startswith("--set="):
            prompts = SETS[a.split("=", 1)[1]]
        elif a.startswith("--edits="):
            edits = json.loads(a.split("=", 1)[1])
        elif a == "--plan":
            plan = True
        elif a.startswith("--note="):
            note = a.split("=", 1)[1]
        else:
            idx.append(int(a))
    base = f"http://127.0.0.1:{port}"
    for i in idx or list(range(len(prompts))):
        for arm in arms:
            rec = run_one(base, prompts[i], arm, plan, note, edits)
            with open(f"{out}/{i}-{arm}.json", "w") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            print(i, arm, json.dumps(score(rec), ensure_ascii=False), "err", rec["errors"][:1], flush=True)


if __name__ == "__main__":
    main()
