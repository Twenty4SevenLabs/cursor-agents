# Cursor Agents setup

This plugin runs Composer 2.5 **local** agents inside a MAD-960 sidecar.

1. Install **Cursor Agents** from Pandamonium Plugins.
2. The first-run walkthrough points at Plugins and asks for your Cursor User API key.
3. Get the key at [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations) (Dashboard → Integrations). Copy the User API Key. This is not your password.
4. Paste it into `CURSOR_API_KEY` on Plugins setup, then Save setup.
5. When the plugin is Ready, the Agents rail appears. Click it to list agents and open the overlay chat.
6. Optional: set `IDE_TRANSCRIPTS_ROOT` to a read-only transcript tree if you want IDE fork.
7. Disable the plugin to hide chrome. Core Pandamonium has no Agents button of its own after cutover.

Never put the key in git, zips, or issue comments. The sidecar HOME is the plugin runtime, not `/home/labsadmin` and not a writable `~/.cursor`.
