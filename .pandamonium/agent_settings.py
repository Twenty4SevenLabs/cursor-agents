"""Plugin-owned agent options. setting_sources is always empty."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def plugin_home() -> Path:
    return Path(os.environ.get("HOME") or "/tmp").expanduser().resolve()


def bridge_home() -> Path:
    return plugin_home()


def cursor_project_slug(cwd: str) -> str:
    name = Path(str(cwd or "default")).name or "default"
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)[:80]


def sdk_agent_store_dir(cwd: str) -> Path:
    slug = cursor_project_slug(cwd) or "default"
    return plugin_home() / "projects" / slug / "sdk-agent-store"


def ensure_sdk_agent_store(cwd: str) -> Path:
    store_dir = sdk_agent_store_dir(cwd)
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def capabilities_summary() -> dict[str, Any]:
    return {
        "bridge_home": str(plugin_home()),
        "cursor_config_dir": "",
        "setting_sources": [],
        "skills_enabled": False,
        "skill_count": 0,
        "mcp_enabled": False,
        "mcp_servers": [],
        "mcp_config_path": "",
        "mcp_config_present": False,
    }


def effective_setting_sources() -> list[str]:
    return []


def build_local_options(cwd: str) -> dict[str, Any]:
    return {"cwd": cwd, "setting_sources": []}


def build_agent_options(*, api_key: str, cwd: str, model: str) -> dict[str, Any]:
    return {
        "api_key": api_key,
        "model": model,
        "local": build_local_options(cwd),
    }


def build_send_options() -> dict[str, Any]:
    return {}
