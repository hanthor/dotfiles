#!/usr/bin/env python3
"""Root-only integration smoke: real osquery, loopback listener and enabled unit.

Uses an isolated temporary baseline; never accepts changes to the fleet baseline.
The temporary unit is enabled but deliberately never started.
"""
from pathlib import Path
import json
import os
import socket
import subprocess
import tempfile
import uuid


REPORTER = "/opt/fleet-osquery/fleet-osquery"


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=240).stdout


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: this smoke briefly enables a temporary system unit.")
    name = "fleet-osquery-smoke-" + uuid.uuid4().hex + ".service"
    unit = Path("/etc/systemd/system") / name
    with tempfile.TemporaryDirectory(prefix="fleet-osquery-smoke-") as directory:
        state = Path(directory) / "state"
        args = [REPORTER, "--state-dir", str(state)]

        def report():
            return json.loads(command(*args, "report", "--json"))

        def listener(rows, port):
            return any(row["address"] == "127.0.0.1" and row["port"] == str(port)
                       and row["protocol"] == "6" for row in rows)

        command(*args, "baseline", "--if-missing")
        baseline = (state / "baseline.json").read_bytes()
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            unit.write_text("[Unit]\nDescription=Temporary osquery smoke (never started)\n"
                            "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
                            "[Install]\nWantedBy=multi-user.target\n")
            command("systemctl", "enable", name)
            for _ in range(2):
                sample = report()
                assert sample["status"] == "drift"
                assert listener(sample["changes"]["listening_ports"]["added"], port)
                assert any(row["name"] == name for row in sample["changes"]["startup_services"]["added"])
                assert (state / "baseline.json").read_bytes() == baseline
            command(*args, "baseline", "--if-missing")
            assert (state / "baseline.json").read_bytes() == baseline
            print("PASS: real TCP listener and enabled, never-started unit detected; drift stays pending")

            # Only the throwaway baseline simulates an earlier kernel. Current
            # kernel data still comes from the real osquery kernel_info table.
            old = json.loads(baseline)
            kernel = next(row for row in old["rows"]["system_versions"] if row["component"] == "kernel")
            current_kernel = kernel["version"]
            kernel["version"] = "smoke-previous-kernel"
            (state / "baseline.json").write_text(json.dumps(old))
            versions = report()["changes"]["system_versions"]
            assert {"component": "kernel", "version": current_kernel} in versions["added"]
            assert {"component": "kernel", "version": "smoke-previous-kernel"} in versions["removed"]
            print("PASS: synthetic prior kernel compared against real current kernel")

            command(*args, "baseline", "--accept")
            accepted = report()
            assert not listener(accepted["changes"]["listening_ports"]["added"], port)
            assert not any(row["name"] == name for row in accepted["changes"]["startup_services"]["added"])
            sock.close()
            command("systemctl", "disable", name)
            removed = report()
            assert listener(removed["changes"]["listening_ports"]["removed"], port)
            assert any(row["name"] == name for row in removed["changes"]["startup_services"]["removed"])
            print("PASS: explicit acceptance clears fixture drift; subsequent removal is detected")
        finally:
            sock.close()
            subprocess.run(["systemctl", "disable", name], check=False, capture_output=True, timeout=30)
            unit.unlink(missing_ok=True)
            command("systemctl", "daemon-reload")
    print("PASS: temporary unit and private smoke state removed; fleet baseline untouched")


if __name__ == "__main__":
    main()
