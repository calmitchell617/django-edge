"""Illustrate sync metadata with one row's lifecycle.

Run: uv run --no-project --with matplotlib docs/blog/render_sync_table.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


ASSETS = Path(__file__).resolve().parent / "assets"
BLUE = "#007fba"
INK = "#161616"
plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})

# Illustrative states of the same PostgreSQL row.
HEADERS = ["Row state", "needs_sync\nCopy needed?", "sync_version\nChange number", "is_deleted\nDeleted?"]
ROWS = [
    ["In sync", "false", "1", "false"],
    ["Edited", "true", "2", "false"],
    ["Copied to D1", "false", "2", "false"],
    ["Deleted", "true", "3", "true"],
    ["Deletion synced to D1", "false", "3", "true"],
]

fig = plt.figure(figsize=(16, 5.6), facecolor="white")
ax = fig.add_axes((0, 0, 1, 1))
ax.set(xlim=(0, 1600), ylim=(560, 0))
ax.axis("off")
ax.text(800, 65, "How one row stays in sync", ha="center", va="center",
        fontsize=30, weight="bold", color=INK)

edges = [50, 560, 890, 1220, 1550]
top, row_height = 125, 65
ax.add_patch(Rectangle((edges[0], top), edges[-1] - edges[0], row_height,
                       facecolor=BLUE, linewidth=0))
for col, heading in enumerate(HEADERS):
    ax.text((edges[col] + edges[col + 1]) / 2, top + row_height / 2,
            heading, ha="center", va="center", fontsize=17,
            color="white", weight="bold", linespacing=1.4)

for row_index, row in enumerate(ROWS):
    y = top + (row_index + 1) * row_height
    ax.add_patch(Rectangle((edges[0], y), edges[-1] - edges[0], row_height,
                           facecolor="#f1f7fb" if row_index % 2 == 0 else "white",
                           linewidth=0))
    ax.plot([edges[0], edges[-1]], [y + row_height, y + row_height],
            color="#d4dbe1", linewidth=0.8)
    for col, value in enumerate(row):
        color = INK
        if col in (1, 3):
            active = "#875600" if col == 1 else "#a61b1b"
            color = active if value == "true" else "#17613b"
        x = edges[col] + 17 if col == 0 else (edges[col] + edges[col + 1]) / 2
        ax.text(x, y + row_height / 2, value,
                ha="left" if col == 0 else "center", va="center", fontsize=16,
                color=color, weight="bold" if col else "normal")

for extension in ("png", "svg"):
    destination = ASSETS / f"django-d1-sync-table.{extension}"
    fig.savefig(destination, dpi=160, facecolor="white", metadata={
        "Title": "How one row stays in sync",
        "Description": "Five illustrative PostgreSQL row states: in sync, edited, copied and acknowledged, soft-deleted pending synchronization, and deletion copied and acknowledged. needs_sync and is_deleted values are color-coded.",
    })
    print(destination)
plt.close(fig)
