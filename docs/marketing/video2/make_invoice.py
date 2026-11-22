"""Fictional invoice for the shoot (made-up company, made-up client)."""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

out = sys.argv[1]
fig = plt.figure(figsize=(16, 10), dpi=100)
fig.patch.set_facecolor("white")
ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_xlim(0, 1600); ax.set_ylim(1000, 0)
k = dict(color="#111111", family="DejaVu Sans")
ax.text(80, 110, "Studio Pivert SARL (société fictive)", fontsize=26, weight="bold", **k)
ax.text(80, 165, "12 rue des Exemples, 00000 Imaginaire", fontsize=18, **k)
ax.text(1520, 110, "FACTURE n° 2026-117", fontsize=34, weight="bold", ha="right", **k)
ax.text(1520, 170, "Date : 14/11/2026", fontsize=22, ha="right", **k)
ax.text(80, 270, "Client : Atelier Lumen", fontsize=28, weight="bold", **k)
ax.plot([80, 1520], [340, 340], color="#111111", lw=2)
rows = [("Conception graphique", "1", "650,00 €"), ("Mise en page brochure", "1", "391,67 €")]
ax.text(80, 390, "Désignation", fontsize=20, weight="bold", **k)
ax.text(1100, 390, "Qté", fontsize=20, weight="bold", **k)
ax.text(1520, 390, "Montant HT", fontsize=20, weight="bold", ha="right", **k)
for j, (a, b, c) in enumerate(rows):
    y = 460 + j * 60
    ax.text(80, y, a, fontsize=20, **k); ax.text(1100, y, b, fontsize=20, **k)
    ax.text(1520, y, c, fontsize=20, ha="right", **k)
ax.plot([80, 1520], [600, 600], color="#888888", lw=1)
ax.text(1100, 660, "Total HT", fontsize=20, **k); ax.text(1520, 660, "1 041,67 €", fontsize=20, ha="right", **k)
ax.text(1100, 715, "TVA 20 %", fontsize=20, **k); ax.text(1520, 715, "208,33 €", fontsize=20, ha="right", **k)
ax.add_patch(plt.Rectangle((760, 760), 780, 100, fill=False, ec="#111111", lw=3))
ax.text(790, 828, "Total TTC : 1 250,00 €", fontsize=38, weight="bold", **k)
ax.text(80, 950, "Document fictif : société et client imaginaires.", fontsize=15, color="#555555")
fig.savefig(out, dpi=100, facecolor="white")
