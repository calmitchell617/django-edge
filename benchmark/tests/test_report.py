import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "report", Path(__file__).parents[1] / "scripts/report.py"
)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    def test_percentiles_and_errors_are_not_conflated(self):
        result = report.summarize(
            [
                {"status": 200, "error": None, "client_ms": 10},
                {"status": 200, "error": None, "client_ms": 20},
                {"status": 503, "error": "HTTP503", "client_ms": 5000},
            ],
            elapsed_s=2,
        )
        self.assertEqual(result["p50_ms"], 15)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["throughput_rps"], 1)

    def test_all_errors_do_not_become_fast_latencies(self):
        result = report.summarize([{"status": 503, "error": "HTTP503", "client_ms": 1}], 1)
        self.assertIsNone(result["p95_ms"])
        self.assertEqual(result["successes"], 0)

    def test_query_mean_weights_calls_and_excludes_failed_requests(self):
        rows = [
            {
                "status": 200,
                "error": None,
                "client_ms": 1,
                "metrics": {"queries": {"default": {"count": 2, "ms": 10}}},
            },
            {
                "status": 200,
                "error": None,
                "client_ms": 2,
                "metrics": {"queries": {"default": {"count": 1, "ms": 20}}},
            },
            {
                "status": 503,
                "error": "HTTP503",
                "client_ms": 5000,
                "metrics": {"queries": {"default": {"count": 1, "ms": 5000}}},
            },
        ]
        result = report.summarize(rows, 1)
        self.assertEqual(result["pg_query_mean_ms"], 10)
        self.assertEqual(result["pg_queries"], 3)
        self.assertIsNone(result["d1_query_mean_ms"])

    def test_real_artifacts_and_unknown_geography(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "requests.jsonl").write_text(
                json.dumps(
                    {
                        "policy": "all_cache",
                        "concurrency": 1,
                        "endpoint": "list",
                        "status": 200,
                        "error": None,
                        "client_ms": 12,
                        "metrics": {
                            "server_ms": 10,
                            "d1": [{"served_by_region": "WEUR", "served_by_primary": True}],
                        },
                    }
                )
                + "\n"
            )
            (root / "trials.jsonl").write_text(
                json.dumps({"policy": "all_cache", "concurrency": 1, "elapsed_s": 1}) + "\n"
            )
            (root / "environment.json").write_text(
                json.dumps(
                    {
                        "started_utc": "test",
                        "client_location": "test",
                        "git_commit": "test",
                        "git_dirty": True,
                    }
                )
            )
            report.make_report(root)
            self.assertIn("**False**", (root / "report.md").read_text())
            self.assertTrue((root / "summary.csv").exists())
            self.assertTrue((root / "latency.svg").read_text().startswith("<svg"))
