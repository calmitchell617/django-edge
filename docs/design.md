# Design and consistency

## Source of truth and read policy

PostgreSQL owns all writes. There is no cross-database transaction or synchronous dual-write requirement. Source transactions commit normally; synchronization happens later.

`X-Read-Policy` selects `postgres`, `auth_cache`, or `all_cache` for each HTTP request. A ContextVar holds the policy, D1 session, and measurements; they are discarded when the request finishes. Unsafe HTTP methods use the PostgreSQL policy. Cached business queries require `.eventually_consistent()` as well as the `all_cache` policy. Ordinary business queries stay on PostgreSQL.

The three mirrored models are a minimal user, a custom database session, and a post. Authentication forces the middleware's lazy `request.user` lookup on each measured request. No groups or permissions are queried. Unchanged sessions are not saved.

Application D1 access is read-only. The maintenance alias is used for schema setup and synchronization. Database errors remain errors during measurements; cache misses do not fall back to PostgreSQL.

## Model-managed tracking

`SyncedModel` provides `sync_version`, `needs_sync`, and `is_deleted`, a partial pending-row index, soft-delete methods, and a manager excluding tombstones. Concrete models declare `sync_triggers()` in `Meta.triggers`. `django-pgtrigger` manages installation through Django migrations.

```python
class Article(SyncedModel):
    title = models.CharField(max_length=200)

    class Meta(SyncedModel.Meta):
        abstract = False
        triggers = sync_triggers()
```

Add the model to the fixed `MIRRORED_MODELS` list and create ordinary migrations. Adding or changing mirrored schemas requires a coordinated fresh setup in this experiment; there is no live schema-change protocol.

The PostgreSQL BEFORE trigger sets version 1 and pending on insert. On update it compares domain columns, excluding the two sync metadata columns. A domain change derives the next version from the current database row and marks it pending. A metadata-only acknowledgement preserves the version. Physical DELETE is rejected; application deletion writes a tombstone instead.

The trigger applies to ordinary saves, QuerySet updates, bulk operations, and SQL. Python-side save handling excludes stale sync metadata when updating a model loaded from the cache. Normal QuerySet writes and locking queries are routed back to PostgreSQL even when the originating QuerySet opted into cached reads. This does not prevent ordinary lost business-field updates from stale whole-object saves; use partial updates or source-side locking when those semantics matter.

## One synchronization cycle

1. Read at most 100 pending rows from a source table, ordered by primary key. Do not hold a source transaction open across D1 network I/O.
2. Serialize fields using the D1 backend's field preparation rules. Preserve primary keys, versions, and tombstones; mark the cached copy clean.
3. Execute an atomic D1 batch. Upserts replace an existing row only if the incoming version is at least its current version.
4. Clear pending on source rows only when their primary keys and copied versions still match.
5. Repeat for at most 10 batches per table, then move to the next selected table. Record copied/acknowledged counts, remaining backlog, and duration.

An intervening source update makes acknowledgement match zero rows, leaving work for a subsequent batch. A failed D1 batch causes no acknowledgement. A completed D1 write followed by a failed source acknowledgement replays safely. A late source transaction becomes pending when it commits; there is no global high-water mark that can skip it.

Acknowledgement is one conditional SQL statement per batch. It does not modify domain columns, so it cannot increment the version or create another pending change.

## Scheduling and controls

One named Python Durable Object, requested in Western Europe, owns a persistent enabled flag and statistics. An initial start schedules the first native alarm. Each alarm runs one cycle and schedules its successor at `max(now, cycle_start + 1000ms)`. Failures back off at 1, 2, 4, 8, 16, then 30 seconds. Normal cycles return to the one-second target.

An asyncio lock serializes alarms and controls across awaited I/O. PostgreSQL connections are closed at the end of every cycle. No permanent background loop or external per-second caller is required. Native alarms provide durable wakeups and can retry deliveries; writes therefore remain idempotent.

`POST /_control/<action>/` requires the configured bearer token. Actions are allowlisted: start, stop, status, migrate, reset, seed, manual sync, runtime probes, restricted primary-cache inspection, and account deactivation for the freshness experiment. There is no arbitrary SQL or command execution endpoint.

Reset and migration require the companion to be stopped. Stop waits for the in-progress cycle to release the lock. Reset clears D1 and PostgreSQL together before IDs and versions are reused. A partial reset must be rerun while stopped; it is not a distributed transaction.

## Consistency boundaries

- One-second polling is a target cadence, not a freshness guarantee. Batch limits, downtime, retries, replica lag, and observation round trips can make visibility slower.
- Rows are copied independently. A cycle does not reproduce a PostgreSQL transaction atomically across tables or batches. This prototype deliberately avoids business foreign-key relationships between mirrored tables.
- D1 sessions provide sequential consistency among that request's D1 queries, not a PostgreSQL transaction snapshot or read-your-write guarantee across stores. A fresh unconstrained session is created for each request.
- New sessions, revocations, inactive accounts, and content changes can be stale on cached reads. PostgreSQL remains available for paths requiring authoritative checks.
- A replica session miss returns an anonymous result while preserving the client's cookie for retry. It does not prove the authoritative session is invalid and does not cause a source read or write.
- The custom D1 adapter is intentionally scoped to this app's ORM queries; it is not a claim of universal PostgreSQL/SQLite SQL compatibility. D1 batch atomicity is used explicitly; Django `atomic()` on D1 is not supported.
- PostgreSQL remains a polling dependency even in the fully cached read mode. This is not an offline application or failover system.

## Measurement boundaries

Client latency includes the HTTP route to the Worker. Server, authentication, business, SQL, and PostgreSQL connection timings are recorded separately. Reports retain failures and sample counts. Native PostgreSQL connections are deliberately closed between requests so cross-request connection pooling does not obscure the comparison.

The test source allows 20 connections. Client concurrency is capped at 10, leaving room for the companion's single connection and management activity. Do not overlap benchmark runs or run unrelated source workloads during measurement. SQLSTATE 53300 is recorded separately so connection-limit failures cannot be mistaken for latency improvements.

Worker placement comes from the platform's `cf-placement` request header, echoed as `X-Worker-Placement`. `cf-ray` is recorded as ingress metadata, not used as proof of execution location. D1 records `served_by_region` and `served_by_primary`. A WEUR primary is requested without an EU jurisdiction restriction, which would prevent an Oceania replica.

The hosted deployment currently omits `cf-placement`, so per-request placement remains `unknown`. Runtime probes also fetch Cloudflare's public trace endpoint and retain only its serving colo, outside timed trials. A Sydney egress result corroborates the Australian placement hint; it does not prove placement independently for every measured request. Reports preserve that distinction.

Freshness observations start after the mutation response reaches the client. Primary and Australian-read checks run concurrently. Their elapsed times include observation transport, and polling occurs every 100ms between responses; they are not exact source commit-to-replica timestamps. The logout scenario deliberately reuses the revoked cookie so client-side cookie removal cannot masquerade as replicated revocation.

Latency comparisons must state the recorded geography evidence and its limits. Runtime checks and exploratory measurements do not establish production suitability.

The disposable accounts use generated high-entropy passwords and Django's salted PBKDF2-SHA256 format with 100,000 iterations, configured in `edge.hashers.BenchmarkPasswordHasher` for the hosted Worker's PBKDF2 limit. This is benchmark configuration, not a production password-storage recommendation. Login is outside measured read trials; the runtime probes check hashing and verification before setup proceeds.
