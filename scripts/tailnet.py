#!/usr/bin/env python3
"""Tailnet hygiene: garbage-collect stale devices, rename them to the inventory, align inventory.yml.

  tailnet.py audit                  what is wrong (exit 1 when anything is)
  tailnet.py gc [--apply]           delete duplicates and stale test VMs
  tailnet.py rename [--apply]       rename live devices to their inventory (tailnet) name
  tailnet.py fix-inventory [--apply]  ansible_host IPs / tailnet_name overrides follow the live devices
  tailnet.py sync [--apply]         gc, then rename, then fix-inventory (planned as one sequence)
  tailnet.py release NAME           delete offline devices called NAME or NAME-<n> (run before joining)

Everything is a dry run unless --apply. Reads come from the Tailscale API when a credential is
available (TS_OAUTH_CLIENT_SECRET, or Bitwarden item `tailscale-apikey`), otherwise from the local
`tailscale status --json` (read-only: enough for audit and for planning). Writes need the API.

Names: a device's tailnet name is its first MagicDNS label. An inventory host's *intended* name is
its `tailnet_name` var, else the inventory name; a `tailnet_name` of the form <host>-<n> is the
auto-suffix Tailscale adds when a stale device still holds <host>, so it is treated as "wants <host>".
Retired hosts (the `vps` group), home cluster nodes, devices shared in from other tailnets,
and Kubernetes proxies of unverifiable cluster ownership are never deleted.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory_parser import parse_host_vars, parse_inventory, set_host_var  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTORY = os.environ.get("DOTFILES_INVENTORY", os.path.join(REPO, "inventory.yml"))
API = "https://api.tailscale.com/api/v2"
BW_ITEM = "tailscale-apikey"
TEST_VM = re.compile(r"(^gate-|^repro-|^tuna-v1-preflight-|.-vm$)")
IP100 = re.compile(r"^100\.\d+\.\d+\.\d+$")
DEVICE_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
# The home Talos cluster is offline temporarily, not retired.
HOME_CLUSTER_NAMES = {"bihar", "karnataka"}


class AuthError(Exception):
    pass


# ── devices ────────────────────────────────────────────────────────────────

def _name(value):
    if not isinstance(value, str):
        return ""
    labels = value.lower().rstrip(".").split(".")
    return labels[0] if labels and all(DNS_LABEL.fullmatch(label) for label in labels) else ""


def _identifier(value):
    return value if isinstance(value, str) and DEVICE_ID.fullmatch(value) else ""


def device_errors(devs):
    """List unverifiable records before constructing a plan or performing any write."""
    errors, ids = [], set()
    for i, d in enumerate(devs, 1):
        reasons = []
        if not _identifier(d["id"]):
            reasons.append("invalid or missing device ID")
        elif d["id"] in ids:
            reasons.append("duplicate device ID")
        else:
            ids.add(d["id"])
        if not _name(d["name"]):
            reasons.append("invalid or missing device name")
        if type(d["online"]) is not bool:
            reasons.append("presence is missing or not boolean")
        if reasons:
            errors.append(f"device {i} ({d['name'] or 'unknown'}): {', '.join(reasons)}")
    return errors

def _ts(value):
    if not value or value.startswith("0001-"):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def devices_from_status(status, now):
    """Normalise `tailscale status --json` (peers + self)."""
    suffix = (status.get("MagicDNSSuffix") or (status.get("CurrentTailnet") or {}).get("MagicDNSSuffix") or "").strip(".")
    out = []
    entries = [(p, False) for p in (status.get("Peer") or {}).values()]
    if status.get("Self"):
        entries.append((status["Self"], True))
    for p, is_self in entries:
        dns = (p.get("DNSName") or "").rstrip(".")
        name = _name(dns or p.get("HostName", ""))
        online = p.get("Online")
        online = online if type(online) is bool else None
        seen = now if online else _ts(p.get("LastSeen"))
        out.append({
            "id": _identifier(p.get("ID")),
            "name": name,
            "ip": (p.get("TailscaleIPs") or [""])[0],
            "tags": list(p.get("Tags") or []),
            "online": online,
            "seen": seen,
            "self": is_self,
            "foreign": bool(suffix and dns and not dns.endswith("." + suffix)),
        })
    return out


def devices_from_api(payload, now, self_ids=()):
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise ValueError("API response has no device list")
    out = []
    for d in payload["devices"]:
        if not isinstance(d, dict):
            raise ValueError("API response contains an invalid device")
        addrs = d.get("addresses") or [""]
        online = d.get("connectedToControl")
        online = online if type(online) is bool else None
        device_id = _identifier(d.get("nodeId") if "nodeId" in d else d.get("id"))
        out.append({
            "id": device_id,
            "name": _name(d.get("name")),
            "ip": next((a for a in addrs if IP100.match(a)), addrs[0]),
            "tags": list(d.get("tags") or []),
            "online": online,
            "seen": now if online else _ts(d.get("lastSeen")),
            "self": device_id in self_ids,
            "foreign": bool(d.get("isExternal")),
        })
    return out


# ── API client ─────────────────────────────────────────────────────────────

def _secret():
    secret = os.environ.get("TS_OAUTH_CLIENT_SECRET", "")
    if secret:
        return secret
    session = os.environ.get("BW_SESSION", "")
    if not session and os.path.exists("/tmp/bw_session"):
        session = open("/tmp/bw_session").read().strip()
    if not session:
        return ""
    env = {**os.environ, "BW_SESSION": session}
    try:
        r = subprocess.run(["bw", "get", "password", BW_ITEM], capture_output=True, text=True, env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


class Api:
    def __init__(self, secret):
        self.secret = secret
        self.auth = None

    def _request(self, method, path, data=None, form=None, auth=None):
        headers = {"Authorization": auth} if auth else {}
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(API + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AuthError("Tailscale rejected the credential (HTTP 401)") from None
            raise
        return json.loads(raw) if raw else {}

    def _bearer(self):
        if self.auth:
            return self.auth
        if self.secret.startswith("tskey-client-"):
            cid = self.secret.split("-")[2]
            tok = self._request("POST", "/oauth/token", form={"client_id": cid, "client_secret": self.secret})
            self.auth = "Bearer " + tok["access_token"]
        else:  # classic API key: HTTP basic with an empty password
            import base64
            self.auth = "Basic " + base64.b64encode((self.secret + ":").encode()).decode()
        return self.auth

    def list_devices(self):
        return self._request("GET", "/tailnet/-/devices?fields=all", auth=self._bearer())

    def delete(self, device_id):
        self._request("DELETE", f"/device/{device_id}", auth=self._bearer())

    def rename(self, device_id, name):
        self._request("POST", f"/device/{device_id}/name", data={"name": name}, auth=self._bearer())


AUTH_HELP = (
    "Create an OAuth client at https://login.tailscale.com/admin/settings/oauth (scopes: devices:core write, "
    "auth_keys write; tag tag:fleet), then `just seed-tailnet-oauth` to store its secret in Bitwarden item "
    f"`{BW_ITEM}` (or export TS_OAUTH_CLIENT_SECRET)."
)


def load_devices(source, now):
    """(devices, api_or_None, source_label). Falls back from the API to local status for reads."""
    if source in ("auto", "api"):
        secret = _secret()
        if secret:
            api = Api(secret)
            try:
                me = local_status().get("Self", {}).get("ID")
                return devices_from_api(api.list_devices(), now, {me} if me else ()), api, "api"
            except AuthError as e:
                if source == "api":
                    raise
                print(f"note: {e}\n      {AUTH_HELP}\n      falling back to local `tailscale status` (read-only)", file=sys.stderr)
        elif source == "api":
            raise AuthError("no Tailscale credential found. " + AUTH_HELP)
    return devices_from_status(local_status(), now), None, "local"


def local_status():
    try:
        return json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


# ── planning (pure) ────────────────────────────────────────────────────────

def load_inventory(text):
    all_hosts, vps = parse_inventory(text)
    hv = parse_host_vars(text)
    hosts = {}
    for h in sorted(all_hosts - vps):
        v = hv.get(h, {})
        tn = v.get("tailnet_name", "").lower()
        intended = h.lower() if (not tn or re.fullmatch(rf"{re.escape(h.lower())}-\d+", tn)) else tn
        hosts[h] = {"intended": intended, "override": tn, "ansible_host": v.get("ansible_host", "")}
    return hosts


def retired_names(text):
    _, vps = parse_inventory(text)
    variables = parse_host_vars(text)
    names = {host.lower() for host in vps}
    names.update(variables.get(host, {}).get("tailnet_name", "").lower() for host in vps)
    names.discard("")
    # A configured auto-suffixed alias also reserves its unsuffixed base.
    names.update(re.sub(r"(?:-\d+)+$", "", name) for name in tuple(names))
    return names


def is_retired(name, names):
    return any(re.fullmatch(rf"{re.escape(base)}(?:-\d+)*", name) for base in names)


def _family(devs, name):
    return [d for d in devs if not d["foreign"] and (d["name"] == name or re.fullmatch(rf"{re.escape(name)}-\d+", d["name"]))]


def _primary(family):
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return max(family, key=lambda d: (d["online"], d["seen"] or epoch))


def plan_gc(devs, hosts, now, days=14, k8s_days=None, retired=(), notes=None):
    """Plan deletes; report k8s proxies whose cluster ownership cannot be verified."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    actions, doomed = [], set()
    if notes is None:
        notes = []

    def add(d, reason):
        if (d["id"] not in doomed and _identifier(d["id"]) and d["online"] is False
                and not d["self"] and not d["foreign"] and not is_retired(d["name"], retired)):
            doomed.add(d["id"])
            if any(t.startswith("tag:k8s") for t in d["tags"]):
                notes.append(f"{d['name']}: k8s proxy ownership unverifiable; not deleting ({reason})")
            else:
                actions.append({"op": "delete", "id": d["id"], "name": d["name"], "ip": d["ip"], "reason": reason})

    inventory_names = {h["intended"] for h in hosts.values()}
    for h in hosts.values():
        fam = _family(devs, h["intended"])
        if len(fam) > 1:
            primary = _primary(fam)
            for d in fam:
                if d is not primary and (d["seen"] or epoch) < (primary["seen"] or epoch):
                    add(d, f"duplicate of {primary['name']}")
    for d in devs:
        old = d["seen"] is None or now - d["seen"] > timedelta(days=days)
        if TEST_VM.search(d["name"]) and d["name"] not in inventory_names and old:
            add(d, f"stale test VM (offline > {days}d)")
        if k8s_days is not None and any(t.startswith("tag:k8s") for t in d["tags"]):
            if d["seen"] is None or now - d["seen"] > timedelta(days=k8s_days):
                add(d, f"stale k8s proxy (offline > {k8s_days}d)")
    return actions


