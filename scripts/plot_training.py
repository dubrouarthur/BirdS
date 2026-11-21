"""Plot the training curve of a run from its job log lines.

hf jobs logs <job> | grep -E "train \\{|eval step" > out/curves/run.log
python scripts/plot_training.py --log out/curves/run.log --out docs/curves/bird-v0.png --total-steps 1646
"""

import argparse
import ast
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--log", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--total-steps", type=int, default=0)
ap.add_argument("--title", default="Bird v0 — perte pendant l'entraînement")
a = ap.parse_args()

train, evals = [], []
for line in Path(a.log).read_text().splitlines():
    if m := re.search(r"train (\{'step'.*\})", line):
        d = ast.literal_eval(m.group(1))
        train.append((d["step"], d["loss"], d["minutes"], d["energy_wh"]))
    elif m := re.search(r"eval step (\d+) ([\d.]+)", line):
        evals.append((int(m.group(1)), float(m.group(2))))

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"  # categorical slots 1 and 2 (validated pair)
fig, ax = plt.subplots(figsize=(9, 4.8), dpi=200, facecolor=SURFACE)
ax.set_facecolor(SURFACE)
ax.plot(
    [s for s, *_ in train],
    [v for _, v, *_ in train],
    color=BLUE,
    lw=2,
    solid_capstyle="round",
    label="Entraînement (moyenne sur 25 étapes)",
)
ax.plot(
    [s for s, _ in evals],
    [v for _, v in evals],
    color=ORANGE,
    lw=2,
    marker="o",
    ms=8,
    mec=SURFACE,
    mew=2,
    label="Évaluation (conversations mises de côté)",
)
for s, v in evals:
    ax.annotate(
        f"{v:.3f}".replace(".", ","),
        (s, v),
        textcoords="offset points",
        xytext=(9, 9),
        ha="left",
        fontsize=9,
        color=INK,
    )
last = train[-1]
ax.set_xlim(0, a.total_steps or last[0] * 1.05)
ax.set_ylim(0.5, max(v for _, v in evals) + 0.05)
if a.total_steps:
    ax.axvline(last[0], color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.text(
        last[0] + a.total_steps * 0.008,
        0.51,
        f"étape {last[0]} sur {a.total_steps}",
        fontsize=9,
        color=MUTED,
        va="bottom",
    )
ax.set_xlabel("Étape d'entraînement", color=MUTED, fontsize=10)
ax.set_ylabel("Perte (plus bas = mieux)", color=MUTED, fontsize=10)
ax.grid(axis="y", color=GRID, lw=1)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(GRID)
ax.tick_params(colors=MUTED, length=0, labelsize=9)
ax.yaxis.set_major_formatter(lambda v, _: f"{v:.2f}".replace(".", ","))
ax.legend(frameon=False, fontsize=9.5, loc="upper right", labelcolor=INK)
ax.set_title(a.title, loc="left", fontsize=13, color=INK, pad=24, fontweight="bold")
sub = f"{last[2]:.0f} min écoulées · {last[3]:.0f} Wh mesurés sur le GPU".replace(".", ",")
ax.text(0, 1.03, sub, transform=ax.transAxes, fontsize=9.5, color=MUTED)
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
fig.tight_layout()
fig.savefig(a.out, facecolor=SURFACE)
print(f"wrote {a.out}: {len(train)} train points, {len(evals)} eval points")
