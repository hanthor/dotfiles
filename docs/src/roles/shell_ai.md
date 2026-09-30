# shell_ai

**Tags:** `dotfiles`, `shell`, `ai`, `secrets`  
**Secrets needed:** Yes (`deepseek-api-key`, `forgejo`, `tavily-api-key`)  
**Runs on:** All machines

Deploys API credentials for the AI coding tools and shell.

## What It Does

1. Creates `~/.pi/agent/` and deploys `models.json` for the pi coding agent
2. When `bw_unlocked`:
   - `bw get password deepseek-api-key` → `~/.pi/agent/auth.json` (0600)
   - `bw get notes forgejo` (the `API Token:` line) → `FORGEJO_TOKEN`
   - `bw get password tavily-api-key` → `TAVILY_API_KEY`
   - Writes the two exports to `~/.config/shell/secrets.sh` (bash/zsh) and
     `~/.config/fish/conf.d/secrets.fish` (fish), both 0600
3. Warns if `deepseek-api-key` is missing

## Notes

- A locked vault leaves any previously written secret files untouched — nothing is overwritten with empty values
- `TAVILY_API_KEY` is read by the `tavily-search` skill deployed by the [`pi`](pi.md) role
