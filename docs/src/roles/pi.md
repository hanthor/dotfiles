# pi

**Tags:** `dotfiles`, `pi`  
**Secrets needed:** No (API keys deployed from Bitwarden by shell role)  
**Runs on:** All machines

Deploys the [PI Coding Agent](https://github.com/earendil-works/pi-coding-agent) configuration and extensions.

## What It Does

1. Creates `~/.pi/agent/` directory structure
2. Deploys `settings.json` with provider, model, and package configuration
3. Installs PI extensions via npm:
   - `pi-subagents` — subagent orchestration
   - `grill-me` — interactive planning interviews
   - `goal-x` — goal tracking system
   - `import-claude-history` — Claude Code history import
   - `rpiv-todo` — task list integration
   - `pi-beads` — token/session tracking
4. Deploys Forgejo MCP bridge extension
5. Deploys the personal skill collection to `~/.pi/agent/skills/james/` and
   symlinks each skill into `~/.claude/skills/` so Claude Code sees the same
   set (single source of truth on disk)

## Skills

Everything under `roles/pi/files/skills/` is deployed as the `james`
collection — adding a skill is just adding a directory, no task edits. Vendored
third-party collections (e.g. `mattpocock`) are installed by their own setup
skills and deliberately **not** tracked here.

Notable: `tunaos-hive-checkin` (health-check the Hive), `tunaos-contributor-fleet`,
`driving-pi`, `tmux-agent-fleet`, `gnome-gui`, `tavily-search`.

`tavily-search` reads `$TAVILY_API_KEY` rather than hardcoding a key — this
repo is public. The `shell_ai` role writes it to `~/.config/shell/secrets.sh`
from the Bitwarden item `tavily-api-key`.

## Notes

- API keys (`auth.json`) are deployed by the `shell` role from Bitwarden
- Extensions are installed to `~/.pi/agent/npm/` via npm
