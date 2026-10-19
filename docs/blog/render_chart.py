"""Render the article's throughput or latency chart from its published CSV.

Run: uv run --no-project --with matplotlib --with svgpath2mpl docs/blog/render_chart.py
Add --metric latency to render median API latency.
"""

import argparse
import csv
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Ellipse, PathPatch
from matplotlib.path import Path as PlotPath
import numpy as np
from svgpath2mpl import parse_path


HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--metric", choices=("throughput", "latency"), default="throughput")
args = parser.parse_args()
latency = args.metric == "latency"
column = "Median API latency (ms)" if latency else "Successful API requests per second"
title = f'"Across the world"\nDjango API {args.metric} with D1 caching'
limit = 4500 if latency else 15
with (HERE / "django-d1-chart-data.csv").open(newline="") as source:
    rows = list(csv.DictReader(source))
values = [float(row[column]) for row in rows]
labels = [
    row["Architecture"].replace(" only", "\nonly").replace(" cache", "\ncache") for row in rows
]
labels[-1] = "D1 auth +\ncontent cache"

plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})
fig = plt.figure(figsize=(14, 11.2), facecolor="white")
fig.text(
    0.5,
    0.93,
    title,
    ha="center",
    va="center",
    fontsize=29,
    weight="bold",
)

# Render the site's own vector logo, preserving its path and white details.
logo = fig.add_axes((0.245, 0.796, 0.067, 0.069))
root = ET.parse(ASSETS / "data-system-reviews.svg").getroot()
ns = {"svg": "http://www.w3.org/2000/svg"}
for element in root.findall(".//svg:path", ns):
    logo.add_patch(PathPatch(parse_path(element.attrib["d"]), facecolor="black", lw=0))
for element in root.findall(".//svg:ellipse", ns):
    attr = element.attrib
    logo.add_patch(
        Ellipse(
            (float(attr["cx"]), float(attr["cy"])),
            2 * float(attr["rx"]),
            2 * float(attr["ry"]),
            facecolor="white",
            lw=0,
        )
    )
logo.set(xlim=(0, 647), ylim=(432, 0), aspect="equal")
logo.axis("off")
fig.text(0.335, 0.847, "Independent benchmark by", fontsize=23, va="center")
fig.text(
    0.335, 0.806, "DataSystemReviews.com", fontsize=23, va="center", weight="bold", style="italic"
)

ax = fig.add_axes((0.16, 0.17, 0.79, 0.54))
ax.set(xlim=(-0.6, 2.6), ylim=(0, limit),
       yticks=range(0, 4501, 900) if latency else range(0, 16, 3))
ax.set_axisbelow(True)
ax.yaxis.grid(True, color="#c6c6c6", linewidth=1)
ax.spines[["top", "right"]].set_visible(False)
for side in ("left", "bottom"):
    ax.spines[side].set_linewidth(1.5)
ax.tick_params(axis="both", length=0, labelsize=20, pad=14)
ax.set_xticks(range(3), labels, weight="bold", fontsize=18)
ax.set_ylabel(column, fontsize=20, weight="bold", labelpad=22)

blue = LinearSegmentedColormap.from_list("dsr_blue", ["#49baf3", "#007fba"])
gradient = np.linspace(0, 1, 512).reshape(-1, 1)
for position, value in enumerate(values):
    left, right = position - 0.36, position + 0.36
    radius_x, radius_y = 0.045, limit * 0.22 / 15
    # Rounded upper corners, with a flat baseline at exactly zero.
    vertices = [
        (left, 0),
        (left, value - radius_y),
        (left, value),
        (left + radius_x, value),
        (right - radius_x, value),
        (right, value),
        (right, value - radius_y),
        (right, 0),
        (left, 0),
    ]
    codes = [
        PlotPath.MOVETO,
        PlotPath.LINETO,
        PlotPath.CURVE3,
        PlotPath.CURVE3,
        PlotPath.LINETO,
        PlotPath.CURVE3,
        PlotPath.CURVE3,
        PlotPath.LINETO,
        PlotPath.CLOSEPOLY,
    ]
    clip = PathPatch(PlotPath(vertices, codes), facecolor="none", lw=0)
    ax.add_patch(clip)
    bar = ax.imshow(
        gradient,
        extent=(left, right, 0, value),
        origin="lower",
        aspect="auto",
        cmap=blue,
        vmin=0,
        vmax=1,
        zorder=3,
    )
    bar.set_clip_path(clip)
    ax.text(
        position,
        value - limit * 0.38 / 15,
        f"{value:,.0f}" if latency else f"{value:.2f}",
        ha="center",
        va="top",
        color="white",
        fontsize=24,
        weight="bold",
        zorder=4,
    )

fig.text(
    0.55,
    0.055,
    "Ten concurrent clients · Three repetitions · Warmup excluded",
    ha="center",
    fontsize=14,
    color="#444444",
)
fig.text(
    0.55,
    0.029,
    "Servers in Australia, PostgreSQL in Amsterdam · " + ("Lower is better" if latency else "Higher is better"),
    ha="center",
    fontsize=14,
    color="#444444",
)
for extension in ("png", "svg"):
    destination = ASSETS / f"django-d1-{args.metric}.{extension}"
    fig.savefig(
        destination,
        dpi=150,
        facecolor="white",
        metadata={"Title": title.replace("\n", " ")},
    )
    print(destination)
plt.close(fig)
