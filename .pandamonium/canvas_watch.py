"""Watch plugin HOME canvases. No host Cursor runtime patches."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

CANVAS_SUFFIX = ".canvas.tsx"
_TOOL_PATH_KEYS = ("path", "file_path", "filePath", "target", "target_file", "targetFile")
_PATH_RE = re.compile(r"(?:~/[^\s\"']+|/[^\s\"']+|[^\s\"']+/[^\s\"']+)\.canvas\.tsx")


def plugin_home() -> Path:
    return Path(os.environ.get("HOME") or "/tmp").expanduser().resolve()


def canvas_dir_for_cwd(cwd: str) -> Path:
    home = plugin_home()
    slug = Path(str(cwd or "default")).name or "default"
    path = home / "projects" / slug / "canvases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_canvas_path(path: str) -> bool:
    return str(path or "").strip().endswith(CANVAS_SUFFIX)


def canvas_title(path: Path) -> str:
    stem = path.name.removesuffix(CANVAS_SUFFIX)
    return re.sub(r"[-_]+", " ", stem).strip().title() or "Canvas"


def canvas_id_for_path(path: Path | str) -> str:
    return hashlib.sha256(f"canvas:{path}".encode()).hexdigest()[:12]


def resolve_canvas_path(raw_path: str, *, cwd: str = "") -> Path | None:
    candidate = str(raw_path or "").strip()
    if not candidate or not is_canvas_path(candidate):
        return None
    path = Path(candidate)
    if not path.is_absolute() and cwd:
        path = Path(cwd).expanduser().resolve() / path
    try:
        path = path.expanduser().resolve()
    except OSError:
        return None
    if not path.is_file():
        return None
    try:
        path.relative_to(plugin_home())
    except ValueError:
        return None
    if "canvases" not in path.parts:
        return None
    return path


def _extract_path_from_mapping(payload: dict[str, Any]) -> str:
    for key in _TOOL_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _paths_from_text(text: str) -> list[str]:
    if not text:
        return []
    return _PATH_RE.findall(str(text))


def detect_canvas_path_from_event(event: dict[str, Any], *, cwd: str = "") -> Path | None:
    if not isinstance(event, dict):
        return None
    candidates: list[str] = []
    if event.get("type") == "artifact":
        url = str(event.get("url") or event.get("path") or "")
        if url:
            candidates.append(url)
    update = event.get("update")
    if isinstance(update, dict):
        kind = str(update.get("type") or update.get("updateType") or "").lower()
        name = str(update.get("name") or update.get("toolName") or "").lower()
        is_completed = "completed" in kind or kind.endswith("completed")
        is_write_like = any(token in name for token in ("write", "edit", "replace", "apply", "notebook"))
        if is_completed and is_write_like:
            for key in ("input", "args", "result"):
                nested = update.get(key)
                if isinstance(nested, dict):
                    path = _extract_path_from_mapping(nested)
                    if path:
                        candidates.append(path)
            path = _extract_path_from_mapping(update)
            if path:
                candidates.append(path)
            output = update.get("output")
            if isinstance(output, str):
                candidates.extend(_paths_from_text(output))
    if event.get("type") == "tool":
        tool_name = str(event.get("name") or event.get("toolName") or "").lower()
        if any(token in tool_name for token in ("write", "edit", "replace", "apply", "notebook")):
            tool_input = event.get("input")
            if isinstance(tool_input, dict):
                path = _extract_path_from_mapping(tool_input)
                if path:
                    candidates.append(path)
    for raw in candidates:
        resolved = resolve_canvas_path(raw, cwd=cwd)
        if resolved:
            return resolved
    return None


def collect_canvas_paths_from_blocks(blocks: list[Any], *, cwd: str = "") -> list[str]:
    found: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") == "text":
            for raw in _paths_from_text(str(block.get("text") or "")):
                resolved = resolve_canvas_path(raw, cwd=cwd)
                if resolved:
                    found.add(str(resolved))
        for key in ("url", "path"):
            raw = str(block.get(key) or "")
            resolved = resolve_canvas_path(raw, cwd=cwd)
            if resolved:
                found.add(str(resolved))
    return sorted(found)


def build_canvas_open_payload(path: Path, *, app_public_url: str = "") -> dict[str, Any]:
    home = plugin_home()
    try:
        rel = str(path.resolve().relative_to(home))
    except ValueError:
        rel = str(path)
    preview = ""
    try:
        preview = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        preview = ""
    return {
        "type": "canvas_open",
        "path": rel,
        "title": canvas_title(path),
        "preview": preview,
        "canvas_id": canvas_id_for_path(path),
        "popup_url": "",
        "embed_url": "",
        "app_public_url": app_public_url or "",
    }


def list_canvas_files(home: Path | None = None) -> list[Path]:
    root = Path(home or plugin_home()) / "projects"
    if not root.is_dir():
        return []
    return sorted(root.glob("*/canvases/*.canvas.tsx"))


def snapshot_open_events(home: Path | None = None) -> list[dict[str, Any]]:
    events = []
    for path in list_canvas_files(home):
        events.append(build_canvas_open_payload(path))
    return events
