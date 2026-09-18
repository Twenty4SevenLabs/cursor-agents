#!/usr/bin/env python3
"""MAD-960 entrypoint: bind PANDAMONIUM_PORT, plugin HOME, config.json key."""

from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_config() -> dict:
    path = Path("/run/pandamonium/config.json")
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    config = load_config()
    port = str(os.environ.get("PANDAMONIUM_PORT") or config.get("PANDAMONIUM_PORT") or "").strip()
    if not port:
        raise SystemExit("PANDAMONIUM_PORT is required")
    os.environ["PANDAMONIUM_PORT"] = port
    home = Path(os.environ.get("HOME") or "/tmp").expanduser().resolve()
    if str(home) in {"/home/labsadmin", "/root"}:
        raise SystemExit("plugin HOME must be the MAD-960 runtime, not the host account")
    (home / "workspaces" / "default").mkdir(parents=True, exist_ok=True)
    (home / "state").mkdir(parents=True, exist_ok=True)
    (home / "projects").mkdir(parents=True, exist_ok=True)
    api_key = str(config.get("CURSOR_API_KEY") or os.environ.get("CURSOR_API_KEY") or "").strip()
    if api_key:
        os.environ["CURSOR_API_KEY"] = api_key
    transcripts = str(config.get("IDE_TRANSCRIPTS_ROOT") or "").strip()
    if transcripts:
        os.environ["IDE_TRANSCRIPTS_ROOT"] = transcripts
    workspaces = config.get("WORKSPACE_ROOTS")
    if isinstance(workspaces, str) and workspaces.strip():
        os.environ["ODYSSEUS_CURSOR_WORKSPACES_JSON"] = workspaces
    else:
        os.environ["ODYSSEUS_CURSOR_WORKSPACES_JSON"] = json.dumps(
            {"default": str(home / "workspaces" / "default")}
        )
    os.environ["ODYSSEUS_CURSOR_BRIDGE_STATE_DIR"] = str(home / "state")
    os.environ["ODYSSEUS_CURSOR_BRIDGE_HOST"] = "127.0.0.1"
    os.chdir(str(HERE))
    import sidecar

    sidecar.main()


if __name__ == "__main__":
    main()
