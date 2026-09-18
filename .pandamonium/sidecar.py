#!/usr/bin/env python3
"""Cursor-agents MAD-960 sidecar. Loopback only."""

from __future__ import annotations

import asyncio
import hmac
import importlib.util
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

from workspace import is_safe_workspace_key, resolve_agent_cwd
_GUARD_PATH = _BRIDGE_DIR / "subscription_guard.py"
_SETTINGS_PATH = _BRIDGE_DIR / "agent_settings.py"
_CANVAS_PATH = _BRIDGE_DIR / "canvas_watch.py"
_IDE_GUARD_PATH = _BRIDGE_DIR / "ide_agent_guard.py"
_FORK_COMPACTION_PATH = _BRIDGE_DIR / "fork_compaction.py"
_GUARD_SPEC = importlib.util.spec_from_file_location("cursor_subscription_guard", _GUARD_PATH)
_SETTINGS_SPEC = importlib.util.spec_from_file_location("cursor_bridge_agent_settings", _SETTINGS_PATH)
_CANVAS_SPEC = importlib.util.spec_from_file_location("cursor_bridge_canvas", _CANVAS_PATH)
_IDE_GUARD_SPEC = importlib.util.spec_from_file_location("cursor_bridge_ide_agent_guard", _IDE_GUARD_PATH)
_FORK_COMPACTION_SPEC = importlib.util.spec_from_file_location("cursor_bridge_fork_compaction", _FORK_COMPACTION_PATH)
assert _GUARD_SPEC and _GUARD_SPEC.loader
assert _SETTINGS_SPEC and _SETTINGS_SPEC.loader
assert _CANVAS_SPEC and _CANVAS_SPEC.loader
assert _IDE_GUARD_SPEC and _IDE_GUARD_SPEC.loader
assert _FORK_COMPACTION_SPEC and _FORK_COMPACTION_SPEC.loader
_guard = importlib.util.module_from_spec(_GUARD_SPEC)
_settings = importlib.util.module_from_spec(_SETTINGS_SPEC)
_canvas = importlib.util.module_from_spec(_CANVAS_SPEC)
_ide_guard = importlib.util.module_from_spec(_IDE_GUARD_SPEC)
_fork_compaction = importlib.util.module_from_spec(_FORK_COMPACTION_SPEC)
_GUARD_SPEC.loader.exec_module(_guard)
_SETTINGS_SPEC.loader.exec_module(_settings)
_CANVAS_SPEC.loader.exec_module(_canvas)
_IDE_GUARD_SPEC.loader.exec_module(_ide_guard)
_FORK_COMPACTION_SPEC.loader.exec_module(_fork_compaction)
REQUIRED_MODEL = _guard.REQUIRED_MODEL
SubscriptionGuardError = _guard.SubscriptionGuardError
assert_agent_options = _guard.assert_agent_options
assert_no_cloud_url = _guard.assert_no_cloud_url
title_from_prompt = _guard.title_from_prompt
validate_startup_models = _guard.validate_startup_models
build_agent_options = _settings.build_agent_options
build_send_options = _settings.build_send_options
ensure_sdk_agent_store = _settings.ensure_sdk_agent_store
capabilities_summary = _settings.capabilities_summary
resolve_canvas_path = _canvas.resolve_canvas_path
detect_canvas_path_from_event = _canvas.detect_canvas_path_from_event
build_canvas_open_payload = _canvas.build_canvas_open_payload
IdeAgentResumeForbidden = _ide_guard.IdeAgentResumeForbidden
is_ide_transcript_agent_id = _ide_guard.is_ide_transcript_agent_id
resolve_sdk_resume_id = _ide_guard.resolve_sdk_resume_id
build_fork_pending_context = _fork_compaction.build_fork_pending_context
build_handoff_user_prompt = _fork_compaction.build_handoff_user_prompt
parse_handoff_response = _fork_compaction.parse_handoff_response
FORK_TAIL_MESSAGE_LIMIT = _fork_compaction.FORK_TAIL_MESSAGE_LIMIT

try:
    from core.atomic_io import atomic_write_json
except ModuleNotFoundError:
    from atomic_io import atomic_write_json  # type: ignore

