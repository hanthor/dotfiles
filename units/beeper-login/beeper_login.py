#!/usr/bin/env python3
"""Sign Beeper Desktop in from the local Desktop API and unlock encryption.

Beeper Desktop only offers email-code sign-in (`signInMethods: ["email"]`), so
the one-time code is read from an IMAP mailbox. Credentials come from the
environment (never argv): BEEPER_EMAIL, BEEPER_IMAP_HOST, BEEPER_IMAP_USER,
BEEPER_IMAP_PASSWORD, BEEPER_RECOVERY_KEY. Exit 0 = ready, 3 = already signed in
elsewhere state we cannot repair, 1 = failure. Secrets are never printed.
"""
import email
import imaplib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BEEPER_API", "http://127.0.0.1:23373")
# Pre-login calls take a placeholder bearer, as Beeper's own CLI does.
PUBLIC_TOKEN = "setup-login-public-client"
CODE_RE = re.compile(r"\b(\d{6})\b")


def api(method, path, body=None, token=PUBLIC_TOKEN):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise SystemExit(f"{method} {path} failed: HTTP {e.code} {detail}")


def wait_for_api(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return api("GET", "/v1/app/setup")
        except SystemExit:
            raise
        except Exception:
            time.sleep(2)
    raise SystemExit("Beeper Desktop API did not come up")


def mailbox():
    m = imaplib.IMAP4_SSL(os.environ["BEEPER_IMAP_HOST"])
    m.login(os.environ["BEEPER_IMAP_USER"], os.environ["BEEPER_IMAP_PASSWORD"])
    m.select("INBOX", readonly=True)
    return m


def newest_uid(m):
    _, data = m.uid("search", None, "FROM", '"beeper"')
    uids = data[0].split()
    return int(uids[-1]) if uids else 0


def extract_code(raw):
    msg = email.message_from_bytes(raw)
    parts = [msg.get("Subject", "")]
    for p in msg.walk():
        if p.get_content_type() in ("text/plain", "text/html"):
            payload = p.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(p.get_content_charset() or "utf-8", "replace"))
    m = CODE_RE.search("\n".join(parts))
    return m.group(1) if m else None


def wait_for_code(m, after_uid, timeout):
    """Newest Beeper message with a UID above after_uid that holds a 6-digit code."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        m.noop()
        _, data = m.uid("search", None, "FROM", '"beeper"')
        for uid in reversed([int(u) for u in data[0].split()]):
            if uid <= after_uid:
                break
            _, msg = m.uid("fetch", str(uid), "(BODY.PEEK[])")
            code = extract_code(msg[0][1])
            if code:
                return code
        time.sleep(3)
    raise SystemExit("no Beeper sign-in code arrived in the mailbox")


def main():
    state = wait_for_api(int(os.environ.get("BEEPER_API_WAIT", "90")))["state"]
    if state == "ready":
        print("ready: already signed in")
        return 0
    if state != "needs-login":
        # Sign-in returns the session token exactly once; without it the
        # recovery-key call cannot be authorised. Sign out in the app to retry.
        print(f"state {state}: signed in but not unlocked; sign out in Beeper and re-run", file=sys.stderr)
        return 3

    m = mailbox()
    baseline = newest_uid(m)
    start = api("POST", "/v1/app/setup/start")
    if "email" not in start.get("signInMethods", []):
        raise SystemExit(f"email sign-in not offered: {start.get('signInMethods')}")
    rid = start["setupRequestID"]
    api("POST", "/v1/app/setup/email", {"setupRequestID": rid, "email": os.environ["BEEPER_EMAIL"]})
    code = wait_for_code(m, baseline, int(os.environ.get("BEEPER_CODE_WAIT", "120")))
    m.logout()

    done = api("POST", "/v1/app/setup/response", {"setupRequestID": rid, "response": code})
    token = (done.get("matrix") or {}).get("accessToken")
    if not token:
        raise SystemExit("sign-in did not return a token (account may not exist yet)")

    session = done["session"]
    if session["state"] != "ready":
        session = api("POST", "/v1/app/setup/verification/recovery-key",
                      {"recoveryKey": os.environ["BEEPER_RECOVERY_KEY"]}, token=token)["session"]
    print(f"state: {session['state']}")
    # needs-first-sync is the app catching up on chats, not a failure.
    return 0 if session["state"] in ("ready", "needs-first-sync") else 1


if __name__ == "__main__":
    sys.exit(main())
