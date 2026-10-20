import copy
import fcntl
import importlib.util
import json
import os
import select
import socket
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import REPO


SCRIPT = REPO / "roles" / "osquery" / "files" / "fleet-osquery.py"


@pytest.fixture
def reporter():
    spec = importlib.util.spec_from_file_location("fleet_osquery_host", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(tmp_path, monkeypatch, reporter):
    samples = {
        "listening_ports": [
            {"address": "127.0.0.1", "port": "22", "protocol": "6", "path": "/usr/sbin/sshd"},
        ],
        "startup_services": [
            {"name": "sshd.service", "unit_file_state": "enabled", "fragment_path": "/usr/lib/systemd/system/sshd.service"},
        ],
        "system_versions": [
            {"component": "kernel", "version": "6.12.1"},
            {"component": "os", "version": "Fedora 43"},
            {"component": "osquery", "version": "5.23.1"},
        ],
    }
    config = tmp_path / "osquery.conf"
    config.write_text(json.dumps({"schedule": {
        "fleet_" + category: {"query": f"SELECT '{category}'", "interval": 900}
        for category in samples
    }}))
    state = tmp_path / "private"
    calls = []

    def run_osquery(command, **kwargs):
        assert command[:2] == ["/fake/osqueryi", "--json"]
        assert kwargs["timeout"] > 0
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.PIPE
        category = command[2].split("'")[1]
        calls.append(category)
        return subprocess.CompletedProcess(command, 0, json.dumps(samples[category]), "")

    monkeypatch.setattr(reporter.subprocess, "run", run_osquery)

    def invoke(*args):
        return reporter.main([
            "--config", str(config), "--state-dir", str(state),
            "--osqueryi", "/fake/osqueryi", *args,
        ])

    def read(name="report.json"):
        return json.loads((state / name).read_text())

    return SimpleNamespace(module=reporter, samples=samples, config=config, state=state,
                           calls=calls, invoke=invoke, read=read)


def test_reports_added_removed_ports_and_keeps_drift_pending(host, capsys):
    assert host.invoke("baseline", "--if-missing") == 0
    baseline = (host.state / "baseline.json").read_bytes()
    removed = copy.deepcopy(host.samples["listening_ports"][0])
    added = {"address": "0.0.0.0", "port": "8080", "protocol": "6", "path": "/usr/bin/example"}
    host.samples["listening_ports"] = [added]
    for _ in range(2):
        capsys.readouterr()
        assert host.invoke("report", "--json") == 0
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "drift"
        assert report["host"] == socket.gethostname()
        assert report["changes"]["listening_ports"] == {"added": [added], "removed": [removed]}
        assert report["counts"]["listening_ports"] == {"baseline": 1, "current": 1, "added": 1, "removed": 1}
        assert host.read() == report
        assert (host.state / "baseline.json").read_bytes() == baseline


def test_enabled_startup_service_addition_and_removal(host):
    assert host.invoke("baseline", "--if-missing") == 0
    old = copy.deepcopy(host.samples["startup_services"][0])
    new = {"name": "backup.service", "unit_file_state": "enabled-runtime",
           "fragment_path": "/run/systemd/system/backup.service"}
    host.samples["startup_services"] = [new]
    assert host.invoke("report") == 0
    assert host.read()["changes"]["startup_services"] == {"added": [new], "removed": [old]}
    host.samples["startup_services"] = []
    assert host.invoke("report") == 0
    assert host.read()["changes"]["startup_services"] == {"added": [], "removed": [old]}


@pytest.mark.parametrize("component", ["kernel", "os", "osquery"])
def test_each_version_transition_is_drift(host, component):
    assert host.invoke("baseline", "--if-missing") == 0
    row = next(row for row in host.samples["system_versions"] if row["component"] == component)
    old = copy.deepcopy(row)
    row["version"] += ".new"
    assert host.invoke("report") == 0
    assert host.read()["changes"]["system_versions"] == {"added": [row], "removed": [old]}


def test_if_missing_never_collects_or_overwrites_existing_baseline_and_accept_resets(host):
    assert host.invoke("baseline", "--if-missing") == 0
    baseline = (host.state / "baseline.json").read_bytes()
    host.samples["listening_ports"] = []
    calls = len(host.calls)
    assert host.invoke("baseline", "--if-missing") == 0
    assert len(host.calls) == calls
    assert (host.state / "baseline.json").read_bytes() == baseline
    assert host.invoke("report") == 0
    assert host.read()["status"] == "drift"
    assert host.invoke("baseline", "--accept") == 0
    assert host.invoke("report") == 0
    assert host.read()["status"] == "ok"
    assert all(not change["added"] and not change["removed"] for change in host.read()["changes"].values())


def test_baseline_requires_explicit_policy(host):
    with pytest.raises(SystemExit) as error:
        host.invoke("baseline")
    assert error.value.code == 2
    assert not host.state.exists()


def test_row_sets_are_deterministic_and_numeric_ports_are_canonical(host):
    extra = {"address": "::", "port": 443, "protocol": 6, "path": "/usr/bin/web"}
    host.samples["listening_ports"] += [extra, copy.deepcopy(extra)]
    assert host.invoke("baseline", "--if-missing") == 0
    rows = host.read("baseline.json")["rows"]["listening_ports"]
    assert len(rows) == 2
    host.samples["listening_ports"].reverse()
    host.samples["listening_ports"][0]["port"] = "00443"
    assert host.invoke("report") == 0
    assert host.read()["status"] == "ok"
    assert host.read()["counts"]["listening_ports"]["current"] == 2


@pytest.mark.parametrize("output,returncode", [
    ("not json", 0),
    ("{}", 0),
    ("null", 0),
    ('[{"address":"a","address":"b","port":"22","protocol":"6","path":"/x"}]', 0),
    ('[{"address":"a","port":"22","protocol":"6","path":"/x","pid":"123"}]', 0),
    ('[{"address":"a","port":true,"protocol":"6","path":"/x"}]', 0),
    ('[{"address":"a","port":"65536","protocol":"6","path":"/x"}]', 0),
    ('[{"address":"a","port":"22","protocol":"256","path":"/x"}]', 0),
    ('[{"address":"a","port":"22","protocol":"6","path":null}]', 0),
    ('[{"address":"a","port":NaN,"protocol":"6","path":"/x"}]', 0),
    ("[]", 7),
])
def test_failed_or_corrupt_collection_preserves_previous_good_state(host, monkeypatch, capsys, output, returncode):
    assert host.invoke("baseline", "--if-missing") == 0
    assert host.invoke("report") == 0
    before = {name: (host.state / name).read_bytes() for name in ("baseline.json", "report.json")}
    monkeypatch.setattr(host.module.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, returncode, output, "private diagnostic"))
    capsys.readouterr()
    assert host.invoke("report", "--json") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "fleet-osquery:" in captured.err
    assert "private diagnostic" not in captured.err
    for name, content in before.items():
        assert (host.state / name).read_bytes() == content
    assert host.invoke("baseline", "--accept") == 1
    assert (host.state / "baseline.json").read_bytes() == before["baseline.json"]


