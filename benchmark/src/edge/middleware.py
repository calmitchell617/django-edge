import json
import time
from contextlib import ExitStack

from django.db import connections
from django.http import JsonResponse

from edge.backends.postgres.base import measure_sql
from edge.context import POLICIES, request_state


class MeasurementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        policy = request.headers.get("X-Read-Policy", "postgres")
        if policy not in POLICIES:
            return JsonResponse({"error": "invalid read policy"}, status=400)
        if request.method not in {"GET", "HEAD"}:
            policy = "postgres"
        started = time.perf_counter()
        with request_state(policy) as current, ExitStack() as stack:
            stack.enter_context(connections["default"].execute_wrapper(measure_sql))
            try:
                response = self.get_response(request)
                metrics = {
                    "policy": policy,
                    "server_ms": (time.perf_counter() - started) * 1000,
                    "queries": current.queries,
                    "pg_connect_ms": current.connections_ms,
                    "d1": current.d1_meta,
                    "database_errors": current.database_errors,
                    "segments": current.segments,
                }
                response["X-Edge-Metrics"] = json.dumps(metrics, separators=(",", ":"))
                response["X-Worker-Placement"] = request.headers.get("cf-placement", "unknown")
                response["Cache-Control"] = "no-store"
                return response
            finally:
                connections.close_all()
