"""Bundle the local editable SDK as ordinary files for the Worker filesystem."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_SOURCE = ROOT.parent / "workers-py/packages/runtime-sdk/src"


def materialize(source=SDK_SOURCE, target=ROOT / "python_modules"):
    if not target.is_dir():
        raise RuntimeError("Run pywrangler sync before bundling")
    if not (source / "workers/__init__.py").exists():
        raise RuntimeError("Local Worker runtime SDK is missing")
    # uv's editable install produces a .pth pointing at a macOS/Linux path. That
    # path does not exist in a deployed isolate. Include the dependency itself,
    # including its JS bridge modules and runtime patch-loader .pth, instead.
    for child in source.iterdir():
        if child.name == "__pycache__":
            continue
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(
                child,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(child, destination)
    for editable in target.glob("_editable*workers_runtime_sdk*.pth"):
        editable.unlink()


if __name__ == "__main__":
    materialize()
    print("Bundled the checked-in Worker runtime SDK.")