HOST = os.getenv("ODYSSEUS_CURSOR_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("PANDAMONIUM_PORT") or os.getenv("ODYSSEUS_CURSOR_BRIDGE_PORT", "8050"))
TOKEN_FILE = Path(os.getenv("ODYSSEUS_CURSOR_BRIDGE_TOKEN_FILE", str(Path(os.environ.get("HOME", "/tmp")) / "state" / "token")))
STATE_DIR = Path(os.getenv("ODYSSEUS_CURSOR_BRIDGE_STATE_DIR", str(Path(os.environ.get("HOME", "/tmp")) / "state")))
REGISTRY_FILE = STATE_DIR / "agents.json"
SETTINGS_FILE = STATE_DIR / "settings.json"
BRIDGE_PROTOCOL = "pandamonium.cursor-bridge.v1"
STARTED_AT = time.time()


def _load_workspaces() -> dict[str, str]:
    try:
        raw = json.loads(os.getenv("ODYSSEUS_CURSOR_WORKSPACES_JSON", "{}"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for name, path in raw.items():
        logical = str(name or "").strip()
        resolved = Path(str(path or "")).expanduser().resolve()
        if logical and is_safe_workspace_key(logical) and resolved.is_absolute() and resolved.is_dir():
            result[logical] = str(resolved)
    return result


WORKSPACES = _load_workspaces()
DEFAULT_WORKSPACE = next(iter(WORKSPACES), "")

try:
    from cursor_sdk.errors import AgentNotFoundError
except ImportError:

    class AgentNotFoundError(Exception):
        """Fallback when cursor_sdk.errors is unavailable."""


def _resolve_cwd(workspace: str, explicit_cwd: str = "") -> str:
    return resolve_agent_cwd(workspace, explicit_cwd=explicit_cwd, workspaces=WORKSPACES)


def _sdk_agent_id(row: dict[str, Any]) -> str:
    return str(row.get("sdk_agent_id") or row.get("agent_id") or "")


def _messages_to_context_prompt(messages: list[dict[str, Any]], *, max_messages: int = 24) -> str:
    lines = ["Continue this Cursor IDE session from Panda. Prior transcript:\n"]
    for msg in messages[-max_messages:]:
        role = str(msg.get("role") or "user").upper()
        chunks: list[str] = []
        for block in msg.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                chunks.append(str(block["text"]).strip())
            elif block.get("type") == "tool":
                summary = str(block.get("summary") or block.get("name") or "tool").strip()
                chunks.append(f"[tool {summary}]")
        text = " ".join(chunks).strip()
        if text:
            lines.append(f"{role}: {text}")
    lines.append("\nContinue naturally from this context.")
    return "\n".join(lines)[:50_000]


async def _resume_sdk_agent(client: Any, agent_id: str, options: dict[str, Any]) -> Any:
    registry = _load_registry()
    row = registry.get(agent_id) or {}
    try:
        resume_id = resolve_sdk_resume_id(agent_id, row)
    except IdeAgentResumeForbidden as exc:
        raise AgentNotFoundError(str(exc)) from exc
    return await client.resume_agent(resume_id, options)


async def _collect_run_assistant_text(run: Any) -> str:
    events: list[dict[str, Any]] = []
    mod = _load_stream_events()
    async for message in run.messages():
        event = mod.sdk_message_to_stream_event(message)
        if event:
            events.append(event)
    await run.wait()
    blocks = _events_to_assistant_blocks(events)
    chunks: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            chunks.append(str(block["text"]))
    return "\n".join(chunks).strip()


async def _run_fork_compaction(agent: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = build_handoff_user_prompt(messages)
    run = await agent.send(prompt, build_send_options())
    try:
        text = await _collect_run_assistant_text(run)
    except Exception:
        return parse_handoff_response("")
    return parse_handoff_response(text)


async def _prepare_ide_fork(
    agent_id: str,
    *,
    workspace: str,
    cwd: str,
    title: str,
    messages: list[dict[str, Any]] | None,
    source: str = "ide",
) -> dict[str, Any]:
    client = await _ensure_client()
    options = assert_agent_options(build_agent_options(api_key=STATE.api_key, cwd=cwd, model=REQUIRED_MODEL))
    agent = await client.create_agent(options)
    sdk_id = getattr(agent, "agent_id", None) or getattr(agent, "id", None)
    if not sdk_id:
        raise HTTPException(status_code=502, detail="cursor_agent_missing")
    transcript = list(messages or [])[-500:]
    handoff = await _run_fork_compaction(agent, transcript)
    pending_context = build_fork_pending_context(handoff, transcript, tail_limit=FORK_TAIL_MESSAGE_LIMIT)
    async with STATE.lock:
        STATE.agent_handles[agent_id] = agent
    row = await _update_registry(
        agent_id,
        sdk_agent_id=str(sdk_id),
        title=title,
        workspace=workspace,
        status="idle",
        source=source,
        forked=True,
        ide_source_id=agent_id if is_ide_transcript_agent_id(agent_id) else None,
        handoff=handoff,
        pending_context=pending_context or None,
        error=None,
    )
    return row


async def _refork_ide_agent(agent_id: str, row: dict[str, Any], *, cwd: str) -> Any | None:
    messages = list(row.get("messages") or [])
    pending_context = row.get("pending_context") if isinstance(row.get("pending_context"), list) else None
    if pending_context and not messages:
        messages = list(pending_context)
    if not messages:
        return None
    workspace = str(row.get("workspace") or DEFAULT_WORKSPACE)
    await _prepare_ide_fork(
        agent_id,
        workspace=workspace,
        cwd=cwd,
        title=str(row.get("title") or "Cursor agent"),
        messages=messages,
        source=str(row.get("source") or "ide"),
    )
    async with STATE.lock:
        return STATE.agent_handles.get(agent_id)


def _token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _authorized(header: str | None) -> bool:
    expected = _token()
    supplied = (header or "").removeprefix("Bearer ").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = _token()
    if not expected:
        return
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _load_registry() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_registry(payload: dict[str, dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_json(str(REGISTRY_FILE), payload, indent=2)
    try:
        REGISTRY_FILE.chmod(0o600)
    except OSError:
        pass


def _dismissed_agent_ids() -> set[str]:
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    raw = payload.get("dismissed_agent_ids") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return set()
    return {str(row).strip() for row in raw if str(row).strip()}


@dataclass
class BridgeState:
    client: Any | None = None
    api_key: str = ""
    guard_failed: str | None = None
    active_runs: dict[str, asyncio.Task] = field(default_factory=dict)
    run_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    canvas_open_paths: dict[str, set[str]] = field(default_factory=dict)
    canvas_open_global: set[str] = field(default_factory=set)
    agent_handles: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


STATE = BridgeState()


async def _ensure_client() -> Any:
    if STATE.guard_failed:
        raise HTTPException(status_code=503, detail=STATE.guard_failed)
    if STATE.client is None:
        await _maybe_launch_client()
    if STATE.client is None:
        raise HTTPException(status_code=503, detail="cursor_bridge_not_ready")
    return STATE.client


async def _maybe_launch_client() -> None:
    if STATE.client is not None or STATE.guard_failed:
        return
    api_key = str(STATE.api_key or os.getenv("CURSOR_API_KEY", "")).strip()
    if not api_key:
        return
    STATE.api_key = api_key
    if not WORKSPACES:
        STATE.guard_failed = "cursor_workspaces_not_configured"
        return
    default_cwd = WORKSPACES.get(DEFAULT_WORKSPACE) or next(iter(WORKSPACES.values()))
    try:
        ensure_sdk_agent_store(default_cwd)
        from cursor_sdk import AsyncClient

        client = await AsyncClient.launch_bridge(
            workspace=default_cwd,
            allow_api_key_env_fallback=False,
        )
        await validate_startup_models(client, api_key)
        STATE.client = client
    except SubscriptionGuardError as exc:
        STATE.guard_failed = exc.reason
    except Exception:
        # Transient startup failures should not block registry reads; retry on next send.
        STATE.client = None


def _public_agent(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": row.get("agent_id"),
        "title": row.get("title") or "Cursor agent",
        "workspace": row.get("workspace"),
        "status": row.get("status") or "idle",
        "source": row.get("source") or "bridge",
        "run_id": row.get("run_id"),
        "updated_at": row.get("updated_at"),
        "error": row.get("error"),
        "read_only": False,
        "forked": bool(row.get("forked")),
        "sdk_agent_id": row.get("sdk_agent_id"),
        "message_count": len(row.get("messages") or []),
    }


def _blocks_from_message(message: object) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not isinstance(message, dict):
        return blocks
    content = message.get("content")
    if not isinstance(content, list):
        return blocks
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip()
        if block_type == "text":
            text = str(block.get("text") or "").strip()
            if text:
                blocks.append({"type": "text", "text": text})
        elif block_type == "tool_use":
            name = str(block.get("name") or "tool").strip() or "tool"
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            blocks.append({"type": "tool", "name": name, "input": tool_input, "summary": name})
    return blocks


async def _append_message(agent_id: str, role: str, blocks: list[dict[str, Any]]) -> None:
    if not blocks:
        return
    async with STATE.lock:
        registry = _load_registry()
        row = dict(registry.get(agent_id) or {})
        messages = list(row.get("messages") or [])
        messages.append({"id": f"msg-{len(messages)}", "role": role, "blocks": blocks})
        row["messages"] = messages[-500:]
        row["agent_id"] = agent_id
        row["updated_at"] = int(time.time())
        registry[agent_id] = row
        _save_registry(registry)


def _load_stream_events():
    from importlib.util import module_from_spec, spec_from_file_location

    path = Path(__file__).resolve().parent / "stream_events.py"
    spec = spec_from_file_location("stream_events", path)
    if spec and spec.loader:
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise RuntimeError("stream_events module unavailable")


def _events_to_assistant_blocks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mod = _load_stream_events()
    return mod.events_to_parity_blocks(events)


def _canvas_paths_for_row(row: dict[str, Any], run_id: str = "") -> list[str]:
    workspace = str(row.get("workspace") or DEFAULT_WORKSPACE)
    cwd = _resolve_cwd(workspace)
    found: set[str] = set()
    for msg in row.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        for path in _canvas.collect_canvas_paths_from_blocks(list(msg.get("blocks") or []), cwd=cwd or ""):
            found.add(path)
    if run_id:
        for event in STATE.run_events.get(run_id, []):
            if event.get("type") == "canvas_open":
                raw = str(event.get("path") or "")
                resolved = resolve_canvas_path(raw, cwd=cwd or "")
                if resolved:
                    found.add(str(resolved))
    canvas_dir = _canvas.canvas_dir_for_cwd(cwd or "")
    if canvas_dir.is_dir():
        cutoff = int(row.get("updated_at") or 0) - 900
        for path in canvas_dir.glob("*.canvas.tsx"):
            try:
                if path.stat().st_mtime >= cutoff:
                    found.add(str(path.resolve()))
            except OSError:
                continue
    return sorted(found)


def _session_payload(row: dict[str, Any]) -> dict[str, Any]:
    messages = list(row.get("messages") or [])
    run_id = str(row.get("run_id") or "")
    if row.get("status") == "running" and run_id:
        live_blocks = _events_to_assistant_blocks(STATE.run_events.get(run_id, []))
        if live_blocks:
            messages = messages + [{"id": "msg-live", "role": "assistant", "blocks": live_blocks, "live": True}]
    return {
        "agent_id": row.get("agent_id"),
        "title": row.get("title") or "Cursor agent",
        "workspace": row.get("workspace"),
        "status": row.get("status") or "idle",
        "source": row.get("source") or "bridge",
        "run_id": row.get("run_id"),
        "updated_at": row.get("updated_at"),
        "read_only": False,
        "can_send": STATE.client is not None and not STATE.guard_failed,
        "forked": bool(row.get("forked")),
        "sdk_agent_id": row.get("sdk_agent_id"),
        "message_count": len(messages),
        "messages": messages,
        "canvas_paths": _canvas_paths_for_row(row, run_id),
    }


async def _append_event(run_id: str, event: dict[str, Any]) -> None:
    async with STATE.lock:
        bucket = STATE.run_events.setdefault(run_id, [])
        bucket.append(event)
        if len(bucket) > 500:
            del bucket[: len(bucket) - 500]


async def _maybe_emit_canvas_open(agent_id: str, run_id: str, event: dict[str, Any]) -> None:
    registry = _load_registry()
    row = registry.get(agent_id) or {}
    workspace = str(row.get("workspace") or DEFAULT_WORKSPACE)
    cwd = _resolve_cwd(workspace)
    path = detect_canvas_path_from_event(event, cwd=cwd or "")
    if not path:
        return
    path_key = str(path)
    async with STATE.lock:
        seen = STATE.canvas_open_paths.setdefault(str(run_id), set())
        if path_key in seen or path_key in STATE.canvas_open_global:
            return
        seen.add(path_key)
        STATE.canvas_open_global.add(path_key)
    public_url = os.getenv("APP_PUBLIC_URL", "").strip()
    payload = build_canvas_open_payload(path, app_public_url=public_url)
    await _append_event(str(run_id), payload)


async def _update_registry(agent_id: str, **changes: Any) -> dict[str, Any]:
    async with STATE.lock:
        registry = _load_registry()
        row = dict(registry.get(agent_id) or {})
        row["agent_id"] = agent_id
        row.update(changes)
        row["updated_at"] = int(time.time())
        registry[agent_id] = row
        _save_registry(registry)
        return row


async def _consume_run(agent_id: str, run: Any) -> None:
    run_id = getattr(run, "run_id", None) or getattr(run, "id", None) or str(uuid.uuid4())
    await _update_registry(agent_id, status="running", run_id=run_id, error=None)
    try:
        async for message in run.messages():
            mod = _load_stream_events()
            event = mod.sdk_message_to_stream_event(message)
            if not event:
                continue
            event["created_at"] = int(time.time())
            await _append_event(str(run_id), event)
            await _maybe_emit_canvas_open(agent_id, str(run_id), event)
        result = await run.wait()
        status = getattr(result, "status", None) or (result.get("status") if isinstance(result, dict) else "finished")
        terminal = "failed" if status == "error" else "idle"
        error = None
        if status == "error":
            error = "cursor_run_failed"
            terminal = "failed"
        assistant_blocks = _events_to_assistant_blocks(STATE.run_events.get(str(run_id), []))
        if assistant_blocks:
            await _append_message(agent_id, "assistant", assistant_blocks)
        await _update_registry(agent_id, status=terminal, error=error)
    except Exception as exc:
        await _update_registry(agent_id, status="failed", error=str(exc)[:240])
        await _append_event(str(run_id), {"type": "error", "text": str(exc)[:240]})
    finally:
        async with STATE.lock:
            STATE.active_runs.pop(str(run_id), None)
            STATE.canvas_open_paths.pop(str(run_id), None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    api_key = os.getenv("CURSOR_API_KEY", "").strip()
    STATE.api_key = api_key
    if not api_key:
        yield
        return
    if not WORKSPACES:
        STATE.guard_failed = "cursor_workspaces_not_configured"
        yield
        return
    default_cwd = WORKSPACES.get(DEFAULT_WORKSPACE) or next(iter(WORKSPACES.values()))
    try:
        ensure_sdk_agent_store(default_cwd)
        from cursor_sdk import AsyncClient

        client = await AsyncClient.launch_bridge(
            workspace=default_cwd,
            allow_api_key_env_fallback=False,
        )
        await validate_startup_models(client, api_key)
        STATE.client = client
    except SubscriptionGuardError as exc:
        STATE.guard_failed = exc.reason
    except Exception:
        STATE.client = None
    try:
        yield
    finally:
        if STATE.client is not None:
            await STATE.client.aclose()
            STATE.client = None


app = FastAPI(title="cursor-agents", lifespan=lifespan)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_UI = _BRIDGE_DIR / "ui"
if _UI.is_dir():
    app.mount("/ui/assets", StaticFiles(directory=_UI), name="ui-assets")


@app.get("/ui/sidebar")
async def ui_sidebar():
    path = _UI / "sidebar.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="ui_missing")
    return FileResponse(path)


@app.get("/ui/overlay")
async def ui_overlay():
    path = _UI / "overlay.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="ui_missing")
    return FileResponse(path)


@app.get("/ui/icon.svg")
async def ui_icon():
    path = _UI / "icon.svg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="ui_missing")
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/canvas/events")
async def canvas_events():
    from canvas_watch import snapshot_open_events
    return {"events": snapshot_open_events()}

@app.get("/health")
async def health() -> dict[str, Any]:
    caps = capabilities_summary()
    return {
        "ok": STATE.client is not None and not STATE.guard_failed,
        "protocol": BRIDGE_PROTOCOL,
        "model_lock": REQUIRED_MODEL,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "guard_failed": STATE.guard_failed,
        "capabilities": caps,
    }


@app.get("/status")
async def status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    registry = _load_registry()
    caps = capabilities_summary()
    return {
        "configured": bool(STATE.api_key),
        "connected": STATE.client is not None and not STATE.guard_failed,
        "model_lock": REQUIRED_MODEL,
        "workspaces": list(WORKSPACES),
        "agent_count": len(registry),
        "guard_failed": STATE.guard_failed,
        "protocol": BRIDGE_PROTOCOL,
        "capabilities": caps,
    }


@app.get("/agents")
async def list_agents(
    authorization: str | None = Header(default=None),
    workspace: str | None = None,
    source: str = "bridge",
) -> dict[str, Any]:
    _require_auth(authorization)
    registry = _load_registry()
    hidden = _dismissed_agent_ids()
    items = [_public_agent(row) for row in registry.values() if str(row.get("agent_id") or "") not in hidden]
    if workspace:
        items = [row for row in items if row.get("workspace") == workspace]
    if source == "bridge":
        items = [row for row in items if row.get("source") == "bridge"]
    await _maybe_launch_client()
    sdk_items: list[dict[str, Any]] = []
    target_workspace = workspace or DEFAULT_WORKSPACE
    cwd = _resolve_cwd(target_workspace)
    if STATE.client is not None and cwd:
        try:
            listed = await STATE.client.agents.list(runtime="local", cwd=cwd, api_key=STATE.api_key)
            raw_items = getattr(listed, "items", None) or []
            for info in raw_items:
                agent_id = getattr(info, "agent_id", None) or getattr(info, "id", None)
                if not agent_id:
                    continue
                agent_id = str(agent_id)
                if agent_id in hidden:
                    continue
                if agent_id not in registry:
                    registry[agent_id] = {
                        "agent_id": agent_id,
                        "title": "Cursor agent",
                        "workspace": target_workspace,
                        "status": "idle",
                        "source": "bridge",
                        "updated_at": int(time.time()),
                    }
                    _save_registry(registry)
                sdk_items.append(_public_agent(registry[agent_id]))
        except Exception:
            sdk_items = []
    merged = {row["agent_id"]: row for row in items}
    for row in sdk_items:
        merged[row["agent_id"]] = row
    ordered = sorted(merged.values(), key=lambda row: int(row.get("updated_at") or 0), reverse=True)
    return {
        "items": ordered,
        "connected": STATE.client is not None and not STATE.guard_failed,
    }


@app.post("/agents")
async def create_agent(payload: dict[str, Any], authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    client = await _ensure_client()
    workspace = str(payload.get("workspace") or DEFAULT_WORKSPACE).strip()
    cwd = _resolve_cwd(workspace)
    if not cwd:
        raise HTTPException(status_code=400, detail="unknown_workspace")
    try:
        ensure_sdk_agent_store(cwd)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"cursor_agent_store_not_writable: {exc}") from exc
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > 50_000:
        raise HTTPException(status_code=400, detail="invalid_prompt")
    title = str(payload.get("title") or title_from_prompt(prompt)).strip()[:120]
    options = assert_agent_options(build_agent_options(api_key=STATE.api_key, cwd=cwd, model=REQUIRED_MODEL))
    try:
        agent = await client.create_agent(options)
        agent_id = getattr(agent, "agent_id", None) or getattr(agent, "id", None)
        if not agent_id:
            raise HTTPException(status_code=502, detail="cursor_agent_missing")
        await _update_registry(
            str(agent_id),
            title=title,
            workspace=workspace,
            status="running",
            source="bridge",
            error=None,
        )
        await _append_message(str(agent_id), "user", [{"type": "text", "text": prompt}])
        run = await agent.send(prompt, build_send_options())
        run_id = getattr(run, "run_id", None) or getattr(run, "id", None)
        task = asyncio.create_task(_consume_run(str(agent_id), run))
        async with STATE.lock:
            if run_id:
                STATE.active_runs[str(run_id)] = task
        return {"agent": _public_agent(_load_registry()[str(agent_id)]), "run_id": run_id}
    except SubscriptionGuardError as exc:
        raise HTTPException(status_code=403, detail=exc.reason) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:240]) from exc


@app.post("/agents/{agent_id}/fork")
async def fork_agent_endpoint(
    agent_id: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    workspace = str(payload.get("workspace") or DEFAULT_WORKSPACE).strip()
    cwd = _resolve_cwd(workspace, str(payload.get("cwd") or ""))
    if not cwd:
        raise HTTPException(status_code=400, detail="unknown_workspace")
    try:
        ensure_sdk_agent_store(cwd)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"cursor_agent_store_not_writable: {exc}") from exc
    title = str(payload.get("title") or "Cursor agent").strip()[:120]
    source = str(payload.get("source") or "ide")
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else None
    if not messages:
        raise HTTPException(status_code=400, detail="messages_required_for_fork")
    registry = _load_registry()
    existing = registry.get(agent_id) or {}
    if existing.get("forked") and existing.get("sdk_agent_id"):
        return {"agent": _public_agent(existing), "forked": True, "already_forked": True}
    try:
        row = await _prepare_ide_fork(
            agent_id,
            workspace=workspace,
            cwd=cwd,
            title=title,
            messages=messages,
            source=source,
        )
        return {"agent": _public_agent(row), "forked": True}
    except SubscriptionGuardError as exc:
        raise HTTPException(status_code=403, detail=exc.reason) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:240]) from exc


@app.post("/agents/{agent_id}/resume")
async def resume_agent_endpoint(
    agent_id: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    if is_ide_transcript_agent_id(agent_id):
        raise HTTPException(status_code=409, detail="ide_fork_required")
    client = await _ensure_client()
    workspace = str(payload.get("workspace") or DEFAULT_WORKSPACE).strip()
    cwd = _resolve_cwd(workspace, str(payload.get("cwd") or ""))
    if not cwd:
        raise HTTPException(status_code=400, detail="unknown_workspace")
    try:
        ensure_sdk_agent_store(cwd)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"cursor_agent_store_not_writable: {exc}") from exc
    options = assert_agent_options(build_agent_options(api_key=STATE.api_key, cwd=cwd, model=REQUIRED_MODEL))
    title = str(payload.get("title") or "Cursor agent").strip()[:120]
    source = str(payload.get("source") or "bridge")
    try:
        await _resume_sdk_agent(client, agent_id, options)
        await _update_registry(
            agent_id,
            title=title,
            workspace=workspace,
            status="idle",
            source=source,
            error=None,
        )
        return {"agent": _public_agent(_load_registry()[agent_id])}
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found") from None
    except SubscriptionGuardError as exc:
        raise HTTPException(status_code=403, detail=exc.reason) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:240]) from exc


@app.post("/agents/{agent_id}/send")
async def send_agent(agent_id: str, payload: dict[str, Any], authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    client = await _ensure_client()
    registry = _load_registry()
    row = registry.get(agent_id)
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    if is_ide_transcript_agent_id(agent_id) and not row.get("forked"):
        raise HTTPException(status_code=409, detail="ide_fork_required")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > 50_000:
        raise HTTPException(status_code=400, detail="invalid_prompt")
    workspace = str(row.get("workspace") or DEFAULT_WORKSPACE)
    cwd = _resolve_cwd(workspace)
    if not cwd:
        raise HTTPException(status_code=400, detail="unknown_workspace")
    try:
        ensure_sdk_agent_store(cwd)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"cursor_agent_store_not_writable: {exc}") from exc
    options = assert_agent_options(build_agent_options(api_key=STATE.api_key, cwd=cwd, model=REQUIRED_MODEL))
    pending_context = row.get("pending_context") if isinstance(row.get("pending_context"), list) else None
    prompt_to_send = prompt
    if pending_context:
        prompt_to_send = f"{_messages_to_context_prompt(pending_context)}\n\nUSER (new message):\n{prompt}"[:50_000]
    try:
        async with STATE.lock:
            agent = STATE.agent_handles.pop(agent_id, None)
        if agent is None:
            agent = await _resume_sdk_agent(client, agent_id, options)
        try:
            run = await agent.send(prompt_to_send, build_send_options())
        except AgentNotFoundError:
            if not row.get("forked"):
                raise
            agent = await _refork_ide_agent(agent_id, row, cwd=cwd)
            if agent is None:
                raise
            run = await agent.send(prompt_to_send, build_send_options())
        run_id = getattr(run, "run_id", None) or getattr(run, "id", None)
        await _append_message(agent_id, "user", [{"type": "text", "text": prompt}])
        await _update_registry(
            agent_id,
            status="running",
            run_id=run_id,
            error=None,
            pending_context=None,
        )
        task = asyncio.create_task(_consume_run(agent_id, run))
        async with STATE.lock:
            if run_id:
                STATE.active_runs[str(run_id)] = task
        return {"agent": _public_agent(_load_registry()[agent_id]), "run_id": run_id}
    except AgentNotFoundError as exc:
        await _update_registry(agent_id, status="failed", error="agent_not_found")
        raise HTTPException(status_code=404, detail="agent_not_found") from exc
    except SubscriptionGuardError as exc:
        await _update_registry(agent_id, status="failed", error=exc.reason)
        raise HTTPException(status_code=403, detail=exc.reason) from exc
    except Exception as exc:
        await _update_registry(agent_id, status="failed", error=str(exc)[:240])
        raise HTTPException(status_code=502, detail=str(exc)[:240]) from exc


@app.get("/agents/{agent_id}/runs/{run_id}/stream")
async def stream_run(agent_id: str, run_id: str, authorization: str | None = Header(default=None)):
    _require_auth(authorization)

    async def event_source():
        seen = 0
        while True:
            async with STATE.lock:
                events = list(STATE.run_events.get(run_id, []))
            for event in events[seen:]:
                seen += 1
                yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"
            registry = _load_registry()
            row = registry.get(agent_id) or {}
            if row.get("status") not in {"running"} and seen >= len(events):
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/agents/{agent_id}/session")
async def agent_session(agent_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    registry = _load_registry()
    row = registry.get(agent_id)
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return _session_payload(row)


@app.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    registry = _load_registry()
    row = registry.get(agent_id)
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    run_id = str(row.get("run_id") or "")
    if run_id:
        task = STATE.active_runs.get(run_id)
        if task and not task.done():
            task.cancel()
        async with STATE.lock:
            STATE.active_runs.pop(run_id, None)
            STATE.run_events.pop(run_id, None)
    registry.pop(agent_id, None)
    _save_registry(registry)
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    dismissed = _dismissed_agent_ids()
    dismissed.add(agent_id)
    payload["dismissed_agent_ids"] = sorted(dismissed)
    atomic_write_json(str(SETTINGS_FILE), payload, indent=2)
    return {"removed": True, "agent_id": agent_id}


@app.post("/canvas/open")
async def open_canvas(payload: dict[str, Any], authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    raw_path = str(payload.get("path") or "").strip()
    cwd = str(payload.get("cwd") or "").strip()
    if not cwd:
        workspace = str(payload.get("workspace") or DEFAULT_WORKSPACE)
        cwd = _resolve_cwd(workspace)
    path = resolve_canvas_path(raw_path, cwd=cwd or "")
    if not path:
        raise HTTPException(status_code=404, detail="canvas_not_found")
    public_url = os.getenv("APP_PUBLIC_URL", "").strip()
    return build_canvas_open_payload(path, app_public_url=public_url)


@app.post("/agents/{agent_id}/runs/{run_id}/cancel")
async def cancel_run(agent_id: str, run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    client = await _ensure_client()
    try:
        run = await client.get_run(run_id, runtime="local", agent_id=agent_id, api_key=STATE.api_key)
        if hasattr(run, "supports") and run.supports("cancel"):
            await run.cancel()
        await _update_registry(agent_id, status="idle")
        return {"cancelled": True}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:240]) from exc


@app.exception_handler(SubscriptionGuardError)
async def guard_handler(_request, exc: SubscriptionGuardError):
    return JSONResponse(status_code=403, content={"error": exc.code, "reason": exc.reason})


def main() -> None:
    import uvicorn

    host = "127.0.0.1"
    port = int(os.environ["PANDAMONIUM_PORT"])
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
