"""Calculator card (birds.harness.calc): exact results from the user's own words, and no false triggers."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from test_crew import Tok

from birds.harness import Agent, Config, calc
from birds.harness.agent import Hooks
from birds.web.widgets import build_widgets


def facts(q, lang="fr"):
    return calc.facts_for(q, lang)


@pytest.mark.parametrize(
    "q, want",
    [
        ("combien font 15 % de 240 ?", "36"),
        ("calcule la TVA sur 1 200 € HT", "1 440 €"),
        ("1 440 € TTC en HT ?", "1 200 €"),
        ("quel est le prix TTC de 250 € HT à 5,5 % ?", "263,75 €"),
        ("j'ai acheté 80 € et vendu 120 €, quelle marge ?", "33,33 %"),
        ("mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %", "1 159,92 €"),
        ("emprunt de 150k sur 15 ans à 4 %, quelle mensualité ?", "1 109,53 €"),
        ("convertis 5 miles en km", "8,0467 km"),
        ("30 °C en °F", "86 °F"),
        ("combien de pieds dans 3 mètres ?", "9,8425 ft"),
        ("2,5 Go en Mo", "2 500 Mo"),
        ("augmentation de 3 % sur un salaire de 2 500 €, combien ça fait ?", "2 575 €"),
        ("remise de 15 % sur 89,90 €, ça fait combien ?", "76,42 €"),
        ("quelle est la variation entre 120 et 150 ?", "25 %"),
        ("quel pourcentage représente 45 sur 180 ?", "25 %"),
        ("1500 + 12 % = ?", "1 680"),
        ("convert 10 pounds to kg", "4,5359 kg"),
    ],
)
def test_exact_results(q, want):
    w, f = facts(q)
    assert w and w["type"] == "calc", q
    assert want in f, (q, f)


@pytest.mark.parametrize(
    "q",
    [
        "rédige un mail annonçant une hausse de 5 % des prix",
        "quel est le taux de TVA en France ?",
        "explique la marge brute",
        "fais un graphique : janvier 120, février 135",
        "convertis 100 dollars en euros",
        "réunion à 14h en salle 3",
        "on a 12 % de croissance cette année",
        "je vends ma voiture 5000 €",
        "envoie 3 docs en pdf",
        "écris 10 lignes en python",
        "fais une présentation sur la marge de 2024",
        "le prêt de 3 salles est validé",
    ],
)
def test_no_false_triggers(q):
    assert facts(q) == (None, "")


def test_loan_is_exact_and_card_is_editable():
    got = calc.detect("mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %")
    res = calc.compute(got)
    r = Decimal("0.035") / 12
    assert res["payment"] == Decimal(200000) * r / (1 - (1 + r) ** -240)
    w = calc.card(got, "fr")
    assert [i["key"] for i in w["inputs"]] == ["principal", "years", "rate"]
    assert [i["value"] for i in w["inputs"]] == ["200000", "20", "3.5"]
    assert w["rows"][0]["main"] and len(json.dumps(w)) < 2000
    en = calc.card(got, "en")
    assert en["rows"][0]["value"] == "1,159.92 €" and en["title"] == "Loan: monthly payment"


def test_vat_rate_assumed_is_said():
    w, _ = facts("calcule la TVA sur 1 200 € HT")
    assert "20 %" in w["note"]
    w, _ = facts("quel est le prix TTC de 250 € HT à 5,5 % ?")
    assert w["note"] == ""


class Once:
    def __init__(self, text):
        self.text, self.prompts = text, []

    def generate(self, prompt, max_tokens, stop, **_):
        self.prompts.append(prompt)
        return {"text": self.text, "prompt_tokens": 10, "completion_tokens": 10, "seconds": 0.01}


def test_agent_gives_the_model_the_results_and_the_ui_the_card(tmp_path):
    llm = Once("La mensualité est de 1 159,92 €.")
    a = Agent(llm, Tok(), Config(workspace=tmp_path, audit_file=None), hooks=Hooks())
    run = a.run("mensualité d'un prêt de 200 000 € sur 20 ans à 3,5 %", lang="fr")
    p = json.loads(llm.prompts[0])
    assert "Mensualité : 1 159,92 €" in p["messages"][-1]["content"]
    assert "web_search" not in p["tools"]
    assert [w["type"] for w in run.widgets] == ["calc"]
    assert [w["type"] for w in build_widgets(run.steps, "", "fr", None, b"x", extra=run.widgets)] == ["calc"]


def test_ordinary_turn_keeps_the_tool_block(tmp_path):
    llm = Once("Bonjour !")
    a = Agent(llm, Tok(), Config(workspace=tmp_path, audit_file=None), hooks=Hooks())
    run = a.run("rédige un mail annonçant une hausse de 5 % des prix", lang="fr")
    p = json.loads(llm.prompts[0])
    assert "Note de Bird" not in p["messages"][-1]["content"] and not run.widgets
