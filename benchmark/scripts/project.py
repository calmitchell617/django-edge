"""Local setup and lifecycle commands. Never print secret values."""

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edge.config import load_local_env  # noqa: E402


def configure():
    load_local_env()
    if not os.environ.get("AIVEN_POSTGRESQL_DSN"):
        raise SystemExit("Set AIVEN_POSTGRESQL_DSN in the repository's .env")
    target = ROOT / "secrets.local.json"
    values = json.loads(target.read_text()) if target.exists() else {}
    values.update(AIVEN_POSTGRESQL_DSN=os.environ["AIVEN_POSTGRESQL_DSN"])
    for name in ("DJANGO_SECRET_KEY", "CONTROL_TOKEN", "BENCH_PASSWORD"):
        values.setdefault(name, secrets.token_urlsafe(36))
    # BENCH_PASSWORD is client-side test configuration, not a Worker binding.
    target.write_text(json.dumps(values, indent=2) + "\n")
    target.chmod(0o600)
    bindings = {k: v for k, v in values.items() if k != "BENCH_PASSWORD"}
    (ROOT / ".dev.vars").write_text(
        "".join(f"{k}={json.dumps(v)}\n" for k, v in bindings.items()) + "EDGE_LOCAL=1\n"
    )
    (ROOT / ".dev.vars").chmod(0o600)
    deployed = ROOT / "bindings.local.json"
    deployed.write_text(json.dumps(bindings) + "\n")
    deployed.chmod(0o600)
    print("Wrote ignored local secret files; values were not printed.")


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["configure", "install", "deploy", "setup", "cleanup"])
    parser.add_argument("--url")
    args = parser.parse_args()
    if args.action == "configure":
        configure()
    elif args.action == "install":
        run("uv", "sync")
        run("npm", "install")
        run("uv", "run", "pywrangler", "sync")
    elif args.action == "deploy":
        if not (ROOT / "bindings.local.json").exists():
            raise SystemExit("Run configure first")
        # The module defers Django initialization until the first request, so the
        # first deployment can exist before its secret bindings are uploaded.
        run("uv", "run", "pywrangler", "deploy")
        run("uv", "run", "pywrangler", "secret", "bulk", "bindings.local.json")
    elif args.action == "setup":
        if not args.url:
            parser.error("setup needs --url")
        run("uv", "run", "python", "scripts/bench.py", "setup", "--url", args.url)
    elif args.action == "cleanup":
        if not args.url:
            parser.error("cleanup needs --url to stop the companion first")
        run("uv", "run", "python", "scripts/bench.py", "stop", "--url", args.url)
        run("uv", "run", "pywrangler", "delete", "--name", "django-edge-reference")
        run("uv", "run", "pywrangler", "d1", "delete", "django-edge-cache")


if __name__ == "__main__":
    main()
