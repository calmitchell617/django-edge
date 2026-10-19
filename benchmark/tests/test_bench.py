"""Check measurement failure handling with an in-memory HTTP transport."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


@unittest.skipUnless(importlib.util.find_spec("httpx"), "requires installed httpx")
class BenchmarkClientTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import httpx

        cls.httpx = httpx
        spec = importlib.util.spec_from_file_location(
            "bench", Path(__file__).parents[1] / "scripts/bench.py"
        )
        cls.bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bench)

    async def test_missing_policy_metrics_is_a_failed_measurement(self):
        def handler(request):
            self.assertEqual(request.headers["X-Read-Policy"], "all_cache")
            return self.httpx.Response(200, json={"posts": []})

        async with self.httpx.AsyncClient(
            base_url="https://test.example", transport=self.httpx.MockTransport(handler)
        ) as client:
            rows, elapsed = await self.bench.phase([client], "all_cache", 0.005, 0, 1)
        self.assertGreater(len(rows), 0)
        self.assertGreater(elapsed, 0)
        self.assertTrue(all(row["error"] == "MissingOrIncorrectPolicyMetrics" for row in rows))

    async def test_control_failure_reports_exception_class_without_arbitrary_messages(self):
        for error, expected in (
            ("OperationalError", " (OperationalError)"),
            ("connection failed: password=secret", ""),
        ):
            with self.subTest(error=error):
                async with self.httpx.AsyncClient(
                    base_url="https://test.example",
                    transport=self.httpx.MockTransport(
                        lambda request, error=error: self.httpx.Response(503, json={"error": error})
                    ),
                ) as client:
                    with self.assertRaises(RuntimeError) as caught:
                        await self.bench.control(client, {"CONTROL_TOKEN": "test-token"}, "seed")
                self.assertEqual(str(caught.exception), f"Control seed failed: HTTP 503{expected}")

    async def test_successes_and_http_failures_remain_distinguishable(self):
        sequence = 0

        def handler(request):
            nonlocal sequence
            sequence += 1
            return self.httpx.Response(
                200 if sequence % 2 else 503,
                json={},
                headers={
                    "X-Edge-Metrics": json.dumps({"policy": "postgres", "server_ms": 1}),
                    "X-Worker-Placement": "remote-SYD",
                },
            )

        async with self.httpx.AsyncClient(
            base_url="https://test.example", transport=self.httpx.MockTransport(handler)
        ) as client:
            rows, _ = await self.bench.phase([client], "postgres", 0.005, 0, 1)
        self.assertTrue(any(row["error"] is None for row in rows))
        self.assertTrue(any(row["error"] == "HTTP503" for row in rows))
        self.assertTrue(all(row["placement"] == "remote-SYD" for row in rows))

    async def test_login_uses_csrf_and_preserves_the_session_cookie(self):
        def handler(request):
            if request.url.path == "/api/health/":
                return self.httpx.Response(
                    200,
                    json={"csrf_token": "test-csrf"},
                    headers={"Set-Cookie": "csrftoken=test-csrf; Path=/"},
                )
            self.assertEqual(request.headers["X-CSRFToken"], "test-csrf")
            self.assertEqual(request.headers["Referer"], "https://test.example")
            self.assertEqual(json.loads(request.content)["username"], "reader001")
            return self.httpx.Response(
                200, json={"id": 2}, headers={"Set-Cookie": "sessionid=test-session; Path=/"}
            )

        async with self.httpx.AsyncClient(
            base_url="https://test.example", transport=self.httpx.MockTransport(handler)
        ) as client:
            result = await self.bench.login(client, {"BENCH_PASSWORD": "test-password"}, 1)
            self.assertEqual(result["id"], 2)
            self.assertEqual(client.cookies["sessionid"], "test-session")

    async def test_readiness_retries_transient_status_failure(self):
        replies = iter(
            [
                self.httpx.Response(503, json={"error": "JsException"}),
                self.httpx.Response(
                    200,
                    json={
                        "enabled": True,
                        "failures": 0,
                        "last_cycle": {"tables": {"demo_post": {"pending": 0}}},
                    },
                ),
            ]
        )
        async with self.httpx.AsyncClient(
            base_url="https://test.example",
            transport=self.httpx.MockTransport(lambda request: next(replies)),
        ) as client:
            with patch.object(self.bench.asyncio, "sleep", new_callable=AsyncMock):
                result = await self.bench.ready(client, {"CONTROL_TOKEN": "test-token"})
        self.assertTrue(result["enabled"])
