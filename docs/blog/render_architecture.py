"""Render the article's architecture in the Data System Reviews chart style.

Run: uv run --no-project --with matplotlib docs/blog/render_architecture.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np


ASSETS = Path(__file__).resolve().parent / "assets"
BLUE = "#007fba"
INK = "#161616"

plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})
fig = plt.figure(figsize=(16, 8), facecolor="white")
ax = fig.add_axes((0, 0, 1, 1))
ax.set(xlim=(0, 1600), ylim=(950, 150))
ax.axis("off")


def text(x, y, content, size=18, color=INK, weight="normal", **kwargs):
    return ax.text(
        x, y, content, ha="center", va="center", fontsize=size,
        color=color, weight=weight, zorder=5, **kwargs,
    )


def box(x, y, width, height, title, *, blue=False):
    patch = FancyBboxPatch(
        (x, y), width, height, boxstyle="round,pad=0,rounding_size=14",
        facecolor="none" if blue else "white",
        edgecolor=BLUE if blue else INK, linewidth=1.8, zorder=3,
    )
    ax.add_patch(patch)
    if blue:
        gradient = ax.imshow(
            np.linspace(1, 0, 256).reshape(-1, 1),
            extent=(x, x + width, y + height, y), aspect="auto",
            cmap=LinearSegmentedColormap.from_list("dsr_blue", ["#49baf3", BLUE]),
            zorder=2,
        )
        gradient.set_clip_path(patch)
    color = "white" if blue else INK
    text(x + width / 2, y + height / 2, title, 23, color, "bold")


def arrow(start, end, *, blue=False, dashed=False):
    ax.add_patch(FancyArrowPatch(
        start, end, arrowstyle="-|>", mutation_scale=20,
        linewidth=2.5, color=BLUE if blue else INK,
        linestyle=(0, (6, 5)) if dashed else "solid", zorder=4,
        shrinkA=0, shrinkB=0,
    ))


text(800, 208, "D1 as a relational cache for Django", 32, weight="bold")

# The replica and app are nearby; the source and cache writer stay in Europe.
for x, width, title in (
    (55, 590, "AUSTRALIA / OCEANIA"),
    (955, 590, "WESTERN EUROPE"),
):
    ax.add_patch(FancyBboxPatch(
        (x, 290), width, 630, boxstyle="round,pad=0,rounding_size=18",
        facecolor="#f6f8fa", edgecolor="#d4dbe1", linewidth=1.4, zorder=0,
    ))
    text(x + width / 2, 320, title, 18, weight="bold")

# Clients are deliberately outside the region: their physical location was unverified.
box(675, 255, 250, 100, "HTTP clients")
ax.plot([800, 800, 350], [355, 410, 410], color=INK, linewidth=2.5, zorder=4)
arrow((350, 410), (350, 455))

box(150, 455, 400, 120, "Django Worker", blue=True)
box(1050, 455, 400, 120, "PostgreSQL")
box(1050, 645, 400, 100, "Sync companion")
box(1050, 800, 400, 100, "D1 primary", blue=True)
box(150, 800, 400, 100, "D1 read replica", blue=True)

arrow((550, 515), (1050, 515))
text(800, 469, "Authoritative reads\n+ all application writes", 17, linespacing=1.5)

arrow((350, 575), (350, 800), blue=True)
text(475, 687, "Nearby reads\n(stale data OK)", 17, BLUE, linespacing=1.5)

arrow((1250, 645), (1250, 575))
text(1104, 610, "Poll changes\n+ acknowledge", 15, linespacing=1.4)
arrow((1250, 745), (1250, 800), blue=True)
text(1100, 773, "Batch upserts", 15, BLUE)

arrow((1050, 850), (550, 850), blue=True, dashed=True)
text(800, 805, "D1 asynchronous\nread replication", 17, BLUE, linespacing=1.5)

for extension in ("png", "svg"):
    destination = ASSETS / f"django-d1-architecture.{extension}"
    fig.savefig(destination, dpi=160, facecolor="white", metadata={
        "Title": "D1 as a relational cache for Django",
        "Description": "Django queries PostgreSQL for authoritative reads and writes, and D1 for opted-in reads. A Durable Object mirrors pending PostgreSQL rows to D1's primary, which replicates asynchronously to Oceania.",
    })
    print(destination)
plt.close(fig)
