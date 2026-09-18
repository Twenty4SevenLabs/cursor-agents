# Ship Cursor Agents to the community

This is the public install package. Core Pandamonium chrome host stays in the Pandamonium `cursor-bridge` branch. This repo only has files needed to install and operate the plugin.

## What goes in the GitHub repo

- `jarvis-extension.json` (JOS manifest)
- `.pandamonium/` sidecar, UI, adapter, SETUP.md, integration.json
- `README.md`, `FIRST_RUN.md`, `LICENSE`
- `scripts/pack-install.sh`

Do not put `.env`, API keys, host `~/.cursor`, or Pandamonium core files here.

## Pack

```bash
./scripts/pack-install.sh
```

Attach `dist/cursor-agents-0.1.0.zip` to a GitHub Release.

## Remaining finalize checklist (lab)

1. Install the zip on a Panda 1.0.70+ build and complete the five-step coach.
2. Confirm Ready rail, overlay send, IDE 409 fork.
3. Wave 3: delete in-tree `#rail-cursor-bridge` only after the lab plugin is Ready.
4. Wave 4: MAD-962 sign and catalog publish (needs signing keys; not a silent publish).
5. Merge Pandamonium `cursor-bridge` → `main` only after `git diff main...cursor-bridge --stat` has no leftover bridge-only core files.