@pytest.mark.parametrize("failure", ["timeout", "missing_binary"])
def test_subprocess_failures_are_errors_without_new_report(host, monkeypatch, failure):
    assert host.invoke("baseline", "--if-missing") == 0

    def fail(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        raise FileNotFoundError("missing osquery")

    monkeypatch.setattr(host.module.subprocess, "run", fail)
    assert host.invoke("report") == 1
    assert not (host.state / "report.json").exists()


@pytest.mark.parametrize("category,rows", [
    ("system_versions", []),
    ("system_versions", [{"component": "kernel", "version": "1"}]),
    ("startup_services", [{"name": "x.service", "unit_file_state": "disabled", "fragment_path": "/x"}]),
])
def test_incomplete_versions_and_unenabled_services_are_not_healthy(host, category, rows):
    assert host.invoke("baseline", "--if-missing") == 0
    host.samples[category] = rows
    assert host.invoke("report") == 1
    assert not (host.state / "report.json").exists()


@pytest.mark.parametrize("contents", ["null", "[]", "{broken", '{"schema_version":1}',
                                         '{"schema_version":1,"schema_version":1}'])
def test_corrupt_baseline_cannot_be_silently_initialized_or_reported_healthy(host, contents):
    host.state.mkdir(mode=0o700)
    (host.state / "baseline.json").write_text(contents)
    for command in (("baseline", "--if-missing"), ("report", "--json")):
        assert host.invoke(*command) == 1
        assert (host.state / "baseline.json").read_text() == contents
    assert not host.calls
    assert host.invoke("baseline", "--accept") == 0
    assert host.invoke("report") == 0
    assert host.read()["status"] == "ok"


def test_missing_baseline_does_not_autoaccept(host):
    assert host.invoke("report", "--json") == 1
    assert not host.calls
    assert not (host.state / "baseline.json").exists()
    assert not (host.state / "report.json").exists()


def test_baseline_from_another_host_requires_explicit_acceptance(host):
    assert host.invoke("baseline", "--if-missing") == 0
    baseline = host.read("baseline.json")
    baseline["host"] = "not-this-host"
    (host.state / "baseline.json").write_text(json.dumps(baseline))
    assert host.invoke("report") == 1
    assert host.invoke("baseline", "--if-missing") == 1
    assert host.invoke("baseline", "--accept") == 0


@pytest.mark.parametrize("query", ["DELETE FROM processes", "SELECT 1; SELECT 2", "PRAGMA table_info(processes)"])
def test_only_configured_single_select_queries_execute(host, query):
    config = json.loads(host.config.read_text())
    config["schedule"]["fleet_startup_services"]["query"] = query
    host.config.write_text(json.dumps(config))
    assert host.invoke("baseline", "--if-missing") == 1
    assert not host.calls
    assert not (host.state / "baseline.json").exists()


def test_state_files_are_private_from_first_creation_and_repaired_if_relaxed(host):
    old_umask = os.umask(0)
    try:
        assert host.invoke("baseline", "--if-missing") == 0
        assert host.invoke("report") == 0
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(host.state.stat().st_mode) == 0o700
    for name in (".lock", "baseline.json", "report.json"):
        assert stat.S_IMODE((host.state / name).stat().st_mode) == 0o600
        (host.state / name).chmod(0o666)
    host.state.chmod(0o777)
    assert host.invoke("baseline", "--if-missing") == 0
    assert stat.S_IMODE(host.state.stat().st_mode) == 0o700
    for name in (".lock", "baseline.json", "report.json"):
        assert stat.S_IMODE((host.state / name).stat().st_mode) == 0o600


@pytest.mark.parametrize("name", [".lock", "baseline.json", "report.json"])
def test_state_symlinks_are_rejected_without_touching_target(host, tmp_path, name):
    target = tmp_path / "outside"
    target.write_text("do not replace")
    target.chmod(0o644)
    host.state.mkdir(mode=0o700)
    (host.state / name).symlink_to(target)
    assert host.invoke("baseline", "--accept") == 1
    assert target.read_text() == "do not replace"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert not host.calls


def test_symlink_state_directory_is_rejected(host, tmp_path):
    target = tmp_path / "outside"
    target.mkdir(mode=0o755)
    host.state.symlink_to(target, target_is_directory=True)
    assert host.invoke("baseline", "--if-missing") == 1
    assert not list(target.iterdir())
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_hardlinked_state_is_rejected_without_chmodding_target(host, tmp_path):
    target = tmp_path / "outside"
    target.write_text("do not replace")
    target.chmod(0o644)
    host.state.mkdir(mode=0o700)
    os.link(target, host.state / "baseline.json")
    assert host.invoke("baseline", "--accept") == 1
    assert target.read_text() == "do not replace"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_atomic_write_failure_preserves_previous_report_and_removes_private_temporary(host, monkeypatch):
    assert host.invoke("baseline", "--if-missing") == 0
    assert host.invoke("report") == 0
    old_report = (host.state / "report.json").read_bytes()
    host.samples["listening_ports"] = []

    def fail_replace(source, destination, **kwargs):
        info = os.stat(source, dir_fd=kwargs["src_dir_fd"])
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert destination == "report.json"
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr(host.module.os, "replace", fail_replace)
    assert host.invoke("report", "--json") == 1
    assert (host.state / "report.json").read_bytes() == old_report
    assert sorted(path.name for path in host.state.iterdir()) == [".lock", "baseline.json", "report.json"]


def test_cli_waits_for_existing_state_lock_before_collecting(host, tmp_path):
    assert host.invoke("baseline", "--if-missing") == 0
    old_baseline = (host.state / "baseline.json").read_bytes()
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps(host.samples))
    marker = tmp_path / "collection-started"
    fake = tmp_path / "osqueryi"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).touch()\n"
        f"rows = json.loads(pathlib.Path({str(samples)!r}).read_text())\n"
        "print(json.dumps(rows[sys.argv[-1].split(\"'\")[1]]))\n"
    )
    fake.chmod(0o700)
    wrapper = (
        "import importlib.util,sys; "
        f"s=importlib.util.spec_from_file_location('host_reporter', {str(SCRIPT)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print('ready',flush=True); sys.exit(m.main(sys.argv[1:]))"
    )
    with (host.state / ".lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        process = subprocess.Popen([
            sys.executable, "-u", "-c", wrapper,
            "--config", str(host.config), "--state-dir", str(host.state),
            "--osqueryi", str(fake), "baseline", "--accept",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert select.select([process.stdout], [], [], 5)[0]
            assert process.stdout.readline().strip() == "ready"
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
            assert not marker.exists()
            assert (host.state / "baseline.json").read_bytes() == old_baseline
            fcntl.flock(lock, fcntl.LOCK_UN)
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            assert "baseline accepted" in stdout
            assert marker.exists()
            assert host.read("baseline.json")["rows"]["system_versions"]
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
