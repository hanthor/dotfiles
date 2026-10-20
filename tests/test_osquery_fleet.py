import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import subprocess
import sys

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "scripts"))
spec = importlib.util.spec_from_file_location("osquery_fleet", REPO / "scripts/osquery-fleet.py")
fleet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fleet)
NOW = datetime.now(timezone.utc)


def inventory(hosts, **groups):
    result = {"_meta": {"hostvars": hosts}, "all": {"hosts": list(hosts)}}
    result.update({group: {"hosts": members} for group, members in groups.items()})
    return result


def peers(*names):
    return {"Peer": {str(i): {"Online": True, "DNSName": f"{name}.tail.ts.net.",
                                 "HostName": "localhost"}
                     for i, name in enumerate(names)}}


def report(age=timedelta(0), drift=False):
    changes = {category: {"added": [], "removed": []} for category in fleet.ROW_FIELDS}
    counts = {category: {"baseline": 1, "current": 1, "added": 0, "removed": 0}
              for category in fleet.ROW_FIELDS}
    if drift:
        changes["listening_ports"]["added"] = [
            {"address": "0.0.0.0", "port": "2222", "protocol": "6", "path": "/usr/sbin/sshd"}]
        counts["listening_ports"].update(current=2, added=1)
    return {"schema_version": 1, "host": "actual-os-hostname", "collected_at": (NOW - age).isoformat(),
            "baseline_at": (NOW - timedelta(days=1)).isoformat(),
            "status": "drift" if drift else "ok", "changes": changes, "counts": counts}


def by_host(overview):
    return {item["inventory_host"]: item for item in overview["hosts"]}


def test_offline_missing_invalid_and_stale_are_distinct(monkeypatch):
    inv = inventory({name: {} for name in ("offline", "missing", "invalid", "stale", "healthy")})
    calls = []

    def read(command, label):
        target = command[-2]
        calls.append(target)
        if target == "missing":
            raise ValueError("cached report read failed (exit 1)")
        if target == "invalid":
            return {"schema_version": 99}
        return report(age=timedelta(minutes=31) if target == "stale" else timedelta(0))

    monkeypatch.setattr(fleet, "command_json", read)
    overview = fleet.collect_fleet(inv, peers("missing", "invalid", "stale", "healthy"),
                                   identities={"controller"}, now=NOW)
    got = by_host(overview)
    assert {name: item["status"] for name, item in got.items()} == {
        "offline": "offline", "missing": "error", "invalid": "error", "stale": "stale", "healthy": "ok"}
    assert "offline" not in calls
    assert overview["coverage"]["error"] == 2
    assert "report" not in got["invalid"]
    assert got["healthy"]["report"]["host"] == "actual-os-hostname"


def test_alias_uses_magicdns_online_name_not_ambiguous_hostname(monkeypatch):
    inv = inventory({"phone-vm": {"tailnet_name": "mumbai", "ansible_host": "100.86.202.86"}})
    calls = []
    monkeypatch.setattr(fleet, "command_json", lambda command, label: calls.append(command) or report())
    online = peers("mumbai")
    online["Peer"]["0"]["HostName"] = "not-the-inventory-alias"
    overview = fleet.collect_fleet(inv, online, identities={"controller"}, now=NOW)
    assert overview["coverage"]["ok"] == 1
    assert calls[0][-2] == "100.86.202.86"


@pytest.mark.parametrize("variables,target", [
    ({"ansible_connection": "local", "ansible_host": "localhost"}, "goa"),
    ({"ansible_connection": "ansible.builtin.local", "tailnet_name": "real-vm"}, "real-vm"),
    ({"ansible_host": "LOCALHOST."}, "goa"),
    ({"ansible_host": "127.0.1.1"}, "goa"),
    ({"ansible_host": "::1"}, "goa"),
])
def test_other_local_alias_is_reached_over_ssh(variables, target):
    command = fleet.report_command("goa", variables, {"punjab"})
    assert command[0] == "ssh"
    assert command[-2:] == [target, "sudo -n cat /var/lib/fleet-osquery/report.json"]
    assert "BatchMode=yes" in command
    assert "StrictHostKeyChecking=yes" in command


def test_local_collection_only_for_actual_self_even_without_tailscale(monkeypatch):
    inv = inventory({"punjab": {"ansible_host": "100.78.73.8", "ansible_connection": "ssh"}})
    calls = []
    monkeypatch.setattr(fleet, "command_json", lambda command, label: calls.append(command) or report())
    got = fleet.collect_fleet(inv, {}, identities={"punjab"}, now=NOW, discovery_error="Tailscale failed")
    assert got["coverage"]["ok"] == 1
    assert calls == [["sudo", "-n", "cat", "/var/lib/fleet-osquery/report.json"]]


def test_tailscale_failure_is_error_not_offline(monkeypatch):
    monkeypatch.setattr(fleet, "command_json", lambda *a: pytest.fail("must not read hosts without discovery"))
    got = fleet.collect_fleet(inventory({"goa": {}}), {}, identities={"punjab"}, now=NOW,
                              discovery_error="Tailscale failed")
    assert got["coverage"]["error"] == 1
    assert got["coverage"]["offline"] == 0


