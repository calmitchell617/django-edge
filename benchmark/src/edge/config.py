"""Configuration without copying deployed secrets into process-global state."""

import os
from pathlib import Path


def setting(name, default=None):
    if name in os.environ:
        return os.environ[name]
    try:
        from workers import env

        return getattr(env, name)
    except ImportError, AttributeError:
        return default


def load_local_env():
    path = Path(__file__).resolve().parents[3] / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def postgres_database():
    from psycopg.conninfo import conninfo_to_dict

    dsn = setting("AIVEN_POSTGRESQL_DSN")
    if not dsn:
        raise RuntimeError("Set AIVEN_POSTGRESQL_DSN; see .env.example")
    options = conninfo_to_dict(dsn)
    result = {
        "ENGINE": "edge.backends.postgres",
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
    for source, target in (
        ("dbname", "NAME"),
        ("host", "HOST"),
        ("port", "PORT"),
        ("user", "USER"),
        ("password", "PASSWORD"),
    ):
        result[target] = options.pop(source, "")
    options.setdefault("sslmode", "require")
    if options["sslmode"] in {"disable", "allow", "prefer"}:
        raise RuntimeError("The reference architecture requires PostgreSQL TLS")
    options.setdefault("connect_timeout", "15")
    result["OPTIONS"] = options
    return result
