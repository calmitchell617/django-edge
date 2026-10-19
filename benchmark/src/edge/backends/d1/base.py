"""Project-local Sessions API adapter; no changes to django-cf are required."""

import time

from django.db import DatabaseError
from django_cf.db.base_engine import CFDatabaseFeatures, CFDatabaseWrapper, CFResult

from edge.context import record_query, state


class Features(CFDatabaseFeatures):
    has_select_for_update = False


class DatabaseWrapper(CFDatabaseWrapper):
    vendor = "cloudflare_d1"
    display_name = "D1"
    features_class = Features

    def get_connection_params(self):
        return {"binding": self.settings_dict["CLOUDFLARE_BINDING"]}

    def get_new_connection(self, conn_params):
        self.binding = conn_params["binding"]
        return super().get_new_connection(conn_params)

    def run_query(self, query, params=None):
        from pyodide.ffi import run_sync
        from workers import env

        current = state.get()
        maintenance = self.alias == "cache_maintenance" and current and current.maintenance
        if not maintenance and query.lstrip().split(None, 1)[0].upper() not in {
            "SELECT",
            "EXPLAIN",
        }:
            raise DatabaseError("D1 application reads are read-only")
        db = getattr(env, self.binding)
        if self.alias == "cache":
            if current is None:
                raise DatabaseError("D1 replica reads require request context")
            if current.d1_session is None:
                current.d1_session = db.withSession("first-unconstrained")
            db = current.d1_session
        sql = query.replace("%s", "?")
        params = list(params or [])
        statement = db.prepare(sql)
        if params:
            statement = statement.bind(*params)
        started = time.perf_counter()
        try:
            response = run_sync(statement.all())
            if not response.get("success", True):
                raise DatabaseError("D1 query failed")
            meta = response.get("meta", {})
            if current:
                current.d1_meta.append(
                    {k: meta.get(k) for k in ("served_by_region", "served_by_primary", "duration")}
                )
            return CFResult.from_object(
                query,
                params,
                response.get("results", []),
                meta.get("rows_read"),
                meta.get("rows_written"),
                meta.get("last_row_id"),
            )
        finally:
            record_query(self.alias, (time.perf_counter() - started) * 1000)
