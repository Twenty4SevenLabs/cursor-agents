"""Minimal atomic JSON writer for the MAD-960 sidecar."""

from __future__ import annotations

import json
import os
from pathlib import Path


def atomic_write_json(path: str, payload: object, indent: int | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
    os.replace(tmp, target)