def apply_to_devices(devs, actions):
    """The device list as it will be after `actions` (gc deletes, renames)."""
    out = [dict(d) for d in devs]
    for a in actions:
        if a["op"] == "delete":
            out = [d for d in out if d["id"] != a["id"]]
        elif a["op"] == "rename":
            for d in out:
                if d["id"] == a["id"]:
                    d["name"] = a["to"]
    return out


def plan_rename(devs, hosts):
    actions, conflicts = [], []
    for host, h in hosts.items():
        fam = _family(devs, h["intended"])
        if not fam:
            continue
        primary = _primary(fam)
        if primary["name"] == h["intended"]:
            continue
        holder = [d for d in devs if d["name"] == h["intended"] and not d["foreign"]]
        if holder:
            conflicts.append(f"{host}: wants {h['intended']} but it is held by {holder[0]['ip']} ({'online' if holder[0]['online'] else 'offline'})")
            continue
        actions.append({"op": "rename", "id": primary["id"], "from": primary["name"], "to": h["intended"], "host": host})
    return actions, conflicts


def plan_inventory(devs, hosts):
    """Inventory edits that make inventory.yml agree with the devices as they are in `devs`."""
    actions, notes = [], []
    for host, h in hosts.items():
        fam = _family(devs, h["intended"])
        if not fam:
            if h["ansible_host"] not in ("localhost", "127.0.0.1"):
                notes.append(f"{host}: no tailnet device named {h['intended']}")
            continue
        primary = _primary(fam)
        if primary["name"] != h["intended"]:
            continue  # not renamed yet: leave the override and IP alone
        if IP100.match(h["ansible_host"]) and primary["ip"] and h["ansible_host"] != primary["ip"]:
            actions.append({"op": "inventory", "host": host, "key": "ansible_host", "from": h["ansible_host"], "to": primary["ip"]})
        if h["override"] and h["intended"] == host.lower():
            actions.append({"op": "inventory", "host": host, "key": "tailnet_name", "from": h["override"], "to": None})
    return actions, notes


