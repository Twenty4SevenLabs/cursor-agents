"""JOS tool adapter: probe the MAD-960 sidecar over loopback."""

import json
import os
import sys
import urllib.request
from pathlib import Path

# cursor_agents__list returns the local agent registry
# cursor_agents__create starts a Composer 2.5 local agent
# cursor_agents__send posts a follow-up to a forked or Panda-owned agent
# cursor_agents__cancel stops an in-flight local run
# cursor_agents__fork copies an IDE transcript into a new local agent

port = ""


def _token() -> str:
    path = Path(os.environ.get("HOME", "/tmp")) / "state" / "token"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _request(method: str, path: str, body=None):
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode())


def _get(path: str):
    return _request("GET", path)


def _post(path: str, body=None):
    return _request("POST", path, body)


def dispatch(name: str, args: dict):
    if args.get("probe") is True:
        health = _get("/health")
        if not isinstance(health, dict):
            raise SystemExit("sidecar_health_invalid")
        if name == "cursor_agents__list":
            return {"ok": True, "count": 0}
        return {"ok": True}

    if name == "cursor_agents__list":
        payload = _get("/agents")
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            items = []
        return {"ok": True, "count": len(items)}
    if name == "cursor_agents__create":
        _post("/agents", {"prompt": args.get("prompt"), "title": args.get("title")})
        return {"ok": True}
    if name == "cursor_agents__send":
        _post(f"/agents/{args['agent_id']}/send", {"prompt": args.get("prompt")})
        return {"ok": True}
    if name == "cursor_agents__cancel":
        _post(f"/agents/{args['agent_id']}/runs/{args['run_id']}/cancel")
        return {"ok": True}
    if name == "cursor_agents__fork":
        _post(f"/agents/{args['agent_id']}/fork")
        return {"ok": True}
    raise SystemExit("unknown_operation")


if __name__ == "__main__":
    config = json.load(open("/run/pandamonium/config.json"))
    port = str(config["PANDAMONIUM_PORT"])
    name = sys.argv[1]
    args = json.load(sys.stdin)
    print(json.dumps(dispatch(name, args)))
    raise SystemExit(0)
