"""Guardrails: IDE transcript agent IDs must never hit SDK resume_agent."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class IdeAgentResumeForbidden(RuntimeError):
    """Raised when code would call SDK resume on an IDE-owned transcript agent id."""

    code = "ide_agent_resume_forbidden"


def ide_projects_root() -> Path:
    override = str(os.getenv("IDE_TRANSCRIPTS_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path("/nonexistent-ide-transcripts")


def is_ide_transcript_agent_id(agent_id: str, projects_root: Path | None = None) -> bool:
    candidate = str(agent_id or "").strip()
    if not candidate or not UUID_RE.fullmatch(candidate):
        return False
    root = (projects_root or ide_projects_root()).resolve()
    if not root.is_dir():
        return False
    pattern = f"**/agent-transcripts/**/{candidate}.jsonl"
    return any(root.glob(pattern))


def resolve_sdk_resume_id(agent_id: str, row: dict[str, Any] | None = None) -> str:
    candidate = str(agent_id or "").strip()
    if not candidate:
        raise IdeAgentResumeForbidden("empty_agent_id")
    registry = row if isinstance(row, dict) else {}
    sdk_id = str(registry.get("sdk_agent_id") or "").strip()
    if is_ide_transcript_agent_id(candidate):
        if registry.get("forked") and sdk_id:
            return sdk_id
        raise IdeAgentResumeForbidden(f"ide_transcript_id:{candidate}")
    if sdk_id and registry.get("forked"):
        return sdk_id
    return candidate