def build_plan(devs, hosts, now, days=14, k8s_days=None, retired=()):
    gc_notes = []
    gc = plan_gc(devs, hosts, now, days, k8s_days, retired, gc_notes)
    after_gc = apply_to_devices(devs, gc)
    renames, conflicts = plan_rename(after_gc, hosts)
    after_rename = apply_to_devices(after_gc, renames)
    inv, notes = plan_inventory(after_rename, hosts)
    return {"gc": gc, "rename": renames, "inventory": inv, "conflicts": conflicts,
            "notes": gc_notes + notes, "gc_notes": gc_notes}


def apply_inventory(text, actions):
    for a in actions:
        text = set_host_var(text, a["host"], a["key"], a["to"])
    return text


# ── CLI ────────────────────────────────────────────────────────────────────

def show(plan, kinds):
    n = 0
    for a in plan["gc"] if "gc" in kinds else []:
        print(f"delete     {a['name']:<40} {a['ip']:<16} {a['reason']}")
        n += 1
    for a in plan["rename"] if "rename" in kinds else []:
        print(f"rename     {a['from']} -> {a['to']}  (inventory host {a['host']})")
        n += 1
    for a in plan["inventory"] if "inventory" in kinds else []:
        to = "(remove)" if a["to"] is None else a["to"]
        print(f"inventory  {a['host']}.{a['key']}: {a['from']} -> {to}")
        n += 1
    for c in plan["conflicts"]:
        print(f"conflict   {c}")
    for c in plan["notes"]:
        print(f"note       {c}")
    return n


