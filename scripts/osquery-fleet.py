#!/usr/bin/env python3
"""Read private cached osquery reports through existing authenticated SSH access.

Offline, unsupported and excluded hosts remain visible in coverage. Drift is a
monitoring result, while stale data and collection failures make the CLI fail.
Optional snapshots are private and atomic. Inventory diagnostics never expose
host variable values.
"""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

from online_hosts import online_peers
sys.path.append(str(Path(__file__).resolve().parent.parent / "units"))
from osquery_native_inventory import load_inventory

INVENTORY = Path(__file__).resolve().parent.parent / "inventory.yml"
REPORT_PATH = "/var/lib/fleet-osquery/report.json"
MAX_AGE = timedelta(minutes=30)
ROW_FIELDS = {
    "listening_ports": {"address", "port", "protocol", "path"},
    "startup_services": {"name", "unit_file_state", "fragment_path"},
    "system_versions": {"component", "version"},
}
STATUSES = ("ok", "drift", "offline", "stale", "error", "unsupported", "excluded")


def command_json(command, label, timeout=30):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ValueError(f"{label} could not run") from None
    if result.returncode:
        raise ValueError(f"{label} failed (exit {result.returncode})")
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError(f"{label} returned invalid JSON") from None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must return a JSON object")
    return value




def load_status():
    status = command_json(["tailscale", "status", "--json"], "Tailscale", timeout=10)
    if status.get("BackendState") != "Running":
        raise ValueError("Tailscale is not running")
    peers = status.get("Peer")
    if peers is None:
        peers = {}
    if not isinstance(peers, dict) or any(
            not isinstance(p, dict) or type(p.get("Online", False)) is not bool or
            any(p.get(key) is not None and not isinstance(p[key], str) for key in ("DNSName", "HostName"))
            for p in peers.values()):
        raise ValueError("Tailscale returned invalid peer metadata")
    return status


def group_hosts(inventory, name, visiting=None):
    visiting = set() if visiting is None else visiting
    if name in visiting:
        raise ValueError("inventory contains a group cycle")
    group = inventory.get(name, {})
    if not isinstance(group, dict):
        raise ValueError("inventory contains an invalid group")
    hosts, children = group.get("hosts", []), group.get("children", [])
    if not isinstance(hosts, list) or not isinstance(children, list):
        raise ValueError("inventory group members must be lists")
    if any(not isinstance(h, str) or not h for h in hosts + children):
        raise ValueError("inventory contains an invalid member name")
    members = set(hosts)
    for child in children:
        members |= group_hosts(inventory, child, visiting | {name})
    return members


def inventory_hosts(inventory):
    meta = inventory.get("_meta", {})
    if not isinstance(meta, dict) or not isinstance(meta.get("hostvars"), dict):
        raise ValueError("inventory is missing effective host variables")
    variables = meta.get("hostvars", {})
    if any(not isinstance(h, str) or not isinstance(v, dict) for h, v in variables.items()):
        raise ValueError("inventory contains invalid host variables")
    hosts = group_hosts(inventory, "all") | set(variables)
    if not hosts:
        raise ValueError("inventory contains no fleet hosts")
    return {host: variables.get(host, {}) for host in hosts}


def self_names():
    names = {os.uname().nodename.lower()}
    try:
        machine = Path("/etc/dotfiles-machine").read_text(encoding="utf-8").strip().lower()
        if machine:
            names.add(machine)
    except OSError:
        pass
    return names | {name.split(".")[0] for name in names}


def safe_target(value):
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError("invalid SSH target")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if len(value) > 253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9.])?", value):
        raise ValueError("invalid SSH target")
    return value


