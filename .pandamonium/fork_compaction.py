"""Fork compaction: structured IDE handoff + tail messages for Panda agents."""

from __future__ import annotations

import json
import re
from typing import Any

FORK_TAIL_MESSAGE_LIMIT = 15

HANDOFF_COMPOSER_PROMPT = """You are preparing a handoff from a Cursor IDE agent session to a Panda bridge agent.

Read the conversation transcript below and reply with ONLY a JSON object (no markdown fences) using this schema:
{
  "goal": "one sentence: what the user is trying to accomplish",
  "files": ["paths or file names materially touched or discussed"],
  "next_steps": ["ordered actionable next steps, 1-5 items"],
  "summary": "2-4 sentences: current state, decisions made, blockers"
}

Rules:
- Be concrete; cite real file paths when present in the transcript.
- Do not invent tools or commits that are not in the transcript.
- next_steps must be things the Panda agent can do next in the sandbox worktree.

TRANSCRIPT:
"""

_HANDOFF_JSON_RE = re.compile(r"\{[\s\S]*\}")


def tail_messages(messages: list[dict[str, Any]], limit: int = FORK_TAIL_MESSAGE_LIMIT) -> list[dict[str, Any]]:
    rows = [row for row in (messages or []) if isinstance(row, dict)]
    if limit <= 0 or len(rows) <= limit:
        return list(rows)
    return list(rows[-limit:])


def build_handoff_user_prompt(messages: list[dict[str, Any]]) -> str:
    """Prompt for one Composer turn that produces structured handoff JSON."""
    lines: list[str] = []
    for row in messages or []:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "unknown").strip().lower()
        chunks: list[str] = []
        for block in row.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                chunks.append(str(block["text"]).strip())
            elif block.get("type") == "tool":
                summary = str(block.get("summary") or block.get("name") or "tool").strip()
                if summary:
                    chunks.append(f"[tool {summary}]")
        text = " ".join(chunks).strip()
        if text:
            lines.append(f"{role}: {text}")
    body = "\n".join(lines).strip() or "(empty transcript)"
    return f"{HANDOFF_COMPOSER_PROMPT}{body[:40_000]}"


def parse_handoff_response(text: str) -> dict[str, Any]:
    """Parse Composer handoff JSON; returns a normalized dict with required keys."""
    raw = str(text or "").strip()
    if not raw:
        return _empty_handoff()
    match = _HANDOFF_JSON_RE.search(raw)
    if not match:
        return _empty_handoff(summary=raw[:2000])
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _empty_handoff(summary=raw[:2000])
    if not isinstance(payload, dict):
        return _empty_handoff(summary=raw[:2000])
    goal = str(payload.get("goal") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    files = _string_list(payload.get("files"))
    next_steps = _string_list(payload.get("next_steps"))
    return {
        "goal": goal or "Continue the IDE conversation in Panda.",
        "files": files,
        "next_steps": next_steps,
        "summary": summary or goal or "Handoff from IDE session.",
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text[:500])
    return result[:20]


def _empty_handoff(*, summary: str = "") -> dict[str, Any]:
    return {
        "goal": "Continue the IDE conversation in Panda.",
        "files": [],
        "next_steps": [],
        "summary": summary or "Handoff from IDE session (no structured summary parsed).",
    }


def format_handoff_system_message(handoff: dict[str, Any]) -> str:
    goal = str(handoff.get("goal") or "").strip()
    summary = str(handoff.get("summary") or "").strip()
    files = handoff.get("files") if isinstance(handoff.get("files"), list) else []
    next_steps = handoff.get("next_steps") if isinstance(handoff.get("next_steps"), list) else []
    files_text = "\n".join(f"- {path}" for path in files) if files else "- (none listed)"
    steps_text = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(next_steps)) if next_steps else "1. Continue from the transcript tail below."
    return (
        "PANDA FORK HANDOFF (from Cursor IDE — read-only source)\n\n"
        f"Goal: {goal}\n\n"
        f"Summary: {summary}\n\n"
        f"Files in play:\n{files_text}\n\n"
        f"Suggested next steps:\n{steps_text}\n"
    )


def build_fork_pending_context(
    handoff: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    tail_limit: int = FORK_TAIL_MESSAGE_LIMIT,
) -> list[dict[str, Any]]:
    """pending_context stored on fork: system handoff + last N transcript messages."""
    system_row = {
        "role": "assistant",
        "blocks": [{"type": "text", "text": format_handoff_system_message(handoff)}],
    }
    return [system_row, *tail_messages(messages, tail_limit)]
