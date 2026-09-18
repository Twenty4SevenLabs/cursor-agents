"""Plugin HOME workspace keys. Cwd must stay inside HOME/workspaces."""

from __future__ import annotations

import os
import re
from pathlib import Path

_WORKSPACE_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def plugin_home() -> Path:
    return Path(os.environ.get("HOME") or "/tmp").expanduser().resolve()


def workspaces_root() -> Path:
    root = plugin_home() / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_safe_workspace_key(slug: str) -> bool:
    key = str(slug or "").strip()
    if not key or ".." in key or "/" in key or "\\" in key:
        return False
    return bool(_WORKSPACE_SEGMENT.fullmatch(key))


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_agent_cwd(
    workspace: str,
    explicit_cwd: str = "",
    workspaces: dict[str, str] | None = None,
) -> str:
    mapping = workspaces or {}
    cwd = str(explicit_cwd or "").strip()
    if cwd:
        candidate = Path(cwd).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            return ""
        if candidate.is_dir() and _within(resolved, plugin_home()):
            return str(resolved)
        return ""
    key = str(workspace or "default").strip() or "default"
    if key in mapping:
        mapped = Path(str(mapping[key])).expanduser()
        try:
            resolved = mapped.resolve()
        except OSError:
            return ""
        if _within(resolved, plugin_home()) and resolved.is_dir():
            return str(resolved)
        return ""
    if not is_safe_workspace_key(key):
        return ""
    path = workspaces_root() / key
    path.mkdir(parents=True, exist_ok=True)
    return str(path.resolve())
