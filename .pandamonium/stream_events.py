"""Normalize Cursor SDK run stream events into parity UI blocks."""

from __future__ import annotations

from typing import Any

PARITY_TYPES = frozenset({"text", "thinking", "tool", "shell", "usage", "artifact", "error", "status"})
DISPLAY_BLOCK_TYPES = frozenset({"text", "thinking", "tool", "shell", "artifact", "error"})
_SDK_REPR_PREFIX = "SDK"


def sdk_message_to_stream_event(message: Any) -> dict[str, Any] | None:
    """Convert cursor-sdk run message objects into normalizable stream events."""
    if message is None:
        return None
    if isinstance(message, dict):
        return dict(message)
    if hasattr(message, "to_json") and callable(message.to_json):
        payload = message.to_json()
        if isinstance(payload, dict):
            return payload
    msg_type = str(getattr(message, "type", "") or "").strip().lower()
    if msg_type == "assistant":
        envelope = getattr(message, "message", None)
        content = getattr(envelope, "content", None) if envelope is not None else None
        blocks: list[dict[str, Any]] = []
        for block in content or ():
            btype = str(getattr(block, "type", "") or "")
            if btype == "text":
                text = str(getattr(block, "text", "") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
            elif btype == "tool_use":
                tool_input = getattr(block, "input", None)
                blocks.append(
                    {
                        "type": "tool_use",
                        "name": str(getattr(block, "name", "tool") or "tool"),
                        "input": tool_input if isinstance(tool_input, dict) else {},
                    }
                )
        if blocks:
            return {"type": "message", "message": {"role": "assistant", "content": blocks}}
        return None
    if msg_type == "thinking":
        text = str(getattr(message, "text", "") or "")
        if not text:
            return None
        return {"type": "update", "update": {"type": "thinking_delta", "delta": text}}
    if msg_type == "tool_call":
        name = str(getattr(message, "name", "tool") or "tool")
        tool_input = getattr(message, "args", None)
        if not isinstance(tool_input, dict):
            tool_input = {}
        status = str(getattr(message, "status", "") or "running").lower()
        if status in {"running", "started"}:
            return {"type": "update", "update": {"type": "tool_call_started", "name": name, "input": tool_input}}
        return {
            "type": "update",
            "update": {
                "type": "tool_call_completed",
                "name": name,
                "input": tool_input,
                "output": getattr(message, "result", None),
            },
        }
    if msg_type == "usage":
        usage = getattr(message, "usage", None)
        payload: dict[str, Any]
        if usage is not None and hasattr(usage, "__dataclass_fields__"):
            from dataclasses import asdict

            payload = asdict(usage)
        elif isinstance(usage, dict):
            payload = usage
        else:
            payload = {}
        return {"type": "update", "update": {"type": "usage", "usage": payload}}
    if msg_type == "status":
        text = str(getattr(message, "status", "") or getattr(message, "message", "") or "").strip()
        return {"type": "update", "update": {"type": "status", "text": text}} if text else None
    return None


def normalize_stream_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    event_type = str(raw.get("type") or "").strip().lower()
    if event_type == "error":
        text = str(raw.get("text") or raw.get("message") or "error").strip()
        return {"type": "error", "text": text} if text else None

    message = raw.get("message")
    if isinstance(message, dict):
        nested = _normalize_message_dict(message)
        if nested:
            return nested
    if isinstance(message, str) and message.strip():
        stripped = message.strip()
        if stripped.startswith(_SDK_REPR_PREFIX) and "Message(" in stripped:
            return None
        return {"type": "text", "text": stripped}

    update = raw.get("update")
    if isinstance(update, dict):
        nested = _normalize_update_dict(update)
        if nested:
            return nested

    if event_type in {"thinking", "tool", "shell", "usage", "artifact", "status"}:
        payload = {key: value for key, value in raw.items() if key != "type"}
        payload["type"] = event_type
        return payload

    return None


def events_to_parity_blocks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    text_buffer: list[str] = []
    thinking_buffer: list[str] = []

    def flush_text() -> None:
        if not text_buffer:
            return
        text = "".join(text_buffer).strip()
        text_buffer.clear()
        if text:
            blocks.append({"type": "text", "text": text})

    def flush_thinking() -> None:
        if not thinking_buffer:
            return
        text = "".join(thinking_buffer).strip()
        thinking_buffer.clear()
        if text:
            blocks.append({"type": "thinking", "text": text, "collapsed": True})

    for raw in events:
        if not isinstance(raw, dict):
            continue
        block = normalize_stream_event(raw)
        if not block:
            continue
        kind = str(block.get("type") or "")
        if kind == "text":
            delta = str(block.get("text") or "")
            if delta:
                text_buffer.append(delta)
            continue
        if kind == "thinking":
            delta = str(block.get("text") or block.get("delta") or "")
            if delta:
                thinking_buffer.append(delta)
            continue
        flush_text()
        flush_thinking()
        if kind in DISPLAY_BLOCK_TYPES:
            blocks.append(block)
    flush_text()
    flush_thinking()
    return blocks


def _normalize_message_dict(message: dict[str, Any]) -> dict[str, Any] | None:
    role = str(message.get("role") or "").lower()
    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text = str(block.get("text") or "")
                if text:
                    parts.append(text)
            elif block_type == "tool_use":
                return {
                    "type": "tool",
                    "name": str(block.get("name") or "tool"),
                    "input": block.get("input") if isinstance(block.get("input"), dict) else {},
                    "summary": str(block.get("name") or "tool"),
                    "status": "completed",
                }
        if parts:
            return {"type": "text", "text": "".join(parts)}
    if role == "assistant" and isinstance(message.get("text"), str):
        text = message["text"].strip()
        return {"type": "text", "text": text} if text else None
    return None


def _normalize_update_dict(update: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(update.get("type") or update.get("updateType") or "").lower()
    if "textdelta" in kind or kind == "text_delta":
        text = str(update.get("text") or update.get("delta") or "")
        return {"type": "text", "text": text} if text else None
    if "thinking" in kind:
        text = str(update.get("text") or update.get("delta") or "")
        return {"type": "thinking", "text": text, "collapsed": True} if text else None
    if "toolcallstarted" in kind or kind == "tool_call_started":
        return {
            "type": "tool",
            "name": str(update.get("name") or update.get("toolName") or "tool"),
            "input": update.get("input") if isinstance(update.get("input"), dict) else {},
            "summary": str(update.get("name") or update.get("toolName") or "tool"),
            "status": "running",
        }
    if "toolcallcompleted" in kind or kind == "tool_call_completed":
        return {
            "type": "tool",
            "name": str(update.get("name") or update.get("toolName") or "tool"),
            "input": update.get("input") if isinstance(update.get("input"), dict) else {},
            "output": update.get("output"),
            "summary": str(update.get("name") or update.get("toolName") or "tool"),
            "status": "completed",
        }
    if "shelloutput" in kind:
        return {
            "type": "shell",
            "text": str(update.get("text") or update.get("delta") or update.get("output") or ""),
        }
    if kind.endswith("usage") or "usage" in kind:
        usage = update.get("usage") if isinstance(update.get("usage"), dict) else update
        return {"type": "usage", "usage": usage}
    if "artifact" in kind:
        return {
            "type": "artifact",
            "name": str(update.get("name") or "artifact"),
            "url": str(update.get("url") or update.get("path") or ""),
        }
    if "status" in kind:
        return {"type": "status", "text": str(update.get("text") or update.get("status") or "")}
    return None