def run_writes(api, plan, kinds, apply_inv):
    failed = 0
    actions = (plan["gc"] if "gc" in kinds else []) + (plan["rename"] if "rename" in kinds else [])
    if any(not _identifier(a["id"]) for a in actions):
        print("error: plan contains an invalid device ID; no changes made", file=sys.stderr)
        return 1
    for a in plan["gc"] if "gc" in kinds else []:
        try:
            api.delete(a["id"])
            print(f"deleted    {a['name']}")
        except (urllib.error.URLError, AuthError) as e:
            print(f"FAILED     delete {a['name']}: {e}")
            failed += 1
    for a in plan["rename"] if "rename" in kinds else []:
        try:
            api.rename(a["id"], a["to"])
            print(f"renamed    {a['from']} -> {a['to']}")
        except (urllib.error.URLError, AuthError) as e:
            print(f"FAILED     rename {a['from']}: {e}")
            failed += 1
    if "inventory" in kinds and plan["inventory"] and failed == 0:
        apply_inv()
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["audit", "gc", "rename", "fix-inventory", "sync", "release"])
    ap.add_argument("name", nargs="?", help="device name (release)")
    ap.add_argument("--apply", action="store_true", help="perform the changes (default: dry run)")
    ap.add_argument("--days", type=int, default=14, help="test VMs offline longer than this are stale (default 14)")
    ap.add_argument("--k8s-days", type=int, default=None, help="report tag:k8s proxies offline longer than this (never delete them)")
    ap.add_argument("--source", choices=["auto", "api", "local"], default="auto")
    args = ap.parse_args(argv)

    if args.cmd == "release" and not args.name:
        ap.error("release needs a device name")
    now = datetime.now(timezone.utc)
    try:
        with open(INVENTORY) as f:
            text = f.read()
        hosts = load_inventory(text)
        retired = retired_names(text)
        protected = retired | HOME_CLUSTER_NAMES
        if args.cmd == "release":
            name = args.name.lower()
            if not DNS_LABEL.fullmatch(name):
                print("error: release needs a valid device name", file=sys.stderr)
                return 2
            if is_retired(name, retired):
                print(f"error: refusing to release retired VPS name {name}", file=sys.stderr)
                return 2
            if is_retired(name, HOME_CLUSTER_NAMES):
                print(f"error: refusing to release home cluster name {name}", file=sys.stderr)
                return 2
        else:
            for host, h in hosts.items():
                intended = h["intended"]
                # A protected home node can be inventoried under its own name;
                # it remains protected from release and garbage collection.
                reserved = retired | (HOME_CLUSTER_NAMES - {host.lower()})
                if is_retired(intended, reserved) or any(is_retired(r, {intended}) for r in reserved):
                    print(f"error: {host} conflicts with a protected name", file=sys.stderr)
                    return 2
        devs, api, label = load_devices("api" if (args.apply or args.cmd == "release") else args.source, now)
    except AuthError as e:
        print(f"error: {e}\n       {AUTH_HELP}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    errors = device_errors(devs)
    if errors:
        for error in errors:
            print(f"unverifiable: {error}", file=sys.stderr)
        print("no plan or changes: device data is incomplete or invalid", file=sys.stderr)
        return 2 if args.apply or args.cmd == "release" else 1

    if args.cmd == "release":
        victims = [d for d in _family(devs, name) if not d["self"] and d["online"] is False
                   and not is_retired(d["name"], protected)]
        if any(any(t.startswith("tag:k8s") for t in d["tags"]) for d in victims):
            print("error: k8s proxy ownership unverifiable; no devices released", file=sys.stderr)
            return 2
        failed = 0
        for d in victims:
            try:
                api.delete(d["id"])
                print(f"deleted    {d['name']} ({d['ip']})")
            except (urllib.error.URLError, AuthError) as e:
                print(f"FAILED     delete {d['name']}: {e}", file=sys.stderr)
                failed += 1
        return 1 if failed else 0

    plan = build_plan(devs, hosts, now, args.days, args.k8s_days, protected)
    kinds = {"audit": {"gc", "rename", "inventory"}, "sync": {"gc", "rename", "inventory"}, "gc": {"gc"},
             "rename": {"rename"}, "fix-inventory": {"inventory"}}[args.cmd]
    if args.cmd == "gc":  # gc alone: later steps are irrelevant
        plan["conflicts"], plan["notes"] = [], plan["gc_notes"]
    if args.cmd == "fix-inventory":  # alone it must reflect the live state, not a simulated one
        inv, notes = plan_inventory(devs, hosts)
        plan = {"gc": [], "rename": [], "inventory": inv, "conflicts": [], "notes": notes}
    if args.cmd == "rename":
        renames, conflicts = plan_rename(devs, hosts)
        plan = {"gc": [], "rename": renames, "inventory": [], "conflicts": conflicts, "notes": []}

    print(f"# {len(devs)} devices from {label}, {len(hosts)} inventory hosts", file=sys.stderr)
    count = show(plan, kinds)
    if not count and not plan["conflicts"] and not plan["notes"]:
        print("tailnet and inventory agree")
    if not args.apply or args.cmd == "audit":
        return 1 if count or plan["conflicts"] or plan["notes"] else 0
    if "gc" in kinds and plan.get("gc_notes"):
        print("error: k8s proxy ownership unverifiable; no changes made", file=sys.stderr)
        return 2

    def write_inventory():
        with open(INVENTORY, "w") as f:
            f.write(apply_inventory(text, plan["inventory"]))
        print(f"updated    {INVENTORY}")

    if args.cmd == "fix-inventory":
        write_inventory()
        return 0
    if args.cmd == "sync" and plan["inventory"] and (plan["gc"] or plan["rename"]):
        # Inventory edits assume the renames happened; re-plan from the live state afterwards.
        failed = run_writes(api, plan, {"gc", "rename"}, lambda: None)
        if failed:
            return 1
        try:
            devs, _, _ = load_devices("api", datetime.now(timezone.utc))
        except (AuthError, urllib.error.URLError, ValueError) as e:
            print(f"error: unable to re-read devices: {e}", file=sys.stderr)
            return 2
        errors = device_errors(devs)
        if errors:
            for error in errors:
                print(f"unverifiable: {error}", file=sys.stderr)
            print("inventory not updated: device data is incomplete or invalid", file=sys.stderr)
            return 2
        inv, _ = plan_inventory(devs, hosts)
        plan["inventory"] = inv
        if inv:
            write_inventory()
        return 0
    return 1 if run_writes(api, plan, kinds, write_inventory) else 0


if __name__ == "__main__":
    sys.exit(main())
