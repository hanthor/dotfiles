# shell_ai

**Unit:** `shell-ai` (`units/shell-ai.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `shell`, `ai`, `secrets`  
**Secrets needed:** Yes (`deepseek-api-key`, `forgejo`, `tavily-api-key`, `meta-api-key`, `kiro-api-key`)  
**Runs on:** All machines

Writes API credentials for the AI coding tools and shell.

## What It Does

With an unlocked vault (`bw_session`; never prompts):

- `bw get password deepseek-api-key` → `DEEPSEEK_API_KEY`
- `bw get notes forgejo` (the `API Token:` line) → `FORGEJO_TOKEN`
- `bw get password tavily-api-key` → `TAVILY_API_KEY`
- `bw get notes meta-api-key` → `META_API_KEY`
- `bw get notes kiro-api-key` → `KIRO_API_KEY`

The values present are written (shell-specific single-quote escaping, 0600, via temp file + `mv`) to `~/.config/shell/secrets.sh` (bash/zsh; also exports `OMP_KIRO_CONFIG`) and `~/.config/fish/conf.d/secrets.fish` (fish; attempts a runtime Kiro key refresh from `/tmp/bw_session`). Fish keeps the deployed key when the refresh fails, is empty, or is not a string; the session is passed through the environment rather than command arguments.

## Output lines

- `SKIPPED: vault locked or --no-secrets` — files left untouched
- `warn: no secrets found in Bitwarden` — files left untouched

## Notes

- Not a chezmoi template on purpose: `bitwarden` template functions abort the whole template when one item is missing, while the unit writes whatever secrets exist.
- A failed Bitwarden read is ignored even if it produced partial output; other successfully read items are still deployed.
- A locked vault leaves any previously written secret files untouched — nothing is overwritten with empty values
- `TAVILY_API_KEY` is read by the `tavily-search` skill deployed by the [`omp`](omp.md) unit
