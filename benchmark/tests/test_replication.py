import asyncio
import copy
import sqlite3
import unittest

from edge.context import request_state, state
from edge.replication import Table, copy_table, next_alarm

TABLE = Table("posts", ("id", "title", "sync_version", "needs_sync", "is_deleted"), "id")


def row(pk=1, version=1, *, deleted=False):
    return {
        "id": pk,
        "title": f"v{version}",
        "sync_version": version,
        "needs_sync": True,
        "is_deleted": deleted,
    }


class Source:
    def __init__(self, *rows):
        self.rows = {r["id"]: copy.copy(r) for r in rows}
        self.before_ack = None
        self.fail_ack = False

    def pending(self, table, limit):
        return [copy.copy(r) for _, r in sorted(self.rows.items()) if r["needs_sync"]][:limit]

    def acknowledge(self, table, rows):
        if self.before_ack:
            self.before_ack()
            self.before_ack = None
        if self.fail_ack:
            raise ConnectionError("lost ack connection")
        count = 0
        for copied in rows:
            current = self.rows[copied["id"]]
            if current["sync_version"] == copied["sync_version"]:
                current["needs_sync"] = False
                count += 1
        return count


class SQLiteCache:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
            "sync_version INTEGER NOT NULL, needs_sync INTEGER, is_deleted INTEGER)"
        )

    def batch(self, table, rows):
        with self.db:
            for r in rows:
                self.db.execute(table.upsert_sql, [r[c] for c in table.columns])

    def rows(self):
        return self.db.execute(
            "SELECT id,title,sync_version,is_deleted FROM posts ORDER BY id"
        ).fetchall()


class ReplicationTests(unittest.TestCase):
    def setUp(self):
        self.cache = SQLiteCache()
        self.addCleanup(self.cache.db.close)

    def test_copy_and_ack_do_not_create_a_feedback_loop(self):
        source = Source(row())
        result = copy_table(TABLE, source, self.cache)
        self.assertEqual(result, {"copied": 1, "acknowledged": 1, "batches": 1})
        self.assertEqual(copy_table(TABLE, source, self.cache)["copied"], 0)
        self.assertEqual(source.rows[1]["sync_version"], 1)

    def test_concurrent_source_change_remains_pending(self):
        source = Source(row())
        source.before_ack = lambda: source.rows.update({1: row(version=2)})
        result = copy_table(TABLE, source, self.cache, max_batches=1)
        self.assertEqual(result["acknowledged"], 0)
        self.assertTrue(source.rows[1]["needs_sync"])
        self.assertEqual(self.cache.rows()[0][2], 1)
        copy_table(TABLE, source, self.cache)
        self.assertEqual(self.cache.rows()[0][2], 2)

    def test_ack_failure_replays_without_duplicates(self):
        source = Source(row())
        source.fail_ack = True
        with self.assertRaises(ConnectionError):
            copy_table(TABLE, source, self.cache)
        self.assertTrue(source.rows[1]["needs_sync"])
        source.fail_ack = False
        copy_table(TABLE, source, self.cache)
        self.assertEqual(len(self.cache.rows()), 1)
        self.assertFalse(source.rows[1]["needs_sync"])

    def test_failing_cache_batch_rolls_back_and_never_acknowledges(self):
        broken = row(2)
        broken["title"] = None
        source = Source(row(), broken)
        with self.assertRaises(sqlite3.IntegrityError):
            copy_table(TABLE, source, self.cache)
        self.assertEqual(self.cache.rows(), [])
        self.assertTrue(all(r["needs_sync"] for r in source.rows.values()))

    def test_older_batch_cannot_overwrite_newer_version(self):
        self.cache.batch(TABLE, [row(version=3)])
        self.cache.batch(TABLE, [row(version=2)])
        self.assertEqual(self.cache.rows(), [(1, "v3", 3, 0)])

    def test_soft_delete_replaces_row_with_tombstone(self):
        source = Source(row())
        copy_table(TABLE, source, self.cache)
        source.rows[1] = row(version=2, deleted=True)
        copy_table(TABLE, source, self.cache)
        self.assertEqual(self.cache.rows(), [(1, "v2", 2, 1)])

    def test_cycle_bound_retains_backlog(self):
        source = Source(*(row(i) for i in range(250)))
        result = copy_table(TABLE, source, self.cache, batch_size=100, max_batches=2)
        self.assertEqual(result["copied"], 200)
        self.assertEqual(sum(r["needs_sync"] for r in source.rows.values()), 50)

    def test_string_primary_keys_and_quoted_columns(self):
        table = Table("sessions", ("session_key", "sync_version", "select"), "session_key")
        self.cache.db.execute(
            "CREATE TABLE sessions (session_key TEXT PRIMARY KEY, "
            'sync_version INTEGER, "select" TEXT)'
        )
        self.cache.db.execute(table.upsert_sql, ["abc", 1, "data"])
        self.assertEqual(
            self.cache.db.execute("SELECT session_key FROM sessions").fetchone(), ("abc",)
        )


class SchedulingTests(unittest.TestCase):
    def test_fast_cycle_waits_remaining_interval(self):
        self.assertEqual(next_alarm(1000, 1200), 2000)

    def test_slow_cycle_restarts_asap(self):
        self.assertEqual(next_alarm(1000, 2500), 2500)

    def test_retry_backoff_is_bounded(self):
        self.assertEqual(
            [next_alarm(0, 0, failures=n) for n in range(1, 8)],
            [1000, 2000, 4000, 8000, 16000, 30000, 30000],
        )


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_and_session_are_isolated_between_requests(self):
        async def worker(policy):
            with request_state(policy) as current:
                current.d1_session = object()
                await asyncio.sleep(0)
                self.assertIs(state.get(), current)
                return state.get().policy, current.d1_session

        first, second = await asyncio.gather(worker("postgres"), worker("all_cache"))
        self.assertEqual((first[0], second[0]), ("postgres", "all_cache"))
        self.assertIsNot(first[1], second[1])
        self.assertIsNone(state.get())

    async def test_context_resets_after_failure(self):
        with self.assertRaises(RuntimeError), request_state("auth_cache"):
            raise RuntimeError("failed request")
        self.assertIsNone(state.get())
