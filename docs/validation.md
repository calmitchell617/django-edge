# Validation status

## Passed checks

- Native test suite: 36 tests, 31 passed and five opt-in PostgreSQL tests skipped. Coverage includes Django API and session behavior, routing, replication races, rollback, scheduling, packaging, diagnostics, measurement handling, and reports.
- The operator separately ran all five real PostgreSQL trigger tests successfully against the dedicated Aiven database. Those tests applied migrations and rolled back their test rows.
- Model/migration consistency, Ruff lint, and formatting checks pass. The upstream `workers-py/` dependency has no source changes.
- Deployed HTTP Worker and Durable Object probes passed direct PostgreSQL TLS, transaction rollback, and password hashing/verification. The D1 atomic batch rollback probe passed.
- Both database migrations completed. Seeding created 100 users and 10,000 posts, the initial backlog drained, and login plus D1 reads passed.
- The full API benchmark completed 18 trials: three policies, concurrency 1 and 10, three repetitions, 10-second warmups and 30-second measurement windows. All 1,999 measured requests succeeded, with no database routing mismatches or recorded database errors.
- All 5,694 recorded D1 query observations reported an Oceania replica rather than the primary.
- All six freshness scenarios passed: login, insert, update, soft delete, logout with the revoked cookie, and account deactivation. Cached visibility was observed 402–1,127 ms after mutation responses, including polling and transport.
- Final synchronization status has zero failures and zero pending rows. The companion alarm is stopped after the experiment.

## Results and evidence

See the [full report](../benchmark/results/2026-10-18-reference/report.md), [raw freshness observations](../benchmark/results/2026-10-18-freshness/freshness.json), and the raw JSONL files alongside the report. CSV/JSON summaries and an SVG chart are generated from those measurements. Application, benchmark client, and report generator fingerprints appear in `source-sha256.json`; dependency versions and lockfile hashes are recorded separately.

The Worker is configured near Sydney, and its pre-run outbound Cloudflare trace probe reported `SYD`. D1's primary probe reported Amsterdam. The post-run companion outbound probe reported Lisbon, consistent with its Western Europe hint. The platform omitted the documented incoming `cf-placement` header, so all per-request placement values remain `unknown`. Outbound probes corroborate configuration; they do not independently locate every timed request.

The local MacBook's physical location was not independently established; Cloudflare ingress was London. Client latency includes that network path. PostgreSQL connections are closed after each request, and connection setup contributes substantially to these results. SQL call timings and authentication/content segments are reported separately. Tail latency varied at concurrency ten; p99 values remain exploratory because endpoint groups have fewer than 1,000 successful samples.

Freshness values are client observations after mutation responses, not exact commit-to-replica delays or a one-second guarantee. Primary and cached-read observation requests have different transport paths.

## Runtime compatibility fixes

- Local SDK sources use consistent editable settings. The build materializes SDK files into the bundle so deployed imports never depend on a development-machine path.
- The disposable accounts use generated passwords and a benchmark-only, salted PBKDF2-SHA256 hasher at 100,000 iterations. The Worker adapter calls Web Crypto explicitly because the hosted Python hashing bridge did not support Django's default path. This is not a production password-storage recommendation.
- Worker and companion code propagated at different times. Setup waits for the required companion probe, and read-only readiness polling retries transient HTTP 503 responses. Mutating controls are not automatically retried.
- Shell networking is available through approved execution, allowing direct deployment and runtime validation. No Hyperdrive or browser clients were used.

## Reproduction

Follow the commands in the [README](../README.md). The Aiven source allows 20 connections; clients are capped at ten, with one additional synchronization connection. Do not overlap benchmark runs.

The freshness run deactivates reader099 and leaves tombstones, so reset through `bench.py setup` before repeating the complete experiment. The latency runner starts synchronization automatically; stop it again when idle.
