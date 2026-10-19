"""Executed inside the HTTP Worker and companion, before running benchmarks."""

import time
from importlib.metadata import version as distribution_version

from django.db import connections, transaction


def runtime_probe(binding):
    from django.contrib.auth.hashers import check_password, make_password
    from pyodide.ffi import run_sync
    from workers import fetch

    started = time.perf_counter()
    try:
        # Fixed public probe value, unrelated to account credentials.
        encoded = make_password("runtime-probe-only")
        password_hashing = check_password("runtime-probe-only", encoded)
        # Independent placement evidence, outside timed trials. Store only the
        # serving colo, never trace IP addresses or other client information.
        trace_response = run_sync(fetch("https://www.cloudflare.com/cdn-cgi/trace"))
        trace = run_sync(trace_response.text())
        egress_colo = next(
            (line.removeprefix("colo=") for line in trace.splitlines() if line.startswith("colo=")),
            None,
        )
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version')")
            server_version = cursor.fetchone()[0]
            cursor.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
            tls = cursor.fetchone()[0]
            cursor.execute("CREATE TEMP TABLE edge_probe (id integer)")
        try:
            with transaction.atomic():
                with connections["default"].cursor() as cursor:
                    cursor.execute("INSERT INTO edge_probe VALUES (1)")
                raise ValueError("intentional rollback")
        except ValueError:
            pass
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT count(*) FROM edge_probe")
            rollback = cursor.fetchone()[0] == 0
            cursor.execute("DROP TABLE edge_probe")
        d1 = run_sync(binding.withSession("first-primary").prepare("SELECT 1 AS ok").all())
        return {
            "ok": bool(tls and rollback and password_hashing and d1["results"][0]["ok"] == 1),
            "password_hashing": password_hashing,
            "egress_colo": egress_colo,
            "egress_evidence": "Cloudflare trace from this execution context; outside timed trials",
            "tls": tls,
            "rollback": rollback,
            "postgres_version": server_version,
            "d1_meta": d1.get("meta", {}),
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "runtime_versions": {
                name: distribution_version(name)
                for name in ("django", "django-pgtrigger", "psycopg", "workers-runtime-sdk")
            },
        }
    finally:
        connections.close_all()
