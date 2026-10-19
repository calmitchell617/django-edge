import time
from contextlib import ExitStack

from django.apps import apps
from django.conf import settings
from django.db import connections

from edge.backends.postgres.base import measure_sql
from edge.context import request_state
from edge.replication import Table, copy_table, quote


def mirrored_models():
    return [apps.get_model(label) for label in settings.MIRRORED_MODELS]


def table_for(model):
    return Table(
        model._meta.db_table,
        tuple(f.column for f in model._meta.concrete_fields),
        model._meta.pk.column,
    )


class PostgresSource:
    def pending(self, table, limit):
        columns = ", ".join(map(quote, table.columns))
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"SELECT {columns} FROM {quote(table.name)} WHERE needs_sync "
                f"ORDER BY {quote(table.primary_key)} LIMIT %s",
                [limit],
            )
            return [dict(zip(table.columns, row, strict=True)) for row in cursor.fetchall()]

    def acknowledge(self, table, rows):
        # One source round trip per batch; no long transaction spans D1 I/O.
        clauses = " OR ".join(f"({quote(table.primary_key)}=%s AND sync_version=%s)" for _ in rows)
        params = [value for row in rows for value in (row[table.primary_key], row["sync_version"])]
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"UPDATE {quote(table.name)} SET needs_sync=FALSE WHERE {clauses}", params
            )
            return cursor.rowcount


class D1Cache:
    def __init__(self, binding):
        self.binding = binding

    def batch(self, table, rows):
        from pyodide.ffi import run_sync

        model = next(m for m in mirrored_models() if m._meta.db_table == table.name)
        fields = {f.column: f for f in model._meta.concrete_fields}
        connection = connections["cache_maintenance"]
        statements = []
        for row in rows:
            values = []
            for name in table.columns:
                # D1 cannot receive datetime, Decimal, or native Python booleans.
                value = fields[name].get_db_prep_value(row[name], connection, prepared=False)
                if name == "needs_sync":
                    value = False
                values.append(int(value) if isinstance(value, bool) else value)
            statements.append(self.binding.prepare(table.upsert_sql).bind(*values))
        results = run_sync(self.binding.batch(statements))
        if len(results) != len(rows) or any(not r.get("success", True) for r in results):
            raise RuntimeError("D1 batch did not complete successfully")


def sync_once(binding, *, batch_size=100, max_batches=10):
    started = time.perf_counter()
    result = {}
    with request_state(maintenance=True) as current, ExitStack() as stack:
        stack.enter_context(connections["default"].execute_wrapper(measure_sql))
        try:
            source, cache = PostgresSource(), D1Cache(binding)
            for model in mirrored_models():
                table = table_for(model)
                stats = copy_table(
                    table, source, cache, batch_size=batch_size, max_batches=max_batches
                )
                with connections["default"].cursor() as cursor:
                    cursor.execute(f"SELECT count(*) FROM {quote(table.name)} WHERE needs_sync")
                    stats["pending"] = cursor.fetchone()[0]
                result[table.name] = stats
            return {
                "tables": result,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "queries": current.queries,
                "pg_connect_ms": current.connections_ms,
            }
        finally:
            connections.close_all()
