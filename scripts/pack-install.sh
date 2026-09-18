#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 - <<'PY'
from pathlib import Path
import json
import zipfile

root = Path(".").resolve()
version = json.loads((root / "jarvis-extension.json").read_text())["version"]
dist = root / "dist"
dist.mkdir(exist_ok=True)
archive_path = dist / f"cursor-agents-{version}.zip"
if archive_path.exists():
    archive_path.unlink()

include_files = [
    "jarvis-extension.json",
    "LICENSE",
    "README.md",
    "FIRST_RUN.md",
    "COMMUNITY.md",
]
skip_parts = {"__pycache__", ".pytest_cache", "dist"}
skip_suffixes = {".pyc"}

added: list[str] = []
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for name in include_files:
        path = root / name
        archive.write(path, name)
        added.append(name)
    for folder in ("scripts", ".pandamonium"):
        for path in sorted((root / folder).rglob("*")):
            if not path.is_file():
                continue
            if any(part in skip_parts for part in path.parts):
                continue
            if path.suffix in skip_suffixes:
                continue
            rel = path.relative_to(root).as_posix()
            archive.write(path, rel)
            added.append(rel)

names = zipfile.ZipFile(archive_path).namelist()
assert "jarvis-extension.json" in names
assert ".pandamonium/server.py" in names
assert ".pandamonium/integration.json" in names
assert "FIRST_RUN.md" in names
print(archive_path)
print(len(names), "files")
PY
