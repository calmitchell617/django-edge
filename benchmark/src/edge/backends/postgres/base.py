import time

from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLWrapper

from edge.context import record_query, state


class DatabaseWrapper(PostgreSQLWrapper):
    def get_new_connection(self, conn_params):
        started = time.perf_counter()
        try:
            connection = super().get_new_connection(conn_params)
        except Exception as error:
            record_error(error)
            raise
        current = state.get()
        if current:
            current.connections_ms.append((time.perf_counter() - started) * 1000)
        return connection

    def create_cursor(self, name=None):
        cursor = super().create_cursor(name)
        # Use Django execute wrappers for SQL metrics, including failed statements.
        return cursor


def measure_sql(execute, sql, params, many, context):
    started = time.perf_counter()
    try:
        return execute(sql, params, many, context)
    except Exception as error:
        record_error(error)
        raise
    finally:
        record_query(context["connection"].alias, (time.perf_counter() - started) * 1000)


def record_error(error):
    current = state.get()
    if current:
        code = getattr(error, "sqlstate", None) or getattr(error.__cause__, "sqlstate", None)
        current.database_errors.append({"type": type(error).__name__, "sqlstate": code})
