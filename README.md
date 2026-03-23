# dotfiles

Personal dotfiles for James Reilly, managed with [chezmoi](https://chezmoi.io).

## Setup

> Requirements: `curl`, `sudo` access, Bitwarden account with secrets pre-loaded (see below)

```bash
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply hanthor
```

You'll be prompted for:
1. **Machine name** — one of: `himachal`, `karnataka`, `dilli`, `kanpur`, `goa`, `bihar`, `matrix`, `lkofoss`
2. **Bitwarden login** — email + master password + phone approval (first time only per machine)

Setup takes ~5 minutes. After it completes:

### Desktop machines only (Zen Browser)

3. Open Zen Browser → hamburger menu → **Sign in to Sync** → approve on phone
4. Click the **Bitwarden extension** → enter master password

## Remote Setup (via Tailscale)

```bash
ssh -t james@<machinename> 'sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply hanthor'
```

## Updating

```bash
chezmoi update         # pull latest + re-apply
chezmoi diff           # preview changes before applying
chezmoi apply --force  # force re-run all run_once_ scripts (e.g. after key rotation)
```

## Key Rotation

`run_once_` scripts only re-run when their content changes. To force re-run after rotating a key, update the rotation comment at the top of the relevant script and commit:

```bash
# rotated 2026-04-01
```

## Bitwarden Vault Setup

Before first run, create these items in Bitwarden:

| Item Name | Type | Fields |
|---|---|---|
| `himachal` | Secure Note | `private_key`, `public_key` |
| `karnataka` | Secure Note | `private_key`, `public_key` |
| `dilli` | Secure Note | `private_key`, `public_key` |
| `kanpur` | Secure Note | `private_key`, `public_key` |
| `goa` | Secure Note | `private_key`, `public_key` |
| `bihar` | Secure Note | `private_key`, `public_key` |
| `matrix` | Secure Note | `private_key`, `public_key` |
| `lkofoss` | Secure Note | `private_key`, `public_key` |
| `github-token` | Login | Password = GitHub PAT (scopes: `repo`, `read:org`, `workflow`, `admin:public_key`) |
| `tailscale-authkey` | Login | Password = Tailscale reusable auth key |

## Security Notes

- The repo is public — no secrets are stored in it
- All secrets are fetched from Bitwarden at setup time
- The Tailscale auth key is shared across machines — rotate it after all machines are enrolled
