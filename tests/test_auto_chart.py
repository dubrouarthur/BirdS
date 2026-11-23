"""Charts drawn by the harness when the figures are there: the user's own, or a table the model wrote instead."""

from __future__ import annotations

from birds.harness import Agent, Config, FakeClient
from birds.harness.agent import figures_in


class Tok:
    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=True, **kw):
        return "\n".join(str(m.get("content")) for m in messages)


def test_figures_in_finds_tables_lists_and_inline_pairs():
    table = "| Année | Population |\n|---|---|\n| 2012 | 2 240 621 |\n| 2017 | 2 187 526 |\n| 2021 | 2 133 111 |"
    cols, rows, _ = figures_in(table)
    assert cols == ["Année", "Population"] and rows[0] == ["2012", "2240621"] and len(rows) == 3
    lst = "Répartition :\n- Nord : 30 %\n- Sud : 45 %\n- Est : 25 %"
    cols, rows, unit = figures_in(lst)
    assert [r[0] for r in rows] == ["Nord", "Sud", "Est"] and unit == "%"
    cols, rows, _ = figures_in("graphique des ventes : janvier 120, février 135, mars 160")
    assert [r[1] for r in rows] == ["120", "135", "160"]
    assert figures_in("Le budget est de 12 000 € et la marge de 31 %.") is None  # two figures: no chart


def test_the_users_figures_are_charted_by_the_harness(tmp_path):
    llm = FakeClient(["Les ventes montent de janvier à mars."])
    run = Agent(llm, Tok(), Config(workspace=tmp_path)).run(
        "Fais un graphique des ventes : janvier 120, février 135, mars 160", lang="fr"
    )
    assert run.charts and run.charts[0]["type"] == "line" and [s.tool for s in run.steps] == ["make_chart"]
    assert len(llm.prompts) == 1  # no nudge, no second generation


def test_a_table_answer_to_a_trend_question_becomes_a_chart(tmp_path):
    table = "Voici l'évolution :\n\n| Année | Taux |\n|---|---|\n| 2019 | 8,4 % |\n| 2021 | 7,9 % |\n| 2023 | 7,3 % |"
    run = Agent(FakeClient([table]), Tok(), Config(workspace=tmp_path)).run(
        "Comment évolue le chômage en France depuis 2019 ?", lang="fr"
    )
    assert run.charts and run.charts[0]["type"] == "line" and run.answer.startswith("Voici")


def test_no_chart_without_a_chart_or_trend_ask(tmp_path):
    table = "| Poste | Coût |\n|---|---|\n| Loyer | 1 200 € |\n| Énergie | 300 € |\n| Assurance | 90 € |"
    run = Agent(FakeClient([table]), Tok(), Config(workspace=tmp_path)).run("Liste mes charges fixes", lang="fr")
    assert not run.charts
