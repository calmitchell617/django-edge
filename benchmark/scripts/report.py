"""Produce CSV, Markdown and an SVG chart from real JSONL benchmark outputs."""

import argparse
import csv
import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def summarize(rows, elapsed_s):
    successes = [r for r in rows if not r.get("error") and r.get("status") == 200]
    metrics = [r.get("metrics", {}) for r in successes]
    values = [r["client_ms"] for r in successes]
    connections = [value for metric in metrics for value in metric.get("pg_connect_ms", [])]

    def query_mean(alias):
        queries = [m.get("queries", {}).get(alias, {}) for m in metrics]
        count = sum(q.get("count", 0) for q in queries)
        return sum(q.get("ms", 0) for q in queries) / count if count else None

    def segment_p50(name):
        return percentile(
            [m["segments"][name] for m in metrics if name in m.get("segments", {})], 0.5
        )

    return {
        "requests": len(rows),
        "successes": len(successes),
        "errors": len(rows) - len(successes),
        "throughput_rps": len(successes) / elapsed_s if elapsed_s else 0,
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "server_p50_ms": percentile([m["server_ms"] for m in metrics if "server_ms" in m], 0.5),
        "pg_connect_p50_ms": percentile(connections, 0.5),
        "pg_query_mean_ms": query_mean("default"),
        "d1_query_mean_ms": query_mean("cache"),
        "auth_p50_ms": segment_p50("auth_ms"),
        "content_p50_ms": segment_p50("content_ms"),
        "pg_queries": sum(m.get("queries", {}).get("default", {}).get("count", 0) for m in metrics),
        "d1_queries": sum(m.get("queries", {}).get("cache", {}).get("count", 0) for m in metrics),
        "low_sample_p99": len(successes) < 1000,
    }


def chart(summaries):
    plotted = [r for r in summaries if r["p95_ms"] is not None]
    height = 80 + len(plotted) * 44
    maximum = max((r["p95_ms"] for r in plotted), default=1) or 1
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" '
        f'viewBox="0 0 900 {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Django API p95 latency by read policy</title>',
        '<desc id="desc">Bars show measured client latency in milliseconds. '
        "See the accompanying report for errors, placement and methodology.</desc>",
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="sans-serif" font-size="14" fill="#17202a">',
        '<text x="20" y="28" font-size="20">Measured request latency — p95 (ms)</text>',
    ]
    colors = {"postgres": "#566573", "auth_cache": "#2471a3", "all_cache": "#148f77"}
    for index, row in enumerate(plotted):
        y = 55 + index * 44
        width = row["p95_ms"] / maximum * 440
        label = html.escape(f"{row['policy']} · c={row['concurrency']} · {row['endpoint']}")
        parts += [
            f'<text x="20" y="{y + 18}">{label}</text>',
            f'<rect x="330" y="{y}" width="{width:.1f}" height="27" '
            f'fill="{colors[row["policy"]]}"/>',
            f'<text x="{340 + width:.1f}" y="{y + 18}">{row["p95_ms"]:.1f}</text>',
        ]
    return "\n".join(parts + ["</g></svg>"])


