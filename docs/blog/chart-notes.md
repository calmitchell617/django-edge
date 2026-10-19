# Charts for the Django D1 benchmark post

Use `django-d1-chart-data.csv`. It contains three architecture rows for **ten concurrent clients**, pooled across three repetitions and the alternating list/detail workload. Warmup requests are excluded.

## Throughput chart

This is the closest match to the existing PostgreSQL 16 vs 17 payments-per-second bar chart:

- Category: `Architecture`.
- Value: `Successful API requests per second`.
- Title: **"Across the world" Django API throughput with Cloudflare D1 caching**.
- Y-axis: **Successful API requests per second**. Start at zero; higher is better.
- Keep the existing white background, bold black title and labels, light horizontal gridlines, blue columns, and DataSystemReviews.com branding.
- Display values to two decimal places: **2.31**, **2.53**, **12.80**.
- Caption: **Ten concurrent clients, three repetitions per architecture, warmup excluded. Servers in Australia, PostgreSQL in Amsterdam.**

## Latency chart

`assets/django-d1-latency.png` and its editable SVG match the throughput chart, including the title's “Across the world” prefix, branding, geography caption, and three architecture categories. Values come from `Median API latency (ms)` in the same CSV: **3,922.96**, **3,591.28**, and **493.33** ms, displayed as **3,923**, **3,591**, and **493**. The axis starts at zero and states **Median API latency (ms)**; lower is better. These are client-observed API request times, not isolated SQL query timings.

```sh
uv run --no-project --with matplotlib --with svgpath2mpl docs/blog/render_chart.py --metric latency
```

Do not put throughput and latency on one shared value axis. If publishing the median chart, retain the post's p95 table and tail-latency discussion.

## Data provenance

The CSV is calculated directly from:

- [Measured requests](../../benchmark/results/2026-10-18-reference/requests.jsonl).
- [Actual elapsed trial durations](../../benchmark/results/2026-10-18-reference/trials.jsonl).

Median and p95 pool successful requests at concurrency ten, using linear interpolation between sorted observations. They are not averages of the endpoint percentiles or repetition percentiles. Throughput is the sum of successful requests divided by the sum of matching trial elapsed times, including in-flight completion. Values are rounded to two decimal places for chart import. Every measured request succeeded.

The records do not contain request start timestamps suitable for a per-minute time series, and the trial windows are short. The comparison bar chart uses the measured data without inventing a time series.

## Publishing notes

The synchronization illustration is `assets/django-d1-sync-table.png` (2560 × 896), with an editable SVG alongside it. It shows five states of one row: in sync, edited, copied to D1, deleted pending synchronization, and deletion synced to D1. `needs_sync` and `is_deleted` values are color-coded. The final row clears `needs_sync` while retaining `is_deleted=true` and the same version. The columns match the implementation: `needs_sync`, `sync_version`, and the boolean `is_deleted`. Versions are explanatory examples, not benchmark observations.

```sh
uv run --no-project --with matplotlib docs/blog/render_sync_table.py
```

The article is plain Markdown with a rendered architecture PNG and two fenced Mermaid sequence diagrams. Each diagram has a prose explanation. Enable Mermaid rendering in the site for the sequence diagrams.

The architecture section embeds `assets/django-d1-architecture.png` (2560 × 1280). An editable vector copy is available as `assets/django-d1-architecture.svg`. Both match the throughput chart's white background, blue gradient, and bold black type. The architecture diagram omits the logo, attribution, region subtitles, and bottom captions. The diagram separates application queries from background synchronization and D1-managed replication. Client location is not presented as Australian; the report records London ingress and an unverified physical location.

Regenerate the architecture assets from the repository root:

```sh
uv run --no-project --with matplotlib docs/blog/render_architecture.py
```

The throughput chart is embedded in the article's results section as `assets/django-d1-throughput.png`. Publish that asset alongside the Markdown, preserving the relative path or adjusting the image URL for the site. An editable vector copy is available as `assets/django-d1-throughput.svg`. Both use the site's existing logo, blue gradient columns, bold labels, and white background.

To regenerate both files from the CSV, run this from the repository root:

```sh
uv run --no-project --with matplotlib --with svgpath2mpl docs/blog/render_chart.py
```

The renderer uses `assets/data-system-reviews.svg`, downloaded from the site's logo asset.

The draft's GitHub links target this repository's `main` branch. Commit and push the implementation and result files before publishing the article so those links expose the new material. This task creates local drafts and chart data; it does not publish the site or push the repository.