def loopback_target(value):
    if not isinstance(value, str):
        return False
    if value.lower().rstrip(".") in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def report_command(alias, variables, identities):
    tailnet = variables.get("tailnet_name", alias)
    if not isinstance(tailnet, str):
        raise ValueError("invalid tailnet name")
    if alias.lower() in identities or tailnet.lower() in identities:
        return ["sudo", "-n", "cat", REPORT_PATH]
    target = variables.get("ansible_host", tailnet)
    # Local Ansible aliases refer to their own machine, not this controller.
    if variables.get("ansible_connection") in ("local", "ansible.builtin.local") or loopback_target(target):
        target = tailnet
    target = safe_target(target)
    if loopback_target(target):
        raise ValueError("non-self SSH target resolves to a loopback name")
    port = variables.get("ansible_port", variables.get("ansible_ssh_port", 22))
    if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("invalid SSH port")
    command = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1", "-p", str(port)]
    user = variables.get("ansible_user", variables.get("ansible_ssh_user"))
    if user is not None:
        if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", user):
            raise ValueError("invalid SSH user")
        command += ["-l", user]
    return command + ["--", target, "sudo -n cat " + REPORT_PATH]


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("report timestamp must be a UTC ISO8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("report timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("report timestamp must be UTC")
    return parsed


def validate_report(report, now):
    fields = {"schema_version", "host", "collected_at", "baseline_at", "status", "changes", "counts"}
    if not isinstance(report, dict) or set(report) != fields:
        raise ValueError("report has invalid fields")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise ValueError("unsupported report schema version")
    if not isinstance(report["host"], str) or not report["host"].strip():
        raise ValueError("report hostname is missing")
    collected = timestamp(report["collected_at"])
    baseline = timestamp(report["baseline_at"])
    if collected > now or baseline > collected:
        raise ValueError("report timestamp is in the future or precedes its baseline")
    if report["status"] not in ("ok", "drift"):
        raise ValueError("report status is invalid")
    if any(not isinstance(report[key], dict) or set(report[key]) != set(ROW_FIELDS)
           for key in ("changes", "counts")):
        raise ValueError("report categories are invalid")
    drift = False
    for category, columns in ROW_FIELDS.items():
        changes, counts = report["changes"][category], report["counts"][category]
        if not isinstance(changes, dict) or set(changes) != {"added", "removed"}:
            raise ValueError("report change fields are invalid")
        if not isinstance(counts, dict) or set(counts) != {"baseline", "current", "added", "removed"}:
            raise ValueError("report count fields are invalid")
        if any(type(n) is not int or n < 0 for n in counts.values()):
            raise ValueError("report counts must be nonnegative integers")
        identities = {}
        for direction in ("added", "removed"):
            rows = changes[direction]
            if not isinstance(rows, list) or counts[direction] != len(rows):
                raise ValueError("report row counts are inconsistent")
            identities[direction] = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) != columns or any(
                        not isinstance(value, str) for value in row.values()):
                    raise ValueError("report contains invalid or non-stable row fields")
                if category == "system_versions" and row["component"] not in ("kernel", "os", "osquery"):
                    raise ValueError("report version component is invalid")
                identity = tuple(row[key] for key in sorted(columns))
                if identity in identities[direction]:
                    raise ValueError("report contains duplicate rows")
                identities[direction].add(identity)
            drift |= bool(rows)
        if identities["added"] & identities["removed"]:
            raise ValueError("report adds and removes the same row")
        if (counts["removed"] > counts["baseline"] or
                counts["current"] != counts["baseline"] - counts["removed"] + counts["added"]):
            raise ValueError("report baseline/current counts are inconsistent")
    if report["status"] != ("drift" if drift else "ok"):
        raise ValueError("report status disagrees with changes")
    return "stale" if now - collected > MAX_AGE else report["status"]