def make_report(directory, freshness_path=None):
    rows = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
    trials = [json.loads(line) for line in (directory / "trials.jsonl").read_text().splitlines()]
    environment = json.loads((directory / "environment.json").read_text())
    validation_path = directory / "runtime-validation.json"
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
    after_path = directory / "runtime-validation-after.json"
    after = json.loads(after_path.read_text()) if after_path.exists() else {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["policy"], row["concurrency"], row["endpoint"]].append(row)
    summaries = []
    for (policy, concurrency, endpoint), group in sorted(grouped.items()):
        elapsed = sum(
            t["elapsed_s"]
            for t in trials
            if t["policy"] == policy and t["concurrency"] == concurrency
        )
        summaries.append(
            {
                "policy": policy,
                "concurrency": concurrency,
                "endpoint": endpoint,
                **summarize(group, elapsed),
            }
        )
    if not summaries:
        raise ValueError("No measurement rows found")
    with (directory / "summary.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    (directory / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    (directory / "latency.svg").write_text(chart(summaries))
    placements = Counter(r.get("placement") or "unknown" for r in rows)
    regions = Counter(
        str(meta.get("served_by_region"))
        for r in rows
        for meta in r.get("metrics", {}).get("d1", [])
    )
    primary = Counter(
        str(meta.get("served_by_primary"))
        for r in rows
        for meta in r.get("metrics", {}).get("d1", [])
    )
    errors = Counter(r["error"] for r in rows if r.get("error"))
    routing_violations = Counter()
    for row in rows:
        if row.get("error") or row.get("status") != 200:
            continue
        queries = row.get("metrics", {}).get("queries", {})
        pg_count = queries.get("default", {}).get("count", 0)
        d1_count = queries.get("cache", {}).get("count", 0)
        expected_routing = {
            "postgres": pg_count > 0 and d1_count == 0,
            "auth_cache": pg_count > 0 and d1_count > 0,
            "all_cache": pg_count == 0 and d1_count > 0,
        }
        if not expected_routing.get(row["policy"], False):
            routing_violations[row["policy"]] += 1
    database_errors = Counter(
        error.get("sqlstate") or error.get("type", "unknown")
        for row in rows
        for error in row.get("metrics", {}).get("database_errors", [])
    )
    expected_colos = {"SYD", "MEL", "BNE", "PER", "ADL", "CBR", "HBA", "DRW"}
    geography_ok = bool(placements) and all(p.split("-")[-1] in expected_colos for p in placements)
    replica_ok = regions.get("OC", 0) > 0 and primary.get("False", 0) > 0

    def fmt(value):
        return "—" if value is None else f"{value:.2f}"

    lines = [
        "# Benchmark results",
        "",
        f"Run: {environment['started_utc']}",
        "",
        f"Client location: {environment['client_location']}",
        "",
        f"Revision: `{environment['git_commit']}`; dirty tree: {environment['git_dirty']}",
        "",
        "Authenticated HTTP requests, alternating list/detail, with warm-up excluded. "
        "Connections close after each request; client latency includes connection setup.",
        "",
        "| Policy | Clients | Endpoint | Success/total | p50 ms | p95 ms | p99 ms | Success/s |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in summaries:
        lines.append(
            f"| {r['policy']} | {r['concurrency']} | {r['endpoint']} | "
            f"{r['successes']} / {r['requests']} | {fmt(r['p50_ms'])} | {fmt(r['p95_ms'])} | "
            f"{fmt(r['p99_ms'])} | {fmt(r['throughput_rps'])} |"
        )
    lines += [
        "",
        "Percentiles use successful requests only. Failures remain in raw data and counts. "
        "Treat p99 as exploratory when a group has fewer than 1,000 successful samples.",
        "",
        "![Measured p95 latency](latency.svg)",
        "",
        "SQL call means include adapter and network time. PostgreSQL connection setup is "
        "reported separately. Authentication and content are request segment medians.",
        "",
        "| Policy | Clients | Endpoint | PG connect p50 ms | Auth p50 ms | Content p50 ms | "
        "PG SQL mean ms | D1 SQL mean ms |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in summaries:
        lines.append(
            f"| {r['policy']} | {r['concurrency']} | {r['endpoint']} | "
            f"{fmt(r['pg_connect_p50_ms'])} | {fmt(r['auth_p50_ms'])} | "
            f"{fmt(r['content_p50_ms'])} | {fmt(r['pg_query_mean_ms'])} | "
            f"{fmt(r['d1_query_mean_ms'])} |"
        )
    lines += [
        "",
        f"Worker placement counts: `{dict(placements)}`",
        "",
        f"D1 region counts: `{dict(regions)}`; primary flags: `{dict(primary)}`",
        "",
        f"Australian execution verified for every recorded request: **{geography_ok}**. "
        f"Oceania replica service observed: **{replica_ok}**.",
        "",
        "Out-of-band egress probes (not per-request placement): "
        f"HTTP Worker `{validation.get('probe_http', {}).get('egress_colo', 'unknown')}`; "
        f"sync companion `{validation.get('probe', {}).get('egress_colo', 'unknown')}`. "
        "These identify the colo serving an outbound Cloudflare trace request. "
        "They corroborate configured placement but do not replace missing per-request evidence.",
        "",
        "Post-run companion egress probe: "
        f"`{after.get('probe', {}).get('egress_colo', 'unknown')}` "
        f"at `{after.get('observed_utc', 'not recorded')}`.",
        "",
        "When per-request placement is unknown, location evidence is limited to the configured "
        "placement hint and out-of-band probes. Treat the geographic comparison as exploratory. "
        "If no Oceania replica service is observed, the intended replica comparison is unverified.",
        "",
        f"Errors: `{dict(errors)}`",
        "",
        f"Unexpected database routing among successful requests: `{dict(routing_violations)}`. "
        "Postgres mode must query only PostgreSQL; auth-cache mode must query both stores; "
        "all-cache mode must query only D1.",
        "",
        f"Database errors by SQLSTATE/type: `{dict(database_errors)}`. "
        "SQLSTATE 53300 indicates too many connections. Clients are capped at 10 "
        "for the declared 20-connection limit; sync uses one additional connection.",
        "",
        "Synchronization snapshots appear in `trials.jsonl`; connection and query timings, "
        "authentication/content segments, and per-request placement appear in `requests.jsonl`. "
        "Propagation scenarios are recorded separately by the freshness command.",
        "",
    ]
    if freshness_path is not None:
        freshness = json.loads(freshness_path.read_text())
        lines += [
            "## Freshness observations",
            "",
            "Elapsed time at the client after each mutation response, including observation "
            "round trips. These are visibility observations, not exact replication lag or a "
            "one-second freshness guarantee.",
            "",
            "| Event | Primary visible ms | Cached read visible ms | Read attempts |",
            "|---|---:|---:|---:|",
        ]
        for event in freshness:
            primary_result = event["primary"]
            replica_result = event["australian_read"]
            lines.append(
                f"| {event['event']} | {fmt(primary_result['visible_ms'])} | "
                f"{fmt(replica_result['visible_ms'])} | {replica_result['attempts']} |"
            )
        lines.append("")
    (directory / "report.md").write_text("\n".join(lines))
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--freshness", type=Path, help="Optional freshness.json from a separate run"
    )
    arguments = parser.parse_args()
    make_report(arguments.directory, arguments.freshness)
    print(f"Wrote report, CSV, JSON and SVG to {arguments.directory}")
