#!/usr/bin/env python3
"""Sign in to Firefox Accounts and write signedInUser.json to a browser profile.

Reads credentials from environment variables:
  FXA_EMAIL     - Firefox Accounts email
  FXA_PASSWORD  - Firefox Accounts password
  FXA_TOTP      - Current TOTP code (6 digits)

Browser selection (optional):
  BROWSER_TYPE  - "zen" (default), "firefox", or "firefox-flatpak"
  PROFILE_DIR   - Override profile directory directly (skips auto-detection)

Idempotent: exits 0 without changes if signedInUser.json already exists and is verified.
"""

import sys
import os
import json
import configparser

BROWSER_BASES = {
    "zen": os.path.expanduser("~/.var/app/app.zen_browser.zen/.zen"),
    "firefox-flatpak": os.path.expanduser("~/.var/app/org.mozilla.firefox/.mozilla/firefox"),
    "firefox": os.path.expanduser("~/.mozilla/firefox"),
}


def find_default_profile(base_dir):
    ini_path = os.path.join(base_dir, "profiles.ini")
    config = configparser.ConfigParser()
    config.read(ini_path)

    # Prefer the Install section's Default — most reliable across browser versions
    for section in config.sections():
        if section.startswith("Install"):
            path = config[section].get("Default")
            if path:
                return os.path.join(base_dir, path)

    # Fall back to the profile flagged Default=1
    for section in config.sections():
        if section.startswith("Profile") and config[section].get("Default") == "1":
            path = config[section].get("Path", "")
            is_relative = config[section].get("IsRelative", "1") == "1"
            return os.path.join(base_dir, path) if is_relative else path

    raise RuntimeError(f"Could not find default profile in {ini_path}")


def resolve_profile_dir():
    # Explicit override wins
    profile_dir = os.environ.get("PROFILE_DIR") or os.environ.get("ZEN_PROFILE_DIR")
    if profile_dir:
        return profile_dir

    browser = os.environ.get("BROWSER_TYPE", "zen").lower()

    if browser == "firefox":
        # Try Flatpak first, fall back to native
        for candidate in [BROWSER_BASES["firefox-flatpak"], BROWSER_BASES["firefox"]]:
            if os.path.exists(os.path.join(candidate, "profiles.ini")):
                return find_default_profile(candidate)
        raise RuntimeError("Firefox profiles.ini not found (tried Flatpak and native paths)")

    base = BROWSER_BASES.get(browser)
    if base is None:
        raise RuntimeError(f"Unknown BROWSER_TYPE '{browser}'. Use: zen, firefox, firefox-flatpak")

    return find_default_profile(base)


def main():
    email = os.environ.get("FXA_EMAIL")
    password = os.environ.get("FXA_PASSWORD")
    totp_code = os.environ.get("FXA_TOTP", "").strip()

    if not all([email, password, totp_code]):
        print("ERROR: FXA_EMAIL, FXA_PASSWORD, and FXA_TOTP must be set", file=sys.stderr)
        sys.exit(2)

    try:
        profile_dir = resolve_profile_dir()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(4)

    signed_in_path = os.path.join(profile_dir, "signedInUser.json")

    if os.path.exists(signed_in_path):
        try:
            with open(signed_in_path) as f:
                data = json.load(f)
            if data.get("accountData", {}).get("verified"):
                existing_email = data["accountData"].get("email", "unknown")
                print(f"Already signed in as {existing_email} — skipping", file=sys.stderr)
                sys.exit(0)
        except (json.JSONDecodeError, KeyError):
            pass  # Malformed — overwrite it

    try:
        import fxa.core
    except ImportError:
        print("ERROR: PyFxA not installed. Run: pip3 install PyFxA", file=sys.stderr)
        sys.exit(3)

    browser = os.environ.get("BROWSER_TYPE", "zen")
    print(f"Signing in to Firefox Accounts as {email} (browser: {browser})...", file=sys.stderr)

    client = fxa.core.Client("https://api.accounts.firefox.com")
    session = client.login(email, password)

    if not session.totp_verify(totp_code):
        print("ERROR: TOTP verification failed — check your code and try again", file=sys.stderr)
        sys.exit(1)

    token = session.token
    if isinstance(token, bytes):
        token = token.hex()

    os.makedirs(profile_dir, exist_ok=True)
    with open(signed_in_path, "w") as f:
        json.dump({
            "version": 1,
            "accountData": {
                "email": email,
                "sessionToken": token,
                "uid": session.uid,
                "verified": True,
            },
        }, f)

    print(f"Wrote signedInUser.json for {email} — restart the browser to begin syncing")


if __name__ == "__main__":
    main()
