#!/usr/bin/env python3
"""Sign in to Firefox Accounts and write signedInUser.json to the Zen Browser profile.

Reads credentials from environment variables:
  FXA_EMAIL     - Firefox Accounts email
  FXA_PASSWORD  - Firefox Accounts password
  FXA_TOTP      - Current TOTP code (6 digits)

Optionally:
  ZEN_PROFILE_DIR - Override the Zen profile directory (default: auto-detected)

Idempotent: exits 0 without changes if signedInUser.json already exists and is verified.
"""

import sys
import os
import json
import configparser

ZEN_BASE = os.path.expanduser("~/.var/app/app.zen_browser.zen/.zen")


def find_default_profile():
    ini_path = os.path.join(ZEN_BASE, "profiles.ini")
    config = configparser.ConfigParser()
    config.read(ini_path)

    # Prefer the Install section's Default — most reliable across Zen versions
    for section in config.sections():
        if section.startswith("Install"):
            path = config[section].get("Default")
            if path:
                return os.path.join(ZEN_BASE, path)

    # Fall back to the profile flagged Default=1
    for section in config.sections():
        if section.startswith("Profile") and config[section].get("Default") == "1":
            path = config[section].get("Path", "")
            is_relative = config[section].get("IsRelative", "1") == "1"
            return os.path.join(ZEN_BASE, path) if is_relative else path

    raise RuntimeError(f"Could not find default Zen profile in {ini_path}")


def main():
    email = os.environ.get("FXA_EMAIL")
    password = os.environ.get("FXA_PASSWORD")
    totp_code = os.environ.get("FXA_TOTP", "").strip()
    profile_dir = os.environ.get("ZEN_PROFILE_DIR") or find_default_profile()

    if not all([email, password, totp_code]):
        print("ERROR: FXA_EMAIL, FXA_PASSWORD, and FXA_TOTP must be set", file=sys.stderr)
        sys.exit(2)

    signed_in_path = os.path.join(profile_dir, "signedInUser.json")

    # Idempotent: skip if already signed in and verified
    if os.path.exists(signed_in_path):
        try:
            with open(signed_in_path) as f:
                data = json.load(f)
            if data.get("accountData", {}).get("verified"):
                existing_email = data["accountData"].get("email", "unknown")
                print(f"Already signed in as {existing_email} — skipping", file=sys.stderr)
                sys.exit(0)
        except (json.JSONDecodeError, KeyError):
            pass  # File is malformed — overwrite it

    try:
        import fxa.core
    except ImportError:
        print("ERROR: PyFxA not installed. Run: pip3 install --user fxa", file=sys.stderr)
        sys.exit(3)

    print(f"Signing in to Firefox Accounts as {email}...", file=sys.stderr)
    client = fxa.core.Client("https://api.accounts.firefox.com")
    session = client.login(email, password)

    success = session.totp_verify(totp_code)
    if not success:
        print("ERROR: TOTP verification failed — check your code and try again", file=sys.stderr)
        sys.exit(1)

    # session.token may be bytes or hex string depending on PyFxA version
    token = session.token
    if isinstance(token, bytes):
        token = token.hex()

    account_data = {
        "email": email,
        "sessionToken": token,
        "uid": session.uid,
        "verified": True,
    }

    os.makedirs(profile_dir, exist_ok=True)
    with open(signed_in_path, "w") as f:
        json.dump({"version": 1, "accountData": account_data}, f)

    print(f"Wrote signedInUser.json for {email} — restart Zen to begin syncing")


if __name__ == "__main__":
    main()