def collect_fleet(inventory, status, selected=None, identities=None, now=None, discovery_error=None):
    hosts = inventory_hosts(inventory)
    identities = self_names() if identities is None else {name.lower() for name in identities}
    started_at = datetime.now(timezone.utc) if now is None else now
    selected = set(hosts) if not selected else set(selected)
    if selected - set(hosts):
        raise ValueError("requested host is not in the inventory")
    retired = group_hosts(inventory, "vps") | {"matrix", "telengana"}
    tests = group_hosts(inventory, "test_fleet")
    termux = group_hosts(inventory, "termux_hosts")
    peers = online_peers(status)
    results = []
    for alias in sorted(selected):
        variables = hosts[alias]
        result = {"inventory_host": alias}
        results.append(result)
        if alias in retired | tests:
            result.update(status="excluded", reason="retired vps" if alias in retired else "test_fleet")
            continue
        if alias in termux:
            result.update(status="unsupported", reason="Termux has no supported root/systemd reporter")
            continue
        if variables.get("osquery_supported") is False:
            result.update(status="unsupported", reason="osquery_supported=false in effective inventory")
            continue
        try:
            command = report_command(alias, variables, identities)
            local = command[0] == "sudo"
            tailnet = variables.get("tailnet_name", alias).lower()
            if not local and discovery_error:
                raise ValueError(discovery_error)
            if not local and tailnet not in peers:
                result.update(status="offline", reason="tailnet peer is offline or absent")
                continue
            report = command_json(command, "cached report read")
            state = validate_report(report, now if now is not None else datetime.now(timezone.utc))
            result.update(status=state, report=report)
            if state == "stale":
                result["reason"] = "cached report is older than 30 minutes"
        except ValueError as exc:
            result.update(status="error", reason=str(exc))
    coverage = {state: sum(item["status"] == state for item in results) for state in STATUSES}
    return {"schema_version": 1, "collected_at": started_at.isoformat(), "coverage": coverage,
            "hosts": results}


def print_overview(overview):
    coverage = overview["coverage"]
    print("Coverage: " + ", ".join(f"{state}={coverage[state]}" for state in STATUSES))
    for item in overview["hosts"]:
        label = json.dumps(item["inventory_host"], ensure_ascii=True)
        report = item.get("report")
        if not report:
            print(f"{label}: {item['status']} — {item['reason']}")
            continue
        actual = json.dumps(report["host"], ensure_ascii=True)
        print(f"{label} (hostname {actual}): {item['status']} — sampled {report['collected_at']}")
        if item.get("reason"):
            print(f"  {item['reason']}")
        for category, changes in report["changes"].items():
            print(f"  {category}: +{len(changes['added'])} -{len(changes['removed'])}")
            for direction, marker in (("added", "+"), ("removed", "-")):
                for row in changes[direction]:
                    print(f"    {marker} {json.dumps(row, sort_keys=True, ensure_ascii=True)}")


def write_snapshot(path, snapshot):
    directory = path.parent
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("snapshot directory must be private and owned by the caller")
    fd, temporary = tempfile.mkstemp(prefix=".fleet-osquery-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(snapshot, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default=os.environ.get("DOTFILES_INVENTORY", str(INVENTORY)))
    parser.add_argument("--host", action="append", help="inventory alias (repeatable)")
    parser.add_argument("--json", action="store_true", help="print private report details as JSON")
    parser.add_argument("--output", type=Path, help="atomically save JSON in an existing private directory")
    args = parser.parse_args(argv)
    try:
        inventory = load_inventory(args.inventory)
        try:
            status, discovery_error = load_status(), None
        except ValueError as exc:
            status, discovery_error = {}, str(exc)
        overview = collect_fleet(inventory, status, args.host, discovery_error=discovery_error)
    except ValueError as exc:
        overview = {"schema_version": 1, "collected_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)}
    if args.output is not None:
        try:
            write_snapshot(args.output, overview)
        except (OSError, ValueError):
            print("osquery fleet: cannot write private snapshot", file=sys.stderr)
            return 1
    if "error" in overview:
        if args.json:
            print(json.dumps(overview))
        else:
            print(f"osquery fleet: {overview['error']}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(overview, sort_keys=True))
    elif args.output is not None:
        print("Fleet snapshot saved: " + ", ".join(
            f"{state}={overview['coverage'][state]}" for state in STATUSES))
    else:
        print_overview(overview)
    return int(bool(overview["coverage"]["error"] or overview["coverage"]["stale"]))


if __name__ == "__main__":
    sys.exit(main())
