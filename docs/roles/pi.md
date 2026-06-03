# pi

**Tags:** `dotfiles`, `pi`  
**Secrets needed:** No (API keys deployed from Bitwarden by shell role)  
**Runs on:** All machines

Deploys the PI Coding Agent configuration and extensions.

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

## Notes

- API keys (`auth.json`) are deployed by the `shell` role from Bitwarden
- Extensions are installed to `~/.pi/agent/npm/` via npm
