from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

POLICIES = ("postgres", "auth_cache", "all_cache")


@dataclass
class RequestState:
    policy: str = "postgres"
    maintenance: bool = False
    queries: dict = field(default_factory=dict)
    connections_ms: list = field(default_factory=list)
    d1_meta: list = field(default_factory=list)
    database_errors: list = field(default_factory=list)
    segments: dict = field(default_factory=dict)
    d1_session: object = None


state = ContextVar("edge_request_state", default=None)


@contextmanager
def request_state(policy="postgres", *, maintenance=False):
    if policy not in POLICIES:
        raise ValueError("Unknown read policy")
    value = RequestState(policy=policy, maintenance=maintenance)
    token = state.set(value)
    try:
        yield value
    finally:
        state.reset(token)


def record_query(alias, elapsed_ms):
    current = state.get()
    if current:
        item = current.queries.setdefault(alias, {"count": 0, "ms": 0.0})
        item["count"] += 1
        item["ms"] += elapsed_ms
