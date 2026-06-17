#!/usr/bin/env python3
"""Ansible module: bw_credential — fetch a single field from a Bitwarden item.

Graceful degradation: never fails the play. Returns {found, value, reason}
so callers gate with `when: result.found`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


def run_bw(args: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    """Run a `bw` command. Returns (rc, stdout, stderr)."""
    env = os.environ.copy()
    env.setdefault("PATH", "/home/linuxbrew/.linuxbrew/bin:" + env.get("PATH", ""))
    p = subprocess.run(
        ["bw", *args],
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def bw_status() -> str:
    """Return 'unlocked', 'locked', 'unauthenticated', or 'missing'."""
    rc, stdout, _ = run_bw(["status"])
    if rc != 0:
        if "command not found" in stdout.lower() or "No such file" in stdout:
            return "missing"
        return "unknown"
    try:
        return json.loads(stdout).get("status", "unknown")
    except (json.JSONDecodeError, AttributeError):
        return "unknown"


def bw_get_item(name: str) -> dict[str, Any] | None:
    """Fetch a single item by exact name. Returns parsed JSON or None."""
    rc, stdout, _ = run_bw(["get", "item", name])
    if rc != 0 or not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def bw_get_totp(item_id: str) -> str | None:
    """Fetch TOTP for an item. Returns the 6-digit code or None."""
    rc, stdout, stderr = run_bw(["get", "totp", item_id])
    if rc != 0:
        return None
    # bw get totp can return the code directly or with whitespace
    return stdout.strip() if stdout else None


def bw_list_items(search: str) -> list[dict[str, Any]]:
    """List items matching a search string. Returns list of parsed items."""
    rc, stdout, _ = run_bw(["list", "items", "--search", search])
    if rc != 0 or not stdout:
        return []
    try:
        items = json.loads(stdout)
        return items if isinstance(items, list) else []
    except json.JSONDecodeError:
        return []


def extract_field(item: dict[str, Any], field: str) -> tuple[bool, str]:
    """Extract a named field from a BW item. Returns (found, value)."""
    if field == "password":
        val = item.get("login", {}).get("password", "")
        return bool(val), val
    if field == "username":
        val = item.get("login", {}).get("username", "")
        return True, val  # username can be empty, but the field exists
    if field == "notes":
        val = item.get("notes", "")
        return True, val
    if field == "totp":
        item_id = item.get("id", "")
        if not item_id:
            return False, ""
        totp = bw_get_totp(item_id)
        return totp is not None, totp or ""
    if field == "ssh_private_key":
        val = item.get("sshKey", {}).get("privateKey", "")
        return bool(val), val
    if field == "ssh_public_key":
        val = item.get("sshKey", {}).get("publicKey", "")
        return bool(val), val
    if field.startswith("custom:"):
        custom_name = field[len("custom:"):]
        for f in item.get("fields", []):
            if f.get("name") == custom_name:
                val = f.get("value", "")
                return True, val
        return False, ""
    # Unknown field — try as a login field name
    val = item.get("login", {}).get(field, "")
    if val:
        return True, val
    # Try top-level field
    val = item.get(field, "")
    if val:
        return True, val
    return False, ""


def main() -> None:
    module_args: dict[str, Any] = {}
    # Manual arg parsing (no ansible-core dependency available at module runtime)
    # Ansible passes args as a JSON file path via ANSIBLE_MODULE_ARGS or via stdin
    args_file = os.environ.get("ANSIBLE_MODULE_ARGS_FILE")
    if args_file:
        with open(args_file) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    args = json.loads(raw) if raw.strip() else {}

    item_name = args.get("item", "")
    field = args.get("field", "password")
    search = args.get("search", "")
    list_mode = args.get("list_mode", False)

    # ── List mode ──
    if list_mode:
        if not search:
            print(json.dumps({
                "found": False,
                "value": "",
                "reason": "search_required",
                "items": [],
            }))
            sys.exit(0)

        status = bw_status()
        if status in ("missing", "unauthenticated", "unknown"):
            print(json.dumps({
                "found": False,
                "value": "",
                "reason": f"bw_{status}",
                "items": [],
            }))
            sys.exit(0)
        if status == "locked":
            print(json.dumps({
                "found": False,
                "value": "",
                "reason": "vault_locked",
                "items": [],
            }))
            sys.exit(0)

        items = bw_list_items(search)
        if not items:
            print(json.dumps({
                "found": False,
                "value": "",
                "reason": "item_not_found",
                "items": [],
            }))
            sys.exit(0)

        print(json.dumps({
            "found": True,
            "value": "",
            "reason": "",
            "items": items,
        }))
        sys.exit(0)

    # ── Single item mode ──
    if not item_name:
        print(json.dumps({
            "found": False,
            "value": "",
            "reason": "item_required",
        }))
        sys.exit(0)

    status = bw_status()
    if status in ("missing", "unauthenticated", "unknown"):
        print(json.dumps({
            "found": False,
            "value": "",
            "reason": f"bw_{status}",
        }))
        sys.exit(0)
    if status == "locked":
        print(json.dumps({
            "found": False,
            "value": "",
            "reason": "vault_locked",
        }))
        sys.exit(0)

    item = bw_get_item(item_name)
    if item is None:
        print(json.dumps({
            "found": False,
            "value": "",
            "reason": "item_not_found",
        }))
        sys.exit(0)

    found, value = extract_field(item, field)
    if not found:
        print(json.dumps({
            "found": False,
            "value": "",
            "reason": "field_not_found",
        }))
        sys.exit(0)

    print(json.dumps({
        "found": True,
        "value": value,
        "reason": "",
    }))


if __name__ == "__main__":
    main()
