"""HTTP-only setup, latency trials and propagation checks. No browser dependencies."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ("postgres", "auth_cache", "all_cache")


class ControlError(RuntimeError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def secrets_config():
    path = ROOT / "secrets.local.json"
    if not path.exists():
        raise SystemExit("Run scripts/project.py configure first")
    return json.loads(path.read_text())


async def control(client, config, action, body=None):
    response = await client.post(
        f"/_control/{action}/",
        json=body or {},
        headers={"Authorization": "Bearer " + config["CONTROL_TOKEN"]},
    )
    if response.status_code != 200:
        # The control API returns exception class names, never driver messages
        # (which can contain credentials). Ignore arbitrary provider HTML/text.
        detail = ""
        try:
            error = response.json().get("error")
            if isinstance(error, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,99}", error):
                detail = f" ({error})"
            locations = response.json().get("locations", [])
            if isinstance(locations, list):
                safe = [
                    location
                    for location in locations
                    if isinstance(location, str)
                    and re.fullmatch(r"[A-Za-z0-9_.<>-]+:\d+:[A-Za-z0-9_<>]+", location)
                ]
                if safe:
                    detail += "\nCode locations: " + " -> ".join(safe[-12:])
        except ValueError, AttributeError:
            pass
        raise ControlError(
            f"Control {action} failed: HTTP {response.status_code}{detail}", response.status_code
        )
    return response.json()


async def login(client, config, index):
    response = await client.get("/api/health/")
    response.raise_for_status()
    token = response.json()["csrf_token"]
    response = await client.post(
        "/api/login/",
        json={"username": f"reader{index:03d}", "password": config["BENCH_PASSWORD"]},
        headers={"X-CSRFToken": token, "Referer": str(client.base_url)},
    )
    response.raise_for_status()
    return response.json()


async def mutation(client, method, path, **kwargs):
    return await client.request(
        method,
        path,
        headers={"X-CSRFToken": client.cookies["csrftoken"], "Referer": str(client.base_url)},
        **kwargs,
    )


async def ready(client, config, *, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = await control(client, config, "status")
        except ControlError as error:
            if error.status != 503:
                raise
            # Status is read-only; retry transient rollout/storage failures.
            await asyncio.sleep(0.5)
            continue
        tables = status.get("last_cycle", {}).get("tables", {})
        if status.get("enabled") and not status.get("failures") and tables:
            if all(t["pending"] == 0 for t in tables.values()):
                return status
        await asyncio.sleep(0.25)
    raise TimeoutError("Synchronization did not drain within readiness deadline")


async def visible(client, path, predicate, *, timeout=90, headers=None):
    started = time.perf_counter()
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        response = await client.get(path, headers={"X-Read-Policy": "all_cache", **(headers or {})})
        attempts += 1
        if predicate(response):
            return {
                "visible_ms": (time.perf_counter() - started) * 1000,
                "attempts": attempts,
                "placement": response.headers.get(
                    "X-Worker-Placement", response.headers.get("cf-placement")
                ),
                "metrics": json.loads(response.headers.get("X-Edge-Metrics", "{}")),
            }
        if response.status_code not in {200, 401, 404}:
            raise RuntimeError(f"Propagation check failed: HTTP {response.status_code}")
        await asyncio.sleep(0.1)
    raise TimeoutError("Replica visibility deadline exceeded")


async def observe_primary(client, config, model, pk, predicate, *, timeout=90):
    started = time.perf_counter()
    attempts = 0
    while time.perf_counter() - started < timeout:
        result = await control(client, config, "cache_state", {"model": model, "pk": pk})
        attempts += 1
        if result["rows"] and predicate(result["rows"][0]):
            return {
                "visible_ms": (time.perf_counter() - started) * 1000,
                "attempts": attempts,
                "meta": result["meta"],
            }
        await asyncio.sleep(0.1)
    raise TimeoutError("Primary visibility deadline exceeded")


async def propagation(
    client, config, event, path, predicate, model, pk, primary_predicate, *, headers=None
):
    primary, replica = await asyncio.gather(
        observe_primary(client, config, model, pk, primary_predicate),
        visible(client, path, predicate, headers=headers),
    )
    return {
        "event": event,
        "primary": primary,
        "australian_read": replica,
        "clock": "elapsed at client after mutation response; includes observation round trips",
    }


async def setup(url, config):
    async with httpx.AsyncClient(base_url=url, timeout=120) as client:
        for action in ("probe_http", "probe", "batch_probe"):
            result = await control(client, config, action)
            if action in {"probe_http", "probe"}:
                # Worker and DO deployments propagate separately. An older DO
                # probe does not exercise the newly required hashing adapter.
                deadline = time.monotonic() + 180
                while "password_hashing" not in result and time.monotonic() < deadline:
                    print(f"Waiting for updated {action} code to reach this location...")
                    await asyncio.sleep(10)
                    result = await control(client, config, action)
                if not result.get("password_hashing"):
                    raise RuntimeError(f"Updated password-hashing runtime gate missing: {action}")
            if not result.get("ok"):
                raise RuntimeError(f"Runtime gate failed: {action}")
            print(f"Passed runtime gate: {action}")
        await control(client, config, "stop")
        await control(client, config, "migrate")
        await control(client, config, "reset")
        await control(client, config, "seed", {"password": config["BENCH_PASSWORD"]})
        await control(client, config, "start")
        await ready(client, config)
        await login(client, config, 0)
        await ready(client, config)
        await visible(
            client,
            "/api/posts/",
            lambda r: r.status_code == 200 and r.json().get("count") == 10_000,
        )
        print("Seeded 100 users and 10,000 posts; replica readiness passed.")


async def phase(clients, policy, seconds, repetition, concurrency):
    started = time.perf_counter()
    deadline = started + seconds

    async def worker(index, client):
        rows = []
        sequence = 0
        while time.perf_counter() < deadline:
            path = (
                "/api/posts/" if sequence % 2 == 0 else f"/api/posts/{1 + (sequence // 2) % 10000}/"
            )
            before = time.perf_counter()
            record = {
                "policy": policy,
                "concurrency": concurrency,
                "repetition": repetition,
                "worker": index,
                "endpoint": "list" if sequence % 2 == 0 else "detail",
                "status": None,
                "error": None,
            }
            try:
                response = await client.get(path, headers={"X-Read-Policy": policy})
                record.update(
                    status=response.status_code,
                    placement=response.headers.get(
                        "X-Worker-Placement", response.headers.get("cf-placement")
                    ),
                    cf_ray=response.headers.get("cf-ray"),
                    metrics=json.loads(response.headers.get("X-Edge-Metrics", "{}")),
                )
                if response.status_code != 200:
                    record["error"] = f"HTTP{response.status_code}"
                elif record["metrics"].get("policy") != policy:
                    record["error"] = "MissingOrIncorrectPolicyMetrics"
            except (httpx.HTTPError, ValueError) as error:
                record["error"] = type(error).__name__
            record["client_ms"] = (time.perf_counter() - before) * 1000
            rows.append(record)
            sequence += 1
        return rows

    batches = await asyncio.gather(*(worker(i, client) for i, client in enumerate(clients)))
    return [row for batch in batches for row in batch], time.perf_counter() - started


def environment(args):
    result = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "client_location": args.client_location,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "warmup_seconds": args.warmup,
        "measurement_seconds": args.duration,
        "repetitions": args.repetitions,
        "concurrency": args.concurrency,
        "postgres_connection_limit": 20,
        "maximum_client_concurrency": 10,
        "policies": POLICIES,
        "dependencies": {},
        "upstream_revision": "c62b46790a773de6edf59216c054bdb8244e1485",
    }
    for name in (
        "django",
        "django-cf",
        "django-pgtrigger",
        "psycopg",
        "workers-py",
        "workers-runtime-sdk",
        "httpx",
    ):
        result["dependencies"][name] = importlib.metadata.version(name)
    result["git_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    result["git_dirty"] = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    )
    result["wrangler"] = json.loads((ROOT / "wrangler.jsonc").read_text())
    result["lockfile_sha256"] = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("uv.lock", "pylock.toml", "package-lock.json")
    }
    result["worker_dependencies"] = [
        {"name": package["name"], "version": package.get("version", "local source")}
        for package in tomllib.loads((ROOT / "pylock.toml").read_text())["packages"]
    ]
    return result


async def benchmark(args, config):
    if not args.client_location:
        raise SystemExit("Provide --client-location, e.g. London, UK")
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    (out / "environment.json").write_text(json.dumps(environment(args), indent=2) + "\n")
    async with httpx.AsyncClient(base_url=args.url, timeout=120) as admin:
        validation = {}
        for action in ("probe_http", "probe", "batch_probe"):
            validation[action] = await control(admin, config, action)
            if not validation[action].get("ok"):
                raise RuntimeError(f"Runtime gate failed: {action}")
        (out / "runtime-validation.json").write_text(json.dumps(validation, indent=2) + "\n")
        await control(admin, config, "start")
        await ready(admin, config)
        with (out / "requests.jsonl").open("w") as raw, (out / "trials.jsonl").open("w") as trials:
            for concurrency in args.concurrency:
                clients = [
                    httpx.AsyncClient(base_url=args.url, timeout=30) for _ in range(concurrency)
                ]
                try:
                    for index, client in enumerate(clients):
                        await login(client, config, index)
                    await ready(admin, config)
                    for client in clients:
                        await visible(client, "/api/me/", lambda r: r.status_code == 200)
                    for repetition in range(args.repetitions):
                        order = POLICIES[repetition % 3 :] + POLICIES[: repetition % 3]
                        for policy in order:
                            before = await control(admin, config, "status")
                            await phase(clients, policy, args.warmup, repetition, concurrency)
                            rows, elapsed = await phase(
                                clients, policy, args.duration, repetition, concurrency
                            )
                            for row in rows:
                                raw.write(json.dumps(row) + "\n")
                            raw.flush()
                            after = await control(admin, config, "status")
                            trials.write(
                                json.dumps(
                                    {
                                        "policy": policy,
                                        "concurrency": concurrency,
                                        "repetition": repetition,
                                        "elapsed_s": elapsed,
                                        "requests": len(rows),
                                        "sync_before": before,
                                        "sync_after": after,
                                    }
                                )
                                + "\n"
                            )
                            trials.flush()
                            print(
                                f"{policy} c={concurrency} repeat={repetition + 1}: "
                                f"{len(rows)} requests; errors="
                                f"{sum(bool(r['error']) for r in rows)}"
                            )
                finally:
                    await asyncio.gather(*(client.aclose() for client in clients))


async def freshness(args, config):
    args.output.mkdir(parents=True, exist_ok=False)
    events = []
    async with httpx.AsyncClient(base_url=args.url, timeout=120) as client:
        await control(client, config, "start")
        user = await login(client, config, 99)
        session_key = client.cookies["sessionid"]
        events.append(
            await propagation(
                client,
                config,
                "login",
                "/api/me/",
                lambda r: r.status_code == 200,
                "demo.Session",
                session_key,
                lambda row: not row["is_deleted"],
            )
        )
        response = await mutation(
            client, "POST", "/api/posts/", json={"title": "Freshness test", "content": "v1"}
        )
        response.raise_for_status()
        pk = response.json()["id"]
        path = f"/api/posts/{pk}/"
        events.append(
            await propagation(
                client,
                config,
                "insert",
                path,
                lambda r: r.status_code == 200,
                "demo.Post",
                pk,
                lambda row: not row["is_deleted"],
            )
        )
        response = await mutation(client, "PATCH", path, json={"content": "v2"})
        response.raise_for_status()
        version = response.json()["sync_version"]
        events.append(
            await propagation(
                client,
                config,
                "update",
                path,
                lambda r: r.status_code == 200 and r.json()["sync_version"] >= version,
                "demo.Post",
                pk,
                lambda row: row["sync_version"] >= version,
            )
        )
        response = await mutation(client, "DELETE", path)
        response.raise_for_status()
        events.append(
            await propagation(
                client,
                config,
                "soft_delete",
                path,
                lambda r: r.status_code == 404,
                "demo.Post",
                pk,
                lambda row: bool(row["is_deleted"]),
            )
        )
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        response = await mutation(client, "POST", "/api/logout/")
        response.raise_for_status()
        # Keep sending the revoked cookie deliberately, rather than measuring
        # the immediate client-side removal of that cookie.
        events.append(
            await propagation(
                client,
                config,
                "logout",
                "/api/me/",
                lambda r: r.status_code == 401,
                "demo.Session",
                session_key,
                lambda row: bool(row["is_deleted"]),
                headers={"Cookie": cookie},
            )
        )
        await login(client, config, 99)
        await visible(client, "/api/me/", lambda r: r.status_code == 200)
        await control(client, config, "deactivate", {"username": "reader099"})
        events.append(
            await propagation(
                client,
                config,
                "deactivate",
                "/api/me/",
                lambda r: r.status_code == 401,
                "demo.User",
                user["id"],
                lambda row: not row["is_active"],
            )
        )
        (args.output / "freshness.json").write_text(json.dumps(events, indent=2) + "\n")
        print("Recorded six propagation scenarios. Reset before another benchmark run.")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "run", "freshness", "stop", "status"])
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    parser.add_argument("--client-location")
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10])
    args = parser.parse_args()
    if (
        args.duration <= 0
        or args.warmup < 0
        or args.repetitions < 1
        or any(c < 1 or c > 10 for c in args.concurrency)
    ):
        parser.error("Use positive timing/repetitions and concurrency 1–10; source limit is 20")
    config = secrets_config()
    if args.action == "setup":
        await setup(args.url, config)
    elif args.action == "run":
        await benchmark(args, config)
    elif args.action == "freshness":
        await freshness(args, config)
    else:
        async with httpx.AsyncClient(base_url=args.url, timeout=120) as client:
            print(json.dumps(await control(client, config, args.action), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