def test_effective_user_port_and_safe_targets():
    command = fleet.report_command("mumbai", {"ansible_host": "100.86.202.86",
                                             "ansible_user": "james", "ansible_port": 2222}, {"punjab"})
    assert command[command.index("-l") + 1] == "james"
    assert command[command.index("-p") + 1] == "2222"
    assert command[-3:] == ["--", "100.86.202.86", "sudo -n cat /var/lib/fleet-osquery/report.json"]


@pytest.mark.parametrize("variables", [
    {"ansible_host": "-oProxyCommand=touch /tmp/pwned"},
    {"ansible_host": "host;touch /tmp/pwned"},
    {"ansible_user": "root -oProxyCommand=bad"},
    {"ansible_port": "22;echo bad"},
    {"ansible_port": 0},
    {"ansible_port": True},
    {"tailnet_name": "localhost", "ansible_connection": "local"},
])
def test_unsafe_connection_variables_are_rejected(variables):
    with pytest.raises(ValueError):
        fleet.report_command("remote", variables, {"controller"})


def test_exclusions_and_unsupported_never_read_even_when_explicitly_selected(monkeypatch):
    inv = inventory({"matrix": {}, "telengana": {}, "lab": {}, "nested-lab": {}, "termux": {},
                     "kerala": {"osquery_supported": False}},
                    vps=["matrix", "telengana"], test_fleet=["lab"], termux_hosts=["termux"])
    inv["test_fleet"]["children"] = ["nested"]
    inv["nested"] = {"hosts": ["nested-lab"]}
    monkeypatch.setattr(fleet, "command_json", lambda *a: pytest.fail("excluded hosts must not be contacted"))
    got = fleet.collect_fleet(inv, peers(*inv["_meta"]["hostvars"]),
                              selected=list(inv["_meta"]["hostvars"]), identities={"controller"}, now=NOW)
    assert got["coverage"]["excluded"] == 4
    assert got["coverage"]["unsupported"] == 2
    assert "Termux" in by_host(got)["termux"]["reason"]


def test_retired_hosts_stay_excluded_without_group_metadata(monkeypatch):
    monkeypatch.setattr(fleet, "command_json", lambda *a: pytest.fail("retired hosts must never be contacted"))
    got = fleet.collect_fleet(inventory({"matrix": {}, "telengana": {}}), peers("matrix", "telengana"),
                              identities={"controller"}, now=NOW)
    assert got["coverage"]["excluded"] == 2


@pytest.mark.parametrize("age,expected", [(timedelta(minutes=30), "ok"),
                                          (timedelta(minutes=30, microseconds=1), "stale")])
def test_freshness_boundary(age, expected):
    assert fleet.validate_report(report(age=age), NOW) == expected


@pytest.mark.parametrize("value", ["bad", "2026-10-20T10:00:00", "2026-10-20T10:00:00+02:00", None])
def test_bad_timestamps_rejected(value):
    sample = report()
    sample["collected_at"] = value
    with pytest.raises(ValueError, match="timestamp"):
        fleet.validate_report(sample, NOW)


def test_report_refreshed_during_collection_is_not_future_dated(monkeypatch):
    started = NOW
    finished = NOW + timedelta(seconds=2)
    moments = iter((started, finished))

    class Clock:
        @staticmethod
        def now(tz):
            return next(moments)

    monkeypatch.setattr(fleet, "datetime", Clock)
    # Parsing must still use the real ISO8601 parser.
    Clock.fromisoformat = datetime.fromisoformat
    fresh = report()
    fresh["collected_at"] = (NOW + timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(fleet, "command_json", lambda *args: fresh)
    got = fleet.collect_fleet(inventory({"remote": {}}), peers("remote"), identities={"controller"})
    assert got["coverage"]["ok"] == 1


def test_future_and_baseline_after_sample_rejected():
    for key in ("collected_at", "baseline_at"):
        sample = report()
        sample[key] = (NOW + timedelta(seconds=1)).isoformat()
        with pytest.raises(ValueError, match="timestamp"):
            fleet.validate_report(sample, NOW)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(schema_version=True),
    lambda r: r.update(schema_version=2),
    lambda r: r.pop("baseline_at"),
    lambda r: r.update(host=""),
    lambda r: r.update(status="ok"),
    lambda r: r["changes"].pop("system_versions"),
    lambda r: r["counts"]["listening_ports"].update(added=0),
    lambda r: r["counts"]["listening_ports"].update(current=99),
    lambda r: r["counts"]["startup_services"].update(baseline=True),
    lambda r: r["changes"]["listening_ports"]["added"][0].update(cmdline="secret"),
    lambda r: r["changes"]["listening_ports"]["added"][0].update(port=2222),
])
def test_schema_inconsistencies_and_nonstable_rows_rejected(mutate):
    sample = report(drift=True)
    mutate(sample)
    with pytest.raises(ValueError):
        fleet.validate_report(sample, NOW)


