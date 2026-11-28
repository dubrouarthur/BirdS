"""Albatros with Mode Agent on Auto: the team runs only for a team task (production, 28/11/2026: « comment aller faire
ses courses à Saint-Cloud, quels sont les supermarchés » ran the deep-research team, « forcé »). No network."""

from types import SimpleNamespace

import pytest

from birds.harness import router
from birds.web import crew_web
from birds.web.backends import ChatRequest

SAINT_CLOUD = "comment aller faire ses courses a saint cloud quels sont les supermarchés"
AI_ACT = "Fais une recherche approfondie sur l'AI Act et ses obligations pour une PME française"


def req(text):
    return ChatRequest(messages=[{"role": "user", "content": text}], agent="auto")


def with_router(monkeypatch, decision):
    seen = []
    monkeypatch.setattr(router, "plan_turn", lambda *a, **k: seen.append(a[1]) or router.Plan(decision))
    return seen


def test_a_local_practical_question_is_no_team_task(monkeypatch):
    seen = with_router(monkeypatch, router.Decision([router.Call("find_places", {"query": "supermarché",
                                                                                "near": "Saint-Cloud"})], "off"))
    assert crew_web.albatros_decision(SimpleNamespace(), req(SAINT_CLOUD), SAINT_CLOUD, 0, 0, "fr") is None
    assert seen == [SAINT_CLOUD]


def test_a_research_ask_the_router_agrees_with_runs_as_a_team_never_forced(monkeypatch):
    with_router(monkeypatch, router.Decision([], "on", True))
    d = crew_web.albatros_decision(SimpleNamespace(), req(AI_ACT), AI_ACT, 0, 0, "fr")
    assert d is not None and d.recipe == "deep_research" and d.forced is False


@pytest.mark.parametrize("text,team", [(SAINT_CLOUD, False), (AI_ACT, True)])
def test_router_unavailable_only_explicit_asks_and_deliverables(monkeypatch, text, team):
    with_router(monkeypatch, None)
    d = crew_web.albatros_decision(SimpleNamespace(), req(text), text, 0, 0, "fr")
    assert (d is not None) is team


def test_the_router_is_asked_once_per_request():
    calls = []

    class Llm:
        pass

    agent = SimpleNamespace(cfg=SimpleNamespace(), llm=Llm())
    agent._router_memo = ((SAINT_CLOUD, 0, False, "fr"), router.Plan(router.Decision([], "off")))
    got = router.plan_turn(agent, SAINT_CLOUD, None, attached=False, lang="fr", deadline=0.0)
    assert got.decision.agent == "off" and not calls


def test_the_parsers_fallback_is_not_the_model_saying_team(monkeypatch):
    with_router(monkeypatch, router.Decision([], "auto", False, "fallback"))
    assert crew_web.albatros_decision(SimpleNamespace(), req(SAINT_CLOUD), SAINT_CLOUD, 0, 0, "fr") is None
