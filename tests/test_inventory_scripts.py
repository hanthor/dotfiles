import shutil
import subprocess
import sys

import pytest
import yaml

from conftest import REPO


@pytest.fixture
def inv(tmp_path):
    p = tmp_path / "inventory.yml"
    shutil.copy(REPO / "inventory.yml", p)
    (tmp_path / "host_vars").mkdir()
    return p


def run(script, *args):
    return subprocess.run([sys.executable, str(REPO / "scripts" / script), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


def load(p):
    return yaml.safe_load(p.read_text())["all"]


@pytest.mark.parametrize("group", ["desktop", "server", "test_fleet"])
def test_register_adds_host_and_group(inv, group):
    r = run("register-machine.py", "newbox", group, inv)
    assert r.returncode == 0, r.stderr
    data = load(inv)
    assert data["hosts"]["newbox"] == {"ansible_host": "localhost", "ansible_connection": "local"}
    assert "newbox" in data["children"][group]["hosts"]
    others = [g for g, v in data["children"].items() if g != group and "newbox" in (v.get("hosts") or {})]
    assert others == []


def test_register_idempotent(inv):
    run("register-machine.py", "newbox", "desktop", inv)
    once = inv.read_text()
    r = run("register-machine.py", "newbox", "desktop", inv)
    assert r.returncode == 0 and "already" in r.stdout
    assert inv.read_text() == once


def test_register_existing_host_is_noop(inv):
    before = inv.read_text()
    assert run("register-machine.py", "kerala", "server", inv).returncode == 0
    assert inv.read_text() == before


def test_purge_removes_host(inv):
    hv = inv.parent / "host_vars" / "newbox.yml"
    before = inv.read_text()
    run("register-machine.py", "newbox", "desktop", inv)
    hv.write_text("---\n")
    r = run("purge-machine.py", "newbox", inv)
    assert r.returncode == 0, r.stderr
    assert inv.read_text() == before
    assert not hv.exists()


def test_purge_existing_host_keeps_neighbours(inv):
    r = run("purge-machine.py", "test-fleet-fedora", inv)
    assert r.returncode == 0, r.stderr
    data = load(inv)
    assert "test-fleet-fedora" not in data["hosts"]
    assert set(data["children"]["test_fleet"]["hosts"]) == {"test-fleet-node2"}
    assert data["hosts"]["test-fleet-node2"]["ansible_port"] == 22026
    assert set(data["children"]["vps"]["hosts"]) == {"matrix", "telengana"}


def test_purge_missing_host_fails_and_is_idempotent(inv):
    run("purge-machine.py", "kanpur", inv)
    after = inv.read_text()
    r = run("purge-machine.py", "kanpur", inv)
    assert r.returncode == 1 and "not found" in r.stdout
    assert inv.read_text() == after


def test_register_unknown_type_fails_without_writing(inv):
    before = inv.read_text()
    r = run("register-machine.py", "newbox", "laptop", inv)
    assert r.returncode == 1
    assert inv.read_text() == before


@pytest.mark.parametrize("group", ["vps", "desktop", "termux_hosts"])
def test_purge_group_name_never_drops_the_group(inv, group):
    # Regression: purging `vps` used to delete the whole group, silently
    # un-excluding the retired VPSes from apply-all.
    before = inv.read_text()
    r = run("purge-machine.py", group, inv)
    assert r.returncode == 1
    assert inv.read_text() == before
