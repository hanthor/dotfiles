#!/usr/bin/env python3
"""Collect stable osquery identities and compare them with an explicit baseline."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time
import uuid


CATEGORIES = {
    "listening_ports": ("address", "port", "protocol", "path"),
    "startup_services": ("name", "unit_file_state", "fragment_path"),
    "system_versions": ("component", "version"),
}
QUERY_TIMEOUT = 30
LOCK_TIMEOUT = 120


class MonitoringError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MonitoringError("duplicate JSON object key")
        result[key] = value
    return result


def reject_constant(value):
    raise MonitoringError("non-finite JSON value")


def decode_json(text):
    try:
        return json.loads(text, object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise MonitoringError("invalid JSON") from exc


def normalize_rows(category, rows):
    if not isinstance(rows, list):
        raise MonitoringError(f"{category}: expected an array of rows")
    fields = CATEGORIES[category]
    normalized = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(fields):
            raise MonitoringError(f"{category}: unexpected row columns")
        values = []
        for field in fields:
            value = row[field]
            if category == "listening_ports" and field in ("port", "protocol"):
                if type(value) not in (str, int) or not re.fullmatch(r"[0-9]+", str(value)):
                    raise MonitoringError(f"{category}: invalid {field}")
                digits = str(value).lstrip("0") or "0"
                if len(digits) > 5:
                    raise MonitoringError(f"{category}: invalid {field}")
                number = int(digits)
                if not 0 <= number <= (65535 if field == "port" else 255):
                    raise MonitoringError(f"{category}: invalid {field}")
                value = str(number)
            if not isinstance(value, str) or "\x00" in value:
                raise MonitoringError(f"{category}: invalid {field}")
            if not value and field not in ("path", "fragment_path"):
                raise MonitoringError(f"{category}: empty {field}")
            values.append(value)
        if category == "startup_services" and row["unit_file_state"] not in (
                "enabled", "enabled-runtime"):
            raise MonitoringError("startup_services: expected an enabled service")
        normalized.add(tuple(values))
    if category == "system_versions":
        components = [row[0] for row in normalized]
        if sorted(components) != ["kernel", "os", "osquery"]:
            raise MonitoringError("system_versions: expected one kernel, os and osquery version")
    return [dict(zip(fields, values)) for values in sorted(normalized)]


def collect(config_path, osqueryi):
    try:
        config = decode_json(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise MonitoringError("cannot read osquery configuration") from exc
    if not isinstance(config, dict) or not isinstance(config.get("schedule"), dict):
        raise MonitoringError("osquery configuration has no schedule")
    queries = {}
    for category in CATEGORIES:
        entry = config["schedule"].get("fleet_" + category)
        query = entry.get("query") if isinstance(entry, dict) else None
        if not isinstance(query, str):
            raise MonitoringError(f"{category}: missing configured query")
        query = query.strip().removesuffix(";").strip()
        if not re.match(r"(?i)^SELECT\b", query) or ";" in query:
            raise MonitoringError(f"{category}: expected a single SELECT query")
        queries[category] = query
    rows = {}
    for category, query in queries.items():
        try:
            result = subprocess.run(
                [osqueryi, "--json", query], check=False,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", timeout=QUERY_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise MonitoringError(f"{category}: osquery timed out") from exc
        except (OSError, UnicodeError) as exc:
            raise MonitoringError(f"{category}: cannot execute osquery") from exc
        if result.returncode != 0:
            # Do not echo arbitrary subprocess output into logs.
            raise MonitoringError(f"{category}: osquery exited {result.returncode}")
        rows[category] = normalize_rows(category, decode_json(result.stdout))
    return rows


def check_private_file(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
        raise MonitoringError("state files must be singly-linked regular files owned by the caller")
    os.fchmod(fd, 0o600)


@contextmanager
def locked_state(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        if os.fstat(directory).st_uid != os.geteuid():
            raise MonitoringError("state directory must be owned by the caller")
        os.fchmod(directory, 0o700)
        lock = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=directory)
        check_private_file(lock)
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MonitoringError("timed out waiting for state lock")
                time.sleep(0.05)
        # Existing files must also be private, including when collection fails.
        for name in ("baseline.json", "report.json"):
            fd = open_state_file(directory, name)
            if fd is not None:
                os.close(fd)
        yield directory
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def open_state_file(directory, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        check_private_file(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_state(directory, name):
    fd = open_state_file(directory, name)
    if fd is None:
        return None
    with os.fdopen(fd, encoding="utf-8") as stream:
        value = decode_json(stream.read())
    if not isinstance(value, dict):
        raise MonitoringError("invalid state document")
    return value


def write_state(directory, name, value):
    # A fresh, private inode is fully flushed before replacing the previous state.
    temporary = "." + name + "." + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def validate_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise MonitoringError("invalid baseline timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise MonitoringError("invalid baseline timestamp") from exc


def validate_baseline(value, host):
    if not isinstance(value, dict) or set(value) != {"schema_version", "host", "collected_at", "rows"}:
        raise MonitoringError("invalid baseline schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise MonitoringError("unsupported baseline schema")
    if value["host"] != host:
        raise MonitoringError("baseline belongs to another hostname")
    validate_timestamp(value["collected_at"])
    if not isinstance(value["rows"], dict) or set(value["rows"]) != set(CATEGORIES):
        raise MonitoringError("invalid baseline categories")
    return {category: normalize_rows(category, value["rows"][category]) for category in CATEGORIES}


def make_report(host, baseline, previous, current):
    changes = {}
    counts = {}
    for category, fields in CATEGORIES.items():
        old = {tuple(row[field] for field in fields) for row in previous[category]}
        new = {tuple(row[field] for field in fields) for row in current[category]}
        changes[category] = {
            "added": [dict(zip(fields, row)) for row in sorted(new - old)],
            "removed": [dict(zip(fields, row)) for row in sorted(old - new)],
        }
        counts[category] = {"baseline": len(old), "current": len(new),
                            "added": len(new - old), "removed": len(old - new)}
    return {
        "schema_version": 1, "host": host, "collected_at": utc_now(),
        "baseline_at": baseline["collected_at"],
        "status": "drift" if any(c["added"] or c["removed"] for c in counts.values()) else "ok",
        "changes": changes, "counts": counts,
    }


def render_text(report):
    lines = [f"{report['host']}: {report['status']} (baseline {report['baseline_at']})"]
    for category, changes in report["changes"].items():
        counts = report["counts"][category]
        lines.append(f"{category}: {counts['current']} current, +{counts['added']} -{counts['removed']}")
        for direction, symbol in (("added", "+"), ("removed", "-")):
            for row in changes[direction]:
                lines.append(f"  {symbol} " + json.dumps(row, sort_keys=True))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/osquery/osquery.conf")
    parser.add_argument("--state-dir", default="/var/lib/fleet-osquery")
    parser.add_argument("--osqueryi", default="/opt/osquery/bin/osqueryi")
    commands = parser.add_subparsers(dest="command", required=True)
    baseline_parser = commands.add_parser("baseline", help="explicitly initialize or accept a baseline")
    policy = baseline_parser.add_mutually_exclusive_group(required=True)
    policy.add_argument("--if-missing", action="store_true")
    policy.add_argument("--accept", action="store_true")
    report_parser = commands.add_parser("report", help="collect and compare without accepting changes")
    report_parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    try:
        host = socket.gethostname()
        with locked_state(args.state_dir) as directory:
            if args.command == "baseline" and args.accept:
                # Explicit acceptance can repair corrupt baseline contents, not unsafe files.
                baseline = None
            else:
                baseline = read_state(directory, "baseline.json")
                if baseline is not None:
                    previous = validate_baseline(baseline, host)
            if args.command == "baseline" and args.if_missing and baseline is not None:
                print(f"{host}: existing baseline retained")
                return 0
            if args.command == "report" and baseline is None:
                raise MonitoringError("baseline missing; run baseline --if-missing first")
            current = collect(args.config, args.osqueryi)
            if args.command == "baseline":
                write_state(directory, "baseline.json", {
                    "schema_version": 1, "host": host, "collected_at": utc_now(), "rows": current,
                })
                print(f"{host}: baseline accepted")
            else:
                report = make_report(host, baseline, previous, current)
                write_state(directory, "report.json", report)
                print(json.dumps(report, sort_keys=True) if args.json_output else render_text(report))
        return 0
    except (MonitoringError, OSError, UnicodeError) as exc:
        print(f"fleet-osquery: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
