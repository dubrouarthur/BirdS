"""Regenerate the data-analysis fixtures (deterministic). Run: .venv/bin/python -I tests/fixtures/data/make_fixtures.py"""

import datetime as dt
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fr(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def ventes() -> None:
    random.seed(7)
    regions = ["Nord", "Sud", "Est", "Ouest", "Île-de-France"]
    products = [("Alpha", 120.0), ("Beta", 85.5), ("Gamma", 42.0), ("Delta", 310.0), ("Epsilon", 19.9), ("Zeta", 64.0)]
    clients = [
        "Durand SA",
        "Martin & Fils",
        "Petit SARL",
        "Bernard Industries",
        "Robert Conseil",
        "Richard Énergie",
        "Dubois Logistique",
        "Moreau Santé",
        "Laurent Bâtiment",
        "Simon Retail",
        "Michel Agro",
        "Lefebvre Tech",
    ]
    reps = ["Camille", "Hugo", "Léa", "Nathan"]
    lines = [
        "Export ERP — ventes 2024-2025",
        "",
        "Date;Région;Produit;Client;Commercial;Quantité;Prix unitaire (€);CA (€);Remise",
    ]
    d0 = dt.date(2024, 1, 2)
    for i in range(480):
        d = d0 + dt.timedelta(days=int(i * 728 / 480) + random.randint(0, 1))
        r = random.choice(regions)
        p, price = random.choice(products)
        c, rep = random.choice(clients), random.choice(reps)
        q = random.randint(1, 40)
        if d.year == 2025:
            q = int(q * 1.12) + 1
        if r == "Île-de-France":
            q += 5
        ca = round(q * price * (1 - 0.05 * random.randint(0, 2)), 2)
        rem = random.choice(["0 %", "5 %", "10 %", "-"])
        lines.append(f"{d.strftime('%d/%m/%Y')};{r};{p};{c};{rep};{q};{fr(price)};{fr(ca)};{rem}")
        if i == 200:
            lines.append("")
    (HERE / "ventes.csv").write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")


def xlsx_merged() -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    ws["A1"] = "Budget par service (k€)"
    ws.append([])
    ws.append(["Service", "2024", None, "2025", None])
    ws.append([None, "Prévu", "Réel", "Prévu", "Réel"])
    ws.merge_cells("A3:A4")
    ws.merge_cells("B3:C3")
    ws.merge_cells("D3:E3")
    data = [("Marketing", 120, 131.5), ("Ventes", 340, 322), ("R&D", 510, 548.25), ("RH", 95, 91), ("IT", 210, 236)]
    for name, a, b in data:
        ws.append([name, a, b, round(a * 1.08, 2), round(b * 1.05, 2)])
    ws.append(["Total", sum(x[1] for x in data), sum(x[2] for x in data), None, None])
    wb.save(HERE / "budget_fusion.xlsx")


if __name__ == "__main__":
    ventes()
    xlsx_merged()
