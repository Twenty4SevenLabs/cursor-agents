"""Subscription-only guardrails for the Cursor bridge.

Fail closed on cloud runtime, non-subscription REST paths, and any model other
than composer-2.5.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

REQUIRED_MODEL = "composer-2.5"
FAST_VARIANT_PATTERN = re.compile(r"fast", re.IGNORECASE)
BLOCKED_HOSTS = ("api.cursor.com", "api2.cursor.sh")
BLOCKED_PATH_PREFIXES = ("/v1/agents", "/v0/agents")
BLOCKED_CLI_TOKENS = (
    "worker start",
    "worker controller",
    "--cloud",
    "cloud-agent",
)


def _text_implies_fast(text: object) -> bool:
    return bool(FAST_VARIANT_PATTERN.search(str(text or "")))


def _mapping_implies_fast(mapping: Mapping[str, Any]) -> bool:
    for key, value in mapping.items():
        if _text_implies_fast(key):
            return True
        if _text_implies_fast(value):
            return True
    return False


def _model_implies_fast(model: Mapping[str, Any]) -> bool:
    params = model.get("params")
    if not isinstance(params, list):
        return False
    for param in params:
        if isinstance(param, Mapping) and _mapping_implies_fast(param):
            return True
    return False


class SubscriptionGuardError(RuntimeError):
    """Raised when a request would bypass subscription-only policy."""

    code = "subscription_guard_violation"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def assert_model(model: object) -> str:
    model_id = ""
    if isinstance(model, str):
        model_id = model.strip()
    elif isinstance(model, Mapping):
        raw = model.get("id") or model.get("model")
        model_id = str(raw or "").strip()
        if _model_implies_fast(model):
            raise SubscriptionGuardError("composer_fast_mode_not_allowed")
    if _text_implies_fast(model_id):
        raise SubscriptionGuardError("composer_fast_mode_not_allowed")
    if model_id != REQUIRED_MODEL:
        raise SubscriptionGuardError(f"model_must_be_{REQUIRED_MODEL}")
    return model_id


def assert_local_runtime(options: Mapping[str, Any]) -> dict[str, Any]:
    if any(key in options for key in ("cloud", "pool", "machine", "env")):
        raise SubscriptionGuardError("cloud_runtime_not_allowed")
    local = options.get("local")
    if not isinstance(local, Mapping):
        raise SubscriptionGuardError("local_runtime_required")
    cwd = str(local.get("cwd") or "").strip()
    if not cwd:
        raise SubscriptionGuardError("local_cwd_required")
    return dict(local)


def assert_agent_options(options: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(options)
    model = payload.get("model")
    assert_model(model)
    if isinstance(model, Mapping):
        for key, value in model.items():
            if key != "params" and (_text_implies_fast(key) or _text_implies_fast(value)):
                raise SubscriptionGuardError("composer_fast_mode_not_allowed")
    assert_local_runtime(payload)
    if payload.get("autoCreatePR") or payload.get("auto_create_pr"):
        raise SubscriptionGuardError("cloud_pr_automation_not_allowed")
    repos = payload.get("repos") or payload.get("cloud")
    if repos:
        raise SubscriptionGuardError("cloud_repos_not_allowed")
    return payload


def assert_no_cloud_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in BLOCKED_HOSTS and any(path.startswith(prefix) for prefix in BLOCKED_PATH_PREFIXES):
        raise SubscriptionGuardError("cloud_rest_api_not_allowed")


def assert_cli_command(command: str | list[str]) -> None:
    text = " ".join(command) if isinstance(command, list) else str(command or "")
    lowered = text.lower()
    for token in BLOCKED_CLI_TOKENS:
        if token in lowered:
            raise SubscriptionGuardError(f"blocked_cli_pattern:{token.replace(' ', '_')}")


def _model_id(row: object) -> str:
    if isinstance(row, Mapping):
        return str(row.get("id") or row.get("model") or "").strip()
    model_id = getattr(row, "id", None)
    if model_id:
        return str(model_id).strip()
    return str(row or "").strip()


def model_catalog_allows_subscription(models: list[Mapping[str, Any]] | list[object] | None) -> bool:
    if not models:
        return False
    for row in models:
        if _model_id(row) == REQUIRED_MODEL:
            return True
    return False


async def validate_startup_models(client: Any, api_key: str) -> None:
    """Ensure composer-2.5 is available for this subscription key."""
    models = await client.models.list(api_key=api_key)
    items: list[object] = []
    if hasattr(models, "items"):
        items = list(models.items or [])
    elif isinstance(models, list):
        items = models
    elif isinstance(models, Mapping):
        raw = models.get("items") or models.get("models")
        if isinstance(raw, list):
            items = raw
    if not model_catalog_allows_subscription(items):
        raise SubscriptionGuardError("composer_2_5_not_available")


def sanitize_title(value: object, fallback: str = "Cursor agent") -> str:
    text = " ".join(str(value or fallback).split())
    if not text:
        text = fallback
    return text[:120]


def title_from_prompt(prompt: str) -> str:
    words = sanitize_title(prompt, "New Cursor agent").split()
    if len(words) <= 8:
        return " ".join(words)
    return " ".join(words[:8]) + "…"
