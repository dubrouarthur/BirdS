"""Trigger audit, maps (wave 2): lists of places and addresses, distances, « autour de moi », typos and spoken forms,
and the office prompts that must never reach the geocoder. The full phrasing set is scripts/bench_maps.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from birds.harness import intents, mapwords

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_maps  # noqa: E402


def _call(text):
    got = next((i for i in intents.detect(text) if i.tool == "find_places"), None)
    return got and (got.mode, got.args)


def test_the_owner_example_geocodes_every_address_of_the_list():
    text = "montre sur une carte : 10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille"
    assert _call(text) == (
        "list",
        {"query": "10 rue de Rivoli Paris ; 5 place Bellecour Lyon ; 1 La Canebière Marseille"},
    )


@pytest.mark.parametrize(
    "text,items",
    [
        ("affiche ces adresses sur une carte :\n- 10 rue de Rivoli, Paris\n- 5 place Bellecour, Lyon",
         ["10 rue de Rivoli, Paris", "5 place Bellecour, Lyon"]),
        ("10 rue de Rivoli Paris\n5 place Bellecour Lyon\n1 La Canebière Marseille",
         ["10 rue de Rivoli Paris", "5 place Bellecour Lyon", "1 La Canebière Marseille"]),
        ("nom;adresse\nAgence Lyon;12 rue de la République 69002 Lyon\nAgence Lille;8 rue Nationale 59000 Lille",
         ["12 rue de la République 69002 Lyon", "8 rue Nationale 59000 Lille"]),
        ("nos agences de Lyon, Marseille et Lille sur une carte", ["Lyon", "Marseille", "Lille"]),
        ("ou sont lyon marseille et lille sur une carte", ["lyon", "marseille", "lille"]),
        ("situe nos agences : Rouen, Caen et Le Havre", ["Rouen", "Caen", "Le Havre"]),
        ("montre sur une carte la tour Eiffel et le Louvre", ["tour Eiffel", "Louvre"]),
    ],
)  # fmt: skip
def test_lists_by_newline_bullet_csv_and_et(text, items):
    mode, args = _call(text)
    assert mode == "list" and args["query"].split(" ; ") == items


def test_a_list_keeps_at_most_25_places():
    text = "carte : " + " ; ".join(f"{n} rue de la Paix Paris" for n in range(1, 40))
    assert len(_call(text)[1]["query"].split(" ; ")) == mapwords.MAX_ITEMS


@pytest.mark.parametrize(
    "text,pair",
    [
        ("c'est loin Lyon de Paris ?", {"Lyon", "Paris"}),
        ("combien de km entre Nantes et Rennes", {"Nantes", "Rennes"}),
        ("c'est loin la gare de Lyon de la tour Eiffel ?", {"gare de Lyon", "tour Eiffel"}),
        ("how far is Lyon from Paris", {"Lyon", "Paris"}),
        ("itineraire gare de lyon tour eiffel", {"gare de lyon", "tour eiffel"}),
    ],
)
def test_distances_are_routes_between_two_places(text, pair):
    mode, args = _call(text)
    assert mode == "route" and {args["query"], args["near"]} == pair


@pytest.mark.parametrize(
    "text", ["restaurants autour de moi", "la pharmacie la plus proche", "coffee shops near me", "les restos du coin"]
)
def test_near_me_asks_for_a_place_and_geocodes_nothing(text):
    assert _call(text) == ("ask", None)


@pytest.mark.parametrize(
    "text",
    [
        "affiche les ventes de Lyon, Marseille et Lille",
        "compare les ventes de Paris et Lyon",
        "liste les clients de Lyon, Marseille et Lille",
        "plan d'accès au VPN de l'entreprise",
        "envoie à cette adresse : paul@example.com",
        "comment venir à bout des retards ?",
        "la distance entre nos positions dans la négociation",
        "écris une fonction qui calcule la distance entre deux points",
        "budget ; planning ; recrutement",
    ],
)
def test_office_prompts_with_map_like_words_never_trigger(text):
    assert _call(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Quelle est la distance entre la Terre et le Soleil ?",
        "Quelle distance entre Mars et Jupiter ?",
        "Quelle est la distance en km entre la Terre et la Lune ?",
        "how far is the Earth from the Moon?",
        "distance between Mars and Jupiter",
    ],
)
def test_a_distance_between_two_non_places_is_left_to_the_model(text):
    assert _call(text) is None


@pytest.mark.parametrize(
    "text,pair",
    [("distance entre la gare de Lyon et Bercy", {"gare de Lyon", "Bercy"}),
     ("quelle est la distance entre la tour Eiffel et le Louvre ?", {"tour Eiffel", "Louvre"})],
)  # fmt: skip
def test_a_distance_with_one_sure_place_is_still_a_route(text, pair):
    mode, args = _call(text)
    assert mode == "route" and {args["query"], args["near"]} == pair


@pytest.mark.parametrize(
    "text,plan",
    [("dans quel ordre visiter : Lyon, Grenoble", "order"), ("optimise ma tournée", "order"),
     ("distances entre Paris, Lyon et Marseille", "distances"), ("carte : Lyon ; Lille", "")],
)  # fmt: skip
def test_plan_of_a_list(text, plan):
    assert mapwords.plan_of(text) == plan


def test_bench_maps_family_is_complete():
    assert len(bench_maps.MAPS_REAL) == 200 and len(bench_maps.MAPS_OFFICE_NO) == 60
    missed = [t for t, s in bench_maps.MAPS_REAL if not bench_maps.correct((t, s))]
    false = [t for t in bench_maps.MAPS_OFFICE_NO if bench_maps.detected(t)]
    assert not missed and not false


@pytest.mark.parametrize(
    "text,args",
    [("dans quel ordre visiter Lyon, Grenoble, Annecy et Chambéry ?",
      {"query": "Lyon ; Grenoble ; Annecy ; Chambéry", "plan": "order"}),
     ("montre sur une carte : Lyon ; Grenoble ; Chambéry, dans quel ordre les visiter ?",
      {"query": "Lyon ; Grenoble ; Chambéry", "plan": "order"}),
     ("montre sur une carte : 3 rue du Circuit Magny-Cours ; 5 place Bellecour Lyon",
      {"query": "3 rue du Circuit Magny-Cours ; 5 place Bellecour Lyon"})],
)  # fmt: skip
def test_the_plan_is_an_argument_and_the_ask_is_not_a_place(text, args):
    got = [i for i in intents.detect(text) if i.tool == "find_places"]
    assert got and got[0].args == args
