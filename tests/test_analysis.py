"""Data analysis computed by the harness (birds/harness/analysis): reading messy tables, profiling, questions turned
into queries (checked against numbers computed independently here), the number check of answers, the v2 chart spec
(fuzzed), the hooks around a run and the web routes. No network, no model."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from birds.harness.analysis import (
    QueryError,
    check_numbers,
    normalize_spec,
    plan_question,
    profile_table,
    read_table,
    read_text_table,
    run_query,
    suggestions,
)
from birds.harness.analysis.cells import fmt_value, parse_date, parse_number
from birds.harness.analysis.charts import TYPES, auto_type, chart_from_result
from birds.harness.analysis.hooks import finish, prepare, strip_note
from birds.harness.analysis.profile import frame_of
from birds.harness.analysis.query import result_numbers
from birds.harness.guard import ToolError

DATA = Path(__file__).parent / "fixtures" / "data"


# ---------------------------------------------------------------- an independent reading of the fixture


def _fr(x: str) -> float | None:
    x = x.replace(" ", "").replace(" ", "").replace(",", ".")
    return float(x) if x else None


@pytest.fixture(scope="module")
def raw():
    """The fixture read with csv + hand parsing (not the code under test)."""
    lines = (DATA / "ventes.csv").read_text(encoding="utf-8-sig").splitlines()
    rows = [r for r in csv.reader(lines[2:], delimiter=";") if r]
    head, body = rows[0], rows[1:]
    out = []
    for r in body:
        d = dt.datetime.strptime(r[0], "%d/%m/%Y")
        out.append({"date": d, "region": r[1], "produit": r[2], "client": r[3], "commercial": r[4],
                    "qte": float(r[5]), "prix": _fr(r[6]), "ca": _fr(r[7])})  # fmt: skip
    assert head[7] == "CA (€)"
    return out


@pytest.fixture(scope="module")
def frame():
    return frame_of(read_table(DATA / "ventes.csv"))


def group(rows, key, val, agg=sum):
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(val(r))
    return {k: agg(v) for k, v in g.items()}


def close(a, b, tol=0.011):
    return a is not None and b is not None and abs(a - b) <= tol * max(1, abs(b) / 1000)


# ---------------------------------------------------------------- cells


@pytest.mark.parametrize(
    "text,decimal,want",
    [
        ("1 234,56 €", ",", (1234.56, "€")),
        ("1 234,5", ",", (1234.5, "")),
        ("12,5 %", ",", (12.5, "%")),
        ("(1 200)", ",", (-1200, "")),
        ("1.234,5", ",", (1234.5, "")),
        ("€1,234.56", ".", (1234.56, "€")),
        ("3 M€", ",", (3_000_000, "€")),
        ("1,2 Md€", ",", (1_200_000_000, "€")),
        ("12 m", ",", (12, "m")),
        ("-3,2 %", ",", (-3.2, "%")),
        ("−7", ",", (-7, "")),
        ("n/a", ",", (None, "")),
        ("1.234", ",", (1234, "")),
        ("45 pts", ",", (45, "pts")),
    ],
)
def test_parse_number(text, decimal, want):
    assert parse_number(text, decimal) == want


@pytest.mark.parametrize("text", ["abc", "12 ans et demi", "=SUM(A1:A3)", "2024-03-04", "1.2.3.4"])
def test_parse_number_refuses(text):
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize(
    "text,order,want,grain",
    [
        ("03/04/2024", "dmy", dt.datetime(2024, 4, 3), "day"),
        ("04/13/2024", "mdy", dt.datetime(2024, 4, 13), "day"),
        ("13/02/24", "dmy", dt.datetime(2024, 2, 13), "day"),
        ("2024-03-04", "dmy", dt.datetime(2024, 3, 4), "day"),
        ("12 mars 2024", "dmy", dt.datetime(2024, 3, 12), "day"),
        ("mars 2024", "dmy", dt.datetime(2024, 3, 1), "month"),
        ("janv.-24", "dmy", dt.datetime(2024, 1, 1), "month"),
        ("T3 2025", "dmy", dt.datetime(2025, 7, 1), "quarter"),
        ("2025-02", "dmy", dt.datetime(2025, 2, 1), "month"),
        ("1er août 2024", "dmy", dt.datetime(2024, 8, 1), "day"),
    ],
)
def test_parse_date(text, order, want, grain):
    assert parse_date(text, order) == (want, grain)


def test_french_formatting():
    assert fmt_value(1234567.891, "€") == "1 234 568 €"
    assert fmt_value(12.5, "%") == "12,5 %"
    assert fmt_value(1234.5, "$", "en") == "$1,234.5"


# ---------------------------------------------------------------- messy tables


MESSY = {
    "semicolon_comma": "Région;CA\nNord;1 234,50\nSud;987,00\nEst;2 100,25\n",
    "comma_dot": 'Region,Revenue\nNorth,"1,234.50"\nSouth,987.00\nEast,"2,100.25"\n',
    "tab": "Région\tCA\nNord\t1234,5\nSud\t987\nEst\t2100,25\n",
    "pipe_markdown": "| Région | CA |\n|---|---|\n| Nord | 1 234,5 |\n| Sud | 987 |\n| Est | 2 100,25 |\n",
    "blank_lines_title": "Export du 03/01/2025\n\n\nRégion;CA\n\nNord;1 234,5\n\nSud;987\nEst;2 100,25\n\n",
    "total_row": "Région;CA\nNord;1 234,5\nSud;987\nEst;2 100,25\nTotal;4 321,75\n",
}


@pytest.mark.parametrize("name", list(MESSY))
def test_messy_csv_profiles_the_same(name):
    t = read_text_table(MESSY[name], f"{name}.csv")
    f = frame_of(t)
    assert t.shape == (3, 2), (t.columns, t.rows)
    assert [c.type for c in f.columns] == ["category", "number"]
    xs = [v for v in f.columns[1].values]
    assert [round(x, 2) for x in xs] == [1234.5, 987.0, 2100.25]
    if name == "total_row":
        assert t.meta["total_row"]  # the Total row is set aside, never summed twice


def test_cp1252_and_bom(tmp_path):
    p = tmp_path / "w.csv"
    p.write_bytes("Ville;Coût\nOrléans;1 200,5\nNîmes;300\nSète;45,25\n".encode("cp1252"))
    t = read_table(p)
    assert t.columns == ["Ville", "Coût"] and t.meta["encoding"] == "windows-1252"
    p.write_bytes("﻿Ville;Coût\nA;1\nB;2\nC;3\n".encode())
    assert read_table(p).columns[0] == "Ville"


def test_xlsx_merged_two_row_header():
    t = read_table(DATA / "budget_fusion.xlsx")
    assert t.columns == ["Service", "2024 Prévu", "2024 Réel", "2025 Prévu", "2025 Réel"]
    assert t.meta["header_rows"] == 2 and t.meta["total_row"] and t.meta["skipped"] == 1
    f = frame_of(t)
    assert f.n == 5 and [c.type for c in f.columns] == ["category"] + ["number"] * 4


def test_profile_of_the_fixture(frame, raw):
    p = profile_table(frame)
    assert (p["rows"], p["cols"]) == (480, 9)
    cols = {c["name"]: c for c in p["columns"]}
    assert cols["Date"]["type"] == "date" and cols["Date"]["span"]["start"] == raw[0]["date"].strftime("%Y-%m-%d")
    assert cols["CA (€)"]["unit"] == "€" and close(cols["CA (€)"]["stats"]["sum"], sum(r["ca"] for r in raw))
    assert close(cols["CA (€)"]["stats"]["median"], statistics.median(r["ca"] for r in raw))
    assert cols["Remise"]["unit"] == "%" and cols["Remise"]["missing"] > 0
    assert cols["Région"]["type"] == "category" and cols["Région"]["distinct"] == 5
    assert len(cols["CA (€)"]["hist"]) == 12 and sum(cols["CA (€)"]["hist"]) == 480
    assert cols["CA (€)"]["stats"]["outliers"]["n"] >= 1
    json.dumps(p)  # JSON-safe


def test_types_id_text_bool_year():
    text = "N° commande;Année;Livré;Commentaire;Montant\n" + "\n".join(
        f"{1000 + i};{2020 + i % 3};{'oui' if i % 2 else 'non'};Commande passée par téléphone, rappel demandé le "
        f"lendemain matin numéro {i};{10 + i}" for i in range(30))  # fmt: skip
    f = frame_of(read_text_table(text, "c.csv"))
    assert [c.type for c in f.columns] == ["id", "date", "bool", "text", "number"]
    assert f.columns[1].grain == "year"


# ---------------------------------------------------------------- 30 questions -> correct numbers


def _ca(r):
    return r["ca"]


def expected(raw):
    by_month = group(raw, lambda r: (r["date"].year, r["date"].month), _ca, lambda v: sum(v) / len(v))
    return by_month


QUESTIONS = [
    # (question, check(result, raw))
    ("quel est le CA total ?", lambda res, raw: close(res["scalar"], sum(map(_ca, raw)))),
    ("CA total en 2025", lambda res, raw: close(res["scalar"], sum(r["ca"] for r in raw if r["date"].year == 2025))),
    ("quel est le CA moyen ?", lambda res, raw: close(res["scalar"], sum(map(_ca, raw)) / len(raw))),
    ("CA médian", lambda res, raw: close(res["scalar"], statistics.median(map(_ca, raw)))),
    ("quel est le CA moyen par mois ?", lambda res, raw: close(res["rows"][0][1], sum(r["ca"] for r in raw if (r["date"].year, r["date"].month) == (2024, 1)) / sum(1 for r in raw if (r["date"].year, r["date"].month) == (2024, 1)))),
    ("CA par mois", lambda res, raw: len(res["rows"]) == 24 and close(res["rows"][-1][1], sum(r["ca"] for r in raw if (r["date"].year, r["date"].month) == (2025, 12)))),
    ("CA par trimestre", lambda res, raw: len(res["rows"]) == 8 and close(res["rows"][0][1], sum(r["ca"] for r in raw if r["date"].year == 2024 and r["date"].month <= 3))),
    ("CA par an", lambda res, raw: [r[0] for r in res["rows"]] == ["2024", "2025"] and close(res["rows"][1][1], sum(r["ca"] for r in raw if r["date"].year == 2025))),
    ("évolution des ventes", lambda res, raw: res["kind"] == "time" and len(res["rows"]) == 24),
    ("top 5 des produits", lambda res, raw: [r[0] for r in res["rows"]] == [k for k, _ in sorted(group(raw, lambda r: r["produit"], _ca).items(), key=lambda kv: -kv[1])[:5]]),
    ("top 3 des clients", lambda res, raw: close(res["rows"][0][1], max(group(raw, lambda r: r["client"], _ca).values())) and len(res["rows"]) == 3),
    ("top 3 des clients dans le Nord", lambda res, raw: close(res["rows"][0][1], max(group([r for r in raw if r["region"] == "Nord"], lambda r: r["client"], _ca).values()))),
    ("quel est le meilleur commercial ?", lambda res, raw: res["rows"][0][0] == max(group(raw, lambda r: r["commercial"], _ca).items(), key=lambda kv: kv[1])[0] and len(res["rows"]) == 1),
    ("les 3 produits les moins vendus", lambda res, raw: [r[0] for r in res["rows"]] == [k for k, _ in sorted(group(raw, lambda r: r["produit"], lambda r: r["qte"]).items(), key=lambda kv: kv[1])[:3]]),
    ("CA par région", lambda res, raw: {r[0]: r[1] for r in res["rows"]}["Est"] == pytest.approx(group(raw, lambda r: r["region"], _ca)["Est"], abs=0.01)),
    ("répartition du CA par région", lambda res, raw: res["kind"] == "share" and abs(sum(r[2] for r in res["rows"]) - 100) < 0.5),
    ("répartition des ventes par produit", lambda res, raw: res["kind"] == "share" and len(res["rows"]) == 6),
    ("combien de clients ?", lambda res, raw: res["scalar"] == len({r["client"] for r in raw})),
    ("combien de commandes ?", lambda res, raw: res["scalar"] == len(raw)),
    ("nombre de commandes par région", lambda res, raw: {r[0]: r[1] for r in res["rows"]} == group(raw, lambda r: r["region"], lambda r: 1.0)),
    ("quantité médiane par produit", lambda res, raw: {r[0]: r[1] for r in res["rows"]}["Alpha"] == statistics.median(r["qte"] for r in raw if r["produit"] == "Alpha")),
    ("quantité totale vendue en 2024", lambda res, raw: res["scalar"] == sum(r["qte"] for r in raw if r["date"].year == 2024)),
    ("prix unitaire moyen par produit", lambda res, raw: close({r[0]: r[1] for r in res["rows"]}["Delta"], 310)),
    ("compare 2024 et 2025", lambda res, raw: close(res["totals"][0], sum(r["ca"] for r in raw if r["date"].year == 2024)) and close(res["totals"][1], sum(r["ca"] for r in raw if r["date"].year == 2025))),
    ("compare 2024 et 2025 par région", lambda res, raw: close({r[0]: r[2] for r in res["rows"]}["Nord"], sum(r["ca"] for r in raw if r["date"].year == 2025 and r["region"] == "Nord"))),
    ("CA de 2025 par rapport à 2024", lambda res, raw: res["kind"] == "compare" and res["change_pct"] == round(100 * (sum(r["ca"] for r in raw if r["date"].year == 2025) / sum(r["ca"] for r in raw if r["date"].year == 2024) - 1), 1)),
    ("corrélation entre prix et quantité", lambda res, raw: res["r"] == round(statistics.correlation([r["prix"] for r in raw], [r["qte"] for r in raw]), 3) or res["r"] == round(statistics.correlation([r["qte"] for r in raw], [r["prix"] for r in raw]), 3)),
    ("distribution du CA", lambda res, raw: close(res["stats"]["median"], statistics.median(map(_ca, raw)))),
    ("CA maximum", lambda res, raw: close(res["scalar"], max(map(_ca, raw)))),
    ("average revenue per month", lambda res, raw: res["kind"] == "time" and len(res["rows"]) == 24),
    ("total des ventes dans l'Est", lambda res, raw: close(res["scalar"], sum(r["ca"] for r in raw if r["region"] == "Est"))),
    ("top 10 clients by revenue", lambda res, raw: len(res["rows"]) == 10 and close(res["rows"][0][1], max(group(raw, lambda r: r["client"], _ca).values()))),
]  # fmt: skip


@pytest.mark.parametrize("question,check", QUESTIONS, ids=[q for q, _ in QUESTIONS])
def test_question_gives_the_right_numbers(frame, raw, question, check):
    plan = plan_question(frame, question)
    assert plan is not None, question
    res = run_query(frame, plan["query"], "en" if question.isascii() and " des " not in question else "fr")
    assert check(res, raw), (question, plan["query"], res["rows"][:5], res.get("scalar"))
    json.dumps(res, default=str)


@pytest.mark.parametrize(
    "question",
    ["résume ce fichier", "traduis ce tableau en anglais", "rédige un mail à Paul avec ces chiffres", "bonjour",
     "explique-moi ce que contient le fichier"],
)  # fmt: skip
def test_non_questions_are_left_to_the_model(frame, question):
    assert plan_question(frame, question) is None


def test_query_is_safe(frame):
    for bad in [
        {"op": "drop"}, {"agg": "sum", "measure": "Nope"}, {"agg": "eval", "measure": "CA (€)"},
        {"agg": "sum", "measure": "Région"}, {"agg": "sum", "measure": "CA (€)", "top": 10_000, "by": "Client"},
        {"agg": "sum", "measure": "CA (€)", "filters": [{"col": "Région", "op": "__import__", "value": 1}]},
        {"op": "compare", "measure": "CA (€)", "years": [1990, 2024]}, "SELECT * FROM t",
    ]:  # fmt: skip
        with pytest.raises(QueryError):
            run_query(frame, bad)


def test_suggestions_are_computed(frame):
    s = suggestions(frame, "fr")
    assert 3 <= len(s) <= 5
    labels = [x["label"] for x in s]
    assert labels[0] == "Évolution mensuelle" and "Total par région" in labels and "Top 10 clients" in labels
    for x in s:
        assert x["result"]["rows"] and x["chart"]["v"] == 2 and x["chart"]["type"] in TYPES
    json.dumps(s)


# ---------------------------------------------------------------- number check of answers


def test_check_numbers_accepts_roundings_and_refuses_inventions():
    res = {"rows": [["Nord", 243706.63], ["Sud", 193196.63]], "total": 436903.26, "change_pct": 12.4}
    allowed = result_numbers(res)
    ok = ("Le Nord arrive en tête avec 243 706,63 €, soit environ 244 k€ ou 0,24 M€, devant le Sud (193 197 €). "
          "Le total atteint 436 903 € (+12,4 %). Les 2 régions ; en 2024.")  # fmt: skip
    assert check_numbers(ok, allowed) == []
    assert check_numbers("Nord : 250 000 €", allowed) == ["250 000 €"]
    assert check_numbers("une hausse de 15 %", allowed) == ["15 %"]
    assert check_numbers("Revenue was 243,706.63 in the North", allowed) == []
    assert check_numbers("Comme vous l'avez dit, 7 500 €", allowed, request="budget de 7 500 €") == []


# ---------------------------------------------------------------- v2 chart spec


def test_auto_type():
    one = [{"name": "CA", "values": [1, 2, 3]}]
    assert auto_type(["janv. 2024", "févr. 2024", "mars 2024"], one)[0] == "line"
    assert auto_type(["A", "B", "C"], one, "répartition du budget")[0] == "donut"
    assert auto_type([f"Client {i}" for i in range(12)], [{"name": "CA", "values": list(range(12))}])[0] == "hbar"
    assert auto_type(["A", "B", "C"], one, kind="scatter")[0] == "scatter"
    assert auto_type(["A", "B"], one)[0] == "bar"


def test_chart_refuses_invented_values():
    args = {"title": "CA", "columns": ["Région", "CA"], "rows": [["Nord", 120], ["Sud", 99]], "type": "donut"}
    normalize_spec(args, allowed=[120, 99, 3])
    with pytest.raises(ToolError, match="not in the data"):
        normalize_spec(args, allowed=[120, 98])


def test_chart_spec_fuzz():
    rng = random.Random(42)
    junk = [None, "", "abc", "12,5", "1 200 €", 3, -4.5, float("nan"), True, [], {}, "=A1", 1e308]
    for _ in range(800):
        n = rng.randint(0, 9)
        width = rng.randint(1, 4)
        args = {"title": rng.choice(["", "T", "x" * 300, None]), "type": rng.choice([*TYPES, "nope", None, "Barres"]),
                "columns": [f"c{j}" for j in range(rng.randint(0, width))],
                "rows": [[rng.choice(["a", "b", 1, None])] + [rng.choice(junk) for _ in range(width - 1)]
                         for _ in range(n)],
                "sort": rng.choice([None, "desc", "asc", "x"]), "top": rng.choice([None, 2, 0, -1, "3"]),
                "annotations": rng.choice([None, ["max"], [{"kind": "target", "value": 5}], "x"])}  # fmt: skip
        if rng.random() < 0.15:
            args = {
                "points": [[i, rng.choice(junk), rng.choice(junk)] for i in range(n)],
                "type": rng.choice(["scatter", None]),
            }
        try:
            spec = normalize_spec(args, rng.choice(["fr", "en"]))
        except ToolError:
            continue
        assert spec["type"] in TYPES
        text = json.dumps(spec, allow_nan=False)  # JSON-safe, no NaN
        assert len(spec["labels"]) == len(spec["rows"]) or spec.get("points")
        for s in spec["series"]:
            assert len(s["values"]) == len(spec["labels"])
            assert all(v is None or (isinstance(v, float) and math.isfinite(v)) for v in s["values"])
        assert "nan" not in text.lower() or "nan" in str(args).lower()


def test_chart_from_each_result_kind(frame):
    kinds = set()
    for q in ["CA par mois", "top 5 des clients", "répartition par région", "compare 2024 et 2025", "combien de clients ?",
              "corrélation entre prix et quantité", "distribution du CA"]:  # fmt: skip
        res = run_query(frame, plan_question(frame, q)["query"])
        spec = chart_from_result(res, "fr", "analysis", "ventes.csv")
        kinds.add(spec["type"])
        assert spec["source"] == "analysis" and spec["source_label"] == "ventes.csv"
        json.dumps(spec, allow_nan=False)
    assert kinds >= {"line", "hbar", "donut", "bar", "kpi", "scatter", "box"}


def test_make_chart_tool_v2_types(tmp_path):
    from birds.harness.tools.chart import make_chart

    ctx = SimpleNamespace(charts=[], lang="fr", request="parts : Web 45, Magasin 30, Partenaires 25", message="",
                          fetched=[], step_info=None)  # fmt: skip
    ctx.message = ctx.request
    args = {"title": "Canaux", "type": "donut", "columns": ["Canal", "Part"],
            "rows": [["Web", 45], ["Magasin", 30], ["Partenaires", 25]]}  # fmt: skip
    out = make_chart(args, ctx)
    assert ctx.charts[0]["v"] == 2 and ctx.charts[0]["type"] == "donut" and "Chart displayed" in out
    with pytest.raises(ToolError, match="not in the data"):
        make_chart({**args, "rows": [["Web", 50], ["Magasin", 30], ["Partenaires", 20]]}, ctx)


# ---------------------------------------------------------------- hooks around a run


def test_prepare_and_finish(tmp_path):
    (tmp_path / "ventes.csv").write_bytes((DATA / "ventes.csv").read_bytes())
    prep = prepare(tmp_path, ["ventes.csv"], "top 3 des clients", "fr")
    assert prep is not None and prep.result["kind"] == "ranking" and prep.card["type"] == "datacard"
    assert "Richard Énergie" in prep.note and strip_note("Bonjour" + prep.note) == "Bonjour"
    assert len(json.dumps(prep.card)) < 60_000
    good = SimpleNamespace(answer="Richard Énergie mène avec 124 158 €, devant Simon Retail (119 274 €).", charts=[],
                           report={})  # fmt: skip
    finish(good, prep)
    assert good.answer.startswith("Richard") and good.charts[0]["v"] == 2 and good.report["data_check"] == {"ok": True}
    bad = SimpleNamespace(answer="Richard Énergie mène avec 150 000 €.", charts=[], report={})
    finish(bad, prep)
    assert "150 000" not in bad.answer and "124" in bad.answer and bad.report["data_check"]["replaced"]


def test_prepare_pasted_table_and_nothing(tmp_path):
    words = "Quel est le total par équipe ?\nÉquipe;Heures\nA;12,5\nB;30\nC;7,25\nA;4"
    prep = prepare(tmp_path, [], words, "fr")
    assert prep is not None and prep.card["origin"] == "pasted"
    assert {r[0]: r[1] for r in prep.result["rows"]} == {"A": 16.5, "B": 30, "C": 7.25}
    assert prepare(tmp_path, [], "bonjour, ça va ?", "fr") is None
    (tmp_path / "note.txt").write_text("Une note sans tableau.\nDeux lignes.", encoding="utf-8")
    assert prepare(tmp_path, ["note.txt"], "résume", "fr") is None


# ---------------------------------------------------------------- web routes and the demo


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from birds.web.server import create_app
    from birds.web.settings import Settings

    s = Settings(demo_delay=0.0, signing_secret=b"x" * 32, signing="configured", rate_limit=0)
    with TestClient(create_app(s)) as c:
        yield c


def test_data_routes(client):
    content = (DATA / "ventes.csv").read_text(encoding="utf-8")
    r = client.post("/api/data/table", json={"name": "ventes.csv", "content": content})
    assert r.status_code == 200 and r.json()["n"] == 480 and len(r.json()["rows"]) == 480
    r = client.post(
        "/api/data/query", json={"name": "ventes.csv", "content": content, "question": "top 3 des produits"}
    )
    body = r.json()
    assert body["ok"] and body["chart"]["type"] == "hbar" and len(body["result"]["rows"]) == 3
    r = client.post("/api/data/query", json={"name": "ventes.csv", "content": content, "query": {"op": "drop"}})
    assert r.json()["ok"] is False
    import base64

    b64 = base64.b64encode((DATA / "budget_fusion.xlsx").read_bytes()).decode()
    r = client.post("/api/data/table", json={"name": "budget.xlsx", "content": b64, "encoding": "base64"})
    assert r.status_code == 200 and r.json()["columns"][1]["name"] == "2024 Prévu"
    assert (
        client.post("/api/data/table", json={"name": "x.pdf", "content": "aaaa", "encoding": "base64"}).status_code
        == 415
    )
    r = client.post("/api/data/table", json={"name": "a.csv", "content": "x"}, headers={"origin": "https://evil.test"})
    assert r.status_code == 403


def test_demo_chat_with_a_csv_shows_the_card(client):
    content = (DATA / "ventes.csv").read_text(encoding="utf-8")
    body = {"messages": [{"role": "user", "content": "quel est le CA moyen par mois ?"}], "lang": "fr",
            "attachments": [{"name": "ventes.csv", "content": content}]}  # fmt: skip
    r = client.post("/api/chat", json=body)
    events = [json.loads(f[6:]) for f in r.text.split("\n\n") if f.startswith("data: ")]
    answer = next(e for e in events if e["type"] == "answer")
    card = answer["widgets"][0]
    assert card["type"] == "datacard" and card["rows"] == 480 and card["answer"]["chart"]["type"] == "line"
    assert answer["charts"][0]["v"] == 2 and "Moyenne de CA" in answer["content"]


def test_csv_text_is_not_bigger_than_needed():
    t = read_text_table("a;b\n" + "\n".join(f"{i};{i * 1.5}".replace(".", ",") for i in range(60000)), "big.csv")
    assert t.shape == (50000, 2) and t.meta["truncated"]


def test_dict_reader_sanity():
    # the fixture is the documented messy shape: a title line, a blank line, a BOM, a blank line in the middle
    text = (DATA / "ventes.csv").read_text(encoding="utf-8")
    assert text.startswith("﻿Export") and "\n\n" in text[100:]
    assert io.StringIO(text).readline().strip()
