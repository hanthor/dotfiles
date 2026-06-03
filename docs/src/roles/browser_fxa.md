# browser_fxa

**Tags:** `desktop`, `browser`, `browser_fxa`  
**Secrets needed:** Yes (Firefox Account credentials from Bitwarden)  
**Runs on:** Desktop group only

Automates Firefox Account sign-in for Zen Browser (and optionally Firefox).

## What It Does

1. Fetches `accounts.firefox.com` credentials + TOTP from Bitwarden
2. Writes `signedInUser.json` to the browser profile directory
3. This pre-authenticates the browser with Firefox Sync

## Configuration

```yaml
# group_vars/all.yml
fxa_bw_item: "accounts.firefox.com"
fxa_bw_username: "jreilly1821@gmail.com"
fxa_browsers:
  - zen
  - firefox
  - firefox-flatpak
```

## Notes

- This only enables FxA sign-in, not the full Sync key bundle
- Opening the browser once after deployment may still be needed to complete Sync
- If credentials are unavailable, the task fails silently — manual sign-in works fine
