# Cursor Agents

Pandamonium plugin for Composer 2.5 local agents. It is **not** a Cursor IDE marketplace plugin.

This repo is the install package. Pandamonium 1.0.70 or newer is required (nameless chrome host plus first-run coach).

## What it is (ELI5)

Pandamonium is the app. This plugin is a Lego brick you snap into Plugins.

1. You install the brick.
2. You paste your Cursor API key (like a hall pass).
3. A new Agents button appears on the left.
4. That button opens a list and a big chat window that talks to Composer 2.5.

The key lives in the plugin vault. It does not go in chat or git.

## Install on Pandamonium

### Option A: Plugins marketplace (when MAD-962 catalog is live)

1. Open Pandamonium.
2. Click **Plugins** (plus on the Plugins section).
3. Find **Cursor Agents** and install it.
4. Follow the on-screen walkthrough (five steps with arrows).

### Option B: zip / source install (community pack)

1. Download `cursor-agents-0.1.0.zip` from [Releases](https://github.com/Twenty4SevenLabs/cursor-agents/releases) or clone this repo.
2. In Pandamonium: Plugins → Add → point at this git URL or upload the zip, depending on your Panda build.
   - Git URL: `https://github.com/Twenty4SevenLabs/cursor-agents.git`
3. Enable the plugin. The first-run coach starts even before the key is saved.

## First-run walkthrough

The coach sits on top of Pandamonium. It does not live inside Cursor.

| Step | What you will see | What you do |
|------|-------------------|-------------|
| 1 | Arrow at Plugins | Read the welcome. Click Next. |
| 2 | Link to Cursor dashboard | Open Integrations, create a User API Key, copy it. |
| 3 | Arrow at Plugins setup | Paste `CURSOR_API_KEY`, Save setup. |
| 4 | Arrow at the left rail | After Ready, click Agents. |
| 5 | Overlay chat | Type a prompt. Send. Wait for Composer 2.5. |

Where the key lives in Cursor: **cursor.com → Dashboard → Integrations**  
Direct link: https://cursor.com/dashboard/integrations

Skip is available. The coach does not show again after Skip or Done (same browser).

## Operate

- **Rail button:** open the agent list (sidebar) and the full-screen overlay.
- **Create / send:** local Composer 2.5 agents only. Fast variants are rejected.
- **IDE chats:** read-only. Continue in Panda **forks**. Resume of an IDE uuid returns 409.
- **Canvases:** plugin-owned HOME only.

## Pack a zip

```bash
./scripts/pack-install.sh
```

Output: `dist/cursor-agents-0.1.0.zip`

## Requirements

- Pandamonium **1.0.70** chrome host
- Linux bubblewrap sidecar (MAD-960)
- Cursor subscription User API key

## License

AGPL-3.0. See `LICENSE`.
