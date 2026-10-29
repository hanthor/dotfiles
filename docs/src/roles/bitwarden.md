# Bitwarden session resolution

Bitwarden is handled by `scripts/bw-resolve.sh` and the apply recipes, not a fleet unit or a host fact. `just apply` resolves a local session, validates it and runs `bw sync` with a 15-second timeout before running units. If resolution or sync fails, it continues with `--no-secrets`. `just apply-tags` does this for secret-bearing selections; on failure it still runs the selection without secrets but returns an error. `just apply-nosecrets` does not unlock the vault.

Unit helpers use a valid `BW_SESSION` or `/tmp/bw_session` noninteractively, and honor `UNITS_NO_SECRETS=1`. Units handle missing sessions and items individually, often printing `SKIPPED` or `PARTIAL` and preserving existing secret data. A successful apply alone does not establish that all secrets were refreshed.

For remote applies, `scripts/bw-resolve.sh remote <host>` attempts to log in and unlock Bitwarden on the target, returning a target-side session. The apply recipe forwards it using SSH `SendEnv=BW_SESSION`; the target must accept it. Tokens are host-specific. See [Secrets with Bitwarden](../bitwarden.md) for vault items and setup.