def test_duplicate_or_cancelled_changes_rejected():
    sample = report(drift=True)
    rows = sample["changes"]["listening_ports"]
    rows["added"].append(copy.deepcopy(rows["added"][0]))
    sample["counts"]["listening_ports"].update(added=2, current=3)
    with pytest.raises(ValueError, match="duplicate"):
        fleet.validate_report(sample, NOW)
    sample = report(drift=True)
    sample["changes"]["listening_ports"]["removed"] = copy.deepcopy(sample["changes"]["listening_ports"]["added"])
    sample["counts"]["listening_ports"].update(removed=1, current=1)
    with pytest.raises(ValueError, match="same row"):
        fleet.validate_report(sample, NOW)


@pytest.mark.parametrize("failure", ["ssh", "missing", "invalid-json", "timeout"])
def test_read_failure_never_returns_report_or_private_diagnostics(monkeypatch, failure):
    def run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 30, output="private-token")
        return subprocess.CompletedProcess(command, 1 if failure in ("ssh", "missing") else 0,
                                           "private-token", "credentials=private-token")

    monkeypatch.setattr(fleet.subprocess, "run", run)
    got = fleet.collect_fleet(inventory({"remote": {}}), peers("remote"), identities={"controller"}, now=NOW)
    assert got["coverage"]["error"] == 1
    assert "private-token" not in json.dumps(got)
    assert "report" not in got["hosts"][0]


@pytest.mark.parametrize("drift,age,expected", [
    (True, timedelta(0), 0), (False, timedelta(minutes=31), 1),
])
def test_cli_drift_is_normal_but_stale_fails_with_offline_coverage(monkeypatch, capsys, drift, age, expected):
    monkeypatch.setattr(fleet, "load_inventory", lambda path: inventory({"remote": {}, "offline": {}}))
    monkeypatch.setattr(fleet, "load_status", lambda: peers("remote"))
    monkeypatch.setattr(fleet, "self_names", lambda: {"controller"})
    monkeypatch.setattr(fleet, "command_json", lambda *a: report(age=age, drift=drift))
    assert fleet.main(["--json"]) == expected
    got = json.loads(capsys.readouterr().out)
    assert got["coverage"]["offline"] == 1
    assert got["coverage"]["drift" if drift else "stale"] == 1


def test_repeatable_host_selection_limits_collection(monkeypatch, capsys):
    monkeypatch.setattr(fleet, "load_inventory", lambda path: inventory({"one": {}, "two": {}, "skip": {}}))
    monkeypatch.setattr(fleet, "load_status", lambda: peers("one", "two", "skip"))
    monkeypatch.setattr(fleet, "self_names", lambda: {"controller"})
    calls = []
    monkeypatch.setattr(fleet, "command_json", lambda command, label: calls.append(command[-2]) or report())
    assert fleet.main(["--host", "one", "--host", "two", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert set(calls) == {"one", "two"}
    assert set(by_host(got)) == {"one", "two"}


def test_text_overview_includes_version_service_and_listener_details(capsys):
    sample = report(drift=True)
    for category, row in (
        ("startup_services", {"name": "sshd.service", "unit_file_state": "enabled",
                              "fragment_path": "/usr/lib/systemd/system/sshd.service"}),
        ("system_versions", {"component": "kernel", "version": "6.18.1"}),
    ):
        sample["changes"][category]["added"].append(row)
        sample["counts"][category].update(added=1, current=2)
    fleet.print_overview({"coverage": {state: int(state == "drift") for state in fleet.STATUSES},
                          "hosts": [{"inventory_host": "alias", "status": "drift", "report": sample}]})
    output = capsys.readouterr().out
    assert "Coverage:" in output
    assert '"alias" (hostname "actual-os-hostname")' in output
    assert "2222" in output and "/usr/sbin/sshd" in output
    assert "sshd.service" in output and "6.18.1" in output


@pytest.mark.parametrize("status", [
    {}, {"BackendState": "Stopped", "Peer": {}},
    {"BackendState": "Running", "Peer": []},
    {"BackendState": "Running", "Peer": {"one": {"Online": "false"}}},
    {"BackendState": "Running", "Peer": {"one": {"Online": True, "DNSName": 42}}},
])
def test_invalid_discovery_metadata_rejected(monkeypatch, status):
    monkeypatch.setattr(fleet, "command_json", lambda *a, **kw: status)
    with pytest.raises(ValueError):
        fleet.load_status()


def test_running_tailnet_without_peers_is_valid_offline_coverage(monkeypatch):
    monkeypatch.setattr(fleet, "command_json", lambda *a, **kw: {"BackendState": "Running", "Peer": None})
    status = fleet.load_status()
    got = fleet.collect_fleet(inventory({"remote": {}}), status, identities={"controller"}, now=NOW)
    assert got["coverage"]["offline"] == 1
    assert got["coverage"]["error"] == 0


def test_unknown_host_and_invalid_effective_inventory_fail_closed():
    with pytest.raises(ValueError, match="not in the inventory"):
        fleet.collect_fleet(inventory({"known": {}}), peers("known"), selected=["unknown"], identities={"controller"})
    with pytest.raises(ValueError, match="effective host variables"):
        fleet.inventory_hosts({"all": {"hosts": ["known"]}})
