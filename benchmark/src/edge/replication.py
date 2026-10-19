"""Database-independent replication algorithm, exercised with a real SQLite cache in tests."""

from dataclasses import dataclass


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple
    primary_key: str

    @property
    def upsert_sql(self):
        names = ", ".join(map(quote, self.columns))
        values = ", ".join("?" for _ in self.columns)
        updates = ", ".join(
            f"{quote(c)}=excluded.{quote(c)}" for c in self.columns if c != self.primary_key
        )
        return (
            f"INSERT INTO {quote(self.name)} ({names}) VALUES ({values}) "
            f"ON CONFLICT ({quote(self.primary_key)}) DO UPDATE SET {updates} "
            f"WHERE excluded.sync_version >= {quote(self.name)}.sync_version"
        )


def copy_table(table, source, cache, *, batch_size=100, max_batches=10):
    copied = acknowledged = batches = 0
    for _ in range(max_batches):
        rows = source.pending(table, batch_size)
        if not rows:
            break
        # Ack only follows successful atomic D1 batch completion. A lost response
        # means replay; it never means guessing that copying succeeded.
        cache.batch(table, rows)
        copied += len(rows)
        acknowledged += source.acknowledge(table, rows)
        batches += 1
    return {"copied": copied, "acknowledged": acknowledged, "batches": batches}


def next_alarm(started_ms, now_ms, *, interval_ms=1000, failures=0):
    if failures:
        return now_ms + min(30_000, 1000 * 2 ** min(failures - 1, 5))
    return max(now_ms, started_ms + interval_ms)
