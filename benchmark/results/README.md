# Experiment results

The [2026-10-18 report](2026-10-18-reference/report.md) contains the completed 18-trial latency run: 1,999 requests and zero errors. Its six freshness observations are stored in `2026-10-18-freshness/freshness.json`. Do not interpret test fixtures or the short smoke run under ignored `private/` as the full benchmark.

Each latency run writes `environment.json`, `runtime-validation.json`, `requests.jsonl`, and `trials.jsonl` into its own new directory. The report command adds `summary.csv`, `summary.json`, `report.md`, and `latency.svg`. Freshness runs write a separate `freshness.json`; pass it to the report with `--freshness` to include the six visibility observations.

Raw request records exclude credentials, cookies, bearer tokens, request bodies, and exception messages. Inspect any additional artifacts before publication. `private/` is ignored for temporary material that should not be published.
