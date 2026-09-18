"""JOS tool adapter: probe the MAD-960 sidecar over loopback."""

import json
import sys
import urllib.request

# cursor_agents__list returns the local agent registry
# cursor_agents__create starts a Composer 2.5 local agent
# cursor_agents__send posts a follow-up to a forked or Panda-owned agent
# cursor_agents__cancel stops an in-flight local run
# cursor_agents__fork copies an IDE transcript into a new local agent

config = json.load(open("/run/pandamonium/config.json"))
port = str(config["PANDAMONIUM_PORT"])
name = sys.argv[1]
args = json.load(sys.stdin)


def _get(path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read().decode())


if args.get("probe") is True:
    health = _get("/health")
    if not isinstance(health, dict):
        raise SystemExit("sidecar_health_invalid")
    if name == "cursor_agents__list":
        print(json.dumps({"ok": True, "count": 0}))
    else:
        print(json.dumps({"ok": True}))
    raise SystemExit(0)

raise SystemExit("expected probe true for packaged operation checks")
